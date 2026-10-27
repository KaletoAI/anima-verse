import { GENERAL_TARGET, type PendingFields } from './pendingFields'
import type { ActionDefinition, PropActionIssue, PropDims, PropFull, PropVariant } from './propTypes'

export interface PropCheckVariant extends PropDims {
  uid: string; stem: string; active: boolean; seasons: string[]
  dims_estimated: boolean; description: string; ground_offset_m: number
  markers: PropVariant['markers']; action_bindings: PropVariant['action_bindings']
  light?: PropVariant['light']; slot_values?: PropVariant['slot_values']
  area_defaults?: PropVariant['area_defaults']; label?: string
  target_faces_high?: number | null; target_faces_low?: number | null
}
export interface PropCheckDocument extends Record<string, unknown> {
  actions: ActionDefinition[]; model_variants: PropCheckVariant[]
}

/** Author-side shape, not the UID-keyed bulk patch or the renderer projection. */
export function propActionCheckDocument(prop: PropFull, variants: PropVariant[], buf: PendingFields): PropCheckDocument {
  const general = buf.get(GENERAL_TARGET) || {}
  const tags = general.tags ?? prop.tags
  const mount = general.mount as { value?: string; suggested?: boolean } | undefined
  return {
    name: prop.name, category: prop.category, tags: prop.tags,
    sway_factor: prop.sway_factor, mount: prop.mount,
    mount_suggested: prop.mount_suggested, slots: prop.slots, key_areas: prop.key_areas,
    ...general,
    ...(mount && typeof mount === 'object'
      ? { mount: mount.value || '', mount_suggested: !!mount.suggested } : {}),
    ...(typeof tags === 'string' ? { tags: tags.split(',').map((tag) => tag.trim()).filter(Boolean) } : {}),
    actions: ('actions' in general ? general.actions : prop.actions) as ActionDefinition[],
    model_variants: variants.map((variant) => ({
      uid: variant.uid, stem: variant.stem, active: variant.active, seasons: variant.seasons,
      ...variant.dims,
      dims_estimated: variant.dims_estimated, description: variant.description,
      ground_offset_m: variant.ground_offset_m, markers: variant.markers,
      action_bindings: variant.action_bindings, light: variant.light,
      slot_values: variant.slot_values, area_defaults: variant.area_defaults,
      label: variant.label, target_faces_high: variant.target_faces_high,
      target_faces_low: variant.target_faces_low,
    })),
  }
}


/** Resolve server array paths against the checked snapshot, never store indices. */
export function resolveCheckIssue(issue: PropActionIssue, document: PropCheckDocument): {
  actionId?: string; variantUid?: string; field: string
} {
  const path = issue.path.split('.')
  const actions = document.actions as PropFull['actions']
  if (path[0] === 'actions') {
    return { actionId: actions[Number(path[1])]?.id, field: path.slice(2).join('.') }
  }
  if (path[0] === 'model_variants') {
    const variant = document.model_variants[Number(path[1])]
    return { variantUid: variant?.uid,
      actionId: path[2] === 'action_bindings'
        ? variant?.action_bindings[Number(path[3])]?.action_id : undefined,
      field: path.slice(2).join('.') }
  }
  return { field: issue.path }
}

export interface PropCheckTarget {
  location_id: string; room_id: string; placement_id: string; variant_uid: string
}
export interface PropCheckTargets {
  revision: string
  rooms: { id: string; name: string; placements: { target: PropCheckTarget }[]
    persons: { name: string; sleeping: boolean }[] }[]
}
export interface PropPlacementCheckRequest {
  target: PropCheckTarget; action_id: string; revision: string; actor: string; partner: string
}
export interface PropPlacementCheckResult { enabled: boolean; reason: string }
export interface PropExecutionResult { execution_id: string; status: string; phase?: string; reason: string }

const REASONS: Record<string, string> = {
  missing_entry_transition: 'Ein passender gemessener Eintrittsübergang vom Zugang zum Körperanker fehlt. Keine Ausführung und kein Teleport. Die Übergangsregel und passende Animation müssen im bestehenden Animationssystem eingerichtet werden.',
  entry_transition_mismatch: 'Der gemessene Eintrittsübergang passt räumlich nicht vom Zugang zum Körperanker.',
  entry_transition_blocked: 'Der Eintritt vom Zugang zum Körperanker ist durch Geometrie blockiert.',
  presence_not_met: 'Die Anwesenheitsregel ist im tatsächlichen Raum nicht erfüllt. Auch schlafende Personen zählen als anwesend.',
  participant_asleep: 'Eine beteiligte Person schläft und ist für diese Handlung nicht verfügbar.',
  target_not_in_actor_room: 'Alle Beteiligten müssen sich bereits im Raum dieser Platzierung befinden.',
  stale_definition: 'Die gespeicherte Definition hat sich geändert. Platzierungen aktualisieren und erneut prüfen; der Entwurf bleibt erhalten.',
  stale_variant: 'Die tatsächlich verwendete Variante hat sich geändert. Platzierungen aktualisieren.',
  placement_not_found: 'Diese Platzierung ist nicht mehr verfügbar. Platzierungen aktualisieren.',
  invalid_definition: 'Die gespeicherte Definition ist ungültig. Konfiguration prüfen und reparieren.',
  invalid_partner: 'Für eine Paarhandlung zwei verschiedene verfügbare Personen wählen.',
  participant_unavailable: 'Eine beteiligte Person ist nicht verfügbar. Personen aktualisieren.',
  participant_claimed: 'Eine beteiligte Person ist bereits durch eine andere Handlung gebunden.',
  journey_already_active: 'Eine beteiligte Person ist bereits unterwegs.',
  interaction_active: 'Eine beteiligte Person ist bereits in einer anderen Interaktion.',
  no_free_slot: 'Kein passender freier Platz ist verfügbar.',
  slot_occupied: 'Der benötigte Platz ist belegt.',
  binding_not_supported: 'Diese Variante unterstützt die Handlung nicht mit einer lokal gültigen Bindung.',
  binding_not_found: 'Für diese Handlung fehlt die Bindung auf der tatsächlichen Variante.',
  unknown_pose: 'Die konfigurierte Darstellung ist nicht im vorhandenen Posenkatalog verfügbar.',
  missing_pair_animation: 'Für diese Paarhandlung fehlt eine unterstützte Paaranimation.',
  incompatible_pose_marker: 'Darstellung und Körperanker sind nicht kompatibel.',
  unsupported_pose_capability: 'Die Darstellung unterstützt die konfigurierte Teilnehmerzahl nicht.',
  sleep_requires_lying_place: 'Echter Schlaf benötigt einen geeigneten Liegeplatz.',
  unknown_requirement_reference: 'Eine Voraussetzung verweist auf einen unbekannten Wert oder Zustand.',
  missing_character_stat: 'Ein benötigter Wert fehlt im Charaktertemplate oder kann nicht gelesen werden.',
  unknown_stat: 'Ein Wirkungswert ist im Charaktertemplate nicht vorhanden.',
  requirement_not_met: 'Eine Werte- oder Zustandsvoraussetzung ist nicht erfüllt.',
  action_not_found: 'Die gewählte Handlung ist nicht gespeichert. Zuerst speichern und aktualisieren.',
  action_disabled: 'Die gespeicherte Handlung ist deaktiviert.',
  world_frozen: 'Die Welt ist eingefroren. Die Ausführung ist derzeit gesperrt.',
  room_geometry_unavailable: 'Für diesen Raum ist keine prüfbare Geometrie verfügbar.',
  invalid_room_geometry: 'Die vorhandene Raumgeometrie ist für einen Wegnachweis ungültig.',
  start_not_walkable: 'Der tatsächliche Startpunkt ist nicht begehbar.',
  departure_not_walkable: 'Der Weg vom bisherigen Platz auf den Boden ist blockiert.',
  no_route: 'Es gibt keinen begehbaren Weg zum Zugang.',
  access_not_walkable: 'Der konfigurierte Zugang ist nicht begehbar.',
  entry_anchor_outside_location: 'Der Körperanker liegt außerhalb des Ortes.',
  consent_declined: 'Die eingeladene Person hat abgelehnt.',
  ended: 'Die Handlung wurde normal beendet.',
  phases_completed: 'Alle Phasen wurden erfolgreich abgeschlossen.',
  awake: 'Die Person ist aufgewacht; die Schlafhandlung ist beendet.',
  cancelled: 'Die Handlung wurde abgebrochen.',
  invalid_request: 'Die Prüfauswahl ist unvollständig oder ungültig. Auswahl aktualisieren.',
}
export function propCheckReason(reason: string): string {
  return REASONS[reason] || `Der Server meldet: ${reason}. Auswahl, Konfiguration und aktuellen Spielstatus prüfen.`
}
