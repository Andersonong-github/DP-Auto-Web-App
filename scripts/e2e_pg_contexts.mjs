/**
 * e2e_pg_contexts.mjs — Complex mode "Permission Group → per-Class Context picker".
 *
 *   node scripts/e2e_pg_contexts.mjs http://127.0.0.1:8098 9333
 *
 * Covers the regression this suite was written for:
 *   - every Class row exposes a "Select contexts…" button next to its combo;
 *   - the picker lists the Group's real contexts and keeps the tick order;
 *   - a hand-picked Class disables its combo (the two inputs are mutually exclusive);
 *   - the run sends the picked names in tick order, and a Class left on its combo
 *     still resolves to <prefix>_Internal (it must never end up empty).
 *
 * Prerequisites: dev_preview.py (stateful fake PBX) on --base, Chrome with a debug port.
 */

import { connectCdp, reporter, sleep } from './cdp.mjs';

const [, , base = 'http://127.0.0.1:8098', port = '9333'] = process.argv;

async function main() {
  const cdp = await connectCdp({ port });
  const { check, summary } = reporter();

  try {
    await cdp.goto(`${base}/api/dev/auto-login`, 3000);
    await cdp.goto(`${base}/api/dev/reset`, 1200);
    await cdp.goto(`${base}/#/complex`, 3200);

    /* ---------------------------------------------------------- static structure */
    const rows = JSON.parse(
      await cdp.evaluate(`JSON.stringify({
        rows: document.querySelectorAll('.pg-row').length,
        buttons: [...document.querySelectorAll('.pg-row button')].map(b => b.textContent.trim()),
        combos: document.querySelectorAll('.pg-row select').length
      })`),
    );
    check('Four Permission Group Class rows render', rows.rows === 4, `${rows.rows} rows`);
    check(
      'Every Class row has a "Select contexts…" button',
      rows.buttons.length === 4 && rows.buttons.every((text) => text.startsWith('Select contexts')),
      JSON.stringify(rows.buttons),
    );
    check('Every Class row keeps its combo box', rows.combos === 4, `${rows.combos} combos`);

    /* ------------------------------------------------------------- fill + load */
    // Scenario for this suite: the Group exists on the "server" with contexts that do NOT
    // include _Internal, and one of them (LEGACY_MAIN) does not even follow the prefix.
    // That is exactly the case the picker must support: put an already-existing context
    // ahead of the standard ones in a Class.
    //
    // Reset first: all suites share one preview process, so a preceding suite may have
    // cleared/replaced the seeded state. Seeding is idempotent, resetting makes it reliable.
    await cdp.evaluate(`fetch('/api/dev/reset', { credentials: 'include' }).then(r => r.status)`);
    await sleep(400);
    await cdp.evaluate(`fetch('/api/dev/seed-contexts?group=PG_CTX&contexts=LEGACY_MAIN,PG_CTX_Fixed', { credentials: 'include' }).then(r => r.text())`);
    await sleep(700);

    await cdp.evaluate(`(() => {
      const set = (index, value) => {
        const el = document.querySelectorAll('.input-plain')[index];
        el.value = value;
        el.dispatchEvent(new Event('input', { bubbles: true }));
      };
      set(0, 'PG_CTX');
      set(1, 'PG_CTX');
      set(2, '10');
      set(5, 'PG_CTX');
      set(6, 'PG_CTX');
      set(7, '60338314500-60338314509');
      set(8, '60338314500-60338314502');
      return true;
    })()`);
    await sleep(400);
    await cdp.evaluate(`[...document.querySelectorAll('button')].find(b => b.textContent.includes('Load contexts')).click()`);
    await sleep(1800);

    const loaded = JSON.parse(
      await cdp.evaluate(`JSON.stringify([...document.querySelectorAll('.pg-row select')].map(s => [...s.options].map(o => o.text)))`),
    );
    check('Contexts loaded into every Class combo', loaded.every((options) => options.length > 0), JSON.stringify(loaded));
    check(
      'No combo option is blank',
      loaded.every((options) => options.every((text) => text.trim().length > 0)),
      JSON.stringify(loaded),
    );

    /* ------------------------------------------------------------- the picker */
    await cdp.evaluate(`document.querySelectorAll('.pg-row button')[1].click()`);
    await sleep(400);

    const picker = JSON.parse(
      await cdp.evaluate(`JSON.stringify({
        open: !!document.querySelector('.ctxpick'),
        title: document.querySelector('.ctxpick .u-modal__title')?.textContent || '',
        items: [...document.querySelectorAll('.ctxpick__item')].map(i => i.textContent.trim()),
        heads: [...document.querySelectorAll('.ctxpick__colhead')].map(h => h.textContent.trim()),
        actions: [...document.querySelectorAll('.ctxpick .u-modal__actions button')].map(b => b.textContent.trim())
      })`),
    );
    check('Picker opens for the clicked Class', picker.open && picker.title.includes('Class_2'), picker.title);
    check(
      'Picker lists pre-existing contexts, even ones outside the Context Prefix',
      picker.items.includes('LEGACY_MAIN') && picker.items.includes('PG_CTX_Fixed'),
      JSON.stringify(picker.items),
    );
    check(
      'Picker has an "Available" and a "Selected (in order)" pane',
      picker.heads.includes('Available contexts') && picker.heads.includes('Selected (in order)'),
      JSON.stringify(picker.heads),
    );
    check(
      'Picker offers Cancel / Clear / Apply',
      ['Cancel', 'Clear', 'Apply'].every((name) => picker.actions.includes(name)),
      JSON.stringify(picker.actions),
    );

    // Tick PG_CTX_Fixed first, then LEGACY_MAIN.
    await cdp.evaluate(`(() => {
      const items = [...document.querySelectorAll('.ctxpick__item')];
      const pick = (name) => items.find(i => i.textContent.includes(name)).querySelector('input').click();
      pick('PG_CTX_Fixed');
      pick('LEGACY_MAIN');
      return true;
    })()`);
    const ordered = JSON.parse(
      await cdp.evaluate(`JSON.stringify([...document.querySelectorAll('.ctxpick__item')].map(i => i.textContent.trim()))`),
    );
    check(
      'Tick order is numbered in click order',
      ordered.find((t) => t.includes('PG_CTX_Fixed')).startsWith('1.') &&
        ordered.find((t) => t.includes('LEGACY_MAIN')).startsWith('2.'),
      JSON.stringify(ordered),
    );

    // The checkboxes must survive relabelling (a regression guard: relabel once wiped them).
    const boxesAlive = await cdp.evaluate(`document.querySelectorAll('.ctxpick__item input[type=checkbox]').length`);
    check('Checkboxes survive renumbering', boxesAlive === picker.items.length, `${boxesAlive} checkboxes`);

    /* ---------------------------- move the pre-existing context to the front */
    const beforeMove = JSON.parse(
      await cdp.evaluate(`JSON.stringify([...document.querySelectorAll('.ctxpick__picked-item .ctxpick__picked-name')].map(n => n.textContent.trim()))`),
    );
    check('Selected pane lists the picks in order', beforeMove[0].includes('PG_CTX_Fixed') && beforeMove[1].includes('LEGACY_MAIN'), JSON.stringify(beforeMove));

    await cdp.evaluate(`(() => {
      const rows = [...document.querySelectorAll('.ctxpick__picked-item')];
      const target = rows.find(r => r.textContent.includes('LEGACY_MAIN'));
      [...target.querySelectorAll('.ctxpick__move')].find(b => b.textContent === '↑').click();
      return true;
    })()`);
    const afterMove = JSON.parse(
      await cdp.evaluate(`JSON.stringify([...document.querySelectorAll('.ctxpick__picked-item .ctxpick__picked-name')].map(n => n.textContent.trim()))`),
    );
    check(
      '↑ moves a pre-existing context to position 1',
      afterMove[0].startsWith('1.') && afterMove[0].includes('LEGACY_MAIN') && afterMove[1].includes('PG_CTX_Fixed'),
      JSON.stringify(afterMove),
    );

    await cdp.evaluate(`[...document.querySelectorAll('.ctxpick .u-modal__actions button')].find(b => b.textContent.trim() === 'Apply').click()`);
    await sleep(400);

    const applied = JSON.parse(
      await cdp.evaluate(`JSON.stringify({
        modalGone: !document.querySelector('.ctxpick'),
        labels: [...document.querySelectorAll('.pg-row button')].map(b => b.textContent.trim()),
        comboDisabled: [...document.querySelectorAll('.pg-row select')].map(s => s.disabled),
        runIsPrimary: document.querySelector('.u-btn--primary')?.textContent.trim() || ''
      })`),
    );
    check('Picker closes after Apply', applied.modalGone === true);
    check('Applied Class shows its context count', applied.labels[1] === '2 selected', applied.labels[1]);
    check('Hand-picked Class disables its combo (mutually exclusive)', applied.comboDisabled[1] === true);
    check('Other Classes keep their combos enabled', applied.comboDisabled.filter(Boolean).length === 1);
    check('The primary button is still Run Pipeline', applied.runIsPrimary === 'Run Pipeline', applied.runIsPrimary);

    /* ------------------- "Add context in front of every Class" dropdown */
    const leadUi = JSON.parse(
      await cdp.evaluate(`JSON.stringify({
        present: !!document.querySelector('.pg-lead select'),
        options: [...(document.querySelector('.pg-lead select')?.options || [])].map(o => o.text.trim()),
        hint: document.querySelector('.pg-lead .u-label__hint:last-of-type')?.textContent || ''
      })`),
    );
    check('Lead-context dropdown is present', leadUi.present === true);
    check(
      'Lead dropdown lists server contexts plus a "none" entry',
      leadUi.options[0].includes('none') && leadUi.options.includes('LEGACY_MAIN'),
      JSON.stringify(leadUi.options),
    );

    // Pick LEGACY_MAIN as the lead context for every Class.
    await cdp.evaluate(`(() => {
      const sel = document.querySelector('.pg-lead select');
      sel.value = 'LEGACY_MAIN';
      sel.dispatchEvent(new Event('change', { bubbles: true }));
      return true;
    })()`);
    const leadPicked = await cdp.evaluate(`document.querySelector('.pg-lead select').value`);
    check('Lead context can be selected', leadPicked === 'LEGACY_MAIN', leadPicked);

    /* -------------------- User Profile "Number context" (Task 9) */
    // The Number-context dropdown only shows what the server-wide context list already
    // holds, so refresh it first — otherwise it only has the "<prefix>_Internal" default.
    await cdp.evaluate(`(() => {
      const select = [...document.querySelectorAll('select.input-plain')]
        .find(s => [...s.options].some(o => o.text.includes('default: <prefix>')));
      const row = select.closest('.u-field') || select.parentElement;
      const refresh = [...row.querySelectorAll('button')].find(b => b.textContent.includes('Refresh'));
      if (refresh) refresh.click();
      return !!refresh;
    })()`);
    await sleep(1800);

    const profileCtx = JSON.parse(
      await cdp.evaluate(`JSON.stringify((() => {
        const sel = [...document.querySelectorAll('select.input-plain')]
          .find(s => [...s.options].some(o => o.text.includes('default: <prefix>')));
        return { found: !!sel, options: sel ? [...sel.options].map(o => o.text.trim()) : [], disabled: sel ? sel.disabled : null };
      })())`),
    );
    check('User Profile Number-context dropdown is present', profileCtx.found === true);
    check(
      'Number-context dropdown lists server contexts, including ones outside the Context Prefix',
      profileCtx.options.includes('LEGACY_MAIN') && profileCtx.options.some((o) => o.includes('default: <prefix>')),
      JSON.stringify(profileCtx.options),
    );
    check('Number-context dropdown is selectable (not disabled)', profileCtx.disabled === false);

    // Choose the pre-existing, non-prefix context and prove it reaches the PBX payload.
    await cdp.evaluate(`(() => {
      const sel = [...document.querySelectorAll('select.input-plain')]
        .find(s => [...s.options].some(o => o.text.includes('default: <prefix>')));
      sel.value = 'LEGACY_MAIN';
      sel.dispatchEvent(new Event('change', { bubbles: true }));
      return true;
    })()`);
    const profileCtxPicked = await cdp.evaluate(`(() => {
      const sel = [...document.querySelectorAll('select.input-plain')]
        .find(s => [...s.options].some(o => o.text.includes('default: <prefix>')));
      return sel.value;
    })()`);
    check('Number context can be selected', profileCtxPicked === 'LEGACY_MAIN', profileCtxPicked);

    /* ------------------------------------------------------------------- run */
    await cdp.evaluate(`document.querySelector('.u-btn--primary').click()`);
    const started = await cdp.waitFor(
      `!!document.querySelector('.runmeta') && !document.querySelector('.runmeta').textContent.includes('—')`,
      { timeoutMs: 20000 },
    );
    check('Pipeline started', Boolean(started));

    const finished = await cdp.waitFor(
      `(() => { const b = [...document.querySelectorAll('button')].find(x => x.textContent.trim() === 'Stop'); return b ? b.disabled : false; })()`,
      { timeoutMs: 120000, intervalMs: 500 },
    );
    check('Pipeline finished', Boolean(finished));

    const log = await cdp.evaluate(`document.querySelector('#loglines')?.textContent || ''`);
    check('Lead context applied to every Class', log.includes("Lead context 'LEGACY_MAIN' placed first"), 'checked lead log line');
    // The seeded Group deliberately has no _Internal (Task 2 "skipped" it): every Class must
    // still end up with a non-empty contextInclude_value, falling back to a context that exists.
    const includeLines = [...log.matchAll(/Include Contexts:\s*([^\n📡✅-]*)/g)].map((m) => m[1].trim());
    check(
      'No Class produces an empty contextInclude_value (no _Internal present)',
      includeLines.length >= 4 && includeLines.every((value) => value.length > 0),
      JSON.stringify(includeLines),
    );
    check(
      'Lead context is position 1 in every Class',
      includeLines.length >= 4 && includeLines.every((value) => value.split(',')[0].trim() === 'LEGACY_MAIN'),
      JSON.stringify(includeLines.map((v) => v.split(',')[0])),
    );
    check(
      'Hand-picked order survives behind the lead context',
      includeLines.some((value) => value.startsWith('LEGACY_MAIN,PG_CTX_Fixed')),
      JSON.stringify(includeLines),
    );

    // Task 9: the chosen number context must actually reach the PBX payload.
    const createdProfiles = JSON.parse(
      await cdp.evaluate(`fetch('/api/dev/debug-profiles', { credentials: 'include' }).then(r => r.text())`),
    ).profiles || [];
    const numberContexts = [...new Set(createdProfiles.map((p) => p.number_context))];
    check(
      'Chosen Number context reaches every User Profile payload',
      createdProfiles.length >= 4 && numberContexts.length === 1 && numberContexts[0] === 'LEGACY_MAIN',
      JSON.stringify({ profiles: createdProfiles.length, numberContexts }),
    );

    const outcome = JSON.parse(
      await cdp.evaluate(`JSON.stringify({
        success: document.querySelectorAll('.tasklist .u-dot--success').length,
        error: document.querySelectorAll('.tasklist .u-dot--error').length,
        progress: document.querySelector('.progress__bar')?.style.width || ''
      })`),
    );
    check('All tasks succeeded', outcome.success === 11 && outcome.error === 0, `${outcome.success} ok / ${outcome.error} failed`);
    check('Progress bar full', outcome.progress === '100%', outcome.progress);
    check('No JS console errors', cdp.consoleErrors.length === 0, `${cdp.consoleErrors.length} errors`);

    await cdp.screenshot('.artifacts/pg-contexts.png');
  } finally {
    cdp.close();
  }

  process.exit(summary());
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
