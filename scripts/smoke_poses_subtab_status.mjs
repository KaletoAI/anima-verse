/**
 * The status rules of the Entries / Transitions / Import / CMU sub-tabs (Ruling A110 phase 5,
 * frontend/src/tabs/poses/clipStatus.ts), pinned by hand:
 *
 *   pose lamp, base sets [female, male]:
 *     kind "bathing"  files: neutral only            → yellow, missing [female, male] (both fall back)
 *     kind "dance"    files: neutral, female, male   → green,  missing []
 *     kind "salsa"    files: female only             → red,    missing [male], no neutral to fall back to
 *     kind "ghost"    no file                        → red,    files 0
 *     kind ""         (no animation)                 → red,    files 0
 *   Run all (posesToAnimate), animatable groups [stand, seat]:
 *     a  solo, stand, kind "ghost" (no file)           → animated
 *     b  solo, stand, kind "bathing" (has a file)      → skipped (current)
 *     c  pair, stand, kind "ghost"                     → skipped (generator makes solo clips)
 *     d  solo, lie,   kind ""                          → skipped (place type not animatable)
 *     e  solo, seat,  kind ""                          → animated
 *     f  solo, seat,  kind "", job already running     → skipped
 *     → ["a", "e"]; at 3 variants the button reads 2 poses, 6 jobs.
 *   rule lamp: bridge kinds all installed → green; + conflict → yellow; one missing → red; none → red.
 *   inbox lamp: no skeleton family → red; reference pose → yellow; else green.
 *   take lamp: rejected → red (even when imported); imported → green; converted → yellow; else grey.
 *
 * Usage: node scripts/smoke_poses_subtab_status.mjs   (no server, no world; bundles the module with esbuild)
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

const dir = await mkdtemp(join(tmpdir(), 'poses-status-'))
try {
  const esbuild = await import(join(ROOT, 'node_modules/esbuild/lib/main.js'))
  const built = await esbuild.build({
    entryPoints: [join(ROOT, 'frontend/src/tabs/poses/clipStatus.ts')],
    bundle: true, platform: 'node', format: 'esm', write: false, logLevel: 'error',
  })
  const file = join(dir, 'status.mjs')
  await writeFile(file, built.outputFiles[0].text, 'utf8')
  const S = await import(`file://${file}`)

  const clips = [
    { kind: 'bathing', set: '' },
    { kind: 'dance', set: '' }, { kind: 'dance', set: 'female' }, { kind: 'dance', set: 'male' },
    { kind: 'salsa', set: 'female' },
  ]
  const base = ['female', 'male']
  console.log('[1] pose lamp')
  const pl = (k) => { const r = S.poseLamp(k, clips, base); return [r.lamp, r.missing, r.neutral, r.files] }
  check('bathing: neutral only', pl('bathing'), ['yellow', ['female', 'male'], true, 1])
  check('dance: every set', pl('dance'), ['green', [], true, 3])
  check('salsa: female only, no neutral', pl('salsa'), ['red', ['male'], false, 1])
  check('ghost: no file', pl('ghost'), ['red', ['female', 'male'], false, 0])
  check('no animation', pl(''), ['red', ['female', 'male'], false, 0])

  console.log('[2] Run all')
  const poses = [
    { key: 'a', animation: 'ghost', participants: 1, group: 'stand' },
    { key: 'b', animation: 'bathing', participants: 1, group: 'stand' },
    { key: 'c', animation: 'ghost', participants: 2, group: 'stand' },
    { key: 'd', animation: '', participants: 1, group: 'lie' },
    { key: 'e', animation: '', participants: 1, group: 'seat' },
    { key: 'f', animation: '', participants: 1, group: 'seat' },
  ]
  const todo = S.posesToAnimate(poses, clips, ['stand', 'seat'], new Set(['f']))
  check('poses to animate', todo, ['a', 'e'])
  check('jobs at 3 variants', todo.length * 3, 6)

  console.log('[3] rule lamp')
  const inst = new Set(['stand-up', 'sit-down'])
  check('all installed', S.ruleLamp(['stand-up'], inst, false), 'green')
  check('installed + conflict', S.ruleLamp(['stand-up', 'sit-down'], inst, true), 'yellow')
  check('one missing', S.ruleLamp(['stand-up', 'gone'], inst, false), 'red')
  check('no bridge', S.ruleLamp([], inst, false), 'red')

  console.log('[4] inbox + take lamp')
  check('unknown rig', S.inboxLamp({ skeleton_family: '' }), 'red')
  check('reference pose', S.inboxLamp({ skeleton_family: 'mixamo', is_rest_candidate: true }), 'yellow')
  check('convertible', S.inboxLamp({ skeleton_family: 'mixamo' }), 'green')
  check('rejected + imported', S.takeLamp({ clip: 'x', status: { rejected: true, imported: [{}] } }), 'red')
  check('imported', S.takeLamp({ status: { imported: [{}] } }), 'green')
  check('converted', S.takeLamp({ clip: 'x', status: {} }), 'yellow')
  check('not converted', S.takeLamp({ status: { imported: [] } }), 'grey')
} finally {
  await rm(dir, { recursive: true, force: true })
}
if (failures) { console.log(`FAILED: ${failures}`); process.exit(1) }
console.log('OK')
