/**
 * ClipLibrary — what is actually INSTALLED in the shared animation libraries:
 * a narrow list of kinds (lamp first, the sets as letters n/f/m/a, used-by
 * count) and the selected kind's edit view (Ruling A110 phase 4).
 *
 * The other three surfaces of the Poses tab look at clips from the outside —
 * the catalog entries name a kind, the CMU browser and the inbox produce one.
 * This one looks at the files on disk: which kind exists in which set, in the
 * free or in the licensed library, how long it runs, where it came from, and
 * which pose entries depend on it. A kind a pose names but no file backs is a
 * "missing" row — the one gap that silently leaves a figure standing.
 *
 * Two libraries, one winner: a LICENSED file HIDES a free file of the same
 * name (the local, untracked library wins over the files in git). The hidden
 * one is not in the listing at all — the server resolves the collision before
 * it answers, so a cell tagged "free" and "licensed" holds files of DIFFERENT
 * names, never two versions of one.
 *
 * "Used by" counts the poses that play a kind AND the transition rules that
 * play it as their bridge (`from → to`) — a bridge-only clip is not unused.
 *
 * Per file the detail column carries the LOOP switch: whether a clip repeats
 * or holds its last frame is the admin's decision AFTER the import
 * (plan-animationen-echtzeit-stehplatz.md E5), not the importer's
 * measurement. It is stored in the `<kind>.json` sidecar and therefore holds
 * for the whole kind in that set — both halves of a pair, every variant.
 *
 * A rename or move onto a name that is already taken is not an error the
 * admin has to work around: the server answers 409, the action box stays open
 * and offers "Replace", which repeats the same call with `overwrite` and lets
 * the incoming file take the place of the one lying there.
 *
 * The edit view has inner sub-tabs — Places (the place preview), Clip (the
 * single-clip viewer with its surface box), Files (loop, repeats, roles,
 * rename/move/delete per file) and Used by — and BESIDE the viewer the
 * ALIGNMENT column: turn, tilt, roll, the whole-clip shift, the surface height
 * and a pair's partner B / a group's role offsets. Every drag moves the
 * figures live. ONE Save writes what is dirty — angles and role offsets BAKED
 * into the file (a Blender run), shift and heights into the sidecar, the
 * green place check (D3) — and says so, finale clips included, before the
 * click. The lamp per clip: green = checked on a place, yellow = sidecar
 * without a check, grey = no sidecar; "Built <time>" is the file's mtime.
 * A draft is never dropped silently: opening another clip or set asks first,
 * and `onUnsaved` tells the host (PosesTab), whose tab and view guards ask too.
 *
 *   PATCH  /assets/animation-clips/{library}/{rel}     {kind?, set?, library?, loop?, loop_count?, overwrite?}
 *   POST   /assets/animation-clips/{library}/{rel}/orient  {yaw_deg?, tilt_deg?, roll_deg?, role_shift_cm?, shift_cm?}
 *   DELETE /assets/animation-clips/{library}/{rel}
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ConfirmDialog } from '@anima/player-ui'
import { bendLimitsOf, clipHeightGroup, ALIGN_RANGE_CM_DEFAULT, ALIGN_TURN_DEG_DEFAULT, type ClipHeightOffsetsCm } from '@anima/scene-render'
import { targetWordOf } from './contactWords'
import { BendLimitsEditor, ContactRelations, RootAngleEditor } from './ContactRelations'
import { PlacePreview, type AlignMoverChoice, type AutoAlignOptions, type AutoAlignResult, type AutoAlignRun, type AlignCast, type PlaceReadout,
  type PairContactWire } from './PlacePreview'
import { AlignResultBlock } from './AlignResult'
import { AlignAllTable, type AlignAllRow } from './AlignAllTable'
import { kindStatusOf, relationStatus, unmeasuredStatus, stateWord, reasonText, STATE_COLOR, UNMEASURED_KEY,
  noteText, noteWord, entryNotes,
  type AlignStatusEntry, type AlignState } from './alignStatus'
import type { AlignmentDraft, ContactRelation } from '@anima/scene-render'
import { ClipPreview, ROLE_COLOR } from './ClipPreview'
import { invalidateAnimationPreviewClips } from '../characters/Model3DViewer'
import { SliderInput } from '../../components/SliderInput'
import { useI18n } from '../../i18n/I18nProvider'
import { ApiError, apiDelete, apiPatch, apiPost } from '../../lib/api'
import { bridgeKinds, orderSets } from './clipSets'
import type { ApiClipRow as BaseApiClipRow, BendLimitsWire, ClipListing, RootAngleWire } from './clipSets'
import { rootMotionSummary } from './rootMotion'
import { generatedBadge, isStudioClip } from './generatedClip'
import { clipLamp, finaleKinds as finaleKindsOf, kindLamp, runSaveWrites, saveSteps, setLetter } from './clipStatus'
import type { SaveWrite } from './clipStatus'
import { LampDot } from './StatusLamp'

interface ApiClipRow extends BaseApiClipRow {
  generator?: string
  license?: string
}

function libraryOf(c: ApiClipRow): string {
  return c.library || c.source || 'free'
}

/** Path inside the library — the listing carries it; older payloads are
 *  rebuilt from set + filename, which is the same string. */
function relOf(c: ApiClipRow): string {
  if (c.rel) return c.rel
  const file = c.filename || `${c.name || c.kind}.fbx`
  return c.set ? `${c.set}/${file}` : file
}

/** The kinds among ``clips`` other than ``kind`` — the finale clips an
 *  orientation or height edit changed along with the clip itself. */
function otherKinds(clips: { kind: string }[] | undefined, kind: string): string[] {
  return Array.from(new Set((clips ?? []).map((c) => c.kind).filter((k) => k && k !== kind)))
}

function clipPath(c: ApiClipRow): string {
  const rel = relOf(c)
    .split('/')
    .map((s) => encodeURIComponent(s))
    .join('/')
  return `/assets/animation-clips/${encodeURIComponent(libraryOf(c))}/${rel}`
}

function mb(bytes?: number): string {
  if (!bytes) return ''
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

/** Variants of a kind, not files: the two halves of a pair are ONE clip. */
function variants(clips: ApiClipRow[]): number {
  return clips.filter((c) => (c.role || '') !== 'b').length
}

interface Cell {
  free: ApiClipRow[]
  licensed: ApiClipRow[]
  all: ApiClipRow[]
}

/** Which gender plays which role of a GROUP clip (three roles and more):
 *  one choice per role, sent as a whole with "Apply" — the server takes only a
 *  complete assignment (every role, not everybody the same). A pair keeps its
 *  one compact choice. */
function GroupGenders({ roles, value, disabled, onApply, t }: {
  roles: string[]
  value: Record<string, string>
  disabled: boolean
  onApply: (v: Record<string, string> | null) => void
  t: (s: string) => string
}) {
  const [draft, setDraft] = useState<Record<string, string>>(value)
  const saved = JSON.stringify(value)
  useEffect(() => { setDraft(JSON.parse(saved)) }, [saved])
  const complete = roles.every((r) => draft[r]) && new Set(roles.map((r) => draft[r])).size > 1
  const changed = JSON.stringify(roles.map((r) => draft[r] || '')) !== JSON.stringify(roles.map((r) => value[r] || ''))
  return (
    <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginTop: 4, flexWrap: 'wrap' }}>
      <span>{t('Roles')}</span>
      {roles.map((r) => (
        <label key={r} style={{ display: 'flex', gap: 3, alignItems: 'center' }}>
          <span>{r.toUpperCase()}</span>
          <select className="ga-input" value={draft[r] || ''} disabled={disabled}
            onChange={(e) => setDraft((prev) => ({ ...prev, [r]: e.target.value }))}>
            <option value="">—</option>
            <option value="male">{t('man')}</option>
            <option value="female">{t('woman')}</option>
          </select>
        </label>
      ))}
      <button type="button" className="ga-btn ga-btn-sm" disabled={disabled || !complete || !changed}
        title={complete ? '' : t('Every role needs a gender, and not all the same.')}
        onClick={() => onApply(draft)}>{t('Apply')}</button>
      {Object.keys(value).length ? (
        <button type="button" className="ga-btn ga-btn-sm" disabled={disabled}
          onClick={() => onApply(null)}>{t('Clear')}</button>
      ) : null}
    </div>
  )
}

/** The repeat count of a looped clip: how many cycles before it holds its
 *  last frame. Empty = endless; a whole number 1..99 otherwise. Saved on
 *  blur or Enter, never per keystroke; a value the server would refuse is
 *  not sent. */
function LoopCountField({ value, disabled, onApply, t, finale = false }: {
  value: number | null | undefined
  disabled: boolean
  onApply: (v: number | null) => void
  t: (s: string) => string
  /** the field of a finale clip without the Loop switch: the same stored
   *  count, read as how often a pose's finale plays the clip */
  finale?: boolean
}) {
  const saved = value == null ? '' : String(value)
  const [draft, setDraft] = useState(saved)
  useEffect(() => { setDraft(saved) }, [saved])
  const text = draft.trim()
  const parsed = text === '' ? null : Number(text)
  const valid = parsed === null || (Number.isInteger(parsed) && parsed >= 1 && parsed <= 99)
  const commit = () => {
    if (!valid || text === saved) return
    onApply(parsed)
  }
  return (
    <label style={{ display: 'flex', gap: 6, alignItems: 'center', marginTop: 4, marginLeft: 22 }}
      title={finale
        ? t('How many times the clip plays when a pose closes with it — for every variant of the kind in this set.')
        : t('How many times the clip plays before it holds its last frame — for every variant of the kind in this set.')}>
      <span>{finale ? t('Times played as a finale') : t('Repeats')}</span>
      <input
        type="number"
        className="ga-input"
        style={{ width: 70 }}
        min={1}
        max={99}
        step={1}
        value={draft}
        placeholder={finale ? '1' : '∞'}
        disabled={disabled}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => { if (e.key === 'Enter') commit() }}
      />
      <span className="ga-form-hint" style={valid ? undefined : { color: 'var(--danger, #f85149)' }}>
        {valid ? (finale ? t('empty = once') : t('empty = endless')) : t('a whole number from 1 to 99, or empty')}
      </span>
    </label>
  )
}

interface Row {
  kind: string
  pair: boolean
  /** how many roles the kind's files play (2 = a pair, 3..5 = a group, 0 = solo) */
  roles: number
  /** pose keys whose `animation` is this kind */
  used: string[]
  cells: Record<string, Cell>
  clips: ApiClipRow[]
  /** named by a pose, but no file anywhere */
  missing: boolean
}

type ActionKind = 'kind' | 'set' | 'library' | 'delete'

interface PoseRef {
  key: string
  animation: string
  /** read-only in the place preview (D2) */
  yaw_offset?: number
  group?: string
  /** the pose's own finale clip kind, else the one a package derives — the finales a save edits too */
  finale_animation?: string
  finale_auto?: string
}

/** One alignment dial row in the column beside the viewer: label | track | number. */
const DIAL = { sliderWidth: 'auto', sliderStyle: { flex: 1, minWidth: 40 }, inputWidth: 54,
  style: { display: 'flex', width: '100%', fontSize: 12 } } as const
const DIAL_LABEL = { width: 74, flex: '0 0 74px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' } as const
const FILTER = { fontSize: 12, padding: '2px 4px', minWidth: 0 } as const
const COL_HEAD = { fontSize: 12, fontWeight: 600, opacity: 0.85, margin: '3px 0 1px' } as const
/** What sits above and below the clip viewer canvas in Game-Admin (header, tabs, the viewer toolbar, its caption), px. */
const PAGE_CHROME_PX = 340
/** Where the alignment column starts below the window top (header, Poses tabs, the kind's head line), px. */
const COL_TOP_PX = 240
/** Degrees wrapped to (−180, 180]. */
function wrapDeg(v: number): number {
  const w = ((v + 180) % 360 + 360) % 360
  return +((w === 0 ? 360 : w) - 180).toFixed(2)
}

type InnerTab = 'places' | 'clip' | 'files' | 'used'
/** A165: the alignment column's tabs — every setting stays reachable, one group at a time. */
type AlignTab = 'clip' | 'partner' | 'contacts' | 'bend' | 'check'

/** The window's inner height, live — the preview and the alignment column size themselves to it (A165). */
function useViewportHeight(): number {
  const [h, setH] = useState(() => (typeof window === 'undefined' ? 900 : window.innerHeight))
  useEffect(() => {
    const on = () => setH(window.innerHeight)
    window.addEventListener('resize', on)
    return () => window.removeEventListener('resize', on)
  }, [])
  return h
}

export function ClipLibrary({
  listing,
  poses,
  onReload,
  rootDropOf,
  focus,
  onOpenPose,
  onUnsaved,
}: {
  listing: ClipListing
  /** the pose catalog entries — the "Used by" column reads their `animation` */
  poses: PoseRef[]
  /** re-fetch the listing (and the catalog) after a rename/move/delete */
  onReload: () => Promise<void> | void
  /** `root_drop` of a place type (fraction of the figure height) — the preview
   *  sinks the figure that far under the calibration box's top, the way the
   *  server places it. Without it the figure would rest ON the bed. */
  rootDropOf?: (group: string) => number
  /** a kind to open right away — the pose editor's "Open in library"; a new
   *  `seq` opens it again even when the kind is the same */
  focus?: { kind: string; seq: number } | null
  /** open a pose entry in Entries (the place preview's yaw-offset link, D2) */
  onOpenPose?: (key: string) => void
  /** The open clip holds edits that were never saved (dials, heights, contacts, bend limits, root angle) — the
   *  host's tab and view guards count it. Reported false again when the library unmounts. */
  onUnsaved?: (unsaved: boolean) => void
}) {
  const { t } = useI18n()
  const [search, setSearch] = useState('')
  const [libFilter, setLibFilter] = useState('')
  // '*' = every set; '' is the neutral set and a value of its own
  const [setFilter, setSetFilter] = useState('*')
  const [onlyUsed, setOnlyUsed] = useState(false)
  const [onlyUnused, setOnlyUnused] = useState(false)
  const [selected, setSelected] = useState('')
  const [previewSet, setPreviewSet] = useState('')
  const [innerTab, setInnerTab] = useState<InnerTab>('places')
  // Which clip has an action open, and the value being typed for it
  const [action, setAction] = useState<{ rel: string; type: ActionKind } | null>(null)
  const [value, setValue] = useState('')
  // "Move to set" with a set that does not exist yet — the select then hands
  // over to a free text field instead of snapping back on every keystroke.
  const [customSet, setCustomSet] = useState(false)
  const [error, setError] = useState('')
  // The body of a rename/move the server refused with 409 (the name is taken).
  // It is kept so the "Replace" button can send exactly that call again, this
  // time with `overwrite` — the collision is a question, not a dead end.
  const [conflict, setConflict] = useState<Record<string, unknown> | null>(null)
  const [busy, setBusy] = useState(false)
  // Bumped after every write so the preview reloads the (possibly renamed) clip
  const [seq, setSeq] = useState(0)
  const [refreshing, setRefreshing] = useState(false)
  // Angles are a draft baked into ONE clip; heights are absolute per-surface
  // sidecar values. Changing the reference surface must not share its height.
  const [yawDeg, setYawDeg] = useState(0)
  const [tiltDeg, setTiltDeg] = useState(0)
  const [rollDeg, setRollDeg] = useState(0)
  // Owner decision 2026-11-23: every role's [tilt, roll, yaw] degrees about its hips — renderer-only, stored in the
  // sidecar (`role_turn_deg`); the draft is the DELTA to the saved value (the dials show saved + delta).
  const [roleTurn, setRoleTurn] = useState<Record<string, [number, number, number]>>({})
  // A STATUS PER CLIP: the statuses an Auto-align click earned, written when its result is saved — keyed by the dial
  // values it wrote (`dialKey`); a hand change after it turns them into "manual: adjusted".
  const pendingStatus = useRef<{ key: string; dials: string; relations: Record<string, AlignStatusEntry> } | null>(null)
  // The clip list's status filter ('' = all) and whether "Align all" includes clips ticked "manual: done".
  const [statusFilter, setStatusFilter] = useState('')
  const [includeDone, setIncludeDone] = useState(false)
  // A165: the alignment column is split into tabs so the 3D view stays in sight while a dial moves.
  const [alignTab, setAlignTab] = useState<AlignTab>('clip')
  const viewH = useViewportHeight()
  // Every role of a pair or group against the scene: {role: [side, up, forward]} cm, baked like the angles
  // (`role_shift_cm`); `shiftRole` is the one the sliders move.
  const [roleShift, setRoleShift] = useState<Record<string, [number, number, number]>>({})
  const [shiftRole, setShiftRole] = useState('a')
  const [clipShift, setClipShift] = useState<[number, number]>([0, 0])
  const [heightDraft, setHeightDraft] = useState<ClipHeightOffsetsCm>({})
  // Owner decision 2026-11-20 (scene-render `pairScale.ts`): the contact pivot an Auto-align run measured ([side,
  // forward] cm, null = none pending) — stored with Save.
  const [pivotDraft, setPivotDraft] = useState<[number, number] | null>(null)
  // Owner decision 2026-11-25 (scene-render `pairHeight.ts`): the contact heights the last Auto-align measured (Save
  // stores them), and the Places view's "Real heights" switch — while it is on, Auto-align and Save are off: both
  // measure and store data of 1.70 m figures, which the real-height preview no longer shows.
  const [contactHeightsDraft, setContactHeightsDraft] = useState<Record<string, PairContactWire> | null>(null)
  const [realHeights, setRealHeights] = useState(false)
  // "Align all" → "Store contact heights": progress of the run over every pair/group clip.
  const [heightsRun, setHeightsRun] = useState<{ running: boolean; done: number; total: number; stored: number; missed: string[] } | null>(null)
  const [heightBusy, setHeightBusy] = useState(false)
  // Empty selects the ground height and draws only the grid.
  const [footprint, setFootprint] = useState('')
  const [orientBusy, setOrientBusy] = useState(false)
  const [orientError, setOrientError] = useState('')
  const [orientSeconds, setOrientSeconds] = useState<number | null>(null)
  /** The place preview's readout (loop medians) — an all-green one is stored with Apply/Save (D3). */
  const [placeReadout, setPlaceReadout] = useState<PlaceReadout | null>(null)
  /** Ruling A126: the place preview's Auto-align (set while a pair scene runs) and its last outcome. */
  const autoAlignRef = useRef<AutoAlignRun | null>(null)
  /** "Align all": the persons by role of the clip stage 1 started on (kept for Re-measure and stage 2), and what the
   *  preview's default fill reads while an "Align all" action runs. */
  const stageCast = useRef<AlignCast | null>(null)
  const castRef = useRef<AlignCast | null>(null)
  /** "Align all" in two stages (owner 2026-11-22, `AlignAllTable`): stage 1 measures every pair and group clip listed,
   *  one row per contact relation, nothing written; stage 2 applies and saves the ticked rows. `running` names the
   *  stage at work, `done`/`total` count clips. */
  const [alignAll, setAlignAll] = useState<{ running: '' | 'measure' | 'apply'; done: number; total: number
    rows: AlignAllRow[] } | null>(null)
  const alignAllStop = useRef(false)
  const [autoAlign, setAutoAlign] = useState<AutoAlignResult | null>(null)
  /** ONE RELATION, ONE MOVER (2026-11-22): the contact relation one Auto-align click aligns (an index into
   *  `alignChoices`) and which of its two roles moves. */
  const [alignPick, setAlignPick] = useState(0)
  const [alignMover, setAlignMover] = useState<AlignMoverChoice>('auto')
  /** Ruling A212: "Also align end clips" — one row per end clip: the Auto-align result and whether it was stored. */
  const [finaleRun, setFinaleRun] = useState<{ running: boolean; rows: { kind: string; result: AutoAlignResult; saved: boolean
    error: string; note: string }[] } | null>(null)
  /** Ruling A212 review H1: the arrangement Auto-align's cap is measured from — the dials as the user last set them
   *  (clip load, save, a manual dial move), never the dials an Auto-align result wrote (an Auto-align click, or an
   *  "Align all" result filled in when its clip is opened). */
  const [alignBase, setAlignBase] = useState<AutoAlignOptions['base']>(null)
  /** The dial values an Auto-align result just wrote (`dialKey`): the base effect skips exactly those, so the base
   *  stays the user's; any other dial value (a manual move) takes over again. */
  const autoWrite = useRef<string | null>(null)
  /** Finale clips the server changed along with the last apply/save. */
  const [finalesTouched, setFinalesTouched] = useState<string[]>([])
  /** Whether the open clip holds unsaved edits — set below, read by `guardSwitch` from event handlers. */
  const unsavedRef = useRef(false)
  /** A clip switch waiting for "discard the unsaved edits?" (in-app, never window.confirm). */
  const [pendingSwitch, setPendingSwitch] = useState<(() => void) | null>(null)
  /** Runs `fn` — a switch to another clip or set, which resets every draft — at once while nothing is unsaved,
   *  otherwise after the user confirmed. */
  const guardSwitch = useCallback((fn: () => void) => {
    if (unsavedRef.current) setPendingSwitch(() => fn)
    else fn()
  }, [])

  const clips = useMemo(() => listing.clips || [], [listing.clips])
  const pairKinds = useMemo(
    () => new Set(listing.pair_kinds || []),
    [listing.pair_kinds],
  )

  /** Columns: everything selectable on a character plus every set that has
   *  files — a set whose directory exists but is not offered anywhere would
   *  otherwise hide its clips. */
  const columns = useMemo(() => {
    const all = new Set<string>([''])
    for (const s of listing.sets || []) all.add(s)
    for (const s of listing.clip_sets || []) all.add(s)
    for (const c of clips) all.add(c.set || '')
    return orderSets(Array.from(all))
  }, [clips, listing.clip_sets, listing.sets])

  const usage = useMemo(() => {
    const out: Record<string, string[]> = {}
    for (const p of poses) {
      const k = (p.animation || '').trim()
      if (!k) continue
      ;(out[k] = out[k] || []).push(p.key)
    }
    for (const r of listing.transitions || []) {
      for (const k of bridgeKinds(r.kind)) (out[k] = out[k] || []).push(`${r.from} → ${r.to}`)
    }
    return out
  }, [poses, listing.transitions])

  const rows = useMemo<Row[]>(() => {
    const kinds = new Set<string>(listing.kinds || [])
    for (const c of clips) kinds.add(c.kind)
    // A kind a pose names but no file backs — the gap this view exists to show
    for (const k of Object.keys(usage)) kinds.add(k)
    return Array.from(kinds)
      .sort()
      .map((kind) => {
        const own = clips.filter((c) => c.kind === kind)
        const cells: Record<string, Cell> = {}
        for (const col of columns) {
          const inSet = own.filter((c) => (c.set || '') === col)
          cells[col] = {
            free: inSet.filter((c) => libraryOf(c) === 'free'),
            licensed: inSet.filter((c) => libraryOf(c) === 'licensed'),
            all: inSet,
          }
        }
        return {
          kind,
          pair: pairKinds.has(kind) || own.some((c) => (c.role || '') === 'b'),
          roles: new Set(own.map((c) => c.role || '').filter(Boolean)).size,
          used: usage[kind] || [],
          cells,
          clips: own,
          missing: !own.length,
        }
      })
  }, [clips, columns, listing.kinds, pairKinds, usage])

  const shown = useMemo(() => {
    const q = search.trim().toLowerCase()
    return rows.filter((r) => {
      if (q && !r.kind.toLowerCase().includes(q)) return false
      if (libFilter === 'studio') {
        if (!r.clips.some(isStudioClip)) return false
      } else if (libFilter && !r.clips.some((c) => libraryOf(c) === libFilter)) return false
      if (setFilter !== '*' && !r.clips.some((c) => (c.set || '') === setFilter)) return false
      if (onlyUsed && !r.used.length) return false
      if (onlyUnused && r.used.length) return false
      if (statusFilter && kindStatus(r.clips).key !== statusFilter) return false
      return true
    })
  }, [libFilter, onlyUnused, onlyUsed, rows, search, setFilter, statusFilter])

  const row = useMemo(() => rows.find((r) => r.kind === selected) || null, [rows, selected])
  /** A STATUS PER CLIP: how many pair/group kinds of the list (before the status filter) show each status. */
  const statusCounts = useMemo(() => {
    const out: Record<string, number> = {}
    for (const r of rows) {
      if ((r.roles ?? 0) < 2 || r.missing) continue
      const k = kindStatus(r.clips).key || 'not_checked'
      out[k] = (out[k] ?? 0) + 1
    }
    return out
  }, [rows])

  const refresh = useCallback(async () => {
    if (refreshing) return
    setRefreshing(true)
    try {
      await onReload()
    } finally {
      setRefreshing(false)
    }
  }, [onReload, refreshing])

  /** Sets the selected kind actually has a clip in — the preview's switch. */
  const rowSets = useMemo(
    () => (row ? orderSets(Array.from(new Set(row.clips.map((c) => c.set || '')))) : []),
    [row],
  )

  /** Back to an untouched clip: the dials are a draft for ONE file. */
  const resetDials = useCallback(() => {
    setYawDeg(0)
    setTiltDeg(0)
    setRollDeg(0)
    setRoleTurn({})
    setRoleShift({})
    setShiftRole('a')
    setClipShift([0, 0])
    setHeightDraft({})
    setOrientError('')
    setOrientSeconds(null)
    setFinalesTouched([])
  }, [])

  const pick = useCallback(
    (kind: string, set?: string) => {
      if (orientBusy || heightBusy) return
      setSelected(kind)
      resetDials()
      // Clicking the row (no column) previews the set the kind actually has —
      // neutral when there is one, otherwise the first that exists.
      const own = clips.filter((c) => c.kind === kind).map((c) => c.set || '')
      const nextSet = set !== undefined ? set : orderSets(Array.from(new Set(own)))[0] || ''
      setPreviewSet(nextSet)
      setAction(null)
      setError('')
      setConflict(null)
    },
    [clips, heightBusy, orientBusy, resetDials],
  )

  /** "Align all" (owner 2026-11-22): open one clip and wait for its Places scene with two or more figures (or for its
   *  answer that no prop has a place for it); null = it never came. */
  const openRun = useCallback(async (kind: string, set: string): Promise<AutoAlignRun | null> => {
    pick(kind, set)
    const wait = (ms: number) => new Promise((r) => setTimeout(r, ms))
    const t0 = performance.now()
    const done = (run: AutoAlignRun | null, stage: OpenWait['stage'], figures = 0) => {
      openWait.current = { s: (performance.now() - t0) / 1000, stage, figures }
      return run
    }
    // up to OPEN_SCENE_S for the clip's scene, then up to OPEN_FIGURES_S for its figures (models loaded for the first
    // time); a scene rebuilt meanwhile (the persons filled in after the props loaded) is waited for again
    let seen = -1, figures = 0
    for (let k = 0; k < OPEN_SCENE_S * 2 + OPEN_FIGURES_S * 2 && !alignAllStop.current; k++) {
      await wait(500)
      const cur = autoAlignRef.current
      if (!cur || cur.kind !== kind || (cur.set ?? '') !== set) { if (seen < 0 && k > OPEN_SCENE_S * 2) break; continue }
      if (cur.noPlace) return done(cur, 'no_place')
      if (seen < 0) seen = k
      figures = cur.figures ?? 0
      if (figures < 2) { if (k - seen > OPEN_FIGURES_S * 2) return done(null, 'figures', figures); continue }
      // a moment for the figures' first frames
      await wait(1500)
      if (autoAlignRef.current === cur) return done(cur, 'ok', figures)
    }
    return done(null, seen < 0 ? 'scene' : 'figures', figures)
  }, [pick])
  /** How long the last `openRun` waited and for what (shown in "Align all"'s row of a clip that gave nothing). */
  const openWait = useRef<OpenWait>({ s: 0, stage: 'ok', figures: 0 })
  /** Stage 1's rows of one clip: one per measured contact relation, or one that says why there is none. */
  const allRowsOf = useCallback((kind: string, set: string, res: AutoAlignResult | null,
    choices: Record<string, AlignMoverChoice> = {}): AlignAllRow[] => {
    if (!res || !res.ok) {
      // no relation was measured (no place, no persons filled, or the persons have no fitting part): not measured
      const w = openWait.current
      const waited = !res ? (w.stage === 'scene' ? t('the scene did not come within {s} s') : t('{n} of 2 figures after {s} s'))
        .replace('{s}', w.s.toFixed(0)).replace('{n}', String(w.figures)) : ''
      return [{ kind, set, key: '', label: '–', bucket: 'unmeasured', rel: null, code: res && !res.ok ? res.code : 'no_pair',
        reason: res && !res.ok ? res.reason : `${t('No pair was filled on a place of this clip.')} (${waited})`, choice: 'auto', tick: false,
        outcome: '', waitS: w.s }]
    }
    return res.relations.map((x) => ({ kind, set, key: x.key, label: `${x.by} → ${x.of} (${targetWordOf(t, x.target)})`,
      bucket: x.bucket, rel: x, reason: '', choice: choices[x.key] ?? 'auto', tick: x.bucket === 'improve', outcome: '',
      waitS: openWait.current.s }))
  }, [t])
  /** Stage 1: measure every pair and group clip listed, relation by relation (mover 'auto'); nothing is written. */
  /** Owner decision 2026-11-25: "Store contact heights" — every pair and group clip of the list (the same choice as
   *  stage 1) is opened with its cast, the contact heights of the arrangement it HAS (the stored dials, nothing
   *  aligned) are measured at 1.70 m and stored (`pair_contact_heights`); a clip without a contact or a pair on a
   *  place is named. The way to fill the clips no Auto-align has touched since contact heights exist. */
  const storeAllHeights = useCallback(async () => {
    const targets = shown.filter((r) => (r.roles ?? 0) >= 2 && !r.missing && (includeDone || kindStatus(r.clips).key !== 'done'))
    const back = selected
    setRealHeights(false)
    alignAllStop.current = false
    stageCast.current = autoAlignRef.current?.cast ?? null
    castRef.current = stageCast.current
    let done = 0, stored = 0
    const missed: string[] = []
    setHeightsRun({ running: true, done, total: targets.length, stored, missed: [] })
    for (const r of targets) {
      if (alignAllStop.current) break
      const set = orderSets(Array.from(new Set(r.clips.map((c) => c.set || ''))))[0] || ''
      const file = clips.find((c) => c.kind === r.kind && (c.set || '') === set && (c.role || '') === 'a')
      const run = file ? await openRun(r.kind, set) : null
      const heights = run && !run.noPlace ? run.contactHeights?.() ?? null : null
      if (heights && file) {
        try { await apiPatch(clipPath(file), { pair_contact_heights: heights }); stored += 1 } catch { missed.push(r.kind) }
      } else missed.push(r.kind)
      done += 1
      setHeightsRun({ running: true, done, total: targets.length, stored, missed: [...missed] })
    }
    invalidateAnimationPreviewClips()
    try { await onReload() } catch { /* the counts above already say what was stored */ }
    setSeq((n) => n + 1)
    setHeightsRun({ running: false, done, total: targets.length, stored, missed })
    castRef.current = null
    if (back) pick(back)
  }, [clips, includeDone, onReload, openRun, pick, selected, shown])
  const runAlignAll = useCallback(async () => {
    const targets = shown.filter((r) => (r.roles ?? 0) >= 2 && !r.missing && (includeDone || kindStatus(r.clips).key !== 'done'))
    const back = selected
    setRealHeights(false)
    alignAllStop.current = false
    stageCast.current = autoAlignRef.current?.cast ?? null
    castRef.current = stageCast.current
    const out: AlignAllRow[] = []
    setAlignAll({ running: 'measure', done: 0, total: targets.length, rows: [] })
    let done = 0
    for (const r of targets) {
      if (alignAllStop.current) break
      const set = orderSets(Array.from(new Set(r.clips.map((c) => c.set || ''))))[0] || ''
      const run = await openRun(r.kind, set)
      const res = run ? run({ each: true, mover: 'auto' }) : null
      out.push(...allRowsOf(r.kind, set, res))
      done += 1
      setAlignAll({ running: 'measure', done, total: targets.length, rows: [...out] })
    }
    setAlignAll({ running: '', done, total: targets.length, rows: out })
    castRef.current = null
    if (back) pick(back)
  }, [allRowsOf, includeDone, openRun, pick, selected, shown])
  /** Stage 1, one clip again: the row's mover choice for its relation, the movers the other rows of the clip used. */
  const remeasureAll = useCallback(async (i: number) => {
    const cur = alignAll
    const row = cur?.rows[i]
    if (!cur || !row) return
    const same = (x: AlignAllRow) => x.kind === row.kind && x.set === row.set
    const moverOf: Record<string, AlignMoverChoice> = {}
    for (const x of cur.rows.filter(same)) if (x.key) moverOf[x.key] = x === row ? row.choice : x.rel?.mover ?? 'auto'
    alignAllStop.current = false
    castRef.current = stageCast.current
    setAlignAll({ ...cur, running: 'measure' })
    const back = selected
    const run = await openRun(row.kind, row.set)
    const res = run ? run({ each: true, moverOf }) : null
    const fresh = allRowsOf(row.kind, row.set, res, row.key ? { [row.key]: row.choice } : {})
    setAlignAll((prev) => {
      if (!prev) return prev
      const at = prev.rows.findIndex(same)
      const rest = prev.rows.filter((x) => !same(x))
      return { ...prev, running: '', rows: [...rest.slice(0, at), ...fresh, ...rest.slice(at)] }
    })
    castRef.current = null
    if (back) pick(back)
  }, [alignAll, allRowsOf, openRun, pick, selected])
  /** Stage 2: each clip with a ticked row is measured again with ONLY its ticked relations and the movers shown, and
   *  stored (orient: the role offsets and role turns; the root angle; the contact pivot) only when every one of them
   *  still applies and improves. A STATUS PER CLIP: every row of the table is recorded in its clip's sidecar — a saved
   *  relation as improved / aligned, a row not ticked with the status stage 1 measured (blocked, mismatch, not
   *  measurable); an unticked "would improve" row leaves its relation as it was. */
  const applyAlignAll = useCallback(async () => {
    const cur = alignAll
    if (!cur) return
    const byClip = new Map<string, AlignAllRow[]>()
    for (const r of cur.rows) byClip.set(`${r.kind}|${r.set}`, [...(byClip.get(`${r.kind}|${r.set}`) ?? []), r])
    let rows = cur.rows.map((r) => ({ ...r, outcome: '' }))
    setRealHeights(false)
    alignAllStop.current = false
    castRef.current = stageCast.current
    setAlignAll({ ...cur, running: 'apply', done: 0, total: byClip.size, rows })
    const back = selected
    let done = 0
    for (const all of byClip.values()) {
      if (alignAllStop.current) break
      const ticked = all.filter((r) => r.tick && r.rel)
      const { kind, set } = all[0]
      const file = clips.find((c) => c.kind === kind && (c.set || '') === set && (c.role || '') === 'a')
      const status: Record<string, AlignStatusEntry | null> = {}
      for (const r of all) {
        if (r.tick) continue
        if (!r.rel) { if (r.code) status[UNMEASURED_KEY] = unmeasuredStatus(r.code); continue }
        if (r.bucket !== 'improve') status[r.key] = relationStatus(r.rel)
      }
      let outcome = ''
      if (ticked.length) {
        const keys = new Set(ticked.map((x) => x.key))
        const declared = (file?.contact_target?.relations ?? []).filter((x) => x.target !== 'none')
        const opts: AutoAlignOptions = { each: true, moverOf: Object.fromEntries(ticked.map((x) => [x.key, x.rel!.mover])),
          ...(declared.length ? { relations: declared.filter((x) => keys.has(`${x.part}>${x.at}:${x.target}`)) } : {}) }
        const run = file ? await openRun(kind, set) : null
        const res = run ? run(opts) : null
        if (!file) outcome = t('No clip file for this set.')
        else if (!res || !res.ok) outcome = res && !res.ok ? res.reason : t('No pair was filled on a place of this clip.')
        else if (!res.relations.every((x) => x.applied && x.bucket === 'improve')) {
          outcome = t('changed when measured again — not saved')
          for (const x of res.relations) if (!x.applied) status[x.key] = relationStatus(x)
        } else {
          try {
            const moved = Object.fromEntries(Object.entries(res.roleShiftCm).filter(([, v]) => v.some((x) => x !== 0)))
            const turned = Object.fromEntries(Object.entries(res.roleTurnDeg).filter(([, v]) => v.some((x) => x !== 0)))
            if (Object.keys(moved).length || Object.keys(turned).length) {
              await apiPost(`${clipPath(file)}/orient`, { yaw_deg: 0, tilt_deg: 0, roll_deg: 0,
                ...(Object.keys(moved).length ? { role_shift_cm: moved } : {}),
                ...(Object.keys(turned).length ? { role_turn_deg: turned } : {}) })
            }
            const root = res.rootAngle
            if (root && (root.pitchDeg !== (file.root_angle?.pitch_deg ?? 0) || root.yawDeg !== (file.root_angle?.yaw_deg ?? 0))) {
              await apiPatch(clipPath(file), { root_angle: { pitch_deg: root.pitchDeg, yaw_deg: root.yawDeg } })
            }
            if (res.pivotCm) await apiPatch(clipPath(file), { pair_pivot_cm: res.pivotCm })
            // Owner decision 2026-11-25: the contact heights of the arrangement just stored (after the orient write).
            if (res.contactHeights) await apiPatch(clipPath(file), { pair_contact_heights: res.contactHeights })
            for (const x of res.relations) status[x.key] = relationStatus(x)
            outcome = t('saved')
          } catch (e) { outcome = (e as Error).message }
        }
      }
      if (file && Object.keys(status).length) {
        if (Object.keys(status).some((k) => k !== UNMEASURED_KEY)) status[UNMEASURED_KEY] = null
        try { await apiPatch(clipPath(file), { align_status: { relations: status } }) } catch (e) {
          outcome = `${outcome ? `${outcome} · ` : ''}${t('status not stored')}: ${(e as Error).message}`
        }
      }
      rows = rows.map((r) => (r.kind === kind && r.set === set && (r.tick || outcome) ? { ...r, outcome } : r))
      done += 1
      setAlignAll({ ...cur, running: 'apply', done, total: byClip.size, rows })
    }
    invalidateAnimationPreviewClips()
    try { await onReload() } catch { /* the rows above already say what was stored */ }
    setSeq((n) => n + 1)
    setAlignAll({ ...cur, running: '', done, total: byClip.size, rows })
    castRef.current = null
    if (back) pick(back)
  }, [alignAll, clips, onReload, openRun, pick, selected, t])

  // Opened from a pose: every filter off so the row is in the list, the kind
  // selected and scrolled into view — once per `seq`, after the listing is in.
  const focused = useRef(0)
  const tableRef = useRef<HTMLDivElement | null>(null)
  useEffect(() => {
    if (!focus?.kind || focus.seq === focused.current || !clips.length) return
    focused.current = focus.seq
    setSearch('')
    setLibFilter('')
    setSetFilter('*')
    setOnlyUsed(false)
    setOnlyUnused(false)
    pick(focus.kind)
    requestAnimationFrame(() => {
      tableRef.current?.querySelector(`[data-kind="${CSS.escape(focus.kind)}"]`)
        ?.scrollIntoView({ block: 'center' })
    })
  }, [clips.length, focus, pick])

  /** The file the dials act on: the previewed set's clip, and for a pair its
   *  A half — the server turns the B half with it, in one Blender run. */
  const orientTarget = useMemo(
    () => (row
      ? row.clips.find((c) => (c.set || '') === previewSet && (c.role || '') !== 'b') || null
      : null),
    [previewSet, row],
  )
  const heightGroup = clipHeightGroup(footprint)
  const heightCm = heightDraft[heightGroup] ?? orientTarget?.height_offsets_cm?.[heightGroup] ?? 0
  const heightDirty = Object.entries(heightDraft).some(
    ([group, cm]) => cm !== (orientTarget?.height_offsets_cm?.[group as keyof ClipHeightOffsetsCm] ?? 0),
  )
  // Ruling A139: the contact relations — a draft over the saved list, reset when the clip changes.
  const savedContacts = orientTarget?.contact_target ?? null
  const savedContactsKey = JSON.stringify(savedContacts?.relations ?? [])
  const [contactDraft, setContactDraft] = useState<ContactRelation[]>([])
  useEffect(() => { setContactDraft(JSON.parse(savedContactsKey) as ContactRelation[]) }, [savedContactsKey, selected])
  // Ruling A145: the bend limits — a draft over the saved (or inherited) value, reset when the clip changes.
  const savedBend = orientTarget?.bend_limits ?? null
  const savedBendKey = JSON.stringify(savedBend?.limits ?? BEND_WIRE_DEFAULT)
  const [bendDraft, setBendDraft] = useState<BendLimitsWire>(BEND_WIRE_DEFAULT)
  useEffect(() => { setBendDraft(JSON.parse(savedBendKey) as BendLimitsWire) }, [savedBendKey, selected])
  // Ruling A158: the attached part's direct root angle — a draft over the saved value, the preview applies it live.
  const savedRoot = orientTarget?.root_angle ?? null
  const savedRootKey = JSON.stringify(savedRoot ?? { pitch_deg: 0, yaw_deg: 0 })
  const [rootDraft, setRootDraft] = useState<RootAngleWire>({ pitch_deg: 0, yaw_deg: 0 })
  useEffect(() => { setRootDraft(JSON.parse(savedRootKey) as RootAngleWire) }, [savedRootKey, selected, previewSet])
  // The contact pivot: every clip or set starts without a pending one.
  useEffect(() => { setPivotDraft(null); setContactHeightsDraft(null) }, [selected, previewSet])
  const savedPivot = orientTarget?.pair_pivot_cm ?? null
  const pivotDirty = !!pivotDraft && !!orientTarget?.role
    && (!savedPivot || pivotDraft[0] !== savedPivot[0] || pivotDraft[1] !== savedPivot[1])
  // Owner decision 2026-11-25: the measured contact heights differ from the stored ones (per relation it measured).
  const savedContactHeights = orientTarget?.pair_contact_heights ?? null
  const contactHeightsDirty = !!contactHeightsDraft && !!orientTarget?.role && Object.entries(contactHeightsDraft)
    .some(([k, v]) => JSON.stringify(savedContactHeights?.[k] ?? null) !== JSON.stringify(v))
  // The dials act on the A half; how many roles it has decides pair or group.
  const isPairTarget = orientTarget?.role === 'a' && (row?.roles ?? 0) === 2
  const isGroupTarget = orientTarget?.role === 'a' && (row?.roles ?? 0) > 2
  // PART 3 (2026-11-22): a pair moves its roles like a group — every role has its own shift (`role_shift_cm`).
  const shiftRoles = isPairTarget || isGroupTarget ? (['a', 'b', 'c', 'd', 'e'] as const).slice(0, row?.roles ?? 0) : []
  const turnedRoles = useMemo(() => (isGroupTarget || isPairTarget
    ? Object.fromEntries(Object.entries(roleTurn).filter(([, v]) => v.some((x) => x !== 0)))
    : {}), [isGroupTarget, isPairTarget, roleTurn])
  const turnDirty = Object.keys(turnedRoles).length > 0
  const savedRoleTurn = orientTarget?.orientation?.role_turn_deg ?? {}
  const movedRoles = useMemo(() => (isGroupTarget || isPairTarget
    ? Object.fromEntries(Object.entries(roleShift).filter(([, v]) => v.some((x) => x !== 0)))
    : {}), [isGroupTarget, isPairTarget, roleShift])
  const roleShiftDirty = Object.keys(movedRoles).length > 0
  const clipShiftDirty = clipShift.some((v) => v !== 0)
  const orientDirty = !!(yawDeg || tiltDeg || rollDeg) || roleShiftDirty || clipShiftDirty || turnDirty
  // The three drafts with a Save button of their own, dirty by the same rule their editor shows "unsaved" by
  // (ContactRelations / BendLimitsEditor / RootAngleEditor).
  const contactsDirty = JSON.stringify(contactDraft) !== savedContactsKey
  const bendDirty = !!savedBend && JSON.stringify(bendDraft) !== savedBendKey
  const rootDirty = rootDraft.pitch_deg !== (savedRoot?.pitch_deg ?? 0) || rootDraft.yaw_deg !== (savedRoot?.yaw_deg ?? 0)
  // Ruling A212: the clip's alignment range (cm) — a draft over the saved (or default) value, reset when the clip changes.
  const savedAlignRange = orientTarget?.align_range?.cm ?? ALIGN_RANGE_CM_DEFAULT
  const [alignRangeDraft, setAlignRangeDraft] = useState<number | null>(null)
  useEffect(() => { setAlignRangeDraft(null) }, [savedAlignRange, selected])
  const alignRangeCm = alignRangeDraft ?? savedAlignRange
  const alignRangeDirty = alignRangeDraft !== null && alignRangeDraft !== savedAlignRange
  // Owner decision 2026-11-23: the clip's rotation range (degrees, each of tilt/roll/yaw) beside the alignment range.
  const savedAlignTurn = orientTarget?.align_turn?.deg ?? ALIGN_TURN_DEG_DEFAULT
  const [alignTurnDraft, setAlignTurnDraft] = useState<number | null>(null)
  useEffect(() => { setAlignTurnDraft(null) }, [savedAlignTurn, selected])
  const alignTurnDeg = alignTurnDraft ?? savedAlignTurn
  const alignTurnDirty = alignTurnDraft !== null && alignTurnDraft !== savedAlignTurn
  /** ONE RELATION, ONE MOVER: the contacts a click can align — the draft's relations (not "none"), or the one the
   *  preview detects when the clip declares none. */
  const alignChoices = useMemo<{ label: string; rel: ContactRelation | null }[]>(() => {
    const rels = contactDraft.filter((x) => x.target !== 'none')
    return rels.length ? rels.map((x) => ({ rel: x,
      label: `${x.part.toUpperCase()} → ${x.at.toUpperCase()} (${targetWordOf(t, x.target)})` }))
      : [{ rel: null, label: t('the detected contact') }]
  }, [contactDraft, t])
  const alignPickShown = alignPick < alignChoices.length ? alignPick : 0
  const alignChoice = alignChoices[alignPickShown] ?? null
  /** Everything a clip switch, a view switch or a tab switch would throw away. */
  const unsaved = orientDirty || heightDirty || contactsDirty || bendDirty || rootDirty || alignRangeDirty || alignTurnDirty || pivotDirty
  unsavedRef.current = unsaved
  useEffect(() => { onUnsaved?.(unsaved) }, [onUnsaved, unsaved])
  useEffect(() => () => onUnsaved?.(false), [onUnsaved])
  // ONE draft object for the place preview, read through a ref in its frame loop (a drag reloads nothing).
  const alignmentDraft = useMemo<AlignmentDraft>(() => ({
    yawDeg, tiltDeg, rollDeg, shiftCm: clipShift,
    roleShiftM: isPairTarget || isGroupTarget
      ? Object.fromEntries(Object.entries(roleShift).map(([r, v]) =>
        [r, [v[0] / 100, v[1] / 100, v[2] / 100] as [number, number, number]]))
      : {},
    heightCm: heightDraft,
    roleTurnDeg: isPairTarget || isGroupTarget ? roleTurn : undefined,
    contactRelations: contactDraft,
    bendLimits: bendLimitsOf(bendDraft),
    rootAngle: { pitchDeg: rootDraft.pitch_deg, yawDeg: rootDraft.yaw_deg },
  }), [bendDraft, rootDraft, contactDraft, clipShift, heightDraft, isGroupTarget, isPairTarget, roleTurn, roleShift, rollDeg, tiltDeg, yawDeg])
  useEffect(() => {
    if (autoWrite.current !== null && autoWrite.current === dialKey(roleTurn, roleShift)) return
    autoWrite.current = null
    setAlignBase({ roleShiftM: Object.fromEntries(Object.entries(roleShift).map(([r, v]) => [r, [v[0] / 100, v[1] / 100, v[2] / 100] as [number, number, number]])),
      roleTurnDeg: roleTurn })
  }, [roleTurn, roleShift])
  const draftRef = useRef(alignmentDraft)
  draftRef.current = alignmentDraft
  /** The check to store with Apply/Save: only when every figure reads green (D3/D4). */
  const placeCheck = useMemo(() => (placeReadout?.allGreen
    ? { prop: placeReadout.prop, place: placeReadout.places, dyaw: +placeReadout.worstYaw.toFixed(2),
      dpos: +placeReadout.worstPos.toFixed(2) }
    : null), [placeReadout])
  const savedCheck = orientTarget?.orientation?.checked ?? null
  // The baked angles live in the sidecar, so a clip without one has nowhere to
  // put them — the block says so instead of earning a 400 after Apply.
  const heightLocked = orientBusy || heightBusy
  const orientLocked = heightLocked || orientTarget?.has_sidecar === false || !!finaleRun?.running

  // What a save would bake: angles and per-role offsets go through Blender; the whole-clip shift and the
  // surface heights are sidecar values (no Blender), the check is a sidecar mark.
  const bakeDirty = !!(yawDeg || tiltDeg || rollDeg) || roleShiftDirty
  /** The finale clips the server edits along with this one (`finale_kinds_of` + same set/library): the
   *  finale of every pose that plays the kind, when a file of it lies beside this clip. */
  const finaleKinds = useMemo(() => (row && orientTarget
    ? finaleKindsOf(poses, row.kind, { set: orientTarget.set, library: libraryOf(orientTarget) },
      clips.map((c) => ({ kind: c.kind, set: c.set, library: libraryOf(c) })))
    : []), [clips, orientTarget, poses, row])
  /** Ruling A212: "Also align end clips" — after the base is saved, each end clip of the same set is opened in the
   *  Places view and aligned with the base's contact relations, joined to the base's last frame (`endPose`), within
   *  the same range; each result is stored on that end clip (orient: the B / role offsets and B's tilt/roll; the
   *  relations too when the end clip has none of its own). Back to the base afterwards. */
  const runAlignFinales = useCallback(async () => {
    const baseRun = autoAlignRef.current
    if (!row || !orientTarget || !baseRun?.endPose) return
    const end = baseRun.endPose()
    if (!end) return
    const baseKind = row.kind, baseSet = previewSet, baseLib = libraryOf(orientTarget)
    const relations = contactDraft
    const rangeCm = alignRangeCm
    const turnRange = alignTurnDeg
    const out: { kind: string; result: AutoAlignResult; saved: boolean; error: string; note: string }[] = []
    setFinaleRun({ running: true, rows: [] })
    const wait = (ms: number) => new Promise((r) => setTimeout(r, ms))
    for (const kind of finaleKinds) {
      pick(kind, baseSet)
      let run: AutoAlignRun | null = null
      for (let k = 0; k < 240; k++) {
        await wait(500)
        const cur = autoAlignRef.current
        if (cur && cur.kind === kind && (cur.set ?? '') === baseSet && (cur.figures ?? 0) >= 2) { run = cur; break }
      }
      await wait(1500)
      // The scene may have been rebuilt meanwhile: only the SAME run that was found counts.
      if (run && autoAlignRef.current !== run) run = null
      const file = clips.find((c) => c.kind === kind && (c.set || '') === baseSet && (c.role || '') === 'a'
        && libraryOf(c) === baseLib)
      // What earlier end-clip runs baked already: the cap is measured from before the first run.
      const appliedShift = file?.align_applied?.role_shift_cm ?? {}
      const appliedTurn = file?.align_applied?.role_turn_deg ?? {}
      const base = { roleShiftM: Object.fromEntries(Object.entries(appliedShift).map(([r, v]) =>
        [r, [-v[0] / 100, -v[1] / 100, -v[2] / 100] as [number, number, number]])),
        roleTurnDeg: Object.fromEntries(Object.entries(appliedTurn).map(([r, v]) =>
          [r, [-v[0], -v[1], -v[2]] as [number, number, number]])) }
      const result: AutoAlignResult = !file ? { ok: false, reason: t('No end clip file for this set.') }
        : run ? run({ relations, rangeCm, turnDeg: turnRange, join: end, base })
          : { ok: false, reason: t('No pair was filled on a place of this clip.') }
      let saved = false, error = '', note = ''
      if (result.ok && file) {
        try {
          const moved = Object.fromEntries(Object.entries(result.roleShiftCm).filter(([, v]) => v.some((x) => x !== 0)))
          const turned = Object.fromEntries(Object.entries(result.roleTurnDeg).filter(([, v]) => v.some((x) => x !== 0)))
          // Ruling A212 (2026-11-20): the end clip's own root angle, when the run solved it and it changed.
          const root = result.rootAngle
          const rootChanged = !!root && (root.pitchDeg !== (file.root_angle?.pitch_deg ?? 0) || root.yawDeg !== (file.root_angle?.yaw_deg ?? 0))
          if (root && rootChanged) await apiPatch(clipPath(file), { root_angle: { pitch_deg: root.pitchDeg, yaw_deg: root.yawDeg } })
          const nothing = !Object.keys(moved).length && !Object.keys(turned).length
          if (nothing && rootChanged) note = t('root angle stored')
          if (!nothing) {
            await apiPost(`${clipPath(file)}/orient`, { yaw_deg: 0, tilt_deg: 0, roll_deg: 0,
              ...(Object.keys(moved).length ? { role_shift_cm: moved } : {}),
              ...(Object.keys(turned).length ? { role_turn_deg: turned } : {}) })
            const sum = (book: Record<string, [number, number, number]>, add: Record<string, [number, number, number]>) => {
              const out: Record<string, [number, number, number]> = { ...book }
              for (const [r, v] of Object.entries(add)) {
                const was = out[r] ?? [0, 0, 0]
                out[r] = [+(was[0] + v[0]).toFixed(2), +(was[1] + v[1]).toFixed(2), +(was[2] + v[2]).toFixed(2)]
              }
              return out
            }
            await apiPatch(clipPath(file), { align_applied: { role_shift_cm: sum(appliedShift, moved),
              role_turn_deg: sum(appliedTurn, turned) } })
          } else if (!rootChanged) note = t('already aligned')
          // Owner decision 2026-11-20: the end clip's own contact pivot (after its orient write, which turns or drops one).
          const sp = file.pair_pivot_cm
          if (result.pivotCm && (!sp || sp[0] !== result.pivotCm[0] || sp[1] !== result.pivotCm[1])) {
            await apiPatch(clipPath(file), { pair_pivot_cm: result.pivotCm })
            if (nothing && !rootChanged) note = t('contact pivot stored')
          }
          // Owner decision 2026-11-25: the end clip's own contact heights, measured on what it now stores.
          if (result.contactHeights) await apiPatch(clipPath(file), { pair_contact_heights: result.contactHeights })
          // The base's relations only where the end clip has none in force.
          if (!file.contact_target?.relations?.length && relations.length) await apiPatch(clipPath(file), { contact_target: relations })
          saved = true
        } catch (e) { error = (e as Error).message }
      }
      out.push({ kind, result, saved, error, note })
      setFinaleRun({ running: true, rows: [...out] })
    }
    invalidateAnimationPreviewClips()
    try { await onReload() } catch { /* the rows above already say what was stored */ }
    setSeq((n) => n + 1)
    setFinaleRun({ running: false, rows: out })
    pick(baseKind, baseSet)
  }, [alignRangeCm, alignTurnDeg, clips, contactDraft, finaleKinds, onReload, orientTarget, pick, previewSet, row, t])
  // A green check that is already stored (same prop and places) is not offered again on its own.
  const checkStored = !!(placeCheck && savedCheck && savedCheck.prop === placeCheck.prop
    && savedCheck.place === placeCheck.place)
  const checkOnly = !orientDirty && !heightDirty && !!placeCheck && !checkStored
  const canSave = !!orientTarget && (orientDirty || heightDirty || checkOnly || rootDirty || pivotDirty || contactHeightsDirty)
    && !heightLocked && !(orientDirty && orientLocked) && !realHeights
  /** The consequence of Save, shown BEFORE the click (checklist point 2). */
  const saveConsequence = useMemo(() => saveSteps({
    bake: bakeDirty, shift: clipShiftDirty || turnDirty, heights: heightDirty, root: rootDirty, pivot: pivotDirty,
    contact: contactHeightsDirty,
    finales: finaleKinds.length,
    greenCheck: !!placeCheck && (orientDirty || heightDirty || !checkStored), savedCheck: !!savedCheck,
  }).map((step) => ({
    bake: t('turn/tilt/roll and role offsets are baked into the clip file (one Blender run, no hub jobs)'),
    shift: t('the side/forward shift and the role turns (tilt/roll/yaw) go to the sidecar'),
    heights: t('surface heights go to the sidecar and apply in game'),
    finales: t('the finale clips change the same way: {kinds}').replace('{kinds}', finaleKinds.join(', ')),
    check: t('the green place check is stored'),
    'clear-check': t('the stored place check is cleared'),
    root: t('the root angle goes to the sidecar'),
    pivot: t('the contact pivot goes to the sidecar (figures of other heights are scaled about it in the game)'),
    contact: t('the contact heights go to the sidecar (the game closes the vertical gap of figures of other heights from them)'),
  })[step]), [bakeDirty, checkStored, clipShiftDirty, contactHeightsDirty, finaleKinds, heightDirty, orientDirty, pivotDirty,
    placeCheck, rootDirty, savedCheck, t, turnDirty])
  /** THE one save path: bake/shift (orient), heights, root angle and contact pivot (PATCH) and the place check, in that
   *  order — the pivot after the orient write, which turns or drops a stored one. */
  const save = useCallback(async () => {
    if (!orientTarget || !canSave) return
    setOrientBusy(true)
    setHeightBusy(heightDirty)
    setOrientError('')
    const touched = new Set<string>()
    const writes: Array<readonly [SaveWrite, () => Promise<unknown>]> = []
    if (orientDirty) {
      writes.push(['orient', async () => {
        const res = await apiPost<{ seconds?: number; clips?: { kind: string }[] }>(`${clipPath(orientTarget)}/orient`, {
          yaw_deg: yawDeg, tilt_deg: tiltDeg, roll_deg: rollDeg,
          ...(roleShiftDirty ? { role_shift_cm: movedRoles } : {}),
          ...(clipShiftDirty ? { shift_cm: clipShift } : {}),
          ...(turnDirty ? { role_turn_deg: turnedRoles } : {}),
          ...(placeCheck ? { checked: placeCheck } : {}),
        })
        setOrientSeconds(typeof res.seconds === 'number' ? res.seconds : null)
        otherKinds(res.clips, orientTarget.kind).forEach((k) => touched.add(k))
      }])
    }
    if (heightDirty) {
      writes.push(['heights', async () => {
        const res = await apiPatch<{ clips?: { kind: string }[] }>(clipPath(orientTarget), { height_offsets_cm: heightDraft })
        otherKinds(res.clips, orientTarget.kind).forEach((k) => touched.add(k))
      }])
    }
    if (rootDirty) writes.push(['root', () => apiPatch(clipPath(orientTarget), { root_angle: rootDraft })])
    if (pivotDirty) writes.push(['pivot', () => apiPatch(clipPath(orientTarget), { pair_pivot_cm: pivotDraft })])
    // After the orient write, which drops stored heights on a tilt, roll or height bake.
    if (contactHeightsDirty) writes.push(['contact', () => apiPatch(clipPath(orientTarget), { pair_contact_heights: contactHeightsDraft })])
    // A STATUS PER CLIP: what this save leaves on the clip's relations — the statuses of the Auto-align result it
    // stores when the dials are still the ones that result wrote, "manual: adjusted" when a hand moved the roles.
    const moves = (roleShiftDirty || turnDirty || rootDirty) && (isPairTarget || isGroupTarget)
    if (moves) {
      const pend = pendingStatus.current
      const fromAuto = !!pend && pend.key === statusKey(orientTarget) && pend.dials === dialKey(roleTurn, roleShift)
      const keys = new Set([...Object.keys(orientTarget.align_status?.relations ?? {}),
        ...contactDraft.filter((x) => x.target !== 'none').map((x) => `${x.part}>${x.at}:${x.target}`),
        ...Object.keys(pend?.relations ?? {})])
      keys.delete(UNMEASURED_KEY)
      const relations: Record<string, AlignStatusEntry | null> = fromAuto ? { ...pend!.relations }
        : Object.fromEntries([...keys].map((k) => [k, { state: 'manual_adjusted' as const }]))
      if (Object.keys(relations).length) {
        relations[UNMEASURED_KEY] = null
        writes.push(['status', () => apiPatch(clipPath(orientTarget), { align_status: { relations } })])
      }
    }
    // Heights are not a bake, and a check with nothing dialled is stored on its own (D3).
    if (!orientDirty && placeCheck) {
      writes.push(['check', () => apiPost(`${clipPath(orientTarget)}/orient`, { checked: placeCheck })])
    }
    try {
      const { applied, error } = await runSaveWrites(writes)
      if (applied.length) {
        setFinalesTouched(Array.from(touched))
        // The new saved values first, THEN the draft back to zero: in between the figures would jump.
        // A failed reload still clears the applied drafts — kept, they would be baked a second time.
        invalidateAnimationPreviewClips()
        let reloadError: unknown = null
        try { await onReload() } catch (e) { reloadError = e }
        if (applied.includes('orient')) {
          setYawDeg(0)
          setTiltDeg(0)
          setRollDeg(0)
          setRoleTurn({})
          setRoleShift({})
          setClipShift([0, 0])
          pendingStatus.current = null
        }
        if (applied.includes('heights')) setHeightDraft({})
        if (applied.includes('pivot')) setPivotDraft(null)
        if (applied.includes('contact')) setContactHeightsDraft(null)
        // The file keeps its URL, so the preview has to be rebuilt AND the
        // clip re-fetched — `seq` does both (component key + cache buster).
        if (applied.includes('orient') || applied.includes('heights')) setSeq((n) => n + 1)
        if (!error && reloadError) setOrientError((reloadError as Error).message)
      }
      if (error) setOrientError((error as Error).message)
    } catch (e) {
      setOrientError((e as Error).message)
    } finally {
      setOrientBusy(false)
      setHeightBusy(false)
    }
  }, [canSave, clipShift, clipShiftDirty, contactDraft, heightDirty, heightDraft, isGroupTarget, isPairTarget, movedRoles, onReload,
    orientDirty, orientTarget, pivotDirty, pivotDraft, placeCheck, roleShift, roleShiftDirty, roleTurn, rollDeg, rootDirty, rootDraft,
    tiltDeg, turnDirty, turnedRoles, yawDeg])

  /** Saved angles and calibration, including every earlier apply. */
  const savedNote = useMemo(() => {
    const o = orientTarget?.orientation
    if (!o) return ''
    const parts = [
      o.yaw_deg ? `${t('turn')} ${o.yaw_deg}°` : '',
      o.tilt_deg ? `${t('tilt')} ${o.tilt_deg}°` : '',
      o.roll_deg ? `${t('roll')} ${o.roll_deg}°` : '',
      typeof o.floor_shift_cm === 'number' ? `${t('floor shift')} ${o.floor_shift_cm} cm` : '',
      o.shift_cm?.some((v) => v !== 0) ? `${t('side / forward shift')} ${o.shift_cm[0]} / ${o.shift_cm[1]} cm` : '',
      ...Object.entries(o.role_turn_deg || {}).map(([r, v]) =>
        `${t('role {r} tilt / roll / yaw').replace('{r}', r.toUpperCase())} ${v[0]} / ${v[1]} / ${v[2]}°`),
      ...Object.entries(o.role_shift_cm || {}).map(([r, v]) =>
        `${t('role {r} forward / side / up').replace('{r}', r.toUpperCase())} ${v[2]} / ${v[0]} / ${v[1]} cm`),
    ].filter(Boolean)
    return parts.length ? parts.join(' · ') : t('nothing turned yet')
  }, [orientTarget, t])

  const openAction = useCallback((clip: ApiClipRow, type: ActionKind) => {
    setError('')
    setConflict(null)
    setAction({ rel: `${libraryOf(clip)}/${relOf(clip)}`, type })
    setValue(type === 'kind' ? clip.kind : type === 'set' ? clip.set || '' : '')
    setCustomSet(false)
  }, [])

  const run = useCallback(
    async (clip: ApiClipRow, body: Record<string, unknown> | null) => {
      if (busy) return
      setBusy(true)
      setError('')
      setConflict(null)
      try {
        if (body) await apiPatch(clipPath(clip), body)
        else await apiDelete(clipPath(clip))
        setAction(null)
        setSeq((n) => n + 1)
        await onReload()
        // A renamed kind carries the selection with it, so the detail pane
        // does not fall back to the placeholder after every rename.
        if (typeof body?.kind === 'string') setSelected(body.kind)
        if (typeof body?.set === 'string') setPreviewSet(body.set)
      } catch (e) {
        setError((e as Error).message)
        // 409 is the ONE refusal with an answer: the name at the target is
        // taken. The action box stays open and offers "Replace", which is
        // this very body once more with `overwrite`.
        if (body && e instanceof ApiError && e.status === 409) setConflict(body)
      } finally {
        setBusy(false)
      }
    },
    [busy, onReload],
  )

  /** The offer after a 409 — shown inside the action box that ran into it. */
  const replaceNode = (clip: ApiClipRow) =>
    conflict ? (
      <>
        <span className="ga-hint" style={{ color: 'var(--danger, #f85149)' }}>
          {t('That name is taken. Replace overwrites the file lying there — it is gone for good.')}
        </span>
        <button
          type="button"
          className="ga-btn ga-btn-sm ga-btn-danger"
          disabled={busy}
          onClick={() => run(clip, { ...conflict, overwrite: true })}
        >
          {t('Replace')}
        </button>
      </>
    ) : null

  /** The sets a kind has files in, as letters (n f m a …) — one mark per set instead of a column each;
   *  the libraries and the variant count sit in the mouse-over. */
  const setMarks = (r: Row) => columns.filter((col) => r.cells[col]?.all.length).map((col) => {
    const cell = r.cells[col]
    const libs = [
      cell.free.length ? t('free') : '',
      cell.licensed.length ? t('licensed') : '',
      cell.all.some(isStudioClip) ? t('studio') : '',
      cell.all.map((c) => generatedBadge(c)).find(Boolean) || '',
    ].filter(Boolean)
    const n = variants(cell.all)
    return (
      <span key={col || 'neutral'} className={`ga-tag${cell.licensed.length ? ' ga-tag-tier' : ''}`}
        style={{ padding: '0 4px', fontSize: 11, cursor: 'pointer' }}
        title={`${col || t('neutral')}: ${libs.join(', ')}${n > 1 ? ` ×${n}` : ''}`}
        onClick={(e) => { e.stopPropagation(); guardSwitch(() => pick(r.kind, col)) }}>
        {setLetter(col)}{n > 1 ? <sup>{n}</sup> : null}
      </span>
    )
  })

  /** "Built <time>" of a clip file — when the import or the last bake wrote it. */
  const builtText = (c: ApiClipRow | null | undefined) => (c?.built_s
    ? t('Built {time}').replace('{time}', new Date(c.built_s * 1000).toLocaleString())
    : '')
  /** The lamp's reason in plain words. */
  const lampText = (c: ApiClipRow) => {
    const lamp = clipLamp(c)
    const ck = c.orientation?.checked
    if (lamp === 'green' && ck) {
      return t('Orientation checked {at} on {prop} / {place}: {dyaw}°, {dpos} cm')
        .replace('{at}', new Date(ck.at).toLocaleString())
        .replace('{prop}', ck.prop).replace('{place}', ck.place)
        .replace('{dyaw}', String(ck.dyaw)).replace('{dpos}', String(ck.dpos))
    }
    return lamp === 'grey'
      ? t('No sidecar: orientation, loop and heights cannot be stored — import the clip again.')
      : t('Orientation not checked on a place yet — Save while every place reads green.')
  }

  /** The kinds a pose closes with (its `finale_animation`, else what a
   *  package derives): such a clip shows its play count without the Loop switch. */
  const finaleClipKinds = new Set(poses
    .map((p) => (p.finale_animation || p.finale_auto || '').trim().toLowerCase()).filter(Boolean))

  const clipNode = (clip: ApiClipRow) => {
    const lib = libraryOf(clip)
    const rel = `${lib}/${relOf(clip)}`
    const open = action?.rel === rel ? action.type : null
    const other = lib === 'licensed' ? 'free' : 'licensed'
    // Which gender plays which half — one answer for every role of the kind.
    const genderA = clip.role_gender?.a || ''
    const halfGender = clip.role ? clip.role_gender?.[clip.role] || '' : ''
    // The roles of THIS kind in this set and library: a group (three and
    // more) edits one gender per role, a pair keeps the compact choice.
    const kindRoles = clip.role
      ? Array.from(new Set(clips
        .filter((c) => c.kind === clip.kind && (c.set || '') === (clip.set || '')
          && libraryOf(c) === lib && c.role)
        .map((c) => c.role as string))).sort()
      : []
    const facts = [
      clip.role
        ? `${t('half')} ${clip.role.toUpperCase()}${halfGender ? ` (${halfGender === 'male' ? t('man') : t('woman')})` : ''}`
        : '',
      clip.duration_s ? `${clip.duration_s.toFixed(1)} s` : '',
      clip.fps ? `${clip.fps} fps` : '',
      clip.frames ? `${clip.frames} ${t('frames')}` : '',
      clip.origin && clip.origin !== 'unknown' && !isStudioClip(clip) ? clip.origin : '',
      mb(clip.size),
      clip.has_sidecar === false ? t('no sidecar') : '',
    ].filter(Boolean)
    return (
      <li key={rel} style={{ fontSize: 12, padding: '6px 0', borderBottom: '1px solid var(--border, #30363d)' }}>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
          <LampDot lamp={clipLamp(clip)} title={lampText(clip)} />
          <code style={{ wordBreak: 'break-all' }}>{clip.filename || relOf(clip)}</code>
          <span className="ga-form-hint" style={{ margin: 0 }}>{builtText(clip)}</span>
          <span className={`ga-tag${lib === 'licensed' ? ' ga-tag-tier' : ''}`}>{t(lib)}</span>
          {generatedBadge(clip) ? (
            <span className="ga-tag ga-tag-tier" title={clip.license}>{generatedBadge(clip)}</span>
          ) : null}
          {isStudioClip(clip) ? (
            <span className="ga-tag ga-tag-tier" title={t('made in the animation studio (written as code)')}>
              {t('studio')}
            </span>
          ) : null}
        </div>
        <div className="ga-form-hint" style={{ marginTop: 2 }}>{facts.join(' · ')}</div>
        <label
          style={{ display: 'flex', gap: 6, alignItems: 'center', marginTop: 4 }}
          title={clip.has_sidecar === false
            ? t('Without a sidecar there is nowhere to store the flag — import the clip again.')
            : t('Applies to the whole kind in this set: both halves of a pair and every variant.')}
        >
          <input
            type="checkbox"
            checked={!!clip.loop}
            disabled={busy || clip.has_sidecar === false}
            onChange={(e) => run(clip, { loop: e.target.checked })}
          />
          <span>{t('Loop')}</span>
          <span className="ga-form-hint">{t('Repeat the clip; off = hold the last frame')}</span>
        </label>
        {clip.loop ? (
          <LoopCountField value={clip.loop_count} t={t}
            disabled={busy || clip.has_sidecar === false}
            onApply={(v) => run(clip, { loop_count: v })} />
        ) : finaleClipKinds.has(clip.kind) ? (
          <LoopCountField value={clip.finale_loop_count} t={t} finale
            disabled={busy || clip.has_sidecar === false}
            onApply={(v) => run(clip, { loop_count: v })} />
        ) : null}
        {clip.root_motion ? (
          <div className="ga-form-hint" style={{ marginTop: 2 }}>
            {t('Root motion')}: {rootMotionSummary(clip.root_motion, t)}
          </div>
        ) : null}
        {clip.role && kindRoles.length > 2 ? (
          <GroupGenders roles={kindRoles} value={clip.role_gender || {}} t={t}
            disabled={busy || clip.has_sidecar === false}
            onApply={(v) => run(clip, { role_gender: v })} />
        ) : clip.role ? (
          <label
            style={{ display: 'flex', gap: 6, alignItems: 'center', marginTop: 4, flexWrap: 'wrap' }}
            title={clip.has_sidecar === false
              ? t('Without a sidecar there is nowhere to store the roles — import the clip again.')
              : t('Applies to both halves of the pair in this set.')}
          >
            <span>{t('Roles')}</span>
            <select
              className="ga-input"
              style={{ maxWidth: 220 }}
              value={genderA}
              disabled={busy || clip.has_sidecar === false}
              onChange={(e) => {
                const a = e.target.value
                run(clip, { role_gender: a ? { a, b: a === 'male' ? 'female' : 'male' } : null })
              }}
            >
              <option value="">{t('not set')}</option>
              <option value="male">{t('A = man, B = woman')}</option>
              <option value="female">{t('A = woman, B = man')}</option>
            </select>
            <span className="ga-form-hint">
              {t('A man and a woman always play their own halves; otherwise the one who starts plays A.')}
            </span>
          </label>
        ) : null}
        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginTop: 4 }}>
          <button type="button" className="ga-btn ga-btn-sm" onClick={() => openAction(clip, 'kind')}>
            {t('Rename kind')}
          </button>
          <button type="button" className="ga-btn ga-btn-sm" onClick={() => openAction(clip, 'set')}>
            {t('Move to set')}
          </button>
          <button type="button" className="ga-btn ga-btn-sm" onClick={() => openAction(clip, 'library')}>
            {other === 'free' ? t('Move to free library') : t('Move to licensed library')}
          </button>
          <button
            type="button"
            className="ga-btn ga-btn-sm ga-btn-danger"
            onClick={() => openAction(clip, 'delete')}
          >
            {t('Delete')}
          </button>
        </div>

        {open === 'kind' ? (
          <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginTop: 6, flexWrap: 'wrap' }}>
            <input
              className="ga-input"
              style={{ maxWidth: 200 }}
              value={value}
              onChange={(e) => setValue(e.target.value)}
            />
            <button
              type="button"
              className="ga-btn ga-btn-sm ga-btn-primary"
              disabled={busy || !value.trim()}
              onClick={() => run(clip, { kind: value.trim().toLowerCase() })}
            >
              {t('Apply')}
            </button>
            <button type="button" className="ga-btn ga-btn-sm" onClick={() => setAction(null)}>
              {t('Cancel')}
            </button>
            {replaceNode(clip)}
            <span className="ga-hint">
              {t('Lowercase letters, digits, space, "_" and "-"; never "__" (that separates the pair halves) and never a trailing "_<number>" (that is the variant numbering).')}
            </span>
            {usage[clip.kind]?.length ? (
              <span className="ga-hint" style={{ color: 'var(--warn, #d29922)' }}>
                {`${t('Poses that play this kind')}: ${usage[clip.kind].join(', ')} — ${t('they are not updated automatically and will find no clip under the old name.')}`}
              </span>
            ) : null}
          </div>
        ) : null}

        {open === 'set' ? (
          <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginTop: 6, flexWrap: 'wrap' }}>
            <select
              className="ga-input"
              style={{ maxWidth: 160 }}
              value={customSet ? '__custom' : value}
              onChange={(e) => {
                const v = e.target.value
                setCustomSet(v === '__custom')
                setValue(v === '__custom' ? '' : v)
              }}
            >
              {columns.map((s) => (
                <option key={s || 'neutral'} value={s}>
                  {s || t('— neutral —')}
                </option>
              ))}
              <option value="__custom">{t('— a new set —')}</option>
            </select>
            {!customSet ? null : (
              <input
                className="ga-input"
                style={{ maxWidth: 160 }}
                placeholder={t('new set')}
                value={value}
                onChange={(e) => setValue(e.target.value)}
              />
            )}
            <button
              type="button"
              className="ga-btn ga-btn-sm ga-btn-primary"
              disabled={busy}
              onClick={() => run(clip, { set: value.trim().toLowerCase() })}
            >
              {t('Apply')}
            </button>
            <button type="button" className="ga-btn ga-btn-sm" onClick={() => setAction(null)}>
              {t('Cancel')}
            </button>
            {replaceNode(clip)}
          </div>
        ) : null}

        {open === 'library' ? (
          <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginTop: 6, flexWrap: 'wrap' }}>
            <span style={{ fontSize: '0.82em' }}>
              {other === 'free'
                ? t('Move to the free library? Everything there is committed to git — only do this when the licence allows passing the raw file on.')
                : t('Move to the licensed library? It stays local and is never committed.')}
            </span>
            <button
              type="button"
              className="ga-btn ga-btn-sm ga-btn-primary"
              disabled={busy}
              onClick={() => run(clip, { library: other })}
            >
              {t('Move')}
            </button>
            <button type="button" className="ga-btn ga-btn-sm" onClick={() => setAction(null)}>
              {t('Cancel')}
            </button>
            {replaceNode(clip)}
          </div>
        ) : null}

        {open === 'delete' ? (
          <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginTop: 6, flexWrap: 'wrap' }}>
            <span style={{ fontSize: '0.82em' }}>
              {clip.role
                ? t('Delete this file? It is one half of a pair — both halves go together.')
                : t('Delete this file?')}
              {usage[clip.kind]?.length
                ? ` ${t('Poses that play this kind')}: ${usage[clip.kind].join(', ')}`
                : ''}
            </span>
            <button
              type="button"
              className="ga-btn ga-btn-sm ga-btn-danger"
              disabled={busy}
              onClick={() => run(clip, null)}
            >
              {t('Delete')}
            </button>
            <button type="button" className="ga-btn ga-btn-sm" onClick={() => setAction(null)}>
              {t('Cancel')}
            </button>
          </div>
        ) : null}
      </li>
    )
  }

  const dialLabel = (text: string) => <span style={DIAL_LABEL} title={text}>{text}</span>
  // A165: the column's tabs — a solo clip has only its own dials; a pair/group adds partner, contacts, bend, check.
  const multi = isPairTarget || isGroupTarget
  const alignTabs: [AlignTab, string][] = [['clip', t('Clip')],
    ...(multi ? [['partner', t('Roles')], ['contacts', t('Contacts')],
      ['bend', t('Bend & root angle')], ['check', t('Check')]] as [AlignTab, string][] : [])]
  const shownAlignTab: AlignTab = alignTabs.some(([id]) => id === alignTab) ? alignTab : 'clip'
  // The 3D view and the column fit the window, so the view stays in sight while a dial moves (A165).
  const previewH = Math.max(300, Math.min(600, viewH - PAGE_CHROME_PX))
  const colMaxH = Math.max(320, viewH - COL_TOP_PX)
  const usedCount = row?.used.length ?? 0
  const fileCount = row ? row.clips.length : 0

  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: '280px minmax(0, 1fr)',
        gap: 12,
        alignItems: 'stretch',
        flex: 1,
        minHeight: 0,
        fontSize: 13,
        // the Help / Translate side tabs sit over the right edge of the page
        paddingRight: 34,
      }}
    >
      {/* ── the list: one row per kind, lamp first, sets as letters ── */}
      <section style={{ display: 'flex', flexDirection: 'column', gap: 6, minWidth: 0, minHeight: 0 }}>
        <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
          <input
            className="ga-input"
            style={{ flex: 1, minWidth: 0 }}
            placeholder={t('Search kind…')}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <button
            type="button"
            className="ga-btn ga-btn-sm"
            disabled={refreshing}
            onClick={() => void refresh()}
            title={t('Re-read the clip libraries from disk')}
          >
            {t('Refresh')}
          </button>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 4 }}>
          <select className="ga-input" style={FILTER} value={libFilter} onChange={(e) => setLibFilter(e.target.value)}
            title={t('Library')}>
            <option value="">{t('all libraries')}</option>
            <option value="free">{t('free')}</option>
            <option value="licensed">{t('licensed')}</option>
            <option value="studio">{t('studio only')}</option>
          </select>
          <select className="ga-input" style={FILTER} value={setFilter} onChange={(e) => setSetFilter(e.target.value)}
            title={t('Set')}>
            <option value="*">{t('all sets')}</option>
            {columns.map((s) => (
              <option key={s || 'neutral'} value={s}>
                {`${setLetter(s)} = ${s || t('neutral')}`}
              </option>
            ))}
          </select>
          <select className="ga-input" style={FILTER} value={onlyUsed ? 'used' : onlyUnused ? 'unused' : ''}
            onChange={(e) => { setOnlyUsed(e.target.value === 'used'); setOnlyUnused(e.target.value === 'unused') }}>
            <option value="">{t('used or not')}</option>
            <option value="used">{t('only used')}</option>
            <option value="unused">{t('only unused')}</option>
          </select>
          <select className="ga-input" style={{ ...FILTER, gridColumn: '1 / -1' }} value={statusFilter} data-testid="clip-status-filter"
            title={t('Alignment status of pair and group clips (the worst contact of the clip)')}
            onChange={(e) => setStatusFilter(e.target.value)}>
            <option value="">{t('any alignment status')}</option>
            {STATUS_KEYS.map((k) => (
              <option key={k} value={k}>{`${stateWord(t, k)} (${statusCounts[k] ?? 0})`}</option>
            ))}
          </select>
        </div>
        <div className="ga-form-hint" style={{ margin: 0, display: 'flex', flexWrap: 'wrap', gap: '0 8px' }} data-testid="clip-status-counts"
          data-counts={JSON.stringify(statusCounts)}>
          {STATUS_KEYS.filter((k) => statusCounts[k]).map((k) => (
            <span key={k} style={{ color: STATE_COLOR[k], cursor: 'pointer' }} onClick={() => setStatusFilter(statusFilter === k ? '' : k)}>
              {`${stateWord(t, k)} ${statusCounts[k]}`}</span>
          ))}
        </div>
        <div className="ga-form-hint" style={{ margin: 0 }}
          title={t('Every installed clip by kind, set and library. A licensed file hides a free one of the same name: only the licensed one is listed and only it is played. A row without any clip is named by a pose but backed by no file — figures fall back to idle there.')}>
          {`${shown.length} ${t('kinds')} · ${t('lamp: green = checked on a place, yellow = not checked, grey = no sidecar')}`}
        </div>
        <div ref={tableRef} data-testid="clip-list"
          style={{ overflow: 'auto', minHeight: 0, flex: 1, borderTop: '1px solid var(--border, #30363d)' }}>
          {!shown.length ? <div className="ga-placeholder">{t('No clips')}</div> : null}
          {shown.map((r) => (
            <div
              key={r.kind}
              data-kind={r.kind}
              onClick={() => guardSwitch(() => pick(r.kind))}
              style={{
                display: 'flex', gap: 6, alignItems: 'center', padding: '3px 4px', cursor: 'pointer',
                borderBottom: '1px solid var(--border, #21262d)',
                background: r.kind === selected ? 'var(--bg-secondary, #21262d)' : undefined,
              }}
            >
              {r.missing
                ? <LampDot lamp="grey" title={t('missing')} />
                : <LampDot lamp={kindLamp(r.clips)} title={lampText(r.clips.find((c) => clipLamp(c) !== 'green' && (c.role || '') !== 'b') || r.clips[0])} />}
              <code title={r.kind} style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                fontSize: 12, color: r.missing ? 'var(--warn, #d29922)' : undefined }}>
                {r.kind}
              </code>
              {r.roles > 2 ? (
                <span className="ga-tag" style={{ padding: '0 4px', fontSize: 11 }} title={t('Group animation — one figure per role')}>
                  {r.roles}
                </span>
              ) : r.pair ? (
                <span className="ga-tag" style={{ padding: '0 4px', fontSize: 11 }} title={t('Pair animation — needs a partner')}>
                  {t('pair')}
                </span>
              ) : null}
              {r.missing ? (
                <span className="ga-tag ga-tag-missing" style={{ padding: '0 4px', fontSize: 11 }}>{t('missing')}</span>
              ) : null}
              <StatusBadge clips={r.clips} />
              <span style={{ display: 'inline-flex', gap: 2 }}>{setMarks(r)}</span>
              <span style={{ width: 18, textAlign: 'right', opacity: 0.75, fontSize: 11 }}
                title={r.used.length ? `${t('Used by')}: ${r.used.join(', ')}` : t('No pose entry plays this kind.')}>
                {r.used.length || ''}
              </span>
            </div>
          ))}
        </div>
      </section>

      {/* ── the selected kind: header, inner sub-tabs, the alignment column beside the viewer ── */}
      <section style={{ minWidth: 0, minHeight: 0, overflowY: 'auto', paddingRight: 4 }}>
        {!row ? (
          <div className="ga-placeholder">{t('Pick a kind to see its files.')}</div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }} data-testid="clip-head">
              <strong style={{ fontSize: 15 }}>{row.kind}</strong>
              {row.roles > 2 ? <span className="ga-tag">{t('group')} {row.roles}</span>
                : row.pair ? <span className="ga-tag">{t('pair')}</span> : null}
              {rowSets.map((s) => (
                <button
                  key={s || 'neutral'}
                  type="button"
                  className={`ga-btn ga-btn-sm${previewSet === s ? ' ga-btn-primary' : ''}`}
                  disabled={orientBusy || heightBusy}
                  title={t('Set the viewer and the dials act on')}
                  onClick={() => guardSwitch(() => { resetDials(); setPreviewSet(s) })}
                >
                  {s || t('neutral')}
                </button>
              ))}
              {orientTarget ? (
                <span style={{ display: 'inline-flex', gap: 5, alignItems: 'center', fontSize: 12 }} data-testid="orientation-check">
                  <LampDot lamp={clipLamp(orientTarget)} />
                  <span>{lampText(orientTarget)}</span>
                </span>
              ) : null}
              {orientTarget?.role === 'a' && orientTarget.align_status ? (
                <span style={{ display: 'inline-flex', gap: 5, alignItems: 'center', fontSize: 12 }} data-testid="clip-align-status"
                  data-status={JSON.stringify(orientTarget.align_status)}>
                  <StatusBadge clips={[orientTarget]} long />
                  <label style={{ display: 'inline-flex', gap: 3, alignItems: 'center' }}
                    title={t('Your own tick that this clip is aligned. Later Auto-align runs keep it, and Align all skips the clip unless told to include it.')}>
                    <input type="checkbox" data-testid="clip-align-done" checked={orientTarget.align_status.done} disabled={busy}
                      onChange={(e) => { void run(orientTarget, { align_status: { done: e.target.checked } }) }} />
                    {t('manual: done')}
                  </label>
                </span>
              ) : null}
              <span style={{ marginLeft: 'auto', fontSize: 12, opacity: 0.8 }} data-testid="clip-built">
                {builtText(orientTarget)}
              </span>
            </div>

            {error ? (
              <div className="ga-form-hint" style={{ color: 'var(--danger, #f85149)', margin: 0 }}>{error}</div>
            ) : null}

            <nav className="ga-subtabs" style={{ display: 'flex', gap: 4 }}>
              {([
                ['places', t('Places')],
                ['clip', t('Clip')],
                ['files', `${t('Files')} (${fileCount})`],
                ['used', `${t('Used by')} (${usedCount})`],
              ] as const).map(([id, label]) => (
                <button key={id} type="button" data-testid={`inner-tab-${id}`}
                  className={`ga-btn ga-btn-sm${innerTab === id ? ' ga-btn-primary' : ''}`}
                  aria-pressed={innerTab === id}
                  onClick={() => { setInnerTab(id); if (id !== 'places') setPlaceReadout(null) }}>
                  {label}
                </button>
              ))}
            </nav>

            {row.missing ? (
              <div className="ga-form-hint" style={{ color: 'var(--warn, #d29922)' }}>
                {t('No file for this kind in any set — import one, or point the poses above at another kind.')}
              </div>
            ) : null}

            <div style={{ display: 'grid', gridTemplateColumns: orientTarget ? 'minmax(0, 1fr) 320px' : 'minmax(0, 1fr)', gap: 8, alignItems: 'start' }}>
              <div style={{ minWidth: 0, position: 'sticky', top: 0, zIndex: 1 }} data-testid="clip-viewer">
                {innerTab === 'places' && !row.missing ? (
                  /* A110 phase 2: the clip on a prop's places, through the shared per-figure runtime. */
                  <PlacePreview kind={row.kind} set={previewSet} roles={row.roles ?? 0} clips={row.clips}
                    draftRef={draftRef} draftSeq={alignmentDraft} bust={seq} height={previewH}
                    poses={poses.filter((p) => (p.animation || '').trim() === row.kind)}
                    onOpenPose={onOpenPose} onReadout={setPlaceReadout} autoAlignRef={autoAlignRef} castRef={castRef}
                    realHeights={realHeights} onRealHeights={setRealHeights}
                    />
                ) : null}
                {innerTab === 'clip' && !row.missing ? (
                  <ClipPreview
                    key={`${row.kind}:${previewSet}:${seq}`}
                    kind={row.kind}
                    set={previewSet}
                    height={previewH}
                    importYaw={yawDeg}
                    importTilt={tiltDeg}
                    importRoll={rollDeg}
                    importHeightM={heightCm / 100}
                    shiftCm={clipShift}
                    roleShiftM={alignmentDraft.roleShiftM && Object.keys(alignmentDraft.roleShiftM).length
                      ? alignmentDraft.roleShiftM as Record<string, [number, number, number]> : undefined}
                    footprint={footprint}
                    rootDrop={footprint ? (rootDropOf?.(footprint) ?? 0) : 0}
                    bust={seq}
                  />
                ) : null}
                {innerTab === 'files' ? (
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(380px, 1fr))', gap: '0 14px' }}>
                    {rowSets.map((s) => (
                      <div key={s || 'neutral'}>
                        <div style={COL_HEAD}>{s || t('neutral')}</div>
                        <ul className="ga-list" style={{ minWidth: 0 }}>
                          {row.clips.filter((c) => (c.set || '') === s).map(clipNode)}
                        </ul>
                      </div>
                    ))}
                  </div>
                ) : null}
                {innerTab === 'used' ? (
                  row.used.length ? (
                    <ul className="ga-list">
                      {row.used.map((u) => {
                        const isPose = poses.some((p) => p.key === u)
                        return (
                          <li key={u} style={{ display: 'flex', gap: 8, alignItems: 'center', padding: '3px 0' }}>
                            <span className="ga-tag" style={{ fontSize: 11 }}>{isPose ? t('pose') : t('transition')}</span>
                            <code>{u}</code>
                            {isPose && onOpenPose ? (
                              <button type="button" className="ga-btn ga-btn-sm" onClick={() => onOpenPose(u)}>
                                {t('Open entry →')}
                              </button>
                            ) : null}
                          </li>
                        )
                      })}
                    </ul>
                  ) : <div className="ga-placeholder">{t('No pose entry plays this kind.')}</div>
                ) : null}
              </div>

              {/* ── the alignment column, beside the viewer: every drag moves the figures live ── */}
              {orientTarget ? (
                <div data-testid="align-col" className="ga-align-col"
                  style={{ border: '1px solid var(--border, #30363d)', borderRadius: 6, padding: '4px 6px',
                    display: 'flex', flexDirection: 'column', gap: 2, fontSize: 12, position: 'sticky', top: 0,
                    maxHeight: colMaxH, overflowY: 'auto' }}
                  title={orientTarget.has_sidecar === false
                    ? t('Without a sidecar there is nowhere to store the flag — import the clip again.')
                    : undefined}>
                  <div style={{ display: 'flex', gap: 6, alignItems: 'baseline' }}>
                    <strong style={{ fontSize: 13 }}>{t('Alignment')}</strong>
                    <span className="ga-form-hint" style={{ margin: 0 }}
                      title={t('Apply orientation writes angles into the clip file and saves horizontal shifts separately. Surface heights are saved separately and also apply in game. Both halves of a pair stay together.')}>
                      {orientDirty || heightDirty ? t('draft — the viewer shows it live') : t('saved state')}
                    </span>
                  </div>
                  <nav className="ga-subtabs" data-testid="align-tabs" style={{ display: 'flex', gap: 2, flexWrap: 'wrap' }}>
                    {alignTabs.map(([id, label]) => (
                      <button key={id} type="button" data-testid={`align-tab-${id}`}
                        className={`ga-btn ga-btn-sm${alignTab === id ? ' ga-btn-primary' : ''}`}
                        aria-pressed={alignTab === id}
                        onClick={() => setAlignTab(id)}>{label}</button>
                    ))}
                  </nav>
                  {shownAlignTab === 'clip' ? (<>
                  <div style={COL_HEAD}>{t('Rotation')}</div>
                  <SliderInput label={dialLabel(t('Turn'))} unit="°"
                    title={t('Degrees the clip turns about the vertical — the import dial, applied after the fact. A lying clip is aimed at the bed with it.')}
                    min={-180} max={180} step={5} fineStep={1} value={yawDeg} onChange={setYawDeg}
                    disabled={orientLocked} {...DIAL} />
                  <div style={{ display: 'flex', gap: 4, paddingLeft: 80 }}>
                    <button type="button" className="ga-btn ga-btn-sm" disabled={orientLocked}
                      onClick={() => setYawDeg((v) => ((v - 90 + 540) % 360) - 180)}>−90°</button>
                    <button type="button" className="ga-btn ga-btn-sm" disabled={orientLocked}
                      onClick={() => setYawDeg((v) => ((v + 90 + 540) % 360) - 180)}>+90°</button>
                  </div>
                  <SliderInput label={dialLabel(t('Tilt'))} unit="°"
                    title={t('Degrees the clip tips forward — a standing figure bows, a lying one rolls onto its face. Positive tips the head towards the clip’s forward axis.')}
                    min={-180} max={180} step={5} fineStep={1} value={tiltDeg} onChange={setTiltDeg}
                    disabled={orientLocked} {...DIAL} />
                  <SliderInput label={dialLabel(t('Roll'))} unit="°"
                    title={t('Degrees the clip tips sideways. Positive tips the figure to its own right.')}
                    min={-180} max={180} step={5} fineStep={1} value={rollDeg} onChange={setRollDeg}
                    disabled={orientLocked} {...DIAL} />
                  <div style={COL_HEAD}>{t('Position')}</div>
                  {([['Shift sideways', 0], ['Shift forward', 1]] as const).map(([label, axis]) => (
                    <SliderInput key={label} label={dialLabel(t(label))} unit="cm"
                      title={t('Moves the whole clip, including both pair halves. Positive sideways is the clip’s left (+X); positive forward is +Z. Applied horizontally at the place’s yaw, independently of turn, tilt and roll.')}
                      min={-200} max={200} step={5} fineStep={1} value={clipShift[axis]}
                      onChange={(cm) => setClipShift((prev) => axis === 0 ? [cm, prev[1]] : [prev[0], cm])}
                      disabled={orientLocked} {...DIAL} />
                  ))}
                  <label style={{ display: 'flex', gap: 6, alignItems: 'center' }}
                    title={t('Which surface the height dial corrects; the Clip tab draws that surface as the box to turn against.')}>
                    {dialLabel(t('Surface'))}
                    <select className="ga-input" style={{ flex: 1, minWidth: 0, fontSize: 12 }} value={footprint}
                      disabled={orientBusy || heightBusy} onChange={(e) => setFootprint(e.target.value)}>
                      <option value="">{t('ground (grid only)')}</option>
                      <option value="lie">{t('bed / lying surface')}</option>
                      <option value="seat">{t('seat')}</option>
                    </select>
                  </label>
                  <SliderInput label={dialLabel(t('Height'))} unit="cm"
                    title={t('Absolute height correction for the selected surface only. Other surface types keep their own values.')}
                    min={-50} max={50} step={1} value={heightCm}
                    onChange={(cm) => setHeightDraft((prev) => ({ ...prev, [heightGroup]: cm }))}
                    disabled={heightLocked} {...DIAL} />
                  </>) : null}
                  {(isPairTarget || isGroupTarget) && orientTarget ? (
                    <>
                      {shownAlignTab === 'contacts' ? (
                      <ContactRelations roles={(['a', 'b', 'c', 'd', 'e'] as const).slice(0, row?.roles ?? 2)}
                        saved={savedContacts} draft={contactDraft} onDraft={setContactDraft} busy={busy}
                        onSave={(next) => { void run(orientTarget, { contact_target: next }) }} />
                      ) : null}
                      {shownAlignTab === 'bend' ? (<>
                      <BendLimitsEditor saved={savedBend} draft={bendDraft} onDraft={setBendDraft} busy={busy}
                        onSave={(next) => { void run(orientTarget, { bend_limits: next }) }} />
                      <RootAngleEditor saved={savedRoot} draft={rootDraft} onDraft={setRootDraft} busy={busy}
                        onSave={(next) => { void run(orientTarget, { root_angle: next }) }} />
                      </>) : null}
                      {shownAlignTab === 'check' ? (<>
                      <div style={{ display: 'flex', gap: 4, alignItems: 'center', flexWrap: 'wrap' }}>
                      <select data-testid="align-relation" value={alignPickShown} disabled={orientLocked || alignChoices.length < 2}
                        title={t('The contact one Auto-align click aligns: the part role → the receiving role, and the target.')}
                        onChange={(e) => setAlignPick(Number(e.target.value))} style={{ fontSize: 11, maxWidth: 160 }}>
                        {alignChoices.map((c, i) => <option key={i} value={i}>{c.label}</option>)}
                      </select>
                      <select data-testid="align-mover" value={alignMover} disabled={orientLocked}
                        title={t('Which of the two roles Auto-align moves for this contact; every other role stays where it is. Auto moves the part’s role and, when that run is blocked (discarded, a cap hit short of the deepest frame’s conditions, or held by the posture), tries the receiving role too and keeps the better result.')}
                        onChange={(e) => setAlignMover(e.target.value as AlignMoverChoice)} style={{ fontSize: 11 }}>
                        <option value="auto">{t('Auto')}</option>
                        <option value="part">{alignChoice?.rel
                          ? t('move {r} (part)').replace('{r}', alignChoice.rel.part.toUpperCase()) : t('move the part’s role')}</option>
                        <option value="receiver">{alignChoice?.rel
                          ? t('move {r} (receiving)').replace('{r}', alignChoice.rel.at.toUpperCase()) : t('move the receiving role')}</option>
                      </select>
                      <button type="button" className="ga-btn ga-btn-sm" data-testid="align-auto"
                        disabled={orientLocked || innerTab !== 'places' || realHeights}
                        title={realHeights ? t('Switch “Real heights” off: Auto-align measures and stores the arrangement of 1.70 m figures.')
                          : innerTab !== 'places'
                          ? t('Open the Places view: Auto-align measures the figures shown there.')
                          : t('Aligns the chosen contact by moving the chosen role (at most the alignment range in every direction and the rotation range in tilt, roll and yaw, around the arrangement you set, staying on its seat or bed) and the part’s root angle: at the deepest frame the part goes in as far as it can — its root just outside the opening, or less when the bottom stops the tip — and at both the deepest and the shallowest frame the shaft runs along the axis through the opening. The moved role may not go deeper into any other person than the clip already does (at least 5 mm allowed); a result that would, or that ends worse than it started, is not applied. Every other role stays. Writes the role and root-angle dials and measures the contact pivot; Save stores them.')}
                        onClick={() => {
                          const run = autoAlignRef.current
                          const res: AutoAlignResult = run ? run({ rangeCm: alignRangeCm, turnDeg: alignTurnDeg, base: alignBase,
                            only: alignChoice?.rel ?? 'detected', mover: alignMover }) : { ok: false, reason: t('The place preview is still loading.') }
                          setAutoAlign(res)
                          // Owner decision 2026-11-25: the contact heights of the arrangement the dials will hold — applied or
                          // not (an unchanged result measured the arrangement as it is); Save stores them.
                          if (res.ok) setContactHeightsDraft(res.contactHeights)
                          // A STATUS PER CLIP: what the click measured. A discarded result changes no dial, so its status
                          // (blocked, mismatch, not measurable) is stored at once; an applied one when Save stores it.
                          const statusNow: Record<string, AlignStatusEntry | null> = {}
                          if (!res.ok) { if (res.code) statusNow[UNMEASURED_KEY] = unmeasuredStatus(res.code) }
                          else for (const x of res.relations) if (!x.applied) statusNow[x.key] = relationStatus(x)
                          if (Object.keys(statusNow).length && orientTarget.role === 'a') {
                            if (Object.keys(statusNow).some((k) => k !== UNMEASURED_KEY)) statusNow[UNMEASURED_KEY] = null
                            void apiPatch(clipPath(orientTarget), { align_status: { relations: statusNow } })
                              .then(() => onReload()).catch((e) => setOrientError((e as Error).message))
                          }
                          // THE VERDICT: a discarded or unchanged result writes nothing — the dials stay as they were.
                          if (!res.ok || !res.applied) return
                          // Ruling A212 (2026-11-20): Auto-align writes the clip's root angle to its dials (a draft).
                          if (res.rootAngle) setRootDraft({ pitch_deg: res.rootAngle.pitchDeg, yaw_deg: res.rootAngle.yawDeg })
                          // Owner decision 2026-11-20: and the contact pivot it measured (Save stores it).
                          setPivotDraft(res.pivotCm)
                          // Only the role that moved changes, its shift and its turn.
                          const turns: Record<string, [number, number, number]> = { ...roleTurn }
                          for (const [r, v] of Object.entries(res.roleTurnDeg)) turns[r] = [+v[0].toFixed(1), +v[1].toFixed(1), +v[2].toFixed(1)]
                          autoWrite.current = dialKey(turns, res.roleShiftCm)
                          pendingStatus.current = { key: statusKey(orientTarget), dials: autoWrite.current,
                            relations: Object.fromEntries(res.relations.filter((x) => x.applied).map((x) => [x.key, relationStatus(x)])) }
                          setRoleShift(res.roleShiftCm)
                          setRoleTurn(turns)
                          const moved = res.movers.find((m) => m.applied)
                          if (moved) setShiftRole(moved.role)
                        }}>
                        {t('Auto-align')}
                      </button>
                      <label style={{ display: 'flex', gap: 3, alignItems: 'center', fontSize: 11 }}
                        title={t('How far Auto-align may move a role around your arrangement, the same in every direction. Stored in this clip’s sidecar; default 8 cm.')}>
                        {t('Alignment range')}
                        <input type="number" min={1} max={40} step={1} value={alignRangeCm} data-testid="align-range"
                          style={{ width: 48 }} disabled={orientLocked}
                          onChange={(e) => setAlignRangeDraft(Math.max(1, Math.min(40, Number(e.target.value) || 8)))} /> cm
                        {alignRangeDirty ? <span style={{ color: 'var(--warning, #d29922)' }}>{t('unsaved')}</span>
                          : <span style={{ opacity: 0.7 }}>{orientTarget.align_range?.source === 'clip' ? t('saved') : t('default')}</span>}
                        <button type="button" className="ga-btn ga-btn-sm" data-testid="align-range-save" disabled={!alignRangeDirty || busy}
                          onClick={() => { void run(orientTarget, { align_range_cm: alignRangeCm }) }}>{t('Save')}</button>
                      </label>
                      <label style={{ display: 'flex', gap: 3, alignItems: 'center', fontSize: 11 }}
                        title={t('How far Auto-align may turn the moved role around your arrangement — tilt, roll and yaw each, about its hips (a standing role keeps its tilt and roll within 3°). 0 = shift only. Stored in this clip’s sidecar; default {d}°.').replace('{d}', String(ALIGN_TURN_DEG_DEFAULT))}>
                        {t('Rotation range')}
                        <input type="number" min={0} max={180} step={5} value={alignTurnDeg} data-testid="align-turn"
                          style={{ width: 48 }} disabled={orientLocked}
                          onChange={(e) => setAlignTurnDraft(Math.max(0, Math.min(180, Number(e.target.value) || 0)))} /> °
                        {alignTurnDirty ? <span style={{ color: 'var(--warning, #d29922)' }}>{t('unsaved')}</span>
                          : <span style={{ opacity: 0.7 }}>{orientTarget.align_turn?.source === 'clip' ? t('saved') : t('default')}</span>}
                        <button type="button" className="ga-btn ga-btn-sm" data-testid="align-turn-save" disabled={!alignTurnDirty || busy}
                          onClick={() => { void run(orientTarget, { align_turn_deg: alignTurnDeg }) }}>{t('Save')}</button>
                      </label>
                      </div>
                      <button type="button" className="ga-btn ga-btn-sm" data-testid="align-finales"
                        disabled={innerTab !== 'places' || !finaleKinds.length || unsaved || orientBusy || heightBusy || !!finaleRun?.running}
                        title={!finaleKinds.length ? t('This clip has no end clip beside it.')
                          : unsaved ? t('Save this clip first: the end clips are aligned to the saved base.')
                            : t('Aligns each end clip ({kinds}) with this clip’s contact relations and joins its first frame to where this clip’s last frame leaves the figures, within the same range; then stores each end clip’s result (one Blender run each, no hub jobs).').replace('{kinds}', finaleKinds.join(', '))}
                        onClick={() => guardSwitch(() => { void runAlignFinales() })}>
                        {finaleRun?.running ? t('Aligning end clips… ({n} done)').replace('{n}', String(finaleRun.rows.length))
                          : t('Also align end clips ({n})').replace('{n}', String(finaleKinds.length))}
                      </button>
                      {finaleRun?.rows.length ? (
                        <table data-testid="align-finales-result" data-result={JSON.stringify(finaleRun.rows)}
                          style={{ borderCollapse: 'collapse', fontSize: 11 }}>
                          <tbody>{finaleRun.rows.map((x) => (
                            <tr key={x.kind}>
                              <td style={{ paddingRight: 6 }}>{x.kind}</td>
                              {x.result.ok ? (
                                <>
                                  <td style={{ whiteSpace: 'nowrap' }}><LampDot lamp={x.result.lamp} title={t('Contact')} />
                                    <LampDot lamp={x.result.movers[0]?.lamp ?? 'green'} title={t('Within the alignment range')} /></td>
                                  <td style={{ padding: '0 4px' }}>{x.result.movers.map((m) => `${m.role.toUpperCase()} ${m.shiftCm.map((v) => v.toFixed(1)).join(' / ')} cm`).join(', ')}</td>
                                  <td style={{ color: x.error ? 'var(--danger, #f85149)' : undefined }}>{x.error || x.note || (x.saved ? t('saved') : '')}</td>
                                </>
                              ) : <td colSpan={3} style={{ color: 'var(--danger, #f85149)' }}>{x.result.reason}</td>}
                            </tr>
                          ))}</tbody>
                        </table>
                      ) : null}
                      <button type="button" className="ga-btn ga-btn-sm" data-testid="align-all"
                        disabled={innerTab !== 'places' || orientBusy || heightBusy || alignAll?.running === 'apply'}
                        title={t('Stage 1 of Align all: measures every pair and group clip in the list, relation by relation, with the persons each clip’s Places view fills in, and sorts each contact into would improve / blocked / geometry mismatch. Nothing is written; stage 2 applies and saves only the rows you leave ticked.')}
                        onClick={() => { if (alignAll?.running) alignAllStop.current = true; else guardSwitch(() => { void runAlignAll() }) }}>
                        {alignAll?.running ? t('Stop ({n} of {m} clips)').replace('{n}', String(alignAll.done)).replace('{m}', String(alignAll.total))
                          : t('Measure all pair and group clips ({n})').replace('{n}', String(shown.filter((r) => (r.roles ?? 0) >= 2 && !r.missing
                            && (includeDone || kindStatus(r.clips).key !== 'done')).length))}
                      </button>
                      <button type="button" className="ga-btn ga-btn-sm" data-testid="align-all-store-heights"
                        disabled={innerTab !== 'places' || orientBusy || heightBusy || !!alignAll?.running}
                        title={t('Measures and stores the contact heights of every pair and group clip in the list, as it is stored now (nothing is aligned or moved): per contact the height of its target at the deepest frame and both roles’ legs there, at 1.70 m. The game closes the vertical gap of figures of other heights from them; a clip without them is not compensated.')}
                        onClick={() => { if (heightsRun?.running) alignAllStop.current = true; else guardSwitch(() => { void storeAllHeights() }) }}>
                        {heightsRun?.running ? t('Stop ({n} of {m} clips)').replace('{n}', String(heightsRun.done)).replace('{m}', String(heightsRun.total))
                          : t('Store contact heights')}
                      </button>
                      {heightsRun && !heightsRun.running ? (
                        <span className="ga-hint" data-testid="align-all-heights-result" data-result={JSON.stringify(heightsRun)} style={{ fontSize: 11 }}>
                          {t('Contact heights stored for {n} of {m} clips.').replace('{n}', String(heightsRun.stored)).replace('{m}', String(heightsRun.total))}
                          {heightsRun.missed.length ? ` ${t('Nothing measured: {kinds}').replace('{kinds}', heightsRun.missed.join(', '))}` : ''}
                        </span>
                      ) : null}
                      <label style={{ display: 'flex', gap: 4, alignItems: 'center', fontSize: 11 }}
                        title={t('Align all skips clips ticked “manual: done” unless this is ticked.')}>
                        <input type="checkbox" data-testid="align-all-include-done" checked={includeDone} disabled={!!alignAll?.running}
                          onChange={(e) => setIncludeDone(e.target.checked)} />
                        {t('include clips marked manual: done')}
                      </label>
                      {alignAll?.rows.length ? (
                        <AlignAllTable rows={alignAll.rows} busy={!!alignAll.running}
                          onTick={(i, on) => setAlignAll((p) => p && ({ ...p, rows: p.rows.map((r, k) => (k === i ? { ...r, tick: on } : r)) }))}
                          onChoice={(i, c) => setAlignAll((p) => p && ({ ...p, rows: p.rows.map((r, k) => (k === i ? { ...r, choice: c } : r)) }))}
                          onRemeasure={(i) => guardSwitch(() => { void remeasureAll(i) })}
                          onOpen={(i) => { const r = alignAll.rows[i]; guardSwitch(() => pick(r.kind, r.set)) }}
                          onApply={() => guardSwitch(() => { void applyAlignAll() })} />
                      ) : null}
                      {autoAlign ? (
                        <AlignResultBlock result={autoAlign} />
                      ) : null}
                      </>) : null}
                    </>
                  ) : null}
                  {(isGroupTarget || isPairTarget) && shownAlignTab === 'partner' ? (
                    <>
                      <div style={{ ...COL_HEAD, display: 'flex', gap: 4, alignItems: 'center', flexWrap: 'wrap' }}
                        title={t('Moves the selected role against the others in the clip files — its own half and its alt halves. Forward is the clip’s forward axis, side positive is its left.')}>
                        <span>{t('Move a role')}</span>
                        {shiftRoles.map((r) => {
                          const moved = (roleShift[r] || [0, 0, 0]).some((v) => v !== 0)
                          return (
                            <button key={r} type="button"
                              className={`ga-btn ga-btn-sm${shiftRole === r ? ' ga-btn-primary' : ''}`}
                              style={{ borderColor: ROLE_COLOR[r], minWidth: 30 }}
                              aria-pressed={shiftRole === r}
                              disabled={orientLocked}
                              onClick={() => setShiftRole(r)}>
                              <span style={{ color: shiftRole === r ? undefined : ROLE_COLOR[r] }}>{r.toUpperCase()}</span>
                              {moved ? ' •' : ''}
                            </button>
                          )
                        })}
                      </div>
                      {([['Forward', 2], ['Side', 0], ['Up', 1]] as const).map(([label, axis]) => (
                        <SliderInput key={label} label={dialLabel(`${shiftRole.toUpperCase()} · ${t(label)}`)} unit="cm"                          min={-50} max={50} step={1} value={(roleShift[shiftRole] || [0, 0, 0])[axis]}
                          onChange={(cm) => setRoleShift((prev) => {
                            const cur = prev[shiftRole] || [0, 0, 0]
                            const next: [number, number, number] = [cur[0], cur[1], cur[2]]
                            next[axis] = cm
                            return { ...prev, [shiftRole]: next }
                          })}
                          disabled={orientLocked} {...DIAL} />
                      ))}
                      {/* Owner decision 2026-11-23: every role turns about its hips — renderer-only, saved beside the clip. */}
                      {([['Tilt', 0, 'Tips the role’s head towards the clip’s forward axis'], ['Roll', 1, 'Tips the role to its own side'],
                        ['Yaw', 2, 'Turns the role about its own vertical axis; positive turns its forward towards its left']] as const).map(([label, axis, hint]) => {
                        const saved = (savedRoleTurn[shiftRole] ?? [0, 0, 0])[axis]
                        const draft = (roleTurn[shiftRole] ?? [0, 0, 0])[axis]
                        return (
                          <SliderInput key={label} label={dialLabel(`${shiftRole.toUpperCase()} · ${t(label)}`)} unit="°"
                            title={`${t(hint)}. ${t('Turns the role about its hips, before its shift — renderer-only, saved beside the clip; the dial shows the saved value plus the draft.')}`}
                            min={-180} max={180} step={1} fineStep={0.1} value={wrapDeg(saved + draft)}
                            onChange={(v) => setRoleTurn((prev) => {
                              const cur = prev[shiftRole] || [0, 0, 0]
                              const next: [number, number, number] = [cur[0], cur[1], cur[2]]
                              next[axis] = wrapDeg(v - saved)
                              return { ...prev, [shiftRole]: next }
                            })}
                            disabled={orientLocked} {...DIAL} />
                        )
                      })}
                      <div style={{ display: 'flex', gap: 4, paddingLeft: 80 }}>
                        <button type="button" className="ga-btn ga-btn-sm" data-testid="role-turn-zero"
                          disabled={orientLocked || [0, 1, 2].every((k) => wrapDeg((savedRoleTurn[shiftRole] ?? [0, 0, 0])[k] + (roleTurn[shiftRole] ?? [0, 0, 0])[k]) === 0)}
                          onClick={() => setRoleTurn((prev) => ({ ...prev,
                            [shiftRole]: [0, 1, 2].map((k) => wrapDeg(-((savedRoleTurn[shiftRole] ?? [0, 0, 0])[k]))) as [number, number, number] }))}>
                          {t('{r} turn 0°').replace('{r}', shiftRole.toUpperCase())}</button>
                        <button type="button" className="ga-btn ga-btn-sm" disabled={orientLocked}
                          onClick={() => setRoleTurn((prev) => {
                            const cur = prev[shiftRole] || [0, 0, 0]
                            return { ...prev, [shiftRole]: [cur[0], cur[1], wrapDeg(cur[2] + 180)] }
                          })}>{t('yaw 180°')}</button>
                      </div>
                    </>
                  ) : null}

                  {/* THE one save path, its consequence spelled out before the click. */}
                  <div style={{ borderTop: '1px solid var(--border, #30363d)', marginTop: 4, paddingTop: 4,
                    position: 'sticky', bottom: -4, background: 'var(--bg, #0d1117)', paddingBottom: 4 }}
                    data-testid="align-consequence">
                    {saveConsequence.length ? (
                      <ul style={{ margin: '0 0 2px 14px', padding: 0, fontSize: 11 }}>
                        {saveConsequence.map((line) => <li key={line}>{line}</li>)}
                      </ul>
                    ) : (
                      <div className="ga-form-hint" style={{ margin: '0 0 4px' }}>
                        {t('Nothing to save — drag a dial, or make every place read green to store the check.')}
                      </div>
                    )}
                    <div style={{ display: 'flex', gap: 6 }}>
                      <button type="button" data-testid="align-save"
                        className="ga-btn ga-btn-sm ga-btn-primary" disabled={!canSave}
                        title={realHeights ? t('Switch “Real heights” off to save: the dials and the measured values belong to 1.70 m figures.') : undefined}
                        onClick={() => void save()}>
                        {orientBusy || heightBusy ? t('Saving…')
                          : bakeDirty ? t('Save (Blender run)')
                            : checkOnly ? t('Save check') : t('Save')}
                      </button>
                      <button type="button" className="ga-btn ga-btn-sm"
                        disabled={(!orientDirty && !heightDirty) || heightLocked} onClick={resetDials}>
                        {t('Reset dials')}
                      </button>
                      {orientSeconds !== null && !orientBusy ? (
                        <span className="ga-form-hint" style={{ margin: 0 }}>{`${t('written in')} ${orientSeconds.toFixed(1)} s`}</span>
                      ) : null}
                    </div>
                  </div>
                  {finalesTouched.length ? (
                    <div className="ga-form-hint" style={{ margin: 0 }}>
                      {`${t('Its finale clips were changed the same way')}: ${finalesTouched.join(', ')}`}
                    </div>
                  ) : null}
                  <div className="ga-form-hint" style={{ margin: 0 }} title={savedNote}>
                    {orientTarget.has_sidecar === false
                      ? t('Without a sidecar there is nowhere to store the flag — import the clip again.')
                      : `${t('Saved orientation and shifts')}: ${savedNote}`}
                  </div>
                  {orientError ? (
                    <div className="ga-form-hint" style={{ color: 'var(--danger, #f85149)', margin: 0 }}>{orientError}</div>
                  ) : null}
                </div>
              ) : null}
            </div>
          </div>
        )}
      </section>
      <ConfirmDialog open={pendingSwitch !== null} title={t('Discard unsaved changes?')}
        message={t('The open clip has edits that were never saved (dials, heights, contacts, bend limits or root angle). Opening another clip or set discards them.')}
        confirmLabel={t('Discard')} danger
        onConfirm={() => { const fn = pendingSwitch; setPendingSwitch(null); fn?.() }}
        onClose={() => setPendingSwitch(null)} />
    </div>
  )
}

/** "Align all": how long `openRun` waits for a clip's scene and then for its figures (seconds). The clips whose pair was
 *  never filled in run 3 were not slow (owner 2026-11-23): the default fill planned them on the previous clip's places
 *  and a figure-less mount hid the no-place answer (both fixed in PlacePreview); on the clone every clip of the licensed library opened
 *  within 3.8 s (run 4). The waits stay generous for a slow renderer. */
const OPEN_SCENE_S = 120
const OPEN_FIGURES_S = 180
interface OpenWait { s: number; stage: 'ok' | 'no_place' | 'scene' | 'figures'; figures: number }
/** A STATUS PER CLIP: the filter's keys, worst first, and "manual: done" last. */
const STATUS_KEYS: (AlignState | 'not_checked' | 'done')[] = ['auto_mismatch', 'auto_blocked', 'not_measurable', 'not_checked',
  'auto_improved', 'manual_adjusted', 'auto_unchanged', 'auto_aligned', 'done']
/** A kind's status in the list (a solo kind: none). */
function kindStatus(clips: readonly ApiClipRow[]) {
  return kindStatusOf(clips)
}
/** Which clip a pending Auto-align status belongs to. */
function statusKey(c: ApiClipRow): string {
  return `${libraryOf(c)}/${relOf(c)}`
}
/** The status badge of a kind (its A files) — the word, the reason, and the numbers in its tooltip. */
function StatusBadge({ clips, long = false }: { clips: readonly ApiClipRow[]; long?: boolean }) {
  const { t } = useI18n()
  const s = kindStatus(clips)
  if (!s.key) return null
  const word = stateWord(t, s.key)
  const why = s.reasons.map((r) => reasonText(t, r, s.who.join(', ') || undefined)).join(', ')
  // THE START OVERLAP's notes in full (how much, which pair and capsules); the other notes as words.
  const overlapNotes = s.overlap.map((n) => noteText(t, n)).join('; ')
  const notes = [...s.notes.filter((c) => !c.startsWith('overlap_')).map((c) => noteWord(t, c)), ...(overlapNotes ? [overlapNotes] : [])].join(', ')
  const tip = clips.filter((c) => (c.role || '') === 'a' && c.align_status).map((c) => {
    const st = c.align_status!
    const rels = Object.entries(st.relations).map(([k, e]) => {
      const nums = [e.depth_mm ? `${t('depth')} ${e.depth_mm[0]} → ${e.depth_mm[1]} mm` : '',
        e.axis_mm ? `${t('off axis')} ${e.axis_mm[0]} → ${e.axis_mm[1]} mm` : '',
        typeof e.root_mm === 'number' ? `${t('root at')} ${e.root_mm} mm` : '',
        typeof e.support_mm === 'number' ? `${t('support')} ${e.support_mm} mm` : '',
        e.mover ? `${t('moved')} ${e.mover.toUpperCase()}` : '',
        e.turn_deg?.some((v) => v !== 0) ? `${t('turn')} ${e.turn_deg.join(' / ')}°` : '',
        e.at ? e.at.slice(0, 16).replace('T', ' ') : ''].filter(Boolean).join(', ')
      const notesNow = entryNotes(e).map((n) => noteText(t, n)).join('; ')
      return `${k === UNMEASURED_KEY ? '–' : k}: ${stateWord(t, e.state)}${e.reason ? ` (${reasonText(t, e.reason, e.with)})` : ''}${nums ? ` — ${nums}` : ''}${notesNow ? ` · ${notesNow}` : ''}`
    })
    return [`${c.set || t('neutral')}${st.done ? ` · ${t('manual: done')}` : ''}`, ...rels].join('\n')
  }).join('\n\n')
  return (
    <span className="ga-tag" data-testid="clip-status-badge" data-status={s.key} data-notes={s.notes.join(' ')} title={tip}
      style={{ padding: '0 4px', fontSize: 10, whiteSpace: 'nowrap', color: STATE_COLOR[s.key], borderColor: STATE_COLOR[s.key] }}>
      {long ? `${word}${why ? ` (${why})` : ''}${notes ? ` · ${notes}` : ''}` : `${word}${notes ? ' ·' : ''}`}
    </span>
  )
}

/** Ruling A212 review H1: the identity of the dial values the alignment base is read from (`alignBase`). */
function dialKey(turns: Record<string, readonly number[]>, roles: Record<string, readonly number[]>): string {
  const book = (b: Record<string, readonly number[]>) => Object.keys(b).sort().filter((k) => b[k].some((v) => v !== 0)).map((k) => [k, b[k]])
  return JSON.stringify([book(turns), book(roles)])
}

/** Ruling A145: the core default of the bend limits (the server's `BEND_LIMITS_DEFAULT`), until the listing says. */
const BEND_WIRE_DEFAULT: BendLimitsWire = {
  raised: { total_deg: 15 },
  resting: { total_deg: 120 },
}
