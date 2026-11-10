/**
 * views/login.js — Login page.
 *
 * Sign in with a Deltapath PBX account: the frontend passes the address, username
 * and password to the backend, the backend opens a session with the PBX, and the
 * browser only receives an HttpOnly session cookie.
 */

import { api } from '../api.js';
import { state, setState } from '../store.js';
import { clear, h, icon, log, toast } from '../ui.js';
import { readPrefs, writePrefs } from '../prefs.js';
import { buildThemeControl } from '../theme.js';

/* uiverse.io by KhelVers — honest-lionfish-67 (light rays decoration, MIT) */
const RAYS = `
<svg viewBox="0 0 299 152" xmlns="http://www.w3.org/2000/svg" aria-hidden="true" focusable="false">
  <path fill="url(#dp-rays-gradient)" d="M149.5 152H133.42L9.53674e-07 4.70132e-06H149.5L299 4.70132e-06L165.58 152H149.5Z"></path>
  <defs>
    <linearGradient id="dp-rays-gradient" gradientUnits="userSpaceOnUse" y2="12.1981" x2="150.12" y1="152" x1="149.5">
      <stop stop-color="#00E0FF"></stop>
      <stop stop-opacity="0" stop-color="#65EDFF" offset="1"></stop>
    </linearGradient>
  </defs>
</svg>`;

export function mountLogin(root, { onAuthenticated }) {
  const config = state.config || {};
  const prefs = readPrefs();
  let proto = prefs.proto;
  let passwordVisible = false;

  const hostInput = h('input', {
    class: 'u-input',
    type: 'text',
    name: 'host',
    placeholder: 'suc.example.com or 192.168.1.10',
    autocomplete: 'off',
    spellcheck: 'false',
    value: prefs.host || config.defaultBaseUrl || '',
    'aria-label': 'PBX server address',
  });
  const userInput = h('input', {
    class: 'u-input',
    type: 'text',
    name: 'username',
    placeholder: 'PBX username',
    autocomplete: 'username',
    spellcheck: 'false',
    value: prefs.username || '',
    'aria-label': 'PBX username',
  });
  const passInput = h('input', {
    class: 'u-input',
    type: 'password',
    name: 'password',
    placeholder: 'PBX password',
    autocomplete: 'current-password',
    'aria-label': 'PBX password',
  });

  const hostField = h('div', { class: 'u-inputForm' });
  const userField = h('div', { class: 'u-inputForm' }, icon('user', 20), userInput);
  const passField = h('div', { class: 'u-inputForm' }, icon('lock', 20), passInput);

  const protoButton = h(
    'button',
    {
      class: 'u-proto',
      type: 'button',
      title: 'Switch http / https',
      on: {
        click: () => {
          proto = proto === 'https' ? 'http' : 'https';
          protoButton.textContent = `${proto}://`;
          log('info', `Protocol switched to ${proto}://`);
        },
      },
    },
    `${proto}://`,
  );
  hostField.append(protoButton, hostInput);

  const eyeButton = h(
    'button',
    {
      class: 'u-input-action',
      type: 'button',
      title: 'Show / hide password',
      'aria-label': 'Show or hide password',
      on: {
        click: () => {
          passwordVisible = !passwordVisible;
          passInput.type = passwordVisible ? 'text' : 'password';
          clear(eyeButton).appendChild(icon(passwordVisible ? 'eyeOff' : 'eye', 18));
        },
      },
    },
    icon('eye', 18),
  );
  passField.appendChild(eyeButton);

  const tlsToggle = h('input', { type: 'checkbox', checked: prefs.tlsVerify });
  const rememberToggle = h('input', { type: 'checkbox', checked: prefs.remember });

  const alertSlot = h('div');
  const submitLabel = h('span', { text: 'Sign in and start session' });
  const submitButton = h(
    'button',
    { class: 'u-btn u-btn--primary u-btn--block', type: 'submit' },
    h('span', { class: 'u-btn__shine' }),
    submitLabel,
  );

  const form = h(
    'form',
    { class: 'u-card login-card', novalidate: true, on: { submit: onSubmit } },
    h(
      'div',
      { class: 'login-card__brand' },
      h('div', { class: 'login-card__logo' }, h('img', { class: 'login-card__logo-img', src: '/logo.png', alt: config.appName || 'Anderson Deltapath-Automation', width: 25, height: 25 })),
      h(
        'div',
        {},
        h('h1', { class: 'login-card__name', text: config.appName || 'Anderson Deltapath-Automation' }),
        h('p', { class: 'login-card__tag', text: 'PBX bulk configuration · browser edition' }),
      ),
    ),
    alertSlot,
    h(
      'div',
      { class: 'u-form' },
      h('div', { class: 'u-field' }, h('label', { class: 'u-label', text: 'PBX server address' }), hostField),
      h('div', { class: 'u-field' }, h('label', { class: 'u-label', text: 'Username' }), userField),
      h('div', { class: 'u-field' }, h('label', { class: 'u-label', text: 'Password' }), passField),
      h(
        'div',
        { class: 'login-card__options' },
        h('label', { class: 'u-switch' }, tlsToggle, h('span', { class: 'u-switch__track' }), 'Ignore certificate validation'),
        h('label', { class: 'u-switch' }, rememberToggle, h('span', { class: 'u-switch__track' }), 'Remember address'),
      ),
      submitButton,
    ),
    h(
      'p',
      { class: 'login-card__foot' },
      'Credentials are only used to start a session with the PBX on the server; the browser never stores the password.',
      h('br'),
      h('strong', { text: `Session expires after ${config.sessionIdleMinutes || 60} minutes idle` }),
    ),
  );

  const themeBar = h(
    'div',
    { style: { position: 'absolute', top: '16px', right: '16px', zIndex: 30 } },
    buildThemeControl(),
  );

  const stage = h(
    'div',
    { class: 'login-stage' },
    themeBar,
    h('div', { class: 'login-stage__aura' }),
    h('div', { class: 'login-stage__grid' }),
    h(
      'div',
      { class: 'login-stack' },
      form,
      h('div', { class: 'u-rays login-rays', html: RAYS }),
    ),
  );

  clear(root).appendChild(stage);
  hostInput.focus();

  function setBusy(busy) {
    submitButton.disabled = busy;
    [hostInput, userInput, passInput, protoButton].forEach((el) => {
      el.disabled = busy;
    });
    clear(submitButton);
    submitButton.appendChild(h('span', { class: 'u-btn__shine' }));
    if (busy) {
      submitButton.appendChild(h('span', { class: 'u-loader u-loader--ring' }));
      submitButton.appendChild(h('span', { text: 'Starting session with PBX…' }));
    } else {
      submitButton.append(submitLabel);
    }
  }

  function showError(message, raw) {
    clear(alertSlot);
    alertSlot.appendChild(
      h(
        'div',
        { class: 'u-alert u-alert--err mt-16' },
        icon('alert', 18),
        h('div', {}, h('div', { text: message }), raw ? h('div', { class: 'u-alert__raw', text: raw }) : null),
      ),
    );
  }

  function normaliseHost(value) {
    let host = (value || '').trim();
    if (host.includes('://')) {
      const [scheme, ...rest] = host.split('://');
      if (scheme === 'http' || scheme === 'https') {
        proto = scheme;
        protoButton.textContent = `${proto}://`;
      }
      host = rest.join('://');
    }
    return host.replace(/\/+$/, '');
  }

  async function onSubmit(event) {
    event.preventDefault();
    clear(alertSlot);

    const host = normaliseHost(hostInput.value);
    const username = userInput.value.trim();
    const password = passInput.value;
    const invalid = [
      [!host, hostField, hostInput],
      [!username, userField, userInput],
      [!password, passField, passInput],
    ].filter(([isEmpty]) => isEmpty);

    [hostField, userField, passField].forEach((field) => field.classList.remove('is-invalid'));
    if (invalid.length) {
      invalid.forEach(([, field]) => field.classList.add('is-invalid'));
      const message = 'Enter the PBX address, username and password.';
      showError(message);
      toast('warn', message);
      invalid[0][2].focus();
      return;
    }

    setBusy(true);
    log('info', `Signing in as ${username}@${proto}://${host} …`);
    const started = performance.now();

    try {
      const session = await api.login({
        base_url: `${proto}://${host}`,
        username,
        password,
        tls_verify: tlsToggle.checked,
      });
      const elapsed = Math.round(performance.now() - started);
      setState({ session });
      writePrefs({
        host,
        username,
        proto,
        tlsVerify: tlsToggle.checked,
        remember: rememberToggle.checked,
      });
      log('ok', `Signed in: ${session.baseUrl} (mode ${session.loginMode}, ${elapsed} ms)`);
      toast('ok', `Connected to ${session.baseUrl}`);
      onAuthenticated();
    } catch (error) {
      setBusy(false);
      showError(error.message || 'Sign-in failed.', error.raw || '');
      log('err', `Sign-in failed: ${error.message}${error.raw ? ` — ${error.raw}` : ''}`);
      toast('err', error.message || 'Sign-in failed');
      passInput.select();
    }
  }

  try {
    window.localStorage.removeItem('dp.web.password');
  } catch {
    /* ignore */
  }
}
