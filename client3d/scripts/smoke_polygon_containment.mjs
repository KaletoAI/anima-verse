/**
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
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '../..');
const SRC_DIR = join(ROOT, 'client3d/src/game');
/** `polygon.ts` is import-free by design (see its header), so a plain
 *  transpile is enough — no bundler, no `three`, no DOM. */
async function loadPolygon() {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(tmpdir(), 'polymath-'));
  try {
    const source = await readFile(join(SRC_DIR, 'polygon.ts'), 'utf8');
    const out = esbuild.transformSync(source, { loader: 'ts', format: 'esm' });
    const file = join(dir, 'polygon.mjs');
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
  if (typeof b === 'number') {
    return typeof a === 'number'
      && (a === b || Math.abs(a - b) <= eps);
  }
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

const L_SHAPE = [[0, 0], [4, 0], [4, 2], [2, 2], [2, 4], [0, 4]];

/** World → tile-local, § A1.1 (`world_geometry.world_to_local`, and the very
 *  turn `scene/tiles.worldToTile` does). Spelled out here so the cases below
 *  can be stated in WORLD metres, the way a walking figure meets them. */
const RAD = (deg) => (deg * Math.PI) / 180;
function worldToLocal(x, z, cx, cz, yawDeg) {
  const c = Math.cos(RAD(yawDeg));
  const s = Math.sin(RAD(yawDeg));
  const dx = x - cx;
  const dz = z - cz;
  return { x: dx * c - dz * s, z: dx * s + dz * c };
}

async function main() {
  const {
    pointInPolygon, polygonArea, polygonSignedArea, polygonBounds,
    polygonDistance, sanitizePolygon, nearestRimPoint,
  } = await loadPolygon();

  /**
   * ------------------------------------------------------------------------
   * (1) WINDING AND AREA — smoke_world_polygon.py, "winding / area"
   * ------------------------------------------------------------------------
   * The area is what decides which of two overlapping places owns a point
   * (v6 Nr. 6), so its sign convention has to be the server's exactly.
   */
  console.log('winding / area (hand: +12 CW, 16 − 4 notch)');
  check('signed area L', polygonSignedArea(L_SHAPE), 12);
  check('area L', polygonArea(L_SHAPE), 12);
  check('signed area CW triangle',
    polygonSignedArea([[0, 0], [1, 0], [0, 1]]), 0.5);
  check('signed area CCW triangle',
    polygonSignedArea([[0, 0], [0, 1], [1, 0]]), -0.5);
  check('closed ring tolerated', polygonArea([...L_SHAPE, [0, 0]]), 12);
  check('degenerate (2 points)', polygonArea([[0, 0], [4, 0]]), 0);
  check('bounds L', polygonBounds(L_SHAPE),
    { minX: 0, minZ: 0, maxX: 4, maxZ: 4 });
  check('a malformed point poisons the whole outline',
    sanitizePolygon([[0, 0], [1, Number.NaN], [2, 2]]), null);

  /**
   * ------------------------------------------------------------------------
   * (2) CONTAINMENT — smoke_world_polygon.py, "containment (notch is outside)"
   * ------------------------------------------------------------------------
   */
  console.log('containment in the LOCAL frame (the notch is outside)');
  check('(1,1) wide arm', pointInPolygon(1, 1, L_SHAPE), true);
  check('(3,1) right arm', pointInPolygon(3, 1, L_SHAPE), true);
  check('(3,3) notch', pointInPolygon(3, 3, L_SHAPE), false);
  check('(5,5) far outside', pointInPolygon(5, 5, L_SHAPE), false);
  check('a line contains nothing', pointInPolygon(0, 0, [[0, 0], [1, 1]]), false);

  /**
   * ------------------------------------------------------------------------
   * (3) DISTANCE — smoke_world_polygon.py, "distance (hand: 1 / 1 / 5 / 0)"
   * ------------------------------------------------------------------------
   */
  console.log('distance to the rim (hand: 1 / 1 / 5 / 0)');
  check('(5,1) east of the x=4 edge', polygonDistance(5, 1, L_SHAPE), 1);
  check('(3,3) in the notch, 1 m from both notch edges',
    polygonDistance(3, 3, L_SHAPE), 1);
  check('(−3,−4) past the (0,0) corner, hypot(3,4)',
    polygonDistance(-3, -4, L_SHAPE), 5);
  check('(1,1) inside = 0', polygonDistance(1, 1, L_SHAPE), 0);
  check('degenerate = Infinity', polygonDistance(0, 0, [[0, 0]]), Infinity);

  /**
   * ------------------------------------------------------------------------
   * (4) THE PIN TRANSFORM — the SERVER's own world-space cases
   * ------------------------------------------------------------------------
   * `smoke_world_polygon.py`, "world-space wrappers": the L-shape pinned at
   * (100, 50) with yaw 90. At that yaw local (lx, lz) lands at world
   * (100 + lz, 50 − lx), so:
   *
   *   world (101, 47) = local (3, 1) -> INSIDE (the right arm)
   *   world (103, 47) = local (3, 3) -> OUTSIDE (the notch)
   *   world (100, 44) = local (6, 0) -> distance 2
   *
   * Those are the server's three lines verbatim; the client reaches them by
   * turning the point with the same inverse and asking the same primitives.
   */
  console.log('the pin transform (pin (100,50), yaw 90 — § A1.1)');
  const PIN = { x: 100, z: 50, yaw: 90 };
  const at = (x, z) => worldToLocal(x, z, PIN.x, PIN.z, PIN.yaw);
  check('world (101,47) is local (3,1)', at(101, 47), { x: 3, z: 1 }, 1e-9);
  check('world (103,47) is local (3,3)', at(103, 47), { x: 3, z: 3 }, 1e-9);
  check('world (100,44) is local (6,0)', at(100, 44), { x: 6, z: 0 }, 1e-9);
  check('contains: world (101,47)',
    pointInPolygon(at(101, 47).x, at(101, 47).z, L_SHAPE), true);
  check('contains: world (103,47) is the NOTCH',
    pointInPolygon(at(103, 47).x, at(103, 47).z, L_SHAPE), false);
  check('distance: world (100,44) -> 2',
    polygonDistance(at(100, 44).x, at(100, 44).z, L_SHAPE), 2, 1e-9);

  /**
   * ------------------------------------------------------------------------
   * (5) SMALLEST AREA WINS — the hut in the village (v6 Nr. 6, E1.2)
   * ------------------------------------------------------------------------
   * `smoke_world_polygon.py`, "location_at_point": a village square of edge
   * 20 (its four synthesized corners, 400 m²) with the L-shaped hut (12 m²)
   * pinned at the same point. The rule is `main.tileAt`, and this is its
   * arithmetic half — the lookup itself needs tiles and `three`.
   *
   *   local (1, 1) -> in BOTH -> the hut wins (12 < 400)
   *   local (3, 3) -> the hut's NOTCH, still in the village -> the village
   *   local (50, 50) -> neither
   */
  console.log('smallest AREA wins (hut in the village)');
  const VILLAGE = [[-10, -10], [10, -10], [10, 10], [-10, 10]];
  check('the village square is 400 m²', polygonArea(VILLAGE), 400);
  check('the hut is 12 m²', polygonArea(L_SHAPE), 12);
  /** The rule of `main.tileAt`, on plain outlines: every one that contains the
   *  point, smallest area first. */
  const pick = (x, z, places) => {
    let best = null;
    for (const p of places) {
      if (!pointInPolygon(x, z, p.pts)) continue;
      const area = polygonArea(p.pts);
      if (!best || area < best.area) best = { id: p.id, area };
    }
    return best ? best.id : null;
  };
  const PLACES = [{ id: 'village', pts: VILLAGE }, { id: 'hut', pts: L_SHAPE }];
  check('inside both -> hut (12 < 400)', pick(1, 1, PLACES), 'hut');
  check('...and the order of the candidates does not decide it',
    pick(1, 1, [...PLACES].reverse()), 'hut');
  check('in the hut\'s notch -> village', pick(3, 3, PLACES), 'village');
  check('outside both -> none', pick(50, 50, PLACES), null);
  // The RED COUNTER-PROBE of the rule that was replaced: by BOUNDING-BOX WIDTH
  // the hut (4) and a 4 m square in the notch would tie, and by the old
  // smallest-WIDTH rule a wide-but-thin place could beat a small compact one.
  // Area orders them the way the server does — and for two squares it orders
  // them identically to width, because width² is monotone in width.
  check('two squares still order like their widths',
    polygonArea([[-2, -2], [2, -2], [2, 2], [-2, 2]]) < polygonArea(VILLAGE),
    true);

  /**
   * ------------------------------------------------------------------------
   * (6) THE RIM POINT — what a FREE boundary offers (`entryOfferNear`)
   * ------------------------------------------------------------------------
   * The nearest point on the outline plus the INWARD normal of the edge it
   * sits on. On a clockwise outline the interior is to the LEFT of an edge
   * a→b, i.e. `(−dz, dx)` normalised:
   *
   *   local (5, 1) -> on the edge (4,0)→(4,2), direction (0, 2);
   *                   inward (−2, 0)/2 = (−1, 0), and −x IS the interior.
   *   local (1, −2) -> on the edge (0,0)→(4,0), direction (4, 0);
   *                    inward (0, 4)/4 = (0, 1), and +z IS the interior.
   */
  console.log('the rim point and its inward normal');
  check('east of the right arm', nearestRimPoint(5, 1, L_SHAPE),
    { x: 4, z: 1, inward: { x: -1, z: 0 }, dist: 1 });
  check('north of the wide arm', nearestRimPoint(1, -2, L_SHAPE),
    { x: 1, z: 0, inward: { x: 0, z: 1 }, dist: 2 });
  check('a degenerate outline has no rim',
    nearestRimPoint(0, 0, [[0, 0], [1, 1]]), null);

  console.log(`\n${passed} passed, ${failed} failed`);
  if (failed) process.exit(1);
}

main().catch((e) => {
  console.error('smoke_polygon_containment:', e.message);
  process.exit(1);
});
