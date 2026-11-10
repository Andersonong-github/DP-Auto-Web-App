/**
 * theme.js — theme manager (dark / light / follow system).
 */

import { readTheme, writeTheme } from './prefs.js';
import { h, icon } from './ui.js';

let currentSetting = 'dark'; // 'dark' | 'light' | 'system'
let effectiveTheme = 'dark'; // 'dark' | 'light'

function detectSystemTheme() {
  return window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
}

function resolveTheme(setting) {
  if (setting === 'system') return detectSystemTheme();
  return setting === 'light' ? 'light' : 'dark';
}

export function applyTheme(setting) {
  currentSetting = ['dark', 'light', 'system'].includes(setting) ? setting : 'dark';
  writeTheme(currentSetting);
  effectiveTheme = resolveTheme(currentSetting);

  document.documentElement.setAttribute('data-theme', effectiveTheme);
  document.documentElement.setAttribute('data-theme-setting', currentSetting);

  // Update meta color-scheme so browser controls adapt
  const meta = document.querySelector('meta[name="color-scheme"]');
  if (meta) meta.setAttribute('content', effectiveTheme);

  window.dispatchEvent(
    new CustomEvent('dp:theme', {
      detail: { setting: currentSetting, effective: effectiveTheme },
    }),
  );
}

export function getThemeSetting() {
  return currentSetting;
}

export function getEffectiveTheme() {
  return effectiveTheme;
}

export function cycleTheme() {
  const order = ['dark', 'light', 'system'];
  const nextIdx = (order.indexOf(currentSetting) + 1) % order.length;
  const next = order[nextIdx];
  applyTheme(next);
  return next;
}

export function initTheme() {
  const saved = readTheme();
  applyTheme(saved);

  if (window.matchMedia) {
    window.matchMedia('(prefers-color-scheme: light)').addEventListener('change', () => {
      if (currentSetting === 'system') {
        applyTheme('system');
      }
    });
  }
}

export function buildThemeControl() {
  const modes = [
    { key: 'dark', label: 'Dark', icon: 'moon' },
    { key: 'light', label: 'Light', icon: 'sun' },
    { key: 'system', label: 'Auto', icon: 'monitor' },
  ];
  const buttons = new Map();

  const wrap = h(
    'div',
    { class: 'themectl', role: 'group', 'aria-label': 'Theme selector' },
    modes.map((m) => {
      const btn = h(
        'button',
        {
          class: `themectl__btn ${getThemeSetting() === m.key ? 'is-active' : ''}`,
          type: 'button',
          title: `Switch to ${m.label} mode`,
          on: {
            click: () => applyTheme(m.key),
          },
        },
        icon(m.icon, 13),
        h('span', { text: m.label }),
      );
      buttons.set(m.key, btn);
      return btn;
    }),
  );

  window.addEventListener('dp:theme', (event) => {
    const activeKey = event.detail.setting;
    buttons.forEach((btn, key) => {
      btn.classList.toggle('is-active', key === activeKey);
    });
  });

  return wrap;
}
