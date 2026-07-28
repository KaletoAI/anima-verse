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
import { useCallback, useEffect, useState } from 'react'
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

function fmtTs(ts: string): string {
  const d = new Date(ts)
  return Number.isNaN(d.getTime()) ? ts : d.toLocaleString()
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

      <div className="ga-thought-list">
        {entries.map((e, i) => (
          <div key={`${e.ts}-${i}`} className="ga-thought-entry">
            <div className="ga-thought-meta">
              <span>{fmtTs(e.ts)}</span>
              {e.location_name ? (
                <span>· {e.location_name}{e.room_name ? ` (${e.room_name})` : ''}</span>
              ) : null}
              {e.present?.length ? (
                <span title={t('Characters present at the time of the thought')}>
                  · {t('with')} {e.present.join(', ')}
                </span>
              ) : null}
            </div>
            <div className="ga-thought-text">{e.content}</div>
          </div>
        ))}
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
