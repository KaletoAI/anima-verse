/**
 * useGarment — one garment info route, polled while a garment run goes:
 * the Hair tab's `GET /characters/{name}/hair` or the Wardrobe's
 * `GET /characters/{name}/garments/{item}` (`app/routes/characters.py` →
 * `garments.garment_info` under the payload's `garment`). Same poll pattern
 * as useBaseBody: one load, then a 3 s tick while a step runs (no give-up —
 * an edit may wait minutes in the GPU queue; after 40 ticks the tick slows
 * down), stopped when nothing runs, on unmount and when the URL changes
 * (another character or item; null = nothing to load).
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { apiGet } from '../../lib/api'
import type { ImageTileMeta } from './RefImage'
import type { Freshness } from './FreshnessBadge'

export const GARMENT_VIEWS = ['front', 'back'] as const
export type GarmentView = typeof GARMENT_VIEWS[number]

/** The image steps of both kinds: hair haired → ghost → cutout, clothing
 *  worn → ghost → cutout (`garment_store.GARMENT_STEPS`). */
export type GarmentImageStep = 'haired' | 'worn' | 'ghost' | 'cutout'
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
  /** The seed the fit chose (else the newest HairDeck run's seed). */
  seed: number | null
  /** The newest HairDeck run's seed. */
  job_seed: number | null
  /** How many seeds HairDeck has made for this hsig. */
  seeds_tried: number
  backend: string | null
  created_at: string | null
  error: string | null
  notes: string[]
  /** The refused fit attempts of the job (gate records with `metrics`). */
  attempts: GateRecord[]
  images: Record<'input' | 'prep' | 'model_input', HairDeckImage>
  /** `beard_free` when the input tile is the profile picture with the beard removed (facial hair). */
  input_source?: 'beard_free' | 'profile'
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
  /** Current / outdated of its preview (server, model_overview.annotate_hair). */
  preview_freshness?: Freshness | null
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
    worn?: Partial<Record<GarmentView, GarmentImageInfo>>
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
  /** Current fsig fit on screen, or an older one and why (server). */
  preview_freshness?: Freshness | null
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

/** The row chip of an own-mesh piece (`garment_set.piece_status`). */
export interface PieceStatus {
  /** How far the chain of the current fingerprint got (`running` wins). */
  state: 'running' | 'fitted' | 'mesh' | 'images' | 'missing'
  /** The step in flight while running. */
  step: string | null
  /** Worn without an accepted fit: the outfit build paints it onto the body. */
  painted: boolean
  /** Why it is painted on (server text, the outfit warning's words). */
  reason: string | null
  /** Names of the worn own-mesh pieces under this one that have a fit: it is fitted over them
   *  (absent when nothing is worn under it). */
  over?: string[]
  /** Names of the worn own-mesh pieces under this one without a fit (painted on): fitted without them. */
  without?: string[]
}

/** GET /characters/{n}/garments — the Wardrobe's own-mesh overview. */
export interface WardrobeGarments {
  pipeline: boolean
  /** Every own-mesh piece the character holds or wears. */
  items: Record<string, PieceStatus>
  /** Worn own-mesh pieces that are over each other: layered in slot order (inner first). */
  overlaps: Array<{ items: string[]; slots: string[] }>
}

/** GET /characters/{n}/garments/{item} — the Wardrobe's own-mesh panel. */
export interface GarmentItemInfo {
  pipeline: boolean
  item_id: string
  name: string
  kind: string
  own_mesh: boolean
  worn: boolean
  status: PieceStatus
  garment: GarmentInfo | null
  limits: Partial<Record<string, Record<string, GateLimit>>>
}

export const garmentRunning = (d: { garment?: GarmentInfo | null } | null | undefined) => !!d?.garment?.running_step

export function useGarment<T extends { garment?: GarmentInfo | null }>(url: string | null) {
  const [info, setInfo] = useState<T | null>(null)
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
        let d: T | null = null
        try {
          d = url ? await apiGet<T>(url) : null
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
    [url, stopPoll],
  )

  useEffect(() => {
    setInfo(null)
    if (!url) return stopPoll
    startPoll()
    return stopPoll
  }, [url, startPoll, stopPoll])

  return { info, setInfo, startPoll }
}

/** The Wardrobe's own-mesh overview of a character (GET
 *  /characters/{n}/garments), loaded by `reload` — the Wardrobe calls it with
 *  its belongings; null before, and when it failed (the toggles then stay
 *  hidden). */
export function useWardrobeGarments(character: string) {
  const [data, setData] = useState<WardrobeGarments | null>(null)
  const load = useCallback(async () => {
    if (!character) { setData(null); return }
    try {
      setData(await apiGet<WardrobeGarments>(`/characters/${encodeURIComponent(character)}/garments`))
    } catch {
      setData(null)
    }
  }, [character])
  /** A panel's newer row status, without reloading the overview. */
  const setStatus = useCallback((itemId: string, status: PieceStatus) => {
    setData((prev) => (prev && prev.items[itemId] ? { ...prev, items: { ...prev.items, [itemId]: status } } : prev))
  }, [])
  return { data, reload: load, setStatus }
}
