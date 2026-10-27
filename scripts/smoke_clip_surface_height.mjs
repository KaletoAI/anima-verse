#!/usr/bin/env node
/**
 * Surface calibration numeric regression. Usage: node scripts/smoke_clip_surface_height.mjs
 * By contract, centimetres describe the 1.70 m figure: +20 cm -> +0.20 m,
 * and a 0.85 m figure gets +0.10 m. Lie, seat and ground are independent;
 * stand/unknown/unmarked and movement use ground, never the previous surface.
 * Actual selected fallback sets and pair halves carry their own metadata.
 */
import assert from 'node:assert/strict'
import { build } from 'rolldown'
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const dir = mkdtempSync(join(tmpdir(), 'clip-surface-height-'))
try {
  const out = join(dir, 'figure.mjs')
  const root = fileURLToPath(new URL('../', import.meta.url))
  const entry = join(dir, 'entry.ts')
  writeFileSync(entry, `
    export * as THREE from ${JSON.stringify(fileURLToPath(import.meta.resolve('three')))};
    export { clipHeightOffsetM, clipHeightGroup } from ${JSON.stringify(join(root, 'packages/scene-render/src/figure.ts'))};
    export { FigureLibrary, Figure, setClipHeightOffsets } from ${JSON.stringify(join(root, 'client3d/src/scene/figures.ts'))};
    export { setClipTransitions } from ${JSON.stringify(join(root, 'client3d/src/game/walk.ts'))};
    export { commitInListOrder } from ${JSON.stringify(join(root, 'client3d/src/game/clipCommit.ts'))};`)
  await build({ input: entry, platform: 'node',
    output: { file: out, format: 'esm', codeSplitting: false } })
  const { clipHeightOffsetM, clipHeightGroup, THREE, FigureLibrary, Figure,
    setClipHeightOffsets, setClipTransitions, commitInListOrder } = await import(pathToFileURL(out).href)
  const near = (a, b) => assert.ok(Math.abs(a - b) < 1e-12, `${a} != ${b}`)
  const selected = { lie: 20, seat: -4, ground: 3 }
  near(clipHeightOffsetM(selected, 'lie', 1.7), 0.20)
  near(clipHeightOffsetM(selected, 'lie', 0.85), 0.10)
  near(clipHeightOffsetM(selected, 'seat', 1.7), -0.04)
  for (const group of ['stand', undefined, '', 'unknown', 'ground']) {
    assert.equal(clipHeightGroup(group), 'ground')
    near(clipHeightOffsetM(selected, group), 0.03)
  }
  // Same playing clip changes group without changing animation kind.
  assert.deepEqual(['lie', 'seat', 'ground', 'lie'].map(g => clipHeightOffsetM(selected, g)),
    [0.2, -0.04, 0.03, 0.2])
  near(clipHeightOffsetM({ lie: 20 }, 'seat'), 0)
  near(clipHeightOffsetM(undefined, 'lie'), 0)
  near(clipHeightOffsetM({ lie: Number.NaN }, 'lie'), 0)
  // Real listing commit -> fallback set clone -> Figure playback. The preferred
  // set is missing: neutral sit has +20 lie/-4 seat/+3 ground cm, female sit
  // has +90 cm. The rendered figure MUST use neutral, never nominal female.
  const sources = [
    { kind: 'sit', set: '', url: 'neutral', heightOffsets: selected },
    { kind: 'sit', set: 'female', url: 'female', heightOffsets: { lie: 90 } },
    ...['a', 'b'].map(role => ({ kind: `pair__${role}`, set: '', url: role,
      heightOffsets: selected })),
    { kind: 'bridge', set: '', url: 'bridge', heightOffsets: { ground: 7, lie: 80 } },
  ]
  const committed = commitInListOrder(sources,
    sources.map(s => ({ clip: new THREE.AnimationClip(s.kind, 1, []) })), {
      rename: (clip, kind) => { clip.name = kind; return clip },
      setFlags: (clip, source) => setClipHeightOffsets(clip, source.heightOffsets),
      isPair: () => false, pairRoot: () => null,
    })
  const library = new FigureLibrary()
  library.clipIndex = committed.index
  library.charSets.set('demo', ['missing'])
  const clips = library.clipsFor('demo')
  for (const height of [1.7, 0.85]) {
    const figure = new Figure({ name: 'demo', template: new THREE.Group(), clips,
      scale: 1, height, assignOnly: true, noClips: false, tier: 'full', libraryFits: true })
    const inst = figure.root.children[0]
    const factor = height / 1.7
    for (const [group, expected] of [['lie', .20], ['seat', -.04], ['ground', .03]]) {
      figure.play('sit-missing', false, 0, group) // actual family fallback = sit
      near(inst.position.y, expected * factor)
    }
    figure.play('sit-missing', true, 0, 'lie') // terrain must override stale lie
    near(inst.position.y, .03 * factor)
    for (const half of ['a', 'b']) {
      assert.equal(figure.playPair(`pair__${half}`, 0, false, true, 'lie'), true)
      near(inst.position.y, .20 * factor)
      figure.playPair(`pair__${half}`, .1, false, true, 'seat')
      near(inst.position.y, -.04 * factor)
    }
    // Correction is WORLD-up, not the leaned body's local up. A 90-degree
    // tilt would turn local Y into Z; a 90-degree roll would turn it into X.
    // Subtract an identical uncalibrated figure, leaving exactly (0,+h,0).
    const baseline = new Figure({ name: 'demo-baseline', template: new THREE.Group(),
      clips: clips.map(c => c.clone()), scale: 1, height, assignOnly: true,
      noClips: false, tier: 'full', libraryFits: true })
    const baselineInst = baseline.root.children[0]
    for (const [tilt, roll] of [[90, 0], [0, 90], [35, -20], [0, 0]]) {
      figure.play('sit', false, 0, 'lie')
      baseline.play('sit', false, 0, 'lie')
      figure.setLean(tilt, roll)
      baseline.setLean(tilt, roll)
      for (let frame = 0; frame < 4; frame++) {
        figure.faceTowards(new THREE.Vector3(1, 0, 0), true)
        baseline.faceTowards(new THREE.Vector3(1, 0, 0), true)
        figure.update(0, { realDelta: 0 })
        baseline.update(0, { realDelta: 0 })
        const delta = inst.getWorldPosition(new THREE.Vector3())
          .sub(baselineInst.getWorldPosition(new THREE.Vector3()))
        near(delta.x, 0)
        near(delta.y, .20 * factor)
        near(delta.z, 0)
      }
    }
    baseline.dispose()
    figure.play('sit', false, 0, 'lie')
    setClipTransitions([{ from: 'sit', to: 'walk', kind: 'bridge', accel: 0 }])
    figure.play('walk', false, 0, 'lie')
    near(inst.position.y, .07 * factor) // bridge owns ground, not previous lie
    setClipTransitions([])
    figure.dispose()
  }
  console.log('clip surface height: numeric scaling and group transition checks passed')
} finally {
  rmSync(dir, { recursive: true, force: true })
}
