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
import { useEffect, useRef, useState } from 'react'
import type { AnimationClip, Material, Mesh, MeshStandardMaterial, Object3D } from 'three'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet } from '../../lib/api'

const _deg = (v?: number) => ((v || 0) * Math.PI) / 180

// ── Shared marker-figure sources (module cache — one fetch per session,
// every viewer instance clones from these) ──
let _figPromise: Promise<Object3D | null> | null = null
const loadTestFigure = (): Promise<Object3D | null> => {
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
 *  contract (map3d.rotation / map3d.size in schnittstellen-3d.md). */
export interface TilePlacement {
  /** Yaw around the vertical axis in degrees. */
  yawDeg: number
  /** The model's share of the location's reference square (]0, 1]). */
  size: number
  /** The location's extent in WORLD metres (map3d.extent_m, default 10 =
   *  one map tile) — together with `size` the ONE scale factor. */
  extentM?: number
}

export function Model3DViewer({ url, format, clipUrl = '', textureUrl = '', height = 320, rotation,
  offsetY = 0, offsetX = 0, offsetZ = 0,
  groundTextureUrl, placement, onBounds, markers, dimsOverlay,
  figureHeight = 0, picking = false, onPickPoint }:
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
    /** Draw the oriented bounding box with W/D/H edges + labels (real
     *  metres) around the model — makes the three dims readable in 3D.
     *  Model mode only; follows the orientation fix live. */
    dimsOverlay?: { width_m: number; depth_m: number; height_m: number } | null
    /** Armed pick mode: a plain click on the mesh reports the hit as RAW-box
     *  fractions — the floor-plan-style marker placement. */
    picking?: boolean
    onPickPoint?: (at: [number, number, number]) => void }) {
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
  // Stale-guard for the async figure loads of an overlay rebuild.
  const figTokenRef = useRef(0)
  const pickingRef = useRef(picking)
  pickingRef.current = picking
  const onPickPointRef = useRef(onPickPoint)
  onPickPointRef.current = onPickPoint
  const overlayFnRef = useRef<(() => void) | null>(null)
  const canvasRef = useRef<HTMLCanvasElement | null>(null)

  // Live overlay refresh (markers moved/added, dims typed) without reload.
  useEffect(() => { overlayFnRef.current?.() }, [markers, dimsOverlay, figureHeight])
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
    orientRef.current?.rotation.set(
      _deg(rotation?.x), _deg(rotation?.y), _deg(rotation?.z))
    if (placementRef.current) placeFnRef.current?.(placementRef.current)
    // The oriented dims box follows the fix.
    overlayFnRef.current?.()
  }, [rotation?.x, rotation?.y, rotation?.z])

  // Live-apply placement changes (yaw slider / size slider) without reload.
  useEffect(() => {
    if (placement) placeFnRef.current?.(placement)
  }, [placement, placement?.yawDeg, placement?.size, placement?.extentM])

  useEffect(() => {
    let disposed = false
    let cleanup: (() => void) | undefined
    setLoading(true)
    setError('')
    setMeshStats(null)

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
        if (ext === 'fbx') {
          const { FBXLoader } = await import('three/examples/jsm/loaders/FBXLoader.js')
          object = await new FBXLoader().loadAsync(url)
        } else if (ext === 'glb' || ext === 'gltf' || ext === 'vrm') {
          const { GLTFLoader } = await import('three/examples/jsm/loaders/GLTFLoader.js')
          const gltf = await new GLTFLoader().loadAsync(url)
          object = gltf.scene
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
        {
          // Face/vertex count over all meshes (indexed: index/3, else pos/3).
          let tris = 0
          let verts = 0
          object.traverse((o: Object3D) => {
            const mesh = o as Mesh
            if (!mesh.isMesh) return
            const geo = mesh.geometry as { index?: { count: number } | null
              attributes?: { position?: { count: number } } }
            const pos = geo.attributes?.position?.count || 0
            verts += pos
            tris += Math.floor((geo.index ? geo.index.count : pos) / 3)
          })
          setMeshStats({ tris, verts })
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
          // ── Tile mode: the world square with the model placed on it. ──
          // Ground: a 1×1 tile in the XZ plane, textured with the location's
          // 2D map icon when available, plus an outline so the tile edge
          // stays visible over dark textures.
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

          // Derive scale + yaw + ground offset fresh from the model's current
          // bounding box — the orientation fix changes the box, so this runs
          // again after every ↻ click (see the rotation effect above).
          // SAME chain as the scene spec: ONE factor on all three axes, the
          // largest YAWED XZ side becomes `size × extent_m`. There is no
          // per-axis branch any more (it made this panel show the model
          // 13–15 % flatter than both scene renderers).
          const applyPlacement = (p: TilePlacement) => {
            place.rotation.set(0, 0, 0)
            place.scale.setScalar(1)
            place.position.set(0, 0, 0)
            place.rotation.y = -_deg(p.yawDeg)
            place.updateMatrixWorld(true)
            const b = new THREE.Box3().setFromObject(place)
            const s = b.getSize(new THREE.Vector3())
            const maxXZ = Math.max(s.x, s.z) || 1
            const size = Math.max(0.02, Math.min(1, p.size))
            const extent = p.extentM && p.extentM > 0 ? p.extentM : 10
            const kWorld = (extent * size) / maxXZ
            // Tile units = world / 10.
            place.scale.setScalar(kWorld / 10)
            place.updateMatrixWorld(true)
            const b2 = new THREE.Box3().setFromObject(place)
            const c2 = b2.getCenter(new THREE.Vector3())
            place.position.set(
              -c2.x + (offsetXRef.current || 0) / 10,
              -b2.min.y + (0.06 + (offsetYRef.current || 0)) / 10,
              -c2.z + (offsetZRef.current || 0) / 10)
          }
          placeFnRef.current = applyPlacement
          disposers.push(() => {
            if (placeFnRef.current === applyPlacement) placeFnRef.current = null
          })
          applyPlacement(placementRef.current)

          // Frame tile + model together from a raised angle — the tile is the
          // reference, so it must always be fully in view.
          place.updateMatrixWorld(true)
          const mb = new THREE.Box3().setFromObject(place)
          const extent = Math.max(1.2, mb.max.y * 1.5)
          const dist = (extent / 2) / Math.tan((Math.PI * camera.fov) / 360) * 1.7
          camera.position.set(dist * 0.75, dist * 0.7, dist * 0.9)
          camera.near = dist / 100
          camera.far = dist * 100
          camera.updateProjectionMatrix()
          controls.target.set(0, Math.min(0.4, Math.max(0.1, mb.max.y / 2)), 0)
          controls.update()
        } else {
          // Frame the model: centre it and pull the camera back to fit.
          const box = new THREE.Box3().setFromObject(pivot)
          const size = box.getSize(new THREE.Vector3())
          const center = box.getCenter(new THREE.Vector3())
          pivot.position.sub(center)

          const maxDim = Math.max(size.x, size.y, size.z) || 1
          const dist = (maxDim / 2) / Math.tan((Math.PI * camera.fov) / 360)
          camera.position.set(0, 0, dist * 1.6)
          camera.near = dist / 100
          camera.far = dist * 100
          camera.updateProjectionMatrix()
          controls.target.set(0, 0, 0)
          controls.update()

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
            const figToken = ++figTokenRef.current
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
                // Body size from the REST pose (a posed sitting box is far
                // shorter and would blow the figure up).
                fpivot.updateMatrixWorld(true)
                const fb = new THREE.Box3().setFromObject(fpivot)
                const fs = fb.getSize(new THREE.Vector3())
                const k = figH / (fs.y || 1)
                if (anim) {
                  const mixer = new THREE.AnimationMixer(inst)
                  mixer.clipAction(anim.clip).play()
                  mixer.update(0)  // static frame-0 pose — no per-frame cost
                }
                fpivot.scale.setScalar(k)
                // Grounding uses the POSED bounds; anchor bottom-centre at
                // the marker's WORLD point so the figure stands upright even
                // when the orientation fix tilts the mesh axes.
                fpivot.updateMatrixWorld(true)
                const fb2 = new THREE.Box3().setFromObject(fpivot)
                const fc2 = fb2.getCenter(new THREE.Vector3())
                place.updateMatrixWorld(true)
                const world = pivot.localToWorld(local.clone())
                const fig = new THREE.Group()
                fig.position.copy(world)
                fig.rotation.y = _deg(m.facing)
                fpivot.position.set(-fc2.x, -fb2.min.y, -fc2.z)
                fig.add(fpivot)
                fig.userData.__shared = true
                figGroup.add(fig)
              })()
            })
            // Oriented bounding box + coloured W/D/H edges with the REAL
            // metre values — which field means which direction.
            const dims = dimsOverlayRef.current
            if (!dims) return
            const ob = new THREE.Box3().setFromObject(object)
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
