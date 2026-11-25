#!/usr/bin/env node
/**
 * Derivation moved to native/tests/Derivations/npc_placement.md (E1, 2026-11-25).
 * Usage:  node client3d/scripts/smoke_npc_placement.mjs
 * Runs until E3 deletes the browser scene; the C# vector tests keep executing the cases.
 */
import { build } from 'esbuild';
import { fileURLToPath } from 'node:url';
import { loadVectors, runVectors } from '../../shared/test-vectors/vectors.mjs';

const entry = `
export { huddleOffset, placeAtLocation } from './client3d/src/game/npcPlacement.ts';
export { slotFor } from './packages/scene-render/src/placeSlot.ts';
export { Vector3 } from 'three';
`;
const built = await build({
  stdin: { contents: entry, resolveDir: fileURLToPath(new URL('../..', import.meta.url)), loader: 'ts' },
  bundle: true, platform: 'node', format: 'esm', write: false, logLevel: 'error',
});
const m = await import(`data:text/javascript;base64,${Buffer.from(built.outputFiles[0].text).toString('base64')}`);

const mapOf = (obj) => new Map(Object.entries(obj ?? {}));
const plane = (abc) => (u, v) => abc[0] * u + abc[1] * v + abc[2];

/** The JSON form of a tile -> the structural `PlacementTile` (Maps, a Set,
 *  three vectors for the slots `slotFor` clones). */
function tileOf(t) {
  const markers = new Map();
  for (const [room, places] of Object.entries(t.roomMarkers ?? {})) {
    const byId = new Map();
    for (const [id, e] of Object.entries(places)) {
      byId.set(id, { ...e, slots: e.slots.map((p) => new m.Vector3(p.x, p.y, p.z)) });
    }
    markers.set(room, byId);
  }
  return {
    center: t.center, yaw: t.yaw, width: t.width, isBuilding: t.isBuilding,
    fade: t.fade, levelFilter: t.levelFilter,
    alwaysVisibleRooms: new Set(t.alwaysVisibleRooms ?? []),
    roomCenters: mapOf(t.roomCenters), roomLevels: mapOf(t.roomLevels),
    roomFloors: mapOf(t.roomFloors),
    roomMarkers: markers,
    roomSitSpots: mapOf(t.roomSitSpots), roomLieSpots: mapOf(t.roomLieSpots),
    corridors: (t.corridors ?? []).map((roomId) => ({ roomId })),
    groundRooms: new Set(t.groundRooms ?? []),
  };
}

const point = (p) => ({ x: p.x, y: p.y, z: p.z });

function placeAtLocationValue(rows, roomOf, tile, ctx) {
  const stand = ctx.roomStand ?? {};
  const out = m.placeAtLocation(rows, tileOf(tile), {
    locId: ctx.locId,
    near: ctx.near,
    roomOf: (name) => roomOf[name],
    shownOf: (name) => ctx.shown?.[name],
    seatOf: m.slotFor,
    roomStandY: (room, lx, lz) => (stand[room] ? plane(stand[room])(lx, lz) : null),
    groundY: (x, z) => plane(ctx.ground)(x, z),
    targetCentre: (id) => ctx.targets?.[id],
  });
  return out.map((p) => ({
    name: p.row.name, branch: p.branch, pos: point(p.pos),
    face: p.face ? point(p.face) : null, lean: p.lean ?? null,
    inRoom: p.inRoom, interiorShown: p.interiorShown, hidden: p.hidden,
    transition: p.transition,
  }));
}

console.log('(vectors) shared/test-vectors/npc_placement.json');
const { passed, failed } = runVectors(loadVectors('npc_placement'), {
  huddleOffset: m.huddleOffset,
  placeAtLocationValue,
});
console.log(`smoke_npc_placement: ${passed} ok, ${failed} failed`);
process.exitCode = failed ? 1 : 0;
