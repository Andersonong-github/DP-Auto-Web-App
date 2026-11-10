/**
 * views/tts.js — Text to Speech page (desktop "AnderOng TTS" ported to the browser).
 *
 * The audio is synthesized by the backend (`/api/tts/synthesize`, edge-tts) because the
 * browser cannot open the Edge TTS websocket itself. The page keeps the desktop
 * workflow — script, language, gender, speed — and adds what the desktop could not do:
 * play the result in the page, choose MP3 or WAV, download it, and see the exact file
 * name that will be uploaded to the PBX as a voice prompt.
 *
 * One engine only (Microsoft Edge neural): it is the only free, keyless service with good
 * Malay + Chinese voices *and* working prosody. The Google Translate backend was removed —
 * it had no rate/volume control and one voice per language.
 *
 * "Tone" is a preset over rate + volume, not a real emotion tag: the free Edge endpoint
 * rejects Azure's `<mstts:express-as>` (every request returns no audio), so the UI does not
 * pretend to offer emotions it cannot deliver.
 */

import { api } from '../api.js';
import { badge, clear, copyText, h, icon, log, toast } from '../ui.js';

const FALLBACK_CATALOG = {
  languages: [
    { language: 'English', genders: ['Female', 'Male'], voices: { Female: 'en-US-AvaNeural', Male: 'en-US-AndrewNeural' } },
    { language: 'Malay', genders: ['Female', 'Male'], voices: { Female: 'ms-MY-YasminNeural', Male: 'ms-MY-OsmanNeural' } },
    { language: 'Chinese', genders: ['Female', 'Male'], voices: { Female: 'zh-CN-XiaoxiaoNeural', Male: 'zh-CN-YunjianNeural' } },
  ],
  defaults: { language: 'Malay', gender: 'Female', rate: 10, tone: 'neutral', format: 'mp3' },
  tones: [
    { id: 'neutral', label: 'Neutral', detail: 'Straight read, no adjustments.', rateOffset: 0, volumeOffset: 0 },
    { id: 'warm', label: 'Warm / friendly', detail: 'A touch slower and softer — a reception greeting.', rateOffset: -8, volumeOffset: -4 },
    { id: 'calm', label: 'Calm / slow', detail: 'Clearly slower and quieter — instructions and after-hours messages.', rateOffset: -20, volumeOffset: -6 },
    { id: 'bright', label: 'Bright / upbeat', detail: 'A little faster and louder — promotions and short announcements.', rateOffset: 12, volumeOffset: 8 },
    { id: 'urgent', label: 'Urgent', detail: 'Fast and loud — time-sensitive notices.', rateOffset: 25, volumeOffset: 14 },
  ],
  formats: [
    { id: 'mp3', label: 'MP3', extension: 'mp3', mediaType: 'audio/mpeg', detail: 'Smallest file; accepted by every PBX upload and browser.' },
    { id: 'wav', label: 'WAV (24 kHz, 16-bit mono)', extension: 'wav', mediaType: 'audio/wav', detail: 'Uncompressed PCM; use when the PBX or an editor wants WAV.' },
  ],
  maxTextChars: 5000,
  minRate: -50,
  maxRate: 50,
  supportsEmotionTag: false,
  emotionNote: 'The free Edge endpoint rejects the Azure emotion tag; use the tone presets instead.',
  samples: {
    English: 'Thank you for calling Boustead Heavy Industries Corporation Berhad. Your call is important to us.',
    Malay: 'Terima kasih kerana menghubungi Boustead Heavy Industries Corporation Berhad.',
    Chinese: '感谢您致电 Boustead Heavy Industries Corporation Berhad。',
  },
};

function toolCard({ title, sub, statusText, statusVariant = '', body, headExtra }) {
  return h(
    'section',
    { class: 'u-card' },
    h(
      'div',
      { class: 'u-card__head' },
      h('div', {}, h('h3', { class: 'u-card__title', text: title }), sub ? h('p', { class: 'u-card__sub', text: sub }) : null),
      headExtra || (statusText ? badge(statusText, statusVariant) : null),
    ),
    h('div', { class: 'u-card__body' }, body),
  );
}

function fmtBytes(value) {
  const bytes = Number(value) || 0;
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
}

export const ttsView = {
  title: 'Text to Speech',
  subtitle: 'Turn a script into an MP3 or WAV voice prompt with Microsoft Edge neural voices',

  mount(root) {
    let catalog = FALLBACK_CATALOG;
    let languages = [];
    let generating = false;

    /* --------------------------------------------------------------- state */
    const state = {
      language: FALLBACK_CATALOG.defaults.language,
      gender: FALLBACK_CATALOG.defaults.gender,
      rate: FALLBACK_CATALOG.defaults.rate,
      tone: FALLBACK_CATALOG.defaults.tone,
      format: FALLBACK_CATALOG.defaults.format,
      result: null, // { url, filename, bytes, voice, tone, format, elapsedMs }
    };

    /* --------------------------------------------------------- tone / format */
    const toneSelect = h(
      'select',
      { class: 'input-plain' },
      FALLBACK_CATALOG.tones.map((tone) => h('option', { value: tone.id }, tone.label)),
    );
    const toneDetail = h('span', { class: 'u-label__hint', text: '' });
    const formatSelect = h(
      'select',
      { class: 'input-plain' },
      FALLBACK_CATALOG.formats.map((format) => h('option', { value: format.id }, format.label)),
    );
    const formatDetail = h('span', { class: 'u-label__hint', text: '' });

    /* ----------------------------------------------------------- script box */
    const scriptArea = h('textarea', {
      class: 'input-plain',
      spellcheck: 'false',
      placeholder: 'Type or paste the script to convert…',
    });
    const counter = h('span', { class: 'tts-counter', text: '0 characters' });
    const sampleButton = h(
      'button',
      { class: 'u-btn u-btn--sm u-btn--ghost', type: 'button', title: 'Insert the sample script for the chosen language' },
      icon('wand', 15),
      'Use sample script',
    );
    const clearButton = h('button', { class: 'u-btn u-btn--sm u-btn--ghost', type: 'button' }, icon('trash', 15), 'Clear');

    /* ---------------------------------------------------- language / gender */
    const languageRow = h('div', { class: 'tts-choice' });
    const genderRow = h('div', { class: 'tts-choice' });

    /* ------------------------------------------------------------- speed */
    const speedValue = h('b', { class: 'tts-speed__value', text: '+10%' });
    const speedSlider = h('input', {
      type: 'range',
      class: 'tts-range',
      min: String(FALLBACK_CATALOG.minRate),
      max: String(FALLBACK_CATALOG.maxRate),
      step: '5',
      value: String(FALLBACK_CATALOG.defaults.rate),
    });
    const speedReset = h('button', { class: 'u-btn u-btn--sm u-btn--ghost', type: 'button', title: 'Back to +10%' }, 'Reset');

    /* ------------------------------------------------------------ output */
    const statusLine = h('div', { class: 'tts-status', text: 'Ready' });
    const resultHost = h('div', { class: 'tts-result' });
    const generateButton = h(
      'button',
      { class: 'u-btn u-btn--primary', type: 'button' },
      h('span', { class: 'u-btn__shine' }),
      icon('play', 16),
      'Generate audio',
    );

    const voicePreview = h('span', { class: 'tts-voiceid', text: '' });

    /* ---------------------------------------------------------- behaviour */
    function updateCounter() {
      const length = scriptArea.value.length;
      counter.textContent = `${length} / ${catalog.maxTextChars} characters`;
      counter.classList.toggle('is-over', length > catalog.maxTextChars);
    }

    function renderLanguages() {
      clear(languageRow);
      languages.forEach((entry) => {
        const active = entry.language === state.language;
        languageRow.appendChild(
          h(
            'button',
            {
              class: `tts-pill ${active ? 'is-active' : ''}`,
              type: 'button',
              on: {
                click: () => {
                  state.language = entry.language;
                  const genders = entry.genders || [];
                  if (!genders.includes(state.gender)) state.gender = genders[0] || 'Female';
                  renderLanguages();
                  renderGenders();
                  renderVoiceId();
                },
              },
            },
            entry.language,
          ),
        );
      });
    }

    function currentLanguageEntry() {
      return languages.find((entry) => entry.language === state.language) || languages[0];
    }

    function renderGenders() {
      clear(genderRow);
      const entry = currentLanguageEntry();
      (entry ? entry.genders : ['Female', 'Male']).forEach((gender) => {
        const active = gender === state.gender;
        genderRow.appendChild(
          h(
            'button',
            {
              class: `tts-pill ${active ? 'is-active' : ''}`,
              type: 'button',
              on: {
                click: () => {
                  state.gender = gender;
                  renderGenders();
                  renderVoiceId();
                },
              },
            },
            gender === 'Female' ? 'Female voice' : 'Male voice',
          ),
        );
      });
    }

    function renderVoiceId() {
      const entry = currentLanguageEntry();
      const voice = entry && entry.voices ? entry.voices[state.gender] : '';
      voicePreview.textContent = voice ? `Voice: ${voice}` : '';
    }

    function currentTone() {
      return catalog.tones.find((tone) => tone.id === state.tone) || catalog.tones[0];
    }

    function currentFormat() {
      return catalog.formats.find((format) => format.id === state.format) || catalog.formats[0];
    }

    function updateToneDetail() {
      const tone = currentTone();
      toneDetail.textContent = tone ? tone.detail : '';
    }

    function updateFormatDetail() {
      const format = currentFormat();
      formatDetail.textContent = format ? format.detail : '';
    }

    function updateSpeed() {
      state.rate = Number(speedSlider.value);
      speedValue.textContent = state.rate >= 0 ? `+${state.rate}%` : `${state.rate}%`;
    }

    function setStatus(text, tone = '') {
      statusLine.textContent = text;
      statusLine.className = `tts-status${tone ? ` tts-status--${tone}` : ''}`;
    }

    function clearResult() {
      if (state.result && state.result.url) URL.revokeObjectURL(state.result.url);
      state.result = null;
      clear(resultHost);
    }

    function renderResult() {
      clear(resultHost);
      if (!state.result) {
        resultHost.appendChild(h('p', { class: 'muted', text: 'No audio yet. Generate MP3 or WAV to preview and download it here.' }));
        return;
      }
      const { url, filename, bytes, voice, elapsedMs } = state.result;
      const audio = h('audio', { class: 'tts-audio', controls: true, src: url, preload: 'metadata' });
      resultHost.append(
        audio,
        h(
          'div',
          { class: 'tts-result__meta' },
          h('span', {}, 'File ', h('b', { class: 'mono', text: filename })),
          h('span', {}, 'Size ', h('b', { text: fmtBytes(bytes) })),
          h('span', {}, 'Voice ', h('b', { class: 'mono', text: voice })),
          h('span', {}, 'Took ', h('b', { text: `${elapsedMs} ms` })),
        ),
        h(
          'div',
          { class: 'row mt-16' },
          h(
            'a',
            { class: 'u-btn u-btn--sm', href: url, download: filename },
            icon('copy', 15),
            `Download ${(state.result.format || 'mp3').toUpperCase()}`,
          ),
          h(
            'button',
            {
              class: 'u-btn u-btn--sm u-btn--ghost',
              type: 'button',
              on: {
                click: async () => {
                  const ok = await copyText(filename);
                  toast(ok ? 'ok' : 'err', ok ? 'File name copied' : 'Copy failed');
                },
              },
            },
            icon('copy', 15),
            'Copy file name',
          ),
        ),
      );
    }

    async function generate() {
      if (generating) return;
      const text = scriptArea.value.trim();
      if (!text) {
        toast('warn', 'Please provide a script to convert.');
        scriptArea.focus();
        return;
      }
      if (text.length > catalog.maxTextChars) {
        toast('warn', `The script is too long (${text.length} / ${catalog.maxTextChars} characters).`);
        return;
      }

      generating = true;
      generateButton.disabled = true;
      clearResult();
      setStatus('Generating audio, please wait…', 'busy');
      const startedAt = Date.now();
      log(
        'info',
        `TTS: generating ${text.length} characters (${state.language}/${state.gender}, tone ${state.tone}, ` +
          `${state.rate >= 0 ? '+' : ''}${state.rate}%, ${state.format.toUpperCase()})`,
      );

      try {
        const result = await api.synthesizeSpeech({
          text,
          language: state.language,
          gender: state.gender,
          rate: state.rate,
          tone: state.tone,
          format: state.format,
        });
        state.result = result;
        renderResult();
        const seconds = ((Date.now() - startedAt) / 1000).toFixed(1);
        setStatus(`Generated ${fmtBytes(result.bytes)} in ${seconds}s`, 'ok');
        toast('ok', `${state.format.toUpperCase()} generated (${fmtBytes(result.bytes)})`);
        log('ok', `TTS: ${result.filename} (${fmtBytes(result.bytes)}, voice ${result.voice})`);
      } catch (error) {
        setStatus('Generation failed', 'err');
        toast('err', error.message);
        log('err', `TTS failed: ${error.message}`);
        resultHost.appendChild(h('div', { class: 'u-alert u-alert--err mt-16' }, icon('alert', 18), h('div', { text: error.message })));
      } finally {
        generating = false;
        generateButton.disabled = false;
      }
    }

    /* ------------------------------------------------------------- wiring */
    scriptArea.addEventListener('input', updateCounter);
    toneSelect.addEventListener('change', () => {
      state.tone = toneSelect.value;
      updateToneDetail();
    });
    formatSelect.addEventListener('change', () => {
      state.format = formatSelect.value;
      updateFormatDetail();
    });
    clearButton.addEventListener('click', () => {
      scriptArea.value = '';
      updateCounter();
      clearResult();
      setStatus('Ready');
      scriptArea.focus();
    });
    sampleButton.addEventListener('click', () => {
      const sample = (catalog.samples && catalog.samples[state.language]) || '';
      if (!sample) {
        toast('warn', 'No sample for this language.');
        return;
      }
      scriptArea.value = sample;
      updateCounter();
    });
    speedSlider.addEventListener('input', updateSpeed);
    speedReset.addEventListener('click', () => {
      speedSlider.value = String(catalog.defaults.rate);
      updateSpeed();
    });
    generateButton.addEventListener('click', generate);

    /* -------------------------------------------------------- assemble page */
    const scriptCard = toolCard({
      title: 'Script',
      sub: 'The text that will be spoken; keep it under the character limit for a single request',
      headExtra: counter,
      body: h(
        'div',
        {},
        scriptArea,
        h('div', { class: 'row mt-16' }, sampleButton, clearButton),
      ),
    });

    const voiceCard = toolCard({
      title: 'Voice parameters',
      sub: 'Edge neural voices with a tone preset and MP3 / WAV output',
      headExtra: voicePreview,
      body: h(
        'div',
        {},
        h('div', { class: 'u-field' }, h('label', { class: 'u-label', text: 'Language' }), languageRow),
        h('div', { class: 'u-field mt-16' }, h('label', { class: 'u-label', text: 'Gender' }), genderRow),
        h(
          'div',
          { class: 'u-field mt-16' },
          h('label', { class: 'u-label' }, 'Tone', toneDetail),
          toneSelect,
        ),
        h(
          'div',
          { class: 'u-field mt-16' },
          h('label', { class: 'u-label' }, 'Output format', formatDetail),
          formatSelect,
        ),
        h(
          'div',
          { class: 'u-field mt-16' },
          h('label', { class: 'u-label' }, 'Speech speed', h('span', { class: 'u-label__hint', text: 'Matches the desktop −50% … +50% slider; the tone adds its own offset' })),
          h(
            'div',
            { class: 'tts-speed' },
            h('span', { class: 'tts-speed__edge', text: 'Slower' }),
            speedSlider,
            h('span', { class: 'tts-speed__edge', text: 'Faster' }),
            speedValue,
            speedReset,
          ),
        ),
      ),
    });

    const outputCard = toolCard({
      title: 'Result',
      sub: 'Preview the audio, then download the MP3 or WAV (or upload it to the PBX as a voice prompt)',
      body: h(
        'div',
        {},
        h('div', { class: 'row tts-actions' }, generateButton, statusLine),
        resultHost,
      ),
    });

    clear(root).append(
      h(
        'div',
        { class: 'page-head' },
        h('div', {}, h('h2', { text: 'Text to Speech' }), h('p', { text: this.subtitle })),
        badge('Extras', 'brand'),
      ),
      h('div', { class: 'grid grid--two' }, scriptCard, h('div', {}, voiceCard, h('div', { class: 'mt-20' }, outputCard))),
    );

    /* ------------------------------------------------------------ bootstrap */
    updateCounter();
    updateSpeed();
    renderLanguages();
    renderGenders();
    renderVoiceId();
    updateToneDetail();
    updateFormatDetail();
    renderResult();

    api
      .ttsVoices()
      .then((data) => {
        if (!data || !Array.isArray(data.languages) || !data.languages.length) return;
        catalog = data;
        languages = data.languages;
        state.language = (data.defaults && data.defaults.language) || languages[0].language;
        state.gender = (data.defaults && data.defaults.gender) || 'Female';

        /* Rebuild the tone dropdown from the server presets. */
        if (Array.isArray(data.tones) && data.tones.length) {
          clear(toneSelect);
          data.tones.forEach((tone) => toneSelect.appendChild(h('option', { value: tone.id }, tone.label)));
          state.tone = (data.defaults && data.defaults.tone) || data.tones[0].id;
          toneSelect.value = state.tone;
        }
        /* Rebuild the format dropdown (MP3 / WAV). */
        if (Array.isArray(data.formats) && data.formats.length) {
          clear(formatSelect);
          data.formats.forEach((format) => formatSelect.appendChild(h('option', { value: format.id }, format.label)));
          state.format = (data.defaults && data.defaults.format) || data.formats[0].id;
          formatSelect.value = state.format;
        }

        speedSlider.min = String(data.minRate ?? -50);
        speedSlider.max = String(data.maxRate ?? 50);
        if (data.defaults && Number.isFinite(Number(data.defaults.rate))) {
          speedSlider.value = String(data.defaults.rate);
        }
        updateCounter();
        updateSpeed();
        renderLanguages();
        renderGenders();
        renderVoiceId();
        updateToneDetail();
        updateFormatDetail();
      })
      .catch((error) => {
        log('warn', `TTS voice catalogue unavailable, using built-in defaults: ${error.message}`);
      });
  },

  unmount() {
    // Nothing to tear down: no timers or event streams on this page.
  },
};
