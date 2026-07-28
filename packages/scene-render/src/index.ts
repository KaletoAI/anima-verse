/**
 * @anima/scene-render — the shared renderer routines of the scene contract.
 *
 * Consumers: `frontend` (admin floor-plan preview + 2D underlay) and
 * `client3d` (3D world map). Both used to carry these routines once each —
 * the clip shader was demonstrably built twice, independently.
 *
 * DELIBERATELY NOT here: camera/LOD/fades, culling application, labels,
 * pathfinding, NPC logic, editor overlays. View state stays per app. The
 * primitive builders draw the same line one level down: geometry here,
 * material from the caller.
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

export { SpecVerifier, VERIFY_EPS } from './verify'
export type { PrimitiveTarget, VerifyRow } from './verify'

export {
  buildPlate, buildWall, buildExtra, buildPlaceholder, wallLength,
  plateTargets, wallTargets,
} from './primitives'

export { FIGURE_ROOT_DROP, rootDropFor } from './types'

export type {
  ScenePayload, ScenePlate, SceneWall, SceneExtra, SceneModelSpec,
  SceneMarker, SceneExit, SceneStyle, SceneOpening, SceneRoom,
} from './types'
