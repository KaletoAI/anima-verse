/**
 * PlanHullOpeningStrip — the selected door in the BUILDING SHELL: how big it
 * is, which contour edge it sits on, where along that edge, and which door
 * hangs in it.
 *
 * WHY IT IS NOT `PlanOpeningStrip`. A room opening answers one question this
 * one cannot ask — WHERE IT LEADS. A hull door always joins the storey's
 * corridor to the outside (§ 6), so there is no target to pick, no "outside"
 * option and no corridor name to offer: the two fields that make up half of
 * the room strip would be a select with exactly one entry. What the two DO
 * share is shared for real: the metre fields come from `OpeningNumField` and
 * the door picker is the very same `OpeningDoorProp` — this file adds the
 * contour edge and the fraction along it, and nothing else.
 *
 * NO WINDOW, NO SILL. A window is not walkable, so the composer never cuts a
 * threshold for one (`scene_recipe._WALKABLE_TYPES`) and the entry would sit
 * in the payload unrendered; and the hull piece a leaf hangs in starts at the
 * storey floor, so a sill has nothing to sit on. Both are absent from the
 * type, not merely hidden here.
 */
import { useI18n } from '../../i18n/I18nProvider'
import { OpeningDoorProp } from './DoorPropPicker'
import { OpeningNumField } from './PlanOpeningStrip'
import { clamp, edgeSegment, r4 } from './planGeometry'
import type { HullOpening } from './worldTypes'

interface Props {
  opening: HullOpening
  /** Index in `map3d.hull_openings`, for the door picker's key — the
   *  "Custom, nothing picked yet" state must never travel to the next door. */
  index: number
  /** The RESOLVED footprint of this storey in local metres — the edge picker
   *  labels its options with the two points each edge runs between, exactly
   *  as the boundary pass-throughs do. */
  outline: Array<[number, number]>
  /** The location's fallback door prop, named as the first option. */
  defaultDoorPropId: string
  /** Merge a patch into this door, or remove it when null is passed. */
  onPatch: (patch: Partial<HullOpening> | null) => void
}

export function PlanHullOpeningStrip({
  opening: op, index, outline, defaultDoorPropId, onPatch,
}: Props) {
  const { t } = useI18n()
  const m = (v: number) => Math.round(v * 10) / 10

  return (
    <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
      <span className="ga-hint" style={{ fontWeight: 600 }}>
        🚪 {t('On the outline')} · {t('Storey {n}').replace('{n}', String(op.level))}:
      </span>
      <select
        className="ga-input"
        style={{ width: 110 }}
        value={op.type}
        onChange={(e) => onPatch({ type: e.target.value as HullOpening['type'] })}
        title={t('A door hangs a leaf in the hole; a passage is the open gap.')}
      >
        <option value="door">{t('Door')}</option>
        <option value="passage">{t('Passage')}</option>
      </select>
      <OpeningNumField label={t('W (m)')} value={op.width_m} min={0.4} max={10}
        onCommit={(v) => onPatch({ width_m: v })} />
      <OpeningNumField label={t('H (m)')} value={op.height_m} min={0.4} max={10}
        onCommit={(v) => onPatch({ height_m: v })} />
      {/* WHICH contour edge carries the door: an index into the storey's own
          footprint, labelled with the two points it runs between so it can be
          corrected without counting vertices on the plan. Clicking the plan
          with the tool armed picks the nearest edge outright. */}
      <label style={{ display: 'inline-flex', gap: 4, alignItems: 'center',
        fontSize: '0.82em', flex: '1 1 220px', minWidth: 0 }}
        title={t('Contour edge of this storey the door sits on.')}>
        {t('Edge')}
        <select
          className="ga-input"
          style={{ flex: 1, minWidth: 0 }}
          value={op.edge}
          onChange={(e) => onPatch({ edge: Number(e.target.value) })}
        >
          {outline.map((_p, ei) => {
            const { a, b } = edgeSegment(outline, ei)
            return (
              <option key={ei} value={ei}>
                {`${ei}: (${m(a[0])},${m(a[1])})→(${m(b[0])},${m(b[1])})`}
              </option>
            )
          })}
          {op.edge >= outline.length ? (
            <option value={op.edge}>
              {`${op.edge} — ${t('not on this storey’s outline')}`}
            </option>
          ) : null}
        </select>
      </label>
      <label style={{ display: 'inline-flex', gap: 4, alignItems: 'center', fontSize: '0.82em' }}
        title={t('Position along that edge (0..1).')}>
        {t('at')}
        <input
          className="ga-input"
          type="number"
          min={0}
          max={1}
          step={0.01}
          style={{ width: 64 }}
          value={op.at}
          onChange={(e) => {
            const v = Number(e.target.value)
            if (Number.isFinite(v)) onPatch({ at: r4(clamp(v, 0, 1)) })
          }}
        />
      </label>
      {op.type === 'door' ? (
        <OpeningDoorProp
          key={index}
          opening={op}
          defaultPropId={defaultDoorPropId}
          onPatch={onPatch}
        />
      ) : null}
      <button
        type="button"
        className="ga-btn ga-btn-sm ga-btn-danger"
        onClick={() => onPatch(null)}
        title={t('Remove this door from the outline')}
      >
        × {t('Remove')}
      </button>
    </div>
  )
}
