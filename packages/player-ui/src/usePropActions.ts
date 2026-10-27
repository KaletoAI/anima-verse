import { useEffect } from 'react'
import { getPropActions, getPropActionState, notifyPropActionChanged, onPropActionChanged, type PropActionOffer, type PropActionState } from './propActions'
import { pollCore, usePoll } from './usePolling'

interface PropActionSnapshot { offers: PropActionOffer[]; state: PropActionState }
const SPEC = { intervalMs: 1000, pushedIntervalMs: 1000, minSpacingMs: 0,
  topics: ['presence', 'scene', 'self', 'world'] as ('presence' | 'scene' | 'self' | 'world')[] }
let users = 0
let offChanged: (() => void) | null = null
let lastLifecycle: string | null = null
function subscribeRefresh(): () => void {
  if (users++ === 0) offChanged = onPropActionChanged(() => {
    // refresh, not signal: an own mutation bypasses normal push spacing and
    // queues a trailing read when an older poll is still in flight.
    for (const key of ['play-prop-actions', 'play-self']) {
      void pollCore().refresh(key)
    }
  })
  return () => { if (--users === 0) { offChanged?.(); offChanged = null } }
}
/** One deduplicated live feed across Self, Scene and every partner card. */
export function usePropActions() {
  useEffect(subscribeRefresh, [])
  return usePoll<PropActionSnapshot>('play-prop-actions', async () => {
    const [offers, state] = await Promise.all([getPropActions(), getPropActionState()])
    const lifecycle = JSON.stringify(state)
    if (lifecycle !== lastLifecycle) {
      const hadLifecycle = lastLifecycle !== null
      lastLifecycle = lifecycle
      if (hadLifecycle || state.incoming.length || state.outgoing.length || state.current.length) {
        notifyPropActionChanged()
      }
    }
    return { offers, state }
  }, SPEC)
}
