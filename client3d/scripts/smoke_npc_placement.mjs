#!/usr/bin/env node
/**
 * Smoke check for WHERE THE FIGURES OF ONE LOCATION ARE DRAWN — the pure room
 * ladder `placeAtLocation` and the huddle `huddleOffset`
 * (`client3d/src/game/npcPlacement.ts`, extracted from
 * `main.computeNpcPlacements` for the native client, plan Task 29).
 *
 * Usage:  node client3d/scripts/smoke_npc_placement.mjs
 *
 * Every number below is derived BY HAND here and never recorded from the
 * current output (§ B5a). The cases run from
 * `shared/test-vectors/npc_placement.json`, which the native client's C#
 * tests read too; each label starts with the [n] of its derivation.
 *
 * ADAPTER (the JSON form of the TS call, mirrored by the C# dispatch):
 *   placeAtLocationValue(rows, roomOf, tile, ctx)
 *     rows    worldmap rows {name, pos?, place?, activity_animation?,
 *             movement_target_id?}
 *     roomOf  object name -> room (absent = no room)
 *     tile    {center, yaw (RADIANS), width, isBuilding, fade, levelFilter,
 *             alwaysVisibleRooms: [ids], roomCenters: {room: point},
 *             roomLevels: {room: n}, roomMarkers: {room: {placeId: {slots:
 *             [points], rotation?, tilt?, roll?}}}, roomSitSpots /
 *             roomLieSpots: {room: [points]}, corridors: [room ids]}
 *     ctx     {locId, near, shown: {name: {room, interiorShown}},
 *             roomStand: {room: [a, b, c]} = the standing height
 *             a·lx + b·lz + c at a TILE-LOCAL point (a room not listed
 *             answers null), ground: [a, b, c] = the huddle ground
 *             a·x + b·z + c at a WORLD point, targets: {id: point}}
 *     The seat point is `slotFor` (scene_models.json) on the marker's slots.
 *     Result: one entry per row in the ladder's order, {name, branch, pos,
 *     face (null = none), lean (null = none), inRoom, interiorShown, hidden,
 *     transition}.
 *
 * ============================================================================
 * THE TILE OF EVERY CASE ("house", the fixture HOUSE)
 * ============================================================================
 * Centre (100, 2, 50), yaw π/2 = 1.5707963267948966 rad: cos = 0 (6.1e-17),
 * sin = 1. With § A1.1
 *     tileToWorld(lx, lz)    = (100 + lx·cos + lz·sin, ·, 50 − lx·sin + lz·cos)
 *                            = (100 + lz, ·, 50 − lx)
 *     worldToTile(x, z)      = (lx, lz) = (50 − z, x − 100)
 *     tileDirToWorld(lx, lz) = (lz, −lx)
 * width 10, a building. Rooms (centre = the stand `deriveRoomSpots` /
 * `deriveCorridorCentres` wrote, level):
 *     hall        (98, 2.01, 47)    0
 *     loft        (103, 4.91, 52)   1
 *     __floor__1  (101, 4.81, 49)   1   the storey-1 corridor
 *     porch       (96, 2.01, 55)    0   ALWAYS VISIBLE
 * Places: hall/chair1 slots (97, 2.46, 46), (97.6, 2.46, 46), rotation 90,
 * tilt 10, roll 0; hall/bare no slots, rotation 0; loft/bed1 slot
 * (104, 5.36, 53), no rotation, tilt 0, roll 0. Sit surfaces of the hall
 * (99, 2.47, 48), (99.5, 2.47, 48); lie surface of the loft
 * (104.5, 5.5, 53.5). Standing height: hall 0.1·lx + 2.01, loft none.
 * Huddle ground 0.01·x + 0.02·z + 1. Targets: market (120, 0, 60), house
 * (= the location itself) (100, 2, 50).
 *
 * ============================================================================
 * [1] huddleOffset(isBuilding, width, index, count)
 * ============================================================================
 * A building: x = (index − (count − 1)/2)·2.3, z = width·0.36.
 *     (true, 10, 0, 3) -> (−2.3, 3.6)    (true, 10, 1, 3) -> (0, 3.6)
 *     (true, 10, 2, 3) -> (2.3, 3.6)     (true, 20, 0, 1) -> (0, 7.2)
 * An open place: angle = index/max(count, 1)·2π, (cos, sin)·2.6.
 *     (false, 10, 0, 4) -> (2.6, 0)      (false, 10, 1, 4) -> (0, 2.6)
 *     (false, 10, 2, 4) -> (−2.6, 0)     (false, 10, 0, 0) -> (2.6, 0)
 *     (the last: count 0 is guarded to 1, angle 0).
 *
 * ============================================================================
 * [2] THE CLOSED INTERIOR (fade 0, level 0 shown, NOT the near ring)
 * ============================================================================
 * Rows Ada (hall, pos (98.5, 47.5)), bo (porch), Cem (no room, target
 * market), Dov (room "attic", which the tile has no centre for, target house).
 * SORTED BY localeCompare: Ada, bo, Cem, Dov — case-insensitive at the first
 * level, an ordinal sort would put "bo" last. Count 4; huddle x by index:
 *     0: −3.45   1: −1.15   2: 1.15   3: 3.45,  z 3.6 -> world (103.6, 50 − x)
 *   Ada: room hall has a centre, but the interior is not revealed (fade 0,
 *        hall not always visible) -> HUDDLE i 0: (103.6, ·, 53.45), ground
 *        1.036 + 1.069 + 1 = 3.105. HIDDEN: in a room with a centre and not
 *        drawn in it (the closed interior). No previous placement -> snap.
 *   bo:  porch is ALWAYS VISIBLE -> revealed, drawn in it. No near ring ->
 *        no seat, no surface; not a corridor; no pos -> CENTRE (96, 2.01, 55).
 *        Not hidden (fade 0 never hides a storey). prev {null, false} ->
 *        next {porch, true}: room AND view changed -> snap.
 *   Cem: no room -> HUDDLE i 2: (103.6, ·, 48.85), ground 1.036 + 0.977 + 1
 *        = 3.013. Faces market: (120 − 103.6, 0, 60 − 48.85) = (16.4, 0,
 *        11.15). prev {null, false} = next -> stay.
 *   Dov: attic has no centre -> not revealed (attic is not always visible),
 *        HUDDLE i 3: (103.6, ·, 46.55), ground 1.036 + 0.931 + 1 = 2.967.
 *        NOT hidden (no centre). Target "house" is its own location: no
 *        facing. prev {null, true} -> next {null, false}: same room -> stay.
 *
 * ============================================================================
 * [3] THE OPEN INTERIOR (fade 1, level 0 shown, the near ring)
 * ============================================================================
 * Twelve rows, sorted Ada Bea Cy Eli Fay Gus Hal Ivo Jo Kai Lu Mo. Hall mates
 * in that order: Ada 0, Bea 1, Cy 2, Eli 3, Kai 4, Lu 5; loft mates: Fay 0,
 * Hal 1, Ivo 2, Mo 3.
 *   Ada  hall, place chair1 slot 1, target market -> SEAT (97.6, 2.46, 46).
 *        rotation 90: gaze (sin, cos) = (1, 0) tile-local -> world (0, −1):
 *        face (0, 0, −1) — the seat's facing wins over the target. tilt 10 ->
 *        lean (10, 0). Snap (first placement).
 *   Bea  hall, "sit-cmu" (family sit) -> POOL sit[1 mod 2] = (99.5, 2.47,
 *        48). prev {hall, true} -> stay.
 *   Cy   hall, "lie-down" (family lie): the hall has no lie surface, so the
 *        sit pool: sit[2 mod 2] = (99, 2.47, 48). prev {kitchen, true} ->
 *        a room change with the view unchanged -> ROUTE.
 *   Eli  hall, place "bare" (no slots: no seat), idle, pos (98.5, 47.5):
 *        tile-local (50 − 47.5, 98.5 − 100) = (2.5, −1.5), standing height
 *        0.1·2.5 + 2.01 = 2.26 -> POS (98.5, 2.26, 47.5). prev {hall, false}
 *        -> the same room -> stay.
 *   Fay  loft, "lie" -> POOL lie[0] = (104.5, 5.5, 53.5). HIDDEN: loft is
 *        storey 1, storey 0 shown.
 *   Gus  __floor__1, target market -> CORRIDOR (101, 4.81, 49), face
 *        (19, 0, 11). Hidden (storey 1).
 *   Hal  loft, nothing -> CENTRE (103, 4.91, 52). Hidden.
 *   Ivo  loft, pos (104, 51), target house -> POS: the loft has no standing
 *        height, so the centre's 4.91: (104, 4.91, 51). No facing (own
 *        location). Hidden.
 *   Jo   no room -> HUDDLE i 8 of 12: x = (8 − 5.5)·2.3 = 5.75 -> world
 *        (103.6, ·, 44.25), ground 1.036 + 0.885 + 1 = 2.921. interiorShown
 *        true (fade 1). prev {null, false} -> next {null, true}: same room ->
 *        stay.
 *   Kai  hall, place chair1 slot "pair" -> the mean of the slots
 *        (97.3, 2.46, 46), face (0, 0, −1), lean (10, 0).
 *   Lu   hall, place chair1 slot 7 (out of range) -> slot 0 (97, 2.46, 46),
 *        face (0, 0, −1), lean (10, 0).
 *   Mo   loft, place bed1 slot 0, target market -> SEAT (104, 5.36, 53); no
 *        rotation, so the target faces it: (16, 0, 7); tilt 0 and roll 0 ->
 *        no lean. Hidden.
 *
 * ============================================================================
 * [4] STOREY 1 SHOWN (fade 1, level 1, NOT the near ring)
 * ============================================================================
 *   Ada  hall, place chair1, "sit", pos (97.6, 46): not near -> no seat and
 *        no surface -> POS, tile-local lx = 50 − 46 = 4, height 0.4 + 2.01 =
 *        2.41: (97.6, 2.41, 46). HIDDEN (hall is storey 0).
 *   bo   porch -> CENTRE (96, 2.01, 55); storey 0, but ALWAYS VISIBLE -> not
 *        hidden.
 *   Fay  loft, "lie", not near -> CENTRE (103, 4.91, 52); storey 1 = shown ->
 *        not hidden. prev {loft, true} -> stay.
 *
 * ============================================================================
 * [5] AN OPEN PLACE (the same tile as a non-building, fade 0)
 * ============================================================================
 * Rows A, B, C without a room: the ring, count 3.
 *   A  angle 0     -> (2.6, 0)               -> world (100, ·, 47.4),
 *                     ground 1 + 0.948 + 1 = 2.948
 *   B  angle 2π/3  -> (−1.3, 2.2516660498395407)
 *                  -> world (102.25166604983954, ·, 51.3),
 *                     ground 1.0225166604983954 + 1.026 + 1 = 3.0485166604983954
 *   C  angle 4π/3  -> (−1.3, −2.2516660498395407)
 *                  -> world (97.74833395016046, ·, 51.3),
 *                     ground 0.9774833395016046 + 1.026 + 1 = 3.0034833395016046
 *   (2.6·sin(2π/3) = 2.6·0.8660254037844386.) All snap, none hidden.
 */
import { build } from 'esbuild';
import { fileURLToPath } from 'node:url';
import { loadVectors, runVectors } from '../../shared/test-vectors/vectors.mjs';

const entry = `
export { huddleOffset, placeAtLocation } from './client3d/src/game/npcPlacement.ts';
export { slotFor } from './client3d/src/scene/placeSlot.ts';
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
    roomMarkers: markers,
    roomSitSpots: mapOf(t.roomSitSpots), roomLieSpots: mapOf(t.roomLieSpots),
    corridors: (t.corridors ?? []).map((roomId) => ({ roomId })),
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
