/**
 * ScenesRecap — einklappbare „Was bisher geschah"-Leiste oben im Chat-Panel.
 * Zeigt die zuletzt konsolidierten Szenen des Avatars (Zeit · Ort · Mit-Teilnehmer
 * · kurze Summary) aus GET /play/scenes. Standard eingeklappt; getrennt vom
 * Live-Stream darunter. plan-room-conversation §7 (Avatar-Recap).
 */
import { useEffect, useState } from 'react'
import { useI18n } from '../i18n/I18nProvider'
import { apiGet } from '../lib/api'

interface SceneRecap {
  ts: string
  location_name: string
  room_name: string
  participants: string[]
  summary: string
}

function fmtTime(ts: string): string {
  if (!ts) return ''
  const d = new Date(ts)
  return isNaN(d.getTime())
    ? ''
    : d.toLocaleString([], { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
}

export function ScenesRecap() {
  const { t } = useI18n()
  const [scenes, setScenes] = useState<SceneRecap[]>([])
  const [open, setOpen] = useState(false)

  useEffect(() => {
    let alive = true
    const tick = async () => {
      try {
        const d = await apiGet<{ scenes?: SceneRecap[] }>('/play/scenes')
        // Server returns newest-first (limit semantics); the recap reads like
        // a story -> chronological, oldest at the top.
        if (alive) setScenes((d?.scenes || []).slice().reverse())
      } catch { /* auth handled in api.ts */ }
    }
    tick()
    const id = setInterval(tick, 30000)  // Szenen ändern sich selten (Idle-Konsolidierung)
    return () => { alive = false; clearInterval(id) }
  }, [])

  if (!scenes.length) return null

  return (
    <div style={{
      flex: '0 0 auto',
      borderBottom: '1px solid var(--border, #30363d)',
      background: 'var(--bg-container, #161b22)',
    }}>
      <button onClick={() => setOpen((o) => !o)} style={{
        width: '100%', textAlign: 'left', padding: '5px 12px',
        background: 'transparent', border: 'none', color: 'inherit',
        cursor: 'pointer', fontSize: '0.82em', opacity: 0.8,
      }}>
        {open ? '▾' : '▸'} {t('Earlier')} ({scenes.length})
      </button>
      {open && (
        <div style={{ maxHeight: 170, overflowY: 'auto', padding: '0 12px 8px' }}>
          {scenes.map((s, i) => (
            <div key={i} style={{
              fontSize: '0.8em', padding: '5px 0',
              borderTop: i ? '1px solid rgba(255,255,255,0.06)' : 'none',
            }}>
              <div style={{ opacity: 0.55, fontSize: '0.92em' }}>
                {fmtTime(s.ts)} · {s.location_name}{s.room_name ? ` – ${s.room_name}` : ''}
                {s.participants.length ? ` · ${t('with')} ${s.participants.join(', ')}` : ''}
              </div>
              <div style={{ opacity: 0.9 }}>{s.summary}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
