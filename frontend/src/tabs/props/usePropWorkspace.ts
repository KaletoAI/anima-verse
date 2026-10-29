/** One draft, revision, variant and viewer-tool owner for the five prop areas. */
import { useModelWater } from './WaterPanel'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useEnlarge } from '../../components/ZoomButton'
import { useI18n } from '../../i18n/I18nProvider'
import { ApiError, apiDelete, apiGet, apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { setUnsavedGuard } from '../../lib/unsavedGuard'
import {
  applyVariantDraft, draftValue, emptyFields, fieldConflicts, dropPendingField,
  GENERAL_TARGET, pendingFieldCount, queueFields, toBulkFieldBody,
  variantTarget, type PendingFields, type AuthorFields, type FieldConflict,
} from './pendingFields'
import {
  groupKeys, newId, posesInGroup, type PoseCatalog,
} from '../world/placeTypes'
import {
  descPatch,
  facePatch, sinkPatch,
} from './variantFields'
import type { DimKey } from './dims'
import { editDimensionGesture, type DimensionGesture } from './dimensionGesture'
import { type AccessRole, type AccessPoint } from './accessGeometry'
import { usePropActionCatalog } from './usePropActionCatalog'
import { propActionCheckDocument } from './propActionChecks'
import { actionEditorIssues } from './propActionAuthoring'
import type {
  PropAreasInfo, PropFull, PropLight, PropMarker, PropSlotValues, PropSourceImage,
  PropVariant, PropView, PropWorkspaceArea, PropActionIssue, VariantBinding, PropAccessPreviews,
} from './propTypes'
import { resolveVariantAfterBarrier, propGenerationSubject, propGenerationTarget,
  propGenerationAuthor, resolvePropRepairAfterBarrier, type PropGenerationTarget,
  type PropGenerationRepair, type PropRepairSnapshot, type PropRepairConfirmation } from './propOperations'

// Starting values from the prop-lights spec, section 7.1.
export const LIGHT_PRESETS: Array<{ name: string; light: Omit<PropLight, 'at'> }> = [
  { name: 'Candle', light: { color: '#ffb35c', intensity: 1.5, range_m: 4, flicker: 'candle', when: 'always', glow_m: 0.10 } },
  { name: 'Oil lamp', light: { color: '#ffc070', intensity: 2.5, range_m: 5, flicker: 'candle', when: 'always', glow_m: 0.14 } },
  { name: 'Fire', light: { color: '#ff8a3c', intensity: 8, range_m: 9, flicker: 'fire', when: 'always', glow_m: 0.5 } },
  { name: 'Ceiling lamp', light: { color: '#fff0d0', intensity: 6, range_m: 8, flicker: 'none', when: 'always', glow_m: 0.2 } },
  { name: 'Street lamp', light: { color: '#ffd9a0', intensity: 15, range_m: 14, flicker: 'none', when: 'night', glow_m: 0.3 } },
  { name: 'Crystal', light: { color: '#8fd8ff', intensity: 2, range_m: 4, flicker: 'none', when: 'always', glow_m: 0.25 } },
  { name: 'Monitor', light: { color: '#b8d4ff', intensity: 1.2, range_m: 2.5, flicker: 'none', when: 'always', glow_m: 0.05 } },
]

/**
 * The scale kit of the 3D preview — the 1.70 m reference figure beside the
 * prop plus the metre grid under both (rule "Always show a scale for dimensions").
 * Remembered per browser, ON until it is switched off: a mesh alone says
 * nothing about its size, so the first look should already carry the scale.
 */
const SCALE_FIGURE_KEY = 'ga.props.scaleFigure'

/** Human name of each view — the tile captions of the source panel. Same
 *  wording as `MeshBackendDialog` and `PropImageDialog`. */
export const VIEW_LABEL: Record<PropView, string> = {
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

export function saveScaleFigure(on: boolean): void {
  try { window.localStorage.setItem(SCALE_FIGURE_KEY, on ? '1' : '0') }
  catch { /* a browser that refuses storage still gets its figure */ }
}

// Marker `at` = fractions of the RAW box in the order [X, Y, Z] — mirrors
// props.MARKER_AT_MIN/MAX: half a box of slack below and a full box above,
// because seats and lying surfaces sit ON the hull or outside it.
const AT_MIN = -0.5
export const AT_MAX = 2
// The height axis reaches a FULL box below (props.MARKER_AT_Y_MIN) — deep
// seat positions in tall machines sit far under the box top.
export const AT_AXES: Array<{ label: string; dim: DimKey; min: number }> = [
  { label: 'X (width)', dim: 'width_m', min: AT_MIN },
  { label: 'Y (height)', dim: 'height_m', min: -1 },
  { label: 'Z (depth)', dim: 'depth_m', min: AT_MIN },
]

function authorSnapshot(prop: PropFull, variants: PropVariant[]): AuthorFields {
  return new Map<string, Record<string, unknown>>([
    [GENERAL_TARGET, { name: prop.name, category: prop.category,
      tags: prop.tags.join(', '), sway_factor: prop.sway_factor ?? 1,
      mount: { value: prop.mount || '', suggested: !!prop.mount_suggested },
      actions: prop.actions, slots: prop.slots, key_areas: prop.key_areas }],
    ...variants.map((v): [string, Record<string, unknown>] => [
      variantTarget(v.uid), { dims: v.dims, description: v.description,
        ground_offset_m: v.ground_offset_m, markers: v.markers,
        seasons: v.seasons, light: v.light ?? null,
        face_targets: { target_faces_high: v.target_faces_high ?? null,
          target_faces_low: v.target_faces_low ?? null } },
    ]),
  ])
}

export function usePropWorkspace({ prop, pending, generatingVariants, cacheBump,
  onChanged, onDelete, armedDelete, onRegenerate, onRegenerateMesh,
  onRegenerateImage, onRefresh, onGenerating, backendFaces = 0,
  onDirtyChange, area, onAreaChange }: {
  prop: PropFull
  /** Library-owned navigation preference; prop-specific state remains keyed by prop id. */
  area: PropWorkspaceArea
  onAreaChange: (area: PropWorkspaceArea) => void
  /** ANY variant of this prop is generating — aggregate status. Target
   *  availability and variant-scoped controls use `generatingVariants`. */
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
  onRegenerateMesh: (target: PropVariant, existingViews: PropView[]) => void
  /** Re-run the source→mesh chain with the stored description/name — this
   *  APPENDS another model variant. */
  onRegenerate: (target: PropGenerationTarget, author: PropVariant) => void
  /** Render a NEW source image for the SELECTED variant only — its mesh stays
   *  until re-meshed, and no other variant's image is touched. `view` says
   *  WHICH of the four pictures is being rendered, `image` is that view's own
   *  record (so the dialog opens on the backend THIS picture was made with)
   *  and `refVariants` names every variant that holds a front image — the
   *  pictures the dialog may offer as this render's appearance reference.
   *  `PropFull` has no variant list, the detail owns it. */
  onRegenerateImage: (target: PropVariant, view: PropView, image: PropSourceImage | undefined,
    subject: string, refs: PropVariant[], author: PropFull) => void
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
  const [mobilePane, setMobilePane] = useState<'editor' | 'preview'>('editor')
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
  // by stable target ("general" / "v:<uid>") and merges field by field, so
  // editing the size and then the subject of one variant is one entry with two
  // fields — see `pendingFields` for the rules.
  const [buf, setBuf] = useState<PendingFields>(emptyFields)
  const baseRevision = useRef(prop.revision)
  const baseline = useRef<AuthorFields>(authorSnapshot(prop, []))
  const [variantRevision, setVariantRevision] = useState('')
  const [variantLoadError, setVariantLoadError] = useState('')
  const [conflicts, setConflicts] = useState<FieldConflict[]>([])
  const [saveError, setSaveError] = useState('')
  const [operation, setOperation] = useState<{
    label: string; resolve: (continueOperation: boolean) => void
  } | null>(null)
  const operationRef = useRef(operation)
  operationRef.current = operation
  const beforeImmediate = useCallback((label: string): Promise<boolean> => {
    if (!dirtyRef.current) return Promise.resolve(true)
    // ES2020 is the admin's supported library target (no withResolvers).
    return new Promise<boolean>((resolve) => {
      operationRef.current?.resolve(false)
      const nextOperation = { label, resolve }
      operationRef.current = nextOperation
      setOperation(nextOperation)
    })
  }, [])
  const finishOperation = useCallback((proceed: boolean) => {
    operationRef.current?.resolve(proceed)
    operationRef.current = null
    setOperation(null)
  }, [])
  useEffect(() => () => { operationRef.current?.resolve(false) }, [])
  const prepareVariantOperation = useCallback(async (uid: string, label: string) => {
    try {
      return await resolveVariantAfterBarrier(uid, () => beforeImmediate(label),
        async () => (await apiGet<{ variants: PropVariant[] }>(
          `/world/props/${enc}/variants`)).variants)
    } catch (error) {
      toast(t((error as Error).message), 'error')
      return null
    }
  }, [beforeImmediate, enc, toast, t])
  const [saving, setSaving] = useState(false)
  const [saveIssues, setSaveIssues] = useState<PropActionIssue[]>([])
  // Server issue paths index the validated snapshot, not a later edited/reloaded list.
  useEffect(() => { setSaveIssues([]) }, [buf, variantRevision, prop.revision])
  const [selectedActionId, setSelectedActionId] = useState('')
  const { catalog, reloadActionCatalog } = usePropActionCatalog()
  /** The Discard button's second click (no `window.confirm` in this UI). */
  const [discardArmed, setDiscardArmed] = useState(false)
  const dirtyCount = pendingFieldCount(buf)
  useEffect(() => { if (!dirtyCount) setDiscardArmed(false) }, [dirtyCount])
  const [serverVariants, setServerVariants] = useState<PropVariant[]>([])
  const queueGeneral = useCallback((patch: Record<string, unknown>) => {
    setBuf(previous => {
      return queueFields(previous, GENERAL_TARGET, patch)
    })
  }, [])
  const queueVariant = useCallback((index: number, patch: Record<string, unknown>) => {
    const row = serverVariants.find(v => v.index === index)
    if (row) setBuf(b => queueFields(b, variantTarget(row.uid), patch))
  }, [serverVariants])
  const [variantMax, setVariantMax] = useState(1)
  // The world's season names + the one it is in now (E2c) — the season chips
  // are a pick from this list, and an empty list (a world without seasons)
  // means the strip shows no season controls at all.
  const [worldSeasons, setWorldSeasons] = useState<string[]>([])
  const [currentSeason, setCurrentSeason] = useState('')
  // The variant everything below the strip works on. Index, not stem: that is
  // what every variant-scoped route takes.
  const [variant, setVariant] = useState(0)
  const selectedUid = useRef('')
  selectedUid.current = serverVariants.find((entry) => entry.index === variant)?.uid || ''
  const onVariantDeleted = useCallback(() => {
    // Selection follows the surviving UID when the fresh list arrives.
    setPreviewFile('')
    setPlacing(null)
  }, [])
  // Dropping the list with the selection matters: a record of the PREVIOUS
  // prop would otherwise answer for the same index until the reload lands.
  // The draft goes with it — it belongs to the prop that was open, and the
  // container has already asked whether it may be lost.
  useEffect(() => {
    setVariant(0)
    setServerVariants([])
    setBuf(emptyFields())
    baseline.current = authorSnapshot(prop, [])
    baseRevision.current = prop.revision
    setVariantRevision('')
    setConflicts([])
    setSaveError('')
    setSaveIssues([])
    setSelectedActionId('')
  }, [prop.id])
  useEffect(() => { setPreviewFile('') }, [prop.id, variant])
  const variantRequest = useRef(0)
  const loadVariants = useCallback(async () => {
    const request = ++variantRequest.current
    try {
      const d = await apiGet<{ variants?: PropVariant[]; max?: number
        revision: string; world_seasons?: string[]; current_season?: string }>(
        `/world/props/${enc}/variants`)
      if (request !== variantRequest.current) return
      const list = d.variants || []
      const previousUid = selectedUid.current
      setVariantLoadError('')
      setServerVariants(list)
      setVariantRevision(d.revision)
      setVariantMax(d.max || 1)
      setWorldSeasons(d.world_seasons || [])
      setCurrentSeason(d.current_season || '')
      // Clamping belongs HERE and not in an effect of its own: a deletion
      // shortens the list, and a separate effect would fight the strip, which
      // selects the freshly added slot before its record has arrived.
      setVariant((i) => list.find((entry) => entry.uid === previousUid)?.index
        ?? list[Math.min(i, Math.max(0, list.length - 1))]?.index ?? 0)
    } catch (error) {
      if (request !== variantRequest.current) return
      setVariantLoadError((error as Error).message)
    }
  }, [enc])
  useEffect(() => { void loadVariants() }, [loadVariants, reloadKey, prop.revision])
  // General and variant records must describe the SAME author revision.
  // A poll/file operation may deliver them separately; never advance the base
  // against a half-old document. Only disjoint author fields rebase silently.
  useEffect(() => {
    if (variantRevision !== prop.revision) return
    const next = authorSnapshot(prop, serverVariants)
    const overlap = fieldConflicts(buf, baseline.current, next)
    setConflicts(overlap)
    if (!overlap.length) {
      baseline.current = next
      baseRevision.current = prop.revision
    }
  }, [prop, serverVariants, variantRevision, buf])
  const revisionReady = variantRevision === prop.revision && !variantLoadError
  const resolveConflict = (conflict: FieldConflict, keepLocal: boolean) => {
    if (variantRevision !== prop.revision) return
    const next = authorSnapshot(prop, serverVariants)
    const accepted = new Map(baseline.current)
    accepted.set(conflict.target, { ...accepted.get(conflict.target),
      [conflict.field]: next.get(conflict.target)?.[conflict.field] })
    baseline.current = accepted
    if (!keepLocal) {
      setBuf((b) => dropPendingField(b, conflict.target, conflict.field))
    } else {
      // A new Map retriggers the comparison without rewriting the local value.
      setBuf((b) => new Map(b))
    }
    setSaveError('')
  }
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
  const waterController = useModelWater(
    shownHasMesh ? `/world/props/${enc}/variants/${variant}/water` : '',
    `${reloadKey}-${prop.revision}-${JSON.stringify(variantRotation)}`, async () => {
      const target = await prepareVariantOperation(shownVariant?.uid || '', t('Change water'))
      return target ? `/world/props/${enc}/variants/${target.index}/water` : null
    }, meshesChanged, shownVariant?.uid || '')
  const { setShape: cancelWaterPlacement } = waterController
  /** The kind the polygon tool is drawing for ('' = not drawing). */
  const [drawKind, setDrawKind] = useState('')
  /** Which picture variant the preview is assembled with (null = the open
   *  variant's own panes and pictures). */
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
  const [placing, setPlacing] = useState<'add' | 'light' | number | null>(null)
  const [accessPlacing, setAccessPlacing] = useState<{ markerId: string; role: AccessRole } | null>(null)
  useEffect(() => {
    if (waterController.shape) { setPlacing(null); setAccessPlacing(null); setDrawKind('') }
  }, [waterController.shape])
  useEffect(() => { setAccessPlacing(null) }, [selectedActionId])
  // A prop or variant switch puts another mesh under the camera: the view
  // state means nothing there, and the previous variant index means something
  // else on the next prop.
  useEffect(() => {
    setAreaFrontal(false); setDrawKind(''); setAreaPreview(null)
    setAccessPlacing(null)
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
      if (patch.drawKind && (saving || previewFile)) return
      setDrawKind(patch.drawKind)
      // ONE CANVAS, ONE GESTURE: arming the ring disarms the marker pick.
      if (patch.drawKind) {
        setMobilePane('preview')
        setAreaFrontal(true); setPreviewFile(''); setPlacing(null); cancelWaterPlacement(null)
        setAccessPlacing(null)
      }
    }
    if (patch.preview !== undefined) {
      setAreaPreview(patch.preview)
      if (patch.preview !== null) setPreviewFile('')
    }
  }, [cancelWaterPlacement, saving, previewFile])
  /** A file picked in the mesh gallery below. It is a DIFFERENT file — its
   *  triangles are not the ones the areas were split against — so the tools
   *  stand down while it is on screen. */
  const showStoredFile = useCallback((file: string) => {
    setPreviewFile(file)
    if (file) {
      setDrawKind(''); setAreaPreview(null); setPlacing(null)
      setAccessPlacing(null)
      cancelWaterPlacement(null)
    }
  }, [cancelWaterPlacement])
  /** Arm or disarm the marker pick — the other half of the exclusion: it
   *  drops a running ring, and while a ring IS running every pick button is
   *  disabled, so the two modes are never both offered. */
  const armPlacing = useCallback((which: 'add' | 'light' | number) => {
    if (saving || previewFile || !shownHasMesh) return
    setMobilePane('preview')
    setPlacing((cur) => (cur === which ? null : which))
    setDrawKind('')
    setAccessPlacing(null)
    cancelWaterPlacement(null)
  }, [cancelWaterPlacement, saving, previewFile, shownHasMesh])
  const armAccess = (markerId: string, role: AccessRole) => {
    if (saving || previewFile || !shownHasMesh) return
    setAccessPlacing(cur => cur?.markerId === markerId && cur.role === role ? null : { markerId, role })
    setPlacing(null); setDrawKind(''); cancelWaterPlacement(null)
    setMobilePane('preview')
  }
  /** Every areas call answers the same payload — one place that holds the
   *  lock, hands a fresh payload to the reader above (which drops it if the
   *  admin has moved on) and maps a failure onto a toast. */
  const runAreas = useCallback((what: string,
    call: (index: number) => Promise<unknown>): void => {
    setAreaBusy(what)
    void (async () => {
      const target = previewFile ? null : await prepareVariantOperation(
        shownVariant?.uid || '', t('Change model surfaces'))
      if (!target) {
        setAreaBusy('')
        return
      }
      try {
        if (variantAreas && target.model_file !== variantAreas.model_file) {
          throw new Error(t("The model changed. Reopen the surface tool."))
        }
        const answer = await call(target.index) as PropAreasInfo | undefined
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
  }, [onAreasInfo, reloadAreas, onRefresh, t, toast, prepareVariantOperation,
    shownVariant?.uid, variantAreas, previewFile])
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
    runAreas('draw', (index) => apiPost(`/world/props/${enc}/areas?variant=${index}`,
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
   *  With nothing picked the preview shows the OPEN variant the same way —
   *  its own panes and pictures, as the client renders it. Showing the bare
   *  mesh instead hid every mirror pane (a mirror has no picture variant to
   *  pick) and every picture variant opened from the strip.
   *
   *  KEYED BY CONTENT, deliberately: the viewer re-applies its slot materials
   *  whenever this object's identity changes — reloading every texture and
   *  rebuilding every mirror — and the variant list gets a fresh identity on
   *  every background poll while a generation runs. */
  const previewSlotsKey = useMemo(() => {
    const shown = areaPreview ?? variant
    const entry = serverVariants.find((v) => v.index === shown) || null
    const merged = entry
      ? { ...(entry.area_defaults || {}), ...(entry.slot_values || {}) }
      : {}
    return Object.keys(merged).length ? JSON.stringify(merged) : ''
  }, [areaPreview, variant, serverVariants])
  const previewSlots = useMemo(
    () => (previewSlotsKey
      ? JSON.parse(previewSlotsKey) as PropSlotValues : undefined),
    [previewSlotsKey])
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

  /** The picture's own provenance as ONE tooltip text, hung on the IMAGE and
   *  on the caption under it. Written out it is a paragraph, and a paragraph
   *  of prompt is what pushed everything below it off the screen — over the
   *  picture it costs nothing and is where one looks for it. */
  const imageTip = shownImage
    ? (shownImage.prompt
      ? `${t('Prompt')}: ${shownImage.prompt}${shownImage.negative
        ? `\n${t('Negative prompt')}: ${shownImage.negative}` : ''}`
      : t('No generation record for this image.'))
    : ''

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
  const mountNow = draftValue<string>(buf, GENERAL_TARGET, 'mount',
    prop.mount || '')
  // The LLM's guess is only still open while nothing has been DECIDED about
  // the field in this draft: queueing a mount confirms it on Save, even when
  // it is the value that was already there, so the hint goes the moment the
  // buffer carries the key — not only when the value differs.
  const mountSuggested = !!prop.mount_suggested
    && draftValue<string | undefined>(buf, GENERAL_TARGET, 'mount',
      undefined) === undefined

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
    if (saving || conflicts.length || !revisionReady) return false
    const issues = actionEditorIssues(draftValue(buf, GENERAL_TARGET, 'actions', prop.actions || []), catalog)
    if (issues.length) { setSaveIssues(issues); return false }
    setSaveError('')
    setSaveIssues([])
    const body = toBulkFieldBody(buf, baseRevision.current)
    setSaving(true)
    setPlacing(null)
    setAccessPlacing(null)
    setDrawKind('')
    cancelWaterPlacement(null)
    try {
      const d = await apiPost<{ variants?: PropVariant[]; revision: string }>(
        `/world/props/${enc}/bulk`, body)
      baseRevision.current = d.revision
      setBuf(emptyFields())
      if (d?.variants) setServerVariants(d.variants)
      // The prop record (name, category, the library row) is the container's —
      // it reloads the list, which is also what the marker/mesh counts hang on.
      await onChanged()
      toast(t('Saved'))
      return true
    } catch (e) {
      const message = (e as Error).message
      setSaveError(message)
      const detail = e instanceof ApiError && e.detail && typeof e.detail === 'object'
        ? e.detail as { issues?: PropActionIssue[] } : null
      setSaveIssues(Array.isArray(detail?.issues) ? detail.issues : [])
      toast(t('Error') + ': ' + message, 'error')
      if ((e as ApiError).status === 409) {
        await onChanged()
        await loadVariants()
      }
      return false
    } finally {
      setSaving(false)
    }
  }, [buf, enc, onChanged, t, toast, saving, conflicts.length,
    revisionReady, loadVariants, cancelWaterPlacement, catalog, prop.actions])

  /** Discard only author fields; already changed files remain on the server. */
  const discard = useCallback(() => {
    setBuf(emptyFields())
    setDiscardArmed(false)
    setSaveError('')
    setSaveIssues([])
    setDimDraft({})
    dimGesture.current = null
    setDescDraft(null)
  }, [])

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
    const target = await prepareVariantOperation(shownVariant?.uid || '', t('Upload source image'))
    if (!target) return
    try {
      const fd = new FormData()
      fd.append('file', file)
      const res = await fetch(
        `/world/props/${enc}/variants/${target.index}/source${view === 'front' ? '' : `?view=${view}`}`,
        { method: 'POST', body: fd, credentials: 'same-origin' })
      const body = await res.json().catch(() => null)
      if (!res.ok) throw new Error(body?.detail?.toString?.() || `HTTP ${res.status}`)
      await meshesChanged()
      toast(t('Saved'))
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [enc, shownVariant?.uid, meshesChanged, t, toast, prepareVariantOperation])

  // Drop ONE extra view's picture. The front is not deletable here — it is
  // the variant's source image, and a variant without one cannot be meshed
  // at all; an extra view is an addition and goes back to "none".
  const deleteView = useCallback(async (view: PropView) => {
    const target = await prepareVariantOperation(shownVariant?.uid || '', t('Delete view image'))
    if (!target) return
    try {
      await apiDelete(`/world/props/${enc}/variants/${target.index}/source?view=${view}`)
      await meshesChanged()
      toast(t('Deleted'))
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [enc, shownVariant?.uid, meshesChanged, t, toast, prepareVariantOperation])
  // Which tile's × is armed (the two-click delete of this admin, never a
  // window.confirm), and which view the shared file input is filling.
  const [armedView, setArmedView] = useState<PropView | null>(null)
  const viewUploadRef = useRef<HTMLInputElement>(null)
  const [uploadView, setUploadView] = useState<PropView>('back')
  // An armed × belongs to the tile it was clicked on — switching the variant
  // (or the prop) shows OTHER pictures, and a still-armed button would delete
  // one of those on a single click.
  useEffect(() => { setArmedView(null) }, [prop.id, variant])


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
  const dimGesture = useRef<DimensionGesture | null>(null)
  const [descDraft, setDescDraft] = useState<string | null>(null)
  /** Is the description expanded to writing size? Readable at rest, a real
   *  editor while it is written in. */
  const [descOpen, setDescOpen] = useState(false)
  // Another variant is another set of numbers: a draft of the one before it
  // would show its size in the new one's fields.
  useEffect(() => {
    setDimDraft({})
    dimGesture.current = null
    setDescDraft(null)
    setDescOpen(false)
  }, [prop.id, shownVariant?.uid])

  // One edited edge, three answers — the whole row is rewritten, so no field
  // of it keeps a draft (a stale one would show a number the server never
  // got). The proportions come from the mesh ON SCREEN when it is loaded.
  const editDim = (key: DimKey, raw: string) => {
    setDimDraft((draft) => ({ ...draft, [key]: raw }))
    if (!shownVariant) return
    const next = editDimensionGesture(dimGesture.current, shownVariant.uid,
      shownVariant.dims, key, raw, shownBbox, variantRotation)
    dimGesture.current = next.gesture
    queueVariant(variant, { dims: next.dims })
  }
  const commitDim = useCallback((key: DimKey, raw: string) => {
    setDimDraft({})
    const previous = dimGesture.current
    dimGesture.current = null
    if (!shownVariant) return
    const next = editDimensionGesture(previous, shownVariant.uid,
      shownVariant.dims, key, raw, shownBbox, variantRotation)
    if ((previous?.uid === shownVariant.uid && previous.key === key)
      || next.dims !== shownVariant.dims) queueVariant(variant, { dims: next.dims })
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
    queueVariant(variant, { face_targets: next || {
      target_faces_high: shownVariant.target_faces_high ?? null,
      target_faces_low: shownVariant.target_faces_low ?? null,
    } })
  }, [shownVariant, queueVariant, variant])

  // THE FIX IS THE FILE'S (v2 E1): the route takes the variant, and what comes
  // back has to reach the viewers below — the preview here, the areas viewer
  // and the strip's dims all turn with it, so this reloads the meshes rather
  // than the record alone.
  const rotate = useCallback(async (axis: 'x' | 'y' | 'z') => {
    const target = await prepareVariantOperation(shownVariant?.uid || '', t('Orientation fix'))
    if (!target) return
    try {
      const fresh = await apiGet<PropAreasInfo>(`/world/props/${enc}/areas?variant=${target.index}`)
      const cur = fresh.rotation || {}
      await apiPost(`/world/props/${enc}/rotation?variant=${target.index}`, {
        x: cur.x || 0, y: cur.y || 0, z: cur.z || 0,
        [axis]: ((cur[axis] || 0) + 90) % 360,
      })
      await meshesChanged()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [enc, shownVariant?.uid, meshesChanged, t, toast, prepareVariantOperation])

  const setRotationAxis = useCallback(async (axis: 'x' | 'y' | 'z', raw: string) => {
    const n = parseFloat(raw)
    const v = Number.isFinite(n) ? ((n % 360) + 360) % 360 : 0
    if (v === (variantRotation?.[axis] || 0)) return
    const target = await prepareVariantOperation(shownVariant?.uid || '', t('Orientation fix'))
    if (!target) return
    try {
      const fresh = await apiGet<PropAreasInfo>(`/world/props/${enc}/areas?variant=${target.index}`)
      const cur = fresh.rotation || {}
      await apiPost(`/world/props/${enc}/rotation?variant=${target.index}`, {
        x: cur.x || 0, y: cur.y || 0, z: cur.z || 0, [axis]: v,
      })
      await meshesChanged()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [variantRotation, enc, shownVariant?.uid, meshesChanged, t, toast, prepareVariantOperation])

  // The walkable surface of the SHOWN variant's mesh. Blender bakes it in the
  // background, so the answer is only "queued" — but the record is reloaded
  // right away all the same: the bake INVALIDATES what the status line shows
  // (a valid lattice becomes the one being replaced), and every other action
  // on this panel refreshes the record it edited. Without it the line kept
  // saying "baked 33×33" until something else happened to reload the prop.
  const bakeSurface = useCallback(async () => {
    const target = await prepareVariantOperation(shownVariant?.uid || '', t('Bake surface'))
    if (!target) return
    try {
      await apiPost(`/world/props/${enc}/surface`, { variant: target.index })
      toast(t('Baking the surface — this runs in the background.'))
      await onChanged()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [enc, shownVariant?.uid, onChanged, t, toast, prepareVariantOperation])

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
    const target = await prepareVariantOperation(shownVariant?.uid || '', t('Remove surface'))
    if (!target) return
    setRemoveArmed(false)
    try {
      const d = await apiDelete<{ deleted?: boolean }>(
        `/world/props/${enc}/surface?variant=${target.index}`)
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
  }, [enc, shownVariant?.uid, meshesChanged, t, toast, prepareVariantOperation])

  // Object-local PLACES (A4, plan-posen-plaetze.md § 4) — same vocabulary as
  // room markers, but the frame is the MESH's own bounding box: `at` =
  // [u, v, w] fractions, `facing` = degrees. The fractions may leave the box
  // by half a box per axis (seats sit ON the hull, see
  // props.sanitize_markers).
  //
  // A marker names a PLACE TYPE (`group`, a key of the pose catalog), never
  // a clip — which pose is played there is the character's business, and the
  // ◀ ▶ cycler below only decides which one the preview figures hold.
  //
  // They belong to the VARIANT since 2026-08-25: a fraction of one mesh's box
  // means nothing on another bake, so the editor below always edits the chip
  // the viewer has open, and the write goes to that variant's route.
  const poseCatalog: PoseCatalog = useMemo(() => ({
    status: catalog.status === 'error' ? 'missing' : catalog.status,
    entries: catalog.poses, groups: catalog.groups,
  }), [catalog])
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

  const light = shownVariant?.light ?? null
  const lightPreset = !light ? '' : LIGHT_PRESETS.find(({ light: preset }) =>
    (Object.keys(preset) as Array<keyof typeof preset>).every((key) => preset[key] === light[key]))?.name || 'Custom'
  const editLight = (patch: Partial<PropLight>) => {
    if (light) queueVariant(variant, { light: { ...light, ...patch } })
  }

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
    // Centimetre grain (2026-09-10): a marker is placed by eye and read back
    // in metres with two decimals, so a finer fraction only hides noise.
    at[axis] = Math.round(v * 100) / 100
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
    if (saving || previewFile) return
    saveMarkers(markers.filter((_, index) => index !== i))
    setSelectedMarker(0); setPlacing(null); setAccessPlacing(null)
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
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      setPlacing(null); setAccessPlacing(null); setDrawKind(''); cancelWaterPlacement(null)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [cancelWaterPlacement])
  // The hit lands on the place the editor is about: 'add' appends one and
  // selects it, an armed index is the selected place (✥ arms exactly that
  // one). Reading `placing` instead of updating through it keeps the write
  // out of a state updater, which React may run more than once.
  const onPickPoint = useCallback((at: [number, number, number]) => {
    if (saving || previewFile) return
    if (placing === 'light') {
      if (light) queueVariant(variant, { light: { ...light, at } })
    } else if (placing === 'add') {
      saveMarkers([...markers, { id: newId(), group: firstGroup, at }])
      setSelectedMarker(markers.length)
    } else if (typeof placing === 'number' && markers[placing]) {
      saveMarkers(markers.map((m, idx) => (idx === placing ? { ...m, at } : m)))
    }
    setPlacing(null)
  }, [placing, markers, firstGroup, saveMarkers, light, queueVariant, variant, saving, previewFile])
  const onPickAccess = (point: Pick<AccessPoint, 'x' | 'z'>) => {
    if (!accessPlacing || saving || previewFile) return
    const index = markers.findIndex(marker => marker.id === accessPlacing.markerId)
    const marker = markers[index]
    if (!marker) return
    patchMarker(index, { access: { ...marker.access,
      [accessPlacing.role]: { yaw: marker.access?.[accessPlacing.role]?.yaw ?? marker.facing ?? 0, ...point } } })
    setAccessPlacing(null)
  }
  const actions = draftValue(buf, GENERAL_TARGET, 'actions', prop.actions || [])
  const accessDocument = useMemo(() => propActionCheckDocument(prop, variants, buf), [prop, variants, buf])
  const [accessPreviewResult, setAccessPreviewResult] = useState<{ document: typeof accessDocument; points: PropAccessPreviews; bindings: Record<string, VariantBinding[]> } | null>(null)
  const accessPreviews = accessPreviewResult?.document === accessDocument ? accessPreviewResult.points : {}
  const derivedBindings = accessPreviewResult?.document === accessDocument ? accessPreviewResult.bindings : {}
  useEffect(() => {
    let current = true
    const timer = setTimeout(() => {
      void apiPost<{ access_previews: PropAccessPreviews; derived_bindings: Record<string, VariantBinding[]> }>(`/world/props/${enc}/validate`, { document: accessDocument })
        .then(result => { if (current) setAccessPreviewResult({ document: accessDocument, points: result.access_previews || {}, bindings: result.derived_bindings || {} }) })
        .catch(() => { if (current) setAccessPreviewResult(null) })
    }, 250)
    return () => { current = false; clearTimeout(timer) }
  }, [accessDocument, enc])
  const authoringIssues = useMemo(() => actionEditorIssues(actions, catalog), [actions, catalog])
  useEffect(() => {
    if (!actions.some(action => action.id === selectedActionId)) setSelectedActionId(actions[0]?.id || '')
  }, [actions, selectedActionId])
  const openImageGeneration = async (view: PropView) => {
    const target = await prepareVariantOperation(shownVariant?.uid || '', t('New image'))
    if (!target) return
    try {
      const [author, refs] = await Promise.all([
        apiGet<{ prop: PropFull }>(`/world/props/${enc}`),
        apiGet<{ variants: PropVariant[]; revision: string; generating_variants: number[] }>(
          `/world/props/${enc}/variants`),
      ])
      const current = refs.variants.find((entry) => entry.uid === target.uid)
      if (!current) throw new Error(t("The target variant was removed. The operation was not performed."))
      if (refs.generating_variants.includes(current.index)) throw new Error(t('This variant is generating right now.'))
      if (author.prop.revision !== refs.revision) throw new Error(t('Prop changed on the server; reopen the generation dialog.'))
      onRegenerateImage(current, view, view === 'front' ? current.image : current.images?.[view],
        propGenerationSubject(author.prop, current),
        refs.variants.filter((entry) => entry.has_source), author.prop)
    } catch (error) { toast(t((error as Error).message), 'error') }
  }
  const openMeshGeneration = async () => {
    const target = await prepareVariantOperation(shownVariant?.uid || '', t('3D from this image'))
    if (target) onRegenerateMesh(target,
      (['back', 'left', 'right'] as PropView[]).filter((view) => !!target.images?.[view]))
  }
  const openRegeneration = async (append = false) => {
    const uid = shownVariant?.uid
    // Choosing a NEW slot waits for the whole prop; a named variant only for itself.
    if ((append ? pending : variantBusy)
      || !await beforeImmediate(t(append ? '+ Generate new variant' : 'Regenerate'))) return
    try {
      const current = await apiGet<{ variants: PropVariant[]; max: number; generating_variants: number[] }>(
        `/world/props/${enc}/variants`)
      const target = current.variants.find(entry => entry.uid === uid)
      if (!append && !target) throw new Error(t('The selected variant was removed.'))
      if (!append && current.generating_variants.includes(target!.index)) {
        throw new Error(t('This variant is generating right now.'))
      }
      const plan: PropGenerationTarget = append
        ? propGenerationTarget(current.variants, current.max, current.generating_variants)
        : { kind: 'existing', uid: target!.uid, index: target!.index }
      onRegenerate(plan, propGenerationAuthor(current.variants, plan))
    } catch (error) { toast(t((error as Error).message), 'error') }
  }
  const [generationRepairs, setGenerationRepairs] = useState<PropGenerationRepair[]>([])
  const [repairLoading, setRepairLoading] = useState(false)
  const [repairLoadError, setRepairLoadError] = useState('')
  const [repairError, setRepairError] = useState('')
  const [repairRefresh, setRepairRefresh] = useState(0)
  const [repairBusy, setRepairBusy] = useState(false)
  const repairAction = useRef(false)
  const [repairRequest, setRepairRequest] = useState<PropRepairConfirmation | null>(null)
  const refreshGenerationRepairs = () => setRepairRefresh((value) => value + 1)
  useEffect(() => {
    let cancelled = false
    setRepairLoading(true)
    void apiGet<{ repairs: PropGenerationRepair[] }>(`/world/props/${enc}/generation-repairs`)
      .then((answer) => {
        if (!cancelled) { setGenerationRepairs(answer.repairs); setRepairLoadError('') }
      }, (error: Error) => {
        if (!cancelled) setRepairLoadError(error.message)
      }).finally(() => { if (!cancelled) setRepairLoading(false) })
    return () => { cancelled = true }
  }, [enc, reloadKey, pending, repairRefresh])
  const readRepairSnapshot = async (): Promise<PropRepairSnapshot> => {
    const [current, retained] = await Promise.all([
      apiGet<Omit<PropRepairSnapshot, 'repairs'>>(`/world/props/${enc}/variants`),
      apiGet<{ repairs: PropGenerationRepair[] }>(`/world/props/${enc}/generation-repairs`),
    ])
    return { ...current, repairs: retained.repairs }
  }
  const openGenerationRepair = async (opId: string) => {
    if (repairAction.current || !shownVariant) return
    const uid = shownVariant.uid
    repairAction.current = true
    setRepairBusy(true)
    setRepairError('')
    try {
      const next = await resolvePropRepairAfterBarrier(opId, uid,
        () => beforeImmediate(t("Assign saved generation to a variant")), readRepairSnapshot)
      if (next) setRepairRequest(next)
    } catch (error) { setRepairError((error as Error).message) }
    finally { repairAction.current = false; setRepairBusy(false) }
  }
  const dismissGenerationRepair = async (opId: string) => {
    if (repairAction.current) return
    repairAction.current = true
    setRepairBusy(true); setRepairError('')
    try {
      await apiPost(`/world/props/${enc}/generation-repairs/${encodeURIComponent(opId)}/dismiss`, {})
      setGenerationRepairs(entries => entries.filter(entry => entry.op_id !== opId))
      refreshGenerationRepairs()
    } catch (error) { setRepairError((error as Error).message) }
    finally { repairAction.current = false; setRepairBusy(false) }
  }
  const cancelGenerationRepair = () => {
    if (!repairAction.current) { setRepairRequest(null); setRepairError('') }
  }
  const confirmGenerationRepair = async () => {
    const request = repairRequest
    if (!request || repairAction.current) return
    repairAction.current = true
    setRepairBusy(true)
    setRepairError('')
    // Hide this decision while the shared save/cancel barrier is active.
    setRepairRequest(null)
    try {
      const next = await resolvePropRepairAfterBarrier(request.repair.op_id, request.target.uid,
        () => beforeImmediate(t("Publish saved result")), readRepairSnapshot)
      if (!next) return
      if (next.target.index !== request.target.index
          || next.target.model_file !== request.target.model_file
          || next.body.base_revision !== request.body.base_revision) {
        setRepairRequest(next)
        setRepairError(t("Target variant, active mesh or document changed. Confirm the current assignment again."))
        return
      }
      const answer = await apiPost<{ status: string }>(
        `/world/props/${enc}/variants/${next.target.index}/generate`, next.body)
      if (answer.status !== 'generating') {
        setRepairRequest(next)
        setRepairError(t("The target variant is already busy. The saved work is retained."))
        return
      }
      refreshGenerationRepairs()
      onGenerating()
      void meshesChanged().catch((error: Error) => toast(error.message, 'error'))
      toast(t(next.repair.status === 'waiting_provider'
        ? "The existing provider job is retrieved and then published. No new render job."
        : "The saved result is published without new generation."))
    } catch (error) {
      setRepairRequest(request)
      setRepairError((error as Error).message)
      refreshGenerationRepairs()
    } finally { repairAction.current = false; setRepairBusy(false) }
  }
  const navigate = (next: PropWorkspaceArea) => {
    onAreaChange(next)
    setMobilePane('editor')
    setPlacing(null)
    setAccessPlacing(null)
    setDrawKind('')
    cancelWaterPlacement(null)
    document.getElementById(`prop-tab-${next}`)?.focus()
  }
  return {
    t, nameNow, queueGeneral, categoryNow, tagsNow, swayNow, mountSuggested,
    mountNow, prop, markers, selIdx, setSelectedMarker, placing, setPlacing,
    groups, addMarker, firstGroup, shownHasMesh, previewFile, drawKind,
    armPlacing, selMarker, patchMarker, groupOptions, removeMarker, shownDims,
    setMarkerAt, selCapacity, selPoses, setPreview, selPoseIdx, variantBusy,
    pending, shownImage, srcOk, enc, variant, reloadKey, setSrcOk, enlarge,
    imageTip, variants, openImageGeneration, shownVariant,
    sourceUploadRef, uploadSource, onRefresh, setUploadView, viewUploadRef,
    armedView, setArmedView, deleteView, uploadView, openMeshGeneration,
    dimDraft, editDim, commitDim, commitSink, descOpen, descDraft,
    setDescOpen, setDescDraft, commitDesc, variantAreas, rotate,
    variantRotation, setRotationAxis, areasFailed, surfaceLabel, bakeSurface,
    shownSurface, removeArmed, removeSurface, setRemoveArmed, showStoredFile,
    meshesChanged, commitFaces, backendFaces, onGenerating, lightPreset,
    queueVariant, light, editLight, waterController, setDrawKind, viewerRef,
    serverVariants, variantMax, areaTools, loadVariants, areaFrontal,
    setAreaView, areasOnView, areaOutlines, previewSlots, onPolygonFaces,
    setShownBbox, poseCatalog, previewPose, shownBbox, scaleFigure, onPickPoint,
    setScaleFigure, dirtyCount, saving, save, discard, discardArmed,
    setDiscardArmed, setVariant, generatingVariants, worldSeasons,
    currentSeason, onDelete, armedDelete, openRegeneration, buf, baseRevision,
    actions, conflicts, saveError, resolveConflict, beforeImmediate,
    operation, finishOperation,
    onVariantDeleted,
    area, navigate, mobilePane, setMobilePane,
    revisionReady, variantLoadError,
    prepareVariantOperation,
    selectedActionId, setSelectedActionId, saveIssues, derivedBindings, accessPreviews, accessPlacing, armAccess, onPickAccess,
    catalog, reloadActionCatalog, authoringIssues,
    generationRepairs, repairLoading, repairLoadError, repairError, repairBusy, repairRequest,
    refreshGenerationRepairs, openGenerationRepair, cancelGenerationRepair, confirmGenerationRepair, dismissGenerationRepair,
  }
}

export type PropWorkspace = ReturnType<typeof usePropWorkspace>
export type PropDetailProps = Parameters<typeof usePropWorkspace>[0]
