/**
 * TerrainDetail — one kind of ground, edited as a form of GROUPED sections.
 *
 * It is the whole of what a terrain type is, in the order one thinks about it:
 * what it IS (Basics), what it LOOKS like (Surface), what it does to a figure
 * on it (Movement & water), what shape it has (Relief), and what grows on it
 * (Vegetation). It replaces the two-row table of the map editor's old type
 * dialog — that one had run out of columns at nine fields and had to hide the
 * tenth in a second row; a section is the place a tenth field can go without
 * anybody having to widen anything.
 *
 * The catalog is TWO layers with override-replace per kind: the shared seed
 * (`shared/terrain/types.json`) ships the defaults, a world row replaces the
 * whole entry of the same kind. That is why there is no "edit the seed" here —
 * saving a seed row simply CREATES the world override, and "Reset to seed"
 * deletes that override so the seed entry comes back. A kind that never existed
 * in the seed has nothing to fall back to: resetting it removes it for good,
 * which is what the confirmation step is for.
 *
 * Nothing is edited live. The draft writes only on `Save`, because a colour
 * picker that PUTs on every drag would put a hundred writes on the wire for one
 * decision. The saved entry is refilled from the SERVER's answer (`PUT` returns
 * the sanitized entry), so a clamped speed or a truncated name shows what was
 * stored instead of what was typed.
 *
 * The limits mirror `app/core/terrain_types.py`. They are a copy, not a second
 * opinion: the server still sanitizes every field, this only spares the user a
 * 400 for something a regex could have said in place.
 *
 * What a ground GROWS (a scatter LIST) is deliberately NOT here (finding B17).
 * It hung on the type until then, which could only ever say "all forest
 * everywhere grows this one tree"; it is authored per painted AREA now, in the
 * area chip of the map itself — said out loud in the Vegetation section,
 * because that is where it used to be typed.
 */
import { useCallback, useState } from 'react'
import { DetailToolbar } from '../../components/DetailToolbar'
import { Field } from '../../components/Field'
import { useI18n } from '../../i18n/I18nProvider'
import { reliefWarnAmpM } from '../map/heightMath'
import type { TerrainType } from '../map/mapTypes'
import type { SurfaceKind } from '../world/worldTypes'
// The app's ONE fallback grey — the server's `terrain_types.DEFAULT_COLOR`,
// held in `TerrainLayer` because that is where an unknown kind is drawn. A
// second literal here would be a second opinion about the same server value.
import { UNKNOWN_COLOR as DEFAULT_COLOR } from '../map/TerrainLayer'

/** Server mirrors — `_KIND_RE`, `SPEED_MIN/MAX`, the cap of the two animation
 *  keys and the two relief clamps of `terrain_types.py`. */
const KIND_RE = /^[a-z0-9][a-z0-9_-]{0,39}$/
const KIND_MAX = 40
const SPEED_MIN = 0
const SPEED_MAX = 2
const SPEED_STEP = 0.05
const NAME_MAX = 60
const ANIM_MAX = 40
const RELIEF_AMP_MIN = 0.05
const RELIEF_AMP_MAX = 2
const RELIEF_AMP_STEP = 0.05
// `terrain_types.RELIEF_WAVE_MIN` = 2 × `heightfield.TILE_STEP_M` (Nyquist).
// It halved on 2026-08-14 with the tile step, which is what made a 4 m swell
// authorable at all.
const RELIEF_WAVE_MIN = 4
const RELIEF_WAVE_MAX = 200
const RELIEF_WAVE_STEP = 1
const SINK_MIN = 0
const SINK_MAX = 1.5
const SINK_STEP = 0.05
const SWAY_MIN = 0.01
const SWAY_MAX = 0.5
const SWAY_STEP = 0.01
// `terrain_types.UNDERGROWTH_MIN/MAX`. The floor is 0 and 0 means "no key",
// exactly like an empty field — there is no smallest visible share here, the
// layer simply gets thinner.
const UNDERGROWTH_MIN = 0
const UNDERGROWTH_MAX = 1
const UNDERGROWTH_STEP = 0.05
/** The shared seed's two undergrown kinds, named in the hint so the number in
 *  an empty field is not a mystery (`shared/terrain/types.json`). */
const UNDERGROWTH_SEED_FOREST = 0.6
const UNDERGROWTH_SEED_GRASS = 0.3
/** `terrain_types.DEFAULT_RELIEF_WAVE_M` — what an amplitude without a wave
 *  gets, named in the hint so an empty field is not a mystery. */
const RELIEF_WAVE_DEFAULT = 32
/** `heightfield.TILE_STEP_M` — the FALLBACK grid step of the steepness hint,
 *  for the moment before the server has answered one. It is the step of the
 *  fine height TILES, i.e. the raster every walk rule reads and the FINEST
 *  there is; the coarsenable overview only ever makes a slope gentler, so the
 *  number quoted here is the worst case. The live value comes from the server
 *  (`GET /world/height-areas` → `tile_step_m`), because a pinned one had to be
 *  hand-edited when the tiles halved on 2026-08-14 and the hint's angle rose
 *  with it (2 m of amplitude now reach 63° over one cell, not 45°). */
const GRID_STEP_M = 2

/** Read one of the string meta keys this form owns. Everything else in `meta`
 *  belongs to whoever wrote it and travels along untouched. */
function metaStrOf(type: TerrainType | null, key: string): string {
  const raw = (type?.meta as Record<string, unknown> | undefined)?.[key]
  return typeof raw === 'string' ? raw : ''
}

/** Read one optional NUMERIC meta key as the string its input shows — a
 *  missing key is the empty field, which is exactly how "no relief" is
 *  authored. */
function metaNumOf(type: TerrainType | null, key: string): string {
  const raw = (type?.meta as Record<string, unknown> | undefined)?.[key]
  return typeof raw === 'number' && Number.isFinite(raw) ? String(raw) : ''
}

/** One optional string key, IN PLACE — trimmed or GONE. The server's
 *  `_trimmed_meta_string`: "no animation" is a missing key, never an empty
 *  string a reader has to test for. */
function setMetaStr(meta: Record<string, unknown>, key: string,
                    raw: string): void {
  const clean = raw.trim()
  if (clean) meta[key] = clean
  else delete meta[key]
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

/** The `meta` keys this form owns, as their fields hold them. */
interface OwnedMeta {
  moveAnim: string
  idleAnim: string
  moveSink: string
  idleSink: string
  reliefAmp: string
  reliefWave: string
  sway: string
  undergrowth: string
}

/** `meta` with the owned keys written — or with the KEY REMOVED where the
 *  field is empty, which is what the server stores too ("no animation" is
 *  never an empty string a reader has to test for). The rest of `meta` is
 *  copied through untouched: the route is a full replace. */
function withOwnedMeta(meta: Record<string, unknown> | undefined,
                       own: OwnedMeta): Record<string, unknown> {
  const next = { ...(meta || {}) }
  setMetaStr(next, 'move_anim', own.moveAnim)
  setMetaStr(next, 'idle_anim', own.idleAnim)
  setMetaNum(next, 'move_sink_m', own.moveSink)
  setMetaNum(next, 'idle_sink_m', own.idleSink)
  setMetaNum(next, 'relief_amplitude_m', own.reliefAmp)
  setMetaNum(next, 'relief_wave_m', own.reliefWave)
  setMetaNum(next, 'sway_m', own.sway)
  setMetaNum(next, 'undergrowth', own.undergrowth)
  return next
}

/** The steepness hint of the amplitude field: the worst case two neighbouring
 *  support points can build out of the noise alone is `atan(2·amp / step)` —
 *  63° at the clamp of 2 m over the 2 m tile step. An empty field quotes that
 *  clamp, so the sentence says what the limit means before anything is typed.
 *
 *  THE TYPED NUMBER IS CLAMPED FIRST, like the server clamps it on save: the
 *  sentence describes what WILL BE STORED, not what stands in the field. A
 *  typed 5 promised "5 m … 79°" while 2 m/63° is what arrives, and a typed
 *  0.02 promised 1° where 0.05 is stored. */
function amplitudeHint(t: (s: string) => string, raw: string,
                       stepM: number): string {
  const typed = parseFloat(raw)
  const amp = Number.isFinite(typed) && typed > 0
    ? Math.min(RELIEF_AMP_MAX, Math.max(RELIEF_AMP_MIN, typed))
    : RELIEF_AMP_MAX
  const deg = Math.round(Math.atan(2 * amp / stepM) * 180 / Math.PI)
  return t('Height of the random hills of this ground, in metres — empty = flat. {amp} m builds slopes of up to {deg}° over one {step} m grid step.')
    .replace('{amp}', String(amp))
    .replace('{deg}', String(deg))
    .replace('{step}', String(stepM))
}

/** The steepness WARNING of the amplitude field: from `reliefWarnAmpM` on, the
 *  worst case above is steeper than the walk gate lets anyone climb, so single
 *  spots of that ground turn into obstacles. Informative only — the clamp
 *  stays at 2 m (user decision 2026-08-14), nothing is blocked or corrected.
 *  The typed number is clamped first, exactly like the hint above it: a typed
 *  5 is stored as 2, and warning about the 5 would name a ground nobody gets.
 *  `''` = nothing to warn about (flat, below the threshold, or no threshold
 *  because the server has not answered a tile step yet). */
function amplitudeWarn(t: (s: string) => string, raw: string,
                       warnAmpM: number | null): string {
  if (warnAmpM === null) return ''
  const typed = parseFloat(raw)
  if (!Number.isFinite(typed) || typed <= 0) return ''
  const amp = Math.min(RELIEF_AMP_MAX, Math.max(RELIEF_AMP_MIN, typed))
  if (amp <= warnAmpM) return ''
  return t('Above ~{max} m the random hills get steeper than walkers can climb — spots of this ground become impassable.')
    .replace('{max}', warnAmpM.toFixed(2))
}

/** The MOVE sink hint — what the number does, where it stops, and why it is
 *  not the same number as the one next to it. */
function moveSinkHint(t: (s: string) => string): string {
  return t('How deep a figure stands IN this ground while it MOVES over it, in metres (0–{max}) — empty = on top of it. A swimmer lies flat, so its lowest point is a knee just under the body; the animation alone puts that knee on the surface and the swimmer on the lake.')
    .replace('{max}', String(SINK_MAX))
}

/** The IDLE sink hint. Two fields because the two poses hang differently in
 *  the water — said here, where the second number is typed. */
function idleSinkHint(t: (s: string) => string): string {
  return t('The same while the figure WAITS on this ground, in metres (0–{max}) — a separate number, because the waiting pose hangs differently: someone treading water stands upright and its lowest point is a foot a whole body length down. Only in force where an idle animation is set above.')
    .replace('{max}', String(SINK_MAX))
}

/** The sway hint — what bends, how far, and what does NOT bend. The last part
 *  is the one the field cannot show: a painted lake is animated by its surface
 *  class, and a number typed here would never move the ground itself. */
function swayHint(t: (s: string) => string): string {
  return t('How far what GROWS on this ground bends in the wind, in metres ({min}–{max}) — empty = it stands still. The tip carries the whole number, the foot none of it, and every plant has its own phase. Counts for all scatter of an area of this kind, tufts and models alike; the ground surface itself is not moved by it.')
    .replace('{min}', String(SWAY_MIN))
    .replace('{max}', String(SWAY_MAX))
}

/** The undergrowth hint — what the number does, that 0 and empty are the same
 *  bare ground, and where the seeded values come from. The last part is the
 *  one the field cannot show: a world row REPLACES the seed entry whole
 *  (override-replace per kind), so the seeded 0.6 of `forest` is gone the
 *  moment this world saves its own forest row without a value here. */
function undergrowthHint(t: (s: string) => string): string {
  return t('How much grows on this ground by itself, without any scatter being authored: 0–{max} of the full tuft density, at knee height between the props. 0 or empty = bare ground. Seeded {forest} on forest and {grass} on grass — saving a row here replaces the shared entry whole, so an empty field really does clear that growth away.')
    .replace('{max}', String(UNDERGROWTH_MAX))
    .replace('{forest}', String(UNDERGROWTH_SEED_FOREST))
    .replace('{grass}', String(UNDERGROWTH_SEED_GRASS))
}

/** The wavelength hint — how wide one swell is, plus the default an amplitude
 *  without a wave falls back to. */
function waveHint(t: (s: string) => string): string {
  return t('Width of one hill of this ground, in metres ({min}–{max}) — empty = {def} m.')
    .replace('{min}', String(RELIEF_WAVE_MIN))
    .replace('{max}', String(RELIEF_WAVE_MAX))
    .replace('{def}', String(RELIEF_WAVE_DEFAULT))
}

export interface TerrainDetailProps {
  /** The entry being edited, or `null` for the create form. */
  type: TerrainType | null
  /** Where the effective entry comes from. A new kind is always this world's. */
  source: 'shared' | 'world'
  /** Every kind the effective catalog holds — the create form refuses a name
   *  that is taken instead of silently overwriting an existing ground. */
  existingKinds: string[]
  /** The surface-texture library as the picker needs it (`GET
   *  /assets/surface-textures`). Empty while it loads or after a failed
   *  fetch — and then NOTHING is marked missing, because "not in the list" and
   *  "no list" are not the same statement. A stored id is still offered and
   *  still selected in that case, just without a verdict on it. */
  surfaces: SurfaceKind[]
  /** The step of the fine height TILES and the walk gate's slope limit, both
   *  straight from the server. 0 = not answered yet, and then the relief hint
   *  falls back to the mirrored constant and the warning simply says nothing. */
  tileStepM: number
  maxSlopeDeg: number
  busy: boolean
  /** Write the entry; answers the SANITIZED row the server stored, or `null`
   *  when the write failed (the caller has already said so). */
  onSave: (draft: TerrainType) => Promise<TerrainType | null>
  /** Delete the world row — the seed entry comes back, or the kind is gone for
   *  good when the seed never had it. Absent for a seed row: there is no world
   *  row to remove. */
  onReset?: () => void
  /** Leave the create form. Absent while an existing kind is edited. */
  onCancel?: () => void
}

export function TerrainDetail({
  type, source, existingKinds, surfaces, tileStepM, maxSlopeDeg, busy,
  onSave, onReset, onCancel,
}: TerrainDetailProps) {
  const { t } = useI18n()
  const isNew = type === null

  const [kind, setKind] = useState(type?.kind || '')
  const [name, setName] = useState(type?.name || '')
  const [color, setColor] = useState(type?.color || DEFAULT_COLOR)
  const [passable, setPassable] = useState(type ? !!type.passable : true)
  const [speed, setSpeed] = useState(type ? String(type.speed_factor) : '1')
  const [surface, setSurface] = useState((type?.surface || '').trim())
  const [moveAnim, setMoveAnim] = useState(metaStrOf(type, 'move_anim'))
  const [idleAnim, setIdleAnim] = useState(metaStrOf(type, 'idle_anim'))
  const [moveSink, setMoveSink] = useState(metaNumOf(type, 'move_sink_m'))
  const [idleSink, setIdleSink] = useState(metaNumOf(type, 'idle_sink_m'))
  const [reliefAmp, setReliefAmp] = useState(metaNumOf(type, 'relief_amplitude_m'))
  const [reliefWave, setReliefWave] = useState(metaNumOf(type, 'relief_wave_m'))
  const [sway, setSway] = useState(metaNumOf(type, 'sway_m'))
  const [undergrowth, setUndergrowth] = useState(metaNumOf(type, 'undergrowth'))
  /** The reset button is armed by the first click and fires on the second —
   *  no `window.confirm` in this UI, and the entry it removes may be the only
   *  copy of a hand-made ground. */
  const [armedReset, setArmedReset] = useState(false)

  const kindClean = kind.trim().toLowerCase()
  const kindBad = kindClean !== '' && !KIND_RE.test(kindClean)
  const kindTaken = isNew && !!kindClean && existingKinds.includes(kindClean)
  const speedNum = parseFloat(speed)
  const speedBad = !Number.isFinite(speedNum)
    || speedNum < SPEED_MIN || speedNum > SPEED_MAX

  // The grid step the hint divides by: the server's, as soon as it has
  // answered one, and the mirrored constant only until then.
  const stepM = tileStepM > 0 ? tileStepM : GRID_STEP_M
  /** From which amplitude the micro relief can outclimb the walk gate — out of
   *  the server's own two numbers, never a constant here (§ A16.2). */
  const warnAmpM = reliefWarnAmpM(maxSlopeDeg, tileStepM)
  const ampWarn = amplitudeWarn(t, reliefAmp, warnAmpM)

  // A stored surface the library does not hold has to stay SELECTABLE either
  // way — a `<select>` whose value matches no option shows the first one
  // instead, so an empty or failed library would display "none" over a stored
  // id and write that emptiness back on the next save.
  const surfaceUnlisted = !!surface && !surfaces.some((s) => s.kind === surface)
  // Whether it is also MISSING is a different statement, and only a library
  // that actually answered can make it: with an empty list "not in the list"
  // is no evidence at all, so nothing gets marked.
  const surfaceMissing = surfaceUnlisted && surfaces.length > 0

  // A field the user cannot fix by typing further is not "dirty", it is
  // wrong — but it still has to enable `Save` so the marking is reachable.
  // The guard matters most on a SEED row: every save there creates a world
  // override, so an idle click must not be able to fork one.
  const dirty = isNew
    || name !== (type?.name || '')
    || color !== (type?.color || DEFAULT_COLOR)
    || passable !== !!type?.passable
    || surface.trim() !== (type?.surface || '').trim()
    || moveAnim.trim() !== metaStrOf(type, 'move_anim')
    || idleAnim.trim() !== metaStrOf(type, 'idle_anim')
    || numChanged(moveSink, metaNumOf(type, 'move_sink_m'))
    || numChanged(idleSink, metaNumOf(type, 'idle_sink_m'))
    || numChanged(reliefAmp, metaNumOf(type, 'relief_amplitude_m'))
    || numChanged(reliefWave, metaNumOf(type, 'relief_wave_m'))
    || numChanged(sway, metaNumOf(type, 'sway_m'))
    || numChanged(undergrowth, metaNumOf(type, 'undergrowth'))
    || (speedBad ? speed !== String(type?.speed_factor) : speedNum !== type?.speed_factor)

  const canSave = dirty && !speedBad && !kindBad && !kindTaken
    && !!kindClean && !busy

  const save = useCallback(async () => {
    if (speedBad || !kindClean || kindBad || kindTaken) return
    // `meta` is free-form and belongs to whoever wrote it — this form owns
    // exactly EIGHT keys in it and hands the rest back untouched. `surface` is
    // ALWAYS sent, empty string included: the route is a full replace, so a
    // body without the key would undress the ground on every save (which is
    // exactly what the old dialog did). The numbers go out unclamped on
    // purpose: the server clamps, and the form refills from its answer, so a
    // typed 5 shows up as the stored 2.
    const saved = await onSave({
      kind: kindClean,
      name,
      color,
      passable,
      speed_factor: speedNum,
      surface: surface.trim(),
      meta: withOwnedMeta(type?.meta,
        { moveAnim, idleAnim, moveSink, idleSink, reliefAmp, reliefWave, sway,
          undergrowth }),
    })
    if (!saved) return
    setName(saved.name || '')
    setColor(saved.color || DEFAULT_COLOR)
    setPassable(!!saved.passable)
    setSpeed(String(saved.speed_factor))
    setSurface((saved.surface || '').trim())
    setMoveAnim(metaStrOf(saved, 'move_anim'))
    setIdleAnim(metaStrOf(saved, 'idle_anim'))
    setMoveSink(metaNumOf(saved, 'move_sink_m'))
    setIdleSink(metaNumOf(saved, 'idle_sink_m'))
    setReliefAmp(metaNumOf(saved, 'relief_amplitude_m'))
    setReliefWave(metaNumOf(saved, 'relief_wave_m'))
    setSway(metaNumOf(saved, 'sway_m'))
    setUndergrowth(metaNumOf(saved, 'undergrowth'))
  }, [color, idleAnim, idleSink, kindBad, kindClean, kindTaken, moveAnim,
      moveSink, name, onSave, passable, reliefAmp, reliefWave, speedBad,
      speedNum, surface, sway, type, undergrowth])

  return (
    <>
      <DetailToolbar
        title={isNew ? t('New terrain type') : (type?.name || type?.kind)}
        saveLabel={isNew ? t('Create') : t('Save')}
        onSave={() => { void save() }}
        disabled={!canSave}
        // Cancel and Reset ride in `extra` rather than in the toolbar's own
        // slots: `disabled` gates ALL of its buttons, and a create form whose
        // kind is still empty would then hold the user in a form they cannot
        // leave.
        extra={onCancel ? (
          <button
            type="button"
            className="ga-btn ga-btn-sm"
            onClick={onCancel}
          >
            {t('Cancel')}
          </button>
        ) : onReset ? (
          armedReset ? (
            <>
              <button
                type="button"
                className="ga-btn ga-btn-sm ga-btn-danger"
                disabled={busy}
                onClick={() => { setArmedReset(false); onReset() }}
              >
                {t('Really reset')}
              </button>
              <button
                type="button"
                className="ga-btn ga-btn-sm"
                onClick={() => setArmedReset(false)}
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
              onClick={() => setArmedReset(true)}
            >
              {t('Reset to seed')}
            </button>
          )
        ) : undefined}
      />
      <div className="ga-form">
        {/* WHERE THIS ENTRY COMES FROM, said before anything is typed: saving a
            seed row does not change the seed, it creates this world's own copy
            of it — and that copy then replaces the seed entry WHOLE. */}
        <div className="ga-field-hint">
          <span className={'ga-source ga-source-' + source}>
            {source === 'world' ? t('world') : t('shared')}
          </span>{' '}
          {isNew
            ? t('New kinds are stored in this world only.')
            : source === 'world'
              ? t('This world holds its own row for this kind — it replaces the shared seed entry whole, field for field.')
              : t('From the shared seed. Saving does not change the seed: it creates this world’s own row, which then replaces the seed entry whole.')}
        </div>

        <div className="ga-section">
          <div className="ga-form-section-label">{t('Basics')}</div>
          <div className="ga-form-row">
            <Field
              label={t('Kind')}
              hint={isNew
                ? (kindBad
                  ? t('A kind is lowercase letters, digits, “_” and “-”, starts with a letter or digit, at most 40 characters.')
                  : kindTaken
                    ? t('“{kind}” already exists — edit it in the list.')
                      .replace('{kind}', kindClean)
                    : t('The id of this ground, lowercase. It cannot be changed later.'))
                : t('The id of this ground — fixed once created.')}
            >
              {isNew ? (
                <input
                  className={'ga-input' + (kindBad || kindTaken ? ' ga-tt-invalid' : '')}
                  value={kind}
                  placeholder={t('e.g. gravel')}
                  aria-invalid={kindBad || kindTaken}
                  maxLength={KIND_MAX}
                  onChange={(e) => setKind(e.target.value)}
                />
              ) : (
                <span className="ga-tt-kind">{type?.kind}</span>
              )}
            </Field>
            <Field label={t('Name')}>
              <input
                className="ga-input"
                maxLength={NAME_MAX}
                value={name}
                placeholder={kindClean || t('Name')}
                onChange={(e) => setName(e.target.value)}
              />
            </Field>
          </div>
          <div className="ga-form-row">
            <Field
              label={t('Colour')}
              compact
              hint={t('The colour of the 2D schematic map — the 3D ground uses the surface below.')}
            >
              <input
                className="ga-tt-color"
                type="color"
                value={color}
                title={color}
                onChange={(e) => setColor(e.target.value)}
              />
            </Field>
            <Field label={t('Passable')} compact inline>
              <input
                type="checkbox"
                checked={passable}
                title={t('Whether characters can walk on this ground')}
                onChange={(e) => setPassable(e.target.checked)}
              />
            </Field>
            <Field
              label={t('Speed factor')}
              compact
              hint={speedBad
                ? t('Speed must be between {min} and {max}')
                  .replace('{min}', String(SPEED_MIN)).replace('{max}', String(SPEED_MAX))
                : t('Movement speed on this ground, 1 = normal')}
            >
              <input
                className={'ga-input ga-tt-num' + (speedBad ? ' ga-tt-invalid' : '')}
                type="number"
                min={SPEED_MIN}
                max={SPEED_MAX}
                step={SPEED_STEP}
                value={speed}
                aria-invalid={speedBad}
                onChange={(e) => setSpeed(e.target.value)}
              />
            </Field>
          </div>
        </div>

        {/* SURFACE — the one section that is a REFERENCE rather than a number.
            It says out loud that the assignment is explicit now, because the
            old behaviour (a same-named texture skinned the ground by itself)
            is exactly what a user would go on expecting otherwise. */}
        <div className="ga-section">
          <div className="ga-form-section-label">{t('Surface')}</div>
          <Field
            label={t('Surface texture')}
            hint={
              <>
                {t('Which material of the surface library skins this ground in 3D. The assignment is EXPLICIT: a texture generated LATER under the same name is not picked up by itself any more — one pick here connects it. Empty = the default ground.')}
                {' '}
                <a href="#/surface-textures">{t('Surface textures')}</a>
              </>
            }
          >
            <select
              className="ga-input"
              value={surface}
              title={t('The library entry this ground wears. Stored as its id; the list shows its name.')}
              onChange={(e) => setSurface(e.target.value)}
            >
              <option value="">{t('— none (default ground) —')}</option>
              {/* A stored value the library does not hold stays SELECTABLE, the
                  way the LoRA library keeps a missing LoRA: it is a legitimate
                  reference to something that may come back, and dropping it
                  from the list would silently rewrite the entry on the next
                  save. The "(missing)" LABEL is what hangs on an answered
                  library — an empty one shows the bare id and no verdict. */}
              {surfaceUnlisted ? (
                <option value={surface}>
                  {surfaceMissing ? `${surface} ${t('(missing)')}` : surface}
                </option>
              ) : null}
              {surfaces.map((s) => (
                <option key={s.kind} value={s.kind}>{s.name}</option>
              ))}
            </select>
          </Field>
          {surfaceMissing ? (
            <div className="ga-field-hint ga-field-warn">
              {t('“{kind}” is not in the surface library — this ground renders the default until the texture exists or another one is picked.')
                .replace('{kind}', surface)}
            </div>
          ) : null}
        </div>

        <div className="ga-section">
          <div className="ga-form-section-label">{t('Movement & water')}</div>
          <div className="ga-form-row">
            <Field
              label={t('Move animation')}
              hint={t('Animation clip a moving figure plays on this ground instead of walking — e.g. “swim” on water. Empty = walk and run as usual.')}
            >
              <input
                className="ga-input"
                maxLength={ANIM_MAX}
                value={moveAnim}
                placeholder={t('walk / run')}
                onChange={(e) => setMoveAnim(e.target.value)}
              />
            </Field>
            <Field
              label={t('Idle animation')}
              hint={t('Animation clip a figure STANDING on this ground plays instead of its own — e.g. “treading-water” on water. Empty = the activity or idle clip as usual.')}
            >
              <input
                className="ga-input"
                maxLength={ANIM_MAX}
                value={idleAnim}
                placeholder={t('idle / activity')}
                onChange={(e) => setIdleAnim(e.target.value)}
              />
            </Field>
          </div>
          <div className="ga-form-row">
            <Field label={t('Sink move (m)')} compact hint={moveSinkHint(t)}>
              <input
                className="ga-input ga-tt-num"
                type="number"
                min={SINK_MIN}
                max={SINK_MAX}
                step={SINK_STEP}
                value={moveSink}
                placeholder={t('on top')}
                onChange={(e) => setMoveSink(e.target.value)}
              />
            </Field>
            <Field label={t('Sink idle (m)')} compact hint={idleSinkHint(t)}>
              <input
                className="ga-input ga-tt-num"
                type="number"
                min={SINK_MIN}
                max={SINK_MAX}
                step={SINK_STEP}
                value={idleSink}
                placeholder={t('on top')}
                onChange={(e) => setIdleSink(e.target.value)}
              />
            </Field>
          </div>
        </div>

        <div className="ga-section">
          <div className="ga-form-section-label">{t('Relief')}</div>
          <div className="ga-form-row">
            <Field
              label={t('Relief amplitude (m)')}
              compact
              hint={amplitudeHint(t, reliefAmp, stepM)}
            >
              <input
                className="ga-input ga-tt-num"
                type="number"
                min={RELIEF_AMP_MIN}
                max={RELIEF_AMP_MAX}
                step={RELIEF_AMP_STEP}
                value={reliefAmp}
                placeholder={t('flat')}
                onChange={(e) => setReliefAmp(e.target.value)}
              />
            </Field>
            <Field
              label={t('Relief wavelength (m)')}
              compact
              hint={waveHint(t)}
            >
              <input
                className="ga-input ga-tt-num"
                type="number"
                min={RELIEF_WAVE_MIN}
                max={RELIEF_WAVE_MAX}
                step={RELIEF_WAVE_STEP}
                value={reliefWave}
                placeholder={String(RELIEF_WAVE_DEFAULT)}
                onChange={(e) => setReliefWave(e.target.value)}
              />
            </Field>
          </div>
          {/* THE STEEPNESS WARNING of the amplitude, on its own line under the
              two fields. Amber and informative: the value is stored as typed,
              the clamp stays at 2 m. */}
          {ampWarn ? (
            <div className="ga-field-hint ga-field-warn">{ampWarn}</div>
          ) : null}
        </div>

        <div className="ga-section">
          <div className="ga-form-section-label">{t('Vegetation')}</div>
          <div className="ga-form-row">
            <Field label={t('Sway (m)')} compact hint={swayHint(t)}>
              <input
                className="ga-input ga-tt-num"
                type="number"
                min={SWAY_MIN}
                max={SWAY_MAX}
                step={SWAY_STEP}
                value={sway}
                placeholder={t('still')}
                onChange={(e) => setSway(e.target.value)}
              />
            </Field>
            <Field label={t('Undergrowth')} compact hint={undergrowthHint(t)}>
              <input
                className="ga-input ga-tt-num"
                type="number"
                min={UNDERGROWTH_MIN}
                max={UNDERGROWTH_MAX}
                step={UNDERGROWTH_STEP}
                value={undergrowth}
                placeholder={t('bare')}
                onChange={(e) => setUndergrowth(e.target.value)}
              />
            </Field>
          </div>
          {/* A type used to declare what its ground grows. It moved to the
              painted AREA, and old entries are simply not read any more —
              which looks exactly like "my trees are gone" unless it is said
              out loud, here, where they were authored. */}
          <div className="ga-field-hint">
            {t('A scatter LIST (which trees, how many) used to be set here. It now belongs to the painted area — select an area on the map and open “Scatter” in its chip. Anything set here before has no effect any more.')}
          </div>
        </div>
      </div>
    </>
  )
}
