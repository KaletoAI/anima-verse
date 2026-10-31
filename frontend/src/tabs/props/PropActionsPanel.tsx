import { useEffect, useState } from 'react'
import { apiGet } from '../../lib/api'
import { PropWorkspaceDialog } from './PropWorkspaceDialog'
import { PropActionChecks } from './PropActionChecks'
import { ActionField, ActionReference, GameDuration, PropActionEffects, PropActionRequirements, referenceLabel } from './PropActionEffects'
import { copyAction, createActionPreset, presentations, type ActionPreset } from './propActionAuthoring'
import { draftValue, GENERAL_TARGET } from './pendingFields'
import type { ActionDefinition, PropActionIssue, PropFull } from './propTypes'
import type { PropWorkspace } from './usePropWorkspace'

const PRESETS: { id: ActionPreset; label: string; explanation: string }[] = [
  { id: 'sit', label: 'Sit / relax', explanation: 'Sit awake until the person ends the action. Recovery applies as a rate over active game time.' },
  { id: 'lie', label: 'Lie down (awake)', explanation: 'Lie down without entering sleep or receiving automatic sleep recovery.' },
  { id: 'sleep', label: 'Go to sleep', explanation: 'Actual transition into sleep; the place stays occupied until waking up.' },
  { id: 'coffee', label: 'Make and drink coffee', explanation: 'Fixed preparation and drinking phases; success only after drinking, no item.' },
  { id: 'pair', label: 'Pair action', explanation: 'An actual pair ability with two clip roles, shared geometry and explicit consent.' },
]

export function PropActionsPanel({ workspace, onIssue }: { workspace: PropWorkspace; onIssue: (issue: PropActionIssue) => void }) {
  const { t, actions, shownVariant, selectedActionId, setSelectedActionId, queueGeneral, queueVariant, variants, catalog, authoringIssues } = workspace
  const action = actions.find(item => item.id === selectedActionId) || actions[0]
  const index = action ? actions.findIndex(item => item.id === action.id) : -1
  const path = `actions.${index}`
  const [checksOpen, setChecksOpen] = useState(false)
  const [createOpen, setCreateOpen] = useState(false)
  const [copyOpen, setCopyOpen] = useState(false)
  const [removeId, setRemoveId] = useState('')
  const removeAction = actions.find(item => item.id === removeId)
  const [repairPhases, setRepairPhases] = useState(false)
  const [sources, setSources] = useState<PropFull[]>([])
  const [sourceId, setSourceId] = useState('')
  const [sourceActions, setSourceActions] = useState<ActionDefinition[]>([])
  const [sourceActionId, setSourceActionId] = useState('')
  const [copyError, setCopyError] = useState('')
  const [copyLoading, setCopyLoading] = useState(false)
  useEffect(() => {
    if (!copyOpen) return
    let alive = true
    setCopyLoading(true); setCopyError('')
    apiGet<{ props: PropFull[] }>('/world/props').then(result => {
      if (alive) setSources(result.props.filter(item => item.id !== workspace.prop.id))
    }).catch(error => { if (alive) setCopyError((error as Error).message) })
      .finally(() => { if (alive) setCopyLoading(false) })
    return () => { alive = false }
  }, [copyOpen, workspace.prop.id])
  useEffect(() => {
    setSourceActions([]); setSourceActionId('')
    if (!copyOpen || !sourceId) return
    let alive = true
    setCopyLoading(true); setCopyError('')
    apiGet<{ prop: PropFull }>(`/world/props/${encodeURIComponent(sourceId)}`).then(result => {
      if (alive) { setSourceActions(result.prop.actions || []); setSourceActionId(result.prop.actions?.[0]?.id || '') }
    }).catch(error => { if (alive) setCopyError((error as Error).message) })
      .finally(() => { if (alive) setCopyLoading(false) })
    return () => { alive = false }
  }, [copyOpen, sourceId])
  const patch = (change: Partial<ActionDefinition>) => {
    if (action) queueGeneral({ actions: actions.map(item => item.id === action.id ? { ...item, ...change } : item) })
  }
  const add = (next: ActionDefinition) => {
    queueGeneral({ actions: [...actions, next] }); setSelectedActionId(next.id)
  }
  const available = action ? presentations(catalog, action.participants === 2 ? 'pair' : 'pose') : []
  const poseOptions = available.map(pose => ({ value: pose.key, label: pose.label || t(referenceLabel(pose.key)) }))
  const binding = (workspace.derivedBindings[shownVariant?.uid || ''] || []).find(item => item.action_id === action?.id)
  // Package actions are listed, never drafted: the one thing the author
  // decides here is whether THIS furniture offers them (exclude_actions).
  const excluded = draftValue<string[]>(workspace.buf, GENERAL_TARGET, 'exclude_actions', workspace.prop.exclude_actions || [])
  return <div className="ga-form prop-area-content prop-actions-panel">
    <div className="prop-action-toolbar"><h3>{t('Actions')}</h3>
      <button type="button" className="ga-btn ga-btn-primary ga-btn-sm" disabled={catalog.status !== 'ready'} onClick={() => setCreateOpen(true)}>{t('Add action')}</button>
    </div>
    <p className="ga-hint">{t('Actions automatically use matching places on every variant. Copies are independent.')}</p>
    {catalog.status !== 'ready' && <p role="status">{t(catalog.status === 'loading' ? 'Loading action catalogs.' : 'Could not load action catalogs. Saving remains disabled.')} {catalog.status === 'error' && <button type="button" className="ga-btn ga-btn-sm" onClick={workspace.reloadActionCatalog}>{t('Reload')}</button>}</p>}
    {!actions.length ? <p>{t('No actions defined. Decorative props do not need actions.')}</p> : <>
      <ul className="prop-action-list" aria-label={t('Select actions')}>
        {actions.map(item => <li key={item.id}><button type="button" className={`ga-btn${action?.id === item.id ? ' is-active ga-btn-primary' : ''}`} aria-pressed={action?.id === item.id}
          onClick={() => setSelectedActionId(item.id)}><strong>{item.name || t('Unnamed action')}</strong><span>{t(item.enabled ? 'Enabled' : 'Disabled')} · {item.participants} {t('People')}</span></button></li>)}
      </ul>
      {action && <div className="prop-action-inspector">
        {authoringIssues.filter(issue => issue.path === path || issue.path.startsWith(`${path}.`)).length > 0 && <div className="prop-action-errors" role="alert">
          <strong>{t('Repair before saving')}</strong><ul>{authoringIssues.filter(issue => issue.path === path || issue.path.startsWith(`${path}.`)).map(issue => <li key={`${issue.path}:${issue.code}`}><button type="button" className="ga-btn ga-btn-sm" onClick={() => onIssue(issue)}>{t(issue.message)}</button></li>)}</ul>
      </div>}
        <section className="prop-action-section"><h4>{t('Action')}</h4>
          <ActionField label={t('Name')}><input className="ga-input" value={action.name} data-author-path={`${path}.name`} onChange={event => patch({ name: event.target.value })} /></ActionField>
          <ActionField label={t('Description for players and NPCs')}><textarea className="ga-textarea" rows={3} value={action.description} data-author-path={`${path}.description`} onChange={event => patch({ description: event.target.value })} /></ActionField>
          <label className="ga-form-row"><input type="checkbox" checked={action.enabled} data-author-path={`${path}.enabled`} onChange={event => patch({ enabled: event.target.checked })} />{t('Enabled')}</label>
          <ActionReference label={t('Pose')} path={`${path}.pose_key`} value={action.ability === 'combined' ? action.phases[0]?.pose_key || '' : action.pose_key}
            options={poseOptions} onChange={pose_key => patch(action.ability === 'combined'
              ? { pose_key, phases: action.phases.map((phase, i) => i === 0 ? { ...phase, pose_key } : phase) }
              : { pose_key, ability: action.participants === 2 ? 'pair' : action.ability === 'sleep' && catalog.poses.find(pose => pose.key === pose_key)?.group === 'lie' ? 'sleep' : 'pose' })} />
          <ActionField label={t('Persons')}><select className="ga-input" value={action.participants} data-author-path={`${path}.participants`} onChange={event => {
            const participants = Number(event.target.value) as 1 | 2
            const ability = participants === 2 ? 'pair' : 'pose'
            const choices = presentations(catalog, ability)
            patch({ participants, ability, phases: [], pose_key: choices.some(pose => pose.key === action.pose_key) ? action.pose_key : choices[0]?.key || '' })
          }}><option value={1}>1</option><option value={2} disabled={!presentations(catalog, 'pair').length}>2</option></select></ActionField>
          {action.participants === 1 && action.ability !== 'combined' && catalog.poses.find(pose => pose.key === action.pose_key)?.group === 'lie' &&
            <label className="ga-form-row"><input type="checkbox" checked={action.ability === 'sleep'} onChange={event => patch({ ability: event.target.checked ? 'sleep' : 'pose' })} />{t('Really fall asleep')}</label>}
        </section>
        <section className="prop-action-section">
          <ActionReference value={action.presence} label={t('Who may be in the room')} path={`${path}.presence`} options={[
            { value: 'any', label: t('Anyone') }, { value: 'alone', label: t('Only alone') },
            { value: 'others', label: t('At least one other person') }, { value: 'participants_only', label: t('Only the participants') },
          ]} onChange={presence => patch({ presence: presence as ActionDefinition['presence'] })} />
        </section>
        <p className="ga-hint">{t('Applies to:')} {binding?.marker_ids.length || 0} {t('places on this variant')}{binding?.marker_ids.length ? ` (${Object.entries((shownVariant?.markers || []).filter(marker => binding.marker_ids.includes(marker.id || '')).reduce<Record<string, number>>((counts, marker) => { counts[marker.group] = (counts[marker.group] || 0) + 1; return counts }, {})).map(([group, count]) => `${group} x${count}`).join(', ')})` : ''}</p>
        <PropActionEffects action={action} catalog={catalog} path={path} onChange={effects => patch({ effects })} />
        <details className="prop-inspector-group"><summary>{t('Advanced')}</summary>
          {action.ability === 'pair' && <p className="ga-hint">{t('The partner is chosen at runtime. Both people must explicitly consent before starting. Actor and partner are effect targets; the pair ability assigns the physical A/B clip roles.')}</p>}
          {action.presence !== 'any' && <>
            <label className="ga-form-row"><input type="checkbox" checked={action.interrupt_on_presence_change} data-author-path={`${path}.interrupt_on_presence_change`} onChange={event => patch({ interrupt_on_presence_change: event.target.checked })} />{t('Cancel if presence changes during the action')}</label>
            <p className="ga-hint">{t('With “Only alone”, someone entering the room ends the action; a sleeping person wakes up.')}</p>
          </>}
          <p className="ga-hint">{t('Always checked on arrival. Sleeping people count as present but are not available partners.')}</p>
        <PropActionRequirements action={action} catalog={catalog} path={path} onChange={requirements => patch({ requirements })} onReloadCatalog={workspace.reloadActionCatalog} />
        <section className="prop-action-section"><h4>{t('Action flow')}</h4>
          <p>{t('Walk to the access point, align there and use the matching entry transition to reach the body anchor. A missing transition blocks execution; no teleporting.')}</p>
          {action.ability === 'combined' ? <>
            <p className="ga-hint">{t('Fixed coffee flow: prepare, then drink. Only finishing the drink counts as success. Cancellation gives no completion bonus and creates no item.')}</p>
            {action.phases.map((phase, phaseIndex) => <fieldset key={phase.id} className="prop-action-row"><legend>{phaseIndex === 0 ? t('Prepare') : phaseIndex === 1 ? t('Drink') : phase.label}</legend>
              <GameDuration label={t('Phase duration')} value={phase.duration_game_s} path={`${path}.phases.${phaseIndex}.duration_game_s`} onChange={duration_game_s => patch({ phases: action.phases.map(item => item.id === phase.id ? { ...item, duration_game_s } : item) })} />
              <ActionReference label={t('Phase presentation')} value={phase.pose_key} options={poseOptions} path={`${path}.phases.${phaseIndex}.pose_key`} onChange={pose_key => patch({ phases: action.phases.map(item => item.id === phase.id ? { ...item, pose_key } : item) })} />
            </fieldset>)}
            {action.phases.length !== 2 && <button type="button" className="ga-btn" onClick={() => setRepairPhases(true)}>{t('Repair fixed coffee flow')}</button>}
          </> : null}
          {!available.length && catalog.status === 'ready' && <p role="alert">{t('No matching executable presentation is available. Configure an actual ability with available clips in Poses, then reload catalogs.')}</p>}
        </section>
        <button type="button" className="ga-btn ga-btn-sm" onClick={() => setCopyOpen(true)}>{t('Copy from another prop')}</button>
        <div className="prop-action-toolbar"><button type="button" className="ga-btn ga-btn-sm" onClick={() => { const next = copyAction(action); next.name = `${action.name} (${t('Copy')})`; add(next) }}>{t('Create independent copy')}</button>
          <button type="button" className="ga-btn ga-btn-sm ga-btn-danger" onClick={() => setRemoveId(action.id)}>{t('Remove action')}</button></div>
        </details>
      </div>}
    </>}
    {workspace.packActions.length > 0 && <section className="prop-action-section prop-pack-actions"><h4>{t('From packages')}</h4>
      <p className="ga-hint">{t('An installed package adds these actions to every prop with a matching place. They are not stored in this prop and are not exported with it.')}</p>
      <ul className="prop-action-list" aria-label={t('From packages')}>
        {workspace.packActions.map(pack => {
          const off = excluded.includes(pack.id)
          const places = (workspace.derivedBindings[shownVariant?.uid || ''] || []).find(item => item.action_id === pack.id)?.marker_ids.length || 0
          return <li key={pack.id} className="prop-pack-action">
            <div><strong>{pack.name}</strong> <span className="ga-hint">{t('From package')} {pack.package_label} · {pack.participants} {t('People')}</span></div>
            <label className="ga-form-row"><input type="checkbox" checked={!off}
              onChange={event => queueGeneral({ exclude_actions: event.target.checked ? excluded.filter(id => id !== pack.id) : [...excluded, pack.id] })} />{t('Offer on this furniture')}</label>
            {!off && <p className="ga-hint">{t('Applies to:')} {places} {t('places on this variant')}</p>}
          </li>
        })}
      </ul>
    </section>}
    {!action && <details className="prop-inspector-group"><summary>{t('Advanced')}</summary>
      <button type="button" className="ga-btn ga-btn-sm" onClick={() => setCopyOpen(true)}>{t('Copy from another prop')}</button>
    </details>}
    <details className="prop-inspector-group" onToggle={event => setChecksOpen(event.currentTarget.open)}>
      <summary>{t('Test in room')}</summary>
      {checksOpen && <PropActionChecks workspace={workspace} onIssue={onIssue} />}
    </details>
    {createOpen && <PropWorkspaceDialog title={t('Choose executable preset')} onCancel={() => setCreateOpen(false)}><div className="ga-modal-body prop-action-presets">
      {PRESETS.map(preset => {
        const ability = preset.id === 'coffee' ? 'combined' : preset.id === 'pair' ? 'pair' : preset.id === 'sleep' ? 'sleep' : 'pose'
        const possible = preset.id === 'coffee' || presentations(catalog, ability).some(pose => preset.id === 'sit' ? pose.group === 'seat' : preset.id === 'lie' || preset.id === 'sleep' ? pose.group === 'lie' : true)
        return <button type="button" key={preset.id} className="ga-btn" disabled={!possible} onClick={() => {
          const next = createActionPreset(preset.id, catalog)
          next.name = t(next.name)
          add(next); setCreateOpen(false)
        }}><strong>{t(preset.label)}</strong><span>{t(preset.explanation)}</span>{preset.id === 'coffee' && <span>{t('Missing phase presentations remain visible as repair errors; no replacement action is chosen.')}</span>}{!possible && <span>{t('No matching ability with available clips.')}</span>}</button>
      })}
    </div><div className="ga-modal-footer"><button type="button" className="ga-btn" onClick={() => setCreateOpen(false)}>{t('Cancel')}</button></div></PropWorkspaceDialog>}
    {copyOpen && <PropWorkspaceDialog title={t('Copy from another prop')} onCancel={() => setCopyOpen(false)}><div className="ga-modal-body">
      <p>{t('The new action gets its own IDs and automatically uses matching places. Changes to the original do not affect the copy.')}</p>
      {copyError && <p role="alert">{copyError}</p>}
      <ActionReference label={t('Source prop')} path="copy.source" value={sourceId} options={sources.map(source => ({ value: source.id, label: source.name }))} onChange={setSourceId} />
      <ActionReference label={t('Action to copy')} path="copy.action" value={sourceActionId} options={sourceActions.map(source => ({ value: source.id, label: source.name }))} onChange={setSourceActionId} />
      {copyLoading && <p role="status">{t('Loading…')}</p>}{sourceId && !copyLoading && !sourceActions.length && <p>{t('This prop has no actions.')}</p>}
    </div><div className="ga-modal-footer"><button type="button" className="ga-btn" onClick={() => setCopyOpen(false)}>{t('Cancel')}</button>
      <button type="button" className="ga-btn ga-btn-primary" disabled={copyLoading || !sourceActions.some(source => source.id === sourceActionId)} onClick={() => {
        const source = sourceActions.find(item => item.id === sourceActionId)
        if (source) { add(copyAction(source)); setCopyOpen(false) }
      }}>{t('Copy independently')}</button></div></PropWorkspaceDialog>}
    {removeId && <PropWorkspaceDialog title={t('Remove action?')} onCancel={() => setRemoveId('')}><div className="ga-modal-body">
      <p>{removeAction?.name || t('This action has already been removed.')}: {t('This action and its exclusions are removed in the draft. Save to apply the change.')}</p>
    </div><div className="ga-modal-footer"><button type="button" className="ga-btn" onClick={() => setRemoveId('')}>{t('Cancel')}</button><button type="button" className="ga-btn ga-btn-danger" disabled={!removeAction} onClick={() => {
      queueGeneral({ actions: actions.filter(item => item.id !== removeId) })
      for (const variant of variants) queueVariant(variant.index, { markers: variant.markers.map(marker => ({ ...marker, exclude_actions: marker.exclude_actions?.filter(id => id !== removeId) })) })
      setSelectedActionId(''); setRemoveId('')
    }}>{t('Remove action')}</button></div></PropWorkspaceDialog>}
    {repairPhases && action && <PropWorkspaceDialog title={t('Replace coffee phases?')} onCancel={() => setRepairPhases(false)}><div className="ga-modal-body"><p>{t('Existing phases will be replaced by preparation and drinking. Effects and requirements are kept.')}</p></div><div className="ga-modal-footer"><button type="button" className="ga-btn" onClick={() => setRepairPhases(false)}>{t('Cancel')}</button><button type="button" className="ga-btn ga-btn-primary" onClick={() => { patch({ phases: createActionPreset('coffee', catalog).phases }); setRepairPhases(false) }}>{t('Replace flow')}</button></div></PropWorkspaceDialog>}
  </div>
}
