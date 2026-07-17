import { useEffect, useState } from 'react'
import { useHelp } from './HelpContext'
import { useI18n } from '../i18n/I18nProvider'
import { apiGet, apiPost } from '../lib/api'
import { SidePanelShell, CopyBtn } from './SidePanelShell'

interface LangOpt { value: string; label: string; label_de?: string }

/**
 * Translate side panel: free-text translation via the "translation" LLM task
 * (Small Helper Model routing). Language list comes from /i18n/languages —
 * the same single source the rest of the app uses.
 */
export function TranslatePanel() {
  const { panel } = useHelp()
  const { t, lang } = useI18n()
  const [langs, setLangs] = useState<LangOpt[]>([])
  const [source, setSource] = useState('')
  const [target, setTarget] = useState(lang === 'en' ? 'de' : 'en')
  const [input, setInput] = useState('')
  const [output, setOutput] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const open = panel === 'translate'

  useEffect(() => {
    if (!open || langs.length) return
    apiGet<{ languages?: LangOpt[] }>('/i18n/languages')
      .then((d) => setLangs(d.languages || []))
      .catch(() => setLangs([{ value: 'en', label: 'English' }, { value: 'de', label: 'German', label_de: 'Deutsch' }]))
  }, [open, langs])

  const langLabel = (l: LangOpt) => (lang === 'de' && l.label_de ? l.label_de : l.label)

  const run = () => {
    const text = input.trim()
    if (!text || busy) return
    setBusy(true)
    setError('')
    apiPost<{ text: string }>('/admin/assist/translate', {
      text, source_lang: source, target_lang: target,
    })
      .then((d) => setOutput(d.text || ''))
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false))
  }

  return (
    <SidePanelShell id="translate" title={t('Translate')}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          <select
            className="ga-input"
            value={source}
            onChange={(e) => setSource(e.target.value)}
            title={t('Source language')}
            aria-label={t('Source language')}
          >
            <option value="">{t('Auto-detect')}</option>
            {langs.map((l) => <option key={l.value} value={l.value}>{langLabel(l)}</option>)}
          </select>
          <span style={{ opacity: 0.6 }}>→</span>
          <select
            className="ga-input"
            value={target}
            onChange={(e) => setTarget(e.target.value)}
            title={t('Target language')}
            aria-label={t('Target language')}
          >
            {langs.map((l) => <option key={l.value} value={l.value}>{langLabel(l)}</option>)}
          </select>
        </div>
        <textarea
          className="ga-textarea"
          rows={7}
          placeholder={t('Text to translate…')}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) run() }}
        />
        <button
          type="button"
          className="ga-btn ga-btn-primary"
          onClick={run}
          disabled={busy || !input.trim()}
        >
          {busy ? t('Translating…') : t('Translate')}
        </button>
        {error ? <div style={{ color: '#f85149' }}>{error}</div> : null}
        <div style={{ position: 'relative' }}>
          <textarea
            className="ga-textarea"
            rows={7}
            readOnly
            placeholder={t('Translation…')}
            value={output}
          />
          {output ? (
            <span style={{ position: 'absolute', top: 6, right: 8 }}>
              <CopyBtn value={output} />
            </span>
          ) : null}
        </div>
      </div>
    </SidePanelShell>
  )
}
