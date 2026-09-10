/**
 * propSpriteMath — the pure arithmetic of the map's "Props from above" layer
 * (no React, no DOM, no three.js): how big a top-down prop sprite is drawn,
 * how it is TURNED so that it faces the way the prop's direction pin points,
 * and which mesh URL a placement or a scatter instance shows.
 *
 * A sprite is a VIEW of a placement the shared package already decided
 * (§ A9): nothing in here moves a prop or picks a variant — the sampler's
 * `yaw` and `variant` are read, never re-derived.
 *
 * THE ROTATION, derived once and pinned in
 * `scripts/smoke_prop_sprite_math.mjs`:
 *
 *   · `worldToScreen` maps +x to the right and +z DOWN (no flip);
 *   · `WorldPropLayer` draws the direction pin at
 *       (px − F·sin(yaw), py − F·cos(yaw)),
 *     i.e. along the screen vector (−sin yaw, −cos yaw) — which is
 *     R_y(yaw)·(0, 0, −1), the model's LOCAL −z turned by the yaw exactly as
 *     `placeModelSpec` turns it;
 *   · `renderPropTopDown` looks straight down with `up = −z` (as the roof
 *     snapshots do): image top = local −z, image right = local +x, so the
 *     unrotated picture's top is the screen vector (0, −1);
 *   · SVG `rotate(a)` on a y-down screen turns (0, −1) into (sin a, −cos a),
 *     and that equals the pin vector iff a = −yaw.
 *
 * Hence `rotate(−yaw_deg)`, the same sign (and the same reason) as the
 * footprint squares of `PlacementLayer`.
 *
 * THE SIZE is the client's own scale law for a scattered mesh
 * (`scatterLod.scatterTargetH` → uniform scale to the target height): the
 * renderer measures the model's box at scale 1, the layer scales it until it
 * is `target height / model height` and draws the width and depth that come
 * out — in true metres, so a sprite covers on the map exactly the ground its
 * prop covers.
 */
import { pickVariant } from '@anima/scene-render'
import { scatterVariantMaps } from './mapTypes'
import type { TerrainAlongEntry, TerrainScatterEntry, WorldProp } from './mapTypes'

/** Sprites ONE render may draw, over every source together. Beyond it the
 *  scatter instances are thinned to their share (`scatterPreviewShares`,
 *  the dots' own key); the world props are never thinned — they are a few
 *  hundred at most, and each one was put down by hand. */
export const PROP_SPRITE_MAX = 2000

/** How much wider than the model's larger horizontal edge the square picture
 *  is — 5 % in total, so a mesh whose corner touches its own box edge is not
 *  clipped by antialiasing at the picture's rim. */
export const PROP_SPRITE_MARGIN = 0.05

/** The flat target height for a mesh nobody sized — the 3D client's
 *  `SCATTER_MODEL_HEIGHT_M`, so the map and the world fall back to the same
 *  size. */
export const PROP_SPRITE_FALLBACK_HEIGHT_M = 2

/** What `renderPropTopDown` measures: the model's bounding box at scale 1,
 *  in metres, AFTER the loader and before any placement. */
export interface PropSpriteDims {
  widthM: number
  heightM: number
  depthM: number
}

/** Side of the SQUARE picture at scale 1: the larger horizontal edge plus
 *  the margin. 0 for junk (a model with no horizontal extent draws nothing). */
export function propSpriteFieldM(widthM: number, depthM: number): number {
  const w = Number(widthM)
  const d = Number(depthM)
  const edge = Math.max(Number.isFinite(w) ? w : 0, Number.isFinite(d) ? d : 0)
  return edge > 0 ? edge * (1 + PROP_SPRITE_MARGIN) : 0
}

/** `target / model height` — the uniform scale the 3D client plants the mesh
 *  by. 0 when either number is not a height, so a caller multiplies into
 *  nothing instead of into NaN. */
export function propSpriteScale(bboxHeightM: number, targetHeightM: number): number {
  const h = Number(bboxHeightM)
  const t = Number(targetHeightM)
  if (!(h > 0) || !(t > 0)) return 0
  return t / h
}

/** The sprite as drawn, in metres: its width and depth (the ground the prop
 *  covers), the side of its square picture, and the scale that produced
 *  them. */
export function propSpriteSizeM(dims: PropSpriteDims, targetHeightM: number): {
  widthM: number; depthM: number; fieldM: number; scale: number
} {
  const scale = propSpriteScale(dims.heightM, targetHeightM)
  return {
    widthM: dims.widthM * scale,
    depthM: dims.depthM * scale,
    fieldM: propSpriteFieldM(dims.widthM, dims.depthM) * scale,
    scale,
  }
}

/** The target height of a scatter or along row — `scatterTargetH` of the 3D
 *  client, mirrored: the authored `height_m` wins, else the prop's own
 *  library height (`prop_height_m`), else the flat fallback. */
export function propSpriteTargetH(entryH?: number, propH?: number): number {
  if (Number(entryH) > 0) return Number(entryH)
  if (Number(propH) > 0) return Number(propH)
  return PROP_SPRITE_FALLBACK_HEIGHT_M
}

/** WHERE THE PICTURE'S CENTRE STANDS relative to the placement point, in
 *  world metres, for a mesh placed ON ITS FILE ORIGIN — a scatter or along
 *  instance (`ground.ts groundedGeometry` scales and lifts, never recentres).
 *  The box centre's offset from the origin (`cxM`, `czM` at scale 1) is
 *  scaled with the instance and turned by its yaw, with the contract's own
 *  rotation (the § A1.1 mapping `mapMath` states: `x = lx·cos + lz·sin`,
 *  `z = −lx·sin + lz·cos`, i.e. local +z at yaw 90° faces +x). A WORLD PROP
 *  hangs on its box centre (`place()` recentres) and shifts by nothing —
 *  the caller passes `anchor: 'centre'` and gets (0, 0). */
export function propSpriteAnchorShift(cxM: number, czM: number, scale: number,
  yawDeg: number, anchor: 'origin' | 'centre'): { dx: number; dz: number } {
  if (anchor === 'centre') return { dx: 0, dz: 0 }
  const lx = Number(cxM) * scale
  const lz = Number(czM) * scale
  if (!Number.isFinite(lx) || !Number.isFinite(lz)) return { dx: 0, dz: 0 }
  const rad = (Number(yawDeg) || 0) * Math.PI / 180
  return {
    dx: lx * Math.cos(rad) + lz * Math.sin(rad),
    dz: -lx * Math.sin(rad) + lz * Math.cos(rad),
  }
}

/** The SVG rotation that turns the picture's top (local −z) onto the
 *  direction pin of `WorldPropLayer` — see the module docstring. A yaw that
 *  is not a number turns nothing. */
export function propSpriteRotateDeg(yawDeg: number): number {
  const y = Number(yawDeg)
  if (!Number.isFinite(y) || y === 0) return 0
  return -y
}

/** The `transform` of one sprite: to its anchor, then the turn ABOUT it. */
export function propSpriteTransform(px: number, py: number, yawDeg: number): string {
  return `translate(${px} ${py}) rotate(${propSpriteRotateDeg(yawDeg)})`
}

/** How many meshes a row's prop has to choose between — what every sampler
 *  is told as `variantCount`, so the preview's instances carry the very
 *  variant the 3D client draws (the shared formula over the cell seed). */
export function scatterVariantCount(entry: TerrainScatterEntry | TerrainAlongEntry): number {
  return scatterVariantMaps(entry).length
}

/** The mesh URL ONE scatter instance shows — the client's rule
 *  (`ground.ts`, the `kinds` of a row): the tier map at the instance's
 *  variant position, its `full` tier; the PRIMARY position alone falls back
 *  to the authored `model` URL. '' = no mesh, no sprite (a tuft). */
export function scatterModelUrl(entry: TerrainScatterEntry | TerrainAlongEntry,
  variant: number | undefined): string {
  const maps = scatterVariantMaps(entry)
  const n = maps.length
  const raw = Number(variant)
  const i = Number.isFinite(raw) && n > 0 ? (((Math.floor(raw) % n) + n) % n) : 0
  return pickVariant(maps[i], 'full') || (i === 0 && entry.model ? entry.model : '')
}

/** The mesh URL a WORLD PROP placement shows — the server's own rule
 *  (`world_props._prop_facts`): list position 0 is the bare model URL,
 *  every other position names its STORE index (`variant_indices`); the
 *  position is the authored `variant`, or the server's `variant_auto` for
 *  "Auto", wrapped modulo the published count as the client wraps it
 *  (`pickModelVariant`). '' when the prop is gone. */
export function worldPropModelUrl(wp: WorldProp): string {
  if (wp.missing || !wp.prop_id) return ''
  const base = `/assets/props/${encodeURIComponent(wp.prop_id)}/model`
  const n = Number(wp.variant_count)
  const rawPos = typeof wp.variant === 'number' ? wp.variant : Number(wp.variant_auto)
  let pos = Number.isFinite(rawPos) ? Math.floor(rawPos) : 0
  if (Number.isFinite(n) && n > 0) pos = ((pos % n) + n) % n
  const store = wp.variant_indices?.[pos]
  return pos > 0 && typeof store === 'number'
    ? `${base}?variant=${store}&tier=full`
    : `${base}?tier=full`
}
