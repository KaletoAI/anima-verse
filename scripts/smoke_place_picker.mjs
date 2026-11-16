/**
 * The place preview's prop picker and Fill all (Ruling A110b, frontend/src/tabs/poses/placePicker.ts), pinned by
 * hand:
 *
 *   props: chair [seat] · sofa [seat, lie] · bed [lie] · post [stand] · rug [ground]
 *   groupProps(want "lie")  → lie first (bed, "sofa (+seat)"), then catalog order stand (post), seat
 *                             (chair, "sofa (+lie)"), ground (rug)
 *   groupProps(want "")     → stand, seat, ground, lie
 *   preselect: memo "bed" kept · memo gone + want seat → chair (first under Seat, alphabetical) · want ground with no
 *              memo → rug · want "kneel" (an added type no prop has) → the first prop at all (post), only stand/ground
 *              clips fall to the bare floor · stand clip, only a chair → bare floor · memo "__ground__" kept
 *   groundRoom("seat", 2): marker type ground (a seat is no floor type), capacity 2, no spacing/axis sent
 *   groundRoom("stand", 1): type stand, no capacity key (1 = the marker itself); count 9 clamps to 4
 *   planFill, places A,B (marker m1, seat) C (m2, lie):
 *     names null                         → loading
 *     no places                          → no_places
 *     want "stand"                       → no_type (a seat or lie place is never filled with a stand clip)
 *     want seat, solo, all               → A, B filled, count 2
 *     want seat, solo, first only        → A only
 *     want seat, pair (a, b)             → A=a, B=b, count 2
 *     want lie, pair (a, b)              → too_few_slots (m2 has 1 slot)
 *     want seat, solo, all, max 1        → count 1
 *     names [Kira, mannequin], 2 places  → A Kira, B mannequin (in order, cycling)
 *
 * Usage: node scripts/smoke_place_picker.mjs   (no server, no world; bundles the module with esbuild)
 */
import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '..')
let failures = 0
const check = (label, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want)
  console.log(`  ${ok ? 'OK  ' : 'FAIL'} ${label}${ok ? '' : ` — got ${JSON.stringify(got)}, want ${JSON.stringify(want)}`}`)
  if (!ok) failures++
}
const dir = await mkdtemp(join(tmpdir(), 'place-picker-'))
try {
  const esbuild = await import(join(ROOT, 'node_modules/esbuild/lib/main.js'))
  const built = await esbuild.build({
    entryPoints: [join(ROOT, 'frontend/src/tabs/poses/placePicker.ts')],
    bundle: true, platform: 'node', format: 'esm', write: false, logLevel: 'error',
  })
  const file = join(dir, 'picker.mjs')
  await writeFile(file, built.outputFiles[0].text, 'utf8')
  const P = await import(`file://${file}`)

  const props = [
    { id: 'chair', marker_groups: ['seat'] }, { id: 'sofa', marker_groups: ['seat', 'lie'] },
    { id: 'bed', marker_groups: ['lie'] }, { id: 'post', marker_groups: ['stand'] }, { id: 'rug', marker_groups: ['ground'] },
  ]
  const flat = (gs) => gs.map((g) => [g.type, g.props.map((p) => p.label)])
  console.log('[1] grouping')
  check('want lie', flat(P.groupProps(props, 'lie')),
    [['lie', ['bed', 'sofa (+seat)']], ['stand', ['post']], ['seat', ['chair', 'sofa (+lie)']], ['ground', ['rug']]])
  check('want none', P.groupProps(props, '').map((g) => g.type), ['stand', 'seat', 'ground', 'lie'])
  console.log('[2] preselect')
  const g = (w) => P.groupProps(props, w)
  check('memo kept', P.preselectProp(g('seat'), 'seat', 'bed'), 'bed')
  check('memo gone, seat', P.preselectProp(g('seat'), 'seat', 'gone'), 'chair')
  check('ground', P.preselectProp(g('ground'), 'ground', ''), 'rug')
  check('unknown type', P.preselectProp(g('kneel'), 'kneel', ''), 'post')
  check('stand without stand prop → floor', P.preselectProp(P.groupProps([props[0]], 'stand'), 'stand', ''), '__ground__')
  check('memo floor kept', P.preselectProp(g('seat'), 'seat', '__ground__'), '__ground__')
  console.log('[3] ground room')
  check('seat clip ×2', P.groundRoom('seat', 2).layout.markers, [{ id: 'floor', group: 'ground', at: [3, 3], rotation: 0, capacity: 2 }])
  check('stand ×1', P.groundRoom('stand', 1).layout.markers, [{ id: 'floor', group: 'stand', at: [3, 3], rotation: 0 }])
  check('clamp 9 → 4', P.groundRoom('ground', 9).layout.markers[0].capacity, 4)
  console.log('[4] fill')
  const places = [{ letter: 'A', markerId: 'm1', group: 'seat' }, { letter: 'B', markerId: 'm1', group: 'seat' },
    { letter: 'C', markerId: 'm2', group: 'lie' }]
  const fill = (o) => P.planFill(o.places ?? places, { names: ['X'], want: 'seat', roles: [''], all: true, max: 6, ...o })
  const brief = (r) => [Object.keys(r.assign), r.count, r.reason]
  check('loading', brief(fill({ names: null })), [[], 0, 'loading'])
  check('no places', brief(fill({ places: [] })), [[], 0, 'no_places'])
  check('no type', brief(fill({ want: 'stand' })), [[], 0, 'no_type'])
  check('seat all', brief(fill({})), [['A', 'B'], 2, ''])
  check('seat first', brief(fill({ all: false })), [['A'], 1, ''])
  const pair = fill({ roles: ['a', 'b'] })
  check('seat pair', [pair.assign.A.role, pair.assign.B.role, pair.count], ['a', 'b', 2])
  check('lie pair', brief(fill({ want: 'lie', roles: ['a', 'b'] })), [[], 0, 'too_few_slots'])
  check('max 1', fill({ max: 1 }).count, 1)
  const names = fill({ names: ['Kira', '__mannequin__'] })
  check('names cycle', [names.assign.A.character, names.assign.B.character], ['Kira', '__mannequin__'])
} finally {
  await rm(dir, { recursive: true, force: true })
}
if (failures) { console.log(`FAILED: ${failures}`); process.exit(1) }
console.log('OK')
