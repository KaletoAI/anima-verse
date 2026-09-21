import { useEffect, useMemo, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { Field } from '../../components/Field'

/**
 * Game-Admin "New character" dialog. A real in-app modal (no window.prompt) with
 * a template picker + name field that POSTs to /characters/create. On success it
 * hands the new name back so the list can reload and select it.
 */

interface TemplateRef {
  name: string
  label?: string
}

interface Props {
  /** Existing character names — used for a client-side duplicate hint. */
  existing: string[]
  onClose: () => void
  onCreated: (name: string) => void
}

export function NewCharacterDialog({ existing, onClose, onCreated }: Props) {
  const { t } = useI18n()
  const { toast } = useToast()
  const [templates, setTemplates] = useState<TemplateRef[] | null>(null)
  const [name, setName] = useState('')
  const [template, setTemplate] = useState('')
  const [busy, setBusy] = useState(false)
  // The server's rejection, verbatim. The name rule lives in
  // app/core/character_name.py and nowhere else; this dialog only shows what
  // it says instead of re-implementing it in TypeScript.
  const [error, setError] = useState('')

  useEffect(() => {
    apiGet<{ templates?: TemplateRef[] }>('/templates/list?template_type=character')
      .then((d) => {
        const list = d.templates || []
        setTemplates(list)
        // Prefer a sensible default if present, else the first template.
        const preferred = list.find((x) => x.name === 'human-default') || list[0]
        if (preferred) setTemplate(preferred.name)
      })
      .catch(() => setTemplates([]))
  }, [])

  const trimmed = name.trim()
  const duplicate = useMemo(
    () => existing.some((n) => n.toLowerCase() === trimmed.toLowerCase()),
    [existing, trimmed],
  )
  const canSubmit = !!trimmed && !!template && !duplicate && !busy

  const submit = async () => {
    if (!canSubmit) return
    setBusy(true)
    setError('')
    try {
      await apiPost('/characters/create', { character_name: trimmed, template })
      toast(t('Character created.'), 'success')
      onCreated(trimmed)
    } catch (e) {
      setError((e as Error).message)
      toast(t('Error') + ': ' + (e as Error).message, 'error')
      setBusy(false)
    }
  }

  return (
    <div className="ga-modal-backdrop" onMouseDown={onClose}>
      <div
        className="ga-modal"
        style={{ maxWidth: 440 }}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="ga-modal-header">
          <span>{t('New character')}</span>
          <button className="ga-modal-close" onClick={onClose} disabled={busy}>
            ×
          </button>
        </div>
        <div className="ga-modal-body">
          <Field
            label={t('Name')}
            hint={
              duplicate ? (
                <span className="ga-img-nomatch">
                  {t('A character with this name already exists.')}
                </span>
              ) : error ? (
                <span className="ga-img-nomatch">{error}</span>
              ) : (
                t("Letters, digits, spaces, - ' . _ — up to 60 characters")
              )
            }
          >
            <input
              className="ga-input"
              autoFocus
              value={name}
              maxLength={60}
              placeholder={t('Character name')}
              onChange={(e) => {
                setName(e.target.value)
                setError('')
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter') submit()
              }}
            />
          </Field>
          <Field label={t('Template')}>
            {templates == null ? (
              <div className="ga-loading">{t('Loading…')}</div>
            ) : templates.length === 0 ? (
              <span className="ga-img-nomatch">{t('No templates available.')}</span>
            ) : (
              <select
                className="ga-input"
                value={template}
                onChange={(e) => setTemplate(e.target.value)}
              >
                {templates.map((tpl) => (
                  <option key={tpl.name} value={tpl.name}>
                    {tpl.label || tpl.name}
                  </option>
                ))}
              </select>
            )}
          </Field>
        </div>
        <div className="ga-modal-footer">
          <button className="ga-btn" onClick={onClose} disabled={busy}>
            {t('Cancel')}
          </button>
          <button className="ga-btn ga-btn-primary" onClick={submit} disabled={!canSubmit}>
            {busy ? t('Creating…') : t('Create')}
          </button>
        </div>
      </div>
    </div>
  )
}
