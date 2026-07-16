/**
 * FloorPlanPreview — live 3D preview of the room layout (AV3D-2), shown next
 * to the floor-plan editor. Renders the building footprint as a ground plate
 * and every laid-out room as a translucent box on its level (stacked floors,
 * basements below ground), with name labels and the exit point as an orange
 * dot — the same data the external 3D client reads, so what you see here is
 * what the client will place. Rebuilds the boxes live while dragging in the
 * editor (the three.js scene itself is created once).
 *
 * three.js is imported dynamically, same as Model3DViewer — it stays in the
 * shared chunk that only loads when a 3D view is opened.
 */
import { useEffect, useRef, useState } from 'react'
import type { Object3D, Group, Material, Mesh } from 'three'
import { useI18n } from '../../i18n/I18nProvider'
import type { Room } from './worldTypes'

const LEVEL_H = 0.3
const PALETTE = [0x58a6ff, 0x3fb950, 0xd29922, 0xf778ba,
                 0xa371f7, 0xf85149, 0x79c0ff, 0x56d364]

interface FloorPlanPreviewProps {
  rooms: Room[]
  /** Building footprint in grid cells (map3d.footprint) — plate aspect. */
  footprint?: number[]
  height?: number
}

export function FloorPlanPreview({ rooms, footprint, height = 360 }: FloorPlanPreviewProps) {
  const { t } = useI18n()
  const mountRef = useRef<HTMLDivElement>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  // Scene handle for the incremental room-box rebuild (drag updates arrive
  // per pointermove — recreating the whole renderer would thrash).
  const handleRef = useRef<{
    THREE: typeof import('three')
    boxes: Group
  } | null>(null)
  const roomsRef = useRef(rooms)
  roomsRef.current = rooms

  const fw = Math.max(1, footprint?.[0] || 1)
  const fd = Math.max(1, footprint?.[1] || 1)

  // Rebuild the room boxes from the current layout (called on every rooms
  // change and once after scene init).
  const rebuild = (h: NonNullable<typeof handleRef.current>, current: Room[]) => {
    const { THREE, boxes } = h
    for (const child of [...boxes.children]) {
      boxes.remove(child)
      child.traverse((o: Object3D) => {
        const mesh = o as Mesh
        mesh.geometry?.dispose?.()
        const m = mesh.material as Material | Material[] | undefined
        if (Array.isArray(m)) m.forEach((x) => x.dispose?.())
        else m?.dispose?.()
      })
    }
    current.forEach((room, idx) => {
      const lay = room.layout
      if (!lay) return
      const color = PALETTE[idx % PALETTE.length]
      const w = lay.w * fw
      const d = lay.d * fd
      const level = lay.level || 0
      const cy = level * LEVEL_H + LEVEL_H / 2
      const cx = (lay.x + lay.w / 2 - 0.5) * fw
      const cz = (lay.y + lay.d / 2 - 0.5) * fd

      const box = new THREE.Mesh(
        new THREE.BoxGeometry(w, LEVEL_H * 0.94, d),
        new THREE.MeshStandardMaterial({ color, transparent: true, opacity: 0.5 }),
      )
      const edges = new THREE.LineSegments(
        new THREE.EdgesGeometry(box.geometry),
        new THREE.LineBasicMaterial({ color }),
      )
      const roomGroup = new THREE.Group()
      roomGroup.add(box)
      roomGroup.add(edges)

      if (lay.exit) {
        const dot = new THREE.Mesh(
          new THREE.SphereGeometry(Math.min(fw, fd) * 0.02, 12, 12),
          new THREE.MeshBasicMaterial({ color: 0xe0a356 }),
        )
        dot.position.set((lay.exit[0] - 0.5) * w, -LEVEL_H * 0.4, (lay.exit[1] - 0.5) * d)
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
      sprite.position.y = LEVEL_H * 0.62
      roomGroup.add(sprite)

      roomGroup.position.set(cx, cy, cz)
      if (lay.rotation) roomGroup.rotation.y = (-(lay.rotation) * Math.PI) / 180
      boxes.add(roomGroup)
    })
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
        const extent = Math.max(fw, fd, LEVEL_H * 4)
        const dist = (extent / 2) / Math.tan((Math.PI * camera.fov) / 360) * 1.5
        camera.position.set(dist * 0.7, dist * 0.75, dist * 0.85)
        controls.target.set(0, LEVEL_H, 0)
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

  // Live-apply layout edits (drag/resize/rotate in the editor) — box rebuild
  // only, the scene/renderer stay.
  useEffect(() => {
    if (handleRef.current) rebuild(handleRef.current, rooms)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rooms])

  return (
    <div className="ga-form" style={{ gap: 6 }}>
      <div className="ga-form-section-label">{t('3D preview')}</div>
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
        {t('Rooms as boxes per level — live while editing the plan; exit points in orange.')}
      </span>
    </div>
  )
}
