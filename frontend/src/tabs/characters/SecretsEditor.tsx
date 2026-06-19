import { useCallback, useEffect, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiDelete, apiGet, apiPost, apiPut } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { Field } from '../../components/Field'

/**
 * Per-character secrets editor (Characters → Secrets), ported from the legacy
 * editor: a list with edit/delete, an inline create/edit form, and an LLM
 * "Generate" action. Backed by /secrets/{name} (+ /{id}, /generate).
 */

interface Secret {
  id: string
  content: string
  category: string
  severity: number
  related_characters?: string[]
  consequences_if_revealed?: string
  known_by?: string[]
}

const CATEGORIES: Array<{ value: string; label: string }> = [
  { value: 'personal', label: 'Personal' },
  { value: 'relationship', label: 'Relationship' },
  { value: 'location', label: 'Location' },
  { value: 'criminal', label: 'Criminal' },
]
const SEVERITY: Record<number, string> = {
  1: 'Harmless',
  2: 'Embarrassing',
  3: 'Serious',
  4: 'Dangerous',
  5: 'Devastating',
}

interface FormState {
  content: string
  category: string
  severity: number
  related: string
  consequences: string
  knownBy: string
}
const EMPTY_FORM: FormState = {
  content: '',
  category: 'personal',
  severity: 2,
  related: '',
  consequences: '',
  knownBy: '',
}

export function SecretsEditor({ character }: { character: string }) {
  const { t } = useI18n()
  const { toast } = useToast()
  const [secrets, setSecrets] = useState<Secret[]>([])
  const [loading, setLoading] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null) // null = closed, '' = new
  const [form, setForm] = useState<FormState>(EMPTY_FORM)
  const [saving, setSaving] = useState(false)
  const [generating, setGenerating] = useState(false)

  const reload = useCallback(async () => {
    setLoading(true)
    try {
      const d = await apiGet<{ secrets?: Secret[] }>(`/secrets/${encodeURIComponent(character)}`)
      setSecrets(d.secrets || [])
    } catch (e) {
      toast(t('Failed to load') + ': ' + (e as Error).message, 'error')
    } finally {
      setLoading(false)
    }
  }, [character, t, toast])

  useEffect(() => {
    setEditingId(null)
    reload()
  }, [reload])

  const openNew = () => {
    setForm(EMPTY_FORM)
    setEditingId('')
  }
  const openEdit = (s: Secret) => {
    setForm({
      content: s.content || '',
      category: s.category || 'personal',
      severity: s.severity || 2,
      related: (s.related_characters || []).join(', '),
      consequences: s.consequences_if_revealed || '',
      knownBy: (s.known_by || []).join(', '),
    })
    setEditingId(s.id)
  }

  const save = useCallback(async () => {
    if (!form.content.trim()) {
      toast(t('Secret text is required'), 'error')
      return
    }
    const payload = {
      content: form.content.trim(),
      category: form.category,
      severity: form.severity,
      related_characters: form.related.split(',').map((x) => x.trim()).filter(Boolean),
      consequences_if_revealed: form.consequences.trim(),
      known_by: form.knownBy.split(',').map((x) => x.trim()).filter(Boolean),
    }
    setSaving(true)
    try {
      if (editingId) {
        await apiPut(`/secrets/${encodeURIComponent(character)}/${encodeURIComponent(editingId)}`, payload)
      } else {
        await apiPost(`/secrets/${encodeURIComponent(character)}`, payload)
      }
      toast(t('Saved'))
      setEditingId(null)
      await reload()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setSaving(false)
    }
  }, [character, editingId, form, reload, t, toast])

  const remove = useCallback(
    async (s: Secret) => {
      if (!window.confirm(t('Delete this secret?'))) return
      try {
        await apiDelete(`/secrets/${encodeURIComponent(character)}/${encodeURIComponent(s.id)}`)
        await reload()
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
      }
    },
    [character, reload, t, toast],
  )

  const generate = useCallback(async () => {
    setGenerating(true)
    try {
      const d = await apiPost<{ count?: number }>(
        `/secrets/${encodeURIComponent(character)}/generate`,
        { count: 2 },
      )
      toast(t('Generated {n} secrets').replace('{n}', String(d.count ?? 0)))
      await reload()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setGenerating(false)
    }
  }, [character, reload, t, toast])

  return (
    <div className="ga-form">
      <div className="ga-fieldset">
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
          <div className="ga-fieldset-title" style={{ margin: 0 }}>
            {t('Secrets')}
          </div>
          <div style={{ display: 'flex', gap: 6 }}>
            <button
              type="button"
              className="ga-btn ga-btn-sm"
              disabled={generating}
              title={t('LLM generates fitting secrets from profile, relationships and history.')}
              onClick={generate}
            >
              {generating ? t('Generating…') : t('Generate')}
            </button>
            <button type="button" className="ga-btn ga-btn-sm ga-btn-primary" onClick={openNew}>
              {t('+ New secret')}
            </button>
          </div>
        </div>

        {loading ? (
          <div className="ga-loading">{t('Loading…')}</div>
        ) : secrets.length === 0 ? (
          <div className="ga-placeholder">{t('No secrets yet.')}</div>
        ) : (
          <div className="ga-secret-list">
            {secrets.map((s) => {
              const content = s.content || ''
              return (
              <div key={s.id} className="ga-secret-row">
                <div className="ga-secret-info">
                  <strong>{content.length > 90 ? content.slice(0, 90) + '…' : content}</strong>
                  <span className="ga-sched-muted">
                    {t(CATEGORIES.find((c) => c.value === s.category)?.label || s.category)} ·{' '}
                    {t(SEVERITY[s.severity] || String(s.severity))}
                    {(s.known_by || []).length > 0
                      ? ' · ' + t('Known by:') + ' ' + (s.known_by || []).join(', ')
                      : ''}
                  </span>
                  {s.consequences_if_revealed ? (
                    <span className="ga-sched-muted">
                      {t('Consequences:')} {s.consequences_if_revealed}
                    </span>
                  ) : null}
                </div>
                <div className="ga-secret-actions">
                  <button className="ga-btn ga-btn-sm" onClick={() => openEdit(s)}>
                    {t('Edit')}
                  </button>{' '}
                  <button className="ga-btn ga-btn-sm ga-btn-danger" onClick={() => remove(s)}>
                    {t('Delete')}
                  </button>
                </div>
              </div>
              )
            })}
          </div>
        )}
      </div>

      {editingId !== null ? (
        <div className="ga-fieldset">
          <div className="ga-fieldset-title">{editingId ? t('Edit secret') : t('New secret')}</div>
          <Field label={t('Secret text')}>
            <textarea
              className="ga-textarea"
              rows={4}
              value={form.content}
              onChange={(e) => setForm((f) => ({ ...f, content: e.target.value }))}
            />
          </Field>
          <div className="ga-form-row">
            <Field label={t('Category')}>
              <select
                className="ga-input"
                value={form.category}
                onChange={(e) => setForm((f) => ({ ...f, category: e.target.value }))}
              >
                {CATEGORIES.map((c) => (
                  <option key={c.value} value={c.value}>
                    {t(c.label)}
                  </option>
                ))}
              </select>
            </Field>
            <Field label={t('Severity')}>
              <select
                className="ga-input"
                value={String(form.severity)}
                onChange={(e) => setForm((f) => ({ ...f, severity: parseInt(e.target.value, 10) }))}
              >
                {[1, 2, 3, 4, 5].map((n) => (
                  <option key={n} value={n}>
                    {n} — {t(SEVERITY[n])}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          <div className="ga-form-row">
            <Field label={t('Related characters')} hint={t('Comma-separated.')}>
              <input
                className="ga-input"
                value={form.related}
                onChange={(e) => setForm((f) => ({ ...f, related: e.target.value }))}
              />
            </Field>
            <Field label={t('Known by')} hint={t('Comma-separated.')}>
              <input
                className="ga-input"
                value={form.knownBy}
                onChange={(e) => setForm((f) => ({ ...f, knownBy: e.target.value }))}
              />
            </Field>
          </div>
          <Field label={t('Consequences if revealed')}>
            <input
              className="ga-input"
              value={form.consequences}
              onChange={(e) => setForm((f) => ({ ...f, consequences: e.target.value }))}
            />
          </Field>
          <div className="ga-form-row" style={{ marginTop: 6, gap: 8 }}>
            <button
              type="button"
              className="ga-btn ga-btn-sm ga-btn-primary"
              disabled={saving}
              onClick={save}
            >
              {saving ? t('Saving…') : t('Save')}
            </button>
            <button type="button" className="ga-btn ga-btn-sm" onClick={() => setEditingId(null)}>
              {t('Cancel')}
            </button>
          </div>
        </div>
      ) : null}
    </div>
  )
}
