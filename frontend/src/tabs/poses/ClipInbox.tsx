/**
 * ClipInbox — importing FOREIGN animation files (plan-clip-import.md steps 1+3).
 *
 * Everything a user drops into `shared/models/clips-inbox` (or uploads here)
 * is listed with the server's probe: which skeleton family the file carries,
 * whether it has fingers, whether it looks like a reference pose. An unknown
 * rig is refused before Blender is ever started — the retargeter has no bone
 * map for it.
 *
 * The inbox is read RECURSIVELY: every entry's `name` is its path relative to
 * the inbox (`walk.fbx`, `pack/female/walk.fbx`), and the list shows the root
 * files first, then one collapsible group per subfolder — a dropped-in pack
 * keeps its structure instead of flattening into one long list.
 *
 * Three things the form exists for:
 *   * a PAIR or GROUP is two to five sources, the selected one first (role
 *     A); the further roles are suggested from the file or take names (a
 *     pack scene with three performers preselects all of them) and can be
 *     dropped again;
 *   * a REFERENCE POSE (T-/A-pose export of the same rig) gives the bones
 *     their real twist instead of a positional reconstruction;
 *   * the TARGET is the licensed library by default — a foreign file is
 *     licensed material until its owner says otherwise.
 *
 *   GET    /assets/clips-inbox
 *   POST   /assets/clips-inbox/upload    (multipart, field "files")
 *   DELETE /assets/clips-inbox/{name}   (name = the relative path)
 *   POST   /assets/clips-inbox/import    {kind, files, rest_file, set, …}
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ClipPreview } from './ClipPreview'
import { SliderInput } from '../../components/SliderInput'
import { useI18n } from '../../i18n/I18nProvider'
import { apiDelete, apiGet, apiPost, apiUpload } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { RootMotionField } from './RootMotionField'
import { rootMotionBlocksLoop, type RootMotionMode } from './rootMotion'

interface Probe {
  skeleton_family: string
  bone_count: number
  has_fingers: boolean
  is_rest_candidate: boolean
  take_count: number
  error?: string
}

/** One animation inside a file. The INDEX is what the importer addresses — a
 *  take name is not unique once Blender has truncated it. */
interface Take {
  index: number
  name: string
  duration_s: number
  /** index of the take that plays the other half of the same scene, or null */
  pair: number | null
  /** indices of every take of the same scene when three or more perform it,
   *  in role order (A first), or null */
  group?: number[] | null
}

/** The role letters of a pair or group, in order (`animation_clips.CLIP_ROLES`). */
const ROLES = ['a', 'b', 'c', 'd', 'e'] as const

/** One further role of a pair or group (B, C, …): the file, the animation
 *  inside it ('' when the file holds only one), and its offset in metres —
 *  forward / side / up as strings of the inputs. */
interface RoleSource { file: string; take: string; fwd: string; side: string; up: string }

function roleSource(file: string, take = '', keep?: RoleSource): RoleSource {
  return { file, take, fwd: keep?.fwd ?? '0', side: keep?.side ?? '0', up: keep?.up ?? '0' }
}

interface InboxEntry {
  name: string
  size: number
  mtime: number
  probe: Probe
  pair?: string
}

interface InboxData {
  dir: string
  entries: InboxEntry[]
  rest_suggestion: string
  families: string[]
}

interface ClipEntry { kind: string; set: string; source: string }

type Target = 'licensed' | 'free'

/** `pack/female/walk.fbx` → `['pack/female', 'walk.fbx']`; a root file has
 *  the empty folder. */
function splitInboxName(name: string): [string, string] {
  const i = name.lastIndexOf('/')
  return i < 0 ? ['', name] : [name.slice(0, i), name.slice(i + 1)]
}

/** A kind proposal from the file name: folder and role prefixes and take
 *  suffixes off, the rest slugged. `Female_Resting_Loop0.fbx` → `resting`. */
function slugFromFile(name: string): string {
  let stem = splitInboxName(name)[1].replace(/\.[^.]+$/, '')
  stem = stem.replace(/^(female|male)[_-]/i, '')
  stem = stem.replace(/[_-](loop|pose|take|clip)\d*$/i, '')
  stem = stem.replace(/[_-]?(a|b|l|r)$/i, '')
  return stem
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
}

/** A kind proposal from a TAKE name: the role marker off, the rest slugged.
 *  `Female[A]_Resting_Loop0` → `resting-loop0`. The phase stays in the name —
 *  one take is one clip, and two phases of a scene are two kinds. */
function slugFromTake(name: string): string {
  return name
    .replace(/^[A-Za-z]+\[[A-Za-z0-9]+\][_-]/, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
}

/** Does a take NAME say "this is a pose, not a movement"? Mirrors
 *  `fbx_import.REST_MARKERS`, so the picker proposes the same file the server
 *  would have proposed had the pose been a file of its own. */
function isRestTake(name: string): boolean {
  const low = name.toLowerCase()
  return ['tpose', 't-pose', 't_pose', 'apose', 'a-pose', 'rest', 'bind']
    .some((m) => low.includes(m))
}

/** The animation picker of one file. Rendered only when a file holds more
 *  than one — a single-take export has nothing to choose. */
function TakeSelect({ label, hint, takes, value, onChange, placeholder }: {
  label: string
  hint?: string
  takes: Take[]
  value: string
  onChange: (v: string) => void
  placeholder: string
}) {
  return (
    <label style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
      <span className="ga-hint">{label} ({takes.length})</span>
      <select className="ga-input" value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">{placeholder}</option>
        {takes.map((tk) => (
          <option key={tk.index} value={tk.index}>
            {tk.name} — {tk.duration_s.toFixed(2)} s
          </option>
        ))}
      </select>
      {hint ? <span className="ga-hint">{hint}</span> : null}
    </label>
  )
}

/** The takes of one inbox file, loaded on demand. The listing only carries
 *  how MANY a file holds, because a pack file has over a hundred of them. */
function useTakes(name: string): Take[] {
  const [takes, setTakes] = useState<Take[]>([])
  useEffect(() => {
    if (!name) {
      setTakes([])
      return
    }
    let live = true
    apiGet<{ takes?: Take[] }>(`/assets/clips-inbox/takes/${encodeURI(name)}`)
      .then((r) => { if (live) setTakes(r.takes || []) })
      .catch(() => { if (live) setTakes([]) })
    return () => { live = false }
  }, [name])
  return takes
}

/** One further role of the import: which file and animation plays it, and
 *  where the pack recorded it (the offset). Its own component, because every
 *  role loads the takes of ITS file. */
function RoleRow({ letter, value, onChange, onRemove, entry, ownTakes, kin, t }: {
  letter: string
  value: RoleSource
  onChange: (v: RoleSource) => void
  onRemove: () => void
  entry: InboxEntry
  ownTakes: Take[]
  kin: InboxEntry[]
  t: (s: string) => string
}) {
  const takes = useTakes(value.file)
  return (
    <div style={{ border: '1px solid var(--ga-border, #3a3a3a)', borderRadius: 4,
      padding: '6px 8px', display: 'flex', flexDirection: 'column', gap: 6 }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end' }}>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 3, flex: 1 }}>
          <span className="ga-hint">{t('Role')} {letter.toUpperCase()}</span>
          <select className="ga-input" value={value.file}
            onChange={(e) => onChange({ ...value, file: e.target.value, take: '' })}>
            <option value="">{t('— pick a file —')}</option>
            {/* Every role out of one pack file is the normal case for a
                scene, so the file itself is a candidate. */}
            {ownTakes.length > 1 ? (
              <option value={entry.name}>{t('this file (another animation)')}</option>
            ) : null}
            {kin.map((e) => (
              <option key={e.name} value={e.name}>{e.name}</option>
            ))}
          </select>
        </label>
        <button type="button" className="ga-btn ga-btn-sm" title={t('Remove this role')}
          onClick={onRemove}>✕</button>
      </div>
      {takes.length > 1 ? (
        <TakeSelect
          label={t('Its animation')}
          takes={takes}
          value={value.take}
          onChange={(v) => onChange({ ...value, take: v })}
          placeholder={t('— pick one —')}
        />
      ) : null}
      <div style={{ display: 'flex', gap: 8 }}>
        {([['forward', 'fwd'], ['side', 'side'], ['up', 'up']] as const).map(([lbl, key]) => (
          <label key={key} style={{ display: 'flex', flexDirection: 'column', gap: 2, flex: 1 }}>
            <span className="ga-hint">{t(lbl)} (m)</span>
            <input className="ga-input" type="number" step="0.05" value={value[key]}
              onChange={(e) => onChange({ ...value, [key]: e.target.value })} />
          </label>
        ))}
      </div>
    </div>
  )
}

function mb(bytes: number): string {
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export function ClipInbox({ onCreatePose, rootDropOf }: {
  onCreatePose?: (kind: string, store?: 'shared' | 'world') => void
  /** `root_drop` of a place type (fraction of the figure height) — the preview
   *  sinks the figure that far under the calibration box's top, the way the
   *  server places it on the real marker. */
  rootDropOf?: (group: string) => number
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const fileInput = useRef<HTMLInputElement | null>(null)

  const [data, setData] = useState<InboxData | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [dragOver, setDragOver] = useState(false)
  const [clips, setClips] = useState<ClipEntry[]>([])
  const [sets, setSets] = useState<string[]>([])

  const [selected, setSelected] = useState('')
  /** the subfolder groups the user has opened (the root files are never folded) */
  const [openGroups, setOpenGroups] = useState<string[]>([])
  /** the further roles B, C, … of a pair or group — empty = a solo import */
  const [others, setOthers] = useState<RoleSource[]>([])
  /** which animation inside each file — '' when the file holds only one */
  const [take, setTake] = useState('')
  const [restTake, setRestTake] = useState('')
  /** takes queued for one batch run, by index */
  const [batch, setBatch] = useState<number[]>([])
  const [batchRun, setBatchRun] = useState<{ done: number; total: number } | null>(null)
  const [batchResult, setBatchResult] = useState<
    { name: string; kind: string; error: string }[]>([])
  const [restFile, setRestFile] = useState('')

  const [kind, setKind] = useState('')
  const [clipSet, setClipSet] = useState('')
  const [startS, setStartS] = useState('0')
  const [endS, setEndS] = useState('')
  const [loopOn, setLoopOn] = useState(false)
  const [loopS, setLoopS] = useState('1.5')
  /** playback factor baked into the clip: 0.5 = half speed, twice as long */
  const [speed, setSpeed] = useState('1')
  const [rootMotion, setRootMotion] = useState<RootMotionMode>('strip')
  /** Put the head upright on the neck (`_cmu.level_head`). Generated
   *  animations get the head wholesale wrong — the Meshy biped this was built
   *  for hangs its head 108° forward for the whole take, crown 17 cm BELOW
   *  the neck base while the figure stands — and the retarget passes that on
   *  faithfully, because a hanging head is what the source says. Unlike the
   *  turn dial this one changes the conversion, so the preview shows it only
   *  after a fresh probe. */
  const [levelHead, setLevelHead] = useState(false)
  const [overwrite, setOverwrite] = useState(false)
  const [target, setTarget] = useState<Target>('licensed')
  const [redistributable, setRedistributable] = useState(false)
  const [importing, setImporting] = useState(false)
  const [imported, setImported] = useState<{ kind: string; files: string[]; seq: number } | null>(null)

  const loadClips = useCallback(async () => {
    try {
      const r = await apiGet<{ clips?: ClipEntry[]; sets?: string[] }>('/assets/animation-clips')
      setClips(r.clips || [])
      setSets(r.sets || [])
    } catch {
      setClips([])
    }
  }, [])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setData(await apiGet<InboxData>('/assets/clips-inbox'))
      setError('')
    } catch (e) {
      setData(null)
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
    void loadClips()
  }, [load, loadClips])

  const entries = useMemo(() => data?.entries || [], [data])
  const entry = useMemo(() => entries.find((e) => e.name === selected) || null, [entries, selected])

  /** The list as folders: the root's files first, then one group per
   *  subfolder in the server's order (a folder's files, then its subfolders). */
  const groups = useMemo(() => {
    const byDir = new Map<string, InboxEntry[]>()
    for (const e of entries) {
      const dir = splitInboxName(e.name)[0]
      const list = byDir.get(dir)
      if (list) list.push(e)
      else byDir.set(dir, [e])
    }
    const out = Array.from(byDir.entries()).map(([dir, list]) => ({ dir, entries: list }))
    return [...out.filter((g) => !g.dir), ...out.filter((g) => !!g.dir)]
  }, [entries])

  /** The inbox files that may join THIS one: same rig family, and not itself.
   *  A pair half or a reference pose from another rig carries different bones
   *  in different places — the retarget cannot notice and produces a constant
   *  offset in every frame (measured up to -174° on the forearm when a Unity
   *  `Tpose.fbx` was offered for the Mixamo-named MOB1 packs). */
  const kin = useMemo(
    () => entries.filter((e) => e.name !== entry?.name && !!e.probe.skeleton_family
      && e.probe.skeleton_family === entry?.probe.skeleton_family),
    [entries, entry],
  )

  /** Picking a file resets the form to that file's own defaults: the pair the
   *  names suggest, the reference pose the inbox offers, the kind slug. */
  const pick = useCallback(
    (name: string) => {
      const e = entries.find((x) => x.name === name) || null
      setSelected(name)
      setOthers(e?.pair ? [roleSource(e.pair)] : [])
      // the pair select lists the partner by its relative path; keep it
      // reachable in the list too
      const dir = splitInboxName(name)[0]
      if (dir) setOpenGroups((prev) => (prev.includes(dir) ? prev : [...prev, dir]))
      const rest = entries.find((x) => x.name === data?.rest_suggestion)
      setRestFile(rest && rest.name !== name
        && rest.probe.skeleton_family === e?.probe.skeleton_family ? rest.name : '')
      setKind(slugFromFile(name))
      setTake('')
      setRestTake('')
      setBatch([])
      setBatchResult([])
      setStartS('0')
      setEndS('')
      setLoopOn(false)
      setRootMotion('strip')
      setOverwrite(false)
      setImported(null)
    },
    [data, entries],
  )

  const upload = useCallback(
    async (files: FileList | File[] | null) => {
      const list = Array.from(files || [])
      if (!list.length || uploading) return
      setUploading(true)
      let ok = 0
      for (const file of list) {
        try {
          await apiUpload('/assets/clips-inbox/upload', file, 'files')
          ok += 1
        } catch (e) {
          toast(`${file.name}: ${(e as Error).message}`, 'error')
        }
      }
      if (ok) toast(`${t('Uploaded')}: ${ok}`)
      setUploading(false)
      await load()
    },
    [load, t, toast, uploading],
  )

  const removeFiles = useCallback(
    async (names: string[]) => {
      for (const name of names) {
        try {
          await apiDelete(`/assets/clips-inbox/${encodeURIComponent(name)}`)
        } catch (e) {
          toast(`${name}: ${(e as Error).message}`, 'error')
        }
      }
      if (names.includes(selected)) {
        setSelected('')
        setImported(null)
      }
      await load()
    },
    [load, selected, toast],
  )

  const existingKinds = useMemo(
    () =>
      new Set(
        clips
          .filter((c) => c.source === target && (c.set || '') === clipSet)
          .map((c) => c.kind),
      ),
    [clips, clipSet, target],
  )
  const takes = useTakes(selected)
  const restTakes = useTakes(restFile)

  // A pack ships its reference pose as one take among the movements, so a
  // multi-take file offers ITS OWN pose rather than a foreign file — the
  // file-name heuristic behind `rest_suggestion` cannot see inside a file.
  useEffect(() => {
    if (!selected || takes.length <= 1) return
    const i = takes.findIndex((tk) => isRestTake(tk.name))
    setRestFile(i >= 0 ? selected : '')
    setRestTake(i >= 0 ? String(i) : '')
  }, [selected, takes])

  // With a take chosen, the clip name comes from what the ANIMATION is called,
  // not from the pack file it happens to sit in — and the other roles of the
  // scene are preselected the way a single-take export preselects its partner
  // FILE, because here every role lives in one file. The chosen take plays
  // role A; a scene of three or more fills B, C, … in the server's role order.
  // Offsets already typed stay with their row.
  useEffect(() => {
    if (take === '') return
    const tk = takes.find((x) => String(x.index) === take)
    if (!tk) return
    setKind(slugFromTake(tk.name))
    const rest = tk.group ? tk.group.filter((i) => i !== tk.index)
      : tk.pair != null ? [tk.pair] : null
    if (rest) setOthers((prev) => rest.map((i, n) => roleSource(selected, String(i), prev[n])))
  }, [selected, take, takes])

  const kindExists = existingKinds.has(kind.trim().toLowerCase())
  const unknownRig = !!entry && !entry.probe.skeleton_family
  /** a pair or group: role A plus at least one further role */
  const isPair = others.length > 0

  /** probe conversion — the preview plays exactly what the form would import */
  const [probe, setProbe] = useState<{ urls: Record<string, string | undefined>; seq: number; seconds: number } | null>(null)
  const [probing, setProbing] = useState(false)

  /** One source address as the API spells it: the file, and which animation
   *  inside it. A file with a single take passes no take. */
  const src = useCallback((name: string, idx: string) => (
    idx === '' ? { name } : { name, take: Number(idx) }
  ), [])

  /** The import body for ONE take of the selected file. Without an argument
   *  it is what the form currently shows; with one it is that take with its
   *  own partner and its own name, which is what a batch needs. */
  /** THE ORIENTATION DIAL, degrees, baked by the import (`yaw_deg`) — the
   *  same field the CMU catalog import has. The conversion aims the root's
   *  FORWARD axis at +Z, which is the facing of an upright actor and the
   *  belly direction of a lying one, so a lying take needs its angle chosen
   *  by eye. The PROBE never bakes it (see `runProbe`): the preview turns the
   *  clip live, which is instant and costs no Blender run per notch. */
  const [yawDeg, setYawDeg] = useState(0)
  const [footprint, setFootprint] = useState('')

  const formBody = useCallback((only?: Take): Record<string, unknown> | null => {
    if (!entry) return null
    // A batch take brings its own scene: its group in role order, else its
    // pair partner, else it stands alone. The form's offsets apply by role.
    const files = only
      ? (only.group || [only.index, ...(only.pair == null ? [] : [only.pair])])
        .map((i) => src(entry.name, String(i)))
      : [src(entry.name, take), ...others.map((o) => src(o.file, o.take))]
    const pairBody = files.length > 1
    const offsets: Record<string, number[]> = {}
    if (pairBody) {
      others.forEach((o, i) => {
        const role = ROLES[i + 1]
        if (i + 1 < files.length) {
          offsets[role] = [Number(o.side) || 0, Number(o.up) || 0, Number(o.fwd) || 0]
        }
      })
    }
    const first = only?.group ? takes.find((x) => x.index === only.group![0]) || only : only
    return {
      kind: first ? slugFromTake(first.name)
        : (kind.trim().toLowerCase() || 'preview'),
      files,
      rest_file: restFile ? src(restFile, restTake) : null,
      set: clipSet,
      start_s: Number(startS) || 0,
      end_s: endS === '' ? null : Number(endS),
      loop_s: loopOn && !isPair ? Number(loopS) || 1 : null,
      speed: Number(speed) || 1,
      // a pair keeps its contact geometry — never any travel
      root_motion: pairBody ? 'strip' : rootMotion,
      yaw_deg: yawDeg || 0,
      level_head: levelHead,
      offsets_m: pairBody ? offsets : null,
      overwrite,
      target,
      redistributable: target === 'free' ? redistributable : false,
    }
  }, [clipSet, endS, entry, isPair, kind, levelHead, loopOn, loopS, others, rootMotion, speed,
      overwrite, redistributable, restFile, restTake, src, startS, take, takes, target, yawDeg])

  /** Loop + travel is refused by the route (400) — the buttons say so first. */
  const loopBlocked = !isPair && rootMotionBlocksLoop(loopOn, rootMotion)

  const runProbe = useCallback(async () => {
    // The ONE exception to "the probe plays the very body the import sends":
    // the orientation dial is applied live in the viewer, so baking it here
    // as well would turn the clip twice. Everything else is the import's own
    // body, unchanged.
    const body = formBody()
    if (body) body.yaw_deg = 0
    if (!body || probing) return
    setProbing(true)
    try {
      const r = await apiPost<{ urls: Record<string, string>; seconds: number }>(
        '/assets/clips-inbox/preview', body)
      // cache-bust: the probe files are overwritten on every run
      const now = Date.now()
      const urls = Object.fromEntries(Object.entries(r.urls || {}).map(([k, u]) => [k, `${u}?v=${now}`]))
      setProbe((prev) => ({ urls, seq: (prev?.seq || 0) + 1, seconds: r.seconds || 0 }))
      setImported(null)
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setProbing(false)
    }
  }, [formBody, probing, t, toast])

  /** Import every queued take, one after another. Sequential on purpose: each
   *  run occupies Blender, and a per-take row is what makes a failure in the
   *  middle readable instead of losing the whole run. */
  const runBatch = useCallback(async () => {
    if (!entry || batchRun) return
    const queued = takes.filter((tk) => batch.includes(tk.index))
    if (!queued.length) return
    setBatchResult([])
    setBatchRun({ done: 0, total: queued.length })
    const out: { name: string; kind: string; error: string }[] = []
    for (const tk of queued) {
      const body = formBody(tk)
      let kindName = ''
      try {
        if (!body) throw new Error('no file selected')
        kindName = String(body.kind || '')
        const r = await apiPost<{ kind: string }>('/assets/clips-inbox/import', body)
        out.push({ name: tk.name, kind: r.kind, error: '' })
      } catch (e) {
        out.push({ name: tk.name, kind: kindName, error: (e as Error).message })
      }
      setBatchResult([...out])
      setBatchRun({ done: out.length, total: queued.length })
    }
    setBatchRun(null)
    await loadClips()
    const bad = out.filter((r) => r.error).length
    toast(bad
      ? `${out.length - bad}/${out.length} ${t('imported')} — ${bad} ${t('failed')}`
      : `${out.length} ${t('imported')}`, bad ? 'error' : undefined)
  }, [batch, batchRun, entry, formBody, loadClips, t, takes, toast])

  const runImport = useCallback(async () => {
    const body = formBody()
    if (!entry || !body || importing) return
    setImporting(true)
    try {
      // The very same body the preview plays — one place decides what an
      // import IS, so a field added to the form cannot reach only one of them.
      body.kind = kind.trim().toLowerCase()
      const names = Array.from(new Set([entry.name, ...others.map((o) => o.file).filter(Boolean)]))
      const r = await apiPost<{ kind: string; seconds: number; files: string[] }>(
        '/assets/clips-inbox/import',
        body,
      )
      toast(`${t('Imported as')} ${r.kind} (${(r.seconds || 0).toFixed(1)} s)`)
      setImported((prev) => ({ kind: r.kind, files: names, seq: (prev?.seq || 0) + 1 }))
      await loadClips()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setImporting(false)
    }
  }, [entry, formBody, importing, kind, loadClips, others, t, toast])

  // Only the FIRST load blanks the view; a refresh keeps the list (and the
  // selection, the form, the preview) in place while the answer is on its way.
  if (loading && !data) return <div className="ga-placeholder">{t('Loading…')}</div>

  return (
    <div
      style={{
        display: 'grid', gridTemplateColumns: 'minmax(280px, 1fr) minmax(340px, 1.4fr)',
        gap: 14, alignItems: 'stretch', flex: 1, minHeight: 0,
      }}
    >
      {/* ── inbox list + upload ── */}
      <section style={{ display: 'flex', flexDirection: 'column', gap: 8, minWidth: 0, minHeight: 0, overflowY: 'auto' }}>
        <div
          onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => { e.preventDefault(); setDragOver(false); void upload(e.dataTransfer.files) }}
          style={{
            border: `1px dashed ${dragOver ? 'var(--accent, #58a6ff)' : 'var(--border, #30363d)'}`,
            borderRadius: 6, padding: 12, textAlign: 'center',
            background: dragOver ? 'rgba(88,166,255,0.08)' : 'transparent',
          }}
        >
          <div>{uploading ? t('Uploading…') : t('Drop FBX or BVH files here')}</div>
          <div className="ga-hint" style={{ marginTop: 4 }}>
            {t('or')}{' '}
            <button type="button" className="ga-btn ga-btn-sm" disabled={uploading}
              onClick={() => fileInput.current?.click()}>
              {t('Choose files…')}
            </button>
          </div>
          <input
            ref={fileInput}
            type="file"
            accept=".fbx,.bvh"
            multiple
            style={{ display: 'none' }}
            onChange={(e) => { void upload(e.target.files); e.target.value = '' }}
          />
        </div>

        <div className="ga-hint" style={{ wordBreak: 'break-all' }}>
          {t('Inbox directory')}: <code>{data?.dir || ''}</code>
          {' — '}{t('subfolders are read too')}
          {error ? ` — ${error}` : ''}
        </div>

        <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
          <span className="ga-hint" style={{ flex: 1 }}>
            {entries.length} {t('files')}
            {groups.filter((g) => g.dir).length
              ? ` · ${groups.filter((g) => g.dir).length} ${t('folders')}`
              : ''}
          </span>
          <button
            type="button"
            className="ga-btn ga-btn-sm"
            disabled={loading}
            title={t('Re-read the inbox directory')}
            onClick={() => { void load(); void loadClips() }}
          >
            ⟳ {t('Refresh')}
          </button>
        </div>

        <ul className="ga-list" style={{ minWidth: 0 }}>
          {!entries.length ? (
            <li className="ga-list-empty">
              {t('Nothing waiting — drop files in the directory above or upload them.')}
            </li>
          ) : null}
          {groups.map((g) => {
            const open = !g.dir || openGroups.includes(g.dir)
            return (
              <li key={g.dir || '/'} style={{ minWidth: 0 }}>
                {g.dir ? (
                  <button
                    type="button"
                    className="ga-list-row"
                    onClick={() =>
                      setOpenGroups((prev) =>
                        prev.includes(g.dir) ? prev.filter((d) => d !== g.dir) : [...prev, g.dir],
                      )
                    }
                  >
                    <span className="ga-list-row-main" style={{ minWidth: 0 }}>
                      <span style={{ opacity: 0.6, marginRight: 6 }}>{open ? '▾' : '▸'}</span>
                      <code>{g.dir}/</code>
                    </span>
                    <span className="ga-source">×{g.entries.length}</span>
                  </button>
                ) : null}
                {open ? (
                  <div style={{ paddingLeft: g.dir ? 14 : 0 }}>
                    {g.entries.map((e) => {
                      const file = splitInboxName(e.name)[1]
                      const badges = [
                        e.probe.skeleton_family || t('unknown rig'),
                        e.probe.has_fingers ? t('fingers') : '',
                        e.probe.is_rest_candidate ? t('reference pose') : '',
                        e.probe.take_count > 1
                          ? `${e.probe.take_count} ${t('animations')}` : '',
                        e.pair ? `${t('pair with')} ${splitInboxName(e.pair)[1]}` : '',
                        mb(e.size),
                      ].filter(Boolean)
                      return (
                        <button
                          key={e.name}
                          type="button"
                          className={`ga-list-row${e.name === selected ? ' is-active' : ''}`}
                          style={{ alignItems: 'flex-start' }}
                          title={e.name}
                          onClick={() => pick(e.name)}
                        >
                          <span className="ga-list-row-main" style={{ minWidth: 0 }}>
                            <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                              {file}
                            </div>
                            <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', fontSize: '0.72em', opacity: 0.75, marginTop: 2 }}>
                              {badges.map((b) => (
                                <span
                                  key={b}
                                  style={{
                                    border: '1px solid var(--border, #30363d)', borderRadius: 3,
                                    padding: '0 4px',
                                    color: b === t('unknown rig') ? 'var(--warn, #d29922)' : undefined,
                                  }}
                                >
                                  {b}
                                </span>
                              ))}
                            </div>
                          </span>
                        </button>
                      )
                    })}
                  </div>
                ) : null}
              </li>
            )
          })}
        </ul>
      </section>

      {/* ── the import form ── */}
      <section style={{ minWidth: 0, minHeight: 0, overflowY: 'auto', paddingRight: 4 }}>
        {!entry ? (
          <div className="ga-placeholder">{t('Pick a file to import it.')}</div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <div>
              <h3 style={{ margin: '0 0 2px' }}>{entry.name}</h3>
              <div className="ga-hint">
                {entry.probe.skeleton_family
                  ? `${entry.probe.skeleton_family} · ${entry.probe.bone_count} ${t('mapped bones')}`
                    + (entry.probe.has_fingers ? ` · ${t('fingers')}` : '')
                  : t('Unknown rig — no bone map matches this file. It cannot be imported; the known families are listed in the inbox README.')}
              </div>
            </div>

            {takes.length > 1 ? (
              <TakeSelect
                label={t('Animation')}
                hint={t('This file holds several. Pick the one to convert —'
                        + ' the import refuses a file whose animation is unnamed'
                        + ' rather than silently taking the first.')}
                takes={takes}
                value={take}
                onChange={setTake}
                placeholder={t('— pick one —')}
              />
            ) : null}

            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <span className="ga-hint">
                {t('Further roles — the animation above plays role A. A pair adds B, a group up to E; all of them become one kind (__a … __e) at a shared anchor. The offset moves a role whose pack recorded it elsewhere. A pack names the axis of ITS engine: a Unity export\'s forward is forward here, an Unreal export\'s forward (its X) is side here with the opposite sign — "-0.3 on the forward axis" is forward -0.3 for Unity, side +0.3 for Unreal.')}
              </span>
              {others.map((o, i) => (
                <RoleRow key={i} letter={ROLES[i + 1]} value={o} entry={entry} ownTakes={takes}
                  kin={kin} t={t}
                  onChange={(v) => setOthers((prev) => prev.map((x, n) => (n === i ? v : x)))}
                  onRemove={() => setOthers((prev) => prev.filter((_x, n) => n !== i))} />
              ))}
              {others.length < ROLES.length - 1 ? (
                <div>
                  <button type="button" className="ga-btn ga-btn-sm"
                    onClick={() => setOthers((prev) => [...prev,
                      roleSource(takes.length > 1 ? entry.name : '')])}>
                    + {t('Add role')} {ROLES[others.length + 1].toUpperCase()}
                  </button>
                </div>
              ) : null}
            </div>

            {takes.length > 1 ? (
              <details style={{ border: '1px solid var(--ga-border, #3a3a3a)',
                borderRadius: 4, padding: '6px 8px' }}>
                <summary style={{ cursor: 'pointer' }}>
                  {t('Import several at once')}
                  {batch.length ? ` (${batch.length})` : ''}
                </summary>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6,
                  marginTop: 6 }}>
                  <span className="ga-hint">
                    {t('Every animation you tick becomes its own clip, named after'
                       + ' itself, with its own counterpart preselected. The settings'
                       + ' above (set, target, reference pose) apply to all of them.'
                       + ' They run one after another.')}
                  </span>
                  <select
                    className="ga-input"
                    multiple
                    size={10}
                    value={batch.map(String)}
                    onChange={(e) => setBatch(
                      Array.from(e.target.selectedOptions, (o) => Number(o.value)))}
                  >
                    {takes.map((tk) => (
                      <option key={tk.index} value={tk.index}>
                        {tk.name} — {tk.duration_s.toFixed(2)} s
                        {tk.group
                          ? ` · ${t('group of')} ${tk.group.length}`
                          : tk.pair != null ? ` + ${takes[tk.pair]?.name ?? ''}` : ''}
                      </option>
                    ))}
                  </select>
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                    <button
                      className="ga-btn ga-btn-sm"
                      type="button"
                      disabled={!batch.length || !!batchRun || unknownRig || loopBlocked}
                      onClick={runBatch}
                    >
                      {batchRun
                        ? `${t('Importing')} ${batchRun.done}/${batchRun.total}…`
                        : `${t('Import')} ${batch.length}`}
                    </button>
                    {batch.length ? (
                      <button className="ga-btn ga-btn-sm" type="button"
                        onClick={() => setBatch([])}>{t('Clear')}</button>
                    ) : null}
                  </div>
                  {batchResult.length ? (
                    <ul style={{ margin: 0, paddingLeft: 18, fontSize: '0.9em' }}>
                      {batchResult.map((r) => (
                        <li key={r.name} style={{ color: r.error ? 'var(--ga-danger, #e06c6c)' : undefined }}>
                          {r.name} → {r.error ? r.error : r.kind}
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </div>
              </details>
            ) : null}


            <label style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
              <span className="ga-hint">{t('Reference pose (optional)')}</span>
              <select className="ga-input" value={restFile} onChange={(e) => setRestFile(e.target.value)}>
                <option value="">{t('— none —')}</option>
                {takes.length > 1 ? (
                  <option value={entry.name}>{t('this file (another animation)')}</option>
                ) : null}
                {kin.map((e) => (
                  <option key={e.name} value={e.name}>{e.name}</option>
                ))}
              </select>
              <span className="ga-hint">
                {t('The bind pose of THIS rig — gives the bones their real twist.'
                   + ' Only files of the same rig family are offered; a pack'
                   + ' usually carries its own pose as one of its animations.')}
              </span>
            </label>

            {restFile && restTakes.length > 1 ? (
              <TakeSelect
                label={t('The reference pose animation')}
                takes={restTakes}
                value={restTake}
                onChange={setRestTake}
                placeholder={t('— pick one —')}
              />
            ) : null}

            <label style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
              <span className="ga-hint">{t('Clip kind (the file stem, lowercase, no "__")')}</span>
              <input className="ga-input" value={kind} onChange={(e) => setKind(e.target.value)} />
            </label>

            <label style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
              <span className="ga-hint">{t('Set (a subdirectory — empty is the neutral figure)')}</span>
              <select className="ga-input" value={clipSet} onChange={(e) => setClipSet(e.target.value)}>
                <option value="">{t('— neutral —')}</option>
                {sets.map((s) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
            </label>

            <div style={{ display: 'flex', gap: 8 }}>
              <label style={{ display: 'flex', flexDirection: 'column', gap: 3, flex: 1 }}>
                <span className="ga-hint">{t('Start (s)')}</span>
                <input className="ga-input" type="number" step="0.1" min="0" value={startS}
                  onChange={(e) => setStartS(e.target.value)} />
              </label>
              <label style={{ display: 'flex', flexDirection: 'column', gap: 3, flex: 1 }}>
                <span className="ga-hint">{t('End (s) — empty is the whole take')}</span>
                <input className="ga-input" type="number" step="0.1" min="0" value={endS}
                  onChange={(e) => setEndS(e.target.value)} />
              </label>
            </div>

            <label style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              <span className="ga-hint">{t('Playback speed ×')}</span>
              <input className="ga-input" type="number" step="0.05" min="0.1" max="4" style={{ width: 80 }}
                value={speed} onChange={(e) => setSpeed(e.target.value)} />
              <span className="ga-hint">{t('0.5 = half speed (twice as long); baked into the clip')}</span>
            </label>

            <label style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              <input type="checkbox" checked={loopOn} disabled={isPair}
                onChange={(e) => setLoopOn(e.target.checked)} />
              <span>{t('Cut to a seamless loop of at least')}</span>
              <input className="ga-input" type="number" step="0.5" min="0.5" style={{ width: 70 }}
                value={loopS} disabled={!loopOn || isPair}
                onChange={(e) => setLoopS(e.target.value)} />
              <span>s</span>
            </label>

            <RootMotionField t={t} value={rootMotion} onChange={setRootMotion}
              pair={isPair} loopOn={loopOn} />

            {/* The head levelling BAKES, so — unlike the turn dial above — the
                preview only shows it after the next probe. */}
            <label style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              <input type="checkbox" checked={levelHead}
                onChange={(e) => setLevelHead(e.target.checked)} />
              <span>
                {t('Level the head (take the source’s head lean out)')}
                <span className="ga-hint" style={{ marginLeft: 6 }}>
                  {t('for a source that holds the head wrong the whole take; its own head motion stays')}
                </span>
              </span>
            </label>

            <label style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
              <span className="ga-hint">{t('Target library')}</span>
              <select className="ga-input" value={target}
                onChange={(e) => setTarget(e.target.value as Target)}>
                <option value="licensed">{t('licensed library (local only)')}</option>
                <option value="free">{t('free library (tracked in git)')}</option>
              </select>
            </label>

            {target === 'free' ? (
              <label style={{ display: 'flex', gap: 6, alignItems: 'flex-start' }}>
                <input type="checkbox" checked={redistributable}
                  onChange={(e) => setRedistributable(e.target.checked)} />
                <span style={{ color: 'var(--warn, #d29922)' }}>
                  {t('Redistributable — put it in the free library. Only tick this when the licence allows passing the raw files on: everything in the free library is committed to git and travels with the repository.')}
                </span>
              </label>
            ) : null}

            {kindExists ? (
              <label style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                <input type="checkbox" checked={overwrite} onChange={(e) => setOverwrite(e.target.checked)} />
                <span style={{ color: 'var(--warn, #d29922)' }}>
                  {t('Overwrite the existing clip of this kind')}
                </span>
              </label>
            ) : null}

            <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
              <button
                type="button"
                className="ga-btn ga-btn-sm ga-btn-primary"
                disabled={importing || unknownRig || !kind.trim() || (target === 'free' && !redistributable)
                  || loopBlocked}
                onClick={runImport}
              >
                {importing ? t('Converting with Blender…') : t('Import')}
              </button>
              {imported ? (
                <>
                  <span className="ga-source">{t('imported as')} {imported.kind}</span>
                  {onCreatePose ? (
                    <button type="button" className="ga-btn ga-btn-sm"
                      // A clip that went into the LICENSED library is licensed
                      // or adult material: its catalog entry belongs in this
                      // world's layer, never in a committed file.
                      onClick={() => onCreatePose(imported.kind,
                        target === 'free' ? 'shared' : 'world')}>
                      {t('Create pose entry')}
                    </button>
                  ) : null}
                  <button type="button" className="ga-btn ga-btn-sm ga-btn-danger"
                    onClick={() => removeFiles(imported.files)}>
                    {t('Delete inbox file(s)')}
                  </button>
                </>
              ) : null}
            </div>

            <div className="ga-hint">
              {isPair
                ? `${t('Roles')}: ${['A', ...others.map((_o, i) => ROLES[i + 1].toUpperCase())].join(', ')}`
                  + ` — ${t('one kind, converted at a shared anchor.')}`
                : t('One Blender run of a few seconds; the new kind is selectable in the pose editor right after.')}
            </div>

            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <button type="button" className="ga-btn" disabled={probing || !entry || loopBlocked}
                onClick={() => void runProbe()}>
                {probing ? t('Converting preview…') : t('Preview with these settings')}
              </button>
              <span className="ga-hint">
                {t('Runs the conversion into a scratch folder — offset, window and reference pose exactly as the import would write them. Nothing is imported.')}
              </span>
            </div>
            {probe && !imported ? (
              <>
                <ClipPreview key={`probe:${probe.seq}`} urls={probe.urls} height={300}
                  importYaw={yawDeg} footprint={footprint}
                  rootDrop={footprint ? (rootDropOf?.(footprint) ?? 0) : 0} />
                <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end', flexWrap: 'wrap' }}>
                  <SliderInput
                    label={t('Turn the clip')}
                    unit="°"
                    title={t('Degrees the import bakes into the clip. The conversion aims the root’s FORWARD axis at +Z, which is the facing of a standing actor and the belly direction of a lying one — so a lying take needs its angle set here.')}
                    min={-180}
                    max={180}
                    step={5}
                    fineStep={1}
                    value={yawDeg}
                    onChange={setYawDeg}
                    sliderWidth="auto"
                    sliderStyle={{ flex: 1, minWidth: 90 }}
                    style={{ display: 'flex', flex: '1 1 260px' }}
                  />
                  <button type="button" className="ga-btn ga-btn-sm"
                    onClick={() => setYawDeg((v) => ((v - 90 + 540) % 360) - 180)}>−90°</button>
                  <button type="button" className="ga-btn ga-btn-sm"
                    onClick={() => setYawDeg((v) => ((v + 90 + 540) % 360) - 180)}>+90°</button>
                  <label style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                    <span className="ga-hint">{t('Turn against')}</span>
                    <select className="ga-input" value={footprint}
                      onChange={(e) => setFootprint(e.target.value)}>
                      <option value="">{t('grid only')}</option>
                      <option value="lie">{t('bed / lying surface')}</option>
                      <option value="seat">{t('seat')}</option>
                    </select>
                  </label>
                </div>
                <div className="ga-hint">{t('Preview of the current settings')} ({probe.seconds.toFixed(1)} s)</div>
              </>
            ) : null}
            {imported ? (
              <ClipPreview key={`${imported.kind}:${imported.seq}`} kind={imported.kind} height={300} />
            ) : null}
          </div>
        )}
      </section>
    </div>
  )
}
