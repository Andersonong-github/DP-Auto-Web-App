/**
 * views/htek.js — Htek / Deltapath IP phone provisioning (Extras → below Text to Speech).
 *
 * Browser port of the desktop "AnderOng Htek/Deltapath FTP AutoProvision Tool".
 * The backend does the real work (ping, ARP, Playwright automation, CSV export);
 * this page keeps the desktop workflow: mode, targets, server parameters, live
 * result table with checkboxes, rescan / delete / export, and a task log.
 *
 * The desktop's global Alt+1 / Alt+2 keystrokes cannot be reproduced by a browser
 * (a page may not type into other applications). This page instead provides
 * configurable in-page shortcuts that copy the matching account's credentials,
 * plus copy buttons. The original desktop tool is left untouched.
 */

import { api } from '../api.js';
import { badge, clear, confirmDialog, copyText, h, icon, log, toast } from '../ui.js';

const DEFAULT_INFO = {
  modes: [
    {
      id: 'provision',
      label: 'Full Provision',
      detail: 'Auto-config + HTTP auth: write the provisioning server parameters and reboot the phone.',
      needsBrowser: true,
    },
    { id: 'scan', label: 'Scan IP & MAC only', detail: 'Ping + ARP only; never logs in.', needsBrowser: false },
    {
      id: 'scan_full',
      label: 'Scan IP, MAC & phone status',
      detail: 'Adds registration status and the MAC shown on the phone page.',
      needsBrowser: true,
    },
  ],
  defaults: {
    mode: 'provision',
    server: 'deltapath-cc.maxis.com.my',
    httpUser: 'spip8014',
    macPrefix: '001fc1',
    auth1User: 'admin',
    auth1Pass: 'admin',
    auth2User: 'admin',
    auth2Pass: '46709394',
    retryCycles: 20,
    retryDelaySeconds: 15,
    allowRouted: false,
  },
  capabilities: { ready: false, browserPath: '', maxTargets: 5000 },
  hotkeyNote: '',
};

const JOB_STORAGE_KEY = 'dp.htek.job';
const HOTKEY_STORAGE_KEY = 'dp.htek.hotkeys';
const HOTKEY_DEFAULTS = ['Alt+Digit1', 'Alt+Digit2'];
let activeCleanup = null;

function loadHotkeys() {
  try {
    const parsed = JSON.parse(localStorage.getItem(HOTKEY_STORAGE_KEY) || 'null');
    if (Array.isArray(parsed) && parsed.length === 2 && parsed.every((item) => typeof item === 'string' && item)) {
      return parsed.slice(0, 2);
    }
  } catch {
    /* localStorage unavailable or invalid: use defaults */
  }
  return [...HOTKEY_DEFAULTS];
}

function saveHotkeys(hotkeys) {
  try {
    localStorage.setItem(HOTKEY_STORAGE_KEY, JSON.stringify(hotkeys));
  } catch {
    /* storage is optional */
  }
}

function codeFromEvent(event) {
  if (event.code) return event.code;
  // WebView2 (the desktop launcher window) can report an empty `code`, e.g.
  // when keys arrive through automation or some remote/IME setups. Fall back to
  // the legacy keyCode and then to the printable key so Alt+1 still matches.
  const legacy = Number(event.keyCode);
  if (legacy >= 48 && legacy <= 57) return `Digit${legacy - 48}`;
  if (legacy >= 96 && legacy <= 105) return `Numpad${legacy - 96}`;
  if (legacy >= 65 && legacy <= 90) return `Key${String.fromCharCode(legacy)}`;
  if (legacy >= 112 && legacy <= 135) return `F${legacy - 111}`;
  const key = event.key || '';
  if (key === ' ') return 'Space';
  if (key.length === 1) {
    if (/[0-9]/.test(key)) return `Digit${key}`;
    if (/[a-zA-Z]/.test(key)) return `Key${key.toUpperCase()}`;
  }
  return key;
}

function comboFromEvent(event) {
  if (!event || ['Control', 'Alt', 'Shift', 'Meta'].includes(event.key)) return null;
  // Require Ctrl/Alt/Meta so plain typing never becomes a shortcut.
  if (!event.ctrlKey && !event.altKey && !event.metaKey) return null;
  const code = codeFromEvent(event);
  if (!code) return null;
  const parts = [];
  if (event.ctrlKey) parts.push('Ctrl');
  if (event.altKey) parts.push('Alt');
  if (event.shiftKey) parts.push('Shift');
  if (event.metaKey) parts.push('Meta');
  parts.push(code);
  return parts.join('+');
}

function displayCombo(combo) {
  return String(combo || '')
    .split('+')
    .map((part) => {
      if (part === 'Ctrl' || part === 'Alt' || part === 'Shift' || part === 'Meta') return part;
      if (part.startsWith('Digit')) return part.slice(5);
      if (part.startsWith('Numpad')) return `Num ${part.slice(6)}`;
      if (part.startsWith('Key')) return part.slice(3);
      if (part === 'ArrowUp') return '↑';
      if (part === 'ArrowDown') return '↓';
      if (part === 'ArrowLeft') return '←';
      if (part === 'ArrowRight') return '→';
      return part === 'Space' ? 'Space' : part;
    })
    .join('+');
}

function toolCard({ title, sub, statusText, statusVariant = '', body, headExtra }) {
  return h(
    'section',
    { class: 'u-card' },
    h(
      'div',
      { class: 'u-card__head' },
      h('div', {}, h('h3', { class: 'u-card__title', text: title }), sub ? h('p', { class: 'u-card__sub', text: sub }) : null),
      headExtra || (statusText ? badge(statusText, statusVariant) : null),
    ),
    h('div', { class: 'u-card__body' }, body),
  );
}

function field(label, control, hint) {
  return h(
    'div',
    { class: 'u-field' },
    h('label', { class: 'u-label' }, label, hint ? h('span', { class: 'u-label__hint', text: hint }) : null),
    control,
  );
}

function textInput(props = {}) {
  return h('input', { class: 'input-plain', type: 'text', spellcheck: 'false', autocomplete: 'off', ...props });
}

function passwordInput(props = {}) {
  const input = h('input', {
    class: 'u-input',
    type: 'password',
    autocomplete: 'new-password',
    spellcheck: 'false',
    ...props,
  });
  let visible = false;
  const eye = h(
    'button',
    {
      class: 'u-input-action',
      type: 'button',
      title: 'Show / hide password',
      'aria-label': 'Show or hide password',
      on: {
        click: () => {
          visible = !visible;
          input.type = visible ? 'text' : 'password';
          clear(eye).appendChild(icon(visible ? 'eyeOff' : 'eye', 17));
        },
      },
    },
    icon('eye', 17),
  );
  const host = h('div', { class: 'u-inputForm htek-pass' }, icon('lock', 18), input, eye);
  return { host, input };
}

function fmtClock(ts) {
  const date = ts ? new Date(ts * 1000) : new Date();
  const pad = (n) => String(n).padStart(2, '0');
  return `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

function parseTargetCount(ipsText, rangeText) {
  const range = String(rangeText || '').trim();
  if (range) {
    if (!range.includes('-')) return 0;
    const parts = range.split('-');
    const startPart = parts[0].trim();
    const endPart = parts[parts.length - 1].trim();
    if (!startPart.includes('.')) return 0;
    const start = Number(startPart.split('.').pop());
    const end = Number(endPart.split('.').pop());
    if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) return 0;
    return end - start + 1;
  }
  const set = new Set();
  String(ipsText || '')
    .split(/[\s,;]+/)
    .map((value) => value.trim())
    .filter((value) => /^(?:\d{1,3}\.){3}\d{1,3}$/.test(value))
    .forEach((value) => set.add(value));
  return set.size;
}

function rowVariant(row) {
  if (row.status === 'RETRY') return 'warn';
  if (row.status === 'STOP') return 'muted';
  if (row.status === 'DONE') {
    return /OFFLINE|MAC MISMATCH|IP CONFLICT|FAIL/.test(row.detail) ? 'err' : 'ok';
  }
  return '';
}

function statusVariant(row) {
  const variant = rowVariant(row);
  if (variant === 'ok') return 'ok';
  if (variant === 'err') return 'err';
  if (variant === 'warn') return 'warn';
  return '';
}

export const htekView = {
  title: 'Htek Provisioning',
  subtitle: 'Scan and auto-provision Htek / Deltapath IP phones — the desktop FTP Provisioning Tool, in the browser',

  mount(root) {
    let info = DEFAULT_INFO;
    let pollTimer = null;
    let pollInFlight = false;
    let actionBusy = false;

    const state = {
      mode: 'provision',
      job: null,
      checked: new Set(),
      tableJobId: null,
      rowNodes: new Map(),
      notifiedState: null,
    };

    let hotkeys = loadHotkeys();
    let recordingIndex = -1;

    /* ------------------------------------------------------------ controls */
    const modeRow = h('div', { class: 'htek-modes' });
    const modeDetail = h('p', { class: 'htek-mode-detail', text: '' });

    const ipsInput = h('textarea', {
      class: 'input-plain htek-targets',
      spellcheck: 'false',
      placeholder: 'One IP per line, for example:\n10.10.7.81\n10.10.7.82\n10.10.7.83',
    });
    ipsInput.value = '10.10.7.81\n10.10.7.82\n10.10.7.83';

    const rangeInput = textInput({ placeholder: 'Example: 10.10.7.1-254' });
    const targetCount = h('span', { class: 'u-label__hint', text: '0 targets' });

    const serverInput = textInput({ placeholder: 'deltapath-cc.maxis.com.my' });
    const httpUserInput = textInput({ placeholder: 'HTTP user' });
    const httpPassField = passwordInput({ placeholder: 'HTTP password' });
    const macPrefixInput = textInput({ placeholder: '001fc1' });

    const auth1User = textInput({ placeholder: 'admin', value: 'admin' });
    const auth1Pass = passwordInput({ placeholder: 'Password', value: 'admin' });
    const auth2User = textInput({ placeholder: 'admin', value: 'admin' });
    const auth2Pass = passwordInput({ placeholder: 'Password', value: '46709394' });

    const allowRoutedToggle = h('input', { type: 'checkbox' });

    const retryCycles = h('input', {
      class: 'input-plain',
      type: 'number',
      min: '0',
      max: '999',
      step: '1',
      value: '20',
      title: '0 = retry until stopped',
    });
    const retryDelay = h('input', {
      class: 'input-plain',
      type: 'number',
      min: '1',
      max: '300',
      step: '1',
      value: '15',
    });

    const capabilityAlert = h('div', { class: 'htek-alert-host' });

    const startButton = h(
      'button',
      { class: 'u-btn u-btn--primary', type: 'button' },
      h('span', { class: 'u-btn__shine' }),
      icon('play', 16),
      'Start task',
    );
    const stopButton = h(
      'button',
      { class: 'u-btn u-btn--danger', type: 'button', disabled: true },
      icon('power', 16),
      'Stop',
    );
    const statusLine = h('div', { class: 'tts-status', text: 'Ready' });
    const progressFill = h('div', { class: 'htek-progress__fill' });
    const progressText = h('span', { class: 'htek-progress__text', text: 'No task yet' });
    const progressHost = h('div', { class: 'htek-progress' }, progressFill);

    const refreshButton = h('button', { class: 'u-btn u-btn--sm u-btn--ghost', type: 'button' }, icon('refresh', 15), 'Refresh');
    const exportButton = h(
      'a',
      { class: 'u-btn u-btn--sm', href: '#', download: 'htek_results.csv' },
      icon('copy', 15),
      'Export CSV',
    );
    const clearButton = h('button', { class: 'u-btn u-btn--sm u-btn--ghost', type: 'button' }, icon('trash', 15), 'Clear all');
    const copyIpsButton = h(
      'button',
      { class: 'u-btn u-btn--sm u-btn--ghost', type: 'button', disabled: true },
      icon('copy', 15),
      'Copy checked IPs',
    );
    const copyMacsButton = h(
      'button',
      { class: 'u-btn u-btn--sm u-btn--ghost', type: 'button', disabled: true },
      icon('copy', 15),
      'Copy checked MACs',
    );
    const rescanButton = h(
      'button',
      { class: 'u-btn u-btn--sm u-btn--ghost', type: 'button', disabled: true },
      icon('refresh', 15),
      'Rescan checked',
    );
    const jobIdLabel = h('span', { class: 'htek-jobid', text: '' });

    const resultHost = h('div', {});
    const jobLog = h('div', { class: 'htek-log' });
    const jobLogCount = h('span', { class: 'htek-log__count', text: '0 lines' });
    const jobLogDetails = h(
      'details',
      { class: 'htek-log-details' },
      h('summary', { class: 'htek-log__head' }, h('span', { text: 'Task log' }), jobLogCount),
      jobLog,
    );

    /* ------------------------------------------------------------- helpers */
    const running = () => Boolean(state.job && state.job.state === 'running');

    function setActionBusy(value) {
      actionBusy = value;
      startButton.disabled = value || running() || (state.mode !== 'scan' && !info.capabilities.ready);
      stopButton.disabled = value || !running();
      refreshButton.disabled = value || !state.job;
      clearButton.disabled = value || !state.job || running();
    }

    function setStatus(text, tone = '') {
      statusLine.textContent = text;
      statusLine.className = `tts-status${tone ? ` tts-status--${tone}` : ''}`;
    }

    function currentMode() {
      return info.modes.find((mode) => mode.id === state.mode) || info.modes[0];
    }

    function renderModes() {
      clear(modeRow);
      info.modes.forEach((mode) => {
        const unavailable = mode.needsBrowser && !info.capabilities.ready;
        const active = mode.id === state.mode;
        modeRow.appendChild(
          h(
            'button',
            {
              class: `htek-mode ${active ? 'is-active' : ''}`,
              type: 'button',
              title: unavailable ? 'Playwright / Chrome is not available on the server host' : mode.detail,
              disabled: unavailable,
              on: {
                click: () => {
                  state.mode = mode.id;
                  renderModes();
                  updateTargetSummary();
                },
              },
            },
            mode.label,
          ),
        );
      });
      const mode = currentMode();
      modeDetail.textContent = mode ? mode.detail : '';
      setActionBusy(false);
    }

    function updateTargetSummary() {
      const count = parseTargetCount(ipsInput.value, rangeInput.value);
      targetCount.textContent = `${count} target${count === 1 ? '' : 's'}`;
      targetCount.classList.toggle('is-over', count > info.capabilities.maxTargets);
    }

    function payload() {
      return {
        mode: state.mode,
        ips: ipsInput.value,
        ipRange: rangeInput.value,
        server: serverInput.value.trim(),
        httpUser: httpUserInput.value.trim(),
        httpPass: httpPassField.input.value,
        macPrefix: macPrefixInput.value.trim(),
        auth1User: auth1User.value.trim(),
        auth1Pass: auth1Pass.input.value,
        auth2User: auth2User.value.trim(),
        auth2Pass: auth2Pass.input.value,
        retryCycles: Number(retryCycles.value) || 0,
        retryDelaySeconds: Number(retryDelay.value) || 15,
        allowRouted: allowRoutedToggle.checked,
      };
    }

    /* ------------------------------------------------------------ rendering */
    function renderProgress() {
      clear(progressText);
      if (!state.job) {
        progressFill.style.width = '0%';
        progressText.textContent = 'No task yet';
        jobIdLabel.textContent = '';
        return;
      }
      const counts = state.job.counts || {};
      const total = Number(counts.total) || 0;
      const processed = Number(counts.processed) || 0;
      const percent = total ? Math.min(100, Math.round((processed / total) * 100)) : 0;
      progressFill.style.width = `${percent}%`;
      progressText.append(
        h('span', { text: `${processed} / ${total} processed` }),
        h('span', { text: `${counts.ok || 0} OK` }),
        h('span', { text: `${counts.fail || 0} failed` }),
        h('span', { text: `${counts.retry || 0} retrying` }),
      );
      jobIdLabel.textContent = `Task ${state.job.id} · ${state.job.state}`;
    }

    function renderLogs() {
      clear(jobLog);
      const entries = (state.job && state.job.logs) || [];
      jobLogCount.textContent = `${entries.length} line${entries.length === 1 ? '' : 's'}`;
      if (!entries.length) {
        jobLog.appendChild(h('div', { class: 'htek-log__empty', text: 'Task log appears here after the first run.' }));
        return;
      }
      entries.slice(-120).forEach((entry) => {
        jobLog.appendChild(
          h(
            'div',
            { class: `htek-log__line htek-log__line--${entry.level}` },
            h('span', { class: 'htek-log__time', text: fmtClock(entry.t) }),
            h('span', { text: entry.message }),
          ),
        );
      });
      jobLog.scrollTop = jobLog.scrollHeight;
    }

    function updateRowNode(node, row) {
      const cells = node.__cells;
      cells.ip.textContent = row.ip;
      cells.mac.textContent = row.mac || '—';
      clear(cells.status).appendChild(badge(row.status, statusVariant(row)));
      cells.detail.textContent = row.detail || '';
      const checkbox = cells.check.querySelector('input');
      checkbox.checked = state.checked.has(row.ip);
      node.className = `htek-row htek-row--${rowVariant(row) || 'idle'}`;
      if (node.__actions) node.__actions.rescan.disabled = running();
    }

    function makeRow(row) {
      const checkbox = h('input', {
        type: 'checkbox',
        checked: state.checked.has(row.ip),
        'aria-label': `Select ${row.ip}`,
        on: {
          change: (event) => {
            if (event.target.checked) state.checked.add(row.ip);
            else state.checked.delete(row.ip);
            syncSelectionControls();
          },
        },
      });
      const statusCell = h('td', {});
      const rescanAction = h(
        'button',
        {
          class: 'copy-cell',
          type: 'button',
          title: 'Rescan this IP',
          disabled: running(),
          on: { click: () => rescan([row.ip]) },
        },
        icon('refresh', 14),
      );
      const node = h(
        'tr',
        { class: `htek-row htek-row--${rowVariant(row) || 'idle'}` },
        h('td', { class: 'htek-check' }, checkbox),
        h('td', { class: 'mono' }, row.ip),
        h('td', { class: 'mono' }, row.mac || '—'),
        statusCell,
        h('td', { class: 'htek-detail' }, row.detail || ''),
        h(
          'td',
          { class: 'htek-row-actions' },
          h(
            'button',
            {
              class: 'copy-cell',
              type: 'button',
              title: 'Open the phone web UI in this PC’s browser',
              on: { click: () => openPhone(row.ip) },
            },
            icon('globe', 14),
          ),
          rescanAction,
          h(
            'button',
            {
              class: 'copy-cell',
              type: 'button',
              title: 'Delete this record',
              on: { click: () => deleteRow(row.ip) },
            },
            icon('trash', 14),
          ),
        ),
      );
      node.__cells = { check: node.firstChild, ip: node.children[1], mac: node.children[2], status: statusCell, detail: node.children[4] };
      node.__actions = { rescan: rescanAction };
      return node;
    }

    function renderResults() {
      const job = state.job;
      if (!job || !job.rows || !job.rows.length) {
        clear(resultHost);
        state.tableJobId = job ? job.id : null;
        state.rowNodes.clear();
        resultHost.appendChild(
          h('div', { class: 'records-empty', text: job ? 'No records. The table was cleared.' : 'No task yet. Configure the targets and press “Start task”.' }),
        );
        syncSelectionControls();
        return;
      }

      if (state.tableJobId !== job.id) {
        clear(resultHost);
        state.tableJobId = job.id;
        state.rowNodes.clear();
      }

      let tbody = resultHost.querySelector('tbody');
      if (!tbody) {
        const selectAll = h('input', {
          type: 'checkbox',
          'aria-label': 'Select all rows',
          on: {
            change: (event) => {
              if (!state.job) return;
              state.job.rows.forEach((row) => {
                if (event.target.checked) state.checked.add(row.ip);
                else state.checked.delete(row.ip);
              });
              state.rowNodes.forEach((node) => {
                node.__cells.check.querySelector('input').checked = event.target.checked;
              });
              syncSelectionControls();
            },
          },
        });
        resultHost.appendChild(
          h(
            'div',
            { class: 'table-wrap' },
            h(
              'table',
              { class: 'table htek-table' },
              h(
                'thead',
                {},
                h(
                  'tr',
                  {},
                  h('th', { class: 'htek-check' }, selectAll),
                  h('th', { text: 'IP address' }),
                  h('th', { text: 'MAC address' }),
                  h('th', { text: 'Status' }),
                  h('th', { text: 'Detail' }),
                  h('th', { text: '' }),
                ),
              ),
              h('tbody', {}),
            ),
          ),
        );
        tbody = resultHost.querySelector('tbody');
      }

      const seen = new Set();
      job.rows.forEach((row) => {
        seen.add(row.ip);
        let node = state.rowNodes.get(row.ip);
        if (!node) {
          node = makeRow(row);
          state.rowNodes.set(row.ip, node);
          tbody.appendChild(node);
        }
        updateRowNode(node, row);
      });
      state.rowNodes.forEach((node, ip) => {
        if (!seen.has(ip)) {
          node.remove();
          state.rowNodes.delete(ip);
          state.checked.delete(ip);
        }
      });
      syncSelectionControls();
    }

    function syncSelectionControls() {
      const job = state.job;
      const count = state.checked.size;
      copyIpsButton.disabled = count === 0;
      copyMacsButton.disabled = count === 0;
      rescanButton.disabled = count === 0 || running();
      clearButton.disabled = actionBusy || !job || running();
      exportButton.classList.toggle('is-disabled', !job || !job.rows || !job.rows.length);
      exportButton.setAttribute('href', job ? api.htekExportUrl(job.id) : '#');
      if (job) {
        const stamp = new Date(job.startedAt * 1000);
        const pad = (n) => String(n).padStart(2, '0');
        exportButton.setAttribute(
          'download',
          `htek_results_${stamp.getFullYear()}${pad(stamp.getMonth() + 1)}${pad(stamp.getDate())}_${pad(stamp.getHours())}${pad(stamp.getMinutes())}${pad(stamp.getSeconds())}.csv`,
        );
      }
    }

    function renderAll() {
      renderProgress();
      renderResults();
      renderLogs();
      setActionBusy(actionBusy);
      if (state.job) {
        const mode = info.modes.find((item) => item.id === state.job.mode);
        if (running()) {
          setStatus(`Running — ${state.job.currentIp || 'preparing'} · cycle ${state.job.cycle || 1}`, 'busy');
        } else if (state.job.state === 'error') {
          setStatus(`Failed: ${state.job.error || 'unknown error'}`, 'err');
        } else if (state.job.state === 'stopped') {
          setStatus('Stopped by the operator', 'err');
        } else {
          setStatus(`Finished${mode ? ` · ${mode.label}` : ''}`, 'ok');
        }
      } else {
        setStatus('Ready');
      }
    }

    /* --------------------------------------------------------------- actions */
    function adoptJob(job) {
      state.job = job;
      state.checked.clear();
      state.tableJobId = null;
      state.rowNodes.clear();
      state.notifiedState = null;
      try {
        sessionStorage.setItem(JOB_STORAGE_KEY, job.id);
      } catch {
        /* storage is optional */
      }
      renderAll();
      if (job.state === 'running') startPolling();
      else stopPolling();
    }

    function stopPolling() {
      if (pollTimer) {
        clearInterval(pollTimer);
        pollTimer = null;
      }
    }

    async function pollOnce() {
      if (pollInFlight || !state.job) return;
      if (state.job.state !== 'running') return;
      pollInFlight = true;
      try {
        const job = await api.htekJob(state.job.id);
        state.job = job;
        renderAll();
        if (job.state !== 'running') {
          stopPolling();
          if (state.notifiedState !== job.state) {
            state.notifiedState = job.state;
            if (job.state === 'finished') {
              const counts = job.counts || {};
              toast('ok', `Task finished: ${counts.ok || 0} OK, ${counts.fail || 0} failed`);
              log('ok', `Htek task ${job.id} finished: ${counts.ok || 0} OK, ${counts.fail || 0} failed`);
            } else if (job.state === 'error') {
              toast('err', `Task failed: ${job.error || 'unknown error'}`);
              log('err', `Htek task ${job.id} failed: ${job.error || 'unknown error'}`);
            } else {
              toast('warn', 'Task stopped');
            }
          }
        }
      } catch (error) {
        log('warn', `Htek status refresh failed: ${error.message}`);
      } finally {
        pollInFlight = false;
      }
    }

    function startPolling() {
      stopPolling();
      pollTimer = setInterval(pollOnce, 1500);
      pollOnce();
    }

    async function startTask() {
      if (actionBusy || running()) return;
      const count = parseTargetCount(ipsInput.value, rangeInput.value);
      if (!count) {
        toast('warn', 'Enter at least one valid IPv4 address or a range such as 10.10.7.1-254.');
        ipsInput.focus();
        return;
      }
      if (count > info.capabilities.maxTargets) {
        toast('warn', `Too many targets (${count}); the limit is ${info.capabilities.maxTargets}.`);
        return;
      }
      if (state.mode !== 'scan' && !info.capabilities.ready) {
        toast('err', 'Provisioning needs Playwright plus a local Chrome/Edge; only SCAN mode is available.');
        return;
      }
      setActionBusy(true);
      setStatus('Starting task…', 'busy');
      try {
        const job = await api.htekStart(payload());
        adoptJob(job);
        toast('ok', 'Task started');
        log('info', `Htek: task ${job.id} started (${state.mode}, ${count} target(s))`);
      } catch (error) {
        setStatus('Start failed', 'err');
        toast('err', error.message);
        log('err', `Htek start failed: ${error.message}`);
      } finally {
        setActionBusy(false);
      }
    }

    async function stopTask() {
      if (!state.job || !running() || actionBusy) return;
      setActionBusy(true);
      try {
        const job = await api.htekStop(state.job.id);
        state.job = job;
        renderAll();
        toast('warn', 'Stop requested');
        log('warn', `Htek: stop requested for task ${job.id}`);
      } catch (error) {
        toast('err', error.message);
      } finally {
        setActionBusy(false);
      }
    }

    async function refreshTask() {
      if (!state.job || actionBusy) return;
      setActionBusy(true);
      try {
        const job = await api.htekJob(state.job.id);
        state.job = job;
        renderAll();
        if (job.state === 'running') startPolling();
      } catch (error) {
        toast('err', error.message);
      } finally {
        setActionBusy(false);
      }
    }

    async function clearAll() {
      if (!state.job || running()) return;
      const ok = await confirmDialog({
        title: 'Clear all results',
        message: 'Remove every row from this task’s result table? The task log is kept.',
        confirmText: 'Clear',
        danger: true,
      });
      if (!ok) return;
      try {
        const job = await api.htekClear(state.job.id);
        state.job = job;
        state.checked.clear();
        renderAll();
        toast('ok', 'Results cleared');
      } catch (error) {
        toast('err', error.message);
      }
    }

    async function deleteRow(ip) {
      if (!state.job) return;
      try {
        const job = await api.htekDeleteRow(state.job.id, ip);
        state.job = job;
        state.checked.delete(ip);
        renderAll();
        log('info', `Htek: record ${ip} deleted`);
      } catch (error) {
        toast('err', error.message);
      }
    }

    async function rescan(ips) {
      if (!state.job || running() || !ips.length) return;
      setActionBusy(true);
      try {
        const job = await api.htekRescan(state.job.id, { ips });
        adoptJob(job);
        toast('ok', `Rescanning ${ips.length} IP(s)`);
        log('info', `Htek: rescan of ${ips.length} IP(s) started as task ${job.id}`);
      } catch (error) {
        toast('err', error.message);
      } finally {
        setActionBusy(false);
      }
    }

    async function openPhone(ip) {
      if (!state.job) return;
      try {
        const result = await api.htekOpen(state.job.id, ip);
        if (!result.ok) toast('warn', `The browser did not acknowledge opening http://${ip}/`);
      } catch (error) {
        toast('err', error.message);
      }
    }

    function checkedList() {
      return Array.from(state.checked);
    }

    /* ---------------------------------------------------------------- wiring */
    [ipsInput, rangeInput].forEach((node) => node.addEventListener('input', updateTargetSummary));
    [auth1User, auth2User, auth1Pass.input, auth2Pass.input].forEach((node) =>
      node.addEventListener('input', scheduleGlobalHotkeySync),
    );
    window.addEventListener('pywebviewready', pushGlobalHotkeys);
    document.addEventListener('keydown', onPageKeydown, true);
    startButton.addEventListener('click', startTask);
    stopButton.addEventListener('click', stopTask);
    refreshButton.addEventListener('click', refreshTask);
    clearButton.addEventListener('click', clearAll);
    rescanButton.addEventListener('click', () => rescan(checkedList()));
    copyIpsButton.addEventListener('click', async () => {
      const ok = await copyText(checkedList().join('\n'));
      toast(ok ? 'ok' : 'err', ok ? `Copied ${state.checked.size} IP(s)` : 'Copy failed');
    });
    copyMacsButton.addEventListener('click', async () => {
      const macs = (state.job ? state.job.rows : [])
        .filter((row) => state.checked.has(row.ip))
        .map((row) => row.mac)
        .filter((mac) => mac && mac !== 'N/A');
      const ok = await copyText(macs.join('\n'));
      toast(ok ? 'ok' : 'err', ok ? `Copied ${macs.length} MAC(s)` : 'Copy failed');
    });
    exportButton.addEventListener('click', (event) => {
      if (!state.job || !state.job.rows || !state.job.rows.length) {
        event.preventDefault();
        toast('warn', 'There are no records to export yet.');
      }
    });

    /* --------------------------------------------------------------- layout */
    const taskCard = toolCard({
      title: 'Task',
      sub: 'Execution mode and the target phones (an IP range wins over the list, exactly like the desktop tool)',
      headExtra: targetCount,
      body: h(
        'div',
        {},
        h('div', { class: 'u-field' }, h('label', { class: 'u-label', text: 'Execution mode' }), modeRow, modeDetail),
        h(
          'div',
          { class: 'u-field mt-16' },
          h('label', { class: 'u-label' }, 'Target IP list', h('span', { class: 'u-label__hint', text: 'one per line, # comments ignored' })),
          ipsInput,
        ),
        h(
          'div',
          { class: 'u-field mt-16' },
          h('label', { class: 'u-label' }, 'IP range', h('span', { class: 'u-label__hint', text: 'last octet, e.g. 10.10.7.1-254' })),
          rangeInput,
        ),
        h(
          'div',
          { class: 'u-field mt-16' },
          h(
            'label',
            { class: 'u-switch' },
            allowRoutedToggle,
            h('span', { class: 'u-switch__track' }),
            'Allow routed / cross-subnet hosts',
          ),
          h('p', {
            class: 'htek-switch-hint',
            text:
              'For phones behind another gateway or static route. ARP has no MAC for them: scan reports reachable, and status/provision read the MAC from the phone page. Leave it off for local-subnet scans.',
          }),
        ),
      ),
    });

    const configCard = toolCard({
      title: 'Provisioning server',
      sub: 'Written to the phone as P237 / P1360 / P1361, then “Autoprovision Now”',
      body: h(
        'div',
        {},
        field('Config server (P237)', serverInput),
        h('div', { class: 'u-field mt-16' }, h('label', { class: 'u-label', text: 'HTTP user (P1360)' }), httpUserInput),
        h('div', { class: 'u-field mt-16' }, h('label', { class: 'u-label', text: 'HTTP password (P1361)' }), httpPassField.host),
        field('MAC vendor prefix', macPrefixInput, 'devices with another prefix are reported as MAC MISMATCH'),
        h(
          'div',
          { class: 'grid htek-two mt-16' },
          field('Retry cycles', retryCycles, '0 = until stopped'),
          field('Retry delay (s)', retryDelay),
        ),
      ),
    });

    const hotkeyNote = h('div', { class: 'u-alert u-alert--info' }, icon('alert', 18), h('div', { text: info.hotkeyNote || '' }));
    const globalHotkeyStatus = h(
      'p',
      { class: 'htek-switch-hint htek-global-status', role: 'status' },
      'Global shortcuts: checking the desktop launcher…',
    );
    const hotkeyButtons = [];

    function refreshHotkeyButton(index) {
      const button = hotkeyButtons[index];
      if (!button) return;
      button.textContent = displayCombo(hotkeys[index]);
      button.title = `Shortcut ${displayCombo(hotkeys[index])} — click to change`;
    }

    async function copyCredentials(index, viaShortcut = false) {
      const userInput = index === 0 ? auth1User : auth2User;
      const passInput = index === 0 ? auth1Pass.input : auth2Pass.input;
      const label = displayCombo(hotkeys[index]);
      const ok = await copyText(`${userInput.value}\t${passInput.value}`);
      const button = hotkeyButtons[index];
      if (button) {
        button.classList.remove('is-hit');
        void button.offsetWidth;
        button.classList.add('is-hit');
        window.setTimeout(() => button.classList.remove('is-hit'), 700);
      }
      if (viaShortcut && ok) log('info', `Htek: ${label} credentials copied by shortcut`);
      toast(ok ? 'ok' : 'err', ok ? `${label} credentials copied` : 'Copy failed');
    }

    function stopRecording() {
      if (recordingIndex >= 0) {
        const button = hotkeyButtons[recordingIndex];
        if (button) {
          button.classList.remove('is-recording');
          refreshHotkeyButton(recordingIndex);
        }
      }
      recordingIndex = -1;
      document.removeEventListener('keydown', onRecordKey, true);
    }

    function onRecordKey(event) {
      if (recordingIndex < 0) return;
      event.preventDefault();
      event.stopPropagation();
      if (event.key === 'Escape') {
        stopRecording();
        return;
      }
      if (event.key === 'Backspace' || event.key === 'Delete') {
        const index = recordingIndex;
        hotkeys[index] = HOTKEY_DEFAULTS[index];
        saveHotkeys(hotkeys);
        stopRecording();
        toast('ok', `Shortcut reset to ${displayCombo(HOTKEY_DEFAULTS[index])}`);
        pushGlobalHotkeys();
        return;
      }
      const combo = comboFromEvent(event);
      if (!combo) return; // wait for Ctrl/Alt/Meta + key
      if (combo === hotkeys[1 - recordingIndex]) {
        toast('warn', 'That shortcut is already used by the other account.');
        return;
      }
      hotkeys[recordingIndex] = combo;
      saveHotkeys(hotkeys);
      stopRecording();
      toast('ok', `Shortcut set to ${displayCombo(combo)}`);
      pushGlobalHotkeys();
    }

    function startRecording(index) {
      stopRecording();
      recordingIndex = index;
      const button = hotkeyButtons[index];
      if (button) {
        button.classList.add('is-recording');
        button.textContent = 'Press keys…';
      }
      document.addEventListener('keydown', onRecordKey, true);
      toast('info', 'Press the new shortcut, for example Alt+3. Backspace resets, Esc cancels.');
    }

    function resetHotkeys() {
      stopRecording();
      hotkeys = [...HOTKEY_DEFAULTS];
      saveHotkeys(hotkeys);
      [0, 1].forEach(refreshHotkeyButton);
      toast('ok', 'Shortcuts reset to Alt+1 and Alt+2');
      pushGlobalHotkeys();
    }

    function onPageKeydown(event) {
      if (recordingIndex >= 0) return;
      const combo = comboFromEvent(event);
      if (!combo) return;
      const index = hotkeys.indexOf(combo);
      if (index < 0) return;
      event.preventDefault();
      event.stopPropagation();
      copyCredentials(index, true);
    }

    // A global shortcut pressed while the launcher window is focused is
    // consumed by the native hook (so PowerToys cannot steal it) and the
    // credentials are copied in Python.  The page polls the copy counter and
    // shows the same feedback as the in-page shortcut.
    const pageHotkeyCopied = (index) => {
      if (index !== 0 && index !== 1) return;
      const label = displayCombo(hotkeys[index]);
      toast('ok', `${label} credentials copied`);
      log('info', `Htek: ${label} credentials copied by global shortcut`);
      const button = hotkeyButtons[index];
      if (button) {
        button.classList.remove('is-hit');
        void button.offsetWidth;
        button.classList.add('is-hit');
        window.setTimeout(() => button.classList.remove('is-hit'), 700);
      }
    };

    /* ------------------------------------------------ Windows-wide shortcuts */
    let hotkeySyncTimer = null;
    let hotkeyPollTimer = null;
    let hotkeyCopySeq = null;
    let lastGlobalCombos = '';

    function consumeHotkeyCopy(copy) {
      if (!copy) return;
      const seq = Number(copy.seq);
      if (!Number.isFinite(seq)) return;
      if (hotkeyCopySeq === null) {
        hotkeyCopySeq = seq; // baseline: do not replay an earlier copy
        return;
      }
      if (seq === hotkeyCopySeq) return;
      hotkeyCopySeq = seq;
      if (copy.index === 0 || copy.index === 1) pageHotkeyCopied(copy.index);
    }

    function consumeHotkeyStatus(status) {
      if (!status) return;
      if (status.ok) {
        setGlobalStatus('active', status.combos);
      } else if (status.error) {
        setGlobalStatus('error', status.error);
      }
      consumeHotkeyCopy(status.last_copy);
    }

    function pollGlobalHotkeys() {
      if (!window.pywebview || !window.pywebview.api) return;
      api
        .htekHotkeyEvent()
        .then(consumeHotkeyCopy)
        .catch(() => {});
    }

    function startHotkeyPolling() {
      if (hotkeyPollTimer) return;
      hotkeyPollTimer = window.setInterval(pollGlobalHotkeys, 1200);
    }

    function setGlobalStatus(kind, detail) {
      const bridge = window.pywebview && window.pywebview.api;
      if (!bridge || typeof bridge.set_htek_hotkeys !== 'function') {
        globalHotkeyStatus.textContent =
          'Global shortcuts: this page is open in a browser tab, so they only copy while this Htek page is focused. ' +
          'Start the app with launcher.py for Windows-wide shortcuts.';
        globalHotkeyStatus.dataset.state = 'browser';
        return;
      }
      if (kind === 'active') {
        const combos = (
          Array.isArray(detail) && detail.length ? detail.map(displayCombo) : hotkeys.map(displayCombo)
        ).join(' / ');
        globalHotkeyStatus.textContent =
          `Global shortcuts active (Windows): ${combos} type user + Tab + password + Enter into the focused window, ` +
          'for example the phone login page. With this window focused they copy the credentials instead.';
        globalHotkeyStatus.dataset.state = 'ok';
      } else if (kind === 'error') {
        globalHotkeyStatus.textContent =
          `Global shortcuts could not start: ${detail || 'unknown error'}. The in-page copy shortcuts still work.`;
        globalHotkeyStatus.dataset.state = 'err';
      } else {
        globalHotkeyStatus.textContent = 'Global shortcuts: connecting to the desktop launcher…';
        globalHotkeyStatus.dataset.state = '';
      }
    }

    function pushGlobalHotkeys() {
      const bridge = window.pywebview && window.pywebview.api;
      if (!bridge || typeof bridge.set_htek_hotkeys !== 'function') {
        setGlobalStatus('browser');
        return;
      }
      const entries = [
        { combo: hotkeys[0], user: auth1User.value, pass: auth1Pass.input.value },
        { combo: hotkeys[1], user: auth2User.value, pass: auth2Pass.input.value },
      ];
      Promise.resolve(bridge.set_htek_hotkeys(entries))
        .then((result) => {
          consumeHotkeyStatus(result);
          if (result && result.ok) {
            startHotkeyPolling();
            const combos = (result.combos || []).join(', ');
            if (combos !== lastGlobalCombos) {
              lastGlobalCombos = combos;
              log('info', `Htek: Windows-wide shortcuts active (${combos || 'none'})`);
            }
          }
        })
        .catch((error) => setGlobalStatus('error', error.message));
    }

    function scheduleGlobalHotkeySync() {
      if (hotkeySyncTimer) clearTimeout(hotkeySyncTimer);
      hotkeySyncTimer = window.setTimeout(() => {
        hotkeySyncTimer = null;
        pushGlobalHotkeys();
      }, 300);
    }

    function credentialRow(index, userInput, passBox) {
      const keyButton = h(
        'button',
        {
          class: 'htek-cred__key',
          type: 'button',
          title: `Shortcut ${displayCombo(hotkeys[index])} — click to change`,
        },
        displayCombo(hotkeys[index]),
      );
      hotkeyButtons[index] = keyButton;
      keyButton.addEventListener('click', () => startRecording(index));
      return h(
        'div',
        { class: 'htek-cred' },
        keyButton,
        userInput,
        passBox.host,
        h(
          'button',
          {
            class: 'u-btn u-btn--sm u-btn--ghost',
            type: 'button',
            title: `Copy user + password for shortcut ${displayCombo(hotkeys[index])} (tab separated)`,
            on: { click: () => copyCredentials(index) },
          },
          icon('copy', 15),
          'Copy',
        ),
      );
    }

    const resetHotkeysButton = h(
      'button',
      { class: 'u-btn u-btn--sm u-btn--ghost', type: 'button', on: { click: resetHotkeys } },
      icon('refresh', 15),
      'Reset shortcuts',
    );

    const credentialsCard = toolCard({
      title: 'Phone HTTP login',
      sub: 'Both accounts are tried, account 2 first (desktop order). Click a key to change its shortcut.',
      body: h(
        'div',
        {},
        capabilityAlert,
        credentialRow(0, auth1User, auth1Pass),
        credentialRow(1, auth2User, auth2Pass),
        h('div', { class: 'mt-16' }, hotkeyNote),
        globalHotkeyStatus,
        h('div', { class: 'mt-16' }, resetHotkeysButton),
      ),
    });

    const progressCard = toolCard({
      title: 'Progress',
      sub: 'The task runs on the backend; this page polls it every 1.5 seconds',
      headExtra: jobIdLabel,
      body: h(
        'div',
        {},
        h('div', { class: 'row tts-actions' }, startButton, stopButton, statusLine),
        h('div', { class: 'htek-progress-wrap' }, progressHost, progressText),
        jobLogDetails,
      ),
    });

    const resultsCard = toolCard({
      title: 'Results & live monitoring',
      sub: 'Check rows to copy or rescan them; export uses the desktop CSV columns',
      headExtra: badge('Extras', 'brand'),
      body: h(
        'div',
        {},
        h('div', { class: 'row htek-toolbar' }, refreshButton, exportButton, rescanButton, copyIpsButton, copyMacsButton, clearButton),
        h('div', { class: 'mt-16' }, resultHost),
      ),
    });

    clear(root).append(
      h(
        'div',
        { class: 'page-head' },
        h('div', {}, h('h2', { text: 'Htek Provisioning' }), h('p', { text: this.subtitle })),
        badge('Extras', 'brand'),
      ),
      h(
        'div',
        { class: 'grid grid--two' },
        h('div', {}, taskCard, h('div', { class: 'mt-20' }, configCard), h('div', { class: 'mt-20' }, credentialsCard)),
        h('div', {}, progressCard, h('div', { class: 'mt-20' }, resultsCard)),
      ),
    );

    /* ------------------------------------------------------------ bootstrap */
    renderModes();
    renderAll();

    if (!info.capabilities.ready) {
      capabilityAlert.appendChild(
        h(
          'div',
          { class: 'u-alert u-alert--warn' },
          icon('alert', 18),
          h('div', {
            text:
              'Playwright / Chrome is not available on the host running the backend. ' +
              'SCAN mode still works; install it with “pip install playwright” (no browser download needed) to enable provisioning.',
          }),
        ),
      );
    }

    function loadPbxDefaults() {
      // P237 = the URL used to sign in to this PBX; P1360/P1361 = its FTP
      // provisioning account. Manual edits made while the request is in flight
      // are preserved instead of being overwritten.
      const before = {
        server: serverInput.value,
        httpUser: httpUserInput.value,
        httpPass: httpPassField.input.value,
      };
      const fill = (input, value, previous) => {
        if (!value) return;
        if (!input.value || input.value === previous) input.value = value;
      };
      api
        .htekPbxDefaults()
        .then((data) => {
          if (!data) return;
          fill(serverInput, data.server, before.server);
          fill(httpUserInput, data.httpUser, before.httpUser);
          fill(httpPassField.input, data.httpPass, before.httpPass);
          scheduleGlobalHotkeySync();
          if (data.ok) {
            log('info', 'P237 / P1360 / P1361 filled from the PBX provisioning settings.');
          } else {
            log('warn', `P237 kept from the PBX login URL; provisioning account not filled: ${data.error || 'unknown reason'}`);
          }
        })
        .catch((error) => log('warn', `PBX provisioning settings unavailable: ${error.message}`));
    }

    api
      .htekInfo()
      .then((data) => {
        if (!data || !Array.isArray(data.modes) || !data.modes.length) return;
        info = data;
        state.mode = (data.defaults && data.defaults.mode) || data.modes[0].id;
        const defaults = data.defaults || {};

        serverInput.value = defaults.server || '';
        httpUserInput.value = defaults.httpUser || '';
        macPrefixInput.value = defaults.macPrefix || '001fc1';
        auth1User.value = defaults.auth1User || 'admin';
        auth1Pass.input.value = defaults.auth1Pass ?? 'admin';
        auth2User.value = defaults.auth2User || 'admin';
        auth2Pass.input.value = defaults.auth2Pass ?? '46709394';
        retryCycles.value = String(defaults.retryCycles ?? 20);
        retryDelay.value = String(defaults.retryDelaySeconds ?? 15);
        allowRoutedToggle.checked = Boolean(defaults.allowRouted);
        if (data.hotkeyNote) hotkeyNote.querySelector('div').textContent = data.hotkeyNote;

        clear(capabilityAlert);
        if (!data.capabilities || !data.capabilities.ready) {
          state.mode = 'scan';
          capabilityAlert.appendChild(
            h(
              'div',
              { class: 'u-alert u-alert--warn' },
              icon('alert', 18),
              h('div', {
                text:
                  'Playwright / Chrome is not available on the host running the backend. ' +
                  'SCAN mode still works; install it with “pip install playwright” to enable provisioning.',
              }),
            ),
          );
        } else {
          capabilityAlert.appendChild(
            h(
              'div',
              { class: 'u-alert u-alert--info' },
              icon('check', 18),
              h('div', {
                text: `Browser automation ready: ${data.capabilities.browserPath || 'installed Chrome/Edge'} (headless).`,
              }),
            ),
          );
        }
        renderModes();
        renderAll();
        scheduleGlobalHotkeySync();
      })
      .catch((error) => log('warn', `Htek capabilities unavailable, using built-in defaults: ${error.message}`))
      .finally(loadPbxDefaults);

    api
      .htekCurrentJob()
      .then((data) => {
        if (data && data.job) {
          adoptJob(data.job);
          log('info', `Htek: restored task ${data.job.id} (${data.job.state})`);
        }
      })
      .catch((error) => log('warn', `Htek task restore failed: ${error.message}`));

    updateTargetSummary();
    setActionBusy(false);
    pushGlobalHotkeys();
    activeCleanup = () => {
      stopPolling();
      stopRecording();
      if (hotkeySyncTimer) {
        clearTimeout(hotkeySyncTimer);
        hotkeySyncTimer = null;
      }
      if (hotkeyPollTimer) {
        clearInterval(hotkeyPollTimer);
        hotkeyPollTimer = null;
      }
      window.removeEventListener('pywebviewready', pushGlobalHotkeys);
      document.removeEventListener('keydown', onPageKeydown, true);
    };
  },

  unmount() {
    // The backend keeps running the task; only the polling timer is page-scoped.
    if (typeof activeCleanup === 'function') {
      activeCleanup();
      activeCleanup = null;
    }
  },
};
