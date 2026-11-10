/**
 * router.js — hash-based routing (no server rewrite rules needed).
 */

export const NAV_ROUTES = [
  { path: '/dashboard', label: 'Dashboard', icon: 'gauge', group: 'Overview' },
  { path: '/standard', label: 'Standard Mode', icon: 'layers', group: 'Pipeline' },
  { path: '/complex', label: 'Complex Mode', icon: 'wand', group: 'Pipeline' },
  { path: '/search-delete', label: 'Search & Delete', icon: 'trash', group: 'Extras' },
  { path: '/siptrunk', label: 'SIP Trunk Status', icon: 'server', group: 'Extras' },
  { path: '/tools', label: 'Name Split Tool', icon: 'sliders', group: 'Extras' },
  { path: '/tts', label: 'Text to Speech', icon: 'voice', group: 'Extras' },
  { path: '/htek', label: 'Htek Provisioning', icon: 'phone', group: 'Extras' },
  { path: '/audit', label: 'Audit Log', icon: 'clock', group: 'System' },
  { path: '/settings', label: 'Settings', icon: 'gear', group: 'System' },
];

const KNOWN = new Set([...NAV_ROUTES.map((item) => item.path), '/login']);

export function currentPath() {
  const raw = window.location.hash.replace(/^#/, '');
  if (!raw || raw === '/') return '/dashboard';
  const path = raw.split('?')[0];
  return path.startsWith('/') ? path : `/${path}`;
}

export function isKnownPath(path) {
  return KNOWN.has(path);
}

export function navigate(path, { replace = false } = {}) {
  const target = `#${path}`;
  if (window.location.hash === target) return;
  if (replace) {
    window.history.replaceState(null, '', target);
    window.dispatchEvent(new HashChangeEvent('hashchange'));
  } else {
    window.location.hash = target;
  }
}

export function startRouter(onRoute) {
  window.addEventListener('hashchange', onRoute);
  onRoute();
}
