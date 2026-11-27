/**
 * PlanPassThroughs — boundary pass-through editor for the inspector's Plot
 * panel. The pass-throughs are plot-level DATA, not a finding — an ordinary
 * means of every location, not a speciality of area/detail ones (ruling
 * 2026-08-04), listed with zero openings too when the plot is unfenced, which
 * is where gates get added to fence it.
 */
import { useI18n } from '../../i18n/I18nProvider'
import { clamp, edgeSegment, r4 } from './planGeometry'
import type { Map3D } from './worldTypes'

interface PlanPassThroughsProps {
  map3d?: Map3D
  /** Absent = this editor may not write map3d, and the pass-throughs are not
   *  shown at all. */
  onMap3d?: (key: keyof Map3D, value: unknown) => void
  /** The plot in local metres — the edge picker labels its options with the
   *  two points each edge runs between. */
  boundaryM: Array<[number, number]>
  /** Width of the location in metres — the cap for a pass-through. */
  planW: number
  selectedBoundary: number | null
  onSelectBoundary: (i: number | null) => void
  /** Server verdict: is the plot fenced (`boundary_openings` non-empty)?
   *  When false, the section shows the open-plot hint even with zero gates. */
  fenced?: boolean
}

export function PlanPassThroughs({
  map3d, onMap3d, boundaryM, planW, selectedBoundary, onSelectBoundary, fenced,
}: PlanPassThroughsProps) {
  const { t } = useI18n()

  if (!onMap3d || (!map3d?.boundary_openings?.length && fenced !== false)) {
    return (
      <span className="ga-hint">
        {t('Edit the plot with 🟩, or add an entry at the edge with ⇥.')}
      </span>
    )
  }

  return (
    <div className="ga-form" style={{ gap: 4 }}>
      <div className="ga-form-section-label">{t('Boundary pass-throughs')}</div>
      {fenced === false ? (
        <div className="ga-anchor-banner">
          <span>ℹ {t('No pass-through drawn: the plot is open on every side. Draw pass-throughs to fence it — then it is entered only through them.')}</span>
        </div>
      ) : null}
      {(map3d?.boundary_openings || []).map((bo, i) => {
        const write = (patch: Partial<typeof bo>) =>
          onMap3d('boundary_openings', (map3d?.boundary_openings || [])
            .map((b, j) => (j === i ? { ...b, ...patch } : b)))
        return (
          <div key={i} onClick={() => onSelectBoundary(i)}
            style={{ display: 'flex', gap: 4, alignItems: 'center',
              flexWrap: 'wrap',
              fontSize: '0.82em', padding: '2px 4px', borderRadius: 4,
              background: selectedBoundary === i
                ? 'rgba(224,163,86,0.15)' : undefined }}>
            {/* WHICH boundary edge the pass-through sits on (v6 Nr. 5):
                an index, labelled with the two points it runs between so
                it can be picked without counting vertices on the plan.
                Clicking the gold bar selects the row; clicking the plan
                in "pass-through" mode picks the nearest edge outright. */}
            <select className="ga-input"
              style={{ flex: '1 1 100%', minWidth: 0 }}
              value={bo.edge}
              title={t('Boundary edge the pass-through sits on')}
              onChange={(e) => write({ edge: Number(e.target.value) })}>
              {boundaryM.map((_p, ei) => {
                const { a, b } = edgeSegment(boundaryM, ei)
                // The points ARE local metres — the label just rounds.
                const m = (v: number) => Math.round(v * 10) / 10
                return (
                  <option key={ei} value={ei}>
                    {`${t('Edge')} ${ei}: (${m(a[0])},${m(a[1])})→(${m(b[0])},${m(b[1])})`}
                  </option>
                )
              })}
              {bo.edge >= boundaryM.length ? (
                <option value={bo.edge}>
                  {`${t('Edge')} ${bo.edge} — ${t('outside the boundary')}`}
                </option>
              ) : null}
            </select>
            <input className="ga-input" type="number" min={0} max={1}
              step={0.01} style={{ width: 60 }} value={bo.at}
              title={t('Position along the edge (0..1)')}
              onChange={(e) => {
                const v = Number(e.target.value)
                if (Number.isFinite(v)) write({ at: r4(clamp(v, 0, 1)) })
              }} />
            {/* The pass-through lies ON a boundary edge, and the
                location's own width is its maximum (plan_width_m — the
                bounding box of the drawn outline). Without the anchor the
                server's 10 m fallback applies — the same rule on both
                sides. */}
            <input className="ga-input" type="number" min={0.5}
              max={planW || 10}
              step={0.5} style={{ width: 60 }} value={bo.width_m}
              title={t('Width (m) — at most the length of the edge')}
              onChange={(e) => {
                const v = Number(e.target.value)
                if (Number.isFinite(v)) {
                  write({ width_m: clamp(v, 0.5, planW || 10) })
                }
              }} />
            <button type="button" className="ga-btn ga-btn-sm ga-btn-danger"
              title={t('Remove')}
              onClick={(e) => {
                e.stopPropagation()
                const next = (map3d?.boundary_openings || [])
                  .filter((_, j) => j !== i)
                onMap3d('boundary_openings', next.length ? next : undefined)
                onSelectBoundary(null)
              }}>✕</button>
          </div>
        )
      })}
    </div>
  )
}
