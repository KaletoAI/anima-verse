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
import { apiGet, apiPost } from '../../lib/api'
import type { ImageTileMeta } from './RefImage'
import type { Freshness } from './FreshnessBadge'
import type { CollisionPayload } from '@anima/scene-render'
import type { GarmentRunBody } from './garmentStyle'

export const GARMENT_VIEWS = ['front', 'back'] as const
export type GarmentView = typeof GARMENT_VIEWS[number]

/** The image steps of both kinds: hair haired → ghost → cutout, clothing
 *  worn → ghost → cutout (`garment_store.GARMENT_STEPS`). */
export type GarmentImageStep = 'haired' | 'worn' | 'ghost' | 'cutout'
export type GarmentStep = GarmentImageStep | 'mesh' | 'hairdeck' | 'mesh_source' | 'cut' | 'fit'

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
  /** Subtract fits also carry the limits they were gated on (`garment_subtract.run_fit`). */
  gates: { ok?: boolean; reasons?: string[]; limits?: RecordLimits }
  tris: number | null
  low: { ok: boolean; tris?: number; ratio?: number; error?: string } | null
  base_signature: string | null
  created_at: string | null
}

/** How the hair mesh is made (`garment_hair.HAIR_METHODS`). */
export type HairMethod = 'edit_chain' | 'hairdeck' | 'subtract'

/** Gate limits as a record stores them: `{key: ["max" | "min", limit]}`
 *  (`garment_cut.CUT_GATES`, `garment_fit.hair_gates`). */
export type RecordLimits = Record<string, [string, number]>

/** The subtract method's source mesh of the haired character
 *  (`garment_subtract.step_info`, step `mesh_source`). */
export interface SubtractSourceInfo {
  status: 'accepted' | 'refused' | 'missing'
  ssig: string
  backend: string | null
  tris: number | null
  error: string | null
  /** The routed result's `route_meta()` (routing, fallback_from, …). */
  routing: Record<string, unknown> | null
  created_at: string | null
}

/** The subtract method's cut (`garment_subtract.step_info`, step `cut`):
 *  `stale` = an accepted cut made from another source mesh. */
export interface SubtractCutInfo {
  status: 'accepted' | 'stale' | 'refused' | 'missing'
  shape: 'cut' | 'shell' | null
  shell_mm: number | null
  /** registration_p95_cm, hairline_cm, label_holes, hair_area_cm2. */
  metrics: Record<string, number>
  gates: { ok?: boolean; reasons?: string[]; limits?: RecordLimits }
  /** The cut's report sections (registration, hairline, label, edge, closed, shell, cut, seconds). */
  report: Record<string, unknown>
  created_at: string | null
}

/** The subtract settings of the Hair tab (`_hair_subtract_settings`). */
export interface HairSubtractSettings {
  /** The shape in effect and where it comes from. */
  shape: 'cut' | 'shell'
  shape_source: 'character' | 'length'
  /** The stored override, "" = automatic (from the hair length). */
  shape_override: '' | 'cut' | 'shell'
  length_class: string | null
  shell_mm: number
  shell_mm_default: number
  shell_mm_min: number
  shell_mm_max: number
}

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
    /** Automatic = the profile's named hair colour (`profile`), else HairDeck's own. */
    source: 'override' | 'profile' | 'hairdeck'
    /** HairDeck's own hair colour (info.json), null when unknown. */
    auto: string | null
    /** The profile's named hair colour (`garment_hair.profile_hair_colour`), null without one. */
    profile?: { name: string; hex: string } | null
    /** The newest HairDeck fit's colour record, null without a fit. */
    fitted?: HairDeckFitColour | null
  }
  /** The placement correction after the head match (`garments.hairdeck_panel`). */
  placement: HairPlacement
}

/** The colour a HairDeck fit used (`garments._hairdeck_colour`): CIE76 ΔE of the hair's median to the target. */
export interface HairDeckFitColour {
  target: string | null
  source: 'override' | 'profile' | 'hairdeck'
  name?: string | null
  /** False: the profile colour was within reach, HairDeck's own colours were kept. */
  applied?: boolean
  delta_e_before?: number | null
  delta_e_after?: number | null
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

/** The kept result of one method NOT selected (`garments.other_methods_info`). */
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

/** `garment_info.refit`: what the refitted piece was made on. */
export interface GarmentRefit {
  source_bsig: string | null
  source_fsig: string | null
  materialized_from: string | null
  /** The ghost's registration onto the new base front (shift: fraction of the figure height). */
  registration: { shift: number | null; scale: number | null } | null
  /** The chain's first step — the Re-render run starts there. */
  first_step: string
  created_at: string | null
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
    mesh_source?: SubtractSourceInfo
    cut?: SubtractCutInfo
    fit?: GarmentFitInfo
  }
  stale_reasons: Array<'description_changed' | 'base_changed' | 'base_model_changed' | 'hairdeck_changed'
    | 'colour_changed' | string>
  /** The step in flight, `queued` between the click and the first step. */
  running_step: string | null
  started_at: string | null
  /** The 1-based place of the item's next waiting run in the character's
   *  garment queue (null = none waits) and the item id in flight (null =
   *  idle) — `garments.queue_state`; absent on an older server. */
  queue_position?: number | null
  queue_running?: string | null
  failed: GarmentFailure | null
  preview_url: string | null
  served_fsig: string | null
  /** The current fit was refitted from images + mesh made on the previous
   *  base (server `garment_source`); null otherwise / on an older server. */
  refit?: GarmentRefit | null
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
  /** A record key holding this record's own limit (same op); `value` when the record lacks it. */
  record_key?: string
}

export interface HairInfo {
  pipeline: boolean
  humanoid: boolean
  description: string
  behind_shoulders: boolean
  item_id: string | null
  equipped: boolean
  garment: GarmentInfo | null
  /** The current base model's capsule set the preview pushes the hair out of; null without one. */
  collision: CollisionPayload | null
  limits: Partial<Record<'haired' | 'ghost' | 'mesh' | 'fit' | 'hairdeck_fit', Record<string, GateLimit>>>
  /** The hair method in effect and where it comes from; the world default. */
  method: HairMethod
  method_source: 'character' | 'world'
  world_method: HairMethod
  /** The HairDeck section (null without a hair item). */
  hairdeck: HairDeckPanel | null
  /** The kept results of the other methods, newest first ([] without one). */
  others: OtherMethodInfo[]
  /** The subtract method's shape and shell thickness (null off humanoids / an older server). */
  subtract?: HairSubtractSettings | null
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

/** A step runs or the item waits in the character's garment queue
 *  (`running_step` is `queued` from the click until its first step). */
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

/** Which button a run click came from: its step and view (`|` for Run all);
 *  a caller may name its own slot (two buttons with the same body). */
export const runSlot = (body: GarmentRunBody) => `${body.step || ''}|${body.view || ''}`

/** Another garment of the character that runs or waits (overview + names). */
export interface OtherRun { id: string; name: string; step: string | null }

/** The answer of POST …/garments/{item}/run. A run of a character whose
 *  other garment runs go is QUEUED behind them (`queued`, its 1-based
 *  `position` in the character's queue, `behind` = what runs/waits before
 *  it); every key is optional — an older server answers `{started}` only. */
export interface RunAnswer {
  started?: boolean
  queued?: boolean
  position?: number | null
  behind?: unknown
}

/** What the panel shows about the user's own run clicks (useGarmentRun). */
export interface RunFeedback {
  /** The slot whose POST is in flight ("Starting…"). */
  pending: string | null
  /** The run this panel started, until it ends: the tiles it targets show
   *  Queued / Generating… / Will be redone. */
  target: GarmentRunBody | null
  /** The start answer's queue place of that run (null = not queued / unknown). */
  queue: { position: number | null; behind: string[] } | null
  /** A click that failed (a real error — a run behind the character's other
   *  garment runs is queued, never refused), shown beside that button until
   *  the next click. */
  refused: { slot: string; message: string } | null
  /** The character's OTHER garments that run or wait — loaded while this
   *  item is queued and after a refusal; null = not known. */
  others: OtherRun[] | null
  /** Item id → display name of the character's belongings (loaded with
   *  `others`), for the ids the queue answers carry. */
  names: Record<string, string>
  /** The Cancel of the item's waiting run: `pending` while the POST is in
   *  flight, `done` from its success until the poll shows the item no longer
   *  queued, `error` = the server's refusal (409 already running / 404). */
  cancel: { pending: boolean; done: boolean; error: string | null }
}

/** The queue place of a start answer; `behind` may name items (strings or
 *  `{name}`/`{item_id}` records) or count them. */
function queuePlace(answer: RunAnswer | null | undefined): RunFeedback['queue'] {
  if (!answer?.queued) return null
  const raw = answer.behind
  const behind = Array.isArray(raw)
    ? raw.map((b) => (typeof b === 'string' ? b
      : b && typeof b === 'object' ? String((b as Record<string, unknown>).name
        ?? (b as Record<string, unknown>).item_id ?? '') : '')).filter(Boolean)
    : typeof raw === 'string' && raw ? [raw] : []
  const position = typeof answer.position === 'number' ? answer.position : null
  return { position, behind }
}

/** The run tile mark of one step (and view) under the feedback. */
export type RunMark = 'queued' | 'generating' | 'redo' | null

/** How a tile of `step` (image steps: `view`) relates to the run this panel
 *  started: the targeted step waits (`queued`) or runs (`generating`); a later
 *  step of a forced run is redone after it (`redo`, until it runs) — the
 *  same view only, when the click named one. `order` = the method's steps. */
export function runMark(fb: RunFeedback | undefined, garment: GarmentInfo | null | undefined,
  order: readonly string[], step: string, view?: string): RunMark {
  const target = fb?.target
  const running = garment?.running_step
  if (!target?.step || !running) return null
  const ti = order.indexOf(target.step)
  const si = order.indexOf(step)
  if (ti < 0 || si < ti) return null
  if (target.view && view && view !== target.view) return null
  // -1 = queued (before every step); a step of another method = unknown.
  const ri = running === 'queued' ? -1 : order.indexOf(running)
  if (running !== 'queued' && ri < 0) return null
  if (ri === si) return 'generating'
  if (ri > si) return null
  if (si === ti) return 'queued'
  return target.force ? 'redo' : null
}

/**
 * The run clicks of a garment panel: `start(body, slot?)` POSTs the run,
 * marks the clicked slot pending while the POST is in flight, keeps the
 * started run as `target` until the poll shows the item idle again, and
 * keeps a failure beside the clicked button. A run behind the character's
 * other garment runs is queued by the server (`RunAnswer`): its queue place
 * goes into `queue`. While the item is queued, the character's other
 * running garments and the item names are loaded (GET /characters/{n}/garments + the names of
 * GET /characters/{n}/belongings).
 */
export function useGarmentRun(character: string, itemId: string,
  info: { garment?: GarmentInfo | null } | null,
  startPoll: (delayMs?: number) => void) {
  const [pending, setPending] = useState<string | null>(null)
  // `since` = the info on screen when the run started: the target ends on
  // the first NEWER info that shows the item idle.
  const [target, setTarget] = useState<{ body: GarmentRunBody; since: unknown;
    queue: RunFeedback['queue'] } | null>(null)
  const [refused, setRefused] = useState<RunFeedback['refused']>(null)
  const [others, setOthers] = useState<OtherRun[] | null>(null)
  const [names, setNames] = useState<Record<string, string>>({})
  // `since` = the info on screen when the cancel answered: "Cancelled" shows
  // until a NEWER info arrives (the server's state then speaks).
  const [cancelState, setCancelState] = useState<{ pending: boolean; since: unknown; error: string | null } | null>(null)
  const infoRef = useRef(info)
  useEffect(() => { infoRef.current = info }, [info])
  const enc = encodeURIComponent(character)

  const loadOthers = useCallback(async () => {
    if (!character) return
    try {
      const [overview, belongings] = await Promise.all([
        apiGet<WardrobeGarments>(`/characters/${enc}/garments`),
        apiGet<{ items?: Array<{ item_id: string; name: string }> }>(`/characters/${enc}/belongings`)
          .catch(() => ({ items: [] })),
      ])
      const names = new Map((belongings.items || []).map((i) => [i.item_id, i.name]))
      setNames(Object.fromEntries(names))
      setOthers(Object.entries(overview.items || {})
        .filter(([id, st]) => id !== itemId && st.state === 'running')
        .map(([id, st]) => ({ id, name: names.get(id) || id, step: st.step })))
    } catch {
      setOthers(null)
    }
  }, [character, enc, itemId])

  const start = useCallback(async (body: GarmentRunBody, slot: string = runSlot(body)) => {
    if (pending !== null || !itemId) return
    setPending(slot)
    setRefused(null)
    setCancelState(null)
    try {
      const answer = await apiPost<RunAnswer>(`/characters/${enc}/garments/${encodeURIComponent(itemId)}/run`, body)
      setTarget({ body, since: info, queue: queuePlace(answer) })
      if (answer?.queued) void loadOthers()
      startPoll(300)
    } catch (e) {
      setRefused({ slot, message: e instanceof Error ? e.message : String(e) })
      startPoll()
    } finally {
      setPending(null)
    }
  }, [enc, info, itemId, loadOthers, pending, startPoll])

  /** Take the item's waiting run out of the character's garment queue
   *  (POST …/garments/{item}/cancel); a run that already started is refused
   *  (409) and its message shown beside the button. */
  const cancel = useCallback(async () => {
    if (!itemId || cancelState?.pending) return
    setCancelState({ pending: true, since: undefined, error: null })
    try {
      await apiPost(`/characters/${enc}/garments/${encodeURIComponent(itemId)}/cancel`, {})
      setTarget(null)
      setCancelState({ pending: false, since: infoRef.current, error: null })
    } catch (e) {
      setCancelState({ pending: false, since: undefined, error: e instanceof Error ? e.message : String(e) })
    } finally {
      startPoll(0)
    }
  }, [cancelState?.pending, enc, itemId, startPoll])

  const running = info?.garment?.running_step || null
  const queued = running === 'queued'
  // The cancel's "Cancelled" ends with the first newer info; its error with
  // the next run click.
  useEffect(() => {
    if (cancelState && !cancelState.pending && !cancelState.error && info !== cancelState.since) setCancelState(null)
  }, [cancelState, info])
  useEffect(() => {
    if (target && info !== target.since && !running) setTarget(null)
  }, [info, running, target])
  useEffect(() => {
    if (queued) void loadOthers()
  }, [queued, loadOthers])
  // Another item / character: nothing of the old one stays on screen.
  useEffect(() => {
    setTarget(null); setRefused(null); setOthers(null); setCancelState(null)
  }, [character, itemId])

  const feedback: RunFeedback = {
    pending, target: target?.body ?? null, queue: target?.queue ?? null, refused, others, names,
    cancel: { pending: !!cancelState?.pending, done: !!cancelState && !cancelState.pending && !cancelState.error,
      error: cancelState?.error ?? null },
  }
  return { feedback, start, cancel }
}
