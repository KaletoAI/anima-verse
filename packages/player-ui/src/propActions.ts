import { apiGet, apiPost } from './api'

/** Exact identity from Core's offer; clients never synthesize furniture targets. */
export interface PropActionTarget {
  location_id: string
  room_id: string
  placement_id: string
  variant_uid: string
}
export interface PropActionChoice {
  partner?: string
  enabled: boolean
  reason: string
}
export interface PropActionEffect {
  id: string
  target: 'actor' | 'partner' | 'both'
  type: string
  when: 'start' | 'success' | 'active'
  stat?: string
  amount?: number
  mood?: string
  condition_id?: string
  duration_game_s?: number
  repeat?: string
}
export interface PropActionOffer {
  action_id: string
  definition_revision: string
  placement_id: string
  variant_uid: string
  target: PropActionTarget
  label: string
  description: string
  enabled: boolean
  reason: string
  required_partner: boolean
  available_targets: Array<PropActionChoice & { partner: string }>
  effects: PropActionEffect[]
}
export interface PropActionResult {
  execution_id: string
  status: string
  reason: string
  effects?: Record<string, unknown>
}
/** Private lifecycle DTO: only GET /play/prop-actions/state may supply this. */
export interface PropActionExecution extends PropActionResult {
  action_id: string
  definition_revision: string
  target: PropActionTarget
  actor: string
  partner: string
  phase: string
  phase_label: string
  label: string
  roles: {
    actor: string
    partner?: string
    clip: Record<string, string>
    access: Record<string, string>
  }
  can_respond: boolean
  can_cancel: boolean
}
export interface PropActionState {
  incoming: PropActionExecution[]
  outgoing: PropActionExecution[]
  current: PropActionExecution[]
  recent_results: PropActionExecution[]
}

/** Presentation only: preserve Core's exact partner verdict, never auto-pick one. */
export function propActionChoices(offer: PropActionOffer): PropActionChoice[] {
  if (!offer.required_partner) return [{ enabled: offer.enabled, reason: offer.reason }]
  return offer.available_targets.length ? offer.available_targets
    : [{ enabled: false, reason: offer.reason }]
}

const CHANGED = 'prop-actions:changed'
/** Hosts subscribe here to force a world poll before short approaches disappear. */
export function onPropActionChanged(listener: (requestId?: string) => void): () => void {
  const changed = (event: Event) => listener((event as CustomEvent<{ request_id?: string }>).detail?.request_id)
  window.addEventListener(CHANGED, changed)
  return () => window.removeEventListener(CHANGED, changed)
}
export function notifyPropActionChanged(requestId?: string): void {
  window.dispatchEvent(new CustomEvent(CHANGED, { detail: requestId === undefined ? undefined : { request_id: requestId } }))
}
export function getPropActions(): Promise<PropActionOffer[]> {
  return apiGet<PropActionOffer[]>('/play/prop-actions')
}
export function getPropActionState(): Promise<PropActionState> {
  return apiGet<PropActionState>('/play/prop-actions/state')
}
let preparation: ((requestId: string) => Promise<void>) | null = null
// Transport correlation only, not an execution identity or server request nonce.
const preparationSession = Math.random().toString(36).slice(2)
let preparationSequence = 0
/** One host owns the position-writer barrier; standalone frontend needs none. */
export function setPropActionPreparation(handler: (requestId: string) => Promise<void>): () => void {
  preparation = handler
  return () => { if (preparation === handler) preparation = null }
}
async function mutate(path: string, body: unknown): Promise<PropActionResult> {
  const requestId = `${preparationSession}:${++preparationSequence}`
  try {
    await preparation?.(requestId)
    return await apiPost<PropActionResult>(path, body)
  } finally {
    // Invalidation releases the host's position barrier even after a refusal.
    // It is never a statement that a request adopted a place or succeeded.
    notifyPropActionChanged(requestId)
  }
}
export function requestPropAction(actionId: string, target: PropActionTarget, revision: string, partner?: string): Promise<PropActionResult> {
  return mutate('/play/prop-actions/request', { action_id: actionId, target, revision, ...(partner === undefined ? {} : { partner }) })
}
export function respondPropAction(executionId: string, accept: boolean): Promise<PropActionResult> {
  return mutate('/play/prop-actions/respond', { execution_id: executionId, accept })
}
export function cancelPropAction(executionId: string): Promise<PropActionResult> {
  return mutate('/play/prop-actions/cancel', { execution_id: executionId })
}
