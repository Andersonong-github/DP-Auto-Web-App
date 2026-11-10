/**
 * views/pipeline-complex.js — parameter sections unique to Complex mode.
 *
 * The sub-options of the desktop "Complex" page beyond the standard params:
 *   Context suffixes / Permission Group four classes / ACL Group three kinds /
 *   User Profile four classes + recording + number context / ACL User three roles /
 *   Custom Outbound Routing (one number + context) / Username + Email lists.
 *
 * These blocks appear only when the matching task is checked (same as desktop).
 */

import { api } from '../api.js';
import { badge, clear, h, icon, log, toast } from '../ui.js';
import { parseExtRange } from './tools.js';

/* Identical to desktop main.py _bind_pg_sub_options */
const PG_FRONT_ITEMS = [
  ['c_i', ['Custom', '_Internal']],
  ['i_c', ['_Internal', 'Custom']],
  ['c', ['Custom']],
  ['i', ['_Internal']],
];
const PG_FIXED_BY_CLASS = { 1: [], 2: ['_Fixed'], 3: ['_Fixed', '_Mobile'], 4: ['_Fixed', '_Mobile', '_IDD'] };
const CTX_SUFFIXES = ['_Internal', '_Fixed', '_Mobile', '_IDD'];
const ACL_GROUPS = ['_Managers', '_Supervisors', '_Users'];
const PROFILE_CLASSES = ['Class_1', 'Class_2', 'Class_3', 'Class_4'];
const CUSTOM_CTX_SUFFIXES = ['_Internal', '_Fixed', '_Mobile', '_IDD'];

/** Permission Group dropdown options: real context names when server data exists, else suffix literals. */
function pgOptions(classNum, serverData) {
  const fixed = PG_FIXED_BY_CLASS[classNum] || [];
  const literals = PG_FRONT_ITEMS.map(([key, front]) => ({ key, label: [...front, ...fixed].join(', ') }));
  if (serverData) {
    const seen = new Map();
    PG_FRONT_ITEMS.forEach(([key, front]) => {
      const parts = [];
      front.forEach((name) => {
        if (name === 'Custom' && serverData.customCtx) parts.push(serverData.customCtx);
        if (name === '_Internal' && serverData.internalCtx) parts.push(serverData.internalCtx);
      });
      parts.push(...(serverData.fixed || []).slice(0, classNum - 1));
      /* Skip combos the server cannot satisfy (e.g. "Custom" with no custom context):
         an empty label would otherwise become a blank, unselectable dropdown entry. */
      const label = parts.join(', ');
      if (label && !seen.has(label)) seen.set(label, key);
    });
    if (seen.size) return [...seen.entries()].map(([label, key]) => ({ key, label }));
  }
  return literals;
}

function card(title, sub, body, headExtra) {
  return h(
    'section',
    { class: 'u-card' },
    h(
      'div',
      { class: 'u-card__head' },
      h('div', {}, h('h3', { class: 'u-card__title', text: title }), sub ? h('p', { class: 'u-card__sub', text: sub }) : null),
      headExtra || null,
    ),
    h('div', { class: 'u-card__body' }, body),
  );
}

function switchRow(label, checked, onChange) {
  const box = h('input', {
    type: 'checkbox',
    checked,
    on: { change: () => onChange(box.checked) },
  });
  return { node: h('label', { class: 'u-switch' }, box, h('span', { class: 'u-switch__track' }), label), box };
}

/**
 * @param {object} options
 * @param {Set<string>} options.selected Currently checked task names (live reference)
 * @param {object} options.prefs Last saved Complex mode params
 * @param {() => void} options.persist Persist callback after param changes
 * @param {object} [options.state] Runtime state object (borrowed to store custom_payloads)
 * @param {Map<string, HTMLElement>} [options.params] Parameter inputs by key (group_name / context_prefix …)
 */
export function buildComplexSection({ selected, prefs = {}, persist = () => {}, state = {}, lists = {}, params = new Map() }) {
  /* ---------------------------------------------------------- runtime state */
  const usernamesArea = lists.usernamesArea || null;
  const emailsArea = lists.emailsArea || null;
  const paramValue = (key) => {
    const el = params.get(key);
    return el && typeof el.value === 'string' ? el.value.trim() : '';
  };

  /** Server-wide context names for both Number-context and Permission Group dropdowns. */
  let profileAllContexts = [];
  let rebuildProfileCtxOptions = () => {};
  const cfg = {
    ctxSuffixes: new Set(prefs.context_suffixes || CTX_SUFFIXES),
    ctxCustom: prefs.ctxCustom || '',
    pg: PROFILE_CLASSES.map((_, index) => ({
      enabled: (prefs.pg ? prefs.pg[index]?.enabled : true) !== false,
      key: (prefs.pg ? prefs.pg[index]?.key : 'c_i') || 'c_i',
      /* Explicit context list picked by hand (tick order); overrides ``key`` when non-empty. */
      ctx: Array.isArray(prefs.pg ? prefs.pg[index]?.ctx : null) ? [...prefs.pg[index].ctx] : [],
    })),
    pgServerData: null,
    /* One context forced to position 1 of every enabled Class (chosen from a single dropdown). */
    pgLead: prefs.pg_lead || '',
    aclGroups: new Set(prefs.acl_group_selection || ['_Managers', '_Users']),
    profileClasses: new Set(prefs.profile_classes_selection || PROFILE_CLASSES),
    profileRecording: Boolean(prefs.profile_recording),
    profileNumberContext: prefs.profile_number_context || '',
    aclRoles: {
      managers: { checked: prefs.acl_managers_checked !== false, value: prefs.acl_managers || '' },
      supervisors: { checked: Boolean(prefs.acl_supervisors_checked), value: prefs.acl_supervisors || '' },
      users: { checked: prefs.acl_users_checked !== false, value: prefs.acl_users || '' },
    },
    usernames: prefs.usernames || '',
    emails: prefs.emails || '',
    /* Complex-only: one hand-picked rule instead of the 10 defaults (desktop Custom Routing).
       The mode itself is driven by the mutually exclusive "Custom Outbound Routing" task. */
    customNumber: prefs.custom_number || '',
    customContext: prefs.custom_context || '_Fixed',
  };
  state.customPayloads = state.customPayloads || {};

  const save = () => {
    const values = {
      context_suffixes: [...cfg.ctxSuffixes],
      ctxCustom: cfg.ctxCustom,
      pg: cfg.pg,
      pg_lead: cfg.pgLead,
      acl_group_selection: [...cfg.aclGroups],
      profile_classes_selection: [...cfg.profileClasses],
      profile_recording: cfg.profileRecording,
      profile_number_context: cfg.profileNumberContext,
      acl_managers: cfg.aclRoles.managers.value,
      acl_managers_checked: cfg.aclRoles.managers.checked,
      acl_supervisors: cfg.aclRoles.supervisors.value,
      acl_supervisors_checked: cfg.aclRoles.supervisors.checked,
      acl_users: cfg.aclRoles.users.value,
      acl_users_checked: cfg.aclRoles.users.checked,
      usernames: usernamesArea ? usernamesArea.value : cfg.usernames,
      emails: emailsArea ? emailsArea.value : cfg.emails,
      custom_number: cfg.customNumber,
      custom_context: cfg.customContext,
    };
    persist(values);
  };

  if (usernamesArea) {
    usernamesArea.addEventListener('input', save);
  }
  if (emailsArea) {
    emailsArea.addEventListener('input', save);
  }

  /* ------------------------------------------------------ Context suffix */
  const ctxCustomInput = h('input', {
    class: 'input-plain',
    placeholder: 'Custom suffix (optional)',
    value: cfg.ctxCustom,
    on: {
      input: () => {
        cfg.ctxCustom = ctxCustomInput.value.trim();
        save();
      },
    },
  });
  const ctxCard = card(
    'Context suffix',
    'Check the contexts to create; the custom suffix is appended as-is',
    h(
      'div',
      { class: 'row' },
      ...CTX_SUFFIXES.map((suffix) =>
        switchRow(suffix, cfg.ctxSuffixes.has(suffix), (checked) => {
          if (checked) cfg.ctxSuffixes.add(suffix);
          else cfg.ctxSuffixes.delete(suffix);
          save();
        }).node,
      ),
    ),
    h('div', { class: 'mt-16', style: { maxWidth: '260px' } }, ctxCustomInput),
  );

  /* --------------------------------------------------- Permission Group */
  const pgOrderLabels = [];
  const pgSelects = [];
  const pgCtxButtons = [];

  /**
   * Every context name the picker can offer, in a stable order:
   *  1. contexts that already exist on the server for this Group (whatever their name —
   *     a Class may include a pre-existing context that does not follow the prefix),
   *  2. the prefix-matched rows,
   *  3. the four standard suffixes built from Context Prefix,
   *  4. the custom suffix typed in the Context card.
   */
  function availableContexts() {
    const out = [];
    const push = (value) => {
      const name = String(value || '').trim();
      if (name && !out.includes(name)) out.push(name);
    };
    const server = cfg.pgServerData;
    if (server) {
      /* Group-wide rows first: this is what lets an operator put an existing, differently
         named context ahead of _Internal (e.g. Task 2 did not create _Internal at all). */
      (server.groupAll || []).forEach(push);
      (server.all || []).forEach(push);
      push(server.customCtx);
      push(server.internalCtx);
      (server.fixed || []).forEach(push);
    }
    (profileAllContexts || []).forEach(push);
    const prefix = paramValue('context_prefix') || paramValue('group_name');
    const base = prefix.endsWith('_') ? prefix.slice(0, -1) : prefix;
    if (base) {
      CTX_SUFFIXES.forEach((suffix) => push(`${base}${suffix}`));
      if (cfg.ctxCustom) push(cfg.ctxCustom.startsWith(base) ? cfg.ctxCustom : `${base}_${cfg.ctxCustom}`);
    }
    return out;
  }

  /** Modal multi-select: tick order defines the order written to ``contextInclude_value``. */
  function pickContexts(classLabel, current) {
    return new Promise((resolve) => {
      let settled = false;
      const order = new Map(current.map((name, i) => [name, i + 1]));
      const nextNum = () => order.size + 1;
      const boxes = new Map();
      const labels = new Map();

      const finish = (value) => {
        if (settled) return;
        settled = true;
        document.removeEventListener('keydown', onKey);
        backdrop.remove();
        resolve(value);
      };
      const onKey = (event) => {
        if (event.key === 'Escape') finish(null);
      };

      const relabel = () => {
        [...order.entries()]
          .sort((a, b) => a[1] - b[1])
          .forEach(([name], i) => order.set(name, i + 1));
        labels.forEach((span, name) => {
          span.textContent = order.has(name) ? `${order.get(name)}. ${name}` : name;
        });
        renderPicked();
      };
      const toggle = (name, checked) => {
        if (checked) {
          if (!order.has(name)) order.set(name, nextNum());
        } else {
          order.delete(name);
        }
        relabel();
      };

      /* ---- "Selected (in order)" list: the only place the final order can be changed ---- */
      const picked = h('ol', { class: 'ctxpick__picked' });

      /** Move an already-selected context up/down so it can be put ahead of the others. */
      const move = (name, delta) => {
        const entries = [...order.entries()].sort((a, b) => a[1] - b[1]).map(([key]) => key);
        const from = entries.indexOf(name);
        const to = from + delta;
        if (from < 0 || to < 0 || to >= entries.length) return;
        entries.splice(to, 0, entries.splice(from, 1)[0]);
        entries.forEach((key, i) => order.set(key, i + 1));
        relabel();
      };

      function renderPicked() {
        clear(picked);
        const entries = [...order.entries()].sort((a, b) => a[1] - b[1]);
        if (!entries.length) {
          picked.appendChild(h('li', { class: 'ctxpick__picked-empty', text: 'Nothing selected yet.' }));
          return;
        }
        entries.forEach(([name], index) => {
          picked.appendChild(
            h(
              'li',
              { class: 'ctxpick__picked-item' },
              h('span', { class: 'ctxpick__picked-name', text: `${index + 1}. ${name}` }),
              h(
                'button',
                {
                  class: 'ctxpick__move',
                  type: 'button',
                  title: 'Move up',
                  disabled: index === 0,
                  on: { click: () => move(name, -1) },
                },
                '↑',
              ),
              h(
                'button',
                {
                  class: 'ctxpick__move',
                  type: 'button',
                  title: 'Move down',
                  disabled: index === entries.length - 1,
                  on: { click: () => move(name, 1) },
                },
                '↓',
              ),
              h(
                'button',
                {
                  class: 'ctxpick__move ctxpick__move--remove',
                  type: 'button',
                  title: 'Remove',
                  on: {
                    click: () => {
                      const box = boxes.get(name);
                      if (box) box.checked = false;
                      toggle(name, false);
                    },
                  },
                },
                '×',
              ),
            ),
          );
        });
      }

      /* ---- "Available contexts" list ---- */
      const list = h('div', { class: 'ctxpick__list' });
      const names = [...new Set([...current, ...availableContexts()])];
      if (!names.length) {
        list.appendChild(
          h('p', { class: 'ctxpick__empty', text: 'No contexts yet — fill Group Name / Context Prefix and press “Load contexts” first.' }),
        );
      }
      names.forEach((name) => {
        const box = h('input', {
          type: 'checkbox',
          checked: order.has(name),
          on: { change: () => toggle(name, box.checked) },
        });
        const text = h('span', { text: order.has(name) ? `${order.get(name)}. ${name}` : name });
        boxes.set(name, box);
        labels.set(name, text);
        list.appendChild(h('label', { class: 'ctxpick__item' }, box, text));
      });
      renderPicked();

      const backdrop = h(
        'div',
        { class: 'u-modal-backdrop', role: 'dialog', 'aria-modal': 'true', on: { click: (e) => e.target === backdrop && finish(null) } },
        h(
          'div',
          { class: 'u-modal ctxpick' },
          h('h3', { class: 'u-modal__title', text: `Contexts for ${classLabel}` }),
          h(
            'p',
            { class: 'u-modal__text' },
            'Tick the contexts to include, then use ↑ / ↓ to set the final order — position 1 goes first in contextInclude_value.',
          ),
          h('div', { class: 'ctxpick__cols' },
            h('div', { class: 'ctxpick__col' },
              h('div', { class: 'ctxpick__colhead', text: 'Available contexts' }),
              list,
            ),
            h('div', { class: 'ctxpick__col' },
              h('div', { class: 'ctxpick__colhead', text: 'Selected (in order)' }),
              picked,
            ),
          ),
          h(
            'div',
            { class: 'u-modal__actions' },
            h('button', { class: 'u-btn u-btn--sm u-btn--ghost', type: 'button', on: { click: () => finish(null) } }, 'Cancel'),
            h(
              'button',
              {
                class: 'u-btn u-btn--sm u-btn--ghost',
                type: 'button',
                on: {
                  click: () => {
                    order.clear();
                    boxes.forEach((box) => {
                      box.checked = false;
                    });
                    relabel();
                  },
                },
              },
              'Clear',
            ),
            h(
              'button',
              {
                class: 'u-btn u-btn--sm u-btn--primary',
                type: 'button',
                /* Map iteration is insertion order, so sort by the renumbered value. */
                on: { click: () => finish([...order.entries()].sort((a, b) => a[1] - b[1]).map(([name]) => name)) },
              },
              'Apply',
            ),
          ),
        ),
      );
      document.body.appendChild(backdrop);
      document.addEventListener('keydown', onKey);
    });
  }

  /** Keep the combo box and the manual picker from both claiming to define the contexts. */
  function syncPgRow(index) {
    const row = cfg.pg[index];
    const manual = row.ctx.length > 0;
    const select = pgSelects[index];
    const button = pgCtxButtons[index];
    if (select) select.disabled = manual;
    if (button) {
      button.textContent = manual ? `${row.ctx.length} selected` : 'Select contexts…';
      button.classList.toggle('is-active', manual);
      button.title = manual
        ? `Hand-picked: ${row.ctx.join(', ')} — click to edit (overrides the combo box)`
        : "Pick this Class's contexts by hand (overrides the combo box)";
    }
  }

  const pgRows = PROFILE_CLASSES.map((label, index) => {
    const classNum = index + 1;
    const options = pgOptions(classNum, cfg.pgServerData);
    const select = h(
      'select',
      {
        class: 'input-plain',
        on: {
          change: () => {
            cfg.pg[index].key = select.value;
            cfg.pg[index].ctx = [];
            syncPgRow(index);
            save();
          },
        },
      },
      options.map((option) => h('option', { value: option.key, selected: option.key === cfg.pg[index].key }, option.label)),
    );
    pgSelects.push(select);
    const orderLabel = h('span', { class: 'tasklist__idx', text: cfg.pg[index].enabled ? '' : '·' });
    pgOrderLabels.push(orderLabel);

    const ctxButton = h(
      'button',
      {
        class: 'u-btn u-btn--sm',
        type: 'button',
        title: 'Pick this Class\'s contexts by hand (overrides the combo box)',
        on: {
          click: async () => {
            const picked = await pickContexts(label, cfg.pg[index].ctx);
            if (picked === null) return;
            cfg.pg[index].ctx = picked;
            syncPgRow(index);
            save();
          },
        },
      },
      'Select contexts…',
    );
    pgCtxButtons.push(ctxButton);

    const box = h('input', {
      type: 'checkbox',
      checked: cfg.pg[index].enabled,
      on: {
        change: () => {
          cfg.pg[index].enabled = box.checked;
          updatePgOrder();
          save();
        },
      },
    });

    return h(
      'div',
      { class: 'row pg-row', style: { marginBottom: '8px' } },
      orderLabel,
      h('label', { class: 'u-switch' }, box, h('span', { class: 'u-switch__track' }), label),
      h('div', { class: 'pg-row__combo' }, select),
      ctxButton,
    );
  });
  cfg.pg.forEach((_row, index) => syncPgRow(index));

  /* -------------------------------------------- "add in front" lead context */
  /**
   * One dropdown that puts a single context at position 1 of every enabled Class.
   * Options are the contexts that already exist on the server for this Group, plus any
   * name typed by hand, so a pre-existing context can be forced to the front of all
   * four Classes without editing them one by one.
   */
  const pgLeadSelect = h('select', { class: 'input-plain' });
  const pgLeadCustom = h('input', {
    class: 'input-plain',
    placeholder: '…or type a context name',
    spellcheck: 'false',
    value: '',
    on: {
      input: () => {
        const typed = pgLeadCustom.value.trim();
        if (typed) {
          /* A typed name wins over the dropdown and becomes its own option. */
          const existing = [...pgLeadSelect.options].find((option) => option.value === typed);
          if (!existing) pgLeadSelect.appendChild(h('option', { value: typed }, typed));
          pgLeadSelect.value = typed;
        }
        cfg.pgLead = pgLeadSelect.value;
        updatePgLeadHint();
        save();
      },
    },
  });

  /** Refresh the dropdown options from the loaded server data (keeps the current pick). */
  function rebuildPgLeadOptions() {
    const current = cfg.pgLead || '';
    clear(pgLeadSelect);
    pgLeadSelect.appendChild(h('option', { value: '', selected: !current }, '— none (Class combo only) —'));
    const names = availableContexts();
    names.forEach((name) => {
      pgLeadSelect.appendChild(h('option', { value: name, selected: name === current }, name));
    });
    if (current && !names.includes(current)) {
      pgLeadSelect.appendChild(h('option', { value: current, selected: true }, current));
    }
    pgLeadSelect.value = current;
    updatePgLeadHint();
  }

  const pgLeadHint = h('span', { class: 'u-label__hint', text: '' });
  function updatePgLeadHint() {
    const lead = (pgLeadSelect.value || '').trim();
    pgLeadHint.textContent = lead
      ? `“${lead}” will be placed FIRST in every enabled Class`
      : 'Optional — pick a context to force it to position 1 of every Class';
  }

  pgLeadSelect.addEventListener('change', () => {
    cfg.pgLead = pgLeadSelect.value;
    updatePgLeadHint();
    save();
  });
  rebuildPgLeadOptions();

  const pgLeadRefreshBtn = h(
    'button',
    {
      class: 'u-btn u-btn--sm',
      type: 'button',
      title: 'Fetch all contexts from the server',
      on: {
        click: async () => {
          pgLeadRefreshBtn.disabled = true;
          try {
            const data = await api.allContexts();
            profileAllContexts = [...new Set((data.contexts || data.items?.map((item) => item.contextID) || []).filter(Boolean))];
            rebuildPgLeadOptions();
            rebuildProfileCtxOptions();
            const found = profileAllContexts.length;
            log('info', `Loaded ${found} server context(s)`);
            toast(found ? 'ok' : 'warn', found ? `Loaded ${found} server contexts` : 'No contexts found on server');
          } catch (error) {
            toast('err', `Failed to load contexts: ${error.message}`);
            log('err', `Failed to load contexts: ${error.message}`);
          } finally {
            pgLeadRefreshBtn.disabled = false;
          }
        },
      },
    },
    icon('refresh', 15),
    'Refresh',
  );

  const pgLeadRow = h(
    'div',
    { class: 'u-field pg-lead' },
    h(
      'label',
      { class: 'u-label' },
      'Add context in front of every Class (Position 1)',
      h('span', { class: 'u-label__hint', text: 'Select a context to place at the 1st position of Class 1-4' }),
    ),
    h(
      'div',
      { class: 'pg-lead__row' },
      h('div', { class: 'pg-lead__select' }, pgLeadSelect),
      h('div', { class: 'pg-lead__custom' }, pgLeadCustom),
      pgLeadRefreshBtn,
    ),
    pgLeadHint,
  );

  function updatePgOrder() {
    let order = 0;
    cfg.pg.forEach((row, index) => {
      if (row.enabled) {
        order += 1;
        pgOrderLabels[index].textContent = String(order);
      } else {
        pgOrderLabels[index].textContent = '·';
      }
    });
  }
  updatePgOrder();

  const pgRefreshBtn = h(
    'button',
    {
      class: 'u-btn u-btn--sm',
      type: 'button',
      on: {
        click: async () => {
          const groupName = paramValue('group_name');
          const ctxPrefix = paramValue('context_prefix') || groupName;
          if (!groupName) {
            toast('warn', 'Fill in Group Name before loading contexts.');
            return;
          }
          pgRefreshBtn.disabled = true;
          try {
            const data = await api.contexts(groupName, ctxPrefix || groupName);
            cfg.pgServerData = data;
            pgSelects.forEach((select, index) => {
              const options = pgOptions(index + 1, data);
              const current = cfg.pg[index].key;
              clear(select);
              options.forEach((option) => select.appendChild(h('option', { value: option.key, selected: option.key === current }, option.label)));
              if (options.length && !options.some((option) => option.key === current)) {
                cfg.pg[index].key = options[0].key;
                select.value = options[0].key;
              }
              select.disabled = options.length === 0;
              syncPgRow(index);
            });
            rebuildPgLeadOptions();
            save();
            const found = (data.all || []).length;
            log('info', `Loaded contexts: ${found} (Customer ID=${data.customerId || '-'})`);
            toast(found ? 'ok' : 'warn', found ? `Loaded ${found} contexts` : 'No contexts found under this group');
          } catch (error) {
            toast('err', `Failed to load contexts: ${error.message}`);
            log('err', `Failed to load contexts: ${error.message}`);
          } finally {
            pgRefreshBtn.disabled = false;
          }
        },
      },
    },
    icon('refresh', 15),
    'Load contexts',
  );

  const pgCard = card(
    'Permission Group (four classes)',
    'Checked Classes are numbered in order; use the combo for a standard combo, or “Select contexts…” to pick this Class\'s contexts by hand',
    h('div', {}, pgLeadRow, h('div', { class: 'mt-16' }, ...pgRows)),
    pgRefreshBtn,
  );

  /* ------------------------------------------------ Custom Outbound Routing */
  /**
   * Desktop "Custom Routing" (Complex tab, Outbound Routing frame): instead of the 10
   * default rules, create a single rule for a hand-picked number and context. The two
   * inputs sit side by side, exactly like the desktop frame and the User Profile rows.
   */
  const customNumberInput = h('input', {
    class: 'input-plain',
    placeholder: 'e.g. _230X or 60312345678',
    spellcheck: 'false',
    value: cfg.customNumber,
    on: {
      input: () => {
        cfg.customNumber = customNumberInput.value.trim();
        save();
      },
    },
  });

  const customCtxSelect = h('select', { class: 'input-plain' });

  /** Rebuild the context choices (suffix literals until Refresh loads the Group's own list). */
  function renderCustomCtxOptions(list) {
    const values = Array.isArray(list) && list.length ? list : CUSTOM_CTX_SUFFIXES;
    const current = cfg.customContext || values[0];
    clear(customCtxSelect);
    values.forEach((value) => {
      customCtxSelect.appendChild(h('option', { value, selected: value === current }, value));
    });
    /* Keep a previously chosen context that the server list does not contain. */
    if (current && !values.includes(current)) {
      customCtxSelect.appendChild(h('option', { value: current, selected: true }, current));
    }
    customCtxSelect.value = current;
  }
  renderCustomCtxOptions();
  customCtxSelect.addEventListener('change', () => {
    cfg.customContext = customCtxSelect.value;
    save();
  });

  const customCtxRefresh = h(
    'button',
    {
      class: 'u-btn u-btn--sm',
      type: 'button',
      title: 'Load the contexts that exist for this Group',
      on: {
        click: async () => {
          const group = paramValue('group_name');
          if (!group) {
            toast('warn', 'Fill in Group Name before loading contexts.');
            return;
          }
          customCtxRefresh.disabled = true;
          try {
            const data = await api.contexts(group, paramValue('context_prefix'));
            const list = [...new Set([...(data.groupAll || []), ...(data.contexts || [])].filter(Boolean))];
            if (list.length) {
              /* Same as the desktop refresh: select the first real context of the Group. */
              cfg.customContext = list[0];
              renderCustomCtxOptions(list);
              save();
            }
            log('info', `Loaded ${list.length} context(s) for custom outbound routing (Group=${group})`);
            toast(list.length ? 'ok' : 'warn', list.length ? `Loaded ${list.length} contexts` : 'No contexts found under this group');
          } catch (error) {
            toast('err', `Failed to load contexts: ${error.message}`);
            log('err', `Failed to load contexts: ${error.message}`);
          } finally {
            customCtxRefresh.disabled = false;
          }
        },
      },
    },
    icon('refresh', 15),
    'Refresh',
  );

  const customOutboundCard = card(
    'Custom Outbound Routing',
    'Creates a single rule for the number and context you choose; select it next to Outbound Routing in the task list',
    h(
      'div',
      { class: 'form-grid mt-16' },
      h(
        'div',
        { class: 'u-field' },
        h('label', { class: 'u-label' }, 'Custom Number', h('span', { class: 'u-label__hint', text: 'The dial pattern, e.g. _230X' })),
        customNumberInput,
      ),
      h(
        'div',
        { class: 'u-field' },
        h('label', { class: 'u-label' }, 'Context', h('span', { class: 'u-label__hint', text: 'Refresh loads the contexts of this Group' })),
        h('div', { class: 'row' }, h('div', { style: { flex: '1 1 160px', minWidth: '140px' } }, customCtxSelect), customCtxRefresh),
      ),
    ),
  );

  /* --------------------------------------------------------- ACL Group */
  const aclCard = card(
    'ACL Group',
    'Which permission groups to create',
    h(
      'div',
      { class: 'row' },
      ...ACL_GROUPS.map((suffix) =>
        switchRow(suffix, cfg.aclGroups.has(suffix), (checked) => {
          if (checked) cfg.aclGroups.add(suffix);
          else cfg.aclGroups.delete(suffix);
          save();
        }).node,
      ),
    ),
  );

  /* ------------------------------------------------------- User Profile */
  /**
   * Number context (Task 9's ``number_context``).
   *
   * The refresh button reads **every context on the PBX, across all Groups** — this mirrors
   * the desktop ``_refresh_ctx_dropdowns`` (``search_contexts_by_prefix("")``), because the
   * operator may point a profile at a context that does not belong to the Group being
   * provisioned. A free-text entry is also accepted for a context that does not exist yet.
   * Blank keeps the task's own default (``<prefix>_Internal``).
   */
  const profileCtxSelect = h(
    'select',
    { class: 'input-plain' },
    [h('option', { value: '', selected: !cfg.profileNumberContext }, '(default: <prefix>_Internal)')],
  );
  const profileCtxCustom = h('input', {
    class: 'input-plain',
    placeholder: '…or type a context name',
    spellcheck: 'false',
    value: '',
    on: {
      input: () => {
        const typed = profileCtxCustom.value.trim();
        if (typed) {
          if (![...profileCtxSelect.options].some((option) => option.value === typed)) {
            profileCtxSelect.appendChild(h('option', { value: typed }, typed));
          }
          profileCtxSelect.value = typed;
        }
        cfg.profileNumberContext = profileCtxSelect.value;
        save();
      },
    },
  });

  /** Rebuild the number-context options from the server-wide list (keeps the pick). */
  rebuildProfileCtxOptions = () => {
    const current = cfg.profileNumberContext || '';
    clear(profileCtxSelect);
    profileCtxSelect.appendChild(h('option', { value: '', selected: !current }, '(default: <prefix>_Internal)'));
    profileAllContexts.forEach((name) => {
      profileCtxSelect.appendChild(h('option', { value: name, selected: name === current }, name));
    });
    if (current && !profileAllContexts.includes(current)) {
      profileCtxSelect.appendChild(h('option', { value: current, selected: true }, current));
    }
    profileCtxSelect.value = current;
  };

  const profileRefresh = h(
    'button',
    {
      class: 'u-btn u-btn--sm',
      type: 'button',
      title: 'Reload every context that exists on the server (all Groups)',
      on: {
        click: async () => {
          profileRefresh.disabled = true;
          try {
            const data = await api.allContexts();
            profileAllContexts = [...new Set((data.contexts || data.items?.map((item) => item.contextID) || []).filter(Boolean))];
            rebuildProfileCtxOptions();
            rebuildPgLeadOptions();
            const found = profileAllContexts.length;
            log('info', `Loaded ${found} server context(s) for the Number context dropdown`);
            toast(found ? 'ok' : 'warn', found ? `Loaded ${found} server contexts` : 'No contexts found on the server');
          } catch (error) {
            toast('err', `Load failed: ${error.message}`);
            log('err', `Load server contexts failed: ${error.message}`);
          } finally {
            profileRefresh.disabled = false;
          }
        },
      },
    },
    icon('refresh', 15),
    'Refresh',
  );
  profileCtxSelect.addEventListener('change', () => {
    cfg.profileNumberContext = profileCtxSelect.value;
    save();
  });

  const profileCard = card(
    'User Profile (four classes)',
    'Which template classes to create, plus number context and the recording toggle',
    h(
      'div',
      {},
      h(
        'div',
        { class: 'row' },
        ...PROFILE_CLASSES.map((label) =>
          switchRow(label, cfg.profileClasses.has(label), (checked) => {
            if (checked) cfg.profileClasses.add(label);
            else cfg.profileClasses.delete(label);
            save();
          }).node,
        ),
      ),
      h(
        'div',
        { class: 'row mt-16' },
        switchRow('Enable recording', cfg.profileRecording, (checked) => {
          cfg.profileRecording = checked;
          save();
        }).node,
      ),
      h(
        'div',
        { class: 'u-field mt-16' },
        h(
          'label',
          { class: 'u-label' },
          'Number context',
          h('span', { class: 'u-label__hint', text: 'Task 9 — Refresh loads every context on the server; blank uses <prefix>_Internal' }),
        ),
        h(
          'div',
          { class: 'row' },
          h('div', { style: { flex: '1 1 200px', minWidth: '150px' } }, profileCtxSelect),
          h('div', { style: { flex: '1 1 160px', minWidth: '140px' } }, profileCtxCustom),
          profileRefresh,
        ),
      ),
    ),
  );

  /* ---------------------------------------------------------- ACL User */
  const aclInputs = {};
  const aclRoleRows = Object.entries({ managers: 'Managers', supervisors: 'Supervisors', users: 'Users' }).map(
    ([key, label]) => {
      const entry = h('input', {
        class: 'input-plain',
        placeholder: 'e.g. 0358797500,0358797501 (blank uses the extension range)',
        value: cfg.aclRoles[key].value,
        on: {
          input: () => {
            cfg.aclRoles[key].value = entry.value;
            save();
          },
          change: () => dedupRoles(key),
        },
      });
      aclInputs[key] = entry;
      const box = h('input', {
        type: 'checkbox',
        checked: cfg.aclRoles[key].checked,
        on: {
          change: () => {
            cfg.aclRoles[key].checked = box.checked;
            entry.disabled = !box.checked;
            save();
          },
        },
      });
      entry.disabled = !cfg.aclRoles[key].checked;
      return h(
        'div',
        { class: 'row', style: { marginBottom: '8px' } },
        h('label', { class: 'u-switch', style: { minWidth: '132px' } }, box, h('span', { class: 'u-switch__track' }), label),
        h('div', { style: { flex: '1 1 320px' } }, entry),
      );
    },
  );

  /** Same as desktop _sync_acl_user_entries: first extension → Managers, the rest → Users (blank fields only). */
  let lastExt = '';
  function syncFromExtRange(extString) {
    lastExt = extString || lastExt;
    const exts = parseExtRange(lastExt, false).items;
    if (!exts.length) return;
    if (cfg.aclRoles.managers.checked && !cfg.aclRoles.managers.value.trim()) {
      cfg.aclRoles.managers.value = exts[0];
      aclInputs.managers.value = exts[0];
    }
    if (cfg.aclRoles.users.checked && !cfg.aclRoles.users.value.trim()) {
      const used = new Set(parseExtRange(cfg.aclRoles.managers.value, false).items);
      const rest = exts.filter((ext) => !used.has(ext));
      if (rest.length) {
        cfg.aclRoles.users.value = rest.join(',');
        aclInputs.users.value = rest.join(',');
      }
    }
    save();
  }

  /** Same as desktop _dedup_acl_user_entries: a number is kept in only one role. */
  function dedupRoles(activeKey) {
    const active = new Set(parseExtRange(cfg.aclRoles[activeKey].value, false).items);
    if (!active.size) return;
    Object.keys(cfg.aclRoles).forEach((key) => {
      if (key === activeKey) return;
      const kept = parseExtRange(cfg.aclRoles[key].value, false).items.filter((ext) => !active.has(ext));
      const next = kept.join(',');
      if (next !== cfg.aclRoles[key].value) {
        cfg.aclRoles[key].value = next;
        aclInputs[key].value = next;
      }
    });
    save();
  }

  const aclUserCard = card(
    'ACL User roles',
    'The first extension goes to Managers automatically, the rest to Users; check to enable, and you can still edit manually',
    h(
      'div',
      {},
      h('div', {}, ...aclRoleRows),
      h(
        'div',
        { class: 'row mt-16' },
        h(
          'button',
          { class: 'u-btn u-btn--sm', type: 'button', on: { click: () => syncFromExtRange(lastExt) } },
          icon('refresh', 15),
          'Autofill from extension range',
        ),
      ),
    ),
  );

  /* ------------------------------------------------------------ visibility */
  const visibility = [
    { names: ['Context'], node: ctxCard },
    { names: ['Permission Group'], node: pgCard },
    { names: ['Custom Outbound Routing'], node: customOutboundCard },
    { names: ['ACL Group'], node: aclCard },
    { names: ['User Profile'], node: profileCard },
    { names: ['ACL User'], node: aclUserCard },
  ];

  function updateVisibility() {
    visibility.forEach(({ names, node }) => {
      const visible = names.some((name) => selected.has(name));
      node.style.display = visible ? '' : 'none';
    });
  }
  updateVisibility();

  /* ---------------------------------------------------------------- collect */
  function collect() {
    const suffixes = [...cfg.ctxSuffixes];
    if (cfg.ctxCustom.trim()) suffixes.push(cfg.ctxCustom.trim());
    const lead = (cfg.pgLead || '').trim();
    const classes = [];
    let order = 0;
    cfg.pg.forEach((row, index) => {
      if (row.enabled) order += 1;
      classes.push({
        class: row.enabled ? order : 0,
        source_class: index + 1,
        enabled: row.enabled,
        key: row.key,
        /* Hand-picked context list (exact names, in order). Empty → backend derives from ``key``.
           The lead context is sent separately so it is prepended to *whatever* the Class
           resolves to, without discarding its combo's own contexts. */
        ctx: [...row.ctx],
        lead,
      });
    });
    return {
      context_suffixes: suffixes,
      pg_spec: { classes },
      pg_lead: lead,
      pg_server_data: cfg.pgServerData,
      acl_group_selection: [...cfg.aclGroups].map((suffix) => suffix.replace(/^_/, '')),
      profile_classes_selection: [...cfg.profileClasses],
      profile_recording: cfg.profileRecording,
      profile_number_context: cfg.profileNumberContext,
      acl_managers: cfg.aclRoles.managers.checked ? cfg.aclRoles.managers.value : '',
      acl_supervisors: cfg.aclRoles.supervisors.checked ? cfg.aclRoles.supervisors.value : '',
      acl_users: cfg.aclRoles.users.checked ? cfg.aclRoles.users.value : '',
      usernames: usernamesArea ? usernamesArea.value.split('\n').map((line) => line.trim()).filter(Boolean) : [],
      emails: emailsArea ? emailsArea.value.split('\n').map((line) => line.trim()).filter(Boolean) : [],
      /* Outbound Routing: selecting "Custom Outbound Routing" creates this single rule. */
      custom_routing_mode: selected.has('Custom Outbound Routing'),
      custom_number: cfg.customNumber.trim(),
      custom_context: cfg.customContext.trim(),
      custom_payloads: {},
    };
  }

  function validate() {
    if (selected.has('Context') && !cfg.ctxSuffixes.size && !cfg.ctxCustom.trim()) {
      return 'Context is selected: check at least one suffix or enter a custom suffix.';
    }
    if (selected.has('Permission Group')) {
      const enabled = cfg.pg.filter((row) => row.enabled);
      if (!enabled.length) return 'Permission Group is selected: check at least one Class.';
      if (enabled.some((row) => !row.ctx.length && !row.key)) {
        return 'Permission Group: every enabled Class needs a context combo, or pick its contexts by hand.';
      }
    }
    if (selected.has('ACL Group') && !cfg.aclGroups.size) {
      return 'ACL Group is selected: check at least one group.';
    }
    if (selected.has('Custom Outbound Routing')) {
      if (!cfg.customNumber.trim()) {
        return 'Custom Outbound Routing: enter a Custom Number.';
      }
      if (!cfg.customContext.trim() || cfg.customContext.trim() === 'Custom') {
        return 'Custom Outbound Routing: choose a context (press Refresh to load this Group\'s contexts).';
      }
    }
    if (selected.has('User Profile') && !cfg.profileClasses.size) {
      return 'User Profile is selected: check at least one Class.';
    }
    return null;
  }

  return {
    cards: [ctxCard, pgCard, customOutboundCard, aclCard, profileCard, aclUserCard],
    collect,
    validate,
    updateVisibility,
    refreshPayloadEditor: () => {},
    syncFromExtRange,
    /** Runs sub-option validation after the Complex mode main validation passes */
    reset: () => {},
  };
}
