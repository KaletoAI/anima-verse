/**
 * useGarment — the character's hair as its own mesh, as
 * `GET /characters/{name}/hair` reports it (`app/routes/characters.py` →
 * `garments.garment_info`), polled while a garment run of the character
 * goes. Same poll pattern as useBaseBody: one load, then a 3 s tick while a
 * step runs (no give-up — an edit may wait minutes in the GPU queue; after
 * 40 ticks the tick slows down), stopped when nothing runs, on unmount and
 * on a character switch.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { apiGet } from '../../lib/api'
import type { ImageTileMeta } from './RefImage'

export const GARMENT_VIEWS = ['front', 'back'] as const
export type GarmentView = typeof GARMENT_VIEWS[number]

export const GARMENT_IMAGE_STEPS = ['haired', 'ghost', 'cutout'] as const
export type GarmentImageStep = typeof GARMENT_IMAGE_STEPS[number]
export type GarmentStep = GarmentImageStep | 'mesh' | 'hairdeck' | 'fit'

/** One gate record (`garment_gates.haired_gate` / `ghost_gate`, a mesh
 *  attempt, the fit gates) — numbers plus `ok` and `reasons`. */
export type GateRecord = Record<string, unknown> & { ok?: boolean; reasons?: string[] }

export interface GarmentImageInfo extends ImageTileMeta {
  /** The accepted final (or the last stored file), versioned; null = none. */
  url: string | null
  accepted: boolean
  /** Every attempt's gate record of the final, keyed first/second. */
  gates: Record<string, GateRecord> | null
  /** Attempt files on disk (refused or replaced attempts), each with the
   *  tile meta (model, creation time) of its own sidecar. */
  attempts: Array<ImageTileMeta & { attempt: number; gate: GateRecord | null; url: string }>
  /** Cut-out only: the routed upscale (`status` applied · lanczos · not_needed). */
  upscale?: Record<string, unknown> | null
  side?: number | null
}

export interface GarmentMeshInfo {
  status: 'accepted' | 'refused' | 'missing'
  metrics: {
    largest_component_share?: number
    tris_raw?: number
    tris_prepared?: number
    ratio?: number
    backend?: string
  }
  /** One record per attempt. */
  gates: GateRecord[]
  tris: number | null
  created_at: string | null
}

export interface GarmentFitInfo {
  /** accepted (current) · stale / outdated (older inputs) · missing */
  status: 'accepted' | 'stale' | 'outdated' | 'missing'
  metrics: Record<string, number>
  /** HairDeck fits: the colour the fit used. */
  colour?: { target: string | null; source: string } | null
  gates: { ok?: boolean; reasons?: string[] }
  tris: number | null
  low: { ok: boolean; tris?: number; ratio?: number; error?: string } | null
  base_signature: string | null
  created_at: string | null
}

/** How the hair mesh is made (`garment_hair.HAIR_METHODS`). */
export type HairMethod = 'edit_chain' | 'hairdeck'

/** One HairDeck tile (`garments.hairdeck_panel` images): null = no file. */
export type HairDeckImage = (ImageTileMeta & { url: string }) | null

/** The HairDeck section of the CURRENT hsig (`garments.hairdeck_panel`). */
export interface HairDeckPanel {
  hsig: string
  /** accepted · refused (no hair found / a file missing) · missing (not run) */
  status: 'accepted' | 'refused' | 'missing'
  attempt: number | null
  seed: number | null
  backend: string | null
  created_at: string | null
  error: string | null
  notes: string[]
  /** The refused fit attempts of the job (gate records with `metrics`). */
  attempts: GateRecord[]
  images: Record<'input' | 'prep' | 'model_input', HairDeckImage>
  colour: {
    /** The manual `#rrggbb`, null = automatic. */
    target: string | null
    source: 'override' | 'hairdeck'
    /** HairDeck's own hair colour (info.json), null when unknown. */
    auto: string | null
  }
  /** The placement correction after the head match (`garments.hairdeck_panel`). */
  placement: HairPlacement
}

/** HairDeck placement: forward shift (metres, +z) and forward tilt (degrees). */
export interface HairPlacement {
  /** The manual values; null = automatic. */
  forward_m: number | null
  tilt_deg: number | null
  /** The forward shift used when none is set. */
  default_forward_m: number
  /** |value| bounds of a manual value. */
  limits: { forward_m: number; tilt_deg: number }
  /** What the newest HairDeck fit applied; null without one (or from before the correction). */
  fitted: {
    forward_m: number | null
    forward_source: 'default' | 'manual' | null
    tilt_deg: number | null
    tilt_source: 'auto' | 'manual' | null
    tilt_solve: string | null
    hairline_target_y: number | null
    hairline_y: number | null
  } | null
}

/** The last result of the method NOT selected (`garments.other_method_info`). */
export interface OtherMethodInfo {
  method: HairMethod
  preview_url: string | null
  created_at: string | null
  metrics: Record<string, number>
  colour?: { target: string | null; source: string } | null
  on_current_base: boolean
}

export interface GarmentFailure {
  step: string
  error: string
  /** Image steps: {view, attempts}; mesh: {attempts}; bottoms: {front, back};
   *  fit: {ok, reasons, limits, metrics}. */
  gates: Record<string, unknown> | null
  failed_at: string | null
}

export interface GarmentInfo {
  item_id: string
  kind: string
  fsig: string | null
  method: HairMethod
  method_source: 'character' | 'world'
  hsig: string | null
  description: string
  steps: {
    haired?: Partial<Record<GarmentView, GarmentImageInfo>>
    ghost?: Partial<Record<GarmentView, GarmentImageInfo>>
    cutout?: Partial<Record<GarmentView, GarmentImageInfo>>
    mesh?: GarmentMeshInfo
    fit?: GarmentFitInfo
  }
  stale_reasons: Array<'description_changed' | 'base_changed' | 'base_model_changed' | 'hairdeck_changed'
    | 'colour_changed' | string>
  /** The step in flight, `queued` between the click and the first step. */
  running_step: string | null
  started_at: string | null
  failed: GarmentFailure | null
  preview_url: string | null
  served_fsig: string | null
}

/** A chip limit (`garment_gates.limits` + mesh + fit in the route). */
export interface GateLimit {
  op: 'lt' | 'le' | 'ge' | 'abs_le' | 'range'
  value: number | [number, number]
  /** The limit is a fraction of the record's image height `H`. */
  per_height?: boolean
  /** Gated on these views only. */
  views?: string[]
}

export interface HairInfo {
  pipeline: boolean
  humanoid: boolean
  description: string
  behind_shoulders: boolean
  item_id: string | null
  equipped: boolean
  garment: GarmentInfo | null
  collision: boolean
  limits: Partial<Record<'haired' | 'ghost' | 'mesh' | 'fit' | 'hairdeck_fit', Record<string, GateLimit>>>
  /** The hair method in effect and where it comes from; the world default. */
  method: HairMethod
  method_source: 'character' | 'world'
  world_method: HairMethod
  /** The HairDeck section (null without a hair item). */
  hairdeck: HairDeckPanel | null
  /** The other method's last result (null without one). */
  other: OtherMethodInfo | null
}

const POLL_MS = 3000
const POLL_SLOW_MS = 15000
const POLL_SLOW_AFTER = 40

export const garmentRunning = (d: HairInfo | null | undefined) => !!d?.garment?.running_step

export function useGarment(character: string) {
  const enc = encodeURIComponent(character)
  const [info, setInfo] = useState<HairInfo | null>(null)
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
        let d: HairInfo | null = null
        try {
          d = await apiGet<HairInfo>(`/characters/${enc}/hair`)
        } catch {
          d = null
        }
        if (pollIdRef.current !== id) return
        setInfo(d)
        if (!garmentRunning(d)) return
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
