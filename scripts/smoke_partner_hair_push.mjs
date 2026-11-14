#!/usr/bin/env node
/**
 * Hair meshes and strand hair pushed out of PARTNER capsules — `packages/scene-render/src/garmentCollision.ts`
 * (`pushOutOfCapsules(…, { partners })`, its shader twin `COLLIDE_GLSL_FUNCTION_SQUEEZE_PARTNER` under
 * `#ifdef COLLIDE_PARTNER`, `GarmentCollision.setPartners`) and `packages/scene-render/src/hairSim.ts`
 * (`StrandHair.setPartners`); plan `docs/superpowers/plans/2026-11-14-cross-person-collision.md` Task 6,
 * derivation D7; spec `docs/superpowers/specs/2026-11-13-cross-person-collision-design.md` Parts 2–3.
 * Hand-derived; every number below comes from the geometry, not from a recorded run.
 *
 * Usage: node scripts/smoke_partner_hair_push.mjs   (no server, no world; bundles itself with esbuild, three in node)
 *
 * THE RULE. Partner capsules carry no bind rule. A partner capsule's radius is fixed per vertex from the point the
 * push starts with: d0 its distance from the axis, depth = r − d0, f = clamp((1.5·M − depth) / (0.5·M), 0, 1) with
 * M = PARTNER_PUSH_MAX_M = 0.04, r' = d0 + depth·f (f = 0: the capsule is left out, r' = 0). Per pass the partner
 * capsules come first, then the own ones (the own body has the last word); the squeeze sets hold both lists.
 *
 * [1] D7, a partner sphere (a = b = origin) of r 0.10, no own capsule, the point on +x:
 *     d 0.08: depth 0.02 ≤ M → f = (0.06 − 0.02)/0.02 = 2 → 1, r' = 0.10 → (0.10, 0, 0);
 *     d 0.05: depth 0.05 → f = (0.06 − 0.05)/0.02 = 0.5, r' = 0.05 + 0.025 = 0.075 → (0.075, 0, 0) — the second pass
 *       finds it ON r' and leaves it there (r' is fixed from the starting point);
 *     d 0.03: depth 0.07 ≥ 1.5·M → f = 0 → stays at (0.03, 0, 0).
 *     The same with squeeze (one capsule: the exact radial push to r'), and the GLSL text (the partner edition,
 *     executed through `glslPushToJs` of `smoke_garment_collision.mjs`) gives the same three points.
 * [2] OWN WINS: own sphere at (0.2, 0, 0), r 0.12; partner sphere at the origin, r 0.10; p (0.09, 0, 0). Partner:
 *     d0 0.09, depth 0.01 → r' = 0.10. Pass 1: partner → (0.10, 0, 0), own (d 0.10 < 0.12) → (0.08, 0, 0); pass 2
 *     the same → (0.08, 0, 0). With squeeze: both contain p, n_partner = +x, n_own = −x, |Σ| = 0 < SQUEEZE_MIN_N →
 *     the ordinary passes → (0.08, 0, 0) (degenerate). GLSL the same.
 * [3] THE UNIFORM BLOCK on a two-bone figure (Hips (0,0,0), Spine (0,1,0)) with a clothing mesh at (0.5, 0, 0) and a
 *     hair mesh at (0, 0, 0.25), both with the vertices (0.05, 0.5, 0) on Hips and (0, 1, 0) on Spine.
 *     The hair's world bounding sphere: its geometry box (0, 0.5, 0)–(0.05, 1, 0), centre (0.025, 0.75, 0), radius
 *     hypot(0.025, 0.25) = 0.251247; carried by the joint with the most skin weight (Hips and Spine tie at 1 → the
 *     first, Hips: bind→world = T(0, 0, 0.25) at the bind pose) → centre (0.025, 0.75, 0.25), r 0.251247.
 *     12 partner spheres (r 0.01) at centre + (0.30 + 0.05·k, 0, 0), handed in the order k = 11, 3, 7, 0, 9, 5, 1,
 *     10, 2, 8, 6, 4: `nearestCapsules` ranks them by 0.29 + 0.05·k → the uniform holds k = 0..7 in that order,
 *     partnerCount 8; in the mesh's frame (world − (0, 0, 0.25)) partnerA[i] = (0.325 + 0.05·i, 0.75, 0, 0.01).
 *     setPartners(the first three handed: k 11, 3, 7) → partnerCount 3, partnerA[0..2] x = 0.475, 0.675, 0.875.
 *     No recompile: the material's `version`, its defines and its program cache key stay the same throughout.
 *     setPartners(null) → partnerCount 0.
 * [4] CLOTH: the clothing material, depth and distance material carry no COLLIDE_PARTNER define and compile no
 *     partner uniform; setPartners changes none of its uniforms. The hair's three carry the define and compile the
 *     partner block (`partnerA`, `partnerB`, `partnerCount`). `patchCollisionVertexShader(src, true)` names no
 *     COLLIDE_PARTNER; `(src, true, true)` puts the partner declarations under `#ifdef COLLIDE_PARTNER` and the
 *     partner edition inside the squeeze block; idempotent.
 * [5] DISPOSE: the handle disposes exactly the six clones it made (hair and clothing: material, depth, distance —
 *     the hair's three are the ones holding the partner uniforms), never a template material; the hair wears its
 *     template again (no COLLIDE_PARTNER), `entries` is empty, and setPartners afterwards touches nothing.
 * [6] STRAND HAIR (Ruling R1), the fixture of `smoke_strand_hair_handle.mjs`: two cards of 17 rows hanging at
 *     x = ∓0.03, z = −0.10, row i at y 1.60 − 0.02·i, rows 0–1 pinned; own colliders ['torso']. A partner sphere
 *     (a = b) at (0, 1.36, −0.065), r 0.06 — between the cards and the body. Rows at y 1.38 / 1.36 / 1.34 lie
 *     hypot(0.03, 0.035, 0.02 | 0 | 0.02) = 0.0503 / 0.0461 / 0.0503 from its centre → 9.7 / 13.9 / 9.7 mm inside;
 *     y 1.40 / 1.32 lie hypot(0.0461, 0.04) = 0.0610 → outside. Without partners the rows rest on their targets
 *     (the fixture at rest), so after 30 steps the row at y 1.36 is still 13.9 mm inside (> 5 mm). With
 *     setPartners([sphere]) every row but the pinned ones lies at least 0.06 − 0.1 mm from the centre after 30
 *     updates of 1/60 s.
 */
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { existsSync } from 'node:fs'
import path from 'node:path'
import assert from 'node:assert/strict'

if (!process.env.PARTNER_HAIR_PUSH_BUNDLED) {
  const here = fileURLToPath(import.meta.url)
  const repo = path.resolve(path.dirname(here), '..')
  const bin = ['client3d/node_modules/esbuild/bin/esbuild', 'node_modules/esbuild/bin/esbuild']
    .map(rel => path.join(repo, rel)).find(existsSync)
  assert.ok(bin, 'esbuild unavailable (npm install) — nothing was checked')
  const out = `/tmp/smoke_partner_hair_push.${process.pid}.mjs`
  const built = spawnSync(bin, [here, '--bundle', '--platform=node', '--format=esm', `--outfile=${out}`,
    '--log-level=error'], { stdio: 'inherit', env: { ...process.env, NODE_PATH: path.join(repo, 'node_modules') } })
  assert.equal(built.status, 0)
  const run = spawnSync('node', [out], { stdio: 'inherit', env: { ...process.env, PARTNER_HAIR_PUSH_BUNDLED: '1' } })
  spawnSync('rm', ['-f', out])
  process.exit(run.status ?? 1)
}

const THREE = await import('three')
const G = await import('../packages/scene-render/src/garmentCollision.ts')
const { COLLISION_VERSION } = await import('../packages/scene-render/src/collision.ts')
const { nearestCapsules, PARTNER_COLLIDE_MAX, PARTNER_PUSH_MAX_M } = await import('../packages/scene-render/src/partnerContact.ts')
const { createStrandHair } = await import('../packages/scene-render/src/hairSim.ts')
const { STRAND_ROWS } = await import('../packages/scene-render/src/hairSimMath.ts')
const { glslPushToJs } = await import('./smoke_garment_collision.mjs')
const { pushOutOfCapsules, patchCollisionVertexShader, createGarmentCollision, COLLIDE_MAX, COLLIDE_PASSES,
  COLLIDE_EPS, COLLIDE_MIN_D, SQUEEZE_ROUNDS, SQUEEZE_STEPS, SQUEEZE_MIN_N } = G

let failures = 0
const check = (label, ok, detail = '') => {
  console.log(`${ok ? 'OK  ' : 'FAIL'} ${label}${detail ? ` — ${detail}` : ''}`)
  if (!ok) failures++
}
const near = (a, b, eps = 1e-6) => Math.abs(a - b) <= eps
const vnear = (a, b, eps = 1e-6) => a.length === 3 && b.length === 3 && a.every((v, i) => near(v, b[i], eps))
const fmt = v => `(${[...v].map(x => +x.toFixed(7)).join(', ')})`
const sphere = (c, r) => ({ a: [...c], b: [...c], r })
const SQ = { squeeze: true }

check('[0] PARTNER_COLLIDE_MAX 8, PARTNER_PUSH_MAX_M 0.04', PARTNER_COLLIDE_MAX === 8 && PARTNER_PUSH_MAX_M === 0.04)

// The partner edition of the shader, executed (the GLSL→JS rewrite of smoke_garment_collision.mjs).
const glslFn = G.COLLIDE_GLSL_FUNCTION_SQUEEZE_PARTNER
const defines = { COLLIDE_MAX, COLLIDE_PASSES, COLLIDE_EPS, COLLIDE_MIN_D, SQUEEZE_ROUNDS, SQUEEZE_STEPS, SQUEEZE_MIN_N,
  PARTNER_COLLIDE_MAX, COLLIDE_PARTNER_PUSH_MAX: PARTNER_PUSH_MAX_M }
const factory = typeof glslFn === 'string' ? glslPushToJs(glslFn, defines) : null
const glslPush = (p, own, partners) => {
  const used = own.slice(0, COLLIDE_MAX), pu = partners.slice(0, PARTNER_COLLIDE_MAX)
  const v4 = (v, w) => ({ x: v[0], y: v[1], z: v[2], w })
  return factory(...Object.values(defines), used.map(c => v4(c.a, c.r)), used.map(c => v4(c.b, 0)),
    used.map(() => v4([0, 0, 0], -1)), used.map(() => v4([0, 0, 0], 0)), used.length, { x: 0, y: 0, z: 0 },
    (v, lo, hi) => Math.min(hi, Math.max(lo, v)), Math.sqrt, Math.min,
    pu.map(c => v4(c.a, c.r)), pu.map(c => v4(c.b, 0)), pu.length)(p)
}

console.log('--- [1] D7 fade ---')
{
  const P = sphere([0, 0, 0], 0.10)
  for (const [x, want] of [[0.08, 0.10], [0.05, 0.075], [0.03, 0.03]]) {
    const ts = pushOutOfCapsules([x, 0, 0], [], 1, undefined, { partners: [P] })
    const tq = pushOutOfCapsules([x, 0, 0], [], 1, undefined, { squeeze: true, partners: [P] })
    check(`d ${x} → (${want}, 0, 0) (TS passes / squeeze)`, vnear(ts, [want, 0, 0], 1e-9) && vnear(tq, [want, 0, 0], 1e-9),
      `${fmt(ts)} / ${fmt(tq)}`)
    const g = factory ? glslPush([x, 0, 0], [], [P]) : [NaN, NaN, NaN]
    check(`d ${x} → (${want}, 0, 0) (the GLSL partner edition)`, vnear(g, [want, 0, 0], 1e-9), fmt(g))
  }
}

console.log('--- [2] own wins ---')
{
  const own = [sphere([0.2, 0, 0], 0.12)], P = [sphere([0, 0, 0], 0.10)]
  const a = pushOutOfCapsules([0.09, 0, 0], own, 1, undefined, { partners: P })
  const b = pushOutOfCapsules([0.09, 0, 0], own, 1, undefined, { squeeze: true, partners: P })
  const g = factory ? glslPush([0.09, 0, 0], own, P) : [NaN, NaN, NaN]
  check('(0.09, 0, 0) → (0.08, 0, 0) without squeeze', vnear(a, [0.08, 0, 0], 1e-9), fmt(a))
  check('(0.09, 0, 0) → (0.08, 0, 0) with squeeze (degenerate)', vnear(b, [0.08, 0, 0], 1e-9), fmt(b))
  check('(0.09, 0, 0) → (0.08, 0, 0) in the GLSL partner edition', vnear(g, [0.08, 0, 0], 1e-9), fmt(g))
}

// --- the figure of [3]–[5] ---------------------------------------------------------------------------------------
function build() {
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
  cloth.position.set(0.5, 0, 0)
  const hair = new THREE.SkinnedMesh(geo(), new THREE.MeshStandardMaterial())
  hair.name = 'garment_hair_y'
  hair.userData.garment = { kind: 'hair', item_id: 'y', fsig: 'z' }
  hair.position.set(0, 0, 0.25)
  figure.add(body, cloth, hair)
  figure.updateMatrixWorld(true)
  const skeleton = new THREE.Skeleton([hips, spine])
  for (const m of [body, cloth, hair]) m.bind(skeleton)
  return { figure, hips, spine, cloth, hair }
}
const payload = { version: COLLISION_VERSION, capsules: [
  { id: 'torso', a: 'mixamorig:Hips', b: 'mixamorig:Spine', r: 0.1, region: 'torso' },
  { id: 'sleeve', a: 'mixamorig:Hips', b: 'mixamorig:Spine', r: 0.2, region: 'arm' }] }
const compiled = (mat) => {
  const shader = { uniforms: {}, vertexShader: THREE.ShaderLib.standard.vertexShader, fragmentShader: '' }
  mat.onBeforeCompile(shader, null)
  return shader
}
const fakeRenderer = (frame) => ({ info: { render: { frame } } })

const fig = build()
const templates = { hair: fig.hair.material, cloth: fig.cloth.material }
const gc = createGarmentCollision(THREE, fig.figure, payload)
const hairEntry = gc?.entries.find(e => e.kind === 'hair')
const clothEntry = gc?.entries.find(e => e.kind === 'clothing')

console.log('--- [3] the uniform block ---')
{
  const centre = [0.025, 0.75, 0.25]
  const s = hairEntry?.sphere
  check('hair sphere: centre (0.025, 0.75, 0.25), r 0.251247', !!s && vnear(s.c, centre, 1e-6) && near(s.r, 0.251247, 1e-6),
    s ? `${fmt(s.c)} r ${s.r}` : 'none')
  check('cloth has no sphere', clothEntry?.sphere === null, String(clothEntry?.sphere))
  const order = [11, 3, 7, 0, 9, 5, 1, 10, 2, 8, 6, 4]
  const caps = order.map(k => sphere([centre[0] + 0.30 + 0.05 * k, centre[1], centre[2]], 0.01))
  const mat = fig.hair.material
  const u = compiled(mat).uniforms
  const v0 = mat.version, key0 = mat.customProgramCacheKey(), def0 = JSON.stringify(mat.defines)
  gc.setPartners(caps)
  fig.hair.onBeforeRender(fakeRenderer(1), null, null, null, mat, null)
  const want = nearestCapsules({ c: centre, r: 0.251247 }, caps, 8)
  check('nearestCapsules picks k = 0..7', want.map(i => order[i]).join() === '0,1,2,3,4,5,6,7', want.map(i => order[i]).join())
  check('partnerCount 8', u.partnerCount?.value === 8, String(u.partnerCount?.value))
  let ok = !!u.partnerA
  for (let i = 0; ok && i < 8; i++) {
    const A = u.partnerA.value[i], B = u.partnerB.value[i]
    ok = vnear([A.x, A.y, A.z], [0.325 + 0.05 * i, 0.75, 0]) && near(A.w, 0.01) && vnear([B.x, B.y, B.z], [0.325 + 0.05 * i, 0.75, 0])
  }
  check('partnerA/B[i] = (0.325 + 0.05·i, 0.75, 0), w 0.01 — the 8 nearest, nearest first, in the mesh frame', ok)
  check('the entry lists the same 8 (mesh frame)', hairEntry?.partners?.length === 8
    && vnear(hairEntry.partners[7].a, [0.675, 0.75, 0]), String(hairEntry?.partners?.length))
  gc.setPartners(caps.slice(0, 3))
  fig.hair.onBeforeRender(fakeRenderer(2), null, null, null, mat, null)
  const xs = [0, 1, 2].map(i => u.partnerA?.value[i].x)
  check('8 → 3: partnerCount 3, x 0.475 / 0.675 / 0.875', u.partnerCount?.value === 3
    && vnear(xs, [0.475, 0.675, 0.875]), `${u.partnerCount?.value} ${fmt(xs)}`)
  check('no recompile: version, defines and program cache key unchanged', mat.version === v0
    && mat.customProgramCacheKey() === key0 && JSON.stringify(mat.defines) === def0, `${v0}→${mat.version} ${key0}`)
  gc.setPartners(null)
  gc.update()
  check('setPartners(null) → partnerCount 0', u.partnerCount?.value === 0, String(u.partnerCount?.value))
}

console.log('--- [4] cloth has no partner block ---')
{
  for (const [kind, mesh, want] of [['hair', fig.hair, true], ['clothing', fig.cloth, false]]) {
    for (const [name, mat] of [['material', mesh.material], ['depth', mesh.customDepthMaterial],
      ['distance', mesh.customDistanceMaterial]]) {
      const shader = compiled(mat)
      const define = 'COLLIDE_PARTNER' in (mat.defines ?? {})
      const block = shader.vertexShader.includes('uniform vec4 partnerA[ PARTNER_COLLIDE_MAX ];')
        && shader.vertexShader.includes('uniform int partnerCount;') && 'partnerCount' in shader.uniforms
      check(`${kind} ${name}: COLLIDE_PARTNER ${want ? 'defined, partner block compiled' : 'absent, no partner block'}`,
        want ? define && block : !define && !shader.vertexShader.includes('partner') && !('partnerCount' in shader.uniforms))
    }
  }
  const cu = compiled(fig.cloth.material).uniforms
  const snap = () => JSON.stringify([cu.collideCount.value, ...cu.collideA.value.map(v => v.toArray()),
    ...cu.collideB.value.map(v => v.toArray())])
  const before = snap()
  gc.setPartners([sphere([0.5, 0.5, 0], 0.3)])
  fig.cloth.onBeforeRender(fakeRenderer(5), null, null, null, fig.cloth.material, null)
  gc.update()
  check('cloth: setPartners changes none of its uniforms, its entry lists no partner', snap() === before
    && (clothEntry?.partners?.length ?? 0) === 0)
  gc.setPartners(null)
  const src = THREE.ShaderLib.standard.vertexShader
  const sq = patchCollisionVertexShader(src, true), sp = patchCollisionVertexShader(src, true, true)
  check('squeeze patch without partner names no COLLIDE_PARTNER', !sq.includes('COLLIDE_PARTNER') && !sq.includes('partnerA'))
  const iDecl = sp.indexOf('#ifdef COLLIDE_PARTNER'), iA = sp.indexOf('uniform vec4 partnerA[ PARTNER_COLLIDE_MAX ];')
  const iSq = sp.indexOf('#ifdef COLLIDE_SQUEEZE'), iEd = typeof glslFn === 'string' ? sp.indexOf(glslFn) : -1
  check('partner patch: declarations under #ifdef COLLIDE_PARTNER, the partner edition inside the squeeze block',
    iDecl >= 0 && iA > iDecl && iSq > iA && iEd > iSq && sp.indexOf('#define COLLIDE_PARTNER_PUSH_MAX 0.04') > iDecl
    && sp.indexOf('#define PARTNER_COLLIDE_MAX 8') > iDecl)
  check('idempotent', patchCollisionVertexShader(sp, true, true) === sp)
}

console.log('--- [5] dispose ---')
{
  const disposed = []
  for (const [kind, mesh] of [['hair', fig.hair], ['clothing', fig.cloth]]) {
    for (const [name, mat] of [['material', mesh.material], ['depth', mesh.customDepthMaterial],
      ['distance', mesh.customDistanceMaterial]]) mat.addEventListener('dispose', () => disposed.push(`${kind}.${name}`))
  }
  let templateDisposed = 0
  for (const t of Object.values(templates)) t.addEventListener('dispose', () => templateDisposed++)
  gc.setPartners([sphere([0.5, 0.75, 0.25], 0.3)])
  gc.dispose()
  check('exactly the six owned clones disposed', disposed.sort().join()
    === 'clothing.depth,clothing.distance,clothing.material,hair.depth,hair.distance,hair.material', disposed.join())
  check('no template disposed', templateDisposed === 0)
  check('hair wears its template again, no COLLIDE_PARTNER on it', fig.hair.material === templates.hair
    && !('COLLIDE_PARTNER' in (templates.hair.defines ?? {})))
  let threw = false
  try { gc.setPartners([sphere([0, 0, 0], 1)]); gc.update() } catch { threw = true }
  check('entries empty, setPartners afterwards touches nothing', gc.entries.length === 0 && !threw
    && fig.hair.material === templates.hair)
}

console.log('--- [6] strand hair ---')
{
  const R = STRAND_ROWS
  const XK = [-0.03, 0.03]
  const PARAMS = { damping: 0.04, stiffness: 1.0, bend: 0.15, iterations: 6, root_deg: 10, root_frac: 0.2,
    fly_soft: true, fly_arc: 0.30, tether: true, tether_r0: 0.015, tether_r1: 0.06, tether_head: 0.012,
    head_clr: 0.03, face_box: true }
  const record = () => {
    const rest = [], pins = [], freeArc = [], freeFrac = [], w = []
    for (let k = 0; k < 2; k++) {
      pins.push(2)
      for (let i = 0; i < R; i++) {
        rest.push(XK[k], 1.60 - 0.02 * i, -0.10)
        freeArc.push(i < 2 ? 0 : 0.02 * (i - 1))
        freeFrac.push(i < 2 ? 0 : (i - 1) / 15)
        w.push(1)
      }
    }
    return { version: 1, item_id: 'hair_fixture', fsig: '0123456789ab', mode: 'hairdeck', fit_sha256: '0',
      frame: 'head_bind', head_bone: 'mixamorig:Head', rows: R, cards: 2, rest, pins, free_arc: freeArc,
      free_frac: freeFrac, follow: { bones: ['mixamorig:Head'], w }, ear_y: 1.50,
      face_box: [-0.06, 0.06, 1.48, 1.66, 0.05], eye_box: [-0.04, 0.04, 1.55, 1.64, 0.05],
      sdf: { dims: [2, 2, 2], lo: [-0.2, 1.3, -0.2], vox: 0.4, order: 'x_fastest', unit: 'mm_int8',
        data: Buffer.from(new Int8Array(8).fill(127).buffer).toString('base64') },
      capsules: { version: COLLISION_VERSION, capsules: [
        { id: 'head', a: 'mixamorig:Neck', b: 'mixamorig:Head', r: 0.2, region: 'head' },
        { id: 'torso', a: 'mixamorig:Spine2', b: 'mixamorig:Neck', r: 0.12, region: 'torso' }], scales: {} },
      params: PARAMS, vertex_attributes: { card: '_STRAND_CARD', u: '_STRAND_U' } }
  }
  const figure = () => {
    const f = new THREE.Group()
    const bone = (name, parent, at) => {
      const b = new THREE.Bone(); b.name = name; b.position.set(...at); (parent ?? f).add(b); return b
    }
    const hips = bone('mixamorig:Hips', null, [0, 0, 0])
    const spine = bone('mixamorig:Spine2', hips, [0, 1.30, 0])
    const neck = bone('mixamorig:Neck', spine, [0, 0.15, 0])
    const head = bone('mixamorig:Head', neck, [0, 0.10, 0])
    f.updateMatrixWorld(true)
    const skeleton = new THREE.Skeleton([hips, spine, neck, head])
    const bodyGeo = new THREE.BufferGeometry()
    bodyGeo.setAttribute('position', new THREE.Float32BufferAttribute([0, 0, 0, 0.1, 0, 0, 0, 0.1, 0], 3))
    bodyGeo.setAttribute('skinIndex', new THREE.Uint16BufferAttribute(new Array(12).fill(0), 4))
    bodyGeo.setAttribute('skinWeight', new THREE.Float32BufferAttribute([1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0], 4))
    const body = new THREE.SkinnedMesh(bodyGeo, new THREE.MeshStandardMaterial())
    const pos = [], nrm = [], card = [], u = [], si = [], sw = []
    for (let k = 0; k < 2; k++) {
      for (let i = 0; i < R; i++) {
        for (const s of [-1, 1]) {
          pos.push(XK[k] + s * 0.004, 1.60 - 0.02 * i, -0.10); nrm.push(0, 0, -1)
          card.push(k + 1); u.push(i); si.push(2, 3, 0, 0); sw.push(0.5, 0.5, 0, 0)
        }
      }
    }
    for (const [x, z] of [[-0.02, -0.02], [0.02, -0.02], [0.02, 0.02], [-0.02, 0.02]]) {
      pos.push(x, 1.695, z); nrm.push(0, 1, 0); card.push(0); u.push(0); si.push(3, 0, 0, 0); sw.push(1, 0, 0, 0)
    }
    const hairGeo = new THREE.BufferGeometry()
    hairGeo.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3))
    hairGeo.setAttribute('normal', new THREE.Float32BufferAttribute(nrm, 3))
    hairGeo.setAttribute('skinIndex', new THREE.Uint16BufferAttribute(si, 4))
    hairGeo.setAttribute('skinWeight', new THREE.Float32BufferAttribute(sw, 4))
    hairGeo.setAttribute('_strand_card', new THREE.Uint16BufferAttribute(card, 1))
    hairGeo.setAttribute('_strand_u', new THREE.Float32BufferAttribute(u, 1))
    const hair = new THREE.SkinnedMesh(hairGeo, new THREE.MeshStandardMaterial())
    const garment = new THREE.Group()
    garment.name = 'garment_hair_fixture'
    garment.userData.garment = { kind: 'hair' }
    garment.add(hair)
    f.add(body, garment)
    f.updateMatrixWorld(true)
    body.bind(skeleton, body.matrixWorld)
    hair.bind(skeleton, hair.matrixWorld)
    return f
  }
  const C = [0, 1.36, -0.065], RS = 0.06
  const run = (partners) => {
    const h = createStrandHair(THREE, figure(), record())
    h.setEnabled(true)
    if (partners) h.setPartners?.(partners)
    for (let s = 0; s < 30; s++) h.update(1 / 60)
    let minD = Infinity, rowD = 0
    for (let q = 0; q < h.sim.n; q++) {
      if (h.sim.pin[q]) continue
      const o = 3 * q, d = Math.hypot(h.sim.X[o] - C[0], h.sim.X[o + 1] - C[1], h.sim.X[o + 2] - C[2])
      minD = Math.min(minD, d)
      if (q % R === 12) rowD = Math.max(rowD, d)
    }
    h.dispose()
    return { minD, rowD, has: typeof h.setPartners === 'function' }
  }
  const without = run(null)
  check('without partners: the row at y 1.36 stays 13.9 mm inside', near(without.rowD, 0.0461, 2e-4)
    && RS - without.minD > 0.005, `row ${without.rowD.toFixed(5)} min ${without.minD.toFixed(5)}`)
  const withP = run([sphere(C, RS)])
  check('StrandHair.setPartners exists', withP.has)
  check('with setPartners([sphere]): every free row ≥ 0.06 − 0.1 mm from the centre after 30 steps',
    withP.minD >= RS - 1e-4, `min ${withP.minD.toFixed(6)}`)
}

console.log(failures ? `\n${failures} check(s) FAILED` : '\nall checks passed')
process.exit(failures ? 1 : 0)
