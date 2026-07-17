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
import { useEffect, useRef, useState } from 'react'
import type { AnimationClip, AnimationMixer, Clock, Group, Material, Mesh, Object3D } from 'three'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet } from '../../lib/api'
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
  height?: number
}

export function FloorPlanPreview({ locationId, rooms, map3d, levelHeightM, onLevelHeight, height = 540 }: FloorPlanPreviewProps) {
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
    skclone: (obj: Object3D) => Object3D
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
  const map3dRef = useRef(map3d)
  map3dRef.current = map3d
  // Mixamo TEST FIGURE (any humanoid character model the server offers) +
  // animation clips per kind — markers show a real animated figure; without
  // figure/clip the mannequin stays the fallback.
  const figRef = useRef<{ status: 'idle' | 'loading' | 'ready' | 'missing'; obj?: Object3D }>({ status: 'idle' })
  const clipListRef = useRef<{ status: 'idle' | 'loading' | 'ready' | 'missing'
    clips: Array<{ kind: string; set: string; url: string }> }>({ status: 'idle', clips: [] })
  const clipCacheRef = useRef<Map<string, { clip: AnimationClip; restObj: Object3D } | 'loading' | 'missing'>>(new Map())
  const mixersRef = useRef<AnimationMixer[]>([])
  const clockRef = useRef<Clock | null>(null)

  const lh = levelHeightM && levelHeightM > 0 ? levelHeightM : DEFAULT_LEVEL_M

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

  // Test figure + clip loaders (async → bump; rebuild stays synchronous).
  const ensureTestFigure = (): Object3D | null => {
    const f = figRef.current
    if (f.status === 'ready') return f.obj || null
    if (f.status !== 'idle') return null
    figRef.current = { status: 'loading' }
    ;(async () => {
      try {
        const { GLTFLoader } = await import('three/examples/jsm/loaders/GLTFLoader.js')
        const gltf = await new GLTFLoader().loadAsync('/play/test-figure/model')
        figRef.current = { status: 'ready', obj: gltf.scene }
      } catch {
        figRef.current = { status: 'missing' }  // no humanoid model → mannequin
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
      if (Array.isArray(m)) m.forEach((x) => x.dispose?.())
      else m?.dispose?.()
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
                        yawDeg: number) => {
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
      fit.scale.setScalar(Math.min(targetW / (fpX || 1), targetD / (fpZ || 1)) * 0.96)

      const holder = new THREE.Group()
      holder.add(fit)
      holder.rotation.set(deg(entry.rotation.x),
                          deg(entry.rotation.y) - deg(yawDeg),
                          deg(entry.rotation.z))
      holder.updateMatrixWorld(true)
      const b2 = new THREE.Box3().setFromObject(holder)
      const c2 = b2.getCenter(new THREE.Vector3())
      holder.position.set(cx - c2.x,
                          floorY + 0.12 - b2.min.y + entry.offsetY,
                          cz - c2.z)
      holder.userData.__noDispose = true
      boxes.add(holder)
    }

    current.forEach((room, idx) => {
      const lay = room.layout
      if (!lay) return
      const color = PALETTE[idx % PALETTE.length]
      const w = lay.w * PLATE_M
      const d = lay.d * PLATE_M
      const level = lay.level || 0
      const floorY = level * lh
      const cy = floorY + lh / 2
      const cx = (lay.x + lay.w / 2 - 0.5) * PLATE_M
      const cz = (lay.y + lay.d / 2 - 0.5) * PLATE_M

      const model = showModelsRef.current && room.id
        ? ensureModel(`room:${room.id}`, room.id)
        : null
      if (model) {
        placeModel(model, w, d, cx, floorY, cz, lay.rotation || 0)
      }

      // Label + exit/marker dots always; the box only when no model stands in.
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
          new THREE.SphereGeometry(0.16, 12, 12),
          new THREE.MeshBasicMaterial({ color: 0xe0a356 }),
        )
        dot.position.set((lay.exit[0] - 0.5) * w, -lh * 0.4, (lay.exit[1] - 0.5) * d)
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
        const floor = -lh * 0.44 + (m.offset_y || 0)
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
          const mixer = new THREE.AnimationMixer(inst)
          mixer.clipAction(anim.clip).play()
          mixer.update(0)
          mixersRef.current.push(mixer)
          // Contract figure scale in rooms: derived from the storey height
          // (level_height / 3, real storey ≈ 3 m) — one value, always
          // consistent with the metre scale. Default 3 → 1/3.
          pivot.updateMatrixWorld(true)
          const fb = new THREE.Box3().setFromObject(pivot)
          const fs = fb.getSize(new THREE.Vector3())
          const figScale = (map3dRef.current?.level_height || 3) / 3
          const k = (1.7 * figScale) / (fs.y || 1)
          pivot.scale.setScalar(k)
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
          const figMat = new THREE.MeshStandardMaterial({
            color: 0x3fb950, transparent: true, opacity: 0.85,
          })
          const body = new THREE.Mesh(new THREE.CapsuleGeometry(0.09, 0.3, 4, 10), figMat)
          body.position.y = floor + 0.24
          fig.add(body)
          const head = new THREE.Mesh(new THREE.SphereGeometry(0.08, 12, 12), figMat)
          head.position.y = floor + 0.5
          fig.add(head)
          // Facing nose — only when a facing is set (0 = south/+Z, 90 = east/+X;
          // unset = the client decides, so the preview stays direction-less).
          if (m.rotation !== undefined) {
            const nose = new THREE.Mesh(new THREE.ConeGeometry(0.05, 0.14, 10), figMat)
            nose.rotation.x = Math.PI / 2
            nose.position.set(0, floor + 0.42, 0.14)
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
      sprite.position.y = lh * 0.62
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
          base.map(([x, z]) => new THREE.Vector3(x, lv * lh + 0.02, z)))
        boxes.add(new THREE.Line(geo, new THREE.LineBasicMaterial({
          color: 0x58a6ff, transparent: true, opacity: lv === 0 ? 0.9 : 0.45,
        })))
      }
    }
    if (m3?.elevator) {
      const lo = Math.min(0, ...usedLevels)
      const hi = Math.max(0, ...usedLevels)
      const hgt = (hi - lo + 1) * lh
      const shaft = new THREE.Mesh(
        new THREE.BoxGeometry(0.5, hgt, 0.5),
        new THREE.MeshStandardMaterial({ color: 0x8b949e, transparent: true, opacity: 0.35 }),
      )
      shaft.position.set((m3.elevator[0] - 0.5) * PLATE_M, lo * lh + hgt / 2,
                         (m3.elevator[1] - 0.5) * PLATE_M)
      boxes.add(shaft)
      const edges = new THREE.LineSegments(
        new THREE.EdgesGeometry(shaft.geometry),
        new THREE.LineBasicMaterial({ color: 0x8b949e }),
      )
      edges.position.copy(shaft.position)
      boxes.add(edges)
    }

    // Building shell over everything — ghosted so the rooms stay visible.
    // Placement per the drop 2026-07-17 "Gebäude-Modell-Normalisierung":
    // largest XZ side = 10 m × 0.92 × map3d.size (tile = 10 m, size default
    // 0.92), XZ centred, bottom at 0.06 m — then meta rotation, the map yaw
    // (map3d.rotation) and offset_y. The metre ruler next to it therefore
    // shows exactly the client's proportions.
    let buildingTopY = 0
    if (showBuildingRef.current) {
      const building = ensureModel('building')
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
        const norm = new THREE.Group()
        norm.add(clone)
        norm.updateMatrixWorld(true)
        const b0 = new THREE.Box3().setFromObject(norm)
        const s0 = b0.getSize(new THREE.Vector3())
        const target = 10 * 0.92 * (m3?.size || 0.92)
        norm.scale.setScalar(target / (Math.max(s0.x, s0.z) || 1))
        const holder = new THREE.Group()
        holder.add(norm)
        holder.rotation.set(deg(building.rotation.x),
                            deg(building.rotation.y) - deg(m3?.rotation || 0),
                            deg(building.rotation.z))
        holder.updateMatrixWorld(true)
        const b2 = new THREE.Box3().setFromObject(holder)
        const c2 = b2.getCenter(new THREE.Vector3())
        holder.position.set(-c2.x, 0.06 - b2.min.y + building.offsetY, -c2.z)
        holder.userData.__noDispose = true
        boxes.add(holder)
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
      const bottomY = Math.min(0, Math.floor(lo * lh))
      const topY = Math.ceil(Math.max((hi + 1) * lh, buildingTopY, lh))
      const rx = -PLATE_M / 2 - 0.7
      const rz = PLATE_M / 2 + 0.7
      const rulerMat = new THREE.LineBasicMaterial({ color: 0xc9d1d9 })
      boxes.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints([
        new THREE.Vector3(rx, bottomY, rz), new THREE.Vector3(rx, topY, rz),
      ]), rulerMat))
      const labelEvery = topY - bottomY > 14 ? 5 : 1
      for (let y = bottomY; y <= topY; y++) {
        const len = y % 5 === 0 ? 0.3 : 0.16
        boxes.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints([
          new THREE.Vector3(rx - len, y, rz), new THREE.Vector3(rx + len, y, rz),
        ]), rulerMat))
        if (y !== 0 && y % labelEvery === 0) {
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
            cctx.fillText(`${y}`, 32, 16)
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
        const y = lv * lh
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
        const target = 1.7 * (lh / 3)
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
          const mixer = new THREE.AnimationMixer(inst)
          mixer.clipAction(anim.clip).play()
          mixer.update(0)
          mixersRef.current.push(mixer)
          pivot.updateMatrixWorld(true)
          const fb = new THREE.Box3().setFromObject(pivot)
          const fs = fb.getSize(new THREE.Vector3())
          const k = target / (fs.y || 1)
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

  // Live-apply layout edits (drag/resize/rotate in the editor) and toggle/
  // load-completion changes — content rebuild only, the scene/renderer stay.
  useEffect(() => {
    if (handleRef.current) rebuild(handleRef.current, rooms)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rooms, map3d, showModels, showBuilding, bump, lh])

  return (
    <div className="ga-form" style={{ gap: 6 }}>
      <div style={{ display: 'flex', gap: 14, alignItems: 'center', flexWrap: 'wrap' }}>
        <div className="ga-form-section-label" style={{ margin: 0, flex: 1 }}>{t('3D preview')}</div>
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
        {onLevelHeight ? (
          <label className="ga-check-row"
            title={t('Storey height in WORLD metres — stacks the floor-plan levels and sets the figure scale in rooms (level_height / 3). Realistic interiors are ≈ 1–1.5; the default 3 reads as a triple-height storey.')}>
            <span>{t('Level height (m)')}</span>
            <input
              className="ga-input"
              type="number"
              min={0.5}
              max={50}
              step={0.1}
              style={{ width: 70 }}
              value={levelHeightM ?? ''}
              placeholder="3"
              onChange={(e) => {
                const n = parseFloat(e.target.value)
                onLevelHeight(Number.isFinite(n) && n > 0 ? n : undefined)
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
