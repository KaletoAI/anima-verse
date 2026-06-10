/**
 * NoticeBanner — persistenter Hinweis-Banner in /play (B Tier 1).
 * Quelle: GET /play/notices (kritische Events am Ort, Bewegungs-Sperre,
 * ungelesene Notifications). Rendert nichts, wenn nichts anliegt.
 * Notifications sind per Klick als gelesen markierbar (POST /notifications/{id}/read).
 */
import { useCallback, useEffect, useState, type CSSProperties } from 'react'
import { useI18n } from '../i18n/I18nProvider'
import { apiGet, apiPost } from '../lib/api'

interface NoticeEvent { id: string; category: string; text: string }
interface NoticeItem { id: number; kind: string; body: string }
interface ForceWarning {
  rule_id: string; rule_name: string; message: string
  go_to: string; go_to_location_id: string; go_to_room_id: string; set_activity: string
}
interface Notices {
  avatar: string
  events: NoticeEvent[]
  leave_blocked: string | null
  force_warning: ForceWarning | null
  notifications: NoticeItem[]
  unread_count: number
}

const EMPTY: Notices = { avatar: '', events: [], leave_blocked: null, force_warning: null, notifications: [], unread_count: 0 }

export function NoticeBanner() {
  const { t } = useI18n()
  const [n, setN] = useState<Notices>(EMPTY)

  const load = useCallback(async () => {
    try { setN(await apiGet<Notices>('/play/notices')) } catch { /* auth handled */ }
  }, [])

  useEffect(() => {
    load()
    const id = setInterval(load, 5000)
    return () => clearInterval(id)
  }, [load])

  const dismiss = useCallback(async (id: number) => {
    try { await apiPost(`/notifications/${id}/read`, {}) } catch { /* ignore */ }
    setN((prev) => ({ ...prev, notifications: prev.notifications.filter((x) => x.id !== id) }))
  }, [])

  const hasAny = n.events.length > 0 || !!n.leave_blocked || !!n.force_warning || n.notifications.length > 0
  if (!hasAny) return null

  // Opaker Hintergrund + farbiger Rand-Streifen — damit die Szene-Schrift
  // darunter nicht durchscheint (sonst „überlagert" sich der Text am Satzanfang).
  const row = (accent: string): CSSProperties => ({
    display: 'flex', alignItems: 'center', gap: 8, padding: '4px 10px',
    borderRadius: 8, background: 'rgba(16,18,24,0.94)',
    border: '1px solid rgba(255,255,255,0.12)', borderLeft: `4px solid ${accent}`,
    fontSize: '0.82em', maxWidth: '100%', boxShadow: '0 2px 8px rgba(0,0,0,0.45)',
  })

  const hasLeftItems = !!n.leave_blocked || n.events.length > 0 || n.notifications.length > 0

  return (
    <>
      {/* Force-Regel als zentrierter, schlanker Separator über die volle Breite —
          zeigt nur, von wem die Meldung kommt (Avatar) + der Text. Kein „Apply",
          kein opaker Block, damit kein UI-Platz weggenommen wird. */}
      {n.force_warning && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: 10, margin: '0 0 6px',
          fontSize: '0.8em', opacity: 0.85, pointerEvents: 'none',
        }}>
          <span style={{ flex: 1, height: 1, background: 'rgba(255,255,255,0.16)' }} />
          <span style={{ flex: '0 0 auto', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: '80%' }}>
            💤 <strong>{n.avatar}</strong>: {n.force_warning.message}
          </span>
          <span style={{ flex: 1, height: 1, background: 'rgba(255,255,255,0.16)' }} />
        </div>
      )}
      {hasLeftItems && (
        <div style={{
          display: 'flex', flexDirection: 'column', gap: 4,
          maxWidth: 'min(560px, 60vw)', margin: '0 0 6px', pointerEvents: 'auto',
        }}>
          {n.leave_blocked && (
            <div style={row('#e05656')}>
              <span>🚫</span>
              <span style={{ flex: 1 }}>{t('You cannot leave')}: {n.leave_blocked}</span>
            </div>
          )}
          {n.events.map((e) => (
            <div key={e.id} style={row('#e6963c')}>
              <span>⚠️</span>
              <span style={{ flex: 1 }}>{e.text}</span>
            </div>
          ))}
          {n.notifications.map((it) => (
            <div key={it.id} style={row('#78aaff')}>
              <span>🔔</span>
              <span style={{ flex: 1 }}>{it.body}</span>
              <button onClick={() => dismiss(it.id)} title={t('Mark as read')}
                style={{ border: 'none', background: 'transparent', color: 'inherit',
                         cursor: 'pointer', opacity: 0.7, fontSize: '1.1em', lineHeight: 1 }}>×</button>
            </div>
          ))}
        </div>
      )}
    </>
  )
}
