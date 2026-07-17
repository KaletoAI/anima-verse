import { useHelp, type SidePanelId } from './HelpContext'
import { useI18n } from '../i18n/I18nProvider'

/**
 * Stacked collapsed-state buttons for the right-edge side panels. One shared
 * flex column so the buttons never overlap regardless of label length, and
 * they stay reachable while a panel is open (the dock shifts to the panel's
 * left edge so switching panels is a single click).
 */
const PANELS: Array<{ id: SidePanelId; label: string; color: string }> = [
  { id: 'help', label: 'Help', color: '#1f6feb' },
  { id: 'translate', label: 'Translate', color: '#238636' },
  { id: 'prompt', label: 'Prompt Help', color: '#8957e5' },
]

export function SidePanelDock() {
  const { panel, setPanel } = useHelp()
  const { t } = useI18n()
  return (
    <div
      style={{
        position: 'fixed', right: panel ? 320 : 0, top: 140, zIndex: 1101,
        display: 'flex', flexDirection: 'column', gap: 8, alignItems: 'flex-end',
      }}
    >
      {PANELS.map((p) => (
        <button
          key={p.id}
          type="button"
          onClick={() => setPanel(panel === p.id ? null : p.id)}
          title={t(p.label)}
          style={{
            background: p.color, color: '#fff', border: 0,
            borderRadius: '6px 0 0 6px', padding: '10px 7px', cursor: 'pointer',
            writingMode: 'vertical-rl', fontSize: '0.8em', letterSpacing: 1,
            opacity: panel && panel !== p.id ? 0.75 : 1,
          }}
        >
          {p.id === 'help' ? `? ${t(p.label)}` : t(p.label)}
        </button>
      ))}
    </div>
  )
}
