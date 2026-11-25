# scatter_math

- Origin: `client3d/scripts/smoke_scatter_math.mjs` @ 011cd048aa3cc2937186d7f35d2203af9491db8a
- Executed by: `native/tests/ScatterVectorTests.cs`, `native/tests/ScatterRowVectorTests.cs`
- Vectors: `shared/test-vectors/scatter.json`, `shared/test-vectors/scatter_rows.json`

## Derivation

```text
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
 * transpile is enough — no bundler, no stand-ins. The one exception is
 * `scatterAxis.ts` (sections R, T, U, X), which imports the ring primitives
 * from `scatter.ts` and is therefore BUNDLED (`loadBundled`) — a second
 * import-free copy of `pointInRing` is exactly what this package exists to
 * prevent. For the same reason the ROAD BAND of (R8) comes out of the
 * renderers' own `strokeToPolygon` (`loadStrokeToPolygon`, bundled from
 * `frontend/src/tabs/map/mapMath.ts`): a road's sides are only the sides of
 * the ring the renderers really draw.
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
 * (A2) THE SAME TREE with a target height of 4:
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
 *      With a target of 1: height = 2, scale = 0.5,
 *      offsetY = -0.5 * 0.5 = -0.25 -> box from 0 to 1.
 *
 * (A5) A FLAT PROP (a decal plane): minY = maxY = 0.7.
 *      height = 0, so no scale is possible however tall the target — scale
 *      stays 1 and offsetY = -0.7 lays it on the ground. An infinite scale
 *      would make it vanish.
 *      Checked with a target of 3 as well: still scale 1, offsetY -0.7.
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
 *      E8 acceptance round). A scatter entry whose prop has no record no
 *      longer hands `null` in — `client3d/src/scene/ground.ts` passes its
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
 * (N6) THE PINNED VARIANT (Task 8, 2026-09-10). A row may name the variant
 *      EVERY one of its instances shows — `variant`, the list position the
 *      server stores for every scatter row since this day, not only for a
 *      centred one:
 *
 *          variant = min( max( floor(variant), 0 ), n − 1 )      (pinned)
 *                  = ( FNV-1a(seed) + ordinal ) mod n            (absent / NaN)
 *
 *      It replaces the formula's ANSWER and nothing else: the stream, every
 *      verdict and x/z/yaw are the (N3) run byte for byte — only the
 *      `variant` field of the returned instances changes. On the (N3)
 *      fixture with `variant: 1`: the same five points (2,4) (5,5) (10,10)
 *      (15,6) (8,16) with the same yaws 0, τ/4, π, 0, 0, every one variant
 *      1. `variant: 9` at n = 3 -> 2 (clamped to the last), `-1` -> 0 (the
 *      first), NaN -> the formula's 0 1 2 0 1 of (N3). n = 1 stays without
 *      a `variant` key even when pinned: a prop with one mesh has nothing
 *      to choose, whatever the row says.
 *      THROUGH THE CELL SAMPLER, the path the authored scatter really takes:
 *      cell (0, 0) at density 0.125 wants round(4096/100 · 0.125) = 5, and
 *      the (N3) stream scaled to the 64 m cell lands c0 at (6.4, 12.8), c1
 *      at (16, 16), c2 at (32, 32), c3 at (48, 19.2), c4 at (25.6, 51.2);
 *      the 20 × 20 square keeps c0 and c1 alone. Free: variants 0, 1 (the
 *      ordinals 0, 1 on the seed 'A', whose hash is divisible by 3, N1);
 *      pinned 1: 1, 1 — at the same two points, yaws 0 and τ/4.
 *      THE EDGE SAMPLER (X9, below): the (X2) fixture — RECT, spacing 7,
 *      offset 1, three variants, the footprint dropping station 0 — with
 *      `variant: 2` keeps the three survivors (9, 0.5) (6.5, 3) (1, 3.5) and
 *      their yaws π, π/2, 0, all variant 2; `variant: 5` -> 2, `-3` -> 0.
 *
 * ============================================================================
 * (S) THE MINIMUM SPACING — a row's own props keep their distance (2026-08-23)
 * ============================================================================
 * A scatter row may author `min_spacing_m`: the least distance two instances
 * OF THAT ROW may stand apart. The sampler takes it as `minSpacingM` and turns
 * it into ONE MORE SUBTRACT-ONLY VERDICT, asked after the ring, the occluders
 * and the footprints, on a candidate that has already drawn all three of its
 * numbers:
 *
 *     rejected  <=>  hypot(x - a.x, z - a.z) < minSpacingM
 *                    for an instance `a` this run has ALREADY ACCEPTED
 *
 * STRICTLY LESS, exactly as the footprint clearance is (`footprintBlocks`,
 * section M): a prop at exactly the authored distance STANDS. Two of the four
 * survivors below sit at exactly 4.0 m from the first, so a `<=` cannot pass
 * this section.
 *
 * THE FIXTURE, a 10 x 10 m ring (0,0) (10,0) (10,10) (0,10): area 100 m2, so
 * density 5 wants round(100/100 * 5) = 5 instances, and `triesPerPoint` 1
 * bounds the run at exactly five candidates — 15 numbers, the whole run on
 * paper. x = 0 + r*10, z = 0 + r*10, yaw = r*2pi:
 *
 *     c0  0.10, 0.10, 0.00  -> ( 1, 1) yaw 0
 *     c1  0.30, 0.30, 0.00  -> ( 3, 3) yaw 0
 *     c2  0.50, 0.10, 0.50  -> ( 5, 1) yaw pi
 *     c3  0.80, 0.40, 0.25  -> ( 8, 4) yaw tau/4
 *     c4  0.10, 0.50, 0.00  -> ( 1, 5) yaw 0
 *
 * (S1) SPACING 0 IS TODAY, EXACTLY. All five candidates lie in the ring and
 *      nothing else rejects, so the list is those five points. `minSpacingM`
 *      absent, 0, -1 and NaN must all give that same list — and on the SEEDED
 *      path (no hand-fed stream) too, which is the regression proof: a world
 *      that never touches the field is sampled byte for byte as before.
 *
 * (S2) SPACING 4, BY PAIRWISE DISTANCE. Every candidate is measured against
 *      the ones ALREADY ACCEPTED, in order:
 *        c0 (1,1)  nothing placed yet                     -> KEPT
 *        c1 (3,3)  to (1,1): hypot(2,2) = sqrt 8  = 2.8284 < 4  -> DROPPED
 *        c2 (5,1)  to (1,1): hypot(4,0)          = 4.0000 not < 4 -> KEPT
 *        c3 (8,4)  to (1,1): hypot(7,3) = sqrt 58 = 7.6158
 *                  to (5,1): hypot(3,3) = sqrt 18 = 4.2426 -> KEPT
 *        c4 (1,5)  to (1,1): hypot(0,4)          = 4.0000 not < 4
 *                  to (5,1): hypot(4,4) = sqrt 32 = 5.6569
 *                  to (8,4): hypot(7,1) = sqrt 50 = 7.0711 -> KEPT
 *      -> [ {1,1,0}, {5,1,pi}, {8,4,tau/4}, {1,5,0} ]. Note c1 is measured
 *      against (1,1) ALONE: a candidate the spacing drops is not there to
 *      crowd anybody, which is what "already accepted" means.
 *      THE YAWS ARE (S1)'S YAWS. All three numbers are drawn before any
 *      verdict, so the spacing SUBTRACTS the crowded prop and leaves the
 *      others exactly where and how they stood — the property of (C2), (C8)
 *      and (M4), now with a fourth kind of rejection.
 *
 * (S3) FOUR OF FIVE, AND THE SAMPLER DOES NOT GO LOOKING FOR A FIFTH. The
 *      budget stays `wanted * triesPerPoint` = 5 candidates; an entry whose
 *      spacing its density cannot afford simply ends up thinner. The stream
 *      of exactly 15 numbers proves it: `stream()` throws on the 16th, so a
 *      sampler that raised its tries to fill the count could not pass (S2) at
 *      all.
 *
 * (S4) THE EDGE IS REAL, FROM THE OTHER SIDE. The same run at spacing 4.01
 *      loses BOTH 4.0 m props: c2 and c4 are now inside the radius, and c3 is
 *      then measured against (1,1) alone (7.6158) and stands.
 *      -> [ {1,1,0}, {8,4,tau/4} ], two instead of four.
 *      And at spacing 2.5, which every pair of the five already keeps (the
 *      closest is 2.8284), the answer is (S1) verbatim: a spacing nobody
 *      violates changes nothing.
 *
 * (S5) THE CANDIDATE ORDINAL SURVIVES IT — the variant rule of (N3), tested
 *      against the new verdict. With three variants and the seed 'A' (whose
 *      hash is divisible by 3, see N1, so the ring starts at 0) the survivors
 *      c0, c2, c3, c4 must show (0 + candidate) mod 3:
 *        c0 -> 0,  c2 -> 2,  c3 -> 0,  c4 -> 1
 *      Counting over the SURVIVORS instead would give 0, 1, 2, 0 — every prop
 *      behind a crowded one a different species, and the whole reason the
 *      ordinal is the candidate's.
 *
 * (S6) THE PREFIX PROPERTY STILL HOLDS (the one the editor's thinned preview
 *      rides on, C14). Acceptance of a candidate depends only on the
 *      candidates BEFORE it, so a lower `maxPoints` still yields the head of
 *      the same list: on a 100 x 100 m ring at density 0.5 (wanted 50) with
 *      spacing 4, `maxPoints` 10 gives the first 10 of those 50. A property,
 *      not a recorded value — the seeded stream cannot be simulated on paper.
 *
 * (S7) THROUGH THE CELL SAMPLER, which is where the authored scatter really
 *      goes. Cell (0,0) is 0..64 in both axes, so x = r*64, z = r*64, and
 *      density 0.09765625 wants round(40.96 * 0.09765625) = 4 candidates at
 *      the cell sampler's fixed one try each:
 *        0.015625, 0.015625, 0.00 -> ( 1, 1) yaw 0
 *        0.046875, 0.046875, 0.00 -> ( 3, 3) yaw 0      -> 2.8284 m, DROPPED
 *        0.078125, 0.015625, 0.50 -> ( 5, 1) yaw pi     -> 4.0 m,    KEPT
 *        0.125000, 0.062500, 0.25 -> ( 8, 4) yaw tau/4  -> 4.2426 m, KEPT
 *      -> three props, the (S2) arithmetic on the cell's own box.
 *
 * (S8) THE RED COUNTER-CHECK — the mutant that makes the grid a lie. The
 *      accepted points are bucketed by a grid of exactly `spacing` metres and
 *      a candidate looks at its own bucket AND THE EIGHT AROUND IT; the mutant
 *      looks only at its own. Derivation, on a 10 x 10 ring at density 2
 *      (wanted 2, one try each) with spacing 4:
 *        0.39, 0.10, 0.00 -> (3.9, 1)  bucket (floor(3.9/4), floor(1/4)) = (0,0)
 *        0.41, 0.10, 0.00 -> (4.1, 1)  bucket (floor(4.1/4), floor(1/4)) = (1,0)
 *      The two stand 0.2 m apart — a fifth of the authored spacing — but in
 *      NEIGHBOURING buckets, so the mutant keeps both and the true sampler
 *      keeps one. A grid that only ever looked in its own cell would enforce
 *      nothing at all across a bucket border, which is most of the map.
 *
 * ============================================================================
 * (P) THE PLACED PROPS' BOXES — scatter does not grow inside a bench
 * ============================================================================
 * A world prop (`app/models/world_props.py`, § A9b) is ONE prop placed by hand
 * at one point: a landmark rock, a signpost, a bench in the wilderness. The
 * sampler knew placed LOCATIONS and nothing else, so the scatter grew straight
 * through every one of them. The fix adds NO rule: the server hands out the
 * box each placement occupies (`prop_boxes`: centre, `yaw_deg`, `half_w`,
 * `half_d` — half the prop's real width and depth plus a 0.25 m margin) and
 * `propBoxFootprint` turns it into the very `ScatterFootprint` a location
 * contributes.
 *
 * THE FIXTURE, used by every case below: a 4 x 2 m prop at (5, 5), yaw 30°,
 * i.e. `half_w` 2, `half_d` 1 — the margin is the server's, so the numbers
 * here are the box as it arrives. With
 *
 *     cos 30° = 0.8660254037844386,  sin 30° = 0.5
 *
 * the four corners follow from § A1.1
 *     x = 5 + lx·cos + lz·sin,   z = 5 - lx·sin + lz·cos
 * over the local corners (-2,-1), (+2,-1), (+2,+1), (-2,+1):
 *
 *     (-2,-1) -> x = 5 - 1.7320508075688772 - 0.5 = 2.7679491924311228
 *                z = 5 + 1 - 0.8660254037844386   = 5.133974596215561
 *     (+2,-1) -> x = 5 + 1.7320508075688772 - 0.5 = 6.232050807568877
 *                z = 5 - 1 - 0.8660254037844386   = 3.1339745962155614
 *     (+2,+1) -> x = 5 + 1.7320508075688772 + 0.5 = 7.232050807568877
 *                z = 5 - 1 + 0.8660254037844386   = 4.866025403784439
 *     (-2,+1) -> x = 5 - 1.7320508075688772 + 0.5 = 3.7679491924311228
 *                z = 5 + 1 + 0.8660254037844386   = 6.866025403784439
 *
 * (P1) THE CORNERS, exactly those four, in that order.
 *
 * (P2) A BOX THAT ENCLOSES NOTHING IS NO BOX: a non-finite centre, a
 *      half-extent of 0 or a negative one give `null`, and `propBoxFootprints`
 *      drops them instead of passing an empty outline on. A missing `yaw_deg`
 *      is read as 0 — a box that is not turned, which is what "no turn" means.
 *
 * (P3) WHICH CANDIDATES DIE, on a 10 x 10 ring (0..10 in both axes) at density
 *      7 over 100 m² -> wanted 7, `triesPerPoint` 1 -> exactly 7 candidates.
 *      The stream feeds (x/10, z/10, 0) per candidate, so `yaw` is 0
 *      throughout and `x = 10·r`. Each is judged in the BOX's own frame
 *      (`worldToLocalXZ`, the inverse of the mapping above):
 *
 *          lx = dx·cos - dz·sin,   lz = dx·sin + dz·cos,   d = point - (5,5)
 *          inside  <=>  |lx| <= 2  and  |lz| <= 1
 *
 *        1. (5, 5)      lx 0, lz 0                          -> INSIDE, dies
 *        2. (6, 5)      lx 0.8660254, lz 0.5                -> INSIDE, dies
 *        3. (5, 6)      lx -0.5, lz 0.8660254               -> INSIDE, dies
 *        4. (3.2, 4.2)  lx -1.5588457+0.4  = -1.1588457
 *                       lz -0.9-0.6928203  = -1.5928203     -> outside, stands
 *        5. (7.1, 4.8)  lx  1.8186533+0.1  =  1.9186533
 *                       lz  1.05-0.1732051 =  0.8767949     -> INSIDE, dies
 *        6. (1, 1)      lx -3.4641016+2 = -1.4641016
 *                       lz -2-3.4641016 = -5.4641016        -> outside, stands
 *        7. (9, 9)      lx  3.4641016-2 =  1.4641016
 *                       lz  2+3.4641016 =  5.4641016        -> outside, stands
 *
 *      -> three instances survive: (3.2, 4.2), (1, 1), (9, 9).
 *
 *      CANDIDATES 4 AND 5 ARE THE POINT OF THE ROTATION, one in each
 *      direction. The prop's axis-aligned bounding box is x 3..7, z 4..6:
 *      (3.2, 4.2) lies INSIDE that box and outside the real prop, (7.1, 4.8)
 *      lies OUTSIDE it and inside the real prop. Either mistake is visible on
 *      the map — a bare patch where nothing stands, a tree inside the bench.
 *
 * (P4) THE RED COUNTER-CHECK: a mutant whose corners are built with cos 1 /
 *      sin 0, i.e. the axis-aligned box 3..7 × 4..6. It must NOT reproduce
 *      (P3)'s answer. Its own, candidate by candidate:
 *        1. (5, 5)     inside 3..7 × 4..6                 -> dies
 *        2. (6, 5)     inside                             -> dies
 *        3. (5, 6)     exactly on the MAX-Z edge, which the half-open ray cast
 *                      puts outside (`pointInFootprint`) -> stands
 *        4. (3.2, 4.2) inside                             -> dies
 *        5. (7.1, 4.8) x 7.1 > 7                          -> stands
 *        6./7.                                            -> stand
 *      -> [(5,6), (7.1,4.8), (1,1), (9,9)]: the swap derived above —
 *      (3.2, 4.2) gone, (7.1, 4.8) standing — and (5, 6) on top of it, which
 *      the TURNED box contains squarely (lz 0.866 < 1) and the square only
 *      grazes. Three of the seven verdicts differ; the mutant is not a near
 *      miss, it is a different prop.
 *
 * (P5) A BOX FULLY INSIDE A LOCATION FOOTPRINT IS REDUNDANT, NEVER HARMFUL.
 *      The square 2..8 × 2..8 contains every corner of the fixture box (x
 *      2.768..7.232, z 3.134..6.866), so with both footprints the answer must
 *      be the location's alone: candidates 1-5 all lie in 2..8 × 2..8 and die
 *      there, 6 and 7 stand -> [(1,1), (9,9)] with or without the box. The
 *      server drops such a box (`prop_boxes` skips a placement inside a
 *      boundary), and this is the proof that dropping it is an economy and not
 *      a behaviour.
 *
 * (P6) SAME AREA OR ANOTHER, THE BOX EXCLUDES. A scattered copy is not
 *      "placed": only hand-placed props make boxes, and every entry of every
 *      area is sampled around all of them. Checked as maths (the same box
 *      excludes the same candidate under two different area seeds) and as
 *      WIRING on `ground.ts`, which holds ONE `footprints` list — the drawn
 *      location outlines plus `propBoxFootprints(payload.prop_boxes)` — and
 *      hands that one list to every cell of every area.
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
 * (G) HOW TALL A SCATTERED PROP IS — `scatterTargetH` (finding 12; Task 9)
 * ============================================================================
 * The height that goes into (A) is the prop's OWN, and nothing else — since
 * Task 9 (2026-09-10) the row carries no height of its own:
 *
 *   1. `prop_height_m`, the prop's real height from the library, shipped by
 *      `GET /play/terrain` (`app/models/terrain.with_scatter_props`).
 *   2. `SCATTER_MODEL_HEIGHT_M` = 2.0 m — only where there is no prop at all.
 *
 * Before finding 12 step 1 did not exist and step 2 was the default, so an
 * 8.5 m tree from the library was drawn at 2 m: avatar height, which is the
 * screenshot in the finding. Between finding 12 and Task 9 an authored
 * `height_m` on the row could still overrule the library; that field is
 * retired, and the function takes ONE argument.
 *
 * (G1) THE PROP'S HEIGHT: (8.5) -> 8.5, not 2 — the tree is as tall as the
 *      Props tab says.
 * (G2) NO PROP: (undefined) -> 2. The flat fallback survives for the URL no
 *      prop record answers for.
 * (G3) "NOT GIVEN" IS EVERY NON-POSITIVE AND EVERY NON-NUMBER, because the
 *      value crosses a JSON boundary: (0) · (-1) · (NaN) · (null) -> 2.
 * (G4) ONE ARGUMENT: `scatterTargetH.length` is 1, and a stale `height_m`
 *      handed in the old first position is read as the prop height it is
 *      not — the pin that no caller may still pass a row height.
 * (G5) the red counter-probe: a mutant that ignores the prop and always
 *      answers the fallback says 2 for (8.5), which the real one does not.
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
 * (V) THE VIEW CONE — what is behind the player is not binned (2026-08-24)
 * ============================================================================
 * The binning had no view test at all: every instance inside the cull distance
 * got a tier, a thinning roll and a slot in an instance buffer, whether it
 * stood in front of the camera or behind it. Measured on the reporting iGPU
 * only ~20 % of the submitted mesh instances and 6…17 % of the billboards were
 * inside the horizontal field of view; the rest was written, uploaded and
 * clipped. Three functions, all pure, all in `scene/scatterLod.ts`.
 *
 * THE CLOSED FORM THIS SECTION DERIVES ITS THRESHOLDS FROM, so the expectation
 * does NOT retrace the module's own `atan`/`cos` chain. With
 *
 *     u = tan(hfov/2) = tan(vfov/2) · aspect        (the horizontal fov)
 *     a = hfov/2,  so  cos a = 1/√(1+u²),  sin a = u/√(1+u²)
 *
 * and the margin exactly 30° (cos 30° = √3/2, sin 30° = 1/2):
 *
 *     cosHalf = cos(a + 30°) = cos a · √3/2 − sin a · 1/2
 *             = (√3 − u) / (2·√(1+u²))
 *
 * (V1) horizontalFovRad — the aspect is really read.
 *      - (90°, 1): tan 45° = 1, ·1 = 1, atan 1 = 45° ⇒ hfov = 90° = π/2.
 *      - (2·atan(0.5) = 53.13010235415598°, 2): tan of the half is 0.5, ·2 = 1
 *        ⇒ hfov = π/2 again. The same answer from another pair, so a function
 *        ignoring `aspect` cannot pass both.
 *      - (90°, 2): 1·2 = 2 ⇒ hfov = 2·atan 2 = 2.214297435588181 rad
 *        (126.86989764584402°).
 *      - JUNK IS NaN, not a guess: fov 0 / 180 / negative / NaN, aspect 0 /
 *        negative / NaN / Infinity. `viewCone` turns that into a cone that
 *        accepts everything — a broken camera draws too much, never too little.
 *
 * (V2) viewCone — the direction is normalised once, the cosine comes from the
 *      formula above.
 *      - (0, −2) at hfov π/2 ⇒ fwd (0, −1) exactly (a length of 2 divided out),
 *        cosHalf = (√3 − 1)/(2√2) = 0.7320508075688772 / 2.8284271247461903
 *        = 0.25881904510252074 — which is cos 75° = (√6 − √2)/4, i.e. 45° of
 *        half-fov plus the 30° margin. Both spellings are asserted.
 *      - (3, 4) ⇒ (0.6, 0.8): the 3-4-5 triangle, so the normalisation is
 *        checked on a vector no rounding can hide.
 *      - THE CLIENT'S OWN CAMERA: `new THREE.PerspectiveCamera(45, …)`
 *        (`scene/engine.ts`) on a 16:9 window. tan 22.5° = √2 − 1 (half-angle
 *        formula), so u = 16(√2 − 1)/9 = 0.7363796664410581 and
 *        cosHalf = (√3 − u)/(2√(1+u²)) ≈ 0.4008. The half-angle that belongs
 *        to it lies between 66° and 67° (cos 66° = 0.40674 is inside,
 *        cos 67° = 0.39073 is not) — checked as such, so the number stays a
 *        statement about an ANGLE rather than a recorded decimal.
 *      - THE THREE DEGENERATE CASES, all "accept everything" (cosHalf = −1):
 *        a forward vector of length 0 (a camera looking straight down), a
 *        non-finite or non-positive hfov, and a half-angle at or past 180°
 *        (hfov 320° ⇒ half 190°, where `Math.cos` would start CLOSING the cone
 *        again: cos 190° = −0.985 would reject the 175° direction that the
 *        360°-wide cone plainly contains).
 *
 * (V3) inViewCone — THE 40 m NEAR KEEP, on fwd (0, 1) and cos 75°.
 *      - (0, −39): dead behind, 39 m ⇒ kept. (0, −40): kept, the line is
 *        inclusive. (0, −40.001): dropped — dot = −40.001 against
 *        cos 75° · 40.001 = 10.353.
 *      - (40, 0) dead sideways: kept. (41, 0): dot = 0 against 10.61 ⇒ dropped.
 *      - A NaN offset is KEPT: `!(NaN > 1600)` is true, and the distance tests
 *        around the call already refuse a degenerate instance.
 *
 * (V4) inViewCone — THE ANGLE, both sides of the line and both sides of the
 *      axis. A point at 100 m and θ off the forward axis is
 *      (100 sin θ, 100 cos θ), so `dot/len` is exactly cos θ and the test is
 *      `cos θ ≥ cos 75°`:
 *        θ = 0 ⇒ in, θ = ±74.9° ⇒ in, θ = ±75.1° ⇒ out, θ = 180° ⇒ out.
 *      A tenth of a degree either side and not the line itself: at exactly 75°
 *      the two sides of the comparison are the same real number reached by two
 *      different float paths, so which way it falls is a matter of one ulp and
 *      pinning it would pin the rounding, not the rule. THE `≥` ITSELF is
 *      pinned exactly where floats are exact instead — with cosHalf = 0 (a
 *      90° half-cone) the point (100, 0) gives dot = 0 ≥ 0 and is IN, while
 *      (100, −0.001) gives −0.001 and is OUT.
 *
 * (V5) THE MARGIN IS REAL — the red counter-check for it. On the 90° fixture
 *      the frustum edge is 45°; a tree at 50° off-axis is inside the cone
 *      (cos 50° = 0.6428 ≥ 0.2588) and would be dropped by a mutant whose
 *      margin is 0 (0.6428 ≥ cos 45° = 0.7071 is false). That wedge is what a
 *      turn between two LOD passes would show as bare ground. Shadows play no
 *      part in the margin: no stage of the scatter casts one.
 *
 * (V6) THE NEAR KEEP IS REAL — the second mutant, with its line deleted. A
 *      tuft 5 m dead behind the camera (0, −5): the real rule keeps it, the
 *      mutant drops it (dot = −5 against cos 75° · 5 = 1.294). Under a steep
 *      look-down the XZ forward points far past the ground actually in the
 *      picture, which is the whole reason the near ring is never cut.
 *
 * ============================================================================
 * (W) THE SEAM AT THE CULL LINE — the billboards CONTINUE the mesh thinning
 * ============================================================================
 * The two thinnings are two halves of one line and are checked together, which
 * is why they are checked HERE and not only in `smoke_impostors.mjs`: the
 * property is a relation between `instanceShare` (the meshes) and
 * `impostorShare` (the billboards), and a file that saw only one of them could
 * not see the step between them.
 *
 * WHAT WAS WRONG (the acceptance finding of 2026-08-22, decided 2026-08-24).
 * The mesh line thins to `SCATTER_MIN_SHARE` = 0.25 by the cull distance, and
 * the billboard line RESTARTED at a full 1 there — so crossing 120 m outwards
 * the wood got four times denser in one step. Its span was calibrated to
 * `IMPOSTOR_FAR_M` = 400 m on top of that, a distance the sampled cell window
 * never reaches, so the thinning was never really applied either.
 *
 * (W1) CONTINUITY, and it is by construction rather than by a tuned number:
 *        instanceShare(120, DEF) = 1 − (75/75)·0.75      = 0.25
 *        impostorShare(120⁺, DEF) = 0.25 · (1 − 0⁺·0.75) = 0.25
 *      The window is OPEN at the near end (`impostorInWindow`), so the
 *      billboard side is read just past the line, at 120.000001 m. Checked
 *      with the second cfg too (cullM = 60): both sides give 0.25 there, so
 *      the rule follows the argument and not the module's constants.
 *
 * (W2) THE REAL REACH OF THE WINDOW, derived exactly as the cost diagnostics
 *      derived it. The scatter is sampled in the `(2k+1)²` square of 64 m
 *      cells around the anchor's own cell, `k = scatterCellSpan(cullM)` (K6),
 *      and nothing outside it exists to be drawn. With the anchor anywhere
 *      inside its own cell:
 *        cull 120 → k = 2 → guaranteed  2·64      = 128 m
 *                           axis max    3·64      = 192 m
 *                           corner max  √2·3·64   = 271.5290039756343 m
 *      i.e. the "~130…270 m" of the diagnostics, against the 400 m the old
 *      span assumed. `impostorReachM` answers the CORNER, the supremum, so the
 *      line reaches its floor exactly where the last instance that can exist
 *      stands. Capped at `IMPOSTOR_FAR_M`: cull 300 → k = 5 → √2·6·64 = 543 m
 *      → 400.
 *
 * (W3) THE LINE ITSELF, `share(d) = 0.25 · (1 − t·0.75)`,
 *      `t = min((d − cullM)/(reach − cullM), 1)`:
 *        the midpoint (120 + 151.5290039756343/2 = 195.76450198781714 m) → t = 0.5
 *          → 0.25 · 0.625 = 0.15625, a hand-exact number at an irrational
 *            distance, which is the case that pins the SHAPE of the line.
 *        the corner (271.5290039756343 m) → t = 1 → 0.25 · 0.25 = 0.0625
 *        400 m (past the corner, inside the stage) → clamped, 0.0625 as well
 *        120 m and nearer → 0, there is no billboard share at all there.
 *      MONOTONE NON-INCREASING over the whole walk: 0…400 m in 0.5 m steps of
 *      the combined line (meshes up to `cullM`, billboards past it) never
 *      rises — 801 samples, and the step at the seam is the one it would show.
 *
 * (W4) THE RED COUNTER-CHECK is the OLD rule, restored by mutating the source:
 *      the span back to `IMPOSTOR_FAR_M − cullM` and the start back to 1. It
 *      answers 1 just past the cull line where the truth is 0.25 (the 4×
 *      step), 0.8125 at 190 m where the real line is already at 0.1633, and
 *      its combined walk is NOT monotone. Same 1000 indices, same hash: the
 *      mutant draws about 4× the billboards the rule now draws at 190 m.
 *
 * ============================================================================
 * (Q) THE TURN — `scatterYaw` (§ A9, 2026-09-09; `aligned` 2026-09-10)
 * ============================================================================
 * The third draw of every candidate, `r`, becomes the instance's yaw by the
 * entry's mode. Since 2026-09-10 there is ONE authored mode, and it is
 * RELATIVE to the local surface axis (section R) — the absolute `fixed` and
 * `quarter` of the day before are gone without a reader:
 *
 *     random (no mode)  r · 2π
 *     aligned           axis + deg · π/180        normalised to [0, 2π)
 *
 * Yaw convention: rotation about +y, facing vector (sin yaw, cos yaw), 0 = +z,
 * π/2 = +x. The axis is handed in as the fourth argument (`axisRad`, default
 * 0), so the function itself stays pure arithmetic.
 *
 * (Q1) r = 0.25, no mode        -> 0.25 · 2π = π/2 = 1.5707963…
 *      the same r, mode "spin"  -> unknown mode reads as random, π/2 again;
 *      so does the retired "fixed" — there is no reader for it.
 * (Q2) aligned, axis π/2, deg 0  -> π/2 whatever r is (r = 0 and r = 0.99).
 *      aligned, axis π/2, deg 90 -> π/2 + π/2 = π.
 *      aligned, axis π/2, deg absent / NaN -> the axis alone, π/2.
 *      aligned, axis absent, deg 90 -> 0 + π/2 = π/2.
 * (Q3) NORMALISED: axis 3π/2, deg 90 -> 2π -> 0; axis 3π/2, deg 270 ->
 *      3π -> π. A renderer reads the number as an angle either way, but the
 *      smokes below compare it, and (X) expects "0 (mod 2π)".
 * (Q4) THE STREAM IS UNTOUCHED. The SQUARE of (C) sampled with the fed stream
 *      [0.5, 0.5, 0.25] gives ONE instance at (10, 10) with yaw π/2 under no
 *      mode; the SAME stream under aligned/deg 90 with an `axisAt` answering
 *      π/2 gives the same (10, 10) with yaw π. Two modes, one position — a
 *      mode turns props in place. Without `axisAt` the axis is 0 -> π/2.
 * (Q5) …and through the CELL sampler the same law: `scatterCellInstances`
 *      with yawMode "aligned" / yawDeg 45 and `axisAt` answering π/4 reads
 *      only yaws of π/2 for a cell of the SQUARE at density 1 (the seed of (K)
 *      draws whatever it draws, every instance still reads π/2).
 *      `axisAt` is asked about the SURVIVOR's own position: an `axisAt` of
 *      "1 for x > 10, else 0" turns every instance right of x = 10 by 1 and
 *      the rest not at all. And it is asked ONLY for survivors — the draw
 *      happens for every candidate (three numbers, (D)), the axis is a pure
 *      function of the position and costs a walk over the ring's edges, so
 *      the (N3) fixture with its occluder asks it 4 times, not 5.
 *
 * ============================================================================
 * (R) THE SURFACE AXIS — `ringEdgeAxis` / `lineAxis` (`scatterAxis.ts`)
 * ============================================================================
 * The axis of a polygon edge A -> B is oriented so that `axis + 90°` faces
 * INTO the polygon: d = (B − A)/|B − A|, heading = atan2(dx, dz); the facing
 * vector of heading + 90° is (sin(h + π/2), cos(h + π/2)) = (cos h, −sin h)
 * = (dz, −dx); if the edge's midpoint M pushed by ε along that vector lies in
 * the ring (`pointInRing`), the axis is heading, else heading + π (i.e. −d).
 * Nearest edge = least point-segment distance; a tie goes to the FIRST edge in
 * the ring (strict `<`). Answers are normalised to [0, 2π).
 *
 * THE FIXTURE, the 10 × 4 rectangle RECT = (0,0) (10,0) (10,4) (0,4), (x, z):
 *
 * (R1) point (5, 0.5): nearest is the bottom edge (z = 0), (0,0) -> (10,0),
 *      d = (1, 0), heading = atan2(1, 0) = π/2; heading + 90° = π -> facing
 *      (sin π, cos π) = (0, −1), which is −z = OUT of the rectangle -> −d,
 *      axis = atan2(−1, 0) = −π/2 -> normalised 3π/2. Check: 3π/2 + π/2 = 2π
 *      ≡ 0 -> facing (0, 1) = +z, into the rectangle. ✔
 * (R2) point (9.5, 2): the right edge (x = 10), (10,0) -> (10,4), d = (0, 1),
 *      heading = atan2(0, 1) = 0; + 90° = π/2 -> facing (1, 0) = +x = out
 *      -> −d, axis = atan2(0, −1) = π. Check: π + π/2 = 3π/2 -> facing
 *      (sin 3π/2, cos 3π/2) = (−1, 0) = −x, into the rectangle. ✔
 * (R3) point (5, 3.5): the top edge, (10,4) -> (0,4), d = (−1, 0), heading
 *      = atan2(−1, 0) = −π/2; + 90° = 0 -> facing (0, 1) = +z = out -> −d
 *      = (1, 0), axis = π/2. Check: π/2 + π/2 = π -> (0, −1), into. ✔
 *      point (0.5, 2): the left edge, (0,4) -> (0,0), d = (0, −1), heading
 *      = atan2(0, −1) = π; + 90° = 3π/2 -> facing (−1, 0) = −x = out -> −d
 *      = (0, 1), axis = atan2(0, 1) = 0. Check: 0 + π/2 -> (1, 0), into. ✔
 *      So the four edges read 3π/2, π, π/2, 0 — and the SAME four for the
 *      ring in the opposite winding: the inside test is winding-blind.
 * (R4) the tie at the centre (5, 2): 2 m to the bottom AND to the top edge,
 *      5 m to the sides -> the first edge in the ring wins -> 3π/2.
 *      A ring of two points is no ring -> 0.
 * (R5) `lineAxis` is the walking direction of the nearest segment, no inside
 *      test: [(0,0),(10,0),(10,10)] at (9, 0.2) -> the first segment (0.2 m
 *      against 1.0 m to the second), axis = atan2(1, 0) = π/2; at (10.3, 5)
 *      the second, axis = atan2(0, 1) = 0. One point is no line -> 0.
 * (R6) THE EDGE SELECTION — `ringSelectedEdges(ring, sides)` (Task 10,
 *      2026-09-10). Edge i is ring[i] -> ring[(i+1) mod n], the closing edge
 *      is n − 1. `undefined` / "all" / a word nobody knows -> every index;
 *      "longest" -> the longest edge, a tie to the SMALLER index; "opposite"
 *      -> the two longest, ascending, ties to the smaller indices. RECT:
 *      lengths 10, 4, 10, 4 -> longest [0] (edge 2 ties, 0 is smaller),
 *      opposite [0, 2], all [0, 1, 2, 3]. The L-shape (0,0) (10,0) (10,4)
 *      (4,4) (4,10) (0,10): lengths 10, 4, 6, 6, 4, 10 -> longest [0] (tie
 *      with edge 5), opposite [0, 5]. Two points are no ring -> [].
 * (R7) `ringEdgeAxis(ring, x, z, edges)` measures ONLY the listed edges.
 *      RECT at (5, 3.5): all -> the top edge, 0.5 m away, π/2 (R3); [0] ->
 *      the bottom edge is the only one measured, 3.5 m away -> 3π/2; [0, 2]
 *      -> the top again, π/2; [] -> nothing to measure -> 0. The tie rule
 *      is the loop's: at the centre (5, 2) under [0, 2] the bottom edge is
 *      checked first -> 3π/2, as in (R4). ABSENT `edges` is today's answer
 *      byte for byte, at every one of the four (R3) points and at the tie.
 *      `areaAxis(null, RECT, "longest")(5, 3.5)` -> 3π/2, without a sides
 *      word -> π/2 (the area's axis of before); with a LINE the word is
 *      ignored: `areaAxis(CORNER, RECT, "longest")(10.3, 5)` -> 0, the (R5)
 *      answer of the line.
 * (R8) THE ROAD SIDES OF A RIBBON — `ribbonSelectedEdges(ring, sides)`
 *      (Task 11, 2026-09-10). A road is a STROKE area, and its ring is the
 *      mitred band `strokeToPolygon` lays around the centre line: side A
 *      forward, side B back, `2n` points. Its edges are therefore
 *
 *          side A     0 … n−2        road end     n−1
 *          side B     n … 2n−2       road start   2n−1  (the closing edge)
 *
 *      and the SIDES of a road are those two chains — never "the longest
 *      edge" of the polygon, which on a road is one arbitrary piece of one
 *      kerb. THE FIXTURE IS THE RENDERERS' OWN BAND: the smoke bundles
 *      `strokeToPolygon` out of `frontend/src/tabs/map/mapMath.ts` rather
 *      than restating it — a second copy of the band rule is exactly what
 *      would rot. The straight road [(0,0),(100,0)] at width 6 is
 *      ROAD = (0,−3) (100,−3) (100,3) (0,3): the segment normal of d = (1,0)
 *      is (dz, −dx) = (0,−1), side A takes it at +3 (z = −3) and runs
 *      forward, side B at −3 (z = +3) and comes back. n = 2, so
 *          absent / "all" / a word nobody knows -> [0, 1, 2, 3]
 *          "longest"  -> [0]      side A; both sides are 100 m, a tie goes to A
 *          "opposite" -> [0, 2]   both sides, the two ends left out
 *      THE LONGER SIDE IS THE OUTER ONE OF A BEND. [(0,0),(50,0),(50,50)] at
 *      width 6 miters both joins (miter length 3/cos45° = 4.2426 <= 2·6, the
 *      corner point (50,0) ± (3,3)) to the band (0,−3) (53,−3) (53,50)
 *      (47,50) (47,3) (0,3): n = 3, side A = edges 0, 1 = 53 + 53 = 106,
 *      side B = edges 3, 4 = 47 + 47 = 94 -> "longest" = [0, 1], the outer
 *      kerb; "opposite" = [0, 1, 3, 4]. The mirrored bend
 *      [(0,0),(50,0),(50,−50)] turns the other way — band (0,−3) (47,−3)
 *      (47,−50) (53,−50) (53,3) (0,3), side A 47 + 47 = 94, side B 53 + 53
 *      = 106 -> "longest" = [3, 4]. So the answer is measured, not "always A".
 *      A ring with an ODD number of points is no band -> every edge; fewer
 *      than three points -> [] as in (R6).
 *
 * ============================================================================
 * (T) THE POLE OF INACCESSIBILITY — `polylabel` (Mapbox 2016)
 * ============================================================================
 * Quadtree cells over the bounding box, a priority queue on
 * `max = d + h · √2` (the farthest any point of the cell can be from the
 * boundary), the centroid cell as the first best, and a cell is not split
 * when `cell.max − bestD <= precision` — it cannot beat the best by more than
 * the tolerance. `d` is the signed distance to the ring: positive inside,
 * negative outside, measured with the very point-segment distance of
 * `footprintDistance`.
 *
 * (T1) RECT: the centroid is (5, 2), 2 m from top and bottom, 5 m from the
 *      sides -> d = 2, and nothing in a 4 m wide strip can be farther than
 *      2 m from its long edges, so no cell ever beats it (strict `>`):
 *      exactly (5, 2), d = 2. The brief allows ± precision 0.5 on the
 *      point; d is checked in [2 − 0.5, 2] — above 2 is impossible.
 * (T2) THE L-SHAPE (0,0) (10,0) (10,4) (4,4) (4,10) (0,10): the area is
 *      10·4 + 4·6 = 64, the centroid x = (40·5 + 24·2)/64 = 4.5,
 *      z = (40·2 + 24·7)/64 = 3.875 — INSIDE, but only 0.125 m under the
 *      inner top edge (10,4) -> (4,4). Both arms are 4 m wide, so the
 *      largest inscribed circle has radius 2 (in either arm, or at the
 *      corner square around (2, 2)). Expected: the point lies in the ring,
 *      d >= 1.9 (2 within the default precision 0.5 easily), and
 *      d_polylabel >= d_centroid − precision, both distances taken by the
 *      smoke's OWN segment walk (0.125 for the centroid).
 * (T3) fewer than three points -> { x: 0, z: 0, d: 0 }.
 *
 * ============================================================================
 * (U) STATIONS ALONG THE RING — `ringStations`
 * ============================================================================
 * Arc length is accumulated over the CLOSED ring (the last edge back to the
 * start included); station k sits at s = start + k · spacing for s < L
 * (start = spacing/2 unless authored, an authored start clamped to the
 * spacing as `strokeStations` clamps it), on the edge whose half-open span
 * [cum_i, cum_i+1) holds s, and it is pushed INWARD by `offsetM` along the
 * facing vector of `axis + 90°` — `n_in` — with the edge's axis of (R).
 * `ordinal` = k, counting stations a caller later rejects. The function does
 * NOT drop a pushed point that misses the ring — that is the caller's
 * subtraction (X).
 *
 * RECT, spacing 7, offset 1: L = 10 + 4 + 10 + 4 = 28, start = 3.5,
 * stations at s ∈ {3.5, 10.5, 17.5, 24.5} (31.5 >= 28 ends it):
 *
 * (U1) s = 3.5, edge 1 (0..10): P = (3.5, 0), axis 3π/2, n_in = facing of
 *      2π = (0, 1) -> (3.5, 1).
 *      s = 10.5, edge 2 (10..14, x = 10): P = (10, 0.5), axis π, n_in =
 *      facing of 3π/2 = (−1, 0) -> (9, 0.5).
 *      s = 17.5, edge 3 (14..24, z = 4, from (10,4) to (0,4)): P = (6.5, 4),
 *      axis π/2, n_in = facing of π = (0, −1) -> (6.5, 3).
 *      s = 24.5, edge 4 (24..28, x = 0, from (0,4) to (0,0)): P = (0, 3.5),
 *      axis 0, n_in = facing of π/2 = (1, 0) -> (1, 3.5).
 *      Ordinals 0..3; all four pushed points lie in the ring.
 * (U2) startM 0: s = 0 is the corner (0, 0) on edge 1 -> (0, 1); then s = 7
 *      -> (7, 1); s = 14 is the START of edge 3 (half-open), P = (10, 4),
 *      n_in (0, −1) -> (10, 3); s = 21 -> P = (3, 4) -> (3, 3).
 *      startM past the spacing clamps to it: startM 100 -> start 7 ->
 *      s = 7, 14, 21, three stations, ordinals 0..2.
 * (U3) a repeated closing point adds no edge and no station; spacing 0 or a
 *      two-point ring places nothing; offsetM absent = 0 -> the stations sit
 *      ON the ring: (3.5, 0), (10, 0.5), (6.5, 4), (0, 3.5).
 * (U4) THE SPACING JITTER (Task 9, 2026-09-10). With `jitterM` > 0 every
 *      station draws ONE number r_k from a SEPARATE stream — the row seed
 *      plus ':jitter', never the yaw stream — and
 *
 *          j_k = (2 · r_k − 1) · jitterM
 *          s_0 = start + j_0,   s_k = s_{k−1} + spacing + j_k,
 *          s_k < 0 -> 0,   the walk ends at the first s_k >= L
 *
 *      (the ending candidate draws too: its j is needed to know it ends).
 *      RECT, spacing 7, offset 1, jitter 2, stream [1, 0, 0.5, 1, 0.5]:
 *      j = [+2, −2, 0, +2, 0]; start 3.5 -> s = 5.5, 10.5, 17.5, 26.5, and
 *      the fifth candidate 33.5 >= 28 ends the walk after five draws.
 *      Points by the (U1) rule: s = 5.5 on edge 1 -> (5.5, 0) -> (5.5, 1);
 *      s = 10.5 on edge 2 -> (10, 0.5) -> (9, 0.5); s = 17.5 on edge 3 ->
 *      (6.5, 4) -> (6.5, 3); s = 26.5 on edge 4, t = 2.5/4 -> P = (0, 1.5)
 *      -> (1, 1.5). Ordinals 0..3, axes as in (U1).
 *      THE CLAMP: jitter 5, stream [0, 0.5, 0.5, 0.5, 0.5]: s_0 = 3.5 − 5 =
 *      −1.5 -> 0, the corner (0, 0) -> (0, 1); then 7, 14, 21 (j = 0) -> the
 *      (U2) points (7, 1), (10, 3), (3, 3); 28 >= 28 ends it.
 *      WITHOUT jitter (absent or 0) the stream is never opened — an injected
 *      stream that throws on its first draw stays silent and the output is
 *      (U1), byte for byte. The real stream is `seededRandom(seed + ':jitter')`:
 *      seed 'r' with jitter 2 equals the run fed `seededRandom('r:jitter')`.
 * (U5) THE SIDES (Task 10, 2026-09-10). `sides` "longest" / "opposite"
 *      replaces the closed-ring walk by ONE RUN PER SELECTED EDGE (R6), in
 *      ascending edge index, each run starting afresh at s = start on ITS
 *      edge and ending at the first s >= its length; `ordinal` counts on
 *      across the runs, and the jitter stream is shared — one draw per
 *      candidate, run after run. RECT, spacing 7, offset 1:
 *        longest  -> edge 0 alone: s = 3.5 < 10 -> (3.5, 0) -> (3.5, 1),
 *                    axis 3π/2, ordinal 0; s = 10.5 >= 10 ends it. ONE station.
 *        opposite -> edge 0: (3.5, 1), ordinal 0; then edge 2, (10,4) ->
 *                    (0,4): s = 3.5 -> P = (6.5, 4), axis π/2, n_in (0, −1)
 *                    -> (6.5, 3), ordinal 1. TWO stations.
 *        spacing 4, opposite -> start 2: edge 0: s = 2, 6 -> (2, 1), (6, 1),
 *                    ordinals 0, 1; 10 >= 10 ends; edge 2: s = 2 -> (8, 3),
 *                    s = 6 -> (4, 3), ordinals 2, 3. `maxPoints` 3 keeps the
 *                    first three — the guard counts across the runs.
 *        "all" and an absent word -> (U1), byte for byte.
 *      Jitter across the runs — opposite, jitter 2, stream [1, 0, 0.5, 1]:
 *      edge 0: j = +2 -> s = 5.5 -> (5.5, 1), ordinal 0; j = −2 -> 5.5 + 7
 *      − 2 = 10.5 >= 10 ends the edge (two draws); edge 2: j = 0 -> s = 3.5
 *      -> (6.5, 3), ordinal 1; j = +2 -> 12.5 >= 10 ends it. FOUR draws for
 *      two stations, and a three-number stream is one short.
 * (U6) THE CHAIN RUNS — `edges` on `ringStations` (Task 11, 2026-09-10).
 *      A selected ROAD SIDE (R8) is not one edge but a CHAIN of them — a
 *      decorated road has hundreds of tiny ones — and its stations are ONE
 *      run over the chain's CUMULATIVE arc length, `s = start + k · spacing`
 *      from the chain's beginning, exactly as the closed ring is walked.
 *      `edges` is an explicit list of edge indices and beats `sides`; it is
 *      read in RING order, every maximal group of CONSECUTIVE indices is one
 *      run, and the list never wraps around the closing edge.
 *
 *      ROAD (R8), spacing 25, offset 1, start = spacing/2 = 12.5:
 *        SIDE A, edge 0 from (0,−3) to (100,−3): heading = atan2(100, 0)
 *        = π/2, the facing of heading + 90° is (0,−1) and (50, −3.0001) lies
 *        OUTSIDE the band -> axis = π/2 + π = 3π/2; n_in = facing of
 *        3π/2 + π/2 = 2π = (0, 1) = +z, into the band. s = 12.5, 37.5, 62.5,
 *        87.5 (112.5 >= 100 ends the run) -> (12.5, −2), (37.5, −2),
 *        (62.5, −2), (87.5, −2).
 *        SIDE B, edge 2 from (100,3) to (0,3): heading = atan2(−100, 0)
 *        = −π/2, facing of heading + 90° = (0, 1) and (50, 3.0001) is
 *        outside -> axis = π/2; n_in = facing of π = (0,−1) = −z.
 *        s = 12.5 -> x = 100 − 12.5 = 87.5 -> (87.5, 2), then (62.5, 2),
 *        (37.5, 2), (12.5, 2).
 *        "opposite" -> those eight, side A first, ordinals 0..7; "longest"
 *        -> the four of side A; and NOTHING stands on the two road ends
 *        (no station at x = 0 or x = 100).
 *      THE CHAIN IS ONE RUN. The same road clicked with a point in the
 *      middle, [(0,0),(40,0),(100,0)] at width 6, is the band (0,−3) (40,−3)
 *      (100,−3) (100,3) (40,3) (0,3) — side A = edges 0, 1 (40 m and 60 m),
 *      side B = edges 3, 4 (60 m and 40 m) — and reads THE SAME EIGHT
 *      stations. A run per edge would answer 12.5, 37.5 on the first edge
 *      and 52.5, 77.5 on the second; the cumulative length of the chain is
 *      what keeps a road's row independent of where somebody clicked.
 *      `edges` covering EVERY edge is the closed-ring walk byte for byte:
 *      L = 100 + 6 + 100 + 6 = 212, s = 12.5 … 87.5 on side A, then 112.5 —
 *      the 6 m end edge spans [100, 106) and is never hit — 6.5 m into side
 *      B -> (93.5, 2), 137.5 -> (68.5, 2), 162.5 -> (43.5, 2), 187.5 ->
 *      (18.5, 2); 212.5 >= 212 ends it. Eight stations either way, and only
 *      the whole rim puts one at 93.5.
 *      An index no edge carries is skipped; an empty list places nothing.
 *
 * ============================================================================
 * (V) THE OCCUPANCY GRID — `OccupancyGrid` and the fifth verdict
 * ============================================================================
 * Rows keep clear of what OTHER rows placed: a survivor is filed with a
 * radius under its row's tag, and a later candidate is blocked when
 * `dist < r + ar` for any filed (ax, az, ar) of ANOTHER row — strictly less,
 * like `min_spacing`. Buckets of 8 m; the search reaches ±ceil((r + rMax)/8)
 * buckets with rMax the largest radius ever filed, so a big occupant is
 * found from far away. The grids of (V1)–(V6) are filled WITHOUT a tag,
 * which counts against everybody; (V7) is the tag.
 *
 * (V1) add(0, 0, 1): blocks(1.5, 0, 1) -> 1.5 < 2, true; blocks(2, 0, 1) ->
 *      2 < 2 is false (strict); blocks(0, 20, 1) -> false; an empty grid
 *      blocks nothing.
 * (V2) add(50, 50, 30): blocks(20, 50, 1) -> 30 < 31, true — (20, 50) is in
 *      bucket 2, the occupant in bucket 6, and ceil(31/8) = 4 buckets reach
 *      it. A search of the neighbouring bucket alone would miss it.
 * (V3) THE SAMPLER: the (N3) fixture (5 candidates, 3 variants, seed 'A',
 *      the fed stream) with a grid holding (2, 4) r 0.5 and `occupyR` 1:
 *      c0 stands at exactly (2, 4), 0 < 1.5 -> blocked; every other survivor
 *      is metres away. Result: c1 (5,5) v1, c2 (10,10) v2, c3 (15,6) v0,
 *      c4 (8,16) v1 — the positions and the variants of the unblocked run,
 *      only subtracted. Afterwards the survivors are filed: blocks(5, 5, 0.1)
 *      is true (0 < 1.1). `occupyR` absent = `clearM`: clearM 1 and a grid
 *      holding (2.4, 4) r 0.1 blocks c0 (0.4 < 1.1); with neither, the radius
 *      is 0 and 0.4 < 0.1 is false — c0 stands.
 * (V4) THE ORDER: occupancy is asked AFTER min_spacing, and a candidate it
 *      removes is NOT filed in the spacing buckets. The (S) fixture at
 *      spacing 4 with (1, 1) occupied (r 0.5, occupyR 1): c0 (1,1) blocked;
 *      c1 (3,3) is then measured against NOBODY -> kept; c2 (5,1) to (3,3):
 *      √8 = 2.83 < 4 -> dropped; c3 (8,4) to (3,3): √26 = 5.10 -> kept;
 *      c4 (1,5) to (3,3): √8 -> dropped. -> [(3,3) yaw 0, (8,4) yaw τ/4].
 *      Had c0 been filed before occupancy removed it, c1 would have been
 *      crowded by a ghost and the list would read (5,1), (8,4), (1,5).
 * (V5) THE CELL SAMPLER files only what the painted shape KEEPS. A cell of
 *      0..64 with the SQUARE (0..20) as the area ring, density 0.05 ->
 *      round(40.96 · 0.05) = 2 candidates, stream [0.1, 0.1, 0; 0.5, 0.5, 0]
 *      -> c0 (6.4, 6.4) inside the square, c1 (32, 32) in the cell but
 *      outside it — a phantom the ring filter drops. Afterwards blocks(6.4,
 *      6.4, 0.1) is true and blocks(32, 32, 0.1) is false: a prop nobody
 *      draws occupies nothing.
 * (V6) THE ROUTING ADAPTER of a pass, `cellOccupancy(grids)`: `grid.add`
 *      files a point into the grid of ITS cell (`scatterCellAt`, 64 m) —
 *      (10, 10) lands in "0,0" and nowhere else; `grid.blocks` asks the grid
 *      of the QUERIED point's cell and no other, without making one: (10.5,
 *      10) is cell (0,0), 0.5 < 1 + 1, blocked; (70, 10) is cell (1,0),
 *      empty, false, and "1,0" still does not exist. A point at (63.5, 10) filed in (0,0)
 *      is 0.7 m from (64.2, 10), yet that lies in (1,0) and is NOT blocked —
 *      the cell is the unit, on the rim of a cell as in its middle; (63.6,
 *      10) beside it is. `gridOf(0, 0)` is the grid the adapter filed into,
 *      `gridOf(1, 0)` makes the second one — two grids in the map.
 * (V7) FOREIGN ONLY (fix wave 2026-09-10). The first cut judged a row
 *      against its own survivors with 2 · clearM, which capped a wood of 8 m
 *      trees at one or two per 100 m² whatever the author wrote; within a
 *      row the distance is `min_spacing_m` and nothing else.
 *      · THE GRID: add(0, 0, 1, 'a') — blocks(1, 0, 1, 'a') is false (own
 *        row), blocks(1, 0, 1, 'b') true, blocks(1, 0, 1) true (an untagged
 *        query counts everything); add(5, 0, 1) untagged — blocks(5.5, 0, 1,
 *        'a') true (an untagged entry counts against every row).
 *      · THE SAMPLER, on the 10 m square at density 2 (round(1 · 2) = 2
 *        candidates), seed 'same', `occupyR` 1, stream [0.30, 0.30, 0;
 *        0.35, 0.30, 0] -> c0 (3, 3), c1 (3.5, 3): 0.5 < 2, yet both stand —
 *        c0 is the row's own. A second run with seed 'other' at density 1,
 *        stream [0.32, 0.30, 0] -> (3.2, 3), against the same grid: 0.2 < 2
 *        to a foreign (3, 3) -> blocked, []. The same run with an explicit
 *        `occupyTag` 'same' is excused -> [(3.2, 3)]: the tag, not the seed,
 *        is the identity, and the default is the seed.
 *      · THE ADAPTER passes the tag through: grid.add(30, 30, 1, 'a') —
 *        grid.blocks(30.5, 30, 1, 'a') false, with 'b' true, and the cell's
 *        own grid answers the same for 'a'.
 *
 * ============================================================================
 * (W) THE EPOCH — `reshuffleEpoch` and the seed suffix
 * ============================================================================
 * epoch = floor(totalSeconds / (reshuffleMin · 60)); `undefined` when the
 * row authors no interval (absent, 0, negative, junk) or the clock is not a
 * number. A seed grows the suffix `:e<epoch>` ONLY for a finite epoch —
 * without the field every seed is byte for byte what it was.
 *
 * (W1) reshuffleEpoch(3599, 60) = floor(3599/3600) = 0; (3600, 60) = 1;
 *      (7199, 60) = 1; (x, undefined) / (x, 0) / (x, −5) / (NaN, 60) ->
 *      undefined.
 * (W2) scatterCellSeed('a', 1, 2, 3) = 'terrain:scatter:a:1:2,3';
 *      scatterCellSeed('a', 1, 2, 3, 7) = 'terrain:scatter:a:1:2,3:e7';
 *      scatterSeed('a', 1) = 'terrain:scatter:a:1', with 7 -> ':e7';
 *      an undefined or NaN epoch adds nothing.
 *
 * ============================================================================
 * (X) THE EDGE AND CENTRE SAMPLERS — `scatterEdgeInstances`,
 *     `scatterCenterInstance`
 * ============================================================================
 * `edge`: the stations of (U), one yaw draw per station ALWAYS (the stream
 * is the row's seed), `yaw = aligned ? axis + deg : r · 2π`, then the
 * verdicts ring (of the PUSHED point) -> occluders -> footprints -> occupied,
 * and a survivor is filed. Variant = (FNV-1a(seed) + ordinal) mod n.
 *
 * (X1) RECT, spacing 7, offset 1, aligned, deg 0 -> the four (U1) points with
 *      yaws 3π/2, π, π/2, 0; deg 90 -> each + π/2, normalised: 0, 3π/2, π,
 *      π/2.
 * (X2) a footprint square (3,0.5) (4,0.5) (4,1.5) (3,1.5) around (3.5, 1)
 *      with clearM 0.2: only station 0 falls (the next survivor, (9, 0.5),
 *      is 5 m from the square). With 3 variants the survivors carry the
 *      variants of ordinals 1..3 — `scatterVariantIndex(seed, k, 3)` for
 *      k = 1, 2, 3 — ordinal 0 is simply missing. A counting stream sees
 *      FOUR draws for the three survivors: the rejected station drew its
 *      number too.
 * (X3) no mode -> yaw = r · 2π from `seededRandom(seed)`, one draw per
 *      station, same four positions.
 * (X4) a grid holding (9, 0.5) r 0.5 with occupyR 1 removes station 1 and
 *      files the other three: blocks(3.5, 1, 0.1) is true afterwards.
 *      Fewer than three ring points -> [].
 * (X8) OFFSET 0 KEEPS THE WHOLE ROW (review finding, 2026-09-10). A station
 *      at offset 0 lies ON the rim, and the even-odd cast counts a boundary
 *      point as inside on some edges and outside on others (`x <
 *      intersection`) — on RECT it kept (3.5, 0) and (0, 3.5) and dropped
 *      (10, 0.5) and (6.5, 4). So the ring verdict tests the pushed point
 *      NUDGED INWARD by ε = 1e-4 m along n_in: (3.5, ε), (10 − ε, 0.5),
 *      (6.5, 4 − ε), (ε, 3.5) — all four strictly inside -> all four
 *      survive, at their rim positions (3.5, 0) (10, 0.5) (6.5, 4) (0, 3.5),
 *      with `offsetM` absent as well as 0.
 *      THE CONCAVE CORNER of the L-shape (0,0) (10,0) (10,4) (4,4) (4,10)
 *      (0,10): L = 10 + 4 + 6 + 6 + 4 + 10 = 40; the corner (4, 4) is at
 *      s = 20, the START of edge 4 (4,4) -> (4,10). spacing 20, startM 20
 *      (clamped to the spacing) -> exactly one station, s = 20 (40 is not
 *      < 40), P = (4, 4). Edge 4: d = (0, 1), heading = 0, n = (dz, −dx) =
 *      (1, 0); the midpoint (4, 7) + (ε, 0) = (4 + ε, 7) is OUTSIDE the
 *      vertical arm (x ∈ [0, 4]) -> −d, axis = π, n_in = facing of 3π/2 =
 *      (−1, 0). The nudged point (4 − ε, 4) lies in the column x < 4, where
 *      the L spans z ∈ [0, 10] — strictly inside (even-odd: only the edges
 *      (4,4)->(4,10) at x = 4 and (0,10)->(0,0) at x = 0 cross z = 4, and
 *      4 − ε < 4 toggles once). -> ONE instance at (4, 4), yaw π under
 *      aligned/deg 0. An offset wider than the shape still lands outside
 *      and still falls: RECT at offset 3 pushes (3.5, 0) to (3.5, 3),
 *      (10, 0.5) to (7, 0.5), (6.5, 4) to (6.5, 1), (0, 3.5) to (3, 3.5) —
 *      all inside; at offset 5, (3.5, 5) and (6.5, −1) are outside and the
 *      row is two.
 * (X10) THE SIDES (Task 10): `sides` is handed straight to `ringStations`
 *      (U5), and everything else stays — one yaw draw per station, the
 *      verdicts, the variant over the ordinal. RECT, spacing 7, offset 1,
 *      aligned 0: longest -> [(3.5, 1) yaw 3π/2]; opposite -> [(3.5, 1)
 *      3π/2, (6.5, 3) π/2], a counting stream sees TWO draws; with 3
 *      variants the two carry the variants of ordinals 0 and 1; "all" is
 *      (X1) byte for byte. The L-shape under opposite (edges 0 and 5),
 *      spacing 6, offset 1: start 3 -> edge 0: s = 3, 9 -> (3, 1), (9, 1),
 *      axis 3π/2; edge 5, (0,10) -> (0,0): d = (0, −1), heading = π, n =
 *      (dz, −dx) = (−1, 0), the midpoint (0, 5) − (ε, 0) is outside -> axis
 *      = 2π -> 0, n_in = facing of π/2 = (1, 0); s = 3 -> P = (0, 7) ->
 *      (1, 7), s = 9 -> (0, 1) -> (1, 1). Four instances, yaws 3π/2, 3π/2,
 *      0, 0, all inside the L.
 * (X11) THE ROAD SIDES (Task 11): `edges` travels through the sampler to
 *      (U6) untouched. The ROAD under `ribbonSelectedEdges(ROAD, "opposite")`,
 *      spacing 25, offset 1, aligned 0°: the eight stations of (U6), each
 *      facing the axis of ITS kerb — 3π/2 on side A, π/2 on side B — all
 *      eight inside the band (the offset pushes inward), eight draws from
 *      the row's stream. Under "longest" the four of side A.
 *
 * `center`: `polylabel(ring)`, one yaw draw, axis = `axisAt(x, z)` when the
 * caller hands one in (a stroke area's centre line), else `ringEdgeAxis`;
 * verdicts occluders -> footprints -> occupied; the variant is the pinned
 * one clamped to [0, n − 1], else the formula with ordinal 0.
 *
 * (X5) RECT, aligned, deg 0, 3 variants, variant 2 -> ONE instance at
 *      (5, 2) ± 0.5, yaw = the axis of the nearest edge of (5, 2): 2 m to
 *      top and bottom, 5 m to the sides, the tie goes to the FIRST edge
 *      (bottom) -> 3π/2; variant 2. variant 9 at n = 3 -> 2 (clamped);
 *      no pin -> scatterVariantIndex(seed, 0, 3); n = 1 -> no variant key.
 * (X6) `axisAt` answering 1 is used instead of the ring: yaw 1 (+ deg 0),
 *      and it was asked at (5, 2) ± 0.5. No mode -> seededRandom(seed)() · 2π.
 * (X7) an occluder over the middle, a footprint over it, or a grid holding
 *      (5, 2) r 1 -> []. A two-point ring -> [].
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
 * (J3) TYPING. `checkScatterPrefs(near, far, cull)`, what the menu asks
 *      before it stores anything, is derived and checked in
 *      `smoke_walk_math.mjs` (header "Scatter detail distances: typing"),
 *      whose cases run from `shared/test-vectors/overview_hud.json` with the
 *      other HUD-side cases the native client reads.
 *
 * (J4) THE TWO SIDES MEET. `scatterLodCfgOf` renames the stored fields into
 *      the cfg the maths takes (that rename is the [J4] case of
 *      `overview_hud.json`, see `smoke_walk_math.mjs`), so a setting of
 *      20/40/300 must produce exactly that behaviour end to end:
 *        19 m, prev low  -> 0 (full)      41 m, prev full -> 1 (low)
 *        301 m           -> 2 (hidden)   share(160) = 1 - (120/260)*0.75
 *                                                   = 0.653846153...
 *
 * ============================================================================
 * E4-T1 EXTRA DERIVATIONS (2026-10-28)
 * [G-tie1]/[G-tie2]: 0.05*0.5*100 = 2.5 and 0.25*0.5*100 = 12.5.
 * JS Math.round rounds upward: 3/100 = 0.03 and 13/100 = 0.13.
 * [K-want1..3]: k = clamp(ceil(cull/64),1,32); cell = floor(position/64).
 * For (0,0,1), centre (0,0), k=1: x=-1..1 for each z=-1..1.
 * For (-0.1,-64,64), centre (-1,-1), k=1: x=-2..0 for each z=-2..0.
 * For (64,128,120), centre (1,2), k=2: x=-1..3 for each z=0..4.
 * These are complete lists in z-major order, including all negative edges.
 * [I-hash]: uint32 arithmetic at each multiply. At index 0 every stage is 0.
 * Index 1: multiply by 2654435761 -> 2654435761; xor-shift15 and multiply
 * 2246822507 -> 4068878901; xor-shift13 and multiply 3266489909 -> 2328563412;
 * xor-shift16 -> 2328593439; /2^32 -> 0.5421679092105478.
 * Index -1: the corresponding uint32 stages are 1640531535, 1587568586,
 * 1993427816, 1993424313; /2^32 -> 0.4641302658710629.
 * [V-radius]: occupyR ?? clearM chooses the explicit radius even at 0 or -1.
 * A positive finite result survives; missing, 0 or negative becomes 0.
 * Thus (2,3)->2, (null,3)->3, ()->0, (0,3)->0, (-1,3)->0,
 * (null,-2)->0 and (0.25,0.5)->0.25.
 * [W-suffix]: missing/null is not a finite number and adds ''. Finite values
 * are spelled literally: 0 -> ':e0', 5 -> ':e5', -1.5 -> ':e-1.5'.
 *
 * scatter_rows.json uses these TS-shape adapters (e4VectorDispatch.mjs):
 * areaAxis({line,ring,sides,at}) calls the returned axis at that point;
 * axisFrom in sampler options builds that same callback. rng/jitterRng lists
 * are consumed once, in order, with exhaustion throwing. In Q4 the horizontal
 * line's heading pi/2 plus authored 90 degrees gives pi at both fed candidates
 * (2,4) and (15,5). In Q5 a diagonal line's pi/4 plus 45 degrees gives pi/2
 * at (6.4,12.8), the only candidate requested by round(40.96*0.025)=1.
 * occupied lists add circles to a fresh grid. occupancy runs add/blocks/sample
 * steps on ONE grid and returns each blocks answer or sample result in order.
 * These exercise V3..V7's derivations above without recording a seeded run.
 * FNV-1a('x') = (2166136261 xor 120)*16777619 modulo 2^32 = 4245442695;
 * this is divisible by 3, so X2's ordinal variants are 0,1,2,0 and the blocked
 * ordinal 0 leaves 1,2,0. X5 without a pin uses ordinal 0, hence variant 0.
 * In U2/U4-clamp, s=14 is the start of the TOP edge: its axis is pi/2.
 * [D1] decoration: on a 100 m line, jagged spacing 10 gives endpoints plus
 * 5,15,...,95 = 12 points; spacing 30 gives 0,15,45,75,100. [D4] budget:
 * room=1024-2=1022, spacing=10000/1022=9.784735812133073, 1024 total points,
 * capped true. [D5] wavy: step=min(10/3,3)=3, x=0,3,...,99,100 = 35 points.
 * decorateStroke's adapter adds pointCount and xs projections of its result;
 * random amplitudes and their closed-form checks remain inline in stroke_styles.
 * [S11] straight/unknown-style centre lines are the clicked points. A straight
 * decoration returns those points, spacing 10 and capped false.
 *
 * [S] WHAT STANDS ALONG THE LINE — `strokeStations` (§ A9 addendum 2026-09-09)
 * ---------------------------------------------------------------------------
 * Hand-derived (see the plan, `plan-strassenrand-scatter.md`):
 *   [S1] [(0,0),(100,0)], spacing 25, offset 3, right: stations at
 *        s = 12.5, 37.5, 62.5, 87.5 (start = spacing/2, 87.5 + 25 > 100).
 *        Direction (1,0): right normal (−dz, dx) = (0, 1) -> z = +3,
 *        yaw = atan2(1, 0) = π/2, plus yaw_deg 0.
 *   [S2] the same, `left`: normal (dz, −dx) = (0, −1) -> z = −3, and the
 *        walking direction is reversed -> yaw = π/2 + π = 3π/2.
 *   [S3] `alternate`: k even right, k odd left -> z = +3, −3, +3, −3 with
 *        yaws π/2, 3π/2, π/2, 3π/2.
 *   [S4] `both`: two per station, right then left -> 8 instances.
 *   [S5] yaw_deg 90 on the right side: π/2 + π/2 = π; on the LEFT side
 *        3π/2 + π/2 = 2π -> 0 (normalised). A bench "looking across" faces −z
 *        from the right (yaw π faces (sin π, cos π) = (0, −1)) and +z from the
 *        left (yaw 0 faces (0, 1)): both look at the line. That is the rule.
 *   [S6] a corner [(0,0),(10,0),(10,10)], spacing 10, offset 2, right, start
 *        5: s = 5 on the first segment -> (5, 2), yaw π/2; s = 15 on the
 *        second (direction (0,1), right normal (−1, 0)) -> (8, 5), yaw
 *        atan2(0, 1) = 0.
 *   [S7] start_m 0 puts the first station on the start point; start_m past
 *        the spacing is clamped to it: spacing 25, start 30 -> first at 25.
 *   [S8] a footprint square over (37.5, 3) drops station 1 and keeps the
 *        ORDINALS: with 3 variants and no pin the survivors keep the variant
 *        they had without the footprint (2, 4 and 6 of 8 in `both` mode…);
 *        simplest: right side only, variants over ordinal k, the survivors'
 *        variants equal the unblocked run's at the same k.
 *   [S9] a pinned variant 1 gives every instance 1; a pin past the count
 *        clamps to n − 1; variantCount 1 carries no variant field at all.
 *   [S10] `random` draws one number per instance from the row's seed and
 *        the positions do not move: same x/z as [S1].
 *   [S11] `strokeCentreLine` of a straight recipe is the clicked points;
 *        of a wavy one it is `decorateStroke` with the toolbar defaults
 *        (10 m, 2 m) when the recipe authors no numbers.
 *   [S12] `occupied` (2026-09-10): a grid holding (37.5, 3) with radius 0.5
 *        and `occupyR` 1 blocks station 1 alone (0 < 1.5; the next station
 *        is 25 m away), the survivors keep the ordinals' variants exactly as
 *        under the footprint of [S8], and they are FILED in turn:
 *        blocks(12.5, 3, 0.1) is true afterwards (0 < 1.1). `occupyR` absent
 *        = `clearM`: clearM 1 and a grid holding (37.9, 3) r 0.1 blocks the
 *        station 0.4 m away (0.4 < 1.1); with neither, the radius is 0 and
 *        0.4 < 0.1 is false — it stands.
 *   [S13] `alongSeed` with an epoch: ('a', 2, 5) -> 'terrain:along:a:2:e5';
 *        without one, or with undefined / NaN, the seed of [S] unchanged.
 *   [S14] THE SPACING JITTER (Task 9, 2026-09-10): with `jitterM` > 0 every
 *        station draws r_k from a SEPARATE stream (the row seed + ':jitter',
 *        never the yaw stream) and j_k = (2·r_k − 1)·jitterM,
 *        s_0 = start + j_0, s_k = s_{k−1} + spacing + j_k, s_k < 0 -> 0,
 *        the walk ends at the first s_k past L (the ending candidate draws
 *        too — its j is needed to know it ends). [S1]'s line, spacing 25,
 *        jitter 5, stream [0, 1, 0.5, 0.25, 0.5]: j = [−5, +5, 0, −2.5, 0];
 *        start 12.5 -> s = 7.5, 37.5, 62.5, 85, and the fifth candidate
 *        110 > 100 ends it after five draws. z = +3 and yaw π/2 as in [S1].
 *        A four-number stream is one short and throws. `random` yaw and
 *        jitter together: the yaws are [S10]'s numbers exactly (the yaw
 *        stream is untouched), the x are the jittered ones. Jitter 0 or
 *        absent never opens the stream (a stream fed nothing stays silent)
 *        and is [S1] byte for byte. The real stream: seed 'terrain:along:a:0'
 *        with jitter 5 equals the run fed seededRandom('terrain:along:a:0:jitter').
 *
 * SHARED VECTORS — `shared/test-vectors/scatter.json`
 * ============================================================================
 * Every case above whose function has a C# port in `native/Core/Scatter/`
 * runs from `shared/test-vectors/scatter.json` (format in its README), which
 * the native client's C# tests read too. The derivations stay HERE; the JSON
 * carries inputs + expectations only, each label starting with the tag of its
 * derivation. A compound check (`[a, b]` against `[x, y]`) became one case
 * per value. The `fn` names are the TypeScript ones; the C# side maps them:
 *
 *   TS (`fn`)              C#
 *   propGroundFit          ScatterMath.GroundFit
 *   pointInRing            ScatterMath.PointInRing
 *   pointInFootprint       ScatterMath.PointInFootprint
 *   footprintDistance      ScatterMath.FootprintDistance
 *   footprintBlocks        ScatterMath.FootprintBlocks
 *   scatterClearM          ScatterMath.ClearM
 *   propBoxFootprint       ScatterMath.PropBoxFootprint
 *   scatterWantedCount     ScatterMath.WantedCount
 *   scatterInstances       ScatterMath.Instances
 *   scatterCellInstances   ScatterMath.CellInstances
 *   scatterSeed            ScatterMath.Seed
 *   scatterCellSeed        ScatterMath.CellSeed
 *   reshuffleEpoch         ScatterMath.ReshuffleEpoch
 *   scatterSeedHash        ScatterMath.SeedHash
 *   scatterVariantIndex    ScatterMath.VariantIndex
 *   scatterYaw             ScatterMath.Yaw
 *   scatterCellAt          ScatterMath.CellAt
 *   scatterCellRing        ScatterMath.CellRing
 *   scatterCellSpan        ScatterMath.CellSpan
 *   scatterTargetH         ScatterLod.TargetH
 *   scatterSway            ScatterLod.Sway
 *   scatterGroundOffset    ScatterLod.GroundOffset
 *   instanceTier           ScatterLod.InstanceTier
 *   instanceShare          ScatterLod.InstanceShare
 *   instanceVisible        ScatterLod.InstanceVisible
 *   horizontalFovRad       ScatterLod.HorizontalFovRad
 *   viewCone               ScatterLod.ViewCone
 *   inViewCone             ScatterLod.InViewCone
 *
 * E4 adds direct wantedScatterCells, instanceHash, scatterOccupyR and
 * seedEpochSuffix cases. The four new files are scatter_rows (R/T/U/V/X/Q,
 * plus the S/D derivations above), impostors (including W-seam), undergrowth
 * and world_props. Their C# consumers arrive with the corresponding ports.
 * scatterPinnedVariant is still exercised through sampler options; seededRandom
 * remains a stream property. The Ug* cases now live in undergrowth.json.
 *
 * The JSON speaks the TypeScript shapes: a point is `[x, z]`, a footprint
 * `{points}`, a LOD cfg `{nearM, farM, cullM}`, a prop box `{x, z, yaw_deg,
 * half_w, half_d}`, a sampler call ONE options object with the TS keys; the
 * results compared are `{x, z, yaw, variant}`, `{scale, offsetY}`,
 * `{fwdX, fwdZ, cosHalf}` and `{points}`. Two conventions on top:
 *   - `rng` in a sampler's options is a LIST of numbers. The runner feeds it
 *     in order and THROWS when the sampler draws past its end — `stream()`
 *     below, the hand-fed stream of section (C).
 *   - An omitted trailing argument / option key is JS `undefined`; `null` is
 *     JS `null`. In every case here both read as "not given" (C# `null`).
 *     The one null in a middle position — the angle of (Q2) "aligned without
 *     an angle" — gives the answer `undefined` gives there.
 *
 * WHAT STAYS INLINE: non-finite inputs, undefined results, source/constant
 * pins, mutations, seeded determinism and relations between calls, instrumentation
 * of callback positions/counts, and GPU/integration checks. Finite arithmetic
 * and object/function inputs representable by the adapters run from vectors.
 */
```
