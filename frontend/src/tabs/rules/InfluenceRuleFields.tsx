import { useEffect, useState } from 'react'
import { Field } from '@anima/player-ui'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPost } from '../../lib/api'
import type { CharacterRef } from '../../lib/refs'

export interface Influence {
  actor: string
  recipient: string
  stat: string
  direction: 'increase' | 'decrease' | 'both'
  factor: number
}

export interface PairCondition {
  kind: string
  op?: string
  value?: number
  observer?: string
}

interface InfluenceOptions {
  stats: { key: string; label: string }[]
  pair_conditions: { kind: string; available: boolean; reason: string }[]
  directions: Influence['direction'][]
  factor_min: number
  factor_max: number
}

export interface InfluenceDiagnostic { path: string; code: string; message: string }
export interface InfluenceValidation {
  errors: InfluenceDiagnostic[]
  warnings: InfluenceDiagnostic[]
  available: boolean
}

export function InfluenceRuleFields({ influence, actorCondition, pairConditions, characters, rule,
  onInfluence, onActorCondition, onPairConditions }: {
  influence: Influence
  actorCondition: string
  pairConditions: PairCondition[]
  characters: CharacterRef[]
  rule: object
  onInfluence: (value: Influence) => void
  onActorCondition: (value: string) => void
  onPairConditions: (value: PairCondition[]) => void
}) {
  const { t } = useI18n()
  const [options, setOptions] = useState<InfluenceOptions | null>(null)
  const [optionsError, setOptionsError] = useState('')
  const [diagnostics, setDiagnostics] = useState<InfluenceValidation | null>(null)
  const [validationError, setValidationError] = useState('')
  const [validating, setValidating] = useState(false)
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    let alive = true
    setOptionsError('')
    apiGet<InfluenceOptions>('/rules/influence-options')
      .then(value => { if (alive) setOptions(value) })
      .catch(error => { if (alive) setOptionsError((error as Error).message) })
    return () => { alive = false }
  }, [attempt])
  useEffect(() => {
    let alive = true
    setDiagnostics(null)
    setValidationError('')
    setValidating(true)
    const timer = window.setTimeout(() => {
      apiPost<InfluenceValidation>('/rules/influence-validate', { rule })
        .then(value => { if (alive) setDiagnostics(value) })
        .catch(error => { if (alive) setValidationError((error as Error).message) })
        .finally(() => { if (alive) setValidating(false) })
    }, 300)
    return () => { alive = false; window.clearTimeout(timer) }
  }, [rule, attempt])
  const changePair = (index: number, value: PairCondition) =>
    onPairConditions(pairConditions.map((pair, i) => i === index ? value : pair))
  return <>
    <p className="ga-hint">{t('Influence creates no base effect. Conditions only gate the multiplier. Matching factors multiply; the effective product is limited to 0.1–5.')}</p>
    <div className="ga-form-row">
      {(['actor', 'recipient'] as const).map(role => <Field key={role} label={role === 'actor' ? t('Actor') : t('Recipient')}>
        <select className="ga-input" name={`influence-${role}`} aria-label={role === 'actor' ? t('Actor') : t('Recipient')} value={influence[role]}
          onChange={event => onInfluence({ ...influence, [role]: event.target.value })}>
          <option value="">{t('Any character')}</option>
          {influence[role] && !characters.some(character => character.name === influence[role]) ?
            <option value={influence[role]}>{t('Missing reference: {value}').replace('{value}', influence[role])}</option> : null}
          {characters.map(character => <option key={character.name} value={character.name}>{character.display_name || character.name}</option>)}
        </select>
      </Field>)}
    </div>
    <div className="ga-form-row">
      <Field label={t('Stat')}>
        <select className="ga-input" name="influence-stat" aria-label={t('Stat')} value={influence.stat}
          onChange={event => onInfluence({ ...influence, stat: event.target.value })}>
          <option value="">— {t('select')} —</option>
          {influence.stat && !options?.stats.some(stat => stat.key === influence.stat) ?
            <option value={influence.stat}>{t('Missing reference: {value}').replace('{value}', influence.stat)}</option> : null}
          {options?.stats.map(stat => <option key={stat.key} value={stat.key}>{t(stat.label)}</option>)}
        </select>
      </Field>
      <Field label={t('Direction')}>
        <select className="ga-input" name="influence-direction" aria-label={t('Direction')} value={influence.direction}
          onChange={event => onInfluence({ ...influence, direction: event.target.value as Influence['direction'] })}>
          {!['increase', 'decrease', 'both'].includes(influence.direction) ? <option value={influence.direction}>{t('Unavailable: {value}').replace('{value}', influence.direction)}</option> : null}
          <option value="increase">{t('Increase')}</option>
          <option value="decrease">{t('Decrease')}</option>
          <option value="both">{t('Both directions')}</option>
        </select>
      </Field>
      <Field label={t('Factor')} hint={t('Enter a finite number from 0.1 to 5. A factor of 1 is neutral.')}>
        <input className="ga-input" name="influence-factor" aria-label={t('Factor')} type="number" min={options?.factor_min ?? 0.1} max={options?.factor_max ?? 5} step="any"
          value={Number.isFinite(influence.factor) ? influence.factor : ''}
          onChange={event => onInfluence({ ...influence, factor: event.target.value === '' ? NaN : Number(event.target.value) })} />
      </Field>
    </div>
    <Field label={t('Actor condition')} hint={t('Evaluated against the actor. Empty means always; all role and pair conditions must match.')}>
      <input className="ga-input" name="actor-condition" aria-label={t('Actor condition')} autoComplete="off" spellCheck={false} value={actorCondition} onChange={event => onActorCondition(event.target.value)} />
    </Field>
    <fieldset style={{ minWidth: 0 }}>
      <legend>{t('Pair conditions')}</legend>
      {pairConditions.length === 0 ? <p className="ga-hint">{t('No pair conditions. No attraction requirement is implied.')}</p> : null}
      {pairConditions.map((pair, index) => {
        const capability = options?.pair_conditions.find(option => option.kind === pair.kind)
        return <div key={index} style={{ marginBottom: 12 }}>
          <div className="ga-form-row" style={{ alignItems: 'end', flexWrap: 'wrap' }}>
            <Field label={t('Pair condition')}>
              <select className="ga-input" name={`pair-${index}-kind`} aria-label={t('Pair condition')} value={pair.kind} onChange={event => changePair(index,
                event.target.value === 'relationship' ? { kind: 'relationship', op: '>', value: 0 } : { kind: 'attraction', observer: 'recipient' })}>
                {pair.kind !== 'relationship' && pair.kind !== 'attraction' ? <option value={pair.kind}>{t('Unavailable: {value}').replace('{value}', pair.kind)}</option> : null}
                <option value="relationship">{t('Pair relationship strength')}{options?.pair_conditions.find(option => option.kind === 'relationship')?.available === false ? ` (${t('Unavailable')})` : ''}</option>
                <option value="attraction">{t('Directed attraction')}{options?.pair_conditions.find(option => option.kind === 'attraction')?.available === false ? ` (${t('Unavailable')})` : ''}</option>
              </select>
            </Field>
            {pair.kind === 'relationship' ? <>
              <Field label={t('Comparison')}>
                <select className="ga-input" name={`pair-${index}-comparison`} aria-label={t('Comparison')} value={pair.op || ''} onChange={event => changePair(index, { ...pair, op: event.target.value })}>
                  {['>', '<', '='].map(op => <option key={op} value={op}>{op}</option>)}
                </select>
              </Field>
              <Field label={t('Threshold')}>
                <input className="ga-input" name={`pair-${index}-threshold`} aria-label={t('Threshold')} type="number" min={0} max={100} value={Number.isFinite(pair.value) ? pair.value : ''}
                  onChange={event => changePair(index, { ...pair, value: event.target.value === '' ? NaN : Number(event.target.value) })} />
              </Field>
            </> : pair.kind === 'attraction' ? <Field label={t('Observer → subject')}>
              <select className="ga-input" name={`pair-${index}-observer`} aria-label={t('Observer → subject')} value={pair.observer || ''} onChange={event => changePair(index, { ...pair, observer: event.target.value })}>
                <option value="recipient">{t('Recipient → actor')}</option>
                <option value="actor">{t('Actor → recipient')}</option>
              </select>
            </Field> : null}
            <button type="button" className="ga-btn ga-btn-sm" aria-label={t('Remove pair condition {n}').replace('{n}', String(index + 1))}
              onClick={() => onPairConditions(pairConditions.filter((_, i) => i !== index))}>{t('Remove')}</button>
          </div>
          {options ? <small>{capability?.available ? t('Available') : t('Unavailable')}{capability?.reason ? `: ${t(capability.reason)}` : ''}</small> : null}
        </div>
      })}
      <button type="button" className="ga-btn ga-btn-sm" onClick={() => onPairConditions([...pairConditions, { kind: 'relationship', op: '>', value: 0 }])}>{t('Add pair condition')}</button>
    </fieldset>
    <div aria-live="polite">
      {optionsError ? <p role="alert">{t('Could not load influence options.')}: {optionsError}</p> : null}
      {validating ? <p>{t('Validating…')}</p> : null}
      {validationError ? <p role="alert">{t('Validation failed')}: {validationError}</p> : null}
      {diagnostics ? <>
        <p>{diagnostics.available ? t('Influence rule is available.') : t('Influence rule is inactive.')}</p>
        {diagnostics.errors.map((issue, index) => <p role="alert" key={`error-${index}`}>{issue.path}: {t(issue.message)}</p>)}
        {diagnostics.warnings.map((issue, index) => <p key={`warning-${index}`}>{t('Warning')}: {issue.path}: {t(issue.message)}</p>)}
      </> : null}
    </div>
    <button type="button" className="ga-btn ga-btn-sm" onClick={() => setAttempt(value => value + 1)} disabled={validating}>{t('Validate')}</button>
  </>
}
