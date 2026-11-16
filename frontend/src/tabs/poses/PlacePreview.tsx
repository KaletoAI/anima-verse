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
 * * Toggles "Collision" and "Channels" (phase 3, off by default, remembered per browser user in localStorage) only
 *   change what is DRAWN and printed — the sim always runs them, as in the game: each figure's capsules as other
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
  bindRelativeClip, calibratedRoot, capsuleWireframe, channelWireframe, clipCalibration,
  installSkinnedNormalCorrection, median, pairYaw, pickModelVariant, placeCapsuleWireframe, placeChannelWireframe,
  placeModelSpec, restCorrections, restPoseOf, strandCandidates,
  type AlignmentDraft, type ChannelNow, type FrameInspection, type AlignmentLamp, type ClipHeightOffsetsCm, type CollisionPayload, type FigureRuntime,
  type HairStrandRecord, type SceneMarker, type SceneModelSpec, type SecondaryMotionPayload,
  contactLamp, contactReport, solveContactShift, solvePairFix, fixRoot, fixPivot, partnerTurnFix, turnAxes,
  fixAnglesDeg, ALIGN_FIT, NO_FIX, RUNTIME_FIT, createPairFit, pairFitObserve, pairFitTotal, findContact, contactSampleOf,
  type PairFitState, pairInterpenetration, clearLamp, PART_REGIONS, type ClearLamp,
  type ContactLamp, type ContactReport, type FitSample, type PairFix,
} from '@anima/scene-render'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPost } from '../../lib/api'
import { loadCharacters } from '../../lib/refs'
import { loadTestFigure, standHipsRef } from '../characters/Model3DViewer'
import { rootAt, rootPath, ROLE_COLOR, type RootPath } from './ClipPreview'
import { ModelTurnHint } from '../../components/ModelTurnHint'
import { attachModelTurn, configureViewControls, poseMatrix } from '../../lib/modelTurn'
import { mountPlaceFigure, placeInteraction, placePhaseB } from './placeFigures'
import { GROUND_MAX, GROUND_PROP, fittingProps, groundFits, groundRoom, groupProps, planFill, preselectProp, type FillReason } from './placePicker'
import { stateMotionUrl, statePicker, type PreviewStateChoice } from '../characters/baseBodyModel'

export const MANNEQUIN = '__mannequin__'
/** D5: figures in the preview, and how many of them run strand hair. */
export const MAX_FIGURES = 6
const STRAND_FIGURES = 2
const LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'

interface ModelAnswer {
  model?: {
    url?: string; collision?: CollisionPayload | null
    hair_strands?: { url?: string; sha256?: string } | null
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
  height_offsets_cm?: ClipHeightOffsetsCm
  orientation?: { shift_cm?: [number, number] | null; partner_turn_deg?: [number, number] | null } | null
}
/** A pose that plays this clip (read-only here, D2). */
export interface PlacePose { key: string; yaw_offset?: number; group?: string }

/** One place letter: a slot of a marker of the prop. */
interface PlaceRow {
  letter: string; marker: SceneMarker; slot: number
  point: [number, number]; facing: number; rootY: number
}
/** A figure on a place: who, which half of the clip, which body (Ruling A110b: the plain base body or the outfit
 *  body the game shows) and, on the base body, the previewed state ('' = at rest). */
interface Assignment { character: string; role: string; body: 'outfit' | 'base'; state: string }

/** A character's plain base body as GET …/figure?plain=1 reports it (`plain_body`) — the Base body tab's source. */
interface PlainInfo {
  url: string; collision: CollisionPayload | null; motion?: SecondaryMotionPayload
  groupCount: number; states: PreviewStateChoice[]
}
interface PlainAnswer {
  plain_body?: {
    model?: { url?: string; status?: string; collision?: CollisionPayload | null } | null
    extension?: { groups?: unknown[]; motion?: SecondaryMotionPayload; states?: PreviewStateChoice[] } | null
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
          groupCount: ext?.groups?.length ?? 0, states: ext?.states ?? [] } : null }))
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

/** The partner overlays (phase 3): what is drawn, never what runs. */
export interface PartnerShow { collision: boolean; channels: boolean
  /** Ruling A129.3: the per-pair fine fit runs (default on) — what the game does when a pair interaction starts. */
  fit: boolean
  /** Ruling A129.4: per frame the entering figure's pelvis follows so the tip stays on the channel axis (default on). */
  follow: boolean
  /** Ruling A129.7: the camera follows the contact point, and an inset shows the channel axis and the shaft. */
  focus: boolean }
const SHOW_KEY = 'anima.placePreview.show'
function loadShow(): PartnerShow {
  try {
    const v = JSON.parse(localStorage.getItem(SHOW_KEY) || '{}') as Partial<PartnerShow>
    return { collision: !!v.collision, channels: !!v.channels, fit: v.fit !== false, follow: v.follow !== false,
      focus: !!v.focus }
  } catch { return { collision: false, channels: false, fit: true, follow: true, focus: false } }
}
/** Capsules of two figures that overlap; a channel occupied by a partner chain. */
const CONTACT_COLOR = 0xff2d2d
const OPENING_COLOR = 0x3fb950

/** Ruling A129.3: the runtime fine fit of the pair shown — live, or stepped at 60 fps by `pairCheck`. */
export interface PairFitReadout {
  phase: 'collect' | 'fitted'; by: string; of: string
  shiftMm: [number, number, number]; turnDeg: [number, number]
  /** Lateral of the tip from the channel axis while inside (s ≥ 0), over the fitted frames (mm). */
  lateralMaxMm: number; lateralMedMm: number; frames: number
}
/** `pairCheck`: the pair shown over whole loops at 60 fps — the clip as stored + draft, then with the fine fit. */
export type PairCheckResult =
  | { ok: false; reason: string }
  | { ok: true; by: string; of: string; before: ContactReport; after: ContactReport; fit: PairFitReadout
      /** Ruling A129.5: the deepest interpenetration besides the channel (mm) over each run's frames, and its pair. */
      clearMm: [number, number, number]; clearWorst: string
      /** Ruling A129.4: the same with the per-frame follow on top of the fit. */
      followed: ContactReport; followFit: PairFitReadout }

/** The printed partner readout (names = place letters). */
interface PartnerInfo {
  closest: { a: string; b: string; capA: string; capB: string; mm: number } | null
  contacts: number
  channels: number
  engaged: { by: string; of: string; channel: string; w: number; openingMm: number | null }[]
}

/** The pose catalog's place types as the picker names them. */
const TYPE_LABEL: Record<string, string> = { stand: 'Stand', seat: 'Seat', ground: 'Ground', lie: 'Lie' }

/** Body and state of one figure (Ruling A110b): outfit body (GET …/model3d, the game's figure) or the plain base body
 *  (GET …/figure?plain=1) — a variant that is not built is greyed with the step that builds it; the state picker is
 *  the Base body tab's (`statePicker`: None (at rest) + each state that moves one of the base model's extension
 *  groups, motion from GET …/base-body/state-motion). */
function BodyPick({ a, outfitBuilt, base, onChange }: {
  a: Assignment; outfitBuilt: boolean; base: PlainInfo | null | undefined
  onChange: (patch: Partial<Assignment>) => void
}) {
  const { t } = useI18n()
  const picker = base ? statePicker(base.groupCount, base.states, t) : null
  const stateTitle = a.body !== 'base' ? t('States are previewed on the base body, as in the Base body tab.')
    : base === undefined ? t('Loading…') : !base ? t('No base model yet (Characters → Base body).') : picker?.note || ''
  const missing = a.body === 'base' ? (base === null ? t('no base model yet (Characters → Base body)') : '')
    : outfitBuilt ? '' : t('no outfit model yet (Characters → Figure)')
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 2, alignItems: 'center', minWidth: 0 }}>
      <select value={a.body} data-testid="place-body" style={{ flex: '1 1 0', minWidth: 0 }} title={t('Base body = the plain body; outfit body = the figure the game shows, with what the character wears.')}
        onChange={(e) => onChange({ body: e.target.value as Assignment['body'], state: '' })}>
        <option value="outfit" disabled={!outfitBuilt}>{outfitBuilt ? t('Outfit body') : `${t('Outfit body')} — ${t('not built')}`}</option>
        <option value="base" disabled={base === null}>{base === null ? `${t('Base body')} — ${t('not built')}` : t('Base body')}</option>
      </select>
      <select value={a.body === 'base' ? a.state : ''} data-testid="place-state" title={stateTitle}
        disabled={a.body !== 'base' || !picker?.options.length} style={{ flex: '1 1 0', minWidth: 0 }}
        onChange={(e) => onChange({ state: e.target.value })}>
        {a.body === 'base' && picker?.options.length
          ? picker.options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)
          : <option value="">{t('None (at rest)')}</option>}
      </select>
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
 *  per place INDEX the person, body and state — restored on the new clip's places with that index. */
const placeMemory: { camera: { pos: [number, number, number]; target: [number, number, number] } | null
  byIndex: Record<number, { character: string; role: string; body: Assignment['body']; state: string }> } = {
  camera: null, byIndex: {} }

/** Ruling A126: the outcome of Auto-align (partner B against the channel the pair's attached part enters). */
export type AutoAlignResult =
  | { ok: false; reason: string }
  | { ok: true; by: string; of: string; channel: string; shiftCm: [number, number, number]
      /** Ruling A129: partner B's tilt/roll (degrees, saved + draft + solved, each within ±20°). */
      turnDeg: [number, number]
      /** Ruling A129.5: the deepest interpenetration besides what the channel allows, its pair and lamp. */
      clearWorst: string; clearLamp: ClearLamp
      before: ContactReport; after: ContactReport; afterShift: ContactReport; overlapBeforeMm: number; overlapAfterMm: number
      lampBefore: ContactLamp; lamp: ContactLamp }

/** The Auto-align of the scene that runs now, tagged with what it shows (A129.6: "Align all" waits for its clip). */
export type AutoAlignRun = (() => AutoAlignResult) & { kind?: string; set?: string; figures?: number }

export function PlacePreview({ kind, set = '', roles, clips, draftRef, draftSeq, bust = 0, poses, onOpenPose,
  onReadout, autoAlignRef, pairCheckRef, height = 360 }: {
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
  /** Set while a scene runs: the pair over whole loops at 60 fps, before and with the per-pair fine fit (A129.3). */
  pairCheckRef?: MutableRefObject<(() => PairCheckResult) | null>
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
  const [variant, setVariant] = useState(0)
  const [scene, setScene] = useState<{ models: SceneModelSpec[]; markers: SceneMarker[] } | null>(null)
  const [assign, setAssign] = useState<Record<string, Assignment>>({})
  const [status, setStatus] = useState('')
  const [paused, setPaused] = useState(false)
  const [speed, setSpeed] = useState(1)
  const [info, setInfo] = useState<{ ms: number; swingMm: number; strands: number; chains: number; figures: FigureReadout[]
    partners: PartnerInfo | null; fit: PairFitReadout | null } | null>(null)
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
  const pairCheckOut = useRef(pairCheckRef); pairCheckOut.current = pairCheckRef
  // The SAVED calibration per role, read live in the frame loop: after Apply the listing (new shift_cm / heights)
  // arrives after the clip reload, and the figures must take it the moment it does — never a stale copy.
  const savedRef = useRef<Record<string, { shiftCm: [number, number] | null; heightOffsetsCm: ClipHeightOffsetsCm | null
    partnerTurnDeg: [number, number] | null }>>({})
  {
    const want = set.trim()
    const out: typeof savedRef.current = {}
    for (const role of ['', 'a', 'b', 'c', 'd', 'e']) {
      const c = (want ? clips.find((x) => (x.role || '') === role && (x.set || '') === want) : undefined)
        || clips.find((x) => (x.role || '') === role && !x.set) || clips.find((x) => (x.role || '') === role)
      if (c) out[role] = { shiftCm: c.orientation?.shift_cm ?? null, heightOffsetsCm: c.height_offsets_cm ?? null,
        partnerTurnDeg: c.orientation?.partner_turn_deg ?? null }
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

  // ── its places from the server (the draft scene preview) ──
  useEffect(() => {
    if (!propId) { setScene(null); return }
    try { localStorage.setItem(memoKey(kind), JSON.stringify({ prop: propId, variant })) } catch { /* private mode */ }
    let off = false
    // The bare floor is one room marker (placePicker.groundRoom); a prop stands at the room centre.
    const room = propId === GROUND_PROP ? groundRoom(wantType, solo ? groundCount : roleList.length)
      : { id: 'place-preview', name: 'Preview',
        layout: { x: -3, y: -3, w: 6, d: 6, props: [{ id: 'p', prop_id: propId, at: [3, 3], yaw: 0, variant }] } }
    apiPost<{ models?: SceneModelSpec[]; markers?: SceneMarker[] }>('/play/scene-preview', { rooms: [room] })
      .then((payload) => {
        if (off) return
        setScene({ models: (payload.models || []).filter((m) => m.role === 'prop'), markers: payload.markers || [] })
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
  const fill = (all: boolean) => {
    const names = chars ? [...chars.filter((c) => c.built).map((c) => c.name), MANNEQUIN] : null
    const plan = planFill(places.map((p) => ({ letter: p.letter, markerId: p.marker.id, group: p.marker.group })),
      { names, want: wantType, roles: solo ? [''] : roleList, all, max: MAX_FIGURES })
    const next = { ...plan.assign }
    if (!all) {
      // A129.8: the persons, bodies and states picked on the last clip, per place index, where this clip has the place.
      const rl = solo ? [''] : roleList
      places.forEach((p, i) => {
        const m = placeMemory.byIndex[i]
        if (!m || !m.character) return
        const role = next[p.letter]?.role ?? (rl.includes(m.role) ? m.role : rl[i % rl.length])
        next[p.letter] = { character: m.character, role, body: m.body, state: m.state }
      })
    }
    setAssign(next)
    if (all) setFillNote({ count: plan.count, reason: plan.reason })
  }
  const filled = useRef('')
  useEffect(() => {
    const key = `${kind}|${propId}|${variant}|${places.length}|${chars ? 1 : 0}`
    if (!places.length || !chars || filled.current === key) return
    filled.current = key
    fill(false)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [places, chars, kind, propId, variant])

  // A129.8: remember what is shown, per place index.
  useEffect(() => {
    if (!places.length) return
    places.forEach((p, i) => {
      const a = assign[p.letter]
      if (a?.character) placeMemory.byIndex[i] = { character: a.character, role: a.role, body: a.body, state: a.state }
      else if (a) delete placeMemory.byIndex[i]
    })
  }, [assign, places])
  const assigned = places.filter((p) => assign[p.letter]?.character)
  const plain = usePlainBodies(places.map((p) => assign[p.letter]?.character || ''))
  // A base figure's model, motion and state are part of the scene's key: a state pick or a base body that arrives
  // rebuilds the scene with the right model.
  const [stateMotions, setStateMotions] = useState<Record<string, SecondaryMotionPayload | null>>({})
  useEffect(() => {
    for (const p of assigned) {
      const a = assign[p.letter]
      const k = `${a.character}|${a.state}`
      if (a.body !== 'base' || !a.state || k in stateMotions || !plain[a.character]) continue
      setStateMotions((cur) => ({ ...cur, [k]: null }))
      apiGet<{ motion: SecondaryMotionPayload }>(stateMotionUrl(a.character, a.state))
        .then((d) => setStateMotions((cur) => ({ ...cur, [k]: d.motion })))
        .catch(() => { /* the figure keeps the rest motion */ })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [assign, plain])
  const assignKey = JSON.stringify(assigned.map((p) => {
    const a = assign[p.letter]
    return [p.letter, a, a.body === 'base' ? [plain[a.character]?.url ?? '', !!stateMotions[`${a.character}|${a.state}`]] : 0]
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
        // Keyed by character + body + state: the outfit body is GET …/model3d (the game's figure), the base body
        // `plain_body.model` of GET …/figure?plain=1 with its rest motion or the picked state's (Base body tab).
        const modelKey = (a: Assignment) => a.character === MANNEQUIN ? MANNEQUIN
          : a.body === 'base' ? `${a.character}|base|${a.state}` : a.character
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
            const motion = (a.state ? stateMotions[`${name}|${a.state}`] : null) ?? base.motion
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
          saved: { shiftCm: [number, number] | null; heightOffsetsCm: ClipHeightOffsetsCm | null; partnerTurnDeg: [number, number] | null }
          anchor: { x: number; y: number; z: number }; placeYaw: number
          arrow: InstanceType<typeof THREE.ArrowHelper>; yawS: number[]; posS: number[]
          medYaw: number; medPos: number; dyaw: number; dpos: number; chains: number
          head: Object3D | null; tips: Object3D[]; tipRest: Map<Object3D, InstanceType<typeof THREE.Vector3>>
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
          const bound = rig ? bindRelativeClip(THREE, inplace, restCorrections(THREE, restPoseOf(THREE, rig), inst)) : inplace
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
          figs.push({ letter: p.letter, character: a.character, role: a.role, place: p, root, inst, mixer, path: clip.path,
            duration: clip.raw.duration, hips, hipsBind: { x: hb.x, y: hb.y, z: hb.z }, bindInv, runtime, hasRecord,
            saved: { shiftCm: o?.shift_cm ?? null, heightOffsetsCm: clip.file.height_offsets_cm ?? null,
              partnerTurnDeg: o?.partner_turn_deg ?? null },
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
        const drawPartners = (res: ReturnType<typeof placePhaseB>) => {
          const sh = showRef.current
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
          partnerInfo = {
            closest: best ? { a: letterOf(best.a), b: letterOf(best.b), capA: best.capA, capB: best.capB, mm: best.depth * 1000 } : null,
            contacts: frame.contacts.length, channels,
            engaged: frame.engagements.map((g) => ({ by: letterOf(g.by), of: letterOf(g.of), channel: g.channel, w: g.w,
              openingMm: g.opening === null ? null : g.opening * 1000 })),
          }
        }

        // ── Ruling A129: the root of a figure — the calibration (draft over saved), then partner B's turn (saved +
        // draft, renderer-only) and `extra` (a solve's trial fix) about the bind hips (`fixPivot`, stage space). ──
        const fixQ = new THREE.Quaternion()
        const placeRoot = (f: Fig, time: number, draft: AlignmentDraft, extra: PairFix = NO_FIX) => {
          const cal = clipCalibration(draft, savedRef.current[f.role] ?? f.saved, f.placeYaw, f.place.marker.group)
          const at = calibratedRoot(cal, { anchor: f.anchor, role: f.role, hips: rootAt(f.path, time), inPlace: solo,
            hipsBind: f.hipsBind, standRefM })
          f.root.position.set(at.x, at.y, at.z)
          f.root.rotation.set(cal.euler[0], cal.euler[1], cal.euler[2], 'YXZ')
          const pivot = fixPivot([at.x, at.y, at.z], cal.frame, [f.hipsBind.x, f.hipsBind.y, f.hipsBind.z])
          if (!solo) {
            const saved = f.role === 'b' ? (savedRef.current[f.role] ?? f.saved).partnerTurnDeg ?? [0, 0] : [0, 0]
            const turn = f.role === 'b' ? draft.partnerTurnDeg ?? [0, 0] : [0, 0]
            const base = partnerTurnFix(saved[0] + turn[0], saved[1] + turn[1], cal.frame)
            const fix: PairFix = { shift: extra.shift, turn: [base.turn[0] + extra.turn[0], base.turn[1] + extra.turn[1],
              base.turn[2] + extra.turn[2]] }
            if (fix.turn.some((v) => v) || fix.shift.some((v) => v)) {
              const r = fixRoot(fix, pivot, [at.x, at.y, at.z])
              f.root.position.set(r.position[0], r.position[1], r.position[2])
              f.root.quaternion.premultiply(fixQ.set(r.quaternion[0], r.quaternion[1], r.quaternion[2], r.quaternion[3]))
            }
          }
          f.root.updateMatrixWorld(true)
          return { pivot, frame: cal.frame }
        }
        // ── Ruling A129.3: the per-pair fine fit — the contact of the pair shown, its samples in stage space. ──
        type Hit = { e: number; r: number; chain: number; channel: string }
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
            if (h) return { e, r, ...h }
          }
          return null
        }
        const sampleAt = (res: NonNullable<ReturnType<typeof placePhaseB>>, hit: Hit, pivot: [number, number, number]): FitSample | null => {
          const ie = res.figures[hit.e].inspection, ir = res.figures[hit.r].inspection
          const w = ie && ir ? contactSampleOf(ie, ir, hit, pivot) : null
          return w ? { tip: toStageP(w.tip), base: toStageP(w.base), o: toStageP(w.o), u: toStageP(w.u, true), pivot } : null
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
        const fitReadout = (st: PairFitState, hit: Hit, axes: [number, number, number][]): PairFitReadout => {
          const tot = pairFitTotal(st)
          const lat = [...st.lateralMm].sort((a, b) => a - b)
          const [tl, rl] = axes.length ? fixAnglesDeg(tot, axes) : [0, 0]
          return { phase: st.phase, by: figs[hit.e].letter, of: figs[hit.r].letter,
            shiftMm: [tot.shift[0] * 1000, tot.shift[1] * 1000, tot.shift[2] * 1000], turnDeg: [tl, rl],
            lateralMaxMm: lat.length ? lat[lat.length - 1] : NaN, lateralMedMm: lat.length ? lat[lat.length >> 1] : NaN,
            frames: lat.length }
        }
        const live: { st: PairFitState; hit: Hit | null; none: boolean; axes: [number, number, number][] } = {
          st: createPairFit(), hit: null, none: false, axes: [] }
        const resetLive = () => { live.st = createPairFit(); live.hit = null; live.none = false }
        let liveFitOn = showRef.current.fit
        const placedNow = new Map<Fig, { pivot: [number, number, number]; frame: number[] }>()
        // ── Ruling A129.7: focus on the contact — the orbit target eases to the channel opening at 0.9 m, and an inset
        // (bottom right, orthographic, side-on to the channel axis) draws the axis (green, ±12 cm) and the shaft
        // (orange, base → tip). The user still orbits: only the target and the distance are eased. ──
        let focusNow: { o: number[]; u: number[]; tip: number[]; base: number[] } | null = null
        const axisGeom = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3()])
        const shaftGeom = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3()])
        const axisMat = new THREE.LineBasicMaterial({ color: 0x3fb950, depthTest: false })
        const shaftMat = new THREE.LineBasicMaterial({ color: 0xff9f1c, depthTest: false })
        own.push(axisGeom, shaftGeom, axisMat, shaftMat)
        const axisLine = new THREE.Line(axisGeom, axisMat), shaftLine = new THREE.Line(shaftGeom, shaftMat)
        axisLine.renderOrder = shaftLine.renderOrder = 1000
        sceneObj.add(axisLine, shaftLine)
        const insetCam = new THREE.OrthographicCamera(-0.12, 0.12, 0.12, -0.12, 0.01, 10)
        const fv = new THREE.Vector3(), fu = new THREE.Vector3(), fside = new THREE.Vector3(), fdir = new THREE.Vector3()
        const setLine = (geom: InstanceType<typeof THREE.BufferGeometry>, a: number[], b: number[]) => {
          const pos = geom.getAttribute('position') as InstanceType<typeof THREE.BufferAttribute>
          pos.setXYZ(0, a[0], a[1], a[2]); pos.setXYZ(1, b[0], b[1], b[2]); pos.needsUpdate = true
          geom.computeBoundingSphere()
        }
        const draw = () => {
          const fc = showRef.current.focus ? focusNow : null
          axisLine.visible = shaftLine.visible = !!fc
          host.dataset.focus = fc ? JSON.stringify({ o: fc.o.map((v) => +v.toFixed(4)), target: [controls.target.x, controls.target.y,
            controls.target.z].map((v) => +v.toFixed(4)), dist: +camera.position.distanceTo(controls.target).toFixed(3) }) : ''
          if (fc) {
            const o = fc.o, u = fc.u
            setLine(axisGeom, [o[0] - u[0] * 0.12, o[1] - u[1] * 0.12, o[2] - u[2] * 0.12], [o[0] + u[0] * 0.12, o[1] + u[1] * 0.12, o[2] + u[2] * 0.12])
            setLine(shaftGeom, fc.base, fc.tip)
            fv.set(o[0], o[1], o[2])
            fdir.copy(camera.position).sub(controls.target)
            controls.target.lerp(fv, 0.2)
            const d = fdir.length() || 1
            camera.position.copy(controls.target).addScaledVector(fdir.normalize(), d + (0.9 - d) * 0.2)
          }
          controls.update()
          placeMemory.camera = { pos: [camera.position.x, camera.position.y, camera.position.z],
            target: [controls.target.x, controls.target.y, controls.target.z] }
          renderer.setScissorTest(false)
          const w = renderer.domElement.clientWidth || width, h = renderer.domElement.clientHeight || height
          renderer.setViewport(0, 0, w, h)
          renderer.render(sceneObj, camera)
          if (fc) {
            // side-on to the axis: look along u × up (or u × x when the axis is vertical)
            fu.set(fc.u[0], fc.u[1], fc.u[2])
            fside.set(0, 1, 0).cross(fu)
            if (fside.lengthSq() < 1e-6) fside.set(1, 0, 0).cross(fu)
            fside.normalize()
            insetCam.position.copy(fv).addScaledVector(fside, 1)
            insetCam.up.set(0, 1, 0)
            insetCam.lookAt(fv)
            insetCam.updateProjectionMatrix()
            const iw = Math.round(Math.min(w, h) * 0.38)
            renderer.setScissorTest(true)
            renderer.setScissor(w - iw - 6, 6, iw, iw)
            renderer.setViewport(w - iw - 6, 6, iw, iw)
            renderer.setClearColor(0x0d1117, 1)
            renderer.clear()
            renderer.render(sceneObj, insetCam)
            renderer.setClearColor(0x000000, 0)
            renderer.setScissorTest(false)
            renderer.setViewport(0, 0, w, h)
          }
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
          const fitOn = showRef.current.fit && !solo && figs.length > 1
          if (fitOn !== liveFitOn) { liveFitOn = fitOn; resetLive() }
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
            const extra = fitOn && live.hit && figs[live.hit.e] === f ? pairFitTotal(live.st, time) : NO_FIX
            placedNow.set(f, placeRoot(f, time, draft, extra))
            f.runtime.poseStep({ realDelta: dt })
          }
          const wantInspect = showRef.current.collision || showRef.current.channels
          const fitInspect = (fitOn && !live.none) || showRef.current.focus
          const phaseB = placePhaseB(entries, frameState, wantInspect || fitInspect)   // phase B (+ the partner readout)
          if (fitInspect && phaseB && !pausedRef.current) {
            if (!live.hit) { live.hit = findHit(phaseB); live.none = !live.hit }
            const pl = live.hit ? placedNow.get(figs[live.hit.e]) : undefined
            const smp = live.hit && pl ? sampleAt(phaseB, live.hit, pl.pivot) : null
            if (live.hit && pl && smp) {
              live.axes = turnAxes(pl.frame)
              pairFitObserve(live.st, smp, time, live.axes, RUNTIME_FIT, showRef.current.follow)
            }
          }
          const inspection = wantInspect ? phaseB : null
          // A129.7: the contact this frame (world) for the camera focus and the inset.
          focusNow = null
          if (showRef.current.focus && phaseB) {
            const hit = live.hit ?? findHit(phaseB)
            const ie = hit ? phaseB.figures[hit.e].inspection : null, ir = hit ? phaseB.figures[hit.r].inspection : null
            const w = hit && ie && ir ? contactSampleOf(ie, ir, hit, [0, 0, 0]) : null
            if (w) focusNow = { o: w.o, u: w.u, tip: w.tip, base: w.base }
          }
          ms = ms * 0.9 + (performance.now() - t0) * 0.1
          drawPartners(inspection)
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
            const fit = fitOn && live.hit ? fitReadout(live.st, live.hit, live.axes) : null
            host.dataset.pairfit = fit ? JSON.stringify(fit) : ''
            setInfo({ ms, swingMm, strands: figs.filter((f) => f.runtime.strandRunning).length,
              chains: figs.filter((f) => !f.runtime.strandRunning && f.chains > 0).length, figures: rows,
              partners: partnerInfo, fit })
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
        // ── Ruling A126: Auto-align. Plays the clip in fixed 60 fps steps (two loops, the second sampled) with partner
        // B moved by `extra` (clip frame metres [side, up, forward] on top of the draft), reads the entering chain and
        // the receiving channel from every figure's inspection, solves the shift (scene-render `channelContact.ts`). ──
        const focusOn = () => { if (!showRef.current.focus) setShow((cur) => ({ ...cur, focus: true })) }
        const autoAlign = (): AutoAlignResult => {
          focusOn()
          if (solo || figs.length < 2) return { ok: false, reason: t('Auto-align needs a pair clip on a place.') }
          const step = 1 / 60
          const placed = new Map<Fig, { pivot: [number, number, number]; frame: number[] }>()
          const runAt = (time: number, draft: AlignmentDraft, inspect: boolean) => {
            for (const f of figs) {
              f.mixer.setTime(time)
              placed.set(f, placeRoot(f, time, draft))
              f.runtime.poseStep({ realDelta: step })
            }
            return placePhaseB(entries, frameState, inspect)
          }
          const base = draftRef.current
          const probe = runAt(timeRef.current, base, true)
          let found: { e: number; r: number; chain: number; channel: string } | null = null
          probe?.figures.forEach((fe, e) => fe.inspection?.chains.forEach((c, ci) => probe.figures.forEach((fr, r) => {
            if (found || r === e) return
            const ch = fr.inspection?.channels.find((x) => x.accepts.includes(c.op))
            if (ch) found = { e, r, chain: ci, channel: ch.id }
          })))
          const hit = found as { e: number; r: number; chain: number; channel: string } | null
          if (!hit) return { ok: false, reason: t('No figure here has an attached part that one of the other figure’s channels accepts.') }
          const fe = figs[hit.e], fr = figs[hit.r]
          const moving = figs.find((f) => f.role === 'b')
          if (!moving || (fe.role !== 'b' && fr.role !== 'b')) return { ok: false, reason: t('Auto-align moves partner B; neither figure of the contact is B.') }
          const sign = moving === fe ? 1 : -1
          const rot = new THREE.Matrix3().setFromMatrix4(stageInv)
          const vec = new THREE.Vector3()
          const toStage = (p: readonly number[], dir = false): [number, number, number] => {
            vec.set(p[0], p[1], p[2])
            if (dir) vec.applyMatrix3(rot).normalize(); else vec.applyMatrix4(stageInv)
            return [vec.x, vec.y, vec.z]
          }
          const b0 = base.roleShiftM.b ?? [0, 0, 0]
          const t0 = base.partnerTurnDeg ?? [0, 0]
          const savedTurn = (savedRef.current.b ?? moving.saved).partnerTurnDeg ?? [0, 0]
          const loop = Math.max(8, Math.ceil(duration / step))
          let axes: [number, number, number][] = []
          const pass = (extra: [number, number, number], turn: [number, number] = [0, 0]) => {
            const draft: AlignmentDraft = { ...base, roleShiftM: { ...base.roleShiftM,
              b: [b0[0] + extra[0], b0[1] + extra[1], b0[2] + extra[2]] }, partnerTurnDeg: [t0[0] + turn[0], t0[1] + turn[1]] }
            const samples: FitSample[] = []
            let overlap = 0, worst = ''   // mm while sampling (A129.5 honest check)
            for (let i = 0; i < 2 * loop; i++) {
              const time = (i % loop) * step % duration
              const res = runAt(time, draft, i >= loop)
              if (!res) continue
              const ie = res.figures[hit.e].inspection, ir = res.figures[hit.r].inspection
              const chain = ie?.chains[hit.chain]
              const ch = ir?.channels.find((x) => x.id === hit.channel)
              if (!ie || !ir || !chain?.segments.length || !ch) continue
              // The entering figure's pivot (stage space); a sign −1 (B receives) turns B, so the tip's pivot is B's.
              const pl = placed.get(moving)!
              axes = turnAxes(pl.frame)
              samples.push({ tip: toStage(chain.segments[chain.segments.length - 1].b), base: toStage(chain.segments[0].a),
                o: toStage(ch.o), u: toStage(ch.u, true), pivot: pl.pivot })
              const h = honestAt(res, hit)
              if (h.mm > overlap) { overlap = h.mm; worst = h.worst }
            }
            return { samples, overlap: overlap / 1000, worst, draft }
          }
          // world (stage) Δ of the entering tip → B's clip-frame role shift: S = sign · frameᵀ Δ, the vertical through the
          // hips-drop gain (root.y moves by hipsBind.y / standRef per metre of clip hips).
          const toClip = (d: [number, number, number], draft: AlignmentDraft): [number, number, number] => {
            const m = clipCalibration(draft, savedRef.current[moving.role] ?? moving.saved, moving.placeYaw,
              moving.place.marker.group).frame
            const k = standRefM > 0 && moving.hipsBind.y > 0 ? moving.hipsBind.y / standRefM : 1
            return [sign * (m[0] * d[0] + m[3] * d[1] + m[6] * d[2]), sign * (m[1] * d[0] + m[4] * d[1] + m[7] * d[2]) / k,
              sign * (m[2] * d[0] + m[5] * d[1] + m[8] * d[2])]
          }
          const p0 = pass([0, 0, 0])
          const chNow = probe!.figures[hit.r].inspection!.channels.find((x) => x.id === hit.channel)!
          if (p0.samples.length < 4) return { ok: false, reason: t('The contact could not be sampled over the clip.') }
          const before = contactReport(p0.samples)
          let extra: [number, number, number] = [0, 0, 0]
          let cur = p0
          for (let it = 0; it < 3; it++) {
            const d = solveContactShift(cur.samples)
            const s = toClip(d, cur.draft)
            extra = [extra[0] + s[0], extra[1] + s[1], extra[2] + s[2]]
            cur = pass(extra)
            if (Math.hypot(d[0], d[1], d[2]) < 0.0005) break
          }
          const afterShift = contactReport(cur.samples)
          // Ruling A129: then the angles — partner B's tilt/roll about its bind hips (±20° in all, saved included)
          // together with the shift, on top of the shift found above. Only when B is the entering figure: turning the
          // receiving figure would carry the channel, which the samples hold fixed.
          let turn: [number, number] = [0, 0]
          if (sign === 1) {
            const lim = ALIGN_FIT.maxAngleDeg
            for (let it = 0; it < 3; it++) {
              const fix = solvePairFix(cur.samples, { ...ALIGN_FIT, axes })
              const [dt, dr] = fixAnglesDeg(fix, axes)
              const total = (i: 0 | 1, d: number) => Math.max(-lim, Math.min(lim, savedTurn[i] + t0[i] + turn[i] + d))
                - savedTurn[i] - t0[i]
              const next: [number, number] = [total(0, dt), total(1, dr)]
              const s = toClip(fix.shift, cur.draft)
              extra = [extra[0] + s[0], extra[1] + s[1], extra[2] + s[2]]
              const moved = Math.abs(next[0] - turn[0]) + Math.abs(next[1] - turn[1])
              turn = next
              cur = pass(extra, turn)
              if (moved < 0.05 && Math.hypot(...fix.shift) < 0.0005) break
            }
          }
          const after = contactReport(cur.samples)
          runAt(timeRef.current, base, false)
          const cm = (v: number) => Math.round(v * 1000) / 10
          const deg = (v: number) => Math.round(v * 10) / 10
          return { ok: true, by: fe.letter, of: fr.letter, channel: hit.channel,
            shiftCm: [cm(b0[0] + extra[0]), cm(b0[1] + extra[1]), cm(b0[2] + extra[2])],
            turnDeg: [deg(t0[0] + turn[0]), deg(t0[1] + turn[1])], afterShift,
            before, after, overlapBeforeMm: p0.overlap * 1000, overlapAfterMm: cur.overlap * 1000,
            clearWorst: cur.worst, clearLamp: clearLamp(cur.overlap * 1000),
            lampBefore: contactLamp(before, chNow), lamp: contactLamp(after, chNow) }
        }
        // ── Ruling A129.3: the pair over whole loops at 60 fps — loop 1 as stored + draft (the "before"), loop 2 is
        // sampled for the fine fit (as client3d does when the interaction starts), loops 3–4 settle the chain and teach
        // the follow (A129.4), loops 5–6 are measured. ──
        const pairCheckOnce = (follow: boolean): PairCheckResult => {
          if (solo || figs.length < 2) return { ok: false, reason: t('The pair check needs a pair clip on a place.') }
          const step = 1 / 60
          const loop = Math.max(8, Math.ceil(duration / step))
          const draft = draftRef.current
          const st = createPairFit()
          let hit: Hit | null = null
          let axes: [number, number, number][] = []
          const before: FitSample[] = [], after: FitSample[] = []
          let clearBefore = 0, clearAfter = 0, clearWorst = ''
          for (let i = 0; i < 6 * loop; i++) {
            const time = (i % loop) * step % duration
            for (const f of figs) {
              f.mixer.setTime(time)
              placedNow.set(f, placeRoot(f, time, draft, hit && figs[hit.e] === f ? pairFitTotal(st, time) : NO_FIX))
              f.runtime.poseStep({ realDelta: step })
            }
            const res = placePhaseB(entries, frameState, true)
            if (!res) continue
            if (!hit) hit = findHit(res)
            if (!hit) continue
            const pl = placedNow.get(figs[hit.e])!
            const smp = sampleAt(res, hit, pl.pivot)
            if (!smp) continue
            axes = turnAxes(pl.frame)
            // Loop 3 settles the chain after the fit's jump; its rows do not count.
            if (i === 4 * loop) st.lateralMm = []
            const h = honestAt(res, hit)
            if (i < loop) { before.push(smp); clearBefore = Math.max(clearBefore, h.mm) }
            else if (st.phase === 'fitted' && i >= 4 * loop) {
              after.push(smp)
              if (h.mm > clearAfter) { clearAfter = h.mm; clearWorst = h.worst }
            }
            pairFitObserve(st, smp, time, axes, RUNTIME_FIT, follow)
          }
          for (const f of figs) {
            f.mixer.setTime(timeRef.current)
            placeRoot(f, timeRef.current, draftRef.current)
          }
          resetLive()
          if (!hit) return { ok: false, reason: t('No figure here has an attached part that one of the other figure’s channels accepts.') }
          if (before.length < 4 || after.length < 4) return { ok: false, reason: t('The contact could not be sampled over the clip.') }
          const fit = fitReadout(st, hit, axes), rep = contactReport(after)
          return { ok: true, by: figs[hit.e].letter, of: figs[hit.r].letter, before: contactReport(before),
            after: rep, fit, followed: rep, followFit: fit, clearMm: [clearBefore, clearAfter, clearAfter], clearWorst }
        }
        const pairCheck = (): PairCheckResult => {
          focusOn()
          const plain = pairCheckOnce(false)
          if (!plain.ok) return plain
          const followed = pairCheckOnce(true)
          return followed.ok ? { ...plain, followed: followed.after, followFit: followed.fit,
            clearMm: [plain.clearMm[0], plain.clearMm[1], followed.clearMm[1]], clearWorst: followed.clearWorst } : plain
        }
        if (pairCheckOut.current) pairCheckOut.current.current = pairCheck
        disposers.push(() => { if (pairCheckOut.current?.current) pairCheckOut.current.current = null })
        if (autoAlignOut.current) autoAlignOut.current.current = Object.assign(autoAlign, { kind, set, figures: figs.length })
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
        {[0.5, 1].map((s) => (
          <button key={s} type="button" className={`ga-btn ga-btn-sm${speed === s ? ' ga-btn-primary' : ''}`}
            onClick={() => setSpeed(s)}>{`${s}×`}</button>
        ))}
        <button type="button" className="ga-btn ga-btn-sm" onClick={() => fill(true)}
          title={t('Every place this clip fits gets a figure (at most 6).')}>{t('Fill all with this clip')}</button>
        {fillNote ? (
          <span role="status" data-testid="place-fill-note" className="ga-hint"
            style={fillNote.count ? { color: '#3fb950' } : { color: 'var(--danger, #f85149)' }}>
            {fillText(fillNote.count, fillNote.reason)}
          </span>
        ) : null}
        <label title={t('Draw each figure’s collision capsules as other figures engage them; overlapping pairs of two figures turn red.')}>
          <input type="checkbox" checked={show.collision} onChange={() => toggleShow('collision')} /> {t('Collision')}
        </label>
        <label title={t('Draw each figure’s channels; a ring at the mouth while a partner’s chain opens it.')}>
          <input type="checkbox" checked={show.channels} onChange={() => toggleShow('channels')} /> {t('Channels')}
        </label>
        <label title={t('Fits every pair on its own, as the game does when a pair interaction starts: one loop is measured, then the entering figure moves by at most 5 cm and turns by at most 10° so the attached part runs along the channel. The stored clip stays as it is.')}>
          <input type="checkbox" data-testid="place-fit" checked={show.fit} onChange={() => toggleShow('fit')} /> {t('Fine-fit the pair')}
        </label>
        <label title={t('The camera eases to the contact point (the channel opening) at 0.9 m, and an inset at the bottom right shows the channel axis (green) and the shaft of the attached part (orange) side-on. Auto-align and the pair check switch it on.')}>
          <input type="checkbox" data-testid="place-focus" checked={show.focus} onChange={() => toggleShow('focus')} /> {t('Focus the contact')}
        </label>
        <label title={t('Per frame, the entering figure’s pelvis follows by at most 2 cm so the attached part’s tip stays on the channel axis through the stroke, as in the game.')}>
          <input type="checkbox" data-testid="place-follow" checked={show.follow} disabled={!show.fit}
            onChange={() => toggleShow('follow')} /> {t('Follow the stroke')}
        </label>
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
          <div ref={hostRef} data-testid="place-preview" style={{ position: 'relative', height, background: 'var(--surface-2, #161b22)' }}>
            {status ? <div style={{ position: 'absolute', inset: 8, fontSize: 12, opacity: 0.8 }}>{status}</div> : null}
          </div>
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
                            const built = !!chars?.find((c) => c.name === v)?.built
                            if (!v) delete next[p.letter]
                            else next[p.letter] = { character: v, role: cur[p.letter]?.role ?? (solo ? '' : roleList[p.slot % roleList.length]),
                              body: built || v === MANNEQUIN ? 'outfit' : 'base', state: '' }
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
                    </div>
                  )) : (info.partners.channels
                    ? t('Channels: {n}, none engaged.').replace('{n}', String(info.partners.channels))
                    : t('No figure carries a channel.'))}
                </div>
              ) : null}
            </div>
          ) : null}
          {show.fit && info?.fit ? (
            <div style={{ marginTop: 6, borderTop: '1px solid var(--border, #30363d)', paddingTop: 4 }} data-testid="place-fit-readout"
              title={t('The fine fit of this pair on top of the stored clip (at most 5 cm and 10°), and how far the attached part’s tip stays off the channel axis while inside, over the fitted frames.')}>
              {info.fit.phase === 'collect'
                ? t('Fine fit {by} → {of}: measuring one loop…').replace('{by}', info.fit.by).replace('{of}', info.fit.of)
                : t('Fine fit {by} → {of}: {x} / {y} / {z} mm, tilt {tilt}°, roll {roll}° · off the axis inside: max {max} mm, median {med} mm')
                  .replace('{by}', info.fit.by).replace('{of}', info.fit.of)
                  .replace('{x}', info.fit.shiftMm[0].toFixed(0)).replace('{y}', info.fit.shiftMm[1].toFixed(0))
                  .replace('{z}', info.fit.shiftMm[2].toFixed(0))
                  .replace('{tilt}', info.fit.turnDeg[0].toFixed(1)).replace('{roll}', info.fit.turnDeg[1].toFixed(1))
                  .replace('{max}', Number.isFinite(info.fit.lateralMaxMm) ? info.fit.lateralMaxMm.toFixed(0) : '–')
                  .replace('{med}', Number.isFinite(info.fit.lateralMedMm) ? info.fit.lateralMedMm.toFixed(0) : '–')}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  )
}
