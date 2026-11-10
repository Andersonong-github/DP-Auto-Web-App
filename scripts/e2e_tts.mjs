/**
 * e2e_tts.mjs — Text to Speech page (Extras → Text to Speech).
 *
 *   node scripts/e2e_tts.mjs http://127.0.0.1:8098 9333
 *
 * The page replaces the desktop "AnderOng TTS" tool. The MP3 is synthesized by the backend
 * (edge-tts), so this suite checks the whole path: catalogue → generate → real playable audio
 * → download link, plus the validation the desktop tool did with message boxes.
 *
 * Requires outbound internet access to speech.platform.bing.com (the Edge voice service).
 */

import { connectCdp, reporter, sleep } from './cdp.mjs';

const [, , base = 'http://127.0.0.1:8098', port = '9333'] = process.argv;

async function main() {
  const cdp = await connectCdp({ port });
  const { check, summary } = reporter();

  try {
    await cdp.goto(`${base}/api/dev/auto-login`, 3000);
    await cdp.goto(`${base}/#/tts`, 3000);

    /* ------------------------------------------------------------ page shell */
    const shell = JSON.parse(
      await cdp.evaluate(`JSON.stringify({
        nav: [...document.querySelectorAll('.nav__item')].map(n => n.textContent.trim()),
        active: document.querySelector('.nav__item.is-active')?.textContent.trim() || '',
        cards: [...document.querySelectorAll('.u-card__title')].map(t => t.textContent.trim()),
        title: document.querySelector('.page-head h2')?.textContent.trim() || ''
      })`),
    );
    check('Text to Speech is in the Extras menu', shell.nav.includes('Text to Speech'), JSON.stringify(shell.nav));
    check('The TTS page is the active route', shell.active.includes('Text to Speech'), shell.active);
    check('Page renders its three cards', ['Script', 'Voice parameters', 'Result'].every((t) => shell.cards.includes(t)), JSON.stringify(shell.cards));

    /* --------------------------------------------------- tone / format dropdowns */
    const controls = JSON.parse(
      await cdp.evaluate(`JSON.stringify({
        selects: [...document.querySelectorAll('select.input-plain')].map(s => ({
          value: s.value,
          options: [...s.options].map(o => ({value: o.value, text: o.text.trim()}))
        })),
        labels: [...document.querySelectorAll('.u-label')].map(l => l.textContent.trim()),
        hints: [...document.querySelectorAll('.u-label__hint')].map(h => h.textContent.trim()),
        generate: document.querySelector('.u-btn--primary')?.textContent.trim() || ''
      })`),
    );
    check('Three dropdowns render (tone, format, and no engine selector)', controls.selects.length === 2, `${controls.selects.length} selects`);

    const toneSelect = controls.selects.find((s) => s.options.some((o) => o.value === 'neutral'));
    check('Tone dropdown is present', Boolean(toneSelect));
    check(
      'Tone offers the five presets',
      toneSelect && ['neutral', 'warm', 'calm', 'bright', 'urgent'].every((id) => toneSelect.options.some((o) => o.value === id)),
      JSON.stringify(toneSelect?.options),
    );
    check('Tone defaults to neutral', toneSelect?.value === 'neutral', toneSelect?.value);
    check(
      'Tone hint explains what the preset does',
      controls.hints.some((h) => /slower|softer|louder|faster|no adjustments/i.test(h)),
      JSON.stringify(controls.hints),
    );

    const formatSelect = controls.selects.find((s) => s.options.some((o) => o.value === 'wav'));
    check('Output format dropdown is present', Boolean(formatSelect));
    check(
      'Format offers MP3 and WAV',
      formatSelect && formatSelect.options.some((o) => o.value === 'mp3') && formatSelect.options.some((o) => o.value === 'wav'),
      JSON.stringify(formatSelect?.options),
    );
    check('Format defaults to MP3', formatSelect?.value === 'mp3', formatSelect?.value);
    check('Generate button says "Generate audio"', /Generate audio/i.test(controls.generate), controls.generate);

    /* ------------------------------------ switch tone + WAV, then generate */
    await cdp.evaluate(`(() => {
      const selects = [...document.querySelectorAll('select.input-plain')];
      const tone = selects.find(s => [...s.options].some(o => o.value === 'calm'));
      tone.value = 'calm';
      tone.dispatchEvent(new Event('change', { bubbles: true }));
      const fmt = selects.find(s => [...s.options].some(o => o.value === 'wav'));
      fmt.value = 'wav';
      fmt.dispatchEvent(new Event('change', { bubbles: true }));
      const area = document.querySelector('textarea.input-plain');
      area.value = 'Terima kasih kerana menghubungi Boustead Heavy Industries Corporation Berhad.';
      area.dispatchEvent(new Event('input', { bubbles: true }));
      return true;
    })()`);
    await sleep(400);

    const toneHint = await cdp.evaluate(
      `[...document.querySelectorAll('.u-label__hint')].map(h => h.textContent.trim()).find(t => /slower|quieter/i.test(t)) || ''`,
    );
    check('Calm tone hint is shown', /slower|quieter/i.test(toneHint), toneHint);

    await cdp.evaluate(`document.querySelector('.u-btn--primary').click()`);
    const wavReady = await cdp.waitFor(
      `(() => { const a = document.querySelector('a[download]'); return !!a && /\\.wav$/.test(a.getAttribute('download') || ''); })()`,
      { timeoutMs: 120000, intervalMs: 500 },
    );
    check('WAV output is generated', Boolean(wavReady));

    // The page's blob: URL is blocked for fetch() by the CSP (connect-src 'self'), so verify
    // the container bytes through the API directly — same request the page just made.
    const wavBytes = JSON.parse(
      await cdp.evaluate(`(async () => {
        const r = await fetch('/api/tts/synthesize', {
          method: 'POST', credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text: 'Terima kasih kerana menghubungi Boustead.', language: 'Malay', gender: 'Female', rate: 10, tone: 'calm', format: 'wav' })
        });
        const buf = new Uint8Array(await r.arrayBuffer());
        const dv = new DataView(buf.buffer);
        const txt = (s, e) => String.fromCharCode(...buf.slice(s, e));
        return JSON.stringify({
          status: r.status, size: buf.length,
          contentType: r.headers.get('Content-Type'),
          filename: r.headers.get('X-TTS-Filename'),
          tone: r.headers.get('X-TTS-Tone'),
          format: r.headers.get('X-TTS-Format'),
          riff: txt(0, 4), wave: txt(8, 12),
          audioFormat: dv.getUint16(20, true),
          channels: dv.getUint16(22, true),
          sampleRate: dv.getUint32(24, true),
          bitsPerSample: dv.getUint16(34, true)
        });
      })()`),
    );
    check('WAV API returns 200 audio/wav', wavBytes.status === 200 && wavBytes.contentType === 'audio/wav', JSON.stringify(wavBytes));
    check('WAV bytes really are RIFF/WAVE', wavBytes.riff === 'RIFF' && wavBytes.wave === 'WAVE', `${wavBytes.riff}/${wavBytes.wave}`);
    check(
      'WAV is 24 kHz / 16-bit / mono PCM',
      wavBytes.audioFormat === 1 && wavBytes.channels === 1 && wavBytes.sampleRate === 24000 && wavBytes.bitsPerSample === 16,
      JSON.stringify({ fmt: wavBytes.audioFormat, ch: wavBytes.channels, rate: wavBytes.sampleRate, bits: wavBytes.bitsPerSample }),
    );
    check('WAV file name carries the calm tone tag', /^tts_malay_female_calm_.*\.wav$/.test(wavBytes.filename), wavBytes.filename);

    const wavInfo = JSON.parse(
      await cdp.evaluate(`(async () => {
        const el = document.querySelector('.tts-audio');
        if (!el) return JSON.stringify({ ok: false });
        if (el.readyState < 1) {
          await new Promise((res) => { el.addEventListener('loadedmetadata', res, {once: true}); setTimeout(res, 5000); });
        }
        return JSON.stringify({
          ok: true,
          readyState: el.readyState,
          duration: el.duration,
          download: document.querySelector('a[download]')?.getAttribute('download') || '',
          meta: document.querySelector('.tts-result__meta')?.textContent.replace(/\\s+/g, ' ').trim() || ''
        });
      })()`),
    );
    check('WAV audio is playable', wavInfo.ok && wavInfo.readyState >= 1 && wavInfo.duration > 1, JSON.stringify(wavInfo));
    check('Download button says WAV', /Download WAV/i.test(await cdp.evaluate(`document.querySelector('a[download]')?.textContent.trim() || ''`)));
    check('Result meta mentions the file name', /\.wav/.test(wavInfo.meta), wavInfo.meta);

    /* ------------------------------------- switch back to MP3 for the rest */
    await cdp.evaluate(`(() => {
      const fmt = [...document.querySelectorAll('select.input-plain')].find(s => [...s.options].some(o => o.value === 'wav'));
      fmt.value = 'mp3';
      fmt.dispatchEvent(new Event('change', { bubbles: true }));
      return true;
    })()`);
    await sleep(300);

    /* ------------------------------------------------------------ catalogue */
    const catalogue = JSON.parse(
      await cdp.evaluate(`JSON.stringify({
        languages: [...document.querySelectorAll('.tts-choice')][0]?.textContent.trim() || '',
        genders: [...document.querySelectorAll('.tts-choice')][1]?.textContent.trim() || '',
        voiceId: document.querySelector('.tts-voiceid')?.textContent.trim() || '',
        speed: document.querySelector('.tts-speed__value')?.textContent.trim() || '',
        slider: (() => { const s = document.querySelector('.tts-range'); return s ? {min: s.min, max: s.max, value: s.value} : null; })()
      })`),
    );
    check(
      'Language pills match the desktop tool (English / Malay / Chinese)',
      ['English', 'Malay', 'Chinese'].every((l) => catalogue.languages.includes(l)),
      catalogue.languages,
    );
    check(
      'Gender pills are Female / Male voice',
      catalogue.genders.includes('Female') && catalogue.genders.includes('Male'),
      catalogue.genders,
    );
    check('Default voice id is shown', /Neural/.test(catalogue.voiceId), catalogue.voiceId);
    check(
      'Speed slider covers the desktop −50% … +50% range',
      catalogue.slider && catalogue.slider.min === '-50' && catalogue.slider.max === '50',
      JSON.stringify(catalogue.slider),
    );
    check('Speed starts at +10% like the desktop', catalogue.speed === '+10%', catalogue.speed);

    /* ------------------------------------------------ validation: empty script */
    // Clear any audio from the previous step first: the guard must be about the *empty*
    // script, not about whatever a previous generation left on the page.
    await cdp.evaluate(`(() => {
      [...document.querySelectorAll('button')].find(b => b.textContent.trim() === 'Clear').click();
      [...document.querySelectorAll('.u-toast')].forEach(t => t.remove());
      return true;
    })()`);
    await sleep(400);
    await cdp.evaluate(`document.querySelector('.u-btn--primary').click()`);
    await sleep(900);
    const emptyGuard = JSON.parse(
      await cdp.evaluate(`JSON.stringify({
        toasts: [...document.querySelectorAll('.u-toast')].map(t => t.textContent.trim()),
        audio: !!document.querySelector('.tts-audio')
      })`),
    );
    check(
      'Empty script is rejected (no request made)',
      emptyGuard.toasts.some((t) => /provide a script/i.test(t)) && emptyGuard.audio === false,
      JSON.stringify(emptyGuard.toasts),
    );

    /* --------------------------------------------------- switch to English/male */
    await cdp.evaluate(`(() => {
      const groups = [...document.querySelectorAll('.tts-choice')];
      [...groups[0].querySelectorAll('.tts-pill')].find(b => b.textContent.trim() === 'English').click();
      return true;
    })()`);
    await sleep(300);
    await cdp.evaluate(`(() => {
      const groups = [...document.querySelectorAll('.tts-choice')];
      [...groups[1].querySelectorAll('.tts-pill')].find(b => b.textContent.trim().startsWith('Male')).click();
      return true;
    })()`);
    await sleep(300);
    const switched = await cdp.evaluate(`document.querySelector('.tts-voiceid')?.textContent.trim() || ''`);
    check('Switching language + gender updates the voice id', switched.includes('en-US-AndrewNeural'), switched);

    /* --------------------------------------------------------- generate audio */
    await cdp.evaluate(`(() => {
      const area = document.querySelector('textarea.input-plain');
      area.value = 'Thank you for calling Boustead Heavy Industries Corporation Berhad.';
      area.dispatchEvent(new Event('input', { bubbles: true }));
      return true;
    })()`);
    await sleep(300);
    const counted = await cdp.evaluate(`document.querySelector('.tts-counter')?.textContent.trim() || ''`);
    check('Character counter tracks the script', /characters/.test(counted), counted);

    await cdp.evaluate(`document.querySelector('.u-btn--primary').click()`);

    const generated = await cdp.waitFor(`!!document.querySelector('.tts-audio')`, { timeoutMs: 120000, intervalMs: 500 });
    check('MP3 is generated', Boolean(generated));

    const audio = JSON.parse(
      await cdp.evaluate(`(async () => {
        const el = document.querySelector('.tts-audio');
        if (!el) return JSON.stringify({ ok: false });
        if (el.readyState < 1) {
          await new Promise((res) => { el.addEventListener('loadedmetadata', res, {once: true}); setTimeout(res, 5000); });
        }
        return JSON.stringify({
          ok: true,
          src: el.src.slice(0, 5),
          duration: el.duration,
          readyState: el.readyState,
          error: el.error ? el.error.code : null,
          meta: document.querySelector('.tts-result__meta')?.textContent.replace(/\\s+/g, ' ').trim() || '',
          download: document.querySelector('a[download]')?.getAttribute('download') || '',
          status: document.querySelector('.tts-status')?.textContent.trim() || ''
        });
      })()`),
    );
    check('Audio is a blob URL served by the page', audio.src === 'blob:', audio.src);
    check('Audio metadata loads (playable MP3)', audio.ok && audio.readyState >= 1 && audio.error === null, JSON.stringify(audio));
    check('Audio has a real duration', Number(audio.duration) > 1, String(audio.duration));
    check('Result shows the voice and size', /Voice en-US-AndrewNeural/.test(audio.meta) && /Size/.test(audio.meta), audio.meta);
    check('Download link carries a sensible .mp3 name', /^tts_english_male_[a-z]+_.*\.mp3$/.test(audio.download), audio.download);
    check('Status line reports success', /Generated/i.test(audio.status), audio.status);

    /* ------------------------------------------------------- Chinese / speed 0 */
    await cdp.evaluate(`(() => {
      const groups = [...document.querySelectorAll('.tts-choice')];
      [...groups[0].querySelectorAll('.tts-pill')].find(b => b.textContent.trim() === 'Chinese').click();
      const area = document.querySelector('textarea.input-plain');
      area.value = '感谢您致电。';
      area.dispatchEvent(new Event('input', { bubbles: true }));
      return true;
    })()`);
    await sleep(300);
    const zhVoice = await cdp.evaluate(`document.querySelector('.tts-voiceid')?.textContent.trim() || ''`);
    check('Chinese voice resolves to a zh-CN neural voice', zhVoice.includes('zh-CN-'), zhVoice);

    await cdp.evaluate(`document.querySelector('.u-btn--primary').click()`);
    // The status line already says "Generated" from the English run, so wait for the
    // download name to change to the Chinese one instead of for the status text.
    const zhDone = await cdp.waitFor(
      `(() => {
         const a = document.querySelector('a[download]');
         return !!a && /^tts_chinese_/.test(a.getAttribute('download') || '');
       })()`,
      { timeoutMs: 120000, intervalMs: 500 },
    );
    check('Chinese script also generates audio', Boolean(zhDone));

    const zhAudio = JSON.parse(
      await cdp.evaluate(`JSON.stringify((() => {
        const el = document.querySelector('.tts-audio');
        return { readyState: el?.readyState ?? 0, download: document.querySelector('a[download]')?.getAttribute('download') || '' };
      })())`),
    );    check('Chinese audio is playable too', zhAudio.readyState >= 1, JSON.stringify(zhAudio));
    check('Chinese file name is prefixed correctly', /^tts_chinese_/.test(zhAudio.download), zhAudio.download);

    /* -------------------------------------------------------------- speed UI */
    await cdp.evaluate(`(() => {
      const s = document.querySelector('.tts-range');
      s.value = '-30';
      s.dispatchEvent(new Event('input', { bubbles: true }));
      return true;
    })()`);
    const slower = await cdp.evaluate(`document.querySelector('.tts-speed__value')?.textContent.trim() || ''`);
    check('Speed label reflects a negative value', slower === '-30%', slower);

    await cdp.evaluate(`[...document.querySelectorAll('button')].find(b => b.textContent.trim() === 'Reset').click()`);
    await sleep(300);
    const reset = await cdp.evaluate(`document.querySelector('.tts-speed__value')?.textContent.trim() || ''`);
    check('Reset restores +10%', reset === '+10%', reset);

    check('No JS console errors', cdp.consoleErrors.length === 0, `${cdp.consoleErrors.length} errors`);

    await cdp.screenshot('.artifacts/tts.png');
  } finally {
    cdp.close();
  }

  process.exit(summary());
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
