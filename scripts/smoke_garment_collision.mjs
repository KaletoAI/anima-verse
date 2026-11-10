#!/usr/bin/env node
/**
 * Smoke check for the GARMENT PUSH — `packages/scene-render/src/garmentCollision.ts`:
 * the pure push (`pushOutOfCapsules`), its shader twin (`COLLIDE_GLSL_FUNCTION`,
 * EXECUTED here through a mechanical GLSL→JS rewrite and compared point by
 * point), the vertex-shader patch on three's real shader sources, and the
 * three binding (`createGarmentCollision`: which meshes, which space, the
 * per-frame hook, the ownership of the cloned materials, inert cases).
 *
 * Usage: direct node call, self-bundling via esbuild (run from anywhere):
 *   node scripts/smoke_garment_collision.mjs
 *
 * Every expected number is derived BY HAND (§ B5a). A capsule is the set of
 * points within r of the segment a→b; a point inside is moved along the
 * perpendicular from its closest axis point c out to |p − c| = r.
 *
 * Capsule C = {a (0,0,0), b (0,1,0), r 0.1}:
 * [1] p (0.05, 0.5, 0): c = (0, 0.5, 0), d = 0.05 < r → (0.1, 0.5, 0).
 *     p (0.2, 0.5, 0): d = 0.2 ≥ r → unchanged.
 *     p (0.1, 0.5, 0) ON the surface: d = r, not < r → unchanged.
 *     p (0, 0.5, 0) ON the axis: d = 0, no direction → unchanged.
 *     p (0, −0.05, 0.03) in the lower cap: t clamps to 0, c = a,
 *       d = √(0.0025 + 0.0009) = 0.0583095, k = r/d = 1.7149859 →
 *       (0, −0.0857493, 0.0514496); |result| = 0.1.
 *     p (0, 1.06, 0.08) in the upper cap: c = b, d = √(0.0036 + 0.0064) = 0.1
 *       → exactly on the surface → unchanged.
 * [2] Degenerate capsule a = b = (0,0,0), r 0.1 (a sphere):
 *     p (0.03, 0.04, 0): d = 0.05 → × 2 → (0.06, 0.08, 0).
 * [3] Weight: p (0.05, 0.5, 0), weight 0.5 → halfway: (0.075, 0.5, 0);
 *     weight 0 → unchanged; weight 2 clamps to 1 → (0.1, 0.5, 0).
 * [4] Two passes, order: C and C' = {a (0.15,0,0), b (0.15,1,0), r 0.1},
 *     p (0.06, 0.5, 0). Pass 1: C → (0.1, 0.5, 0); C' (axis x = 0.15,
 *     d = 0.05) → pushed to x = 0.15 − 0.1 = 0.05. Pass 2 repeats both →
 *     (0.05, 0.5, 0): payload order decides, deterministically (a vertex
 *     squeezed between two overlapping capsules ends at the later one's surface).
 * [5] COLLIDE_MAX: 16 far capsules + a 17th containing p → p unchanged
 *     (only the first 16 are applied); with the containing one FIRST → pushed.
 * [6] capsuleInFrame with m = T(1,0,0)·S(2): C → a (1,0,0), b (1,2,0), r 0.2.
 * [6b] BIND RULE: radius capped at the bind distance d0 of the vertex's bind
 *     point q to the bind capsule. C with bind capsule = C's own axis:
 *     q (0.06, 0.5, 0): d0 = 0.06 → p (0.03, 0.5, 0) pushed to (0.06, 0.5, 0)
 *       (not to 0.1); p (0.08, 0.5, 0): d = 0.08 ≥ 0.06 → unchanged;
 *     q = p = (0.05, 0.5, 0) (the bind pose itself) → unchanged;
 *     q (0.3, 0.5, 0): d0 = 0.3 ≥ r → the plain push, (0.05,0.5,0) → (0.1, 0.5, 0);
 *     bind capsule (1,0,0)→(1,1,0), q (1.02, 0.5, 0): d0 = 0.02 → p (0.05, 0.5, 0)
 *       has d = 0.05 ≥ 0.02 → unchanged (the bind capsule is its own frame);
 *     no bind point given → the plain push (0.1, 0.5, 0).
 * [7] ONE SOURCE: COLLIDE_GLSL_FUNCTION run as JS on 3000 random points ×
 *     random capsule sets of 0–20 capsules (incl. degenerate ones; half the
 *     points near a capsule axis, so > 600 of them are pushed; about half the
 *     capsules under the bind rule with a random bind point and bind capsule)
 *     gives the same point as pushOutOfCapsules (≤ 1e-12 m).
 * [8] The patch on three's real sources (standard, depth, distance): the
 *     declarations once after `#include <common>`, the push once right after
 *     `#include <skinning_vertex>` (before `#include <project_vertex>`), the
 *     weight attribute only under COLLIDE_WEIGHT; idempotent.
 * [9] createGarmentCollision on a two-bone figure — Hips at (0,0,0), Spine at
 *     (0,1,0); payload {torso: Hips→Spine r 0.1, ghost: Hips→Missing,
 *     sleeve: Hips→Spine r 0.2 region arm}:
 *     body mesh + garment `garment_clothing_x` (mesh moved to (0.5,0,0), which
 *     is ITS local space) + hair `garment_hair_y`.
 *       - one entry (the clothing; hair gets no capsules) holding ONLY the
 *         torso capsule (cloth is never pushed out of an arm capsule), its local capsule
 *         a = (−0.5, 0, 0), b = (−0.5, 1, 0), r 0.1 (= world − mesh offset);
 *       - its material is a CLONE (the template's stays untouched) that chains
 *         the template material's own compile hook (clone() drops it), depth +
 *         distance materials set, all three compile the patch (onBeforeCompile
 *         on a fake shader adds the uniforms and `collidePush(`);
 *       - hook: Spine moved to (0, 2, 0) → onBeforeRender(frame 1) writes
 *         b = (−0.5, 2, 0); moved again in the SAME frame → unchanged;
 *         onBeforeShadow(frame 2) → updated;
 *       - a garment carrying `_collide` gets the COLLIDE_WEIGHT define;
 *       - dispose(): original material back, hooks gone (prototype again),
 *         custom depth/distance cleared, the 3 owned clones disposed;
 *       - inert: no garment / null payload → null.
 *     The hair `garment_hair_y` sits at (0, 0, 0.25) when bound, so its
 *     geometry space is world − (0, 0, 0.25):
 *       - its entry holds torso AND sleeve (hair: torso/arm/head regions),
 *         local torso a (0, 0, −0.25), b (0, 1, −0.25), r 0.1, and the BIND
 *         capsule the same a/b (bind pose = current pose at bind time);
 *       - after Spine → (0, 2, 0): local b (0, 2, −0.25), bind b still
 *         (0, 1, −0.25); uniforms collideBindA[0] = (0, 0, −0.25, 0) (w ≥ 0 =
 *         rule on), collideBindB[0] = (0, 1, −0.25, 0);
 *       - the clothing is under the bind rule too: its bind torso capsule
 *         a (−0.5, 0, 0), b (−0.5, 1, 0), uniform collideBindA[0].w = 0;
 *       - hair only → one entry (no longer inert).
 * [10] CLOTHING AT REST (bind rule for every garment): the clothing mesh at
 *     the origin, its vertex v0 = (0.05, 0.5, 0) lies 0.05 from the torso
 *     axis (0,0,0)→(0,1,0), inside r 0.1. The plain push (Task 3) moved it to
 *     (0.1, 0.5, 0) in the REST pose — 0.05 m of puff. With the bind rule its
 *     bind distance d0 = 0.05 caps the radius: displacement 0 in the rest
 *     pose. Posed: Hips moved to (−0.02, 0, 0) (whole torso axis x = −0.02,
 *     v0 skinned to Hips moves along to (0.03, 0.5, 0) — distance still 0.05)
 *     → still 0; Spine-weighted v1 = (0, 1, 0) sits ON the axis end b → stays.
 *     Body swung into the cloth: the entry's local capsule shifted to
 *     x = +0.03, the cloth point (0.05, 0.5, 0) with the same bind point:
 *     d = 0.02 < d0 = 0.05 → pushed outwards (+x) to 0.03 + 0.05 →
 *     (0.08, 0.5, 0) — back to its bind distance, not to r (0.13).
 * [11] FOOTWEAR gets NO capsules (footwear spec § 7.2: a rigid shoe is never
 *     pushed). garmentCapsules('footwear', …) over one capsule of every
 *     region (torso, leg, arm, head, chest, attached_part) → [] — none, not
 *     the 4 non-arm non-extension ones (torso, leg, head) the cloth rule
 *     would leave. On the [9] figure with a skinned footwear garment
 *     `garment_footwear_i_left` (extras kind footwear) under a Group:
 *       - clothing + shoe → exactly one entry, the clothing (shoe skipped);
 *       - shoe only → createGarmentCollision null (nothing to push);
 *       - collidingGarmentMeshes lists the clothing mesh, not the shoe;
 *       - the shoe's material stays the template (never patched).
 */
import { spawnSync } from 'child_process'
import * as fs from 'fs'
import * as path from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

/** The mechanical GLSL→JS rewrite of `COLLIDE_GLSL_FUNCTION` (scalar statements only). */
export function glslPushToJs(glsl, defines) {
  let body = glsl
    .replace(/vec3\s+collidePush\s*\(\s*vec3\s+p\s*\)\s*\{/, 'function collidePush(p0) { const p = { x: p0[0], y: p0[1], z: p0[2] };')
    .replace(/\bfloat\s+/g, 'let ')
    .replace(/\bint\s+/g, 'let ')
    .replace(/return p;/, 'return [p.x, p.y, p.z];')
  if (/\bvec[234]\b|\bmat[234]\b/.test(body)) throw new Error('GLSL push uses vector types — not scalar any more')
  const names = Object.keys(defines)
  // eslint-disable-next-line no-new-func
  return new Function(...names, 'collideA', 'collideB', 'collideBindA', 'collideBindB', 'collideCount', 'position',
    'clamp', 'sqrt', 'min', `${body}\nreturn collidePush;`)
}

async function main() {
  if (!process.env.SMOKE_BUNDLED) {
    const bundlePath = '/tmp/smoke_garment_collision_bundled.mjs'
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

  const G = await import('../packages/scene-render/src/garmentCollision.ts')
  const THREE = await import('three')
  const { pushOutOfCapsules, capsuleInFrame, patchCollisionVertexShader, createGarmentCollision,
    COLLIDE_MAX, COLLIDE_PASSES, COLLIDE_EPS, COLLIDE_MIN_D, COLLIDE_GLSL_FUNCTION } = G

  const failures = []
  const check = (label, ok, detail = '') => {
    console.log(`  ${ok ? '✓' : '✗'} ${label}${detail ? ` — ${detail}` : ''}`)
    if (!ok) failures.push(label)
  }
  const near = (a, b, eps = 1e-6) => Math.abs(a - b) <= eps
  const vnear = (a, b, eps = 1e-6) => a.length === 3 && b.length === 3 && a.every((v, i) => near(v, b[i], eps))
  const fmt = (v) => `(${[...v].map((x) => +x.toFixed(7)).join(', ')})`
  const C = { a: [0, 0, 0], b: [0, 1, 0], r: 0.1 }

  console.log('--- [1] one capsule ---')
  let q = pushOutOfCapsules([0.05, 0.5, 0], [C])
  check('inside the cylinder → (0.1, 0.5, 0)', vnear(q, [0.1, 0.5, 0]), fmt(q))
  q = pushOutOfCapsules([0.2, 0.5, 0], [C])
  check('outside → unchanged', vnear(q, [0.2, 0.5, 0]), fmt(q))
  q = pushOutOfCapsules([0.1, 0.5, 0], [C])
  check('on the surface → unchanged', vnear(q, [0.1, 0.5, 0], 0), fmt(q))
  q = pushOutOfCapsules([0, 0.5, 0], [C])
  check('on the axis → unchanged', vnear(q, [0, 0.5, 0], 0), fmt(q))
  q = pushOutOfCapsules([0, -0.05, 0.03], [C])
  check('lower cap → (0, −0.0857493, 0.0514496)', vnear(q, [0, -0.0857493, 0.0514496]), fmt(q))
  check('lower cap → |q − a| = r', near(Math.hypot(...q), 0.1, 1e-9))
  q = pushOutOfCapsules([0, 1.06, 0.08], [C])
  check('upper cap, exactly on the surface → unchanged', vnear(q, [0, 1.06, 0.08], 1e-9), fmt(q))

  console.log('--- [2] degenerate capsule a = b ---')
  q = pushOutOfCapsules([0.03, 0.04, 0], [{ a: [0, 0, 0], b: [0, 0, 0], r: 0.1 }])
  check('sphere → (0.06, 0.08, 0)', vnear(q, [0.06, 0.08, 0]), fmt(q))

  console.log('--- [3] weight ---')
  q = pushOutOfCapsules([0.05, 0.5, 0], [C], 0.5)
  check('weight 0.5 → (0.075, 0.5, 0)', vnear(q, [0.075, 0.5, 0]), fmt(q))
  q = pushOutOfCapsules([0.05, 0.5, 0], [C], 0)
  check('weight 0 → unchanged', vnear(q, [0.05, 0.5, 0], 0), fmt(q))
  q = pushOutOfCapsules([0.05, 0.5, 0], [C], 2)
  check('weight 2 clamps to 1 → (0.1, 0.5, 0)', vnear(q, [0.1, 0.5, 0]), fmt(q))

  console.log('--- [4] two passes, payload order ---')
  const C2 = { a: [0.15, 0, 0], b: [0.15, 1, 0], r: 0.1 }
  q = pushOutOfCapsules([0.06, 0.5, 0], [C, C2])
  check(`${COLLIDE_PASSES} passes → (0.05, 0.5, 0)`, COLLIDE_PASSES === 2 && vnear(q, [0.05, 0.5, 0]), fmt(q))

  console.log('--- [5] COLLIDE_MAX ---')
  const far = Array.from({ length: 16 }, (_, i) => ({ a: [10 + i, 0, 0], b: [10 + i, 1, 0], r: 0.1 }))
  q = pushOutOfCapsules([0.05, 0.5, 0], [...far, C])
  check(`COLLIDE_MAX = 16, the 17th is not applied`, COLLIDE_MAX === 16 && vnear(q, [0.05, 0.5, 0], 0), fmt(q))
  q = pushOutOfCapsules([0.05, 0.5, 0], [C, ...far])
  check('first in payload order is applied', vnear(q, [0.1, 0.5, 0]), fmt(q))

  console.log('--- [6] capsuleInFrame ---')
  const m = new THREE.Matrix4().makeTranslation(1, 0, 0).multiply(new THREE.Matrix4().makeScale(2, 2, 2)).elements
  const f = capsuleInFrame(C, m)
  check('a (1,0,0), b (1,2,0), r 0.2', vnear(f.a, [1, 0, 0]) && vnear(f.b, [1, 2, 0]) && near(f.r, 0.2),
    `${fmt(f.a)} ${fmt(f.b)} ${f.r}`)

  console.log('--- [6b] bind rule ---')
  const Cb = { ...C, bind: { a: [0, 0, 0], b: [0, 1, 0] } }
  q = pushOutOfCapsules([0.03, 0.5, 0], [Cb], 1, [0.06, 0.5, 0])
  check('d0 0.06: (0.03, 0.5, 0) → (0.06, 0.5, 0)', vnear(q, [0.06, 0.5, 0]), fmt(q))
  q = pushOutOfCapsules([0.08, 0.5, 0], [Cb], 1, [0.06, 0.5, 0])
  check('d0 0.06: (0.08, 0.5, 0) unchanged', vnear(q, [0.08, 0.5, 0], 0), fmt(q))
  q = pushOutOfCapsules([0.05, 0.5, 0], [Cb], 1, [0.05, 0.5, 0])
  check('bind pose itself → unchanged', vnear(q, [0.05, 0.5, 0], 0), fmt(q))
  q = pushOutOfCapsules([0.05, 0.5, 0], [Cb], 1, [0.3, 0.5, 0])
  check('d0 ≥ r → plain push (0.1, 0.5, 0)', vnear(q, [0.1, 0.5, 0]), fmt(q))
  q = pushOutOfCapsules([0.05, 0.5, 0], [{ ...C, bind: { a: [1, 0, 0], b: [1, 1, 0] } }], 1, [1.02, 0.5, 0])
  check('bind capsule in its own frame, d0 0.02 → unchanged', vnear(q, [0.05, 0.5, 0], 0), fmt(q))
  q = pushOutOfCapsules([0.05, 0.5, 0], [Cb])
  check('no bind point → plain push', vnear(q, [0.1, 0.5, 0]), fmt(q))

  console.log('--- [7] ONE SOURCE: the shader text executed ---')
  const defines = { COLLIDE_MAX, COLLIDE_PASSES, COLLIDE_EPS, COLLIDE_MIN_D }
  const factory = glslPushToJs(COLLIDE_GLSL_FUNCTION, defines)
  let seed = 12345
  const rnd = () => { seed = (seed * 1103515245 + 12345) % 2147483648; return seed / 2147483648 }
  let worst = 0, moved = 0, bindLimited = 0
  const jitter = (v, s) => v.map((x) => x + (rnd() - 0.5) * s)
  for (let n = 0; n < 3000; n++) {
    const count = Math.floor(rnd() * 21)
    const caps = Array.from({ length: count }, () => {
      const a = [rnd() - 0.5, rnd() * 2, rnd() - 0.5]
      const b = rnd() < 0.15 ? [...a] : [a[0] + (rnd() - 0.5) * 0.6, a[1] + (rnd() - 0.5) * 0.6, a[2] + (rnd() - 0.5) * 0.6]
      const c = { a, b, r: 0.02 + rnd() * 0.2 }
      if (rnd() < 0.5) c.bind = { a: jitter(a, 0.1), b: jitter(b, 0.1) }
      return c
    })
    // half the points near a random capsule's axis, so the sample pushes a lot
    const near0 = count && rnd() < 0.5 ? caps[Math.floor(rnd() * count)] : null
    const p = near0 ? near0.a.map((v, i) => v + (near0.b[i] - v) * rnd() + (rnd() - 0.5) * 0.2)
      : [rnd() - 0.5, rnd() * 2, rnd() - 0.5]
    const bindP = jitter(p, 0.15)
    const used = caps.slice(0, COLLIDE_MAX)
    const A = used.map((c) => ({ x: c.a[0], y: c.a[1], z: c.a[2], w: c.r }))
    const B = used.map((c) => ({ x: c.b[0], y: c.b[1], z: c.b[2], w: 0 }))
    const BA = used.map((c) => (c.bind ? { x: c.bind.a[0], y: c.bind.a[1], z: c.bind.a[2], w: 0 } : { x: 0, y: 0, z: 0, w: -1 }))
    const BB = used.map((c) => (c.bind ? { x: c.bind.b[0], y: c.bind.b[1], z: c.bind.b[2], w: 0 } : { x: 0, y: 0, z: 0, w: 0 }))
    const glsl = factory(COLLIDE_MAX, COLLIDE_PASSES, COLLIDE_EPS, COLLIDE_MIN_D, A, B, BA, BB, used.length,
      { x: bindP[0], y: bindP[1], z: bindP[2] }, (v, lo, hi) => Math.min(hi, Math.max(lo, v)), Math.sqrt, Math.min)(p)
    const ts = pushOutOfCapsules(p, caps, 1, bindP)
    const plain = pushOutOfCapsules(p, caps)
    if (Math.hypot(plain[0] - ts[0], plain[1] - ts[1], plain[2] - ts[2]) > 1e-9) bindLimited++
    worst = Math.max(worst, Math.hypot(glsl[0] - ts[0], glsl[1] - ts[1], glsl[2] - ts[2]))
    if (Math.hypot(ts[0] - p[0], ts[1] - p[1], ts[2] - p[2]) > 1e-9) moved++
  }
  check('GLSL text and TS function agree on 3000 points', worst <= 1e-12, `worst ${worst}`)
  check('the sample actually pushes (> 600 points moved)', moved > 600, `${moved} moved`)
  check('the bind rule actually limits (> 300 points differ from the plain push)', bindLimited > 300, `${bindLimited} limited`)

  console.log('--- [8] shader patch on three\'s sources ---')
  const count = (s, needle) => s.split(needle).length - 1
  for (const [name, src] of [['standard', THREE.ShaderLib.standard.vertexShader],
    ['depth', THREE.ShaderLib.depth.vertexShader], ['distance', THREE.ShaderLib.distance.vertexShader]]) {
    const out = patchCollisionVertexShader(src)
    const iSkin = out.indexOf('#include <skinning_vertex>')
    const iCall = out.indexOf('collidePush( transformed )')
    const iProj = out.indexOf('#include <project_vertex>')
    check(`${name}: declarations once, function once`, count(out, 'uniform vec4 collideA') === 1
      && count(out, 'uniform vec4 collideBindA') === 1 && count(out, 'vec3 collidePush( vec3 p )') === 1)
    check(`${name}: push after skinning, before projection`, iSkin >= 0 && iCall > iSkin && iProj > iCall)
    check(`${name}: weight attribute only under COLLIDE_WEIGHT`,
      /#ifdef COLLIDE_WEIGHT\nattribute float _collide;\n#endif/.test(out))
    check(`${name}: idempotent`, patchCollisionVertexShader(out) === out)
  }

  console.log('--- [9] createGarmentCollision on a figure ---')
  const build = ({ clothing = true, hair = true, weighted = false, clothingAt = [0.5, 0, 0], footwear = false } = {}) => {
    const figure = new THREE.Group()
    const hips = new THREE.Bone(); hips.name = 'mixamorig:Hips'
    const spine = new THREE.Bone(); spine.name = 'mixamorig:Spine'
    spine.position.set(0, 1, 0)
    hips.add(spine)
    figure.add(hips)
    const geo = () => {
      const g = new THREE.BufferGeometry()
      g.setAttribute('position', new THREE.Float32BufferAttribute([0.05, 0.5, 0, 0, 1, 0], 3))
      g.setAttribute('skinIndex', new THREE.Uint16BufferAttribute([0, 0, 0, 0, 1, 0, 0, 0], 4))
      g.setAttribute('skinWeight', new THREE.Float32BufferAttribute([1, 0, 0, 0, 1, 0, 0, 0], 4))
      return g
    }
    const meshes = {}
    meshes.body = new THREE.SkinnedMesh(geo(), new THREE.MeshStandardMaterial())
    figure.add(meshes.body)
    if (clothing) {
      const g = geo()
      if (weighted) g.setAttribute('_collide', new THREE.Float32BufferAttribute([1, 0.5], 1))
      meshes.clothing = new THREE.SkinnedMesh(g, new THREE.MeshStandardMaterial())
      meshes.clothing.name = 'garment_clothing_x'
      meshes.clothing.position.set(...clothingAt)
      figure.add(meshes.clothing)
    }
    if (hair) {
      meshes.hair = new THREE.SkinnedMesh(geo(), new THREE.MeshStandardMaterial())
      meshes.hair.name = 'garment_hair_y'
      meshes.hair.userData.garment = { kind: 'hair', item_id: 'y', fsig: 'z' }
      meshes.hair.position.set(0, 0, 0.25)
      figure.add(meshes.hair)
    }
    if (footwear) {
      const shoe = new THREE.Group()
      shoe.name = 'garment_footwear_i_left'
      shoe.userData.garment = { kind: 'footwear', item_id: 'i', fsig: 'abc', side: 'left' }
      meshes.footwear = new THREE.SkinnedMesh(geo(), new THREE.MeshStandardMaterial())
      shoe.add(meshes.footwear)
      figure.add(shoe)
    }
    figure.updateMatrixWorld(true)
    const skeleton = new THREE.Skeleton([hips, spine])
    for (const mesh of Object.values(meshes)) mesh.bind(skeleton)
    return { figure, hips, spine, meshes }
  }
  const payload = { version: 2, capsules: [
    { id: 'torso', a: 'mixamorig:Hips', b: 'mixamorig:Spine', r: 0.1, region: 'torso' },
    { id: 'ghost', a: 'mixamorig:Hips', b: 'mixamorig:Missing', r: 0.1, region: 'torso' },
    { id: 'sleeve', a: 'mixamorig:Hips', b: 'mixamorig:Spine', r: 0.2, region: 'arm' }] }
  const fig = build()
  const templateMaterial = fig.meshes.clothing.material
  // a compile hook on the template's material (clone() drops it) must survive into the patched clone
  templateMaterial.onBeforeCompile = (shader) => { shader.vertexShader = `// template hook\n${shader.vertexShader}` }
  const disposed = []
  const gc = createGarmentCollision(THREE, fig.figure, payload)
  check('two entries (clothing, hair)', gc?.entries.length === 2
    && gc.entries[0].mesh === fig.meshes.clothing && gc.entries[0].kind === 'clothing'
    && gc.entries[1].mesh === fig.meshes.hair && gc.entries[1].kind === 'hair', String(gc?.entries.length))
  check('clothing: torso only, the arm capsule is not applied',
    gc?.entries[0].capsules.map((c) => c.capsule.id).join() === 'torso', gc?.entries[0].capsules.map((c) => c.capsule.id).join())
  check('missing joint reported by the binding', JSON.stringify(gc?.binding.missing) === '["ghost"]')
  let local = gc.entries[0].local[0]
  check('local capsule a (−0.5,0,0), b (−0.5,1,0), r 0.1', vnear(local.a, [-0.5, 0, 0]) && vnear(local.b, [-0.5, 1, 0])
    && near(local.r, 0.1), `${fmt(local.a)} ${fmt(local.b)} ${local.r}`)
  const own = fig.meshes.clothing.material
  check('material is a clone, template untouched', own !== templateMaterial
    && templateMaterial.customProgramCacheKey === THREE.Material.prototype.customProgramCacheKey)
  const chained = { uniforms: {}, vertexShader: THREE.ShaderLib.standard.vertexShader }
  own.onBeforeCompile(chained, null)
  check('the template\'s own compile hook is chained into the clone', chained.vertexShader.startsWith('// template hook')
    && chained.vertexShader.includes('collidePush('))
  check('cache key: the template hook\'s source + |collide', own.customProgramCacheKey()
    === `${templateMaterial.onBeforeCompile.toString()}|collide`)
  const hairEntry = gc.entries[1]
  check('hair: torso AND sleeve (arm region)', hairEntry.capsules.map((c) => c.capsule.id).join() === 'torso,sleeve',
    hairEntry.capsules.map((c) => c.capsule.id).join())
  const hl = hairEntry.local[0]
  check('hair local torso a (0,0,−0.25), b (0,1,−0.25), r 0.1', vnear(hl.a, [0, 0, -0.25]) && vnear(hl.b, [0, 1, -0.25])
    && near(hl.r, 0.1), `${fmt(hl.a)} ${fmt(hl.b)} ${hl.r}`)
  check('hair bind capsule a (0,0,−0.25), b (0,1,−0.25)', !!hl.bind && vnear(hl.bind.a, [0, 0, -0.25]) && vnear(hl.bind.b, [0, 1, -0.25]),
    hl.bind ? `${fmt(hl.bind.a)} ${fmt(hl.bind.b)}` : 'none')
  const cb = gc.entries[0].local[0].bind
  check('clothing bind capsule a (−0.5,0,0), b (−0.5,1,0)', !!cb && vnear(cb.a, [-0.5, 0, 0]) && vnear(cb.b, [-0.5, 1, 0]),
    cb ? `${fmt(cb.a)} ${fmt(cb.b)}` : 'none')
  const hairMat = fig.meshes.hair.material
  check('hair material patched (a clone)', String(hairMat.customProgramCacheKey()).includes('collide'))
  for (const [name, mat] of [['material', own], ['depth', fig.meshes.clothing.customDepthMaterial],
    ['distance', fig.meshes.clothing.customDistanceMaterial]]) {
    mat.addEventListener('dispose', () => disposed.push(name))
    const shader = { uniforms: {}, vertexShader: THREE.ShaderLib.standard.vertexShader, fragmentShader: '' }
    mat.onBeforeCompile(shader, null)
    check(`${name}: compiles the patch with the shared uniforms`, shader.vertexShader.includes('collidePush(')
      && shader.uniforms.collideCount?.value === 1 && shader.uniforms.collideA?.value?.length === COLLIDE_MAX
      && mat.customProgramCacheKey().endsWith('|collide'))
  }
  check('depth material packs RGBA like three\'s own', fig.meshes.clothing.customDepthMaterial.depthPacking === THREE.RGBADepthPacking)
  const shaderOf = (mat) => { const s = { uniforms: {}, vertexShader: THREE.ShaderLib.standard.vertexShader }; mat.onBeforeCompile(s, null); return s }
  const uniformsOf = shaderOf(own).uniforms
  check('depth material shares the uniform objects', shaderOf(fig.meshes.clothing.customDepthMaterial).uniforms.collideA === uniformsOf.collideA)
  const fakeRenderer = (frame) => ({ info: { render: { frame } } })
  fig.spine.position.set(0, 2, 0)
  fig.figure.updateMatrixWorld(true)
  fig.meshes.clothing.onBeforeRender(fakeRenderer(1), null, null, null, own, null)
  const B = uniformsOf.collideB.value[0]
  check('onBeforeRender frame 1 → b (−0.5, 2, 0)', vnear([B.x, B.y, B.z], [-0.5, 2, 0]), fmt([B.x, B.y, B.z]))
  fig.spine.position.set(0, 3, 0)
  fig.figure.updateMatrixWorld(true)
  fig.meshes.clothing.onBeforeRender(fakeRenderer(1), null, null, null, own, null)
  check('same frame again → unchanged', near(B.y, 2), String(B.y))
  fig.meshes.clothing.onBeforeShadow(fakeRenderer(2), null, null, null, null, null, null)
  check('onBeforeShadow frame 2 → b y 3', near(B.y, 3), String(B.y))
  const cba = uniformsOf.collideBindA.value[0]
  check('clothing uniform collideBindA[0] = (−0.5, 0, 0, 0)', vnear([cba.x, cba.y, cba.z], [-0.5, 0, 0]) && near(cba.w, 0),
    fmt([cba.x, cba.y, cba.z, cba.w]))
  fig.spine.position.set(0, 2, 0)
  fig.figure.updateMatrixWorld(true)
  fig.meshes.hair.onBeforeRender(fakeRenderer(3), null, null, null, hairMat, null)
  const hu = shaderOf(hairMat).uniforms
  const hb = hu.collideB.value[0], hba = hu.collideBindA.value[0], hbb = hu.collideBindB.value[0]
  check('hair after Spine → (0,2,0): b (0, 2, −0.25)', vnear([hb.x, hb.y, hb.z], [0, 2, -0.25]), fmt([hb.x, hb.y, hb.z]))
  check('hair bind uniforms fixed: A (0,0,−0.25,0), B (0,1,−0.25)', vnear([hba.x, hba.y, hba.z], [0, 0, -0.25]) && near(hba.w, 0)
    && vnear([hbb.x, hbb.y, hbb.z], [0, 1, -0.25]), `${fmt([hba.x, hba.y, hba.z, hba.w])} ${fmt([hbb.x, hbb.y, hbb.z])}`)
  const A = uniformsOf.collideA.value[0]
  check('collideA.w carries r', near(A.w, 0.1), String(A.w))
  gc.dispose()
  check('dispose: original material back', fig.meshes.clothing.material === templateMaterial)
  check('dispose: hooks back on the prototype',
    !Object.prototype.hasOwnProperty.call(fig.meshes.clothing, 'onBeforeRender')
    && !Object.prototype.hasOwnProperty.call(fig.meshes.clothing, 'onBeforeShadow'))
  check('dispose: custom depth/distance cleared', fig.meshes.clothing.customDepthMaterial === undefined
    && fig.meshes.clothing.customDistanceMaterial === undefined)
  check('dispose: the 3 owned clones freed', disposed.sort().join() === 'depth,distance,material', disposed.join())

  const w = build({ weighted: true })
  const gw = createGarmentCollision(THREE, w.figure, payload)
  check('_collide → COLLIDE_WEIGHT define + its own cache key', 'COLLIDE_WEIGHT' in (w.meshes.clothing.material.defines ?? {})
    && w.meshes.clothing.material.customProgramCacheKey().endsWith('|collideW'))
  gw.dispose()
  check('inert: no garment → null', createGarmentCollision(THREE, build({ clothing: false, hair: false }).figure, payload) === null)
  check('inert: null payload → null', createGarmentCollision(THREE, build().figure, null) === null)
  const hairOnly = build({ clothing: false })
  const ho = createGarmentCollision(THREE, hairOnly.figure, payload)
  check('hair only → one hair entry', ho?.entries.length === 1 && ho.entries[0].kind === 'hair')
  ho?.dispose()

  console.log('--- [10] clothing at rest: no puff ---')
  const rest = build({ hair: false, clothingAt: [0, 0, 0] })
  const gr = createGarmentCollision(THREE, rest.figure, payload)
  const ce = gr.entries[0]
  const geoPos = ce.mesh.geometry.attributes.position
  const v0 = [geoPos.getX(0), geoPos.getY(0), geoPos.getZ(0)]
  q = pushOutOfCapsules(v0, ce.local, 1, v0)
  check('rest pose: v0 (0.05, 0.5, 0) not displaced (plain push: (0.1, 0.5, 0))', vnear(q, v0, 0), fmt(q))
  const plainRest = pushOutOfCapsules(v0, ce.local)
  check('the plain push WOULD puff it to (0.1, 0.5, 0)', vnear(plainRest, [0.1, 0.5, 0]), fmt(plainRest))
  rest.hips.position.set(-0.02, 0, 0)
  rest.figure.updateMatrixWorld(true)
  gr.update()
  const v0posed = new THREE.Vector3(...v0)
  ce.mesh.applyBoneTransform(0, v0posed)
  q = pushOutOfCapsules([v0posed.x, v0posed.y, v0posed.z], ce.local, 1, v0)
  check('rigid move of body + cloth: (0.03, 0.5, 0) stays', vnear(q, [0.03, 0.5, 0]), fmt(q))
  const v1 = [geoPos.getX(1), geoPos.getY(1), geoPos.getZ(1)]
  const v1posed = new THREE.Vector3(...v1); ce.mesh.applyBoneTransform(1, v1posed)
  q = pushOutOfCapsules([v1posed.x, v1posed.y, v1posed.z], ce.local, 1, v1)
  check('v1 on the axis end stays', vnear(q, [v1posed.x, v1posed.y, v1posed.z], 0), fmt(q))
  const swung = ce.local.map((c) => ({ ...c, a: [0.03, c.a[1], c.a[2]], b: [0.03, c.b[1], c.b[2]] }))
  q = pushOutOfCapsules([0.05, 0.5, 0], swung, 1, v0)
  check('body swung into the cloth: pushed back to its bind distance → (0.08, 0.5, 0)', vnear(q, [0.08, 0.5, 0]), fmt(q))
  gr.dispose()

  console.log('--- [11] footwear: no capsules ---')
  const { garmentCapsules, collidingGarmentMeshes } = G
  const everyRegion = ['torso', 'leg', 'arm', 'head', 'chest', 'attached_part']
    .map((region) => ({ capsule: { id: region, region } }))
  const shoeCaps = garmentCapsules('footwear', everyRegion)
  check('garmentCapsules(footwear, every region) → []', Array.isArray(shoeCaps) && shoeCaps.length === 0,
    shoeCaps.map((e) => e.capsule.region).join())
  const shod = build({ hair: false, footwear: true })
  const shoeTemplate = shod.meshes.footwear.material
  const gs = createGarmentCollision(THREE, shod.figure, payload)
  check('clothing + shoe → one entry, the clothing', gs?.entries.length === 1 && gs.entries[0].kind === 'clothing',
    gs?.entries.map((e) => e.kind).join())
  check('the shoe\'s material is never patched', shod.meshes.footwear.material === shoeTemplate)
  const colliding = collidingGarmentMeshes(shod.figure)
  check('collidingGarmentMeshes: the clothing, not the shoe', colliding.length === 1 && colliding[0] === shod.meshes.clothing,
    colliding.map((m) => m.name || m.parent?.name).join())
  gs?.dispose()
  const shoeOnly = build({ clothing: false, hair: false, footwear: true })
  check('shoe only → null (nothing to push)', createGarmentCollision(THREE, shoeOnly.figure, payload) === null)

  if (failures.length) {
    console.log(`\nFAIL — ${failures.length} check(s): ${failures.join('; ')}`)
    process.exit(1)
  }
  console.log('\nOK — garment push, shader twin, patch and binding as derived')
}

main().catch((e) => { console.error(e); process.exit(1) })
