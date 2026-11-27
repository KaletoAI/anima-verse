import { useI18n } from '../../i18n/I18nProvider'
import { QuestParamForm } from './QuestParamForm'
import { defaultParams, issuesAt } from './questsModel'
import type { CatalogType, Issue, ParamSpec, Role } from './questsModel'

/**
 * The leaf editor shared by conditions and effects: optional type select, the type's description, stray-parameter
 * issues (for parameters the registered type does not declare), and the generic `QuestParamForm`.
 */
export function QuestLeafEditor({
  leaf, types, pickable, roles, issues, path, onChange, targets, placeholders, setup, typeLabel, hideTypeSelect,
}: {
  leaf: { type: string; params: Record<string, unknown> }
  types: CatalogType[]
  pickable?: CatalogType[]
  roles: Role[]
  issues: Issue[]
  path: string
  onChange: (next: { type: string; params: Record<string, unknown> }) => void
  targets?: (p: ParamSpec) => string[]
  placeholders?: string
  setup?: boolean
  typeLabel?: string
  hideTypeSelect?: boolean
}) {
  const { t } = useI18n()
  const offered = pickable ?? types
  const type = types.find((x) => x.id === leaf.type)
  const inOffered = offered.some((x) => x.id === leaf.type)
  // Issues of a parameter the type does not declare have no field to stand under: shown at the leaf.
  const declared = new Set((type?.params || []).map((p) => path + '.params.' + p.key))
  const stray = issuesAt(issues, path + '.params').filter(
    (i) => ![...declared].some((d) => i.path === d || i.path.startsWith(d + '.')),
  )

  return (
    <>
      {!hideTypeSelect ? (
        <div className="ga-form-row">
          <select className="ga-input" aria-label={typeLabel} value={leaf.type}
            onChange={(e) => {
              const picked = types.find((x) => x.id === e.target.value)
              onChange({ type: e.target.value, params: defaultParams(picked) })
            }}>
            {!type ? (
              <option value={leaf.type}>{leaf.type} ({t('not registered')})</option>
            ) : !inOffered ? (
              <option value={leaf.type}>{t(type.label)} ({t('not allowed here')})</option>
            ) : null}
            {offered.map((x) => <option key={x.id} value={x.id}>{t(x.label)}</option>)}
          </select>
        </div>
      ) : null}
      {type?.description ? <p className="ga-form-hint">{t(type.description)}</p> : null}
      {stray.map((i, n) => <p key={n} className="ga-hint" role="alert">{t(i.message)}</p>)}
      {type ? (
        <QuestParamForm spec={type.params} values={leaf.params || {}} roles={roles} issues={issues}
          path={path + '.params'} onChange={(params) => onChange({ type: leaf.type, params })}
          targets={targets} placeholders={placeholders} setup={setup} />
      ) : null}
    </>
  )
}
