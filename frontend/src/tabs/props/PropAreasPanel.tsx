/**
 * PropAreasPanel — the "Areas" section of the prop editor
 * (spec-picture-props.md § 4, U2/U4/U6).
 *
 * ONE VARIANT AT A TIME (spec-bild-props-v2.md E1). The areas, the door-leaf
 * box and the orientation fix belong to the model FILE, and every variant is
 * its own generation with its own axes and its own materials — so this panel
 * speaks about the variant the strip above has selected: it loads that
 * variant's areas, shows that variant's mesh, and every verb below carries
 * `?variant=` so a split can never land in the mesh nobody is looking at.
 *
 * ONE 3D VIEW PER PROP (spec-bild-props-v2.md, ruling V11). This panel renders
 * NO viewer of its own any more: the prop page has exactly one preview — the
 * big one above — and the Areas tools are a MODE of it. The outlines, the
 * front view, the polygon ring, the assembly preview and the test swing all
 * ride the model the admin is already looking at, which is also the only mesh
 * whose R1 face order matches the `mesh_layout` a ring is flattened against.
 * So the view state does not live here: PropDetail owns it (it owns the
 * viewer), and this panel switches it through `tools`.
 *
 * WHERE A PICTURE PROP IS ASSEMBLED. A frame prop is rendered with a chroma-key
 * panel in it, Blender splits that panel off as its own material, and here the
 * admin sees the result, corrects it, and hangs a picture on it:
 *
 *   · "Detect areas" (another Blender run) and "Draw area" (the polygon tool
 *     of D5: picking a kind turns the preview above to the front view and arms
 *     the ring; the client turns the ring into flat R1 triangle indices, the
 *     server splits them),
 *   · the area list — kind, real size, where it came from, how many triangles,
 *     and a way to dissolve it again,
 *   · "Picture variants": every picture hung on this frame is a VARIANT of it
 *     (D2), so the list is the variant list filtered to the ones that carry
 *     slot values, and clicking one shows the assembly in the preview above.
 *
 * Nothing in here decides geometry, a material name or a URL form: the server
 * owns all three, and every kind-dependent choice reads `AREA_KINDS` (R8), so
 * a third kind is one entry in `propTypes.ts` and no branch here.
 */
import { useEffect, useMemo, useState } from 'react'
import { MATERIAL_PRESETS } from '@anima/scene-render'
import { useI18n } from '../../i18n/I18nProvider'
import { apiDelete, apiGet, apiPatch, apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { PictureVariantDialog } from './PictureVariantDialog'
import { AREA_KINDS, areaKindOf } from './propTypes'
import type { PropArea, PropAreasInfo, PropFull, PropSlotValues,
  PropVariant } from './propTypes'

/**
 * THE HANDLE ON THE ONE 3D VIEW (V11) — what this panel may switch on the
 * preview above, plus the lock its own verbs share with the polygon tool up
 * there. PropDetail owns every field: it owns the viewer, it reads the areas,
 * and it is where the coupling rules live (arming the ring turns the front
 * view on, leaving the front view disarms it, a stored gallery file stands the
 * tools down — that file has another face order).
 */
export interface PropAreaTools {
  /** Which kind the polygon tool is drawing for ('' = not drawing). */
  drawKind: string
  /** Which picture variant the preview is assembled with (null = bare mesh). */
  preview: number | null
  /** Switch either — the parent applies the coupling rules. The FRONT VIEW is
   *  not switched from here: arming the ring turns it on, and its button sits
   *  on the viewer that owns it. */
  setView: (patch: { drawKind?: string; preview?: number | null }) => void
  /** Which areas call is running ('' = none). A Blender run blocks the lot:
   *  they all write the same mesh, and the server serialises them anyway. */
  busy: string
  setBusy: (what: string) => void
  /** Run one areas call: it holds the lock, hands a fresh payload to the
   *  reader and maps a failure onto a toast. */
  run: (what: string, call: () => Promise<unknown>) => void
}

/** The server's `LEAF_RESIDUAL_NOTE` (props.py) — a warning with a number
 *  in it, so it cannot be looked up as it stands: the count is taken off
 *  the text and the template translated. */
const LEAF_RESIDUAL_NOTE = '{n} frame faces remain inside the leaf footprint — draw the leaf again or check the door'
const LEAF_RESIDUAL_RE = /^(\d+) frame faces remain inside the leaf footprint/

/** What one variant is called in the list. */
function variantName(v: PropVariant, t: (s: string) => string): string {
  return v.label || `${t('Variant')} ${v.index + 1}`
}

export function PropAreasPanel({ prop, variant, variants, variantMax, reloadKey,
  info, infoFailed, tools, onVariantsChanged }: {
  prop: PropFull
  /** STORE index of the variant the detail has open — the mesh this panel
   *  reads, draws on and splits. Every route below takes it. */
  variant: number
  /** The prop's variants as the detail loaded them — the picture ones are the
   *  subset carrying `slot_values`. */
  variants: PropVariant[]
  /** Configured ceiling on ACTIVE variants, the PRIMARY one included: a frame
   *  therefore holds at most `variantMax − 1` picture variants. */
  variantMax: number
  /** Bumped whenever this prop's meshes changed — a mesh that moved under an
   *  area list has to be read again. */
  reloadKey: number
  /** The OPEN variant's areas payload, read by the detail (`GET …/areas?
   *  variant=`) — one reader for the fix, the strip's box turn and this
   *  panel. `null` = still reading, or the read failed. */
  info: PropAreasInfo | null
  /** …and it FAILED (`info` null alone cannot tell that from "still
   *  reading", and the status line must not read the same in both). */
  infoFailed: boolean
  /** The one 3D view above: what this panel may switch on it, and the call
   *  lock its verbs share with the polygon tool up there (V11). */
  tools: PropAreaTools
  /** Reload the variant list (one was added, re-copied, or its pane
   *  defaults changed). */
  onVariantsChanged: () => void
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const enc = encodeURIComponent(prop.id)
  /** The view state and the call lock of the ONE preview (V11) — held by
   *  PropDetail, switched from here. */
  const { busy, setBusy, run, drawKind, preview } = tools
  /** The variant the dialog is editing (null = a new one, undefined = closed). */
  const [editing, setEditing] = useState<number | null | undefined>(undefined)

  /** Every route of this panel names the variant — one place that writes it,
   *  so no verb can quietly fall back to the primary mesh. */
  const q = `?variant=${variant}`

  // A prop OR variant switch closes the dialog: the previous variant index
  // means something else on the next prop. The VIEW state is dropped by the
  // detail, which owns it together with the viewer it belongs to.
  useEffect(() => { setEditing(undefined) }, [prop.id, variant])
  /** The areas of the variant the DIALOG is editing, whenever that is not the
   *  one the panel has open. The record publishes only the variants a scene
   *  renders, and a switched-off or out-of-season one has to be dressed too —
   *  so the file is asked directly, exactly as the detail asks for the open
   *  one. `null` = nothing fetched (yet). */
  const [editAreas, setEditAreas] = useState<PropArea[] | null>(null)
  useEffect(() => {
    setEditAreas(null)
    if (editing === undefined || editing === null || editing === variant) return
    let cancelled = false
    void (async () => {
      try {
        const d = await apiGet<PropAreasInfo>(
          `/world/props/${enc}/areas?variant=${editing}`)
        if (!cancelled && d.variant === editing) setEditAreas(d.areas || [])
      } catch {
        if (!cancelled) setEditAreas([])
      }
    })()
    return () => { cancelled = true }
  }, [enc, editing, variant, reloadKey])

  const areas = useMemo(() => info?.areas || [], [info])
  // Split by what an area is FILLED with, not by its kind name (R8): a picture
  // variant needs a gallery area, the pane defaults a preset one.
  // `warning` is what a SUCCESSFUL run had to say (today: no leaf found).
  const warning = info?.warning || ''
  const presetAreas = areas.filter((a) => areaKindOf(a.kind)?.value === 'preset')
  // THE FRAME A NEW PICTURE IS HUNG ON is always the PRIMARY variant's mesh —
  // `props.add_picture_variant` copies that one and checks the assignment
  // against ITS areas, whichever variant the admin happens to be looking at.
  // So the "new variant" button and the dialog behind it read the primary
  // entry of the record, not the areas loaded above.
  const primaryEntry = prop.variant_tiers?.[0]
  const frameAreas = primaryEntry?.areas || (variant === 0 ? areas : [])
  const framePictureAreas = frameAreas.filter(
    (a) => areaKindOf(a.kind)?.value === 'image')
  const pictureVariants = variants.filter(
    (v) => v.slot_values && Object.keys(v.slot_values).length)
  /** The cap counts ACTIVE variants INCLUDING the primary one, so a frame
   *  holds at most `variantMax − 1` pictures. */
  const pictureCap = Math.max(0, variantMax - 1)

  /** A fresh split of THIS variant's mesh. Without `kinds` the server looks
   *  for everything it knows; "Detect now" hands it exactly what the prop
   *  asked its render for (E3). */
  const detect = (kinds?: string[]) => run(kinds ? 'detect-kinds' : 'detect',
    () => apiPost(`/world/props/${enc}/areas${q}`,
      kinds ? { mode: 'auto', kinds } : { mode: 'auto' }))

  const setKind = (areaId: string, kind: string) => run('kind',
    () => apiPatch(`/world/props/${enc}/areas/${encodeURIComponent(areaId)}${q}`,
      { kind }))

  const removeArea = (areaId: string) => run('delete',
    () => apiDelete(`/world/props/${enc}/areas/${encodeURIComponent(areaId)}${q}`))

  /** What THIS variant's pane shows when nobody hung anything on it. The
   *  defaults describe ONE mesh, so they live on the variant entry like its
   *  slot values do (v2 E1) — and the variant list has to be reloaded with
   *  the record, because that is where the dialog reads them from. */
  const setDefault = (areaId: string, preset: string) => {
    const next: PropSlotValues = { ...(info?.area_defaults || {}) }
    if (preset) next[areaId] = { preset }
    else delete next[areaId]
    run('defaults', async () => {
      await apiPost(`/world/props/${enc}/variants/${variant}/area-defaults`,
        { area_defaults: next })
      onVariantsChanged()
      return undefined
    })
  }

  const submitVariant = async (values: PropSlotValues, label: string | undefined) => {
    setBusy('variant')
    try {
      // R10: the label travels only when the admin typed one — an omitted key
      // keeps the stored name, `""` re-derives it from the picture files.
      const body: Record<string, unknown> = { slot_values: values }
      if (label !== undefined) body.label = label
      if (editing === null) {
        await apiPost(`/world/props/${enc}/variants/picture`, body)
        toast(t('Picture variant created.'))
      } else if (editing !== undefined) {
        await apiPost(`/world/props/${enc}/variants/${editing}/slot-values`, body)
        toast(t('Saved.'))
      }
      setEditing(undefined)
      onVariantsChanged()
    } catch (e) {
      toast(`${t('Error')}: ${(e as Error).message}`, 'error')
    } finally {
      setBusy('')
    }
  }

  const recopy = async (index: number) => {
    setBusy('recopy')
    try {
      await apiPost(`/world/props/${enc}/variants/${index}/recopy`, {})
      toast(t('Frame copied again.'))
      onVariantsChanged()
    } catch (e) {
      toast(`${t('Error')}: ${(e as Error).message}`, 'error')
    } finally {
      setBusy('')
    }
  }

  // THREE states, not two: `info` is null while the areas request is in
  // flight or after it failed, and reading that as "Blender available" would
  // put a green tick on a panel that knows nothing. Only an answered request
  // that says `available` is one.
  const blenderReason = info?.blender.available === false
    ? (info.blender.reason || t('unknown reason')) : ''
  const running = !!busy
  /** The variant this panel is open on, as the strip knows it — its label
   *  names the header, its mesh decides whether there is anything to split. */
  const shownVariant = variants.find((v) => v.index === variant) || null
  /** A verb may only be offered when the answer actually said Blender can
   *  run — an unread panel knows nothing and must not promise a split. */
  const canRun = !!info && !blenderReason && !running && !!info.model_file
  /** WHICH MESH the dialog is dressing. A NEW picture variant is a copy of
   *  the PRIMARY frame and the server checks its values against THAT file's
   *  areas; an EXISTING variant is checked against its OWN file — never the
   *  primary's, or the dialog would offer areas that variant does not have.
   *  So the controls are built from the entry that will be validated. */
  const dialogAreas = editing === null || editing === undefined
    ? frameAreas
    : (editing === variant ? areas : (editAreas || []))
  /** Which key surfaces the NEXT render of this prop is asked for (R7, E3) —
   *  a prop-wide wish, edited in the generation dialogs. `info` answers with
   *  the record's list, the record itself before the first payload. */
  const requested = info?.key_areas || prop.key_areas || []

  return (
    <>
      <div className="ga-form-section-label">
        {`${t('Areas')} · ${t('Variant')} ${variant + 1}`}
        {shownVariant?.label ? ` · ${shownVariant.label}` : ''}
      </div>
      <span className="ga-hint" style={{ display: 'block' }}>
        {t('The key surfaces of THIS variant’s mesh — the panel a picture hangs on, the pane of a door. Each one is a material of that model file; a picture is hung on it as a variant of this prop.')}
      </span>

      {/* Status: can Blender run at all, when did it last, what went wrong. */}
      <div className="ga-hint" style={{ display: 'block' }}>
        {!info
          ? (infoFailed
            ? `⚠ ${t('Could not read this prop’s areas — reload the page.')}`
            : `… ${t('Reading the areas…')}`)
          : blenderReason
            ? `⚠ ${t('Blender is not available')}: ${blenderReason}`
            : `✓ ${t('Blender available')}`}
        {info?.last_run ? ` · ${t('last run')} ${info.last_run.slice(0, 16).replace('T', ' ')}` : ''}
      </div>
      {info?.error ? (
        <div className="ga-hint" style={{ display: 'block', color: 'var(--danger, #f85149)' }}>
          {`${t('Last automatic run failed')}: ${info.error}`}
        </div>
      ) : null}
      {/* A run that WORKED and found nothing to cut is a note, not a failure
          — the server keeps the two apart (`warning` vs. `error`), so a door
          without a detectable leaf does not read as a broken detection. */}
      {warning ? (
        <div className="ga-hint" style={{ display: 'block' }}>
          {`ℹ ${LEAF_RESIDUAL_RE.test(warning)
            ? t(LEAF_RESIDUAL_NOTE).replace('{n}', LEAF_RESIDUAL_RE.exec(warning)![1])
            : t(warning)}`}
        </div>
      ) : null}
      {info && !areas.length && info.last_run ? (
        <div className="ga-hint" style={{ display: 'block' }}>
          {t('Nothing detected — draw an area or check the prompt (the render needs a flat chroma-key panel).')}
        </div>
      ) : null}

      {/* WHAT THE NEXT RENDER IS ASKED FOR (E3). A line, not a checkbox: the
          wish is set where a render is ordered (the create form, the
          generation dialogs), and here it only explains what a mesh of this
          prop is expected to carry — plus the one verb that belongs to it,
          looking for exactly those kinds on the variant that is open. */}
      <div className="ga-form-row" style={{ marginTop: 4 }}>
        <span className="ga-hint">
          {`${t('Requested for the next generation')}: `}
          {requested.length
            ? requested.map((k) => t(areaKindOf(k)?.label || k)).join(' · ')
            : t('none')}
        </span>
        <button type="button" className="ga-btn ga-btn-sm"
          disabled={!canRun || !requested.length}
          onClick={() => detect(requested)}
          title={requested.length
            ? t('Split THIS variant’s mesh now, looking for exactly the kinds above — for a mesh that landed before the prop asked for them.')
            : t('This prop asks its renders for no key surface — pick the kinds when you order a render.')}>
          🔍 {busy === 'detect-kinds' ? t('Detecting…') : t('Detect now')}
        </button>
      </div>

      <div className="ga-form-row">
        <button type="button" className="ga-btn ga-btn-sm"
          disabled={!canRun}
          onClick={() => detect()}
          title={t('Look for chroma-key panels in the mesh again and split every one of them off as its own material. Replaces the automatically detected areas; a drawn one is kept.')}>
          🔍 {busy === 'detect' ? t('Detecting…') : t('Detect areas')}
        </button>
        {/* THE POLYGON TOOL IS DRAWN UP THERE (V11): picking a kind turns the
            one preview to the front view and arms the ring — a flat surface is
            only fully in view head-on, and edge-on there is barely a sliver of
            it to click. */}
        {drawKind ? (
          <>
            <span className="ga-hint">
              {t('Click the outline of the surface; click the first point again to close it, Escape cancels.')}
            </span>
            <button type="button" className="ga-btn ga-btn-sm"
              onClick={() => tools.setView({ drawKind: '' })}>{t('Cancel')}</button>
          </>
        ) : (
          <select className="ga-input" style={{ width: 130 }} value=""
            disabled={!canRun}
            title={t('Draw a surface by hand: pick its kind, then ring it on the front view.')}
            onChange={(e) => {
              if (e.target.value) tools.setView({ drawKind: e.target.value })
            }}>
            <option value="">{t('✏ Draw area…')}</option>
            {AREA_KINDS.map((k) => (
              <option key={k.kind} value={k.kind}>{t(k.label)}</option>
            ))}
          </select>
        )}
      </div>

      {/* The areas themselves. */}
      {areas.length ? (
        <div className="ga-list" style={{ marginTop: 8, maxHeight: 220 }}>
          {areas.map((a) => (
            <div key={a.id} className="ga-list-row" style={{ cursor: 'default' }}>
              <span className="ga-list-row-main">
                <span style={{ color: areaKindOf(a.kind)?.color }}>■</span>
                <strong>{a.id}</strong>
                <span className="ga-list-row-sub">
                  {`${a.size_m[0].toFixed(2)} × ${a.size_m[1].toFixed(2)} m`}
                  {' · '}
                  {a.source === 'manual' ? t('drawn')
                    : a.source === 'adopt' ? t('named') : t('detected')}
                  {' · '}
                  {t('{n} faces').replace('{n}', String(a.faces))}
                </span>
              </span>
              <span style={{ display: 'inline-flex', gap: 4, alignItems: 'center' }}>
                {/* THE DOOR LEAF is a node, not a material (R9): it cannot be
                    renamed into a colour kind, nor a colour area into it —
                    the server refuses both, so neither is offered. */}
                {a.kind === 'leaf' ? (
                  <span className="ga-hint" style={{ width: 110 }}
                    title={t('The door leaf is a node of the mesh, not a material — only the leaf swings. Dissolve it to put its faces back into the frame.')}>
                    {t('Door leaf')}
                  </span>
                ) : (
                <select className="ga-input" style={{ width: 110 }}
                  value={a.kind} disabled={running}
                  title={t('Change what this surface IS — the material is renamed, and a picture area becomes a pane or the other way round.')}
                  onChange={(e) => setKind(a.id, e.target.value)}>
                  {/* A kind this client does not know keeps its own entry —
                      otherwise the select would SHOW the first option and
                      silently offer to change what nobody asked to change. */}
                  {areaKindOf(a.kind) ? null : (
                    <option value={a.kind}>{a.kind}</option>
                  )}
                  {AREA_KINDS.filter((k) => k.kind !== 'leaf').map((k) => (
                    <option key={k.kind} value={k.kind}>{t(k.label)}</option>
                  ))}
                </select>
                )}
                <button type="button" className="ga-btn ga-btn-sm"
                  disabled={running}
                  aria-label={t('Delete area')}
                  title={t('Dissolve this area — its triangles go back to the material they came from.')}
                  onClick={() => removeArea(a.id)}>🗑</button>
              </span>
            </div>
          ))}
        </div>
      ) : null}

      {/* A pane's look belongs to the VARIANT (v2 E1) — it describes the
          panes of THIS mesh, and a door prop has no picture variants, so
          without it its glass could never be set at all. */}
      {presetAreas.length ? (
        <>
          <div className="ga-form-section-label">{t('Pane defaults')}</div>
          <span className="ga-hint" style={{ display: 'block' }}>
            {t('What these panes look like on every placement of THIS variant — a door has no picture variants, so this is where its glass is set.')}
          </span>
          <div className="ga-form-row">
            {presetAreas.map((a) => (
              <label key={a.id} style={{ display: 'inline-flex', gap: 4, alignItems: 'center' }}>
                <span className="ga-hint">{a.id}</span>
                <select className="ga-input" style={{ width: 120 }}
                  disabled={running}
                  value={info?.area_defaults?.[a.id]?.preset || ''}
                  onChange={(e) => setDefault(a.id, e.target.value)}>
                  <option value="">{t('None')}</option>
                  {/* The looks a renderer actually draws — @anima/scene-render
                      owns that list, and a preset nothing draws must not be
                      offerable. */}
                  {MATERIAL_PRESETS.map((preset) => (
                    <option key={preset} value={preset}>
                      {preset === 'glass' ? t('Glass') : preset}
                    </option>
                  ))}
                </select>
              </label>
            ))}
          </div>
        </>
      ) : null}

      {/* ── Picture variants ── */}
      <div className="ga-form-section-label">{t('Picture variants')}</div>
      <span className="ga-hint" style={{ display: 'block' }}>
        {t('Every picture hung on this frame is a variant of the prop: it carries a copy of the frame’s mesh and shows its own picture. The floor plan then places the prop and picks the variant.')}
      </span>
      {pictureVariants.length ? (
        <div className="ga-list" style={{ maxHeight: 240 }}>
          {pictureVariants.map((v) => (
            <div key={v.index}
              className={`ga-list-row${preview === v.index ? ' is-active' : ''}`}
              style={{ cursor: 'default' }}>
              <span className="ga-list-row-main">
                <button type="button" className="ga-btn ga-btn-sm"
                  aria-label={t('Preview this variant')}
                  aria-pressed={preview === v.index}
                  title={preview === v.index
                    ? t('Stop previewing — show the bare frame again.')
                    : t('Show this assembly in the viewer above.')}
                  onClick={() => tools.setView({
                    preview: preview === v.index ? null : v.index })}>
                  👁
                </button>
                <strong>{variantName(v, t)}</strong>
                <span className="ga-list-row-sub">
                  {Object.entries(v.slot_values || {}).map(([id, value]) => {
                    const known = areas.some((a) => a.id === id)
                    const what = value.image
                      ? decodeURIComponent(value.image.split('/').pop() || '')
                      : (value.preset || '')
                    return (
                      <span key={id} style={{ marginRight: 8, opacity: known ? 1 : 0.5 }}>
                        {`${id}: ${what}`}
                        {known ? '' : ` ${t('(area removed)')}`}
                      </span>
                    )
                  })}
                </span>
                {v.stale ? (
                  <span className="ga-list-row-sub"
                    title={t('The frame was split again after this copy was made — the picture still hangs on the old mesh.')}>
                    ⚠ {t('outdated frame')}
                  </span>
                ) : null}
              </span>
              <span style={{ display: 'inline-flex', gap: 4 }}>
                <button type="button" className="ga-btn ga-btn-sm"
                  disabled={running}
                  aria-label={t('Edit the pictures')}
                  title={t('Change the pictures on this variant.')}
                  onClick={() => setEditing(v.index)}>✏</button>
                {v.stale ? (
                  <button type="button" className="ga-btn ga-btn-sm"
                    disabled={running}
                    title={t('Copy the prop’s current frame into this variant again — its pictures stay.')}
                    onClick={() => void recopy(v.index)}>
                    ⟳ {t('Re-copy mesh')}
                  </button>
                ) : null}
              </span>
            </div>
          ))}
        </div>
      ) : (
        <span className="ga-hint" style={{ display: 'block' }}>
          {t('No picture hung on this frame yet.')}
        </span>
      )}
      <div className="ga-form-row">
        <button type="button" className="ga-btn ga-btn-sm"
          disabled={running || !framePictureAreas.length
            || pictureVariants.length >= pictureCap}
          title={framePictureAreas.length
            ? t('Hang a picture: the server copies the PRIMARY variant’s frame into a new variant and puts the picture on it.')
            : t('The primary variant has no picture area yet — detect or draw one on it first.')}
          onClick={() => setEditing(null)}>
          ＋ {t('New picture variant')}
        </button>
        <span className="ga-hint">
          {t('{n} of {max} picture variants')
            .replace('{n}', String(pictureVariants.length))
            .replace('{max}', String(pictureCap))}
        </span>
      </div>

      <PictureVariantDialog
        open={editing !== undefined}
        title={editing === null
          ? t('New picture variant')
          : `${t('Picture variant')} · ${editing !== undefined && editing !== null
            ? variantName(variants.find((v) => v.index === editing)
              || ({ index: editing } as PropVariant), t) : ''}`}
        areas={dialogAreas}
        initial={editing !== null && editing !== undefined
          ? variants.find((v) => v.index === editing)?.slot_values
          : primaryEntry?.area_defaults}
        initialLabel={editing !== null && editing !== undefined
          ? variants.find((v) => v.index === editing)?.label || '' : ''}
        busy={busy === 'variant'}
        onSubmit={(values, label) => void submitVariant(values, label)}
        onClose={() => setEditing(undefined)}
      />
    </>
  )
}
