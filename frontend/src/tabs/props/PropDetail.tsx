/**
 * PropDetail — detail panel of one prop.
 *
 * TWO COLUMNS, and since 2026-08-25 the split says what a prop IS:
 *
 *   left   the PROP's general fields (name, category, tags, sway) — and below
 *          them the MODEL VARIANTS, which carry everything about how the
 *          object looks: size, generation subject, ground offset, seasons and
 *          markers. The marker editor of the SELECTED variant sits under the
 *          strip, because it is dialled against the viewer opposite.
 *   right  the preview: the selected variant's source image, its mesh in the
 *          3D viewer with the 1.70 m reference figure, the persisted
 *          orientation fix and the mesh gallery.
 *
 * The prop's meshes are a GALLERY (`PropModelPanel`, one active file per
 * resolution tier) — upload and tier assignment live there, and clicking a
 * row previews that file in the viewer here. Since E2.3 a prop carries
 * SEVERAL such galleries, one per MODEL VARIANT (`PropVariantStrip`): the
 * selected variant decides which mesh the viewer shows, which gallery the
 * panel edits, which slot a re-mesh writes into — and which markers, which
 * size and which sink are being edited.
 *
 * Markers are OBJECT-LOCAL (`at` = [u, v, w] fractions of THAT variant's model
 * bounding box), so they travel with the mesh into any room.
 *
 * ONE DRAFT, ONE SAVE (2026-08-25). Every FIELD on this panel — the prop's
 * general ones and the five each variant owns — collects in a change buffer
 * (`pendingFields`) and reaches the server when "Save (n)" is pressed, in ONE
 * request and ONE sidecar write. Nothing here writes on blur any more, so the
 * three metres, the subject, the sink, a season and a marker of one variant
 * are one save instead of seven, and "Discard" is a real way back.
 *
 * What stays IMMEDIATE, and why: everything that moves a FILE or changes the
 * variant LIST — image render and upload, meshing, the mesh gallery, the
 * orientation fix, and add / on-off / delete of a variant. Those change what
 * the store indices, the mesh signature and a running generation address; a
 * draft of them would be a promise about files that do not exist yet. Their
 * reloads land UNDER the draft (`applyVariantDraft` puts it back on top), so
 * an unsaved size survives a mesh that finishes in the background.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { FIGURE_HEIGHT_M } from '@anima/scene-render'
import { DetailToolbar } from '../../components/DetailToolbar'
import { Field } from '../../components/Field'
import { ExportButton, PublishButton } from '../../components/ImportExport'
import { SliderInput } from '../../components/SliderInput'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { setUnsavedGuard } from '../../lib/unsavedGuard'
import {
  applyVariantDraft, draftValue, dropDeletedVariant, emptyFields,
  GENERAL_TARGET, pendingFieldCount, queueFields, toBulkFieldBody,
  variantTarget, type PendingFields,
} from './pendingFields'
import { Model3DViewer } from '../characters/Model3DViewer'
import { GroundOffsetGauge } from './GroundOffsetGauge'
import { PropAreasPanel } from './PropAreasPanel'
import { PropModelPanel } from './PropModelPanel'
import { PropVariantStrip } from './PropVariantStrip'
import {
  groupKeys, groupLabel, newId, posesInGroup, previewEntry, usePoseCatalog,
} from '../world/placeTypes'
import { CATEGORY_DATALIST_ID } from './propTypes'
import type { DimKey } from './dims'
import type {
  PropFull, PropMarker, PropSlot, PropSlotKind, PropSourceImage, PropVariant,
} from './propTypes'

/**
 * The scale kit of the 3D preview — the 1.70 m reference figure beside the
 * prop plus the metre grid under both (rule "Kein Maß ohne Maßstab").
 * Remembered per browser, ON until it is switched off: a mesh alone says
 * nothing about its size, so the first look should already carry the scale.
 */
const SCALE_FIGURE_KEY = 'ga.props.scaleFigure'

/** Storage can throw (private mode, site data off) and can hold anything —
 *  every path ends at the default rather than at a broken panel. */
function loadScaleFigure(): boolean {
  try {
    const raw = window.localStorage.getItem(SCALE_FIGURE_KEY)
    return raw === null ? true : raw !== '0'
  } catch { return true }
}

function saveScaleFigure(on: boolean): void {
  try { window.localStorage.setItem(SCALE_FIGURE_KEY, on ? '1' : '0') }
  catch { /* a browser that refuses storage still gets its figure */ }
}

// Marker `at` = fractions of the RAW box in the order [X, Y, Z] — mirrors
// props.MARKER_AT_MIN/MAX: half a box of slack per axis, because seats and
// lying surfaces sit ON the hull or just outside it.
const AT_MIN = -0.5
const AT_MAX = 1.5
// The height axis reaches a FULL box below (props.MARKER_AT_Y_MIN) — deep
// seat positions in tall machines sit far under the box top.
const AT_AXES: Array<{ label: string; dim: DimKey; min: number }> = [
  { label: 'X (width)', dim: 'width_m', min: AT_MIN },
  { label: 'Y (height)', dim: 'height_m', min: -1 },
  { label: 'Z (depth)', dim: 'depth_m', min: AT_MIN },
]

/** The two things a texture slot can take — the server's `props.SLOT_KINDS`,
 *  with the label each one gets in the picker. */
const SLOT_KINDS: Array<{ kind: PropSlotKind; label: string }> = [
  { kind: 'image', label: 'Image' },
  { kind: 'material', label: 'Material' },
]

export function PropDetail({ prop, pending, generatingVariants, cacheBump,
  onChanged, onDelete, armedDelete, onRegenerate, onRegenerateMesh,
  onRegenerateImage, onRefresh, onGenerating, onDirtyChange }: {
  prop: PropFull
  /** ANY variant of this prop is generating — the aggregate. Only the two
   *  prop-level actions read it; everything variant-scoped asks
   *  `generatingVariants` instead. */
  pending: boolean
  /** STORE indices with a run in flight (server state, polled by the
   *  container). A variant switched off keeps its index, so these are matched
   *  against a chip's `index`, never against its position in the strip. */
  generatingVariants: number[]
  cacheBump: number
  onChanged: () => Promise<unknown>
  onDelete: () => void
  armedDelete: boolean
  /** Re-mesh the EXISTING source image (skips the image render) INTO the
   *  variant the admin currently has open — the index travels with the call,
   *  because the dialog that runs it lives in the container. */
  onRegenerateMesh: (variant: number) => void
  /** Re-run the source→mesh chain with the stored description/name — this
   *  APPENDS another model variant. */
  onRegenerate: () => void
  /** Render a NEW source image for the SELECTED variant only — its mesh stays
   *  until re-meshed, and no other variant's image is touched. The variant's
   *  current image record travels along so the dialog opens on the backend
   *  THIS picture was made with. */
  onRegenerateImage: (variant: number, image?: PropSourceImage,
    subject?: string) => void
  /** Reload the prop + bust the image cache — generations run in the
   *  background, this fetches the current state on demand. */
  onRefresh: () => void
  /** Start the container's pending poll — a background job was just kicked
   *  off from inside the detail (the mesh gallery's low variant). */
  onGenerating: () => void
  /** How many FIELD edits are waiting in the draft (0 = clean). The container
   *  asks before it lets the selection leave this prop — a tab switch is the
   *  shell's question, a prop switch has to be this tab's own. */
  onDirtyChange: (count: number) => void
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const enc = encodeURIComponent(prop.id)
  // Which stored mesh the viewer shows ('' = the active one the clients get).
  // A filename is only valid inside ONE variant's gallery, so switching the
  // variant drops it as surely as switching the prop does.
  const [previewFile, setPreviewFile] = useState('')

  // ── Model variants (E2.3) ──────────────────────────────────────────────
  // ONE reload key for everything that reads this prop's meshes: the
  // container's cacheBump (a background generation finished) plus every local
  // change made here — a gallery row selected or deleted, a variant added,
  // toggled or removed. The strip and the gallery must never disagree about
  // which tiers exist, so they reload off the same number.
  const [localBump, setLocalBump] = useState(0)
  const reloadKey = cacheBump + localBump
  const meshesChanged = useCallback(async () => {
    setLocalBump((n) => n + 1)
    return onChanged()
  }, [onChanged])

  // ── THE DRAFT (2026-08-25) ─────────────────────────────────────────────
  // Every field edit of this prop, waiting for one explicit Save. It is keyed
  // by target ("general" / "v:<store index>") and merges field by field, so
  // editing the size and then the subject of one variant is one entry with two
  // fields — see `pendingFields` for the rules.
  const [buf, setBuf] = useState<PendingFields>(emptyFields)
  const [saving, setSaving] = useState(false)
  /** The Discard button's second click (no `window.confirm` in this UI). */
  const [discardArmed, setDiscardArmed] = useState(false)
  const dirtyCount = pendingFieldCount(buf)
  useEffect(() => { if (!dirtyCount) setDiscardArmed(false) }, [dirtyCount])
  const queueGeneral = useCallback((patch: Record<string, unknown>) => {
    setBuf((b) => queueFields(b, GENERAL_TARGET, patch))
  }, [])
  const queueVariant = useCallback((index: number,
    patch: Record<string, unknown>) => {
    setBuf((b) => queueFields(b, variantTarget(index), patch))
  }, [])

  const [serverVariants, setServerVariants] = useState<PropVariant[]>([])
  const [variantMax, setVariantMax] = useState(1)
  // The world's season names + the one it is in now (E2c) — the season chips
  // are a pick from this list, and an empty list (a world without seasons)
  // means the strip shows no season controls at all.
  const [worldSeasons, setWorldSeasons] = useState<string[]>([])
  const [currentSeason, setCurrentSeason] = useState('')
  // The variant everything below the strip works on. Index, not stem: that is
  // what every variant-scoped route takes.
  const [variant, setVariant] = useState(0)
  // Dropping the list with the selection matters: a record of the PREVIOUS
  // prop would otherwise answer for the same index until the reload lands.
  // The draft goes with it — it belongs to the prop that was open, and the
  // container has already asked whether it may be lost.
  useEffect(() => {
    setVariant(0)
    setServerVariants([])
    setBuf(emptyFields())
  }, [prop.id])
  useEffect(() => { setPreviewFile('') }, [prop.id, variant])
  const loadVariants = useCallback(async () => {
    try {
      const d = await apiGet<{ variants?: PropVariant[]; max?: number
        world_seasons?: string[]; current_season?: string }>(
        `/world/props/${enc}/variants`)
      const list = d.variants || []
      setServerVariants(list)
      setVariantMax(d.max || 1)
      setWorldSeasons(d.world_seasons || [])
      setCurrentSeason(d.current_season || '')
      // Clamping belongs HERE and not in an effect of its own: a deletion
      // shortens the list, and a separate effect would fight the strip, which
      // selects the freshly added slot before its record has arrived.
      setVariant((i) => (list.length ? Math.min(i, list.length - 1) : 0))
    } catch {
      setServerVariants([])
    }
  }, [enc])
  useEffect(() => { void loadVariants() }, [loadVariants, reloadKey])
  // WHAT EVERYTHING BELOW READS: the server's list with the draft laid on top.
  // A background reload (a finished mesh, an added variant) therefore cannot
  // eat an unsaved number, and the 3D preview, the reference figure and the
  // marker read-backs all measure against what is on screen.
  const variants = useMemo(() => applyVariantDraft(serverVariants, buf),
    [serverVariants, buf])
  const shownVariant = variants.find((v) => v.index === variant) || null
  // Is the variant the detail has OPEN the one that is generating? Every
  // variant-scoped action below reads this instead of the prop-level flag —
  // rendering variant 3's image must not put "Generating…" on variant 1.
  const variantBusy = generatingVariants.includes(variant)
  // Until the list has arrived the prop record answers for the first variant —
  // `has_model` there IS the primary variant's state, so the viewer does not
  // flash its empty box on every prop switch.
  const shownHasMesh = shownVariant
    ? shownVariant.has_model
    : variant === 0 && prop.has_model
  // The SOURCE IMAGE belongs to the variant just like its meshes do (variant 0
  // keeps the historic `source.png`, every further one has `source-v<n>.png`),
  // so the left pane shows, re-renders and uploads THIS variant's picture. The
  // prop record answers only until the list has arrived — its image fields ARE
  // the primary variant's.
  const shownImage: PropSourceImage | null = shownVariant
    ? (shownVariant.has_source ? shownVariant.image : null)
    : (variants.length === 0 && variant === 0 && prop.has_source
      ? { backend: prop.backend_image || '', prompt: prop.prompt || '',
        negative: prop.negative || '', generated_at: prop.source_generated_at || '' }
      : null)

  const [nameDraft, setNameDraft] = useState(prop.name)
  const [categoryDraft, setCategoryDraft] = useState(prop.category)
  const [tagsDraft, setTagsDraft] = useState(prop.tags.join(', '))
  // The wind factor as a string draft — committed on blur/Enter. Its own sync
  // effect (below) is enough: the deps are the primitive value, so a
  // background poll that changes nothing re-renders without touching what the
  // admin is typing.
  const [swayDraft, setSwayDraft] = useState(String(prop.sway_factor ?? 1))
  useEffect(() => {
    setSwayDraft(String(prop.sway_factor ?? 1))
  }, [prop.id, prop.sway_factor])
  // Drafts re-arm on PROP CHANGE only — the background poll reloads the
  // list every few seconds while a generation runs, and resetting on every
  // fresh object identity overwrote whatever the admin was typing (user
  // finding 2026-08-02: the description reverted mid-edit).
  useEffect(() => {
    setNameDraft(prop.name)
    setCategoryDraft(prop.category)
    setTagsDraft(prop.tags.join(', '))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prop.id])
  // What the four general fields SAY right now: the buffered value once they
  // were edited, the stored one before that. Every commit compares against
  // these, never against the prop record — a field typed away and back must
  // end up with what is on screen, not with a stale entry in the buffer. The
  // tags travel as the raw comma text; splitting them is the server's
  // (`props._coerce_tags`), and has been since long before the draft.
  const nameNow = draftValue(buf, GENERAL_TARGET, 'name', prop.name)
  const categoryNow = draftValue(buf, GENERAL_TARGET, 'category', prop.category)
  const tagsNow = draftValue(buf, GENERAL_TARGET, 'tags', prop.tags.join(', '))
  const swayNow = draftValue<number>(buf, GENERAL_TARGET, 'sway_factor',
    prop.sway_factor ?? 1)

  // ── TEXTURE SLOTS ──────────────────────────────────────────────────────
  // The fillable surfaces of the mesh, a plain list of {name, kind}. They
  // belong to the OBJECT (a slot IS a material of the model), so they sit here
  // beside the sway factor and not on a variant. The list needs no local
  // typing state: it lives in the draft, which is also what the rows render
  // from — one buffered FIELD however many rows are edited.
  const slots = draftValue<PropSlot[]>(buf, GENERAL_TARGET, 'slots',
    prop.slots || [])
  const saveSlots = useCallback((next: PropSlot[]) => {
    queueGeneral({ slots: next })
  }, [queueGeneral])
  const patchSlot = (i: number, patch: Partial<PropSlot>) =>
    saveSlots(slots.map((s, idx) => (idx === i ? { ...s, ...patch } : s)))
  // What the server would do with this list, said BEFORE the save: a nameless
  // slot is a 400 for the whole batch, and a name given twice collapses to its
  // first entry. Both are silent surprises otherwise ("Saved" and a row gone).
  const slotProblem = useMemo(() => {
    const names = slots.map((s) => (s.name || '').trim().toLowerCase())
    if (names.some((n) => !n)) return t('A slot without a name cannot be saved.')
    if (new Set(names).size !== names.length) {
      return t('Two slots share a name — only the first one would be kept.')
    }
    return ''
  }, [slots, t])

  // The RAW box of the mesh the viewer has OPEN, i.e. the SELECTED variant's,
  // measured on load. What the overlays scale by is the mesh on screen: a
  // variant's own GLB has its own proportions, and measuring another one's box
  // would size the figure beside a stranger.
  const [shownBbox, setShownBbox] = useState<[number, number, number] | null>(null)
  // The scale kit of the viewer (figure + metre grid) — a VIEW, so it is
  // remembered in the browser and never on the prop.
  const [scaleFigure, setScaleFigure] = useState(loadScaleFigure)
  // Source image beside the model (left pane of the split preview) — the
  // server says whether THIS variant has one; the flag only catches a 404 that
  // races the list (a delete between load and render).
  const [srcOk, setSrcOk] = useState(true)
  // Another variant (or another file of it) means another mesh — its box is
  // measured when it has loaded, never inherited from the one before.
  useEffect(() => { setShownBbox(null) }, [prop.id, variant, previewFile])
  useEffect(() => { setSrcOk(true) }, [prop.id, variant, reloadKey])

  // How big the DISPLAYED variant really is — the size belongs to the VARIANT
  // (2026-08-25), so this is a plain read of the chip that is open. Everything
  // the viewer measures with hangs on it: the reference figure, the dims
  // overlay and the metres the marker sliders read back. Until the variant
  // list has arrived the prop record answers, and its dims ARE the primary
  // variant's.
  const shownDims = useMemo(() => (shownVariant ? shownVariant.dims : {
    width_m: prop.width_m, depth_m: prop.depth_m, height_m: prop.height_m,
  }), [shownVariant, prop.width_m, prop.depth_m, prop.height_m])

  // Same source rule as the dims: the shown variant answers, the prop record
  // stands in until the variant list has arrived (its value IS the primary
  // variant's).
  const shownSurface = shownVariant?.surface_status ?? prop.surface_status ?? null
  const surfaceLabel = shownSurface?.state === 'baked'
    ? t('baked {cols}×{rows} @ {step} m')
      .replace('{cols}', String(shownSurface.cols ?? '?'))
      .replace('{rows}', String(shownSurface.rows ?? '?'))
      .replace('{step}', String(shownSurface.step ?? '?'))
    : shownSurface?.state === 'stale'
      ? t('stale (model or fix changed)')
      : t('missing')

  // ── Save / Discard ─────────────────────────────────────────────────────
  // ONE request for the whole panel: the general fields and every variant
  // patch travel in the batch body, the answer is what was really stored, and
  // the client adopts THAT rather than believing its own draft.
  const save = useCallback(async () => {
    const body = toBulkFieldBody(buf)
    setSaving(true)
    try {
      const d = await apiPost<{ variants?: PropVariant[] }>(
        `/world/props/${enc}/bulk`, body)
      setBuf(emptyFields())
      if (d?.variants) setServerVariants(d.variants)
      // The prop record (name, category, the library row) is the container's —
      // it reloads the list, which is also what the marker/mesh counts hang on.
      await onChanged()
      toast(t('Saved'))
    } catch (e) {
      // Nothing was written (the batch validates before it stores), so the
      // draft stays exactly as it is and Save can simply be pressed again.
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setSaving(false)
    }
  }, [buf, enc, onChanged, t, toast])

  /** Throw the draft away and show what the server has. The four text inputs
   *  hold their own typing state, so they are re-armed here as well — a
   *  Discard that left the old text standing in the boxes would look like it
   *  had done nothing. */
  const discard = useCallback(() => {
    setBuf(emptyFields())
    setDiscardArmed(false)
    setNameDraft(prop.name)
    setCategoryDraft(prop.category)
    setTagsDraft(prop.tags.join(', '))
    setSwayDraft(String(prop.sway_factor ?? 1))
  }, [prop.name, prop.category, prop.tags, prop.sway_factor])

  // Leaving with a full buffer must not happen silently: the browser's own
  // question for a reload or a closed tab, the shell's for a tab switch (the
  // tab is unmounted then, and the draft would die with it), the container's
  // for a switch to another prop.
  const dirtyRef = useRef(0)
  dirtyRef.current = dirtyCount
  useEffect(() => {
    if (!dirtyCount) return
    const warn = (e: BeforeUnloadEvent) => {
      e.preventDefault()
      // The browser shows its own generic wording; the value only needs to be
      // non-null for legacy engines.
      e.returnValue = ''
    }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [dirtyCount])
  useEffect(() => {
    setUnsavedGuard(() => dirtyRef.current > 0)
    return () => setUnsavedGuard(null)
  }, [])
  useEffect(() => { onDirtyChange(dirtyCount) }, [dirtyCount, onDirtyChange])
  // The panel is gone (the prop was deleted, the create form opened): nothing
  // is unsaved any more, and a container that still believed otherwise would
  // ask about a draft nobody can see.
  useEffect(() => () => onDirtyChange(0), [onDirtyChange])

  // Upload a picture as THIS variant's source image — the same act as
  // uploading a GLB into its gallery, one step earlier in the chain: what the
  // ⚙ re-mesh below then works from. Variant-scoped route, so it can never
  // overwrite another version's picture.
  const sourceUploadRef = useRef<HTMLInputElement>(null)
  const uploadSource = useCallback(async (file: File) => {
    try {
      const fd = new FormData()
      fd.append('file', file)
      const res = await fetch(`/world/props/${enc}/variants/${variant}/source`,
        { method: 'POST', body: fd, credentials: 'same-origin' })
      const body = await res.json().catch(() => null)
      if (!res.ok) throw new Error(body?.detail?.toString?.() || `HTTP ${res.status}`)
      await meshesChanged()
      toast(t('Saved'))
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [enc, variant, meshesChanged, t, toast])

  // An empty or unreadable field is not a factor: it commits the default 1,
  // and the server answers by dropping the key. Clamped here as well so the
  // input echoes back what will actually be stored.
  const commitSway = useCallback(() => {
    const n = parseFloat(swayDraft)
    const next = Number.isFinite(n) ? Math.min(Math.max(n, 0), 1) : 1
    setSwayDraft(String(next))
    if (next === swayNow) return
    queueGeneral({ sway_factor: next })
  }, [swayDraft, swayNow, queueGeneral])

  const rotate = useCallback(async (axis: 'x' | 'y' | 'z') => {
    const cur = prop.rotation || {}
    try {
      await apiPost(`/world/props/${enc}/rotation`, {
        x: cur.x || 0, y: cur.y || 0, z: cur.z || 0,
        [axis]: ((cur[axis] || 0) + 90) % 360,
      })
      await onChanged()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [prop.rotation, enc, onChanged, t, toast])

  const setRotationAxis = useCallback(async (axis: 'x' | 'y' | 'z', raw: string) => {
    const n = parseFloat(raw)
    const v = Number.isFinite(n) ? ((n % 360) + 360) % 360 : 0
    if (v === (prop.rotation?.[axis] || 0)) return
    const cur = prop.rotation || {}
    try {
      await apiPost(`/world/props/${enc}/rotation`, {
        x: cur.x || 0, y: cur.y || 0, z: cur.z || 0, [axis]: v,
      })
      await onChanged()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [prop.rotation, enc, onChanged, t, toast])

  // The walkable surface of the SHOWN variant's mesh. Blender bakes it in the
  // background, so the answer is only "queued" — but the record is reloaded
  // right away all the same: the bake INVALIDATES what the status line shows
  // (a valid lattice becomes the one being replaced), and every other action
  // on this panel refreshes the record it edited. Without it the line kept
  // saying "baked 33×33" until something else happened to reload the prop.
  const bakeSurface = useCallback(async () => {
    try {
      await apiPost(`/world/props/${enc}/surface`, { variant })
      toast(t('Baking the surface — this runs in the background.'))
      await onChanged()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [enc, variant, onChanged, t, toast])

  // Object-local PLACES (A4, plan-posen-plaetze.md § 4) — same vocabulary as
  // room markers, but the frame is the MESH's own bounding box: `at` =
  // [u, v, w] fractions, `facing` = degrees. The fractions may leave the box
  // by half a box per axis (seats sit ON the hull, see
  // props.sanitize_markers).
  //
  // A marker names a PLACE TYPE (`group`: seat, bed, floor …), never a clip —
  // which pose is played there is the character's business, and the ◀ ▶
  // cycler below only decides which one the preview figures hold.
  //
  // They belong to the VARIANT since 2026-08-25: a fraction of one mesh's box
  // means nothing on another bake, so the editor below always edits the chip
  // the viewer has open, and the write goes to that variant's route.
  const poseCatalog = usePoseCatalog()
  const groups = poseCatalog.groups
  // Which pose of its place type a marker's preview figures play, keyed by
  // marker id. VIEW state only — nothing of it is stored.
  const [previewPose, setPreviewPose] = useState<Record<string, string>>({})
  // THE MARKER LIST IS THE DRAFT'S. It needs no local state of its own any
  // more and no debounce: an edit goes into the change buffer, the buffer is
  // what `variants` above is drawn from, and the viewer beside it reads the
  // very same array — so dragging a slider is immediate on screen and costs
  // exactly one field of one save. Until the variant record has arrived the
  // prop record answers for the primary variant, as everywhere else here.
  const markers: PropMarker[] = useMemo(() => (
    shownVariant ? shownVariant.markers
      : (variant === 0 ? prop.markers || [] : [])
  ), [shownVariant, variant, prop.markers])

  // The place types a new marker is offered, in picker order; a new marker
  // takes the first of them.
  const groupOptions = useMemo(() => groupKeys(groups), [groups])
  const firstGroup = groupOptions[0] || ''

  const saveMarkers = useCallback((next: PropMarker[]) => {
    queueVariant(variant, { markers: next })
  }, [queueVariant, variant])

  const patchMarker = (i: number, patch: Partial<PropMarker>) =>
    saveMarkers(markers.map((m, idx) => (idx === i ? { ...m, ...patch } : m)))
  const setMarkerAt = (i: number, axis: 0 | 1 | 2, raw: number | string) => {
    const n = typeof raw === 'number' ? raw : parseFloat(raw)
    const lo = AT_AXES[axis].min
    const v = Number.isFinite(n) ? Math.min(Math.max(n, lo), AT_MAX) : 0
    const at = [...markers[i].at] as [number, number, number]
    at[axis] = Math.round(v * 10000) / 10000
    patchMarker(i, { at })
  }
  const addMarker = () =>
    saveMarkers([...markers, { id: newId(), group: firstGroup, at: [0.5, 0, 0.5] }])
  const removeMarker = (i: number) =>
    saveMarkers(markers.filter((_, idx) => idx !== i))

  // Floor-plan-style placement: arm ('add' or a marker index), then click the
  // mesh in the viewer — the hit lands as raw-box fractions. Esc disarms.
  const [placing, setPlacing] = useState<'add' | number | null>(null)
  useEffect(() => { setPlacing(null) }, [prop.id, variant])
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setPlacing(null) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])
  const onPickPoint = useCallback((at: [number, number, number]) => {
    setPlacing((cur) => {
      if (cur === 'add') {
        saveMarkers([...markers, { id: newId(), group: firstGroup, at }])
      } else if (cur !== null && markers[cur]) {
        saveMarkers(markers.map((m, idx) => (idx === cur ? { ...m, at } : m)))
      }
      return null
    })
  }, [markers, firstGroup, saveMarkers])

  return (
    <>
      <DetailToolbar
        title={prop.name}
        onDelete={onDelete}
        deleteLabel={armedDelete ? t('Really delete?') : t('Delete prop')}
        // THE DRAFT. Save exists only while there IS one — a permanently
        // greyed-out button teaches nothing about when it would do something —
        // and its number is the only place the size of the unsaved work is
        // visible. `disabled` gates the whole bar while the batch is in flight.
        onSave={dirtyCount > 0 ? () => { void save() } : undefined}
        saveLabel={saving
          ? t('Saving…')
          : t('Save ({n})').replace('{n}', String(dirtyCount))}
        disabled={saving}
        extra={
          <>
            {dirtyCount > 0 ? (
              <>
                <button type="button"
                  className={'ga-btn ga-btn-sm' + (discardArmed ? ' ga-btn-danger' : '')}
                  disabled={saving}
                  title={t('Throw the unsaved field changes away and take what the server has')}
                  onClick={() => {
                    if (discardArmed) discard()
                    else setDiscardArmed(true)
                  }}>
                  {discardArmed
                    ? t('Really discard {n}').replace('{n}', String(dirtyCount))
                    : t('Discard')}
                </button>
                {discardArmed ? (
                  <button type="button" className="ga-btn ga-btn-sm"
                    onClick={() => setDiscardArmed(false)}>
                    {t('Cancel')}
                  </button>
                ) : null}
              </>
            ) : null}
            {/* The one PROP-level action: it does not name a variant, the
                server picks the target (an empty slot, a fresh one, or the
                last one at the cap). Two of those at once would race for the
                same slot, so it stays gated on the prop's aggregate — unlike
                everything below the strip, which names its variant. */}
            <button type="button" className="ga-btn ga-btn-sm"
              disabled={pending}
              onClick={onRegenerate}
              title={pending
                ? t('A generation of this prop is already running — it picks the variant it appends to, so only one at a time.')
                : `${t('Re-render the source image from the target variant’s description (the prop’s name as fallback) and mesh it as ANOTHER model variant of this prop — the existing variants stay untouched. At the limit the run lands in the last variant.')} ${t('Maximum active variants:')} ${variantMax}`}>
              🧊 {pending ? t('Generating…') : t('Regenerate')}
            </button>
            {/* The whole props/<id>/ folder travels: sidecar, meshes,
                selection and source render. */}
            <ExportButton
              endpoint={`/world/props/${encodeURIComponent(prop.id)}/export`}
              filename={`prop_${prop.id}.zip`}
              title={t('Download the prop as a ZIP (mesh, source image, dims and markers)')}
            />
            <PublishButton packType="prop" entityId={prop.id} defaultName={prop.name} />
          </>
        }
      />
      <div className="ga-detail-cols">
        {/* Inputs: everything the sidecar stores. */}
        <div className="ga-form">
          {/* Editable sidecar fields. */}
          <div className="ga-form-section-label">{t('Properties')}</div>
          <div className="ga-form-row">
            <Field label={t('Name')}>
              <input className="ga-input" value={nameDraft}
                onChange={(e) => setNameDraft(e.target.value)}
                onBlur={() => {
                  // A prop without a name is not a state the server stores, so
                  // an emptied field snaps back to the current one.
                  const nm = nameDraft.trim()
                  if (nm && nm !== nameNow) queueGeneral({ name: nm })
                  else setNameDraft(nameNow)
                }}
                onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }} />
            </Field>
            <Field label={t('Category')}>
              <input className="ga-input" list={CATEGORY_DATALIST_ID} value={categoryDraft}
                onChange={(e) => setCategoryDraft(e.target.value)}
                onBlur={() => {
                  if (categoryDraft !== categoryNow) {
                    queueGeneral({ category: categoryDraft })
                  }
                }} />
            </Field>
            <Field label={t('Tags (comma-separated)')}
              hint={t('Tag "walkable" lets figures stand on this prop; its surface is baked from the mesh.')}>
              <input className="ga-input" value={tagsDraft}
                onChange={(e) => setTagsDraft(e.target.value)}
                onBlur={() => {
                  if (tagsDraft !== tagsNow) queueGeneral({ tags: tagsDraft })
                }} />
            </Field>
            {/* The one number that describes the WHOLE object rather than one
                of its versions: how hard it bends in the wind. It rides the
                same row as the other prop-wide fields instead of holding a
                line of its own for one narrow number (§ B1). Size, subject,
                sink and markers moved into the variants (2026-08-25). */}
            <Field label={t('Sway factor')}>
              <input className="ga-input" type="number" min={0} max={1} step={0.05}
                value={swayDraft}
                title={t('How much of its ground’s wind this prop takes part in when it is scattered over a painted area: the terrain kind says how far things bend there, this multiplies it. 1 = the full amount, 0 = stands still whatever blows, empty = 1. Very small products stand still as well — the deflection only starts at about 0.005 m, so on a ground that bends 0.06 m every factor up to 0.08 comes to a standstill.')}
                onChange={(e) => setSwayDraft(e.target.value)}
                onBlur={commitSway}
                onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }} />
            </Field>
          </div>

          {/* THE TEXTURE SLOTS — the surfaces of this mesh that can be filled
              later (a frame that takes a picture, a pane that takes glass).
              The import reads a first draft off the model's material names;
              this is where it is corrected. */}
          <div className="ga-form-section-label">
            {t('Texture slots')}
            {prop.slots_auto && slots.length ? (
              <span className="ga-hint" style={{ marginLeft: 6, fontWeight: 400 }}
                title={t('This list was read off the model’s material names, and every new mesh re-reads it. Editing it makes it yours — from then on no model overwrites it.')}>
                · {t('detected')}
              </span>
            ) : null}
          </div>
          <span className="ga-hint">
            {t('Surfaces of the mesh that can be filled later: a material named “slot_<name>” is one, and so are the plain names picture, screen, sign (image) and glass (material). Read off every mesh that lands — correct it here, and no later mesh touches your list again.')}
          </span>
          {slots.length === 0 ? (
            <div className="ga-hint" style={{ fontSize: '0.85em' }}>
              {t('No texture slots — the model names none.')}
            </div>
          ) : (
            slots.map((s, i) => (
              <div key={i} className="ga-form-row">
                <input className="ga-input" style={{ flex: 1, minWidth: 0 }}
                  value={s.name}
                  placeholder={t('Slot name')}
                  title={t('The material name in the model, lower-case (the “slot_” prefix is not part of it).')}
                  onChange={(e) => patchSlot(i, { name: e.target.value })} />
                <select className="ga-input" style={{ width: 120 }}
                  value={s.kind}
                  title={t('What fills it: an image (a picture on the surface) or a material (glass, mirror, matte).')}
                  onChange={(e) => patchSlot(i,
                    { kind: e.target.value as PropSlotKind })}>
                  {SLOT_KINDS.map((k) => (
                    <option key={k.kind} value={k.kind}>{t(k.label)}</option>
                  ))}
                </select>
                <button type="button" className="ga-btn ga-btn-sm ga-btn-danger"
                  title={t('Remove this texture slot')}
                  onClick={() => saveSlots(slots.filter((_, idx) => idx !== i))}>
                  ×
                </button>
              </div>
            ))
          )}
          {slotProblem ? (
            <span className="ga-hint" style={{ color: 'var(--warn, #d29922)' }}>
              {slotProblem}
            </span>
          ) : null}
          <div>
            <button type="button" className="ga-btn ga-btn-sm"
              title={t('Add a slot by hand — for a material the detection does not know by name.')}
              onClick={() => saveSlots([...slots, { name: '', kind: 'image' }])}>
              + {t('Texture slot')}
            </button>
          </div>

          {/* Measured in the mesh itself — the cost of placing this prop
              many times, which the sizes below say nothing about. */}
          {prop.measured?.tris ? (
            <span className="ga-hint">
              {`${prop.measured.tris.toLocaleString()} ${t('tris')}`}
              {prop.measured.uv_layers === 0 && (prop.measured.vertex_colors || 0) > 0
                ? ` · ${t('no UVs, colour in the vertices')}`
                : ''}
            </span>
          ) : null}

          {prop.prompt ? (
            <span className="ga-hint" style={{ fontSize: '0.78em' }} title={prop.prompt}>
              {prop.source === 'generated' ? t('Generated') : t('Source')}
              {prop.backend ? ` · ${prop.backend}` : ''} · {prop.prompt}
            </span>
          ) : null}

          {/* THE VARIANTS — several meshes of the same object, each with its
              own size, subject, sink, seasons and markers. The selected chip
              decides what the viewer opposite shows and what the gallery and
              the marker editor below act on. */}
          <PropVariantStrip
            propId={prop.id}
            variants={variants}
            max={variantMax}
            selected={variant}
            onSelect={setVariant}
            onChanged={meshesChanged}
            onEditVariant={queueVariant}
            // A deleted variant renumbers the list, so the draft is renumbered
            // with it — an unsaved size must never land on the neighbour that
            // moved into the gap.
            onDeleted={(index) => setBuf((b) => dropDeletedVariant(b, index))}
            generating={generatingVariants}
            worldSeasons={worldSeasons}
            currentSeason={currentSeason}
            // The proportions a variant's W/D/H redistribute along: the box of
            // the mesh ON SCREEN, which belongs to the SELECTED chip. Every
            // other chip falls back to its own stored dims inside the strip.
            shownBbox={shownBbox}
            rotation={prop.rotation}
          />

          {/* THE SELECTED VARIANT, dialled against the viewer opposite: the
              1.70 m figure that makes its ground offset judgeable, and its
              object-local markers. Both are the variant's, and both need the
              mesh beside them — which is why they stand here and not inside
              the chip. */}
          <div className="ga-form-section-label">
            {t('Variant')} {variant + 1} · {t('Markers')}
          </div>
          {/* The visible reference (Maße brauchen Bezug): the sink is only
              judgeable against this variant's own box and a person. The
              SLIDER in the chip follows the variant's height too — a footstool
              is dialled in its own centimetres, a tree in its own metres —
              while the stored limit stays ±5 m. */}
          <GroundOffsetGauge offsetM={shownVariant?.ground_offset_m ?? 0}
            widthM={shownDims.width_m}
            heightM={shownDims.height_m} />
          <span className="ga-hint">
            {t('Object-local PLACES a character is seated on — each names a place type (seat, bed, floor …) and takes as many figures as its capacity. They belong to THIS variant, because at = fraction of ITS model bounding box (X = width, Y = height, Z = depth); the range reaches from -0.5 to 1.5, because seats and lying surfaces sit on the hull or just outside it. Place roughly with ✥, fine-tune with the sliders — the figures in the preview follow live.')}
          </span>
          {markers.length === 0 ? (
            <div className="ga-empty" style={{ fontSize: '0.85em' }}>{t('No markers yet.')}</div>
          ) : (
            markers.map((m, i) => {
              const capacity = m.capacity || 1
              // The poses of this marker's PLACE TYPE, its default first —
              // the ◀ ▶ cycler picks which one the preview figures hold. View
              // state only, keyed by the marker's id; a marker stored before
              // ids existed gets one minted into the draft on the first click.
              const poses = posesInGroup(poseCatalog, m.group)
              const poseIdx = Math.max(0, poses.indexOf(
                (m.id && previewPose[m.id]) || poses[0]))
              const setPreview = (pose: string) => {
                const id = m.id || newId()
                if (!m.id) patchMarker(i, { id })
                setPreviewPose((cur) => ({ ...cur, [id]: pose }))
              }
              return (
              <div key={i} className="ga-marker-card">
                <div className="ga-form-row">
                  <span className="ga-hint" style={{ minWidth: 20 }}>🎯 {i + 1}</span>
                  <select
                    className="ga-input"
                    style={{ flex: 1, minWidth: 0 }}
                    value={m.group}
                    title={t('Place type of the pose catalog (seat, bed, floor …) — WHAT this spot is, not which clip plays on it. A character taking a pose of this type is seated here.')}
                    onChange={(e) => patchMarker(i, { group: e.target.value })}
                  >
                    {groupOptions.map((k) => (
                      <option key={k} value={k}>{groupLabel(groups, k)}</option>
                    ))}
                    {/* A stored place type the catalog no longer offers stays
                        selectable — losing it silently would rewrite the
                        marker on the next save. */}
                    {m.group && !groupOptions.includes(m.group) ? (
                      <option value={m.group}>{m.group}</option>
                    ) : null}
                  </select>
                  <button
                    type="button"
                    className={`ga-btn ga-btn-sm${placing === i ? ' ga-btn-primary' : ''}`}
                    onClick={() => setPlacing((cur) => (cur === i ? null : i))}
                    title={t('Then click the spot on the model in the viewer to move this marker there (Esc cancels).')}
                  >
                    ✥
                  </button>
                  <button
                    type="button"
                    className="ga-btn ga-btn-sm ga-btn-danger"
                    onClick={() => removeMarker(i)}
                    title={t('Remove this marker')}
                  >
                    ×
                  </button>
                </div>
                {AT_AXES.map((axis, ax) => {
                  // Metres = fraction × the dim of the VARIANT this marker
                  // belongs to, so the seat height is directly dialable in
                  // real units.
                  const dimM = shownDims[axis.dim]
                  return (
                    <SliderInput
                      key={axis.label}
                      className="ga-marker-axis"
                      style={{ display: 'flex', fontSize: '0.8em' }}
                      label={(
                        <span className="ga-hint" style={{ width: 66, flex: '0 0 auto' }}>
                          {t(axis.label)}
                        </span>
                      )}
                      ariaLabel={t(axis.label)}
                      min={axis.min}
                      max={AT_MAX}
                      step={0.005}
                      fineStep={0.001}
                      value={m.at[ax]}
                      onChange={(v) => setMarkerAt(i, ax as 0 | 1 | 2, v)}
                      sliderWidth="auto"
                      sliderStyle={{ flex: 1, minWidth: 60 }}
                      inputWidth={72}
                      readback={(
                        <span className="ga-hint" style={{ width: 58, flex: '0 0 auto', textAlign: 'right' }}
                          title={t('Fraction × this variant’s dimension.')}>
                          {(m.at[ax] * dimM).toFixed(2)} m
                        </span>
                      )}
                    />
                  )
                })}
                <SliderInput
                  className="ga-marker-axis"
                  style={{ display: 'flex', fontSize: '0.8em' }}
                  title={t('Facing in degrees: 0 south, 90 east, 180 north, 270 west. Unset = the client default (face the neighbours).')}
                  label={<span className="ga-hint" style={{ width: 66, flex: '0 0 auto' }}>🧭 {t('Facing')}</span>}
                  ariaLabel={t('Facing')}
                  min={0}
                  max={360}
                  step={5}
                  fineStep={1}
                  value={m.facing}
                  fallback={0}
                  clearable
                  placeholder="—"
                  onChange={(v) => patchMarker(i, { facing: ((v % 360) + 360) % 360 })}
                  onClear={() => patchMarker(i, { facing: undefined })}
                  sliderWidth="auto"
                  sliderStyle={{ flex: 1, minWidth: 60 }}
                  inputWidth={72}
                >
                  <button
                    type="button"
                    className="ga-btn ga-btn-sm"
                    style={{ width: 58, flex: '0 0 auto' }}
                    disabled={m.facing === undefined}
                    onClick={() => patchMarker(i, { facing: undefined })}
                    title={t('Unset the facing — the client decides.')}
                  >
                    ✕
                  </button>
                </SliderInput>
                {/* A place with room for several: the SERVER composes
                    `capacity` slots `spacing_m` apart across the facing
                    (payload `markers[].slots`) — the viewer opposite seats one
                    figure per slot. */}
                <SliderInput
                  className="ga-marker-axis"
                  style={{ display: 'flex', fontSize: '0.8em' }}
                  title={t('How many figures this place takes — a bench seats several. The slots line up across the facing.')}
                  label={<span className="ga-hint" style={{ width: 66, flex: '0 0 auto' }}>{t('Capacity')}</span>}
                  ariaLabel={t('Capacity')}
                  min={1}
                  max={8}
                  step={1}
                  value={capacity}
                  onChange={(v) => {
                    const cap = Math.max(1, Math.min(8, Math.round(v)))
                    // Capacity 1 is a single spot and carries neither key —
                    // the same shape the server stores.
                    patchMarker(i, cap > 1
                      ? { capacity: cap }
                      : { capacity: undefined, spacing_m: undefined })
                  }}
                  sliderWidth="auto"
                  sliderStyle={{ flex: 1, minWidth: 60 }}
                  inputWidth={72}
                />
                {capacity > 1 ? (
                  <SliderInput
                    className="ga-marker-axis"
                    style={{ display: 'flex', fontSize: '0.8em' }}
                    title={t('Distance between neighbouring slots in metres (0.6 = a bench seat).')}
                    label={<span className="ga-hint" style={{ width: 66, flex: '0 0 auto' }}>{t('Spacing')}</span>}
                    ariaLabel={t('Spacing')}
                    min={0.2}
                    max={3}
                    step={0.05}
                    fineStep={0.01}
                    value={m.spacing_m ?? 0.6}
                    onChange={(v) => patchMarker(i, { spacing_m: Math.round(v * 100) / 100 })}
                    unit="m"
                    sliderWidth="auto"
                    sliderStyle={{ flex: 1, minWidth: 60 }}
                    inputWidth={72}
                  />
                ) : null}
                {poses.length ? (
                  <div className="ga-form-row" style={{ fontSize: '0.8em' }}
                    title={t('Which pose of this place type the preview figures hold — view only, nothing is stored. Every slot shows it; a pair pose seats both halves around the marker.')}>
                    <span className="ga-hint" style={{ width: 66, flex: '0 0 auto' }}>
                      {t('Pose')}
                    </span>
                    <button type="button" className="ga-btn ga-btn-sm"
                      onClick={() => setPreview(poses[(poseIdx + poses.length - 1) % poses.length])}>
                      ◀
                    </button>
                    <span className="ga-hint" style={{ flex: 1, minWidth: 0 }}>
                      {poses[poseIdx]} ({poseIdx + 1}/{poses.length})
                    </span>
                    <button type="button" className="ga-btn ga-btn-sm"
                      onClick={() => setPreview(poses[(poseIdx + 1) % poses.length])}>
                      ▶
                    </button>
                  </div>
                ) : null}
              </div>
              )
            })
          )}
          <div style={{ display: 'flex', gap: 6 }}>
            <button
              type="button"
              className={`ga-btn ga-btn-sm${placing === 'add' ? ' ga-btn-primary' : ''}`}
              // Placing means clicking the mesh in the viewer — so it needs a
              // mesh SHOWN there, not just one somewhere on the prop. And a
              // marker needs a place type to name: without the catalog the
              // server would drop it on save.
              disabled={!(shownHasMesh || previewFile) || !firstGroup}
              onClick={() => setPlacing((cur) => (cur === 'add' ? null : 'add'))}
              title={t('Then click the spot on the model in the viewer to drop a marker there (Esc cancels) — like placing markers on the floor plan.')}
            >
              🎯 {placing === 'add' ? t('Click the model…') : t('Place marker')}
            </button>
            <button type="button" className="ga-btn ga-btn-sm" onClick={addMarker}
              disabled={!firstGroup}
              title={firstGroup
                ? t('Add a place at the box centre — pick its type, then position it with ✥ or the X/Y/Z sliders.')
                : t('No place types yet — the Poses tab defines them.')}>
              + {t('Marker')}
            </button>
          </div>
        </div>

        {/* Preview: the viewer plus the orientation fix that steers it —
            sticky, so it stays in view while a long marker list scrolls. */}
        <div className="ga-form ga-detail-cols-sticky">
          {variantBusy ? (
            <span className="ga-hint">
              {`${t('Generating the model — this takes a few minutes.')} · ${t('Variant')} ${variant + 1}`}
            </span>
          ) : pending ? (
            // Another variant of the same prop is busy — worth saying, but it
            // blocks nothing here.
            <span className="ga-hint">
              {t('Another variant of this prop is generating.')}
            </span>
          ) : null}
          {/* Split preview: the SELECTED VARIANT's source image on the left,
              its model on the right — and that image can be re-meshed
              directly (dialog picks backend / face count / texture size;
              the image render is skipped). Both panes follow the strip: the
              image belongs to the variant, so a second version of the object
              never shows (or overwrites) the first one's picture. */}
          <div style={{ display: 'flex', gap: 8, alignItems: 'stretch', flexWrap: 'wrap' }}>
          <div style={{ flex: '0 1 220px', minWidth: 160, display: 'flex',
            flexDirection: 'column', gap: 4 }}>
            <div className="ga-form-section-label" style={{ margin: 0 }}>
              {t('Source image')} · {t('Variant')} {variant + 1}
            </div>
            {shownImage && srcOk ? (
              <img
                src={`/assets/props/${enc}/source?variant=${variant}&v=${reloadKey}`}
                alt={t('Source image')}
                onError={() => setSrcOk(false)}
                style={{ width: '100%', flex: 1, maxHeight: 340,
                  objectFit: 'contain', borderRadius: 8,
                  border: '1px solid var(--border, #30363d)',
                  background: 'rgba(255,255,255,0.04)' }}
              />
            ) : (
              <div className="ga-empty" style={{ flex: 1 }}>
                {variants.length > 1
                  ? t('This variant has no source image yet — render one or upload a picture.')
                  : t('No source image (uploaded model).')}
              </div>
            )}
            {/* Provenance of the image SHOWN: what this variant's picture was
                generated with. Full prompt/negative in the tooltip — the
                caption stays one line. Uploaded/legacy images have no record
                and say so. */}
            {shownImage && srcOk ? (
              <span className="ga-hint" style={{ fontSize: 10, lineHeight: '13px' }}
                title={shownImage.prompt
                  ? `${t('Prompt')}: ${shownImage.prompt}${shownImage.negative
                    ? `\n${t('Negative prompt')}: ${shownImage.negative}` : ''}`
                  : t('No generation record for this image.')}>
                {shownImage.backend
                  ? `🖼 ${shownImage.backend}${shownImage.generated_at
                    ? ` · ${shownImage.generated_at.slice(0, 10)}` : ''}`
                  : t('No generation record for this image.')}
              </span>
            ) : null}
            <div style={{ display: 'flex', gap: 4 }}>
              <button type="button" className="ga-btn ga-btn-sm"
                style={{ flex: 1 }}
                disabled={variantBusy}
                // The SUBJECT travels with it: the dialog composes the final
                // prompt itself, so it has to compose from the text this
                // VARIANT renders from — its own, and the prop's NAME when it
                // has none (the server resolves it the same way for an empty
                // prompt, `props.variant_description`).
                onClick={() => onRegenerateImage(variant, shownImage || undefined,
                  shownVariant?.description || prop.name)}
                title={variantBusy
                  ? t('This variant is generating right now.')
                  : t('Render a NEW source image FOR THIS VARIANT (backend and prompt in the dialog). Its 3D model stays until you re-mesh from the new image; the other variants keep their own images.')}>
                🖼 {variantBusy ? t('Generating…') : t('New image')}
              </button>
              <button type="button" className="ga-btn ga-btn-sm"
                onClick={() => sourceUploadRef.current?.click()}
                title={t('Upload a picture as this variant’s source image — the ⚙ re-mesh below then works from it.')}>
                ⬆
              </button>
              <input ref={sourceUploadRef} type="file" accept="image/*"
                style={{ display: 'none' }}
                onChange={(e) => {
                  const f = e.target.files?.[0]
                  if (f) void uploadSource(f)
                  e.target.value = ''
                }} />
              <button type="button" className="ga-btn ga-btn-sm"
                onClick={onRefresh}
                title={t('Reload — fetch the current image and metadata (the render runs in the background).')}>
                🔄
              </button>
            </div>
            {/* The re-mesh targets the SELECTED variant — that is the whole
                difference to 🧊 above, which appends another one. It reads
                the image shown here, which is that variant's own. */}
            <button type="button" className="ga-btn ga-btn-sm"
              disabled={variantBusy || !shownImage || !srcOk}
              onClick={() => onRegenerateMesh(variant)}
              title={variantBusy
                ? t('This variant is generating right now.')
                : t('Mesh THIS image again into the SELECTED variant — no new render, no new variant; backend, face count and texture size come from the dialog. Dims and markers stay.')}>
              ⚙ {t('3D from this image')} · {t('Variant')} {variant + 1}
            </button>
          </div>
          <div style={{ flex: '1 1 260px', minWidth: 240 }}>
          {shownHasMesh || previewFile ? (
            <Model3DViewer
              url={previewFile
                // A file picked in the gallery below — including ones no tier
                // serves (only the admin route hands those out).
                ? `/world/props/${enc}/variants/${variant}/models/files/${encodeURIComponent(previewFile)}?v=${reloadKey}`
                // The serving URL of the SELECTED variant; `variant` is
                // explicit even for the primary one, so the preview cannot
                // quietly fall back to another mesh.
                : `/assets/props/${enc}/model?variant=${variant}&v=${encodeURIComponent(prop.created_at || '')}-${reloadKey}`}
              format="glb"
              height={340}
              rotation={prop.rotation}
              onBounds={(b) => setShownBbox(b.size)}
              // ONE FIGURE PER SLOT, holding the pose the cycler stands on
              // (else the place type's default). `root_drop` comes from the
              // pose catalog because this prop is UNCOMPOSED — the payload's
              // `root_offset` only exists for a placed one.
              markers={markers.map((m) => {
                const entry = previewEntry(poseCatalog, m.group,
                                           m.id ? previewPose[m.id] : undefined)
                return {
                  at: m.at, group: m.group, capacity: m.capacity,
                  spacing_m: m.spacing_m, facing: m.facing,
                  previewKind: entry?.animation,
                  previewYawOffset: entry?.yaw_offset,
                  rootDrop: groups[m.group]?.root_drop,
                }
              })}
              // The DISPLAYED variant's own size — the three numbers the strip
              // edits for exactly this chip.
              dimsOverlay={shownDims}
              // HOW DEEP IT STANDS, on the same draft the gauge above reads:
              // the viewer's ground plane goes where the scene's floor would
              // be (`bottom_y = floor + ground_offset_m`), so the buried part
              // disappears under it while the mesh, its W/D/H box and its
              // markers stay exactly where they are. Typing in the chip's
              // sink field moves the ground immediately — `variants` is the
              // draft, not the server's answer.
              groundOffsetM={shownVariant?.ground_offset_m ?? 0}
              // 1.7 m in MESH units — real scale = the displayed mesh's own
              // largest raw edge over its largest real dim; every figure in
              // the viewer (the marker poses and the standing reference)
              // sizes itself to that.
              figureHeight={(() => {
                const bb = shownBbox ?? (shownVariant?.primary ? prop.bbox : null)
                if (!bb) return 0
                const maxExtent = Math.max(bb[0], bb[1], bb[2])
                const maxDim = Math.max(shownDims.width_m, shownDims.depth_m,
                  shownDims.height_m) || 1
                return FIGURE_HEIGHT_M * (maxExtent / maxDim)
              })()}
              scaleFigure={scaleFigure}
              picking={placing !== null}
              onPickPoint={onPickPoint}
            />
          ) : (
            <div className="ga-empty">
              {variants.length > 1
                ? t('This variant has no model yet — mesh the source image into it or upload a GLB below.')
                : t('No model yet — generate it or upload a GLB below.')}
            </div>
          )}
          {/* The scale of the preview. A mesh fills its frame whatever it
              measures, so "is this 40 cm or 4 m" is unanswerable without a
              human beside it — the figure IS the answer, and it never scales
              with the model. */}
          {shownHasMesh || previewFile ? (
            <label
              className="ga-hint"
              style={{ display: 'inline-flex', alignItems: 'center', gap: 4,
                marginTop: 4, cursor: 'pointer' }}
              title={t('Puts a FIXED 1.70 m person beside the model, on the ground the model stands IN, over a one-metre grid — the preview’s scale. The ground is solid, so whatever the sink buries really disappears under it. The figure never scales with the prop: if it looks wrong, the W/D/H of this variant are wrong.')}
            >
              <input
                type="checkbox"
                checked={scaleFigure}
                onChange={(e) => {
                  setScaleFigure(e.target.checked)
                  saveScaleFigure(e.target.checked)
                }}
              />
              {t('Reference figure (1.70 m)')}
            </label>
          ) : null}
          {/* WHICH numbers the preview is measuring — the chip's, always. Said
              once here, so the viewer and the strip opposite never read as
              contradicting each other. */}
          <span className="ga-hint" style={{ display: 'block' }}>
            {t('Measured against variant {n}: {w} × {d} × {h} m.')
              .replace('{n}', String(variant + 1))
              .replace('{w}', shownDims.width_m.toFixed(2))
              .replace('{d}', shownDims.depth_m.toFixed(2))
              .replace('{h}', shownDims.height_m.toFixed(2))}
          </span>
          </div>
          </div>

          {/* Orientation fix — ↻ adds +90°, the field sets a free exact angle. */}
          {prop.has_model ? (
            <>
              <div className="ga-form-section-label">{t('Orientation fix')}</div>
              <div className="ga-form-row">
                {(['x', 'y', 'z'] as const).map((axis) => (
                  <span key={axis} style={{ display: 'inline-flex', gap: 2, alignItems: 'center' }}>
                    <button type="button" className="ga-btn ga-btn-sm"
                      onClick={() => { void rotate(axis) }} title={t('+90°')}>
                      ↻ {axis.toUpperCase()}
                    </button>
                    <input
                      key={`${axis}-${prop.rotation?.[axis] || 0}`}
                      className="ga-input" type="number" min={-360} max={720} step={0.1}
                      style={{ width: 64 }}
                      defaultValue={prop.rotation?.[axis] || 0}
                      title={t('Exact angle in degrees — free rotation for meshes that came out tilted.')}
                      onBlur={(e) => { void setRotationAxis(axis, e.target.value) }}
                      onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
                    />
                  </span>
                ))}
              </div>
              <span className="ga-hint">{t('Orientation fix — persisted; the 3D client applies it on load.')}</span>
            </>
          ) : null}

          {/* The lattice a figure's feet are put on, baked from THIS variant's
              mesh — a state to read, not a value to dial. It follows the
              orientation fix, which is why it can go stale.
              Gated on the SHOWN variant's mesh, not on the prop's: the status
              line, the button and the route all speak about the variant the
              viewer has open, so a variant with a mesh must offer the bake
              even when the primary one has none (T8). */}
          {shownHasMesh ? (
            <>
              <div className="ga-form-section-label">{t('Walkable surface')}</div>
              <div className="ga-form-row" style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <span className="ga-muted">{surfaceLabel}</span>
                <button type="button" className="ga-btn ga-btn-sm"
                  onClick={() => { void bakeSurface() }}
                  title={t('Bake the surface figures walk on — runs Blender in the background')}>
                  {t('Bake surface')}
                </button>
              </div>
            </>
          ) : null}

          {/* THE KEY SURFACES of this prop's mesh and the pictures hung on
              them (spec-picture-props.md § 4). It needs a mesh to read them
              off, so it appears with the model — and it works on the PRIMARY
              variant's mesh, which is the frame every picture variant copies.
              */}
          {prop.has_model ? (
            <PropAreasPanel
              prop={prop}
              variants={serverVariants}
              variantMax={variantMax}
              reloadKey={reloadKey}
              onPropChanged={onRefresh}
              onVariantsChanged={() => { void loadVariants() }}
            />
          ) : null}

          {/* The SELECTED variant's mesh gallery: every stored run, one active
              file per resolution tier, upload and delete. */}
          <PropModelPanel
            propId={prop.id}
            variant={variant}
            reloadKey={reloadKey}
            preview={previewFile}
            onPreview={setPreviewFile}
            onChanged={meshesChanged}
            pending={variantBusy}
            onGenerating={onGenerating}
          />
        </div>
      </div>
    </>
  )
}
