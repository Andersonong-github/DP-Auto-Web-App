/**
 * e2e_login.mjs — drives a real browser over CDP to verify the login gate and login flow.
 *
 *   1) Start Chrome with a debugging port:
 *      chrome.exe --headless --remote-debugging-port=9333 --user-data-dir=%TEMP%\dpchrome\e2e about:blank
 *   2) Run:
 *      node scripts/e2e_login.mjs http://127.0.0.1:8098 9333
 *
 * Requires Node 22+ (uses the global WebSocket). Local verification only; not part of deployment.
 */

const [, , base = 'http://127.0.0.1:8098', port = '9333'] = process.argv;
const USERNAME = process.env.DP_E2E_USER || 'demo';
const PASSWORD = process.env.DP_E2E_PASS || 'demo';
const HOST = process.env.DP_E2E_HOST || 'pbx.demo.local';

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

class Cdp {
  constructor(ws) {
    this.ws = ws;
    this.seq = 0;
    this.pending = new Map();
    this.consoleErrors = [];
    ws.addEventListener('message', (event) => {
      const message = JSON.parse(event.data);
      if (message.id && this.pending.has(message.id)) {
        const { resolve, reject } = this.pending.get(message.id);
        this.pending.delete(message.id);
        if (message.error) reject(new Error(JSON.stringify(message.error)));
        else resolve(message.result);
        return;
      }
      if (message.method === 'Runtime.exceptionThrown') {
        this.consoleErrors.push(message.params.exceptionDetails?.exception?.description || 'exception');
      }
      if (message.method === 'Runtime.consoleAPICalled' && message.params.type === 'error') {
        this.consoleErrors.push(message.params.args.map((arg) => arg.value ?? arg.description).join(' '));
      }
    });
  }

  send(method, params = {}) {
    const id = ++this.seq;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }
}

const results = [];
function check(name, ok, detail = '') {
  results.push({ name, ok, detail });
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? ` — ${detail}` : ''}`);
}

async function main() {
  const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  const page = targets.find((target) => target.type === 'page');
  if (!page) throw new Error('no page target available; make sure Chrome was started with --remote-debugging-port');

  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    ws.addEventListener('open', resolve, { once: true });
    ws.addEventListener('error', reject, { once: true });
  });

  const cdp = new Cdp(ws);
  await cdp.send('Page.enable');
  await cdp.send('Runtime.enable');

  const evaluate = async (expression) => {
    const result = await cdp.send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
    if (result.exceptionDetails) {
      throw new Error(result.exceptionDetails.exception?.description || 'in-page exception');
    }
    return result.result.value;
  };
  const goto = async (url, wait = 2600) => {
    await cdp.send('Page.navigate', { url });
    await sleep(wait);
  };

  try {
  /* 1. Visit a protected route while logged out */
  await goto(`${base}/#/dashboard`);
  const gate = await evaluate(`JSON.stringify({
    login: !!document.querySelector('.login-stage'),
    shell: !!document.querySelector('.shell'),
    hash: location.hash,
    nav: document.querySelectorAll('.nav__item').length
  })`);
  const gateInfo = JSON.parse(gate);
  check('login page shown when logged out', gateInfo.login === true);
  check('app shell not rendered when logged out', gateInfo.shell === false);
  check('no nav items when logged out', gateInfo.nav === 0);

  /* 2. The server API is blocked as well */
  const probeStatus = await evaluate(`fetch('/api/pbx/probe').then((r) => r.status)`);
  check('/api/pbx/probe returns 401 when logged out', probeStatus === 401, `status=${probeStatus}`);

  /* 3. Fill in and submit the login form */
  await evaluate(`(() => {
    const set = (name, value) => {
      const el = document.querySelector('input[name="' + name + '"]');
      el.value = value;
      el.dispatchEvent(new Event('input', { bubbles: true }));
    };
    set('host', ${JSON.stringify(HOST)});
    set('username', ${JSON.stringify(USERNAME)});
    set('password', ${JSON.stringify(PASSWORD)});
    document.querySelector('form.login-card').requestSubmit();
    return true;
  })()`);
  await sleep(3200);

  const afterLogin = JSON.parse(
    await evaluate(`JSON.stringify({
      shell: !!document.querySelector('.shell'),
      login: !!document.querySelector('.login-stage'),
      hash: location.hash,
      user: document.querySelector('.sidebar__user-name')?.textContent || '',
      host: document.querySelector('.sidebar__user-host')?.textContent || '',
      pill: document.querySelector('.conn-pill')?.textContent || '',
      nav: document.querySelectorAll('.nav__item').length,
      title: document.querySelector('.topbar__title')?.textContent || '',
      tokenSaved: (document.querySelector('#loglines')?.textContent || '').includes('Signed in'),
      storedPassword: Object.keys(localStorage).some((k) => k.toLowerCase().includes('pass'))
    })`),
  );
  check('app shell rendered after login', afterLogin.shell === true);
  check('login page gone after login', afterLogin.login === false);
  check('redirected to dashboard after login', afterLogin.hash === '#/dashboard', afterLogin.hash);
  check('sidebar shows the logged-in user', afterLogin.user === USERNAME, afterLogin.user);
  check('sidebar shows the PBX host', afterLogin.host === HOST, afterLogin.host);
  check('all nav items present', afterLogin.nav === 9, `${afterLogin.nav} items`);
  check('log console records the successful login', afterLogin.tokenSaved === true);
  check('no password stored locally', afterLogin.storedPassword === false);

  /* 3b. Shell: the sidebar scrolls on its own and the run log can be resized */
  const shellInfo = JSON.parse(
    await evaluate(`JSON.stringify((() => {
      const scroll = document.querySelector('.sidebar__scroll');
      scroll.scrollTop = scroll.scrollHeight;
      const last = [...document.querySelectorAll('.nav__item')].pop();
      const signOut = [...document.querySelectorAll('button')].find((b) => b.textContent.includes('Sign out'));
      return {
        hasScroll: !!scroll,
        scrollable: scroll.scrollHeight > scroll.clientHeight,
        flagged: document.querySelector('.sidebar').classList.contains('is-scrollable'),
        lastVisible: last.getBoundingClientRect().bottom <= window.innerHeight + 1,
        signOutVisible: !!signOut && signOut.getBoundingClientRect().bottom <= window.innerHeight + 1,
        dock: !!document.querySelector('.logdock__resize'),
        height: document.querySelector('.logdock')?.style.getPropertyValue('--log-height') || ''
      };
    })())`),
  );
  check('sidebar has its own scroll area', shellInfo.hasScroll === true);
  check('the menu scrolls and reaches the last item', shellInfo.lastVisible === true);
  check(
    'an overflowing menu is flagged scrollable (shows the hint)',
    shellInfo.scrollable === false || shellInfo.flagged === true,
    `scrollable=${shellInfo.scrollable} flagged=${shellInfo.flagged}`,
  );
  check('sign out stays pinned at the bottom', shellInfo.signOutVisible === true, `viewport=${(await evaluate('window.innerHeight'))}px`);
  check('run-log resize handle present', shellInfo.dock === true, `--log-height: ${shellInfo.height}`);

  // Zoom in through the real Ctrl+wheel path, then check the menu bottom is still reachable.
  await evaluate(`(() => {
    for (let i = 0; i < 12; i += 1) {
      document.dispatchEvent(new WheelEvent('wheel', { deltaY: -100, ctrlKey: true, cancelable: true, bubbles: true }));
    }
    return true;
  })()`);
  const zoomed = JSON.parse(
    await evaluate(`JSON.stringify((() => {
      const scroll = document.querySelector('.sidebar__scroll');
      const sidebar = document.querySelector('.sidebar');
      scroll.scrollTop = scroll.scrollHeight;
      const last = [...document.querySelectorAll('.nav__item')].pop();
      return {
        zoom: parseFloat(document.documentElement.style.getPropertyValue('--dp-zoom') || '1'),
        overflow: scroll.scrollHeight > scroll.clientHeight,
        lastVisible: last.getBoundingClientRect().bottom <= window.innerHeight + 1,
        sidebarH: Math.round(sidebar.getBoundingClientRect().height)
      };
    })())`),
  );
  check('Ctrl+wheel zoom reaches 160%', zoomed.zoom > 1.5, `${zoomed.zoom}x`);
  check(
    'zoomed sidebar is scrollable and the last item is reachable',
    zoomed.overflow === true && zoomed.lastVisible === true,
    `sidebar=${zoomed.sidebarH}px`,
  );
  await evaluate(`(() => {
    for (let i = 0; i < 12; i += 1) {
      document.dispatchEvent(new WheelEvent('wheel', { deltaY: 100, ctrlKey: true, cancelable: true, bubbles: true }));
    }
    return true;
  })()`);

  const logDrag = JSON.parse(
    await evaluate(`JSON.stringify((() => {
      const dock = document.querySelector('.logdock');
      const handle = document.querySelector('.logdock__resize');
      const read = () => Math.round(parseFloat(getComputedStyle(dock).getPropertyValue('--log-height')) || 0);
      const start = read();
      const top = handle.getBoundingClientRect().top;
      const send = (type, y) => handle.dispatchEvent(new PointerEvent(type, { clientY: y, bubbles: true, pointerId: 1, isPrimary: true }));

      // drag down -> shorter
      send('pointerdown', top);
      send('pointermove', top + 90);
      send('pointerup', top + 90);
      const shrunk = read();
      const storedAfterShrink = window.localStorage.getItem('dp.web.logHeight');

      // drag up -> taller
      send('pointerdown', top + 90);
      send('pointermove', top - 60);
      send('pointerup', top - 60);
      const grown = read();

      // double-click -> back to the default (clamped to the viewport)
      handle.dispatchEvent(new MouseEvent('dblclick', { bubbles: true }));
      return { start, shrunk, grown, storedAfterShrink, reset: read(), max: Math.max(90, Math.round(window.innerHeight / (parseFloat(document.documentElement.style.getPropertyValue('--dp-zoom')) || 1)) - 190) };
    })())`),
  );
  check('dragging down makes the run log shorter', logDrag.shrunk < logDrag.start, `${logDrag.start} -> ${logDrag.shrunk}`);
  check('dragging up makes the run log taller', logDrag.grown > logDrag.shrunk, `${logDrag.shrunk} -> ${logDrag.grown}`);
  check('run-log height is persisted', String(logDrag.storedAfterShrink) === String(logDrag.shrunk), `stored=${logDrag.storedAfterShrink}`);
  check('double-click resets to the default height', Math.round(logDrag.reset) === Math.min(246, logDrag.max), `${logDrag.reset}px (clamp ${logDrag.max}px)`);

  /* 3d. The explicit menu scroll control works, and the panel fits a phone viewport */
  const menuButton = JSON.parse(
    await evaluate(`JSON.stringify((() => {
      const button = document.querySelector('.sidebar__scrollbtn');
      const node = document.querySelector('.sidebar__scroll');
      if (!button) return { present: false };
      node.scrollTop = 0;
      const visible = getComputedStyle(button).display !== 'none';
      button.click();
      return { present: true, visible, label: button.textContent.trim() };
    })())`),
  );
  check(
    'menu scroll control is available when the menu overflows',
    menuButton.present === true && menuButton.visible === true,
    menuButton.label,
  );
  await sleep(700);
  const afterClick = await evaluate(`Math.round(document.querySelector('.sidebar__scroll').scrollTop)`);
  check('clicking it scrolls the menu down', afterClick > 0, `scrollTop=${afterClick}px`);

  await cdp.send('Emulation.setDeviceMetricsOverride', { width: 390, height: 720, deviceScaleFactor: 1, mobile: true });
  await sleep(600);
  const phone = JSON.parse(
    await evaluate(`JSON.stringify((() => {
      const sidebar = document.querySelector('.sidebar');
      const node = sidebar.querySelector('.sidebar__scroll') || sidebar;
      sidebar.scrollTop = sidebar.scrollHeight;
      node.scrollTop = node.scrollHeight;
      const last = [...document.querySelectorAll('.nav__item')].pop();
      const signOut = [...document.querySelectorAll('button')].find((b) => b.textContent.includes('Sign out'));
      const rect = sidebar.getBoundingClientRect();
      return {
        sidebarTop: Math.round(rect.top),
        sidebarBottom: Math.round(rect.bottom),
        viewport: window.innerHeight,
        lastBottom: Math.round(last.getBoundingClientRect().bottom),
        signOutBottom: signOut ? Math.round(signOut.getBoundingClientRect().bottom) : -1
      };
    })())`),
  );
  check(
    'phone-sized viewport: the panel never exceeds the visible height',
    phone.sidebarBottom <= phone.viewport + 2,
    `sidebar=${phone.sidebarTop}..${phone.sidebarBottom}px viewport=${phone.viewport}px`,
  );
  check(
    'phone-sized viewport: last menu entry and Sign out are reachable',
    phone.lastBottom <= phone.viewport + 2 && phone.signOutBottom <= phone.viewport + 2,
    `last=${phone.lastBottom} signOut=${phone.signOutBottom}`,
  );
  await cdp.send('Emulation.clearDeviceMetricsOverride');
  await sleep(400);

  // Illustrate both fixes: menu scrolled to the bottom + a tall, resized run log, at 140% zoom.
  await evaluate(`(() => {
    for (let i = 0; i < 8; i += 1) {
      document.dispatchEvent(new WheelEvent('wheel', { deltaY: -100, ctrlKey: true, cancelable: true, bubbles: true }));
    }
    const scroll = document.querySelector('.sidebar__scroll');
    scroll.scrollTop = scroll.scrollHeight;
    const dock = document.querySelector('.logdock');
    dock.style.setProperty('--log-height', '300px');
    return true;
  })()`);
  await sleep(400);
  {
    // local helper (this suite talks to CDP directly, it does not import cdp.mjs)
    const { writeFileSync } = await import('node:fs');
    // a desktop-sized viewport, otherwise the narrow window puts the sidebar in drawer mode
    await cdp.send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
    await sleep(500);
    await evaluate(`(() => {
      const scroll = document.querySelector('.sidebar__scroll');
      scroll.scrollTop = 0;
      return true;
    })()`);
    await sleep(200);
    const shot = await cdp.send('Page.captureScreenshot', { format: 'png' });
    writeFileSync(new URL('../.artifacts/shell-sidebar-logdock.png', import.meta.url), Buffer.from(shot.data, 'base64'));
    await cdp.send('Emulation.clearDeviceMetricsOverride');
  }
  await evaluate(`(() => {
    for (let i = 0; i < 8; i += 1) {
      document.dispatchEvent(new WheelEvent('wheel', { deltaY: 100, ctrlKey: true, cancelable: true, bubbles: true }));
    }
    document.querySelector('.logdock').style.removeProperty('--log-height');
    return true;
  })()`);

  /* 4. Protected routes are reachable */
  await goto(`${base}/#/tools`);
  const tools = JSON.parse(
    await evaluate(`JSON.stringify({
      shell: !!document.querySelector('.shell'),
      cards: document.querySelectorAll('.u-card').length,
      splitReady: !!document.querySelector('textarea')
    })`),
  );
  check('toolbox reachable after login', tools.shell === true && tools.cards >= 2, `${tools.cards} cards`);

  /* 5. The pure front-end tool really works (name split, 1:1 with utils/name_split.py) */
  const split = await evaluate(`(() => {
    const areas = document.querySelectorAll('textarea');
    const input = areas[0];
    input.value = 'Ahmad Bin Ali\\nTan Wei Ming\\nMadonna\\nali & abu binti omar';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    return areas[1].value;
  })()`);
  check(
    'name split matches the desktop rules (connectors, half split, title case)',
    split === 'Ahmad\tAli\nTan\tWei Ming\nMadonna\t\nAli\tAbu Omar',
    JSON.stringify(split),
  );

  /* 6. Save a screenshot */
  const shot = await cdp.send('Page.captureScreenshot', { format: 'png' });
  const { writeFileSync } = await import('node:fs');
  writeFileSync(new URL('../.artifacts/e2e-tools.png', import.meta.url), Buffer.from(shot.data, 'base64'));

  /* 7. Log out → the gate applies again */
  await evaluate(`document.querySelector('.sidebar .u-btn--danger').click()`);
  await sleep(600);
  const dialog = await evaluate(`!!document.querySelector('.u-modal-backdrop')`);
  check('confirmation dialog shown before logout', dialog === true);
  await evaluate(`document.querySelector('.u-modal__actions button:last-child').click()`);
  await sleep(2200);

  const afterLogout = JSON.parse(
    await evaluate(`JSON.stringify({
      login: !!document.querySelector('.login-stage'),
      shell: !!document.querySelector('.shell'),
      hash: location.hash
    })`),
  );
  check('back on the login page after logout', afterLogout.login === true && afterLogout.shell === false);
  const probeAfter = await evaluate(`fetch('/api/pbx/probe').then((r) => r.status)`);
  check('/api/pbx/probe returns 401 again after logout', probeAfter === 401, `status=${probeAfter}`);

  /* 8. Console errors */
  check('no JS console errors', cdp.consoleErrors.length === 0, cdp.consoleErrors.slice(0, 3).join(' | '));

  } catch (error) {
    console.error('\n[suite error]', error && error.stack ? error.stack : error);
    check('suite ran without throwing', false, String((error && error.message) || error).slice(0, 140));
  } finally {
    const failed = results.filter((item) => !item.ok);
    console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
    // Close the browser too: leaving it alive means the next run on this port would
    // re-attach to a stale instance (and its HTTP cache) instead of loading fresh files.
    try {
      await cdp.send('Browser.close');
    } catch {
      /* the socket often drops before the reply arrives */
    }
    ws.close();
    process.exit(failed.length ? 1 : 0);
  }
}

main().catch((error) => {
  console.error('E2E run failed: ', error.message);
  process.exit(2);
});
