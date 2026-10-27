import type { ActionDefinition, ActionEffect, PropActionIssue } from './propTypes'
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
export const actionId = () => crypto.randomUUID()

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
  const preferred = available.find(p => p.group === (preset === 'lie' || preset === 'sleep' ? 'lie' : 'seat'))
    || (preset === 'pair' || preset === 'coffee' ? available[0] : undefined)
  const pose_key = preferred?.key || ''
  return {
    id: actionId(), name: ({ sit: 'Sitzen / entspannen', lie: 'Hinlegen (wach)', sleep: 'Schlafen gehen', coffee: 'Kaffee machen und trinken', pair: 'Gemeinsame Paarhandlung' })[preset],
    description: '', enabled: true, ability, pose_key, participants: ability === 'pair' ? 2 : 1,
    presence: 'any', interrupt_on_presence_change: false,
    phases: ability === 'combined' ? [
      { id: actionId(), label: 'Zubereiten', duration_game_s: 120, pose_key },
      { id: actionId(), label: 'Trinken', duration_game_s: 180, pose_key },
    ] : [], requirements: [], effects: [],
  }
}

/** No copied binding: the destination geometry must be deliberately assigned. */
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
    add('actions', 'catalog_unavailable', catalog.status === 'loading' ? 'Aktionskataloge werden geladen.' : 'Aktionskataloge konnten nicht geladen werden. Erneut laden, bevor du speicherst.')
    return issues
  }
  actions.forEach((action, i) => {
    const path = `actions.${i}`
    if (!action.name.trim()) add(`${path}.name`, 'invalid_text', 'Bitte einen Namen eingeben.')
    if (!['pose', 'combined', 'sleep', 'pair'].includes(action.ability)) add(`${path}.ability`, 'unsupported_ability', 'Unbekannte Fähigkeit. Eine ausführbare Fähigkeit wählen.')
    if (action.participants !== (action.ability === 'pair' ? 2 : 1)) add(`${path}.participants`, 'unsupported_combination', 'Die Personenzahl passt nicht zur Fähigkeit.')
    const allowed = presentations(catalog, action.ability)
    const checkPose = (key: string, p: string) => {
      if (!allowed.some(pose => pose.key === key)) add(p, 'unsupported_pose_capability', 'Darstellung fehlt oder passt nicht zur Fähigkeit. Eine verfügbare Darstellung wählen.')
    }
    if (action.ability === 'combined') {
      if (action.phases.length !== 2) add(`${path}.phases`, 'unsupported_combination', 'Kaffee benötigt genau zwei Phasen: Zubereiten und Trinken. Ablauf ausdrücklich reparieren.')
      action.phases.forEach((phase, j) => {
        if (!(phase.duration_game_s > 0) || !Number.isFinite(phase.duration_game_s)) add(`${path}.phases.${j}.duration_game_s`, 'invalid_phase', 'Eine positive Dauer in Spielzeit ist erforderlich.')
        checkPose(phase.pose_key, `${path}.phases.${j}.pose_key`)
      })
    } else checkPose(action.pose_key, `${path}.pose_key`)
    action.requirements.forEach((row, j) => {
      const p = `${path}.requirements.${j}`
      if (action.participants === 1 && row.target !== 'actor') add(`${p}.target`, 'invalid_target', 'Diese Handlung hat keine Partnerperson.')
      if (row.type === 'stat' && !catalog.stats.includes(row.stat)) add(`${p}.stat`, 'unknown_requirement_reference', 'Unbekannter Wert. Bestehenden Wert wählen oder Voraussetzung entfernen.')
      if (row.type === 'stat' && !Number.isFinite(row.value)) add(`${p}.value`, 'invalid_number', 'Eine endliche Vergleichszahl ist erforderlich.')
      if (row.type === 'condition' && !catalog.conditions.some(c => c.name === row.condition_id)) add(`${p}.condition_id`, 'unknown_requirement_reference', 'Unbekannter Zustand. Bestehenden Zustand wählen oder Voraussetzung entfernen.')
    })
    action.effects.forEach((row, j) => {
      const p = `${path}.effects.${j}`
      if (!effectTimings(action, row.type).includes(row.when)) add(`${p}.when`, 'unsupported_combination', 'Dieser Zeitpunkt ist für Wirkung und Fähigkeit nicht erlaubt. Bitte ausdrücklich ändern.')
      if (action.participants === 1 && row.target !== 'actor') add(`${p}.target`, 'invalid_target', 'Diese Handlung hat keine Partnerperson.')
      if (row.type === 'stat_delta') {
        if (!catalog.stats.includes(row.stat)) add(`${p}.stat`, 'unknown_stat', 'Unbekannter Wert. Bestehenden Wert wählen oder Wirkung entfernen.')
        if (!Number.isFinite(row.amount)) add(`${p}.amount`, 'invalid_number', 'Ein endlicher Betrag ist erforderlich.')
      }
      if (row.type === 'mood' && !row.mood.trim()) add(`${p}.mood`, 'invalid_text', 'Bitte eine Stimmung eingeben oder auswählen.')
      if (row.type === 'condition_add' || row.type === 'condition_remove') {
        if (!catalog.conditions.some(c => c.name === row.condition_id)) add(`${p}.condition_id`, 'unknown_condition', 'Unbekannter Zustand. Bestehenden Zustand wählen oder Wirkung entfernen.')
      }
      if (row.type === 'condition_add' && (!(row.duration_game_s > 0) || !Number.isFinite(row.duration_game_s))) add(`${p}.duration_game_s`, 'invalid_number', 'Eine positive Zustandsdauer ist erforderlich.')
    })
  })
  return issues
}
