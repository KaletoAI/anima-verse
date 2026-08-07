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
import { useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { typeColor } from './TerrainLayer'
import type { TerrainArea, TerrainType } from './mapTypes'

/** What a click on the map does. `select` is the location editor of Task 3. */
export type TerrainMode = 'select' | 'paint' | 'edit-area'

/** Server mirrors — `_sanitize_polygon`/`sanitize_area` in
 *  `app/models/terrain.py`. */
export const MIN_POINTS = 3
export const MAX_POINTS = 256
export const MAX_COORD = 100000
export const MAX_Z_ORDER = 10000

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
  /** Vertices in the running draft. */
  draftLen: number
  onCloseDraft: () => void
  onDiscardDraft: () => void
  areaCount: number
}

export function TerrainToolbar({
  mode, onMode, types, paintKind, onPaintKind, draftLen,
  onCloseDraft, onDiscardDraft, areaCount,
}: TerrainToolbarProps) {
  const { t } = useI18n()
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
  return (
    <>
      <span className="ga-terrain-modes">
        {btn('select', '⬚', t('Locations'),
          t('Place, move and turn locations'))}
        {btn('paint', '🖌', t('Paint'),
          t('Draw a terrain area: click to set points, click the first point to close'))}
        {btn('edit-area', '✎', t('Edit terrain'),
          t('Click an area to select it, then drag its points'))}
      </span>
      <span className="ga-map-toolbar-info">
        {t('{n} areas').replace('{n}', String(areaCount))}
      </span>

      {mode === 'paint' ? (
        <>
          <span className="ga-terrain-palette">
            {types.length === 0 ? (
              <span className="ga-map-tray-empty">{t('No terrain types')}</span>
            ) : types.map((ty) => (
              <TypeChip key={ty.kind} type={ty} armed={ty.kind === paintKind}
                onPick={() => onPaintKind(ty.kind)} />
            ))}
          </span>
          <span className={'ga-map-arm' + (paintKind ? '' : ' warn')}>
            {!paintKind
              ? t('Pick a terrain type first')
              : draftLen === 0
                ? t('Click the map to set the first point')
                : t('{n} of {max} points — click the first one to close, Escape discards')
                  .replace('{n}', String(draftLen)).replace('{max}', String(MAX_POINTS))}
            {draftLen > 0 ? (
              <>
                <button type="button" className="ga-btn ga-btn-sm"
                  disabled={draftLen < MIN_POINTS} onClick={onCloseDraft}
                  title={t('Close the ring and save the area')}>
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
      ) : null}
    </>
  )
}

export interface TerrainAreaChipProps {
  area: TerrainArea
  types: Record<string, TerrainType>
  /** The catalog in display order, for the kind palette. */
  typeList: TerrainType[]
  onKind: (kind: string) => void
  /** Move one layer up (+1) or down (−1). */
  onZOrder: (delta: number) => void
  onDelete: () => void
  onClose: () => void
}

/**
 * The selected area, floating over the canvas — the same chip pattern the
 * location selection uses. Deleting arms an inline confirmation row (no
 * `window.confirm`); the state is local because the chip is remounted per area
 * (`key`), so a fresh selection is never half-armed.
 */
export function TerrainAreaChip({
  area, types, typeList, onKind, onZOrder, onDelete, onClose,
}: TerrainAreaChipProps) {
  const { t } = useI18n()
  const [armed, setArmed] = useState(false)
  const known = types[area.kind]
  return (
    <div className="ga-map-chip">
      <div className="ga-map-chip-head">
        <span className="ga-terrain-swatch"
          style={{ background: typeColor(types, area.kind) }} />
        <strong>{known?.name || area.kind}</strong>
        <button type="button" className="ga-modal-close"
          title={t('Clear selection')} onClick={onClose}>×</button>
      </div>
      <div className="ga-map-chip-row">
        {known ? (
          <span>{t('{n} points').replace('{n}', String(area.polygon.length))}</span>
        ) : (
          <span className="ga-map-chip-warn">
            {t('Unknown terrain type “{kind}”').replace('{kind}', area.kind)}
          </span>
        )}
        <span className="ga-map-chip-pos">{t('layer {n}').replace('{n}', String(area.z_order))}</span>
      </div>
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
        <button type="button" className="ga-btn ga-btn-sm"
          title={t('Draw this area over the ones around it')}
          onClick={() => onZOrder(1)}>
          {t('Bring forward')}
        </button>
        <button type="button" className="ga-btn ga-btn-sm"
          title={t('Draw this area under the ones around it')}
          onClick={() => onZOrder(-1)}>
          {t('Send back')}
        </button>
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
      <div className="ga-map-chip-row ga-map-chip-label">
        {t('Drag a point to move it · double-click removes it · click an edge to add one')}
      </div>
    </div>
  )
}
