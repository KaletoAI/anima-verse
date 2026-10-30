import { useEffect, useSyncExternalStore } from 'react'
import { getPropActions, getPropActionState, onPropActionChanged, isPropActionHosted, getHostedPropActions, subscribeHostedPropActions, type PropActionSnapshot } from './propActions'
import { pollCore, usePoll } from './usePolling'

const SPEC = { intervalMs: 3000, pushedIntervalMs: 6000, minSpacingMs: 3000,
  topics: ['presence', 'scene', 'self', 'world'] as ('presence' | 'scene' | 'self' | 'world')[] }
let users = 0
let offChanged: (() => void) | null = null
function subscribeRefresh(): () => void {
  if (users++ === 0) offChanged = onPropActionChanged(() => {
    // refresh, not signal: an own mutation bypasses normal push spacing and
    // queues a trailing read when an older poll is still in flight.
    for (const key of (isPropActionHosted() ? ['play-self'] : ['play-prop-actions', 'play-self'])) {
      void pollCore().refresh(key)
    }
  })
  return () => { if (--users === 0) { offChanged?.(); offChanged = null } }
}
/** One deduplicated live feed across Self, Scene and every partner card. */
export function usePropActions() {
  useEffect(subscribeRefresh, [])
  const hosted = useSyncExternalStore(subscribeHostedPropActions, isPropActionHosted, isPropActionHosted)
  const snapshot = useSyncExternalStore(subscribeHostedPropActions, getHostedPropActions, getHostedPropActions)
  const polled = usePoll<PropActionSnapshot>('play-prop-actions', async () => {
    const [offers, state] = await Promise.all([getPropActions(), getPropActionState()])
    return { offers, state }
  }, { ...SPEC, enabled: !hosted })
  return hosted ? { data: snapshot, error: null, refresh: async () => {} } : polled
}
