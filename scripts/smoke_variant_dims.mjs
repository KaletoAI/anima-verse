#!/usr/bin/env node
/**
 * Smoke run for the SIZE TRIO of a prop model variant — the pure helper the
 * variant strip redistributes with, `variantRedistribute` in
 * `frontend/src/tabs/props/dims.ts`, plus the `orientedDims` it reads its
 * ratios out of.
 *
 * Usage:  node scripts/smoke_variant_dims.mjs
 *         (bundles the module with esbuild — a Vite dependency, already
 *          installed; no bundler config, no jsdom, no server)
 *
 * Same discipline as the other mjs smokes: every expected number is derived BY
 * HAND below and never recorded from the current output. What is deliberately
 * NOT covered is the React wiring (which chip is selected, when a POST goes
 * out, what the toast says) — that is a rendering question and this file could
 * only record it. The ROUTE is unchanged by this feature and stays with
 * `scripts/smoke_prop_variants.py` [18]: it always took the three keys as one
 * patch, the client just never sent more than one of them at a time.
 *
 * ============================================================================
 * WHY ONE EDIT MOVES ALL THREE
 * ============================================================================
 * A prop is never squeezed on one axis. `place()` in `@anima/scene-render`
 * scales the mesh UNIFORMLY until its largest oriented edge equals
 * `max(width, depth, height)` — the recipe even ships that single number as
 * `max_m`. So the trio carries exactly one degree of freedom (HOW BIG the
 * object is) on top of a fixed aspect (WHAT SHAPE it is). Editing one number
 * on its own resizes nothing; it only makes the other two lie about a mesh
 * that never changed — and, worse, it can hand the maximum to another axis,
 * which DOES change the rendered size in a way nobody typed.
 *
 * Hence: the edited edge is the statement, the other two are recomputed from
 * it, and all three go out in one call. Clearing any one of them clears all
 * three (a two-thirds override matches no aspect ratio) — that half is client
 * wiring, `variantFields.dimsPatch`, and is documented rather than asserted
 * here.
 *
 * ============================================================================
 * (A) THE FACTOR — edited/base, applied to the other two
 * ============================================================================
 * Take the reference box W2 x D1 x H0.5 as the ratio source. Only quotients
 * matter, so the unit of the source is irrelevant:
 *
 *   set HEIGHT 4    factor 4 / 0.5 = 8      -> W 2*8  = 16
 *                                              D 1*8  = 8
 *                                              H         4
 *   set WIDTH 3     factor 3 / 2   = 1.5    -> D 1*1.5  = 1.5
 *                                              H 0.5*1.5 = 0.75
 *   set DEPTH 0.25  factor 0.25/1  = 0.25   -> W 2*0.25  = 0.5
 *                                              H 0.5*0.25 = 0.125
 *   set WIDTH 2     factor 1                -> the box unchanged (2, 1, 0.5)
 *
 * ============================================================================
 * (B) PRECISION — three decimals, the server's own
 * ============================================================================
 * `props._coerce_dim_m` keeps `(0, 100]` rounded to THREE decimals. The
 * followers are written straight to the server (they are never a draft the
 * admin corrects before blur), so they are rounded to exactly that — the field
 * echoes back what was really stored, with no round trip to discover it.
 *
 *   source W1 x D3 x H7,  set HEIGHT 1   factor 1/7 = 0.142857…
 *                                        -> W 1 * 1/7 = 0.142857… -> 0.143
 *                                           D 3 * 1/7 = 0.428571… -> 0.429
 *
 * ============================================================================
 * (C) THE WINDOW — 0.001 m … 100 m, clamped VISIBLY
 * ============================================================================
 * 0.001 m is the smallest number that survives the server's rounding; anything
 * under it becomes zero there, and a zero CLEARS the key instead of storing a
 * size. 100 m is the ceiling the server clamps to. The edited value is clamped
 * BEFORE the factor is taken, so what is stored stays exactly proportional to
 * what was sent:
 *
 *   source W2 x D1 x H0.5,  set HEIGHT 250
 *          -> the edit clamps to 100, factor 100 / 0.5 = 200
 *          -> W 2*200 = 400 -> clamped 100,  D 1*200 = 200 -> clamped 100
 *          = (100, 100, 100): the aspect visibly breaks instead of a 400 m
 *            edge being stored behind the admin's back.
 *   source W2 x D1 x H0.5,  set HEIGHT 0.0004
 *          -> the edit clamps to 0.001, factor 0.001 / 0.5 = 0.002
 *          -> W 2*0.002 = 0.004,  D 1*0.002 = 0.002
 *
 * ============================================================================
 * (D) NO MEANINGFUL ANSWER -> null (the caller writes the edited field alone)
 * ============================================================================
 * A value that is not a positive number is not a size — the strip reads that
 * as "clear the override", never as a redistribution. And a ratio source with
 * a non-positive edge (a mesh box measuring zero on one axis) has no aspect to
 * scale along: multiplying it out would store a zero, i.e. silently clear a
 * key the admin did not touch.
 *
 * ============================================================================
 * (E) WHERE THE RATIOS COME FROM — the VARIANT's box, never the prop's
 * ============================================================================
 * For the chip the preview has open the source is the measured mesh box, run
 * through the prop's orientation fix by `orientedDims` — the same turn every
 * renderer makes. That function returns [width(x), height(y), depth(z)], so
 * the mapping into the trio swaps the last two:
 *
 *   raw box [2, 0.5, 1], no fix        -> W 2,  H 0.5,  D 1
 *   raw box [2, 0.5, 1], 90° about Y   -> x and z trade places: W 1, H 0.5, D 2
 *          (new x = old z, new z = -old x; the y edge is untouched)
 *   and then set HEIGHT 1 on that turned box: factor 1 / 0.5 = 2
 *          -> W 1*2 = 2,  D 2*2 = 4
 *
 * Every other chip has no mesh loaded and the variant payload carries no box,
 * so its ratio source is its own `effective_dims` — the trio it is already
 * rendered by. Those are values, not geometry, so that half needs no check
 * here beyond the arithmetic of (A).
 */
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = fileURLToPath(new URL('..', import.meta.url));
const SRC = join(ROOT, 'frontend/src/tabs/props/dims.ts');

/** Bundled and imported — the module is plain TypeScript with no imports of
 *  its own, but esbuild strips the types and hands back real ESM. */
async function loadBundled(src, prefix) {
  const esbuild = await import('esbuild');
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

let failed = 0;
let passed = 0;
function check(label, actual, expected) {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  if (ok) {
    passed += 1;
    console.log(`  ok   ${label}`);
  } else {
    failed += 1;
    console.log(`  FAIL ${label}\n       expected ${JSON.stringify(expected)}`
      + `\n       actual   ${JSON.stringify(actual)}`);
  }
}

const { variantRedistribute, orientedDims, DIM_KEYS, DIM_MIN_M, DIM_MAX_M } =
  await loadBundled(SRC, 'variantdims-');

/** The trio in one fixed order, so a check reads like the box it describes. */
const trio = (r) => (r === null ? null : [r.width_m, r.depth_m, r.height_m]);

// The reference box of (A): 2 m wide, 1 m deep, 0.5 m high.
const BOX = { width_m: 2, depth_m: 1, height_m: 0.5 };

console.log('\nA   the factor — one edge drives, the other two follow');
check('the three keys are width, depth, height',
  DIM_KEYS, ['width_m', 'depth_m', 'height_m']);
check('height 4 on a 2 x 1 x 0.5 box = factor 8',
  trio(variantRedistribute('height_m', 4, BOX)), [16, 8, 4]);
check('width 3 on the same box = factor 1.5',
  trio(variantRedistribute('width_m', 3, BOX)), [3, 1.5, 0.75]);
check('depth 0.25 = factor 0.25',
  trio(variantRedistribute('depth_m', 0.25, BOX)), [0.5, 0.25, 0.125]);
check('the value it already has changes nothing',
  trio(variantRedistribute('width_m', 2, BOX)), [2, 1, 0.5]);
check('the edited edge is EXACTLY what was typed',
  variantRedistribute('height_m', 4, BOX).height_m, 4);

console.log('\nB   precision — three decimals, the server’s own');
check('height 1 on a 1 x 3 x 7 box gives 1/7 and 3/7 to the millimetre',
  trio(variantRedistribute('height_m', 1, { width_m: 1, depth_m: 3, height_m: 7 })),
  [0.143, 0.429, 1]);

console.log('\nC   the window — 0.001 m … 100 m, clamped visibly');
check('the floor is a millimetre', DIM_MIN_M, 0.001);
check('the ceiling is 100 m', DIM_MAX_M, 100);
check('height 250 clamps the EDIT to 100 first, then the followers',
  trio(variantRedistribute('height_m', 250, BOX)), [100, 100, 100]);
check('height 0.0004 clamps up to the millimetre and scales from there',
  trio(variantRedistribute('height_m', 0.0004, BOX)), [0.004, 0.002, 0.001]);
check('100 m exactly is inside the window',
  variantRedistribute('height_m', 100, BOX).height_m, 100);

console.log('\nD   no meaningful answer -> null');
check('zero is not a size', variantRedistribute('height_m', 0, BOX), null);
check('a negative is not a size', variantRedistribute('height_m', -2, BOX), null);
check('NaN is not a size', variantRedistribute('height_m', NaN, BOX), null);
check('a flat EDITED edge has no factor',
  variantRedistribute('height_m', 4, { width_m: 2, depth_m: 1, height_m: 0 }), null);
check('a flat FOLLOWER edge would store a zero, so nothing is returned',
  variantRedistribute('height_m', 4, { width_m: 0, depth_m: 1, height_m: 0.5 }), null);

console.log('\nE   the ratio source of the SELECTED chip — its own mesh box');
check('an unturned raw box reads [width, height, depth]',
  orientedDims([2, 0.5, 1]), [2, 0.5, 1]);
check('90° about Y trades x and z',
  orientedDims([2, 0.5, 1], { y: 90 }), [1, 0.5, 2]);
{
  // The turned box as the strip maps it: orientedDims -> [w, h, d].
  const [w, h, d] = orientedDims([2, 0.5, 1], { y: 90 });
  check('height 1 on the TURNED box = factor 2 on a 1 x 2 x 0.5 footprint',
    trio(variantRedistribute('height_m', 1,
      { width_m: w, depth_m: d, height_m: h })), [2, 4, 1]);
}

console.log(`\n${failed ? `FAILED (${failed})` : 'all checks passed'}`
  + `  —  ${passed} ok`);
process.exit(failed ? 1 : 0);
