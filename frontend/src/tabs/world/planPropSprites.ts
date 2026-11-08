/**
 * planPropSprites — which scene-payload spec belongs to which prop the floor
 * plan draws, for the plan's "Props from above" (the map's sprite layer,
 * applied to `layout.props`). Pure, no React, no three.js.
 *
 * The plan has no mesh URL of its own and must not build one: WHICH variant
 * a placement shows is decided by the server (`scene_recipe._variant_index`,
 * the hash of an "Auto" placement lives there alone). The scene payload the
 * plan tab already holds (`useScenePreview`, the same response the 3D preview
 * renders) carries that decision per placement, so the plan reads it there.
 *
 * THE MATCH (server side, `scene_recipe._prop_models` over
 * `room_recipe._join_placements`): every dict in a room's `layout.props`
 * becomes exactly ONE placement, in list order, and every placement exactly
 * ONE spec with `role 'prop'`, `measure 'xyz'` and that room's `room_id`.
 * Scattered copies (the yard) are appended AFTER all of them, and the door
 * and window leaves are `measure 'fit'` — so the n-th `xyz` spec of a room IS
 * `layout.props[n]`. `models[].id` is the PROP id, shared by every copy, so
 * it cannot name a placement on its own; it is the cross-check instead: while
 * the debounced payload still describes the draft before the last edit
 * (a prop deleted or reordered), the n-th spec may name another prop, and
 * then this answers nothing and the plan keeps the plain footprint.
 */
import { pickModelVariant } from '@anima/scene-render'
import type { SceneModelSpec } from '@anima/scene-render'

/** The placement specs of a payload, per `room_id`, in payload order. */
export type PlanPropSpecs = ReadonlyMap<string, readonly SceneModelSpec[]>

const NO_SPECS: PlanPropSpecs = new Map()

/** Group the payload's PLACEMENT specs by room — doors and windows (`fit`)
 *  and every non-prop model left out. */
export function groupPlacementSpecs(models: readonly SceneModelSpec[] | null | undefined): PlanPropSpecs {
  if (!models?.length) return NO_SPECS
  const out = new Map<string, SceneModelSpec[]>()
  for (const m of models) {
    if (m.role !== 'prop' || m.measure !== 'xyz') continue
    const room = m.room_id || ''
    let list = out.get(room)
    if (!list) { list = []; out.set(room, list) }
    list.push(m)
  }
  return out
}

/** The spec of `layout.props[index]` in room `roomId`, or null when the
 *  payload does not (yet) describe that very placement. A stored placement
 *  `id` must agree too when both sides have one. */
export function placementSpecOf(specs: PlanPropSpecs, roomId: string, index: number,
  prop: { prop_id?: string; id?: string }): SceneModelSpec | null {
  const spec = specs.get(roomId)?.[index]
  if (!spec || !prop.prop_id || spec.id !== prop.prop_id) return null
  if (prop.id && spec.placement_id && spec.placement_id !== prop.id) return null
  return spec
}

/** The mesh URL the sprite of a placement spec is rendered from: the `full`
 *  tier of the variant the SERVER resolved for it. '' = no mesh (a
 *  placeholder box) — no picture, the footprint stays. */
export function placementSpecModelUrl(spec: SceneModelSpec): string {
  return pickModelVariant(spec, 'full') || ''
}
