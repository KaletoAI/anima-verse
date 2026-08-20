/**
 * Smoke run for the BOUNDARY EDIT in the floor-plan editor — the arithmetic
 * behind `RoomLayoutEditor`'s new 🟩 tool, which mounts the ONE `PolygonHandles`
 * gesture on `map3d.boundary`.
 *
 * Usage:  node scripts/smoke_plan_boundary_edit.mjs
 *         (bundles the modules with esbuild — a Vite dependency, already
 *          installed; no bundler config, no jsdom, no server)
 *
 * There is no jsdom harness in this repo and no frontend test runner, so the
 * check is what a check here can be: the PURE math the gesture stands on, with
 * every number derived BY HAND from the rules below and never recorded from
 * the current output. What is deliberately NOT covered is the React wiring
 * (the context provider, the SVG that carries the handles, the toolbar mode) —
 * that is a rendering question and this file would only be able to record it.
 *
 * ---------------------------------------------------------------------------
 * [1] THE TWO VIEWPORT VOCABULARIES (`planGeometry.planMapView`)
 * ---------------------------------------------------------------------------
 * The floor plan states a viewport as a min corner plus a square edge
 * (`PlanView {x0, z0, size}`); the map canvas states it as a centre plus a
 * zoom (`mapMath.View {cx, cz, pxPerM}`). `PolygonHandles` reads the map's
 * form, so the plan is translated once — and the translation must be EXACT,
 * or the handles sit next to the polygon they are supposed to hold:
 *
 *     pxPerM = canvasPx / size          cx = x0 + size/2      w = h = canvasPx
 *     worldToScreen(x) = w/2 + (x − cx)·pxPerM
 *                      = canvasPx·(x − x0)/size
 *                      = viewFx(v, x)·canvasPx                 ← the identity
 *
 * Hand-derived cases (the canvas is square, so one edge is both w and h):
 *
 *   A) v = {x0:−7, z0:−7, size:14}, canvasPx 420   (the default plan, zoom 1)
 *        pxPerM = 420/14 = 30,  cx = cz = 0
 *        (5, −3) -> x = 210 + 5·30 = 360,  y = 210 + (−3)·30 = 120
 *        and viewFx = (5+7)/14 = 12/14 -> ·420 = 360            ✔ identical
 *           viewFz = (−3+7)/14 = 4/14 -> ·420 = 120             ✔
 *        screenToWorld(360, 120) = (0 + 150/30, 0 + (−90)/30) = (5, −3)  ✔
 *   B) v = {x0:2, z0:−3, size:20}, canvasPx 300    (an off-centre plot)
 *        pxPerM = 15, cx = 12, cz = 7
 *        the window's min corner (2, −3) -> (0, 0)            = canvas corner
 *        the window's max corner (22, 17) -> (300, 300)       = the other one
 *   C) v = {x0:−7, z0:−7, size:14}, canvasPx 1260  (the 3× plan zoom)
 *        pxPerM = 90 — the canvas grows, the window does not, and (5,5) lands
 *        at 630 + 450 = 1080 on both axes; viewFx·1260 = (12/14)·1260 = 1080
 *   D) a degenerate window (size 0) or an unmeasured canvas (0 px) must not
 *        divide anything by nothing: both fall back to 1, so
 *        planMapView({0,0,0}, 0) = {view:{cx:0.5, cz:0.5, pxPerM:1}, w:1, h:1}
 *        — useless but finite, instead of NaN handles.
 *
 * THE DRAG ITSELF needs no case of its own: `PolygonHandles` moves a vertex by
 * `ox + dx/pxPerM` and rounds to 2 decimals, so pxPerM is the whole conversion
 * and case A pins it at 30 — a 45 px drag is 1.5 m, a 7 px drag is 0.2333… ->
 * 0.23 m, the centimetre the server stores.
 *
 * ---------------------------------------------------------------------------
 * [2] THE COMMIT of one finished vertex gesture
 * ---------------------------------------------------------------------------
 * NO PIN TRANSFORM IS INVOLVED — that is the point. The map tab drags in WORLD
 * metres and has to send every vertex back through § A1.1; the floor plan
 * already draws in the location's LOCAL metres, the very frame `map3d.boundary`
 * is stored in, so what comes out of the gesture is the stored value verbatim.
 *
 * Boundary [[−5,−5], [5,−5], [5,5], [−5,5]] in the window of case A:
 *   vertex 1 (5,−5) sits at screen (210 + 150, 210 − 150) = (360, 60)
 *   drag it +30 px right and +60 px down -> screen (390, 120)
 *   screenToWorld(390, 120) = ((390−210)/30, (120−210)/30) = (6, −3)
 *   commit = [[−5,−5], [6,−3], [5,5], [−5,5]]
 *
 * That list has to survive `world_ops._sanitize_map3d` UNCHANGED, or the
 * read-back would move the handles the hand just placed. Two rules decide it:
 *   * ≥ 3 points, none further than the coordinate bound from the pin
 *     -> `boundaryComplaint` says nothing;
 *   * ONE winding: clockwise in map view = POSITIVE shoelace sum, else the
 *     server reverses the ring and every handle index shifts. By hand:
 *       (−5,−5)->(6,−3):  (−5)(−3) − (6)(−5)  = 15 + 30 = 45
 *       (6,−3) ->(5, 5):  (6)(5)   − (5)(−3)  = 30 + 15 = 45
 *       (5, 5) ->(−5,5):  (5)(5)   − (−5)(5)  = 25 + 25 = 50
 *       (−5,5) ->(−5,−5): (−5)(−5) − (−5)(5)  = 25 + 25 = 50
 *                                                  sum  = 190 > 0   ✔ kept
 *
 * ---------------------------------------------------------------------------
 * [3] THE SEED (`boundaryApi.seedSquare`) — the shared first shape
 * ---------------------------------------------------------------------------
 * A centred square, clockwise in map view, rounded to the centimetre:
 *   seedSquare(10)     -> h = 5    -> [[−5,−5],[5,−5],[5,5],[−5,5]]
 *                         shoelace = 4 · 2h² = 200 > 0, so the sanitizer keeps
 *                         the order and the vertices stay where they were put
 *   seedSquare(14.005) -> h = round(700.25)/100 = 7      (the cm rounding)
 *   seedSquare(0.03)   -> h = round(1.5)/100 = 0.02      (JS rounds .5 up)
 *
 * ---------------------------------------------------------------------------
 * [4] THE THREE RULES of a boundary write (`boundaryApi.boundaryComplaint`)
 * ---------------------------------------------------------------------------
 * One list, two editors — the map tab and the floor plan must refuse the same
 * things, and each returns the ENGLISH source string plus its number, so the
 * caller can translate it:
 *   2 points               -> "needs at least {n} points", n = 3
 *   3 points               -> null                       (the smallest area)
 *   64 points              -> null                       (the server's cap)
 *   65 points              -> "holds at most {n} points", n = 64
 *   a point at ±100000     -> null                       (exactly the bound)
 *   a point at 100000.01   -> "may not lie further than {n} m", n = 100000
 *   a NaN coordinate       -> the same distance complaint (it is not a point)
 * The order matters: too few points is reported before the distance, because a
 * two-point "boundary" is not a shape whose distances mean anything.
 */
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = fileURLToPath(new URL('..', import.meta.url));

/** The three modules behind one entry point — `boundaryApi` pulls in the API
 *  client, which esbuild resolves and inlines; it is never called here. */
async function loadModules() {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(tmpdir(), 'planboundary-smoke-'));
  try {
    const file = join(dir, 'entry.mjs');
    await esbuild.build({
      stdin: {
        contents: [
          "export { planMapView, viewFx, viewFz } from"
          + " './frontend/src/tabs/world/planGeometry'",
          "export { screenToWorld, worldToScreen } from"
          + " './frontend/src/tabs/map/mapMath'",
          "export { BOUNDARY_MAX_COORD_M, BOUNDARY_MAX_POINTS,"
          + " BOUNDARY_MIN_POINTS, boundaryComplaint, seedSquare } from"
          + " './frontend/src/tabs/world/boundaryApi'",
        ].join('\n'),
        resolveDir: ROOT,
        loader: 'ts',
      },
      outfile: file, bundle: true, format: 'esm', platform: 'neutral',
      logLevel: 'silent', absWorkingDir: ROOT,
    });
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

/** Shoelace sum of a ring — POSITIVE means clockwise in map view (x east,
 *  z south), which is the one winding the server stores. */
function shoelace(pts) {
  let sum = 0;
  for (let i = 0; i < pts.length; i++) {
    const [ax, az] = pts[i];
    const [bx, bz] = pts[(i + 1) % pts.length];
    sum += ax * bz - bx * az;
  }
  return sum;
}

const {
  planMapView, viewFx, viewFz, screenToWorld, worldToScreen,
  BOUNDARY_MAX_COORD_M, BOUNDARY_MAX_POINTS, BOUNDARY_MIN_POINTS,
  boundaryComplaint, seedSquare,
} = await loadModules();

console.log('[1] the two viewport vocabularies (planMapView)');
const vA = { x0: -7, z0: -7, size: 14 };
const mA = planMapView(vA, 420);
check('A: 14 m over 420 px', mA,
  { view: { cx: 0, cz: 0, pxPerM: 30 }, w: 420, h: 420 });
check('A: (5,−3) -> screen (360, 120)',
  worldToScreen(5, -3, mA.view, mA.w, mA.h), { x: 360, y: 120 });
check('A: the plan\'s own fx lands on the same pixel',
  [viewFx(vA, 5) * 420, viewFz(vA, -3) * 420], [360, 120]);
check('A: screenToWorld is the exact inverse',
  screenToWorld(360, 120, mA.view, mA.w, mA.h), { x: 5, z: -3 });

const vB = { x0: 2, z0: -3, size: 20 };
const mB = planMapView(vB, 300);
check('B: off-centre window', mB.view, { cx: 12, cz: 7, pxPerM: 15 });
check('B: the window\'s min corner is the canvas corner',
  worldToScreen(2, -3, mB.view, mB.w, mB.h), { x: 0, y: 0 });
check('B: the window\'s max corner is the far canvas corner',
  worldToScreen(22, 17, mB.view, mB.w, mB.h), { x: 300, y: 300 });

const mC = planMapView(vA, 1260);
check('C: 3x plan zoom triples pxPerM only', mC.view,
  { cx: 0, cz: 0, pxPerM: 90 });
check('C: (5,5) -> 1080 on both axes, like fx·canvasPx',
  [worldToScreen(5, 5, mC.view, mC.w, mC.h).x, viewFx(vA, 5) * 1260],
  [1080, 1080]);

check('D: a degenerate window and an unmeasured canvas stay finite',
  planMapView({ x0: 0, z0: 0, size: 0 }, 0),
  { view: { cx: 0.5, cz: 0.5, pxPerM: 1 }, w: 1, h: 1 });

console.log('[2] the commit of one finished vertex gesture');
const ring = [[-5, -5], [5, -5], [5, 5], [-5, 5]];
check('vertex 1 sits at screen (360, 60)',
  worldToScreen(ring[1][0], ring[1][1], mA.view, mA.w, mA.h), { x: 360, y: 60 });
const dragged = screenToWorld(390, 120, mA.view, mA.w, mA.h);
check('dragged +30/+60 px -> local metres (6, −3)', [dragged.x, dragged.z],
  [6, -3]);
const committed = ring.map((p, i) => (i === 1 ? [dragged.x, dragged.z] : p));
check('the commit list is the stored value verbatim — no pin transform',
  committed, [[-5, -5], [6, -3], [5, 5], [-5, 5]]);
check('the sanitizer has nothing to complain about',
  boundaryComplaint(committed), null);
check('and nothing to re-wind: the shoelace stays positive',
  shoelace(committed), 190);

console.log('[3] the seed square');
check('seedSquare(10)', seedSquare(10), [[-5, -5], [5, -5], [5, 5], [-5, 5]]);
check('seedSquare(10) winds clockwise in map view', shoelace(seedSquare(10)),
  200);
check('seedSquare(14.005) rounds to the centimetre', seedSquare(14.005),
  [[-7, -7], [7, -7], [7, 7], [-7, 7]]);
check('seedSquare(0.03) rounds .5 up, like the sanitizer',
  seedSquare(0.03), [[-0.02, -0.02], [0.02, -0.02], [0.02, 0.02], [-0.02, 0.02]]);

console.log('[4] the three rules of a boundary write');
const square = (n) => Array.from({ length: n }, (_, i) => [i, 0]);
check('the caps are the server\'s',
  [BOUNDARY_MIN_POINTS, BOUNDARY_MAX_POINTS, BOUNDARY_MAX_COORD_M],
  [3, 64, 100000]);
check('2 points', boundaryComplaint(square(2)),
  { message: 'A boundary needs at least {n} points', n: 3 });
check('3 points', boundaryComplaint(square(3)), null);
check('64 points', boundaryComplaint(square(64)), null);
check('65 points', boundaryComplaint(square(65)),
  { message: 'A boundary holds at most {n} points', n: 64 });
check('exactly at the distance bound',
  boundaryComplaint([[100000, 0], [0, -100000], [-100000, 0]]), null);
check('one centimetre past it',
  boundaryComplaint([[100000.01, 0], [0, -1], [-1, 0]]),
  { message: 'A boundary point may not lie further than {n} m from the pin',
    n: 100000 });
check('a NaN coordinate is not a point either',
  boundaryComplaint([[NaN, 0], [0, -1], [-1, 0]]),
  { message: 'A boundary point may not lie further than {n} m from the pin',
    n: 100000 });
check('too few points is reported before the distance',
  boundaryComplaint([[100000.01, 0], [0, -1]]),
  { message: 'A boundary needs at least {n} points', n: 3 });

console.log(`\n${passed} ok, ${failed} failed`);
process.exit(failed ? 1 : 0);
