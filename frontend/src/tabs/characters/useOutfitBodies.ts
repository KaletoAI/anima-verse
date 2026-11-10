/**
 * useOutfitBodies — the character's outfit bodies as
 * `GET /characters/{name}/outfit-bodies` reports them
 * (`app/core/outfit_bodies.py::info`), polled every 3 s while a run of the
 * tab waits or works (slower after ~2 min, like useBaseBody), stopped on
 * unmount / character switch. `refreshKey` reloads once (a template save may
 * have switched the mode).
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { apiGet } from '../../lib/api'
import type { ImageTileMeta } from './RefImage'
import type { Freshness } from './FreshnessBadge'
import type { ModelStep } from './ModelSteps'
import type { CollisionPayload } from '@anima/scene-render'

export const BODY_VIEWS = ['front', 'back', 'left', 'right'] as const
export type BodyView = typeof BODY_VIEWS[number]
export type RunKind = 'regenerate' | 'rerig' | 'refit' | 'view'

/** One dressed view of an outfit body (`outfit_bodies.view_infos`). */
export interface BodyViewInfo {
  /** The texture store's current view (`source` "texture"), else the body's mesher input ("body"). */
  url: string | null
  /** Tile meta incl. the server's freshness (`outfit_body_view_freshness`). */
  meta: ImageTileMeta | null
  source: 'texture' | 'body' | null
  /** running · queued (a view run of the tab) · failed (its last run) · "" */
  status: '' | 'running' | 'queued' | 'failed'
  queue_position: number | null
  error: string
  /** The kept fit's gate warning. */
  warning: string
  /** Why it cannot be rendered now (server English), "" when it can. */
  blocked: string
}

export interface BodyOutfit {
  signature: string
  /** Saved outfit name, else the piece names joined. */
  name: string
  worn: boolean
  /** Why this outfit's model is older than the body (`outfit_body_stale`). */
  stale_reason: 'body_mode' | 'outfit_body' | null
}

export interface BodyFit {
  item_id: string
  name: string
  fsig: string | null
  /** accepted · stale · outdated · missing · failed · no_base_fit */
  status: string
  error: string
  created_at: string | null
}

export interface OutfitBody {
  body_id: string
  texture_signature: string | null
  /** running · queued · failed · missing · unrigged · ready */
  status: string
  error: string
  run_kind: RunKind | 'build' | null
  queue_position: number | null
  last_run: { kind: RunKind; view?: BodyView | null; ok: boolean; error: string; finished_at: string;
    detail?: { fitted?: string[]; failed?: { name: string; error: string }[] } } | null
  created_at: string | null
  url: string | null
  views: Partial<Record<BodyView, string | null>>
  image_meta?: Partial<Record<BodyView, ImageTileMeta | null>>
  used_views?: string[]
  view_warnings?: string[]
  dress_text: string
  freshness: Freshness | null
  /** Per dressed view: image, freshness, run state, why it cannot render. */
  view_info?: Partial<Record<BodyView, BodyViewInfo>>
  outfits: BodyOutfit[]
  steps: ModelStep[]
  collision?: CollisionPayload | null
  fits: BodyFit[]
  can_regenerate: boolean
  regenerate_from: string | null
  can_rerig: boolean
}

export interface PaintedBody {
  texture_signature: string
  outfits: Omit<BodyOutfit, 'stale_reason'>[]
  views: Partial<Record<BodyView, string | null>>
  image_meta?: Partial<Record<BodyView, ImageTileMeta | null>>
  painted: boolean
  dress_text: string
}

export interface QueueEntry { kind: RunKind; body_id: string; item_id?: string | null; view?: BodyView }

export interface OutfitBodiesInfo {
  humanoid: boolean
  pipeline: boolean
  mode: 'retexture' | 'mesh'
  signature: string
  bodies: OutfitBody[]
  textures: PaintedBody[]
  queue: { running: QueueEntry | null; waiting: QueueEntry[] }
  /** Another 3D run of the character holds the generation guard. */
  generation_running: boolean
  active: boolean
}

const POLL_MS = 3000
const POLL_SLOW_MS = 15000
const POLL_SLOW_AFTER = 40

export function useOutfitBodies(character: string, refreshKey = '') {
  const enc = encodeURIComponent(character)
  const [info, setInfo] = useState<OutfitBodiesInfo | null>(null)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const pollIdRef = useRef(0)

  const stopPoll = useCallback(() => {
    pollIdRef.current += 1
    if (timerRef.current) clearTimeout(timerRef.current)
    timerRef.current = null
  }, [])

  const startPoll = useCallback(
    (delayMs = 0) => {
      stopPoll()
      const id = pollIdRef.current
      let n = 0
      const tick = async () => {
        timerRef.current = null
        let d: OutfitBodiesInfo | null = null
        try {
          d = await apiGet<OutfitBodiesInfo>(`/characters/${enc}/outfit-bodies`)
        } catch {
          d = null
        }
        if (pollIdRef.current !== id) return
        setInfo(d)
        if (!d?.active) return
        n += 1
        timerRef.current = setTimeout(tick, n >= POLL_SLOW_AFTER ? POLL_SLOW_MS : POLL_MS)
      }
      timerRef.current = setTimeout(tick, delayMs)
    },
    [enc, stopPoll],
  )

  useEffect(() => {
    setInfo(null)
    if (!character) return stopPoll
    startPoll()
    return stopPoll
  }, [character, startPoll, stopPoll])

  // A saved template change (the mode) reloads once.
  const firstKey = useRef(refreshKey)
  useEffect(() => {
    if (refreshKey === firstKey.current) return
    firstKey.current = refreshKey
    startPoll()
  }, [refreshKey, startPoll])

  return { info, startPoll }
}
