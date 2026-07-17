/**
 * topDownSnapshot — renders the placed room models of ONE level straight from
 * above (orthographic, exactly covering the contract's 8×8 m reference
 * square) and returns the image as a data URL. The floor-plan editor lays it
 * BEHIND the room rectangles, so markers can be dropped on actual furniture.
 * Placement follows the contract chain (schnittstellen-3d.md → placement
 * semantics), so the underlay lines up with what the game client renders.
 *
 * Models are cached per room id (shared promise — a re-render never
 * re-downloads); the WebGL context is created per snapshot and released
 * immediately (browsers cap live contexts).
 */
import { apiGet } from '../../lib/api'
import type { Object3D } from 'three'
import type { Room } from './worldTypes'

const PLATE_M = 8

interface CachedModel {
  obj: Object3D
  rotation: { x?: number; y?: number; z?: number }
  offsetY: number
}

const modelCache = new Map<string, Promise<CachedModel | null>>()

function loadRoomModel(roomId: string): Promise<CachedModel | null> {
  let p = modelCache.get(roomId)
  if (!p) {
    p = (async () => {
      try {
        const base = `/play/rooms/${encodeURIComponent(roomId)}/model`
        const meta = await apiGet<{ format?: string; url?: string
          rotation?: { x?: number; y?: number; z?: number }
          offset_y?: number }>(`${base}/meta`)
        const fmt = (meta.format || 'glb').toLowerCase()
        if (fmt !== 'glb' && fmt !== 'gltf') return null
        const { GLTFLoader } = await import('three/examples/jsm/loaders/GLTFLoader.js')
        const gltf = await new GLTFLoader().loadAsync(meta.url || base)
        return { obj: gltf.scene, rotation: meta.rotation || {},
                 offsetY: meta.offset_y || 0 }
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
  width?: number
}): Promise<string | null> {
  const { rooms, level, width = 840 } = opts
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
    const w = lay.w * PLATE_M
    const d = lay.d * PLATE_M
    // Contract chain: normalize to unit footprint, fit × 0.96 (unrotated),
    // then meta rotation + layout yaw; top-down ignores heights.
    const norm = new THREE.Group()
    norm.add(entry.obj.clone(true))
    norm.updateMatrixWorld(true)
    const b0 = new THREE.Box3().setFromObject(norm)
    const s0 = b0.getSize(new THREE.Vector3())
    const unit = 1 / (Math.max(s0.x, s0.z) || 1)
    const fpX = s0.x * unit
    const fpZ = s0.z * unit
    norm.scale.setScalar(unit)
    norm.updateMatrixWorld(true)
    const b1 = new THREE.Box3().setFromObject(norm)
    const c1 = b1.getCenter(new THREE.Vector3())
    norm.position.set(-c1.x, -b1.min.y, -c1.z)
    const fit = new THREE.Group()
    fit.add(norm)
    fit.scale.setScalar(Math.min(w / (fpX || 1), d / (fpZ || 1)) * 0.96)
    const holder = new THREE.Group()
    holder.add(fit)
    holder.rotation.set(deg(entry.rotation.x),
                        deg(entry.rotation.y) - deg(lay.rotation),
                        deg(entry.rotation.z))
    holder.updateMatrixWorld(true)
    const b2 = new THREE.Box3().setFromObject(holder)
    const c2 = b2.getCenter(new THREE.Vector3())
    holder.position.set((lay.x + lay.w / 2 - 0.5) * PLATE_M - c2.x, -b2.min.y,
                        (lay.y + lay.d / 2 - 0.5) * PLATE_M - c2.z)
    scene.add(holder)
  })

  // Straight down, up = -Z: image top = plan top, image left = plan left —
  // pixel-aligned with the editor rectangles (both cover the 8×8 m square).
  const half = PLATE_M / 2
  const camera = new THREE.OrthographicCamera(-half, half, half, -half, 0.01, 200)
  camera.position.set(0, 60, 0)
  camera.up.set(0, 0, -1)
  camera.lookAt(0, 0, 0)

  const renderer = new THREE.WebGLRenderer({
    antialias: true, alpha: true, preserveDrawingBuffer: true,
  })
  try {
    renderer.setSize(width, width)
    renderer.render(scene, camera)
    return renderer.domElement.toDataURL('image/png')
  } finally {
    // Cached model clones share geometry with the cache — dispose ONLY the
    // GL context, not the scene contents.
    renderer.dispose()
    renderer.forceContextLoss()
  }
}
