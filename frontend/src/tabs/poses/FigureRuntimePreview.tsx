/**
 * FigureRuntimePreview — ONE character of the world playing the edited clip through the SHARED per-figure runtime
 * (`@anima/scene-render` `FigureRuntime` + `runFigureFrame`, Ruling A110 phase 1): the same secondary motion, GPU
 * garment push, per-strand hair and two-phase frame the 3D client runs, so hair and secondary motion look here as
 * they do in the game. Phase 2 grows this into the place preview (prop, places A…X, several figures).
 *
 * Only characters with a built model can be picked (D1); the others are listed greyed out with the step that
 * builds one. The model comes from `GET /characters/{name}/model3d` (the 3D client's source), the strand record
 * from its `hair_strands` URL, the clip from the clip library like the neutral preview above it.
 *
 * Frame per tick: mixer (phase A, in place) → `runtime.poseStep` → `runFigureFrame` (phase B). The frame time of
 * that work is shown in the corner (ms), so a slow preview is visible, not guessed.
 *
 * three.js is imported dynamically — the admin bundle must not carry it for tabs that never show 3D.
 */
import { useEffect, useRef, useState } from 'react'
import type { Object3D } from 'three'
import { FIGURE_HEIGHT_M, STRAND_RECORD_VERSION, anchorFigureBind, bindRelativeClip, clipHipsDrop, createFigureRuntime,
  installSkinnedNormalCorrection, restCorrections, restPoseOf, runFigureFrame,
  type CollisionPayload, type HairStrandRecord, type SecondaryMotionPayload } from '@anima/scene-render'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet } from '../../lib/api'
import { loadCharacters } from '../../lib/refs'
import { standHipsRef } from '../characters/Model3DViewer'
import { rootAt, rootPath } from './ClipPreview'
import { ModelTurnHint } from '../../components/ModelTurnHint'
import { attachModelTurn, configureViewControls, poseMatrix } from '../../lib/modelTurn'

interface ModelAnswer {
  model?: {
    url?: string; collision?: CollisionPayload | null
    hair_strands?: { url?: string; sha256?: string } | null
    built_at?: string; generated_at?: string
  }
  motion?: SecondaryMotionPayload
}
interface ApiClip { kind: string; role?: string; set?: string; url: string }

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

export function FigureRuntimePreview({ kind, set = '', height = 300, bust = 0 }: {
  kind: string; set?: string; height?: number; bust?: number
}) {
  const { t } = useI18n()
  const rows = useBuiltCharacters()
  const [name, setName] = useState('')
  const [status, setStatus] = useState('')
  const [info, setInfo] = useState<{ ms: number; strands: boolean; chains: number; swingMm: number } | null>(null)
  const hostRef = useRef<HTMLDivElement>(null)

  // Pick the first built character once the list is known.
  useEffect(() => {
    if (!name && rows) {
      const first = rows.find((r) => r.built)
      if (first) setName(first.name)
    }
  }, [rows, name])

  useEffect(() => {
    const host = hostRef.current
    if (!host || !name || !kind) return
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
        const { createGLTFLoader } = await import('../../lib/gltfLoader')
        const answer = await apiGet<ModelAnswer>(`/characters/${encodeURIComponent(name)}/model3d`)
        const m = answer.model
        if (!m?.url) { setStatus(t('No model yet — build one in Characters → Figure.')); return }
        const listing = await apiGet<{ clips?: ApiClip[] }>('/assets/animation-clips')
        const clips = listing.clips || []
        const want = set.trim()
        const pick = (role: string) =>
          (want ? clips.find((c) => c.kind === kind && (c.role || '') === role && (c.set || '') === want) : undefined)
          || clips.find((c) => c.kind === kind && (c.role || '') === role && !c.set)
          || clips.find((c) => c.kind === kind && (c.role || '') === role)
        // A pair or group clip: role a stands in for phase 1 (one figure).
        const clipRef = pick('') || pick('a')
        if (!clipRef) { setStatus(t('No clip file for this kind in shared/models/clips.')); return }
        const [gltf, clipObj, rig, standRefCm] = await Promise.all([
          createGLTFLoader().loadAsync(m.url),
          new FBXLoader().loadAsync(bust ? `${clipRef.url}${clipRef.url.includes('?') ? '&' : '?'}v=${bust}` : clipRef.url),
          new FBXLoader().loadAsync('/assets/animation-rig').catch(() => null),
          standHipsRef(),
        ])
        const standRefM = (standRefCm || 0) / 100
        let record: HairStrandRecord | null = null
        const ref = m.hair_strands
        if (ref?.url) {
          const res = await fetch(ref.url).catch(() => null)
          const json = res?.ok ? await res.json().catch(() => null) as HairStrandRecord | null : null
          record = json && json.version === STRAND_RECORD_VERSION ? json : null
        }
        if (disposed) return

        // ── scene ──
        const width = host.clientWidth || 480
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
        const stage = new THREE.Group()
        stage.matrixAutoUpdate = false
        scene.add(stage)
        // A 0.5 m grid (4 m wide) and the 1.70 m reference figure height as a post beside the figure.
        const grid = new THREE.GridHelper(4, 8, 0x7a8594, 0x3a4350)
        stage.add(grid)
        const postGeom = new THREE.CylinderGeometry(0.01, 0.01, FIGURE_HEIGHT_M, 6)
        const postMat = new THREE.MeshBasicMaterial({ color: 0xffc857 })
        const post = new THREE.Mesh(postGeom, postMat)
        post.position.set(-0.6, FIGURE_HEIGHT_M / 2, 0)
        stage.add(post)
        disposers.push(() => { postGeom.dispose(); postMat.dispose(); grid.geometry.dispose()
          ;(grid.material as { dispose: () => void }).dispose() })

        // ── the figure: the loaded scene IS the instance (this mount owns it; nothing is cloned or shared) ──
        const inst = gltf.scene as Object3D
        inst.traverse((o) => { o.frustumCulled = false })
        anchorFigureBind(THREE, inst, FIGURE_HEIGHT_M)
        const root = new THREE.Group()
        root.add(inst)
        stage.add(root)
        root.updateMatrixWorld(true)
        const box = new THREE.Box3().setFromObject(inst)
        const size = box.getSize(new THREE.Vector3())
        const runtime = createFigureRuntime(THREE, {
          root, template: inst, motion: () => answer.motion, collision: m.collision, tier: 'full',
          bindRadius: Math.max(FIGURE_HEIGHT_M, Math.hypot(size.x / 2, size.y, size.z / 2)),
        })
        if (record) {
          runtime.loadStrandRecord = () => record
          if (runtime.prepareStrandHair()) runtime.setStrandHair(true)
        }
        // The clip, in place and bind-relative (the same routine every admin viewer uses).
        const raw = clipObj.animations?.[0]
        if (!raw) { setStatus(t('No clip file for this kind in shared/models/clips.')); return }
        // The clip plays in place; its hips HEIGHT lowers the root by the shared rule (`clipHipsDrop`), so a sitting
        // clip sits instead of floating — the same rule as the neutral preview above.
        const path = rootPath(raw, standRefM)
        raw.tracks = raw.tracks.filter((tr) => !(/hips/i.test(tr.name) && tr.name.endsWith('.position')))
        let hipsBindY = FIGURE_HEIGHT_M * 0.55
        inst.traverse((o) => { if (/hips/i.test(o.name) && hipsBindY === FIGURE_HEIGHT_M * 0.55) hipsBindY = o.getWorldPosition(new THREE.Vector3()).y })
        const bound = rig ? bindRelativeClip(THREE, raw, restCorrections(THREE, restPoseOf(THREE, rig), inst)) : raw
        const mixer = new THREE.AnimationMixer(inst)
        const action = mixer.clipAction(bound)
        action.play()
        disposers.push(() => {
          mixer.stopAllAction()
          mixer.uncacheRoot(inst)
          runtime.dispose()
          // This mount loaded the model itself: its geometry, materials and textures are its own.
          inst.traverse((o) => {
            const mesh = o as unknown as { geometry?: { dispose(): void }; material?: unknown; skeleton?: { dispose(): void } }
            mesh.geometry?.dispose()
            mesh.skeleton?.dispose()
            const mats = Array.isArray(mesh.material) ? mesh.material : mesh.material ? [mesh.material] : []
            for (const mat of mats as Array<{ dispose(): void } & Record<string, unknown>>) {
              for (const v of Object.values(mat)) {
                if (v && typeof v === 'object' && (v as { isTexture?: boolean }).isTexture) (v as { dispose(): void }).dispose()
              }
              mat.dispose()
            }
          })
        })

        const camera = new THREE.PerspectiveCamera(35, width / height, 0.05, 100)
        camera.position.set(0.5, 1.3, 2.6)
        const controls = new OrbitControls(camera, renderer.domElement)
        controls.target.set(0, 0.8, 0)
        configureViewControls(THREE, controls)
        controls.update()
        disposers.push(() => controls.dispose())
        const turn = attachModelTurn(host)
        disposers.push(() => turn.dispose())
        const PIVOT: [number, number, number] = [0, 0.9, 0]
        // The evidence that the hair moves (and how much): every hair chain tip's travel in the HEAD's frame, the
        // largest over the run in mm — on the root `data-hair-swing-mm` for headless checks, and in the readout.
        let head: Object3D | null = null
        const tips: Object3D[] = []
        inst.traverse((o) => {
          if (/^mixamorig:?head$/i.test(o.name)) head = o
          if (/^HairGen_.*_end$/.test(o.name)) tips.push(o)
        })
        const tipRest = new Map<Object3D, InstanceType<typeof THREE.Vector3>>()
        const scratch = new THREE.Vector3()
        let swingMm = 0
        const frameState = { openingTurn: 0 }
        const entry = [{ name, interaction: null, figure: runtime }]
        let last = performance.now()
        let lastInfo = 0
        let ms = 0
        setStatus('')
        const tick = () => {
          if (disposed) return
          raf = requestAnimationFrame(tick)
          const now = performance.now()
          const dt = Math.min(0.1, (now - last) / 1000)
          last = now
          turn.tick(dt)
          stage.matrix.fromArray(poseMatrix(turn.pose, PIVOT))
          stage.matrixWorldNeedsUpdate = true
          const t0 = performance.now()
          mixer.update(dt)                        // phase A: the pose and the clip's hips height
          root.position.y = standRefM ? -clipHipsDrop(hipsBindY, rootAt(path, action.time).y, standRefM) : 0
          root.updateMatrixWorld(true)
          runtime.poseStep({ realDelta: dt })
          runFigureFrame(entry, frameState)       // phase B: strands, secondary motion
          ms = ms * 0.9 + (performance.now() - t0) * 0.1
          const h = head as Object3D | null
          if (h && tips.length) {
            for (const tip of tips) {
              h.worldToLocal(tip.getWorldPosition(scratch))
              const rest = tipRest.get(tip)
              if (!rest) tipRest.set(tip, scratch.clone())
              else swingMm = Math.max(swingMm, rest.distanceTo(scratch) * 1000 * h.getWorldScale(new THREE.Vector3()).x)
            }
            host.dataset.hairSwingMm = swingMm.toFixed(0)
          }
          if (now - lastInfo > 250) {
            lastInfo = now
            setInfo({ ms, strands: runtime.strandRunning, chains: Object.keys(answer.motion?.groups ?? {}).length, swingMm })
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
  }, [name, kind, set, height, bust, t])

  return (
    <div style={{ border: '1px solid var(--border, #30363d)', borderRadius: 4, padding: 6 }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 12, marginBottom: 4 }}>
        <strong>{t('Character on the shared runtime')}</strong>
        <select value={name} onChange={(e) => setName(e.target.value)} style={{ maxWidth: 200 }}
          title={t('Only characters with a built model can be picked.')}>
          <option value="">—</option>
          {(rows ?? []).map((r) => (
            <option key={r.name} value={r.name} disabled={!r.built}>
              {r.built ? r.name : `${r.name} — ${t('no model yet (Characters → Figure)')}`}
            </option>
          ))}
        </select>
        {info ? (
          <span style={{ marginLeft: 'auto', opacity: 0.8 }}
            title={t('Phase B of the two-phase frame: secondary motion and strand hair.')}>
            {info.strands ? t('strand hair') : t('hair on chains')} · {t('{n} motion groups').replace('{n}', String(info.chains))}
            {' · '}{t('hair swing {mm} mm').replace('{mm}', info.swingMm.toFixed(0))}
            {' · '}{info.ms.toFixed(1)} ms
          </span>
        ) : null}
      </div>
      <div ref={hostRef} style={{ position: 'relative', height, background: 'var(--surface-2, #161b22)' }}>
        {status ? <div style={{ position: 'absolute', inset: 8, fontSize: 12, opacity: 0.8 }}>{status}</div> : null}
      </div>
      <ModelTurnHint />
    </div>
  )
}
