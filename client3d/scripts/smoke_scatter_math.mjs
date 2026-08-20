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
 * WHERE SECTION (K) WENT (2026-08-16). This file used to carry a section on
 * the automatic UNDERGROWTH, which was a second layer of the same builder and
 * a second user of the same sampler. It is neither any more: the layer has its
 * own 64 m raster, its own per-cell seed and a look of its own
 * (`client3d/src/scene/undergrowth.ts`), so its 59 checks moved whole to
 * `client3d/scripts/smoke_undergrowth.mjs` — 239 checks here became 180. The
 * cases that did NOT move are the ones the rebuild deleted: the per-AREA count
 * rule, its 20 000 ceiling and the "capped" report, because a painted shape is
 * not the unit the layer is grown in any more.
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
 * (B) pointInFootprint — the exclusion of finding B18, on a POLYGON
 * ============================================================================
 * Contract v6 "Gebiete": a footprint is the location's DRAWN OUTLINE, and the
 * exclusion is a ray cast over it in WORLD metres — half-open, the very rule
 * of `app/core/world_geometry.point_in_polygon` and
 * `client3d/src/game/polygon.pointInPolygon`. The package knows nothing about
 * pins: whoever holds the row turns `map3d.boundary` out of the local frame
 * once per location (§ A1.1) before handing it in.
 *
 * THE FIXTURE IS THE SERVER'S OWN, the concave L-shape of
 * `scripts/smoke_world_polygon.py` (map view, x east / z south), in LOCAL
 * metres:
 *
 *         (0,0) ──── (4,0)
 *           │  wide     │
 *           │  arm    (4,2)
 *           │    (2,2)──┘
 *           │      │  notch at (3,3)
 *         (0,4)─(2,4)
 *
 * PINNED AT (100, 50) WITH YAW 90 — the pin case of
 * `smoke_polygon_containment.mjs`. § A1.1 says
 *
 *     x = cx + lx·cos(yaw) + lz·sin(yaw)
 *     z = cz − lx·sin(yaw) + lz·cos(yaw)
 *
 * and at yaw 90 (cos 0, sin 1) that is x = 100 + lz, z = 50 − lx. Every corner
 * by hand:
 *
 *     local (0,0) -> (100 + 0, 50 − 0) = (100, 50)
 *     local (4,0) -> (100 + 0, 50 − 4) = (100, 46)
 *     local (4,2) -> (100 + 2, 50 − 4) = (102, 46)
 *     local (2,2) -> (100 + 2, 50 − 2) = (102, 48)
 *     local (2,4) -> (100 + 4, 50 − 2) = (104, 48)
 *     local (0,4) -> (100 + 4, 50 − 0) = (104, 50)
 *
 * (B1) THE NOTCH IS NOT EXCLUDED — the bug this replaces. The old square test
 *      took `plan_width_m` (the bounding box, 4) and cleared the WHOLE 4×4
 *      block, so the bay bitten out of a lake grew nothing.
 *        local (3,3) -> world (100 + 3, 50 − 3) = (103, 47)
 *        the ray from (103, 47) to +x crosses: the edge (100,50)→(100,46) at
 *        x = 100 (not to the right), the edge (102,46)→(102,48) at x = 102
 *        (not to the right either — 103 > 102); the three edges at z = 48/50
 *        do not straddle z = 47 at all. ZERO crossings -> OUTSIDE.
 *      -> `pointInFootprint` false: a prop MAY stand in the notch.
 *
 * (B2) THE WIDE ARM IS EXCLUDED.
 *        local (1,1) -> world (100 + 1, 50 − 1) = (101, 49)
 *        crossings to the right of (101, 49): the edge (104,48)→(104,50)
 *        straddles z = 49 and sits at x = 104 > 101 -> ONE crossing;
 *        (100,50)→(100,46) straddles it too but at x = 100 < 101.
 *        ONE crossing -> INSIDE.
 *      And the right arm, local (3,1) -> world (101, 47): the only crossing to
 *      the right is (102,46)→(102,48) at x = 102 -> INSIDE.
 *
 * (B3) OUTSIDE THE BOUNDING BOX. local (5,5) -> world (105, 45) — outside on
 *      both axes -> false, the case a bounding-box test would also get right
 *      and the one that pins that nothing was inverted.
 *
 * (B4) NO OUTLINE, NO EXCLUSION. Fewer than three points (a line, a single
 *      point, an empty list), a missing `points` and a junk coordinate all
 *      block nothing: since v6 Nr. 1 a location without a boundary has no area
 *      at all, and a poisoned outline is not a shape anyone can name (the same
 *      all-or-nothing `polygon.sanitizePolygon` applies). A non-finite QUERY
 *      point is refused for the same reason.
 *
 * (B5) A CLOSED RING IS TOLERATED: the repeated first point makes a degenerate
 *      edge, which can never straddle a ray. Same answers as (B1)/(B2).
 *
 * ============================================================================
 * (M) footprintDistance / footprintBlocks — the CLEARANCE (finding 2026-08-20)
 * ============================================================================
 * A scattered prop is not a point. The centre test of (B) let a tree whose
 * TRUNK stands 40 cm outside a boundary hang metres of canopy over the place
 * behind it — reported as "scatter overhangs into locations". The exclusion is
 * therefore a distance:
 *
 *     excluded  <=>  footprintDistance(x, z) < clearM
 *     clearM     =  extentM / 2        the measured half-width of THAT mesh
 *     clearM     =  heightM * 0.5      while nothing has been measured
 *
 * `footprintDistance` is the twin of `world_geometry.polygon_distance` and of
 * `game/polygon.polygonDistance`: 0 anywhere INSIDE, the edge distance
 * outside, `Infinity` for an outline that encloses nothing.
 *
 * (M1) THE TWO REPORTED NUMBERS, on the square 0..10 × 0..10.
 *      A prop centred at (10.4, 5) stands 0.4 m east of the x = 10 edge; the
 *      nearest point of the outline is (10, 5), so the distance is 0.4.
 *      With clearM 1.0: 0.4 < 1.0 -> EXCLUDED, and it is the tree that used to
 *      hang over the courtyard.
 *      A prop centred at (11.4, 5) is 1.4 m out: 1.4 < 1.0 is false -> KEPT.
 *      The centre of the square, (5, 5), has distance 0 -> excluded whatever
 *      the clearance, which is the (B) behaviour unchanged.
 *      Past the CORNER, at (13, 14): neither edge is reachable perpendicularly,
 *      so the nearest point is the corner (10, 10) and the distance is
 *      hypot(3, 4) = 5 — the case that pins the segment clamping.
 *
 * (M2) NO CLEARANCE IS THE OLD TEST, spelled out and not derived: a point
 *      INSIDE has distance 0, and `0 < 0` is false — so a clearM of 0 must
 *      fall back to `pointInFootprint` or every prop would stand in the middle
 *      of the building. The automatic undergrowth passes no clearance and has
 *      to keep behaving exactly as it did.
 *
 * (M3) THE CONCAVE FIXTURE of (B), so the notch is judged by the same shape
 *      the server judges: the notch point world (103, 47) is 1 m from both
 *      notch edges (local (3,3) sits 1 m from the edge at local x = 2 and 1 m
 *      from the one at local z = 2). So clearM 1.0 KEEPS it (1 < 1 is false)
 *      and clearM 1.2 excludes it — an edge-exact pair the ray cast alone
 *      cannot tell apart.
 *
 * (M4) IN THE SAMPLER, and this is the determinism half: ring 0..20 × 0..20,
 *      density 0.5 -> wanted = round(400/100 * 0.5) = 2, one try each. The
 *      footprint is the square 10..20 × 0..10. Fed 0.48 / 0.25 / 0.00 and
 *      0.43 / 0.25 / 0.50:
 *        x = 0 + 0.48*20 = 9.6, z = 0 + 0.25*20 = 5, yaw = 0
 *          -> 0.4 m west of the x = 10 edge
 *        x = 0 + 0.43*20 = 8.6, z = 5, yaw = 0.5*2pi = pi
 *          -> 1.4 m west of it
 *      With clearM 1.0 the first is dropped and the second stands at (8.6, 5)
 *      with yaw pi — the SAME yaw it has with clearM 0, because all three
 *      numbers are drawn before any test. That is the whole determinism
 *      claim: the candidate stream is identical, only the verdict flips.
 *
 * (M5) `scatterClearM` — the two branches, by hand. An 8 m tree nobody has
 *      measured: 8 * 0.5 = 4 m of clearance. The same tree measured 3 m
 *      across: 3 / 2 = 1.5 m. A junk or absent extent falls back to the
 *      estimate; a junk height is no clearance at all (0), which is the plain
 *      containment test again.
 *
 * (M6) THE RED COUNTER-CHECK: a mutant whose blocking test is the old
 *      `pointInFootprint` keeps the 0.4 m tree — the exact defect.
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
 * (C2) THE SAME STREAM with a footprint over the FIRST point: the outline
 *      (1,3) (3,3) (3,5) (1,5) in WORLD metres — 1..3 by 3..5. The first
 *      candidate (2, 4) is its centre and is dropped — but it still cost its
 *      three numbers, so the second candidate is the very same 0.75/0.25/0.00
 *      it was in (C1).
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
 * (C12) THE CONCAVE FOOTPRINT, END TO END — the lake with a bay, the whole
 *       reason the square went. The L-shaped place of section (B) stands in a
 *       meadow painted around it: the 8 x 8 m square 100..108 by 44..52.
 *         wanted = round(64 / 100 * 3.125) = 2, `triesPerPoint` 1 -> exactly
 *         two candidates; x = 100 + r*8, z = 44 + r*8:
 *           0.375, 0.375, 0.50 -> (103, 47) yaw pi  — the NOTCH
 *           0.125, 0.625, 0.00 -> (101, 49) yaw 0   — the wide ARM
 *       Without the place both stand. WITH it the arm is subtracted and the
 *       notch keeps growing: [ {103, 47, pi} ] — ground the place does not
 *       cover, and the bay of a lake is exactly that ground.
 *       THE RED PROBE of the replaced rule: the bounding SQUARE of the same
 *       outline — (100,46) (104,46) (104,50) (100,50), the 4 m `plan_width_m`
 *       block — contains BOTH points, so the old exclusion returns [] and
 *       cannot pass this case.
 *
 * (C13) TWO AREAS OF ONE KIND (reported 2026-08-19: "the second Deep Forest
 *       grows nothing / grows differently"). The count hangs on the painted
 *       AREA and the seed on the area's ID — never on the terrain kind, which
 *       is the same string for both.
 *         a 100 x 100 m wood at 3 per 100 m2: round(10 000/100 · 3) = 300
 *         a  30 x  30 m wood at the same   3: round(   900/100 · 3) =  27
 *       Both rings ARE their own bounding boxes, so no candidate is ever
 *       rejected and the run reaches those counts exactly. Divided back out
 *       that is 3.0 and 3.0 per 100 m2 — the settings, in both areas.
 *       The seeds are `terrain:scatter:ta_big:0` and
 *       `terrain:scatter:ta_small:0`: two different streams, so neither wood
 *       is a copy of the other and neither can displace the other in a map
 *       keyed by anything.
 * (C14) A LOWER `maxPoints` IS A PREFIX. The candidate stream depends on the
 *       seed alone, so the first 25 accepted candidates of the 300-prop wood
 *       are the first 25 of that same list — which is what lets the map
 *       editor thin its preview to a dot budget
 *       (`mapMath.scatterPreviewShares`, `scripts/smoke_scatter_preview.mjs`)
 *       and still draw props the world really plants.
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
 * (K) THE CELL RASTER — the authored scatter is a WINDOW, not a shape
 * ============================================================================
 * The second defect of the 2026-08-19 report: "the SMALLER Deep-Forest area is
 * far denser than the larger one, at the same settings". It was not a sampling
 * bias — it was the ceiling. `scatterInstances` spends at most
 * `SCATTER_MAX_PER_ENTRY` instances over a painted shape of ANY size, so a
 * capped area is drawn at 2000/(A/100) props per 100 m2, i.e. proportional to
 * 1/A. Two woods of one authoring, 16.3 times apart in size, came out 14 times
 * apart in density.
 *
 * Since 2026-08-19 the authored scatter is sampled the way the automatic
 * undergrowth has been since 2026-08-16: per 64 m CELL
 * (`scatterCellInstances`), at the authored density, with the painted ring as
 * the FILTER and not as the sampled box. The count of one cell is
 *
 *     round(4096 / 100 * density),  capped at SCATTER_MAX_PER_CELL = 4000
 *
 * (K1) THE PER-CELL COUNTS, by hand — 4096/100 = 40.96:
 *        d = 3    -> round(122.88)  = 123
 *        d = 20   -> round(819.2)   = 819
 *        d = 10   -> round(409.6)   = 410
 *        d = 1    -> round(40.96)   =  41
 *        d = 0.1  -> round(4.096)   =   4
 *        d = 200  -> round(8192)    = 8192 -> CAPPED to 4000
 *      The cap is therefore reached at 4000/40.96 = 97.66 props per 100 m2 —
 *      about one prop per square metre, and it bites at that SAME density in
 *      every cell of every area. A ceiling can no longer make two woods differ.
 *
 * (K2) THE TWO FORESTS, the fixture of the report. Both cell-aligned squares
 *      of one kind at d = 3:
 *        BIG   (0,0)..(1280,1280)  = 1 638 400 m2 = 20 x 20 = 400 cells
 *        SMALL (2048,0)..(2176,128)=    16 384 m2 =  2 x  2 =   4 cells
 *      Every cell of both lies wholly inside its own area, so the ring filter
 *      drops nothing and each cell carries its 123 props:
 *        BIG   400 * 123 = 49 200 over 16 384 hundred-m2 -> 3.00293 per 100 m2
 *        SMALL   4 * 123 =    492 over    163.84         -> 3.00293 per 100 m2
 *      IDENTICAL to five decimals, from areas 100 times apart. (3.00293 and
 *      not 3.0 because a cell rounds 122.88 up to 123 — the rounding of the
 *      count rule, unchanged.)
 *
 * (K3) THE RED COUNTER-PROBE — the behaviour this replaces, on the same two
 *      areas through the WHOLE-AREA sampler:
 *        BIG   min(round(16384 * 3), 2000) = 2000 -> 2000/16384   = 0.12207
 *        SMALL     round(163.84 * 3)       =  492 ->  492/163.84  = 3.00293
 *      A factor of 24.6 between two areas nobody authored differently. The
 *      cell rule must NOT reproduce those two numbers.
 *
 * (K4) THE SEED IS PER CELL. `scatterCellSeed('ta_1', 0, -2, 3)` is
 *      `terrain:scatter:ta_1:0:-2,3`. Two cells of one entry draw different
 *      streams (without that, every cell would map the same numbers onto its
 *      own box and the wood would be one pattern stamped out every 64 m), and
 *      the same cell always draws the same one — walking out of a wood and
 *      back into it finds the identical trees.
 *
 * (K5) THE RING IS A FILTER, NOT A BOX. Cell (0,0) is 0..64 in both axes; the
 *      area is its LEFT HALF, (0,0)..(32,64). At d = 0.1 the cell wants 4
 *      candidates, and with the stream
 *        0.10, 0.50, 0.00 -> (6.4, 32) yaw 0      inside  ->  kept
 *        0.90, 0.50, 0.25 -> (57.6, 32)           x > 32  ->  dropped
 *        0.25, 0.25, 0.50 -> (16, 16) yaw pi      inside  ->  kept
 *        0.75, 0.75, 0.75 -> (48, 48)             x > 32  ->  dropped
 *      exactly two props stand. The candidates are the CELL's either way: what
 *      an area reaches into must not change the stream of the cell, or two
 *      areas meeting in one cell would move each other's props.
 *
 * (K6) THE WINDOW. `scatterCellSpan(cullM) = ceil(cullM / 64)`, and the window
 *      is the (2k+1)^2 square of cells around the anchor's OWN cell:
 *        cull 120 -> k = 2 -> 25 cells; at (0,0) the first is (-2,-2)
 *        cull  60 -> k = 1 ->  9 cells
 *        cull 300 -> k = 5 -> 121 cells
 *      COVERAGE, the property the square is for: from anywhere inside its own
 *      cell the anchor is at least k*64 m from the far edge of the window, and
 *      k*64 >= cullM by construction (128 >= 120, 64 >= 60, 320 >= 300). So
 *      nothing within the cull distance is ever missing, and the set changes
 *      only when the anchor crosses a cell border — never with every metre.
 *      At (100, 30) the anchor cell is (1, 0), so the window runs (-1,-2) to
 *      (3, 2).
 *
 * (K7) WHAT THE REPORTING WORLD COSTS, in instances. Its big wood carries
 *      seven rows summing to 43.1 per 100 m2, i.e. per cell
 *        41 + 4 + 410 + 410 + 41 + 41 + 819 = 1766
 *      -> 1766/40.96 = 43.115 per 100 m2, the authored density, and
 *      25 * 1766 = 44 150 instances held for the whole window (102 400 m2).
 *      The small wood's six rows sum to 43.0 -> 1762 per cell -> 43.018.
 *      Inside the player's own 120 m cull circle (45 238.9 m2) that is
 *      19 505 against 19 461 props — the same wood twice. BEFORE: 46 and 645.
 *
 * ============================================================================
 * (N) THE VARIANT MIX — a wood of 14 000 trees is not one tree
 * ============================================================================
 * A prop may carry up to four active model variants (§ B2 addendum). The room
 * scatter and the world props have mixed them since 2026-08-19, resolved on
 * the SERVER per copy; the painted terrain scatter could not, because its
 * instances do not exist on the server at all — they are sampled client-side
 * in a camera window whose cell set changes as the player walks. So a forest
 * of 14 000 trees kept drawing ONE mesh 14 000 times.
 *
 * The mix therefore runs where the instances are made, with the SAME formula
 * (`app/core/props.py scatter_variant_index`) over the seed the sampler
 * already has — the CELL's own seed string:
 *
 *     variant = ( scatterSeedHash(cell seed) + candidate ) mod n
 *
 * (N1) THE HASH, BY HAND. `scatterSeedHash` is FNV-1a 32-bit — the very state
 *      `seededRandom` starts its stream from, lifted out so one seed answers
 *      one hash:
 *        h = 2166136261 = 0x811C9DC5
 *        for each char c:  h = ((h XOR c) * 16777619) mod 2^32
 *      The empty string never enters the loop, so hash('') = 2166136261, the
 *      offset basis itself. For the single character 'A' (0x41):
 *        h XOR 0x41 = 0x811C9DC5 XOR 0x41 = 0x811C9D84 = 2166136196
 *        16777619   = 2^24 + 403
 *        (2166136196 * 2^24) mod 2^32 = (2166136196 mod 2^8) * 2^24
 *                                     = 0x84 * 2^24 = 132 * 16777216
 *                                     = 2 214 592 512
 *        (2166136196 * 403)  mod 2^32 = 872 952 886 988 - 203 * 4 294 967 296
 *                                     = 872 952 886 988 - 871 878 361 088
 *                                     =   1 074 525 900
 *        sum                          = 3 289 118 412   (< 2^32, no wrap)
 *      -> hash('A') = 3 289 118 412. Its digit sum is 39, so it is divisible
 *      by 3: hash('A') mod 3 = 0. UNSIGNED is the contract, not a detail —
 *      `Math.imul` gives a SIGNED int32 and (-1) % 3 is -1 in JavaScript, so a
 *      signed hash would hand a renderer a negative variant index.
 *
 * (N2) THE FORMULA, on that hash. With n = 3 and the seed 'A' (offset 0), the
 *      candidates 0..5 walk the ring:
 *        (0+0..5) mod 3  =  0, 1, 2, 0, 1, 2
 *      — the same shape as the § B2 hand-check of the room scatter (seed 7,
 *      3 variants -> 1, 2, 0, 1, 2, 0), which is the point: ONE formula, two
 *      kinds of seed. The real cell seed of (K4),
 *      `terrain:scatter:ta_1:0:-2,3`, hashes to 3 875 892 755, and
 *      3 875 892 755 mod 3 = 2, so ITS cell starts at 2: 2, 0, 1, 2, 0, 1.
 *      Every cell of a wood therefore enters the ring at its own offset, which
 *      is what keeps a mixed forest from being one repeating pattern.
 *      n <= 1 has nothing to choose from and answers 0 for every candidate.
 *
 * (N3) THE CANDIDATE, NOT THE SURVIVOR. The number the formula counts is the
 *      candidate's ordinal in the cell's stream, rejected ones included —
 *      the same choice that makes the yaw a wasted draw in (C) and (D). A
 *      cell of 5 candidates at d = 1.25 (round(400/100 * 1.25) = 5) over the
 *      20 x 20 square, with three variants and the seed 'A':
 *        c0  0.10, 0.20, 0.00  -> ( 2,  4) yaw 0        kept   variant 0
 *        c1  0.25, 0.25, 0.25  -> ( 5,  5) yaw tau/4    kept   variant 1
 *        c2  0.50, 0.50, 0.50  -> (10, 10) yaw pi       kept   variant 2
 *        c3  0.75, 0.30, 0.00  -> (15,  6) yaw 0        kept   variant 0
 *        c4  0.40, 0.80, 0.00  -> ( 8, 16) yaw 0        kept   variant 1
 *      Now paint an area OVER the middle — the occluder (8,8)..(12,12), which
 *      covers c2 and nothing else. The survivors are c0, c1, c3, c4 and they
 *      keep the variants 0, 1, 0, 1: a shape drawn over a wood removes the
 *      trees under it and does not re-species the ones beside it. Counting
 *      over the SURVIVORS would give 0, 1, 2, 0 instead — every tree behind
 *      the new shape a different kind of tree. This is not a hypothetical:
 *      the clearance an entry keeps from a building is REFINED the moment its
 *      mesh lands (`ground.ts noteSpread` -> `rebuildScatter`), so a survivor
 *      index would re-roll a wood a second after the player looked at it.
 *
 * (N4) n = 1 IS TODAY'S BEHAVIOUR, BYTE FOR BYTE. Without `variantCount`, with
 *      0 and with 1 the sampler returns the very same objects it always did —
 *      three keys, no `variant` at all. The absence IS the contract: every
 *      existing consumer (the map editor's dot preview, the backdrop profile)
 *      is untouched by the feature existing, and a prop with one variant costs
 *      no payload field and no second mesh.
 *
 * (N5) THE MESHES. `ground.ts buildScatter` splits a cell's points into one
 *      bucket per variant and builds ONE InstancedMesh pair per (row, variant)
 *      — the existing per-row entry, once per variant. On the (N3) fixture:
 *        no occluder: buckets [2, 2, 1] -> 3 meshes  (5 instances)
 *        with it:     buckets [2, 2, 0] -> 2 meshes  (4 instances)
 *      A variant no candidate picked gets NO mesh and NO download, which is
 *      why the split happens after the sampling and not before it. The sums
 *      are the whole instance count either way — a split may not lose a prop.
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
 *
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
    .replace(
      'out.push(mixing\n'
      + '      ? { x, z, yaw, variant: scatterVariantIndex(opts.seed, index, variants) }\n'
      + '      : { x, z, yaw })',
      'out.push({ x, z, yaw: rnd() * Math.PI * 2 })');
}

/** Section (N3)'s mutant: the variant is counted over the SURVIVORS instead of
 *  over the candidates, so a rejection shifts the whole rest of the cell into
 *  other meshes — the wood behind a newly painted shape changes species.
 *  See the header for the derivation. */
function variantFromSurvivorIndex(source) {
  return source.replace(
    'variant: scatterVariantIndex(opts.seed, index, variants)',
    'variant: scatterVariantIndex(opts.seed, out.length, variants)');
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

/** Section (H8)'s mutant: the ground offset is dropped and the sampled height
 *  is handed back as it came — the state of the code before the field existed,
 *  where a sunk fir stands on the grass in a painted wood while the same fir
 *  is buried correctly in every room. */
function ignoreGroundOffset(source) {
  return source.replace(
    '  if (typeof offsetM !== \'number\' || !Number.isFinite(offsetM)) return 0;\n'
    + '  return Math.min(Math.max(offsetM, -SCATTER_GROUND_OFFSET_LIMIT_M),\n'
    + '    SCATTER_GROUND_OFFSET_LIMIT_M);\n',
    '  return 0;\n');
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

/** Section (M6)'s mutant: the clearance is thrown away and the old "is its
 *  CENTRE inside?" decides again — the state the user reported as scatter
 *  overhanging into locations. */
function centreInsteadOfClearance(source) {
  return source.replace(
    '  if (!(clear > 0)) return pointInFootprint(fp, x, z)\n'
    + '  return footprintDistance(fp, x, z) < clear\n',
    '  return pointInFootprint(fp, x, z)\n');
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
    scatterWantedCount, scatterCellAt, scatterCellInstances, scatterCellRing,
    scatterCellSeed, scatterCellSpan, scatterCellsInBox, wantedScatterCells,
    scatterSeedHash, scatterVariantIndex,
    footprintBlocks, footprintDistance, scatterClearM,
    SCATTER_CELL_M, SCATTER_CLEAR_HEIGHT_RATIO, SCATTER_MAX_PER_CELL,
  } = await loadTs(SRC);

  const TAU = Math.PI * 2;
  const SQUARE = [[0, 0], [20, 0], [20, 20], [0, 20]];
  const TRIANGLE = [[0, 0], [20, 0], [0, 20]];
  // The occluder rings of (C8..C11) — see the header for what each covers.
  const OCC_LEFT = [[0, 0], [10, 0], [10, 10], [0, 10]];
  const OCC_RIGHT = [[12, 0], [20, 0], [20, 10], [12, 10]];
  const OCC_FAR = [[30, 30], [40, 30], [40, 40], [30, 40]];
  const BOWTIE = [[0, 0], [10, 10], [10, 0], [0, 10]];
  /** The server's concave L-shape in LOCAL metres — the fixture of
   *  `scripts/smoke_world_polygon.py` and `smoke_polygon_containment.mjs`. */
  const L_LOCAL = [[0, 0], [4, 0], [4, 2], [2, 2], [2, 4], [0, 4]];
  /** Local -> world (§ A1.1) — the turn the CALLER does before the sampler
   *  ever sees a footprint (`ground.ts → worldFootprints`). Spelled out here,
   *  never imported: the world literals of section (B) are hand-derived from
   *  this formula, and a shared helper would be checking itself. */
  const localToWorld = (lx, lz, cx, cz, yawDeg) => {
    const r = (yawDeg * Math.PI) / 180;
    const c = Math.cos(r);
    const s = Math.sin(r);
    // rounded to nanometres: cos(90 deg) is 6.1e-17 in binary floats, not 0,
    // and a corner at 100.0000000000000002 reads worse than it is.
    return [Math.round((cx + lx * c + lz * s) * 1e9) / 1e9,
      Math.round((cz - lx * s + lz * c) * 1e9) / 1e9];
  };
  const L_WORLD = L_LOCAL.map(([lx, lz]) => localToWorld(lx, lz, 100, 50, 90));
  /** (C2)/(D): the outline that covers the first candidate of the (C1) stream
   *  — 1..3 by 3..5 in world metres, and (2, 4) is its centre. */
  const FP_OVER_FIRST = { points: [[1, 3], [3, 3], [3, 5], [1, 5]] };
  /**
   * (C12): a meadow painted AROUND the L-shaped place of section (B) — the
   * 8 × 8 m square 100..108 by 44..52, which holds the whole outline.
   *
   *   wanted = round(64 / 100 * 3.125) = round(2) = 2, and `triesPerPoint` 1
   *   bounds the run at exactly those two candidates.
   *   x = 100 + r*8, z = 44 + r*8:
   *     0.375, 0.375, 0.50 -> (103, 47), yaw pi   — the NOTCH  (B1)
   *     0.125, 0.625, 0.00 -> (101, 49), yaw 0    — the wide ARM (B2)
   */
  const L_MEADOW = {
    ring: [[100, 44], [108, 44], [108, 52], [100, 52]],
    areaM2: 64, densityPer100m2: 3.125, seed: 's', triesPerPoint: 1,
  };
  const L_STREAM = [0.375, 0.375, 0.50, 0.125, 0.625, 0.00];
  const L_BOTH = [{ x: 103, z: 47, yaw: Math.PI }, { x: 101, z: 49, yaw: 0 }];
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

  console.log('\n(B) pointInFootprint — the DRAWN outline stays clear (B18, v6)');
  // The caller's job, done here by hand so the expectations below are literals
  // and not the output of a helper: local -> world at pin (100, 50), yaw 90.
  check('B the pin transform puts local (4,0) at world (100,46)',
    L_WORLD[1], [100, 46]);
  check('B …and the whole outline is the hand-derived one', L_WORLD, [
    [100, 50], [100, 46], [102, 46], [102, 48], [104, 48], [104, 50],
  ]);
  const HUT = { points: L_WORLD };
  check('B1 the NOTCH — local (3,3) = world (103,47) — is NOT excluded',
    pointInFootprint(HUT, 103, 47), false);
  check('B2 the wide arm — local (1,1) = world (101,49) — IS excluded',
    pointInFootprint(HUT, 101, 49), true);
  check('B2 …and the right arm — local (3,1) = world (101,47) — too',
    pointInFootprint(HUT, 101, 47), true);
  check('B3 local (5,5) = world (105,45) is past the outline entirely',
    pointInFootprint(HUT, 105, 45), false);
  check('B4 a two-point outline blocks nothing',
    pointInFootprint({ points: [[100, 50], [100, 46]] }, 100, 48), false);
  check('B4 an empty outline blocks nothing',
    pointInFootprint({ points: [] }, 101, 49), false);
  check('B4 a missing outline blocks nothing',
    pointInFootprint({}, 101, 49), false);
  check('B4 a junk coordinate poisons the whole outline',
    pointInFootprint({ points: [[100, 50], [100, NaN], [102, 46], [102, 48]] },
      101, 47), false);
  check('B4 a NaN query point is refused', pointInFootprint(HUT, NaN, 49), false);
  check('B5 a closed ring answers exactly as the open one does (inside)',
    pointInFootprint({ points: [...L_WORLD, [100, 50]] }, 101, 49), true);
  check('B5 …and in the notch (outside)',
    pointInFootprint({ points: [...L_WORLD, [100, 50]] }, 103, 47), false);

  console.log('\n(M) the CLEARANCE — a prop stops OVERHANGING a location');
  const SQ_FP = { points: [[0, 0], [10, 0], [10, 10], [0, 10]] };
  check('M1 (10.4, 5) is 0.4 m east of the x = 10 edge',
    footprintDistance(SQ_FP, 10.4, 5), 0.4);
  check('M1 (11.4, 5) is 1.4 m out', footprintDistance(SQ_FP, 11.4, 5), 1.4);
  check('M1 the centre is INSIDE and reads 0',
    footprintDistance(SQ_FP, 5, 5), 0);
  check('M1 past the corner it is hypot(3, 4) = 5',
    footprintDistance(SQ_FP, 13, 14), 5);
  // Infinity survives no JSON round trip, so the four are asserted as the
  // predicate they stand for: nothing can ever be that close.
  check('M1 a degenerate outline is unreachable',
    [footprintDistance({ points: [[0, 0], [10, 0]] }, 5, 5),
      footprintDistance({}, 5, 5),
      footprintDistance({ points: [[0, 0], [10, NaN], [10, 10]] }, 5, 5),
      footprintDistance(SQ_FP, NaN, 5)].map((d) => d === Infinity),
    [true, true, true, true]);
  check('M1 …and therefore blocks nothing, at any clearance',
    footprintBlocks({ points: [[0, 0], [10, NaN], [10, 10]] }, 5, 5, 1e6),
    false);
  check('M1 …and with clearM 1.0 the 0.4 m prop goes, the 1.4 m one stays',
    [footprintBlocks(SQ_FP, 10.4, 5, 1), footprintBlocks(SQ_FP, 11.4, 5, 1)],
    [true, false]);
  check('M1 the prop INSIDE is excluded whatever the clearance',
    [footprintBlocks(SQ_FP, 5, 5, 1), footprintBlocks(SQ_FP, 5, 5, 0)],
    [true, true]);
  check('M2 without a clearance it is the plain containment test again',
    [footprintBlocks(SQ_FP, 10.4, 5, 0), footprintBlocks(SQ_FP, 10.4, 5),
      footprintBlocks(SQ_FP, 10.4, 5, NaN)],
    [false, false, false]);
  check('M3 the concave NOTCH is exactly 1 m from both its edges',
    footprintDistance(HUT, 103, 47), 1);
  check('M3 …so clearM 1.0 keeps the prop there and 1.2 takes it away',
    [footprintBlocks(HUT, 103, 47, 1), footprintBlocks(HUT, 103, 47, 1.2)],
    [false, true]);
  const CLEAR_SAMPLE = {
    ring: SQUARE, areaM2: 400, densityPer100m2: 0.5, seed: 's',
    footprints: [{ points: [[10, 0], [20, 0], [20, 10], [10, 10]] }],
    triesPerPoint: 1,
  };
  const CLEAR_STREAM = [0.48, 0.25, 0.00, 0.43, 0.25, 0.50];
  check('M4 without a clearance both candidates stand — 0.4 m and 1.4 m out',
    scatterInstances({ ...CLEAR_SAMPLE, rng: stream(CLEAR_STREAM) }),
    [{ x: 9.6, z: 5, yaw: 0 }, { x: 8.6, z: 5, yaw: Math.PI }]);
  check('M4 clearM 1.0 SUBTRACTS the 0.4 m one and leaves the other untouched',
    scatterInstances({ ...CLEAR_SAMPLE, clearM: 1, rng: stream(CLEAR_STREAM) }),
    [{ x: 8.6, z: 5, yaw: Math.PI }]);
  check('M4 …the same holds through the cell sampler',
    scatterCellInstances({
      ring: [[0, 0], [64, 0], [64, 64], [0, 64]], cx: 0, cz: 0,
      densityPer100m2: 0.05,
      seed: 'm4',
      footprints: [{ points: [[10, 0], [20, 0], [20, 10], [10, 10]] }],
      clearM: 1,
      rng: stream([0.15, 0.078125, 0.00, 0.134375, 0.078125, 0.50]),
    }),
    [{ x: 8.6, z: 5, yaw: Math.PI }]);
  check('M5 an 8 m prop nobody measured keeps 4 m — as wide as it is tall',
    scatterClearM(8), 4);
  check('M5 …measured 3 m across it keeps 1.5', scatterClearM(8, 3), 1.5);
  check('M5 a junk extent falls back to the estimate',
    [scatterClearM(8, 0), scatterClearM(8, NaN), scatterClearM(8, null)],
    [4, 4, 4]);
  check('M5 …and a junk height is no clearance at all',
    [scatterClearM(0), scatterClearM(NaN), scatterClearM(-3)], [0, 0, 0]);
  check('M5 the estimate ratio is a half', SCATTER_CLEAR_HEIGHT_RATIO, 0.5);
  const centreMutant = await loadTs(SRC, centreInsteadOfClearance);
  checkNot('M6 the "centre inside" mutant does NOT reproduce the M4 answer',
    centreMutant.scatterInstances({
      ...CLEAR_SAMPLE, clearM: 1, rng: stream(CLEAR_STREAM),
    }),
    [{ x: 8.6, z: 5, yaw: Math.PI }]);
  check('M6 …it keeps the overhanging 0.4 m prop, which IS the defect',
    centreMutant.scatterInstances({
      ...CLEAR_SAMPLE, clearM: 1, rng: stream(CLEAR_STREAM),
    }),
    [{ x: 9.6, z: 5, yaw: 0 }, { x: 8.6, z: 5, yaw: Math.PI }]);

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
      footprints: [FP_OVER_FIRST],
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

  console.log('\n  C12 the CONCAVE footprint, end to end (the lake with a bay)');
  check('C12 without the hut both candidates stand',
    scatterInstances({ ...L_MEADOW, rng: stream(L_STREAM) }), L_BOTH);
  check('C12 the hut subtracts the ARM and leaves the NOTCH growing',
    scatterInstances({ ...L_MEADOW, footprints: [HUT], rng: stream(L_STREAM) }),
    [L_BOTH[0]]);
  // The RED counter-probe of the bug this replaces: the old exclusion was the
  // bounding SQUARE of the outline, and it swallows the notch as well.
  const L_SQUARE_FP = { points: [[100, 46], [104, 46], [104, 50], [100, 50]] };
  check('C12 the bounding SQUARE would have cleared the notch too — the bug',
    scatterInstances({ ...L_MEADOW, footprints: [L_SQUARE_FP],
      rng: stream(L_STREAM) }), []);

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

  console.log('\n  C13 TWO AREAS OF ONE KIND — the count is the AREA\'s, '
    + 'never the kind\'s');
  check('C13 a 10 000 m2 wood at 3 per 100 m2 wants 300',
    scatterWantedCount(10000, 3), 300);
  check('C13 …and a 900 m2 one of the same kind and density wants 27',
    scatterWantedCount(900, 3), 27);
  const BIG = [[0, 0], [100, 0], [100, 100], [0, 100]];      // 10 000 m2
  const SMALL = [[200, 0], [230, 0], [230, 30], [200, 30]];  //    900 m2
  const big = scatterInstances({
    ring: BIG, areaM2: 10000, densityPer100m2: 3, seed: scatterSeed('ta_big', 0),
  });
  const small = scatterInstances({
    ring: SMALL, areaM2: 900, densityPer100m2: 3, seed: scatterSeed('ta_small', 0),
  });
  check('C13 both areas are planted, 300 and 27 props',
    [big.length, small.length], [300, 27]);
  check('C13 …at the SAME density per 100 m2 — 3 and 3',
    [big.length / (10000 / 100), small.length / (900 / 100)], [3, 3]);
  check('C13 the seeds are per AREA INSTANCE, not per kind',
    [scatterSeed('ta_big', 0), scatterSeed('ta_small', 0)],
    ['terrain:scatter:ta_big:0', 'terrain:scatter:ta_small:0']);
  check('C13 …so the second area is not a copy of the first',
    JSON.stringify(scatterInstances({
      ring: BIG, areaM2: 10000, densityPer100m2: 3,
      seed: scatterSeed('ta_small', 0),
    })) !== JSON.stringify(big), true);
  // (C14) A LOWER CEILING IS A PREFIX, not a second sample — what lets the map
  // editor thin its preview to a budget and still draw props the world plants.
  const thinned = scatterInstances({
    ring: BIG, areaM2: 10000, densityPer100m2: 3, seed: scatterSeed('ta_big', 0),
    maxPoints: 25,
  });
  check('C14 maxPoints 25 gives the first 25 of the very same 300',
    thinned, big.slice(0, 25));

  console.log('\n(K) the CELL raster — the density of the GROUND, not of the shape');
  // (K1) the per-cell counts, straight off 4096/100 = 40.96
  const CELL_M2 = SCATTER_CELL_M * SCATTER_CELL_M;
  check('K0 a cell is 64 m, i.e. 4 096 m2', [SCATTER_CELL_M, CELL_M2], [64, 4096]);
  check('K1 d = 3 / 20 / 10 / 1 / 0.1 per cell -> 123 / 819 / 410 / 41 / 4',
    [3, 20, 10, 1, 0.1].map((d) =>
      scatterWantedCount(CELL_M2, d, SCATTER_MAX_PER_CELL)),
    [123, 819, 410, 41, 4]);
  check('K1 the guard is 4 000 per cell, i.e. 97.66 props per 100 m2',
    [scatterWantedCount(CELL_M2, 200, SCATTER_MAX_PER_CELL),
      Math.round((SCATTER_MAX_PER_CELL / (CELL_M2 / 100)) * 100) / 100],
    [4000, 97.66]);
  // (K2) the two forests — cell-aligned squares, 100 times apart in size
  const F_BIG = [[0, 0], [1280, 0], [1280, 1280], [0, 1280]];
  const F_SMALL = [[2048, 0], [2176, 0], [2176, 128], [2048, 128]];
  const cellCount = (ring, id, cells) => cells.reduce((sum, [cx, cz]) => sum
    + scatterCellInstances({
      ring, cx, cz, densityPer100m2: 3, seed: scatterCellSeed(id, 0, cx, cz),
    }).length, 0);
  const bigCells = [];
  for (let cz = 0; cz < 20; cz += 1) for (let cx = 0; cx < 20; cx += 1) bigCells.push([cx, cz]);
  const smallCells = [[32, 0], [33, 0], [32, 1], [33, 1]];
  const bigN = cellCount(F_BIG, 'ta_big', bigCells);
  const smallN = cellCount(F_SMALL, 'ta_small', smallCells);
  check('K2 one cell wholly inside either wood carries its 123 props',
    [scatterCellInstances({
      ring: F_BIG, cx: 5, cz: 7, densityPer100m2: 3,
      seed: scatterCellSeed('ta_big', 0, 5, 7),
    }).length,
    scatterCellInstances({
      ring: F_SMALL, cx: 32, cz: 1, densityPer100m2: 3,
      seed: scatterCellSeed('ta_small', 0, 32, 1),
    }).length],
    [123, 123]);
  check('K2 400 cells of the big wood and 4 of the small: 49 200 and 492 props',
    [bigN, smallN], [49200, 492]);
  const density = (n, m2) => Math.round((n / (m2 / 100)) * 100000) / 100000;
  check('K2 …which is the SAME density per 100 m2 on both — 3.00293',
    [density(bigN, 1638400), density(smallN, 16384)], [3.00293, 3.00293]);
  // (K3) the red counter-probe: the whole-area sampler on the same two woods
  const oldBig = scatterInstances({
    ring: F_BIG, areaM2: 1638400, densityPer100m2: 3, seed: scatterSeed('ta_big', 0),
  }).length;
  const oldSmall = scatterInstances({
    ring: F_SMALL, areaM2: 16384, densityPer100m2: 3, seed: scatterSeed('ta_small', 0),
  }).length;
  check('K3 the OLD whole-area path really did cap the big wood at 2 000',
    [oldBig, oldSmall], [2000, 492]);
  check('K3 …i.e. 0.12207 against 3.00293 per 100 m2 — a factor of 24.6',
    [density(oldBig, 1638400), density(oldSmall, 16384),
      Math.round((density(oldSmall, 16384) / density(oldBig, 1638400)) * 10) / 10],
    [0.12207, 3.00293, 24.6]);
  checkNot('K3 …and the cell rule does NOT reproduce that pair',
    [density(bigN, 1638400), density(smallN, 16384)],
    [density(oldBig, 1638400), density(oldSmall, 16384)]);
  check('K3 …because the cell rule puts the two woods at ONE density, ratio 1',
    density(bigN, 1638400) / density(smallN, 16384), 1);
  // (K4) the seed
  check('K4 the seed carries area, row AND cell',
    scatterCellSeed('ta_1', 0, -2, 3), 'terrain:scatter:ta_1:0:-2,3');
  const cellA = scatterCellInstances({
    ring: F_BIG, cx: 3, cz: 4, densityPer100m2: 3,
    seed: scatterCellSeed('ta_big', 0, 3, 4),
  });
  const cellB = scatterCellInstances({
    ring: F_BIG, cx: 4, cz: 4, densityPer100m2: 3,
    seed: scatterCellSeed('ta_big', 0, 4, 4),
  });
  check('K4 the same cell asked twice gives the identical props', cellA,
    scatterCellInstances({
      ring: F_BIG, cx: 3, cz: 4, densityPer100m2: 3,
      seed: scatterCellSeed('ta_big', 0, 3, 4),
    }));
  check('K4 …and the neighbour cell is not that pattern shifted by 64 m',
    cellA.map((p) => [p.x + SCATTER_CELL_M, p.z, p.yaw]).slice(0, 3)
      .some((p, i) => Math.abs(p[0] - cellB[i].x) < 1e-9
        && Math.abs(p[1] - cellB[i].z) < 1e-9), false);
  // (K5) the ring filters, it does not shrink the box
  check('K5 a cell half covered by the area keeps exactly its two inside props',
    scatterCellInstances({
      ring: [[0, 0], [32, 0], [32, 64], [0, 64]], cx: 0, cz: 0,
      densityPer100m2: 0.1, seed: 'k5',
      rng: stream([0.10, 0.50, 0.00, 0.90, 0.50, 0.25,
        0.25, 0.25, 0.50, 0.75, 0.75, 0.75]),
    }),
    [{ x: 6.4, z: 32, yaw: 0 }, { x: 16, z: 16, yaw: Math.PI }]);
  // (K6) the window
  check('K6 cull 120 / 60 / 300 -> a span of 2 / 1 / 5 cells',
    [scatterCellSpan(120), scatterCellSpan(60), scatterCellSpan(300)], [2, 1, 5]);
  check('K6 …i.e. 25 / 9 / 121 cells in the window',
    [wantedScatterCells(0, 0, 120).length, wantedScatterCells(0, 0, 60).length,
      wantedScatterCells(0, 0, 300).length], [25, 9, 121]);
  check('K6 …and every span reaches at least as far as its cull distance',
    [120, 60, 300].map((c) => scatterCellSpan(c) * SCATTER_CELL_M >= c),
    [true, true, true]);
  check('K6 at the origin the window runs from (-2,-2)',
    wantedScatterCells(0, 0, 120)[0], [-2, -2]);
  check('K6 at (100, 30) the anchor cell is (1, 0), so it runs from (-1,-2)',
    [scatterCellAt(100), scatterCellAt(30), wantedScatterCells(100, 30, 120)[0]],
    [1, 0, [-1, -2]]);
  check('K6 a step inside the same cell does not move the window',
    wantedScatterCells(100, 30, 120), wantedScatterCells(120, 60, 120));
  check('K6 …crossing the border does', wantedScatterCells(130, 30, 120)[0],
    [0, -2]);
  check('K6 a cell owns its lower edge',
    [scatterCellAt(0), scatterCellAt(63.99), scatterCellAt(64),
      scatterCellAt(-1)], [0, 0, 1, -1]);
  check('K6 the cell ring is its own box',
    scatterCellRing(0, 0), [[0, 0], [64, 0], [64, 64], [0, 64]]);
  check('K6 a world box asks for every cell it meets, row-major',
    scatterCellsInBox(0, 0, 70, 10), [[0, 0], [1, 0]]);
  check('K6 …and a box bigger than the guard asks for none',
    scatterCellsInBox(0, 0, 1e6, 1e6).length, 0);
  // (K7) what the reporting world costs
  const BIG_ROWS = [1, 0.1, 10, 10, 1, 1, 20];
  const SMALL_ROWS = [1, 10, 1, 10, 20, 1];
  const perCell = (rows) => rows.reduce((sum, d) =>
    sum + scatterWantedCount(CELL_M2, d, SCATTER_MAX_PER_CELL), 0);
  check('K7 the reporting world\'s two woods want 1 766 and 1 762 props per cell',
    [perCell(BIG_ROWS), perCell(SMALL_ROWS)], [1766, 1762]);
  check('K7 …i.e. 43.115 and 43.018 per 100 m2 — the authored 43.1 and 43.0',
    [Math.round((perCell(BIG_ROWS) / 40.96) * 1000) / 1000,
      Math.round((perCell(SMALL_ROWS) / 40.96) * 1000) / 1000],
    [43.115, 43.018]);
  check('K7 …44 150 and 44 050 instances held over a 25-cell window',
    [25 * perCell(BIG_ROWS), 25 * perCell(SMALL_ROWS)], [44150, 44050]);
  check('K7 …19 505 and 19 461 inside the 120 m cull circle (was 46 and 645)',
    [Math.round(((Math.PI * 120 * 120) / 100) * (perCell(BIG_ROWS) / 40.96)),
      Math.round(((Math.PI * 120 * 120) / 100) * (perCell(SMALL_ROWS) / 40.96))],
    [19505, 19461]);

  console.log('\n(N) the VARIANT MIX — a wood of 14 000 trees is not one tree');
  // (N1) the hash. An INDEPENDENT FNV-1a, written out here and never imported:
  // the point of the section is that the module's hash is this arithmetic, and
  // a shared helper would be checking itself (same discipline as `localToWorld`
  // above).
  const fnv1a = (seed) => {
    let h = 2166136261;
    for (let i = 0; i < seed.length; i += 1) {
      h = Math.imul(h ^ seed.charCodeAt(i), 16777619);
    }
    return h >>> 0;
  };
  check('N1 the empty seed is the offset basis itself',
    scatterSeedHash(''), 2166136261);
  check('N1 hash(\'A\') is the hand-derived 3 289 118 412',
    scatterSeedHash('A'), 3289118412);
  check('N1 …and 3 289 118 412 mod 3 = 0 — the offset of the (N3) fixture',
    scatterSeedHash('A') % 3, 0);
  check('N1 the real cell seed of (K4) hashes to 3 875 892 755',
    scatterSeedHash(scatterCellSeed('ta_1', 0, -2, 3)), 3875892755);
  check('N1 …the module agrees with an independently written FNV-1a',
    ['', 'A', 'terrain:scatter:ta_1:0:-2,3', 'terrain:scatter:ta_big:7:31,-4']
      .map(scatterSeedHash),
    ['', 'A', 'terrain:scatter:ta_1:0:-2,3', 'terrain:scatter:ta_big:7:31,-4']
      .map(fnv1a));
  check('N1 the hash is UNSIGNED — a negative one would be a negative variant',
    ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'].map(scatterSeedHash)
      .every((h) => h >= 0 && h < 2 ** 32 && Number.isInteger(h)), true);
  // (N2) the formula
  check('N2 seed \'A\', 3 variants, candidates 0..5 walk the ring from 0',
    [0, 1, 2, 3, 4, 5].map((i) => scatterVariantIndex('A', i, 3)),
    [0, 1, 2, 0, 1, 2]);
  check('N2 the (K4) cell starts at 2 — every cell enters the ring on its own',
    [0, 1, 2, 3, 4, 5].map((i) =>
      scatterVariantIndex('terrain:scatter:ta_1:0:-2,3', i, 3)),
    [2, 0, 1, 2, 0, 1]);
  check('N2 n = 1 has nothing to choose from',
    [0, 1, 2, 7].map((i) => scatterVariantIndex('A', i, 1)), [0, 0, 0, 0]);
  check('N2 …and neither has n = 0, a negative n or junk',
    [scatterVariantIndex('A', 3, 0), scatterVariantIndex('A', 3, -2),
      scatterVariantIndex('A', 3, NaN), scatterVariantIndex('A', 3, null),
      scatterVariantIndex('A', NaN, 3)], [0, 0, 0, 0, 0]);
  check('N2 a big instance number wraps rather than running off the list',
    [scatterVariantIndex('A', 3000, 4), scatterVariantIndex('A', 3001, 4)],
    [(3289118412 + 3000) % 4, (3289118412 + 3001) % 4]);
  check('N2 …and the answer is always a usable index',
    [1, 2, 3, 4].every((n) => [0, 1, 2, 3, 4, 5, 6, 7].every((i) => {
      const v = scatterVariantIndex(`terrain:scatter:ta_${i}:0:${i},${n}`, i, n);
      return Number.isInteger(v) && v >= 0 && v < n;
    })), true);
  // (N3) the candidate, not the survivor
  const MIX = {
    ring: SQUARE, areaM2: 400, densityPer100m2: 1.25, seed: 'A',
    triesPerPoint: 1, variantCount: 3,
  };
  const MIX_STREAM = [0.10, 0.20, 0.00, 0.25, 0.25, 0.25, 0.50, 0.50, 0.50,
    0.75, 0.30, 0.00, 0.40, 0.80, 0.00];
  /** The ring painted OVER the middle of (N3) — it covers c2 and nothing else. */
  const OCC_MIDDLE = [[8, 8], [12, 8], [12, 12], [8, 12]];
  const mixed = scatterInstances({ ...MIX, rng: stream(MIX_STREAM) });
  check('N3 five candidates, five props, each with the variant of its ordinal',
    mixed,
    [{ x: 2, z: 4, yaw: 0, variant: 0 },
      { x: 5, z: 5, yaw: TAU * 0.25, variant: 1 },
      { x: 10, z: 10, yaw: Math.PI, variant: 2 },
      { x: 15, z: 6, yaw: 0, variant: 0 },
      { x: 8, z: 16, yaw: 0, variant: 1 }]);
  const subtracted = scatterInstances({
    ...MIX, occluders: [OCC_MIDDLE], rng: stream(MIX_STREAM),
  });
  check('N3 a shape painted over the middle takes c2 and nothing else away',
    subtracted.map((p) => [p.x, p.z]), [[2, 4], [5, 5], [15, 6], [8, 16]]);
  check('N3 …and the survivors keep the variants they had: 0, 1, 0, 1',
    subtracted.map((p) => p.variant), [0, 1, 0, 1]);
  const survivorMutant = await loadTs(SRC, variantFromSurvivorIndex);
  checkNot('N3 the mutant "count the survivors" does NOT reproduce that',
    survivorMutant.scatterInstances({
      ...MIX, occluders: [OCC_MIDDLE], rng: stream(MIX_STREAM),
    }).map((p) => p.variant), [0, 1, 0, 1]);
  check('N3 …it re-species the wood behind the new shape: 0, 1, 2, 0',
    survivorMutant.scatterInstances({
      ...MIX, occluders: [OCC_MIDDLE], rng: stream(MIX_STREAM),
    }).map((p) => p.variant), [0, 1, 2, 0]);
  check('N3 …and it agrees where nothing was subtracted, which is why it hides',
    survivorMutant.scatterInstances({ ...MIX, rng: stream(MIX_STREAM) })
      .map((p) => p.variant), mixed.map((p) => p.variant));
  // DETERMINISM: the production stream, twice, through the cell sampler.
  const CELL_MIX = {
    ring: [[0, 0], [64, 0], [64, 64], [0, 64]], cx: 0, cz: 0,
    densityPer100m2: 0.2, seed: scatterCellSeed('ta_mix', 0, 0, 0),
    variantCount: 3,
  };
  check('N3 the same cell answers the same mix twice — no load order in it',
    scatterCellInstances(CELL_MIX).map((p) => p.variant),
    scatterCellInstances(CELL_MIX).map((p) => p.variant));
  check('N3 …and it is the formula on the CELL seed, not on anything else',
    scatterCellInstances(CELL_MIX).map((p) => p.variant),
    scatterCellInstances(CELL_MIX).map((_p, i) =>
      scatterVariantIndex(scatterCellSeed('ta_mix', 0, 0, 0), i, 3)));
  // Each cell enters the ring at ITS OWN offset. Not "every neighbour differs"
  // — a hash is allowed to agree with its neighbour, and two of three cells
  // sharing an offset is the arithmetic working, not failing. What must not
  // happen is ONE offset for the whole wood, which would stamp the same mix
  // out every 64 m.
  const cellOffsets = [];
  for (let cz = 0; cz < 4; cz += 1) {
    for (let cx = 0; cx < 4; cx += 1) {
      cellOffsets.push(
        scatterVariantIndex(scatterCellSeed('ta_mix', 0, cx, cz), 0, 3));
    }
  }
  check('N3 …and the 16 cells of a wood do not all enter the ring together',
    new Set(cellOffsets).size, 3);
  // (N4) the regression proof: one variant is the world as it was
  const PLAIN = { ...MIX, variantCount: undefined };
  const plain = scatterInstances({ ...PLAIN, rng: stream(MIX_STREAM) });
  check('N4 without a variant count the instances carry three keys, as ever',
    plain.map((p) => Object.keys(p).sort()),
    plain.map(() => ['x', 'yaw', 'z']));
  for (const n of [undefined, 0, 1]) {
    check(`N4 variantCount ${String(n)} is byte for byte the old answer`,
      scatterInstances({ ...MIX, variantCount: n, rng: stream(MIX_STREAM) }),
      plain);
  }
  check('N4 …and the cell sampler passes that through untouched',
    scatterCellInstances({ ...CELL_MIX, variantCount: 1 }),
    scatterCellInstances({ ...CELL_MIX, variantCount: undefined }));
  check('N4 a mixed cell places the SAME props in the SAME places as a plain one',
    scatterCellInstances(CELL_MIX).map((p) => [p.x, p.z, p.yaw]),
    scatterCellInstances({ ...CELL_MIX, variantCount: 1 })
      .map((p) => [p.x, p.z, p.yaw]));
  // (N5) the meshes — the split `ground.ts buildScatter` builds them from
  const bucketsOf = (points, n) => {
    const buckets = Array.from({ length: n }, () => []);
    for (const p of points) (buckets[p.variant ?? 0] ?? buckets[0]).push(p);
    return buckets;
  };
  check('N5 the (N3) cell fills three buckets 2 / 2 / 1 — three meshes',
    bucketsOf(mixed, 3).map((b) => b.length), [2, 2, 1]);
  check('N5 …with the occluder it is 2 / 2 / 0, so variant 2 gets NO mesh',
    bucketsOf(subtracted, 3).map((b) => b.length), [2, 2, 0]);
  check('N5 …and a split never loses a prop',
    [bucketsOf(mixed, 3).reduce((s, b) => s + b.length, 0),
      bucketsOf(subtracted, 3).reduce((s, b) => s + b.length, 0)],
    [mixed.length, subtracted.length]);
  check('N5 one variant is one bucket — the entry the row always had',
    bucketsOf(plain, 1).map((b) => b.length), [plain.length]);
  // …and that this is really what the client does, pinned by its source (E).
  const mixSrc = await readFile(GROUND_SRC, 'utf8');
  check('N5 buildScatter tells the sampler how many variants there are',
    mixSrc.includes('variantCount: kinds.length'), true);
  check('N5 …buckets the points by the sampler\'s answer, never by a count',
    mixSrc.includes('(buckets[p.variant ?? 0] ?? buckets[0]).push(p)'), true);
  check('N5 …and builds one entry per (row, variant)',
    mixSrc.includes('kinds.forEach((kind, variantPos) => {')
    && mixSrc.includes('const points = buckets[variantPos];'), true);
  check('N5 …skipping a variant nothing picked, so it costs no download',
    /const points = buckets\[variantPos\];[\s\S]{0,400}?if \(!points\.length\) return;/
      .test(mixSrc), true);
  check('N5 the client never CALLS the formula itself — the sampler decides',
    /scatterVariantIndex\(/.test(mixSrc), false);
  check('N5 the payload list it reads is `model_variants` (§ A9)',
    mixSrc.includes('const list = entry.model_variants;'), true);

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
      footprints: [FP_OVER_FIRST],
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
  // …and the wiring of section (M) on the client side, which is not maths and
  // can only be read: the clearance goes INTO the sampler, and it is derived
  // from the measured spread of the entry's own meshes at its planted height.
  check('E ground.ts hands the clearance to the cell sampler',
    groundSrc.includes('          clearM,\n'), true);
  check('E …derived from the measured spread, or estimated from the height',
    groundSrc.includes(
      'const clearM = scatterClearM(h, spread === null ? null : spread * h);'),
    true);
  check('E …and the measurement is filed where the mesh is grounded',
    groundSrc.includes('noteSpread(url, geometry);'), true);

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

  console.log('\n(H8) the ground offset — how deep a scattered prop stands');
  // The second fact the payload puts on a scatter entry from the PROP's
  // record (§ A9, 2026-08-20). The instances of a painted scatter are seated
  // client-side, so the seat is `heightAt(x, z) + this` — a fir at −0.2 sinks
  // 20 cm into the ground in a wood exactly as it does in a room.
  const { SCATTER_GROUND_OFFSET_LIMIT_M, scatterGroundOffset }
    = await loadTs(LOD_SRC);
  check('H8 the limit is the server\'s own ±5 m', SCATTER_GROUND_OFFSET_LIMIT_M, 5);
  check('H8 a stated sink is passed through', scatterGroundOffset(-0.2), -0.2);
  check('H8 …and a stated lift as well', scatterGroundOffset(0.35), 0.35);
  // An absent key is the NORMAL case here (the server ships it only when it
  // differs), so it has to read as "on the ground" and not as anything else.
  for (const [bad, name] of [[undefined, 'undefined'], [null, 'null'],
    [NaN, 'NaN'], ['x', 'a string']]) {
    check(`H8 ${name} means "on the ground"`, scatterGroundOffset(bad), 0);
  }
  check('H8 a hand-edited -99 cannot bury a wood', scatterGroundOffset(-99), -5);
  check('H8 …and a 99 cannot launch it', scatterGroundOffset(99), 5);
  // The seat itself, hand-derived: ground 12.5 m under the instance, entry at
  // −0.2 → 12.3; the same instance on an entry without the key stays at 12.5.
  check('H8 an instance at ground 12.5 with −0.2 is seated at 12.3',
    12.5 + scatterGroundOffset(-0.2), 12.3);
  check('H8 …and without the key at 12.5 exactly',
    12.5 + scatterGroundOffset(undefined), 12.5);
  // (H8a) THE one place — asserted on ground.ts, like (E)/(H6).
  const sinkCalls = groundSrc.match(
    /scatterGroundOffset\(entry\.ground_offset_m\)/g);
  check('H8a ground.ts reads the offset in exactly ONE place',
    sinkCalls ? sinkCalls.length : 0, 1);
  check('H8a …and every instance is seated with it',
    groundSrc.includes('const y = heightAt(p.x, p.z) + entrySink;'), true);
  check('H8a no seat uses the bare sample any more',
    groundSrc.includes('const y = heightAt(p.x, p.z);'), false);
  // (H8b) the red counter-check
  const noSink = await loadTs(LOD_SRC, ignoreGroundOffset);
  check('H8b the "ignore the offset" mutant seats the fir at 12.5',
    12.5 + noSink.scatterGroundOffset(-0.2), 12.5);
  checkNot('H8b …which is NOT where the real rule seats it',
    12.5 + scatterGroundOffset(-0.2), 12.5);

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
