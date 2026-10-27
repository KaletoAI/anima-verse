import { PropModelPanel } from './PropModelPanel'
import { PropVariantStrip } from './PropVariantStrip'
import { PROP_EXTRA_VIEWS } from './propTypes'
import { SliderInput } from '../../components/SliderInput'
import { DESC_ROWS_OPEN, DESC_ROWS_REST, DIM_FIELDS, SINK_LIMIT_M } from './variantFields'
import { VIEW_LABEL } from './usePropWorkspace'
import type { PropWorkspace } from './usePropWorkspace'

export function PropAssets({ workspace }: { workspace: PropWorkspace }) {
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
    currentSeason, onVariantDeleted, prepareVariantOperation } = workspace
  return <div className="ga-form prop-area-content">
    <h3>{t('Modell & Varianten')}</h3>
    <p className="ga-hint">{t('Upload, Generierung, Orientierung und begehbare Oberfläche werden sofort angewendet. Beschreibung, Maße, Bodenausgleich und Budgets gehören zum Entwurf.')}</p>
    <button type="button" className="ga-btn" disabled={pending}
      onClick={() => { void openRegeneration() }}>
      {t(pending ? 'Generating…' : 'Regenerate')} · {t('Ziel im Generierungsdialog prüfen')}
    </button>
    <details className="prop-inspector-group" open>
      <summary>{t('Aktivität & Jahreszeiten')}</summary>
      <PropVariantStrip propId={prop.id} variants={variants} max={variantMax}
        selected={variant} onSelect={setVariant} onChanged={meshesChanged}
        onEditVariant={queueVariant} onDeleted={onVariantDeleted}
        generating={generatingVariants} worldSeasons={worldSeasons}
        currentSeason={currentSeason} prepareVariantOperation={prepareVariantOperation} />
    </details>
          {variantBusy ? (
            <span className="ga-hint">
              {t('Generating the model — this takes a few minutes.')}
            </span>
          ) : pending ? (
            // Another variant of the same prop is busy — worth saying, but it
            // blocks nothing here.
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

          
    {previewFile && <p className="ga-hint">{t('Historische Vorschau: Orientierung und begehbare Oberfläche des veröffentlichten Modells sind gesperrt.')}</p>}
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
