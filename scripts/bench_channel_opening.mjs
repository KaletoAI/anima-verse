#!/usr/bin/env node
/**
 * Bench of the channel OPENING's frame cost (Ruling A102b): skipping unchanged frames (`ChannelOpeningBinding.changed`,
 * 1 mm / 0.5°) and the per-frame budget (at most one recompute per frame, receivers visited from a rotating start —
 * the rule `NpcManager.tickSecondary` / `Figure.applyChannelOpenings` run in client3d).
 *
 * Usage:  node scripts/bench_channel_opening.mjs [--frames 300]
 *
 * Self-bundling via esbuild; no server, no world, no outbound request. A synthetic receiving region: 20 480 vertices
 * (rings around a channel of R 35 mm, D 130 mm), skinned to three bones (a root and two side bones, weights blended
 * by side). The occupant: 3 segments of radius 25 mm on the channel axis, carried with the root. 60 frames per second.
 *   held  — nothing moves after the first frame;
 *   walk  — root moves forward 1.4 m/s and sways ±5° about y at 1 Hz, the side bones swing ±25° about x at 1 Hz.
 * Per scenario: 1 receiver and 3 receivers, budget 1 vs no skip/budget (every opening recomputes every frame).
 * Printed: ms per frame (mean, p95), recomputes per frame, the largest frame lag of a receiver (frames since its last
 * recompute while it was changed).
 *
 * The checks it makes (hand reasoning, not timing): the first bind takes a frame's budget, so a receiver's first
 * apply is the frame after. held → exactly one recompute per receiver over the whole run; walk, budget 1 → one
 * recompute per frame from frame 1 on (frames − 1 for one receiver); with 3 receivers, once all are bound (from
 * frame 6), the rotating start serves each every 3rd frame, so none waits more than 2 frames.
 */
import { spawnSync } from 'child_process'
import * as fs from 'fs'
import * as path from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

async function main() {
  if (!process.env.SMOKE_BUNDLED) {
    const bundlePath = '/tmp/bench_channel_opening_bundled.mjs'
    const root = path.join(__dirname, '../')
    const bin = ['client3d/node_modules/.bin/esbuild', 'node_modules/.bin/esbuild']
      .map((rel) => path.join(root, rel)).find((p) => fs.existsSync(p))
    if (!bin) { console.error('esbuild not found (npm install) — nothing was measured'); process.exit(1) }
    const built = spawnSync(bin, [__filename, '--bundle', '--platform=node', '--format=esm', `--outfile=${bundlePath}`],
      { cwd: root, stdio: 'inherit' })
    if (built.status !== 0) process.exit(built.status ?? 1)
    const run = spawnSync('node', [bundlePath, ...process.argv.slice(2)],
      { stdio: 'inherit', env: { ...process.env, SMOKE_BUNDLED: '1' }, cwd: root })
    process.exit(run.status ?? 1)
  }
  const O = await import('../packages/scene-render/src/channelOpening.ts')
  const THREE = await import('three')
  const frames = Number(process.argv[process.argv.indexOf('--frames') + 1]) || 300
  const failures = []
  const check = (label, ok, detail = '') => {
    console.log(`${ok ? 'ok  ' : 'FAIL'} ${label}${detail ? ` — ${detail}` : ''}`)
    if (!ok) failures.push(label)
  }

  /** One receiver: the region mesh, its bones and its channel in bind space (+z into the body). */
  const makeReceiver = (x0) => {
    const pts = [], si = [], sw = []
    const RINGS = 160, PER = 128
    for (let k = 0; k < RINGS; k++) {
      const s = -0.06 + (0.25 * k) / RINGS
      for (let i = 0; i < PER; i++) {
        const th = (i / PER) * Math.PI * 2
        const rho = 0.012 + 0.05 * ((k * 7 + i) % 5) / 5
        const x = rho * Math.cos(th), y = rho * Math.sin(th)
        pts.push(x, y, s)
        const side = Math.max(0, Math.min(1, 0.5 + x / 0.1))
        si.push(0, 1, 2, 0); sw.push(0.5, 0.5 * (1 - side), 0.5 * side, 0)
      }
    }
    const geo = new THREE.BufferGeometry()
    geo.setAttribute('position', new THREE.Float32BufferAttribute(pts, 3))
    geo.setAttribute('skinIndex', new THREE.Uint16BufferAttribute(si, 4))
    geo.setAttribute('skinWeight', new THREE.Float32BufferAttribute(sw, 4))
    const idx = []
    for (let k = 0; k < RINGS - 1; k++) for (let i = 0; i < PER; i++) {
      const a = k * PER + i, b = k * PER + ((i + 1) % PER), c = a + PER, d = b + PER
      idx.push(a, b, c, b, d, c)
    }
    geo.setIndex(idx)
    geo.computeVertexNormals()
    const rootBone = new THREE.Bone(), left = new THREE.Bone(), right = new THREE.Bone()
    left.position.set(-0.08, 0, 0); right.position.set(0.08, 0, 0)
    rootBone.add(left, right)
    const mesh = new THREE.SkinnedMesh(geo, new THREE.MeshBasicMaterial())
    const group = new THREE.Group()
    group.add(rootBone, mesh)
    group.updateMatrixWorld(true)
    mesh.bind(new THREE.Skeleton([rootBone, left, right]))
    rootBone.position.set(x0, 0, 0)
    group.updateMatrixWorld(true)
    return { group, rootBone, left, right, mesh, binding: null, last: -1, lag: 0, recomputes: 0 }
  }
  const channelOf = (rc) => {
    const m = rc.rootBone.matrixWorld
    const o = new THREE.Vector3(0, 0, 0).applyMatrix4(m), u = new THREE.Vector3(0, 0, 1).transformDirection(m)
    return { id: 'c', o: [o.x, o.y, o.z], u: [u.x, u.y, u.z], depth: 0.13, r: 0.035, coneDeg: 30, funnel: 0.05,
      accepts: [], minLength: 0, compressMin: 0.8, kinds: null, suppress: new Set() }
  }
  const segmentsOf = (rc) => {
    const m = rc.rootBone.matrixWorld
    const at = (z) => { const v = new THREE.Vector3(0, 0, z).applyMatrix4(m); return [v.x, v.y, v.z] }
    return [{ a: at(-0.1), b: at(-0.02), r: 0.025 }, { a: at(-0.02), b: at(0.05), r: 0.025 }, { a: at(0.05), b: at(0.1), r: 0.025 }]
  }
  const pose = (rc, f, walk) => {
    if (walk) {
      const t = f / 60
      rc.rootBone.position.z = 1.4 * t
      rc.rootBone.rotation.y = (5 * Math.PI / 180) * Math.sin(2 * Math.PI * t)
      rc.left.rotation.x = (25 * Math.PI / 180) * Math.sin(2 * Math.PI * t)
      rc.right.rotation.x = -(25 * Math.PI / 180) * Math.sin(2 * Math.PI * t)
    }
    rc.group.updateMatrixWorld(true)
  }

  const run = (receivers, walk, gated) => {
    const rcs = Array.from({ length: receivers }, (_, k) => makeReceiver(k * 1.0))
    const times = []
    let turn = 0, recomputes = 0, maxLag = 0
    for (let f = 0; f < frames; f++) {
      for (const rc of rcs) pose(rc, f, walk)
      const t0 = performance.now()
      const budget = { left: gated ? 1 : Infinity }
      const start = turn++ % rcs.length
      for (let k = 0; k < rcs.length; k++) {
        const rc = rcs[(start + k) % rcs.length]
        const ch = channelOf(rc), segs = segmentsOf(rc)
        if (!rc.binding) {
          if (!(budget.left > 0)) continue
          budget.left--
          rc.binding = O.bindChannelOpening(THREE, rc.group, ch)
        }
        const changed = gated ? rc.binding.changed(ch, segs) : true
        if (!changed) { rc.lag = 0; continue }
        if (!(budget.left > 0)) { rc.lag++; if (f >= 6) maxLag = Math.max(maxLag, rc.lag); continue }
        budget.left--
        rc.binding.apply(ch, segs)
        rc.lag = 0
        rc.recomputes++
        recomputes++
      }
      times.push(performance.now() - t0)
    }
    for (const rc of rcs) rc.binding?.dispose()
    const steady = times.slice(10).sort((a, b) => a - b)
    const mean = steady.reduce((a, b) => a + b, 0) / steady.length
    return { mean, p95: steady[Math.floor(steady.length * 0.95)], recomputes, perFrame: recomputes / frames, maxLag,
      per: rcs.map(rc => rc.recomputes), candidates: makeReceiver(0) && null }
  }

  const row = (label, r) => console.log(`${label.padEnd(34)} ${r.mean.toFixed(3)} ms mean · ${r.p95.toFixed(3)} ms p95 · `
    + `${r.perFrame.toFixed(2)} recomputes/frame · max lag ${r.maxLag} frames (from frame 6)`)
  const results = {}
  for (const receivers of [1, 3]) for (const walk of [false, true]) for (const gated of [true, false]) {
    const label = `${receivers} receiver${receivers > 1 ? 's' : ''} · ${walk ? 'walk' : 'held'} · ${gated ? 'skip+budget' : 'every frame'}`
    results[label] = run(receivers, walk, gated)
    row(label, results[label])
  }
  check('held, skip+budget: one recompute per receiver over the run',
    results['1 receiver · held · skip+budget'].recomputes === 1
    && results['3 receivers · held · skip+budget'].per.every(n => n === 1))
  check('walk, skip+budget: one recompute per frame after the bind frame (the budget)', results['1 receiver · walk · skip+budget'].recomputes === frames - 1
    && results['3 receivers · walk · skip+budget'].recomputes <= frames)
  check('walk, 3 receivers: no receiver waits more than 2 frames', results['3 receivers · walk · skip+budget'].maxLag <= 2,
    String(results['3 receivers · walk · skip+budget'].maxLag))
  if (failures.length) { console.error(`\nFAILED: ${failures.join(', ')}`); process.exit(1) }
  console.log('\nALL OK')
}
main()
