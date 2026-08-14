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

export { applyClipOutline, disposeClipMaterials, CLIP_MAX_POINTS } from './clip'

export { applyCutouts, disposeCutoutMaterials, CUTOUT_MAX_POLYS,
  CUTOUT_MAX_POINTS } from './cutouts'
export type { CutoutHandle } from './cutouts'

export { sampleTerrain, drapeGeometry, TERRAIN_CELLS } from './terrain'

export { sampleWorldHeight, sampleGroundHeight, worldHeightRange,
  maxWorldHeightIn, worldHeightRangeIn } from './worldHeight'
export { tileKeyAt, sampleCompositeHeight, sampleCompositeGroundHeight,
  maxCompositeHeightIn, compositeHeightRangeIn } from './worldHeight'
export type { WorldHeightField, WorldHeightTiles } from './worldHeight'

export { gridPlate, subdivideOnGrid, gridStepFor, GRID_MAX_CELLS } from './gridMesh'
export type { GridBox, GridGeometry, PlateGeometry } from './gridMesh'

export {
  buildAreaGeometry, signedArea, polygonArea, cleanRing, shapePoints,
  AREA_EPS_M2, AREA_POLYGON_OFFSET,
} from './groundAreas'
export type { AreaGeometry, Point2 } from './groundAreas'

export {
  propGroundFit, scatterInstances, scatterSeed, seededRandom, pointInRing,
  pointInFootprint, worldToLocalXZ, SCATTER_MAX_PER_ENTRY,
  SCATTER_TRIES_PER_POINT,
} from './scatter'
export type {
  PropGroundFit, ScatterEntry, ScatterFootprint, ScatterInstance,
  ScatterPoint2, ScatterSampleOptions,
} from './scatter'

export { SpecVerifier, VERIFY_EPS } from './verify'
export type { PrimitiveTarget, VerifyRow } from './verify'

export {
  buildPlate, buildWall, buildExtra, buildPlaceholder, wallLength,
  plateTargets, wallTargets,
} from './primitives'

export { FIGURE_ROOT_DROP, rootDropFor, pickVariant, MODEL_TIERS } from './types'

export { surfaceMaterial, updateSurfaceMaterials, setSurfaceSky,
  disposeSurfaceMaterials, surfaceTimeUniform } from './materials'
export type { SurfaceMaterialSpec, SurfaceMaterialOptions } from './materials'

export type {
  ScenePayload, ScenePlate, SceneWall, SceneExtra, SceneModelSpec, ModelTier,
  SceneMarker, SceneStyle, SceneOpening, SceneRoom, SceneTerrain,
  SceneBoundaryOpening, SceneDoorway, SceneProblem,
} from './types'
