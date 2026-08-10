#!/usr/bin/env node
/**
 * Smoke check for the pure polygon maths behind the terrain ground
 * (plan-freie-weltkarte-e4-3d-client.md, task 2) —
 * `packages/scene-render/src/groundAreas.ts`.
 *
 * Usage:  node client3d/scripts/smoke_ground_math.mjs
 *
 * Same discipline as `client3d/scripts/smoke_walk_math.mjs` and
 * `scripts/smoke_scene_recipe.py`: every expected number below is derived BY
 * HAND from the geometry, written out in this header, and NEVER recorded from
 * the current output. A check that only pins today's result proves nothing.
 *
 * `groundAreas.ts` takes `three` as a PARAMETER (package rule) and imports it
 * only as a type, so the transpiled module has no runtime import at all and
 * can be loaded here directly — the same esbuild transpile the walk smoke
 * uses. `signedArea`, `polygonArea`, `cleanRing` and `shapePoints` are pure
 * arithmetic on number pairs; `buildAreaGeometry` gets a four-member stand-in
 * for the THREE namespace at the end of the file, because what is checked
 * there is the shape of its RETURN VALUE, not Three's triangulator.
 *
 * --- The coordinate convention ---------------------------------------------
 * A terrain polygon is a list of WORLD points `[x, z]` in metres (the payload
 * of `GET /play/terrain`). The ground lies in the XZ plane at y = 0 — the
 * `ground_y` discipline of the plan: no renderer bakes a height into the
 * geometry, so every y below is exactly 0.
 *
 * --- signedArea (shoelace) --------------------------------------------------
 *   A = 1/2 * SUM_i ( x_i * z_{i+1} - x_{i+1} * z_i ),  i wrapping
 * Sign carries the winding, `polygonArea` is |A| and therefore winding-blind.
 *
 * (T) TRIANGLE  (0,0) (10,0) (0,6)
 *   terms: 0*0 - 10*0 =  0
 *          10*6 - 0*0 = 60
 *          0*0 - 0*6  =  0
 *   A = 60/2 = 30      -> area 30 m2   (base 10 * height 6 / 2 = 30, checks out)
 *
 * (T') the SAME triangle wound the other way: (0,0) (0,6) (10,0)
 *   terms: 0*6 - 0*0   =   0
 *          0*0 - 10*6  = -60
 *          10*0 - 0*0  =   0
 *   A = -30            -> area 30 m2 as well
 *
 * (S) UNIT SQUARE (0,0) (0,1) (1,1) (1,0)
 *   terms: 0*1-0*0 = 0 ; 0*1-1*1 = -1 ; 1*0-1*1 = -1 ; 1*0-0*0 = 0
 *   A = -2/2 = -1      -> area 1 m2
 *
 * (C) CONCAVE "L", 6 corners, going (0,0) (6,0) (6,2) (2,2) (2,5) (0,5)
 *   terms: 0*0 - 6*0  =   0
 *          6*2 - 6*0  =  12
 *          6*2 - 2*2  =   8
 *          2*5 - 2*2  =   6
 *          2*5 - 0*5  =  10
 *          0*0 - 0*5  =   0
 *   sum = 36 -> A = 18 -> area 18 m2
 *   Cross-check by decomposition: the L is a 6x2 foot (12) plus a 2x3 leg
 *   (2 wide, from z=2 to z=5 -> 6) = 18. Two independent derivations agree.
 *
 * (C') the same L REVERSED (0,5) (2,5) (2,2) (6,2) (6,0) (0,0)
 *   Reversal negates the shoelace exactly -> A = -18, area 18 m2.
 *
 * (D) DEGENERATE: three collinear points (0,0) (5,0) (10,0) -> A = 0, area 0.
 *   terms: 0*0-5*0 = 0 ; 5*0-10*0 = 0 ; 10*0-0*0 = 0. Nothing to triangulate.
 *
 * (P) The demo-scale POND, a 12 x 8 rectangle whose corner is bevelled by a
 *   2 x 2 triangle: (0,0) (12,0) (12,8) (2,8) (0,6)
 *   terms:  0*0  - 12*0 =   0
 *          12*8  - 12*0 =  96
 *          12*8  -  2*8 =  80
 *           2*6  -  0*8 =  12
 *           0*0  -  0*6 =   0
 *   sum = 188 -> A = 94 -> area 94 m2
 *   Cross-check: full rectangle 12*8 = 96, minus the cut corner triangle with
 *   legs 2 and 2 -> 96 - 2 = 94. Agrees.
 *
 * --- cleanRing --------------------------------------------------------------
 * The ring the geometry is built from: non-finite points dropped, consecutive
 * duplicates collapsed, and a closing point equal to the first removed (a
 * painted area may or may not repeat its first corner — `THREE.Shape` closes
 * itself, and the doubled point would make earcut see a zero-length edge).
 * Order is otherwise PRESERVED; the winding is not touched here.
 *   [(0,0), (10,0), (0,6), (0,0)]        -> 3 points, closing dup gone
 *   [(0,0), (0,0), (10,0), (0,6)]        -> 3 points, consecutive dup gone
 *   [(0,0), (10,0), (NaN,1), (0,6)]      -> 3 points, junk gone
 *   [(0,0), (10,0)]                      -> 2 points: no ring, [] is the answer
 *
 * --- shapePoints ------------------------------------------------------------
 * The mapping into `THREE.Shape` space. `ShapeGeometry` builds in XY with the
 * face normal on +z; the ground needs it in XZ with the normal UP, so the
 * geometry is rotated by -90 deg around X:
 *   rotX(-90): (x, y, z) -> (x,  y*cos(-90) - z*sin(-90),  y*sin(-90) + z*cos(-90))
 *                        = (x,  z,  -y)
 *   a shape point (px, py, 0)  ->  (px, 0, -py)
 *   the normal   (0, 0, 1)     ->  (0, 1, 0)        <- up, which is the point
 * So a world point (x, z) must be fed as (x, -z), and the world z of a shape
 * point is -py. `shapePoints` does that mapping AND normalises the winding so
 * the shape-space ring is counter-clockwise (positive shoelace in shape
 * space); the shape-space area of a ring is exactly -A_world (the z flip
 * negates it), so a world ring with A > 0 gets reversed and one with A < 0
 * passes through unchanged.
 *
 * The reversal keeps the FIRST corner where it is and turns the rest around
 * ([p0, p1, p2] -> [p0, p2, p1]). Plain list reversal would describe the very
 * same ring, only entered at another corner; keeping the entry point makes the
 * two windings of ONE polygon collapse onto the IDENTICAL point list, which is
 * the "winding both ways" promise stated as an equality the checks can pin.
 *   (T) A = +30 > 0 -> reversed about its first corner:
 *       world [(0,0), (0,6), (10,0)] -> z negated -> [(0,0), (0,-6), (10,0)]
 *       shoelace of that: 0*(-6)-0*0 = 0 ; 0*0-10*(-6) = 60 ; 10*0-0*0 = 0
 *                         -> +30, counter-clockwise. Good.
 *   (T') A = -30 < 0 -> kept, z negated: [(0,0), (0,-6), (10,0)] — the SAME
 *       list as (T).
 *   (S) A = -1 < 0 -> kept in order, z negated: [(0,0), (0,-1), (1,-1), (1,0)]
 *
 * A ring that encloses nothing (|A| below 1e-9: collinear points, a hairline)
 * yields an EMPTY list — there is no face to build, and `buildAreaGeometry`
 * answers `null` for it instead of putting a zero-area mesh into the scene.
 */
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '../..');
const SRC = join(ROOT, 'packages/scene-render/src/groundAreas.ts');

/**
 * The module is TypeScript and deliberately free of any RUNTIME import (three
 * arrives as a parameter, and its type comes in via `import type`, which
 * esbuild erases), so a plain transpile is enough — no bundler, exactly as in
 * `client3d/scripts/smoke_walk_math.mjs`. If someone ever adds a real import to it,
 * this loader fails loudly, which is the intended alarm.
 */
async function loadGroundAreas() {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(tmpdir(), 'groundmath-'));
  try {
    const source = await readFile(SRC, 'utf8');
    const out = esbuild.transformSync(source, { loader: 'ts', format: 'esm' });
    const file = join(dir, 'groundAreas.mjs');
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

// The polygons of the header, once, so every check reads against the same
// shape the derivation above is written for.
const TRIANGLE = [[0, 0], [10, 0], [0, 6]];
const TRIANGLE_CW = [[0, 0], [0, 6], [10, 0]];
const SQUARE = [[0, 0], [0, 1], [1, 1], [1, 0]];
const L_SHAPE = [[0, 0], [6, 0], [6, 2], [2, 2], [2, 5], [0, 5]];
const L_SHAPE_REV = [[0, 5], [2, 5], [2, 2], [6, 2], [6, 0], [0, 0]];
const COLLINEAR = [[0, 0], [5, 0], [10, 0]];
const POND = [[0, 0], [12, 0], [12, 8], [2, 8], [0, 6]];

async function main() {
  const { signedArea, polygonArea, cleanRing, shapePoints, buildAreaGeometry }
    = await loadGroundAreas();

  console.log('signedArea — the shoelace, sign carries the winding');
  check('(T) triangle, counter-clockwise in world XZ', signedArea(TRIANGLE), 30);
  check('(T\') the same triangle the other way round', signedArea(TRIANGLE_CW), -30);
  check('(S) unit square', signedArea(SQUARE), -1);
  check('(C) concave L', signedArea(L_SHAPE), 18);
  check('(C\') the L reversed', signedArea(L_SHAPE_REV), -18);
  check('(D) three collinear points enclose nothing', signedArea(COLLINEAR), 0);
  check('(P) bevelled pond', signedArea(POND), 94);
  check('fewer than three points is no ring', signedArea([[0, 0], [1, 1]]), 0);

  console.log('\npolygonArea — |shoelace|, so both windings give the same m2');
  check('(T) triangle', polygonArea(TRIANGLE), 30);
  check('(T\') reversed triangle, SAME area', polygonArea(TRIANGLE_CW), 30);
  check('(S) unit square', polygonArea(SQUARE), 1);
  check('(C) concave L', polygonArea(L_SHAPE), 18);
  check('(C\') reversed L, SAME area', polygonArea(L_SHAPE_REV), 18);
  check('(D) degenerate strip', polygonArea(COLLINEAR), 0);
  check('(P) bevelled pond', polygonArea(POND), 94);
  // A closed ring must not count its repeated corner twice — the extra edge
  // is zero-length and contributes nothing, which this pins.
  check('a repeated first corner changes nothing',
    polygonArea([...TRIANGLE, [0, 0]]), 30);

  console.log('\ncleanRing — junk out, order kept, winding untouched');
  check('the closing duplicate goes',
    cleanRing([[0, 0], [10, 0], [0, 6], [0, 0]]), TRIANGLE);
  check('consecutive duplicates collapse',
    cleanRing([[0, 0], [0, 0], [10, 0], [0, 6]]), TRIANGLE);
  check('non-finite points are dropped',
    cleanRing([[0, 0], [10, 0], [NaN, 1], [0, 6]]), TRIANGLE);
  check('and so is an infinite one',
    cleanRing([[0, 0], [10, 0], [0, 6], [Infinity, Infinity]]), TRIANGLE);
  check('a two-point ring is no ring at all',
    cleanRing([[0, 0], [10, 0]]), []);
  check('the concave L survives unchanged', cleanRing(L_SHAPE), L_SHAPE);
  check('a ring that collapses to two distinct points is dropped',
    cleanRing([[0, 0], [0, 0], [1, 1], [1, 1]]), []);

  console.log('\nshapePoints — into THREE.Shape space (x, -z), winding normalised');
  check('(T) the CCW-in-world triangle gets reversed',
    shapePoints(TRIANGLE), [[0, 0], [0, -6], [10, 0]]);
  check('(T\') the CW one lands on the very same ring',
    shapePoints(TRIANGLE_CW), [[0, 0], [0, -6], [10, 0]]);
  check('(S) the square keeps its order, z flips',
    shapePoints(SQUARE), [[0, 0], [0, -1], [1, -1], [1, 0]]);
  check('(D) a degenerate ring yields nothing', shapePoints(COLLINEAR), []);
  // The invariant the geometry depends on: shape-space shoelace positive
  // (counter-clockwise), so the -90 deg rotation puts the normal up.
  check('(C) the L comes out counter-clockwise in shape space',
    signedArea(shapePoints(L_SHAPE)) > 0, true);
  check('(C\') …and so does the reversed L',
    signedArea(shapePoints(L_SHAPE_REV)) > 0, true);
  check('(P) the pond, too', signedArea(shapePoints(POND)) > 0, true);
  // Round trip: the shape ring describes the same figure, so its area in
  // shape space must equal the world area.
  check('(P) shape ring keeps the pond area', polygonArea(shapePoints(POND)), 94);

  // --- buildAreaGeometry: the CLEANED ring comes back out --------------------
  //
  // The wrapper needs a THREE namespace, and the four members it touches are
  // small enough to stand in for here. That is the point: what is checked is
  // the CONTRACT of the return value, not Three's triangulator.
  //
  // `ring` exists because every caller that measures the area afterwards (the
  // scatter's bounding box, its point-in-polygon test, the LOD centre) must
  // measure the ring the MESH was built from. Reading the raw payload instead
  // let a single non-finite corner poison the bounding box with NaN — and NaN
  // fails silently: no scatter and a NaN distance, which both just look like
  // "this kind scatters nothing".
  const fakeThree = {
    Vector2: class { constructor(x, y) { this.x = x; this.y = y; } },
    Shape: class { constructor(points) { this.points = points; } },
    ShapeGeometry: class {
      constructor(shape) { this.shape = shape; this.rotatedX = null; }
      rotateX(a) { this.rotatedX = a; return this; }
      computeBoundingSphere() { this.sphered = true; return this; }
    },
  };

  console.log('\nbuildAreaGeometry — geometry, area and the ring it was built from');
  const junkPond = [[0, 0], [12, 0], [12, 8], [2, 8], [NaN, 3], [0, 6], [0, 0]];
  const builtPond = buildAreaGeometry(fakeThree, junkPond);
  check('the junk corner and the closing duplicate are gone from the ring',
    builtPond.ring, POND);
  check('and the area is the hand-derived 94 m2 of the cleaned ring',
    builtPond.areaM2, 94);
  check('the geometry was turned onto the XZ plane, normals up',
    builtPond.geometry.rotatedX, -Math.PI / 2);
  check('…and got its bounding sphere', builtPond.geometry.sphered, true);
  check('the shape ring has as many points as the cleaned world ring',
    builtPond.geometry.shape.points.length, POND.length);
  check('a reversed ring builds just the same area',
    buildAreaGeometry(fakeThree, L_SHAPE_REV).areaM2, 18);
  check('…and its ring keeps the order it was given',
    buildAreaGeometry(fakeThree, L_SHAPE_REV).ring, L_SHAPE_REV);
  check('a ring that encloses nothing builds nothing',
    buildAreaGeometry(fakeThree, COLLINEAR), null);
  check('and neither does a two-point one',
    buildAreaGeometry(fakeThree, [[0, 0], [1, 1]]), null);
  check('nor an empty polygon', buildAreaGeometry(fakeThree, []), null);
  check('nor a missing one', buildAreaGeometry(fakeThree, null), null);

  console.log(`\n${passed} ok, ${failed} failed`);
  process.exit(failed ? 1 : 0);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
