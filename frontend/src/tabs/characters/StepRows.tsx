/**
 * StepRows — the pieces every character tab's flow is drawn with (the user's tab checklist, rebuilt first in the
 * Hairstyles tab, Task UI4; shared since Task UI5):
 * - `StepLight` — the traffic light of a step (green current · yellow due · red failed · grey nothing to do ·
 *   blue running);
 * - `StepRowView` — one step: light, name, state on the right in the light's colour, the reason in plain words
 *   under it (the numbers on mouse-over), its single button(s) as children, the button's disabled reason under it;
 * - `SubTabs` — the sub-tab bar of a tab's right-hand panel (sub-tabs instead of scrolling).
 * Their colours and the panel frame: stepStyle.ts.
 */
import type { ReactNode } from 'react'
import type { Light } from './hairstylesModel'
import { LIGHT_COLOR } from './stepStyle'

export function StepLight({ light, title }: { light: Light; title?: string }) {
  return (
    <span aria-hidden title={title} style={{
      flex: '0 0 10px', width: 10, height: 10, borderRadius: '50%', background: LIGHT_COLOR[light],
      boxShadow: light === 'blue' ? '0 0 0 3px rgba(88,166,255,0.25)' : undefined, display: 'inline-block',
    }} />
  )
}

/** What a step row shows. */
export interface StepRowData {
  name: string
  light: Light
  /** The short state on the right ("Current", "Due", "Failed"). */
  state: string
  /** The reason in plain words: what, when, what fixes it. */
  reason: string
  /** The row's mouse-over: numbers and sources. */
  detail?: string
  /** Its single button's disabled reason, written under the row. */
  button?: { disabled: string | null } | null
}

/** One step: light, name, state; the reason (mouse-over: the numbers); its single button(s) as children. */
export function StepRowView({ row, aside, children }: { row: StepRowData; aside?: ReactNode; children?: ReactNode }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 3, paddingBottom: 6,
      borderBottom: '1px solid var(--border, #30363d)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }} title={row.detail || undefined}>
        <StepLight light={row.light} />
        <strong style={{ fontSize: 13, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {row.name}
        </strong>
        {aside}
        <span className="ga-hint" style={{ marginLeft: 'auto', color: LIGHT_COLOR[row.light], textAlign: 'right' }}>
          {row.state}
        </span>
      </div>
      {row.reason ? (
        <div className="ga-hint" style={{ overflowWrap: 'anywhere' }} title={row.detail || undefined}>{row.reason}</div>
      ) : null}
      {children}
      {row.button?.disabled ? <div className="ga-hint">{row.button.disabled}</div> : null}
    </div>
  )
}

/** The sub-tab bar of a right-hand panel. */
export function SubTabs<T extends string>({ tabs, value, onChange }: {
  tabs: ReadonlyArray<{ id: T; label: string; title?: string }>
  value: T
  onChange: (id: T) => void
}) {
  return (
    <nav className="ga-subtabs" style={{ margin: 0 }}>
      {tabs.map((tab) => (
        <button key={tab.id} type="button" title={tab.title}
          className={`ga-btn ga-btn-sm${value === tab.id ? ' ga-btn-primary' : ''}`}
          onClick={() => onChange(tab.id)}>
          {tab.label}
        </button>
      ))}
    </nav>
  )
}
