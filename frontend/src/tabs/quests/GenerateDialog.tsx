import { useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { Field } from '@anima/player-ui'
import { useI18n } from '../../i18n/I18nProvider'
import { loadCharacters } from '../../lib/refs'
import type { CharacterRef } from '../../lib/refs'
import { generateQuest, questError } from './api'
import { questErrorText } from './questsModel'

const MAX_BRIEF_CHARS = 2000

/**
 * Portal dialog to enqueue an admin LLM quest-authoring job (`POST /quests/generate`). Collects a short brief and an
 * optional in-world giver character; on 202 it hands `task_id` to `onSubmitted` and closes, while any refusal
 * (including 409 `busy`) is shown inline with the dialog kept open.
 */
export function GenerateDialog({
  open, onClose, onSubmitted,
}: {
  open: boolean
  onClose: () => void
  onSubmitted: (taskId: string) => void
}) {
  const { t } = useI18n()
  const [characters, setCharacters] = useState<CharacterRef[]>([])
  const [brief, setBrief] = useState('')
  const [giver, setGiver] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!open) return
    setBrief('')
    setGiver('')
    setError('')
    loadCharacters().then(setCharacters).catch(() => setCharacters([]))
  }, [open])

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  const inWorld = useMemo(
    () => characters.filter((c) => !c.temporary && c.status !== 'dormant' && c.status !== 'pooled'),
    [characters],
  )

  if (!open) return null

  const trimmed = brief.trim()

  const submit = async () => {
    if (!trimmed || busy) return
    setBusy(true)
    setError('')
    try {
      const res = await generateQuest(trimmed, giver)
      onSubmitted(res.task_id)
      onClose()
    } catch (e) {
      setError(questErrorText(questError(e), t))
    } finally {
      setBusy(false)
    }
  }

  return createPortal(
    <div className="ga-modal-backdrop" onClick={onClose}>
      <div className="ga-modal ga-quest-start" role="dialog" aria-label={t('Generate with LLM')}
        onClick={(e) => e.stopPropagation()}>
        <div className="ga-modal-header">
          <span>{t('Generate with LLM')}</span>
          <button type="button" className="ga-modal-close" onClick={onClose}>×</button>
        </div>
        <div className="ga-modal-body ga-form">
          <Field label={t('Brief')}>
            <textarea className="ga-textarea" rows={4} maxLength={MAX_BRIEF_CHARS} value={brief}
              placeholder={t('A short idea, e.g. the innkeeper needs someone to fetch herbs from the forest')}
              onChange={(e) => setBrief(e.target.value)} />
          </Field>
          <Field label={t('Quest giver')}>
            <select className="ga-input" value={giver} onChange={(e) => setGiver(e.target.value)}>
              <option value="">{t('— no giver —')}</option>
              {inWorld.map((c) => <option key={c.name} value={c.name}>{c.display_name || c.name}</option>)}
            </select>
          </Field>
          {error ? (
            <div className="ga-quest-error" role="alert">
              <p>{error}</p>
            </div>
          ) : null}
        </div>
        <div className="ga-modal-footer" style={{ display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
          <button type="button" className="ga-btn ga-btn-sm" onClick={onClose}>{t('Cancel')}</button>
          <button type="button" className="ga-btn ga-btn-sm ga-btn-primary" disabled={!trimmed || busy}
            onClick={() => { void submit() }}>
            {busy ? t('Generating…') : t('Generate')}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  )
}
