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
import {
  SHORE_RAMP_DEFAULT_M, SHORE_RAMP_MAX_M, SHORE_RAMP_MIN_M,
  WATER_DEPTH_DEFAULT_M, WATER_DEPTH_MAX_M, WATER_DEPTH_MIN_M,
} from '../map/mapTypes'
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
// `terrain_types.SWIM_FROM_*`. THE THIRD FIELD OF THE MOVEMENT SENTENCE (W4c):
// from which WATER DEPTH the two clips and the two sinks above count at all.
// 0 IS A VALUE here — "swim from the very rim", what every water kind did
// before this round — so an empty field is the server's metre, not a zero.
const SWIM_FROM_MIN = 0
const SWIM_FROM_MAX = 10
const SWIM_FROM_STEP = 0.1
const SWIM_FROM_DEFAULT = 1
const SWAY_MIN = 0.01
const SWAY_MAX = 0.5
const SWAY_STEP = 0.01
// `terrain_types.UNDERGROWTH_MIN/MAX`. The floor is 0 and 0 means "no key",
// exactly like an empty field — there is no smallest visible share here, the
// layer simply gets thinner.
const UNDERGROWTH_MIN = 0
const UNDERGROWTH_MAX = 1
const UNDERGROWTH_STEP = 0.05
// `terrain_layers.EDGE_BLEND_MIN_M/MAX_M/DEFAULT_M`. THE ONE FIELD HERE WHERE
// ZERO IS A VALUE and not "unset": it is the HARD CUT of a room floor, a kerb,
// a paved path (plan-ein-boden.md § G3), so it has its own setter and its own
// dirty test below — every other number in this form treats 0 as "no key".
const EDGE_BLEND_MIN = 0
const EDGE_BLEND_MAX = 8
const EDGE_BLEND_STEP = 0.1
const EDGE_BLEND_DEFAULT = 1.5
/** The DEPTH step of the water section. Its floor is 0.2 m and not 0: a bed
 *  exactly at the mirror is not water, it is a wet floor, so the server clamps
 *  rather than accepting it (`heightfield.WATER_DEPTH_MIN_M`). */
const WATER_DEPTH_STEP = 0.1
/** …and the ramp's. 0 IS A VALUE here, exactly like `edge_blend_m`: it is the
 *  walled basin, a step instead of a beach, and it has to survive a save. */
const SHORE_RAMP_STEP = 0.5
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

/** Read one BOOLEAN meta key — the water flag. A missing key is `false`, which
 *  is what "not water" is: there is no third state. */
function metaBoolOf(type: TerrainType | null, key: string): boolean {
  return !!(type?.meta as Record<string, unknown> | undefined)?.[key]
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

/** One optional number where ZERO IS A VALUE, IN PLACE —
 *  `terrain_layers.sanitize_edge_blend`. Junk still leaves no key (which reads
 *  back as the default width), but a typed 0 is stored as 0: the hard cut. */
function setMetaBlend(meta: Record<string, unknown>, key: string,
                      raw: string): void {
  const num = parseFloat(raw)
  if (Number.isFinite(num) && num >= 0) meta[key] = num
  else delete meta[key]
}

/** …and its dirty test, on the same "0 is a value" rule. */
function blendChanged(raw: string, stored: string): boolean {
  const typed = parseFloat(raw)
  const known = parseFloat(stored)
  return (Number.isFinite(typed) && typed >= 0 ? typed : null)
    !== (Number.isFinite(known) && known >= 0 ? known : null)
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

/** One BOOLEAN key, IN PLACE — written or GONE. `false` leaves no key behind:
 *  "not water" is the absence of the flag everywhere the server asks it
 *  (`terrain_types.is_water_kind`), so a stored `false` would only be a second
 *  way of writing the same nothing. */
function setMetaBool(meta: Record<string, unknown>, key: string,
                     value: boolean): void {
  if (value) meta[key] = true
  else delete meta[key]
}

/** The `meta` keys this form owns, as their fields hold them. */
interface OwnedMeta {
  moveAnim: string
  idleAnim: string
  moveSink: string
  idleSink: string
  swimFrom: string
  reliefAmp: string
  reliefWave: string
  sway: string
  undergrowth: string
  edgeBlend: string
  water: boolean
  waterDepth: string
  shoreRamp: string
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
  // The swim threshold shares the "0 is a value" rule of the transition width:
  // a 0 means "swim from the very rim" and has to survive a save, while an
  // empty field is the server's default metre.
  setMetaBlend(next, 'swim_from_m', own.swimFrom)
  setMetaNum(next, 'relief_amplitude_m', own.reliefAmp)
  setMetaNum(next, 'relief_wave_m', own.reliefWave)
  setMetaNum(next, 'sway_m', own.sway)
  setMetaNum(next, 'undergrowth', own.undergrowth)
  setMetaBlend(next, 'edge_blend_m', own.edgeBlend)
  setMetaBool(next, 'water', own.water)
  setMetaNum(next, 'water_depth_m', own.waterDepth)
  // The ramp shares the "0 is a value" rule of the transition, not the "empty
  // means no key" rule of every other number: a ramp of 0 is the walled basin.
  setMetaBlend(next, 'shore_ramp_m', own.shoreRamp)
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

/** The swim-threshold hint (W4c) — the field that turns swimming from a
 *  property of the KIND into one of the water DEPTH under the figure. It says
 *  what the SHALLOW side looks like, because that is the case the number
 *  creates and the one nobody can see in the field. */
function swimFromHint(t: (s: string) => string): string {
  return t('From which water DEPTH a figure swims here, in metres ({min}–{max}) — empty = {def} m. Shallower water is waded: the figure walks on the bed with its own clips and is not sunk at all; from this depth the two animations and the two sink depths above take over. 0 = swim from the very rim.')
    .replace('{min}', String(SWIM_FROM_MIN))
    .replace('{max}', String(SWIM_FROM_MAX))
    .replace('{def}', String(SWIM_FROM_DEFAULT))
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

/** The transition hint. It has to say the three things the field cannot show:
 *  that an EMPTY field is not zero (it is the default fringe), that ZERO is a
 *  real setting — the hard cut a room floor or a kerb needs — and WHOSE number
 *  counts where two grounds meet, which is the question a second area next
 *  door raises and this field alone can never answer (user rule 2026-08-21,
 *  pinned in `scripts/smoke_terrain_layers.py` [13]). */
function edgeBlendHint(t: (s: string) => string): string {
  return t('How wide the transition from this ground to the one under it is, in metres (0–{max}) — empty = {def} m, the soft fringe every ground had before. 0 is the HARD CUT: the edge then runs exactly on the line that was painted, anti-aliased but not blended, which is what a room floor, a kerb or a paved path wants. Where two grounds share an edge, the HIGHER layer’s number wins — the one painted on top decides how it fades into what is below.')
    .replace('{max}', String(EDGE_BLEND_MAX))
    .replace('{def}', String(EDGE_BLEND_DEFAULT))
}

/** The water-flag hint — what the checkbox switches on, said as the two things
 *  that visibly change (a carved bed, a mirror) rather than as the flag it is.
 *  It also has to say that the NAME never mattered: a world whose river kind is
 *  called `lagoon` carves exactly like one whose kind is called `water`, and a
 *  ground that was never flagged simply never carved, however blue it looked. */
function waterFlagHint(t: (s: string) => string): string {
  return t('This kind IS water: every area painted with it gets a bed carved under the world height field and a mirror drawn on top, so no terrain can poke through the surface at any distance. The name of the kind never decides this — only this box does, and any ground can be turned into water with it.')
}

/** The kind-DEFAULT depth hint. Its job is to say who wins: the number here is
 *  what every area of this kind gets UNLESS that area typed its own, and
 *  changing it therefore moves every bed nobody overrode. */
function waterDepthHint(t: (s: string) => string): string {
  return t('How far the bed lies under the mirror once the shore ramp is through, in metres ({min}–{max}) — empty = {def} m. It is the DEFAULT of this kind: a single painted area may type its own depth and wins, everything else follows this number the moment it changes.')
    .replace('{min}', String(WATER_DEPTH_MIN_M))
    .replace('{max}', String(WATER_DEPTH_MAX_M))
    .replace('{def}', String(WATER_DEPTH_DEFAULT_M))
}

/** The kind-DEFAULT shore-ramp hint. Same override rule, plus the one thing a
 *  number field cannot show: 0 is a setting here, not an empty field. */
function shoreRampHint(t: (s: string) => string): string {
  return t('How far INSIDE the outline the full depth is reached, in metres ({min}–{max}) — empty = {def} m, a beach that wades in. 0 is a VALUE: the bed drops at the line that was painted, which is the walled basin of a pool or a quay. The DEFAULT of this kind; a single painted area may override it.')
    .replace('{min}', String(SHORE_RAMP_MIN_M))
    .replace('{max}', String(SHORE_RAMP_MAX_M))
    .replace('{def}', String(SHORE_RAMP_DEFAULT_M))
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
  const [swimFrom, setSwimFrom] = useState(metaNumOf(type, 'swim_from_m'))
  const [reliefAmp, setReliefAmp] = useState(metaNumOf(type, 'relief_amplitude_m'))
  const [reliefWave, setReliefWave] = useState(metaNumOf(type, 'relief_wave_m'))
  const [sway, setSway] = useState(metaNumOf(type, 'sway_m'))
  const [undergrowth, setUndergrowth] = useState(metaNumOf(type, 'undergrowth'))
  const [edgeBlend, setEdgeBlend] = useState(metaNumOf(type, 'edge_blend_m'))
  const [water, setWater] = useState(metaBoolOf(type, 'water'))
  const [waterDepth, setWaterDepth] = useState(metaNumOf(type, 'water_depth_m'))
  const [shoreRamp, setShoreRamp] = useState(metaNumOf(type, 'shore_ramp_m'))
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
    || blendChanged(swimFrom, metaNumOf(type, 'swim_from_m'))
    || numChanged(reliefAmp, metaNumOf(type, 'relief_amplitude_m'))
    || numChanged(reliefWave, metaNumOf(type, 'relief_wave_m'))
    || numChanged(sway, metaNumOf(type, 'sway_m'))
    || numChanged(undergrowth, metaNumOf(type, 'undergrowth'))
    || blendChanged(edgeBlend, metaNumOf(type, 'edge_blend_m'))
    || water !== metaBoolOf(type, 'water')
    || numChanged(waterDepth, metaNumOf(type, 'water_depth_m'))
    || blendChanged(shoreRamp, metaNumOf(type, 'shore_ramp_m'))
    || (speedBad ? speed !== String(type?.speed_factor) : speedNum !== type?.speed_factor)

  const canSave = dirty && !speedBad && !kindBad && !kindTaken
    && !!kindClean && !busy

  const save = useCallback(async () => {
    if (speedBad || !kindClean || kindBad || kindTaken) return
    // `meta` is free-form and belongs to whoever wrote it — this form owns
    // exactly THIRTEEN keys in it and hands the rest back untouched. `surface` is
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
        { moveAnim, idleAnim, moveSink, idleSink, swimFrom, reliefAmp,
          reliefWave, sway, undergrowth, edgeBlend, water, waterDepth,
          shoreRamp }),
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
    setSwimFrom(metaNumOf(saved, 'swim_from_m'))
    setReliefAmp(metaNumOf(saved, 'relief_amplitude_m'))
    setReliefWave(metaNumOf(saved, 'relief_wave_m'))
    setSway(metaNumOf(saved, 'sway_m'))
    setUndergrowth(metaNumOf(saved, 'undergrowth'))
    setEdgeBlend(metaNumOf(saved, 'edge_blend_m'))
    setWater(metaBoolOf(saved, 'water'))
    setWaterDepth(metaNumOf(saved, 'water_depth_m'))
    setShoreRamp(metaNumOf(saved, 'shore_ramp_m'))
  }, [color, edgeBlend, idleAnim, idleSink, kindBad, kindClean, kindTaken,
      moveAnim, moveSink, name, onSave, passable, reliefAmp, reliefWave,
      shoreRamp, speedBad, speedNum, surface, sway, swimFrom, type,
      undergrowth, water, waterDepth])

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
          {/* THE DEPTH THE TWO ROWS ABOVE START AT (W4c). It stands under them
              and not in the Water section on purpose: it decides which CLIP
              and which SINK a figure gets, which is what this section is
              about — the Water section shapes the bed, this one carries the
              figure. It counts for any ground the map covers with water, so
              it stays readable on an unflagged kind like the two shape
              numbers do. */}
          <div className="ga-form-row">
            <Field label={t('Swim from depth (m)')} compact
              hint={swimFromHint(t)}>
              <input
                className="ga-input ga-tt-num"
                type="number"
                min={SWIM_FROM_MIN}
                max={SWIM_FROM_MAX}
                step={SWIM_FROM_STEP}
                value={swimFrom}
                placeholder={String(SWIM_FROM_DEFAULT)}
                onChange={(e) => setSwimFrom(e.target.value)}
              />
            </Field>
          </div>
        </div>

        {/* WATER IS A KIND (§ A16.3, addendum "Ein Wasser-Gesetz" — W1). The
            flag is the ONE predicate the bake, the layer table, the sanitizer
            and the map editor all ask, so it belongs to the kind and not to a
            name, a colour or a texture class. The two numbers under it are
            what this kind's water is NORMALLY like; a single painted area may
            override both, and the mirror itself is always the area's alone —
            two lakes of one kind stand at two heights. */}
        <div className="ga-section">
          <div className="ga-form-section-label">{t('Water')}</div>
          <Field label={t('Water kind')} inline hint={waterFlagHint(t)}>
            <input
              type="checkbox"
              checked={water}
              title={t('This kind is water: painted areas carve a bed and get a mirror')}
              onChange={(e) => setWater(e.target.checked)}
            />
          </Field>
          {/* The two numbers stay READABLE and EDITABLE on an unflagged kind,
              exactly as the server whitelists them for every kind: a ground is
              often given its depth before somebody decides it is water, and a
              value that survived that edit is one the author already chose. */}
          <div className="ga-form-row">
            <Field label={t('Depth (m)')} compact hint={waterDepthHint(t)}>
              <input
                className="ga-input ga-tt-num"
                type="number"
                min={WATER_DEPTH_MIN_M}
                max={WATER_DEPTH_MAX_M}
                step={WATER_DEPTH_STEP}
                value={waterDepth}
                placeholder={String(WATER_DEPTH_DEFAULT_M)}
                onChange={(e) => setWaterDepth(e.target.value)}
              />
            </Field>
            <Field label={t('Shore ramp (m)')} compact hint={shoreRampHint(t)}>
              <input
                className="ga-input ga-tt-num"
                type="number"
                min={SHORE_RAMP_MIN_M}
                max={SHORE_RAMP_MAX_M}
                step={SHORE_RAMP_STEP}
                value={shoreRamp}
                placeholder={String(SHORE_RAMP_DEFAULT_M)}
                onChange={(e) => setShoreRamp(e.target.value)}
              />
            </Field>
          </div>
          {/* WHAT THIS SECTION CANNOT SET, said where somebody would look for
              it: the mirror is per AREA, and so are the flow direction and the
              bed — a kind has no single water level to give. */}
          <div className="ga-field-hint">
            {t('The water LEVEL, the flow direction and the bed under the water belong to the painted area, not to the kind — select an area on the map to set them. Two lakes of one kind stand at two heights, so a kind could never answer for both.')}
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
            <Field label={t('Transition (m)')} compact hint={edgeBlendHint(t)}>
              <input
                className="ga-input ga-tt-num"
                type="number"
                min={EDGE_BLEND_MIN}
                max={EDGE_BLEND_MAX}
                step={EDGE_BLEND_STEP}
                value={edgeBlend}
                placeholder={String(EDGE_BLEND_DEFAULT)}
                onChange={(e) => setEdgeBlend(e.target.value)}
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
