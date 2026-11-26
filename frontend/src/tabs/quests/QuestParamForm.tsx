import type { ReactNode } from 'react'
import { Field } from '@anima/player-ui'
import { useI18n } from '../../i18n/I18nProvider'
import { ROLE_KINDS, issuesAt, rolesOfKinds } from './questsModel'
import type { Issue, ParamSpec, Role } from './questsModel'

function isValidJson(text: string): boolean {
  try {
    JSON.parse(text)
    return true
  } catch {
    return false
  }
}

/**
 * The parameters of one catalog type, rendered from its D5 spec: `str` and `text` are text, `int` and `float`
 * numbers (an empty field is left out, never 0), `bool` a checkbox, `select` its `choices` with
 * `choice_labels`, `role` a select over the template's roles of the allowed kinds, and `target` a select over
 * reachable role keys and quest-created effect keys. Labels and descriptions come from the server in English and
 * go through t(). The issues of `path` (`<expression>.params`) are shown under their field.
 */
export function QuestParamForm({
  spec, values, roles, issues, path, onChange, targets, placeholders, setup,
}: {
  spec: ParamSpec[]
  values: Record<string, unknown>
  roles: Role[]
  issues: Issue[]
  /** The D7 path of the params object, e.g. `steps.0.condition.params`. */
  path: string
  onChange: (next: Record<string, unknown>) => void
  targets?: (p: ParamSpec) => string[]
  placeholders?: string
  setup?: boolean
}) {
  const { t } = useI18n()
  if (spec.length === 0) return <p className="ga-form-hint">{t('This type has no parameters.')}</p>

  const roleKeySet = new Set(roles.map((r) => r.key).filter(Boolean))

  const set = (key: string, value: unknown) => {
    const next = { ...values }
    if (value === undefined) delete next[key]
    else next[key] = value
    onChange(next)
  }
  const short = spec.filter((p) => p.type !== 'text')
  const long = spec.filter((p) => p.type === 'text')

  const field = (p: ParamSpec) => {
    const value = values[p.key]
    const label = t(p.label || p.key) + (p.required ? ' *' : '')
    const tip = p.description ? t(p.description) : undefined
    const errors = issuesAt(issues, path + '.' + p.key)
    let control
    let extraHint: ReactNode = null
    if (p.type === 'bool') {
      control = <input type="checkbox" checked={value === true} onChange={(e) => set(p.key, e.target.checked)} />
    } else if (p.type === 'int' || p.type === 'float') {
      control = (
        <input className="ga-input" type="number" min={p.min} max={p.max}
          step={p.step ?? (p.type === 'int' ? 1 : 'any')}
          value={typeof value === 'number' ? value : ''}
          onChange={(e) => {
            if (e.target.value === '') return set(p.key, undefined)
            const n = p.type === 'int' ? parseInt(e.target.value, 10) : parseFloat(e.target.value)
            set(p.key, Number.isFinite(n) ? n : undefined)
          }} />
      )
    } else if (p.type === 'select') {
      const choices = p.choices || []
      const current = typeof value === 'string' ? value : ''
      control = (
        <select className="ga-input" value={current} onChange={(e) => set(p.key, e.target.value || undefined)}>
          <option value="">{t('— none —')}</option>
          {current && !choices.includes(current) ? <option value={current}>{current}</option> : null}
          {choices.map((c, i) => <option key={c} value={c}>{p.choice_labels?.[i] ? t(p.choice_labels[i]) : c}</option>)}
        </select>
      )
    } else if (p.type === 'role') {
      const kinds = p.role_kinds && p.role_kinds.length ? p.role_kinds : ROLE_KINDS
      const options = rolesOfKinds(roles, kinds).filter((r) => r.key)
      const current = typeof value === 'string' ? value : ''
      const emptyLabel = p.avatar_default && !setup ? t('— the avatar who did the step —') : t('— choose a role —')
      control = (
        <select className="ga-input" value={current} onChange={(e) => set(p.key, e.target.value || undefined)}>
          <option value="">{emptyLabel}</option>
          {current && !options.some((r) => r.key === current)
            ? <option value={current}>{current} ({t('not a fitting role')})</option> : null}
          {options.map((r) => <option key={r.key} value={r.key}>{r.key}</option>)}
        </select>
      )
    } else if (p.type === 'target') {
      const options = targets ? targets(p) : []
      const roleOpts = options.filter((k) => roleKeySet.has(k))
      const effectOpts = options.filter((k) => !roleKeySet.has(k))
      const current = typeof value === 'string' ? value : ''
      control = (
        <select className="ga-input" value={current} onChange={(e) => set(p.key, e.target.value || undefined)}>
          <option value="">{t('— choose —')}</option>
          {current && !options.includes(current)
            ? <option value={current}>{current} ({t('not reachable here')})</option> : null}
          {roleOpts.length ? (
            <optgroup label={t('Roles')}>
              {roleOpts.map((k) => <option key={k} value={k}>{k}</option>)}
            </optgroup>
          ) : null}
          {effectOpts.length ? (
            <optgroup label={t('Created by this quest')}>
              {effectOpts.map((k) => <option key={k} value={k}>{k}</option>)}
            </optgroup>
          ) : null}
        </select>
      )
    } else if (p.type === 'text') {
      const textVal = typeof value === 'string' ? value : ''
      const isJson = p.placeholders === false
      control = (
        <textarea className={isJson ? 'ga-textarea ga-quest-json' : 'ga-textarea'} rows={2} value={textVal}
          onChange={(e) => set(p.key, e.target.value)} />
      )
      if (isJson) {
        if (textVal.trim() && !isValidJson(textVal)) {
          extraHint = <p className="ga-hint">{t('Not valid JSON')}</p>
        }
      } else if (placeholders) {
        extraHint = (
          <span className="ga-quest-placeholders">{t('Placeholders: {list}').replace('{list}', placeholders)}</span>
        )
      }
    } else {
      control = (
        <input className="ga-input" value={typeof value === 'string' ? value : ''}
          onChange={(e) => set(p.key, e.target.value)} />
      )
    }
    return (
      <Field key={p.key} label={label} tip={tip} hint={p.type === 'text' && p.placeholders !== false ? extraHint : undefined}
        compact={p.type === 'bool'}>
        {control}
        {p.type === 'text' && p.placeholders === false ? extraHint : null}
        {errors.map((i, n) => <p key={n} className="ga-hint" role="alert">{t(i.message)}</p>)}
      </Field>
    )
  }

  return (
    <>
      {short.length ? <div className="ga-form-row ga-quest-params">{short.map(field)}</div> : null}
      {long.map(field)}
    </>
  )
}
