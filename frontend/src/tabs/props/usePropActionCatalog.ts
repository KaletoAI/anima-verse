import { useEffect, useState } from 'react'
import { apiGet } from '../../lib/api'
import type { ActionCatalog, ActionPresentation } from './propActionAuthoring'

const EMPTY: ActionCatalog = { status: 'loading', stats: [], conditions: [], poses: [], kinds: [], pairKinds: [], groups: {} }
let inFlight: Promise<ActionCatalog> | undefined
function loadCatalog(): Promise<ActionCatalog> {
  inFlight ??= Promise.all([
    apiGet<{ keys: string[] }>('/world/stat-keys'),
    apiGet<{ conditions: ActionCatalog['conditions'] }>('/world/conditions/list'),
    apiGet<{ entries: ActionPresentation[]; kinds: string[]; pair_kinds: string[]; groups: ActionCatalog['groups'] }>('/poses?axis=pose'),
  ]).then(([stats, conditions, poses]) => ({
    status: 'ready' as const, stats: stats.keys, conditions: conditions.conditions,
    poses: poses.entries, kinds: poses.kinds, pairKinds: poses.pair_kinds, groups: poses.groups,
  })).finally(() => { inFlight = undefined })
  return inFlight
}

/** The same real sources as EffectsEditor, states and the pose editor; no fallback vocabulary. */
export function usePropActionCatalog() {
  const [catalog, setCatalog] = useState<ActionCatalog>(EMPTY)
  const [reload, setReload] = useState(0)
  useEffect(() => {
    let alive = true
    setCatalog(previous => ({ ...previous, status: 'loading' }))
    loadCatalog().then(next => { if (alive) setCatalog(next) })
      .catch(() => { if (alive) setCatalog(previous => ({ ...previous, status: 'error' })) })
    return () => { alive = false }
  }, [reload])
  return { catalog, reloadActionCatalog: () => setReload(value => value + 1) }
}
