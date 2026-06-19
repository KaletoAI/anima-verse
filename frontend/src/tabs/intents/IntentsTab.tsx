import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiDelete, apiGet, apiPatch, apiPost } from '../../lib/api'
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
  participants: string[] // additional participants beyond the owner
  priority: number
  triggerKind: TriggerKind
  locationId: string
  runDate: string
  outfitHint: string
  durationMin: number // 0 = never expires
}

const INITIAL_FORM: FormState = {
  title: '',
  description: '',
  owner: '',
  participants: [],
  priority: 3,
  triggerKind: 'standing',
  locationId: '',
  runDate: '',
  outfitHint: '',
  durationMin: 0,
}

const DURATION_OPTIONS: Array<{ value: number; label: string }> = [
  { value: 0, label: 'Never expires' },
  { value: 60, label: '1 hour' },
  { value: 360, label: '6 hours' },
  { value: 1440, label: '1 day' },
  { value: 2880, label: '2 days' },
  { value: 10080, label: '7 days' },
]

function expiresAtLabel(iso: string | undefined): string {
  if (!iso) return ''
  return iso.slice(0, 16).replace('T', ' ')
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
  const [editingId, setEditingId] = useState<string | null>(null)
  // original participant objects of the intent being edited — preserved so an
  // admin edit does not wipe role/progress of participants that stay.
  const [editParticipants, setEditParticipants] = useState<
    Record<string, { role?: string; progress?: unknown[] }>
  >({})

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

  const resetForm = useCallback(() => {
    setEditingId(null)
    setEditParticipants({})
    setForm(INITIAL_FORM)
  }, [])

  const handleEdit = useCallback(
    (it: Intent) => {
      const allParts = Object.keys(it.participants || {})
      const owner = it.owner || allParts[0] || ''
      const extras = allParts.filter((p) => p !== owner)
      const k = (it.trigger?.kind as TriggerKind) || 'standing'
      setEditParticipants(it.participants || {})
      setForm({
        title: it.title || '',
        description: it.description || '',
        owner,
        participants: extras,
        priority: it.priority || 3,
        triggerKind: ['standing', 'now', 'at_location', 'at_time'].includes(k) ? k : 'standing',
        locationId: it.trigger?.location_id || it.location_id || '',
        runDate: it.trigger?.run_date ? it.trigger.run_date.slice(0, 16) : '',
        outfitHint: it.outfit_hint || '',
        // expires_at is absolute; we cannot reverse it to a preset, so keep the
        // existing expiry untouched on edit unless the admin picks a new duration.
        durationMin: 0,
      })
      setEditingId(it.id)
      window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' })
    },
    [],
  )

  const handleSubmit = useCallback(
    async (e: FormEvent) => {
      e.preventDefault()
      if (!form.title.trim()) {
        toast(t('Title is required'), 'error')
        return
      }
      if (!form.owner.trim()) {
        toast(t('Pick an owner'), 'error')
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
      // Build participants dict (owner + extras), preserving role/progress of
      // members that already existed on the edited intent.
      const names = [form.owner.trim(), ...form.participants].filter(
        (n, i, arr) => n && arr.indexOf(n) === i,
      )
      const participants: Record<string, { role?: string; progress?: unknown[] }> = {}
      for (const n of names) {
        participants[n] = editParticipants[n] || { role: '', progress: [] }
      }
      const payload: Record<string, unknown> = {
        title: form.title.trim(),
        description: form.description.trim(),
        owner: form.owner.trim(),
        participants,
        priority: form.priority,
        trigger,
        location_id: form.triggerKind === 'at_location' ? form.locationId : '',
        outfit_hint: form.outfitHint.trim(),
      }
      // Only stamp source on create — editing must not flip a character-owned
      // intent into a human one.
      if (!editingId) payload.source = 'human'
      // expires_at: only set when a duration preset is chosen. 0 = leave as-is
      // on edit / "never" on create.
      if (form.durationMin > 0) {
        payload.expires_at = new Date(Date.now() + form.durationMin * 60_000).toISOString()
      } else if (!editingId) {
        payload.expires_at = ''
      }
      setSubmitting(true)
      try {
        if (editingId) {
          await apiPatch(`/intents/${encodeURIComponent(editingId)}`, payload)
          toast(t('Intent updated'))
        } else {
          await apiPost('/intents', payload)
          toast(t('Intent created'))
        }
        resetForm()
        await reload()
      } catch (err) {
        toast(t('Save failed') + ': ' + (err as Error).message, 'error')
      } finally {
        setSubmitting(false)
      }
    },
    [form, editingId, editParticipants, reload, resetForm, t, toast],
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
              <th>{t('Expires')}</th>
              <th>{t('Status')}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {error ? (
              <tr>
                <td colSpan={8}>error: {error}</td>
              </tr>
            ) : intents === null ? (
              <tr>
                <td colSpan={8} className="ga-sched-muted">
                  {t('Loading…')}
                </td>
              </tr>
            ) : intents.length === 0 ? (
              <tr>
                <td colSpan={8} className="ga-sched-muted">
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
                    <td className="ga-sched-muted" style={{ fontSize: 12 }}>
                      {expiresAtLabel(it.expires_at) || '—'}
                    </td>
                    <td className={active ? 'ga-status-ok' : 'ga-status-paused'}>{t(it.status)}</td>
                    <td className="ga-or-actions-col">
                      <button className="ga-btn ga-btn-sm" onClick={() => handleEdit(it)}>
                        {t('Edit')}
                      </button>{' '}
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
        <h3>{editingId ? t('Edit intent') : t('Create intent')}</h3>
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
            <div className="ga-sched-field">
              <label>{editingId ? t('Expiry (change)') : t('Expiry')}</label>
              <select
                className="ga-input"
                value={form.durationMin}
                onChange={(e) => setForm((f) => ({ ...f, durationMin: parseInt(e.target.value, 10) }))}
              >
                {editingId ? <option value={0}>{t('keep current')}</option> : null}
                {DURATION_OPTIONS.map((d) => (
                  <option key={d.value} value={d.value}>
                    {t(d.label)}
                  </option>
                ))}
              </select>
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
            <div className="ga-sched-field" style={{ minWidth: 220 }}>
              <label>{t('Additional participants (optional)')}</label>
              <select
                className="ga-input"
                multiple
                size={3}
                value={form.participants}
                onChange={(e) =>
                  setForm((f) => ({
                    ...f,
                    participants: Array.from(e.target.selectedOptions, (o) => o.value),
                  }))
                }
              >
                {characters
                  .filter((c) => c.name !== form.owner)
                  .map((c) => (
                    <option key={c.name} value={c.name}>
                      {c.display_name || c.name}
                    </option>
                  ))}
              </select>
            </div>
          </div>
          <div className="ga-sched-form-row">
            <button type="submit" className="ga-btn ga-btn-primary" disabled={submitting}>
              {submitting
                ? t('Saving…')
                : editingId
                  ? t('Save changes')
                  : t('Create')}
            </button>
            {editingId ? (
              <button type="button" className="ga-btn" onClick={resetForm} disabled={submitting}>
                {t('Cancel')}
              </button>
            ) : null}
          </div>
        </form>
      </section>
    </div>
  )
}
