# enter_math

- Origin: `client3d/scripts/smoke_enter_math.mjs` @ 011cd048aa3cc2937186d7f35d2203af9491db8a
- Executed by: `native/tests/EnterVectorTests.cs`
- Vectors: `shared/test-vectors/enter.json`

## Derivation

```text
/**
 * Smoke check for the pure ENTRY maths of the 3D client
 * (plan-freie-weltkarte-e4-3d-client.md task 5; contract v6 "Gebiete") —
 * `client3d/src/game/enterLocation.ts`.
 *
 * Usage:  node client3d/scripts/smoke_enter_math.mjs
 *
 * Same discipline as `client3d/scripts/smoke_ground_math.mjs` and
 * `smoke_travel_math.mjs`: every expected number below is derived BY HAND from
 * the contract (§ A1.1, § A1.3 and § B1 Nr. 13 of docs/schnittstellen-3d.md)
 * and from the server's own `app/core/boundary_entry.py`, written out in this
 * header, and NEVER recorded from the current output. A check that only pins
 * today's result proves nothing.
 *
 * `enterLocation.ts` imports NOTHING but the polygon primitives it measures a
 * free boundary with, so a plain esbuild transpile loads it here. If someone
 * puts a runtime import into it, this loader fails loudly, which is the
 * intended alarm: the module mirrors a SERVER rule and has to stay checkable
 * without a bundler, a DOM or three.
 *
 * ===========================================================================
 * WHY THIS FILE EXISTS — AND WHAT V6 TOOK OUT OF IT
 * ===========================================================================
 * Entering a location is the one place where the client anticipates a server
 * decision. The server accepts a crossing only when the reported point lies
 * within 1.5 m of an authored boundary opening (`_POS_OPENING_TOLERANCE_M` in
 * `app/routes/play.py`, checked in `scripts/smoke_play_pos.py`); the client
 * offers "Betreten" within 3 m of the same point and then walks the figure to
 * it. If the two computed that point differently, the offer would promise
 * something the next position report cannot deliver.
 *
 * SINCE CONTRACT V6 THE CLIENT COMPUTES NOTHING ABOUT AN OPENING. The worldmap
 * row carries `locations[].openings` (§ A1.3) — edge INDEX, `at_world` in
 * WORLD metres, `inward` unit normal in WORLD axes, `room` — computed by
 * `boundary_entry.opening_world_frames`, the very function the entry gate
 * measures with. The client consumes them VERBATIM. Gone with that:
 *   - the edge LETTERS N/E/S/W (v6 Nr. 5: an edge is a polygon edge index);
 *   - the half-edge formula off `plan_width_m` (`anchorRawOpening`), the
 *     mirror the client kept for locations whose scene answers 404 — the
 *     worldmap row answers for those too, so there is nothing left to mirror;
 *   - `tile_rotation` and its flip rule (v6 Nr. 15: deleted, a location is
 *     turned by its pin alone);
 *   - `freeBoundaryOf` and its three-state scene cache: `openings.length === 0`
 *     IS the free-boundary statement, and it rides on the row that built the
 *     tile, so there is no "still in flight" state to be conservative about.
 *
 * ---------------------------------------------------------------------------
 * (1) localToWorld — § A1.1, `app/core/world_geometry.local_to_world`
 * ---------------------------------------------------------------------------
 *     x = cx + lx·cos(yaw) + lz·sin(yaw)
 *     z = cz − lx·sin(yaw) + lz·cos(yaw)
 *
 * yaw in RADIANS. At yaw 0 it is a plain translation. It is what turns a rim
 * point of a FREE boundary back into the world (the outline is local metres);
 * openings do not go through it any more. The turning cases are hand-computed
 * with cos 90° = 0, sin 90° = 1:
 *
 *   centre (50, 50), yaw 0:
 *     local (0, −5)   -> (50 + 0,        50 − 0 + (−5))   = (50, 45)
 *     local (5, 0)    -> (55, 50)
 *   centre (50, 50), yaw 90° (π/2):
 *     local (0, −5)   -> x = 50 + 0·0 + (−5)·1 = 45
 *                        z = 50 − 0·1 + (−5)·0 = 50        = (45, 50)
 *     local (5, 0)    -> x = 50 + 5·0 + 0·1 = 50
 *                        z = 50 − 5·1 + 0·0 = 45           = (50, 45)
 *   centre (0, 0), yaw 180°  (cos −1, sin 0):
 *     local (3, 4)    -> (−3, −4)
 *   centre (0, 0), yaw 270°  (cos 0, sin −1):
 *     local (5, 0)    -> x = 0 + 0 + 0 = 0,  z = 0 − 5·(−1) = 5   = (0, 5)
 *
 * ---------------------------------------------------------------------------
 * (2) THE ONE SQUARE BOTH SIDES CHECK — the gatehouse of
 *     `scripts/smoke_worldmap_v2.py` [9]
 * ---------------------------------------------------------------------------
 * Pin (0, 0), boundary the DRAWN centred 12 m square (−6,−6) (6,−6) (6,6)
 * (−6,6), clockwise in map view (since 2026-08-19 nothing is synthesized: a
 * location without a drawn outline has no area, and the server answers
 * `boundary: null` for it — which this client already draws as a bare pin).
 * One opening, edge 0 (= point 0 → point 1, the edge
 * from (−6,−6) to (6,−6)) at 0.5:
 *
 *     point  = (−6 + 0.5·12, −6) = (0, −6)
 *     inward: d = (12, 0), |d| = 12, (−dz, dx)/|d| = (0, 1); the probe a
 *             millimetre along it lands at (0, −5.999), inside the square
 *     yaw 0  -> at_world (0, −6),  inward (0, 1)
 *     yaw 90 -> at_world (−6, 0),  inward (1, 0)   (§ A1.1; the normal turns
 *               about the ORIGIN, the point about the pin)
 *
 * These are the SAME numbers the server smoke derives — that is the point of
 * using one fixture on both sides. What this file then checks is that the
 * client hands them back UNCHANGED: at yaw 90 the offer must still be exactly
 * (−6, 0) with normal (1, 0), because nothing here turns a payload point.
 *
 *   avatar (0, −8)  -> 2 m from (0, −6)  ≤ 3  -> offered, inward (0, 1)
 *   avatar (0, −10) -> 4 m                > 3  -> null
 *   the turned gatehouse, avatar (−8, 0) -> 2 m from (−6, 0) -> offered,
 *                                            inward (1, 0)
 *
 * ---------------------------------------------------------------------------
 * (3) entryOfferNear — WHEN "Betreten" stands
 * ---------------------------------------------------------------------------
 * ENTER_RADIUS = 3 m, measured to the opening WORLD POINT. The rules, and the
 * ones that are GONE with the cells:
 *   - the location the avatar stands in is never a candidate (one does not
 *     enter where one is);
 *   - a location WITH openings offers entry at them and nowhere else
 *     (decision 2026-08-04: the server refuses the crossing anywhere else);
 *   - a location with NO opening has a FREE boundary, and since contract v6
 *     its whole DRAWN RIM is the offer (the polygon successor of "anywhere
 *     along the edge"). Without an outline it has no rim and offers nothing;
 *   - 4-ADJACENCY and the crossed-EDGE filter are gone: on a free plane a
 *     crossing has no edge, only a distance — which is what the server
 *     measures too;
 *   - an OPEN location beats a locked one at any distance; among equals the
 *     nearest opening wins.
 *
 * The world for the checks, all of it as the SERVER would deliver it for the
 * 10 m square (−5,−5) (5,−5) (5,5) (−5,5):
 *
 *   HALL at (50, 50), yaw 0, opening edge 0 at 0.5 -> local (0, −5),
 *     inward (0, 1)  ->  at_world (50, 45), inward (0, 1)
 *   BARN at (50, 30), yaw 0, opening edge 2 at 0.5: edge 2 runs (5,5)→(−5,5),
 *     so the point is local (0, 5) and d = (−10, 0), (−dz, dx)/|d| = (0, −1)
 *     — north, into the square  ->  at_world (50, 35), inward (0, −1)
 *   SHED at (65, 50), yaw 0, NO openings and NO outline
 *
 *   avatar (50, 43)  -> HALL's opening (50,45): |43−45| = 2   ≤ 3  -> offered
 *                       BARN's opening (50,35): |43−35| = 8   > 3
 *   avatar (50, 41)  -> HALL 4 m, BARN 6 m: nothing within 3   -> null
 *   avatar (50, 37)  -> BARN 2 m -> BARN offered (HALL is 8 m off)
 *   avatar (50, 40)  -> HALL 5, BARN 5: both out of reach       -> null
 *   avatar (50, 44)  -> HALL 1 m, and HALL is where the avatar already IS
 *                       (myLocId) -> null
 *   avatar (63, 50)  -> SHED has neither openings nor an outline -> null,
 *                       whatever the distance
 *   avatar (50, 43) with a LOCKED HALL and BARN 8 m away
 *                    -> HALL still, with `locked` in the caller's hands
 *   avatar exactly between two open ones: the nearer wins;
 *   an open one 2.5 m away beats a locked one 1 m away.
 *
 * The FOOTPRINT of a candidate is read for the free boundary alone. A tile
 * with authored openings may carry any yaw at all and the offer does not move
 * — the check below turns HALL by 90° and expects the very same point, which
 * is what "verbatim" means.
 *
 * Task 46 label index: [20] localToWorld; [21] entryOfferNear, including the
 * free-boundary and lock tables still written beside the calls below;
 * [22] area/bounds/sanitize; [23] contains; [24] distance; [25] rim.
 * [21] Meadow square +/-5 at (50,50): (57,50) -> rim (55,50), dist2,
 * inward(-1,0); (59,50) is out; (52,50) is exactly3 inside. Yaw90 turns
 * (50,43) to local(7,0), rim back to (50,45), inward(0,1). Open HALL at
 * (50,45), distance1.5, beats locked gate at (50,44.5), distance1, from
 * (50,43.5); among locked the distance1 wins. Authored openings beat rim.
 * [22] Triangles (0,0),(1,0),(0,1) and reversed have signed area +/-0.5.
 * A repeated closing vertex keeps area12; two points have area0. L bounds
 * are min(0,0), max(4,4); a NaN coordinate invalidates the whole outline.
 * [23] L: (1,1),(3,1) in; (3,3),(5,5) out; line contains nothing.
 * [24] L: (5,1) and (3,3) distance1; (-3,-4) distance5; (1,1) inside0.
 * Degenerate outline distance is infinite: adapter returns its exact
 * Infinity predicate because finite JSON expectations cannot encode it.
 * Pin(100,50), yaw90: world(101,47)/(103,47)/(100,44) -> local(3,1)/(3,3)/(6,0),
 * respectively true/false/distance2. The world-transform glue stays inline.
 * [25] Rim at (5,1) -> (4,1), inward(-1,0), dist1; (1,-2) -> (1,0),
 * inward(0,1), dist2. A two-point outline has no rim.
 * Collected polygon source header:

 * Smoke: the CLIENT's polygon primitives answer exactly what the SERVER's do
 * (contract v6 "Gebiete", § B5a — numbers, never screenshots).
 *
 * Usage:  node client3d/scripts/smoke_polygon_containment.mjs
 *
 * Since v6 a location is a drawn POLYGON: `map3d.boundary` in local metres
 * around the pin, turned by `yaw_deg` (§ A1.1). Both sides of the wire have to
 * agree about which metre belongs to which place — the server judges every
 * position report (`world_geometry.boundary_contains` /`location_at_point`),
 * the client predicts that judgement (`game/polygon.ts` + `scene/tiles.tile
 * Contains` + `main.tileAt`), and a client that decided differently would walk
 * the figure into a refusal three times a second.
 *
 * EVERY NUMBER BELOW IS THE SERVER SMOKE'S. `scripts/smoke_world_polygon.py`
 * derives them by hand from the contract; this file repeats the SAME cases
 * against the TypeScript twins and must produce identical answers. Where that
 * file names an expectation, the comment here names it too, so the two can be
 * read side by side.
 *
 * The fixture is its concave L-shape (map view, x east / z south):
 *
 *         (0,0) ──── (4,0)
 *           │  wide     │
 *           │  arm    (4,2)
 *           │    (2,2)──┘
 *           │      │  notch at (3,3)
 *         (0,4)─(2,4)
 *
 * walked clockwise, so the shoelace sum is POSITIVE: 0+8+4+4+8+0 = 24 →
 * signed area +12, and 4×4 minus the 2×2 notch is 12 as well. ✓
 */
```
