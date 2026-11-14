import type { ModelWater } from '../props/propTypes'
import { accessWorldPoint, accessLocalPoint } from '../props/accessGeometry'
/**
 * Model3DViewer — interactive preview of a generated character mesh.
 *
 * three.js and its loaders are imported DYNAMICALLY: they are ~1 MB and only
 * the 3D tab needs them, so Vite splits them into their own chunk that loads
 * on first view instead of bloating the admin bundle.
 *
 * Format follows the file: the gateway decides what it produces (Trellis2 ->
 * FBX), so the loader is picked by extension.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode, MouseEvent as ReactMouseEvent } from 'react'
import type { AnimationClip, Material, Mesh, MeshStandardMaterial, Object3D,
  Quaternion, Vector3 } from 'three'
import { FIGURE_HEIGHT_M, anchorFigureBind, applySlotMaterials,
  installSkinnedNormalCorrection, createSecondaryMotion, bindRelativeClip, clipHipsDrop, disposeSlotMaterials, figureRootY,
  hipsTrackMedian, leafPivot, markerSlots, pairPoints, pairYaw,
  restCorrections, restPoseOf, rigHipsHeight,
  standingHipsRef, clipHeightOffsetM, clipHeightGroup, createCollisionOverlay, collidingGarmentMeshes,
  createGarmentCollision, applyAlphaCutoff, applyFootPose, applyFootPoseToPose, figureBox, footPoseLiftM,
  footPoseMatches, transplantedRestPose, measureClipGround, clipGroundOffset, plantFootPose,
  seatFootLift, createStrandHair } from '@anima/scene-render'
import type { SecondaryMotion, SecondaryMotionPayload, RestPose, ClipHeightOffsetsCm,
  CollisionOverlay, CollisionPayload, FootPose, GarmentCollision, HairStrandRecord, StrandHair } from '@anima/scene-render'
import { previewMotionAmp, previewRootPose, TURN_S } from './hairstylesModel'
import type { PreviewMotionKind } from './hairstylesModel'
import { applyViewerTexture, zeroViewerMetalness } from './modelTexture'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet } from '../../lib/api'
import { attachModelTurn, configureViewControls, isUpright, poseMatrix, wrapAngle } from '../../lib/modelTurn'
import type { ModelTurnControl } from '../../lib/modelTurn'
import { ModelTurnHint } from '../../components/ModelTurnHint'
import type { SceneModelSpec } from '../world/worldTypes'
import { buildMeasureAids, disposeAids, referenceFigure,
  type MeasureKey } from '../world/measureKit'
import { alignMeshLayout, meshLayoutOf, pointInPolygon,
  polygonArea } from '../props/faceSelect'
import { closesOnFirstPoint, shouldRefit } from '../props/viewerMath'
import { CLOSE_TOL_PX } from '../world/planGeometry'
import { areaKindOf } from '../props/propTypes'
import type { AreaOutline, LeafBbox, MeshLayoutEntry,
  PropSlotValues } from '../props/propTypes'
import { BuiltAtCaption } from './BuiltAtCaption'
import { createExtensionGroupOverlay, extensionGroupIds, groupColorCss } from './extensionGroupOverlay'
import type { ExtensionGroupOverlay } from './extensionGroupOverlay'
import { FreshnessCorner } from './FreshnessBadge'
import type { Freshness } from './FreshnessBadge'

const _deg = (v?: number) => ((v || 0) * Math.PI) / 180

/**
 * The sliver of GLTFLoader's parser this file uses: which glTF node/mesh/
 * primitive an object came from, and the raw node names. Typed here rather
 * than imported, because `GLTFParser` is not part of three's public types and
 * only these three fields are read.
 */
interface GltfParser {
  associations?: Map<Object3D, { nodes?: number; meshes?: number; primitives?: number }>
  json?: { nodes?: Array<{ name?: string }> }
}

/** Ceiling on ONE hand-drawn selection ring. A selection polygon is a gesture,
 *  not a stored shape (the map's `MAX_POINTS` budgets a saved outline), and a
 *  panel is ringed in a handful of clicks — 64 is generous and keeps the
 *  per-triangle test cheap. */
const MAX_POLYGON_POINTS = 64

// ── Shared marker-figure sources (module cache — one fetch per session,
// every viewer instance clones from these) ──
let _figPromise: Promise<Object3D | null> | null = null
export const loadTestFigure = (): Promise<Object3D | null> => {
  if (!_figPromise) {
    _figPromise = (async () => {
      try {
        const meta = await apiGet<{ format?: string }>('/play/test-figure/meta')
        let obj: Object3D
        if ((meta.format || 'glb') === 'fbx') {
          const { FBXLoader } = await import('three/examples/jsm/loaders/FBXLoader.js')
          obj = await new FBXLoader().loadAsync('/play/test-figure/model')
        } else {
          const { createGLTFLoader } = await import('../../lib/gltfLoader')
          obj = (await createGLTFLoader().loadAsync('/play/test-figure/model')).scene
        }
        // Neutral clay figure — placement and scale are judged, not a look.
        const THREE = await import('three')
        installSkinnedNormalCorrection(THREE)
        const clay = new THREE.MeshStandardMaterial({
          color: 0x9aa4af, roughness: 0.85, metalness: 0,
        })
        obj.traverse((o: Object3D) => {
          const mesh = o as Mesh
          if (!mesh.isMesh) return
          const old = mesh.material
          mesh.material = clay
          if (Array.isArray(old)) old.forEach((m) => m.dispose?.())
          else old?.dispose?.()
        })
        return obj
      } catch {
        return null
      }
    })()
  }
  return _figPromise
}
/** One entry of `GET /assets/animation-clips`: the clip's KIND, the half of a
 *  pair it plays (`a`/`b`, empty = solo) and the figure set it was made for. */
interface ClipEntry { kind: string; role?: string; set: string; url: string
  height_offsets_cm?: ClipHeightOffsetsCm }
/** The sidecar of a complete PAIR kind (§ A8a): where each half stands around
 *  the shared anchor, in metres of the clip's own frame. */
interface PairMeta {
  geometry?: { roles?: Record<string, { anchor_xz_m?: [number, number] }> }
}
let _clipIndexPromise: Promise<{ clips: ClipEntry[]
                                 pairs: Record<string, PairMeta> }> | null = null
/** The clip index — ONE fetch per session, shared by every viewer instance.
 *  It carries the pair sidecars too, so a pair pose can be seated without a
 *  second request. */
const clipIndex = () => {
  if (!_clipIndexPromise) {
    _clipIndexPromise = apiGet<{ clips?: ClipEntry[]; pairs?: Record<string, PairMeta> }>(
      '/assets/animation-clips')
      .then((d) => ({ clips: d.clips || [], pairs: d.pairs || {} }))
      .catch(() => ({ clips: [], pairs: {} }))
  }
  return _clipIndexPromise
}
/** The reference RIG every library clip is authored on
 *  (`/assets/animation-rig`), reduced to the two things the previews read off
 *  it: its REST POSE (`rest`, for `restCorrections`) and its rest HIPS HEIGHT
 *  (`hipsY`, the standing reference — see `standHipsRef`). One fetch per
 *  session, shared by every admin preview (this viewer, the clip preview, the
 *  floor-plan preview). An empty rest map and `hipsY: undefined` are the
 *  normal state while the rig is not served, and then a clip is bound as it
 *  comes — the behaviour of before.
 *
 *  Reading the rest off the CLIP file instead does not work: an FBX carrying
 *  an animation stores its nodes at the take's first frame, a mean 7.6° and
 *  up to 100° away from the rest. */
let _donorRigPromise: Promise<{ rest: RestPose; hipsY: number | undefined }> | null = null
const donorRig = () => {
  if (!_donorRigPromise) {
    _donorRigPromise = (async () => {
      try {
        const THREE = await import('three')
        installSkinnedNormalCorrection(THREE)
        const { FBXLoader } = await import('three/examples/jsm/loaders/FBXLoader.js')
        const rig = await new FBXLoader().loadAsync('/assets/animation-rig')
        return { rest: restPoseOf(THREE, rig), hipsY: rigHipsHeight(THREE, rig) }
      } catch {
        return { rest: { world: new Map<string, Quaternion>(),
                         parent: new Map<string, Quaternion>(),
                         parentBone: new Map<string, string | null>(),
                         position: new Map<string, Vector3>() },
                 hipsY: undefined }
      }
    })()
  }
  return _donorRigPromise
}
const donorRest = async () => (await donorRig()).rest
const _clipCache = new Map<string, Promise<{ clip: AnimationClip; restObj: Object3D
                                             hipsMedian: number | null
                                             heightOffsets?: ClipHeightOffsetsCm } | null>>()
/** One clip of `kind` — the `role` half of it when it is a pair clip. */
const loadClip = (kind: string, role = '') => {
  const key = role ? `${kind}#${role}` : kind
  let cached = _clipCache.get(key)
  if (!cached) {
    cached = (async () => {
      const { clips } = await clipIndex()
      // Prefer a set-less clip, then female, then anything of the kind —
      // same pick as the floor-plan preview.
      const of = clips.filter((c) => c.kind === kind && (c.role || '') === role)
      const pick = of.find((c) => !c.set) || of.find((c) => c.set === 'female') || of[0]
      if (!pick) return null
      try {
        const { FBXLoader } = await import('three/examples/jsm/loaders/FBXLoader.js')
        const clipObj = await new FBXLoader().loadAsync(pick.url)
        const clip = clipObj.animations?.[0]
        if (!clip) return null
        // The hips height the clip is played AT — measured BEFORE the track
        // goes, because dropping it drops that information with it. The
        // figure is lowered by it again in `addMarkerFigure`
        // (`clipHipsDrop`); the 3D client keeps the track and rescales it,
        // which comes to the same height.
        const hipsMedian = hipsTrackMedian(clip)
        // Play in place — the hips position track is in Mixamo centimetres
        // and carries the locomotion of the take across the room.
        clip.tracks = clip.tracks.filter(
          (tr) => !(/hips/i.test(tr.name) && tr.name.endsWith('.position')))
        return { clip, restObj: clipObj, hipsMedian, heightOffsets: pick.height_offsets_cm }
      } catch {
        return null
      }
    })()
    _clipCache.set(key, cached)
  }
  return cached
}
let _standRefPromise: Promise<number | null> | null = null

/** Refresh all admin consumers after a clip sidecar or file changes. */
export function invalidateAnimationPreviewClips(): void {
  _clipIndexPromise = null
  _clipCache.clear()
  _standRefPromise = null
  window.dispatchEvent(new Event('animation-clips-changed'))
}
/** The STANDING hips height of the clip library, in clip units — the
 *  reference every clip's own hips height is read against (`clipHipsDrop`).
 *  The SAME rule the 3D client applies (`standingHipsRef` of
 *  @anima/scene-render, used by `figures.adaptExternalClips`): the reference
 *  rig's REST hips height, the straight-legged stance every clip was
 *  retargeted onto. Only when no rig is served does the idle clip's hips
 *  median stand in (bent knees, 2.6 % lower — figures then float ~2.85 cm),
 *  with one warning per session. One resolution per session; `null` when
 *  there is neither, and then no figure is lowered at all rather than lowered
 *  against a guess. */
export const standHipsRef = (): Promise<number | null> => {
  if (!_standRefPromise) {
    _standRefPromise = (async () => {
      const { hipsY } = await donorRig()
      // The idle clip is only fetched when the rig does not answer.
      const rigOnly = standingHipsRef(hipsY, null)
      if (rigOnly.ref !== null) return rigOnly.ref
      const idle = await loadClip('idle')
      const { ref, source } = standingHipsRef(hipsY, idle?.hipsMedian)
      if (source === 'idle') {
        console.warn('[Model3DViewer] no reference rig at /assets/animation-rig —'
          + ' posed preview figures stand on the idle clip\'s hips median')
      } else {
        console.warn('[Model3DViewer] neither a reference rig nor an idle clip'
          + ' with a hips track — posed preview figures keep their bind hips height')
      }
      return ref
    })()
  }
  return _standRefPromise
}

/** Placement of a building model on its map tile — mirrors the worldmap
 *  contract (schnittstellen-3d.md; the model's SIZE comes from the scene
 *  spec's `max_m`, the declared real width of v6 Nr. 3, and a BUILDING has no
 *  placement yaw at all since v6 Nr. 10). */
export interface TilePlacement {
  /** Edge length of the stage in WORLD metres (the payload's `extent_m` =
   *  the footprint edge `plan_width_m`) — the SAME
   *  reference square the floor-plan preview draws, so the blue edge line
   *  means the same thing in both. */
  extentM?: number
  /** The placement spec out of the scene payload. Size (`max_m`), ground
   *  height (`bottom_y`) and shift (`anchor`) are taken from it verbatim —
   *  this viewer does not re-derive a single placement rule, which is why
   *  the walk-height dial is visible here at all: it moves `bottom_y`.
   *  Absent (room models, payload still pending) = the neutral fallback
   *  below. */
  spec?: SceneModelSpec | null
  /** Neutral fallback only (room models, payload still pending): yaw + the
   *  share of the stage the model fills. NOT a contract field — the scene
   *  spec's `max_m` decides wherever there is one. */
  yawDeg?: number
  size?: number
  /** Reference sizes (measureKit): which dial is being edited, plus the
   *  scalars the rulers need. Without them the stage shows nothing human and
   *  a metre field is guesswork. */
  measure?: MeasureKey
  k?: number
  planWidthM?: number
  storeyWorld?: number
  storeyRealM?: number
  figureHeightWorld?: number
}

/** One extra GLB of `Model3DViewer`'s `companions` (Ruling A48a). */
export interface ViewerCompanion {
  key: string
  url: string
  /** `ghost`: translucent grey-blue, never hides the model; `mark`: flat red, drawn over the model's own faces. */
  style: 'ghost' | 'mark'
  visible: boolean
  /** Ruling A48c: the companion follows the viewer's `deform` (it is part of the shown mesh, e.g. its red faces). */
  follow?: boolean
  /** Ruling A48c: show only the faces whose byte in `bits` (one per face, in the file's order) has bit `bit`. */
  faceBits?: { bits: Uint8Array; bit: number } | null
}

/** Ruling A48c: a live position map of the shown model — `map` rewrites flat xyz positions (in the loaded model's
 *  own frame) in place, always starting from the positions as loaded; a new `key` applies it again. */
export interface ViewerDeform { key: string; map: (xyz: Float32Array) => void }

export interface ActionAccessOverlay {
  role: 'actor' | 'partner'
  label: string
  x: number
  z: number
  yaw: number
}

export function Model3DViewer({ url, format, motion, motionToolbar, statusPanel, freshness, builtAt, sideToolbar = false, embeddedTakes = false, clipLoops, clipUrl = '', textureUrl = '', height = 320, rotation,
  offsetY = 0, offsetX = 0, offsetZ = 0,
  placement, onBounds, markers, lightPoint, surfacePoints, waterRegions, onPickModelPoint, dimsOverlay,
  figureHeight = 0, scaleFigure = false, groundOffsetM = 0,
  picking = false, onPickPoint, actionAccessPoints, spatialAuthoring = false, onPickGroundPoint,
  frontal = false, onFrontalChange, keepCamera = false,
  areaOutlines, polylines, slots, meshLayout, drawing = false, drawThrough = false,
  onPolygonFaces, onDrawCancel, leafBbox, collision, showCollision = false, footPose = null, clipGroup,
  meshAdjust = null, focus = null, alphaCutoff, strandHair, strandNote, subject = 'model', extensionBones = false,
  extensionNote = null, companions, onCompanionState, deform = null, resetViewOnDoubleClick = false }:
  { url: string; format: string; embeddedTakes?: boolean; clipLoops?: Record<string, { loop: boolean }>; motion?: SecondaryMotionPayload; motionToolbar?: ReactNode; statusPanel?: ReactNode; sideToolbar?: boolean; clipUrl?: string; textureUrl?: string; height?: number;
    /** Whether the "Extension bones" overlay starts switched on (Rulings A45/A56, `extensionGroupOverlay.ts`): the
     *  surface each of `motion`'s non-hair groups moves, as a wire grid in one colour per group, faded by skin
     *  weight and skinned with the mesh, plus a colour legend beside the toggle. The toggle is offered whenever
     *  `motion` names such a group; off by default — every viewer starts with it off (Ruling A62), and the toggle's
     *  state lives only as long as the viewer, never saved. */
    extensionBones?: boolean
    /** Ruling A64: what the shown model carries of the extension groups, in plain words (ExtensionPresenceNote) —
     *  written at the foot of the toggle column, also when the model has no group at all, so a missing group
     *  (covered by a worn piece, not built, not declared) is never a mystery. */
    extensionNote?: ReactNode
    /** Current / outdated / no data of the shown model (server verdict,
     *  app/core/model_overview.py) — a badge in the top left corner. */
    freshness?: Freshness | null
    /** When the shown model was built (a SYSTEM stamp from its payload, Ruling UI3 a) — a caption in the
     *  bottom right corner (`BuiltAtCaption`). */
    builtAt?: string | null
    /** The world's hair-card alpha cutoff (the hair GET's `alpha_cutoff`, strand-hair spec § 6.1): applied live
     *  to every material the model brought in as glTF MASK (`applyAlphaCutoff`), so a changed setting shows at
     *  once without a refit. Undefined = the glTF material's own cutoff. */
    alphaCutoff?: number
    /** Persisted 90°-step orientation fix ({x,y,z} in degrees) — applied live,
     *  without reloading the model. */
    rotation?: { x?: number; y?: number; z?: number }
    /** Fires ONCE per successful load with the RAW model box (before pivot,
     *  orientation fix and placement) — for callers that need the mesh's own
     *  proportions. */
    onBounds?: (b: { min: [number, number, number]
                     max: [number, number, number]
                     size: [number, number, number] }) => void
    /** Vertical placement offset in model units/metres (tile mode only) —
     *  negative sinks the model below the tile, like the 3D client does. */
    offsetY?: number
  /** Tile-plane shift in world metres (after the yaw): +x east, +z south. */
  offsetX?: number
  offsetZ?: number
    /** When `placement` is set, the viewer shows the world tile (a 1×1 ground
     *  square) and places the model on it — centred, yawed and scaled per
     *  `placement`, feet on the ground. */
    placement?: TilePlacement
    /** Object-local PLACES (numbered dots) — `at` = fractions of the RAW
     *  model bounding box, `group` the pose catalog's place type, and the
     *  place seats `capacity` figures `spacing_m` metres apart in a row
     *  `slot_axis` degrees off its `facing` (absent = 90 = across it). The preview puts ONE figure on every slot, playing
     *  `previewKind` (the clip of the pose the editor cycled to); a PAIR clip
     *  seats its two halves around the marker instead, turned by
     *  `previewYawOffset`. `rootDrop` is the place type's root drop as a
     *  FRACTION of the figure height: the composed payload's `root_offset`
     *  does not exist for a prop standing on its own, so it comes from the
     *  pose catalog and is converted into mesh units here.
     *  Model mode only; refreshed live. */
    markers?: Array<{ at: [number, number, number]
      group?: string; capacity?: number; spacing_m?: number; facing?: number
      slot_axis?: number; assigned?: boolean; selected?: boolean
      previewKind?: string; previewYawOffset?: number; rootDrop?: number }>
    /** Object-local light dot, refreshed live independently of the scale kit. */
    lightPoint?: { at: [number, number, number]; color: string }
    /** Small dots ON the model at absolute positions of its own frame (model
     *  units, the loaded glTF scene) — e.g. extension tip positions while
     *  their sliders move. Model mode only; refreshed live, drawn on top. */
    surfacePoints?: Array<{ at: [number, number, number]; color: string }>
    waterRegions?: ModelWater | null
    /** Pick in the fixed model frame, in model units. */
    onPickModelPoint?: (point: [number, number, number]) => void
    /** Height of a 1.7 m preview figure in MESH units (the caller derives
     *  it from bbox ÷ dims). > 0 shows a posed test figure at every marker
     *  — a sit marker is only judgeable with someone sitting there. */
    figureHeight?: number
    /** Put the STANDING 1.70 m reference beside the model, on the model's own
     *  ground plane, plus a one-metre ground grid under both (model mode
     *  only, needs `figureHeight` > 0). "No measurement without a scale": a mesh alone
     *  says nothing about its size — a stool and a gate look identical when
     *  both fill the frame. The figure never scales; the declared dims scale
     *  it, so a wrong Width/Depth/Height is visible instead of invisible. */
    scaleFigure?: boolean
    /** How deep the SHOWN mesh stands in the ground, in real metres — the
     *  prop variant's `ground_offset_m` (§ B2 addendum 2026-08-20). SIGN as
     *  the scene composes it: `bottom_y = floor + ground_offset_m`, so a
     *  NEGATIVE value sinks the mesh and a positive one lifts it off the
     *  ground.
     *
     *  The mesh itself never moves here — the GROUND does. Everything else in
     *  this mode is measured off the mesh (the dims box, the markers, the
     *  camera framing), so moving the model would drag all of that with it and
     *  claim the object had changed size or that a marker had moved. Instead
     *  the kit's plane sits where the scene's floor would be
     *  (`floor = mesh bottom − offset`): at −0.20 m the plane rides 20 cm
     *  above the mesh's lower edge, and exactly those 20 cm are under ground.
     *
     *  Needs the scale kit (`scaleFigure` + `figureHeight`): without a plane
     *  and a person on it there is nothing for a sink to be relative to.
     *  Model mode only; opt-in, so every other caller renders as before. */
    groundOffsetM?: number
    /** Draw the oriented bounding box with W/D/H edges + labels (real
     *  metres) around the model — makes the three dims readable in 3D.
     *  Model mode only; follows the orientation fix live. */
    dimsOverlay?: { width_m: number; depth_m: number; height_m: number } | null
    /** Armed pick mode: a plain click on the mesh reports the hit as RAW-box
     *  fractions — the floor-plan-style marker placement. */
    picking?: boolean
    onPickPoint?: (at: [number, number, number]) => void
    /** Already oriented local metres, relative to the footprint centre. */
    actionAccessPoints?: ActionAccessOverlay[]
    /** Keep body/access/heading overlays visible independently of scale kit. */
    spatialAuthoring?: boolean
    /** Ground-plane pick: local x/z metres, allowed outside the mesh bounds. */
    onPickGroundPoint?: (point: { x: number; z: number }) => void
    /** THE FRONT VIEW (spec-picture-props.md § 4, spec-bild-props-v2 § B1):
     *  the model straight on, centred, filling the frame — the authoring view
     *  of a flat panel, and the one the polygon tool is drawn on. It is a
     *  MODE, not a framing: while it is on the orbit is LOCKED (zoom and pan
     *  stay), so a flat surface is ringed with its whole face towards the
     *  camera instead of edge-on, where half of it is hidden behind the frame
     *  and a foreshortened sliver is all there is to click. The projection
     *  itself is never in danger — the ring is projected against the LIVE
     *  camera here and travels as triangle indices. Model mode only. */
    frontal?: boolean
    /** Offering this makes the front view a switchable mode: the viewer then
     *  shows its own "Front view" / "Reset view" controls and reports every
     *  press here, so the OWNER holds the state and can gate what only works
     *  head-on (the polygon tool). Without it nothing changes for a caller —
     *  no buttons, and the framing stays the straight-on one it always was. */
    onFrontalChange?: (on: boolean) => void
    /** Keep camera and target across a MODEL SWITCH instead of framing the
     *  new model (§ B1). For an editor that swaps versions of one object
     *  under the camera — a re-split frame, a picture variant, the far tier —
     *  where re-framing on every swap throws away the angle being worked at.
     *  A model of a different SIZE is framed anyway (`shouldRefit`), and the
     *  viewer offers "Reset view" whenever this is on, because a kept camera
     *  needs a way back. Off by default: every other caller frames every
     *  load, exactly as before. Model mode only. */
    keepCamera?: boolean
    /** Outlines of the prop's key surfaces, in glTF y-up MODEL space (the
     *  server computed them at the split — the client draws, never measures).
     *  One `LineSegments` per area, coloured by KIND out of `AREA_KINDS`, hung
     *  under the loaded model so it rides the orientation fix along. Model
     *  mode only; refreshed live. */
    areaOutlines?: AreaOutline[]
    /** Generic overlay polylines in the loaded model's own (glTF y-up) MODEL
     *  space — hung under the loaded object like `areaOutlines`, so they ride
     *  the orientation fix along; drawn on top (no depth test). The caller's
     *  server measured them (e.g. a shoe's insole and topline); this viewer
     *  only draws. Model mode only; refreshed live. */
    polylines?: Array<{ points: [number, number, number][]; color: string }>
    /** THE ASSEMBLY PREVIEW: what the picture areas show, keyed by area id —
     *  the SAME `applySlotMaterials` both renderers use, so the poster hangs
     *  in this preview the way it hangs in the scene. Cleared (or changed) the
     *  materials go back to the mesh's own. Model mode only. */
    slots?: PropSlotValues
    /** The R1 face order the server split against (`GET …/areas`). The polygon
     *  tool refuses to send indices unless the LOADED meshes match it. */
    meshLayout?: MeshLayoutEntry[]
    /** Armed polygon tool: an SVG over the canvas takes the gesture (click =
     *  point, double-click = close, Escape = cancel). Model mode only. */
    drawing?: boolean
    /** THE PICK IS A PRISM (spec-bild-props-v2.md E2): with it, the ring
     *  takes EVERY triangle whose centre projects inside it — back faces,
     *  edges, handles, whatever sits behind the front — with no facing and
     *  no occlusion test. The door leaf is a body, and a leaf cut as a skin
     *  is "shut and open at once". Off (a picture, a pane: surfaces) the
     *  three sight tests below apply. */
    drawThrough?: boolean
    /** The closed polygon's triangles as FLAT indices in R1 order — every
     *  front-facing, unoccluded triangle whose centre projects inside the
     *  ring (or, with `drawThrough`, every triangle under it). An empty
     *  array means "nothing was hit", which the panel says out loud instead
     *  of posting. */
    onPolygonFaces?: (faces: number[]) => void
    /** Escape was pressed while the tool was armed. The half-drawn ring is
     *  dropped here either way; this tells the OWNER to disarm as well, which
     *  is what "Escape cancels" promises — without it the tool stays armed
     *  with an empty ring and the next click starts another one. */
    onDrawCancel?: () => void
    /** THE DOOR LEAF (spec-picture-props.md § 6): the box of the model's
     *  `leaf` node in raw model metres, as the server measured it at the
     *  split. With it — and a `leaf` node in the loaded model — the viewer
     *  offers "Test swing": the leaf turns 85° about its hinge edge — the
     *  line `leafPivot` of @anima/scene-render states from this box and the
     *  orientation fix (`rotation`), the same routine the 3D client hangs
     *  its pivot with (ruling R13) — and back, so the cut can be judged
     *  before a door is placed anywhere. Model mode only. */
    leafBbox?: LeafBbox | null
    /** Extra GLBs drawn WITH the model, in the loaded model's own frame (they hang under the same pivot, so they
     *  frame, turn and move with it) — Ruling A48a: the base body as a translucent `ghost`, the faces inside it as a
     *  red `mark` drawn over the model's own. Loaded after the model, one by one, without reloading it; `visible`
     *  switches live. Not part of the framing or the mesh numbers. */
    companions?: ViewerCompanion[]
    /** A companion started loading, finished or failed (`error`: it is not shown). */
    onCompanionState?: (key: string, state: 'loading' | 'ready' | 'error') => void
    /** Ruling A48c: a live position map of the model and its `follow` companions (`ViewerDeform`); null = as loaded.
     *  Applied without reloading anything (the fit allowance's preview). */
    deform?: ViewerDeform | null
    /** Ruling A48c: a double-click also frames the view again (zoom and pan back), not only the pose. */
    resetViewOnDoubleClick?: boolean
    /** The model's collision capsules (`model.collision`, server
     *  app/core/collision.py). With capsules the viewer offers "Collision
     *  capsules": wireframes on the PLAYING figure, placed every frame by
     *  `createCollisionOverlay` of @anima/scene-render (the endpoint rule the
     *  garment push uses too). Refreshed live without reloading the model. */
    collision?: CollisionPayload | null
    /** Show the capsules whatever the toggle says — while the caller's
     *  radius sliders preview a draft (CollisionScales), so the effect is
     *  visible as the slider moves. */
    showCollision?: boolean
    /** THE FIT'S FOOT POSE (`foot_pose` of a footwear fit, footPose.ts of
     *  @anima/scene-render). Applied only when the loaded model carries the
     *  shoes it was fitted for (`footPoseMatches`): the extension is baked into
     *  the clip right after the bind-relative step (`applyFootPose`, with the
     *  figure's own rest pose), a figure without a clip gets the still pose
     *  (`applyFootPoseToPose`); the root lift is a placement term, see
     *  `clipGroup`. Null / another model = bare feet, as before. */
    footPose?: FootPose | null
    /** The height group the clip is played in (`clipHeightGroup`: ground /
     *  seat / lie). With it the figure is PLACED like the marker figures —
     *  this viewer plays every clip in place, so without it a seated clip
     *  would sit at standing hips height: lowered by `clipHipsDrop`, moved by
     *  the clip's `clipHeightOffsetM` and lifted by `footPoseLiftM` (the shod
     *  sole; standing only), over a floor grid at the bare bind soles. A shod
     *  figure in the ground group is then grounded on its SOLE per clip
     *  (`measureClipGround`, the rule the 3D client's terrain drop shares).
     *  Model mode only; absent = centred as before. */
    clipGroup?: 'ground' | 'seat' | 'lie'
    /** A LIVE vertex preview of the meshes whose name starts with `match` (model mode): every vertex of their
     *  loaded positions goes through `map` (model units of the mesh's own geometry, which is the fit frame for
     *  a grafted garment node) and their material colour is multiplied by `tint` (linear rgb) — re-applied
     *  whenever the prop changes, without reloading; null / no `map` and `tint` = the loaded mesh as it is.
     *  The Hairstyles tab drags its placement and colour sliders through it. */
    meshAdjust?: { match: string; map?: ((p: [number, number, number]) => [number, number, number]) | null
      tint?: [number, number, number] | null
      /** Ruling A71, the HAAR Cut preview: the first `positions.length / 3` vertices of the matched mesh take these
       *  positions and their uv.y these `v` (`hairCut.cutOverride`, the server's rule) — the strands pause while it
       *  is shown, like under a `map`. */
      cut?: { positions: Float32Array; v: Float32Array } | null } | null
    /** Frame a PART of the model instead of all of it (model mode): the camera looks at `center` (model units
     *  of the loaded scene) from far enough to hold a sphere of `radius`, from the front three-quarter or —
     *  `side` — from the model's +x side (its left), where a forward shift and a forward tilt read as lengths
     *  and angles. "Reset view" returns to it; a change of the prop re-frames. null = the whole model. */
    focus?: { center: [number, number, number]; radius: number; side?: boolean } | null
    /** Per-strand hair (strand-hair spec § 6.2.5, coordinator ruling H-R2): the strand record of the previewed
     *  fit and the live Stiffness factor — the preview runs the game's `createStrandHair` on the loaded model
     *  (bound to the hair mesh carrying `_STRAND_CARD` / `_STRAND_U`), with the same parameters. Given at all
     *  (also null), the preview is a FIGURE preview: a left drag turns the figure about the vertical axis
     *  (`DRAG_TURN_DEG_PER_PX`) so the hair reacts, right drag or Shift+drag orbits the camera, and the motion
     *  buttons Sway / Walk / Turn / Stop sit in the toolbar beside the viewer. null = no record (the hair stays
     *  still; `strandNote` says why). undefined = any other preview (the camera orbits as always). */
    strandHair?: { record: HairStrandRecord; stiffness: number } | null
    /** Why the hair stays still while `strandHair` is null (plain words, translated by the caller). */
    strandNote?: string
    /** What a drag turns, for the hint under the viewer (T-U4, `ModelTurnHint`): a figure or a model. */
    subject?: 'figure' | 'model' }) {
  const { t } = useI18n()
  const [takes, setTakes] = useState<string[]>([])
  const [take, setTake] = useState('')
  const [takePlaying, setTakePlaying] = useState(true)
  const [takeSpeed, setTakeSpeed] = useState(1)
  const takeRef = useRef({ take, playing: takePlaying, speed: takeSpeed, loops: clipLoops })
  takeRef.current = { take, playing: takePlaying, speed: takeSpeed, loops: clipLoops }
  const [secondaryOn, setSecondaryOn] = useState(true)
  const secondaryOnRef = useRef(secondaryOn)
  secondaryOnRef.current = secondaryOn
  const motionRef = useRef(motion)
  motionRef.current = motion
  // The extension-group overlay (Rulings A45/A56): read per frame like the motion, so the toggle never reloads the
  // model.
  const [bonesOn, setBonesOn] = useState(extensionBones)
  const bonesOnRef = useRef(bonesOn)
  bonesOnRef.current = bonesOn
  const hasExtensionBones = useMemo(() => extensionGroupIds(motion).length > 0, [motion])
  /** The overlay's readout: the largest swing of a group bone from its bind pose (degrees); null = overlay off. */
  const [bonesSwing, setBonesSwing] = useState<number | null>(null)
  /** The legend beside the toggle: the groups the overlay found a surface for, with their colour index. */
  const [bonesLegend, setBonesLegend] = useState<ExtensionGroupOverlay['groups']>([])
  // Per-strand hair and the figure preview (ruling H-R2): read per frame, so a dragged Stiffness or a new record
  // never reloads the model.
  const strandHairRef = useRef(strandHair)
  strandHairRef.current = strandHair
  const turnMode = strandHair !== undefined
  const turnModeRef = useRef(turnMode)
  turnModeRef.current = turnMode
  const [strandMotion, setStrandMotion] = useState<PreviewMotionKind | null>(null)
  const strandMotionRef = useRef(strandMotion)
  strandMotionRef.current = strandMotion
  /** The model's drag turn and tilt (whole degrees; T-U4, `lib/modelTurn.ts`): the Reset pose button, the status. */
  const [turnPose, setTurnPose] = useState({ turn: 0, tilt: 0 })
  /** Eases the model back to upright (set by the loader, which owns the control). */
  const turnResetRef = useRef<(() => void) | null>(null)
  /** What the strands do now: running (cards, the tips' largest distance from rest in mm), refused (the record
   *  does not fit the loaded hair mesh), paused (a placement preview reshapes the mesh), off (no record). */
  const [strandStatus, setStrandStatus] = useState<{ state: 'off' | 'running' | 'refused' | 'paused'; cards?: number;
    tipMm?: number }>({ state: 'off' })
  const footPoseRef = useRef(footPose)
  footPoseRef.current = footPose
  /** The loader re-runs when the pose of ANOTHER fit arrives, not on every
   *  new object identity of the same record. */
  const footPoseKey = footPose?.source ? `${footPose.source.item_id}:${footPose.source.fsig}` : ''
  const [collisionOn, setCollisionOn] = useState(false)
  const collisionRef = useRef<CollisionPayload | null>(null)
  const collisionShownOn = collisionOn || showCollision
  collisionRef.current = collisionShownOn && collision?.capsules?.length ? collision : null
  // Garments pushed out of the capsules (`createGarmentCollision`, the same
  // routine the 3D client runs) — on by default; the toggle compares.
  const [garmentPushOn, setGarmentPushOn] = useState(true)
  // Read per frame (like the push toggle): a dragged setting must not re-download the model.
  const alphaCutoffRef = useRef(alphaCutoff)
  alphaCutoffRef.current = alphaCutoff
  const [garmentPushable, setGarmentPushable] = useState(false)
  const garmentPushRef = useRef<CollisionPayload | null>(null)
  garmentPushRef.current = garmentPushOn && collision?.capsules?.length ? collision : null
  // Extension-bone tips kept outside the capsules (`setCollision` of the
  // secondary motion, the same routine the 3D client runs) — on by default.
  const [extensionPushOn, setExtensionPushOn] = useState(true)
  const extensionPushRef = useRef<CollisionPayload | null>(null)
  extensionPushRef.current = extensionPushOn && collision?.capsules?.length ? collision : null
  const mountRef = useRef<HTMLDivElement>(null)
  const [error, setError] = useState('')
  // Triangle/vertex count of the loaded mesh — every preview shows it, so
  // oversized assets are visible at a glance (asset-sizing note).
  const [meshStats, setMeshStats] = useState<{ tris: number; verts: number } | null>(null)
  const [loading, setLoading] = useState(true)
  const orientRef = useRef<Object3D | null>(null)
  const rotationRef = useRef(rotation)
  rotationRef.current = rotation
  const placeFnRef = useRef<((p: TilePlacement) => void) | null>(null)
  const companionsRef = useRef(companions)
  companionsRef.current = companions
  const onCompanionStateRef = useRef(onCompanionState)
  onCompanionStateRef.current = onCompanionState
  const companionFnRef = useRef<(() => void) | null>(null)
  const companionsKey = (companions || []).map((c) => `${c.key}|${c.url}|${c.style}|${c.visible ? 1 : 0}`).join(';')
  const deformRef = useRef(deform)
  deformRef.current = deform
  const deformFnRef = useRef<(() => void) | null>(null)
  const deformKey = `${deform?.key || ''}|${(companions || []).map((c) => `${c.key}:${c.follow ? 1 : 0}:${
    c.faceBits ? c.faceBits.bit : '-'}`).join(';')}`
  const resetViewOnDblRef = useRef(resetViewOnDoubleClick)
  resetViewOnDblRef.current = resetViewOnDoubleClick
  // The viewer's height is read live (Ruling A48c: the larger view grows the SAME viewer — a new height resizes the
  // canvas and keeps the model, the camera and the pose).
  const heightRef = useRef(height)
  heightRef.current = height
  /** Reference-size overlay of the current placement (own sprites/materials). */
  const aidsRef = useRef<Object3D | null>(null)
  const placementRef = useRef(placement)
  placementRef.current = placement
  const offsetYRef = useRef(offsetY)
  offsetYRef.current = offsetY
  const offsetXRef = useRef(offsetX)
  offsetXRef.current = offsetX
  const offsetZRef = useRef(offsetZ)
  offsetZRef.current = offsetZ
  // Ref, not a dependency: a fresh callback identity per render must not
  // re-download the model.
  const onBoundsRef = useRef(onBounds)
  onBoundsRef.current = onBounds
  // Marker/dims overlay + pick mode — all live-applied via refs so none of
  // them re-runs the loader effect.
  const waterRef = useRef(waterRegions)
  waterRef.current = waterRegions
  const waterPickRef = useRef(onPickModelPoint)
  waterPickRef.current = onPickModelPoint
  const lightPointRef = useRef(lightPoint)
  lightPointRef.current = lightPoint
  const markersRef = useRef(markers)
  markersRef.current = markers
  const surfacePointsRef = useRef(surfacePoints)
  surfacePointsRef.current = surfacePoints
  const dimsOverlayRef = useRef(dimsOverlay)
  dimsOverlayRef.current = dimsOverlay
  const figureHeightRef = useRef(figureHeight)
  figureHeightRef.current = figureHeight
  const scaleFigureRef = useRef(scaleFigure)
  scaleFigureRef.current = scaleFigure
  const groundOffsetRef = useRef(groundOffsetM)
  groundOffsetRef.current = groundOffsetM
  // Stale-guard for the async figure loads of an overlay rebuild.
  const figTokenRef = useRef(0)
  const pickingRef = useRef(picking)
  pickingRef.current = picking
  const onPickPointRef = useRef(onPickPoint)
  onPickPointRef.current = onPickPoint
  const actionAccessRef = useRef(actionAccessPoints)
  actionAccessRef.current = actionAccessPoints
  const spatialAuthoringRef = useRef(spatialAuthoring)
  spatialAuthoringRef.current = spatialAuthoring
  const groundPickRef = useRef(onPickGroundPoint)
  groundPickRef.current = onPickGroundPoint
  const overlayFnRef = useRef<(() => void) | null>(null)
  /** Re-frames the model-mode camera (model + scale kit). */
  const refitFnRef = useRef<(() => void) | null>(null)
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  // ── The front view as a MODE (§ B1) ──
  const frontalRef = useRef(frontal)
  frontalRef.current = frontal
  /** Does the CALLER offer the toggle? Only then is "not frontal" a stated
   *  mode with a framing of its own — every viewer that never heard of the
   *  toggle keeps the straight-on framing it has always opened with. */
  const frontalModeRef = useRef(!!onFrontalChange)
  frontalModeRef.current = !!onFrontalChange
  /** Locks / unlocks the orbit for the mode — set by the loader, because it
   *  needs the live controls. */
  const frontalFnRef = useRef<((on: boolean) => void) | null>(null)
  const keepCameraRef = useRef(keepCamera)
  keepCameraRef.current = keepCamera
  /** Where the camera stood, and how big the model under it was. Survives the
   *  loader effect, which is the whole point: with `keepCamera` a model switch
   *  inside one viewer (a re-split frame, a picture variant) must not yank the
   *  camera back to the default view — only a model of a different SIZE does
   *  (`shouldRefit`). Position and target say it all: OrbitControls dollies a
   *  PERSPECTIVE camera by moving it, so `camera.zoom` never leaves 1.
   *  Model mode only; the tile mode frames its stage every time. */
  const camStateRef = useRef<{ pos: [number, number, number]
    target: [number, number, number]; radius: number } | null>(null)
  // ── Picture areas: outlines, the assembly preview, the polygon tool ──
  const areaOutlinesRef = useRef(areaOutlines)
  areaOutlinesRef.current = areaOutlines
  const areaFnRef = useRef<(() => void) | null>(null)
  const polylinesRef = useRef(polylines)
  polylinesRef.current = polylines
  const polylineFnRef = useRef<(() => void) | null>(null)
  const meshAdjustRef = useRef(meshAdjust)
  meshAdjustRef.current = meshAdjust
  const meshAdjustFnRef = useRef<(() => void) | null>(null)
  const focusRef = useRef(focus)
  focusRef.current = focus
  const focusKey = focus ? `${focus.center.join(',')}|${focus.radius}|${focus.side ? 1 : 0}` : ''
  const slotsRef = useRef(slots)
  slotsRef.current = slots
  const slotFnRef = useRef<(() => void) | null>(null)
  const onPolygonFacesRef = useRef(onPolygonFaces)
  onPolygonFacesRef.current = onPolygonFaces
  const onDrawCancelRef = useRef(onDrawCancel)
  onDrawCancelRef.current = onDrawCancel
  const drawingRef = useRef(drawing)
  drawingRef.current = drawing
  /** Shows / hides the marker dots and the figures on them — set by the
   *  loader, because it owns the two groups. */
  const figuresFnRef = useRef<((show: boolean) => void) | null>(null)
  // ── The door leaf test swing (spec § 6) ──
  const leafBboxRef = useRef(leafBbox)
  leafBboxRef.current = leafBbox
  /** Turns the loaded model's `leaf` node open/shut — set by the loader,
   *  because it needs the node. */
  const swingFnRef = useRef<((open: boolean) => void) | null>(null)
  /** Does the LOADED model carry a `leaf` node at all? Without one there is
   *  nothing to swing and the button stays away. */
  const [hasLeaf, setHasLeaf] = useState(false)
  /** Is the leaf standing open right now (the button's own state)? */
  const [leafOpen, setLeafOpen] = useState(false)
  /** The pick itself — set by the loader, because it needs the live camera.
   *  Takes the ring in CANVAS PIXELS plus the canvas size and answers the flat
   *  R1 triangle indices. */
  const selectFacesRef = useRef<((poly: Array<[number, number]>,
    w: number, h: number, through: boolean) => number[]) | null>(null)
  /** Read at the moment the ring closes — a prop value would be the render
   *  the gesture started in. */
  const drawThroughRef = useRef(drawThrough)
  drawThroughRef.current = drawThrough
  /** What the LOADED model's R1 layout is — measured once per load, compared
   *  against the server's `meshLayout` before the tool is armed. */
  const [loadedLayout, setLoadedLayout] = useState<MeshLayoutEntry[] | null>(null)
  /** The ring being drawn, in canvas pixels ([] = nothing started). */
  const [poly, setPoly] = useState<Array<[number, number]>>([])
  /** The same ring, read by the click handler: a click decides against the
   *  ring AS IT STANDS, and reading it off state would race the render its
   *  predecessor queued. */
  const polyRef = useRef<Array<[number, number]>>([])
  polyRef.current = poly
  /** Where the cursor is while a ring is open — the rubber band. */
  const [polyCursor, setPolyCursor] = useState<[number, number] | null>(null)

  /** Model and area list still describe the same mesh? Only then may indices
   *  be sent (R1) — a mismatched index marks a random strip of the mesh. */
  const layoutOk = useMemo(() => alignMeshLayout(loadedLayout, meshLayout),
    [loadedLayout, meshLayout])

  // Live outline / preview refresh — a detected area or a picked picture must
  // show up without re-downloading the model.
  useEffect(() => { areaFnRef.current?.() }, [areaOutlines])
  useEffect(() => { polylineFnRef.current?.() }, [polylines])
  useEffect(() => { meshAdjustFnRef.current?.() }, [meshAdjust])
  useEffect(() => { companionFnRef.current?.() }, [companionsKey])
  useEffect(() => { deformFnRef.current?.() }, [deformKey])
  useEffect(() => { if (focusKey) refitFnRef.current?.() }, [focusKey])
  useEffect(() => { slotFnRef.current?.() }, [slots])
  // Disarming the tool drops whatever was half-drawn: a ring that survived
  // into the next arming would send points from the previous camera.
  useEffect(() => {
    if (!drawing) { setPoly([]); setPolyCursor(null) }
  }, [drawing])
  // A ring is drawn over the MODEL, and a marker dot with a 1.70 m figure on
  // it stands in front of exactly the surface being ringed. The pick itself
  // never sees them (the raycast is model-only), but the admin has to.
  useEffect(() => { figuresFnRef.current?.(!drawing) }, [drawing])
  // Escape cancels the running ring (the map's gesture — see PolygonHandles).
  useEffect(() => {
    if (!drawing) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      setPoly([])
      setPolyCursor(null)
      // "Escape cancels" — the whole gesture, not only its points: the owner
      // disarms the tool, so the next click orbits again instead of starting
      // another ring nobody asked for.
      onDrawCancelRef.current?.()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [drawing])
  // The front view is a MODE: switching it on locks the orbit (zoom and pan
  // stay) and re-frames the model straight on ONCE. Switching it off only
  // hands the rotation back — the camera keeps standing where it is.
  useEffect(() => {
    frontalFnRef.current?.(frontal)
    if (frontal) refitFnRef.current?.()
  }, [frontal])

  /** Where a pointer event landed inside the overlay, in canvas pixels. */
  const atOverlay = (e: { clientX: number; clientY: number
    currentTarget: { getBoundingClientRect: () => DOMRect } }): [number, number] => {
    const r = e.currentTarget.getBoundingClientRect()
    return [e.clientX - r.left, e.clientY - r.top]
  }

  /**
   * Closes the ring and hands the triangles over.
   *
   * Below three points — or with no enclosed area at all — nothing is
   * reported: an empty selection is a refusal, and a scribble is not a
   * polygon.
   */
  const finishPoly = (ring: Array<[number, number]>, w: number, h: number) => {
    setPoly([])
    setPolyCursor(null)
    if (ring.length < 3 || polygonArea(ring) <= 0) return
    const faces = selectFacesRef.current?.(ring, w, h, drawThroughRef.current) || []
    onPolygonFacesRef.current?.(faces)
  }

  /**
   * One click: close the ring, or drop another point.
   *
   * THE MAP'S GESTURE (`MapTab.addDraftPoint`): a ring closes by clicking its
   * FIRST point again, within `CLOSE_TOL_PX` pixels — there is no double-click
   * here, because on an SVG both presses of one arrive as ordinary clicks and
   * each would drop a point of its own.
   */
  const addPolyPoint = (e: ReactMouseEvent<SVGSVGElement>) => {
    const r = e.currentTarget.getBoundingClientRect()
    const at = atOverlay(e)
    const cur = polyRef.current
    if (closesOnFirstPoint(cur, at, CLOSE_TOL_PX)) {
      finishPoly([...cur], r.width, r.height)
      return
    }
    if (cur.length >= MAX_POLYGON_POINTS) return
    setPoly([...cur, at])
  }

  /** Is the cursor standing ON the first point, i.e. would this click close
   *  the ring? Drawn as a snap highlight plus the closing segment, so the
   *  gesture is visible BEFORE it is committed. */
  const closesHere = !!polyCursor
    && closesOnFirstPoint(poly, polyCursor, CLOSE_TOL_PX)

  // Live overlay refresh (markers moved/added, dims typed, a sink dialled)
  // without reload — a typed number must show up while it is being typed.
  useEffect(() => { overlayFnRef.current?.() },
    [markers, lightPoint, surfacePoints, waterRegions, dimsOverlay, figureHeight, scaleFigure, groundOffsetM, actionAccessPoints, spatialAuthoring])
  useEffect(() => {
    const refresh = () => overlayFnRef.current?.()
    window.addEventListener('animation-clips-changed', refresh)
    return () => window.removeEventListener('animation-clips-changed', refresh)
  }, [])
  // Switching the scale kit on widens what has to be in view.
  useEffect(() => { refitFnRef.current?.() }, [scaleFigure])
  // The armed pick tool reads as a crosshair on the canvas.
  useEffect(() => {
    if (canvasRef.current) canvasRef.current.style.cursor = picking ? 'crosshair' : ''
  }, [picking])

  // Live-apply an offset change (the placement fn reads the ref).
  useEffect(() => {
    if (placementRef.current) placeFnRef.current?.(placementRef.current)
  }, [offsetY, offsetX, offsetZ])

  // Live-apply a changed rotation to the mounted scene — a reload would
  // re-download a multi-MB model per 90° click. In tile mode the orientation
  // fix changes the model's bounding box, so the placement (scale + ground
  // offset) is re-derived right after.
  useEffect(() => {
    if (orientRef.current) orientRef.current.rotation.order = 'YXZ'
    orientRef.current?.rotation.set(
      _deg(rotation?.x), _deg(rotation?.y), _deg(rotation?.z))
    if (placementRef.current) placeFnRef.current?.(placementRef.current)
    // The oriented dims box follows the fix.
    overlayFnRef.current?.()
  }, [rotation?.x, rotation?.y, rotation?.z])

  // Live-apply placement changes (yaw slider / size slider) without reload.
  useEffect(() => {
    if (placement) placeFnRef.current?.(placement)
  }, [placement, placement?.yawDeg, placement?.size, placement?.extentM,
    placement?.spec, placement?.measure, placement?.figureHeightWorld])

  useEffect(() => {
    let disposed = false
    let cleanup: (() => void) | undefined
    setLoading(true)
    setError('')
    setMeshStats(null)
    setHasLeaf(false)
    setLeafOpen(false)
    // A new model is a new face order — the polygon tool stays disabled until
    // the fresh one has been measured and matched against the server's.
    setLoadedLayout(null)

    ;(async () => {
      try {
        const THREE = await import('three')
        installSkinnedNormalCorrection(THREE)
        const { OrbitControls } = await import('three/examples/jsm/controls/OrbitControls.js')

        const mount = mountRef.current
        if (!mount || disposed) return

        const width = mount.clientWidth || 320
        const scene = new THREE.Scene()
        scene.background = null

        const camera = new THREE.PerspectiveCamera(45, width / heightRef.current, 0.1, 5000)
        const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true })
        renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
        renderer.setSize(width, heightRef.current)
        mount.appendChild(renderer.domElement)

        // Teardown is wired up the moment the WebGL context exists — BEFORE the
        // first await — so every early return (the `disposed` checks after each
        // loadAsync) and the catch below dispose the renderer instead of
        // leaking its context (the browser caps live contexts at ~16). Disposers
        // run LIFO; `splice` makes cleanup idempotent — the catch may run it,
        // then the effect cleanup runs it again on unmount.
        const disposers: Array<() => void> = []
        cleanup = () => {
          for (const d of disposers.splice(0).reverse()) {
            try { d() } catch { /* teardown is best-effort */ }
          }
        }
        disposers.push(() => {
          renderer.dispose()
          if (renderer.domElement.parentNode === mount) {
            mount.removeChild(renderer.domElement)
          }
        })

        // Bright, flat, even lighting — the mesh is inspected, not staged.
        // three.js uses physical light units, so a single dim key light leaves
        // the model near-black: ambient + hemisphere + a 3-point rig.
        scene.add(new THREE.AmbientLight(0xffffff, 2.0))
        scene.add(new THREE.HemisphereLight(0xffffff, 0x666666, 3.0))
        const key = new THREE.DirectionalLight(0xffffff, 3.0)
        key.position.set(1, 2, 3)
        scene.add(key)
        const fill = new THREE.DirectionalLight(0xffffff, 1.5)
        fill.position.set(-2, 1, 2)
        scene.add(fill)
        const back = new THREE.DirectionalLight(0xffffff, 1.5)
        back.position.set(0, 1, -3)
        scene.add(back)
        renderer.toneMappingExposure = 1.2

        const controls = new OrbitControls(camera, renderer.domElement)
        controls.enableDamping = true
        disposers.push(() => controls.dispose())
        // T-U4 (`lib/modelTurn.ts`): the pointer turns the MODEL, Shift + drag moves the view, the wheel zooms. The
        // control is attached once the model has loaded (its pivot is the model's centre).
        let modelTurn: ModelTurnControl | null = null

        // THE FRONT VIEW'S LOCK (§ B1). The model stands straight on and does
        // not turn; zoom and pan stay on — the admin still has to get close to
        // a panel and shift it into the middle, only the ANGLE is fixed. The
        // plain drag (and the one-finger drag) pans then.
        const applyFrontal = (on: boolean) => {
          if (!on) { configureViewControls(THREE, controls); return }
          controls.enableRotate = false
          controls.enableZoom = true
          controls.enablePan = true
          controls.mouseButtons = { LEFT: THREE.MOUSE.PAN, MIDDLE: THREE.MOUSE.DOLLY, RIGHT: THREE.MOUSE.PAN }
          controls.touches = { ONE: THREE.TOUCH.PAN, TWO: THREE.TOUCH.DOLLY_PAN }
          controls.update()
          modelTurn?.snapUpright()
        }
        applyFrontal(frontalRef.current)
        frontalFnRef.current = applyFrontal
        disposers.push(() => {
          if (frontalFnRef.current === applyFrontal) frontalFnRef.current = null
        })

        const ext = (format || url.split('.').pop() || '').toLowerCase()
        let embedded: import('three').AnimationClip[] = []
        let object: Object3D
        let gltfParser: GltfParser | null = null
        if (ext === 'fbx') {
          const { FBXLoader } = await import('three/examples/jsm/loaders/FBXLoader.js')
          object = await new FBXLoader().loadAsync(url)
          embedded = object.animations
        } else if (ext === 'glb' || ext === 'gltf' || ext === 'vrm') {
          const { createGLTFLoader } = await import('../../lib/gltfLoader')
          const gltf = await createGLTFLoader().loadAsync(url)
          object = gltf.scene
          embedded = gltf.animations
          // The parser is kept for ONE reason: it is the only place that still
          // knows which glTF NODE a loaded mesh came from (`associations`) and
          // what that node was really called (`json.nodes[i].name`, unsanitised).
          // The R1 face order counts per node, so the polygon tool needs both.
          gltfParser = gltf.parser as GltfParser
        } else if (ext === 'obj') {
          const { OBJLoader } = await import('three/examples/jsm/loaders/OBJLoader.js')
          object = await new OBJLoader().loadAsync(url)
        } else {
          throw new Error(`Unsupported format: ${ext}`)
        }
        if (disposed) return

        // The RAW model box — measured before pivot / orientation fix /
        // placement, so it describes the mesh's own axes and proportions.
        // (setFromObject updates the matrices itself.) This is also the frame
        // object-local markers live in: measured while the object is still
        // unparented, its coordinates equal the later PIVOT-local space.
        const rawBox = new THREE.Box3().setFromObject(object)
        const rawSize = rawBox.getSize(new THREE.Vector3())
        // Every mesh of the model in LOAD order, then folded into the R1
        // order the SERVER counts in — per glTF NODE, which is per Blender
        // object (`meshLayoutOf`). The counts below, the layout comparison and
        // the polygon tool's flat index all read this one list, so the order is
        // stated exactly once.
        const loaded: Mesh[] = []
        object.traverse((o: Object3D) => {
          const mesh = o as Mesh
          // An InstancedMesh draws one geometry many times; there is no single
          // triangle behind a face index, so it can never be part of an R1
          // order. Excluded here AND in the pick below.
          if (mesh.isMesh && !(mesh as { isInstancedMesh?: boolean }).isInstancedMesh) {
            loaded.push(mesh)
          }
        })
        // WHICH NODE a primitive belongs to, and what that node is called.
        // `associations` maps every object the loader made to its glTF indices:
        // a single-primitive node IS the mesh (it carries `nodes`), while the
        // primitives of a multi-primitive node carry only `primitives` and hang
        // under a Group that carries `nodes`. So the mesh is asked first and
        // its parents after, and the NAME comes out of the raw glTF JSON —
        // three's own `name` went through `sanitizeNodeName` (`Frame.001` →
        // `Frame001`) and through `createUniqueName` (`Frame` → `Frame_1`), and
        // neither is what the server split against.
        const nodeOf = (mesh: Mesh, at: number) => {
          const assoc = gltfParser?.associations
          const own = assoc?.get(mesh)
          const primitive = own?.primitives ?? 0
          let node: Object3D | null = mesh
          while (node) {
            const idx = assoc?.get(node)?.nodes
            if (idx !== undefined) {
              // A node without a name carries none in three either (`node.name`
              // is only assigned inside `if (nodeDef.name)`), and Blender's
              // importer falls back to the MESH name for exactly that case —
              // so this falls back the same way before giving up.
              const named = gltfParser?.json?.nodes?.[idx]?.name
              return { nodeKey: `n${idx}`, name: named || node.name || mesh.name,
                       primitive }
            }
            node = node.parent
          }
          // No parser (an FBX/OBJ preview) or a mesh the loader never
          // registered: the object stands for itself, under its own name.
          return { nodeKey: `o${at}`, name: mesh.userData?.name || mesh.name, primitive }
        }
        const groups = meshLayoutOf(loaded.map(nodeOf))
        // The meshes in R1 sequence — groups by name, primitives within a
        // group in their own order.
        const ordered: Mesh[] = groups.flatMap((g) => g.members.map((i) => loaded[i]))
        const triCountOf = (mesh: Mesh): number => {
          const geo = mesh.geometry as { index?: { count: number } | null
            attributes?: { position?: { count: number } } }
          const pos = geo.attributes?.position?.count || 0
          return Math.floor((geo.index ? geo.index.count : pos) / 3)
        }
        {
          // Face/vertex count over all meshes (indexed: index/3, else pos/3).
          let tris = 0
          let verts = 0
          for (const mesh of ordered) {
            const geo = mesh.geometry as {
              attributes?: { position?: { count: number } } }
            verts += geo.attributes?.position?.count || 0
            tris += triCountOf(mesh)
          }
          setMeshStats({ tris, verts })
          setLoadedLayout(groups.map((g) => ({
            name: g.name,
            tri_count: g.members.reduce((n, i) => n + triCountOf(loaded[i]), 0),
          })))
        }
        if (onBoundsRef.current) {
          onBoundsRef.current({
            min: [rawBox.min.x, rawBox.min.y, rawBox.min.z],
            max: [rawBox.max.x, rawBox.max.y, rawBox.max.z],
            size: [rawSize.x, rawSize.y, rawSize.z],
          })
        }

        // An FBX embeds no texture — the basecolor PNG of the same generation
        // run comes separately and has to be bound to the materials by hand
        // (a GLB carries its textures inside and needs none of this).
        //
        // flipY=false: the gateway delivers the PNG display-ready, already
        // V-flipped to match the FBX UVs sampled natively (gateway
        // normalize_delivery, 2026-07-15) — every consumer (this preview, the
        // 3D client, DCC imports) binds it as stored, no compensation.
        // Textures generated BEFORE that gateway fix render mirrored here:
        // regenerate the model.
        // AV3D-14 aftermath (finding 2026-07-26, Rosi): generated GLBs now
        // embed a metal-roughness texture, and character bakes carry ~0.5
        // metalness across skin — with the glTF default metallicFactor 1.0
        // and no env map the figure renders as the MR map's tint instead of
        // its base colour. This viewer is a diagnostic: kill metalness (the
        // roughness channel of the same map stays active), colours stay true —
        // except on a garment whose material preset sets it (Ruling A36).
        zeroViewerMetalness(object)

        if (textureUrl) {
          const tex = await new THREE.TextureLoader().loadAsync(textureUrl)
          if (disposed) return
          tex.colorSpace = THREE.SRGBColorSpace
          tex.flipY = false
          tex.wrapS = THREE.RepeatWrapping
          tex.wrapT = THREE.RepeatWrapping
          tex.needsUpdate = true
          applyViewerTexture(object, tex)
        }

        // A pivot carries the orientation fix: the clip animates the model's
        // OWN root bone, so rotating the model itself would fight the
        // animation. The pivot sits above it, untouched by the mixer.
        const pivot = new THREE.Group()
        pivot.add(object)
        // The persisted admin rotation sits on its OWN group above the pivot —
        // the pivot carries the automatic up-axis fix, this one the admin's
        // 90° choice; they must not overwrite each other.
        const orient = new THREE.Group()
        orient.add(pivot)
        // Placement group (tile mode): carries yaw + tile scale + ground
        // offset ABOVE the orientation fix, so re-orienting the model never
        // fights the placement. Identity transform in normal mode.
        const place = new THREE.Group()
        place.add(orient)
        const previewRoot = new THREE.Group()
        // The figure preview's root motion (ruling H-R2: the drag turn, Sway / Walk / Turn) sits between the
        // preview root and the placement — identity everywhere else. Since Ruling A41 the drag is the ONLY way a
        // viewer tilts the figure (the Tilt sliders are gone): extension bones feel gravity through this matrix.
        const turnRoot = new THREE.Group()
        turnRoot.matrixAutoUpdate = false
        turnRoot.add(place)
        previewRoot.add(turnRoot)
        // The overlays that annotate the model in world terms (dims, access points, marker figures) turn with it
        // (T-U4): the same matrix as `turnRoot`. They are BUILT upright (`upright`), in the frame they always had.
        const followTurn = new THREE.Group()
        followTurn.matrixAutoUpdate = false
        previewRoot.add(followTurn)
        scene.add(previewRoot)
        /** Run `fn` with the model upright (no drag turn), the matrices updated, then put the turn back. */
        const upright = <T,>(fn: () => T): T => {
          const turn = turnRoot.matrix.clone()
          turnRoot.matrix.identity()
          previewRoot.updateMatrixWorld(true)
          try { return fn() } finally {
            turnRoot.matrix.copy(turn)
            previewRoot.updateMatrixWorld(true)
          }
        }
        const _r = rotationRef.current
        // 'YXZ' like place() in @anima/scene-render: yaw outermost, tilt and
        // roll in the already-turned frame. The preview must not disagree with
        // the scene about what a dial means.
        orient.rotation.order = 'YXZ'
        orient.rotation.set(_deg(_r?.x), _deg(_r?.y), _deg(_r?.z))
        orientRef.current = orient
        disposers.push(() => {
          if (orientRef.current === orient) orientRef.current = null
        })
        disposers.push(() => {
          scene.traverse((o: Object3D) => {
            const mesh = o as Mesh
            mesh.geometry?.dispose?.()
            const m = mesh.material as Material | Material[] | undefined
            if (Array.isArray(m)) m.forEach((x) => x.dispose?.())
            else m?.dispose?.()
          })
        })

        // Animation clip (shared Mixamo FBX, "Without Skin" = keyframes only).
        // It drives the model's own skeleton by bone name, so model and clip
        // MUST come from the same rig — see shared/models/clips/README.md.
        let secondary: SecondaryMotion | null = null
        let secondaryRev = motionRef.current?.rev
        let secondaryEnabled = secondaryOnRef.current
        let mixer: InstanceType<typeof THREE.AnimationMixer> | null = null
        let embeddedAction: import('three').AnimationAction | null = null
        let activeTake = ''
        let embeddedFinished = false
        if (embeddedTakes) {
          setTakes(embedded.map(clip => clip.name))
          setTake(previous => embedded.some(clip => clip.name === previous)
            ? previous : embedded[0]?.name || '')
          mixer = new THREE.AnimationMixer(object)
          const embeddedMixer = mixer
          const onFinished = (event: { action: import('three').AnimationAction }) => {
            if (event.action !== embeddedAction) return
            embeddedFinished = true
            takeRef.current.playing = false
            setTakePlaying(false)
          }
          embeddedMixer.addEventListener('finished', onFinished)
          disposers.push(() => {
            embeddedMixer.removeEventListener('finished', onFinished)
            embeddedMixer.stopAllAction()
          })
        } else setTakes([])
        // THE SHOD FIGURE: the fit's foot pose holds only for a model that
        // carries exactly the shoes it was fitted for — anything else (the
        // bare base, another fit, a rebuild in between) keeps bare feet.
        const shod = footPoseRef.current && footPoseMatches(object, footPoseRef.current)
          ? footPoseRef.current : null
        /** The figure's vertical placement in its height group (`clipGroup`),
         *  and the floor its bare bind soles stand on — measured in the bind
         *  pose, applied after the framing below. */
        let stance: { y: number; floorY: number } | null = null
        /** The bare bind sole plane in SCENE units once framed (the floor grid's
         *  height): the floor the seated knee-raise measures against — the
         *  shipped rest, never a measurement on the cut body (P3b). */
        let floorWorldY: number | null = null
        const measureStance = async (hipsMedian: number | null,
          heightOffsets?: ClipHeightOffsetsCm): Promise<{ y: number; floorY: number } | null> => {
          if (!clipGroup) return null
          const hipsOf = (root: Object3D): Object3D | null => {
            let found: Object3D | null = null
            root.traverse((o) => { if (!found && /hips/i.test(o.name)) found = o })
            return found
          }
          const standRef = hipsMedian !== null ? await standHipsRef() : null
          pivot.updateMatrixWorld(true)
          // The FIGURE's box — the shoes are garments and do not count, so the
          // floor is where the bare soles stand in the bind pose; a shod
          // figure's box is the BARE body's the record ships (the served
          // body is cut under the shoe, `footPoseRest`).
          const box = figureBox(THREE, object, shod)
          const hips = hipsOf(object)
          const hipsBindY = hips ? hips.getWorldPosition(new THREE.Vector3()).y - box.min.y : null
          const figH = box.max.y - box.min.y
          // The fit's `root_lift_m` is in this model's own metres: no figure
          // scaling (`footPoseLiftM`'s default height).
          return {
            y: -clipHipsDrop(hipsBindY, hipsMedian, standRef)
              + clipHeightOffsetM(heightOffsets, clipGroup, figH)
              + footPoseLiftM(shod, clipGroup),
            floorY: box.min.y,
          }
        }
        if (clipUrl) {
          const { FBXLoader } = await import('three/examples/jsm/loaders/FBXLoader.js')
          const clipObj = await new FBXLoader().loadAsync(clipUrl)
          if (disposed) return
          const clip = clipObj.animations?.[0]
          if (!clip) throw new Error('Clip contains no animation track')
          // The hips height the clip is played AT — read before its track goes
          // (`loadClip` does the same for the marker figures).
          const clipHipsMedian = clipGroup ? hipsTrackMedian(clip) : null

          // Up-axis fix. The mixer overwrites the model's root-bone rotation
          // with the clip's values, so a convention mismatch (Mixamo clips are
          // Y-up, the generated meshes need not be) lays the figure down.
          //
          // The correction is measured from the two REST skeletons — the
          // model's and the clip file's — NEVER from the animated pose: a
          // sitting or lying clip is legitimately not upright, and judging by
          // the rendered pose would "correct" exactly those into nonsense.
          // We want pivot ∘ modelRest ≈ clipRest at the root bone's parent,
          // so we pick the axis rotation that aligns the two rest frames.
          const hipsOf = (root: Object3D): Object3D | null => {
            let found: Object3D | null = null
            root.traverse((o) => {
              if (!found && /hips/i.test(o.name)) found = o
            })
            return found
          }
          const modelHips = hipsOf(object)
          const clipHips = hipsOf(clipObj)
          if (modelHips?.parent && clipHips?.parent) {
            object.updateMatrixWorld(true)
            clipObj.updateMatrixWorld(true)
            const restModel = modelHips.parent.getWorldQuaternion(new THREE.Quaternion())
            const restClip = clipHips.parent.getWorldQuaternion(new THREE.Quaternion())
            let bestRx = 0
            let bestAngle = Infinity
            for (const rx of [0, Math.PI / 2, -Math.PI / 2, Math.PI]) {
              const candidate = new THREE.Quaternion()
                .setFromEuler(new THREE.Euler(rx, 0, 0))
                .multiply(restModel)
              const angle = candidate.angleTo(restClip)
              if (angle < bestAngle) {
                bestAngle = angle
                bestRx = rx
              }
            }
            pivot.rotation.x = bestRx
          }

          // Play IN PLACE: drop the root/hips position track. Otherwise a walk
          // clip with root motion carries the figure out of frame — and the
          // track is in the clip's units (Mixamo: centimetres), which would
          // fling a differently scaled model across the scene.
          clip.tracks = clip.tracks.filter(
            (tr) => !(/hips/i.test(tr.name) && tr.name.endsWith('.position')),
          )
          // BIND-RELATIVE, the same routine the 3D client uses: the clip is
          // written in the reference rig's rest frame, so each value is read
          // as a rotation away from THAT rest and re-expressed against this
          // model's own bind pose. Without it the copy overwrites the
          // character's stance — a model whose T-pose stands with the feet
          // splayed 18° showed 18° of extra toe-in on every clip.
          const donor = await donorRest()
          const corrections = restCorrections(THREE, donor, object, undefined, shod)
          if (disposed) return
          // The shoe's extension, baked ONCE right after the bind-relative
          // step into this load's own (unposed) clip; a bone the clip has no
          // track for takes the figure's rest rotation, and the extension
          // carries the delta the transplant put on the foot — the clip is
          // relative to the rest the corrections play, not to the bind
          // (footPose.ts, `transplantedRestPose`).
          const rest = shod ? restPoseOf(THREE, object) : null
          const bare = bindRelativeClip(THREE, clip, corrections)
          let bound = applyFootPose(THREE, bare, shod, rest,
            rest ? transplantedRestPose(THREE, donor, rest, corrections) : null)
          if (clipGroup) {
            const entry = (await clipIndex()).clips.find((c) => c.url === clipUrl)
            stance = await measureStance(clipHipsMedian, entry?.height_offsets_cm)
            if (disposed) return
            if (stance && shod && clipGroup === 'ground') {
              // THE SHOD FOOT PLANT, then THE SHOD GROUND (scene-render
              // `footPlant.ts` / `clipGround.ts`, the shared rules the 3D
              // client's clip paths use too): per stance frame the sole is
              // levelled, its forepart held and its lowest contact put on the
              // floor by the leg; then the clip's residual offset is measured
              // on the sole contacts, with the placement so far as the root
              // term — both on a clone the mixer may pose, under the same
              // up-axis fix as the figure. The model is in metres.
              const { clone: skclone } = await import('three/examples/jsm/utils/SkeletonUtils.js')
              if (disposed) return
              const holder = new THREE.Group()
              holder.rotation.copy(pivot.rotation)
              const probe = skclone(object) as Object3D
              holder.add(probe)
              bound = plantFootPose(THREE, bound, bare, probe, shod, { rootY: stance.y, unitsPerCm: 0.01 })
              measureClipGround(THREE, [bound], probe, { footPose: shod, rootY: stance.y })
              stance.y -= clipGroundOffset(bound)
            }
          }
          // Bind capture after the automatic up-axis fix, before frame zero.
          secondary = createSecondaryMotion(THREE, object, secondaryEnabled ? motionRef.current : undefined, object)
          mixer = new THREE.AnimationMixer(object)
          mixer.clipAction(bound).play()
          mixer.update(0)  // apply frame 0 so the framing below fits the pose
          disposers.push(() => mixer?.stopAllAction())
        } else if (!embeddedTakes && (shod || clipGroup)) {
          // No clip plays: the shod figure shows the still pose once.
          applyFootPoseToPose(THREE, object, shod)
          object.updateMatrixWorld(true)
          stance = await measureStance(null)
          if (disposed) return
        }
        secondary ??= createSecondaryMotion(THREE, object, secondaryEnabled ? motionRef.current : undefined, object)
        disposers.push(() => secondary?.dispose())
        // The capsule overlay lives in the SCENE root (world space) and is
        // rebuilt whenever the shown payload changes (toggle, slider preview,
        // a recomputed set) — never the model.
        let collisionOverlay: CollisionOverlay | null = null
        let collisionShown: CollisionPayload | null | undefined
        disposers.push(() => collisionOverlay?.dispose())
        // The garment push patches CLONES of the garment materials and puts
        // the originals back on dispose — before the scene traversal above
        // frees the model's own materials (disposers run in reverse).
        let garmentCollision: GarmentCollision | null = null
        let garmentShown: CollisionPayload | null | undefined
        disposers.push(() => garmentCollision?.dispose())
        // The extension-group overlay (Rulings A45/A56) in the scene root, rebuilt when the toggle or the payload's
        // revision changes; it frees only what it created.
        let boneOverlay: ExtensionGroupOverlay | null = null
        let bonesShown: string | null = null
        let bonesClock = 0
        let bonesRead: number | null = null
        disposers.push(() => boneOverlay?.dispose())
        // The cutoff last applied to the materials on screen (`applyAlphaCutoff`); a new garment push swaps in
        // fresh material clones, so it is applied again then.
        let alphaShown: number | undefined
        let extensionShown: CollisionPayload | null | undefined
        setGarmentPushable(collidingGarmentMeshes(object).length > 0)
        const clock = new THREE.Clock()
        pivot.updateMatrixWorld(true)
        // Per-strand hair (strand-hair spec § 6.2.5): the handle of the record now given, created on the frame the
        // record (identity) changes; on only while no placement preview reshapes the hair mesh (`meshAdjust` map —
        // the strands rebuild the vertices the map would move). Out of the garment push while on, as in the client.
        let strand: StrandHair | null = null
        let strandRecord: HairStrandRecord | null = null
        let strandStiffness = 1
        const strandOn = (on: boolean) => {
          if (!strand || strand.enabled === on) return
          strand.setEnabled(on)
          garmentCollision?.excludeMesh(strand.mesh, on)
        }
        disposers.push(() => { strand?.dispose(); strand = null })

        if (placementRef.current) {
          // ── Stage mode: the location's reference square in WORLD metres,
          // with the model placed by its SCENE SPEC. Everything here is the
          // same square, the same numbers and the same blue edge as the
          // floor-plan preview — the two used to disagree because this stage
          // was a fixed 10 m tile while the preview drew map3d.extent_m.
          const groundMat = new THREE.MeshBasicMaterial({ color: 0x2e3742 })
          const groundGeo = new THREE.PlaneGeometry(1, 1)
          const ground = new THREE.Mesh(groundGeo, groundMat)
          ground.rotation.x = -Math.PI / 2
          scene.add(ground)
          const edges = new THREE.LineSegments(
            new THREE.EdgesGeometry(groundGeo),
            new THREE.LineBasicMaterial({ color: 0x58a6ff }),
          )
          edges.rotation.x = -Math.PI / 2
          edges.position.y = 0.002
          scene.add(edges)

          // The model is placed from the SPEC — size, ground height and shift
          // are server numbers, not rules re-derived here. The one local step
          // is the division by the measured extent, exactly like place().
          // Without a spec (room models) the neutral fallback centres the
          // model on the stage at height 0.
          const applyPlacement = (p: TilePlacement) => {
            const spec = p.spec
            const extent = p.extentM && p.extentM > 0 ? p.extentM : 10
            ground.scale.set(extent, extent, 1)
            edges.scale.set(extent, extent, 1)
            // A GROUND model hangs BELOW the square — an opaque stage would
            // hide exactly the part whose height is being dialled.
            const isGround = spec?.display === 'ground'
            groundMat.transparent = isGround
            groundMat.opacity = isGround ? 0.35 : 1
            groundMat.depthWrite = !isGround
            groundMat.needsUpdate = true

            place.rotation.set(0, 0, 0)
            place.scale.setScalar(1)
            place.position.set(0, 0, 0)
            // The seating shift of the previous run (below) — cleared before
            // anything is measured, or every re-apply would stack another one.
            orient.position.set(0, 0, 0)
            // `+rad` since E4 (§ A1.1): the THIRD renderer of `spec.yaw_deg`,
            // next to `placeModelSpec` (@anima/scene-render) and the 3D client.
            // This viewer has its own placement maths, so it needs the sign
            // separately — with the old minus it would show every model turned
            // the other way round from the scene it is being tuned for.
            place.rotation.y = _deg(spec ? spec.yaw_deg : p.yawDeg)
            // How BIG a model is must not depend on how it is TURNED: the
            // axis-aligned hull of a tilted box is larger than the box, so a
            // fine-angle orientation fix made the model shrink as it was
            // dialled (user finding 2026-07-28 — first on room models, then
            // on location models). Measure with the fix SNAPPED to 90°, draw
            // with the real one. Same rule as place() in @anima/scene-render;
            // this viewer has its own placement math and needs it separately.
            const _rr = rotationRef.current
            const _snap = (v?: number) => Math.round((v || 0) / 90) * 90
            orient.rotation.set(_deg(_snap(_rr?.x)), _deg(_snap(_rr?.y)),
                                _deg(_snap(_rr?.z)))
            place.updateMatrixWorld(true)
            const b = new THREE.Box3().setFromObject(place)
            const s = b.getSize(new THREE.Vector3())
            const measured = (spec?.measure === 'xyz'
              ? Math.max(s.x, s.y, s.z) : Math.max(s.x, s.z)) || 1
            orient.rotation.set(_deg(_rr?.x), _deg(_rr?.y), _deg(_rr?.z))
            const target = spec?.max_m
              ?? extent * Math.max(0.02, Math.min(1, p.size ?? 1))
            // Seating datum (§ B2 step 4, revised 2026-08-20): the object
            // hangs on the centre it has BEFORE the yaw, and the yaw spins it
            // about that point — measuring the FINISHED, turned hull made a
            // model's position depend on its angle, which is a datum the
            // server cannot reproduce from a bbox (its composed prop markers
            // then land beside the prop). Same rule as place() in
            // @anima/scene-render; this viewer has its own placement math and
            // needs it separately. Measured BEFORE the scale (still 1) and
            // with the yaw off, so the shift is a plain object-frame offset.
            const yawKeep = place.rotation.y
            place.rotation.y = 0
            place.updateMatrixWorld(true)
            const cFix = new THREE.Box3().setFromObject(place)
              .getCenter(new THREE.Vector3())
            orient.position.set(-cFix.x, -cFix.y, -cFix.z)
            place.rotation.y = yawKeep
            place.scale.setScalar(target / measured)
            place.updateMatrixWorld(true)
            const b2 = new THREE.Box3().setFromObject(place)
            // With a spec the offsets are already baked into anchor/bottom_y;
            // without one they are the only thing that moves the model.
            const ax = spec ? spec.anchor[0] : (offsetXRef.current || 0)
            const az = spec ? spec.anchor[1] : (offsetZRef.current || 0)
            const bottom = spec ? spec.bottom_y : (offsetYRef.current || 0)
            place.position.set(ax, bottom - b2.min.y, az)

            // Reference sizes for the dials next to this viewer — the same
            // kit the floor-plan preview draws, so a metre means the same
            // thing in both (measureKit).
            disposeAids(aidsRef.current)
            const figure = p.figureHeightWorld || 0
            if (figure > 0) {
              aidsRef.current = buildMeasureAids(THREE, {
                measure: p.measure ?? null,
                extentM: extent,
                k: p.k || 1,
                planWidthM: p.planWidthM || 0,
                storeyWorld: p.storeyWorld || 3,
                storeyRealM: p.storeyRealM || 3,
                figureHeightWorld: figure,
                modelWidthM: spec?.max_m,
                modelBottomY: spec?.bottom_y,
                walkYWorld: spec?.walk_y_world,
              })
              scene.add(aidsRef.current)
            }
          }
          placeFnRef.current = applyPlacement
          disposers.push(() => {
            if (placeFnRef.current === applyPlacement) placeFnRef.current = null
          })
          applyPlacement(placementRef.current)

          // Frame square + model together from a raised angle — the square is
          // the reference, so it must always be fully in view.
          place.updateMatrixWorld(true)
          const mb = new THREE.Box3().setFromObject(place)
          const stage = placementRef.current.extentM || 10
          const span = Math.max(stage * 1.2, (mb.max.y - mb.min.y) * 1.5, 1.2)
          const dist = (span / 2) / Math.tan((Math.PI * camera.fov) / 360) * 1.7
          camera.position.set(dist * 0.75, dist * 0.7, dist * 0.9)
          camera.near = dist / 100
          camera.far = dist * 100
          camera.updateProjectionMatrix()
          controls.target.set(0, Math.min(stage * 0.15, Math.max(0.1, mb.max.y / 2)), 0)
          controls.update()
        } else {
          // Frame the model: centre it and pull the camera back to fit.
          const box = new THREE.Box3().setFromObject(pivot)
          const size = box.getSize(new THREE.Vector3())
          const center = box.getCenter(new THREE.Vector3())
          pivot.position.sub(center)
          // The height group's placement (`clipGroup`): framed as the bind
          // pose, then lowered / lifted against a floor grid at the bare bind
          // soles — the same terms as the marker figures.
          if (stance) {
            const floor = new THREE.GridHelper(2, 20, 0x58a6ff, 0x30363d)
            floor.position.y = stance.floorY - center.y
            floorWorldY = floor.position.y
            scene.add(floor)
            pivot.position.y += stance.y
            pivot.updateMatrixWorld(true)
          }

          // The framing has to hold the SCALE KIT too, or a footstool fills
          // the frame and the 1.70 m figure beside it is off-screen — which
          // is exactly the comparison the kit exists for.
          const fitView = () => {
            let maxDim = Math.max(size.x, size.y, size.z) || 1
            const kitH = scaleFigureRef.current ? figureHeightRef.current : 0
            if (kitH > 0) {
              const metre = kitH / FIGURE_HEIGHT_M
              // The figure sits on ONE side, the camera looks at the model's
              // centre: the visible width is twice the reach to the figure
              // (0.40 m margin + its ~0.16 m half-width).
              // A SINK raises the ground plane above the mesh's lower edge, so
              // the vertical span to hold is the figure PLUS what was buried —
              // otherwise a deeply sunk trunk frames its person off-screen.
              maxDim = Math.max(maxDim, size.x + 1.12 * metre, kitH * 1.3,
                kitH - (groundOffsetRef.current || 0) * metre)
            }
            const dist = (maxDim / 2) / Math.tan((Math.PI * camera.fov) / 360)
            const back = dist * 1.6
            // WHICH view is reset to depends on the mode. Straight on is the
            // authoring view — and the only framing a viewer without the
            // toggle has ever had, so nothing changes for those. With the
            // toggle OFF the reset is a three-quarter view instead: rotation
            // is free there, and a solid object only reads as a body from an
            // angle. Same distance either way.
            if (frontalRef.current || !frontalModeRef.current) {
              camera.position.set(0, 0, back)
            } else {
              camera.position.copy(new THREE.Vector3(0.6, 0.45, 0.9)
                .normalize().multiplyScalar(back))
            }
            camera.near = dist / 100
            camera.far = dist * 100
            camera.updateProjectionMatrix()
            controls.target.set(0, 0, 0)
            controls.update()
            const f = focusRef.current
            if (f) {
              object.updateMatrixWorld(true)
              const c = object.localToWorld(new THREE.Vector3(f.center[0], f.center[1], f.center[2]))
              const d = (f.radius / Math.sin((Math.PI * camera.fov) / 360)) * 1.1
              const dir = (f.side ? new THREE.Vector3(1, 0.12, 0.1) : new THREE.Vector3(0.45, 0.15, 1))
                .transformDirection(object.matrixWorld)
              camera.position.copy(c).addScaledVector(dir, d)
              camera.near = d / 100
              camera.far = d * 100
              camera.updateProjectionMatrix()
              controls.target.copy(c)
              controls.update()
            }
          }
          // How big this model is, as ONE number: the radius of its bounding
          // sphere. It is the yardstick for whether the next model to load is
          // still the same object (`shouldRefit`).
          const radius = size.length() / 2
          const prevCam = camStateRef.current
          fitView()
          // THE CAMERA SURVIVES A MODEL SWITCH (§ B1) — where the caller asked
          // for it: a re-split frame or a picture variant is the same object in
          // another version, and re-framing it would throw away the angle that
          // was being worked at. Only a model of a different SIZE is framed
          // again. Without `keepCamera` every load frames, as it always did.
          if (keepCameraRef.current && prevCam
              && !shouldRefit(prevCam.radius, radius)) {
            camera.position.fromArray(prevCam.pos)
            controls.target.fromArray(prevCam.target)
            controls.update()
          }
          // Saved either way, so switching the flag on mid-life has something
          // to restore — only the restore above is gated.
          const saveCam = () => {
            camStateRef.current = {
              pos: camera.position.toArray() as [number, number, number],
              target: controls.target.toArray() as [number, number, number],
              radius,
            }
            // The camera as plain numbers on the mount (position, target): what a UI check compares.
            mount.dataset.camera = [...camStateRef.current.pos, ...camStateRef.current.target]
              .map((v) => v.toFixed(4)).join(',')
          }
          saveCam()
          controls.addEventListener('change', saveCam)
          disposers.push(() => controls.removeEventListener('change', saveCam))
          // Only the kit switch and "Reset view" refit — a marker edit or a
          // typed dim must never yank a camera the user has orbited into
          // place.
          refitFnRef.current = fitView
          disposers.push(() => {
            if (refitFnRef.current === fitView) refitFnRef.current = null
          })

          // ── Marker + dims overlay (model mode) ──
          // Markers live in the pivot frame (raw-box fractions → local
          // coordinates, they turn with the orientation fix); the dims box is
          // measured in WORLD space around the oriented model. Both rebuild
          // live through overlayFnRef — dims typing, marker edits and every
          // ↻ click refresh without a reload.
          const rawMaxDim = Math.max(rawSize.x, rawSize.y, rawSize.z) || 1
          const waterGroup = new THREE.Group()
          pivot.add(waterGroup)
          const markerGroup = new THREE.Group()
          pivot.add(markerGroup)
          const dimsGroup = new THREE.Group()
          followTurn.add(dimsGroup)
          const accessGroup = new THREE.Group()
          followTurn.add(accessGroup)
          // Preview figures anchor in WORLD space (they stand upright while
          // the marker point rides the object through the orientation fix) —
          // the upright world: they turn with the model's drag turn.
          const figGroup = new THREE.Group()
          followTurn.add(figGroup)
          // The scale kit — standing 1.70 m reference + metre grid. Its own
          // group so it lives and dies with one switch, untouched by the
          // marker figures above (those are POSED, at a marker; this one
          // stands beside the model and answers "how big is this thing").
          const refGroup = new THREE.Group()
          scene.add(refGroup)
          const clearGroup = (g: Object3D) => {
            for (const c of [...g.children]) {
              g.remove(c)
              // Figure clones share skeleton/geometry with the module cache —
              // remove them, never dispose through them.
              if (c.userData.__shared) continue
              c.traverse((o: Object3D) => {
                const mesh = o as Mesh
                mesh.geometry?.dispose?.()
                const m = mesh.material as
                  (MeshStandardMaterial & { map?: { dispose?: () => void } }) | undefined
                m?.map?.dispose?.()
                m?.dispose?.()
              })
            }
          }
          // ── Picture areas: the outlines of the key surfaces ──
          // The edges come from the server in glTF y-up MODEL space (the
          // coordinates GLTFLoader hands over), so the group hangs under the
          // loaded object itself: pivot centring and the orientation fix then
          // carry the outline along with the surface it belongs to, and this
          // viewer measures nothing (§ B5a).
          const areaGroup = new THREE.Group()
          object.add(areaGroup)
          const rebuildAreas = () => {
            clearGroup(areaGroup)
            for (const area of areaOutlinesRef.current || []) {
              const pts: Vector3[] = []
              for (const [a, b] of area.edges || []) {
                pts.push(new THREE.Vector3(a[0], a[1], a[2]),
                         new THREE.Vector3(b[0], b[1], b[2]))
              }
              if (!pts.length) continue
              // Colour by KIND, out of the one constant (R8) — a kind this
              // client does not know yet draws in neutral grey rather than
              // not at all.
              const hex = areaKindOf(area.kind)?.color || '#8b949e'
              const line = new THREE.LineSegments(
                new THREE.BufferGeometry().setFromPoints(pts),
                new THREE.LineBasicMaterial({ color: new THREE.Color(hex),
                  depthTest: false }))
              line.renderOrder = 4
              areaGroup.add(line)
            }
          }
          areaFnRef.current = rebuildAreas
          rebuildAreas()
          disposers.push(() => {
            if (areaFnRef.current === rebuildAreas) areaFnRef.current = null
            clearGroup(areaGroup)
          })

          // ── Overlay polylines (model space, like the area outlines) ──
          const polylineGroup = new THREE.Group()
          object.add(polylineGroup)
          const rebuildPolylines = () => {
            clearGroup(polylineGroup)
            for (const pl of polylinesRef.current || []) {
              const pts = (pl.points || []).map((p) => new THREE.Vector3(p[0], p[1], p[2]))
              if (pts.length < 2) continue
              const line = new THREE.Line(
                new THREE.BufferGeometry().setFromPoints(pts),
                new THREE.LineBasicMaterial({ color: new THREE.Color(pl.color), depthTest: false }))
              line.renderOrder = 5
              polylineGroup.add(line)
            }
          }
          polylineFnRef.current = rebuildPolylines
          rebuildPolylines()
          disposers.push(() => {
            if (polylineFnRef.current === rebuildPolylines) polylineFnRef.current = null
            clearGroup(polylineGroup)
          })

          // ── Live vertex preview (`meshAdjust`): the loaded positions and colour are kept, every change maps
          // them anew — the meshes are this load's own, so nothing shared is touched. ──
          let adjustTargets: Array<{ mesh: Mesh; base: Float32Array; baseV: Float32Array | null
            color: InstanceType<typeof THREE.Color> | null }> = []
          let adjustMatch: string | null = null
          const applyMeshAdjust = () => {
            const adjust = meshAdjustRef.current
            const match = adjust?.match || ''
            // The strands own the hair vertices while they run: a placement map (and the capture of the loaded
            // positions) needs the mesh's own geometry back — the frame loop turns them on again without a map.
            if (adjust?.map || adjust?.cut || match !== adjustMatch) strandOn(false)
            if (match !== adjustMatch) {
              adjustMatch = match
              adjustTargets = []
              if (match) {
                object.traverse((o: Object3D) => {
                  const mesh = o as Mesh
                  if (!mesh.isMesh || !o.name.startsWith(match)) return
                  const pos = mesh.geometry.getAttribute('position')
                  const base = new Float32Array(pos.count * 3)
                  for (let i = 0; i < pos.count; i++) {
                    base[i * 3] = pos.getX(i); base[i * 3 + 1] = pos.getY(i); base[i * 3 + 2] = pos.getZ(i)
                  }
                  const uv = mesh.geometry.getAttribute('uv')
                  const baseV = uv ? new Float32Array(uv.count) : null
                  if (uv && baseV) for (let i = 0; i < uv.count; i++) baseV[i] = uv.getY(i)
                  const mat = mesh.material as MeshStandardMaterial | MeshStandardMaterial[]
                  const color = !Array.isArray(mat) && mat?.color ? mat.color.clone() : null
                  adjustTargets.push({ mesh, base, baseV, color })
                })
              }
            }
            for (const target of adjustTargets) {
              const pos = target.mesh.geometry.getAttribute('position')
              const map = adjust?.map
              // A cut fits the mesh only when it names no more vertices than it has (the HAAR cards come first).
              const cut = adjust?.cut && adjust.cut.positions.length <= pos.count * 3 ? adjust.cut : null
              const nCut = cut ? cut.positions.length / 3 : 0
              // Running strands write these vertices themselves (a colour drag only tints).
              const own = !(strand?.enabled && target.mesh === strand.mesh)
              for (let i = 0; own && i < pos.count; i++) {
                const p: [number, number, number] = i < nCut && cut
                  ? [cut.positions[i * 3], cut.positions[i * 3 + 1], cut.positions[i * 3 + 2]]
                  : [target.base[i * 3], target.base[i * 3 + 1], target.base[i * 3 + 2]]
                const q = map ? map(p) : p
                pos.setXYZ(i, q[0], q[1], q[2])
              }
              const uv = target.mesh.geometry.getAttribute('uv')
              if (own && uv && target.baseV) {
                for (let i = 0; i < uv.count; i++) uv.setY(i, i < nCut && cut ? cut.v[i] : target.baseV[i])
                uv.needsUpdate = true
              }
              if (own) {
                pos.needsUpdate = true
                target.mesh.geometry.computeBoundingBox()
                target.mesh.geometry.computeBoundingSphere()
              }
              const mat = target.mesh.material as MeshStandardMaterial
              if (target.color && !Array.isArray(mat) && mat.color) {
                const tint = adjust?.tint
                mat.color.copy(target.color)
                if (tint) mat.color.setRGB(target.color.r * tint[0], target.color.g * tint[1], target.color.b * tint[2])
              }
            }
          }
          meshAdjustFnRef.current = applyMeshAdjust
          applyMeshAdjust()
          disposers.push(() => {
            if (meshAdjustFnRef.current === applyMeshAdjust) meshAdjustFnRef.current = null
            adjustTargets = []
          })

          // ── The door leaf test swing (spec § 6) ──
          // The SAME routine the 3D client hangs its pivot with — `leafPivot`
          // of @anima/scene-render (ruling R13): the rule is stated in the
          // FIXED frame `place()` seats (min.x, min.y, centre z of the box
          // turned by the orientation fix) and mapped back into the raw one,
          // axis included; `rotationRef.current` is that very fix, the one
          // `orient` above applies here and `_door_prop_models` ships as
          // `fix_euler`. Hung INSIDE the loaded object, below `orient`, so the
          // raw coordinates are the right ones; the leaf keeps its world
          // position until the pivot turns. Nothing is measured here.
          let leafNode: Object3D | null = null
          object.traverse((o: Object3D) => {
            if (!leafNode && o !== object && o.name === 'leaf') leafNode = o
          })
          setHasLeaf(!!leafNode)
          let leafPivotGroup: Object3D | null = null
          let leafHome: Vector3 | null = null
          const swingLeaf = (open: boolean) => {
            const bbox = leafBboxRef.current
            const leaf = leafNode as Object3D | null
            if (!leaf || !leaf.parent || !bbox) return
            if (!leafPivotGroup) {
              leafPivotGroup = new THREE.Group()
              leafPivotGroup.name = 'leaf_pivot'
              leafHome = leaf.position.clone()
              leaf.parent.add(leafPivotGroup)
              leafPivotGroup.add(leaf)
            }
            // Re-seated on every swing: a fresh detection moves the box, a
            // turned orientation dial moves the hinge edge.
            const spec = leafPivot(bbox, rotationRef.current)
            leafPivotGroup.position.set(spec.point[0], spec.point[1], spec.point[2])
            leaf.position.copy(leafHome as Vector3).sub(leafPivotGroup.position)
            leafPivotGroup.setRotationFromAxisAngle(
              new THREE.Vector3(spec.axis[0], spec.axis[1], spec.axis[2]),
              open ? (85 * Math.PI) / 180 : 0)
            leafPivotGroup.updateMatrixWorld(true)
          }
          swingFnRef.current = swingLeaf
          disposers.push(() => {
            if (swingFnRef.current === swingLeaf) swingFnRef.current = null
          })

          // ── The assembly preview: pictures INTO the slot materials ──
          // The same routine both renderers call (@anima/scene-render), so
          // this preview cannot disagree with the scene about how a poster
          // looks. It REPLACES `mesh.material` with a clone, so the mesh's own
          // materials are remembered here and put back before every re-apply —
          // otherwise switching the preview off would leave the last picture
          // hanging with no way back short of a reload.
          const ownMaterials = new Map<Mesh, Material | Material[]>()
          for (const mesh of ordered) ownMaterials.set(mesh, mesh.material)
          let slotClones: Material[] = []
          const applySlots = () => {
            disposeSlotMaterials(slotClones)
            slotClones = []
            for (const [mesh, mat] of ownMaterials) mesh.material = mat
            const values = slotsRef.current
            if (!values || !Object.keys(values).length) return
            slotClones = applySlotMaterials(THREE, object, values,
              (src, onError) => new THREE.TextureLoader()
                .load(src, undefined, undefined, onError))
          }
          slotFnRef.current = applySlots
          applySlots()
          disposers.push(() => {
            if (slotFnRef.current === applySlots) slotFnRef.current = null
            // Put the mesh back BEFORE the general teardown traverses the
            // scene: it disposes whatever material is attached, and a clone
            // left in place would let the model's own one leak instead.
            // Disposers run LIFO, so this one runs first.
            disposeSlotMaterials(slotClones)
            slotClones = []
            for (const [mesh, mat] of ownMaterials) mesh.material = mat
          })

          // ── The polygon pick (D5 / R1) ──
          // SIGHT logic, nothing else: which triangles did the admin ring in?
          // Three tests per triangle, all in this camera's frame — the centre
          // projects inside the ring, the face turns towards the camera, and
          // the ray from the camera through that centre reaches it first
          // (unoccluded). With `through` (kind leaf, E2) only the FIRST test
          // runs: the ring is a prism and takes back faces, edges and
          // handles under it — the server cuts the same prism through the
          // footprint of what it gets. The flat index is the R1 one: meshes
          // by name, triangles in buffer order, counted straight through.
          const selectFaces = (ring: Array<[number, number]>,
                               vw: number, vh: number, through: boolean): number[] => {
            const out: number[] = []
            if (ring.length < 3 || vw <= 0 || vh <= 0) return out
            place.updateMatrixWorld(true)
            const camPos = camera.getWorldPosition(new THREE.Vector3())
            const ray = new THREE.Raycaster()
            const a = new THREE.Vector3()
            const b = new THREE.Vector3()
            const c = new THREE.Vector3()
            const centre = new THREE.Vector3()
            const ab = new THREE.Vector3()
            const ac = new THREE.Vector3()
            const normal = new THREE.Vector3()
            const toCam = new THREE.Vector3()
            let base = 0
            for (const mesh of ordered) {
              // An INSTANCED mesh draws one geometry many times — a face index
              // would name a triangle of the template, not of an instance, so
              // it can carry no area. (It never reaches this list either; the
              // guard is here so the rule stands where the index is built.)
              if ((mesh as { isInstancedMesh?: boolean }).isInstancedMesh) continue
              const geo = mesh.geometry
              const pos = geo.attributes.position
              const index = geo.index
              // The WHOLE buffer, deliberately: `geometry.drawRange` and
              // material groups can render a subset, but the server counts
              // every triangle of the object (`calc_loop_triangles`), so the
              // flat index has to as well. A prop mesh out of the split has
              // neither, and one that did would fail the layout comparison.
              const tris = triCountOf(mesh)
              for (let i = 0; i < tris; i++) {
                const i0 = index ? index.getX(3 * i) : 3 * i
                const i1 = index ? index.getX(3 * i + 1) : 3 * i + 1
                const i2 = index ? index.getX(3 * i + 2) : 3 * i + 2
                a.fromBufferAttribute(pos, i0)
                b.fromBufferAttribute(pos, i1)
                c.fromBufferAttribute(pos, i2)
                mesh.localToWorld(a)
                mesh.localToWorld(b)
                mesh.localToWorld(c)
                centre.copy(a).add(b).add(c).multiplyScalar(1 / 3)
                const p = centre.clone().project(camera)
                const sx = ((p.x + 1) / 2) * vw
                const sy = ((1 - p.y) / 2) * vh
                if (!pointInPolygon(sx, sy, ring)) continue
                if (through) { out.push(base + i); continue }
                // Facing the camera: the winding normal against the line of
                // sight. A back face of the same panel would double every
                // index and drag the far wall of a box into the selection —
                // exactly what a leaf pick WANTS and a surface pick must not.
                normal.copy(ab.subVectors(b, a)).cross(ac.subVectors(c, a))
                if (normal.dot(toCam.subVectors(camPos, centre)) <= 0) continue
                // Unoccluded: the first thing the ray meets has to BE this
                // triangle. `faceIndex` is three's triangle number in buffer
                // order — the very number R1 counts.
                ray.set(camPos, toCam.subVectors(centre, camPos).normalize())
                // Against the MESHES only, never the whole subtree: the area
                // outlines hang under the model as `LineSegments`, and a line
                // is raycast with a fat threshold in model units — it would
                // "occlude" every triangle behind it.
                const hit = ray.intersectObjects(ordered, false)[0]
                if (!hit || hit.object !== mesh || hit.faceIndex !== i) continue
                out.push(base + i)
              }
              base += tris
            }
            return out
          }
          selectFacesRef.current = selectFaces
          disposers.push(() => {
            if (selectFacesRef.current === selectFaces) selectFacesRef.current = null
          })

          const textSprite = (text: string, color: string, h: number) => {
            const c = document.createElement('canvas')
            const ctx = c.getContext('2d')!
            ctx.font = '600 26px system-ui, sans-serif'
            c.width = Math.ceil(ctx.measureText(text).width) + 14
            c.height = 34
            const ctx2 = c.getContext('2d')!
            ctx2.font = '600 26px system-ui, sans-serif'
            ctx2.fillStyle = 'rgba(13,17,23,0.72)'
            ctx2.fillRect(0, 0, c.width, c.height)
            ctx2.fillStyle = color
            ctx2.fillText(text, 7, 26)
            const tex = new THREE.CanvasTexture(c)
            const spr = new THREE.Sprite(new THREE.SpriteMaterial({
              map: tex, depthTest: false }))
            spr.renderOrder = 3
            spr.scale.set(h * (c.width / c.height), h, 1)
            return spr
          }
          const rebuildOverlay = () => {
            clearGroup(markerGroup)
            clearGroup(waterGroup)
            clearGroup(dimsGroup)
            clearGroup(accessGroup)
            clearGroup(figGroup)
            clearGroup(refGroup)
            const figToken = ++figTokenRef.current
            // The model's box in WORLD space, after the orientation fix —
            // both the scale kit and the dims overlay below measure from it,
            // so the figure stands on the same lower edge the H label marks.
            // setFromObject refreshes only `object` itself, never its parents:
            // the framing just moved the pivot, and a stale pivot matrix put
            // the ground at a bottom-origin mesh's half height.
            previewRoot.updateMatrixWorld(true)
            const ob = new THREE.Box3().setFromObject(object)
            const accessMetre = figureHeightRef.current / FIGURE_HEIGHT_M
            if (accessMetre > 0 && spatialAuthoringRef.current) {
              const centre = ob.getCenter(new THREE.Vector3())
              const groundY = ob.min.y - (groundOffsetRef.current || 0) * accessMetre
              // A ground tool still needs its real metre plane when the optional mannequin kit is off.
              if (!scaleFigureRef.current) {
                const reach = Math.max(ob.max.x - ob.min.x, ob.max.z - ob.min.z) + 4 * accessMetre
                const cells = Math.max(2, Math.ceil(reach / accessMetre))
                const grid = new THREE.GridHelper(cells * accessMetre, cells, 0x8b949e, 0x8b949e)
                grid.position.set(centre.x, groundY, centre.z)
                accessGroup.add(grid)
              }
              for (const point of actionAccessRef.current || []) {
                const color = point.role === 'actor' ? 0x58a6ff : 0xd2a8ff
                const position = new THREE.Vector3(...accessWorldPoint(point, {
                  centreX: centre.x, centreZ: centre.z, groundY, unitsPerMetre: accessMetre }))
                const ring = new THREE.Mesh(new THREE.RingGeometry(.12 * accessMetre, .16 * accessMetre, 28),
                  new THREE.MeshBasicMaterial({ color, side: THREE.DoubleSide, depthTest: false }))
                ring.rotation.x = -Math.PI / 2
                ring.position.copy(position); ring.renderOrder = 4
                accessGroup.add(ring)
                const yaw = point.yaw * Math.PI / 180
                const heading = new THREE.ArrowHelper(new THREE.Vector3(Math.sin(yaw), 0, Math.cos(yaw)),
                  position, .5 * accessMetre, color, .13 * accessMetre, .08 * accessMetre)
                accessGroup.add(heading)
                const label = textSprite(point.label, point.role === 'actor' ? '#58a6ff' : '#d2a8ff', .16 * accessMetre)
                label.position.copy(position); label.position.y += .18 * accessMetre
                accessGroup.add(label)
              }
            }

            // ── Scale kit: the 1.70 m reference beside the model ──
            // `figureHeight` IS the conversion: it is what 1.70 m measures in
            // this mesh's units, so every metre here is figH / 1.70.
            const scaleH = figureHeightRef.current
            if (scaleFigureRef.current && scaleH > 0) {
              const metre = scaleH / FIGURE_HEIGHT_M
              // WHERE THE GROUND IS. The scene composes
              // `bottom_y = floor + ground_offset_m`, so the floor this mesh
              // was dialled for is its lower edge MINUS the offset: at
              // −0.20 m the plane rides 20 cm above the mesh's bottom, and
              // that much of it is buried. The mesh does not move — the
              // dims box, the markers and the framing all hang on it.
              const sinkM = groundOffsetRef.current || 0
              const groundY = ob.min.y - sinkM * metre
              // Beside, never inside: half the model's width plus a fixed
              // 0.40 m margin, so a wide mesh pushes the figure out instead
              // of swallowing it. The figure itself is ~0.31 m across.
              const offX = (ob.max.x - ob.min.x) / 2 + 0.4 * metre
              const cx = (ob.min.x + ob.max.x) / 2
              const cz = (ob.min.z + ob.max.z) / 2
              // Same neutral mannequin as every other metre dial in the admin
              // (measureKit) — it must read as "the reference", not as a
              // character, and it NEVER scales with the model.
              const fig = referenceFigure(THREE, scaleH)
              // Soles on the GROUND, never on the mesh's lower edge: the
              // person stands on the plane the object is sunk into, which is
              // what makes the sink readable at all.
              fig.position.set(cx + offX, groundY, cz)
              refGroup.add(fig)
              // Unit label, not UI copy: "1.70 m" reads the same in every
              // language the admin speaks, like the dims labels below.
              const tag = textSprite('1.70 m', '#f0f6fc', scaleH * 0.14)
              tag.position.set(cx + offX, groundY + scaleH * 1.12, cz)
              refGroup.add(tag)
              // One-metre ground grid under both — a metre stated once is a
              // claim, a metre repeated is a ruler. Whole cells, wide enough
              // to reach past the figure and around the model.
              const reach = Math.max(offX + metre, (ob.max.z - ob.min.z) / 2 + metre)
              const cells = Math.max(2, Math.ceil((2 * reach) / metre))
              // THE GROUND ITSELF, under the ruler. The grid is a LINE helper
              // and hides nothing, so a sunk mesh would keep showing its
              // buried half straight through the "ground" and the dial would
              // read as no dial at all. The disc is the opaque part: solid,
              // depth-writing, the same slate the stage ground of tile mode
              // uses, and wide enough (2 × the grid's reach) that its rim
              // never reads as the edge of a table. It lives and dies with
              // the reference figure, because a ground without the person and
              // the ruler on it is a floor nobody can measure against — and
              // switching the kit off is how one looks at a bare mesh.
              const disc = new THREE.Mesh(
                new THREE.CircleGeometry(reach * 2, 64),
                new THREE.MeshBasicMaterial({ color: 0x2e3742 }))
              disc.rotation.x = -Math.PI / 2
              disc.position.set(cx, groundY, cz)
              refGroup.add(disc)
              const grid = new THREE.GridHelper(cells * metre, cells,
                0x8b949e, 0x8b949e)
              // A hair above the disc, or the two z-fight over the same plane.
              grid.position.set(cx, groundY + metre * 0.002, cz)
              const gm = grid.material as Material & { opacity: number
                transparent: boolean; depthWrite: boolean }
              gm.transparent = true
              gm.opacity = 0.22
              gm.depthWrite = false
              refGroup.add(grid)
            }
            // ONE preview figure: the neutral test figure holding frame 0
            // of `kind` (the `role` half of a pair clip), its bind-pose root
            // at (x, y, z) and turned by `facingDeg`. Marker figures anchor
            // in WORLD space — they stand upright while the marker point
            // rides the object through the orientation fix — and they live in
            // `figGroup`, never under the model or the area overlay.
            const addMarkerFigure = async (o: {
              x: number; y: number; z: number
              kind?: string; role?: 'a' | 'b'; surfaceGroup?: string
              facingDeg?: number; figH: number; token: number }) => {
              const src = await loadTestFigure()
              if (!src || disposed || figTokenRef.current !== o.token) return
              const anim = o.kind ? await loadClip(o.kind, o.role || '') : null
              const { clone: skclone } =
                await import('three/examples/jsm/utils/SkeletonUtils.js')
              if (disposed || figTokenRef.current !== o.token) return
              const standRef = anim ? await standHipsRef() : null
              if (disposed || figTokenRef.current !== o.token) return
              const inst = skclone(src) as Object3D
              const fpivot = new THREE.Group()
              fpivot.add(inst)
              const hipsOf = (root: Object3D): Object3D | null => {
                let found: Object3D | null = null
                root.traverse((o2) => { if (!found && /hips/i.test(o2.name)) found = o2 })
                return found
              }
              const instHips = hipsOf(inst)
              // Up-axis fix measured on the REST skeletons — same logic as
              // the floor-plan preview / the main clip path above.
              if (anim) {
                const clipHips = hipsOf(anim.restObj)
                if (instHips?.parent && clipHips?.parent) {
                  inst.updateMatrixWorld(true)
                  anim.restObj.updateMatrixWorld(true)
                  const restModel = instHips.parent.getWorldQuaternion(new THREE.Quaternion())
                  const restClip = clipHips.parent.getWorldQuaternion(new THREE.Quaternion())
                  let bestRx = 0
                  let bestAngle = Infinity
                  for (const rx of [0, Math.PI / 2, -Math.PI / 2, Math.PI]) {
                    const cand = new THREE.Quaternion()
                      .setFromEuler(new THREE.Euler(rx, 0, 0)).multiply(restModel)
                    const angle = cand.angleTo(restClip)
                    if (angle < bestAngle) { bestAngle = angle; bestRx = rx }
                  }
                  fpivot.rotation.x = bestRx
                }
              }
              // SIZE AND ANCHOR FROM THE BIND POSE, through the shared
              // routine — soles on 0, XZ centred, scaled to `figH` (1.70 m in
              // this mesh's units). The clip is played afterwards and never
              // re-grounds the body.
              // LATENT TRAP: this runs AFTER `fpivot.rotation.x = bestRx`, so
              // the box it measures is the box of the TILTED figure — with a
              // ±90° fix the "height" would be the figure's depth. Today
              // every clip in the library matches the figure's up axis and
              // `bestRx` is 0; the day one does not, the anchor has to be
              // taken before the tilt (or the tilt applied to a parent).
              // A shod figure anchors on the BARE body's box the record ships
              // (`figureBox` with the record; matched against this instance).
              anchorFigureBind(THREE, fpivot, o.figH, footPoseRef.current)
              // The clip's OWN hips height, put back. Every clip is played in
              // place (the hips position track is dropped above), which also
              // drops the height that track carried: without this, sit, sleep
              // and idle are all drawn at the same bind height and a seated
              // figure floats 0.43 m over the seat marker. Measured HERE, in
              // mesh units, so it scales with `figH` on its own — right after
              // the anchor (which leaves the world matrix current) and BEFORE
              // the clip is played, so it is the BIND height.
              const hipsBindY = instHips
                ? instHips.getWorldPosition(new THREE.Vector3()).y
                : null
              const hipsDrop = clipHipsDrop(hipsBindY, anim?.hipsMedian, standRef)
              // A shod figure only when it carries the fitted shoes (the
              // clay test figure never does): same rule as the main viewer.
              const shodFig = footPoseRef.current && footPoseMatches(inst, footPoseRef.current)
                ? footPoseRef.current : null
              if (anim) {
                // Same bind-relative transplant as the main viewer above and
                // as the 3D client: the marker figure keeps its own stance —
                // and the shoe's extension right after it, from the unposed
                // cached clip.
                const donor = await donorRest()
                const corrections = restCorrections(THREE, donor, inst, undefined, shodFig)
                const restFig = shodFig ? restPoseOf(THREE, inst) : null
                const bareFig = bindRelativeClip(THREE, anim.clip, corrections)
                let bound = applyFootPose(THREE, bareFig,
                  shodFig, restFig, restFig ? transplantedRestPose(THREE, donor, restFig, corrections) : null)
                if (shodFig && clipHeightGroup(o.surfaceGroup) === 'ground') {
                  // The shod foot plant (scene-render `footPlant.ts`), for a
                  // marker on the ground: the floor is the marker's surface,
                  // the figure stands `−hipsDrop + offsets + lift` over it.
                  const { clone: skclone } = await import('three/examples/jsm/utils/SkeletonUtils.js')
                  if (disposed || figTokenRef.current !== o.token) return
                  const probe = skclone(inst) as Object3D
                  bound = plantFootPose(THREE, bound, bareFig, probe, shodFig, {
                    rootY: -hipsDrop + clipHeightOffsetM(anim.heightOffsets, o.surfaceGroup, o.figH)
                      + footPoseLiftM(shodFig, o.surfaceGroup, o.figH),
                    unitsPerCm: 0.01,
                  })
                }
                if (disposed || figTokenRef.current !== o.token) return
                const mixer = new THREE.AnimationMixer(inst)
                mixer.clipAction(bound).play()
                // THE SETTLED POSE, not the approach (2026-08-29). A clip is
                // a MOVEMENT, and its first frame is where the body starts
                // OUT of the pose: measured on `laying-back` (hips → head
                // against the rig's forward axis) the first frame lies 68.5°
                // ACROSS the facing and the last one 5.6° ALONG it. A place
                // preview that showed frame 0 therefore showed a figure
                // mid-roll — and a facing dialled against that put the
                // capacity slots at an angle to the bed, so two sleepers came
                // out head-to-foot instead of side by side. A hair before the
                // end rather than exactly on it: a looping action wraps at
                // `duration` and would land back on frame 0.
                mixer.setTime(Math.max(0, anim.clip.duration - 0.001))
              }
              const fig = new THREE.Group()
              fig.position.set(o.x, o.y - hipsDrop
                + clipHeightOffsetM(anim?.heightOffsets, o.surfaceGroup, o.figH)
                + footPoseLiftM(shodFig, o.surfaceGroup, o.figH), o.z)
              fig.rotation.y = _deg(o.facingDeg)
              fig.add(fpivot)
              fig.userData.__shared = true
              figGroup.add(fig)
            }
            // Numbered marker dots at their raw-box fractions.
            const r = rawMaxDim * 0.025
            const water = waterRef.current
            if (water) {
              // Sidecars include the fix; undo it before the parent applies it.
              const inverse = orient.quaternion.clone().invert()
              for (const region of water.regions) {
                if (region.outline.length < 3) continue
                if (region.enabled) {
                  const shape = new THREE.Shape(region.outline.map(([x, z]) => new THREE.Vector2(x, -z)))
                  for (const ring of region.holes || []) {
                    shape.holes.push(new THREE.Path(ring.map(([x, z]) => new THREE.Vector2(x, -z))))
                  }
                  const geometry = new THREE.ShapeGeometry(shape)
                  geometry.rotateX(-Math.PI / 2)
                  geometry.translate(0, water.box_min[1] + region.level, 0)
                  geometry.applyQuaternion(inverse)
                  waterGroup.add(new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({
                    color: region.look.tint, transparent: true, opacity: 1 - 0.6 * region.look.clarity,
                    side: THREE.DoubleSide, depthWrite: false })))
                } else {
                  for (const ring of [region.outline, ...(region.holes || [])]) {
                    if (!ring.length) continue
                    const points = [...ring, ring[0]].map(([x, z]) =>
                      new THREE.Vector3(x, water.box_min[1] + region.level, z).applyQuaternion(inverse))
                    const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(points),
                      new THREE.LineDashedMaterial({ color: '#f59e0b', dashSize: rawMaxDim * 0.02,
                        gapSize: rawMaxDim * 0.01, depthTest: false }))
                    line.computeLineDistances()
                    waterGroup.add(line)
                  }
                }
              }
            }
            const light = lightPointRef.current
            if (light) {
              const dot = new THREE.Mesh(
                new THREE.SphereGeometry(r, 10, 10),
                new THREE.MeshBasicMaterial({ color: light.color, depthTest: false }))
              dot.renderOrder = 3
              dot.position.set(
                rawBox.min.x + light.at[0] * rawSize.x,
                rawBox.min.y + light.at[1] * rawSize.y,
                rawBox.min.z + light.at[2] * rawSize.z)
              markerGroup.add(dot)
            }
            for (const point of surfacePointsRef.current || []) {
              const dot = new THREE.Mesh(
                new THREE.SphereGeometry(rawMaxDim * 0.004, 12, 12),
                new THREE.MeshBasicMaterial({ color: point.color, depthTest: false }))
              dot.renderOrder = 4
              dot.position.set(point.at[0], point.at[1], point.at[2])
              markerGroup.add(dot)
            }
            // The markers belong to the scale kit (user 2026-09-08): the
            // checkbox that hides the 1.70 m figure hides the numbered dots
            // and the posed preview figures with it — on a wall mirror they
            // sit right on the pane. `rebuildOverlay` re-runs on the toggle
            // (see its effect deps), so this is the whole switch.
            if (scaleFigureRef.current || spatialAuthoringRef.current) (markersRef.current || []).forEach((m, i) => {
              const local = new THREE.Vector3(
                rawBox.min.x + m.at[0] * rawSize.x,
                rawBox.min.y + m.at[1] * rawSize.y,
                rawBox.min.z + m.at[2] * rawSize.z)
              // Optional body-marker state; callers without it retain their palette.
              const color = m.assigned === undefined ? 0x3fb950
                : m.assigned ? 0x3fb950 : 0x8b949e
              const dot = new THREE.Mesh(
                new THREE.SphereGeometry(m.selected ? r * 1.35 : r, 10, 10),
                new THREE.MeshBasicMaterial({ color, depthTest: false }))
              dot.renderOrder = 2
              dot.position.copy(local)
              markerGroup.add(dot)
              if (m.selected) {
                const halo = new THREE.Mesh(new THREE.SphereGeometry(r * 1.8, 10, 10),
                  new THREE.MeshBasicMaterial({ color: 0xf0b35c, wireframe: true, depthTest: false }))
                halo.position.copy(local); halo.renderOrder = 3
                markerGroup.add(halo)
              }
              const num = textSprite(String(i + 1), `#${color.toString(16).padStart(6, '0')}`, rawMaxDim * 0.09)
              num.position.copy(local)
              num.position.y += r * 2.4
              markerGroup.add(num)
              if (spatialAuthoringRef.current && typeof m.facing === 'number') {
                const world = pivot.localToWorld(local.clone())
                const yaw = m.facing * Math.PI / 180
                const heading = new THREE.ArrowHelper(new THREE.Vector3(Math.sin(yaw), 0, Math.cos(yaw)),
                  world, .4 * accessMetre, color)
                figGroup.add(heading)
              }
              // Posed preview figures (1.7 m at the caller's mesh scale) —
              // ONE PER SLOT: a seat is only judgeable with someone sitting on
              // it, and a bench only with everyone it seats.
              const figH = figureHeightRef.current
              if (!(figH > 0)) return
              // `figH` IS the conversion: it is what 1.70 m measures in this
              // mesh's units, so one metre is figH / 1.70 of them.
              const perMetre = figH / FIGURE_HEIGHT_M
              if (spatialAuthoringRef.current) {
                const world = pivot.localToWorld(local.clone())
                markerSlots([world.x, world.z], m.facing, m.capacity || 1,
                  (m.spacing_m || .6) * perMetre, m.slot_axis).forEach(([x, z], slot) => {
                  const dot = new THREE.Mesh(new THREE.SphereGeometry(.055 * perMetre, 8, 8),
                    new THREE.MeshBasicMaterial({ color, depthTest: false }))
                  dot.position.set(x, world.y, z); dot.renderOrder = 4
                  figGroup.add(dot)
                  if (m.selected) {
                    const halo = new THREE.Mesh(new THREE.SphereGeometry(.075 * perMetre, 10, 10),
                      new THREE.MeshBasicMaterial({ color: 0xf0b35c, wireframe: true, depthTest: false }))
                    halo.position.copy(dot.position); halo.renderOrder = 5
                    figGroup.add(halo)
                  }
                  const label = textSprite(`Slot ${slot + 1}`, `#${color.toString(16).padStart(6, '0')}`, .12 * perMetre)
                  label.position.set(x, world.y + .12 * perMetre, z)
                  figGroup.add(label)
                })
              }
              const kind = m.previewKind || undefined
              void (async () => {
                const idx = await clipIndex()
                if (disposed || figTokenRef.current !== figToken) return
                const world = upright(() => pivot.localToWorld(local.clone()))
                // WHICH part of the body the marker point carries: a seated
                // body touches at the buttocks, so the root goes the place
                // type's share of the figure height BELOW the marked surface.
                // Same routine as the floor-plan preview and the 3D client —
                // but the number cannot come from the payload's `root_offset`
                // here, because a prop in this viewer is UNCOMPOSED: the
                // caller reads `root_drop` off the pose catalog's group and
                // the fraction becomes mesh units right here (0 while the
                // catalog is not loaded — the root on the surface).
                const rootY = figureRootY(world.y,
                  typeof m.rootDrop === 'number' ? m.rootDrop * figH : undefined)
                const pair = kind ? idx.pairs[kind] : undefined
                // Slot and pair geometry are the shared package's mirror of
                // the server formulas (`markerSlots`, `pairPoints`) — this
                // viewer shows ONE prop BEFORE any composition, so there is
                // no payload to read finished slots off. Metres → mesh units
                // through `perMetre` (spacing and the role offsets alike).
                if (pair) {
                  // A PAIR pose is ONE clip in two halves around ONE anchor:
                  // the server seats it at the marker CENTRE and turns the
                  // clip frame by `pairYaw`, each half standing at its
                  // sidecar `anchor_xz_m` in that frame — the same two
                  // figures the floor-plan preview draws, not one per slot.
                  const yawOffset = m.previewYawOffset || 0
                  const yawDeg = (pairYaw(m.facing, yawOffset) * 180) / Math.PI
                  const offset = (role: 'a' | 'b'): [number, number] => {
                    const [ox, oz] = pair.geometry?.roles?.[role]?.anchor_xz_m || [0, 0]
                    return [ox * perMetre, oz * perMetre]
                  }
                  const pts = pairPoints([world.x, world.z], m.facing, yawOffset,
                                         { a: offset('a'), b: offset('b') })
                  for (const role of ['a', 'b'] as const) {
                    if (spatialAuthoringRef.current) {
                      const label = textSprite(`Clip ${role.toUpperCase()}`, '#3fb950', .16 * perMetre)
                      label.position.set(pts[role][0], world.y + .22 * perMetre, pts[role][1])
                      figGroup.add(label)
                    }
                    await addMarkerFigure({
                      x: pts[role][0], y: rootY, z: pts[role][1],
                      kind, role, surfaceGroup: m.group, facingDeg: yawDeg, figH, token: figToken })
                  }
                  return
                }
                // 0.6 m = one person's width on a bench, the server's default.
                for (const [sx, sz] of markerSlots([world.x, world.z], m.facing,
                                                   m.capacity || 1,
                                                   (m.spacing_m || 0.6) * perMetre,
                                                   m.slot_axis)) {
                  await addMarkerFigure({ x: sx, y: rootY, z: sz, kind, surfaceGroup: m.group,
                                          facingDeg: m.facing, figH, token: figToken })
                }
              })()
            })
            // Oriented bounding box + coloured W/D/H edges with the REAL
            // metre values — which field means which direction.
            const dims = dimsOverlayRef.current
            if (!dims) return
            dimsGroup.add(new THREE.Box3Helper(ob, 0x6e7681))
            const edge = (a: [number, number, number],
                          b: [number, number, number], color: number) => {
              const g = new THREE.BufferGeometry().setFromPoints([
                new THREE.Vector3(...a), new THREE.Vector3(...b)])
              const line = new THREE.Line(g,
                new THREE.LineBasicMaterial({ color, depthTest: false }))
              line.renderOrder = 2
              dimsGroup.add(line)
            }
            const lbl = (text: string, color: string,
                         p: [number, number, number]) => {
              const s = textSprite(text, color, rawMaxDim * 0.085)
              s.position.set(...p)
              dimsGroup.add(s)
            }
            const out = rawMaxDim * 0.045
            // W along X (front bottom edge), D along Z (right bottom edge),
            // H along Y (front right vertical) — axis colours match nothing
            // else in the UI on purpose, they only mean "these three".
            edge([ob.min.x, ob.min.y, ob.max.z], [ob.max.x, ob.min.y, ob.max.z], 0xff7b72)
            lbl(`W ${dims.width_m.toFixed(2)} m`, '#ff7b72',
              [(ob.min.x + ob.max.x) / 2, ob.min.y - out, ob.max.z + out])
            edge([ob.max.x, ob.min.y, ob.min.z], [ob.max.x, ob.min.y, ob.max.z], 0x79c0ff)
            lbl(`D ${dims.depth_m.toFixed(2)} m`, '#79c0ff',
              [ob.max.x + out, ob.min.y - out, (ob.min.z + ob.max.z) / 2])
            edge([ob.max.x, ob.min.y, ob.max.z], [ob.max.x, ob.max.y, ob.max.z], 0x3fb950)
            lbl(`H ${dims.height_m.toFixed(2)} m`, '#3fb950',
              [ob.max.x + out, (ob.min.y + ob.max.y) / 2, ob.max.z + out])
          }
          const rebuildUpright = () => upright(rebuildOverlay)
          overlayFnRef.current = rebuildUpright
          rebuildUpright()
          const showFigures = (show: boolean) => {
            markerGroup.visible = show
            figGroup.visible = show
          }
          figuresFnRef.current = showFigures
          // A load that lands mid-gesture starts hidden, like the rest.
          showFigures(!drawingRef.current)
          disposers.push(() => {
            if (figuresFnRef.current === showFigures) figuresFnRef.current = null
            overlayFnRef.current = null
            figTokenRef.current++
            clearGroup(markerGroup)
            clearGroup(waterGroup)
            clearGroup(dimsGroup)
            clearGroup(accessGroup)
            clearGroup(figGroup)
            clearGroup(refGroup)
          })

          // ── Pick mode: a plain click (no orbit drag) on the mesh reports
          // the hit as raw-box fractions — floor-plan-style placement. ──
          canvasRef.current = renderer.domElement
          renderer.domElement.style.cursor = pickingRef.current ? 'crosshair' : ''
          let downAt: [number, number] | null = null
          const onDown = (e: PointerEvent) => { downAt = [e.clientX, e.clientY] }
          const onUp = (e: PointerEvent) => {
            const start = downAt
            downAt = null
            if (!start || !pickingRef.current || (!onPickPointRef.current && !waterPickRef.current && !groundPickRef.current)) return
            if (Math.hypot(e.clientX - start[0], e.clientY - start[1]) > 5) return
            const rect = renderer.domElement.getBoundingClientRect()
            const ndc = new THREE.Vector2(
              ((e.clientX - rect.left) / rect.width) * 2 - 1,
              -(((e.clientY - rect.top) / rect.height) * 2 - 1))
            const ray = new THREE.Raycaster()
            ray.setFromCamera(ndc, camera)
            if (groundPickRef.current) {
              const pick = groundPickRef.current
              const metre = figureHeightRef.current / FIGURE_HEIGHT_M
              if (!(metre > 0)) return
              // The ground is the UPRIGHT model's (T-U4: the drag may have turned it, the access grid with it):
              // the ray goes into the upright frame, `upright · turned⁻¹`, and the box is measured there.
              const turned = object.matrixWorld.clone()
              upright(() => {
                ray.ray.applyMatrix4(object.matrixWorld.clone().multiply(turned.invert()))
                const box = new THREE.Box3().setFromObject(object)
                const centre = box.getCenter(new THREE.Vector3())
                const groundY = box.min.y - (groundOffsetRef.current || 0) * metre
                const point = ray.ray.intersectPlane(new THREE.Plane(new THREE.Vector3(0, 1, 0), -groundY), new THREE.Vector3())
                if (point) pick(accessLocalPoint([point.x, point.y, point.z], {
                  centreX: centre.x, centreZ: centre.z, groundY, unitsPerMetre: metre }))
              })
              return
            }
            const hit = ray.intersectObject(object, true)[0]
            if (!hit) return
            const local = pivot.worldToLocal(hit.point.clone())
            if (waterPickRef.current) {
              const fixed = local.clone().applyQuaternion(orient.quaternion)
              waterPickRef.current([fixed.x, fixed.y, fixed.z])
              return
            }
            const frac = (v: number, lo: number, span: number) =>
              Math.round(Math.min(Math.max((v - lo) / (span || 1), 0), 1) * 1000) / 1000
            onPickPointRef.current?.([
              frac(local.x, rawBox.min.x, rawSize.x),
              frac(local.y, rawBox.min.y, rawSize.y),
              frac(local.z, rawBox.min.z, rawSize.z),
            ])
          }
          renderer.domElement.addEventListener('pointerdown', onDown)
          renderer.domElement.addEventListener('pointerup', onUp)
          disposers.push(() => {
            renderer.domElement.removeEventListener('pointerdown', onDown)
            renderer.domElement.removeEventListener('pointerup', onUp)
            if (canvasRef.current === renderer.domElement) canvasRef.current = null
          })
        }

        // ── Companions (Ruling A48a) ── Extra GLBs under the pivot, in the model's own frame: loaded one by one
        // after the model (a slow one never holds the model back), restyled, switched on and off live.
        const companionObjs = new Map<string, { url: string; style: ViewerCompanion['style']; obj: Object3D | null }>()
        const disposeCompanion = (obj: Object3D) => {
          obj.removeFromParent()
          obj.traverse((o: Object3D) => {
            const mesh = o as Mesh
            mesh.geometry?.dispose?.()
            const m = mesh.material as Material | Material[] | undefined
            if (Array.isArray(m)) m.forEach((x) => x.dispose?.())
            else m?.dispose?.()
          })
        }
        const styleCompanion = (obj: Object3D, style: ViewerCompanion['style']) => {
          obj.traverse((o: Object3D) => {
            const mesh = o as Mesh
            if (!mesh.isMesh) return
            const old = mesh.material as Material | Material[]
            mesh.material = style === 'ghost'
              ? new THREE.MeshStandardMaterial({ color: 0x9fb3cc, roughness: 0.9, metalness: 0, transparent: true,
                opacity: 0.3, depthWrite: false, side: THREE.DoubleSide })
              : new THREE.MeshBasicMaterial({ color: 0xf85149, side: THREE.DoubleSide, polygonOffset: true,
                polygonOffsetFactor: -2, polygonOffsetUnits: -4 })
            mesh.renderOrder = style === 'ghost' ? 2 : 1
            if (Array.isArray(old)) old.forEach((m) => m.dispose?.())
            else old?.dispose?.()
          })
        }
        const applyCompanions = () => {
          const list = companionsRef.current || []
          for (const [key, entry] of [...companionObjs]) {
            const want = list.find((c) => c.key === key)
            if (!want || want.url !== entry.url || want.style !== entry.style) {
              if (entry.obj) disposeCompanion(entry.obj)
              companionObjs.delete(key)
            }
          }
          for (const c of list) {
            const entry = companionObjs.get(c.key)
            if (entry) {
              if (entry.obj) entry.obj.visible = c.visible
              continue
            }
            const fresh: { url: string; style: ViewerCompanion['style']; obj: Object3D | null } =
              { url: c.url, style: c.style, obj: null }
            companionObjs.set(c.key, fresh)
            onCompanionStateRef.current?.(c.key, 'loading')
            ;(async () => {
              const { createGLTFLoader } = await import('../../lib/gltfLoader')
              const gltf = await createGLTFLoader().loadAsync(c.url)
              if (disposed || companionObjs.get(c.key) !== fresh) {
                disposeCompanion(gltf.scene)
                return
              }
              styleCompanion(gltf.scene, c.style)
              fresh.obj = gltf.scene
              gltf.scene.visible = !!(companionsRef.current || []).find((x) => x.key === c.key)?.visible
              pivot.add(gltf.scene)
              deformCompanion(c.key, gltf.scene)
              onCompanionStateRef.current?.(c.key, 'ready')
            })().catch(() => {
              if (!disposed && companionObjs.get(c.key) === fresh) onCompanionStateRef.current?.(c.key, 'error')
            })
          }
        }
        companionFnRef.current = applyCompanions
        disposers.push(() => {
          if (companionFnRef.current === applyCompanions) companionFnRef.current = null
          for (const entry of companionObjs.values()) if (entry.obj) disposeCompanion(entry.obj)
          companionObjs.clear()
        })

        // ── Live deformation (Ruling A48c) ── `deform` rewrites the positions of the model and of every companion
        // with `follow`, in the model's own frame, always from the positions as loaded (kept per geometry the first
        // time); `faceBits` narrows a companion to the faces whose byte has the bit. Nothing is reloaded.
        const deformRoot = (root: Object3D, map: ViewerDeform['map'] | null) => {
          root.updateMatrixWorld(true)
          const rootInv = root.matrixWorld.clone().invert()
          const toRoot = new THREE.Matrix4()
          const toLocal = new THREE.Matrix4()
          const v = new THREE.Vector3()
          root.traverse((o: Object3D) => {
            const mesh = o as Mesh
            if (!mesh.isMesh || (o as { isSkinnedMesh?: boolean }).isSkinnedMesh) return
            const geo = mesh.geometry
            const pos = geo.getAttribute('position')
            if (!pos) return
            const ud = geo.userData as { deformBase?: Float32Array }
            if (!map && !ud.deformBase) return
            if (!ud.deformBase) {
              const base = new Float32Array(pos.count * 3)
              for (let i = 0; i < pos.count; i++) {
                base[3 * i] = pos.getX(i); base[3 * i + 1] = pos.getY(i); base[3 * i + 2] = pos.getZ(i)
              }
              ud.deformBase = base
            }
            const work = Float32Array.from(ud.deformBase)
            if (map) {
              toRoot.multiplyMatrices(rootInv, mesh.matrixWorld)
              const identity = toRoot.equals(new THREE.Matrix4())
              if (!identity) {
                for (let i = 0; i < pos.count; i++) {
                  v.set(work[3 * i], work[3 * i + 1], work[3 * i + 2]).applyMatrix4(toRoot)
                  work[3 * i] = v.x; work[3 * i + 1] = v.y; work[3 * i + 2] = v.z
                }
              }
              map(work)
              if (!identity) {
                toLocal.copy(toRoot).invert()
                for (let i = 0; i < pos.count; i++) {
                  v.set(work[3 * i], work[3 * i + 1], work[3 * i + 2]).applyMatrix4(toLocal)
                  work[3 * i] = v.x; work[3 * i + 1] = v.y; work[3 * i + 2] = v.z
                }
              }
            }
            for (let i = 0; i < pos.count; i++) pos.setXYZ(i, work[3 * i], work[3 * i + 1], work[3 * i + 2])
            pos.needsUpdate = true
            geo.computeBoundingSphere()
            geo.computeBoundingBox()
          })
        }
        const maskFaces = (root: Object3D, fb: ViewerCompanion['faceBits']) => {
          root.traverse((o: Object3D) => {
            const mesh = o as Mesh
            if (!mesh.isMesh) return
            const geo = mesh.geometry
            const ud = geo.userData as { maskBase?: Uint32Array }
            if (!fb && !ud.maskBase) return
            if (!ud.maskBase) {
              const pos = geo.getAttribute('position')
              ud.maskBase = geo.index ? Uint32Array.from(geo.index.array as ArrayLike<number>)
                : Uint32Array.from({ length: pos ? pos.count : 0 }, (_, i) => i)
            }
            const base = ud.maskBase
            const faces = Math.floor(base.length / 3)
            if (!fb || fb.bit < 0 || fb.bits.length !== faces) {
              // No mask, or one that does not describe this geometry: every face, as loaded.
              geo.setIndex(new THREE.BufferAttribute(Uint32Array.from(base), 1))
              return
            }
            const keep: number[] = []
            for (let f = 0; f < faces; f++) {
              if ((fb.bits[f] >> fb.bit) & 1) keep.push(base[3 * f], base[3 * f + 1], base[3 * f + 2])
            }
            geo.setIndex(new THREE.BufferAttribute(Uint32Array.from(keep), 1))
          })
        }
        const deformCompanion = (key: string, obj: Object3D) => {
          const c = (companionsRef.current || []).find((x) => x.key === key)
          deformRoot(obj, c?.follow ? deformRef.current?.map ?? null : null)
          maskFaces(obj, c?.faceBits ?? null)
        }
        const applyDeform = () => {
          deformRoot(object, deformRef.current?.map ?? null)
          for (const [key, entry] of companionObjs) if (entry.obj) deformCompanion(key, entry.obj)
          // The deformed model's extent in its own frame (min x, max x, min z, max z) as plain numbers on the mount:
          // what a UI check compares with the rule (`scripts/check_figure_ui.mjs`'s harness, Ruling A48c).
          const box = new THREE.Box3()
          object.updateMatrixWorld(true)
          const rootInv = object.matrixWorld.clone().invert()
          object.traverse((o: Object3D) => {
            const mesh = o as Mesh
            if (!mesh.isMesh || !mesh.geometry.boundingBox) return
            box.union(mesh.geometry.boundingBox.clone().applyMatrix4(
              new THREE.Matrix4().multiplyMatrices(rootInv, mesh.matrixWorld)))
          })
          mount.dataset.modelBox = [box.min.x, box.max.x, box.min.z, box.max.z].map((v) => v.toFixed(5)).join(',')
          mount.dataset.deform = deformRef.current?.key || ''
        }
        deformFnRef.current = applyDeform
        disposers.push(() => { if (deformFnRef.current === applyDeform) deformFnRef.current = null })
        applyCompanions()
        object.traverse((o: Object3D) => { const m = o as Mesh; if (m.isMesh) m.geometry.computeBoundingBox() })
        applyDeform()

        setLoading(false)

        // ── The model turn (T-U4, `lib/modelTurn.ts`) ── A plain drag turns and tilts the MODEL about its centre —
        // the focused part when the viewer focuses one (the Hairstyles preview: the head) — so simulated hair and
        // extension bones feel it like any root motion; Shift + drag moves the view, the wheel zooms, a double-click
        // (or Reset pose) stands it upright again. Off while the front view holds the model straight on.
        previewRoot.updateMatrixWorld(true)
        const focusAt = focusRef.current
        const turnPivot = previewRoot.worldToLocal(focusAt
          ? object.localToWorld(new THREE.Vector3(focusAt.center[0], focusAt.center[1], focusAt.center[2]))
          : new THREE.Box3().setFromObject(object).getCenter(new THREE.Vector3()))
        const turnAllowed = () => !frontalRef.current
        const turnControl = attachModelTurn(mount, {
          isEnabled: turnAllowed,
          onChange: (pose) => {
            const turn = Math.round((wrapAngle(pose.yaw) * 180) / Math.PI)
            const tilt = Math.round((pose.pitch * 180) / Math.PI)
            setTurnPose(prev => (prev.turn === turn && prev.tilt === tilt ? prev : { turn, tilt }))
          },
        })
        modelTurn = turnControl
        // Ruling A48c: where the caller asks for it, the double-click frames the view again too (zoom, pan).
        const onDoubleView = (e: MouseEvent) => {
          if (!resetViewOnDblRef.current || e.shiftKey) return
          // The damped pan / turn of the last drag would keep moving the camera after the reset: spend it first.
          const damping = controls.enableDamping
          controls.enableDamping = false
          controls.update()
          controls.enableDamping = damping
          refitFnRef.current?.()
        }
        mount.addEventListener('dblclick', onDoubleView)
        disposers.push(() => mount.removeEventListener('dblclick', onDoubleView))
        const resetTurn = () => turnControl.reset()
        turnResetRef.current = resetTurn
        disposers.push(() => {
          turnControl.dispose()
          if (modelTurn === turnControl) modelTurn = null
          if (turnResetRef.current === resetTurn) turnResetRef.current = null
        })
        // The motion buttons: the kind playing (or easing out), its clock and amplitude (`previewMotionAmp`).
        let motionKind: PreviewMotionKind | null = null
        let motionT = 0
        let motionAmp = 0
        /** The root motion of this frame: T(pivot + offset) · Ry(drag yaw + yaw) · Rx(drag pitch + pitch) · T(−pivot)
         *  (`poseMatrix`), the motion buttons' part only in the Hairstyles preview. */
        const applyTurn = (dt: number) => {
          const wanted = turnModeRef.current ? strandMotionRef.current : null
          if (wanted && wanted !== motionKind) {
            motionKind = wanted
            motionT = 0
            if (wanted === 'turn') motionAmp = 1   // the turn eases itself in from rest
          }
          motionAmp = previewMotionAmp(motionAmp, wanted ? 1 : 0, dt)
          if (motionKind) motionT += dt
          if (wanted === 'turn' && motionT >= TURN_S) {
            strandMotionRef.current = null
            setStrandMotion(null)
          }
          if (!wanted && motionAmp < 1e-4) { motionKind = null; motionAmp = 0 }
          const pose = motionKind ? previewRootPose(motionKind, motionT, motionAmp)
            : { yaw: 0, pitch: 0, offset: [0, 0, 0] as [number, number, number] }
          if (!turnAllowed() && !isUpright(turnControl.pose)) turnControl.snapUpright()
          turnControl.tick(dt)
          const drag = turnControl.pose
          turnRoot.matrix.fromArray(poseMatrix({ yaw: drag.yaw + pose.yaw, pitch: drag.pitch + pose.pitch },
            [turnPivot.x, turnPivot.y, turnPivot.z], [pose.offset[0], pose.offset[1], pose.offset[2]]))
          turnRoot.matrixWorldNeedsUpdate = true
          followTurn.matrix.copy(turnRoot.matrix)
          followTurn.matrixWorldNeedsUpdate = true
        }
        // The strands per frame: (re)bind a new record, on/off, the live Stiffness, the step, the status line.
        let statusClock = 0
        let shownStatus = ''
        const tickStrands = (dt: number) => {
          const given = strandHairRef.current
          const record = given?.record ?? null
          const paused = !!meshAdjustRef.current?.map || !!meshAdjustRef.current?.cut
          // A new record binds to the mesh's own (unmapped) positions: never while a placement map is shown.
          if (record !== strandRecord && !(record && paused)) {
            strandOn(false)
            strand?.dispose()
            strandRecord = record
            strand = record ? createStrandHair(THREE, object, record) : null
            strandStiffness = NaN
          }
          if (strand && given && given.stiffness !== strandStiffness) {
            strandStiffness = given.stiffness
            strand.setStiffness(strandStiffness)
          }
          if (strand && !paused && !strand.enabled) {
            meshAdjustFnRef.current?.()   // the template's own positions back before the strands take over
            strandOn(true)
          }
          if (strand?.enabled) strand.update(dt)
          statusClock += dt
          if (statusClock < 0.25 && shownStatus) return
          statusClock = 0
          let next: { state: 'off' | 'running' | 'refused' | 'paused'; cards?: number; tipMm?: number }
          if (!strandRecord) next = { state: 'off' }
          else if (!strand) next = { state: 'refused' }
          else if (!strand.enabled) next = { state: 'paused' }
          else {
            // The tips' largest distance from where they rest — where gravity holds them on the turned and tilted
            // figure (`sim.hang`, T-U3; 0 once they have settled, at any tilt).
            const cards = strandRecord.cards
            const X = strand.sim.X, T = strand.sim.hang, rows = strand.sim.n / cards
            let tip = 0
            for (let k = 0; k < cards; k++) {
              const q = 3 * (k * rows + rows - 1)
              tip = Math.max(tip, Math.hypot(X[q] - T[q], X[q + 1] - T[q + 1], X[q + 2] - T[q + 2]))
            }
            next = { state: 'running', cards, tipMm: Math.round(tip * 1000) }
          }
          const key = JSON.stringify(next)
          if (key !== shownStatus) {
            shownStatus = key
            setStrandStatus(next)
          }
        }

        let raf: number | null = null
        let renderVisible = false
        let renderWidth = width
        let renderHeight = heightRef.current
        const animate = () => {
          raf = null
          if (disposed || !renderVisible) return
          const realDelta = clock.getDelta()
          if (embeddedTakes && mixer) {
            const control = takeRef.current
            if (activeTake !== control.take) {
              embeddedAction?.stop()
              const clip = embedded.find(candidate => candidate.name === control.take)
              embeddedAction = clip ? mixer.clipAction(clip) : null
              activeTake = control.take
              embeddedFinished = false
              embeddedAction?.reset().play()
            }
            if (embeddedAction) {
              if (embeddedFinished && control.playing) {
                embeddedAction.reset().play()
                embeddedFinished = false
              }
              const loop = control.loops?.[activeTake]?.loop !== false
              embeddedAction.setLoop(loop ? THREE.LoopRepeat : THREE.LoopOnce, loop ? Infinity : 1)
              embeddedAction.clampWhenFinished = !loop
            }
            mixer.update(control.playing ? realDelta * control.speed : 0)
          } else if (mixer) mixer.update(realDelta)
          // Seated with the fitted shoes: the heels come up to the floor grid
          // through the knee, after the mixer's pose, before the extension
          // motion (P3b, `Figure.update` does the same in the world).
          if (clipGroup === 'seat' && shod && floorWorldY !== null) seatFootLift(THREE, object, shod, floorWorldY)
          if (secondaryRev !== motionRef.current?.rev || secondaryEnabled !== secondaryOnRef.current) {
            secondaryEnabled = secondaryOnRef.current
            secondaryRev = motionRef.current?.rev
            secondary?.configure(secondaryEnabled ? motionRef.current : undefined)
            if (!secondaryEnabled) secondary?.reset()
          }
          applyTurn(Math.min(realDelta, 0.1))
          previewRoot.updateMatrixWorld(true)
          if (extensionShown !== extensionPushRef.current) {
            extensionShown = extensionPushRef.current
            secondary?.setCollision(extensionShown)
          }
          secondary?.update(realDelta)
          object.updateMatrixWorld(true)
          // The strands after the pose of the frame is final (the client: after the mixer and the matrices).
          if (turnModeRef.current || strand) tickStrands(realDelta)
          if (collisionShown !== collisionRef.current) {
            collisionOverlay?.dispose()
            collisionShown = collisionRef.current
            collisionOverlay = createCollisionOverlay(THREE, object, collisionShown)
            if (collisionOverlay) scene.add(collisionOverlay.group)
          }
          collisionOverlay?.update()
          const bonesWanted = bonesOnRef.current && motionRef.current ? motionRef.current.rev : null
          if (bonesWanted !== bonesShown) {
            boneOverlay?.dispose()
            bonesShown = bonesWanted
            boneOverlay = bonesWanted !== null ? createExtensionGroupOverlay(THREE, object, motionRef.current) : null
            if (boneOverlay) scene.add(boneOverlay.group)
            setBonesLegend(boneOverlay ? boneOverlay.groups : [])
          }
          boneOverlay?.update()
          bonesClock += realDelta
          if (bonesClock >= 0.25) {
            bonesClock = 0
            const read = boneOverlay ? boneOverlay.swingDeg() : null
            if (read !== bonesRead) {
              bonesRead = read
              setBonesSwing(read)
            }
          }
          if (garmentShown !== garmentPushRef.current) {
            garmentCollision?.dispose()
            garmentShown = garmentPushRef.current
            garmentCollision = createGarmentCollision(THREE, object, garmentShown)
            if (strand?.enabled) garmentCollision?.excludeMesh(strand.mesh, true)
            alphaShown = undefined
          }
          const cutoff = alphaCutoffRef.current
          if (typeof cutoff === 'number' && cutoff !== alphaShown) {
            applyAlphaCutoff(object, cutoff)
            alphaShown = cutoff
          }
          controls.update()
          renderer.render(scene, camera)
          raf = requestAnimationFrame(animate)
        }

        disposers.push(() => {
          renderVisible = false
          clock.stop()
          if (raf !== null) cancelAnimationFrame(raf)
        })
        const onResize = () => {
          const w = mount.clientWidth
          if (disposed || document.hidden || !w || !mount.clientHeight) {
            renderVisible = false
            clock.stop()
            if (raf !== null) { cancelAnimationFrame(raf); raf = null }
            return
          }
          const h = heightRef.current
          if (w !== renderWidth || h !== renderHeight) {
            renderWidth = w
            renderHeight = h
            camera.aspect = w / h
            camera.updateProjectionMatrix()
            renderer.setSize(w, h)
          }
          if (!renderVisible) {
            renderVisible = true
            // Hidden time is not animation/physics time. Keep object and camera.
            clock.start()
            raf = requestAnimationFrame(animate)
          }
        }
        // A hidden mobile editor keeps this viewer mounted, but no RAF or scene
        // updates run until its stage has a visible size again.
        const resizeObserver = new ResizeObserver(onResize)
        resizeObserver.observe(mount)
        disposers.push(() => resizeObserver.disconnect())
        document.addEventListener('visibilitychange', onResize)
        disposers.push(() => document.removeEventListener('visibilitychange', onResize))
        onResize()
      } catch (e) {
        cleanup?.()  // dispose the context if the renderer was already created
        if (!disposed) {
          setError((e as Error).message)
          setLoading(false)
        }
      }
    })()

    return () => {
      disposed = true
      cleanup?.()
    }
  }, [url, format, clipUrl, textureUrl, embeddedTakes, clipGroup, footPoseKey])

  const turned = turnPose.turn !== 0 || turnPose.tilt !== 0
  return (
    <div className={sideToolbar ? 'ga-model3d-preview' : undefined}>
      {embeddedTakes && takes.length > 0 ? (
        <div className="ga-row">
          <label>{t('Embedded take')} <select value={take} onChange={event => setTake(event.target.value)}>
            {takes.map(name => <option key={name} value={name}>{name}</option>)}
          </select></label>
          <button type="button" onClick={() => setTakePlaying(value => !value)}>{t(takePlaying ? 'Pause' : 'Play')}</button>
          <label>{t('Playback speed')} <select value={takeSpeed} onChange={event => setTakeSpeed(Number(event.target.value))}>
            {[0.25, 0.5, 1, 1.5, 2].map(speed => <option key={speed} value={speed}>{speed}×</option>)}
          </select></label>
        </div>
      ) : null}
      <div className={sideToolbar ? 'ga-model3d-canvas' : undefined}>
      <div style={{ position: 'relative' }}>
      <div
        ref={mountRef}
        style={{
          width: '100%',
          height,
          borderRadius: 8,
          border: '1px solid var(--border, #30363d)',
          background: 'rgba(255, 255, 255, 0.04)',
          overflow: 'hidden',
        }}
      />
      {meshStats && !loading && !error ? (
        <span
          title={t('Triangles / vertices of the loaded mesh — dial the face count in the generate dialog.')}
          style={{
            position: 'absolute', left: 6, bottom: 6,
            fontSize: '0.72em', opacity: 0.75, pointerEvents: 'none',
            background: 'rgba(13,17,23,0.55)', color: '#e6edf3',
            padding: '1px 6px', borderRadius: 4,
          }}
        >
          {meshStats.tris.toLocaleString()} △ · {meshStats.verts.toLocaleString()} ●
        </span>
      ) : null}
      {/* THE POLYGON TOOL — an SVG over the canvas, the map's gestures
          (`MapTab.addDraftPoint`): a click drops a point, a click back ON the
          first point closes the ring, Escape cancels. The closing click is
          announced before it happens — the first point swells and the closing
          segment is drawn — so the ring is never closed by surprise. It only
          ever REPORTS; the panel posts, the server splits. */}
      {drawing && !loading && !error ? (
        layoutOk ? (
          <svg
            width="100%" height={height}
            style={{ position: 'absolute', inset: 0,
              cursor: closesHere ? 'pointer' : 'crosshair' }}
            onClick={addPolyPoint}
            onMouseMove={(e) => {
              if (poly.length) setPolyCursor(atOverlay(e))
            }}
          >
            {poly.length ? (
              <polyline
                points={[...poly,
                  // The band runs to the cursor — or, when the cursor has
                  // snapped, to the first point: that IS the closing segment.
                  ...(closesHere ? [poly[0]] : polyCursor ? [polyCursor] : [])]
                  .map(([x, y]) => `${x},${y}`).join(' ')}
                fill={closesHere ? 'rgba(63,185,80,0.16)' : 'rgba(88,166,255,0.14)'}
                stroke={closesHere ? '#3fb950' : '#58a6ff'} strokeWidth={1.5}
              />
            ) : null}
            {poly.map(([x, y], i) => (
              <circle key={i} cx={x} cy={y}
                r={i === 0 && closesHere ? 6 : 3}
                fill={i === 0 && closesHere ? '#3fb950' : '#58a6ff'} />
            ))}
          </svg>
        ) : (
          <div
            style={{
              position: 'absolute', inset: 0, display: 'flex',
              alignItems: 'center', justifyContent: 'center', padding: 12,
              textAlign: 'center', fontSize: '0.85em',
              background: 'rgba(13,17,23,0.72)', color: '#e6edf3',
            }}
          >
            {t('Model and area layout differ — run “Detect areas” first.')}
          </div>
        )
      ) : null}
      <FreshnessCorner freshness={freshness} />
      {!loading && !error ? <BuiltAtCaption at={builtAt} /> : null}
      {/* THE VIEW CONTROLS — one column at the top right, so no button has to
          know how many of its neighbours happen to be shown. */}
      {!loading && !error && (motion || onFrontalChange || keepCamera
        || (leafBbox && hasLeaf) || collision?.capsules?.length || extensionNote) ? (
        <div className="ga-viewer-toggles" style={{
          position: 'absolute', right: 6, top: 6, display: 'flex',
          flexDirection: 'column', alignItems: 'flex-end', gap: 4,
        }}>
          {motion ? (
            <button type="button" className="ga-btn ga-btn-sm"
              aria-pressed={secondaryOn} onClick={() => setSecondaryOn(on => !on)}>
              {t('Secondary motion')}
            </button>
          ) : null}
          {hasExtensionBones ? (
            <button type="button" className="ga-btn ga-btn-sm"
              aria-pressed={bonesOn} onClick={() => setBonesOn(on => !on)}
              title={t('Show the surface each extension group moves as a grid, faint where it moves less — drag the figure to tilt it and watch it hang')}>
              {t('Extension bones')}
            </button>
          ) : null}
          {hasExtensionBones && bonesOn && bonesLegend.length ? (
            <div className="ga-ext-legend" title={t('Grid colour per extension group')} style={{
              display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 2, padding: '2px 6px',
              borderRadius: 4, background: 'rgba(13,17,23,0.72)', color: '#e6edf3', fontSize: 11,
            }}>
              {bonesLegend.map((g) => (
                <span key={g.id} style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                  {g.id}
                  <span aria-hidden="true" style={{ width: 10, height: 10, borderRadius: 2,
                    border: `2px solid ${groupColorCss(g.color)}`, background: `${groupColorCss(g.color)}55` }} />
                </span>
              ))}
            </div>
          ) : null}
          {collision?.capsules?.length ? (
            <button type="button" className="ga-btn ga-btn-sm"
              aria-pressed={collisionShownOn} onClick={() => setCollisionOn(on => !on)}
              title={t('Show collision capsules on the playing figure')}>
              {t('Collision capsules')}
            </button>
          ) : null}
          {collision?.capsules?.length && garmentPushable ? (
            <button type="button" className="ga-btn ga-btn-sm"
              aria-pressed={garmentPushOn} onClick={() => setGarmentPushOn(on => !on)}
              title={t('Push garments out of the collision capsules (off = as skinned)')}>
              {t('Garment collision')}
            </button>
          ) : null}
          {motion && Object.keys(motion.groups ?? {}).length > 0 && collision?.capsules?.length ? (
            <button type="button" className="ga-btn ga-btn-sm"
              aria-pressed={extensionPushOn} onClick={() => setExtensionPushOn(on => !on)}
              title={t('Keep extension-bone tips outside the collision capsules (off = free swing)')}>
              {t('Extension collision')}
            </button>
          ) : null}
          {/* The front view is a MODE the owner holds (§ B1): pressed, the
              model stands straight on and the orbit is locked — the state a
              ring may be drawn in. */}
          {onFrontalChange ? (
            <button
              type="button" className="ga-btn ga-btn-sm"
              style={{ opacity: 0.85,
                ...(frontal ? { background: '#238636', borderColor: '#2ea043',
                  color: '#fff' } : null) }}
              aria-pressed={frontal}
              onClick={() => onFrontalChange(!frontal)}
              title={frontal
                ? t('Front view is on: the model stands straight on and cannot be turned — zoom and pan still work. Click to orbit freely again.')
                : t('Look at the model straight on and lock the turning — the view a surface is drawn in.')}
            >
              {t('Front view')}
            </button>
          ) : null}
          {/* A kept camera needs a way back — so the reset is offered wherever
              the camera survives a model switch, mode or no mode. */}
          {keepCamera ? (
            <button
              type="button" className="ga-btn ga-btn-sm"
              style={{ opacity: 0.85 }}
              onClick={() => refitFnRef.current?.()}
              title={t('Frame the whole model again, in the view that is switched on right now.')}
            >
              {t('Reset view')}
            </button>
          ) : null}
          {/* The door leaf's test swing (spec § 6): only with a leaf node in
              the model AND a leaf_bbox from the server — both, or there is
              nothing to turn or nowhere to turn it about. */}
          {leafBbox && hasLeaf ? (
            <button
              type="button" className="ga-btn ga-btn-sm"
              style={{ opacity: 0.85 }}
              aria-pressed={leafOpen}
              onClick={() => {
                const next = !leafOpen
                setLeafOpen(next)
                swingFnRef.current?.(next)
              }}
              title={t('Swing the door leaf 85° open about its hinge edge (left hinge) to check the cut — click again to shut it.')}
            >
              {leafOpen ? t('Shut leaf') : t('Test swing')}
            </button>
          ) : null}
          {extensionNote}
        </div>
      ) : null}
      {loading || error ? (
        <div
          style={{
            position: 'absolute',
            inset: 0,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            pointerEvents: 'none',
            fontSize: '0.85em',
            opacity: 0.75,
            padding: 8,
            textAlign: 'center',
          }}
        >
          {error ? `${t('Error')}: ${error}` : t('Loading…')}
        </div>
      ) : null}
      </div>
      {!loading && !error ? <ModelTurnHint subject={subject} locked={frontal} turned={turned} resetsView={resetViewOnDoubleClick}
        onReset={() => turnResetRef.current?.()} /> : null}
      {!loading && !error && bonesOn && hasExtensionBones && bonesSwing !== null ? (
        <div className="ga-hint" style={{ fontSize: 11 }}>
          {t('Extension bones: up to {n}° from their built pose · no jobs').replace('{n}', String(bonesSwing))}
        </div>
      ) : null}
      </div>
      {sideToolbar ? <aside className="ga-model3d-toolbar">
        {statusPanel}
        {turnMode ? (
          <div className="ga-fieldset ga-model3d-group">
            <span className="ga-fieldset-title" style={{ margin: 0, fontSize: 11 }}>{t('Motion preview')}</span>
            <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
              {([['sway', t('Sway'), t('Sways the figure ±15° about the head — preview only, no jobs')],
                ['walk', t('Walk'), t('Walks the figure 25 cm back and forth — preview only, no jobs')],
                ['turn', t('Turn'), t('Turns the figure 180° and back — preview only, no jobs')],
              ] as const).map(([kind, label, title]) => (
                <button key={kind} type="button" className={`ga-btn ga-btn-sm${strandMotion === kind ? ' ga-btn-primary' : ''}`}
                  aria-pressed={strandMotion === kind} title={title} disabled={loading || !!error}
                  onClick={() => setStrandMotion(kind)}>{label}</button>
              ))}
              <button type="button" className="ga-btn ga-btn-sm" disabled={loading || !!error || !strandMotion}
                title={t('Eases the figure back to rest — the hair settles')}
                onClick={() => setStrandMotion(null)}>{t('Stop')}</button>
            </div>
            <span className="ga-hint" style={{ fontSize: 10 }}>
              {strandStatus.state === 'running'
                ? t('Every strand swings · {n} strands · tips {mm} mm from rest')
                  .replace('{n}', String(strandStatus.cards ?? 0)).replace('{mm}', String(strandStatus.tipMm ?? 0))
                : strandStatus.state === 'refused'
                  ? t('The preview model does not carry this record’s strand binding — the hair stays still.')
                  : strandStatus.state === 'paused'
                    ? t('The strands rest while the placement preview is shown.')
                    : strandNote || t('The hair stays still.')}
            </span>
            <span className="ga-hint" style={{ fontSize: 10 }}>
              {t('Turned {turn}° · tilted {tilt}° — the hair falls with the figure · no jobs')
                .replace('{turn}', String(turnPose.turn)).replace('{tilt}', String(turnPose.tilt))}
            </span>
          </div>
        ) : null}
        {motionToolbar}
      </aside> : null}
    </div>
  )
}
