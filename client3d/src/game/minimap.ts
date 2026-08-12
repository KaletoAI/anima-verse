/**
 * The minimap projection — world METRE to canvas pixel, camera yaw to compass
 * bearing (stage 5 task 3; put on the metre world in E4 task 2).
 *
 * The minimap shows the WHOLE world frame at once (`world_bounds` of § A12, the
 * unfiltered extent over all placed locations) fitted into a square canvas,
 * north up, with no scrolling and no zoom of its own. That is deliberate: a map
 * that panned with the avatar would answer "where am I looking" but never "how
 * much of the world is still dark", and the fog of war is what this picture is
 * about.
 *
 * It draws the painted TERRAIN AREAS coarsely (the polygons of `/play/terrain`,
 * in list order, in their catalog colours) with the known places as dots on
 * top. Terrain is never fogged — it is the ground, and only locations hide.
 *
 * PURE like `walk.ts`, `soundtrack.ts` and `fog.ts`: no `three`, no DOM, no
 * module state, and only type-only imports. That is what lets
 * `client3d/scripts/smoke_walk_math.mjs` derive every number below by hand — the canvas
 * in `hud/Minimap.tsx` only strokes what these functions return, and `main.ts`
 * only publishes the inputs.
 */
import type { WorldBounds } from '../types';

/** A world point on the ground plane, `[x, z]` in metres — the shape the
 *  terrain payload uses. */
export type Point2 = [number, number];

/** One painted area, ready to fill: the ring in world metres and the colour
 *  the terrain CATALOG gives its kind. The minimap invents no colour of its
 *  own — see `terrainColor`. */
export interface MinimapArea {
  polygon: Point2[];
  color: string;
}

/** A known place, as a dot. Metre centre, nothing else — the minimap is not a
 *  floor plan. */
export interface MinimapDot {
  x: number;
  z: number;
}

/**
 * The bus slice `main.ts` publishes and `Minimap.tsx` draws. Everything the
 * picture needs and nothing else — the component asks no question of the
 * scene, and the scene renders no pixel of the map.
 */
export interface MinimapState {
  /** painted terrain, BOTTOM TO TOP (list order = the server's z order) */
  areas: MinimapArea[];
  /** the places the avatar knows about */
  locations: MinimapDot[];
  /** the avatar's metre position, or null while no figure stands on the map */
  avatar: MinimapDot | null;
  /** camera yaw in radians — the avatar looks where the follow cam looks */
  yaw: number;
  /** the world frame in metres; null when nothing is placed at all */
  bounds: WorldBounds | null;
}

/** Where the world lands on the canvas: `scale` pixels per METRE, plus the
 *  pixel position of the world ORIGIN (x = 0, z = 0). The frame's minima are
 *  absorbed into the offsets, so placing a point needs the layout alone — see
 *  `worldToPx`. */
export interface MinimapLayout {
  scale: number;
  offX: number;
  offY: number;
}

/** `localStorage` key of the "show the minimap" switch in the game menu.
 *  Default ON: the map is a reading aid, not a mode. */
export const MINIMAP_PREF_KEY = 'av3d.minimap';

/** Edge length of the canvas in CSS pixels. Square, because the frame it shows
 *  can be wide or tall and a fixed aspect would crop one of them. */
export const MINIMAP_SIZE_PX = 160;

/** Smallest frame the map will show, in metres. A world with ONE placed
 *  location has a zero-wide extent, and dividing the canvas by it would give
 *  an infinite scale; ten metres is roughly a house and keeps the single dot
 *  in the middle of a sane window. */
export const MINIMAP_MIN_SPAN_M = 10;

/** Fill for a kind the terrain catalog does not know — the same neutral grey
 *  the server hands out for a type without a colour. */
export const TERRAIN_FALLBACK_COLOR = '#888888';

/**
 * "Contain" fit of the whole frame into a square canvas, centred on the
 * shorter axis. The longer axis decides the scale, so no part of the world is
 * ever cut off and the frame stays still while the fog lifts — the bounds are
 * computed over ALL placed locations, discovered or not.
 *
 * `bounds` null (nothing placed at all) gives scale 0 and the canvas centre:
 * there is no map, so nothing is drawn.
 */
export function minimapLayout(bounds: WorldBounds | null | undefined,
                              sizePx: number): MinimapLayout {
  if (!bounds) return { scale: 0, offX: sizePx / 2, offY: sizePx / 2 };
  const cx = (bounds.min_x + bounds.max_x) / 2;
  const cz = (bounds.min_z + bounds.max_z) / 2;
  const w = Math.max(bounds.max_x - bounds.min_x, MINIMAP_MIN_SPAN_M);
  const d = Math.max(bounds.max_z - bounds.min_z, MINIMAP_MIN_SPAN_M);
  const scale = Math.min(sizePx / w, sizePx / d);
  // Centred on the world's MIDPOINT, which is what makes the clamped span of a
  // degenerate frame open symmetrically around the one thing that is placed.
  return { scale, offX: sizePx / 2 - cx * scale, offY: sizePx / 2 - cz * scale };
}

/**
 * A world point in canvas pixels. `py` grows with the world's z, and north is
 * `-z`, so north ends up UP on the canvas without any extra flip.
 */
export function worldToPx(p: { x: number; z: number },
                          layout: MinimapLayout): { px: number; py: number } {
  return { px: layout.offX + p.x * layout.scale, py: layout.offY + p.z * layout.scale };
}

/**
 * The DOTS of a location list, as one string — the redraw signature of the
 * places on the map.
 *
 * The publisher in `main.ts` only redraws the minimap when its signature
 * changes, and the places used to enter that signature by their COUNT alone.
 * A count answers "has one been discovered", never "has one moved": since the
 * seamless world a location can be dragged to another metre without the list
 * growing, and the map then kept a dot at the old spot until something else
 * (a step, an orbit) happened to move the signature.
 *
 * Id AND point, because both change the picture on their own: a place that
 * moves is a dot in a new spot, and one place replaced by another at the very
 * same metre is a different place under the same dot — the tooltip and the
 * fog reveal that follow it are not the same. Unplaced (`null`) stringifies to
 * "null" and is thereby its own state as well: the dot is not drawn, and a
 * place that gets a position must bring it back.
 *
 * Computed once per list — when `main.ts` TAKES a payload — never per redraw
 * tick: the publisher runs four times a second and would otherwise walk every
 * known location of the world for a string that only a poll can change.
 */
export function locationsSignature(
  locations: { id: string; pos_x: number | null; pos_z: number | null }[],
): string {
  return locations.map((l) => `${l.id}:${l.pos_x},${l.pos_z}`).join(';');
}

/**
 * The GEOMETRY of one location, as one string — the rebuild signature of the
 * tile that stands on it.
 *
 * The same lesson as above, for the other consumer (finding B13). A tile is
 * built from exactly four numbers (§ A1.1): the centre `pos_x`/`pos_z`, the
 * rotation `yaw_deg` and the footprint edge `plan_width_m`. None of them is in
 * `map3d` — they sit on the location ROW — so the layout signature that
 * watches `map3d` + the room layouts cannot see any of them, and a place moved
 * or turned in the world editor kept its tile standing at the old metre in
 * every running client. The server meanwhile judges walking, entering and
 * leaving against the new footprint, so the two sides disagreed about where
 * the walls of a place are.
 *
 * The numbers go in verbatim rather than rounded: they arrive rounded from the
 * server (`build_worldmap_payload`), and a rounding of our own would be a
 * second opinion about when a place has moved. `null`/`undefined` stringify to
 * themselves and are thereby their own state — an unplaced location is not a
 * location at the origin.
 */
export function footprintSignature(loc: {
  pos_x: number | null; pos_z: number | null;
  yaw_deg?: number; plan_width_m?: number | null;
}): string {
  return `${loc.pos_x},${loc.pos_z},${loc.yaw_deg},${loc.plan_width_m}`;
}

/**
 * Camera yaw (radians) → compass bearing in degrees, 0 = north and rising
 * CLOCKWISE, normalised into [0, 360).
 *
 * The sign is read off the code, not chosen: `engine.ts` puts the camera at
 * `target + (sin yaw, _, cos yaw) * dist`, so it looks along
 * `(-sin yaw, -cos yaw)` in XZ — the very forward vector `walkDir` uses. North
 * is `-z` and east is `+x`. A bearing of a direction `(dx, dz)` is
 * `atan2(dx, -dz)`, and substituting the forward vector gives
 * `atan2(-sin yaw, cos yaw) = -yaw`: the yaw runs counter-clockwise on the
 * compass. Hence the minus below, and hence yaw π/2 (looking west) is 270.
 */
export function yawToCompassDeg(yaw: number): number {
  const deg = -yaw * 180 / Math.PI;
  return ((deg % 360) + 360) % 360;
}

/**
 * Colour of a terrain kind — looked up in the world's own TYPE CATALOG
 * (`/play/terrain → types[].color`), never guessed.
 *
 * This used to be a regular-expression table over a de/en vocabulary, with the
 * fills copied from the procedural textures. That table was a second source of
 * truth for something the world already declares per kind, and it could not
 * know a kind an admin had just invented. Now the map is drawn in the colours
 * the catalog gives, and a kind that is not in it gets ONE neutral grey.
 *
 * `colors` maps the lower-cased kind to `#rrggbb`; `main.ts` builds it from
 * the terrain payload.
 */
export function terrainColor(kind: string | undefined,
                             colors: Record<string, string> | Map<string, string>
): string {
  const key = (kind || '').toLowerCase().trim();
  if (!key) return TERRAIN_FALLBACK_COLOR;
  const hit = colors instanceof Map ? colors.get(key) : colors[key];
  return hit || TERRAIN_FALLBACK_COLOR;
}
