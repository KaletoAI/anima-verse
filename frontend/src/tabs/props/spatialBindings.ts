import { placeTransform } from '../../../../packages/scene-render/src/placeTransform'
import type { ActionDefinition, PropMarker, PropVariant, VariantBinding } from './propTypes'

export type AccessRole = 'actor' | 'partner'
export type AccessPoint = { x: number; z: number; yaw: number }
export type AccessFrame = { centreX: number; centreZ: number; groundY: number; unitsPerMetre: number }

/** Measure with the canonical snapped fix; the viewer still draws the exact rotation. */
export function propMetresPerUnit(bbox: [number, number, number],
  dims: { width_m: number; depth_m: number; height_m: number },
  rotation?: { x?: number; y?: number; z?: number }): number {
  return placeTransform({
    role: 'prop', id: '', variants: {}, level: 0,
    fix_euler: { x: rotation?.x ?? 0, y: rotation?.y ?? 0, z: rotation?.z ?? 0 },
    yaw_deg: 0, measure: 'xyz', max_m: Math.max(dims.width_m, dims.depth_m, dims.height_m),
    anchor: [0, 0], bottom_y: 0,
  }, [{ min: [0, 0, 0], max: bbox }]).outerScale
}

/** Access is already oriented: never apply the raw mesh fix a second time. */
export function accessWorldPoint(point: AccessPoint, frame: AccessFrame): [number, number, number] {
  return [frame.centreX + point.x * frame.unitsPerMetre, frame.groundY,
    frame.centreZ + point.z * frame.unitsPerMetre]
}
export function accessLocalPoint(point: [number, number, number], frame: AccessFrame) {
  return { x: (point[0] - frame.centreX) / frame.unitsPerMetre,
    z: (point[2] - frame.centreZ) / frame.unitsPerMetre }
}

/** One queueVariant patch changes geometry and references atomically. */
export function removeBoundMarker(variant: Pick<PropVariant, 'markers' | 'action_bindings'>,
  markerId: string, choice?: { replaceWith: string } | { removeBindings: true }) {
  const bindings = variant.action_bindings || []
  const referenced = bindings.some(binding => binding.marker_ids.includes(markerId))
  if (referenced && !choice) throw new Error('Explicit reference repair choice required')
  if (choice && 'replaceWith' in choice
    && (choice.replaceWith === markerId || !variant.markers.some(m => m.id === choice.replaceWith))) {
    throw new Error('Invalid replacement marker')
  }
  return {
    markers: variant.markers.filter(marker => marker.id !== markerId),
    action_bindings: bindings.flatMap(binding => {
      if (!binding.marker_ids.includes(markerId)) return [binding]
      if (choice && 'replaceWith' in choice) return [{ ...binding,
        marker_ids: [...new Set(binding.marker_ids.map(id => id === markerId ? choice.replaceWith : id))],
        validation: 'repair_required' as const }]
      return []
    }),
  }
}

/** Same local expanded-footprint rule as room_stand; this proves NO room path. */
export function bindingProblems(binding: VariantBinding, action: Pick<ActionDefinition, 'participants'>,
  markers: PropMarker[], dims: { width_m: number; depth_m: number }): string[] {
  const problems: string[] = []
  if (!binding.marker_ids.length) problems.push('Körperanker fehlt.')
  if (new Set(binding.marker_ids).size !== binding.marker_ids.length) problems.push('Körperanker doppelt gebunden.')
  for (const id of binding.marker_ids) {
    const marker = markers.find(m => m.id === id)
    if (!marker) problems.push(`Unbekannter Körperanker: ${id}`)
    else if (action.participants === 2 && (marker.capacity || 1) < 2) problems.push('Jede Paaralternative braucht mindestens 2 Plätze am selben Körperanker.')
  }
  if (!(dims.width_m > 0 && dims.depth_m > 0)) problems.push('Grundflächenmaße fehlen.')
  const roles: AccessRole[] = action.participants === 2 ? ['actor', 'partner'] : ['actor']
  if (Object.keys(binding.access_points).some(role => !roles.includes(role as AccessRole))) {
    problems.push('Nicht passende Rollenzugänge entfernen.')
  }
  for (const role of roles) {
    const point = binding.access_points[role]
    const label = action.participants === 2 ? role === 'actor' ? 'Clip A' : 'Clip B' : 'handelnde Person'
    if (!point || ![point.x, point.z, point.yaw].every(Number.isFinite)) problems.push(`Zugang ${label} fehlt oder ist ungültig.`)
    else if (Math.abs(point.x) <= dims.width_m / 2 + .30 && Math.abs(point.z) <= dims.depth_m / 2 + .30) {
      problems.push(`Zugang ${label} liegt in der Grundfläche einschließlich 0,30 m Körperabstand.`)
    }
  }
  return problems
}

/** Called only at user-edit boundaries; inspecting saved geometry never dirties it. */
export function editedBindingValidation(variant: Pick<PropVariant, 'uid' | 'markers' | 'dims' | 'action_bindings'>,
  actions: ActionDefinition[]) {
  const bindings = variant.action_bindings || []
  let changed = false
  const normalized = bindings.map(binding => {
    if (binding.validation === 'suggested') return binding
    const action = actions.find(item => item.id === binding.action_id)
    const validation = action && binding.variant_uid === variant.uid
      && (!binding.supported || !bindingProblems(binding, action, variant.markers, variant.dims).length)
      ? 'local_valid' as const : 'repair_required' as const
    if (validation === binding.validation) return binding
    changed = true
    return { ...binding, validation }
  })
  return changed ? normalized : bindings
}
