import { useEffect, useMemo, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet } from '../../lib/api'
import { ModelPicker, type PickerOption } from '../../components/ModelPicker'
import { usePersistentState } from '../../lib/usePersistentState'
import { FreeModePanel } from './FreeModePanel'

/**
 * World Dev — the free mode only (plan
 * docs/superpowers/plans/2026-11-25-world-dev-free-remove-schema-modes.md).
 * A model gets a plain-language task and builds it directly in the paused
 * world through the journaled tools; the run is accepted or discarded as a
 * whole. This tab is the shell around `FreeModePanel`: the model picker, the
 * Effort select and the per-reply budget.
 */

interface ModelEntry {
  name: string
  provider?: string
  /** Per 1M tokens, in USD. Local / unpriced models leave these at 0. */
  pricing?: { input?: number; output?: number }
}

// Effort levels of the Anthropic Messages API (output_config.effort).
const EFFORT_LEVELS = ['low', 'medium', 'high', 'xhigh', 'max']
// Completion budgets offered next to the model picker; 128000 is the
// largest output Claude models accept on the synchronous Messages API.
const BUDGET_STEPS = [4096, 8192, 16384, 32768, 65536, 128000]

export function WorldDevTab() {
  const { t } = useI18n()
  const [models, setModels] = useState<ModelEntry[]>([])
  // Flat, provider-grouped options with a price sublabel — fed to the
  // searchable ModelPicker.
  const modelOptions: PickerOption[] = useMemo(() => {
    const fmt = (v: number) =>
      v >= 1 ? v.toFixed(2) : v.toFixed(2).replace(/\.?0+$/, '') || v.toFixed(2)
    return [...models]
      .sort((a, b) => (a.provider || '').localeCompare(b.provider || '')
        || a.name.localeCompare(b.name))
      .map((m) => {
        const inP = m.pricing?.input || 0
        const outP = m.pricing?.output || 0
        const sub = (inP > 0 || outP > 0) ? `$${fmt(inP)} / $${fmt(outP)} per 1M` : ''
        return { value: `${m.provider || ''}|${m.name}`, label: m.name,
                 group: m.provider || '', sublabel: sub }
      })
  }, [models])
  // sessionStorage-backed so the picks survive a Game-Admin tab switch
  // (which unmounts this component) and a page reload.
  const [model, setModel] = usePersistentState('worlddev.model', '')
  const [provider, setProvider] = usePersistentState('worlddev.provider', '')
  // Per-reply completion budget. Empty = auto (the routing entry's value,
  // else 64k for a Claude model, else the provider default). A stored '0'
  // from the removed 'none' option shows and acts as auto.
  const [maxTokens, setMaxTokens] = usePersistentState('worlddev.maxTokens', '')
  // Thinking depth for Claude models (output_config.effort); '' = model default.
  const [effort, setEffort] = usePersistentState('worlddev.effort', '')

  useEffect(() => {
    apiGet<{ providers?: Record<string, { models?: ModelEntry[] }> }>('/characters/available-models')
      .then((d) => {
        const flat: ModelEntry[] = []
        for (const [provName, prov] of Object.entries(d.providers || {})) {
          for (const m of prov.models || []) {
            flat.push({ name: m.name, provider: provName, pricing: m.pricing })
          }
        }
        setModels(flat)
      })
      .catch(() => setModels([]))
  }, [])

  return (
    <div className="ga-wd-shell">
      <div className="ga-wd-config">
        <div className="ga-wd-config-row">
          <ModelPicker
            className="ga-wd-model-select"
            options={modelOptions}
            value={model ? `${provider}|${model}` : ''}
            emptyLabel={t('Pick model')}
            placeholder={t('Pick model')}
            onChange={(v) => {
              if (!v) { setModel(''); setProvider(''); return }
              const [prov, name] = v.split('|', 2)
              setProvider(prov || ''); setModel(name || '')
            }}
          />
          <select
            className="ga-input ga-wd-compact-select"
            value={effort}
            title={t('Effort: how deeply a Claude model thinks before answering. Its thinking comes out of the token budget next to this. Other providers ignore it. Default = the model\'s own level.')}
            onChange={(e) => setEffort(e.target.value)}
          >
            <option value="">{t('Effort: default')}</option>
            {EFFORT_LEVELS.map((lv) => (
              <option key={lv} value={lv}>{t('Effort: {level}').replace('{level}', lv)}</option>
            ))}
          </select>
          <select
            className="ga-input ga-wd-compact-select"
            value={maxTokens === '0' ? '' : maxTokens}
            title={t('Token budget (max_tokens) per reply: thinking plus reply. Auto = the model\'s LLM-Routing max_tokens, else 64k for a Claude model, else the provider\'s default.')}
            onChange={(e) => setMaxTokens(e.target.value)}
          >
            <option value="">{t('Budget: auto')}</option>
            {BUDGET_STEPS.map((n) => (
              <option key={n} value={String(n)}>{t('Budget: {size}').replace('{size}', `${Math.round(n / 1024)}k`)}</option>
            ))}
            {maxTokens.trim() && maxTokens !== '0' && !BUDGET_STEPS.includes(parseInt(maxTokens, 10)) && (
              <option value={maxTokens}>{t('Budget: {size}').replace('{size}', maxTokens)}</option>
            )}
          </select>
        </div>
      </div>

      <FreeModePanel model={model} provider={provider} maxTokens={maxTokens} effort={effort} />
    </div>
  )
}
