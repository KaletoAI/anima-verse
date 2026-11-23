/**
 * PlacePreview — the edited clip on a real PROP's places, through the shared per-figure runtime (Ruling A110
 * phase 2, spec docs/superpowers/specs/2026-11-16-poses-tab-redesign-design.md § 2.2).
 *
 * * The prop and its places A…X come from the SERVER: `POST /play/scene-preview` with a one-room draft holding
 *   only that prop at the origin answers the same `models[]` spec and `markers[].slots` / `facing` / `y_world` /
 *   `root_offset` the game sends (phase 0, `scripts/smoke_prop_places_preview.py`). The prop mesh is placed by
 *   the contract's `placeModelSpec`, nothing geometric is derived here.
 * * Per place a character (D1: built figures + the 1.70 m mannequin; others greyed with the step that builds one)
 *   playing this clip — a solo clip in place on its slot, a pair/group's roles in ONE clip frame on the place
 *   centre turned by `pairYaw(facing, yaw_offset)`, the game's seating. At most 6 figures (D5).
 * * The Library's alignment DRAFT is read through `draftRef` in the frame loop (a slider drag reloads nothing) and
 *   applied over the saved calibration by `clipCalibration` / `calibratedRoot` (scene-render): the hips land
 *   where the baked clip will put them, so Apply does not move a figure.
 * * Frame: mixers (phase A) → root placement → `runtime.poseStep` → `runFigureFrame` (phase B). Strand hair for
 *   the 2 figures nearest the camera (D5, `strandCandidates`), the rest on spring chains; frame time shown.
 * * Readout per figure: Δyaw of the body forward (hips, projected) against the place facing and Δpos of the hips
 *   against the slot point, now and as the LOOP MEDIAN, with the D4 lamp. The pose's `yaw_offset` is shown
 *   read-only with a link to its entry (D2).
 *
 * * Icon toggles "Collision", "Channels" and "Partner see-through" (Ruling A212; off by default, remembered per browser
 *   user in localStorage) only change what is DRAWN — the sim always runs them, as in the game. The bend of the
 *   attached part always runs, exactly as in the game. Collision and Channels draw each figure's capsules as other
 *   figures engage them (pairs of two figures that overlap drawn red, the deepest pair in mm), and each channel with
 *   its opening (a ring at the mouth while a partner chain occupies it; who engages whom, w, opening radius in mm).
 *   The numbers come from `FigureRuntime.inspect` / `inspectFrame` (`placeFigures.ts`); client3d computes them on
 *   the same runtime (`scripts/smoke_place_preview_partners.mjs`).
 *
 * three.js is imported dynamically — the admin bundle must not carry it for tabs that never show 3D.
 */
import { Fragment, useEffect, useMemo, useRef, useState, type MutableRefObject } from 'react'
import type { Object3D, AnimationClip } from 'three'
import {
  CAPSULE_REGION_COLORS, FIGURE_HEIGHT_M, contactCapsules, OPENING_MARGIN_M, STRAND_RECORD_VERSION, alignmentDelta, alignmentLamp,
  applyFootPose, bindRelativeClip, calibratedRoot, capsuleWireframe, channelWireframe, clipCalibration,
  footPoseLiftM, footPoseMatches, installSkinnedNormalCorrection, median, pairYaw, pickModelVariant,
  placeCapsuleWireframe, placeChannelWireframe, placeModelSpec, plantFootPose, restCorrections, restPoseOf,
  strandCandidates, transplantedRestPose, type FootPose,
  type AlignmentDraft, type ChannelNow, type FrameInspection, type AlignmentLamp, type ClipHeightOffsetsCm, type CollisionPayload, type FigureRuntime,
  type HairStrandRecord, type SceneMarker, type SceneModelSpec, type SecondaryMotionPayload,
  contactReport, fixRoot, fixPivot, roleTurnFix, findContact, contactSampleOf,
  attachedPartIndex, partBoneNames, pairInterpenetration, clearLamp, PART_REGIONS, type ClearLamp,
  type ContactLamp, type ContactReport, type FitSample, type PairFix,
  isPointTarget, POINT_TARGET_OPS, MOUTH_CHANNEL_ID, type ContactTarget,
  bendSample, BEND_LIMITS_DEFAULT, type BendLimits, type BendResult,
  supportSample, supportHeight, postureReport, postureAngleCapDeg, supportMode, surfaceGap, surfaceExcess, SUPPORT_CAPSULES, type PostureReport, type ContactRelation,
  alignByPasses, pairPivotCm, keyReport, keyLamp, keyReasons, alignMovers, alignCap, relativeOf, joinDelta, type AlignLamp, type AlignBound, type AlignSample,
  type AlignPass, type KeyReport, type KeyReason, type RootAngle,
  keyFrames, keyWorstMm, clearAllowM, alignVerdict, deepHolds, alignBlocked, compareCandidates, alignBucket, ALIGN_CLEAR_SLACK_MM, visibleRootDepth,
  lampOf, solveLinear, ALIGN_ROOT_MARGIN_MM, ALIGN_GAIN_SLACK_MM, ALIGN_SUPPORT_SLACK_MM,
  type ClearCapsule, type ClearFrame, type ClearRow, type AlignCandidate, type AlignDiscard, type AlignBucket, type AlignNote,
  channelReadoutKey, foldReadoutMax, type ChannelReadout, type ChannelReadoutMax,
} from '@anima/scene-render'
import { useI18n } from '../../i18n/I18nProvider'
import { targetWordOf } from './contactWords'
import { apiGet, apiPatch, apiPost } from '../../lib/api'
import { loadCharacters } from '../../lib/refs'
import { loadTestFigure, standHipsRef } from '../characters/Model3DViewer'
import { rootAt, rootPath, ROLE_COLOR, type RootPath } from './ClipPreview'
import { ModelTurnHint } from '../../components/ModelTurnHint'
import { attachModelTurn, configureViewControls, poseMatrix } from '../../lib/modelTurn'
import { mountPlaceFigure, placeInteraction, placePhaseB } from './placeFigures'
import { GROUND_MAX, GROUND_PROP, defaultBody, fittingProps, groundFits, groundRoom, groupProps, planFill, preselectProp, type FillReason } from './placePicker'
import { effectivePoses, poseGroups, poseMotionUrl, posesParam, type PoseGroupChoice } from '../characters/baseBodyModel'

export const MANNEQUIN = '__mannequin__'
/** D5: figures in the preview, and how many of them run strand hair. */
export const MAX_FIGURES = 6
const STRAND_FIGURES = 2
const LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'

interface ModelAnswer {
  model?: {
    url?: string; collision?: CollisionPayload | null
    hair_strands?: { url?: string; sha256?: string } | null
    /** The fitted shoe's foot pose of the served file (`model3d.py`, `garment_assembly.served_foot_pose`). */
    foot_pose?: FootPose | null
  }
  motion?: SecondaryMotionPayload
}
interface PropRow {
  id: string; name?: string; marker_count?: number; marker_groups?: string[]; marker_capacities?: Record<string, number>; has_model?: boolean
  variant_tiers?: Array<{ variant: number }>
}
/** One clip file of the edited kind, as the listing carries it. */
export interface PlaceClip {
  role?: string; set?: string; url: string
  /** where the clip lives (the listing's `library`/`source` + `rel`) — what "Measure channel profile" PATCHes */
  library?: string; source?: string; rel?: string
  /** pair scene: the stored channel profile the server's readout estimate reads (null = not measured) */
  channel_profile?: ChannelProfile | null
  height_offsets_cm?: ClipHeightOffsetsCm
  orientation?: { shift_cm?: [number, number] | null; role_turn_deg?: Record<string, [number, number, number]> | null } | null
  /** Ruling A212: the clip's alignment range (cm). */
  align_range?: { cm: number } | null
  align_turn?: { deg: number } | null
}
/** Pair scene: per channel id (from the collision records) the largest share of the entering chain's length inside
 *  over one clip cycle and how many times the part reached the channel's bottom in that cycle — the clip sidecar's
 *  `channel_profile` (PATCH /assets/animation-clips/{library}/{rel}). */
export type ChannelProfile = Record<string, { share_max: number; reaches_per_cycle: number }>

/** The channel profile of one clip cycle: per readout key its maxima (`foldReadoutMax`) and reach edges, folded per
 *  channel (the largest share and reach count over the receivers and entering figures). Empty = nothing engaged. */
function channelProfileOf(maxima: ReadonlyMap<string, ChannelReadoutMax>,
  reaches: ReadonlyMap<string, number>): ChannelProfile {
  const out: ChannelProfile = {}
  for (const [key, m] of maxima) {
    const channel = key.split('|')[1]
    if (!channel) continue
    const share = Math.round(Math.min(1, Math.max(0, m.insertionOfLength)) * 10000) / 10000
    const count = Math.min(99, Math.max(0, Math.round(reaches.get(key) ?? 0)))
    const prev = out[channel]
    out[channel] = { share_max: Math.max(prev?.share_max ?? 0, share), reaches_per_cycle: Math.max(prev?.reaches_per_cycle ?? 0, count) }
  }
  return out
}

/** A pose that plays this clip (read-only here, D2). */
export interface PlacePose { key: string; yaw_offset?: number; group?: string }

/** One place letter: a slot of a marker of the prop. */
interface PlaceRow {
  letter: string; marker: SceneMarker; slot: number
  point: [number, number]; facing: number; rootY: number
}
/** A figure on a place: who, which half of the clip, which body (Ruling A110b: the plain base body or the outfit
 *  body the game shows) and, on the base body, the pose picked per extension group (pair scene: '' = at rest; a group
 *  without a pick shows its `preview_pose`). */
interface Assignment { character: string; role: string; body: 'outfit' | 'base'; poses: Record<string, string> }
/** "Align all" (owner 2026-11-23): the persons by ROLE that every clip it opens is measured with. */
export interface AlignCast {
  /** The person of each role's first place (in letter order). */
  byRole: Record<string, Assignment>
  /** The persons of the other places, in letter order: they go to the places of roles the cast has no person for. */
  extra: Assignment[]
}
/** The cast of a scene: each role's first place gives its person, the other places are the spares. */
function castOf(assign: Record<string, Assignment>): AlignCast {
  const byRole: Record<string, Assignment> = {}
  const extra: Assignment[] = []
  for (const [, a] of Object.entries(assign).sort(([x], [y]) => x.localeCompare(y))) {
    if (!a?.character || !a.role) continue
    if (byRole[a.role]) extra.push(a); else byRole[a.role] = a
  }
  return { byRole, extra }
}

/** A character's plain base body as GET …/figure?plain=1 reports it (`plain_body`) — the Base body tab's source. */
interface PlainInfo {
  url: string; collision: CollisionPayload | null; motion?: SecondaryMotionPayload
  groups: PoseGroupChoice[]
}
interface PlainAnswer {
  plain_body?: {
    model?: { url?: string; status?: string; collision?: CollisionPayload | null } | null
    extension?: { groups?: unknown[]; motion?: SecondaryMotionPayload } | null
  }
}
/** The base body of each character asked for, fetched once per mount: PlainInfo, null = none built, undefined = loading. */
function usePlainBodies(names: readonly string[]) {
  const [rows, setRows] = useState<Record<string, PlainInfo | null>>({})
  const asked = useRef(new Set<string>())
  const key = names.join('|')
  useEffect(() => {
    for (const name of names) {
      if (!name || name === MANNEQUIN || asked.current.has(name)) continue
      asked.current.add(name)
      apiGet<PlainAnswer>(`/characters/${encodeURIComponent(name)}/figure?plain=1`).then((d) => {
        const m = d?.plain_body?.model
        const ready = !!m?.url && m.status === 'ready'
        const ext = ready ? d?.plain_body?.extension : null
        setRows((cur) => ({ ...cur, [name]: ready ? { url: m!.url!, collision: m!.collision ?? null, motion: ext?.motion,
          groups: poseGroups(ext?.groups) } : null }))
      }).catch(() => setRows((cur) => ({ ...cur, [name]: null })))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])
  return rows
}

/** One figure's readout: now and the loop median. */
export interface FigureReadout {
  letter: string; character: string; role: string
  dyaw: number; dpos: number; medYaw: number; medPos: number; lamp: AlignmentLamp | null
}
/** What the Library needs to store a check (D3): the figures' readouts and whether they are all green. */
export interface PlaceReadout { prop: string; places: string; figures: FigureReadout[]; allGreen: boolean
  worstYaw: number; worstPos: number }

/** The partner overlays (phase 3): what is drawn, never what runs. The bend always runs (Ruling A212: as in the
 *  game). */
export interface PartnerShow { collision: boolean; channels: boolean
  /** Ruling A212: every mesh of the entering figure turns see-through; its attached part stays opaque. Preview only. */
  seeThrough: boolean }
const SHOW_KEY = 'anima.placePreview.show'
function loadShow(): PartnerShow {
  try {
    const v = JSON.parse(localStorage.getItem(SHOW_KEY) || '{}') as Partial<PartnerShow>
    return { collision: !!v.collision, channels: !!v.channels, seeThrough: !!v.seeThrough }
  } catch { return { collision: false, channels: false, seeThrough: false } }
}
/** Ruling A212: the see-through partner's opacity. */
const SEE_THROUGH_OPACITY = 0.25
/** Capsules of two figures that overlap; a channel occupied by a partner chain. */
const CONTACT_COLOR = 0xff2d2d
const OPENING_COLOR = 0x3fb950

/** Ruling A145: how far the attached part turned at its root — the largest over the frames, the root limit there, and
 *  the lamp (yellow when the limit cut the turn in some frame). */
export interface BendReadout { maxDeg: number; limitDeg: number; atLimit: number; frames: number; lamp: 'green' | 'yellow' }
/** The printed partner readout (names = place letters). */
interface PartnerInfo {
  closest: { a: string; b: string; capA: string; capB: string; mm: number } | null
  contacts: number
  channels: number
  engaged: { by: string; of: string; channel: string; w: number; openingMm: number | null
    /** The receiving figure's channel readout of this chain this frame (`channelReadout.ts`; null = not yet). */
    readout: ChannelReadout | null
    /** Its maxima over the last whole clip loop (`full`), or over the loop so far until one has passed. */
    max: ChannelReadoutMax | null; full: boolean }[]
  /** Ruling A212: each figure with a mouth: how far it is open now (null = no `mouth_open`) and whether its mouth
   *  channel carries the built opening (`open_height` / `teeth_gap`, mm; null = the mouth build has not run). */
  mouths: { letter: string; open: number | null; built: boolean; openHeightMm: number | null; teethGapMm: number | null }[]
}

/** The pose catalog's place types as the picker names them. */
const TYPE_LABEL: Record<string, string> = { stand: 'Stand', seat: 'Seat', ground: 'Ground', lie: 'Lie' }

/** Body and poses of one figure (Ruling A110b): outfit body (GET …/model3d, the game's figure) or the plain base body
 *  (GET …/figure?plain=1) — a variant that is not built is greyed with the step that builds it. On the base body, one
 *  pose picker per extension group that declares poses (pair scene): Rest + its pose ids, pre-selected with the
 *  group's `preview_pose`; motion from GET …/base-body/pose-motion. */
function BodyPick({ a, outfitBuilt, base, onChange }: {
  a: Assignment; outfitBuilt: boolean; base: PlainInfo | null | undefined
  onChange: (patch: Partial<Assignment>) => void
}) {
  const { t } = useI18n()
  const groups = a.body === 'base' && base ? base.groups : []
  const missing = a.body === 'base' ? (base === null ? t('no base model yet (Characters → Base body)') : '')
    : outfitBuilt ? '' : t('no outfit model yet (Characters → Figure)')
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 2, alignItems: 'center', minWidth: 0 }}>
      <select value={a.body} data-testid="place-body" style={{ flex: '1 1 0', minWidth: 0 }} title={t('Base body = the plain body; outfit body = the figure the game shows, with what the character wears.')}
        onChange={(e) => onChange({ body: e.target.value as Assignment['body'], poses: {} })}>
        <option value="outfit" disabled={!outfitBuilt}>{outfitBuilt ? t('Outfit body') : `${t('Outfit body')} — ${t('not built')}`}</option>
        <option value="base" disabled={base === null}>{base === null ? `${t('Base body')} — ${t('not built')}` : t('Base body')}</option>
      </select>
      {groups.map((g) => (
        <select key={g.id} value={g.id in a.poses ? a.poses[g.id] : g.preview_pose} data-testid="place-pose"
          title={`${g.id} — ${t('Preview only — nothing is saved, nothing runs.')}`} style={{ flex: '1 1 0', minWidth: 0 }}
          onChange={(e) => onChange({ poses: { ...a.poses, [g.id]: e.target.value } })}>
          <option value="">{t('Rest')}</option>
          {g.poses.map((p) => <option key={p} value={p}>{p}</option>)}
        </select>
      ))}
      {missing ? <div className="ga-hint" style={{ flexBasis: '100%', color: 'var(--danger, #f85149)' }}>{missing}</div> : null}
    </div>
  )
}

const LAMP_COLOR: Record<AlignmentLamp, string> = { green: '#3fb950', yellow: '#d29922', red: '#f85149' }

/** Characters and whether each has a built model (D1); probed once per mount. */
function useBuiltCharacters() {
  const [rows, setRows] = useState<{ name: string; built: boolean }[] | null>(null)
  useEffect(() => {
    let off = false
    void (async () => {
      const chars = await loadCharacters().catch(() => [])
      const out = await Promise.all(chars.map(async (c) => {
        const res = await fetch(`/characters/${encodeURIComponent(c.name)}/model3d`).catch(() => null)
        const data = res?.ok ? await res.json().catch(() => null) as ModelAnswer | null : null
        return { name: c.name, built: !!data?.model?.url }
      }))
      if (!off) setRows(out)
    })()
    return () => { off = true }
  }, [])
  return rows
}

const memoKey = (kind: string) => `anima.placePreview.${kind}`

/** Ruling A129.8: what the Places view keeps when the clip changes (tab state, for this page load): the camera, and
 *  per place INDEX the person, body and poses — restored on the new clip's places with that index. */
const placeMemory: { camera: { pos: [number, number, number]; target: [number, number, number] } | null
  byIndex: Record<number, { character: string; role: string; body: Assignment['body']; poses: Record<string, string> }> } = {
  camera: null, byIndex: {} }

/** Ruling A150: the persons, bodies and poses last picked per place index, remembered in this browser across page
 *  loads and server restarts (localStorage; the server has no per-user preference store). */
const PEOPLE_KEY = 'anima.placePreview.people'
function loadPeople(): typeof placeMemory.byIndex {
  try {
    const v = JSON.parse(localStorage.getItem(PEOPLE_KEY) || '{}') as { byIndex?: typeof placeMemory.byIndex }
    return v.byIndex && typeof v.byIndex === 'object' ? v.byIndex : {}
  } catch { return {} }
}
function savePeople(byIndex: typeof placeMemory.byIndex) {
  try { localStorage.setItem(PEOPLE_KEY, JSON.stringify({ byIndex })) } catch { /* private mode: not remembered */ }
}

/** Ruling A212 (procedure of 2026-11-20): the two key frames of the stroke (deepest, shallowest) before and after
 *  Auto-align — the rigid shaft against the target axis, and the bend still needed there. */
export interface KeyAlign { before: KeyReport | null; after: KeyReport | null }
/** Ruling A126/A139: one solved contact relation (the moving place `part`, the target it aims at). */
export interface RelationAlign { by: string; of: string; channel: string; target: ContactTarget; part: string
      /** The role that moved for it (ONE RELATION, ONE MOVER) and which of the two it is; `alternative` = the automatic
       *  alternative was taken (the receiving role, after the part's carrier was blocked), `tried` = the movers run. */
      moved: string; mover: AlignMover; alternative: boolean; tried: AlignMover[]
      /** The relation's key in "Align all" (part role > receiving role : target). */
      key: string
      /** THE VERDICT (pairAlign): applied, or discarded — 'overlap' with `collide` (the other figure it would go into),
       *  'support' (off its surface further than at the start), 'worse' (further off the axis than its start); the dials
       *  then stay as they were. */
      applied: boolean; discard: AlignDiscard | null; collide: ClearView | null
      /** THE VERDICT's other outcome: nothing gained, nothing written ("unchanged — already fits"), and the NOTES on the
       *  result (little depth, shallower, support corrected, no change needed). */
      unchanged: boolean; notes: AlignNote[]
      /** THE ROOT PULL-BACK: how far the measured correction pulled the moved role back along the channel axis (mm), and
       *  what stopped it while the rendered visible root was still inside — the range cap, the person (place letter)
       *  it would have gone into, or its support (it would have left its surface); null for a point target. */
      rootPull: { mm: number; stuck: { why: 'range' | 'overlap' | 'support'; with: string } | null
        /** The solved state before the pull-back: its rendered visible root's deepest point and its axis error (mm). */
        solvedVisMm: number; solvedAxisMm: number } | null
      /** THE CLEARANCE: the moved role against every other figure (mm over the loop: start, allowance, after). */
      clear: ClearView[]
      /** "Align all" stage 1: the bucket of this relation, and what it did with the clip's one root angle. */
      bucket: AlignBucket; root: 'solved' | 'kept' | 'none'
      /** THE RENDERED ROOT: the part's root joint and visible root over the loop as rendered (mm along the axis, + =
       *  inside), the frame where the visible root is deepest, before and after; null for a point target. */
      rendered: { before: RootFrameView; after: RootFrameView; isolated: RootFrameView
        frames: (RootFrameView & { isoRootMm: number; isoVisMm: number })[] } | null
      /** Why the contact lamp is not green (`keyReasons`; empty = green). */
      reasons: KeyReason[]
      /** How many sampled frames hold the tip inside (s_tip > 0) before and after, of `frames`. */
      tipInside: { before: number; after: number; frames: number }
      shiftCm: [number, number, number]
      /** The moved role's turn [tilt, roll, yaw] (degrees, base + solved). */
      turnDeg: [number, number, number]
      /** THE SUPPORT, ABSOLUTE (postureSupport): the moved role's mode and its lowest support capsule's gap over its
       *  surface over the loop (mm, [min, max]) before and after, the excess over the touch band (mm), and every
       *  other role's gap at the start (reported, never moved). */
      support: { mode: 'surface' | 'band' | 'none'; beforeMm: [number, number] | null; afterMm: [number, number] | null
        excessBeforeMm: number; excessAfterMm: number
        others: { letter: string; role: string; mm: [number, number] | null }[] }
      clearWorst: string; clearLamp: ClearLamp
      before: ContactReport; after: ContactReport; overlapBeforeMm: number; overlapAfterMm: number
      lampBefore: ContactLamp; lamp: ContactLamp
      /** Ruling A212: the deepest and the shallowest frame before and after. */
      keys: KeyAlign
      /** Ruling A145: what the bend does on the aligned samples (Auto-align itself is rigid; null = no chain). */
      bend: BendReadout | null
      /** Ruling A150: the moving figure's support before/after against its own posture (null = none read), and why the
       *  contact lamp is not green when the posture held it back. */
      postureBefore: PostureReport | null; posture: PostureReport | null; limitReason: 'posture' | null }
/** THE CLEARANCE of the moved role against one other figure (place letter; mm): the start's worst overlap over the loop,
 *  the allowance (at least `ALIGN_CLEAR_TOL_MM`, 5 mm), after the run, and the worst capsule pair. */
export interface RootFrameView { k: number; rootMm: number; visMm: number; tipMm: number }
export interface ClearView { with: string; startMm: number; allowMm: number; afterMm: number; worst: string }
/** Ruling A212: one moving role — its total offset around the base arrangement, and whether the cap stopped it. */
export interface MoverAlign { role: string; letter: string; mover: AlignMover; applied: boolean; shiftCm: [number, number, number]
  turnDeg: [number, number, number]
  /** What THIS run moved (cm, degrees): the result minus the dials when it was clicked. */
  adjustCm: [number, number, number]; adjustDeg: [number, number, number]
  rangeCm: number; turnRangeDeg: number
  /** red when an unknown hit its cap/slider range (`hits`), green otherwise. */
  lamp: AlignLamp; hits: AlignBound[]
  /** The root angle this run wrote (null = not solved for this role) and the one before (degrees). */
  rootAngle: RootAngle | null; rootBefore: RootAngle | null
  /** The measure → solve passes (increments) and whether they converged. */
  passes: AlignPass[]; converged: boolean }
export type AutoAlignResult =
  /** `code`: why nothing could be measured, for the clip's status (no place fits, no figure has the part, the pair
   *  never filled in). */
  | { ok: false; reason: string; code?: 'no_place' | 'no_part' | 'no_pair' }
  | { ok: true; relations: RelationAlign[]; roleShiftCm: Record<string, [number, number, number]>
      movers: MoverAlign[]
      target: ContactTarget; part: string
      by: string; of: string; channel: string; shiftCm: [number, number, number]
      /** The moved role's turn draft [tilt, roll, yaw] (degrees, base + solved, within the rotation range of the base). */
      turnDeg: [number, number, number]
      /** The turn drafts of every moved role (degrees), like `roleShiftCm`. */
      roleTurnDeg: Record<string, [number, number, number]>
      support: RelationAlign['support']
      clearWorst: string; clearLamp: ClearLamp
      before: ContactReport; after: ContactReport; overlapBeforeMm: number; overlapAfterMm: number
      lampBefore: ContactLamp; lamp: ContactLamp; bend: BendReadout | null; keys: KeyAlign
      postureBefore: PostureReport | null; posture: PostureReport | null; limitReason: 'posture' | null
      /** The clip's root angle Auto-align wrote (null = it did not solve it). */
      rootAngle: RootAngle | null
      /** The other contacts whose attached part the clip's one root angle turns too ("B → A (mouth)"), when this run
       *  solved it for one relation — the UI names them. */
      rootShared: string[]
      reasons: KeyReason[]
      /** Owner decision 2026-11-20 (scene-render `pairScale.ts`): the clip's contact pivot [side, forward] cm in the clip
       *  frame — the contact target's point at the deepest key frame after the run, the mean over the relations; real
       *  figure heights are scaled about it in the game (null = not measured). */
      pivotCm: [number, number] | null
      /** Whether any group of the run was applied (THE VERDICT); none = the dials stay as they were. */
      applied: boolean }

/** Ruling A212: the base clip's last frame — each role's hips relative to each other role's, in that role's clip frame
 *  (`relativeOf`; key `<moving>|<anchor>`). End clips are joined to it. */
export interface EndPose { kind: string; rel: Record<string, [number, number, number]> }
/** Ruling A212: what an Auto-align run may be told — another clip's relations (end clips align with the base's), the
 *  clip's alignment range (cm) and the end pose to join. */
/** ONE RELATION, ONE MOVER (2026-11-22): which of a relation's two roles a click moves — the part's carrier or the
 *  receiving role; 'auto' (the default) tries the part's carrier first and, when that run is blocked, the receiving
 *  role too, and takes the better (pairAlign `compareCandidates`). */
export type AlignMover = 'part' | 'receiver'
export type AlignMoverChoice = AlignMover | 'auto'
export interface AutoAlignOptions { relations?: ContactRelation[]; rangeCm?: number | null; turnDeg?: number | null; join?: EndPose | null
  /** One click = one contact relation: the relation to align ('detected' = the auto-detected contact of a clip without
   *  declared relations) and which of its roles moves (default 'part'). Absent = every relation, each moved by its
   *  part's carrier ("Align all", end clips). */
  only?: ContactRelation | 'detected' | null; mover?: AlignMoverChoice
  /** "Align all": every relation one after the other, each on the previous one's result (default mover 'auto'), and
   *  a mover per relation key (`RelationAlign.key`). */
  each?: boolean; moverOf?: Record<string, AlignMoverChoice>
  /** The arrangement the cap is measured from (draft values: role shifts in metres, role turns in degrees); absent =
   *  the dials now. */
  base?: { roleShiftM?: Record<string, [number, number, number]>; roleTurnDeg?: Record<string, [number, number, number]> } | null }
/** The Auto-align of the scene that runs now, tagged with what it shows (A129.6: "Align all" waits for its clip). */
export type AutoAlignRun = ((opts?: AutoAlignOptions) => AutoAlignResult) & { kind?: string; set?: string; figures?: number
  endPose?: () => EndPose | null
  /** The persons of this scene by role (what "Align all" carries to every clip it opens). */
  cast?: AlignCast
  /** No prop has a place this clip fits on: the run only says so (the scene never starts). */
  noPlace?: boolean }

export function PlacePreview({ kind, set = '', roles, clips, draftRef, draftSeq, bust = 0, poses, onOpenPose,
  onReadout, autoAlignRef, castRef, height = 360 }: {
  kind: string; set?: string
  /** 0/1 = solo, 2 = pair, 3+ = group */
  roles: number
  /** every file of this kind (all sets); the preview picks the previewed set's */
  clips: PlaceClip[]
  draftRef: MutableRefObject<AlignmentDraft>
  /** a new value whenever the draft changes (the draft object itself) — restarts the loop median */
  draftSeq: unknown
  bust?: number
  poses: PlacePose[]
  onOpenPose?: (key: string) => void
  onReadout?: (r: PlaceReadout | null) => void
  /** Set while a scene runs: plays the clip headless-fast and solves partner B's shift (Ruling A126). */
  autoAlignRef?: MutableRefObject<AutoAlignRun | null>
  /** Set while "Align all" runs: the default fill puts these persons on the places of their role (the place-index memory
   *  alone drifted to other persons whenever a clip used other places — two persons without a fitting part). */
  castRef?: MutableRefObject<AlignCast | null>
  height?: number
}) {
  const { t } = useI18n()
  const chars = useBuiltCharacters()
  const [props, setProps] = useState<PropRow[] | null>(null)
  const [propId, setPropId] = useState('')
  /** Solo figures on the bare floor (1..GROUND_MAX). */
  const [groundCount, setGroundCount] = useState(2)
  /** The last Fill all's outcome: count placed or why none. */
  const [fillNote, setFillNote] = useState<{ count: number; reason: FillReason } | null>(null)
  /** Ruling A150: remembered persons that no longer exist (their places got the default fill). */
  const [goneNote, setGoneNote] = useState<string[]>([])
  const [variant, setVariant] = useState(0)
  /** The draft scene and the clip/prop it was built for (`for`): until the next clip's scene has come, the previous
   *  clip's scene is still shown, and the default fill must not plan the new clip on it. */
  const [scene, setScene] = useState<{ models: SceneModelSpec[]; markers: SceneMarker[]; for: string } | null>(null)
  const [assign, setAssign] = useState<Record<string, Assignment>>({})
  const assignRef = useRef(assign)
  assignRef.current = assign
  const [status, setStatus] = useState('')
  /** Ruling A139: what the persons picked lack for their place's role (from the contact relations). */
  const [roleIssues, setRoleIssues] = useState<string[]>([])
  const [swapNote, setSwapNote] = useState('')
  const swapTried = useRef('')
  const targetWord = (x: ContactTarget) => targetWordOf(t, x)
  const [paused, setPaused] = useState(false)
  const [speed, setSpeed] = useState(0.2)
  /** Pair scene: "Measure channel profile" — armed (waits for the next loop start), measuring (one whole cycle), then
   *  the PATCH; `note` says how it went. The frame loop reads `measureRef`. */
  const [measure, setMeasure] = useState<{ phase: 'armed' | 'measuring' | 'saving' | 'done' | 'error'; note: string } | null>(null)
  const measureRef = useRef<'armed' | 'measuring' | null>(null)
  const onMeasuredRef = useRef<(profile: ChannelProfile) => void>(() => {})
  /** The clip the measurement was started on: a profile measured on another one is never stored. */
  const measureClip = useRef('')
  onMeasuredRef.current = (profile) => {
    const channels = Object.keys(profile).sort()
    if (measureClip.current !== `${kind}|${set.trim()}`) {
      setMeasure({ phase: 'error', note: t('The clip changed during the measurement — nothing stored.') })
      return
    }
    if (!channels.length) {
      setMeasure({ phase: 'error', note: t('No channel was engaged during the cycle — nothing stored.') })
      return
    }
    const want = set.trim()
    const clip = clips.find((c) => (c.set || '') === want) ?? clips[0]
    if (!clip?.rel) {
      setMeasure({ phase: 'error', note: t('The clip has no library path — reload the clip list.') })
      return
    }
    const path = `/assets/animation-clips/${encodeURIComponent(clip.library || clip.source || 'free')}/${
      clip.rel.split('/').map((s) => encodeURIComponent(s)).join('/')}`
    const list = channels.map((ch) => t('{channel}: {pct} % of the part inside, {n} reaches per cycle')
      .replace('{channel}', ch.split(':').pop() || ch).replace('{pct}', (profile[ch].share_max * 100).toFixed(0))
      .replace('{n}', String(profile[ch].reaches_per_cycle))).join(' · ')
    setMeasure({ phase: 'saving', note: list })
    apiPatch(path, { channel_profile: profile })
      .then(() => setMeasure({ phase: 'done', note: t('Channel profile stored — {list}').replace('{list}', list) }))
      .catch((e: unknown) => setMeasure({ phase: 'error', note: t('Channel profile not stored: {error}')
        .replace('{error}', e instanceof Error ? e.message : String(e)) }))
  }
  const [info, setInfo] = useState<{ ms: number; swingMm: number; strands: number; chains: number; figures: FigureReadout[]
    partners: PartnerInfo | null } | null>(null)
  const [show, setShow] = useState<PartnerShow>(loadShow)
  const showRef = useRef(show); showRef.current = show
  const toggleShow = (k: keyof PartnerShow) => setShow((cur) => {
    const next = { ...cur, [k]: !cur[k] }
    try { localStorage.setItem(SHOW_KEY, JSON.stringify(next)) } catch { /* private mode: not remembered */ }
    return next
  })
  const hostRef = useRef<HTMLDivElement>(null)
  const pausedRef = useRef(paused); pausedRef.current = paused
  const speedRef = useRef(speed); speedRef.current = speed
  // The clip time outlives a rebuild (Apply reloads the clip): a paused figure is compared at the SAME instant.
  const timeRef = useRef(0)
  const draftSeqRef = useRef(draftSeq); draftSeqRef.current = draftSeq
  const onReadoutRef = useRef(onReadout); onReadoutRef.current = onReadout
  const autoAlignOut = useRef(autoAlignRef); autoAlignOut.current = autoAlignRef
  // The SAVED calibration per role, read live in the frame loop: after Apply the listing (new shift_cm / heights)
  // arrives after the clip reload, and the figures must take it the moment it does — never a stale copy.
  const savedRef = useRef<Record<string, { shiftCm: [number, number] | null; heightOffsetsCm: ClipHeightOffsetsCm | null
    roleTurnDeg: Record<string, [number, number, number]> }>>({})
  {
    const want = set.trim()
    const out: typeof savedRef.current = {}
    for (const role of ['', 'a', 'b', 'c', 'd', 'e']) {
      const c = (want ? clips.find((x) => (x.role || '') === role && (x.set || '') === want) : undefined)
        || clips.find((x) => (x.role || '') === role && !x.set) || clips.find((x) => (x.role || '') === role)
      if (c) out[role] = { shiftCm: c.orientation?.shift_cm ?? null, heightOffsetsCm: c.height_offsets_cm ?? null,
        roleTurnDeg: c.orientation?.role_turn_deg ?? {} }
    }
    savedRef.current = out
  }
  const solo = roles < 2
  const roleList = useMemo(() => (solo ? [''] : ['a', 'b', 'c', 'd', 'e'].slice(0, roles)), [roles, solo])
  const pose = poses[0]
  const yawOffset = pose?.yaw_offset ?? 0
  const wantType = (pose?.group || '').trim()
  const isGround = propId === GROUND_PROP

  // ── the props with places ──
  useEffect(() => {
    let off = false
    apiGet<PropRow[]>('/assets/props').then((list) => {
      if (off) return
      const usable = (Array.isArray(list) ? list : []).filter((p) => (p.marker_count ?? 0) > 0 && p.has_model !== false)
      setProps(usable)
      let memo: { prop?: string; variant?: number } = {}
      try { memo = JSON.parse(localStorage.getItem(memoKey(kind)) || '{}') } catch { memo = {} }
      // Only the props that fit the clip (Ruling A110c); the remembered one while it still fits, else the first.
      const pick = preselectProp(groupProps(fittingProps(usable, wantType, roles), wantType), wantType, memo.prop || '',
        groundFits(wantType, roles))
      setPropId(pick)
      setVariant(pick === memo.prop ? memo.variant ?? 0 : 0)
    }).catch(() => { if (!off) { setProps([]); setPropId(groundFits(wantType, roles) ? GROUND_PROP : '') } })
    return () => { off = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kind, wantType, roles])
  const propGroups = useMemo(() => groupProps(fittingProps(props ?? [], wantType, roles), wantType),
    [props, wantType, roles])
  const groundOk = groundFits(wantType, roles)
  const nothingFits = props !== null && !groundOk && !propGroups.length
  // "Align all" (owner 2026-11-22): a clip no prop has a place for answers at once instead of being waited for.
  useEffect(() => {
    if (!nothingFits || !autoAlignOut.current) return
    const stub: AutoAlignRun = Object.assign((): AutoAlignResult => ({ ok: false, reason: t('No prop has a place this clip fits on.'), code: 'no_place' }),
      { kind, set, figures: 0, noPlace: true })
    autoAlignOut.current.current = stub
    return () => { if (autoAlignOut.current?.current === stub) autoAlignOut.current.current = null }
  }, [nothingFits, kind, set, t])

  // ── its places from the server (the draft scene preview) ──
  useEffect(() => {
    if (!propId) { setScene(null); return }
    try { localStorage.setItem(memoKey(kind), JSON.stringify({ prop: propId, variant })) } catch { /* private mode */ }
    let off = false
    const sceneFor = `${kind}|${propId}|${variant}`
    // The bare floor is one room marker (placePicker.groundRoom); a prop stands at the room centre.
    const room = propId === GROUND_PROP ? groundRoom(wantType, solo ? groundCount : roleList.length)
      : { id: 'place-preview', name: 'Preview',
        layout: { x: -3, y: -3, w: 6, d: 6, props: [{ id: 'p', prop_id: propId, at: [3, 3], yaw: 0, variant }] } }
    apiPost<{ models?: SceneModelSpec[]; markers?: SceneMarker[] }>('/play/scene-preview', { rooms: [room] })
      .then((payload) => {
        if (off) return
        setScene({ models: (payload.models || []).filter((m) => m.role === 'prop'), markers: payload.markers || [], for: sceneFor })
      })
      .catch((e) => { if (!off) { setScene(null); setStatus(String((e as Error).message || e)) } })
    return () => { off = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [propId, variant, kind, groundCount, wantType, roleList.length])

  const places = useMemo<PlaceRow[]>(() => {
    const out: PlaceRow[] = []
    for (const m of scene?.markers || []) {
      m.slots.forEach((s, i) => {
        if (out.length >= LETTERS.length) return
        out.push({ letter: LETTERS[out.length], marker: m, slot: i, point: s, facing: m.facing ?? 0,
          rootY: m.y_world - (m.root_offset ?? 0) })
      })
    }
    return out
  }, [scene])

  // Default fill and Fill all: built characters first, the mannequin between them (D1), only on places of the
  // clip's place type (placePicker.planFill). Fill all reports what it did — the count, or why nobody was placed.
  // The assignment a fill just set: until it is rendered, what is shown belongs to the previous clip or to the
  // empty first render and must not be remembered (it would wipe the memory the fill is about to read).
  const fillResult = useRef<object | null>(null)
  /** The places the last fill planned for this clip: only those are remembered (a place the clip does not take must not
   *  overwrite what the previous clip remembered there — it emptied every later clip's persons in "Align all"). */
  const planned = useRef<Set<string>>(new Set())
  const fill = (all: boolean) => {
    const names = chars ? [...chars.filter((c) => c.built).map((c) => c.name), MANNEQUIN] : null
    const plan = planFill(places.map((p) => ({ letter: p.letter, markerId: p.marker.id, group: p.marker.group })),
      { names, want: wantType, roles: solo ? [''] : roleList, all, max: MAX_FIGURES,
        body: (name) => defaultBody(plain[name], name === MANNEQUIN) })
    const next = { ...plan.assign }
    planned.current = new Set(Object.keys(plan.assign))
    if (!all) {
      // A129.8: the persons, bodies and poses picked on the last clip, per place index — only on the places the
      // default fill gives this clip; a remembered figure never adds a place the clip does not take (a place
      // remembered from "Fill all" stays empty). A place remembered EMPTY stays empty.
      const rl = solo ? [''] : roleList
      // A150: this page load's memory first, else what this browser remembered.
      const memo = Object.keys(placeMemory.byIndex).length ? placeMemory.byIndex : loadPeople()
      const known = new Set([...(chars ?? []).map((c) => c.name), MANNEQUIN])
      const gone: string[] = []
      places.forEach((p, i) => {
        const m = memo[i]
        // An entry without `poses` (remembered before the pose pickers) is not read.
        if (!m || !m.poses || typeof m.poses !== 'object' || !(p.letter in plan.assign)) return
        if (!m.character) { delete next[p.letter]; return }
        if (!known.has(m.character)) { if (!gone.includes(m.character)) gone.push(m.character); return }
        const role = next[p.letter]?.role ?? (rl.includes(m.role) ? m.role : rl[i % rl.length])
        next[p.letter] = { character: m.character, role, body: m.body, poses: m.poses }
      })
      setGoneNote(gone)
      const cast = castRef?.current
      if (cast) {
        // "Align all": each role's FIRST place gets the cast's person of that role; every other place keeps its own
        // person unless that person is already placed, then the default fill's, then any built person not placed yet
        // — never one person twice (a doubled person never finished mounting).
        const letters = Object.keys(next).sort()
        const castNames = new Set([...Object.values(cast.byRole), ...cast.extra].map((c) => c.character).filter((n) => known.has(n)))
        const used = new Set<string>()
        const fromCast = new Set<string>()
        for (const l of letters) {
          const r = next[l]?.role
          const c = r ? cast.byRole[r] : undefined
          if (!c || !known.has(c.character) || used.has(c.character)) continue
          next[l] = { ...c, role: r }; used.add(c.character); fromCast.add(l)
        }
        const spare = [...(names ?? [])]
        const extra = cast.extra.filter((c) => known.has(c.character))
        for (const l of letters) {
          if (fromCast.has(l)) continue
          const r = next[l]?.role
          // a role the cast has no person for takes the cast's next spare person
          const x = r && !cast.byRole[r] ? extra.find((c) => !used.has(c.character)) : undefined
          if (x) { next[l] = { ...x, role: r }; used.add(x.character); continue }
          const a = next[l]
          const free = (n: string | undefined) => !!n && !used.has(n) && !castNames.has(n)
          const pick = free(a?.character) ? a!.character : free(plan.assign[l]?.character) ? plan.assign[l]!.character
            : spare.find((n) => free(n))
          if (!pick) { delete next[l]; continue }
          next[l] = { ...(a ?? plan.assign[l]!), character: pick,
            ...(pick !== a?.character ? { body: defaultBody(plain[pick], pick === MANNEQUIN), poses: {} } : {}) }
          used.add(pick)
        }
      }
    } else setGoneNote([])
    fillResult.current = next
    setAssign(next)
    if (all) setFillNote({ count: plan.count, reason: plan.reason })
  }
  const filled = useRef('')
  useEffect(() => {
    const key = `${kind}|${propId}|${variant}|${places.length}|${chars ? 1 : 0}`
    // "Align all" (owner 2026-11-23, the clips never filled in run 3): the default fill waits for THIS clip's scene. Planned
    // on the previous clip's places (still shown while the new scene loads), it emptied every place of a clip whose place
    // type differs, and the same key then kept the real places from being filled at all.
    if (scene?.for !== `${kind}|${propId}|${variant}`) return
    if (!places.length || !chars || filled.current === key) return
    filled.current = key
    fill(false)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [places, chars, kind, propId, variant])

  // A129.8: remember what is shown, per place index.
  useEffect(() => {
    if (!places.length || !filled.current) return
    if (fillResult.current) {
      if (assign !== fillResult.current) return
      fillResult.current = null
    }
    // An emptied place is remembered as empty — so "— empty" survives the next clip and the next page load.
    places.forEach((p, i) => {
      const a = assign[p.letter]
      if (!a?.character && !planned.current.has(p.letter)) return
      placeMemory.byIndex[i] = a?.character
        ? { character: a.character, role: a.role, body: a.body, poses: a.poses }
        : { character: '', role: '', body: 'outfit', poses: {} }
    })
    savePeople(placeMemory.byIndex)
  }, [assign, places])
  const assigned = places.filter((p) => assign[p.letter]?.character)
  const plain = usePlainBodies(places.map((p) => assign[p.letter]?.character || ''))
  // A figure put on the base body while its plain body was still loading: once GET …/figure?plain=1 says there is
  // none, it shows the outfit body (a new figure's body is the base body only when that is built).
  useEffect(() => {
    const flip = Object.keys(assign).filter((l) => assign[l].body === 'base' && assign[l].character !== MANNEQUIN
      && plain[assign[l].character] === null)
    if (!flip.length) return
    setAssign((cur) => {
      const next = { ...cur }
      for (const l of flip) if (next[l]) next[l] = { ...next[l], body: 'outfit', poses: {} }
      return next
    })
  }, [assign, plain])
  // The group poses in effect on a base figure (its picks, else each group's preview_pose), as the request parameter.
  const posesOf = (a: Assignment) => a.body === 'base' ? posesParam(effectivePoses(plain[a.character]?.groups ?? [], a.poses)) : ''
  // A base figure's model, motion and poses are part of the scene's key: a pose pick or a base body that arrives
  // rebuilds the scene with the right model.
  const [poseMotions, setPoseMotions] = useState<Record<string, SecondaryMotionPayload | null>>({})
  useEffect(() => {
    for (const p of assigned) {
      const a = assign[p.letter]
      const base = plain[a.character]
      if (a.body !== 'base' || !base) continue
      const poses = effectivePoses(base.groups, a.poses)
      const k = `${a.character}|${posesParam(poses)}`
      if (!posesParam(poses) || k in poseMotions) continue
      setPoseMotions((cur) => ({ ...cur, [k]: null }))
      apiGet<{ motion: SecondaryMotionPayload }>(poseMotionUrl(a.character, poses))
        .then((d) => setPoseMotions((cur) => ({ ...cur, [k]: d.motion })))
        .catch(() => { /* the figure keeps the rest motion */ })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [assign, plain])
  const assignKey = JSON.stringify(assigned.map((p) => {
    const a = assign[p.letter]
    const k = `${a.character}|${posesOf(a)}`
    return [p.letter, a, a.body === 'base' ? [plain[a.character]?.url ?? '', posesOf(a), !!poseMotions[k]] : 0]
  }))
  const propName = isGround ? t('Ground (no prop)') : props?.find((p) => p.id === propId)?.name || propId

  // ── the scene ──
  useEffect(() => {
    const host = hostRef.current
    if (!host || !scene || !kind) return
    let disposed = false
    let raf = 0
    const disposers: Array<() => void> = []
    setStatus(t('Loading…'))
    setInfo(null)
    void (async () => {
      try {
        const THREE = await import('three')
        installSkinnedNormalCorrection(THREE)
        const { OrbitControls } = await import('three/examples/jsm/controls/OrbitControls.js')
        const { FBXLoader } = await import('three/examples/jsm/loaders/FBXLoader.js')
        const { clone: skclone } = await import('three/examples/jsm/utils/SkeletonUtils.js')
        const { createGLTFLoader } = await import('../../lib/gltfLoader')
        const gltfLoader = createGLTFLoader()
        const want = set.trim()
        const fileOf = (role: string) =>
          (want ? clips.find((c) => (c.role || '') === role && (c.set || '') === want) : undefined)
          || clips.find((c) => (c.role || '') === role && !c.set)
          || clips.find((c) => (c.role || '') === role)
        const [rig, standRefCm] = await Promise.all([
          new FBXLoader().loadAsync('/assets/animation-rig').catch(() => null), standHipsRef()])
        const standRefM = (standRefCm || 0) / 100
        // Clips per role, loaded once.
        const clipFiles = new Map<string, { file: PlaceClip; raw: AnimationClip; path: RootPath }>()
        for (const role of new Set(assigned.map((p) => assign[p.letter].role))) {
          const file = fileOf(role)
          if (!file) continue
          const obj = await new FBXLoader().loadAsync(bust ? `${file.url}${file.url.includes('?') ? '&' : '?'}v=${bust}` : file.url)
          const raw = obj.animations?.[0]
          if (raw) clipFiles.set(role, { file, raw, path: rootPath(raw, standRefM) })
        }
        // Models per character, loaded once; the mannequin is shared and never disposed here.
        // Keyed by character + body + poses: the outfit body is GET …/model3d (the game's figure), the base body
        // `plain_body.model` of GET …/figure?plain=1 with its rest motion or the picked poses' (pose-motion).
        const modelKey = (a: Assignment) => a.character === MANNEQUIN ? MANNEQUIN
          : a.body === 'base' ? `${a.character}|base|${posesOf(a)}` : a.character
        const models = new Map<string, { template: Object3D; answer: ModelAnswer | null; record: HairStrandRecord | null; owned: boolean }>()
        for (const a of assigned.map((p) => assign[p.letter])) {
          const name = a.character
          const mk = modelKey(a)
          if (models.has(mk)) continue
          if (name === MANNEQUIN) {
            const fig = await loadTestFigure()
            if (fig) models.set(mk, { template: fig, answer: null, record: null, owned: false })
            continue
          }
          if (a.body === 'base') {
            const base = plain[name]
            if (!base) continue
            const poses = posesOf(a)
            const motion = (poses ? poseMotions[`${name}|${poses}`] : null) ?? base.motion
            const gltf = await gltfLoader.loadAsync(base.url).catch(() => null)
            if (gltf) models.set(mk, { template: gltf.scene, answer: { model: { url: base.url, collision: base.collision }, motion },
              record: null, owned: true })
            continue
          }
          const answer = await apiGet<ModelAnswer>(`/characters/${encodeURIComponent(name)}/model3d`).catch(() => null)
          if (!answer?.model?.url) continue
          const gltf = await gltfLoader.loadAsync(answer.model.url)
          let record: HairStrandRecord | null = null
          if (answer.model.hair_strands?.url) {
            const res = await fetch(answer.model.hair_strands.url).catch(() => null)
            const json = res?.ok ? await res.json().catch(() => null) as HairStrandRecord | null : null
            record = json && json.version === STRAND_RECORD_VERSION ? json : null
          }
          models.set(mk, { template: gltf.scene, answer, record, owned: true })
        }
        // The prop mesh, placed by the contract's routine.
        const propObjects: Object3D[] = []
        for (const spec of scene.models) {
          const url = pickModelVariant(spec, 'full')
          if (!url) continue
          const gltf = await gltfLoader.loadAsync(url).catch(() => null)
          if (gltf) propObjects.push(placeModelSpec(THREE, gltf.scene, spec, { clone: false }))
        }
        if (disposed) return
        const disposeTree = (root: Object3D, textures = true) => root.traverse((o) => {
          const mesh = o as unknown as { geometry?: { dispose(): void }; material?: unknown; skeleton?: { dispose(): void } }
          mesh.geometry?.dispose()
          const mats = Array.isArray(mesh.material) ? mesh.material : mesh.material ? [mesh.material] : []
          for (const mat of mats as Array<{ dispose(): void } & Record<string, unknown>>) {
            if (textures) for (const v of Object.values(mat)) {
              if (v && typeof v === 'object' && (v as { isTexture?: boolean }).isTexture) (v as { dispose(): void }).dispose()
            }
            mat.dispose()
          }
        })
        // This mount loaded the character templates and the prop: they are its own. Clones share their buffers.
        disposers.push(() => {
          for (const m of models.values()) if (m.owned) disposeTree(m.template)
          for (const p of propObjects) disposeTree(p)
        })

        // ── stage ──
        const width = host.clientWidth || 640
        const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true })
        renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2))
        renderer.setSize(width, height)
        host.appendChild(renderer.domElement)
        disposers.push(() => { renderer.dispose(); renderer.domElement.remove() })
        const sceneObj = new THREE.Scene()
        sceneObj.add(new THREE.HemisphereLight(0xffffff, 0x556677, 1.1))
        const key = new THREE.DirectionalLight(0xffffff, 1.2)
        key.position.set(2, 4, 3)
        sceneObj.add(key)
        const stage = new THREE.Group()
        stage.matrixAutoUpdate = false
        sceneObj.add(stage)
        const own: Array<{ dispose(): void }> = []
        disposers.push(() => own.forEach((d) => d.dispose()))
        for (const p of propObjects) stage.add(p)
        // 0.5 m grid, 4 m wide, and the 1.70 m reference post beside the prop (never scaled).
        const grid = new THREE.GridHelper(4, 8, 0x7a8594, 0x3a4350)
        own.push(grid.geometry, grid.material as { dispose(): void })
        stage.add(grid)
        const propBox = new THREE.Box3()
        for (const p of propObjects) propBox.expandByObject(p)
        const postX = propBox.isEmpty() ? -1 : propBox.min.x - 0.5
        const postGeom = new THREE.CylinderGeometry(0.012, 0.012, FIGURE_HEIGHT_M, 6)
        const postMat = new THREE.MeshBasicMaterial({ color: 0xffc857 })
        own.push(postGeom, postMat)
        const post = new THREE.Mesh(postGeom, postMat)
        post.position.set(postX, FIGURE_HEIGHT_M / 2, 0)
        stage.add(post)
        // Place markers: a box with its letter on the surface, the place facing as a dashed arrow.
        const markGeom = new THREE.BoxGeometry(0.1, 0.02, 0.1)
        own.push(markGeom)
        const letterSprite = (text: string, color: string) => {
          const canvas = document.createElement('canvas')
          canvas.width = 64; canvas.height = 64
          const ctx = canvas.getContext('2d')
          if (ctx) {
            ctx.fillStyle = color; ctx.font = 'bold 44px sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'
            ctx.fillText(text, 32, 34)
          }
          const tex = new THREE.CanvasTexture(canvas)
          const mat = new THREE.SpriteMaterial({ map: tex, depthTest: false })
          own.push(tex, mat)
          const s = new THREE.Sprite(mat)
          s.scale.set(0.18, 0.18, 1)
          return s
        }
        for (const p of places) {
          const used = !!assign[p.letter]?.character
          const mat = new THREE.MeshBasicMaterial({ color: used ? 0xffc857 : 0x8b949e })
          own.push(mat)
          const box = new THREE.Mesh(markGeom, mat)
          box.position.set(p.point[0], p.marker.y_world + 0.01, p.point[1])
          stage.add(box)
          const label = letterSprite(p.letter, used ? '#ffc857' : '#8b949e')
          label.position.set(p.point[0], p.marker.y_world + 0.12, p.point[1])
          stage.add(label)
          const rad = p.facing * Math.PI / 180
          const dir = new THREE.Vector3(Math.sin(rad), 0, Math.cos(rad))
          const from = new THREE.Vector3(p.point[0], p.marker.y_world + 0.03, p.point[1])
          const lineGeom = new THREE.BufferGeometry().setFromPoints([from, from.clone().addScaledVector(dir, 0.45)])
          const lineMat = new THREE.LineDashedMaterial({ color: 0xffc857, dashSize: 0.04, gapSize: 0.03 })
          own.push(lineGeom, lineMat)
          const line = new THREE.Line(lineGeom, lineMat)
          line.computeLineDistances()
          stage.add(line)
        }

        // ── figures ──
        const hipsOf = (root: Object3D): Object3D | null => {
          let found: Object3D | null = null
          root.traverse((o) => { if (!found && /hips/i.test(o.name)) found = o })
          return found
        }
        interface Fig {
          letter: string; character: string; role: string; place: PlaceRow; root: Object3D; inst: Object3D
          mixer: InstanceType<typeof THREE.AnimationMixer>; path: RootPath; duration: number
          hips: Object3D | null; hipsBind: { x: number; y: number; z: number }
          bindInv: InstanceType<typeof THREE.Quaternion>; runtime: FigureRuntime; hasRecord: boolean
          saved: { shiftCm: [number, number] | null; heightOffsetsCm: ClipHeightOffsetsCm | null
            roleTurnDeg: Record<string, [number, number, number]> }
          anchor: { x: number; y: number; z: number }; placeYaw: number
          arrow: InstanceType<typeof THREE.ArrowHelper>; yawS: number[]; posS: number[]
          medYaw: number; medPos: number; dyaw: number; dpos: number; chains: number
          head: Object3D | null; tips: Object3D[]; tipRest: Map<Object3D, InstanceType<typeof THREE.Vector3>>
          /** A129.9: the part-only twins of the body's skinned meshes (same attributes and skeleton). */
          partMeshes: Object3D[]
          collision: CollisionPayload | null
        }
        const figs: Fig[] = []
        const centreOf = (m: SceneMarker) => {
          const n = m.slots.length || 1
          return { x: m.slots.reduce((a, s) => a + s[0], 0) / n, z: m.slots.reduce((a, s) => a + s[1], 0) / n }
        }
        for (const p of assigned) {
          const a = assign[p.letter]
          const model = models.get(modelKey(a))
          const clip = clipFiles.get(a.role)
          if (!model || !clip) continue
          const answer = model.answer
          const { root, inst, runtime } = mountPlaceFigure(THREE, (o) => skclone(o) as Object3D, model.template,
            { collision: answer?.model?.collision ?? null, motion: () => answer?.motion })
          stage.add(root)
          root.updateMatrixWorld(true)
          const hips = hipsOf(inst)
          const hb = hips ? hips.getWorldPosition(new THREE.Vector3()) : new THREE.Vector3(0, FIGURE_HEIGHT_M * 0.55, 0)
          const bindInv = hips ? hips.getWorldQuaternion(new THREE.Quaternion()).invert() : new THREE.Quaternion()
          let hasRecord = false
          if (model.record) {
            const record = model.record
            runtime.loadStrandRecord = () => record
            hasRecord = runtime.prepareStrandHair()
          }
          const tracks = clip.raw.tracks.filter((tr) => !(/hips/i.test(tr.name) && tr.name.endsWith('.position')))
          const inplace = new THREE.AnimationClip(clip.raw.name, clip.raw.duration, tracks)
          // THE SHOD CLIP, the 3D client's `prepareShoes` step: only a body that carries exactly the fitted shoes
          // (`footPoseMatches`) gets the extension right after the bind-relative step (relative to the rest the
          // transplant plays, `transplantedRestPose`) and the per-frame foot plant on an unposed probe clone; a
          // bare figure's clip passes through untouched.
          const fp = answer?.model?.foot_pose
          const shod = fp && footPoseMatches(model.template, fp) ? fp : null
          const donor = rig ? restPoseOf(THREE, rig) : null
          const corrections = donor ? restCorrections(THREE, donor, inst, undefined, shod) : null
          const bareClip = corrections ? bindRelativeClip(THREE, inplace, corrections) : inplace
          let bound = bareClip
          if (shod) {
            const rest = restPoseOf(THREE, inst)
            const clipRest = donor && corrections?.size ? transplantedRestPose(THREE, donor, rest, corrections) : null
            bound = applyFootPose(THREE, bareClip, shod, rest, clipRest)
            if (bound !== bareClip) bound = plantFootPose(THREE, bound, bareClip, skclone(model.template) as Object3D, shod,
              { rootY: footPoseLiftM(shod, 'ground'), unitsPerCm: 0.01 })
          }
          const mixer = new THREE.AnimationMixer(inst)
          mixer.clipAction(bound).play()
          const m = p.marker
          const centre = centreOf(m)
          const anchor = solo ? { x: p.point[0], y: p.rootY, z: p.point[1] } : { x: centre.x, y: p.rootY, z: centre.z }
          const placeYaw = solo ? p.facing * Math.PI / 180 : pairYaw(p.facing, yawOffset)
          const arrow = new THREE.ArrowHelper(new THREE.Vector3(0, 0, 1), new THREE.Vector3(), 0.5,
            new THREE.Color(ROLE_COLOR[a.role] || '#58a6ff').getHex(), 0.1, 0.06)
          stage.add(arrow)
          own.push(arrow)
          const label = letterSprite(p.letter, ROLE_COLOR[a.role] || '#58a6ff')
          label.position.y = FIGURE_HEIGHT_M + 0.15
          root.add(label)
          const o = clip.file.orientation
          let head: Object3D | null = null
          const tips: Object3D[] = []
          inst.traverse((n) => {
            if (/^mixamorig:?head$/i.test(n.name)) head = n
            if (/^HairGen_.*_end$/.test(n.name)) tips.push(n)
          })
          // A129.9: part-only twins of the skinned meshes — the triangles weighted onto the bones of the motion groups
          // that carry an op (scene-render attachedPartIndex); attributes and skeleton are shared, only the index is new.
          // Ruling A212: a twin keeps the mesh's own (opaque) material and draws after the see-through body.
          const partMeshes: Object3D[] = []
          const partNames = partBoneNames((answer?.motion?.groups ?? {}) as Record<string, { bones: string[]; op?: string | null }>)
          const bare = (n: string) => n.replace(/^mixamorig:?/i, '').toLowerCase()
          const partBare = new Set([...partNames].map(bare))
          if (partBare.size) {
            const found: InstanceType<typeof THREE.SkinnedMesh>[] = []
            inst.traverse((n) => { if ((n as InstanceType<typeof THREE.SkinnedMesh>).isSkinnedMesh) found.push(n as InstanceType<typeof THREE.SkinnedMesh>) })
            for (const m of found) {
              const g = m.geometry, si = g.getAttribute('skinIndex'), sw = g.getAttribute('skinWeight')
              if (!si || !sw || !m.parent) continue
              const bones = new Set<number>()
              m.skeleton.bones.forEach((b, i) => { if (partBare.has(bare(b.name))) bones.add(i) })
              if (!bones.size) continue
              const index = g.index ? g.index.array : Array.from({ length: g.getAttribute('position').count }, (_, i) => i)
              const tri = attachedPartIndex(index, si.array, sw.array, bones)
              if (!tri.length) continue
              const pg = new THREE.BufferGeometry()
              for (const [k, v] of Object.entries(g.attributes)) pg.setAttribute(k, v)
              pg.setIndex(tri)
              // Ruling A212: its own material (owned by this mount), opaque but in the transparent pass so it draws
              // after the see-through body.
              const twinMat = (Array.isArray(m.material) ? m.material : [m.material]).map((x) => {
                const c = x.clone(); c.transparent = true; c.opacity = 1; c.depthWrite = true
                // keep the source's shader hooks (garment collision, skinned normals)
                c.onBeforeCompile = x.onBeforeCompile; c.customProgramCacheKey = x.customProgramCacheKey
                own.push(c); return c
              })
              const twin = new THREE.SkinnedMesh(pg, Array.isArray(m.material) ? twinMat : twinMat[0])
              twin.bind(m.skeleton, m.bindMatrix)
              twin.position.copy(m.position); twin.quaternion.copy(m.quaternion); twin.scale.copy(m.scale)
              twin.frustumCulled = false
              twin.visible = false
              twin.renderOrder = 2
              m.parent.add(twin)
              partMeshes.push(twin)
              // not disposed: pg shares the template's attribute buffers, disposing it would drop them on the GPU
            }
          }
          figs.push({ letter: p.letter, partMeshes, collision: answer?.model?.collision ?? null, character: a.character, role: a.role, place: p, root, inst, mixer, path: clip.path,
            duration: clip.raw.duration, hips, hipsBind: { x: hb.x, y: hb.y, z: hb.z }, bindInv, runtime, hasRecord,
            saved: { shiftCm: o?.shift_cm ?? null, heightOffsetsCm: clip.file.height_offsets_cm ?? null,
              roleTurnDeg: o?.role_turn_deg ?? {} },
            anchor, placeYaw, arrow, yawS: [], posS: [], medYaw: NaN, medPos: NaN, dyaw: 0, dpos: 0,
            chains: Object.keys(answer?.motion?.groups ?? {}).length, head, tips, tipRest: new Map() })
          disposers.push(() => { mixer.stopAllAction(); mixer.uncacheRoot(inst); runtime.dispose() })
        }
        if (!figs.length) {
          setStatus(!assigned.length || clipFiles.size ? t('Pick a character for a place.') : t('No clip file for this kind in shared/models/clips.'))
        } else setStatus('')

        const camera = new THREE.PerspectiveCamera(35, width / height, 0.05, 100)
        camera.position.set(0.4, 1.7, 3.6)
        const controls = new OrbitControls(camera, renderer.domElement)
        controls.target.set(0, 0.6, 0)
        // A129.8: the camera of the last clip (or of the last rebuild) carries over.
        if (placeMemory.camera) {
          camera.position.set(...placeMemory.camera.pos)
          controls.target.set(...placeMemory.camera.target)
        }
        configureViewControls(THREE, controls)
        controls.update()
        disposers.push(() => controls.dispose())
        const turn = attachModelTurn(host)
        disposers.push(() => turn.dispose())
        const PIVOT: [number, number, number] = [0, 0.6, 0]

        const duration = figs.length ? Math.min(...figs.map((f) => f.duration)) : 1
        const frameState = { openingTurn: 0 }
        const entries = figs.map((f) => ({
          name: `${f.letter}:${f.character}`,
          interaction: solo ? null : placeInteraction(kind, f.place.marker.id,
            figs.filter((g) => g.place.marker.id === f.place.marker.id).map((g) => `${g.letter}:${g.character}`)),
          figure: f.runtime,
        }))
        // ── partner overlays (phase 3): world space, on the scene root — the runtime reads the stage-turned figures ──
        const overlay = new THREE.Group()
        sceneObj.add(overlay)
        const capLines = new Map<string, ReturnType<typeof capsuleWireframe>>()
        const chLines = new Map<string, ReturnType<typeof channelWireframe>>()
        const rings = new Map<string, InstanceType<typeof THREE.LineLoop>>()
        const ringGeom = new THREE.BufferGeometry().setFromPoints(Array.from({ length: 33 },
          (_, k) => new THREE.Vector3(Math.cos(k * Math.PI / 16), 0, Math.sin(k * Math.PI / 16))))
        const ringMat = new THREE.LineBasicMaterial({ color: OPENING_COLOR, depthTest: false })
        own.push(ringGeom, ringMat)
        disposers.push(() => {
          for (const l of [...capLines.values(), ...chLines.values()]) {
            l.geometry.dispose(); (l.material as { dispose(): void }).dispose()
          }
          overlay.removeFromParent()
        })
        const nameToLetter = new Map(figs.map((f) => [`${f.letter}:${f.character}`, f.letter]))
        const letterOf = (name: string) => nameToLetter.get(name) ?? name
        let partnerInfo: PartnerInfo | null = null
        // The channel readouts' maxima per clip loop (key = channelReadoutKey): this loop's so far, and the last whole one.
        let loopMax = new Map<string, ChannelReadoutMax>()
        let lastLoopMax: Map<string, ChannelReadoutMax> | null = null
        // The reach edges per key and loop (an edge = insertionOfDepth reaching 1 from below, as client3d's readout
        // reports count them; the edge state outlives the loop boundary, so a reach across it counts once).
        let loopReaches = new Map<string, number>()
        let lastLoopReaches = new Map<string, number>()
        let reachedKeys = new Set<string>()
        const drawPartners = (res: ReturnType<typeof placePhaseB>, wrapped: boolean) => {
          const sh = showRef.current
          if (wrapped) {
            lastLoopMax = loopMax; loopMax = new Map()
            lastLoopReaches = loopReaches; loopReaches = new Map()
            // Pair scene: a measurement starts at a loop start and ends at the next one — exactly one clip cycle.
            if (measureRef.current === 'measuring') { measureRef.current = null; onMeasuredRef.current(channelProfileOf(lastLoopMax, lastLoopReaches)) }
            else if (measureRef.current === 'armed') measureRef.current = 'measuring'
          }
          overlay.visible = !!res
          if (!res) { partnerInfo = null; return }
          const frame = res.frame
          const touching = new Set<string>()
          for (const c of frame.contacts) { touching.add(`${c.a}|${c.capA}`); touching.add(`${c.b}|${c.capB}`) }
          const usedCaps = new Set<string>(), usedCh = new Set<string>()
          let channels = 0
          for (const { name, inspection: ins } of res.figures) {
            if (!ins) continue
            if (sh.collision) for (const c of contactCapsules(ins)) {
              const key = `${name}|${c.id}`
              usedCaps.add(key)
              let line = capLines.get(key)
              if (!line) { line = capsuleWireframe(THREE, c.now, CAPSULE_REGION_COLORS[c.region]); capLines.set(key, line); overlay.add(line) }
              else placeCapsuleWireframe(THREE, line, c.now)
              ;(line.material as InstanceType<typeof THREE.LineBasicMaterial>).color.setHex(
                touching.has(key) ? CONTACT_COLOR : CAPSULE_REGION_COLORS[c.region] ?? 0xffd166)
            }
            channels += ins.channels.length
            if (sh.channels) for (const ch of ins.channels) {
              const key = `${name}|${ch.id}`
              usedCh.add(key)
              const now = ch as unknown as ChannelNow
              let line = chLines.get(key)
              if (!line) { line = channelWireframe(THREE, now, CAPSULE_REGION_COLORS.channel); chLines.set(key, line); overlay.add(line) }
              else placeChannelWireframe(THREE, line, now)
              const open = ins.openings.find((o) => o.channel === ch.id)
              let ring = rings.get(key)
              if (!ring) { ring = new THREE.LineLoop(ringGeom, ringMat); ring.renderOrder = 999; rings.set(key, ring); overlay.add(ring) }
              ring.visible = !!open
              if (open) {
                const rad = open.radius + OPENING_MARGIN_M
                ring.position.set(ch.o[0], ch.o[1], ch.o[2])
                ring.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), new THREE.Vector3(ch.u[0], ch.u[1], ch.u[2]))
                ring.scale.setScalar(rad)
              }
            }
          }
          for (const [k, l] of capLines) l.visible = usedCaps.has(k)
          for (const [k, l] of chLines) l.visible = usedCh.has(k)
          for (const [k, r] of rings) if (!usedCh.has(k)) r.visible = false
          const best = frame.closest.reduce<FrameInspection['closest'][number] | null>((w, c) => (!w || c.depth > w.depth ? c : w), null)
          if (!pausedRef.current) {
            const now = frame.engagements.flatMap((g) => (g.readout ? [g.readout] : []))
            foldReadoutMax(loopMax, now)
            const reached = new Set<string>()
            for (const r of now) {
              if (r.insertionOfDepth < 1) continue
              const key = channelReadoutKey(r)
              if (!reachedKeys.has(key)) loopReaches.set(key, (loopReaches.get(key) ?? 0) + 1)
              reached.add(key)
            }
            reachedKeys = reached
          }
          partnerInfo = {
            closest: best ? { a: letterOf(best.a), b: letterOf(best.b), capA: best.capA, capB: best.capB, mm: best.depth * 1000 } : null,
            contacts: frame.contacts.length, channels,
            engaged: frame.engagements.map((g) => {
              const key = g.readout ? channelReadoutKey(g.readout) : ''
              const full = lastLoopMax?.get(key) ?? null
              return { by: letterOf(g.by), of: letterOf(g.of), channel: g.channel, w: g.w,
                openingMm: g.opening === null ? null : g.opening * 1000, readout: g.readout,
                max: full ?? loopMax.get(key) ?? null, full: !!full }
            }),
            mouths: res.figures.flatMap(({ inspection: ins }, k) => {
              const ch = figs[k]?.collision?.channels?.find((c) => c.id === MOUTH_CHANNEL_ID)
              if (!ins || (ins.mouthOpen === null && !ch)) return []
              const mm = (v: number | undefined) => (typeof v === 'number' && v > 0 ? v * 1000 : null)
              return [{ letter: figs[k].letter, open: ins.mouthOpen, built: mm(ch?.open_height) !== null || mm(ch?.teeth_gap) !== null,
                openHeightMm: mm(ch?.open_height), teethGapMm: mm(ch?.teeth_gap) }]
            }),
          }
        }

        // ── The root of a figure — the calibration (draft over saved), then its role's turn (saved + draft, renderer-only,
        // owner decision 2026-11-23: every role) about the bind hips (`fixPivot`, stage space). ──
        const fixQ = new THREE.Quaternion()
        const placeRoot = (f: Fig, time: number, draft: AlignmentDraft) => {
          const cal = clipCalibration(draft, savedRef.current[f.role] ?? f.saved, f.placeYaw, f.place.marker.group)
          const at = calibratedRoot(cal, { anchor: f.anchor, role: f.role, hips: rootAt(f.path, time), inPlace: solo,
            hipsBind: f.hipsBind, standRefM })
          f.root.position.set(at.x, at.y, at.z)
          f.root.rotation.set(cal.euler[0], cal.euler[1], cal.euler[2], 'YXZ')
          const pivot = fixPivot([at.x, at.y, at.z], cal.frame, [f.hipsBind.x, f.hipsBind.y, f.hipsBind.z])
          if (!solo) {
            const saved = (savedRef.current[f.role] ?? f.saved).roleTurnDeg[f.role] ?? [0, 0, 0]
            const turn = draft.roleTurnDeg?.[f.role] ?? [0, 0, 0]
            // the yaw about the role's own vertical axis goes first (`roleTurnFix`)
            const fix: PairFix = roleTurnFix(saved[0] + turn[0], saved[1] + turn[1], cal.frame, saved[2] + turn[2])
            if (fix.turn.some((v) => v) || fix.shift.some((v) => v)) {
              const r = fixRoot(fix, pivot, [at.x, at.y, at.z])
              f.root.position.set(r.position[0], r.position[1], r.position[2])
              f.root.quaternion.premultiply(fixQ.set(r.quaternion[0], r.quaternion[1], r.quaternion[2], r.quaternion[3]))
            }
          }
          f.root.updateMatrixWorld(true)
          // Ruling A158: the clip's direct root angle on the attached part — on every part place (a relation's `part`;
          // without relations every figure: only one with an attached part turns). Live: read from the draft each frame.
          const parts = (draft.contactRelations ?? []).filter((x) => x.target !== 'none').map((x) => x.part)
          f.runtime.setRootAngle(!solo && (!parts.length || parts.includes(f.role)) ? draft.rootAngle ?? null : null)
          return { pivot, frame: cal.frame }
        }
        // ── Ruling A126/A139: the contact of the pair shown, its samples in stage space. ──
        type Hit = { e: number; r: number; chain: number; channel: string; target: ContactTarget }
        const stageRot = new THREE.Matrix3()
        const sv = new THREE.Vector3()
        const toStageP = (p: readonly number[], dir = false): [number, number, number] => {
          sv.set(p[0], p[1], p[2])
          if (dir) sv.applyMatrix3(stageRot.setFromMatrix4(stageInv)).normalize(); else sv.applyMatrix4(stageInv)
          return [sv.x, sv.y, sv.z]
        }
        const findHit = (res: NonNullable<ReturnType<typeof placePhaseB>>): Hit | null => {
          for (let e = 0; e < res.figures.length; e++) for (let r = 0; r < res.figures.length; r++) {
            const ie = res.figures[e].inspection, ir = res.figures[r].inspection
            if (r === e || !ie || !ir) continue
            const h = findContact(ie, ir)
            if (h) return { e, r, ...h, target: 'channel' }
          }
          return null
        }
        // Ruling A139: the clip's contact relations (draft, read live) → one hit per relation; none declared = the
        // A126 auto-detection (one hit).
        const findHits = (res: NonNullable<ReturnType<typeof placePhaseB>>,
          rels: readonly ContactRelation[] = draftRef.current.contactRelations ?? []): Hit[] => {
          if (!rels.length) { const h = findHit(res); return h ? [h] : [] }
          const out: Hit[] = []
          for (const rel of rels) {
            const e = figs.findIndex((f) => f.role === rel.part), r = figs.findIndex((f) => f.role === rel.at)
            const ie = e >= 0 ? res.figures[e].inspection : null, ir = r >= 0 ? res.figures[r].inspection : null
            const h = ie && ir ? findContact(ie, ir, rel.target) : null
            if (h) out.push({ e, r, ...h, target: rel.target })
          }
          return out
        }
        // Ruling A139: what each place's ROLE needs (from the relations) against what its person has — a part place
        // needs an attached part, an anchor place the channel / hand / head the target names.
        const roleNeeds = (res: NonNullable<ReturnType<typeof placePhaseB>>,
          all: readonly ContactRelation[] = draftRef.current.contactRelations ?? []): string[] => {
          const rels = all.filter((x) => x.target !== 'none')
          const out: string[] = []
          for (const rel of rels) {
            const e = figs.findIndex((f) => f.role === rel.part), r = figs.findIndex((f) => f.role === rel.at)
            if (e < 0 || r < 0) continue
            const ie = res.figures[e].inspection, ir = res.figures[r].inspection
            if (!ie?.chains.some((c) => c.segments.length && POINT_TARGET_OPS.includes(c.op))) {
              out.push(t('Place {p} ({who}) needs an attached part.').replace('{p}', figs[e].letter).replace('{who}', figs[e].character))
              continue
            }
            if (ir && !findContact(ie, ir, rel.target)) out.push(t('Place {p} ({who}) has no {target} for place {q}.')
              .replace('{p}', figs[r].letter).replace('{who}', figs[r].character).replace('{target}', targetWord(rel.target))
              .replace('{q}', figs[e].letter))
          }
          return out
        }
        // Ruling A150: the sample carries the moving figure's support (stage space, the surface under its place; `ids` =
        // the capsules a baseline pass chose).
        // ONE RELATION, ONE MOVER: `mover` = the figure the trial moves (its pivot `pl`, its support); the receiving one
        // marks the sample `mover: 'receiver'` (pairAlign `moveSample` then moves the channel, not the part).
        /** THE VISIBLE ROOT (pairAlign): the body-side end of the part capsule nearest the chain's root joint — how far
         *  along the shaft beyond the joint (never negative) and its radius. */
        const v3 = (p: readonly number[]): [number, number, number] => [p[0], p[1], p[2]]
        const visibleRootOf = (ie: NonNullable<NonNullable<ReturnType<typeof placePhaseB>>['figures'][number]['inspection']>,
          chain: number): { rootLeadM: number; rootRingM: number } => {
          const seg = ie.chains[chain]?.segments
          if (!seg?.length) return { rootLeadM: 0, rootRingM: 0 }
          const p0 = seg[0].a, tip = seg[seg.length - 1].b
          const d = [tip[0] - p0[0], tip[1] - p0[1], tip[2] - p0[2]], dl = Math.hypot(d[0], d[1], d[2]) || 1
          let best = Infinity, lead = 0, ring = 0
          for (const c of ie.capsules) {
            if (!PART_REGIONS.includes(c.region)) continue
            for (const end of [c.now.a, c.now.b]) {
              const g = Math.hypot(end[0] - p0[0], end[1] - p0[1], end[2] - p0[2])
              if (g < best) {
                best = g; ring = c.now.r
                lead = ((end[0] - p0[0]) * d[0] + (end[1] - p0[1]) * d[1] + (end[2] - p0[2]) * d[2]) / dl
              }
            }
          }
          return { rootLeadM: Math.max(0, lead), rootRingM: ring }
        }
        const sampleAt = (res: NonNullable<ReturnType<typeof placePhaseB>>, hit: Hit,
          pl: { pivot: [number, number, number]; frame: number[] }, ids?: readonly string[] | null, mover = hit.e): AlignSample | null => {
          const ie = res.figures[hit.e].inspection, ir = res.figures[hit.r].inspection
          const w = ie && ir ? contactSampleOf(ie, ir, hit, pl.pivot) : null
          if (!w || !ie) return null
          const im = res.figures[mover].inspection
          const support = im ? supportSample(im.capsules, { ids, surface: figs[mover].place.marker.y_world, map: (p) => toStageP(p) }) : null
          // Ruling A212 (2026-11-20): the body axes the root angle turns about, the channel's depth and the tip's radius.
          const body = entries[hit.e].figure.bodyFrame()
          const depth = w.channel ? ir?.channels.find((x) => x.id === hit.channel)?.depth ?? 0 : 0
          const segs = ie.chains[hit.chain]?.segments ?? []
          return { tip: toStageP(w.tip), base: toStageP(w.base), o: toStageP(w.o), u: toStageP(w.u, true), pivot: pl.pivot,
            chain: w.chain?.map((p) => toStageP(p)), raised: w.raised, channel: w.channel,
            body: { side: toStageP(body.side, true), up: toStageP(body.up, true) },
            ...(depth > 0 ? { depthM: depth, tipRadiusM: segs.length ? segs[segs.length - 1].r : 0 } : {}),
            ...(w.channel ? visibleRootOf(ie, hit.chain) : {}),
            ...(support ? { support } : {}), ...(mover === hit.r ? { mover: 'receiver' as const } : {}) }
        }
        // ── Ruling A145: the attached part bends toward its target near the opening — at its root when raised, at every
        // joint when resting (`chainBend.ts`) — a render step every frame; Auto-align is rigid and only reports it afterwards. ──
        /** The bend limits in force: the clip's draft (or the default) — the part always bends, as in the game (A212). */
        const bendLimitsNow = (): BendLimits | null => draftRef.current.bendLimits ?? BEND_LIMITS_DEFAULT
        /** The bend a stage sample gets when rendered (null without limits or a chain). */
        const bendOf = (smp: FitSample, lim: BendLimits | null): BendResult | null => (lim ? bendSample(smp, lim).bend : null)
        /** Bend the entering figure's chain bones of this frame (world; the same solve as `bendOf`). */
        const bendBones = (res: NonNullable<ReturnType<typeof placePhaseB>>, hit: Hit, lim: BendLimits | null): BendResult | null => {
          if (!lim) return null
          const ie = res.figures[hit.e].inspection, ir = res.figures[hit.r].inspection
          const w = ie && ir ? contactSampleOf(ie, ir, hit, [0, 0, 0]) : null
          const b = w ? bendSample(w, lim).bend : null
          if (b) entries[hit.e].figure.bendChain(hit.chain, b.turns)
          return b
        }
        /** The bend over sampled frames (largest, its limit, frames at the limit, lamp). */
        const bendReadout = (bends: readonly (BendResult | null)[]): BendReadout | null => {
          const got = bends.filter((x): x is BendResult => !!x)
          if (!got.length) return null
          const top = got.reduce((a, x) => (x.deg > a.deg ? x : a), got[0])
          const atLimit = got.filter((x) => x.atLimit).length
          return { maxDeg: top.deg, limitDeg: top.maxDeg, atLimit, frames: got.length,
            lamp: atLimit > 0 ? 'yellow' : 'green' }
        }
        // Ruling A129.5: the honest check of one frame — only the entering figure's attached part against the
        // receiving channel's `suppress` capsules is exempt; the pair is named by place letter and capsule.
        const honestAt = (res: NonNullable<ReturnType<typeof placePhaseB>>, hit: Hit) => {
          const ie = res.figures[hit.e].inspection, ir = res.figures[hit.r].inspection
          const ch = ir?.channels.find((x) => x.id === hit.channel)
          const got = pairInterpenetration(res.frame.contacts, { entering: entries[hit.e].name,
            parts: new Set((ie?.capsules ?? []).filter((c) => PART_REGIONS.includes(c.region)).map((c) => c.id)),
            receiving: entries[hit.r].name, allowed: new Set(ch?.suppress ?? []) })
          const w = got.worst
          return { mm: got.depth * 1000, worst: w ? `${letterOf(w.a)} ${w.capA} ↔ ${letterOf(w.b)} ${w.capB}` : '' }
        }
        // Ruling A139/A145: one live bend record per contact relation (the hit and the bend limits in force).
        type LiveRec = { hit: Hit; bend: BendLimits | null }
        const live: { recs: LiveRec[]; found: boolean; none: boolean } = { recs: [], found: false, none: false }
        const resetLive = () => { live.recs = []; live.found = false; live.none = false }
        // ── Ruling A212: the see-through partner — every mesh of the entering figure (body, hair, clothing, teeth, strand
        // hair) draws translucent: the flags of the material it CURRENTLY carries are flipped (no clone, so the garment
        // collision hooks on those materials stay) and restored when off; re-checked every frame, because strand hair
        // swaps meshes and materials. The part twins carry their own opaque material in the transparent pass, drawn
        // after the body (renderOrder 2). Restored on unmount: a template (the mannequin) outlives this mount. ──
        type Flags = { transparent: boolean; opacity: number; depthWrite: boolean }
        const flipped = new Map<InstanceType<typeof THREE.Material>, Flags>()
        const restore = (mat: InstanceType<typeof THREE.Material>, f: Flags) => {
          mat.transparent = f.transparent; mat.opacity = f.opacity; mat.depthWrite = f.depthWrite; mat.needsUpdate = true
        }
        disposers.push(() => { for (const [m, f] of flipped) restore(m, f); flipped.clear() })
        const seeThroughFrame = (on: readonly Fig[]) => {
          if (!on.length && !flipped.size) return
          const want = new Set<InstanceType<typeof THREE.Material>>()
          for (const f of on) {
            const twins = new Set(f.partMeshes)
            f.inst.traverse((o) => {
              const m = o as InstanceType<typeof THREE.Mesh>
              if (!m.isMesh || twins.has(m)) return
              for (const mat of (Array.isArray(m.material) ? m.material : [m.material])) if (mat) want.add(mat)
            })
          }
          for (const [m, f] of flipped) if (!want.has(m)) { restore(m, f); flipped.delete(m) }
          for (const m of want) {
            if (flipped.has(m)) continue
            flipped.set(m, { transparent: m.transparent, opacity: m.opacity, depthWrite: m.depthWrite })
            m.transparent = true; m.opacity = SEE_THROUGH_OPACITY; m.depthWrite = false; m.needsUpdate = true
          }
        }
        const draw = () => {
          controls.update()
          placeMemory.camera = { pos: [camera.position.x, camera.position.y, camera.position.z],
            target: [controls.target.x, controls.target.y, controls.target.z] }
          renderer.render(sceneObj, camera)
        }
        const scratch = new THREE.Vector3()
        const q = new THREE.Quaternion()
        const fwd = new THREE.Vector3()
        const stageInv = new THREE.Matrix4()
        let last = performance.now()
        let lastInfo = 0
        let lastBudget = 0
        let ms = 0
        let swingMm = 0
        let lastSig: string | null = null
        let seenSeq = draftSeqRef.current
        let needsSeq: unknown = {}
        let lastTime = timeRef.current
        const tick = () => {
          if (disposed) return
          raf = requestAnimationFrame(tick)
          const now = performance.now()
          const dt = Math.min(0.1, (now - last) / 1000)
          last = now
          turn.tick(dt)
          stage.matrix.fromArray(poseMatrix(turn.pose, PIVOT))
          stage.matrixWorldNeedsUpdate = true
          stage.updateMatrixWorld(true)
          stageInv.copy(stage.matrixWorld).invert()
          if (!pausedRef.current) timeRef.current = (timeRef.current + dt * speedRef.current) % duration
          const time = timeRef.current
          const wrapped = time < lastTime
          lastTime = time
          // Ruling A212: the bend always runs on a pair, as in the game.
          const pairOn = !solo && figs.length > 1
          if (seenSeq !== draftSeqRef.current) {
            resetLive()
            seenSeq = draftSeqRef.current
            for (const f of figs) { f.yawS = []; f.posS = []; f.medYaw = NaN; f.medPos = NaN }
          }
          const t0 = performance.now()
          const draft = draftRef.current
          for (const f of figs) {
            // phase A: the pose, then the root by the calibration (draft over saved, the bake's order)
            f.mixer.setTime(time)
            placeRoot(f, time, draft)
            f.runtime.poseStep({ realDelta: dt })
          }
          // Ruling A212: the entering figure(s) see-through, the attached part opaque.
          {
            const ents = live.recs.length ? live.recs.map((x) => figs[x.hit.e]) : figs.filter((x) => x.role === 'b')
            const on = showRef.current.seeThrough ? figs.filter((f) => ents.includes(f)) : []
            seeThroughFrame(on)
            for (const f of figs) for (const tw of f.partMeshes) tw.visible = on.includes(f)
            host.dataset.seeThrough = on.length
              ? JSON.stringify({ figures: on.map((f) => f.letter), materials: flipped.size }) : ''
          }
          // The fixed readout row (Ruling A212) needs every pair frame's inspection.
          const wantInspect = showRef.current.collision || showRef.current.channels || pairOn
          const bendInspect = pairOn && !live.none
          const phaseB = placePhaseB(entries, frameState, wantInspect || bendInspect || needsSeq !== draftSeqRef.current)
          if (phaseB && needsSeq !== draftSeqRef.current && !solo && figs.length > 1) {
            needsSeq = draftSeqRef.current
            const needs = roleNeeds(phaseB)
            host.dataset.roleNeeds = JSON.stringify(needs)
            setRoleIssues(needs)
            // A part place whose person has no attached part swaps ROLES (the persons stay on their places) with a
            // place that is no part place and whose person has one — once per persons/clip, then only the warning.
            const swapKey = `${kind}|${assignKey}`
            if (needs.length && swapTried.current !== swapKey) {
              swapTried.current = swapKey
              const partRoles = new Set((draftRef.current.contactRelations ?? []).filter((x) => x.target !== 'none').map((x) => x.part))
              const has = (i: number) => !!phaseB.figures[i].inspection?.chains.some((c) => c.segments.length && POINT_TARGET_OPS.includes(c.op))
              const lack = figs.findIndex((f, i) => partRoles.has(f.role) && !has(i))
              const donor = figs.findIndex((f, i) => !partRoles.has(f.role) && has(i))
              if (lack >= 0 && donor >= 0) {
                const a = figs[lack], b = figs[donor]
                setSwapNote(t('Swapped roles {r1} and {r2}: {who} has the attached part role {r1} needs.')
                  .split('{r1}').join(a.role.toUpperCase()).replace('{r2}', b.role.toUpperCase()).replace('{who}', b.character))
                setAssign((cur) => ({ ...cur, [a.letter]: { ...cur[a.letter], role: b.role }, [b.letter]: { ...cur[b.letter], role: a.role } }))
              }
            }
          }
          if (bendInspect && phaseB && !pausedRef.current) {
            if (!live.found) {
              live.recs = findHits(phaseB).map((hit) => ({ hit, bend: bendLimitsNow() }))
              live.found = true
              live.none = !live.recs.length
            }
            // Ruling A145: the entering figure's chain bones bend toward the target every frame.
            for (const rec of live.recs) bendBones(phaseB, rec.hit, rec.bend)
          }
          const inspection = wantInspect ? phaseB : null
          ms = ms * 0.9 + (performance.now() - t0) * 0.1
          drawPartners(inspection, wrapped)
          // readout: hips in stage space against the place
          for (const f of figs) {
            if (!f.hips) continue
            f.hips.getWorldPosition(scratch).applyMatrix4(stageInv)
            f.hips.getWorldQuaternion(q)
            q.premultiply(new THREE.Quaternion().setFromRotationMatrix(stageInv)).multiply(f.bindInv)
            fwd.set(0, 0, 1).applyQuaternion(q)
            const d = alignmentDelta({ x: fwd.x, z: fwd.z }, f.place.facing, { x: scratch.x, z: scratch.z },
              { x: f.place.point[0], z: f.place.point[1] })
            f.dyaw = d.dyaw; f.dpos = d.dpos
            if (wrapped && f.yawS.length) { f.medYaw = median(f.yawS); f.medPos = median(f.posS); f.yawS = []; f.posS = [] }
            if (!pausedRef.current) { f.yawS.push(d.dyaw); f.posS.push(d.dpos) }
            f.arrow.position.set(scratch.x, f.place.marker.y_world + 0.05, scratch.z)
            const len = Math.hypot(fwd.x, fwd.z) || 1
            f.arrow.setDirection(scratch.set(fwd.x / len, 0, fwd.z / len))
            // the evidence that the hair moves: every hair chain tip's travel in the HEAD's frame (mm, max)
            const h = f.head as Object3D | null
            if (h) for (const tip of f.tips) {
              h.worldToLocal(tip.getWorldPosition(scratch))
              const rest = f.tipRest.get(tip)
              if (!rest) f.tipRest.set(tip, scratch.clone())
              else swingMm = Math.max(swingMm, rest.distanceTo(scratch) * 1000 * h.getWorldScale(fwd).x)
            }
          }
          if (now - lastBudget > 500 && figs.length) {
            lastBudget = now
            // D5: strand hair for the 2 nearest the camera, the rest on chains.
            const views = figs.map((f) => ({ name: f.letter, position: f.root.getWorldPosition(new THREE.Vector3()),
              tier: 'full' as const, hasRecord: f.hasRecord, firstPerson: false, costMs: f.runtime.strandCostMs,
              running: f.runtime.strandRunning }))
            const on = new Set(strandCandidates(views, camera.position).sort((a, b) => a.distance - b.distance)
              .slice(0, STRAND_FIGURES).map((c) => c.name))
            for (const f of figs) if (f.hasRecord) f.runtime.setStrandHair(on.has(f.letter))
          }
          if (now - lastInfo > 250) {
            lastInfo = now
            const rows: FigureReadout[] = figs.map((f) => {
              const medYaw = Number.isFinite(f.medYaw) ? f.medYaw : (f.yawS.length ? median(f.yawS) : f.dyaw)
              const medPos = Number.isFinite(f.medPos) ? f.medPos : (f.posS.length ? median(f.posS) : f.dpos)
              return { letter: f.letter, character: f.character, role: f.role, dyaw: f.dyaw, dpos: f.dpos, medYaw, medPos,
                lamp: Number.isFinite(f.medYaw) ? alignmentLamp(medYaw, medPos) : null }
            })
            setInfo({ ms, swingMm, strands: figs.filter((f) => f.runtime.strandRunning).length,
              chains: figs.filter((f) => !f.runtime.strandRunning && f.chains > 0).length, figures: rows,
              partners: partnerInfo })
            host.dataset.partners = partnerInfo ? JSON.stringify(partnerInfo) : ''
            host.dataset.figures = JSON.stringify(figs.map((f) => {
              f.hips?.getWorldPosition(scratch).applyMatrix4(stageInv)
              return { letter: f.letter, time: +time.toFixed(4), hips: [scratch.x, scratch.y, scratch.z].map((v) => +v.toFixed(5)),
                dyaw: +f.dyaw.toFixed(3), dpos: +f.dpos.toFixed(3) }
            }))
            host.dataset.frameMs = ms.toFixed(2)
            const done = rows.filter((r) => r.lamp)
            const ready = done.length > 0 && done.length === rows.length
            // Only a CHANGED readout reaches the Library (it re-renders the whole edit view).
            const sig = ready ? rows.map((r) => `${r.letter}${r.medYaw.toFixed(1)}/${r.medPos.toFixed(1)}`).join() : ''
            if (sig === lastSig) { draw(); return }
            lastSig = sig
            onReadoutRef.current?.(ready ? {
              prop: propName, places: rows.map((r) => r.letter).join('+'), figures: rows,
              allGreen: rows.every((r) => r.lamp === 'green'),
              worstYaw: rows.reduce((w, r) => Math.abs(r.medYaw) > Math.abs(w) ? r.medYaw : w, 0),
              worstPos: Math.max(...rows.map((r) => r.medPos)),
            } : null)
          }
          draw()
        }
        // ── Ruling A212 (the owner's procedure of 2026-11-20): Auto-align ADJUSTS around the user's base arrangement
        // (the dials when it is clicked). Plays the clip in fixed 60 fps steps (two loops, the second sampled) with the
        // role that carries the attached part moved by `extra` (clip frame metres [side, up, forward] on top of the
        // draft) and the clip's root angle in force, and solves the DEEPEST and the SHALLOWEST frame of every contact
        // relation of that role together: the rigid shaft along the axis through the opening at both, the part as deep
        // as it goes at the deepest (scene-render `pairAlign.ts`). Measure → solve → measure again until the increment
        // vanishes. One click aligns ONE relation and moves the role it names (the part's carrier or the receiving
        // role); every other role stays. A cap or slider range that stops it is named. ──
        const step = 1 / 60
        const placed = new Map<Fig, { pivot: [number, number, number]; frame: number[] }>()
        const runAt = (time: number, draft: AlignmentDraft, inspect: boolean, isolated = false) => {
          for (const f of figs) {
            f.mixer.setTime(time)
            placed.set(f, placeRoot(f, time, draft))
            f.runtime.poseStep({ realDelta: step })
          }
          return placePhaseB(entries, frameState, inspect, { isolated })
        }
        const hipsStage = (f: Fig): [number, number, number] => {
          if (!f.hips) return [f.root.position.x, f.root.position.y, f.root.position.z]
          f.hips.getWorldPosition(scratch).applyMatrix4(stageInv)
          return [scratch.x, scratch.y, scratch.z]
        }
        type FigCaps = { pivot: [number, number, number]; caps: ClearCapsule[][] }
        type PassOut = { per: AlignSample[][]; ks: number[][]; overlap: number; worst: string; draft: AlignmentDraft
          heights: Map<number, { ids: string[]; h: number; mode: 'surface' | 'band' }>
          /** THE CLEARANCE (pairAlign): per sampled frame k every figure's stage capsules and the mover's pivot; per figure
           *  the mover's worst overlap with it over the loop (metres) and its capsule pair; per frame the per-figure depths. */
          caps: Map<number, FigCaps>; clearBy: number[]; clearWorst: string[]; clearAt: Map<number, number[]> }
        const relLabel = (h: Hit) => `${figs[h.e].letter} → ${figs[h.r].letter} (${targetWordOf(t, h.target)})`
        /** A relation's key in "Align all" (part role > receiving role : target) — the per-row mover choice. */
        const relKey = (h: Hit) => `${figs[h.e].role}>${figs[h.r].role}:${h.target}`
        const stageCaps = (insp: NonNullable<NonNullable<ReturnType<typeof placePhaseB>>['figures'][number]['inspection']>): ClearCapsule[] =>
          contactCapsules(insp).map((c) => ({ id: c.id, a: toStageP(c.now.a), b: toStageP(c.now.b), r: c.now.r }))
        const autoAlign = (opts: AutoAlignOptions = {}): AutoAlignResult => {
          if (solo || figs.length < 2) return { ok: false, reason: t('Auto-align needs a pair clip on a place.'), code: 'no_pair' }
          const loop = Math.max(8, Math.ceil(duration / step))
          const base = draftRef.current
          const rels = opts.relations ?? base.contactRelations ?? []
          const probe = runAt(timeRef.current, base, true)
          if (rels.length && rels.every((x) => x.target === 'none'))
            return { ok: false, reason: t('Every contact of this clip is “none”: nothing to align.') }
          const all = probe ? findHits(probe, rels) : []
          if (rels.length) {
            const needs = probe ? roleNeeds(probe, rels) : []
            if (needs.length) return { ok: false, reason: needs.join(' '), code: 'no_part' }
          }
          if (!all.length) return { ok: false, reason: t('No figure here has an attached part that one of the other figure’s channels accepts.'), code: 'no_part' }
          // ONE RELATION, ONE MOVER (2026-11-22): a click names the relation and the role that moves; "Align all" runs
          // every relation one after the other (`each`); without either (end clips) every relation is aligned by its part's
          // carrier, one solve per figure.
          const only = opts.only
          const hits = !only ? all : only === 'detected' ? all.slice(0, 1)
            : all.filter((h) => figs[h.e].role === only.part && figs[h.r].role === only.at && h.target === only.target)
          if (!hits.length) return { ok: false, code: 'no_part', reason: t('This contact is not in the scene: {rel}.').replace('{rel}',
            only && only !== 'detected' ? `${only.part.toUpperCase()} → ${only.at.toUpperCase()} (${targetWordOf(t, only.target)})` : '–') }
          const bendLim = bendLimitsNow()
          const fileA = clips.find((c) => (c.set || '') === set.trim() && c.role === 'a') ?? clips.find((c) => c.role === 'a')
          const cap = alignCap(opts.rangeCm ?? fileA?.align_range?.cm, opts.turnDeg ?? fileA?.align_turn?.deg)
          const rangeCm = Math.round(cap.forwardM * 1000) / 10
          // Auto-align is RIGID: the contact report and the key rows read the samples as solved (no bend); the key rows
          // and the bend readout say what the bend still does there afterwards.
          const rep = (smps: readonly FitSample[]) => contactReport(smps)
          const cm = (v: number) => Math.round(v * 1000) / 10
          const deg = (v: number) => Math.round(v * 10) / 10
          // Ruling A158: the clip has ONE root angle; it turns the attached part of every part place (`placeRoot`). The
          // first group whose part chain it turns solves it, the others keep it.
          const partRels = rels.filter((x) => x.target !== 'none')
          const partRoles = partRels.map((x) => x.part)
          const rootTurns = (role: string) => !partRoles.length || partRoles.includes(role)
          // THE CLEARANCE: the pairs the honest check exempts (an attached-part capsule against a receiving channel's
          // suppress capsules) for every contact of the scene, seen from either figure as the mover.
          const exempt = new Set<string>()
          for (const h of all) {
            const ie = probe?.figures[h.e].inspection, ir = probe?.figures[h.r].inspection
            const parts = (ie?.capsules ?? []).filter((c) => PART_REGIONS.includes(c.region)).map((c) => c.id)
            const sup = ir?.channels.find((x) => x.id === h.channel)?.suppress ?? []
            for (const p of parts) for (const s of sup) {
              exempt.add(`${p}|${entries[h.r].name}|${s}`)
              exempt.add(`${s}|${entries[h.e].name}|${p}`)
            }
          }
          // THE RENDERED ROOT (owner finding 2026-11-22, crouching-mission): the part's root over the loop AS RENDERED —
          // partners on (channel engagement, guidance), the chain bend applied every frame as `tick` does — per frame
          // the root joint's depth along the axis and the VISIBLE root's (pairAlign `visibleRootDepth`), mm, + = inside the
          // opening. The isolated samples the solve reads give the same numbers for the root joint.
          type RootFrame = { k: number; rootMm: number; visMm: number; tipMm: number; u: [number, number, number]; d: [number, number, number] }
          const renderedRoots = (draft: AlignmentDraft, hit: Hit, isolated = false): RootFrame[] => {
            const out: RootFrame[] = []
            resetAll()
            const lim = bendLimitsNow()
            for (let i = 0; i < 2 * loop; i++) {
              const time = (i % loop) * step % duration
              const res = runAt(time, draft, true, isolated)
              if (!res) continue
              if (!isolated) bendBones(res, hit, lim)
              if (i < loop) continue
              const ie = res.figures[hit.e].inspection, ir = res.figures[hit.r].inspection
              const ch = ir?.channels.find((x) => x.id === hit.channel)
              const seg = ie?.chains[hit.chain]?.segments
              if (!ie || !ch || !seg?.length || isPointTarget(hit.target)) continue
              const u0 = ch.u, ul = Math.hypot(u0[0], u0[1], u0[2]) || 1
              const u = [u0[0] / ul, u0[1] / ul, u0[2] / ul]
              const s = (p: readonly number[]) => (p[0] - ch.o[0]) * u[0] + (p[1] - ch.o[1]) * u[1] + (p[2] - ch.o[2]) * u[2]
              const p0 = seg[0].a, tip = seg[seg.length - 1].b
              const vr = visibleRootOf(ie, hit.chain)
              const vis = visibleRootDepth({ o: v3(ch.o), u: v3(u), tip: v3(tip), ...vr }, v3(p0))
              const dl = Math.hypot(tip[0] - p0[0], tip[1] - p0[1], tip[2] - p0[2]) || 1
              out.push({ k: i - loop, rootMm: s(p0) * 1000, visMm: vis * 1000, tipMm: s(tip) * 1000, u: [u[0], u[1], u[2]],
                d: [(tip[0] - p0[0]) / dl, (tip[1] - p0[1]) / dl, (tip[2] - p0[2]) / dl] })
            }
            return out
          }
          const rootPeak = (fr: readonly RootFrame[]): RootFrameView => {
            const p = fr.reduce((a, x) => (x.visMm > a.visMm ? x : a), fr[0] ?? { k: -1, rootMm: NaN, visMm: NaN, tipMm: NaN, u: [0, 0, 1], d: [0, 0, 1] })
            return { k: p.k, rootMm: p.rootMm, visMm: p.visMm, tipMm: p.tipMm }
          }
          // Every pass starts from the same rest state and samples WITHOUT partners (`placePhaseB` isolated): no
          // channel engagement, guidance or latch carries over from the frames before (module docstring of pairAlign).
          const resetAll = () => { for (const f of figs) f.runtime.reset() }
          type Cand = { rows: RelationAlign[]; moverRow: MoverAlign; draft: AlignmentDraft; applied: boolean; solvedRoot: boolean
            pivot: AlignSample[][]; cand: AlignCandidate; blocked: boolean }
          /** One bounded solve of `group` (relations of one part figure) moving figure `mi` from `start`, and its
           *  verdict (pairAlign THE CLEARANCE / THE VERDICT). A string = why it could not be measured. */
          const runGroup = (group: Hit[], mi: number, moverKind: AlignMover, start: AlignmentDraft, mayRoot: boolean): Cand | string => {
            const moving = figs[mi]
            const mr = moving.role
            const partFig = group[0].e
            const anchor = figs[moverKind === 'receiver' ? group[0].e : group[0].r]
            const b0 = start.roleShiftM[mr] ?? [0, 0, 0]
            const t0: [number, number, number] = [...(start.roleTurnDeg?.[mr] ?? [0, 0, 0])] as [number, number, number]
            // The BASE the cap is measured from (Ruling A212 review H1): the arrangement the user set, not the dials an
            // earlier Auto-align already moved — a second click stays inside the same cap.
            const bb = opts.base ? opts.base.roleShiftM?.[mr] ?? [0, 0, 0] : b0
            const tb: [number, number, number] = opts.base ? [...(opts.base.roleTurnDeg?.[mr] ?? [0, 0, 0])] as [number, number, number] : t0
            const savedTurn = (savedRef.current[mr] ?? moving.saved).roleTurnDeg[mr] ?? [0, 0, 0]
            // THE ROLE TURN (owner 2026-11-23): any moved role turns, within the clip's rotation range.
            const turns = cap.angleDeg > 0
            const root0: RootAngle = { pitchDeg: start.rootAngle?.pitchDeg ?? 0, yawDeg: start.rootAngle?.yawDeg ?? 0 }
            // The chain the root angle turns: the PART figure's first chain with a point-target op (`applyRootAngle`).
            const rootChain = probe!.figures[partFig].inspection?.chains.findIndex((c) => c.segments.length > 0 && POINT_TARGET_OPS.includes(c.op)) ?? -1
            const turnsRoot = rootTurns(figs[partFig].role) && group.some((h) => h.chain === rootChain)
            const solveRoot = mayRoot && turnsRoot
            const draftOf = (extra: [number, number, number], turn: readonly number[], root: RootAngle | null): AlignmentDraft => ({ ...start,
              roleShiftM: { ...start.roleShiftM, [mr]: [bb[0] + extra[0], bb[1] + extra[1], bb[2] + extra[2]] },
              roleTurnDeg: turns ? { ...(start.roleTurnDeg ?? {}), [mr]: [tb[0] + (turn[0] ?? 0), tb[1] + (turn[1] ?? 0), tb[2] + (turn[2] ?? 0)] }
                : start.roleTurnDeg,
              ...(root ? { rootAngle: root } : {}) })
            // Ruling A150: the moving figure's own posture per frame index (its support capsules and height), from the
            // baseline pass; every later pass keeps the same capsules and measures against that height.
            const placeGroup = moving.place.marker.group
            let baseline: Map<number, { ids: string[]; h: number; mode: 'surface' | 'band' }> | null = null
            let moverFrame: number[] = [1, 0, 0, 0, 1, 0, 0, 0, 1]
            const moverName = entries[mi].name
            const nameAt = new Map(entries.map((e, j) => [e.name, j]))
            const pass = (extra: [number, number, number], turn: readonly number[] = [0, 0, 0], root: RootAngle | null = null): PassOut => {
              const draft = draftOf(extra, turn, root)
              const per: AlignSample[][] = group.map(() => [])
              const ks: number[][] = group.map(() => [])
              const heights = new Map<number, { ids: string[]; h: number; mode: 'surface' | 'band' }>()
              const caps = new Map<number, FigCaps>()
              const clearAt = new Map<number, number[]>()
              const clearBy = figs.map(() => 0), clearWorst = figs.map(() => '')
              let overlap = 0, worst = ''   // mm while sampling (A129.5 honest check)
              resetAll()
              for (let i = 0; i < 2 * loop; i++) {
                const time = (i % loop) * step % duration
                const res = runAt(time, draft, i >= loop, true)
                if (!res) continue
                const pl = placed.get(moving)!
                const k = i - loop
                moverFrame = pl.frame
                group.forEach((hit, gi) => {
                  const smp = sampleAt(res, hit, pl, gi === 0 ? baseline?.get(k)?.ids : undefined, mi)
                  if (!smp) return
                  if (gi === 0 && smp.support) {
                    heights.set(k, { ids: smp.support.ids, h: supportHeight(smp.support.pts, smp.support.r), mode: supportMode(smp.support) })
                    const b = baseline?.get(k)
                    // THE SUPPORT, ABSOLUTE: the mode of this frame from the base arrangement (postureSupport `supportMode`).
                    if (b) smp.support = { ...smp.support, base: b.h, mode: b.mode }
                  } else if (gi > 0) delete smp.support
                  per[gi].push({ ...smp, phase: duration > 0 ? time / duration : 0 })
                  ks[gi].push(k)
                  const h = honestAt(res, hit)
                  if (h.mm > overlap) { overlap = h.mm; worst = h.worst }
                })
                if (k < 0) continue
                // THE CLEARANCE: the mover against every other figure this frame (exempt pairs skipped).
                caps.set(k, { pivot: pl.pivot, caps: res.figures.map((f) => (f.inspection ? stageCaps(f.inspection) : [])) })
                const ds = figs.map(() => 0)
                for (const c of res.frame.contacts) {
                  const mine = c.a === moverName ? { cap: c.capA, other: c.b, oc: c.capB } : c.b === moverName ? { cap: c.capB, other: c.a, oc: c.capA } : null
                  if (!mine || exempt.has(`${mine.cap}|${mine.other}|${mine.oc}`)) continue
                  const j = nameAt.get(mine.other)
                  if (j === undefined || c.depth <= ds[j]) continue
                  ds[j] = c.depth
                  if (c.depth > clearBy[j]) { clearBy[j] = c.depth; clearWorst[j] = `${moving.letter} ${mine.cap} ↔ ${figs[j].letter} ${mine.oc}` }
                }
                clearAt.set(k, ds)
              }
              return { per, ks, overlap: overlap / 1000, worst, draft, heights, caps, clearBy, clearWorst, clearAt }
            }
            // the moving role's clip frame → world shift: B = frame · diag(1, k, 1) (the vertical through the hips-drop
            // gain: root.y moves by hipsBind.y / standRef per metre of clip hips).
            const basisOf = (draft: AlignmentDraft): number[] => {
              const m = clipCalibration(draft, savedRef.current[mr] ?? moving.saved, moving.placeYaw, placeGroup).frame
              const k = standRefM > 0 && moving.hipsBind.y > 0 ? moving.hipsBind.y / standRefM : 1
              return [m[0], m[1] * k, m[2], m[3], m[4] * k, m[5], m[6], m[7] * k, m[8]]
            }
            // The join (end clips): where the base clip's last frame left this role against the other role.
            const joinOf = (draft: AlignmentDraft) => {
              const rel = opts.join?.rel[`${mr}|${anchor.role}`]
              if (!rel) return null
              runAt(0, draft, false)
              return { deltaM: joinDelta(placed.get(anchor)!.frame, rel, hipsStage(moving), hipsStage(anchor)) }
            }
            const st0 = turns ? [-(savedTurn[0] + tb[0]), -(savedTurn[1] + tb[1]), -(savedTurn[2] + tb[2])] : [0, 0, 0]
            baseline = pass([-bb[0], -bb[1], -bb[2]], st0).heights
            // the dials now, relative to the base
            const x0: [number, number, number] = [b0[0] - bb[0], b0[1] - bb[1], b0[2] - bb[2]]
            const a0: [number, number, number] = turns ? [t0[0] - tb[0], t0[1] - tb[1], t0[2] - tb[2]] : [0, 0, 0]
            const p0 = pass(x0, a0)
            if (p0.per.some((x) => x.length < 4)) return t('The contact could not be sampled over the clip.')
            // THE CLEARANCE: each other figure's allowance from the start (the dials when clicked).
            const others = figs.map((_, j) => j).filter((j) => j !== mi)
            const allow = figs.map((_, j) => clearAllowM(p0.clearBy[j]))
            const clearOf = (got: PassOut): ClearFrame[] => {
              const want = new Set<number>()
              got.per.forEach((smps, gi) => {
                const kf = keyFrames(smps)
                if (kf) { want.add(got.ks[gi][kf.deep]); want.add(got.ks[gi][kf.shallow]) }
              })
              // plus the frame with the largest excess over an allowance (any overlap at all; none = no such frame)
              let wk = -1, wx = -Infinity
              for (const [k, ds] of got.clearAt) for (const j of others) if (ds[j] > 0 && ds[j] - allow[j] > wx) { wx = ds[j] - allow[j]; wk = k }
              if (wk >= 0) want.add(wk)
              const out: ClearFrame[] = []
              for (const k of want) {
                const fc = got.caps.get(k)
                if (!fc) continue
                out.push({ pivot: fc.pivot, mover: fc.caps[mi], exempt,
                  others: others.map((j) => ({ name: entries[j].name, allowM: allow[j], caps: fc.caps[j] })) })
              }
              return out
            }
            // Measure → solve → measure again (`alignByPasses`); the first measurement is p0.
            let firstUsed = false
            const measure = (s: { x: [number, number, number]; deg: number[]; root: RootAngle | null }) => {
              const got = firstUsed ? pass(s.x, turns ? [s.deg[0] ?? 0, s.deg[1] ?? 0, s.deg[2] ?? 0] : [0, 0, 0], s.root) : p0
              firstUsed = true
              return { relations: got.per.map((samples, gi) => ({ samples, rooted: solveRoot && group[gi].chain === rootChain })),
                basis: basisOf(got.draft), join: joinOf(got.draft), clear: clearOf(got), out: got }
            }
            // THE ROLE TURN: the trial's rotation as rendered — the moved role's clip frame and what is already stored and
            // drafted under the base (pairAlign `roleTurnDelta`); a standing role keeps its tilt/roll within the posture cap.
            const frame0 = moverFrame
            const solveRun = (seeds: boolean) => {
              firstUsed = false
              return alignByPasses(measure, { cap, seeds,
                turn: turns ? { frame: frame0, offsetDeg: [savedTurn[0] + tb[0], savedTurn[1] + tb[1], savedTurn[2] + tb[2]] } : null,
                angleCapDeg: turns ? postureAngleCapDeg(placeGroup, cap.angleDeg) : undefined },
              { x: x0, deg: turns ? a0 : [], root: solveRoot ? root0 : null })
            }
            // THE SEEDS are ranked by the solve's MODEL, which is least exact for the large turns they start from
            // (crouching-doggy 2026-11-23: a seed at the 45° caps modelled 85 mm axis error and measured 154 mm against
            // 114 mm at the start). A seeded run whose measured axis error ends worse than the start is run again from
            // the start alone, and the better of the two measured results is kept.
            const worstAxis = (r: ReturnType<typeof solveRun>) => Math.max(0, ...group.map((h, gi) => {
              const kb = keyReport(p0.per[gi], bendLim), ka = keyReport(r.last.out.per[gi], bendLim)
              const inside = !isPointTarget(h.target)
              return kb && ka ? keyWorstMm(ka, inside) - keyWorstMm(kb, inside) : 0
            }))
            let run = solveRun(true)
            if (turns && cap.angleDeg >= 30 && worstAxis(run) > ALIGN_GAIN_SLACK_MM) {
              const plain = solveRun(false)
              if (worstAxis(plain) < worstAxis(run)) run = plain
            }
            let cur = run.last.out
            let extra: [number, number, number] = [run.state.x[0], run.state.x[1], run.state.x[2]]
            const turn: [number, number, number] = turns ? [run.state.deg[0] ?? 0, run.state.deg[1] ?? 0, run.state.deg[2] ?? 0] : [0, 0, 0]
            const hitsNow = run.sol?.hits ?? []
            const slack = ALIGN_CLEAR_SLACK_MM / 1000
            // THE SUPPORT, ABSOLUTE: the moved role's gap over its surface over the loop, before and after, and every
            // other role's at the start (reported only).
            const gapRange = (smps: readonly AlignSample[]): [number, number] | null => {
              const g = smps.map((x) => surfaceGap(x.support)).filter((v): v is number => v !== null)
              return g.length ? [Math.min(...g) * 1000, Math.max(...g) * 1000] : null
            }
            const excessOf = (smps: readonly AlignSample[]) => Math.max(0, ...smps.map((x) => {
              const g = x.support?.mode === 'surface' ? surfaceGap(x.support) : null
              return g === null ? 0 : Math.abs(surfaceExcess(g)) * 1000
            }))
            // THE ROOT PULL-BACK (owner 2026-11-23 evening): the solve holds the visible root outside on the isolated
            // samples; what the page SHOWS is the loop as rendered (partners on, the chain bend). Measured there: while
            // the visible root is inside the margin on some frame, the moved role is drawn back by the missing depth (the
            // part's carrier out of the opening, the receiving role away from the part) along that frame's SHAFT — the
            // line from the part's root through its tip, which is the channel axis once aligned. Along the shaft the
            // shaft line stays where it is, so the axis error (the opening-plane offset, the angle) does not change; along
            // the axis itself a shaft 50–60° off it slid sideways across the opening (crouching-doggy: +39 mm axis error
            // for a 21 mm pull). The step travels need / cos θ (θ the shaft's angle to the axis, cos at least 0.3),
            // within the range cap, THE CLEARANCE (a step that would go into a person is halved, at most three times) and
            // THE SUPPORT (a role on a surface tries the shaft's horizontal part next, so it stays on its surface). What
            // stopped it is named when the root stays inside: the range cap, the person, or the support. Depth is
            // whatever remains.
            const chHits = group.filter((h) => !isPointTarget(h.target))
            const renderAll = (draft: AlignmentDraft) => chHits.map((h) => renderedRoots(draft, h))
            let afterFrames = renderAll(cur.draft)
            const solvedVisMm = Math.max(-Infinity, ...afterFrames.flat().map((x) => x.visMm))
            const solvedAxisMm = Math.max(0, ...group.map((h, gi) => { const k = keyReport(cur.per[gi], bendLim); return k ? keyWorstMm(k, !isPointTarget(h.target)) : 0 }))
            let pulledM = 0
            let stuck: { why: 'range' | 'overlap' | 'support'; with: string } | null = null
            const capM = [cap.sideM, cap.upM, cap.forwardM]
            const mulB = (B: readonly number[], v: readonly number[]) => [B[0] * v[0] + B[1] * v[1] + B[2] * v[2],
              B[3] * v[0] + B[4] * v[1] + B[5] * v[2], B[6] * v[0] + B[7] * v[1] + B[8] * v[2]]
            // THE SUPPORT holds through the pull too: a role on a surface may not end further off it than at the start.
            const onSurface = p0.per[0]?.some((x) => x.support?.mode === 'surface') ?? false
            // (bounded by the start or the solved state, whichever is further off: the pull never makes it worse)
            const excessCap = onSurface ? Math.max(0, excessOf(p0.per[0]), excessOf(cur.per[0])) + ALIGN_SUPPORT_SLACK_MM : Infinity
            const supportOk = (got: PassOut) => !onSurface || excessOf(got.per[0]) <= excessCap
            for (let it = 0; it < 8 && chHits.length; it++) {
              let peak: RootFrame | null = null
              for (const fr of afterFrames) for (const x of fr) if (!peak || x.visMm > peak.visMm) peak = x
              if (!peak || !(peak.visMm > -ALIGN_ROOT_MARGIN_MM)) break
              const needM = (peak.visMm + ALIGN_ROOT_MARGIN_MM + 0.5) / 1000
              const sgn = moverKind === 'receiver' ? 1 : -1
              const B = basisOf(cur.draft)
              // The directions, in order: the shaft; for a role on a surface, the shaft's horizontal part (it stays on
              // its surface — the shaft line then moves a little sideways, the price of keeping the support).
              const d = peak.d, u = peak.u
              const hl = Math.hypot(d[0], d[2])
              const dirs: [number, number, number][] = [d]
              if (onSurface && hl > 1e-6) dirs.push([d[0] / hl, 0, d[2] / hl])
              let took = false, tookF = 0, hitWith = '', why: 'range' | 'overlap' | 'support' | '' = '', clampedStep = false
              for (const dir of dirs) {
                const along = dir[0] * u[0] + dir[1] * u[1] + dir[2] * u[2]
                if (along < 0.3) continue
                const travel = needM / along
                const dx = solveLinear([[B[0], B[1], B[2]], [B[3], B[4], B[5]], [B[6], B[7], B[8]]],
                  [dir[0] * travel * sgn, dir[1] * travel * sgn, dir[2] * travel * sgn])
                if (!dx) continue
                const want: [number, number, number] = [extra[0] + dx[0], extra[1] + dx[1], extra[2] + dx[2]]
                const clamped = want.map((v, i) => Math.max(-capM[i], Math.min(capM[i], v))) as [number, number, number]
                const step = clamped.map((v, i) => v - extra[i])
                if (Math.max(...step.map(Math.abs)) < 1e-5) { why = why || 'range'; continue }
                for (let h = 0; h < 4 && !took; h++) {
                  const f = 0.5 ** h
                  const tryX: [number, number, number] = [extra[0] + step[0] * f, extra[1] + step[1] * f, extra[2] + step[2] * f]
                  const got = pass(tryX, turn, run.state.root)
                  const over = others.find((j) => got.clearBy[j] > allow[j] + slack)
                  if (over !== undefined) { if (!hitWith) hitWith = figs[over].letter; why = 'overlap'; continue }
                  if (!supportOk(got)) { if (why !== 'overlap') why = 'support'; continue }
                  const sw = mulB(B, [step[0] * f, step[1] * f, step[2] * f])
                  pulledM += Math.hypot(sw[0], sw[1], sw[2])
                  cur = got; extra = tryX; took = true; tookF = f
                  clampedStep = clamped.some((v, i) => Math.abs(v - want[i]) > 1e-9)
                }
                if (took) break
              }
              afterFrames = renderAll(cur.draft)
              if (!took) { stuck = { why: why || 'range', with: why === 'overlap' ? hitWith : '' }; break }
              if (tookF === 1 && clampedStep) {
                if (afterFrames.some((fr) => fr.some((x) => x.visMm > 0))) stuck = { why: 'range', with: '' }
                break
              }
            }
            const rootInsideNow = afterFrames.some((fr) => fr.some((x) => x.visMm > 0))
            if (!rootInsideNow) stuck = null
            else if (!stuck) stuck = { why: 'range', with: '' }
            const postureOf = (smps: readonly FitSample[]) => {
              const r = postureReport(smps.map((x) => ({ support: x.support })))
              return r.frames ? r : null
            }
            const shiftCm: [number, number, number] = [cm(bb[0] + extra[0]), cm(bb[1] + extra[1]), cm(bb[2] + extra[2])]
            const turnDeg: [number, number, number] = turns ? [deg(tb[0] + turn[0]), deg(tb[1] + turn[1]), deg(tb[2] + turn[2])]
              : [deg(t0[0]), deg(t0[1]), deg(t0[2])]
            const adjustCm: [number, number, number] = [cm(extra[0] - x0[0]), cm(extra[1] - x0[1]), cm(extra[2] - x0[2])]
            const adjustDeg: [number, number, number] = [deg(turn[0] - a0[0]), deg(turn[1] - a0[1]), deg(turn[2] - a0[2])]
            const modes = new Set(p0.per[0].map((x) => x.support?.mode ?? 'none'))
            const othersSupport = figs.map((f, j) => ({ f, j })).filter(({ j }) => j !== mi).map(({ f, j }) => {
              const g: number[] = []
              for (const fc of p0.caps.values()) {
                const low = fc.caps[j].filter((c) => SUPPORT_CAPSULES.includes(c.id))
                if (low.length) g.push(Math.min(...low.map((c) => Math.min(c.a[1], c.b[1]) - c.r)) - f.place.marker.y_world)
              }
              return { letter: f.letter, role: f.role, mm: g.length ? [Math.min(...g) * 1000, Math.max(...g) * 1000] as [number, number] : null }
            })
            const support: RelationAlign['support'] = {
              mode: modes.has('surface') ? 'surface' : modes.has('band') ? 'band' : 'none',
              beforeMm: gapRange(p0.per[0]), afterMm: gapRange(cur.per[0]),
              excessBeforeMm: excessOf(p0.per[0]), excessAfterMm: excessOf(cur.per[0]), others: othersSupport }
            // THE CLEARANCE after the run, over the whole loop of the last measurement.
            const clearRows: ClearRow[] = others.map((j) => ({ name: figs[j].letter, startM: p0.clearBy[j], allowM: allow[j],
              afterM: cur.clearBy[j], worst: cur.clearWorst[j] || p0.clearWorst[j] }))
            // THE WHOLE SCENE's deepest overlap (any pair, the A129.5 honest check) may not deepen either: the other roles'
            // placement and bend follow the moved one, so a pair without the mover can go deeper (sitting-mission
            // 2026-11-23: C↔D 176 → 191 mm while every pair with the mover got shallower).
            if (cur.overlap > p0.overlap + slack) {
              const pair = [...new Set((cur.worst.match(/(?:^|↔ )([A-Z])\b/g) ?? []).map((s) => s.replace('↔', '').trim()))].join('↔')
              clearRows.push({ name: pair || '–', startM: p0.overlap, allowM: p0.overlap, afterM: cur.overlap, worst: cur.worst })
            }
            const clearOk = clearRows.every((c) => c.afterM <= c.allowM + slack)
            // THE RENDERED ROOT before and after (and the isolated loop the solve reads, frame by frame).
            const rendered = group.map((hit) => {
              if (isPointTarget(hit.target)) return null
              const before = renderedRoots(p0.draft, hit), after = afterFrames[chHits.indexOf(hit)] ?? renderedRoots(cur.draft, hit)
              const iso = renderedRoots(cur.draft, hit, true)
              return { before: rootPeak(before), after: rootPeak(after), isolated: rootPeak(iso),
                frames: after.map((x, i) => ({ k: x.k, rootMm: x.rootMm, visMm: x.visMm, tipMm: x.tipMm,
                  isoRootMm: iso[i]?.rootMm ?? NaN, isoVisMm: iso[i]?.visMm ?? NaN })) }
            })
            const reports = group.map((hit, gi) => {
              const kb = keyReport(p0.per[gi], bendLim), ka = keyReport(cur.per[gi], bendLim)
              const inside = !isPointTarget(hit.target)
              const rr = rendered[gi]
              return { kb, ka, inside, verdict: alignVerdict(kb, ka, inside, clearRows,
                rr ? { beforeMm: rr.before.visMm, afterMm: rr.after.visMm, pulledMm: pulledM * 1000 } : null,
                support.mode === 'surface' ? { beforeMm: support.excessBeforeMm, afterMm: support.excessAfterMm } : null) }
            })
            // A group is discarded by any of its relations' hard conditions, applied when none is broken and one gains.
            const bad = reports.find((x) => x.verdict.why)?.verdict ?? null
            const applied = !bad && reports.some((x) => x.verdict.applied)
            const posture0 = postureOf(cur.per[0])
            const deepOk = reports.every((x) => deepHolds(x.ka, x.inside))
            const cand: AlignCandidate = { applied, deepOk, clearOk,
              axisMm: Math.max(...reports.map((x) => (x.ka ? keyWorstMm(x.ka, x.inside) : Infinity))),
              depthMm: Math.min(...reports.map((x) => (x.ka ? x.ka.deep.depthMm : -Infinity))) }
            const rootAngle = solveRoot && applied && run.state.root
              ? { pitchDeg: deg(run.state.root.pitchDeg), yawDeg: deg(run.state.root.yawDeg) } : null
            const view = (c: ClearRow): ClearView => ({ with: c.name, startMm: c.startM * 1000, allowMm: c.allowM * 1000,
              afterMm: c.afterM * 1000, worst: c.worst })
            const collide = bad?.collide ? view(bad.collide) : null
            const rows: RelationAlign[] = group.map((hit, gi) => {
              const { kb, ka, inside } = reports[gi]
              const before = rep(p0.per[gi]), after = rep(cur.per[gi])
              const posture = gi === 0 ? posture0 : null
              // THE RENDERED ROOT decides 'root_inside': a visible root inside the opening on a rendered frame is red,
              // with its reason; one outside on every rendered frame is not, whatever the isolated samples say.
              const rootIn = inside && (rendered[gi]?.after.visMm ?? -Infinity) > 0
              const reasons = keyReasons(ka, hitsNow, inside, kb).filter((x) => x !== 'root_inside' || !rendered[gi])
              if (rootIn && !reasons.includes('root_inside')) reasons.push('root_inside')
              const lamp = lampOf(ka, reasons, inside)
              const v = reports[gi].verdict
              const insideCount = (smps: readonly AlignSample[]) => smps.filter((x) =>
                (x.tip[0] - x.o[0]) * x.u[0] + (x.tip[1] - x.o[1]) * x.u[1] + (x.tip[2] - x.o[2]) * x.u[2] > 0).length
              return { by: figs[hit.e].letter, of: figs[hit.r].letter, channel: hit.channel, target: hit.target, part: figs[hit.e].role,
                key: relKey(hit), moved: mr, mover: moverKind, alternative: false, tried: [moverKind],
                applied, discard: bad?.why ?? null, collide, unchanged: !applied && !bad, notes: v.notes,
                rootPull: inside ? { mm: pulledM * 1000, stuck: rootIn ? stuck : null, solvedVisMm, solvedAxisMm } : null,
                clear: clearRows.map(view),
                bucket: alignBucket(kb, ka, inside, { applied, why: bad?.why ?? null },
                  { stuck: rootIn && !!stuck, capUnmet: hitsNow.length > 0 && !deepHolds(ka, inside) }),
                root: solveRoot ? 'solved' : turnsRoot ? 'kept' : 'none',
                reasons,
                tipInside: { before: insideCount(p0.per[gi]), after: insideCount(cur.per[gi]), frames: cur.per[gi].length },
                postureBefore: gi === 0 ? postureOf(p0.per[gi]) : null, posture,
                limitReason: lamp !== 'green' && posture?.limited ? 'posture' : null, shiftCm, turnDeg, support,
                before, after, overlapBeforeMm: p0.overlap * 1000, overlapAfterMm: cur.overlap * 1000,
                clearWorst: cur.worst, clearLamp: clearLamp(cur.overlap * 1000), lampBefore: keyLamp(kb, [], inside), lamp,
                keys: { before: kb, after: ka },
                bend: bendReadout(cur.per[gi].map((x) => bendOf(x, bendLim))), rendered: rendered[gi] }
            })
            const moverRow: MoverAlign = { role: mr, letter: moving.letter, mover: moverKind, applied, shiftCm, turnDeg, adjustCm,
              adjustDeg, rangeCm, turnRangeDeg: cap.angleDeg, lamp: hitsNow.length ? 'red' : 'green', hits: hitsNow, rootAngle, rootBefore: solveRoot ? root0 : null,
              passes: run.trace, converged: run.converged }
            return { rows, moverRow, draft: cur.draft, applied, solvedRoot: solveRoot && applied, pivot: applied ? cur.per : p0.per, cand,
              blocked: alignBlocked({ applied, postureLimited: !!posture0?.limited, hits: hitsNow, deepOk, stuck: !!stuck }) }
          }
          // The groups: one per relation, one after the other (a click, "Align all"), each with the role its choice
          // names — 'auto' tries the part's carrier first and the receiving role when that run is blocked; without
          // either, one group per part figure moved by it (end clips).
          const sequential = !!only || !!opts.each
          const groups: { group: Hit[]; choice: AlignMover | 'auto' }[] = sequential
            ? hits.map((h) => ({ group: [h], choice: (only ? opts.mover : opts.moverOf?.[relKey(h)] ?? opts.mover) ?? 'auto' }))
            : [...alignMovers(hits).values()].map((g) => ({ group: g, choice: 'part' as const }))
          let rootSolved = false
          let cur0 = base
          const rows: RelationAlign[] = []
          const moverRows: MoverAlign[] = []
          // The aligned samples of every relation, for the contact pivot (`pairPivotCm`).
          const pivotRels: AlignSample[][] = []
          for (const { group, choice } of groups) {
            const kind: AlignMover = choice === 'auto' ? 'part' : choice
            const moverOf = (k: AlignMover) => (k === 'receiver' ? group[0].r : group[0].e)
            const first = runGroup(group, moverOf(kind), kind, cur0, !rootSolved)
            if (typeof first === 'string') return { ok: false, reason: first }
            let pick = first
            if (choice === 'auto' && first.blocked) {
              // THE AUTOMATIC ALTERNATIVE: the same relation with the receiving role moving, from the same start.
              const second = runGroup(group, moverOf('receiver'), 'receiver', cur0, !rootSolved)
              if (typeof second !== 'string') {
                const better = compareCandidates(second.cand, first.cand) < 0
                pick = better ? second : first
                for (const r of pick.rows) { r.tried = ['part', 'receiver']; r.alternative = better }
              }
            }
            rows.push(...pick.rows)
            moverRows.push(pick.moverRow)
            pivotRels.push(...pick.pivot)
            if (pick.applied) { cur0 = pick.draft; if (pick.solvedRoot) rootSolved = true }
          }
          resetAll()
          runAt(timeRef.current, draftRef.current, false)
          const roleShiftCm: Record<string, [number, number, number]> = {}
          for (const [r, v] of Object.entries(cur0.roleShiftM)) roleShiftCm[r] = [cm(v[0]), cm(v[1]), cm(v[2])]
          const roleTurnDeg: Record<string, [number, number, number]> = {}
          for (const [r, v] of Object.entries(cur0.roleTurnDeg ?? {})) roleTurnDeg[r] = [deg(v[0]), deg(v[1]), deg(v[2])]
          // The pivot in the clip frame of the receiving figure's place anchor (every role of a clip shares it).
          const recv = figs[hits[0].r]
          const pivotCm = pairPivotCm(pivotRels, recv.anchor, recv.placeYaw)
          const rootAngle = moverRows.find((m) => m.applied && m.rootAngle)?.rootAngle ?? null
          // The other contacts whose part the one root angle turns as well (only a one-relation click can surprise there).
          const rootShared = only && rootAngle ? all.filter((h) => !hits.includes(h) && rootTurns(figs[h.e].role)).map(relLabel) : []
          return { ok: true, ...rows[0], relations: rows, roleShiftCm, roleTurnDeg, movers: moverRows, rootAngle, rootShared, pivotCm,
            applied: moverRows.some((m) => m.applied) }
        }
        // ── Ruling A212: the base clip's last frame, for the end clips' join. ──
        const endPose = (): EndPose | null => {
          if (solo || figs.length < 2) return null
          const time = Math.max(0, duration - step)
          runAt(time, draftRef.current, false)
          const rel: Record<string, [number, number, number]> = {}
          for (const f of figs) for (const g of figs) {
            if (f !== g) rel[`${f.role}|${g.role}`] = relativeOf(placed.get(g)!.frame, hipsStage(f), hipsStage(g))
          }
          runAt(timeRef.current, draftRef.current, false)
          return { kind, rel }
        }
        // Only a mount of THIS clip's scene answers for it — the previous clip's scene is remounted under the new kind
        // until the new scene comes (or for good, when no prop fits) — and a mount without figures never replaces the
        // no-place answer of the same clip ("Align all" waited for both in vain).
        const noPlaceRun = autoAlignOut.current?.current
        if (autoAlignOut.current && scene?.for.startsWith(`${kind}|`) && !(figs.length === 0 && noPlaceRun?.noPlace && noPlaceRun.kind === kind && (noPlaceRun.set ?? '') === (set ?? '')))
          autoAlignOut.current.current = Object.assign(autoAlign, { kind, set, figures: figs.length, endPose,
            cast: castOf(assignRef.current) })
        disposers.push(() => { if (autoAlignOut.current?.current === autoAlign) autoAlignOut.current.current = null })
        tick()
      } catch (e) {
        setStatus(String(e))
      }
    })()
    return () => {
      disposed = true
      cancelAnimationFrame(raf)
      onReadoutRef.current?.(null)
      disposers.forEach((d) => d())
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scene, assignKey, kind, set, bust, height, yawOffset, t])

  const nAssigned = assigned.length
  const typeLabel = (ty: string) => TYPE_LABEL[ty] ? t(TYPE_LABEL[ty]) : ty
  const fillText = (count: number, reason: FillReason) => {
    const want = wantType ? typeLabel(wantType) : ''
    switch (reason) {
      case '': return t('Filled {n} places.').replace('{n}', String(count))
      case 'loading': return t('Characters are still loading — try again in a moment.')
      case 'no_places': return t('This choice has no places — pick a prop or Ground (no prop).')
      case 'no_type': return t('No {type} place here — pick a prop under “{type}”.').split('{type}').join(want)
      case 'too_few_slots': return t('No {type} place with {n} slots for this pair or group — pick a prop with a wider place.')
        .replace('{type}', want || t('fitting')).replace('{n}', String(roleList.length))
    }
  }
  const variants = props?.find((p) => p.id === propId)?.variant_tiers || []
  const readout = new Map((info?.figures || []).map((f) => [f.letter, f]))
  const fmt = (v: number, d = 1) => `${v >= 0 ? '+' : ''}${v.toFixed(d)}`

  return (
    <div style={{ border: '1px solid var(--border, #30363d)', borderRadius: 4, padding: 6 }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 12, marginBottom: 4, flexWrap: 'wrap' }}>
        <strong>{t('Places')}</strong>
        <label title={t('Props with places; the scene comes from the server like in the game.')}>
          {t('Prop')}{' '}
          <select value={propId} onChange={(e) => { setPropId(e.target.value); setVariant(0); setFillNote(null) }}
            style={{ maxWidth: 220 }} data-testid="place-prop">
            {groundOk ? (
              <optgroup label={t('No prop')}>
                <option value={GROUND_PROP}>{t('Ground (no prop)')}</option>
              </optgroup>
            ) : null}
            {nothingFits ? <option value="">{t('— none fits —')}</option> : null}
            {propGroups.map((g) => (
              <optgroup key={g.type || '-'} label={g.type ? `${typeLabel(g.type)}${g.type === wantType ? ` — ${t('this clip')}` : ''}`
                : t('Other')}>
                {g.props.map((p) => <option key={`${g.type}/${p.id}`} value={p.id}>{p.label}</option>)}
              </optgroup>
            ))}
          </select>
        </label>
        {isGround && solo ? (
          <label title={t('Figures on the bare floor in one row, as a room’s floor place seats them: 0.6 m apart, across the facing.')}>
            {t('Figures')}{' '}
            <select value={groundCount} onChange={(e) => { setGroundCount(Number(e.target.value)); setFillNote(null) }}>
              {Array.from({ length: GROUND_MAX }, (_v, i) => <option key={i} value={i + 1}>{i + 1}</option>)}
            </select>
          </label>
        ) : null}
        {variants.length > 1 ? (
          <label>
            {t('Variant')}{' '}
            <select value={variant} onChange={(e) => setVariant(Number(e.target.value))}>
              {variants.map((_v, i) => <option key={i} value={i}>{`v${i + 1}`}</option>)}
            </select>
          </label>
        ) : null}
        <button type="button" className="ga-btn ga-btn-sm" onClick={() => setPaused((p) => !p)}>
          {paused ? t('▶ Play') : t('⏸ Pause')}
        </button>
        {[0.2, 0.5, 1].map((s) => (
          <button key={s} type="button" className={`ga-btn ga-btn-sm${speed === s ? ' ga-btn-primary' : ''}`}
            onClick={() => setSpeed(s)}>{`${s}×`}</button>
        ))}
        <button type="button" className="ga-btn ga-btn-sm" onClick={() => fill(true)}
          title={t('Every place this clip fits gets a figure (at most 6).')}>{t('Fill all with this clip')}</button>
        {!solo ? (
          <button type="button" className="ga-btn ga-btn-sm" data-testid="place-measure-profile"
            disabled={paused || measure?.phase === 'armed' || measure?.phase === 'measuring' || measure?.phase === 'saving'}
            title={t('Plays one whole clip cycle and stores in the clip, per channel, the largest share of the entering part inside and how many times it reached the bottom. The server estimates the readouts of a running scene from it when no 3D client shows that scene.')}
            onClick={() => { measureClip.current = `${kind}|${set.trim()}`; measureRef.current = 'armed'; setMeasure({ phase: 'armed', note: '' }) }}>
            {t('Measure channel profile')}
          </button>
        ) : null}
        {measure ? (
          <span role="status" data-testid="place-measure-note" className="ga-hint"
            style={measure.phase === 'error' ? { color: 'var(--danger, #f85149)' } : measure.phase === 'done' ? { color: '#3fb950' } : undefined}>
            {measure.phase === 'armed' || measure.phase === 'measuring' ? t('Measuring one clip cycle…')
              : measure.phase === 'saving' ? t('Storing the channel profile…') : measure.note}
          </span>
        ) : null}
        {goneNote.length ? (
          <span role="status" data-testid="place-gone-note" className="ga-hint" style={{ color: 'var(--warning, #d29922)' }}>
            {t('Remembered {names} no longer exists; the default fill took the place.').replace('{names}', goneNote.join(', '))}
          </span>
        ) : null}
        {fillNote ? (
          <span role="status" data-testid="place-fill-note" className="ga-hint"
            style={fillNote.count ? { color: '#3fb950' } : { color: 'var(--danger, #f85149)' }}>
            {fillText(fillNote.count, fillNote.reason)}
          </span>
        ) : null}
        {info ? (
          <span style={{ marginLeft: 'auto', opacity: 0.8 }}
            title={t('Phase B of the two-phase frame: secondary motion and strand hair. Strand hair runs for the 2 figures nearest the camera.')}>
            {t('{n} strand hair').replace('{n}', String(info.strands))} · {t('{n} on chains').replace('{n}', String(info.chains))}
            {' · '}{t('hair swing {mm} mm').replace('{mm}', info.swingMm.toFixed(0))}
            {' · '}{info.ms.toFixed(1)} ms
          </span>
        ) : null}
      </div>
      {nothingFits ? (
        <div role="status" data-testid="place-none-fits" className="ga-hint"
          style={{ color: 'var(--danger, #f85149)', marginBottom: 4 }}>
          {t('No prop has a {type} place with at least {n} slots, so this clip cannot be shown on a place. Such a prop must exist first — add a {type} place with that capacity to a prop in the Props tab.')
            .split('{type}').join(wantType ? typeLabel(wantType) : t('fitting')).replace('{n}', String(roles < 2 ? 1 : roles))}
        </div>
      ) : null}
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) 300px', gap: 8 }}>
        <div>
          <div className="ga-viewer-toggles" data-testid="place-toggles" style={{ display: 'flex', gap: 4, marginBottom: 4 }}>
            {([
              ['collision', '◎', t('Collision'), t('Draw each figure’s collision capsules as other figures engage them; overlapping pairs of two figures turn red.')],
              ['channels', '⊙', t('Channels'), t('Draw each figure’s channels; a ring at the mouth while a partner’s chain opens it.')],
              ['seeThrough', '◐', t('Partner see-through (attached part stays)'), t('Every mesh of the entering figure — body, hair, clothing, teeth — turns see-through; its attached part stays as it is. Preview only, nothing is stored.')],
            ] as const).map(([k, glyph, label, tip]) => (
              <button key={k} type="button" className="ga-btn ga-btn-sm" data-testid={`place-toggle-${k}`} aria-pressed={show[k]}
                aria-label={label} title={`${label} — ${tip}`} onClick={() => toggleShow(k)}>{glyph}</button>
            ))}
          </div>
          <div ref={hostRef} data-testid="place-preview" style={{ position: 'relative', height, background: 'var(--surface-2, #161b22)' }}>
            {status ? <div style={{ position: 'absolute', inset: 8, fontSize: 12, opacity: 0.8 }}>{status}</div> : null}
            {roleIssues.length || swapNote ? (
              <div data-testid="place-role-needs" style={{ position: 'absolute', left: 8, top: 8, maxWidth: '60%', fontSize: 12,
                background: 'rgba(13,17,23,0.85)', border: '1px solid var(--warning, #d29922)', borderRadius: 4, padding: '2px 6px' }}>
                {swapNote ? <div>{swapNote}</div> : null}
                {roleIssues.map((x) => <div key={x} style={{ color: 'var(--warning, #d29922)' }}>⚠ {x}</div>)}
              </div>
            ) : null}
          </div>
          {!solo ? (
            <div data-testid="place-readout-row" className="ga-hint" style={{ fontSize: 11, fontVariantNumeric: 'tabular-nums', minHeight: 16 }}
              title={t('Always shown on a pair: each engaged channel’s depth and stretch now, and each mouth’s opening value with whether its opening was built.')}>
              {info?.partners ? (
                <>
                  {info.partners.engaged.length ? info.partners.engaged.map((g, i) => (
                    <span key={`e${i}`} style={{ marginRight: 10 }}>
                      {t('{by} → {of} {channel}: in {cm} cm · stretch {mm} mm ({pct} %)')
                        .replace('{by}', g.by).replace('{of}', g.of).replace('{channel}', g.channel.split(':').pop() || g.channel)
                        .replace('{cm}', g.readout ? (g.readout.insertionM * 100).toFixed(1) : '–')
                        .replace('{mm}', g.readout ? (g.readout.stretchM * 1000).toFixed(1) : '–')
                        .replace('{pct}', g.readout ? (g.readout.stretchRatio * 100).toFixed(0) : '–')}
                    </span>
                  )) : <span style={{ marginRight: 10 }}>{t('No channel engaged.')}</span>}
                  {info.partners.mouths.map((m) => (
                    <span key={`m${m.letter}`} style={{ marginRight: 10 }} data-testid="place-mouth-readout">
                      {t('Mouth {p}: open {v}').replace('{p}', m.letter).replace('{v}', m.open === null ? '–' : m.open.toFixed(2))}
                      {' · '}
                      {m.built
                        ? t('opening built ({h} mm)').replace('{h}', ((m.teethGapMm ?? m.openHeightMm) ?? 0).toFixed(1))
                        : <span style={{ color: 'var(--warning, #d29922)' }}>{t('opening not built (no opening height: run the mouth build)')}</span>}
                    </span>
                  ))}
                </>
              ) : t('Measuring…')}
            </div>
          ) : null}
          <ModelTurnHint />
          <div className="ga-hint">{t('Figures 1.70 m, yellow post 1.70 m, grid 0.5 m · dashed = place facing, arrow = body facing.')}</div>
        </div>
        <div style={{ fontSize: 12, minWidth: 0, overflow: 'hidden' }}>
          {pose ? (
            <div className="ga-hint" style={{ marginBottom: 4 }}
              title={t('The pose’s yaw offset turns a pair or group on its place in the game. It is edited in Entries.')}>
              {t('Pose {key}: yaw offset {deg}°').replace('{key}', pose.key).replace('{deg}', String(yawOffset))}{' '}
              {onOpenPose ? (
                <button type="button" className="ga-btn ga-btn-sm" onClick={() => onOpenPose(pose.key)}>{t('Open entry →')}</button>
              ) : null}
            </div>
          ) : null}
          <table style={{ width: '100%', borderCollapse: 'collapse', tableLayout: 'fixed' }}>
            <colgroup><col style={{ width: 60 }} /><col /><col style={{ width: 52 }} /><col style={{ width: 70 }} /></colgroup>
            <thead>
              <tr style={{ textAlign: 'left', opacity: 0.7, whiteSpace: 'nowrap' }}>
                <th />
                <th>{t('Character')}</th>
                <th title={t('Body facing against the place facing, degrees (loop median).')}>{t('Δ turn')}</th>
                <th title={t('Hips against the place point, cm (loop median).')}>{t('Δ pos')}</th>
              </tr>
            </thead>
            <tbody>
              {places.map((p) => {
                const a = assign[p.letter]
                const r = readout.get(p.letter)
                const full = !a?.character && nAssigned >= MAX_FIGURES
                const body = a?.character && a.character !== MANNEQUIN
                return (
                  <Fragment key={p.letter}>
                  <tr style={{ borderTop: '1px solid var(--border, #30363d)' }}>
                    <td style={{ overflow: 'hidden', whiteSpace: 'nowrap' }} title={`${p.marker.group}${p.marker.label ? ` · ${p.marker.label}` : ''} · ${t('facing')} ${p.facing}°`}>
                      <strong>{p.letter}</strong> <span style={{ opacity: 0.7 }}>{p.marker.group}</span>
                    </td>
                    <td style={{ display: 'flex', gap: 2, minWidth: 0 }}>
                      <select value={a?.character || ''} disabled={full} style={{ flex: 1, minWidth: 0 }}
                        title={full ? t('At most 6 figures.') : t('A character without an outfit model can still show its base body.')}
                        onChange={(e) => {
                          const v = e.target.value
                          setAssign((cur) => {
                            const next = { ...cur }
                            if (!v) delete next[p.letter]
                            else next[p.letter] = { character: v, role: cur[p.letter]?.role ?? (solo ? '' : roleList[p.slot % roleList.length]),
                              body: defaultBody(plain[v], v === MANNEQUIN), poses: {} }
                            return next
                          })
                        }}>
                        <option value="">{t('— empty')}</option>
                        <option value={MANNEQUIN}>{t('1.70 m mannequin')}</option>
                        {(chars ?? []).map((c) => (
                          <option key={c.name} value={c.name}>
                            {c.built ? c.name : `${c.name} — ${t('no outfit model yet')}`}
                          </option>
                        ))}
                      </select>
                      {!solo && a?.character ? (
                        <select value={a.role} style={{ flex: '0 0 auto' }} title={t('Which half of the clip this figure plays.')}
                          onChange={(e) => setAssign((cur) => ({ ...cur, [p.letter]: { ...cur[p.letter], role: e.target.value } }))}>
                          {roleList.map((r) => <option key={r} value={r}>{`(${r})`}</option>)}
                        </select>
                      ) : null}
                    </td>
                    <td style={{ whiteSpace: 'nowrap', overflow: 'hidden', textAlign: 'right' }} title={r ? `${t('now')} ${fmt(r.dyaw)}°` : ''}>
                      {r ? `${fmt(r.medYaw)}°` : ''}
                    </td>
                    <td style={{ whiteSpace: 'nowrap', overflow: 'hidden', textAlign: 'right' }} title={r ? `${t('now')} ${r.dpos.toFixed(1)} cm` : ''}>
                      {r ? (
                        <>
                          {`${r.medPos.toFixed(1)} cm `}
                          <span style={{ display: 'inline-block', width: 9, height: 9, borderRadius: 5,
                            background: r.lamp ? LAMP_COLOR[r.lamp] : '#8b949e' }}
                            title={r.lamp ? t('Loop median: green ≤ 3° and 2 cm, yellow ≤ 10° and 6 cm, else red.')
                              : t('Measuring — the lamp shows after one full loop.')} />
                        </>
                      ) : null}
                    </td>
                  </tr>
                  {body ? (
                    <tr>
                      <td />
                      <td colSpan={3} style={{ paddingBottom: 3 }}>
                        <BodyPick a={a} outfitBuilt={!!chars?.find((c) => c.name === a.character)?.built}
                          base={plain[a.character]} onChange={(patch) => setAssign((cur) => ({ ...cur, [p.letter]: { ...cur[p.letter], ...patch } }))} />
                      </td>
                    </tr>
                  ) : null}
                  </Fragment>
                )
              })}
            </tbody>
          </table>
          {!places.length && propId && !isGround ? <div className="ga-hint">{t('This prop has no places.')}</div> : null}
          {(show.collision || show.channels) && info?.partners ? (
            <div style={{ marginTop: 6, borderTop: '1px solid var(--border, #30363d)', paddingTop: 4 }} data-testid="place-partners">
              {show.collision ? (
                <div title={t('Closest capsule pair of two figures: positive = they overlap by that much, negative = the gap.')}>
                  {info.partners.closest ? (
                    <>
                      <span style={{ display: 'inline-block', width: 9, height: 9, borderRadius: 5, marginRight: 4,
                        background: info.partners.closest.mm > 0 ? '#f85149' : '#3fb950' }} />
                      {t('Closest pair {a} {capA} ↔ {b} {capB}: {mm} mm')
                        .replace('{a}', info.partners.closest.a).replace('{capA}', info.partners.closest.capA)
                        .replace('{b}', info.partners.closest.b).replace('{capB}', info.partners.closest.capB)
                        .replace('{mm}', `${info.partners.closest.mm > 0 ? '+' : ''}${info.partners.closest.mm.toFixed(1)}`)}
                      {' · '}{t('{n} overlapping').replace('{n}', String(info.partners.contacts))}
                    </>
                  ) : t('Fewer than two figures with collision capsules.')}
                </div>
              ) : null}
              {show.channels ? (
                <div title={t('A chain of one figure engaged in another figure’s channel: its weight w and the radius the channel opens to.')}>
                  {info.partners.engaged.length ? info.partners.engaged.map((g, i) => (
                    <div key={i}>
                      {t('{by} → {of} {channel}: w {w}, opening {mm}')
                        .replace('{by}', g.by).replace('{of}', g.of).replace('{channel}', g.channel)
                        .replace('{w}', g.w.toFixed(2))
                        .replace('{mm}', g.openingMm === null ? t('pending') : `${g.openingMm.toFixed(1)} mm`)}
                      {g.readout ? (
                        <div className="ga-hint" style={{ fontSize: 10, margin: '0 0 0 10px', fontVariantNumeric: 'tabular-nums' }}
                          data-testid="place-channel-readout"
                          title={t('Now: how far the part’s front is past the opening (in % of the channel’s depth and of the part’s own length inside), how much wider than its rest radius {r} mm the part holds the channel (radius, in % of it) and the depth scale k (1 = not compressed).')
                            .replace('{r}', (g.readout.restRadiusM * 1000).toFixed(1))}>
                          {t('In {cm} cm ({depth} % of the channel, {part} % of the part) · stretch {mm} mm ({pct} %) · k {k}')
                            .replace('{cm}', (g.readout.insertionM * 100).toFixed(1))
                            .replace('{depth}', (g.readout.insertionOfDepth * 100).toFixed(0))
                            .replace('{part}', (g.readout.insertionOfLength * 100).toFixed(0))
                            .replace('{mm}', (g.readout.stretchM * 1000).toFixed(1))
                            .replace('{pct}', (g.readout.stretchRatio * 100).toFixed(0))
                            .replace('{k}', g.readout.compressK.toFixed(2))}
                          {g.max ? (
                            <div title={g.full ? t('The largest values over the last whole loop of the clip (k: the smallest).')
                              : t('The largest values since this loop began; after one whole loop the line shows that loop’s.')}>
                              {(g.full ? t('Loop max: in {cm} cm ({depth} %) · stretch {mm} mm ({pct} %) · k {k}')
                                : t('Max so far: in {cm} cm ({depth} %) · stretch {mm} mm ({pct} %) · k {k}'))
                                .replace('{cm}', (g.max.insertionM * 100).toFixed(1))
                                .replace('{depth}', (g.max.insertionOfDepth * 100).toFixed(0))
                                .replace('{mm}', (g.max.stretchM * 1000).toFixed(1))
                                .replace('{pct}', (g.max.stretchRatio * 100).toFixed(0))
                                .replace('{k}', g.max.compressK.toFixed(2))}
                            </div>
                          ) : null}
                        </div>
                      ) : null}
                    </div>
                  )) : (info.partners.channels
                    ? t('Channels: {n}, none engaged.').replace('{n}', String(info.partners.channels))
                    : t('No figure carries a channel.'))}
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  )
}
