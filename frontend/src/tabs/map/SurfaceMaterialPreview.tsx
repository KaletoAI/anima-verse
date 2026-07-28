/**
 * SurfaceMaterialPreview — a 10 × 10 m patch of the surface, lit the way the
 * game lights it, with the 1.70 m figure standing on it.
 *
 * It exists because of one dial: `wave_m` is a REAL METRE value, and by this
 * project's rule a metre dial without a reference size is not dialable —
 * nobody can picture "1.6 m between wave crests" in the abstract. Here the
 * ripples run past a person on a square whose edge is stated, so the number
 * means something. The other dials (sky share, roughness, tint) are judged
 * the same way: by looking, not by guessing.
 *
 * The material comes from `surfaceMaterial` — the SAME routine the 3D client
 * and the floor-plan preview use. A preview that painted its own water would
 * be the third implementation of the thing this package exists to unify.
 *
 * three is loaded lazily: the Map tab does not otherwise carry it.
 */
import { useEffect, useRef } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import type { SurfaceMaterialSpec } from './surfaceTypes'

/** Edge of the previewed patch in metres — stated in the caption, because a
 *  wavelength is only judgeable against a known distance. */
const PATCH_M = 10
const FIGURE_M = 1.7

export function SurfaceMaterialPreview({ material, textureUrl, sizeM }: {
  material: SurfaceMaterialSpec | null | undefined
  /** Active version of the kind ('' = none, the tint carries the colour). */
  textureUrl?: string
  /** Physical edge length of that texture in metres (tiling scale). */
  sizeM?: number
}) {
  const { t } = useI18n()
  const mountRef = useRef<HTMLDivElement>(null)
  // Ref, not a dependency: re-running the effect would rebuild the whole
  // scene on every keystroke in a dial.
  const specRef = useRef(material)
  specRef.current = material
  const rebuildRef = useRef<(() => void) | null>(null)

  // Rebuild only the MATERIAL when a dial changes — cheap, and the ripples
  // keep running while you drag a number.
  useEffect(() => { rebuildRef.current?.() }, [material, textureUrl, sizeM])

  useEffect(() => {
    const mount = mountRef.current
    if (!mount) return
    let disposed = false
    const disposers: Array<() => void> = []

    void (async () => {
      const THREE = await import('three')
      const { surfaceMaterial, updateSurfaceMaterials } =
        await import('@anima/scene-render')
      const { referenceFigure } = await import('../world/measureKit')
      if (disposed) return

      const w = mount.clientWidth || 320
      const h = 190
      const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true })
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
      renderer.setSize(w, h)
      renderer.outputColorSpace = THREE.SRGBColorSpace
      mount.appendChild(renderer.domElement)
      disposers.push(() => {
        renderer.dispose()
        renderer.domElement.remove()
      })

      const scene = new THREE.Scene()
      scene.background = new THREE.Color(0x9fc7e8)   // the client's day sky
      // Same three lights as the 3D client, so the specular highlight the
      // roughness dial controls behaves the way it will in the game.
      scene.add(new THREE.HemisphereLight(0xdfeeff, 0x8a9a78, 1.5))
      const sun = new THREE.DirectionalLight(0xfff2d8, 2.0)
      sun.position.set(6, 8, 4)
      scene.add(sun)
      const fill = new THREE.DirectionalLight(0xdde8ff, 0.5)
      fill.position.set(-6, 4, -5)
      scene.add(fill)

      // Low camera: water only shows its sky reflection at a grazing angle,
      // so a top-down preview would hide the very thing being dialled.
      const camera = new THREE.PerspectiveCamera(38, w / h, 0.1, 200)
      camera.position.set(0, 2.4, 8.6)
      camera.lookAt(0, 0.4, 0)

      const geo = new THREE.PlaneGeometry(PATCH_M, PATCH_M)
      geo.rotateX(-Math.PI / 2)
      const plate: import('three').Mesh<
        import('three').BufferGeometry, import('three').Material
      > = new THREE.Mesh(geo, new THREE.MeshStandardMaterial())
      scene.add(plate)
      disposers.push(() => geo.dispose())

      const fig = referenceFigure(THREE, FIGURE_M)
      fig.position.set(-2.6, 0, 2.2)
      scene.add(fig)
      disposers.push(() => {
        fig.traverse((o) => {
          const m = o as unknown as { geometry?: { dispose(): void }
                                      material?: { dispose(): void } }
          m.geometry?.dispose?.()
          m.material?.dispose?.()
        })
      })

      let tex: import('three').Texture | null = null
      const rebuild = () => {
        const old = plate.material
        plate.material = surfaceMaterial(THREE, {
          material: specRef.current, map: tex, color: 0x8fa0a8,
        })
        old.dispose()
      }
      rebuildRef.current = rebuild
      disposers.push(() => {
        rebuildRef.current = null
        plate.material.dispose()
      })

      // The texture tiles at its REAL size, exactly like in the game — a
      // preview at some other tiling would misrepresent the wavelength.
      if (textureUrl) {
        try {
          const loaded = await new THREE.TextureLoader().loadAsync(textureUrl)
          if (disposed) { loaded.dispose(); return }
          loaded.colorSpace = THREE.SRGBColorSpace
          loaded.wrapS = loaded.wrapT = THREE.RepeatWrapping
          const tile = Math.max(sizeM || 3, 0.05)
          loaded.repeat.set(PATCH_M / tile, PATCH_M / tile)
          tex = loaded
          disposers.push(() => loaded.dispose())
        } catch { /* the tint alone is a fine preview */ }
      }
      rebuild()

      let raf = 0
      let last = performance.now()
      const animate = () => {
        raf = requestAnimationFrame(animate)
        const now = performance.now()
        updateSurfaceMaterials(Math.min((now - last) / 1000, 0.1))
        last = now
        renderer.render(scene, camera)
      }
      animate()
      disposers.push(() => cancelAnimationFrame(raf))
    })()

    return () => {
      disposed = true
      for (const d of disposers.reverse()) {
        try { d() } catch { /* teardown is best effort */ }
      }
    }
    // Mount once; dial changes go through rebuildRef.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div>
      <div ref={mountRef} style={{
        width: '100%', maxWidth: 360, height: 190, borderRadius: 6,
        overflow: 'hidden', background: '#0d1117',
      }} />
      <div className="ga-field-hint">
        {t('{n} × {n} m of the surface, with the 1.70 m figure for scale.')
          .replace(/\{n\}/g, String(PATCH_M))}
      </div>
    </div>
  )
}
