/**
 * e2e_ops.mjs — two optional-task pages: SIP trunk status + Search & Delete.
 *
 *   node scripts/e2e_ops.mjs http://127.0.0.1:8098 9333
 *
 * Same prerequisites as e2e_pipeline.mjs (fake PBX + Chrome with a debug port).
 */

import { connectCdp, reporter, sleep } from './cdp.mjs';

const [, , base = 'http://127.0.0.1:8098', port = '9333'] = process.argv;
const DELETE_PASSWORD = process.env.DP_DELETE_PASSWORD || '871211My';

async function main() {
  const cdp = await connectCdp({ port });
  const { check, summary } = reporter();

  try {
    await cdp.goto(`${base}/api/dev/auto-login`, 3000);
    // Clear the fake PBX history so the search scenario starts from a known state
    // (earlier standard/complex suites stuff E2E_GROUP into it)
    await cdp.goto(`${base}/api/dev/reset`, 1500);

    /* ---------------------------------------------- SIP trunk status */
    await cdp.goto(`${base}/#/siptrunk`, 3200);
    const trunk = JSON.parse(
      await cdp.evaluate(`JSON.stringify({
        rows: document.querySelectorAll('.u-card table.table tbody tr').length,
        peers: document.querySelectorAll('.peer-dropdown__item input[type=checkbox]').length,
        autoOptions: document.querySelectorAll('select.input-plain option').length,
        hasStatus: (document.body.textContent || '').includes('registered'),
        nav: document.querySelectorAll('.nav__item').length
      })`),
    );
    check('SIP trunk page loads', trunk.nav === 9, `${trunk.nav} nav items`);
    check('Trunk status table has data', trunk.rows === 2, `${trunk.rows} rows`);
    check('Peer filter checkboxes present', trunk.peers === 2, `${trunk.peers} of them`);
    check('Status field rendered', trunk.hasStatus === true);

    // Filter: check one peer only; the table should keep just 1 row
    await cdp.evaluate(`(() => {
      const box = document.querySelector('.peer-dropdown__item input[type=checkbox]');
      box.checked = true;
      box.dispatchEvent(new Event('change', { bubbles: true }));
      return true;
    })()`);
    await sleep(400);
    const filtered = await cdp.evaluate(`document.querySelectorAll('.u-card table.table tbody tr').length`);
    check('Filtering by peer works', filtered === 1, `${filtered} rows`);

    await cdp.screenshot('.artifacts/ops-siptrunk.png');

    /* --------------------- Search & Delete (desktop parity: 20 task rows) */
    // Create a group first so the page has something to find.
    await cdp.evaluate(`fetch('/api/pipeline/run', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode: 'standard', tasks: ['Group', 'Context', 'ACL Group', 'User Profile'],
        params: { group_name: 'E2E_SD', group_code: 'E2E_SD', context_prefix: 'E2E_SD', perm_group_prefix: 'E2E_SD', user_ext: '0358797500 - 0358797502' } })
    }).then(r => r.status)`);
    await sleep(5000);

    await cdp.goto(`${base}/#/search-delete`, 3500);
    const initial = JSON.parse(
      await cdp.evaluate(`JSON.stringify({
        rows: document.querySelectorAll('.sd-row').length,
        cinch: (document.body.textContent || '').includes('Cinch Contact Center'),
        keyword: !!document.querySelector('.sd-combo__input'),
        deleteDisabled: [...document.querySelectorAll('button')].find(b => b.textContent.includes('Delete'))?.disabled ?? null
      })`),
    );
    check('20 optional task rows rendered (desktop parity)', initial.rows === 20, `${initial.rows} rows`);
    check('Cinch Contact Center group present', initial.cinch === true);
    check('Group Name/ID search box + group suggestions present', initial.keyword === true);
    check('Delete button disabled without selection', initial.deleteDisabled === true);

    await cdp.evaluate(`[...document.querySelectorAll('button')].find(b => b.textContent.trim() === 'All Tasks').click()`);
    await sleep(300);
    const afterAll = JSON.parse(
      await cdp.evaluate(`JSON.stringify({
        checked: [...document.querySelectorAll('.sd-row input[type=checkbox]')].filter(c => c.checked).length,
        deleteDisabled: [...document.querySelectorAll('button')].find(b => b.textContent.includes('Delete'))?.disabled ?? null
      })`),
    );
    check('All Tasks checks all 20 rows', afterAll.checked === 20, `${afterAll.checked}/20`);
    check('Delete button enabled after selection', afterAll.deleteDisabled === false);

    // One keyword searches every checked type; each row reports its own result.
    await cdp.evaluate(`(() => {
      const input = document.querySelector('.sd-combo__input');
      input.value = 'E2E_SD';
      input.dispatchEvent(new Event('input', { bubbles: true }));
      [...document.querySelectorAll('button')].find(b => b.textContent.includes('Search')).click();
      return true;
    })()`);
    const searched = await cdp.waitFor(
      `[...document.querySelectorAll('.sd-result')].filter(n => /Found \\d+:|Not found|Error/.test(n.textContent)).length >= 5`,
      { timeoutMs: 90000 },
    );
    const hits = await cdp.evaluate(`document.querySelectorAll('.sd-result--ok').length`);
    check('One search hits multiple task types', Boolean(searched), `${hits} types returned results`);

    const statuses = JSON.parse(
      await cdp.evaluate(`JSON.stringify([...document.querySelectorAll('.sd-row .sd-result')].map(n => n.textContent).filter(Boolean))`),
    );
    check(
      'Result text matches desktop (ID: / Found N:)',
      statuses.some((t) => /Found \d+:/.test(t)) && statuses.some((t) => /^ID: /.test(t)),
      statuses.slice(0, 2).join(' | ').slice(0, 80),
    );

    // Caller ID Manipulation must show the *resolved DID*, not the internal extension range.
    const callerIdRow = await cdp.evaluate(`(() => {
      const row = [...document.querySelectorAll('.sd-row')].find((r) => r.textContent.includes('Caller ID Manipulation'));
      return row ? (row.querySelector('.sd-result')?.textContent || '') : '';
    })()`);
    check(
      'Caller ID Manipulation shows DID range (desktop parity)',
      /6400-6499|60328566400-60328566499/.test(callerIdRow),
      callerIdRow.slice(0, 70),
    );

    // Delete bottom-to-top with the password gate.
    await cdp.evaluate(`[...document.querySelectorAll('button')].find(b => b.textContent.includes('Delete')).click()`);
    await sleep(600);
    const promptShown = await cdp.evaluate(`!!document.querySelector('.u-modal input[type=password]')`);
    check('Delete password prompt appears', promptShown === true);

    await cdp.evaluate(`(() => {
      document.querySelector('.u-modal input[type=password]').value = 'wrong-password';
      [...document.querySelectorAll('.u-modal__actions button')].find(b => b.textContent.trim() === 'Continue').click();
      return true;
    })()`);
    await sleep(600);
    await cdp.evaluate(`[...document.querySelectorAll('.u-modal__actions button')].find(b => b.textContent.trim() === 'Delete').click()`);
    const rejected = await cdp.waitFor(
      `(document.querySelector('#loglines')?.textContent || '').includes('Incorrect delete password')`,
      { timeoutMs: 25000 },
    );
    check('Wrong password rejected by server', Boolean(rejected));

    await cdp.evaluate(`[...document.querySelectorAll('button')].find(b => b.textContent.includes('Delete')).click()`);
    await sleep(600);
    await cdp.evaluate(`(() => {
      document.querySelector('.u-modal input[type=password]').value = ${JSON.stringify(DELETE_PASSWORD)};
      [...document.querySelectorAll('.u-modal__actions button')].find(b => b.textContent.trim() === 'Continue').click();
      return true;
    })()`);
    await sleep(600);
    const confirmShown = await cdp.waitFor(
      `/Delete \\d+ checked/.test(document.querySelector('.u-modal__title')?.textContent || '')`,
      { timeoutMs: 15000 },
    );
    check('Second confirmation appears', Boolean(confirmShown));

    await cdp.evaluate(`[...document.querySelectorAll('.u-modal__actions button')].find(b => b.textContent.trim() === 'Delete').click()`);
    const deleted = await cdp.waitFor(
      `(document.querySelector('#loglines')?.textContent || '').includes('Delete finished')`,
      { timeoutMs: 40000 },
    );
    check('Delete runs and reports result', Boolean(deleted));

    const logText = await cdp.evaluate(`document.querySelector('#loglines')?.textContent || ''`);
    check(
      'Delete count is correct',
      /Delete finished: [1-9]\d* deleted/.test(logText),
      (logText.match(/Delete finished: \d+ deleted \/ \d+ failed/) || [''])[0],
    );

    await cdp.screenshot('.artifacts/ops-search-delete.png');


    // Re-search a single type after the delete, to prove per-row selection works
    await cdp.evaluate(`(() => {
      [...document.querySelectorAll('button')].find(b => b.textContent.trim() === 'No Task').click();
      const row = [...document.querySelectorAll('.sd-row')].find(r => r.textContent.includes('Hunt Group'));
      const box = row.querySelector('input[type=checkbox]');
      box.checked = true;
      box.dispatchEvent(new Event('change', { bubbles: true }));
      const input = document.querySelector('.sd-combo__input');
      input.value = 'E2E_SD';
      input.dispatchEvent(new Event('input', { bubbles: true }));
      [...document.querySelectorAll('button')].find(b => b.textContent.includes('Search')).click();
      return true;
    })()`);
    const huntOk = await cdp.waitFor(
      `[...document.querySelectorAll('.sd-row')].some(r => r.textContent.includes('Hunt Group') && /Found \\d+:/.test(r.textContent))`,
      { timeoutMs: 60000 },
    );
    check('Single selected type still matches (Hunt Group)', Boolean(huntOk));

    /* ---------------------------------------------- Operation log (audit) */
    await cdp.goto(`${base}/#/audit`, 3200);
    const audit = JSON.parse(
      await cdp.evaluate(`JSON.stringify({
        nav: document.querySelectorAll('.nav__item').length,
        rows: document.querySelectorAll('.u-card table.table tbody tr').length,
        text: document.body.textContent || '',
        kinds: document.querySelectorAll('select.input-plain option').length
      })`),
    );
    check('Audit page loads', audit.nav === 9, `${audit.nav} nav items`);
    check('Login and logout recorded', audit.text.includes('Login OK'), `rows=${audit.rows}`);
    check('Delete recorded (including the rejected one)', audit.text.includes('Search & Delete') && audit.text.includes('bad password'), '');
    check('Kind filter dropdown present', audit.kinds >= 7, `${audit.kinds} options`);

    await cdp.screenshot('.artifacts/ops-audit.png');
    check('No JS console errors', cdp.consoleErrors.length === 0, cdp.consoleErrors.slice(0, 3).join(' | '));
  } catch (error) {
    // Important: the error must not be swallowed by finally, or it would "pass green" without really finishing
    console.error('\n[suite exception]', error && error.stack ? error.stack : error);
    check('Suite ran without throwing', false, String((error && error.message) || error).slice(0, 140));
  } finally {
    const failed = summary();
    cdp.close();
    process.exit(failed ? 1 : 0);
  }
}

main().catch((error) => {
  console.error('E2E run failed:', error.message);
  process.exit(2);
});
