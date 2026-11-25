#!/usr/bin/env node
/**
 * Smoke: the Game-Admin figure polls never stack, the `generation` push is debounced and the open-steps focus
 * read is throttled (frontend/src/lib/guardedPoll.ts; plan 2026-11-24-figure-poll-caches Task 1). Before it, a
 * `setInterval` fired its read every period whether the last one had answered or not, so a slow server collected
 * one more request per period, and a burst of pushes became a burst of reads.
 *
 * Usage:  node scripts/smoke_guarded_poll.mjs      (no server; esbuild from the workspace bundles the module)
 *
 * Fake timers: one virtual clock, timers run in time order, microtasks are flushed after each one.
 *
 * THE CASES, DERIVED BY HAND:
 * [G1] guardedInterval, load takes 12 s, period 5 s, run 30 s. Ticks at 5, 10, 15, 20, 25, 30:
 *      t=5 starts (busy until 17), t=10 and t=15 are skipped, t=20 starts (busy until 32), t=25 and t=30 are
 *      skipped → 2 calls (a plain setInterval: 6).
 * [G2] load rejects at once, period 5 s, run 10 s → ticks 5 and 10 both call (the guard is released on failure) →
 *      2 calls, and no unhandled rejection escapes.
 * [G3] debounced 300 ms, calls at 0, 50, 120, 200 ms → 1 run, at 200 + 300 = 500 ms. Same four calls, then
 *      cancel() at 300 ms → 0 runs by 1000 ms.
 * [G4] throttled 10 s, calls at 0, 3, 9, 11 s → runs at 0 (leading) and 11 (11 - 0 >= 10); 3 and 9 fall within
 *      10 s of the run at 0 → runs [0, 11000].
 * [G5] guardedInterval, load takes 4 s, period 5 s; stop at t=7 (the call started at 5 still runs) → run to 30 s:
 *      exactly 1 call.
 * [G6] Source guard: the six touched files under frontend/src/tabs/characters/ contain no `setInterval(`, and
 *      every `onTopics(['generation'], X)` in them passes an identifier X that the same file assigns from
 *      `debounced(`.
 */
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = fileURLToPath(new URL('..', import.meta.url));
const require_ = createRequire(import.meta.url);

// esbuild resolves from the workspace (scripts/ has no node_modules of its own; see smoke_cut_build_row_text.mjs)
function esbuildModule() {
  for (const cand of ['esbuild', join(ROOT, 'frontend/node_modules/esbuild'),
                      join(ROOT, 'client3d/node_modules/esbuild'), join(ROOT, 'node_modules/esbuild')]) {
    try {
      return require_(cand);
    } catch { /* next candidate */ }
  }
  console.error('esbuild not found (npm install) — nothing was checked');
  process.exit(1);
}

async function loadBundled(src) {
  const esbuild = esbuildModule();
  const dir = await mkdtemp(join(tmpdir(), 'smoke-guarded-poll-'));
  try {
    const file = join(dir, 'module.mjs');
    await esbuild.build({ entryPoints: [src], outfile: file, bundle: true, format: 'esm', platform: 'neutral',
      logLevel: 'silent', absWorkingDir: ROOT });
    return await import(`file://${file}`);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

const failures = [];
function check(label, got, want) {
  const g = JSON.stringify(got);
  const w = JSON.stringify(want);
  if (g === w) console.log(`  [ok] ${label}: ${g}`);
  else { console.log(`  [FAIL] ${label}: got ${g}, want ${w}`); failures.push(label); }
}

/** A virtual clock: setTimeout/setInterval queue entries, advance(to) runs them in time order. */
function fakeTimers() {
  let now = 0;
  let seq = 0;
  const timers = new Map();
  const flush = async () => { for (let i = 0; i < 20; i++) await Promise.resolve(); };
  const add = (fn, ms, every) => { const id = ++seq; timers.set(id, { at: now + ms, fn, every: every ? ms : 0, seq: id }); return id; };
  return {
    now: () => now,
    timers: {
      setTimeout: (fn, ms) => add(fn, ms, false),
      clearTimeout: (id) => { timers.delete(id); },
      setInterval: (fn, ms) => add(fn, ms, true),
      clearInterval: (id) => { timers.delete(id); },
    },
    async advance(to) {
      await flush();
      for (;;) {
        let next = null;
        let nextId = 0;
        for (const [id, t] of timers) {
          if (t.at <= to && (!next || t.at < next.at || (t.at === next.at && t.seq < next.seq))) { next = t; nextId = id; }
        }
        if (!next) break;
        now = next.at;
        if (next.every) { next.at += next.every; next.seq = ++seq; } else timers.delete(nextId);
        next.fn();
        await flush();
      }
      now = to;
    },
  };
}

const src = join(ROOT, 'frontend/src/lib/guardedPoll.ts');
let mod;
try {
  mod = await loadBundled(src);
} catch (e) {
  console.log(`  [FAIL] bundle ${src}: ${(e && e.message) || e}`);
  process.exit(1);
}
const { guardedInterval, debounced, throttled } = mod;

// [G1]
{
  const ft = fakeTimers();
  const starts = [];
  const load = () => { starts.push(ft.now()); return new Promise((res) => ft.timers.setTimeout(res, 12000)); };
  guardedInterval(load, 5000, ft.timers);
  await ft.advance(30000);
  check('[G1] 12 s load, 5 s period, 30 s: call times', starts, [5000, 20000]);
}
// [G2]
{
  const ft = fakeTimers();
  let calls = 0;
  const load = () => { calls += 1; return Promise.reject(new Error('boom')); };
  guardedInterval(load, 5000, ft.timers);
  await ft.advance(10000);
  check('[G2] a rejected load releases the guard: calls in 10 s', calls, 2);
}
// [G3]
{
  const ft = fakeTimers();
  const runs = [];
  const fn = debounced(() => runs.push(ft.now()), 300, ft.timers);
  for (const t of [0, 50, 120, 200]) { await ft.advance(t); fn(); }
  await ft.advance(1000);
  check('[G3] debounced: run times', runs, [500]);
  const ft2 = fakeTimers();
  const runs2 = [];
  const fn2 = debounced(() => runs2.push(ft2.now()), 300, ft2.timers);
  for (const t of [0, 50, 120, 200]) { await ft2.advance(t); fn2(); }
  await ft2.advance(300);
  fn2.cancel();
  await ft2.advance(1000);
  check('[G3] cancel() before it fires: runs', runs2.length, 0);
}
// [G4]
{
  let clock = 0;
  const runs = [];
  const fn = throttled(() => runs.push(clock), 10000, () => clock);
  for (const t of [0, 3000, 9000, 11000]) { clock = t; fn(); }
  check('[G4] throttled 10 s: run times', runs, [0, 11000]);
}
// [G5]
{
  const ft = fakeTimers();
  let calls = 0;
  const load = () => { calls += 1; return new Promise((res) => ft.timers.setTimeout(res, 4000)); };
  const stop = guardedInterval(load, 5000, ft.timers);
  await ft.advance(7000);
  stop();
  await ft.advance(30000);
  check('[G5] stop while a load runs: calls', calls, 1);
}
// [G6]
{
  const dir = join(ROOT, 'frontend/src/tabs/characters');
  const files = ['useOpenSteps.ts', 'TemplateCutTextureBox.tsx', 'TemplateParamsDialog.tsx',
    'BuildAllOpenButton.tsx', 'useFigure.ts', 'useGarment.ts'];
  const bad = [];
  let pushes = 0;
  for (const f of files) {
    const text = await readFile(join(dir, f), 'utf8');
    if (text.includes('setInterval(')) bad.push(`${f}: setInterval(`);
    for (const m of text.matchAll(/onTopics\(\s*\['generation'\]\s*,\s*([^)]*)\)/g)) {
      pushes += 1;
      const arg = m[1].trim();
      const ident = /^[A-Za-z_$][\w$]*$/.test(arg) ? arg : '';
      const assigned = ident && new RegExp(`\\b(?:const|let)\\s+${ident}\\s*=\\s*debounced\\(`).test(text);
      if (!assigned) bad.push(`${f}: onTopics(['generation'], ${arg}) is not a debounced function`);
    }
  }
  check('[G6] no setInterval, every generation push debounced', bad, []);
  check('[G6] generation pushes found (>= 4)', pushes >= 4, true);
}

if (failures.length) {
  console.log(`\nFAILED (${failures.length}): ${failures.join(', ')}`);
  process.exit(1);
}
console.log('\nOK');
