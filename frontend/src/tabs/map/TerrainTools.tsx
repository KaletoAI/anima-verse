/**
 * TerrainTools — the terrain controls of the map toolbar and the chip of the
 * selected area. Purely presentational, like `PlanToolbar`: every handler and
 * all state live in `MapTab`, these components only decide what is armed,
 * disabled or shown.
 *
 * The modes are exclusive because their clicks mean different things — select
 * a location, drop a vertex, pick an area. A single "click on the map" that
 * guesses from context would be exactly the kind of hidden modality the plan
 * editor already learned to avoid.
 *
 * The user picks them in TWO steps (user finding 2026-08-13): WHAT is being
 * edited (`MapPrimary`: Location / Terrain / Heights), and — under Terrain and
 * Heights, with the same two words in both — WHETHER a click draws a new shape
 * or picks an existing one (`MapSub`: New / Select). Painting and reshaping
 * ground are one subject, not two peers of "Locations", and the pair of
 * gestures is the same question in both subjects.
 *
 * The limits below are the SERVER's (`app/models/terrain.py`), mirrored so a
 * refusal arrives as a sentence in the toolbar instead of a 400 after the
 * user has clicked 257 times. They are a copy, not a second opinion: the
 * server still validates, and any change there must land here too.
 */
import { useEffect, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { SliderInput } from '../../components/SliderInput'
import type { PropRef } from '../../lib/refs'
import { fmtHeight, heightColor } from './HeightLayer'
import { minFalloffFor, reliefStepNotice, tooSteep } from './heightMath'
import {
  STROKE_STYLES, flowCompass, formatAreaM2, polygonAreaM2, type StrokeStyle,
} from './mapMath'
import { typeColor } from './TerrainLayer'
import {
  FLOW_DIR_MAX_DEG, FLOW_DIR_MIN_DEG, FLOW_SPEED_DEFAULT_M_S,
  FLOW_SPEED_MAX_M_S, FLOW_SPEED_MIN_M_S, RELIEF_AMP_MAX_M, RELIEF_AMP_MIN_M,
  RELIEF_WAVE_DEFAULT_M, RELIEF_WAVE_MAX_M, RELIEF_WAVE_MIN_M,
  SHORE_RAMP_MAX_M, SHORE_RAMP_MIN_M,
  WATER_DEPTH_MAX_M, WATER_DEPTH_MIN_M, isWaterKind, waterKindDefaults,
} from './mapTypes'
import type {
  FlowAlong, HeightArea, TerrainArea, TerrainRelief, TerrainScatterEntry,
  TerrainStroke, TerrainType, TerrainWater, TerrainWaterProfile,
} from './mapTypes'

/**
 * What a click on the map does. `select` is the location editor of Task 3;
 * `heights` edits the world RELIEF (§ A16) and has a sub-tool of its own
 * (`HeightTool`), the way `paint` has a shape.
 *
 * This stays the ONE state the canvas, the layer order and the hit tests read.
 * The two-step toolbar is a view of it: `paint` and `edit-area` are the two
 * halves of the Terrain subject, and `heights` splits along `HeightTool`
 * instead. Nothing about a click changed when the buttons were regrouped.
 */
export type TerrainMode = 'select' | 'paint' | 'edit-area' | 'heights' | 'props'

/** WHAT the toolbar is editing — the primary switch. */
export type MapPrimary = 'location' | 'terrain' | 'heights' | 'props'

/** WHETHER a click draws a new shape or picks an existing one. The dependent
 *  switch of Terrain and Heights, worded identically in both. */
export type MapSub = 'new' | 'select'

/** The subject a canvas mode belongs to. The toolbar, the tray lists and the
 *  layer order all ask this question, so it is answered in one place. */
export function primaryOf(mode: TerrainMode): MapPrimary {
  if (mode === 'heights') return 'heights'
  if (mode === 'props') return 'props'
  if (mode === 'select') return 'location'
  return 'terrain'
}

/**
 * What a click means inside the heights mode: pick an existing height area, or
 * drop the next vertex of a new one. Explicit rather than guessed from
 * whatever happens to sit under the cursor — the same reason the modes
 * themselves are a visible switch.
 */
export type HeightTool = 'select' | 'draw'

/**
 * HOW the paint mode draws. Both produce the very same thing — a polygon in
 * `terrain_areas` — they only differ in what the user's clicks mean: the
 * outline of a ring (`area`), or the centre line of a ribbon (`line`) whose
 * outline the editor computes from a width.
 */
export type PaintShape = 'area' | 'line'

/** Server mirrors — `_sanitize_polygon`/`sanitize_area` in
 *  `app/models/terrain.py`. */
export const MIN_POINTS = 3
export const MAX_POINTS = 2050
export const MAX_COORD = 100000

/** Clicks ONE hand-drawn ring may take. Not a server mirror: the storage cap
 *  above is what the LINE TOOL generates (a sampled `wavy` kilometre is 670
 *  outline points), and nobody clicks a ring two thousand times — a gesture
 *  that long is a stuck mouse button, and every one of those clicks is a
 *  handle to drag afterwards. */
export const MAX_DRAFT_POINTS = 256
export const MAX_Z_ORDER = 10000

/** Server mirror — `app/models/terrain.MAX_SCATTER_ENTRIES`. */
export const MAX_SCATTER_ENTRIES = 8

/** What a freshly added scatter row starts as.
 *
 *  The target height is deliberately EMPTY (finding 12): an entry without
 *  `height_m` now takes the height the prop really has in the library, and a
 *  row seeded with 2 m would override exactly that — every tree ended up
 *  avatar-high because the seeded number was an authored answer nobody had
 *  given. The field shows the inherited height as its placeholder instead, so
 *  it is still visible and still an obvious knob to turn. */
const NEW_SCATTER_ENTRY: TerrainScatterEntry = {
  density_per_100m2: 1,
}

/** The target height a scatter row inherits when it authors none: the prop's
 *  own library height, and the 3D client's flat fallback where there is no
 *  prop (the built-in tuft, a hand-written URL). Mirrors
 *  `client3d/src/scene/scatterLod.scatterTargetH` — the editor only SHOWS the
 *  number, the renderers decide it. */
const SCATTER_FALLBACK_HEIGHT_M = 2

/** Server mirror — `app/models/terrain.MIN_SPACING_MAX_M`. The widest gap a
 *  scatter row may keep between its own props; the server clamps to it rather
 *  than refusing, so this is the knob's range and not a rejection threshold. */
export const SCATTER_SPACING_MAX_M = 100

/** The URL a scatter `model` stores: exactly the `model_url` the prop library
 *  hands out on the server (`app/core/props.py`), and exactly what the 3D
 *  ground passes to its GLB loader unchanged (`client3d/src/scene/ground.ts`
 *  → `buildScatter`). Site-relative like every other asset URL in the payload,
 *  so a client on another host resolves it against its own API origin. */
export function propModelUrl(id: string): string {
  return `/assets/props/${encodeURIComponent(id)}/model`
}

/** A line needs two points to have a direction at all. */
export const MIN_STROKE_POINTS = 2

/** Click limit of a centre LINE. It is not the server's — the server only ever
 *  sees the generated polygon, which a bendy line inflates by up to 4n−4
 *  points. This caps the GESTURE; the generated polygon is checked against
 *  `MAX_POINTS` on top of it, because a hairpin chain overruns that anyway. */
export const MAX_STROKE_POINTS = 100

/** Stroke width in metres: a footpath at the bottom, a broad river at the top,
 *  3 m — a cart track — as the thing most people draw first. */
export const STROKE_WIDTH_MIN_M = 0.5
export const STROKE_WIDTH_MAX_M = 50
export const STROKE_WIDTH_DEFAULT_M = 3

/** How far apart the deflections of a decorated line sit, in metres, and how
 *  far they swing to either side. Both are the SERVER's clamps
 *  (`app/models/terrain.STROKE_SPACING_MIN_M` …), mirrored here so a knob
 *  cannot ask for something the store would quietly correct. The defaults are
 *  a bank one can see the shape of: a deflection every 10 m, 2 m out. */
export const STROKE_SPACING_MIN_M = 2
export const STROKE_SPACING_MAX_M = 100
export const STROKE_SPACING_DEFAULT_M = 10
export const STROKE_AMPLITUDE_MIN_M = 0.5
export const STROKE_AMPLITUDE_MAX_M = 30
export const STROKE_AMPLITUDE_DEFAULT_M = 2

/** The width as it may be stored: inside the range, on the 2-decimal metre
 *  grid the server keeps coordinates on. */
function clampStrokeWidth(v: number): number {
  if (!Number.isFinite(v)) return STROKE_WIDTH_DEFAULT_M
  const c = Math.min(STROKE_WIDTH_MAX_M, Math.max(STROKE_WIDTH_MIN_M, v))
  return Math.round(c * 100) / 100
}

/**
 * The width field, used both in the toolbar (the width the NEXT line gets) and
 * in the chip (the width the selected one HAS).
 *
 * It keeps its own text draft so a half-typed "0." is not thrown away and
 * clamped mid-keystroke; the value is committed on blur and on Enter, and a
 * value outside the range is corrected instead of refused — the field is a
 * knob, not a form. Enter is stopped here: the paint mode listens for it to
 * finish a line, and finishing the drawing while the cursor sits in a number
 * field is not what that key means here.
 *
 * `commit` NEVER writes the field. It hands the number to the parent and asks
 * for a resync; what the box then shows is `widthM` — the width the thing
 * actually has. That matters because the parent may refuse: a width that makes
 * an unusable outline is toasted and dropped without `widthM` ever moving, and
 * a field that had written the refused number itself would be the last place
 * in the editor still claiming it. The token is what makes the effect run in
 * that case at all, since `widthM` did not change.
 */
function WidthField({ widthM, onWidth }: {
  widthM: number; onWidth: (m: number) => void
}) {
  const { t } = useI18n()
  const [draft, setDraft] = useState(String(widthM))
  const [resync, setResync] = useState(0)
  useEffect(() => { setDraft(String(widthM)) }, [widthM, resync])
  const commit = () => {
    setResync((n) => n + 1)
    const v = parseFloat(draft)
    if (!Number.isFinite(v)) return
    const c = clampStrokeWidth(v)
    if (c !== widthM) onWidth(c)
  }
  return (
    <label className="ga-terrain-width"
      title={t('Width of the ribbon the centre line becomes ({min}–{max} m)')
        .replace('{min}', String(STROKE_WIDTH_MIN_M))
        .replace('{max}', String(STROKE_WIDTH_MAX_M))}>
      {t('Width')}
      <input
        className="ga-input"
        type="number" step={0.5}
        min={STROKE_WIDTH_MIN_M} max={STROKE_WIDTH_MAX_M}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key !== 'Enter') return
          e.stopPropagation()
          e.currentTarget.blur()
        }}
      />
      m
    </label>
  )
}

/**
 * A number knob of a scatter entry — the `WidthField` pattern, generalised.
 *
 * Its own text draft so a half-typed "0." survives, committed on blur and on
 * Enter (which is stopped here: the paint mode listens for it to finish a
 * line). It never writes itself — it hands the number up and shows whatever
 * comes back, so a value the server clamps is not left claimed by the field.
 * An empty field is a real state and commits as `null`: "no target height" is
 * not the same as "0 m tall". `placeholder` is what the empty field then
 * inherits — the number shown greyed out is the one that really applies.
 */
function ScatterNum({ label, title, value, step, placeholder, onCommit }: {
  label: string; title: string; value: number | null; step: number
  placeholder?: string
  onCommit: (v: number | null) => void
}) {
  const [draft, setDraft] = useState(value === null ? '' : String(value))
  const [resync, setResync] = useState(0)
  useEffect(() => { setDraft(value === null ? '' : String(value)) }, [value, resync])
  const commit = () => {
    setResync((n) => n + 1)
    const text = draft.trim()
    if (text === '') { if (value !== null) onCommit(null); return }
    const v = parseFloat(text)
    if (!Number.isFinite(v) || v < 0) return
    const r = Math.round(v * 1000) / 1000
    if (r !== value) onCommit(r)
  }
  return (
    <label title={title}>
      {label}
      <input
        className="ga-input"
        type="number" min={0} step={step}
        placeholder={placeholder}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key !== 'Enter') return
          e.stopPropagation()
          e.currentTarget.blur()
        }}
      />
    </label>
  )
}

/**
 * What an area GROWS — the list editor of finding B17.
 *
 * It sits in the AREA chip and not in the type dialog because that is where
 * the decision is: the shape one means is already selected, and the "Scatter
 * preview" switch in the toolbar shows the very points the 3D client will
 * plant (both sides call the ONE sampler, `@anima/scene-render`).
 *
 * Every change writes straight through, like the kind and the layer next to
 * it — the numbers commit on blur, the pickers on choice. `colorOf` is the
 * same index colour the preview draws with, so a row and its dots can be told
 * apart by eye.
 */
function ScatterEditor({ entries, props, colorOf, onChange }: {
  entries: TerrainScatterEntry[]
  props: PropRef[]
  colorOf: (index: number) => string
  onChange: (entries: TerrainScatterEntry[]) => void
}) {
  const { t } = useI18n()
  const patch = (i: number, next: Partial<TerrainScatterEntry>) => {
    const out = entries.map((e, k) => (k === i ? { ...e, ...next } : e))
    // An absent key is not the same as an empty one — the server whitelist
    // drops `height_m`/`model` when they are not set, and so must this, or a
    // cleared field would travel as `null` and read back as junk.
    const e = out[i]
    if (!(typeof e.height_m === 'number' && e.height_m > 0)) delete e.height_m
    if (!(typeof e.min_spacing_m === 'number' && e.min_spacing_m > 0)) {
      delete e.min_spacing_m
    }
    if (!e.model) delete e.model
    onChange(out)
  }
  return (
    <div className="ga-terrain-scatter">
      {entries.map((e, i) => {
        const model = e.model || ''
        const prop = props.find((p) => propModelUrl(p.id) === model)
        const known = !model || !!prop
        // What the empty height field inherits — the prop's real height from
        // the library (the same number the Props tab shows, the lean
        // `/assets/props` listing already carries it), the flat fallback where
        // there is no prop record.
        const inherited = (prop && Number(prop.height_m) > 0)
          ? Number(prop.height_m) : SCATTER_FALLBACK_HEIGHT_M
        return (
          <div className="ga-terrain-scatter-row" key={i}>
            <span className="ga-terrain-swatch" style={{ background: colorOf(i) }} />
            <label className="ga-terrain-scatter-model">
              <select
                className="ga-input"
                value={model}
                title={t('A prop from the library replaces the tuft. Only props that already have a mesh are offered.')}
                onChange={(ev) => patch(i, { model: ev.target.value })}
              >
                <option value="">{t('Tuft (no model)')}</option>
                {props.map((p) => (
                  <option key={p.id} value={propModelUrl(p.id)}>{p.name || p.id}</option>
                ))}
                {/* A model URL the library does not know — hand-authored, or a
                    prop that has since been deleted. It stays selected and
                    visible instead of silently falling back to the tuft. */}
                {known ? null : <option value={model}>{model}</option>}
              </select>
            </label>
            <ScatterNum
              label={t('per 100 m²')}
              title={t('How many of these stand on 100 m² of this area. 0 = none.')}
              value={Number.isFinite(e.density_per_100m2) ? e.density_per_100m2 : 0}
              step={0.5}
              onCommit={(v) => patch(i, { density_per_100m2: v ?? 0 })}
            />
            <ScatterNum
              label={t('height (m)')}
              title={model && prop
                ? t('Target height: the model is scaled until it is this tall, and it always stands ON the ground. Empty = the prop’s own height from the Props tab ({h} m).')
                  .replace('{h}', String(inherited))
                : t('Target height: the model is scaled until it is this tall, and it always stands ON the ground. Empty = the prop’s own height from the Props tab, and 2 m for a model this world has no prop for (0.8 m for a tuft).')}
              value={typeof e.height_m === 'number' ? e.height_m : null}
              placeholder={model ? String(inherited) : undefined}
              step={0.5}
              onCommit={(v) => patch(i, { height_m: v && v > 0 ? v : undefined })}
            />
            {/* HOW FAR THIS ROW'S OWN PROPS STAY APART. It is a per-ROW knob
                and not a per-area one: a wood is trees far apart with ferns
                between them, and the two rows that make it say two different
                distances. Empty and 0 are the same answer — no constraint —
                so the field carries no placeholder to inherit. */}
            <ScatterNum
              label={t('Min. spacing (m)')}
              title={t('Instances of this entry keep at least this distance from each other. 0 = none.')}
              value={typeof e.min_spacing_m === 'number' ? e.min_spacing_m : null}
              step={0.5}
              onCommit={(v) => patch(i, {
                min_spacing_m: v && v > 0
                  ? Math.min(v, SCATTER_SPACING_MAX_M) : undefined,
              })}
            />
            <button type="button" className="ga-btn ga-btn-sm"
              title={t('Remove this scatter')}
              onClick={() => onChange(entries.filter((_, k) => k !== i))}>
              ×
            </button>
          </div>
        )
      })}
      <div className="ga-terrain-scatter-row">
        <button type="button" className="ga-btn ga-btn-sm"
          disabled={entries.length >= MAX_SCATTER_ENTRIES}
          title={entries.length >= MAX_SCATTER_ENTRIES
            ? t('At most {n} scatters per area').replace('{n}', String(MAX_SCATTER_ENTRIES))
            : t('Add another prop to this ground')}
          onClick={() => onChange([...entries, { ...NEW_SCATTER_ENTRY }])}>
          + {t('Scatter')}
        </button>
        <span className="ga-map-chip-label">
          {t('Placement is deterministic per area and skips the footprints of placed locations. Ground covered by an area painted on top of this one stays bare. Switch on “Scatter preview” to see the very points the 3D world plants — the automatic undergrowth of the ground type is grown by the 3D client alone and never appears here.')}
        </span>
      </div>
    </div>
  )
}

/** Server mirrors — `app/models/heightfield.py`. Heights are CLAMPED there
 *  rather than refused, so these are the knobs' range and not a refusal
 *  threshold; the editor simply never sends anything outside them. */
export const HEIGHT_MAX_M = 50
export const FALLOFF_MAX_M = 1000
/** What a freshly drawn height area starts as: a low rise with a ramp that is
 *  walkable AT THE DEFAULT LIMITS — 3 m over 10 m is 0.3 m per metre, under
 *  both the 0.4 m step and the 40° slope. A default that starts out warned
 *  would teach the warning to be ignored. */
export const HEIGHT_DEFAULT_M = 3
export const FALLOFF_DEFAULT_M = 10

/**
 * WHICH PAINTED GROUND CARRIES A WATER MIRROR — asked of the CATALOG since W1
 * (`mapTypes.isWaterKind`, § A16.3 addendum).
 *
 * There is no hardcoded kind id here any more. `meta.water` on the terrain
 * type is the one predicate the server, the bake, the layer table and this
 * editor all ask, so a world whose river is called `lagoon` carves exactly
 * like one whose river is called `water` — and the kind editor can turn any
 * ground into water with a click. The two carved numbers default from the KIND
 * (`waterKindDefaults`) and a painted area may override them.
 *
 * The level has no constant default: it is the MEDIAN HEIGHT ALONG THE RIM of
 * the polygon, which only the server can compute — an unset level says
 * "auto (rim)" and no number.
 */
/**
 * A metre knob with a NAMED clamp — the `WidthField` pattern, with a sign and
 * a limit that says itself. The relief's height and ramp are typed into it,
 * and so are the spacing and the swing of a decorated line.
 *
 * Its own text draft, so a half-typed "−" or "0." is not clamped mid-keystroke;
 * committed on blur and on Enter (which is stopped here, or it would finish
 * the polygon being drawn). It NEVER writes itself: it hands the number up and
 * shows what comes back, so a value the server clamps is not left claimed by
 * the field. The token makes the effect run even when the parent's value did
 * not move.
 *
 * THE CLAMP IS SAID WHILE IT IS TYPED (finding 14, 2026-08-13). It always
 * clamped — 80 became the 50 m of `heightfield.MAX_HEIGHT_M` — but silently,
 * one round trip later, and a mountain that simply refused to grow past a
 * number nobody named reads as a broken field. Typing past the limit now marks
 * the input and names the limit right there. Nothing is refused: the value is
 * still committed, clamped, exactly as the server stores it.
 */
function MetreNum({ label, title, value, step, min, max, onCommit }: {
  label: string; title: string; value: number; step: number
  min: number; max: number; onCommit: (v: number) => void
}) {
  const { t } = useI18n()
  const [draft, setDraft] = useState(String(value))
  const [resync, setResync] = useState(0)
  useEffect(() => { setDraft(String(value)) }, [value, resync])
  const typed = parseFloat(draft)
  // Only a NUMBER can be out of range: a half-typed "−" or "0." is neither
  // wrong nor worth shouting about.
  const over = Number.isFinite(typed) && typed > max
  const under = Number.isFinite(typed) && typed < min
  const commit = () => {
    setResync((n) => n + 1)
    const v = parseFloat(draft)
    if (!Number.isFinite(v)) return
    const c = Math.round(Math.min(max, Math.max(min, v)) * 100) / 100
    if (c !== value) onCommit(c)
  }
  return (
    <label className="ga-terrain-width" title={title}>
      {label}
      <input
        className={'ga-input' + (over || under ? ' ga-tt-invalid' : '')}
        type="number" step={step} min={min} max={max}
        value={draft}
        aria-invalid={over || under}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key !== 'Enter') return
          e.stopPropagation()
          e.currentTarget.blur()
        }}
      />
      m
      {over || under ? (
        <span className="ga-height-clamp">
          {over
            ? t('max {n} m').replace('{n}', String(max))
            : t('min {n} m').replace('{n}', String(min))}
        </span>
      ) : null}
    </label>
  )
}

/** A palette entry: colour swatch plus the type's name. */
function TypeChip({ type, armed, onPick }: {
  type: TerrainType; armed: boolean; onPick: () => void
}) {
  const { t } = useI18n()
  return (
    <button
      type="button"
      className={'ga-terrain-chip' + (armed ? ' armed' : '')}
      onClick={onPick}
      title={type.passable
        ? t('{kind} — passable, speed ×{f}')
          .replace('{kind}', type.kind).replace('{f}', String(type.speed_factor))
        : t('{kind} — impassable').replace('{kind}', type.kind)}
    >
      <span className="ga-terrain-swatch" style={{ background: type.color }} />
      {type.name || type.kind}
    </button>
  )
}

export interface TerrainToolbarProps {
  mode: TerrainMode
  /** The primary switch. `MapTab` maps a subject back onto a canvas mode — it
   *  is the one that knows which half of Terrain the user was last in. */
  onPrimary: (p: MapPrimary) => void
  /** The dependent switch of Terrain and Heights, and where it stands. */
  sub: MapSub
  onSub: (s: MapSub) => void
  /** The effective catalog, already sorted by the server. */
  types: TerrainType[]
  /** The armed kind; empty until one is picked. */
  paintKind: string
  onPaintKind: (kind: string) => void
  /** Which gesture the paint mode is on, and the width the next LINE gets. */
  shape: PaintShape
  onShape: (s: PaintShape) => void
  widthM: number
  onWidth: (m: number) => void
  /** How the next line is BENT: the style, and the two numbers that shape its
   *  deflections. They only apply to `line` and only past `straight`. */
  strokeStyle: StrokeStyle
  onStrokeStyle: (s: StrokeStyle) => void
  spacingM: number
  onSpacingM: (m: number) => void
  amplitudeM: number
  onAmplitudeM: (m: number) => void
  /** The spacing the point budget FORCED on the running draft, or 0 when the
   *  one asked for holds (`mapMath.decorateStroke`). A line drawn coarser than
   *  its own field claims has to say so. */
  cappedSpacingM: number
  /** Vertices in the running draft. */
  draftLen: number
  onCloseDraft: () => void
  onDiscardDraft: () => void
  areaCount: number
  /** The heights mode (§ A16): the two numbers the NEXT drawn area gets, how
   *  many height areas there are, and the walk limit the steepness warning is
   *  measured against. Which gesture is armed is the shared `sub` switch. */
  heightM: number
  onHeightM: (m: number) => void
  falloffM: number
  onFalloffM: (m: number) => void
  heightCount: number
  /** The two walk limits the steepness warning is measured against
   *  (§ A1.3) — the STEP is usually the binding one, see `heightMath`. */
  maxSlopeDeg: number
  maxStepM: number
  /** How coarse the world's relief GRID is right now and the finest it can be,
   *  both straight from the server (`GET /world/height-areas`). 0 = not
   *  answered yet. Shown while the Heights mode is open, as soon as the grid
   *  is coarser than the finest one — see `heightMath.reliefStepNotice`. */
  gridStepM: number
  gridStepDefaultM: number
  /** World props (§ A9a): how many are placed, the server's hard ceiling and
   *  the count from which the badge warns. All three from the server — the
   *  editor never invents a limit of its own. */
  propCount: number
  propMax: number
  propWarnAt: number
  /** The catalog fetch FAILED — an empty palette then means "not loaded",
   *  not "nothing defined", and the way out is Reload, not another click. */
  typesError?: boolean
}

export function TerrainToolbar({
  mode, onPrimary, sub, onSub, types, paintKind, onPaintKind, shape, onShape,
  widthM, onWidth, strokeStyle, onStrokeStyle, spacingM, onSpacingM,
  amplitudeM, onAmplitudeM, cappedSpacingM,
  draftLen, onCloseDraft, onDiscardDraft, areaCount,
  typesError,
  heightM, onHeightM, falloffM, onFalloffM, heightCount, maxSlopeDeg,
  maxStepM, gridStepM, gridStepDefaultM,
  propCount, propMax, propWarnAt,
}: TerrainToolbarProps) {
  const { t } = useI18n()
  const isLine = shape === 'line'
  const primary = primaryOf(mode)
  const drawingHeights = primary === 'heights' && sub === 'new'
  const needFalloff = minFalloffFor(heightM, maxSlopeDeg, maxStepM)
  const nextTooSteep = tooSteep(heightM, falloffM, maxSlopeDeg, maxStepM)
  const stepNotice = reliefStepNotice(gridStepM, gridStepDefaultM)
  const btn = (p: MapPrimary, icon: string, label: string, title: string) => (
    <button
      type="button"
      className={'ga-btn ga-btn-sm' + (primary === p ? ' ga-btn-primary' : '')}
      title={title}
      onClick={() => onPrimary(p)}
    >
      {icon} {label}
    </button>
  )
  const subBtn = (s: MapSub, icon: string, label: string, title: string) => (
    <button
      type="button"
      className={'ga-btn ga-btn-sm' + (sub === s ? ' ga-btn-primary' : '')}
      title={title}
      onClick={() => onSub(s)}
    >
      {icon} {label}
    </button>
  )
  const shapeBtn = (s: PaintShape, icon: string, label: string, title: string) => (
    <button
      type="button"
      className={'ga-btn ga-btn-sm' + (shape === s ? ' ga-btn-primary' : '')}
      title={title}
      onClick={() => onShape(s)}
    >
      {icon} {label}
    </button>
  )
  /** How a line style presents itself. Driven off `STROKE_STYLES`, so the
   *  toolbar offers exactly the styles `decorateStroke` can draw — a fourth
   *  one would appear here by adding it there. */
  const styleWords = (s: StrokeStyle) => (s === 'jagged'
    ? { icon: '⋀', label: t('Jagged'),
      title: t('Triangular spikes of random height, across the line') }
    : s === 'wavy'
      ? { icon: '∿', label: t('Wavy'),
        title: t('A soft wave of random phase and height, across the line') }
      : { icon: '╱', label: t('Straight'),
        title: t('The line exactly as it is clicked') })
  const styleBtn = (s: StrokeStyle) => {
    const w = styleWords(s)
    return (
      <button
        key={s}
        type="button"
        className={'ga-btn ga-btn-sm' + (strokeStyle === s ? ' ga-btn-primary' : '')}
        title={w.title}
        onClick={() => onStrokeStyle(s)}
      >
        {w.icon} {w.label}
      </button>
    )
  }
  return (
    <>
      {/* WHAT is being edited. Three subjects, not four tools: drawing ground
          and reshaping it are the same subject, and listing the two terrain
          gestures here made them look like peers of the location editor. */}
      <span className="ga-terrain-modes">
        {btn('location', '⬚', t('Location'),
          t('Place, move and turn locations'))}
        {btn('terrain', '🖌', t('Terrain'),
          t('Paint the ground: draw new areas, or select one and reshape it'))}
        {btn('heights', '⛰', t('Heights'),
          t('Shape the ground: areas that stand higher or lower than the flat world'))}
        {/* The fourth subject (§ A9a): SINGLE props outside any location. The
            painted ground next door says how densely something grows — only
            this one can say "that rock, there". */}
        {btn('props', '🪵', t('Props'),
          t('Place single props on the world plane: a landmark rock, a signpost, a bench'))}
      </span>
      {/* …and WHETHER a click draws or picks. The same two words under both
          subjects: it is the same question, and two vocabularies for it were
          the reason the heights sub-tools read as something else entirely. */}
      {primary === 'location' || primary === 'props' ? null : (
        <span className="ga-terrain-modes">
          {/* Not the pentagon of the shape buttons next to it: "New" is the
              gesture, "Area/Line" is HOW it draws, and one icon for two
              questions makes them look like the same switch. */}
          {subBtn('new', '✚', t('New'), primary === 'heights'
            ? t('Click the outline of a new height area; click the first point again to close it')
            : t('Draw terrain: an area from its outline, or a line with a width'))}
          {subBtn('select', '✋', t('Select'), primary === 'heights'
            ? t('Click a height area to select it, then drag its points')
            : t('Click an area to select it, then drag its points'))}
        </span>
      )}
      {mode === 'props' ? (
        // The cap badge (§ A9a). Both numbers come from the server, so the
        // editor holds no ceiling of its own: it refuses nothing, it only
        // says how close the world is to the one the server will refuse at.
        <span className={'ga-map-toolbar-info'
          + (propWarnAt > 0 && propCount >= propWarnAt ? ' ga-map-chip-warn' : '')}
          title={propWarnAt > 0 && propCount >= propWarnAt
            ? t('Every world prop is its own draw call — from here on the map gets heavier with each one.')
            : undefined}
        >
          {t('{n} of {max} props').replace('{n}', String(propCount))
            .replace('{max}', String(propMax))}
        </span>
      ) : (
        <span className="ga-map-toolbar-info">
          {mode === 'heights'
            ? t('{n} height areas').replace('{n}', String(heightCount))
            : t('{n} areas').replace('{n}', String(areaCount))}
        </span>
      )}

      {mode === 'paint' ? (
        <>
          {/* WHAT the clicks mean, next to the palette that says what they
              paint. Switching drops a running draft (MapTab) — an outline is
              not a centre line, and reading one as the other would move
              ground nobody drew. */}
          <span className="ga-terrain-modes">
            {shapeBtn('area', '⬟', t('Area'),
              t('Click the outline; click the first point again to close it'))}
            {shapeBtn('line', '➜', t('Line'),
              t('Click a centre line; it becomes an area of the width below'))}
          </span>
          {isLine ? (
            <>
              <WidthField widthM={widthM} onWidth={onWidth} />
              {/* HOW the centre line runs before it is widened. A river bank
                  drawn with the ruler reads as a canal, and the two numbers
                  are only asked for once there is something to shape — a
                  spacing next to a straight line would be a dead knob. */}
              <span className="ga-terrain-modes">
                {STROKE_STYLES.map((s) => styleBtn(s))}
              </span>
              {strokeStyle === 'straight' ? null : (
                <>
                  <MetreNum
                    label={t('Spacing')}
                    title={t('Roughly how far apart the deflections sit along the line. It is an average, not a raster — every deflection has a size of its own.')}
                    value={spacingM} step={1}
                    min={STROKE_SPACING_MIN_M} max={STROKE_SPACING_MAX_M}
                    onCommit={onSpacingM} />
                  <MetreNum
                    label={t('Swing')}
                    title={t('How far the deflections reach out to either side of the clicked line. The ribbon is that much wider than its width alone.')}
                    value={amplitudeM} step={0.5}
                    min={STROKE_AMPLITUDE_MIN_M} max={STROKE_AMPLITUDE_MAX_M}
                    onCommit={onAmplitudeM} />
                </>
              )}
              {/* One area holds `MAX_POINTS` outline points and every centre
                  point costs two of them, so a line long enough to overrun
                  that is drawn coarser instead of being refused on save — and
                  says so, because a line drawn coarser than its own field
                  claims is the kind of silence that gets read as a broken
                  knob. It takes some three kilometres of `wavy` river to get
                  here. */}
              {cappedSpacingM > 0 ? (
                <span className="ga-map-arm warn"
                  title={t('An area may hold {max} outline points, and every point of the centre line spends two of them. The line still gets its style — just at the closest spacing that fits. Shorten the line or set a wider spacing to draw the one you asked for.')
                    .replace('{max}', String(MAX_POINTS))}>
                  {t('Too many deflections for one area — this line is drawn with one every {n} m.')
                    .replace('{n}', String(Math.round(cappedSpacingM * 10) / 10))}
                </span>
              ) : null}
            </>
          ) : null}
        </>
      ) : null}

      {/* The palette and the way into the type editor. The CHIPS only mean
          something while painting (they arm the next stroke), but the link is
          the only door to passability, speed, surface and the move animation
          of a type — and one edits those while looking at the area one drew,
          not while holding a brush (user finding 2026-08-13: the button was
          reachable in Paint alone). */}
      {mode === 'paint' || mode === 'edit-area' ? (
        <span className="ga-terrain-palette">
          {mode !== 'paint' ? null : types.length === 0 ? (
            <span className="ga-map-tray-empty">
              {typesError
                ? t('Terrain types could not be loaded — retry via Reload')
                : t('No terrain types')}
            </span>
          ) : types.map((ty) => (
            <TypeChip key={ty.kind} type={ty} armed={ty.kind === paintKind}
              onPick={() => onPaintKind(ty.kind)} />
          ))}
          {/* The vocabulary is EDITED in its own tab (Terrain), not in a modal
              over the canvas: a ground has five aspects and a dozen fields,
              and the palette is where one notices the vocabulary is missing
              something — not where one wants to author it. The link is a plain
              hash href, which is exactly how this app switches tabs. */}
          <a className="ga-btn ga-btn-sm" href="#/terrain"
            title={t('Open the Terrain tab — add kinds or change colour, surface, passability, speed and relief')}>
            {t('Manage terrain types')}
          </a>
        </span>
      ) : null}

      {mode === 'paint' ? (
        <span className={'ga-map-arm' + (paintKind ? '' : ' warn')}>
            {!paintKind
              ? (typesError
                ? t('Terrain types could not be loaded — retry via Reload')
                : t('Pick a terrain type first'))
              : draftLen === 0
                ? (isLine
                  ? t('Click the map to set the first point of the line')
                  : t('Click the map to set the first point'))
                : (isLine
                  // A line is OPEN: there is no first point to come back to,
                  // so the way to end it has to be said outright.
                  ? t('{n} of {max} points — double-click or Enter finishes the line, Escape discards')
                    .replace('{n}', String(draftLen))
                    .replace('{max}', String(MAX_STROKE_POINTS))
                  : t('{n} of {max} points — click the first one to close, Escape discards')
                    .replace('{n}', String(draftLen))
                    .replace('{max}', String(MAX_DRAFT_POINTS)))}
            {draftLen > 0 ? (
              <>
                <button type="button" className="ga-btn ga-btn-sm"
                  disabled={draftLen < (isLine ? MIN_STROKE_POINTS : MIN_POINTS)}
                  onClick={onCloseDraft}
                  title={isLine
                    ? t('Turn the line into an area and save it')
                    : t('Close the ring and save the area')}>
                  {isLine ? t('Finish') : t('Close')}
                </button>
                <button type="button" className="ga-btn ga-btn-sm"
                  onClick={onDiscardDraft}>
                  {t('Discard')}
                </button>
              </>
            ) : null}
        </span>
      ) : null}

      {/* HOW COARSE THE GROUND'S OVERVIEW GRID IS, permanently, while heights
          are being edited (finding 14). Nobody sets this number — the server
          doubles it until the grid over the whole painted extent fits its
          point budget, so one area drawn far out flattens the small hills of
          every other one. It only appears once the grid IS coarser than the
          finest, which is the state nothing else on screen shows.
          WHAT IT COSTS IS THE DISTANCE, and only that, since the relief is
          delivered twice (§ A16.3): the fine tiles every rule and the near
          ground read are never coarsened. The sentence says so, because a
          warning that sounded like "your world is now walked on a 32 m grid"
          would send the author hunting for a problem that is not there. */}
      {mode === 'heights' && stepNotice ? (
        <span className="ga-map-arm warn" title={t('The relief grid is one shared raster over everything painted in the world. The further apart those areas lie, the coarser it has to be to stay inside the server’s point budget — and support points are what carries a hill. Since the relief is delivered twice, this coarsens the distant view alone: every rule and the ground near a character read the fine height tiles.')}>
          {t('World relief overview step is now {n} m (painted extent forces a coarser grid) — details under {d} m vanish from the DISTANT view; walk rules and the near ground always read the fine height tiles.')
            .replace('{n}', String(stepNotice.stepM))
            .replace('{d}', String(stepNotice.lostUnderM))}
        </span>
      ) : null}

      {mode === 'heights' ? (
        <>
          {drawingHeights ? (
            <>
              <MetreNum
                label={t('Height')}
                title={t('How high the ground stands inside the new area. Negative digs a hollow.')}
                value={heightM} step={0.5}
                min={-HEIGHT_MAX_M} max={HEIGHT_MAX_M} onCommit={onHeightM} />
              <MetreNum
                label={t('Ramp')}
                title={t('Over how many metres before the outline the ground climbs to that height. 0 = a wall at the edge.')}
                value={falloffM} step={0.5}
                min={0} max={FALLOFF_MAX_M} onCommit={onFalloffM} />
              <span className={'ga-map-arm' + (nextTooSteep ? ' warn' : '')}>
                {nextTooSteep
                  ? t('This ramp is too steep for walkers — it needs {n} m or more')
                    .replace('{n}', String(needFalloff))
                  : draftLen === 0
                    ? t('Click the map to set the first point')
                    : t('{n} of {max} points — click the first one to close, Escape discards')
                      .replace('{n}', String(draftLen))
                      .replace('{max}', String(MAX_DRAFT_POINTS))}
                {draftLen > 0 ? (
                  <>
                    <button type="button" className="ga-btn ga-btn-sm"
                      disabled={draftLen < MIN_POINTS}
                      onClick={onCloseDraft}
                      title={t('Close the ring and save the height area')}>
                      {t('Close')}
                    </button>
                    <button type="button" className="ga-btn ga-btn-sm"
                      onClick={onDiscardDraft}>
                      {t('Discard')}
                    </button>
                  </>
                ) : null}
              </span>
            </>
          ) : (
            <span className="ga-map-arm">
              {t('Click a height area to select it')}
            </span>
          )}
        </>
      ) : null}
    </>
  )
}

export interface TerrainLayerHintProps {
  /** The kind unpainted ground has, named for a reader: the catalog's name for
   *  `terrain.default_kind`, or the bare kind when the catalog has no entry
   *  for it. Empty until both answers are in — the sentence then drops the
   *  clause instead of naming a kind nobody confirmed. */
  defaultKindName: string
  /** The long explanation, open or not. The state lives in `MapTab` on
   *  purpose: this block is unmounted whenever the mode is not `paint`, and
   *  help that closed itself every time the user looked at a location would
   *  have to be found a second time. */
  open: boolean
  onOpen: (open: boolean) => void
}

/**
 * What painting DOES to the ground, said out loud — a line under the toolbar,
 * plus the long version behind the "?".
 *
 * It belongs to the paint mode and nowhere else: this is the one place where
 * the layer model becomes an actual decision, because the next ring will sit
 * ON something. Its own block under the toolbar rather than another item in
 * it — a sentence wedged between a palette and a button reflows into a column
 * two words wide and is not read.
 *
 * Read-only, all of it: nothing in here changes the map.
 */
export function TerrainLayerHint({ defaultKindName, open, onOpen }: TerrainLayerHintProps) {
  const { t } = useI18n()
  return (
    <div className="ga-terrain-guide">
      <div className="ga-terrain-hint">
        <span>
          {defaultKindName
            ? t('Areas may overlap — the topmost wins; unpainted ground is {kind}. Reorder via the selection chip.')
              .replace('{kind}', defaultKindName)
            : t('Areas may overlap — the topmost wins. Reorder via the selection chip.')}
        </span>
        <button type="button" className="ga-terrain-help-btn"
          aria-expanded={open}
          title={t('How terrain layers and the line tool work')}
          onClick={() => onOpen(!open)}>
          ?
        </button>
      </div>
      {open ? (
        <div className="ga-terrain-help">
          <p>{t('Every area sits on a layer of its own: where two of them overlap, only the topmost one counts — for the colour on the map and for the answer the server gives about that spot.')}</p>
          <p>{t('Ground nobody painted keeps the default kind, so there is no need to paint a base layer under everything else.')}</p>
          <p>{t('Select an area and use “Bring forward” or “Send back” in its chip to move it one layer at a time.')}</p>
          <p>{t('The Line tool reads your clicks as a centre line and turns it into an area of the width you set; you then edit that area by its centre-line points and its width, not by its outline, until you convert it into an ordinary area.')}</p>
          <p>{t('A jagged or wavy line hangs deflections of random size off that centre line before it is widened — the spacing and the swing say how far apart and how far out. The line is set for the NEXT stroke; an area keeps the style it was drawn with.')}</p>
        </div>
      ) : null}
    </div>
  )
}

/**
 * WHAT A WATER AREA SAYS ABOUT ITSELF (§ A16.3, addendum "Ein Wasser-Gesetz").
 *
 * A lake used to be the one surface in this world that was FLAT, and until the
 * bake knew that, distant terrain kept poking through it: the mirror was drawn
 * on one raster and the ground under it on another, so a coarse level of
 * detail put a green ridge where the near view had water. The bake now presses
 * the bed to `level − depth` under the whole polygon and ramps it back to the
 * untouched land over the shore width, and "is the ground under the water?"
 * has a single answer at every distance.
 *
 * SINCE W1 THE MIRROR IS A PROFILE, not a number. A FLOW DIRECTION tilts it
 * along the flow axis between an upstream and a downstream level, and every
 * one of those two ends may be left open — the rim median of that end's third
 * of the polygon answers then, and the read-back line names what the bake
 * really used. No flow direction = still water = one constant level, the lake
 * of every round before this one.
 *
 * AND SINCE W4a AN AREA DRAWN AS A LINE FLOWS ALONG THAT LINE, so this panel
 * offers EXACTLY ONE flow control and which one depends on the area:
 *
 * * drawn with the line tool → the three-way choice (still / along the line /
 *   against it, `meta.flow_along`), because a river bends and one bearing
 *   cannot say where a meander runs;
 * * an ordinary polygon → the bearing field of W1 (`meta.flow_dir_deg`), which
 *   is the straight axis such an area has and nothing more.
 *
 * NEVER BOTH, and not only for tidiness: the bake lets the line win over the
 * bearing (`heightfield.is_flowing`), so a visible degree field on a drawn
 * river would be a control that changes nothing. The other way round it would
 * be worse — a bearing left over from before the line was drawn keeps flowing
 * the area while the panel says "still" — so the three-way choice CLEARS
 * `flow_dir_deg` whenever it writes.
 *
 * EVERY FIELD MAY BE EMPTY, and empty is the normal state. Depth and shore
 * ramp then come from the KIND (the placeholder names the number in force),
 * the level from the rim, and the bed from the bare world.
 *
 * THE THREE METRE FIELDS ARE TYPED, NOT SWEPT (user request 2026-08-23). A
 * water level is a world height somebody reads off the terrain, a depth and a
 * shore ramp are numbers somebody knows — none of the three is found by
 * dragging, and the track only ate the room the number needed. They keep their
 * clamps, their steps and their "empty = the kind/the rim decides" state; only
 * the slider is gone (`SliderInput slider={false}`). With it goes the level's
 * ±10 m window around an already-set level, which existed so a DRAG could still
 * trim centimetres there: as a clamp on a TYPED field it would refuse the very
 * number the field is for (a lake moved from 2 m to 40 m would silently land at
 * 12). The level therefore accepts the whole world height range, set or not.
 */
function WaterFields({ water, profile, hasLine, kindType, typeList, onWater }: {
  water: TerrainWater
  /** The bake's own mirror for this area (server output) — the read-back of
   *  the two end levels where the author left them open. */
  profile: TerrainWaterProfile | null
  /** Was this area DRAWN AS A LINE (`meta.stroke`)? Then it has an axis of its
   *  own and flows along it; otherwise it is a polygon with a bearing. */
  hasLine: boolean
  /** The area's own terrain type: it carries the depth/ramp DEFAULTS the
   *  empty fields fall back to. */
  kindType: TerrainType | undefined
  /** The whole catalog, for the bed-kind picker. */
  typeList: TerrainType[]
  onWater: (patch: Partial<TerrainWater>) => void
}) {
  const { t } = useI18n()
  const level = water.water_level
  // The two numbers in force where this area authors none — the KIND's, never
  // the module's, so the placeholder shows what the bake will really do.
  const kindDefaults = waterKindDefaults(kindType)
  const flow = water.flow_dir_deg
  // DOES THIS WATER FLOW AT ALL? — the same rule the bake uses
  // (`heightfield.is_flowing`), read off the two authoring fields: a drawn line
  // flows when it says so, a polygon flows when it carries a bearing. Only then
  // is a flow SPEED a control at all: a lake reads `uSpeed`, the kind's
  // still-water dial, and this number would change nothing on it.
  const flowing = hasLine ? !!water.flow_along : flow !== undefined
  // A bed kind the catalog no longer holds stays SELECTABLE, the way a missing
  // surface texture does: it is a legitimate reference to a ground that may
  // come back, and dropping it from the list would rewrite the area on the
  // next save. Water kinds are not offered — a bed of water is a second lake
  // under the first one, and the layer bake would paint one over the other.
  const bed = water.bed_kind || ''
  const bedUnlisted = !!bed && !typeList.some((ty) => ty.kind === bed)
  return (
    <>
      <div className="ga-map-chip-row">
        <SliderInput
          label={t('Water level (m)')}
          title={t('The height the water surface stands at, as a world height in metres. Empty = the server pins it to the median height along the rim of this area.')}
          value={level}
          fallback={0}
          slider={false}
          min={-HEIGHT_MAX_M} max={HEIGHT_MAX_M} step={0.05} fineStep="any"
          clearable placeholder={t('auto (rim)')}
          onChange={(v) => onWater({ water_level: v })}
          onClear={() => onWater({ water_level: undefined })}
          readback={level === undefined
            ? <span className="ga-map-chip-label">{t('auto (rim)')}</span>
            : null}
        />
      </div>
      <div className="ga-map-chip-row">
        <SliderInput
          label={t('Depth (m)')}
          title={t('How far the bed is carved below the water surface. Empty = the depth this terrain kind defaults to.')}
          value={water.water_depth_m}
          fallback={kindDefaults.depthM}
          slider={false}
          min={WATER_DEPTH_MIN_M} max={WATER_DEPTH_MAX_M} step={0.1}
          fineStep="any"
          clearable placeholder={String(kindDefaults.depthM)}
          onChange={(v) => onWater({ water_depth_m: v })}
          onClear={() => onWater({ water_depth_m: undefined })}
        />
        <SliderInput
          label={t('Shore ramp (m)')}
          title={t('Over how many metres the bed climbs back to the untouched land at the water’s edge. 0 = a wall at the shore. Empty = the ramp this terrain kind defaults to.')}
          value={water.shore_ramp_m}
          fallback={kindDefaults.rampM}
          slider={false}
          min={SHORE_RAMP_MIN_M} max={SHORE_RAMP_MAX_M} step={0.5}
          fineStep="any"
          clearable placeholder={String(kindDefaults.rampM)}
          onChange={(v) => onWater({ shore_ramp_m: v })}
          onClear={() => onWater({ shore_ramp_m: undefined })}
        />
      </div>
      {/* THE FLOW — the one control that turns a lake into a river, and which
          one it is depends on what the area IS (W4a). A drawn line flows along
          itself; a polygon flows along a bearing. Exactly one of the two is on
          screen, never both. */}
      {hasLine ? (
        <>
          <div className="ga-map-chip-row">
            <span className="ga-map-chip-label">{t('Flow')}</span>
            <select
              className="ga-input"
              style={{ flex: 1, minWidth: 0 }}
              value={water.flow_along || ''}
              title={t('Which way this water runs along the line it was drawn as. The mirror falls from knot to knot down that line and the ripples follow every bend.')}
              onChange={(e) => onWater({
                flow_along: (e.target.value || undefined) as FlowAlong | undefined,
                // The bearing of W1 is the straight axis this line replaced.
                // The bake ignores it here, so leaving it stored would be a
                // number that acts on nothing — except when the choice goes
                // back to "still", where it would keep the area flowing behind
                // the panel's back. It goes, either way.
                flow_dir_deg: undefined,
              })}
            >
              <option value="">{t('Still')}</option>
              <option value="forward">{t('Along the line')}</option>
              <option value="reverse">{t('Against the line')}</option>
            </select>
          </div>
          <div className="ga-map-chip-row ga-map-chip-label">
            {t('This area was drawn as a line, so its own centre line is the flow axis — “along” runs in the order the points were drawn, “against” the other way. The arrows on the map follow it bend by bend, and the water level falls from one line point to the next; it never runs uphill.')}
          </div>
        </>
      ) : (
        <div className="ga-map-chip-row">
          <SliderInput
            label={t('Flow direction (°)')}
            title={t('Which way this water flows, as a bearing in degrees: 0° south, 90° east, 180° north, 270° west. It tilts the mirror between an upstream and a downstream level and points the ripples the same way. Empty = still water — one level everywhere, which is what a lake is.')}
            value={flow}
            fallback={0}
            min={FLOW_DIR_MIN_DEG} max={FLOW_DIR_MAX_DEG} step={5} fineStep="any"
            clearable placeholder={t('still')}
            unit="°"
            onChange={(v) => onWater({ flow_dir_deg: v })}
            onClear={() => onWater({ flow_dir_deg: undefined })}
            readback={
              <span className="ga-map-chip-label">
                {flow === undefined ? t('still water (lake)') : flowCompass(flow)}
              </span>
            }
          />
        </div>
      )}
      {/* HOW FAST IT RUNS (finding 2026-08-23 no. 2, `meta.flow_speed_m_s`).
          ONLY ON FLOWING WATER, and that is not tidiness: the shader reads the
          still-water dial on a lake, so this number would sit there doing
          nothing at all. It is an OVERRIDE — empty means the water's surface
          KIND answers, which is where a world speeds up every river at once.
          A number left behind by an area that has since been set back to
          "still" is NOT cleared: unlike the bearing of W4a it acts on nothing
          while the water stands, and it is the speed the author picked for the
          moment the flow comes back. */}
      {flowing ? (
        <>
          <div className="ga-map-chip-row">
            <SliderInput
              label={t('Flow speed (m/s)')}
              title={t('How fast this one water runs, in metres per second. Empty = the speed of its surface kind. It changes the ripple and nothing else — the bed, the mirror and the flow direction stay exactly as they are.')}
              value={water.flow_speed_m_s}
              fallback={FLOW_SPEED_DEFAULT_M_S}
              slider={false}
              min={FLOW_SPEED_MIN_M_S} max={FLOW_SPEED_MAX_M_S} step={0.01}
              clearable
              placeholder={t('kind ({n} m/s)')
                .replace('{n}', String(FLOW_SPEED_DEFAULT_M_S))}
              unit="m/s"
              onChange={(v) => onWater({ flow_speed_m_s: v })}
              onClear={() => onWater({ flow_speed_m_s: undefined })}
            />
          </div>
          <div className="ga-map-chip-row ga-map-chip-label">
            {t('Empty = the flow speed of this water’s surface kind ({n} m/s unless that kind was dialled elsewhere), so one setting speeds up every river of a world and this field is for the single torrent that differs. 0 stops the current without turning the water into a lake.')
              .replace('{n}', String(FLOW_SPEED_DEFAULT_M_S))}
          </div>
        </>
      ) : null}
      {/* WHAT THE BAKE READ BACK. Where the author leaves an end open, the rim
          median of that third answers — a number only the server can compute,
          so it is shown rather than re-derived here.
          FLOWING IS "AT LEAST TWO KNOTS", once and for both kinds of area: the
          profile's axis is one knot for still water, so the very same test
          covers the bearing river of W1 and the drawn one of W4a without this
          panel reading either authoring field a second time. */}
      {profile && profile.axis.length >= 2 ? (
        <div className="ga-map-chip-row ga-map-chip-label">
          {t('The bake carves this water from {up} m upstream down to {down} m downstream.')
            .replace('{up}', profile.level_up.toFixed(2))
            .replace('{down}', profile.level_down.toFixed(2))}
        </div>
      ) : null}
      {/* THE KNOTS THEMSELVES — the levels the bake measured along the line, in
          flow order. On a bent river the two ends above say almost nothing:
          they cannot show that the middle of the run sits between them, nor
          that it never climbs back (the bake's running minimum). This does,
          and it is READ-ONLY — every one of these numbers is derived from the
          ground the line crosses, and the only knots an author may set are the
          two ends, through the level fields above. */}
      {profile && profile.axis.length >= 2 ? (
        <div className="ga-map-chip-row ga-map-chip-label">
          {t('Levels along the line: {levels} m')
            .replace('{levels}', profile.axis
              .map((knot) => knot[3].toFixed(1)).join(' → '))}
        </div>
      ) : null}
      {/* THE BED — what the layer bake paints UNDER this water. Since W1 a
          water layer never paints its own texture on the ground: the mirror is
          its own surface above, and painting the lake twice had the two work
          against each other. */}
      <div className="ga-map-chip-row">
        <span className="ga-map-chip-label">{t('Bed kind')}</span>
        <select
          className="ga-input"
          style={{ flex: 1, minWidth: 0 }}
          value={bed}
          title={t('Which ground the bake paints under this water — sand, gravel, rock. Empty = the bare world, the ground that is there anyway.')}
          onChange={(e) => onWater({ bed_kind: e.target.value || undefined })}
        >
          <option value="">{t('— bare world —')}</option>
          {bedUnlisted ? (
            <option value={bed}>{`${bed} ${t('(missing)')}`}</option>
          ) : null}
          {typeList.filter((ty) => !isWaterKind(ty)).map((ty) => (
            <option key={ty.kind} value={ty.kind}>{ty.name || ty.kind}</option>
          ))}
        </select>
      </div>
      <div className="ga-map-chip-row ga-map-chip-label">
        {t('This keeps terrain from poking through the water at any distance: the world height field is carved down to the water level minus the depth and ramped back up to the land over the shore width, so every level of detail stays below the same mirror. Depth and shore ramp are empty until this one area needs its own — the terrain kind answers otherwise, and the level comes from the rim.')}
      </div>
    </>
  )
}

/**
 * HOW BUMPY THIS ONE AREA IS (§ A16.2) — two numbers, typed, not swept.
 *
 * The micro-relief is BAKED into the world heightfield: random small hills
 * wherever this area lies, in the one field the walk rules, the server gate and
 * both renderers read. Nothing renders it separately, so what is set here moves
 * the ground itself, exactly as a height area does.
 *
 * IT IS A PROPERTY OF THIS AREA, NOT OF ITS KIND (decision 2026-08-23), which
 * is why the fields live in this panel and not in the Terrain tab any more. A
 * kind-level amplitude made every meadow of a world equally bumpy; "grass" can
 * now be a rolling upland in one place and a flat pasture in the next. The
 * pattern still comes from the kind (the noise seed is a hash of its name), so
 * two neighbouring areas of one kind with the same two numbers still have no
 * seam between them.
 *
 * EMPTY IS THE NORMAL STATE: no amplitude = flat ground, no wave = the server's
 * 32 m swell. The numbers go out UNCLAMPED — the server clamps and the panel
 * refills from what it stored, so a typed 5 comes back as the stored 2.
 *
 * THE STEEPNESS WARNING under them is informative and clamps nothing: from
 * `tile_step_m · tan(max_slope_deg) / 2` on, the worst flank the noise can
 * build between two support points is steeper than the walk gate lets anybody
 * climb, and single spots of this ground turn into obstacles. Both numbers come
 * from the server; without them the line simply says nothing.
 */
function ReliefFields({ relief, warnAmpM, onRelief }: {
  relief: TerrainRelief
  /** From which amplitude the hills outclimb the walk gate, in metres — or
   *  null while the server has not answered the two numbers it is made of. */
  warnAmpM: number | null
  onRelief: (patch: Partial<TerrainRelief>) => void
}) {
  const { t } = useI18n()
  const amp = relief.relief_amplitude_m
  // The typed value is CLAMPED before it is judged, exactly as the server will
  // store it: warning about a typed 5 would name a ground nobody ever gets.
  const ampClamped = amp === undefined
    ? undefined
    : Math.min(RELIEF_AMP_MAX_M, Math.max(RELIEF_AMP_MIN_M, amp))
  const steep = warnAmpM !== null && ampClamped !== undefined
    && ampClamped > warnAmpM
  return (
    <>
      <div className="ga-map-chip-row">
        {/* step 0.1: the number field's up/down arrows walk in tenths of a
            metre (user 2026-08-23) — with fineStep "any" the browser stepped
            them by a whole metre. Typing stays free: commit rounds to the
            step's decimals, which one decimal is. */}
        <SliderInput
          label={t('Relief amplitude (m)')}
          title={t('How high the random small hills of this area stand, in metres. It is baked into the world heightfield, so figures walk over it. Empty = flat ground.')}
          value={amp}
          fallback={0}
          slider={false}
          min={RELIEF_AMP_MIN_M} max={RELIEF_AMP_MAX_M} step={0.1}
          clearable placeholder={t('flat')}
          onChange={(v) => onRelief({ relief_amplitude_m: v })}
          onClear={() => onRelief({ relief_amplitude_m: undefined })}
        />
        <SliderInput
          label={t('Relief wavelength (m)')}
          title={t('How wide ONE swell of those hills is, in metres — small values make a choppy field, large ones a gentle roll. Empty = the server’s {n} m.')
            .replace('{n}', String(RELIEF_WAVE_DEFAULT_M))}
          value={relief.relief_wave_m}
          fallback={RELIEF_WAVE_DEFAULT_M}
          slider={false}
          min={RELIEF_WAVE_MIN_M} max={RELIEF_WAVE_MAX_M} step={1}
          fineStep="any"
          clearable placeholder={String(RELIEF_WAVE_DEFAULT_M)}
          onChange={(v) => onRelief({ relief_wave_m: v })}
          onClear={() => onRelief({ relief_wave_m: undefined })}
        />
      </div>
      {steep ? (
        <div className="ga-map-chip-row ga-map-chip-warn">
          {t('Above ~{max} m the random hills get steeper than walkers can climb — spots of this area become impassable.')
            .replace('{max}', (warnAmpM as number).toFixed(2))}
        </div>
      ) : null}
    </>
  )
}

export interface TerrainAreaChipProps {
  area: TerrainArea
  types: Record<string, TerrainType>
  /** The catalog in display order, for the kind palette. */
  typeList: TerrainType[]
  /** The catalog fetch FAILED — then NO area can be named and the hint must
   *  say that, instead of blaming every single one of them on the user. */
  typesError?: boolean
  /** The area's stroke recipe, already CHECKED (`MapTab.readStroke`) — null
   *  for an ordinary painted area. */
  stroke: TerrainStroke | null
  onKind: (kind: string) => void
  /** Move one layer up (+1) or down (−1). */
  onZOrder: (delta: number) => void
  /** New width for a stroke area — the polygon is regenerated from it. */
  onWidth: (m: number) => void
  /** What this area GROWS (`meta.scatter`, already checked by the caller) and
   *  the prop library its model picker offers. */
  scatter: TerrainScatterEntry[]
  props: PropRef[]
  /** The area's water numbers, already CHECKED (`mapTypes.readWater`). Only
   *  an area of a WATER KIND (`meta.water`) shows them; every other one
   *  carries an empty object and the chip says nothing about water. */
  water: TerrainWater
  /** The bake's own mirror for this area (`meta.water_profile`, server
   *  output) — null for still water and for anything that is not water. */
  waterProfile: TerrainWaterProfile | null
  /** The area's own MICRO-RELIEF, already CHECKED (`mapTypes.readRelief`).
   *  Every area may carry it — it is the shape's property, not the kind's. */
  relief: TerrainRelief
  /** From which amplitude those hills outclimb the walk gate, in metres
   *  (`heightMath.reliefWarnAmpM` out of the server's own two numbers), or
   *  null while the server has not answered them. */
  reliefWarnAmpM: number | null
  /** The preview colour of the n-th entry — the same one the map draws. */
  scatterColor: (index: number) => string
  onScatter: (entries: TerrainScatterEntry[]) => void
  /** Write one or more water numbers. `undefined` in the patch DROPS the key,
   *  which hands the field back to the server's default. */
  onWater: (patch: Partial<TerrainWater>) => void
  /** The same for the two relief numbers — `undefined` DROPS the key, which is
   *  how "flat" and "the default wave" are written. */
  onRelief: (patch: Partial<TerrainRelief>) => void
  /** Drop `meta.stroke` and keep the polygon: the area becomes an ordinary
   *  one, editable point by point. One way, hence the confirmation. */
  onConvert: () => void
  onDelete: () => void
  onClose: () => void
}

/**
 * The selected area, floating over the canvas — the same chip pattern the
 * location selection uses. Deleting arms an inline confirmation row (no
 * `window.confirm`); the state is local because the chip is remounted per area
 * (`key`), so a fresh selection is never half-armed.
 *
 * An area whose kind the catalog no longer knows can only do ONE thing: get a
 * kind. Every other write is a full replace whose unknown `kind` the server
 * rejects before it reads anything else, so reshaping and re-layering are shut
 * off — and the chip SAYS why instead of leaving three dead buttons to be
 * discovered by clicking them. Deleting stays open: erasing needs no kind, and
 * it is the other honest answer to an area nobody can name any more.
 *
 * A STROKE area is the same area with a recipe attached. Its chip counts the
 * line's points instead of the polygon's (those are what the handles edit),
 * carries the width, and offers the one-way exit: converting it drops the
 * recipe, keeps the polygon and hands the outline back to the point editor.
 *
 * What the area GROWS is edited here too (finding B17), folded away until
 * asked for — see `ScatterEditor`.
 */
export function TerrainAreaChip({
  area, types, typeList, typesError, stroke, scatter, props, water,
  waterProfile, relief, reliefWarnAmpM, scatterColor,
  onKind, onZOrder, onWidth, onScatter, onWater, onRelief, onConvert, onDelete,
  onClose,
}: TerrainAreaChipProps) {
  const { t } = useI18n()
  const [armed, setArmed] = useState(false)
  const [convArmed, setConvArmed] = useState(false)
  const [scatterOpen, setScatterOpen] = useState(false)
  const known = types[area.kind]
  return (
    <div className="ga-map-chip">
      <div className="ga-map-chip-head">
        <span className="ga-terrain-swatch"
          style={{ background: typeColor(types, area.kind) }} />
        <strong>{known?.name || area.kind}</strong>
        {stroke ? <span className="ga-map-chip-tag">{t('line')}</span> : null}
        {/* WHICH line, when it is not the plain one. The style is set for the
            NEXT line in the toolbar; here it is a read-out, so an area whose
            outline nobody can place any more can at least be recognised. */}
        {stroke && stroke.style && stroke.style !== 'straight' ? (
          <span className="ga-map-chip-tag">
            {stroke.style === 'jagged' ? t('jagged') : t('wavy')}
          </span>
        ) : null}
        {/* Layering sits in the header as two arrows, right next to the close
            button: it is the one action used again and again while stacking
            areas, and a full button row buys it nothing. The disabled state is
            the same one every other write carries — an area whose kind the
            catalog no longer knows cannot be re-layered either. */}
        <button type="button" className="ga-modal-close ga-map-chip-z"
          disabled={!known}
          title={t('Bring forward') + ' — ' + t('Draw this area over the ones around it')}
          aria-label={t('Bring forward')}
          onClick={() => onZOrder(1)}>↑</button>
        <button type="button" className="ga-modal-close ga-map-chip-z"
          disabled={!known}
          title={t('Send back') + ' — ' + t('Draw this area under the ones around it')}
          aria-label={t('Send back')}
          onClick={() => onZOrder(-1)}>↓</button>
        <button type="button" className="ga-modal-close"
          title={t('Clear selection')} onClick={onClose}>×</button>
      </div>
      <div className="ga-map-chip-row">
        {known ? (
          <span>
            {stroke
              ? t('{n} line points · {m} in the outline')
                .replace('{n}', String(stroke.points.length))
                .replace('{m}', String(area.polygon.length))
              : t('{n} points').replace('{n}', String(area.polygon.length))}
          </span>
        ) : (
          <span className="ga-map-chip-warn">
            {t('Unknown terrain type “{kind}”').replace('{kind}', area.kind)}
          </span>
        )}
        <span className="ga-map-chip-pos">{t('layer {n}').replace('{n}', String(area.z_order))}</span>
      </div>
      {/* HOW MUCH GROUND THIS AREA COVERS. The point count says how the shape
          is BUILT and nothing about how big it is — a four-corner rectangle can
          be a courtyard or a whole valley — and the size is what a scatter
          density (per 100 m²), a bake cost and a walk across it are read
          against. Every kind of area, not just water: it is geometry, and the
          kind has no say in it. For an area drawn as a LINE this is the
          generated ribbon, which is the ground it really covers; its centre
          line has no area at all. */}
      <div className="ga-map-chip-row ga-map-chip-label">
        {t('Area: {area}').replace('{area}',
          formatAreaM2(polygonAreaM2(area.polygon)))}
      </div>
      {stroke && known ? (
        <div className="ga-map-chip-row">
          <WidthField widthM={stroke.width_m} onWidth={onWidth} />
        </div>
      ) : null}
      <div className="ga-map-chip-row">
        <span className="ga-map-chip-label">{t('Type')}</span>
      </div>
      <div className="ga-terrain-palette">
        {typeList.map((ty) => (
          <TypeChip key={ty.kind} type={ty} armed={ty.kind === area.kind}
            onPick={() => onKind(ty.kind)} />
        ))}
      </div>
      {/* THE WATER MIRROR (§ A16.3, W1). Not folded away like the scatter: an
          area that is water has these numbers and nothing else to say about
          them, and the level is the field the shore optics hang on. WHICH
          areas are water is the CATALOG's answer (`meta.water`) and never the
          kind's name — an area whose kind the catalog no longer knows cannot
          be written at all, so it does not offer them either. */}
      {isWaterKind(known) ? (
        <WaterFields water={water} profile={waterProfile} kindType={known}
          hasLine={!!stroke && stroke.points.length >= 2}
          typeList={typeList} onWater={onWater} />
      ) : null}
      {/* HOW BUMPY THIS AREA IS (§ A16.2). Not folded away and not limited to
          one sort of ground: since 2026-08-23 the micro-relief is the AREA's
          own, so every area may say it — a water area included, whose bed the
          hills roughen under the mirror. An area whose kind the catalog no
          longer knows cannot be written at all, hence the same gate every
          other write here carries. */}
      {known ? (
        <ReliefFields relief={relief} warnAmpM={reliefWarnAmpM}
          onRelief={onRelief} />
      ) : null}
      {/* What grows here (finding B17). Folded away by default: most areas
          grow nothing, and an area is selected far more often to be reshaped
          or re-layered than to be planted. An area whose kind the catalog no
          longer knows cannot be written at all (every write is a full replace
          the server rejects on the kind), so it does not offer this either. */}
      <div className="ga-map-chip-row">
        <button type="button"
          className={'ga-btn ga-btn-sm' + (scatter.length ? ' ga-tt-scatter-on' : '')}
          disabled={!known}
          aria-expanded={scatterOpen}
          title={t('What grows on this area — props, how many per 100 m², how tall')}
          onClick={() => setScatterOpen((o) => !o)}>
          {t('Scatter')}
          {scatter.length ? ` (${scatter.length})` : ` — ${t('none')}`}
          {scatterOpen ? ' ▾' : ' ▸'}
        </button>
      </div>
      {scatterOpen && known ? (
        <ScatterEditor entries={scatter} props={props} colorOf={scatterColor}
          onChange={onScatter} />
      ) : null}
      <div className="ga-map-chip-actions">
        {stroke && known ? (
          convArmed ? (
            <>
              <button type="button" className="ga-btn ga-btn-sm ga-btn-danger"
                onClick={() => { setConvArmed(false); onConvert() }}>
                {t('Really convert')}
              </button>
              <button type="button" className="ga-btn ga-btn-sm"
                onClick={() => setConvArmed(false)}>
                {t('Cancel')}
              </button>
            </>
          ) : (
            <button type="button" className="ga-btn ga-btn-sm"
              title={t('Keep the shape, drop the line: the outline becomes editable point by point. This cannot be undone.')}
              onClick={() => setConvArmed(true)}>
              {t('Convert to area')}
            </button>
          )
        ) : null}
        {armed ? (
          <>
            <button type="button" className="ga-btn ga-btn-sm ga-btn-danger"
              onClick={() => { setArmed(false); onDelete() }}>
              {t('Really delete')}
            </button>
            <button type="button" className="ga-btn ga-btn-sm"
              onClick={() => setArmed(false)}>
              {t('Cancel')}
            </button>
          </>
        ) : (
          <button type="button" className="ga-btn ga-btn-sm"
            title={t('Erase this painted area')}
            onClick={() => setArmed(true)}>
            {t('Delete area')}
          </button>
        )}
      </div>
      <div className={'ga-map-chip-row ' + (known ? 'ga-map-chip-label' : 'ga-map-chip-warn')}>
        {known
          ? (stroke
            ? t('Drag a line point to move it · double-click removes it · click between two to add one')
            : t('Drag a point to move it · double-click removes it · click an edge to add one'))
          : (typesError
            ? t('Terrain types could not be loaded — retry via Reload')
            : t('Pick a terrain type first'))}
      </div>
    </div>
  )
}

export interface TerrainAreaListProps {
  /** The areas to offer, TOPMOST FIRST. Filtering (what is on screen) and
   *  ordering are the caller's — `MapTab` owns the view, this only draws. */
  areas: TerrainArea[]
  /** The effective catalog by kind, for colour and name. */
  types: Record<string, TerrainType>
  selectedId: string
  onSelect: (id: string) => void
}

/**
 * The painted areas in view, as a list — the second way to select one.
 *
 * The canvas hit test can only ever return the TOPMOST polygon under the
 * cursor (that is what makes it agree with the engine about which kind is at a
 * spot). Where two areas overlap, the lower one is therefore unreachable by
 * clicking, and no click sequence gets to it (finding 5). Naming all of them
 * does, and it costs no new gesture on the canvas.
 *
 * Ordered the way the map is read: the area drawn LAST is the one the eye
 * sees, so it is named first. The row says the type's colour, the type's name
 * and which layer the area sits on — the three things that tell two areas of
 * the same kind apart, and the same wording the chip uses.
 */
export function TerrainAreaList({
  areas, types, selectedId, onSelect,
}: TerrainAreaListProps) {
  const { t } = useI18n()
  return (
    <div className="ga-map-tray-section">
      <div className="ga-map-tray-title">{t('Terrain areas')}</div>
      {areas.length === 0 ? (
        <div className="ga-map-tray-empty">{t('No areas in view')}</div>
      ) : (
        <div className="ga-map-tray-items ga-map-tray-areas">
          {areas.map((a) => (
            <button
              key={a.id}
              type="button"
              className={'ga-map-tray-item'
                + (a.id === selectedId ? ' selected' : '')}
              onClick={() => onSelect(a.id)}
              title={t('Select this area — the topmost one is listed first')}
            >
              <span className="ga-terrain-swatch"
                style={{ background: typeColor(types, a.kind) }} />
              <span className="ga-map-tray-name">
                {types[a.kind]?.name || a.kind}
              </span>
              <span className="ga-map-tray-stamp">
                {t('layer {n}').replace('{n}', String(a.z_order))}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

export interface HeightAreaListProps {
  /** The height areas to offer, newest first — filtering (what is on screen)
   *  and ordering are the caller's, exactly as for `TerrainAreaList`. */
  areas: HeightArea[]
  selectedId: string
  onSelect: (id: string) => void
  /** The two walk limits, so a ramp nobody can walk up is marked in the list
   *  as well as on the map (§ A1.3). */
  maxSlopeDeg: number
  maxStepM: number
}

/**
 * The height areas in view, as a list — the same second way in the painted
 * areas have.
 *
 * A relief area has no name, so the row says what an author actually tells two
 * of them apart by: which way the ground goes (colour and sign), how far, and
 * how wide the ramp is. Overlapping relief is as unreachable by clicking as
 * overlapping terrain — the canvas can only answer with one polygon — and this
 * is the way to the one underneath.
 */
export function HeightAreaList({
  areas, selectedId, onSelect, maxSlopeDeg, maxStepM,
}: HeightAreaListProps) {
  const { t } = useI18n()
  return (
    <div className="ga-map-tray-section">
      <div className="ga-map-tray-title">{t('Height areas')}</div>
      {areas.length === 0 ? (
        <div className="ga-map-tray-empty">{t('No height areas in view')}</div>
      ) : (
        <div className="ga-map-tray-items ga-map-tray-areas">
          {areas.map((a) => {
            const steep = tooSteep(a.height_m, a.falloff_m, maxSlopeDeg, maxStepM)
            return (
              <button
                key={a.id}
                type="button"
                className={'ga-map-tray-item'
                  + (a.id === selectedId ? ' selected' : '')}
                onClick={() => onSelect(a.id)}
                title={steep
                  ? t('Select this height area — its ramp is too steep for walkers')
                  : t('Select this height area')}
              >
                <span className="ga-terrain-swatch"
                  style={{ background: heightColor(a.height_m) }} />
                <span className="ga-map-tray-name">
                  {(steep ? '⚠ ' : '') + fmtHeight(a.height_m)}
                </span>
                <span className="ga-map-tray-stamp">
                  {t('ramp {n} m').replace('{n}', String(a.falloff_m))}
                </span>
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}

export interface MapDisplayPanelProps {
  /** Folded or not. Session state in `MapTab` like the switches themselves. */
  open: boolean
  onOpen: (open: boolean) => void
  scatterPreview: boolean
  onScatterPreview: (on: boolean) => void
  locations: boolean
  onLocations: (on: boolean) => void
  roofs: boolean
  /** The roof switch takes no argument — flipping it also drops the rendered
   *  pictures, which is how they are refreshed (see `MapTab`). */
  onRoofs: () => void
  /** The zoom is under the budget gate: the switch says so instead of showing
   *  empty squares that read as "there are no models". */
  roofsZoomedOut: boolean
  roofMinPxPerM: number
}

/**
 * What the map DRAWS — three switches that change nothing about the world.
 *
 * They sit in the tray, not in the toolbar, and folded away by default: they
 * are set once and then looked at rarely, while the toolbar next to them is
 * where every gesture is armed. Mixing "what am I editing" with "what can I
 * see" in one row was what made that row unreadable (user finding 2026-08-13).
 *
 * Folded, the header still SAYS what is not in its default state. Two of these
 * switches explain something the user would otherwise see as a defect — an
 * empty map (locations off) and footprints without roofs (zoomed out) — and
 * hiding the cause behind a chevron would turn a setting into a mystery. The
 * markers are the same icons as the switches, so the fold is the only thing
 * the panel hides.
 */
export function MapDisplayPanel({
  open, onOpen, scatterPreview, onScatterPreview, locations, onLocations,
  roofs, onRoofs, roofsZoomedOut, roofMinPxPerM,
}: MapDisplayPanelProps) {
  const { t } = useI18n()
  // What is NOT at its default — a marker for the header, a sentence for the
  // tooltip. Both are built from the same three questions, in the order the
  // switches stand in.
  const marks: string[] = []
  const said: string[] = []
  if (scatterPreview) {
    marks.push('🌲')
    said.push(t('Scatter preview is on'))
  }
  if (!locations) {
    marks.push('📍 ' + t('off'))
    said.push(t('The locations are switched off — the map draws no footprints'))
  } else if (roofs && roofsZoomedOut) {
    marks.push('🏢 ' + t('(zoom in)'))
    said.push(t('Zoom in to at least {n} px per metre to see the roofs')
      .replace('{n}', String(roofMinPxPerM)))
  } else if (roofs) {
    marks.push('🏢')
    said.push(t('The building roofs are on'))
  }
  const base = t('What the map draws — none of it changes the world')
  return (
    <div className="ga-map-tray-section">
      <button type="button" className="ga-map-tray-toggle"
        aria-expanded={open}
        title={!open && said.length ? base + ' — ' + said.join(' · ') : base}
        onClick={() => onOpen(!open)}>
        <span className="ga-map-tray-title">{t('Display')}</span>
        {!open && marks.length ? (
          <span className="ga-map-tray-flags">{marks.join(' ')}</span>
        ) : null}
        <span>{open ? '▾' : '▸'}</span>
      </button>
      {open ? (
        <div className="ga-map-tray-checks">
          <label className="ga-map-toolbar-check"
            title={t('Show what the areas grow, as dots. Zoomed in it draws exactly the props the 3D world plants; zoomed out too far for that, a thinned sample that says on the map which fraction of the density it shows. Footprints of placed locations stay clear either way.')}>
            <input type="checkbox" checked={scatterPreview}
              onChange={(e) => onScatterPreview(e.target.checked)} />
            🌲 {t('Scatter preview')}
          </label>
          {/* Locations are a VIEW too, and the one that can be IN THE WAY: a
              footprint is drawn with an opaque picture, so ground and relief
              points underneath it are neither visible nor grabbable (finding
              6). Switching the layer off is the way to them; it changes
              nothing about the world, and nothing is placed or moved while it
              is off (the layer takes no pointer events at all). */}
          <label className="ga-map-toolbar-check"
            title={t('Draw the placed locations. Switch them off to reach ground and relief points that lie under a building.')}>
            <input type="checkbox" checked={locations}
              onChange={(e) => onLocations(e.target.checked)} />
            📍 {t('Locations')}
          </label>
          {/* With the locations off there is nothing to draw a roof into, so
              the switch says so instead of doing nothing. */}
          <label className="ga-map-toolbar-check"
            title={locations
              ? (roofsZoomedOut
                ? t('Zoom in to at least {n} px per metre to see the roofs')
                  .replace('{n}', String(roofMinPxPerM))
                : t('Show each building model from above inside its footprint. Switch off and on again to refresh the pictures.'))
              : t('Switch the locations back on to see the roofs')}>
            <input type="checkbox" checked={roofs} onChange={onRoofs}
              disabled={!locations} />
            🏢 {t('Building roofs')}
            {roofsZoomedOut && locations ? ' ' + t('(zoom in)') : ''}
          </label>
        </div>
      ) : null}
    </div>
  )
}

export interface HeightAreaChipProps {
  area: HeightArea
  /** The two walk limits (worldmap payload, § A1.3). */
  maxSlopeDeg: number
  maxStepM: number
  onHeight: (m: number) => void
  onFalloff: (m: number) => void
  onDelete: () => void
  onClose: () => void
}

/**
 * The selected HEIGHT area — the same floating chip the terrain and the
 * locations use, with the two numbers that make a relief.
 *
 * The steepness line is the point of it. A ramp climbs its full height over
 * exactly `falloff_m` metres, so its gradient is fixed the moment both numbers
 * are set, and a plateau whose flank is steeper than `max_slope_deg` is sealed
 * against every walker — server AND client refuse the step (§ A15 Nr. 8). That
 * is a legitimate thing to build (a mesa reached through an opening) and a
 * miserable thing to build by accident, so it is said out loud, with the width
 * that would fix it, and nothing is refused.
 *
 * The warning is about THIS area and nothing else. A location dropped on the
 * flank may soften it — a BUILT one stamps its own plateau into the height
 * field (plan "Ein Boden" § 2 G5) — but which locations are built is the
 * server's classification, so that is said once as a side note and never
 * counted on as a plateau the editor can predict.
 *
 * Deleting arms an inline confirmation (no `window.confirm`); the state is
 * local because the chip is remounted per area (`key`).
 */
export function HeightAreaChip({
  area, maxSlopeDeg, maxStepM, onHeight, onFalloff, onDelete, onClose,
}: HeightAreaChipProps) {
  const { t } = useI18n()
  const [armed, setArmed] = useState(false)
  const need = minFalloffFor(area.height_m, maxSlopeDeg, maxStepM)
  const steep = tooSteep(area.height_m, area.falloff_m, maxSlopeDeg, maxStepM)
  return (
    <div className="ga-map-chip">
      <div className="ga-map-chip-head">
        <strong>{fmtHeight(area.height_m)}</strong>
        <span className="ga-map-chip-tag">
          {area.height_m < 0 ? t('hollow') : t('rise')}
        </span>
        <button type="button" className="ga-modal-close"
          title={t('Clear selection')} onClick={onClose}>×</button>
      </div>
      <div className="ga-map-chip-row">
        <span>{t('{n} points').replace('{n}', String(area.polygon.length))}</span>
      </div>
      <div className="ga-map-chip-row">
        <MetreNum
          label={t('Height')}
          title={t('How high the ground stands inside this area. Negative digs a hollow.')}
          value={area.height_m} step={0.5}
          min={-HEIGHT_MAX_M} max={HEIGHT_MAX_M} onCommit={onHeight} />
        <MetreNum
          label={t('Ramp')}
          title={t('Over how many metres before the outline the ground climbs to that height. 0 = a wall at the edge.')}
          value={area.falloff_m} step={0.5}
          min={0} max={FALLOFF_MAX_M} onCommit={onFalloff} />
      </div>
      <div className={'ga-map-chip-row ' + (steep ? 'ga-map-chip-warn' : 'ga-map-chip-label')}>
        {steep
          ? t('Too steep for walkers: this height needs a ramp of at least {n} m to stay under the {deg}° slope and the {step} m step a walker takes. Nobody will climb this flank — only openings lead up here.')
            .replace('{n}', String(need))
            .replace('{deg}', String(Math.round(maxSlopeDeg)))
            .replace('{step}', String(maxStepM))
          : t('Walkable: the ramp stays under the {deg}° slope and the {step} m step a walker takes.')
            .replace('{deg}', String(Math.round(maxSlopeDeg)))
            .replace('{step}', String(maxStepM))}
      </div>
      {/* The side note about placements: a built location standing here
          stamps its own plateau, a natural one lets this relief run straight
          through. The rule is stated, never re-derived here. */}
      <div className="ga-map-chip-row ga-map-chip-label">
        {t('Ground is levelled automatically under built locations.')}
      </div>
      <div className="ga-map-chip-actions">
        {armed ? (
          <>
            <button type="button" className="ga-btn ga-btn-sm ga-btn-danger"
              onClick={() => { setArmed(false); onDelete() }}>
              {t('Really delete')}
            </button>
            <button type="button" className="ga-btn ga-btn-sm"
              onClick={() => setArmed(false)}>
              {t('Cancel')}
            </button>
          </>
        ) : (
          <button type="button" className="ga-btn ga-btn-sm"
            title={t('Remove this height area — the ground here goes flat again')}
            onClick={() => setArmed(true)}>
            {t('Delete height area')}
          </button>
        )}
      </div>
      <div className="ga-map-chip-row ga-map-chip-label">
        {t('Drag a point to move it · double-click removes it · click an edge to add one')}
      </div>
    </div>
  )
}
