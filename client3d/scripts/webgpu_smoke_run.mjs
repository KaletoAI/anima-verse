#!/usr/bin/env node
/**
 * Drive `webgpu-smoke.html` (client3d/src/webgpuSmoke.ts) in a headless
 * Chrome via CDP and print the page's JSON report — the boot probe of the
 * renderer switch, runnable without a world server, a login or a real GPU
 * (Chrome's SwiftShader gives a software WebGPU adapter).
 *
 * Usage:  node client3d/scripts/webgpu_smoke_run.mjs [--chrome <path>] [--url <base>] [--frames 60]
 *         default chrome: ~/.cache/ms-playwright/chromium-<n>/chrome-linux64/chrome (newest n)
 *         default url:    http://127.0.0.1:5283 (the branch's Vite dev server)
 * Prints one JSON line per mode (webgl, webgpu) and exits non-zero if either
 * report carries errors or the WebGPU run did not end up on the WebGPU backend.
 *
 * `--dump-dom` cannot be used for this: in that mode requestAnimationFrame
 * fires once and stops, so the animation loop never reaches the report frame.
 * A CDP-driven page renders continuously (Node >= 22 has WebSocket built in).
 */
import { spawn } from 'node:child_process';
import { readdirSync, existsSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';

const args = process.argv.slice(2);
const opt = (name, def) => { const i = args.indexOf(name); return i >= 0 ? args[i + 1] : def; };
const BASE = opt('--url', 'http://127.0.0.1:5283');
const FRAMES = opt('--frames', '60');
const PORT = 9333 + Math.floor(Math.random() * 500);

function findChrome() {
  const given = opt('--chrome', null);
  if (given) return given;
  const root = join(homedir(), '.cache/ms-playwright');
  if (!existsSync(root)) return null;
  const dirs = readdirSync(root).filter((d) => /^chromium-\d+$/.test(d)).sort();
  for (const d of dirs.reverse()) {
    const p = join(root, d, 'chrome-linux64/chrome');
    if (existsSync(p)) return p;
  }
  return null;
}

const chrome = findChrome();
if (!chrome) { console.error('no chrome found — pass --chrome <path>'); process.exit(2); }

const proc = spawn(chrome, [
  '--headless=new', '--no-sandbox', '--disable-gpu-sandbox',
  '--enable-unsafe-webgpu', '--enable-unsafe-swiftshader', '--enable-features=Vulkan',
  '--use-angle=swiftshader', '--ignore-gpu-blocklist',
  `--remote-debugging-port=${PORT}`, '--window-size=800,600', 'about:blank',
], { stdio: ['ignore', 'ignore', 'ignore'] });

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function json(url) { const r = await fetch(url); return r.json(); }

async function waitForChrome() {
  for (let i = 0; i < 100; i++) {
    try { return await json(`http://127.0.0.1:${PORT}/json/version`); } catch { await sleep(200); }
  }
  throw new Error('chrome did not open the debugging port');
}

class Cdp {
  constructor(ws) { this.ws = ws; this.id = 0; this.pending = new Map(); this.events = [];
    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.id && this.pending.has(msg.id)) { this.pending.get(msg.id)(msg); this.pending.delete(msg.id); }
      else if (msg.method) this.events.push(msg);
    };
  }
  send(method, params = {}) {
    const id = ++this.id;
    return new Promise((resolve) => { this.pending.set(id, resolve); this.ws.send(JSON.stringify({ id, method, params })); });
  }
}

async function runMode(query) {
  const target = await json(`http://127.0.0.1:${PORT}/json/new?about:blank`).catch(async () => {
    const r = await fetch(`http://127.0.0.1:${PORT}/json/new?about:blank`, { method: 'PUT' }); return r.json();
  });
  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((r, j) => { ws.onopen = r; ws.onerror = j; });
  const cdp = new Cdp(ws);
  await cdp.send('Page.enable');
  await cdp.send('Runtime.enable');
  await cdp.send('Page.navigate', { url: `${BASE}/webgpu-smoke.html${query}` });
  let title = '';
  const deadline = Date.now() + 120000;
  while (Date.now() < deadline) {
    await sleep(500);
    const r = await cdp.send('Runtime.evaluate', { expression: 'document.title', returnByValue: true });
    title = r.result?.result?.value ?? '';
    if (title.startsWith('{')) break;
  }
  ws.close();
  await fetch(`http://127.0.0.1:${PORT}/json/close/${target.id}`).catch(() => {});
  if (!title.startsWith('{')) return { error: 'no report within 120 s', query };
  return JSON.parse(title);
}

let exit = 0;
try {
  await waitForChrome();
  const gl = await runMode(`?frames=${FRAMES}`);
  console.log(JSON.stringify({ mode: 'webgl', ...gl }));
  const gpu = await runMode(`?webgpu=1&frames=${FRAMES}`);
  console.log(JSON.stringify({ mode: 'webgpu', ...gpu }));
  if (gl.error || (gl.errors && gl.errors.length)) exit = 1;
  if (gpu.error || (gpu.errors && gpu.errors.length) || gpu.active !== 'webgpu') exit = 1;
} catch (e) {
  console.error(String(e)); exit = 2;
} finally {
  proc.kill('SIGKILL');
}
process.exit(exit);
