#!/usr/bin/env node
/**
 * Smoke check for the pure ENTRY maths of the 3D client
 * (plan-freie-weltkarte-e4-3d-client.md, task 5) —
 * `client3d/src/game/enterLocation.ts`.
 *
 * Usage:  node client3d/scripts/smoke_enter_math.mjs
 *
 * Same discipline as `client3d/scripts/smoke_ground_math.mjs` and
 * `smoke_travel_math.mjs`: every expected number below is derived BY HAND from
 * the contract (§ A1.1 and § B1 Nr. 13 of docs/schnittstellen-3d.md) and from
 * the server's own `app/core/boundary_entry.py`, written out in this header,
 * and NEVER recorded from the current output. A check that only pins today's
 * result proves nothing.
 *
 * `enterLocation.ts` has NO import at all — not even a type-only one — so a
 * plain esbuild transpile loads it here. If someone puts a runtime import into
 * it, this loader fails loudly, which is the intended alarm: the module is the
 * client's mirror of a SERVER rule and has to stay checkable without a
 * bundler, a DOM or three.
 *
 * ===========================================================================
 * WHY THIS FILE EXISTS
 * ===========================================================================
 * Entering a location is the one place where the client anticipates a server
 * decision. The server accepts a crossing only when the reported point lies
 * within 1.5 m of an authored boundary opening (`_POS_OPENING_TOLERANCE_M` in
 * `app/routes/play.py`, checked in `scripts/smoke_play_pos.py`); the client
 * offers "Betreten" within 3 m of the same point and then walks the figure to
 * it. If the two computed that point differently, the offer would promise
 * something the next position report cannot deliver — so the mapping is
 * derived here from the contract, exactly as the server derives it.
 *
 * ---------------------------------------------------------------------------
 * (1) localToWorld — § A1.1, `app/core/world_geometry.local_to_world`
 * ---------------------------------------------------------------------------
 *     x = cx + lx·cos(yaw) + lz·sin(yaw)
 *     z = cz − lx·sin(yaw) + lz·cos(yaw)
 *
 * yaw in RADIANS. At yaw 0 it is a plain translation. The turning cases are
 * hand-computed with cos 90° = 0, sin 90° = 1:
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
 * These are the same numbers the SERVER's docstring derives for
 * `opening_world_points`: "a location at (50, 50), plan_width_m 10, yaw 0,
 * opening N at 0.5 → local (0, −5) → (50, 45); the same location at yaw 90
 * → (45, 50)". Both sides therefore agree on the point the smoke
 * `scripts/smoke_play_pos.py` enters through.
 *
 * ---------------------------------------------------------------------------
 * (2) openingWorldPoints — the payload's `at_world` turned into the world
 * ---------------------------------------------------------------------------
 * The scene payload (§ B1 Nr. 13) delivers each opening TILE-LOCAL, with the
 * world edge letter already resolved by the server (`tile_rotation` applied).
 * So the client only has to turn the point by the tile's own `yaw_deg`, which
 * is `localToWorld` above. A 10 m location has its N edge at local z = −5:
 *
 *   HALL at (50, 50), yaw 0, opening N at_world (0, −5)   -> (50, 45)
 *   the same at yaw 90                                     -> (45, 50)
 *   two openings, N (0, −5) and E (5, 0), yaw 0            -> (50,45), (55,50)
 *   ...and at yaw 90                                       -> (45,50), (50,45)
 *
 * ---------------------------------------------------------------------------
 * (3) entryOfferNear — WHEN "Betreten" stands
 * ---------------------------------------------------------------------------
 * ENTER_RADIUS = 3 m, measured to the opening WORLD POINT. The rules, and the
 * ones that are GONE with the cells:
 *   - the location the avatar stands in is never a candidate (one does not
 *     enter where one is);
 *   - a location without openings offers nothing, however close one stands
 *     (decision 2026-08-04: only an authored opening is an entrance, and the
 *     server refuses the crossing anywhere else);
 *   - 4-ADJACENCY and the crossed-EDGE filter are gone: on a free plane a
 *     crossing has no edge, only a distance — which is what the server
 *     measures too;
 *   - an OPEN location beats a locked one at any distance; among equals the
 *     nearest opening wins.
 *
 * The world for the checks — HALL at (50, 50), 10 m, yaw 0, opening N at
 * (50, 45); BARN at (50, 30), 10 m, yaw 0, opening S at local (0, +5) →
 * (50, 35); SHED at (65, 50), 10 m, yaw 0, NO openings.
 *
 *   avatar (50, 43)  -> HALL's opening (50,45): |43−45| = 2   ≤ 3  -> offered
 *                       BARN's opening (50,35): |43−35| = 8   > 3
 *   avatar (50, 41)  -> HALL 4 m, BARN 6 m: nothing within 3   -> null
 *   avatar (50, 37)  -> BARN 2 m -> BARN offered (HALL is 8 m off)
 *   avatar (50, 40)  -> HALL 5, BARN 5: both out of reach       -> null
 *   avatar (50, 44)  -> HALL 1 m, and HALL is where the avatar already IS
 *                       (myLocId) -> null
 *   avatar (63, 50)  -> SHED has no openings -> null, whatever the distance
 *   avatar (50, 43) with a LOCKED HALL and BARN 8 m away
 *                    -> HALL still, with `locked` in the caller's hands
 *   avatar exactly between two open ones: the nearer wins;
 *   an open one 2.5 m away beats a locked one 1 m away.
 *
 * ---------------------------------------------------------------------------
 * (4) freeBoundaryOf — WHERE a free walker may cross without an opening
 * ---------------------------------------------------------------------------
 * The mirror of the server's rule in `app/routes/play.py`: a location with NO
 * authored boundary opening at all has a FREE boundary and is walked into like
 * open ground (only `accessible_when` and the access rules still judge it);
 * one WITH openings is entered at those and nowhere else, within 1.5 m.
 *
 * The client has TWO sources where the server has one: the COMPOSED scene
 * payload (its cache has three states) and the RAW `map3d.boundary_openings`
 * of the location, which the worldmap row carries (§ A12).
 *
 *   payload with openings -> false: the openings are the way in
 *   payload without any   -> true : free, the server says so too
 *   undefined (in flight) -> false: nothing is known yet, and the conservative
 *                                   answer is the closed one — the opposite
 *                                   would open every footprint for the seconds
 *                                   its payload needs to arrive
 *   null (404 on /scene)  -> the AUTHORED count decides
 *
 * The 404 case is the one that needs both. `/play/locations/{id}/scene`
 * answers 404 for "no building outline, no room with a layout and no building
 * model" — and NOTHING ELSE. The server reads the openings from
 * `map3d.boundary_openings` (`boundary_entry._rotated_openings`), which the
 * world editor lets an author draw before any layout exists. So the two
 * mistakes are symmetric and both are wrong:
 *   - 404 as a WALL bounced the walker off a painted meadow the server would
 *     have let it stroll into (the task-5 ledger finding);
 *   - 404 as FREE would let it stroll into a place whose author HAD drawn a
 *     gate — the server answers `no_opening` 403 and the figure snaps back,
 *     on every single attempt.
 * With openings authored, entering is the ordinary walk to the opening point
 * (`entryOfferNear` above), exactly as for a location that has a scene.
 *
 * ---------------------------------------------------------------------------
 * (5) anchorRawOpening — the 404 case gets its POINTS (E5 task 2)
 * ---------------------------------------------------------------------------
 * Knowing a 404 place is closed is not the same as being able to enter it.
 * The composed openings come with the SCENE, so a location without one had no
 * point to walk to: blocked at the boundary (it has authored openings, so it
 * is no free boundary) and no offer to accept — unreachable on foot, while the
 * server would have let the crossing through. The client therefore anchors the
 * RAW `map3d.boundary_openings` itself, with the server's own formula:
 *
 *   free = (at − 0.5)·w                 w = plan_width_m, half = w/2
 *   N → (free, −half)   S → (free, +half)   W → (−half, free)   E → (+half, free)
 *
 * `tile_rotation` first, in 90° steps: the letter walks N→E→S→W and `at`
 * flips to 1 − at on every step taken FROM an E or a W edge
 * (`boundary_entry._rotated_openings` / `scene_recipe._TILE_EDGE_CW`).
 * `plan_width_m` ≤ 0 (or absent) yields NO point at all — `placed_footprint`
 * refuses the same case, and an invented edge length would put the offer at a
 * metre nobody authored.
 *
 * SIDE BY SIDE with the server. Left: this module, tile-LOCAL. Right:
 * `app/core/boundary_entry.opening_world_points` for a location at (50, 50),
 * yaw 0, i.e. world = (50 + lx, 50 + lz). Every right-hand number is the
 * server's own output for that fixture, and every left-hand one is derived
 * from the formula above:
 *
 *   w=10  N at 0.5   free 0     -> ( 0.0, −5.0)   server N (50.0, 45.0)
 *   w=10  E at 0.25  free −2.5  -> ( 5.0, −2.5)   server E (55.0, 47.5)
 *   w=10  N at 0.30  free −2.0  -> (−2.0, −5.0)   server N (48.0, 45.0)
 *   w=10  N at 0     free −5    -> (−5.0, −5.0)   server N (45.0, 45.0)   NW corner
 *   w=10  N at 1     free +5    -> ( 5.0, −5.0)   server N (55.0, 45.0)   NE corner
 *   w=10  S at 0 / 1            -> (∓5.0, +5.0)   server S (45/55, 55.0)
 *   w=10  W at 0 / 1            -> (−5.0, ∓5.0)   server W (45.0, 45/55)
 *   w=10  E at 0 / 1            -> ( 5.0, ∓5.0)   server E (55.0, 45/55)
 *   w=40  W at 0.25  free −10   -> (−20.0, −10.0) server W (30.0, 40.0)
 *
 *   rotation 90 (the flip rule):
 *   w=10  E at 0.25 -> S at 0.75, free +2.5 -> ( 2.5,  5.0)  server S (52.5, 55.0)
 *   w=10  N at 0.30 -> E at 0.30, free −2.0 -> ( 5.0, −2.0)  server E (55.0, 48.0)
 *   rotation 180: N 0.30 -> E 0.30 -> S 0.70, free +2.0 -> (2.0, 5.0)
 *                                                          server S (52.0, 55.0)
 *   rotation 270: ... -> W 0.70, free +2.0 -> (−5.0, 2.0)  server W (45.0, 52.0)
 *
 *   sanitising, the server's rule verbatim (`_rotated_openings`):
 *   at NaN -> the midpoint 0.5 -> ( 0.0, −5.0)   server N (50.0, 45.0)
 *   at 2   -> clamped to 1     -> ( 5.0, −5.0)   server N (55.0, 45.0)
 *   at −1  -> clamped to 0     -> (−5.0, −5.0)   server N (45.0, 45.0)
 *   w = 0  -> NO point         -> null           server []
 *
 * The one yaw case, to show the two halves compose: the same w=40 S at 0.75 at
 * yaw 90 gives local (10, 20) and `localToWorld(10, 20, 50, 50, π/2)` =
 * (50 + 20, 50 − 10) = (70, 40) — the server's own (70.0, 40.0).
 *
 * INWARD. The scene payload names an `inward` unit normal per opening; a raw
 * one has none, so `inwardOf` supplies it: N is the −z edge, so inward from it
 * is +z. The server's smoke derives the same four
 * (`scripts/smoke_boundary_entry.py` part 1/2): N [0, 1], E [−1, 0], and under
 * rotation 90 the E opening becomes an S one whose inward is [0, −1].
 */
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '../..');
const SRC = join(ROOT, 'client3d/src/game/enterLocation.ts');

async function loadEnterLocation() {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(tmpdir(), 'entermath-'));
  try {
    const source = await readFile(SRC, 'utf8');
    const out = esbuild.transformSync(source, { loader: 'ts', format: 'esm' });
    const file = join(dir, 'enterLocation.mjs');
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

const RAD = (deg) => (deg * Math.PI) / 180;
// The rounding is the check's, not the module's: cos(90°) is 6.1e-17, not 0,
// so a coordinate that should read 45 arrives as 44.99999999999999. Every
// expectation below is exact to the centimetre, which is two orders of
// magnitude finer than anything the payload expresses.
const EPS = 1e-9;

async function main() {
  const {
    localToWorld, openingWorldPoints, entryOfferNear, ENTER_RADIUS,
    freeBoundaryOf, anchorRawOpening, anchorRawOpenings, rotatedEdge, inwardOf,
  } = await loadEnterLocation();

  console.log('\nlocalToWorld — § A1.1, the mapping the server uses');
  check('yaw 0 is a plain translation (N edge of a 10 m square)',
    localToWorld(0, -5, 50, 50, 0), { x: 50, z: 45 }, EPS);
  check('yaw 0, the E edge', localToWorld(5, 0, 50, 50, 0), { x: 55, z: 50 }, EPS);
  check('yaw 90: the N edge point lands west of the centre',
    localToWorld(0, -5, 50, 50, RAD(90)), { x: 45, z: 50 }, EPS);
  check('yaw 90: the E edge point lands north of it',
    localToWorld(5, 0, 50, 50, RAD(90)), { x: 50, z: 45 }, EPS);
  check('yaw 180 mirrors through the centre',
    localToWorld(3, 4, 0, 0, RAD(180)), { x: -3, z: -4 }, EPS);
  check('yaw 270 turns the other way',
    localToWorld(5, 0, 0, 0, RAD(270)), { x: 0, z: 5 }, EPS);

  console.log('\nopeningWorldPoints — the payload is tile-local, the world is not');
  const hallFp = { x: 50, z: 50, yaw: 0 };
  const twoOpenings = [
    { edge: 'N', at: { x: 0, z: -5 } },
    { edge: 'E', at: { x: 5, z: 0 } },
  ];
  check('yaw 0: centre plus the local point',
    openingWorldPoints(hallFp, twoOpenings),
    [{ edge: 'N', x: 50, z: 45 }, { edge: 'E', x: 55, z: 50 }], EPS);
  check('yaw 90: BOTH points turn with the footprint',
    openingWorldPoints({ ...hallFp, yaw: RAD(90) }, twoOpenings),
    [{ edge: 'N', x: 45, z: 50 }, { edge: 'E', x: 50, z: 45 }], EPS);
  check('no openings, no points', openingWorldPoints(hallFp, []), []);

  console.log('\nentryOfferNear — when "Betreten" stands');
  check('ENTER_RADIUS is the 3 m of the plan', ENTER_RADIUS, 3);
  const HALL = {
    locId: 'hall',
    footprint: { x: 50, z: 50, yaw: 0 },
    openings: [{ edge: 'N', at: { x: 0, z: -5 } }],
  };
  const BARN = {
    locId: 'barn',
    footprint: { x: 50, z: 30, yaw: 0 },
    openings: [{ edge: 'S', at: { x: 0, z: 5 } }],
  };
  const SHED = { locId: 'shed', footprint: { x: 65, z: 50, yaw: 0 }, openings: [] };

  check('2 m from the opening: offered, with the point to walk to',
    entryOfferNear({ x: 50, z: 43 }, '', [HALL, BARN]),
    { locId: 'hall', point: { x: 50, z: 45 }, edge: 'N', dist: 2 }, EPS);
  check('4 m from it: nothing on offer',
    entryOfferNear({ x: 50, z: 41 }, '', [HALL, BARN]), null);
  check('the other side of the road offers the OTHER barn',
    entryOfferNear({ x: 50, z: 37 }, '', [HALL, BARN])?.locId, 'barn');
  check('exactly between the two, out of reach of both',
    entryOfferNear({ x: 50, z: 40 }, '', [HALL, BARN]), null);
  check('the location one is IN is never offered',
    entryOfferNear({ x: 50, z: 44 }, 'hall', [HALL, BARN]), null);
  check('a location without openings offers nothing at any distance',
    entryOfferNear({ x: 63, z: 50 }, '', [SHED]), null);
  check('...not even standing on its edge',
    entryOfferNear({ x: 60, z: 50 }, '', [SHED]), null);

  console.log('\nentryOfferNear — open beats locked, then nearest');
  const LOCKED_HALL = { ...HALL, locked: true };
  const NEAR_LOCKED = {
    locId: 'gate',
    footprint: { x: 50, z: 30, yaw: 0 },
    openings: [{ edge: 'S', at: { x: 0, z: 5 } }],   // world (50, 35)
    locked: true,
  };
  // Avatar at (50, 36.5): the locked gate's opening is 1.5 m away, HALL's is
  // 8.5 m — out of reach, so the locked one is the only answer there is.
  check('a lone locked place is still the answer (the key says why)',
    entryOfferNear({ x: 50, z: 36.5 }, '', [NEAR_LOCKED, HALL])?.locId, 'gate');
  // Avatar at (50, 43.5): HALL 1.5 m (open) — and a locked gate at 1 m.
  const CLOSER_LOCKED = {
    locId: 'gate',
    footprint: { x: 50, z: 39.5, yaw: 0 },
    openings: [{ edge: 'N', at: { x: 0, z: -5 } }],  // world (50, 34.5)... see below
    locked: true,
  };
  // Its opening is at (50, 34.5), which is 9 m away — deliberately NOT the
  // case being made. The locked one that IS in reach sits at (50, 44.5):
  const LOCKED_IN_REACH = {
    locId: 'gate',
    footprint: { x: 50, z: 49.5, yaw: 0 },
    openings: [{ edge: 'N', at: { x: 0, z: -5 } }],  // world (50, 44.5)
    locked: true,
  };
  check('an open one 1.5 m off beats a locked one 1 m off',
    entryOfferNear({ x: 50, z: 43.5 }, '', [LOCKED_IN_REACH, HALL])?.locId, 'hall');
  check('...and the order of the candidates does not decide it',
    entryOfferNear({ x: 50, z: 43.5 }, '', [HALL, LOCKED_IN_REACH])?.locId, 'hall');
  check('two locked ones: the nearer wins',
    entryOfferNear({ x: 50, z: 43.5 }, '', [LOCKED_HALL, LOCKED_IN_REACH])?.locId,
    'gate');
  check('the far locked gate is out of reach either way',
    entryOfferNear({ x: 50, z: 43.5 }, '', [CLOSER_LOCKED]), null);

  console.log('\nfreeBoundaryOf — the scene cache and the authored openings');
  const COMPOSED = { boundary_openings: [{ edge: 'N', at_world: { x: 0, z: -5 } }] };
  check('a payload with an opening is entered THERE, not anywhere',
    freeBoundaryOf(COMPOSED, 1), false);
  check('a payload with an empty opening list is a free boundary',
    freeBoundaryOf({ boundary_openings: [] }, 0), true);
  check('a payload that states no openings at all is one too',
    freeBoundaryOf({}, 0), true);
  //   with a payload the COMPOSED list is the better answer and the raw count
  //   has no say — the two can only disagree while a save is in flight
  check('a payload beats the authored count (composed wins)',
    freeBoundaryOf({ boundary_openings: [] }, 3), true);
  check('...in the other direction too', freeBoundaryOf(COMPOSED, 0), false);
  //   404 + nothing authored: the meadow of the task-5 ledger finding
  check('404 and no authored opening is a free boundary',
    freeBoundaryOf(null, 0), true);
  //   404 + a gate drawn before any layout exists: still the gate, not a stroll
  check('404 with an authored opening stays closed',
    freeBoundaryOf(null, 1), false);
  check('...however many are drawn', freeBoundaryOf(null, 4), false);
  //   in flight: neither source is asked, the answer is the closed one
  check('a payload still in flight stays closed (the conservative answer)',
    freeBoundaryOf(undefined, 0), false);
  check('...and stays closed with openings authored as well',
    freeBoundaryOf(undefined, 2), false);

  console.log('\nanchorRawOpening — the raw list anchored like the server does');
  // Every expectation is the LEFT column of the table in the header; the
  // comment behind it is the server's own output for the same fixture at
  // centre (50, 50), yaw 0 (`boundary_entry.opening_world_points`).
  check('N at 0.5 is the middle of the north edge',
    anchorRawOpening('N', 0.5, 10), { x: 0, z: -5 }, EPS);          // (50, 45)
  check('E at 0.25 sits a quarter down the east edge',
    anchorRawOpening('E', 0.25, 10), { x: 5, z: -2.5 }, EPS);       // (55, 47.5)
  check('N at 0.30', anchorRawOpening('N', 0.3, 10), { x: -2, z: -5 }, EPS); // (48, 45)
  check('N at 0 is the NW corner',
    anchorRawOpening('N', 0, 10), { x: -5, z: -5 }, EPS);           // (45, 45)
  check('N at 1 is the NE corner',
    anchorRawOpening('N', 1, 10), { x: 5, z: -5 }, EPS);            // (55, 45)
  check('S runs left to right as well (at 0)',
    anchorRawOpening('S', 0, 10), { x: -5, z: 5 }, EPS);            // (45, 55)
  check('...and at 1', anchorRawOpening('S', 1, 10), { x: 5, z: 5 }, EPS);   // (55, 55)
  check('W runs top to bottom (at 0)',
    anchorRawOpening('W', 0, 10), { x: -5, z: -5 }, EPS);           // (45, 45)
  check('...and at 1', anchorRawOpening('W', 1, 10), { x: -5, z: 5 }, EPS);  // (45, 55)
  check('E at 0', anchorRawOpening('E', 0, 10), { x: 5, z: -5 }, EPS);       // (55, 45)
  check('E at 1', anchorRawOpening('E', 1, 10), { x: 5, z: 5 }, EPS);        // (55, 55)
  check('a 40 m location: W at 0.25 is 10 m up its west edge',
    anchorRawOpening('W', 0.25, 40), { x: -20, z: -10 }, EPS);      // (30, 40)

  console.log('\nanchorRawOpening — tile_rotation, the composer\'s own flip rule');
  check('90°: E at 0.25 becomes the S edge at 0.75',
    anchorRawOpening('E', 0.25, 10, 90), { x: 2.5, z: 5 }, EPS);    // S (52.5, 55)
  check('90°: N at 0.30 becomes the E edge, `at` unflipped',
    anchorRawOpening('N', 0.3, 10, 90), { x: 5, z: -2 }, EPS);      // E (55, 48)
  check('180°: N at 0.30 becomes S at 0.70',
    anchorRawOpening('N', 0.3, 10, 180), { x: 2, z: 5 }, EPS);      // S (52, 55)
  check('270°: ...and W at 0.70',
    anchorRawOpening('N', 0.3, 10, 270), { x: -5, z: 2 }, EPS);     // W (45, 52)
  check('360° is no rotation at all',
    anchorRawOpening('N', 0.3, 10, 360), { x: -2, z: -5 }, EPS);
  check('the letter turns with it', rotatedEdge('E', 90), 'S');
  check('...twice', rotatedEdge('N', 180), 'S');
  check('...and not at all without rotation', rotatedEdge('W'), 'W');

  console.log('\nanchorRawOpening — the sanitising the server does too');
  check('an unusable `at` is the edge MIDPOINT',
    anchorRawOpening('N', Number.NaN, 10), { x: 0, z: -5 }, EPS);   // (50, 45)
  check('`at` past the end is pulled onto the edge',
    anchorRawOpening('N', 2, 10), { x: 5, z: -5 }, EPS);            // (55, 45)
  check('...and before the start as well',
    anchorRawOpening('N', -1, 10), { x: -5, z: -5 }, EPS);          // (45, 45)
  // WITHOUT AN ANCHOR THERE IS NO POINT — `placed_footprint` refuses the very
  // same case, so the server would not name a point either.
  check('no plan width, no point', anchorRawOpening('N', 0.5, 0), null);
  check('...a negative one neither', anchorRawOpening('N', 0.5, -10), null);
  check('...nor a non-finite one', anchorRawOpening('N', 0.5, Number.NaN), null);
  check('an edge letter that is none', anchorRawOpening('X', 0.5, 10), null);

  console.log('\nanchorRawOpenings — the whole list, and what drops out of it');
  check('two openings, both anchored',
    anchorRawOpenings([{ edge: 'N', at: 0.5 }, { edge: 'E', at: 0.5 }], 10),
    [{ edge: 'N', at: { x: 0, z: -5 } }, { edge: 'E', at: { x: 5, z: 0 } }], EPS);
  check('rotation turns letter AND point together',
    anchorRawOpenings([{ edge: 'E', at: 0.25 }], 10, 90),
    [{ edge: 'S', at: { x: 2.5, z: 5 } }], EPS);
  check('no anchor: the location stays closed, not free',
    anchorRawOpenings([{ edge: 'N', at: 0.5 }], 0), []);
  check('nothing authored, nothing anchored', anchorRawOpenings([], 10), []);
  check('...and a missing list is the same', anchorRawOpenings(undefined, 10), []);

  console.log('\ninwardOf — the normal a raw opening has no payload for');
  check('N is the −z edge, so inward is +z', inwardOf('N'), { x: 0, z: 1 }, EPS);
  check('S', inwardOf('S'), { x: 0, z: -1 }, EPS);
  check('W', inwardOf('W'), { x: 1, z: 0 }, EPS);
  check('E', inwardOf('E'), { x: -1, z: 0 }, EPS);
  // The rotated case of the server's smoke: an E opening under rotation 90 is
  // an S opening, and its inward is S's own — the two derivations agree.
  check('a rotated E opening carries S\'s inward',
    inwardOf(rotatedEdge('E', 90)), { x: 0, z: -1 }, EPS);

  console.log('\nthe two halves compose — local anchor, then § A1.1');
  // w=40, S at 0.75 -> local (10, 20); centre (50, 50) at yaw 90 -> (70, 40),
  // which is what `opening_world_points` answers for that very fixture.
  const s75 = anchorRawOpening('S', 0.75, 40);
  check('the raw anchor turned into the world at yaw 90',
    localToWorld(s75.x, s75.z, 50, 50, RAD(90)), { x: 70, z: 40 }, EPS);
  check('...and the whole list through `openingWorldPoints`',
    openingWorldPoints({ x: 50, z: 50, yaw: 0 },
      anchorRawOpenings([{ edge: 'N', at: 0.5 }, { edge: 'E', at: 0.25 }], 10)),
    [{ edge: 'N', x: 50, z: 45 }, { edge: 'E', x: 55, z: 47.5 }], EPS);

  console.log(`\n${passed} passed, ${failed} failed`);
  return failed ? 1 : 0;
}

main().then((code) => process.exit(code), (err) => {
  console.error('smoke_enter_math:', err?.message || err);
  process.exit(1);
});
