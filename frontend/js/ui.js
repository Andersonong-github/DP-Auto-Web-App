/**
 * ui.js — DOM helpers, icons, toasts and log console output.
 */

import { pushLog, state } from './store.js';

const SVG_NS = 'http://www.w3.org/2000/svg';

/* ------------------------------------------------------------------ Icons */
const ICONS = {
  brand: '<path d="M5.5 10a6.5 6.5 0 0113 0"/><path d="M8.6 13.4a3.4 3.4 0 016.8 0"/><circle cx="12" cy="17.6" r="1.5"/>',
  server:
    '<rect x="3" y="4" width="18" height="7" rx="2"/><rect x="3" y="13" width="18" height="7" rx="2"/><path d="M7 7.5h.01M7 16.5h.01"/>',
  shield: '<path d="M12 3.2l7 2.9v5.6c0 4.2-2.9 7.7-7 9.1-4.1-1.4-7-4.9-7-9.1V6.1l7-2.9z"/>',
  lock: '<rect x="4.5" y="10" width="15" height="10" rx="2.2"/><path d="M8.2 10V7.4a3.8 3.8 0 017.6 0V10"/>',
  user: '<circle cx="12" cy="8.2" r="3.7"/><path d="M4.6 20a7.4 7.4 0 0114.8 0"/>',
  globe:
    '<circle cx="12" cy="12" r="8.6"/><path d="M3.4 12h17.2"/><path d="M12 3.4c2.5 2.7 2.5 14.5 0 17.2-2.5-2.7-2.5-14.5 0-17.2z"/>',
  eye: '<path d="M2.6 12S6.1 5.6 12 5.6 21.4 12 21.4 12 17.9 18.4 12 18.4 2.6 12 2.6 12z"/><circle cx="12" cy="12" r="3"/>',
  eyeOff:
    '<path d="M4 4l16 16"/><path d="M9.6 5.9A9.7 9.7 0 0112 5.6c5.9 0 9.4 6.4 9.4 6.4a17.6 17.6 0 01-3.2 4.1"/><path d="M6.5 8.1A17.6 17.6 0 002.6 12S6.1 18.4 12 18.4c1 0 1.9-.2 2.7-.5"/><path d="M9.9 9.9a3 3 0 004.2 4.2"/>',
  gauge: '<path d="M4.4 19.2a8.2 8.2 0 1115.2 0"/><path d="M12 15.2l3.6-4.3"/>',
  layers:
    '<path d="M12 3.4l8.6 4.3L12 12 3.4 7.7 12 3.4z"/><path d="M4 12.5l8 4 8-4M4 16.6l8 4 8-4"/>',
  wand: '<path d="M5 19.2L15.6 8.6"/><path d="M14.6 4.4l1 2.1 2.1 1-2.1 1-1 2.1-1-2.1-2.1-1 2.1-1 1-2.1z"/><path d="M19 14.2l.7 1.4 1.4.7-1.4.7-.7 1.4-.7-1.4-1.4-.7 1.4-.7.7-1.4z"/>',
  cube: '<path d="M12 3.5l7.5 4.2v8.6L12 20.5 4.5 16.3V7.7L12 3.5z"/><path d="M4.5 7.7L12 12l7.5-4.3M12 12v8.5"/>',
  sliders:
    '<path d="M5 8h8.5M18.5 8H19M5 16h3.5M13 16h6"/><circle cx="15.8" cy="8" r="2.2"/><circle cx="10.5" cy="16" r="2.2"/>',
  gear: '<circle cx="12" cy="12" r="3.2"/><path d="M12 3.4v2.3M12 18.3v2.3M4.7 7.8l2 1.1M17.3 15.1l2 1.1M4.7 16.2l2-1.1M17.3 8.9l2-1.1"/>',
  logout: '<path d="M14.8 5.6H18a2 2 0 012 2v8.8a2 2 0 01-2 2h-3.2"/><path d="M10 8.6L6.6 12 10 15.4M6.6 12h9"/>',
  refresh: '<path d="M20.2 12a8.2 8.2 0 11-2.5-6"/><path d="M20.2 4.4V10h-5.6"/>',
  check: '<path d="M5 12.6l4.6 4.6L19 7.4"/>',
  alert: '<path d="M12 4.4l8.6 15.2H3.4L12 4.4z"/><path d="M12 10v4.2M12 17.2h.01"/>',
  menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
  copy: '<rect x="9" y="9" width="11" height="11" rx="2.2"/><path d="M15 5.6H6.2A2.2 2.2 0 004 7.8v8.8"/>',
  trash:
    '<path d="M4.6 7.2h14.8"/><path d="M9.4 7.2V5.4a1.2 1.2 0 011.2-1.2h2.8a1.2 1.2 0 011.2 1.2v1.8"/><path d="M6.6 7.2l.9 12a1.5 1.5 0 001.5 1.4h6a1.5 1.5 0 001.5-1.4l.9-12"/>',
  play: '<path d="M7.6 5.2v13.6L19 12 7.6 5.2z"/>',
  power: '<path d="M12 4v7.4"/><path d="M7.4 6.8a6.8 6.8 0 108.9-.1"/>',
  clock: '<circle cx="12" cy="12" r="8.4"/><path d="M12 7.6V12l3 1.9"/>',
  search: '<circle cx="11" cy="11" r="6.6"/><path d="M20 20l-4.6-4.6"/>',
  zoomIn: '<circle cx="11" cy="11" r="6.6"/><path d="M20 20l-4.6-4.6M11 8.4v5.2M8.4 11h5.2"/>',
  zoomOut: '<circle cx="11" cy="11" r="6.6"/><path d="M20 20l-4.6-4.6M8.4 11h5.2"/>',
  chevron: '<path d="M8 10l4 4 4-4"/>',
  chevronDown: '<path d="M6 9l6 6 6-6"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/>',
  moon: '<path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z"/>',
  monitor: '<rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/>',
  sidebarCollapse: '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 3v18M14 9l-3 3 3 3"/>',
  sidebarExpand: '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 3v18M13 15l3-3-3-3"/>',
  voice: '<path d="M4 9.5v5M8 6.5v11M12 4v16M16 7.5v9M20 10.5v3"/>',
  phone:
    '<path d="M7.2 3.6h2.9l1.4 3.8-2 1.3a12.4 12.4 0 005.8 5.8l1.3-2 3.8 1.4v2.9a2 2 0 01-2.1 2A16.6 16.6 0 014.6 5.7a2 2 0 012-2.1z"/>',
  volume: '<path d="M4 9.5h3l4-3.5v12l-4-3.5H4z"/><path d="M16 8.6a5 5 0 010 6.8M18.7 6a8.5 8.5 0 010 12"/>',
};

export function icon(name, size = 20) {
  const svg = document.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('fill', 'none');
  svg.setAttribute('stroke', 'currentColor');
  svg.setAttribute('stroke-width', '1.7');
  svg.setAttribute('stroke-linecap', 'round');
  svg.setAttribute('stroke-linejoin', 'round');
  svg.setAttribute('width', String(size));
  svg.setAttribute('height', String(size));
  svg.setAttribute('aria-hidden', 'true');
  svg.innerHTML = ICONS[name] || ICONS.cube;
  return svg;
}

/* ------------------------------------------------------------------ DOM */
export function h(tag, props, ...children) {
  const el = document.createElement(tag);
  if (props) {
    for (const [key, value] of Object.entries(props)) {
      if (value === null || value === undefined || value === false) continue;
      if (key === 'class') el.className = value;
      else if (key === 'text') el.textContent = String(value);
      else if (key === 'html') el.innerHTML = value;
      else if (key === 'on') {
        for (const [event, handler] of Object.entries(value)) el.addEventListener(event, handler);
      } else if (key === 'dataset') Object.assign(el.dataset, value);
      else if (key === 'style' && typeof value === 'object') Object.assign(el.style, value);
      else el.setAttribute(key, value === true ? '' : String(value));
    }
  }
  append(el, children);
  return el;
}

function append(parent, children) {
  for (const child of children.flat(4)) {
    if (child === null || child === undefined || child === false) continue;
    parent.appendChild(child instanceof Node ? child : document.createTextNode(String(child)));
  }
}

export function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
  return node;
}

export function fmtDuration(seconds) {
  const total = Math.max(0, Math.floor(Number(seconds) || 0));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h) return `${h} h ${m} m`;
  if (m) return `${m} m ${s} s`;
  return `${s} s`;
}

export function fmtClock(ts) {
  const date = ts ? new Date(ts) : new Date();
  const pad = (n, w = 2) => String(n).padStart(w, '0');
  return `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

/** Fixed YYYY-MM-DD HH:mm:ss, independent of browser locale settings. */
export function fmtDateTime(ts) {
  const date = ts ? new Date(ts) : new Date();
  const pad = (n, w = 2) => String(n).padStart(w, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

/* ----------------------------------------------------------------- Toast */
export function toast(kind, message, ttl = 4600) {
  const host = document.getElementById('toasts');
  if (!host) return;
  const node = h(
    'div',
    { class: `u-toast u-toast--${kind}` },
    icon(kind === 'ok' ? 'check' : kind === 'err' ? 'alert' : kind === 'warn' ? 'alert' : 'server', 18),
    h('div', { text: message }),
  );
  host.appendChild(node);
  setTimeout(() => {
    node.classList.add('is-leaving');
    setTimeout(() => node.remove(), 220);
  }, ttl);
}

/* ------------------------------------------------------------------ Log */
export function log(level, message) {
  const entry = { t: Date.now(), level, message: String(message) };
  pushLog(entry);
  appendLogLine(entry);
}

function appendLogLine(entry) {
  const host = document.getElementById('loglines');
  if (!host) return;
  const empty = host.querySelector('.logdock__empty');
  if (empty) empty.remove();
  host.appendChild(
    h(
      'div',
      { class: `log-line log-line--${entry.level}` },
      h('span', { class: 'log-line__time', text: fmtClock(entry.t) }),
      h('span', { class: 'log-line__msg', text: entry.message }),
    ),
  );
  host.scrollTop = host.scrollHeight;
  updateLogCount();
}

export function updateLogCount() {
  const badge = document.getElementById('logcount');
  if (badge) badge.textContent = `${state.logs.length} entries`;
}

export function renderLogLines(host) {
  clear(host);
  if (!state.logs.length) {
    host.appendChild(h('div', { class: 'logdock__empty', text: 'No logs yet. Sign-in, self-checks and later task runs are recorded here.' }));
    return;
  }
  state.logs.forEach((entry) => {
    host.appendChild(
      h(
        'div',
        { class: `log-line log-line--${entry.level}` },
        h('span', { class: 'log-line__time', text: fmtClock(entry.t) }),
        h('span', { class: 'log-line__msg', text: entry.message }),
      ),
    );
  });
  host.scrollTop = host.scrollHeight;
}

export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const area = document.createElement('textarea');
    area.value = text;
    area.setAttribute('readonly', '');
    area.style.position = 'fixed';
    area.style.opacity = '0';
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand('copy');
    area.remove();
    return ok;
  }
}

/* -------------------------------------------------------------- Status widgets */
export function dot(state_, title) {
  const cls = state_ === 'running' ? 'u-dot--running' : state_ === 'success' ? 'u-dot--success' : state_ === 'error' ? 'u-dot--error' : '';
  return h('span', { class: `u-dot ${cls}`, title: title || '' });
}

export function badge(text, variant = '', title = '') {
  return h('span', { class: `u-badge ${variant ? `u-badge--${variant}` : ''}`, title, text });
}

export function emptyState(title, description, iconName = 'cube') {
  return h('div', { class: 'empty' }, icon(iconName, 34), h('h3', { text: title }), h('p', { text: description }));
}

/* -------------------------------------------------------------- Modals */
export function promptDialog({
  title = 'Enter value',
  message = '',
  label = '',
  type = 'text',
  placeholder = '',
  confirmText = 'OK',
  cancelText = 'Cancel',
} = {}) {
  return new Promise((resolve) => {
    let settled = false;
    const input = h('input', {
      class: 'input-plain',
      type,
      placeholder,
      autocomplete: 'off',
      spellcheck: 'false',
    });
    const finish = (value) => {
      if (settled) return;
      settled = true;
      document.removeEventListener('keydown', onKey);
      backdrop.remove();
      resolve(value);
    };
    const onKey = (event) => {
      if (event.key === 'Escape') finish(null);
      if (event.key === 'Enter') finish(input.value);
    };

    const backdrop = h(
      'div',
      {
        class: 'u-modal-backdrop',
        role: 'dialog',
        'aria-modal': 'true',
        on: {
          click: (event) => {
            if (event.target === backdrop) finish(null);
          },
        },
      },
      h(
        'div',
        { class: 'u-modal' },
        h('h3', { class: 'u-modal__title', text: title }),
        message ? h('p', { class: 'u-modal__text', text: message }) : null,
        h(
          'div',
          { class: 'u-field mt-16' },
          label ? h('label', { class: 'u-label', text: label }) : null,
          input,
        ),
        h(
          'div',
          { class: 'u-modal__actions' },
          h('button', { class: 'u-btn u-btn--sm u-btn--ghost', type: 'button', on: { click: () => finish(null) } }, cancelText),
          h('button', { class: 'u-btn u-btn--sm u-btn--danger', type: 'button', on: { click: () => finish(input.value) } }, confirmText),
        ),
      ),
    );

    document.body.appendChild(backdrop);
    document.addEventListener('keydown', onKey);
    input.focus();
  });
}

export function confirmDialog({
  title = 'Confirm action',
  message = '',
  confirmText = 'OK',
  cancelText = 'Cancel',
  danger = false,
} = {}) {
  return new Promise((resolve) => {
    let settled = false;
    const finish = (value) => {
      if (settled) return;
      settled = true;
      document.removeEventListener('keydown', onKey);
      backdrop.remove();
      resolve(value);
    };
    const onKey = (event) => {
      if (event.key === 'Escape') finish(false);
      if (event.key === 'Enter') finish(true);
    };

    const backdrop = h(
      'div',
      {
        class: 'u-modal-backdrop',
        role: 'dialog',
        'aria-modal': 'true',
        on: {
          click: (event) => {
            if (event.target === backdrop) finish(false);
          },
        },
      },
      h(
        'div',
        { class: 'u-modal' },
        h('h3', { class: 'u-modal__title', text: title }),
        h('p', { class: 'u-modal__text', text: message }),
        h(
          'div',
          { class: 'u-modal__actions' },
          h('button', { class: 'u-btn u-btn--sm u-btn--ghost', type: 'button', on: { click: () => finish(false) } }, cancelText),
          h(
            'button',
            {
              class: `u-btn u-btn--sm ${danger ? 'u-btn--danger' : 'u-btn--ghost'}`,
              type: 'button',
              on: { click: () => finish(true) },
            },
            confirmText,
          ),
        ),
      ),
    );

    document.body.appendChild(backdrop);
    document.addEventListener('keydown', onKey);
    backdrop.querySelector('.u-modal__actions button:last-child').focus();
  });
}