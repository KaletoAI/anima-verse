#!/usr/bin/env node
/**
 * Smoke check for the pure scatter maths: the sampler shared by the 3D client
 * and the map editor (`packages/scene-render/src/scatter.ts`, sections A-E),
 * the client's display LOD on top of it (`client3d/src/scene/scatterLod.ts`,
 * sections F-I) and the three distances the player may set for it
 * (`client3d/src/game/prefs.ts`, section J). Three modules, one subject —
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
 *      The constant is the LAST resort of the precedence in (G), and it is
 *      loaded from `scatterLod.ts` with everything else there.
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
 * so the built-in tuft's size (`TUFT_HEIGHT_M` = 0.8, `TUFT_RADIUS_M` = 0.22 —
 * hip-high next to a 1.70 m figure instead of knee-high, finding 2) is pinned
 * by reading the source. The fallback target height moved to `scatterLod.ts`
 * with the precedence it belongs to and is checked as a value in (G).
 * Without this the arithmetic above would keep passing while the client
 * quietly went back to scale 1.
 *
 * ============================================================================
 * (F) THE DISPLAY LOD — WHERE IT WENT
 * ============================================================================
 * This section used to check the AREA-WIDE half of
 * `client3d/src/scene/scatterLod.ts`: `scatterTierFor` (one mesh tier per
 * painted area), `scatterCountShare` and `scatterVisibleCount` (the tail of a
 * seed-stable list, capped by the area's distance), plus two red mutants for
 * the band and the budget. All three functions are GONE with the caller that
 * asked them — `scene/ground.ts` bins every instance on its own since
 * 2026-08-15 (see the file header and section (I)), so an area no longer has a
 * tier and there is no tail to cap.
 *
 * The rules themselves did not go: (I1)-(I4) below ask the same three
 * questions of ONE prop at ITS OWN distance, with the thresholds handed in
 * rather than read out of module scope. What is unchecked here now — that
 * `ground.ts` fills the two instance buffers from those answers — is not
 * arithmetic and cannot be checked in this file at all: it needs three.js, a
 * scene and a camera.
 *
 * ============================================================================
 * (G) HOW TALL A SCATTERED PROP IS — `scatterTargetH` (finding 12)
 * ============================================================================
 * The height that goes into (A) is a precedence of three, and every step of it
 * is a decision somebody made:
 *
 *   1. `height_m` on the scatter row — someone typed it for THIS ground.
 *   2. `prop_height_m`, the prop's real height from the library, shipped by
 *      `GET /play/terrain` (`app/models/terrain.with_scatter_props`).
 *   3. `SCATTER_MODEL_HEIGHT_M` = 2.0 m — only where there is no prop at all.
 *
 * Before finding 12 step 2 did not exist and step 3 was the default, so an
 * 8.5 m tree from the library was drawn at 2 m: avatar height, which is the
 * screenshot in the finding.
 *
 * (G1) THE AUTHORED HEIGHT WINS: (4, 8.5) -> 4. The author of the area
 *      overrules the library, not the other way round.
 * (G2) THE REPORTED CASE: (undefined, 8.5) -> 8.5, not 2. Nothing authored,
 *      so the tree is as tall as the Props tab says.
 * (G3) NEITHER: (undefined, undefined) -> 2. The flat fallback survives for
 *      the URL no prop record answers for.
 * (G4) "NOT GIVEN" IS EVERY NON-POSITIVE AND EVERY NON-NUMBER, on both
 *      arguments, because both cross a JSON boundary:
 *        (0, 8.5) · (-3, 8.5) · (NaN, 8.5) · (null, 8.5) -> 8.5
 *        (undefined, 0) · (undefined, -1) · (undefined, NaN) -> 2
 *        (NaN, NaN) -> 2, a FINITE answer — a NaN target height would scale
 *        the mesh into a NaN matrix and the prop would vanish, not shrink.
 * (G5) THE RED COUNTER-CHECK, built by mutating the source: the two lines are
 *      swapped, so the prop's height is consulted FIRST. It answers 8.5 for
 *      (4, 8.5) where the truth is 4 — every authored correction in the map
 *      editor would be silently ignored. Pinned from both sides: the mutant's
 *      answer is asserted to BE 8.5 and the true answer NOT to be.
 *
 * ============================================================================
 * (H) HOW FAR ONE PROP BENDS — `scatterSway` (sway factor, 2026-08-14)
 * ============================================================================
 * Two authors, one number (§ A9): the terrain KIND says how hard it blows over
 * this ground (`meta.sway_m`, clamped 0.01..0.5 by the caller), the PROP says
 * how much of that it takes part in (`sway_factor`, 0..1, shipped on the
 * scatter entry by `GET /play/terrain`). The effective amplitude is the
 * product, rounded to two decimals — the precision `applySway` bakes into the
 * shader, and the same test `ground.ts` uses to decide whether the material
 * has to be cloned at all.
 *
 * (H1) THE PLAIN CASE, a meadow at 0.06 m:
 *      factor 1    -> 0.06 * 1    = 0.06   the full amount
 *      factor 0.5  -> 0.06 * 0.5  = 0.03
 *      factor 0.25 -> 0.06 * 0.25 = 0.015  -> rounds to 0.02
 *      A forest at 0.04 with factor 0.5 -> 0.02.
 * (H2) THE POINT OF THE FIELD — the boulder: 0.06 * 0 = 0. Exactly zero, so
 *      the caller's `sway > 0` test fails and the prop keeps the shared,
 *      unpatched material. A stone in a waving meadow stands still.
 * (H3) THE FIELD IS ABSENT for every entry the server ships no factor for (a
 *      tuft, a prop at the default, a foreign URL). undefined/null/NaN and
 *      non-numbers therefore read as 1, NOT as 0 — reading them as "nothing"
 *      would stop the wind in every world that never touched the field:
 *        (0.06, undefined) · (0.06, null) · (0.06, NaN) · (0.06, 'x') -> 0.06
 *      `null` is the case a plain `Number()` gets wrong (`Number(null) === 0`)
 *      and it is the one that hurts, because 0 is a LEGAL factor in this
 *      field: a null on the wire would freeze a whole meadow. Found by this
 *      check, not by reading the code.
 * (H4) OUT OF RANGE IS CLAMPED, as the server clamps it: a hand-edited 5
 *      cannot amplify the wind (0.06 * 1 = 0.06) and a -2 cannot invert it
 *      (0.06 * 0 = 0). And no wind is no wind whatever the factor:
 *        (0, 0.5) · (-1, 1) -> 0
 * (H5) A PRODUCT THAT ROUNDS TO ZERO IS ZERO: 0.04 * 0.1 = 0.004 -> 0.00.
 *      `applySway` refuses anything under SWAY_MIN_M (0.01), so a value that
 *      survives the `> 0` test only to be refused by the shader would buy a
 *      material clone per area that never moves. The rounding is what keeps
 *      the two tests agreeing. Just above the line: 0.06 * 0.1 = 0.006 ->
 *      0.01, which the shader does accept.
 * (H6) THE ONE PLACE IT IS APPLIED. `ground.ts` computes the product ONCE per
 *      scatter entry and everything downstream reads it off `prop.sway`, so
 *      the tier swap keeps the factor. Asserted on the SOURCE, the way (E)
 *      pins the tuft constants: `scatterSway(sway, entry.sway_factor)` occurs
 *      exactly once, `sway: entrySway` is what the ScatterProp carries, and
 *      the bare `applySway(mat, sway,` of the old code is gone.
 * (H7) THE RED COUNTER-CHECK, built by mutating the source: the factor is
 *      ignored and the ground's amplitude handed back unchanged. It answers
 *      0.06 for the boulder (0.06, 0) where the truth is 0 — the stone waves
 *      with the meadow, which is the whole feature undone. Pinned from both
 *      sides.
 *
 * ============================================================================
 * (I) THE LOD PER INSTANCE — `instanceTier` / `instanceVisible` (2026-08-15)
 * ============================================================================
 * (F) asks its three questions ONCE PER AREA, and an area is a wood: with one
 * tier for all of it the tree at the player's feet drops to the cheap mesh
 * because the far edge of the same wood is 100 m away. The rules here are the
 * same three questions asked of ONE prop at ITS OWN distance, with the
 * distances handed in as a `cfg` — which is what lets every case below feed
 * hand-picked numbers instead of borrowing the module's.
 *
 * Two configurations are used throughout:
 *   DEF  = SCATTER_LOD_DEFAULTS = the constants of (F): 35 / 45 / 120
 *   CFG2 = { nearM 10, farM 20, cullM 60 } — nothing to do with the module's
 *          numbers, so a function that ignored its argument fails visibly.
 *
 * (I1) THE MESH BAND, PER INSTANCE. Exactly `scatterTierFor`'s rule (F1-F4),
 *      now with 0 = full, 1 = low and both thresholds still EXCLUSIVE:
 *        DEF, prev low:  0 m -> 0 · 34.9 -> 0 · 35 -> 1 (not < 35)
 *        DEF, prev full: 45 -> 0 (not > 45) · 45.001 -> 1 · 100 -> 1
 *        DEF at 40 m: prev full -> 0, prev low -> 1. ONE distance, two
 *          answers — the band in one line, as in (F4).
 *        CFG2, prev low:  9.9 -> 0 · 10 -> 1
 *        CFG2, prev full: 20 -> 0 · 20.1 -> 1 · at 15 m: full -> 0, low -> 1
 *          The same shape 25 m nearer, which is the proof that the numbers
 *          come from the argument and not from the constants.
 *
 * (I2) THE CULL EDGE, and it is asymmetric on purpose: hidden BEYOND `cullM`,
 *      drawn again only under 0.92 * `cullM` = 110.4 m at the default 120.
 *        DEF: 120 m, prev low -> 1 (120 is still drawn, as in F6)
 *             120.001 -> 2 · 1000 -> 2 · NaN -> 2 for every prev
 *        DEF, prev HIDDEN: 119 -> 2 (inside the cull but not yet under the
 *             re-entry line) · 110.4 -> 2 (not < 110.4) · 110.399 -> 1 · a
 *             teleport to 30 m -> 0
 *        CFG2: 0.92 * 60 = 55.2 -> prev hidden at 55.2 -> 2, at 55 -> 1,
 *             at 60.1 -> 2
 *      THE POINT OF THE FACTOR, as a walk: a camera drifting across the cull
 *      edge, 119.9 / 120.1 / 119.9 / 120.1 / 119.9 / 120.1, starting drawn.
 *      The class changes exactly ONCE (out at the first 120.1) and stays out,
 *      because coming back needs 110.4. Without the factor each crossing
 *      would add and remove the prop again — six times over that walk.
 *
 * (I3) THE SHARE AT THE INSTANCE'S OWN DISTANCE — `instanceShare(d, cfg)`,
 *      the line of (F6) with the cfg's numbers:
 *        share(d) = 1 - (d - farM)/(cullM - farM) * 0.75
 *        DEF:  0 -> 1 · 45 -> 1 · 60 -> 1 - (15/75)*0.75 = 0.85
 *              82.5 -> 0.625 · 105 -> 1 - (60/75)*0.75 = 0.4
 *              120 -> 0.25 · 120.001 -> 0 · NaN -> 0
 *        CFG2: 40 -> 1 - (20/40)*0.75 = 0.625 — the midpoint again, at a
 *              distance where DEF still draws everything.
 *
 * (I4) WHICH instances survive the thinning — `instanceVisible(i, d, cfg)`.
 *      Checked by the PROPERTIES the hash has to guarantee, never by a table
 *      of its outputs: a list of "index 7 is in at 82.5 m" would pin today's
 *      mix and nothing else, while these four are what the feature promises.
 *        - inside `farM` everything is drawn: all 1000 indices at 45 m.
 *        - beyond `cullM` nothing is: 0 of 1000 at 120.001.
 *        - STABLE: the set at 82.5 m built twice is the same set. This is the
 *          whole reason a hash is used instead of "the first n" — the set may
 *          not change while nothing moves.
 *        - MONOTONE: the set at 105 m (share 0.4) is a SUBSET of the set at
 *          60 m (share 0.85). Walking closer only ever ADDS trees, so nothing
 *          pops away in front of the player.
 *        - the COUNT is the share: over 1000 indices, within +-5 % of
 *          1000 * share. 850 at 60 m, 625 at 82.5 m, 400 at 105 m, 250 at
 *          120 m, and 625 again for CFG2 at 40 m.
 *          WHAT THE +-5 % REALLY IS, because "roughly three sigma" stood here
 *          and is wrong: the tolerance is RELATIVE, the binomial spread is
 *          not, so the two drift apart as the share sinks. At n = 1000,
 *          sigma = sqrt(n*p*(1-p)) is 11.3 counts at p = 0.85 against a
 *          tolerance of 42.5 (3.8 sigma), 15.5 at p = 0.4 against 20 (1.3
 *          sigma) and 13.7 at p = 0.25 against 12.5 — 0.9 sigma, TIGHTER than
 *          chance would reliably meet. That is on purpose and it is not a
 *          coin toss: the hash is deterministic, so what these rows pin is
 *          that THIS mix lands inside the band at every one of those shares.
 *          It does, by 10 / 15 / 4 / 8 counts.
 *          THE 0.25 ROW IS THE ONE THAT CHOSE THE HASH. The textbook
 *          `fract(sin(i*12.9898)*43758.5453)` is inside the band at 0.85,
 *          0.625 and even at 0.4 (380, exactly on the 20-count line) — and
 *          draws 215 at 0.25, 35 counts or 2.6 sigma short, 14 % too few
 *          exactly where the thinning has to work. Without this row the whole
 *          table would have accepted the biased mix.
 *        - instance 0 is drawn wherever anything of the entry is (its hash is
 *          0): at 119.9 m it is in, past the cull it is out. That is the
 *          per-instance form of the "floor of ONE" in (F7).
 *
 * (I5) THE RED COUNTER-CHECKS, both built by mutating the source:
 *      - "no band per instance": the two threshold lines are replaced by
 *        `return distM > cfg.farM ? 1 : 0`. It answers FULL at 44.9 m for an
 *        instance that stands at low, where the truth is low, and the flutter
 *        is countable: over the walk 44.9 / 45.1 / 44.9 / 45.1 / 44.9 / 45.1
 *        the mutant changes class 6 times and the real rule 0 times. Every
 *        one of those changes moves a matrix between two instanced buffers.
 *      - "random instead of a hash": `instanceHash` hands back `Math.random()`.
 *        Of the set at 82.5 m built twice, about 0.625 * 0.375 * 1000 = 234
 *        indices are then in the second set that were not in the first —
 *        asserted as "more than 100", which is some ten sigma away from what
 *        a fair coin could produce, while the real set gains 0. That is trees
 *        blinking in and out on every tick with the camera standing still.
 *      - "the textbook mix": `instanceHash` is replaced by
 *        `fract(sin(i*12.9898)*43758.5453)`, the hash that was tried first.
 *        It draws 215 of 1000 at the cull edge where 250 are wanted — 35
 *        counts outside the band the real mix holds by 8 — and it is asserted
 *        to pass at share 0.4 all the same, which is why the 0.25 row of (I4)
 *        and not the rest of that table is what chose the hash.
 *
 * ============================================================================
 * (J) THE DETAIL DISTANCES AS A SETTING — `client3d/src/game/prefs.ts`
 * ============================================================================
 * The three distances are a LOCAL view setting (localStorage), so the same
 * contract as the audio prefs applies: never throw, never return half a
 * setting, fall back field by field. Two rules are its own.
 *
 * (J1) THE DEFAULTS ARE THE MODULE'S. `DEFAULT_SCATTER_PREFS` is 35/45/120,
 *      written out because `prefs.ts` has no imports — so the check loads BOTH
 *      modules and compares the values, and a change to one alone goes red.
 *      The key is its own and versioned: `av3d.view.scatter.v1`, NOT the audio
 *      key `av3d.audio.v1`, which a display setting has no business in.
 *
 * (J2) READING. null / unparsable / a JSON non-object -> the defaults. A field
 *      is taken only if it is a finite NUMBER ("45" is not, NaN is not), and
 *      what is taken is CLAMPED to 5..2000 m rather than refused:
 *        {"scatterNearM":3}     -> 5 (and 5 < 45 < 120 still climbs -> taken)
 *        {"scatterCullM":5000}  -> 2000
 *        {"scatterFarM":"50"}   -> the default 45
 *      But the triple only means anything TOGETHER, so an unordered one falls
 *      back completely instead of field by field:
 *        {"scatterNearM":100}   -> 100 < 45 is false -> all three defaults
 *      Round trip: `loadScatterPrefs(saveScatterPrefs(p))` returns `p`.
 *
 * (J3) TYPING. `checkScatterPrefs(near, far, cull)` is what the menu asks
 *      before it stores anything:
 *        (20, 40, 300)      -> ok, taken as typed
 *        (3, 10, 50)        -> ok, the 3 clamped up to 5
 *        (40, 20, 300)      -> refused, 'order' — near is not under far
 *        (20, 40, 40)       -> refused, 'order' — equal is not ordered either
 *        (NaN, 45, 120)     -> refused, 'number' (an empty number field)
 *        ('30', 45, 120)    -> refused, 'number' (a string is not a number)
 *        (2500, 3000, 4000) -> refused, 'order': all three clamp to 2000 and
 *                              collide there, which is better told to the
 *                              player than silently drawn.
 *
 * (J4) THE TWO SIDES MEET. `scatterLodCfgOf` renames the stored fields into
 *      the cfg the maths takes, so a setting of 20/40/300 must produce exactly
 *      that behaviour end to end:
 *        19 m, prev low  -> 0 (full)      41 m, prev full -> 1 (low)
 *        301 m           -> 2 (hidden)   share(160) = 1 - (120/260)*0.75
 *                                                   = 0.653846153...
 */
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '../..');
const SRC = join(ROOT, 'packages/scene-render/src/scatter.ts');
const LOD_SRC = join(ROOT, 'client3d/src/scene/scatterLod.ts');
const GROUND_SRC = join(ROOT, 'client3d/src/scene/ground.ts');
const PREFS_SRC = join(ROOT, 'client3d/src/game/prefs.ts');

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

/** Section (G5)'s mutant: the precedence is turned around — the prop's library
 *  height is consulted before the height authored on the row, so an author who
 *  corrects one area's trees is overruled by the library. */
function swapHeightPrecedence(source) {
  return source.replace(
    '  if (Number(entryH) > 0) return Number(entryH);\n'
    + '  if (Number(propH) > 0) return Number(propH);\n',
    '  if (Number(propH) > 0) return Number(propH);\n'
    + '  if (Number(entryH) > 0) return Number(entryH);\n');
}

/** Section (H7)'s mutant: the prop's factor is ignored and the ground's
 *  amplitude is handed back as it came — the state of the code before the
 *  factor existed, where every prop of a waving area waves. */
function ignoreSwayFactor(source) {
  return source.replace(
    '  return Math.round(base * clamped * 100) / 100;\n',
    '  return Math.round(base * 100) / 100;\n');
}

/** Section (I5)'s third mutant: the textbook `fract(sin(i*12.9898)*43758.5453)`
 *  in place of the murmur3 finaliser — the mix that WAS tried first, and the
 *  one the 0.25 row of (I4) rejected. */
function sinInsteadOfMurmur(source) {
  return source.replace(
    '  let h = Math.imul(index | 0, 2654435761) >>> 0;\n'
    + '  h = Math.imul(h ^ (h >>> 15), 2246822507);\n'
    + '  h = Math.imul(h ^ (h >>> 13), 3266489909);\n'
    + '  h ^= h >>> 16;\n'
    + '  return (h >>> 0) / 4294967296;\n',
    '  const v = Math.sin(index * 12.9898) * 43758.5453;\n'
    + '  return v - Math.floor(v);\n');
}

/** Section (I5)'s first mutant: the per-instance band is gone, so an instance
 *  in the 35…45 m band no longer keeps the tier it has — the very thrash the
 *  band exists to prevent, now once per prop instead of once per area. */
function dropInstanceBand(source) {
  return source.replace(
    '  if (distM < cfg.nearM) return 0;\n'
    + '  if (distM > cfg.farM) return 1;\n'
    + '  return held;\n',
    '  return distM > cfg.farM ? 1 : 0;\n');
}

/** Section (I5)'s second mutant: the index hash is replaced by chance. Each
 *  tick draws a NEW set of survivors, which is the flickering wood the stable
 *  hash exists to prevent. */
function randomInsteadOfHash(source) {
  return source.replace(
    '  let h = Math.imul(index | 0, 2654435761) >>> 0;\n'
    + '  h = Math.imul(h ^ (h >>> 15), 2246822507);\n'
    + '  h = Math.imul(h ^ (h >>> 13), 3266489909);\n'
    + '  h ^= h >>> 16;\n'
    + '  return (h >>> 0) / 4294967296;\n',
    '  return Math.random();\n');
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
    ['TUFT_HEIGHT_M', 0.8],
    ['TUFT_RADIUS_M', 0.22],
  ]) {
    const m = new RegExp(`const ${name} = (-?[0-9.]+);`).exec(groundSrc);
    check(`E ground.ts ${name} is ${want} m`, m ? Number(m[1]) : null, want);
  }

  // The constants of the LOD, which section (I) derives its expectations from.
  // Loaded here because (G) and (H) below read the same module.
  const {
    SCATTER_TIER_NEAR, SCATTER_TIER_FAR, SCATTER_CULL_FAR, SCATTER_MIN_SHARE,
    SCATTER_MODEL_HEIGHT_M, scatterTargetH,
    SCATTER_SWAY_FACTOR_DEFAULT, scatterSway,
  } = await loadTs(LOD_SRC);
  console.log('\n(F) the display LOD — the four numbers everything is derived from');
  check('F NEAR is 35 m', SCATTER_TIER_NEAR, 35);
  check('F FAR is 45 m', SCATTER_TIER_FAR, 45);
  check('F CULL is 120 m', SCATTER_CULL_FAR, 120);
  check('F the smallest share is a quarter', SCATTER_MIN_SHARE, 0.25);

  console.log('\n(G) how tall a scattered prop is — the precedence of finding 12');
  // The fallback of (A8) and step 3 of the precedence are the same number.
  check('G the flat fallback is 2 m', SCATTER_MODEL_HEIGHT_M, DEFAULT_TARGET_H);
  // (G1) the authored height wins
  check('G1 an authored 4 m beats the library\'s 8.5 m',
    scatterTargetH(4, 8.5), 4);
  // (G2) the reported case
  check('G2 nothing authored -> the library\'s 8.5 m, not 2 m',
    scatterTargetH(undefined, 8.5), 8.5);
  // (G3) neither
  check('G3 no prop at all -> the flat 2 m',
    scatterTargetH(undefined, undefined), 2);
  // (G4) "not given" on both arguments
  // `JSON.stringify(NaN)` is "null", so the labels are written out — two
  // cases that read the same in the log are one case as far as a reader is
  // concerned.
  for (const [bad, name] of [[0, '0'], [-3, '-3'], [NaN, 'NaN'], [null, 'null']]) {
    check(`G4 an entry height of ${name} is no request`,
      scatterTargetH(bad, 8.5), 8.5);
  }
  for (const [bad, name] of [[0, '0'], [-1, '-1'], [NaN, 'NaN'], [null, 'null']]) {
    check(`G4 a prop height of ${name} is no answer`,
      scatterTargetH(undefined, bad), 2);
  }
  check('G4 NaN on both sides still yields a FINITE height',
    scatterTargetH(NaN, NaN), 2);
  // (G5) the red counter-check
  const swapped = await loadTs(LOD_SRC, swapHeightPrecedence);
  check('G5 the "library first" mutant answers 8.5 m for an authored 4 m',
    swapped.scatterTargetH(4, 8.5), 8.5);
  checkNot('G5 …which is NOT what the real precedence answers',
    scatterTargetH(4, 8.5), 8.5);

  console.log('\n(H) the wind factor — kind × prop, the one effective amplitude');
  check('H an absent factor means the FULL amount', SCATTER_SWAY_FACTOR_DEFAULT, 1);
  // (H1) the plain products
  check('H1 a 0.06 m meadow at factor 1 bends 0.06 m', scatterSway(0.06, 1), 0.06);
  check('H1 …at 0.5 half as far', scatterSway(0.06, 0.5), 0.03);
  check('H1 …at 0.25 -> 0.015, rounded to 0.02', scatterSway(0.06, 0.25), 0.02);
  check('H1 a 0.04 m forest at 0.5 -> 0.02', scatterSway(0.04, 0.5), 0.02);
  // (H2) the boulder — the reason the field exists
  check('H2 factor 0 is EXACTLY 0, so no material is ever cloned',
    scatterSway(0.06, 0), 0);
  // (H3) no factor is not "no wind"
  for (const [bad, name] of [[undefined, 'undefined'], [null, 'null'],
    [NaN, 'NaN'], ['x', 'a string']]) {
    check(`H3 ${name} reads as the full amount, not as nothing`,
      scatterSway(0.06, bad), 0.06);
  }
  // (H4) the clamp, both ends, and a ground with no wind at all
  check('H4 a hand-edited 5 cannot amplify the wind', scatterSway(0.06, 5), 0.06);
  check('H4 a hand-edited -2 cannot invert it', scatterSway(0.06, -2), 0);
  check('H4 no wind stays no wind however willing the prop',
    scatterSway(0, 0.5), 0);
  check('H4 …and a negative amplitude is no wind either', scatterSway(-1, 1), 0);
  // (H5) the rounding is the shader's own threshold
  check('H5 0.04 * 0.1 = 0.004 -> 0, below what applySway would accept',
    scatterSway(0.04, 0.1), 0);
  check('H5 0.06 * 0.1 = 0.006 -> 0.01, the smallest amplitude there is',
    scatterSway(0.06, 0.1), 0.01);
  // (H6) THE one place — asserted on ground.ts, like (E)
  const swayCalls = groundSrc.match(/scatterSway\(sway, entry\.sway_factor\)/g);
  check('H6 ground.ts multiplies in exactly ONE place',
    swayCalls ? swayCalls.length : 0, 1);
  check('H6 …and that product is what the ScatterProp carries',
    groundSrc.includes('sway: entrySway,'), true);
  check('H6 …the tuft bends by it too, not by the area\'s raw amplitude',
    groundSrc.includes('applySway(mat, entrySway, h);'), true);
  check('H6 no caller passes the unfactored amplitude any more',
    groundSrc.includes('applySway(mat, sway,'), false);
  // (H7) the red counter-check
  const noFactor = await loadTs(LOD_SRC, ignoreSwayFactor);
  check('H7 the "ignore the factor" mutant bends the boulder by 0.06 m',
    noFactor.scatterSway(0.06, 0), 0.06);
  checkNot('H7 …which is NOT what the real product answers',
    scatterSway(0.06, 0), 0.06);

  console.log('\n(I) the LOD per instance — band, cull edge, stable thinning');
  const {
    SCATTER_LOD_DEFAULTS, SCATTER_UNHIDE_FACTOR,
    instanceTier, instanceShare, instanceVisible,
  } = await loadTs(LOD_SRC);
  const DEF = SCATTER_LOD_DEFAULTS;
  // A configuration that shares no number with the module's, so a function
  // reading the constants instead of its argument cannot pass (I1)/(I2).
  const CFG2 = { nearM: 10, farM: 20, cullM: 60 };
  /** Which of the first `n` instances are drawn at that distance. */
  const drawn = (visible, d, cfg, n = 1000) => {
    const out = [];
    for (let i = 0; i < n; i += 1) if (visible(i, d, cfg)) out.push(i);
    return out;
  };
  /** How often the class CHANGES along a walk — the number the hysteresis is
   *  there to keep down, and what a buffer refill costs. */
  const swaps = (tier, prev, dists, cfg) => {
    let cur = prev;
    let n = 0;
    for (const d of dists) {
      const next = tier(d, cur, cfg);
      if (next !== cur) n += 1;
      cur = next;
    }
    return n;
  };

  check('I the defaults are the constants of (F)',
    [DEF.nearM, DEF.farM, DEF.cullM], [35, 45, 120]);
  check('I an instance re-appears at 0.92 of the cull distance',
    SCATTER_UNHIDE_FACTOR, 0.92);

  // (I1) the mesh band, per instance
  check('I1 a low instance at 0 m -> full', instanceTier(0, 1, DEF), 0);
  check('I1 a low instance at 34.9 m -> full', instanceTier(34.9, 1, DEF), 0);
  check('I1 …but at exactly 35 m it stays low', instanceTier(35, 1, DEF), 1);
  check('I1 a full instance at exactly 45 m stays full',
    instanceTier(45, 0, DEF), 0);
  check('I1 …at 45.001 m it drops to low', instanceTier(45.001, 0, DEF), 1);
  check('I1 …and at 100 m it is low', instanceTier(100, 0, DEF), 1);
  check('I1 40 m answers differently for the two tiers',
    [instanceTier(40, 0, DEF), instanceTier(40, 1, DEF)], [0, 1]);
  check('I1 CFG2 promotes at its own 10 m, not at 35',
    [instanceTier(9.9, 1, CFG2), instanceTier(10, 1, CFG2)], [0, 1]);
  check('I1 …demotes at its own 20 m, not at 45',
    [instanceTier(20, 0, CFG2), instanceTier(20.1, 0, CFG2)], [0, 1]);
  check('I1 …and holds its own band at 15 m',
    [instanceTier(15, 0, CFG2), instanceTier(15, 1, CFG2)], [0, 1]);

  // (I2) the cull edge and the way back
  check('I2 120 m is still drawn', instanceTier(120, 1, DEF), 1);
  check('I2 120.001 m is hidden', instanceTier(120.001, 1, DEF), 2);
  check('I2 1000 m is hidden', instanceTier(1000, 0, DEF), 2);
  check('I2 a NaN distance hides, whatever stood there',
    [instanceTier(NaN, 0, DEF), instanceTier(NaN, 1, DEF), instanceTier(NaN, 2, DEF)],
    [2, 2, 2]);
  check('I2 a hidden instance at 119 m stays hidden', instanceTier(119, 2, DEF), 2);
  check('I2 …at exactly 110.4 m too (the line is exclusive)',
    instanceTier(110.4, 2, DEF), 2);
  check('I2 …and comes back as LOW just under it',
    instanceTier(110.399, 2, DEF), 1);
  check('I2 …or as full if it re-appears inside the near distance',
    instanceTier(30, 2, DEF), 0);
  check('I2 CFG2 re-appears under its own 55.2 m',
    [instanceTier(55.2, 2, CFG2), instanceTier(55, 2, CFG2),
      instanceTier(60.1, 2, CFG2)],
    [2, 1, 2]);
  check('I2 drifting across the cull edge costs ONE change, not six',
    swaps(instanceTier, 1, [119.9, 120.1, 119.9, 120.1, 119.9, 120.1], DEF), 1);

  // (I3) the share at the instance's own distance
  check('I3 share at 0 m is 1', instanceShare(0, DEF), 1);
  check('I3 share at 45 m is still 1', instanceShare(45, DEF), 1);
  check('I3 share at 60 m is 0.85', instanceShare(60, DEF), 0.85);
  check('I3 share at 82.5 m is 0.625', instanceShare(82.5, DEF), 0.625);
  check('I3 share at 105 m is 0.4', instanceShare(105, DEF), 0.4);
  check('I3 share at 120 m is the quarter', instanceShare(120, DEF), 0.25);
  check('I3 share past the cull is 0', instanceShare(120.001, DEF), 0);
  check('I3 share of a NaN distance is 0', instanceShare(NaN, DEF), 0);
  check('I3 CFG2 is at its midpoint 0.625 where DEF still draws everything',
    [instanceShare(40, CFG2), instanceShare(40, DEF)], [0.625, 1]);

  // (I4) which instances survive — properties, never a table of hashes
  check('I4 inside the far distance every instance is drawn',
    drawn(instanceVisible, 45, DEF).length, 1000);
  check('I4 past the cull distance none is',
    drawn(instanceVisible, 120.001, DEF).length, 0);
  check('I4 the set at 82.5 m is the SAME set when asked again',
    drawn(instanceVisible, 82.5, DEF), drawn(instanceVisible, 82.5, DEF));
  const near60 = new Set(drawn(instanceVisible, 60, DEF));
  const far105 = drawn(instanceVisible, 105, DEF);
  check('I4 what is drawn at 105 m is still drawn at 60 m (nothing pops away)',
    far105.filter((i) => !near60.has(i)).length, 0);
  for (const [d, cfg, share, label] of [
    [60, DEF, 0.85, 'DEF at 60 m'], [82.5, DEF, 0.625, 'DEF at 82.5 m'],
    [105, DEF, 0.4, 'DEF at 105 m'],
    // THE ROW THAT CHOSE THE HASH — the cull edge, where the share is at its
    // smallest and the tolerance at its tightest (0.9 sigma). The mix in use
    // draws 258 of the ideal 250; the textbook sin-hash draws 215 and fails
    // here alone. See (I4) in the header for the whole derivation.
    [120, DEF, 0.25, 'DEF at 120 m'],
    [40, CFG2, 0.625, 'CFG2 at 40 m'],
  ]) {
    const n = drawn(instanceVisible, d, cfg).length;
    check(`I4 ${label} draws ${1000 * share} of 1000, within 5 % (got ${n})`,
      Math.abs(n - 1000 * share) <= 0.05 * 1000 * share, true);
  }
  check('I4 instance 0 survives as long as anything of the entry does',
    [instanceVisible(0, 119.9, DEF), instanceVisible(0, 120.001, DEF)],
    [true, false]);

  // (I5) the red counter-checks
  const noInstanceBand = await loadTs(LOD_SRC, dropInstanceBand);
  check('I5 the "no band" mutant answers full at 44.9 m for a low instance',
    noInstanceBand.instanceTier(44.9, 1, DEF), 0);
  checkNot('I5 …which is NOT what the real rule answers there',
    instanceTier(44.9, 1, DEF), 0);
  const FLUTTER = [44.9, 45.1, 44.9, 45.1, 44.9, 45.1];
  check('I5 …and it swaps mesh 6 times over a walk across 45 m',
    swaps(noInstanceBand.instanceTier, 1, FLUTTER, DEF), 6);
  check('I5 …where the real rule swaps none',
    swaps(instanceTier, 1, FLUTTER, DEF), 0);
  const rolledHash = await loadTs(LOD_SRC, randomInsteadOfHash);
  const rolledA = new Set(drawn(rolledHash.instanceVisible, 82.5, DEF));
  const rolledB = drawn(rolledHash.instanceVisible, 82.5, DEF);
  const churn = rolledB.filter((i) => !rolledA.has(i)).length;
  check(`I5 the "random" mutant reshuffles the set between two ticks (${churn})`,
    churn > 100, true);
  // …and the mix that was tried FIRST, pinned from both sides: at the cull
  // edge it draws 215 where 250 are wanted, 35 counts outside the +-12.5 the
  // real mix holds — while at 0.4 it would still have passed (380 against a
  // 20-count line). One row apart, one hash chosen.
  const sinHash = await loadTs(LOD_SRC, sinInsteadOfMurmur);
  const sinAt120 = drawn(sinHash.instanceVisible, 120, DEF).length;
  check('I5 the textbook sin-hash draws 215 of 1000 at the cull edge',
    sinAt120, 215);
  check('I5 …which is outside the band the real mix keeps',
    Math.abs(sinAt120 - 250) > 12.5, true);
  check('I5 …while at share 0.4 it would have passed unnoticed',
    Math.abs(drawn(sinHash.instanceVisible, 105, DEF).length - 400) <= 20, true);

  console.log('\n(J) the detail distances as a local setting — prefs.ts');
  const {
    SCATTER_PREFS_KEY, SCATTER_PREF_MIN_M, SCATTER_PREF_MAX_M,
    DEFAULT_SCATTER_PREFS, checkScatterPrefs, loadScatterPrefs,
    saveScatterPrefs, scatterLodCfgOf,
  } = await loadTs(PREFS_SRC);
  const PREF_DEFAULTS = {
    scatterNearM: 35, scatterFarM: 45, scatterCullM: 120,
  };

  // (J1) the same three numbers on both sides, and a key of its own
  check('J1 the stored defaults are 35 / 45 / 120', DEFAULT_SCATTER_PREFS,
    PREF_DEFAULTS);
  check('J1 …which is exactly SCATTER_LOD_DEFAULTS',
    scatterLodCfgOf(DEFAULT_SCATTER_PREFS), DEF);
  check('J1 the store key is its own, not the audio one',
    SCATTER_PREFS_KEY, 'av3d.view.scatter.v1');
  check('J1 a distance runs 5 .. 2000 m',
    [SCATTER_PREF_MIN_M, SCATTER_PREF_MAX_M], [5, 2000]);

  // (J2) reading whatever the store holds
  check('J2 nothing stored yet -> defaults', loadScatterPrefs(null), PREF_DEFAULTS);
  check('J2 unparsable text -> defaults',
    loadScatterPrefs('not json at all'), PREF_DEFAULTS);
  check('J2 JSON null -> defaults', loadScatterPrefs('null'), PREF_DEFAULTS);
  check('J2 an array is not a prefs object',
    loadScatterPrefs('[35,45,120]'), PREF_DEFAULTS);
  check('J2 an empty object -> defaults', loadScatterPrefs('{}'), PREF_DEFAULTS);
  check('J2 a numeric string is not a number',
    loadScatterPrefs('{"scatterFarM":"50"}'), PREF_DEFAULTS);
  check('J2 null is not a number either',
    loadScatterPrefs('{"scatterFarM":null}'), PREF_DEFAULTS);
  check('J2 3 m clamps up to the 5 m floor',
    loadScatterPrefs('{"scatterNearM":3}'), { ...PREF_DEFAULTS, scatterNearM: 5 });
  check('J2 5000 m clamps down to the 2000 m ceiling',
    loadScatterPrefs('{"scatterCullM":5000}'),
    { ...PREF_DEFAULTS, scatterCullM: 2000 });
  check('J2 a stored triple that does not climb falls back COMPLETELY',
    loadScatterPrefs('{"scatterNearM":100}'), PREF_DEFAULTS);
  check('J2 a stored triple that climbs is taken as it stands',
    loadScatterPrefs('{"scatterNearM":20,"scatterFarM":40,"scatterCullM":300}'),
    { scatterNearM: 20, scatterFarM: 40, scatterCullM: 300 });
  const typed = { scatterNearM: 12, scatterFarM: 24, scatterCullM: 90 };
  check('J2 the round trip returns what was stored',
    loadScatterPrefs(saveScatterPrefs(typed)), typed);

  // (J3) what the menu asks before it stores anything
  check('J3 20 / 40 / 300 is taken as typed',
    checkScatterPrefs(20, 40, 300),
    { ok: true, prefs: { scatterNearM: 20, scatterFarM: 40, scatterCullM: 300 } });
  check('J3 a 3 is taken, clamped up to 5',
    checkScatterPrefs(3, 10, 50),
    { ok: true, prefs: { scatterNearM: 5, scatterFarM: 10, scatterCullM: 50 } });
  check('J3 near above far is refused as unordered',
    checkScatterPrefs(40, 20, 300), { ok: false, error: 'order' });
  check('J3 equal is not ordered either',
    checkScatterPrefs(20, 40, 40), { ok: false, error: 'order' });
  check('J3 an empty number field is refused as no number',
    checkScatterPrefs(NaN, 45, 120), { ok: false, error: 'number' });
  check('J3 a string is refused as no number',
    checkScatterPrefs('30', 45, 120), { ok: false, error: 'number' });
  check('J3 three values colliding at the ceiling are refused, not drawn',
    checkScatterPrefs(2500, 3000, 4000), { ok: false, error: 'order' });

  // (J4) the setting reaches the maths
  const setCfg = scatterLodCfgOf({
    scatterNearM: 20, scatterFarM: 40, scatterCullM: 300,
  });
  check('J4 the stored fields become a cfg', setCfg,
    { nearM: 20, farM: 40, cullM: 300 });
  check('J4 …and 20 / 40 / 300 behaves that way end to end',
    [instanceTier(19, 1, setCfg), instanceTier(41, 0, setCfg),
      instanceTier(301, 1, setCfg)],
    [0, 1, 2]);
  check('J4 …including the thinning line of the set cull distance',
    instanceShare(160, setCfg), 1 - (120 / 260) * 0.75);

  console.log(`\n${passed} ok, ${failed} failed`);
  process.exit(failed ? 1 : 0);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
