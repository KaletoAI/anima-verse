#!/usr/bin/env node
/**
 * Smoke check: a STANDING pair interaction (§ A8a, `anchor.place_id` null)
 * stays on the storey of its room — the upper floor, the cellar, a storey
 * corridor — instead of dropping onto the terrain under the building.
 *
 * Usage:  node client3d/scripts/smoke_pair_storey.mjs
 *         (needs three and esbuild; no clips, no models, no server)
 *
 * Hand-derived expectations
 * -------------------------
 * § A8a puts a pair figure at `anchor + R_y(yaw) · clipRoot(t)`; the clip
 * frame has its floor at y = 0, so the HEIGHT is the floor the pair stands
 * on. For a pair on a place it is the place's slot height (unchanged here);
 * a pair that met halfway stands on the floor of the ROOM both are in — the
 * same height every other figure the server put on a room point gets
 * (`roomFloorAt + WALK_CLEARANCE_M`, `WALK_CLEARANCE_M` = 0.01, else the
 * room's stand centre for a room without a floor of its own, § A13c).
 *
 * The tile below stands at centre y = 0 and has no baked surfaces, so a
 * room's floor is its DECLARED plate top (`tile.center.y + declared`):
 *
 *   [1] `roomStandY` per room (tile-local point (1, 2)):
 *       og      declared  3.20 → 3.20 + 0.01 =  3.21
 *       keller  declared −2.80 → −2.80 + 0.01 = −2.79
 *       flur    no floor entry, stand centre y 6.41 → 6.41
 *       nowhere neither                          → null
 *
 *   [2] `NpcManager.tick` with one NPC in a pair, the clip root held at
 *       (0.3, 0) in the clip frame, anchor (10, 22), yaw 0 →
 *       x = 10 + 0.3·cos 0 + 0·sin 0 = 10.3, z = 22 − 0.3·sin 0 + 0 = 22.
 *       The terrain stub answers 0.5 everywhere (the ground under the house).
 *       a) room `og` (stand sampler = `roomStandY` above)  → y =  3.21
 *       b) room `keller`                                    → y = −2.79
 *       c) the location's ground (sampler answers null)     → y =  0.5 (terrain)
 *       d) seated on a place, slot height 3.65              → y =  3.65
 *       Before the fix every case but d) came out at 0.5: the pair sat on the
 *       terrain, i.e. on the ground floor.
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
    const entry = [
      `export { NpcManager } from '${src}/scene/npcs';`,
      `export { roomStandY } from '${src}/scene/tiles';`,
    ].join('\n');
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

  // A tile with three rooms: an upper-storey room, a cellar room (both with
  // a declared plate top) and a storey corridor (stand centre only).
  const tile = {
    center: new THREE.Vector3(0, 0, 0),
    surfaces: [],
    roomFloors: new Map([
      ['og', { hull: [[0, 0], [4, 0], [4, 4]], declared: 3.2 }],
      ['keller', { hull: [[0, 0], [4, 0], [4, 4]], declared: -2.8 }],
    ]),
    roomCenters: new Map([['flur', new THREE.Vector3(2, 6.41, 2)]]),
  };

  console.log('[1] roomStandY');
  near('[1] og: declared 3.20 + clearance', C.roomStandY(tile, 'og', 1, 2), 3.21);
  near('[1] keller: declared -2.80 + clearance', C.roomStandY(tile, 'keller', 1, 2), -2.79);
  near('[1] flur: the corridor stand centre', C.roomStandY(tile, 'flur', 1, 2), 6.41);
  check('[1] unknown room: null', C.roomStandY(tile, 'nowhere', 1, 2) === null);

  console.log('[2] NpcManager.tick — one figure in a pair');
  const TERRAIN = 0.5;
  const run = (room, seatY) => {
    const lib = { pairRootAt: () => ({ x: 0.3, z: 0 }) };
    const figure = {
      playPair: () => true, holdsTravel: false, takeTravel: () => {},
      setYaw: () => {}, update: () => {},
    };
    const mgr = new C.NpcManager(lib, {
      syncCounters: { posCorr: 0, pos409: 0, travBack: 0, travFwd: 0, travErrMaxM: 0, arrive: 0, place: 0 },
      errWindow: { t: [], e: [] },
    });
    mgr.setGroundHeight(() => TERRAIN);
    mgr.setPlaceAt(() => (seatY === undefined ? undefined : { slots: [{ y: seatY }] }));
    mgr.setRoomStandAt((_name, x, z) => (room ? C.roomStandY(tile, room, x - 10, z - 22) : null));
    const root = new THREE.Group();
    const npc = {
      name: 'A', animation: 'idle', root, figure, ring: null, sprite: null,
      label: { visible: false }, labelName: { textContent: '' }, labelActivity: { textContent: '' },
      labelBubble: null, bubbleUntil: 0, target: new THREE.Vector3(), pace: 1, face: null,
      waypoints: [], ride: null, route: null, travelling: false, reckon: null,
      interaction: {
        id: 'p1', clip: 'handshake__a',
        anchor: { x: 10, z: 22, yaw: 0, placeId: seatY === undefined ? null : 'sofa' },
        elapsed: 0, clipT: 0, clipDuration: 2, loop: true, rate: 1, stamp: 0,
      },
      activity: '', travelLine: null, travelKey: '', bobPhase: 0, settle: null,
    };
    mgr.npcs.set('A', npc);
    mgr.tick(1 / 30, 10);
    return root.position;
  };
  const og = run('og');
  near('[2a] og: x = 10.3', og.x, 10.3);
  near('[2a] og: z = 22', og.z, 22);
  near('[2a] og: y = the upper floor, 3.21', og.y, 3.21);
  near('[2b] keller: y = the cellar floor, -2.79', run('keller').y, -2.79);
  near('[2c] ground of the location: y = terrain 0.5', run(null).y, TERRAIN);
  near('[2d] seated pair: y = slot height 3.65', run('og', 3.65).y, 3.65);

  console.log(failed ? `\n${failed} check(s) FAILED` : '\nall checks passed');
  process.exit(failed ? 1 : 0);
}

main().catch((e) => { console.error(e); process.exit(1); });
