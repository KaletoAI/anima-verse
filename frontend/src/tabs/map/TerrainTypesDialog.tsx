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
 * What a ground GROWS is deliberately NOT here (finding B17). It hung on the
 * type until then, which could only ever say "all forest everywhere grows this
 * one tree"; it is authored per painted AREA now, in the area chip of the map
 * itself — where the shape one means is already selected and the preview shows
 * what it does.
 *
 * What a ground is CROSSED like, on the other hand, belongs to the type and is
 * edited here: the pace (`speed_factor`) and, since finding 3 of the E8
 * acceptance, the movement animation (`meta.move_anim` — "swim" on water).
 * Both count everywhere the ground is painted, inside a placed location as
 * much as out in the wilderness; only the PASSABILITY is a wilderness question
 * (§ A15, "footprint wins").
 *
 * And what a ground is SHAPED like: the micro-relief (`meta.relief_amplitude_m`
 * / `meta.relief_wave_m`, § A16.2) — random small hills baked into the world
 * heightfield wherever this kind is painted. It is authored per KIND, not per
 * area, because it describes what the ground is, and it is one editing step
 * away from making a slope nobody can climb: the amplitude field says in its
 * hint how steep its number gets over one 4 m grid step.
 */
import { useCallback, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiDelete, apiPut } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import type { TerrainType } from './mapTypes'
// The app's ONE fallback grey — the server's `terrain_types.DEFAULT_COLOR`,
// held in `TerrainLayer` because that is where an unknown kind is drawn. A
// second literal here would be a second opinion about the same server value.
import { UNKNOWN_COLOR as DEFAULT_COLOR } from './TerrainLayer'

/** Server mirrors — `_KIND_RE`, `SPEED_MIN/MAX`, the `move_anim` cap and the
 *  two relief clamps of `terrain_types.py`. */
const KIND_RE = /^[a-z0-9][a-z0-9_-]{0,39}$/
const SPEED_MIN = 0
const SPEED_MAX = 2
const SPEED_STEP = 0.05
const NAME_MAX = 60
const MOVE_ANIM_MAX = 40
const RELIEF_AMP_MIN = 0.05
const RELIEF_AMP_MAX = 2
const RELIEF_AMP_STEP = 0.05
const RELIEF_WAVE_MIN = 8
const RELIEF_WAVE_MAX = 200
const RELIEF_WAVE_STEP = 1
/** `terrain_types.DEFAULT_RELIEF_WAVE_M` — what an amplitude without a wave
 *  gets, named in the hint so an empty field is not a mystery. */
const RELIEF_WAVE_DEFAULT = 32
/** `heightfield.DEFAULT_STEP_M` — the grid step the steepness hint divides by.
 *  It is the FINEST step; a coarsened grid only ever makes the slope gentler,
 *  so the number quoted here is the worst case. */
const GRID_STEP_M = 4

/** Read the string meta key this dialog owns. Everything else in `meta`
 *  belongs to whoever wrote it and travels along untouched. */
function moveAnimOf(type: TerrainType): string {
  const raw = (type.meta as { move_anim?: unknown } | undefined)?.move_anim
  return typeof raw === 'string' ? raw : ''
}

/** Read one optional NUMERIC meta key as the string its input shows — a
 *  missing key is the empty field, which is exactly how "no relief" is
 *  authored. */
function metaNumOf(type: TerrainType, key: string): string {
  const raw = (type.meta as Record<string, unknown> | undefined)?.[key]
  return typeof raw === 'number' && Number.isFinite(raw) ? String(raw) : ''
}

/** One optional numeric key, IN PLACE — written or GONE. Mirrors the server's
 *  `_clamped_meta_number`: nothing, junk or a non-positive number leaves NO
 *  key behind, so no reader has to tell "authored as 0" from "not authored". */
function setMetaNum(meta: Record<string, unknown>, key: string,
                    raw: string): void {
  const num = parseFloat(raw)
  if (Number.isFinite(num) && num > 0) meta[key] = num
  else delete meta[key]
}

/** Whether an optional numeric field differs from what is stored, compared as
 *  NUMBERS — "0.40" is not a change to 0.4, and empty, junk and 0 are all the
 *  same "no value" the server keeps as a missing key. */
function numChanged(raw: string, stored: string): boolean {
  const typed = parseFloat(raw)
  const known = parseFloat(stored)
  return (Number.isFinite(typed) && typed > 0 ? typed : null)
    !== (Number.isFinite(known) && known > 0 ? known : null)
}

/** The `meta` keys this dialog owns, as their fields hold them. */
interface OwnedMeta {
  moveAnim: string
  reliefAmp: string
  reliefWave: string
}

/** `meta` with the owned keys written — or with the KEY REMOVED where the
 *  field is empty, which is what the server stores too ("no animation" is
 *  never an empty string a reader has to test for). The rest of `meta` is
 *  copied through untouched: the route is a full replace. */
function withOwnedMeta(meta: Record<string, unknown> | undefined,
                       own: OwnedMeta): Record<string, unknown> {
  const next = { ...(meta || {}) }
  const clean = own.moveAnim.trim()
  if (clean) next.move_anim = clean
  else delete next.move_anim
  setMetaNum(next, 'relief_amplitude_m', own.reliefAmp)
  setMetaNum(next, 'relief_wave_m', own.reliefWave)
  return next
}

/** The steepness hint of the amplitude field: the worst case two neighbouring
 *  support points can build out of the noise alone is `atan(2·amp / step)` —
 *  45° at the clamp of 2 m. An empty field quotes that clamp, so the sentence
 *  says what the limit means before anything is typed.
 *
 *  THE TYPED NUMBER IS CLAMPED FIRST, like the server clamps it on save: the
 *  sentence describes what WILL BE STORED, not what stands in the field. A
 *  typed 5 promised "5 m … 68°" while 2 m/45° is what arrives, and a typed
 *  0.02 promised 1° where 0.05 is stored. */
function amplitudeHint(t: (s: string) => string, raw: string): string {
  const typed = parseFloat(raw)
  const amp = Number.isFinite(typed) && typed > 0
    ? Math.min(RELIEF_AMP_MAX, Math.max(RELIEF_AMP_MIN, typed))
    : RELIEF_AMP_MAX
  const deg = Math.round(Math.atan(2 * amp / GRID_STEP_M) * 180 / Math.PI)
  return t('Height of the random hills of this ground, in metres — empty = flat. {amp} m builds slopes of up to {deg}° over one {step} m grid step.')
    .replace('{amp}', String(amp))
    .replace('{deg}', String(deg))
    .replace('{step}', String(GRID_STEP_M))
}

/** The wavelength hint — how wide one swell is, plus the default an amplitude
 *  without a wave falls back to. */
function waveHint(t: (s: string) => string): string {
  return t('Width of one hill of this ground, in metres ({min}–{max}) — empty = {def} m.')
    .replace('{min}', String(RELIEF_WAVE_MIN))
    .replace('{max}', String(RELIEF_WAVE_MAX))
    .replace('{def}', String(RELIEF_WAVE_DEFAULT))
}

/** What one row sends — the same shape it reads. `meta` travels along
 *  untouched: the route is a full replace, so a body without it would blank
 *  whatever put something there. */
type TypeDraft = TerrainType

interface TypeRowProps {
  type: TerrainType
  source: 'shared' | 'world'
  busy: boolean
  armedReset: boolean
  onArmReset: (armed: boolean) => void
  onSave: (draft: TypeDraft) => Promise<TerrainType | null>
  onReset: () => void
}

function TypeRow({
  type, source, busy, armedReset, onArmReset, onSave, onReset,
}: TypeRowProps) {
  const { t } = useI18n()
  const [name, setName] = useState(type.name || '')
  const [color, setColor] = useState(type.color || DEFAULT_COLOR)
  const [passable, setPassable] = useState(!!type.passable)
  const [speed, setSpeed] = useState(String(type.speed_factor))
  const [moveAnim, setMoveAnim] = useState(moveAnimOf(type))
  const [reliefAmp, setReliefAmp] = useState(metaNumOf(type, 'relief_amplitude_m'))
  const [reliefWave, setReliefWave] = useState(metaNumOf(type, 'relief_wave_m'))

  const speedNum = parseFloat(speed)
  const speedBad = !Number.isFinite(speedNum)
    || speedNum < SPEED_MIN || speedNum > SPEED_MAX

  // A field the user cannot fix by typing further is not "dirty", it is
  // wrong — but it still has to enable `Save` so the marking is reachable.
  const dirty = name !== (type.name || '')
    || color !== (type.color || DEFAULT_COLOR)
    || passable !== !!type.passable
    || moveAnim.trim() !== moveAnimOf(type)
    || numChanged(reliefAmp, metaNumOf(type, 'relief_amplitude_m'))
    || numChanged(reliefWave, metaNumOf(type, 'relief_wave_m'))
    || (speedBad ? speed !== String(type.speed_factor) : speedNum !== type.speed_factor)

  const save = useCallback(async () => {
    if (speedBad) return
    // `meta` is free-form and belongs to whoever wrote it — this dialog owns
    // exactly THREE keys in it and hands the rest back untouched. The relief
    // numbers are sent unclamped on purpose: the server clamps, and the row
    // refills from its answer, so a typed 5 shows up as the stored 2.
    const saved = await onSave({
      kind: type.kind, name, color, passable,
      speed_factor: speedNum,
      meta: withOwnedMeta(type.meta, { moveAnim, reliefAmp, reliefWave }),
    })
    if (!saved) return
    setName(saved.name || '')
    setColor(saved.color || DEFAULT_COLOR)
    setPassable(!!saved.passable)
    setSpeed(String(saved.speed_factor))
    setMoveAnim(moveAnimOf(saved))
    setReliefAmp(metaNumOf(saved, 'relief_amplitude_m'))
    setReliefWave(metaNumOf(saved, 'relief_wave_m'))
  }, [color, moveAnim, name, onSave, passable, reliefAmp, reliefWave, speedBad,
      speedNum, type])

  return (
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
          className={'ga-input ga-tt-num' + (speedBad ? ' ga-tt-invalid' : '')}
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
      <td>
        <input
          className="ga-input ga-tt-input"
          maxLength={MOVE_ANIM_MAX}
          value={moveAnim}
          placeholder={t('walk / run')}
          title={t('Animation clip a moving figure plays on this ground instead of walking — e.g. “swim” on water. Empty = walk and run as usual.')}
          onChange={(e) => setMoveAnim(e.target.value)}
        />
      </td>
      <td>
        <input
          className="ga-input ga-tt-num"
          type="number"
          min={RELIEF_AMP_MIN}
          max={RELIEF_AMP_MAX}
          step={RELIEF_AMP_STEP}
          value={reliefAmp}
          placeholder={t('flat')}
          title={amplitudeHint(t, reliefAmp)}
          onChange={(e) => setReliefAmp(e.target.value)}
        />
      </td>
      <td>
        <input
          className="ga-input ga-tt-num"
          type="number"
          min={RELIEF_WAVE_MIN}
          max={RELIEF_WAVE_MAX}
          step={RELIEF_WAVE_STEP}
          value={reliefWave}
          placeholder={String(RELIEF_WAVE_DEFAULT)}
          title={waveHint(t)}
          onChange={(e) => setReliefWave(e.target.value)}
        />
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
          disabled={!dirty || speedBad || busy}
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
  const [newMoveAnim, setNewMoveAnim] = useState('')
  const [newReliefAmp, setNewReliefAmp] = useState('')
  const [newReliefWave, setNewReliefWave] = useState('')

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
      passable: newPassable, speed_factor: newSpeedNum,
      meta: withOwnedMeta({}, {
        moveAnim: newMoveAnim,
        reliefAmp: newReliefAmp,
        reliefWave: newReliefWave,
      }),
    })
    if (!saved) return
    setNewKind('')
    setNewName('')
    setNewColor(DEFAULT_COLOR)
    setNewPassable(true)
    setNewSpeed('1')
    setNewMoveAnim('')
    setNewReliefAmp('')
    setNewReliefWave('')
  }, [kindClean, newColor, newMoveAnim, newName, newPassable, newReliefAmp,
      newReliefWave, newSpeedNum, putType])

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
          {/* A type used to declare what its ground grows. It moved to the
              painted AREA, and old entries are simply not read any more —
              which looks exactly like "my trees are gone" unless it is said
              out loud, here, where they were authored. */}
          <div className="ga-tt-hint">
            {t('Scatter used to be set here. It now belongs to the painted area — select an area on the map and open “Scatter” in its chip. Anything set here before has no effect any more.')}
          </div>
          <table className="ga-tt-table">
            <thead>
              <tr>
                <th>{t('Kind')}</th>
                <th>{t('Name')}</th>
                <th>{t('Colour')}</th>
                <th className="ga-tt-center">{t('Passable')}</th>
                <th>{t('Speed')}</th>
                <th>{t('Move animation')}</th>
                <th>{t('Relief amplitude (m)')}</th>
                <th>{t('Relief wavelength (m)')}</th>
                <th>{t('Source')}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {types.length === 0 ? (
                <tr>
                  <td colSpan={10} className="ga-map-tray-empty">
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
                    title={t('Whether characters can walk on this ground')}
                    onChange={(e) => setNewPassable(e.target.checked)}
                  />
                </td>
                <td>
                  <input
                    className={'ga-input ga-tt-num' + (newSpeedBad ? ' ga-tt-invalid' : '')}
                    type="number"
                    min={SPEED_MIN}
                    max={SPEED_MAX}
                    step={SPEED_STEP}
                    value={newSpeed}
                    aria-invalid={newSpeedBad}
                    title={newSpeedBad
                      ? t('Speed must be between {min} and {max}')
                        .replace('{min}', String(SPEED_MIN)).replace('{max}', String(SPEED_MAX))
                      : t('Movement speed on this ground, 1 = normal')}
                    onChange={(e) => setNewSpeed(e.target.value)}
                  />
                </td>
                <td>
                  <input
                    className="ga-input ga-tt-input"
                    maxLength={MOVE_ANIM_MAX}
                    value={newMoveAnim}
                    placeholder={t('walk / run')}
                    title={t('Animation clip a moving figure plays on this ground instead of walking — e.g. “swim” on water. Empty = walk and run as usual.')}
                    onChange={(e) => setNewMoveAnim(e.target.value)}
                  />
                </td>
                <td>
                  <input
                    className="ga-input ga-tt-num"
                    type="number"
                    min={RELIEF_AMP_MIN}
                    max={RELIEF_AMP_MAX}
                    step={RELIEF_AMP_STEP}
                    value={newReliefAmp}
                    placeholder={t('flat')}
                    title={amplitudeHint(t, newReliefAmp)}
                    onChange={(e) => setNewReliefAmp(e.target.value)}
                  />
                </td>
                <td>
                  <input
                    className="ga-input ga-tt-num"
                    type="number"
                    min={RELIEF_WAVE_MIN}
                    max={RELIEF_WAVE_MAX}
                    step={RELIEF_WAVE_STEP}
                    value={newReliefWave}
                    placeholder={String(RELIEF_WAVE_DEFAULT)}
                    title={waveHint(t)}
                    onChange={(e) => setNewReliefWave(e.target.value)}
                  />
                </td>
                {/* Source: a new kind is always this world's own. */}
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
                <td colSpan={10} className="ga-tt-newhint">
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
