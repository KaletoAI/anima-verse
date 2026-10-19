#!/usr/bin/env node
/**
 * Smoke check: the HEIGHT of a room marker's slots (`tiles.deriveRoomSpots`)
 * is the room's floor UNDER THE PLACE plus the marker's own `offset_y` — the
 * room's baked diorama lattice is not part of it, and the floor is not taken
 * at the room's centre.
 *
 * Usage:  node client3d/scripts/smoke_marker_floor.mjs
 *         (needs three and esbuild; no models, no server)
 *
 * The finding (2026-10-20, "Dachboden", storey 2): a lying place with
 * `offset_y` 0.30 over the storey datum, in a diorama room whose furniture at
 * the room's CENTRE stands 0.69 m high. The slots were written as
 * `floor(room centre) − drop + offsetY`, and the floor there was the lattice —
 * the table top — so the pair on the mattress lay 0.69 m above where the
 * place says. A marker's `offset_y` already says how high the furniture under
 * it is (§ A4: `y_world` = datum + `offset_y`, the composer knows no lattice),
 * so the floor it stands on is the room's floor WITHOUT the lattice: its
 * declaration, else the terrain — sampled at the place (the mean of its
 * slots: the slots of one place share one height).
 *
 * Hand-derived expectations
 * -------------------------
 * [1] Upper storey, tile centre y 0, yaw 0. Room `attic`, hull (−1,−0.5)…
 *     (1,0.5), declared floor 5.43. One lattice for the room: s = max_m 2 /
 *     extent 2 = 1, anchor (0,0), bottom_y 5.43, step 1, origin (−1,−0.5),
 *     3 × 2 nodes, values 13 69 13 / 13 69 13 cm → the middle column (x = 0)
 *     is a table at 5.43 + 0.69 = 6.12, the edge x = 1 a mattress at 5.56.
 *     Marker `bed` at (1, 0), `offsetY` 0.30, `drop` 0.002:
 *       slot y = 5.43 − 0.002 + 0.30 = 5.728
 *       (before: 6.12 − 0.002 + 0.30 = 6.418, the table under the centre)
 *     The room's CENTRE (centroid (0, 0)) still stands on the lattice:
 *       6.12 + 0.01 = 6.13 — a figure walks on the diorama, a place does not.
 * [2] Storey 0 on a slope, no declaration: terrain y = 0.1·x. Room `yard`,
 *     hull (0,0)…(4,2), centroid (2, 1). Marker `bench` with two slots at
 *     (3.2, 1) and (3.8, 1) (mean x 3.5), `offsetY` 0.05, `drop` 0:
 *       both slots y = 0.1·3.5 + 0.05 = 0.40
 *       (before: terrain at the centre 0.1·2 + 0.05 = 0.25)
 */
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '../..');
let failed = 0;
const check = (label, ok, detail = '') => {
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${label}${detail ? `  (${detail})` : ''}`);
  if (!ok) failed++;
};
const near = (label, actual, expected, eps = 1e-9) =>
  check(label, Number.isFinite(actual) && Math.abs(actual - expected) <= eps,
    `${Number(actual).toFixed(6)} (expected ${expected})`);

/** Bundle the client modules into ONE file next to this script (three stays
 *  external so the bundle and this script share one three). */
async function loadClient() {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(ROOT, 'client3d/scripts/.smoke-'));
  try {
    const src = join(ROOT, 'client3d/src');
    const entry = `export { deriveRoomSpots, setWorldGround } from '${src}/scene/tiles';`;
    const built = await esbuild.build({
      stdin: { contents: entry, resolveDir: dir, loader: 'ts' },
      bundle: true, platform: 'node', format: 'esm', write: false,
      outfile: join(dir, 'client.mjs'), external: ['three', 'three/*'],
    });
    const file = join(dir, 'client.mjs');
    await writeFile(file, built.outputFiles[0].text, 'utf8');
    return await import(`file://${file}`);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

async function main() {
  const THREE = await import('three');
  const C = await loadClient();
  C.setWorldGround((x) => 0.1 * x);

  const tileWith = (roomId, hull, declared, surfaces, markers) => ({
    center: new THREE.Vector3(0, 0, 0), yaw: 0, group: new THREE.Group(),
    loc: { rooms: [{ id: roomId, name: roomId }] },
    roomFloors: new Map([[roomId, declared === undefined ? { hull } : { hull, declared }]]),
    surfaces, roomRects: new Map(), roomCenters: new Map(),
    roomSitSpots: new Map(), roomLieSpots: new Map(),
    roomMarkers: new Map([[roomId, new Map(markers.map((m) => [m.id, m]))]]),
  });
  const marker = (id, slots, offsetY, drop) => ({
    roomId: '', id, group: 'lie', slots: slots.map(([x, z]) => new THREE.Vector3(x, 99, z)),
    offsetY, drop, fixed: false, diorama: true, level: 0, lift: 0,
  });

  console.log('[1] upper storey, diorama room with a table at its centre');
  const attic = tileWith('attic', [[-1, -0.5], [1, -0.5], [1, 0.5], [-1, 0.5]], 5.43, [{
    id: 'attic-model', roomId: 'attic', level: 2, lift: 0,
    spec: { anchor: [0, 0], yaw_deg: 0, bottom_y: 5.43, max_m: 2, measure: 'xz' },
    surface: { step: 1, origin: [-1, -0.5], cols: 3, rows: 2, values: [13, 69, 13, 13, 69, 13],
      box_min: [-1, 0, -0.5], box_max: [1, 1, 0.5], extent_snapped: [2, 1, 1] },
  }], [marker('bed', [[1, 0]], 0.30, 0.002)]);
  C.deriveRoomSpots(attic, 'attic');
  near('[1] lying place: declared floor 5.43 − 0.002 + 0.30', attic.roomMarkers.get('attic').get('bed').slots[0].y, 5.728);
  near('[1] room centre still on the lattice: 6.12 + 0.01', attic.roomCenters.get('attic').y, 6.13);

  console.log('[2] storey 0 on a slope, no declaration');
  const yard = tileWith('yard', [[0, 0], [4, 0], [4, 2], [0, 2]], undefined, [],
    [marker('bench', [[3.2, 1], [3.8, 1]], 0.05, 0)]);
  C.deriveRoomSpots(yard, 'yard');
  const bench = yard.roomMarkers.get('yard').get('bench').slots;
  near('[2] slot 0: terrain at the place 0.35 + 0.05', bench[0].y, 0.40);
  near('[2] slot 1: the same height as slot 0', bench[1].y, 0.40);

  console.log(failed ? `\n${failed} check(s) FAILED` : '\nall checks passed');
  process.exit(failed ? 1 : 0);
}

main().catch((e) => { console.error(e); process.exit(1); });
