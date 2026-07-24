/**
 * FloorPlanPreview — live 3D preview of the room layout (AV3D-2), shown next
 * to the floor-plan editor. Follows the CONTRACT placement semantics
 * (schnittstellen-3d.md → "Platzierungs-Semantik (Referenz für Vorschauen)")
 * so it renders exactly what the game client renders:
 *
 *   - reference surface = fixed 8×8 m square (layout fractions refer to it),
 *   - floor height = level × 3 m (map3d.level_height may override the 3),
 *   - room model: normalized to unit footprint (largest XZ side = 1, XZ
 *     centred, bottom y=0), uniformly scaled by min(w/fp_x, d/fp_z) × 0.96,
 *     bottom at floor + 0.12 m — THEN the meta rotation {x,y,z}, the layout
 *     yaw and offset_y (metres) apply,
 *   - exit = fraction of the room rectangle (orange dot), markers green.
 *
 * Two compare switches: "Real room models" swaps the level boxes for the
 * rooms' ACTIVE models (rooms without one keep their box), "Building model
 * overlay" ghosts the location's building model over the plan. Models are
 * fetched once and cached; the boxes rebuild live while dragging in the
 * editor (the three.js scene itself is created once). three.js is imported
 * dynamically — it stays in the shared chunk.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import type { AnimationClip, AnimationMixer, Clock, Group, Material, Mesh, Object3D, Texture } from 'three'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPost } from '../../lib/api'
import { normalizeOpeningEdge, outlineOf, mirrorOpenings } from './planGeometry'
import { getBuildingDims, notifyModel3dChanged } from './topDownSnapshot'
import { useToast } from '../../lib/Toast'
import type { Map3D, Room } from './worldTypes'

// Contract constants: the 8×8 m reference square and the 3 m storey.
const PLATE_M = 8
const DEFAULT_LEVEL_M = 3
const PALETTE = [0x58a6ff, 0x3fb950, 0xd29922, 0xf778ba,
                 0xa371f7, 0xf85149, 0x79c0ff, 0x56d364]

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
  height?: number
}

export function FloorPlanPreview({ locationId, rooms, map3d, levelHeightM, onLevelHeight, onPlanWidth, fallbackYawDeg = 0, height = 540 }: FloorPlanPreviewProps) {
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
  // Prop library meta (orientation fix + real dims per id) — one fetch feeds
  // every placement; prop GLBs land in cacheRef under "prop:<id>".
  const propsMetaRef = useRef<{ status: 'idle' | 'loading' | 'ready'
    map: Map<string, { rotation: { x?: number; y?: number; z?: number }
      dims: [number, number, number]; hasModel: boolean }> }>(
    { status: 'idle', map: new Map() })
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
    // ONE compression factor per location (anchored mode): the reference
    // square (8 world-m) represents plan_width_m real metres → k = 8 /
    // plan_width_m. EVERYTHING derives from real size × k — storeys,
    // figures, shell height; without the anchor k = 1 (legacy). The
    // building entry is fetched regardless of the overlay toggle so the
    // storey derivation is always live.
    const bAnchor = ensureModel('building')
    const planW = map3dRef.current?.plan_width_m
      || (bAnchor && bAnchor.heightM > 0 && wphRef.current > 0
          ? bAnchor.heightM * wphRef.current : 0)
    const kFac = planW > 0 ? PLATE_M / planW : 1
    const lhEff = bAnchor && bAnchor.heightM > 0 && bAnchor.floors > 0
      ? (bAnchor.heightM / bAnchor.floors) * kFac
      : lh
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

    // Place a model per the CONTRACT chain: normalize to unit footprint
    // (largest XZ side = 1, XZ centred, bottom y=0), uniform fit
    // min(w/fp_x, d/fp_z) × 0.96 measured on the UNROTATED model, bottom on
    // floor + 0.12 m — then meta rotation, layout yaw and offset_y. After
    // the rotations the bottom is re-grounded from the rotated bounds.
    const placeModel = (entry: CachedModel, targetW: number, targetD: number,
                        cx: number, floorY: number, cz: number,
                        yawDeg: number, offsetY = 0) => {
      const clone = entry.obj.clone(true)
      const norm = new THREE.Group()
      norm.add(clone)
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
      const fitScale = Math.min(targetW / (fpX || 1), targetD / (fpZ || 1)) * 0.96
      fit.scale.setScalar(fitScale)

      // Contract order: meta rotation FIX first (inner group), THEN the
      // layout yaw as its own parent — combining both in one Euler drifts
      // as soon as an x/z fix is set (the yaw would tilt the fixed axis).
      const holder = new THREE.Group()
      holder.add(fit)
      holder.rotation.set(deg(entry.rotation.x), deg(entry.rotation.y),
                          deg(entry.rotation.z))
      const yawG = new THREE.Group()
      yawG.add(holder)
      yawG.rotation.y = -deg(yawDeg)
      yawG.updateMatrixWorld(true)
      const b2 = new THREE.Box3().setFromObject(yawG)
      const c2 = b2.getCenter(new THREE.Vector3())
      yawG.position.set(cx - c2.x,
                        floorY + 0.12 - b2.min.y + offsetY,
                        cz - c2.z)
      yawG.userData.__noDispose = true
      boxes.add(yawG)
      // World extent of the model's largest side — with the model's
      // declared real width this yields the room's content scale.
      return fitScale
    }

    // ── Props (plan-room-props.md): meta, meshes, real-size placement ──
    const ensurePropsMeta = (): boolean => {
      const s = propsMetaRef.current
      if (s.status !== 'idle') return s.status === 'ready'
      s.status = 'loading'
      apiGet<{ props?: Array<{ id: string; has_model?: boolean
        rotation?: { x?: number; y?: number; z?: number }
        width_m?: number; depth_m?: number; height_m?: number }> }>('/world/props')
        .then((d) => {
          for (const p of d.props || []) {
            s.map.set(p.id, { rotation: p.rotation || {},
              dims: [p.width_m || 1, p.depth_m || 1, p.height_m || 1],
              hasModel: !!p.has_model })
          }
        })
        .catch(() => {})
        .finally(() => { s.status = 'ready'; setBump((b) => b + 1) })
      return false
    }
    const ensurePropModel = (propId: string): CachedModel | null => {
      const key = `prop:${propId}`
      const cur = cacheRef.current.get(key)
      if (cur === 'loading' || cur === 'missing') return null
      if (cur) return cur
      cacheRef.current.set(key, 'loading')
      ;(async () => {
        try {
          const { GLTFLoader } = await import('three/examples/jsm/loaders/GLTFLoader.js')
          const gltf = await new GLTFLoader().loadAsync(
            `/assets/props/${encodeURIComponent(propId)}/model`)
          cacheRef.current.set(key, { obj: gltf.scene, rotation: {},
            offsetY: 0, floors: 0, heightM: 0, widthM: 0 })
        } catch {
          cacheRef.current.set(key, 'missing')
        }
        setBump((b) => b + 1)
      })()
      return null
    }
    // REAL-size rule: the prop scales by ITS OWN dims × kFac — uniformly from
    // the largest edge over the largest extent of the FIXED mesh (dims are
    // post-fix by convention); the placement never fit-scales. Chain mirrors
    // placeModel: fix (inner) → yaw (parent) → uniform world scale → re-ground
    // the rotated bounds at the floor + offset.
    const placePropModel = (entry: CachedModel,
        rot: { x?: number; y?: number; z?: number },
        dims: [number, number, number], px: number, pz: number,
        floorY: number, yawDeg2: number, offY: number) => {
      const clone = entry.obj.clone(true)
      const holder = new THREE.Group()
      holder.add(clone)
      holder.rotation.set(deg(rot.x), deg(rot.y), deg(rot.z))
      holder.updateMatrixWorld(true)
      const b0 = new THREE.Box3().setFromObject(holder)
      const s0 = b0.getSize(new THREE.Vector3())
      const maxExtent = Math.max(s0.x, s0.y, s0.z) || 1
      const s = (Math.max(dims[0], dims[1], dims[2]) * kFac) / maxExtent
      const yawG = new THREE.Group()
      yawG.add(holder)
      yawG.rotation.y = -deg(yawDeg2)
      const outer = new THREE.Group()
      outer.add(yawG)
      outer.scale.setScalar(s)
      outer.updateMatrixWorld(true)
      const b1 = new THREE.Box3().setFromObject(outer)
      const c1 = b1.getCenter(new THREE.Vector3())
      outer.position.set(px - c1.x, floorY + 0.05 + offY * kFac - b1.min.y, pz - c1.z)
      outer.userData.__noDispose = true
      boxes.add(outer)
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

    current.forEach((room, idx) => {
      const lay = room.layout
      if (!lay) return
      const color = PALETTE[idx % PALETTE.length]
      const w = lay.w * PLATE_M
      const d = lay.d * PLATE_M
      const level = lay.level || 0
      const floorY = level * lhEff
      const cy = floorY + lhEff / 2
      // Diorama placement comes from the PLAN: layout.model_at anchors the
      // model like a prop (default = centred), layout.model_offset_y is the
      // height — the room sidecar offset is retired.
      const mAt = lay.model_at || [0.5, 0.5]
      const cx = (lay.x + mAt[0] * lay.w - 0.5) * PLATE_M
      const cz = (lay.y + mAt[1] * lay.d - 0.5) * PLATE_M

      const model = showModelsRef.current && room.id
        ? ensureModel(`room:${room.id}`, room.id)
        : null
      let fitScale = 0
      if (model) {
        fitScale = placeModel(model, w, d, cx, floorY, cz, lay.rotation || 0,
                              lay.model_offset_y || 0)
      }

      // Prop placements: real-size furnishing meshes; a wireframe box of the
      // prop's dims stands in while meta/mesh load and for dangling ids.
      ;(lay.props || []).forEach((p) => {
        ensurePropsMeta()
        const pm = propsMetaRef.current.map.get(p.prop_id)
        const dims: [number, number, number] = pm?.dims || [1, 1, 1]
        const px = (lay.x + p.at[0] * lay.w - 0.5) * PLATE_M
        const pz = (lay.y + p.at[1] * lay.d - 0.5) * PLATE_M
        const entry = pm?.hasModel ? ensurePropModel(p.prop_id) : null
        if (entry && pm) {
          placePropModel(entry, pm.rotation, dims, px, pz, floorY,
            p.yaw || 0, p.offset_y || 0)
        } else {
          const standIn = new THREE.Mesh(
            new THREE.BoxGeometry(dims[0] * kFac, dims[2] * kFac, dims[1] * kFac),
            new THREE.MeshBasicMaterial({ color: 0xd29922, wireframe: true }))
          standIn.rotation.y = -deg(p.yaw || 0)
          standIn.position.set(px,
            floorY + 0.05 + (p.offset_y || 0) * kFac + (dims[2] * kFac) / 2, pz)
          boxes.add(standIn)
        }
      })
      // Figure scale in THIS room. Anchored mode: the ONE location factor
      // k — rect sizes derive from width_m, so content and figures share
      // it automatically. Legacy: per-room rect/width_m, else storey/3.
      const roomFigScale = planW > 0
        ? kFac
        : (model && model.widthM > 0 && fitScale > 0
            ? fitScale / model.widthM
            : lhEff / 3)

      // Label + exit/marker dots always; the box only when no model stands in.
      // A drawn hull renders as its extruded polygon prism instead of the box.
      const roomGroup = new THREE.Group()
      if (!model) {
        // Outdoor rooms (always_visible — terraces, gardens) stand in as a
        // FLAT plate: the full-height prism read as walls they must not have.
        const outdoorStandin = !!lay.always_visible
        const boxH = outdoorStandin ? 0.12 : lhEff * 0.94
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
          // Ground the plate on the storey floor (the group sits mid-storey;
          // the prism geometry spans 0..boxH, the box is centred).
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
        roomGroup.add(box)
        roomGroup.add(edges)
      }

      if (lay.exit) {
        const dot = new THREE.Mesh(
          new THREE.SphereGeometry(0.16, 12, 12),
          new THREE.MeshBasicMaterial({ color: 0xe0a356 }),
        )
        dot.position.set((lay.exit[0] - 0.5) * w, -lhEff * 0.4, (lay.exit[1] - 0.5) * d)
        roomGroup.add(dot)
      }
      // Animation markers (green — exit stays orange): a dot on the room
      // floor plus a small TEST FIGURE at the contract's in-room figure
      // scale (1/3 of the ~1.7 m map figure ≈ 0.57 m) with the animation
      // kind as a label — placement is judgeable at a glance. A simple
      // mannequin for now; an animated skinned figure would need a bundled
      // rigged model.
      ;(lay.markers || []).forEach((m, mi) => {
        const mx = (m.at[0] - 0.5) * w
        const mz = (m.at[1] - 0.5) * d
        // offset_y is additive to the sampled seat height in the client —
        // the preview has no sampling, so it applies from the room floor.
        const floor = -lhEff * 0.44 + (m.offset_y || 0)
        const fig = new THREE.Group()
        // No marker dot in 3D — it sat exactly where the figure is judged
        // and got in the way; the figure + numbered label mark the spot,
        // the 2D plan keeps its green dot for precise positioning.

        // Preferred: a REAL Mixamo figure with the marker's animation (any
        // humanoid character model the server offers + the shared clip of
        // the kind). Falls back to the mannequin while loading / when
        // figure or clip is missing.
        const figSrc = ensureTestFigure()
        const anim = figSrc ? ensureClip(m.animation) : null
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
          // BODY size comes from the REST pose (standing T-pose) — the
          // posed bbox would blow lying/sitting figures up (a lying box is
          // ~half as tall, so the figure came out ~twice as large).
          pivot.updateMatrixWorld(true)
          const fb = new THREE.Box3().setFromObject(pivot)
          const fs = fb.getSize(new THREE.Vector3())
          const k = (1.7 * roomFigScale) / (fs.y || 1)
          const mixer = new THREE.AnimationMixer(inst)
          mixer.clipAction(anim.clip).play()
          mixer.update(0)
          mixersRef.current.push(mixer)
          pivot.scale.setScalar(k)
          // Grounding DOES use the posed bounds — a lying figure rests on
          // the floor, not on where its feet would be standing.
          pivot.updateMatrixWorld(true)
          const fb2 = new THREE.Box3().setFromObject(pivot)
          const fc2 = fb2.getCenter(new THREE.Vector3())
          pivot.position.set(-fc2.x, floor - fb2.min.y, -fc2.z)
          pivot.userData.__noDispose = true
          fig.add(pivot)
          if (m.rotation !== undefined) {
            fig.rotation.y = ((m.rotation || 0) * Math.PI) / 180
          }
        } else {
          // Mannequin fallback — scaled to the SAME figure size as the real
          // figure would be (it used to be a fixed ~0.57 m regardless of
          // the room scale).
          const tgt = 1.7 * roomFigScale
          const figMat = new THREE.MeshStandardMaterial({
            color: 0x3fb950, transparent: true, opacity: 0.85,
          })
          const body = new THREE.Mesh(
            new THREE.CapsuleGeometry(0.055 * tgt, 0.62 * tgt, 4, 10), figMat)
          body.position.y = floor + 0.42 * tgt
          fig.add(body)
          const head = new THREE.Mesh(
            new THREE.SphereGeometry(0.09 * tgt, 12, 12), figMat)
          head.position.y = floor + 0.88 * tgt
          fig.add(head)
          // Facing nose — only when a facing is set (0 = south/+Z, 90 = east/+X;
          // unset = the client decides, so the preview stays direction-less).
          if (m.rotation !== undefined) {
            const nose = new THREE.Mesh(
              new THREE.ConeGeometry(0.05 * tgt, 0.16 * tgt, 10), figMat)
            nose.rotation.x = Math.PI / 2
            nose.position.set(0, floor + 0.74 * tgt, 0.14 * tgt)
            fig.add(nose)
            fig.rotation.y = ((m.rotation || 0) * Math.PI) / 180
          }
        }

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
          mctx.fillStyle = '#7ee2a0'
          mctx.fillText(`${mi + 1} · ${m.animation}`.slice(0, 14), 64, 20)
        }
        const msprite = new THREE.Sprite(new THREE.SpriteMaterial({
          map: new THREE.CanvasTexture(mc), transparent: true, depthTest: false,
        }))
        msprite.scale.set(1.3, 0.4, 1)
        msprite.position.y = floor + 0.78
        fig.add(msprite)

        fig.position.set(mx, 0, mz)
        roomGroup.add(fig)
      })

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

      // The group does NOT yaw: x/y/w/d are the rectangle AS PLACED and the
      // exit/markers are fractions of that placed rectangle (matches the 2D
      // editor exactly) — layout.rotation only orients the room MODEL,
      // applied in placeModel above.
      roomGroup.position.set(cx, cy, cz)
      boxes.add(roomGroup)
    })

    // Building outline + elevator (AV3D-12): the drawn contour per used
    // level (walls are the client's job — the preview shows the shape) and
    // the elevator as a translucent shaft through all levels.
    const m3 = map3dRef.current
    const usedLevels = Array.from(new Set(
      current.filter((r) => r.layout).map((r) => r.layout!.level || 0)))
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
    // "Walls & floor" per the client recipe: per used level a floor plate
    // in outline shape (extruded downward) + one box per polygon edge as
    // the outer wall; the ground floor gets door gaps at the projected
    // room exits (fallback: a central door in the southernmost piece).
    wallCullRef.current = []
    if (showWallsRef.current && (m3?.outline?.length || 0) >= 3) {
      const pts = m3!.outline!.map(([fx, fy]) =>
        [(fx - 0.5) * PLATE_M, (fy - 0.5) * PLATE_M] as [number, number])
      const lvls = (usedLevels.length ? usedLevels : [0]).slice().sort((a, b) => a - b)
      let area2 = 0
      for (let i = 0; i < pts.length; i++) {
        const [x1, z1] = pts[i]
        const [x2, z2] = pts[(i + 1) % pts.length]
        area2 += x1 * z2 - x2 * z1
      }
      const ccw = area2 > 0

      // Ground-floor exits projected onto the contour (< 0.45 m = a door).
      const exits: Array<[number, number]> = current
        .filter((r) => r.layout?.exit && (r.layout.level || 0) === 0)
        .map((r) => {
          const lay = r.layout!
          return [
            (lay.x + lay.exit![0] * lay.w - 0.5) * PLATE_M,
            (lay.y + lay.exit![1] * lay.d - 0.5) * PLATE_M,
          ] as [number, number]
        })
      const doorsPerEdge = new Map<number, number[]>()
      let anyDoor = false
      pts.forEach((a, i) => {
        const b = pts[(i + 1) % pts.length]
        const dx = b[0] - a[0]
        const dz = b[1] - a[1]
        const len = Math.hypot(dx, dz) || 1
        for (const [ex, ez] of exits) {
          const tp = Math.min(len, Math.max(0, ((ex - a[0]) * dx + (ez - a[1]) * dz) / len))
          const px = a[0] + (dx / len) * tp
          const pz = a[1] + (dz / len) * tp
          if (Math.hypot(ex - px, ez - pz) < 0.45) {
            if (!doorsPerEdge.has(i)) doorsPerEdge.set(i, [])
            doorsPerEdge.get(i)!.push(tp)
            anyDoor = true
          }
        }
      })
      if (!anyDoor) {
        let best = 0
        let bestZ = -Infinity
        pts.forEach((a, i) => {
          const b = pts[(i + 1) % pts.length]
          const mz = (a[1] + b[1]) / 2
          if (mz > bestZ) { bestZ = mz; best = i }
        })
        const a = pts[best]
        const b = pts[(best + 1) % pts.length]
        doorsPerEdge.set(best, [Math.hypot(b[0] - a[0], b[1] - a[1]) / 2])
      }

      // Floor plates: outline shape, extruded DOWNWARD (top at
      // level × storey + 0.08, thickness 0.14).
      const shape = new THREE.Shape()
      pts.forEach(([x, z], i) => { if (i === 0) shape.moveTo(x, z); else shape.lineTo(x, z) })
      shape.closePath()
      const plateGeo = new THREE.ExtrudeGeometry(shape, { depth: 0.14, bevelEnabled: false })
      for (const lv of lvls) {
        // Per-level floor kind (map3d.level_floors): the plate tiles with
        // the kind's texture at its real size — rooms lay their own floor
        // plates ABOVE this one, so a room floor overrides only its area.
        const lvKind = m3?.level_floors?.[String(lv)] || ''
        const lvTex = lvKind ? ensureSurfaceTex(lvKind) : null
        let plateMat: Material
        if (lvTex?.tex) {
          const tile = lvTex.sizeM * kFac
          const t = (lvTex.tex as Texture).clone()
          t.needsUpdate = true
          t.repeat.set(1 / tile, 1 / tile)
          plateMat = new THREE.MeshStandardMaterial({
            map: t, transparent: lv !== 0, opacity: lv === 0 ? 1 : 0.4,
          })
        } else {
          plateMat = new THREE.MeshStandardMaterial({
            color: 0xd8d0c2, transparent: lv !== 0, opacity: lv === 0 ? 1 : 0.4,
          })
        }
        const plate = new THREE.Mesh(plateGeo, plateMat)
        plate.rotation.x = Math.PI / 2
        plate.position.y = lv * lhEff + 0.08
        boxes.add(plate)
      }

      // Outer walls: one box per edge per level; ground floor split at the
      // doors (gap ±0.4 m, residues < 0.06 dropped).
      const WALL_H = Math.max(0.6, lhEff - 0.15)
      pts.forEach((a, i) => {
        const b = pts[(i + 1) % pts.length]
        const dx = b[0] - a[0]
        const dz = b[1] - a[1]
        const len = Math.hypot(dx, dz)
        if (len < 0.001) return
        const yaw = -Math.atan2(dz, dx)
        const nx = (ccw ? dz : -dz) / len
        const nz = (ccw ? -dx : dx) / len
        for (const lv of lvls) {
          let segs: Array<[number, number]> = [[0, len]]
          if (lv === 0 && doorsPerEdge.has(i)) {
            for (const tp of doorsPerEdge.get(i)!.sort((p, q) => p - q)) {
              const next: Array<[number, number]> = []
              for (const [s0, s1] of segs) {
                if (tp - 0.4 > s0) next.push([s0, Math.min(s1, tp - 0.4)])
                if (tp + 0.4 < s1) next.push([Math.max(s0, tp + 0.4), s1])
              }
              segs = next
            }
          }
          for (const [s0, s1] of segs) {
            const sl = s1 - s0
            if (sl < 0.06) continue
            const wall = new THREE.Mesh(
              new THREE.BoxGeometry(sl, WALL_H, 0.07),
              new THREE.MeshStandardMaterial({
                color: 0xcfc4b2, transparent: lv !== 0, opacity: lv === 0 ? 1 : 0.45,
              }),
            )
            const tc = (s0 + s1) / 2
            const mx = a[0] + (dx / len) * tc
            const mz = a[1] + (dz / len) * tc
            wall.position.set(mx, lv * lhEff + 0.08 + WALL_H / 2, mz)
            wall.rotation.y = yaw
            boxes.add(wall)
            wallCullRef.current.push({ mesh: wall, mx, mz, nx, nz })
          }
        }
      })
    }

    // Room-shell walls (B5): per placed room, the hull edges (drawn outline
    // or the implicit rectangle) as wall segments split around the room's
    // openings (NO CSG). Doors/passages leave a full-height gap; windows keep
    // a sill wall + a header wall and fill the opening with a translucent
    // glass pane between sill and sill+height. Wall height = the derived
    // storey height (lhEff). Surfaces are only a colour hint here (no texture
    // sampling — preview latitude); the client does the real texturing. Walls
    // register in the camera-cull set so the near ones hide and the interior
    // stays visible.
    if (showWallsRef.current) {
      const WALL_T = 0.07
      const WALL_H = Math.max(0.6, lhEff - 0.15)
      for (const room of current) {
        const lay = room.layout
        if (!lay) continue
        const lv = lay.level || 0
        const floorY = lv * lhEff
        // Outdoor rooms (always_visible — terraces, gardens) get NO shell
        // walls; their floor plate below still renders. The client follows
        // the same rule from the flag it already reads.
        const outdoor = !!lay.always_visible
        // Surfaces (B1/F7): a set wall kind samples its REAL texture — tiled
        // at its true size_m — as soon as it is loaded; the warmer colour
        // hint covers loading and texture-less kinds.
        const wallTex = lay.surfaces?.wall ? ensureSurfaceTex(lay.surfaces.wall) : null
        const wallColor = lay.surfaces?.wall ? 0xe8e0d0 : 0xcfc4b2
        const wallMat = new THREE.MeshStandardMaterial({
          color: wallColor, transparent: lv !== 0, opacity: lv === 0 ? 1 : 0.5,
        })
        // BoxGeometry UVs are per-face normalized, so a tiled wall needs a
        // per-mesh texture clone with its own repeat.
        const wallMatFor = (segLen: number, h: number): Material => {
          if (!wallTex?.tex) return wallMat
          const tile = wallTex.sizeM * kFac
          const t = (wallTex.tex as Texture).clone()
          t.needsUpdate = true
          t.repeat.set(segLen / tile, h / tile)
          return new THREE.MeshStandardMaterial({
            map: t, transparent: lv !== 0, opacity: lv === 0 ? 1 : 0.5,
          })
        }
        const glassMat = new THREE.MeshStandardMaterial({
          color: 0x9fc2d8, transparent: true, opacity: 0.25,
        })
        // Hull points in plate metres; with clockwise winding (screen coords
        // = XZ here) the outward normal of edge (ux, uz) is (uz, -ux).
        const hull = outlineOf(lay).map(([u, v]) => [
          (lay.x + u * lay.w - 0.5) * PLATE_M,
          (lay.y + v * lay.d - 0.5) * PLATE_M,
        ])
        // One physical hole, two walls: the neighbours' openings on shared
        // edges cut this room's wall too (mirror of the recipe/editor).
        const mirrored = room.id ? mirrorOpenings(
          { id: room.id, x: lay.x, y: lay.y, w: lay.w, d: lay.d,
            outline: lay.outline },
          current.filter((r) => r.id && r.id !== room.id && r.layout
              && (r.layout.level || 0) === lv)
            .map((r) => ({ id: r.id!, name: r.name,
              layout: { id: r.id!, x: r.layout!.x, y: r.layout!.y,
                w: r.layout!.w, d: r.layout!.d, outline: r.layout!.outline,
                openings: r.layout!.openings } })),
          planW > 0 ? planW : 8) : []
        const edges = hull.map((a, i) => {
          const b = hull[(i + 1) % hull.length]
          const len = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1
          return { i, ax: a[0], az: a[1], bx: b[0], bz: b[1],
            nx: (b[1] - a[1]) / len, nz: -(b[0] - a[0]) / len }
        })
        for (const ed of outdoor ? [] : edges) {
          const L = Math.hypot(ed.bx - ed.ax, ed.bz - ed.az)
          if (L < 0.05) continue
          const ux = (ed.bx - ed.ax) / L
          const uz = (ed.bz - ed.az) / L
          const yaw = -Math.atan2(ed.bz - ed.az, ed.bx - ed.ax)
          const placeBox = (segStart: number, segLen: number, y: number,
                            h: number, thick: number, mat: Material) => {
            if (segLen < 0.02 || h < 0.02) return
            const tc = segStart + segLen / 2
            const mx = ed.ax + ux * tc
            const mz = ed.az + uz * tc
            const box = new THREE.Mesh(new THREE.BoxGeometry(segLen, h, thick), mat)
            box.position.set(mx, floorY + 0.08 + y + h / 2, mz)
            box.rotation.y = yaw
            boxes.add(box)
            // Register on the ground floor only (upper floors stay ghosted).
            if (lv === 0) wallCullRef.current.push({ mesh: box, mx, mz, nx: ed.nx, nz: ed.nz })
          }
          // Openings on this edge → along-edge spans (metres × kFac → world).
          // Letters and indices read through ONE normalization (planGeometry).
          const spans = [
            ...(lay.openings || [])
              .map((o) => ({ op: o, norm: normalizeOpeningEdge(o) })),
            // Mirrored entries come pre-normalized onto this room's edges.
            ...mirrored.map((o) => ({
              op: o as unknown as NonNullable<typeof lay.openings>[number],
              norm: { edge: o.edge, at: o.at } })),
          ]
            .filter(({ norm }) => norm.edge === ed.i)
            .map(({ op: o, norm }) => {
              const halfW = Math.min((o.width_m * kFac) / 2, L / 2)
              const c = Math.min(Math.max(norm.at, 0), 1) * L
              return { s0: Math.max(0, c - halfW), s1: Math.min(L, c + halfW), op: o }
            }).sort((a, b) => a.s0 - b.s0)
          // Full-height solid wall = [0, L] minus every opening span.
          let solids: Array<[number, number]> = [[0, L]]
          for (const sp of spans) {
            const next: Array<[number, number]> = []
            for (const [s0, s1] of solids) {
              if (sp.s0 > s0) next.push([s0, Math.min(s1, sp.s0)])
              if (sp.s1 < s1) next.push([Math.max(s0, sp.s1), s1])
            }
            solids = next.filter(([a, b]) => b - a > 0.02)
          }
          for (const [s0, s1] of solids)
            placeBox(s0, s1 - s0, 0, WALL_H, WALL_T, wallMatFor(s1 - s0, WALL_H))
          // Windows: sill wall + header wall + glass pane; doors/passages
          // stay a full gap.
          for (const sp of spans) {
            if (sp.op.type !== 'window') continue
            const segLen = sp.s1 - sp.s0
            const sill = Math.min(sp.op.sill_m * kFac, WALL_H)
            const top = Math.min((sp.op.sill_m + sp.op.height_m) * kFac, WALL_H)
            if (sill > 0.02) placeBox(sp.s0, segLen, 0, sill, WALL_T, wallMatFor(segLen, sill))
            if (WALL_H - top > 0.02) placeBox(sp.s0, segLen, top, WALL_H - top, WALL_T, wallMatFor(segLen, WALL_H - top))
            if (top - sill > 0.02) placeBox(sp.s0, segLen, sill, top - sill, WALL_T * 0.6, glassMat)
          }
        }
        // Room floor plate: only when a floor kind is set — textured at its
        // real tile size (ShapeGeometry UVs are in shape units = metres), a
        // plain warm hint while it loads / without a texture.
        if (lay.surfaces?.floor) {
          const floorTexInfo = ensureSurfaceTex(lay.surfaces.floor)
          const shape = new THREE.Shape()
          hull.forEach(([hx, hz], i) => {
            if (i === 0) shape.moveTo(hx, -hz)
            else shape.lineTo(hx, -hz)
          })
          shape.closePath()
          let fmat: Material
          if (floorTexInfo?.tex) {
            const tile = floorTexInfo.sizeM * kFac
            const t = (floorTexInfo.tex as Texture).clone()
            t.needsUpdate = true
            t.repeat.set(1 / tile, 1 / tile)
            fmat = new THREE.MeshStandardMaterial({ map: t })
          } else {
            fmat = new THREE.MeshStandardMaterial({ color: 0xd8cfc0 })
          }
          const plate = new THREE.Mesh(new THREE.ShapeGeometry(shape), fmat)
          plate.rotation.x = -Math.PI / 2
          plate.position.y = floorY + 0.04
          boxes.add(plate)
        }
      }
    }

    if (m3?.elevator && solo === null) {
      // Elevator per the client's render recipe (schnittstellen →
      // "Render-Rezept Fahrstuhl"): all sizes are real metres × the figure
      // scale k (anchored 8/plan_width, legacy storey/3). Shaft 1.8 m
      // square with four corner columns + roof, glass on three sides (the
      // side toward the building centre stays open), a 1.6 m pad per
      // level, a static cabin on the ground floor.
      const kEl = planW > 0 ? kFac : lhEff / 3
      const ex = (m3.elevator[0] - 0.5) * PLATE_M
      const ez = (m3.elevator[1] - 0.5) * PLATE_M
      const hi = Math.max(0, ...usedLevels)
      const outer = 1.8 * kEl
      const col = Math.max(0.14 * kEl, 0.05)
      const shaftTop = (hi + 1) * lhEff + 0.08
      const colMat = new THREE.MeshStandardMaterial({ color: 0x6d7681 })
      for (const sx of [-1, 1]) {
        for (const sz of [-1, 1]) {
          const post = new THREE.Mesh(new THREE.BoxGeometry(col, shaftTop, col), colMat)
          post.position.set(ex + sx * (outer - col) / 2, shaftTop / 2,
                            ez + sz * (outer - col) / 2)
          boxes.add(post)
        }
      }
      const roof = new THREE.Mesh(new THREE.BoxGeometry(outer, 0.05, outer), colMat)
      roof.position.set(ex, shaftTop + 0.025, ez)
      boxes.add(roof)
      // Open side = dominant axis of the elevator position, sign toward
      // the centre; glass on the three other sides.
      const openSide = Math.abs(ex) >= Math.abs(ez)
        ? (ex > 0 ? 'west' : 'east')
        : (ez > 0 ? 'north' : 'south')
      const glassMat = new THREE.MeshStandardMaterial({
        color: 0x9fc2d8, transparent: true, opacity: 0.22,
      })
      const sides: Array<['north' | 'south' | 'east' | 'west', number, number, number, number]> = [
        ['north', ex, ez - outer / 2, outer, 0.03],
        ['south', ex, ez + outer / 2, outer, 0.03],
        ['west', ex - outer / 2, ez, 0.03, outer],
        ['east', ex + outer / 2, ez, 0.03, outer],
      ]
      for (const [side, gx, gz, w2, d2] of sides) {
        if (side === openSide) continue
        const glass = new THREE.Mesh(new THREE.BoxGeometry(w2, shaftTop, d2), glassMat)
        glass.position.set(gx, shaftTop / 2, gz)
        boxes.add(glass)
      }
      const padMat = new THREE.MeshStandardMaterial({ color: 0xaab4be })
      for (const lv of (usedLevels.length ? usedLevels : [0])) {
        const pad = new THREE.Mesh(
          new THREE.BoxGeometry(1.6 * kEl, 0.05, 1.6 * kEl), padMat)
        pad.position.set(ex, lv * lhEff + 0.08 - 0.025, ez)
        boxes.add(pad)
      }
      const cab = new THREE.Mesh(
        new THREE.BoxGeometry(1.4 * kEl, Math.max(0.6 * lhEff, 0.3), 1.4 * kEl),
        new THREE.MeshStandardMaterial({ color: 0x3d4650, transparent: true, opacity: 0.85 }),
      )
      cab.position.set(ex, 0.08 + Math.max(0.6 * lhEff, 0.3) / 2, ez)
      boxes.add(cab)
    }

    // Building shell over everything — ghosted so the rooms stay visible.
    // DETAIL-view scale is PER AXIS: the footprint (XZ) always follows the
    // plan (tile fit, largest XZ side = 10 × 0.92 × map3d.size) so the
    // floor-plan rectangles land on the shell; the height (Y) follows
    // height_m when declared. With correct mesh proportions both factors
    // coincide (no distortion) — a too-flat relief gets exactly the
    // repair it needs. Yaw per contract chain: map3d.rotation, absent →
    // map_rotation_2d (the model turns with the 2D icon), else 0.
    let buildingTopY = 0
    if (showBuildingRef.current) {
      const building = bAnchor
      if (building) {
        if (!building.ghost) {
          // Keep the model's own textures — a flat gray ghost was near
          // invisible on the dark canvas. Unlit (basic) + semi-transparent +
          // no depth write: clearly the building, rooms shine through.
          const g = building.obj.clone(true)
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
          building.ghost = g
        }
        const clone = building.ghost.clone(true)
        const metaG = new THREE.Group()
        metaG.add(clone)
        metaG.rotation.set(deg(building.rotation.x), deg(building.rotation.y),
                           deg(building.rotation.z))
        const mapYaw = m3?.rotation !== undefined ? m3.rotation : fallbackYawDeg
        // Contract order: meta fix first, THEN the map yaw as its own parent.
        const holder = new THREE.Group()
        holder.add(metaG)
        holder.rotation.y = -deg(mapYaw)
        holder.updateMatrixWorld(true)
        const br = new THREE.Box3().setFromObject(holder)
        const sr = br.getSize(new THREE.Vector3())
        const kxz = (10 * 0.92 * (m3?.size || 0.92)) / (Math.max(sr.x, sr.z) || 1)
        const ky = building.heightM > 0
          ? (building.heightM * kFac) / (sr.y || 1)
          : kxz
        // Per-axis scale in WORLD space — the outer group sits above the
        // rotation fix, so a lying model raised by 90° stretches upward.
        const outer = new THREE.Group()
        outer.add(holder)
        outer.scale.set(kxz, ky, kxz)
        outer.updateMatrixWorld(true)
        const b2 = new THREE.Box3().setFromObject(outer)
        const c2 = b2.getCenter(new THREE.Vector3())
        outer.position.set(-c2.x + (building.offsetX || 0),
                           0.06 - b2.min.y + building.offsetY,
                           -c2.z + (building.offsetZ || 0))
        outer.userData.__noDispose = true
        boxes.add(outer)
        buildingTopY = 0.06 + building.offsetY + (b2.max.y - b2.min.y)
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

      // Comparison figure at the ruler: the room-scale Mixamo test figure
      // (1.7 m × level_height/3) standing on the ground next to the metre
      // scale — storey height vs. figure height is judgeable at a glance.
      {
        const target = planW > 0 ? 1.7 * kFac : 1.7 * (lhEff / 3)
        const fig = new THREE.Group()
        const figSrc = ensureTestFigure()
        const kinds = clipListRef.current.clips.map((c) => c.kind)
        const kind = kinds.includes('idle') ? 'idle'
          : kinds.includes('stand') ? 'stand' : kinds[0]
        const anim = figSrc && kind ? ensureClip(kind) : null
        if (figSrc && anim) {
          const inst = h.skclone(figSrc)
          const pivot = new THREE.Group()
          pivot.add(inst)
          // Same up-axis fix as the marker figures (rest skeletons only).
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
            for (const rxc of [0, Math.PI / 2, -Math.PI / 2, Math.PI]) {
              const cand = new THREE.Quaternion()
                .setFromEuler(new THREE.Euler(rxc, 0, 0)).multiply(restModel)
              const angle = cand.angleTo(restClip)
              if (angle < bestAngle) { bestAngle = angle; bestRx = rxc }
            }
            pivot.rotation.x = bestRx
          }
          // Same rest-pose measurement as the marker figures.
          pivot.updateMatrixWorld(true)
          const fb = new THREE.Box3().setFromObject(pivot)
          const fs = fb.getSize(new THREE.Vector3())
          const k = target / (fs.y || 1)
          const mixer = new THREE.AnimationMixer(inst)
          mixer.clipAction(anim.clip).play()
          mixer.update(0)
          mixersRef.current.push(mixer)
          pivot.scale.setScalar(k)
          pivot.updateMatrixWorld(true)
          const fb2 = new THREE.Box3().setFromObject(pivot)
          const fc2 = fb2.getCenter(new THREE.Vector3())
          pivot.position.set(-fc2.x, -fb2.min.y, -fc2.z)
          pivot.userData.__noDispose = true
          fig.add(pivot)
        } else {
          // Mannequin fallback while figure/clip load (or are missing).
          const figMat = new THREE.MeshStandardMaterial({
            color: 0x8b949e, transparent: true, opacity: 0.85,
          })
          const body = new THREE.Mesh(
            new THREE.CapsuleGeometry(0.055 * target, 0.62 * target, 4, 10), figMat)
          body.position.y = 0.42 * target
          fig.add(body)
          const head = new THREE.Mesh(
            new THREE.SphereGeometry(0.09 * target, 12, 12), figMat)
          head.position.y = 0.88 * target
          fig.add(head)
        }
        // Facing the plate, just inside the ruler corner.
        fig.position.set(rx + 0.55, 0, rz - 0.35)
        fig.rotation.y = Math.PI / 4
        boxes.add(fig)
      }
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
      fallbackYawDeg])

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
        {t('Renders per the client contract (8×8 m reference, 0.96 fit, floor + 0.12 m; building: largest side = 10 × 0.92 × size m) — metre ruler + storey lines check the level height against the model.')}
      </span>
    </div>
  )
}
