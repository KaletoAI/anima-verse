#!/usr/bin/env node
/**
 * Exporter of the hair-chain vectors for the native port: shared/test-vectors/collision_core.json and
 * shared/test-vectors/hair_chains.json. Every expectation is the OUTPUT OF THE TYPESCRIPT IMPLEMENTATION
 * (packages/scene-render/src/collision.ts, garmentCollision.ts, secondaryMotion.ts, bundled by esbuild exactly as the
 * browser has them), never of the C# one — the C# tests (native/tests/HairVectorTests.cs) replay the files.
 * Unlike the hand-derived vector files these are generated: the hand derivations stay in the source smokes named
 * per case, and this script asserts the hand numbers of those smokes on the TypeScript before it writes anything
 * (a drift of the TypeScript away from its derivation stops the export).
 *
 * Usage:
 *   node scripts/export_hair_vectors.mjs           write both files
 *   node scripts/export_hair_vectors.mjs --check   regenerate in memory, replay the files on disk through the
 *                                                  TypeScript (shared/test-vectors/vectors.mjs runVectors) and
 *                                                  fail when a file differs from what the TypeScript gives now
 * No server, no world, no DOM. Needs the root node_modules (three, esbuild).
 *
 * The one non-exported production function, secondaryMotion.ts contactAngle, is exposed by appending
 * "export { contactAngle as __contactAngle }" to that file's text inside the bundle — the function itself is
 * byte for byte the production one. keepHairTipOutside is a closure of createSecondaryMotion: its point
 * arithmetic is reproduced in the adapter contactAngleTurn below (production pushOutOfCapsules + contactAngle +
 * three's applyAxisAngle); the closure itself runs in the end-to-end hairChain cases.
 *
 * ADAPTERS (mirrored by native/tests/HairVectorTests.cs). Points [x,y,z]; matrices column-major 16 numbers.
 *   jointNowFrom(meshWorld, bindMatrixInverse, boneWorld, boneInverse, bindMatrix) → {position, bindToWorld}
 *   capsuleNow(capsule{r,a_pos?,b_pos?}, a{position,bindToWorld}, b) → {a, b, r}
 *   linearScale(m) → number
 *   tipBindFactors(tip, [{a,b,r}]) → [factor]
 *   hairChainCapsules([{id,a,region?}]) → [id] (the bound list's capsules)
 *   pushOutOfCapsules(p, [{a,b,r,bind?:{a,b}}], weight, bindP|null, squeeze) → point
 *   contactAngleTurn(head, tip, capsules, limit) → {angle, axis, depth0} | null — keepHairTipOutside on points
 *   bindCollision(rig) → {capsules:[{id, now, bind}], missing} | null. rig = {root: matrix, bones: [{name, parent
 *     (index|null = root), matrix (local)}], mesh: matrix (local, under root), payload, pose: {root?: matrix,
 *     bones?: [[index, matrix]]}}: one skinned mesh over every bone (one vertex), bound at load (three: bindMatrix =
 *     mesh world, boneInverse = inverse bone world), then the pose, then binding.update().
 *   hairChain(rig) → {frames: [{frame, matrices: [bone world matrices]}], tips: [{bone, capsules, tip, tipLocal}]}.
 *     rig = {bones, positions, indices, weights (one skin over every bone in order, the mesh on an identity root),
 *     payload, collision|null, frames: [{dt, pose: [[index, qx, qy, qz, qw]]}], record: [frame numbers]}:
 *     createSecondaryMotion(THREE, root, payload), setCollision(collision) when given; per frame the pose's bones
 *     get their quaternion (position/scale stay the bind ones), then update(dt); the recorded frames' bone world
 *     matrices; contactTips() after the last frame.
 *
 * CASES and their hand derivations:
 *   [g…]   scripts/smoke_garment_collision.mjs [1]–[6b] (the push, its weight, COLLIDE_MAX, the bind rule)
 *   [sq…]  scripts/smoke_collision_squeeze.mjs [1]–[4] (fixture D3: T x 0 r 0.1, A x 0.13 r 0.05)
 *   [r…]   the random sample of smoke_collision_squeeze.mjs [5] (LCG seed 4242, same generator), 40 points
 *   [e…]   scripts/smoke_collision_endpoints.mjs (the endpoint rule: jointNowFrom / capsuleNow / bindCollision)
 *   [h1]   scripts/smoke_hair_chain_contact.mjs [1] (hairChainCapsules), its FIXTURE (tip bind factor 1 at
 *          |J1 − H| = 0.07 > r 0.05) and its pitch geometry for contactAngleTurn
 *   [hc…]  smoke_hair_chain_contact.mjs [2]/[3] end to end
 *   [ts…]  scripts/smoke_hair_today_skin.mjs [1]–[3] end to end
 *   [x…]   the [hc] rig with a second, bind-capped capsule set (a_pos/b_pos fixed to Head, a shoulder_hair sphere
 *          the tip sits 0.03 from at bind → factor 0.6) — exercises the squeeze push and the bind rule end to end;
 *          no hand derivation beyond the factor.
 */
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { join } from 'node:path'
import assert from 'node:assert/strict'
import { build } from 'esbuild'
import * as THREE from 'three'
import { parseVectors, runVectors } from '../shared/test-vectors/vectors.mjs'

const root = fileURLToPath(new URL('../', import.meta.url))
const SRC = root + 'packages/scene-render/src/'

async function modules() {
  const dir = await mkdtemp(join(root, 'scripts/.export-hair-vectors-'))
  try {
    const expose = { name: 'expose-contact-angle', setup(b) {
      b.onLoad({ filter: /secondaryMotion\.ts$/ }, async args => ({
        contents: (await readFile(args.path, 'utf8')) + '\nexport { contactAngle as __contactAngle }\n', loader: 'ts' }))
    } }
    const result = await build({ stdin: { contents: [
      "export * as C from '" + SRC + "collision.ts'",
      "export * as G from '" + SRC + "garmentCollision.ts'",
      "export * as S from '" + SRC + "secondaryMotion.ts'"].join('\n'), resolveDir: root, loader: 'ts' },
      bundle: true, platform: 'node', format: 'esm', write: false, external: ['three', 'three/*'], logLevel: 'error',
      plugins: [expose] })
    const file = join(dir, 'hair.mjs')
    await writeFile(file, result.outputFiles[0].text)
    return await import('file://' + file)
  } finally { await rm(dir, { recursive: true, force: true }) }
}
const { C, G, S } = await modules()

const mat = m => new THREE.Matrix4().fromArray(m)
const arr = m => Array.from(m.elements)
const T = (x, y, z) => arr(new THREE.Matrix4().makeTranslation(x, y, z))
const TRS = (t, q, s) => arr(new THREE.Matrix4().compose(new THREE.Vector3(...t), new THREE.Quaternion(...q), new THREE.Vector3(...s)))
const qAxis = (axis, deg) => new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(...axis).normalize(), deg * Math.PI / 180).toArray()

// ---- the dispatch (TypeScript side) ----------------------------------------------------------------------------

function contactAngleTurn(head, tip, capsules, limit) {
  if (!(limit > 0)) return null
  const SQ = { squeeze: true }
  const pushed = G.pushOutOfCapsules(tip, capsules, 1, undefined, SQ)
  const depth0 = Math.hypot(pushed[0] - tip[0], pushed[1] - tip[1], pushed[2] - tip[2])
  if (depth0 < 1e-6) return null
  const h = new THREE.Vector3(...head), lever = new THREE.Vector3(...tip).sub(h)
  const axis = new THREE.Vector3(...pushed).sub(new THREE.Vector3(...tip))
  axis.crossVectors(lever, axis)
  if (axis.lengthSq() < 1e-20 || lever.lengthSq() < 1e-12) return null
  axis.normalize()
  const t = new THREE.Vector3()
  const angle = S.__contactAngle(turn => {
    t.copy(lever).applyAxisAngle(axis, turn).add(h)
    const p = G.pushOutOfCapsules([t.x, t.y, t.z], capsules, 1, undefined, SQ)
    return Math.hypot(p[0] - t.x, p[1] - t.y, p[2] - t.z)
  }, depth0, limit)
  return angle === null ? null : { angle, axis: axis.toArray(), depth0 }
}

function makeRig(data) {
  const group = new THREE.Group()
  if (data.root) mat(data.root).decompose(group.position, group.quaternion, group.scale)
  const bones = data.bones.map(b => {
    const bone = new THREE.Bone(); bone.name = b.name
    mat(b.matrix).decompose(bone.position, bone.quaternion, bone.scale)
    return bone
  })
  data.bones.forEach((b, i) => (b.parent === null ? group : bones[b.parent]).add(bones[i]))
  return { group, bones }
}

function bindCollisionValue(data) {
  const { group, bones } = makeRig(data)
  const geo = new THREE.BufferGeometry()
  geo.setAttribute('position', new THREE.Float32BufferAttribute([0, 0, 0], 3))
  geo.setAttribute('skinIndex', new THREE.Uint16BufferAttribute([0, 0, 0, 0], 4))
  geo.setAttribute('skinWeight', new THREE.Float32BufferAttribute([1, 0, 0, 0], 4))
  const mesh = new THREE.SkinnedMesh(geo, new THREE.MeshBasicMaterial())
  if (data.mesh) mat(data.mesh).decompose(mesh.position, mesh.quaternion, mesh.scale)
  group.add(mesh); group.updateMatrixWorld(true)
  mesh.bind(new THREE.Skeleton(bones))
  if (data.pose?.root) mat(data.pose.root).decompose(group.position, group.quaternion, group.scale)
  for (const [i, m] of data.pose?.bones ?? []) mat(m).decompose(bones[i].position, bones[i].quaternion, bones[i].scale)
  group.updateMatrixWorld(true)
  const binding = C.bindCollision(THREE, group, data.payload)
  try {
    if (!binding) return null
    binding.update()
    return { capsules: binding.capsules.map(e => ({ id: e.capsule.id, now: e.now, bind: e.bind })), missing: binding.missing }
  } finally { geo.dispose(); mesh.material.dispose() }
}

function hairChainValue(data) {
  const { group, bones } = makeRig(data)
  const geo = new THREE.BufferGeometry()
  geo.setAttribute('position', new THREE.Float32BufferAttribute(data.positions, 3))
  geo.setAttribute('skinIndex', new THREE.Uint16BufferAttribute(data.indices, 4))
  geo.setAttribute('skinWeight', new THREE.Float32BufferAttribute(data.weights, 4))
  const mesh = new THREE.SkinnedMesh(geo, new THREE.MeshBasicMaterial())
  group.add(mesh); group.updateMatrixWorld(true)
  mesh.bind(new THREE.Skeleton(bones))
  const motion = S.createSecondaryMotion(THREE, group, data.payload)
  try {
    if (data.collision) motion.setCollision(data.collision)
    const record = new Set(data.record)
    const frames = []
    data.frames.forEach((f, k) => {
      for (const [i, ...q] of f.pose ?? []) bones[i].quaternion.fromArray(q)
      group.updateMatrixWorld(true)
      motion.update(f.dt)
      if (record.has(k + 1)) frames.push({ frame: k + 1, matrices: bones.map(b => arr(b.matrixWorld)) })
    })
    const tips = motion.contactTips().map(t => ({ bone: t.bone, capsules: t.capsules, tip: t.tip, tipLocal: t.tipLocal }))
    return { frames, tips }
  } finally { motion.dispose(); geo.dispose(); mesh.material.dispose() }
}

export const dispatch = {
  jointNowFrom: (a, b, c, d, e) => { const j = C.jointNowFrom(a, b, c, d, e); return { position: j.position, bindToWorld: Array.from(j.bindToWorld) } },
  capsuleNow: (c, a, b) => C.capsuleNow(c, a, b),
  linearScale: m => C.linearScale(m),
  tipBindFactors: (tip, caps) => S.tipBindFactors(tip, caps),
  hairChainCapsules: list => S.hairChainCapsules(list.map(capsule => ({ capsule }))).map(e => e.capsule.id),
  pushOutOfCapsules: (p, caps, weight, bindP, squeeze) => G.pushOutOfCapsules(p, caps, weight, bindP ?? undefined, squeeze ? { squeeze: true } : undefined),
  contactAngleTurn,
  bindCollision: bindCollisionValue,
  hairChain: hairChainValue,
}

// ---- the cases --------------------------------------------------------------------------------------------------

const cases = { collision: [], hair: [] }
const add = (file, label, fn, args, eps) => {
  const expect = dispatch[fn](...structuredClone(args))
  cases[file].push({ label, fn, args, expect: JSON.parse(JSON.stringify(expect)), ...(eps !== undefined ? { eps } : {}) })
  return expect
}
const near = (a, b, eps) => a.length === b.length && a.every((x, i) => Math.abs(x - b[i]) <= eps)

// [g] the garment push (smoke_garment_collision.mjs [1]–[6b])
const Cap = { a: [0, 0, 0], b: [0, 1, 0], r: 0.1 }
for (const [p, want] of [[[0.05, 0.5, 0], [0.1, 0.5, 0]], [[0.2, 0.5, 0], [0.2, 0.5, 0]], [[0.1, 0.5, 0], [0.1, 0.5, 0]],
  [[0, 0.5, 0], [0, 0.5, 0]], [[0, -0.05, 0.03], [0, -0.0857493, 0.0514496]], [[0, 1.06, 0.08], [0, 1.06, 0.08]]]) {
  const got = add('collision', '[g1] capsule C, p (' + p.join(', ') + ')', 'pushOutOfCapsules', [p, [Cap], 1, null, false])
  assert.ok(near(got, want, 1e-6), 'g1 ' + p + ' → ' + got)
}
assert.ok(near(add('collision', '[g2] a sphere doubles d', 'pushOutOfCapsules',
  [[0.03, 0.04, 0], [{ a: [0, 0, 0], b: [0, 0, 0], r: 0.1 }], 1, null, false]), [0.06, 0.08, 0], 1e-12))
for (const [w, want] of [[0.5, 0.075], [0, 0.05], [2, 0.1]])
  assert.ok(near(add('collision', '[g3] weight ' + w, 'pushOutOfCapsules', [[0.05, 0.5, 0], [Cap], w, null, false]), [want, 0.5, 0], 1e-12))
assert.ok(near(add('collision', '[g4] two passes: the later capsule wins', 'pushOutOfCapsules',
  [[0.06, 0.5, 0], [Cap, { a: [0.15, 0, 0], b: [0.15, 1, 0], r: 0.1 }], 1, null, false]), [0.05, 0.5, 0], 1e-12))
const far16 = Array.from({ length: 16 }, (_, i) => ({ a: [5 + i, 0, 0], b: [5 + i, 1, 0], r: 0.1 }))
assert.ok(near(add('collision', '[g5] COLLIDE_MAX: the 17th capsule is not applied', 'pushOutOfCapsules',
  [[0.05, 0.5, 0], [...far16, Cap], 1, null, false]), [0.05, 0.5, 0], 0))
assert.ok(near(add('collision', '[g5] COLLIDE_MAX: the same capsule first is', 'pushOutOfCapsules',
  [[0.05, 0.5, 0], [Cap, ...far16], 1, null, false]), [0.1, 0.5, 0], 1e-12))
const Cb = { ...Cap, bind: { a: [0, 0, 0], b: [0, 1, 0] } }
for (const [label, p, q, cap, want] of [
  ['bind distance 0.06 caps the radius', [0.03, 0.5, 0], [0.06, 0.5, 0], Cb, [0.06, 0.5, 0]],
  ['outside the capped radius', [0.08, 0.5, 0], [0.06, 0.5, 0], Cb, [0.08, 0.5, 0]],
  ['the bind pose itself stays', [0.05, 0.5, 0], [0.05, 0.5, 0], Cb, [0.05, 0.5, 0]],
  ['a far bind point caps nothing', [0.05, 0.5, 0], [0.3, 0.5, 0], Cb, [0.1, 0.5, 0]],
  ['the bind capsule is its own frame', [0.05, 0.5, 0], [1.02, 0.5, 0], { ...Cap, bind: { a: [1, 0, 0], b: [1, 1, 0] } }, [0.05, 0.5, 0]],
  ['no bind point: the plain push', [0.05, 0.5, 0], null, Cb, [0.1, 0.5, 0]]])
  assert.ok(near(add('collision', '[g6b] bind rule: ' + label, 'pushOutOfCapsules', [p, [cap], 1, q, false]), want, 1e-9), label)

// [sq] the squeeze rule (smoke_collision_squeeze.mjs, fixture D3)
const D3 = [{ a: [0, 0, 0], b: [0, 1, 0], r: 0.10 }, { a: [0.13, 0, 0], b: [0.13, 1, 0], r: 0.05 }]
for (const [label, p, sq, want, eps] of [
  ['[sq1] inside both: squeeze', [0.09, 0.5, 0.02], true, [0.092281, 0.5, 0.038526], 1e-5],
  ['[sq1] inside both: ordinary passes', [0.09, 0.5, 0.02], false, [0.092223, 0.5, 0.032756], 1e-5],
  ['[sq2] the arm case: squeeze', [0.105, 0.5, 0.02], true, [0.111572, 0.5, 0.046480], 1e-5],
  ['[sq2] the arm case: ordinary passes', [0.105, 0.5, 0.02], false, [0.093149, 0.5, 0.033791], 1e-5],
  ['[sq3] opposite normals: ordinary passes', [0.09, 0.5, 0], true, [0.08, 0.5, 0], 1e-9],
  ['[sq4] inside T only', [0, 0.5, 0.05], true, [0, 0.5, 0.1], 1e-6],
  ['[sq4] inside A only', [0.15, 0.5, 0.01], true, [0.174721, 0.5, 0.022361], 1e-6],
  ['[sq4] in no capsule', [0.3, 0.5, 0], true, [0.3, 0.5, 0], 0]])
  assert.ok(near(add('collision', label, 'pushOutOfCapsules', [p, D3, 1, null, sq]), want, eps), label)
assert.ok(near(add('collision', '[sq4] weight 0.5 blends the squeezed point', 'pushOutOfCapsules',
  [[0.15, 0.5, 0.01], D3, 0.5, null, true]), [0.162361, 0.5, 0.016180], 1e-6))

// [r] the random sample of smoke_collision_squeeze.mjs [5] (same LCG and draw order), squeeze and ordinary
{
  let seed = 4242
  const rnd = () => { seed = (seed * 1103515245 + 12345) % 2147483648; return seed / 2147483648 }
  const jitter = (v, s) => v.map(x => x + (rnd() - 0.5) * s)
  for (let n = 0; n < 40; n++) {
    const count = Math.floor(rnd() * 21)
    const set = Array.from({ length: count }, () => {
      const a = [rnd() - 0.5, rnd() * 2, rnd() - 0.5]
      const b = rnd() < 0.15 ? [...a] : [a[0] + (rnd() - 0.5) * 0.6, a[1] + (rnd() - 0.5) * 0.6, a[2] + (rnd() - 0.5) * 0.6]
      const c = { a, b, r: 0.02 + rnd() * 0.2 }
      if (rnd() < 0.5) c.bind = { a: jitter(a, 0.1), b: jitter(b, 0.1) }
      return c
    })
    const kind = count ? Math.floor(rnd() * 3) : 0
    const i0 = Math.floor(rnd() * count), c0 = set[i0]
    const u = rnd(), axisPoint = c0 ? c0.a.map((v, i) => v + (c0.b[i] - v) * u) : null
    let p
    if (kind === 0) p = [rnd() - 0.5, rnd() * 2, rnd() - 0.5]
    else if (kind === 1 || count < 2) p = jitter(axisPoint, 0.2)
    else {
      const dir = jitter([0, 0, 0], 2), len = Math.hypot(...dir) || 1
      const off = dir.map(v => (v / len) * c0.r * (0.5 + rnd() * 0.8))
      set[(i0 + 1 + Math.floor(rnd() * (count - 1))) % count] = { a: c0.a.map((v, i) => v + off[i]),
        b: c0.b.map((v, i) => v + off[i]), r: 0.02 + rnd() * 0.2 }
      const f = 0.3 + rnd() * 0.4
      p = jitter(axisPoint.map((v, i) => v + off[i] * f), 0.02)
    }
    const bindP = rnd() < 0.5 ? jitter(p, 0.15) : [p[0] + 2, p[1], p[2]]
    const tag = String(n).padStart(2, '0')
    add('collision', '[r' + tag + '] random set of ' + count + ', squeeze', 'pushOutOfCapsules', [p, set, 1, bindP, true])
    add('collision', '[r' + tag + '] random set of ' + count + ', ordinary', 'pushOutOfCapsules', [p, set, 1, bindP, false])
  }
}

// [e] the endpoint rule
const rotX = deg => qAxis([1, 0, 0], deg)
{
  const meshWorld = TRS([0.5, 0, -1], qAxis([0, 1, 0], 30), [2, 2, 2])
  const bindMatrix = TRS([0.2, 0.1, 0], qAxis([0, 0, 1], 10), [1, 1, 1])
  const boneWorld = TRS([0, 1.2, 0.1], qAxis([1, 1, 0], 25), [1, 1, 1])
  const boneInverse = arr(mat(TRS([0, 1, 0], rotX(5), [1, 1, 1])).invert())
  const bindInv = arr(mat(bindMatrix).invert())
  const j = add('collision', '[e1] jointNowFrom, detached bind mode', 'jointNowFrom', [meshWorld, bindInv, boneWorld, boneInverse, bindMatrix])
  add('collision', '[e1] jointNowFrom, attached (mesh world · bindMatrixInverse = I)', 'jointNowFrom',
    [bindMatrix, bindInv, boneWorld, boneInverse, bindMatrix])
  const J = { position: j.position, bindToWorld: Array.from(j.bindToWorld) }
  const J2 = { position: [0.3, 1.9, 0.2], bindToWorld: TRS([0.1, 0.2, 0], rotX(-20), [1, 1, 1]) }
  add('collision', '[e2] capsuleNow: joints only, radius × joint a scale', 'capsuleNow', [{ r: 0.07 }, J, J2])
  add('collision', '[e2] capsuleNow: bind positions on both ends', 'capsuleNow', [{ r: 0.07, a_pos: [0, 1.6, 0.05], b_pos: [0.1, 1.7, 0] }, J, J2])
  add('collision', '[e2] capsuleNow: a bind position on b only', 'capsuleNow', [{ r: 0.05, b_pos: [0.1, 1.7, 0] }, J2, J])
  assert.ok(Math.abs(add('collision', '[e3] linearScale of a uniform ×2', 'linearScale', [meshWorld]) - 2) < 1e-12)
  add('collision', '[e3] linearScale of a non-uniform scale', 'linearScale', [TRS([1, 2, 3], qAxis([1, 2, 3], 40), [1, 2, 4])])
  const bones = [{ name: 'mixamorig:Hips', parent: null, matrix: T(0, 1, 0) }, { name: 'mixamorig:Spine', parent: 0, matrix: T(0, 0.3, 0) },
    { name: 'mixamorig:Head', parent: 1, matrix: T(0, 0.5, 0.02) }, { name: 'mixamorig:LeftArm', parent: 1, matrix: T(0.2, 0.2, 0) }]
  const payload = { version: C.COLLISION_VERSION, capsules: [
    { id: 'torso', a: 'mixamorig:Hips', b: 'mixamorig:Spine', r: 0.12, region: 'torso' },
    { id: 'head', a: 'mixamorig:Head', b: 'mixamorig:Head', r: 0.09, region: 'head', a_pos: [0, 1.85, 0.03], b_pos: [0, 1.95, 0.03] },
    { id: 'left_upper_arm', a: 'mixamorig:LeftArm', b: 'mixamorig:LeftArm', r: 0.05, region: 'arm', b_pos: [0.45, 1.5, 0] },
    { id: 'ghost', a: 'mixamorig:Hips', b: 'mixamorig:Missing', r: 0.1, region: 'torso' },
    { id: 'flat', a: 'mixamorig:Hips', b: 'mixamorig:Spine', r: 0, region: 'torso' }] }
  const pose = { bones: [[1, TRS([0, 0.3, 0], rotX(30), [1, 1, 1])], [2, TRS([0, 0.5, 0.02], qAxis([0, 1, 0], -40), [1, 1, 1])]] }
  const plain = add('collision', '[e4] bindCollision: a posed figure', 'bindCollision', [{ bones, payload, pose }])
  assert.deepEqual(plain.missing, ['ghost', 'flat'])
  add('collision', '[e4] bindCollision: a figure placed and scaled before binding, moved after', 'bindCollision',
    [{ root: TRS([3, 0, -2], qAxis([0, 1, 0], 90), [0.5, 0.5, 0.5]), bones, payload,
      pose: { ...pose, root: TRS([4, 0.5, -2], qAxis([0, 1, 0], 60), [0.5, 0.5, 0.5]) } }])
  add('collision', '[e4] bindCollision: a mesh offset under the root (detached geometry space)', 'bindCollision',
    [{ bones, payload, mesh: T(0, 0, 0.25), pose }])
  assert.equal(add('collision', '[e5] bindCollision: another version → null', 'bindCollision', [{ bones, payload: { ...payload, version: 8 }, pose }]), null)
  assert.equal(add('collision', '[e5] bindCollision: no capsules → null', 'bindCollision', [{ bones, payload: { version: C.COLLISION_VERSION, capsules: [] }, pose }]), null)
}

// [h1] hair capsule selection and the tip's bind rule
{
  const bound = [{ id: 'head', a: 'mixamorig:Head', region: 'head' }, { id: 'chest', a: 'mixamorig:Spine2', region: 'torso' },
    { id: 'left_upper_arm', a: 'mixamorig:LeftArm', region: 'arm' }, { id: 'left_shoulder_hair', a: 'mixamorig:LeftShoulder', region: 'shoulder_hair' },
    { id: 'pack:Breast_L', a: 'Breast_L', region: 'chest' }, { id: 'pack:Breast_L:chest_hair', a: 'Breast_L', region: 'chest_hair' },
    { id: 'outer_spine', a: 'mixamorig:Spine1', region: 'outer_trunk' }, { id: 'no_region', a: 'mixamorig:Hips' }]
  assert.deepEqual(add('collision', '[h1] hairChainCapsules: HAIR_REGIONS in payload order, ancestors kept, outer_trunk never',
    'hairChainCapsules', [bound]), ['head', 'chest', 'left_upper_arm', 'left_shoulder_hair', 'pack:Breast_L:chest_hair'])
  const sphere = { a: [0, 1.6, 0], b: [0, 1.6, 0], r: 0.05 }
  assert.deepEqual(add('collision', '[h1] tipBindFactors: J1 0.07 from the head sphere → 1', 'tipBindFactors', [[0, 1.6, -0.07], [sphere]]), [1])
  const f = add('collision', '[h1] tipBindFactors: capped, segment, zero radius', 'tipBindFactors',
    [[0, 1.6, -0.07], [{ a: [0, 1.6, -0.1], b: [0, 1.6, -0.1], r: 0.05 }, { a: [0, 1.5, 0], b: [0, 1.8, 0], r: 0.1 }, { a: [0, 0, 0], b: [0, 1, 0], r: 0 }]])
  assert.ok(near(f, [0.6, 0.7, 1], 1e-12), String(f))
  // the pitch geometry of the FIXTURE: link _00 (joint J0 (0,1.7,−0.07), lever 0.1 down) turned by β toward the head
  const J0 = [0, 1.7, -0.07]
  const tipAt = deg => [0, 1.7 - 0.1 * Math.cos(deg * Math.PI / 180), -0.07 + 0.1 * Math.sin(deg * Math.PI / 180)]
  const lim = 28 * Math.PI / 180
  const t20 = add('collision', '[h1] contactAngleTurn: β 20° inside the head sphere turns back to the surface', 'contactAngleTurn', [J0, tipAt(20), [sphere], lim])
  // the surface is crossed at β ≈ 11.5° (smoke_hair_chain_contact.mjs FIXTURE): the turn is ≈ 8.5°
  assert.ok(Math.abs(t20.angle * 180 / Math.PI - (20 - 11.5)) < 0.3, String(t20.angle * 180 / Math.PI))
  add('collision', '[h1] contactAngleTurn: a 2° budget cannot get out (the shallowest angle)', 'contactAngleTurn', [J0, tipAt(20), [sphere], 2 * Math.PI / 180])
  assert.equal(add('collision', '[h1] contactAngleTurn: a tip outside → null', 'contactAngleTurn', [J0, tipAt(5), [sphere], lim]), null)
  assert.equal(add('collision', '[h1] contactAngleTurn: no budget → null', 'contactAngleTurn', [J0, tipAt(20), [sphere], 0]), null)
  add('collision', '[h1] contactAngleTurn: between two capsules (squeeze)', 'contactAngleTurn',
    [J0, tipAt(20), [sphere, { a: [0, 1.55, -0.14], b: [0, 1.7, -0.14], r: 0.06 }], lim])
  add('collision', '[h1] contactAngleTurn: a pushed point along the lever turns nothing', 'contactAngleTurn',
    [[0, 1.6, 0.2], [0, 1.6, 0.04], [sphere], lim])
}

// [hc] / [ts] / [x] end to end (smoke_hair_chain_contact.mjs, smoke_hair_today_skin.mjs)
const hairGroup = { freq_hz: 1, zeta: 0.5, gravity: 0, gravity_scale: 1, gain: 1, max_deg: 35, sag_max_deg: 10, spill_max_deg: 0,
  head_sag: 1, axis_gain: [1, 1, 1], flatten: 0, stretch: 0, spread: 0.5, flatten_floor: 1, spill: 0, translate: 0, squash: [1, 1],
  length: 1, girth: 1, rest_deg: 0, rest_max_deg: 90, rigid_tail: 0, scale_axis: 'centroid', straighten_deg: 0, freetext_clothing_gain: 1 }
const still = { max_deg: 0, sag_max_deg: 0, gravity: 0, gain: 0 }
const dt = 1 / 60
const pitch = (bone, deg, frames = 90) => Array.from({ length: frames }, (_, k) =>
  ({ dt, pose: [[bone, ...qAxis([1, 0, 0], -Math.min(1, (k + 1) * dt / 0.25) * deg)]] }))
const every = n => Array.from({ length: 90 / n }, (_, k) => (k + 1) * n).concat([1, 3, 8, 12, 15, 20])
const contactRig = {
  bones: [{ name: 'mixamorig:Hips', parent: null, matrix: T(0, 0, 0) }, { name: 'mixamorig:Head', parent: 0, matrix: T(0, 1.6, 0) },
    { name: 'HairGen_c00_00', parent: 1, matrix: T(0, 0.1, -0.07) }, { name: 'HairGen_c00_01', parent: 2, matrix: T(0, -0.1, 0) }],
  positions: [0, 1.65, -0.07, 0, 1.55, -0.07], indices: [2, 0, 0, 0, 3, 0, 0, 0], weights: [1, 0, 0, 0, 1, 0, 0, 0],
}
const headSphere = { version: C.COLLISION_VERSION, capsules: [{ id: 'head', a: 'mixamorig:Head', b: 'mixamorig:Head', r: 0.05, region: 'head' }] }
const chainGroup = (extra = {}) => ({ ...hairGroup, bones: ['HairGen_c00_00', 'HairGen_c00_01'], ...extra })
const depthOf = r => Math.max(...r.frames.map(f => 0.05 - Math.hypot(f.matrices[3][12], f.matrices[3][13] - 1.6, f.matrices[3][14])))
const allFrames = Array.from({ length: 90 }, (_, k) => k + 1)
/** The end-to-end chains: measured equal to 1e-9 m; 1e-8 leaves room for another libm (sin/cos/acos). */
const HC = 1e-8
{
  const control = hairChainValue({ ...contactRig, payload: { rev: 'f', groups: { hair_c00: chainGroup({ hair: true }) } }, collision: null,
    frames: pitch(1, 40), record: allFrames })
  assert.ok(depthOf(control) > 0.005, 'hc control depth ' + depthOf(control))
  add('hair', '[hc2] control: no collision payload, the tip sinks into the head sphere', 'hairChain',
    [{ ...contactRig, payload: { rev: 'f', groups: { hair_c00: chainGroup({ hair: true }) } }, collision: null, frames: pitch(1, 40), record: every(5) }], HC)
  const on = hairChainValue({ ...contactRig, payload: { rev: 'f', groups: { hair_c00: chainGroup({ hair: true }) } }, collision: headSphere,
    frames: pitch(1, 40), record: allFrames })
  assert.ok(depthOf(on) <= 0.001, 'hc on depth ' + depthOf(on))
  assert.equal(on.tips.length, 2)
  add('hair', '[hc2] hair: the head capsule keeps the tip outside (≤ 1 mm in every frame)', 'hairChain',
    [{ ...contactRig, payload: { rev: 'f', groups: { hair_c00: chainGroup({ hair: true }) } }, collision: headSphere, frames: pitch(1, 40), record: every(5) }], HC)
  const plain = add('hair', '[hc2] without hair: Head is an ancestor, no contact', 'hairChain',
    [{ ...contactRig, payload: { rev: 'f', groups: { hair_c00: chainGroup() } }, collision: headSphere, frames: pitch(1, 40), record: every(5) }], HC)
  assert.equal(plain.tips.length, 0)
  add('hair', '[hc3] a chain the model lacks next to c00', 'hairChain',
    [{ ...contactRig, payload: { rev: 'f', groups: { hair_c00: chainGroup({ hair: true }), hair_c07: { ...hairGroup, bones: ['HairGen_c07_00'], hair: true } } },
      collision: headSphere, frames: pitch(1, 40), record: every(15) }], HC)
  add('hair', '[hc3] only the absent chain: nothing moves', 'hairChain',
    [{ ...contactRig, payload: { rev: 'f', groups: { hair_c07: { ...hairGroup, bones: ['HairGen_c07_00'], hair: true } } },
      collision: headSphere, frames: [{ dt, pose: [[1, ...qAxis([1, 0, 0], 0.5 * 180 / Math.PI)]] }], record: [1] }], HC)
  // [x] the same pitch with a squeeze pair and a bind-capped sphere fixed to Head by bind positions
  const pair = { version: C.COLLISION_VERSION, capsules: [
    { id: 'head', a: 'mixamorig:Head', b: 'mixamorig:Head', r: 0.05, region: 'head' },
    { id: 'back', a: 'mixamorig:Head', b: 'mixamorig:Head', r: 0.06, region: 'torso', a_pos: [0, 1.5, -0.15], b_pos: [0, 1.75, -0.15] },
    { id: 'nape', a: 'mixamorig:Head', b: 'mixamorig:Head', r: 0.05, region: 'shoulder_hair', a_pos: [0, 1.6, -0.1], b_pos: [0, 1.6, -0.1] },
    { id: 'skipped_cloth', a: 'mixamorig:Head', b: 'mixamorig:Head', r: 0.3, region: 'leg' }] }
  for (const [deg, label] of [[40, 'forward'], [-40, 'backward']])
    add('hair', '[x1] hair: head, a back capsule and a bind-capped nape sphere, pitch ' + label, 'hairChain',
      [{ ...contactRig, payload: { rev: 'f', groups: { hair_c00: chainGroup({ hair: true }) } }, collision: pair, frames: pitch(1, deg), record: every(5) }], HC)
}
{
  const todayRig = {
    bones: [{ name: 'mixamorig:Hips', parent: null, matrix: T(0, 0, 0) }, { name: 'mixamorig:Spine2', parent: 0, matrix: T(0, 1.3, 0) },
      { name: 'mixamorig:Head', parent: 1, matrix: T(0, 0.3, 0) }, { name: 'HairGen_c00_00', parent: 2, matrix: T(0, 0.1, -0.07) },
      { name: 'HairGen_c00_01', parent: 3, matrix: T(0, -0.1, 0) }, { name: 'HairGen_c00_02', parent: 4, matrix: T(0, -0.1, 0) }],
    positions: [0, 1.65, -0.07, 0, 1.55, -0.07, 0, 1.45, -0.07, 0, 1.6, -0.07],
    indices: [3, 0, 0, 0, 4, 0, 0, 0, 5, 0, 0, 0, 4, 0, 0, 0], weights: [1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0],
  }
  const hg = { ...hairGroup, hair: true, anchor_from: 'mixamorig:Head' }
  const posed = [{ dt, pose: [[1, ...qAxis([1, 0, 0], 30)], [2, ...qAxis([1, 0, 0], -40)]] }]
  const pos = (r, i) => r.frames[r.frames.length - 1].matrices[i].slice(12, 15)
  const r1 = add('hair', '[ts1] zero swing = today\'s skin', 'hairChain', [{ ...todayRig, payload: { rev: 'f', groups: { hair_c00: { ...hg, ...still,
    bones: ['HairGen_c00_00', 'HairGen_c00_01'], anchor_blend: { HairGen_c00_00: { 'mixamorig:Head': 1 },
      HairGen_c00_01: { 'mixamorig:Head': 0.5, 'mixamorig:Spine2': 0.5 }, HairGen_c00_02: { 'mixamorig:Spine2': 1 } } } } },
    collision: null, frames: posed, record: [1] }], HC)
  assert.ok(near(pos(r1, 3), [0, 1.64613, 0.06370], 1e-5) && near(pos(r1, 4), [0, 1.57123, 0.08522], 1e-5)
    && near(pos(r1, 5), [0, 1.50821, 0.03938], 1e-5), 'ts1 ' + [pos(r1, 3), pos(r1, 4), pos(r1, 5)])
  const r2 = add('hair', '[ts2] the swing is the head share', 'hairChain', [{ ...todayRig, payload: { rev: 'f', groups: { hair_c00: { ...hg,
    bones: ['HairGen_c00_00', 'HairGen_c00_01'], anchor_blend: { HairGen_c00_00: { 'mixamorig:Head': 1 }, HairGen_c00_01: { 'mixamorig:Spine2': 1 } } } } },
    collision: null, frames: pitch(2, 40), record: every(5) }], HC)
  assert.ok(r2.frames.every(f => near(f.matrices[4].slice(12, 15), [0, 1.6, -0.07], 1e-6)), 'ts2 _01 still')
  const r3 = add('hair', '[ts3] a rows-only group', 'hairChain', [{ ...todayRig, payload: { rev: 'f', groups: { hair_c00: { ...hg, ...still, bones: [],
    anchor_blend: { HairGen_c00_02: { 'mixamorig:Head': 0.5, 'mixamorig:Spine2': 0.5 } } } } }, collision: null, frames: posed, record: [1] }], HC)
  assert.ok(near(pos(r3, 5), [0, 1.47869, 0.06890], 1e-5), 'ts3 ' + pos(r3, 5))
  add('hair', '[ts4] today\'s skin under the head share with the head capsule (rows + contact)', 'hairChain', [{ ...todayRig,
    payload: { rev: 'f', groups: { hair_c00: { ...hg, bones: ['HairGen_c00_00', 'HairGen_c00_01'], anchor_blend: { HairGen_c00_00: { 'mixamorig:Head': 1 },
      HairGen_c00_01: { 'mixamorig:Head': 0.7, 'mixamorig:Spine2': 0.3 }, HairGen_c00_02: { 'mixamorig:Spine2': 0.6, 'mixamorig:Head': 0.4 } } } } },
    collision: { version: C.COLLISION_VERSION, capsules: [{ id: 'head', a: 'mixamorig:Head', b: 'mixamorig:Head', r: 0.05, region: 'head' }] },
    frames: pitch(2, 40), record: every(5) }], HC)
}

// ---- write / check -------------------------------------------------------------------------------------------------

const files = {
  collision_core: { format: 'anima-test-vectors/1', source: 'scripts/export_hair_vectors.mjs', fixtures: {}, cases: cases.collision },
  hair_chains: { format: 'anima-test-vectors/1', source: 'scripts/export_hair_vectors.mjs', fixtures: {}, cases: cases.hair },
}
/** JSON with one key per line, but every array of plain numbers / strings on one line (the files stay readable). */
function format(v, pad = '') {
  if (Array.isArray(v)) {
    if (v.every(x => x === null || typeof x !== 'object')) return JSON.stringify(v).replaceAll(',', ', ')
    return '[\n' + v.map(x => pad + '  ' + format(x, pad + '  ')).join(',\n') + '\n' + pad + ']'
  }
  if (v && typeof v === 'object') {
    const keys = Object.keys(v)
    if (!keys.length) return '{}'
    return '{\n' + keys.map(k => pad + '  ' + JSON.stringify(k) + ': ' + format(v[k], pad + '  ')).join(',\n') + '\n' + pad + '}'
  }
  return JSON.stringify(v)
}
let failed = 0
for (const [name, data] of Object.entries(files)) {
  const path = root + 'shared/test-vectors/' + name + '.json'
  const text = format(data) + '\n'
  parseVectors(text)
  if (process.argv.includes('--check')) {
    const disk = await readFile(path, 'utf8')
    const r = runVectors(parseVectors(disk), dispatch)
    failed += r.failed
    if (disk !== text) { console.log('DRIFT ' + name + '.json differs from what the TypeScript gives now'); failed++ }
    else console.log('same  ' + name + '.json (' + data.cases.length + ' cases)')
  } else {
    await writeFile(path, text)
    console.log('wrote shared/test-vectors/' + name + '.json (' + data.cases.length + ' cases)')
  }
}
process.exit(failed ? 1 : 0)
