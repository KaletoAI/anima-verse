/**
 * SurfaceMaterialPreview — 3 × 3 tiles of the surface, lit the way the game
 * lights it, with the 1.70 m figure standing on it.
 *
 * EVERY kind gets it, not just water. Nine tiles because that is what a
 * tileable texture has to survive: a seam shows at the joins, a too-obvious
 * feature shows as a grid, and neither is visible on a single tile — which is
 * all the list thumbnail ever shows. The figure states the scale, so
 * `size_m` becomes judgeable at the same time ("is that gravel or boulders?").
 *
 * For water it also carries the one dial that made this necessary: `wave_m`
 * is a REAL METRE value, and by this project's rule a metre dial without a
 * reference size is not dialable — nobody can picture "1.6 m between wave
 * crests" in the abstract.
 *
 * The material comes from `surfaceMaterial` — the SAME routine the 3D client
 * and the floor-plan preview use. A preview that painted its own water would
 * be the third implementation of the thing that package exists to unify.
 *
 * three is loaded lazily: the Map tab does not otherwise carry it.
 */
import { useEffect, useRef } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import type { SurfaceMaterialSpec } from './surfaceTypes'

/** How many texture tiles the patch shows per edge. */
const TILES = 3
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
  const sizeMRef = useRef(sizeM)
  sizeMRef.current = sizeM
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
      // so a top-down preview would hide the very thing being dialled. High
      // enough to see all nine tiles at once — that is what the joins are for.
      const camera = new THREE.PerspectiveCamera(38, w / h, 0.1, 500)

      // A UNIT plate, scaled per rebuild: the patch is TILES × size_m, and
      // size_m is editable while this is on screen.
      const geo = new THREE.PlaneGeometry(1, 1)
      geo.rotateX(-Math.PI / 2)
      const plate: import('three').Mesh<
        import('three').BufferGeometry, import('three').Material
      > = new THREE.Mesh(geo, new THREE.MeshStandardMaterial())
      scene.add(plate)
      disposers.push(() => geo.dispose())

      const fig = referenceFigure(THREE, FIGURE_M)
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
        const tile = Math.max(sizeMRef.current || 3, 0.05)
        const patch = TILES * tile
        plate.scale.set(patch, 1, patch)
        // The figure stands at the front-left corner, a step inside the patch.
        fig.position.set(-patch * 0.34, 0, patch * 0.3)
        // Frame the whole patch from a low angle; both grow with it.
        camera.position.set(0, patch * 0.26, patch * 0.92)
        camera.lookAt(0, FIGURE_M * 0.25, 0)
        if (tex) tex.repeat.set(TILES, TILES)
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

      // Exactly TILES × TILES repetitions — the joins are the point: a seam
      // or a too-obvious feature shows there and nowhere else.
      if (textureUrl) {
        try {
          const loaded = await new THREE.TextureLoader().loadAsync(textureUrl)
          if (disposed) { loaded.dispose(); return }
          loaded.colorSpace = THREE.SRGBColorSpace
          loaded.wrapS = loaded.wrapT = THREE.RepeatWrapping
          loaded.repeat.set(TILES, TILES)
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

  const patchM = TILES * Math.max(sizeM || 3, 0.05)
  return (
    <div>
      <div ref={mountRef} style={{
        width: '100%', height: 230, borderRadius: 6,
        overflow: 'hidden', background: '#0d1117',
      }} />
      <div className="ga-field-hint">
        {t('{t} × {t} tiles = {m} × {m} m, with the 1.70 m figure for scale — '
          + 'seams and repeating features show at the joins.')
          .replace(/\{t\}/g, String(TILES))
          .replace(/\{m\}/g, patchM.toFixed(patchM < 10 ? 1 : 0))}
      </div>
    </div>
  )
}
