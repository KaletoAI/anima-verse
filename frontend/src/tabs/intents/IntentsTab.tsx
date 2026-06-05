import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiDelete, apiGet, apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { loadCharacters, loadLocations, type CharacterRef, type LocationRef } from '../../lib/refs'

/**
 * Game-Admin "Intents" tab — the unified "Vorhaben & Aufgaben" store
 * (plan-intents-unified.md). Replaces the legacy assignments panel:
 * human-set tasks and character-owned intents live in one place. Admins
 * create/cancel/complete here; characters create their own via [INTENT:]
 * markers and retrospect goals.
 */

interface Intent {
  id: string
  source: 'human' | 'character'
  owner: string
  participants: Record<string, { role?: string; progress?: unknown[] }>
  title: string
  description: string
  trigger: { kind?: string; location_id?: string; run_date?: string }
  priority: number
  status: string
  location_id?: string
  outfit_hint?: string
  expires_at?: string
}

type TriggerKind = 'standing' | 'now' | 'at_location' | 'at_time'

interface FormState {
  title: string
  description: string
  owner: string
  priority: number
  triggerKind: TriggerKind
  locationId: string
  runDate: string
  outfitHint: string
}

const INITIAL_FORM: FormState = {
  title: '',
  description: '',
  owner: '',
  priority: 3,
  triggerKind: 'standing',
  locationId: '',
  runDate: '',
  outfitHint: '',
}

const PRIORITY_LABELS: Record<number, string> = {
  1: 'Critical',
  2: 'High',
  3: 'Normal',
  4: 'Low',
  5: 'Idle',
}

const POLL_INTERVAL_MS = 15_000

function triggerSummary(it: Intent, locName: (id: string) => string): string {
  const k = it.trigger?.kind || 'standing'
  if (k === 'at_location') return `@ ${locName(it.trigger?.location_id || it.location_id || '')}`
  if (k === 'at_time') return `⏰ ${(it.trigger?.run_date || '').slice(0, 16).replace('T', ' ')}`
  if (k === 'now') return 'now'
  return 'standing'
}

export function IntentsTab() {
  const { t } = useI18n()
  const { toast } = useToast()
  const [intents, setIntents] = useState<Intent[] | null>(null)
  const [characters, setCharacters] = useState<CharacterRef[]>([])
  const [locations, setLocations] = useState<LocationRef[]>([])
  const [showAll, setShowAll] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [form, setForm] = useState<FormState>(INITIAL_FORM)
  const [submitting, setSubmitting] = useState(false)

  const locName = useCallback(
    (id: string) => locations.find((l) => l.id === id)?.name || id || '—',
    [locations],
  )

  const reload = useCallback(async () => {
    try {
      const data = await apiGet<Intent[]>(`/intents${showAll ? '' : '?status=active'}`)
      setIntents(data || [])
      setError(null)
    } catch (e) {
      setError((e as Error).message)
    }
  }, [showAll])

  useEffect(() => {
    loadCharacters().then(setCharacters).catch(() => setCharacters([]))
    loadLocations().then(setLocations).catch(() => setLocations([]))
  }, [])

  useEffect(() => {
    reload()
    const id = window.setInterval(reload, POLL_INTERVAL_MS)
    return () => window.clearInterval(id)
  }, [reload])

  const handleSubmit = useCallback(
    async (e: FormEvent) => {
      e.preventDefault()
      if (!form.title.trim()) {
        toast(t('Title is required'), 'error')
        return
      }
      const trigger: Record<string, unknown> = { kind: form.triggerKind }
      if (form.triggerKind === 'at_location') {
        if (!form.locationId) {
          toast(t('Pick a location'), 'error')
          return
        }
        trigger.location_id = form.locationId
      }
      if (form.triggerKind === 'at_time') {
        if (!form.runDate) {
          toast(t('Pick a date/time'), 'error')
          return
        }
        trigger.run_date = new Date(form.runDate).toISOString()
      }
      setSubmitting(true)
      try {
        await apiPost('/intents', {
          title: form.title.trim(),
          description: form.description.trim(),
          owner: form.owner.trim(),
          source: 'human',
          priority: form.priority,
          trigger,
          location_id: form.triggerKind === 'at_location' ? form.locationId : '',
          outfit_hint: form.outfitHint.trim(),
        })
        setForm({ ...INITIAL_FORM, owner: form.owner, triggerKind: form.triggerKind })
        toast(t('Intent created'))
        await reload()
      } catch (err) {
        toast(t('Create failed') + ': ' + (err as Error).message, 'error')
      } finally {
        setSubmitting(false)
      }
    },
    [form, reload, t, toast],
  )

  const handleComplete = useCallback(
    async (id: string) => {
      try {
        await apiPost(`/intents/${encodeURIComponent(id)}/complete`, {})
        await reload()
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
      }
    },
    [reload, t, toast],
  )

  const handleDelete = useCallback(
    async (id: string, title: string) => {
      if (!window.confirm(t('Delete intent "{x}"?').replace('{x}', title))) return
      try {
        await apiDelete(`/intents/${encodeURIComponent(id)}`)
        await reload()
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
      }
    },
    [reload, t, toast],
  )

  return (
    <div className="ga-page-scroll">
      <h2 style={{ fontSize: 16, marginBottom: 6 }}>{t('Intents — Plans & Tasks')}</h2>

      <section className="ga-sched-section">
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <h3 style={{ margin: 0 }}>{t('All intents')}</h3>
          <label className="ga-sched-muted" style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} />
            {t('show inactive too')}
          </label>
        </div>
        <p className="ga-sched-muted">
          {t(
            'One store for human-assigned tasks and character-owned plans. Characters create their own via reflection and in-chat decisions; admins can add, complete or remove any intent here.',
          )}
        </p>
        <table className="ga-sched-table">
          <thead>
            <tr>
              <th>{t('Title')}</th>
              <th>{t('Owner')}</th>
              <th>{t('Source')}</th>
              <th>{t('Trigger')}</th>
              <th>{t('Priority')}</th>
              <th>{t('Status')}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {error ? (
              <tr>
                <td colSpan={7}>error: {error}</td>
              </tr>
            ) : intents === null ? (
              <tr>
                <td colSpan={7} className="ga-sched-muted">
                  {t('Loading…')}
                </td>
              </tr>
            ) : intents.length === 0 ? (
              <tr>
                <td colSpan={7} className="ga-sched-muted">
                  {t('No intents yet.')}
                </td>
              </tr>
            ) : (
              intents.map((it) => {
                const active = it.status === 'active'
                const parts = Object.keys(it.participants || {})
                const owner = it.owner || parts[0] || '—'
                return (
                  <tr key={it.id}>
                    <td>
                      <div>{it.title}</div>
                      {it.description ? (
                        <div className="ga-sched-muted" style={{ fontSize: 12 }}>
                          {it.description}
                        </div>
                      ) : null}
                    </td>
                    <td>
                      <span className="ga-tag ga-tag-char">{owner}</span>
                      {parts.length > 1 ? (
                        <span className="ga-sched-muted"> +{parts.length - 1}</span>
                      ) : null}
                    </td>
                    <td>
                      <span className={it.source === 'human' ? 'ga-tag ga-tag-admin' : 'ga-tag'}>
                        {it.source}
                      </span>
                    </td>
                    <td>{triggerSummary(it, locName)}</td>
                    <td>{t(PRIORITY_LABELS[it.priority] || 'Normal')}</td>
                    <td className={active ? 'ga-status-ok' : 'ga-status-paused'}>{t(it.status)}</td>
                    <td className="ga-or-actions-col">
                      {active ? (
                        <button className="ga-btn ga-btn-sm" onClick={() => handleComplete(it.id)}>
                          {t('Complete')}
                        </button>
                      ) : null}{' '}
                      <button
                        className="ga-btn ga-btn-sm ga-btn-danger"
                        onClick={() => handleDelete(it.id, it.title)}
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
        <h3>{t('Create intent')}</h3>
        <form className="ga-sched-form" onSubmit={handleSubmit}>
          <div className="ga-sched-form-row">
            <div className="ga-sched-field" style={{ flex: 1, minWidth: 220 }}>
              <label>{t('Title')}</label>
              <input
                className="ga-input"
                value={form.title}
                onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}
                placeholder={t('e.g. Photoshoot in the park')}
                required
              />
            </div>
            <div className="ga-sched-field">
              <label>{t('Owner')}</label>
              <select
                className="ga-input"
                value={form.owner}
                onChange={(e) => setForm((f) => ({ ...f, owner: e.target.value }))}
                required
              >
                <option value="">{t('— pick character —')}</option>
                {characters.map((c) => (
                  <option key={c.name} value={c.name}>
                    {c.display_name || c.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="ga-sched-field">
              <label>{t('Priority')}</label>
              <select
                className="ga-input"
                value={form.priority}
                onChange={(e) => setForm((f) => ({ ...f, priority: parseInt(e.target.value, 10) }))}
              >
                {[1, 2, 3, 4, 5].map((p) => (
                  <option key={p} value={p}>
                    {p} — {t(PRIORITY_LABELS[p])}
                  </option>
                ))}
              </select>
            </div>
            <div className="ga-sched-field">
              <label>{t('Trigger')}</label>
              <select
                className="ga-input"
                value={form.triggerKind}
                onChange={(e) => setForm((f) => ({ ...f, triggerKind: e.target.value as TriggerKind }))}
              >
                <option value="standing">{t('standing (ongoing)')}</option>
                <option value="now">{t('now (bump immediately)')}</option>
                <option value="at_location">{t('on entering a location')}</option>
                <option value="at_time">{t('at a date/time')}</option>
              </select>
            </div>
            {form.triggerKind === 'at_location' ? (
              <div className="ga-sched-field">
                <label>{t('Location')}</label>
                <select
                  className="ga-input"
                  value={form.locationId}
                  onChange={(e) => setForm((f) => ({ ...f, locationId: e.target.value }))}
                >
                  <option value="">{t('— pick location —')}</option>
                  {locations.map((l) => (
                    <option key={l.id} value={l.id}>
                      {l.name || l.id}
                    </option>
                  ))}
                </select>
              </div>
            ) : null}
            {form.triggerKind === 'at_time' ? (
              <div className="ga-sched-field">
                <label>{t('Date/time')}</label>
                <input
                  type="datetime-local"
                  className="ga-input"
                  value={form.runDate}
                  onChange={(e) => setForm((f) => ({ ...f, runDate: e.target.value }))}
                />
              </div>
            ) : null}
            <div className="ga-sched-field">
              <label>{t('Outfit hint (optional)')}</label>
              <input
                className="ga-input"
                value={form.outfitHint}
                onChange={(e) => setForm((f) => ({ ...f, outfitHint: e.target.value }))}
              />
            </div>
          </div>
          <div className="ga-sched-form-row">
            <div className="ga-sched-field" style={{ flex: 1, minWidth: 320 }}>
              <label>{t('Description (optional)')}</label>
              <input
                className="ga-input"
                value={form.description}
                onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
                placeholder={t('What should happen?')}
              />
            </div>
            <div style={{ display: 'flex', alignItems: 'flex-end' }}>
              <button type="submit" className="ga-btn ga-btn-primary" disabled={submitting}>
                {submitting ? t('Creating…') : t('Create')}
              </button>
            </div>
          </div>
        </form>
      </section>
    </div>
  )
}
