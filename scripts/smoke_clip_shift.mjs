#!/usr/bin/env node
/** Usage: node scripts/smoke_clip_shift.mjs
 * Hand derivations in shared/test-vectors/clip_shift.json. This exercises
 * actual set selection, derived clips, solo/pair playback, lean and movement;
 * losing metadata or applying a shift twice changes world body positions.
 */
import assert from 'node:assert/strict'
import { build } from 'rolldown'
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const dir = mkdtempSync(join(tmpdir(), 'clip-shift-'))
try {
  const root = fileURLToPath(new URL('../', import.meta.url))
  const entry = join(dir, 'entry.ts'), out = join(dir, 'check.mjs')
  writeFileSync(entry, `
    export * as THREE from ${JSON.stringify(fileURLToPath(import.meta.resolve('three')))};
    export { clipShiftM } from ${JSON.stringify(join(root, 'packages/scene-render/src/figure.ts'))};
    export { FigureLibrary, Figure, setClipShift, setClipRootPath } from ${JSON.stringify(join(root, 'client3d/src/scene/figures.ts'))};
    export { commitInListOrder } from ${JSON.stringify(join(root, 'client3d/src/game/clipCommit.ts'))};`)
  await build({ input: entry, platform: 'node', output: { file: out, format: 'esm', codeSplitting: false } })
  const { THREE, clipShiftM, FigureLibrary, Figure, setClipShift, setClipRootPath, commitInListOrder } = await import(pathToFileURL(out).href)
  const vectors = JSON.parse(readFileSync(join(root, 'shared/test-vectors/clip_shift.json')))
  assert.equal(vectors.format, 'anima-test-vectors/1')
  const near = (a, b) => assert.ok(Math.abs(a - b) < 1e-10, `${a} != ${b}`)
  const sources = ['sit', 'pair__a', 'pair__b', 'plain', 'entry', 'exit'].map(kind => ({kind, set: '', url: kind,
    shift: kind === 'plain' ? undefined : kind === 'exit' ? [-10, 20] : [25, -40]}))
  const index = commitInListOrder(sources, sources.map(s => ({clip: new THREE.AnimationClip(s.kind, 1, s.kind === 'entry' || s.kind === 'exit'
    ? [new THREE.VectorKeyframeTrack('Hips.position', [0, 1], s.kind === 'entry' ? [0, 1, 0, 0, .5, 0] : [0, .5, 0, 0, 1, 0])] : [])})), {
    rename: (c, name) => { c.name = name; return c },
    setFlags: (c, s) => setClipShift(c, s.shift),
    isPair: () => false, pairRoot: () => null,
  })
  const library = new FigureLibrary()
  library.clipIndex = index.index
  library.charSets.set('demo', ['missing'])
  for (const height of [1.7, .85, 2.1]) {
    const template = new THREE.Group(), hips = new THREE.Object3D(); hips.name = 'Hips'; template.add(hips)
    const clips = library.clipsFor('demo')
    // Fitting computes root paths after set-chain selection.
    for (const clip of clips) if (clip.name === 'entry' || clip.name === 'exit')
      setClipRootPath(clip, {times: new Float32Array([0, 1]), xz: new Float32Array([0, 0, 0, 0])})
    const fig = new Figure({name: 'demo', template, clips,
      scale: 1, height, assignOnly: true, noClips: false, tier: 'full', libraryFits: true})
    const inst = fig.root.children[0]
    for (const v of vectors.cases) {
      const yaw = v.yaw_deg * Math.PI / 180
      const measured = clipShiftM(v.shift_cm, yaw)
      near(measured.x, v.world_m[0]); near(measured.z, v.world_m[1])
    }
    for (const [tilt, roll] of [[0, 0], [90, 0], [0, 90], [35, -20]]) {
      for (const v of vectors.cases.filter(v => v.shift_cm[0] === 25)) {
        for (const mode of ['solo', 'moving', 'a', 'b']) {
          fig.root.position.set(3, 2, 5)
          fig.root.rotation.set(tilt * Math.PI / 180, v.yaw_deg * Math.PI / 180, roll * Math.PI / 180, 'YXZ')
          fig.targetYaw = fig.root.rotation.y
          if (mode === 'a' || mode === 'b') assert.equal(fig.playPair(`pair__${mode}`, 0, false, true, 'lie'), true)
          else fig.play('sit-fallback', mode === 'moving', 0, 'seat')
          for (let i = 0; i < 4; i++) {
            fig.update(0, {realDelta: 0})
            const p = inst.getWorldPosition(new THREE.Vector3())
            near(p.x, 3 + v.world_m[0]); near(p.y, 2); near(p.z, 5 + v.world_m[1])
          }
        }
      }
    }
    fig.setLean(0, 0)
    fig.play('plain')
    fig.update(0, {realDelta: 0})
    near(inst.position.x, 0); near(inst.position.z, 0)
    // B1 owns a manually sought entry/exit, bypassing normal play().
    assert.equal(fig.playPropEntry('entry', 0, 170, 0, 0, .5, 0, false), true)
    let point = inst.getWorldPosition(new THREE.Vector3())
    near(point.x, 3.25); near(point.z, 4.6)
    assert.equal(fig.playPropEntry('exit', 0, 170, 0, .5, 0, 0, false), true)
    point = inst.getWorldPosition(new THREE.Vector3())
    near(point.x, 2.9); near(point.z, 5.2)
    fig.dispose()
  }
  console.log('OK: shared shift vectors, selected-set clones, solo/movement/pair bodies, yaw, lean, absolute cm, B1 entry/exit and reset')
} finally { rmSync(dir, {recursive: true, force: true}) }
