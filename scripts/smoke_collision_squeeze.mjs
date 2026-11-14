#!/usr/bin/env node
/**
 * Smoke check for the SQUEEZE rule — `packages/scene-render/src/garmentCollision.ts`
 * (`pushOutOfCapsules(p, capsules, weight, bindP, { squeeze: true })` and its shader twin
 * `COLLIDE_GLSL_FUNCTION_SQUEEZE`, compiled under `#ifdef COLLIDE_SQUEEZE` for hair only; plan
 * `docs/superpowers/plans/2026-11-14-cross-person-collision.md` Task 3, fixture D3, spec
 * `docs/superpowers/specs/2026-11-13-cross-person-collision-design.md` "Added 2026-11-13 — squeeze rule").
 *
 * Usage: direct node call, self-bundling via esbuild (run from anywhere):
 *   node scripts/smoke_collision_squeeze.mjs
 *
 * THE RULE (radii = the bind-capped radii). S = the capsules containing p; empty → p. Per round (at most
 * SQUEEZE_ROUNDS = 3): |S| = 1 in round 1 → the exact radial push; otherwise N = unit(Σ n_i), n_i the unit vector
 * from capsule i's closest axis point to the ORIGINAL p; |Σ n_i| < SQUEEZE_MIN_N (1e-3) → the ordinary passes; t by
 * SQUEEZE_STEPS = 16 bisection steps on [0, 2·max r_S] for "p + tN is outside every capsule of S" (2·max r_S not
 * outside them all → the ordinary passes); q = p + t_hi·N. q inside capsules not in S → they join S, next round;
 * otherwise q. Without `squeeze` the push is the ordinary passes, unchanged.
 *
 * FIXTURE D3 — two vertical capsules (axes along y, y 0 → 1), the point at y = 0.5, written (x, z):
 *   T: axis x = 0, z = 0, r 0.10;   A: axis x = 0.13, z = 0, r 0.05.   Payload order T, A.
 * Bisection resolution: 2·0.1 / 2^16 = 3.05e-6 m → tolerance 1e-5 m (0.01 mm).
 *
 * [1] S1, inside both: p = (0.09, 0.02). d_T = √(0.0081 + 0.0004) = 0.092195, n_T = (0.976187, 0.216930);
 *     d_A = √(0.0016 + 0.0004) = 0.044721, n_A = (−0.894427, 0.447214). Σ = (0.081760, 0.664144),
 *     N = (0.122183, 0.992508). Exit along N: |p + tN| = 0.1 at t_T = 0.018666, |p + tN − (0.13, 0)| = 0.05 at
 *     t_A = 0.011942 → outside both first at t = 0.018666 → q = (0.092281, 0.038526): d_T = 0.100000,
 *     d_A = 0.053917.
 *     Without squeeze: pass 1 T to (0.097619, 0.021693), A (d 0.038976) to (0.088460, 0.027829); pass 2 T
 *     (d 0.092735) to (0.095390, 0.030009), A (d 0.045808) to (0.092223, 0.032756) — 2.13 mm inside T: the last
 *     applied capsule wins.
 *     Weight 0.5 on [4]'s A-only point: halfway, (0.162361, 0.5, 0.016180).
 * [2] S2, the spec's arm case: p = (0.105, 0.02), inside A only (d_A = √(0.000625 + 0.0004) = 0.032016;
 *     d_T = 0.106888). Round 1, S = {A}: radial push to q1 = (0.13, 0) + 0.05·(−0.780869, 0.624695) =
 *     (0.090957, 0.031235), d_T = 0.096170 → inside T. Round 2, S = {A, T}: n_A = (−0.780869, 0.624695),
 *     n_T = (0.982339, 0.187112), N = (0.240868, 0.970558); exit t = 0.027283 → q = (0.111572, 0.046480):
 *     d_A = 0.050000, d_T = 0.120868.
 *     Without squeeze: pass 1 A → q1; pass 2 T → q1·0.1/0.096170 = (0.094580, 0.032479), A (d 0.048064) →
 *     (0.093149, 0.033791): d_T = 0.099089 → 0.91 mm inside T.
 * [3] S3, degenerate: p = (0.09, 0). n_T = (1, 0), n_A = (−1, 0) → |Σ| = 0 < SQUEEZE_MIN_N → the ordinary passes:
 *     T to (0.1, 0), A (d 0.03) to (0.08, 0); pass 2 the same → (0.08, 0.5, 0), with or without squeeze.
 * [4] Inside one capsule only — the squeeze result is the push without squeeze:
 *     p (0, 0.5, 0.05) in T only (d_A = √(0.0169 + 0.0025) ≥ 0.05) → (0, 0.5, 0.1), d_A = 0.164012 → no
 *     second capsule;
 *     p (0.15, 0.5, 0.01) in A only: d_A = 0.022361 → (0.13, 0.5, 0) + 0.05·(0.894427, 0, 0.447214) =
 *     (0.174721, 0.5, 0.022361), d_T = 0.176135 ≥ 0.1 → no second capsule.
 *     A point in no capsule (0.3, 0.5, 0) → unchanged.
 * [5] ONE SOURCE: `COLLIDE_GLSL_FUNCTION_SQUEEZE` executed through the GLSL→JS rewrite of
 *     `smoke_garment_collision.mjs` (`glslPushToJs`, the SQUEEZE_* defines as parameters) gives the TS points
 *     of [1]–[4] to 1e-6 m; and on 3000 random points × random capsule sets of 0–20 (incl. degenerate ones,
 *     half under the bind rule — its bind point near p for half the points, 2 m away for the rest; a third of the
 *     points near an axis, a third between the axes of two capsules laid side by side) it gives the TS squeeze
 *     points to 1e-9 m, with
 *     more than 300 points where the squeeze differs from the ordinary passes (the sample exercises the rule).
 * [6] HAIR ONLY (plan R10): createGarmentCollision on a two-bone figure with a clothing and a hair garment —
 *     the hair material, its depth and its distance material compile a vertex shader WITH `COLLIDE_SQUEEZE`
 *     (the `#ifdef` block of the squeeze edition) and carry the `COLLIDE_SQUEEZE` define, cache key `|collideS`;
 *     the clothing's three have NO `COLLIDE_SQUEEZE` in the patched source, no such define, key `|collide`.
 *     `patchCollisionVertexShader(src)` without the flag is today's patch (no `COLLIDE_SQUEEZE`); with it the
 *     squeeze edition sits under `#ifdef COLLIDE_SQUEEZE`, the plain one under `#else`, idempotent.
 */
import { spawnSync } from 'child_process'
import * as fs from 'fs'
import * as path from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

async function main() {
  if (!process.env.SMOKE_BUNDLED) {
    const bundlePath = '/tmp/smoke_collision_squeeze_bundled.mjs'
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
  const { COLLISION_VERSION } = await import('../packages/scene-render/src/collision.ts')
  const { glslPushToJs } = await import('./smoke_garment_collision.mjs')
  const THREE = await import('three')
  const { pushOutOfCapsules, patchCollisionVertexShader, createGarmentCollision, COLLIDE_MAX, COLLIDE_PASSES,
    COLLIDE_EPS, COLLIDE_MIN_D, COLLIDE_GLSL_FUNCTION_SQUEEZE, SQUEEZE_ROUNDS, SQUEEZE_STEPS, SQUEEZE_MIN_N } = G

  const failures = []
  const check = (label, ok, detail = '') => {
    console.log(`  ${ok ? '✓' : '✗'} ${label}${detail ? ` — ${detail}` : ''}`)
    if (!ok) failures.push(label)
  }
  const dist = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2])
  const vnear = (a, b, eps) => Array.isArray(a) && a.length === 3 && dist(a, b) <= eps
  const fmt = (v) => `(${[...v].map((x) => +x.toFixed(6)).join(', ')})`
  const axisD = (p, x) => Math.hypot(p[0] - x, p[2])
  const T = { a: [0, 0, 0], b: [0, 1, 0], r: 0.10 }
  const A = { a: [0.13, 0, 0], b: [0.13, 1, 0], r: 0.05 }
  const caps = [T, A]
  const SQ = { squeeze: true }
  const MM = 1e-5

  check('the constants: SQUEEZE_ROUNDS 3, SQUEEZE_STEPS 16, SQUEEZE_MIN_N 1e-3',
    SQUEEZE_ROUNDS === 3 && SQUEEZE_STEPS === 16 && SQUEEZE_MIN_N === 1e-3,
    `${SQUEEZE_ROUNDS} ${SQUEEZE_STEPS} ${SQUEEZE_MIN_N}`)

  console.log('--- [1] S1: inside both ---')
  const p1 = [0.09, 0.5, 0.02]
  let q = pushOutOfCapsules(p1, caps, 1, undefined, SQ)
  check('squeeze → (0.092281, 0.5, 0.038526) ±0.01 mm', vnear(q, [0.092281, 0.5, 0.038526], MM), fmt(q))
  check('… outside both: d_T ≥ 0.1, d_A ≥ 0.05', axisD(q, 0) >= 0.1 - 1e-9 && axisD(q, 0.13) >= 0.05 - 1e-9,
    `d_T ${axisD(q, 0).toFixed(6)} d_A ${axisD(q, 0.13).toFixed(6)}`)
  q = pushOutOfCapsules(p1, caps)
  check('without squeeze → (0.092223, 0.5, 0.032756), 2.13 mm inside T', vnear(q, [0.092223, 0.5, 0.032756], MM)
    && Math.abs(0.1 - axisD(q, 0) - 0.00213) < MM, `${fmt(q)} d_T ${axisD(q, 0).toFixed(6)}`)

  console.log('--- [2] S2: the arm case (inside A only, the radial push lands in T) ---')
  const p2 = [0.105, 0.5, 0.02]
  q = pushOutOfCapsules(p2, caps, 1, undefined, SQ)
  check('squeeze → (0.111572, 0.5, 0.046480) ±0.01 mm', vnear(q, [0.111572, 0.5, 0.046480], MM), fmt(q))
  check('… d_A = 0.05, d_T = 0.120868', Math.abs(axisD(q, 0.13) - 0.05) < MM && Math.abs(axisD(q, 0) - 0.120868) < MM,
    `d_A ${axisD(q, 0.13).toFixed(6)} d_T ${axisD(q, 0).toFixed(6)}`)
  q = pushOutOfCapsules(p2, caps)
  check('without squeeze → (0.093149, 0.5, 0.033791), 0.91 mm inside T', vnear(q, [0.093149, 0.5, 0.033791], MM)
    && Math.abs(0.1 - axisD(q, 0) - 0.00091) < MM, `${fmt(q)} d_T ${axisD(q, 0).toFixed(6)}`)

  console.log('--- [3] S3: degenerate (opposite normals) ---')
  const p3 = [0.09, 0.5, 0]
  q = pushOutOfCapsules(p3, caps, 1, undefined, SQ)
  check('squeeze → the ordinary passes (0.08, 0.5, 0)', vnear(q, [0.08, 0.5, 0], 1e-9), fmt(q))
  check('… identical to the push without squeeze', dist(q, pushOutOfCapsules(p3, caps)) === 0)

  console.log('--- [4] inside one capsule only ---')
  for (const [p, want] of [[[0, 0.5, 0.05], [0, 0.5, 0.1]], [[0.15, 0.5, 0.01], [0.174721, 0.5, 0.022361]],
    [[0.3, 0.5, 0], [0.3, 0.5, 0]]]) {
    const s = pushOutOfCapsules(p, caps, 1, undefined, SQ)
    const o = pushOutOfCapsules(p, caps)
    check(`${fmt(p)} → ${fmt(want)}, identical to the push without squeeze`, vnear(s, want, 1e-6) && dist(s, o) === 0,
      `${fmt(s)} vs ${fmt(o)}`)
  }
  q = pushOutOfCapsules([0.15, 0.5, 0.01], caps, 0.5, undefined, SQ)
  check('weight 0.5 blends the squeezed point like the plain one', vnear(q, [0.162361, 0.5, 0.016180], 1e-6), fmt(q))

  console.log('--- [5] ONE SOURCE: the squeeze shader text executed ---')
  const defines = { COLLIDE_MAX, COLLIDE_PASSES, COLLIDE_EPS, COLLIDE_MIN_D, SQUEEZE_ROUNDS, SQUEEZE_STEPS, SQUEEZE_MIN_N }
  const factory = glslPushToJs(COLLIDE_GLSL_FUNCTION_SQUEEZE, defines)
  const glslPush = (p, set, bindP = [0, 0, 0]) => {
    const used = set.slice(0, COLLIDE_MAX)
    const UA = used.map((c) => ({ x: c.a[0], y: c.a[1], z: c.a[2], w: c.r }))
    const UB = used.map((c) => ({ x: c.b[0], y: c.b[1], z: c.b[2], w: 0 }))
    const BA = used.map((c) => (c.bind ? { x: c.bind.a[0], y: c.bind.a[1], z: c.bind.a[2], w: 0 } : { x: 0, y: 0, z: 0, w: -1 }))
    const BB = used.map((c) => (c.bind ? { x: c.bind.b[0], y: c.bind.b[1], z: c.bind.b[2], w: 0 } : { x: 0, y: 0, z: 0, w: 0 }))
    return factory(...Object.values(defines), UA, UB, BA, BB, used.length, { x: bindP[0], y: bindP[1], z: bindP[2] },
      (v, lo, hi) => Math.min(hi, Math.max(lo, v)), Math.sqrt, Math.min)(p)
  }
  for (const p of [p1, p2, p3, [0, 0.5, 0.05], [0.15, 0.5, 0.01], [0.3, 0.5, 0]]) {
    const g = glslPush(p, caps), t = pushOutOfCapsules(p, caps, 1, undefined, SQ)
    check(`GLSL = TS at ${fmt(p)}`, vnear(g, t, 1e-6), `${fmt(g)} vs ${fmt(t)}`)
  }
  let seed = 4242
  const rnd = () => { seed = (seed * 1103515245 + 12345) % 2147483648; return seed / 2147483648 }
  const jitter = (v, s) => v.map((x) => x + (rnd() - 0.5) * s)
  let worst = 0, squeezed = 0
  for (let n = 0; n < 3000; n++) {
    const count = Math.floor(rnd() * 21)
    const set = Array.from({ length: count }, () => {
      const a = [rnd() - 0.5, rnd() * 2, rnd() - 0.5]
      const b = rnd() < 0.15 ? [...a] : [a[0] + (rnd() - 0.5) * 0.6, a[1] + (rnd() - 0.5) * 0.6, a[2] + (rnd() - 0.5) * 0.6]
      const c = { a, b, r: 0.02 + rnd() * 0.2 }
      if (rnd() < 0.5) c.bind = { a: jitter(a, 0.1), b: jitter(b, 0.1) }
      return c
    })
    // a third free, a third near one capsule's axis, a third squeezed: a second capsule laid beside the first
    // (its axis shifted by 0.5–1.3 r sideways) and the point between the two axes
    const kind = count ? Math.floor(rnd() * 3) : 0
    const i0 = Math.floor(rnd() * count), c0 = set[i0]
    const u = rnd(), axisPoint = c0 ? c0.a.map((v, i) => v + (c0.b[i] - v) * u) : null
    let p
    if (kind === 0) p = [rnd() - 0.5, rnd() * 2, rnd() - 0.5]
    else if (kind === 1 || count < 2) p = jitter(axisPoint, 0.2)
    else {
      const dir = jitter([0, 0, 0], 2), len = Math.hypot(...dir) || 1
      const off = dir.map((v) => (v / len) * c0.r * (0.5 + rnd() * 0.8))
      set[(i0 + 1 + Math.floor(rnd() * (count - 1))) % count] = { a: c0.a.map((v, i) => v + off[i]),
        b: c0.b.map((v, i) => v + off[i]), r: 0.02 + rnd() * 0.2 }
      const f = 0.3 + rnd() * 0.4
      p = jitter(axisPoint.map((v, i) => v + off[i] * f), 0.02)
    }
    // half the bind points near p (the bind rule caps the radii), half 2 m away (it caps nothing)
    const bindP = rnd() < 0.5 ? jitter(p, 0.15) : [p[0] + 2, p[1], p[2]]
    const ts = pushOutOfCapsules(p, set, 1, bindP, SQ)
    worst = Math.max(worst, dist(glslPush(p, set, bindP), ts))
    if (dist(ts, pushOutOfCapsules(p, set, 1, bindP)) > 1e-9) squeezed++
  }
  check('GLSL text and TS squeeze agree on 3000 random points (≤ 1e-9 m)', worst <= 1e-9, `worst ${worst}`)
  check('the sample exercises the rule (> 300 points differ from the ordinary passes)', squeezed > 300, `${squeezed} differ`)

  console.log('--- [6] hair only ---')
  const plainSrc = THREE.ShaderLib.standard.vertexShader
  const plain = patchCollisionVertexShader(plainSrc)
  const sq = patchCollisionVertexShader(plainSrc, true)
  check('the plain patch has no COLLIDE_SQUEEZE', !plain.includes('COLLIDE_SQUEEZE'))
  const iIf = sq.indexOf('#ifdef COLLIDE_SQUEEZE'), iSq = sq.indexOf(COLLIDE_GLSL_FUNCTION_SQUEEZE)
  const iElse = sq.indexOf('#else', iSq), iPlain = sq.indexOf(G.COLLIDE_GLSL_FUNCTION, iElse)
  check('the squeeze patch: squeeze edition under #ifdef COLLIDE_SQUEEZE, the plain one under #else',
    iIf >= 0 && iSq > iIf && iElse > iSq && iPlain > iElse && sq.indexOf('#endif', iPlain) > iPlain)
  check('the squeeze patch defines SQUEEZE_ROUNDS / _STEPS / _MIN_N inside the #ifdef',
    sq.indexOf('#define SQUEEZE_ROUNDS 3') > iIf && sq.indexOf('#define SQUEEZE_STEPS 16') > iIf
    && sq.indexOf('#define SQUEEZE_MIN_N 0.001') > iIf && sq.indexOf('#define SQUEEZE_MIN_N') < iSq)
  check('idempotent', patchCollisionVertexShader(sq, true) === sq && patchCollisionVertexShader(plain) === plain)

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
  const body = new THREE.SkinnedMesh(geo(), new THREE.MeshStandardMaterial())
  const cloth = new THREE.SkinnedMesh(geo(), new THREE.MeshStandardMaterial())
  cloth.name = 'garment_clothing_x'
  const hair = new THREE.SkinnedMesh(geo(), new THREE.MeshStandardMaterial())
  hair.name = 'garment_hair_y'
  hair.userData.garment = { kind: 'hair', item_id: 'y', fsig: 'z' }
  figure.add(body, cloth, hair)
  figure.updateMatrixWorld(true)
  const skeleton = new THREE.Skeleton([hips, spine])
  for (const m of [body, cloth, hair]) m.bind(skeleton)
  const payload = { version: COLLISION_VERSION, capsules: [
    { id: 'torso', a: 'mixamorig:Hips', b: 'mixamorig:Spine', r: 0.1, region: 'torso' }] }
  const gc = createGarmentCollision(THREE, figure, payload)
  check('two entries: clothing, hair', gc?.entries.map((e) => e.kind).join() === 'clothing,hair',
    gc?.entries.map((e) => e.kind).join())
  const compiled = (mat) => {
    const shader = { uniforms: {}, vertexShader: THREE.ShaderLib.standard.vertexShader, fragmentShader: '' }
    mat.onBeforeCompile(shader, null)
    return shader.vertexShader
  }
  for (const [kind, mesh, want] of [['hair', hair, true], ['clothing', cloth, false]]) {
    for (const [name, mat] of [['material', mesh.material], ['depth', mesh.customDepthMaterial],
      ['distance', mesh.customDistanceMaterial]]) {
      const src = compiled(mat)
      const has = src.includes('COLLIDE_SQUEEZE') && src.includes('collidePush(')
      const define = 'COLLIDE_SQUEEZE' in (mat.defines ?? {})
      const key = mat.customProgramCacheKey()
      check(`${kind} ${name}: COLLIDE_SQUEEZE ${want ? 'in' : 'NOT in'} the patched source and defines, key |collide${want ? 'S' : ''}`,
        (want ? has && define : !src.includes('COLLIDE_SQUEEZE') && !define && src.includes('collidePush('))
        && key.endsWith(want ? '|collideS' : '|collide'), `source ${src.includes('COLLIDE_SQUEEZE')} define ${define} key …${key.slice(-10)}`)
    }
  }
  gc.dispose()

  if (failures.length) {
    console.log(`\nFAIL — ${failures.length} check(s): ${failures.join('; ')}`)
    process.exit(1)
  }
  console.log('\nOK — the squeeze rule, its shader twin and the hair-only define as derived')
}

main().catch((e) => { console.error(e); process.exit(1) })
