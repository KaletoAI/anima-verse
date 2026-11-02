import { useEffect, useRef, useState } from 'react'
import type { Object3D } from 'three'
import { anchorFigureBind, clipHipsDrop } from '@anima/scene-render'
import { useI18n } from '../../i18n/I18nProvider'
import { loadTestFigure, standHipsRef } from '../characters/Model3DViewer'
import { loadPreviewClip, rootPath, rootAt } from './ClipPreview'
import { chainRoots, segmentAt, type Segment } from './transitionSequence'

export interface Placement {
  startUrl: string; startTimeS: number; targetUrl: string; targetTimeS: number
  forwardM: number; leftM: number; yawDeg: number
}

/** Shared scene ownership: one-shot sequence or two frozen placement poses. */
export function TransitionScene({ segments, placement, height = 280, replay = 0, onEnded }: {
  segments: Segment[]; placement?: Placement; height?: number; replay?: number; onEnded?: () => void
}) {
  const host = useRef<HTMLDivElement>(null)
  const ended = useRef(onEnded)
  ended.current = onEnded
  const livePlacement = useRef(placement)
  livePlacement.current = placement
  const { t } = useI18n()
  const [status, setStatus] = useState('')
  const key = JSON.stringify(segments)
  const placementMode = !!placement
  useEffect(() => {
    const element = host.current
    if (!element) return
    let disposed = false
    let raf = 0
    const cleanup: Array<() => void> = []
    setStatus(t('Loading…'))
    void (async () => {
      try {
        const THREE = await import('three')
        const { OrbitControls } = await import('three/examples/jsm/controls/OrbitControls.js')
        const { clone } = await import('three/examples/jsm/utils/SkeletonUtils.js')
        const source = await loadTestFigure()
        const stand = ((await standHipsRef()) || 0) / 100
        if (!source) throw new Error(t('No test figure available (shared/models/figure).'))
        const specs: Segment[] = JSON.parse(key)
        const loaded = await Promise.all(specs.map((s) => loadPreviewClip(s.url)))
        // FBX resources belong to this effect; figure resources are shared
        // with the cached test figure and must stay alive.
        const releaseClips = () => loaded.forEach(({ object }) => object.traverse((o) => {
          if (o instanceof THREE.Mesh) {
            o.geometry.dispose()
            for (const material of [o.material].flat()) material.dispose()
          }
        }))
        if (disposed) { releaseClips(); return }
        cleanup.push(releaseClips)
        const scene = new THREE.Scene()
        scene.add(new THREE.HemisphereLight(0xffffff, 0x556677, 2))
        const grid = new THREE.GridHelper(8, 32, 0x7a8594, 0x3a4350)
        scene.add(grid)
        const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true })
        renderer.setPixelRatio(Math.min(devicePixelRatio, 2))
        element.appendChild(renderer.domElement)
        cleanup.push(() => { renderer.dispose(); renderer.domElement.remove() })
        const camera = new THREE.PerspectiveCamera(40, 1, 0.05, 100)
        camera.position.set(3, 2.7, 5)
        const controls = new OrbitControls(camera, renderer.domElement)
        controls.target.set(0, 0.8, 0)
        cleanup.push(() => controls.dispose())
        const resize = () => {
          const width = element.clientWidth || 400
          renderer.setSize(width, height)
          camera.aspect = width / height
          camera.updateProjectionMatrix()
        }
        const observer = new ResizeObserver(resize)
        observer.observe(element); resize()
        cleanup.push(() => observer.disconnect())
        const hipsOf = (root: Object3D) => {
          let hips: Object3D | undefined
          root.traverse((o) => { if (!hips && /hips/i.test(o.name)) hips = o })
          return hips
        }
        const players = loaded.map(({ object, clip }, index) => {
          const inst = clone(source)
          const pivot = new THREE.Group()
          pivot.add(inst)
          const hips = hipsOf(inst)
          const clipHips = hipsOf(object)
          if (hips?.parent && clipHips?.parent) {
            inst.updateMatrixWorld(true); object.updateMatrixWorld(true)
            const modelQ = hips.parent.getWorldQuaternion(new THREE.Quaternion())
            const clipQ = clipHips.parent.getWorldQuaternion(new THREE.Quaternion())
            let best = Infinity
            for (const rx of [0, Math.PI / 2, -Math.PI / 2, Math.PI]) {
              const q = new THREE.Quaternion().setFromEuler(new THREE.Euler(rx, 0, 0)).multiply(modelQ)
              const angle = q.angleTo(clipQ)
              if (angle < best) { best = angle; pivot.rotation.x = rx }
            }
          }
          anchorFigureBind(THREE, pivot, 1.7)
          const root = new THREE.Group(); root.add(pivot); scene.add(root)
          root.updateMatrixWorld(true)
          const bindY = hips?.getWorldPosition(new THREE.Vector3()).y || 0.935
          const path = rootPath(clip, stand)
          const animation = new THREE.AnimationClip(clip.name, clip.duration,
            clip.tracks.filter((tr) => !(/hips/i.test(tr.name) && tr.name.endsWith('.position'))))
          const mixer = new THREE.AnimationMixer(inst)
          const action = mixer.clipAction(animation).setLoop(THREE.LoopOnce, 1)
          action.play().clampWhenFinished = true
          cleanup.push(() => { mixer.stopAllAction(); mixer.uncacheRoot(inst) })
          const heading = (time: number) => {
            action.reset().play(); mixer.setTime(time); root.updateMatrixWorld(true)
            const v = new THREE.Vector3(0, 0, 1).applyQuaternion(hips?.getWorldQuaternion(new THREE.Quaternion()) || new THREE.Quaternion())
            return Math.atan2(v.x, v.z)
          }
          const start = specs[index].startS
          const initialYaw = heading(start)
          const endYaw = heading(specs[index].endS)
          const a = rootAt(path, start); const b = rootAt(path, specs[index].endS)
          const c = Math.cos(initialYaw); const s = Math.sin(initialYaw)
          if (placementMode && index === 1) inst.traverse((o) => {
            if (o instanceof THREE.Mesh) {
              o.material = (Array.isArray(o.material) ? o.material : [o.material]).map((m) => {
                const mat = m.clone(); mat.transparent = true; mat.opacity = 0.35
                cleanup.push(() => mat.dispose()); return mat
              })
            }
          })
          return { root, mixer, action, heading, path, bindY, initialYaw, a,
            end: { x: (b.x - a.x) * c - (b.z - a.z) * s,
              z: (b.x - a.x) * s + (b.z - a.z) * c,
              yaw: Math.atan2(Math.sin(endYaw - initialYaw), Math.cos(endYaw - initialYaw)) } }
        })
        if (placementMode) {
          const reference = clone(source)
          anchorFigureBind(THREE, reference, 1.7)
          reference.position.x = -1.8; scene.add(reference)
        }
        cleanup.push(() => scene.traverse((o) => {
          if (o instanceof THREE.GridHelper) { o.geometry.dispose(); for (const m of [o.material].flat()) m.dispose() }
        }))
        const roots = chainRoots(players.map((p) => p.end))
        const duration = specs.reduce((sum, s) => sum + s.endS - s.startS, 0)
        const started = performance.now()
        let notified = false
        setStatus('')
        const tick = () => {
          if (disposed) return
          const elapsed = (performance.now() - started) / 1000
          const current = segmentAt(specs, Math.min(elapsed, duration))
          for (const [i, p] of players.entries()) {
            const placement = livePlacement.current
            p.root.visible = placementMode || current?.index === i
            if (!p.root.visible) continue
            const time = placement ? (i === 0 ? placement.startTimeS : placement.targetTimeS) : current!.localS
            p.action.reset().play(); p.mixer.setTime(time)
            const r = rootAt(p.path, time)
            const base = placement ? { x: i ? placement.leftM : 0, z: i ? placement.forwardM : 0,
              yaw: i ? placement.yawDeg * Math.PI / 180 : 0 } : roots[i]
            // Normalize each frozen pose's heading at the selected time.
            p.root.rotation.y = 0
            p.root.rotation.y = base.yaw - (placement ? p.heading(time) : p.initialYaw)
            const offset = new THREE.Vector3(placement ? 0 : r.x - p.a.x, 0, placement ? 0 : r.z - p.a.z)
              .applyAxisAngle(new THREE.Vector3(0, 1, 0), p.root.rotation.y)
            p.root.position.set(base.x + offset.x, -clipHipsDrop(p.bindY, r.y, stand), base.z + offset.z)
          }
          if (!placementMode && elapsed >= duration && !notified) { notified = true; ended.current?.() }
          controls.update(); renderer.render(scene, camera)
          raf = requestAnimationFrame(tick)
        }
        tick()
      } catch (error) { if (!disposed) setStatus(String(error)) }
    })()
    return () => { disposed = true; cancelAnimationFrame(raf); cleanup.reverse().forEach((fn) => fn()) }
  }, [key, placementMode, height, replay, t])
  return <><div ref={host} style={{ height, width: '100%', background: '#0d1117' }} />
    <div className="ga-hint">{status || t('Figures 1.70 m · grid 0.25 m')}</div></>
}

export function TransitionSequencePreview({ segments, height, onEnded }: {
  segments: Segment[]; height?: number; onEnded?: () => void
}) {
  const [replay, setReplay] = useState(0)
  const { t } = useI18n()
  return <div><TransitionScene segments={segments} height={height} replay={replay} onEnded={onEnded} />
    <button type="button" className="ga-btn ga-btn-sm" onClick={() => setReplay((n) => n + 1)}>{t('Replay')}</button></div>
}
