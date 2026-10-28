import { ExportButton, PublishButton } from '../../components/ImportExport'
import { PropOverview } from './PropOverview'
import { PropActionsPanel } from './PropActionsPanel'
import { PropPlaces } from './PropPlaces'
import { PropAssets } from './PropAssets'
import { PropAppearance } from './PropAppearance'
import { PropPreview } from './PropPreview'
import { PropWorkspaceDialog } from './PropWorkspaceDialog'
import { usePropWorkspace, type PropDetailProps } from './usePropWorkspace'
import type { PropActionIssue, PropWorkspaceArea } from './propTypes'

const AREAS: { id: PropWorkspaceArea; label: string }[] = [
  { id: 'overview', label: "Overview" },
  { id: 'actions', label: "Actions" },
  { id: 'places', label: "Places" },
  { id: 'assets', label: "Model & variants" },
  { id: 'appearance', label: "Appearance" },
]

/** Layout owns no second form or viewer: every area consumes this workspace. */
export function PropDetail(props: PropDetailProps) {
  const workspace = usePropWorkspace(props)
  const { t, prop, nameNow, area, navigate, mobilePane, setMobilePane,
    dirtyCount, saving, save, discard, discardArmed, setDiscardArmed,
    variant, variants, shownVariant, setVariant, conflicts, saveError,
    resolveConflict, beforeImmediate, operation, finishOperation,
    revisionReady, variantLoadError, loadVariants, saveIssues, authoringIssues } = workspace
  const openIssue = (issue: PropActionIssue) => {
    const actionMatch = /^actions\.(\d+)/.exec(issue.path)
    const variantMatch = /^model_variants\.(\d+)/.exec(issue.path)
    let markerToSelect: number | undefined
    if (actionMatch) {
      workspace.setSelectedActionId(workspace.actions[Number(actionMatch[1])]?.id || '')
      navigate('actions')
    } else if (variantMatch) {
      const target = variants[Number(variantMatch[1])]
      if (target) {
        setVariant(target.index)
        const markerMatch = /\.markers\.(\d+)/.exec(issue.path)
        if (markerMatch) markerToSelect = Number(markerMatch[1])
      }
      navigate('places')
    } else navigate('actions')
    requestAnimationFrame(() => {
      if (markerToSelect !== undefined) workspace.setSelectedMarker(markerToSelect)
      requestAnimationFrame(() => {
        const fields = Array.from(document.querySelectorAll<HTMLElement>('[data-author-path]'))
        const field = fields.find(item => item.dataset.authorPath === issue.path)
          || fields.find(item => item.dataset.authorPath?.startsWith(`${issue.path}.`))
          || (markerToSelect !== undefined ? document.querySelector<HTMLElement>('.ga-marker-card input, .ga-marker-card select') : null)
          || document.getElementById('prop-workspace-editor')
        for (let parent = field?.parentElement; parent; parent = parent.parentElement) {
          if (parent instanceof HTMLDetailsElement) parent.open = true
        }
        field?.focus()
        field?.scrollIntoView({ block: 'nearest' })
      })
    })
  }
  return <div className={`prop-workspace is-${mobilePane}`}>
    <header className="prop-workspace-header">
      <div className="prop-workspace-title">
        <h2>{nameNow || prop.name}</h2>
        <span className="ga-hint">{t("Entire prop")} · {dirtyCount
          ? t("{n} unsaved fields").replace('{n}', String(dirtyCount))
          : t("Saved")}</span>
      </div>
      <div className="prop-workspace-save">
        {dirtyCount > 0 && <button type="button"
          className={`ga-btn${discardArmed ? ' ga-btn-danger' : ''}`} disabled={saving}
          onClick={() => discardArmed ? discard() : setDiscardArmed(true)}>
          {t(discardArmed ? "Really discard changes?" : "Discard changes")}
        </button>}
        {discardArmed && <button type="button" className="ga-btn" onClick={() => setDiscardArmed(false)}>{t('Cancel')}</button>}
        <button type="button" className="ga-btn ga-btn-primary"
          disabled={!dirtyCount || saving || conflicts.length > 0 || !revisionReady || authoringIssues.length > 0}
          onClick={() => { void save() }}>{t(saving ? 'Saving…' : "Save")}</button>
        <details className="prop-object-menu" onKeyDown={(event) => {
          if (event.key !== 'Escape') return
          event.preventDefault(); event.stopPropagation()
          event.currentTarget.open = false
          event.currentTarget.querySelector('summary')?.focus()
        }}>
          <summary className="ga-btn">{t("Prop menu")}</summary>
          <div className="prop-object-menu-items">
            <span className="ga-hint">{t("Export and publication use the saved version.")}</span>
            <ExportButton endpoint={`/world/props/${encodeURIComponent(prop.id)}/export`}
              filename={`prop_${prop.id}.zip`} />
            <fieldset disabled={dirtyCount > 0 || saving}>
              <PublishButton packType="prop" entityId={prop.id} defaultName={prop.name} />
            </fieldset>
            {dirtyCount > 0 && <span className="ga-hint">{t("Save before publishing.")}</span>}
            <button type="button" className="ga-btn ga-btn-danger" disabled={saving}
              onClick={async () => {
                if (!props.armedDelete || await beforeImmediate(t('Delete prop'))) props.onDelete()
              }}>{t(props.armedDelete ? 'Really delete?' : 'Delete prop')}</button>
          </div>
        </details>
      </div>
    </header>
    {variantLoadError && <p role="alert">{variantLoadError} <button type="button" className="ga-btn ga-btn-sm" onClick={() => { void loadVariants() }}>{t("Reload variants")}</button></p>}
    <nav className="prop-workspace-tabs" role="tablist" aria-label={t("Prop areas")}>
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
      <span id="prop-workspace-variant-label">{t("Variant")} · {t("Geometry")}</span>
      <div className="prop-variant-buttons" role="group" aria-labelledby="prop-workspace-variant-label">
        {variants.map((v) => <button key={v.uid} type="button"
          className="ga-btn ga-btn-sm" aria-pressed={variant === v.index} disabled={saving}
          onClick={() => setVariant(v.index)}>
          {v.label || `${t('Variant')} ${v.index + 1}`}{v.primary ? ` · ${t('Primary')}` : ''}{!v.active ? ` · ${t("inactive")}` : ''}
        </button>)}
      </div>
      <span className="ga-hint">{area === 'actions'
        ? t("Action applies to the entire prop")
        : t("Geometry fields apply to this variant.")}</span>
    </div>
    {(saveError || conflicts.length > 0) && <section className="prop-workspace-conflicts" role="alert">
      <strong>{t("Draft is retained")}</strong>
      {saveError && <p>{saveError}</p>}
      {conflicts.length > 0 && <p>{t("These fields also changed on the server. Resolve each field before saving again.")}</p>}
      {conflicts.map((conflict) => <div className="prop-conflict" key={`${conflict.target}.${conflict.field}`}>
        <strong>{conflict.target === 'general' ? t("Entire prop")
          : variants.find((v) => `v:${v.uid}` === conflict.target)?.label || conflict.target} / {conflict.field}</strong>
        <details><summary>{t("View server change")}</summary>
          <div>{t('Server')}: <pre>{JSON.stringify(conflict.server, null, 2) ?? t("Variant removed")}</pre></div>
          <div>{t("My draft")}: <pre>{JSON.stringify(conflict.local, null, 2)}</pre></div>
        </details>
        <div className="ga-form-row">
          {!conflict.missing && <button type="button" className="ga-btn ga-btn-sm"
            onClick={() => resolveConflict(conflict, true)}>{t("Keep my field draft")}</button>}
          <button type="button" className="ga-btn ga-btn-sm"
            onClick={() => resolveConflict(conflict, false)}>{t(conflict.missing ? "Discard the removed variant's draft" : "Use server value")}</button>
        </div>
      </div>)}
    </section>}
    {saveIssues.length > 0 && <section className="prop-workspace-conflicts" role="alert">
      <strong>{t("Repair configuration")}</strong>
      <ul>{saveIssues.map((issue, index) => <li key={`${issue.path}:${issue.code}:${index}`}>
        <button type="button" className="ga-btn ga-btn-sm" onClick={() => openIssue(issue)}>{t(issue.message)}</button>
      </li>)}</ul>
    </section>}
    {authoringIssues.length > 0 && <div className="prop-action-errors" role="status">
      {t("Saving is blocked until the action configuration is repaired.")}
      {' '}<button type="button" className="ga-btn ga-btn-sm" onClick={() => openIssue(authoringIssues[0])}>{t("Open action errors")}</button>
    </div>}
    <div className="prop-mobile-switch" aria-label={t("Workspace view")}>
      <button type="button" className="ga-btn" aria-pressed={mobilePane === 'editor'} onClick={() => setMobilePane('editor')}>{t('Editor')}</button>
      <button type="button" className="ga-btn" aria-pressed={mobilePane === 'preview'} onClick={() => setMobilePane('preview')}>{t("Preview")}</button>
    </div>
    <div className="prop-workspace-body">
      <section id="prop-workspace-editor" role="tabpanel" aria-labelledby={`prop-tab-${area}`}
        className="prop-workspace-editor" tabIndex={0}>
        <fieldset className="prop-editor-fields" disabled={saving}>
          {area === 'overview' && <PropOverview workspace={workspace} />}
          {area === 'actions' && <PropActionsPanel workspace={workspace} onIssue={openIssue} />}
          {area === 'places' && <PropPlaces workspace={workspace} />}
          {area === 'assets' && <PropAssets workspace={workspace} />}
          {area === 'appearance' && <PropAppearance workspace={workspace} />}
        </fieldset>
      </section>
      <aside className="prop-workspace-preview" aria-label={t('3D preview')}>
        <PropPreview workspace={workspace} />
        <span className="ga-hint">{shownVariant?.label || `${t('Variant')} ${variant + 1}`} · {t("Preview without world changes")}</span>
      </aside>
    </div>
    {operation && <PropWorkspaceDialog title={t("Save changes and continue")}
      onCancel={() => { if (!saving) finishOperation(false) }}>
      <div className="ga-modal-body">
        <p>{operation.label} — {t("Applies immediately.")}</p>
        <p>{t("Save the shared draft first. Discard does not undo subsequent file changes.")}</p>
        {saveError && <p role="alert">{saveError}</p>}
        {conflicts.length > 0 && <p role="alert">{t("Cancel and resolve field conflicts in the workspace first.")}</p>}
      </div>
      <div className="ga-modal-footer">
        <button type="button" className="ga-btn" disabled={saving} onClick={() => finishOperation(false)}>{t('Cancel')}</button>
        <button type="button" className="ga-btn ga-btn-primary" disabled={saving || conflicts.length > 0 || !revisionReady}
          onClick={async () => { if (!dirtyCount || await save()) finishOperation(true) }}>{t("Save changes and continue")}</button>
      </div>
    </PropWorkspaceDialog>}
  </div>
}
