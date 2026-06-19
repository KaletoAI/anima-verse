import { useCallback, useEffect, useState } from 'react'
import { useI18n } from '../i18n/I18nProvider'
import { apiGet } from '../lib/api'
import './NewsPanel.css'

/**
 * Player news channel — surfaces world events (posted by admins in the Events
 * tab) as news. danger/disruption events are shown as "breaking". The visual
 * style is world-configurable (modern / newspaper / flyer) so a low-tech world
 * reads like a printed flyer and a modern world like a media feed.
 */

type NewsStyle = 'modern' | 'newspaper' | 'flyer'

interface NewsItem {
  id: string
  text: string
  category: string
  created_at: string
  location_id: string
  global: boolean
  breaking: boolean
}

interface NewsFeed {
  avatar: string
  style: NewsStyle
  title: string
  items: NewsItem[]
}

const POLL_MS = 20_000
const DEFAULT_TITLE: Record<NewsStyle, string> = {
  modern: 'Channel',
  newspaper: 'The Daily',
  flyer: 'Notice',
}

function timeLabel(iso: string): string {
  if (!iso) return ''
  return iso.slice(0, 16).replace('T', ' ')
}

export function NewsPanel() {
  const { t } = useI18n()
  const [feed, setFeed] = useState<NewsFeed | null>(null)
  const [error, setError] = useState<string | null>(null)

  const reload = useCallback(async () => {
    try {
      const data = await apiGet<NewsFeed>('/play/news')
      setFeed(data)
      setError(null)
    } catch (e) {
      setError((e as Error).message)
    }
  }, [])

  useEffect(() => {
    reload()
    const id = window.setInterval(reload, POLL_MS)
    return () => window.clearInterval(id)
  }, [reload])

  const style: NewsStyle = feed?.style && ['modern', 'newspaper', 'flyer'].includes(feed.style)
    ? feed.style
    : 'modern'
  const title = feed?.title?.trim() || t(DEFAULT_TITLE[style])
  const items = feed?.items || []
  const breaking = items.filter((i) => i.breaking)
  const regular = items.filter((i) => !i.breaking)

  return (
    <div className={`news news--${style}`}>
      <div className="news-masthead">
        <div className="news-title">{title}</div>
        <div className="news-sub">
          {t('Edition')} · {timeLabel(new Date().toISOString())}
        </div>
      </div>

      {error ? <div className="news-empty">error: {error}</div> : null}

      {breaking.length > 0 ? (
        <div className="news-breaking">
          <div className="news-breaking-label">{t('Breaking')}</div>
          {breaking.map((it) => (
            <article key={it.id} className="news-item news-item--breaking">
              <div className="news-item-body">{it.text}</div>
              <div className="news-item-meta">
                <span className="news-cat">{it.category}</span>
                <span className="news-time">{timeLabel(it.created_at)}</span>
              </div>
            </article>
          ))}
        </div>
      ) : null}

      <div className="news-list">
        {!error && items.length === 0 ? (
          <div className="news-empty">{t('No news right now.')}</div>
        ) : null}
        {regular.map((it) => (
          <article key={it.id} className="news-item">
            <div className="news-item-body">{it.text}</div>
            <div className="news-item-meta">
              {it.category ? <span className="news-cat">{it.category}</span> : null}
              {it.global ? <span className="news-scope">{t('world')}</span> : null}
              <span className="news-time">{timeLabel(it.created_at)}</span>
            </div>
          </article>
        ))}
      </div>
    </div>
  )
}
