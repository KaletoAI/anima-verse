import { Field } from '@anima/player-ui'
import { useI18n } from '../../i18n/I18nProvider'
import { SortableList } from '../../components/SortableList'
import { QuestLeafEditor } from './QuestLeafEditor'
import { defaultParams, issuesAt, moveItem, newEffectKey, targetOptions } from './questsModel'
import type { CatalogType, EffectEntry, Issue, TemplateDraft } from './questsModel'

function Alerts({ issues }: { issues: Issue[] }) {
  const { t } = useI18n()
  return <>{issues.map((i, n) => <p key={n} className="ga-hint" role="alert">{t(i.message)}</p>)}</>
}

/**
 * Generic ordered effect-list editor used for setup effects, step `on_done` effects and rewards. Each entry holds
 * a key, an effect type, an optional `permanent` flag (always true for rewards, checkbox omitted) and the type's
 * parameters rendered through `QuestLeafEditor`.
 */
export function EffectListEditor({
  effects, draft, effectTypes, issues, path, where, reward, setup, placeholders, onChange, onStructureChange,
}: {
  effects: EffectEntry[]
  draft: TemplateDraft
  effectTypes: CatalogType[]
  issues: Issue[]
  /** D7 list path, e.g. `setup_effects`, `steps.0.on_done`, `rewards`. */
  path: string
  /** Scope position for entry index `j`, e.g. `(j) => 'setup:' + j`. */
  where: (index: number) => string
  reward?: boolean
  setup?: boolean
  placeholders?: string
  onChange: (next: EffectEntry[]) => void
  onStructureChange: () => void
}) {
  const { t } = useI18n()

  const setEntry = (j: number, patch: Partial<EffectEntry>) =>
    onChange(effects.map((e, i) => (i === j ? { ...e, ...patch, ...(reward ? { permanent: true } : {}) } : e)))

  const moveEntry = (from: number, to: number) => {
    onStructureChange()
    onChange(moveItem(effects, from, to))
  }

  const addEffect = () => {
    const first = effectTypes[0]
    onChange([
      ...effects,
      { key: newEffectKey(draft), type: first?.id || '', params: defaultParams(first), permanent: !!reward },
    ])
  }

  const listIssues = issues.filter((i) => i.path === path)
  const indexed = effects.map((entry, index) => ({ entry, index }))

  return (
    <div className="ga-quest-effects">
      <Alerts issues={listIssues} />
      {effects.length === 0 ? (
        <p className="ga-form-hint">{t('No effects.')}</p>
      ) : (
        <SortableList
          items={indexed}
          getKey={(w) => String(w.index)}
          onReorder={(keys) => { onStructureChange(); onChange(keys.map((k) => effects[Number(k)])) }}
          render={({ entry, index }) => {
            const entryPath = `${path}.${index}`
            const pickedType = effectTypes.find((x) => x.id === entry.type)
            const entryIssues = issues.filter((i) => i.path === entryPath)
            return (
              <div className="ga-quest-effect">
                <div className="ga-form-row">
                  <Field label={t('Key') + ' *'} compact>
                    <input className="ga-input ga-quest-key" value={entry.key}
                      onChange={(e) => setEntry(index, { key: e.target.value })} />
                    <Alerts issues={issuesAt(issues, `${entryPath}.key`)} />
                  </Field>
                  <Field label={t('Effect type')} compact>
                    <select className="ga-input" aria-label={t('Effect type')} value={entry.type}
                      onChange={(e) => {
                        const nextType = effectTypes.find((x) => x.id === e.target.value)
                        setEntry(index, { type: e.target.value, params: defaultParams(nextType) })
                      }}>
                      {!pickedType ? <option value={entry.type}>{entry.type} ({t('not registered')})</option> : null}
                      {effectTypes.map((x) => <option key={x.id} value={x.id}>{t(x.label)}</option>)}
                    </select>
                    <Alerts issues={issuesAt(issues, `${entryPath}.type`)} />
                  </Field>
                  {!reward ? (
                    <Field label={t('Permanent')} compact tip={t('Stays in the world when the run ends')}>
                      <input type="checkbox" checked={entry.permanent}
                        onChange={(e) => setEntry(index, { permanent: e.target.checked })} />
                      <Alerts issues={issuesAt(issues, `${entryPath}.permanent`)} />
                    </Field>
                  ) : null}
                  <div className="ga-quest-move">
                    <button type="button" className="ga-btn ga-btn-sm" disabled={index === 0}
                      title={t('Move up')} aria-label={t('Move up')} onClick={() => moveEntry(index, index - 1)}>↑</button>
                    <button type="button" className="ga-btn ga-btn-sm" disabled={index === effects.length - 1}
                      title={t('Move down')} aria-label={t('Move down')} onClick={() => moveEntry(index, index + 1)}>↓</button>
                  </div>
                  <button type="button" className="ga-btn ga-btn-sm ga-btn-danger ga-quest-remove"
                    onClick={() => { onStructureChange(); onChange(effects.filter((_, i) => i !== index)) }}>
                    {t('Remove')}
                  </button>
                </div>
                <Alerts issues={entryIssues} />
                <QuestLeafEditor
                  leaf={{ type: entry.type, params: entry.params }}
                  types={effectTypes}
                  roles={draft.roles}
                  issues={issues}
                  path={entryPath}
                  onChange={(leaf) => setEntry(index, { type: leaf.type, params: leaf.params })}
                  targets={(p) => targetOptions(draft, where(index), p, effectTypes)}
                  placeholders={placeholders}
                  setup={setup}
                  typeLabel={t('Effect type')}
                  hideTypeSelect
                />
              </div>
            )
          }}
        />
      )}
      <div>
        <button type="button" className="ga-btn ga-btn-sm" onClick={addEffect}>{t('+ Add effect')}</button>
      </div>
    </div>
  )
}
