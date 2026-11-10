/**
 * api.js — the single gateway to the backend /api.
 *
 * Every request sends credentials: 'same-origin'; the session id lives in an
 * HttpOnly Cookie, so the frontend can never read the PBX credentials.
 */

const unauthorizedHandlers = new Set();

/** Register a "session expired" callback (used by app.js to return to the login page). */
export function onUnauthorized(handler) {
  unauthorizedHandlers.add(handler);
  return () => unauthorizedHandlers.delete(handler);
}

function apiError(message, status, code, extra = {}) {
  const error = new Error(message);
  error.status = status;
  error.code = code;
  Object.assign(error, extra);
  return error;
}

function detailMessage(payload, fallback) {
  const detail = payload && payload.detail;
  if (typeof detail === 'string' && detail) return detail;
  if (detail && typeof detail === 'object' && detail.message) return detail.message;
  if (detail && Array.isArray(detail) && detail.length) {
    // FastAPI validation error
    const first = detail[0];
    const field = Array.isArray(first.loc) ? first.loc[first.loc.length - 1] : '';
    return `${field ? field + ': ' : ''}${first.msg || 'Invalid parameter'}`;
  }
  return fallback;
}

async function request(path, options = {}) {
  const { method = 'GET', body, timeoutMs = 90000 } = options;
  const controller = new AbortController();
  const timer = timeoutMs ? setTimeout(() => controller.abort(), timeoutMs) : null;
  let response;

  try {
    response = await fetch(`/api${path}`, {
      method,
      credentials: 'same-origin',
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
      cache: 'no-store',
    });
  } catch (error) {
    if (error && error.name === 'AbortError') {
      throw apiError('Request timed out; the backend or PBX did not respond in time.', 0, 'timeout');
    }
    throw apiError('Cannot reach the backend service. Check that it is running.', 0, 'network');
  } finally {
    if (timer) clearTimeout(timer);
  }

  const text = await response.text();
  let payload = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = { detail: text.slice(0, 400) };
    }
  }

  if (!response.ok) {
    const code = (payload && payload.detail && payload.detail.code) || `http_${response.status}`;
    const raw = (payload && payload.detail && payload.detail.raw) || '';
    const error = apiError(
      detailMessage(payload, `Request failed (HTTP ${response.status})`),
      response.status,
      code,
      { raw, payload },
    );
    if (response.status === 401 && code === 'unauthenticated') {
      unauthorizedHandlers.forEach((handler) => {
        try {
          handler();
        } catch (err) {
          console.error(err);
        }
      });
    }
    throw error;
  }

  return payload;
}

export const api = {
  health: () => request('/health', { timeoutMs: 8000 }),
  config: () => request('/config', { timeoutMs: 8000 }),
  session: () => request('/auth/session', { timeoutMs: 10000 }),
  login: (credentials) => request('/auth/login', { method: 'POST', body: credentials, timeoutMs: 90000 }),
  logout: () => request('/auth/logout', { method: 'POST', timeoutMs: 10000 }),
  probe: () => request('/pbx/probe', { timeoutMs: 120000 }),
  /** For Complex mode: fetch this Group's Contexts by prefix (Custom / _Internal / _Fixed / …). */
  contexts: (groupName, prefix = '') =>
    request(`/pbx/contexts?group_name=${encodeURIComponent(groupName)}&prefix=${encodeURIComponent(prefix)}`, {
      timeoutMs: 60000,
    }),
  /** Every context on the PBX, across all Groups (desktop `_refresh_ctx_dropdowns`). */
  allContexts: () => request('/pbx/contexts/all', { timeoutMs: 90000 }),

  // ---- Pipeline ----
  /** Start a pipeline run and return the run snapshot (run id and task statuses). */
  startPipeline: (payload) => request('/pipeline/run', { method: 'POST', body: payload, timeoutMs: 30000 }),
  listRuns: () => request('/pipeline/runs', { timeoutMs: 15000 }),
  getRun: (runId) => request(`/pipeline/runs/${runId}`, { timeoutMs: 15000 }),
  stopRun: (runId) => request(`/pipeline/runs/${runId}/stop`, { method: 'POST', timeoutMs: 15000 }),
  /** SSE URL (EventSource cannot use the fetch wrapper). */
  runEventsUrl: (runId, after = 0) => `/api/pipeline/runs/${encodeURIComponent(runId)}/events?after=${after}`,
  recordsCsvUrl: (runId) => `/api/pipeline/runs/${encodeURIComponent(runId)}/records.csv`,

  // ---- Optional tasks: Search & Delete / SIP Trunk status ----
  searchEntities: () => request('/ops/entities', { timeoutMs: 15000 }),
  /** Group / Customer list for the Search & Delete Group dropdown. */
  opsGroups: () => request('/ops/groups', { timeoutMs: 60000 }),
  /** Search several object types at once; the response is grouped per object type. */
  searchObjects: (payload) => request('/ops/search', { method: 'POST', body: payload, timeoutMs: 180000 }),
  deleteObjects: (payload) => request('/ops/delete', { method: 'POST', body: payload, timeoutMs: 180000 }),
  siptrunkStatus: () => request('/ops/pbx/siptrunk/status', { timeoutMs: 90000 }),

  // ---- Search & Delete, desktop parity (20 task types, one keyword) ----
  /** The 20 task types of the desktop page, in desktop order. */
  optionalEntities: () => request('/ops/optional/entities', { timeoutMs: 15000 }),
  /** Search every checked task type with one keyword (group name or customer ID). */
  optionalSearch: (payload) => request('/ops/optional/search', { method: 'POST', body: payload, timeoutMs: 300000 }),
  /** Delete what the previous search found, walking the list in reverse. */
  optionalDelete: (payload) => request('/ops/optional/delete', { method: 'POST', body: payload, timeoutMs: 300000 }),

  // ---- Text to Speech (Extras) ----  /** Voice catalogue: languages, genders, voice ids, limits and sample scripts. */
  ttsVoices: () => request('/tts/voices', { timeoutMs: 20000 }),
  /**
   * Generate an MP3. Returns ``{ url, filename, bytes, voice, elapsedMs }`` where ``url`` is a
   * blob URL the caller must revoke; the audio itself never touches the JSON layer.
   */
  synthesizeSpeech: async ({ text, language, gender, rate, tone, format }, { timeoutMs = 120000 } = {}) => {
    const response = await fetch('/api/tts/synthesize', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, language, gender, rate, tone, format }),
      cache: 'no-store',
    });
    if (!response.ok) {
      const raw = await response.text();
      let message = `Voice generation failed (HTTP ${response.status})`;
      try {
        const payload = JSON.parse(raw);
        message = detailMessage(payload, message);
      } catch {
        /* keep the generic message */
      }
      throw apiError(message, response.status, 'tts_error');
    }
    const blob = await response.blob();
    const filename = response.headers.get('X-TTS-Filename') || 'tts.mp3';
    return {
      url: URL.createObjectURL(blob),
      blob,
      filename,
      bytes: Number(response.headers.get('X-TTS-Bytes')) || blob.size,
      voice: response.headers.get('X-TTS-Voice') || '',
      tone: response.headers.get('X-TTS-Tone') || '',
      format: response.headers.get('X-TTS-Format') || 'mp3',
      elapsedMs: Number(response.headers.get('X-TTS-Elapsed-Ms')) || 0,
    };
  },

  // ---- Htek provisioning (Extras) ----
  /** Capabilities, defaults and whether Playwright + Chrome/Edge are available. */
  htekInfo: () => request('/htek/info', { timeoutMs: 20000 }),
  /** P237 / P1360 / P1361 defaults read from the PBX this session is logged in to. */
  htekPbxDefaults: () => request('/htek/pbx-defaults', { timeoutMs: 30000 }),
  /** Last credential copy made by the desktop launcher's Windows-wide shortcut. */
  htekHotkeyEvent: () => request('/htek/hotkey-event', { timeoutMs: 12000 }),
  /** Latest task of this session, so the page can be re-opened without losing the run. */
  htekCurrentJob: () => request('/htek/jobs/current', { timeoutMs: 20000 }),
  htekStart: (payload) => request('/htek/jobs', { method: 'POST', body: payload, timeoutMs: 30000 }),
  htekJob: (jobId) => request(`/htek/jobs/${encodeURIComponent(jobId)}`, { timeoutMs: 20000 }),
  htekStop: (jobId) => request(`/htek/jobs/${encodeURIComponent(jobId)}/stop`, { method: 'POST', timeoutMs: 20000 }),
  htekRescan: (jobId, payload) =>
    request(`/htek/jobs/${encodeURIComponent(jobId)}/rescan`, { method: 'POST', body: payload, timeoutMs: 30000 }),
  htekClear: (jobId) => request(`/htek/jobs/${encodeURIComponent(jobId)}/clear`, { method: 'POST', timeoutMs: 20000 }),
  htekDeleteRow: (jobId, ip) =>
    request(`/htek/jobs/${encodeURIComponent(jobId)}/rows/${encodeURIComponent(ip)}`, {
      method: 'DELETE',
      timeoutMs: 20000,
    }),
  htekOpen: (jobId, ip) =>
    request(`/htek/jobs/${encodeURIComponent(jobId)}/open`, { method: 'POST', body: { ip }, timeoutMs: 20000 }),
  htekExportUrl: (jobId) => `/api/htek/jobs/${encodeURIComponent(jobId)}/export.csv`,

  // ---- Operation log (audit) ----
  auditEntries: ({ limit = 200, kind = '', actor = '' } = {}) =>
    request(`/audit/entries?limit=${limit}&kind=${encodeURIComponent(kind)}&actor=${encodeURIComponent(actor)}`, {
      timeoutMs: 20000,
    }),
  auditCsvUrl: (limit = 2000) => `/api/audit/export.csv?limit=${limit}`,
};
