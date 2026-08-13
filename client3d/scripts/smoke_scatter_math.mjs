#!/usr/bin/env node
/**
 * Smoke check for the pure scatter maths: the sampler shared by the 3D client
 * and the map editor (`packages/scene-render/src/scatter.ts`, sections A-E)
 * and the client's display LOD on top of it
 * (`client3d/src/scene/scatterLod.ts`, section F). Two modules, one subject —
 * where a prop stands and how much of it is drawn are the two halves of the
 * same contract, and splitting them over two files would duplicate this
 * harness and let the halves drift apart.
 *
 * Usage:  node client3d/scripts/smoke_scatter_math.mjs
 *
 * Same discipline as `smoke_ground_math.mjs` and `scripts/smoke_scene_recipe.py`:
 * every expected number below is derived BY HAND in this header and NEVER
 * recorded from the current output. A check that only pins today's result
 * proves nothing.
 *
 * NEITHER module has an import (see their headers), so a plain esbuild
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
 * (A8) THE DEFAULT TARGET HEIGHT of a scattered model, 2.0 m (finding 1 of the
 *      E8 acceptance round). A scatter entry without `height_m` no longer
 *      hands `null` in — `client3d/src/scene/ground.ts` passes its
 *      `SCATTER_MODEL_HEIGHT_M`, so "whatever the file says" is never a size
 *      in a world measured in metres. The arithmetic is (A2)'s with a
 *      different target:
 *        a tree exported in CENTIMETRES, minY 0, maxY 0.02:
 *          height 0.02, scale = 2 / 0.02 = 100, offsetY = -0 * 100 = 0
 *          -> the 2 cm speck standing next to the 1.70 m figure becomes 2 m.
 *        a 4 m tree modelled around its centre, minY -2, maxY +2:
 *          height 4, scale = 2 / 4 = 0.5, offsetY = -(-2) * 0.5 = +1
 *          -> box 0 .. 2. The default SHRINKS an oversized prop too.
 *      The constant itself lives in the client (it cannot be imported here —
 *      that module imports three), so its VALUE is pinned separately, see (E).
 *
 * ============================================================================
 * (B) pointInFootprint — the exclusion of finding B18
 * ============================================================================
 * A footprint is a SQUARE of edge `plan_width_m` centred on `pos_x/pos_z` and
 * turned by `yaw_deg` (§ A1.1). The test turns the point into the square's own
 * frame (a rotation by -yaw) and compares against half the edge.
 *
 * (B1) AXIS-ALIGNED, centre (10, 10), edge 4 -> the square runs 8..12 on both
 *      axes.
 *        (10, 10)   centre                      -> inside
 *        (11.9, 8.1) just inside the corner      -> inside
 *        (12.1, 10) 0.1 m past the east edge     -> outside
 *        (10, 7.9)  0.1 m short of the north edge-> outside
 *        (12, 12)   exactly the corner           -> inside (<= half)
 *
 * (B2) TURNED BY 45 deg, centre (0, 0), edge 2 (half 1). The square's corners
 *      now point along the axes at distance sqrt(2) = 1.41421356..., and the
 *      EDGE midpoints sit at distance 1 along the diagonals.
 *        (1.3, 0)      -> inside  (a corner direction; 1.3 < 1.414)
 *        (1.5, 0)      -> outside (past the corner)
 *        (0.8, 0.8)    -> local (via -45 deg): x = 0.8*cos45 + 0.8*sin45
 *                        ... careful, the mapping is
 *                        lx = dx*cos - dz*sin, lz = dx*sin + dz*cos
 *                        with cos = sin = 0.70710678 for yaw 45:
 *                        lx = 0.8*0.7071 - 0.8*0.7071 = 0
 *                        lz = 0.8*0.7071 + 0.8*0.7071 = 1.13137
 *                        |lz| = 1.131 > 1 -> OUTSIDE. The point lies past the
 *                        edge midpoint on the diagonal, which is exactly what
 *                        a turned square does that an axis-aligned box test
 *                        would get wrong.
 *        (0.7, 0.7)    -> lz = 0.98995 <= 1 -> inside.
 *
 * (B3) NOT A SQUARE AT ALL — never blocks anything:
 *        unplaced (pos_x null), edge 0, edge negative, edge missing, NaN
 *        centre. All false, for the centre point itself.
 *
 * (B4) THE ANCHOR IS THE HOISTED FIELD, NOT THE NESTED ONE. The worldmap
 *      payload hoists `plan_width_m` to the top level; the map editor's rows
 *      (`/world/locations`) carry it only inside `map3d`. A row of the second
 *      kind handed in RAW therefore has no edge at all — the review's
 *      critical finding: the editor preview excluded nothing while the client
 *      excluded correctly.
 *        raw editor row {pos 10/10, yaw 0, map3d:{plan_width_m: 4}} at (10,10)
 *          -> FALSE: nothing at the top level, so no square
 *        the ADAPTER shape {pos 10/10, yaw 0, plan_width_m: 4} at (10,10)
 *          -> TRUE, and it is the very square of (B1)
 *      The type makes the first call impossible to write since the review
 *      (every field required); this pins the RUNTIME half of the same rule,
 *      which no type can reach in plain JS.
 *
 * ============================================================================
 * (C) scatterInstances — the sampler, with a HAND-FED random stream
 * ============================================================================
 * The seeded PRNG cannot be simulated on paper, so the checks feed a fixed
 * list of numbers through `rng` and derive the points from the formula:
 *
 *     wanted = min(round(areaM2 / 100 * density), maxPoints)
 *     x   = minX + r * (maxX - minX)
 *     z   = minZ + r * (maxZ - minZ)      (the NEXT number)
 *     yaw = r * 2*pi                       (the NEXT one, ALWAYS drawn)
 *     reject when outside the ring, inside an OCCLUDER or inside a footprint
 *
 * THREE numbers per candidate, drawn before the test even when the candidate
 * is thrown away. That is the point of (C2): every candidate keeps its place
 * in the stream, so a footprint SUBTRACTS the props it covers instead of
 * shifting everything behind it.
 *
 * THE SQUARE: (0,0) (20,0) (20,20) (0,20). Bounds 0..20 on both axes,
 * area 400 m2. With density 25 per 100 m2: wanted = round(400/100 * 25) = 100
 * — too many to write out, so the cases below cap with `maxPoints`.
 *
 * (C1) density 0.5 -> round(4 * 0.5) = 2 wanted. `triesPerPoint` 1 bounds the
 *      loop at 2 candidates, so the stream below is the WHOLE run — with the
 *      default budget the sampler would keep asking for a replacement after
 *      any rejection, which is right in the world and unreadable on paper.
 *      Stream:
 *        0.10, 0.20, 0.50   -> x = 0 + 0.10*20 = 2,  z = 0.20*20 = 4,
 *                              yaw = 0.50 * 2pi = pi, inside the square
 *        0.75, 0.25, 0.00   -> x = 15, z = 5, yaw = 0, inside
 *      -> [ {2, 4, pi}, {15, 5, 0} ]. Six numbers for two points.
 *
 * (C2) THE SAME STREAM with a footprint over the FIRST point: a location at
 *      (2, 4), yaw 0, edge 2 covers 1..3 by 3..5. The first candidate is
 *      inside it and is dropped — but it still cost its three numbers, so the
 *      second candidate is the very same 0.75/0.25/0.00 it was in (C1).
 *      Result: [ {15, 5, 0} ] — (C1) MINUS the covered point, nothing else
 *      moved (same `triesPerPoint` 1, so the two runs are the same two
 *      candidates). That is the whole promise of finding B18: a building clears the
 *      ground it stands on and does not rearrange the wood around it.
 *
 * (C3) A MISS OUTSIDE THE RING. Ring = the LOWER-LEFT TRIANGLE of that square,
 *      (0,0) (20,0) (0,20): area 200 m2, same 0..20 bounding box. With
 *      density 1 -> round(200/100 * 1) = 2 wanted.
 *      Stream 0.90, 0.90, 0.00 -> (18, 18): x + z = 36 > 20, OUTSIDE the
 *        triangle, rejected; the yaw number is spent all the same.
 *      Then 0.10, 0.10, 0.00 -> (2, 2) inside, yaw 0.
 *      Then 0.25, 0.25, 0.50 -> (5, 5) inside, yaw pi.
 *      -> [ {2, 2, 0}, {5, 5, pi} ].
 *
 * (C4) THE TRY BUDGET. Same triangle, wanted 2, `triesPerPoint` 1 -> 2 tries
 *      in total. A stream that misses twice (0.9/0.9 and 0.95/0.95, three
 *      numbers each) gives an EMPTY list instead of looping forever.
 *
 * (C5) NOTHING TO SCATTER: density 0, a negative density, an area of 0, a
 *      two-point "ring" and a density so low that `round` gives 0
 *      (400 m2 at 0.1 per 100 m2 -> round(0.4) = 0) all yield [].
 *
 * (C6) maxPoints CAPS the count: 400 m2 at density 25 wants 100, capped to 3.
 *      Fed with a stream of 9 numbers (three points), it returns exactly 3.
 *
 * (C7) DETERMINISM of the real path (a property, not a recorded value): the
 *      same seed gives an identical list twice, and `scatterSeed` differs per
 *      index, so entry 0 and entry 1 of one area do not stand in the same
 *      spots.
 *
 * ----------------------------------------------------------------------------
 * (C8..C11) OCCLUDERS — only the TOPMOST area of a spot scatters (finding 2 of
 * the E8 acceptance round: a wood painted under a river grew its trees through
 * the water). `areas` arrives bottom to top, so an area's occluders are the
 * cleaned rings after its own index, and the test is the very `pointInRing`
 * even-odd rule the area's own ring uses.
 *
 * THE OCCLUDER SQUARE `OCC_LEFT`: (0,0) (10,0) (10,10) (0,10) — the lower-left
 * quarter of the 20 x 20 sampling square. `OCC_RIGHT`: (12,0) (20,0) (20,10)
 * (12,10).
 *
 * (C8) THE SAME STREAM as (C1) with `OCC_LEFT`. The first candidate (2, 4) is
 *      inside it and is dropped; (15, 5) has x = 15 > 10 and survives. Result
 *      [ {15, 5, 0} ] — (C1) MINUS the covered point, exactly the shape (C2)
 *      has for footprints, and for the same reason: the three numbers were
 *      already drawn.
 *
 * (C9) THE EXISTENCE GUARANTEE. `occluders` absent, `occluders: []`, one
 *      EMPTY ring and `OCC_RIGHT`-far-from-everything must all give (C1)
 *      verbatim — the two points {2,4,pi} and {15,5,0}. An area with nothing
 *      painted over it must not move a single prop.
 *      (`OCC_RIGHT` does cover (15,5), so the "far" ring here is a third
 *      square well outside the stream's points: (30,30) (40,30) (40,40)
 *      (30,40).)
 *
 * (C10) THE EVEN-ODD RULE, on a BOW-TIE occluder
 *       (0,0) (10,10) (10,0) (0,10). Its two lobes meet at (5,5); the notches
 *       above and below that crossing are OUTSIDE by even-odd. Crossings to
 *       the right of the point, at the point's own z:
 *         (2, 5): the diagonal crosses at x = 5 (toggle), the right edge
 *                 x = 10 (toggle), the anti-diagonal at x = 5 (toggle), the
 *                 left edge x = 0 is not to the right -> 3 crossings, INSIDE.
 *         (5, 2): the diagonal crosses at x = 2 (not to the right), the right
 *                 edge x = 10 (toggle), the anti-diagonal at x = 8 (toggle),
 *                 the left edge x = 0 no -> 2 crossings, OUTSIDE.
 *       Stream 0.10, 0.25, 0.00 -> (2, 5) yaw 0   -> occluded, dropped
 *              0.25, 0.10, 0.50 -> (5, 2) yaw pi  -> the notch, kept
 *       -> [ {5, 2, pi} ]. A bounding-box test of the occluder would have
 *       dropped both.
 *
 * (C11) SEVERAL OCCLUDERS: being inside ANY of them is enough. With
 *       [FAR, OCC_RIGHT] on the (C1) stream, (2,4) survives (in neither) and
 *       (15,5) falls to the second ring -> [ {2, 4, pi} ]. The mirror image of
 *       (C8), so a wrong "only the first ring counts" cannot pass both.
 *
 * ============================================================================
 * (D) THE RED COUNTER-CHECK — a mutant that provably fails
 * ============================================================================
 * The cases above are only worth their runtime if a wrong sampler fails them.
 * So the module is transpiled a SECOND time from a mutated source and the same
 * arithmetic is run against it; the check passes when the mutant DISAGREES.
 *
 * THE MUTANT: "draw the yaw only when the candidate is accepted" — the exact
 * shape of the mistake the occluder test invites (test first, draw later).
 * Textually: the `const yaw = rnd() * ...` line is deleted and the yaw is
 * drawn inside `out.push` instead. A rejected candidate then costs TWO numbers
 * instead of three, and the whole stream behind it shifts.
 *
 * ITS DERIVATION, on a case built for it: the (C8) square with `OCC_LEFT`,
 * density 0.5 (wanted 2) and `triesPerPoint` 2 (budget 4 candidates), fed
 *   0.10, 0.20, 0.50,   0.75, 0.25, 0.00,   0.60, 0.80, 0.25
 *   TRUE sampler:  (2,4) occluded (3 numbers spent) | (15,5) yaw 0 kept |
 *                  (0.60,0.80) -> (12,16), x = 12 > 10 and z = 16 > 10, so
 *                  outside OCC_LEFT, yaw = 0.25 * 2pi = pi/2, kept
 *                  -> [ {15,5,0}, {12,16,pi/2} ]
 *   MUTANT:        (2,4) occluded, only TWO numbers spent | the next candidate
 *                  reads 0.50/0.75 -> (10, 15): z = 15 > 10, so outside
 *                  OCC_LEFT, accepted, and only NOW draws its yaw from the
 *                  next number: 0.25 * 2pi = pi/2
 *                  -> its FIRST instance is {10, 15, pi/2}, not {15, 5, 0}
 * The two lists differ in their very first point, and that is what the check
 * asserts (what the mutant does with the rest of the stream is beside the
 * point — it has already lost). The mutant breaks (C2) as well, the
 * footprint's own subtraction: the same property from the other side.
 *
 * ============================================================================
 * (E) THE CLIENT'S SCATTER CONSTANTS
 * ============================================================================
 * `client3d/src/scene/ground.ts` imports three.js and cannot be loaded here,
 * so the three numbers of finding 1+2 are pinned by reading the source: the
 * default target height a model without `height_m` is normalised to
 * (`SCATTER_MODEL_HEIGHT_M` = 2.0, the one (A8) does the arithmetic for) and
 * the built-in tuft's size (`TUFT_HEIGHT_M` = 0.8, `TUFT_RADIUS_M` = 0.22 —
 * hip-high next to a 1.70 m figure instead of knee-high). Without this the
 * arithmetic above would keep passing while the client quietly went back to
 * scale 1.
 *
 * ============================================================================
 * (F) THE DISPLAY LOD — `client3d/src/scene/scatterLod.ts`
 * ============================================================================
 * WHERE an instance stands is (A)-(D) above and belongs to the sampler; HOW
 * MUCH of it is drawn is a second, independent question, and it lives in its
 * own import-free module for exactly the reason this file exists. Its numbers
 * (plan-scatter-lod.md, binding): NEAR = 35 m, FAR = 45 m, CULL = 120 m,
 * MIN_SHARE = 0.25. Every distance is measured to the AREA — the camera's
 * distance to the bounding sphere's centre MINUS its radius — so a camera
 * standing in a wood reads 0 m, and inside a large area it goes negative.
 *
 * (F1) THE TIER WITHOUT A HISTORY — `scatterTierFor(d, 'full')`, the case a
 *      freshly built area is in. Both thresholds are EXCLUSIVE:
 *        d = 0 -> full · 35 -> full · 45 -> full (45 is not > 45)
 *        d = 45.001 -> low · 120 -> low
 *
 * (F2) DEMOTION. A `full` area is only demoted beyond FAR:
 *        40 m -> full (inside the band, nothing changes)
 *        46 m -> low
 *
 * (F3) PROMOTION. A `low` area is only promoted below NEAR:
 *        40 m -> low (the same 40 m, the other answer)
 *        35 m -> low (not < 35)
 *        34.9 m -> full
 *
 * (F4) THE HYSTERESIS IN ONE LINE: at 40 m the answer depends ONLY on what
 *      stands there — `full` stays full, `low` stays low. A rule without a
 *      band cannot produce two answers for one distance, which is what the
 *      red counter-check (F8) turns into a failing case.
 *
 * (F5) A NON-FINITE DISTANCE (a degenerate area, see `ringBounds`) keeps the
 *      current tier — and `scatterCountShare` hides such an area anyway, so
 *      the tier it "keeps" is never drawn.
 *
 * (F6) THE BUDGET — `scatterCountShare(d)`. Flat 1 up to FAR, then a straight
 *      line to MIN_SHARE at CULL, then nothing:
 *        share(d) = 1 - (d - 45)/(120 - 45) * (1 - 0.25)   for 45 < d <= 120
 *        -20 -> 1 (camera inside the area) · 0 -> 1 · 45 -> 1
 *         60 -> 1 - (15/75)*0.75 = 1 - 0.15         = 0.85
 *         82.5 (the midpoint) -> 1 - 0.5*0.75       = 0.625
 *        120 -> 1 - 1*0.75                          = 0.25
 *        120.001 -> 0 · 1000 -> 0 · NaN -> 0
 *      The value AT 120 is the last one still drawn: 0 starts beyond it, which
 *      is the one distance where "thinned out" turns into "gone".
 *
 * (F7) THE INSTANCE COUNT — `scatterVisibleCount(base, d)`, rounded, because
 *      `InstancedMesh.count` is a whole number, and floored at ONE while
 *      anything is drawn at all:
 *        (400,   0) -> 400            (400, 82.5) -> round(250)   = 250
 *        (400, 120) -> round(100) = 100   (400, 121) -> 0
 *        (  3, 118) -> share = 1 - (73/75)*0.75 = 0.27, 3*0.27 = 0.81 -> 1
 *        (  1, 120) -> 0.25 rounds to 0, the floor keeps the lone landmark
 *                      tree at 1 — the budget thins dense scatter, it does not
 *                      erase sparse scatter
 *        (  0,  10) -> 0              nothing placed stays nothing
 *
 * (F8) THE RED COUNTER-CHECKS, both built by mutating the source:
 *      - "either-or, no band": the two hysteresis lines are replaced by
 *        `return distM > SCATTER_TIER_FAR ? 'low' : 'full'`. It answers `full`
 *        at 40 m for an area that stands at `low` — where the truth is `low`
 *        (F3/F4) — so a camera drifting through the band would swap meshes
 *        every tick. Pinned from both sides: the mutant's answer is asserted
 *        to BE 'full' and the true answer is asserted NOT to be.
 *      - "no budget": the linear part is replaced by `return 1`. At 82.5 m it
 *        draws 400 of 400 instead of 250, which is the whole saving gone.
 */
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '../..');
const SRC = join(ROOT, 'packages/scene-render/src/scatter.ts');
const LOD_SRC = join(ROOT, 'client3d/src/scene/scatterLod.ts');
const GROUND_SRC = join(ROOT, 'client3d/src/scene/ground.ts');

/** See the header: neither module has a runtime import, so a transpile is all
 *  it takes. Should someone add one, this fails loudly — that is the alarm.
 *
 *  `mutate` rewrites the SOURCE before the transpile — that is how sections
 *  (D) and (F8) get a wrong module to compare against, without a second copy
 *  of the maths lying around to rot. */
async function loadTs(src, mutate) {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(tmpdir(), 'scattermath-'));
  try {
    const original = await readFile(src, 'utf8');
    const source = mutate ? mutate(original) : original;
    if (mutate && source === original) {
      throw new Error('the mutant changed nothing — the counter-check would be vacuous');
    }
    const out = esbuild.transformSync(source, { loader: 'ts', format: 'esm' });
    const file = join(dir, 'module.mjs');
    await writeFile(file, out.code, 'utf8');
    return await import(`file://${file}`);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

/** Section (D)'s mutant: the yaw is drawn only for an ACCEPTED candidate, so a
 *  rejected one costs two numbers instead of three and shifts everything
 *  behind it. See the header for the derivation. */
function yawOnAcceptance(source) {
  return source
    .replace('    const yaw = rnd() * Math.PI * 2\n', '')
    .replace('out.push({ x, z, yaw })', 'out.push({ x, z, yaw: rnd() * Math.PI * 2 })');
}

/** Section (F8)'s first mutant: ONE threshold instead of a band — the tier no
 *  longer depends on what is already standing, which is precisely the thrash
 *  the hysteresis exists to prevent. */
function dropHysteresis(source) {
  return source.replace(
    `  if (current === 'low' && distM < SCATTER_TIER_NEAR) return 'full';\n`
    + `  if (current === 'full' && distM > SCATTER_TIER_FAR) return 'low';\n`
    + '  return current;\n',
    `  return distM > SCATTER_TIER_FAR ? 'low' : 'full';\n`);
}

/** Section (F8)'s second mutant: the linear part of the budget is gone, so
 *  everything inside the cull distance is drawn in full. */
function dropBudget(source) {
  return source.replace(
    '  const t = (distM - SCATTER_TIER_FAR) / (SCATTER_CULL_FAR - SCATTER_TIER_FAR);\n'
    + '  return 1 - t * (1 - SCATTER_MIN_SHARE);\n',
    '  return 1;\n');
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
/** The other half of a red counter-check: the value the MUTANT produces,
 *  asserted absent. A mutant that agrees means the case pins nothing. */
function checkNot(label, actual, forbidden, eps = 1e-9) {
  const ok = !compare(actual, forbidden, eps);
  if (ok) {
    passed += 1;
    console.log(`  ok   ${label}`);
  } else {
    failed += 1;
    console.log(`  FAIL ${label}\n       this is the value the correct sampler gives`
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

/** A random stream from a fixed list — see section (C). Running past its end
 *  is a broken expectation, not a wrap-around, so it throws. */
function stream(values) {
  let i = 0;
  return () => {
    if (i >= values.length) throw new Error('scatter drew more numbers than the case feeds');
    const v = values[i];
    i += 1;
    return v;
  };
}

async function main() {
  const {
    propGroundFit, pointInFootprint, pointInRing, scatterInstances, scatterSeed,
  } = await loadTs(SRC);

  const TAU = Math.PI * 2;
  const SQUARE = [[0, 0], [20, 0], [20, 20], [0, 20]];
  const TRIANGLE = [[0, 0], [20, 0], [0, 20]];
  // The occluder rings of (C8..C11) — see the header for what each covers.
  const OCC_LEFT = [[0, 0], [10, 0], [10, 10], [0, 10]];
  const OCC_RIGHT = [[12, 0], [20, 0], [20, 10], [12, 10]];
  const OCC_FAR = [[30, 30], [40, 30], [40, 40], [30, 40]];
  const BOWTIE = [[0, 0], [10, 10], [10, 0], [0, 10]];
  // The (C1) stream and the two points it makes — reused by every existence
  // check below, so "nothing moved" is one literal and not four.
  const C1_STREAM = [0.10, 0.20, 0.50, 0.75, 0.25, 0.00];
  const C1_POINTS = [{ x: 2, z: 4, yaw: Math.PI }, { x: 15, z: 5, yaw: 0 }];
  /** The client's `SCATTER_MODEL_HEIGHT_M` (metres), written out by hand and
   *  pinned against the client source in section (E). */
  const DEFAULT_TARGET_H = 2.0;

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
  check('A8 the 2 m default blows a centimetre-sized tree up to 2 m',
    propGroundFit(0, 0.02, DEFAULT_TARGET_H), { scale: 100, offsetY: 0 });
  check('A8 …and SHRINKS an oversized one to the same 2 m',
    propGroundFit(-2, 2, DEFAULT_TARGET_H), { scale: 0.5, offsetY: 1 });

  console.log('\n(B) pointInFootprint — footprints stay clear (B18)');
  const fp = { pos_x: 10, pos_z: 10, yaw_deg: 0, plan_width_m: 4 };
  check('B1 the centre is inside', pointInFootprint(fp, 10, 10), true);
  check('B1 just inside the corner', pointInFootprint(fp, 11.9, 8.1), true);
  check('B1 0.1 m past the east edge', pointInFootprint(fp, 12.1, 10), false);
  check('B1 0.1 m short of the north edge', pointInFootprint(fp, 10, 7.9), false);
  check('B1 exactly the corner counts as inside',
    pointInFootprint(fp, 12, 12), true);
  const turned = { pos_x: 0, pos_z: 0, yaw_deg: 45, plan_width_m: 2 };
  check('B2 1.3 m along a corner direction is inside a 45 deg square',
    pointInFootprint(turned, 1.3, 0), true);
  check('B2 1.5 m is past that corner', pointInFootprint(turned, 1.5, 0), false);
  check('B2 (0.8, 0.8) is past the edge midpoint on the diagonal',
    pointInFootprint(turned, 0.8, 0.8), false);
  check('B2 (0.7, 0.7) is still inside', pointInFootprint(turned, 0.7, 0.7), true);
  check('B3 an unplaced location blocks nothing',
    pointInFootprint({ pos_x: null, pos_z: null, yaw_deg: 0, plan_width_m: 4 }, 0, 0), false);
  check('B3 a zero edge blocks nothing',
    pointInFootprint({ pos_x: 0, pos_z: 0, yaw_deg: 0, plan_width_m: 0 }, 0, 0), false);
  check('B3 a negative edge blocks nothing',
    pointInFootprint({ pos_x: 0, pos_z: 0, yaw_deg: 0, plan_width_m: -5 }, 0, 0), false);
  check('B3 a missing edge blocks nothing',
    pointInFootprint({ pos_x: 0, pos_z: 0 }, 0, 0), false);
  check('B3 a NaN centre blocks nothing',
    pointInFootprint({ pos_x: NaN, pos_z: 0, yaw_deg: 0, plan_width_m: 4 }, 0, 0), false);
  // (B4) — the anchor is the HOISTED field. An editor row handed in raw has
  // its edge only inside `map3d` and is therefore no square at all.
  const rawEditorRow = { pos_x: 10, pos_z: 10, yaw_deg: 0, map3d: { plan_width_m: 4 } };
  check('B4 a nested map3d.plan_width_m is NOT read',
    pointInFootprint(rawEditorRow, 10, 10), false);
  check('B4 …and the adapted row is the very square of (B1)',
    pointInFootprint({
      pos_x: rawEditorRow.pos_x, pos_z: rawEditorRow.pos_z,
      yaw_deg: rawEditorRow.yaw_deg,
      plan_width_m: rawEditorRow.map3d.plan_width_m,
    }, 10, 10), true);
  check('B4 …the same adapted row rejects a point past its edge',
    pointInFootprint({
      pos_x: rawEditorRow.pos_x, pos_z: rawEditorRow.pos_z,
      yaw_deg: rawEditorRow.yaw_deg,
      plan_width_m: rawEditorRow.map3d.plan_width_m,
    }, 12.1, 10), false);

  console.log('\n  pointInRing — the even-odd rule both sides share');
  check('the centre of the square is inside', pointInRing(10, 10, SQUARE), true);
  check('a point outside it is not', pointInRing(25, 10, SQUARE), false);
  check('(18, 18) is outside the lower-left triangle',
    pointInRing(18, 18, TRIANGLE), false);
  check('…and (2, 2) is inside it', pointInRing(2, 2, TRIANGLE), true);

  console.log('\n(C) scatterInstances — the sampler');
  check('C1 two points out of six hand-fed numbers',
    scatterInstances({
      ring: SQUARE, areaM2: 400, densityPer100m2: 0.5, seed: 's',
      triesPerPoint: 1,
      rng: stream(C1_STREAM),
    }),
    C1_POINTS);
  check('C2 a footprint SUBTRACTS the covered point — the rest is (C1) verbatim',
    scatterInstances({
      ring: SQUARE, areaM2: 400, densityPer100m2: 0.5, seed: 's',
      footprints: [{ pos_x: 2, pos_z: 4, yaw_deg: 0, plan_width_m: 2 }],
      triesPerPoint: 1,
      rng: stream(C1_STREAM),
    }),
    [{ x: 15, z: 5, yaw: 0 }]);
  check('C3 a candidate outside the ring costs its three numbers all the same',
    scatterInstances({
      ring: TRIANGLE, areaM2: 200, densityPer100m2: 1, seed: 's',
      rng: stream([0.90, 0.90, 0.00, 0.10, 0.10, 0.00, 0.25, 0.25, 0.50]),
    }),
    [{ x: 2, z: 2, yaw: 0 }, { x: 5, z: 5, yaw: Math.PI }]);
  check('C4 the try budget ends the loop instead of hanging',
    scatterInstances({
      ring: TRIANGLE, areaM2: 200, densityPer100m2: 1, seed: 's',
      triesPerPoint: 1,
      rng: stream([0.90, 0.90, 0.00, 0.95, 0.95, 0.00]),
    }), []);
  check('C5 density 0 scatters nothing',
    scatterInstances({ ring: SQUARE, areaM2: 400, densityPer100m2: 0, seed: 's' }), []);
  check('C5 a negative density scatters nothing',
    scatterInstances({ ring: SQUARE, areaM2: 400, densityPer100m2: -3, seed: 's' }), []);
  check('C5 an area of 0 scatters nothing',
    scatterInstances({ ring: SQUARE, areaM2: 0, densityPer100m2: 5, seed: 's' }), []);
  check('C5 a two-point ring scatters nothing',
    scatterInstances({ ring: [[0, 0], [1, 1]], areaM2: 400, densityPer100m2: 5, seed: 's' }), []);
  check('C5 a density that rounds to zero scatters nothing',
    scatterInstances({ ring: SQUARE, areaM2: 400, densityPer100m2: 0.1, seed: 's' }), []);
  check('C6 maxPoints caps the count at 3',
    scatterInstances({
      ring: SQUARE, areaM2: 400, densityPer100m2: 25, seed: 's', maxPoints: 3,
      rng: stream([0.1, 0.1, 0, 0.2, 0.2, 0.25, 0.3, 0.3, 0.5]),
    }),
    [{ x: 2, z: 2, yaw: 0 }, { x: 4, z: 4, yaw: TAU * 0.25 },
     { x: 6, z: 6, yaw: Math.PI }]);

  console.log('\n  C8..C11 occluders — only the topmost area of a spot scatters');
  check('C8 an area painted OVER this one subtracts the covered point',
    scatterInstances({
      ring: SQUARE, areaM2: 400, densityPer100m2: 0.5, seed: 's',
      occluders: [OCC_LEFT], triesPerPoint: 1, rng: stream(C1_STREAM),
    }),
    [{ x: 15, z: 5, yaw: 0 }]);
  for (const [what, occluders] of [
    ['no occluders at all', undefined],
    ['an empty occluder list', []],
    ['an empty ring', [[]]],
    ['a ring that covers nothing here', [OCC_FAR]],
  ]) {
    check(`C9 ${what} moves not one prop — (C1) verbatim`,
      scatterInstances({
        ring: SQUARE, areaM2: 400, densityPer100m2: 0.5, seed: 's',
        occluders, triesPerPoint: 1, rng: stream(C1_STREAM),
      }),
      C1_POINTS);
  }
  check('C10 the occluder is tested EVEN-ODD: the bow-tie notch is not covered',
    scatterInstances({
      ring: SQUARE, areaM2: 400, densityPer100m2: 0.5, seed: 's',
      occluders: [BOWTIE], triesPerPoint: 1,
      rng: stream([0.10, 0.25, 0.00, 0.25, 0.10, 0.50]),
    }),
    [{ x: 5, z: 2, yaw: Math.PI }]);
  check('C11 lying in ANY occluder is enough — here it is the second',
    scatterInstances({
      ring: SQUARE, areaM2: 400, densityPer100m2: 0.5, seed: 's',
      occluders: [OCC_FAR, OCC_RIGHT], triesPerPoint: 1, rng: stream(C1_STREAM),
    }),
    [{ x: 2, z: 4, yaw: Math.PI }]);

  console.log('\n  C7 determinism of the seeded path (a property, not a record)');
  const opts = { ring: SQUARE, areaM2: 400, densityPer100m2: 2 };
  const a1 = scatterInstances({ ...opts, seed: scatterSeed('ta_1', 0) });
  const a2 = scatterInstances({ ...opts, seed: scatterSeed('ta_1', 0) });
  const b1 = scatterInstances({ ...opts, seed: scatterSeed('ta_1', 1) });
  check('the same seed gives the identical list', a1, a2);
  check('…and it is not empty', a1.length, 8);
  check('a second entry of the same area stands elsewhere',
    JSON.stringify(a1) !== JSON.stringify(b1), true);
  check('the seed is area- and index-stable',
    scatterSeed('ta_1', 2), 'terrain:scatter:ta_1:2');

  console.log('\n(D) the RED counter-check — a mutant that fails these cases');
  const RED = {
    ring: SQUARE, areaM2: 400, densityPer100m2: 0.5, seed: 's',
    occluders: [OCC_LEFT], triesPerPoint: 2,
  };
  const RED_STREAM = [0.10, 0.20, 0.50, 0.75, 0.25, 0.00, 0.60, 0.80, 0.25];
  const RED_TRUE = [{ x: 15, z: 5, yaw: 0 }, { x: 12, z: 16, yaw: TAU * 0.25 }];
  check('D the true sampler drops the covered candidate, the rest keeps its numbers',
    scatterInstances({ ...RED, rng: stream(RED_STREAM) }), RED_TRUE);
  const mutant = await loadTs(SRC, yawOnAcceptance);
  const redMutant = mutant.scatterInstances({ ...RED, rng: stream(RED_STREAM) });
  checkNot('D the mutant "yaw only on acceptance" does NOT reproduce that list',
    redMutant, RED_TRUE);
  check('D …its first instance is the hand-derived shifted one',
    redMutant[0], { x: 10, z: 15, yaw: TAU * 0.25 });
  checkNot('D …and it breaks the footprint subtraction (C2) too',
    mutant.scatterInstances({
      ring: SQUARE, areaM2: 400, densityPer100m2: 0.5, seed: 's',
      footprints: [{ pos_x: 2, pos_z: 4, yaw_deg: 0, plan_width_m: 2 }],
      triesPerPoint: 1, rng: stream(C1_STREAM),
    }),
    [{ x: 15, z: 5, yaw: 0 }]);

  console.log('\n(E) the client\'s scatter constants — pinned by reading the source');
  const groundSrc = await readFile(GROUND_SRC, 'utf8');
  for (const [name, want] of [
    ['SCATTER_MODEL_HEIGHT_M', DEFAULT_TARGET_H],
    ['TUFT_HEIGHT_M', 0.8],
    ['TUFT_RADIUS_M', 0.22],
  ]) {
    const m = new RegExp(`const ${name} = (-?[0-9.]+);`).exec(groundSrc);
    check(`E ground.ts ${name} is ${want} m`, m ? Number(m[1]) : null, want);
  }

  console.log('\n(F) the display LOD — tier hysteresis, budget, instance count');
  const {
    SCATTER_TIER_NEAR, SCATTER_TIER_FAR, SCATTER_CULL_FAR, SCATTER_MIN_SHARE,
    scatterTierFor, scatterCountShare, scatterVisibleCount,
  } = await loadTs(LOD_SRC);
  // The four numbers everything below is derived from — the plan's, and the
  // reason the derivations in the header are arithmetic and not opinion.
  check('F NEAR is 35 m', SCATTER_TIER_NEAR, 35);
  check('F FAR is 45 m', SCATTER_TIER_FAR, 45);
  check('F CULL is 120 m', SCATTER_CULL_FAR, 120);
  check('F the smallest share is a quarter', SCATTER_MIN_SHARE, 0.25);

  // (F1) a fresh area, no history
  check('F1 0 m -> full', scatterTierFor(0, 'full'), 'full');
  check('F1 exactly 35 m -> full', scatterTierFor(35, 'full'), 'full');
  check('F1 exactly 45 m -> full (the threshold is exclusive)',
    scatterTierFor(45, 'full'), 'full');
  check('F1 45.001 m -> low', scatterTierFor(45.001, 'full'), 'low');
  check('F1 120 m -> low', scatterTierFor(120, 'full'), 'low');
  // (F2) demotion
  check('F2 full at 40 m stays full (inside the band)',
    scatterTierFor(40, 'full'), 'full');
  check('F2 full at 46 m -> low', scatterTierFor(46, 'full'), 'low');
  // (F3) promotion
  check('F3 low at 40 m stays low (the same 40 m)',
    scatterTierFor(40, 'low'), 'low');
  check('F3 low at exactly 35 m stays low', scatterTierFor(35, 'low'), 'low');
  check('F3 low at 34.9 m -> full', scatterTierFor(34.9, 'low'), 'full');
  check('F3 low at 0 m -> full', scatterTierFor(0, 'low'), 'full');
  // (F4) the band, both directions from ONE distance
  check('F4 40 m answers differently for the two tiers',
    [scatterTierFor(40, 'full'), scatterTierFor(40, 'low')], ['full', 'low']);
  // (F5) a degenerate area
  check('F5 NaN keeps full', scatterTierFor(NaN, 'full'), 'full');
  check('F5 NaN keeps low', scatterTierFor(NaN, 'low'), 'low');

  // (F6) the budget
  check('F6 share inside the area (-20 m) is 1', scatterCountShare(-20), 1);
  check('F6 share at 0 m is 1', scatterCountShare(0), 1);
  check('F6 share at 45 m is still 1', scatterCountShare(45), 1);
  check('F6 share at 60 m is 0.85', scatterCountShare(60), 0.85);
  check('F6 share at the midpoint 82.5 m is 0.625', scatterCountShare(82.5), 0.625);
  check('F6 share at 120 m is the quarter', scatterCountShare(120), 0.25);
  check('F6 share just past 120 m is 0', scatterCountShare(120.001), 0);
  check('F6 share at 1000 m is 0', scatterCountShare(1000), 0);
  check('F6 share of a NaN distance is 0', scatterCountShare(NaN), 0);

  // (F7) the instance count
  check('F7 400 near -> 400', scatterVisibleCount(400, 0), 400);
  check('F7 400 at 82.5 m -> 250', scatterVisibleCount(400, 82.5), 250);
  check('F7 400 at 120 m -> 100', scatterVisibleCount(400, 120), 100);
  check('F7 400 past the cull -> 0', scatterVisibleCount(400, 121), 0);
  check('F7 3 at 118 m -> 1 (0.81 rounds up)', scatterVisibleCount(3, 118), 1);
  check('F7 the lone tree at 120 m survives', scatterVisibleCount(1, 120), 1);
  check('F7 …but is gone past the cull', scatterVisibleCount(1, 121), 0);
  check('F7 nothing placed stays nothing', scatterVisibleCount(0, 10), 0);

  // (F8) the red counter-checks
  const noBand = await loadTs(LOD_SRC, dropHysteresis);
  check('F8 the "either-or" mutant answers full at 40 m for a low area',
    noBand.scatterTierFor(40, 'low'), 'full');
  checkNot('F8 …which is NOT what the real rule answers there',
    scatterTierFor(40, 'low'), 'full');
  check('F8 …and it flaps: 40 m gives one answer for both tiers',
    [noBand.scatterTierFor(40, 'full'), noBand.scatterTierFor(40, 'low')],
    ['full', 'full']);
  const noBudget = await loadTs(LOD_SRC, dropBudget);
  check('F8 the "no budget" mutant draws all 400 at 82.5 m',
    noBudget.scatterVisibleCount(400, 82.5), 400);
  checkNot('F8 …which is NOT what the real budget draws there',
    scatterVisibleCount(400, 82.5), 400);

  console.log(`\n${passed} ok, ${failed} failed`);
  process.exit(failed ? 1 : 0);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
