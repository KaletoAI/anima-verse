/**
 * SelfPanel — der eigene Zustand des Avatars (B Tier 1, Redesign).
 * Aufbau (an alter UI orientiert): Profilbild · Status-Balken als 2×3-Grid ·
 * Stimmung (editierbar) · Aktivität (read-only, wird aus dem Chat gesetzt).
 * Outfit/Inventar leben im Belongings-Panel.
 * Quelle: GET /play/self · Setter: POST /play/self/mood.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { useI18n } from '../i18n/I18nProvider'
import { apiGet, apiPost } from '../lib/api'
import { usePoll } from './usePolling'
import { EmptyState } from './EmptyState'

interface BarMeta { color?: string; label?: string; name?: string; name_de?: string }
interface SelfData {
  avatar: string
  mood: string
  activity: string
  status_effects: Record<string, number>
  bar_meta: Record<string, BarMeta>
  conditions: Array<{ name?: string; label?: string; icon?: string }>
  profile_image: string
}

export function SelfPanel() {
  const { t } = useI18n()
  const { data, refresh } = usePoll<SelfData>(
    'play-self', () => apiGet<SelfData>('/play/self'), { intervalMs: 5000 })
  const [moodDraft, setMoodDraft] = useState('')
  const [activityDraft, setActivityDraft] = useState('')
  const [activityFocused, setActivityFocused] = useState(false)
  const [moodFocused, setMoodFocused] = useState(false)
  const [busy, setBusy] = useState(false)
  // Bei sehr schmalem Panel die Balken-Beschriftung + Zahl ausblenden und nur
  // den Balken (mit klar sichtbarem Ende) zeigen.
  const rootRef = useRef<HTMLDivElement | null>(null)
  const [compact, setCompact] = useState(false)
  useEffect(() => {
    const el = rootRef.current
    if (!el) return
    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width || 0
      setCompact(w > 0 && w < 150)
    })
    ro.observe(el)
    return () => ro.disconnect()
    // Re-run sobald das Root-Div existiert (beim Mount ist data noch null →
    // frueher Return ohne rootRef; erst nach dem Laden ist das Div da).
  }, [data?.avatar])

  // Mirror the polled mood into the draft while the field is not focused.
  useEffect(() => {
    if (data && !moodFocused) setMoodDraft(data.mood || '')
  }, [data, moodFocused])

  useEffect(() => {
    if (data && !activityFocused) setActivityDraft(data.activity || '')
  }, [data, activityFocused])

  const setMood = useCallback(async () => {
    if (busy) return
    setBusy(true)
    try { await apiPost('/play/self/mood', { mood: moodDraft.trim() }); await refresh() }
    catch { /* ignore */ } finally { setBusy(false) }
  }, [busy, moodDraft, refresh])

  const setActivity = useCallback(async () => {
    if (busy) return
    setBusy(true)
    try { await apiPost('/play/self/activity', { activity: activityDraft.trim() }); await refresh() }
    catch { /* ignore */ } finally { setBusy(false) }
  }, [busy, activityDraft, refresh])

  if (!data || !data.avatar) {
    return <EmptyState icon="self" title={t('No active avatar')} />
  }

  const portraitUrl = data.profile_image
    ? `/characters/${encodeURIComponent(data.avatar)}/images/${encodeURIComponent(data.profile_image)}`
    : `/characters/${encodeURIComponent(data.avatar)}/outfit-expression?fallback=default`
  const bars = Object.entries(data.status_effects || {})

  return (
    <div ref={rootRef} style={{ display: 'flex', flexDirection: 'column', gap: 8, fontSize: '0.9em', height: '100%', minHeight: 0 }}>
      {/* Profilbild (skaliert mit dem Fenster) mit Balken-Overlay im unteren Bereich */}
      <div style={{ flex: 1, minHeight: 0, position: 'relative', display: 'grid', placeItems: 'center', overflow: 'hidden', borderRadius: 8, background: 'rgba(255,255,255,0.04)' }}>
        <img src={portraitUrl} alt={data.avatar}
          onError={(e) => { (e.target as HTMLImageElement).style.visibility = 'hidden' }}
          style={{ maxHeight: '100%', maxWidth: '100%', objectFit: 'contain', display: 'block' }} />

        {/* Conditions oben über dem Bild */}
        {data.conditions.length > 0 && (
          <div style={{ position: 'absolute', top: 6, left: 6, right: 6, display: 'flex', flexWrap: 'wrap', gap: 4 }}>
            {data.conditions.map((c, i) => (
              <span key={i} style={{ padding: '1px 7px', borderRadius: 10, fontSize: '0.7em',
                background: 'rgba(40,30,10,0.7)', border: '1px solid rgba(255,170,90,0.5)' }}>
                {c.icon ? `${c.icon} ` : ''}{c.label || c.name}
              </span>
            ))}
          </div>
        )}

        {/* Status-Balken als 2×3-Grid, unten ins Bild gelegt */}
        {bars.length > 0 && (
          <div style={{
            position: 'absolute', left: 0, right: 0, bottom: 0,
            padding: '14px 8px 6px',
            background: 'linear-gradient(transparent, rgba(0,0,0,0.7) 38%)',
            display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '3px 10px',
          }}>
            {bars.map(([key, val]) => {
              const m = data.bar_meta?.[key] || {}
              const pct = Math.max(0, Math.min(100, Number(val) || 0))
              const full = m.name_de || m.name || key
              // Track mit klar sichtbarem Ende (Rahmen), damit man die Füllung
              // auch ohne Zahl abschätzen kann — besonders im Compact-Modus.
              const track = (
                <div style={{
                  flex: 1, height: compact ? 7 : 5, borderRadius: 3,
                  background: 'rgba(255,255,255,0.18)',
                  border: '1px solid rgba(255,255,255,0.45)',
                  overflow: 'hidden', boxSizing: 'border-box',
                }}>
                  <div style={{ width: `${pct}%`, height: '100%', background: m.color || 'var(--accent,#6aa9ff)' }} />
                </div>
              )
              return (
                <div key={key} title={`${full}: ${pct}/100`}
                  style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                  {!compact && (
                    <span style={{ width: 26, opacity: 0.8, fontSize: '0.6em', textTransform: 'uppercase' }}>
                      {m.label || key.slice(0, 3)}
                    </span>
                  )}
                  {track}
                  {!compact && (
                    <span style={{ width: 16, textAlign: 'right', fontVariantNumeric: 'tabular-nums', fontSize: '0.6em', opacity: 0.7 }}>{pct}</span>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* Stimmung */}
      <label style={{ flex: '0 0 auto', display: 'flex', flexDirection: 'column', gap: 3 }}>
        <span style={{ opacity: 0.6, fontSize: '0.8em' }}>{t('Mood')}</span>
        <input value={moodDraft} disabled={busy}
          onFocus={() => setMoodFocused(true)}
          onBlur={() => { setMoodFocused(false); setMood() }}
          onChange={(e) => setMoodDraft(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
          placeholder={t('How do you feel?')}
          className="ga-input" style={{ width: '100%', boxSizing: 'border-box' }} />
      </label>

      {/* Aktuelle Aktivität — editierbar (freier Text; Chat/Loop setzen sie
          ebenfalls). Setzen weckt einen schlafenden Avatar. */}
      <label style={{ flex: '0 0 auto', display: 'flex', flexDirection: 'column', gap: 3 }}>
        <span style={{ opacity: 0.6, fontSize: '0.8em' }}>{t('Activity')}</span>
        <input value={activityDraft} disabled={busy}
          onFocus={() => setActivityFocused(true)}
          onBlur={() => { setActivityFocused(false); setActivity() }}
          onChange={(e) => setActivityDraft(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
          placeholder={t('What are you doing?')}
          className="ga-input" style={{ width: '100%', boxSizing: 'border-box' }} />
      </label>
    </div>
  )
}
