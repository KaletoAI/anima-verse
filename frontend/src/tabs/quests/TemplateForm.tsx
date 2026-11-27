import { useState } from 'react'
import { Field } from '@anima/player-ui'
import { useI18n } from '../../i18n/I18nProvider'
import { SortableList } from '../../components/SortableList'
import { ConditionEditor } from './ConditionEditor'
import { EffectListEditor } from './EffectListEditor'
import {
  ROLE_KINDS, draftWarnings, issuesAt, moveItem, newStepId, placeholderList, rolesOfKinds, targetOptions,
} from './questsModel'
import type { Catalog, Expr, Issue, Role, RoleKind, Step, TemplateDraft } from './questsModel'

type Section = 'basics' | 'roles' | 'steps' | 'effects' | 'start'

const SECTIONS: { id: Section; label: string; paths: string[] }[] = [
  { id: 'basics', label: 'Basics', paths: ['title', 'giver_role', 'time_limit_s', 'summary'] },
  { id: 'roles', label: 'Roles', paths: ['roles'] },
  { id: 'steps', label: 'Steps', paths: ['steps'] },
  { id: 'effects', label: 'Setup & rewards', paths: ['setup_effects', 'rewards'] },
  { id: 'start', label: 'Start & requirements', paths: ['start_condition', 'prerequisites'] },
]

const ROLE_KIND_LABELS: Record<RoleKind, string> = {
  character: 'Character',
  location: 'Location',
  room: 'Room',
  item: 'Item',
}

/** The time limit in game hours. The text is held locally while the field has focus, so it can be emptied and
 *  retyped; leaving the field commits it (empty or not a positive number = 0, no time limit). */
function HoursInput({ value, onCommit }: { value: number; onCommit: (hours: number) => void }) {
  const [text, setText] = useState<string | null>(null)
  const shown = Number.isFinite(value) ? String(value) : '0'
  return (
    <input className="ga-input ga-quest-num" type="number" min={0} step="any"
      value={text ?? shown}
      onFocus={() => setText(shown)}
      onChange={(e) => setText(e.target.value)}
      onBlur={() => {
        const n = parseFloat(text ?? shown)
        setText(null)
        onCommit(Number.isFinite(n) && n > 0 ? n : 0)
      }} />
  )
}

function Alerts({ issues }: { issues: Issue[] }) {
  const { t } = useI18n()
  return <>{issues.map((i, n) => <p key={n} className="ga-hint" role="alert">{t(i.message)}</p>)}</>
}

/**
 * The detail form of one quest template, split into four sub-tabs so no pane grows past a screen: Basics (title,
 * state, time limit in game hours, summary, GM notes), Roles, Steps (ordered; each with its condition) and Start &
 * requirements. Server issues are shown at their D7 path; a sub-tab names how many it holds.
 *
 * `onStructureChange` is called when roles, steps or the entries of an All/Any group are removed or reordered — the
 * issue paths carry indices, so the caller drops the issues it holds instead of showing them at the wrong row.
 * Steps move by drag (⋮⋮) or by the ↑ ↓ buttons — the drag lands a step ABOVE its target, so only ↓ reaches the end.
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
  const effectTypes = catalog.effects
  const roleKinds = catalog.role_kinds.length ? catalog.role_kinds : ROLE_KINDS
  const characterRoles = rolesOfKinds(draft.roles, ['character']).filter((r) => r.key)
  const warnings = draftWarnings(draft)

  const setRole = (i: number, patch: Partial<Role>) =>
    set('roles', draft.roles.map((r, j) => (j === i ? { ...r, ...patch } : r)))
  const setStep = (i: number, patch: Partial<Step>) =>
    set('steps', draft.steps.map((s, j) => (j === i ? { ...s, ...patch } : s)))
  const moveStep = (from: number, to: number) => {
    onStructureChange()
    set('steps', moveItem(draft.steps, from, to))
  }
  // One line under each player text: the role placeholders it may use (rendered with the bound names at start).
  const placeholders = placeholderList(draft.roles)
  const placeholderHint = placeholders
    ? <span className="ga-quest-placeholders">{t('Placeholders: {list}').replace('{list}', placeholders)}</span>
    : null

  const basics = (
    <div className="ga-form">
      <div className="ga-form-row">
        <Field label={t('Title') + ' *'} hint={placeholderHint}>
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
        <Field label={t('Quest giver')} compact
          tip={t('The character who hands out the quest; their prompt mentions it.')}>
          <select className="ga-input" value={draft.giver_role}
            onChange={(e) => set('giver_role', e.target.value)}>
            <option value="">{t('— none —')}</option>
            {draft.giver_role && !characterRoles.some((r) => r.key === draft.giver_role) ? (
              <option value={draft.giver_role}>{draft.giver_role} ({t('not a fitting role')})</option>
            ) : null}
            {characterRoles.map((r) => <option key={r.key} value={r.key}>{r.key}</option>)}
          </select>
          <Alerts issues={issuesAt(issues, 'giver_role')} />
        </Field>
        <Field label={t('Time limit (game hours)')} compact tip={t('0 = no time limit')}>
          <HoursInput value={draft.time_limit_h} onCommit={(hours) => set('time_limit_h', hours)} />
          <Alerts issues={issuesAt(issues, 'time_limit_s')} />
        </Field>
      </div>
      <Field label={t('Summary')}
        hint={<>{t('Shown to the player in the quest book.')}{placeholderHint ? <><br />{placeholderHint}</> : null}</>}>
        <textarea className="ga-textarea" rows={2} value={draft.summary} onChange={(e) => set('summary', e.target.value)} />
        <Alerts issues={issuesAt(issues, 'summary')} />
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
      <p className="ga-form-hint">{t('Steps are done one after another; drag ⋮⋮ or use ↑ ↓ to reorder them.')}</p>
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
              <Field label={t('Text') + ' *'} tip={t('What the player reads in the quest book.')} hint={placeholderHint}>
                <input className="ga-input" value={step.text} onChange={(e) => setStep(index, { text: e.target.value })} />
                <Alerts issues={issuesAt(issues, `steps.${index}.text`)} />
              </Field>
              <Field label={t('Hint')}>
                <input className="ga-input" value={step.hint} onChange={(e) => setStep(index, { hint: e.target.value })} />
                <Alerts issues={issuesAt(issues, `steps.${index}.hint`)} />
              </Field>
              <div className="ga-quest-move">
                <button type="button" className="ga-btn ga-btn-sm" disabled={index === 0}
                  title={t('Move up')} aria-label={t('Move up')} onClick={() => moveStep(index, index - 1)}>↑</button>
                <button type="button" className="ga-btn ga-btn-sm" disabled={index === draft.steps.length - 1}
                  title={t('Move down')} aria-label={t('Move down')} onClick={() => moveStep(index, index + 1)}>↓</button>
              </div>
              <button type="button" className="ga-btn ga-btn-sm ga-btn-danger ga-quest-remove"
                onClick={() => { onStructureChange(); set('steps', draft.steps.filter((_, j) => j !== index)) }}>
                {t('Remove')}
              </button>
            </div>
            <Field label={t('Done when')}>
              <ConditionEditor expr={step.condition} types={conditionTypes} roles={draft.roles} issues={issues}
                path={`steps.${index}.condition`} onChange={(condition: Expr) => setStep(index, { condition })}
                onStructureChange={onStructureChange}
                targets={(p) => targetOptions(draft, `step:${index}`, p, effectTypes)}
                placeholders={placeholders}
                allowStepOnly />
              {warnings.filter((w) => w.path === `steps.${index}.condition`).map((w, n) => (
                <p key={n} className="ga-field-warn">{t(w.message)}</p>
              ))}
            </Field>
            <Field label={t('On done')}>
              <EffectListEditor
                effects={step.on_done}
                draft={draft}
                effectTypes={effectTypes}
                issues={issues}
                path={`steps.${index}.on_done`}
                where={(j) => `on_done:${index}:${j}`}
                placeholders={placeholders}
                onChange={(on_done) => setStep(index, { on_done })}
                onStructureChange={onStructureChange}
              />
            </Field>
            <Field label={t('Role notes')}
              hint={t('What a character of this quest knows or should do while this step is current. Only that character sees it, never the player.')}>
              <Alerts issues={issues.filter((i) => i.path === `steps.${index}.role_notes`)} />
              {step.role_notes.map((note, j) => (
                <div key={j} className="ga-form-row ga-quest-role-note">
                  <Field label={t('Character')} compact>
                    <select className="ga-input" value={note.role}
                      onChange={(e) => setStep(index, {
                        role_notes: step.role_notes.map((n, k) => (k === j ? { ...n, role: e.target.value } : n)),
                      })}>
                      <option value="">{t('— none —')}</option>
                      {note.role && !characterRoles.some((r) => r.key === note.role) ? (
                        <option value={note.role}>{note.role} ({t('not a fitting role')})</option>
                      ) : null}
                      {characterRoles.map((r) => <option key={r.key} value={r.key}>{r.key}</option>)}
                    </select>
                    <Alerts issues={issuesAt(issues, `steps.${index}.role_notes.${j}.role`)} />
                  </Field>
                  <Field label={t('Text')} hint={placeholderHint}>
                    <textarea className="ga-textarea" rows={2} value={note.text}
                      onChange={(e) => setStep(index, {
                        role_notes: step.role_notes.map((n, k) => (k === j ? { ...n, text: e.target.value } : n)),
                      })} />
                    <Alerts issues={issuesAt(issues, `steps.${index}.role_notes.${j}.text`)} />
                  </Field>
                  <button type="button" className="ga-btn ga-btn-sm ga-btn-danger ga-quest-remove"
                    onClick={() => {
                      onStructureChange()
                      setStep(index, { role_notes: step.role_notes.filter((_, k) => k !== j) })
                    }}>
                    {t('Remove')}
                  </button>
                </div>
              ))}
              <div>
                <button type="button" className="ga-btn ga-btn-sm"
                  onClick={() => setStep(index, { role_notes: [...step.role_notes, { role: '', text: '' }] })}>
                  {t('+ Add role note')}
                </button>
              </div>
            </Field>
          </div>
        )}
      />
      <div>
        <button type="button" className="ga-btn ga-btn-sm"
          onClick={() => set('steps', [...draft.steps, { id: newStepId(draft.steps), text: '', hint: '', condition: {}, on_done: [], role_notes: [] }])}>
          {t('+ Add step')}
        </button>
      </div>
    </div>
  )

  const effects = (
    <div className="ga-form">
      <Field label={t('Setup')}
        hint={t('Put into the world when a run starts; the run stays in Preparing until they exist. Removed when the run ends unless permanent.')}>
        <EffectListEditor
          effects={draft.setup_effects}
          draft={draft}
          effectTypes={effectTypes}
          issues={issues}
          path="setup_effects"
          where={(j) => `setup:${j}`}
          setup
          placeholders={placeholders}
          onChange={(setup_effects) => set('setup_effects', setup_effects)}
          onStructureChange={onStructureChange}
        />
      </Field>
      <Field label={t('Rewards')}
        hint={t('Given to the avatar who finishes the last step; rewards always stay.')}>
        <EffectListEditor
          effects={draft.rewards}
          draft={draft}
          effectTypes={effectTypes}
          issues={issues}
          path="rewards"
          where={(j) => `reward:${j}`}
          reward
          placeholders={placeholders}
          onChange={(rewards) => set('rewards', rewards)}
          onStructureChange={onStructureChange}
        />
      </Field>
    </div>
  )

  const start = (
    <div className="ga-form">
      <Field label={t('Start condition')}
        hint={t('The quest opens for the player once this holds; until then it stays hidden.')}>
        <ConditionEditor expr={draft.start_condition} types={conditionTypes} roles={draft.roles} issues={issues}
          path="start_condition" onChange={(start_condition) => set('start_condition', start_condition)}
          onStructureChange={onStructureChange}
          targets={(p) => targetOptions(draft, 'start', p, effectTypes)}
          placeholders={placeholders} />
      </Field>
      <Field label={t('Requirements')}
        hint={t('A player who does not meet them sees the quest locked, with the text below as the reason.')}>
        <ConditionEditor expr={draft.prerequisites.condition} types={prerequisiteTypes} roles={draft.roles} issues={issues}
          path="prerequisites.condition"
          onChange={(condition) => set('prerequisites', { ...draft.prerequisites, condition })}
          onStructureChange={onStructureChange}
          targets={(p) => targetOptions(draft, 'prereq', p, effectTypes)}
          placeholders={placeholders} />
      </Field>
      <Field label={t('Locked text')}
        hint={<>{t('Empty: "You do not meet the requirements."')}{placeholderHint ? <><br />{placeholderHint}</> : null}</>}>
        <input className="ga-input ga-quest-locked" value={draft.prerequisites.locked_text}
          onChange={(e) => set('prerequisites', { ...draft.prerequisites, locked_text: e.target.value })} />
        <Alerts issues={issuesAt(issues, 'prerequisites.locked_text')} />
      </Field>
    </div>
  )

  return (
    <div className="ga-quest-form">
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
      {section === 'basics' ? basics : section === 'roles' ? roles : section === 'steps' ? steps : section === 'effects' ? effects : start}
    </div>
  )
}
