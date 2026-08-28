/**
 * PropAreasPanel — the "Areas" section of the prop editor
 * (spec-picture-props.md § 4, U2/U4/U6).
 *
 * WHERE A PICTURE PROP IS ASSEMBLED. A frame prop is rendered with a chroma-key
 * panel in it, Blender splits that panel off as its own material, and here the
 * admin sees the result, corrects it, and hangs a picture on it:
 *
 *   · the FRONT VIEW of the prop with every key surface outlined in its kind's
 *     colour (the outline edges come from the server — the client draws them,
 *     it never measures geometry, § B5a),
 *   · "Detect areas" (another Blender run) and "Draw area" (the polygon tool
 *     of D5: ring the panel on the front view, the client turns the ring into
 *     flat R1 triangle indices, the server splits them),
 *   · the area list — kind, real size, where it came from, how many triangles,
 *     and a way to dissolve it again,
 *   · "Picture variants": every picture hung on this frame is a VARIANT of it
 *     (D2), so the list is the variant list filtered to the ones that carry
 *     slot values, and clicking one shows the assembly in the viewer.
 *
 * Nothing in here decides geometry, a material name or a URL form: the server
 * owns all three, and every kind-dependent choice reads `AREA_KINDS` (R8), so
 * a third kind is one entry in `propTypes.ts` and no branch here.
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { MATERIAL_PRESETS } from '@anima/scene-render'
import { Model3DViewer } from '../characters/Model3DViewer'
import { useI18n } from '../../i18n/I18nProvider'
import { apiDelete, apiGet, apiPatch, apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { PictureVariantDialog } from './PictureVariantDialog'
import { AREA_KINDS, areaKindOf } from './propTypes'
import type { PropAreasInfo, PropFull, PropSlotValues,
  PropVariant } from './propTypes'

/** What one variant is called in the list. */
function variantName(v: PropVariant, t: (s: string) => string): string {
  return v.label || `${t('Variant')} ${v.index + 1}`
}

export function PropAreasPanel({ prop, variants, variantMax, reloadKey,
  onPropChanged, onVariantsChanged }: {
  prop: PropFull
  /** The prop's variants as the detail loaded them — the picture ones are the
   *  subset carrying `slot_values`. */
  variants: PropVariant[]
  /** Configured ceiling on ACTIVE variants, the PRIMARY one included: a frame
   *  therefore holds at most `variantMax − 1` picture variants. */
  variantMax: number
  /** Bumped whenever this prop's meshes changed — the viewer has to refetch. */
  reloadKey: number
  /** Reload the prop record (its `key_areas` / `area_defaults` moved). */
  onPropChanged: () => void
  /** Reload the variant list (one was added or re-copied). */
  onVariantsChanged: () => void
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const enc = encodeURIComponent(prop.id)
  const [info, setInfo] = useState<PropAreasInfo | null>(null)
  /** Which action is running ('' = none). A Blender run blocks the lot: they
   *  all write the same mesh, and the server serialises them anyway. */
  const [busy, setBusy] = useState('')
  /** The kind the polygon tool is drawing for ('' = not drawing). */
  const [drawKind, setDrawKind] = useState('')
  /** Which picture variant the viewer is previewing (null = the bare mesh). */
  const [preview, setPreview] = useState<number | null>(null)
  /** The variant the dialog is editing (null = a new one, undefined = closed). */
  const [editing, setEditing] = useState<number | null | undefined>(undefined)

  /** Did the last areas request FAIL? `info` null alone cannot say — before
   *  the first answer it means "still reading", after a failure "we know
   *  nothing", and the status line must not read the same in both. */
  const [loadFailed, setLoadFailed] = useState(false)

  const load = useCallback(async () => {
    try {
      setInfo(await apiGet<PropAreasInfo>(`/world/props/${enc}/areas`))
      setLoadFailed(false)
    } catch {
      setInfo(null)
      setLoadFailed(true)
    }
  }, [enc])
  useEffect(() => { void load() }, [load, reloadKey])
  // A prop switch drops every view state — the previous prop's variant index
  // means something else here.
  useEffect(() => { setPreview(null); setDrawKind(''); setEditing(undefined) },
    [prop.id])

  const areas = useMemo(() => info?.areas || [], [info])
  const outlines = useMemo(() => areas.map((a) => ({
    id: a.id, kind: a.kind, edges: a.edges || [] })), [areas])
  // Split by what an area is FILLED with, not by its kind name (R8): a picture
  // variant needs a gallery area, the pane defaults a preset one.
  // `warning` is what a SUCCESSFUL run had to say (today: no leaf found).
  // Read off the payload here rather than through `PropAreasInfo`, which a
  // parallel strand owns.
  const warning = (info as { warning?: string } | null)?.warning || ''
  const pictureAreas = areas.filter((a) => areaKindOf(a.kind)?.value === 'image')
  const presetAreas = areas.filter((a) => areaKindOf(a.kind)?.value === 'preset')
  const pictureVariants = variants.filter(
    (v) => v.slot_values && Object.keys(v.slot_values).length)
  /** The cap counts ACTIVE variants INCLUDING the primary one, so a frame
   *  holds at most `variantMax − 1` pictures. */
  const pictureCap = Math.max(0, variantMax - 1)
  const previewVariant = preview === null
    ? null : variants.find((v) => v.index === preview) || null
  // WHAT THE PREVIEW SHOWS: the prop-wide defaults with the picked variant's
  // own values on top — the same merge the scene recipe does (`_slot_spec`),
  // keyed by AREA ID, which is the slot name `applySlotMaterials` matches
  // after taking the material's `slot_` prefix off (R11).
  //
  // MEMOISED, deliberately: the viewer re-applies its slot materials whenever
  // this object's identity changes, and a fresh map per render would reload
  // every texture on every keystroke elsewhere in the panel. It depends on the
  // two things it reads, not on the whole `info` — a status refresh must not
  // re-download the picture.
  const defaults = info?.area_defaults
  const slots = useMemo(() => (previewVariant
    ? { ...(defaults || {}), ...(previewVariant.slot_values || {}) }
    : undefined), [previewVariant, defaults])

  /** Every areas call answers the same payload — one place that stores it and
   *  maps the failure onto a toast the admin can act on. */
  const run = useCallback(async (what: string, call: () => Promise<unknown>) => {
    setBusy(what)
    try {
      const answer = await call() as PropAreasInfo | undefined
      if (answer && Array.isArray(answer.areas)) setInfo(answer)
      else await load()
      onPropChanged()
    } catch (e) {
      toast(`${t('Error')}: ${(e as Error).message}`, 'error')
      await load()
    } finally {
      setBusy('')
    }
  }, [load, onPropChanged, t, toast])

  const detect = () => void run('detect',
    () => apiPost(`/world/props/${enc}/areas`, { mode: 'auto' }))

  const onPolygonFaces = (faces: number[]) => {
    const kind = drawKind
    setDrawKind('')
    if (!faces.length) {
      toast(t('Nothing was inside the outline — draw around the surface, facing it.'), 'error')
      return
    }
    void run('draw', () => apiPost(`/world/props/${enc}/areas`,
      { mode: 'manual', faces, kind }))
  }

  const setKind = (areaId: string, kind: string) => void run('kind',
    () => apiPatch(`/world/props/${enc}/areas/${encodeURIComponent(areaId)}`, { kind }))

  const removeArea = (areaId: string) => void run('delete',
    () => apiDelete(`/world/props/${enc}/areas/${encodeURIComponent(areaId)}`))

  /** The prop-wide value of a pane — a door prop has no variants, so this is
   *  the only way its glass ever gets a look. */
  const setDefault = (areaId: string, preset: string) => {
    const next: PropSlotValues = { ...(info?.area_defaults || {}) }
    if (preset) next[areaId] = { preset }
    else delete next[areaId]
    void run('defaults', async () => {
      await apiPost(`/world/props/${enc}`, { area_defaults: next })
      return undefined
    })
  }

  /** Which key colours a NEW render of this prop asks for (R7). */
  const toggleKeyArea = (kind: string, on: boolean) => {
    const cur = new Set(info?.key_areas || [])
    if (on) cur.add(kind)
    else cur.delete(kind)
    void run('key', async () => {
      await apiPost(`/world/props/${enc}`,
        { key_areas: AREA_KINDS.filter((k) => cur.has(k.kind)).map((k) => k.kind) })
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
  /** A verb may only be offered when the answer actually said Blender can
   *  run — an unread panel knows nothing and must not promise a split. */
  const canRun = !!info && !blenderReason && !running && prop.has_model

  return (
    <>
      <div className="ga-form-section-label">{t('Areas')}</div>
      <span className="ga-hint" style={{ display: 'block' }}>
        {t('The key surfaces of this prop’s mesh — the panel a picture hangs on, the pane of a door. Each one is a material of the model; a picture is hung on it as a variant of this prop.')}
      </span>

      {/* Status: can Blender run at all, when did it last, what went wrong. */}
      <div className="ga-hint" style={{ display: 'block' }}>
        {!info
          ? (loadFailed
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
          {`ℹ ${t(warning)}`}
        </div>
      ) : null}
      {info && !areas.length && info.last_run ? (
        <div className="ga-hint" style={{ display: 'block' }}>
          {t('Nothing detected — draw an area or check the prompt (the render needs a flat chroma-key panel).')}
        </div>
      ) : null}

      <div className="ga-form-row">
        <button type="button" className="ga-btn ga-btn-sm"
          disabled={!canRun}
          onClick={detect}
          title={t('Look for chroma-key panels in the mesh again and split every one of them off as its own material. Replaces the automatically detected areas; a drawn one is kept.')}>
          🔍 {busy === 'detect' ? t('Detecting…') : t('Detect areas')}
        </button>
        {drawKind ? (
          <>
            <span className="ga-hint">
              {t('Click the outline of the surface, double-click to close, Escape cancels.')}
            </span>
            <button type="button" className="ga-btn ga-btn-sm"
              onClick={() => setDrawKind('')}>{t('Cancel')}</button>
          </>
        ) : (
          <>
            <select className="ga-input" style={{ width: 130 }} value=""
              disabled={!canRun}
              title={t('Draw a surface by hand: pick its kind, then ring it on the front view.')}
              onChange={(e) => { if (e.target.value) setDrawKind(e.target.value) }}>
              <option value="">{t('✏ Draw area…')}</option>
              {AREA_KINDS.map((k) => (
                <option key={k.kind} value={k.kind}>{t(k.label)}</option>
              ))}
            </select>
          </>
        )}
      </div>

      {/* The front view with the outlines — and, while a picture variant is
          picked, the assembly it renders as. */}
      {prop.has_model ? (
        <Model3DViewer
          url={`/assets/props/${enc}/model?v=${encodeURIComponent(prop.created_at || '')}-${reloadKey}`}
          format="glb"
          height={340}
          rotation={prop.rotation}
          frontal
          areaOutlines={outlines}
          meshLayout={info?.mesh_layout}
          drawing={!!drawKind}
          onPolygonFaces={onPolygonFaces}
          slots={slots}
          leafBbox={info?.leaf_bbox || null}
        />
      ) : (
        <div className="ga-empty">
          {t('No model yet — a prop gets its key surfaces from its mesh.')}
        </div>
      )}

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
                  {a.source === 'manual' ? t('drawn') : t('detected')}
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

      {/* A pane's look is prop-wide: a door prop has no variants, so without
          this its glass could never be set at all. */}
      {presetAreas.length ? (
        <>
          <div className="ga-form-section-label">{t('Pane defaults')}</div>
          <span className="ga-hint" style={{ display: 'block' }}>
            {t('What these panes look like on EVERY placement of this prop — a door has no variants, so this is where its glass is set.')}
          </span>
          <div className="ga-form-row">
            {presetAreas.map((a) => (
              <label key={a.id} style={{ display: 'inline-flex', gap: 4, alignItems: 'center' }}>
                <span className="ga-hint">{a.id}</span>
                <select className="ga-input" style={{ width: 120 }}
                  disabled={running}
                  value={defaults?.[a.id]?.preset || ''}
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

      {/* What a NEW render of this prop asks for (R7) — the same choice the
          create form offers, on a prop that already exists. */}
      <div className="ga-form-row" style={{ marginTop: 4 }}>
        <span className="ga-hint">{t('Key areas requested at render time')}:</span>
        {AREA_KINDS.filter((k) => k.requestLabel).map((k) => (
          <label key={k.kind} style={{ display: 'inline-flex', gap: 4, alignItems: 'center' }}>
            <input type="checkbox" disabled={running}
              checked={(info?.key_areas || []).includes(k.kind)}
              onChange={(e) => toggleKeyArea(k.kind, e.target.checked)} />
            {t(k.requestLabel as string)}
          </label>
        ))}
      </div>

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
                  onClick={() => setPreview(preview === v.index ? null : v.index)}>
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
          disabled={running || !pictureAreas.length
            || pictureVariants.length >= pictureCap}
          title={pictureAreas.length
            ? t('Hang a picture: the server copies this frame’s mesh into a new variant and puts the picture on it.')
            : t('This prop has no picture area yet — detect or draw one first.')}
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
        areas={areas}
        initial={editing !== null && editing !== undefined
          ? variants.find((v) => v.index === editing)?.slot_values
          : info?.area_defaults}
        initialLabel={editing !== null && editing !== undefined
          ? variants.find((v) => v.index === editing)?.label || '' : ''}
        busy={busy === 'variant'}
        onSubmit={(values, label) => void submitVariant(values, label)}
        onClose={() => setEditing(undefined)}
      />
    </>
  )
}
