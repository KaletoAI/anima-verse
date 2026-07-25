/**
 * FloorPlanPreview — live 3D preview of the room layout (AV3D-2), shown next
 * to the floor-plan editor. Since v4 it is CONSUMER No. 1 of the server's
 * scene recipe (shared/schnittstellen-3d.md part B): the current editor
 * draft goes to POST /play/scene-preview and what comes back is rendered as
 * it is — plates, walls, extras, model placement specs, figures, markers and
 * exits, all in world metres around the tile centre.
 *
 * That means: NO geometry decision lives here any more. Wall thickness, door
 * gaps, fit factors, storey heights, figure scale and the colour vocabulary
 * all come from the payload; this file only builds boxes, extruded polygons
 * and meshes from it. Anything that stays is view state — camera, toggles,
 * level solo, culling, labels, texture tiling, clip retargeting.
 *
 * Two compare switches: "Real room models" swaps the level boxes for the
 * rooms' ACTIVE models (rooms without one keep their box), "Building model
 * overlay" ghosts the location's building model over the plan. Models are
 * fetched once and cached; the scene rebuilds live while dragging in the
 * editor (the three.js scene itself is created once). three.js is imported
 * dynamically — it stays in the shared chunk.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import type { AnimationClip, AnimationMixer, Clock, Group, Material, Mesh, Object3D, Texture } from 'three'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPost } from '../../lib/api'
import { getBuildingDims, notifyModel3dChanged } from './topDownSnapshot'
import { useToast } from '../../lib/Toast'
import type { Map3D, Room, SceneModelSpec, ScenePayload } from './worldTypes'

// The reference square (8 m) is the preview's own stage — ground plate,
// ruler position and camera framing. Every DERIVED length comes from the
// scene payload.
const PLATE_M = 8
const DEFAULT_LEVEL_M = 3
// The ONE geometry number that stays on this side: contract § B2 puts the
// 0.96 fit margin into the client's place() routine (fit_box fallback).
const FIT_BOX_MARGIN = 0.96
// Preview AIDS — deliberately NOT part of the scene style (which covers
// walls, floors, glass and the room palette): these paint things only the
// admin preview shows. Elevator metal has no colour in the contract yet.
const AID = {
  exit: 0xe0a356,
  marker: 0x3fb950,
  markerLabel: '#7ee2a0',
  placeholder: 0xd29922,
  figure: 0x8b949e,
  elevatorMetal: 0x6d7681,
  elevatorPad: 0xaab4be,
  elevatorCabin: 0x3d4650,
  ruler: 0xc9d1d9,
}

interface CachedModel {
  obj: Object3D
  rotation: { x?: number; y?: number; z?: number }
  /** Vertical placement offset in metres (negative sinks it). */
  offsetY: number
  /** Tile-plane shift in world metres (after the yaw): +x east, +z south —
   *  buildings only (rooms are positioned by their layout rect). */
  offsetX?: number
  offsetZ?: number
  /** Detail-view scale anchors (0 = undeclared): buildings carry
   *  floors (storeys the mesh depicts) + heightM (world metres, uniform
   *  scale target; storey height derives as heightM / floors), rooms
   *  carry widthM (real-world width of the largest side; content scale =
   *  rect extent / widthM, figures in the room derive from it). */
  floors: number
  heightM: number
  widthM: number
  /** Prepared once on first overlay use: the model with its own textures on
   *  unlit, semi-transparent materials — visibly the building, still
   *  see-through. Scene inserts clones of this (shared materials). */
  ghost?: Object3D
}
type CacheEntry = CachedModel | 'loading' | 'missing'

interface FloorPlanPreviewProps {
  locationId: string
  rooms: Room[]
  /** map3d draft — outline/elevator (AV3D-12) are drawn from it. */
  map3d?: Map3D
  /** Storey height in metres (map3d.level_height) — empty = the contract's 3. */
  levelHeightM?: number
  /** When set, the toolbar shows a level-height field next to the metre
   *  scale (writes map3d.level_height on the location draft). */
  onLevelHeight?: (v: number | undefined) => void
  /** When set, the toolbar shows the plan-width anchor field (writes
   *  map3d.plan_width_m on the location draft). */
  onPlanWidth?: (v: number | undefined) => void
  /** The 2D icon rotation (map_rotation_2d) — the contract's yaw fallback
   *  when map3d.rotation is unset (the model turns with the 2D icon). */
  fallbackYawDeg?: number
  /** The server-composed scene of the current draft (useScenePreview in the
   *  parent — the 2D editor reads the same response). null = not there yet
   *  or the composer failed; then there is nothing to render. */
  scene: ScenePayload | null
  sceneError?: string
  height?: number
}

export function FloorPlanPreview({ locationId, rooms, map3d, levelHeightM, onLevelHeight, onPlanWidth, fallbackYawDeg = 0, scene, sceneError = '', height = 540 }: FloorPlanPreviewProps) {
  const { t } = useI18n()
  const mountRef = useRef<HTMLDivElement>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [showModels, setShowModels] = useState(false)
  const [showBuilding, setShowBuilding] = useState(false)
  // "Walls & floor" overlay — the client's render recipe (schnittstellen
  // → "Render-Rezept Wände & Boden"): outline floor plates + outer walls
  // with door gaps at the ground-floor exits.
  const [showWalls, setShowWalls] = useState(false)
  // Exclusive level view: null = all levels, a number renders ONLY that
  // storey (rooms, plates, walls, figures) — the ruler and the building
  // overlay stay, the elevator shaft only shows with all levels visible.
  const [soloLevel, setSoloLevel] = useState<number | null>(null)
  // Model-load completion re-triggers the rebuild (loads are async, the
  // rebuild itself is synchronous against the cache).
  const [bump, setBump] = useState(0)
  // Scene handle for the incremental rebuild (drag updates arrive per
  // pointermove — recreating the whole renderer would thrash).
  const handleRef = useRef<{
    THREE: typeof import('three')
    boxes: Group
    skclone: (obj: Object3D) => Object3D
  } | null>(null)
  const roomsRef = useRef(rooms)
  roomsRef.current = rooms
  const showModelsRef = useRef(showModels)
  showModelsRef.current = showModels
  const showBuildingRef = useRef(showBuilding)
  showBuildingRef.current = showBuilding
  const showWallsRef = useRef(showWalls)
  showWallsRef.current = showWalls
  const soloLevelRef = useRef(soloLevel)
  soloLevelRef.current = soloLevel
  // Wall pieces for the per-frame camera culling (a wall whose OUTSIDE
  // faces the camera hides, so the interior stays visible — recipe rule).
  const wallCullRef = useRef<Array<{
    mesh: Object3D; mx: number; mz: number; nx: number; nz: number }>>([])
  // Loaded models by key ("room:<id>" / "building") — originals live here,
  // the scene gets clones (shared geometry, nothing to dispose per rebuild).
  const cacheRef = useRef<Map<string, CacheEntry>>(new Map())
  const map3dRef = useRef(map3d)
  map3dRef.current = map3d
  // Mixamo TEST FIGURE (any humanoid character model the server offers) +
  // animation clips per kind — markers show a real animated figure; without
  // figure/clip the mannequin stays the fallback.
  const figRef = useRef<{ status: 'idle' | 'loading' | 'ready' | 'missing'; obj?: Object3D }>({ status: 'idle' })
  // Surface textures per kind: the /assets listing (url + real tiling size)
  // plus lazily loaded THREE textures — walls/floors sample them real-scale.
  const surfaceListRef = useRef<{ status: 'idle' | 'loading' | 'ready'
    map: Map<string, { url: string; sizeM: number }> }>(
    { status: 'idle', map: new Map() })
  const surfaceTexRef = useRef<Map<string, unknown>>(new Map())
  const clipListRef = useRef<{ status: 'idle' | 'loading' | 'ready' | 'missing'
    clips: Array<{ kind: string; set: string; url: string }> }>({ status: 'idle', clips: [] })
  const clipCacheRef = useRef<Map<string, { clip: AnimationClip; restObj: Object3D } | 'loading' | 'missing'>>(new Map())
  const mixersRef = useRef<AnimationMixer[]>([])
  const clockRef = useRef<Clock | null>(null)

  const lh = levelHeightM && levelHeightM > 0 ? levelHeightM : DEFAULT_LEVEL_M

  // The whole geometry arrives from the server (contract § B1/B3) — the
  // parent holds the debounced draft request, this component only renders.
  const sceneRef = useRef<ScenePayload | null>(null)
  sceneRef.current = scene

  // Mesh width-per-height ratio via the SHARED helper (same value the
  // layout editor uses) — auto plan width = declared height × this ratio
  // when no explicit plan_width_m is set.
  const wphRef = useRef(0)
  useEffect(() => {
    let stale = false
    getBuildingDims(locationId)
      .then((d) => {
        if (!stale && d) {
          wphRef.current = d.widthPerHeight
          setBump((b) => b + 1)
        }
      })
      .catch(() => undefined)
    return () => { stale = true }
  }, [locationId])

  // ANY model mutation anywhere (panel, adjust strip, preview toolbar)
  // invalidates the module caches and lands here: drop our cached entry
  // and refetch — everything derived recomputes on the next rebuild.
  useEffect(() => {
    const onChanged = (e: Event) => {
      const det = (e as CustomEvent).detail as { locationId?: string; roomId?: string }
      if (det?.roomId) {
        cacheRef.current.delete(`room:${det.roomId}`)
      }
      if (det?.locationId === locationId) {
        cacheRef.current.delete('building')
        getBuildingDims(locationId)
          .then((d) => { if (d) wphRef.current = d.widthPerHeight; setBump((b) => b + 1) })
          .catch(() => undefined)
      }
      setBump((b) => b + 1)
    }
    window.addEventListener('anima-model3d-changed', onChanged)
    return () => window.removeEventListener('anima-model3d-changed', onChanged)
  }, [locationId])

  // Active building model in the cache (re-read on every bump-triggered
  // render) — feeds the "Model storeys" field in the toolbar.
  const bEntryRaw = cacheRef.current.get('building')
  const buildingEntry = bEntryRaw && bEntryRaw !== 'loading' && bEntryRaw !== 'missing'
    ? bEntryRaw : null

  const { toast } = useToast()
  const commitBuildingFloors = (raw: string) => {
    const n = parseFloat(raw)
    const floors = Number.isFinite(n) && n > 0 ? n : 0
    if (!buildingEntry || floors === buildingEntry.floors) return
    void apiPost<{ meta?: { floors?: number } }>(
      `/world/locations/${encodeURIComponent(locationId)}/model3d/floors`,
      { floors })
      .then(() => notifyModel3dChanged({ locationId }))
      .catch((e) => toast(t('Error') + ': ' + (e as Error).message, 'error'))
  }
  const commitBuildingHeight = (raw: string) => {
    const n = parseFloat(raw)
    const heightM = Number.isFinite(n) && n > 0 ? n : 0
    if (!buildingEntry || heightM === buildingEntry.heightM) return
    void apiPost<{ meta?: { height_m?: number } }>(
      `/world/locations/${encodeURIComponent(locationId)}/model3d/height`,
      { height_m: heightM })
      .then(() => notifyModel3dChanged({ locationId }))
      .catch((e) => toast(t('Error') + ': ' + (e as Error).message, 'error'))
  }
  // Storey height derived from the building anchors — shown as the
  // level-height placeholder (the manual value is only the fallback).
  const lhDerived = buildingEntry && buildingEntry.heightM > 0 && buildingEntry.floors > 0
    ? buildingEntry.heightM / buildingEntry.floors
    : 0
  // Plan width auto-derived from the building model (declared height × the
  // mesh's width-per-height ratio) — the placeholder AND the anchor check.
  const pwDerived = buildingEntry && buildingEntry.heightM > 0 && wphRef.current > 0
    ? buildingEntry.heightM * wphRef.current
    : 0
  // No anchor at all: neither an explicit value nor a model to derive one
  // from. The field is mandatory then (Abnahme round 4) — a silent 0 sends
  // the 3D client into its legacy 24 m fallback.
  const anchorMissing = !(map3d?.plan_width_m && map3d.plan_width_m > 0) && pwDerived <= 0

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
          offset_y?: number; offset_x?: number; offset_z?: number
          floors?: number
          height_m?: number; width_m?: number }>(`${base}/meta`)
        const fmt = (meta.format || 'glb').toLowerCase()
        if (fmt !== 'glb' && fmt !== 'gltf') throw new Error(`format ${fmt}`)
        const { GLTFLoader } = await import('three/examples/jsm/loaders/GLTFLoader.js')
        const gltf = await new GLTFLoader().loadAsync(meta.url || base)
        cache.set(key, { obj: gltf.scene, rotation: meta.rotation || {},
                         offsetY: meta.offset_y || 0,
                         offsetX: meta.offset_x || 0,
                         offsetZ: meta.offset_z || 0,
                         floors: meta.floors || 0,
                         heightM: meta.height_m || 0,
                         widthM: meta.width_m || 0 })
      } catch {
        cache.set(key, 'missing')  // 404 = no model — the box stays
      }
      setBump((b) => b + 1)
    })()
    return null
  }

  // Test figure + clip loaders (async → bump; rebuild stays synchronous).
  const ensureTestFigure = (): Object3D | null => {
    const f = figRef.current
    if (f.status === 'ready') return f.obj || null
    if (f.status !== 'idle') return null
    figRef.current = { status: 'loading' }
    ;(async () => {
      try {
        // Preferred: a Mixamo STANDARD character (X Bot & Co.) the admin
        // dropped into shared/models/figure/ — FBX or GLB; fallback is the
        // first humanoid character model. The meta names the format.
        const meta = await apiGet<{ format?: string }>('/play/test-figure/meta')
        let obj: Object3D
        if ((meta.format || 'glb') === 'fbx') {
          const { FBXLoader } = await import('three/examples/jsm/loaders/FBXLoader.js')
          obj = await new FBXLoader().loadAsync('/play/test-figure/model')
        } else {
          const { GLTFLoader } = await import('three/examples/jsm/loaders/GLTFLoader.js')
          obj = (await new GLTFLoader().loadAsync('/play/test-figure/model')).scene
        }
        // NEUTRAL example figure: strip any textures/materials to one flat
        // clay-gray material — the preview judges placement and scale, not
        // a specific look. Replaced ONCE on the cached source; the
        // skeleton clones share the material.
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
        figRef.current = { status: 'ready', obj }
      } catch {
        figRef.current = { status: 'missing' }  // no figure → mannequin
      }
      setBump((b) => b + 1)
    })()
    return null
  }
  const ensureClip = (kind: string) => {
    const idx = clipListRef.current
    if (idx.status === 'idle') {
      clipListRef.current = { status: 'loading', clips: [] }
      apiGet<{ clips?: Array<{ kind: string; set: string; url: string }> }>('/assets/animation-clips')
        .then((d) => {
          clipListRef.current = { status: 'ready', clips: d.clips || [] }
          setBump((b) => b + 1)
        })
        .catch(() => { clipListRef.current = { status: 'missing', clips: [] } })
      return null
    }
    if (idx.status !== 'ready') return null
    const cached = clipCacheRef.current.get(kind)
    if (cached === 'loading' || cached === 'missing') return null
    if (cached) return cached
    // Prefer a set-less clip, then female, then anything of the kind.
    const of = idx.clips.filter((c) => c.kind === kind)
    const pick = of.find((c) => !c.set) || of.find((c) => c.set === 'female') || of[0]
    if (!pick) {
      clipCacheRef.current.set(kind, 'missing')
      return null
    }
    clipCacheRef.current.set(kind, 'loading')
    ;(async () => {
      try {
        const { FBXLoader } = await import('three/examples/jsm/loaders/FBXLoader.js')
        const clipObj = await new FBXLoader().loadAsync(pick.url)
        const clip = clipObj.animations?.[0]
        if (!clip) throw new Error('no track')
        // Play IN PLACE — drop the root/hips position track (clip units are
        // Mixamo centimetres; it would fling the scaled figure around).
        clip.tracks = clip.tracks.filter(
          (tr) => !(/hips/i.test(tr.name) && tr.name.endsWith('.position')))
        clipCacheRef.current.set(kind, { clip, restObj: clipObj })
      } catch {
        clipCacheRef.current.set(kind, 'missing')
      }
      setBump((b) => b + 1)
    })()
    return null
  }

  // Rebuild the plan content from the current layout (called on every rooms/
  // toggle change and once after scene init).
  const rebuild = (h: NonNullable<typeof handleRef.current>, current: Room[]) => {
    const { THREE, boxes } = h
    // Exclusive level view: everything level-bound derives from the
    // filtered list (plates and walls follow via usedLevels).
    const solo = soloLevelRef.current
    if (solo !== null) {
      current = current.filter((r) => (r.layout?.level || 0) === solo)
    }
    // Scalars come FROM THE PAYLOAD (contract § A1): k = world metres per
    // real metre, storey_m = the derived storey height. Until the first
    // response arrives the preview stands on the unscaled defaults.
    const sc = sceneRef.current
    const kFac = sc ? sc.k : 1
    const lhEff = sc ? sc.storey_m : lh
    const style = sc?.style
    const figBase = sc ? sc.figures.base_height_m_world : 1.7
    // Hex colour of the payload style ('#rrggbb' → three.js number).
    const hex = (c: string | undefined, fallback: number): number => {
      const v = parseInt((c || '').replace('#', ''), 16)
      return Number.isFinite(v) ? v : fallback
    }
    const visibleLevel = (lv: number) => solo === null || lv === solo
    // The building entry is fetched regardless of the overlay toggle — the
    // model panel's fields read it.
    const bAnchor = ensureModel('building')
    for (const mixer of mixersRef.current) mixer.stopAllAction()
    mixersRef.current = []
    // Recursive disposal that BAILS on __noDispose subtrees — cached-model
    // and test-figure clones share geometry/materials with their caches
    // (a plain traverse would visit and kill the shared resources).
    const disposeSafe = (o: Object3D) => {
      if (o.userData.__noDispose) return
      const mesh = o as Mesh
      mesh.geometry?.dispose?.()
      const m = mesh.material as Material | Material[] | undefined
      // Per-mesh texture CLONES (tiled walls/floors) and the label
      // CanvasTextures die with their material — the shared caches sit in
      // __noDispose subtrees and are never visited.
      const disposeMat = (x: Material) => {
        (x as Material & { map?: Texture | null }).map?.dispose?.()
        x.dispose?.()
      }
      if (Array.isArray(m)) m.forEach(disposeMat)
      else if (m) disposeMat(m)
      for (const c of o.children) disposeSafe(c)
    }
    for (const child of [...boxes.children]) {
      boxes.remove(child)
      disposeSafe(child)
    }

    const deg = (v?: number) => ((v || 0) * Math.PI) / 180

    // ── THE placement routine (contract § B2) ──────────────────────────
    // Building, room diorama and prop differ only in the SPEC the server
    // sends — never in code. Chain: fix_euler ('XYZ') on the inner group →
    // measure → scale per scale_mode → yaw as the PARENT rotation (never
    // combined into one Euler, an x/z fix would tilt with it) → measure the
    // result and seat its BBox on bottom_y / anchor.
    const placeSpec = (source: Object3D, spec: SceneModelSpec): Object3D => {
      const fix = new THREE.Group()
      fix.add(source.clone(true))
      fix.rotation.set(deg(spec.fix_euler?.x), deg(spec.fix_euler?.y),
                       deg(spec.fix_euler?.z))
      fix.updateMatrixWorld(true)
      const sFix = new THREE.Box3().setFromObject(fix).getSize(new THREE.Vector3())

      const yawG = new THREE.Group()
      yawG.add(fix)
      yawG.rotation.y = -deg(spec.yaw_deg)
      yawG.updateMatrixWorld(true)
      const sYaw = new THREE.Box3().setFromObject(yawG).getSize(new THREE.Vector3())

      const outer = new THREE.Group()
      outer.add(yawG)
      if (spec.scale_axes) {
        // Server-measured mesh: the factors come ready (contract § B4).
        outer.scale.set(spec.scale_axes.xz, spec.scale_axes.y, spec.scale_axes.xz)
      } else if (spec.scale_mode === 'tile_fit') {
        // Buildings fill their tile per AXIS, measured on the ROTATED box:
        // the footprint follows the plan, the height its declared metres.
        const kxz = (spec.box?.xz || 1) / (Math.max(sYaw.x, sYaw.z) || 1)
        const ky = spec.box?.y ? spec.box.y / (sYaw.y || 1) : kxz
        outer.scale.set(kxz, ky, kxz)
      } else if (spec.scale_mode === 'real_size') {
        // ONE law of scale: real metres over the largest measured extent.
        // measure_axes 'xz' ignores the height (dioramas, § B2a).
        const maxExtent = (spec.measure_axes === 'xz'
          ? Math.max(sFix.x, sFix.z)
          : Math.max(sFix.x, sFix.y, sFix.z)) || 1
        outer.scale.setScalar((spec.max_m || 1) / maxExtent)
      } else {
        // fit_box fallback: fit the UNROTATED footprint into the target box.
        outer.scale.setScalar(Math.min((spec.box?.w || 1) / (sFix.x || 1),
                                       (spec.box?.d || 1) / (sFix.z || 1))
                              * FIT_BOX_MARGIN)
      }
      outer.updateMatrixWorld(true)
      const bOut = new THREE.Box3().setFromObject(outer)
      const cOut = bOut.getCenter(new THREE.Vector3())
      outer.position.set(spec.anchor[0] - cOut.x,
                         spec.bottom_y - bOut.min.y,
                         spec.anchor[1] - cOut.z)
      outer.userData.__noDispose = true
      boxes.add(outer)
      return outer
    }

    // Prop meshes by id — the URL comes from the spec, everything else about
    // the prop (fix, size, placeholder) is already in it.
    const ensurePropModel = (propId: string, url: string): CachedModel | null => {
      const key = `prop:${propId}`
      const cur = cacheRef.current.get(key)
      if (cur === 'loading' || cur === 'missing') return null
      if (cur) return cur
      cacheRef.current.set(key, 'loading')
      ;(async () => {
        try {
          const { GLTFLoader } = await import('three/examples/jsm/loaders/GLTFLoader.js')
          const gltf = await new GLTFLoader().loadAsync(url)
          cacheRef.current.set(key, { obj: gltf.scene, rotation: {},
            offsetY: 0, floors: 0, heightM: 0, widthM: 0 })
        } catch {
          cacheRef.current.set(key, 'missing')
        }
        setBump((b) => b + 1)
      })()
      return null
    }
    // ── Surface textures: real-scale sampling for walls + room floors ──
    const ensureSurfaceList = (): boolean => {
      const s = surfaceListRef.current
      if (s.status !== 'idle') return s.status === 'ready'
      s.status = 'loading'
      apiGet<Array<{ kind?: string; url?: string; size_m?: number }>>(
        '/assets/surface-textures')
        .then((list) => {
          for (const entry of Array.isArray(list) ? list : []) {
            if (entry?.kind && entry.url)
              s.map.set(entry.kind, { url: entry.url, sizeM: entry.size_m || 1 })
          }
        })
        .catch(() => {})
        .finally(() => { s.status = 'ready'; setBump((b) => b + 1) })
      return false
    }
    // Loaded texture (RepeatWrapping, sRGB) + its real-world tile size, or
    // null while loading / when the kind has no texture (color hint stays).
    const ensureSurfaceTex = (kind: string): { tex: unknown; sizeM: number } | null => {
      if (!ensureSurfaceList()) return null
      const info = surfaceListRef.current.map.get(kind)
      if (!info) return null
      const cache = surfaceTexRef.current
      const cur = cache.get(kind) as { tex: unknown; sizeM: number } | 'loading' | undefined
      if (cur === 'loading') return null
      if (cur) return cur
      cache.set(kind, 'loading')
      new THREE.TextureLoader().load(info.url, (tex) => {
        tex.wrapS = THREE.RepeatWrapping
        tex.wrapT = THREE.RepeatWrapping
        tex.colorSpace = THREE.SRGBColorSpace
        cache.set(kind, { tex, sizeM: info.sizeM })
        setBump((b) => b + 1)
      }, undefined, () => cache.set(kind, { tex: null, sizeM: info.sizeM }))
      return null
    }

    // ── Figures ────────────────────────────────────────────────────────
    // ONE figure routine for markers and the comparison figure: the real
    // Mixamo test figure with the requested clip, else the mannequin. Height
    // is ALWAYS figures.base_height_m_world from the payload — the figure is
    // the fixed reference, it never scales with a slider. World coordinates,
    // bottom seated on `y`; `facing` is the world compass (0 = south).
    const placeFigure = (opts: { x: number; y: number; z: number
                                 animation?: string; facing?: number
                                 label?: string }) => {
      const fig = new THREE.Group()
      const figSrc = ensureTestFigure()
      const kinds = clipListRef.current.clips.map((c) => c.kind)
      const kind = opts.animation
        || (kinds.includes('idle') ? 'idle' : kinds.includes('stand') ? 'stand' : kinds[0])
      const anim = figSrc && kind ? ensureClip(kind) : null
      if (figSrc && anim) {
        const inst = h.skclone(figSrc)
        const pivot = new THREE.Group()
        pivot.add(inst)
        // Up-axis fix measured on the REST skeletons (never the animated
        // pose) — same logic as the model viewer.
        const hipsOf = (root: Object3D): Object3D | null => {
          let found: Object3D | null = null
          root.traverse((o) => { if (!found && /hips/i.test(o.name)) found = o })
          return found
        }
        const modelHips = hipsOf(inst)
        const clipHips = hipsOf(anim.restObj)
        if (modelHips?.parent && clipHips?.parent) {
          inst.updateMatrixWorld(true)
          anim.restObj.updateMatrixWorld(true)
          const restModel = modelHips.parent.getWorldQuaternion(new THREE.Quaternion())
          const restClip = clipHips.parent.getWorldQuaternion(new THREE.Quaternion())
          let bestRx = 0
          let bestAngle = Infinity
          for (const rx of [0, Math.PI / 2, -Math.PI / 2, Math.PI]) {
            const cand = new THREE.Quaternion()
              .setFromEuler(new THREE.Euler(rx, 0, 0)).multiply(restModel)
            const angle = cand.angleTo(restClip)
            if (angle < bestAngle) { bestAngle = angle; bestRx = rx }
          }
          pivot.rotation.x = bestRx
        }
        // BODY size comes from the REST pose (standing T-pose) — the posed
        // bbox would blow lying/sitting figures up (a lying box is ~half as
        // tall, so the figure came out ~twice as large).
        pivot.updateMatrixWorld(true)
        const fs = new THREE.Box3().setFromObject(pivot).getSize(new THREE.Vector3())
        const mixer = new THREE.AnimationMixer(inst)
        mixer.clipAction(anim.clip).play()
        mixer.update(0)
        mixersRef.current.push(mixer)
        pivot.scale.setScalar(figBase / (fs.y || 1))
        // Grounding DOES use the posed bounds — a lying figure rests on the
        // floor, not on where its feet would be standing.
        pivot.updateMatrixWorld(true)
        const fb2 = new THREE.Box3().setFromObject(pivot)
        const fc2 = fb2.getCenter(new THREE.Vector3())
        pivot.position.set(-fc2.x, -fb2.min.y, -fc2.z)
        pivot.userData.__noDispose = true
        fig.add(pivot)
      } else {
        // Mannequin fallback while figure/clip load (or are missing) — same
        // height as the real figure would be.
        const tgt = figBase
        const figMat = new THREE.MeshStandardMaterial({
          color: opts.animation ? AID.marker : AID.figure,
          transparent: true, opacity: 0.85,
        })
        const body = new THREE.Mesh(
          new THREE.CapsuleGeometry(0.055 * tgt, 0.62 * tgt, 4, 10), figMat)
        body.position.y = 0.42 * tgt
        fig.add(body)
        const head = new THREE.Mesh(
          new THREE.SphereGeometry(0.09 * tgt, 12, 12), figMat)
        head.position.y = 0.88 * tgt
        fig.add(head)
        // Facing nose — only when a facing is set (0 = south/+Z, 90 = east/+X;
        // unset = the client decides, so the preview stays direction-less).
        if (opts.facing !== undefined) {
          const nose = new THREE.Mesh(
            new THREE.ConeGeometry(0.05 * tgt, 0.16 * tgt, 10), figMat)
          nose.rotation.x = Math.PI / 2
          nose.position.set(0, 0.74 * tgt, 0.14 * tgt)
          fig.add(nose)
        }
      }
      if (opts.facing !== undefined) fig.rotation.y = deg(opts.facing)
      if (opts.label) {
        const mc = document.createElement('canvas')
        mc.width = 128
        mc.height = 40
        const mctx = mc.getContext('2d')
        if (mctx) {
          mctx.font = '600 22px sans-serif'
          mctx.textAlign = 'center'
          mctx.textBaseline = 'middle'
          mctx.shadowColor = 'rgba(0,0,0,0.9)'
          mctx.shadowBlur = 5
          mctx.fillStyle = AID.markerLabel
          mctx.fillText(opts.label.slice(0, 14), 64, 20)
        }
        const msprite = new THREE.Sprite(new THREE.SpriteMaterial({
          map: new THREE.CanvasTexture(mc), transparent: true, depthTest: false,
        }))
        msprite.scale.set(1.3, 0.4, 1)
        msprite.position.y = figBase * 1.15
        fig.add(msprite)
      }
      fig.position.set(opts.x, opts.y, opts.z)
      boxes.add(fig)
      return fig
    }

    // ── Models (contract § B2): every mesh through the ONE routine ──────
    // Which meshes exist and where they go is the payload's business; the
    // toggles only decide what is SHOWN.
    // Top of the placed building shell — the metre ruler reaches up to it.
    let buildingTopY = 0
    const roomsWithModel = new Set(
      (sc?.models || []).filter((m) => m.role === 'room').map((m) => m.room_id))
    for (const spec of sc?.models || []) {
      if (!visibleLevel(spec.level)) continue
      if (spec.role === 'building') {
        if (!showBuildingRef.current || !bAnchor) continue
        if (!bAnchor.ghost) {
          // Keep the model's own textures — a flat gray ghost was near
          // invisible on the dark canvas. Unlit (basic) + semi-transparent +
          // no depth write: clearly the building, rooms shine through.
          const g = bAnchor.obj.clone(true)
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
          bAnchor.ghost = g
        }
        const placed = placeSpec(bAnchor.ghost, spec)
        placed.updateMatrixWorld(true)
        const bb = new THREE.Box3().setFromObject(placed)
        buildingTopY = bb.max.y
        continue
      }
      if (spec.role === 'room') {
        if (!showModelsRef.current) continue
        const entry = ensureModel(`room:${spec.id}`, spec.id)
        if (entry) placeSpec(entry.obj, spec)
        continue
      }
      // Props: the mesh when there is one, else the payload's placeholder
      // box (dims × k, already world metres) — a placement is never dropped.
      const entry = spec.url ? ensurePropModel(spec.id, spec.url) : null
      if (entry) {
        placeSpec(entry.obj, spec)
      } else if (spec.placeholder_dims) {
        const dims = spec.placeholder_dims
        const standIn = new THREE.Mesh(
          new THREE.BoxGeometry(dims.w, dims.h, dims.d),
          new THREE.MeshBasicMaterial({ color: AID.placeholder, wireframe: true }))
        standIn.rotation.y = -deg(spec.yaw_deg)
        standIn.position.set(spec.anchor[0], spec.bottom_y + dims.h / 2, spec.anchor[1])
        boxes.add(standIn)
      }
    }

    current.forEach((room, idx) => {
      const lay = room.layout
      if (!lay) return
      const palette = style?.room_palette || []
      const color = hex(palette[idx % (palette.length || 1)], 0x58a6ff)
      const w = lay.w * PLATE_M
      const d = lay.d * PLATE_M
      const level = lay.level || 0
      const floorY = level * lhEff
      const cy = floorY + lhEff / 2
      // Editor overlay only: the room RECTANGLE as placed (the diorama has
      // its own anchor in the payload and is drawn above).
      const cx = (lay.x + lay.w / 2 - 0.5) * PLATE_M
      const cz = (lay.y + lay.d / 2 - 0.5) * PLATE_M
      const model = showModelsRef.current && room.id && roomsWithModel.has(room.id)

      // Label; the box only when no model stands in.
      // A drawn hull renders as its extruded polygon prism instead of the box.
      const roomGroup = new THREE.Group()
      if (!model) {
        // Outdoor rooms (always_visible — terraces, gardens) get NO body at
        // all: only their outline as a flat line loop on the ground — the
        // floor TEXTURE below (surfaces.floor / level plate / terrain) is
        // what one sees.
        const outdoorStandin = !!lay.always_visible
        const boxH = outdoorStandin ? 0.02 : lhEff * 0.94
        const mat = new THREE.MeshStandardMaterial({ color, transparent: true, opacity: 0.5 })
        let box: Mesh
        if (lay.outline?.length) {
          // Shape plane XY maps to world XZ after rotation.x = -π/2
          // (shape y → -z, extrusion +z → +y), so points go in as (x, -z).
          const shape = new THREE.Shape()
          lay.outline.forEach(([u, v], i) => {
            const px = (u - 0.5) * w
            const pz = (v - 0.5) * d
            if (i === 0) shape.moveTo(px, -pz)
            else shape.lineTo(px, -pz)
          })
          shape.closePath()
          box = new THREE.Mesh(
            new THREE.ExtrudeGeometry(shape, { depth: boxH, bevelEnabled: false }), mat)
          box.rotation.x = -Math.PI / 2
          box.position.y = -boxH / 2
        } else {
          box = new THREE.Mesh(new THREE.BoxGeometry(w, boxH, d), mat)
        }
        if (outdoorStandin) {
          // Ground the outline on the storey floor (the group sits
          // mid-storey; the prism geometry spans 0..boxH, the box is centred).
          box.position.y = lay.outline?.length
            ? -lhEff / 2
            : -lhEff / 2 + boxH / 2
        }
        const edges = new THREE.LineSegments(
          new THREE.EdgesGeometry(box.geometry),
          new THREE.LineBasicMaterial({ color }),
        )
        edges.rotation.copy(box.rotation)
        edges.position.copy(box.position)
        if (!outdoorStandin) roomGroup.add(box)  // outdoor: lines only
        roomGroup.add(edges)
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
      sprite.scale.set(3.2, 0.8, 1)
      sprite.position.y = lhEff * 0.62
      roomGroup.add(sprite)

      // The group does NOT yaw: x/y/w/d are the rectangle AS PLACED
      // (layout.rotation only orients the room MODEL, which the payload
      // spec already carries).
      roomGroup.position.set(cx, cy, cz)
      boxes.add(roomGroup)
    })

    // ── Exits and markers (payload, world coordinates) ─────────────────
    // Exit points: the payload resolves explicit AND derived exits into one
    // frame — the preview only draws the dot.
    const levelOfRoom = new Map<string, number>(
      current.filter((r) => r.id && r.layout)
        .map((r) => [r.id as string, r.layout!.level || 0]))
    for (const exit of sc?.exits || []) {
      const lv = levelOfRoom.get(exit.room_id)
      if (lv === undefined || !visibleLevel(lv)) continue
      const dot = new THREE.Mesh(
        new THREE.SphereGeometry(0.16, 12, 12),
        new THREE.MeshBasicMaterial({ color: AID.exit }),
      )
      dot.position.set(exit.at_world[0], lv * lhEff + 0.25, exit.at_world[1])
      boxes.add(dot)
    }
    // Animation markers: room markers AND the props' seat/stand spots, both
    // already composed into world coordinates by the server. A figure with
    // the marker's clip stands there, numbered per room.
    const markerNo = new Map<string, number>()
    for (const marker of sc?.markers || []) {
      const lv = levelOfRoom.get(marker.room_id)
      if (lv !== undefined && !visibleLevel(lv)) continue
      const n = (markerNo.get(marker.room_id) || 0) + 1
      markerNo.set(marker.room_id, n)
      placeFigure({
        x: marker.at_world[0], y: marker.y_world, z: marker.at_world[1],
        animation: marker.animation, facing: marker.facing,
        label: `${n} · ${marker.animation}`,
      })
    }

    // Building outline + elevator (AV3D-12): the drawn contour per used
    // level (walls are the client's job — the preview shows the shape) and
    // the elevator as a translucent shaft through all levels.
    const m3 = map3dRef.current
    // The levels in play come from the payload (the server decides what a
    // "used level" is); before the first response the rooms stand in.
    const usedLevels = sc
      ? sc.levels.map((l) => l.level)
      : Array.from(new Set(current.filter((r) => r.layout)
          .map((r) => r.layout!.level || 0)))
    if (m3?.outline?.length) {
      const base = m3.outline.map(([x, y]) =>
        [(x - 0.5) * PLATE_M, (y - 0.5) * PLATE_M] as [number, number])
      base.push(base[0])
      for (const lv of (usedLevels.length ? usedLevels : [0])) {
        const geo = new THREE.BufferGeometry().setFromPoints(
          base.map(([x, z]) => new THREE.Vector3(x, lv * lhEff + 0.02, z)))
        boxes.add(new THREE.Line(geo, new THREE.LineBasicMaterial({
          color: 0x58a6ff, transparent: true, opacity: lv === 0 ? 0.9 : 0.45,
        })))
      }
    }
    // ── Server-composed primitives (contract § B1) ──────────────────────
    // plates / walls / extras arrive FINISHED: world metres around the tile
    // centre, split around every opening, coloured by `style`. Nothing here
    // decides geometry — this is Box/Extrude construction and texture
    // tiling, no more. View state stays local (level solo, toggles, the
    // camera culling that uses the delivered outward_normal).
    wallCullRef.current = []
    // Every colour/opacity below is the payload's — there is no local
    // default to fall back to, because without the payload there is nothing
    // to paint in the first place.
    const wallColor = hex(sc?.style.wall_color, 0xffffff)
    const floorColor = hex(sc?.style.floor_color, 0xffffff)
    const glassColor = hex(sc?.style.glass_color, 0xffffff)
    const glassOpacity = sc?.style.glass_opacity ?? 1
    const upperWall = sc?.style.upper_wall_opacity ?? 1
    const upperFloor = sc?.style.upper_floor_opacity ?? 1

    if (sc && showWallsRef.current) {
      // Floor slabs. A textured kind tiles at its REAL size (size_m × k);
      // thickness 0 means "texture surface only, no body" (outdoor rooms).
      for (const plate of sc.plates) {
        if (!visibleLevel(plate.level) || plate.outline.length < 3) continue
        const upper = plate.opacity_role === 'upper'
        const solid = plate.thickness > 0
        const shape = new THREE.Shape()
        plate.outline.forEach(([px, pz], i) => {
          // Extruded plates go in as (x, z) and rotate +90° (the extrusion
          // then runs downward); flat ones as (x, −z) with −90°.
          const sy = solid ? pz : -pz
          if (i === 0) shape.moveTo(px, sy)
          else shape.lineTo(px, sy)
        })
        shape.closePath()
        const info = plate.texture_kind ? ensureSurfaceTex(plate.texture_kind) : null
        let mat: Material
        if (info?.tex) {
          const tile = info.sizeM * kFac
          const tex = (info.tex as Texture).clone()
          tex.needsUpdate = true
          tex.repeat.set(1 / tile, 1 / tile)
          mat = new THREE.MeshStandardMaterial({
            map: tex, transparent: upper, opacity: upper ? upperFloor : 1,
          })
        } else {
          mat = new THREE.MeshStandardMaterial({
            color: floorColor, transparent: upper, opacity: upper ? upperFloor : 1,
          })
        }
        const mesh = new THREE.Mesh(
          solid
            ? new THREE.ExtrudeGeometry(shape, { depth: plate.thickness, bevelEnabled: false })
            : new THREE.ShapeGeometry(shape),
          mat)
        mesh.rotation.x = solid ? Math.PI / 2 : -Math.PI / 2
        mesh.position.y = plate.top_y
        boxes.add(mesh)
      }

      // Wall segments. Doors/passages are already gaps, a window arrives as
      // sill + head + its own glass entry — one box each.
      for (const wall of sc.walls) {
        if (!visibleLevel(wall.level)) continue
        const dx = wall.to[0] - wall.from[0]
        const dz = wall.to[1] - wall.from[1]
        const len = Math.hypot(dx, dz)
        if (len < 1e-4) continue
        const upper = wall.opacity_role === 'upper'
        let mat: Material
        if (wall.glass) {
          mat = new THREE.MeshStandardMaterial({
            color: glassColor, transparent: true, opacity: glassOpacity,
          })
        } else {
          // BoxGeometry UVs are per-face normalized, so a tiled wall needs a
          // per-mesh texture clone with its own repeat.
          const info = wall.texture_kind ? ensureSurfaceTex(wall.texture_kind) : null
          if (info?.tex) {
            const tile = info.sizeM * kFac
            const tex = (info.tex as Texture).clone()
            tex.needsUpdate = true
            tex.repeat.set(len / tile, wall.height / tile)
            mat = new THREE.MeshStandardMaterial({
              map: tex, transparent: upper, opacity: upper ? upperWall : 1,
            })
          } else {
            mat = new THREE.MeshStandardMaterial({
              color: wallColor, transparent: upper, opacity: upper ? upperWall : 1,
            })
          }
        }
        const box = new THREE.Mesh(
          new THREE.BoxGeometry(len, wall.height, wall.thickness), mat)
        const mx = (wall.from[0] + wall.to[0]) / 2
        const mz = (wall.from[1] + wall.to[1]) / 2
        box.position.set(mx, wall.base_y + wall.height / 2, mz)
        box.rotation.y = -Math.atan2(dz, dx)
        boxes.add(box)
        // Camera culling with the DELIVERED normal — a wall whose outside
        // faces the camera hides so the interior stays visible.
        if (!wall.glass) {
          wallCullRef.current.push({ mesh: box, mx, mz,
            nx: wall.outward_normal[0], nz: wall.outward_normal[1] })
        }
      }
    }

    // Extras (elevator shaft/glass/pads/cabin): typed boxes, centre + size,
    // straight from the payload. The shaft spans all levels, so it only
    // shows in the all-levels view.
    if (sc && solo === null) {
      for (const extra of sc.extras) {
        const glass = extra.kind.endsWith('_glass')
        const mat = glass
          ? new THREE.MeshStandardMaterial({
              color: glassColor, transparent: true, opacity: glassOpacity })
          : new THREE.MeshStandardMaterial({
              color: extra.kind === 'elevator_pad' ? AID.elevatorPad
                : extra.kind === 'elevator_cabin' ? AID.elevatorCabin
                  : AID.elevatorMetal,
              transparent: extra.kind === 'elevator_cabin',
              opacity: extra.kind === 'elevator_cabin' ? 0.85 : 1 })
        const mesh = new THREE.Mesh(
          new THREE.BoxGeometry(extra.size[0], extra.size[1], extra.size[2]), mat)
        mesh.position.set(extra.center[0], extra.center[1], extra.center[2])
        boxes.add(mesh)
      }
    }

    // Height scale (drop 2026-07-17): a vertical metre ruler with 1-m ticks
    // at the south-west corner plus a storey line per level at level × lh —
    // whether the storey height fits the building model is visible at a
    // glance. The ruler is in WORLD metres, same basis as the client.
    {
      const lo = Math.min(0, ...usedLevels)
      const hi = Math.max(0, ...usedLevels)
      // Anchored mode: the ruler counts REAL metres (one tick = kFac world
      // units) — the admin thinks in real sizes, and the shell top lands
      // exactly on its declared height_m label.
      const unit = kFac
      const topWorld = Math.max((hi + 1) * lhEff, buildingTopY, lhEff)
      const bottomY = Math.min(0, Math.floor((lo * lhEff) / unit))
      const topY = Math.ceil(topWorld / unit)
      const rx = -PLATE_M / 2 - 0.7
      const rz = PLATE_M / 2 + 0.7
      const rulerMat = new THREE.LineBasicMaterial({ color: 0xc9d1d9 })
      boxes.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints([
        new THREE.Vector3(rx, bottomY * unit, rz), new THREE.Vector3(rx, topY * unit, rz),
      ]), rulerMat))
      const labelEvery = topY - bottomY > 14 ? 5 : 1
      for (let yi = bottomY; yi <= topY; yi++) {
        const y = yi * unit
        const len = yi % 5 === 0 ? 0.3 : 0.16
        boxes.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints([
          new THREE.Vector3(rx - len, y, rz), new THREE.Vector3(rx + len, y, rz),
        ]), rulerMat))
        if (yi !== 0 && yi % labelEvery === 0) {
          const c = document.createElement('canvas')
          c.width = 64
          c.height = 32
          const cctx = c.getContext('2d')
          if (cctx) {
            cctx.font = '600 20px sans-serif'
            cctx.textAlign = 'center'
            cctx.textBaseline = 'middle'
            cctx.shadowColor = 'rgba(0,0,0,0.9)'
            cctx.shadowBlur = 4
            cctx.fillStyle = '#c9d1d9'
            cctx.fillText(`${yi}`, 32, 16)
          }
          const spr = new THREE.Sprite(new THREE.SpriteMaterial({
            map: new THREE.CanvasTexture(c), transparent: true, depthTest: false,
          }))
          spr.scale.set(0.6, 0.3, 1)
          spr.position.set(rx - 0.55, y, rz)
          boxes.add(spr)
        }
      }
      // Storey lines around the reference square at every level plate
      // (ground level 0 is the plate itself).
      const storeyMat = new THREE.LineBasicMaterial({
        color: 0x8b949e, transparent: true, opacity: 0.45,
      })
      const hp = PLATE_M / 2
      for (let lv = lo; lv <= hi + 1; lv++) {
        const y = lv * lhEff
        if (Math.abs(y) < 1e-6) continue
        boxes.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints([
          new THREE.Vector3(-hp, y, -hp), new THREE.Vector3(hp, y, -hp),
          new THREE.Vector3(hp, y, hp), new THREE.Vector3(-hp, y, hp),
          new THREE.Vector3(-hp, y, -hp),
        ]), storeyMat))
      }

      // Comparison figure at the ruler: the test figure at exactly
      // figures.base_height_m_world, standing on the ground next to the
      // metre scale — storey height vs. figure height at a glance. Facing 45
      // = north-east, i.e. towards the plate.
      placeFigure({ x: rx + 0.55, y: 0, z: rz - 0.35, facing: 45 })
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
        const mount = mountRef.current
        if (!mount || disposed) return

        const width = mount.clientWidth || 320
        const scene = new THREE.Scene()
        scene.background = null
        // Contract camera (Kamera & Maussteuerung): FOV 45, near 0.5, far 800.
        const camera = new THREE.PerspectiveCamera(45, width / height, 0.5, 800)
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
        key.position.set(6, 10, 6)
        scene.add(key)

        // ── Camera rig per the client contract (schnittstellen-3d.md →
        // "Kamera & Maussteuerung") — the preview feels identical to the
        // game client. Orbit around a ground target: dist 2.5..150, pitch
        // coupled to zoom (18°..62° base + free offset −35..35, clamped
        // 8..85), dist/yaw exponentially smoothed (~8/s).
        const cam = {
          target: new THREE.Vector3(0, 0, 0),
          dist: 14, distGoal: 14,
          yaw: 0.6, yawGoal: 0.6,
          pitchOffset: 0,
        }
        const applyCamera = () => {
          const tNorm = Math.sqrt(Math.max(0, (cam.dist - 2.5) / (150 - 2.5)))
          const basePitch = 18 + (62 - 18) * tNorm
          const pitch = ((Math.min(85, Math.max(8, basePitch + cam.pitchOffset))) * Math.PI) / 180
          camera.position.set(
            cam.target.x + Math.sin(cam.yaw) * Math.cos(pitch) * cam.dist,
            cam.target.y + Math.sin(pitch) * cam.dist,
            cam.target.z + Math.cos(cam.yaw) * Math.cos(pitch) * cam.dist,
          )
          camera.lookAt(cam.target)
        }
        const groundPoint = (clientX: number, clientY: number) => {
          const rect = renderer.domElement.getBoundingClientRect()
          const ndc = new THREE.Vector2(
            ((clientX - rect.left) / rect.width) * 2 - 1,
            -((clientY - rect.top) / rect.height) * 2 + 1,
          )
          const ray = new THREE.Raycaster()
          ray.setFromCamera(ndc, camera)
          const p = new THREE.Vector3()
          return ray.ray.intersectPlane(new THREE.Plane(new THREE.Vector3(0, 1, 0), 0), p)
            ? p.clone() : null
        }
        const dragRefLocal: {
          mode: '' | 'pan' | 'rotate'
          startGround: InstanceType<typeof THREE.Vector3> | null
          lastX: number
          lastY: number
        } = { mode: '', startGround: null, lastX: 0, lastY: 0 }
        renderer.domElement.style.touchAction = 'none'
        const onPointerDown = (e: PointerEvent) => {
          renderer.domElement.setPointerCapture(e.pointerId)
          if (e.button === 0 && !e.shiftKey && !e.ctrlKey && !e.altKey) {
            // Left drag = ground-anchored pan: the pressed ground point
            // stays under the cursor.
            dragRefLocal.mode = 'pan'
            dragRefLocal.startGround = groundPoint(e.clientX, e.clientY)
          } else {
            // Middle/right or modifier+left = rotate/tilt.
            dragRefLocal.mode = 'rotate'
          }
          dragRefLocal.lastX = e.clientX
          dragRefLocal.lastY = e.clientY
        }
        const onPointerMove = (e: PointerEvent) => {
          if (!dragRefLocal.mode) return
          if (dragRefLocal.mode === 'pan') {
            const g = groundPoint(e.clientX, e.clientY)
            if (g && dragRefLocal.startGround) {
              cam.target.add(dragRefLocal.startGround.clone().sub(g))
              applyCamera()
            }
          } else {
            const dx = e.clientX - dragRefLocal.lastX
            const dy = e.clientY - dragRefLocal.lastY
            cam.yawGoal -= dx * 0.005
            cam.pitchOffset = Math.min(35, Math.max(-35, cam.pitchOffset + dy * 0.25))
          }
          dragRefLocal.lastX = e.clientX
          dragRefLocal.lastY = e.clientY
        }
        const onPointerUp = (e: PointerEvent) => {
          dragRefLocal.mode = ''
          dragRefLocal.startGround = null
          try { renderer.domElement.releasePointerCapture(e.pointerId) } catch { /* released */ }
        }
        const onWheel = (e: WheelEvent) => {
          e.preventDefault()
          const cursor = groundPoint(e.clientX, e.clientY)
          const old = cam.distGoal
          cam.distGoal = Math.min(150, Math.max(2.5, old * Math.exp(e.deltaY * 0.0012)))
          // Zooming IN pulls the target toward the ground point under the
          // cursor (contract: lerp by 1 − distNew/distOld).
          if (cursor && cam.distGoal < old) {
            cam.target.lerp(cursor, 1 - cam.distGoal / old)
          }
        }
        const onContext = (e: Event) => e.preventDefault()
        renderer.domElement.addEventListener('pointerdown', onPointerDown)
        renderer.domElement.addEventListener('pointermove', onPointerMove)
        renderer.domElement.addEventListener('pointerup', onPointerUp)
        renderer.domElement.addEventListener('pointercancel', onPointerUp)
        renderer.domElement.addEventListener('wheel', onWheel, { passive: false })
        renderer.domElement.addEventListener('contextmenu', onContext)
        disposers.push(() => {
          renderer.domElement.removeEventListener('pointerdown', onPointerDown)
          renderer.domElement.removeEventListener('pointermove', onPointerMove)
          renderer.domElement.removeEventListener('pointerup', onPointerUp)
          renderer.domElement.removeEventListener('pointercancel', onPointerUp)
          renderer.domElement.removeEventListener('wheel', onWheel)
          renderer.domElement.removeEventListener('contextmenu', onContext)
        })

        // Ground plate = the contract's 8×8 m reference square, plus outline.
        const groundGeo = new THREE.PlaneGeometry(PLATE_M, PLATE_M)
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
        outline.position.y = 0.01
        scene.add(outline)

        const boxes = new THREE.Group()
        scene.add(boxes)
        disposers.push(() => {
          const disposeSafe = (o: Object3D) => {
            if (o.userData.__noDispose) return
            const mesh = o as Mesh
            mesh.geometry?.dispose?.()
            const m = mesh.material as Material | Material[] | undefined
            if (Array.isArray(m)) m.forEach((x) => x.dispose?.())
            else m?.dispose?.()
            for (const c of o.children) disposeSafe(c)
          }
          disposeSafe(scene)
        })

        const { clone: skclone } = await import('three/examples/jsm/utils/SkeletonUtils.js')
        clockRef.current = new THREE.Clock()
        handleRef.current = { THREE, boxes, skclone }
        disposers.push(() => { handleRef.current = null })
        rebuild(handleRef.current, roomsRef.current)

        // Initial framing: distance so the 8 m plate fits comfortably.
        cam.dist = cam.distGoal = Math.max(
          6, (PLATE_M * 1.2 / 2) / Math.tan((Math.PI * camera.fov) / 360) * 1.35)
        applyCamera()

        setLoading(false)

        let raf = 0
        const animate = () => {
          raf = requestAnimationFrame(animate)
          const delta = clockRef.current?.getDelta() || 0
          // Recipe camera culling: hide a wall piece whose OUTSIDE faces
          // the camera — the interior stays visible despite the walls.
          for (const w of wallCullRef.current) {
            w.mesh.visible =
              (camera.position.x - w.mx) * w.nx + (camera.position.z - w.mz) * w.nz <= 0
          }
          for (const mixer of mixersRef.current) mixer.update(delta)
          // Contract smoothing: dist/yaw approach their goals with
          // 1 − exp(−8·dt) per frame.
          const k = 1 - Math.exp(-8 * delta)
          cam.dist += (cam.distGoal - cam.dist) * k
          cam.yaw += (cam.yawGoal - cam.yaw) * k
          applyCamera()
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
  }, [height])

  // Dispose the cached model ORIGINALS only on unmount.
  useEffect(() => {
    const cache = cacheRef.current
    const clipCache = clipCacheRef.current
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
      if (figRef.current.obj) disposeTree(figRef.current.obj)
      figRef.current = { status: 'idle' }
      clipCache.clear()
    }
  }, [])

  // Levels that exist in the layout — feeds the exclusive-level buttons.
  const previewLevels = useMemo<number[]>(() => Array.from(new Set(
    rooms.filter((r) => r.layout)
      .map((r) => r.layout!.level || 0))).sort((a, b) => a - b), [rooms])

  // Live-apply layout edits (drag/resize/rotate in the editor) and toggle/
  // load-completion changes — content rebuild only, the scene/renderer stay.
  useEffect(() => {
    if (handleRef.current) rebuild(handleRef.current, rooms)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rooms, map3d, showModels, showBuilding, showWalls, soloLevel, bump, lh,
      fallbackYawDeg, scene])

  return (
    <div className="ga-form" style={{ gap: 6 }}>
      {/* Icon toolbar — the toggles/anchors read via tooltip, not label text
          (the plan pane is the busy one, this row stays quiet). */}
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <div className="ga-form-section-label" style={{ margin: 0, flex: 1 }}>{t('3D preview')}</div>
        {previewLevels.length > 1 ? (
          <span style={{ display: 'inline-flex', gap: 2, alignItems: 'center' }}>
            <button
              type="button"
              className={`ga-btn ga-btn-sm${soloLevel === null ? ' ga-btn-primary' : ''}`}
              onClick={() => setSoloLevel(null)}
              title={t('Show all levels.')}
            >
              ∀
            </button>
            {previewLevels.map((lv) => (
              <button
                key={lv}
                type="button"
                className={`ga-btn ga-btn-sm${soloLevel === lv ? ' ga-btn-primary' : ''}`}
                onClick={() => setSoloLevel((cur) => (cur === lv ? null : lv))}
                title={t('Show ONLY level {n} — rooms, plates and walls of the other storeys hide (click again for all).')
                  .replace('{n}', String(lv))}
              >
                {lv}
              </button>
            ))}
          </span>
        ) : null}
        <button
          type="button"
          className={`ga-btn ga-btn-sm${showModels ? ' ga-btn-primary' : ''}`}
          onClick={() => setShowModels((v) => !v)}
          title={t('Real room models — swap the level boxes for the generated room meshes (contract placement).')}
        >
          🛋
        </button>
        <button
          type="button"
          className={`ga-btn ga-btn-sm${showBuilding ? ' ga-btn-primary' : ''}`}
          onClick={() => setShowBuilding((v) => !v)}
          title={t('Building model overlay — ghost the building mesh over the plan (tile fit, metre ruler matches).')}
        >
          🏢
        </button>
        <button
          type="button"
          className={`ga-btn ga-btn-sm${showWalls ? ' ga-btn-primary' : ''}`}
          onClick={() => setShowWalls((v) => !v)}
          title={t('Walls & floor — render the outline floor plates and outer walls exactly like the game client (doors at the ground-floor exits; walls facing the camera hide). Needs a drawn outline.')}
        >
          🧱
        </button>
        {onPlanWidth ? (
          <label className="ga-check-row"
            title={anchorMissing
              ? t('Plan width (m) is REQUIRED here: no building model declares a height, so nothing can be derived. Without it the 3D client falls back to a legacy scale (24 m plan width) that does not match the storey height.')
              : t('Plan width (m): real-world width the floor-plan square represents. Empty = auto-derived from the building model (height × mesh proportions) — set a value only to correct it. THE scale anchor: room sizes derive from their declared widths, figures and storeys from real size × 8/plan width.')}>
            <span>{anchorMissing ? '⚠' : '📐'}</span>
            <input
              className="ga-input"
              type="number"
              min={0.5}
              max={500}
              step={0.5}
              style={anchorMissing
                ? { width: 70, borderColor: '#d29922' }
                : { width: 70 }}
              value={map3d?.plan_width_m ?? ''}
              placeholder={pwDerived > 0 ? `${t('auto')} (${pwDerived.toFixed(1)})` : '—'}
              onChange={(e) => {
                const n = parseFloat(e.target.value)
                onPlanWidth(Number.isFinite(n) && n > 0 ? n : undefined)
              }}
            />
          </label>
        ) : null}
        {onLevelHeight ? (
          <label className="ga-check-row"
            title={t('Level height (m): storey height in WORLD metres — stacks the floor-plan levels and sets the figure scale in rooms (level_height / 3). Realistic interiors are ≈ 1–1.5; the default 3 reads as a triple-height storey.')}>
            <span>↕</span>
            <input
              className="ga-input"
              type="number"
              min={0.5}
              max={50}
              step={0.1}
              style={{ width: 70 }}
              value={levelHeightM ?? ''}
              placeholder={lhDerived ? `${t('auto')} (${lhDerived.toFixed(2)})` : '3'}
              title={lhDerived
                ? t('Derived from the building model (height ÷ storeys) — this field is only the fallback without those anchors.')
                : undefined}
              onChange={(e) => {
                const n = parseFloat(e.target.value)
                onLevelHeight(Number.isFinite(n) && n > 0 ? n : undefined)
              }}
            />
          </label>
        ) : null}
        {buildingEntry ? (
          <label className="ga-check-row"
            title={t('Model height (m): estimated height of the building MODEL in world metres — dial it at the metre ruler. The footprint keeps following the floor plan (tile fit); only the height is scaled to this value, so a too-flat mesh gets repaired. Storey height derives as height ÷ storeys; empty = natural proportions.')}>
            <span>📏</span>
            <input
              key={`bh-${buildingEntry.heightM}`}
              className="ga-input"
              type="number"
              min={0}
              max={500}
              step={0.1}
              style={{ width: 70 }}
              defaultValue={buildingEntry.heightM || ''}
              placeholder={t('natural')}
              onBlur={(e) => commitBuildingHeight(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
            />
          </label>
        ) : null}
        {buildingEntry ? (
          <label className="ga-check-row"
            title={t('Model storeys: storeys the building MODEL depicts — together with the model height this derives the storey height (height ÷ storeys) for stacking the levels.')}>
            <span>🏬</span>
            <input
              key={`bf-${buildingEntry.floors}`}
              className="ga-input"
              type="number"
              min={0}
              max={200}
              step={0.5}
              style={{ width: 62 }}
              defaultValue={buildingEntry.floors || ''}
              placeholder="—"
              onBlur={(e) => commitBuildingFloors(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
            />
          </label>
        ) : null}
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
        {loading || error || sceneError ? (
          <div style={{
            position: 'absolute', inset: 0, display: 'flex', alignItems: 'center',
            justifyContent: 'center', pointerEvents: 'none', fontSize: '0.85em',
            opacity: 0.75, padding: 8, textAlign: 'center',
          }}>
            {error ? `${t('Error')}: ${error}`
              : sceneError
                // The server owns the geometry — without its answer there is
                // nothing to show. No second, locally computed picture.
                ? `${t('Scene recipe unavailable — the preview renders what the server composes. Reload once the backend answers again.')} (${sceneError})`
                : t('Loading…')}
          </div>
        ) : null}
      </div>
      <span className="ga-hint">
        {t('Renders the server-composed scene (POST /play/scene-preview) — the same geometry the 3D client gets; metre ruler + storey lines check the level height against the model.')}
      </span>
    </div>
  )
}
