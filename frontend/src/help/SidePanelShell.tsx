import { useState, type ReactNode } from 'react'
import { useHelp, type SidePanelId } from './HelpContext'
import { useI18n } from '../i18n/I18nProvider'

/** Small copy button: copies the given string to the clipboard. */
export function CopyBtn({ value }: { value: string }) {
  const { t } = useI18n()
  const [done, setDone] = useState(false)
  const copy = () => {
    navigator.clipboard?.writeText(value).then(() => {
      setDone(true)
      setTimeout(() => setDone(false), 1000)
    }).catch(() => { /* ignore */ })
  }
  return (
    <button
      type="button"
      onClick={copy}
      title={t('Copy')}
      style={{
        background: 'none', border: 0, color: done ? '#3fb950' : '#8b949e',
        cursor: 'pointer', padding: '0 2px', fontSize: '0.9em', lineHeight: 1,
      }}
    >{done ? '✓' : '⧉'}</button>
  )
}

/**
 * Shared frame for the right-edge side panels (Help / Translate / Prompt
 * Help): fixed aside with header + close button + scrollable body. Renders
 * only while its panel id is the active one; the collapsed-state buttons
 * live in SidePanelDock.
 */
export function SidePanelShell({ id, title, children }: {
  id: SidePanelId
  title: string
  children: ReactNode
}) {
  const { panel, setPanel } = useHelp()
  const { t } = useI18n()
  if (panel !== id) return null
  return (
    <aside
      style={{
        position: 'fixed', right: 0, top: 100, bottom: 0, width: 320, zIndex: 1100,
        background: '#0d1117', borderLeft: '1px solid #30363d',
        boxShadow: '-4px 0 16px rgba(0,0,0,0.4)', display: 'flex',
        flexDirection: 'column', color: '#c9d1d9',
      }}
    >
      <div style={{
        display: 'flex', alignItems: 'center', padding: '8px 10px',
        borderBottom: '1px solid #30363d', flex: '0 0 auto',
      }}>
        <strong style={{ fontSize: '0.85em' }}>{title}</strong>
        <button
          type="button"
          onClick={() => setPanel(null)}
          title={t('Collapse')}
          style={{ marginLeft: 'auto', background: 'none', border: 0, color: '#8b949e', cursor: 'pointer', fontSize: '1.1em' }}
        >×</button>
      </div>
      <div style={{ padding: '10px 12px', overflowY: 'auto', fontSize: '0.82em', lineHeight: 1.5 }}>
        {children}
      </div>
    </aside>
  )
}
