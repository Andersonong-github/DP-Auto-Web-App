/**
 * views/siptrunk.js — SIP Trunk status page.
 *
 * Data comes from the backend /api/ops/pbx/siptrunk/status (merges the siptrunk list with activepeer),
 * the desktop optional task opt_siptrunkstatus.py: supports filtering by peer ID and timed auto-refresh.
 */

import { api } from '../api.js';
import { badge, clear, copyText, dot, h, icon, log, toast } from '../ui.js';

const AUTO_OPTIONS = [
  { label: 'Off', seconds: 0 },
  { label: 'Every 5s', seconds: 5 },
  { label: 'Every 10s', seconds: 10 },
  { label: 'Every 20s', seconds: 20 },
  { label: 'Every 30s', seconds: 30 },
  { label: 'Every 1 min', seconds: 60 },
  { label: 'Every 5 min', seconds: 300 },
];

function statusVariant(status) {
  const text = String(status || '').toLowerCase();
  if (text.includes('regist') || text.includes('ok') || text.includes('up') || text.includes('online')) return 'success';
  if (text.includes('fail') || text.includes('down') || text.includes('unreach') || text.includes('reject')) return 'error';
  return 'idle';
}

export const siptrunkView = {
  title: 'SIP Trunk Status',
  subtitle: 'Live status of trunks and online peers',

  mount(root) {
    let data = null;
    let selected = new Set();
    let timer = null;
    let loading = false;

    const peerBox = h('div', { class: 'row', style: { gap: '12px', alignItems: 'center' } });
    const autoSelect = h(
      'select',
      { class: 'input-plain', style: { width: '150px' } },
      AUTO_OPTIONS.map((option) => h('option', { value: String(option.seconds) }, option.label)),
    );
    const refreshButton = h('button', { class: 'u-btn u-btn--sm', type: 'button' }, icon('refresh', 15), 'Refresh');
    const tableHost = h('div', {});
    const meta = h('div', { class: 'runmeta' });

    let isDropdownOpen = false;
    let peerFilterQuery = '';
    const dropdownWrap = h('div', { class: 'peer-dropdown' });

    function getTriggerText(peers) {
      if (!peers.length) return 'No trunks read';
      if (!selected.size) return '0 selected (show all trunks)';
      if (selected.size === peers.length) return `All trunks (${peers.length} selected)`;
      return `${selected.size} of ${peers.length} trunks selected`;
    }

    function renderPeers() {
      clear(peerBox);
      const peers = (data && data.peerIds) || [];
      if (!peers.length) {
        peerBox.appendChild(h('span', { class: 'muted', text: '(no trunk peer IDs read)' }));
        return;
      }

      const triggerLabel = h('span', { text: getTriggerText(peers) });
      const triggerBtn = h(
        'button',
        {
          class: 'peer-dropdown__trigger',
          type: 'button',
          title: 'Click to select trunks from dropdown',
          on: {
            click: (e) => {
              e.stopPropagation();
              isDropdownOpen = !isDropdownOpen;
              dropdownWrap.classList.toggle('is-open', isDropdownOpen);
              const cardEl = dropdownWrap.closest('.u-card');
              if (cardEl) cardEl.classList.toggle('has-open-dropdown', isDropdownOpen);
              if (isDropdownOpen) {
                const search = dropdownWrap.querySelector('.peer-dropdown__search');
                if (search) search.focus();
              }
            },
          },
        },
        h('span', { class: 'row', style: { gap: '8px' } }, icon('server', 15), triggerLabel),
        icon('chevronDown', 13),
      );

      const searchInput = h('input', {
        class: 'peer-dropdown__search',
        type: 'text',
        placeholder: 'Filter trunk IDs...',
        value: peerFilterQuery,
        on: {
          click: (e) => e.stopPropagation(),
          input: (e) => {
            peerFilterQuery = e.target.value.toLowerCase().trim();
            renderItemsList();
          },
        },
      });

      const selectAllBtn = h(
        'button',
        {
          class: 'u-btn u-btn--xs',
          type: 'button',
          on: {
            click: (e) => {
              e.stopPropagation();
              selected = new Set(peers);
              triggerLabel.textContent = getTriggerText(peers);
              renderItemsList();
              renderTable();
            },
          },
        },
        'Select All',
      );

      const clearBtn = h(
        'button',
        {
          class: 'u-btn u-btn--xs u-btn--ghost',
          type: 'button',
          on: {
            click: (e) => {
              e.stopPropagation();
              selected.clear();
              triggerLabel.textContent = getTriggerText(peers);
              renderItemsList();
              renderTable();
            },
          },
        },
        'Clear',
      );

      const listContainer = h('div', { class: 'peer-dropdown__list' });

      function renderItemsList() {
        clear(listContainer);
        const filtered = peers.filter((p) => !peerFilterQuery || p.toLowerCase().includes(peerFilterQuery));
        if (!filtered.length) {
          listContainer.appendChild(h('span', { class: 'muted', style: { padding: '8px', fontSize: '12px' }, text: 'No matching trunks' }));
          return;
        }

        filtered.forEach((peer) => {
          const checkbox = h('input', {
            type: 'checkbox',
            checked: selected.has(peer),
            on: {
              change: (e) => {
                e.stopPropagation();
                if (checkbox.checked) selected.add(peer);
                else selected.delete(peer);
                triggerLabel.textContent = getTriggerText(peers);
                renderTable();
              },
            },
          });

          listContainer.appendChild(
            h(
              'label',
              {
                class: 'peer-dropdown__item',
                on: { click: (e) => e.stopPropagation() },
              },
              checkbox,
              h('span', { text: peer }),
            ),
          );
        });
      }
      renderItemsList();

      const applyBtn = h(
        'button',
        {
          class: 'u-btn u-btn--sm u-btn--primary u-btn--block',
          type: 'button',
          on: {
            click: (e) => {
              e.stopPropagation();
              isDropdownOpen = false;
              dropdownWrap.classList.remove('is-open');
              const cardEl = dropdownWrap.closest('.u-card');
              if (cardEl) cardEl.classList.remove('has-open-dropdown');
              renderTable();
            },
          },
        },
        'Apply Selection',
      );

      const menu = h(
        'div',
        {
          class: 'peer-dropdown__menu',
          on: { click: (e) => e.stopPropagation() },
        },
        h('div', { class: 'peer-dropdown__tools' }, selectAllBtn, clearBtn),
        searchInput,
        listContainer,
        applyBtn,
      );

      clear(dropdownWrap);
      dropdownWrap.className = `peer-dropdown ${isDropdownOpen ? 'is-open' : ''}`;
      dropdownWrap.append(triggerBtn, menu);

      peerBox.appendChild(dropdownWrap);

      // If specific trunks are selected, show quick reset pill
      if (selected.size > 0) {
        peerBox.appendChild(
          h(
            'button',
            {
              class: 'u-btn u-btn--xs u-btn--ghost',
              type: 'button',
              title: 'Reset to show all trunks',
              on: {
                click: () => {
                  selected.clear();
                  renderPeers();
                  renderTable();
                },
              },
            },
            icon('trash', 13),
            'Show all',
          ),
        );
      }
    }

    const onDocClick = (e) => {
      if (isDropdownOpen && !dropdownWrap.contains(e.target)) {
        isDropdownOpen = false;
        dropdownWrap.classList.remove('is-open');
        const cardEl = dropdownWrap.closest('.u-card');
        if (cardEl) cardEl.classList.remove('has-open-dropdown');
      }
    };
    document.addEventListener('click', onDocClick);

    function visibleRows() {
      const rows = (data && data.rows) || [];
      if (!selected.size) return rows;
      return rows.filter((row) => selected.has(row.name));
    }

    function renderTable() {
      clear(tableHost);
      const rows = visibleRows();
      const allCount = ((data && data.rows) || []).length;

      clear(meta);
      meta.append(
        h('span', {}, 'Online peers ', h('b', { text: String(allCount) })),
        h('span', {}, 'Showing ', h('b', { text: String(rows.length) })),
        h('span', {}, 'Total trunks ', h('b', { text: String((data && data.trunkCount) || 0) })),
        h('span', {}, 'Updated ', h('b', { text: data ? new Date(data.checkedAt * 1000).toLocaleTimeString() : '—' })),
      );

      if (!rows.length) {
        tableHost.appendChild(
          h('div', { class: 'records-empty', text: data ? 'No matching online peers.' : 'No data loaded yet; click Refresh at the top right.' }),
        );
        return;
      }

      tableHost.appendChild(
        h(
          'div',
          { class: 'table-wrap' },
          h(
            'table',
            { class: 'table' },
            h(
              'thead',
              {},
              h(
                'tr',
                {},
                h('th', { text: 'Peer ID / Name' }),
                h('th', { text: 'Host' }),
                h('th', { text: 'Port' }),
                h('th', { text: 'Status' }),
                h('th', { text: 'Group' }),
                h('th', { text: '' }),
              ),
            ),
            h(
              'tbody',
              {},
              rows.map((row) =>
                h(
                  'tr',
                  {},
                  h('td', { class: 'mono' }, h('div', { class: 'row' }, dot(statusVariant(row.status)), h('span', { text: row.name }))),
                  h('td', { class: 'mono', text: row.host || '—' }),
                  h('td', { class: 'mono', text: row.port || '—' }),
                  h('td', {}, badge(row.status || 'Unknown', statusVariant(row.status) === 'success' ? 'ok' : statusVariant(row.status) === 'error' ? 'err' : '')),
                  h('td', { class: 'mono', text: row.group || '—' }),
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
                            const ok = await copyText(`${row.name}\t${row.host}\t${row.port}\t${row.status}`);
                            toast(ok ? 'ok' : 'err', ok ? 'Row copied' : 'Copy failed');
                          },
                        },
                      },
                      icon('copy', 14),
                    ),
                  ),
                ),
              ),
            ),
          ),
        ),
      );
    }

    async function load({ silent = false } = {}) {
      if (loading) return;
      loading = true;
      refreshButton.disabled = true;
      try {
        data = await api.siptrunkStatus();
        // Drop peers that no longer exist this time
        selected = new Set([...selected].filter((peer) => data.peerIds.includes(peer)));
        renderPeers();
        renderTable();
        if (!silent) log('info', `SIP Trunk status: ${(data.rows || []).length} online peers / ${data.trunkCount} trunks`);
      } catch (error) {
        if (error.status === 401) return;
        if (!silent) {
          toast('err', `Load failed: ${error.message}`);
          log('err', `Failed to load SIP Trunk status: ${error.message}`);
        }
      } finally {
        loading = false;
        refreshButton.disabled = false;
      }
    }

    function restartTimer() {
      if (timer) clearInterval(timer);
      timer = null;
      const seconds = Number(autoSelect.value) || 0;
      if (seconds > 0) {
        timer = setInterval(() => load({ silent: true }), seconds * 1000);
        log('info', `Auto-refresh on: every ${seconds}s`);
      }
    }

    refreshButton.addEventListener('click', () => load());
    autoSelect.addEventListener('change', restartTimer);

    clear(root).append(
      h(
        'div',
        { class: 'page-head' },
        h('div', {}, h('h2', { text: 'SIP Trunk Status' }), h('p', { text: 'Trunk list and online peer status shown together; check peer IDs to view only the ones you care about.' })),
        h('div', { class: 'row' }, h('span', { class: 'muted', text: 'Auto-refresh' }), autoSelect, refreshButton),
      ),
      h(
        'section',
        { class: 'u-card u-card--filter' },
        h(
          'div',
          { class: 'u-card__head' },
          h('div', {}, h('h3', { class: 'u-card__title', text: 'Peer ID Filter' }), h('p', { class: 'u-card__sub', text: 'Nothing checked shows all' })),
          badge('GET /api/ops/pbx/siptrunk/status', 'brand'),
        ),
        h('div', { class: 'u-card__body' }, peerBox),
      ),
      h('section', { class: 'u-card u-card--table mt-20' }, h('div', { class: 'u-card__body' }, meta, tableHost)),
    );

    this._teardown = () => {
      if (timer) clearInterval(timer);
      timer = null;
      document.removeEventListener('click', onDocClick);
    };

    renderTable();
    load();
  },

  unmount() {
    if (this._teardown) this._teardown();
    this._teardown = null;
  },
};
