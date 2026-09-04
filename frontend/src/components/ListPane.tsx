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
}: {
  id: string
  /** Shown vertically in the collapsed strip so the pane stays identifiable. */
  label?: string
  className?: string
  children: ReactNode
}) {
  const { t } = useI18n()
  const [collapsed, setCollapsed] = usePersistentState<boolean>(`listpane.${id}.collapsed`, false)
  const gripTitle = collapsed ? t('Expand list') : t('Collapse list')
  return (
    <aside className={`${className} ga-listpane${collapsed ? ' is-collapsed' : ''}`}>
      {collapsed ? null : children}
      <button
        type="button"
        className="ga-listpane-grip"
        aria-expanded={!collapsed}
        aria-label={gripTitle}
        title={gripTitle}
        onClick={() => setCollapsed((c) => !c)}
      >
        <span className="ga-listpane-grip-icon" aria-hidden="true">{collapsed ? '›' : '‹'}</span>
        {collapsed && label ? <span className="ga-listpane-grip-label">{label}</span> : null}
      </button>
    </aside>
  )
}
