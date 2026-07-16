/**
 * FloorPlanPreview — live 3D preview of the room layout (AV3D-2), shown next
 * to the floor-plan editor. Renders the building footprint as a ground plate
 * and every laid-out room as a translucent box on its level (stacked floors,
 * basements below ground), with name labels and the exit point as an orange
 * dot — the same data the external 3D client reads, so what you see here is
 * what the client will place.
 *
 * Two compare switches: "Real room models" swaps the boxes for the rooms'
 * ACTIVE 3D models (contain-fit into each room rectangle, per-model
 * orientation fix applied; rooms without a model keep their box), and
 * "Building model overlay" ghosts the location's building model over the
 * plan (contain-fit to the footprint) — so plan, room models and building
 * shell can be checked against each other. Models are fetched once and
 * cached; the boxes rebuild live while dragging in the editor (the three.js
 * scene itself is created once).
 *
 * three.js is imported dynamically, same as Model3DViewer — it stays in the
 * shared chunk that only loads when a 3D view is opened.
 */
import { useEffect, useRef, useState } from 'react'
import type { Object3D, Group, Material, Mesh } from 'three'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet } from '../../lib/api'
import type { Room } from './worldTypes'

// Metres per map tile assumed by the preview — 3 m storeys render as 0.2
// plate units, which lined up with real building models.
const TILE_METERS = 15
const DEFAULT_LEVEL_M = 3
const PALETTE = [0x58a6ff, 0x3fb950, 0xd29922, 0xf778ba,
                 0xa371f7, 0xf85149, 0x79c0ff, 0x56d364]

interface CachedModel {
  obj: Object3D
  rotation: { x?: number; y?: number; z?: number }
  /** Vertical placement offset in model units/metres (negative sinks it). */
  offsetY: number
  /** Prepared once on first overlay use: the model with its own textures on
   *  unlit, semi-transparent materials — visibly the building, still
   *  see-through. Scene inserts clones of this (shared materials). */
  ghost?: Object3D
}
type CacheEntry = CachedModel | 'loading' | 'missing'

interface FloorPlanPreviewProps {
  locationId: string
  rooms: Room[]
  /** Building footprint in grid cells (map3d.footprint) — plate aspect. */
  footprint?: number[]
  /** Storey height in metres (map3d.level_height) — empty = 3. */
  levelHeightM?: number
  height?: number
}

export function FloorPlanPreview({ locationId, rooms, footprint, levelHeightM, height = 360 }: FloorPlanPreviewProps) {
  const { t } = useI18n()
  const mountRef = useRef<HTMLDivElement>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [showModels, setShowModels] = useState(false)
  const [showBuilding, setShowBuilding] = useState(false)
  // Model-load completion re-triggers the rebuild (loads are async, the
  // rebuild itself is synchronous against the cache).
  const [bump, setBump] = useState(0)
  // Scene handle for the incremental rebuild (drag updates arrive per
  // pointermove — recreating the whole renderer would thrash).
  const handleRef = useRef<{
    THREE: typeof import('three')
    boxes: Group
  } | null>(null)
  const roomsRef = useRef(rooms)
  roomsRef.current = rooms
  const showModelsRef = useRef(showModels)
  showModelsRef.current = showModels
  const showBuildingRef = useRef(showBuilding)
  showBuildingRef.current = showBuilding
  // Loaded models by key ("room:<id>" / "building") — originals live here,
  // the scene gets clones (shared geometry, nothing to dispose per rebuild).
  const cacheRef = useRef<Map<string, CacheEntry>>(new Map())

  const fw = Math.max(1, footprint?.[0] || 1)
  const fd = Math.max(1, footprint?.[1] || 1)
  // Storey height in plate units: configured metres over the assumed
  // metres-per-tile (default 3 m ≙ 0.2 units).
  const lh = (levelHeightM && levelHeightM > 0 ? levelHeightM : DEFAULT_LEVEL_M) / TILE_METERS

  // Fetch a model (meta + GLB) into the cache; returns it when ready. A miss
  // is cached too — no retry storm per drag frame.
  const ensureModel = (key: string, roomId?: string): CachedModel | null => {
    const cache = cacheRef.current
    const cur = cache.get(key)
    if (cur === 'loading' || cur === 'missing') return null
    if (cur) return cur
    cache.set(key, 'loading')
    ;(async () => {
      try {
        const base = roomId
          ? `/play/rooms/${encodeURIComponent(roomId)}/model`
          : `/play/locations/${encodeURIComponent(locationId)}/model`
        const meta = await apiGet<{ format?: string; url?: string
          rotation?: { x?: number; y?: number; z?: number }
          offset_y?: number }>(`${base}/meta`)
        const fmt = (meta.format || 'glb').toLowerCase()
        if (fmt !== 'glb' && fmt !== 'gltf') throw new Error(`format ${fmt}`)
        const { GLTFLoader } = await import('three/examples/jsm/loaders/GLTFLoader.js')
        const gltf = await new GLTFLoader().loadAsync(meta.url || base)
        cache.set(key, { obj: gltf.scene, rotation: meta.rotation || {},
                         offsetY: meta.offset_y || 0 })
      } catch {
        cache.set(key, 'missing')  // 404 = no model — the box stays
      }
      setBump((b) => b + 1)
    })()
    return null
  }

  // Rebuild the plan content from the current layout (called on every rooms/
  // toggle change and once after scene init).
  const rebuild = (h: NonNullable<typeof handleRef.current>, current: Room[]) => {
    const { THREE, boxes } = h
    for (const child of [...boxes.children]) {
      boxes.remove(child)
      if (child.userData.__noDispose) continue  // cached-model clone
      child.traverse((o: Object3D) => {
        const mesh = o as Mesh
        mesh.geometry?.dispose?.()
        const m = mesh.material as Material | Material[] | undefined
        if (Array.isArray(m)) m.forEach((x) => x.dispose?.())
        else m?.dispose?.()
      })
    }

    const deg = (v?: number) => ((v || 0) * Math.PI) / 180

    // Contain-fit a cached model into a target rectangle: per-model
    // orientation fix on an inner pivot, uniform scale so the horizontal
    // extents fit, bottom on the given floor height, centred on cx/cz.
    const placeModel = (entry: CachedModel, targetW: number, targetD: number,
                        cx: number, bottomY: number, cz: number,
                        yawDeg: number, ghost: boolean) => {
      if (ghost && !entry.ghost) {
        // Keep the model's own textures — a flat gray ghost was near
        // invisible on the dark canvas. Unlit (basic) + semi-transparent +
        // no depth write: clearly the building, rooms shine through.
        const g = entry.obj.clone(true)
        g.traverse((o: Object3D) => {
          const mesh = o as Mesh
          if (!mesh.isMesh) return
          const src = Array.isArray(mesh.material) ? mesh.material[0] : mesh.material
          const map = (src as { map?: unknown })?.map || null
          mesh.material = new THREE.MeshBasicMaterial({
            map: map as never, color: 0xffffff,
            transparent: true, opacity: 0.55, depthWrite: false,
          })
        })
        entry.ghost = g
      }
      const inner = new THREE.Group()
      const clone = (ghost ? entry.ghost! : entry.obj).clone(true)
      inner.add(clone)
      inner.rotation.set(deg(entry.rotation.x), deg(entry.rotation.y), deg(entry.rotation.z))
      const holder = new THREE.Group()
      holder.add(inner)
      holder.updateMatrixWorld(true)
      const b = new THREE.Box3().setFromObject(holder)
      const s = b.getSize(new THREE.Vector3())
      holder.scale.setScalar(Math.min(targetW / (s.x || 1), targetD / (s.z || 1)))
      holder.rotation.y = -deg(yawDeg)
      holder.updateMatrixWorld(true)
      const b2 = new THREE.Box3().setFromObject(holder)
      const c2 = b2.getCenter(new THREE.Vector3())
      // offset_y is in model units/metres — scale with the model (same
      // proportion the 3D client renders).
      holder.position.set(cx - c2.x,
        bottomY - b2.min.y + entry.offsetY * holder.scale.x, cz - c2.z)
      holder.userData.__noDispose = true
      boxes.add(holder)
    }

    current.forEach((room, idx) => {
      const lay = room.layout
      if (!lay) return
      const color = PALETTE[idx % PALETTE.length]
      const w = lay.w * fw
      const d = lay.d * fd
      const level = lay.level || 0
      const bottomY = level * lh
      const cy = bottomY + lh / 2
      const cx = (lay.x + lay.w / 2 - 0.5) * fw
      const cz = (lay.y + lay.d / 2 - 0.5) * fd

      const model = showModelsRef.current && room.id
        ? ensureModel(`room:${room.id}`, room.id)
        : null
      if (model) {
        placeModel(model, w, d, cx, bottomY, cz, lay.rotation || 0, false)
      }

      // Label + exit dot always; the box only when no real model stands in.
      const roomGroup = new THREE.Group()
      if (!model) {
        const box = new THREE.Mesh(
          new THREE.BoxGeometry(w, lh * 0.94, d),
          new THREE.MeshStandardMaterial({ color, transparent: true, opacity: 0.5 }),
        )
        const edges = new THREE.LineSegments(
          new THREE.EdgesGeometry(box.geometry),
          new THREE.LineBasicMaterial({ color }),
        )
        roomGroup.add(box)
        roomGroup.add(edges)
      }

      if (lay.exit) {
        const dot = new THREE.Mesh(
          new THREE.SphereGeometry(Math.min(fw, fd) * 0.02, 12, 12),
          new THREE.MeshBasicMaterial({ color: 0xe0a356 }),
        )
        dot.position.set((lay.exit[0] - 0.5) * w, -lh * 0.4, (lay.exit[1] - 0.5) * d)
        roomGroup.add(dot)
      }

      // Name label as a canvas sprite floating above the box.
      const canvas = document.createElement('canvas')
      canvas.width = 256
      canvas.height = 64
      const ctx = canvas.getContext('2d')
      if (ctx) {
        ctx.font = '600 26px sans-serif'
        ctx.textAlign = 'center'
        ctx.textBaseline = 'middle'
        ctx.shadowColor = 'rgba(0,0,0,0.9)'
        ctx.shadowBlur = 6
        ctx.fillStyle = '#fff'
        ctx.fillText((room.name || room.id || '').slice(0, 18), 128, 32)
      }
      const tex = new THREE.CanvasTexture(canvas)
      const sprite = new THREE.Sprite(new THREE.SpriteMaterial({
        map: tex, transparent: true, depthTest: false,
      }))
      sprite.scale.set(Math.min(fw, fd) * 0.45, Math.min(fw, fd) * 0.11, 1)
      sprite.position.y = lh * 0.62
      roomGroup.add(sprite)

      roomGroup.position.set(cx, cy, cz)
      if (lay.rotation) roomGroup.rotation.y = -deg(lay.rotation)
      boxes.add(roomGroup)
    })

    // Building shell over everything — ghosted so the rooms stay visible.
    if (showBuildingRef.current) {
      const building = ensureModel('building')
      if (building) placeModel(building, fw, fd, 0, 0, 0, 0, true)
    }
  }

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
        const camera = new THREE.PerspectiveCamera(45, width / height, 0.01, 100)
        const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true })
        renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
        renderer.setSize(width, height)
        mount.appendChild(renderer.domElement)

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

        scene.add(new THREE.AmbientLight(0xffffff, 1.6))
        scene.add(new THREE.HemisphereLight(0xffffff, 0x666666, 2.0))
        const key = new THREE.DirectionalLight(0xffffff, 2.0)
        key.position.set(2, 3, 2)
        scene.add(key)

        const controls = new OrbitControls(camera, renderer.domElement)
        controls.enableDamping = true
        disposers.push(() => controls.dispose())

        // Ground plate = the building footprint, plus an outline.
        const groundGeo = new THREE.PlaneGeometry(fw, fd)
        const ground = new THREE.Mesh(
          groundGeo,
          new THREE.MeshBasicMaterial({ color: 0x2e3742 }),
        )
        ground.rotation.x = -Math.PI / 2
        scene.add(ground)
        const outline = new THREE.LineSegments(
          new THREE.EdgesGeometry(groundGeo),
          new THREE.LineBasicMaterial({ color: 0x58a6ff }),
        )
        outline.rotation.x = -Math.PI / 2
        outline.position.y = 0.002
        scene.add(outline)

        const boxes = new THREE.Group()
        scene.add(boxes)
        disposers.push(() => {
          scene.traverse((o: Object3D) => {
            if (o.userData.__noDispose) return
            const mesh = o as Mesh
            mesh.geometry?.dispose?.()
            const m = mesh.material as Material | Material[] | undefined
            if (Array.isArray(m)) m.forEach((x) => x.dispose?.())
            else m?.dispose?.()
          })
        })

        handleRef.current = { THREE, boxes }
        disposers.push(() => { handleRef.current = null })
        rebuild(handleRef.current, roomsRef.current)

        // Frame plate + a couple of levels from a raised angle.
        const extent = Math.max(fw, fd, lh * 4)
        const dist = (extent / 2) / Math.tan((Math.PI * camera.fov) / 360) * 1.5
        camera.position.set(dist * 0.7, dist * 0.75, dist * 0.85)
        controls.target.set(0, lh, 0)
        controls.update()

        setLoading(false)

        let raf = 0
        const animate = () => {
          raf = requestAnimationFrame(animate)
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
        cleanup?.()
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fw, fd, height])

  // Dispose the cached model ORIGINALS only on unmount — the init effect may
  // re-run on a footprint change while clones of these are still wanted.
  useEffect(() => {
    const cache = cacheRef.current
    return () => {
      const disposeTree = (root: Object3D) => root.traverse((o: Object3D) => {
        const mesh = o as Mesh
        mesh.geometry?.dispose?.()  // shared with the ghost — double dispose is safe
        const m = mesh.material as Material | Material[] | undefined
        if (Array.isArray(m)) m.forEach((x) => x.dispose?.())
        else m?.dispose?.()
      })
      for (const entry of cache.values()) {
        if (entry === 'loading' || entry === 'missing') continue
        disposeTree(entry.obj)
        if (entry.ghost) disposeTree(entry.ghost)
      }
      cache.clear()
    }
  }, [])

  // Live-apply layout edits (drag/resize/rotate in the editor) and toggle/
  // load-completion changes — content rebuild only, the scene/renderer stay.
  useEffect(() => {
    if (handleRef.current) rebuild(handleRef.current, rooms)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rooms, showModels, showBuilding, bump, lh])

  return (
    <div className="ga-form" style={{ gap: 6 }}>
      <div className="ga-form-section-label">{t('3D preview')}</div>
      <div style={{ display: 'flex', gap: 14, alignItems: 'center', flexWrap: 'wrap' }}>
        <label className="ga-check-row">
          <input type="checkbox" checked={showModels}
            onChange={(e) => setShowModels(e.target.checked)} />
          <span>{t('Real room models')}</span>
        </label>
        <label className="ga-check-row">
          <input type="checkbox" checked={showBuilding}
            onChange={(e) => setShowBuilding(e.target.checked)} />
          <span>{t('Building model overlay')}</span>
        </label>
      </div>
      <div style={{ position: 'relative' }}>
        <div
          ref={mountRef}
          style={{
            width: '100%', height, borderRadius: 8,
            border: '1px solid var(--border, #30363d)',
            background: 'rgba(255, 255, 255, 0.04)', overflow: 'hidden',
          }}
        />
        {loading || error ? (
          <div style={{
            position: 'absolute', inset: 0, display: 'flex', alignItems: 'center',
            justifyContent: 'center', pointerEvents: 'none', fontSize: '0.85em',
            opacity: 0.75, padding: 8, textAlign: 'center',
          }}>
            {error ? `${t('Error')}: ${error}` : t('Loading…')}
          </div>
        ) : null}
      </div>
      <span className="ga-hint">
        {t('Rooms as boxes per level — live while editing the plan; exit points in orange. Rooms without a model keep their box; the building shell renders ghosted.')}
      </span>
    </div>
  )
}
