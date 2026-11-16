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
 *
 *   PATCH  /assets/animation-clips/{library}/{rel}     {kind?, set?, library?, loop?, loop_count?, overwrite?}
 *   POST   /assets/animation-clips/{library}/{rel}/orient  {yaw_deg?, tilt_deg?, roll_deg?, partner_shift_cm?, role_shift_cm?, shift_cm?}
 *   DELETE /assets/animation-clips/{library}/{rel}
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { bendLimitsOf, clipHeightGroup, type ClipHeightOffsetsCm } from '@anima/scene-render'
import { BendLimitsEditor, ContactRelations } from './ContactRelations'
import { targetWordOf } from './contactWords'
import { PlacePreview, type AutoAlignResult, type AutoAlignRun, type PairCheckResult, type PlaceReadout } from './PlacePreview'
import type { AlignmentDraft, ContactRelation } from '@anima/scene-render'
import { ClipPreview, ROLE_COLOR } from './ClipPreview'
import { invalidateAnimationPreviewClips } from '../characters/Model3DViewer'
import { SliderInput } from '../../components/SliderInput'
import { useI18n } from '../../i18n/I18nProvider'
import { ApiError, apiDelete, apiPatch, apiPost } from '../../lib/api'
import { bridgeKinds, orderSets } from './clipSets'
import type { ApiClipRow as BaseApiClipRow, BendLimitsWire, ClipListing } from './clipSets'
import { rootMotionSummary } from './rootMotion'
import { generatedBadge, isStudioClip } from './generatedClip'
import { clipLamp, finaleKinds as finaleKindsOf, kindLamp, saveSteps, setLetter } from './clipStatus'
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
function LoopCountField({ value, disabled, onApply, t }: {
  value: number | null | undefined
  disabled: boolean
  onApply: (v: number | null) => void
  t: (s: string) => string
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
      title={t('How many times the clip plays before it holds its last frame — for every variant of the kind in this set.')}>
      <span>{t('Repeats')}</span>
      <input
        type="number"
        className="ga-input"
        style={{ width: 70 }}
        min={1}
        max={99}
        step={1}
        value={draft}
        placeholder="∞"
        disabled={disabled}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => { if (e.key === 'Enter') commit() }}
      />
      <span className="ga-form-hint" style={valid ? undefined : { color: 'var(--danger, #f85149)' }}>
        {valid ? t('empty = endless') : t('a whole number from 1 to 99, or empty')}
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
const COL_HEAD = { fontSize: 12, fontWeight: 600, opacity: 0.85, margin: '6px 0 2px' } as const

type InnerTab = 'places' | 'clip' | 'files' | 'used'

export function ClipLibrary({
  listing,
  poses,
  onReload,
  rootDropOf,
  focus,
  onOpenPose,
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
  // A pair's B half against A: [side, up, forward] centimetres, baked like the angles.
  const [partnerShift, setPartnerShift] = useState<[number, number, number]>([0, 0, 0])
  // Ruling A129: partner B's [tilt, roll] degrees about its hips — renderer-only, stored in the sidecar like shift_cm.
  const [partnerTurn, setPartnerTurn] = useState<[number, number]>([0, 0])
  // A group's roles, each against the scene: {role: [side, up, forward]} cm,
  // baked like the partner shift; `shiftRole` is the one the sliders move.
  const [roleShift, setRoleShift] = useState<Record<string, [number, number, number]>>({})
  const [shiftRole, setShiftRole] = useState('a')
  const [clipShift, setClipShift] = useState<[number, number]>([0, 0])
  const [heightDraft, setHeightDraft] = useState<ClipHeightOffsetsCm>({})
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
  /** Ruling A129.6: "Align all" — Auto-align over every pair clip listed, one result per clip, nothing saved. The
   *  results wait per clip (kind|set) and fill the Partner B dials when that clip is opened. */
  const [alignAll, setAlignAll] = useState<{ running: boolean; done: number; rows: { kind: string; set: string
    result: AutoAlignResult }[] } | null>(null)
  const pendingAlign = useRef<Record<string, { shiftCm: [number, number, number]; turnDeg: [number, number]
    roleShiftCm: Record<string, [number, number, number]> }>>({})
  const alignAllStop = useRef(false)
  const [autoAlign, setAutoAlign] = useState<AutoAlignResult | null>(null)
  /** Ruling A129.3: the pair shown before and with the per-pair fine fit the game runs. */
  const pairCheckRef = useRef<(() => PairCheckResult) | null>(null)
  const [pairCheck, setPairCheck] = useState<PairCheckResult | null>(null)
  /** Finale clips the server changed along with the last apply/save. */
  const [finalesTouched, setFinalesTouched] = useState<string[]>([])

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
      return true
    })
  }, [libFilter, onlyUnused, onlyUsed, rows, search, setFilter])

  const row = useMemo(() => rows.find((r) => r.kind === selected) || null, [rows, selected])

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
    setPartnerShift([0, 0, 0])
    setPartnerTurn([0, 0])
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
      // A129.6: an "Align all" result for this clip fills the Partner B dials as a draft (Save stores it).
      const waiting = pendingAlign.current[`${kind}|${nextSet}`]
      if (waiting) {
        setPartnerShift(waiting.roleShiftCm.b ?? waiting.shiftCm); setPartnerTurn(waiting.turnDeg)
        setRoleShift(waiting.roleShiftCm)
      }
      setAction(null)
      setError('')
      setConflict(null)
    },
    [clips, heightBusy, orientBusy, resetDials],
  )

  /** A129.6: Auto-align every pair clip listed, one after the other, on the pair each one's preview fills in. */
  const runAlignAll = useCallback(async () => {
    const targets = shown.filter((r) => (r.roles ?? 0) >= 2 && !r.missing)
    const back = selected
    alignAllStop.current = false
    const out: { kind: string; set: string; result: AutoAlignResult }[] = []
    setAlignAll({ running: true, done: 0, rows: [] })
    const wait = (ms: number) => new Promise((r) => setTimeout(r, ms))
    for (const r of targets) {
      if (alignAllStop.current) break
      const set = orderSets(Array.from(new Set(r.clips.map((c) => c.set || ''))))[0] || ''
      delete pendingAlign.current[`${r.kind}|${set}`]
      pick(r.kind, set)
      let run: AutoAlignRun | null = null
      // The preview of THIS clip with two figures; then a moment for the figures' first frames.
      for (let k = 0; k < 240 && !alignAllStop.current; k++) {
        await wait(500)
        const cur = autoAlignRef.current
        if (cur && cur.kind === r.kind && (cur.set ?? '') === set && (cur.figures ?? 0) >= 2) { run = cur; break }
      }
      await wait(1500)
      const result: AutoAlignResult = run ? run() : { ok: false, reason: t('No pair was filled on a place of this clip.') }
      if (result.ok) pendingAlign.current[`${r.kind}|${set}`] = { shiftCm: result.shiftCm, turnDeg: result.turnDeg,
        roleShiftCm: result.roleShiftCm }
      out.push({ kind: r.kind, set, result })
      setAlignAll({ running: true, done: out.length, rows: [...out] })
    }
    setAlignAll({ running: false, done: out.length, rows: out })
    if (back) pick(back)
  }, [pick, selected, shown, t])

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
  // The dials act on the A half; how many roles it has decides pair or group.
  const isPairTarget = orientTarget?.role === 'a' && (row?.roles ?? 0) === 2
  const isGroupTarget = orientTarget?.role === 'a' && (row?.roles ?? 0) > 2
  const groupRoles = isGroupTarget ? (['a', 'b', 'c', 'd', 'e'] as const).slice(0, row?.roles ?? 0) : []
  const shiftDirty = isPairTarget && partnerShift.some((v) => v !== 0)
  const turnDirty = isPairTarget && partnerTurn.some((v) => v !== 0)
  const movedRoles = useMemo(() => (isGroupTarget
    ? Object.fromEntries(Object.entries(roleShift).filter(([, v]) => v.some((x) => x !== 0)))
    : {}), [isGroupTarget, roleShift])
  const roleShiftDirty = Object.keys(movedRoles).length > 0
  const clipShiftDirty = clipShift.some((v) => v !== 0)
  const orientDirty = !!(yawDeg || tiltDeg || rollDeg) || shiftDirty || roleShiftDirty || clipShiftDirty || turnDirty
  // ONE draft object for the place preview, read through a ref in its frame loop (a drag reloads nothing).
  const alignmentDraft = useMemo<AlignmentDraft>(() => ({
    yawDeg, tiltDeg, rollDeg, shiftCm: clipShift,
    roleShiftM: isPairTarget
      ? { b: [partnerShift[0] / 100, partnerShift[1] / 100, partnerShift[2] / 100] }
      : isGroupTarget
        ? Object.fromEntries(Object.entries(roleShift).map(([r, v]) =>
          [r, [v[0] / 100, v[1] / 100, v[2] / 100] as [number, number, number]]))
        : {},
    heightCm: heightDraft,
    partnerTurnDeg: isPairTarget ? partnerTurn : undefined,
    contactRelations: contactDraft,
    bendLimits: bendLimitsOf(bendDraft),
  }), [bendDraft, contactDraft, clipShift, heightDraft, isGroupTarget, isPairTarget, partnerShift, partnerTurn, roleShift, rollDeg, tiltDeg, yawDeg])
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
  const orientLocked = heightLocked || orientTarget?.has_sidecar === false

  // What a save would bake: angles and per-role offsets go through Blender; the whole-clip shift and the
  // surface heights are sidecar values (no Blender), the check is a sidecar mark.
  const bakeDirty = !!(yawDeg || tiltDeg || rollDeg) || shiftDirty || roleShiftDirty
  /** The finale clips the server edits along with this one (`finale_kinds_of` + same set/library): the
   *  finale of every pose that plays the kind, when a file of it lies beside this clip. */
  const finaleKinds = useMemo(() => (row && orientTarget
    ? finaleKindsOf(poses, row.kind, { set: orientTarget.set, library: libraryOf(orientTarget) },
      clips.map((c) => ({ kind: c.kind, set: c.set, library: libraryOf(c) })))
    : []), [clips, orientTarget, poses, row])
  // A green check that is already stored (same prop and places) is not offered again on its own.
  const checkStored = !!(placeCheck && savedCheck && savedCheck.prop === placeCheck.prop
    && savedCheck.place === placeCheck.place)
  const checkOnly = !orientDirty && !heightDirty && !!placeCheck && !checkStored
  const canSave = !!orientTarget && (orientDirty || heightDirty || checkOnly) && !heightLocked
    && !(orientDirty && orientLocked)
  /** The consequence of Save, shown BEFORE the click (checklist point 2). */
  const saveConsequence = useMemo(() => saveSteps({
    bake: bakeDirty, shift: clipShiftDirty || turnDirty, heights: heightDirty, finales: finaleKinds.length,
    greenCheck: !!placeCheck && (orientDirty || heightDirty || !checkStored), savedCheck: !!savedCheck,
  }).map((step) => ({
    bake: t('turn/tilt/roll and role offsets are baked into the clip file (one Blender run, no hub jobs)'),
    shift: t('the side/forward shift and partner B’s tilt/roll go to the sidecar'),
    heights: t('surface heights go to the sidecar and apply in game'),
    finales: t('the finale clips change the same way: {kinds}').replace('{kinds}', finaleKinds.join(', ')),
    check: t('the green place check is stored'),
    'clear-check': t('the stored place check is cleared'),
  })[step]), [bakeDirty, checkStored, clipShiftDirty, finaleKinds, heightDirty, orientDirty, placeCheck, savedCheck, t, turnDirty])
  /** THE one save path: bake/shift (orient), heights (PATCH) and the place check, in that order. */
  const save = useCallback(async () => {
    if (!orientTarget || !canSave) return
    setOrientBusy(true)
    setHeightBusy(heightDirty)
    setOrientError('')
    const touched = new Set<string>()
    try {
      if (orientDirty) {
        const res = await apiPost<{ seconds?: number; clips?: { kind: string }[] }>(`${clipPath(orientTarget)}/orient`, {
          yaw_deg: yawDeg, tilt_deg: tiltDeg, roll_deg: rollDeg,
          ...(shiftDirty ? { partner_shift_cm: partnerShift } : {}),
          ...(roleShiftDirty ? { role_shift_cm: movedRoles } : {}),
          ...(clipShiftDirty ? { shift_cm: clipShift } : {}),
          ...(turnDirty ? { partner_turn_deg: partnerTurn } : {}),
          ...(placeCheck ? { checked: placeCheck } : {}),
        })
        setOrientSeconds(typeof res.seconds === 'number' ? res.seconds : null)
        otherKinds(res.clips, orientTarget.kind).forEach((k) => touched.add(k))
      }
      if (heightDirty) {
        const res = await apiPatch<{ clips?: { kind: string }[] }>(clipPath(orientTarget), { height_offsets_cm: heightDraft })
        otherKinds(res.clips, orientTarget.kind).forEach((k) => touched.add(k))
      }
      // Heights are not a bake, and a check with nothing dialled is stored on its own (D3).
      if (!orientDirty && placeCheck) await apiPost(`${clipPath(orientTarget)}/orient`, { checked: placeCheck })
      setFinalesTouched(Array.from(touched))
      // The new saved values first, THEN the draft back to zero: in between the figures would jump.
      invalidateAnimationPreviewClips()
      await onReload()
      setYawDeg(0)
      setTiltDeg(0)
      setRollDeg(0)
      setPartnerShift([0, 0, 0])
      setPartnerTurn([0, 0])
      setRoleShift({})
      setClipShift([0, 0])
      setHeightDraft({})
      // The file keeps its URL, so the preview has to be rebuilt AND the
      // clip re-fetched — `seq` does both (component key + cache buster).
      if (orientDirty || heightDirty) setSeq((n) => n + 1)
    } catch (e) {
      setOrientError((e as Error).message)
    } finally {
      setOrientBusy(false)
      setHeightBusy(false)
    }
  }, [canSave, clipShift, clipShiftDirty, heightDirty, heightDraft, movedRoles, onReload, orientDirty, orientTarget,
    partnerShift, partnerTurn, placeCheck, roleShiftDirty, rollDeg, shiftDirty, tiltDeg, turnDirty, yawDeg])

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
      o.partner_shift_cm
        ? `${t('partner B forward / side / up')} ${o.partner_shift_cm[2]} / ${o.partner_shift_cm[0]} / ${o.partner_shift_cm[1]} cm`
        : '',
      o.partner_turn_deg?.some((v) => v !== 0)
        ? `${t('partner B tilt / roll')} ${o.partner_turn_deg[0]} / ${o.partner_turn_deg[1]}°` : '',
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
        onClick={(e) => { e.stopPropagation(); pick(r.kind, col) }}>
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
              onClick={() => pick(r.kind)}
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
                  onClick={() => { resetDials(); setPreviewSet(s) }}
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

            <div style={{ display: 'grid', gridTemplateColumns: orientTarget ? 'minmax(0, 1fr) 290px' : 'minmax(0, 1fr)', gap: 10, alignItems: 'start' }}>
              <div style={{ minWidth: 0 }}>
                {innerTab === 'places' && !row.missing ? (
                  /* A110 phase 2: the clip on a prop's places, through the shared per-figure runtime. */
                  <PlacePreview kind={row.kind} set={previewSet} roles={row.roles ?? 0} clips={row.clips}
                    draftRef={draftRef} draftSeq={alignmentDraft} bust={seq} height={600}
                    poses={poses.filter((p) => (p.animation || '').trim() === row.kind)}
                    onOpenPose={onOpenPose} onReadout={setPlaceReadout} autoAlignRef={autoAlignRef}
                    pairCheckRef={pairCheckRef} />
                ) : null}
                {innerTab === 'clip' && !row.missing ? (
                  <ClipPreview
                    key={`${row.kind}:${previewSet}:${seq}`}
                    kind={row.kind}
                    set={previewSet}
                    height={600}
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
                <div data-testid="align-col"
                  style={{ border: '1px solid var(--border, #30363d)', borderRadius: 6, padding: '6px 8px',
                    display: 'flex', flexDirection: 'column', gap: 3, fontSize: 12 }}
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
                  {isPairTarget ? (
                    <>
                      <div style={COL_HEAD}
                        title={t('Moves partner B against partner A in the clip file — the import offset, after the fact. Forward is the clip’s forward axis, side positive is its left.')}>
                        {t('Partner B')}
                      </div>
                      {([['Forward', 2], ['Side', 0], ['Up', 1]] as const).map(([label, axis]) => (
                        <SliderInput key={label} label={dialLabel(t(label))} unit="cm"
                          min={-50} max={50} step={1} value={partnerShift[axis]}
                          onChange={(cm) => setPartnerShift((prev) => {
                            const next: [number, number, number] = [prev[0], prev[1], prev[2]]
                            next[axis] = cm
                            return next
                          })}
                          disabled={orientLocked} {...DIAL} />
                      ))}
                      {([['B tilt', 0], ['B roll', 1]] as const).map(([label, axis]) => (
                        <SliderInput key={label} label={dialLabel(t(label))} unit="°"
                          title={t('Turns partner B about its hips, on top of the clip — renderer-only, saved beside the clip like the shift. Tilt tips B’s head towards the clip’s forward axis, roll tips B sideways.')}
                          min={-20} max={20} step={1} fineStep={0.1} value={partnerTurn[axis]}
                          onChange={(v) => setPartnerTurn((prev) => axis === 0 ? [v, prev[1]] : [prev[0], v])}
                          disabled={orientLocked} {...DIAL} />
                      ))}
                    </>
                  ) : null}
                  {(isPairTarget || isGroupTarget) && orientTarget ? (
                    <>
                      <ContactRelations roles={(['a', 'b', 'c', 'd', 'e'] as const).slice(0, row?.roles ?? 2)}
                        saved={savedContacts} draft={contactDraft} onDraft={setContactDraft} busy={busy}
                        onSave={(next) => { void run(orientTarget, { contact_target: next }) }} />
                      <BendLimitsEditor saved={savedBend} draft={bendDraft} onDraft={setBendDraft} busy={busy}
                        onSave={(next) => { void run(orientTarget, { bend_limits: next }) }} />
                      <button type="button" className="ga-btn ga-btn-sm" data-testid="align-auto"
                        disabled={orientLocked || innerTab !== 'places'}
                        title={innerTab !== 'places'
                          ? t('Open the Places view: Auto-align measures the figures shown there.')
                          : t('Plays the clip with the figures shown and, per contact, moves the place with the attached part (a pair: partner B) so that the tip sits at the target at the outermost frame and stays on the target’s axis; a pair’s B is then turned (tilt/roll, at most 20°). Writes the sliders above; Save stores them as usual.')}
                        onClick={() => {
                          const run = autoAlignRef.current
                          const res: AutoAlignResult = run ? run() : { ok: false, reason: t('The place preview is still loading.') }
                          setAutoAlign(res)
                          if (res.ok && isPairTarget) {
                            setPartnerShift(res.roleShiftCm.b ?? res.shiftCm)
                            setPartnerTurn([+res.turnDeg[0].toFixed(1), +res.turnDeg[1].toFixed(1)])
                          } else if (res.ok) setRoleShift(res.roleShiftCm)
                        }}>
                        {t('Auto-align')}
                      </button>
                      <button type="button" className="ga-btn ga-btn-sm" data-testid="pair-check"
                        disabled={innerTab !== 'places'}
                        title={t('Plays the pair shown over six loops: the first as stored with the dials above, then the fine fit the game makes for this pair when the interaction starts (at most 5 cm and 10°), with and without the per-frame follow; the last two loops are measured. Changes nothing, saves nothing.')}
                        onClick={() => {
                          const run = pairCheckRef.current
                          setPairCheck(run ? run() : { ok: false, reason: t('The place preview is still loading.') })
                        }}>
                        {t('Check this pair')}
                      </button>
                      <button type="button" className="ga-btn ga-btn-sm" data-testid="align-all"
                        disabled={innerTab !== 'places' || orientBusy || heightBusy}
                        title={t('Runs Auto-align on every pair clip in the list, one after the other, with the pair each clip’s Places view fills in (the persons you picked stay). Nothing is saved: open a clip from the table and Save it there.')}
                        onClick={() => { if (alignAll?.running) alignAllStop.current = true; else void runAlignAll() }}>
                        {alignAll?.running ? t('Stop ({n} done)').replace('{n}', String(alignAll.done))
                          : t('Align all pair and group clips ({n})').replace('{n}', String(shown.filter((r) => (r.roles ?? 0) >= 2 && !r.missing).length))}
                      </button>
                      {alignAll?.rows.length ? (
                        <table data-testid="align-all-result" data-result={JSON.stringify(alignAll.rows)}
                          style={{ borderCollapse: 'collapse', fontSize: 11 }}>
                          <thead><tr><th style={{ textAlign: 'left' }}>{t('Clip')}</th><th /><th>{t('tip')}</th><th>{t('depth')}</th>
                            <th>{t('off axis')}</th><th>{t('angle')}</th><th>{t('else')}</th><th /></tr></thead>
                          <tbody>
                            {alignAll.rows.map((x) => (
                              <tr key={`${x.kind}|${x.set}`}>
                                <td title={x.set ? `${x.kind} (${x.set})` : x.kind} style={{ maxWidth: 80, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{x.kind}</td>
                                {x.result.ok ? (
                                  <>
                                    <td style={{ whiteSpace: 'nowrap' }}><LampDot lamp={x.result.lamp} title={t('Channel contact')} />
                                      <LampDot lamp={x.result.clearLamp} title={t('Nothing else interpenetrates (green at most 5 mm)')} /></td>
                                    <td style={{ textAlign: 'right' }}>{x.result.after.entryMm.toFixed(0)}</td>
                                    <td style={{ textAlign: 'right' }}>{x.result.after.depthMm.toFixed(0)}</td>
                                    <td style={{ textAlign: 'right' }}>{x.result.after.maxLateralMm.toFixed(0)}</td>
                                    <td style={{ textAlign: 'right' }}>{x.result.after.axisDeg.toFixed(0)}°</td>
                                    <td style={{ textAlign: 'right' }}>{x.result.overlapAfterMm.toFixed(0)}</td>
                                  </>
                                ) : <td colSpan={6} style={{ color: 'var(--danger, #f85149)' }} title={x.result.reason}>{x.result.reason}</td>}
                                <td><button type="button" className="ga-btn ga-btn-sm" onClick={() => pick(x.kind, x.set)}
                                  disabled={alignAll.running}>{t('Open')}</button></td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      ) : null}
                      {alignAll && !alignAll.running && alignAll.rows.length ? (
                        <div className="ga-form-hint" style={{ margin: 0 }}>
                          {t('mm; nothing is saved. Open a clip: its Partner B dials carry the result; Save stores it.')}</div>
                      ) : null}
                      {pairCheck ? (
                        <div data-testid="pair-check-result" data-result={JSON.stringify(pairCheck)} style={{ fontSize: 11, lineHeight: 1.35 }}>
                          {pairCheck.ok ? (
                            <>
                              <div>{t('{by} → {of}: fine fit {x} / {y} / {z} mm, tilt {tilt}°, roll {roll}°')
                                .replace('{by}', pairCheck.by).replace('{of}', pairCheck.of)
                                .replace('{x}', pairCheck.fit.shiftMm[0].toFixed(0)).replace('{y}', pairCheck.fit.shiftMm[1].toFixed(0))
                                .replace('{z}', pairCheck.fit.shiftMm[2].toFixed(0))
                                .replace('{tilt}', pairCheck.fit.turnDeg[0].toFixed(1)).replace('{roll}', pairCheck.fit.turnDeg[1].toFixed(1))}</div>
                              <table style={{ borderCollapse: 'collapse' }}>
                                <thead><tr><th /><th style={{ padding: '0 4px' }}>{t('stored')}</th><th style={{ padding: '0 4px' }}>{t('fine fit')}</th>
                                  <th style={{ padding: '0 4px' }}>{t('+ follow')}</th></tr></thead>
                                <tbody>
                                  {([
                                    [t('Tip to opening at the outermost frame'), pairCheck.before.entryMm, pairCheck.after.entryMm, pairCheck.followed.entryMm, 'mm'],
                                    [t('Depth at the deepest frame'), pairCheck.before.depthMm, pairCheck.after.depthMm, pairCheck.followed.depthMm, 'mm'],
                                    [t('Off the axis inside, worst frame'), pairCheck.before.maxLateralMm, pairCheck.after.maxLateralMm, pairCheck.followed.maxLateralMm, 'mm'],
                                    [t('Shaft against the axis at the outermost frame'), pairCheck.before.axisDeg, pairCheck.after.axisDeg, pairCheck.followed.axisDeg, '°'],
                                    [t('Interpenetration besides the channel'), pairCheck.clearMm[0], pairCheck.clearMm[1], pairCheck.clearMm[2], 'mm'],
                                  ] as const).map(([label, a, b, c, unit]) => (
                                    <tr key={label}><td>{label}</td>
                                      <td style={{ textAlign: 'right', padding: '0 4px' }}>{a.toFixed(0)} {unit}</td>
                                      <td style={{ textAlign: 'right', padding: '0 4px' }}>{b.toFixed(0)} {unit}</td>
                                      <td style={{ textAlign: 'right', padding: '0 4px' }}>{c.toFixed(0)} {unit}</td></tr>
                                  ))}
                                </tbody>
                              </table>
                              {pairCheck.fit.bend ? (
                                <BendLine bend={pairCheck.followFit.bend ?? pairCheck.fit.bend} />
                              ) : null}
                              {pairCheck.clearWorst ? (
                                <div className="ga-form-hint" style={{ margin: 0 }}>
                                  {t('Deepest besides the channel: {pair}').replace('{pair}', pairCheck.clearWorst)}</div>
                              ) : null}
                            </>
                          ) : <span style={{ color: 'var(--danger, #f85149)' }}>{pairCheck.reason}</span>}
                        </div>
                      ) : null}
                      {autoAlign ? (
                        <div data-testid="align-auto-result" data-result={JSON.stringify(autoAlign)}
                          style={{ fontSize: 11, lineHeight: 1.35 }}>
                          {autoAlign.ok ? (
                            <>
                              <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                                <LampDot lamp={autoAlign.lamp} title={autoAlign.lamp === 'green'
                                  ? t('On the opening at the outermost frame and inside the channel at the deepest.')
                                  : autoAlign.lamp === 'yellow' ? t('Inside at the deepest frame, but off the axis or off the opening.')
                                    : t('Not inside the channel at the deepest frame.')} />
                                <LampDot lamp={autoAlign.clearLamp} title={(autoAlign.clearLamp === 'green'
                                  ? t('Nothing else interpenetrates: only the attached part enters the other body, through the channel (at most 5 mm elsewhere).')
                                  : t('The bodies interpenetrate besides the channel by {mm} mm, deepest at {pair} (green at most 5 mm, yellow at most 20 mm).')
                                    .replace('{mm}', autoAlign.overlapAfterMm.toFixed(0)).replace('{pair}', autoAlign.clearWorst || '–'))} />
                                <span>{t('{by} → {of}: {channel}').replace('{by}', autoAlign.by).replace('{of}', autoAlign.of)
                                  .replace('{channel}', autoAlign.target === 'channel' ? (autoAlign.channel.split(':').pop() || autoAlign.channel) : targetWordOf(t, autoAlign.target))}</span>
                              </div>
                              <table style={{ borderCollapse: 'collapse' }}>
                                <thead><tr><th /><th style={{ padding: '0 4px' }}>{t('before')}</th><th style={{ padding: '0 4px' }}>{t('after')}</th></tr></thead>
                                <tbody>
                                  {([
                                    [autoAlign.target === 'channel' ? t('Tip to opening at the outermost frame') : t('Tip to target at the outermost frame'), autoAlign.before.entryMm, autoAlign.after.entryMm],
                                    ...(autoAlign.target === 'channel' ? [[t('Depth at the deepest frame'), autoAlign.before.depthMm, autoAlign.after.depthMm] as const] : []),
                                    [t('Off the axis, worst frame'), autoAlign.before.maxLateralMm, autoAlign.after.maxLateralMm],
                                    [t('Interpenetration besides the channel'), autoAlign.overlapBeforeMm, autoAlign.overlapAfterMm],
                                  ] as const).map(([label, a, b]) => (
                                    <tr key={label}><td>{label}</td>
                                      <td style={{ textAlign: 'right', padding: '0 4px' }}>{a.toFixed(0)} mm</td>
                                      <td style={{ textAlign: 'right', padding: '0 4px' }}>{b.toFixed(0)} mm</td></tr>
                                  ))}
                                  {autoAlign.target === 'channel' ? (<tr><td>{t('Depth gained by B’s tilt/roll')}</td>
                                    <td style={{ textAlign: 'right', padding: '0 4px' }}>{autoAlign.afterShift.depthMm.toFixed(0)} mm</td>
                                    <td style={{ textAlign: 'right', padding: '0 4px' }}>{autoAlign.after.depthMm.toFixed(0)} mm</td></tr>) : null}
                                  <tr><td>{t('B tilt / roll')}</td><td />
                                    <td style={{ textAlign: 'right', padding: '0 4px' }}>{autoAlign.turnDeg[0].toFixed(1)}° / {autoAlign.turnDeg[1].toFixed(1)}°</td></tr>
                                  <tr><td>{t('Shaft against the axis at the outermost frame')}</td>
                                    <td style={{ textAlign: 'right', padding: '0 4px' }}>{autoAlign.before.axisDeg.toFixed(0)}°</td>
                                    <td style={{ textAlign: 'right', padding: '0 4px' }}>{autoAlign.after.axisDeg.toFixed(0)}°</td></tr>
                                </tbody>
                              </table>
                              {autoAlign.bend ? <BendLine bend={autoAlign.bend} /> : null}
                              {autoAlign.relations.length > 1 ? (
                                <table data-testid="align-auto-relations" style={{ borderCollapse: 'collapse' }}>
                                  <thead><tr><th style={{ textAlign: 'left' }}>{t('Contact')}</th><th /><th>{t('to target')}</th><th>{t('depth')}</th>
                                    <th>{t('off axis')}</th><th>{t('shift')}</th></tr></thead>
                                  <tbody>{autoAlign.relations.map((x) => (
                                    <tr key={x.part}><td>{x.by} → {x.of} {targetWordOf(t, x.target)}</td>
                                      <td><LampDot lamp={x.lamp} title={t('Contact')} /></td>
                                      <td style={{ textAlign: 'right', padding: '0 4px' }}>{x.before.entryMm.toFixed(0)} → {x.after.entryMm.toFixed(0)} mm</td>
                                      <td style={{ textAlign: 'right', padding: '0 4px' }}>{x.target === 'channel' ? `${x.after.depthMm.toFixed(0)} mm` : '–'}</td>
                                      <td style={{ textAlign: 'right', padding: '0 4px' }}>{x.before.maxLateralMm.toFixed(0)} → {x.after.maxLateralMm.toFixed(0)} mm</td>
                                      <td style={{ textAlign: 'right', padding: '0 4px' }}>{x.part.toUpperCase()} {x.shiftCm.map((v) => v.toFixed(1)).join(' / ')} cm</td></tr>
                                  ))}</tbody>
                                </table>
                              ) : null}
                              <div className="ga-form-hint" style={{ margin: 0 }}>
                                {t('Measured on the pair shown; another pair may need its own run. Save stores the sliders.')}
                              </div>
                            </>
                          ) : <span style={{ color: 'var(--danger, #f85149)' }}>{autoAlign.reason}</span>}
                        </div>
                      ) : null}
                    </>
                  ) : null}
                  {isGroupTarget ? (
                    <>
                      <div style={{ ...COL_HEAD, display: 'flex', gap: 4, alignItems: 'center', flexWrap: 'wrap' }}
                        title={t('Moves the selected role against the others in the clip files — its own half and its alt halves. Forward is the clip’s forward axis, side positive is its left.')}>
                        <span>{t('Move a role')}</span>
                        {groupRoles.map((r) => {
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
                        <SliderInput key={label} label={dialLabel(`${shiftRole.toUpperCase()} · ${t(label)}`)} unit="cm"
                          min={-50} max={50} step={1} value={(roleShift[shiftRole] || [0, 0, 0])[axis]}
                          onChange={(cm) => setRoleShift((prev) => {
                            const cur = prev[shiftRole] || [0, 0, 0]
                            const next: [number, number, number] = [cur[0], cur[1], cur[2]]
                            next[axis] = cm
                            return { ...prev, [shiftRole]: next }
                          })}
                          disabled={orientLocked} {...DIAL} />
                      ))}
                    </>
                  ) : null}

                  {/* THE one save path, its consequence spelled out before the click. */}
                  <div style={{ borderTop: '1px solid var(--border, #30363d)', marginTop: 6, paddingTop: 6 }}
                    data-testid="align-consequence">
                    {saveConsequence.length ? (
                      <ul style={{ margin: '0 0 4px 14px', padding: 0 }}>
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
    </div>
  )
}

/** Ruling A145: the core default of the bend limits (the server's `BEND_LIMITS_DEFAULT`), until the listing says. */
const BEND_WIRE_DEFAULT: BendLimitsWire = { raised: { joint_deg: 15, total_deg: 35 }, resting: { joint_deg: 45, total_deg: 120 } }

/** Ruling A145: "Bend 28° of max 35°" with its lamp — yellow when the part was at its limit in some frame. */
function BendLine({ bend }: { bend: { maxDeg: number; limitDeg: number; atLimit: number; frames: number; lamp: 'green' | 'yellow' } }) {
  const { t } = useI18n()
  return (
    <div data-testid="bend-readout" style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
      <LampDot lamp={bend.lamp} title={bend.lamp === 'yellow'
        ? t('The attached part is at its bend limit in {n} of {m} frames: the rest of the way is the partner’s shift or turn.')
          .replace('{n}', String(bend.atLimit)).replace('{m}', String(bend.frames))
        : t('The attached part bends within its limit in every frame.')} />
      <span>{t('Bend {deg}° of max {max}°').replace('{deg}', bend.maxDeg.toFixed(0)).replace('{max}', bend.limitDeg.toFixed(0))}</span>
    </div>
  )
}
