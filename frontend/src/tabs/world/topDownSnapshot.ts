/**
 * topDownSnapshot — renders the placed room models of ONE level straight from
 * above (orthographic, exactly covering the building footprint) and returns
 * the image as a data URL. The floor-plan editor lays it BEHIND the room
 * rectangles, so markers can be dropped on actual furniture. Alignment is by
 * construction: the models are placed with the same layout fractions the
 * rectangles use.
 *
 * Models are cached per room id (shared promise — a re-render never
 * re-downloads); the WebGL context is created per snapshot and released
 * immediately (browsers cap live contexts).
 */
import { apiGet } from '../../lib/api'
import type { Object3D } from 'three'
import type { Room } from './worldTypes'

interface CachedModel {
  obj: Object3D
  rotation: { x?: number; y?: number; z?: number }
}

const modelCache = new Map<string, Promise<CachedModel | null>>()

function loadRoomModel(roomId: string): Promise<CachedModel | null> {
  let p = modelCache.get(roomId)
  if (!p) {
    p = (async () => {
      try {
        const base = `/play/rooms/${encodeURIComponent(roomId)}/model`
        const meta = await apiGet<{ format?: string; url?: string
          rotation?: { x?: number; y?: number; z?: number } }>(`${base}/meta`)
        const fmt = (meta.format || 'glb').toLowerCase()
        if (fmt !== 'glb' && fmt !== 'gltf') return null
        const { GLTFLoader } = await import('three/examples/jsm/loaders/GLTFLoader.js')
        const gltf = await new GLTFLoader().loadAsync(meta.url || base)
        return { obj: gltf.scene, rotation: meta.rotation || {} }
      } catch {
        return null  // 404 = no model — the room just has no underlay
      }
    })()
    modelCache.set(roomId, p)
  }
  return p
}

export async function renderTopDownSnapshot(opts: {
  rooms: Room[]
  level: number
  fw: number
  fd: number
  width?: number
}): Promise<string | null> {
  const { rooms, level, fw, fd, width = 840 } = opts
  const placed = rooms.filter((r) => r.id && r.layout && (r.layout.level || 0) === level)
  if (!placed.length) return null
  const entries = await Promise.all(placed.map((r) => loadRoomModel(r.id!)))
  if (!entries.some(Boolean)) return null

  const THREE = await import('three')
  const deg = (v?: number) => ((v || 0) * Math.PI) / 180
  const scene = new THREE.Scene()
  scene.background = null
  // Bright, even light — the underlay is a reference image, not a staging.
  scene.add(new THREE.AmbientLight(0xffffff, 2.4))
  scene.add(new THREE.HemisphereLight(0xffffff, 0x888888, 2.4))

  placed.forEach((room, idx) => {
    const entry = entries[idx]
    const lay = room.layout
    if (!entry || !lay) return
    const w = lay.w * fw
    const d = lay.d * fd
    const inner = new THREE.Group()
    inner.add(entry.obj.clone(true))
    inner.rotation.set(deg(entry.rotation.x), deg(entry.rotation.y), deg(entry.rotation.z))
    const holder = new THREE.Group()
    holder.add(inner)
    holder.rotation.y = -deg(lay.rotation)
    holder.updateMatrixWorld(true)
    const b = new THREE.Box3().setFromObject(holder)
    const s = b.getSize(new THREE.Vector3())
    holder.scale.setScalar(Math.min(w / (s.x || 1), d / (s.z || 1)))
    holder.updateMatrixWorld(true)
    const b2 = new THREE.Box3().setFromObject(holder)
    const c2 = b2.getCenter(new THREE.Vector3())
    holder.position.set((lay.x + lay.w / 2 - 0.5) * fw - c2.x, -b2.min.y,
                        (lay.y + lay.d / 2 - 0.5) * fd - c2.z)
    scene.add(holder)
  })

  // Straight down, up = -Z: image top = plan top, image left = plan left —
  // pixel-aligned with the editor rectangles.
  const camera = new THREE.OrthographicCamera(-fw / 2, fw / 2, fd / 2, -fd / 2, 0.01, 100)
  camera.position.set(0, 20, 0)
  camera.up.set(0, 0, -1)
  camera.lookAt(0, 0, 0)

  const height = Math.max(1, Math.round((width * fd) / fw))
  const renderer = new THREE.WebGLRenderer({
    antialias: true, alpha: true, preserveDrawingBuffer: true,
  })
  try {
    renderer.setSize(width, height)
    renderer.render(scene, camera)
    return renderer.domElement.toDataURL('image/png')
  } finally {
    // Cached model clones share geometry with the cache — dispose ONLY the
    // GL context, not the scene contents.
    renderer.dispose()
    renderer.forceContextLoss()
  }
}
