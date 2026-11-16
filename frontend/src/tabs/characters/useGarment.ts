/**
 * useGarment — one garment info route, polled while a garment run goes (and, Ruling A46b, while accepted
 * images are re-gated under the current gate version):
 * the hair row's `GET /characters/{name}/hair` or the Wardrobe's
 * `GET /characters/{name}/garments/{item}` (`app/routes/characters.py` →
 * `garments.garment_info` under the payload's `garment`). Same poll pattern
 * as useBaseBody: one load, then a 3 s tick while a step runs (no give-up —
 * an edit may wait minutes in the GPU queue; after 40 ticks the tick slows
 * down), stopped when nothing runs, on unmount and when the URL changes
 * (another character or item; null = nothing to load).
 */
import type { UseUndoState } from './refusedAttemptsModel'
import type { FitSettingsInfo } from './fitSettingsModel'
import type { AllowanceView } from './fitWiden'
import type { FootwearAllowanceView } from './footwearAllowanceModel'
import { useCallback, useEffect, useRef, useState } from 'react'
import { apiGet, apiPost, type BootHemState } from '../../lib/api'
import type { ImageTileMeta } from './RefImage'
import type { Freshness } from './FreshnessBadge'
import type { CollisionPayload, FootPose } from '@anima/scene-render'
import type { GarmentRunBody } from './garmentStyle'
import type { MeshMode } from './figureModel'
import type { HaarPanel } from './hairstylesModel'

export const GARMENT_VIEWS = ['front', 'back'] as const
export type GarmentView = typeof GARMENT_VIEWS[number]

/** The image steps of clothing: worn → ghost → cutout (`garment_store.GARMENT_STEPS`). */
export type GarmentImageStep = 'worn' | 'ghost' | 'cutout'
export type GarmentStep = GarmentImageStep | 'mesh' | 'hairdeck' | 'fit'

/** One gate record (an image step's gate, a mesh
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
  /** Ruling A60, cut-out only: the opening it was made with (null: made before the openings were looked for). */
  opening?: CutoutOpening | null
  /** The drafted back is an EMPTY composite: the base back unchanged. */
  empty?: boolean
  /** Why this view is not made (the steps after an empty drafted back). */
  skipped?: string | null
  /** Ruling A37: the image was taken by the user although its gate refused it ("Use this"); `holds` false once
   *  an input changed (the view is then due again). */
  user_accepted?: { at: string | null; attempt: number | null; reasons: string[]; holds: boolean } | null
  /** Ruling A46c: a piece-only view made from the worn view — its mask numbers (`garment_from_worn.piece_mask`). */
  from_worn?: FromWornNumbers | null
}

/** The mask numbers of a piece-only view made from the worn view (`garment_from_worn.piece_mask`). */
export interface FromWornNumbers {
  /** The piece's pixels over the figure's. */
  piece_share?: number
  piece_px?: number
  figure_px?: number
  holes_filled?: number
  skin_removed_px?: number
  /** Set when the skin step was skipped (the piece has the skin's colour). */
  skin_removed?: string
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
  /** Ruling A58: the mesh in use was chosen with "Use this" although its gate refused it. */
  user_accepted?: boolean
  /** Ruling A58: the piece's mesh job of this fingerprint in flight; null when none runs. */
  job?: GarmentMeshJob | null
  /** Ruling A48a: the Mesh row's 3D view — the mesh files and the kept meshes with their files. */
  view?: GarmentMeshView
}

/** Ruling A58: the running mesh job of a piece — since when, which hub job of how many, and whether another mesh
 *  was chosen during it (`chosen`: its result then stays a kept mesh). */
export interface GarmentMeshJob {
  id: string
  started_at: string
  hub_jobs: number
  max_hub_jobs: number
  phase: 'starting' | 'hub' | 'prepare' | 'publish' | string
  chosen: boolean
}

/** One mesh file of the Mesh row (Ruling A48a): `url` versioned by content, `body_url` its body view (JSON). */
export interface GarmentMeshFile { url: string; body_url: string; tris: number | null }

/** A kept mesh of the piece (Ruling A58): a refused attempt (`attempt`), the mesh in use before a run or a pick
 *  replaced it (`previous`), a result that finished while another mesh was chosen (`job`) — or an attempt that
 *  failed outright (`failed`, `attempt` 0, no files). `attempt` is its slot (the URLs' `attempt=`). */
export interface GarmentMeshAttempt {
  attempt: number
  origin: 'attempt' | 'previous' | 'job' | 'failed'
  ok: boolean
  reasons: string[]
  error: string
  created_at?: string | null
  backend?: string
  /** The attempt number within its run. */
  run_attempt?: number | null
  /** Finished while another mesh was chosen — kept, not applied. */
  chosen_during_job?: boolean
  /** Why "Use this" waits ("" when it can). */
  use_block?: string
  tris_raw?: number | null
  tris_prepared?: number | null
  largest_component_share?: number | null
  prepared: GarmentMeshFile | null
  raw: GarmentMeshFile | null
}

export interface GarmentMeshView {
  prepared: GarmentMeshFile | null
  raw: GarmentMeshFile | null
  /** Ruling A48d: the shell from the body of the last shell fit (none before one). */
  shell?: GarmentMeshFile | null
  attempts: GarmentMeshAttempt[]
}

/** `GET …/mesh/{which}/body` (Ruling A48a): the share of the mesh's area inside the base body and the overlays. */
export interface GarmentMeshBodyView {
  key: string
  share: number
  face_share: number
  faces: number
  inside_faces: number
  bsig: string
  placement: { scale: number; offset: [number, number, number]; k: number }
  computed_at: string
  seconds: number
  ghost_url: string
  inside_url: string | null
  /** Ruling A48c: the fit allowance's axis and, per factor, the share inside and the trunk gap. */
  allowance?: AllowanceView
}

export interface GarmentFitInfo {
  /** accepted (current) · stale / outdated (older inputs) · missing */
  status: 'accepted' | 'stale' | 'outdated' | 'missing'
  metrics: Record<string, number>
  /** HairDeck fits: the colour the fit used. */
  colour?: { target: string | null; source: string } | null
  /** A fit may carry the limits it was gated on (`RecordLimits`). */
  gates: { ok?: boolean; reasons?: string[]; limits?: RecordLimits }
  tris: number | null
  low: { ok: boolean; tris?: number; ratio?: number; error?: string } | null
  base_signature: string | null
  created_at: string | null
  /** Ruling A69: the fit in use was refused by its checks and accepted by the user (the reason in plain words, the
   *  measured reasons in `detail`); null/absent otherwise. */
  user_accepted?: { at: string | null; reason: string; detail: string } | null
}

/** How the hair is made (`garment_hair.HAIR_METHODS`); `body` = inside the body mesh, no hair mesh. */
export type HairMethod = 'body' | 'hairdeck' | 'haar'

/** Gate limits as a record stores them: `{key: ["max" | "min", limit]}`. */
export type RecordLimits = Record<string, [string, number]>

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
  /** The spring chains of the newest HairDeck fit and the Swing/Stiffness settings (`hair_motion.panel`). */
  chains?: HairChains
}

/** HairDeck spring chains (`hair_motion.panel`). Swing is a fit input (off = today's hair, re-fitted on change);
 *  Stiffness changes only the motion. */
export interface HairChains {
  /** The bound chains of the newest fit; null when `fitted` is false. */
  count: number | null
  /** How many joints swing (counted with Swing on). */
  links: number
  swing: boolean
  /** The factor on HairDeck's per-chain stiffness (1 = as generated). */
  stiffness: number
  /** [lo, hi] of the Stiffness factor. */
  limits: [number, number]
  /** False: no fit yet, or one from before the spring chains. */
  fitted: boolean
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

/** HairDeck placement: forward shift (metres, +z), forward tilt (degrees),
 *  hair width (scale of the sides' reach beyond the head, 1 = HairDeck's own)
 *  and up/down shift (metres, +y; Ruling A85). */
export interface HairPlacement {
  /** The manual values; null = automatic (width: 1, up/down: none). */
  forward_m: number | null
  tilt_deg: number | null
  width_scale: number | null
  up_m: number | null
  /** The forward shift used when none is set. */
  default_forward_m: number
  /** |value| bounds of forward and up/down; [lo, hi] of the tilt (back −15 … forward +30) and of the width. */
  limits: { forward_m: number; tilt_deg: [number, number]; up_m: number; width_scale: [number, number] }
  /** What the newest HairDeck fit applied; null without one (or from before the correction). */
  fitted: {
    forward_m: number | null
    forward_source: 'default' | 'manual' | null
    tilt_deg: number | null
    tilt_source: 'auto' | 'manual' | null
    tilt_solve: string | null
    width_scale?: number | null
    width_source?: 'auto' | 'manual' | null
    up_m?: number | null
    up_source?: 'manual' | 'none' | null
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

/** Ruling A46, "Piece-only views from": the setting of one view (server `garment_from_worn`). */
export type PieceViewChoice = 'auto' | 'generated' | 'worn'
/** What a piece-only view is made from: the image edit or the worn view minus the body. */
export type PieceViewSource = 'generated' | 'worn'
/** One step a source change makes due (`garments._piece_view_due`): first attempts; the fit is CPU work. */
export interface PieceViewDue { step: 'ghost' | 'cutout' | 'mesh' | 'fit'; view?: GarmentView; jobs: number }
/** Where a choice makes the view come from, why (`why` keys `garment_from_worn.REASONS`, `detail` a gate
 *  reason or a reach, shown as it is) and what it makes due. */
export interface PieceViewOption {
  source: PieceViewSource
  why: string
  detail: string
  reason: string
  due: PieceViewDue[]
}
/** One view's "Piece-only views from" (`garments.piece_views_info`): the setting, its effect now, the source of
 *  the accepted image (null without one) and every choice's effect before it is saved. */
export interface PieceViewInfo extends Partial<PieceViewOption> {
  choice: PieceViewChoice
  auto?: boolean
  made_from?: PieceViewSource | null
  options?: Record<PieceViewChoice, PieceViewOption>
  /** The view is not made (an empty drafted back). */
  skipped?: boolean
  /** Ruling A46b: its accepted image is being re-gated under the current gate version — the source shown is the
   *  stored verdict's until the next poll ("Checking…"). */
  checking?: boolean
}

/** Ruling A60, "Openings from the worn view": the setting of one cut-out view (server `garment_openings`). */
export type CutoutOpeningChoice = 'auto' | 'off'
/** The opening a cut-out was made with: `found` the worn view shows enclosed body inside the piece, `applied` it is
 *  cut (Auto), `share` its pixels over the cut-out's garment pixels, `reason` why none was found. */
export interface CutoutOpening {
  applied?: boolean
  found?: boolean
  px?: number | null
  share?: number | null
  choice?: CutoutOpeningChoice
  reason?: string | null
}
/** One view's "Openings from the worn view" (`garments.cutout_openings_info`): the setting, the cut-out's record,
 *  what is due now and what each choice would make due before it is saved. */
export interface CutoutOpeningInfo {
  choice: CutoutOpeningChoice
  made?: boolean
  opening?: CutoutOpening | null
  /** Made before the openings were looked for: current; its own button makes it again on the CPU. */
  legacy?: boolean
  /** Made again, the cut-out reuses its own colours (no hub job). */
  reusable?: boolean
  due?: PieceViewDue[]
  options?: Record<CutoutOpeningChoice, { due: PieceViewDue[] }>
  skipped?: boolean | string
}

export interface GarmentInfo {
  item_id: string
  kind: string
  fsig: string | null
  /** The hair method, or `edit_chain` for an own-mesh outfit piece. */
  method: HairMethod | 'edit_chain'
  method_source: 'character' | 'world'
  hsig: string | null
  description: string
  steps: {
    worn?: Partial<Record<GarmentView, GarmentImageInfo>>
    ghost?: Partial<Record<GarmentView, GarmentImageInfo>>
    cutout?: Partial<Record<GarmentView, GarmentImageInfo>>
    mesh?: GarmentMeshInfo
    fit?: GarmentFitInfo
  }
  stale_reasons: Array<'description_changed' | 'base_changed' | 'base_model_changed' | 'hairdeck_changed'
    | 'colour_changed' | string>
  /** The pair step's views, both accepted (Ruling A33): whether they agree, and the view a disagreeing pair
   *  renders again (`redo`) — a view button never repairs the pair; null/absent otherwise. */
  pair?: { step: string; agree: boolean; redo: GarmentView | null; error: string | null } | null
  /** The step in flight, `queued` between the click and the first step. */
  running_step: string | null
  started_at: string | null
  /** The 1-based place of the item's next waiting run in the character's
   *  garment queue (null = none waits) and the item id in flight (null =
   *  idle) — `garments.queue_state`; absent on an older server. */
  queue_position?: number | null
  queue_running?: string | null
  /** The item's CPU refit runs BESIDE the character's garment queue (Ruling A30): it waits behind
   *  nothing, so no "Queued behind …"; absent on an older server. */
  queue_beside?: boolean
  failed: GarmentFailure | null
  preview_url: string | null
  /** When the previewed fit was made (Ruling UI3 a: the preview's caption); null without one. */
  preview_built_at?: string | null
  served_fsig: string | null
  /** The current fit was refitted from images + mesh made on the previous
   *  base (server `garment_source`); null otherwise / on an older server. */
  refit?: GarmentRefit | null
  /** Current fsig fit on screen, or an older one and why (server). */
  preview_freshness?: Freshness | null
  /** Ruling A46: where each piece-only view comes from; null/absent for a piece without the choice. */
  piece_views?: Partial<Record<GarmentView, PieceViewInfo>> | null
  /** Ruling A60: per view whether the cut-out opens where the worn view shows the body; null/absent otherwise. */
  cutout_openings?: Partial<Record<GarmentView, CutoutOpeningInfo>> | null
  /** Ruling A47: the sleeves per side, the width allowance and the arm light (`garments.fit_settings_info`). */
  fit_settings?: FitSettingsInfo | null
  /** Ruling A46b: accepted images gated under an older gate version, being re-gated in the background now
   *  (`garments.regate_shown`); the panel polls until it is empty. */
  regate_checking?: Array<{ step: string; view: GarmentView }>
}

/** The run state every garment panel carries (clothing, hair and footwear alike): what the run
 *  marks, the status line and the failure block read. */
export type GarmentRunState = Pick<GarmentInfo, 'running_step' | 'started_at' | 'queue_position' | 'queue_running'
  | 'queue_beside' | 'failed'>

/** The steps of a footwear piece in chain order (`garment_store.FOOTWEAR_STEPS`): the item steps
 *  (one shoe source per item, shared by every wearer) and the per-body fit. */
export const FOOTWEAR_STEPS = ['source', 'empty', 'cutout', 'mesh', 'insole', 'fit'] as const
export type FootwearStep = typeof FOOTWEAR_STEPS[number]

/** One step of the shoe source (`garment_footwear.info` steps). `refused` = its gates refused the
 *  result, `failed` = the backend failed (`error` = the backend's own words), `waiting` = the backend
 *  was busy or media generation is off — retry later. */
export interface FootwearStepInfo {
  status: 'accepted' | 'refused' | 'failed' | 'waiting' | 'missing'
  /** The step's gate record (`ok`, `reasons` and the gated numbers). */
  gates: GateRecord
  /** The step's numbers (gate numbers, sizes, triangle counts). */
  metrics: Record<string, number>
  /** The step's file, versioned; null = none. */
  url: string | null
  /** Server-computed: Item image changed / Older source version / Older analysis version. */
  freshness: Freshness | null
  backend: string
  created_at: string | null
  error: string | null
}

/** One empty-shoe edit attempt (`empty.try{n}`). */
export interface FootwearEmptyAttempt {
  attempt: number
  ok: boolean | null
  gates: GateRecord
  seed: number | null
  backend: string
  error: string | null
  /** Why an attempt without an image failed: `backend` or `load`. */
  failure: 'backend' | 'load' | null
  url: string | null
}

/** One shoe mesh attempt. */
export interface FootwearMeshAttempt {
  attempt: number
  ok?: boolean
  gates?: GateRecord
  error?: string
  failure?: 'backend' | 'load'
}

/** The insole analysis (`insole.json`, `footwear_insole.analyse`): per-item numbers at the
 *  nominal length, the type gates and the overlay polylines in the prepared mesh's own coordinates. */
export interface FootwearInsole {
  version: number | null
  nominal: {
    k?: number
    heel_seat_h_m?: number | null
    insole_ball_h_m?: number | null
    heel_rise_m?: number | null
    pitch_deg?: number | null
    shank_slope_deg?: number | null
  } | null
  gates: GateRecord & { refusal?: string | null } | null
  /** `slabs` = per tube slab of a boot its measured extent as a closed ring (`garment_footwear._insole_view`). */
  overlay: {
    insole?: [number, number, number][]
    topline?: [number, number, number][]
    slabs?: { points: [number, number, number][]; closed: boolean }[]
  } | null
  frame: Record<string, unknown> | null
  /** A boot's shaft (class other than `none`), at the nominal length; null for a shoe. */
  shaft?: FootwearInsoleShaft | null
}

/** The shaft summary of the insole analysis (boots spec 2026-11-11 § 6.1). */
export interface FootwearInsoleShaft {
  class: 'ankle' | 'knee' | 'overknee' | string
  /** Collar height above the heel seat (m, nominal). */
  collar_h_m: number | null
  /** The top closed tube slab above the ground (m, nominal). */
  top_m: number | null
  closed_share: number | null
  /** Cap faces removed from the prepared mesh (a single-view mesher closes the opening). */
  cap_removed: number | null
  slabs: number
  slabs_closed: number
}

/** The split of a fit (`garment_footwear._split_view`): a boot splits at the wearer's ankle into a rigid
 *  foot part and a clothing-weighted shaft — four nodes per pair; a shoe carries `is_boot` false and the
 *  collar diagnostic. */
export interface FootwearFitSplit {
  is_boot: boolean
  band_m: number | null
  /** A topline more than this above the ankle makes a boot (m). */
  margin_m: number | null
  sides: Record<string, {
    y_m?: number
    topline_m?: number
    collar_above_ankle_mm?: number
    /** Faces per node part (`foot`, `shaft`). */
    parts: Record<string, number>
  }>
}

/** The shaft summary of a split fit (`garment_footwear._fit_shaft_view`), worse side. */
export interface FootwearFitShaft {
  class: string | null
  push_p95_m?: number
  push_max_m?: number
  inside_share?: number
  seam_gap_p95_mm?: number
  seam_stretch_max?: number
  leg_follow_deg?: number
  clip_m?: number
  knee_margin_m?: number
  top_m?: number
}

/** One fit gate of a footwear fit record (`footwear_fit.fit_pair`): the measured value, its limit
 *  (a number, or `[lo, hi]` for a range), whether it passed and whether it refuses a fit yet
 *  (`gating` false = recorded only, activated in a later phase). */
export interface FootwearFitGate {
  value: number | null
  limit: number | [number, number]
  ok: boolean
  gating: boolean
}

/** The fit of the current fsig on ONE body (`garment_footwear._fit_info`). `stale` = made on other body
 *  bytes or by an older fit version, `outdated` = the shoe source changed since, `refused` = the persisted
 *  refusal of this fsig holds on this body. */
export interface FootwearFitInfo {
  status: 'accepted' | 'stale' | 'outdated' | 'refused' | 'missing'
  gates: Record<string, FootwearFitGate>
  /** width_factor, width_cap, root_lift_m, k_m_per_unit, length_m and per side (`_left` / `_right`)
   *  width_needed, slim_needed, extension_deg, toe_room_mm. */
  metrics: Record<string, number>
  url: null
  freshness: Freshness | null
  created_at: string | null
  error: string | null
  /** The split and the shaft of the accepted record (null without one; `shaft` null for a shoe). */
  split?: FootwearFitSplit | null
  shaft?: FootwearFitShaft | null
}

/** One row of `fits`: the base model first, then (outfit body mode mesh) every stored outfit body. */
export interface FootwearFitRow extends FootwearFitInfo {
  /** The base signature / the outfit body id (null without a base). */
  body_id: string | null
  base: boolean
}

/** GET /characters/{n}/garments/{item} → `garment` of a footwear piece (`garment_footwear.info`). */
export interface FootwearInfo extends GarmentRunState {
  item_id: string
  kind: 'footwear'
  method: 'shoe'
  method_source: string
  description: string
  fsig: string | null
  /** The shown shoe source and the current one (they differ while the shown one is stale). */
  ssig: string
  current_ssig: string
  steps: {
    source?: FootwearStepInfo & { upscale?: Record<string, unknown> | null }
    empty?: FootwearStepInfo & { attempts?: FootwearEmptyAttempt[] }
    cutout?: FootwearStepInfo
    mesh?: FootwearStepInfo & { attempts?: FootwearMeshAttempt[] }
    insole?: FootwearStepInfo & { version?: number | null }
    fit?: FootwearFitInfo
  }
  /** item_image_changed · source_version_changed · analysis_updated */
  stale_reasons: string[]
  /** The inventory item image (read-only here), versioned. */
  item_image_url: string | null
  mesh_url: string | null
  /** When the shown shoe mesh was made (Ruling UI3 a); null without one. */
  mesh_built_at?: string | null
  insole: FootwearInsole | null
  /** The fit of the current fsig per body (base first). */
  fits: FootwearFitRow[]
  /** The width cap the next fit uses (1.00–1.10, default 1.10). */
  width_cap: number
  /** The shod base model of the current fsig (GET …/garments/{item}/model), versioned; null without one. */
  preview_url: string | null
  /** When that fit was made (Ruling UI3 a); null without one. */
  preview_built_at?: string | null
  preview_freshness?: Freshness | null
  /** That fit's foot pose (with `source.fsig`) — the preview applies it only to a GLB carrying those shoes. */
  foot_pose: FootPose | null
  /** Ruling A82: the Width / Length allowance box (`garment_footwear.allowance_view`). */
  allowance?: FootwearAllowanceView | null
}

/** The panel's `garment` as footwear info — the server sends `garment_footwear.info` for kind
 *  `footwear` (`garments.garment_info`); null for every other kind. */
export function footwearOf(info: { kind?: string; garment?: unknown } | null | undefined): FootwearInfo | null {
  if (info?.kind !== 'footwear' || !info.garment) return null
  return info.garment as FootwearInfo
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
  /** Ruling A46c: a value beyond the limit is a warning — the gate never refuses for it (the registration caps). */
  warn?: boolean
  /** Ruling A46c: the number exists for a generated image only, never for one made from the worn view. */
  generated_only?: boolean
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
  limits: Partial<Record<'hairdeck_fit', Record<string, GateLimit>>>
  /** The hair method in effect and where it comes from; the world default. */
  method: HairMethod
  method_source: 'character' | 'world'
  world_method: HairMethod
  /** The HairDeck section (null without a hair item). */
  hairdeck: HairDeckPanel | null
  /** The HAAR variants of a HAAR hairstyle (`garments.haar_panel`; null for another mode). */
  haar?: HaarPanel | null
  /** The kept results of the other methods, newest first ([] without one). */
  others: OtherMethodInfo[]
  /** The method is `body`: the hair is part of the body mesh — no steps, no run, no preview. */
  hair_in_body?: boolean
  /** With `hair_in_body`: the stored base's prompt freshness (`base_body.base_prompts_freshness`). */
  base_prompts?: Freshness | null
  /** Task 14 (GET …/hair?item_id=): this hairstyle is the plain body's. */
  plain?: boolean
  /** What its "Run all" runs now (`garments.run_estimate`; HAAR adds `cpu_fits`); null off the pipeline or without
   *  a hairstyle. */
  run?: { steps: string[]; hub_jobs: number | null; note: string; refit: boolean; cpu_fits?: number } | null
  /** The current base model's file (the preview of a `body` hairstyle that is the plain body's); null without. */
  body_url?: string | null
  /** When that base model was built (Ruling UI3 a); null without one. */
  body_built_at?: string | null
  /** The world's hair-card alpha cutoff (`base_body.hair_alpha_cutoff`, strand-hair spec § 6.1): the preview
   *  applies it to the MASK cards of the fit it shows. */
  alpha_cutoff?: number
  /** The strand record of the previewed fit (`GET …/garments/{item}/hair-strands`, strand-hair spec § 6.2.3): the
   *  Hairstyles preview runs the game's per-strand sim on it; null without a preview fit. */
  preview_strands_url?: string | null
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
  /** Outfit body mode mesh only: worn without an accepted fit — never painted (meshed) into the outfit body,
   *  so it is missing from the outfit model until its mesh is accepted (ruling 2026-11-10). */
  missing?: boolean
  /** Worn without its own mesh (no accepted fit, or refused): in the body shape until it is ready
   *  (ruling A11) — never painted then. */
  in_body?: boolean
  /** Why it is in the body / missing (server text, the outfit warning's words). The server's `painted`
   *  flag is not read: a worn own-mesh piece without its mesh sits in the body (ruling A11), never painted. */
  reason: string | null
  /** Names of the worn own-mesh pieces under this one that have a fit: it is fitted over them
   *  (absent when nothing is worn under it). */
  over?: string[]
  /** Names of the worn own-mesh pieces under this one without a fit (painted on): fitted without them. */
  without?: string[]
  /** Ruling A69 (`fitted` only): what of the fitted piece its checks refused and the user accepted — the fit, the
   *  mesh or an image (`step`, `view` "" unless an image); null/absent when nothing. */
  accepted_by_user?: { step: string; view: string; reason: string } | null
}

/** GET /characters/{n}/garments — the Wardrobe's own-mesh overview. */
export interface WardrobeGarments {
  pipeline: boolean
  /** Every own-mesh piece the character holds or wears. */
  items: Record<string, PieceStatus>
  /** The mode of EVERY outfit piece the character holds or wears (`garment_set.held_outfit_pieces`) — the
   *  row's mode select; the mode lives on the item, the same for every wearer. */
  modes: Record<string, MeshMode>
  /** Worn own-mesh pieces that are over each other: layered in slot order (inner first). */
  overlaps: Array<{ items: string[]; slots: string[] }>
  /** The boot hem control under the worn feet piece (boots spec § 8.3). */
  hem?: BootHemState
  /** Open / closed (Task 11b): the item flag "Can be worn open" of every held outfit piece. */
  closable?: Record<string, boolean>
  /** The worn pieces worn open (absent = closed). */
  piece_state?: Record<string, 'open'>
  /** Closable pieces whose prompt fragment already names a state (ruling A6: the row's hint). */
  names_state?: Record<string, boolean>
  /** Build automatically is on: a toggle starts the Build. */
  auto_build?: boolean
  /** The own mesh's material of every held outfit piece (Ruling A36, `piece_material.describe`): the stored
   *  choice and the preset "auto" takes effect as ("" = the generated roughness map). */
  materials?: Record<string, PieceMaterialInfo>
}

/** `outfit_piece.material` (Ruling A36): auto or a fixed preset. */
export type PieceMaterial = 'auto' | 'leather' | 'denim' | 'knit' | 'cotton' | 'rubber' | 'metal'

/** A piece's material choice and what "auto" resolves to ("" = the generated roughness map stays). */
export interface PieceMaterialInfo {
  choice: PieceMaterial
  guess: '' | Exclude<PieceMaterial, 'auto'>
}


/** Why a view needs another one (`garments.view_needs`): made from that image (`source`), a back drafted from its
 *  front (`draft`), a front matched to the back's length (`pair`). */
export type ViewNeed = 'source' | 'draft' | 'pair'

/** What one per-view button of the step grid spends and needs before the click (`garments.view_plan`, Ruling A33):
 *  `jobs` this view (first attempts), `missing` the views it needs that are not accepted (run order; the button is
 *  refused while any is — its "first" action renders them, `prerequisite_jobs`), `follow_up` what the same run
 *  renders again after it (a drafted step's back), `skipped` why the view is not made. */
export interface ViewRunPlan {
  step: string
  view: GarmentView
  jobs: number
  skipped: string | null
  missing: Array<{ step: string; view: GarmentView; why: ViewNeed; for: [string, GarmentView]; jobs: number }>
  prerequisite_jobs: number
  follow_up: Array<{ step: string; view: GarmentView; why: ViewNeed; jobs: number }>
  follow_up_jobs: number
}

/** `view_runs` of the panel: step → view → plan (null without per-view runs). */
export type ViewRunPlans = Partial<Record<string, Partial<Record<GarmentView, ViewRunPlan>>>>

/** "Use this" on one stored attempt before the click (`garments.use_plans`, Ruling A37): `passing` its gate
 *  passes (else the click accepts it as the user), `in_use` it is the view's image now, `block` why it cannot be
 *  used ("" = it can), `follow_up` the chain's estimate after the click (null when in use or blocked). */
export interface AttemptUsePlan {
  passing: boolean
  in_use: boolean
  block: string
  follow_up: { steps: string[]; hub_jobs: number | null; note: string } | null
}

/** `use_runs` of the panel: step → view → attempt number → plan. */
export type AttemptUsePlans = Partial<Record<string, Partial<Record<GarmentView, Record<string, AttemptUsePlan>>>>>

/** GET /characters/{n}/garments/{item} — the Wardrobe's own-mesh panel. */
export interface GarmentItemInfo {
  pipeline: boolean
  item_id: string
  name: string
  kind: string
  mesh_mode: MeshMode
  worn: boolean
  status: PieceStatus
  garment: GarmentInfo | null
  limits: Partial<Record<string, Record<string, GateLimit>>>
  /** What "Run all" runs now (`garments.run_estimate`; null off the pipeline): the steps from the first one
   *  that is not current, their first-attempt hub jobs (null = unknown, `note` says why); `refit` — the chain
   *  refits on the CPU first (0 hub jobs). */
  run?: { steps: string[]; hub_jobs: number | null; note: string; refit: boolean } | null
  /** Each per-view button's cost and prerequisites (`garments.view_plans`, Ruling A33); null without per-view runs. */
  view_runs?: ViewRunPlans | null
  /** "Use this" on each stored attempt (`garments.use_plans`, Ruling A37); null without per-view runs. */
  use_runs?: AttemptUsePlans | null
  /** Ruling A79: what Undo of the last "Use this" takes back (`garments.use_undo_state`); null without one. */
  use_undo?: UseUndoState | null
}

/** A step runs or the item waits in the character's garment queue
 *  (`running_step` is `queued` from the click until its first step). */
export const garmentRunning = (d: { garment?: GarmentInfo | null } | null | undefined) => !!d?.garment?.running_step
/** Ruling A46b: accepted images are being re-gated under the current gate version (the poll goes on). */
export const garmentChecking = (d: { garment?: GarmentInfo | null } | null | undefined) =>
  !!d?.garment?.regate_checking?.length

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
        if (!garmentRunning(d) && !garmentChecking(d)) return
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

/** One wearer of an item (GET /inventory/items/{id}/wearers): its pending changes, "Build automatically",
 *  and what its own Build would cost and run (`figure_build.cost`, a manual Build). */
export interface ItemWearer {
  name: string
  changes: number
  auto_build: boolean
  hub_jobs: number | null
  steps: string[]
}

/** GET /inventory/items/{id}/wearers — the characters on the figure pipeline wearing the item now. */
export interface ItemWearers {
  item_id: string
  mode: MeshMode | ''
  wearers: ItemWearer[]
  /** The sum of every wearer's Build cost; `hub_jobs` null as soon as one is unknown. */
  cost: { hub_jobs: number | null; note: string }
}

/** The Wardrobe's own-mesh overview of a character (GET
 *  /characters/{n}/garments), loaded by `reload` — the Wardrobe calls it with
 *  its belongings; null before, and when it failed (the mode selects then stay
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
  /** A CPU refit started beside the character's garment queue (Ruling A30) — not queued. */
  beside?: boolean
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
 *  step of a forced CHAIN run (`chain`) is redone after it (`redo`, until it
 *  runs) — the same view only, when the click named one; a step-only run
 *  (the dialog's buttons) redoes nothing after it. `order` = the method's steps. */
export function runMark(fb: RunFeedback | undefined, garment: GarmentRunState | null | undefined,
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
  return target.force && target.chain ? 'redo' : null
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
      // A refit beside the queue (Ruling A30) — or beside the piece's own mesh job (Ruling A58) — is shown by the
      // server's `queue_beside`; as a target it would read "Queued" behind a run it does not wait for.
      setTarget(answer?.beside ? null : { body, since: info, queue: queuePlace(answer) })
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
