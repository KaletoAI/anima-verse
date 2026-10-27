import { useState } from 'react'
import { PropWorkspaceDialog } from './PropWorkspaceDialog'
import { bindingProblems, type AccessRole } from './spatialBindings'
import type { PropWorkspace } from './usePropWorkspace'
import { groupLabel } from '../world/placeTypes'

/** Spatial inspector shares the workspace's canonical actions/variant draft. */
export function PropSpatialBindings({ workspace: w }: { workspace: PropWorkspace }) {
  const { t, actions, selectedActionId, setSelectedActionId, shownVariant, markers,
    patchBinding, armAccess, accessPlacing, saving, previewFile, shownHasMesh } = w
  const [replacement, setReplacement] = useState('')
  const action = actions.find(a => a.id === selectedActionId)
  const bindings = shownVariant?.action_bindings || []
  const binding = bindings.find(b => b.action_id === action?.id)
  const variantPosition = w.variants.findIndex(variant => variant.uid === shownVariant?.uid)
  const bindingPath = `model_variants.${variantPosition}.action_bindings.${bindings.indexOf(binding!)}`
  const problems = binding && action ? bindingProblems(binding, action, markers, w.shownDims) : []
  const roles: AccessRole[] = action?.participants === 2 ? ['actor', 'partner'] : ['actor']
  const removal = w.markerRemoval?.uid === shownVariant?.uid ? w.markerRemoval : null
  const dependents = removal ? bindings.filter(b => b.marker_ids.includes(removal.markerId)) : []
  const unknown = bindings.filter((b, index) => !actions.some(a => a.id === b.action_id)
    || bindings.findIndex(entry => entry.action_id === b.action_id) !== index)
  return <section>
    <h3>{t('Platzbindung je Variante')}</h3>
    <p className="ga-hint">{t('Die Handlung gilt für das gesamte Prop. Körperanker und Zugänge gehören nur zur oben ausgewählten Variante.')}</p>
    <label className="ga-form-row">{t('Gewählte Handlung')}
      <select className="ga-input" value={action?.id || ''} onChange={e => { setSelectedActionId(e.target.value); w.setPlacing(null) }}>
        <option value="">{t('Handlung auswählen')}</option>
        {actions.map(a => <option key={a.id} value={a.id}>{a.name || a.id}{a.enabled ? '' : ` (${t('deaktiviert')})`}</option>)}
      </select>
    </label>
    {!actions.length && <p className="ga-hint">{t('Keine Aktionen: Ein dekoratives Prop braucht keine Bindung.')}</p>}
    {action && <fieldset className="prop-editor-fields" disabled={saving || !!previewFile || !shownVariant}>
      <label className="ga-form-row">{t('Unterstützung dieser Variante')}
        <select id="prop-binding-supported" data-author-path={binding ? `${bindingPath}.supported` : undefined} className="ga-input" value={!binding ? 'missing' : binding.supported ? 'supported' : 'unsupported'}
          onChange={e => patchBinding(action.id, { supported: e.target.value === 'supported', validation: 'repair_required' })}>
          {!binding && <option value="missing">{t('Nicht zugeordnet — Reparatur nötig')}</option>}
          <option value="supported">{t('Unterstützt (Bindung bearbeiten)')}</option>
          <option value="unsupported">{t('Ausdrücklich nicht unterstützt')}</option>
        </select>
      </label>
      {binding && <>
        {binding.variant_uid !== shownVariant?.uid && <p role="alert" id="prop-binding-variant_uid" tabIndex={-1}>
          {t('Bindung verweist auf eine andere Varianten-UUID.')}{' '}
          <button type="button" className="ga-btn ga-btn-sm" onClick={() => patchBinding(action.id, { validation: 'repair_required' })}>{t('Mit dieser Variante verknüpfen')}</button>
        </p>}
        <p role="status" className="ga-hint" id="prop-binding-validation" tabIndex={-1}>{!binding.supported ? t('Diese Variante bietet die Handlung nicht an.')
          : binding.validation === 'local_valid' && !problems.length ? t('Lokal bestätigt. Raumweg und Anwesenheit nicht geprüft.')
            : t('Reparatur nötig: Körperanker/Zugänge bearbeiten und lokal bestätigen.')}</p>
        <div id="prop-binding-marker_ids" tabIndex={-1}>
          <strong>{t('Körperanker — Alternativen, keine aufeinanderfolgenden Schritte')}</strong>
          {markers.map((m, i) => <label key={m.id || i} className="ga-form-row">
            <input type="checkbox" checked={!!m.id && binding.marker_ids.includes(m.id)} disabled={!m.id}
              onChange={e => patchBinding(action.id, { marker_ids: e.target.checked ? [...binding.marker_ids, m.id!] : binding.marker_ids.filter(id => id !== m.id), validation: 'repair_required' })} />
            {t('Marker')} {i + 1} · {groupLabel(w.groups, m.group)} · {t('Kapazität')} {m.capacity || 1}
            <button type="button" className="ga-btn ga-btn-sm" onClick={() => w.setSelectedMarker(i)}>{t('Körperanker bearbeiten')}</button>
          </label>)}
          {binding.marker_ids.filter(id => !markers.some(m => m.id === id)).map(id => <div key={id} role="alert">
            {t('Unbekannter Marker')}: {id}
            <select className="ga-input" aria-label={t('Fehlenden Marker ersetzen')} value="" onChange={e => {
              if (e.target.value) patchBinding(action.id, { marker_ids: [...new Set(binding.marker_ids.map(mid => mid === id ? e.target.value : mid))], validation: 'repair_required' })
            }}><option value="">{t('Ersatzmarker auswählen')}</option>{markers.filter(m => m.id).map((m, i) => <option key={m.id} value={m.id}>{t('Marker')} {i + 1} · {groupLabel(w.groups, m.group)}</option>)}</select>
            <button type="button" className="ga-btn ga-btn-sm" onClick={() => patchBinding(action.id, { marker_ids: binding.marker_ids.filter(mid => mid !== id), validation: 'repair_required' })}>{t('Fehlende Referenz entfernen')}</button>
          </div>)}
        </div>
        {action.participants === 2 && <p className="ga-hint">{t('Paargeometrie: Jede Alternative ist ein gemeinsamer Marker mit mindestens zwei Slots. Clip A/B müssen je einen eindeutigen Slot innerhalb 0,05 m treffen. Kapazität, Abstand, Achse und Facing unten einstellen; der Raumcheck prüft die reale Paargeometrie. Die Zugänge gehören zu den physischen Cliprollen A/B. Die Laufzeit ordnet Personen nach den Clip-Geschlechtsregeln zu; Initiator/Partner als Wirkungsziele bleiben unverändert. Keine feste Personen-zu-A/B-Zuweisung.')}</p>}
        <p className="ga-hint" id="prop-binding-access_points" tabIndex={-1}>{t('Zugänge: lokale Meter X/Z ab Mitte der orientierten Grundfläche, am Boden; außerhalb der Bounding-Box erlaubt. Yaw: 0° Süd (+Z), 90° Ost (+X). Kein nachgewiesener Raumweg.')}</p>
        {Object.keys(binding.access_points).some(role => !roles.includes(role as AccessRole)) && <p role="alert">
          {t('Zugang für eine nicht vorhandene Rolle.')}
          <button type="button" className="ga-btn ga-btn-sm" onClick={() => patchBinding(action.id, {
            access_points: Object.fromEntries(Object.entries(binding.access_points).filter(([role]) => roles.includes(role as AccessRole))),
            validation: 'repair_required',
          })}>{t('Nicht passende Rollenzugänge entfernen')}</button>
        </p>}
        {roles.map(role => {
          const point = binding.access_points[role]
          const picking = accessPlacing?.actionId === action.id && accessPlacing.role === role
          return <div key={role} id={`prop-binding-access_points-${role}`} tabIndex={-1}>
            <strong>{action.participants === 2 ? role === 'actor' ? t('Zugang Clip A') : t('Zugang Clip B') : t('Zugang handelnde Person')}</strong>
            {!point && binding.supported && <p role="alert">{t('Zugang fehlt. Auf dem Boden setzen oder numerisch anlegen.')}</p>}
            <div className="ga-form-row">
              {(['x', 'z', 'yaw'] as const).map(key => <label key={key} style={{ flex: '1 1 90px', minWidth: 0 }}>
                {key === 'yaw' ? t('Ausrichtung (°)') : `${key.toUpperCase()} (m)`}
                <input id={`prop-binding-access_points-${role}-${key}`} data-author-path={`${bindingPath}.access_points.${role}.${key}`} className="ga-input" type="number" step={key === 'yaw' ? 1 : .01}
                  value={point && Number.isFinite(point[key]) ? point[key] : ''} onChange={e => {
                    const n = e.target.value === '' ? Number.NaN : Number(e.target.value)
                    patchBinding(action.id, { access_points: { ...binding.access_points, [role]: { x: 0, z: 0, yaw: 0, ...point, [key]: n } }, validation: 'repair_required' })
                  }} />
              </label>)}
            </div>
            <button type="button" className={`ga-btn ga-btn-sm${picking ? ' ga-btn-primary' : ''}`} disabled={!shownHasMesh}
              onClick={() => armAccess(action.id, role)}>{picking ? t('Boden anklicken… (Esc beendet Werkzeug)') : t('Zugang am Boden setzen')}</button>
            {point && <button type="button" className="ga-btn ga-btn-sm" onClick={() => {
              const next = { ...binding.access_points }; delete next[role]
              patchBinding(action.id, { access_points: next, validation: 'repair_required' })
            }}>{t('Zugang entfernen')}</button>}
          </div>
        })}
        {binding.supported && problems.length > 0 && <ul role="alert">{problems.map(p => <li key={p}>{t(p)}</li>)}</ul>}
        <button type="button" className="ga-btn" disabled={problems.length > 0 || !binding.supported}
          onClick={() => patchBinding(action.id, { validation: 'local_valid' })}>{t('Zugänge lokal bestätigen (kein Raumweg)')}</button>
        <p className="ga-hint">{t('Bestätigt nur vollständige Anker und freie Zugänge außerhalb der eigenen Grundfläche mit 0,30 m Abstand. Paar-Slotpassung, Eintrittsübergang, andere Möbel, Wände und Personen prüft erst der Server/Raumcheck.')}</p>
      </>}
    </fieldset>}
    {!!unknown.length && <div role="alert"><strong>{t('Unbekannte oder doppelte Aktionsbindungen')}</strong>{unknown.map((b, i) => <div key={`${b.action_id}-${i}`}>
      {b.action_id} <button className="ga-btn ga-btn-sm" type="button" disabled={saving || !!previewFile} onClick={() => w.queueVariant(w.variant, { action_bindings: bindings.filter(entry => entry !== b) })}>{t('Ungültige Bindung entfernen')}</button>
    </div>)}</div>}
    <div><strong>{t('Alle verwendenden Aktionen dieser Variante')}</strong>
      <ul>{bindings.map((b, i) => <li key={`${b.action_id}-${i}`}><button type="button" className="ga-btn ga-btn-sm" onClick={() => setSelectedActionId(b.action_id)}>{actions.find(a => a.id === b.action_id)?.name || b.action_id}</button> · {!b.supported ? t('Nicht unterstützt') : b.validation === 'local_valid' ? t('Lokal bestätigt') : t('Reparatur nötig')}</li>)}</ul>
    </div>
    {removal && <PropWorkspaceDialog title={t('Referenzierten Körperanker entfernen')} onCancel={() => { w.setMarkerRemoval(null); setReplacement('') }}>
      <p>{t('Diese Aktionen verwenden den Marker. Ersatz verknüpfen oder alle abhängigen Bindungen zusammen mit dem Marker aus demselben Entwurf entfernen:')}</p>
      <ul>{dependents.map(b => <li key={b.action_id}>{actions.find(a => a.id === b.action_id)?.name || b.action_id}</li>)}</ul>
      <label>{t('Ersatzmarker')}<select className="ga-input" value={replacement} onChange={e => setReplacement(e.target.value)}><option value="">{t('Auswählen')}</option>
        {markers.filter(m => m.id && m.id !== removal.markerId).map((m, i) => <option key={m.id} value={m.id}>{groupLabel(w.groups, m.group)} · {m.id} ({i + 1})</option>)}
      </select></label>
      <div className="ga-form-row">
        <button type="button" className="ga-btn" disabled={saving || !markers.some(m => m.id === replacement && m.id !== removal.markerId)} onClick={() => { w.commitMarkerRemoval(removal.markerId, { replaceWith: replacement }); setReplacement('') }}>{t('Neu verknüpfen und Marker entfernen')}</button>
        <button type="button" className="ga-btn ga-btn-danger" disabled={saving} onClick={() => { w.commitMarkerRemoval(removal.markerId, { removeBindings: true }); setReplacement('') }}>{t('Marker und abhängige Bindungen entfernen')}</button>
        <button type="button" className="ga-btn" onClick={() => { w.setMarkerRemoval(null); setReplacement('') }}>{t('Abbrechen')}</button>
      </div>
    </PropWorkspaceDialog>}
  </section>
}
