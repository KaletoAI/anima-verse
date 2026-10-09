import { useCallback, useEffect, useState } from 'react'
import { Field } from '../../components/Field'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { Origin, type SchemaProps } from './SchemaNode'
import { getAt, setAt, type Json } from './schemaValues'

export type UseCaseDefaults = {
  use_cases: string[]
  families: string[]
  defaults: Record<string, Record<string, Record<string, string>>>
}
export function UseCaseStyles({ defaults, values, overrides, onChange, onReset }: {
  defaults: UseCaseDefaults
  values: Json
} & Pick<SchemaProps, 'overrides' | 'onChange' | 'onReset'>) {
  const { t } = useI18n()
  const { toast } = useToast()
  const raw = getAt(values, 'image_generation.use_cases')
  const cases = [...new Set([...defaults.use_cases, ...Object.keys(raw && typeof raw === 'object' && !Array.isArray(raw) ? raw : {})])]
  const [selected, setSelected] = useState('')
  const current = cases.includes(selected) ? selected : cases[0]
  const [cacheSize, setCacheSize] = useState<number | null>(null)
  const [clearing, setClearing] = useState(false)
  const loadCache = useCallback(async () => {
    try { setCacheSize((await apiGet<{ entries: number }>('/world/compose-cache')).entries) }
    catch (error) { toast(t('Error') + ': ' + (error as Error).message, 'error') }
  }, [t, toast])
  useEffect(() => { void loadCache() }, [loadCache])
  const change = (path: string, value: Json) => onChange(path, setAt(values, path, value))
  const path = `image_generation.use_cases.${current}`
  return <div className="ga-setup-styles">
    <nav className="ga-list ga-setup-style-list" aria-label={t('Image styles')}>
      {cases.map(uc => <button key={uc} type="button" aria-pressed={uc === current} className={`ga-list-row${uc === current ? ' is-active' : ''}`}
        onClick={() => setSelected(uc)}>{uc}</button>)}
    </nav>
    <div className="ga-form ga-setup-style-detail">
      <div className="ga-form-row">
        <button type="button" className="ga-btn ga-btn-sm" disabled={clearing} onClick={async () => {
          setClearing(true)
          try { await apiPost('/world/compose-cache/clear', {}); await loadCache() }
          catch (error) { toast(t('Error') + ': ' + (error as Error).message, 'error') }
          finally { setClearing(false) }
        }}>{t('Clear compose cache')}</button>
        {cacheSize !== null && <span className="ga-form-hint">{cacheSize} {t('cached prompts')}</span>}
      </div>
      {current && <>
        <div className="ga-setup-section-head"><h3 className="ga-setup-heading">{current}</h3><Origin path={path} overrides={overrides} onReset={onReset} /></div>
        <Field label={t('Compose via LLM (opt-in)')}>
          <input type="checkbox" aria-label={t('Compose via LLM (opt-in)')} checked={Boolean(getAt(values, `${path}.llm_compose`))}
            onChange={event => change(`${path}.llm_compose`, event.target.checked)} />
        </Field>
        {defaults.families.map(family => <section key={family} className="ga-fieldset ga-setup-fields">
          <h4 className="ga-fieldset-title">{family}</h4>
          {(['prompt_style', 'prompt_negative', 'prompt_instruction'] as const).map(key => {
            const fieldPath = `${path}.styles.${family}.${key}`
            const value = String(getAt(values, fieldPath) ?? '')
            const placeholder = defaults.defaults[current]?.[family]?.[key] ?? ''
            return <div className="ga-setup-field" key={key}><Field label={key === 'prompt_style' ? t('Style') : key === 'prompt_negative' ? t('Negative') : t('Instruction')}>
              <textarea className="ga-textarea" rows={3} value={value} placeholder={placeholder}
                onChange={event => change(fieldPath, event.target.value)} />
              {!value && placeholder && <button type="button" className="ga-btn ga-btn-sm" onClick={() => change(fieldPath, placeholder)}>{t('Copy default')}</button>}
            </Field></div>
          })}
        </section>)}
      </>}
    </div>
  </div>
}
