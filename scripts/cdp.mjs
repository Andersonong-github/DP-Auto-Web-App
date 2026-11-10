/**
 * cdp.mjs — minimal Chrome DevTools Protocol client (WebSocket built into Node 22+).
 *
 * Usage:
 *   const { evaluate, goto, screenshot, consoleErrors, close } = await connectCdp({ port: 9333 });
 */

import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, isAbsolute, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

export const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/** Screenshots are written relative to the project root, not the caller's cwd. */
const PROJECT_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');

function artifactPath(target) {
  const full = isAbsolute(target) ? target : resolve(PROJECT_ROOT, target);
  mkdirSync(dirname(full), { recursive: true });
  return full;
}

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

export async function connectCdp({ port = 9333 } = {}) {
  const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  const page = targets.find((target) => target.type === 'page');
  if (!page) throw new Error('No available page target; make sure Chrome was started with --remote-debugging-port');
  // Note: if an old browser instance is still attached to this debug port, tests will run against the old page (learned this the hard way)
  if (page.url && !/^(about:blank|chrome:)/.test(page.url)) {
    console.warn(`[warn] target page is currently at ${page.url}, may be connected to a previous browser instance`);
  }

  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    ws.addEventListener('open', resolve, { once: true });
    ws.addEventListener('error', reject, { once: true });
  });

  const client = new Cdp(ws);
  await client.send('Page.enable');
  await client.send('Runtime.enable');

  return {
    client,
    consoleErrors: client.consoleErrors,

    async evaluate(expression) {
      const result = await client.send('Runtime.evaluate', {
        expression,
        awaitPromise: true,
        returnByValue: true,
      });
      if (result.exceptionDetails) {
        throw new Error(result.exceptionDetails.exception?.description || 'exception in page');
      }
      return result.result.value;
    },

    async goto(url, wait = 2600) {
      await client.send('Page.navigate', { url });
      await sleep(wait);
    },

    async screenshot(path, { width = 1600, height = 1000 } = {}) {
      // Without a viewport override, headless defaults to 800x600 and the screenshots look bad
      await client
        .send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: false })
        .catch(() => {});
      const shot = await client.send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true });
      await client.send('Emulation.clearDeviceMetricsOverride').catch(() => {});
      writeFileSync(artifactPath(path), Buffer.from(shot.data, 'base64'));
      return artifactPath(path);
    },

    /** Poll an expression in the page until it returns a truthy value or times out. */
    async waitFor(expression, { timeoutMs = 60000, intervalMs = 500 } = {}) {
      const deadline = Date.now() + timeoutMs;
      while (Date.now() < deadline) {
        try {
          const value = await this.evaluate(expression);
          if (value) return value;
        } catch {
          /* the page may be navigating */
        }
        await sleep(intervalMs);
      }
      return null;
    },

    close() {
      // Ask the browser to exit first, so the next run does not connect to a leftover instance
      client.send('Browser.close').catch(() => {}).finally(() => {
        setTimeout(() => ws.close(), 200);
      });
    },
  };
}

export function reporter() {
  const results = [];
  return {
    check(name, ok, detail = '') {
      results.push({ name, ok, detail });
      console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? ` — ${detail}` : ''}`);
    },
    summary() {
      const failed = results.filter((item) => !item.ok);
      console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
      return failed.length;
    },
  };
}
