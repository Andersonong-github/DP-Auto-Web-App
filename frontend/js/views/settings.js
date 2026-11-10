/**
 * views/settings.js — runtime config, UI zoom, and diagnostics.
 */

import { api } from '../api.js';
import { clearPrefs } from '../prefs.js';
import { state } from '../store.js';
import { badge, clear, confirmDialog, copyText, fmtDateTime, h, icon, log, toast } from '../ui.js';
import { applyTheme, getThemeSetting } from '../theme.js';
import { applyZoom, resetZoom, zoomBy } from '../zoom.js';

function kv(rows) {
  return h(
    'dl',
    { class: 'kv' },
    rows.flatMap(([term, value]) => [h('dt', { text: term }), h('dd', { text: value == null || value === '' ? '—' : String(value) })]),
  );
}

export const settingsView = {
  title: 'Settings',
  subtitle: 'Runtime config, UI zoom, and diagnostics',
  mount(root) {
    const config = state.config || {};
    const session = state.session || {};
    const healthSlot = h('div', { class: 'muted', text: 'Reading backend status…' });
    const zoomValue = h('span', { class: 'zoomctl__value', text: `${Math.round(state.zoom * 100)}%` });

    document.addEventListener(
      'dp:zoom',
      (event) => {
        zoomValue.textContent = `${Math.round(event.detail * 100)}%`;
      },
      { once: false },
    );

    const copyDiagnostics = async () => {
      const payload = {
        app: config.appName,
        version: config.version,
        session: {
          authenticated: session.authenticated,
          baseUrl: session.baseUrl,
          username: session.username,
          loginMode: session.loginMode,
          ageSeconds: session.ageSeconds,
        },
        probe: state.probe,
        userAgent: navigator.userAgent,
        logs: state.logs.map((entry) => `${new Date(entry.t).toISOString()} [${entry.level}] ${entry.message}`),
      };
      const ok = await copyText(JSON.stringify(payload, null, 2));
      toast(ok ? 'ok' : 'err', ok ? 'Diagnostics copied (no passwords)' : 'Copy failed');
      log('info', 'Export diagnostics (no passwords)');
    };

    clear(root).append(
      h(
        'div',
        { class: 'page-head' },
        h('div', {}, h('h2', { text: 'Settings' }), h('p', { text: 'Most configuration is supplied through container environment variables (DP_*); this page is read-only.' })),
      ),
      h(
        'div',
        { class: 'grid grid--two' },
        h(
          'section',
          { class: 'u-card' },
          h('div', { class: 'u-card__head' }, h('div', {}, h('h3', { class: 'u-card__title', text: 'Runtime Configuration' }))),
          h(
            'div',
            { class: 'u-card__body' },
            kv([
              ['App name', config.appName],
              ['Version', config.version],
              ['Default PBX address', config.defaultBaseUrl || 'Not set (DP_DEFAULT_BASE_URL)'],
              ['Session idle timeout', `${config.sessionIdleMinutes || 60} min`],
              ['Ignore certificate validation by default', config.tlsVerifyDefault ? 'Yes' : 'No'],
              ['Pipeline tasks', (config.tasks || []).length],
            ]),
          ),
        ),
        h(
          'section',
          { class: 'u-card' },
          h('div', { class: 'u-card__head' }, h('div', {}, h('h3', { class: 'u-card__title', text: 'Backend Status' }))),
          h('div', { class: 'u-card__body' }, healthSlot),
        ),
        h(
          'section',
          { class: 'u-card' },
          h(
            'div',
            { class: 'u-card__head' },
            h('div', {}, h('h3', { class: 'u-card__title', text: 'Color Theme' }), h('p', { class: 'u-card__sub', text: 'Choose dark mode, light mode, or follow system theme' })),
          ),
          h(
            'div',
            { class: 'u-card__body' },
            h(
              'div',
              { class: 'row', style: { gap: '10px' } },
              [
                { key: 'dark', label: 'Dark Mode', icon: 'moon' },
                { key: 'light', label: 'Light Mode', icon: 'sun' },
                { key: 'system', label: 'Follow System', icon: 'monitor' },
              ].map((opt) => {
                const isCurrent = getThemeSetting() === opt.key;
                return h(
                  'button',
                  {
                    class: `u-btn u-btn--sm ${isCurrent ? 'u-btn--primary' : 'u-btn--ghost'}`,
                    type: 'button',
                    on: {
                      click: () => {
                        applyTheme(opt.key);
                        toast('ok', `Theme set to: ${opt.label}`);
                        settingsView.mount(root);
                      },
                    },
                  },
                  icon(opt.icon, 15),
                  opt.label,
                );
              }),
            ),
            h(
              'p',
              { class: 'muted mt-16', text: 'Theme choice is saved locally and remembered across browser sessions.' },
            ),
          ),
        ),
        h(
          'section',
          { class: 'u-card' },
          h(
            'div',
            { class: 'u-card__head' },
            h('div', {}, h('h3', { class: 'u-card__title', text: 'UI Zoom' }), h('p', { class: 'u-card__sub', text: 'You can also zoom with Ctrl + scroll wheel (0.5x - 3.0x)' })),
          ),
          h(
            'div',
            { class: 'u-card__body' },
            h(
              'div',
              { class: 'row' },
              h('div', { class: 'zoomctl' }, h('button', { class: 'zoomctl__btn', type: 'button', title: 'Zoom out', on: { click: () => zoomBy(-0.05) } }, icon('zoomOut', 16)), zoomValue, h('button', { class: 'zoomctl__btn', type: 'button', title: 'Zoom in', on: { click: () => zoomBy(0.05) } }, icon('zoomIn', 16))),
              h('button', { class: 'u-btn u-btn--sm', type: 'button', on: { click: () => resetZoom() } }, 'Reset to 100%'),
            ),
            h(
              'p',
              { class: 'muted mt-16', text: 'Zoom level is stored locally in the browser and only affects the display size on this device.' },
            ),
          ),
        ),
        h(
          'section',
          { class: 'u-card' },
          h('div', { class: 'u-card__head' }, h('div', {}, h('h3', { class: 'u-card__title', text: 'Diagnostics & Local Data' }))),
          h(
            'div',
            { class: 'u-card__body' },
            h(
              'div',
              { class: 'row' },
              h('button', { class: 'u-btn u-btn--sm', type: 'button', on: { click: copyDiagnostics } }, icon('copy', 15), 'Copy diagnostics'),
              h(
                'button',
                {
                  class: 'u-btn u-btn--sm u-btn--danger',
                  type: 'button',
                  on: {
                    click: async () => {
                      const ok = await confirmDialog({
                        title: 'Clear local preferences',
                        message: 'This deletes the PBX address and username remembered by the browser (server sessions are unaffected).',
                        confirmText: 'Clear',
                        danger: true,
                      });
                      if (!ok) return;
                      clearPrefs();
                      log('info', 'Local preferences cleared');
                      toast('ok', 'Local preferences cleared');
                    },
                  },
                },
                icon('trash', 15),
                'Clear local preferences',
              ),
            ),
            h('p', { class: 'muted mt-16', text: 'Only the PBX address, username, protocol, and zoom level are stored locally; passwords are never written to disk.' }),
          ),
        ),
      ),
    );

    api
      .health()
      .then((data) => {
        clear(healthSlot).append(
          h(
            'div',
            { class: 'row', style: { marginBottom: '12px' } },
            badge('Backend online', 'ok'),
            h('span', { class: 'muted mono', text: 'GET /api/health' }),
          ),
          kv([
            ['Status', data.status],
            ['Version', data.version],
            ['Active sessions', `${data.activeSessions}`],
            ['Server time', fmtDateTime(data.time)],
          ]),
        );
      })
      .catch((error) => {
        clear(healthSlot).append(
          h('div', { class: 'u-alert u-alert--err' }, icon('alert', 18), h('div', { text: `Backend unavailable: ${error.message}` })),
        );
      });
  },
};
