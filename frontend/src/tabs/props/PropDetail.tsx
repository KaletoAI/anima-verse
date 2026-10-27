import { ExportButton, PublishButton } from '../../components/ImportExport'
import { PropOverview } from './PropOverview'
import { PropActionsSummary } from './PropActionsSummary'
import { PropPlaces } from './PropPlaces'
import { PropAssets } from './PropAssets'
import { PropAppearance } from './PropAppearance'
import { PropPreview } from './PropPreview'
import { PropWorkspaceDialog } from './PropWorkspaceDialog'
import { usePropWorkspace, type PropDetailProps } from './usePropWorkspace'
import type { PropWorkspaceArea } from './propTypes'

const AREAS: { id: PropWorkspaceArea; label: string }[] = [
  { id: 'overview', label: 'Übersicht' },
  { id: 'actions', label: 'Aktionen' },
  { id: 'places', label: 'Plätze & Zugänge' },
  { id: 'assets', label: 'Modell & Varianten' },
  { id: 'appearance', label: 'Darstellung' },
]

/** Layout owns no second form or viewer: every area consumes this workspace. */
export function PropDetail(props: PropDetailProps) {
  const workspace = usePropWorkspace(props)
  const { t, prop, nameNow, area, navigate, mobilePane, setMobilePane,
    dirtyCount, saving, save, discard, discardArmed, setDiscardArmed,
    variant, variants, shownVariant, setVariant, conflicts, saveError,
    resolveConflict, beforeImmediate, operation, finishOperation,
    revisionReady, variantLoadError, loadVariants } = workspace
  return <div className={`prop-workspace is-${mobilePane}`}>
    <header className="prop-workspace-header">
      <div className="prop-workspace-title">
        <h2>{nameNow || prop.name}</h2>
        <span className="ga-hint">{t('Gesamtes Prop')} · {dirtyCount
          ? t('{n} ungespeicherte Felder').replace('{n}', String(dirtyCount))
          : t('Gespeichert')}</span>
      </div>
      <div className="prop-workspace-save">
        {dirtyCount > 0 && <button type="button"
          className={`ga-btn${discardArmed ? ' ga-btn-danger' : ''}`} disabled={saving}
          onClick={() => discardArmed ? discard() : setDiscardArmed(true)}>
          {t(discardArmed ? 'Änderungen wirklich verwerfen?' : 'Änderungen verwerfen')}
        </button>}
        {discardArmed && <button type="button" className="ga-btn" onClick={() => setDiscardArmed(false)}>{t('Cancel')}</button>}
        <button type="button" className="ga-btn ga-btn-primary"
          disabled={!dirtyCount || saving || conflicts.length > 0 || !revisionReady}
          onClick={() => { void save() }}>{t(saving ? 'Saving…' : 'Speichern')}</button>
        <details className="prop-object-menu" onKeyDown={(event) => {
          if (event.key !== 'Escape') return
          event.preventDefault(); event.stopPropagation()
          event.currentTarget.open = false
          event.currentTarget.querySelector('summary')?.focus()
        }}>
          <summary className="ga-btn">{t('Objektmenü')}</summary>
          <div className="prop-object-menu-items">
            <span className="ga-hint">{t('Export und Veröffentlichung verwenden den gespeicherten Stand.')}</span>
            <ExportButton endpoint={`/world/props/${encodeURIComponent(prop.id)}/export`}
              filename={`prop_${prop.id}.zip`} />
            <fieldset disabled={dirtyCount > 0 || saving}>
              <PublishButton packType="prop" entityId={prop.id} defaultName={prop.name} />
            </fieldset>
            {dirtyCount > 0 && <span className="ga-hint">{t('Vor dem Veröffentlichen speichern.')}</span>}
            <button type="button" className="ga-btn ga-btn-danger" disabled={saving}
              onClick={async () => {
                if (!props.armedDelete || await beforeImmediate(t('Delete prop'))) props.onDelete()
              }}>{t(props.armedDelete ? 'Really delete?' : 'Delete prop')}</button>
          </div>
        </details>
      </div>
    </header>
    {variantLoadError && <p role="alert">{variantLoadError} <button type="button" className="ga-btn ga-btn-sm" onClick={() => { void loadVariants() }}>{t('Varianten erneut laden')}</button></p>}
    <nav className="prop-workspace-tabs" role="tablist" aria-label={t('Prop-Bereiche')}>
      {AREAS.map((item, index) => <button key={item.id} type="button" role="tab"
        id={`prop-tab-${item.id}`} aria-controls="prop-workspace-editor"
        aria-selected={area === item.id} tabIndex={area === item.id ? 0 : -1}
        className={`prop-workspace-tab${area === item.id ? ' is-active' : ''}`}
        onClick={() => navigate(item.id)} onKeyDown={(event) => {
          const next = event.key === 'ArrowRight' ? (index + 1) % AREAS.length
            : event.key === 'ArrowLeft' ? (index + AREAS.length - 1) % AREAS.length
            : event.key === 'Home' ? 0 : event.key === 'End' ? AREAS.length - 1 : -1
          if (next < 0) return
          event.preventDefault()
          navigate(AREAS[next].id)
          document.getElementById(`prop-tab-${AREAS[next].id}`)?.focus()
        }}>{t(item.label)}</button>)}
    </nav>
    <div className="prop-workspace-context">
      <label htmlFor="prop-workspace-variant">{t('Variante')} · {t('Geometrie')}</label>
      <select id="prop-workspace-variant" className="ga-input" value={variant}
        disabled={!variants.length || saving} onChange={(event) => setVariant(+event.target.value)}>
        {variants.map((v) => <option key={v.uid} value={v.index}>
          {v.label || `${t('Variant')} ${v.index + 1}`}{v.primary ? ` · ${t('Primary')}` : ''}{!v.active ? ` · ${t('inaktiv')}` : ''}
        </option>)}
      </select>
      <span className="ga-hint">{area === 'actions'
        ? t('Handlung gilt für das gesamte Prop')
        : t('Geometriefelder gelten für diese Variante.')}</span>
    </div>
    {(saveError || conflicts.length > 0) && <section className="prop-workspace-conflicts" role="alert">
      <strong>{t('Entwurf bleibt erhalten')}</strong>
      {saveError && <p>{saveError}</p>}
      {conflicts.length > 0 && <p>{t('Diese Felder wurden auch auf dem Server geändert. Entscheide je Feld, bevor du erneut speicherst.')}</p>}
      {conflicts.map((conflict) => <div className="prop-conflict" key={`${conflict.target}.${conflict.field}`}>
        <strong>{conflict.target === 'general' ? t('Gesamtes Prop')
          : variants.find((v) => `v:${v.uid}` === conflict.target)?.label || conflict.target} / {conflict.field}</strong>
        <details><summary>{t('Serveränderung ansehen')}</summary>
          <div>{t('Server')}: <pre>{JSON.stringify(conflict.server, null, 2) ?? t('Variante entfernt')}</pre></div>
          <div>{t('Mein Entwurf')}: <pre>{JSON.stringify(conflict.local, null, 2)}</pre></div>
        </details>
        <div className="ga-form-row">
          {!conflict.missing && <button type="button" className="ga-btn ga-btn-sm"
            onClick={() => resolveConflict(conflict, true)}>{t('Meinen Feldentwurf behalten')}</button>}
          <button type="button" className="ga-btn ga-btn-sm"
            onClick={() => resolveConflict(conflict, false)}>{t(conflict.missing ? 'Entwurf der entfernten Variante verwerfen' : 'Serverwert übernehmen')}</button>
        </div>
      </div>)}
    </section>}
    <div className="prop-mobile-switch" aria-label={t('Arbeitsansicht')}>
      <button type="button" className="ga-btn" aria-pressed={mobilePane === 'editor'} onClick={() => setMobilePane('editor')}>{t('Editor')}</button>
      <button type="button" className="ga-btn" aria-pressed={mobilePane === 'preview'} onClick={() => setMobilePane('preview')}>{t('Vorschau')}</button>
    </div>
    <div className="prop-workspace-body">
      <section id="prop-workspace-editor" role="tabpanel" aria-labelledby={`prop-tab-${area}`}
        className="prop-workspace-editor" tabIndex={0}>
        <fieldset className="prop-editor-fields" disabled={saving}>
          {area === 'overview' && <PropOverview workspace={workspace} />}
          {area === 'actions' && <PropActionsSummary workspace={workspace} />}
          {area === 'places' && <PropPlaces workspace={workspace} />}
          {area === 'assets' && <PropAssets workspace={workspace} />}
          {area === 'appearance' && <PropAppearance workspace={workspace} />}
        </fieldset>
      </section>
      <aside className="prop-workspace-preview" aria-label={t('3D preview')}>
        <PropPreview workspace={workspace} />
        <span className="ga-hint">{shownVariant?.label || `${t('Variant')} ${variant + 1}`} · {t('Vorschau ohne Weltänderungen')}</span>
      </aside>
    </div>
    {operation && <PropWorkspaceDialog title={t('Änderungen speichern und fortfahren')}
      onCancel={() => { if (!saving) finishOperation(false) }}>
      <div className="ga-modal-body">
        <p>{operation.label} — {t('Wird sofort angewendet.')}</p>
        <p>{t('Zuerst den gemeinsamen Entwurf speichern. Verwerfen macht anschließende Dateiänderungen nicht rückgängig.')}</p>
        {saveError && <p role="alert">{saveError}</p>}
        {conflicts.length > 0 && <p role="alert">{t('Abbrechen und zuerst die Feldkonflikte im Arbeitsbereich auflösen.')}</p>}
      </div>
      <div className="ga-modal-footer">
        <button type="button" className="ga-btn" disabled={saving} onClick={() => finishOperation(false)}>{t('Cancel')}</button>
        <button type="button" className="ga-btn ga-btn-primary" disabled={saving || conflicts.length > 0 || !revisionReady}
          onClick={async () => { if (!dirtyCount || await save()) finishOperation(true) }}>{t('Änderungen speichern und fortfahren')}</button>
      </div>
    </PropWorkspaceDialog>}
  </div>
}
