/**
 * The mood suggestion list, loaded from the server.
 *
 * `shared/config/moods.json` is the single source; `GET /admin/shared-lists/moods`
 * hands out its ids. Both places that offer moods (the character placement
 * editor and the effects editor) call this hook, so the list cannot drift
 * apart the way the two hand-maintained copies did.
 *
 * There is deliberately no hard-coded fallback: while the request is in
 * flight — or if it fails — the list is empty, and the field stays usable
 * because a mood is free text in the backend anyway. A stand-in list would
 * just be the drift again.
 */
import { useEffect, useState } from 'react'
import { apiGet } from './api'

let cached: string[] | null = null
let inFlight: Promise<string[]> | null = null

function fetchMoods(): Promise<string[]> {
  if (cached) return Promise.resolve(cached)
  if (!inFlight) {
    inFlight = apiGet<{ moods?: string[] }>('/admin/shared-lists/moods')
      .then((r) => {
        cached = r?.moods ?? []
        return cached
      })
      .catch(() => [])
      .finally(() => { inFlight = null })
  }
  return inFlight
}

/** Mood ids in catalog order; `[]` while loading or when the read failed. */
export function useMoods(): string[] {
  const [moods, setMoods] = useState<string[]>(cached ?? [])
  useEffect(() => {
    let alive = true
    fetchMoods().then((list) => { if (alive) setMoods(list) })
    return () => { alive = false }
  }, [])
  return moods
}
