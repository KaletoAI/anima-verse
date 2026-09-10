/**
 * PropSpriteLayer — "Props from above": every previewed prop as its MODEL
 * seen straight down, turned as it stands, sized in true metres. The
 * counterpart of the map's roof view for the things that are not buildings:
 * a hand-placed bench, the trees of a scattered wood, the lamps along a road.
 *
 * ONE picture per mesh URL (`renderPropTopDown`, cached for the session and
 * handed out by `usePropSprites`), ONE `<image>` per instance: the
 * per-instance work is a transform string and a size, nothing else — the
 * distinct meshes are few, the instances many.
 *
 * A sprite is a VIEW of a placement the shared package already decided (§ A9):
 * the anchor is the sampler's point, the turn the sampler's yaw, the variant
 * the sampler's variant. Nothing here moves a prop; `propSpriteMath` holds
 * the arithmetic and `scripts/smoke_prop_sprite_math.mjs` pins it — the
 * rotation is derived from the direction pin of `WorldPropLayer`, which is
 * the check by eye: pin and picture point the same way, always.
 *
 * Geometry only — no text, no `t()`. What the user reads about this layer
 * (the switch, the zoom gate, the budget note) lives in the Display panel.
 */
import type { PropSprite } from '../world/topDownSnapshot'
import { useMapView } from './MapCanvas'
import { worldToScreen } from './mapMath'
import type { ScreenPt } from './mapMath'
import { propSpriteAnchorShift, propSpriteSizeM, propSpriteTransform } from './propSpriteMath'
import type { PropSpriteMap } from './usePropSprites'

/** One thing to draw from above: where it stands, how it is turned, which
 *  mesh it shows and how tall it is meant to be. */
export interface PropSpriteInstance {
  key: string
  x: number
  z: number
  yawDeg: number
  url: string
  targetHeightM: number
  /** What the point IS to the mesh: its file ORIGIN (a scatter or along
   *  instance, as the 3D client instances it) or its box CENTRE (a world
   *  prop, as `place()` hangs it). The picture is centred on the box, so an
   *  origin-anchored sprite is shifted by the box's centre offset
   *  (`propSpriteAnchorShift`). */
  anchor: 'origin' | 'centre'
}

/** ONE sprite: the picture centred on `p`, sized in map pixels from the
 *  model's box and its target height, turned about `p` by the layer's one
 *  rotation. Inert to the pointer — a sprite is a picture of a placement,
 *  and whatever handles clicks under it (a marker, the canvas) keeps them. */
export function PropSpriteImage({ p, yawDeg, sprite, targetHeightM, pxPerM }: {
  p: ScreenPt
  yawDeg: number
  sprite: PropSprite
  targetHeightM: number
  pxPerM: number
}) {
  const size = propSpriteSizeM(sprite, targetHeightM)
  const side = size.fieldM * pxPerM
  if (!(side > 0)) return null
  const half = side / 2
  return (
    <image href={sprite.url} x={-half} y={-half} width={side} height={side}
      transform={propSpriteTransform(p.x, p.y, yawDeg)} pointerEvents="none" />
  )
}

/** Every instance whose picture has landed, as a sprite; the rest draw
 *  nothing here (their dot stays, see `TerrainLayer`). Off-screen sprites are
 *  skipped by their own extent, so a pan over empty ground costs nothing. */
export function PropSpriteLayer({ instances, sprites }: {
  instances: readonly PropSpriteInstance[]
  sprites: PropSpriteMap
}) {
  const { view, w, h } = useMapView()
  if (!w || !h || !instances.length) return null
  return (
    <g pointerEvents="none">
      {instances.map((inst) => {
        const sprite = sprites.get(inst.url)
        if (!sprite) return null
        const size = propSpriteSizeM(sprite, inst.targetHeightM)
        // The picture's centre in world metres: the point, plus — for a mesh
        // standing on its origin — its box centre turned with the instance.
        const shift = propSpriteAnchorShift(sprite.cxM, sprite.czM, size.scale,
          inst.yawDeg, inst.anchor)
        const s = worldToScreen(inst.x + shift.dx, inst.z + shift.dz, view, w, h)
        // Half the picture's diagonal: a sprite standing at 45° is not dropped
        // just before its corner would leave the screen.
        const r = (size.fieldM * view.pxPerM) * Math.SQRT1_2
        if (s.x + r < 0 || s.y + r < 0 || s.x - r > w || s.y - r > h) return null
        return (
          <PropSpriteImage key={inst.key} p={s} yawDeg={inst.yawDeg} sprite={sprite}
            targetHeightM={inst.targetHeightM} pxPerM={view.pxPerM} />
        )
      })}
    </g>
  )
}
