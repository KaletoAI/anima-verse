/**
 * TemplateSelector — Character-Template wählen + wechseln (wie alte UI), oben
 * über der Identität. Wechsel via POST /characters/{name}/switch-template:
 *   mode=diff  → zeigt neue/entfallende Felder (In-App-Bestätigung, kein confirm())
 *   mode=apply → führt die Migration durch (Defaults setzen, alte Felder löschen)
 * Danach `onSwitched()` → Editor neu laden.
 */
import { useCallback, useEffect, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'

interface TmplRef { name: string; label?: string }
interface DiffField { key: string; label?: string; label_de?: string; default?: unknown; current_value?: unknown }
interface DiffResp { old_template: string; new_template: string; added: DiffField[]; removed: DiffField[] }

export function TemplateSelector({
  character,
  templateId,
  onSwitched,
}: {
  character: string
  templateId: string
  onSwitched: () => void
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const [templates, setTemplates] = useState<TmplRef[]>([])
  const [pending, setPending] = useState<DiffResp | null>(null) // Diff wartet auf Bestätigung
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    apiGet<{ templates?: TmplRef[] }>('/templates/list?template_type=character')
      .then((d) => setTemplates(d.templates || []))
      .catch(() => setTemplates([]))
  }, [])

  const apply = useCallback(
    async (newTemplate: string) => {
      setBusy(true)
      try {
        const r = await apiPost<{ added?: unknown[]; removed?: unknown[] }>(
          `/characters/${encodeURIComponent(character)}/switch-template`,
          { new_template: newTemplate, mode: 'apply' },
        )
        const a = (r.added || []).length
        const rm = (r.removed || []).length
        toast(t('Template switched') + (a || rm ? ` (+${a} / -${rm})` : ''))
        setPending(null)
        onSwitched()
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
      } finally {
        setBusy(false)
      }
    },
    [character, t, toast, onSwitched],
  )

  const onSelect = useCallback(
    async (newTemplate: string) => {
      if (!newTemplate || newTemplate === templateId || busy) return
      setBusy(true)
      try {
        const d = await apiPost<DiffResp>(
          `/characters/${encodeURIComponent(character)}/switch-template`,
          { new_template: newTemplate, mode: 'diff' },
        )
        if ((d.added || []).length || (d.removed || []).length) {
          setPending(d) // Bestätigung anzeigen
          setBusy(false)
        } else {
          await apply(newTemplate) // nichts geht verloren → direkt
        }
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
        setBusy(false)
      }
    },
    [character, templateId, busy, apply, t, toast],
  )

  const fieldLabel = (f: DiffField) => f.label || f.key

  return (
    <div className="ga-template-bar">
      <label className="ga-template-bar-label">{t('Template')}</label>
      <select
        className="ga-input"
        style={{ width: 'auto', minWidth: 200 }}
        value={templateId}
        disabled={busy}
        onChange={(e) => onSelect(e.target.value)}
      >
        {templateId && !templates.some((tp) => tp.name === templateId) ? (
          <option value={templateId}>{templateId}</option>
        ) : null}
        {templates.map((tp) => (
          <option key={tp.name} value={tp.name}>
            {tp.label || tp.name}
          </option>
        ))}
      </select>

      {pending ? (
        <div className="ga-template-diff">
          <div className="ga-template-diff-title">
            {t('Switch template')}: {pending.old_template} → {pending.new_template}
          </div>
          {pending.added.length > 0 ? (
            <div>
              <div className="ga-template-diff-head">{t('New fields (filled with default):')}</div>
              {pending.added.map((f) => (
                <div key={f.key} className="ga-template-diff-add">
                  + {fieldLabel(f)}
                  {f.default !== null && f.default !== undefined && f.default !== '' ? ` = ${String(f.default)}` : ''}
                </div>
              ))}
            </div>
          ) : null}
          {pending.removed.length > 0 ? (
            <div>
              <div className="ga-template-diff-head">{t('Removed fields (values are lost!):')}</div>
              {pending.removed.map((f) => (
                <div key={f.key} className="ga-template-diff-rem">
                  − {fieldLabel(f)}
                  {f.current_value ? ` (${String(f.current_value).slice(0, 50)})` : ''}
                </div>
              ))}
            </div>
          ) : null}
          <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
            <button
              type="button"
              className="ga-btn ga-btn-sm ga-btn-primary"
              disabled={busy}
              onClick={() => apply(pending.new_template)}
            >
              {t('Switch')}
            </button>
            <button type="button" className="ga-btn ga-btn-sm" disabled={busy} onClick={() => setPending(null)}>
              {t('Cancel')}
            </button>
          </div>
        </div>
      ) : null}
    </div>
  )
}
