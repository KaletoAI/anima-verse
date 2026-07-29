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
import { useI18n } from '../i18n/I18nProvider'
import { apiGet } from '../lib/api'

export interface ThoughtEntry {
  ts: string
  location_name: string
  room_name: string
  present: string[]
  content: string
}

const PAGE = 50

// Same time vocabulary as the Timeline next door (MindPanel) — local copies,
// because importing from MindPanel would close an import cycle.
function clockOf(ts: string): string {
  const d = new Date(ts)
  return Number.isNaN(d.getTime()) ? ts : d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}
function dayOf(ts: string): string {
  const d = new Date(ts)
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleDateString([], { weekday: 'short', year: 'numeric', month: 'long', day: 'numeric' })
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
                <span style={{ flex: '0 0 38px', opacity: 0.5, fontSize: '0.74em',
                               fontVariantNumeric: 'tabular-nums', paddingTop: 7 }}>
                  {clockOf(e.ts)}
                </span>
                <div style={{ flex: 1, minWidth: 0, padding: '6px 10px', borderRadius: 8,
                              background: 'rgba(255,255,255,0.035)',
                              borderLeft: '3px solid rgba(120,170,255,0.35)' }}>
                  {(e.location_name || e.present?.length || trigger) ? (
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
