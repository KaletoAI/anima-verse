/**
 * PropVariantStrip — the prop's MODEL VARIANTS as one row of chips.
 *
 * A prop carries several meshes of the same object (E2.3): a scattered wood
 * was the same tree twenty times over, so the prop keeps an ORDERED list of
 * variants, each a mesh gallery of its own. The FIRST ACTIVE one is the
 * PRIMARY variant — what `/assets/props/{id}/model` serves without a
 * `variant` parameter and therefore what every consumer that knows nothing
 * about variants keeps getting.
 *
 * The strip is the selector for everything below it: clicking a chip decides
 * which variant the 3D preview and the mesh gallery (`PropModelPanel`) show
 * and act on. It owns the four variant verbs (add, toggle, delete, select);
 * the LIST itself is loaded by `PropDetail`, because the viewer up there needs
 * the same records to know which mesh URL to show.
 *
 * The active cap comes from the server (`image_generation.prop_variant_max`),
 * so "add" is greyed with a reason instead of letting the POST come back 409.
 *
 * SEASONS (E2c): a variant may be tagged with the seasons it depicts — one row
 * of toggle chips per variant, offered from the world's own season list, never
 * free text. Untagged (the default) means every season. A variant that is
 * tagged for another season keeps its meshes but renders nowhere until that
 * season comes round, which the chip row says in as many words. A world
 * without seasons gets no chips at all: the tags would be inert.
 *
 * THE VARIANT OWNS WHAT IT LOOKS LIKE (2026-08-25, user decision). Size,
 * generation subject, ground offset and markers used to sit on the PROP with
 * an optional per-variant override; they live on the variant now and nowhere
 * else, so this strip is where a prop is actually authored. Each chip carries:
 *
 *   - W / D / H in metres (mandatory — there is nothing left to inherit),
 *   - the subject its product shot is rendered from,
 *   - how deep it stands in the ground,
 *   - the season chips,
 *   - how many object-local markers it has (the editor itself is below the
 *     strip, on the SELECTED chip: it needs the 3D viewer beside it),
 *   - and what it should COST in triangles, close up and at distance (v2 E5):
 *     two budgets that are the DEFAULT of every run naming none — the
 *     generate dialog, the automatic improvement, the distance mesh.
 *
 * THE THREE DIMS MOVE TOGETHER (2026-08-24, user decision): editing one of
 * them pulls the other two along the variant's proportions — and all three go
 * out in ONE call. The reason is the renderer: `place()` scales a prop
 * UNIFORMLY to `max(W, D, H)`, so the trio has one degree of freedom (how big)
 * plus a fixed aspect (what shape). Editing one number alone would resize
 * nothing and only make the other two lie about the mesh. An empty or
 * unusable field is therefore not a size at all: it snaps back to what is
 * stored, because a variant without a size is not a state that may exist.
 *
 * THE FIELDS ARE DRAFTED, THE VERBS ARE IMMEDIATE (2026-08-25). Size, subject,
 * sink, seasons and markers go into the detail's change buffer
 * (`pendingFields`) and reach the server when Save is pressed — which is why
 * this strip posts none of them any more; it hands them up. Add, on/off and
 * delete stay immediate: they change the store indices, the mesh signature and
 * what a running generation addresses, and every file action beside them (mesh
 * gallery, source image) speaks to the server about a variant that has to
 * exist there. The `variants` this strip renders are the DRAFT list, so a
 * typed number is on screen and in the 3D preview long before it is stored.
 */
import { useCallback, useEffect, useState } from 'react'
import { faceFor } from '../../components/faceBudget'
import { DEFAULT_MODEL_TIER } from '../../components/ModelGallery'
import { useI18n } from '../../i18n/I18nProvider'
import { apiDelete, apiPost } from '../../lib/api'
import { SliderInput } from '../../components/SliderInput'
import { useToast } from '../../lib/Toast'
import { DIM_KEYS, DIM_MAX_M, DIM_MIN_M, orientedDims, variantRedistribute,
  type DimKey } from './dims'
import type { PropDims, PropVariant } from './propTypes'

/** The three overridable dims in the prop form's own order. `label` is the
 *  short caption on the input, `title` the sentence behind it. */
const DIM_FIELDS: Array<{ key: DimKey; label: string; title: string }> = [
  { key: 'width_m', label: 'W', title: 'Width (m)' },
  { key: 'depth_m', label: 'D', title: 'Depth (m)' },
  { key: 'height_m', label: 'H', title: 'Height (m)' },
]

/** The two face budgets of a variant (v2 E5), in the order they are used: the
 *  close-up mesh first, the distance mesh second. `placeholder` says what
 *  happens when the field is left empty — the picked backend's own face count
 *  for the full mesh, a quarter of it for the distance mesh (the dialog's
 *  `faceFor` rule, and the number the reduction lands near). */
const FACE_FIELDS: Array<{
  key: 'high' | 'low'
  label: string
  title: string
  placeholder: (backendFaces: number, t: (s: string) => string) => string
}> = [
  { key: 'high', label: '△ High', title: 'Triangles this variant’s close-up mesh should cost. Empty = whatever the picked backend uses by default. The generate dialog opens on this number and the automatic improvement re-meshes to it; above the backend’s own ceiling the run is clamped and the gallery row says so.',
    // The dialog's own rule, imported rather than restated: the number the
    // admin sees here and the number a run starts on must be one function.
    placeholder: (faces, t) => (faces
      ? faceFor(DEFAULT_MODEL_TIER, faces) : t('backend default')) },
  { key: 'low', label: '△ Low', title: 'Triangles this variant’s DISTANCE mesh should cost. Empty = the configured reduction fraction decides. Given, the server reduces to exactly this budget — it divides it by the full mesh’s own triangle count to get the Decimate ratio.',
    placeholder: (faces, t) => (faces
      ? faceFor('low', faces) : t('LOD ratio')) },
]

/** The window the server accepts a budget in (`props.FACE_TARGET_MIN/MAX`) —
 *  the input only has to agree with it. */
const FACE_TARGET_MIN = 100
const FACE_TARGET_MAX = 2000000

/** One chip's width in pixels — wide enough for the three size fields, which
 *  are the widest row in it. Fixed on purpose (see the chip's own comment):
 *  the strip may only ever grow DOWNWARDS, never re-flow sideways. */
const CHIP_W = 290

/** Clamp of the ground offset, the stored limit itself
 *  (`props.GROUND_OFFSET_MIN/MAX`). The field is TYPED, not swept (user
 *  2026-08-25), so there is no dial to fit to the object any more — the value
 *  is judged against the 1.70 m figure gauge below the strip, and the clamp
 *  only has to agree with what the server accepts. */
const SINK_LIMIT_M = 5

/** Rows of the per-variant description field: readable at rest, a real
 *  editor while it is written in. */
// 5/12 (was 3/8, before that 1/4): the user twice asked for more room —
// prompts for a variant are whole sentences, not tags (2026-08-24).
const DESC_ROWS_REST = 5
const DESC_ROWS_OPEN = 12

export function PropVariantStrip({ propId, variants, max, selected, onSelect,
  onChanged, onEditVariant, onDeleted, generating = [], worldSeasons = [],
  currentSeason = '', shownBbox = null, rotation, backendFaces = 0 }: {
  propId: string
  /** Every variant, active or not, in order — the DRAFT list (PropDetail's
   *  load with the change buffer laid on top), so a field edit shows here and
   *  in the preview at once. */
  variants: PropVariant[]
  /** Ceiling on ACTIVE variants — the "add" action's gate. */
  max: number
  /** Index of the variant the detail currently works on. */
  selected: number
  /** Select a variant — the caller also drops its file preview. */
  onSelect: (index: number) => void
  /** Reload the variant list and the prop record (a variant changes both the
   *  strip and the prop's mesh signature). */
  onChanged: () => Promise<unknown>
  /** Put one variant's field edit into the detail's change buffer — nothing is
   *  written until Save. `patch` is a fragment of the batch body: `{dims}`,
   *  `{description}`, `{ground_offset_m}` or `{seasons}`. */
  onEditVariant: (index: number, patch: Record<string, unknown>) => void
  /** A variant was really deleted on the server (STORE index). The detail
   *  drops its pending fields and renumbers the ones behind it, exactly as the
   *  server renumbered the list. */
  onDeleted: (index: number) => void
  /** STORE indices with a generation in flight. Matched against a chip's own
   *  `index`, NOT against its position in this list: a switched-off variant
   *  keeps its index, so the two part company as soon as one is toggled off.
   *  Only those chips lose their toggle and their delete — the job is about to
   *  write into that slot, and a delete renumbers everything behind it.
   *  Adding a slot is never blocked by a run: it appends at the end. */
  generating?: number[]
  /** The world's season NAMES (`game_seasons`) — the only values a chip may
   *  set. Empty = a world without seasons, and then no chips are drawn. */
  worldSeasons?: string[]
  /** The season the world is in right now, for the "renders now" hint. */
  currentSeason?: string
  /** RAW bounding box of the mesh the 3D preview currently has open — i.e. of
   *  the SELECTED variant, measured on load (`PropDetail.shownBbox`). The one
   *  true statement about that variant's proportions the client holds; `null`
   *  while nothing is loaded, and then the stored dims stand in. */
  shownBbox?: [number, number, number] | null
  /** The orientation fix of the SELECTED variant's model file, applied to
   *  `shownBbox` before it is read as width/height/depth — the same turn
   *  every renderer makes. The fix belongs to the FILE (v2 E1), so it is only
   *  ever the box on screen that it is applied to. */
  rotation?: { x?: number; y?: number; z?: number }
  /** Face count the picked mesh backend would use of its own accord — the
   *  PLACEHOLDER of the two budget fields (v2 E5). 0 = unknown, and the
   *  placeholder says "backend default" instead of a number. */
  backendFaces?: number
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const enc = encodeURIComponent(propId)
  // Two-step delete like the mesh rows: the first click arms the chip, the
  // second one deletes. Same reason as everywhere in this admin — no
  // window.confirm.
  const [armedDel, setArmedDel] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  // What is being TYPED into a size field, keyed `<store index>:<dim>`. An
  // entry lives only while the field is edited: the commit drops it again and
  // the input falls back to the stored override, so a background reload can
  // never stomp what is under the cursor and no sync effect is needed.
  const [dimDraft, setDimDraft] = useState<Record<string, string>>({})
  useEffect(() => { setDimDraft({}) }, [propId])
  // The same law for the description field, keyed by store index: a draft
  // exists only while the field is edited. `descOpen` is the ONE variant whose
  // field is expanded to writing size — every field is readable at rest, only
  // the one under the cursor gets the room of a real editor.
  const [descDraft, setDescDraft] = useState<Record<number, string>>({})
  const [descOpen, setDescOpen] = useState<number | null>(null)
  useEffect(() => { setDescDraft({}); setDescOpen(null) }, [propId])
  // …and for the two face budgets, keyed `<store index>:<high|low>`. Same
  // law: a draft exists only while the field is edited, so an empty field
  // under the cursor is not read back as "cleared" until it is committed.
  const [faceDraft, setFaceDraft] = useState<Record<string, string>>({})
  useEffect(() => { setFaceDraft({}) }, [propId])
  // Arming is bound to an INDEX, and a delete renumbers everything behind it —
  // so any change of the list disarms rather than pointing at another variant.
  useEffect(() => { setArmedDel(null) }, [propId, variants.length])

  const activeCount = variants.filter((v) => v.active).length
  const capReached = activeCount >= max

  const run = useCallback(async (fn: () => Promise<unknown>, ok: string) => {
    setBusy(true)
    try {
      await fn()
      await onChanged()
      toast(ok)
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setBusy(false)
    }
  }, [onChanged, t, toast])

  // The new slot carries no mesh — it is filled by the next generation
  // targeted at it, so selecting it right away is what the admin wants to do
  // next. Its FIELDS come from the chip that is open (`from`): a version of an
  // object is authored by editing the one beside it, not by re-typing size,
  // subject, sink and markers.
  const add = useCallback(() => {
    void run(async () => {
      const d = await apiPost<{ index?: number }>(
        `/world/props/${enc}/variants`, { from: selected })
      if (typeof d?.index === 'number') onSelect(d.index)
    }, t('Variant added'))
  }, [enc, onSelect, run, selected, t])

  const toggle = useCallback((v: PropVariant) => {
    void run(
      () => apiPost(`/world/props/${enc}/variants/${v.index}/active`, { active: !v.active }),
      v.active ? t('Variant switched off') : t('Variant switched on'))
  }, [enc, run, t])

  // Toggling ONE season on a variant: the chips are a set, and the server
  // stores what it is sent — so the new set is computed here and drafted whole.
  const toggleSeason = useCallback((v: PropVariant, season: string) => {
    const has = v.seasons.some((s) => s.toLowerCase() === season.toLowerCase())
    const next = has
      ? v.seasons.filter((s) => s.toLowerCase() !== season.toLowerCase())
      : [...v.seasons, season]
    onEditVariant(v.index, { seasons: next })
  }, [onEditVariant])

  // WHERE THE PROPORTIONS COME FROM — never the prop's box.
  //
  // The variant the preview has open is MEASURED: `shownBbox` is its raw mesh
  // box, and the prop's orientation fix turns it into [width, height, depth]
  // exactly as the prop form does it. That is the only true statement about
  // THIS mesh the client holds, and it is the one that matters — a sapling's
  // GLB is not a small pine, so redistributing a chip's height along the
  // PROP's aspect would give it the grown tree's footprint.
  //
  // Every other chip has no mesh loaded, and the payload carries no per-variant
  // box (`GET …/variants` sends dims, not geometry). Its stored `dims` are the
  // ratio source instead, and they ARE that variant's declared aspect. Since
  // every renderer sizes a variant by exactly those three numbers, rescaling
  // along them keeps the object the shape it is rendered at — and the first
  // edit is made against the mesh anyway, because the chip you are typing into
  // is normally the one you are looking at.
  const ratiosFor = useCallback((v: PropVariant): Record<DimKey, number> => {
    if (v.index === selected && shownBbox) {
      const [w, h, d] = orientedDims(shownBbox, rotation)
      return { width_m: w, depth_m: d, height_m: h }
    }
    return {
      width_m: v.dims.width_m,
      depth_m: v.dims.depth_m,
      height_m: v.dims.height_m,
    }
  }, [rotation, selected, shownBbox])

  // Commit ONE edited size field of ONE variant — and with it the other two.
  //
  // The trio is a resize of a known mesh, not three free numbers (see the
  // module header), so the edited value drives and the other two follow the
  // variant's proportions. All three travel as ONE `dims` object into the
  // draft, so the preview follows immediately and Save writes one field.
  //
  // An empty or unusable input is not a size at all: the draft is dropped and
  // the field snaps back to what is stored. There is nothing to inherit since
  // 2026-08-25, so "cleared" is not a state a variant may be in — a typing
  // slip costs the edit, never the size.
  const commitDim = useCallback((v: PropVariant, key: DimKey, raw: string) => {
    setDimDraft((d) => {
      const next = { ...d }
      // The whole row is rewritten by this commit, so no field of it keeps a
      // draft — a stale one would show a number the server never got.
      for (const k of DIM_KEYS) delete next[`${v.index}:${k}`]
      return next
    })
    const stored = v.dims as PropDims
    const n = parseFloat(raw)
    if (!Number.isFinite(n) || n <= 0) return
    // A ratio source with a flat edge (a mesh box measuring zero on one axis)
    // redistributes to nothing usable — then the edited field goes out alone
    // rather than a zero, and the other two stay where they are. Clamped and
    // rounded to the same window the helper keeps, so this path cannot store a
    // number the server would round away into a cleared key either.
    const next: PropDims = variantRedistribute(key, n, ratiosFor(v))
      ?? {
        ...stored,
        [key]: Math.round(Math.min(Math.max(n, DIM_MIN_M), DIM_MAX_M) * 1000) / 1000,
      }
    if (DIM_KEYS.every((k) => next[k] === stored[k])) return
    onEditVariant(v.index, { dims: next })
  }, [onEditVariant, ratiosFor])

  // How deep ONE variant stands in the ground. No debounce any more and no
  // local echo: the number goes straight into the draft, the draft IS what the
  // field and the 1.70 m gauge below the strip read, and Save writes it once
  // however often it was corrected. 0 clears the key, which is the normal
  // state.
  const commitSink = useCallback((v: PropVariant, value: number) => {
    const next = Math.round(
      Math.min(Math.max(value, -SINK_LIMIT_M), SINK_LIMIT_M) * 100) / 100
    if (next === v.ground_offset_m) return
    onEditVariant(v.index, { ground_offset_m: next })
  }, [onEditVariant])

  // Commit ONE variant's generation subject. Blank clears the key and a render
  // of this variant composes from the prop's NAME — the same law the server
  // stores by, so the draft says exactly what will be kept.
  const commitDesc = useCallback((v: PropVariant, raw: string) => {
    setDescDraft((d) => {
      const next = { ...d }
      delete next[v.index]
      return next
    })
    const value = raw.trim()
    if (value === (v.description || '')) return
    onEditVariant(v.index, { description: value })
  }, [onEditVariant])

  // Commit ONE of the variant's two face budgets (v2 E5).
  //
  // An EMPTY field is a real statement here, unlike a size: it CLEARS the
  // budget and hands the decision back to the backend default (full) / the
  // configured reduction ratio (low) — which is exactly what the placeholder
  // then shows, so the field never lies about what the next run will use.
  //
  // BOTH budgets travel every time, like the dims trio and for the same
  // reason: the change buffer merges patches field by field, so a second edit
  // sending only its own half would drop the first one. The other half is read
  // off the DRAFT list, which already carries an earlier edit.
  const commitFaces = useCallback(
    (v: PropVariant, which: 'high' | 'low', raw: string) => {
      setFaceDraft((d) => {
        const next = { ...d }
        delete next[`${v.index}:${which}`]
        return next
      })
      const text = raw.trim()
      const n = text ? parseInt(text, 10) : 0
      const value = text && Number.isFinite(n) && n > 0 ? n : null
      const stored = {
        target_faces_high: v.target_faces_high ?? null,
        target_faces_low: v.target_faces_low ?? null,
      }
      const next = {
        ...stored,
        [which === 'high' ? 'target_faces_high' : 'target_faces_low']: value,
      }
      if (next.target_faces_high === stored.target_faces_high
        && next.target_faces_low === stored.target_faces_low) return
      onEditVariant(v.index, { face_targets: next })
    }, [onEditVariant])

  // Deleting a variant is IMMEDIATE (it takes its meshes and its source image
  // with it and renumbers everything behind it) — so the detail is told which
  // index went, and it renumbers its pending fields the same way.
  const remove = useCallback((index: number) => {
    setArmedDel(null)
    void run(async () => {
      await apiDelete(`/world/props/${enc}/variants/${index}`)
      onDeleted(index)
    }, t('Variant deleted'))
  }, [enc, onDeleted, run, t])

  return (
    <>
      <div className="ga-form-section-label">{t('Model variants')}</div>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'flex-start' }}>
        {variants.map((v) => {
          const isSelected = v.index === selected
          const isBusy = generating.includes(v.index)
          // Does this variant render right now? Computed HERE, not read off
          // the record: the chips may hold an unsaved tag, and a badge that
          // still answered from the last load would contradict the chip the
          // admin just lit. Mirrors `props.season_tags_active` on the names
          // this row offers — untagged is always in season, and so is every
          // variant in a world without seasons.
          const inSeason = !v.seasons.length || !currentSeason
            || v.seasons.some(
              (s) => s.toLowerCase() === currentSeason.toLowerCase())
          return (
            <div
              key={v.index}
              style={{
                // FIXED WIDTH, not content width: the description field below
                // grows when it is focused, and a chip whose width depended on
                // its content would re-flow the whole strip while typing. With
                // every chip the same width the line-up never changes — only
                // the focused chip gets taller, in place.
                display: 'flex', flexDirection: 'column', gap: 4, width: CHIP_W,
                padding: '4px 6px', borderRadius: 6,
                border: `1px solid ${isSelected
                  ? 'var(--accent, #58a6ff)' : 'var(--border, #30363d)'}`,
                background: isSelected ? 'rgba(88,166,255,0.10)' : 'transparent',
                // A switched-off variant keeps its meshes but is not rendered
                // anywhere — it reads as muted, not as missing.
                opacity: v.active ? 1 : 0.55,
              }}
            >
              <button
                type="button"
                className="ga-btn ga-btn-sm"
                style={{
                  border: 0, background: 'transparent', padding: '0 2px',
                  textAlign: 'left', fontWeight: isSelected ? 600 : 400,
                }}
                onClick={() => onSelect(v.index)}
                title={v.primary
                  ? t('Primary variant — this is the mesh every consumer gets that does not ask for a variant. Click to show it in the preview and the gallery below.')
                  : t('Show this variant in the preview and the mesh gallery below.')}
              >
                {v.primary ? '★ ' : ''}{t('Variant')} {v.index + 1}
              </button>
              <div style={{ display: 'flex', gap: 3, alignItems: 'center', flexWrap: 'wrap' }}>
                {/* The spinner belongs on the chip the server names, and on no
                    other one — this is the whole point of the store index. */}
                {isBusy ? (
                  <span className="ga-source"
                    title={t('A generation is running for this variant — its image or its mesh is being written right now.')}>
                    {t('generating…')}
                  </span>
                ) : null}
                {v.has_model ? (
                  v.tiers.map((tier) => (
                    <span key={tier} className="ga-tag ga-tag-tier">{tier}</span>
                  ))
                ) : (
                  <span className="ga-tag ga-tag-missing">{t('no mesh')}</span>
                )}
                {/* The counterpart of the list badge: the row says HOW MANY
                    variants lack their product shot, here stands which one. */}
                {v.has_source ? null : (
                  <span className="ga-tag ga-tag-missing"
                    title={t('This variant has no source image — it cannot be re-meshed until one is rendered or uploaded.')}>
                    {t('no image')}
                  </span>
                )}
              </div>
              {/* The variant's size (2026-08-25: its own, not an override —
                  the three numbers every renderer scales this mesh by). */}
              <div style={{ display: 'flex', gap: 3, alignItems: 'center',
                flexWrap: 'wrap' }}>
                {DIM_FIELDS.map((f) => {
                  const draftKey = `${v.index}:${f.key}`
                  const shown = dimDraft[draftKey] ?? String(v.dims[f.key])
                  return (
                    <label
                      key={f.key}
                      style={{ display: 'flex', alignItems: 'center', gap: 2 }}
                      title={`${t(f.title)} — ${t('the real extent of THIS variant’s mesh after the orientation fix.')} ${t('Edit one of the three and the other two follow this variant’s proportions — a prop is always scaled uniformly, so the trio says how big it is, its ratios say what shape.')}`}
                    >
                      <span className="ga-hint">{t(f.label)}</span>
                      <input
                        className="ga-input"
                        type="number"
                        min={0.01}
                        max={100}
                        step={0.05}
                        style={{ width: 62, padding: '1px 3px' }}
                        disabled={busy}
                        value={shown}
                        onChange={(e) => {
                          const value = e.target.value
                          setDimDraft((d) => ({ ...d, [draftKey]: value }))
                        }}
                        onBlur={(e) => commitDim(v, f.key, e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') e.currentTarget.blur()
                        }}
                      />
                    </label>
                  )
                })}
              </div>
              {v.dims_estimated ? (
                <span className="ga-hint" style={{ fontSize: '0.8em' }}>
                  {t('Estimated — refined automatically when the model arrives.')}
                </span>
              ) : null}
              {/* WHAT THIS VERSION COSTS (v2 E5). Two budgets, because a prop
                  is rendered at two distances: the close-up mesh and the one
                  the client swaps in at range. They are the DEFAULT of every
                  run that names none — the generate dialog opens on them, the
                  automatic improvement inherits them, and the CPU distance
                  mesh turns the low one into its reduction ratio. Empty = no
                  statement, and the placeholder shows what would happen then.
                  A budget belongs to the VARIANT and not to the run: a sapling
                  is cheaper than the grown tree beside it, whichever dialog
                  the mesh was last made from. */}
              <div style={{ display: 'flex', gap: 3, alignItems: 'center',
                flexWrap: 'wrap' }}>
                {FACE_FIELDS.map((f) => {
                  const draftKey = `${v.index}:${f.key}`
                  const stored = f.key === 'high'
                    ? v.target_faces_high : v.target_faces_low
                  const shown = faceDraft[draftKey]
                    ?? (stored ? String(stored) : '')
                  return (
                    <label
                      key={f.key}
                      style={{ display: 'flex', alignItems: 'center', gap: 2 }}
                      title={t(f.title)}
                    >
                      <span className="ga-hint">{t(f.label)}</span>
                      <input
                        className="ga-input"
                        type="number"
                        min={FACE_TARGET_MIN}
                        max={FACE_TARGET_MAX}
                        step={500}
                        style={{ width: 84, padding: '1px 3px' }}
                        disabled={busy}
                        value={shown}
                        placeholder={f.placeholder(backendFaces, t)}
                        onChange={(e) => {
                          const value = e.target.value
                          setFaceDraft((d) => ({ ...d, [draftKey]: value }))
                        }}
                        onBlur={(e) => commitFaces(v, f.key, e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') e.currentTarget.blur()
                        }}
                      />
                    </label>
                  )
                })}
              </div>
              {/* HOW DEEP THIS VERSION STANDS IN THE GROUND — it applies
                  wherever this variant is drawn: every manual placement, every
                  scattered copy in a room or yard, every instance of a painted
                  terrain scatter and every world prop. The per-placement
                  `offset_y` in the room editor stays the trim of ONE instance
                  on top of it. A TYPED number, no dial (user 2026-08-25):
                  sinking is a value you know — 0.05 for a mesh with a base
                  plate, 0.4 to bury a root ball — and a slider that has to
                  sweep the whole ±5 m range cannot hit either. The 1.70 m
                  figure that makes the number judgeable stands below the
                  strip, on the selected chip. */}
              <SliderInput
                ariaLabel={t('Ground offset (m)')}
                label={<span className="ga-hint"
                  style={{ width: 44, flex: '0 0 auto' }}
                  title={t('Negative sinks this variant into the ground, positive lifts it off — the same amount everywhere it stands: rooms, yard, painted scatter, world props. Use it for a mesh that carries no root ball or base plate. 0 = it stands on the ground.')}>
                  ⤓ {t('Sink')}
                </span>}
                style={{ display: 'flex', fontSize: '0.8em' }}
                unit="m"
                slider={false}
                min={-SINK_LIMIT_M}
                max={SINK_LIMIT_M}
                step={0.01}
                value={v.ground_offset_m}
                onChange={(value) => commitSink(v, value)}
                inputWidth={70}
              />
              {/* The markers are the variant's too (2026-08-25) — the chip
                  says how many, the editor sits below the strip because it
                  needs the 3D viewer beside it. */}
              <button
                type="button"
                className="ga-btn ga-btn-sm"
                style={{ textAlign: 'left', padding: '0 4px',
                  fontSize: '0.85em' }}
                onClick={() => onSelect(v.index)}
                title={t('Object-local spots a figure with a matching animation snaps to. They are fractions of THIS variant’s mesh box, so every version has its own — select the chip to edit them under the strip, with the model beside you.')}
              >
                🎯 {v.markers.length} {t('markers')}
                {isSelected ? '' : ` · ${t('select to edit')}`}
              </button>
              {/* The variant's own generation subject (2026-08-24). A new
                  variant starts with a COPY of the prop's text, so the field
                  opens filled and is EDITED ("…as a sapling") instead of
                  written from nothing. Cleared = back to inheriting, which is
                  what the placeholder then shows. Three lines at rest — enough
                  to READ the sentence without opening it — and eight while it
                  is being written; the chip keeps its width either way, so the
                  strip grows downwards instead of re-flowing. */}
              <textarea
                className="ga-textarea"
                rows={descOpen === v.index ? DESC_ROWS_OPEN : DESC_ROWS_REST}
                style={{ width: '100%', fontSize: '0.85em', resize: 'vertical' }}
                disabled={busy}
                value={descDraft[v.index] ?? (v.description || '')}
                placeholder={t('Description (generation subject)')}
                title={t('What THIS variant’s source image is rendered from — the subject of its prompt. Empty = the render composes from the prop’s name. A new variant starts as a copy of the one it was added from, so a version differs by an edit: “…as a sapling”, “…broken”, “…covered in snow”.')}
                onFocus={() => setDescOpen(v.index)}
                onChange={(e) => {
                  const value = e.target.value
                  setDescDraft((d) => ({ ...d, [v.index]: value }))
                }}
                onBlur={(e) => {
                  setDescOpen((i) => (i === v.index ? null : i))
                  commitDesc(v, e.target.value)
                }}
              />
              {/* Season chips (E2c). A set, not a single choice: a variant may
                  depict two seasons. No chip lit = every season, which is why
                  the row needs no "always" chip of its own. */}
              {worldSeasons.length ? (
                <div style={{ display: 'flex', gap: 3, flexWrap: 'wrap' }}>
                  {worldSeasons.map((season) => {
                    const on = v.seasons.some(
                      (s) => s.toLowerCase() === season.toLowerCase())
                    return (
                      <button
                        key={season}
                        type="button"
                        className={`ga-btn ga-btn-sm${on ? ' ga-btn-primary' : ''}`}
                        style={{ padding: '0 5px', fontSize: '0.85em' }}
                        disabled={busy}
                        onClick={() => toggleSeason(v, season)}
                        title={on
                          ? t('This variant renders in {season}. Click to drop that season; with no season left it renders all year.')
                            .replace('{season}', season)
                          : t('Show this variant only in {season} (and in every other season you light up here).')
                            .replace('{season}', season)}
                      >
                        {season}
                      </button>
                    )
                  })}
                </div>
              ) : null}
              {v.seasons.length && !inSeason ? (
                <span className="ga-tag ga-tag-missing"
                  title={t('Out of season — this variant is not rendered while the world is in {season}.')
                    .replace('{season}', currentSeason || '—')}>
                  {t('out of season')}
                </span>
              ) : null}
              <div style={{ display: 'flex', gap: 3 }}>
                <button
                  type="button"
                  className={`ga-btn ga-btn-sm${v.active ? ' ga-btn-primary' : ''}`}
                  style={{ flex: 1 }}
                  disabled={busy || isBusy}
                  onClick={() => toggle(v)}
                  title={isBusy
                    ? t('This variant is generating right now — switching it off would move the primary variant under the running job.')
                    : v.active
                      ? t('Switch this variant off — its meshes stay stored, but nothing renders it any more. The last active variant cannot be switched off.')
                      : t('Switch this variant back on — it counts against the active limit again.')}
                >
                  {v.active ? '☑' : '☐'} {t('Active')}
                </button>
                <button
                  type="button"
                  className={`ga-btn ga-btn-sm${armedDel === v.index ? ' ga-btn-danger' : ''}`}
                  disabled={busy || isBusy || variants.length < 2}
                  onClick={() => {
                    if (armedDel === v.index) remove(v.index)
                    else setArmedDel(v.index)
                  }}
                  title={isBusy
                    ? t('This variant is generating right now — the run is about to write the very files a delete would remove.')
                    : variants.length < 2
                      ? t('A prop always keeps one variant.')
                      : t('Delete this variant with all its stored meshes.')}
                >
                  {armedDel === v.index ? t('Really?') : '×'}
                </button>
              </div>
            </div>
          )
        })}
        <button
          type="button"
          className="ga-btn ga-btn-sm"
          style={{ alignSelf: 'center' }}
          // NOT gated on a running generation: appending a slot renumbers
          // nothing and touches no file a job holds. `busy` is only this
          // strip's own in-flight request — the concurrent-add guard.
          disabled={busy || capReached}
          onClick={add}
          title={capReached
            ? t('The limit of active variants is reached — switch one off or delete it first.')
            : t('Add a variant slot — size, description, sink and markers are copied from the selected chip AS IT IS SAVED (unsaved edits stay behind, so save them first if they should travel); the next generation fills its mesh, or you upload a GLB into it.')}
        >
          + {t('Add variant')}
        </button>
      </div>
      {/* One short line — the details live in the field tooltips (user
          2026-08-24: the footer paragraph was long and half-translated). */}
      <span className="ga-hint">
        {t('Variants of one object — scatter mixes them, ★ is the default, the selected chip drives the preview.')}
        {worldSeasons.length ? ' ' + t('Season chips limit when a variant renders.') : null}
        {' '}
        {`${t('Active:')} ${activeCount}/${max}`}
      </span>
    </>
  )
}
