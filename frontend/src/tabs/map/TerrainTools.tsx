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
import type { PropRef } from '../../lib/refs'
import { fmtHeight, heightColor } from './HeightLayer'
import { minFalloffFor, tooSteep } from './heightMath'
import { typeColor } from './TerrainLayer'
import type {
  HeightArea, TerrainArea, TerrainScatterEntry, TerrainStroke, TerrainType,
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
export type TerrainMode = 'select' | 'paint' | 'edit-area' | 'heights'

/** WHAT the toolbar is editing — the primary switch. */
export type MapPrimary = 'location' | 'terrain' | 'heights'

/** WHETHER a click draws a new shape or picks an existing one. The dependent
 *  switch of Terrain and Heights, worded identically in both. */
export type MapSub = 'new' | 'select'

/** The subject a canvas mode belongs to. The toolbar, the tray lists and the
 *  layer order all ask this question, so it is answered in one place. */
export function primaryOf(mode: TerrainMode): MapPrimary {
  if (mode === 'heights') return 'heights'
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
export const MAX_POINTS = 256
export const MAX_COORD = 100000
export const MAX_Z_ORDER = 10000

/** Server mirror — `app/models/terrain.MAX_SCATTER_ENTRIES`. */
export const MAX_SCATTER_ENTRIES = 8

/** What a freshly added scatter row starts as.
 *
 *  The target height is WRITTEN OUT rather than left empty on purpose: an
 *  entry without `height_m` falls back to the 3D client's default
 *  (`SCATTER_MODEL_HEIGHT_M`, 2 m), and an author who cannot see that number
 *  cannot correct it either. Two metres is a shrub/small tree next to a 1.70 m
 *  figure — visible, and an obvious knob to turn. Existing entries without the
 *  field stay valid; they just take the same default silently. */
const NEW_SCATTER_ENTRY: TerrainScatterEntry = {
  density_per_100m2: 1, height_m: 2,
}

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
 *  points. This caps the gesture at something that cannot possibly overrun the
 *  256-point polygon limit by accident; the generated polygon is checked on
 *  top of it, because a hairpin chain overruns it anyway. */
export const MAX_STROKE_POINTS = 100

/** Stroke width in metres: a footpath at the bottom, a broad river at the top,
 *  3 m — a cart track — as the thing most people draw first. */
export const STROKE_WIDTH_MIN_M = 0.5
export const STROKE_WIDTH_MAX_M = 50
export const STROKE_WIDTH_DEFAULT_M = 3

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
 * not the same as "0 m tall".
 */
function ScatterNum({ label, title, value, step, onCommit }: {
  label: string; title: string; value: number | null; step: number
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
    if (!e.model) delete e.model
    onChange(out)
  }
  return (
    <div className="ga-terrain-scatter">
      {entries.map((e, i) => {
        const model = e.model || ''
        const known = !model || props.some((p) => propModelUrl(p.id) === model)
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
              title={t('Target height: the model is scaled until it is this tall, and it always stands ON the ground. Empty = the 3D world’s default, 2 m for a model and 0.8 m for a tuft.')}
              value={typeof e.height_m === 'number' ? e.height_m : null}
              step={0.5}
              onCommit={(v) => patch(i, { height_m: v && v > 0 ? v : undefined })}
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
          {t('Placement is deterministic per area and skips the footprints of placed locations. Ground covered by an area painted on top of this one stays bare. Switch on “Scatter preview” to see the very points the 3D world plants.')}
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
 * A metre knob of the relief — the `WidthField` pattern, with a sign.
 *
 * Its own text draft, so a half-typed "−" or "0." is not clamped mid-keystroke;
 * committed on blur and on Enter (which is stopped here, or it would finish
 * the polygon being drawn). It NEVER writes itself: it hands the number up and
 * shows what comes back, so a value the server clamps is not left claimed by
 * the field. The token makes the effect run even when the parent's value did
 * not move.
 */
function HeightNum({ label, title, value, step, min, max, onCommit }: {
  label: string; title: string; value: number; step: number
  min: number; max: number; onCommit: (v: number) => void
}) {
  const [draft, setDraft] = useState(String(value))
  const [resync, setResync] = useState(0)
  useEffect(() => { setDraft(String(value)) }, [value, resync])
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
        className="ga-input"
        type="number" step={step} min={min} max={max}
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
  /** Vertices in the running draft. */
  draftLen: number
  onCloseDraft: () => void
  onDiscardDraft: () => void
  areaCount: number
  /** Open the type manager. It sits IN the palette because that is where the
   *  vocabulary is missing something — and it is the only surface that can
   *  answer "there is no kind for this" with anything but a shrug. */
  onManageTypes: () => void
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
  /** The catalog fetch FAILED — an empty palette then means "not loaded",
   *  not "nothing defined", and the way out is Reload, not another click. */
  typesError?: boolean
}

export function TerrainToolbar({
  mode, onPrimary, sub, onSub, types, paintKind, onPaintKind, shape, onShape,
  widthM, onWidth, draftLen, onCloseDraft, onDiscardDraft, areaCount,
  onManageTypes, typesError,
  heightM, onHeightM, falloffM, onFalloffM, heightCount, maxSlopeDeg,
  maxStepM,
}: TerrainToolbarProps) {
  const { t } = useI18n()
  const isLine = shape === 'line'
  const primary = primaryOf(mode)
  const drawingHeights = primary === 'heights' && sub === 'new'
  const needFalloff = minFalloffFor(heightM, maxSlopeDeg, maxStepM)
  const nextTooSteep = tooSteep(heightM, falloffM, maxSlopeDeg, maxStepM)
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
      </span>
      {/* …and WHETHER a click draws or picks. The same two words under both
          subjects: it is the same question, and two vocabularies for it were
          the reason the heights sub-tools read as something else entirely. */}
      {primary === 'location' ? null : (
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
      <span className="ga-map-toolbar-info">
        {mode === 'heights'
          ? t('{n} height areas').replace('{n}', String(heightCount))
          : t('{n} areas').replace('{n}', String(areaCount))}
      </span>

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
          {isLine ? <WidthField widthM={widthM} onWidth={onWidth} /> : null}
        </>
      ) : null}

      {/* The palette and the way into the type editor. The CHIPS only mean
          something while painting (they arm the next stroke), but "Manage…"
          is the only door to passability, speed and the move animation of a
          type — and one edits those while looking at the area one drew, not
          while holding a brush (user finding 2026-08-13: the button was
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
          <button type="button" className="ga-btn ga-btn-sm"
            title={t('Add terrain types or change colour, passability and speed')}
            onClick={onManageTypes}>
            {t('Manage…')}
          </button>
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
                    .replace('{max}', String(MAX_POINTS)))}
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

      {mode === 'heights' ? (
        <>
          {drawingHeights ? (
            <>
              <HeightNum
                label={t('Height')}
                title={t('How high the ground stands inside the new area. Negative digs a hollow.')}
                value={heightM} step={0.5}
                min={-HEIGHT_MAX_M} max={HEIGHT_MAX_M} onCommit={onHeightM} />
              <HeightNum
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
                      .replace('{max}', String(MAX_POINTS))}
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
        </div>
      ) : null}
    </div>
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
  /** The preview colour of the n-th entry — the same one the map draws. */
  scatterColor: (index: number) => string
  onScatter: (entries: TerrainScatterEntry[]) => void
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
  area, types, typeList, typesError, stroke, scatter, props, scatterColor,
  onKind, onZOrder, onWidth, onScatter, onConvert, onDelete, onClose,
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
        <button type="button" className="ga-btn ga-btn-sm" disabled={!known}
          title={t('Draw this area over the ones around it')}
          onClick={() => onZOrder(1)}>
          {t('Bring forward')}
        </button>
        <button type="button" className="ga-btn ga-btn-sm" disabled={!known}
          title={t('Draw this area under the ones around it')}
          onClick={() => onZOrder(-1)}>
          {t('Send back')}
        </button>
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
            title={t('Show what the areas grow, as dots — exactly the points the 3D world plants (footprints of placed locations stay clear).')}>
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
 * flank does not soften it any more: since 2026-08-13 a place levels the
 * ground under itself only when its own "Flatten terrain" box is ticked
 * (`level_ground`, § A16.1), so that is said once, as a side note about an
 * option — never as a plateau the editor can count on.
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
        <HeightNum
          label={t('Height')}
          title={t('How high the ground stands inside this area. Negative digs a hollow.')}
          value={area.height_m} step={0.5}
          min={-HEIGHT_MAX_M} max={HEIGHT_MAX_M} onCommit={onHeight} />
        <HeightNum
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
      {/* The opt-in side note: the relief no longer bends for a placement, so
          the chip says who does the flattening and that somebody has to ask
          for it. */}
      <div className="ga-map-chip-row ga-map-chip-label">
        {t('A location standing here only levels the ground under itself when its “Flatten terrain” box is ticked — otherwise this relief runs straight through it.')}
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
