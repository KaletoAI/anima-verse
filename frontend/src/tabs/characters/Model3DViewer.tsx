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
import type { Material, Mesh, MeshStandardMaterial, Object3D } from 'three'
import { useI18n } from '../../i18n/I18nProvider'

const _deg = (v?: number) => ((v || 0) * Math.PI) / 180

/** Placement of a building model on its map tile — mirrors the worldmap
 *  contract (map3d.rotation / map3d.size in schnittstellen-3d.md). */
export interface TilePlacement {
  /** Yaw around the vertical axis in degrees. */
  yawDeg: number
  /** Base size as a fraction of the tile edge (0..1). */
  size: number
  /** Declared model height in world metres (0 = natural) — applies the
   *  detail view's per-axis k_y so this viewer matches the floor-plan
   *  preview and the 3D client exactly. */
  heightM?: number
  /** Explicit plan width anchor (map3d.plan_width_m, 0 = auto/legacy). */
  planWidthM?: number
}

export function Model3DViewer({ url, format, clipUrl = '', textureUrl = '', height = 320, rotation,
  offsetY = 0, groundTextureUrl, placement }:
  { url: string; format: string; clipUrl?: string; textureUrl?: string; height?: number;
    /** Persisted 90°-step orientation fix ({x,y,z} in degrees) — applied live,
     *  without reloading the model. */
    rotation?: { x?: number; y?: number; z?: number }
    /** Vertical placement offset in model units/metres (tile mode only) —
     *  negative sinks the model below the tile, like the 3D client does. */
    offsetY?: number
    /** When `placement` is set, the viewer shows the world tile (a 1×1 ground
     *  square, textured with this image when given) and places the model on
     *  it — centred, yawed and scaled per `placement`, feet on the ground. */
    groundTextureUrl?: string
    placement?: TilePlacement }) {
  const { t } = useI18n()
  const mountRef = useRef<HTMLDivElement>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const orientRef = useRef<Object3D | null>(null)
  const rotationRef = useRef(rotation)
  rotationRef.current = rotation
  const placeFnRef = useRef<((p: TilePlacement) => void) | null>(null)
  const placementRef = useRef(placement)
  placementRef.current = placement
  const offsetYRef = useRef(offsetY)
  offsetYRef.current = offsetY

  // Live-apply an offset change (the placement fn reads the ref).
  useEffect(() => {
    if (placementRef.current) placeFnRef.current?.(placementRef.current)
  }, [offsetY])

  // Live-apply a changed rotation to the mounted scene — a reload would
  // re-download a multi-MB model per 90° click. In tile mode the orientation
  // fix changes the model's bounding box, so the placement (scale + ground
  // offset) is re-derived right after.
  useEffect(() => {
    orientRef.current?.rotation.set(
      _deg(rotation?.x), _deg(rotation?.y), _deg(rotation?.z))
    if (placementRef.current) placeFnRef.current?.(placementRef.current)
  }, [rotation?.x, rotation?.y, rotation?.z])

  // Live-apply placement changes (yaw slider / size slider) without reload.
  useEffect(() => {
    if (placement) placeFnRef.current?.(placement)
  }, [placement, placement?.yawDeg, placement?.size,
    placement?.heightM, placement?.planWidthM])

  useEffect(() => {
    let disposed = false
    let cleanup: (() => void) | undefined
    setLoading(true)
    setError('')

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
          // SAME placement chain as the floor-plan preview / 3D client
          // (v3 contract, in tile units: 1 unit = 10 m world): rotation
          // first, then k_xz = (10 × 0.92 × size)/maxXZ and k_y from the
          // declared model height (natural without it), bottom of the
          // scaled bbox at the 0.06 m socle + offset_y (world metres).
          const applyPlacement = (p: TilePlacement) => {
            place.rotation.set(0, 0, 0)
            place.scale.setScalar(1)
            place.position.set(0, 0, 0)
            place.updateMatrixWorld(true)
            // Yaw-free measurement first: the auto plan width derives from
            // the mesh's width-per-height ratio AFTER the meta rotation fix
            // but BEFORE the map yaw (getBuildingDims does the same) —
            // yawing a non-square footprint would change the AABB and drift
            // the two viewers apart.
            const b0 = new THREE.Box3().setFromObject(place)
            const s0 = b0.getSize(new THREE.Vector3())
            const wph = (Math.max(s0.x, s0.z) || 1) / (s0.y || 1)
            place.rotation.y = -_deg(p.yawDeg)
            place.updateMatrixWorld(true)
            const b = new THREE.Box3().setFromObject(place)
            const s = b.getSize(new THREE.Vector3())
            const maxXZ = Math.max(s.x, s.z) || 1
            const size = Math.max(0.02, Math.min(1.5, p.size))
            const kxzWorld = (10 * 0.92 * size) / maxXZ
            let kyWorld = kxzWorld
            if (p.heightM && p.heightM > 0) {
              // Effective plan width: explicit anchor, else auto-derived
              // (height × width-per-height) — the identical chain the
              // floor preview computes.
              const planW = (p.planWidthM && p.planWidthM > 0)
                ? p.planWidthM
                : p.heightM * wph
              const kFac = planW > 0 ? 8 / planW : 1
              kyWorld = (p.heightM * kFac) / (s.y || 1)
            }
            // Tile units = world / 10.
            place.scale.set(kxzWorld / 10, kyWorld / 10, kxzWorld / 10)
            place.updateMatrixWorld(true)
            const b2 = new THREE.Box3().setFromObject(place)
            const c2 = b2.getCenter(new THREE.Vector3())
            place.position.set(
              -c2.x,
              -b2.min.y + (0.06 + (offsetYRef.current || 0)) / 10,
              -c2.z)
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
