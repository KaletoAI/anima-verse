/**
 * @anima/scene-render — the shared renderer routines of the scene contract.
 *
 * Consumers: `frontend` (admin floor-plan preview + 2D underlay) and
 * `client3d` (3D world map). Both used to carry these routines once each —
 * the clip shader was demonstrably built twice, independently.
 *
 * DELIBERATELY NOT here: camera/LOD/fades, culling application, labels,
 * pathfinding, NPC logic, editor overlays. View state stays per app.
 *
 * The primitive builders take their material from the caller — but HOW a
 * surface KIND is painted lives here (`materials.ts`), because both renderers
 * show the same lake. That appearance existed twice with different defaults
 * until 2026-07-28.
 *
 * three is a PARAMETER everywhere, never an import — otherwise the package
 * would pull the library into the main bundle of the admin, which loads it
 * lazily. Type imports are unaffected (they vanish on compile).
 */
export { placeModelSpec } from './place'
export type { PlaceOptions } from './place'

export { flatGround, storeyGroundLift } from './storeyGround'
export type { GroundSampler } from './storeyGround'

export { applyClipOutline, disposeClipMaterials, CLIP_MAX_POINTS } from './clip'

export { applyCutouts, CUTOUT_MAX_POLYS,
  CUTOUT_MAX_POINTS } from './cutouts'
export type { CutoutHandle } from './cutouts'

export { bilinear, latticeSample, sampleWorldHeight, worldHeightRange,
  tileKeyAt, heightAt, finestStep, rayGroundHit } from './worldHeight'
export type { RayGroundOpts, WorldHeightField, WorldHeightTiles,
  WorldHeightTileStats } from './worldHeight'

export { hillshadeImage, MAP_RELIEF_Z_FACTOR } from './hillshade'
export type { HillshadeOpts, HillshadeImage } from './hillshade'

export {
  decodeSd, layerPairAt, layerSdAt, layerSdBlockAt, layerWeight, lcNoise,
  lcPushedSd, packLayerWindow, terrainLayerGlsl, terrainLayerVertexGlsl,
  topLayerAt,
} from './layerCut'
export type {
  LayerMaskWindow, TerrainLayer, TerrainLayerBatch, TerrainLayerFormat,
  TerrainLayerIndex, TerrainLayerOverview, TerrainLayerTile,
} from './layerCut'

export {
  buildAreaGeometry, signedArea, polygonArea, cleanRing, shapePoints,
  AREA_EPS_M2,
} from './groundAreas'
export type { AreaGeometry, Point2 } from './groundAreas'

export {
  propGroundFit, scatterInstances, scatterSeed, scatterWantedCount,
  scatterSeedHash, scatterVariantIndex,
  seededRandom, pointInRing, pointInFootprint, worldToLocalXZ,
  footprintBlocks, footprintDistance, scatterClearM,
  SCATTER_CLEAR_HEIGHT_RATIO, SCATTER_MAX_PER_ENTRY, SCATTER_TRIES_PER_POINT,
  scatterCellAt, scatterCellInstances, scatterCellRing, scatterCellSeed,
  scatterCellSpan, scatterCellsInBox, scatterCellCountInBox, wantedScatterCells,
  SCATTER_CELL_M, SCATTER_CELLS_MAX, SCATTER_MAX_PER_CELL,
} from './scatter'
export type {
  PropGroundFit, ScatterCellOptions, ScatterEntry, ScatterFootprint,
  ScatterInstance, ScatterPoint2, ScatterSampleOptions,
} from './scatter'

export { SpecVerifier, VERIFY_EPS } from './verify'
export type { PrimitiveTarget, VerifyRow } from './verify'

export {
  buildPlate, buildWall, buildExtra, buildPlaceholder, wallLength,
  plateTargets, wallTargets,
} from './primitives'

export {
  FIGURE_ROOT_DROP, rootDropFor, pickVariant, pickModelVariant, MODEL_TIERS,
} from './types'

export {
  FIGURE_HEIGHT_M, anchorFigureBind, figureRootDrop, figureRootY,
} from './figure'

export { surfaceMaterial, updateSurfaceMaterials, setSurfaceSky,
  surfaceTimeUniform } from './materials'
export type { SurfaceMaterialSpec, SurfaceMaterialOptions } from './materials'

export type {
  ScenePayload, ScenePlate, SceneWall, SceneExtra, SceneModelSpec, ModelTier,
  SceneMarker, SceneStyle, SceneOpening, SceneRoom, SceneFloor,
  SceneBoundaryOpening, SceneDoorway, SceneProblem,
} from './types'
