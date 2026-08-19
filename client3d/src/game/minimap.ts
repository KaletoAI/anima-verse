/**
 * The minimap projection — world METRE to canvas pixel, camera yaw to compass
 * bearing (stage 5 task 3; put on the metre world in E4 task 2).
 *
 * TWO FRAMINGS, one projection. Embodied, the map is a WINDOW around the
 * avatar: north up, the figure in the middle, and a radius of exactly the
 * distance one can see in the 3D view — capped at half the world, so a world
 * smaller than the sight radius is never zoomed out (`minimapRadius`). Without
 * a figure on the map it falls back to the WHOLE world frame (`world_bounds` of
 * § A12, the unfiltered extent over all placed locations), contain-fitted.
 * `minimapView` is the one place that chooses; every drawing path goes through
 * `worldToPx` and therefore needs to know neither which of the two it is in.
 *
 * The whole frame used to be the only framing, on the argument that a panning
 * map cannot say "how much of the world is still dark". On a metre world it
 * showed up to a kilometre and a half across 160 pixels, where a metre is a
 * tenth of a pixel and the relief is a smudge — it answered "how much of the
 * world is still unknown" and no other question. The window answers the one a
 * player standing in the world asks, and it is the same ground the eye has:
 * the scene haze closes at the radius, so the map stops exactly where sight
 * does.
 *
 * It draws the painted TERRAIN AREAS coarsely (the polygons of `/play/terrain`,
 * in list order, in their catalog colours) with the known places as dots on
 * top. Terrain is never withheld — it is the ground, and only locations hide.
 *
 * PURE like `walk.ts` and `soundtrack.ts`: no `three`, no DOM, no
 * module state, and only type-only imports. That is what lets
 * `client3d/scripts/smoke_walk_math.mjs` derive every number below by hand — the canvas
 * in `hud/Minimap.tsx` only strokes what these functions return, and `main.ts`
 * only publishes the inputs.
 */
import type { HillshadeImage } from '@anima/scene-render';
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
 * The world RELIEF as a finished shading layer, plus where its rectangle sits.
 *
 * The image comes from `hillshadeImage` (`@anima/scene-render`) — the same
 * routine, the same lamp and the same `MAP_RELIEF_Z_FACTOR` the 2D player map
 * shades with. `main.ts` computes it ONCE per height revision, not per publish:
 * the walk goes over every support point of the world, while this slice is
 * republished four times a second.
 *
 * The geometry travels with it because the image alone says nothing about where
 * it belongs: pixel `(i, j)` is the support point
 * `(origin_x + i·step_m, origin_z + j·step_m)`, row 0 being the smallest z, the
 * NORTHERNMOST line.
 */
export interface MinimapRelief {
  image: HillshadeImage;
  origin_x: number;
  origin_z: number;
  step_m: number;
}

/**
 * The bus slice `main.ts` publishes and `Minimap.tsx` draws. Everything the
 * picture needs and nothing else — the component asks no question of the
 * scene, and the scene renders no pixel of the map.
 */
export interface MinimapState {
  /** painted terrain, BOTTOM TO TOP (list order = the server's z order) */
  areas: MinimapArea[];
  /** the relief over the painted ground, or null while the world is flat or
   *  its field has not arrived */
  relief: MinimapRelief | null;
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

/**
 * FARTHEST radius of the embodied window in metres — THE SIGHT RADIUS, and
 * that is the whole of the zoom rule. There is no slider and no setting: the
 * map shows the ground one can actually see, so what stands on it is what one
 * could walk up to and look at. A world smaller than that gets `minimapRadius`
 * instead — see there.
 *
 * The number is the far end of the scene fog, `new THREE.Fog(…, 220, 520)` in
 * `scene/engine.ts` — past it the 3D view is a flat haze and a map dot would
 * promise sight that is not there. It is repeated here rather than imported
 * because `engine.ts` is `three`-bound and this module is pure (see the head of
 * the file); `scene/heightTiles.ts` derives its own 560 m from the same 520 and
 * says so. All three move together or none does.
 */
export const MINIMAP_VIEW_RADIUS_M = 520;

/**
 * How far the avatar walks before the window is re-anchored — IN PIXELS OF THE
 * MAP, not in metres of the world.
 *
 * The map follows the figure, but not per frame and not per step: re-anchoring
 * on every published position would redraw the canvas for a picture nobody can
 * tell apart. What "nobody can tell apart" means, though, is a pixel budget, and
 * a fixed metre budget only reads as one at ONE scale. At the full 520 m sight
 * radius a metre is 0.15 px on the 160 px canvas, so four metres are 0.6 px —
 * the right number. In a small world at, say, a 50 m radius a metre is 1.6 px
 * and those same four metres would be a 6.4 px jerk of the whole picture, four
 * times a second.
 *
 * So the step is 0.6 px and `minimapFollowStepM` turns it into metres for
 * whatever radius applies. The avatar dot is drawn on the ANCHOR, so it never
 * leaves the middle while the ground under it lags by less than that.
 */
export const MINIMAP_FOLLOW_STEP_PX = 0.6;

/** Fill for a kind the terrain catalog does not know — the same neutral grey
 *  the server hands out for a type without a colour
 *  (`app/core/terrain_types.py: DEFAULT_COLOR`). THE one fallback colour of
 *  this app: the ground (`scene/ground.ts`) imports it from here instead of
 *  keeping a second literal, so an unknown kind is one colour everywhere. */
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
 * The WINDOW fit: a square of `radiusM` metres in every direction around
 * `center`, filling the canvas edge to edge.
 *
 * One scale for the whole picture — `sizePx / (2 · radiusM)` — and the centre
 * lands on the canvas centre by construction: that is what puts the avatar in
 * the middle. North stays up, the window never turns with the camera; the
 * compass rose is what says where one looks.
 *
 * A point `radiusM` metres away lands exactly on the edge — `0` or `sizePx` —
 * which is one past the last pixel on the far sides. Deliberate: the mapping is
 * continuous and the canvas is the clip. Anything outside simply misses the
 * canvas and is thereby not drawn, which is all the culling this picture needs.
 *
 * No centre (no figure on the map) or a non-positive radius gives scale 0 and
 * the canvas centre, the same "nothing to draw" answer `minimapLayout` gives
 * for an empty world.
 */
export function minimapWindowLayout(center: { x: number; z: number } | null | undefined,
                                    radiusM: number,
                                    sizePx: number): MinimapLayout {
  if (!center || !(radiusM > 0)) return { scale: 0, offX: sizePx / 2, offY: sizePx / 2 };
  const scale = sizePx / (2 * radiusM);
  return { scale, offX: sizePx / 2 - center.x * scale, offY: sizePx / 2 - center.z * scale };
}

/**
 * HOW WIDE the window is for this world: the sight radius, or half the world if
 * the world is smaller than that.
 *
 *     radius = min(MINIMAP_VIEW_RADIUS_M, max(span, MINIMAP_MIN_SPAN_M) / 2)
 *
 * with `span` the LONGER axis of the world frame. The sight radius is the
 * promise the map makes about scale; the half span is what keeps the promise it
 * used to make about coverage. In a world of a kilometre and a half the first
 * one binds and the map is the ground one can see; in a 400 m world the second
 * does and the map comes out exactly as wide as the old whole-frame fit —
 * `sizePx / max(w, d)` and `sizePx / (2 · span/2)` are the same number — so no
 * small world is zoomed OUT by the window.
 *
 * The `MINIMAP_MIN_SPAN_M` floor is the same one the whole-frame fit uses, and
 * it is why the radius can never be 0: a world with one placed location has
 * `min == max` on both axes (§ A12 warns about exactly that), which would
 * otherwise divide the canvas by nothing. No bounds at all is that same case —
 * there is no world to be half of, and a 10 m window is a sane nothing.
 */
export function minimapRadius(bounds: WorldBounds | null | undefined): number {
  const span = bounds
    ? Math.max(bounds.max_x - bounds.min_x, bounds.max_z - bounds.min_z) : 0;
  return Math.min(MINIMAP_VIEW_RADIUS_M, Math.max(span, MINIMAP_MIN_SPAN_M) / 2);
}

/**
 * The follow step in METRES for a given radius: `MINIMAP_FOLLOW_STEP_PX`
 * divided by the scale that radius gives, which is the same as
 *
 *     stepM = stepPx · 2 · radiusM / sizePx.
 *
 * Constant on the CANVAS by construction — `stepM · scale` is `stepPx` for
 * every radius — which is the whole point of counting the step in pixels.
 */
export function minimapFollowStepM(radiusM: number,
                                   sizePx: number = MINIMAP_SIZE_PX): number {
  return MINIMAP_FOLLOW_STEP_PX * 2 * radiusM / sizePx;
}

/**
 * WHICH OF THE TWO FRAMINGS applies — the one decision, made once per redraw.
 *
 * A figure on the map means the embodied window around it; without one there is
 * nothing to centre on and the whole world frame is what is left. Every drawing
 * path takes the layout from here, so terrain, relief, places and the avatar
 * can never be framed differently from one another.
 *
 * The radius comes from `minimapRadius` — the same call `main.ts` derives its
 * follow step from, so the window's width and the step that moves it are never
 * two opinions.
 */
export function minimapView(avatar: { x: number; z: number } | null | undefined,
                            bounds: WorldBounds | null | undefined,
                            sizePx: number): MinimapLayout {
  return avatar
    ? minimapWindowLayout(avatar, minimapRadius(bounds), sizePx)
    : minimapLayout(bounds, sizePx);
}

/**
 * Where the window is centred, given where it was centred and where the avatar
 * stands now: the old anchor while the figure has not walked more than `stepM`,
 * a fresh one once it has. The step comes from `minimapFollowStepM` over the
 * radius the window actually has — it is a pixel budget, not a metre one.
 *
 * Returning the PREVIOUS object identity on a small move is the point — the
 * publisher puts the anchor into its redraw signature, so an unchanged anchor
 * is an unchanged picture and costs neither a publish nor a canvas.
 *
 * No position (no figure yet, or the mode was left) clears the anchor: a window
 * kept around a metre from minutes ago would be worse than none.
 */
export function minimapAnchor(prev: MinimapDot | null,
                              pos: { x: number; z: number } | null | undefined,
                              stepM: number): MinimapDot | null {
  if (!pos) return null;
  if (prev && Math.hypot(pos.x - prev.x, pos.z - prev.z) <= stepM) return prev;
  return { x: pos.x, z: pos.z };
}

/**
 * A world point in canvas pixels. `py` grows with the world's z, and north is
 * `-z`, so north ends up UP on the canvas without any extra flip.
 *
 * THE one world→pixel routine of the minimap, whichever framing the layout came
 * from — the polygons, the relief rectangle, the place dots and the avatar all
 * go through here. That is what makes the framing a single decision instead of
 * four agreeing ones.
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
 * built from the centre `pos_x`/`pos_z`, the rotation `yaw_deg` and — since
 * contract v6 — THE DRAWN OUTLINE `boundary` (with `plan_width_m`, its derived
 * bounding-box width, along for the texture scale). None of them is in `map3d`
 * on the worldmap row — they sit on the location ROW — so the layout signature
 * that watches `map3d` + the room layouts cannot see any of them, and a place
 * moved, turned or REDRAWN in the world editor kept its tile standing at the
 * old metres in every running client. The server meanwhile judges walking,
 * entering and leaving against the new footprint, so the two sides disagreed
 * about where the walls of a place are.
 *
 * THE OUTLINE POINTS GO IN, not just its width: v6 lets an author reshape a
 * place without changing the bounding box at all — pulling a notch into a
 * square keeps `plan_width_m` exactly where it was, and a signature made of the
 * old four numbers would never notice.
 *
 * The numbers go in verbatim rather than rounded: they arrive rounded from the
 * server (`build_worldmap_payload`), and a rounding of our own would be a
 * second opinion about when a place has moved. `null`/`undefined` stringify to
 * themselves and are thereby their own state — an unplaced location is not a
 * location at the origin, and a location with no area is not one with a
 * boundary.
 */
export function footprintSignature(loc: {
  pos_x: number | null; pos_z: number | null;
  yaw_deg?: number; plan_width_m?: number | null;
  boundary?: [number, number][] | null;
}): string {
  const outline = loc.boundary
    ? loc.boundary.map(([x, z]) => `${x} ${z}`).join(' ')
    : `${loc.boundary}`;
  return `${loc.pos_x},${loc.pos_z},${loc.yaw_deg},${loc.plan_width_m},${outline}`;
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
