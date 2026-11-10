/**
 * prefs.js — browser local preferences (stores only server address/username, never passwords).
 */

const KEY = 'dp.web.lastLogin';

const DEFAULTS = {
  host: '',
  username: '',
  proto: 'https',
  tlsVerify: false,
  remember: true,
};

export function readPrefs() {
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return { ...DEFAULTS };
    const parsed = JSON.parse(raw);
    return {
      host: typeof parsed.host === 'string' ? parsed.host : '',
      username: typeof parsed.username === 'string' ? parsed.username : '',
      proto: parsed.proto === 'http' ? 'http' : 'https',
      tlsVerify: Boolean(parsed.tlsVerify),
      remember: parsed.remember !== false,
    };
  } catch {
    return { ...DEFAULTS };
  }
}

export function writePrefs(prefs) {
  try {
    window.localStorage.setItem(
      KEY,
      JSON.stringify({
        host: prefs.host || '',
        username: prefs.username || '',
        proto: prefs.proto === 'http' ? 'http' : 'https',
        tlsVerify: Boolean(prefs.tlsVerify),
        remember: prefs.remember !== false,
      }),
    );
  } catch {
    /* localStorage unavailable in private mode; ignore */
  }
}

export function clearPrefs() {
  try {
    window.localStorage.removeItem(KEY);
  } catch {
    /* ignore */
  }
}

/* ------------------------------------------------- log dock height (draggable panel) */

const LOG_HEIGHT_KEY = 'dp.web.logHeight';

/** Saved run-log height in CSS px; 0 means "never set". */
export function readLogHeight() {
  try {
    const value = parseFloat(window.localStorage.getItem(LOG_HEIGHT_KEY) || '');
    return Number.isFinite(value) && value > 0 ? value : 0;
  } catch {
    return 0;
  }
}

export function writeLogHeight(value) {
  try {
    window.localStorage.setItem(LOG_HEIGHT_KEY, String(Math.round(value)));
  } catch {
    /* ignore */
  }
}

/* ------------------------------------------------- pipeline params (stored per mode) */

const PIPELINE_PREFIX = 'dp.web.pipeline.';

export function readPipelinePrefs(mode) {
  try {
    const raw = window.localStorage.getItem(`${PIPELINE_PREFIX}${mode}`);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch {
    return {};
  }
}

export function writePipelinePrefs(mode, values) {
  try {
    window.localStorage.setItem(`${PIPELINE_PREFIX}${mode}`, JSON.stringify(values || {}));
  } catch {
    /* ignore */
  }
}

export function clearPipelinePrefs(mode) {
  try {
    window.localStorage.removeItem(`${PIPELINE_PREFIX}${mode}`);
  } catch {
    /* ignore */
  }
}

/* ------------------------------------------------- theme preference */

const THEME_KEY = 'dp.web.theme';

export function readTheme() {
  try {
    const raw = window.localStorage.getItem(THEME_KEY);
    return ['dark', 'light', 'system'].includes(raw) ? raw : 'dark';
  } catch {
    return 'dark';
  }
}

export function writeTheme(theme) {
  try {
    window.localStorage.setItem(THEME_KEY, theme);
  } catch {
    /* ignore */
  }
}

/* ------------------------------------------------- sidebar collapsed */

const SIDEBAR_KEY = 'dp.web.sidebarCollapsed';

export function readSidebarCollapsed() {
  try {
    return window.localStorage.getItem(SIDEBAR_KEY) === '1';
  } catch {
    return false;
  }
}

export function writeSidebarCollapsed(collapsed) {
  try {
    window.localStorage.setItem(SIDEBAR_KEY, collapsed ? '1' : '0');
  } catch {
    /* ignore */
  }
}
