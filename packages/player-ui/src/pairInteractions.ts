import { apiPost } from './api'

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

export function invitePair(partner: string, pose: string): Promise<unknown> {
  return request('/play/interact', { partner, pose }, partner)
}

export function respondPair(inviteId: string, accept: boolean, partner?: string): Promise<unknown> {
  return request('/play/interact/respond', { invite_id: inviteId, accept }, accept ? partner : undefined)
}
