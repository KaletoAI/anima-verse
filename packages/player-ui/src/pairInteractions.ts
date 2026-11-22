import { apiPost } from './api'
import type { PropActionConsent } from './propActions'

export type PairFacingPhase = 'begin' | 'keep' | 'rollback'
type Facing = (phase: PairFacingPhase, requestId: string, partner: string) => void
let facing: Facing | null = null
let serial = 0

/** The HUD forwards only visual intent to its host; HTTP stays in the shared panels. */
export function setPairFacing(handler: Facing): () => void {
  facing = handler
  return () => { if (facing === handler) facing = null }
}

async function request(path: string, body: unknown, partner?: string): Promise<unknown> {
  const id = `pair:${++serial}`
  const preview = facing
  if (partner) preview?.('begin', id, partner)
  try {
    const answer = await apiPost<{ status?: string }>(path, body)
    if (partner) preview?.(answer?.status === 'declined' ? 'rollback' : 'keep', id, partner)
    return answer
  } catch (error) {
    if (partner) preview?.('rollback', id, partner)
    throw error
  }
}

/** Propose a free pair pose: "ask" (default) puts the question, "react"
 *  starts it at once and the partner reacts — the same two ways as a
 *  furniture pair action (`requestPropAction`). */
export function invitePair(partner: string, pose: string, consent: PropActionConsent = 'ask'): Promise<unknown> {
  return request('/play/interact', { partner, pose, ...(consent === 'react' ? { consent } : {}) }, partner)
}

export function respondPair(inviteId: string, accept: boolean, partner?: string): Promise<unknown> {
  return request('/play/interact/respond', { invite_id: inviteId, accept }, accept ? partner : undefined)
}

/** The own avatar holds its gauge back in its free pair scene (or lets go) —
 *  the free-pair twin of `holdPropActionMeter` (server `pose_scene.hold`). */
export async function holdPairMeter(sceneId: string, hold: boolean): Promise<void> {
  await apiPost('/play/interact/hold', { scene_id: sceneId, hold })
}

/** The own avatar plays an alt half of its role in its free pair scene
 *  ("" = its own half again; server `pose_scene.set_alt`). */
export async function setPairAlt(sceneId: string, alt: string): Promise<void> {
  await apiPost('/play/interact/alt', { scene_id: sceneId, alt })
}
