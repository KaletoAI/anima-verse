/**
 * TemplateSelector — pick and switch the character template; a compact select
 * in the detail toolbar, right-aligned next to the character name. Switching goes through
 * POST /characters/{name}/switch-template:
 *   mode=diff  → shows the fields gained/lost (confirmed in-app, never with a
 *                browser dialog)
 *   mode=apply → runs the migration (set defaults, drop the old fields)
 * Afterwards `onSwitched()` → reload the editor.
 */
import { useCallback, useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
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
  locked = false,
}: {
  character: string
  templateId: string
  onSwitched: () => void
  /** A temporary NPC stays a temporary NPC — switching it to a full
   *  template would grant it wardrobe/memory/… it structurally lacks
   *  (and once did: pieces minted by a mis-templated edit). The server
   *  refuses the switch too; this just removes the offer. */
  locked?: boolean
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

  const current = templates.find((tp) => tp.name === templateId)?.label || templateId

  if (locked) {
    return (
      <span className="ga-input ga-template-inline" style={{ width: 'auto', minWidth: 160, opacity: 0.7 }}
            title={t('Temporary NPCs keep their template — convert is not supported.')}>
        {current}
      </span>
    )
  }

  return (
    <>
      <select
        className="ga-input ga-template-inline"
        style={{ width: 'auto', minWidth: 160 }}
        aria-label={t('Template')}
        title={t('Template')}
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

      {/* The select sits in the toolbar next to the name, where nothing may
          grow: the field diff of a switch is a modal on document.body. */}
      {pending ? createPortal(
        <div className="ga-modal-backdrop" role="presentation">
          <div className="ga-modal" role="dialog" aria-modal="true" aria-label={t('Switch template')}
               style={{ maxWidth: 560 }}>
            <div className="ga-modal-header">
              <h3>{t('Switch template')}: {pending.old_template} → {pending.new_template}</h3>
            </div>
            <div className="ga-modal-body" style={{ fontSize: 13 }}>
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
            </div>
            <div className="ga-modal-footer">
              <button type="button" className="ga-btn" disabled={busy} onClick={() => setPending(null)}>
                {t('Cancel')}
              </button>
              <button type="button" className="ga-btn ga-btn-primary" disabled={busy}
                onClick={() => apply(pending.new_template)}>
                {t('Switch')}
              </button>
            </div>
          </div>
        </div>,
        document.body,
      ) : null}
    </>
  )
}
