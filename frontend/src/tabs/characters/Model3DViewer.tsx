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
import type { MouseEvent as ReactMouseEvent } from 'react'
import type { AnimationClip, Material, Mesh, MeshStandardMaterial, Object3D,
  Vector3 } from 'three'
import { FIGURE_HEIGHT_M, anchorFigureBind, applySlotMaterials,
  disposeSlotMaterials, figureRootY } from '@anima/scene-render'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet } from '../../lib/api'
import type { SceneModelSpec } from '../world/worldTypes'
import { buildMeasureAids, disposeAids, referenceFigure,
  type MeasureKey } from '../world/measureKit'
import { alignMeshLayout, meshLayoutOf, pointInPolygon,
  polygonArea } from '../props/faceSelect'
import { areaKindOf } from '../props/propTypes'
import type { AreaOutline, MeshLayoutEntry,
  PropSlotValues } from '../props/propTypes'

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

/** How far apart the two presses of a DOUBLE-click may land, in pixels. The
 *  SVG has no double-click of its own: both presses arrive as ordinary clicks
 *  and each drops a point, so by the time `dblclick` fires the ring carries
 *  one point too many. A trailing point this close to its predecessor IS the
 *  second press and goes again (the map's rule, `MapTab.DBLCLICK_MERGE_PX`). */
const DBLCLICK_MERGE_PX = 8

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
          const { GLTFLoader } = await import('three/examples/jsm/loaders/GLTFLoader.js')
          obj = (await new GLTFLoader().loadAsync('/play/test-figure/model')).scene
        }
        // Neutral clay figure — placement and scale are judged, not a look.
        const THREE = await import('three')
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
let _clipsPromise: Promise<Array<{ kind: string; set: string; url: string }>> | null = null
const _clipCache = new Map<string, Promise<{ clip: AnimationClip; restObj: Object3D } | null>>()
const loadClip = (kind: string) => {
  if (!_clipsPromise) {
    _clipsPromise = apiGet<{ clips?: Array<{ kind: string; set: string; url: string }> }>(
      '/assets/animation-clips')
      .then((d) => d.clips || [])
      .catch(() => [])
  }
  let cached = _clipCache.get(kind)
  if (!cached) {
    cached = (async () => {
      const clips = await _clipsPromise!
      // Prefer a set-less clip, then female, then anything of the kind —
      // same pick as the floor-plan preview.
      const of = clips.filter((c) => c.kind === kind)
      const pick = of.find((c) => !c.set) || of.find((c) => c.set === 'female') || of[0]
      if (!pick) return null
      try {
        const { FBXLoader } = await import('three/examples/jsm/loaders/FBXLoader.js')
        const clipObj = await new FBXLoader().loadAsync(pick.url)
        const clip = clipObj.animations?.[0]
        if (!clip) return null
        // Play in place — the hips position track is in Mixamo centimetres.
        clip.tracks = clip.tracks.filter(
          (tr) => !(/hips/i.test(tr.name) && tr.name.endsWith('.position')))
        return { clip, restObj: clipObj }
      } catch {
        return null
      }
    })()
    _clipCache.set(kind, cached)
  }
  return cached
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

export function Model3DViewer({ url, format, clipUrl = '', textureUrl = '', height = 320, rotation,
  offsetY = 0, offsetX = 0, offsetZ = 0,
  groundTextureUrl, placement, onBounds, markers, dimsOverlay,
  figureHeight = 0, scaleFigure = false, groundOffsetM = 0,
  picking = false, onPickPoint,
  frontal = false, areaOutlines, slots, meshLayout, drawing = false,
  onPolygonFaces }:
  { url: string; format: string; clipUrl?: string; textureUrl?: string; height?: number;
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
     *  square, textured with this image when given) and places the model on
     *  it — centred, yawed and scaled per `placement`, feet on the ground. */
    groundTextureUrl?: string
    placement?: TilePlacement
    /** Object-local markers (numbered dots) — `at` = fractions of the RAW
     *  model bounding box; `animation` poses the preview figure, `facing`
     *  turns it. Model mode only; refreshed live. */
    markers?: Array<{ at: [number, number, number]
      animation?: string; facing?: number }>
    /** Height of a 1.7 m preview figure in MESH units (the caller derives
     *  it from bbox ÷ dims). > 0 shows a posed test figure at every marker
     *  — a sit marker is only judgeable with someone sitting there. */
    figureHeight?: number
    /** Put the STANDING 1.70 m reference beside the model, on the model's own
     *  ground plane, plus a one-metre ground grid under both (model mode
     *  only, needs `figureHeight` > 0). "Kein Maß ohne Maßstab": a mesh alone
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
    /** THE FRONT VIEW (spec-picture-props.md § 4): the model straight on,
     *  centred, filling the frame — the authoring view of a flat panel, and
     *  the one the polygon tool is drawn on. It is the framing model mode
     *  already opens with; this only makes it a stated MODE, so the viewer
     *  offers "Front view" to get back to it after an orbit. Model mode only.
     */
    frontal?: boolean
    /** Outlines of the prop's key surfaces, in glTF y-up MODEL space (the
     *  server computed them at the split — the client draws, never measures).
     *  One `LineSegments` per area, coloured by KIND out of `AREA_KINDS`, hung
     *  under the loaded model so it rides the orientation fix along. Model
     *  mode only; refreshed live. */
    areaOutlines?: AreaOutline[]
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
    /** The closed polygon's triangles as FLAT indices in R1 order — every
     *  front-facing, unoccluded triangle whose centre projects inside the
     *  ring. An empty array means "nothing was hit", which the panel says out
     *  loud instead of posting. */
    onPolygonFaces?: (faces: number[]) => void }) {
  const { t } = useI18n()
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
  const markersRef = useRef(markers)
  markersRef.current = markers
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
  const overlayFnRef = useRef<(() => void) | null>(null)
  /** Re-frames the model-mode camera (model + scale kit). */
  const refitFnRef = useRef<(() => void) | null>(null)
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  // ── Picture areas: outlines, the assembly preview, the polygon tool ──
  const areaOutlinesRef = useRef(areaOutlines)
  areaOutlinesRef.current = areaOutlines
  const areaFnRef = useRef<(() => void) | null>(null)
  const slotsRef = useRef(slots)
  slotsRef.current = slots
  const slotFnRef = useRef<(() => void) | null>(null)
  const onPolygonFacesRef = useRef(onPolygonFaces)
  onPolygonFacesRef.current = onPolygonFaces
  /** The pick itself — set by the loader, because it needs the live camera.
   *  Takes the ring in CANVAS PIXELS plus the canvas size and answers the flat
   *  R1 triangle indices. */
  const selectFacesRef = useRef<((poly: Array<[number, number]>,
    w: number, h: number) => number[]) | null>(null)
  /** What the LOADED model's R1 layout is — measured once per load, compared
   *  against the server's `meshLayout` before the tool is armed. */
  const [loadedLayout, setLoadedLayout] = useState<MeshLayoutEntry[] | null>(null)
  /** The ring being drawn, in canvas pixels ([] = nothing started). */
  const [poly, setPoly] = useState<Array<[number, number]>>([])
  /** The same ring, read by the double-click handler: `dblclick` arrives as
   *  its own event after both clicks, and reading it off state would race the
   *  render they queued. */
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
  useEffect(() => { slotFnRef.current?.() }, [slots])
  // Disarming the tool drops whatever was half-drawn: a ring that survived
  // into the next arming would send points from the previous camera.
  useEffect(() => {
    if (!drawing) { setPoly([]); setPolyCursor(null) }
  }, [drawing])
  // Escape cancels the running ring (the map's gesture — see PolygonHandles).
  useEffect(() => {
    if (!drawing) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      setPoly([])
      setPolyCursor(null)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [drawing])
  // Switching the front view on re-frames straight away — it is a MODE, not a
  // one-off framing at load.
  useEffect(() => { if (frontal) refitFnRef.current?.() }, [frontal])

  /** Where a pointer event landed inside the overlay, in canvas pixels. */
  const atOverlay = (e: { clientX: number; clientY: number
    currentTarget: { getBoundingClientRect: () => DOMRect } }): [number, number] => {
    const r = e.currentTarget.getBoundingClientRect()
    return [e.clientX - r.left, e.clientY - r.top]
  }

  /** Click = one point of the ring. */
  const addPolyPoint = (e: ReactMouseEvent<SVGSVGElement>) => {
    const at = atOverlay(e)
    setPoly((cur) => (cur.length >= MAX_POLYGON_POINTS ? cur : [...cur, at]))
  }

  /**
   * Double-click closes the ring and hands over the triangles.
   *
   * Both presses already dropped a point (see `DBLCLICK_MERGE_PX`), so the
   * trailing one goes again when it sits on its predecessor. Below three
   * points — or with no enclosed area at all — nothing is reported: an empty
   * selection is a refusal, and a scribble is not a polygon.
   */
  const closePoly = (e: ReactMouseEvent<SVGSVGElement>) => {
    const r = e.currentTarget.getBoundingClientRect()
    const ring = [...polyRef.current]
    if (ring.length > 3) {
      const [ax, ay] = ring[ring.length - 2]
      const [bx, by] = ring[ring.length - 1]
      if (Math.hypot(ax - bx, ay - by) <= DBLCLICK_MERGE_PX) ring.pop()
    }
    setPoly([])
    setPolyCursor(null)
    if (ring.length < 3 || polygonArea(ring) <= 0) return
    const faces = selectFacesRef.current?.(ring, r.width, r.height) || []
    onPolygonFacesRef.current?.(faces)
  }

  // Live overlay refresh (markers moved/added, dims typed, a sink dialled)
  // without reload — a typed number must show up while it is being typed.
  useEffect(() => { overlayFnRef.current?.() },
    [markers, dimsOverlay, figureHeight, scaleFigure, groundOffsetM])
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
    // A new model is a new face order — the polygon tool stays disabled until
    // the fresh one has been measured and matched against the server's.
    setLoadedLayout(null)

    ;(async () => {
      try {
        const THREE = await import('three')
        const { OrbitControls } = await import('three/examples/jsm/controls/OrbitControls.js')

        const mount = mountRef.current
        if (!mount || disposed) return

        const width = mount.clientWidth || 320
        const scene = new THREE.Scene()
        scene.background = null

        const camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 5000)
        const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true })
        renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
        renderer.setSize(width, height)
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

        const ext = (format || url.split('.').pop() || '').toLowerCase()
        let object: Object3D
        let gltfParser: GltfParser | null = null
        if (ext === 'fbx') {
          const { FBXLoader } = await import('three/examples/jsm/loaders/FBXLoader.js')
          object = await new FBXLoader().loadAsync(url)
        } else if (ext === 'glb' || ext === 'gltf' || ext === 'vrm') {
          const { GLTFLoader } = await import('three/examples/jsm/loaders/GLTFLoader.js')
          const gltf = await new GLTFLoader().loadAsync(url)
          object = gltf.scene
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
        // roughness channel of the same map stays active), colours stay true.
        object.traverse((o: Object3D) => {
          const mesh = o as Mesh
          if (!mesh.isMesh) return
          const mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material]
          for (const m of mats) {
            const std = m as MeshStandardMaterial
            if (std.isMeshStandardMaterial && std.metalnessMap) {
              std.metalness = 0
              std.needsUpdate = true
            }
          }
        })

        if (textureUrl) {
          const tex = await new THREE.TextureLoader().loadAsync(textureUrl)
          if (disposed) return
          tex.colorSpace = THREE.SRGBColorSpace
          tex.flipY = false
          tex.wrapS = THREE.RepeatWrapping
          tex.wrapT = THREE.RepeatWrapping
          tex.needsUpdate = true
          object.traverse((o: Object3D) => {
            const mesh = o as Mesh
            if (!mesh.isMesh) return
            const mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material]
            for (const m of mats) {
              const mat = m as MeshStandardMaterial
              mat.map = tex
              // A grey/tinted base colour would multiply into the texture.
              mat.color?.set(0xffffff)
              mat.needsUpdate = true
            }
          })
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
        scene.add(place)
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
        let mixer: InstanceType<typeof THREE.AnimationMixer> | null = null
        if (clipUrl) {
          const { FBXLoader } = await import('three/examples/jsm/loaders/FBXLoader.js')
          const clipObj = await new FBXLoader().loadAsync(clipUrl)
          if (disposed) return
          const clip = clipObj.animations?.[0]
          if (!clip) throw new Error('Clip contains no animation track')

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
          mixer = new THREE.AnimationMixer(object)
          mixer.clipAction(clip).play()
          mixer.update(0)  // apply frame 0 so the framing below fits the pose
          disposers.push(() => mixer?.stopAllAction())
        }
        const clock = new THREE.Clock()
        pivot.updateMatrixWorld(true)

        if (placementRef.current) {
          // ── Stage mode: the location's reference square in WORLD metres,
          // with the model placed by its SCENE SPEC. Everything here is the
          // same square, the same numbers and the same blue edge as the
          // floor-plan preview — the two used to disagree because this stage
          // was a fixed 10 m tile while the preview drew map3d.extent_m.
          const groundMat = new THREE.MeshBasicMaterial({ color: 0x2e3742 })
          if (groundTextureUrl) {
            try {
              const gtex = await new THREE.TextureLoader().loadAsync(groundTextureUrl)
              gtex.colorSpace = THREE.SRGBColorSpace
              groundMat.map = gtex
              groundMat.color.set(0xffffff)
              groundMat.needsUpdate = true
            } catch { /* an untextured tile is fine */ }
            if (disposed) return
          }
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
            camera.position.set(0, 0, dist * 1.6)
            camera.near = dist / 100
            camera.far = dist * 100
            camera.updateProjectionMatrix()
            controls.target.set(0, 0, 0)
            controls.update()
          }
          fitView()
          // Only the kit switch refits — a marker edit or a typed dim must
          // never yank a camera the user has orbited into place.
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
          const markerGroup = new THREE.Group()
          pivot.add(markerGroup)
          const dimsGroup = new THREE.Group()
          scene.add(dimsGroup)
          // Preview figures anchor in WORLD space (they stand upright while
          // the marker point rides the object through the orientation fix).
          const figGroup = new THREE.Group()
          scene.add(figGroup)
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
          // (unoccluded). The flat index is the R1 one: meshes by name,
          // triangles in buffer order, counted straight through.
          const selectFaces = (ring: Array<[number, number]>,
                               vw: number, vh: number): number[] => {
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
                // Facing the camera: the winding normal against the line of
                // sight. A back face of the same panel would double every
                // index and drag the far wall of a box into the selection.
                normal.copy(ab.subVectors(b, a)).cross(ac.subVectors(c, a))
                if (normal.dot(toCam.subVectors(camPos, centre)) <= 0) continue
                const p = centre.clone().project(camera)
                const sx = ((p.x + 1) / 2) * vw
                const sy = ((1 - p.y) / 2) * vh
                if (!pointInPolygon(sx, sy, ring)) continue
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
            clearGroup(dimsGroup)
            clearGroup(figGroup)
            clearGroup(refGroup)
            const figToken = ++figTokenRef.current
            // The model's box in WORLD space, after the orientation fix —
            // both the scale kit and the dims overlay below measure from it,
            // so the figure stands on the same lower edge the H label marks.
            const ob = new THREE.Box3().setFromObject(object)

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
            // Numbered marker dots at their raw-box fractions.
            const r = rawMaxDim * 0.025
            ;(markersRef.current || []).forEach((m, i) => {
              const local = new THREE.Vector3(
                rawBox.min.x + m.at[0] * rawSize.x,
                rawBox.min.y + m.at[1] * rawSize.y,
                rawBox.min.z + m.at[2] * rawSize.z)
              const dot = new THREE.Mesh(
                new THREE.SphereGeometry(r, 10, 10),
                new THREE.MeshBasicMaterial({ color: 0x3fb950, depthTest: false }))
              dot.renderOrder = 2
              dot.position.copy(local)
              markerGroup.add(dot)
              const num = textSprite(String(i + 1), '#3fb950', rawMaxDim * 0.09)
              num.position.copy(local)
              num.position.y += r * 2.4
              markerGroup.add(num)
              // Posed preview figure (1.7 m at the caller's mesh scale) —
              // a sit marker is only judgeable with someone sitting there.
              const figH = figureHeightRef.current
              if (!(figH > 0)) return
              void (async () => {
                const src = await loadTestFigure()
                if (!src || disposed || figTokenRef.current !== figToken) return
                const anim = m.animation ? await loadClip(m.animation) : null
                const { clone: skclone } =
                  await import('three/examples/jsm/utils/SkeletonUtils.js')
                if (disposed || figTokenRef.current !== figToken) return
                const inst = skclone(src) as Object3D
                const fpivot = new THREE.Group()
                fpivot.add(inst)
                // Up-axis fix measured on the REST skeletons — same logic as
                // the floor-plan preview / the main clip path above.
                if (anim) {
                  const hipsOf = (root: Object3D): Object3D | null => {
                    let found: Object3D | null = null
                    root.traverse((o) => { if (!found && /hips/i.test(o.name)) found = o })
                    return found
                  }
                  const instHips = hipsOf(inst)
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
                // routine — soles on 0, XZ centred, scaled to `figH` (1.70 m
                // in this mesh's units). The clip is played afterwards and
                // never re-grounds the body.
                anchorFigureBind(THREE, fpivot, figH)
                if (anim) {
                  const mixer = new THREE.AnimationMixer(inst)
                  mixer.clipAction(anim.clip).play()
                  mixer.update(0)  // static frame-0 pose — no per-frame cost
                }
                place.updateMatrixWorld(true)
                // WHICH part of the body the marker point carries: a seated
                // body touches at the buttocks, so the root goes the clip's
                // share of the figure height BELOW the marked surface. Same
                // routine and same table as the floor-plan preview and the 3D
                // client, which is the whole point — this viewer used to read
                // the hips bone off the "posed" skeleton instead, and because
                // every clip is played in place (the Mixamo hips POSITION
                // track is dropped above) that reading was one constant for
                // every clip: 0.9288 m at H = 1.70 m, which put a sitter
                // 0.395 m below where the scene renders it.
                const world = pivot.localToWorld(local.clone())
                const fig = new THREE.Group()
                fig.position.copy(world)
                fig.position.y = figureRootY(world.y, figH, m.animation)
                fig.rotation.y = _deg(m.facing)
                fig.add(fpivot)
                fig.userData.__shared = true
                figGroup.add(fig)
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
          overlayFnRef.current = rebuildOverlay
          rebuildOverlay()
          disposers.push(() => {
            overlayFnRef.current = null
            figTokenRef.current++
            clearGroup(markerGroup)
            clearGroup(dimsGroup)
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
            if (!start || !pickingRef.current || !onPickPointRef.current) return
            if (Math.hypot(e.clientX - start[0], e.clientY - start[1]) > 5) return
            const rect = renderer.domElement.getBoundingClientRect()
            const ndc = new THREE.Vector2(
              ((e.clientX - rect.left) / rect.width) * 2 - 1,
              -(((e.clientY - rect.top) / rect.height) * 2 - 1))
            const ray = new THREE.Raycaster()
            ray.setFromCamera(ndc, camera)
            const hit = ray.intersectObject(object, true)[0]
            if (!hit) return
            const local = pivot.worldToLocal(hit.point.clone())
            const frac = (v: number, lo: number, span: number) =>
              Math.round(Math.min(Math.max((v - lo) / (span || 1), 0), 1) * 1000) / 1000
            onPickPointRef.current([
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

        setLoading(false)

        let raf = 0
        const animate = () => {
          raf = requestAnimationFrame(animate)
          if (mixer) mixer.update(clock.getDelta())
          controls.update()
          renderer.render(scene, camera)
        }
        animate()
        disposers.push(() => cancelAnimationFrame(raf))

        const onResize = () => {
          const w = mount.clientWidth || width
          camera.aspect = w / height
          camera.updateProjectionMatrix()
          renderer.setSize(w, height)
        }
        window.addEventListener('resize', onResize)
        disposers.push(() => window.removeEventListener('resize', onResize))
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
  }, [url, format, clipUrl, textureUrl, height, groundTextureUrl])

  return (
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
          (PolygonHandles): click drops a point, double-click closes, Escape
          cancels. It only ever REPORTS; the panel posts, the server splits. */}
      {drawing && !loading && !error ? (
        layoutOk ? (
          <svg
            width="100%" height={height}
            style={{ position: 'absolute', inset: 0, cursor: 'crosshair' }}
            onClick={addPolyPoint}
            onDoubleClick={closePoly}
            onMouseMove={(e) => {
              if (poly.length) setPolyCursor(atOverlay(e))
            }}
          >
            {poly.length ? (
              <polyline
                points={[...poly, ...(polyCursor ? [polyCursor] : [])]
                  .map(([x, y]) => `${x},${y}`).join(' ')}
                fill="rgba(88,166,255,0.14)" stroke="#58a6ff" strokeWidth={1.5}
              />
            ) : null}
            {poly.map(([x, y], i) => (
              <circle key={i} cx={x} cy={y} r={3} fill="#58a6ff" />
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
      {/* Back to the authoring view after an orbit — the polygon is drawn on
          whatever the camera shows, but a flat panel is judged head-on. */}
      {frontal && !loading && !error ? (
        <button
          type="button" className="ga-btn ga-btn-sm"
          style={{ position: 'absolute', right: 6, top: 6, opacity: 0.85 }}
          onClick={() => refitFnRef.current?.()}
          title={t('Look at the model straight on again — the view the areas were drawn in.')}
        >
          {t('Front view')}
        </button>
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
  )
}
