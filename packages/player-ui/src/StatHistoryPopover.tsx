import { useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'
import { useI18n } from './I18nProvider'

export interface StatChange {
  id: number
  game_ts: string
  label: string
  changes: Record<string, { old: number; new: number }>
}

export function StatHistoryPopover({ stat, name, rows, anchor, onClose }: {
  stat: string; name: string; rows: StatChange[]; anchor: HTMLElement; onClose: () => void
}) {
  const { t } = useI18n()
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const outside = (event: PointerEvent) => {
      if (!ref.current?.contains(event.target as Node) && !anchor.contains(event.target as Node)) onClose()
    }
    const escape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { onClose(); anchor.focus() }
    }
    document.addEventListener('pointerdown', outside)
    document.addEventListener('keydown', escape)
    return () => {
      document.removeEventListener('pointerdown', outside)
      document.removeEventListener('keydown', escape)
    }
  }, [anchor, onClose])
  const rect = anchor.getBoundingClientRect()
  const history = rows.filter(row => row.changes[stat]).slice(0, 10)
  return createPortal(
    <div ref={ref} role="dialog" aria-label={`${name}: ${t('History')}`}
      style={{ position: 'fixed', zIndex: 10000, left: Math.max(8, Math.min(rect.left, window.innerWidth - 328)),
        top: Math.max(8, Math.min(rect.bottom + 6, window.innerHeight - 300)),
        width: 300, maxWidth: 'calc(100vw - 32px)', maxHeight: 'min(280px, calc(100vh - 32px))', overflow: 'auto',
        padding: 12, borderRadius: 8, background: 'var(--bg, #20242c)', color: 'var(--text, #eee)',
        border: '1px solid var(--border, #555)', boxShadow: '0 6px 24px #0008' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
        <strong>{name}: {t('History')}</strong>
        <button type="button" onClick={onClose} aria-label={t('Close')}>×</button>
      </div>
      {history.length === 0 ? <p>{t('No recent changes')}</p> : history.map(row => (
        <div key={row.id} style={{ marginTop: 8 }}>
          <div>{row.label}: {row.changes[stat].old}→{row.changes[stat].new}</div>
          <small style={{ opacity: 0.7 }}>{row.game_ts}</small>
        </div>
      ))}
    </div>, document.body)
}
