/**
 * PlacePreview — the edited clip on a real PROP's places, through the shared per-figure runtime (Ruling A110
 * phase 2, spec docs/superpowers/specs/2026-11-16-poses-tab-redesign-design.md § 2.2).
 *
 * * The prop and its places A…X come from the SERVER: `POST /play/scene-preview` with a one-room draft holding
 *   only that prop at the origin answers the same `models[]` spec and `markers[].slots` / `facing` / `y_world` /
 *   `root_offset` the game sends (phase 0, `scripts/smoke_prop_places_preview.py`). The prop mesh is placed by
 *   the contract's `placeModelSpec`, nothing geometric is derived here.
 * * Per place a character (D1: built figures + the 1.70 m mannequin; others greyed with the step that builds one)
 *   playing this clip — a solo clip in place on its slot, a pair/group's roles in ONE clip frame on the place
 *   centre turned by `pairYaw(facing, yaw_offset)`, the game's seating. At most 6 figures (D5).
 * * The Library's alignment DRAFT is read through `draftRef` in the frame loop (a slider drag reloads nothing) and
 *   applied over the saved calibration by `clipCalibration` / `calibratedRoot` (scene-render): the hips land
 *   where the baked clip will put them, so Apply does not move a figure.
 * * Frame: mixers (phase A) → root placement → `runtime.poseStep` → `runFigureFrame` (phase B). Strand hair for
 *   the 2 figures nearest the camera (D5, `strandCandidates`), the rest on spring chains; frame time shown.
 * * Readout per figure: Δyaw of the body forward (hips, projected) against the place facing and Δpos of the hips
 *   against the slot point, now and as the LOOP MEDIAN, with the D4 lamp. The pose's `yaw_offset` is shown
 *   read-only with a link to its entry (D2).
 *
 * * Toggles "Collision" and "Channels" (phase 3, off by default, remembered per browser user in localStorage) only
 *   change what is DRAWN and printed — the sim always runs them, as in the game: each figure's capsules as other
 *   figures engage them (pairs of two figures that overlap drawn red, the deepest pair in mm), and each channel with
 *   its opening (a ring at the mouth while a partner chain occupies it; who engages whom, w, opening radius in mm).
 *   The numbers come from `FigureRuntime.inspect` / `inspectFrame` (`placeFigures.ts`); client3d computes them on
 *   the same runtime (`scripts/smoke_place_preview_partners.mjs`).
 *
 * three.js is imported dynamically — the admin bundle must not carry it for tabs that never show 3D.
 */
import { useEffect, useMemo, useRef, useState, type MutableRefObject } from 'react'
import type { Object3D, AnimationClip } from 'three'
import {
  CAPSULE_REGION_COLORS, FIGURE_HEIGHT_M, OPENING_MARGIN_M, STRAND_RECORD_VERSION, alignmentDelta, alignmentLamp,
  bindRelativeClip, calibratedRoot, capsuleWireframe, channelWireframe, clipCalibration,
  installSkinnedNormalCorrection, median, pairYaw, pickModelVariant, placeCapsuleWireframe, placeChannelWireframe,
  placeModelSpec, restCorrections, restPoseOf, strandCandidates,
  type AlignmentDraft, type ChannelNow, type FrameInspection, type AlignmentLamp, type ClipHeightOffsetsCm, type CollisionPayload, type FigureRuntime,
  type HairStrandRecord, type SceneMarker, type SceneModelSpec, type SecondaryMotionPayload,
} from '@anima/scene-render'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPost } from '../../lib/api'
import { loadCharacters } from '../../lib/refs'
import { loadTestFigure, standHipsRef } from '../characters/Model3DViewer'
import { rootAt, rootPath, ROLE_COLOR, type RootPath } from './ClipPreview'
import { ModelTurnHint } from '../../components/ModelTurnHint'
import { attachModelTurn, configureViewControls, poseMatrix } from '../../lib/modelTurn'
import { mountPlaceFigure, placeInteraction, placePhaseB } from './placeFigures'

export const MANNEQUIN = '__mannequin__'
/** D5: figures in the preview, and how many of them run strand hair. */
export const MAX_FIGURES = 6
const STRAND_FIGURES = 2
const LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'

interface ModelAnswer {
  model?: {
    url?: string; collision?: CollisionPayload | null
    hair_strands?: { url?: string; sha256?: string } | null
  }
  motion?: SecondaryMotionPayload
}
interface PropRow {
  id: string; name?: string; marker_count?: number; has_model?: boolean
  variant_tiers?: Array<{ variant: number }>
}
/** One clip file of the edited kind, as the listing carries it. */
export interface PlaceClip {
  role?: string; set?: string; url: string
  height_offsets_cm?: ClipHeightOffsetsCm
  orientation?: { shift_cm?: [number, number] | null } | null
}
/** A pose that plays this clip (read-only here, D2). */
export interface PlacePose { key: string; yaw_offset?: number; group?: string }

/** One place letter: a slot of a marker of the prop. */
interface PlaceRow {
  letter: string; marker: SceneMarker; slot: number
  point: [number, number]; facing: number; rootY: number
}
interface Assignment { character: string; role: string }

/** One figure's readout: now and the loop median. */
export interface FigureReadout {
  letter: string; character: string; role: string
  dyaw: number; dpos: number; medYaw: number; medPos: number; lamp: AlignmentLamp | null
}
/** What the Library needs to store a check (D3): the figures' readouts and whether they are all green. */
export interface PlaceReadout { prop: string; places: string; figures: FigureReadout[]; allGreen: boolean
  worstYaw: number; worstPos: number }

/** The partner overlays (phase 3): what is drawn, never what runs. */
export interface PartnerShow { collision: boolean; channels: boolean }
const SHOW_KEY = 'anima.placePreview.show'
function loadShow(): PartnerShow {
  try {
    const v = JSON.parse(localStorage.getItem(SHOW_KEY) || '{}') as Partial<PartnerShow>
    return { collision: !!v.collision, channels: !!v.channels }
  } catch { return { collision: false, channels: false } }
}
/** Capsules of two figures that overlap; a channel occupied by a partner chain. */
const CONTACT_COLOR = 0xff2d2d
const OPENING_COLOR = 0x3fb950

/** The printed partner readout (names = place letters). */
interface PartnerInfo {
  closest: { a: string; b: string; capA: string; capB: string; mm: number } | null
  contacts: number
  channels: number
  engaged: { by: string; of: string; channel: string; w: number; openingMm: number | null }[]
}

const LAMP_COLOR: Record<AlignmentLamp, string> = { green: '#3fb950', yellow: '#d29922', red: '#f85149' }

/** Characters and whether each has a built model (D1); probed once per mount. */
function useBuiltCharacters() {
  const [rows, setRows] = useState<{ name: string; built: boolean }[] | null>(null)
  useEffect(() => {
    let off = false
    void (async () => {
      const chars = await loadCharacters().catch(() => [])
      const out = await Promise.all(chars.map(async (c) => {
        const res = await fetch(`/characters/${encodeURIComponent(c.name)}/model3d`).catch(() => null)
        const data = res?.ok ? await res.json().catch(() => null) as ModelAnswer | null : null
        return { name: c.name, built: !!data?.model?.url }
      }))
      if (!off) setRows(out)
    })()
    return () => { off = true }
  }, [])
  return rows
}

const memoKey = (kind: string) => `anima.placePreview.${kind}`

export function PlacePreview({ kind, set = '', roles, clips, draftRef, draftSeq, bust = 0, poses, onOpenPose,
  onReadout, height = 360 }: {
  kind: string; set?: string
  /** 0/1 = solo, 2 = pair, 3+ = group */
  roles: number
  /** every file of this kind (all sets); the preview picks the previewed set's */
  clips: PlaceClip[]
  draftRef: MutableRefObject<AlignmentDraft>
  /** a new value whenever the draft changes (the draft object itself) — restarts the loop median */
  draftSeq: unknown
  bust?: number
  poses: PlacePose[]
  onOpenPose?: (key: string) => void
  onReadout?: (r: PlaceReadout | null) => void
  height?: number
}) {
  const { t } = useI18n()
  const chars = useBuiltCharacters()
  const [props, setProps] = useState<PropRow[] | null>(null)
  const [propId, setPropId] = useState('')
  const [variant, setVariant] = useState(0)
  const [scene, setScene] = useState<{ models: SceneModelSpec[]; markers: SceneMarker[] } | null>(null)
  const [assign, setAssign] = useState<Record<string, Assignment>>({})
  const [status, setStatus] = useState('')
  const [paused, setPaused] = useState(false)
  const [speed, setSpeed] = useState(1)
  const [info, setInfo] = useState<{ ms: number; swingMm: number; strands: number; chains: number; figures: FigureReadout[]
    partners: PartnerInfo | null } | null>(null)
  const [show, setShow] = useState<PartnerShow>(loadShow)
  const showRef = useRef(show); showRef.current = show
  const toggleShow = (k: keyof PartnerShow) => setShow((cur) => {
    const next = { ...cur, [k]: !cur[k] }
    try { localStorage.setItem(SHOW_KEY, JSON.stringify(next)) } catch { /* private mode: not remembered */ }
    return next
  })
  const hostRef = useRef<HTMLDivElement>(null)
  const pausedRef = useRef(paused); pausedRef.current = paused
  const speedRef = useRef(speed); speedRef.current = speed
  // The clip time outlives a rebuild (Apply reloads the clip): a paused figure is compared at the SAME instant.
  const timeRef = useRef(0)
  const draftSeqRef = useRef(draftSeq); draftSeqRef.current = draftSeq
  const onReadoutRef = useRef(onReadout); onReadoutRef.current = onReadout
  // The SAVED calibration per role, read live in the frame loop: after Apply the listing (new shift_cm / heights)
  // arrives after the clip reload, and the figures must take it the moment it does — never a stale copy.
  const savedRef = useRef<Record<string, { shiftCm: [number, number] | null; heightOffsetsCm: ClipHeightOffsetsCm | null }>>({})
  {
    const want = set.trim()
    const out: typeof savedRef.current = {}
    for (const role of ['', 'a', 'b', 'c', 'd', 'e']) {
      const c = (want ? clips.find((x) => (x.role || '') === role && (x.set || '') === want) : undefined)
        || clips.find((x) => (x.role || '') === role && !x.set) || clips.find((x) => (x.role || '') === role)
      if (c) out[role] = { shiftCm: c.orientation?.shift_cm ?? null, heightOffsetsCm: c.height_offsets_cm ?? null }
    }
    savedRef.current = out
  }
  const solo = roles < 2
  const roleList = useMemo(() => (solo ? [''] : ['a', 'b', 'c', 'd', 'e'].slice(0, roles)), [roles, solo])
  const pose = poses[0]
  const yawOffset = pose?.yaw_offset ?? 0

  // ── the props with places ──
  useEffect(() => {
    let off = false
    apiGet<PropRow[]>('/assets/props').then((list) => {
      if (off) return
      const usable = (Array.isArray(list) ? list : []).filter((p) => (p.marker_count ?? 0) > 0 && p.has_model !== false)
      setProps(usable)
      let memo: { prop?: string; variant?: number } = {}
      try { memo = JSON.parse(localStorage.getItem(memoKey(kind)) || '{}') } catch { memo = {} }
      const first = usable.find((p) => p.id === memo.prop) || usable[0]
      setPropId(first?.id || '')
      setVariant(first && first.id === memo.prop ? memo.variant ?? 0 : 0)
    }).catch(() => { if (!off) setProps([]) })
    return () => { off = true }
  }, [kind])

  // ── its places from the server (the draft scene preview) ──
  useEffect(() => {
    if (!propId) { setScene(null); return }
    try { localStorage.setItem(memoKey(kind), JSON.stringify({ prop: propId, variant })) } catch { /* private mode */ }
    let off = false
    const room = { id: 'place-preview', name: 'Preview',
      layout: { x: -3, y: -3, w: 6, d: 6, props: [{ id: 'p', prop_id: propId, at: [3, 3], yaw: 0, variant }] } }
    apiPost<{ models?: SceneModelSpec[]; markers?: SceneMarker[] }>('/play/scene-preview', { rooms: [room] })
      .then((payload) => {
        if (off) return
        setScene({ models: (payload.models || []).filter((m) => m.role === 'prop'), markers: payload.markers || [] })
      })
      .catch((e) => { if (!off) { setScene(null); setStatus(String((e as Error).message || e)) } })
    return () => { off = true }
  }, [propId, variant, kind])

  const places = useMemo<PlaceRow[]>(() => {
    const out: PlaceRow[] = []
    for (const m of scene?.markers || []) {
      m.slots.forEach((s, i) => {
        if (out.length >= LETTERS.length) return
        out.push({ letter: LETTERS[out.length], marker: m, slot: i, point: s, facing: m.facing ?? 0,
          rootY: m.y_world - (m.root_offset ?? 0) })
      })
    }
    return out
  }, [scene])

  // Default fill: the first built character (else the mannequin) on the first place(s) the clip fits.
  const fill = (all: boolean) => {
    // Built characters first, the mannequin between them (D1); a pose's place type limits the places.
    const names = [...(chars ?? []).filter((c) => c.built).map((c) => c.name), MANNEQUIN]
    const who = (i: number) => names[i % names.length]
    const wantGroup = (pose?.group || '').trim()
    const next: Record<string, Assignment> = {}
    let n = 0
    const byMarker = new Map<string, PlaceRow[]>()
    const fits = wantGroup && places.some((p) => p.marker.group === wantGroup)
    for (const p of places) {
      if (fits && p.marker.group !== wantGroup) continue
      byMarker.set(p.marker.id, [...(byMarker.get(p.marker.id) || []), p])
    }
    for (const rows of byMarker.values()) {
      if (!all && n) break
      if (solo) {
        for (const p of rows) {
          if (n >= MAX_FIGURES || (!all && n)) break
          next[p.letter] = { character: who(n), role: '' }; n++
        }
      } else if (rows.length >= roleList.length && n + roleList.length <= MAX_FIGURES) {
        roleList.forEach((r, i) => { next[rows[i].letter] = { character: who(n), role: r }; n++ })
      }
    }
    setAssign(next)
  }
  const filled = useRef('')
  useEffect(() => {
    const key = `${kind}|${propId}|${variant}|${places.length}|${chars ? 1 : 0}`
    if (!places.length || !chars || filled.current === key) return
    filled.current = key
    fill(false)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [places, chars, kind, propId, variant])

  const assigned = places.filter((p) => assign[p.letter]?.character)
  const assignKey = JSON.stringify(assigned.map((p) => [p.letter, assign[p.letter]]))
  const propName = props?.find((p) => p.id === propId)?.name || propId

  // ── the scene ──
  useEffect(() => {
    const host = hostRef.current
    if (!host || !scene || !kind) return
    let disposed = false
    let raf = 0
    const disposers: Array<() => void> = []
    setStatus(t('Loading…'))
    setInfo(null)
    void (async () => {
      try {
        const THREE = await import('three')
        installSkinnedNormalCorrection(THREE)
        const { OrbitControls } = await import('three/examples/jsm/controls/OrbitControls.js')
        const { FBXLoader } = await import('three/examples/jsm/loaders/FBXLoader.js')
        const { clone: skclone } = await import('three/examples/jsm/utils/SkeletonUtils.js')
        const { createGLTFLoader } = await import('../../lib/gltfLoader')
        const gltfLoader = createGLTFLoader()
        const want = set.trim()
        const fileOf = (role: string) =>
          (want ? clips.find((c) => (c.role || '') === role && (c.set || '') === want) : undefined)
          || clips.find((c) => (c.role || '') === role && !c.set)
          || clips.find((c) => (c.role || '') === role)
        const [rig, standRefCm] = await Promise.all([
          new FBXLoader().loadAsync('/assets/animation-rig').catch(() => null), standHipsRef()])
        const standRefM = (standRefCm || 0) / 100
        // Clips per role, loaded once.
        const clipFiles = new Map<string, { file: PlaceClip; raw: AnimationClip; path: RootPath }>()
        for (const role of new Set(assigned.map((p) => assign[p.letter].role))) {
          const file = fileOf(role)
          if (!file) continue
          const obj = await new FBXLoader().loadAsync(bust ? `${file.url}${file.url.includes('?') ? '&' : '?'}v=${bust}` : file.url)
          const raw = obj.animations?.[0]
          if (raw) clipFiles.set(role, { file, raw, path: rootPath(raw, standRefM) })
        }
        // Models per character, loaded once; the mannequin is shared and never disposed here.
        const models = new Map<string, { template: Object3D; answer: ModelAnswer | null; record: HairStrandRecord | null; owned: boolean }>()
        for (const name of new Set(assigned.map((p) => assign[p.letter].character))) {
          if (name === MANNEQUIN) {
            const fig = await loadTestFigure()
            if (fig) models.set(name, { template: fig, answer: null, record: null, owned: false })
            continue
          }
          const answer = await apiGet<ModelAnswer>(`/characters/${encodeURIComponent(name)}/model3d`).catch(() => null)
          if (!answer?.model?.url) continue
          const gltf = await gltfLoader.loadAsync(answer.model.url)
          let record: HairStrandRecord | null = null
          if (answer.model.hair_strands?.url) {
            const res = await fetch(answer.model.hair_strands.url).catch(() => null)
            const json = res?.ok ? await res.json().catch(() => null) as HairStrandRecord | null : null
            record = json && json.version === STRAND_RECORD_VERSION ? json : null
          }
          models.set(name, { template: gltf.scene, answer, record, owned: true })
        }
        // The prop mesh, placed by the contract's routine.
        const propObjects: Object3D[] = []
        for (const spec of scene.models) {
          const url = pickModelVariant(spec, 'full')
          if (!url) continue
          const gltf = await gltfLoader.loadAsync(url).catch(() => null)
          if (gltf) propObjects.push(placeModelSpec(THREE, gltf.scene, spec, { clone: false }))
        }
        if (disposed) return
        const disposeTree = (root: Object3D, textures = true) => root.traverse((o) => {
          const mesh = o as unknown as { geometry?: { dispose(): void }; material?: unknown; skeleton?: { dispose(): void } }
          mesh.geometry?.dispose()
          const mats = Array.isArray(mesh.material) ? mesh.material : mesh.material ? [mesh.material] : []
          for (const mat of mats as Array<{ dispose(): void } & Record<string, unknown>>) {
            if (textures) for (const v of Object.values(mat)) {
              if (v && typeof v === 'object' && (v as { isTexture?: boolean }).isTexture) (v as { dispose(): void }).dispose()
            }
            mat.dispose()
          }
        })
        // This mount loaded the character templates and the prop: they are its own. Clones share their buffers.
        disposers.push(() => {
          for (const m of models.values()) if (m.owned) disposeTree(m.template)
          for (const p of propObjects) disposeTree(p)
        })

        // ── stage ──
        const width = host.clientWidth || 640
        const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true })
        renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2))
        renderer.setSize(width, height)
        host.appendChild(renderer.domElement)
        disposers.push(() => { renderer.dispose(); renderer.domElement.remove() })
        const sceneObj = new THREE.Scene()
        sceneObj.add(new THREE.HemisphereLight(0xffffff, 0x556677, 1.1))
        const key = new THREE.DirectionalLight(0xffffff, 1.2)
        key.position.set(2, 4, 3)
        sceneObj.add(key)
        const stage = new THREE.Group()
        stage.matrixAutoUpdate = false
        sceneObj.add(stage)
        const own: Array<{ dispose(): void }> = []
        disposers.push(() => own.forEach((d) => d.dispose()))
        for (const p of propObjects) stage.add(p)
        // 0.5 m grid, 4 m wide, and the 1.70 m reference post beside the prop (never scaled).
        const grid = new THREE.GridHelper(4, 8, 0x7a8594, 0x3a4350)
        own.push(grid.geometry, grid.material as { dispose(): void })
        stage.add(grid)
        const propBox = new THREE.Box3()
        for (const p of propObjects) propBox.expandByObject(p)
        const postX = propBox.isEmpty() ? -1 : propBox.min.x - 0.5
        const postGeom = new THREE.CylinderGeometry(0.012, 0.012, FIGURE_HEIGHT_M, 6)
        const postMat = new THREE.MeshBasicMaterial({ color: 0xffc857 })
        own.push(postGeom, postMat)
        const post = new THREE.Mesh(postGeom, postMat)
        post.position.set(postX, FIGURE_HEIGHT_M / 2, 0)
        stage.add(post)
        // Place markers: a box with its letter on the surface, the place facing as a dashed arrow.
        const markGeom = new THREE.BoxGeometry(0.1, 0.02, 0.1)
        own.push(markGeom)
        const letterSprite = (text: string, color: string) => {
          const canvas = document.createElement('canvas')
          canvas.width = 64; canvas.height = 64
          const ctx = canvas.getContext('2d')
          if (ctx) {
            ctx.fillStyle = color; ctx.font = 'bold 44px sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'
            ctx.fillText(text, 32, 34)
          }
          const tex = new THREE.CanvasTexture(canvas)
          const mat = new THREE.SpriteMaterial({ map: tex, depthTest: false })
          own.push(tex, mat)
          const s = new THREE.Sprite(mat)
          s.scale.set(0.18, 0.18, 1)
          return s
        }
        for (const p of places) {
          const used = !!assign[p.letter]?.character
          const mat = new THREE.MeshBasicMaterial({ color: used ? 0xffc857 : 0x8b949e })
          own.push(mat)
          const box = new THREE.Mesh(markGeom, mat)
          box.position.set(p.point[0], p.marker.y_world + 0.01, p.point[1])
          stage.add(box)
          const label = letterSprite(p.letter, used ? '#ffc857' : '#8b949e')
          label.position.set(p.point[0], p.marker.y_world + 0.12, p.point[1])
          stage.add(label)
          const rad = p.facing * Math.PI / 180
          const dir = new THREE.Vector3(Math.sin(rad), 0, Math.cos(rad))
          const from = new THREE.Vector3(p.point[0], p.marker.y_world + 0.03, p.point[1])
          const lineGeom = new THREE.BufferGeometry().setFromPoints([from, from.clone().addScaledVector(dir, 0.45)])
          const lineMat = new THREE.LineDashedMaterial({ color: 0xffc857, dashSize: 0.04, gapSize: 0.03 })
          own.push(lineGeom, lineMat)
          const line = new THREE.Line(lineGeom, lineMat)
          line.computeLineDistances()
          stage.add(line)
        }

        // ── figures ──
        const hipsOf = (root: Object3D): Object3D | null => {
          let found: Object3D | null = null
          root.traverse((o) => { if (!found && /hips/i.test(o.name)) found = o })
          return found
        }
        interface Fig {
          letter: string; character: string; role: string; place: PlaceRow; root: Object3D; inst: Object3D
          mixer: InstanceType<typeof THREE.AnimationMixer>; path: RootPath; duration: number
          hips: Object3D | null; hipsBind: { x: number; y: number; z: number }
          bindInv: InstanceType<typeof THREE.Quaternion>; runtime: FigureRuntime; hasRecord: boolean
          saved: { shiftCm: [number, number] | null; heightOffsetsCm: ClipHeightOffsetsCm | null }
          anchor: { x: number; y: number; z: number }; placeYaw: number
          arrow: InstanceType<typeof THREE.ArrowHelper>; yawS: number[]; posS: number[]
          medYaw: number; medPos: number; dyaw: number; dpos: number; chains: number
          head: Object3D | null; tips: Object3D[]; tipRest: Map<Object3D, InstanceType<typeof THREE.Vector3>>
        }
        const figs: Fig[] = []
        const centreOf = (m: SceneMarker) => {
          const n = m.slots.length || 1
          return { x: m.slots.reduce((a, s) => a + s[0], 0) / n, z: m.slots.reduce((a, s) => a + s[1], 0) / n }
        }
        for (const p of assigned) {
          const a = assign[p.letter]
          const model = models.get(a.character)
          const clip = clipFiles.get(a.role)
          if (!model || !clip) continue
          const answer = model.answer
          const { root, inst, runtime } = mountPlaceFigure(THREE, (o) => skclone(o) as Object3D, model.template,
            { collision: answer?.model?.collision ?? null, motion: () => answer?.motion })
          stage.add(root)
          root.updateMatrixWorld(true)
          const hips = hipsOf(inst)
          const hb = hips ? hips.getWorldPosition(new THREE.Vector3()) : new THREE.Vector3(0, FIGURE_HEIGHT_M * 0.55, 0)
          const bindInv = hips ? hips.getWorldQuaternion(new THREE.Quaternion()).invert() : new THREE.Quaternion()
          let hasRecord = false
          if (model.record) {
            const record = model.record
            runtime.loadStrandRecord = () => record
            hasRecord = runtime.prepareStrandHair()
          }
          const tracks = clip.raw.tracks.filter((tr) => !(/hips/i.test(tr.name) && tr.name.endsWith('.position')))
          const inplace = new THREE.AnimationClip(clip.raw.name, clip.raw.duration, tracks)
          const bound = rig ? bindRelativeClip(THREE, inplace, restCorrections(THREE, restPoseOf(THREE, rig), inst)) : inplace
          const mixer = new THREE.AnimationMixer(inst)
          mixer.clipAction(bound).play()
          const m = p.marker
          const centre = centreOf(m)
          const anchor = solo ? { x: p.point[0], y: p.rootY, z: p.point[1] } : { x: centre.x, y: p.rootY, z: centre.z }
          const placeYaw = solo ? p.facing * Math.PI / 180 : pairYaw(p.facing, yawOffset)
          const arrow = new THREE.ArrowHelper(new THREE.Vector3(0, 0, 1), new THREE.Vector3(), 0.5,
            new THREE.Color(ROLE_COLOR[a.role] || '#58a6ff').getHex(), 0.1, 0.06)
          stage.add(arrow)
          own.push(arrow)
          const label = letterSprite(p.letter, ROLE_COLOR[a.role] || '#58a6ff')
          label.position.y = FIGURE_HEIGHT_M + 0.15
          root.add(label)
          const o = clip.file.orientation
          let head: Object3D | null = null
          const tips: Object3D[] = []
          inst.traverse((n) => {
            if (/^mixamorig:?head$/i.test(n.name)) head = n
            if (/^HairGen_.*_end$/.test(n.name)) tips.push(n)
          })
          figs.push({ letter: p.letter, character: a.character, role: a.role, place: p, root, inst, mixer, path: clip.path,
            duration: clip.raw.duration, hips, hipsBind: { x: hb.x, y: hb.y, z: hb.z }, bindInv, runtime, hasRecord,
            saved: { shiftCm: o?.shift_cm ?? null, heightOffsetsCm: clip.file.height_offsets_cm ?? null },
            anchor, placeYaw, arrow, yawS: [], posS: [], medYaw: NaN, medPos: NaN, dyaw: 0, dpos: 0,
            chains: Object.keys(answer?.motion?.groups ?? {}).length, head, tips, tipRest: new Map() })
          disposers.push(() => { mixer.stopAllAction(); mixer.uncacheRoot(inst); runtime.dispose() })
        }
        if (!figs.length) {
          setStatus(!assigned.length || clipFiles.size ? t('Pick a character for a place.') : t('No clip file for this kind in shared/models/clips.'))
        } else setStatus('')

        const camera = new THREE.PerspectiveCamera(35, width / height, 0.05, 100)
        camera.position.set(0.4, 1.7, 3.6)
        const controls = new OrbitControls(camera, renderer.domElement)
        controls.target.set(0, 0.6, 0)
        configureViewControls(THREE, controls)
        controls.update()
        disposers.push(() => controls.dispose())
        const turn = attachModelTurn(host)
        disposers.push(() => turn.dispose())
        const PIVOT: [number, number, number] = [0, 0.6, 0]

        const duration = figs.length ? Math.min(...figs.map((f) => f.duration)) : 1
        const frameState = { openingTurn: 0 }
        const entries = figs.map((f) => ({
          name: `${f.letter}:${f.character}`,
          interaction: solo ? null : placeInteraction(kind, f.place.marker.id,
            figs.filter((g) => g.place.marker.id === f.place.marker.id).map((g) => `${g.letter}:${g.character}`)),
          figure: f.runtime,
        }))
        // ── partner overlays (phase 3): world space, on the scene root — the runtime reads the stage-turned figures ──
        const overlay = new THREE.Group()
        sceneObj.add(overlay)
        const capLines = new Map<string, ReturnType<typeof capsuleWireframe>>()
        const chLines = new Map<string, ReturnType<typeof channelWireframe>>()
        const rings = new Map<string, InstanceType<typeof THREE.LineLoop>>()
        const ringGeom = new THREE.BufferGeometry().setFromPoints(Array.from({ length: 33 },
          (_, k) => new THREE.Vector3(Math.cos(k * Math.PI / 16), 0, Math.sin(k * Math.PI / 16))))
        const ringMat = new THREE.LineBasicMaterial({ color: OPENING_COLOR, depthTest: false })
        own.push(ringGeom, ringMat)
        disposers.push(() => {
          for (const l of [...capLines.values(), ...chLines.values()]) {
            l.geometry.dispose(); (l.material as { dispose(): void }).dispose()
          }
          overlay.removeFromParent()
        })
        const nameToLetter = new Map(figs.map((f) => [`${f.letter}:${f.character}`, f.letter]))
        const letterOf = (name: string) => nameToLetter.get(name) ?? name
        let partnerInfo: PartnerInfo | null = null
        const drawPartners = (res: ReturnType<typeof placePhaseB>) => {
          const sh = showRef.current
          overlay.visible = !!res
          if (!res) { partnerInfo = null; return }
          const frame = res.frame
          const touching = new Set<string>()
          for (const c of frame.contacts) { touching.add(`${c.a}|${c.capA}`); touching.add(`${c.b}|${c.capB}`) }
          const usedCaps = new Set<string>(), usedCh = new Set<string>()
          let channels = 0
          for (const { name, inspection: ins } of res.figures) {
            if (!ins) continue
            if (sh.collision) for (const c of ins.capsules) {
              const key = `${name}|${c.id}`
              usedCaps.add(key)
              let line = capLines.get(key)
              if (!line) { line = capsuleWireframe(THREE, c.now, CAPSULE_REGION_COLORS[c.region]); capLines.set(key, line); overlay.add(line) }
              else placeCapsuleWireframe(THREE, line, c.now)
              ;(line.material as InstanceType<typeof THREE.LineBasicMaterial>).color.setHex(
                touching.has(key) ? CONTACT_COLOR : CAPSULE_REGION_COLORS[c.region] ?? 0xffd166)
            }
            channels += ins.channels.length
            if (sh.channels) for (const ch of ins.channels) {
              const key = `${name}|${ch.id}`
              usedCh.add(key)
              const now = ch as unknown as ChannelNow
              let line = chLines.get(key)
              if (!line) { line = channelWireframe(THREE, now, CAPSULE_REGION_COLORS.channel); chLines.set(key, line); overlay.add(line) }
              else placeChannelWireframe(THREE, line, now)
              const open = ins.openings.find((o) => o.channel === ch.id)
              let ring = rings.get(key)
              if (!ring) { ring = new THREE.LineLoop(ringGeom, ringMat); ring.renderOrder = 999; rings.set(key, ring); overlay.add(ring) }
              ring.visible = !!open
              if (open) {
                const rad = open.radius + OPENING_MARGIN_M
                ring.position.set(ch.o[0], ch.o[1], ch.o[2])
                ring.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), new THREE.Vector3(ch.u[0], ch.u[1], ch.u[2]))
                ring.scale.setScalar(rad)
              }
            }
          }
          for (const [k, l] of capLines) l.visible = usedCaps.has(k)
          for (const [k, l] of chLines) l.visible = usedCh.has(k)
          for (const [k, r] of rings) if (!usedCh.has(k)) r.visible = false
          const best = frame.closest.reduce<FrameInspection['closest'][number] | null>((w, c) => (!w || c.depth > w.depth ? c : w), null)
          partnerInfo = {
            closest: best ? { a: letterOf(best.a), b: letterOf(best.b), capA: best.capA, capB: best.capB, mm: best.depth * 1000 } : null,
            contacts: frame.contacts.length, channels,
            engaged: frame.engagements.map((g) => ({ by: letterOf(g.by), of: letterOf(g.of), channel: g.channel, w: g.w,
              openingMm: g.opening === null ? null : g.opening * 1000 })),
          }
        }

        const scratch = new THREE.Vector3()
        const q = new THREE.Quaternion()
        const fwd = new THREE.Vector3()
        const stageInv = new THREE.Matrix4()
        let last = performance.now()
        let lastInfo = 0
        let lastBudget = 0
        let ms = 0
        let swingMm = 0
        let lastSig: string | null = null
        let seenSeq = draftSeqRef.current
        let lastTime = timeRef.current
        const tick = () => {
          if (disposed) return
          raf = requestAnimationFrame(tick)
          const now = performance.now()
          const dt = Math.min(0.1, (now - last) / 1000)
          last = now
          turn.tick(dt)
          stage.matrix.fromArray(poseMatrix(turn.pose, PIVOT))
          stage.matrixWorldNeedsUpdate = true
          stage.updateMatrixWorld(true)
          stageInv.copy(stage.matrixWorld).invert()
          if (!pausedRef.current) timeRef.current = (timeRef.current + dt * speedRef.current) % duration
          const time = timeRef.current
          const wrapped = time < lastTime
          lastTime = time
          if (seenSeq !== draftSeqRef.current) {
            seenSeq = draftSeqRef.current
            for (const f of figs) { f.yawS = []; f.posS = []; f.medYaw = NaN; f.medPos = NaN }
          }
          const t0 = performance.now()
          const draft = draftRef.current
          for (const f of figs) {
            // phase A: the pose, then the root by the calibration (draft over saved, the bake's order)
            f.mixer.setTime(time)
            const cal = clipCalibration(draft, savedRef.current[f.role] ?? f.saved, f.placeYaw, f.place.marker.group)
            const r = rootAt(f.path, time)
            const at = calibratedRoot(cal, { anchor: f.anchor, role: f.role, hips: r, inPlace: solo, hipsBind: f.hipsBind, standRefM })
            f.root.position.set(at.x, at.y, at.z)
            f.root.rotation.set(cal.euler[0], cal.euler[1], cal.euler[2], 'YXZ')
            f.root.updateMatrixWorld(true)
            f.runtime.poseStep({ realDelta: dt })
          }
          const wantInspect = showRef.current.collision || showRef.current.channels
          const inspection = placePhaseB(entries, frameState, wantInspect)   // phase B (+ the partner readout)
          ms = ms * 0.9 + (performance.now() - t0) * 0.1
          drawPartners(inspection)
          // readout: hips in stage space against the place
          for (const f of figs) {
            if (!f.hips) continue
            f.hips.getWorldPosition(scratch).applyMatrix4(stageInv)
            f.hips.getWorldQuaternion(q)
            q.premultiply(new THREE.Quaternion().setFromRotationMatrix(stageInv)).multiply(f.bindInv)
            fwd.set(0, 0, 1).applyQuaternion(q)
            const d = alignmentDelta({ x: fwd.x, z: fwd.z }, f.place.facing, { x: scratch.x, z: scratch.z },
              { x: f.place.point[0], z: f.place.point[1] })
            f.dyaw = d.dyaw; f.dpos = d.dpos
            if (wrapped && f.yawS.length) { f.medYaw = median(f.yawS); f.medPos = median(f.posS); f.yawS = []; f.posS = [] }
            if (!pausedRef.current) { f.yawS.push(d.dyaw); f.posS.push(d.dpos) }
            f.arrow.position.set(scratch.x, f.place.marker.y_world + 0.05, scratch.z)
            const len = Math.hypot(fwd.x, fwd.z) || 1
            f.arrow.setDirection(scratch.set(fwd.x / len, 0, fwd.z / len))
            // the evidence that the hair moves: every hair chain tip's travel in the HEAD's frame (mm, max)
            const h = f.head as Object3D | null
            if (h) for (const tip of f.tips) {
              h.worldToLocal(tip.getWorldPosition(scratch))
              const rest = f.tipRest.get(tip)
              if (!rest) f.tipRest.set(tip, scratch.clone())
              else swingMm = Math.max(swingMm, rest.distanceTo(scratch) * 1000 * h.getWorldScale(fwd).x)
            }
          }
          if (now - lastBudget > 500 && figs.length) {
            lastBudget = now
            // D5: strand hair for the 2 nearest the camera, the rest on chains.
            const views = figs.map((f) => ({ name: f.letter, position: f.root.getWorldPosition(new THREE.Vector3()),
              tier: 'full' as const, hasRecord: f.hasRecord, firstPerson: false, costMs: f.runtime.strandCostMs,
              running: f.runtime.strandRunning }))
            const on = new Set(strandCandidates(views, camera.position).sort((a, b) => a.distance - b.distance)
              .slice(0, STRAND_FIGURES).map((c) => c.name))
            for (const f of figs) if (f.hasRecord) f.runtime.setStrandHair(on.has(f.letter))
          }
          if (now - lastInfo > 250) {
            lastInfo = now
            const rows: FigureReadout[] = figs.map((f) => {
              const medYaw = Number.isFinite(f.medYaw) ? f.medYaw : (f.yawS.length ? median(f.yawS) : f.dyaw)
              const medPos = Number.isFinite(f.medPos) ? f.medPos : (f.posS.length ? median(f.posS) : f.dpos)
              return { letter: f.letter, character: f.character, role: f.role, dyaw: f.dyaw, dpos: f.dpos, medYaw, medPos,
                lamp: Number.isFinite(f.medYaw) ? alignmentLamp(medYaw, medPos) : null }
            })
            setInfo({ ms, swingMm, strands: figs.filter((f) => f.runtime.strandRunning).length,
              chains: figs.filter((f) => !f.runtime.strandRunning && f.chains > 0).length, figures: rows,
              partners: partnerInfo })
            host.dataset.partners = partnerInfo ? JSON.stringify(partnerInfo) : ''
            host.dataset.figures = JSON.stringify(figs.map((f) => {
              f.hips?.getWorldPosition(scratch).applyMatrix4(stageInv)
              return { letter: f.letter, time: +time.toFixed(4), hips: [scratch.x, scratch.y, scratch.z].map((v) => +v.toFixed(5)),
                dyaw: +f.dyaw.toFixed(3), dpos: +f.dpos.toFixed(3) }
            }))
            host.dataset.frameMs = ms.toFixed(2)
            const done = rows.filter((r) => r.lamp)
            const ready = done.length > 0 && done.length === rows.length
            // Only a CHANGED readout reaches the Library (it re-renders the whole edit view).
            const sig = ready ? rows.map((r) => `${r.letter}${r.medYaw.toFixed(1)}/${r.medPos.toFixed(1)}`).join() : ''
            if (sig === lastSig) { controls.update(); renderer.render(sceneObj, camera); return }
            lastSig = sig
            onReadoutRef.current?.(ready ? {
              prop: propName, places: rows.map((r) => r.letter).join('+'), figures: rows,
              allGreen: rows.every((r) => r.lamp === 'green'),
              worstYaw: rows.reduce((w, r) => Math.abs(r.medYaw) > Math.abs(w) ? r.medYaw : w, 0),
              worstPos: Math.max(...rows.map((r) => r.medPos)),
            } : null)
          }
          controls.update()
          renderer.render(sceneObj, camera)
        }
        tick()
      } catch (e) {
        setStatus(String(e))
      }
    })()
    return () => {
      disposed = true
      cancelAnimationFrame(raf)
      onReadoutRef.current?.(null)
      disposers.forEach((d) => d())
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scene, assignKey, kind, set, bust, height, yawOffset, t])

  const nAssigned = assigned.length
  const variants = props?.find((p) => p.id === propId)?.variant_tiers || []
  const readout = new Map((info?.figures || []).map((f) => [f.letter, f]))
  const fmt = (v: number, d = 1) => `${v >= 0 ? '+' : ''}${v.toFixed(d)}`

  return (
    <div style={{ border: '1px solid var(--border, #30363d)', borderRadius: 4, padding: 6 }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 12, marginBottom: 4, flexWrap: 'wrap' }}>
        <strong>{t('Places')}</strong>
        <label title={t('Props with places; the scene comes from the server like in the game.')}>
          {t('Prop')}{' '}
          <select value={propId} onChange={(e) => { setPropId(e.target.value); setVariant(0) }} style={{ maxWidth: 200 }}>
            {(props ?? []).length ? null : <option value="">{t('— no prop with places —')}</option>}
            {(props ?? []).map((p) => <option key={p.id} value={p.id}>{p.name || p.id}</option>)}
          </select>
        </label>
        {variants.length > 1 ? (
          <label>
            {t('Variant')}{' '}
            <select value={variant} onChange={(e) => setVariant(Number(e.target.value))}>
              {variants.map((_v, i) => <option key={i} value={i}>{`v${i + 1}`}</option>)}
            </select>
          </label>
        ) : null}
        <button type="button" className="ga-btn ga-btn-sm" onClick={() => setPaused((p) => !p)}>
          {paused ? t('▶ Play') : t('⏸ Pause')}
        </button>
        {[0.5, 1].map((s) => (
          <button key={s} type="button" className={`ga-btn ga-btn-sm${speed === s ? ' ga-btn-primary' : ''}`}
            onClick={() => setSpeed(s)}>{`${s}×`}</button>
        ))}
        <button type="button" className="ga-btn ga-btn-sm" disabled={!places.length} onClick={() => fill(true)}
          title={t('Every place this clip fits gets a figure (at most 6).')}>{t('Fill all with this clip')}</button>
        <label title={t('Draw each figure’s collision capsules as other figures engage them; overlapping pairs of two figures turn red.')}>
          <input type="checkbox" checked={show.collision} onChange={() => toggleShow('collision')} /> {t('Collision')}
        </label>
        <label title={t('Draw each figure’s channels; a ring at the mouth while a partner’s chain opens it.')}>
          <input type="checkbox" checked={show.channels} onChange={() => toggleShow('channels')} /> {t('Channels')}
        </label>
        {info ? (
          <span style={{ marginLeft: 'auto', opacity: 0.8 }}
            title={t('Phase B of the two-phase frame: secondary motion and strand hair. Strand hair runs for the 2 figures nearest the camera.')}>
            {t('{n} strand hair').replace('{n}', String(info.strands))} · {t('{n} on chains').replace('{n}', String(info.chains))}
            {' · '}{t('hair swing {mm} mm').replace('{mm}', info.swingMm.toFixed(0))}
            {' · '}{info.ms.toFixed(1)} ms
          </span>
        ) : null}
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) 300px', gap: 8 }}>
        <div>
          <div ref={hostRef} data-testid="place-preview" style={{ position: 'relative', height, background: 'var(--surface-2, #161b22)' }}>
            {status ? <div style={{ position: 'absolute', inset: 8, fontSize: 12, opacity: 0.8 }}>{status}</div> : null}
          </div>
          <ModelTurnHint />
          <div className="ga-hint">{t('Figures 1.70 m, yellow post 1.70 m, grid 0.5 m · dashed = place facing, arrow = body facing.')}</div>
        </div>
        <div style={{ fontSize: 12 }}>
          {pose ? (
            <div className="ga-hint" style={{ marginBottom: 4 }}
              title={t('The pose’s yaw offset turns a pair or group on its place in the game. It is edited in Entries.')}>
              {t('Pose {key}: yaw offset {deg}°').replace('{key}', pose.key).replace('{deg}', String(yawOffset))}{' '}
              {onOpenPose ? (
                <button type="button" className="ga-btn ga-btn-sm" onClick={() => onOpenPose(pose.key)}>{t('Open entry →')}</button>
              ) : null}
            </div>
          ) : null}
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ textAlign: 'left', opacity: 0.7 }}>
                <th />
                <th>{t('Character')}</th>
                <th title={t('Body facing against the place facing, degrees (loop median).')}>{t('Δ turn')}</th>
                <th title={t('Hips against the place point, cm (loop median).')}>{t('Δ pos')}</th>
              </tr>
            </thead>
            <tbody>
              {places.map((p) => {
                const a = assign[p.letter]
                const r = readout.get(p.letter)
                const full = !a?.character && nAssigned >= MAX_FIGURES
                return (
                  <tr key={p.letter}>
                    <td title={`${p.marker.group}${p.marker.label ? ` · ${p.marker.label}` : ''} · ${t('facing')} ${p.facing}°`}>
                      <strong>{p.letter}</strong> <span style={{ opacity: 0.7 }}>{p.marker.group}</span>
                    </td>
                    <td>
                      <select value={a?.character || ''} disabled={full} style={{ maxWidth: 130 }}
                        title={full ? t('At most 6 figures.') : t('Only characters with a built model can be picked.')}
                        onChange={(e) => {
                          const v = e.target.value
                          setAssign((cur) => {
                            const next = { ...cur }
                            if (!v) delete next[p.letter]
                            else next[p.letter] = { character: v, role: cur[p.letter]?.role ?? (solo ? '' : roleList[p.slot % roleList.length]) }
                            return next
                          })
                        }}>
                        <option value="">{t('— empty')}</option>
                        <option value={MANNEQUIN}>{t('1.70 m mannequin')}</option>
                        {(chars ?? []).map((c) => (
                          <option key={c.name} value={c.name} disabled={!c.built}>
                            {c.built ? c.name : `${c.name} — ${t('no model yet (Characters → Figure)')}`}
                          </option>
                        ))}
                      </select>
                      {!solo && a?.character ? (
                        <select value={a.role} style={{ marginLeft: 2 }} title={t('Which half of the clip this figure plays.')}
                          onChange={(e) => setAssign((cur) => ({ ...cur, [p.letter]: { ...cur[p.letter], role: e.target.value } }))}>
                          {roleList.map((r) => <option key={r} value={r}>{`(${r})`}</option>)}
                        </select>
                      ) : null}
                    </td>
                    <td style={{ whiteSpace: 'nowrap' }} title={r ? `${t('now')} ${fmt(r.dyaw)}°` : ''}>
                      {r ? `${fmt(r.medYaw)}°` : ''}
                    </td>
                    <td style={{ whiteSpace: 'nowrap' }} title={r ? `${t('now')} ${r.dpos.toFixed(1)} cm` : ''}>
                      {r ? (
                        <>
                          {`${r.medPos.toFixed(1)} cm `}
                          <span style={{ display: 'inline-block', width: 9, height: 9, borderRadius: 5,
                            background: r.lamp ? LAMP_COLOR[r.lamp] : '#8b949e' }}
                            title={r.lamp ? t('Loop median: green ≤ 3° and 2 cm, yellow ≤ 10° and 6 cm, else red.')
                              : t('Measuring — the lamp shows after one full loop.')} />
                        </>
                      ) : null}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          {!places.length && propId ? <div className="ga-hint">{t('This prop has no places.')}</div> : null}
          {(show.collision || show.channels) && info?.partners ? (
            <div style={{ marginTop: 6, borderTop: '1px solid var(--border, #30363d)', paddingTop: 4 }} data-testid="place-partners">
              {show.collision ? (
                <div title={t('Closest capsule pair of two figures: positive = they overlap by that much, negative = the gap.')}>
                  {info.partners.closest ? (
                    <>
                      <span style={{ display: 'inline-block', width: 9, height: 9, borderRadius: 5, marginRight: 4,
                        background: info.partners.closest.mm > 0 ? '#f85149' : '#3fb950' }} />
                      {t('Closest pair {a} {capA} ↔ {b} {capB}: {mm} mm')
                        .replace('{a}', info.partners.closest.a).replace('{capA}', info.partners.closest.capA)
                        .replace('{b}', info.partners.closest.b).replace('{capB}', info.partners.closest.capB)
                        .replace('{mm}', `${info.partners.closest.mm > 0 ? '+' : ''}${info.partners.closest.mm.toFixed(1)}`)}
                      {' · '}{t('{n} overlapping').replace('{n}', String(info.partners.contacts))}
                    </>
                  ) : t('Fewer than two figures with collision capsules.')}
                </div>
              ) : null}
              {show.channels ? (
                <div title={t('A chain of one figure engaged in another figure’s channel: its weight w and the radius the channel opens to.')}>
                  {info.partners.engaged.length ? info.partners.engaged.map((g, i) => (
                    <div key={i}>
                      {t('{by} → {of} {channel}: w {w}, opening {mm}')
                        .replace('{by}', g.by).replace('{of}', g.of).replace('{channel}', g.channel)
                        .replace('{w}', g.w.toFixed(2))
                        .replace('{mm}', g.openingMm === null ? t('pending') : `${g.openingMm.toFixed(1)} mm`)}
                    </div>
                  )) : (info.partners.channels
                    ? t('{n} channels, none engaged.').replace('{n}', String(info.partners.channels))
                    : t('No figure carries a channel.'))}
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  )
}
