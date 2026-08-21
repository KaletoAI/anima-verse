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
 * three.js is imported dynamically, like in Model3DViewer — the admin bundle
 * must not carry it for the tabs that never show 3D.
 */
import { useEffect, useRef, useState } from 'react'
import type { AnimationClip, Object3D } from 'three'
import { anchorFigureBind } from '@anima/scene-render'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet } from '../../lib/api'
import { loadTestFigure } from '../characters/Model3DViewer'

const FIGURE_H = 1.7

interface ApiClip { kind: string; role?: string; set?: string; url: string }

/** Explicit clip URLs instead of a kind lookup — how the CMU catalog browser
 *  previews a TRIAL clip, which is in no library and has no kind yet. */
export interface ClipUrls { a?: string; b?: string; solo?: string }

/** Root path of a half: hips XZ per key, clip centimetres → metres. */
function rootPath(clip: AnimationClip): { times: ArrayLike<number>; xz: Float32Array } {
  const track = clip.tracks.find((tr) => tr.name.endsWith('.position') && /hips/i.test(tr.name))
  if (!track) return { times: [0], xz: new Float32Array([0, 0]) }
  const n = track.times.length
  const xz = new Float32Array(n * 2)
  for (let i = 0; i < n; i++) {
    xz[i * 2] = track.values[i * 3] / 100
    xz[i * 2 + 1] = track.values[i * 3 + 2] / 100
  }
  return { times: track.times, xz }
}

function rootAt(path: { times: ArrayLike<number>; xz: Float32Array }, t: number) {
  const { times, xz } = path
  const n = times.length
  if (t <= times[0]) return { x: xz[0], z: xz[1] }
  if (t >= times[n - 1]) return { x: xz[(n - 1) * 2], z: xz[(n - 1) * 2 + 1] }
  let lo = 0
  let hi = n - 1
  while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (times[mid] <= t) lo = mid; else hi = mid }
  const f = (t - times[lo]) / ((times[hi] - times[lo]) || 1)
  return { x: xz[lo * 2] + (xz[hi * 2] - xz[lo * 2]) * f, z: xz[lo * 2 + 1] + (xz[hi * 2 + 1] - xz[lo * 2 + 1]) * f }
}

/** Play only [start, end) seconds of the clip, looped — what an import with
 *  that window (or the server-computed loop cut) will write. */
export interface PlayWindow { start: number; end: number }

export function ClipPreview({ kind = '', height = 300, urls, window: win }:
  { kind?: string; height?: number; urls?: ClipUrls; window?: PlayWindow }) {
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
        // anchor: a small cross at the origin, +X marked (A → B)
        const axis = new THREE.AxesHelper(0.5)
        scene.add(axis)
        const camera = new THREE.PerspectiveCamera(40, width / height, 0.05, 100)
        camera.position.set(0.6, 2.2, 4.2)
        const controls = new OrbitControls(camera, renderer.domElement)
        controls.target.set(0, 0.9, 0)
        controls.update()
        disposers.push(() => controls.dispose())

        // ── figures + clips ──
        const fbx = new FBXLoader()
        const players: Array<{ root: Object3D; mixer: InstanceType<typeof THREE.AnimationMixer>; path: ReturnType<typeof rootPath>; duration: number }> = []
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
          scene.add(root)
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
          players.push({ root, mixer, path, duration: clip.duration })
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
          const time = start + ((performance.now() - started) / 1000) % duration
          for (const p of players) {
            p.mixer.setTime(time)
            const r = rootAt(p.path, time)
            p.root.position.set(r.x, 0, r.z)
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
  }, [kind, height, urlKey, t])

  return (
    <div style={{ marginTop: 8 }}>
      <div ref={hostRef} style={{ width: '100%', height, borderRadius: 6, overflow: 'hidden', background: '#0d1117' }} />
      <div className="ga-hint" style={{ marginTop: 4 }}>
        {status || (info
          ? (Number.isFinite(info.dist)
            ? `${t('A ↔ B')}: ${info.dist.toFixed(2)} m · ${info.time.toFixed(1)} / ${info.duration.toFixed(1)} s`
              + ` · ${t('figures 1.70 m, grid 1 m, +X = A → B')}`
            : `${info.time.toFixed(1)} / ${info.duration.toFixed(1)} s · ${t('figure 1.70 m, grid 1 m, in place')}`)
          : '')}
      </div>
    </div>
  )
}
