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
  prop_label: string
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

export interface PropActionSnapshot { offers: PropActionOffer[]; state: PropActionState }
let hosted = false
let hostSnapshot: PropActionSnapshot | null = null
const hostListeners = new Set<() => void>()
/** The scene owns reads in an embedded HUD; snapshots cross the existing state bridge. */
export function setPropActionHost(on: boolean): void {
  hosted = on; hostSnapshot = null
  for (const listener of hostListeners) listener()
}
export function isPropActionHosted(): boolean { return hosted }
export function getHostedPropActions(): PropActionSnapshot | null { return hostSnapshot }
export function publishHostedPropActions(snapshot: PropActionSnapshot | null): void {
  hostSnapshot = snapshot
  for (const listener of hostListeners) listener()
}
export function subscribeHostedPropActions(listener: () => void): () => void {
  hostListeners.add(listener)
  return () => { hostListeners.delete(listener) }
}

let burstUntil = 0
let pollPeriodMs = 3000
export function setPropActionPollPeriod(ms: number): void { pollPeriodMs = Math.max(3000, ms) }
function cachedRead<T>(load: () => Promise<T>) {
  let pending: Promise<T> | null = null, value: T, hasValue = false
  let started = -Infinity, generation = 0, failed = false, failure: unknown
  return {
    invalidate() { generation++; hasValue = false; failed = false },
    async read(): Promise<T> {
      const epoch = generation
      if (pending) {
        const answer = await pending
        return epoch === generation && hasValue ? answer : this.read()
      }
      const now = Date.now()
      if (now - started < (now < burstUntil ? 500 : pollPeriodMs)) {
        if (hasValue) return value
        if (failed) throw failure
      }
      started = now
      const request = load()
      pending = request
      try {
        const answer = await request
        if (epoch === generation) { value = answer; hasValue = true; failed = false }
        return answer
      } catch (error) {
        if (epoch === generation) { failed = true; failure = error; hasValue = false }
        throw error
      } finally { if (pending === request) pending = null }
    },
  }
}
const offersRead = cachedRead(() => apiGet<PropActionOffer[]>('/play/prop-actions'))
const stateRead = cachedRead(() => apiGet<PropActionState>('/play/prop-actions/state'))

const CHANGED = 'prop-actions:changed'
/** Hosts subscribe here to force a world poll before short approaches disappear. */
export function onPropActionChanged(listener: (requestId?: string) => void): () => void {
  const changed = (event: Event) => listener((event as CustomEvent<{ request_id?: string }>).detail?.request_id)
  window.addEventListener(CHANGED, changed)
  return () => window.removeEventListener(CHANGED, changed)
}
export function notifyPropActionChanged(requestId?: string): void {
  if (requestId !== undefined) {
    offersRead.invalidate(); stateRead.invalidate()
    if (Date.now() >= burstUntil) burstUntil = Date.now() + 5000
  }
  window.dispatchEvent(new CustomEvent(CHANGED, { detail: requestId === undefined ? undefined : { request_id: requestId } }))
}
export function getPropActions(): Promise<PropActionOffer[]> {
  return hosted ? Promise.resolve(hostSnapshot?.offers ?? []) : offersRead.read()
}
export function getPropActionState(): Promise<PropActionState> {
  return hosted ? Promise.resolve(hostSnapshot?.state ?? { incoming: [], outgoing: [], current: [], recent_results: [] }) : stateRead.read()
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
