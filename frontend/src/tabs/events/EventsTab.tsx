import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiDelete, apiGet, apiPost, apiPut } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { loadLocations, type LocationRef } from '../../lib/refs'

/**
 * Game-Admin "Events" tab — replaces the legacy "Events" drawer of the old UI.
 * Admins post world events (what happened, where, how long, how severe); the
 * Player-UI surfaces them as a news channel. The presentation style of that
 * channel (modern / newspaper / flyer) is also chosen here, per world.
 */

interface WorldEvent {
  id: string
  text: string
  location_id?: string | null
  category?: string
  created_at?: string
  expires_at?: string | null
}

type NewsStyle = 'modern' | 'newspaper' | 'flyer'

const CATEGORIES: Array<{ value: string; label: string }> = [
  { value: '', label: 'Uncategorised' },
  { value: 'ambient', label: 'Ambient' },
  { value: 'social', label: 'Social' },
  { value: 'disruption', label: 'Disruption (breaking)' },
  { value: 'danger', label: 'Danger (breaking)' },
]

const TTL_OPTIONS: Array<{ value: number; label: string }> = [
  { value: 1, label: '1 hour' },
  { value: 6, label: '6 hours' },
  { value: 24, label: '24 hours' },
  { value: 48, label: '2 days' },
  { value: 168, label: '7 days' },
  { value: 0, label: 'Never expires' },
]

const NEWS_STYLES: Array<{ value: NewsStyle; label: string; hint: string }> = [
  { value: 'modern', label: 'Modern media channel', hint: 'Card feed, colour accents — modern worlds.' },
  { value: 'newspaper', label: 'Newspaper', hint: 'Serif masthead + columns — classic worlds.' },
  { value: 'flyer', label: 'Old flyer (b/w)', hint: 'High-contrast black & white notice — low-tech worlds.' },
]

function fmt(iso: string | undefined | null): string {
  if (!iso) return '—'
  return iso.slice(0, 16).replace('T', ' ')
}

export function EventsTab() {
  const { t } = useI18n()
  const { toast } = useToast()
  const [events, setEvents] = useState<WorldEvent[] | null>(null)
  const [locations, setLocations] = useState<LocationRef[]>([])
  const [error, setError] = useState<string | null>(null)

  // create form
  const [text, setText] = useState('')
  const [locationId, setLocationId] = useState('')
  const [category, setCategory] = useState('')
  const [ttl, setTtl] = useState(24)
  const [submitting, setSubmitting] = useState(false)

  // news presentation (world setting)
  const [style, setStyle] = useState<NewsStyle>('modern')
  const [mastheadTitle, setMastheadTitle] = useState('')
  const [styleDirty, setStyleDirty] = useState(false)
  const [savingStyle, setSavingStyle] = useState(false)

  const locName = useCallback(
    (id: string | null | undefined) =>
      !id ? t('All locations (global)') : locations.find((l) => l.id === id)?.name || id,
    [locations, t],
  )

  const reload = useCallback(async () => {
    try {
      const data = await apiGet<{ events: WorldEvent[] }>('/events')
      setEvents(data.events || [])
      setError(null)
    } catch (e) {
      setError((e as Error).message)
    }
  }, [])

  useEffect(() => {
    loadLocations().then(setLocations).catch(() => setLocations([]))
    reload()
    apiGet<{ news?: { style?: string; title?: string } }>('/world/settings')
      .then((s) => {
        const st = (s.news?.style as NewsStyle) || 'modern'
        setStyle(['modern', 'newspaper', 'flyer'].includes(st) ? st : 'modern')
        setMastheadTitle(s.news?.title || '')
      })
      .catch(() => {})
  }, [reload])

  const handleCreate = useCallback(
    async (e: FormEvent) => {
      e.preventDefault()
      if (!text.trim()) {
        toast(t('Event text is required'), 'error')
        return
      }
      setSubmitting(true)
      try {
        await apiPost('/events', {
          text: text.trim(),
          location_id: locationId || null,
          category,
          ttl_hours: ttl,
        })
        setText('')
        setCategory('')
        toast(t('Event created'))
        await reload()
      } catch (err) {
        toast(t('Create failed') + ': ' + (err as Error).message, 'error')
      } finally {
        setSubmitting(false)
      }
    },
    [text, locationId, category, ttl, reload, t, toast],
  )

  const handleDelete = useCallback(
    async (id: string) => {
      try {
        await apiDelete(`/events/${encodeURIComponent(id)}`)
        await reload()
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
      }
    },
    [reload, t, toast],
  )

  const saveStyle = useCallback(async () => {
    setSavingStyle(true)
    try {
      await apiPut('/world/settings', { news: { style, title: mastheadTitle.trim() } })
      setStyleDirty(false)
      toast(t('News style saved'))
    } catch (e) {
      toast(t('Save failed') + ': ' + (e as Error).message, 'error')
    } finally {
      setSavingStyle(false)
    }
  }, [style, mastheadTitle, t, toast])

  return (
    <div className="ga-page-scroll">
      <h2 style={{ fontSize: 16, marginBottom: 6 }}>{t('Events')}</h2>

      <section className="ga-sched-section">
        <h3>{t('News presentation')}</h3>
        <p className="ga-sched-muted">
          {t('How the Player-UI news channel looks. Pick a style that fits the world.')}
        </p>
        <div className="ga-sched-form-row">
          <div className="ga-sched-field" style={{ minWidth: 240 }}>
            <label>{t('Style')}</label>
            <select
              className="ga-input"
              value={style}
              onChange={(e) => {
                setStyle(e.target.value as NewsStyle)
                setStyleDirty(true)
              }}
            >
              {NEWS_STYLES.map((s) => (
                <option key={s.value} value={s.value}>
                  {t(s.label)}
                </option>
              ))}
            </select>
            <span className="ga-sched-muted" style={{ fontSize: 12 }}>
              {t(NEWS_STYLES.find((s) => s.value === style)?.hint || '')}
            </span>
          </div>
          <div className="ga-sched-field" style={{ flex: 1, minWidth: 220 }}>
            <label>{t('Masthead title (optional)')}</label>
            <input
              className="ga-input"
              value={mastheadTitle}
              onChange={(e) => {
                setMastheadTitle(e.target.value)
                setStyleDirty(true)
              }}
              placeholder={t('e.g. The Daily Herald')}
            />
          </div>
          <div style={{ display: 'flex', alignItems: 'flex-end' }}>
            <button
              className="ga-btn ga-btn-primary"
              onClick={saveStyle}
              disabled={!styleDirty || savingStyle}
            >
              {savingStyle ? t('Saving…') : t('Save style')}
            </button>
          </div>
        </div>
      </section>

      <section className="ga-sched-section">
        <h3>{t('Active events')}</h3>
        <table className="ga-sched-table">
          <thead>
            <tr>
              <th>{t('Event')}</th>
              <th>{t('Location')}</th>
              <th>{t('Category')}</th>
              <th>{t('Created')}</th>
              <th>{t('Expires')}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {error ? (
              <tr>
                <td colSpan={6}>error: {error}</td>
              </tr>
            ) : events === null ? (
              <tr>
                <td colSpan={6} className="ga-sched-muted">
                  {t('Loading…')}
                </td>
              </tr>
            ) : events.length === 0 ? (
              <tr>
                <td colSpan={6} className="ga-sched-muted">
                  {t('No events.')}
                </td>
              </tr>
            ) : (
              events.map((e) => {
                const breaking = (e.category || '') === 'danger' || (e.category || '') === 'disruption'
                return (
                  <tr key={e.id}>
                    <td>{e.text}</td>
                    <td>{locName(e.location_id)}</td>
                    <td>
                      {e.category ? (
                        <span className={breaking ? 'ga-tag ga-tag-admin' : 'ga-tag'}>
                          {e.category}
                        </span>
                      ) : (
                        <span className="ga-sched-muted">—</span>
                      )}
                    </td>
                    <td className="ga-sched-muted" style={{ fontSize: 12 }}>{fmt(e.created_at)}</td>
                    <td className="ga-sched-muted" style={{ fontSize: 12 }}>{fmt(e.expires_at)}</td>
                    <td className="ga-or-actions-col">
                      <button
                        className="ga-btn ga-btn-sm ga-btn-danger"
                        onClick={() => handleDelete(e.id)}
                      >
                        {t('Delete')}
                      </button>
                    </td>
                  </tr>
                )
              })
            )}
          </tbody>
        </table>
      </section>

      <section className="ga-sched-section">
        <h3>{t('Post event')}</h3>
        <form className="ga-sched-form" onSubmit={handleCreate}>
          <div className="ga-sched-form-row">
            <div className="ga-sched-field" style={{ flex: 1, minWidth: 320 }}>
              <label>{t('What happened?')}</label>
              <input
                className="ga-input"
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder={t('e.g. A storm rolls in over the harbour')}
                required
              />
            </div>
            <div className="ga-sched-field">
              <label>{t('Location')}</label>
              <select className="ga-input" value={locationId} onChange={(e) => setLocationId(e.target.value)}>
                <option value="">{t('All locations (global)')}</option>
                {locations.map((l) => (
                  <option key={l.id} value={l.id}>
                    {l.name || l.id}
                  </option>
                ))}
              </select>
            </div>
            <div className="ga-sched-field">
              <label>{t('Category')}</label>
              <select className="ga-input" value={category} onChange={(e) => setCategory(e.target.value)}>
                {CATEGORIES.map((c) => (
                  <option key={c.value} value={c.value}>
                    {t(c.label)}
                  </option>
                ))}
              </select>
            </div>
            <div className="ga-sched-field">
              <label>{t('Expiry')}</label>
              <select
                className="ga-input"
                value={ttl}
                onChange={(e) => setTtl(parseInt(e.target.value, 10))}
              >
                {TTL_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {t(o.label)}
                  </option>
                ))}
              </select>
            </div>
            <div style={{ display: 'flex', alignItems: 'flex-end' }}>
              <button type="submit" className="ga-btn ga-btn-primary" disabled={submitting}>
                {submitting ? t('Posting…') : t('Post')}
              </button>
            </div>
          </div>
        </form>
      </section>
    </div>
  )
}
