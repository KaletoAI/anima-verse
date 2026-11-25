/**
 * Smoke run for the part-link helpers of `frontend/src/tabs/items/itemsModel.ts` (plan-anhaenger Task 8, design G):
 * `partLinksOf`, `withLink`, `withCharm`, `withoutCharm`, `updateCharm`, `atDeg`, `MAX_CHARMS`, `isPartItem`, and how
 * `itemToDraft` / `draftToBody` carry `outfit_piece.jewellery`.
 *
 * Usage:  node scripts/smoke_part_link_model.mjs
 *         (bundles the module with esbuild — a Vite dependency, already installed; no DOM, no server, no world)
 *
 * Expected values, derived by hand from the server rules they mirror (`accessory_spec.links` / `_at` / `MAX_CHARMS`):
 *
 * [1] MAX_CHARMS = 6. atDeg: 'front' 0, 'left_hip' +90 (the body's left), 'right_hip' −90; a number is wrapped to
 *     [−180, 180): 200 → −160, −180 → −180, 180 → −180.
 * [2] partLinksOf of a belt {buckle {item_p, 50 mm}, charms [{item_q, left_hip, hang, drop 2}]} →
 *     [{role buckle, index 0, item item_p, size_mm 50, at_deg 0, mount null, drop_cm 0},
 *      {role charm, index 0, item item_q, size_mm null, at_deg 90, mount 'hang', drop_cm 2}];
 *     of a necklace {pendant {item_g}} → [{role pendant, index 0, item item_g, size_mm null, at_deg 0, mount null,
 *     drop_cm 0}]; of a necklace's `charms` (no place for them) → nothing; of no jewellery → [].
 * [3] withCharm adds {item, at: 'front', drop_cm: 0} by default and marks the draft dirty; the draft passed in is not
 *     changed; on a belt with 6 charms it returns null (refused). withCharm on a necklace → null.
 * [4] withLink(belt, 'buckle', 'item_x') → buckle {item: item_x} (a size of the old link is dropped — the new part
 *     brings its own); withLink(.., null) → buckle null. withoutCharm(belt, 0) → charms []. updateCharm(belt, 0,
 *     {at: 'right_hip'}) → charms[0].at 'right_hip', the rest kept.
 * [5] isPartItem: jewellery.kind 'charm' → true; 'belt' → false; no outfit piece → false.
 * [6] draftToBody: a part sends slots [] and its jewellery with kind 'charm'; a host sends `jewellery` only when the
 *     draft's links were edited (`jewellery_dirty`) — an untouched form never overwrites a Wardrobe change.
 */
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const SRC = join(ROOT, 'frontend/src/tabs/items/itemsModel.ts')

async function load() {
  const esbuild = await import('esbuild')
  const dir = await mkdtemp(join(tmpdir(), 'partlink-smoke-'))
  try {
    const file = join(dir, 'itemsModel.mjs')
    await esbuild.build({
      entryPoints: [SRC], outfile: file, bundle: true, format: 'esm', platform: 'neutral',
      logLevel: 'silent', absWorkingDir: ROOT,
    })
    return await import(`file://${file}`)
  } finally {
    await rm(dir, { recursive: true, force: true })
  }
}

let failed = 0
function check(label, actual, expected) {
  const ok = JSON.stringify(actual) === JSON.stringify(expected)
  console.log(`${ok ? '  OK  ' : '  FAIL'} ${label}: ${JSON.stringify(actual)}${ok ? '' : ` (expected ${JSON.stringify(expected)})`}`)
  if (!ok) failed += 1
}

const m = await load()

console.log('[1] constants and angles')
check('[1] MAX_CHARMS', m.MAX_CHARMS, 6)
check('[1] named', ['front', 'left_hip', 'right_hip'].map(m.atDeg), [0, 90, -90])
check('[1] wrapped', [200, -180, 180].map(m.atDeg), [-160, -180, -180])

const belt = (charms = [{ item: 'item_q', at: 'left_hip', mount: 'hang', drop_cm: 2 }]) => ({
  ...m.EMPTY_DRAFT, category: 'outfit_piece', slots: ['outer'],
  jewellery: { kind: 'belt', buckle: { item: 'item_p', size_mm: 50 }, charms }, jewellery_dirty: false,
})
const neck = { ...m.EMPTY_DRAFT, category: 'outfit_piece', slots: ['neck'],
  jewellery: { kind: 'necklace', pendant: { item: 'item_g' }, charms: [{ item: 'item_z', at: 'front' }] } }

console.log('[2] partLinksOf')
check('[2] belt', m.partLinksOf(belt()), [
  { role: 'buckle', index: 0, item: 'item_p', size_mm: 50, at_deg: 0, mount: null, drop_cm: 0 },
  { role: 'charm', index: 0, item: 'item_q', size_mm: null, at_deg: 90, mount: 'hang', drop_cm: 2 },
])
check('[2] necklace', m.partLinksOf(neck), [
  { role: 'pendant', index: 0, item: 'item_g', size_mm: null, at_deg: 0, mount: null, drop_cm: 0 },
])
check('[2] none', m.partLinksOf(m.EMPTY_DRAFT), [])

console.log('[3] withCharm')
const b = belt()
const b2 = m.withCharm(b, { item: 'item_r' })
check('[3] appended', b2.jewellery.charms.at(-1), { item: 'item_r', at: 'front', drop_cm: 0 })
check('[3] dirty', b2.jewellery_dirty, true)
check('[3] input unchanged', b.jewellery.charms.length, 1)
const six = belt(Array.from({ length: 6 }, (_, i) => ({ item: `item_c${i}`, at: 'front' })))
check('[3] 7th refused', m.withCharm(six, { item: 'item_r' }), null)
check('[3] necklace refused', m.withCharm(neck, { item: 'item_r' }), null)

console.log('[4] withLink / withoutCharm / updateCharm')
check('[4] new buckle', m.withLink(belt(), 'buckle', 'item_x').jewellery.buckle, { item: 'item_x' })
check('[4] no buckle', m.withLink(belt(), 'buckle', null).jewellery.buckle, null)
check('[4] charm removed', m.withoutCharm(belt(), 0).jewellery.charms, [])
check('[4] charm moved', m.updateCharm(belt(), 0, { at: 'right_hip' }).jewellery.charms[0],
  { item: 'item_q', at: 'right_hip', mount: 'hang', drop_cm: 2 })

console.log('[5] isPartItem')
check('[5] charm', m.isPartItem({ id: 'a', outfit_piece: { slots: [], jewellery: { kind: 'charm' } } }), true)
check('[5] belt', m.isPartItem({ id: 'a', outfit_piece: { slots: ['outer'], jewellery: { kind: 'belt' } } }), false)
check('[5] plain', m.isPartItem({ id: 'a' }), false)

console.log('[6] draftToBody')
const part = m.itemToDraft({ id: 'item_p', category: 'outfit_piece',
  outfit_piece: { slots: [], jewellery: { kind: 'charm', charm: { size_mm: 50, mount: 'flat', flip: false } } } })
check('[6] part flag', part.is_part, true)
const pb = m.draftToBody(part).outfit_piece
check('[6] part body', [pb.slots, pb.jewellery.kind, pb.jewellery.charm.size_mm], [[], 'charm', 50])
check('[6] host untouched', 'jewellery' in m.draftToBody(belt()).outfit_piece, false)
check('[6] host edited', m.draftToBody(m.withLink(belt(), 'buckle', null)).outfit_piece.jewellery.buckle, null)

if (failed) {
  console.log(`\n${failed} check(s) failed`)
  process.exit(1)
}
console.log('\nall checks passed')
