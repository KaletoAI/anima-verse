#!/usr/bin/env node
/**
 * Smoke check for the two PURE place helpers of the 3D client
 * (`client3d/src/game/placement.ts`): `markerLiftPoint` — WHERE a place
 * marker's storey-0 terrain lift is sampled — and `pickablePlaceFor` — WHICH
 * place a click on a prop mesh opens.
 *
 * Usage:  node client3d/scripts/smoke_place_lift.mjs
 *
 * Like `scripts/smoke_scene_recipe.py` and `smoke_walk_math.mjs`, every
 * expected number below is derived BY HAND from the contract (§ B5a), never
 * recorded from the current output.
 *
 * ==========================================================================
 * [1] markerLiftPoint — ONE PROP, ONE GROUND
 * ==========================================================================
 * The defect it closes (user finding 2026-08-28, the avatar sitting ~40 cm
 * too low on the "Stone bench" above the cliff): a prop stands on the ground
 * under ITS OWN ANCHOR (§ A16.9, `reliftPlacement` samples
 * `models[].anchor`), while the seat marks on it were lifted at the MARKER's
 * own point — the anchor plus the marker offset, decimetres away and, on a
 * slope, at a different height. The seat therefore floated over or sank into
 * the bench by exactly the relief between the two points.
 *
 * The rule: a marker of `source: "prop"` is sampled at its PLACEMENT'S
 * anchor, which the payload now names (`markers[].anchor`, the same `[u, v]`
 * the prop's own spec carries). A room marker has no placement and keeps its
 * own point.
 *
 * Fixture — a bench placed at tile-local (1.0, 2.0), its seat marker offset
 * 0.4 m along +x, i.e. `at_world` (1.4, 2.0), capacity 2 with slots 0.6 m
 * apart across the facing, so slot 0 sits at (1.1, 2.0) and slot 1 at
 * (1.7, 2.0).
 *
 *   markerLiftPoint(at (1.4, 2.0), anchor (1.0, 2.0))  -> (1.0, 2.0)
 *   markerLiftPoint(at (1.4, 2.0), null / undefined)   -> (1.4, 2.0)
 *   a non-finite anchor is NO anchor                   -> (1.4, 2.0)
 *
 * [1b] and what that is worth in metres. Ground `h(x, z) = x` (a 45° slope in
 * x — chosen so the sampled height IS the x coordinate and every number below
 * can be read off the fixture), datum = 0.25:
 *
 *   lift = h(x, z) − datum          (storeyGroundLift, § A16.9, level 0)
 *
 *   at the ANCHOR      x = 1.0 -> 1.00 − 0.25 = 0.75   <- the one right answer
 *   at `at_world`      x = 1.4 -> 1.40 − 0.25 = 1.15   <- the old MOUNT
 *   at slot 0          x = 1.1 -> 1.10 − 0.25 = 0.85   <- the old RE-LIFT
 *
 * Two facts in those three numbers: the seat used to be lifted 0.40 m too
 * high (1.15 vs 0.75), and mount and re-lift disagreed with EACH OTHER by
 * 0.30 m on a bench of capacity > 1, because the mount sampled `at_world` and
 * `reliftScene` sampled `slots[0]`. With one lift point both are 0.75 and
 * `storeyGroundRelift(0.75, …)` moves the seat by delta 0.
 *
 * A DECLARED STOREY is not carried by the terrain at all (§ A16.9): the same
 * marker on level 1 lifts by 0 whatever the ground says.
 *
 * ==========================================================================
 * [2] pickablePlaceFor — the prop IS the click target
 * ==========================================================================
 * Since 2026-08-28 a prop whose markers offer a free slot takes the click
 * itself (rings are left to the places WITHOUT a prop). One prop may carry
 * several places, so the hit point decides: the place whose NEAREST FREE SLOT
 * is closest to it. Distances are plain XZ metres.
 *
 * Fixture — a bench "b1/seat1" with free slots at (0, 0) and (0.6, 0), and a
 * stool "b1/seat2" with one free slot at (2, 0), in that list order.
 *
 *   hit (0.2, 0)  bench min(0.2, 0.4) = 0.2 | stool 1.8   -> "b1/seat1"
 *   hit (1.9, 0)  bench min(1.9, 1.3) = 1.3 | stool 0.1   -> "b1/seat2"
 *   hit (1.3, 0)  bench min(1.3, 0.7) = 0.7 | stool 0.7   -> TIE, and a tie
 *                 falls to the FIRST entry of the list    -> "b1/seat1"
 *                 (this is why the pick needs an epsilon: in binary floats
 *                 (0.6 − 1.3)² = 0.49000000000000010214 and (2 − 1.3)² =
 *                 0.48999999999999993561, so a strict `<` would hand a
 *                 MATHEMATICAL tie to the second entry on noise alone)
 *   hit (0.6, 0.5)  bench min(hypot(0.6, 0.5) = 0.78102496759…,
 *                             0.5) = 0.5
 *                 | stool hypot(1.4, 0.5) = 1.48660687473… -> "b1/seat1"
 *                 (z counts — a hit is a point on the mesh, not an x)
 *   a place with no free slot never wins, and a list in which nobody has one
 *   answers null (total, never a throw — same contract as `slotFor`).
 */
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

// '../..' = the REPO root (this file lives in client3d/scripts/), the anchor
// every smoke script here uses.
const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '../..');

/**
 * Both modules under test are deliberately free of any runtime dependency
 * (no `three`, no DOM, no value import), so a plain esbuild transpile is
 * enough — the same loader `smoke_walk_math.mjs` uses.
 */
async function loadModule(relPath) {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(tmpdir(), 'placelift-'));
  try {
    const source = await readFile(join(ROOT, relPath), 'utf8');
    const out = esbuild.transformSync(source, { loader: 'ts', format: 'esm' });
    const file = join(dir, 'mod.mjs');
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
  if (typeof b === 'object') {
    const keys = Object.keys(b);
    if (typeof a !== 'object' || a === null) return false;
    if (Object.keys(a).length !== keys.length) return false;
    return keys.every((k) => compare(a[k], b[k], eps));
  }
  return a === b;
}

async function main() {
  const placement = await loadModule('client3d/src/game/placement.ts');
  const storeyGround = await loadModule('packages/scene-render/src/storeyGround.ts');
  const { markerLiftPoint, pickablePlaceFor } = placement;
  const { storeyGroundLift, storeyGroundRelift } = storeyGround;

  // --- [1] markerLiftPoint -------------------------------------------------
  console.log('\n[1] markerLiftPoint — a prop marker stands on its prop’s ground');
  const AT = { x: 1.4, z: 2.0 };          // the marker's own point (at_world)
  const ANCHOR = { x: 1.0, z: 2.0 };      // its placement's anchor
  const SLOT0 = { x: 1.1, z: 2.0 };       // slot 0 of the capacity-2 bench
  check('a prop marker is sampled at its placement anchor',
        markerLiftPoint(AT, ANCHOR), { x: 1.0, z: 2.0 });
  check('a room marker (no anchor) keeps its own point',
        markerLiftPoint(AT, null), { x: 1.4, z: 2.0 });
  check('...an absent anchor is the same case',
        markerLiftPoint(AT, undefined), { x: 1.4, z: 2.0 });
  check('a non-finite anchor is no anchor',
        markerLiftPoint(AT, { x: Number.NaN, z: 2.0 }), { x: 1.4, z: 2.0 });
  check('the answer is a COPY — a caller may not edit the payload',
        markerLiftPoint(AT, ANCHOR) !== ANCHOR, true);

  console.log('\n[1b] …and what that is worth on a 45° slope (datum 0.25)');
  const ground = (x) => x;                // h(x, z) = x, see the header
  const datum = 0.25;
  const liftAt = (p) => storeyGroundLift(0, p.x, p.z, datum, ground);
  check('lift at the ANCHOR = 1.00 − 0.25', liftAt(markerLiftPoint(AT, ANCHOR)), 0.75);
  check('the old mount sampled at_world: 1.40 − 0.25', liftAt(AT), 1.15);
  check('...i.e. the seat floated 0.40 m over the bench',
        liftAt(AT) - liftAt(markerLiftPoint(AT, ANCHOR)), 0.4);
  check('the old re-lift sampled slot 0: 1.10 − 0.25', liftAt(SLOT0), 0.85);
  check('...mount and re-lift disagreed by 0.30 m', liftAt(AT) - liftAt(SLOT0), 0.3);
  check('with ONE lift point the re-lift moves nothing',
        storeyGroundRelift(0.75, 0, ANCHOR.x, ANCHOR.z, datum, ground),
        { lift: 0.75, delta: 0 });
  check('a declared storey is not carried by the terrain',
        storeyGroundLift(1, ANCHOR.x, ANCHOR.z, datum, ground), 0);

  // --- [2] pickablePlaceFor ------------------------------------------------
  console.log('\n[2] pickablePlaceFor — which place a click on the prop opens');
  const PLACES = [
    { id: 'b1/seat1', free: [{ x: 0, z: 0 }, { x: 0.6, z: 0 }] },
    { id: 'b1/seat2', free: [{ x: 2, z: 0 }] },
  ];
  check('a hit at the bench end -> the bench',
        pickablePlaceFor({ x: 0.2, z: 0 }, PLACES), 'b1/seat1');
  check('a hit next to the stool -> the stool',
        pickablePlaceFor({ x: 1.9, z: 0 }, PLACES), 'b1/seat2');
  check('a tie falls to the first entry',
        pickablePlaceFor({ x: 1.3, z: 0 }, PLACES), 'b1/seat1');
  check('z counts as much as x',
        pickablePlaceFor({ x: 0.6, z: 0.5 }, PLACES), 'b1/seat1');
  check('a place without a free slot never wins',
        pickablePlaceFor({ x: 2, z: 0 }, [{ id: 'x', free: [] }, PLACES[0]]),
        'b1/seat1');
  check('nobody free -> null',
        pickablePlaceFor({ x: 0, z: 0 }, [{ id: 'x', free: [] }]), null);
  check('an empty list -> null', pickablePlaceFor({ x: 0, z: 0 }, []), null);

  console.log(`\n${passed} ok, ${failed} failed`);
  process.exit(failed ? 1 : 0);
}

main().catch((e) => { console.error(e); process.exit(1); });
