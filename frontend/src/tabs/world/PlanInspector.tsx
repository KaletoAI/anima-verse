/**
 * PlanInspector — the dock right of the floor plan: three tabs, one visible at
 * a time, and a fold button that gives the whole column back to the plan.
 *
 * WHAT PROBLEM IT SOLVES. Everything that is not the plan used to be laid out
 * BELOW it or beside it at the same time: the room panel in its own column,
 * and under the canvas the legend, the leftover-room warning, the server's
 * findings, the pass-through rows, then the prop strip, the marker strip, the
 * opening strip, the elevator, the staircase and the room chips — a vertical
 * stack that grew with the location and pushed the plan out of sight exactly
 * when the plan had most to show. None of it is needed at once: a selection,
 * the storey's settings and the findings are three different questions.
 *
 * The findings tab carries a COUNT and is silent without one, which is the
 * whole point — "Boundary pass-throughs" and a warning banner must not cost
 * the plan a single pixel of height on a location that has neither.
 *
 * The three panes arrive as nodes, not as props. The selection pane in
 * particular is built from a dozen closures over the editor's drag state,
 * draft geometry and server calls; threading those through an interface would
 * buy nothing and cost every one of them a name.
 */
import type { ReactNode } from 'react'
import { useI18n } from '../../i18n/I18nProvider'

export type InspectorTab = 'selection' | 'level' | 'findings'

interface Props {
  tab: InspectorTab
  onTab: (tab: InspectorTab) => void
  /** Fold state — folded, the dock is a single button and the plan takes the
   *  width. Owned by the editor so the plan can re-measure. */
  collapsed: boolean
  onCollapsed: (collapsed: boolean) => void
  /** What the selection tab is about right now, for its label ("Room",
   *  "Prop", "Nothing selected") — a tab that says what it holds is worth
   *  more than one that says "Selection". */
  selectionLabel: string
  /** How many findings are waiting. 0 = no badge. */
  findingCount: number
  selection: ReactNode
  level: ReactNode
  findings: ReactNode
}

export function PlanInspector({
  tab, onTab, collapsed, onCollapsed, selectionLabel, findingCount,
  selection, level, findings,
}: Props) {
  const { t } = useI18n()

  if (collapsed) {
    return (
      <div className="ga-plan-inspector is-collapsed">
        <button
          type="button"
          className="ga-btn ga-btn-sm"
          title={t('Show the inspector (selection, storey, findings).')}
          onClick={() => onCollapsed(false)}
        >
          ⟨{findingCount ? <span className="ga-plan-badge">{findingCount}</span> : null}
        </button>
      </div>
    )
  }

  const Tab = ({ id, label, badge }: {
    id: InspectorTab; label: string; badge?: number
  }) => (
    <button
      type="button"
      className={`ga-btn ga-btn-sm${tab === id ? ' ga-btn-primary' : ''}`}
      onClick={() => onTab(id)}
      title={label}
    >
      {label}
      {badge ? <span className="ga-plan-badge">{badge}</span> : null}
    </button>
  )

  return (
    <div className="ga-plan-inspector">
      <div className="ga-plan-inspector-tabs">
        <Tab id="selection" label={selectionLabel} />
        <Tab id="level" label={t('Storey')} />
        <Tab id="findings" label={t('Findings')} badge={findingCount} />
        <button
          type="button"
          className="ga-btn ga-btn-sm"
          style={{ flex: '0 0 auto' }}
          title={t('Fold the inspector away — the plan takes the width.')}
          onClick={() => onCollapsed(true)}
        >⟩</button>
      </div>
      <div className="ga-plan-inspector-body">
        {tab === 'selection' ? selection
          : tab === 'level' ? level
            : findings}
      </div>
    </div>
  )
}
