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

  // Apply the force rule manually (the avatar is never forced automatically):
  // set the activity and, if the rule moves somewhere, the location.
  const applyForce = useCallback(async (f: ForceWarning, avatar: string) => {
    if (!avatar) return
    try {
      if (f.set_activity) {
        await apiPost(`/characters/${encodeURIComponent(avatar)}/current-activity`,
          { current_activity: f.set_activity })
      }
      if (f.go_to && f.go_to !== 'stay' && f.go_to_location_id) {
        await apiPost(`/characters/${encodeURIComponent(avatar)}/current-location`,
          { current_location: f.go_to_location_id, current_room: f.go_to_room_id || '' })
      }
    } catch { /* ignore — reload shows the real state */ }
    load()
  }, [load])

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

  return (
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
      {n.force_warning && (
        <div style={row('#e6b13c')}>
          <span>⚠️</span>
          <span style={{ flex: 1 }}>
            <strong>{n.force_warning.rule_name || t('Forced rule')}:</strong> {n.force_warning.message}
          </span>
          <button onClick={() => applyForce(n.force_warning!, n.avatar)} title={t('Apply this rule')}
            style={{ border: '1px solid rgba(230,177,60,0.6)', background: 'rgba(230,177,60,0.18)',
                     color: 'inherit', cursor: 'pointer', borderRadius: 6, padding: '2px 8px',
                     fontSize: '0.92em', flex: '0 0 auto' }}>{t('Apply')}</button>
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
  )
}
