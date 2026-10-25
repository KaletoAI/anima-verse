#!/usr/bin/env node
/**
 * Canonical hand oracle for shared/test-vectors/scene_primitives.json.
 * Run from the repository root: node client3d/scripts/smoke_scene_primitives.mjs.
 *
 * [1] wallMeshMeasurements is the ordered list of the 31 checks in smoke_wall_uv.
 * Its input is [length, height, thickness, tileM]; the sill is 1.2 by 0.9.
 * The repeated face numbers and six unit UV spans are derived below. The box
 * is x 0..10.2624, y 0..2.65, z -0.035..0.035: centre x=10.2624/2=5.1312,
 * centre z=0, base=0, height=2.65, length=10.2624, thickness=0.07.
 * Old reveal squeeze = 5.1312/0.035 = 146.6057142857, rounded to 146.6057;
 * old sill squeeze = 0.45/0.035 = 12.8571428571, rounded to 12.8571.
 * [2] extraMeshMeasurements is the ordered list of the 12 smoke_extra_box checks.
 * 38.2997*pi/180 = 0.6684558675020722 radians; its other components are zero.
 * Centres, corner probes, and UV arithmetic are derived in the copied header.
 * [3] plateMeshMeasurements is the ordered list of all 34 smoke_plate_hole checks.
 * Two disjoint rectangular holes have n=4+4+4=12 vertices, h=2; two bridges
 * duplicate four vertices, hence 12+4-2=14 triangles. Every rectangular ring
 * has four sides, two triangles per side: three rings give 3*4*2=24 sides.
 * Zero target residuals follow from top=3.08, bottom=3.08-0.1=2.98; the flat
 * plate has top=bottom=0 and exactly one top_y target. The checks below derive
 * all area, coverage, orientation and bounds values, including repeated cases.
 * [4] diagonal wall from (1,2) to (4,6): delta=(3,4), hypot=5;
 * midpoint=(2.5,4), y=7+3/2=8.5; yaw=-atan2(4,3)=-0.9272952180016122.
 * Axis wall delta=(10,0): length=10, yaw=0, midpoint=(5,0), y=-1+2/2=0.
 * [5] face order px,nx,py,ny,pz,nz: duplicate (depth,height), (width,depth),
 * (width,height), each divided by tileM; no texture means six (1,1) spans.
 * [6] three intrinsic XYZ means Rx*Ry*Rz. For 90 degrees on all axes,
 * (x,y,z)->(-y,x,z)->(z,x,y)->(z,-y,x). Thus (1,2,3)+(10,20,30)
 * becomes (13,18,31). Ry maps (-y,x,z) to (z,x,y),
 * then Rx maps (z,x,y) to (z,-y,x): (1,2,3) -> (3,-2,1).
 * Therefore translated probes are (13,18,31) and (7,22,29).
 * An unrotated box at (1,2,3), size (2,4,6) has min (0,0,0), max (2,4,6);
 * corner order is x low/high, then y low/high, then z low/high.
 * [7] placeholder size=(w,h,d), offset=(0,h/2,0); min=(-w/2,0,-d/2),
 * max=(w/2,h,d/2). (2,4,6) gives offset (0,2,0), min(-1,0,-3), max(1,4,3).
 * Clamping every dimension below .01 gives size(.01,.01,.01), offset y=.005,
 * min(-.005,0,-.005), max(.005,.01,.005).
 * [8] solid shape preserves x,z; flat shape negates each z, for outline AND
 * holes. Rotation is respectively +pi/2=1.5707963267948966 or its negative.
 * A ring with fewer than three points encloses no area and is omitted.
 */

/**
 * Smoke: a wall texture must tile in WORLD METRES on every face of the box —
 * the broad face AND the narrow ones a door or window leaves behind.
 *
 * Usage (the package is TypeScript, so it is bundled first):
 *     node_modules/.bin/esbuild client3d/scripts/smoke_wall_uv.mjs --bundle \
 *         --platform=node --format=esm --outfile=/tmp/wuv.mjs && node /tmp/wuv.mjs
 *
 * Runs headless against the SHARED buildWall — the one routine both renderers
 * use — with the real three from node_modules, so the box's uv layout is the
 * one that actually ships, not a stub of it.
 *
 * THE DEFECT IT PINS DOWN (user report: "windows and doors of locations are
 * warped in the client"). Both renderers used to compute ONE repeat from the
 * wall FACE and put it on the material:
 *
 *     tex.repeat.set(len / tileM, wall.height / tileM)
 *
 * `BoxGeometry` normalises the uvs of every face to 0..1, so that one repeat
 * hits all six. Five of them are not the wall face:
 *
 *   ±x  the end faces  — a door jamb / window reveal, only `thickness` wide
 *   ±y  top and bottom — a sill's top, a lintel's underside, `thickness` deep
 *   ±z  the wall faces — the only ones the old number was ever right for
 *
 * With a typical `thickness` of 0.07 m the error is not subtle: see the red
 * counter-check in section 3, which recomputes the old numbers.
 *
 * EXPECTED, worked out by hand. Metres per tile must be the same everywhere,
 * so a face's uv span is (its own extent in metres) / tileM.
 *
 *   A. Wall segment 10.2624 m long, 2.65 m high, 0.07 m thick, tileM 2:
 *        wall face  (±z): u = 10.2624/2 = 5.1312   v = 2.65/2 = 1.325
 *        reveal     (±x): u =    0.07/2 = 0.035    v = 2.65/2 = 1.325
 *        top/bottom (±y): u = 10.2624/2 = 5.1312   v =  0.07/2 = 0.035
 *
 *      The reveal's u is 0.035 and NOT 5.1312 — that single number is the
 *      whole bug: the old code tiled 146.6 times too often across 7 cm.
 *
 *   B. Sill under a window, 1.2 m long, 0.9 m high, 0.07 m thick, tileM 2:
 *        top face   (±y): u = 1.2/2 = 0.6          v = 0.07/2 = 0.035
 *      The old v was 0.9/2 = 0.45, i.e. 12.86 times too dense on the one face
 *      a person standing at the window actually looks down on.
 *
 * The face order is NOT hard-coded here on purpose: each group of 4 vertices
 * is identified by its NORMAL and then measured against the extent that normal
 * implies. A three release that reorders `buildPlane` would therefore be
 * caught by this check instead of silently passing it.
 */
/**
 * Smoke check for `buildExtra` (`packages/scene-render/src/primitives.ts`) —
 * the ONE box routine both renderers hand a scene extra to, since v13 with a
 * `rotation` (the stair stringer) and a `tileM` (a textured extra). Numbers,
 * no screenshots (§ B5a).
 *
 * Usage:  node packages/scene-render/scripts/smoke_extra_box.mjs
 *         (self-bundles through esbuild like the client3d smokes)
 *
 * THE SAME HAND-DERIVED NUMBERS AS THE SERVER SMOKE (scripts/
 * smoke_scene_recipe.py [5s]), so a drift between the two sides fails here:
 *
 *   [1] rotation — the contract's own stringer (EG → OG, at (2, −2), dir 90,
 *       storey 3.00): centre [3.999582, 1.437218, −2.575], size
 *       [4.969547, 0.16, 0.05], rotation [0, 0, 38.2997]. The server put the
 *       board's TOP EDGE on the line from (0, −0.04) to (3.90, 3.04) in
 *       (along, y), i.e. from x = 2 to x = 5.9 in the scene — so the box's
 *       local corner (−L/2, +d/2, 0) must land on (2.00, −0.04) and
 *       (+L/2, +d/2, 0) on (5.90, 3.04) once three has applied the Euler in
 *       radians: 38.2997° = 0.668460 rad, and
 *         x' = x·cos θ − y·sin θ = −2.4847736·0.7847797 − 0.08·0.6197748
 *            = −1.9500000 − 0.0495820 = −1.9995820  → +3.9995820 = 2.0000
 *         y' = x·sin θ + y·cos θ = −2.4847736·0.6197748 + 0.08·0.7847797
 *            = −1.5400000 + 0.0627824 = −1.4772176  → +1.4372176 = −0.0400
 *       A flight along +z (dir 0) pitches about x by −38.2997°: the local
 *       corner (0, +d/2, −L/2) then lands on (2, −0.04, −2) — the foot.
 *   [2] uvs — a tread, size [0.26, 0.04, 1.10], tileM 0.5: every face is
 *       scaled by ITS OWN extent over the tile (the wall routine), so the
 *       largest uv on the +x face is (1.10/0.5, 0.04/0.5) = (2.2, 0.08), on
 *       the +y face (0.26/0.5, 1.10/0.5) = (0.52, 2.2) and on the +z face
 *       (0.52, 0.08). tileM 0 leaves every face at 0..1.
 *   [3] no rotation → the mesh is axis aligned (rotation 0, 0, 0).
 */

/**
 * Smoke: a floor plate with a HOLE in it — the opening a staircase cuts into
 * the floor it arrives on (`plates[].holes`, contract addendum "Treppen v2").
 *
 * Usage:  node client3d/scripts/smoke_plate_hole.mjs
 *
 * (Node 22 strips the types of the imported `.ts` itself and resolves `three`
 * out of `client3d/node_modules`. On an older runtime, bundle it first:
 *     client3d/node_modules/.bin/esbuild client3d/scripts/smoke_plate_hole.mjs \
 *         --bundle --platform=node --format=esm --outfile=/tmp/ph.mjs \
 *         && node /tmp/ph.mjs )
 *
 * Runs headless against the SHARED `buildPlate` — the one routine both
 * renderers build a floor with — using the real three from node_modules, so
 * what is measured is the geometry that actually ships.
 *
 * WHY IT EXISTS. Before v2 a `ScenePlate` was a single ring, and the floor of
 * the storey a flight arrives on was closed: the stairs ended under a lid.
 * The server now states the opening, and both renderers have to take it out of
 * the shape. Two things can go wrong and neither shows up in a bounding box:
 * the hole is dropped (the lid is back), or it is placed with the WRONG SIGN
 * on its second coordinate — `buildPlate` mirrors z for the flat plate variant
 * (`sy = −pz`) and must mirror the hole with it, or the opening lands in the
 * other half of the room.
 *
 * ============================================================================
 * THE FIXTURE, and every expected number derived from it BY HAND
 * ============================================================================
 * Outline (local metres, x/z, straddling z = 0 on purpose — a sign error is
 * invisible on a plate that lies entirely on one side of the pin):
 *
 *     [[0, −3], [8, −3], [8, 3], [0, 3]]        8 × 6 m  =  48 m²
 *
 * Hole, deliberately NOT symmetric about z = 0:
 *
 *     [[2, 0.5], [5, 0.5], [5, 2.5], [2, 2.5]]  3 × 2 m  =   6 m²
 *
 *   A. Top-face area with the hole:      48 − 6      = 42 m²
 *      Top-face area without it:                       48 m²
 *   B. Triangle count of the top face, for ONE hole. Counting n over EVERY
 *      ring — the outline plus the hole, because each bridge splits one
 *      vertex of each into two — a polygon with n vertices and h holes comes
 *      out at n + 2h − 2:
 *        no hole:  n = 4,     h = 0  ->  4 + 0 − 2 =  2 triangles
 *        one hole: n = 4 + 4, h = 1  ->  8 + 2 − 2 =  8 triangles
 *      The law is stated here for the one-hole case only, which is what a
 *      staircase produces per plate. Section 5 derives the two-hole count
 *      by adding the four bridge duplicates before triangulation.
 *   C. Coverage in WORLD xz. The hole's centre is (3.5, 1.5); its MIRROR
 *      about z = 0 is (3.5, −1.5), which lies inside the outline as well —
 *      that pair is the sign probe:
 *        (3.5,  1.5)  covered by NO top-face triangle   (the opening)
 *        (3.5, −1.5)  covered by exactly ONE            (the red probe)
 *        (1.0,  1.5) / (6.5, 1.5) / (3.5, 2.9) / (3.5, 0.1)  covered
 *          (west, east, north and south of the opening, all still floor)
 *   D. The bounding box is the OUTLINE's, hole or no hole (`plateTargets`
 *      stays as it is): x 0…8, z −3…3, top face on `top_y`, and for a body
 *      the bottom face one `thickness` below it.
 *        solid: top_y 3.08, thickness 0.10  ->  y 2.98 … 3.08
 *        flat:  top_y 0.00, thickness 0     ->  y 0.00 … 0.00
 *   E. The extrusion CAPS THE OPENING. Side triangles (the ones spanning both
 *      y levels) are 2 per ring edge: 4 edges outer = 8 without a hole, plus
 *      4 edges of the hole = 16 with one.
 *   F. AND THOSE WALLS FACE THE RIGHT WAY. A surface normal points away from
 *      the material, and the material lies outside a hole, so the 8 outer
 *      walls must face away from the plate's middle and the 8 hole walls
 *      towards the opening's. This is where three's winding rule is load-
 *      bearing: `ExtrudeGeometry` re-winds the holes only inside its
 *      `if (reverse)` branch, i.e. only when the outer contour is NOT
 *      clockwise by `ShapeUtils.isClockWise`. Every stored outline has a
 *      POSITIVE shoelace (`world_geometry`: positive = clockwise in map view),
 *      which three reads as "not clockwise" — the branch runs and normalises
 *      the hole whatever its own winding is. Measured counter-case, NOT pinned
 *      below because the server never composes it: a negative-shoelace outline
 *      skips the branch, and a hole wound like it then answers 0/8.
 *
 * Both plate kinds are measured with the same numbers, because the two
 * branches of `buildPlate` differ only in how they get there:
 *   solid  shape (x, z),  extruded downward, rotated +90° about x
 *   flat   shape (x, −z), a bare ShapeGeometry, rotated −90° about x
 * Both must put the point (px, pz) of the payload at world (px, ·, pz).
 */
import { build } from 'esbuild';
import { mkdtemp, writeFile, rm } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { loadVectors, runVectors } from '../../shared/test-vectors/vectors.mjs';

const dir = await mkdtemp(join(tmpdir(), 'scene-primitives-'));
try {
  const compile = async (entry, name) => {
    const result = await build({ entryPoints: [entry], bundle: true,
      platform: 'node', format: 'esm', write: false });
    const file = join(dir, name + '.mjs');
    await writeFile(file, result.outputFiles[0].text);
    return file;
  };
  const math = await import(await compile('packages/scene-render/src/primitiveMath.ts', 'math'));
  const measurements = {}
  try {
    for (const [name, entry] of Object.entries({ wall: 'client3d/scripts/smoke_wall_uv.mjs',
      extra: 'packages/scene-render/scripts/smoke_extra_box.mjs', plate: 'client3d/scripts/smoke_plate_hole.mjs' })) {
      globalThis.__scenePrimitiveMeasure = (values) => { measurements[name] = values }
      await import(name === 'plate' ? new URL('./smoke_plate_hole.mjs', import.meta.url).href : await compile(entry, name))
      if (!measurements[name]) throw new Error('Smoke returned no measurements: ' + entry)
    }
  } finally { delete globalThis.__scenePrimitiveMeasure }
  const { passed, failed } = runVectors(loadVectors('scene_primitives'), {
    ...math,
    wallMeshMeasurements: () => measurements.wall,
    extraMeshMeasurements: () => measurements.extra,
    plateMeshMeasurements: () => measurements.plate,
  });
  console.log(`\n${passed} ok, ${failed} failed`);
  process.exitCode = failed ? 1 : 0;
} finally { await rm(dir, { recursive: true, force: true }); }
