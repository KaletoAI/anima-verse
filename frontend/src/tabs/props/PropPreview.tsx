import { FIGURE_HEIGHT_M } from '@anima/scene-render'
import { Model3DViewer } from '../characters/Model3DViewer'
import { previewEntry } from '../world/placeTypes'
import { saveScaleFigure } from './usePropWorkspace'
import type { PropWorkspace } from './usePropWorkspace'

export function PropPreview({ workspace }: { workspace: PropWorkspace }) {
  const { t, viewerRef, shownHasMesh, previewFile, enc, variant, reloadKey, prop, variantRotation, areaFrontal, setAreaView, areasOnView, areaOutlines, variantAreas, previewSlots, drawKind, onPolygonFaces, setShownBbox, light, waterController, markers, poseCatalog, previewPose, groups, shownDims, shownVariant, shownBbox, scaleFigure, placing, onPickPoint, variants, setScaleFigure } = workspace
  const { showStoredFile, navigate, saving } = workspace
  return <div className="ga-form prop-area-content">
          <div className="ga-form-section-label" style={{ marginTop: 0 }}>
            {t('3D preview')}
          </div>
    {previewFile && <div className="prop-history-notice" role="status">
      <strong>{t('Historische / alternative Meshvorschau')}</strong>
      <span>{previewFile}</span>
      <span>{t('Dateivorschau statt bearbeitbarer Full-Geometrie. Flächenwerkzeuge sind gesperrt.')}</span>
      <button type="button" className="ga-btn ga-btn-sm" onClick={() => showStoredFile('')}>{t('Aktives Modell zeigen')}</button>
    </div>}
          <div ref={viewerRef}>
          {shownHasMesh || previewFile ? (
            <Model3DViewer
              url={previewFile
                // A file picked in the gallery below — including ones no tier
                // serves (only the admin route hands those out).
                ? `/world/props/${enc}/variants/${variant}/models/files/${encodeURIComponent(previewFile)}?v=${reloadKey}`
                // The serving URL of the SELECTED variant; `variant` is
                // explicit even for the primary one, so the preview cannot
                // quietly fall back to another mesh.
                : `/assets/props/${enc}/model?variant=${variant}&v=${encodeURIComponent(prop.created_at || '')}-${reloadKey}`}
              format="glb"
              height={460}
              // The fix of the OPEN variant's file (v2 E1) — the prop has none
              // any more, and a neighbour's angles would tilt this mesh.
              rotation={variantRotation}
              // Switching variant or tier swaps ANOTHER VERSION of the same
              // object under the camera — the angle stays, "Reset view" frames
              // again on demand (§ B1).
              keepCamera
              // ── THE AREAS MODE (V11) ──────────────────────────────────
              // The one view is also the authoring view: the front view is a
              // mode of it, the outlines are drawn on it, a ring is projected
              // against ITS camera, and the assembly the panel below picks is
              // hung on this very mesh. Everything mesh-bound is offered only
              // while the SERVED file of the open variant is on screen — a
              // file picked in the gallery has another face order.
              frontal={areaFrontal}
              onFrontalChange={(on) => setAreaView({ frontal: on })}
              areaOutlines={areasOnView ? areaOutlines : undefined}
              meshLayout={areasOnView ? variantAreas?.mesh_layout : undefined}
              slots={areasOnView ? previewSlots : undefined}
              drawing={!saving && areasOnView && !!drawKind}
              drawThrough={drawKind === 'leaf'}
              onPolygonFaces={onPolygonFaces}
              onDrawCancel={() => setAreaView({ drawKind: '' })}
              leafBbox={areasOnView ? (variantAreas?.leaf_bbox || null) : null}
              onBounds={(b) => setShownBbox(b.size)}
              // ONE FIGURE PER SLOT, holding the pose the cycler stands on
              // (else the place type's default). `root_drop` comes from the
              // pose catalog because this prop is UNCOMPOSED — the payload's
              // `root_offset` only exists for a placed one.
              lightPoint={light || undefined}
              waterRegions={previewFile ? null : waterController.water}
              onPickModelPoint={!saving && waterController.shape && !previewFile ? waterController.pick : undefined}
              markers={markers.map((m) => {
                const entry = previewEntry(poseCatalog, m.group,
                                           m.id ? previewPose[m.id] : undefined)
                return {
                  at: m.at, group: m.group, capacity: m.capacity,
                  spacing_m: m.spacing_m, facing: m.facing,
                  slot_axis: m.slot_axis,
                  previewKind: entry?.animation,
                  previewYawOffset: entry?.yaw_offset,
                  rootDrop: groups[m.group]?.root_drop,
                }
              })}
              // The DISPLAYED variant's own size — the three numbers the strip
              // edits for exactly this chip.
              dimsOverlay={shownDims}
              // HOW DEEP IT STANDS, on the same draft the gauge above reads:
              // the viewer's ground plane goes where the scene's floor would
              // be (`bottom_y = floor + ground_offset_m`), so the buried part
              // disappears under it while the mesh, its W/D/H box and its
              // markers stay exactly where they are. Typing in the chip's
              // sink field moves the ground immediately — `variants` is the
              // draft, not the server's answer.
              groundOffsetM={shownVariant?.ground_offset_m ?? 0}
              // 1.7 m in MESH units — real scale = the displayed mesh's own
              // largest raw edge over its largest real dim; every figure in
              // the viewer (the marker poses and the standing reference)
              // sizes itself to that.
              figureHeight={(() => {
                const bb = shownBbox ?? (shownVariant?.primary ? prop.bbox : null)
                if (!bb) return 0
                const maxExtent = Math.max(bb[0], bb[1], bb[2])
                const maxDim = Math.max(shownDims.width_m, shownDims.depth_m,
                  shownDims.height_m) || 1
                return FIGURE_HEIGHT_M * (maxExtent / maxDim)
              })()}
              scaleFigure={scaleFigure}
              picking={!saving && (placing !== null || !!waterController.shape)}
              onPickPoint={onPickPoint}
            />
          ) : (
            <div className="ga-empty">
              {variants.length > 1
                ? t('This variant has no model yet — mesh the source image into it or upload a GLB below.')
                : t('No model yet — generate it or upload a GLB below.')}
              <button type="button" className="ga-btn" onClick={() => navigate('assets')}>{t('Modell & Varianten öffnen')}</button>
            </div>
          )}
          
          {shownHasMesh || previewFile ? (
            <label
              className="ga-hint"
              style={{ display: 'inline-flex', alignItems: 'center', gap: 4,
                marginTop: 4, cursor: 'pointer' }}
              title={t('Puts a FIXED 1.70 m person beside the model, on the ground the model stands IN, over a one-metre grid — the preview’s scale. The ground is solid, so whatever the sink buries really disappears under it. The figure never scales with the prop: if it looks wrong, the W/D/H of this variant are wrong. The place markers and their posed figures are part of the kit and go with it.')}
            >
              <input
                type="checkbox"
                checked={scaleFigure}
                onChange={(e) => {
                  setScaleFigure(e.target.checked)
                  saveScaleFigure(e.target.checked)
                }}
              />
              {t('Reference figure (1.70 m)')}
            </label>
          ) : null}
          
          <span className="ga-hint" style={{ display: 'block' }}>
            {t('Measured: {w} × {d} × {h} m.')
              .replace('{w}', shownDims.width_m.toFixed(2))
              .replace('{d}', shownDims.depth_m.toFixed(2))
              .replace('{h}', shownDims.height_m.toFixed(2))}
          </span>
          </div>
  </div>
}
