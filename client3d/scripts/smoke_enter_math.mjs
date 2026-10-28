#!/usr/bin/env node
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
import { vectorChecks } from './embodyVectorDispatch.mjs';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const vectorCase = vectorChecks(check, ["enter"]);

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '../..');
const SRC_DIR = join(ROOT, 'client3d/src/game');
/** `enterLocation.ts` and the one module it imports — the polygon primitives
 *  the free-boundary rule is measured with (contract v6). Both are pure TS with
 *  no runtime dependency, so a plain transpile is enough; the only fix-up is
 *  the extension Node's ESM loader wants. */
const MODULES = ['polygon', 'enterLocation'];

async function loadEnterLocation() {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(tmpdir(), 'entermath-'));
  try {
    for (const name of MODULES) {
      const source = await readFile(join(SRC_DIR, `${name}.ts`), 'utf8');
      const out = esbuild.transformSync(source, { loader: 'ts', format: 'esm' });
      await writeFile(join(dir, `${name}.mjs`),
        out.code.replace(/(from\s*["'])(\.\/[\w-]+)(["'])/g, '$1$2.mjs$3'), 'utf8');
    }
    return await import(`file://${join(dir, 'enterLocation.mjs')}`);
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
  const { localToWorld, entryOfferNear, ENTER_RADIUS } = await loadEnterLocation();

  console.log('\nlocalToWorld — § A1.1, the mapping the server uses');
  vectorCase("[20] " + ('yaw 0 is a plain translation (N edge of a 10 m square)'));
  vectorCase("[20] " + ('yaw 0, the E edge'));
  vectorCase("[20] " + ('yaw 90: the N edge point lands west of the centre'));
  vectorCase("[20] " + ('yaw 90: the E edge point lands north of it'));
  vectorCase("[20] " + ('yaw 180 mirrors through the centre'));
  vectorCase("[20] " + ('yaw 270 turns the other way'));

  /**
   * THE GATEHOUSE — the one fixture `scripts/smoke_worldmap_v2.py` [9] checks
   * on the server side. Both files carry the same four numbers; the server
   * derives them, this one proves the client passes them through untouched.
   */
  console.log('\nentryOfferNear — the openings arrive FINISHED (v6, § A1.3)');
  const GATE = {
    locId: 'gate',
    footprint: { x: 0, z: 0, yaw: 0 },
    openings: [{ edge: 0, at_world: [0, -6], inward: [0, 1], room: '' }],
  };
  vectorCase("[21] " + ('2 m from the gatehouse opening: offered, verbatim'));
  vectorCase("[21] 4 m from it: nothing on offer (1)");
  // The TURNED gatehouse: the server delivered (−6, 0) / (1, 0) for yaw 90,
  // and the client must not turn that a second time — the footprint yaw is
  // read for the free boundary alone.
  const GATE_90 = {
    locId: 'gate',
    footprint: { x: 0, z: 0, yaw: RAD(90) },
    openings: [{ edge: 0, at_world: [-6, 0], inward: [1, 0], room: '' }],
  };
  vectorCase("[21] " + ('yaw 90: the server-turned point is handed back unturned'));

  console.log('\nentryOfferNear — when "Betreten" stands');
  check('ENTER_RADIUS is the 3 m of the plan', ENTER_RADIUS, 3);
  const HALL = {
    locId: 'hall',
    footprint: { x: 50, z: 50, yaw: 0 },
    openings: [{ edge: 0, at_world: [50, 45], inward: [0, 1] }],
  };
  const BARN = {
    locId: 'barn',
    footprint: { x: 50, z: 30, yaw: 0 },
    openings: [{ edge: 2, at_world: [50, 35], inward: [0, -1] }],
  };
  const SHED = { locId: 'shed', footprint: { x: 65, z: 50, yaw: 0 }, openings: [] };

  vectorCase("[21] " + ('2 m from the opening: offered, with the point to walk to'));
  vectorCase("[21] 4 m from it: nothing on offer (2)");
  vectorCase("[21] " + ('the other side of the road offers the OTHER barn'));
  vectorCase("[21] " + ('...and its own inward normal comes with it'));
  vectorCase("[21] " + ('exactly between the two, out of reach of both'));
  vectorCase("[21] " + ('the location one is IN is never offered'));
  vectorCase("[21] " + ('a location without openings AND without an outline offers nothing'));
  vectorCase("[21] " + ('...not even standing where its rim would be'));
  // A turned footprint does not move an authored opening — the payload point
  // is the payload point (the same statement as the gatehouse case, made on
  // the fixture the distance rules run on).
  vectorCase("[21] " + ('the footprint yaw does not touch an authored opening'));

  /**
   * --- A FREE BOUNDARY IS ITS WHOLE RIM (contract v6 "Gebiete") ------------
   *
   * A location with NO authored opening never said where its way in is, so
   * anywhere along the DRAWN OUTLINE counts — measured as the distance to the
   * polygon rim, not to the edges of a square (the square is only that
   * polygon's special case, and the client has no code path for it any more).
   *
   * THE MEADOW: pin (50, 50), yaw 0, outline the 10 m square
   * (−5,−5) (5,−5) (5,5) (−5,5) — clockwise in map view, the stored winding.
   *
   *   avatar (57, 50) -> local (7, 0); the nearest rim point is local (5, 0),
   *     2 m away, so world (55, 50) and dist 2. INWARD: that point sits on the
   *     edge (5,−5)→(5,5), direction (0, 10); the interior lies to the left of
   *     a clockwise edge, which is (−dz, dx)/|d| = (−1, 0) — and −x is indeed
   *     where the middle of the square is.
   *   avatar (59, 50) -> 4 m from the rim, past ENTER_RADIUS = 3 -> nothing.
   *   avatar (52, 50) -> INSIDE, 3 m from the same rim point: the rim distance
   *     does not care which side one is on, so the offer stands at exactly the
   *     radius. (One normally stands IN the place then, and `myLocId` drops it
   *     — this is the boundary case of the measurement, not of the UX.)
   *
   * THE TURNED MEADOW: the same square at yaw 90.
   *   avatar (50, 43): world→local turns (0, −7) into (7, 0) — the same local
   *     point as the first case — so the rim point is local (5, 0), at 2 m.
   *     Turned back it is world (50, 45), and the inward normal (−1, 0)
   *     becomes world (0, 1): south, into the square through its north edge.
   */
  console.log('\nentryOfferNear — a free boundary is its whole rim (v6)');
  const SQUARE = [[-5, -5], [5, -5], [5, 5], [-5, 5]];
  const MEADOW = {
    locId: 'meadow',
    footprint: { x: 50, z: 50, yaw: 0 },
    openings: [],
    boundary: SQUARE,
  };
  vectorCase("[21] " + ('2 m outside the rim: offered, at the rim point, with its inward normal'));
  vectorCase("[21] " + ('4 m outside: out of reach'));
  vectorCase("[21] " + ('3 m INSIDE the rim: the distance is a distance, so it stands'));
  vectorCase("[21] " + ('the place one is IN is dropped before any of that'));
  const TURNED = { ...MEADOW, locId: 'turned',
                   footprint: { x: 50, z: 50, yaw: RAD(90) } };
  vectorCase("[21] " + ('yaw 90: the rim point and the normal turn with the footprint'));
  // An authored opening still wins over the rim: a place that says where its
  // way in is has no free boundary at all, and the offer is the opening's own
  // point — the outline is not consulted.
  vectorCase("[21] " + ('with an authored opening the rim is not consulted'));

  console.log('\nentryOfferNear — open beats locked, then nearest');
  const LOCKED_HALL = { ...HALL, locked: true };
  const NEAR_LOCKED = {
    locId: 'gate',
    footprint: { x: 50, z: 30, yaw: 0 },
    openings: [{ edge: 2, at_world: [50, 35], inward: [0, -1] }],
    locked: true,
  };
  // Avatar at (50, 36.5): the locked gate's opening is 1.5 m away, HALL's is
  // 8.5 m — out of reach, so the locked one is the only answer there is.
  vectorCase("[21] " + ('a lone locked place is still the answer (the key says why)'));
  // Avatar at (50, 43.5): HALL 1.5 m (open) — and a locked gate 1 m off, whose
  // opening sits at (50, 44.5).
  const LOCKED_IN_REACH = {
    locId: 'gate',
    footprint: { x: 50, z: 49.5, yaw: 0 },
    openings: [{ edge: 0, at_world: [50, 44.5], inward: [0, 1] }],
    locked: true,
  };
  // ...and one whose opening is 9 m away: out of reach either way, the case
  // being made is the one above.
  const FAR_LOCKED = {
    locId: 'gate',
    footprint: { x: 50, z: 39.5, yaw: 0 },
    openings: [{ edge: 0, at_world: [50, 34.5], inward: [0, 1] }],
    locked: true,
  };
  vectorCase("[21] " + ('an open one 1.5 m off beats a locked one 1 m off'));
  vectorCase("[21] " + ('...and the order of the candidates does not decide it'));
  vectorCase("[21] " + ('two locked ones: the nearer wins'));
  vectorCase("[21] " + ('the far locked gate is out of reach either way'));

  console.log('\nthe free-boundary statement is the EMPTY list (v6)');
  // No `freeBoundaryOf` any more: an empty opening list IS "enter anywhere
  // along the rim", and a non-empty one IS "only here". Both are shown on the
  // same fixture, with and without an outline.
  vectorCase("[21] " + ('no openings + an outline -> the rim answers'));
  vectorCase("[21] " + ('openings + the same outline -> the opening answers'));

  console.log(`\n${passed} passed, ${failed} failed`);
  return failed ? 1 : 0;
}

main().then((code) => process.exit(code), (err) => {
  console.error('smoke_enter_math:', err?.message || err);
  process.exit(1);
});
