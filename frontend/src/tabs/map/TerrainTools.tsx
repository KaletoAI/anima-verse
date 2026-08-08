/**
 * TerrainTools — the terrain controls of the map toolbar and the chip of the
 * selected area. Purely presentational, like `PlanToolbar`: every handler and
 * all state live in `MapTab`, these components only decide what is armed,
 * disabled or shown.
 *
 * The three modes are exclusive because their clicks mean three different
 * things — select a location, drop a vertex, pick an area. A single "click on
 * the map" that guesses from context would be exactly the kind of hidden
 * modality the plan editor already learned to avoid.
 *
 * The limits below are the SERVER's (`app/models/terrain.py`), mirrored so a
 * refusal arrives as a sentence in the toolbar instead of a 400 after the
 * user has clicked 257 times. They are a copy, not a second opinion: the
 * server still validates, and any change there must land here too.
 */
import { useEffect, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { typeColor } from './TerrainLayer'
import type { TerrainArea, TerrainStroke, TerrainType } from './mapTypes'

/** What a click on the map does. `select` is the location editor of Task 3. */
export type TerrainMode = 'select' | 'paint' | 'edit-area'

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
 */
function WidthField({ widthM, onWidth }: {
  widthM: number; onWidth: (m: number) => void
}) {
  const { t } = useI18n()
  const [draft, setDraft] = useState(String(widthM))
  useEffect(() => { setDraft(String(widthM)) }, [widthM])
  const commit = () => {
    const v = parseFloat(draft)
    if (!Number.isFinite(v)) { setDraft(String(widthM)); return }
    const c = clampStrokeWidth(v)
    setDraft(String(c))
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
  onMode: (m: TerrainMode) => void
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
  /** The catalog fetch FAILED — an empty palette then means "not loaded",
   *  not "nothing defined", and the way out is Reload, not another click. */
  typesError?: boolean
}

export function TerrainToolbar({
  mode, onMode, types, paintKind, onPaintKind, shape, onShape, widthM, onWidth,
  draftLen, onCloseDraft, onDiscardDraft, areaCount, onManageTypes, typesError,
}: TerrainToolbarProps) {
  const { t } = useI18n()
  const isLine = shape === 'line'
  const btn = (m: TerrainMode, icon: string, label: string, title: string) => (
    <button
      type="button"
      className={'ga-btn ga-btn-sm' + (mode === m ? ' ga-btn-primary' : '')}
      title={title}
      onClick={() => onMode(m)}
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
      <span className="ga-terrain-modes">
        {btn('select', '⬚', t('Locations'),
          t('Place, move and turn locations'))}
        {btn('paint', '🖌', t('Paint'),
          t('Draw terrain: an area from its outline, or a line with a width'))}
        {btn('edit-area', '✎', t('Edit terrain'),
          t('Click an area to select it, then drag its points'))}
      </span>
      <span className="ga-map-toolbar-info">
        {t('{n} areas').replace('{n}', String(areaCount))}
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
          <span className="ga-terrain-palette">
            {types.length === 0 ? (
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
        </>
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
 */
export function TerrainAreaChip({
  area, types, typeList, typesError, stroke, onKind, onZOrder, onWidth,
  onConvert, onDelete, onClose,
}: TerrainAreaChipProps) {
  const { t } = useI18n()
  const [armed, setArmed] = useState(false)
  const [convArmed, setConvArmed] = useState(false)
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
