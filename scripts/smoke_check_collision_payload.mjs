#!/usr/bin/env node
/**
 * Smoke check for WHICH capsule set the garment check measures with (Ruling B11i) —
 * `scripts/collisionPayloadSource.mjs`, used by `scripts/check_garment_collision.mjs`.
 * The check used to fit the capsules from the GLB alone: no extension capsules (`chest`,
 * `chest_hair` of a `pair_protrusion` body) and no character scales — 10 hair capsules where the
 * client pushes with 12. It now measures the SERVED record by default.
 *
 * Usage: node scripts/smoke_check_collision_payload.mjs   (plain node, no server, no world, no files)
 *
 * The file functions are injected (an in-memory map), so every case is decided by hand:
 * [1] m/Kira.glb + m/Kira.json {collision: {version V, source "own", capsules [A, B]}}
 *     → kind "served", file m/Kira.json, payload = that record (2 capsules); the note names
 *     version V, 2 capsules, source own. V = `COLLISION_VERSION` of `collision.ts`, read from its
 *     source (this smoke runs in plain node, without the TS bundler) — no bump touches this file.
 * [2] the same with --fitted → still "served": the fitted set is a FALLBACK, never preferred.
 * [3] --collision p.json for the one model, sidecar present → kind "file", payload = p.json's content.
 * [4] --collision with two models → error "--collision needs exactly one model".
 * [5] m/fit.glb, no sidecar, no flag → error naming "no sidecar fit.json" and "--fitted".
 * [6] the same with --fitted → kind "fitted", payload null, the note says "NOT the set the client gets".
 * [7] m/Old.glb + m/Old.json without a collision record → error "carries no collision record";
 *     with --fitted → "fitted".
 * [8] a sidecar whose `collision` has no capsule list ({version V}) counts as no record → as [7].
 * [9] sidecarPath: "a/b/x.GLB" → "a/b/x.json"; "x.glb" → "x.json".
 */
import * as fs from 'fs'
import * as path from 'path'
import { FITTED_NOTE, resolvePayloadSource, sidecarPath } from './collisionPayloadSource.mjs'

/** `COLLISION_VERSION` of `packages/scene-render/src/collision.ts` (module docstring [1]). */
const COLLISION_VERSION = Number(/export const COLLISION_VERSION = (\d+)/.exec(
  fs.readFileSync(new URL('../packages/scene-render/src/collision.ts', import.meta.url), 'utf8'))?.[1])
if (!Number.isInteger(COLLISION_VERSION)) throw new Error('COLLISION_VERSION not found in collision.ts')

let failures = 0
function check(label, ok, detail = '') {
  if (!ok) failures++
  console.log(`${ok ? 'PASS' : 'FAIL'} ${label}${detail ? ` — ${detail}` : ''}`)
}
function throws(fn, needle) {
  try { fn() } catch (e) { return String(e.message).includes(needle) ? '' : `message: ${e.message}` }
  return 'no error'
}

const A = { id: 'hips', a: 'Hips', b: 'Spine1', r: 0.05, region: 'torso' }
const B = { id: 'breast_pair:leftbreast:chest_hair', a: 'LeftBreast', b: 'LeftBreast', r: 0.068, region: 'chest_hair' }
const files = new Map([
  ['m/Kira.json', { signature: 's', collision: { version: COLLISION_VERSION, source: 'own', capsules: [A, B] } }],
  ['p.json', { version: COLLISION_VERSION, capsules: [A] }],
  ['m/Old.json', { signature: 's' }],
  ['m/Bad.json', { collision: { version: COLLISION_VERSION } }],
])
const io = { exists: (f) => files.has(f), readJson: (f) => structuredClone(files.get(f)) }

// [1]
const s1 = resolvePayloadSource('m/Kira.glb', {}, io)
check('[1] sidecar record is served', s1.kind === 'served' && s1.file === 'm/Kira.json'
  && s1.payload.capsules.length === 2 && s1.payload.capsules[1].region === 'chest_hair', JSON.stringify(s1.kind))
check('[1] note names version, count, source', s1.note.includes(`version ${COLLISION_VERSION}, 2 capsules, source own`), s1.note)
// [2]
check('[2] --fitted never beats a served record', resolvePayloadSource('m/Kira.glb', { fitted: true }, io).kind === 'served')
// [3]
const s3 = resolvePayloadSource('m/Kira.glb', { collision: 'p.json' }, io)
check('[3] --collision wins for one model', s3.kind === 'file' && s3.payload.capsules.length === 1)
// [4]
const e4 = throws(() => resolvePayloadSource('m/Kira.glb', { collision: 'p.json', modelCount: 2 }, io), '--collision needs exactly one model')
check('[4] --collision with two models refused', !e4, e4)
// [5]
const e5 = throws(() => resolvePayloadSource('m/fit.glb', {}, io), 'no sidecar fit.json')
check('[5] no record, no flag -> refused', !e5, e5)
check('[5] the refusal points at --fitted', !throws(() => resolvePayloadSource('m/fit.glb', {}, io), '--fitted'))
// [6]
const s6 = resolvePayloadSource('m/fit.glb', { fitted: true }, io)
check('[6] --fitted fallback', s6.kind === 'fitted' && s6.payload === null && s6.note.includes(FITTED_NOTE)
  && FITTED_NOTE.includes('NOT the set the client gets'), s6.note)
// [7]
const e7 = throws(() => resolvePayloadSource('m/Old.glb', {}, io), 'carries no collision record')
check('[7] sidecar without record refused', !e7, e7)
check('[7] ... and falls back with --fitted', resolvePayloadSource('m/Old.glb', { fitted: true }, io).kind === 'fitted')
// [8]
const e8 = throws(() => resolvePayloadSource('m/Bad.glb', {}, io), 'carries no collision record')
check('[8] record without capsules is no record', !e8, e8)
// [9]
check('[9] sidecarPath', sidecarPath('a/b/x.GLB') === path.join('a/b', 'x.json') && sidecarPath('x.glb') === 'x.json',
  `${sidecarPath('a/b/x.GLB')} ${sidecarPath('x.glb')}`)

console.log(failures ? `${failures} FAILED` : 'all passed')
process.exit(failures ? 1 : 0)
