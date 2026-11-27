/**
 * PlanFindings — everything the floor plan has to SAY, in one place: the
 * legend of the three shapes, the editor's own leftover-room finding, and the
 * server's `problems[]`. Boundary pass-throughs live in PlanPassThroughs
 * inside the Plot panel.
 *
 * WHY IT IS A PANEL AND NOT A COLUMN OF BANNERS. These used to stack under
 * the canvas, inside the plan's own column — so a location with three findings
 * pushed the plan up and shrank the one surface the whole tab exists for, and
 * it did so PERMANENTLY, because a finding is not something one dismisses. In
 * the single-panel inspector they live in the Findings panel whose toolbar
 * button carries a count: with nothing to report it is silent and costs no
 * height at all, and the status line under the plan says in one word that
 * there is something to read.
 */
import { useI18n } from '../../i18n/I18nProvider'
import type { Room, SceneProblem } from './worldTypes'

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
}

export function PlanFindings({
  hasBoundary, placedOnMap, tinyRooms, tinyRoomM, problems, problemText,
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
    </>
  )
}
