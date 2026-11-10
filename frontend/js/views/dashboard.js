/**
 * views/dashboard.js — Dashboard: connection status, session info, PBX self-check, migration progress.
 */

import { api } from '../api.js';
import { state, setState } from '../store.js';
import { badge, clear, dot, emptyState, fmtDateTime, fmtDuration, h, icon, log, toast } from '../ui.js';

let autoProbeStarted = false;
let durationNode = null;
let ticker = null;
let recentAudit = null;
let auditLoading = false;
/** Set on unmount so late async callbacks cannot repaint a page the user left. */
let unmounted = false;

/** Session age is computed live from the browser clock, not from the backend snapshot. */
function liveAge(session) {
  if (!session || !session.createdAt) return 0;
  return Math.max(0, Math.floor(Date.now() / 1000 - session.createdAt));
}

function statCard(label, iconName, value, hint, extra) {
  return h(
    'div',
    { class: 'u-card stat' },
    h('div', { class: 'stat__label' }, icon(iconName, 16), label),
    h('div', { class: 'stat__value' }, value),
    h('div', { class: 'stat__hint', text: hint || '' }),
    extra || null,
  );
}

function probeRow(item) {
  return h(
    'tr',
    {},
    h('td', {}, h('div', { class: 'row' }, item.ok ? dot('success') : dot('error'), h('span', { text: item.label }))),
    h('td', { class: 'mono', text: item.endpoint.replace('RESTful/index.php/', '') }),
    h('td', { class: 'mono', text: item.statusCode ? String(item.statusCode) : '—' }),
    h('td', { class: 'mono', text: item.latencyMs != null ? `${item.latencyMs} ms` : '—' }),
    h('td', {}, item.detail ? h('span', { class: 'muted', text: item.detail }) : h('span', { class: 'muted', text: item.rows != null ? `${item.rows} rows` : 'OK' })),
  );
}

function probeBody(onRefresh) {
  const probe = state.probe;
  if (!probe) {
    return h(
      'div',
      {},
      h('div', { class: 'u-skeleton', style: { height: '108px', width: '100%' } }),
      h('p', { class: 'muted mt-16', text: 'Running PBX connectivity self-check…' }),
    );
  }
  return h(
    'div',
    {},
    h(
      'div',
      { class: 'row row--between' },
      h(
        'div',
        { class: 'row' },
        probe.ok ? badge('All passed', 'ok') : badge('Issues found', 'err'),
        h('span', { class: 'muted mono', text: `${probe.results.length} probes · ${new Date(probe.checkedAt).toLocaleTimeString()}` }),
      ),
      h(
        'button',
        { class: 'u-btn u-btn--sm', type: 'button', on: { click: () => runProbe(onRefresh) } },
        icon('refresh', 16),
        'Re-run self-check',
      ),
    ),
    h(
      'div',
      { class: 'table-wrap mt-16' },
      h(
        'table',
        { class: 'table' },
        h(
          'thead',
          {},
          h(
            'tr',
            {},
            h('th', { text: 'Probe' }),
            h('th', { text: 'Endpoint' }),
            h('th', { text: 'HTTP' }),
            h('th', { text: 'Latency' }),
            h('th', { text: 'Result' }),
          ),
        ),
        h('tbody', {}, probe.results.map(probeRow)),
      ),
    ),
  );
}

async function runProbe(onRefresh) {
  setState({ probe: null });
  if (onRefresh) onRefresh();
  log('info', 'Starting PBX connectivity self-check…');
  try {
    const result = await api.probe();
    setState({ probe: result });
    log(result.ok ? 'ok' : 'warn', `Self-check done: ${result.results.filter((item) => item.ok).length}/${result.results.length} endpoints OK.`);
    if (!result.ok) toast('warn', 'Some endpoints failed; see the self-check table.');
  } catch (error) {
    if (error.status === 401) return;
    setState({ probe: { ok: false, checkedAt: Date.now(), baseUrl: state.session.baseUrl || '', results: [] } });
    log('err', `Self-check failed: ${error.message}`);
    toast('err', `Self-check failed: ${error.message}`);
  }
  if (onRefresh) onRefresh();
}

function auditCard() {
  const rows = recentAudit;
  return h(
    'section',
    { class: 'u-card' },
    h(
      'div',
      { class: 'u-card__head' },
      h('div', {}, h('h3', { class: 'u-card__title', text: 'Recent Activity' }), h('p', { class: 'u-card__sub', text: 'Audit log of logins, pipeline runs and deletions' })),
      h('a', { class: 'u-btn u-btn--sm', href: '#/audit' }, 'View all'),
    ),
    h(
      'div',
      { class: 'u-card__body' },
      rows === null
        ? h('div', { class: 'u-skeleton', style: { height: '96px', width: '100%' } })
        : rows.length === 0
          ? h('div', { class: 'records-empty', text: 'No records yet.' })
          : h(
              'ul',
              { class: 'tasklist' },
              rows.slice(0, 6).map((entry) =>
                h(
                  'li',
                  {},
                  dot(entry.ok ? 'success' : 'error'),
                  h(
                    'span',
                    {},
                    h('span', { class: 'tasklist__name', text: entry.kindLabel }),
                    h('span', { class: 'tasklist__cn', text: ` ${entry.actor} · ${entry.summary}` }),
                  ),
                  badge(new Date(entry.ts * 1000).toLocaleTimeString(), ''),
                ),
              ),
            ),
    ),
  );
}

export const dashboardView = {
  title: 'Dashboard',
  subtitle: 'Connection status, session info and recent activity',
  mount(root) {
    unmounted = false;
    const render = () => {
      // Guard against late async callbacks (probe / audit fetch) repainting the
      // dashboard after the user already navigated away — that used to overwrite
      // the Standard/Complex page with the dashboard on the first visit.
      if (unmounted || !root.isConnected) return;
      const session = state.session || {};
      const config = state.config || {};
      const probe = state.probe;
      durationNode = h('span', { text: fmtDuration(liveAge(session)) });

      clear(root).append(
        h('div', { class: 'page-head' }, h('div', {}, h('h2', { text: 'Overview' }), h('p', { text: 'The data below comes from live backend and PBX probes; every PBX call goes through the server-side proxy.' }))),
        h(
          'div',
          { class: 'grid grid--stats' },
          statCard(
            'PBX Connection',
            'server',
            probe ? (probe.ok ? 'OK' : 'Error') : session.authenticated ? 'Signed in' : 'Not connected',
            session.baseUrl || '—',
          ),
          statCard('Login Mode', 'shield', session.loginMode === 'session' ? 'Web session' : 'RESTful', session.loginMode === 'session' ? 'authProcess.php fallback login' : 'auth/login direct login'),
          statCard('Session Age', 'clock', durationNode, `Auto-expires after ${config.sessionIdleMinutes || 60} min idle`),
          statCard('Backend Version', 'gauge', config.version || '—', config.appName || ''),
        ),
        h(
          'div',
          { class: 'grid grid--two mt-20' },
          h(
            'section',
            { class: 'u-card' },
            h(
              'div',
              { class: 'u-card__head' },
              h('div', {}, h('h3', { class: 'u-card__title', text: 'PBX Connectivity Self-Check' }), h('p', { class: 'u-card__sub', text: 'Verifies that the session can still read restricted endpoints' })),
            ),
            h('div', { class: 'u-card__body' }, probeBody(render)),
          ),
          auditCard(),
          h(
            'section',
            { class: 'u-card' },
            h(
              'div',
              { class: 'u-card__head' },
              h('div', {}, h('h3', { class: 'u-card__title', text: 'Session Info' }), h('p', { class: 'u-card__sub', text: 'The session lives in server memory; the browser only holds an HttpOnly cookie' })),
            ),
            h(
              'div',
              { class: 'u-card__body' },
              h(
                'dl',
                { class: 'kv' },
                h('dt', { text: 'PBX Address' }),
                h('dd', { text: session.baseUrl || '—' }),
                h('dt', { text: 'Username' }),
                h('dd', { text: session.username || '—' }),
                h('dt', { text: 'Login Method' }),
                h('dd', { text: session.loginMode || '—' }),
                h('dt', { text: 'Created' }),
                h('dd', { text: fmtDateTime(session.createdAt ? session.createdAt * 1000 : null) }),
                h('dt', { text: 'Last Activity' }),
                h('dd', { text: fmtDateTime(session.lastSeen ? session.lastSeen * 1000 : null) }),
                h('dt', { text: 'Session Limits' }),
                h('dd', { text: `idle ${config.sessionIdleMinutes || 60} min / absolute ${Math.round((session.absoluteTimeoutSeconds || 0) / 60) || 480} min` }),
              ),
            ),
          ),
        ),
      );

      if (!state.session.authenticated) {
        clear(root).appendChild(emptyState('Session expired', 'Sign in again to view the dashboard.', 'lock'));
      }
    };

    render();

    // Recent activity: fetched once on first mount, then the card is redrawn
    if (recentAudit === null && !auditLoading && state.session.authenticated) {
      auditLoading = true;
      api
        .auditEntries({ limit: 6 })
        .then((data) => {
          recentAudit = data.entries || [];
        })
        .catch(() => {
          recentAudit = [];
        })
        .finally(() => {
          auditLoading = false;
          render();
        });
    }

    if (ticker) clearInterval(ticker);
    ticker = setInterval(() => {
      if (durationNode) durationNode.textContent = fmtDuration(liveAge(state.session));
    }, 1000);

    if (!autoProbeStarted && state.session.authenticated) {
      autoProbeStarted = true;
      runProbe(render);
    }
  },
  unmount() {
    unmounted = true;
    if (ticker) {
      clearInterval(ticker);
      ticker = null;
    }
    durationNode = null;
  },
};
