/**
 * Smoke run for `client3d/src/scene/viewShift.ts` — where the 3D client's
 * camera aims when the HUD's chat window covers part of the picture.
 *
 * Usage:  node client3d/scripts/smoke_view_shift.mjs
 *         (transforms the module with esbuild — a Vite dependency, already
 *          installed; no bundler, no GL context, no server)
 *
 * Every number below is derived BY HAND from the rule, never recorded from the
 * current output.
 *
 * ---------------------------------------------------------------------------
 * THE RULE
 * ---------------------------------------------------------------------------
 * A panel covering [px, pr] x [py, pb] of a W x H canvas leaves four maximal
 * free strips, each running the full length of the other axis:
 *
 *     L = [0, px] x [0, H]    area px·H           centre (px/2, H/2)
 *     R = [pr, W] x [0, H]    area (W−pr)·H       centre ((pr+W)/2, H/2)
 *     T = [0, W] x [0, py]    area W·py           centre (W/2, py/2)
 *     B = [0, W] x [pb, H]    area W·(H−pb)       centre (W/2, (pb+H)/2)
 *
 * The aim point goes to the area-weighted average of the four centres, and the
 * SHIFT is that point minus the middle of the canvas, clamped to ±0.35·W/2
 * horizontally and ±0.35·H/2 vertically. Screen axes: +dx right, +dy DOWN.
 *
 * ---------------------------------------------------------------------------
 * [1] THE DEFAULT PANEL — 840 x 680 on a 1920 x 1080 window
 * ---------------------------------------------------------------------------
 * The stylesheet anchors the panel 12 px from the left and 12 px from the
 * bottom (`hud.css`, `.hud-chat`), so it covers
 *
 *     px = 12   pr = 852   py = 1080 − 12 − 680 = 388   pb = 1068
 *
 *     areas   L = 12·1080     =    12 960     centre (    6, 540)
 *             R = 1068·1080   = 1 153 440     centre ( 1386, 540)
 *             T = 1920·388    =   744 960     centre (  960, 194)
 *             B = 1920·12     =    23 040     centre (  960, 1074)
 *             Σ                = 1 934 400
 *
 *     cx = (12960·6 + 1153440·1386 + 744960·960 + 23040·960) / 1934400
 *        = (77 760 + 1 598 667 840 + 715 161 600 + 22 118 400) / 1934400
 *        = 2 336 025 600 / 1 934 400 = 1207.6228...
 *     cy = (12960·540 + 1153440·540 + 744960·194 + 23040·1074) / 1934400
 *        = (6 998 400 + 622 857 600 + 144 522 240 + 24 744 960) / 1934400
 *        = 799 123 200 / 1 934 400 = 413.11...
 *
 *     dx = 1207.6228 − 960 = 247.6228      dy = 413.1117 − 540 = −126.8883
 *
 * The caps are 0.35·960 = 336 and 0.35·540 = 189; neither binds. So the
 * default window moves the avatar a quarter of a half-width to the right and
 * lifts it an eighth of the picture — visibly out of the corner, nowhere near
 * the edge.
 *
 * ---------------------------------------------------------------------------
 * [2] THE SHAPE DECIDES THE DIRECTION
 * ---------------------------------------------------------------------------
 * With the panel flush in the corner (px = py = 0) the left and bottom strips
 * vanish and only R and T are left:
 *
 *   a) FULL-HEIGHT, half-width — pr = 960, pb = 1080:
 *        R = 960·1080 = 1 036 800, centre (1440, 540); T and B are empty.
 *        centre = (1440, 540) → dx = 480 → CLAMPED to 336, dy = 0.
 *      Nothing is free above it, so the shift is purely sideways.
 *   b) FULL-WIDTH, half-height — pr = 1920, pb = 540, py = 540:
 *        T = 1920·540 = 1 036 800, centre (960, 270); the rest is empty.
 *        centre = (960, 270) → dx = 0, dy = −270 → CLAMPED to −189.
 *      Nothing is free beside it, so the shift is purely upwards.
 *
 * ---------------------------------------------------------------------------
 * [3] THE CAP, AND THE DEGENERATE CASES
 * ---------------------------------------------------------------------------
 * A 1600 x 900 panel at (12, 168) on 1920 x 1080 (pr = 1612, pb = 1068):
 *
 *     L = 12 960 (6, 540)   R = 308·1080 = 332 640 (1766, 540)
 *     T = 1920·168 = 322 560 (960, 84)   B = 23 040 (960, 1074)
 *     Σ = 691 200
 *     cx = (77 760 + 587 442 240 + 309 657 600 + 22 118 400) / 691 200
 *        = 919 296 000 / 691 200 = 1330.0
 *     cy = (6 998 400 + 179 625 600 + 27 095 040 + 24 744 960) / 691 200
 *        = 238 464 000 / 691 200 = 345.0
 *     dx = 370.0 → CLAMPED to 336      dy = −195.0 → CLAMPED to −189
 *
 * A panel that covers the whole canvas leaves Σ = 0: there is nothing to aim
 * beside, and the honest answer is the middle rather than an arbitrary corner.
 * The same answer, NO_SHIFT = {0, 0}, for no panel at all, for a panel of zero
 * width (it covers nothing: pr = px) and for a canvas that has no size yet
 * (w = h = 0, before the first layout).
 *
 * ---------------------------------------------------------------------------
 * [4] A PANEL HANGING OVER THE EDGE IS CLIPPED, NOT TRUSTED
 * ---------------------------------------------------------------------------
 * Mid-animation the panel may report a box that reaches past the bottom edge:
 * 960 x 4000 at (0, 0). Clipped to the canvas it is pb = min(4000, 1080) =
 * 1080 — exactly the full-height panel of [2a] -> dx 336 (capped), dy 0.
 *
 * ---------------------------------------------------------------------------
 * [5] A SMALLER WINDOW SHIFTS LESS
 * ---------------------------------------------------------------------------
 * 520 x 260 (the clamp's floor) at (12, 1080 − 12 − 260 = 808), pr = 532, pb = 1068:
 *
 *     L = 12·1080 = 12 960 (6, 540)     R = 1388·1080 = 1 499 040 (1226, 540)
 *     T = 1920·808 = 1 551 360 (960, 404)   B = 23 040 (960, 1074)
 *     Σ = 3 086 400
 *     cx = (77 760 + 1 837 823 040 + 1 489 305 600 + 22 118 400) / 3 086 400
 *        = 3 349 324 800 / 3 086 400 = 1085.1882...
 *     cy = (6 998 400 + 809 481 600 + 626 749 440 + 24 744 960) / 3 086 400
 *        = 1 467 974 400 / 3 086 400 = 475.6267...
 *     dx = 125.1882      dy = −64.3733
 *
 * The cases (inputs + expectations) live in shared/test-vectors/view_shift.json,
 * shared with the native client's C# tests; each case label starts with the [n]
 * of its derivation above. What stays inline below: the relations ("the cap
 * does not bind", "a smaller window shifts less than the default").
 */
import { readFile, writeFile, mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadVectors, runVectors } from '../../shared/test-vectors/vectors.mjs';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const SRC = join(ROOT, 'client3d/src/scene/viewShift.ts');

/** The module, transformed and imported — it has no imports of its own, so a
 *  single-file transform is enough. esbuild resolves from client3d/, whose
 *  Vite dependency it is. */
async function loadShift() {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(tmpdir(), 'viewshift-smoke-'));
  try {
    const source = await readFile(SRC, 'utf8');
    const out = esbuild.transformSync(source, { loader: 'ts', format: 'esm' });
    const file = join(dir, 'viewShift.mjs');
    await writeFile(file, out.code, 'utf8');
    return await import(`file://${file}`);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

const V = await loadShift();
const vectors = runVectors(loadVectors('view_shift'), { viewShiftFor: V.viewShiftFor });
let passed = vectors.passed;
let failed = vectors.failed;
function check(what, ok) {
  if (ok) { passed += 1; console.log(`  ok   ${what}`); }
  else { failed += 1; console.log(`  FAIL ${what}`); }
}

const W = 1920;
const H = 1080;
console.log('\n(inline) relations');
const def = V.viewShiftFor(W, H, { x: 12, y: 388, w: 840, h: 680 });
check('[1] the cap does not bind horizontally', Math.abs(def.dx) < 0.35 * W / 2);
check('[1] the cap does not bind vertically', Math.abs(def.dy) < 0.35 * H / 2);
const small = V.viewShiftFor(W, H, { x: 12, y: 808, w: 520, h: 260 });
check('[5] a smaller window shifts less than the default', small.dx < def.dx);

console.log(`\n${passed} ok, ${failed} failed`);
process.exit(failed === 0 ? 0 : 1);
