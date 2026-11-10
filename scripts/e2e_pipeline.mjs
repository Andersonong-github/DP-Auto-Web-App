/**
 * e2e_pipeline.mjs — run the pipeline UI once with a real browser (Standard / Complex).
 *
 *   node scripts/e2e_pipeline.mjs http://127.0.0.1:8098 9333 standard
 *   node scripts/e2e_pipeline.mjs http://127.0.0.1:8098 9333 complex
 *
 * Preconditions: dev_preview.py (stateful fake PBX) is running on --base;
 * Chrome started with --remote-debugging-port=<port>.
 */

import { connectCdp, reporter, sleep } from './cdp.mjs';

const [, , base = 'http://127.0.0.1:8098', port = '9333', mode = 'standard'] = process.argv;

// Expected values per mode: total tasks / default checked / actually run
const EXPECT =
  {
    standard: { tasks: 13, checked: 12, run: 12 },
    complex: { tasks: 12, checked: 11, run: 11 },
  }[mode] || { tasks: 13, checked: 12, run: 12 };

async function main() {
  const cdp = await connectCdp({ port });
  const { check, summary } = reporter();
  const label = mode === 'complex' ? 'Complex mode' : 'Standard mode';

  try {
    // 1. Create a fake session and enter the matching mode
    await cdp.goto(`${base}/api/dev/auto-login`, 3000);
    await cdp.goto(`${base}/#/${mode}`, 3000);

    const form = JSON.parse(
      await cdp.evaluate(`JSON.stringify({
        inputs: document.querySelectorAll('.input-plain').length,
        tasks: document.querySelectorAll('.tasklist--selectable input[type=checkbox]').length,
        checked: [...document.querySelectorAll('.tasklist--selectable input[type=checkbox]')].filter(c => c.checked).length,
        runDisabled: document.querySelector('.u-btn--primary')?.disabled ?? null,
        shell: !!document.querySelector('.shell'),
        cards: document.querySelectorAll('.u-card').length
      })`),
    );
    check(`${label} page loaded`, form.shell === true);
    check('Parameter form rendered', form.inputs >= 10, `${form.inputs} inputs`);
    check(`Task list renders ${EXPECT.tasks} items`, form.tasks === EXPECT.tasks, `${form.tasks} items`);
    check(`Defaults checked ${EXPECT.checked} items`, form.checked === EXPECT.checked, `${form.checked} items`);
    check('Run button enabled', form.runDisabled === false);

    /* ------------ the two User-provisioning tasks are paired side by side ------------ */
    const pairing = JSON.parse(
      await cdp.evaluate(`JSON.stringify((() => {
        const pair = document.querySelector('.tasklist__pair');
        if (!pair) return { present: false };
        const kids = [...pair.children].map(li => {
          const r = li.getBoundingClientRect();
          return {
            x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width),
            name: li.querySelector('.tasklist__name')?.textContent || '',
            index: li.querySelector('.tasklist__idx')?.textContent || '',
            hasBadge: !!li.querySelector('.u-badge')
          };
        });
        const names = [...document.querySelectorAll('.tasklist--selectable .tasklist__name')].map(n => n.textContent);
        return {
          present: true,
          kids,
          sideBySide: kids.length === 2 && Math.abs(kids[0].y - kids[1].y) < 2 && kids[1].x > kids[0].x,
          topLevelRows: document.querySelectorAll('.tasklist--selectable > li').length,
          nameCount: names.length,
          hasMobility: names.includes('User (Mobility Apps Only)'),
          hasHtek: names.includes('User (Htek Mac based Only)'),
          cnLabels: document.querySelectorAll('.tasklist__cn').length,
          duplicateLabels: names.filter((n, i) => names.indexOf(n) !== i)
        };
      })())`),
    );
    check('The two User-provisioning tasks are paired in one row', pairing.present === true);
    check('The pair is laid out left / right, not stacked', pairing.sideBySide === true, JSON.stringify(pairing.kids?.map((k) => ({ x: k.x, y: k.y }))));
    check(
      'Both User tasks keep their own name, index and status badge',
      pairing.hasMobility && pairing.hasHtek && pairing.kids.every((k) => k.index && k.hasBadge),
      JSON.stringify(pairing.kids),
    );
    check(
      `Pairing does not hide any task (${EXPECT.tasks} names, ${EXPECT.tasks - 1} top-level rows)`,
      pairing.nameCount === EXPECT.tasks && pairing.topLevelRows === EXPECT.tasks - 1,
      `${pairing.nameCount} names / ${pairing.topLevelRows} rows`,
    );
    check(
      'No duplicated grey secondary label next to the task names',
      pairing.cnLabels === 0 && pairing.duplicateLabels.length === 0,
      `${pairing.cnLabels} cn labels, duplicates=${JSON.stringify(pairing.duplicateLabels)}`,
    );

    if (mode === 'complex') {
      const extras = JSON.parse(
        await cdp.evaluate(`JSON.stringify({
          pgRows: document.querySelectorAll('.u-card select.input-plain').length,
          switches: document.querySelectorAll('.u-switch input[type=checkbox]').length,
          cards: document.querySelectorAll('.u-card').length
        })`),
      );
      check('Complex mode sub-option cards rendered', extras.cards >= 8, `${extras.cards} cards`);
      check('Four Permission Group dropdowns present', extras.pgRows >= 4, `${extras.pgRows} dropdowns`);
      check('Toggle controls present', extras.switches >= 10, `${extras.switches} switches`);
    }

    // 2. Fill in parameters (index matches PARAM_FIELDS order)
    await cdp.evaluate(`(() => {
      const set = (index, value) => {
        const el = document.querySelectorAll('.input-plain')[index];
        el.value = value;
        el.dispatchEvent(new Event('input', { bubbles: true }));
      };
      set(0, 'E2E_GROUP');
      set(1, 'E2E_CODE');
      set(2, '10');
      set(3, '202.179.100.99');
      set(4, '7978');
      set(5, 'E2E_GROUP');
      set(6, 'E2E_GROUP');
      set(7, '60338314500-60338314509');
      set(8, '60338314500-60338314502');
      return true;
    })()`);
    await sleep(600);

    const preview = await cdp.evaluate(
      `(() => { const t = [...document.querySelectorAll('textarea.input-plain')].find(el => el.readOnly); return t ? t.value : ''; })()`,
    );
    check('Extension preview parsed live', preview.split('\n').filter(Boolean).length === 3, JSON.stringify(preview));

    // Task titles must not repeat themselves (they used to render "Group Group").
    const titles = JSON.parse(
      await cdp.evaluate(`JSON.stringify([...document.querySelectorAll('.task-row')].map((row) => {
        const name = row.querySelector('.tasklist__name')?.textContent || '';
        const sub = row.querySelector('.tasklist__cn')?.textContent || '';
        return { name, sub: sub.trim() };
      }))`),
    );
    check(
      'Task titles are not duplicated',
      titles.length >= 12 && titles.every((t) => !t.sub || t.sub !== t.name),
      `${titles.length} rows, duplicated=${titles.filter((t) => t.sub && t.sub === t.name).length}`,
    );

    // 3. Run the pipeline
    await cdp.evaluate(`document.querySelector('.u-btn--primary').click()`);
    const started = await cdp.waitFor(
      `!!document.querySelector('.runmeta') && document.querySelector('.runmeta').textContent.includes('Run') && !document.querySelector('.runmeta').textContent.includes('—')`,
      { timeoutMs: 20000 },
    );
    check('Pipeline started', Boolean(started));

    const finished = await cdp.waitFor(
      `(() => { const b = [...document.querySelectorAll('button')].find(x => x.textContent.trim() === 'Stop'); return b ? b.disabled : false; })()`,
      { timeoutMs: 120000, intervalMs: 500 },
    );
    check('Pipeline finished (Stop button disabled)', Boolean(finished));

    const outcome = JSON.parse(
      await cdp.evaluate(`JSON.stringify({
        success: document.querySelectorAll('.tasklist .u-dot--success').length,
        error: document.querySelectorAll('.tasklist .u-dot--error').length,
        records: document.querySelectorAll('.records-table tbody tr').length,
        log: (document.querySelector('#loglines')?.textContent || ''),
        progress: document.querySelector('.progress__bar')?.style.width || '',
        meta: document.querySelector('.runmeta')?.textContent || ''
      })`),
    );
    check(
      `All tasks succeeded (${EXPECT.run} green dots)`,
      outcome.success === EXPECT.run && outcome.error === 0,
      `success ${outcome.success} / failed ${outcome.error}`,
    );
    check('3 extension records created', outcome.records === 3, `${outcome.records} records`);
    check('Completion message shown in log console', outcome.log.includes('All tasks completed!'));
    check('Progress bar full', outcome.progress === '100%', outcome.progress);

    if (outcome.success !== EXPECT.run || outcome.error !== 0 || outcome.records !== 3) {
      const tail = outcome.log.split('\n').slice(-16).join('\n');
      console.log(`\n--- last 16 log lines ---\n${tail}\n`);
    }

    const csvEnabled = await cdp.evaluate(
      `(() => { const b = [...document.querySelectorAll('button')].find(x => x.textContent.includes('Export CSV')); return b ? !b.disabled : false; })()`,
    );
    check('Export CSV button enabled', csvEnabled === true);

    /* --------------------- ACL User: every role carries the 4 manager_allow features */
    if (mode === 'standard' || mode === 'complex') {
      const aclUpdates = JSON.parse(
        await cdp.evaluate(`fetch('/api/dev/debug-acl-users', { credentials: 'include' }).then(r => r.text())`),
      ).updates || [];
      if (aclUpdates.length) {
        const parsed = aclUpdates.map((row) => {
          let features = [];
          try {
            features = JSON.parse(row.features);
          } catch {
            /* leave empty */
          }
          const allow = features.filter((f) => f.feature === 'manager_allow').map((f) => f.data);
          const ext = features.find((f) => f.feature === 'extension');
          return { privileges: row.privileges, aclgroup: row.aclgroup, allow, ext: ext ? ext.data : '' };
        });
        const EXPECT_ALLOW = ['makeCall', 'getUserDevice', 'checkFeatures', 'frsipMobileLogin'];
        check(
          'ACL User: every user gets all 4 manager_allow features',
          parsed.every((row) => EXPECT_ALLOW.every((name) => row.allow.includes(name))),
          JSON.stringify(parsed.map((row) => ({ p: row.privileges, n: row.allow.length }))),
        );
        check(
          'ACL User: every user still carries its extension feature',
          parsed.every((row) => row.ext.length > 0),
          JSON.stringify(parsed.map((row) => row.ext)),
        );
        const managerRows = parsed.filter((row) => row.privileges === 'manager');
        const limitedRows = parsed.filter((row) => row.privileges === 'limited');
        check(
          'ACL User: privileges still separate manager from limited',
          managerRows.length >= 1 && limitedRows.length >= 1,
          `${managerRows.length} manager / ${limitedRows.length} limited`,
        );
        check(
          'ACL User: manager and user point at different ACL groups',
          managerRows.length && limitedRows.length && managerRows[0].aclgroup !== limitedRows[0].aclgroup,
          JSON.stringify({ manager: managerRows[0]?.aclgroup, limited: limitedRows[0]?.aclgroup }),
        );
      }
    }

    await cdp.screenshot(`.artifacts/pipeline-${mode}.png`);
    check('No JS console errors', cdp.consoleErrors.length === 0, cdp.consoleErrors.slice(0, 3).join(' | '));
  } catch (error) {
    // Important: don't let finally swallow the exception, or it will "pass all green" without actually finishing
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
