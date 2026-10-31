import { GENERAL_TARGET, type PendingFields } from './pendingFields'
import { actionEditorIssues, type ActionCatalog } from './propActionAuthoring'
import type { ActionDefinition, PropActionIssue, PropDims, PropFull, PropVariant, PropAccessPreviews } from './propTypes'

export interface PropCheckVariant extends PropDims {
  uid: string; stem: string; active: boolean; seasons: string[]
  dims_estimated: boolean; description: string; ground_offset_m: number
  markers: PropVariant['markers']
  light?: PropVariant['light']; slot_values?: PropVariant['slot_values']
  area_defaults?: PropVariant['area_defaults']; label?: string
  target_faces_high?: number | null; target_faces_low?: number | null
}
export interface PropCheckDocument extends Record<string, unknown> {
  actions: ActionDefinition[]; model_variants: PropCheckVariant[]
}

export interface PropConfigurationResult {
  valid: boolean; placement: 'not_checked'; issues: PropActionIssue[]
  access_previews?: PropAccessPreviews
}
export interface PropConfigurationSnapshot {
  propId: string; revision: string; document: PropCheckDocument
  catalog: ActionCatalog; revisionReady: boolean
}
export interface PropConfigurationRequest {
  snapshot: PropConfigurationSnapshot; sequence: number
}

/** Catalog and document references identify the immutable authoring snapshots. */
export function samePropConfigurationSnapshot(
  checked: PropConfigurationSnapshot, current: PropConfigurationSnapshot,
): boolean {
  return checked.propId === current.propId && checked.revision === current.revision
    && checked.document === current.document && checked.catalog === current.catalog
    && checked.revisionReady === current.revisionReady
}

/** Also reject older requests for the same snapshot, including their error/finally paths. */
export function isCurrentPropConfigurationRequest(
  checked: PropConfigurationRequest, current: PropConfigurationRequest,
): boolean {
  return checked.sequence === current.sequence
    && samePropConfigurationSnapshot(checked.snapshot, current.snapshot)
}

/** Combine existing editor blockers with server validation; neither engine is replaced. */
export function composePropConfigurationResult(
  document: PropCheckDocument, catalog: ActionCatalog, server: PropConfigurationResult,
): PropConfigurationResult {
  const issues: PropActionIssue[] = []
  const positions = new Map<string, number>()
  for (const issue of [...server.issues, ...actionEditorIssues(document.actions, catalog)]) {
    const key = `${issue.path}\0${issue.code}`
    const index = positions.get(key)
    if (index === undefined) {
      positions.set(key, issues.length)
      issues.push(issue)
    } else if (issues[index].severity !== 'error' && issue.severity === 'error') {
      issues[index] = issue
    }
  }
  return { ...server, issues, valid: server.valid && !issues.some(issue => issue.severity === 'error') }
}

/** Author-side shape, not the UID-keyed bulk patch or the renderer projection. */
export function propActionCheckDocument(prop: PropFull, variants: PropVariant[], buf: PendingFields): PropCheckDocument {
  const general = buf.get(GENERAL_TARGET) || {}
  const tags = general.tags ?? prop.tags
  const mount = general.mount as { value?: string; suggested?: boolean } | undefined
  return {
    name: prop.name, category: prop.category, tags: prop.tags, bbox: prop.bbox,
    sway_factor: prop.sway_factor, mount: prop.mount,
    mount_suggested: prop.mount_suggested, slots: prop.slots, key_areas: prop.key_areas,
    exclude_actions: prop.exclude_actions || [],
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
      light: variant.light,
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

const REASONS: Record<string, string> = {
  missing_entry_transition: "A matching measured entry transition from access to body anchor is missing. Configure the transition rule and matching animation in the animation system before execution.",
  entry_transition_mismatch: "The measured entry transition does not connect access and body anchor.",
  entry_transition_blocked: "Geometry blocks entry from access to body anchor.",
  presence_not_met: "The presence rule is not met in the actual room. Sleeping people also count as present.",
  participant_asleep: "A participant is sleeping and unavailable for this action.",
  target_not_in_actor_room: "All participants must already be in this placement's room.",
  stale_definition: "The saved definition changed. Refresh placements and check again; the draft is retained.",
  stale_variant: "The resolved variant changed. Refresh placements.",
  placement_not_found: "This placement is no longer available. Refresh placements.",
  invalid_definition: "The saved definition is invalid. Check and repair the configuration.",
  invalid_partner: "Choose two different available persons for a pair action.",
  participant_unavailable: "A participant is unavailable. Refresh persons.",
  participant_claimed: "A participant is already occupied by another action.",
  journey_already_active: "A participant is already travelling.",
  interaction_active: "A participant is already in another interaction.",
  no_free_slot: "No suitable free place is available.",
  slot_occupied: "The required place is occupied.",
  binding_not_supported: "This variant has no supported matching place for the action.",
  binding_not_found: "This action has no matching place on the resolved variant.",
  unknown_pose: "The configured presentation is unavailable in the pose catalog.",
  missing_pair_animation: "This pair action has no supported pair animation.",
  incompatible_pose_marker: "Presentation and body anchor are incompatible.",
  unsupported_pose_capability: "The presentation does not support the configured participant count.",
  sleep_requires_lying_place: "Actual sleep requires a suitable lying place.",
  unknown_requirement_reference: "A requirement references an unknown stat or condition.",
  missing_character_stat: "A required stat is missing from the character template or cannot be read.",
  unknown_stat: "An effect stat is missing from the character template.",
  requirement_not_met: "A stat or condition requirement is not met.",
  action_not_found: "The selected action is not saved. Save and refresh first.",
  action_disabled: "The saved action is disabled.",
  world_frozen: "The world is frozen. Execution is currently blocked.",
  room_geometry_unavailable: "No verifiable geometry is available for this room.",
  invalid_room_geometry: "The existing room geometry is invalid for path verification.",
  start_not_walkable: "The actual starting point is not walkable.",
  departure_not_walkable: "The path from the previous place to the floor is blocked.",
  no_route: 'Es gibt keinen begehbaren Weg zum Zugang.',
  access_not_walkable: "The configured access is not walkable.",
  entry_anchor_outside_location: "The body anchor is outside the location.",
  consent_declined: "The invited person declined.",
  ended: "The action ended normally.",
  phases_completed: "All phases completed successfully.",
  awake: "The person woke up; the sleep action has ended.",
  cancelled: "The action was cancelled.",
  invalid_request: "The check selection is incomplete or invalid. Refresh the selection.",
}
export function propCheckReason(reason: string): string {
  return REASONS[reason] || 'The server reported an unknown reason. Check the selection, configuration and current game state.'
}
