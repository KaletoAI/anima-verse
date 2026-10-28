import { useEffect, useMemo, useRef, useState } from 'react'
import { Field } from '@anima/player-ui'
import { ApiError, apiGet, apiPost } from '../../lib/api'
import type { PropActionIssue } from './propTypes'
import type { PropWorkspace } from './usePropWorkspace'
import { composePropConfigurationResult, isCurrentPropConfigurationRequest,
  propActionCheckDocument, propCheckReason, resolveCheckIssue, samePropConfigurationSnapshot,
  type PropConfigurationResult, type PropConfigurationSnapshot, type PropConfigurationRequest,
  type PropCheckTargets, type PropPlacementCheckRequest,
  type PropPlacementCheckResult } from './propActionChecks'

interface CheckError { message: string; status?: number }

interface CorePlan {
  waypoints: [number, number][]
  access: { x: number; z: number; yaw: number }
  entry_anchor: { x: number; y: number; z: number; marker_id: string; slot: number }
}
function CorePlans({ plans, t }: { plans?: Record<string, CorePlan>; t: (text: string) => string }) {
  if (!plans || !Object.keys(plans).length) return null
  return <details><summary>{t('Computed Core paths and entry targets')}</summary>
    <p className="ga-hint">{t('World X/Z coordinates in metres. The line shows the computed walking path. Access and body anchor are separate targets; no straight entry path is assumed between them.')}</p>
    {Object.entries(plans).map(([role, plan]) => {
      const points = [...plan.waypoints, [plan.access.x, plan.access.z], [plan.entry_anchor.x, plan.entry_anchor.z]]
      const xs = points.map(point => point[0]), zs = points.map(point => point[1])
      const x = Math.min(...xs) - .4, z = Math.min(...zs) - .4
      const width = Math.max(...xs) - x + .4, depth = Math.max(...zs) - z + .4
      return <div key={role}>
        <strong>{t(role === 'actor' ? 'Actor' : role === 'partner' ? 'Partner' : role)}</strong>
        <svg role="img" aria-label={t('Computed walking path, access and body anchor')} viewBox={`${x} ${z} ${width} ${depth}`} width="240" height="160">
          <polyline points={plan.waypoints.map(point => point.join(',')).join(' ')} fill="none" stroke="currentColor" strokeWidth=".06" />
          <circle cx={plan.access.x} cy={plan.access.z} r=".12" fill="none" stroke="currentColor" strokeWidth=".05" />
          <rect x={plan.entry_anchor.x - .1} y={plan.entry_anchor.z - .1} width=".2" height=".2" fill="currentColor" />
        </svg>
        <p>{t('Access (circle)')}: X {plan.access.x}, Z {plan.access.z}, {t('Heading')} {plan.access.yaw}°.
          {' '}{t('Body anchor (square)')}: {plan.entry_anchor.marker_id}, {t('Slot')} {plan.entry_anchor.slot}, X {plan.entry_anchor.x}, Y {plan.entry_anchor.y}, Z {plan.entry_anchor.z}.</p>
      </div>
    })}
  </details>
}

function checkError(error: unknown): CheckError {
  if (error instanceof ApiError) {
    const detail = error.detail
    const reason = detail && typeof detail === 'object' && 'reason' in detail
      ? String(detail.reason) : ''
    return { status: error.status, message: reason ? propCheckReason(reason)
      : typeof detail === 'string' ? detail
        : error.status === 422 ? 'The selection or configuration is invalid. Check the fields and try again.'
          : error.status === 403 ? 'This check requires administrator access.'
            : error.status === 409 ? 'The saved placement or revision changed. Refresh and check again.'
              : 'The request could not be completed. Try again.' }
  }
  return { message: error instanceof Error ? error.message : 'The request failed. Try again.' }
}

/** Read-only document validation and saved room preflight. */
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
    key: string; result: PropPlacementCheckResult & { plans?: Record<string, CorePlan> }
  } | null>(null)
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
  const missing = dirtyCount || saving ? 'Missing: save or discard the draft'
    : !revisionReady ? 'Missing: wait for the saved configuration'
      : !locationsLoaded ? 'Missing: load the saved locations'
        : !locationId ? 'Missing: choose a location'
          : loading ? 'Missing: wait for room data'
            : !room ? 'Missing: choose a room'
              : !placement ? 'Missing: choose a placement'
                : !savedAction ? 'Missing: choose a saved action'
                  : !actorPresent ? 'Missing: choose a person in the room'
                    : !partnerPresent ? 'Missing: choose an available partner in the room'
                      : !savedReady ? 'Missing: refresh the saved placement and revision' : ''
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
    setPlacementResult(null); setLoading(false)
  }, [prop.id])

  useEffect(() => {
    const token = ++sourceRequest.current
    let disposed = false
    setLoading(true)
    apiGet<{ locations: { id: string; name: string }[] }>('/world/locations').then(result => {
      if (!disposed && token === sourceRequest.current) {
        setLocations(result.locations); setLocationsLoaded(true)
      }
    }).catch(error => {
      if (!disposed && token === sourceRequest.current) setRoomError(checkError(error))
    }).finally(() => { if (!disposed && token === sourceRequest.current) setLoading(false) })
    return () => { disposed = true }
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
    setActor(''); setPartner(''); setRoomError(null)
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
      const result = await apiPost<PropPlacementCheckResult & { plans?: Record<string, CorePlan> }>(`${path}/check-placement`, request)
      if (activeProp.current === propId) setPlacementResult({ key: requestKey, result })
    } catch (error) {
      if (activeProp.current === propId) setRoomError(checkError(error))
    } finally { setBusy(false) }
  }

  return <section className="prop-inspector-group" aria-label={t('Read-only checks')}>
    <h3>{t('Checks')}</h3>
    <p className="ga-hint">{t('Configuration checking reads the entire draft, including all variants. Nothing is saved and no world values change.')}</p>
    <button type="button" className="ga-btn ga-btn-sm" disabled={validating || !revisionReady}
      onClick={() => { void validateConfiguration() }}>{t(validating ? 'Checking configuration…' : 'Check configuration')}</button>
    {currentConfigurationError && <p role="alert">{currentConfigurationError.status ? `HTTP ${currentConfigurationError.status}: ` : ''}{t(currentConfigurationError.message)}</p>}
    {!revisionReady && <p className="ga-hint">{t('Wait for all variants and a consistent revision; resolve loading errors in the workspace.')}</p>}
    {configuration && !currentConfiguration && <p role="status">{t('The draft changed since the check. Check again.')}</p>}
    {currentConfiguration && <div role="status">
      <p>{t(currentConfiguration.valid ? 'Configuration valid' : 'Configuration contains errors')}</p>
      <p className="ga-hint">{t('Room path, entry and presence: not checked. These require an actual saved placement.')}</p>
      <ul>{currentConfiguration.issues.map((issue, index) => {
        const location = resolveCheckIssue(issue, document)
        const action = workspace.actions.find((entry) => entry.id === location.actionId)
        const variant = variants.find((entry) => entry.uid === location.variantUid)
        return <li key={`${issue.path}-${issue.code}-${index}`}>
          <button type="button" className="ga-btn ga-btn-sm" onClick={() => onIssue(issue)}>
            {t(issue.severity === 'error' ? 'Error' : 'Warning')}: {t(issue.message)}
            {action ? ` · ${action.name}` : ''}{variant ? ` · ${t('Variant')} ${variant.index + 1}` : ''}
            {location.field ? ` · ${t(location.field.includes('access_points') ? 'Access' : location.field.includes('marker_ids') ? 'Body anchor' : location.field.includes('requirements') ? 'Requirement' : location.field.includes('effects') ? 'Effect' : location.field.includes('phases') ? 'Action flow' : 'Configuration')}` : ''}
          </button>
        </li>
      })}</ul>
    </div>}

    <h3>{t('Check in room')}</h3>
    <p className="ga-hint">{t('Uses the saved configuration. This check reserves no place, moves nobody and changes no values. It reports the first blocking reason; later checks are not confirmed as passed.')}</p>
    {dirtyCount > 0 && <p role="status">{t('Save or discard the draft before checking a saved room placement.')}</p>}
    <button type="button" className="ga-btn ga-btn-sm" disabled={loading || busy}
      onClick={() => { void loadLocations() }}>{t('Refresh locations')}</button>
    {locationsLoaded && !locations.length && <p>{t('No saved locations available.')}</p>}
    {locationsLoaded && <Field label={t('Saved location')}>
      <select aria-label={t('Saved location')} className="ga-input" value={locationId}
        disabled={loading || busy} onChange={(event) => { void loadTargets(event.target.value) }}>
        <option value="">{t('Choose a location')}</option>
        {locations.map((entry) => <option key={entry.id} value={entry.id}>{entry.name}</option>)}
      </select>
    </Field>}
    {locationId && <button type="button" className="ga-btn ga-btn-sm" disabled={loading || busy}
      onClick={() => { void loadTargets(locationId) }}>{t('Refresh placements and people')}</button>}
    {loading && <p role="status">{t('Loading saved data…')}</p>}
    {targets && !targets.rooms.length && <p>{t('This location has no resolvable placement of this prop with body anchors. Place the prop in a room, repair its variant and markers, and ensure the location has a world position. Then refresh.')}</p>}
    {targets && targets.rooms.length > 0 && <>
      <Field label={t('Actual room')}>
        <select aria-label={t('Actual room')} className="ga-input" value={roomId} disabled={busy || loading}
          onChange={(event) => { setRoomId(event.target.value); setPlacementId(''); setActor(''); setPartner('') }}>
          <option value="">{t('Choose a room')}</option>
          {targets.rooms.map((entry) => <option key={entry.id} value={entry.id}>{entry.name}</option>)}
        </select>
      </Field>
      {room && <>
        <Field label={t('Saved placement')}>
          <select aria-label={t('Saved placement')} className="ga-input" value={placementId} disabled={busy || loading}
            onChange={(event) => { setPlacementId(event.target.value) }}>
            <option value="">{t('Choose a placement')}</option>
            {room.placements.map(({ target }, index) => {
              const variant = variants.find((entry) => entry.uid === target.variant_uid)
              return <option key={target.placement_id} value={target.placement_id}>
                {t('Placement')} {index + 1} · {variant ? `${t('Variant')} ${variant.index + 1}` : t('Variant no longer available')}
              </option>
            })}
          </select>
        </Field>
        <Field label={t('Actor in the room')}>
          <select aria-label={t('Actor in the room')} className="ga-input" value={actor} disabled={busy || loading}
            onChange={(event) => { setActor(event.target.value); setPartner('') }}>
            <option value="">{t('Choose a person')}</option>
            {room.persons.map((person) => <option key={person.name} value={person.name} disabled={person.sleeping}>
              {person.name}{person.sleeping ? ` · ${t('sleeping; counts as present')}` : ''}
            </option>)}
          </select>
        </Field>
        {!room.persons.length && <p>{t('There are no people in this room. This check does not create or move test people.')}</p>}
        {pair && <Field label={t('Partner in the room')}>
          <select aria-label={t('Partner in the room')} className="ga-input" value={partner} disabled={busy || loading}
            onChange={(event) => { setPartner(event.target.value) }}>
            <option value="">{t('Choose a partner')}</option>
            {room.persons.filter((person) => person.name !== actor).map((person) => <option key={person.name} value={person.name} disabled={person.sleeping}>
              {person.name}{person.sleeping ? ` · ${t('sleeping; unavailable')}` : ''}
            </option>)}
          </select>
        </Field>}
      </>}
    </>}
    <p>{t('Selected saved action')}: {savedAction?.name || t('Choose an action and save it if needed')}</p>
    {targets && targets.revision !== prop.revision && <p role="status">{t('Check data and workspace have different saved revisions. Refresh the workspace and placements; no draft is overwritten.')}</p>}
    <button type="button" className="ga-btn ga-btn-sm" disabled={!canCheck}
      onClick={() => { void checkPlacement() }}>{t(busy ? 'Request in progress…' : 'Check in room (read only)')}</button>
    {missing && <p className="ga-hint" role="status">{t(missing)}</p>}
    {roomError && <p role="alert">{roomError.status ? `HTTP ${roomError.status}: ` : ''}{t(roomError.message)}</p>}
    {placementResult && <div role="status">
      {(placementResult.key !== requestKey || !savedReady) && <p className="ga-hint">{t('Previous check: the selection or saved configuration has changed. Check again for a current result.')}</p>}
      <p>{t(placementResult.result.enabled ? 'Currently available: availability, path and entry checked. No execution started.' : 'Currently blocked')}</p>
      {placementResult.result.reason && <p>{t(propCheckReason(placementResult.result.reason))}</p>}
      <p className="ga-hint">{t('Snapshot only, no reservation. Normal rules are checked again at actual start and arrival; no pair consent has been given.')}</p>
      <CorePlans plans={placementResult.result.plans} t={t} />
    </div>}

  </section>
}
