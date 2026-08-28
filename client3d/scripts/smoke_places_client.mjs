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

  if (FAILED.length) {
    console.error(`\n${FAILED.length} check(s) FAILED: ${FAILED.join(', ')}`)
    process.exit(1)
  }
  console.log('\nall place-slot checks passed')
}

main().catch((e) => { console.error(e); process.exit(1) })
