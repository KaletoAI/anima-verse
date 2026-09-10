/**
 * PlanFindings — everything the floor plan has to SAY, in one place: the
 * legend of the three shapes, the editor's own leftover-room finding, the
 * server's `problems[]` and the boundary pass-throughs.
 *
 * WHY IT IS A TAB AND NOT A COLUMN OF BANNERS. All four used to stack under
 * the canvas, inside the plan's own column — so a location with three findings
 * and two pass-throughs pushed the plan up and shrank the one surface the
 * whole tab exists for, and it did so PERMANENTLY, because a finding is not
 * something one dismisses. In the inspector they are a tab with a count: with
 * nothing to report the tab is silent and costs no height at all, and the
 * status line under the plan says in one word that there is something to read.
 *
 * The pass-throughs are building-level DATA, not a message, and they are here
 * for the same reason: they belong to the plot, not to a selected room, so the
 * room panel is the wrong home and the plan's own column was the expensive
 * one. An ordinary means of every location, not a speciality of area/detail
 * ones (ruling 2026-08-04) — listed with zero openings too, when the server
 * reports no entrance at all, which is exactly where one gets added.
 */
import { useI18n } from '../../i18n/I18nProvider'
import { clamp, edgeSegment, r4 } from './planGeometry'
import { roomLabel, type Map3D, type Room, type SceneProblem } from './worldTypes'

interface Props {
  /** The plot exists (`map3d.boundary`, ≥ 3 points) — the legend draws its
   *  line solid or dashed after it, like the canvas does. */
  hasBoundary: boolean
  placedOnMap: boolean
  /** Rooms smaller than `tinyRoomM` — leftovers from the fraction era. */
  tinyRooms: Room[]
  tinyRoomM: number
  problems: SceneProblem[]
  /** The editor's own wording for one server finding (it knows the room
   *  names; the composer only ships ids). */
  problemText: (p: SceneProblem) => string
  map3d?: Map3D
  /** Absent = this editor may not write map3d, and the pass-throughs are not
   *  shown at all. */
  onMap3d?: (key: keyof Map3D, value: unknown) => void
  /** The plot in local metres — the edge picker labels its options with the
   *  two points each edge runs between. */
  boundaryM: Array<[number, number]>
  /** Width of the location in metres — the cap for a pass-through. */
  planW: number
  /** Rooms on the plan, for the "leads to" link. */
  placedRooms: Room[]
  selectedBoundary: number | null
  onSelectBoundary: (i: number | null) => void
  /** The server found no way in at all — then the list is shown even empty. */
  hasEntrance?: boolean
}

export function PlanFindings({
  hasBoundary, placedOnMap, tinyRooms, tinyRoomM, problems, problemText,
  map3d, onMap3d, boundaryM, planW, placedRooms, selectedBoundary,
  onSelectBoundary, hasEntrance,
}: Props) {
  const { t } = useI18n()
  return (
    <>
      {/* THE THREE SHAPES, NAMED. The plan draws a plot, a house and rooms on
          top of each other, and until this line existed nothing said which was
          which — an author who drew the building contour expecting a room got
          a correct but unhelpful "no room has a floor plan" and no way to tell
          the shapes apart (user finding 2026-08-20). In the colours and
          strokes the canvas really uses. */}
      <div className="ga-hint" style={{ display: 'flex', gap: 10,
        flexWrap: 'wrap', alignItems: 'center', fontSize: '0.76em' }}>
        <span style={{ display: 'inline-flex', gap: 4, alignItems: 'center' }}
          title={t('The plot itself — the ground this location covers. Editable here with the 🟩 tool and on the map tab; solid once the location is placed, dashed while it is not.')}>
          <svg width={20} height={8} aria-hidden>
            <line x1={1} y1={4} x2={19} y2={4} stroke="#3fb950" strokeWidth={2}
              strokeDasharray={hasBoundary && placedOnMap ? undefined : '4 3'} />
          </svg>
          {t('location boundary')}
        </span>
        <span style={{ display: 'inline-flex', gap: 4, alignItems: 'center' }}
          title={t('The building standing on the plot — the 🏗 tool draws it. It is NOT a room: a contour with no room inside holds nothing anybody can enter.')}>
          <svg width={20} height={8} aria-hidden>
            <line x1={1} y1={4} x2={19} y2={4} stroke="#58a6ff" strokeWidth={2} />
          </svg>
          {t('building contour')}
        </span>
        <span style={{ display: 'inline-flex', gap: 4, alignItems: 'center' }}
          title={t('The rooms — what can actually be entered. Drawn with the ⬠ tool; every location needs at least one.')}>
          <svg width={20} height={8} aria-hidden>
            <rect x={1} y={1} width={18} height={6} fill="rgba(139,148,158,0.12)"
              stroke="#8b949e" strokeWidth={1.5} />
          </svg>
          {t('rooms')}
        </span>
      </div>

      {/* The editor's OWN finding, not the server's: rooms left over from the
          fraction era. Gentle — it is a "here is why", not an error, and it
          names the rooms so the author can go and fix the right ones. */}
      {tinyRooms.length ? (
        <div className="ga-anchor-banner">
          <span>⚠ {t('{rooms} — smaller than {n} m. These are leftovers from before rooms were stored in metres; their old share of the reference square is now read as metres. Nothing repairs them automatically: delete them, or redraw their hull with ⬠.')
            .replace('{rooms}', tinyRooms.map((r) => r.name || r.id).join(', '))
            .replace('{n}', String(tinyRoomM))}</span>
        </div>
      ) : null}

      {/* Findings of the SERVER about this floor plan (§ 4.3,
          plan-betreten-und-tueren.md): the composer states them, the editor
          only shows them — at the room it names, otherwise at the location. */}
      {problems.map((p, i) => (
        <div key={`${p.kind}-${p.room_id || ''}-${i}`}
          className="ga-anchor-banner">
          <span>⚠ {problemText(p)}</span>
        </div>
      ))}

      {onMap3d
        && (map3d?.boundary_openings?.length || hasEntrance === false) ? (
        <div className="ga-form" style={{ gap: 4, marginTop: 6 }}>
          <div className="ga-form-section-label">{t('Boundary pass-throughs')}</div>
          {hasEntrance === false ? (
            <div className="ga-anchor-banner">
              <span>ℹ {t('No pass-through drawn: characters may enter anywhere along the boundary. Draw openings to channel entry.')}</span>
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
                <select className="ga-input" style={{ flex: 1, minWidth: 80 }}
                  value={bo.room || ''}
                  title={t('Linked room — where the pass-through leads (feeds the future journey walk-through).')}
                  onChange={(e) => write({ room: e.target.value || undefined })}>
                  <option value="">{t('No room link')}</option>
                  {placedRooms.map((r) => (
                    <option key={r.id} value={r.id}>{roomLabel(r, t)}</option>
                  ))}
                </select>
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
      ) : null}
    </>
  )
}
