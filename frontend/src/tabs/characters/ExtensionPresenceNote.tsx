/**
 * ExtensionPresenceNote — the viewer's line about the shown model's extension groups (Ruling A64,
 * `extensionPresence.ts`): one row per line, its light first, the record's own reason on mouse-over. Rendered in
 * the viewer's toggle column (Model3DViewer `extensionNote`) of the Figure tab and the 3D tab.
 */
import { useI18n } from '../../i18n/I18nProvider'
import { StepLight } from './StepRows'
import { presenceLines } from './extensionPresence'
import type { ExtensionPresence } from './extensionPresence'

export function ExtensionPresenceNote({ presence }: { presence: ExtensionPresence | null | undefined }) {
  const { t } = useI18n()
  const lines = presenceLines(presence, t)
  if (!lines.length) return null
  return (
    <div className="ga-ext-presence" style={{
      display: 'flex', flexDirection: 'column', gap: 3, maxWidth: 300, padding: '4px 8px', borderRadius: 4,
      background: 'rgba(13,17,23,0.78)', color: '#e6edf3', fontSize: 11, lineHeight: 1.35,
    }}>
      {lines.map((line, i) => (
        <span key={i} title={line.title} style={{ display: 'flex', gap: 6, alignItems: 'baseline',
          fontWeight: i === 0 ? 600 : undefined, opacity: line.light === null && i > 0 ? 0.8 : undefined }}>
          {line.light ? <StepLight light={line.light} /> : null}
          <span>{line.text}</span>
        </span>
      ))}
    </div>
  )
}
