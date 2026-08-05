/**
 * The minimap projection — cell to canvas pixel, camera yaw to compass bearing
 * (stage 5, task 3).
 *
 * The minimap shows the WHOLE world frame at once (`grid_bounds` of § A12, the
 * unfiltered extent over all placed locations) fitted into a square canvas,
 * north up, with no scrolling and no zoom of its own. That is deliberate: a
 * map that panned with the avatar would answer "where am I looking" but never
 * "how much of the world is still dark", and the fog of war is exactly what
 * this stage is about.
 *
 * PURE like `walk.ts`, `soundtrack.ts` and `fog.ts`: no `three`, no DOM, no
 * module state and one type-only import. That is what lets
 * `scripts/smoke_walk_math.mjs` derive every number below by hand — the canvas
 * in `hud/Minimap.tsx` only strokes what these functions return, and `main.ts`
 * only publishes the inputs.
 */
import type { GridBounds } from './fog';

/** A known cell of the map, with the surface kind its tile was built from
 *  (`tiles.ts gridSurfaceKind` — the server's open vocabulary, else the
 *  normalised legacy style). */
export interface MinimapCell {
  x: number;
  y: number;
  terrain: string;
}

/**
 * The bus slice `main.ts` publishes and `Minimap.tsx` draws. Everything the
 * picture needs and nothing else — the component asks no question of the
 * scene, and the scene renders no pixel of the map.
 */
export interface MinimapState {
  /** every cell the avatar knows about (the fog covers the rest) */
  cells: MinimapCell[];
  /** the avatar's grid cell, or null while no figure stands on the map */
  avatar: { x: number; y: number } | null;
  /** camera yaw in radians — the avatar looks where the follow cam looks */
  yaw: number;
  /** the world frame; null when nothing is placed at all */
  bounds: GridBounds | null;
}

/** Where a cell lands on the canvas: `scale` pixels per cell, plus the pixel
 *  position of the grid ORIGIN (cell 0,0's top-left corner). The frame's
 *  `min_x`/`min_y` are absorbed into the offsets, so placing a cell needs the
 *  layout alone — see `cellToPx`. */
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

/**
 * "Contain" fit of the whole frame into a square canvas, centred on the
 * shorter axis. The longer axis decides the scale, so no cell is ever cut off
 * and the frame stays still while the fog lifts — the bounds are computed over
 * ALL placed locations, discovered or not.
 *
 * `bounds` null (nothing placed at all) gives scale 0 and the canvas centre:
 * there is no map, so nothing is drawn.
 */
export function minimapLayout(bounds: GridBounds | null | undefined,
                              sizePx: number): MinimapLayout {
  if (!bounds) return { scale: 0, offX: sizePx / 2, offY: sizePx / 2 };
  const cols = bounds.max_x - bounds.min_x + 1;
  const rows = bounds.max_y - bounds.min_y + 1;
  const scale = Math.min(sizePx / cols, sizePx / rows);
  return {
    scale,
    offX: (sizePx - cols * scale) / 2 - bounds.min_x * scale,
    offY: (sizePx - rows * scale) / 2 - bounds.min_y * scale,
  };
}

/**
 * The CENTRE of a cell in canvas pixels. `py` grows with the grid's y, and
 * north is `-gy` (`walk.ts stepDirection`), so north ends up UP on the canvas
 * without any extra flip.
 *
 * Fractional coordinates are legal — a caller may publish a position between
 * two cells and gets the point between the two centres.
 */
export function cellToPx(cell: { x: number; y: number },
                         layout: MinimapLayout): { px: number; py: number } {
  return {
    px: layout.offX + (cell.x + 0.5) * layout.scale,
    py: layout.offY + (cell.y + 0.5) * layout.scale,
  };
}

/**
 * Camera yaw (radians) → compass bearing in degrees, 0 = north and rising
 * CLOCKWISE, normalised into [0, 360).
 *
 * The sign is read off the code, not chosen: `engine.ts` puts the camera at
 * `target + (sin yaw, _, cos yaw) * dist`, so it looks along
 * `(-sin yaw, -cos yaw)` in XZ — the very forward vector `walkDir` uses.
 * `gridToWorld` maps `+gy` to `+z` and `stepDirection` calls `-gy` north, so
 * north is `-z` and east is `+x`. A bearing of a direction `(dx, dz)` is
 * `atan2(dx, -dz)`, and substituting the forward vector gives
 * `atan2(-sin yaw, cos yaw) = -yaw`: the yaw runs counter-clockwise on the
 * compass. Hence the minus below, and hence yaw π/2 (looking west) is 270.
 */
export function yawToCompassDeg(yaw: number): number {
  const deg = -yaw * 180 / Math.PI;
  return ((deg % 360) + 360) % 360;
}

/**
 * Colour of a surface kind on the minimap. NOT a palette of its own: every
 * value here is the base fill of the matching procedural surface texture in
 * `scene/textures.ts` (grass `#7fa055`, asphalt `#5a5e63`, water `#3f7fb8`,
 * pavers `#b8ac97`), so the map is drawn in the colours the world is.
 *
 * The vocabulary mirrors `tiles.ts terrainKind` — tolerant, de/en, and in the
 * same order — extended by sand and rock, which are open server surface kinds
 * without a procedural texture of their own and therefore borrow the pavers
 * and the asphalt fill. `forest` shares the grass fill because its tile does
 * too (`tiles.ts fallbackFor`). Everything else — the building styles
 * ('house', 'cafe', 'highrise', 'generic'), an unknown kind, the empty string
 * — is the pavers default, so a built-up cell reads as pale stone against the
 * green.
 */
export function terrainColor(kind: string | undefined): string {
  const t = (kind || '').toLowerCase().trim();
  if (/water|see|lake|meer|ocean|fluss|river|teich|pond/.test(t)) return '#3f7fb8';
  if (/forest|wald|wood|park/.test(t)) return '#7fa055';
  if (/road|street|stra|weg|path|asphalt/.test(t)) return '#5a5e63';
  if (/grass|wiese|meadow|feld|field|gras/.test(t)) return '#7fa055';
  if (/sand|beach|strand|dune|dü/.test(t)) return '#b8ac97';
  if (/rock|stone|fels|stein|gravel|kies|cliff/.test(t)) return '#5a5e63';
  return '#b8ac97';
}
