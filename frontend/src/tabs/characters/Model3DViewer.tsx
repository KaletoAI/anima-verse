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
import type { Material, Mesh, Object3D } from 'three'
import { useI18n } from '../../i18n/I18nProvider'

export function Model3DViewer({ url, format, clipUrl = '', height = 320 }:
  { url: string; format: string; clipUrl?: string; height?: number }) {
  const { t } = useI18n()
  const mountRef = useRef<HTMLDivElement>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

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

        // A pivot carries the orientation fix: the clip animates the model's
        // OWN root bone, so rotating the model itself would fight the
        // animation. The pivot sits above it, untouched by the mixer.
        const pivot = new THREE.Group()
        pivot.add(object)
        scene.add(pivot)

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
        }
        const clock = new THREE.Clock()
        pivot.updateMatrixWorld(true)

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

        setLoading(false)

        let raf = 0
        const animate = () => {
          raf = requestAnimationFrame(animate)
          if (mixer) mixer.update(clock.getDelta())
          controls.update()
          renderer.render(scene, camera)
        }
        animate()

        const onResize = () => {
          const w = mount.clientWidth || width
          camera.aspect = w / height
          camera.updateProjectionMatrix()
          renderer.setSize(w, height)
        }
        window.addEventListener('resize', onResize)

        cleanup = () => {
          cancelAnimationFrame(raf)
          window.removeEventListener('resize', onResize)
          mixer?.stopAllAction()
          controls.dispose()
          renderer.dispose()
          scene.traverse((o: Object3D) => {
            const mesh = o as Mesh
            mesh.geometry?.dispose?.()
            const m = mesh.material as Material | Material[] | undefined
            if (Array.isArray(m)) m.forEach((x) => x.dispose?.())
            else m?.dispose?.()
          })
          if (renderer.domElement.parentNode === mount) mount.removeChild(renderer.domElement)
        }
      } catch (e) {
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
  }, [url, format, clipUrl, height])

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
