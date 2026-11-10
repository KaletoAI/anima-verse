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
import type { CollisionPayload } from '@anima/scene-render'
import type { FaceCleanupState, FaceFields } from './ModelFaceActions'

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
  /** The base body's capsule set — the one every outfit model inherits
   *  (characters.py `_base_body_model_extras`, `collision.ensure`). */
  collision?: CollisionPayload | null
}

/** The base model's face fields (`model3d.face_info`), merged into `model`. */
export type BaseModelWithFace = BaseModelInfo & FaceFields

/** The current outfit's model on the pipeline. */
export interface BaseOutfitInfo {
  signature: string
  /** stale = built on an older base body (or before the pipeline, for
   *  another body detail, or with an own-mesh piece painted on that has its
   *  garment mesh now). */
  status: 'running' | 'failed' | 'stale' | 'ready' | 'missing'
  error: string
  /** Why a stale model is stale; null unless status is stale. */
  stale_reason: 'older_base' | 'before_pipeline' | 'detail_changed' | 'mesh_item_ready' | null
  /** Warnings of the stored model: dressed views left out because the
   *  edit turned the figure around, own-mesh pieces left painted on
   *  (server English text). */
  warnings: string[]
  /** The retexture worker's proof (None for an undressed base copy). */
  proof: Record<string, unknown> | null
  url: string | null
}

/** One side of a pair tip group (`extension_tip.tip_panels`); every
 *  position/direction is in the model's own glTF frame, metres. */
export interface ExtensionTipSide {
  side: 'left' | 'right'
  /** Where the tip goes without an offset: the colour marker or the
   *  geometry crest. */
  suggested: [number, number, number]
  /** The built tip (stub base), null while the group was not built. */
  tip: [number, number, number] | null
  /** Surface tangents at the suggestion: up, and away from the midline. */
  tangent_up: [number, number, number]
  tangent_out: [number, number, number]
  /** [up, out] mm the built tip was moved by. */
  offset_mm: [number, number]
}

export interface ExtensionTipDisc {
  enabled: boolean
  color: string
  diameter_mm: number
  soft_mm: number
}

export interface ExtensionTipOverride {
  offsets: Array<{ up: number; out: number }>
  mirror: boolean
  disc: ExtensionTipDisc
}

/** A pair tip extension group of the base model (`extension_tips`). */
export interface ExtensionTipPanelInfo {
  id: string
  /** The group's declared label, else its id. */
  label: string
  /** This model's own switch (extension_rig_models[sig][group].enabled,
   *  the 3D tab's Enabled box). */
  enabled: boolean
  /** Whether the build uses the group — false also when its source group is off. */
  active: boolean
  status: string
  reason: string
  tip_source: 'colour' | 'geometry' | null
  sides: Array<ExtensionTipSide | null>
  /** The stored override (null = none). */
  override: ExtensionTipOverride | null
  /** The last build's disc result. */
  disc: { status: string; reason: string; pixels: number } | null
  limits: { offset_max_mm: number; diameter_mm: [number, number]; soft_max_mm: number
    disc_defaults: ExtensionTipDisc }
  /** An Apply of this model runs now. */
  running: boolean
  /** The last Apply's error ('' when it succeeded). */
  error: string
}

export interface BaseBodyInfo {
  pipeline: boolean
  humanoid: boolean
  signature: string
  images: Partial<Record<BaseView, string | null>>
  /** Per stored view: model, creation time and freshness for the image tile. */
  image_meta?: Partial<Record<BaseView, ImageTileMeta | null>>
  status: Partial<Record<BaseView, BaseViewStatus>>
  model: BaseModelWithFace | null
  outfit: BaseOutfitInfo | null
  /** The face cleanup of the base source (`model3d.face_cleanup_state`). */
  face_cleanup?: FaceCleanupState | null
  /** The stored collision region scales (`model3d_opts.collision_scales`). */
  collision_scales?: Record<string, number>
  /** The base model's pair tip groups (characters.py `_base_body_model_extras`). */
  extension_tips?: ExtensionTipPanelInfo[]
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

/** A tip Apply (extension rebuild of the base model) runs. */
export const tipsRunning = (d: BaseBodyInfo | null | undefined) =>
  !!d?.extension_tips?.some((group) => group.running)

const isActive = (d: BaseBodyInfo | null | undefined) =>
  viewsRunning(d) || modelRunning(d) || !!d?.face_cleanup?.running || tipsRunning(d)

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
