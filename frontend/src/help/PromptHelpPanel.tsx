import { useEffect, useState } from 'react'
import { useHelp } from './HelpContext'
import { useI18n } from '../i18n/I18nProvider'
import { apiPost } from '../lib/api'
import { SidePanelShell, CopyBtn } from './SidePanelShell'

/**
 * Prompt Help side panel: improves an image prompt in place via the
 * "image_prompt" LLM task (Image Prompt Enhancer routing). The result always
 * comes back in English and replaces the prompt field content. Focused admin
 * prompt fields are taken over automatically; "Apply to field" writes the
 * (improved) prompt back into the field it came from.
 */
export function PromptHelpPanel() {
  const { panel, getCapture, captureTick, writeBack } = useHelp()
  const { t } = useI18n()
  const [prompt, setPrompt] = useState('')
  const [wish, setWish] = useState('')
  const [busy, setBusy] = useState(false)
  const [applied, setApplied] = useState(false)
  const [error, setError] = useState('')
  // What the captured field said it renders — travels with the request so a
  // specialised prompt (a seamless tiling texture, say) is not "improved"
  // into an ordinary scene.
  const [context, setContext] = useState('')
  const open = panel === 'prompt'

  // Take over the text of the last focused admin PROMPT field (live while open).
  useEffect(() => {
    if (!open) return
    const c = getCapture()
    if (c && c.isPrompt && c.text.trim()) {
      setPrompt(c.text)
      setContext(c.promptContext || '')
    }
  }, [open, captureTick, getCapture])

  const run = () => {
    const p = prompt.trim()
    if (!p || busy) return
    setBusy(true)
    setError('')
    apiPost<{ prompt: string }>('/admin/assist/prompt-help', {
      prompt: p, request: wish.trim(), context,
    })
      .then((d) => { if (d.prompt) setPrompt(d.prompt) })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false))
  }

  const applyBack = () => {
    if (!prompt.trim() || busy) return
    if (writeBack(prompt)) {
      setError('')
      setApplied(true)
      setTimeout(() => setApplied(false), 1200)
    } else {
      setError(t('The source field is no longer available.'))
    }
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
            rows={18}
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
          rows={5}
          placeholder={t('What should be improved?')}
          value={wish}
          onChange={(e) => setWish(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) run() }}
        />
        <div style={{ display: 'flex', gap: 6 }}>
          <button
            type="button"
            className="ga-btn ga-btn-primary"
            style={{ flex: 1 }}
            onClick={run}
            disabled={busy || !prompt.trim()}
          >
            {busy ? t('Running…') : t('Run')}
          </button>
          <button
            type="button"
            className="ga-btn"
            style={{ flex: 1 }}
            onClick={applyBack}
            disabled={busy || !prompt.trim()}
          >
            {applied ? `✓ ${t('Applied')}` : t('Apply to field')}
          </button>
        </div>
        {error ? <div style={{ color: '#f85149' }}>{error}</div> : null}
      </div>
    </SidePanelShell>
  )
}
