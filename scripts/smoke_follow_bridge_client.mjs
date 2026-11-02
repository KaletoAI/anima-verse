#!/usr/bin/env node
/**
 * The bridge out of a pair pose, on the client side (plan-folge-pose.md F2).
 * Usage: node scripts/smoke_follow_bridge_client.mjs
 *
 * A figure that played a pair half keeps `<kind>__<role>` as the clip it
 * leaves (`Figure.playPair` sets `currentKind = clipName`; native's
 * `Figure.PlayPair` the same). The server names exactly those halves as
 * `from` (`animation_clips.client_transition_rules`, smoke_follow_pose.py
 * [9]). By hand, with the rows below — the server's answer for the rule
 * `run-pair -> sitting`, bridge {a: run-up, b: run-up-b}, finale run-pair-end:
 *   run-pair__a     -> sit : run-up
 *   run-pair__b     -> sit : run-up-b
 *   run-pair-end__b -> sit : run-up-b   (ended right after the finale)
 *   run-pair        -> sit : none       (no figure ever plays the bare kind)
 *   run-pair__a     -> walk: none       (only the follow is ruled)
 * and the pace the steering reads while that bridge holds the figure: accel
 * 0 -> bridgePace 0 (held on the spot, like standing up out of a seat).
 */
import assert from 'node:assert/strict'
import { build } from 'rolldown'
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const dir = mkdtempSync(join(tmpdir(), 'follow-bridge-'))
try {
  const root = fileURLToPath(new URL('../', import.meta.url))
  const entry = join(dir, 'entry.ts')
  const out = join(dir, 'walk.mjs')
  writeFileSync(entry, `export { setClipTransitions, clipTransition, bridgePace } from ${
    JSON.stringify(join(root, 'client3d/src/game/walk.ts'))};`)
  await build({ input: entry, platform: 'node', output: { file: out, format: 'esm', codeSplitting: false } })
  const { setClipTransitions, clipTransition, bridgePace } = await import(pathToFileURL(out).href)
  const rows = [
    { from: 'run-pair__a', to: 'sit', kind: 'run-up', accel: 0 },
    { from: 'run-pair__b', to: 'sit', kind: 'run-up-b', accel: 0 },
    { from: 'run-pair-end__a', to: 'sit', kind: 'run-up', accel: 0 },
    { from: 'run-pair-end__b', to: 'sit', kind: 'run-up-b', accel: 0 },
  ]
  const table = setClipTransitions(rows)
  assert.equal(table.length, 4)
  assert.equal(clipTransition('run-pair__a', 'sit')?.kind, 'run-up')
  assert.equal(clipTransition('run-pair__b', 'sit')?.kind, 'run-up-b')
  assert.equal(clipTransition('run-pair-end__b', 'sit')?.kind, 'run-up-b')
  assert.equal(clipTransition('run-pair', 'sit'), null)
  assert.equal(clipTransition('run-pair__a', 'walk'), null)
  assert.equal(bridgePace(clipTransition('run-pair__a', 'sit').accel, 0.5), 0)
  console.log('OK smoke_follow_bridge_client: pair halves pick their own bridge into the follow pose')
} finally {
  rmSync(dir, { recursive: true, force: true })
}
