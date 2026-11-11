#!/usr/bin/env node
/**
 * Smoke check for the SHIPPED BARE REST of a foot pose (Task 20b) —
 * `packages/scene-render/src/footPose.ts` (`footPoseRest`), `figure.ts`
 * (`figureBox(three, root, fp)`), `clipRetarget.ts` (`restCorrections(…, fp)`,
 * `restSolesOf`) — the TypeScript twin of `scripts/smoke_foot_rest.py`.
 *
 * Usage: direct node call, self-bundling via esbuild (run from anywhere):
 *   node scripts/smoke_foot_rest.mjs
 *
 * THE FIXTURES are `scripts/fixtures/foot_rest_bare.glb` and `foot_rest_cut.glb`
 * (laid out by hand in the Python smoke's docstring: a body of ten vertices
 * on Hips / Foot / ToeBase joints, a hair garment that must never count; the
 * cut file without the five sole vertices and with two shoe nodes
 * `garment_footwear_i_<side>`, kind footwear, item_id i, fsig abc), the
 * expectations `scripts/fixtures/foot_rest_vector.json` — ONE vector for both
 * languages, which is the point: what the server now measures on the bare
 * file (Python) is what the renderers used to measure on the loaded one (TS).
 *
 * [1] BARE, measured by the TS routines: `figureBox` = vector.bare.box and
 *     `restSolesOf` = vector.bare.soles (1e-6; float32 positions): the hair
 *     garment at y 1.8 and under the sole is in neither.
 * [2] CUT, measured without a record — the finding: the floor 25 mm higher
 *     (vector.cut.box), the left soles B / D, the right side left out.
 * [3] `footPoseRest`: null for null, another version, no `rest`, a malformed
 *     box, a non-matching root (the bare file carries no shoe node); the box
 *     and soles of a well-formed record; a side with a bad triple left out.
 * [4] `figureBox(cut, fp)` with `fp.rest = vector.bare` = the BARE box exactly;
 *     a non-matching record (fsig zzz) → the cut box; a root with a world
 *     transform (translated by (1, 2, 3)) → the shipped box moved by it.
 * [5] `restCorrections(donor, bare)` with the bare fixture as its own donor
 *     fires the foot stance rule on the bare soles (mean tilt 8.148° > 6°):
 *     every bone of both foot subtrees gets an entry whose `right` factor is
 *     Rx(−tilt) — leftfoot 7.765166°, rightfoot 8.530766° about −x (the
 *     vector's `corrections_deg`); no other entry. On the CUT body without a
 *     record the pair is incomplete (no right toe) → NO entry at all; with
 *     the record the cut body's corrections equal the bare body's, entry by
 *     entry (1e-9).
 * FAILS BEFORE / PASSES AFTER: on bf0c2f78 `footPoseRest` does not exist,
 *     `figureBox` ignores the record ([4] reads the cut box) and
 *     `restCorrections` has no record to read ([5] finds no entry on the cut).
 */
import { spawnSync } from 'child_process'
import * as fs from 'fs'
import * as path from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

async function main() {
  if (!process.env.SMOKE_BUNDLED) {
    const bundlePath = '/tmp/smoke_foot_rest_bundled.mjs'
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

  globalThis.self = globalThis
  if (!globalThis.window) globalThis.window = globalThis
  if (!globalThis.document) {
    globalThis.document = { createElement: () => ({ style: {}, getContext: () => null, setAttribute() {} }) }
  }
  const THREE = await import('three')
  const { GLTFLoader } = await import('three/examples/jsm/loaders/GLTFLoader.js')
  const { figureBox } = await import('../packages/scene-render/src/figure.ts')
  const { restPoseOf, restSolesOf, restCorrections } = await import('../packages/scene-render/src/clipRetarget.ts')
  const { footPoseRest } = await import('../packages/scene-render/src/footPose.ts')

  const failures = []
  const check = (label, ok, detail = '') => {
    console.log(`  ${ok ? '✓' : '✗'} ${label}${detail ? ` — ${detail}` : ''}`)
    if (!ok) failures.push(label)
  }
  const near = (a, b, eps = 1e-6) => Math.abs(a - b) <= eps
  const nearV = (v, t, eps = 1e-6) => near(v.x, t[0], eps) && near(v.y, t[1], eps) && near(v.z, t[2], eps)
  const fmt = (v) => `(${v.toArray().map((x) => x.toFixed(4)).join(', ')})`
  const fixtures = path.join(process.cwd(), 'scripts/fixtures')   // the bundle runs from the repo root
  const vector = JSON.parse(fs.readFileSync(path.join(fixtures, 'foot_rest_vector.json'), 'utf8'))
  const ab = (b) => b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength)
  const load = async (name) => {
    const scene = (await new GLTFLoader().parseAsync(ab(fs.readFileSync(path.join(fixtures, name))), '')).scene
    scene.updateMatrixWorld(true)
    return scene
  }
  const bare = await load('foot_rest_bare.glb')
  const cut = await load('foot_rest_cut.glb')
  const fp = (rest, fsig = 'abc') => ({ version: 1, source: { item_id: 'i', fsig, glb_sha256: 'x' }, bones: {},
    root_lift_m: 0.05, contacts: { left: [], right: [] }, ...(rest ? { rest } : {}) })

  console.log('--- [1] the bare fixture through the TS routines = the vector ---')
  const bareBox = figureBox(THREE, bare)
  check('figureBox(bare) = vector.bare.box', nearV(bareBox.min, vector.bare.box.min) && nearV(bareBox.max, vector.bare.box.max),
    `${fmt(bareBox.min)} ${fmt(bareBox.max)}`)
  const bareRest = restPoseOf(THREE, bare)
  const bareSoles = restSolesOf(THREE, bare, bareRest)
  for (const side of ['left', 'right']) {
    const s = bareSoles.get(side)
    check(`restSolesOf(bare).${side} = vector`, !!s && nearV(s.heel, vector.bare.soles[side].heel) && nearV(s.toe, vector.bare.soles[side].toe),
      s ? `${fmt(s.heel)} ${fmt(s.toe)}` : 'missing')
  }

  console.log('--- [2] the cut fixture without a record — the finding ---')
  const cutBox = figureBox(THREE, cut)
  check('figureBox(cut) = vector.cut.box (floor +25 mm)', nearV(cutBox.min, vector.cut.box.min) && nearV(cutBox.max, vector.cut.box.max),
    `${fmt(cutBox.min)} ${fmt(cutBox.max)}`)
  const cutSoles = restSolesOf(THREE, cut, restPoseOf(THREE, cut))
  check('restSolesOf(cut): left B / D, right left out', cutSoles.size === 1 && !!cutSoles.get('left')
    && nearV(cutSoles.get('left').heel, vector.cut.soles.left.heel) && nearV(cutSoles.get('left').toe, vector.cut.soles.left.toe),
    `${cutSoles.size} side(s)`)

  console.log('--- [3] footPoseRest ---')
  check('null record → null', footPoseRest(THREE, null) === null)
  check('another version → null', footPoseRest(THREE, { ...fp(vector.bare), version: 2 }) === null)
  check('no rest → null', footPoseRest(THREE, fp(null)) === null)
  check('a malformed box → null', footPoseRest(THREE, fp({ box: { min: [0, 0], max: [1, 1, 1] }, soles: {} })) === null)
  check('a root without the shoe nodes → null', footPoseRest(THREE, fp(vector.bare), bare) === null)
  const parsed = footPoseRest(THREE, fp(vector.bare), cut)
  check('a matching root: the box and both soles', !!parsed && nearV(parsed.box.min, vector.bare.box.min)
    && parsed.soles.size === 2 && nearV(parsed.soles.get('right').toe, vector.bare.soles.right.toe))
  const oneBad = footPoseRest(THREE, fp({ box: vector.bare.box, soles: { left: vector.bare.soles.left, right: { heel: [0, 'x', 0], toe: [0, 0, 0] } } }))
  check('a side with a bad triple is left out', !!oneBad && oneBad.soles.size === 1 && oneBad.soles.has('left'))

  console.log('--- [4] figureBox(cut, fp) = the bare box ---')
  const shipped = figureBox(THREE, cut, fp(vector.bare))
  check('figureBox(cut, fp) = vector.bare.box', nearV(shipped.min, vector.bare.box.min, 1e-9) && nearV(shipped.max, vector.bare.box.max, 1e-9),
    `${fmt(shipped.min)} ${fmt(shipped.max)}`)
  const other = figureBox(THREE, cut, fp(vector.bare, 'zzz'))
  check('a non-matching record → the cut box', nearV(other.min, vector.cut.box.min) && nearV(other.max, vector.cut.box.max))
  const moved = await load('foot_rest_cut.glb')
  moved.position.set(1, 2, 3)
  moved.updateMatrixWorld(true)
  const movedBox = figureBox(THREE, moved, fp(vector.bare))
  check('a root translated by (1, 2, 3) → the shipped box moved by it',
    nearV(movedBox.min, [vector.bare.box.min[0] + 1, vector.bare.box.min[1] + 2, vector.bare.box.min[2] + 3], 1e-9), fmt(movedBox.min))

  console.log('--- [5] restCorrections: the foot stance on the bare soles, the cut body with and without the record ---')
  const donor = restPoseOf(THREE, bare)
  const bareCorr = restCorrections(THREE, donor, bare)
  const expectedKeys = ['leftfoot', 'lefttoebase', 'rightfoot', 'righttoebase']
  check('bare: entries for both foot subtrees only', bareCorr.size === 4 && expectedKeys.every((k) => bareCorr.has(k)),
    [...bareCorr.keys()].join(', '))
  const angleDeg = (q) => (2 * Math.acos(Math.min(1, Math.abs(q.w))) * 180) / Math.PI
  for (const [key, deg] of Object.entries(vector.corrections_deg)) {
    const e = bareCorr.get(key)
    const ok = !!e && near(angleDeg(e.right), deg, 1e-5) && e.right.x * e.right.w < 0 && near(e.right.y, 0, 1e-9) && near(e.right.z, 0, 1e-9)
    check(`bare ${key}: right = Rx(−${deg}°)`, ok, e ? `${angleDeg(e.right).toFixed(6)}°` : 'missing')
  }
  const cutCorr = restCorrections(THREE, donor, cut)
  check('cut without a record: no entry (the pair incomplete)', cutCorr.size === 0, `${cutCorr.size} entries`)
  const cutShipped = restCorrections(THREE, donor, cut, undefined, fp(vector.bare))
  let same = cutShipped.size === bareCorr.size
  for (const [k, v] of bareCorr) {
    const w = cutShipped.get(k)
    if (!w || v.left.angleTo(w.left) > 1e-9 || v.right.angleTo(w.right) > 1e-9) same = false
  }
  check('cut with the record = bare, entry by entry', same, `${cutShipped.size} entries`)
  const cutOther = restCorrections(THREE, donor, cut, undefined, fp(vector.bare, 'zzz'))
  check('cut with a non-matching record: as without', cutOther.size === 0)

  if (failures.length) {
    console.log(`\nFAIL: ${failures.length} check(s) failed`)
    process.exit(1)
  }
  console.log('\nOK: shipped bare rest — one vector for Python and TypeScript, box and soles taken from the record')
}

main().catch((err) => { console.error(err); process.exit(1) })
