/**
 * useBaseBody — the character's base body as `GET /characters/{name}/base-body`
 * reports it (`app/core/base_body.py::base_info`), polled while anything of it
 * runs: a base view render, the base model, or the current outfit's model on
 * the pipeline. Same poll pattern as FieldModelRefs: one load, then a 3 s
 * tick while active (no give-up — a render may wait minutes in the queue;
 * after ~2 min the tick slows down), stopped on unmount / character switch.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { apiGet } from '../../lib/api'
import type { ImageTileMeta } from './RefImage'
import type { Freshness } from './FreshnessBadge'
import type { ModelStep } from './ModelSteps'

export const BASE_VIEWS = ['front', 'back', 'left', 'right'] as const
export type BaseView = typeof BASE_VIEWS[number]

/** Per-view render state (system-time stamps). */
export interface BaseViewStatus {
  running: boolean
  started_at?: string | null
  failed: boolean
  error?: string | null
  failed_at?: string | null
  /** A caveat on a view that was stored anyway (the front's hand check). */
  warning?: string | null
}

/** Base model of the CURRENT base signature. */
export interface BaseModelInfo {
  signature: string
  url: string | null
  created_at: string | null
  /** running · failed (run error, or the rig failed on a static mesh) ·
   *  unrigged (static checkpoint without a run) · ready */
  status: 'running' | 'failed' | 'unrigged' | 'ready'
  error: string
  /** What was done to the stored model, step by step (server,
   *  app/core/model_overview.py) — absent while none is stored. */
  steps?: ModelStep[]
  /** Built from the base views stored now? */
  freshness?: Freshness | null
}

/** The current outfit's model on the pipeline. */
export interface BaseOutfitInfo {
  signature: string
  /** stale = built on an older base body (or before the pipeline). */
  status: 'running' | 'failed' | 'stale' | 'ready' | 'missing'
  error: string
  /** Why a stale model is stale; null unless status is stale. */
  stale_reason: 'older_base' | 'before_pipeline' | null
  /** View-guard warnings of the stored model: dressed views left out
   *  because the edit turned the figure around (server English text). */
  warnings: string[]
  /** The retexture worker's proof (None for an undressed base copy). */
  proof: Record<string, unknown> | null
  url: string | null
}

export interface BaseBodyInfo {
  pipeline: boolean
  humanoid: boolean
  signature: string
  images: Partial<Record<BaseView, string | null>>
  /** Per stored view: model, creation time and freshness for the image tile. */
  image_meta?: Partial<Record<BaseView, ImageTileMeta | null>>
  status: Partial<Record<BaseView, BaseViewStatus>>
  model: BaseModelInfo | null
  outfit: BaseOutfitInfo | null
  now?: string
}

const POLL_MS = 3000
const POLL_SLOW_MS = 15000
const POLL_SLOW_AFTER = 40

export const viewsRunning = (d: BaseBodyInfo | null | undefined) =>
  BASE_VIEWS.some((v) => !!d?.status?.[v]?.running)

/** A 3D run of this character (base model or outfit model) — they share one
 *  per-character guard on the server, so either blocks both buttons. */
export const modelRunning = (d: BaseBodyInfo | null | undefined) =>
  d?.model?.status === 'running' || d?.outfit?.status === 'running'

const isActive = (d: BaseBodyInfo | null | undefined) => viewsRunning(d) || modelRunning(d)

export function useBaseBody(character: string) {
  const enc = encodeURIComponent(character)
  const [info, setInfo] = useState<BaseBodyInfo | null>(null)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  // Poll generation: a tick of a stopped/restarted chain drops its result.
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
        let d: BaseBodyInfo | null = null
        try {
          d = await apiGet<BaseBodyInfo>(`/characters/${enc}/base-body`)
        } catch {
          d = null
        }
        if (pollIdRef.current !== id) return
        setInfo(d)
        if (!isActive(d)) return
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

  return { info, setInfo, startPoll }
}
