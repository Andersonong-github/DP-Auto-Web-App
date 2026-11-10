/**
 * zoom.js — UI zoom (matches the desktop Ctrl+wheel zoom, 0.5x - 3.0x).
 */

import { state } from './store.js';

const KEY = 'dp.web.zoom';
const MIN = 0.5;
const MAX = 3;
const STEP = 0.05;

function clamp(value) {
  return Math.min(MAX, Math.max(MIN, Math.round(value * 20) / 20));
}

export function readZoom() {
  try {
    const value = parseFloat(window.localStorage.getItem(KEY) || '1');
    return Number.isFinite(value) ? clamp(value) : 1;
  } catch {
    return 1;
  }
}

export function applyZoom(value) {
  const next = clamp(Number(value) || 1);
  state.zoom = next;
  const target = document.getElementById('app');
  if (target) target.style.zoom = String(next);
  // CSS `zoom` multiplies used lengths, so a 100vh container becomes zoom×viewport
  // tall and its bottom would be unreachable. Layout code divides by this variable
  // to stay exactly one viewport tall at any zoom level.
  document.documentElement.style.setProperty('--dp-zoom', String(next));
  try {
    window.localStorage.setItem(KEY, String(next));
  } catch {
    /* ignore */
  }
  document.dispatchEvent(new CustomEvent('dp:zoom', { detail: next }));
  return next;
}

export function zoomBy(delta) {
  return applyZoom(state.zoom + delta);
}

export function resetZoom() {
  return applyZoom(1);
}

/** Install Ctrl + wheel zoom. */
export function initZoom() {
  applyZoom(readZoom());
  document.addEventListener(
    'wheel',
    (event) => {
      if (!event.ctrlKey) return;
      event.preventDefault();
      zoomBy(event.deltaY < 0 ? STEP : -STEP);
    },
    { passive: false },
  );
}
