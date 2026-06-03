/**
 * LayoutsPanel — benannte Layouts verwalten (speichern / laden / überschreiben /
 * löschen). plan-room-conversation Phase 2.
 *
 * Bewusst KEINE JS-Dialoge (kein window.prompt) — alles als In-App-UI.
 * Wird als Dialog-Panel gerendert (siehe PlayerApp `kind: 'dialog'`).
 * Einheitliche Schriftgröße über den Wurzel-Container (alles `inherit`).
 */
import { useState } from 'react'
import { useI18n } from '../i18n/I18nProvider'

const FONT = 13

const btn: React.CSSProperties = {
  padding: '3px 9px', borderRadius: 6, cursor: 'pointer',
  fontSize: 'inherit', fontFamily: 'inherit',
  border: '1px solid var(--border, #30363d)',
  background: 'var(--bg-hover, #1f2937)', color: 'inherit',
}

export function LayoutsPanel({
  presets, onSave, onLoad, onDelete,
}: {
  presets: Record<string, unknown>
  onSave: (name: string) => void
  onLoad: (name: string) => void
  onDelete: (name: string) => void
}) {
  const { t } = useI18n()
  const [name, setName] = useState('')
  const names = Object.keys(presets).sort((a, b) => a.localeCompare(b))
  const exists = names.includes(name.trim())

  const save = () => {
    const n = name.trim()
    if (!n) return
    onSave(n)
    setName('')
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10, fontSize: FONT }}>
      <div style={{ display: 'flex', gap: 6 }}>
        <input value={name} onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') save() }}
          placeholder={t('Layout name')}
          style={{
            flex: 1, minWidth: 0, padding: '3px 8px', borderRadius: 6,
            fontSize: 'inherit', fontFamily: 'inherit',
            border: '1px solid var(--border, #30363d)',
            background: 'var(--bg, #0d1117)', color: 'inherit',
          }} />
        <button onClick={save} disabled={!name.trim()} style={btn}>
          {exists ? t('Overwrite') : t('Save')}
        </button>
      </div>

      {names.length === 0 ? (
        <div style={{ opacity: 0.5 }}>{t('No saved layouts yet.')}</div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          {names.map((n) => (
            <div key={n} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{n}</span>
              <button onClick={() => onLoad(n)} style={btn} title={t('Load this layout')}>{t('Load')}</button>
              <button onClick={() => onSave(n)} style={btn} title={t('Overwrite with current layout')}>{t('Overwrite')}</button>
              <button onClick={() => onDelete(n)} style={{ ...btn, background: 'transparent', opacity: 0.7 }} title={t('Delete')}>×</button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
