/**
 * ThoughtsTab — read-only view of a character's thought journal.
 *
 * A thought turn's narrative (inner monologue, plans, judgements) used to be
 * discarded after the Tool-LLM had read it; it is journalled now
 * (plan-thought-journal.md). This panel is the history — the agent-loop admin
 * page keeps its own live preview of the CURRENT turn, which this does not
 * replace.
 *
 * Thoughts are private cognition: the endpoint behind this is admin-gated, and
 * they exist nowhere else a player or another character could reach. No
 * editing and no deleting here (v1) — the journal prunes itself after the
 * daily consolidation.
 *
 * Backend: GET /characters/{n}/thoughts?limit=&before=
 */
import { useCallback, useEffect, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet } from '../../lib/api'

export interface ThoughtEntry {
  ts: string
  location_id: string
  room_id: string
  content: string
}

const PAGE = 50

function fmtTs(ts: string): string {
  const d = new Date(ts)
  return Number.isNaN(d.getTime()) ? ts : d.toLocaleString()
}

export function ThoughtsTab({ character }: { character: string }) {
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
    <div className="ga-form">
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
              {e.location_id ? <span>· {e.location_id}</span> : null}
              {e.room_id ? <span>· {e.room_id}</span> : null}
            </div>
            <div className="ga-thought-text">{e.content}</div>
          </div>
        ))}
      </div>

      {loading ? <div className="ga-loading">{t('Loading…')}</div> : null}

      {hasMore && !loading ? (
        <button type="button" className="ga-btn ga-btn-sm"
          onClick={() => { void load(entries[entries.length - 1]?.ts) }}>
          {t('Load more')}
        </button>
      ) : null}
    </div>
  )
}
