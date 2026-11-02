#!/usr/bin/env node
/** Hand-derived: 1.5 + 1.2 + 1.5 = 4.2 seconds. At a join the next
 * segment starts; the final endpoint stays visible. A 180° turn sends
 * the next segment's +0.2 z to -0.2 z: -0.4 - 0.2 = -0.6 m. */
import assert from 'node:assert/strict'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
// Match the existing smokes: hoisted esbuild, then the frontend workspace.
let esbuild
try { esbuild = await import('esbuild') }
catch { esbuild = await import(new URL('../frontend/node_modules/esbuild/lib/main.js', import.meta.url)) }
const { build } = esbuild
const dir = mkdtempSync(join(tmpdir(), 'transition-sequence-'))
try {
  await build({ entryPoints: ['frontend/src/tabs/poses/transitionSequence.ts'], bundle: true, platform: 'node', format: 'esm', outfile: join(dir, 'sequence.mjs') })
  const { segmentAt, chainRoots, clipWindow } = await import(join(dir, 'sequence.mjs'))
  const segments = [1.5, 1.2, 1.5].map((endS) => ({ url: '', startS: 0, endS }))
  for (const [t, index] of [[0, 0], [1.49, 0], [1.5, 1], [2.7, 2], [4.2, 2], [4.21, null]]) {
    assert.equal(segmentAt(segments, t)?.index ?? null, index)
  }
  assert.equal(segmentAt([{ url: '', startS: 3, endS: 4 }], 0.5).localS, 3.5)
  assert.equal(segmentAt([], 0), null)
  // A looping 2 s start sampled at 0.5 s needs its tail 1..2 and head 0..0.5.
  assert.deepEqual(clipWindow('start', 0.5, 2, true, true), [
    { url: 'start', startS: 1, endS: 2 }, { url: 'start', startS: 0, endS: 0.5 },
  ])
  assert.deepEqual(clipWindow('target', 1.5, 2, true, false), [
    { url: 'target', startS: 1.5, endS: 2 }, { url: 'target', startS: 0, endS: 1 },
  ])
  assert.deepEqual(clipWindow('one-shot', 0.5, 2, false, true), [{ url: 'one-shot', startS: 0, endS: 0.5 }])
  const roots = chainRoots([{ x: 0, z: -0.4, yaw: Math.PI }, { x: 0, z: 0.2, yaw: 0 }])
  assert.equal(roots.length, 3)
  for (const [i, z] of [[0, 0], [1, -0.4], [2, -0.6]]) {
    assert.ok(Math.abs(roots[i].x) < 1e-9)
    assert.ok(Math.abs(roots[i].z - z) < 1e-9)
  }
  assert.equal(roots[2].yaw, Math.PI)
  await build({ entryPoints: ['frontend/src/tabs/poses/transitionSelection.ts'], bundle: true, platform: 'node', format: 'esm', outfile: join(dir, 'selection.mjs') })
  const { transitionClip, transitionOptions, transitionSets } = await import(join(dir, 'selection.mjs'))
  const poses = [{ key: 'standing', animation: 'idle', participants: 1 }, { key: 'hug', animation: 'hug', participants: 2 },
    { key: 'crowd', animation: 'crowd', participants: 5 }]
  const listing = { clips: [
    { kind: 'idle', role: '', set: '', url: 'idle.fbx' },
    { kind: 'hug', role: 'a', set: 'female', url: 'female-a.fbx' },
    { kind: 'hug', role: 'b', set: '', url: 'neutral-b.fbx' },
    { kind: 'hug', role: 'b', set: 'male', url: 'male-b.fbx' },
    ...['a', 'b', 'c', 'd', 'e'].map((role) => ({ kind: 'crowd', role, set: '', url: `${role}.fbx` })),
    { kind: 'hug', role: 'c', set: '', url: 'not-an-animation.json' },
  ] }
  assert.deepEqual(transitionOptions(poses, listing), [
    { pose: 'walking', role: '' }, { pose: 'standing', role: '' },
    { pose: 'hug', role: 'a' }, { pose: 'hug', role: 'b' },
    { pose: 'crowd', role: 'a' }, { pose: 'crowd', role: 'b' }, { pose: 'crowd', role: 'c' },
    { pose: 'crowd', role: 'd' }, { pose: 'crowd', role: 'e' },
  ])
  assert.equal(transitionClip(poses, listing, 'hug', 'male', 'b').url, 'male-b.fbx')
  assert.equal(transitionClip(poses, listing, 'hug', 'female', 'b').url, 'neutral-b.fbx')
  assert.equal(transitionClip(poses, listing, 'hug', 'male', 'a'), undefined)
  assert.equal(transitionClip(poses, listing, 'walking', 'female').url, 'idle.fbx')
  assert.deepEqual(transitionSets(poses, listing, 'hug', 'a'), ['female'])
  assert.deepEqual(transitionSets(poses, listing, 'hug', 'b'), ['', 'male'])
  await build({ entryPoints: ['frontend/src/tabs/poses/clipPreviewPlacement.ts'], bundle: true, platform: 'node', format: 'esm', outfile: join(dir, 'placement.mjs') })
  const { previewCalibration, relativeTargetRoot } = await import(join(dir, 'placement.mjs'))
  // B at x=.4, A at -.4: delta .8. B shift +10 cm, A -10 cm:
  // delta becomes 1 m. Turning +90 degrees sends +X to -Z.
  const a = previewCalibration([-10, 0], .02)
  const b = previewCalibration([10, 0], .03)
  assert.equal(a.y, .02)
  const relative = relativeTargetRoot({ x: .4, z: 0 }, { x: -.4, z: 0 }, b, a, Math.PI / 2)
  assert.ok(Math.abs(relative.x) < 1e-9)
  assert.ok(Math.abs(relative.z + 1) < 1e-9)
  assert.deepEqual(relativeTargetRoot({ x: .4, z: 0 }, { x: .4, z: 0 }, b, b, 0), { x: 0, z: 0 })
  console.log('PASS transition selection: solo/pair/group roles, set fallback and availability')
  console.log('PASS transition placement: target-relative partners, sidecar shift and rotation')
  console.log('PASS transition sequence: boundaries, local time, composed travel and turn')
} finally { rmSync(dir, { recursive: true, force: true }) }
