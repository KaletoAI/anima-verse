/**
 * SelfPanel — the avatar's own state (B tier 1, redesign).
 * Layout (following the old UI): portrait · status bars as a 2×3 grid · mood
 * (editable) · activity (read-only, set from the chat).
 * Outfit and inventory live in the Belongings panel.
 * Source: GET /play/self · setter: POST /play/self/mood.
 */
import { useToast } from './Toast'
import { StatHistoryPopover, type StatChange } from './StatHistoryPopover'
import { StatFill } from './StatBoost'
import { statTitle, conditionTitle, type StatBoost, type BoostCondition } from './statBoosts'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useI18n } from './I18nProvider'
import { ApiError, apiGet, apiPost } from './api'
import { usePoll } from './usePolling'
import { SYNC_ENDPOINTS } from './syncEndpoints'
import { EmptyState } from './EmptyState'
import { useEnlarge } from './ZoomButton'
import { transparentPortraitUrl } from './thumbs'

/** Public per-stat provenance; private rule/event details are never needed here. */
export interface StatCause {
  actor: string | null
  base_delta: number
  /** Present on records whose hourly budget was applied before influence. */
  capped_base_delta?: number
  modified_delta: number
  capped_delta: number
  factor: number
}
interface BarMeta { color?: string; label?: string; name?: string; name_de?: string }
interface SelfData {
  avatar: string
  stat_changes: StatChange[]
  stat_bands: Record<string, string>
  mood: string
  activity: string
  status_effects: Record<string, number>
  stat_boosts?: Record<string, StatBoost>
  bar_meta: Record<string, BarMeta>
  conditions: BoostCondition[]
  profile_image: string
  expression_version?: string
}

export function SelfPanel() {
  const { t, lang } = useI18n()
  const enlarge = useEnlarge()
  const { data, refresh } = usePoll<SelfData>(
    'play-self', () => apiGet<SelfData>('/play/self'), SYNC_ENDPOINTS.self)
  const { toast } = useToast()
  const seen = useRef<{ avatar: string; id: number; bands: Record<string, string> } | null>(null)
  const [history, setHistory] = useState<{ avatar: string; stat: string; anchor: HTMLElement } | null>(null)
  const closeHistory = useCallback(() => setHistory(null), [])
  useEffect(() => {
    if (!data) return
    const previous = seen.current
    const rows = data.stat_changes || []
    const bands = data.stat_bands || {}
    const newest = Math.max(0, ...rows.map(row => row.id))
    seen.current = { avatar: data.avatar, id: previous?.avatar === data.avatar ? Math.max(previous.id, newest) : newest, bands }
    if (!data.avatar || !previous || previous.avatar !== data.avatar) return
    const name = (key: string) => {
      const meta = data.bar_meta?.[key]
      return (lang === 'de' ? meta?.name_de || meta?.name : meta?.name) || key
    }
    for (const row of rows) {
      if (row.id <= previous.id) continue
      const change = Object.entries(row.changes).find(([, value]) => Math.abs(value.new - value.old) >= 10)
      if (change) {
        const [key, value] = change
        const delta = value.new - value.old
        toast(`${name(key)} ${delta < 0 ? '−' : '+'}${Math.abs(delta)}: ${t(row.stat_labels?.[key] ?? row.label)}`, 'info')
        return
      }
    }
    for (const key of new Set([...Object.keys(previous.bands), ...Object.keys(bands)])) {
      if ((bands[key] || '') !== (previous.bands[key] || '')) {
        toast(`${name(key)}: ${bands[key] || t('back to normal')}`, 'info')
        return
      }
    }
  }, [data, lang, t, toast])
  const [moodDraft, setMoodDraft] = useState('')
  const [activityDraft, setActivityDraft] = useState('')
  const [activityFocused, setActivityFocused] = useState(false)
  const [moodFocused, setMoodFocused] = useState(false)
  const [busy, setBusy] = useState(false)
  // On a very narrow panel, hide the bar labels and numbers and show only the
  // bar itself (with a clearly visible end).
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
    // Re-run as soon as the root div exists (data is still null at mount → the
    // early return leaves rootRef unset; the div only appears after loading).
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

  // A two-person action cannot be put on alone — the server refuses it with
  // 409 "pair_pose". Silently swallowing that leaves the player typing
  // "hug Kira" into a field that never reacts, so the refusal is spelled out
  // and points at the way that does work.
  const [activityNote, setActivityNote] = useState('')

  const setActivity = useCallback(async () => {
    if (busy) return
    setBusy(true)
    setActivityNote('')
    try { await apiPost('/play/self/activity', { activity: activityDraft.trim() }) }
    catch (e) {
      if (e instanceof ApiError && e.detail === 'pair_pose') {
        setActivityNote(t('That takes two — ask them with “Together…” on their card.'))
      }
    }
    await refresh()
    setBusy(false)
  }, [busy, activityDraft, refresh, t])

  if (!data || !data.avatar) {
    return <EmptyState icon="self" title={t('No active avatar')} />
  }

  const portraitUrl = data.profile_image
    ? transparentPortraitUrl(`/characters/${encodeURIComponent(data.avatar)}/images/${encodeURIComponent(data.profile_image)}`)
    : `/characters/${encodeURIComponent(data.avatar)}/outfit-expression?fallback=default&v=${encodeURIComponent(data.expression_version || '')}`
  const bars = Object.entries(data.status_effects || {})

  return (
    <div ref={rootRef} style={{ display: 'flex', flexDirection: 'column', gap: 8, fontSize: '0.9em', height: '100%', minHeight: 0 }}>
      {/* Portrait (scales with the window) with the bar overlay along its bottom */}
      <div style={{ flex: 1, minHeight: 0, position: 'relative', display: 'grid', placeItems: 'center', overflow: 'hidden' }}>
        <img src={portraitUrl} alt={data.avatar}
          onError={(e) => { (e.target as HTMLImageElement).style.visibility = 'hidden' }}
          {...enlarge({ src: portraitUrl, alt: data.avatar },
            { maxHeight: '100%', maxWidth: '100%', objectFit: 'contain', display: 'block' })} />

        {/* Conditions across the top of the image */}
        {data.conditions.length > 0 && (
          <div style={{ position: 'absolute', top: 6, left: 6, right: 6, display: 'flex', flexWrap: 'wrap', gap: 4 }}>
            {data.conditions.map((c, i) => (
              <span key={i} title={conditionTitle(t, c)} style={{ padding: '1px 7px', borderRadius: 10, fontSize: '0.7em',
                background: 'rgba(40,30,10,0.7)', border: '1px solid rgba(255,170,90,0.5)' }}>
                {c.icon ? `${c.icon} ` : ''}{c.label || c.name}
              </span>
            ))}
          </div>
        )}

        {/* Status bars as a 2×3 grid, laid over the bottom of the image */}
        {bars.length > 0 && (
          <div style={{
            position: 'absolute', left: 0, right: 0, bottom: 0,
            padding: '14px 8px 6px',
            background: 'linear-gradient(transparent, rgba(0,0,0,0.7) 38%)',
            display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '3px 10px',
          }}>
            {bars.map(([key, val]) => {
              const m = data.bar_meta?.[key] || {}
              const boost = data.stat_boosts?.[key]
              const value = boost?.value ?? Number(val)
              const pct = Math.max(0, Math.min(100, Number(val) || 0))
              const full = (lang === 'de' ? m.name_de || m.name : m.name) || key
              // Track with a clearly visible end (border) so the fill level can
              // be judged without the number — matters most in compact mode.
              const track = (
                <div style={{
                  position: 'relative', flex: 1, height: compact ? 7 : 5, borderRadius: 3,
                  background: 'rgba(255,255,255,0.18)',
                  border: '1px solid rgba(255,255,255,0.45)',
                  overflow: 'hidden', boxSizing: 'border-box',
                }}>
                  <StatFill base={pct} boost={boost} color={m.color || 'var(--accent,#6aa9ff)'} />
                </div>
              )
              return (
                <button type="button" key={key} title={statTitle(t, full, pct, boost)}
                  aria-label={full} aria-haspopup="dialog" aria-expanded={history?.avatar === data.avatar && history.stat === key}
                  onClick={event => setHistory({ avatar: data.avatar, stat: key, anchor: event.currentTarget })}
                  style={{ display: 'flex', alignItems: 'center', gap: 4, border: 0, padding: 0, background: 'transparent', color: 'inherit', cursor: 'pointer', minWidth: 0 }}>
                  {!compact && (
                    <span style={{ width: 26, opacity: 0.8, fontSize: '0.6em', textTransform: 'uppercase' }}>
                      {m.label || key.slice(0, 3)}
                    </span>
                  )}
                  {track}
                  {!compact && (
                    <span style={{ minWidth: 20, textAlign: 'right', fontVariantNumeric: 'tabular-nums', fontSize: '0.6em', opacity: 0.7 }}>{value}</span>
                  )}
                </button>
              )
            })}
          </div>
        )}
      </div>

      {history && history.avatar === data.avatar && (
        <StatHistoryPopover stat={history.stat}
          name={(lang === 'de' ? data.bar_meta[history.stat]?.name_de || data.bar_meta[history.stat]?.name : data.bar_meta[history.stat]?.name) || history.stat}
          rows={data.stat_changes || []} anchor={history.anchor} onClose={closeHistory} />
      )}

      {/* Mood */}
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

      {/* Current activity — editable (free text; the chat and the agent loop
          set it too). Setting it wakes a sleeping avatar. */}
      <label style={{ flex: '0 0 auto', display: 'flex', flexDirection: 'column', gap: 3 }}>
        <span style={{ opacity: 0.6, fontSize: '0.8em' }}>{t('Activity')}</span>
        <input value={activityDraft} disabled={busy}
          onFocus={() => setActivityFocused(true)}
          onBlur={() => { setActivityFocused(false); setActivity() }}
          onChange={(e) => setActivityDraft(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
          placeholder={t('What are you doing?')}
          className="ga-input" style={{ width: '100%', boxSizing: 'border-box' }} />
        {activityNote && (
          <span style={{ color: '#d6b06a', fontSize: '0.76em' }}>{activityNote}</span>
        )}
      </label>
    </div>
  )
}
