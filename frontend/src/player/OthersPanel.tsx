/**
 * OthersPanel — Zustand der anwesenden anderen Charaktere (read-only), als
 * Gegenstück zu Self. Karten fließen responsive nebeneinander/untereinander
 * (flex-wrap je nach Fensterbreite). Quelle: GET /play/others.
 */
import { useEffect, useRef, useState } from 'react'
import { useI18n } from '../i18n/I18nProvider'
import { apiGet } from '../lib/api'
import { usePoll } from './usePolling'
import { EmptyState } from './EmptyState'

interface BarMeta { color?: string; label?: string; name?: string; name_de?: string }
interface CharState {
  name: string
  mood: string
  activity: string
  status_effects: Record<string, number>
  bar_meta: Record<string, BarMeta>
  conditions: Array<{ name?: string; label?: string; icon?: string }>
  profile_image: string
  in_party?: boolean
}
interface Others { avatar: string; characters: CharState[] }

function portraitUrl(c: CharState): string {
  return c.profile_image
    ? `/characters/${encodeURIComponent(c.name)}/images/${encodeURIComponent(c.profile_image)}`
    : `/characters/${encodeURIComponent(c.name)}/outfit-expression?fallback=default`
}

function StatBars({ c }: { c: CharState }) {
  const bars = Object.entries(c.status_effects || {})
  // Bei schmaler Karte Label + Zahl ausblenden, nur Balken (mit klarem Ende).
  const ref = useRef<HTMLDivElement | null>(null)
  const [compact, setCompact] = useState(false)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width || 0
      setCompact(w > 0 && w < 150)
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  if (!bars.length) return null
  return (
    <div ref={ref} style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '2px 8px', marginTop: 4 }}>
      {bars.map(([key, val]) => {
        const m = c.bar_meta?.[key] || {}
        const pct = Math.max(0, Math.min(100, Number(val) || 0))
        return (
          <div key={key} title={`${m.name_de || m.name || key}: ${pct}/100`}
            style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
            {!compact && (
              <span style={{ width: 24, opacity: 0.7, fontSize: '0.58em', textTransform: 'uppercase' }}>{m.label || key.slice(0, 3)}</span>
            )}
            <div style={{
              flex: 1, height: compact ? 6 : 4, borderRadius: 3,
              background: 'rgba(255,255,255,0.16)',
              border: '1px solid rgba(255,255,255,0.45)',
              overflow: 'hidden', boxSizing: 'border-box',
            }}>
              <div style={{ width: `${pct}%`, height: '100%', background: m.color || 'var(--accent,#6aa9ff)' }} />
            </div>
            {!compact && (
              <span style={{ width: 14, textAlign: 'right', fontVariantNumeric: 'tabular-nums', fontSize: '0.58em', opacity: 0.65 }}>{pct}</span>
            )}
          </div>
        )
      })}
    </div>
  )
}

export function OthersPanel() {
  const { t } = useI18n()
  const { data } = usePoll<Others>(
    'play-others', () => apiGet<Others>('/play/others'), { intervalMs: 5000 })

  if (!data) return <EmptyState small title={t('Loading…')} />
  if (!data.characters.length) {
    return <EmptyState icon="others" title={t('Nobody else is here.')} />
  }

  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, alignContent: 'flex-start', height: '100%', minHeight: 0, overflow: 'auto', fontSize: '0.9em' }}>
      {data.characters.map((c) => (
        <div key={c.name} style={{
          flex: '1 1 190px', minWidth: 160, maxWidth: '100%', alignSelf: 'flex-start',
          display: 'flex', flexDirection: 'column', gap: 4, padding: 8, borderRadius: 8,
          // Party-Mitglieder bekommen eine eigene (blaue) Karten-Farbe.
          background: c.in_party ? 'rgba(120,170,255,0.16)' : 'rgba(255,255,255,0.05)',
          border: c.in_party ? '1px solid rgba(120,170,255,0.55)' : '1px solid rgba(255,255,255,0.08)',
        }}>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <img src={portraitUrl(c)} alt={c.name}
              onError={(e) => { (e.target as HTMLImageElement).style.visibility = 'hidden' }}
              style={{ width: 44, height: 44, borderRadius: 6, objectFit: 'cover', flex: '0 0 auto', background: 'rgba(255,255,255,0.08)' }} />
            <div style={{ minWidth: 0 }}>
              <div style={{ fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {c.name}{c.in_party ? <span title={t('In your party')} style={{ marginLeft: 4 }}>👥</span> : null}
              </div>
              {c.mood && <div style={{ opacity: 0.6, fontSize: '0.78em', fontStyle: 'italic', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{c.mood}</div>}
              {c.activity && <div style={{ opacity: 0.55, fontSize: '0.74em', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{c.activity}</div>}
            </div>
          </div>
          {c.conditions.length > 0 && (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 3 }}>
              {c.conditions.map((cd, i) => (
                <span key={i} style={{ padding: '0 6px', borderRadius: 9, fontSize: '0.7em',
                  background: 'rgba(255,170,90,0.2)', border: '1px solid rgba(255,170,90,0.4)' }}>
                  {cd.icon ? `${cd.icon} ` : ''}{cd.label || cd.name}
                </span>
              ))}
            </div>
          )}
          <StatBars c={c} />
        </div>
      ))}
    </div>
  )
}
