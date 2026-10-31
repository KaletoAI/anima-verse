/**
 * PromptImprover — the optional "✨ Improve prompt" row of the player image
 * dialogs (gallery/Instagram regenerate, diary-page regenerate, scene photo).
 *
 * With a change wish the LLM rewrites the prompt accordingly; with the wish
 * left empty it only optimises the prompt for the image model (same content).
 * The result replaces the dialog's prompt field, so it stays visible and
 * editable before anything is generated. Same server route as the Game-Admin
 * dialog: POST /world/imagegen-enhance-prompt { prompt, improvement_request? }.
 */
import { useEffect, useRef, useState } from 'react'
import { apiPost } from './api'
import { useI18n } from './I18nProvider'

export function PromptImprover({ prompt, onPrompt, disabled = false, onBusyChange }: {
  prompt: string
  onPrompt: (prompt: string) => void
  disabled?: boolean
  /** Lets the host block its Generate button while the LLM rewrites. */
  onBusyChange?: (busy: boolean) => void
}) {
  const { t } = useI18n()
  const [wish, setWish] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const alive = useRef(true)
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])

  const run = async () => {
    const base = prompt.trim()
    if (!base || busy || disabled) return
    setBusy(true); onBusyChange?.(true); setError('')
    try {
      const res = await apiPost<{ prompt?: string }>('/world/imagegen-enhance-prompt', {
        prompt: base, improvement_request: wish.trim(),
      })
      if (!alive.current) return
      if (res?.prompt) { onPrompt(res.prompt); setWish('') }
    } catch (err) {
      if (alive.current) setError(err instanceof Error ? err.message : t('Prompt improvement failed.'))
    } finally {
      if (alive.current) { setBusy(false); onBusyChange?.(false) }
    }
  }

  return <div className="ga-field" style={{ marginBottom: 10 }}>
    <span className="ga-field-caption">{t('Improvement request')}</span>
    <div style={{ display: 'flex', gap: 6 }}>
      <input className="ga-input" style={{ flex: 1 }} value={wish} disabled={busy || disabled}
        placeholder={t('What to change (optional)')}
        onChange={(e) => setWish(e.target.value)}
        // The player dialogs are forms: Enter here improves, it must not generate.
        onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); void run() } }} />
      <button type="button" className="ga-btn" disabled={busy || disabled || !prompt.trim()}
        title={wish.trim()
          ? t('Rewrite the prompt with this change via LLM')
          : t('Optimise the prompt for the image model via LLM (content stays the same)')}
        onClick={() => { void run() }}>
        {busy ? '…' : `✨ ${t('Improve prompt')}`}
      </button>
    </div>
    {error && <div className="player-photo-hint" role="alert">{error}</div>}
  </div>
}
