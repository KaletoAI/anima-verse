/**
 * ClipPreview — a neutral 1.70 m figure playing an animation kind; for a PAIR
 * kind two figures playing the two halves together, the way the 3D client
 * does it (contract § A8a):
 *
 *   * a solo clip plays in place (the hips position track is dropped, as in
 *     every renderer); a pair's halves share ONE anchor frame (origin = the
 *     anchor, +X from A to B) and each figure's ROOT follows the hips XZ of
 *     its half (centimetres → metres);
 *   * all mixers are driven from ONE clock, so a handshake meets and a dance
 *     stays in step — which is what this preview exists to judge;
 *   * a 1 m grid, the anchor and (for a pair) the live A↔B root distance give
 *     the metres a reference (a figure is 1.70 m, the scale used everywhere).
 *
 * A PAIR pose that names a place type is previewed ON that place: a virtual
 * marker box of the type's size, facing SOUTH, and the two figures anchored
 * to it by the SERVER's formula (`places.pair_yaw`) — yaw = facing − 90° +
 * `yaw_offset`, the root `root_drop × 1.70` under the marked surface. That is
 * what the `yaw_offset` slider under the canvas dials: the preview turns the
 * pair against the bench exactly as the running interaction will.
 *
 * three.js is imported dynamically, like in Model3DViewer — the admin bundle
 * must not carry it for the tabs that never show 3D.
 */
import { useEffect, useRef, useState } from 'react'
import type { AnimationClip, Object3D } from 'three'
import { anchorFigureBind } from '@anima/scene-render'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet } from '../../lib/api'
import { loadTestFigure } from '../characters/Model3DViewer'
import { SliderInput } from '../../components/SliderInput'

const FIGURE_H = 1.7

/** The virtual marker a pair is played on, per place type.
 *
 *  `size` is width × height × depth in metres, the width across the marker's
 *  facing. `support` says what the box IS: a body the figures rest on (seat,
 *  bed, floor — the marked surface is its TOP, the root sinks `root_drop`
 *  below that), or furniture they stand AT. A counter's `root_drop` is 0
 *  because the marked surface is the floor spot where the person stands; the
 *  counter body belongs in FRONT of them, so its box keeps the ground plane
 *  and is pushed out along the marker facing.
 *
 *  A stand (and any place type without a body — an unknown or empty group)
 *  has no box: the pair plays on the ground, the way this preview always did. */
interface MarkerBox {
  size: [number, number, number]
  support: boolean
}

/** Gap between the figures' floor spot and the furniture they stand at. */
const FRONT_GAP_M = 0.2

const MARKER_BOX: Record<string, MarkerBox> = {
  seat: { size: [0.5, 0.45, 0.5], support: true },
  bed: { size: [2.0, 0.5, 1.0], support: true },
  floor: { size: [1.0, 0.05, 0.6], support: true },
  counter: { size: [1.0, 0.9, 0.6], support: false },
}

function markerBox(group?: string): MarkerBox | undefined {
  return MARKER_BOX[(group || '').trim().toLowerCase()]
}

/** Y rotation (radians) of the clip frame on the marker — the server's rule
 *  (`app/core/places.py: pair_yaw`) with the preview's marker facing SOUTH
 *  (compass 0): clip +X (A → B) falls along `facing − 90° + yaw_offset`. */
function pairYaw(yawOffsetDeg: number): number {
  return ((0 - 90 + yawOffsetDeg) * Math.PI) / 180
}

interface ApiClip { kind: string; role?: string; set?: string; url: string }

/** Explicit clip URLs instead of a kind lookup — how the CMU catalog browser
 *  previews a TRIAL clip, which is in no library and has no kind yet. */
export interface ClipUrls { a?: string; b?: string; solo?: string }

/** Root path of a half: hips XZ per key, clip centimetres → metres. */
/** Standing hips height of the clip library's skeleton (metres) — every
 *  converted clip puts a standing actor's hips there (cmu_clip leg ratio). */
const CLIP_STAND_HIPS_M = 1.13

function rootPath(clip: AnimationClip): { times: ArrayLike<number>; xyz: Float32Array } {
  const track = clip.tracks.find((tr) => tr.name.endsWith('.position') && /hips/i.test(tr.name))
  if (!track) return { times: [0], xyz: new Float32Array([0, CLIP_STAND_HIPS_M, 0]) }
  const n = track.times.length
  const xyz = new Float32Array(n * 3)
  for (let i = 0; i < n * 3; i++) xyz[i] = track.values[i] / 100
  return { times: track.times, xyz }
}

function rootAt(path: { times: ArrayLike<number>; xyz: Float32Array }, t: number) {
  const { times, xyz } = path
  const n = times.length
  const at = (i: number) => ({ x: xyz[i * 3], y: xyz[i * 3 + 1], z: xyz[i * 3 + 2] })
  if (t <= times[0]) return at(0)
  if (t >= times[n - 1]) return at(n - 1)
  let lo = 0
  let hi = n - 1
  while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (times[mid] <= t) lo = mid; else hi = mid }
  const f = (t - times[lo]) / ((times[hi] - times[lo]) || 1)
  const a = at(lo); const b = at(hi)
  return { x: a.x + (b.x - a.x) * f, y: a.y + (b.y - a.y) * f, z: a.z + (b.z - a.z) * f }
}

/** Play only [start, end) seconds of the clip, looped — what an import with
 *  that window (or the server-computed loop cut) will write. */
export interface PlayWindow { start: number; end: number }

export function ClipPreview({ kind = '', height = 300, urls, window: win, speed = 1,
  group, rootDrop = 0, yawOffset = 0, onYawOffset }:
  { kind?: string; height?: number; urls?: ClipUrls; window?: PlayWindow; speed?: number
    /** place type of the pose — a pair is seated on a virtual marker of it */
    group?: string
    /** how far the figure root sits below the marked surface, as a FRACTION
     *  of the figure height (the place type's `root_drop`) */
    rootDrop?: number
    /** degrees the clip frame turns against the marker facing */
    yawOffset?: number
    /** given = the pose is a pair one and the yaw offset is dialled here */
    onYawOffset?: (deg: number) => void }) {
  const { t } = useI18n()
  const hostRef = useRef<HTMLDivElement | null>(null)
  const [status, setStatus] = useState<string>('')
  const [info, setInfo] = useState<{ dist: number; time: number; duration: number } | null>(null)
  // The effect must not re-run on every render just because the caller passed a
  // fresh object literal — the three URLs go in as ONE string and come apart
  // again inside.
  const urlKey = [urls?.a || '', urls?.b || '', urls?.solo || ''].join('|')
  // The window is read by the running tick through a ref — changing it must
  // not rebuild the whole scene (the figures and clips stay loaded).
  const winRef = useRef<PlayWindow | undefined>(win)
  winRef.current = win
  /** playback factor (0.5 = half speed) — what an import with `speed` bakes in */
  const speedRef = useRef(speed)
  speedRef.current = speed > 0 ? speed : 1
  // Turning the pair on the marker (and a re-dialled root drop) must not
  // reload figure and clips — the running tick reads both through a ref, so
  // dragging the slider moves the couple in the live scene.
  const yawRef = useRef(yawOffset)
  yawRef.current = yawOffset
  const dropRef = useRef(rootDrop)
  dropRef.current = rootDrop
  const box = markerBox(group)
  // Does the loaded clip actually have two halves? Only then is there a pair
  // to seat — a kind without an A/B pair plays solo whatever the pose says.
  const [pairClip, setPairClip] = useState(false)
  // A marker to turn against: a pair clip AND a place type with a body.
  const seated = pairClip && !!box

  useEffect(() => {
    const host = hostRef.current
    const [urlA, urlB, urlSolo] = urlKey.split('|')
    const direct = !!(urlA || urlB || urlSolo)
    if (!host || (!kind && !direct)) return
    let disposed = false
    let raf = 0
    const disposers: Array<() => void> = []
    setStatus(t('Loading…'))
    setInfo(null)
    setPairClip(false)
    void (async () => {
      try {
        const THREE = await import('three')
        const { OrbitControls } = await import('three/examples/jsm/controls/OrbitControls.js')
        const { FBXLoader } = await import('three/examples/jsm/loaders/FBXLoader.js')
        const { clone: skclone } = await import('three/examples/jsm/utils/SkeletonUtils.js')
        let parts: Array<{ role: 'a' | 'b' | ''; url: string }> = []
        if (direct) {
          parts = urlA && urlB
            ? [{ role: 'a', url: urlA }, { role: 'b', url: urlB }]
            : [{ role: '', url: urlSolo || urlA || urlB }]
        } else {
          const listing = await apiGet<{ clips?: ApiClip[] }>('/assets/animation-clips')
          const clips = listing.clips || []
          // neutral set first, then any set of the kind (same pick as the viewers)
          const pick = (role: string) =>
            clips.find((c) => c.kind === kind && (c.role || '') === role && !c.set)
            || clips.find((c) => c.kind === kind && (c.role || '') === role)
          const isPair = !!(pick('a') && pick('b'))
          parts = isPair
            ? [{ role: 'a', url: pick('a')!.url }, { role: 'b', url: pick('b')!.url }]
            : pick('') ? [{ role: '', url: pick('')!.url }] : []
        }
        if (!parts.length) { setStatus(t('No clip file for this kind in shared/models/clips.')); return }
        const src = await loadTestFigure()
        if (!src) { setStatus(t('No test figure available (shared/models/figure).')); return }
        if (disposed) return

        // ── scene ──
        const width = host.clientWidth || 600
        const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true })
        renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2))
        renderer.setSize(width, height)
        host.appendChild(renderer.domElement)
        disposers.push(() => { renderer.dispose(); renderer.domElement.remove() })
        const scene = new THREE.Scene()
        scene.add(new THREE.HemisphereLight(0xffffff, 0x556677, 1.1))
        const key = new THREE.DirectionalLight(0xffffff, 1.2)
        key.position.set(2, 4, 3)
        scene.add(key)
        scene.add(new THREE.GridHelper(8, 8, 0x7a8594, 0x3a4350))
        // The clip frame: origin = the marker anchor, +X = A → B. Seated on a
        // marker it carries the pair's turn and the root drop; without one it
        // stays the identity and the figures stand in world coordinates, as
        // they always did.
        const frame = new THREE.Group()
        scene.add(frame)
        // anchor: a small cross at the origin, +X marked (A → B)
        const axis = new THREE.AxesHelper(0.5)
        frame.add(axis)
        // The virtual marker — a pair only, and only for a place type with a
        // body. It does NOT turn with the clip frame: the marker faces south,
        // and seeing the couple turn against it is the point of the slider.
        const seat = parts.length === 2 ? markerBox(group) : undefined
        setPairClip(parts.length === 2)
        if (seat) {
          const [bw, bh, bd] = seat.size
          const geom = new THREE.BoxGeometry(bw, bh, bd)
          const mesh = new THREE.Mesh(geom, new THREE.MeshStandardMaterial({
            color: 0x7d8ea8, transparent: true, opacity: 0.45, roughness: 0.9,
          }))
          const edges = new THREE.LineSegments(
            new THREE.EdgesGeometry(geom),
            new THREE.LineBasicMaterial({ color: 0xc9d4e4 }),
          )
          // Both kinds stand ON the ground plane; furniture the figures only
          // stand AT is pushed out along the marker facing (+z = south), so
          // the counter is in front of them instead of under them.
          const boxZ = seat.support ? 0 : bd / 2 + FRONT_GAP_M
          for (const o of [mesh, edges]) {
            o.position.set(0, bh / 2, boxZ)
            scene.add(o)
          }
          disposers.push(() => {
            geom.dispose()
            edges.geometry.dispose();
            (mesh.material as { dispose: () => void }).dispose();
            (edges.material as { dispose: () => void }).dispose()
          })
        }
        const camera = new THREE.PerspectiveCamera(40, width / height, 0.05, 100)
        camera.position.set(0.6, 2.2, 4.2)
        const controls = new OrbitControls(camera, renderer.domElement)
        controls.target.set(0, 0.9, 0)
        controls.update()
        disposers.push(() => controls.dispose())

        // ── figures + clips ──
        const fbx = new FBXLoader()
        const players: Array<{ root: Object3D; mixer: InstanceType<typeof THREE.AnimationMixer>; path: ReturnType<typeof rootPath>; duration: number; hipsBindY: number }> = []
        const hipsOf = (root: Object3D): Object3D | null => {
          let found: Object3D | null = null
          root.traverse((o) => { if (!found && /hips/i.test(o.name)) found = o })
          return found
        }
        for (const { role, url } of parts) {
          const obj = await fbx.loadAsync(url)
          const clip = obj.animations?.[0]
          if (!clip || disposed) return
          const path = rootPath(clip)
          // play in place — the root follows the path instead
          const tracks = clip.tracks.filter((tr) => !(/hips/i.test(tr.name) && tr.name.endsWith('.position')))
          const inplace = new THREE.AnimationClip(clip.name, clip.duration, tracks)
          const inst = skclone(src) as Object3D
          const pivot = new THREE.Group()
          pivot.add(inst)
          // up-axis fix between the figure's and the clip's armature (same
          // rule as Model3DViewer / FloorPlanPreview)
          const instHips = hipsOf(inst)
          const clipHips = hipsOf(obj)
          if (instHips?.parent && clipHips?.parent) {
            inst.updateMatrixWorld(true)
            obj.updateMatrixWorld(true)
            const restModel = instHips.parent.getWorldQuaternion(new THREE.Quaternion())
            const restClip = clipHips.parent.getWorldQuaternion(new THREE.Quaternion())
            let bestRx = 0
            let bestAngle = Infinity
            for (const rx of [0, Math.PI / 2, -Math.PI / 2, Math.PI]) {
              const cand = new THREE.Quaternion().setFromEuler(new THREE.Euler(rx, 0, 0)).multiply(restModel)
              const angle = cand.angleTo(restClip)
              if (angle < bestAngle) { bestAngle = angle; bestRx = rx }
            }
            pivot.rotation.x = bestRx
          }
          anchorFigureBind(THREE, pivot, FIGURE_H)
          const root = new THREE.Group()
          root.add(pivot)
          frame.add(root)
          // where the figure's hips sit in its bind pose — the clip's hips
          // height is played RELATIVE to that: a lying clip (hips 0.2 m) drops
          // the body, a standing one (1.13 m) leaves it where it binds
          root.updateMatrixWorld(true)
          const hipsBindY = instHips ? instHips.getWorldPosition(new THREE.Vector3()).y : FIGURE_H * 0.55
          // label A / B over the head (pair only)
          const canvas = document.createElement('canvas')
          canvas.width = 64; canvas.height = 64
          const ctx = canvas.getContext('2d')
          if (ctx && role) {
            ctx.fillStyle = role === 'a' ? '#58a6ff' : '#f78166'
            ctx.font = 'bold 44px sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'
            ctx.fillText(role.toUpperCase(), 32, 34)
          }
          const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(canvas), depthTest: false }))
          sprite.scale.set(0.25, 0.25, 1)
          sprite.position.y = FIGURE_H + 0.2
          root.add(sprite)
          const mixer = new THREE.AnimationMixer(inst)
          mixer.clipAction(inplace).play()
          players.push({ root, mixer, path, duration: clip.duration, hipsBindY })
        }
        if (disposed) return
        setStatus('')
        const fullDuration = Math.min(...players.map((p) => p.duration))
        const started = performance.now()
        let lastInfo = 0
        const tick = () => {
          if (disposed) return
          raf = requestAnimationFrame(tick)
          const w = winRef.current
          const start = w ? Math.min(Math.max(w.start, 0), fullDuration) : 0
          const end = w && w.end > start ? Math.min(w.end, fullDuration) : fullDuration
          const duration = Math.max(end - start, 1 / 30)
          const time = start + (((performance.now() - started) / 1000) * speedRef.current) % duration
          if (seat) {
            // Server formula, both terms: the frame turns by facing − 90° +
            // yaw_offset, and its origin sits `root_drop × 1.70` under the
            // MARKED SURFACE — the box top for a body the figures rest on,
            // the ground plane for furniture they only stand at.
            frame.rotation.y = pairYaw(yawRef.current || 0)
            frame.position.y = (seat.support ? seat.size[1] : 0)
              - (dropRef.current || 0) * FIGURE_H
          }
          for (const p of players) {
            p.mixer.setTime(time)
            const r = rootAt(p.path, time)
            // hips height scaled by this figure's proportion (bind hips over
            // the library's standing 1.13 m), minus the bind height itself
            p.root.position.set(r.x, r.y * (p.hipsBindY / CLIP_STAND_HIPS_M) - p.hipsBindY, r.z)
          }
          if (performance.now() - lastInfo > 150) {
            lastInfo = performance.now()
            const a = players[0].root.position
            const b = players[1]?.root.position
            setInfo({ dist: b ? Math.hypot(a.x - b.x, a.z - b.z) : NaN, time, duration: end })
          }
          controls.update()
          renderer.render(scene, camera)
        }
        tick()
      } catch (e) {
        setStatus(String(e))
      }
    })()
    return () => {
      disposed = true
      cancelAnimationFrame(raf)
      disposers.forEach((d) => d())
    }
  }, [kind, height, urlKey, group, t])

  // What the marker under (or in front of) the pair is — only while one is
  // actually seated on it.
  const markerNote = seated && box
    ? ` · ${t('marker')} ${box.size[0].toFixed(2)} × ${box.size[1].toFixed(2)}`
      + ` × ${box.size[2].toFixed(2)} m, ${t('facing south')}`
      + (box.support
        ? `, ${t('drop')} ${(rootDrop * FIGURE_H).toFixed(2)} m`
        : `, ${t('in front — the figures stand on the floor spot')}`)
    : ''

  return (
    <div style={{ marginTop: 8 }}>
      <div ref={hostRef} style={{ width: '100%', height, borderRadius: 6, overflow: 'hidden', background: '#0d1117' }} />
      <div className="ga-hint" style={{ marginTop: 4 }}>
        {status || (info
          ? (Number.isFinite(info.dist)
            ? `${t('A ↔ B')}: ${info.dist.toFixed(2)} m · ${info.time.toFixed(1)} / ${info.duration.toFixed(1)} s`
              + ` · ${t('figures 1.70 m, grid 1 m, +X = A → B')}` + markerNote
            : `${info.time.toFixed(1)} / ${info.duration.toFixed(1)} s · ${t('figure 1.70 m, grid 1 m, in place')}`)
          : '')}
      </div>
      {onYawOffset ? (
        <>
          <SliderInput
            label={t('Yaw offset')}
            unit="°"
            title={t('Degrees the pair clip’s frame turns against the marker facing. The preview’s marker faces south, so the couple turns exactly as it will on the real bench.')}
            min={-180}
            max={180}
            step={5}
            fineStep={1}
            value={yawOffset}
            onChange={onYawOffset}
            disabled={!seated}
            sliderWidth="auto"
            sliderStyle={{ flex: 1, minWidth: 80 }}
            style={{ display: 'flex', marginTop: 6 }}
          />
          {/* Nothing to turn against: no place type with a body, or a kind
              that has no two halves. The value stays what it is — it is
              edited again as soon as there is a marker to see it on. */}
          {seated ? null : (
            <div className="ga-hint" style={{ marginTop: 2 }}>
              {t('No marker box for this place type')}
            </div>
          )}
        </>
      ) : null}
    </div>
  )
}
