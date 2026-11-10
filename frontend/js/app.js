/**
 * app.js — boot flow, app shell and routing.
 *
 * Gate logic: without a server session confirmed by /api/auth/session, only the
 * login page renders; every business view is built only after isAuthed() is true,
 * and any 401 immediately kicks back to the login page.
 */

import { api, onUnauthorized } from './api.js';
import { isAuthed, setState, state, subscribe } from './store.js';
import { readLogHeight, writeLogHeight, readSidebarCollapsed, writeSidebarCollapsed } from './prefs.js';
import { initTheme, applyTheme, getThemeSetting, buildThemeControl } from './theme.js';
import { NAV_ROUTES, currentPath, isKnownPath, navigate } from './router.js';
import {
  badge,
  clear,
  confirmDialog,
  copyText,
  h,
  icon,
  log,
  renderLogLines,
  toast,
  updateLogCount,
} from './ui.js';
import { mountLogin } from './views/login.js';
import { dashboardView } from './views/dashboard.js';
import { pipelineView } from './views/pipeline.js';
import { searchDeleteView } from './views/search-delete.js';
import { siptrunkView } from './views/siptrunk.js';
import { toolsView } from './views/tools.js';
import { ttsView } from './views/tts.js';
import { htekView } from './views/htek.js';
import { auditView } from './views/audit.js';
import { settingsView } from './views/settings.js';
import { initZoom, resetZoom, zoomBy } from './zoom.js';

const appEl = document.getElementById('app');

// Views are resolved lazily. `pipelineView(mode)` snapshots `state.config.tasks` when it
// is called, so building it here (before boot() has fetched /api/config) produced an
// empty task list on the very first visit to Standard/Complex — later visits worked only
// because config was cached by then.
const VIEW_FACTORIES = {
  '/dashboard': () => dashboardView,
  '/standard': () => pipelineView('standard'),
  '/complex': () => pipelineView('complex'),
  '/search-delete': () => searchDeleteView,
  '/siptrunk': () => siptrunkView,
  '/tools': () => toolsView,
  '/tts': () => ttsView,
  '/htek': () => htekView,
  '/audit': () => auditView,
  '/settings': () => settingsView,
};

function resolveView(path) {
  const factory = VIEW_FACTORIES[path] || (() => dashboardView);
  return factory();
}

let screen = null; // 'login' | 'shell'
let refs = null; // node references inside the shell
let currentView = null; // current view (for unmounting timers / later SSE streams)

function teardownView() {
  if (currentView && typeof currentView.unmount === 'function') {
    try {
      currentView.unmount();
    } catch (error) {
      console.error(error);
    }
  }
  currentView = null;
}

function hostLabel(url) {
  if (!url) return 'Not connected';
  return String(url).replace(/^https?:\/\//, '').replace(/\/+$/, '');
}

/* ----------------------------------------------------------- Login page */
function showLogin() {
  if (screen === 'login') return;
  teardownView();
  screen = 'login';
  refs = null;
  clear(appEl);
  document.title = `Sign in · ${(state.config && state.config.appName) || 'Anderson Deltapath-Automation'}`;
  mountLogin(appEl, {
    onAuthenticated: () => {
      screen = null;
      // Land on the dashboard only when the URL does not already point somewhere
      // real. Forcing /dashboard here raced with a quick click on Standard/Complex:
      // this callback could fire after the user's navigation and re-render the
      // dashboard over it (the "first visit shows Overview" bug).
      const path = currentPath();
      if (path === '/login' || !isKnownPath(path)) {
        navigate('/dashboard', { replace: true });
      }
      onRoute();
    },
  });
}

/* ----------------------------------------------------------- App shell */
function buildShell() {
  const navItems = new Map();
  const groups = [];
  NAV_ROUTES.forEach((item) => {
    let group = groups.find((entry) => entry.name === item.group);
    if (!group) {
      group = { name: item.group, items: [] };
      groups.push(group);
    }
    group.items.push(item);
  });

  const navSections = groups.map((group) =>
    h(
      'div',
      {},
      h('div', { class: 'sidebar__section', text: group.name }),
      h(
        'nav',
        { class: 'nav' },
        group.items.map((item) => {
          const el = h(
            'a',
            { class: 'nav__item', href: `#${item.path}` },
            icon(item.icon, 18),
            h('span', { text: item.label }),
            item.badge ? badge(item.badge, '') : null,
          );
          navItems.set(item.path, el);
          return el;
        }),
      ),
    ),
  );

  const pillDot = h('span', { class: 'u-dot u-dot--success' });
  const pillText = h('span', { text: 'Connected' });
  const pillHost = h('span', { class: 'conn-pill__host', text: hostLabel(state.session.baseUrl) });
  const userName = h('div', { class: 'sidebar__user-name', text: state.session.username || '—' });
  const userHost = h('div', { class: 'sidebar__user-host', text: hostLabel(state.session.baseUrl) });
  const zoomValue = h('span', { class: 'zoomctl__value', text: `${Math.round(state.zoom * 100)}%` });
  document.addEventListener('dp:zoom', (event) => {
    zoomValue.textContent = `${Math.round(event.detail * 100)}%`;
  });

  let isSidebarCollapsed = readSidebarCollapsed();

  let sidebarCollapseBtn = null;
  const toggleSidebar = (force) => {
    isSidebarCollapsed = typeof force === 'boolean' ? force : !isSidebarCollapsed;
    shell.classList.toggle('is-sidebar-collapsed', isSidebarCollapsed);
    writeSidebarCollapsed(isSidebarCollapsed);
    if (sidebarCollapseBtn) {
      clear(sidebarCollapseBtn).appendChild(icon(isSidebarCollapsed ? 'sidebarExpand' : 'sidebarCollapse', 16));
      sidebarCollapseBtn.title = isSidebarCollapsed ? 'Expand sidebar (Ctrl+B)' : 'Collapse sidebar (Ctrl+B)';
    }
  };

  sidebarCollapseBtn = h(
    'button',
    {
      class: 'sidebar__collapse-btn',
      type: 'button',
      title: isSidebarCollapsed ? 'Expand sidebar (Ctrl+B)' : 'Collapse sidebar (Ctrl+B)',
      'aria-label': 'Toggle sidebar',
      on: { click: () => toggleSidebar() },
    },
    icon(isSidebarCollapsed ? 'sidebarExpand' : 'sidebarCollapse', 16),
  );

  const sidebar = h(
    'aside',
    { class: 'sidebar' },
    h(
      'div',
      { class: 'sidebar__brand' },
      h('div', { class: 'sidebar__logo' }, h('img', { class: 'sidebar__logo-img', src: '/logo.png', alt: (state.config && state.config.appName) || 'Anderson Deltapath-Automation', width: 22, height: 22 })),
      h(
        'div',
        { class: 'sidebar__brand-text', style: { minWidth: '0' } },
        h('div', { class: 'sidebar__title', text: (state.config && state.config.appName) || 'Anderson Deltapath-Automation' }),
        h('div', { class: 'sidebar__version', text: `v${(state.config && state.config.version) || '—'}` }),
      ),
      sidebarCollapseBtn,
    ),
    // The nav list scrolls on its own: the brand and the user/sign-out block stay
    // pinned, so every entry stays reachable no matter how many routes exist or
    // how far the UI is zoomed.
    h('div', { class: 'sidebar__scroll' }, ...navSections),
    h('div', { class: 'sidebar__user' }, icon('user', 20), h('div', { class: 'sidebar__user-meta' }, userName, userHost)),
    h(
      'button',
      { class: 'u-btn u-btn--danger u-btn--sm u-btn--block', type: 'button', on: { click: onLogout } },
      icon('logout', 16),
      'Sign out',
    ),
  );

  // Make the fact that the menu scrolls visible: flag when there is more below,
  // and flag when the user has reached the end. The panel itself is scrollable too
  // (safety net), so watch both it and the inner list.
  const sidebarScroll = sidebar.querySelector('.sidebar__scroll');
  const scrollTargets = [sidebarScroll, sidebar].filter(Boolean);
  let scrollButtonLabel = null;
  const syncSidebarScroll = () => {
    const overflowing = scrollTargets.some((node) => node.scrollHeight > node.clientHeight + 2);
    const atEnd = scrollTargets.every(
      (node) => node.scrollTop + node.clientHeight >= node.scrollHeight - 2,
    );
    sidebar.classList.toggle('is-scrollable', overflowing);
    sidebar.classList.toggle('is-scrolled-end', !overflowing || atEnd);
    if (scrollButtonLabel) scrollButtonLabel.textContent = atEnd ? 'Top' : 'More';
  };
  scrollTargets.forEach((node) => {
    node.addEventListener('scroll', syncSidebarScroll, { passive: true });
    if (typeof ResizeObserver !== 'undefined') new ResizeObserver(syncSidebarScroll).observe(node);
  });
  window.addEventListener('resize', syncSidebarScroll);
  window.addEventListener('orientationchange', syncSidebarScroll);
  // Re-check after the first paint, when fonts/labels have settled.
  requestAnimationFrame(syncSidebarScroll);
  setTimeout(syncSidebarScroll, 300);
  setTimeout(syncSidebarScroll, 1200);

  // Explicit scroll control: shown only while the menu overflows, so the menu can
  // always be moved down (and back up) even if wheel/touch scrolling misbehaves.
  const scrollMenuButton = h(
    'button',
    {
      class: 'sidebar__scrollbtn',
      type: 'button',
      title: 'Scroll the menu',
      on: {
        click: () => {
          const node = sidebarScroll || sidebar;
          const atEnd = node.scrollTop + node.clientHeight >= node.scrollHeight - 4;
          const target = atEnd ? 0 : node.scrollTop + Math.round(node.clientHeight * 0.85);
          if (typeof node.scrollTo === 'function') node.scrollTo({ top: target, behavior: 'smooth' });
          else node.scrollTop = target;
          setTimeout(syncSidebarScroll, 350);
        },
      },
    },
    icon('chevron', 16),
    h('span', { text: 'More' }),
  );
  const userBlock = sidebar.querySelector('.sidebar__user');
  if (userBlock) sidebar.insertBefore(scrollMenuButton, userBlock);
  else sidebar.appendChild(scrollMenuButton);
  scrollButtonLabel = scrollMenuButton.querySelector('span');
  syncSidebarScroll();

  const titleEl = h('h1', { class: 'topbar__title', text: 'Dashboard' });
  const subEl = h('p', { class: 'topbar__sub', text: '' });

  const topbar = h(
    'header',
    { class: 'topbar' },
    h(
      'button',
      {
        class: 'u-input-action hamburger',
        type: 'button',
        title: 'Menu',
        'aria-label': 'Open menu',
        on: { click: () => shell.classList.toggle('is-nav-open') },
      },
      icon('menu', 20),
    ),
    h(
      'button',
      {
        class: 'u-input-action topbar__sidebar-toggle',
        type: 'button',
        title: 'Toggle sidebar (Ctrl+B)',
        'aria-label': 'Toggle sidebar',
        on: { click: () => toggleSidebar() },
      },
      icon('sidebarCollapse', 18),
    ),
    h('div', { class: 'topbar__titles' }, titleEl, subEl),
    h(
      'div',
      { class: 'topbar__tools' },
      h('div', { class: 'conn-pill' }, pillDot, pillText, pillHost),
      buildThemeControl(),
      h(
        'div',
        { class: 'zoomctl' },
        h('button', { class: 'zoomctl__btn', type: 'button', title: 'Zoom out', on: { click: () => zoomBy(-0.05) } }, icon('zoomOut', 16)),
        h('span', { class: 'zoomctl__value', title: 'Reset to 100%', on: { click: () => resetZoom() }, text: `${Math.round(state.zoom * 100)}%` }),
        h('button', { class: 'zoomctl__btn', type: 'button', title: 'Zoom in', on: { click: () => zoomBy(0.05) } }, icon('zoomIn', 16)),
      ),
    ),
  );

  const viewHost = h('div', { class: 'view' });

  const loglines = h('div', { class: 'logdock__lines', id: 'loglines' });
  const logTools = h(
    'div',
    {
      class: 'logdock__tools',
      on: {
        click: (event) => event.stopPropagation(),
      },
    },
    h(
      'button',
      {
        class: 'u-btn u-btn--sm u-btn--ghost',
        type: 'button',
        on: {
          click: async () => {
            const text = state.logs.map((entry) => `${new Date(entry.t).toISOString()} [${entry.level}] ${entry.message}`).join('\n');
            const ok = await copyText(text || '');
            toast(ok ? 'ok' : 'err', ok ? 'Log copied' : 'Copy failed');
          },
        },
      },
      icon('copy', 15),
      'Copy',
    ),
    h(
      'button',
      {
        class: 'u-btn u-btn--sm u-btn--ghost',
        type: 'button',
        on: {
          click: () => {
            state.logs.length = 0;
            renderLogLines(loglines);
            updateLogCount();
          },
        },
      },
      icon('trash', 15),
      'Clear',
    ),
  );
  const dock = h(
    'div',
    { class: 'logdock is-open' },
    h(
      'div',
      { class: 'logdock__bar', on: { click: () => dock.classList.toggle('is-open') } },
      icon('chevron', 16),
      h('span', { class: 'logdock__title', text: 'Run log' }),
      h('span', { class: 'logdock__count', id: 'logcount' }),
      logTools,
    ),
    h('div', { class: 'logdock__body' }, loglines),
  );

  /* ---- Draggable run-log height (persisted; zoom-aware) ---- */
  const LOG_MIN = 90;
  const LOG_DEFAULT = 246;
  /** Never let the panel eat more than the viewport (remember: heights live in zoomed px). */
  const maxLogHeight = () => Math.max(LOG_MIN, Math.round(window.innerHeight / (state.zoom || 1)) - 190);

  let logHeight = Math.min(Math.max(readLogHeight() || LOG_DEFAULT, LOG_MIN), maxLogHeight());
  const applyLogHeight = () => dock.style.setProperty('--log-height', `${Math.round(logHeight)}px`);

  let dragging = false;
  let dragStartY = 0;
  let dragStartHeight = 0;

  const resizeHandle = h('div', {
    class: 'logdock__resize',
    title: 'Drag to resize · double-click to reset',
  });
  const clampLogHeight = (value) => Math.min(Math.max(value, LOG_MIN), maxLogHeight());

  resizeHandle.addEventListener('pointerdown', (event) => {
    dragging = true;
    dragStartY = event.clientY;
    dragStartHeight = logHeight;
    dock.classList.add('is-resizing');
    dock.classList.add('is-open');
    try {
      resizeHandle.setPointerCapture(event.pointerId);
    } catch {
      /* pointer capture is best-effort */
    }
    event.preventDefault();
  });
  resizeHandle.addEventListener('pointermove', (event) => {
    if (!dragging) return;
    // Pointer coordinates are in unzoomed screen px, the panel height is in zoomed px.
    const delta = (dragStartY - event.clientY) / (state.zoom || 1);
    logHeight = clampLogHeight(dragStartHeight + delta);
    applyLogHeight();
  });
  const endDrag = (event) => {
    if (!dragging) return;
    dragging = false;
    dock.classList.remove('is-resizing');
    writeLogHeight(logHeight);
    try {
      resizeHandle.releasePointerCapture(event.pointerId);
    } catch {
      /* ignore */
    }
  };
  resizeHandle.addEventListener('pointerup', endDrag);
  resizeHandle.addEventListener('pointercancel', endDrag);
  resizeHandle.addEventListener('dblclick', () => {
    logHeight = clampLogHeight(LOG_DEFAULT);
    applyLogHeight();
    writeLogHeight(logHeight);
  });
  window.addEventListener('resize', () => {
    logHeight = clampLogHeight(logHeight);
    applyLogHeight();
  });
  dock.prepend(resizeHandle);
  applyLogHeight();

  const shell = h(
    'div',
    {
      class: 'shell',
      on: {
        click: (event) => {
          if (event.target === shell && shell.classList.contains('is-nav-open')) {
            shell.classList.remove('is-nav-open');
          }
        },
      },
    },
    sidebar,
    h('main', { class: 'main' }, topbar, viewHost, dock),
  );

  if (isSidebarCollapsed) {
    shell.classList.add('is-sidebar-collapsed');
  }

  // Global Ctrl+B shortcut to toggle sidebar
  window.addEventListener('keydown', (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'b' && !event.shiftKey && !event.altKey) {
      const active = document.activeElement;
      if (active && (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA')) return;
      event.preventDefault();
      toggleSidebar();
    }
  });

  clear(appEl).appendChild(shell);
  screen = 'shell';
  refs = { shell, navItems, titleEl, subEl, viewHost, pillDot, pillText, pillHost, userName, userHost, loglines };
  renderLogLines(loglines);
  updateLogCount();
  updateTopbar();
}

function updateTopbar() {
  if (!refs) return;
  const session = state.session || {};
  refs.userName.textContent = session.username || '—';
  refs.userHost.textContent = hostLabel(session.baseUrl);
  refs.pillHost.textContent = hostLabel(session.baseUrl);
  const probe = state.probe;
  refs.pillDot.className = `u-dot ${probe && probe.ok === false ? 'u-dot--error' : 'u-dot--success'}`;
  refs.pillText.textContent = probe && probe.ok === false ? 'API error' : 'Connected';
}

/* ----------------------------------------------------------- Routing */
function renderView(path) {
  if (!refs) return;
  const view = resolveView(path);
  teardownView();
  currentView = view;
  refs.titleEl.textContent = view.title;
  refs.subEl.textContent = view.subtitle || '';
  document.title = `${view.title} · ${(state.config && state.config.appName) || 'Anderson Deltapath-Automation'}`;
  refs.navItems.forEach((el, itemPath) => el.classList.toggle('is-active', itemPath === path));
  refs.shell.classList.remove('is-nav-open');
  clear(refs.viewHost);
  view.mount(refs.viewHost);
  window.scrollTo({ top: 0 });
}

function onRoute() {
  if (!isAuthed()) {
    showLogin();
    return;
  }
  const path = currentPath();
  if (path === '/login' || !isKnownPath(path)) {
    navigate('/dashboard', { replace: true });
    return;
  }
  if (screen !== 'shell') buildShell();
  renderView(path);
}

/* ----------------------------------------------------------- Logout */
async function performLogout({ confirm }) {
  if (confirm) {
    const ok = await confirmDialog({
      title: 'Sign out',
      message: 'The PBX session stored on the server will be dropped; you must enter your PBX credentials again to continue.',
      confirmText: 'Sign out',
      danger: true,
    });
    if (!ok) return;
  }
  try {
    await api.logout();
  } catch (error) {
    log('warn', `Logout request failed (local cleanup still runs): ${error.message}`);
  }
  setState({ session: { authenticated: false }, probe: null });
  log('info', 'Signed out');
  if (confirm) toast('ok', 'Signed out');
  screen = null;
  showLogin();
  navigate('/login', { replace: true });
}

function onLogout() {
  performLogout({ confirm: true });
}

function onSessionExpired() {
  if (screen === 'login') return;
  setState({ session: { authenticated: false }, probe: null });
  log('warn', 'Session expired, please sign in again.');
  toast('warn', 'Session expired, please sign in again.');
  screen = null;
  showLogin();
  navigate('/login', { replace: true });
}

/* ----------------------------------------------------------- Boot */
async function boot() {
  initTheme();
  initZoom();
  onUnauthorized(onSessionExpired);
  subscribe(updateTopbar);

  try {
    const config = await api.config();
    setState({ config });
    log('info', `Runtime config loaded: ${config.appName} v${config.version}`);
  } catch (error) {
    log('err', `Failed to read runtime config: ${error.message}`);
    toast('err', 'Backend service unavailable, please check the container status.');
  }

  try {
    const session = await api.session();
    setState({ session });
    if (session.authenticated) {
      log('ok', `Session restored: ${session.username}@${session.baseUrl} (mode ${session.loginMode})`);
    } else {
      log('info', 'Not signed in; waiting for PBX credentials.');
    }
  } catch (error) {
    setState({ session: { authenticated: false } });
    log('err', `Session check failed: ${error.message}`);
  }

  setState({ ready: true });
  window.addEventListener('hashchange', onRoute);
  onRoute();
}

boot();
