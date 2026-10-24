/** Motion prompt and optional duration; the server chooses the video backend. */
import { useEffect, useRef, useState } from 'react'
import { useI18n } from './I18nProvider'
import type { InstagramAnimateControl } from './InstagramPanel'
import { animatePayload } from './playerDialogPayloads'
import { PlayerDialogFrame } from './PlayerDialogFrame'

export function PlayerAnimateDialog({ ctl }: { ctl: InstagramAnimateControl }) {
  const { t } = useI18n()
  const [prompt, setPrompt] = useState(ctl.prompt)
  const [seconds, setSeconds] = useState('')
  const [suggesting, setSuggesting] = useState(false)
  const [error, setError] = useState('')
  const alive = useRef(true)
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])
  const payload = animatePayload({ prompt, seconds })
  return <PlayerDialogFrame title={ctl.hasVideo ? t('Re-animate') : t('Animate')} action={t('Animate')}
    disabled={!payload} pending={suggesting} onClose={ctl.onClose}
    onSubmit={() => { if (payload) return ctl.onSubmit(payload) }}>
    <label className="ga-field">
      <span className="ga-field-caption">{t('Prompt')}</span>
      <textarea className="ga-input" rows={5} autoFocus value={prompt} onChange={(e) => setPrompt(e.target.value)} />
    </label>
    {!payload && <div className="player-photo-hint">{t('Enter a prompt.')}</div>}
    <button type="button" className="ga-btn" onClick={async () => {
      setSuggesting(true)
      setError('')
      try {
        const suggestion = await ctl.onSuggest({ system_prompt: '', llm_override: '' })
        if (alive.current) setPrompt(suggestion)
      } catch (err) {
        if (alive.current) setError(err instanceof Error ? err.message : t('Suggestion failed.'))
      } finally { if (alive.current) setSuggesting(false) }
    }}>{t('Suggest')}</button>
    {error && <div className="player-photo-hint" role="alert">{error}</div>}
    <label className="ga-field">
      <span className="ga-field-caption">{t('Length in seconds (empty = backend default)')}</span>
      <input type="number" min={1} step={1} className="ga-input" value={seconds} onChange={(e) => setSeconds(e.target.value)} />
    </label>
  </PlayerDialogFrame>
}
