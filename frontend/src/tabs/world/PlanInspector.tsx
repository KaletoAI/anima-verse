/**
 * PlanInspector — the single-pane dock right of the floor plan, and a fold
 * button that gives the whole column back to the plan.
 *
 * WHAT PROBLEM IT SOLVES. Everything that is not the plan used to be laid out
 * BELOW it or beside it at the same time: the room panel in its own column,
 * and under the canvas the legend, the leftover-room warning, the server's
 * findings, the pass-through rows, then the prop strip, the marker strip, the
 * opening strip, the elevator, the staircase and the room chips — a vertical
 * stack that grew with the location and pushed the plan out of sight exactly
 * when the plan had most to show. None of it is needed at once.
 *
 * Instead of a tab bar, the dock is now fully dynamic: it always renders the
 * single panel belonging to the active tool in PlanToolbar, with a header
 * naming that tool (and optional context subtitle). The pane content arrives
 * as `children` built from closures over the editor's drag state, draft
 * geometry and server calls.
 */
import type { ReactNode } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { PANEL_INFO, type PlanPanel } from './planTools'

interface Props {
  panel: PlanPanel
  /** Fold state — folded, the dock is a single button and the plan takes the
   *  width. Owned by the editor so the plan can re-measure. */
  collapsed: boolean
  onCollapsed: (collapsed: boolean) => void
  /** How many findings are waiting. 0 = no badge. */
  findingCount: number
  /** Optional context shown muted next to the panel title (e.g. room name). */
  subtitle?: string
  children: ReactNode
}

export function PlanInspector({
  panel, collapsed, onCollapsed, findingCount, subtitle, children,
}: Props) {
  const { t } = useI18n()

  if (collapsed) {
    return (
      <div className="ga-plan-inspector is-collapsed">
        <button
          type="button"
          className="ga-btn ga-btn-sm"
          title={t('Show the inspector.')}
          onClick={() => onCollapsed(false)}
        >
          ⟨{findingCount ? <span className="ga-plan-badge">{findingCount}</span> : null}
        </button>
      </div>
    )
  }

  const info = PANEL_INFO[panel]

  return (
    <div className="ga-plan-inspector">
      <div className="ga-plan-inspector-head">
        <span className="ga-plan-panel-title" style={{ flex: 1, minWidth: 0, borderBottom: 0, paddingBottom: 0 }}>
          {info.icon} {t(info.label)}
          {subtitle ? <span className="ga-hint" style={{ fontWeight: 400, marginLeft: 6 }}>{subtitle}</span> : null}
        </span>
        <button
          type="button"
          className="ga-btn ga-btn-sm"
          style={{ flex: '0 0 auto' }}
          title={t('Fold the inspector away — the plan takes the width.')}
          onClick={() => onCollapsed(true)}
        >⟩</button>
      </div>
      <div className="ga-plan-inspector-body">
        {children}
      </div>
    </div>
  )
}
