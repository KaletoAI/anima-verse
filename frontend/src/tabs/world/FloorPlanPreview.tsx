/**
 * FloorPlanPreview — live 3D preview of the room layout (AV3D-2), shown next
 * to the floor-plan editor. Since v4 it is CONSUMER No. 1 of the server's
 * scene recipe (shared/schnittstellen-3d.md part B): the current editor
 * draft goes to POST /play/scene-preview and what comes back is rendered as
 * it is — plates, walls, extras, model placement specs, figures and markers,
 * all in world metres around the tile centre.
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
import { apiGet } from '../../lib/api'
import { applyCutouts, buildExtra, buildPlaceholder, buildPlate, buildWall,
  drapeGeometry,
  applyClipOutline, disposeClipMaterials, pickVariant, placeModelSpec, plateTargets,
  SpecVerifier,
  VERIFY_EPS, surfaceMaterial, updateSurfaceMaterials, wallLength,
  wallTargets } from '@anima/scene-render'
import type { CutoutHandle, SurfaceMaterialSpec, VerifyRow } from '@anima/scene-render'
import type { Map3D, Room, SceneModelSpec, ScenePayload } from './worldTypes'
import { buildMeasureAids, disposeAids, useActiveMeasure,
  type MeasureKey } from './measureKit'

// The reference square is the preview's stage — ground plate, ruler position
// and camera framing. Its WORLD size is a per-location dial and arrives in
// the payload (`extent_m`); this is only the value before the first response.
// It used to be a hardcoded 8 while the model filled 10 × 0.92 × size, which
// is exactly why plan and model could not line up (2026-07-28).
const DEFAULT_EXTENT_M = 10
const DEFAULT_STOREY_REAL_M = 3
// Preview AIDS — deliberately NOT part of the scene style (which covers
// walls, floors, glass and the room palette): these paint things only the
// admin preview shows. Elevator colours come from the payload's style block.
const AID = {
  marker: 0x3fb950,
  markerLabel: '#7ee2a0',
  placeholder: 0xd29922,
  figure: 0x8b949e,
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
  /** Real-size anchor of a ROOM model (0 = undeclared): the real width of
   *  its largest side. Buildings have none — their size follows the
   *  location's extent × size. */
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
  /** Storey height in REAL metres (map3d.storey_height_m) — empty = 3. */
  storeyHeightM?: number
  /** When set, the toolbar shows the storey-height field next to the metre
   *  scale (writes map3d.storey_height_m on the location draft). */
  onStoreyHeight?: (v: number | undefined) => void
  /** When set, the toolbar shows the plan-width anchor field (writes
   *  map3d.plan_width_m on the location draft). */
  onPlanWidth?: (v: number | undefined) => void
  /** Which metre dial is being edited RIGHT NOW — decides which reference
   *  size the preview shows (measureKit). The preview owns the state for its
   *  own toolbar fields; a parent may override for fields it hosts itself. */
  measure?: MeasureKey
  /** The 2D icon rotation (map_rotation_2d) — the contract's yaw fallback
   *  when map3d.rotation is unset (the model turns with the 2D icon). */
  fallbackYawDeg?: number
  /** The server-composed scene of the current draft (useScenePreview in the
   *  parent — the 2D editor reads the same response). null = not there yet
   *  or the composer failed; then there is nothing to render. */
  scene: ScenePayload | null
  sceneError?: string
  /** Calibration figure (§ B2a): the FIXED 1.70 m reference standing IN a
   *  room while its width_m / walk_y are dialed. ``at`` = fraction of the
   *  room rectangle (click on the 2D plan); absent = the diorama anchor.
   *  Pure UI state, never persisted. */
  calibration?: { roomId: string; at?: [number, number] } | null
  height?: number
}

export function FloorPlanPreview({ locationId, rooms, map3d, storeyHeightM, onStoreyHeight, onPlanWidth, fallbackYawDeg = 0, scene, sceneError = '', calibration = null, measure: measureProp, height = 540 }: FloorPlanPreviewProps) {
  const { t } = useI18n()
  // Reference sizes: the toolbar's own fields drive them; a parent may push
  // one in for a field it hosts (the model tab does that).
  const { measure: ownMeasure, bind: bindMeasure } = useActiveMeasure()
  const measure = measureProp ?? ownMeasure
  const mountRef = useRef<HTMLDivElement>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [showModels, setShowModels] = useState(false)
  const [showBuilding, setShowBuilding] = useState(false)
  // "Walls & floor" overlay — the client's render recipe (schnittstellen
  // → "Render-Rezept Wände & Boden"): outline floor plates + outer walls
  // with door gaps at the ground-floor doors.
  // Plates and walls ARE the scene — having them off by default meant the
  // preview opened without the room floors, which is the reference you dial
  // heights against (user finding 2026-07-28).
  const [showWalls, setShowWalls] = useState(true)
  // Exclusive level view: null = all levels, a number renders ONLY that
  // storey (rooms, plates, walls, figures) — the ruler and the building
  // overlay stay, the elevator shaft only shows with all levels visible.
  const [soloLevel, setSoloLevel] = useState<number | null>(null)
  // Verify mode (contract § B5a): arithmetic instead of screenshots — after
  // every rebuild the placed objects are re-measured and diffed against the
  // spec they were built from.
  const [verify, setVerify] = useState(false)
  const verifyRef = useRef(verify)
  verifyRef.current = verify
  const [verifyReport, setVerifyReport] = useState<{
    checked: number; rows: VerifyRow[]; notes: string[] } | null>(null)
  // Model-load completion re-triggers the rebuild (loads are async, the
  // rebuild itself is synchronous against the cache).
  const [bump, setBump] = useState(0)
  // Triangle budget of the last rebuild — what the location costs to draw.
  const [budget, setBudget] = useState<{ tris: number; meshes: number
    models: number } | null>(null)
  // Scene handle for the incremental rebuild (drag updates arrive per
  // pointermove — recreating the whole renderer would thrash).
  const handleRef = useRef<{
    THREE: typeof import('three')
    boxes: Group
    skclone: (obj: Object3D) => Object3D
    /** The filled reference square at height 0. It is NOT level-bound, so the
     *  solo view of a BASEMENT has to see through it. */
    ground: Mesh
  } | null>(null)
  // Cutout handle of the last rebuild (area locations): its material clones
  // must be released before the next one patches fresh clones.
  const cutoutRef = useRef<CutoutHandle | null>(null)
  // Plate + edge loop of the reference square — both are unit-sized and get
  // scaled to the payload's extent_m on every rebuild.
  const squareRef = useRef<Object3D[] | null>(null)
  // Reference-size overlay of the last rebuild (its own sprites/materials).
  const aidsRef = useRef<Group | null>(null)
  const measureRef = useRef<MeasureKey>(null)
  measureRef.current = measure
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
    map: Map<string, { url: string; sizeM: number
                       material?: SurfaceMaterialSpec | null }> }>(
    { status: 'idle', map: new Map() })
  const surfaceTexRef = useRef<Map<string, unknown>>(new Map())
  const clipListRef = useRef<{ status: 'idle' | 'loading' | 'ready' | 'missing'
    clips: Array<{ kind: string; set: string; url: string }> }>({ status: 'idle', clips: [] })
  const clipCacheRef = useRef<Map<string, { clip: AnimationClip; restObj: Object3D } | 'loading' | 'missing'>>(new Map())
  const mixersRef = useRef<AnimationMixer[]>([])
  const clockRef = useRef<Clock | null>(null)

  // Stand-in until the first payload: the declared REAL storey height read as
  // if k were 1. From then on `scene.storey_m` decides.
  const lh = storeyHeightM && storeyHeightM > 0 ? storeyHeightM : DEFAULT_STOREY_REAL_M

  // The whole geometry arrives from the server (contract § B1/B3) — the
  // parent holds the debounced draft request, this component only renders.
  const sceneRef = useRef<ScenePayload | null>(null)
  sceneRef.current = scene
  const calibrationRef = useRef(calibration)
  calibrationRef.current = calibration

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
        cacheRef.current.delete(`building:${locationId}`)
      }
      setBump((b) => b + 1)
    }
    window.addEventListener('anima-model3d-changed', onChanged)
    return () => window.removeEventListener('anima-model3d-changed', onChanged)
  }, [locationId])

  // The plan width is the ONLY scale anchor since 2026-07-28 — there is no
  // second path to derive it from a model any more (that one existed to feed
  // the per-axis height scaling, which is gone). Missing = mandatory field.
  const anchorMissing = !(map3d?.plan_width_m && map3d.plan_width_m > 0)

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
          width_m?: number }>(`${base}/meta`)
        const fmt = (meta.format || 'glb').toLowerCase()
        if (fmt !== 'glb' && fmt !== 'gltf') throw new Error(`format ${fmt}`)
        const { GLTFLoader } = await import('three/examples/jsm/loaders/GLTFLoader.js')
        const gltf = await new GLTFLoader().loadAsync(meta.url || base)
        cache.set(key, { obj: gltf.scene, rotation: meta.rotation || {},
                         offsetY: meta.offset_y || 0,
                         offsetX: meta.offset_x || 0,
                         offsetZ: meta.offset_z || 0,
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
    // A basement lies BELOW the reference square, and that square is not
    // level-bound — it stayed in the picture and covered the very storey the
    // solo view was opened for. While a level < 0 is soloed it goes ghost;
    // depthWrite off as well, so it cannot occlude what is underneath. The
    // edge loop stays as it is: a line hides nothing and it keeps the plan's
    // extent readable.
    {
      const under = solo !== null && solo < 0
      const gm = h.ground.material as Material & { opacity: number }
      gm.transparent = under
      gm.opacity = under ? 0.15 : 1
      gm.depthWrite = !under
      gm.needsUpdate = true
    }
    // Scalars come FROM THE PAYLOAD (contract § A1): k = world metres per
    // real metre, storey_m = the derived storey height. Until the first
    // response arrives the preview stands on the unscaled defaults.
    const sc = sceneRef.current
    const kFac = sc ? sc.k : 1
    const lhEff = sc ? sc.storey_m : lh
    // The ONE number that turns a plan fraction into metres — from the
    // payload, never a constant (that was the 8-vs-9.2 drift).
    const PLATE_M = sc?.extent_m || DEFAULT_EXTENT_M
    for (const o of squareRef.current || []) o.scale.set(PLATE_M, PLATE_M, 1)
    // A ground location brings its own floor: the stage plate would cut the
    // model at y = 0 exactly like the 3D client's tile plate did (Mondscheinsee
    // spans −0.80 … +2.69). The edge loop stays — it is the frame, not a floor.
    // `shell_area` (v5.2) deliberately does NOT match: in the interior view —
    // which this preview IS — that model is faded out, and the plate is the
    // backstop under the detail scene, exactly what the client shows close up.
    const groundLoc = (sc?.models || []).some(
      (m) => m.role === 'building' && m.display === 'ground')
    if (h.ground) h.ground.visible = !groundLoc
    const style = sc?.style
    const figBase = sc ? sc.figures.base_height_m_world : 1.7
    // Hex colour of the payload style ('#rrggbb' → three.js number).
    const hex = (c: string | undefined, fallback: number): number => {
      const v = parseInt((c || '').replace('#', ''), 16)
      return Number.isFinite(v) ? v : fallback
    }
    const visibleLevel = (lv: number) => solo === null || lv === solo

    // ── Verify (contract § B5a): arithmetic instead of screenshots ──────
    // The scene recipe is the TARGET. After building, every object is
    // re-measured in world space and diffed against the spec it came from;
    // findings travel between sessions as numbers, never as pictures.
    // The diff itself lives in @anima/scene-render — the SAME arithmetic the
    // 3D client runs, so a number measured here means the same thing there.
    // The admin preview is built around the origin, hence the zero reference.
    const verifier = new SpecVerifier(THREE)
    const VERIFY_ORIGIN = new THREE.Vector3()
    // Facts the arithmetic CANNOT check: a shell clip discards fragments, not
    // geometry, so the rendered BBox stays the unclipped one (§ B1). The
    // report names where clipping is active instead of pretending to measure it.
    const verifyNotes: string[] = []
    const verifyPlacement = (obj: Object3D, spec: SceneModelSpec) => {
      if (spec.clip_outline?.length) {
        verifyNotes.push(`${spec.role}:${spec.id} clip: ${spec.clip_outline.length} points`)
      }
      verifier.placement(obj, spec, VERIFY_ORIGIN)
    }
    // The building entry is fetched regardless of the overlay toggle — the
    // model panel's fields read it.
    // Keyed by LOCATION: a plain 'building' key survived a location switch,
    // so the preview kept showing the previous location's model until the
    // whole editor unmounted (user finding 2026-07-28). Room ids are unique
    // on their own.
    const bAnchor = ensureModel(`building:${locationId}`)
    for (const mixer of mixersRef.current) mixer.stopAllAction()
    mixersRef.current = []
    // Recursive disposal that BAILS on __noDispose subtrees — cached-model
    // and test-figure clones share geometry/materials with their caches
    // (a plain traverse would visit and kill the shared resources).
    const disposeSafe = (o: Object3D) => {
      if (o.userData.__noDispose) {
        // The subtree's geometry/textures belong to the cache — but a shell
        // clip put PRIVATE material clones on it (§ B1), and those are ours.
        disposeClipMaterials(o)
        return
      }
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
    // The previous rebuild's cutout clones go before the subtree does — they
    // sit on __noDispose clones that disposeSafe deliberately leaves alone.
    cutoutRef.current?.dispose()
    cutoutRef.current = null
    for (const child of [...boxes.children]) {
      boxes.remove(child)
      disposeSafe(child)
    }

    const deg = (v?: number) => ((v || 0) * Math.PI) / 180

    // ── THE placement routine (contract § B2) ──────────────────────────
    // Building, room diorama and prop differ only in the SPEC the server
    // sends — never in code. Chain: fix_euler ('XYZ') on the inner group →
    // measure → ONE uniform scale (max_m / measured extent) → yaw as the
    // PARENT rotation (never
    // combined into one Euler, an x/z fix would tilt with it) → measure the
    // result and seat its BBox on bottom_y / anchor.
    const placeSpec = (source: Object3D, spec: SceneModelSpec): Object3D => {
      const outer = placeModelSpec(THREE, source, spec)
      outer.userData.__noDispose = true
      boxes.add(outer)
      // Room clip (§ B1): the client discards diorama fragments outside the
      // room hull — without the same call here the preview showed the FULL
      // diorama including its baked surroundings and diverged massively from
      // the client. Preview coordinates ARE payload world coordinates, so
      // the polygon applies as-is; disposeSafe already frees the clones.
      if (spec.clip_outline?.length) {
        applyClipOutline(THREE, outer, spec.clip_outline)
      }
      if (verifyRef.current) verifyPlacement(outer, spec)
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
            offsetY: 0, widthM: 0 })
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
      apiGet<Array<{ kind?: string; url?: string; size_m?: number
                     material?: SurfaceMaterialSpec | null }>>(
        '/assets/surface-textures')
        .then((list) => {
          for (const entry of Array.isArray(list) ? list : []) {
            if (entry?.kind && entry.url)
              s.map.set(entry.kind, { url: entry.url, sizeM: entry.size_m || 1,
                                material: entry.material ?? null })
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
                                 tilt?: number; roll?: number
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
      // Facing is the compass, tilt/roll lean the figure out of the upright —
      // applied in the figure's own frame, i.e. AFTER the yaw ('YXZ' puts the
      // yaw first, so tilt stays "head up/down" and roll "sideways").
      fig.rotation.order = 'YXZ'
      fig.rotation.set(deg(opts.tilt), deg(opts.facing ?? 0), deg(opts.roll))
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
        // Area location: the model keeps standing and gets its holes. The
        // preview IS the interior view, so they are always on — no fade state
        // to follow here. Polygons are world metres around the origin, which
        // is exactly where this preview builds.
        if (spec.cutouts?.length) {
          cutoutRef.current = applyCutouts(THREE, placed, spec.cutouts)
          cutoutRef.current.setEnabled(true)
        }
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
      // Tier (§ B1 variants): stage 1 requests `full` everywhere — the
      // distance-based choice is stage 3 (plan-3d-lod-und-betreten.md).
      const propUrl = pickVariant(spec.variants, 'full')
      const entry = propUrl ? ensurePropModel(spec.id, propUrl) : null
      if (entry) {
        placeSpec(entry.obj, spec)
      } else if (spec.placeholder_dims) {
        // The builder's box sits on its own bottom face, so it seats on
        // bottom_y like a placed mesh — the wireframe look stays ours.
        const standIn = buildPlaceholder(THREE, spec.placeholder_dims,
          new THREE.MeshBasicMaterial({ color: AID.placeholder, wireframe: true }))
        // `+rad` since E4 (§ A1.1) — the FOURTH renderer of `spec.yaw_deg`,
        // next to `placeModelSpec` (@anima/scene-render), the 3D client's own
        // placeholder and the model viewer. Its sibling real mesh two lines up
        // goes through `placeSpec` → `placeModelSpec`, so a minus here would
        // draw the stand-in of a prop at yaw 30 turned to −30 while the mesh
        // that replaces it stands at +30 — in the one surface whose whole job
        // is judging placement.
        standIn.rotation.y = deg(spec.yaw_deg)
        standIn.position.set(spec.anchor[0], spec.bottom_y, spec.anchor[1])
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

    // ── Markers (payload, world coordinates) ──────────────────────────
    const levelOfRoom = new Map<string, number>(
      current.filter((r) => r.id && r.layout)
        .map((r) => [r.id as string, r.layout!.level || 0]))
    // Calibration figure (§ B2a): the FIXED 1.70 m reference INSIDE the room
    // — the admin dials width_m until the furniture matches it, and walk_y
    // until it stands on the visible floor. It never scales with either.
    const calib = calibrationRef.current
    if (sc && calib?.roomId) {
      const room = current.find((r) => r.id === calib.roomId)
      const lay = room?.layout
      if (lay && visibleLevel(lay.level || 0)) {
        const spec = sc.models.find(
          (m) => m.role === 'room' && m.room_id === calib.roomId)
        const plate = sc.plates.find((p) => p.room_id === calib.roomId)
        const at = calib.at
        placeFigure({
          x: at ? (lay.x + at[0] * lay.w - 0.5) * PLATE_M
            : spec?.anchor[0] ?? (lay.x + lay.w / 2 - 0.5) * PLATE_M,
          // Standing height: the room's declared walkable floor, else the
          // room plate, else the storey floor — all from the payload.
          y: spec?.walk_y_world ?? plate?.top_y ?? (lay.level || 0) * lhEff,
          z: at ? (lay.y + at[1] * lay.d - 0.5) * PLATE_M
            : spec?.anchor[1] ?? (lay.y + lay.d / 2 - 0.5) * PLATE_M,
          facing: 0,
        })
      }
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
        x: marker.at_world[0],
        // y_world is the SURFACE; the figure's root sits root_offset below it
        // (a seated body touches at the buttocks). Same subtraction as the
        // 3D client — the number comes from the payload, not from here.
        y: marker.y_world - (marker.root_offset || 0), z: marker.at_world[1],
        animation: marker.animation, facing: marker.facing,
        tilt: marker.tilt, roll: marker.roll,
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
    // decides geometry — the boxes and extrusions themselves are built by
    // @anima/scene-render, the same routines the 3D client runs. What stays
    // here is the MATERIAL (preview colours, texture tiling) and the view
    // state (level solo, toggles, the camera culling that uses the delivered
    // outward_normal).
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
        const info = plate.texture_kind ? ensureSurfaceTex(plate.texture_kind) : null
        let mat: Material
        // Aussehen der ART aus dem geteilten Paket — derselbe See wie im
        // 3D-Client, matt bleibt der Default.
        const kindMat = plate.texture_kind
          ? surfaceListRef.current.map.get(plate.texture_kind)?.material ?? null : null
        if (info?.tex) {
          const tile = info.sizeM * kFac
          const tex = (info.tex as Texture).clone()
          tex.needsUpdate = true
          tex.repeat.set(1 / tile, 1 / tile)
          mat = surfaceMaterial(THREE, { material: kindMat, map: tex,
            transparent: upper, opacity: upper ? upperFloor : 1 })
        } else {
          mat = surfaceMaterial(THREE, { material: kindMat, color: floorColor,
            transparent: upper, opacity: upper ? upperFloor : 1 })
        }
        const mesh = buildPlate(THREE, plate, mat)
        if (plate.relief && sc.terrain) {
          // Terrain relief (§ B1 Nr. 14): an outdoor plate of a non-flat room
          // follows the height field instead of lying on top_y — subdivided
          // and raised through the SAME sampler the 3D client uses, so the
          // preview shows the slope the game shows. The stage plate below
          // stays flat on purpose: it is the reference square, a measuring
          // aid, not ground.
          mesh.updateMatrix()
          const flat = mesh.geometry
          mesh.geometry = drapeGeometry(THREE, flat, sc.terrain, PLATE_M,
                                        mesh.matrix)
          flat.dispose()
        }
        boxes.add(mesh)
        if (verifyRef.current) {
          verifier.primitive(mesh, VERIFY_ORIGIN,
            `plate:${plate.room_id || 'level'}@${plate.level}`, plateTargets(plate))
        }
      }

      // Wall segments. Doors/passages are already gaps, a window arrives as
      // sill + head + its own glass entry — one box each.
      for (const wall of sc.walls) {
        if (!visibleLevel(wall.level)) continue
        const len = wallLength(wall)
        if (len < 1e-4) continue
        const upper = wall.opacity_role === 'upper'
        let mat: Material
        // World size of one texture tile; 0 = untextured, nothing to tile.
        // BoxGeometry normalises the uvs of EVERY face to 0..1, so the tiling
        // has to go into the geometry (buildWall) — a repeat on the material
        // is computed from the broad wall face and would crush the texture on
        // every jamb, reveal and sill of a door or window.
        let tileM = 0
        if (wall.glass) {
          mat = new THREE.MeshStandardMaterial({
            color: glassColor, transparent: true, opacity: glassOpacity,
          })
        } else {
          const info = wall.texture_kind ? ensureSurfaceTex(wall.texture_kind) : null
          const kindMat = wall.texture_kind
            ? surfaceListRef.current.map.get(wall.texture_kind)?.material ?? null : null
          if (info?.tex) {
            tileM = info.sizeM * kFac
            // Still one clone per wall: the uv scale differs per segment, and a
            // shared texture would have every mesh fight over its filtering.
            const tex = (info.tex as Texture).clone()
            tex.needsUpdate = true
            mat = surfaceMaterial(THREE, { material: kindMat, map: tex,
              transparent: upper, opacity: upper ? upperWall : 1 })
          } else {
            mat = surfaceMaterial(THREE, { material: kindMat, color: wallColor,
              transparent: upper, opacity: upper ? upperWall : 1 })
          }
        }
        const box = buildWall(THREE, wall, mat, tileM)
        boxes.add(box)
        // Camera culling with the DELIVERED normal — a wall whose outside
        // faces the camera hides so the interior stays visible.
        if (!wall.glass) {
          wallCullRef.current.push({ mesh: box,
            mx: (wall.from[0] + wall.to[0]) / 2,
            mz: (wall.from[1] + wall.to[1]) / 2,
            nx: wall.outward_normal[0], nz: wall.outward_normal[1] })
        }
        if (verifyRef.current) {
          verifier.primitive(box, VERIFY_ORIGIN,
            `wall:${wall.room_id || 'contour'}@${wall.level}`, wallTargets(wall))
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
              color: glassColor, transparent: true,
              opacity: sc.style.elevator_glass_opacity })
          : new THREE.MeshStandardMaterial({
              color: hex(extra.kind === 'elevator_pad'
                ? sc.style.elevator_pad_color
                : extra.kind === 'elevator_cabin'
                  ? sc.style.elevator_cabin_color
                  : sc.style.elevator_frame_color, 0x6d7681),
              transparent: extra.kind === 'elevator_cabin',
              opacity: extra.kind === 'elevator_cabin'
                ? sc.style.elevator_cabin_opacity : 1 })
        boxes.add(buildExtra(THREE, extra, mat))
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

    // ── Reference sizes for the metre dials (measureKit) ────────────────
    // No number in real metres without something human beside it; which
    // ruler shows follows the field the cursor sits in.
    disposeAids(aidsRef.current)
    aidsRef.current = buildMeasureAids(THREE, {
      measure: measureRef.current,
      extentM: PLATE_M,
      k: kFac,
      planWidthM: map3dRef.current?.plan_width_m || 0,
      storeyWorld: lhEff,
      storeyRealM: kFac > 0 ? lhEff / kFac : lhEff,
      figureHeightWorld: figBase,
      modelWidthM: sc?.models.find((m) => m.role === 'building')?.max_m,
      modelBottomY: sc?.models.find((m) => m.role === 'building')?.bottom_y,
      walkYWorld: sc?.models.find((m) => m.role === 'building')?.walk_y_world,
      levels: usedLevels,
      words: { ground: t('Level 0'), walk: t('Ground'), of: t('of') },
    })
    boxes.add(aidsRef.current)

    // Verify report (§ B5a): machine-readable, deviations one by one with
    // actual/target. The console table is the one that travels between
    // sessions; the overlay is just the hint that it is there.
    if (verifyRef.current) {
      if (verifier.rows.length) {
        console.warn(`[verify] ${verifier.rows.length} deviation(s) > ${VERIFY_EPS} m `
          + `in ${verifier.checked} checked numbers`)
        console.table(verifier.rows)
      } else {
        console.info(`[verify] ${verifier.checked} numbers checked, `
          + `no deviation > ${VERIFY_EPS} m`)
      }
      if (verifyNotes.length) console.info(`[verify] ${verifyNotes.join(' · ')}`)
      setVerifyReport({ checked: verifier.checked, rows: verifier.rows,
                        notes: verifyNotes })
    } else {
      setVerifyReport(null)
    }

    // Triangle budget of the WHOLE location as built (plates, walls, models,
    // scattered copies, placeholders) — everything the rebuild put into
    // `boxes`. This is the number the frame rate rides on: a scattered prop
    // shares its geometry between clones, but every clone is its own draw
    // call and its triangles render each frame.
    {
      let tris = 0
      let meshes = 0
      boxes.traverse((o) => {
        const mesh = o as Mesh
        if (!mesh.isMesh || mesh.visible === false) return
        const g = mesh.geometry as { index?: { count: number } | null
          attributes?: { position?: { count: number } } } | undefined
        const n = g?.index ? g.index.count : g?.attributes?.position?.count || 0
        if (n > 0) {
          tris += Math.round(n / 3)
          meshes += 1
        }
      })
      const modelCount = (sc?.models || []).length
      setBudget({ tris, meshes, models: modelCount })
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

        // Ground plate = the location's reference square, plus outline. Built
        // as a 1 × 1 plane and SCALED to `extent_m` on every rebuild — the
        // square is a per-location dial now, not a constant.
        const groundGeo = new THREE.PlaneGeometry(1, 1)
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
        squareRef.current = [ground, outline]

        const boxes = new THREE.Group()
        scene.add(boxes)
        disposers.push(() => {
          const disposeSafe = (o: Object3D) => {
            if (o.userData.__noDispose) { disposeClipMaterials(o); return }
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
        handleRef.current = { THREE, boxes, skclone, ground }
        disposers.push(() => { handleRef.current = null })
        rebuild(handleRef.current, roomsRef.current)

        // Initial framing: distance so the reference square fits comfortably.
        const ext0 = sceneRef.current?.extent_m || DEFAULT_EXTENT_M
        cam.dist = cam.distGoal = Math.max(
          6, (ext0 * 1.2 / 2) / Math.tan((Math.PI * camera.fov) / 360) * 1.35)
        applyCamera()

        setLoading(false)

        let raf = 0
        const animate = () => {
          raf = requestAnimationFrame(animate)
          const delta = clockRef.current?.getDelta() || 0
          updateSurfaceMaterials(delta)   // eine Zeit für alle Wasserflächen
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
      fallbackYawDeg, scene, calibration, verify, measure])

  return (
    <div className="ga-form" style={{ gap: 6 }}>
      {/* Icon toolbar — the toggles/anchors read via tooltip, not label text
          (the plan pane is the busy one, this row stays quiet). */}
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <div className="ga-form-section-label" style={{ margin: 0, flex: 1 }}>{t('3D preview')}</div>
        {budget ? (
          <span
            className="ga-hint"
            style={{ fontSize: 11,
              color: budget.tris > 500_000 ? 'var(--danger, #f85149)'
                : budget.tris > 250_000 ? '#d29922' : undefined }}
            title={t('Triangle budget of THIS location as built (models, scattered copies, plates, walls). Guideline: stay under ~250k triangles per location, 500k is where weak clients hurt — scattered props should be lean meshes (2–5k triangles, face count in the mesh dialog), single furniture up to ~20k. Every scattered copy is its own draw call.')}
          >
            △ {budget.tris >= 1000
              ? `${Math.round(budget.tris / 1000)}k` : budget.tris}
            {' · '}{budget.models} {t('models')}
          </span>
        ) : null}
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
          title={t('Walls & floor — render the outline floor plates and outer walls exactly like the game client (doors at the ground-floor doorways; walls facing the camera hide). Needs a drawn outline.')}
        >
          🧱
        </button>
        <button
          type="button"
          className={`ga-btn ga-btn-sm${verify ? ' ga-btn-primary' : ''}`}
          onClick={() => setVerify((v) => !v)}
          title={t('Verify — re-measure every placed object and diff it against the scene recipe (tolerance 0.01 m). Deviations land in the browser console as a table with actual/target; that table is the evidence, not a screenshot.')}
        >
          ✓
        </button>
        {onPlanWidth ? (
          <label className="ga-check-row"
            title={anchorMissing
              ? t('Plan width (m) is REQUIRED: it is the only scale anchor. Without it nothing has a real size — figures, props and storeys fall back to a meaningless legacy scale and floor-plan geometry cannot be saved.')
              : t('Plan width (m): how wide this location is in REAL metres — the edge of its footprint on the world map AND the square the floor plan is drawn in. THE scale anchor: every other length (figures at 1.70 m, props, dioramas, storeys) is a real metre measured against it.')}>
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
              placeholder="—"
              {...bindMeasure('plan_width')}
              onChange={(e) => {
                const n = parseFloat(e.target.value)
                onPlanWidth(Number.isFinite(n) && n > 0 ? n : undefined)
              }}
            />
          </label>
        ) : null}
        {onStoreyHeight ? (
          <label className="ga-check-row"
            title={t('Storey height (m): the height of one storey in REAL metres — a normal room is 2.5 to 3. It stacks the floor-plan levels; the world height follows from the plan width like every other length.')}>
            <span>↕</span>
            <input
              className="ga-input"
              type="number"
              min={0.5}
              max={50}
              step={0.1}
              style={{ width: 70 }}
              value={storeyHeightM ?? ''}
              placeholder="3"
              {...bindMeasure('storey')}
              onChange={(e) => {
                const n = parseFloat(e.target.value)
                onStoreyHeight(Number.isFinite(n) && n > 0 ? n : undefined)
              }}
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
        {verifyReport ? (
          <div style={{
            position: 'absolute', left: 8, top: 8, maxWidth: '70%',
            padding: '6px 8px', borderRadius: 6, fontSize: '0.78em',
            background: 'rgba(13,17,23,0.85)', pointerEvents: 'none',
            border: `1px solid ${verifyReport.rows.length ? '#f85149' : '#3fb950'}`,
          }}>
            <div style={{ fontWeight: 600,
              color: verifyReport.rows.length ? '#f85149' : '#3fb950' }}>
              {t('{n} numbers checked, {m} deviations')
                .replace('{n}', String(verifyReport.checked))
                .replace('{m}', String(verifyReport.rows.length))}
            </div>
            {verifyReport.rows.slice(0, 6).map((r, i) => (
              <div key={i} style={{ color: '#f85149', fontFamily: 'monospace' }}>
                {`${r.object} ${r.field}: ${r.actual} ≠ ${r.target} (Δ ${r.delta})`}
              </div>
            ))}
            {verifyReport.rows.length > 6 ? (
              <div style={{ opacity: 0.8 }}>{t('…full table in the console')}</div>
            ) : null}
            {verifyReport.notes.map((n, i) => (
              <div key={`n${i}`} style={{ opacity: 0.8, fontFamily: 'monospace' }}>{n}</div>
            ))}
          </div>
        ) : null}
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
