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

export { leafPivot, fixMatrix } from './leafPivot'
export type { LeafBox, FixEuler, LeafPivotSpec } from './leafPivot'

export { surfaceHeightAt, highestSurfaceAt, surfaceScale } from './surface'
export type { PlacedSurface, SurfacePlacement } from './surface'

export { flatGround, storeyGroundLift, storeyGroundRelift,
  tileDatumStep } from './storeyGround'
export type { GroundSampler, StoreyGroundStep,
  TileDatumStep } from './storeyGround'

export { applyClipOutline, disposeClipMaterials, CLIP_MAX_POINTS } from './clip'

export { normBoneName, restPoseOf, restCorrections, restSolesOf, transplantedRestPose, bindRelativeValues,
  bindRelativeClip, LEG_STANCE_TOLERANCE_DEG, TORSO_STANCE_TOLERANCE_DEG,
  FOOT_STANCE_TOLERANCE_DEG } from './clipRetarget'
export type { RestPose, RestCorrection } from './clipRetarget'

export { applyDepthCut, disposeCutMaterials } from './depthCut'

export { applySlotMaterials, disposeSlotMaterials, GLASS_PRESET,
  MATERIAL_PRESETS, slotFill, slotNameOf } from './slotMaterials'
export type { SlotTextureLoader, SlotFill } from './slotMaterials'

export { planeOfFaces, MirrorBudget, sharedMirrorBudget, attachMirror,
  disposeMirror, mirrorPlaneOf, mirrorRefreshes, MIRROR_PRESET } from './mirrorSurface'
export type { MirrorPlane, MirrorOptions, MirrorInfo } from './mirrorSurface'

export { applyCutouts } from './cutouts'
export type { CutoutHandle } from './cutouts'

export { bilinear, latticeSample, sampleWorldHeight, worldHeightRange,
  tileKeyAt, heightAt, finestStep, rayGroundHit } from './worldHeight'
export type { RayGroundOpts, WorldHeightField, WorldHeightTiles,
  WorldHeightTileStats } from './worldHeight'

export { hillshadeImage, MAP_RELIEF_Z_FACTOR } from './hillshade'
export type { HillshadeOpts, HillshadeImage } from './hillshade'

export {
  decodeSd, layerPairAt, layerSdAt, layerSdBlockAt, layerWeight,
  lcPushedSd, packLayerWindow, terrainLayerGlsl, terrainLayerVertexGlsl,
  topLayerAt,
} from './layerCut'
export type {
  LayerMaskWindow, TerrainLayer, TerrainLayerBatch, TerrainLayerFormat,
  TerrainLayerIndex, TerrainLayerOverview, TerrainLayerTile,
} from './layerCut'

export {
  buildAreaGeometry, signedArea, polygonArea, cleanRing, shapePoints,
} from './groundAreas'
export type { AreaGeometry, Point2 } from './groundAreas'

export {
  propGroundFit, scatterInstances, scatterSeed, scatterWantedCount,
  scatterSeedHash, scatterVariantIndex, scatterYaw,
  reshuffleEpoch,
  seededRandom, pointInRing, pointInFootprint, worldToLocalXZ,
  footprintBlocks, footprintDistance, scatterClearM,
  propBoxFootprint, propBoxFootprints,
  SCATTER_CLEAR_HEIGHT_RATIO, SCATTER_MAX_PER_ENTRY,
  scatterCellAt, scatterCellInstances, scatterCellRing, scatterCellSeed,
  scatterCellSpan, scatterCellsInBox, scatterCellCountInBox, wantedScatterCells,
  SCATTER_CELL_M, SCATTER_CELLS_MAX, SCATTER_MAX_PER_CELL,
} from './scatter'
export type {
  PropGroundFit, ScatterCellOptions, ScatterEntry, ScatterFootprint,
  ScatterInstance, ScatterOccupancy, ScatterPlaceMode, ScatterPoint2,
  ScatterPropBox, ScatterSampleOptions, ScatterYawMode,
} from './scatter'

export {
  ringEdgeAxis, ringSelectedEdges, ribbonSelectedEdges, lineAxis, areaAxis,
  polylabel, ringStations,
  scatterEdgeInstances, scatterCenterInstance,
} from './scatterAxis'
export type {
  PoleOfInaccessibility, RingStation, RingStationOptions,
  ScatterEdgeOptions, ScatterCenterOptions,
} from './scatterAxis'

export { OccupancyGrid, cellOccupancy } from './occupancy'
export type { CellGrids, CellOccupancy } from './occupancy'

export {
  STROKE_STYLES, isStrokeStyle, strokeSeed, decorateStroke,
  MAX_DECORATED_POINTS, STROKE_SPACING_DEFAULT_M, STROKE_AMPLITUDE_DEFAULT_M,
  strokeCentreLine, strokeStations, alongSeed,
} from './stroke'
export type {
  StrokeStyle, StrokeDeco, DecoratedStroke, StrokeRecipe,
  StrokeStationOptions,
} from './stroke'

export { SpecVerifier, VERIFY_EPS, inFrame, primitiveRows, placementRows } from './verify'
export type { PrimitiveTarget, VerifyRow } from './verify'

export {
  buildPlate, buildWall, buildExtra, buildPlaceholder, wallLength,
  plateTargets, wallTargets,
} from './primitives'

export { pickVariant, pickModelVariant } from './types'

export { FIGURE_HEIGHT_M, anchorFigureBind, clipHipsDrop, figureBox, figureRootY, inGarment, isGarmentNode,
  hipsTrackMedian, rigHipsHeight, standingHipsRef, clipHeightGroup, clipHeightOffsetM } from './figure'
export { clipShiftM } from './figure'
export type { ClipHeightOffsetsCm, ClipShiftCm } from './figure'

export { markerSlots, pairYaw, rotateXZ, pairPoints } from './placeGeometry'
export { clipCalibration, calibratedRoot, bakedHips, isEmptyDraft, EMPTY_DRAFT, alignmentLamp, alignmentDelta,
  median, wrapDeg, eulerYXZ, matQuat, ALIGN_GREEN, ALIGN_YELLOW } from './clipCalibration'
export type { AlignmentDraft, ContactRelation, SavedCalibration, ClipCalibration, RootInput, AlignmentLamp } from './clipCalibration'
export type { XZ } from './placeGeometry'

export { surfaceMaterial, updateSurfaceMaterials, setSurfaceSky,
  surfaceTimeUniform, surfaceSkyUniform, surfaceWaveNormal,
  waterFlowFactor, WATER_FLOW_FACTOR_MIN,
  WATER_FLOW_SPEED_DEFAULT_M_S, WATER_FLOW_SPEED_MAX_M_S } from './materials'
export type { SurfaceMaterialSpec, SurfaceMaterialOptions } from './materials'

export { strokeWidthM, waterfallsFrom, WATERFALL_MIN_DROP_M,
  WATERFALL_MIN_SLOPE } from './waterfall'
export type { Waterfall, WaterfallAxis, WaterfallKnot } from './waterfall'

export type {
  ScenePayload, ScenePlate, SceneWall, SceneExtra, SceneModelSpec, ModelTier,
  SceneMarker, SceneStyle, SceneOpening, SceneRoom, SceneFloor,
  SceneBoundaryOpening, SceneCorridor, SceneCutPlane, SceneDoorway, SceneProblem,
  SceneSlotValues, SceneStairs, SceneSurface,
} from './types'

export { createSecondaryMotion, stepSecondaryParticle, softMotionAngle, blendMotionParams, extensionCapsules, hairChainCapsules,
  tipBindFactors, withoutHairGroups } from './secondaryMotion'
export type { MotionGroup, MotionAttributeProfiles, ExtensionRigDeclaration, SecondaryMotionPayload, SecondaryMotion } from './secondaryMotion'

export { installSkinnedNormalCorrection } from './skinnedNormals'

export { placeTransform } from './placeTransform'
export type { MeshBox, PlaceTransform } from './placeTransform'

export { wallTransform, boxFaceExtents, boxFaceUVs, extraRotation,
  extraCorners, plateShape, placeholderBox } from './primitiveMath'
export { clipOutlinePoints, cutoutPolygons, clipPointInside, clipKeepsPoint,
  cutoutPadding, cutoutDiscardsPoint } from './clipMath'
export { cutPlaneData } from './depthCutMath'
export { surfaceFinish, applyAlphaCutoff } from './materials'
export type { VerifyPoint, VerifyBox, VerifyMeasurement, VerifyResult } from './verify'

export { gateWaterExtra, setWaterExtrasEnabled, waterExtrasUniform } from './waterExtras'
export { setMirrorsEnabled } from './mirrorSurface'

export { buildPropWater } from './propWater'
export type { ScenePropWater } from './types'

export { mapHipsTrack } from './hipsTrack'
export type { HipsTrackOptions } from './hipsTrack'

export { findLegChains, advanceProceduralPhase, proceduralGaitAmplitudes, proceduralIdleAmplitudes } from './proceduralGait'
export type { GaitBone, GaitBox, GaitChain } from './proceduralGait'

export { COLLISION_VERSION, HAIR_ONLY_REGIONS, PARTNER_ONLY_REGIONS, CAPSULE_REGION_COLORS, mat4Multiply, transformPoint, linearScale, jointNowFrom,
  capsuleNow, capsuleLineSegments, bindCollision, capsuleWireframe, placeCapsuleWireframe,
  createCollisionOverlay } from './collision'
export type { CollisionCapsule, CollisionPayload, ChannelRecord, ChannelOverride, CapsuleNow, JointNow, BoundCapsule,
  CollisionBinding, CollisionOverlay } from './collision'

export { COLLIDE_MAX, COLLIDE_PASSES, COLLIDE_EPS, COLLIDE_MIN_D, SQUEEZE_ROUNDS, SQUEEZE_STEPS, SQUEEZE_MIN_N,
  COLLIDE_GLSL_DECLARATIONS, COLLIDE_GLSL_PARTNER_DECLARATIONS, COLLIDE_GLSL_FUNCTION, COLLIDE_GLSL_FUNCTION_SQUEEZE,
  COLLIDE_GLSL_FUNCTION_SQUEEZE_PARTNER, COLLIDE_GLSL_APPLY, pushOutOfCapsules, capsuleInFrame,
  patchCollisionVertexShader, garmentKind, garmentCapsules, HAIR_REGIONS, EXTENSION_REGIONS, CLOTH_EXCLUDED_REGIONS, collidingGarmentMeshes, createGarmentCollision } from './garmentCollision'
export type { CollideCapsule, GarmentCollision, GarmentCollisionEntry, PushOptions } from './garmentCollision'

export { PARTNER_MAX, PARTNER_COLLIDE_MAX, PARTNER_PUSH_MAX_M, PARTNER_HYST_M, PARTNER_RELEASE_DEG_S,
  PARTNER_PREFILTER_SLACK_M, bodySphere, reachSphere, selectPartners, partnerCapsules, broadPhase, nearestCapsules,
  createPartnerList, snapshotPartnerLists, fillPartnerList, consumerPartnerCapsules, cullPartnerList, chainPartners,
  contactAnglePair, releasedAngle, snapshotPartner } from './partnerContact'
export type { Sphere, PartnerCapsule, PartnerSnapshot, PartnerList } from './partnerContact'

export { CHANNEL_BLEND_S, CHANNEL_HYST_M, CHANNEL_HYST_DEG, CHANNEL_GROW, channelCoords, inZone, allowedRadius,
  radialGuidanceAngle, depthJoint, depthScale, stepEngagement, channelGate, suppressedIds, guideRod, previewChannel, bindChannels, regionWeights, CHANNEL_REGION_K, CHANNEL_REGION_M,
  channelLineSegments, channelWireframe, placeChannelWireframe } from './channels'
export type { ChannelNow, Engagement } from './channels'
export { OPENING_MARGIN_M, OPENING_FALLOFF_M, OPENING_SKIP_M, OPENING_SKIP_DEG, OPENING_BAND_M, OPENING_BAND_K, OPENING_SLACK_M, OPENING_POSE_SLACK_M, openingBand,
  openedDistance, openingWeight, openingCandidates, openingDisplacement, displaceInto, channelOpening, openingReach,
  bindChannelOpening } from './channelOpening'
export type { OpeningSegment, OpeningOptions, ChannelOpeningBinding } from './channelOpening'

export { PROBE_NAME, PROBE_COLOR, probeCapsules, probeSweepOffset, probeSweptPose, probeSnapshot } from './partnerProbe'
export type { ProbeSourceCapsule, ProbePose } from './partnerProbe'

export { STRAND_ROWS, StrandMismatch, StrandSim, bindStrands, boxDepth, decodeStrandSdf, eyePointsEntered,
  invertAffine, lerpFrame, limitSegmentAngle, maxSdfDepthMm, restInsideBox, scalpCameras, scalpExposure, SCALP_CAMERA_FOV_DEG,
  strandCapsules, strandParams, strandSdfAt, strandTargets, STRAND_LIMITS, pickStrandFigures, RootInertia,
  STRAND_ROOT_LIMITS, STRAND_STRETCH_MAX, STRAND_RECORD_VERSION } from './hairSimMath'
export type { HairStrandRecord, StrandBinding, StrandFrame, StrandParams, StrandSdf, StrandCandidate,
  StrandLimits } from './hairSimMath'

export { createStrandHair, STRAND_DT, STRAND_MAX_STEPS, STRAND_RESET_DELTA_S, STRAND_RESET_JUMP_M,
  STRAND_MS_PER_CARD } from './hairSim'
export type { StrandHair } from './hairSim'

export { FOOT_POSE_VERSION, SEAT_FADE_M, applyFootPose, applyFootPoseToPose, footPoseLiftM, footPoseMatches,
  footContactsNow, footPoseRest, seatRaise, seatFootLift } from './footPose'
export type { FootPose, FootPoseRest, FootContact, FootSide } from './footPose'

export { GROUND_SAMPLE_FRAMES, GROUND_SAMPLE_VERTICES, SOLE_LEVEL_M, groundOffsetOf, soleGroundOffsetOf,
  clipGroundOffset, measureClipGround } from './clipGround'
export type { ClipGroundOptions } from './clipGround'

export { BAND_LO_CM, BAND_HI_CM, VY_LO_CM_S, VY_HI_CM_S, GROUND_PCT, MIN_WEIGHT, FULL, CONTACT_POINTS, ramp,
  groundHeights, contactWeights, footLockPath, maxPlantedDrift } from './footLock'
export type { Vec3, Tracks } from './footLock'

export { qrot, rotationBetween, twoBoneIk } from './twoBoneIk'
export type { Quat } from './twoBoneIk'

export { PLANT_FADE_S, PLANT_FALLBACK_FPS, plantSampleTimes, fadeRuns, levelTurn, plantFootPose } from './footPlant'
export type { FootPlantOptions } from './footPlant'

// The per-figure runtime of the two-phase frame (Ruling A110): client3d's `Figure` wraps it, the Game-Admin
// place preview drives it directly — one frame order, one secondary motion, one partner pass.
export { FigureRuntime, createFigureRuntime } from './figureRuntime'
export type { FigureRuntimeOptions, ChannelOccupants, FigureInspection, OpeningInspection } from './figureRuntime'
export { contactCapsules, inspectFrame, segmentSegmentDistance } from './figureInspect'
export type { CapsuleContact, FrameInspection } from './figureInspect'
export { planPartnerFrame } from './partnerFrame'
export type { FrameFigure } from './partnerFrame'
export { runFigureFrame, OPENING_BUDGET } from './frameLoop'
export type { FramePhaseB, FrameEntry, FrameLoopState } from './frameLoop'
export { strandCandidates } from './strandBudget'
export type { StrandFigureView } from './strandBudget'
export { slotFor } from './placeSlot'
export type { PlaceEntry } from './placeSlot'
export { solveContactShift, contactReport, contactLamp, entryFrame, bodyOverlap, CONTACT_ENTRY_WEIGHT,
  CONTACT_ENTRY_GREEN_MM, CONTACT_CLEAR_MM } from './channelContact'
export type { ContactSample, ContactReport, ContactLamp } from './channelContact'
export { CONTACT_TARGETS, POINT_TARGETS, PROVISIONAL_TARGETS, TARGET_RADIUS_M, HEAD_FRONT, TARGET_BONE_NAMES, isContactTarget,
  isPointTarget, targetFrame, targetFrames, orientAlong, targetLamp } from './contactTarget'
export type { ContactTarget, PointTarget, TargetBones, TargetFrame } from './contactTarget'
export { solvePairFix, fixPoint, unfixPoint, fixSample, fixRoot, composeFix, turnMatrix, matrixTurn, fixAnglesDeg,
  findContact, contactSampleOf, turnAxes, createPairFit, pairFitTotal, pairFitObserve, FIT_MIN_SAMPLES, FOLLOW, partnerTurnFix, fixPivot, ALIGN_FIT, RUNTIME_FIT, FIT_ANGLE_WEIGHT_M, NO_FIX,
  pairInterpenetration, clearLamp, PART_REGIONS, CLEAR_GREEN_MM, CLEAR_YELLOW_MM } from './pairFit'
export type { FitSample, PairFix, FitBounds, FitOptions, PairFitState, ClearLamp } from './pairFit'
export { attachedPartIndex, partBoneNames, PART_WEIGHT_SHARE } from './attachedPart'
