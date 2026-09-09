/**
 * MindThoughtsSection — read-only view of a character's thought journal,
 * a section of the Mind panel (next to Relationships/History).
 *
 * ADMIN ONLY: it renders solely when MindPanel gets `withThoughts` (the
 * Game-Admin Mind tab) — never in /play. Thoughts are private cognition; the
 * endpoint behind this is admin-gated, and they exist nowhere a player or
 * another character could reach. No editing, no deleting (v1) — the journal
 * prunes itself after the daily consolidation.
 *
 * Backend: GET /characters/{n}/thoughts?limit=&before= — delivers location/
 * room NAMES and the characters present at turn time (user feedback
 * 2026-07-29: ids and missing presence made the entries unreadable).
 */
import { Fragment, useCallback, useEffect, useState } from 'react'
import type React from 'react'
import { useI18n } from './I18nProvider'
import { apiGet } from './api'
import { formatDate, formatTime } from './clockFormat'
import { clockSettings, useClockSettings } from './clockSettings'

export interface ThoughtEntry {
  ts: string
  /** GAME time of the thought as the canonical world-calendar stamp
   *  (`Y0002-D109T14:00:00`). Empty for rows written before the column
   *  existed. Kept for callers that need the raw instant — the display uses
   *  `game_label` below. */
  game_ts?: string
  /** The stamp above already rendered by the SERVER ("Summer, day 17 · 14:23
   *  · Year 3"). Empty whenever `game_ts` is — clients never format a game
   *  stamp themselves. */
  game_label?: string
  location_name: string
  room_name: string
  present: string[]
  /** Characters in OTHER rooms of the location at thought time, as frozen
   *  "Name (room)" snapshots. Empty for rows written before the column. */
  nearby?: string[]
  content: string
}

const PAGE = 50

// Same time vocabulary as the Timeline next door (MindPanel) — local copies,
// because importing from MindPanel would close an import cycle.
// SYSTEM stamps — shown in the configured world timezone and clock format,
// not in the viewer's browser locale.
function clockOf(ts: string): string {
  return formatTime(ts, clockSettings()) || ts
}
function dayOf(ts: string): string {
  return formatDate(ts, clockSettings(),
    { weekday: 'short', year: 'numeric', month: 'long', day: 'numeric' })
}
/** The clock part of the server-rendered world-calendar label ("Summer, day
 *  17 · 14:23 · Year 3" → "14:23") for the narrow time column, re-rendered in
 *  the configured clock format. The label always arrives in 24h — it is the
 *  same string prompts get — so the hour and minute are read out of it and
 *  formatted here. The full label goes into the tooltip; nothing here parses a
 *  game stamp. */
function gameClockOf(gameLabel?: string): string {
  // The label arrives with its clock part already in the configured display
  // format (the 12h shapes carry an AM/PM suffix), so this only cuts it out —
  // no reformatting, no game-stamp parsing.
  const m = /\b(\d{1,2}:\d{2}(?::\d{2})?(?:\s?[AP]M)?)/.exec(gameLabel || '')
  return m ? m[1].trim() : ''
}
const sepStyle: React.CSSProperties = {
  margin: '6px 0 2px', fontSize: '0.74em', opacity: 0.55, letterSpacing: 0.4,
  borderBottom: '1px solid rgba(255,255,255,0.12)', paddingBottom: 2,
}

/** Splits the `[trigger: …]` prefix the journal writes for prompted turns. */
function splitTrigger(content: string): { trigger: string; text: string } {
  const m = /^\[trigger:\s*([^\]]*)\]\s*\n?/.exec(content || '')
  return m ? { trigger: m[1].trim(), text: content.slice(m[0].length) }
    : { trigger: '', text: content || '' }
}

export function MindThoughtsSection({ character }: { character: string }) {
  // Subscribe to the shared clock settings so the stamp helpers above
  // re-render once the server-configured format and timezone arrive.
  useClockSettings()
  const { t } = useI18n()
  const [entries, setEntries] = useState<ThoughtEntry[]>([])
  const [hasMore, setHasMore] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async (before?: string) => {
    if (!character) return
    setLoading(true)
    try {
      const q = `limit=${PAGE}` + (before ? `&before=${encodeURIComponent(before)}` : '')
      const d = await apiGet<{ thoughts: ThoughtEntry[]; has_more: boolean }>(
        `/characters/${encodeURIComponent(character)}/thoughts?${q}`)
      // `before` set = load-more, so append; otherwise this is a fresh load.
      setEntries((prev) => (before ? [...prev, ...(d.thoughts || [])] : (d.thoughts || [])))
      setHasMore(!!d.has_more)
      setError('')
    } catch (e) {
      setError((e as Error).message)
      if (!before) setEntries([])
    } finally {
      setLoading(false)
    }
  }, [character])

  useEffect(() => {
    setEntries([])
    setHasMore(false)
    void load()
  }, [load])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8, height: '100%', overflow: 'auto' }}>
      <div className="ga-hint">
        {t('What this character thought during their autonomous turns — private: it never reaches another character, a chat or a player. Raw thoughts are removed a few days after the day they belong to has been consolidated.')}
      </div>

      {error ? <div className="ga-hint">{error}</div> : null}

      {!entries.length && !loading && !error ? (
        <div className="ga-placeholder">{t('No thoughts recorded yet.')}</div>
      ) : null}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {entries.map((e, i) => {
          const day = dayOf(e.ts)
          const prevDay = i > 0 ? dayOf(entries[i - 1].ts) : ''
          const { trigger, text } = splitTrigger(e.content)
          return (
            <Fragment key={`${e.ts}-${i}`}>
              {day && day !== prevDay ? <div style={sepStyle}>{day}</div> : null}
              <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
                <span style={{ flex: '0 0 52px', opacity: 0.5, fontSize: '0.74em',
                               fontVariantNumeric: 'tabular-nums', paddingTop: 7,
                               display: 'flex', flexDirection: 'column', gap: 1 }}>
                  <span>{clockOf(e.ts)}</span>
                  {e.game_label ? (
                    <span title={`${t('Game time')}: ${e.game_label}`}>
                      🕰 {gameClockOf(e.game_label) || e.game_label}
                    </span>
                  ) : null}
                </span>
                <div style={{ flex: 1, minWidth: 0, padding: '6px 10px', borderRadius: 8,
                              background: 'rgba(255,255,255,0.035)',
                              borderLeft: '3px solid rgba(120,170,255,0.35)' }}>
                  {(e.location_name || e.present?.length || e.nearby?.length || trigger) ? (
                    <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'baseline',
                                  fontSize: '0.78em', opacity: 0.65, marginBottom: 3 }}>
                      {e.location_name ? (
                        <span>📍 {e.location_name}{e.room_name ? ` · ${e.room_name}` : ''}</span>
                      ) : null}
                      {e.present?.length ? (
                        <span title={t('Characters present at the time of the thought')}>
                          👥 {e.present.join(', ')}
                        </span>
                      ) : null}
                      {e.nearby?.length ? (
                        <span style={{ opacity: 0.75 }}
                          title={t('At this location, but in another room — out of sight and earshot at the time of the thought.')}>
                          🚪 {e.nearby.join(', ')}
                        </span>
                      ) : null}
                      {trigger ? (
                        <span style={{ color: 'var(--warn, #d8b45a)', opacity: 0.9 }}
                          title={t('This thought was prompted (manual trigger or loop hint).')}>
                          ⚡ {trigger}
                        </span>
                      ) : null}
                    </div>
                  ) : null}
                  <div style={{ whiteSpace: 'pre-wrap', lineHeight: 1.45,
                                fontStyle: 'italic', opacity: 0.92 }}>
                    {text}
                  </div>
                </div>
              </div>
            </Fragment>
          )
        })}
      </div>

      {loading ? <div className="ga-loading">{t('Loading…')}</div> : null}

      {hasMore && !loading ? (
        <button type="button" className="ga-btn ga-btn-sm" style={{ alignSelf: 'flex-start' }}
          onClick={() => { void load(entries[entries.length - 1]?.ts) }}>
          {t('Load more')}
        </button>
      ) : null}
    </div>
  )
}
