/**
 * views/pipeline.js — Standard / Complex pipeline page.
 *
 * Standard mode (phase 2) is fully usable: parameter form → task selection → server-side sequential run →
 * SSE live log + status dots + extension record export.
 * Complex mode (phase 3) currently only lists the tasks and their differences.
 */

import { api } from '../api.js';
import { readPipelinePrefs, writePipelinePrefs } from '../prefs.js';
import { state } from '../store.js';
import { badge, clear, copyText, dot, h, icon, log, toast } from '../ui.js';
import { buildComplexSection } from './pipeline-complex.js';
import { parseExtRange } from './tools.js';

const HTEK_MODELS = ['List Provide Model', 'uc902g', 'uc902sp', 'uc921g'];
const EXCLUSIVE = ['User (Mobility Apps Only)', 'User (Htek Mac based Only)'];
/**
 * Complex mode gives Outbound Routing a second, mutually exclusive flavour: instead of the
 * 10 default rules, the operator can provision one hand-picked number + context. The pair is
 * rendered side by side exactly like the two User provisioning tasks.
 */
const OUTBOUND_PAIR = ['Outbound Routing', 'Custom Outbound Routing'];
const TASK_PAIRS = [EXCLUSIVE, OUTBOUND_PAIR];

/** Parameter form definition (keys match the desktop session / backend PipelineParams). */
const PARAM_FIELDS = [
  { key: 'group_name', label: 'Group Name', hint: 'Spaces become _ automatically, max 30 characters', placeholder: 'CARSOME_Kajang' },
  { key: 'group_code', label: 'Group Code', placeholder: 'MCBLL5248_MV_CARSOME_KJG' },
  { key: 'unified_limit', label: 'Max Concurrent Calls & Reg User', hint: '1-300', type: 'number', attrs: { min: 1, max: 300 } },
  { key: 'host_ip', label: 'SIP Trunk Host / IP', placeholder: '202.179.100.99' },
  { key: 'port', label: 'SIP Trunk Port', placeholder: '7978' },
  { key: 'context_prefix', label: 'Context Prefix', placeholder: 'CARSOME' },
  { key: 'perm_group_prefix', label: 'Permission Group Prefix', placeholder: 'CARSOME' },
  { key: 'inbound_ranges', label: 'Inbound Ranges / CallerID', hint: '603xxx-603xxx, comma-separate multiple ranges', wide: true, placeholder: '60338314500-60338314509' },
  { key: 'user_ext', label: 'User Extension / Extension Range', hint: '603xxx-603xxx, comma-separate multiple ranges', wide: true, placeholder: '60338314500-60338314503' },
];

const STATUS_TEXT = { 0: 'Pending', 1: 'Running', 2: 'Success', 3: 'Failed' };
const STATUS_DOT = { 0: '', 1: 'running', 2: 'success', 3: 'error' };
const STATUS_CLASS = { 0: '', 1: 'is-running', 2: 'is-success', 3: 'is-error' };

/** Matches clean_mac in the desktop main.py. */
function cleanMac(raw) {
  return String(raw || '').replace(/[:.\-\s]/g, '').trim();
}

/** Keep the first (default) member of every mutually-exclusive task pair. */
function withoutPairConflicts(names) {
  const keep = new Set(names);
  TASK_PAIRS.forEach((pair) => {
    const picked = pair.filter((name) => keep.has(name));
    picked.slice(1).forEach((name) => keep.delete(name));
  });
  return names.filter((name) => keep.has(name));
}

export function pipelineView(mode) {
  const isStandard = mode !== 'complex';

  return {
    title: isStandard ? 'Standard Mode Pipeline' : 'Complex Mode Pipeline',
    subtitle: isStandard
      ? 'Group → Number (Strip Digits) full task set, for provisioning a customer from scratch'
      : 'Shares the task order with Standard mode, skips Number (Strip Digits), and supports detailed sub-options',

    mount(root) {
      const allTasks = (state.config && state.config.tasks) || [];
      const tasks = allTasks.filter((task) => (isStandard ? task.standard !== false : task.complex !== false));
      const prefs = readPipelinePrefs(mode);

      // Default selection: every task except Htek provisioning (matches desktop “Select All”),
      // and keep the default Outbound Routing variant (not the custom one).
      const defaultSelected = tasks
        .map((task) => task.name)
        .filter((name) => name !== 'User (Htek Mac based Only)' && name !== 'Custom Outbound Routing');
      const known = new Set(tasks.map((task) => task.name));
      let restored = Array.isArray(prefs.tasks) ? prefs.tasks.filter((name) => known.has(name)) : null;
      if (restored) {
        restored = withoutPairConflicts(restored);
      }

      /* ---------------------------------------------------------- Runtime state */
      const runtime = {
        runId: null,
        running: false,
        finished: false,
        source: null,
        lastSeq: 0,
        startedAt: 0,
        records: [],
        recordKeys: new Set(),
        total: 0,
        taskDots: new Map(),
        taskRows: new Map(),
        selected: new Set(restored && restored.length ? restored : defaultSelected),
      };

      /* ------------------------------------------------------------ Parameter form */
      const inputs = new Map();
      const paramFields = PARAM_FIELDS.map((field) => {
        const input = h('input', {
          class: 'input-plain',
          type: field.type || 'text',
          value: prefs[field.key] || '',
          placeholder: field.placeholder || '',
          spellcheck: 'false',
          ...(field.attrs || {}),
        });
        inputs.set(field.key, input);
        return h(
          'div',
          { class: 'u-field' },
          h('label', { class: 'u-label' }, field.label, field.hint ? h('span', { class: 'u-label__hint', text: field.hint }) : null),
          input,
        );
      });

      const usernamesArea = h('textarea', {
        class: 'input-plain',
        spellcheck: 'false',
        placeholder: 'One Username per line (matches extensions one to one; a single line means all extensions share the first)',
      });
      usernamesArea.value = prefs.usernames || '';

      const emailsArea = h('textarea', {
        class: 'input-plain',
        spellcheck: 'false',
        placeholder: 'One Email per line (same rules, optional)',
      });
      emailsArea.value = prefs.emails || '';

      const htekModel = h(
        'select',
        { class: 'input-plain' },
        HTEK_MODELS.map((model) => h('option', { value: model, selected: (prefs.htek_model || 'uc902g') === model }, model)),
      );
      const htekMac = h('textarea', {
        class: 'input-plain',
        spellcheck: 'false',
        placeholder: 'One MAC per line (optional model after TAB, with “List Provide Model”):\n00:1A:2B:3C:4D:5E\n00:1A:2B:3C:4D:5F\tuc902g',
      });
      htekMac.value = prefs.htek_mac || '';

      const extPreview = h('textarea', { class: 'input-plain', readOnly: true, placeholder: 'Extension preview' });

      /* On parameter change → save locally + refresh the extension preview */
      /** Saves the form + task selection; Complex sub-options pass their values as ``overrides``. */
      const persist = (overrides = {}) => {
        const values = { tasks: [...runtime.selected] };
        inputs.forEach((input, key) => {
          values[key] = input.value;
        });
        values.htek_model = htekModel.value;
        values.htek_mac = htekMac.value;
        values.usernames = usernamesArea.value;
        values.emails = emailsArea.value;
        Object.assign(values, overrides);
        writePipelinePrefs(mode, values);
      };

      /* Complex-mode-only sub-options (Context suffix / Permission Group / ACL / templates …) */
      const complex = isStandard
        ? null
        : buildComplexSection({
            selected: runtime.selected,
            prefs,
            persist,
            state: runtime,
            lists: { usernamesArea, emailsArea },
            params: inputs,
          });

      const refreshPreview = () => {        const parsed = parseExtRange(inputs.get('user_ext').value, isStandard);
        const shown = parsed.items.slice(0, 200);
        extPreview.value =
          parsed.items.length === 0
            ? ''
            : shown.join('\n') + (parsed.items.length > shown.length ? `\n… ${parsed.items.length - shown.length} more omitted` : '');
        return parsed.items;
      };

      inputs.forEach((input) => {
        input.addEventListener('input', () => {
          if (input === inputs.get('group_name')) input.value = input.value.replace(/ /g, '_').slice(0, 30);
          if (complex && input === inputs.get('user_ext')) complex.syncFromExtRange(input.value);
          refreshPreview();
          persist();
        });
      });
      htekModel.addEventListener('change', persist);
      htekMac.addEventListener('input', persist);

      /* ------------------------------------------------------------ Task list */
      function setTaskStatus(name, status) {
        const row = runtime.taskRows.get(name);
        const dotEl = runtime.taskDots.get(name);
        if (!row || !dotEl) return;
        Object.values(STATUS_CLASS).forEach((cls) => cls && row.classList.remove(cls));
        if (STATUS_CLASS[status]) row.classList.add(STATUS_CLASS[status]);
        dotEl.className = `u-dot ${STATUS_DOT[status] ? `u-dot--${STATUS_DOT[status]}` : ''}`;
        dotEl.title = STATUS_TEXT[status];
        const badgeEl = row.querySelector('.u-badge');
        if (badgeEl) {
          badgeEl.textContent = STATUS_TEXT[status];
          badgeEl.className = `u-badge ${status === 2 ? 'u-badge--ok' : status === 3 ? 'u-badge--err' : status === 1 ? 'u-badge--warn' : ''}`;
        }
      }

      function toggleExclusive(name, checked) {
        // Mutually exclusive pairs: User (Mobility) / User (Htek), and in Complex mode
        // Outbound Routing / Custom Outbound Routing.
        const pair = TASK_PAIRS.find((item) => item.includes(name));
        if (!pair) return;
        const others = pair.filter((item) => item !== name);
        if (checked) {
          const conflicts = others.filter((item) => runtime.selected.has(item));
          conflicts.forEach((other) => {
            const otherBox = runtime.taskRows.get(other)?.querySelector('input');
            if (otherBox) otherBox.checked = false;
            runtime.selected.delete(other);
          });
          if (conflicts.length) {
            toast('warn', `“${conflicts.join('”, “')}” was unchecked automatically (the two options are mutually exclusive)`);
          }
        }
      }

      /** Build one task row (also used inside the paired User-provisioning block). */
      function buildTaskRow(task, index) {
        const checkbox = h('input', {
          type: 'checkbox',
          checked: runtime.selected.has(task.name),
          on: {
            change: () => {
              if (checkbox.checked) {
                runtime.selected.add(task.name);
                toggleExclusive(task.name, true);
              } else {
                runtime.selected.delete(task.name);
              }
              setTaskStatus(task.name, 0);
              persist();
              updateRunButton();
              if (complex) complex.updateVisibility();
            },
          },
        });
        const dotEl = dot('idle', STATUS_TEXT[0]);
        const statusBadge = badge(STATUS_TEXT[0], '');
        const elapsed = h('span', { class: 'task-row__elapsed', text: '' });
        const row = h(
          'li',
          {},
          h(
            'label',
            { class: 'task-row' },
            checkbox,
            h('span', { class: 'tasklist__idx', text: String(index + 1) }),
            dotEl,
            h('span', { class: 'tasklist__name', text: task.name }),
            elapsed,
            statusBadge,
          ),
        );
        runtime.taskDots.set(task.name, dotEl);
        runtime.taskRows.set(task.name, row);
        return row;
      }

      /* Mutually exclusive task alternatives share one row, two columns:
         User (Mobility) / User (Htek), and Outbound / Custom Outbound in Complex mode. */
      const listChildren = [];
      const rendered = new Set();
      tasks.forEach((task, index) => {
        if (rendered.has(task.name)) return;
        const pair = TASK_PAIRS.find((item) => item.includes(task.name));
        const present = pair
          ? pair
              .map((name) => tasks.findIndex((entry) => entry.name === name))
              .filter((pairIndex) => pairIndex >= 0)
          : [index];
        if (present.length > 1) {
          present.forEach((pairIndex) => rendered.add(tasks[pairIndex].name));
          listChildren.push(
            h(
              'li',
              { class: 'tasklist__pair' },
              ...present.map((pairIndex) => buildTaskRow(tasks[pairIndex], pairIndex)),
            ),
          );
          return;
        }
        rendered.add(task.name);
        listChildren.push(buildTaskRow(task, index));
      });

      const taskList = h('ul', { class: 'tasklist tasklist--selectable' }, listChildren);

      /* ------------------------------------------------------------ Records table */
      const recordsBody = h('tbody');
      const recordsWrap = h('div', { class: 'table-wrap' }, h('table', { class: 'table records-table' },
        h('thead', {}, h('tr', {}, h('th', { text: 'Extension' }), h('th', { text: 'Login Password' }), h('th', { text: 'PIN' }), h('th', { text: '' }))),
        recordsBody,
      ));
      const recordsEmpty = h('div', { class: 'records-empty', text: 'No extension records yet. They appear here after you select “User (Mobility Apps Only)” and run.' });
      const recordsHost = h('div', {}, recordsEmpty);
      const exportButton = h('button', { class: 'u-btn u-btn--sm', type: 'button', disabled: true }, icon('copy', 15), 'Copy Records');
      const csvButton = h('button', { class: 'u-btn u-btn--sm', type: 'button', disabled: true }, icon('check', 15), 'Export CSV');

      function renderRecords() {
        clear(recordsBody);
        runtime.records.forEach((record) => {
          recordsBody.appendChild(
            h(
              'tr',
              {},
              h('td', { class: 'mono', text: record.extension }),
              h('td', { class: 'mono', text: record.login_password }),
              h('td', { class: 'mono', text: record.pin }),
              h(
                'td',
                {},
                h(
                  'button',
                  {
                    class: 'copy-cell',
                    type: 'button',
                    title: 'Copy this row',
                    on: {
                      click: async () => {
                        const ok = await copyText(`${record.extension}\t${record.login_password}\t${record.pin}`);
                        toast(ok ? 'ok' : 'err', ok ? 'Row copied' : 'Copy failed');
                      },
                    },
                  },
                  icon('copy', 14),
                ),
              ),
            ),
          );
        });
        const has = runtime.records.length > 0;
        if (has && !recordsWrap.isConnected) recordsHost.appendChild(recordsWrap);
        if (!has && recordsWrap.isConnected) recordsWrap.remove();
        recordsEmpty.style.display = has ? 'none' : '';
        exportButton.disabled = !has;
        csvButton.disabled = !has;
      }

      async function copyAllRecords() {
        const text = runtime.records.map((r) => `${r.extension}\t${r.login_password}\t${r.pin}`).join('\n');
        const ok = await copyText(text);
        toast(ok ? 'ok' : 'err', ok ? `Copied ${runtime.records.length} records (ready to paste into Excel)` : 'Copy failed');
      }

      function exportCsv() {
        const lines = ['Extension,Login Password,PIN', ...runtime.records.map((r) => `${r.extension},${r.login_password},${r.pin}`)];
        const blob = new Blob([`\ufeff${lines.join('\r\n')}`], { type: 'text/csv;charset=utf-8' });
        const url = URL.createObjectURL(blob);
        const link = h('a', { href: url, download: `dp-records-${runtime.runId || 'manual'}.csv` });
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(url);
        log('info', `Exported ${runtime.records.length} extension records`);
      }

      exportButton.addEventListener('click', copyAllRecords);
      csvButton.addEventListener('click', exportCsv);

      /* ------------------------------------------------------------ Run controls */
      const progressBar = h('div', { class: 'progress__bar' });
      const progress = h('div', { class: 'progress' }, progressBar);
      const runMeta = h('div', { class: 'runmeta' });
      const errorSlot = h('div');
      const selectedBadge = badge('0 selected', 'brand');
      const runButton = h(
        'button',
        { class: 'u-btn u-btn--primary', type: 'button', on: { click: () => startRun() } },
        h('span', { class: 'u-btn__shine' }),
        icon('play', 16),
        'Run Pipeline',
      );
      const stopButton = h('button', { class: 'u-btn u-btn--danger u-btn--sm', type: 'button', disabled: true, on: { click: () => stopRun() } }, 'Stop');

      function updateRunButton() {
        const count = runtime.selected.size;
        selectedBadge.textContent = `${count} selected`;
        runButton.disabled = runtime.running || count === 0;
        runButton.title = count === 0 ? 'Select at least one task' : '';
      }

      function setMeta(extra = {}) {
        const elapsed = runtime.startedAt ? Math.round((Date.now() - runtime.startedAt) / 1000) : 0;
        clear(runMeta);
        runMeta.append(
          h('span', {}, 'Selected ', h('b', { text: String(runtime.selected.size) })),
          h('span', {}, 'Records ', h('b', { text: String(runtime.records.length) })),
          h('span', {}, 'Run ', h('b', { text: runtime.runId || '—' })),
          h('span', {}, 'Elapsed ', h('b', { text: `${elapsed}s` })),
          extra.statusText ? h('span', {}, 'Status ', h('b', { text: extra.statusText })) : null,
        );
      }

      function fillParams() {
        const params = {};
        inputs.forEach((input, key) => {
          params[key] = input.value.trim();
        });
        params.htek_model = htekModel.value;
        params.htek_mac_data = htekMac.value
          .split('\n')
          .map((line) => line.trim())
          .filter(Boolean)
          .map((line) => {
            const [rawMac, ...rest] = line.replace(/\t/g, ' ').split(/\s+/);
            const mac = cleanMac(rawMac);
            const model = rest.join(' ').trim();
            return { mac, mac_select: mac, model: model ? model.toUpperCase() : '' };
          })
          .filter((row) => row.mac);
        if (complex) {
          const extra = complex.collect();
          runtime.lastCustomPayloads = extra.custom_payloads || {};
          delete extra.custom_payloads;
          Object.assign(params, extra);
        }
        return params;
      }

      function validate(params) {
        if (runtime.selected.size === 0) return 'Select at least one task.';
        if (runtime.selected.has('Group')) {
          if (!params.group_name) return 'Enter a Group Name.';
          if (!params.group_code) return 'Enter a Group Code.';
        }
        const limit = Number(params.unified_limit || '10');
        if (!Number.isInteger(limit) || limit < 1 || limit > 300) return 'Max Concurrent Calls & Reg User must be an integer from 1-300.';
        const needsExt = ['User (Mobility Apps Only)', 'User (Htek Mac based Only)', 'Number (Strip Digits)', 'ACL User'].some((name) =>
          runtime.selected.has(name),
        );
        if (needsExt && !params.user_ext) return 'Enter a User Extension / Extension Range.';
        if (runtime.selected.has('User (Htek Mac based Only)')) {
          const exts = parseExtRange(params.user_ext, isStandard);
          if (!exts.items.length) return 'No valid extensions parsed from the extension range.';
          if (params.htek_mac_data.length !== exts.items.length) {
            return `Htek MAC data needs ${exts.items.length} lines (one per extension), currently ${params.htek_mac_data.length}.`;
          }
        }
        if (complex) {
          const subError = complex.validate();
          if (subError) return subError;
        }
        return null;
      }

      /* -------------------------------------------------------- SSE event handling */
      function elapsedOf(task) {
        if (!task.startedAt) return '';
        const end = task.finishedAt || Date.now() / 1000;
        return `${Math.max(0, Math.round(end - task.startedAt))}s`;
      }

      function markTask(name, status, task) {
        setTaskStatus(name, status);
        const row = runtime.taskRows.get(name);
        if (row && task) {
          const el = row.querySelector('.task-row__elapsed');
          if (el) el.textContent = elapsedOf(task);
        }
      }

      function setProgress(done, total, failed) {
        const pct = total ? Math.round((done / total) * 100) : 0;
        progressBar.style.width = `${pct}%`;
        progressBar.classList.toggle('progress__bar--error', failed > 0);
      }

      function finishRun(status) {
        runtime.running = false;
        runtime.finished = true;
        stopButton.disabled = true;
        updateRunButton();
        const statusText = { success: 'Success', failed: 'Failed', stopped: 'Stopped' }[status] || status || '';
        setMeta({ statusText });
        // Note: the stream is **not** closed here — a finished run still needs it to backfill history logs,
        // closing is left to stream_end.
        return statusText;
      }

      function handleEvent(event) {
        runtime.lastSeq = event.seq || runtime.lastSeq;
        switch (event.kind) {
          case 'run_start':
            runtime.startedAt = Date.now();
            runtime.total = event.tasks.length;
            event.tasks.forEach((name) => setTaskStatus(name, 0));
            setProgress(0, runtime.total, 0);
            setMeta({ statusText: 'Running' });
            break;
          case 'task':
            markTask(event.name, event.status, event);
            if (event.status === 2 || event.status === 3) {
              const done = [...runtime.taskDots.values()].filter((d) => d.classList.contains('u-dot--success') || d.classList.contains('u-dot--error')).length;
              const failed = [...runtime.taskDots.values()].filter((d) => d.classList.contains('u-dot--error')).length;
              // the denominator is the number of tasks this run actually executes, not the total shown in the UI
              setProgress(done, runtime.total || runtime.taskDots.size, failed);
            }
            setMeta({ statusText: STATUS_TEXT[event.status] || '' });
            break;
          case 'log':
            log(event.level || 'info', event.message);
            break;
          case 'record': {
            // events may replay from seq 0 (to keep logs complete), so dedupe records by content
            const key = `${event.extension}|${event.login_password}|${event.pin}`;
            if (!runtime.recordKeys.has(key)) {
              runtime.recordKeys.add(key);
              runtime.records.push({ extension: event.extension, login_password: event.login_password, pin: event.pin });
              renderRecords();
            }
            setMeta({ statusText: 'Running' });
            break;
          }
          case 'customer':
            log('info', `Customer ID = ${event.customerId}`);
            break;
          case 'run_end': {
            const alreadyFinished = runtime.finished;
            const statusText = finishRun(event.status);
            const tone = event.status === 'success' ? 'ok' : event.status === 'stopped' ? 'warn' : 'err';
            if (!alreadyFinished) toast(tone, `Pipeline: ${statusText}, ${runtime.records.length} extension records`);
            break;
          }
          case 'stream_end':
            if (runtime.source) {
              runtime.source.close();
              runtime.source = null;
            }
            // stream ended without run_end (e.g. the run had already finished when we subscribed), fetch a snapshot
            if (runtime.running && runtime.runId) {
              api
                .getRun(runtime.runId)
                .then((snapshot) => {
                  applySnapshot(snapshot);
                  finishRun(snapshot.status);
                })
                .catch(() => finishRun('unknown'));
            }
            break;
          default:
            break;
        }
      }

      function attach(runId, after = 0) {
        if (runtime.source) runtime.source.close();
        runtime.runId = runId;
        runtime.attached = true;
        const source = new EventSource(api.runEventsUrl(runId, after));
        runtime.source = source;
        source.onmessage = (message) => {
          try {
            handleEvent(JSON.parse(message.data));
          } catch (error) {
            console.error('SSE parse failed', error);
          }
        };
        source.onerror = () => {
          // disconnected: wait 2s, then resume once from lastSeq (the backend keeps events in memory)
          source.close();
          runtime.source = null;
          if (!runtime.running) return;
          setTimeout(async () => {
            try {
              const snapshot = await api.getRun(runId);
              applySnapshot(snapshot);
              if (snapshot.status === 'running') attach(runId, snapshot.lastSeq);
              else runtime.running = false;
            } catch (error) {
              log('warn', `Event stream lost and unrecoverable: ${error.message}`);
              runtime.running = false;
              updateRunButton();
            }
          }, 2000);
        };
      }

      function applySnapshot(snapshot) {
        runtime.runId = snapshot.id;
        if (snapshot.records && snapshot.records.length) {
          runtime.records = [...snapshot.records];
          runtime.recordKeys = new Set(
            snapshot.records.map((r) => `${r.extension}|${r.login_password}|${r.pin}`),
          );
        }
        snapshot.tasks.forEach((task) => markTask(task.name, task.status, task));
        setProgress(snapshot.progress.done, snapshot.progress.total, snapshot.progress.error);
        renderRecords();
        setMeta({ statusText: { running: 'Running', success: 'Success', failed: 'Failed', stopped: 'Stopped' }[snapshot.status] || snapshot.status });
      }

      async function startRun() {
        const params = fillParams();
        const error = validate(params);
        if (error) {
          toast('warn', error);
          log('warn', `Parameter validation failed: ${error}`);
          return;
        }

        clear(errorSlot);
        runtime.records = [];
        runtime.recordKeys = new Set();
        runtime.finished = false;
        renderRecords();
        setProgress(0, runtime.selected.size, 0);
        runtime.taskRows.forEach((_row, name) => setTaskStatus(name, 0));

        runButton.disabled = true;
        stopButton.disabled = false;
        runtime.running = true;
        runtime.startedAt = Date.now();
        setMeta({ statusText: 'Starting' });
        log('info', `Submitting pipeline: ${runtime.selected.size} tasks`);

        try {
          const snapshot = await api.startPipeline({
            mode,
            tasks: [...runtime.selected],
            params,
            custom_payloads: runtime.lastCustomPayloads || {},
          });
          // Key: seed from the snapshot (task status / records / progress), then **always subscribe from seq 0**,
          // so history logs stay complete even for an instant run; records are deduped via recordKeys.
          runtime.runId = snapshot.id;
          applySnapshot(snapshot);
          attach(snapshot.id, 0);
          if (snapshot.status === 'running') {
            runtime.running = true;
            stopButton.disabled = false;
          } else {
            const statusText = finishRun(snapshot.status);
            toast(snapshot.status === 'success' ? 'ok' : 'err', `Pipeline: ${statusText}, ${runtime.records.length} extension records`);
          }
        } catch (err) {
          runtime.running = false;
          stopButton.disabled = true;
          updateRunButton();
          errorSlot.appendChild(h('div', { class: 'u-alert u-alert--err mt-16' }, icon('alert', 18), h('div', { text: err.message })));
          log('err', `Start failed: ${err.message}`);
          toast('err', err.message);
        }
      }

      async function stopRun() {
        if (!runtime.runId) return;
        stopButton.disabled = true;
        try {
          await api.stopRun(runtime.runId);
          log('warn', 'Stop requested; the run will abort after the current task finishes.');
        } catch (error) {
          toast('err', `Stop failed: ${error.message}`);
          stopButton.disabled = false;
        }
      }

      /* ------------------------------------------------------------- Assemble page */
      const formCard = h(
        'section',
        { class: 'u-card' },
        h(
          'div',
          { class: 'u-card__head' },
          h('div', {}, h('h3', { class: 'u-card__title', text: 'Parameters' }), h('p', { class: 'u-card__sub', text: 'Matches the desktop standard_parameter fields, saved automatically in this browser' })),
          badge(isStandard ? 'Standard' : 'Complex', 'brand'),
        ),
        h(
          'div',
          { class: 'u-card__body' },
          h('div', { class: 'form-grid' }, paramFields),
          isStandard
            ? null
            : h(
                'div',
                { class: 'form-grid mt-20' },
                h(
                  'div',
                  { class: 'u-field' },
                  h('label', { class: 'u-label' }, 'Username', h('span', { class: 'u-label__hint', text: 'One per line; blank uses the extension' })),
                  usernamesArea,
                ),
                h(
                  'div',
                  { class: 'u-field' },
                  h('label', { class: 'u-label' }, 'Email', h('span', { class: 'u-label__hint', text: 'One per line; blank uses the default' })),
                  emailsArea,
                ),
              ),
          h(
            'div',
            { class: 'form-grid form-grid--wide mt-20' },
            h(
              'div',
              { class: 'u-field' },
              h('label', { class: 'u-label' }, 'Htek MAC Data', h('span', { class: 'u-label__hint', text: 'Line count is checked only when Htek provisioning is selected' })),
              htekMac,
            ),
            h('div', { class: 'u-field' }, h('label', { class: 'u-label', text: 'Htek Model' }), htekModel),
          ),
          h(
            'div',
            { class: 'u-field mt-20' },
            h('label', { class: 'u-label' }, 'Extension Preview', h('span', { class: 'u-label__hint', text: 'Parsed live from User Extension (strips prefix 6, up to 5000 per run)' })),
            extPreview,
          ),
        ),
      );

      const recordsCard = h(
        'section',
        { class: 'u-card' },
        h(
          'div',
          { class: 'u-card__head' },
          h('div', {}, h('h3', { class: 'u-card__title', text: 'Extension Records' }), h('p', { class: 'u-card__sub', text: 'Login passwords and PINs returned by the PBX during provisioning' })),
          h('div', { class: 'row' }, exportButton, csvButton),
        ),
        h('div', { class: 'u-card__body' }, recordsHost),
      );

      const runCard = h(
        'section',
        { class: 'u-card' },
        h(
          'div',
          { class: 'u-card__head' },
          h('div', {}, h('h3', { class: 'u-card__title', text: 'Run' }), h('p', { class: 'u-card__sub', text: 'Runs sequentially on the server; logs stream live to the run console below' })),
          h('div', { class: 'row' }, stopButton, runButton),
        ),
        h('div', { class: 'u-card__body' }, progress, runMeta, errorSlot),
      );

      clear(root).append(
        h(
          'div',
          { class: 'page-head' },
          h('div', {}, h('h2', { text: isStandard ? 'Standard Mode' : 'Complex Mode' }), h('p', { text: this.subtitle })),
          h(
            'div',
            { class: 'row' },
            h(
              'button',
              {
                class: 'u-btn u-btn--sm',
                type: 'button',
                on: {
                  click: () => {
                    runtime.selected = new Set(tasks.map((task) => task.name));
                    // keep only one member of each mutually exclusive pair
                    runtime.selected = new Set(withoutPairConflicts([...runtime.selected]));
                    runtime.taskRows.forEach((row, name) => {
                      const box = row.querySelector('input');
                      if (box) box.checked = runtime.selected.has(name);
                    });
                    persist();
                    updateRunButton();
                    setMeta({});
                    if (complex) complex.updateVisibility();
                  },
                },
              },
              icon('check', 15),
              'Select All',
            ),
            h(
              'button',
              {
                class: 'u-btn u-btn--sm',
                type: 'button',
                on: {
                  click: () => {
                    runtime.selected.clear();
                    runtime.taskRows.forEach((row) => {
                      const box = row.querySelector('input');
                      if (box) box.checked = false;
                    });
                    persist();
                    updateRunButton();
                    setMeta({});
                    if (complex) complex.updateVisibility();
                  },
                },
              },
              'Clear',
            ),
            isStandard ? null : badge('Complex Mode Available', 'ok'),
          ),
        ),
        h(
          'div',
          { class: 'grid grid--two' },
          h(
            'div',
            {},
            formCard,
            complex ? complex.cards.map((node) => h('div', { class: 'mt-20' }, node)) : null,
            h('div', { class: 'mt-20' }, recordsCard),
          ),
          h(
            'div',
            {},
            h(
              'section',
              { class: 'u-card' },
              h(
                'div',
                { class: 'u-card__head' },
                h('div', {}, h('h3', { class: 'u-card__title', text: 'Tasks' }), h('p', { class: 'u-card__sub', text: `${tasks.length} tasks · same order as the desktop app, stops on failure` })),
                selectedBadge,
              ),
              h('div', { class: 'u-card__body' }, taskList),
            ),
            h('div', { class: 'mt-20' }, runCard),
          ),
        ),
      );

      refreshPreview();
      renderRecords();
      setMeta({});
      updateRunButton();
      if (complex) complex.updateVisibility();

      // Reattach automatically if a pipeline is still running after a page refresh.
      // Note: only reattach outside startRun, otherwise it competes for the same SSE stream as the run just started,
      // causing duplicate event handling (doubled records, progress stuck midway).
      api
        .listRuns()
        .then((runs) => {
          if (runtime.attached || runtime.running || runtime.runId) return;
          const active = (runs || []).find((run) => run.status === 'running');
          if (!active) return;
          runtime.running = true;
          stopButton.disabled = false;
          updateRunButton();
          applySnapshot(active);
          log('info', `Reattached to running pipeline ${active.id} (mode ${active.mode})`);
          attach(active.id, active.lastSeq);
        })
        .catch(() => {});

      // refresh the “Elapsed” value on the progress bar every second
      const ticker = setInterval(() => {
        if (runtime.running) setMeta({ statusText: 'Running' });
      }, 1000);
      this._ticker = ticker;
      // on unmount, close the SSE stream and the timer so events stop arriving after leaving the page
      this._teardown = () => {
        if (runtime.source) {
          runtime.source.close();
          runtime.source = null;
        }
      };
    },

    unmount() {
      if (this._ticker) clearInterval(this._ticker);
      this._ticker = null;
      if (this._teardown) this._teardown();
      this._teardown = null;
    },
  };
}
