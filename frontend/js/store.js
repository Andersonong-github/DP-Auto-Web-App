/**
 * store.js — Minimal global state container (no framework, subscription-based re-render).
 */

const subscribers = new Set();

export const state = {
  /** Runtime config from /api/config */
  config: null,
  /** { authenticated, baseUrl, username, ... } */
  session: { authenticated: false },
  /** Last /api/pbx/probe result */
  probe: null,
  /** Log console entries (keep at most MAX_LOGS) */
  logs: [],
  /** UI zoom factor, 0.5 - 3.0, matches desktop Ctrl+wheel */
  zoom: 1,
  /** Whether initialization is complete */
  ready: false,
};

const MAX_LOGS = 500;

export function subscribe(handler) {
  subscribers.add(handler);
  return () => subscribers.delete(handler);
}

export function setState(patch) {
  Object.assign(state, patch);
  subscribers.forEach((handler) => handler(state));
}

export function pushLog(entry) {
  state.logs.push(entry);
  if (state.logs.length > MAX_LOGS) state.logs.splice(0, state.logs.length - MAX_LOGS);
}

export function isAuthed() {
  return Boolean(state.session && state.session.authenticated);
}
