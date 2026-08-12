/**
 * TerrainTypesDialog — the editor of the ground vocabulary (Seamless World, E2).
 *
 * The catalog is TWO layers with override-replace per kind: the shared seed
 * (`shared/terrain/types.json`) ships the defaults, a world row replaces the
 * whole entry of the same kind. That is why there is no "edit shared" here —
 * saving a shared row simply CREATES the world override, and "Reset" deletes
 * that override so the shared entry comes back. A kind that never existed in
 * the seed has nothing to fall back to: resetting it removes it for good,
 * which is what the confirmation step is for.
 *
 * Nothing is edited live. Each row keeps its own draft and writes only on
 * `Save`, because a colour picker that PUTs on every drag would put a hundred
 * writes on the wire for one decision. The saved row is refilled from the
 * SERVER's answer (`PUT` returns the sanitized entry), so a clamped speed or a
 * truncated name shows what was stored instead of what was typed.
 *
 * The limits mirror `app/core/terrain_types.py`. They are a copy, not a second
 * opinion: the server still sanitizes every field, this only spares the user a
 * 400 for something a regex could have said in place.
 *
 * Each row can also author what its ground GROWS — the `meta.scatter` block
 * the 3D ground reads (E5 Task 6). It hangs under the row instead of in a
 * column of its own: three fields per kind would make the table unreadable,
 * and scatter is authored once and then left alone.
 */
import { useCallback, useEffect, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiDelete, apiPut } from '../../lib/api'
import { loadPropAssets, type PropRef } from '../../lib/refs'
import { useToast } from '../../lib/Toast'
import type { TerrainScatter, TerrainType } from './mapTypes'

/** Server mirrors — `_KIND_RE`, `SPEED_MIN/MAX`, `DEFAULT_COLOR`. */
const KIND_RE = /^[a-z0-9][a-z0-9_-]{0,39}$/
const SPEED_MIN = 0
const SPEED_MAX = 2
const SPEED_STEP = 0.05
const NAME_MAX = 60
const DEFAULT_COLOR = '#888888'

/** The URL a scatter `model` stores: exactly the `model_url` the prop library
 *  hands out on the server (`app/core/props.py`), and exactly what the 3D
 *  ground passes to its GLB loader unchanged (`client3d/src/scene/ground.ts`
 *  → `buildScatter`). Site-relative like every other asset URL in the payload,
 *  so a client on another host resolves it against its own API origin. */
function propModelUrl(id: string): string {
  return `/assets/props/${encodeURIComponent(id)}/model`
}

/**
 * `meta.scatter` as a normalized block, or null when this kind grows nothing.
 *
 * `meta` is free-form JSON the server passes through, so nothing guarantees a
 * stored `scatter` has the declared shape — every field is read through a
 * check. The field ORDER is load-bearing: the dirty check compares this
 * against the draft block by JSON string, and both are built here.
 */
function readScatter(meta: Record<string, unknown> | undefined): TerrainScatter | null {
  const raw = meta?.scatter
  if (!raw || typeof raw !== 'object') return null
  const s = raw as Record<string, unknown>
  const density = Number(s.density_per_100m2)
  const height = Number(s.height_m)
  const out: TerrainScatter = {
    density_per_100m2: Number.isFinite(density) && density > 0 ? density : 0,
  }
  if (Number.isFinite(height) && height > 0) out.height_m = height
  if (typeof s.model === 'string' && s.model) out.model = s.model
  return out
}

/** What one row sends — the same shape it reads. `meta` travels along
 *  untouched: the route is a full replace, so a body without it would blank
 *  whatever put something there. */
type TypeDraft = TerrainType

interface TypeRowProps {
  type: TerrainType
  source: 'shared' | 'world'
  /** The prop library for the scatter model picker (only props WITH a mesh). */
  props: PropRef[]
  busy: boolean
  armedReset: boolean
  onArmReset: (armed: boolean) => void
  onSave: (draft: TypeDraft) => Promise<TerrainType | null>
  onReset: () => void
}

function TypeRow({
  type, source, props, busy, armedReset, onArmReset, onSave, onReset,
}: TypeRowProps) {
  const { t } = useI18n()
  const [name, setName] = useState(type.name || '')
  const [color, setColor] = useState(type.color || DEFAULT_COLOR)
  const [passable, setPassable] = useState(!!type.passable)
  const [speed, setSpeed] = useState(String(type.speed_factor))

  const stored = readScatter(type.meta)
  const [scatterOpen, setScatterOpen] = useState(false)
  const [density, setDensity] = useState(
    stored && stored.density_per_100m2 ? String(stored.density_per_100m2) : '')
  const [tuftH, setTuftH] = useState(stored?.height_m ? String(stored.height_m) : '')
  const [model, setModel] = useState(stored?.model || '')

  const speedNum = parseFloat(speed)
  const speedBad = !Number.isFinite(speedNum)
    || speedNum < SPEED_MIN || speedNum > SPEED_MAX
  const densityNum = parseFloat(density)
  const densityBad = density.trim() !== ''
    && (!Number.isFinite(densityNum) || densityNum < 0)
  const tuftNum = parseFloat(tuftH)
  const tuftBad = tuftH.trim() !== '' && (!Number.isFinite(tuftNum) || tuftNum <= 0)

  // The block this row would store. Nothing authored (no density, no height,
  // no model) means NO block at all — an empty `scatter: {}` would be a
  // rendering statement nobody made. A density of 0 next to a chosen model is
  // kept on purpose: that is "scatter turned off", not "never configured".
  const densityOn = Number.isFinite(densityNum) && densityNum > 0
  const tuftOn = Number.isFinite(tuftNum) && tuftNum > 0
  let draftScatter: TerrainScatter | null = null
  if (densityOn || tuftOn || model) {
    draftScatter = { density_per_100m2: densityOn ? densityNum : 0 }
    if (tuftOn) draftScatter.height_m = tuftNum
    if (model) draftScatter.model = model
  }

  // A field the user cannot fix by typing further is not "dirty", it is
  // wrong — but it still has to enable `Save` so the marking is reachable.
  const dirty = name !== (type.name || '')
    || color !== (type.color || DEFAULT_COLOR)
    || passable !== !!type.passable
    || (speedBad ? speed !== String(type.speed_factor) : speedNum !== type.speed_factor)
    || JSON.stringify(draftScatter) !== JSON.stringify(stored)

  const save = useCallback(async () => {
    if (speedBad || densityBad || tuftBad) return
    // `meta` is free-form and belongs to whoever wrote it — only the
    // `scatter` key is this dialog's, everything else travels along.
    const meta: Record<string, unknown> = { ...(type.meta || {}) }
    if (draftScatter) meta.scatter = draftScatter
    else delete meta.scatter
    const saved = await onSave({
      kind: type.kind, name, color, passable,
      speed_factor: speedNum, meta,
    })
    if (!saved) return
    setName(saved.name || '')
    setColor(saved.color || DEFAULT_COLOR)
    setPassable(!!saved.passable)
    setSpeed(String(saved.speed_factor))
    const back = readScatter(saved.meta)
    setDensity(back && back.density_per_100m2 ? String(back.density_per_100m2) : '')
    setTuftH(back?.height_m ? String(back.height_m) : '')
    setModel(back?.model || '')
  }, [color, densityBad, draftScatter, name, onSave, passable, speedBad,
      speedNum, tuftBad, type])

  const modelKnown = !model || props.some((p) => propModelUrl(p.id) === model)

  return (
    <>
    <tr>
      <td className="ga-tt-kind">{type.kind}</td>
      <td>
        <input
          className="ga-input ga-tt-input"
          maxLength={NAME_MAX}
          value={name}
          placeholder={type.kind}
          onChange={(e) => setName(e.target.value)}
        />
      </td>
      <td>
        <input
          className="ga-tt-color"
          type="color"
          value={color}
          title={color}
          onChange={(e) => setColor(e.target.value)}
        />
      </td>
      <td className="ga-tt-center">
        <input
          type="checkbox"
          checked={passable}
          title={t('Whether characters can walk on this ground')}
          onChange={(e) => setPassable(e.target.checked)}
        />
      </td>
      <td>
        <input
          className={'ga-input ga-tt-speed' + (speedBad ? ' ga-tt-invalid' : '')}
          type="number"
          min={SPEED_MIN}
          max={SPEED_MAX}
          step={SPEED_STEP}
          value={speed}
          aria-invalid={speedBad}
          title={speedBad
            ? t('Speed must be between {min} and {max}')
              .replace('{min}', String(SPEED_MIN)).replace('{max}', String(SPEED_MAX))
            : t('Movement speed on this ground, 1 = normal')}
          onChange={(e) => setSpeed(e.target.value)}
        />
      </td>
      <td className="ga-tt-center">
        <button
          type="button"
          className={'ga-btn ga-btn-sm' + (draftScatter ? ' ga-tt-scatter-on' : '')}
          aria-expanded={scatterOpen}
          title={t('What this ground grows — density, tuft height and an optional prop model')}
          onClick={() => setScatterOpen((o) => !o)}
        >
          {draftScatter
            ? t('{n}/100 m²').replace('{n}', String(draftScatter.density_per_100m2))
            : t('off')}
          {scatterOpen ? ' ▾' : ' ▸'}
        </button>
      </td>
      <td>
        <span className={'ga-source ga-source-' + source}>
          {source === 'world' ? t('world') : t('shared')}
        </span>
      </td>
      <td className="ga-tt-actions">
        <button
          type="button"
          className="ga-btn ga-btn-sm ga-btn-primary"
          disabled={!dirty || speedBad || densityBad || tuftBad || busy}
          title={source === 'shared'
            ? t('Save — this creates a world override of the shared entry')
            : t('Save the world override')}
          onClick={() => { void save() }}
        >
          {t('Save')}
        </button>
        {source === 'world' ? (
          armedReset ? (
            <>
              <button
                type="button"
                className="ga-btn ga-btn-sm ga-btn-danger"
                disabled={busy}
                onClick={() => { onArmReset(false); onReset() }}
              >
                {t('Really reset')}
              </button>
              <button
                type="button"
                className="ga-btn ga-btn-sm"
                onClick={() => onArmReset(false)}
              >
                {t('Cancel')}
              </button>
            </>
          ) : (
            <button
              type="button"
              className="ga-btn ga-btn-sm"
              disabled={busy}
              title={t('Remove the world override — the shared default comes back. A kind that exists only in this world is deleted.')}
              onClick={() => onArmReset(true)}
            >
              {t('Reset')}
            </button>
          )
        ) : null}
      </td>
    </tr>
    {scatterOpen ? (
      <tr className="ga-tt-scatter-row">
        <td />
        <td colSpan={7}>
          <div className="ga-tt-scatter">
            <label>
              {t('Density (per 100 m²)')}
              <input
                className={'ga-input ga-tt-speed' + (densityBad ? ' ga-tt-invalid' : '')}
                type="number"
                min={0}
                step={1}
                value={density}
                placeholder="0"
                aria-invalid={densityBad}
                title={t('How many instances stand on 100 m² of this ground. Empty or 0 = nothing is scattered.')}
                onChange={(e) => setDensity(e.target.value)}
              />
            </label>
            <label>
              {t('Tuft height (m)')}
              <input
                className={'ga-input ga-tt-speed' + (tuftBad ? ' ga-tt-invalid' : '')}
                type="number"
                min={0}
                step={0.05}
                value={tuftH}
                placeholder="0.55"
                aria-invalid={tuftBad}
                title={t('Height of the built-in tuft. Ignored once a prop model is chosen.')}
                onChange={(e) => setTuftH(e.target.value)}
              />
            </label>
            <label className="ga-tt-scatter-model">
              {t('Prop model')}
              <select
                className="ga-input ga-tt-input"
                value={model}
                title={t('A prop from the library replaces the tuft. Only props that already have a mesh are offered.')}
                onChange={(e) => setModel(e.target.value)}
              >
                <option value="">{t('Tuft (no model)')}</option>
                {props.map((p) => (
                  <option key={p.id} value={propModelUrl(p.id)}>
                    {p.name || p.id}
                  </option>
                ))}
                {/* A model URL that is not in the library — hand-authored, or
                    a prop that has since been deleted. It stays selected and
                    visible instead of silently falling back to the tuft. */}
                {modelKnown ? null : <option value={model}>{model}</option>}
              </select>
            </label>
            <span className="ga-tt-hint">
              {t('Instances are placed deterministically per area, so the same ground always looks the same. Density counts per 100 m² of the painted area.')}
            </span>
          </div>
        </td>
      </tr>
    ) : null}
    </>
  )
}

export interface TerrainTypesDialogProps {
  types: TerrainType[]
  sources: Record<string, 'shared' | 'world'>
  /** Refetch the catalog in `MapTab` — palette and area colours follow it. */
  onChanged: () => Promise<void> | void
  onClose: () => void
}

export function TerrainTypesDialog({
  types, sources, onChanged, onClose,
}: TerrainTypesDialogProps) {
  const { t } = useI18n()
  const { toast } = useToast()
  const [busy, setBusy] = useState(false)
  const [armedReset, setArmedReset] = useState('')

  // The new-kind row. `kind` is the only field with a shape to get wrong —
  // everything else is a picker or gets clamped by the server.
  const [newKind, setNewKind] = useState('')
  const [newName, setNewName] = useState('')
  const [newColor, setNewColor] = useState(DEFAULT_COLOR)
  const [newPassable, setNewPassable] = useState(true)
  const [newSpeed, setNewSpeed] = useState('1')

  // The prop library for the scatter model picker — fetched once, only the
  // props that actually have a mesh. A failed fetch leaves the picker with
  // just the tuft option; it must never block editing colours and speeds.
  const [propList, setPropList] = useState<PropRef[]>([])
  useEffect(() => {
    let alive = true
    loadPropAssets()
      .then((list) => {
        if (!alive) return
        setPropList(list.filter((p) => p.has_model !== false)
          .sort((a, b) => (a.name || a.id).localeCompare(b.name || b.id)))
      })
      .catch(() => { /* no props to pick from — the tuft still works */ })
    return () => { alive = false }
  }, [])

  const putType = useCallback(async (draft: TypeDraft): Promise<TerrainType | null> => {
    setBusy(true)
    try {
      const r = await apiPut<{ type?: TerrainType }>(
        `/world/terrain-types/${encodeURIComponent(draft.kind)}`,
        {
          name: draft.name, color: draft.color, passable: draft.passable,
          speed_factor: draft.speed_factor, meta: draft.meta || {},
        })
      await Promise.resolve(onChanged())
      return r?.type || null
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
      return null
    } finally {
      setBusy(false)
    }
  }, [onChanged, t, toast])

  const resetType = useCallback(async (kind: string) => {
    setBusy(true)
    try {
      await apiDelete(`/world/terrain-types/${encodeURIComponent(kind)}`)
      await Promise.resolve(onChanged())
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setBusy(false)
    }
  }, [onChanged, t, toast])

  const kindClean = newKind.trim().toLowerCase()
  const kindBad = kindClean !== '' && !KIND_RE.test(kindClean)
  const kindTaken = !!kindClean && types.some((ty) => ty.kind === kindClean)
  const newSpeedNum = parseFloat(newSpeed)
  const newSpeedBad = !Number.isFinite(newSpeedNum)
    || newSpeedNum < SPEED_MIN || newSpeedNum > SPEED_MAX
  const canAdd = !!kindClean && !kindBad && !kindTaken && !newSpeedBad && !busy

  const addType = useCallback(async () => {
    const saved = await putType({
      kind: kindClean, name: newName.trim(), color: newColor,
      passable: newPassable, speed_factor: newSpeedNum, meta: {},
    })
    if (!saved) return
    setNewKind('')
    setNewName('')
    setNewColor(DEFAULT_COLOR)
    setNewPassable(true)
    setNewSpeed('1')
  }, [kindClean, newColor, newName, newPassable, newSpeedNum, putType])

  return (
    <div className="ga-modal-backdrop" onMouseDown={onClose}>
      <div className="ga-modal ga-tt-modal" onMouseDown={(e) => e.stopPropagation()}>
        <div className="ga-modal-header">
          <span>{t('Terrain types')}</span>
          <button type="button" className="ga-modal-close" onClick={onClose}>×</button>
        </div>
        <div className="ga-modal-body">
          <div className="ga-tt-hint">
            {t('The kind should match a surface-texture kind so the 3D ground can use a real texture — the 2D map only ever shows the colour.')}
          </div>
          <table className="ga-tt-table">
            <thead>
              <tr>
                <th>{t('Kind')}</th>
                <th>{t('Name')}</th>
                <th>{t('Colour')}</th>
                <th className="ga-tt-center">{t('Passable')}</th>
                <th>{t('Speed')}</th>
                <th className="ga-tt-center">{t('Scatter')}</th>
                <th>{t('Source')}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {types.length === 0 ? (
                <tr>
                  <td colSpan={8} className="ga-map-tray-empty">
                    {t('No terrain types')}
                  </td>
                </tr>
              ) : types.map((ty) => {
                const src = sources[ty.kind] === 'world' ? 'world' : 'shared'
                // The source is part of the key on purpose: a `Reset` swaps the
                // whole entry for the shared one underneath it, and a row that
                // kept its draft would go on showing the values that were just
                // deleted. Crossing that line remounts the row with what the
                // server now says. A save on a row that is ALREADY an override
                // does not cross it — that row refills itself from the answer.
                return (
                  <TypeRow
                    key={ty.kind + ':' + src}
                    type={ty}
                    source={src}
                    props={propList}
                    busy={busy}
                    armedReset={armedReset === ty.kind}
                    onArmReset={(a) => setArmedReset(a ? ty.kind : '')}
                    onSave={putType}
                    onReset={() => { void resetType(ty.kind) }}
                  />
                )
              })}
            </tbody>
            <tfoot>
              <tr>
                <td>
                  <input
                    className={'ga-input ga-tt-input ga-tt-kind'
                      + (kindBad || kindTaken ? ' ga-tt-invalid' : '')}
                    value={newKind}
                    placeholder={t('e.g. gravel')}
                    aria-invalid={kindBad || kindTaken}
                    maxLength={40}
                    onChange={(e) => setNewKind(e.target.value)}
                  />
                </td>
                <td>
                  <input
                    className="ga-input ga-tt-input"
                    maxLength={NAME_MAX}
                    value={newName}
                    placeholder={kindClean || t('Name')}
                    onChange={(e) => setNewName(e.target.value)}
                  />
                </td>
                <td>
                  <input
                    className="ga-tt-color"
                    type="color"
                    value={newColor}
                    title={newColor}
                    onChange={(e) => setNewColor(e.target.value)}
                  />
                </td>
                <td className="ga-tt-center">
                  <input
                    type="checkbox"
                    checked={newPassable}
                    onChange={(e) => setNewPassable(e.target.checked)}
                  />
                </td>
                <td>
                  <input
                    className={'ga-input ga-tt-speed' + (newSpeedBad ? ' ga-tt-invalid' : '')}
                    type="number"
                    min={SPEED_MIN}
                    max={SPEED_MAX}
                    step={SPEED_STEP}
                    value={newSpeed}
                    aria-invalid={newSpeedBad}
                    onChange={(e) => setNewSpeed(e.target.value)}
                  />
                </td>
                <td />
                <td className="ga-tt-actions">
                  <button
                    type="button"
                    className="ga-btn ga-btn-sm ga-btn-primary"
                    disabled={!canAdd}
                    onClick={() => { void addType() }}
                  >
                    {t('Add')}
                  </button>
                </td>
              </tr>
              <tr>
                <td colSpan={8} className="ga-tt-newhint">
                  {kindBad
                    ? t('A kind is lowercase letters, digits, “_” and “-”, starts with a letter or digit, at most 40 characters.')
                    : kindTaken
                      ? t('“{kind}” already exists — edit it in the table above.')
                        .replace('{kind}', kindClean)
                      : t('New kinds are stored in this world only.')}
                </td>
              </tr>
            </tfoot>
          </table>
        </div>
        <div className="ga-modal-footer">
          <button type="button" className="ga-btn ga-btn-sm" onClick={onClose}>
            {t('Close')}
          </button>
        </div>
      </div>
    </div>
  )
}
