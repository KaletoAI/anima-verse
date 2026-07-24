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
import type { Mesh, Object3D } from 'three'
import type { Map3D, Room } from './worldTypes'

const PLATE_M = 8

interface CachedModel {
  obj: Object3D
  rotation: { x?: number; y?: number; z?: number }
  offsetY: number
  offsetX: number
  offsetZ: number
  /** Declared real-world width of the largest side (metres, 0 = unset). */
  widthM: number
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
          offset_y?: number; offset_x?: number; offset_z?: number
          width_m?: number }>(`${base}/meta`)
        const fmt = (meta.format || 'glb').toLowerCase()
        if (fmt !== 'glb' && fmt !== 'gltf') return null
        const { GLTFLoader } = await import('three/examples/jsm/loaders/GLTFLoader.js')
        const gltf = await new GLTFLoader().loadAsync(meta.url || base)
        return { obj: gltf.scene, rotation: meta.rotation || {},
                 offsetY: meta.offset_y || 0,
                 offsetX: meta.offset_x || 0, offsetZ: meta.offset_z || 0,
                 widthM: meta.width_m || 0 }
      } catch {
        return null  // 404 = no model — the room just has no underlay
      }
    })()
    modelCache.set(roomId, p)
  }
  return p
}

interface BuildingModel {
  obj: Object3D
  rotation: { x?: number; y?: number; z?: number }
  heightM: number
  floors: number
  /** Tile-plane shift in world metres (after the yaw): +x east, +z south. */
  offsetX: number
  offsetZ: number
}

const buildingCache = new Map<string, Promise<BuildingModel | null>>()

function loadBuildingModel(locationId: string): Promise<BuildingModel | null> {
  let p = buildingCache.get(locationId)
  if (!p) {
    p = (async () => {
      try {
        const base = `/play/locations/${encodeURIComponent(locationId)}/model`
        const meta = await apiGet<{ format?: string; url?: string
          rotation?: { x?: number; y?: number; z?: number }
          height_m?: number; floors?: number
          offset_x?: number; offset_z?: number }>(`${base}/meta`)
        const fmt = (meta.format || 'glb').toLowerCase()
        if (fmt !== 'glb' && fmt !== 'gltf') return null
        const { GLTFLoader } = await import('three/examples/jsm/loaders/GLTFLoader.js')
        const gltf = await new GLTFLoader().loadAsync(meta.url || base)
        return { obj: gltf.scene, rotation: meta.rotation || {},
                 heightM: meta.height_m || 0, floors: meta.floors || 0,
                 offsetX: meta.offset_x || 0, offsetZ: meta.offset_z || 0 }
      } catch {
        return null
      }
    })()
    buildingCache.set(locationId, p)
  }
  return p
}

/** ONE refresh channel for every 3D-model mutation (height, storeys,
 *  width, rotation, offset, select, delete — from the panel, the adjust
 *  strip or the preview toolbar): invalidates the module caches here and
 *  broadcasts 'anima-model3d-changed'. The floor-plan editor and the
 *  preview listen and refetch — EVERYTHING derived (plan width, rect
 *  sizes, figures, storeys, shell) recomputes from fresh metas. */
export function notifyModel3dChanged(detail: { locationId?: string; roomId?: string }) {
  if (detail.roomId) modelCache.delete(detail.roomId)
  if (detail.locationId) buildingCache.delete(detail.locationId)
  window.dispatchEvent(new CustomEvent('anima-model3d-changed', { detail }))
}

/** Scale-anchor inputs of the building model: declared height/storeys plus
 *  the mesh's width-per-height ratio (largest XZ side / Y, measured AFTER
 *  the meta rotation fix). The auto plan width derives as
 *  heightM × widthPerHeight — editor and preview share this helper so
 *  both compute the identical value. null = no model. */
export async function getBuildingDims(locationId: string):
    Promise<{ heightM: number; floors: number; widthPerHeight: number } | null> {
  const entry = await loadBuildingModel(locationId)
  if (!entry) return null
  const THREE = await import('three')
  const deg = (v?: number) => ((v || 0) * Math.PI) / 180
  const holder = new THREE.Group()
  holder.add(entry.obj.clone(true))
  holder.rotation.set(deg(entry.rotation.x), deg(entry.rotation.y),
                      deg(entry.rotation.z))
  holder.updateMatrixWorld(true)
  const size = new THREE.Box3().setFromObject(holder).getSize(new THREE.Vector3())
  return { heightM: entry.heightM, floors: entry.floors,
           widthPerHeight: (Math.max(size.x, size.z) || 1) / (size.y || 1) }
}

/** Declared width + normalized footprint of a room's ACTIVE model — the
 *  floor-plan editor derives the room-rectangle size from it in anchored
 *  mode (plan_width_m set): long side = width_m / plan_width_m, short side
 *  via the footprint aspect. null = no model. Shares the model cache. */
export async function getRoomModelDims(roomId: string):
    Promise<{ widthM: number; fpX: number; fpZ: number } | null> {
  const entry = await loadRoomModel(roomId)
  if (!entry) return null
  const THREE = await import('three')
  const box = new THREE.Box3().setFromObject(entry.obj)
  const size = box.getSize(new THREE.Vector3())
  const m = Math.max(size.x, size.z) || 1
  return { widthM: entry.widthM, fpX: size.x / m, fpZ: size.z / m }
}

export async function renderTopDownSnapshot(opts: {
  rooms: Room[]
  level: number
  width?: number
  /** Render the room models (the "Models behind the plan" layer). */
  includeRooms?: boolean
  /** Also render the location's BUILDING model (ghosted, plan-fit + yaw
   *  chain) — for tracing the outline polygon over the real footprint. */
  building?: { locationId: string; map3d?: Map3D; fallbackYawDeg?: number }
}): Promise<string | null> {
  const { rooms, level, width = 840, includeRooms = true, building } = opts
  const placed = includeRooms
    ? rooms.filter((r) => r.id && r.layout && (r.layout.level || 0) === level)
    : []
  const bModel = building ? await loadBuildingModel(building.locationId) : null
  if (!placed.length && !bModel) return null
  const entries = await Promise.all(placed.map((r) => loadRoomModel(r.id!)))
  if (!entries.some(Boolean) && !bModel) return null

  const THREE = await import('three')
  const deg = (v?: number) => ((v || 0) * Math.PI) / 180
  const scene = new THREE.Scene()
  scene.background = null
  // Bright, even light — the underlay is a reference image, not a staging.
  scene.add(new THREE.AmbientLight(0xffffff, 2.4))
  scene.add(new THREE.HemisphereLight(0xffffff, 0x888888, 2.4))

  // Building layer first, half-transparent — the roof view IS the real
  // footprint to trace the outline over; rooms stay readable through it.
  if (bModel && building) {
    const m3 = building.map3d
    const holder = new THREE.Group()
    const clone = bModel.obj.clone(true)
    clone.traverse((o: Object3D) => {
      const mesh = o as Mesh
      if (!mesh.isMesh) return
      const src = Array.isArray(mesh.material) ? mesh.material[0] : mesh.material
      const map = (src as { map?: unknown })?.map || null
      mesh.material = new THREE.MeshBasicMaterial({
        map: map as never, color: 0xffffff,
        transparent: true, opacity: 0.55, depthWrite: false,
      })
    })
    const metaG = new THREE.Group()
    metaG.add(clone)
    metaG.rotation.set(deg(bModel.rotation.x), deg(bModel.rotation.y),
                       deg(bModel.rotation.z))
    holder.add(metaG)
    const mapYaw = m3?.rotation !== undefined
      ? m3.rotation : (building.fallbackYawDeg || 0)
    holder.rotation.y = -deg(mapYaw)
    holder.updateMatrixWorld(true)
    const br = new THREE.Box3().setFromObject(holder)
    const sr = br.getSize(new THREE.Vector3())
    const kxz = (10 * 0.92 * (m3?.size || 0.92)) / (Math.max(sr.x, sr.z) || 1)
    holder.scale.setScalar(kxz)
    holder.updateMatrixWorld(true)
    const b2 = new THREE.Box3().setFromObject(holder)
    const c2 = b2.getCenter(new THREE.Vector3())
    holder.position.set(-c2.x + (bModel.offsetX || 0),
                        -b2.min.y - (b2.max.y - b2.min.y) - 0.5,
                        -c2.z + (bModel.offsetZ || 0))
    scene.add(holder)
  }

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
    // Contract order: meta rotation fix first (inner), THEN the layout yaw
    // as its own parent — one combined Euler drifts once an x/z fix is set.
    const holder = new THREE.Group()
    holder.add(fit)
    holder.rotation.set(deg(entry.rotation.x), deg(entry.rotation.y),
                        deg(entry.rotation.z))
    const yawG = new THREE.Group()
    yawG.add(holder)
    yawG.rotation.y = -deg(lay.rotation)
    yawG.updateMatrixWorld(true)
    const b2 = new THREE.Box3().setFromObject(yawG)
    const c2 = b2.getCenter(new THREE.Vector3())
    // Plan-placed diorama anchor (layout.model_at, default = centred).
    const mAt = lay.model_at || [0.5, 0.5]
    yawG.position.set((lay.x + mAt[0] * lay.w - 0.5) * PLATE_M - c2.x, -b2.min.y,
                      (lay.y + mAt[1] * lay.d - 0.5) * PLATE_M - c2.z)
    scene.add(yawG)
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
