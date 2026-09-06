/**
 * DescriptionSyncPanel — "the description says what really stands here"
 * (plan-furnish-v2.md § 2b B14b, decision E8).
 *
 * The room description is the author's brief AND what the chat and the image
 * prompts read. After a furnishing run the two drift apart in both directions:
 * pieces the description promised were never built, pieces the solver placed
 * are named nowhere. This panel closes that gap — as a BUTTON WITH A PREVIEW,
 * never automatically: the server proposes a text, the admin edits it and only
 * then does Apply store it.
 */
import { useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiPost, apiPut } from '../../lib/api'
import { useToast } from '../../lib/Toast'

interface Props {
  /** The furnish target id — a room id, or the yard's `__ground__@<loc>`. */
  roomId: string
  /** Keeps the editor draft in step with what was just stored: the location
   *  editor holds the room objects and would otherwise write the OLD
   *  description back on its next save. */
  onApplied?: (description: string) => void
}

interface SyncResponse {
  proposal: string
  inventory?: Array<{ name: string; count: number; mount: string }>
}

export function DescriptionSyncPanel({ roomId, onApplied }: Props) {
  const { t, lang } = useI18n()
  const { toast } = useToast()
  const [busy, setBusy] = useState(false)
  const [draft, setDraft] = useState<string | null>(null)
  const [inventory, setInventory] = useState<SyncResponse['inventory']>([])

  const propose = async () => {
    setBusy(true)
    try {
      const data = await apiPost<SyncResponse>(
        `/world/rooms/${encodeURIComponent(roomId)}/description-sync`, { lang })
      setDraft(data.proposal || '')
      setInventory(data.inventory || [])
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setBusy(false)
    }
  }

  const apply = async () => {
    if (!draft || !draft.trim()) return
    setBusy(true)
    try {
      await apiPut(`/world/rooms/${encodeURIComponent(roomId)}/description`,
        { description: draft })
      onApplied?.(draft)
      setDraft(null)
      toast(t('Description saved.'))
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setBusy(false)
    }
  }

  if (draft === null) {
    return (
      <button type="button" className="ga-btn ga-btn-sm" disabled={busy}
        style={{ alignSelf: 'flex-start' }}
        title={t('Asks the LLM for a description that names the pieces really standing here. You read it before anything is stored.')}
        onClick={() => { void propose() }}>
        📝 {busy ? t('Asking the LLM…') : t('Sync description with inventory')}
      </button>
    )
  }

  return (
    <div className="ga-form" style={{ gap: 6, border: '1px solid var(--border, #30363d)',
      borderRadius: 8, padding: 8 }}>
      <div className="ga-form-hint">
        {t('Proposed description — edit it as you like; nothing is stored until you apply it.')}
      </div>
      {inventory && inventory.length ? (
        <div className="ga-hint">
          {t('Based on:')}{' '}
          {inventory.map((i) => `${i.count}× ${i.name}`).join(', ')}
        </div>
      ) : (
        <div className="ga-hint">{t('The room holds nothing yet.')}</div>
      )}
      <textarea className="ga-input" rows={6} style={{ width: '100%' }}
        value={draft} onChange={(e) => setDraft(e.target.value)} />
      <div className="ga-furnish-actions">
        <button type="button" className="ga-btn ga-btn-sm" disabled={busy}
          onClick={() => setDraft(null)}>
          {t('Cancel')}
        </button>
        <button type="button" className="ga-btn ga-btn-sm ga-btn-primary"
          disabled={busy || !draft.trim()} onClick={() => { void apply() }}>
          {t('Apply')}
        </button>
      </div>
    </div>
  )
}
