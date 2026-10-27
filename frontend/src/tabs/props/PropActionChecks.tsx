import { useEffect, useMemo, useRef, useState } from 'react'
import { Field } from '@anima/player-ui'
import { ApiError, apiGet, apiPost } from '../../lib/api'
import type { PropActionIssue } from './propTypes'
import type { PropWorkspace } from './usePropWorkspace'
import { PropWorkspaceDialog } from './PropWorkspaceDialog'
import { composePropConfigurationResult, isCurrentPropConfigurationRequest,
  propActionCheckDocument, propCheckReason, resolveCheckIssue, samePropConfigurationSnapshot,
  type PropConfigurationResult, type PropConfigurationSnapshot, type PropConfigurationRequest,
  type PropCheckTargets, type PropPlacementCheckRequest,
  type PropPlacementCheckResult, type PropExecutionResult } from './propActionChecks'

interface CheckError { message: string; status?: number }

function checkError(error: unknown): CheckError {
  if (error instanceof ApiError) {
    const detail = error.detail
    const reason = detail && typeof detail === 'object' && 'reason' in detail
      ? String(detail.reason) : ''
    return { status: error.status, message: reason ? propCheckReason(reason)
      : typeof detail === 'string' ? detail
        : error.status === 422 ? 'Die Auswahl oder Konfiguration ist ungültig. Eingaben prüfen und erneut versuchen.'
          : error.status === 403 ? 'Für diese Prüfung sind Adminrechte erforderlich.'
            : error.status === 409 ? 'Die gespeicherte Platzierung oder Revision hat sich geändert. Aktualisieren und erneut prüfen.'
              : 'Die Anfrage konnte nicht abgeschlossen werden. Erneut versuchen.' }
  }
  return { message: error instanceof Error ? error.message : 'Die Anfrage ist fehlgeschlagen. Erneut versuchen.' }
}

/** No preview executor: document validation, saved preflight and real execution stay separate. */
export function PropActionChecks({ workspace, onIssue }: {
  workspace: PropWorkspace; onIssue: (issue: PropActionIssue) => void
}) {
  const { t, prop, variants, buf, catalog, selectedActionId, dirtyCount, saving, revisionReady } = workspace
  const document = useMemo(() => propActionCheckDocument(prop, variants, buf), [prop, variants, buf])
  const snapshot = useMemo<PropConfigurationSnapshot>(() => ({
    propId: prop.id, revision: prop.revision, document, catalog, revisionReady,
  }), [prop.id, prop.revision, document, catalog, revisionReady])
  const configurationRequest = useRef<PropConfigurationRequest>({ snapshot, sequence: 0 })
  if (!samePropConfigurationSnapshot(configurationRequest.current.snapshot, snapshot)) {
    configurationRequest.current = { snapshot, sequence: configurationRequest.current.sequence + 1 }
  }
  const [configuration, setConfiguration] = useState<{
    snapshot: PropConfigurationSnapshot; result: PropConfigurationResult
  } | null>(null)
  const [configurationError, setConfigurationError] = useState<{
    snapshot: PropConfigurationSnapshot; error: CheckError
  } | null>(null)
  const [validation, setValidation] = useState<PropConfigurationRequest | null>(null)
  const [locations, setLocations] = useState<{ id: string; name: string }[]>([])
  const [locationsLoaded, setLocationsLoaded] = useState(false)
  const [locationId, setLocationId] = useState('')
  const [targets, setTargets] = useState<PropCheckTargets | null>(null)
  const [roomId, setRoomId] = useState('')
  const [placementId, setPlacementId] = useState('')
  const [actor, setActor] = useState('')
  const [partner, setPartner] = useState('')
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [roomError, setRoomError] = useState<CheckError | null>(null)
  const [placementResult, setPlacementResult] = useState<{
    key: string; result: PropPlacementCheckResult
  } | null>(null)
  const [execution, setExecution] = useState<{
    key: string; result: PropExecutionResult
  } | null>(null)
  const [confirmation, setConfirmation] = useState<PropPlacementCheckRequest | null>(null)
  const sourceRequest = useRef(0)
  const activeProp = useRef(prop.id)
  activeProp.current = prop.id
  const path = `/world/props/${encodeURIComponent(prop.id)}`
  const room = targets?.rooms.find((entry) => entry.id === roomId)
  const placement = room?.placements.find((entry) => entry.target.placement_id === placementId)
  const savedAction = prop.actions.find((entry) => entry.id === selectedActionId)
  const pair = savedAction?.participants === 2
  const actorPresent = room?.persons.some((person) => person.name === actor && !person.sleeping)
  const partnerPresent = !pair || room?.persons.some((person) => person.name === partner && !person.sleeping && person.name !== actor)
  const request: PropPlacementCheckRequest | null = placement && savedAction && actorPresent && partnerPresent
    ? { target: placement.target, action_id: savedAction.id, revision: targets!.revision,
      actor, partner: pair ? partner : '' } : null
  const requestKey = request ? JSON.stringify(request) : ''
  const savedReady = !dirtyCount && !saving && revisionReady && targets?.revision === prop.revision
  const canCheck = !!request && savedReady && !loading && !busy
  const validating = !!validation && isCurrentPropConfigurationRequest(validation, configurationRequest.current)
  const currentConfiguration = configuration && samePropConfigurationSnapshot(configuration.snapshot, snapshot)
    ? configuration.result : null
  const currentConfigurationError = configurationError && samePropConfigurationSnapshot(configurationError.snapshot, snapshot)
    ? configurationError.error : null

  useEffect(() => {
    sourceRequest.current += 1
    setLocations([]); setLocationsLoaded(false); setLocationId(''); setTargets(null)
    setRoomId(''); setPlacementId(''); setActor(''); setPartner('')
    setConfiguration(null); setConfigurationError(null); setRoomError(null)
    setPlacementResult(null); setExecution(null); setConfirmation(null); setLoading(false)
  }, [prop.id])

  async function validateConfiguration() {
    if (!revisionReady) return
    const checked = { snapshot, sequence: configurationRequest.current.sequence + 1 }
    configurationRequest.current = checked
    setValidation(checked); setConfiguration(null); setConfigurationError(null)
    try {
      const result = await apiPost<PropConfigurationResult>(`${path}/validate`, { document: checked.snapshot.document })
      if (isCurrentPropConfigurationRequest(checked, configurationRequest.current)) {
        setConfiguration({ snapshot: checked.snapshot,
          result: composePropConfigurationResult(checked.snapshot.document, checked.snapshot.catalog, result) })
      }
    } catch (error) {
      if (isCurrentPropConfigurationRequest(checked, configurationRequest.current)) {
        setConfigurationError({ snapshot: checked.snapshot, error: checkError(error) })
      }
    } finally {
      if (isCurrentPropConfigurationRequest(checked, configurationRequest.current)) setValidation(null)
    }
  }

  async function loadLocations() {
    const token = ++sourceRequest.current
    setLoading(true); setRoomError(null)
    try {
      const result = await apiGet<{ locations: { id: string; name: string }[] }>('/world/locations')
      if (token === sourceRequest.current) {
        setLocations(result.locations); setLocationsLoaded(true)
      }
    } catch (error) {
      if (token === sourceRequest.current) setRoomError(checkError(error))
    } finally { if (token === sourceRequest.current) setLoading(false) }
  }

  async function loadTargets(id: string) {
    const token = ++sourceRequest.current
    setLocationId(id); setTargets(null); setRoomId(''); setPlacementId('')
    setActor(''); setPartner(''); setRoomError(null); setConfirmation(null)
    if (!id) { setLoading(false); return }
    setLoading(true)
    try {
      const result = await apiGet<PropCheckTargets>(`${path}/check-targets?location_id=${encodeURIComponent(id)}`)
      if (token === sourceRequest.current) setTargets(result)
    } catch (error) {
      if (token === sourceRequest.current) setRoomError(checkError(error))
    } finally { if (token === sourceRequest.current) setLoading(false) }
  }

  async function checkPlacement() {
    if (!canCheck || !request) return
    const propId = prop.id
    setBusy(true); setRoomError(null)
    try {
      const result = await apiPost<PropPlacementCheckResult>(`${path}/check-placement`, request)
      if (activeProp.current === propId) setPlacementResult({ key: requestKey, result })
    } catch (error) {
      if (activeProp.current === propId) setRoomError(checkError(error))
    } finally { setBusy(false) }
  }

  async function execute() {
    if (!canCheck || !confirmation || JSON.stringify(confirmation) !== requestKey) return
    const propId = prop.id, confirmed = confirmation
    setConfirmation(null); setBusy(true); setRoomError(null)
    try {
      const result = await apiPost<PropExecutionResult>(`${path}/execute-test`, {
        ...confirmed, confirmed: true, request_id: crypto.randomUUID(),
      })
      if (activeProp.current === propId) {
        setExecution({ key: requestKey, result }); setPlacementResult(null)
      }
    } catch (error) {
      if (activeProp.current === propId) setRoomError(checkError(error))
    } finally { setBusy(false) }
  }

  return <section className="prop-inspector-group" aria-label={t('Prüfung und echte Ausführung')}>
    <h3>{t('Prüfung')}</h3>
    <p className="ga-hint">{t('Konfiguration prüfen liest den gesamten aktuellen Entwurf mit allen Varianten. Es wird nichts gespeichert und kein Weltwert verändert.')}</p>
    <button type="button" className="ga-btn ga-btn-sm" disabled={validating || !revisionReady}
      onClick={() => { void validateConfiguration() }}>{t(validating ? 'Konfiguration wird geprüft…' : 'Konfiguration prüfen')}</button>
    {currentConfigurationError && <p role="alert">{currentConfigurationError.status ? `HTTP ${currentConfigurationError.status}: ` : ''}{t(currentConfigurationError.message)}</p>}
    {!revisionReady && <p className="ga-hint">{t('Vollständige Varianten und konsistente Revision abwarten; Ladefehler im Arbeitsbereich beheben.')}</p>}
    {configuration && !currentConfiguration && <p role="status">{t('Der Entwurf wurde seit der Prüfung verändert. Bitte erneut prüfen.')}</p>}
    {currentConfiguration && <div role="status">
      <p>{t(currentConfiguration.valid ? 'Konfiguration gültig' : 'Konfiguration enthält Fehler')}</p>
      <p className="ga-hint">{t('Raumweg, Eintritt und Anwesenheit: nicht geprüft. Dafür ist eine tatsächliche gespeicherte Platzierung erforderlich.')}</p>
      <ul>{currentConfiguration.issues.map((issue, index) => {
        const location = resolveCheckIssue(issue, document)
        const action = workspace.actions.find((entry) => entry.id === location.actionId)
        const variant = variants.find((entry) => entry.uid === location.variantUid)
        return <li key={`${issue.path}-${issue.code}-${index}`}>
          <button type="button" className="ga-btn ga-btn-sm" onClick={() => onIssue(issue)}>
            {t(issue.severity === 'error' ? 'Fehler' : 'Warnung')}: {t(issue.message)}
            {action ? ` · ${action.name}` : ''}{variant ? ` · ${t('Variante')} ${variant.index + 1}` : ''}
            {location.field ? ` · ${t(location.field.includes('access_points') ? 'Zugang' : location.field.includes('marker_ids') ? 'Körperanker' : location.field.includes('requirements') ? 'Voraussetzung' : location.field.includes('effects') ? 'Wirkung' : location.field.includes('phases') ? 'Ablauf' : 'Konfiguration')}` : ''}
          </button>
        </li>
      })}</ul>
    </div>}

    <h3>{t('Im Raum prüfen')}</h3>
    <p className="ga-hint">{t('Nur gespeicherte Konfiguration. Diese Prüfung reserviert keinen Platz, bewegt niemanden und verändert keine Werte. Sie meldet den ersten tatsächlichen Sperrgrund; spätere Prüfungen sind damit nicht als bestanden bestätigt.')}</p>
    {dirtyCount > 0 && <p role="status">{t('Der Entwurf ist ungespeichert. Zuerst mit Speichern im Arbeitsbereich übernehmen oder bewusst verwerfen; Raumprüfung und Ausführung bleiben gesperrt.')}</p>}
    <button type="button" className="ga-btn ga-btn-sm" disabled={loading || busy}
      onClick={() => { void loadLocations() }}>{t(locationsLoaded ? 'Orte aktualisieren' : 'Gespeicherte Orte laden')}</button>
    {locationsLoaded && !locations.length && <p>{t('Keine gespeicherten Orte vorhanden.')}</p>}
    {locationsLoaded && <Field label={t('Gespeicherter Ort')}>
      <select aria-label={t('Gespeicherter Ort')} className="ga-input" value={locationId}
        disabled={loading || busy} onChange={(event) => { void loadTargets(event.target.value) }}>
        <option value="">{t('Ort wählen')}</option>
        {locations.map((entry) => <option key={entry.id} value={entry.id}>{entry.name}</option>)}
      </select>
    </Field>}
    {locationId && <button type="button" className="ga-btn ga-btn-sm" disabled={loading || busy}
      onClick={() => { void loadTargets(locationId) }}>{t('Platzierungen und Personen aktualisieren')}</button>}
    {loading && <p role="status">{t('Gespeicherte Daten werden gelesen…')}</p>}
    {targets && !targets.rooms.length && <p>{t('An diesem Ort gibt es keine tatsächlich auflösbare Platzierung dieses Props mit Körperankern. Prop im Raum platzieren, Variante und Marker reparieren; der Ort benötigt eine Weltposition. Danach aktualisieren.')}</p>}
    {targets && targets.rooms.length > 0 && <>
      <Field label={t('Tatsächlicher Raum')}>
        <select aria-label={t('Tatsächlicher Raum')} className="ga-input" value={roomId} disabled={busy || loading}
          onChange={(event) => { setRoomId(event.target.value); setPlacementId(''); setActor(''); setPartner(''); setConfirmation(null) }}>
          <option value="">{t('Raum wählen')}</option>
          {targets.rooms.map((entry) => <option key={entry.id} value={entry.id}>{entry.name}</option>)}
        </select>
      </Field>
      {room && <>
        <Field label={t('Gespeicherte Platzierung')}>
          <select aria-label={t('Gespeicherte Platzierung')} className="ga-input" value={placementId} disabled={busy || loading}
            onChange={(event) => { setPlacementId(event.target.value); setConfirmation(null) }}>
            <option value="">{t('Platzierung wählen')}</option>
            {room.placements.map(({ target }, index) => {
              const variant = variants.find((entry) => entry.uid === target.variant_uid)
              return <option key={target.placement_id} value={target.placement_id}>
                {t('Platzierung')} {index + 1} · {variant ? `${t('Variante')} ${variant.index + 1}` : t('Variante nicht mehr verfügbar')}
              </option>
            })}
          </select>
        </Field>
        <Field label={t('Ausführende Person im Raum')}>
          <select aria-label={t('Ausführende Person im Raum')} className="ga-input" value={actor} disabled={busy || loading}
            onChange={(event) => { setActor(event.target.value); setPartner(''); setConfirmation(null) }}>
            <option value="">{t('Person wählen')}</option>
            {room.persons.map((person) => <option key={person.name} value={person.name} disabled={person.sleeping}>
              {person.name}{person.sleeping ? ` · ${t('schläft; zählt als anwesend')}` : ''}
            </option>)}
          </select>
        </Field>
        {!room.persons.length && <p>{t('Keine tatsächlichen Personen in diesem Raum. Hier werden keine Testpersonen erzeugt oder versetzt.')}</p>}
        {pair && <Field label={t('Partnerperson im Raum')}>
          <select aria-label={t('Partnerperson im Raum')} className="ga-input" value={partner} disabled={busy || loading}
            onChange={(event) => { setPartner(event.target.value); setConfirmation(null) }}>
            <option value="">{t('Partnerperson wählen')}</option>
            {room.persons.filter((person) => person.name !== actor).map((person) => <option key={person.name} value={person.name} disabled={person.sleeping}>
              {person.name}{person.sleeping ? ` · ${t('schläft; nicht verfügbar')}` : ''}
            </option>)}
          </select>
        </Field>}
      </>}
    </>}
    <p>{t('Gewählte gespeicherte Handlung')}: {savedAction?.name || t('Aktion auswählen und gegebenenfalls speichern')}</p>
    {targets && targets.revision !== prop.revision && <p role="status">{t('Prüfdaten und Arbeitsbereich haben verschiedene gespeicherte Revisionen. Arbeitsbereich und Platzierungen aktualisieren; kein Entwurf wird überschrieben.')}</p>}
    <button type="button" className="ga-btn ga-btn-sm" disabled={!canCheck}
      onClick={() => { void checkPlacement() }}>{t(busy ? 'Anfrage läuft…' : 'Im Raum prüfen (nur lesen)')}</button>
    {roomError && <p role="alert">{roomError.status ? `HTTP ${roomError.status}: ` : ''}{t(roomError.message)}</p>}
    {placementResult?.key === requestKey && savedReady && <div role="status">
      <p>{t(placementResult.result.enabled ? 'Aktuell ausführbar: Verfügbarkeit, Weg und Eintritt geprüft. Keine Ausführung gestartet.' : 'Aktuell gesperrt')}</p>
      {placementResult.result.reason && <p>{t(propCheckReason(placementResult.result.reason))}</p>}
      <p className="ga-hint">{t('Momentaufnahme, keine Reservierung. Beim echten Start und bei Ankunft gelten erneut die normalen Regeln; Paarzustimmung wurde nicht erteilt.')}</p>
    </div>}

    <h3>{t('Echte Ausführung')}</h3>
    <p className="ga-hint">{t('Keine Vorschau: Die Handlung läuft in der Welt, bewegt echte Personen und kann Werte, Stimmung, Schlaf und Zustände verändern. Paarhandlungen fragen die gewählte Partnerperson nach normaler ausdrücklicher Zustimmung. Es gibt keinen Admin-Bypass.')}</p>
    <button type="button" className="ga-btn ga-btn-sm ga-btn-danger" disabled={!canCheck}
      onClick={() => setConfirmation(request)}>{t('Handlung in der Welt ausführen…')}</button>
    {execution?.key === requestKey && <div role="status">
      <p>{t('Serverstatus')}: {t(({ awaiting_consent: 'Wartet auf ausdrückliche Partnerzustimmung', approaching: 'Hinlaufen / Eintritt', active: 'Aktiv', sleeping: 'Echter Schlaf', completed: 'Abgeschlossen', cancelled: 'Abgebrochen', failed: 'Fehlgeschlagen', refused: 'Abgelehnt' } as Record<string, string>)[execution.result.status] || execution.result.status)}</p>
      {execution.result.reason && <p>{t(propCheckReason(execution.result.reason))}</p>}
      {execution.result.execution_id && <p className="ga-hint">{t('Ausführungs-ID')}: {execution.result.execution_id}</p>}
      <p className="ga-hint">{t('Dies ist die Antwort auf den Start, kein fortlaufender Status. Zustimmung, Beenden und Abbrechen erfolgen über die normalen Spieloberflächen der Beteiligten.')}</p>
    </div>}
    {confirmation && <PropWorkspaceDialog title={t('Handlung wirklich in der Welt ausführen?')} onCancel={() => setConfirmation(null)}>
      <div className="ga-form">
        <p>{savedAction?.name} · {confirmation.actor}{confirmation.partner ? ` + ${confirmation.partner}` : ''}</p>
        <p>{room?.name} · {t('Platzierung')} {(room?.placements.findIndex(entry => entry.target.placement_id === confirmation.target.placement_id) ?? -1) + 1}</p>
        <p>{t('Diese echte Handlung kann Werte und Zustände dauerhaft ändern, Personen bewegen oder echten Schlaf beginnen. Es werden die gespeicherte Definition und normale Regeln verwendet. Bei Paaren ist die Zustimmung der Partnerperson weiterhin erforderlich.')}</p>
        {(!canCheck || JSON.stringify(confirmation) !== requestKey) && <p role="alert">{t('Auswahl oder Entwurf wurde verändert. Abbrechen, Daten aktualisieren und erneut bestätigen.')}</p>}
        <div className="ga-modal-actions">
          <button type="button" className="ga-btn" onClick={() => setConfirmation(null)}>{t('Abbrechen')}</button>
          <button type="button" className="ga-btn ga-btn-danger" disabled={!canCheck || JSON.stringify(confirmation) !== requestKey}
            onClick={() => { void execute() }}>{t('Ja, echte Handlung ausführen')}</button>
        </div>
      </div>
    </PropWorkspaceDialog>}
  </section>
}
