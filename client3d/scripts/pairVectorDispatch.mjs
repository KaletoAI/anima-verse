/** Task 32 test-only adapters. All geometry, timing and placement run production
 * code. Inputs are explicit JSON; no live configuration, models or server.
 */
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import { build } from 'esbuild';
import * as THREE from 'three';
import { loadVectors, runVectors } from '../../shared/test-vectors/vectors.mjs';

const root = fileURLToPath(new URL('../../', import.meta.url));
let loaded;
async function modules() {
  if (!loaded) loaded = (async () => {
    const dir = await mkdtemp(join(root, 'client3d/scripts/.smoke-'));
    try {
      const entry = `export {pairClipPhase, PAIR_SNAP_S} from '${root}client3d/src/game/pairClip.ts';
export {extractRootPath, isPairClipName, rootPathAt} from '${root}client3d/src/scene/figures.ts';
export {NpcManager} from '${root}client3d/src/scene/npcs.ts';
export {roomStandY} from '${root}client3d/src/scene/tiles.ts';
export {anchorFigureBind} from '${root}packages/scene-render/src/figure.ts';`;
      const built = await build({stdin: {contents: entry, resolveDir: root, loader: 'ts'},
        bundle: true, platform: 'node', format: 'esm', write: false,
        outfile: join(dir, 'vectors.mjs'),
        external: ['three', 'three/*'], logLevel: 'error'});
      const file = join(dir, 'vectors.mjs');
      await writeFile(file, built.outputFiles[0].text);
      return await import(`file://${file}`);
    } finally { await rm(dir, {recursive: true, force: true}); }
  })();
  return loaded;
}
function tileFrom(data) {
  return {...data, center: new THREE.Vector3(...data.center),
    roomFloors: new Map(data.roomFloors),
    roomCenters: new Map(data.roomCenters.map(([k,v]) => [k,new THREE.Vector3(...v)]))};
}

/** Exercise the full manager tick with the same minimal NPC as the source smoke. */
function placement(m, data) {
  const tile = tileFrom(data.tile);
  const lib = { pairRootAt: () => data.root };
  const figure = {
    playPair: () => true, holdsTravel: false, takeTravel: () => {},
    setYaw: () => {}, update: () => {}, setFirstPerson: () => {}, hasHead: false,
  };
  const mgr = new m.NpcManager(lib, {
    syncCounters: { posCorr: 0, pos409: 0, travBack: 0, travFwd: 0, travErrMaxM: 0, arrive: 0, place: 0 },
    errWindow: { t: [], e: [] },
  });
  mgr.setGroundHeight(() => data.terrainY);
  mgr.setPlaceAt(() => (data.seatSlots === null ? undefined : { slots: data.seatSlots }));
  mgr.setRoomStandAt((_name, x, z) => (data.room ? m.roomStandY(tile, data.room, x - data.anchor.x, z - data.anchor.z) : null));
  const root = new THREE.Group();
  const npc = {
    name: 'A', animation: 'idle', root, figure, ring: null, sprite: null,
    label: { visible: false }, labelName: { textContent: '' }, labelActivity: { textContent: '' },
    labelBubble: null, bubbleUntil: 0, target: new THREE.Vector3(), pace: 1, face: null,
    waypoints: [], ride: null, route: null, travelling: false, reckon: null,
    interaction: {
      id: 'p1', clip: 'handshake__a',
      anchor: { ...data.anchor, placeId: data.placeId },
      elapsed: 0, clipT: 0, clipDuration: 2, loop: true, rate: 1, stamp: 0,
    },
    activity: '', travelLine: null, travelKey: '', bobPhase: 0, settle: null,
  };
  mgr.npcs.set('A', npc);
  mgr.tick(1 / 30, 10);
  return root.position;
}

export async function pairVectorDispatch() {
  const m = await modules();
  return {
    pairClipValue: (input, field) => m.pairClipPhase(input)[field],
    pairSnapS: () => m.PAIR_SNAP_S,
    pairFrames: (input, frames, field) => {
      let result;
      for (const dt of frames) {
        input.localClipT += input.rate > 0 ? dt : 0;
        result = m.pairClipPhase(input);
        input.localClipT = result.clipT;
      }
      return result[field];
    },
    isPairClipName: m.isPairClipName,
    extractPairRootPath: (tracks) => {
      const clip = new THREE.AnimationClip('pair', -1, tracks.map((t) =>
        new THREE.VectorKeyframeTrack(t.name, t.times, t.values)));
      const path = m.extractRootPath(clip);
      return {times: Array.from(path.times), xz: Array.from(path.xz)};
    },
    pairRootPathValue: (path, t, field) => m.rootPathAt({
      times: Float32Array.from(path.times), xz: Float32Array.from(path.xz)}, t)[field],
    pairRoomStandY: (tile, room, x, z) => m.roomStandY(tileFrom(tile), room, x, z),
    pairPlacementValue: (data, field) => placement(m, data)[field],
    anchorFigureBindValue: (data) => {
      const pivot = new THREE.Group();
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute('position', new THREE.Float32BufferAttribute([ ...data.min, ...data.max ], 3));
      pivot.add(new THREE.Mesh(geometry));
      pivot.position.fromArray(data.initialPosition);
      pivot.scale.setScalar(data.initialScale);
      try {
        const scale = m.anchorFigureBind(THREE, pivot, data.height);
        const box = new THREE.Box3().setFromObject(pivot);
        return {scale, position: pivot.position.toArray(), min: box.min.toArray(), max: box.max.toArray()};
      } finally { geometry.dispose(); pivot.children[0].material.dispose(); }
    },
  };
}
export async function runPairVectors(name) {
  return runVectors(loadVectors(name), await pairVectorDispatch());
}
