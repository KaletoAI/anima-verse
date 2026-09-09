#!/usr/bin/env node
/**
 * Smoke run for the ONE time-of-day format — in all THREE places it exists.
 *
 * Usage:  node scripts/smoke_clock_format.mjs
 *
 * `server.time_format` (admin → Server) decides how a time of day reads, and
 * `server.timezone` decides which wall clock a SYSTEM stamp is read on. Three
 * implementations have to agree on both:
 *
 *   1. `app/core/game_time.py`                    → format_time_of_day()
 *   2. `packages/player-ui/src/clockFormat.ts`    → formatGameTime/formatTime
 *   3. `static/admin/clock-format.js`             → AdminClock.time()
 *
 * A twin that drifts is the whole risk here, so every expected string below is
 * derived BY HAND and all three are held against the same table — nothing is
 * recorded from current output.
 *
 * ============================================================================
 * THE TABLE, DERIVED
 * ============================================================================
 * Rules of the four shapes:
 *   24h          hour zero-padded, minute zero-padded, no seconds
 *   24h_seconds  … plus ":SS"
 *   12h          hour 0 reads 12 AM, hour 12 reads 12 PM, 13 reads 1 PM; the
 *                HOUR is not padded, minute/second always are; " AM"/" PM"
 *   12h_seconds  … plus ":SS" before the suffix
 *
 *   (h, m, s)   24h        24h_seconds   12h          12h_seconds
 *   (0, 7, 5)   00:07      00:07:05      12:07 AM     12:07:05 AM
 *   (9, 0, 0)   09:00      09:00:00      9:00 AM      9:00:00 AM
 *   (12,30,5)   12:30      12:30:05      12:30 PM     12:30:05 PM
 *   (13, 5,5)   13:05      13:05:05      1:05 PM      1:05:05 PM
 *   (23,59,5)   23:59      23:59:05      11:59 PM     11:59:05 PM
 *
 * ============================================================================
 * THE ZONES, DERIVED
 * ============================================================================
 * A SYSTEM stamp is an instant; the zone decides the wall clock.
 *
 *   2026-07-01T12:00:00Z  (northern summer)
 *     UTC              → 12:00       offset +0
 *     Europe/Berlin    → 14:00       CEST, +2
 *     America/New_York → 08:00       EDT,  −4
 *     Asia/Tokyo       → 21:00       JST,  +9 (no DST)
 *
 *   2026-01-15T23:30:00Z  (northern winter, and a day boundary)
 *     Europe/Berlin    → 00:30       CET, +1 → the NEXT day
 *     America/New_York → 18:30       EST, −5 → the same day
 *
 * This file runs with TZ=Asia/Tokyo on purpose: the results above must hold
 * anyway. That is the regression guard for the actual bug — the header clock
 * used to read the VIEWER's zone (`Date.getHours()`), so on a Tokyo machine it
 * showed 21:00 where the world clock says 14:00.
 *
 * An unknown zone name falls back to UTC — never to the local zone, which
 * would silently be Tokyo here.
 */

// Must be set before the first date is formatted; Node re-reads TZ on change.
process.env.TZ = 'Asia/Tokyo';

import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { mkdtemp, rm } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const ROOT = fileURLToPath(new URL('..', import.meta.url));
const require_ = createRequire(import.meta.url);

function esbuildModule() {
  for (const cand of ['esbuild',
                      join(ROOT, 'frontend/node_modules/esbuild'),
                      join(ROOT, 'client3d/node_modules/esbuild')]) {
    try {
      return require_(cand);
    } catch { /* next candidate */ }
  }
  console.error('esbuild not found (npm install) — nothing was checked');
  process.exit(1);
}

async function loadBundled(src, prefix) {
  const esbuild = esbuildModule();
  const dir = await mkdtemp(join(tmpdir(), prefix));
  try {
    const file = join(dir, 'module.mjs');
    await esbuild.build({
      entryPoints: [src], outfile: file, bundle: true, format: 'esm',
      platform: 'neutral', logLevel: 'silent', absWorkingDir: ROOT,
    });
    return await import(`file://${file}`);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

/** The admin pages' plain script, loaded with a fake page around it. */
function loadAdminClock() {
  const code = readFileSync(join(ROOT, 'static/admin/clock-format.js'), 'utf8');
  const dataset = {};
  const sandbox = { window: {}, document: { body: { dataset } } };
  vm.createContext(sandbox);
  vm.runInContext(code, sandbox);
  return { admin: sandbox.window.AdminClock, dataset };
}

let failed = 0;
let passed = 0;
function eq(label, actual, expected) {
  if (actual === expected) {
    passed += 1;
  } else {
    failed += 1;
    console.error(`FAIL ${label}: got ${JSON.stringify(actual)}, want ${JSON.stringify(expected)}`);
  }
}

// ── the hand-derived tables ────────────────────────────────────────────────
const SHAPES = [
  // [hour, minute, second, 24h, 24h_seconds, 12h, 12h_seconds]
  [0, 7, 5, '00:07', '00:07:05', '12:07 AM', '12:07:05 AM'],
  [9, 0, 0, '09:00', '09:00:00', '9:00 AM', '9:00:00 AM'],
  [12, 30, 5, '12:30', '12:30:05', '12:30 PM', '12:30:05 PM'],
  [13, 5, 5, '13:05', '13:05:05', '1:05 PM', '1:05:05 PM'],
  [23, 59, 5, '23:59', '23:59:05', '11:59 PM', '11:59:05 PM'],
];
const FORMATS = ['24h', '24h_seconds', '12h', '12h_seconds'];

const ZONES = [
  ['2026-07-01T12:00:00Z', 'UTC', '12:00'],
  ['2026-07-01T12:00:00Z', 'Europe/Berlin', '14:00'],
  ['2026-07-01T12:00:00Z', 'America/New_York', '08:00'],
  ['2026-07-01T12:00:00Z', 'Asia/Tokyo', '21:00'],
  ['2026-01-15T23:30:00Z', 'Europe/Berlin', '00:30'],
  ['2026-01-15T23:30:00Z', 'America/New_York', '18:30'],
];

const { formatGameTime, formatTime, asTimeFormat, sameZoneDay } =
  await loadBundled(join(ROOT, 'packages/player-ui/src/clockFormat.ts'), 'clockfmt-');
const { admin, dataset } = loadAdminClock();

// ── 1. the four shapes, in TypeScript and in the admin script ──────────────
for (const row of SHAPES) {
  const [h, m, s] = row;
  FORMATS.forEach((fmt, i) => {
    const want = row[3 + i];
    eq(`ts formatGameTime(${h},${m},${fmt},${s})`, formatGameTime(h, m, fmt, s), want);
    // The admin script has no game clock, so it is checked through a stamp of
    // that wall time in a fixed zone (UTC) — same shape function underneath.
    dataset.clockFormat = fmt;
    dataset.clockTimezone = 'UTC';
    const iso = `2026-07-01T${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}Z`;
    eq(`admin time(${iso}, ${fmt})`, admin.time(iso), want);
  });
}

// ── 2. the same four shapes in Python ──────────────────────────────────────
const pyArgs = SHAPES.map((r) => `${r[0]},${r[1]},${r[2]}`).join(' ');
const pyOut = execFileSync(join(ROOT, '.venv/bin/python'), ['-c', `
import sys
from app.core.game_time import format_time_of_day as f
formats = ${JSON.stringify(FORMATS)}
for triple in sys.argv[1:]:
    h, m, s = (int(x) for x in triple.split(','))
    print("\\t".join(f(h, m, fmt, s) for fmt in formats))
`, ...pyArgs.split(' ')], { cwd: ROOT, encoding: 'utf8' }).trim().split('\n');
SHAPES.forEach((row, r) => {
  const got = (pyOut[r] || '').split('\t');
  FORMATS.forEach((fmt, i) => {
    eq(`py format_time_of_day(${row[0]},${row[1]},${fmt},${row[2]})`, got[i], row[3 + i]);
  });
});

// ── 3. the zones (24h, so only the wall clock is under test) ───────────────
for (const [iso, tz, want] of ZONES) {
  eq(`ts formatTime(${iso}, ${tz})`, formatTime(iso, { format: '24h', timeZone: tz }), want);
  dataset.clockFormat = '24h';
  dataset.clockTimezone = tz;
  eq(`admin time(${iso}, ${tz})`, admin.time(iso), want);
}

// ── 4. an unknown zone reads as UTC, never as the local one (Tokyo here) ───
eq('ts formatTime(unknown zone)',
   formatTime('2026-07-01T12:00:00Z', { format: '24h', timeZone: 'Mars/Olympus' }), '12:00');
dataset.clockTimezone = 'Mars/Olympus';
eq('admin time(unknown zone)', admin.time('2026-07-01T12:00:00Z'), '12:00');

// ── 5. guards around the edges ─────────────────────────────────────────────
eq('ts asTimeFormat(garbage)', asTimeFormat('twelve-ish'), '24h');
eq('ts asTimeFormat(12h)', asTimeFormat('12h'), '12h');
eq('ts formatTime(empty)', formatTime('', { format: '24h', timeZone: 'UTC' }), '');
eq('ts formatTime(garbage)', formatTime('not-a-date', { format: '24h', timeZone: 'UTC' }), '');
dataset.clockFormat = '24h';
dataset.clockTimezone = 'UTC';
eq('admin time(empty)', admin.time(''), '');
eq('admin time(garbage)', admin.time('not-a-date'), '');

// The day boundary decides "today only shows a time": 23:30 UTC and 00:30 UTC
// are the same Berlin day (01:30 and 02:30 CEST on 2026-07-02) but different
// UTC days.
eq('sameZoneDay(Berlin, across UTC midnight)',
   String(sameZoneDay('2026-07-01T23:30:00Z', '2026-07-02T00:30:00Z',
                      { format: '24h', timeZone: 'Europe/Berlin' })), 'true');
eq('sameZoneDay(UTC, across UTC midnight)',
   String(sameZoneDay('2026-07-01T23:30:00Z', '2026-07-02T00:30:00Z',
                      { format: '24h', timeZone: 'UTC' })), 'false');

console.log(`${passed} checks passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
