/**
 * views/audit.js — Audit log page.
 *
 * Only records state-changing or security-related actions: login success/failure, logout, pipeline start and end, delete.
 * Read-only queries (search, number lookup, probe) are deliberately not logged, otherwise the log would be flooded.
 */

import { api } from '../api.js';
import { badge, clear, h, icon, log, toast } from '../ui.js';

const KIND_VARIANT = {
  login: 'ok',
  login_failed: 'err',
  logout: '',
  pipeline_start: 'brand',
  pipeline_end: 'brand',
  delete: 'warn',
};

function fmtTime(ts) {
  const date = new Date(ts * 1000);
  const pad = (n) => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

export const auditView = {
  title: 'Audit Log',
  subtitle: 'Audit records of logins, pipeline runs and delete operations',

  mount(root) {
    const runtime = { entries: [], total: 0, persistent: false, kind: '', limit: 200 };

    const kindSelect = h('select', { class: 'input-plain', style: { minWidth: '170px' } }, [
      h('option', { value: '' }, 'All types'),
    ]);
    const limitSelect = h(
      'select',
      { class: 'input-plain', style: { minWidth: '120px' } },
      [50, 200, 500, 1000].map((value) => h('option', { value: String(value), selected: value === runtime.limit }, `${value} rows`)),
    );
    const refreshButton = h('button', { class: 'u-btn u-btn--sm', type: 'button' }, icon('refresh', 15), 'Refresh');
    const exportButton = h('button', { class: 'u-btn u-btn--sm', type: 'button' }, icon('copy', 15), 'Export CSV');
    const summary = h('div', { class: 'runmeta' });
    const tableHost = h('div', {});

    function renderTable() {
      clear(tableHost);

      clear(summary);
      summary.append(
        h('span', {}, 'Total in this process ', h('b', { text: String(runtime.total) })),
        h('span', {}, 'Showing ', h('b', { text: String(runtime.entries.length) })),
        h('span', {}, 'Persistent ', h('b', { text: runtime.persistent ? 'On (JSONL)' : 'Memory only (cleared on restart)' })),
      );

      if (!runtime.entries.length) {
        tableHost.appendChild(h('div', { class: 'records-empty', text: 'No records yet. They appear after a login, pipeline run or delete.' }));
        return;
      }

      tableHost.appendChild(
        h(
          'div',
          { class: 'table-wrap' },
          h(
            'table',
            { class: 'table records-table' },
            h(
              'thead',
              {},
              h(
                'tr',
                {},
                h('th', { text: 'Time' }),
                h('th', { text: 'Type' }),
                h('th', { text: 'Operator' }),
                h('th', { text: 'Source IP' }),
                h('th', { text: 'Result' }),
                h('th', { text: 'Summary' }),
                h('th', { text: '' }),
              ),
            ),
            h(
              'tbody',
              {},
              runtime.entries.map((entry) =>
                h(
                  'tr',
                  { class: entry.ok ? '' : 'is-missing' },
                  h('td', { class: 'mono', text: fmtTime(entry.ts) }),
                  h('td', {}, badge(entry.kindLabel, KIND_VARIANT[entry.kind] || '')),
                  h('td', { class: 'mono', text: entry.actor }),
                  h('td', { class: 'mono', text: entry.sourceIp }),
                  h('td', {}, entry.ok ? badge('Success', 'ok') : badge('Failed', 'err')),
                  h('td', { text: entry.summary }),
                  h(
                    'td',
                    {},
                    Object.keys(entry.detail || {}).length
                      ? h(
                          'button',
                          {
                            class: 'copy-cell',
                            type: 'button',
                            title: 'View details',
                            on: {
                              click: () => {
                                const text = JSON.stringify(entry.detail, null, 2);
                                log('info', `${entry.kindLabel} ${fmtTime(entry.ts)} details: ${text.replace(/\s+/g, ' ').slice(0, 500)}`);
                                toast('ok', 'Details written to the run log at the bottom');
                              },
                            },
                          },
                          icon('search', 14),
                        )
                      : null,
                  ),
                ),
              ),
            ),
          ),
        ),
      );
    }

    async function load() {
      refreshButton.disabled = true;
      try {
        const data = await api.auditEntries({ limit: runtime.limit, kind: runtime.kind });
        runtime.entries = data.entries || [];
        runtime.total = data.total || 0;
        runtime.persistent = Boolean(data.persistent);
        if (kindSelect.options.length <= 1 && (data.kinds || []).length) {
          (data.kinds || []).forEach((kind) => kindSelect.appendChild(h('option', { value: kind.key }, kind.label)));
        }
        renderTable();
      } catch (error) {
        if (error.status !== 401) {
          toast('err', `Failed to read log: ${error.message}`);
          log('err', `Failed to read audit log: ${error.message}`);
        }
      } finally {
        refreshButton.disabled = false;
      }
    }

    kindSelect.addEventListener('change', () => {
      runtime.kind = kindSelect.value;
      load();
    });
    limitSelect.addEventListener('change', () => {
      runtime.limit = Number(limitSelect.value) || 200;
      load();
    });
    refreshButton.addEventListener('click', load);
    exportButton.addEventListener('click', () => {
      const link = h('a', { href: api.auditCsvUrl(2000), download: 'dp-audit.csv' });
      document.body.appendChild(link);
      link.click();
      link.remove();
      log('info', 'Export audit log CSV');
    });

    clear(root).append(
      h(
        'div',
        { class: 'page-head' },
        h(
          'div',
          {},
          h('h2', { text: 'Audit Log' }),
          h('p', { text: 'Records login/logout, pipeline start and end, and delete operations. Passwords and read-only queries are not recorded.' }),
        ),
        badge('Phase 5', 'brand'),
      ),
      h(
        'section',
        { class: 'u-card' },
        h(
          'div',
          { class: 'u-card__head' },
          h('div', {}, h('h3', { class: 'u-card__title', text: 'Filters' })),
          h('div', { class: 'row' }, kindSelect, limitSelect, refreshButton, exportButton),
        ),
        h('div', { class: 'u-card__body' }, summary, tableHost),
      ),
    );

    renderTable();
    load();
  },
};
