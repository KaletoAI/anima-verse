#!/usr/bin/env node
/**
 * Smoke check for the MINIMAP WINDOW — the sight-radius framing of the map in
 * the embodied mode (`client3d/src/game/minimap.ts`).
 *
 * Usage:  node client3d/scripts/smoke_minimap_math.mjs
 *
 * Every number below is derived BY HAND in this docstring and never recorded
 * from the current output (§ B5a: numbers, not screenshots). The whole-frame
 * framing, `worldToPx` and the redraw signatures are checked in
 * `smoke_walk_math.mjs`; this file is about the window, the choice between the
 * two, and the anchor that moves it.
 *
 * ============================================================================
 * [1] The radius IS the sight radius — capped at half the world
 * ============================================================================
 * `MINIMAP_VIEW_RADIUS_M` is 520 m because the scene fog closes the 3D view at
 * 520 m (`scene/engine.ts`: `new THREE.Fog(0x9fc7e8, 220, 520)`). The two are
 * separate literals — `engine.ts` is `three`-bound, `minimap.ts` is pure — so
 * this file reads the fog call out of the ENGINE SOURCE and compares. A change
 * to the fog that forgets the map fails here rather than in someone's eyes.
 *
 * `minimapRadius(bounds) = min(520, max(span, MINIMAP_MIN_SPAN_M) / 2)` with
 * `span` the longer axis of the world frame:
 *   - 2 000 × 2 000 m -> min(520, 1000) = 520      the sight radius binds
 *   - 400 × 400 m     -> min(520,  200) = 200      half the world binds
 *   - 400 × 100 m     -> span is the LONGER axis   -> 200
 *   - 6 × 6 m         -> the 10 m floor           -> 5
 *   - min == max (one placed location, § A12 warns of it) -> the floor, 5,
 *     never 0 — that is what the floor is for
 *   - no bounds at all -> the same 5: no world to be half of
 * THE POINT of the cap: in a small world the window then has EXACTLY the scale
 * of the old whole-frame fit, `sizePx / max(w, d)` = `sizePx / (2 · span/2)`.
 * The window never zooms a small world OUT — it only ever zooms in.
 *
 * ============================================================================
 * [2] `minimapWindowLayout(center, radiusM, sizePx)`
 * ============================================================================
 *     scale = sizePx / (2 · radiusM)          [px per METRE, fixed]
 *     offX  = sizePx / 2 - center.x · scale
 *     offY  = sizePx / 2 - center.z · scale
 * and `worldToPx` (unchanged) then puts a point at
 *     px = offX + x · scale,   py = offY + z · scale.
 *
 * THE HAND CASE, used all through this file: avatar at (100, -200), radius
 * 520 m, canvas edge 256 px.
 *     scale = 256 / 1040 = 16/65 = 0.24615384615384617
 *     offX  = 128 - 100 · 16/65 = 128 - 1600/65 = 103.38461538461539
 *     offY  = 128 + 200 · 16/65 = 128 + 3200/65 = 177.23076923076923
 *   - the avatar itself: px = 128 - 1600/65 + 1600/65 = 128, py likewise 128.
 *     THE MIDDLE OF THE CANVAS, by construction and not by luck.
 *   - 520 m NORTH (north is -z, so z = -720):
 *     py = 128 + 200·s - 720·s = 128 - 520·s = 128 - 128 = 0  -> (128, 0)
 *     The top edge. North is UP with no flip anywhere — `py` simply grows
 *     with z.
 *   - 520 m EAST (x = 620):   px = 128 + 520·s = 256  -> (256, 128)
 *     256 on a 256 px canvas is ONE PAST the last pixel (0…255). That is the
 *     edge convention: the mapping is continuous, the canvas is the clip, and
 *     the far edge belongs to the next pixel that does not exist.
 *   - 520 m SOUTH (z = 320):  py = 256           -> (128, 256)
 *   - 520 m WEST  (x = -420): px = 0             -> (0, 128)
 *   - HALF WAY EAST (260 m, x = 360): 260 · 16/65 = 64 -> px = 192
 *   - a quarter north (130 m, z = -330):        py = 128 - 32 = 96
 *   - a place 900 m east (x = 1000): px = 128 + 900·s = 349.53… — off the
 *     canvas, i.e. NOT DRAWN. No rim clamping in v1: a dot on the edge would
 *     claim a place is within sight when it is not.
 *   - the same window on the real 160 px canvas: scale = 160/1040 = 2/13 =
 *     0.15384615384615385, so a metre is 0.15 px.
 *   - no centre / radius 0: scale 0 and the canvas centre — the same "nothing
 *     to draw" answer the whole-frame fit gives for an empty world.
 *
 * ============================================================================
 * [3] `minimapView(avatar, bounds, sizePx)` — which framing applies
 * ============================================================================
 * A figure on the map -> the window around it, at `minimapRadius(bounds)`. No
 * figure -> the whole world frame, unchanged (`minimapLayout`, checked in
 * `smoke_walk_math.mjs`).
 *   - the 2 km world: the window of [2], 0.24615… px/m against the whole
 *     frame's 0.128 — the zoom the whole point of this is.
 *   - a 400 m world: radius 200, scale 256/400 = 0.64 — and that IS the whole
 *     frame's own scale for it, to the last bit. The cap hands the small world
 *     back exactly as it was framed before.
 *   - a 400 × 100 m world: radius 200 again (the longer axis), scale 0.64 —
 *     the contain fit's scale as well, since the longer axis decides there too.
 *
 * ============================================================================
 * [4] `minimapFollowStepM` + `minimapAnchor(prev, pos, stepM)`
 * ============================================================================
 * The step is a PIXEL budget, `MINIMAP_FOLLOW_STEP_PX` = 0.6 px, turned into
 * metres by the radius: `stepM = 0.6 · 2 · radius / sizePx`.
 *   - radius 520, 160 px -> 0.6 · 1040 / 160 = 3.9 m      (the full sight window)
 *   - radius 200, 160 px -> 0.6 ·  400 / 160 = 1.5 m      (a 400 m world)
 *   - radius   5, 160 px -> 0.6 ·   10 / 160 = 0.0375 m   (the degenerate floor)
 *   - radius  50, 160 px -> 0.375 m — where a fixed 4 m step would have jerked
 *     the picture by 4 · (160/100) = 6.4 px at a time. That is the case this
 *     rule exists for.
 *   - `stepM · scale` is 0.6 px for every one of them — the invariant.
 *
 * `minimapAnchor` keeps the old anchor while the figure is within `stepM` of
 * it, takes a fresh one past that, and hands the SAME OBJECT back in the first
 * case so the publisher's signature can compare it away. With the 3.9 m step:
 *   - no anchor yet, pos (10, 20)                    -> (10, 20)
 *   - anchor (10, 20), pos (13, 20)   distance 3     -> the old one, identically
 *   - anchor (10, 20), pos (14, 20)   distance 4     -> (14, 20)
 *   - THE BOUNDARY, on a 3-4-5 triangle so the distance is exact in binary:
 *     anchor (10, 20), pos (13, 24), distance exactly 5 against a step of 5 ->
 *     the old anchor (the step is the tolerance, not the trigger), and against
 *     a step of 4.999 -> a fresh one
 *   - anchor (10, 20), pos (13, 23)   distance √18 = 4.2426…  -> moves
 *     (the test is a RADIUS, not a per-axis box: 3 m east and 3 m south is
 *     more walking than 3.9 m)
 *   - with the 1.5 m step of a 400 m world, those same 3 m MOVE the window —
 *     the small world follows sooner, which is the pixel budget at work
 *   - anchor (10, 20), pos null (no figure, mode left) -> null
 *
 * ============================================================================
 * [5] The relief rectangle in the window (Task 2 hillshade, moved framing)
 * ============================================================================
 * `Minimap.tsx` draws the shading into the rectangle whose north-west corner
 * is `worldToPx(origin - step/2)` and whose size is `cols · step · scale` —
 * half a step larger on every side, so the smoothed `drawImage` puts the
 * centre of pixel (i, j) back ON the support point. That has to keep holding
 * in the window, where the rectangle is far bigger than the canvas.
 *
 * Field: origin (0, 0), step 100 m, 5 × 5 support points, in the hand window
 * above.
 *     nw = worldToPx(-50, -50) = (103.38461538461539 - 50·s,
 *                                 177.23076923076923 - 50·s)
 *                              = (91.07692307692308, 164.92307692307693)
 *     size = 5 · 100 · s = 8000/65 = 123.07692307692308  (both axes)
 *   - column i centre = nw.px + (i + 0.5)·100·s:
 *       i = 0 -> 91.076923… + 12.307692… = 103.38461538461539 = worldToPx(0).px
 *       i = 4 -> 91.076923… + 110.769230… = 201.84615384615384 = worldToPx(400).px
 *   - row 0 centre = 164.923076… + 12.307692… = 177.23076923076923 =
 *     worldToPx(z = 0).py, and row 4 lands at 275.69… — BIGGER py, i.e.
 *     further down. Row 0 = smallest z = north = TOP. That is the flip that
 *     must not creep in, and [6] proves it would show here.
 *
 * ============================================================================
 * [6] RED counterproofs — mutants that must fail
 * ============================================================================
 * (a) THE Z FLIP. A projection that mirrored the canvas vertically,
 *     py' = sizePx - (offY + z·scale), still puts the avatar at 128 (the
 *     centre is a fixed point of the mirror!) — so the avatar check alone
 *     would not catch it. The point 520 m north lands at 256 instead of 0:
 *     the northern edge at the BOTTOM. Row 0 of the relief goes with it, to
 *     78.769… instead of 177.230…, and the hills are lit from the wrong side
 *     of the map.
 * (b) THE WRONG CENTRE. The same window centred on the world origin instead of
 *     the avatar puts the avatar at (152.61538461538461, 78.76923076923077) —
 *     not the middle, so the figure would drift out of its own map.
 * (c) THE WHOLE-MAP FRAMING. `minimapLayout` over a 2 000 m world gives scale
 *     0.128 px/m against the window's 0.24615…: the very "always the whole
 *     map" the window replaces, and the two must never come out equal.
 */
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

// '../..' = the REPO root (this file lives in client3d/scripts/), the anchor
// every smoke in this directory uses.
const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '../..');
const MINIMAP_TS = join(ROOT, 'client3d/src/game/minimap.ts');
const ENGINE_TS = join(ROOT, 'client3d/src/scene/engine.ts');

/** `minimap.ts` is pure and its only imports are type-only, so a plain esbuild
 *  transpile (a Vite dependency; `tsx` is not installed) is enough to import
 *  it here — the same trick `smoke_walk_math.mjs` uses. */
async function loadMinimap() {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(tmpdir(), 'minimapmath-'));
  try {
    const source = await readFile(MINIMAP_TS, 'utf8');
    const out = esbuild.transformSync(source, { loader: 'ts', format: 'esm' });
    const file = join(dir, 'minimap.mjs');
    await writeFile(file, out.code, 'utf8');
    return await import(`file://${file}`);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

let failed = 0;
let passed = 0;
function check(label, actual, expected, eps = 1e-12) {
  const ok = compare(actual, expected, eps);
  if (ok) {
    passed += 1;
    console.log(`  ok   ${label}`);
  } else {
    failed += 1;
    console.log(`  FAIL ${label}\n       expected ${JSON.stringify(expected)}`
      + `\n       actual   ${JSON.stringify(actual)}`);
  }
}
function compare(a, b, eps) {
  if (a === null || b === null) return a === b;
  if (typeof b === 'number') return typeof a === 'number' && Math.abs(a - b) <= eps;
  if (typeof b === 'object') {
    const keys = Object.keys(b);
    if (typeof a !== 'object' || a === null) return false;
    if (Object.keys(a).length !== keys.length) return false;
    return keys.every((k) => compare(a[k], b[k], eps));
  }
  return a === b;
}
/** A counterproof: the mutant's answer must NOT be the right one. */
function differs(label, mutant, correct, eps = 1e-12) {
  if (!compare(mutant, correct, eps)) {
    passed += 1;
    console.log(`  ok   ${label} (mutant ${JSON.stringify(mutant)} rejected)`);
  } else {
    failed += 1;
    console.log(`  FAIL ${label} — the mutant passes, so the check proves nothing`);
  }
}

const { minimapWindowLayout, minimapView, minimapRadius, minimapFollowStepM,
  minimapAnchor, minimapLayout, worldToPx, MINIMAP_VIEW_RADIUS_M,
  MINIMAP_FOLLOW_STEP_PX, MINIMAP_MIN_SPAN_M, MINIMAP_SIZE_PX } = await loadMinimap();

// --- [1] the radius is the fog's, capped at half the world -----------------
console.log('\n[1] the window radius IS the sight radius of the 3D view');
check('the documented sight radius', MINIMAP_VIEW_RADIUS_M, 520);
check('the documented follow step', MINIMAP_FOLLOW_STEP_PX, 0.6);
const engineSrc = await readFile(ENGINE_TS, 'utf8');
const fogCall = /new THREE\.Fog\(([^)]*)\)/.exec(engineSrc);
check('engine.ts still builds the scene fog', Boolean(fogCall), true);
// The probe is a TEXT read of foreign source, so it has to say when it stopped
// being able to read it at all — "expected 520, actual null" would send the
// next reader looking for a broken map instead of a rewritten fog line.
const fogEnd = fogCall ? Number((fogCall[1].split(',')[2] ?? '').trim()) : NaN;
if (Number.isFinite(fogEnd)) {
  check('…and its FAR end is what the map shows', fogEnd, MINIMAP_VIEW_RADIUS_M);
} else {
  failed += 1;
  console.log('  FAIL the fog end is no longer a number literal in engine.ts —'
    + ' update this coupling probe (and check MINIMAP_VIEW_RADIUS_M by hand)');
}

console.log('\n[1b] …but never wider than half the world');
check('a 2 km world: the sight radius binds',
  minimapRadius({ min_x: -1000, min_z: -1000, max_x: 1000, max_z: 1000 }), 520);
check('a 400 m world: half the world binds',
  minimapRadius({ min_x: -200, min_z: -200, max_x: 200, max_z: 200 }), 200);
check('the LONGER axis is the span',
  minimapRadius({ min_x: 0, min_z: 0, max_x: 400, max_z: 100 }), 200);
check('a 6 m world falls onto the 10 m floor',
  minimapRadius({ min_x: 0, min_z: 0, max_x: 6, max_z: 6 }), MINIMAP_MIN_SPAN_M / 2);
check('ONE placed location (min == max) is caught by the floor, never radius 0',
  minimapRadius({ min_x: 5, min_z: 5, max_x: 5, max_z: 5 }), 5);
check('no bounds at all likewise', minimapRadius(null), 5);
check('…and undefined', minimapRadius(undefined), 5);

// --- [2] the window fit ----------------------------------------------------
console.log('\n[2] the window: one ruler per radius, the avatar in the middle');
const AVATAR = { x: 100, z: -200 };
const W = minimapWindowLayout(AVATAR, 520, 256);
const s = 16 / 65;
check('scale, offX, offY of the hand case', W,
  { scale: s, offX: 128 - 100 * s, offY: 128 + 200 * s });
check('scale is 256 / (2 · 520)', W.scale, 0.24615384615384617, 1e-15);
check('THE AVATAR SITS IN THE MIDDLE', worldToPx(AVATAR, W), { px: 128, py: 128 });
check('520 m north is the top edge', worldToPx({ x: 100, z: -720 }, W),
  { px: 128, py: 0 });
check('520 m east is the right edge', worldToPx({ x: 620, z: -200 }, W),
  { px: 256, py: 128 });
check('520 m south is the bottom edge', worldToPx({ x: 100, z: 320 }, W),
  { px: 128, py: 256 });
check('520 m west is the left edge', worldToPx({ x: -420, z: -200 }, W),
  { px: 0, py: 128 });
check('260 m east is half way to the edge', worldToPx({ x: 360, z: -200 }, W).px, 192);
check('130 m north is a quarter of the way up',
  worldToPx({ x: 100, z: -330 }, W).py, 96);
const far = worldToPx({ x: 1000, z: -200 }, W);
check('a place 900 m east lands off the canvas', far.px, 349.53846153846155, 1e-12);
check('…which is past the edge, so it is simply not drawn', far.px > 256, true);
const W160 = minimapWindowLayout(AVATAR, MINIMAP_VIEW_RADIUS_M, MINIMAP_SIZE_PX);
check('on the real 160 px canvas a metre is 0.15 px', W160.scale, 2 / 13);
check('no figure to centre on -> nothing to draw',
  minimapWindowLayout(null, 520, 256), { scale: 0, offX: 128, offY: 128 });
check('a zero radius likewise', minimapWindowLayout(AVATAR, 0, 256),
  { scale: 0, offX: 128, offY: 128 });

// --- [3] which framing -----------------------------------------------------
console.log('\n[3] embodied = the window, no figure = the whole frame');
const BOUNDS = { min_x: -1000, min_z: -1000, max_x: 1000, max_z: 1000 };
check('a figure on the map is framed by its sight',
  minimapView(AVATAR, BOUNDS, 256), W);
check('no figure falls back to the whole world frame',
  minimapView(null, BOUNDS, 256), minimapLayout(BOUNDS, 256));
check('nothing placed and no figure -> nothing to draw',
  minimapView(null, null, 256), { scale: 0, offX: 128, offY: 128 });
// The cap, at the consumer: a small world must come out with the scale it had
// before the window existed — the window may zoom IN, never out.
const SMALL = { min_x: -200, min_z: -200, max_x: 200, max_z: 200 };
check('a 400 m world is framed at 0.64 px/m', minimapView(AVATAR, SMALL, 256).scale, 0.64);
check('…which is exactly the whole-frame fit it had before',
  minimapView(AVATAR, SMALL, 256).scale, minimapLayout(SMALL, 256).scale);
const FLAT = { min_x: 0, min_z: 0, max_x: 400, max_z: 100 };
check('a 400 x 100 m world too (the longer axis decides on both sides)',
  minimapView(AVATAR, FLAT, 256).scale, minimapLayout(FLAT, 256).scale);
check('the 2 km world is the one that gets zoomed IN',
  minimapView(AVATAR, BOUNDS, 256).scale > minimapLayout(BOUNDS, 256).scale, true);

// --- [4] the follow step and the anchor ------------------------------------
console.log('\n[4] the window follows a PIXEL budget, not a metre one');
const STEP = minimapFollowStepM(520, 160);
check('the full sight window steps 3.9 m', STEP, 3.9, 1e-12);
check('a 400 m world steps 1.5 m', minimapFollowStepM(200, 160), 1.5, 1e-12);
check('the degenerate floor steps 3.75 cm',
  minimapFollowStepM(5, 160), 0.0375, 1e-12);
check('a 100 m world steps 37.5 cm — where 4 m would have been 6.4 px',
  minimapFollowStepM(50, 160), 0.375, 1e-12);
for (const r of [520, 200, 50, 5]) {
  check(`radius ${r}: the step is 0.6 px on the canvas`,
    minimapFollowStepM(r, 160) * minimapWindowLayout({ x: 0, z: 0 }, r, 160).scale,
    MINIMAP_FOLLOW_STEP_PX, 1e-12);
}
check('the canvas edge defaults to the real one',
  minimapFollowStepM(520), minimapFollowStepM(520, MINIMAP_SIZE_PX));

console.log('\n[4b] the anchor moves only past that step');
const A0 = minimapAnchor(null, { x: 10, z: 20 }, STEP);
check('the first position anchors the window', A0, { x: 10, z: 20 });
check('three metres keep the anchor', minimapAnchor(A0, { x: 13, z: 20 }, STEP), A0);
check('…and hand back the very same object',
  minimapAnchor(A0, { x: 13, z: 20 }, STEP) === A0, true);
check('four metres move it', minimapAnchor(A0, { x: 14, z: 20 }, STEP),
  { x: 14, z: 20 });
// The boundary on a 3-4-5 triangle, so the distance is exactly 5 in binary and
// the <= is tested rather than a rounding of it.
check('a distance of exactly the step still keeps the anchor',
  minimapAnchor(A0, { x: 13, z: 24 }, 5) === A0, true);
check('…and a hair more moves it', minimapAnchor(A0, { x: 13, z: 24 }, 4.999),
  { x: 13, z: 24 });
check('the tolerance is a radius, not a box (3 east + 3 south = 4.24 m)',
  minimapAnchor(A0, { x: 13, z: 23 }, STEP), { x: 13, z: 23 });
check('the same 3 m DO move the window of a 400 m world',
  minimapAnchor(A0, { x: 13, z: 20 }, minimapFollowStepM(200, 160)), { x: 13, z: 20 });
check('no figure clears the anchor', minimapAnchor(A0, null, STEP), null);
check('…and so does an undefined position',
  minimapAnchor(A0, undefined, STEP), null);

// --- [5] the relief rectangle in the window --------------------------------
console.log('\n[5] the half-step relief rectangle keeps landing on the support points');
const FIELD = { origin_x: 0, origin_z: 0, step_m: 100, cols: 5, rows: 5 };
const nw = worldToPx({ x: FIELD.origin_x - FIELD.step_m / 2,
  z: FIELD.origin_z - FIELD.step_m / 2 }, W);
const rectW = FIELD.cols * FIELD.step_m * W.scale;
check('the north-west corner of the destination rectangle', nw,
  { px: 91.07692307692308, py: 164.92307692307693 }, 1e-12);
check('its edge length', rectW, 123.07692307692308, 1e-12);
const colCentre = (i) => nw.px + (i + 0.5) / FIELD.cols * rectW;
const rowCentre = (j) => nw.py + (j + 0.5) / FIELD.rows * rectW;
check('column 0 centres on support point x = 0',
  colCentre(0), worldToPx({ x: 0, z: 0 }, W).px);
check('column 4 centres on support point x = 400',
  colCentre(4), worldToPx({ x: 400, z: 0 }, W).px);
check('ROW 0 centres on support point z = 0 (the northernmost line)',
  rowCentre(0), worldToPx({ x: 0, z: 0 }, W).py);
check('row 4 centres on z = 400', rowCentre(4), worldToPx({ x: 0, z: 400 }, W).py);
check('…and lands FURTHER DOWN than row 0', rowCentre(4) > rowCentre(0), true);

// --- [6] the mutants -------------------------------------------------------
console.log('\n[6] red counterproofs — what a wrong projection would give');
const flipped = (p) => ({ px: W.offX + p.x * W.scale,
  py: 256 - (W.offY + p.z * W.scale) });
check('the z flip is invisible on the avatar itself (a fixed point of the mirror)',
  flipped(AVATAR), { px: 128, py: 128 });
differs('the z flip puts the NORTH edge at the bottom',
  flipped({ x: 100, z: -720 }), worldToPx({ x: 100, z: -720 }, W));
check('…at py 256 instead of 0', flipped({ x: 100, z: -720 }).py, 256);
differs('the z flip drags relief row 0 down with it',
  256 - rowCentre(0), rowCentre(0));
check('…to 78.77 instead of 177.23', 256 - rowCentre(0), 78.76923076923077, 1e-12);
const OFF_CENTRE = minimapWindowLayout({ x: 0, z: 0 }, 520, 256);
differs('a window centred anywhere else loses the middle',
  worldToPx(AVATAR, OFF_CENTRE), { px: 128, py: 128 });
check('…the avatar drifts to (152.6, 78.8)', worldToPx(AVATAR, OFF_CENTRE),
  { px: 152.61538461538461, py: 78.76923076923077 }, 1e-12);
differs('the whole-map framing is NOT the window (a 2 km world at 0.128 px/m)',
  minimapLayout(BOUNDS, 256).scale, W.scale);
check('…that being the 0.128 px/m the window replaces',
  minimapLayout(BOUNDS, 256).scale, 0.128);

console.log(`\n${passed + failed} checks, ${failed} failures`);
process.exit(failed ? 1 : 0);
