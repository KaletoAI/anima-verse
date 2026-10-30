/**
 * Smoke run for the graphics settings of `client3d/src/game/prefs.ts`
 * (Task 26d — the game menu's Graphics tab: anti-aliasing and shadows).
 *
 * Usage:  node client3d/scripts/smoke_graphics_prefs.mjs
 *         (transforms the module with esbuild — a Vite dependency, already
 *          installed; no bundler, no DOM, no server)
 *
 * The cases live in `shared/test-vectors/graphics_prefs.json`, which the native
 * client's C# port reads as well. Every expectation is derived BY HAND below
 * from the rules, never recorded from the current output.
 *
 * ---------------------------------------------------------------------------
 * THE RULES
 * ---------------------------------------------------------------------------
 * Shape: `{ antiAliasing: 'off' | '2x' | '4x', shadows: boolean }`, stored as
 * JSON under `av3d.view.graphics.v1`. Default `{ antiAliasing: '2x',
 * shadows: true }`.
 *
 *   load   — no string / unparsable / not a plain JSON object → the defaults.
 *            Otherwise FIELD BY FIELD: a level is taken only if it is exactly
 *            one of the three strings (case-sensitive, no numbers), the switch
 *            only if it is a JSON boolean; anything else falls back to that
 *            field's default and leaves the other field alone.
 *   check  — (level, switch) from outside → ok + prefs, or the FIRST refused
 *            field: the level is checked before the switch.
 *   save   — `{"antiAliasing":<level>,"shadows":<bool>}`, that key order, no
 *            spaces.
 *   msaa   — off → 0, 2x → 2, 4x → 4 samples (Godot `Viewport.msaa_3d`).
 *   browser antialias — WebGL knows on/off only: on unless the level is off.
 *   browser pick — the browser menu's Off/On → the level to store: Off is
 *            'off'; On keeps a level that is already on (2x or 4x — both show
 *            as "On", so clicking the lit pill must not rewrite it) and turns
 *            'off' into the default '2x'.
 *
 * ---------------------------------------------------------------------------
 * [1] NOTHING USABLE STORED → THE DEFAULTS
 * ---------------------------------------------------------------------------
 *   null (nothing stored)          → { '2x', true }
 *   ''   (empty string, falsy)     → { '2x', true }
 *   'not json'  (parse error)      → { '2x', true }
 *   '[]'        (array)            → { '2x', true }
 *   'null'      (JSON null)        → { '2x', true }
 *   '"4x"'      (a bare string)    → { '2x', true } — a level alone is not
 *                                     the object, even a valid one.
 *
 * ---------------------------------------------------------------------------
 * [2] FIELD BY FIELD
 * ---------------------------------------------------------------------------
 *   {"antiAliasing":"4x","shadows":false}      both valid  → { '4x', false }
 *   {"antiAliasing":"off","shadows":true}      both valid  → { 'off', true }
 *   {"antiAliasing":"8x","shadows":false}      8x is no level → '2x'; the
 *                                              switch stays false → { '2x', false }
 *   {"antiAliasing":"off","shadows":"false"}   a STRING "false" is not a
 *                                              boolean → true; level kept
 *                                              → { 'off', true }
 *   {"antiAliasing":4,"shadows":0}             a number is neither → { '2x', true }
 *   {"antiAliasing":"4X"}                      case-sensitive, and the
 *                                              switch is missing → { '2x', true }
 *   {}                                         → { '2x', true }
 *
 * ---------------------------------------------------------------------------
 * [3] CHECK
 * ---------------------------------------------------------------------------
 *   ('4x', false)  → ok, { '4x', false }
 *   ('off', true)  → ok, { 'off', true }
 *   ('8x', true)   → refused: antiAliasing
 *   ('off', 'yes') → refused: shadows
 *   (null, null)   → refused: antiAliasing (the level is checked first)
 *   ('2x', 1)      → refused: shadows (1 is not a boolean)
 *
 * ---------------------------------------------------------------------------
 * [4] SAVE AND THE ROUND TRIP
 * ---------------------------------------------------------------------------
 *   save { '4x', false } → '{"antiAliasing":"4x","shadows":false}'
 *   save { 'off', true } → '{"antiAliasing":"off","shadows":true}'
 *   load of the first string → { '4x', false } — the same prefs back.
 *
 * ---------------------------------------------------------------------------
 * [5] MSAA SAMPLES         off → 0     2x → 2     4x → 4
 * [6] BROWSER ANTIALIAS    off → false 2x → true  4x → true
 * [7] BROWSER PICK         (Off, '4x') → 'off'   (Off, 'off') → 'off'
 *                          (On, 'off') → '2x'    (On, '2x') → '2x'
 *                          (On, '4x')  → '4x'
 *
 * ---------------------------------------------------------------------------
 * [8] THE CONSTANTS BOTH CLIENTS SHARE
 * ---------------------------------------------------------------------------
 *   key      'av3d.view.graphics.v1'
 *   levels   ['off', '2x', '4x'] — the menu order of the native choice
 *   defaults { antiAliasing: '2x', shadows: true }
 *   renderScale defaults to 'auto'; its JSON fixed values are numbers.
 *   [9] Missing/invalid scale -> auto; [10] auto uses a 1920*1080 budget,
 *   floor(sqrt(budget/pixels)*20)/20, clamped to [.5,1]. Hand derivations
 *   are in the vector file's comment, consumed by both clients.
 *   `graphicsPrefsConstants()` is a smoke adapter returning these three as
 *   `{ key, levels, defaults }` — the C# side mirrors it.
 */
import { readFile, writeFile, mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadVectors, runVectors } from '../../shared/test-vectors/vectors.mjs';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const SRC = join(ROOT, 'client3d', 'src', 'game', 'prefs.ts');

/** The module, transformed and imported — it has no imports of its own, so a
 *  single-file transform is enough. */
async function loadPrefsModule() {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(tmpdir(), 'graphics-prefs-'));
  try {
    const source = await readFile(SRC, 'utf8');
    const out = esbuild.transformSync(source, { loader: 'ts', format: 'esm' });
    const file = join(dir, 'prefs.mjs');
    await writeFile(file, out.code, 'utf8');
    return await import(`file://${file}`);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

const P = await loadPrefsModule();
const vectors = runVectors(loadVectors('graphics_prefs'), {
  autoRenderScale: (...a) => P.autoRenderScale(...a),
  effectiveRenderScale: (...a) => P.effectiveRenderScale(...a),
  loadGraphicsPrefs: P.loadGraphicsPrefs,
  checkGraphicsPrefs: P.checkGraphicsPrefs,
  saveGraphicsPrefs: P.saveGraphicsPrefs,
  msaaSamplesOf: P.msaaSamplesOf,
  browserAntialias: P.browserAntialias,
  pickBrowserAntiAliasing: P.pickBrowserAntiAliasing,
  graphicsPrefsConstants: () => ({
    key: P.GRAPHICS_PREFS_KEY,
    levels: [...P.ANTI_ALIASING_LEVELS],
    defaults: { ...P.DEFAULT_GRAPHICS_PREFS },
  }),
});
let passed = vectors.passed;
let failed = vectors.failed;
function check(what, ok) {
  if (ok) { passed += 1; console.log(`  ok   ${what}`); }
  else { failed += 1; console.log(`  FAIL ${what}`); }
}

console.log('\n(inline) relations');
// A loaded default is a COPY: a caller that edits it must not move the default.
const fresh = P.loadGraphicsPrefs(null);
fresh.shadows = false;
check('[1] the defaults come back as a copy', P.DEFAULT_GRAPHICS_PREFS.shadows === true
  && P.loadGraphicsPrefs(null).shadows === true);
// The round trip holds for all 36 combinations, including automatic and every fixed scale.
let roundTrips = 0;
for (const aa of ['off', '2x', '4x']) {
  for (const shadows of [true, false]) for (const renderScale of ['auto', 1, 0.85, 0.75, 0.66, 0.5]) {
    const back = P.loadGraphicsPrefs(P.saveGraphicsPrefs({ antiAliasing: aa, shadows, renderScale }));
    if (back.antiAliasing === aa && back.shadows === shadows && back.renderScale === renderScale) roundTrips += 1;
  }
}
check('[4] save → load returns all 36 valid prefs unchanged', roundTrips === 36);
// The browser pick never lands on a level the browser would show differently:
// Off stays off, On stays on.
let picks = 0;
for (const current of ['off', '2x', '4x']) {
  for (const on of [true, false]) {
    const next = P.pickBrowserAntiAliasing(on, current);
    if (P.browserAntialias({ antiAliasing: next, shadows: true }) === on) picks += 1;
  }
}
check('[7] the browser pick always shows what was clicked', picks === 6);

console.log(`\n${passed} ok, ${failed} failed`);
process.exit(failed === 0 ? 0 : 1);
