import { SliderInput } from '../../components/SliderInput'
import { groupLabel } from '../world/placeTypes'
import { AT_AXES, AT_MAX } from './usePropWorkspace'
import type { PropWorkspace } from './usePropWorkspace'
import { PropSpatialBindings } from './PropSpatialBindings'
import { propMetresPerUnit } from './spatialBindings'

export function PropPlaces({ workspace }: { workspace: PropWorkspace }) {
  const { t, markers, selIdx, setSelectedMarker, placing, setPlacing, groups, addMarker, firstGroup, shownHasMesh, previewFile, drawKind, armPlacing, selMarker, patchMarker, groupOptions, removeMarker, shownDims, setMarkerAt, selCapacity, selPoses, setPreview, selPoseIdx } = workspace
  const rawBbox = workspace.shownBbox ?? (workspace.shownVariant?.primary ? workspace.prop.bbox : null)
  const metresPerUnit = rawBbox ? propMetresPerUnit(rawBbox, shownDims, workspace.variantRotation) : 0
  return <div className="ga-form prop-area-content">
          <PropSpatialBindings workspace={workspace} />
          {previewFile && <p role="status" className="ga-hint">{t('Historische Meshvorschau: Körperanker und Zugänge sind gesperrt. Zum aktiven Modell zurückkehren, um zu bearbeiten.')}</p>}
          <fieldset className="prop-editor-fields" disabled={workspace.saving || !!previewFile || !workspace.shownVariant}>
          <div className="ga-form-section-label">{t('Prop places')}</div>
          <span className="ga-hint">
            {t('Object-local PLACES a character is seated on — each names a place type of the pose catalog and takes as many figures as its capacity. They belong to THIS variant, because at = fraction of ITS model bounding box (X = width, Y = height, Z = depth); the range reaches from -0.5 to 2, because seats and lying surfaces sit on the hull or outside it. Place roughly with ✥, fine-tune with the sliders — the figures in the preview follow live.')}
          </span>
          <div className="ga-list-detail">
            <div className="ga-list-detail-side">
              {markers.length === 0 ? (
                /* `ga-empty` carries no style in this stylesheet — the muted
                   hint is what every other "nothing here yet" line uses. */
                <span className="ga-hint">{t('No places yet.')}</span>
              ) : (
                <ul className="ga-list">
                  {markers.map((m, i) => (
                    <li key={m.id || i}>
                      <button
                        type="button"
                        className={`ga-list-row${i === selIdx ? ' is-active' : ''}`}
                        onClick={() => {
                          setSelectedMarker(i)
                          // A pick armed for the place just left behind would
                          // move THAT one on the next click in the viewer.
                          // 'add' names no place yet and stays armed.
                          if (typeof placing === 'number') setPlacing(null)
                        }}
                      >
                        <span className="ga-list-row-main">
                          🎯 {i + 1}
                          
                          <span className="ga-list-row-sub" style={{
                            minWidth: 0, overflow: 'hidden',
                            textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            · {groupLabel(groups, m.group)}
                          </span>
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                <button type="button" className="ga-btn ga-btn-sm" onClick={addMarker}
                  disabled={!firstGroup}
                  title={firstGroup
                    ? t('Add a place at the box centre — pick its type, then position it with ✥ or the X/Y/Z sliders.')
                    : t('No place types yet — the Poses tab defines them.')}>
                  + {t('Marker')}
                </button>
                <button
                  type="button"
                  className={`ga-btn ga-btn-sm${placing === 'add' ? ' ga-btn-primary' : ''}`}
                  // Placing means clicking the mesh in the viewer — so it needs
                  // a mesh SHOWN there, not just one somewhere on the prop. And
                  // a marker needs a place type to name: without the catalog
                  // the server would drop it on save.
                  // …and not while a ring is being drawn: the two arm modes
                  // share the one canvas (V11).
                  disabled={!(shownHasMesh || previewFile) || !firstGroup || !!drawKind}
                  onClick={() => armPlacing('add')}
                  title={drawKind
                    ? t('Finish or cancel the surface you are drawing first — the ring and the marker pick share the one preview.')
                    : t('Then click the spot on the model in the viewer to drop a marker there (Esc cancels) — like placing markers on the floor plan.')}
                >
                  🎯 {placing === 'add' ? t('Click the model…') : t('Place marker')}
                </button>
              </div>
            </div>
            
            {selMarker ? (
              <div className="ga-marker-card">
                <p className="ga-hint">{t('Verwendende Aktionen dieses Körperankers')}: {(workspace.shownVariant?.action_bindings || [])
                  .filter(b => !!selMarker.id && b.marker_ids.includes(selMarker.id))
                  .map(b => workspace.actions.find(a => a.id === b.action_id)?.name || b.action_id).join(', ') || t('Keine')}</p>
                <div className="ga-form-row">
                  <span className="ga-hint" style={{ minWidth: 20 }}>🎯 {selIdx + 1}</span>
                  <select
                    className="ga-input"
                    style={{ flex: 1, minWidth: 0 }}
                    value={selMarker.group}
                    title={t('Place type of the pose catalog — WHAT this spot is, not which clip plays on it. A character taking a pose of this type is seated here.')}
                    onChange={(e) => patchMarker(selIdx, { group: e.target.value })}
                  >
                    {groupOptions.map((k) => (
                      <option key={k} value={k}>{groupLabel(groups, k)}</option>
                    ))}
                    
                    {selMarker.group && !groupOptions.includes(selMarker.group) ? (
                      <option value={selMarker.group}>{selMarker.group}</option>
                    ) : null}
                  </select>
                  <button
                    type="button"
                    className={`ga-btn ga-btn-sm${placing === selIdx ? ' ga-btn-primary' : ''}`}
                    // One canvas, one gesture: while a ring is being drawn the
                    // SVG over the viewer swallows every click a pick needs.
                    disabled={!shownHasMesh || !!previewFile || workspace.saving}
                    onClick={() => armPlacing(selIdx)}
                    title={drawKind
                      ? t('Finish or cancel the surface you are drawing first — the ring and the marker pick share the one preview.')
                      : t('Then click the spot on the model in the viewer to move this marker there (Esc cancels).')}
                  >
                    ✥
                  </button>
                  <button
                    type="button"
                    className="ga-btn ga-btn-sm ga-btn-danger"
                    onClick={() => removeMarker(selIdx)}
                    title={t('Remove this marker')}
                  >
                    ×
                  </button>
                </div>
                {AT_AXES.map((axis, ax) => {
                  // Body coordinates remain fractions of the raw box even after an orientation fix.
                  const dimM = rawBbox ? rawBbox[ax] * metresPerUnit : shownDims[axis.dim]
                  return (
                    <SliderInput
                      key={axis.label}
                      className="ga-marker-axis"
                      style={{ display: 'flex', fontSize: '0.8em' }}
                      label={(
                        <span className="ga-hint" style={{ width: 66, flex: '0 0 auto' }}>
                          {t(axis.label)}
                        </span>
                      )}
                      ariaLabel={t(axis.label)}
                      min={axis.min}
                      max={AT_MAX}
                      step={0.01}
                      value={selMarker.at[ax]}
                      onChange={(v) => setMarkerAt(selIdx, ax as 0 | 1 | 2, v)}
                      sliderWidth="auto"
                      sliderStyle={{ flex: 1, minWidth: 60 }}
                      inputWidth={72}
                      readback={(
                        <span className="ga-hint" style={{ width: 58, flex: '0 0 auto', textAlign: 'right' }}
                          title={t('Bruchteil der rohen Modell-Bounding-Box, in Meter derselben Viewer-Skalierung umgerechnet.')}>
                          {(selMarker.at[ax] * dimM).toFixed(2)} m
                        </span>
                      )}
                    />
                  )
                })}
                <SliderInput
                  className="ga-marker-axis"
                  style={{ display: 'flex', fontSize: '0.8em' }}
                  title={t('Facing in degrees: 0 south, 90 east, 180 north, 270 west. Unset = the client default (face the neighbours).')}
                  label={<span className="ga-hint" style={{ width: 66, flex: '0 0 auto' }}>🧭 {t('Facing')}</span>}
                  ariaLabel={t('Facing')}
                  min={0}
                  max={360}
                  step={5}
                  fineStep={1}
                  value={selMarker.facing}
                  fallback={0}
                  clearable
                  placeholder="—"
                  onChange={(v) => patchMarker(selIdx, { facing: ((v % 360) + 360) % 360 })}
                  onClear={() => patchMarker(selIdx, { facing: undefined })}
                  sliderWidth="auto"
                  sliderStyle={{ flex: 1, minWidth: 60 }}
                  inputWidth={72}
                >
                  <button
                    type="button"
                    className="ga-btn ga-btn-sm"
                    style={{ width: 58, flex: '0 0 auto' }}
                    disabled={selMarker.facing === undefined}
                    onClick={() => patchMarker(selIdx, { facing: undefined })}
                    title={t('Unset the facing — the client decides.')}
                  >
                    ✕
                  </button>
                </SliderInput>
                
                <SliderInput
                  className="ga-marker-axis"
                  style={{ display: 'flex', fontSize: '0.8em' }}
                  title={t('How many figures this place takes — a bench seats several. The slots line up across the facing.')}
                  label={<span className="ga-hint" style={{ width: 66, flex: '0 0 auto' }}>{t('Capacity')}</span>}
                  ariaLabel={t('Capacity')}
                  min={1}
                  max={8}
                  step={1}
                  value={selCapacity}
                  onChange={(v) => {
                    const cap = Math.max(1, Math.min(8, Math.round(v)))
                    // Capacity 1 is a single spot and carries neither key —
                    // the same shape the server stores.
                    patchMarker(selIdx, cap > 1
                      ? { capacity: cap }
                      : { capacity: undefined, spacing_m: undefined,
                          slot_axis: undefined })
                  }}
                  sliderWidth="auto"
                  sliderStyle={{ flex: 1, minWidth: 60 }}
                  inputWidth={72}
                />
                {selCapacity > 1 ? (
                  <SliderInput
                    className="ga-marker-axis"
                    style={{ display: 'flex', fontSize: '0.8em' }}
                    title={t('Distance between neighbouring slots in metres (0.6 = a bench seat).')}
                    label={<span className="ga-hint" style={{ width: 66, flex: '0 0 auto' }}>{t('Spacing')}</span>}
                    ariaLabel={t('Spacing')}
                    min={0.2}
                    max={3}
                    step={0.05}
                    fineStep={0.01}
                    value={selMarker.spacing_m ?? 0.6}
                    onChange={(v) => patchMarker(selIdx, { spacing_m: Math.round(v * 100) / 100 })}
                    unit="m"
                    sliderWidth="auto"
                    sliderStyle={{ flex: 1, minWidth: 60 }}
                    inputWidth={72}
                  />
                ) : null}
                
                {selCapacity > 1 ? (
                  <SliderInput
                    className="ga-marker-axis"
                    style={{ display: 'flex', fontSize: '0.8em' }}
                    title={t('Which way the row of slots runs, in degrees off the facing. 90 = across it — right for sitting and standing, where the shoulders are the narrow side. 0 = along it, which is what a bed wants: a lying figure already lies across its facing, so a 90° row would stack the sleepers head-to-foot instead of side by side. Watch the preview figures while you turn it.')}
                    label={<span className="ga-hint" style={{ width: 66, flex: '0 0 auto' }}>{t('Slot axis')}</span>}
                    ariaLabel={t('Slot axis')}
                    min={0}
                    max={180}
                    step={5}
                    fineStep={1}
                    value={selMarker.slot_axis ?? 90}
                    onChange={(v) => patchMarker(selIdx,
                      { slot_axis: Math.max(0, Math.min(180, Math.round(v))) })}
                    unit="°"
                    sliderWidth="auto"
                    sliderStyle={{ flex: 1, minWidth: 60 }}
                    inputWidth={72}
                  />
                ) : null}
                {selPoses.length ? (
                  <div className="ga-form-row" style={{ fontSize: '0.8em' }}
                    title={t('Which pose of this place type the preview figures hold — view only, nothing is stored. Every slot shows it; a pair pose seats both halves around the marker.')}>
                    <span className="ga-hint" style={{ width: 66, flex: '0 0 auto' }}>
                      {t('Pose')}
                    </span>
                    <button type="button" className="ga-btn ga-btn-sm"
                      onClick={() => setPreview(selPoses[(selPoseIdx + selPoses.length - 1) % selPoses.length])}>
                      ◀
                    </button>
                    <span className="ga-hint" style={{ flex: 1, minWidth: 0 }}>
                      {selPoses[selPoseIdx]} ({selPoseIdx + 1}/{selPoses.length})
                    </span>
                    <button type="button" className="ga-btn ga-btn-sm"
                      onClick={() => setPreview(selPoses[(selPoseIdx + 1) % selPoses.length])}>
                      ▶
                    </button>
                  </div>
                ) : null}
              </div>
            ) : null}
          </div>
          </fieldset>
  </div>
}
