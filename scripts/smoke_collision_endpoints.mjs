#!/usr/bin/env node
/**
 * Smoke check for the collision-capsule ENDPOINT RULE —
 * `packages/scene-render/src/collision.ts`, the ONE routine the admin viewer
 * (wireframes) and the garment/hair push of both renderers read capsules with
 * (`docs/schnittstellen-3d.md` "Collision capsules (`collision`)").
 *
 * Usage: direct node call, self-bundling via esbuild (run from anywhere):
 *   node scripts/smoke_collision_endpoints.mjs
 *
 * Every expected number is derived BY HAND (§ B5a). Column vectors;
 * Rz(90°): (x, y, z) → (−y, x, z); T(t) translates by t; S(s) scales.
 *
 * FIXTURE — the head capsule of Kira's current base (task-1 report):
 *   Head joint bind position J = (0, 1.5, 0.1), boneInverse = T(−J);
 *   capsule {a = b = Head, b_pos P = (0, 1.62, 0.13), r = 0.071};
 *   body mesh at the origin, bindMatrix = I.
 *
 * [1] Pure math, attached bind mode (meshWorld · bindMatrixInverse = I),
 *     pose boneWorld = T(0.2, 1.4, 0) · Rz(90°):
 *       a (no a_pos) = the joint = boneWorld · origin = (0.2, 1.4, 0)
 *       b = boneWorld · T(−J) · P: P − J = (0, 0.12, 0.03) → Rz90 →
 *           (−0.12, 0, 0.03) → + (0.2, 1.4, 0) = (0.08, 1.4, 0.03)
 *       r = 0.071 (rotation + translation keep lengths)
 *     The capsule length |b − a| = |P − J| = sqrt(0.0144 + 0.0009) = 0.123693
 *     in every pose (the point is FIXED to the joint).
 * [2] The same pose under a parent scale S(0.5) (bone world = S(0.5) · …):
 *       a = (0.1, 0.7, 0), b = (0.04, 0.7, 0.015), r = 0.0355
 * [3] Detached bind mode, meshWorld = T(1, 0, 0), bindMatrixInverse = I:
 *     the skin is drawn one metre to the right of the bones, and so are the
 *     endpoints: a = (1.2, 1.4, 0), b = (1.08, 1.4, 0.03), r = 0.071.
 * [4] The SAME numbers through three: a real SkinnedMesh + Skeleton posed as
 *     in [1] (Head under a root bone; root at T(0.2, 1.4, 0), Head local
 *     Rz(90°)), `bindCollision` → a = (0.2, 1.4, 0), b = (0.08, 1.4, 0.03),
 *     r = 0.071; and three's OWN skinning of a vertex at P weighted 1.0 to
 *     Head (`applyBoneTransform` + `matrixWorld`) lands on b — the rule is
 *     what the renderer draws, not a second opinion.
 *     A capsule naming a joint the figure lacks is in `missing`, not drawn;
 *     a garment skinned mesh's skeleton is never used (its bones are not
 *     looked at — a capsule naming only a garment bone is missing);
 *     version 3 / no capsules → null.
 * [5] Wireframe lines of r = 0.1, length 0.4: every vertex lies within
 *     r of the axis segment y ∈ [−0.2, 0.2] (distance ≤ r + 1e-9), the
 *     extreme y is ±(0.2 + 0.1·sin(π/2)) = ±0.3, the count is even (pairs).
 *     `capsuleWireframe` placed on [1]'s capsule: position = the midpoint
 *     (0.14, 1.4, 0.015), local +y maps onto (b − a)/|b − a|.
 */
import { spawnSync } from 'child_process'
import * as fs from 'fs'
import * as path from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

async function main() {
  if (!process.env.SMOKE_BUNDLED) {
    const bundlePath = '/tmp/smoke_collision_endpoints_bundled.mjs'
    const root = path.join(__dirname, '../')
    const bin = ['client3d/node_modules/.bin/esbuild', 'node_modules/.bin/esbuild']
      .map((rel) => path.join(root, rel)).find((p) => fs.existsSync(p))
    if (!bin) {
      console.error('esbuild not found (npm install) — nothing was checked')
      process.exit(1)
    }
    const built = spawnSync(bin, [
      __filename, '--bundle', '--platform=node', '--format=esm', `--outfile=${bundlePath}`,
    ], { cwd: root, stdio: 'inherit' })
    if (built.status !== 0) process.exit(built.status ?? 1)
    const run = spawnSync('node', [bundlePath], {
      stdio: 'inherit', env: { ...process.env, SMOKE_BUNDLED: '1' }, cwd: root,
    })
    process.exit(run.status ?? 1)
  }

  const { jointNowFrom, capsuleNow, capsuleLineSegments, bindCollision, capsuleWireframe } =
    await import('../packages/scene-render/src/collision.ts')
  const THREE = await import('three')

  const failures = []
  const check = (label, ok, detail = '') => {
    console.log(`  ${ok ? '✓' : '✗'} ${label}${detail ? ` — ${detail}` : ''}`)
    if (!ok) failures.push(label)
  }
  const near = (a, b, eps = 1e-6) => Math.abs(a - b) <= eps
  const vnear = (a, b, eps = 1e-6) => a.length === 3 && b.length === 3 && a.every((v, i) => near(v, b[i], eps))
  const fmt = (v) => `(${[...v].map((x) => +x.toFixed(6)).join(', ')})`

  // Column-major helpers (three's Matrix4.elements layout).
  const I = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
  const T = (x, y, z) => [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, x, y, z, 1]
  const S = (s) => [s, 0, 0, 0, 0, s, 0, 0, 0, 0, s, 0, 0, 0, 0, 1]
  const RZ90 = [0, 1, 0, 0, -1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
  const mul = (a, b) => new THREE.Matrix4().fromArray(a).multiply(new THREE.Matrix4().fromArray(b)).elements

  const J = [0, 1.5, 0.1]
  const P = [0, 1.62, 0.13]
  const capsule = { id: 'head', a: 'mixamorig:Head', b: 'mixamorig:Head', b_pos: P, r: 0.071, region: 'head' }
  const boneInverse = T(-J[0], -J[1], -J[2])
  const pose = mul(T(0.2, 1.4, 0), RZ90)

  console.log('--- [1] attached bind mode, posed head ---')
  let joint = jointNowFrom(I, I, pose, boneInverse, I)
  let now = capsuleNow(capsule, joint, joint)
  check('a = the joint (0.2, 1.4, 0)', vnear(now.a, [0.2, 1.4, 0]), fmt(now.a))
  check('b = (0.08, 1.4, 0.03)', vnear(now.b, [0.08, 1.4, 0.03]), fmt(now.b))
  check('r = 0.071', near(now.r, 0.071), String(now.r))
  const len = (c) => Math.hypot(c.b[0] - c.a[0], c.b[1] - c.a[1], c.b[2] - c.a[2])
  check('|b − a| = 0.123693', near(len(now), 0.123693), String(len(now)))
  const bind = capsuleNow(capsule, jointNowFrom(I, I, T(...J), boneInverse, I), jointNowFrom(I, I, T(...J), boneInverse, I))
  check('bind pose: a = J, b = P', vnear(bind.a, J) && vnear(bind.b, P), `${fmt(bind.a)} ${fmt(bind.b)}`)
  check('bind pose: same length', near(len(bind), 0.123693))

  console.log('--- [2] under a parent scale 0.5 ---')
  joint = jointNowFrom(I, I, mul(S(0.5), pose), boneInverse, I)
  now = capsuleNow(capsule, joint, joint)
  check('a = (0.1, 0.7, 0)', vnear(now.a, [0.1, 0.7, 0]), fmt(now.a))
  check('b = (0.04, 0.7, 0.015)', vnear(now.b, [0.04, 0.7, 0.015]), fmt(now.b))
  check('r = 0.0355', near(now.r, 0.0355), String(now.r))

  console.log('--- [3] detached bind mode, mesh one metre to the right ---')
  joint = jointNowFrom(T(1, 0, 0), I, pose, boneInverse, I)
  now = capsuleNow(capsule, joint, joint)
  check('a = (1.2, 1.4, 0)', vnear(now.a, [1.2, 1.4, 0]), fmt(now.a))
  check('b = (1.08, 1.4, 0.03)', vnear(now.b, [1.08, 1.4, 0.03]), fmt(now.b))
  check('r = 0.071', near(now.r, 0.071))

  console.log('--- [4] the same through three (bindCollision + three\'s own skinning) ---')
  const rootBone = new THREE.Bone(); rootBone.name = 'mixamorig:Hips'
  const head = new THREE.Bone(); head.name = 'mixamorig:Head'
  rootBone.add(head)
  head.position.set(0, 0.2, 0.1)  // bind: root at (0, 1.3, 0) → head at J = (0, 1.5, 0.1)
  rootBone.position.set(0, 1.3, 0)
  const figure = new THREE.Group()
  figure.add(rootBone)
  const geometry = new THREE.BufferGeometry()
  geometry.setAttribute('position', new THREE.Float32BufferAttribute([...P, ...J, 0, 1.3, 0], 3))
  geometry.setAttribute('skinIndex', new THREE.Uint16BufferAttribute([1, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0], 4))
  geometry.setAttribute('skinWeight', new THREE.Float32BufferAttribute([1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0], 4))
  const body = new THREE.SkinnedMesh(geometry, new THREE.MeshBasicMaterial())
  figure.add(body)
  figure.updateMatrixWorld(true)
  body.bind(new THREE.Skeleton([rootBone, head]))
  // A garment with its OWN skeleton: a bone named Neck that the body lacks.
  const neck = new THREE.Bone(); neck.name = 'mixamorig:Neck'
  const garment = new THREE.SkinnedMesh(geometry.clone(), new THREE.MeshBasicMaterial())
  garment.name = 'garment_scarf'
  garment.add(neck)
  figure.add(garment)
  figure.updateMatrixWorld(true)
  garment.bind(new THREE.Skeleton([neck]))
  // Pose: root T(0.2, 1.4, 0), head local = Rz(90°) at the root's origin → head world = T(0.2, 1.4, 0)·Rz90.
  rootBone.position.set(0.2, 1.4, 0)
  head.position.set(0, 0, 0)
  head.quaternion.setFromAxisAngle(new THREE.Vector3(0, 0, 1), Math.PI / 2)
  figure.updateMatrixWorld(true)
  const payload = {
    version: 2,
    capsules: [capsule,
      { id: 'left_shin', a: 'mixamorig:LeftLeg', b: 'mixamorig:LeftFoot', r: 0.09, region: 'leg' },
      { id: 'neck_only', a: 'mixamorig:Neck', b: 'mixamorig:Neck', r: 0.05, region: 'torso' }],
  }
  const binding = bindCollision(THREE, figure, payload)
  const bound = binding?.capsules.find((c) => c.capsule.id === 'head')?.now
  check('bound: a = (0.2, 1.4, 0)', !!bound && vnear(bound.a, [0.2, 1.4, 0]), bound && fmt(bound.a))
  check('bound: b = (0.08, 1.4, 0.03)', !!bound && vnear(bound.b, [0.08, 1.4, 0.03]), bound && fmt(bound.b))
  check('bound: r = 0.071', !!bound && near(bound.r, 0.071))
  const skinned = body.applyBoneTransform(0, new THREE.Vector3(...P)).applyMatrix4(body.matrixWorld)
  check('three\'s skinning of P lands on b', !!bound && vnear(bound.b, [skinned.x, skinned.y, skinned.z], 1e-5),
    fmt([skinned.x, skinned.y, skinned.z]))
  const skinnedJ = body.applyBoneTransform(1, new THREE.Vector3(...J)).applyMatrix4(body.matrixWorld)
  check('three\'s skinning of J lands on a', !!bound && vnear(bound.a, [skinnedJ.x, skinnedJ.y, skinnedJ.z], 1e-5),
    fmt([skinnedJ.x, skinnedJ.y, skinnedJ.z]))
  check('missing joints reported, garment skeleton ignored',
    JSON.stringify(binding?.missing) === JSON.stringify(['left_shin', 'neck_only']), JSON.stringify(binding?.missing))
  check('only the head is bound', binding?.capsules.length === 1)
  // update() follows a new pose
  head.quaternion.identity()
  figure.updateMatrixWorld(true)
  binding.update()
  const straight = binding.capsules[0].now
  check('update(): unrotated head → b = (0.2, 1.52, 0.03)', vnear(straight.b, [0.2, 1.52, 0.03]), fmt(straight.b))
  check('version 3 → null', bindCollision(THREE, figure, { ...payload, version: 3 }) === null)
  check('no capsules → null', bindCollision(THREE, figure, { version: 2, capsules: [] }) === null)
  check('null payload → null', bindCollision(THREE, figure, null) === null)

  console.log('--- [5] wireframe ---')
  const lines = capsuleLineSegments(0.1, 0.4)
  let worst = 0, ymax = -Infinity, ymin = Infinity
  for (let i = 0; i < lines.length; i += 3) {
    const [x, y, z] = [lines[i], lines[i + 1], lines[i + 2]]
    const cy = Math.max(-0.2, Math.min(0.2, y))
    worst = Math.max(worst, Math.hypot(x, y - cy, z))
    ymax = Math.max(ymax, y); ymin = Math.min(ymin, y)
  }
  check('every vertex within r of the axis segment', worst <= 0.1 + 1e-9, String(worst))
  check('extreme y = ±0.3', near(ymax, 0.3) && near(ymin, -0.3), `${ymin} … ${ymax}`)
  check('pairs', (lines.length / 3) % 2 === 0)
  const c1 = { a: [0.2, 1.4, 0], b: [0.08, 1.4, 0.03], r: 0.071 }
  const wire = capsuleWireframe(THREE, c1)
  check('wire at the midpoint (0.14, 1.4, 0.015)', vnear(wire.position.toArray(), [0.14, 1.4, 0.015]), fmt(wire.position.toArray()))
  const up = new THREE.Vector3(0, 1, 0).applyQuaternion(wire.quaternion)
  const dir = new THREE.Vector3(-0.12, 0, 0.03).normalize()
  check('local +y along b − a', vnear(up.toArray(), dir.toArray()), fmt(up.toArray()))
  wire.geometry.dispose()

  console.log(failures.length ? `\nFAIL (${failures.length})` : '\nOK')
  process.exit(failures.length ? 1 : 0)
}

main().catch((e) => { console.error(e); process.exit(1) })
