import type { ActionDefinition, ActionEffect, ActionRequirement, PropActionIssue } from './propTypes'
import type { PoseGroupSpec } from '../world/placeTypes'

export interface ActionPresentation {
  key: string; label?: string; label_de?: string; group?: string
  solo?: boolean; animation?: string; places?: number; yaw_offset?: number
}
export interface ActionCatalog {
  status: 'loading' | 'ready' | 'error'
  stats: string[]
  conditions: { name: string; label: string; icon?: string }[]
  poses: ActionPresentation[]
  kinds: string[]
  pairKinds: string[]
  groups: Record<string, PoseGroupSpec>
}
export type ActionPreset = 'sit' | 'lie' | 'sleep' | 'coffee' | 'pair'
/** randomUUID is secure-context-only; getRandomValues also works on HTTP LANs. */
export function actionId(): string {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID()
  const bytes = crypto.getRandomValues(new Uint8Array(16))
  bytes[6] = (bytes[6] & 0x0f) | 0x40
  bytes[8] = (bytes[8] & 0x3f) | 0x80
  const hex = Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}

export function createRequirement(catalog: ActionCatalog): ActionRequirement | null {
  if (catalog.stats.length) return { id: actionId(), target: 'actor', type: 'stat', stat: catalog.stats[0], op: 'ge', value: 0 }
  if (catalog.conditions.length) return { id: actionId(), target: 'actor', type: 'condition', condition_id: catalog.conditions[0].name, present: true }
  return null
}

/** Select only real catalog capabilities, including complete two-clip pairs. */
export function presentations(catalog: ActionCatalog, ability: ActionDefinition['ability']) {
  return catalog.poses.filter(pose => ability === 'pair'
    ? pose.solo === false && catalog.pairKinds.includes(pose.animation || '')
    : pose.solo !== false && catalog.kinds.includes(pose.animation || '')
      && (ability !== 'sleep' || pose.group === 'lie'))
}

export function createActionPreset(preset: ActionPreset, catalog: ActionCatalog): ActionDefinition {
  const ability = preset === 'coffee' ? 'combined' : preset === 'sleep' ? 'sleep' : preset === 'pair' ? 'pair' : 'pose'
  const available = presentations(catalog, ability)
  const prepare = preset === 'coffee' ? available.find(pose => pose.animation === 'making-coffee')
    || available.find(pose => pose.animation === 'cooking') : undefined
  const drink = preset === 'coffee' ? available.find(pose => pose.animation === 'drinking') : undefined
  const preferred = preset === 'coffee' ? prepare
    : preset === 'sit' ? available.find(pose => pose.group === 'seat' && pose.animation === 'sit')
    : available.find(p => p.group === (preset === 'lie' || preset === 'sleep' ? 'lie' : 'seat'))
      || (preset === 'pair' ? available[0] : undefined)
  const pose_key = preferred?.key || ''
  return {
    id: actionId(), name: ({ sit: "Sit / relax", lie: "Lie down (awake)", sleep: "Go to sleep", coffee: "Make and drink coffee", pair: "Pair action" })[preset],
    description: '', enabled: true, ability, pose_key, participants: ability === 'pair' ? 2 : 1,
    presence: 'any', interrupt_on_presence_change: false,
    phases: ability === 'combined' ? [
      { id: actionId(), label: "Prepare", duration_game_s: 120, pose_key: prepare?.key || '' },
      { id: actionId(), label: "Drink", duration_game_s: 180, pose_key: drink?.key || '' },
    ] : [], requirements: [], effects: [],
  }
}

/** Combined entry uses its first phase; authoring can inspect any actual phase. */
export function actionPreviewPose(action: ActionDefinition | undefined, phaseId?: string): string {
  if (!action) return ''
  if (action.ability !== 'combined') return action.pose_key
  return (action.phases.find(phase => phase.id === phaseId) || action.phases[0])?.pose_key || ''
}

/** Independent identities; matching places are derived for the destination. */
export function copyAction(source: ActionDefinition): ActionDefinition {
  return { ...source, id: actionId(),
    phases: source.phases.map(row => ({ ...row, id: actionId() })),
    effects: source.effects.map(row => ({ ...row, id: actionId() })),
    requirements: source.requirements.map(row => ({ ...row, id: actionId() })),
  }
}

export function effectTimings(action: ActionDefinition, type: ActionEffect['type']): ActionEffect['when'][] {
  const timings: ActionEffect['when'][] = ['start']
  if (action.ability === 'combined' || action.ability === 'sleep') timings.push('success')
  if (type === 'stat_delta' && action.ability !== 'sleep') timings.push('active')
  return timings
}

/** Editor-only restrictions and catalog references; the server remains authoritative. */
export function actionEditorIssues(actions: ActionDefinition[], catalog: ActionCatalog): PropActionIssue[] {
  const issues: PropActionIssue[] = []
  const add = (path: string, code: string, message: string) => issues.push({ path, code, message, severity: 'error' })
  if (actions.length && catalog.status !== 'ready') {
    add('actions', 'catalog_unavailable', catalog.status === 'loading' ? "Loading action catalogs." : "Could not load action catalogs. Reload before saving.")
    return issues
  }
  actions.forEach((action, i) => {
    const path = `actions.${i}`
    if (!action.name.trim()) add(`${path}.name`, 'invalid_text', "Enter a name.")
    if (!['pose', 'combined', 'sleep', 'pair'].includes(action.ability)) add(`${path}.ability`, 'unsupported_ability', "Unknown ability. Choose an executable ability.")
    if (action.participants !== (action.ability === 'pair' ? 2 : 1)) add(`${path}.participants`, 'unsupported_combination', "The number of persons does not match the ability.")
    const allowed = presentations(catalog, action.ability)
    const checkPose = (key: string, p: string) => {
      if (!allowed.some(pose => pose.key === key)) add(p, 'unsupported_pose_capability', "Presentation is missing or incompatible with the ability. Choose an available presentation.")
    }
    if (action.ability === 'combined') {
      if (action.phases.length !== 2) add(`${path}.phases`, 'unsupported_combination', "Coffee requires exactly two phases: preparation and drinking. Explicitly repair the flow.")
      action.phases.forEach((phase, j) => {
        if (!(phase.duration_game_s > 0) || !Number.isFinite(phase.duration_game_s)) add(`${path}.phases.${j}.duration_game_s`, 'invalid_phase', "A positive duration in game time is required.")
        checkPose(phase.pose_key, `${path}.phases.${j}.pose_key`)
      })
    } else checkPose(action.pose_key, `${path}.pose_key`)
    action.requirements.forEach((row, j) => {
      const p = `${path}.requirements.${j}`
      if (action.participants === 1 && row.target !== 'actor') add(`${p}.target`, 'invalid_target', "This action has no partner.")
      if (row.type === 'stat' && !catalog.stats.includes(row.stat)) add(`${p}.stat`, 'unknown_requirement_reference', "Unknown stat. Choose an existing stat or remove the requirement.")
      if (row.type === 'stat' && !Number.isFinite(row.value)) add(`${p}.value`, 'invalid_number', 'A finite comparison value is required.')
      if (row.type === 'condition' && !catalog.conditions.some(c => c.name === row.condition_id)) add(`${p}.condition_id`, 'unknown_requirement_reference', "Unknown condition. Choose an existing condition or remove the requirement.")
    })
    action.effects.forEach((row, j) => {
      const p = `${path}.effects.${j}`
      if (!effectTimings(action, row.type).includes(row.when)) add(`${p}.when`, 'unsupported_combination', "This timing is not allowed for the effect and ability. Change it explicitly.")
      if (action.participants === 1 && row.target !== 'actor') add(`${p}.target`, 'invalid_target', "This action has no partner.")
      if (row.type === 'stat_delta') {
        if (!catalog.stats.includes(row.stat)) add(`${p}.stat`, 'unknown_stat', "Unknown stat. Choose an existing stat or remove the effect.")
        if (!Number.isFinite(row.amount)) add(`${p}.amount`, 'invalid_number', 'A finite amount is required.')
      }
      if (row.type === 'mood' && !row.mood.trim()) add(`${p}.mood`, 'invalid_text', "Enter or select a mood.")
      if (row.type === 'condition_add' || row.type === 'condition_remove') {
        if (!catalog.conditions.some(c => c.name === row.condition_id)) add(`${p}.condition_id`, 'unknown_condition', "Unknown condition. Choose an existing condition or remove the effect.")
      }
      if (row.type === 'condition_add' && (!(row.duration_game_s > 0) || !Number.isFinite(row.duration_game_s))) add(`${p}.duration_game_s`, 'invalid_number', 'A positive condition duration is required.')
    })
  })
  return issues
}
