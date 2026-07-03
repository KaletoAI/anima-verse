/**
 * NoticeBanner — persistenter Hinweis-Banner in /play (B Tier 1).
 * Quelle: GET /play/notices (kritische Events am Ort, Bewegungs-Sperre,
 * ungelesene Notifications). Rendert nichts, wenn nichts anliegt.
 * Notifications sind per Klick als gelesen markierbar (POST /notifications/{id}/read).
 */
import { useCallback, useEffect, useState, type CSSProperties } from 'react'
import { useI18n } from '../i18n/I18nProvider'
import { apiGet, apiPost } from '../lib/api'
import { usePoll } from './usePolling'

interface NoticeEvent { id: string; category: string; text: string }
interface NoticeItem { id: number; kind: string; body: string }
interface ForceWarning {
  rule_id: string; rule_name: string; message: string
  go_to: string; go_to_location_id: string; go_to_room_id: string; set_activity: string
}
interface PartyInfo { role: 'leader' | 'follower'; leader: string; members: string[] }
interface Notices {
  avatar: string
  events: NoticeEvent[]
  leave_blocked: string | null
  force_warning: ForceWarning | null
  notifications: NoticeItem[]
  unread_count: number
  party: PartyInfo | null
}

const EMPTY: Notices = { avatar: '', events: [], leave_blocked: null, force_warning: null, notifications: [], unread_count: 0, party: null }

export function NoticeBanner() {
  const { t } = useI18n()
  const [n, setN] = useState<Notices>(EMPTY)
  const { data } = usePoll<Notices>(
    'play-notices', () => apiGet<Notices>('/play/notices'), { intervalMs: 5000 })

  // Polled state is authoritative; dismiss/leaveParty below patch it
  // optimistically until the next poll (same net behavior as before).
  useEffect(() => { if (data) setN(data) }, [data])

  const dismiss = useCallback(async (id: number) => {
    try { await apiPost(`/notifications/${id}/read`, {}) } catch { /* ignore */ }
    setN((prev) => ({ ...prev, notifications: prev.notifications.filter((x) => x.id !== id) }))
  }, [])

  const leaveParty = useCallback(async () => {
    try { await apiPost('/play/party/leave', {}) } catch { /* ignore */ }
    setN((prev) => ({ ...prev, party: null }))
  }, [])

  const hasAny = n.events.length > 0 || !!n.leave_blocked || !!n.force_warning
    || n.notifications.length > 0 || !!n.party
  if (!hasAny) return null

  // Opaker Hintergrund + farbiger Rand-Streifen — damit die Szene-Schrift
  // darunter nicht durchscheint. Explizite helle Textfarbe (nicht `inherit`),
  // sonst ist die Schrift je nach Theme/Kontext auf dem dunklen Block unlesbar.
  const row = (accent: string): CSSProperties => ({
    display: 'flex', alignItems: 'center', gap: 8, padding: '6px 12px',
    borderRadius: 8, background: 'rgba(16,18,24,0.94)', color: 'var(--text, #e6edf3)',
    border: '1px solid rgba(255,255,255,0.12)', borderLeft: `4px solid ${accent}`,
    fontSize: 13, lineHeight: 1.35, maxWidth: '100%', boxShadow: '0 2px 8px rgba(0,0,0,0.45)',
    pointerEvents: 'auto',
  })

  const hasLeftItems = !!n.leave_blocked || n.events.length > 0
    || n.notifications.length > 0 || !!n.party

  // Overlay statt Inline-Fluss: der Banner-Container ist 0px hoch und lässt seinen
  // Inhalt nach unten überlaufen, zentriert über den oberen Panel-Rand. So
  // verschiebt er die UI-Verteilung NICHT, auch wenn mehrere Meldungen anliegen.
  // Container ohne Pointer-Events (Panels darunter bleiben bedienbar), nur die
  // interaktiven Elemente (×) fangen Klicks ab.
  return (
    <div style={{
      position: 'relative', height: 0, overflow: 'visible', zIndex: 60,
      display: 'flex', flexDirection: 'column', alignItems: 'center',
      gap: 6, paddingTop: 6, pointerEvents: 'none',
    }}>
      {/* Force-Regel als zentrierter, schlanker Separator. */}
      {n.force_warning && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: 10, width: 'min(560px, 70vw)', maxWidth: '100%',
          fontSize: 12.5, opacity: 0.85, color: 'var(--text, #e6edf3)',
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
          width: 'min(560px, 70vw)', maxWidth: '100%',
        }}>
          {n.party && (
            <div style={row('#78aaff')}>
              <span>👥</span>
              <span style={{ flex: 1 }}>
                {n.party.role === 'follower'
                  ? `${t('You are in a party, following')} ${n.party.leader}`
                  : `${t('You lead a party with')} ${n.party.members.join(', ')}`}
              </span>
              <button onClick={leaveParty}
                style={{ border: '1px solid rgba(255,255,255,0.25)', background: 'transparent',
                         color: 'inherit', cursor: 'pointer', borderRadius: 6,
                         padding: '1px 8px', fontSize: '0.92em' }}>
                {t('Leave party')}
              </button>
            </div>
          )}
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
    </div>
  )
}
