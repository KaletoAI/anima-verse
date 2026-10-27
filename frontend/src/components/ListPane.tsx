import type { ReactNode } from 'react'
import { useI18n } from '../i18n/I18nProvider'
import { usePersistentState } from '../lib/usePersistentState'

/**
 * Collapsible list column of the list-detail tabs. Replaces the bare
 * `<aside className="ga-twocol-left">` — renders the aside, a grip to
 * collapse/expand it and (while expanded) its children. Collapsed it is a
 * narrow strip holding only the grip, and the detail pane takes the room.
 *
 * The collapsed state is persisted per pane (`id` must be stable per tab)
 * so it survives the tab switch and a reload. Children are NOT rendered
 * while collapsed — nothing hidden stays reachable via Tab.
 *
 * Grid hosts (Items, Locations) pass their column class via `className`;
 * the grid switches its first track on `:has(> .ga-listpane.is-collapsed)`.
 */
export function ListPane({
  id,
  label,
  className = 'ga-twocol-left',
  children,
  expanded,
  onExpandedChange,
  collapseDisabled = false,
}: {
  id: string
  /** Shown vertically in the collapsed strip so the pane stays identifiable. */
  label?: string
  className?: string
  children: ReactNode
  expanded?: boolean
  onExpandedChange?: (expanded: boolean) => void
  collapseDisabled?: boolean
}) {
  const { t } = useI18n()
  const [collapsed, setCollapsed] = usePersistentState<boolean>(`listpane.${id}.collapsed`, false)
  const isCollapsed = expanded === undefined ? collapsed : !expanded
  const gripTitle = isCollapsed ? t('Expand list') : t('Collapse list')
  return (
    <aside className={`${className} ga-listpane${isCollapsed ? ' is-collapsed' : ''}`} aria-label={label}>
      {isCollapsed ? null : children}
      <button
        type="button"
        className="ga-listpane-grip"
        aria-expanded={!isCollapsed}
        aria-label={gripTitle}
        title={gripTitle}
        disabled={collapseDisabled}
        onClick={() => {
          if (onExpandedChange) onExpandedChange(isCollapsed)
          else setCollapsed((c) => !c)
        }}
      >
        <span className="ga-listpane-grip-icon" aria-hidden="true">{isCollapsed ? '›' : '‹'}</span>
        {isCollapsed && label ? <span className="ga-listpane-grip-label">{label}</span> : null}
      </button>
    </aside>
  )
}
