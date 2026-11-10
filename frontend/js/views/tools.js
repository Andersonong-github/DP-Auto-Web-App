/**
 * views/tools.js — Toolbox.
 *
 * Name splitting and number range expansion are pure text processing and do not depend on the PBX, so they
 * are already usable in stage 1 and also verify the “no access when logged out” gate. Tools needing PBX APIs wait for stage 4.
 */

import { badge, clear, copyText, h, icon, log, toast } from '../ui.js';

/* ------------------------------------------------------------ Name split rules */
/* Keep in sync with the desktop utils/name_split.py: title case → drop Malay connectors → split in half */
const CONNECTORS = [
  ' Bin ',
  ' Binti ',
  ' & ',
  '&',
  ' Bini ',
  ' Bt ',
  ' bin ',
  ' binti ',
  ' bini ',
  ' bt ',
  ' A/L ',
  ' A/P ',
  ' a/l ',
  ' a/p ',
];

function titleCase(value) {
  return value.replace(/[\w'’]+/g, (word) => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase());
}

export function splitName(raw) {
  let name = String(raw || '').trim();
  if (!name) return ['', ''];
  name = titleCase(name);
  CONNECTORS.forEach((token) => {
    name = name.split(token).join(' ');
  });
  const words = name.split(/\s+/).filter(Boolean);
  if (!words.length) return ['', ''];
  if (words.length === 1) return [words[0].slice(0, 20), ''];
  const pivot = Math.floor(words.length / 2);
  return [words.slice(0, pivot).join(' ').slice(0, 20), words.slice(pivot).join(' ').slice(0, 20)];
}

/* --------------------------------------------------------- Number range rules */
/* Keep in sync with the desktop utils/ext_parser.py: comma groups, range expansion, optional strip of prefix 6 */
const MAX_RANGE = 5000;

export function parseExtRange(input, stripSix = true) {
  const result = [];
  let truncated = false;
  String(input || '')
    .split(',')
    .map((group) => group.trim())
    .filter(Boolean)
    .forEach((group) => {
      if (group.includes('-')) {
        const [rawStart, rawEnd] = group.split('-', 2).map((part) => part.trim());
        let start = stripSix && rawStart.startsWith('6') ? rawStart.slice(1) : rawStart;
        let end = stripSix && rawEnd.startsWith('6') ? rawEnd.slice(1) : rawEnd;
        if (!/^\d+$/.test(start) || !/^\d+$/.test(end)) return;
        const width = start.length;
        let startNum = Number(start);
        let endNum = Number(end);
        if (endNum < startNum) return;
        if (endNum - startNum + 1 > MAX_RANGE) {
          endNum = startNum + MAX_RANGE - 1;
          truncated = true;
        }
        for (let num = startNum; num <= endNum; num += 1) result.push(String(num).padStart(width, '0'));
      } else {
        result.push(stripSix && group.startsWith('6') ? group.slice(1) : group);
      }
    });
  return { items: result, truncated };
}

/* ------------------------------------------------------------------ Components */
function toolCard({ title, sub, statusText, statusVariant = '', body }) {
  return h(
    'section',
    { class: 'u-card' },
    h(
      'div',
      { class: 'u-card__head' },
      h('div', {}, h('h3', { class: 'u-card__title', text: title }), h('p', { class: 'u-card__sub', text: sub })),
      badge(statusText, statusVariant),
    ),
    h('div', { class: 'u-card__body' }, body),
  );
}

function textarea(props) {
  return h('textarea', {
    class: 'u-input',
    style: {
      width: '100%',
      minHeight: '132px',
      padding: '12px',
      border: '1.5px solid var(--line)',
      borderRadius: '10px',
      background: 'rgba(9, 15, 27, 0.75)',
      fontFamily: 'var(--mono)',
      fontSize: '12.5px',
      resize: 'vertical',
    },
    spellcheck: 'false',
    ...props,
  });
}

function nameSplitTool() {
  const input = textarea({ placeholder: 'One full name per line, for example:\nAhmad Bin Ali\nTan Wei Ming' });
  const output = textarea({ readOnly: true, placeholder: 'Split result (First Name ⇥ Last Name)' });
  const copyButton = h('button', { class: 'u-btn u-btn--sm', type: 'button', disabled: true }, icon('copy', 15), 'Copy result');

  const run = () => {
    const rows = input.value
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean)
      .map((line) => splitName(line));
    output.value = rows.map(([first, last]) => `${first}\t${last}`).join('\n');
    copyButton.disabled = rows.length === 0;
    log('info', `Name split: ${rows.length} rows`);
  };

  input.addEventListener('input', run);
  copyButton.addEventListener('click', async () => {
    const ok = await copyText(output.value);
    toast(ok ? 'ok' : 'err', ok ? 'Copied to clipboard (ready to paste into Excel)' : 'Copy failed, please select the text manually');
  });

  return toolCard({
    title: 'Name Split Tool',
    sub: 'Title case → remove connectors such as Bin / Binti / Bt → split in half into First / Last, each truncated to 20 characters',
    statusText: 'Ready',
    statusVariant: 'ok',
    body: h(
      'div',
      {},
      h('div', { class: 'u-field' }, h('label', { class: 'u-label', text: 'Input' }), input),
      h('div', { class: 'u-field mt-16' }, h('label', { class: 'u-label', text: 'Output' }), output),
      h('div', { class: 'row mt-16' }, copyButton),
    ),
  });
}

function extRangeTool() {
  const input = h('input', {
    class: 'u-input',
    style: {
      width: '100%',
      height: '44px',
      padding: '0 12px',
      border: '1.5px solid var(--line)',
      borderRadius: '10px',
      background: 'rgba(9, 15, 27, 0.75)',
      fontFamily: 'var(--mono)',
      fontSize: '13px',
    },
    value: '60358797500 - 60358797509',
    spellcheck: 'false',
  });
  const stripToggle = h('input', { type: 'checkbox', checked: true });
  const summary = h('div', { class: 'u-alert u-alert--info mt-16' });
  const preview = textarea({ readOnly: true });
  const copyButton = h('button', { class: 'u-btn u-btn--sm', type: 'button', disabled: true }, icon('copy', 15), 'Copy all');

  let items = [];

  const run = () => {
    const parsed = parseExtRange(input.value, stripToggle.checked);
    items = parsed.items;
    clear(summary);
    summary.append(
      icon(parsed.truncated ? 'alert' : 'check', 18),
      h('div', {
        text: parsed.truncated
          ? `Expanded ${items.length} numbers (limit of ${MAX_RANGE} exceeded, truncated)`
          : `Expanded ${items.length} numbers`,
      }),
    );
    preview.value = items.slice(0, 200).join('\n') + (items.length > 200 ? `\n… ${items.length - 200} more omitted` : '');
    copyButton.disabled = items.length === 0;
    log('info', `Number range expansion: ${items.length} items`);
  };

  input.addEventListener('input', run);
  stripToggle.addEventListener('change', run);
  copyButton.addEventListener('click', async () => {
    const ok = await copyText(items.join('\n'));
    toast(ok ? 'ok' : 'err', ok ? `Copied ${items.length} numbers` : 'Copy failed, please select the text manually');
  });

  const field = h(
    'div',
    { class: 'u-field' },
    h('label', { class: 'u-label', text: 'Number ranges (comma-separated ranges supported)' }),
    input,
  );

  run();

  return toolCard({
    title: 'Number Range Preview',
    sub: 'Same rules as the desktop ext_parser: zero-pad to the start width, at most 5000 per run',
    statusText: 'Ready',
    statusVariant: 'ok',
    body: h(
      'div',
      {},
      field,
      h('div', { class: 'mt-16' }, h('label', { class: 'u-switch' }, stripToggle, h('span', { class: 'u-switch__track' }), 'Strip prefix 6')),
      summary,
      h('div', { class: 'u-field mt-16' }, h('label', { class: 'u-label', text: 'First 200 numbers' }), preview),
      h('div', { class: 'row mt-16' }, copyButton),
    ),
  });
}

function plannedTool(title, sub, detail) {
  return toolCard({
    title,
    sub,
    statusText: 'Stage 4',
    body: h('p', { class: 'muted', text: detail }),
  });
}

export const toolsView = {
  title: 'Name Split Tool',
  subtitle: 'Split full names into First / Last, exactly like the desktop Name Split Tools tab',
  mount(root) {
    clear(root).append(
      h(
        'div',
        { class: 'page-head' },
        h('div', {}, h('h2', { text: 'Name Split Tool' }), h('p', { text: 'Split full names (and preview number ranges) without touching the PBX.' })),
      ),
      h(
        'div',
        { class: 'grid grid--two' },
        nameSplitTool(),
        extRangeTool(),
      ),
    );
  },
};
