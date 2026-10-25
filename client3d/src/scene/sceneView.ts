import type { WorldLocation } from '../types';
/** Pure scene view decisions, shared with native-client test vectors. */
import type { ScenePayload, SceneModelSpec } from '@anima/scene-render';
export { storeyPieceOpacity } from './storeyDisplay';
export { farShellSource } from './shellPlan';
export { ringFor, placeDistance } from '../game/streamRings';

type ViewTile = { interior: unknown; isBuilding: boolean; modelIsShellArea?: boolean; modelIsGround?: boolean };
export function openable(tile: ViewTile): boolean {
  return !!tile.interior && (tile.isBuilding || !!tile.modelIsShellArea || !!tile.modelIsGround);
}
export function hasInterior(scene: Pick<ScenePayload, 'plates' | 'floor_plan' | 'walls' | 'extras' | 'markers' | 'models'>): boolean {
  return scene.plates.length > 0 || scene.floor_plan.length > 0 || scene.walls.length > 0
    || scene.extras.length > 0 || scene.markers.length > 0 || scene.models.some(m => m.role !== 'building');
}
export function isOutdoorSpec(roomId: SceneModelSpec['room_id'], alwaysVisible: readonly string[], outdoor: readonly string[]): boolean {
  return !roomId || alwaysVisible.includes(roomId) || outdoor.includes(roomId);
}
export function buildingTier(distance: number, current: 'low' | 'full'): 'low' | 'full' {
  if (current === 'low' && distance < 45) return 'full';
  if (current === 'full' && distance > 60) return 'low';
  return current;
}
export function interiorTier(areaDetail: boolean, open: boolean): 'low' | 'full' {
  return areaDetail && !open ? 'low' : 'full';
}
export function wallVisible(camX: number, camZ: number, midX: number, midZ: number,
                            normalX: number, normalZ: number, level: number, shown: number): boolean {
  return (camX - midX) * normalX + (camZ - midZ) * normalZ <= 0 && level === shown;
}
export function fadeStep(fade: number, target: number, dt: number): number {
  const k = 1 - Math.exp(-4 * dt);
  return (1 - k) * fade + k * target;
}
export function fadeOpacities(f: number) {
  return { roof: Math.max(0, 1 - f * 1.4), shell: 1 - f * 0.88,
    roofVisible: f < 0.95, shellShadow: f < 0.4, interiorVisible: f > 0.03, labelsVisible: f > 0.5 };
}
export function roomVisible(alwaysVisible: boolean, level: number | null, shown: number): boolean {
  return alwaysVisible || (level ?? 0) === shown;
}
export function farShellPiece(kind: 'plate' | 'wall', piece: { level: number; room_id?: string | null; glass?: boolean }): boolean {
  return piece.level >= 0 && (kind === 'plate' ? !piece.room_id : !piece.glass);
}
export function doorMarkTransform(width: number, thickness: number, along: { x: number; z: number },
                                  mid: { x: number; z: number }, baseY: number) {
  return { scale: [width, 1, Math.max(width * 0.3, thickness)], yaw: Math.atan2(-along.z, along.x),
    position: [mid.x, baseY + 0.02, mid.z] };
}
export function boundaryMarkTransform(width: number, inward: { x: number; z: number }, x: number, z: number, ground: number) {
  return { scale: [width, 1, Math.max(width * 0.3, 0.3)], yaw: Math.atan2(inward.x, inward.z),
    position: [x, ground + 0.05, z] };
}
export function neighbourOccludes(camera: { x: number; z: number }, target: { x: number; z: number },
                                  neighbour: { x: number; z: number; width: number; height: number }, sameTile = false): boolean {
  if (sameTile || neighbour.height <= 1.5) return false;
  const tx = target.x - camera.x, tz = target.z - camera.z;
  const nx = neighbour.x - camera.x, nz = neighbour.z - camera.z;
  const len2 = tx * tx + tz * tz;
  const t = len2 > 1e-6 ? (nx * tx + nz * tz) / len2 : 0;
  const px = camera.x + tx * t, pz = camera.z + tz * t;
  return t > 0.05 && t < 0.92
    && Math.hypot(neighbour.x - px, neighbour.z - pz) < neighbour.width * 1.05;
}
/** Grow only the camera-facing edges, by at most one footprint width. */
export function basementHole(bounds: { minX: number; minZ: number; maxX: number; maxZ: number },
                              center: { x: number; z: number }, camera: { x: number; z: number }, width: number): [number, number, number, number] {
  let { minX, minZ, maxX, maxZ } = bounds;
  const dx = camera.x - center.x, dz = camera.z - center.z;
  const len = Math.hypot(dx, dz) || 1, ux = dx / len, uz = dz / len;
  if (ux > 0) maxX += width * ux; else minX += width * ux;
  if (uz > 0) maxZ += width * uz; else minZ += width * uz;
  return [minX, minZ, maxX, maxZ];
}
export interface TileFrame { center: { x: number; y: number; z: number }; yaw: number }
export function tileToWorld(tile: TileFrame, lx: number, lz: number, ly = 0) {
  const c = Math.cos(tile.yaw), s = Math.sin(tile.yaw);
  return { x: tile.center.x + lx * c + lz * s, y: tile.center.y + ly, z: tile.center.z - lx * s + lz * c };
}
export function tileDirToWorld(tile: Pick<TileFrame, 'yaw'>, lx: number, lz: number) {
  const c = Math.cos(tile.yaw), s = Math.sin(tile.yaw);
  return { x: lx * c + lz * s, z: -lx * s + lz * c };
}
export function tileWorldBounds(tile: TileFrame & { boundary: [number, number][] | null }) {
  if (!tile.boundary) return null;
  let minX = Infinity, minZ = Infinity, maxX = -Infinity, maxZ = -Infinity;
  for (const [lx, lz] of tile.boundary) {
    const p = tileToWorld(tile, lx, lz);
    if (p.x < minX) minX = p.x;
    if (p.x > maxX) maxX = p.x;
    if (p.z < minZ) minZ = p.z;
    if (p.z > maxZ) maxZ = p.z;
  }
  return { minX, minZ, maxX, maxZ };
}

type TileStyle = 'forest' | 'road' | 'grass' | 'water' | 'cafe' | 'house' | 'highrise' | 'generic';

/** Terrain vocabulary (German/English); empty means no override. */
function terrainKind(raw: string | undefined): TileStyle | null {
  const t = (raw || '').toLowerCase().trim();
  if (!t) return null;
  if (/water|see|lake|meer|ocean|fluss|river|teich|pond/.test(t)) return 'water';
  if (/forest|wald|wood|park/.test(t)) return 'forest';
  if (/road|street|stra|weg|path|asphalt/.test(t)) return 'road';
  if (/grass|wiese|meadow|feld|field|gras/.test(t)) return 'grass';
  return null;
}

/** AV3D-1: map3d.style -> building style. Empty/unknown -> null. */
function styleKind(raw: string | undefined): TileStyle | null {
  const s = (raw || '').toLowerCase().trim();
  if (!s) return null;
  if (/tower|highrise|high-rise|hochhaus|skyscraper/.test(s)) return 'highrise';
  if (/shop|cafe|caf|store|laden|bar|restaurant/.test(s)) return 'cafe';
  if (/house|haus|home|residence|cottage|villa/.test(s)) return 'house';
  if (/generic|hall|block|building/.test(s)) return 'generic';
  return terrainKind(s); // Also accepts terrain styles such as lake or forest.
}


export function detectStyle(loc: WorldLocation): TileStyle {
  // Priority: map3d.style (AV3D-1) > terrain (AV3D-7) > name heuristic. The
  // area vocabulary (forest/road/grass) is only ever guessed for an AREA
  // location — a built place never wears a ground look because its name says
  // "park".
  const explicit = styleKind(loc.map3d?.style) ?? terrainKind(loc.terrain);
  if (explicit) return explicit;

  const n = (loc.name || '').toLowerCase();
  if (loc.map3d?.area_model) {
    if (/forest|wald|park|wood/.test(n)) return 'forest';
    if (/street|stra|road|weg|alley/.test(n)) return 'road';
    return 'grass';
  }
  if (/high-rise|highrise|tower|hochhaus|skyscraper|building/.test(n)) return 'highrise';
  if (/caf|bar|restaurant|shop|laden|store|diner/.test(n)) return 'cafe';
  if (/residence|house|haus|home|cottage|villa/.test(n)) return 'house';
  return 'generic';
}

