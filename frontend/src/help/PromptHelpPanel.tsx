import { useState } from 'react'
import { useI18n } from '../i18n/I18nProvider'
import { apiPost } from '../lib/api'
import { SidePanelShell, CopyBtn } from './SidePanelShell'

/**
 * Prompt Help side panel: improves an image prompt in place via the
 * "image_prompt" LLM task (Image Prompt Enhancer routing). The result always
 * comes back in English and replaces the prompt field content.
 */
export function PromptHelpPanel() {
  const { t } = useI18n()
  const [prompt, setPrompt] = useState('')
  const [wish, setWish] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const run = () => {
    const p = prompt.trim()
    if (!p || busy) return
    setBusy(true)
    setError('')
    apiPost<{ prompt: string }>('/admin/assist/prompt-help', {
      prompt: p, request: wish.trim(),
    })
      .then((d) => { if (d.prompt) setPrompt(d.prompt) })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false))
  }

  return (
    <SidePanelShell id="prompt" title={t('Prompt Help')}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        <div style={{ opacity: 0.7 }}>
          {t('Improves the prompt in place and always returns English.')}
        </div>
        <div style={{ position: 'relative' }}>
          <textarea
            className="ga-textarea"
            rows={9}
            placeholder={t('Prompt…')}
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            disabled={busy}
          />
          {prompt ? (
            <span style={{ position: 'absolute', top: 6, right: 8 }}>
              <CopyBtn value={prompt} />
            </span>
          ) : null}
        </div>
        <textarea
          className="ga-textarea"
          rows={3}
          placeholder={t('What should be improved?')}
          value={wish}
          onChange={(e) => setWish(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) run() }}
        />
        <button
          type="button"
          className="ga-btn ga-btn-primary"
          onClick={run}
          disabled={busy || !prompt.trim()}
        >
          {busy ? t('Running…') : t('Run')}
        </button>
        {error ? <div style={{ color: '#f85149' }}>{error}</div> : null}
      </div>
    </SidePanelShell>
  )
}
