import { useState } from 'react'
import { Field } from '@anima/player-ui'
import { useI18n } from '../../i18n/I18nProvider'
import { SortableList } from '../../components/SortableList'
import { ConditionEditor } from './ConditionEditor'
import { ROLE_KINDS, issuesAt, newStepId } from './questsModel'
import type { Catalog, Expr, Issue, Role, RoleKind, Step, TemplateDraft } from './questsModel'

type Section = 'basics' | 'roles' | 'steps' | 'start'

const SECTIONS: { id: Section; label: string; paths: string[] }[] = [
  { id: 'basics', label: 'Basics', paths: ['title', 'time_limit_s'] },
  { id: 'roles', label: 'Roles', paths: ['roles'] },
  { id: 'steps', label: 'Steps', paths: ['steps'] },
  { id: 'start', label: 'Start & requirements', paths: ['start_condition', 'prerequisites'] },
]

const ROLE_KIND_LABELS: Record<RoleKind, string> = {
  character: 'Character',
  location: 'Location',
  room: 'Room',
  item: 'Item',
}

function Alerts({ issues }: { issues: Issue[] }) {
  return <>{issues.map((i, n) => <p key={n} className="ga-hint" role="alert">{i.message}</p>)}</>
}

/**
 * The detail form of one quest template, split into four sub-tabs so no pane grows past a screen: Basics (title,
 * state, time limit in game hours, summary, GM notes), Roles, Steps (ordered; each with its condition) and Start &
 * requirements. Server issues are shown at their D7 path; a sub-tab names how many it holds.
 *
 * `onStructureChange` is called when roles or steps are removed or reordered — the issue paths carry indices, so
 * the caller drops the issues it holds instead of showing them at the wrong row.
 */
export function TemplateForm({
  draft, catalog, issues, onChange, onStructureChange,
}: {
  draft: TemplateDraft
  catalog: Catalog
  issues: Issue[]
  onChange: (next: TemplateDraft) => void
  onStructureChange: () => void
}) {
  const { t } = useI18n()
  const [section, setSection] = useState<Section>('basics')
  const set = <K extends keyof TemplateDraft>(key: K, value: TemplateDraft[K]) => onChange({ ...draft, [key]: value })

  const conditionTypes = catalog.conditions
  const prerequisiteTypes = [...catalog.conditions, ...catalog.prerequisites]
  const roleKinds = catalog.role_kinds.length ? catalog.role_kinds : ROLE_KINDS

  const setRole = (i: number, patch: Partial<Role>) =>
    set('roles', draft.roles.map((r, j) => (j === i ? { ...r, ...patch } : r)))
  const setStep = (i: number, patch: Partial<Step>) =>
    set('steps', draft.steps.map((s, j) => (j === i ? { ...s, ...patch } : s)))

  const basics = (
    <div className="ga-form">
      <div className="ga-form-row">
        <Field label={t('Title') + ' *'}>
          <input className="ga-input" value={draft.title} onChange={(e) => set('title', e.target.value)} />
          <Alerts issues={issuesAt(issues, 'title')} />
        </Field>
        <Field label={t('State')} compact
          tip={t('Only a ready template can be started. A template with issues can only be saved as a draft.')}>
          <select className="ga-input" value={draft.state}
            onChange={(e) => set('state', e.target.value === 'ready' ? 'ready' : 'draft')}>
            <option value="draft">{t('Draft')}</option>
            <option value="ready">{t('Ready')}</option>
          </select>
        </Field>
        <Field label={t('Time limit (game hours)')} compact tip={t('0 = no time limit')}>
          <input className="ga-input ga-quest-num" type="number" min={0} step="any"
            value={Number.isFinite(draft.time_limit_h) ? draft.time_limit_h : 0}
            onChange={(e) => {
              const n = parseFloat(e.target.value)
              set('time_limit_h', Number.isFinite(n) && n > 0 ? n : 0)
            }} />
          <Alerts issues={issuesAt(issues, 'time_limit_s')} />
        </Field>
      </div>
      <Field label={t('Summary')} hint={t('Shown to the player in the quest book.')}>
        <textarea className="ga-textarea" rows={2} value={draft.summary} onChange={(e) => set('summary', e.target.value)} />
      </Field>
      <Field label={t('GM notes')} hint={t('Only for the game master; never shown to a player.')}>
        <textarea className="ga-textarea" rows={4} value={draft.gm_notes} onChange={(e) => set('gm_notes', e.target.value)} />
      </Field>
    </div>
  )

  const roles = (
    <div className="ga-form">
      <p className="ga-form-hint">
        {t('A role is a placeholder the conditions refer to; starting a quest binds each role to a character, location, room or item of the world.')}
      </p>
      {draft.roles.length === 0 ? <p className="ga-form-hint">{t('No roles yet.')}</p> : null}
      {draft.roles.map((role, i) => (
        <div key={i} className="ga-form-row ga-quest-role">
          <Field label={t('Key') + ' *'} compact>
            <input className="ga-input ga-quest-key" value={role.key} onChange={(e) => setRole(i, { key: e.target.value })} />
            <Alerts issues={issuesAt(issues, `roles.${i}.key`)} />
          </Field>
          <Field label={t('Role kind')} compact>
            <select className="ga-input" value={role.kind} onChange={(e) => setRole(i, { kind: e.target.value as RoleKind })}>
              {!roleKinds.includes(role.kind) ? <option value={role.kind}>{role.kind || '—'}</option> : null}
              {roleKinds.map((k) => <option key={k} value={k}>{t(ROLE_KIND_LABELS[k] || k)}</option>)}
            </select>
            <Alerts issues={issuesAt(issues, `roles.${i}.kind`)} />
          </Field>
          <Field label={t('Description')}>
            <input className="ga-input" value={role.description} onChange={(e) => setRole(i, { description: e.target.value })} />
          </Field>
          <button type="button" className="ga-btn ga-btn-sm ga-btn-danger ga-quest-remove"
            onClick={() => { onStructureChange(); set('roles', draft.roles.filter((_, j) => j !== i)) }}>
            {t('Remove')}
          </button>
        </div>
      ))}
      <div>
        <button type="button" className="ga-btn ga-btn-sm"
          onClick={() => set('roles', [...draft.roles, { key: '', kind: roleKinds[0] || 'character', description: '' }])}>
          {t('+ Add role')}
        </button>
      </div>
    </div>
  )

  const indexed = draft.steps.map((step, index) => ({ step, index }))
  const steps = (
    <div className="ga-form">
      <p className="ga-form-hint">{t('Steps are done one after another; drag ⋮⋮ to reorder them.')}</p>
      <Alerts issues={issues.filter((i) => i.path === 'steps')} />
      <SortableList
        items={indexed}
        getKey={(w) => String(w.index)}
        onReorder={(keys) => { onStructureChange(); set('steps', keys.map((k) => draft.steps[Number(k)])) }}
        render={({ step, index }) => (
          <div className="ga-quest-step">
            <div className="ga-form-row">
              <Field label={t('Step id') + ' *'} compact>
                <input className="ga-input ga-quest-key" value={step.id} onChange={(e) => setStep(index, { id: e.target.value })} />
                <Alerts issues={issuesAt(issues, `steps.${index}.id`)} />
              </Field>
              <Field label={t('Text') + ' *'} tip={t('What the player reads in the quest book.')}>
                <input className="ga-input" value={step.text} onChange={(e) => setStep(index, { text: e.target.value })} />
                <Alerts issues={issuesAt(issues, `steps.${index}.text`)} />
              </Field>
              <Field label={t('Hint')}>
                <input className="ga-input" value={step.hint} onChange={(e) => setStep(index, { hint: e.target.value })} />
              </Field>
              <button type="button" className="ga-btn ga-btn-sm ga-btn-danger ga-quest-remove"
                onClick={() => { onStructureChange(); set('steps', draft.steps.filter((_, j) => j !== index)) }}>
                {t('Remove')}
              </button>
            </div>
            <Field label={t('Done when')}>
              <ConditionEditor expr={step.condition} types={conditionTypes} roles={draft.roles} issues={issues}
                path={`steps.${index}.condition`} onChange={(condition: Expr) => setStep(index, { condition })} />
            </Field>
          </div>
        )}
      />
      <div>
        <button type="button" className="ga-btn ga-btn-sm"
          onClick={() => set('steps', [...draft.steps, { id: newStepId(draft.steps), text: '', hint: '', condition: {} }])}>
          {t('+ Add step')}
        </button>
      </div>
    </div>
  )

  const start = (
    <div className="ga-form">
      <Field label={t('Start condition')}
        hint={t('The quest opens for the player once this holds; until then it stays hidden.')}>
        <ConditionEditor expr={draft.start_condition} types={conditionTypes} roles={draft.roles} issues={issues}
          path="start_condition" onChange={(start_condition) => set('start_condition', start_condition)} />
      </Field>
      <Field label={t('Requirements')}
        hint={t('A player who does not meet them sees the quest locked, with the text below as the reason.')}>
        <ConditionEditor expr={draft.prerequisites.condition} types={prerequisiteTypes} roles={draft.roles} issues={issues}
          path="prerequisites.condition"
          onChange={(condition) => set('prerequisites', { ...draft.prerequisites, condition })} />
      </Field>
      <Field label={t('Locked text')} hint={t('Empty: "You do not meet the requirements."')}>
        <input className="ga-input" value={draft.prerequisites.locked_text}
          onChange={(e) => set('prerequisites', { ...draft.prerequisites, locked_text: e.target.value })} />
        <Alerts issues={issuesAt(issues, 'prerequisites.locked_text')} />
      </Field>
    </div>
  )

  return (
    <>
      <nav className="ga-subtabs" aria-label={t('Quest template')}>
        {SECTIONS.map((s) => {
          const count = s.paths.reduce((n, p) => n + issuesAt(issues, p).length, 0)
          return (
            <button key={s.id} type="button" aria-pressed={section === s.id}
              className={`ga-btn ga-btn-sm${section === s.id ? ' ga-btn-primary' : ''}`}
              onClick={() => setSection(s.id)}>
              {t(s.label)}{count ? <span className="ga-tag ga-tag-missing">{count}</span> : null}
            </button>
          )
        })}
      </nav>
      {section === 'basics' ? basics : section === 'roles' ? roles : section === 'steps' ? steps : start}
    </>
  )
}
