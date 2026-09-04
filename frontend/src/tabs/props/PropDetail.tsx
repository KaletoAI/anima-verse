/**
 * PropDetail — detail panel of one prop.
 *
 * TWO COLUMNS, and since 2026-08-25 the split says what a prop IS:
 *
 *   left   the PROP's general fields (name, category, tags, sway), the MODEL
 *          VARIANTS as a strip of selector chips, and the object-local places
 *          of the selected variant — dialled against the viewer opposite.
 *   right  EVERYTHING THE SELECTED VARIANT IS, named once at the top and never
 *          again ("Variant n", 2026-08-29): its source image, its mesh in the
 *          3D viewer with the 1.70 m reference figure, its resolution tiers
 *          with the two triangle budgets, its own settings (size, sink,
 *          generation subject), the persisted orientation fix, the walkable
 *          surface and its key areas.
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
 * ONE 3D VIEW (2026-08-28, spec-bild-props-v2 ruling V11). There is exactly
 * one preview on this page, and the AREAS tools are a mode of it: the front
 * view, the surface outlines, the polygon ring, the assembly preview of a
 * picture variant and the door leaf's test swing all ride the model in that
 * viewer. The Areas panel below is the list and the verbs; the view state and
 * the areas-call lock live here, because the viewer does.
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
import { useEnlarge } from '../../components/ZoomButton'
import { useI18n } from '../../i18n/I18nProvider'
import { ApiError, apiDelete, apiGet, apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { setUnsavedGuard } from '../../lib/unsavedGuard'
import {
  applyVariantDraft, draftValue, dropDeletedVariant, emptyFields,
  GENERAL_TARGET, pendingFieldCount, queueFields, toBulkFieldBody,
  variantTarget, type PendingFields,
} from './pendingFields'
import { Model3DViewer } from '../characters/Model3DViewer'
import { PropAreasPanel } from './PropAreasPanel'
import { PropModelPanel } from './PropModelPanel'
import { PropVariantStrip } from './PropVariantStrip'
import {
  groupKeys, groupLabel, newId, posesInGroup, previewEntry, usePoseCatalog,
} from '../world/placeTypes'
import { CATEGORY_DATALIST_ID, PROP_EXTRA_VIEWS } from './propTypes'
import {
  DESC_ROWS_OPEN, DESC_ROWS_REST, DIM_FIELDS, SINK_LIMIT_M, descPatch,
  dimRatios, dimsPatch, facePatch, sinkPatch,
} from './variantFields'
import type { DimKey } from './dims'
import type {
  PropAreasInfo, PropFull, PropMarker, PropSourceImage, PropVariant, PropView,
} from './propTypes'

/**
 * The scale kit of the 3D preview — the 1.70 m reference figure beside the
 * prop plus the metre grid under both (rule "Kein Maß ohne Maßstab").
 * Remembered per browser, ON until it is switched off: a mesh alone says
 * nothing about its size, so the first look should already carry the scale.
 */
const SCALE_FIGURE_KEY = 'ga.props.scaleFigure'

/** Human name of each view — the tile captions of the source panel. Same
 *  wording as `MeshBackendDialog` and `PropImageDialog`. */
const VIEW_LABEL: Record<PropView, string> = {
  front: 'Front view', back: 'Back view', left: 'Left view', right: 'Right view',
}

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
// props.MARKER_AT_MIN/MAX: half a box of slack below and a full box above,
// because seats and lying surfaces sit ON the hull or outside it.
const AT_MIN = -0.5
const AT_MAX = 2
// The height axis reaches a FULL box below (props.MARKER_AT_Y_MIN) — deep
// seat positions in tall machines sit far under the box top.
const AT_AXES: Array<{ label: string; dim: DimKey; min: number }> = [
  { label: 'X (width)', dim: 'width_m', min: AT_MIN },
  { label: 'Y (height)', dim: 'height_m', min: -1 },
  { label: 'Z (depth)', dim: 'depth_m', min: AT_MIN },
]

export function PropDetail({ prop, pending, generatingVariants, cacheBump,
  onChanged, onDelete, armedDelete, onRegenerate, onRegenerateMesh,
  onRegenerateImage, onRefresh, onGenerating, backendFaces = 0,
  onDirtyChange }: {
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
   *  because the dialog that runs it lives in the container. `existingViews`
   *  are the extra views this variant holds a file for, so the dialog can
   *  offer exactly those to the multi-view alias: `PropFull` has no variant
   *  list, the detail owns it. */
  onRegenerateMesh: (variant: number, existingViews: PropView[]) => void
  /** Re-run the source→mesh chain with the stored description/name — this
   *  APPENDS another model variant. */
  onRegenerate: () => void
  /** Render a NEW source image for the SELECTED variant only — its mesh stays
   *  until re-meshed, and no other variant's image is touched. `view` says
   *  WHICH of the four pictures is being rendered, `image` is that view's own
   *  record (so the dialog opens on the backend THIS picture was made with)
   *  and `hasFront` whether a front exists to slot as the reference. */
  onRegenerateImage: (variant: number, view: PropView, image?: PropSourceImage,
    subject?: string, hasFront?: boolean) => void
  /** Reload the prop + bust the image cache — generations run in the
   *  background, this fetches the current state on demand. */
  onRefresh: () => void
  /** Start the container's pending poll — a background job was just kicked
   *  off from inside the detail (the mesh gallery's low variant). */
  onGenerating: () => void
  /** Face count a mesh backend would use of its own accord — the PLACEHOLDER
   *  behind the variants' face budgets (v2 E5). 0 = unknown. */
  backendFaces?: number
  /** How many FIELD edits are waiting in the draft (0 = clean). The container
   *  asks before it lets the selection leave this prop — a tab switch is the
   *  shell's question, a prop switch has to be this tab's own. */
  onDirtyChange: (count: number) => void
}) {
  const { t } = useI18n()
  const enlarge = useEnlarge()
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

  // ── WHAT THE OPEN VARIANT'S FILE CARRIES (v2 E1) ───────────────────────
  // The areas, the door-leaf box and the orientation fix belong to the model
  // FILE, so they are read PER VARIANT — and from the one place that answers
  // for ANY store index: `GET …/areas?variant=` resolves a switched-off or
  // out-of-season variant just as well (`props.areas_info` →
  // `_resolve_variant`, 404 only for an index the prop does not have), while
  // the record's `variant_tiers` publishes the effective variants alone.
  //
  // ONE request feeds everything that needs them: the fix of the 3D preview,
  // the turn the strip applies to the measured box, and the areas panel below
  // — which is why the fetch lives here and not inside that panel.
  const [areasInfo, setAreasInfo] = useState<PropAreasInfo | null>(null)
  const [areasFailed, setAreasFailed] = useState(false)
  /** Bumped by the areas panel when one of its verbs changed the file. */
  const [areasBump, setAreasBump] = useState(0)
  const reloadAreas = useCallback(() => setAreasBump((n) => n + 1), [])
  useEffect(() => {
    if (!shownHasMesh) { setAreasInfo(null); setAreasFailed(false); return }
    let cancelled = false
    void (async () => {
      try {
        const d = await apiGet<PropAreasInfo>(
          `/world/props/${enc}/areas?variant=${variant}`)
        if (!cancelled) { setAreasInfo(d); setAreasFailed(false) }
      } catch {
        if (!cancelled) { setAreasInfo(null); setAreasFailed(true) }
      }
    })()
    // A chip switched while the request was in flight would otherwise land
    // variant A's areas on variant B's mesh — outlines and R1 face indices of
    // the wrong file, and a drawn ring would split the wrong triangles.
    return () => { cancelled = true }
  }, [enc, variant, shownHasMesh, reloadKey, areasBump])
  /** The payload ONLY while it speaks about the variant that is open. The
   *  answer names the store index it was read for, so a late one is simply
   *  not used instead of being applied to the wrong mesh. */
  const variantAreas = areasInfo && areasInfo.variant === variant
    ? areasInfo : null
  /** The orientation fix of THIS variant's active full file. */
  const variantRotation = variantAreas?.rotation
  /** A verb of the panel answered with a fresh payload. It names the store
   *  index it was read for, so one that finished after the admin moved on is
   *  dropped rather than applied to the mesh now on screen. */
  const onAreasInfo = useCallback((next: PropAreasInfo) => {
    if (next.variant !== variant) return
    setAreasInfo(next)
    setAreasFailed(false)
  }, [variant])

  // ── ONE 3D VIEW PER PROP (v2 ruling V11) ───────────────────────────────
  // The Areas tools are a MODE of the one preview, not a viewer of their
  // own: outlines, front view, polygon ring, assembly preview and test swing
  // ride the model the admin is already looking at — which is also the only
  // mesh whose R1 face order matches the `mesh_layout` a ring is flattened
  // against. So the VIEW state lives here, with the viewer, and the panel
  // below only switches it.
  /** Front view on (§ B1)? Off by default: this is the general preview, where
   *  markers and dims are dialled at an angle. Arming the ring turns it on,
   *  because a flat surface is only ringable head-on. */
  const [areaFrontal, setAreaFrontal] = useState(false)
  /** The kind the polygon tool is drawing for ('' = not drawing). */
  const [drawKind, setDrawKind] = useState('')
  /** Which picture variant the preview is assembled with (null = bare mesh). */
  const [areaPreview, setAreaPreview] = useState<number | null>(null)
  /** Which areas call is running ('' = none) — the lock the panel's verbs and
   *  the polygon tool share, because they all write the same mesh. */
  const [areaBusy, setAreaBusy] = useState('')
  /** THE OTHER ARM MODE OF THE SAME CANVAS: floor-plan-style marker placement
   *  ('add' or a marker index, null = disarmed). It is declared up here with
   *  the ring because the two cannot both be armed — the drawing SVG lies
   *  over the canvas and swallows every click the pick is waiting for, and a
   *  ring that closes would hand the canvas back to a pick armed minutes
   *  ago, which then drops a marker on the next click. */
  const [placing, setPlacing] = useState<'add' | number | null>(null)
  // A prop or variant switch puts another mesh under the camera: the view
  // state means nothing there, and the previous variant index means something
  // else on the next prop.
  useEffect(() => {
    setAreaFrontal(false); setDrawKind(''); setAreaPreview(null)
  }, [prop.id, variant])
  /** THE COUPLING RULES, in one place because they are invariants of the one
   *  view: arming the ring turns the front view on and drops a stored gallery
   *  file (another file is another face order); leaving the front view
   *  disarms the ring — the points already clicked were placed against the old
   *  camera; and previewing an assembly also needs the served mesh, the one
   *  the areas were split against. */
  const setAreaView = useCallback((patch: { frontal?: boolean
    drawKind?: string; preview?: number | null }) => {
    if (patch.frontal !== undefined) {
      setAreaFrontal(patch.frontal)
      if (!patch.frontal) setDrawKind('')
    }
    if (patch.drawKind !== undefined) {
      setDrawKind(patch.drawKind)
      // ONE CANVAS, ONE GESTURE: arming the ring disarms the marker pick.
      if (patch.drawKind) {
        setAreaFrontal(true); setPreviewFile(''); setPlacing(null)
      }
    }
    if (patch.preview !== undefined) {
      setAreaPreview(patch.preview)
      if (patch.preview !== null) setPreviewFile('')
    }
  }, [])
  /** A file picked in the mesh gallery below. It is a DIFFERENT file — its
   *  triangles are not the ones the areas were split against — so the tools
   *  stand down while it is on screen. */
  const showStoredFile = useCallback((file: string) => {
    setPreviewFile(file)
    if (file) { setDrawKind(''); setAreaPreview(null) }
  }, [])
  /** Arm or disarm the marker pick — the other half of the exclusion: it
   *  drops a running ring, and while a ring IS running every pick button is
   *  disabled, so the two modes are never both offered. */
  const armPlacing = useCallback((which: 'add' | number) => {
    setPlacing((cur) => (cur === which ? null : which))
    setDrawKind('')
  }, [])
  /** Every areas call answers the same payload — one place that holds the
   *  lock, hands a fresh payload to the reader above (which drops it if the
   *  admin has moved on) and maps a failure onto a toast. */
  const runAreas = useCallback((what: string,
    call: () => Promise<unknown>): void => {
    setAreaBusy(what)
    void (async () => {
      try {
        const answer = await call() as PropAreasInfo | undefined
        if (answer && Array.isArray(answer.areas)) onAreasInfo(answer)
        else reloadAreas()
        onRefresh()
      } catch (e) {
        toast(`${t('Error')}: ${(e as Error).message}`, 'error')
        reloadAreas()
      } finally {
        setAreaBusy('')
      }
    })()
  }, [onAreasInfo, reloadAreas, onRefresh, t, toast])
  /** The closed ring, as flat R1 triangle indices of the mesh on screen. The
   *  door leaf is a BODY (E2): its ring is a prism and the server cuts the
   *  same prism through what it gets. A surface kind is picked by sight. */
  const onPolygonFaces = useCallback((faces: number[]) => {
    const kind = drawKind
    setDrawKind('')
    if (!faces.length) {
      toast(t('Nothing was inside the outline — draw around the surface, facing it.'), 'error')
      return
    }
    runAreas('draw', () => apiPost(`/world/props/${enc}/areas?variant=${variant}`,
      { mode: 'manual', faces, kind, through: kind === 'leaf' }))
  }, [drawKind, enc, variant, runAreas, t, toast])
  /** MAY THE TOOLS SPEAK ABOUT WHAT IS ON SCREEN? Only while the viewer shows
   *  the SERVED mesh of the open variant: a file picked in the gallery is
   *  another file, and its triangles are not the ones the outlines, the leaf
   *  box and the R1 indices belong to. */
  const areasOnView = !previewFile && !!variantAreas
  // …and when it stops being so mid-gesture (a refetch that failed), the tool
  // disarms: the ring would have nothing to be flattened against, and leaving
  // "Click the outline…" standing over a viewer that has already dropped the
  // overlay promises a gesture nobody can finish.
  useEffect(() => {
    if (drawKind && !areasOnView) setDrawKind('')
  }, [drawKind, areasOnView])
  /** The key surfaces of the open variant, as the viewer draws them — the
   *  edges come from the server, the client never measures (§ B5a). */
  const areaOutlines = useMemo(() => (variantAreas?.areas || []).map((a) => ({
    id: a.id, kind: a.kind, edges: a.edges || [] })), [variantAreas])
  /** WHAT AN ASSEMBLY PREVIEW SHOWS: the PICKED variant's own pane defaults
   *  with its own values on top — exactly the merge the scene recipe makes for
   *  the variant it resolves (`scene_recipe._slot_spec`), keyed by AREA ID,
   *  which is the slot name `applySlotMaterials` matches after taking the
   *  material's `slot_` prefix off (R11). Both halves belong to the SAME entry
   *  since v2 E1 — the open variant's defaults would preview a mesh nobody
   *  renders.
   *
   *  MEMOISED, deliberately: the viewer re-applies its slot materials whenever
   *  this object's identity changes, and a fresh map per render would reload
   *  every texture on every keystroke on this page. */
  const previewSlots = useMemo(() => {
    const picked = areaPreview === null
      ? null : serverVariants.find((v) => v.index === areaPreview) || null
    return picked
      ? { ...(picked.area_defaults || {}), ...(picked.slot_values || {}) }
      : undefined
  }, [areaPreview, serverVariants])
  const areaTools = useMemo(() => ({
    drawKind, preview: areaPreview, setView: setAreaView,
    busy: areaBusy, setBusy: setAreaBusy, run: runAreas,
  }), [drawKind, areaPreview, setAreaView, areaBusy, runAreas])
  /** The preview, so arming the ring can bring it into view: the tools sit
   *  below a long panel, and a front view nobody can see is not one. */
  const viewerRef = useRef<HTMLDivElement | null>(null)
  useEffect(() => {
    if (drawKind) viewerRef.current?.scrollIntoView({ block: 'nearest' })
  }, [drawKind])
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
  const uploadSource = useCallback(async (file: File, view: PropView = 'front') => {
    try {
      const fd = new FormData()
      fd.append('file', file)
      const res = await fetch(
        `/world/props/${enc}/variants/${variant}/source${view === 'front' ? '' : `?view=${view}`}`,
        { method: 'POST', body: fd, credentials: 'same-origin' })
      const body = await res.json().catch(() => null)
      if (!res.ok) throw new Error(body?.detail?.toString?.() || `HTTP ${res.status}`)
      await meshesChanged()
      toast(t('Saved'))
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [enc, variant, meshesChanged, t, toast])

  // Drop ONE extra view's picture. The front is not deletable here — it is
  // the variant's source image, and a variant without one cannot be meshed
  // at all; an extra view is an addition and goes back to "none".
  const deleteView = useCallback(async (view: PropView) => {
    try {
      await apiDelete(`/world/props/${enc}/variants/${variant}/source?view=${view}`)
      await meshesChanged()
      toast(t('Deleted'))
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [enc, variant, meshesChanged, t, toast])
  // Which tile's × is armed (the two-click delete of this admin, never a
  // window.confirm), and which view the shared file input is filling.
  const [armedView, setArmedView] = useState<PropView | null>(null)
  const viewUploadRef = useRef<HTMLInputElement>(null)
  const [uploadView, setUploadView] = useState<PropView>('back')
  // An armed × belongs to the tile it was clicked on — switching the variant
  // (or the prop) shows OTHER pictures, and a still-armed button would delete
  // one of those on a single click.
  useEffect(() => { setArmedView(null) }, [prop.id, variant])

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

  // ── THE SELECTED VARIANT'S OWN FIELDS (2026-08-29) ─────────────────────
  // Size, sink, description and the two triangle budgets belong to the
  // VARIANT (2026-08-25) but are edited HERE, beside the model they describe:
  // one set of inputs for the version on screen instead of a form per chip.
  // The law behind each of them lives in `variantFields.ts`; what this file
  // owns is the typing state and the hand-off into the change buffer.
  //
  // What is being TYPED into a size field, keyed by dim. An entry lives only
  // while the field is edited — the commit drops it and the input falls back
  // to the stored number, so a background reload can never stomp what is under
  // the cursor and no sync effect is needed.
  const [dimDraft, setDimDraft] = useState<Record<string, string>>({})
  const [descDraft, setDescDraft] = useState<string | null>(null)
  /** Is the description expanded to writing size? Readable at rest, a real
   *  editor while it is written in. */
  const [descOpen, setDescOpen] = useState(false)
  // Another variant is another set of numbers: a draft of the one before it
  // would show its size in the new one's fields.
  useEffect(() => {
    setDimDraft({})
    setDescDraft(null)
    setDescOpen(false)
  }, [prop.id, variant])

  // One edited edge, three answers — the whole row is rewritten, so no field
  // of it keeps a draft (a stale one would show a number the server never
  // got). The proportions come from the mesh ON SCREEN when it is loaded.
  const commitDim = useCallback((key: DimKey, raw: string) => {
    setDimDraft({})
    if (!shownVariant) return
    const next = dimsPatch(shownVariant.dims, key, raw,
      dimRatios(shownVariant.dims, shownBbox, variantRotation))
    if (next) queueVariant(variant, { dims: next })
  }, [shownVariant, shownBbox, variantRotation, queueVariant, variant])

  // How deep this variant stands in the ground. No debounce and no local echo:
  // the number goes straight into the draft, the draft IS what the field, the
  // gauge and the viewer's ground plane read, and Save writes it once however
  // often it was corrected. 0 clears the key, which is the normal state.
  const commitSink = useCallback((value: number) => {
    if (!shownVariant) return
    const next = sinkPatch(shownVariant.ground_offset_m, value)
    if (next !== null) queueVariant(variant, { ground_offset_m: next })
  }, [shownVariant, queueVariant, variant])

  const commitDesc = useCallback((raw: string) => {
    setDescDraft(null)
    if (!shownVariant) return
    const next = descPatch(shownVariant.description, raw)
    if (next !== null) queueVariant(variant, { description: next })
  }, [shownVariant, queueVariant, variant])

  // One of the two triangle budgets (v2 E5) — committed from the resolution
  // tiers section, which is what they decide. Both halves travel every time;
  // the reason is in `variantFields.facePatch`.
  const commitFaces = useCallback((which: 'high' | 'low', raw: string) => {
    if (!shownVariant) return
    const next = facePatch({ high: shownVariant.target_faces_high,
      low: shownVariant.target_faces_low }, which, raw)
    if (next) queueVariant(variant, { face_targets: next })
  }, [shownVariant, queueVariant, variant])

  // THE FIX IS THE FILE'S (v2 E1): the route takes the variant, and what comes
  // back has to reach the viewers below — the preview here, the areas viewer
  // and the strip's dims all turn with it, so this reloads the meshes rather
  // than the record alone.
  const rotate = useCallback(async (axis: 'x' | 'y' | 'z') => {
    const cur = variantRotation || {}
    try {
      await apiPost(`/world/props/${enc}/rotation?variant=${variant}`, {
        x: cur.x || 0, y: cur.y || 0, z: cur.z || 0,
        [axis]: ((cur[axis] || 0) + 90) % 360,
      })
      await meshesChanged()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [variantRotation, enc, variant, meshesChanged, t, toast])

  const setRotationAxis = useCallback(async (axis: 'x' | 'y' | 'z', raw: string) => {
    const n = parseFloat(raw)
    const v = Number.isFinite(n) ? ((n % 360) + 360) % 360 : 0
    if (v === (variantRotation?.[axis] || 0)) return
    const cur = variantRotation || {}
    try {
      await apiPost(`/world/props/${enc}/rotation?variant=${variant}`, {
        x: cur.x || 0, y: cur.y || 0, z: cur.z || 0, [axis]: v,
      })
      await meshesChanged()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [variantRotation, enc, variant, meshesChanged, t, toast])

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

  /** The Remove button's second click (no `window.confirm` in this UI). */
  const [removeArmed, setRemoveArmed] = useState(false)
  // Disarmed by every variant switch: the button speaks about the variant the
  // viewer has open, and an arming carried over would delete another mesh's
  // lattice on a click meant for this one.
  useEffect(() => { setRemoveArmed(false) }, [prop.id, variant])
  // Throwing the lattice away — the counterpart of the bake, and the only way
  // back to "this prop is not walkable" once one has been baked. It happens on
  // the spot (no Blender), so the status line has to be right afterwards:
  // `meshesChanged` reloads the VARIANT records, and it is the shown variant's
  // `surface_status` the line reads, not the prop record's.
  const removeSurface = useCallback(async () => {
    setRemoveArmed(false)
    try {
      const d = await apiDelete<{ deleted?: boolean }>(
        `/world/props/${enc}/surface?variant=${variant}`)
      toast(d?.deleted ? t('Surface removed.') : t('There was no surface to remove.'))
      await meshesChanged()
    } catch (e) {
      // 409 = a bake of this prop is running, and it would write the file
      // again anyway. It is the one refusal that is neither a defect nor a
      // reason to try something else, so it says WHEN to try again instead of
      // showing the server sentence.
      if ((e as ApiError)?.status === 409) {
        toast(t('A bake is running for this prop — try again when it has finished.'), 'error')
      } else {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
      }
    }
  }, [enc, variant, meshesChanged, t, toast])

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
  /** WHICH PLACE THE CARD BESIDE THE LIST IS ABOUT (2026-08-29). The list only
   *  selects; a place is edited in exactly ONE card, so the column no longer
   *  grows a form per marker and the sliders of the place in hand stay in
   *  view. View state — nothing of it is stored. */
  const [selectedMarker, setSelectedMarker] = useState(0)
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

  // The selection is CLAMPED on the way out: the list can shrink under it (a
  // discarded draft, a removed place) and what is edited must be a place that
  // exists — in the very same render. The reset effect below covers the
  // prop/variant switch, but it runs AFTER that render, so this clamp is what
  // carries the frame in between: a shorter list on the new variant would
  // otherwise be indexed past its end for one paint.
  const selIdx = markers.length
    ? Math.min(selectedMarker, markers.length - 1)
    : 0
  const selMarker: PropMarker | undefined = markers[selIdx]

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
  // A place is added TO BE EDITED — the card opposite the list follows it, so
  // the type select and the sliders are already about the new one. A pick
  // armed for the place left behind is dropped with it: the viewer would keep
  // the crosshair on and write the next mesh click into the OLD place, whose
  // card is no longer even on screen.
  const addMarker = () => {
    saveMarkers([...markers, { id: newId(), group: firstGroup, at: [0.5, 0, 0.5] }])
    setSelectedMarker(markers.length)
    setPlacing(null)
  }
  // Removing leaves the NEIGHBOUR selected: the place that slid into the gap,
  // or the new last one when the tail went. An armed pick would otherwise
  // point at an index that now means another place.
  const removeMarker = (i: number) => {
    const next = markers.filter((_, idx) => idx !== i)
    saveMarkers(next)
    setSelectedMarker(Math.max(0, Math.min(i, next.length - 1)))
    setPlacing(null)
  }

  // Capacity 1 is a single spot and carries no key — the shape the server
  // stores, so the absent key reads as the one figure it means.
  const selCapacity = selMarker?.capacity || 1
  // The poses of the SELECTED place's TYPE, its default first — the ◀ ▶ cycler
  // in the card picks which one the preview figures hold. View state only,
  // keyed by the marker's id; a place stored before ids existed gets one
  // minted into the draft on the first click.
  const selPoses = selMarker ? posesInGroup(poseCatalog, selMarker.group) : []
  const selPoseIdx = Math.max(0, selPoses.indexOf(
    (selMarker?.id && previewPose[selMarker.id]) || selPoses[0]))
  const setPreview = (pose: string) => {
    if (!selMarker) return
    const id = selMarker.id || newId()
    if (!selMarker.id) patchMarker(selIdx, { id })
    setPreviewPose((cur) => ({ ...cur, [id]: pose }))
  }

  // Floor-plan-style placement: armed further up (it shares the canvas with
  // the ring), then click the mesh in the viewer — the hit lands as raw-box
  // fractions. Esc disarms. And another prop or another variant is another
  // list of places: an index selected here means something else there.
  useEffect(() => { setPlacing(null); setSelectedMarker(0) }, [prop.id, variant])
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setPlacing(null) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])
  // The hit lands on the place the editor is about: 'add' appends one and
  // selects it, an armed index is the selected place (✥ arms exactly that
  // one). Reading `placing` instead of updating through it keeps the write
  // out of a state updater, which React may run more than once.
  const onPickPoint = useCallback((at: [number, number, number]) => {
    if (placing === 'add') {
      saveMarkers([...markers, { id: newId(), group: firstGroup, at }])
      setSelectedMarker(markers.length)
    } else if (placing !== null && markers[placing]) {
      saveMarkers(markers.map((m, idx) => (idx === placing ? { ...m, at } : m)))
    }
    setPlacing(null)
  }, [placing, markers, firstGroup, saveMarkers])

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
      <div className="ga-detail-cols ga-detail-cols-3 ga-detail-cols--panes">
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
            {/* One number between 0 and 1 — `compact` keeps it at the width
                of what it holds instead of taking an equal share of the row
                from the three text fields beside it. */}
            <Field label={t('Sway factor')} compact>
              <input className="ga-input" type="number" min={0} max={1} step={0.05}
                style={{ width: 76 }}
                value={swayDraft}
                title={t('How much of its ground’s wind this prop takes part in when it is scattered over a painted area: the terrain kind says how far things bend there, this multiplies it. 1 = the full amount, 0 = stands still whatever blows, empty = 1. Very small products stand still as well — the deflection only starts at about 0.005 m, so on a ground that bends 0.06 m every factor up to 0.08 comes to a standstill.')}
                onChange={(e) => setSwayDraft(e.target.value)}
                onBlur={commitSway}
                onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }} />
            </Field>
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

          {/* THE VARIANTS — several meshes of the same object. The chip is the
              SELECTOR (2026-08-29): it says which version this is, whether it
              renders and in which seasons, while everything that describes the
              version itself is edited opposite, beside the model it is about.
              The selected chip decides what the viewer opposite shows and what
              the gallery, the settings and the marker editor act on. */}
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
          />

          {/* THE SELECTED VARIANT'S PLACES, dialled against the viewer
              opposite: they are the variant's own (at = a fraction of ITS
              box), so they need the mesh beside them — which is why they
              stand here and not inside the chip.
              LIST LEFT, ONE CARD RIGHT (2026-08-29, user decision): the
              column used to grow a whole form per place, so five places meant
              five stacked slider sets and the one in hand scrolled away. The
              list names them, the card edits exactly one. The heading says
              which places these are — WHICH variant they belong to is said
              once at the top of the column opposite. The source string is
              `Prop places` and not `Places`, because that word is already the
              admin's name for LOCATIONS: one English string, one meaning, or
              the German heading reads "Orte" over a list of seats. */}
          <div className="ga-form-section-label">{t('Prop places')}</div>
          <span className="ga-hint">
            {t('Object-local PLACES a character is seated on — each names a place type (seat, bed, floor …) and takes as many figures as its capacity. They belong to THIS variant, because at = fraction of ITS model bounding box (X = width, Y = height, Z = depth); the range reaches from -0.5 to 2, because seats and lying surfaces sit on the hull or outside it. Place roughly with ✥, fine-tune with the sliders — the figures in the preview follow live.')}
          </span>
          <div className="ga-list-detail">
            <div className="ga-list-detail-side">
              {markers.length === 0 ? (
                /* `ga-empty` carries no style in this stylesheet — the muted
                   hint is what every other "nothing here yet" line uses. */
                <span className="ga-hint">{t('No places yet.')}</span>
              ) : (
                <ul className="ga-list">
                  {markers.map((m, i) => (
                    <li key={m.id || i}>
                      <button
                        type="button"
                        className={`ga-list-row${i === selIdx ? ' is-active' : ''}`}
                        onClick={() => {
                          setSelectedMarker(i)
                          // A pick armed for the place just left behind would
                          // move THAT one on the next click in the viewer.
                          // 'add' names no place yet and stays armed.
                          if (typeof placing === 'number') setPlacing(null)
                        }}
                      >
                        <span className="ga-list-row-main">
                          🎯 {i + 1}
                          {/* A long place-type label is cut, not wrapped —
                              the row is 160 px wide and the number in front
                              of it must stay readable. `minWidth: 0` is what
                              lets a flex child shrink at all. */}
                          <span className="ga-list-row-sub" style={{
                            minWidth: 0, overflow: 'hidden',
                            textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            · {groupLabel(groups, m.group)}
                          </span>
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                <button type="button" className="ga-btn ga-btn-sm" onClick={addMarker}
                  disabled={!firstGroup}
                  title={firstGroup
                    ? t('Add a place at the box centre — pick its type, then position it with ✥ or the X/Y/Z sliders.')
                    : t('No place types yet — the Poses tab defines them.')}>
                  + {t('Marker')}
                </button>
                <button
                  type="button"
                  className={`ga-btn ga-btn-sm${placing === 'add' ? ' ga-btn-primary' : ''}`}
                  // Placing means clicking the mesh in the viewer — so it needs
                  // a mesh SHOWN there, not just one somewhere on the prop. And
                  // a marker needs a place type to name: without the catalog
                  // the server would drop it on save.
                  // …and not while a ring is being drawn: the two arm modes
                  // share the one canvas (V11).
                  disabled={!(shownHasMesh || previewFile) || !firstGroup || !!drawKind}
                  onClick={() => armPlacing('add')}
                  title={drawKind
                    ? t('Finish or cancel the surface you are drawing first — the ring and the marker pick share the one preview.')
                    : t('Then click the spot on the model in the viewer to drop a marker there (Esc cancels) — like placing markers on the floor plan.')}
                >
                  🎯 {placing === 'add' ? t('Click the model…') : t('Place marker')}
                </button>
              </div>
            </div>
            {/* THE ONE PLACE IN HAND. Every input of it writes through the
                clamped index, so a list that shrank under the selection can
                never be edited past its end. */}
            {selMarker ? (
              <div className="ga-marker-card">
                <div className="ga-form-row">
                  <span className="ga-hint" style={{ minWidth: 20 }}>🎯 {selIdx + 1}</span>
                  <select
                    className="ga-input"
                    style={{ flex: 1, minWidth: 0 }}
                    value={selMarker.group}
                    title={t('Place type of the pose catalog (seat, bed, floor …) — WHAT this spot is, not which clip plays on it. A character taking a pose of this type is seated here.')}
                    onChange={(e) => patchMarker(selIdx, { group: e.target.value })}
                  >
                    {groupOptions.map((k) => (
                      <option key={k} value={k}>{groupLabel(groups, k)}</option>
                    ))}
                    {/* A stored place type the catalog no longer offers stays
                        selectable — losing it silently would rewrite the
                        marker on the next save. */}
                    {selMarker.group && !groupOptions.includes(selMarker.group) ? (
                      <option value={selMarker.group}>{selMarker.group}</option>
                    ) : null}
                  </select>
                  <button
                    type="button"
                    className={`ga-btn ga-btn-sm${placing === selIdx ? ' ga-btn-primary' : ''}`}
                    // One canvas, one gesture: while a ring is being drawn the
                    // SVG over the viewer swallows every click a pick needs.
                    disabled={!!drawKind}
                    onClick={() => armPlacing(selIdx)}
                    title={drawKind
                      ? t('Finish or cancel the surface you are drawing first — the ring and the marker pick share the one preview.')
                      : t('Then click the spot on the model in the viewer to move this marker there (Esc cancels).')}
                  >
                    ✥
                  </button>
                  <button
                    type="button"
                    className="ga-btn ga-btn-sm ga-btn-danger"
                    onClick={() => removeMarker(selIdx)}
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
                      value={selMarker.at[ax]}
                      onChange={(v) => setMarkerAt(selIdx, ax as 0 | 1 | 2, v)}
                      sliderWidth="auto"
                      sliderStyle={{ flex: 1, minWidth: 60 }}
                      inputWidth={72}
                      readback={(
                        <span className="ga-hint" style={{ width: 58, flex: '0 0 auto', textAlign: 'right' }}
                          title={t('Fraction × this variant’s dimension.')}>
                          {(selMarker.at[ax] * dimM).toFixed(2)} m
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
                  value={selMarker.facing}
                  fallback={0}
                  clearable
                  placeholder="—"
                  onChange={(v) => patchMarker(selIdx, { facing: ((v % 360) + 360) % 360 })}
                  onClear={() => patchMarker(selIdx, { facing: undefined })}
                  sliderWidth="auto"
                  sliderStyle={{ flex: 1, minWidth: 60 }}
                  inputWidth={72}
                >
                  <button
                    type="button"
                    className="ga-btn ga-btn-sm"
                    style={{ width: 58, flex: '0 0 auto' }}
                    disabled={selMarker.facing === undefined}
                    onClick={() => patchMarker(selIdx, { facing: undefined })}
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
                  value={selCapacity}
                  onChange={(v) => {
                    const cap = Math.max(1, Math.min(8, Math.round(v)))
                    // Capacity 1 is a single spot and carries neither key —
                    // the same shape the server stores.
                    patchMarker(selIdx, cap > 1
                      ? { capacity: cap }
                      : { capacity: undefined, spacing_m: undefined,
                          slot_axis: undefined })
                  }}
                  sliderWidth="auto"
                  sliderStyle={{ flex: 1, minWidth: 60 }}
                  inputWidth={72}
                />
                {selCapacity > 1 ? (
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
                    value={selMarker.spacing_m ?? 0.6}
                    onChange={(v) => patchMarker(selIdx, { spacing_m: Math.round(v * 100) / 100 })}
                    unit="m"
                    sliderWidth="auto"
                    sliderStyle={{ flex: 1, minWidth: 60 }}
                    inputWidth={72}
                  />
                ) : null}
                {/* WHICH WAY THE ROW RUNS (2026-08-29, user decision). 90° —
                    across the facing — is right for everyone who sits or
                    stands: their shoulders are the narrow side. A LYING pose
                    turns the body across the facing instead, so the same 90°
                    row runs down the body and two sleepers land head-to-foot;
                    0° puts them side by side. The figures in the preview
                    follow it live, which is what makes it dialable at all. */}
                {selCapacity > 1 ? (
                  <SliderInput
                    className="ga-marker-axis"
                    style={{ display: 'flex', fontSize: '0.8em' }}
                    title={t('Which way the row of slots runs, in degrees off the facing. 90 = across it — right for sitting and standing, where the shoulders are the narrow side. 0 = along it, which is what a bed wants: a lying figure already lies across its facing, so a 90° row would stack the sleepers head-to-foot instead of side by side. Watch the preview figures while you turn it.')}
                    label={<span className="ga-hint" style={{ width: 66, flex: '0 0 auto' }}>{t('Slot axis')}</span>}
                    ariaLabel={t('Slot axis')}
                    min={0}
                    max={180}
                    step={5}
                    fineStep={1}
                    value={selMarker.slot_axis ?? 90}
                    onChange={(v) => patchMarker(selIdx,
                      { slot_axis: Math.max(0, Math.min(180, Math.round(v))) })}
                    unit="°"
                    sliderWidth="auto"
                    sliderStyle={{ flex: 1, minWidth: 60 }}
                    inputWidth={72}
                  />
                ) : null}
                {selPoses.length ? (
                  <div className="ga-form-row" style={{ fontSize: '0.8em' }}
                    title={t('Which pose of this place type the preview figures hold — view only, nothing is stored. Every slot shows it; a pair pose seats both halves around the marker.')}>
                    <span className="ga-hint" style={{ width: 66, flex: '0 0 auto' }}>
                      {t('Pose')}
                    </span>
                    <button type="button" className="ga-btn ga-btn-sm"
                      onClick={() => setPreview(selPoses[(selPoseIdx + selPoses.length - 1) % selPoses.length])}>
                      ◀
                    </button>
                    <span className="ga-hint" style={{ flex: 1, minWidth: 0 }}>
                      {selPoses[selPoseIdx]} ({selPoseIdx + 1}/{selPoses.length})
                    </span>
                    <button type="button" className="ga-btn ga-btn-sm"
                      onClick={() => setPreview(selPoses[(selPoseIdx + 1) % selPoses.length])}>
                      ▶
                    </button>
                  </div>
                ) : null}
              </div>
            ) : null}
          </div>
        </div>

        {/* THE VARIANT COLUMN — everything the SELECTED variant IS: its
            picture, its metres, its sink, its orientation fix, its walkable
            surface, its areas. The model all of it is dialled against stands
            in the column to the right, in view the whole time.
            ONE HEADER (2026-08-29, user decision): this whole column speaks
            about the variant the strip has open, so it is named ONCE at the
            top instead of appending "· Variant n" to every section below. */}
        <div className="ga-form">
          <div className="ga-form-section-label" style={{ marginTop: 0 }}>
            {t('Variant')} {variant + 1}
          </div>
          {variantBusy ? (
            <span className="ga-hint">
              {t('Generating the model — this takes a few minutes.')}
            </span>
          ) : pending ? (
            // Another variant of the same prop is busy — worth saying, but it
            // blocks nothing here.
            <span className="ga-hint">
              {t('Another variant of this prop is generating.')}
            </span>
          ) : null}
          {/* The SELECTED VARIANT's source image — and it can be re-meshed
              straight from here into the model opposite (the dialog picks
              backend / face count / texture size; the image render is
              skipped). It follows the strip: the image belongs to the variant,
              so a second version of the object never shows (or overwrites) the
              first one's picture. */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <div className="ga-form-section-label" style={{ margin: 0 }}>
              {t('Source image')}
            </div>
            {shownImage && srcOk ? (
              <img
                src={`/assets/props/${enc}/source?variant=${variant}&v=${reloadKey}`}
                alt={t('Source image')}
                onError={() => setSrcOk(false)}
                {...enlarge(
                  { src: `/assets/props/${enc}/source?variant=${variant}&v=${reloadKey}`, alt: `${prop.name} — ${t('Source image')}` },
                  { width: '100%', maxHeight: 300,
                    objectFit: 'contain', borderRadius: 8,
                    border: '1px solid var(--border, #30363d)',
                    background: 'rgba(255,255,255,0.04)' })}
              />
            ) : (
              <div className="ga-empty">
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
                onClick={() => onRegenerateImage(variant, 'front',
                  shownImage || undefined,
                  shownVariant?.description || prop.name,
                  !!shownVariant?.has_source)}
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
                  if (f) void uploadSource(f, 'front')
                  e.target.value = ''
                }} />
              <button type="button" className="ga-btn ga-btn-sm"
                onClick={onRefresh}
                title={t('Reload — fetch the current image and metadata (the render runs in the background).')}>
                🔄
              </button>
            </div>
            {/* THE EXTRA VIEWS (design 2026-09-02). Beside the front picture
                a variant may hold a back and two side shots — mesh input for
                a multi-view img2mesh alias, one tile each: render it (the
                dialog offers the front as the appearance reference), upload
                one, or drop it again. They replace nothing: the front stays
                the source image, and a view reaches the mesh only when the
                re-mesh dialog below has it picked. */}
            <div className="ga-form-section-label" style={{ margin: '6px 0 0' }}>
              {t('Extra views (multi-view mesh)')}
            </div>
            <div style={{ display: 'flex', gap: 6 }}>
              {PROP_EXTRA_VIEWS.map((view) => {
                const rec = shownVariant?.images?.[view]
                return (
                  <div key={view} style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 3 }}>
                    <span className="ga-hint">{t(VIEW_LABEL[view])}</span>
                    {rec ? (
                      <img
                        src={`/assets/props/${enc}/source?variant=${variant}&view=${view}&v=${reloadKey}`}
                        alt={t(VIEW_LABEL[view])}
                        {...enlarge(
                          { src: `/assets/props/${enc}/source?variant=${variant}&view=${view}&v=${reloadKey}`,
                            alt: `${prop.name} — ${t(VIEW_LABEL[view])}`,
                            caption: rec.backend ? `${rec.backend}${rec.generated_at ? ` · ${rec.generated_at.slice(0, 10)}` : ''}` : t('Uploaded') },
                          { width: '100%', aspectRatio: '1', objectFit: 'contain', borderRadius: 6,
                            border: '1px solid var(--border, #30363d)', background: 'rgba(255,255,255,0.04)' })}
                        title={`${rec.backend ? `🖼 ${rec.backend}${rec.generated_at ? ` · ${rec.generated_at.slice(0, 10)}` : ''}` : t('Uploaded')} — ${t('Click to enlarge')}`} />
                    ) : (
                      <div style={{ width: '100%', aspectRatio: '1', borderRadius: 6,
                        border: '1px dashed var(--border, #30363d)', display: 'flex',
                        alignItems: 'center', justifyContent: 'center' }}>
                        <span className="ga-hint">{t('none')}</span>
                      </div>
                    )}
                    <div style={{ display: 'flex', gap: 3 }}>
                      <button type="button" className="ga-btn ga-btn-sm" style={{ flex: 1 }}
                        disabled={variantBusy}
                        onClick={() => onRegenerateImage(variant, view, rec,
                          shownVariant?.description || prop.name,
                          !!shownVariant?.has_source)}
                        title={t('Render this view (optionally with the front image as reference).')}>
                        🖼
                      </button>
                      {/* Upload and delete are locked while the variant runs
                          for the same reason the front's 🖼 is: a mesh run
                          READS the view files when it starts, so swapping or
                          dropping one mid-run would bake a picture nobody
                          asked for. */}
                      <button type="button" className="ga-btn ga-btn-sm"
                        disabled={variantBusy}
                        onClick={() => { setUploadView(view); viewUploadRef.current?.click() }}
                        title={variantBusy
                          ? t('This variant is generating right now.')
                          : t('Upload a picture as this view.')}>
                        ⬆
                      </button>
                      {rec ? (
                        <button type="button" className="ga-btn ga-btn-sm ga-btn-danger"
                          disabled={variantBusy}
                          onClick={() => {
                            if (armedView === view) { setArmedView(null); void deleteView(view) }
                            else setArmedView(view)
                          }}
                          title={variantBusy
                            ? t('This variant is generating right now.')
                            : armedView === view ? t('Click again to delete this view') : t('Delete this view image')}>
                          {armedView === view ? t('Sure?') : '×'}
                        </button>
                      ) : null}
                    </div>
                  </div>
                )
              })}
              <input ref={viewUploadRef} type="file" accept="image/*" style={{ display: 'none' }}
                onChange={(e) => {
                  const f = e.target.files?.[0]
                  if (f) void uploadSource(f, uploadView)
                  e.target.value = ''
                }} />
            </div>
            {/* The re-mesh targets the SELECTED variant — that is the whole
                difference to 🧊 above, which appends another one. It reads
                the image shown here, which is that variant's own. */}
            <button type="button" className="ga-btn ga-btn-sm"
              disabled={variantBusy || !shownImage || !srcOk}
              onClick={() => onRegenerateMesh(variant,
                PROP_EXTRA_VIEWS.filter((v) => !!shownVariant?.images?.[v]))}
              title={variantBusy
                ? t('This variant is generating right now.')
                : t('Mesh THIS image again into the SELECTED variant — no new render, no new variant; backend, face count and texture size come from the dialog. Dims and markers stay.')}>
              ⚙ {t('3D from this image')}
            </button>
          </div>
          {/* WHAT THIS VERSION IS (2026-08-29). The three numbers every
              renderer scales its mesh by, how deep it stands in the ground and
              the subject its product shot is rendered from — the variant's own
              fields, dialled against the model beside them rather than inside
              a chip in the other column. Nothing is written until Save: every
              commit here goes into the change buffer, which is also what the
              preview reads, so a typed metre is on screen at once. */}
          {shownVariant ? (
            <>
              <div className="ga-form-section-label">{t('Variant settings')}</div>
              <div className="ga-form-row" style={{ gap: 8, alignItems: 'center' }}>
                {DIM_FIELDS.map((f) => {
                  const shown = dimDraft[f.key] ?? String(shownVariant.dims[f.key])
                  return (
                    <label
                      key={f.key}
                      style={{ display: 'flex', alignItems: 'center', gap: 3 }}
                      title={`${t(f.title)} — ${t('the real extent of THIS variant’s mesh after the orientation fix.')} ${t('Edit one of the three and the other two follow this variant’s proportions — a prop is always scaled uniformly, so the trio says how big it is, its ratios say what shape.')}`}
                    >
                      <span className="ga-hint">{t(f.label)}</span>
                      <input
                        className="ga-input"
                        type="number"
                        min={0.01}
                        max={100}
                        step={0.05}
                        style={{ width: 74 }}
                        value={shown}
                        onChange={(e) => {
                          const value = e.target.value
                          setDimDraft((d) => ({ ...d, [f.key]: value }))
                        }}
                        onBlur={(e) => commitDim(f.key, e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') e.currentTarget.blur()
                        }}
                      />
                      <span className="ga-hint">m</span>
                    </label>
                  )
                })}
              </div>
              {shownVariant.dims_estimated ? (
                <span className="ga-hint">
                  {t('Estimated — refined automatically when the model arrives.')}
                </span>
              ) : null}
              {/* HOW DEEP THIS VERSION STANDS IN THE GROUND — it applies
                  wherever this variant is drawn: every manual placement, every
                  scattered copy in a room or yard, every instance of a painted
                  terrain scatter and every world prop. The per-placement
                  `offset_y` in the room editor stays the trim of ONE instance
                  on top of it. A TYPED number, no dial (user 2026-08-25):
                  sinking is a value you know — 0.05 for a mesh with a base
                  plate, 0.4 to bury a root ball — and a slider that has to
                  sweep the whole ±5 m range cannot hit either. What makes it
                  judgeable is the 1.70 m figure in the viewer beside it. */}
              <SliderInput
                ariaLabel={t('Ground offset (m)')}
                label={<span className="ga-hint"
                  style={{ width: 66, flex: '0 0 auto' }}
                  title={t('Negative sinks this variant into the ground, positive lifts it off — the same amount everywhere it stands: rooms, yard, painted scatter, world props. Use it for a mesh that carries no root ball or base plate. 0 = it stands on the ground.')}>
                  ⤓ {t('Sink')}
                </span>}
                style={{ display: 'flex', fontSize: '0.85em' }}
                unit="m"
                slider={false}
                min={-SINK_LIMIT_M}
                max={SINK_LIMIT_M}
                step={0.01}
                value={shownVariant.ground_offset_m}
                onChange={commitSink}
                inputWidth={74}
              />
              {/* The variant's own generation subject (2026-08-24). A new
                  variant starts with a COPY of the one it was added from, so
                  the field opens filled and is EDITED ("…as a sapling")
                  instead of written from nothing. Cleared = the render
                  composes from the prop's name. Five lines at rest — enough to
                  READ the sentence without opening it — and twelve while it is
                  being written. */}
              <textarea
                className="ga-textarea"
                rows={descOpen ? DESC_ROWS_OPEN : DESC_ROWS_REST}
                style={{ width: '100%', resize: 'vertical' }}
                value={descDraft ?? (shownVariant.description || '')}
                placeholder={t('Description (generation subject)')}
                title={t('What THIS variant’s source image is rendered from — the subject of its prompt. Empty = the render composes from the prop’s name. A new variant starts as a copy of the one it was added from, so a version differs by an edit: “…as a sapling”, “…broken”, “…covered in snow”.')}
                onFocus={() => setDescOpen(true)}
                onChange={(e) => setDescDraft(e.target.value)}
                onBlur={(e) => {
                  setDescOpen(false)
                  commitDesc(e.target.value)
                }}
              />
            </>
          ) : null}

          {/* Orientation fix — ↻ adds +90°, the field sets a free exact angle.
              IT BELONGS TO THE FILE (v2 E1): what is dialled here is the OPEN
              variant's active full mesh, and the low mesh follows it. Every
              variant answers, a switched-off or out-of-season one included —
              the angles come from the areas payload, which is read per store
              index. Only while that payload is still on its way is there
              nothing to dial: a 0 offered then would be written over the
              stored angles by the next click. */}
          {shownHasMesh ? (
            <>
              <div className="ga-form-section-label">
                {t('Orientation fix')}
              </div>
              <div className="ga-form-row">
                {(['x', 'y', 'z'] as const).map((axis) => (
                  <span key={axis} style={{ display: 'inline-flex', gap: 2, alignItems: 'center' }}>
                    <button type="button" className="ga-btn ga-btn-sm"
                      disabled={!variantAreas}
                      onClick={() => { void rotate(axis) }} title={t('+90°')}>
                      ↻ {axis.toUpperCase()}
                    </button>
                    <input
                      key={`${axis}-${variant}-${variantRotation?.[axis] || 0}`}
                      className="ga-input" type="number" min={-360} max={720} step={0.1}
                      style={{ width: 64 }}
                      disabled={!variantAreas}
                      defaultValue={variantRotation?.[axis] || 0}
                      title={t('Exact angle in degrees — free rotation for meshes that came out tilted.')}
                      onBlur={(e) => { void setRotationAxis(axis, e.target.value) }}
                      onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
                    />
                  </span>
                ))}
              </div>
              <span className="ga-hint">
                {variantAreas
                  ? t('Orientation fix of this variant’s model file — persisted; the 3D client applies it on load.')
                  : (areasFailed
                    ? t('Could not read this prop’s areas — reload the page.')
                    : t('Reading the areas…'))}
              </span>
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
                {/* Gated on the FILE, not on the state: a lattice is a file,
                    and offering to remove nothing teaches the wrong thing —
                    but an unparseable sidecar reads as `missing` while lying
                    on disk, and that is exactly the case where removing it is
                    the repair. Stale counts too. */}
                {shownSurface?.file ? (
                  <>
                    <button type="button"
                      className={'ga-btn ga-btn-sm' + (removeArmed ? ' ga-btn-danger' : '')}
                      onClick={() => {
                        if (removeArmed) void removeSurface()
                        else setRemoveArmed(true)
                      }}
                      title={t('Throw the baked lattice away — figures walk on the terrain again until it is baked anew')}>
                      {removeArmed ? t('Really remove?') : t('Remove surface')}
                    </button>
                    {removeArmed ? (
                      <button type="button" className="ga-btn ga-btn-sm"
                        onClick={() => setRemoveArmed(false)}>
                        {t('Cancel')}
                      </button>
                    ) : null}
                  </>
                ) : null}
              </div>
            </>
          ) : null}

          {/* THE KEY SURFACES of the OPEN variant's mesh and the pictures hung
              on this prop (spec-picture-props.md § 4). It needs a mesh to read
              them off, so it appears with the model — and it works on the
              SELECTED variant (v2 E1): every variant is its own generation
              with its own materials, and a new picture variant still copies
              the primary frame, which the panel says. */}
          {shownHasMesh ? (
            <PropAreasPanel
              prop={prop}
              variant={variant}
              variants={serverVariants}
              variantMax={variantMax}
              reloadKey={reloadKey}
              // The areas of the OPEN variant, read once above — the panel
              // lists and splits exactly the file the preview shows.
              info={variantAreas}
              infoFailed={areasFailed}
              // The one 3D view (V11): the panel has none of its own, it
              // switches the preview in the column beside it and shares its
              // call lock.
              tools={areaTools}
              onVariantsChanged={() => { void loadVariants() }}
            />
          ) : null}

        </div>

        {/* THE MODEL COLUMN — the widest of the three, because it is the
            thing being judged: the mesh of the SELECTED variant, and
            directly under it the resolution tiers, which are nothing but
            "which file of it do the clients get at which distance".
            Each column is its own scroll pane (.ga-detail-cols--panes), so
            it stays in view while the two columns to its left scroll
            through places, settings and areas. */}
        <div className="ga-form">
          <div className="ga-form-section-label" style={{ marginTop: 0 }}>
            {t('3D preview')}
          </div>
          <div ref={viewerRef}>
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
              // The fix of the OPEN variant's file (v2 E1) — the prop has none
              // any more, and a neighbour's angles would tilt this mesh.
              rotation={variantRotation}
              // Switching variant or tier swaps ANOTHER VERSION of the same
              // object under the camera — the angle stays, "Reset view" frames
              // again on demand (§ B1).
              keepCamera
              // ── THE AREAS MODE (V11) ──────────────────────────────────
              // The one view is also the authoring view: the front view is a
              // mode of it, the outlines are drawn on it, a ring is projected
              // against ITS camera, and the assembly the panel below picks is
              // hung on this very mesh. Everything mesh-bound is offered only
              // while the SERVED file of the open variant is on screen — a
              // file picked in the gallery has another face order.
              frontal={areaFrontal}
              onFrontalChange={(on) => setAreaView({ frontal: on })}
              areaOutlines={areasOnView ? areaOutlines : undefined}
              meshLayout={areasOnView ? variantAreas?.mesh_layout : undefined}
              slots={areasOnView ? previewSlots : undefined}
              drawing={areasOnView && !!drawKind}
              drawThrough={drawKind === 'leaf'}
              onPolygonFaces={onPolygonFaces}
              onDrawCancel={() => setAreaView({ drawKind: '' })}
              leafBbox={areasOnView ? (variantAreas?.leaf_bbox || null) : null}
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
                  slot_axis: m.slot_axis,
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
          {/* WHICH numbers the preview is measuring — the open variant's,
              always. It is the one the column to the left is about,
              so the line says the metres and not the number. */}
          <span className="ga-hint" style={{ display: 'block' }}>
            {t('Measured: {w} × {d} × {h} m.')
              .replace('{w}', shownDims.width_m.toFixed(2))
              .replace('{d}', shownDims.depth_m.toFixed(2))
              .replace('{h}', shownDims.height_m.toFixed(2))}
          </span>
          </div>

          {/* THE RESOLUTION TIERS of the SELECTED variant, directly under the
              preview (user 2026-08-29): which file the clients get at which
              distance is what the viewer above is showing, so the two belong
              together. The section carries the gallery — every stored run, one
              active file per tier, upload and delete — and the two triangle
              budgets that decide what the next run costs. */}
          <PropModelPanel
            propId={prop.id}
            variant={variant}
            reloadKey={reloadKey}
            preview={previewFile}
            onPreview={showStoredFile}
            onChanged={meshesChanged}
            pending={variantBusy}
            // The SELECTED variant's own budgets (v2 E5) — the distance-mesh
            // button names the low one, the reduction dialog opens on it, and
            // the two fields in the section edit them.
            faceTargets={{ high: shownVariant?.target_faces_high,
              low: shownVariant?.target_faces_low }}
            // Without a variant record there is nothing to commit into —
            // `commitFaces` would return on its own doorstep — so the two
            // fields are not offered at all, the same gate the Variant
            // settings in the column beside them stand behind.
            onEditFaceTarget={shownVariant ? commitFaces : undefined}
            backendFaces={backendFaces}
            onGenerating={onGenerating}
          />
        </div>
      </div>
    </>
  )
}
