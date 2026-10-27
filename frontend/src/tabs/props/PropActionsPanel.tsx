import { useEffect, useState } from 'react'
import { apiGet } from '../../lib/api'
import { PropWorkspaceDialog } from './PropWorkspaceDialog'
import { PropActionChecks } from './PropActionChecks'
import { ActionField, ActionReference, GameDuration, PropActionEffects, PropActionRequirements, referenceLabel } from './PropActionEffects'
import { copyAction, createActionPreset, presentations, type ActionPreset } from './propActionAuthoring'
import type { ActionDefinition, PropActionIssue, PropFull } from './propTypes'
import type { PropWorkspace } from './usePropWorkspace'

const PRESETS: { id: ActionPreset; label: string; explanation: string }[] = [
  { id: 'sit', label: 'Sitzen / entspannen', explanation: 'Wach sitzen, bis die Person die Handlung beendet. Erholung als Rate aktiver Spielzeit.' },
  { id: 'lie', label: 'Hinlegen (wach)', explanation: 'Nur hinlegen, ohne Schlafzustand oder automatische Schlafregeneration.' },
  { id: 'sleep', label: 'Schlafen gehen', explanation: 'Echter Wach-zu-Schlaf-Übergang; Liegeplatz bleibt bis zum Aufwachen belegt.' },
  { id: 'coffee', label: 'Kaffee machen und trinken', explanation: 'Feste Phasen Zubereiten und Trinken; Erfolg erst nach dem Trinken, kein Item.' },
  { id: 'pair', label: 'Paarhandlung', explanation: 'Reale Paarfähigkeit mit zwei Cliprollen, gemeinsamer Geometrie und ausdrücklicher Zustimmung.' },
]
const ABILITIES = [
  { value: 'pose', label: 'Wache Haltung / Entspannung' }, { value: 'sleep', label: 'Echt einschlafen' },
  { value: 'combined', label: 'Kaffee zubereiten und trinken' }, { value: 'pair', label: 'Gemeinsame Paarfähigkeit' },
]

export function PropActionsPanel({ workspace, onIssue }: { workspace: PropWorkspace; onIssue: (issue: PropActionIssue) => void }) {
  const { t, actions, shownVariant, selectedActionId, setSelectedActionId, queueGeneral, queueVariant, variants, catalog, authoringIssues } = workspace
  const action = actions.find(item => item.id === selectedActionId) || actions[0]
  const index = action ? actions.findIndex(item => item.id === action.id) : -1
  const path = `actions.${index}`
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
  const available = action ? presentations(catalog, action.ability) : []
  const poseOptions = available.map(pose => ({ value: pose.key, label: pose.label_de || pose.label || t(referenceLabel(pose.key)) }))
  const binding = shownVariant?.action_bindings.find(item => item.action_id === action?.id)
  return <div className="ga-form prop-area-content prop-actions-panel">
    <div className="prop-action-toolbar"><h3>{t('Aktionen')}</h3>
      <button type="button" className="ga-btn ga-btn-primary ga-btn-sm" disabled={catalog.status !== 'ready'} onClick={() => setCreateOpen(true)}>{t('Aktion hinzufügen')}</button>
      <button type="button" className="ga-btn ga-btn-sm" onClick={() => setCopyOpen(true)}>{t('Von anderem Prop kopieren')}</button>
    </div>
    <p className="ga-hint">{t('Handlungen gelten für das gesamte Prop. Die ausgewählte Variante bestimmt nur Körperanker und Zugänge. Kopien sind unabhängig.')}</p>
    {catalog.status !== 'ready' && <p role="status">{t(catalog.status === 'loading' ? 'Aktionskataloge werden geladen.' : 'Aktionskataloge konnten nicht geladen werden. Speichern bleibt gesperrt.')} {catalog.status === 'error' && <button type="button" className="ga-btn ga-btn-sm" onClick={workspace.reloadActionCatalog}>{t('Erneut laden')}</button>}</p>}
    {!actions.length ? <p>{t('Keine Aktionen definiert. Dekorative Props benötigen keine Handlung.')}</p> : <>
      <ul className="prop-action-list" aria-label={t('Handlungen auswählen')}>
        {actions.map(item => <li key={item.id}><button type="button" className={`ga-btn${action?.id === item.id ? ' is-active ga-btn-primary' : ''}`} aria-pressed={action?.id === item.id}
          onClick={() => setSelectedActionId(item.id)}><strong>{item.name || t('Unbenannte Handlung')}</strong><span>{t(item.enabled ? 'Aktiviert' : 'Deaktiviert')} · {item.participants} {t('Personen')}</span></button></li>)}
      </ul>
      {action && <div className="prop-action-inspector">
        {authoringIssues.filter(issue => issue.path === path || issue.path.startsWith(`${path}.`)).length > 0 && <div className="prop-action-errors" role="alert">
          <strong>{t('Vor dem Speichern reparieren')}</strong><ul>{authoringIssues.filter(issue => issue.path === path || issue.path.startsWith(`${path}.`)).map(issue => <li key={`${issue.path}:${issue.code}`}><button type="button" className="ga-btn ga-btn-sm" onClick={() => onIssue(issue)}>{t(issue.message)}</button></li>)}</ul>
        </div>}
        <section className="prop-action-section"><h4>{t('Handlung')}</h4>
          <ActionField label={t('Name der Handlung')}><input className="ga-input" value={action.name} data-author-path={`${path}.name`} onChange={event => patch({ name: event.target.value })} /></ActionField>
          <ActionField label={t('Beschreibung für Spieler und NPCs')}><textarea className="ga-textarea" rows={3} value={action.description} data-author-path={`${path}.description`} onChange={event => patch({ description: event.target.value })} /></ActionField>
          <label className="ga-form-row"><input type="checkbox" checked={action.enabled} data-author-path={`${path}.enabled`} onChange={event => patch({ enabled: event.target.checked })} />{t('Handlung aktiviert')}</label>
          <div className="prop-action-grid"><ActionReference label={t('Ausführbare Fähigkeit')} path={`${path}.ability`} value={action.ability} options={ABILITIES.map(item => ({ ...item, label: t(item.label) }))}
            onChange={value => {
              const ability = value as ActionDefinition['ability']
              patch({ ability, participants: ability === 'pair' ? 2 : 1,
                phases: ability === 'combined' ? action.phases.length ? action.phases : createActionPreset('coffee', catalog).phases : [] })
              for (const variant of variants) if (variant.action_bindings.some(item => item.action_id === action.id)) queueVariant(variant.index, {
                action_bindings: variant.action_bindings.map(item => item.action_id === action.id ? { ...item, validation: 'repair_required' } : item),
              })
            }} />
            <ActionField label={t('Personen')}><select className="ga-input" value={action.participants} data-author-path={`${path}.participants`} onChange={event => {
              const participants = Number(event.target.value) as 1 | 2
              patch({ participants, ability: participants === 2 ? 'pair' : 'pose', phases: [] })
            }}><option value={1}>{t('Eine Person (Solo)')}</option><option value={2} disabled={!presentations(catalog, 'pair').length}>{t('Zwei Personen (reale Paarfähigkeit)')}</option></select></ActionField>
          </div>
          {action.ability === 'pair' && <p className="ga-hint">{t('Partnerperson wird zur Laufzeit gewählt. Kein Start vor exakter Zustimmung beider Personen. Ausführende Person und Partnerperson sind Wirkungsziele; die physischen Cliprollen A/B werden von der echten Paarfähigkeit zugeteilt.')}</p>}
        </section>
        <section className="prop-action-section"><h4>{t('Teilnehmer & Regeln')}</h4>
          <ActionReference value={action.presence} label={t('Anwesenheit im ganzen Raum')} path={`${path}.presence`} options={[
            { value: 'any', label: t('Unabhängig von anderen Personen') }, { value: 'alone', label: t('Nur allein') },
            { value: 'others', label: t('Mindestens eine weitere Person') }, { value: 'participants_only', label: t('Nur die Beteiligten') },
          ]} onChange={presence => patch({ presence: presence as ActionDefinition['presence'] })} />
          <p className="ga-hint">{t('Bei Ankunft immer prüfen. Schlafende zählen als Anwesende, sind aber keine verfügbaren Partner.')}</p>
          <label className="ga-form-row"><input type="checkbox" checked={action.interrupt_on_presence_change} data-author-path={`${path}.interrupt_on_presence_change`} onChange={event => patch({ interrupt_on_presence_change: event.target.checked })} />{t('Bei Regelverletzung während der Handlung unterbrechen')}</label>
          {action.ability === 'sleep' && action.interrupt_on_presence_change && <p className="ga-hint">{t('Eine verletzte laufende Regel kann diesen Schlaf ausdrücklich unterbrechen und aufwecken.')}</p>}
        </section>
        <PropActionRequirements action={action} catalog={catalog} path={path} onChange={requirements => patch({ requirements })} />
        <section className="prop-action-section"><h4>{t('Ablauf')}</h4>
          <p>{t('Zum Zugang hinlaufen, dort ausrichten und über den passenden Eintrittsübergang zum Körperanker wechseln. Ein fehlender Übergang sperrt die Ausführung; kein Teleport.')}</p>
          {action.ability === 'combined' ? <>
            <p className="ga-hint">{t('Fester Kaffeeablauf, kein Workflow-Editor: Zubereiten, danach Trinken. Nur vollständiges Trinken ist Erfolg. Abbruch gibt keinen Abschlussbonus und erzeugt kein Item.')}</p>
            {action.phases.map((phase, phaseIndex) => <fieldset key={phase.id} className="prop-action-row"><legend>{phaseIndex === 0 ? t('Zubereiten') : phaseIndex === 1 ? t('Trinken') : phase.label}</legend>
              <GameDuration label={t('Dauer der Phase')} value={phase.duration_game_s} path={`${path}.phases.${phaseIndex}.duration_game_s`} onChange={duration_game_s => patch({ phases: action.phases.map(item => item.id === phase.id ? { ...item, duration_game_s } : item) })} />
              <ActionReference label={t('Darstellung der Phase')} value={phase.pose_key} options={poseOptions} path={`${path}.phases.${phaseIndex}.pose_key`} onChange={pose_key => patch({ phases: action.phases.map(item => item.id === phase.id ? { ...item, pose_key } : item) })} />
            </fieldset>)}
            {action.phases.length !== 2 && <button type="button" className="ga-btn" onClick={() => setRepairPhases(true)}>{t('Festen Kaffeeablauf reparieren')}</button>}
          </> : <>
            <ActionReference label={t('Verfügbare Darstellung')} value={action.pose_key} options={poseOptions} path={`${path}.pose_key`} onChange={pose_key => patch({ pose_key })} />
            <p className="ga-hint">{t(action.ability === 'sleep'
              ? 'Erfolg beim echten Einschlafen, nicht nach Clipende. Schlafdauer und Erholung steuert die vorhandene Schlafmechanik. Platzbelegung endet beim echten Aufwachen.'
              : 'Dauer: bis ausdrücklich beendet. Normales Beenden ist kein Abschlussbonus; Weggehen und Regelverletzungen sind Abbruch. Bereits erarbeitete Erholung bleibt erhalten.')}</p>
          </>}
          {!available.length && catalog.status === 'ready' && <p role="alert">{t('Keine passende ausführbare Darstellung vorhanden. Im Posenbereich eine echte Fähigkeit mit verfügbaren Clips pflegen, danach Kataloge erneut laden.')}</p>}
        </section>
        <section className="prop-action-section"><h4>{t('Platzbindung dieser Variante')}</h4>
          <p>{!binding ? t('Keine Bindung für diese Variante. In Plätze & Zugänge zuordnen oder ausdrücklich nicht unterstützen.') : !binding.supported ? t('In dieser Variante ausdrücklich nicht unterstützt.') : t(binding.validation === 'repair_required' ? 'Bindung benötigt Reparatur.' : binding.validation === 'local_valid' ? 'Lokal geprüft; Raumweg und Anwesenheit nicht geprüft.' : 'Zugangsvorschlag; Raumweg und Anwesenheit nicht geprüft.')}</p>
          <button type="button" className="ga-btn" onClick={() => { setSelectedActionId(action.id); workspace.navigate('places') }}>{t('Im Modell bearbeiten')}</button>
        </section>
        <PropActionEffects action={action} catalog={catalog} path={path} onChange={effects => patch({ effects })} />
        <div className="prop-action-toolbar"><button type="button" className="ga-btn ga-btn-sm" onClick={() => { const next = copyAction(action); next.name = `${action.name} (${t('Kopie')})`; add(next) }}>{t('Unabhängige Kopie erstellen')}</button>
          <button type="button" className="ga-btn ga-btn-sm ga-btn-danger" onClick={() => setRemoveId(action.id)}>{t('Aktion entfernen')}</button></div>
      </div>}
    </>}
    <PropActionChecks workspace={workspace} onIssue={onIssue} />
    {createOpen && <PropWorkspaceDialog title={t('Ausführbare Vorlage wählen')} onCancel={() => setCreateOpen(false)}><div className="ga-modal-body prop-action-presets">
      {PRESETS.map(preset => {
        const ability = preset.id === 'coffee' ? 'combined' : preset.id === 'pair' ? 'pair' : preset.id === 'sleep' ? 'sleep' : 'pose'
        const possible = presentations(catalog, ability).some(pose => preset.id === 'sit' ? pose.group === 'seat' : preset.id === 'lie' || preset.id === 'sleep' ? pose.group === 'lie' : true)
        return <button type="button" key={preset.id} className="ga-btn" disabled={!possible} onClick={() => {
          const next = createActionPreset(preset.id, catalog)
          next.name = t(next.name)
          add(next); setCreateOpen(false)
        }}><strong>{t(preset.label)}</strong><span>{t(preset.explanation)}</span>{!possible && <span>{t('Keine passende Fähigkeit mit verfügbaren Clips vorhanden.')}</span>}</button>
      })}
    </div><div className="ga-modal-footer"><button type="button" className="ga-btn" onClick={() => setCreateOpen(false)}>{t('Cancel')}</button></div></PropWorkspaceDialog>}
    {copyOpen && <PropWorkspaceDialog title={t('Von anderem Prop kopieren')} onCancel={() => setCopyOpen(false)}><div className="ga-modal-body">
      <p>{t('Die neue Handlung bekommt eigene IDs und keine fremden Geometriebindungen. Änderungen am Original wirken nicht auf die Kopie.')}</p>
      {copyError && <p role="alert">{copyError}</p>}
      <ActionReference label={t('Quellobjekt')} path="copy.source" value={sourceId} options={sources.map(source => ({ value: source.id, label: source.name }))} onChange={setSourceId} />
      <ActionReference label={t('Zu kopierende Handlung')} path="copy.action" value={sourceActionId} options={sourceActions.map(source => ({ value: source.id, label: source.name }))} onChange={setSourceActionId} />
      {copyLoading && <p role="status">{t('Loading…')}</p>}{sourceId && !copyLoading && !sourceActions.length && <p>{t('Dieses Prop hat keine Aktionen.')}</p>}
    </div><div className="ga-modal-footer"><button type="button" className="ga-btn" onClick={() => setCopyOpen(false)}>{t('Cancel')}</button>
      <button type="button" className="ga-btn ga-btn-primary" disabled={copyLoading || !sourceActions.some(source => source.id === sourceActionId)} onClick={() => {
        const source = sourceActions.find(item => item.id === sourceActionId)
        if (source) { add(copyAction(source)); setCopyOpen(false) }
      }}>{t('Unabhängig übernehmen')}</button></div></PropWorkspaceDialog>}
    {removeId && <PropWorkspaceDialog title={t('Aktion und Bindungen entfernen?')} onCancel={() => setRemoveId('')}><div className="ga-modal-body">
      <p>{removeAction?.name || t('Diese Handlung wurde inzwischen entfernt.')}: {t('Diese Handlung und alle ihre variantengebundenen Zuordnungen werden gemeinsam im Entwurf entfernt. Die Körpermarker bleiben erhalten. Erst Speichern übernimmt die Änderung.')}</p>
      <ul>{variants.filter(variant => variant.action_bindings.some(item => item.action_id === removeId)).map(variant => <li key={variant.uid}>{variant.label || `${t('Variant')} ${variant.index + 1}`}</li>)}</ul>
    </div><div className="ga-modal-footer"><button type="button" className="ga-btn" onClick={() => setRemoveId('')}>{t('Cancel')}</button><button type="button" className="ga-btn ga-btn-danger" disabled={!removeAction} onClick={() => {
      queueGeneral({ actions: actions.filter(item => item.id !== removeId) })
      for (const variant of variants) if (variant.action_bindings.some(item => item.action_id === removeId)) queueVariant(variant.index, { action_bindings: variant.action_bindings.filter(item => item.action_id !== removeId) })
      setSelectedActionId(''); setRemoveId('')
    }}>{t('Handlung und Bindungen entfernen')}</button></div></PropWorkspaceDialog>}
    {repairPhases && action && <PropWorkspaceDialog title={t('Kaffeephasen ersetzen?')} onCancel={() => setRepairPhases(false)}><div className="ga-modal-body"><p>{t('Vorhandene Phasen werden ausdrücklich durch Zubereiten und Trinken ersetzt. Wirkungen und Voraussetzungen bleiben erhalten.')}</p></div><div className="ga-modal-footer"><button type="button" className="ga-btn" onClick={() => setRepairPhases(false)}>{t('Cancel')}</button><button type="button" className="ga-btn ga-btn-primary" onClick={() => { patch({ phases: createActionPreset('coffee', catalog).phases }); setRepairPhases(false) }}>{t('Ablauf ersetzen')}</button></div></PropWorkspaceDialog>}
  </div>
}
