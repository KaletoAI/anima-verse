# backdrop_math

- Origin: the browser scene's deleted `smoke_backdrop_math.mjs` @ 011cd048aa3cc2937186d7f35d2203af9491db8a
- Executed by: `native/tests/BackdropVectorTests.cs`
- Vectors: `shared/test-vectors/backdrop.json`

## Derivation

```text
/**
 * Smoke check for the pure maths of the FAR BACKDROP (§ A17): the ridge
 * profile of the browser scene's `backdropProfile.ts` — where the mountain
 * silhouette has a peak, how high it stands there, and how the two rings are
 * offset against each other.
 *
 * Usage:  node smoke_backdrop_math.mjs   (historical; the runner was deleted with the browser scene in E3)
 *
 * Same discipline as `smoke_scatter_math.mjs` and `scripts/smoke_scene_recipe.py`:
 * every expected number below is derived BY HAND in this header and NEVER
 * recorded from the current output. A check that only pins today's result
 * proves nothing.
 *
 * The module under test is IMPORT-FREE by design (its header says so), so a
 * plain esbuild transpile is enough — the same loader the scatter and relief
 * smokes use, no bundler and no stand-ins. That is also the reason the pure
 * half is its own file: `scene/backdrop.ts` needs `three` for its triangles
 * and could not be loaded here at all.
 *
 * ============================================================================
 * THE FORMULA, once
 * ============================================================================
 * Per layer L (0 = front, 1 = back) the ring carries `segments` nodes at the
 * angles i · 360/segments, and
 *
 *     h_i   = heightM · f(L) · ( 0.45 + 0.55 · r_i )     f(L) = 1 + 0.25·L
 *     R(L)  = 380 + 60 · L                               (metres)
 *
 * with r_i the i-th number of the layer's stream. An OPEN arc [s, e] emits
 *
 *     (s, 0) · every node angle strictly inside · (e, 0)
 *
 * and multiplies each inner node by the taper
 *
 *     ramp( min(a − s, e − a) / 12 ),  ramp(t) = 3t² − 2t³ clamped to [0,1]
 *
 * so the range climbs out of the ground at both ends instead of ending in a
 * wall. A FULL ring (span ≥ 360) has no ends, is not tapered, and repeats its
 * first node at +360 to close the strip.
 *
 * The hand cases feed `rnd` — the same device `scatterInstances.rng` uses —
 * because a seeded xorshift cannot be simulated on paper. ONE stream serves
 * both layers in order (front's `segments` numbers first).
 *
 * ============================================================================
 * (A) THE TWO LAYER OFFSETS — the parallax of the design decision
 * ============================================================================
 * (A1) R(0) = 380 + 60·0 = 380 m, R(1) = 380 + 60·1 = 440 m.
 * (A2) f(0) = 1, f(1) = 1 + 0.25 = 1.25.
 * (A3) With the SAME random number both rings differ by exactly that factor:
 *      r = 1, heightM = 100 -> front 100 · 1 · (0.45 + 0.55) = 100 m,
 *      back 100 · 1.25 · 1 = 125 m.
 *
 * ============================================================================
 * (B) THE FULL RING — [0, 360], segments 8 (step 45°), heightM 100, r ≡ 1
 * ============================================================================
 * Nodes: 0, 45, 90, …, 315 — eight of them, each at 100 m (front). No taper.
 * The ring closes with the first node again at 360, so the layer has 9 points
 * and 8 quads:
 *   front [ (0,100) (45,100) (90,100) (135,100) (180,100) (225,100)
 *           (270,100) (315,100) (360,100) ]
 *   back  the same angles at 125 m.
 * 18 points in total — the profile carries BOTH layers.
 *
 * ============================================================================
 * (C) ARC CLIPPING — "N" is [157.5, 202.5] (§ A17), segments 8, r ≡ 1
 * ============================================================================
 * ceil(157.5/45) = 4 and floor(202.5/45) = 4 (the ends are nudged off the
 * node grid by an epsilon), so exactly ONE node lies inside: 180°.
 *   at 180: min(180−157.5, 202.5−180) = 22.5° ≥ 12 -> ramp = 1 -> 100 m
 * -> front [ (157.5, 0) (180, 100) (202.5, 0) ], back the same at 125 m.
 * The ring is 45° of range in the north and nothing anywhere else, which is
 * the whole point of authoring an arc.
 *
 * ============================================================================
 * (D) AN ARC PAST 360 — [292.5, 427.5] ("SE,S,SW"), segments 8
 * ============================================================================
 * § A17 forbids a wrapped arc: a run across 0 arrives as end > 360. The node
 * indices are taken MODULO the ring, so the sweep continues into the same
 * table it started in.
 * Front stream r = [1, 0, 1, 1, 1, 1, 1, 0.5] gives the node heights
 *   i:      0    1   2    3    4    5    6    7
 *   a:      0   45  90  135  180  225  270  315
 *   h:    100   45 100  100  100  100  100  72.5      (0.45+0.55·0 = 0.45,
 *                                                      0.45+0.55·0.5 = 0.725)
 * ceil(292.5/45) = 7, floor(427.5/45) = 9 -> i = 7, 8, 9:
 *   i=7  a=315  node 7          -> 72.5   (d = min(22.5, 112.5) = 22.5 -> 1)
 *   i=8  a=360  node 8 mod 8 = 0 -> 100    (d = min(67.5, 67.5) -> 1)
 *   i=9  a=405  node 9 mod 8 = 1 -> 45     (d = min(112.5, 22.5) = 22.5 -> 1)
 * -> front [ (292.5,0) (315,72.5) (360,100) (405,45) (427.5,0) ].
 * The back layer is fed r ≡ 1 (its own eight numbers) -> 125 m at all three.
 *
 * ============================================================================
 * (E) THE TAPER — a narrow arc [0, 20], segments 72 (step 5°), r ≡ 1
 * ============================================================================
 * Nodes inside: 5, 10, 15. Node height 100 m, and with ramp(t) = 3t² − 2t³:
 *   a=5 :  d = min(5, 15) = 5,  t = 5/12
 *          ramp = 3·25/144 − 2·125/1728 = 900/1728 − 250/1728 = 650/1728
 *               = 325/864 = 0.376157407407…      -> 37.6157407407… m
 *   a=10:  d = min(10, 10) = 10, t = 10/12 = 5/6
 *          ramp = 3·25/36 − 2·125/216 = 450/216 − 250/216 = 200/216 = 25/27
 *               = 0.925925925926…                -> 92.5925925926… m
 *   a=15:  d = min(15, 5) = 5   -> the same 37.6157… m as a=5 (symmetric)
 * plus the two ends at 0. A ridge that comes out of the ground and goes back
 * into it.
 *
 * ============================================================================
 * (F) THE CLAMPS — the client re-clamps what the server already validated
 * ============================================================================
 * (F1) 5 m -> 20 m (the floor), 1000 m -> 300 m (the ceiling), 120 -> 120,
 *      NaN / undefined / a string -> the default 120.
 * (F2) Through the profile ("N", r ≡ 1): heightM 5 gives a 20 m front peak
 *      and a 20·1.25 = 25 m back peak; heightM 1000 gives 300 / 375 m.
 * (F3) THE LOWEST PEAK, r ≡ 0: 100 · (0.45 + 0) = 45 m front, and
 *      100 · 1.25 · 0.45 = 56.25 m back. No peak is ever lower than that —
 *      a ridge running down to 0 would look like teeth, not like a range.
 *
 * ============================================================================
 * (G) NOTHING TO DRAW / JUNK
 * ============================================================================
 * No arcs, an empty arc (start = end), a reversed one (end < start) and a
 * non-finite one all yield an EMPTY profile — never a ring "just in case".
 * `segments` is bounded into [8, 720]: 2 becomes 8 (a full ring of 9 points
 * per layer), NaN falls back to the default 96 (97 points per layer).
 *
 * ============================================================================
 * (H) THE COMPASS — § A1.8, the one figure compass of this contract
 * ============================================================================
 * direction(a) = (sin a, cos a) with x east and z south:
 *   0° -> ( 0,  1)  south     90° -> ( 1, 0)  east
 * 180° -> ( 0, −1)  north    270° -> (−1, 0)  west
 * and 45° -> (0.7071067811865476, 0.7071067811865476), south-east.
 *
 * ============================================================================
 * (I) DETERMINISM AND THE COPIED RNG
 * ============================================================================
 * The real path (no `rnd`) is a pure function of the seed: the same call twice
 * is the same list, a different seed is a different list, and the two layers
 * draw from their own streams — the back ridge is NOT the front one scaled by
 * 1.25. Every peak of a full ring stays inside [0.45·H·f, H·f] by the formula.
 * `backdropRandom` is a deliberate COPY of `seededRandom` in
 * `packages/scene-render/src/scatter.ts` (the module has to stay import-free);
 * the check loads BOTH and compares their streams, so the copy cannot drift
 * into different numbers unnoticed.
 *
 * ============================================================================
 * (J) THE RED COUNTER-CHECKS — mutants that must fail
 * ============================================================================
 * (J1) The layer HEIGHT offset removed (f(L) ≡ 1): the back ring answers 100 m
 *      in case (A3)/(B) where the real rule answers 125 — the two ridges would
 *      be one silhouette, and the back one would never be seen.
 * (J2) The layer RADIUS offset removed (R(L) ≡ 380): both rings stand at
 *      380 m, so there is no parallax left at all.
 * (J3) The modulo of the node lookup removed: case (D)'s 405° reads past the
 *      end of the table and gives NaN instead of 45 m — a wrap-free arc would
 *      tear a hole into the ring.
 * (J4) The compass mirrored (cos/sin swapped): 180° becomes (cos, sin) =
 *      (−1, 0), i.e. WEST — an arc authored as "N" would stand in the west.
 *
 * [0] Vector cases carrying A/F labels use the lettered hand
 * calculations above: radii380/440, factors1/1.25, clamps20/300/120.
 * [20] Shared ridge cases: the north arc has endpoints157.5/202.5
 * at0 and the sole inner8-segment node180 at100/125 (derivations C/A).
 * Six objects carry the angles, heights and layer0/1. Empty arcs and
 * zero-span arcs remain empty even on the seeded path. Compass0/180
 * is(0,1)/(0,-1) by H.
 * For a NONEMPTY seeded case, use the documented unsigned32-bit FNV
 * recurrence h=(h xor char)*16777619 mod2^32, initially2166136261.
 * The text "backdrop-7-l0" finishes at1822100270; "backdrop-7-l1"
 * at1838877889. Each draw applies a=(h xor(h>>>15))*2246822519,
 * b=(a xor(a>>>13))*3266489917 (both mod2^32), then h=b xor(b>>>16).
 * Successive unsigned states, calculated with that integer recurrence:
 * l0:1511548076,4280321300,56394140,760984436,1669887557;
 * l1:211144938,1895373586,2072848599,3986337067,3060965876.
 * The north peak is node4, the FIFTH draw. Heights therefore are
 * 100*(.45+.55*1669887557/4294967296)=66.38405470992438 and
 * 125*(.45+.55*3060965876/4294967296)=105.24720753892325.
 * Endpoints remain0 at157.5/202.5; the layer numbers remain0/1.
 */
```
