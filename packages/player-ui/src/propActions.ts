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
export interface PropActionDeparture {
  seat: [number, number]
  stand: [number, number]
  exit_clip: string
  exit_s: number
}
export interface PropActionMotion {
  execution_id: string
  journey_id: string
  room_id: string
  floor_y: number | null
  waypoints: [number, number][]
  paces_m_s_real: (number | null)[] | null
  departure: PropActionDeparture | null
  access: { x: number; y: number; z: number; yaw: number }
  anchor: { x: number; y: number; z: number; yaw: number; root_offset: number; place_id: string; slot: number }
  entry: { mode: 'bridge' | 'direct'; kind: string; pose_key: string; duration_s: number } | null
  height_cm: number | null
  role: 'a' | 'b' | null
}
export interface PropActionResult {
  execution_id: string
  status: string
  reason: string
  motion?: PropActionMotion | PropActionDeparture | null
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
      if (now - started < pollPeriodMs) {
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
/** Hosts receive mutation answers immediately; uncorrelated events invalidate status. */
export type PropActionSource = 'request' | 'respond' | 'cancel'
export function onPropActionChanged(listener: (requestId?: string, result?: PropActionResult, source?: PropActionSource) => void): () => void {
  const changed = (event: Event) => {
    const detail = (event as CustomEvent<{ request_id?: string; result?: PropActionResult; source?: PropActionSource }>).detail
    listener(detail?.request_id, detail?.result, detail?.source)
  }
  window.addEventListener(CHANGED, changed)
  return () => window.removeEventListener(CHANGED, changed)
}
export function notifyPropActionChanged(requestId?: string, result?: PropActionResult, source?: PropActionSource): void {
  if (requestId !== undefined) {
    offersRead.invalidate(); stateRead.invalidate()
  }
  window.dispatchEvent(new CustomEvent(CHANGED, { detail: { request_id: requestId, result, source } }))
}
export function getPropActions(): Promise<PropActionOffer[]> {
  return hosted ? Promise.resolve(hostSnapshot?.offers ?? []) : offersRead.read()
}
export function getPropActionState(): Promise<PropActionState> {
  return hosted ? Promise.resolve(hostSnapshot?.state ?? { incoming: [], outgoing: [], current: [], recent_results: [] }) : stateRead.read()
}
let preparation: ((requestId: string, target?: PropActionTarget) => Promise<void>) | null = null
// Transport correlation only, not an execution identity or server request nonce.
const preparationSession = Math.random().toString(36).slice(2)
let preparationSequence = 0
/** One host owns the position-writer barrier; standalone frontend needs none. */
export function setPropActionPreparation(handler: (requestId: string, target?: PropActionTarget) => Promise<void>): () => void {
  preparation = handler
  return () => { if (preparation === handler) preparation = null }
}
async function mutate(path: string, body: unknown): Promise<PropActionResult> {
  const requestId = `${preparationSession}:${++preparationSequence}`
  let result: PropActionResult | undefined
  try {
    const payload = body as { target?: PropActionTarget; execution_id?: string }
    const target = payload.target ?? (path.endsWith('/respond')
      ? hostSnapshot?.state.incoming.find(row => row.execution_id === payload.execution_id)?.target : undefined)
    await preparation?.(requestId, target)
    result = await apiPost<PropActionResult>(path, body)
    return result
  } catch (error) {
    const execution = body as { execution_id?: string }
    result = { execution_id: execution.execution_id ?? '', status: 'failed', reason: String(error) }
    throw error
  } finally {
    // Invalidation releases the host's position barrier even after a refusal.
    // It is never a statement that a request adopted a place or succeeded.
    notifyPropActionChanged(requestId, result, path.split('/').at(-1) as PropActionSource)
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
