import { useState } from 'react'
import { PropModelPanel } from './PropModelPanel'
import { PropVariantStrip } from './PropVariantStrip'
import { PropWorkspaceDialog } from './PropWorkspaceDialog'
import { PROP_EXTRA_VIEWS } from './propTypes'
import { propGenerationTarget } from './propOperations'
import { SliderInput } from '../../components/SliderInput'
import { DESC_ROWS_OPEN, DESC_ROWS_REST, DIM_FIELDS, SINK_LIMIT_M } from './variantFields'
import { VIEW_LABEL } from './usePropWorkspace'
import type { PropWorkspace } from './usePropWorkspace'

const REPAIR_STATUS = {
  ready: 'Mesh result retained; ready for assignment.',
  collected: 'Provider result retained; processing and publication are still pending.',
  waiting_provider: 'Provider result not yet collected. Only the existing paid job will be continued.',
  unrecorded: 'No publishable result or provider job ID recorded. Retained files are kept.',
}

export function PropAssets({ workspace }: { workspace: PropWorkspace }) {
  const [discardId, setDiscardId] = useState('')
  const { variantBusy, t, pending, shownImage, srcOk, enc, variant, reloadKey,
    setSrcOk, enlarge, prop, imageTip, variants, openImageGeneration, shownVariant,
    sourceUploadRef, uploadSource, onRefresh, setUploadView, viewUploadRef,
    armedView, setArmedView, deleteView, uploadView, openMeshGeneration,
    dimDraft, editDim, commitDim, commitSink, descOpen, descDraft, setDescOpen,
    setDescDraft, commitDesc, shownHasMesh, variantAreas, rotate, variantRotation,
    setRotationAxis, areasFailed, surfaceLabel, bakeSurface, shownSurface,
    removeArmed, removeSurface, setRemoveArmed, previewFile, showStoredFile,
    meshesChanged, commitFaces, backendFaces, onGenerating, openRegeneration,
    variantMax, setVariant, queueVariant, generatingVariants, worldSeasons,
    currentSeason, onVariantDeleted, prepareVariantOperation,
    generationRepairs, repairLoading, repairLoadError, repairError, repairBusy, repairRequest,
    refreshGenerationRepairs, openGenerationRepair, cancelGenerationRepair, confirmGenerationRepair, dismissGenerationRepair } = workspace
  let generationUnavailable = ''
  try { propGenerationTarget(variants, variantMax, generatingVariants) }
  catch (error) { generationUnavailable = (error as Error).message }
  return <div className="ga-form prop-area-content">
    <h3>{t('Model & variants')}</h3>
    <p className="ga-hint">{t('Uploads, generation, orientation and walkable surfaces apply immediately. Description, dimensions, ground offset and budgets belong to the draft.')}</p>
    <button type="button" className="ga-btn" disabled={variantBusy || !shownVariant}
      title={variantBusy ? t('This variant is generating right now.') : undefined}
      onClick={() => { void openRegeneration() }}>
      {t('Regenerate')}
    </button>
    <button type="button" className="ga-btn" disabled={pending || !!generationUnavailable}
      onClick={() => { void openRegeneration(true) }}>{t('+ Generate new variant')}</button>
    {pending && <p className="ga-hint" role="status">{t(variantBusy
      ? 'This variant is generating right now.'
      : 'Another variant is generating — a new variant can be added once it has finished.')}</p>}
    {!pending && generationUnavailable && <p className="ga-hint">{t(generationUnavailable)}</p>}
    <details className="prop-inspector-group" open>
      <summary>{t('Activity & seasons')}</summary>
      <PropVariantStrip propId={prop.id} variants={variants} max={variantMax}
        selected={variant} onSelect={setVariant} onChanged={meshesChanged}
        onEditVariant={queueVariant} onDeleted={onVariantDeleted}
        generating={generatingVariants} worldSeasons={worldSeasons}
        currentSeason={currentSeason} prepareVariantOperation={prepareVariantOperation} />
    </details>
    {(generationRepairs.length > 0 || repairLoading || repairLoadError) && <details className="prop-inspector-group">
      <summary>{t('Older generation results')} ({generationRepairs.length})</summary>
      <p className="ga-hint">{t('Result of an older paid job whose target variant is unknown — assign it to the selected variant or discard it.')}</p>
      <p><strong>{t('Selected target')}: {shownVariant
        ? shownVariant.label || `${t('Variant')} ${shownVariant.index + 1}`
        : t('No variant selected')}</strong></p>
      <button type="button" className="ga-btn ga-btn-sm" disabled={repairLoading || repairBusy}
        onClick={refreshGenerationRepairs}>{t('Refresh retained jobs')}</button>
      {repairLoading && <p className="ga-hint" role="status">{t('Loading retained jobs…')}</p>}
      {repairLoadError && <p role="alert">{t('Could not refresh retained jobs.')}{' '}{repairLoadError}</p>}
      {generationRepairs.map((entry) => <article key={entry.op_id} className="ga-form">
        <strong>{entry.original_name || t('Older generation')}</strong>
        <span className="ga-hint">{t('Backend')}: {entry.backend || t('Stored routing selection')}{' · '}
          {t('Tier')}: {entry.tier}{' · '}{entry.created_at}</span>
        <span className="ga-hint">{entry.original_variant === null
          ? t('Original target was not recorded.')
          : `${t('Originally requested')}: ${t('Variant')} ${entry.original_variant + 1}. ${t('Historical index, not a confirmed assignment.')}`}</span>
        <p role="status">{t(REPAIR_STATUS[entry.status])}</p>
        <details><summary>{t('Job details')}</summary>
          <p className="ga-hint" style={{ overflowWrap: 'anywhere' }}>{entry.op_id}</p>
          <p className="ga-hint">{entry.reason}</p>
        </details>
        <button type="button" className="ga-btn" disabled={!entry.can_resume || !shownVariant || variantBusy || repairBusy}
          onClick={() => { void openGenerationRepair(entry.op_id) }}>
          {t(entry.status === 'waiting_provider' ? 'Assign existing job…' : 'Assign retained result…')}
        </button>
        <button type="button" className="ga-btn ga-btn-sm ga-btn-danger" disabled={repairBusy}
          onClick={() => setDiscardId(entry.op_id)}>{t('Discard')}</button>
        {discardId === entry.op_id && <div role="group" aria-label={t('Discard older generation result?')}>
          <p>{t('Discard this result from the repair list? Stored files and gallery history are kept.')}</p>
          <button type="button" className="ga-btn ga-btn-danger" disabled={repairBusy}
            onClick={() => { void dismissGenerationRepair(entry.op_id).then(() => setDiscardId('')) }}>{t('Confirm discard')}</button>
          <button type="button" className="ga-btn" disabled={repairBusy} onClick={() => setDiscardId('')}>{t('Cancel')}</button>
        </div>}
      </article>)}
    </details>}
    {repairError && <p role="alert">{t(repairError)}</p>}
    {repairRequest && <PropWorkspaceDialog title={t('Explicitly assign retained result')}
      onCancel={cancelGenerationRepair}>
      <div className="ga-modal-body">
        <p><strong>{t('Target')}: {repairRequest.target.label
          || `${t('Variant')} ${repairRequest.target.index + 1}`}</strong></p>
        <p className="ga-hint" style={{ overflowWrap: 'anywhere' }}>{t('Stable variant ID')}: {repairRequest.target.uid}</p>
        <p>{t('Retained job')}: {repairRequest.repair.original_name}{' · '}
          {repairRequest.repair.backend || t('Stored routing selection')}{' · '}
          {t('Tier')}: {repairRequest.repair.tier}</p>
        <p role="status">{t(REPAIR_STATUS[repairRequest.repair.status])}</p>
        <p><strong>{t('The result replaces the target variant’s active file for the stored tier. Previous mesh files remain in the gallery.')}</strong></p>
        {repairRequest.target.model_file && <p className="ga-hint">
          {t('Current model preview')}: {repairRequest.target.model_file}</p>}
        <p>{t('No new provider job, source image or generation fee. If the old job is still running, only its result is collected. The target variant’s source images are kept.')}</p>
        {repairError && <p role="alert">{t(repairError)}</p>}
      </div>
      <div className="ga-modal-footer">
        <button type="button" className="ga-btn" disabled={repairBusy}
          onClick={cancelGenerationRepair}>{t('Cancel')}</button>
        <button type="button" className="ga-btn ga-btn-primary" disabled={repairBusy}
          onClick={() => { void confirmGenerationRepair() }}>{t('Confirm assignment and publish result')}</button>
      </div>
    </PropWorkspaceDialog>}
          {variantBusy ? (
            <span className="ga-hint">
              {t('Generating the model — this takes a few minutes.')}
            </span>
          ) : pending ? (
            // The prop-wide generation gate also covers other variants.
            <span className="ga-hint">
              {t('Another variant of this prop is generating.')}
            </span>
          ) : null}
          
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <div className="ga-form-section-label" style={{ margin: 0 }}>
              {t('Source image')}
            </div>
            {shownImage && srcOk ? (
              <img
                src={`/assets/props/${enc}/source?variant=${variant}&v=${reloadKey}`}
                alt={t('Source image')}
                onError={() => setSrcOk(false)}
                {...enlarge(
                  { src: `/assets/props/${enc}/source?variant=${variant}&v=${reloadKey}`, alt: `${prop.name} — ${t('Source image')}` },
                  { width: '100%', maxHeight: 300,
                    objectFit: 'contain', borderRadius: 8,
                    border: '1px solid var(--border, #30363d)',
                    background: 'rgba(255,255,255,0.04)' })}
                // AFTER the spread, deliberately: `enlarge` brings its own
                // "Click to enlarge" title, and the prompt would be the one
                // overwritten. Both fit in one tooltip.
                title={imageTip
                  ? `${imageTip}\n\n${t('Click to enlarge')}`
                  : t('Click to enlarge')}
              />
            ) : (
              <div className="ga-empty">
                {variants.length > 1
                  ? t('This variant has no source image yet — render one or upload a picture.')
                  : t('No source image (uploaded model).')}
              </div>
            )}
            
            {shownImage && srcOk ? (
              <span className="ga-hint" title={imageTip}>
                {shownImage.backend
                  ? `🖼 ${shownImage.backend}${shownImage.generated_at
                    ? ` · ${shownImage.generated_at.slice(0, 10)}` : ''}`
                  : t('No generation record for this image.')}
              </span>
            ) : null}
            <div style={{ display: 'flex', gap: 4 }}>
              <button type="button" className="ga-btn ga-btn-sm"
                style={{ flex: 1 }}
                disabled={variantBusy}
                // The SUBJECT travels with it: the dialog composes the final
                // prompt itself, so it has to compose from the text this
                // VARIANT renders from — its own, and the prop's NAME when it
                // has none (the server resolves it the same way for an empty
                // prompt, `props.variant_description`).
                onClick={() => { void openImageGeneration('front') }}
                title={variantBusy
                  ? t('This variant is generating right now.')
                  : t('Render a NEW source image FOR THIS VARIANT (backend and prompt in the dialog). Its 3D model stays until you re-mesh from the new image; the other variants keep their own images.')}>
                🖼 {variantBusy ? t('Generating…') : t('New image')}
              </button>
              <button type="button" className="ga-btn ga-btn-sm"
                disabled={variantBusy}
                onClick={() => sourceUploadRef.current?.click()}
                title={t('Upload a picture as this variant’s source image — the ⚙ re-mesh below then works from it.')}>
                {t('Upload image')}
              </button>
              <input ref={sourceUploadRef} type="file" accept="image/*"
                style={{ display: 'none' }}
                onChange={(e) => {
                  const f = e.target.files?.[0]
                  if (f) void uploadSource(f, 'front')
                  e.target.value = ''
                }} />
              <button type="button" className="ga-btn ga-btn-sm"
                onClick={onRefresh}
                title={t('Reload — fetch the current image and metadata (the render runs in the background).')}>
                🔄
              </button>
            </div>
            
            <div className="ga-form-section-label" style={{ margin: '6px 0 0' }}>
              {t('Extra views (multi-view mesh)')}
            </div>
            <div style={{ display: 'flex', gap: 6 }}>
              {PROP_EXTRA_VIEWS.map((view) => {
                const rec = shownVariant?.images?.[view]
                return (
                  <div key={view} style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 3 }}>
                    <span className="ga-hint">{t(VIEW_LABEL[view])}</span>
                    {rec ? (
                      <img
                        src={`/assets/props/${enc}/source?variant=${variant}&view=${view}&v=${reloadKey}`}
                        alt={t(VIEW_LABEL[view])}
                        {...enlarge(
                          { src: `/assets/props/${enc}/source?variant=${variant}&view=${view}&v=${reloadKey}`,
                            alt: `${prop.name} — ${t(VIEW_LABEL[view])}`,
                            caption: rec.backend ? `${rec.backend}${rec.generated_at ? ` · ${rec.generated_at.slice(0, 10)}` : ''}` : t('Uploaded') },
                          { width: '100%', aspectRatio: '1', objectFit: 'contain', borderRadius: 6,
                            border: '1px solid var(--border, #30363d)', background: 'rgba(255,255,255,0.04)' })}
                        title={`${rec.backend ? `🖼 ${rec.backend}${rec.generated_at ? ` · ${rec.generated_at.slice(0, 10)}` : ''}` : t('Uploaded')} — ${t('Click to enlarge')}`} />
                    ) : (
                      <div style={{ width: '100%', aspectRatio: '1', borderRadius: 6,
                        border: '1px dashed var(--border, #30363d)', display: 'flex',
                        alignItems: 'center', justifyContent: 'center' }}>
                        <span className="ga-hint">{t('none')}</span>
                      </div>
                    )}
                    <div style={{ display: 'flex', gap: 3 }}>
                      <button type="button" className="ga-btn ga-btn-sm" style={{ flex: 1 }}
                        disabled={variantBusy}
                        onClick={() => { void openImageGeneration(view) }}
                        title={t('Render this view (optionally with a front image as reference).')}>
                        🖼
                      </button>
                      
                      <button type="button" className="ga-btn ga-btn-sm"
                        disabled={variantBusy}
                        onClick={() => { setUploadView(view); viewUploadRef.current?.click() }}
                        title={variantBusy
                          ? t('This variant is generating right now.')
                          : t('Upload a picture as this view.')}>
                        ⬆
                      </button>
                      {rec ? (
                        <button type="button" className="ga-btn ga-btn-sm ga-btn-danger"
                          disabled={variantBusy}
                          onClick={() => {
                            if (armedView === view) { setArmedView(null); void deleteView(view) }
                            else setArmedView(view)
                          }}
                          title={variantBusy
                            ? t('This variant is generating right now.')
                            : armedView === view ? t('Click again to delete this view') : t('Delete this view image')}>
                          {armedView === view ? t('Sure?') : '×'}
                        </button>
                      ) : null}
                    </div>
                  </div>
                )
              })}
              <input ref={viewUploadRef} type="file" accept="image/*" style={{ display: 'none' }}
                onChange={(e) => {
                  const f = e.target.files?.[0]
                  if (f) void uploadSource(f, uploadView)
                  e.target.value = ''
                }} />
            </div>
            
            <button type="button" className="ga-btn ga-btn-sm"
              disabled={variantBusy || !shownImage || !srcOk}
              onClick={() => { void openMeshGeneration() }}
              title={variantBusy
                ? t('This variant is generating right now.')
                : t('Mesh THIS image again into the SELECTED variant — no new render, no new variant; backend, face count and texture size come from the dialog. Dims and markers stay.')}>
              ⚙ {t('3D from this image')}
            </button>
          </div>
          
          {shownVariant ? (
            <>
              <div className="ga-form-section-label">{t('Variant settings')}</div>
              <div className="ga-form-row" style={{ gap: 8, alignItems: 'center' }}>
                {DIM_FIELDS.map((f) => {
                  const shown = dimDraft[f.key] ?? String(shownVariant.dims[f.key])
                  return (
                    <label
                      key={f.key}
                      style={{ display: 'flex', alignItems: 'center', gap: 3 }}
                      title={`${t(f.title)} — ${t('the real extent of THIS variant’s mesh after the orientation fix.')} ${t('Edit one of the three and the other two follow this variant’s proportions — a prop is always scaled uniformly, so the trio says how big it is, its ratios say what shape.')}`}
                    >
                      <span className="ga-hint">{t(f.label)}</span>
                      <input
                        className="ga-input"
                        type="number"
                        min={0.01}
                        max={100}
                        step={0.05}
                        style={{ width: 74 }}
                        value={shown}
                        onChange={(e) => editDim(f.key, e.target.value)}
                        onBlur={(e) => commitDim(f.key, e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') e.currentTarget.blur()
                        }}
                      />
                      <span className="ga-hint">m</span>
                    </label>
                  )
                })}
              </div>
              {shownVariant.dims_estimated ? (
                <span className="ga-hint">
                  {t('Estimated — refined automatically when the model arrives.')}
                </span>
              ) : null}
              
              <SliderInput
                ariaLabel={t('Ground offset (m)')}
                label={<span className="ga-hint"
                  style={{ width: 66, flex: '0 0 auto' }}
                  title={t('Negative sinks this variant into the ground, positive lifts it off — the same amount everywhere it stands: rooms, yard, painted scatter, world props. Use it for a mesh that carries no root ball or base plate. 0 = it stands on the ground.')}>
                  ⤓ {t('Sink')}
                </span>}
                style={{ display: 'flex', fontSize: '0.85em' }}
                unit="m"
                slider={false}
                min={-SINK_LIMIT_M}
                max={SINK_LIMIT_M}
                step={0.01}
                value={shownVariant.ground_offset_m}
                onChange={commitSink}
                inputWidth={74}
              />
              
              <span className="ga-hint" style={{ marginTop: 4 }}>
                {t('Description (generation subject)')}
              </span>
              <textarea
                className="ga-textarea"
                rows={descOpen ? DESC_ROWS_OPEN : DESC_ROWS_REST}
                style={{ width: '100%', resize: 'vertical' }}
                value={descDraft ?? (shownVariant.description || '')}
                placeholder={t('Description (generation subject)')}
                title={t('What THIS variant’s source image is rendered from — the subject of its prompt. Empty = the render composes from the prop’s name. A new variant starts as a copy of the one it was added from, so a version differs by an edit: “…as a sapling”, “…broken”, “…covered in snow”.')}
                onFocus={() => setDescOpen(true)}
                onChange={(e) => {
                  setDescDraft(e.target.value)
                  queueVariant(variant, { description: e.target.value })
                }}
                onBlur={(e) => {
                  setDescOpen(false)
                  commitDesc(e.target.value)
                }}
              />
            </>
          ) : null}

          
    {previewFile && <p className="ga-hint">{t('Historical preview: orientation and walkable surface editing of the published model are locked.')}</p>}
    <fieldset className="prop-editor-fields" disabled={!!previewFile}>
          {shownHasMesh ? (
            <>
              <div className="ga-form-section-label">
                {t('Orientation fix')}
              </div>
              <div className="ga-form-row">
                {(['x', 'y', 'z'] as const).map((axis) => (
                  <span key={axis} style={{ display: 'inline-flex', gap: 2, alignItems: 'center' }}>
                    <button type="button" className="ga-btn ga-btn-sm"
                      disabled={!variantAreas}
                      onClick={() => { void rotate(axis) }} title={t('+90°')}>
                      ↻ {axis.toUpperCase()}
                    </button>
                    <input
                      key={`${axis}-${variant}-${variantRotation?.[axis] || 0}`}
                      className="ga-input" type="number" min={-360} max={720} step={0.1}
                      style={{ width: 64 }}
                      disabled={!variantAreas}
                      defaultValue={variantRotation?.[axis] || 0}
                      title={t('Exact angle in degrees — free rotation for meshes that came out tilted.')}
                      onBlur={(e) => { void setRotationAxis(axis, e.target.value) }}
                      onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
                    />
                  </span>
                ))}
              </div>
              <span className="ga-hint">
                {variantAreas
                  ? t('Orientation fix of this variant’s model file — persisted; the 3D client applies it on load.')
                  : (areasFailed
                    ? t('Could not read this prop’s areas — reload the page.')
                    : t('Reading the areas…'))}
              </span>
            </>
          ) : null}

          
          {shownHasMesh ? (
            <>
              <div className="ga-form-section-label">{t('Walkable surface')}</div>
              <div className="ga-form-row" style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <span className="ga-muted">{surfaceLabel}</span>
                <button type="button" className="ga-btn ga-btn-sm"
                  onClick={() => { void bakeSurface() }}
                  title={t('Bake the surface figures walk on — runs Blender in the background')}>
                  {t('Bake surface')}
                </button>
                
                {shownSurface?.file ? (
                  <>
                    <button type="button"
                      className={'ga-btn ga-btn-sm' + (removeArmed ? ' ga-btn-danger' : '')}
                      onClick={() => {
                        if (removeArmed) void removeSurface()
                        else setRemoveArmed(true)
                      }}
                      title={t('Throw the baked lattice away — figures walk on the terrain again until it is baked anew')}>
                      {removeArmed ? t('Really remove?') : t('Remove surface')}
                    </button>
                    {removeArmed ? (
                      <button type="button" className="ga-btn ga-btn-sm"
                        onClick={() => setRemoveArmed(false)}>
                        {t('Cancel')}
                      </button>
                    ) : null}
                  </>
                ) : null}
              </div>
            </>
          ) : null}
    </fieldset>
          <PropModelPanel
            prepareVariantOperation={prepareVariantOperation}
            propId={prop.id}
            variant={variant}
            variantUid={shownVariant?.uid || ''}
            reloadKey={reloadKey}
            preview={previewFile}
            onPreview={(file) => showStoredFile(file === shownVariant?.model_file ? '' : file)}
            onChanged={meshesChanged}
            pending={variantBusy}
            // The SELECTED variant's own budgets (v2 E5) — the distance-mesh
            // button names the low one, the reduction dialog opens on it, and
            // the two fields in the section edit them.
            faceTargets={{ high: shownVariant?.target_faces_high,
              low: shownVariant?.target_faces_low }}
            // Without a variant record there is nothing to commit into —
            // `commitFaces` would return on its own doorstep — so the two
            // fields are not offered at all, the same gate the Variant
            // settings in the column beside them stand behind.
            onEditFaceTarget={shownVariant ? commitFaces : undefined}
            backendFaces={backendFaces}
            onGenerating={onGenerating}
          />
  </div>
}
