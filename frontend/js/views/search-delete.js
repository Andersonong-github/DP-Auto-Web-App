/**
 * views/search-delete.js — "Search & Delete" (desktop parity).
 *
 * Mirrors the desktop DP Auto API tab exactly:
 *   - one row per task type (20 of them: 17 + 3 under "Cinch Contact Center");
 *   - each row has a status light, a checkbox, the label and its own result text;
 *   - one keyword box (group name or customer ID) + a group suggestion list;
 *   - [All Tasks] [No Task] [Search] [Delete];
 *   - Search queries every checked type and writes "Found N: ..." / "Not found";
 *   - Delete removes what each checked type found, walking the list in reverse,
 *     after the delete password and a confirmation.
 *
 * Deliberate difference: the delete password is verified server-side
 * (DP_DELETE_PASSWORD), so the browser never holds it.
 */

import { api } from '../api.js';
import { badge, clear, confirmDialog, h, icon, log, promptDialog, toast } from '../ui.js';

const STATUS_IDLE = 0;
const STATUS_RUNNING = 1;
const STATUS_SUCCESS = 2;
const STATUS_ERROR = 3;

const DOT_CLASS = {
  [STATUS_IDLE]: '',
  [STATUS_RUNNING]: 'u-dot--running',
  [STATUS_SUCCESS]: 'u-dot--success',
  [STATUS_ERROR]: 'u-dot--error',
};

export const searchDeleteView = {
  title: 'Search & Delete',
  subtitle: 'One keyword searches every checked task type; delete removes what was found, bottom-to-top',

  mount(root) {
    const runtime = {
      entities: [],
      rows: new Map(), // key -> { light, statusNode, checkbox }
      selected: new Set(),
      searchedKeys: [],
    };

    // A native <datalist> cannot show a long Group list: Chrome caps how many
    // suggestions it renders and the popup cannot scroll through the rest, so
    // most Groups were invisible even after a refresh. Use a real dropdown that
    // renders every match and scrolls.
    //
    // The panel is attached to <body> and positioned with `fixed` coordinates:
    // the surrounding .u-card uses backdrop-filter, which creates a stacking
    // context, so a panel nested inside it can never paint above the next card.
    const groupPanel = h('div', { class: 'sd-combo', role: 'listbox', hidden: true });
    document.body.appendChild(groupPanel);
    const groupMeta = h('span', { class: 'sd-combo__meta muted' });
    const keywordInput = h('input', {
      class: 'input-plain sd-combo__input',
      placeholder: 'Group name or customer ID',
      autocomplete: 'off',
      spellcheck: 'false',
      style: { minWidth: '250px' },
      role: 'combobox',
      'aria-autocomplete': 'list',
      'aria-expanded': 'false',
      on: {
        input: () => {
          renderGroupPanel();
          openGroupPanel();
        },
        focus: () => {
          if (groups.length) {
            renderGroupPanel();
            openGroupPanel();
          }
        },
        click: () => {
          // A click always opens the list, even when the field already had focus.
          if (groups.length) {
            renderGroupPanel();
            openGroupPanel();
          }
        },
        keydown: (event) => {
          if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            event.preventDefault();
            if (!isGroupPanelOpen()) {
              renderGroupPanel();
              openGroupPanel();
            }
            moveGroupActive(event.key === 'ArrowDown' ? 1 : -1);
            return;
          }
          if (event.key === 'Enter') {
            // Enter picks the highlighted suggestion; otherwise it starts the search.
            if (isGroupPanelOpen() && activeGroupIndex >= 0) {
              event.preventDefault();
              chooseGroupAt(activeGroupIndex);
              return;
            }
            closeGroupPanel();
            doSearch();
            return;
          }
          if (event.key === 'Escape') {
            closeGroupPanel();
          }
        },
      },
    });
    const groupInputWrap = h('div', { class: 'sd-combo-wrap' }, keywordInput);
    const refreshGroupsButton = h(
      'button',
      { class: 'u-btn u-btn--sm u-btn--ghost', type: 'button', title: 'Reload group list', on: { click: () => loadGroups() } },
      icon('refresh', 15),
    );
    const allButton = h('button', { class: 'u-btn u-btn--sm', type: 'button', on: { click: () => setAll(true) } }, 'All Tasks');
    const noneButton = h('button', { class: 'u-btn u-btn--sm', type: 'button', on: { click: () => setAll(false) } }, 'No Task');
    const searchButton = h(
      'button',
      { class: 'u-btn u-btn--primary', type: 'button', on: { click: () => doSearch() } },
      h('span', { class: 'u-btn__shine' }),
      icon('search', 16),
      'Search',
    );
    const deleteButton = h(
      'button',
      { class: 'u-btn u-btn--danger u-btn--sm', type: 'button', disabled: true, on: { click: () => doDelete() } },
      icon('trash', 15),
      'Delete',
    );

    const listHost = h('div', {});
    const summary = h('div', { class: 'runmeta' });

    const toolbarCard = h(
      'section',
      { class: 'u-card' },
      h(
        'div',
        { class: 'u-card__body' },
        h(
          'div',
          { class: 'row' },
          h('span', { class: 'u-label', text: 'Group Name/ID Search:' }),
          groupInputWrap,
          refreshGroupsButton,
          allButton,
          noneButton,
          searchButton,
          deleteButton,
        ),
        h('div', { class: 'mt-16 row row--between' }, summary, groupMeta),
      ),
    );

    let groups = [];

    /* --------------------------------------------------------------- helpers */
    function checkedKeys() {
      return runtime.entities.filter((entity) => runtime.selected.has(entity.key)).map((entity) => entity.key);
    }

    function setLight(key, status) {
      const row = runtime.rows.get(key);
      if (row) row.light.className = `u-dot ${DOT_CLASS[status] || ''}`;
    }

    function setStatusText(key, text, ok) {
      const row = runtime.rows.get(key);
      if (!row) return;
      row.statusNode.textContent = text || '';
      row.statusNode.className = ok ? 'sd-result sd-result--ok' : 'sd-result';
    }

    function updateCounters() {
      clear(summary);
      summary.append(
        h('span', {}, 'Tasks ', h('b', { text: `${runtime.selected.size}/${runtime.entities.length}` })),
        h('span', {}, 'Last search ', h('b', { text: runtime.searchedKeys.length ? `${runtime.searchedKeys.length} type(s)` : '—' })),
      );
      deleteButton.disabled = runtime.selected.size === 0;
    }

    /* ------------------------------------------------------- group dropdown */
    // Every matching Group is rendered; the panel scrolls instead of truncating.
    let groupMatches = [];
    let activeGroupIndex = -1;

    function isGroupPanelOpen() {
      return !groupPanel.hidden;
    }

    function openGroupPanel() {
      if (!groupMatches.length) {
        closeGroupPanel();
        return;
      }
      positionGroupPanel();
      groupPanel.hidden = false;
      keywordInput.setAttribute('aria-expanded', 'true');
    }

    function closeGroupPanel() {
      groupPanel.hidden = true;
      activeGroupIndex = -1;
      keywordInput.setAttribute('aria-expanded', 'false');
    }

    /** Keep the body-mounted panel aligned with the input, including on scroll/resize. */
    function positionGroupPanel() {
      const rect = keywordInput.getBoundingClientRect();
      groupPanel.style.left = `${Math.round(rect.left)}px`;
      groupPanel.style.top = `${Math.round(rect.bottom + 6)}px`;
      groupPanel.style.width = `${Math.round(rect.width)}px`;
    }

    function renderGroupPanel() {
      const text = keywordInput.value.trim().toLowerCase();
      groupMatches = groups.filter((group) => {
        if (!text) return true;
        const label = `${group.name}  [${group.id}]`.toLowerCase();
        return group.name.toLowerCase().startsWith(text) || label.includes(text);
      });

      clear(groupPanel);
      activeGroupIndex = -1;

      if (!groups.length) {
        groupMeta.textContent = 'Group list not loaded';
        groupPanel.appendChild(h('div', { class: 'sd-combo__empty', text: 'No groups loaded — press ↻ to reload.' }));
        return;
      }
      if (!groupMatches.length) {
        groupMeta.textContent = `${groups.length} group(s), no match`;
        groupPanel.appendChild(h('div', { class: 'sd-combo__empty', text: `No group matches “${keywordInput.value.trim()}”.` }));
        return;
      }

      groupMeta.textContent = text
        ? `${groupMatches.length} of ${groups.length} group(s)`
        : `${groups.length} group(s)`;

      groupMatches.forEach((group, index) => {
        groupPanel.appendChild(
          h(
            'button',
            {
              class: 'sd-combo__option',
              type: 'button',
              role: 'option',
              dataset: { index: String(index) },
              on: {
                mousedown: (event) => {
                  event.preventDefault(); // keep focus in the input
                  chooseGroupAt(index);
                },
              },
            },
            h('span', { class: 'sd-combo__name', text: group.name }),
            h('span', { class: 'sd-combo__id', text: `[${group.id}]` }),
          ),
        );
      });
    }

    function highlightGroup() {
      [...groupPanel.querySelectorAll('.sd-combo__option')].forEach((node, index) => {
        const active = index === activeGroupIndex;
        node.classList.toggle('is-active', active);
        if (active) node.scrollIntoView({ block: 'nearest' });
      });
    }

    function moveGroupActive(delta) {
      if (!groupMatches.length) return;
      activeGroupIndex = (activeGroupIndex + delta + groupMatches.length) % groupMatches.length;
      highlightGroup();
    }

    function chooseGroupAt(index) {
      const group = groupMatches[index];
      if (!group) return;
      keywordInput.value = group.name;
      closeGroupPanel();
      keywordInput.focus();
    }

    // Close when clicking outside the combo.
    document.addEventListener('mousedown', (event) => {
      if (!groupInputWrap.contains(event.target)) closeGroupPanel();
    });

    function setAll(checked) {
      runtime.selected.clear();
      runtime.rows.forEach((row, key) => {
        row.checkbox.checked = checked;
        if (checked) runtime.selected.add(key);
      });
      updateCounters();
    }

    /* ---------------------------------------------------------------- render */
    function renderList() {
      clear(listHost);
      const build = (entity) => {
        const light = h('span', { class: 'u-dot' });
        const checkbox = h('input', {
          type: 'checkbox',
          checked: runtime.selected.has(entity.key),
          on: {
            change: () => {
              if (checkbox.checked) runtime.selected.add(entity.key);
              else runtime.selected.delete(entity.key);
              updateCounters();
            },
          },
        });
        const statusNode = h('span', { class: 'sd-result', text: '' });
        runtime.rows.set(entity.key, { light, checkbox, statusNode });
        return h('label', { class: 'sd-row' }, light, checkbox, h('span', { class: 'sd-label', text: entity.label }), statusNode);
      };

      const main = runtime.entities.filter((entity) => entity.group !== 'cinch');
      const cinch = runtime.entities.filter((entity) => entity.group === 'cinch');
      listHost.appendChild(h('div', { class: 'sd-group' }, main.map(build)));
      if (cinch.length) {
        listHost.appendChild(h('div', { class: 'sd-group__title', text: 'Cinch Contact Center' }));
        listHost.appendChild(h('div', { class: 'sd-group' }, cinch.map(build)));
      }
      updateCounters();
    }

    /* --------------------------------------------------------------- actions */
    async function loadEntities() {
      try {
        const data = await api.optionalEntities();
        runtime.entities = data.entities || [];
        runtime.rows.clear();
        runtime.selected.clear();
        renderList();
      } catch (error) {
        if (error.status !== 401) toast('err', `Could not load the task list: ${error.message}`);
      }
    }

    async function loadGroups() {
      refreshGroupsButton.disabled = true;
      try {
        groups = (await api.opsGroups()) || [];
        renderGroupPanel();
        groupMeta.textContent = groups.length ? `${groups.length} group(s) loaded` : 'No groups returned by the PBX';
        log('info', `Group list loaded: ${groups.length} entries`);
        if (!groups.length) {
          toast('warn', 'The PBX returned no groups. Check the connection, then press ↻ to reload.');
        }
      } catch (error) {
        if (error.status !== 401) {
          groupMeta.textContent = 'Group list failed to load';
          log('warn', `Group list failed: ${error.message}`);
          toast('err', `Could not load the group list: ${error.message}`);
        }
      } finally {
        refreshGroupsButton.disabled = false;
      }
    }

    async function doSearch() {
      const keyword = keywordInput.value.trim();
      if (!keyword) {
        toast('warn', 'Enter a group name or customer ID.');
        return;
      }
      const keys = checkedKeys();
      if (!keys.length) {
        toast('warn', 'Check at least one task.');
        return;
      }

      keys.forEach((key) => {
        setLight(key, STATUS_RUNNING);
        // "Searching…" must not count as a hit, so it keeps the neutral style
        setStatusText(key, 'Searching…', false);
      });
      searchButton.disabled = true;
      log('info', `Search & Delete: "${keyword}" across ${keys.length} task(s)`);

      try {
        const data = await api.optionalSearch({ keyword, entities: keys });
        runtime.searchedKeys = keys;
        if (data.customerId) log('info', `Resolved to "${data.resolvedKeyword}" (customer ID ${data.customerId})`);

        let found = 0;
        (data.results || []).forEach((result) => {
          if (result.error) {
            setLight(result.key, STATUS_ERROR);
            setStatusText(result.key, `Error: ${result.error}`, false);
            return;
          }
          if (result.itemCount > 0) {
            found += 1;
            setLight(result.key, STATUS_SUCCESS);
            setStatusText(result.key, result.status, true);
          } else {
            setLight(result.key, STATUS_ERROR);
            setStatusText(result.key, result.status || 'Not found', false);
          }
        });
        updateCounters();
        toast(found ? 'ok' : 'warn', found ? `${found} task type(s) found something` : 'Nothing found');
      } catch (error) {
        if (error.status !== 401) {
          keys.forEach((key) => {
            setLight(key, STATUS_ERROR);
            setStatusText(key, error.message, false);
          });
          toast('err', error.message);
          log('err', `Search failed: ${error.message}`);
        }
      } finally {
        searchButton.disabled = false;
      }
    }

    async function doDelete() {
      const keys = checkedKeys();
      if (!keys.length) return;

      const password = await promptDialog({
        title: 'Delete password',
        message: `Delete what the search found for ${keys.length} checked task(s). This cannot be undone.`,
        label: 'Password',
        type: 'password',
        confirmText: 'Continue',
      });
      if (password === null) {
        log('info', 'Delete cancelled');
        return;
      }

      const labels = runtime.entities.filter((entity) => keys.includes(entity.key)).map((entity) => entity.label);
      const ok = await confirmDialog({
        title: `Delete ${keys.length} checked task(s)?`,
        message: labels.join(', '),
        confirmText: 'Delete',
        danger: true,
      });
      if (!ok) {
        log('info', 'Delete cancelled');
        return;
      }

      deleteButton.disabled = true;
      log('warn', `Deleting checked tasks bottom-to-top: ${[...labels].reverse().join(', ')}`);
      try {
        const data = await api.optionalDelete({ entities: keys, password });
        (data.results || []).forEach((result) => {
          setLight(result.key, result.deleted > 0 ? STATUS_SUCCESS : (result.failed > 0 ? STATUS_ERROR : STATUS_IDLE));
          setStatusText(result.key, result.status, result.deleted > 0);
          if (result.failed > 0) {
            (result.results || []).filter((r) => !r.ok).forEach((r) => {
              log('err', `  ${result.label} delete failed (${r.id || 'unknown'}): ${r.detail || 'unknown error'}`);
            });
          }
        });
        toast(data.failed ? 'warn' : 'ok', `Deleted ${data.deleted}, failed ${data.failed}`);
        log(data.failed ? 'warn' : 'ok', `Delete finished: ${data.deleted} deleted / ${data.failed} failed`);
      } catch (error) {
        if (error.status !== 401) {
          toast('err', error.message);
          log('err', `Delete failed: ${error.message}`);
        }
      } finally {
        runtime.searchedKeys = [];
        updateCounters();
      }
    }

    /* ---------------------------------------------------------------- layout */
    clear(root).append(
      h(
        'div',
        { class: 'page-head' },
        h(
          'div',
          {},
          h('h2', { text: 'Search & Delete' }),
          h('p', {
            text: 'Same as the desktop page: one keyword searches every checked task type, each row reports its own result, and Delete removes what was found bottom-to-top.',
          }),
        ),
        badge('Optional Task', 'brand'),
      ),
      toolbarCard,
      h('section', { class: 'u-card mt-20' }, h('div', { class: 'u-card__body' }, listHost)),
    );

    // Reposition/close the body-mounted panel as the layout moves under it.
    const onReflow = () => {
      if (isGroupPanelOpen()) positionGroupPanel();
    };
    const onDocumentPointer = (event) => {
      if (!groupInputWrap.contains(event.target) && !groupPanel.contains(event.target)) closeGroupPanel();
    };
    window.addEventListener('scroll', onReflow, true);
    window.addEventListener('resize', onReflow);
    document.addEventListener('mousedown', onDocumentPointer);

    renderList();
    loadEntities();
    loadGroups();

    // The view is torn down via unmount(); the panel lives outside `root`.
    this._teardown = () => {
      window.removeEventListener('scroll', onReflow, true);
      window.removeEventListener('resize', onReflow);
      document.removeEventListener('mousedown', onDocumentPointer);
      groupPanel.remove();
    };
  },

  unmount() {
    if (this._teardown) this._teardown();
    this._teardown = null;
  },
};
