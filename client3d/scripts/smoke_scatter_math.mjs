#!/usr/bin/env node
/**
 * Smoke check for the pure scatter maths shared by the 3D client and the map
 * editor — `packages/scene-render/src/scatter.ts`.
 *
 * Usage:  node client3d/scripts/smoke_scatter_math.mjs
 *
 * Same discipline as `smoke_ground_math.mjs` and `scripts/smoke_scene_recipe.py`:
 * every expected number below is derived BY HAND in this header and NEVER
 * recorded from the current output. A check that only pins today's result
 * proves nothing.
 *
 * `scatter.ts` has NO import at all (see its header), so a plain esbuild
 * transpile is enough — no bundler, no stand-ins.
 *
 * ============================================================================
 * (A) propGroundFit — a prop STANDS on the ground (finding B16)
 * ============================================================================
 * A GLB carries whatever origin its author chose; the placeholder cone it
 * replaces is built with its base at y = 0. The fit is arithmetic on the
 * mesh's bounding box:
 *
 *     scale   = targetH / (maxY - minY)      when a target height is asked for
 *     offsetY = -minY * scale
 *
 * so afterwards the box runs from y = 0 to y = targetH.
 *
 * (A1) THE REPORTED CASE. A 2 m tree modelled around its centre:
 *      minY = -1, maxY = +1, no target height.
 *      scale = 1 (nothing asked), offsetY = -(-1) * 1 = +1.
 *      -> the tree rises by exactly the 1 m it used to stand too deep, and
 *         its base sits at 0. Before the fix the offset was 0 and half the
 *         2 m tree was underground — which is the finding, word for word.
 *
 * (A2) THE SAME TREE with height_m = 4:
 *      height = 1 - (-1) = 2, scale = 4/2 = 2,
 *      offsetY = -(-1) * 2 = +2.
 *      -> after scaling the lowest point is at -2, the lift puts it at 0 and
 *         the top at -2 + 2*2 = ... in box terms: min 0, max 4. A 4 m tree.
 *
 * (A3) AN AUTHOR WHO ALREADY PUT THE BASE AT 0: minY = 0, maxY = 3.
 *      scale = 1, offsetY = -0 = 0 -> nothing moves. The fix must not
 *      "correct" a prop that was right.
 *
 * (A4) A PROP HANGING ABOVE ITS ORIGIN: minY = 0.5, maxY = 2.5.
 *      scale = 1, offsetY = -0.5 -> it comes DOWN onto the ground. The rule
 *      is "lowest point at 0", not "lift everything".
 *      With height_m = 1: height = 2, scale = 0.5,
 *      offsetY = -0.5 * 0.5 = -0.25 -> box from 0 to 1.
 *
 * (A5) A FLAT PROP (a decal plane): minY = maxY = 0.7.
 *      height = 0, so no scale is possible however tall the target — scale
 *      stays 1 and offsetY = -0.7 lays it on the ground. An infinite scale
 *      would make it vanish.
 *      Checked with height_m = 3 as well: still scale 1, offsetY -0.7.
 *
 * (A6) JUNK BOX (a geometry with no vertices gives NaN bounds): scale 1,
 *      offsetY 0 — the prop stands where the file put it rather than at NaN,
 *      which would remove every instance from the screen at once.
 *
 * (A7) A target height that is not a height (0, negative, NaN, null) is not a
 *      request: scale stays 1, only the grounding lift applies. Derived from
 *      minY = -1, maxY = 1 -> offsetY = +1 in every one of those cases.
 *
 */
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '../..');
const SRC = join(ROOT, 'packages/scene-render/src/scatter.ts');

/** See the header: the module has no runtime import, so a transpile is all it
 *  takes. Should someone add one, this fails loudly — that is the alarm. */
async function loadScatter() {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(tmpdir(), 'scattermath-'));
  try {
    const source = await readFile(SRC, 'utf8');
    const out = esbuild.transformSync(source, { loader: 'ts', format: 'esm' });
    const file = join(dir, 'scatter.mjs');
    await writeFile(file, out.code, 'utf8');
    return await import(`file://${file}`);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

let failed = 0;
let passed = 0;
function check(label, actual, expected, eps = 1e-9) {
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
  if (Array.isArray(b)) {
    return Array.isArray(a) && a.length === b.length
      && b.every((v, i) => compare(a[i], v, eps));
  }
  if (typeof b === 'object') {
    const keys = Object.keys(b);
    if (typeof a !== 'object' || a === null) return false;
    if (Object.keys(a).length !== keys.length) return false;
    return keys.every((k) => compare(a[k], b[k], eps));
  }
  return a === b;
}

async function main() {
  const { propGroundFit } = await loadScatter();

  console.log('\n(A) propGroundFit — the prop stands on the ground (B16)');
  check('A1 a 2 m tree around its centre rises by exactly 1 m',
    propGroundFit(-1, 1, null), { scale: 1, offsetY: 1 });
  check('A2 …and with height_m 4 it doubles and lifts by 2',
    propGroundFit(-1, 1, 4), { scale: 2, offsetY: 2 });
  check('A3 a prop already based at 0 is not "corrected"',
    propGroundFit(0, 3, null), { scale: 1, offsetY: 0 });
  check('A4 a prop hanging above its origin comes DOWN',
    propGroundFit(0.5, 2.5, null), { scale: 1, offsetY: -0.5 });
  check('A4 …and scales to a 1 m target from there',
    propGroundFit(0.5, 2.5, 1), { scale: 0.5, offsetY: -0.25 });
  check('A5 a flat prop lies on the ground instead of scaling to infinity',
    propGroundFit(0.7, 0.7, null), { scale: 1, offsetY: -0.7 });
  check('A5 …even when a target height is asked for',
    propGroundFit(0.7, 0.7, 3), { scale: 1, offsetY: -0.7 });
  check('A6 a NaN box leaves the prop where the file put it',
    propGroundFit(NaN, NaN, 2), { scale: 1, offsetY: 0 });
  for (const bad of [0, -2, NaN, null, undefined, 'tall']) {
    check(`A7 target height ${JSON.stringify(bad)} is no request — lift only`,
      propGroundFit(-1, 1, bad), { scale: 1, offsetY: 1 });
  }

  console.log(`\n${passed} ok, ${failed} failed`);
  process.exit(failed ? 1 : 0);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
