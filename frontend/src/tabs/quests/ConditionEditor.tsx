import { useI18n } from '../../i18n/I18nProvider'
import { QuestLeafEditor } from './QuestLeafEditor'
import { defaultParams, isEmptyExpr } from './questsModel'
import type { CatalogType, Expr, Issue, ParamSpec, Role } from './questsModel'

type Mode = 'true' | 'leaf' | 'all' | 'any' | 'not'

const MODE_LABELS: Record<Mode, string> = {
  true: 'Always true',
  leaf: 'Condition',
  all: 'All of',
  any: 'Any of',
  not: 'Not',
}

function modeOf(expr: Expr): Mode {
  if (isEmptyExpr(expr)) return 'true'
  if ('type' in expr) return 'leaf'
  if ('all' in expr) return 'all'
  if ('any' in expr) return 'any'
  if ('not' in expr) return 'not'
  return 'true'
}

/** The issues whose path is exactly one of `paths` (the issues of this node itself, not of its children). */
function exactly(issues: Issue[], ...paths: string[]): Issue[] {
  return issues.filter((i) => paths.includes(i.path))
}

/**
 * A D7 expression as a recursive editor: "always true", one condition (a catalog type plus its parameters), or an
 * all / any / not group of further expressions. `types` are the catalog types this position accepts (a step and the
 * start condition take conditions, the prerequisites conditions and prerequisites). `path` is the D7 path of this
 * node; server issues are shown at the node they name, parameter issues under their field. `onStructureChange` is
 * called when an entry of an All/Any group is removed (the later entries' indices shift, so the caller drops the
 * issues it holds instead of showing them under the wrong entry).
 */
export function ConditionEditor({
  expr, types, roles, issues, path, onChange, onStructureChange, targets, placeholders, allowStepOnly = false,
}: {
  expr: Expr
  types: CatalogType[]
  roles: Role[]
  issues: Issue[]
  path: string
  onChange: (next: Expr) => void
  onStructureChange?: () => void
  targets?: (p: ParamSpec) => string[]
  placeholders?: string
  allowStepOnly?: boolean
}) {
  const { t } = useI18n()
  const mode = modeOf(expr)
  const pickable = allowStepOnly ? types : types.filter((x) => !x.step_only)

  const freshLeaf = (): Expr => (pickable.length ? { type: pickable[0].id, params: defaultParams(pickable[0]) } : {})

  const switchMode = (next: Mode) => {
    if (next === mode) return
    const current = isEmptyExpr(expr) ? freshLeaf() : expr
    if (next === 'true') onChange({})
    else if (next === 'leaf') onChange(mode === 'not' ? (expr as { not: Expr }).not : 'type' in current ? current : freshLeaf())
    else if (next === 'all' || next === 'any') {
      const children = mode === 'all' || mode === 'any'
        ? (expr as Record<string, Expr[]>)[mode] : [current]
      onChange(next === 'all' ? { all: children } : { any: children })
    } else onChange({ not: current })
  }

  const own = exactly(issues, path, path ? path + '.type' : 'type')

  let body = null
  if (mode === 'leaf') {
    const leaf = expr as { type: string; params?: Record<string, unknown> }
    body = (
      <QuestLeafEditor
        leaf={{ type: leaf.type, params: leaf.params || {} }}
        types={types}
        pickable={pickable}
        roles={roles}
        issues={issues}
        path={path}
        onChange={(next) => onChange(next)}
        targets={targets}
        placeholders={placeholders}
        setup={false}
        typeLabel={t('Condition type')}
      />
    )
  } else if (mode === 'all' || mode === 'any') {
    const children = (expr as Record<string, Expr[]>)[mode]
    const put = (list: Expr[]) => onChange(mode === 'all' ? { all: list } : { any: list })
    body = (
      <div className="ga-quest-cond-children">
        {children.map((child, i) => (
          <div key={i} className="ga-quest-cond-child">
            <ConditionEditor expr={child} types={types} roles={roles} issues={issues}
              path={`${path}.${mode}.${i}`} onChange={(next) => put(children.map((c, j) => (j === i ? next : c)))}
              onStructureChange={onStructureChange} targets={targets} placeholders={placeholders}
              allowStepOnly={allowStepOnly} />
            <button type="button" className="ga-btn ga-btn-sm" disabled={children.length <= 1}
              title={children.length <= 1 ? t('A group needs at least one entry') : undefined}
              onClick={() => { onStructureChange?.(); put(children.filter((_, j) => j !== i)) }}>{t('Remove')}</button>
          </div>
        ))}
        <button type="button" className="ga-btn ga-btn-sm" onClick={() => put([...children, freshLeaf()])}>
          {t('+ Add condition')}
        </button>
      </div>
    )
  } else if (mode === 'not') {
    const inner = (expr as { not: Expr }).not
    body = (
      <div className="ga-quest-cond-children">
        <ConditionEditor expr={inner} types={types} roles={roles} issues={issues} path={path + '.not'}
          onChange={(next) => onChange({ not: next })} onStructureChange={onStructureChange}
          targets={targets} placeholders={placeholders} allowStepOnly={false} />
      </div>
    )
  }

  return (
    <div className="ga-quest-cond">
      <div className="ga-quest-cond-head">
        <select className="ga-input" aria-label={t('Expression kind')} value={mode}
          onChange={(e) => switchMode(e.target.value as Mode)}>
          {(Object.keys(MODE_LABELS) as Mode[]).map((m) => <option key={m} value={m}>{t(MODE_LABELS[m])}</option>)}
        </select>
      </div>
      {own.map((i, n) => <p key={n} className="ga-hint" role="alert">{t(i.message)}</p>)}
      {body}
    </div>
  )
}
