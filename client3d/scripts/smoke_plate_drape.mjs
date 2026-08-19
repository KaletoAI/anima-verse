#!/usr/bin/env node
/**
 * Smoke: the footprint PLATE lies on the ground under it
 * (`client3d/src/scene/tiles.ts` `plateGeometry`, contract v6 no. 4 + § A16).
 *
 * Usage:  node client3d/scripts/smoke_plate_drape.mjs
 *         (bundles the client's tile module; needs three + esbuild)
 *
 * Same discipline as `smoke_scene_recipe.py` and every other check here: every
 * expected number below is derived BY HAND from the geometry in this header
 * and never recorded from the current output. § B5a — numbers, never
 * screenshots.
 *
 * --- WHY THIS FILE EXISTS ---------------------------------------------------
 * Two defects reported on the v6 polygon plate (2026-08-19):
 *   A "the ground plate is HIGHER than the terrain"
 *   B "the footprint is partly covered by the underlying terrain's texture,
 *      and it changes with view and movement"
 * Both are one measurement: the signed distance between a plate vertex and the
 * world ground at that vertex's own world point. Positive = the plate rides
 * above the landscape (A), negative = the landscape stands THROUGH the plate
 * (B). This file measures it per vertex.
 *
 * --- THE TERRAIN ------------------------------------------------------------
 * A PLANE, deliberately: `h(x, z) = 0.05 · x` — a 5 % slope towards east, flat
 * along z. A plane is the one landscape whose drawn triangle surface IS the
 * sampler's answer whatever grid it is cut on, so every deviation measured
 * below belongs to the plate's own rule and not to two rasters disagreeing.
 *
 * --- THE FIXTURE ------------------------------------------------------------
 * A location pinned at world (200, 0), yaw 0, outline a 40 m square in local
 * metres: (−20,−20) (20,−20) (20,20) (−20,20), clockwise in map view.
 *
 *   tile floor  center.y = h(200, 0) = 0.05 · 200 = 10.0 m
 *   lift rule   plateLift(worldY, tileY) = max(0, worldY − tileY)
 *   liftAt(lx)  = max(0, h(200 + lx) − 10) = max(0, 0.05 · lx)
 *
 * The drape lattice (`DRAPE_STEP_M` 2, `DRAPE_MAX_SEGMENTS` 48):
 *   spanX = spanZ = 40 -> seg = min(48, ceil(40/2)) = 20 -> step = 40/20 = 2 m
 *   lattice lx, lz in {−20, −18, …, 18, 20}  ->  21 × 21 = 441 vertices
 * Every cell centre (−19, −17, … 19) lies strictly inside the square, so no
 * cell is dropped and every lattice point is emitted — rim points included.
 *
 * Flatness probe: the largest lift on the lattice INSIDE the polygon. The east
 * column lx = +20 sits on the outline and the half-open containment test
 * (`game/polygon.pointInPolygon`, strict `x < crossX`) puts it outside, so the
 * largest probed lift is at lx = +18: 0.05 · 18 = 0.9 m. 0.9 > 0.05
 * (`DRAPE_FLAT_EPS_M`) -> the DRAPED grid is built, not the flat outline.
 *
 * --- [1] THE GROUND PLATE, per vertex ---------------------------------------
 * world y of a vertex = center.y + PLATE_Y_M + lift
 *                     = 10 + 0.04 + max(0, 0.05 · lx)
 * ground under it     = h(200 + lx) = 10 + 0.05 · lx
 * difference d(lx)    = 0.04 + max(0, 0.05·lx) − 0.05·lx
 *
 *   lx = +20 -> 10 + 0.04 + 1.00 = 11.04 ;  ground 11.00 ; d = +0.04
 *   lx = +10 -> 10 + 0.04 + 0.50 = 10.54 ;  ground 10.50 ; d = +0.04
 *   lx =   0 -> 10 + 0.04 + 0.00 = 10.04 ;  ground 10.00 ; d = +0.04
 *   lx = −10 -> 10 + 0.04 + 0.00 = 10.04 ;  ground  9.50 ; d = +0.54
 *   lx = −20 -> 10 + 0.04 + 0.00 = 10.04 ;  ground  9.00 ; d = +1.04
 *
 * So: NOTHING pokes through (min d = +0.04 > 0), and uphill the plate is the
 * ground plus exactly the 4 cm it is lifted by. Downhill it stays the tile
 * floor and the landscape passes underneath — `game/ground.plateLift`'s
 * documented "the plate only ever rises", coupled to `standY`, by which the
 * figure walks at the same 10.04 m. That is the DELIBERATE part of finding A
 * and this file pins it as such: max d = 1.04 m on this fixture.
 *
 * --- [2] THE SOCLE, built FLAT — the regression -----------------------------
 * Until this file's fix the socle plate under a building was built with no
 * lift at all (`platePolygonGeometry(boundary, width, null)`): the flat branch
 * triangulates the outline itself, four corner vertices, all at the tile floor.
 *
 *   world y of every vertex = 10 + SOCLE_Y_M = 10.045, everywhere
 *   lx = +20 -> ground 11.00 -> d = 10.045 − 11.00 = −0.955  (B: buried)
 *   lx = −20 -> ground  9.00 -> d = 10.045 −  9.00 = +1.045  (A: floating)
 *
 * Harmless while the socle was the few metres of paving around a procedural
 * hut; since the shell was struck (586fdc99) the socle IS the drawn area of
 * the place, and v6 outlines are hundreds of metres across. The flat case is
 * reproduced here by asking for a plate BEFORE any world ground is taken over
 * (`setWorldGround`), which is exactly the `liftAt = null` the socle used to
 * pass — so section [2] is the red counter-proof, run first, on a fresh module.
 *
 * --- [3] SCALE: the same fixture at v6 size ---------------------------------
 * Outline 400 m square (−200 … 200), same pin, same slope.
 *   spanX = 400 -> segX = min(48, ceil(400/2) = 200) = 48 -> step = 400/48
 *                = 8.3333… m   (the 2 m promise is spent at 96 m of span)
 *   lattice lx in {−200, −191.666…, …, 200}, 49 × 49 = 2401 vertices
 *   liftAt(lx) = max(0, 0.05 · lx), so d(lx) = 0.04 + max(0,0.05lx) − 0.05lx
 *   lx = −200 -> d = 0.04 + 0 + 10.00 = 10.04 m of air under the west rim
 *   lx = +200 -> d = 0.04
 * FLAT (the old socle) at this size: d(+200) = 0.045 − 20.0 + 10.0 = −9.955 m
 * of terrain standing through the plate, d(−200) = +10.045 m of float.
 *
 * --- [4] THE FRAME: yaw 90° -------------------------------------------------
 * § A1.1: world = (at.x + lx·cos + lz·sin, at.z − lx·sin + lz·cos). At yaw 90°
 * (cos 0, sin 1) that is (at.x + lz, at.z − lx): the slope now runs along the
 * outline's LOCAL z, so liftAt(lx, lz) = max(0, 0.05 · lz) and the same five
 * numbers of [1] appear on the other axis. A plate that lifted around the
 * world axes instead of its own would fail here and nowhere else.
 *
 * --- [5] THE REBUILD PREDICATE: the pin is not the place ---------------------
 * A built plate is frozen against the ground it was draped on, and the relief
 * arrives as a 256 m window that follows the player (§ A16.3) — so the ground
 * under a footprint sharpens WITHOUT the pin's own reading moving.
 * `main.relevelTiles` asked the pin alone; the plate then kept a stale drape
 * while the landscape under it rose, which is the "changes with movement" half
 * of the report.
 *
 * The fixture is [1]'s, with a second terrain that adds a 0.5 m bump on the
 * world box |x − 215| < 4, |z| < 4 — deliberately AWAY from the pin:
 *
 *   pin (200, 0):  |200 − 215| = 15, not < 4  ->  h = 10.0 in BOTH terrains,
 *                  so the old pin-only predicate says "nothing to do".
 *   lattice: lx, lz in {−20, −18, …, 20}, world point (200 + lx, lz)
 *     bump in x: |200 + lx − 215| < 4  ->  11 < lx < 19  ->  lx in {12,14,16,18}
 *     bump in z: |lz| < 4              ->  lz in {−2, 0, 2}
 *   -> exactly 4 · 3 = 12 of the 441 samples move, each by exactly 0.50 m.
 *
 * So the lattice predicate must answer TRUE where the pin predicate answers
 * FALSE. Its epsilon is 1 mm: a bump of 0.0005 m must NOT trigger a rebuild
 * (0.0005 < 0.001), one of 0.0015 m must.
 *
 * --- [6] THE DEPTH BIAS -----------------------------------------------------
 * The painted areas pull themselves towards the camera by
 * `−min(index + 1, AREA_OFFSET_MAX)` depth units to stack coplanar ground
 * (`scene/ground.ts`), while the footprint plate carried NO bias — so its 4 cm
 * of air was competing against up to 32 depth units of the area under it.
 *
 * One depth unit at range z, for this camera (`engine.ts`: near 0.2, far 800)
 * and a 24-bit buffer:
 *   Δz = z² · (f − n) / (f · n · 2^24) = z² · 799.8 / (160 · 16777216)
 *      = z² · 2.9795e−7  metres
 * so the plate's 4 cm are worth 0.04 / 2.9795e−7 / z² = 134252 / z² units, and
 * the plate lost to an area of bias b beyond z = sqrt(134252 / b):
 *   b =  1 -> 366 m ;  b =  2 -> 259 m ;  b =  5 -> 164 m ;
 *   b = 10 -> 116 m ;  b = 32 ->  65 m
 * — "partly covered by the texture of the terrain under it, changes with view".
 *
 * The remedy is the file's own 2026-08-03 pattern with the sign mirrored (the
 * detail-mode backstop is pushed BACK so it never pokes through what is above
 * it; a footprint plate is pulled FORWARD so nothing below pokes through it),
 * at one rung above the ladder's ceiling:
 *   PLATE_POLYGON_OFFSET = −(AREA_OFFSET_MAX + 1) = −33
 * That relation is the check — the two constants live in two files that cannot
 * import each other (`scene/ground.ts` takes `setWorldGround` from
 * `scene/tiles.ts`), so this is where they are held together.
 */
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '../..');
const TILES_SRC = join(ROOT, 'client3d/src/scene/tiles.ts');
const GROUND_SRC = join(ROOT, 'client3d/src/scene/ground.ts');

/** A client module, bundled for node. `external: ['three']` leaves node's own
 *  three the only one in play (same trick as `smoke_occlusion.mjs`), and the
 *  bundle is written next to the sources so node resolves `three` upwards from
 *  it. A fresh call gives a FRESH module — section [2] needs one whose
 *  `worldGroundAt` has never been set. */
async function loadModule(src) {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(ROOT, 'client3d/scripts/.smoke-'));
  try {
    const built = await esbuild.build({
      entryPoints: [src], bundle: true, platform: 'node', format: 'esm',
      write: false, outfile: join(dir, 'mod.mjs'),
      external: ['three', 'three/*'],
    });
    const file = join(dir, 'mod.mjs');
    await writeFile(file, built.outputFiles[0].text, 'utf8');
    return await import(`file://${file}`);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}
const loadTiles = () => loadModule(TILES_SRC);

let failed = 0;
let passed = 0;
function check(label, actual, expected, eps = 1e-6) {
  const ok = Number.isFinite(actual) && Math.abs(actual - expected) <= eps;
  if (ok) { passed += 1; console.log(`  ok   ${label}: ${fmt(actual)}`); }
  else {
    failed += 1;
    console.log(`  FAIL ${label}: ${fmt(actual)} — expected ${fmt(expected)}`);
  }
}
function fmt(v) {
  return typeof v === 'number' ? (Number.isInteger(v) ? String(v) : v.toFixed(4)) : String(v);
}

/** The terrain of the whole file: a 5 % slope east, flat along z. */
const SLOPE = 0.05;
const terrainAt = (x) => SLOPE * x;

/** A square outline in local metres, clockwise in map view (x east, z south) —
 *  the winding the server stores and the shape a legacy square synthesizes. */
function square(half) {
  return [[-half, -half], [half, -half], [half, half], [-half, half]];
}

/**
 * Every vertex of a plate geometry as {lx, lz, worldY, groundY, d}.
 *
 * The plate frame (`tiles.ts`): the mesh is turned by −90° about X, so a
 * vertex (px, py, pz) sits at tile-local (px, pz, −py) — the outline point is
 * (px, −py) and the HEIGHT is pz. The tile group carries pin and yaw, so the
 * world point is the § A1.1 mapping of that outline point.
 */
function measure(geo, at, plateY) {
  const pos = geo.attributes.position;
  const cos = Math.cos(at.yaw);
  const sin = Math.sin(at.yaw);
  const out = [];
  for (let i = 0; i < pos.count; i++) {
    const px = pos.getX(i);
    const py = pos.getY(i);
    const pz = pos.getZ(i);
    const lx = px;
    const lz = -py;
    const wx = at.x + lx * cos + lz * sin;
    const wz = at.z - lx * sin + lz * cos;
    const worldY = at.y + plateY + pz;
    const groundY = terrainAt(wx, wz);
    out.push({ lx, lz, worldY, groundY, d: worldY - groundY });
  }
  return out;
}

/** The measured vertex nearest to a lattice point, so a check can name the
 *  point it derived by hand instead of a vertex index. */
function at(rows, lx, lz) {
  let best = null;
  let bestErr = Infinity;
  for (const r of rows) {
    const err = Math.abs(r.lx - lx) + Math.abs(r.lz - lz);
    if (err < bestErr) { bestErr = err; best = r; }
  }
  return bestErr <= 1e-6 ? best : null;
}

const PIN = { x: 200, y: 10, z: 0, yaw: 0 };

async function main() {
  // ---- [2] first: the FLAT plate, on a module that has no world ground -----
  console.log('\n[2] the socle built FLAT (liftAt = null) — the reported defect');
  {
    const tiles = await loadTiles();
    const geo = tiles.plateGeometry(square(20), 40, PIN);
    const rows = measure(geo, PIN, tiles.SOCLE_Y_M);
    check('vertices (the outline, triangulated)', rows.length, 4);
    const east = at(rows, 20, 20) ?? at(rows, 20, -20);
    const west = at(rows, -20, 20) ?? at(rows, -20, -20);
    check('east rim world y', east.worldY, 10.045);
    check('east rim ground', east.groundY, 11.0);
    check('east rim: terrain stands THROUGH the plate', east.d, -0.955);
    check('west rim world y', west.worldY, 10.045);
    check('west rim ground', west.groundY, 9.0);
    check('west rim: plate floats over the terrain', west.d, 1.045);
  }

  // ---- [1] the draped plate ------------------------------------------------
  console.log('\n[1] the ground plate, draped on the world ground');
  const tiles = await loadTiles();
  tiles.setWorldGround(terrainAt);
  check('PLATE_Y_M', tiles.PLATE_Y_M, 0.04);
  check('SOCLE_Y_M', tiles.SOCLE_Y_M, 0.045);
  {
    const geo = tiles.plateGeometry(square(20), 40, PIN);
    const rows = measure(geo, PIN, tiles.PLATE_Y_M);
    check('vertices (21 x 21 lattice, 2 m step)', rows.length, 441);
    check('lattice min lx', Math.min(...rows.map((r) => r.lx)), -20);
    check('lattice max lx', Math.max(...rows.map((r) => r.lx)), 20);
    for (const [lx, worldY, ground, d] of [
      [20, 11.04, 11.0, 0.04],
      [10, 10.54, 10.5, 0.04],
      [0, 10.04, 10.0, 0.04],
      [-10, 10.04, 9.5, 0.54],
      [-20, 10.04, 9.0, 1.04],
    ]) {
      const r = at(rows, lx, 0);
      check(`lx=${lx} world y`, r.worldY, worldY);
      check(`lx=${lx} ground`, r.groundY, ground);
      check(`lx=${lx} plate − ground`, r.d, d);
    }
    const ds = rows.map((r) => r.d);
    check('nothing pokes through (min)', Math.min(...ds), 0.04);
    check('deliberate float, downhill rim (max)', Math.max(...ds), 1.04);
  }

  // ---- [3] the same rule at v6 scale ---------------------------------------
  console.log('\n[3] a 400 m outline — the size v6 draws');
  {
    const geo = tiles.plateGeometry(square(200), 400, PIN);
    const rows = measure(geo, PIN, tiles.PLATE_Y_M);
    check('vertices (49 x 49 lattice, capped at 48 segments)', rows.length, 2401);
    check('lattice step', 400 / 48, 8.333333, 1e-6);
    const east = at(rows, 200, 0);
    const west = at(rows, -200, 0);
    check('east rim plate − ground', east.d, 0.04);
    check('west rim plate − ground', west.d, 10.04);
    check('nothing pokes through (min)', Math.min(...rows.map((r) => r.d)), 0.04);
  }

  // ---- [4] the frame: yaw 90° ---------------------------------------------
  console.log('\n[4] yaw 90° — the lift follows the OUTLINE, not the world axes');
  {
    const spun = { ...PIN, yaw: Math.PI / 2 };
    const geo = tiles.plateGeometry(square(20), 40, spun);
    const rows = measure(geo, spun, tiles.PLATE_Y_M);
    check('vertices', rows.length, 441);
    for (const [lz, worldY, ground, d] of [
      [20, 11.04, 11.0, 0.04],
      [0, 10.04, 10.0, 0.04],
      [-20, 10.04, 9.0, 1.04],
    ]) {
      const r = at(rows, 0, lz);
      check(`lz=${lz} world y`, r.worldY, worldY);
      check(`lz=${lz} ground`, r.groundY, ground);
      check(`lz=${lz} plate − ground`, r.d, d);
    }
    check('nothing pokes through (min)', Math.min(...rows.map((r) => r.d)), 0.04);
  }

  // ---- [5] the rebuild predicate ------------------------------------------
  console.log('\n[5] relevelTiles: the ground moved AWAY FROM THE PIN');
  {
    const bumped = (amount) => (x, z) => (
      terrainAt(x) + (Math.abs(x - 215) < 4 && Math.abs(z) < 4 ? amount : 0));
    const pin = { x: PIN.x, z: PIN.z, yaw: PIN.yaw };
    const before = tiles.plateGroundSamples(square(20), pin);
    check('lattice samples (21 x 21)', before.length, 441);

    tiles.setWorldGround(bumped(0.5));
    const after = tiles.plateGroundSamples(square(20), pin);
    // The PIN reading, which is all `relevelTiles` used to look at.
    check('pin height before', terrainAt(200), 10.0);
    check('pin height after (unchanged -> old predicate says no)',
          bumped(0.5)(200, 0), 10.0);

    let moved = 0;
    let worst = 0;
    for (let i = 0; i < before.length; i++) {
      const d = Math.abs(after[i] - before[i]);
      if (d >= 1e-3) moved += 1;
      if (d > worst) worst = d;
    }
    check('lattice samples that moved', moved, 12);
    check('largest move', worst, 0.5);
    check('predicate: rebuild', tiles.plateGroundMoved(before, after) ? 1 : 0, 1);
    check('predicate: unchanged ground', tiles.plateGroundMoved(before, before) ? 1 : 0, 0);

    // The 1 mm epsilon, from both sides.
    tiles.setWorldGround(bumped(0.0005));
    check('predicate: 0.5 mm is not a move',
          tiles.plateGroundMoved(before, tiles.plateGroundSamples(square(20), pin)) ? 1 : 0, 0);
    tiles.setWorldGround(bumped(0.0015));
    check('predicate: 1.5 mm is',
          tiles.plateGroundMoved(before, tiles.plateGroundSamples(square(20), pin)) ? 1 : 0, 1);

    // A redrawn outline gives a lattice of another size — that is a move too.
    check('predicate: outline redrawn (441 vs 2401)',
          tiles.plateGroundMoved(before, tiles.plateGroundSamples(square(200), pin)) ? 1 : 0, 1);
    // Nothing sampled yet (no field, no outline) has not moved.
    check('predicate: nothing sampled', tiles.plateGroundMoved(null, after) ? 1 : 0, 0);
    check('no outline -> no samples',
          tiles.plateGroundSamples(null, pin) === null ? 1 : 0, 1);
  }

  // ---- [6] the depth bias --------------------------------------------------
  console.log('\n[6] the plate stands one rung in front of the ground ladder');
  {
    const ground = await loadModule(GROUND_SRC);
    check('AREA_OFFSET_MAX (scene/ground.ts)', ground.AREA_OFFSET_MAX, 32);
    check('PLATE_POLYGON_OFFSET (scene/tiles.ts)', tiles.PLATE_POLYGON_OFFSET, -33);
    check('one rung above the ladder ceiling',
          tiles.PLATE_POLYGON_OFFSET, -(ground.AREA_OFFSET_MAX + 1));
    check('and in FRONT of it (negative pulls towards the camera)',
          tiles.PLATE_POLYGON_OFFSET < -ground.AREA_OFFSET_MAX ? 1 : 0, 1);
    const mat = { polygonOffset: false, polygonOffsetFactor: 0, polygonOffsetUnits: 0 };
    tiles.applyPlateDepthBias(mat);
    check('applyPlateDepthBias: on', mat.polygonOffset ? 1 : 0, 1);
    check('applyPlateDepthBias: factor', mat.polygonOffsetFactor, -33);
    check('applyPlateDepthBias: units', mat.polygonOffsetUnits, -33);
  }

  console.log(`\n${passed} ok, ${failed} failed`);
  process.exit(failed ? 1 : 0);
}

main().catch((e) => { console.error(e); process.exit(1); });
