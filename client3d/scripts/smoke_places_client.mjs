#!/usr/bin/env node
/**
 * Smoke check for the client's half of PLACES (plan-posen-plaetze.md § 4,
 * numbers, no screenshots — § B5a): the one pure rule the 3D client applies
 * to a seat the SERVER handed it, `client3d/src/scene/placeSlot.ts`.
 *
 * Usage:  node client3d/scripts/smoke_places_client.mjs
 *         (self-bundles through esbuild like its siblings)
 *
 * WHAT THE CLIENT DOES NOT DECIDE. A character's worldmap row carries
 * `place: {id, slot, …}`; the scene payload carries the marker's `slots[]`
 * (one world point per unit of capacity, the server's slot formula). The
 * client looks the marker up by id and takes the slot the server named —
 * it chooses nothing, and the only rules it has are the two clamps below.
 *
 * Hand-derived expectations
 * -------------------------
 * One entry with capacity 3 at anchor (−2, 0, −3), spacing 0.6 m along the
 * facing's cross axis (here z), so the server's slots are
 *
 *   slot 0: (−2, 0, −3.6)     slot 1: (−2, 0, −3)     slot 2: (−2, 0, −2.4)
 *
 * (index i sits at at + (i − (n−1)/2)·spacing: (0−1)·0.6 = −0.6,
 * (1−1)·0.6 = 0, (2−1)·0.6 = +0.6 — the middle slot IS the anchor).
 *
 *   [1] `slotFor(e, 1)`      → slot 1, the anchor point (−2, 0, −3).
 *   [2] `slotFor(e, 'pair')` → the place's CENTRE, the mean of its slots
 *                              (−2, 0, −3): a PAIR is anchored on the place
 *                              (the server's `centre_of`, the worldmap row's
 *                              own x/z for a pair) and the clip's own frame
 *                              moves both partners out from there. A fresh
 *                              vector, not one of the slots.
 *   [3] `slotFor(e, 7)`      → slot 0: an index outside the entry's slots
 *                              (the capacity shrank under a sitter) falls
 *                              back to the first slot, never throws.
 *   [4] `slotFor(e, 2)`      → slot 2, the last one (−2, 0, −2.4) — the
 *                              range check is `< length`, not `< length − 1`.
 *   [5] the answer is the entry's OWN vector (identity), so a caller that
 *       moves the figure must `clone()` — and a re-lift of the entry
 *       (`reliftScene`, `deriveRoomSpots`) reaches the seat without a copy.
 *   [6] an entry WITHOUT slots (a payload marker that named none) answers
 *       `undefined` for a numbered slot and for a pair alike — total, never
 *       a throw and never a made-up point; the callers guard.
 *
 * WHICH TARGET A PLACE GETS (`scene/placeGlyphs.ts`, ruling 2026-08-28)
 * --------------------------------------------------------------------
 * Since the prop mesh itself takes the seat's click, the ring and the mesh
 * split the offered places between them — every place must end up with
 * exactly one target, and none with two.
 *
 *   [7] `buildGlyphs` draws a ring for
 *         - a ROOM marker (`fixed: false`)                        -> yes
 *         - a PROP marker with an `anchor` (its mesh is the target) -> no
 *         - a PROP marker WITHOUT one (a payload from before the field:
 *           `pickableProps` cannot find its mesh, so a ring is the only
 *           target it can have)                                   -> yes
 *       …and `skipPlaceId` still removes the place the avatar itself holds.
 *       Three offers, two rings, and their `userData.placeId` are the room
 *       marker's and the anchor-less prop marker's.
 *   [8] `pickableProps` keys on ROOM + ANCHOR, not on the anchor alone: an
 *       anchor is a metre point in the room's own frame, so a bench in the
 *       same corner of two rooms carries the same pair. Two entries at
 *       anchor (1, 2), one in room "a" and one in room "b", against ONE
 *       placement in room "a" -> one pickable prop with ONE place, "a/seat".
 *       An entry without an anchor is never matched (it is a room marker),
 *       and a placement whose mesh has not loaded (`object: null`) is
 *       nothing to click.
 *
 * A POLL OLDER THAN OUR OWN SEAT CHANGE (plan-aufstehen.md, Task 1)
 * ----------------------------------------------------------------
 * Standing up releases the seat on the server and walks straight away. The
 * worldmap poll that was in flight while that happened still shows the seat,
 * and all three of its consumers (`reconcileAvatarPlace`, `reconcileAvatarPos`
 * and the player branch of `npcs.update`) ask ONE rule whether to believe it:
 * `pollIsStale(polledAt, ownSeatChangeAt)` — the poll is stale when it was
 * ASKED before the server ANSWERED our own last seat change. Both stamps are
 * `performance.now()` milliseconds, so the comparison is a plain `<`.
 *
 *   [9] `pollIsStale(1000, Infinity)` -> true: `Infinity` is the release in
 *       flight (no answer yet), and nothing asked before it can know about it.
 *       `pollIsStale(120, 200)`      -> true: asked 80 ms before the answer.
 *       `pollIsStale(300, 200)`      -> false: asked after it, believe it.
 *       `pollIsStale(200, 200)`      -> false: the same instant is not older.
 *       `pollIsStale(0, 0)`          -> false: no seat change of our own has
 *       ever been answered (the start value, and the value a FAILED release
 *       falls back to) — every poll counts, the server's word stands.
 *
 *  [10] WHICH CLIP A STANDING FIGURE PLAYS, `standingClipFor(animation,
 *       groundIdle)` — the expression the frame loop of `npcs.tick()` runs for
 *       every figure, the avatar included: the GROUND has the first word, then
 *       the server's activity clip, and a figure that has neither simply
 *       stands.
 *         ('sit', '')      -> 'sit'   the server's activity clip
 *         (undefined, '')  -> 'idle'  nothing named: the figure stands
 *         ('sit', 'tread') -> 'tread' the ground wins (standing in a lake)
 *       This is why the stand-up clears `npc.animation` locally
 *       (`setPlayerAnimation(name, null)`): with 'sit' still on the figure the
 *       rule keeps answering 'sit' until a fresh poll arrives.
 */

// Self-bundling guard — esbuild is required to resolve TypeScript imports
import { spawnSync } from 'child_process'
import * as fs from 'fs'
import * as path from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

async function main() {
  if (!process.env.SMOKE_BUNDLED) {
    const bundlePath = '/tmp/smoke_places_client_bundled.mjs'
    const root = path.join(__dirname, '../../')
    const bin = ['client3d/node_modules/.bin/esbuild',
                 'node_modules/.bin/esbuild']
      .map((rel) => path.join(root, rel)).find((p) => fs.existsSync(p))
    if (!bin) {
      console.error('esbuild not found (npm install) — nothing was checked')
      process.exit(1)
    }
    const esbuildResult = spawnSync(bin, [
      __filename, '--bundle', '--platform=node', '--format=esm',
      `--outfile=${bundlePath}`,
    ], { cwd: root, stdio: 'inherit' })
    if (esbuildResult.status !== 0) process.exit(esbuildResult.status ?? 1)
    const runResult = spawnSync('node', [bundlePath], {
      stdio: 'inherit',
      env: { ...process.env, SMOKE_BUNDLED: '1' },
    })
    process.exit(runResult.status ?? 1)
  }

  const THREE = await import('three')
  const { slotFor } = await import('../src/scene/placeSlot.ts')

  const FAILED = []
  function check(label, got, want) {
    const ok = Math.abs(got.x - want[0]) <= 1e-9
      && Math.abs(got.y - want[1]) <= 1e-9
      && Math.abs(got.z - want[2]) <= 1e-9
    console.log(`  ${ok ? 'ok  ' : 'FAIL'} ${label}: (${got.x}, ${got.y}, ${got.z})`
      + (ok ? '' : `  (expected ${want.join(', ')})`))
    if (!ok) FAILED.push(label)
  }
  /** …and the same for a plain LIST of values — `check` above compares a
   *  `Vector3` against three numbers and cannot say anything about the ids
   *  the ring/prop targets carry. */
  function checkList(label, got, want) {
    const ok = Array.isArray(got) && got.length === want.length
      && got.every((v, i) => v === want[i])
    console.log(`  ${ok ? 'ok  ' : 'FAIL'} ${label}: ${JSON.stringify(got)}`
      + (ok ? '' : `  (expected ${JSON.stringify(want)})`))
    if (!ok) FAILED.push(label)
  }
  function checkTrue(label, ok) {
    console.log(`  ${ok ? 'ok  ' : 'FAIL'} ${label}`)
    if (!ok) FAILED.push(label)
  }

  const entry = {
    group: 'seat',
    slots: [new THREE.Vector3(-2, 0, -3.6),
            new THREE.Vector3(-2, 0, -3),
            new THREE.Vector3(-2, 0, -2.4)],
    rotation: 90, drop: 0.314, offsetY: 0, fixed: true, level: 0, lift: 0,
  }

  console.log('[1] a numbered slot is that slot')
  check('slotFor(e, 1)', slotFor(entry, 1), [-2, 0, -3])
  console.log('[2] a pair sits on the centre, the mean of the slots')
  check("slotFor(e, 'pair')", slotFor(entry, 'pair'), [-2, 0, -3])
  checkTrue("slotFor(e, 'pair') is a fresh vector, none of the slots",
    !entry.slots.includes(slotFor(entry, 'pair')))
  console.log('[3] an index out of range falls back to slot 0')
  check('slotFor(e, 7)', slotFor(entry, 7), [-2, 0, -3.6])
  check('slotFor(e, -1)', slotFor(entry, -1), [-2, 0, -3.6])
  console.log('[4] the last slot is still in range')
  check('slotFor(e, 2)', slotFor(entry, 2), [-2, 0, -2.4])
  console.log('[5] the answer is the entry\'s own vector, not a copy')
  checkTrue('slotFor(e, 1) === e.slots[1]', slotFor(entry, 1) === entry.slots[1])
  console.log('[6] an entry without slots answers undefined')
  const bare = { ...entry, slots: [] }
  checkTrue('slotFor(bare, 0) === undefined', slotFor(bare, 0) === undefined)
  checkTrue("slotFor(bare, 'pair') === undefined", slotFor(bare, 'pair') === undefined)

  // --- the two targets a place can have (ruling 2026-08-28) ----------------
  const { buildGlyphs, pickableProps } = await import('../src/scene/placeGlyphs.ts')
  /** One place entry of a room's marker map. Only the fields the two
   *  functions read are set — the rest is `slotFor`'s business above. */
  const place = (roomId, x, z, extra) => ({
    roomId, group: 'seat', slots: [new THREE.Vector3(x, 0, z)],
    drop: 0, offsetY: 0, level: 0, lift: 0, liftAt: { x, z }, ...extra,
  })
  /** One offer of `GET /play/places` — free slot 0, as the fixtures need. */
  const offer = (id) => ({ id, label: id, group: 'seat', capacity: 1,
    free: 1, free_slots: [0], poses: [] })

  console.log('[7] rings: room markers and anchor-less prop markers only')
  const glyphEntries = new Map([
    ['r1', place('a', 1, 1)],
    ['p1', place('a', 2, 2, { fixed: true, anchor: [2, 2] })],
    ['p2', place('a', 3, 3, { fixed: true })],
  ])
  const glyphOffers = [offer('r1'), offer('p1'), offer('p2')]
  const rings = buildGlyphs(glyphEntries, glyphOffers, '')
  const ringIds = rings.children.map((m) => m.userData.placeId).sort()
  checkList('two rings: the room marker and the anchor-less prop marker',
    ringIds, ['p2', 'r1'])
  const skipped = buildGlyphs(glyphEntries, glyphOffers, 'r1')
  checkList('...and the place the avatar holds still loses its ring',
    skipped.children.map((m) => m.userData.placeId), ['p2'])

  console.log('[8] pickableProps keys on ROOM + anchor')
  const propEntries = new Map([
    ['a/seat', place('a', 1, 2, { fixed: true, anchor: [1, 2] })],
    ['b/seat', place('b', 1, 2, { fixed: true, anchor: [1, 2] })],
    ['a/room', place('a', 4, 4)],
  ])
  const mesh = new THREE.Object3D()
  const picked = pickableProps([{ roomId: 'a', anchor: [1, 2], object: mesh }],
    propEntries, [offer('a/seat'), offer('b/seat'), offer('a/room')])
  checkTrue('one pickable prop', picked.length === 1)
  checkList('...carrying ONLY the place of its own room',
    picked[0].places.map((p) => p.id), ['a/seat'])
  checkList('...at that place’s free slot point',
    [picked[0].places[0].free.length,
     picked[0].places[0].free[0].x, picked[0].places[0].free[0].z], [1, 1, 2])
  checkTrue('a placement whose mesh has not loaded is nothing to click',
    pickableProps([{ roomId: 'a', anchor: [1, 2], object: null }],
      propEntries, [offer('a/seat')]).length === 0)
  checkTrue('a room in which nothing is free offers no prop',
    pickableProps([{ roomId: 'a', anchor: [1, 2], object: mesh }],
      propEntries, []).length === 0)

  // --- the stale poll and the standing clip (plan-aufstehen.md) ------------
  const { pollIsStale } = await import('../src/game/placement.ts')
  const { standingClipFor } = await import('../src/game/walk.ts')

  console.log('[9] a poll asked before our own seat change was answered is stale')
  checkTrue('pollIsStale(1000, Infinity) — release in flight',
    pollIsStale(1000, Infinity) === true)
  checkTrue('pollIsStale(120, 200) — asked before the answer',
    pollIsStale(120, 200) === true)
  checkTrue('pollIsStale(300, 200) — asked after the answer',
    pollIsStale(300, 200) === false)
  checkTrue('pollIsStale(200, 200) — the same instant is not older',
    pollIsStale(200, 200) === false)
  checkTrue('pollIsStale(0, 0) — no seat change of our own, ever',
    pollIsStale(0, 0) === false)

  console.log('[10] the standing clip: ground first, then the server, then idle')
  checkList("standingClipFor('sit', '') / (undefined, '') / ('sit', 'tread')",
    [standingClipFor('sit', ''), standingClipFor(undefined, ''),
     standingClipFor('sit', 'tread')], ['sit', 'idle', 'tread'])

  if (FAILED.length) {
    console.error(`\n${FAILED.length} check(s) FAILED: ${FAILED.join(', ')}`)
    process.exit(1)
  }
  console.log('\nall place-slot checks passed')
}

main().catch((e) => { console.error(e); process.exit(1) })
