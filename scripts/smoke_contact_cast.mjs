#!/usr/bin/env node
/**
 * Owner 2026-11-25 ("einmal automatisch durchgehen und speichern"): the pure parts of the one-click "Store contact
 * heights" — `frontend/src/tabs/poses/contactCast.ts`. Every expected value is derived BY HAND below (§ B5a).
 *
 * Usage: node scripts/smoke_contact_cast.mjs   (no server, no world; bundles the module with esbuild)
 *
 * [1] THE CAST ORDER. People (gender, built part ops, built channels):
 *       Anna f —            channels [mouth]                 (no channel of her own)
 *       Bea  f —            channels [mouth, pkg:ch accepts appendage_chain]
 *       Cleo f —            channels [mouth, pkg:ch accepts attached_part]
 *       Dirk m — parts [attached_part]
 *       Emil m — parts [pair_protrusion]                     (no attached part)
 *       Finn m — parts [appendage_chain]
 *     Clip roles a, b; role_gender a f, b m; relation b → a : channel.
 *       no previous cast → a: Bea (fits; Anna does not; Bea < Cleo by name), b: Dirk (fits; Dirk < Finn) — unmet {}.
 *       previous {a: Cleo, b: Finn} → a: Cleo, b: Finn (both fit; the role's previous person beats the name).
 *       previous {a: Anna, b: Emil} → a: Bea, b: Dirk (a person who meets the need beats the previous one).
 *       previous {a: Finn, b: Cleo} (persons of the previous cast in other roles) → a: Cleo, b: Finn (a person of the
 *       previous cast beats the name; the gender decides the role).
 *     Relation b → a : mouth → no need of a; a: Anna (name order), b: Dirk (part).
 *       previous {a: Cleo, b: Finn} → a: Cleo (previous, mouth needs nothing), b: Finn.
 *     Nobody with a part: people Anna, Bea, Emil; b → a : channel → a: Bea, b: Emil with unmet {b: [part]}.
 *     No woman in the pool: people Dirk, Finn; role_gender a f → a takes any person: Dirk (meets nothing a needs → unmet
 *       {a: [channel]}), b: Finn (Dirk is used).
 *     Group a f, b m, c m; relations b → a : channel, c → a : hand_left → a Bea, b Dirk, c Finn (part; Emil has none).
 * [2] impliedRelation (declared part genders [male], channel genders [female]): a f, b m → b → a : channel;
 *     a m, b f → a → b : channel; no genders and no gendered declarations → b → a.
 * [3] THE DECLARED ANCHOR on a simple posed chain. Bind joints: Hips (0, 1, 0), Head (0, 1.6, 0), LeftArm (0.2, 1.4,
 *     0), RightArm (−0.2, 1.4, 0), LeftFoot (0.1, 0.1, 0), LeftToeBase (0.1, 0, 0.1).
 *     Frame: up = unit(Head − Hips) = (0, 1, 0); side = unit(LeftArm − RightArm) = (1, 0, 0) (no part along up);
 *     front = side × up = (1,0,0) × (0,1,0) = (0, 0, 1); (LeftToeBase − LeftFoot) = (0, −0.1, 0.1), dot +0.1 → kept.
 *     The channel declaration Hips + [0, −0.11, 0.04] → bind point (0, 0.89, 0.04).
 *     POSED: the Hips joint lies down — turned +90° about X and moved to (0, 0.3, 0): world = T(0, 0.3, 0) · Rx(90°),
 *     bind inverse = T(0, −1, 0). P − Hips = (0, −0.11, 0.04); Rx(90°)(x, y, z) = (x, −z, y) = (0, −0.04, −0.11);
 *     + (0, 0.3, 0) → (0, 0.26, −0.11): the contact height is 0.26 m.
 *     STANDING (world = T(0, 1.05, 0), the hips 5 cm above their bind height): (0, 0.89 − 1 + 1.05, 0.04) =
 *     (0, 0.94, 0.04) → 0.94 m.
 *     The part anchor Hips + [0, −0.09, 0] standing: (0, 0.96, 0); its distance to the opening (0, 0.94, 0.04) is
 *     √(0.02² + 0.04²) = 0.04472136.
 *     A rig whose feet point back (LeftToeBase (0.1, 0, −0.1)) flips front to (0, 0, −1): bind point (0, 0.89, −0.04).
 *     A missing joint (no LeftToeBase) → no frame → null.
 * [4] deepestFrame: distances 0.30, 0.12, 0.05, 0.20 → index 2; no samples → −1.
 * [5] contactAnchorsOf drops an entry without a 3-number offset and keeps op / accepts / genders.
 */
import assert from 'node:assert/strict'
import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '..')
async function load() {
  const dir = await mkdtemp(join(ROOT, 'scripts/.smoke-contact-cast-'))
  try {
    const esbuild = await import(join(ROOT, 'node_modules/esbuild/lib/main.js'))
    const built = await esbuild.build({
      entryPoints: [join(ROOT, 'frontend/src/tabs/poses/contactCast.ts')],
      bundle: true, platform: 'node', format: 'esm', write: false,
      outfile: join(dir, 'cc.mjs'), external: ['three', 'three/*'], logLevel: 'error',
    })
    const file = join(dir, 'cc.mjs')
    await writeFile(file, built.outputFiles[0].text, 'utf8')
    return await import(pathToFileURL(file).href)
  } finally {
    await rm(dir, { recursive: true, force: true })
  }
}
const M = await load()
let n = 0
const ok = (label) => { n++; console.log('  ok', label) }
const near = (got, want, label, eps = 1e-9) => got.forEach((v, i) => assert.ok(Math.abs(v - want[i]) <= eps, `${label}: ${got} vs ${want}`))

// [1]
const ch = (id, ops) => ({ id, accepts: ops })
const P = {
  Anna: { name: 'Anna', gender: 'female', parts: [], channels: [ch('mouth', ['attached_part', 'appendage_chain'])] },
  Bea: { name: 'Bea', gender: 'female', parts: [], channels: [ch('mouth', ['attached_part']), ch('pkg:ch', ['appendage_chain'])] },
  Cleo: { name: 'Cleo', gender: 'female', parts: [], channels: [ch('mouth', ['attached_part']), ch('pkg:ch', ['attached_part'])] },
  Dirk: { name: 'Dirk', gender: 'male', parts: ['attached_part'], channels: [] },
  Emil: { name: 'Emil', gender: 'male', parts: ['pair_protrusion'], channels: [] },
  Finn: { name: 'Finn', gender: 'male', parts: ['appendage_chain'], channels: [] },
}
const all = Object.values(P)
const RG = { a: 'female', b: 'male' }
const C = (relations, previous, people = all, roles = ['a', 'b'], roleGender = RG) =>
  M.chooseContactCast({ roles, roleGender, relations, people, previous })
const chan = [{ part: 'b', at: 'a', target: 'channel' }]
assert.deepEqual(C(chan), { byRole: { a: 'Bea', b: 'Dirk' }, unmet: {} })
assert.deepEqual(C(chan, { a: 'Cleo', b: 'Finn' }).byRole, { a: 'Cleo', b: 'Finn' })
assert.deepEqual(C(chan, { a: 'Anna', b: 'Emil' }).byRole, { a: 'Bea', b: 'Dirk' })
assert.deepEqual(C(chan, { a: 'Finn', b: 'Cleo' }).byRole, { a: 'Cleo', b: 'Finn' })
const mouth = [{ part: 'b', at: 'a', target: 'mouth' }]
assert.deepEqual(C(mouth).byRole, { a: 'Anna', b: 'Dirk' })
assert.deepEqual(C(mouth, { a: 'Cleo', b: 'Finn' }).byRole, { a: 'Cleo', b: 'Finn' })
assert.deepEqual(C(chan, undefined, [P.Anna, P.Bea, P.Emil]), { byRole: { a: 'Bea', b: 'Emil' }, unmet: { b: ['part'] } })
assert.deepEqual(C(chan, undefined, [P.Dirk, P.Finn]), { byRole: { a: 'Dirk', b: 'Finn' }, unmet: { a: ['channel'] } })
assert.deepEqual(C([...chan, { part: 'c', at: 'a', target: 'hand_left' }], undefined, all, ['a', 'b', 'c'],
  { a: 'female', b: 'male', c: 'male' }).byRole, { a: 'Bea', b: 'Dirk', c: 'Finn' })
ok('[1] the cast: needs first, then the previous cast, then the name; unmet needs listed')

// [2]
const anchors = { parts: [{ id: 'p', bone: 'Hips', offset: [0, -0.09, 0], genders: ['male'] }],
  channels: [{ id: 'c', bone: 'Hips', offset: [0, -0.11, 0.04], genders: ['female'] }] }
assert.deepEqual(M.impliedRelation(['a', 'b'], { a: 'female', b: 'male' }, anchors), { part: 'b', at: 'a', target: 'channel' })
assert.deepEqual(M.impliedRelation(['a', 'b'], { a: 'male', b: 'female' }, anchors), { part: 'a', at: 'b', target: 'channel' })
assert.deepEqual(M.impliedRelation(['a', 'b'], {}, anchors), { part: 'b', at: 'a', target: 'channel' })
ok('[2] impliedRelation by the declarations\' genders, else B → A')

// [3]
const J = { 'mixamorig:Hips': [0, 1, 0], 'mixamorig:Head': [0, 1.6, 0], 'mixamorig:LeftArm': [0.2, 1.4, 0],
  'mixamorig:RightArm': [-0.2, 1.4, 0], 'mixamorig:LeftFoot': [0.1, 0.1, 0], 'mixamorig:LeftToeBase': [0.1, 0, 0.1] }
const fr = M.bodyFrameOf(J)
near(fr.up, [0, 1, 0], 'up'); near(fr.side, [1, 0, 0], 'side'); near(fr.front, [0, 0, 1], 'front')
const bindP = M.declaredPoint(J, 'Hips', [0, -0.11, 0.04])
near(bindP, [0, 0.89, 0.04], 'bind point')
// column-major: T(0,0.3,0)·Rx(90°): columns x (1,0,0), y (0,0,1) [cos 90 = 0, sin 90 = 1], z (0,−1,0), t (0,0.3,0)
const lying = [1, 0, 0, 0, 0, 0, 1, 0, 0, -1, 0, 0, 0, 0.3, 0, 1]
const inv = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, -1, 0, 1]
near(M.posedPoint(lying, inv, bindP), [0, 0.26, -0.11], 'lying', 1e-12)
const standing = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 1.05, 0, 1]
const open = M.posedPoint(standing, inv, bindP)
near(open, [0, 0.94, 0.04], 'standing', 1e-12)
const part = M.posedPoint(standing, inv, M.declaredPoint(J, 'Hips', [0, -0.09, 0]))
near(part, [0, 0.96, 0], 'part anchor', 1e-12)
assert.ok(Math.abs(Math.hypot(part[0] - open[0], part[1] - open[1], part[2] - open[2]) - 0.04472136) < 1e-8)
near(M.declaredPoint({ ...J, 'mixamorig:LeftToeBase': [0.1, 0, -0.1] }, 'Hips', [0, -0.11, 0.04]), [0, 0.89, -0.04], 'flipped front')
const { 'mixamorig:LeftToeBase': _, ...noToe } = J
assert.equal(M.declaredPoint(noToe, 'Hips', [0, -0.11, 0.04]), null)
ok('[3] the declared anchor: body frame, bind point, posed rigidly on its joint (lying 0.26 m, standing 0.94 m)')

// [4]
const s = (d) => ({ point: [0, d, 0], o: [0, 0, 0] })
assert.equal(M.deepestFrame([s(0.30), s(0.12), s(0.05), s(0.20)]), 2)
assert.equal(M.deepestFrame([]), -1)
ok('[4] deepestFrame = the closest approach')

// [5]
const w = M.contactAnchorsOf({ channels: [{ id: 'x', bone: 'Hips', offset: [0, 1] }, { id: 'c', bone: 'Hips', offset: [0, -0.11, 0.04],
  accepts: ['attached_part'], genders: ['female'] }], parts: [{ id: 'p', op: 'appendage_chain', bone: 'Hips', offset: [0, -0.09, 0], genders: null }] })
assert.deepEqual(w, { channels: [{ id: 'c', bone: 'Hips', offset: [0, -0.11, 0.04], genders: ['female'], accepts: ['attached_part'] }],
  parts: [{ id: 'p', bone: 'Hips', offset: [0, -0.09, 0], genders: null, op: 'appendage_chain' }] })
ok('[5] contactAnchorsOf')
console.log(`smoke_contact_cast: ${n} ok`)
