/**
 * The Library's status rules (Ruling A110 phase 4, frontend/src/tabs/poses/clipStatus.ts), pinned by hand:
 *
 *   lamp per file (D3): has_sidecar false → grey; orientation.checked set → green; else yellow.
 *   lamp per kind: the weakest of its non-B files; no file → grey.
 *     pair  [a: checked, b: no check]        → green  (B follows A, the dials act on A)
 *     solo  [checked, unchecked variant]     → yellow
 *     solo  [checked, no sidecar]            → grey
 *   set letters: '' → n, female → f, male → m, animal → a.
 *   finale kinds (server finale_kinds_of + _finale_files): poses playing "sit" name finales
 *     "sit-up" (own), "sit-climax" (derived, finale_animation empty), "sit" (itself → dropped),
 *     "sit-up" again (deduped); files: sit-up in neutral/free, sit-climax only in male/free
 *     → editing neutral/free gives ["sit-up"]; editing male/free gives ["sit-climax"].
 *   save steps: the order bake, shift, heights, finales, check | clear-check;
 *     finales only when something is written; a stored check is cleared by a bake or shift that
 *     carries no green check (the server clears on every orient write), never by heights alone.
 *
 * Usage: node scripts/smoke_clip_library_status.mjs   (no server, no world; bundles the module with esbuild)
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

const dir = await mkdtemp(join(tmpdir(), 'clip-status-'))
try {
  const esbuild = await import(join(ROOT, 'node_modules/esbuild/lib/main.js'))
  const built = await esbuild.build({
    entryPoints: [join(ROOT, 'frontend/src/tabs/poses/clipStatus.ts')],
    bundle: true, platform: 'node', format: 'esm', write: false, logLevel: 'error',
  })
  const file = join(dir, 'status.mjs')
  await writeFile(file, built.outputFiles[0].text, 'utf8')
  const S = await import(`file://${file}`)

  const CK = { at: '2026-11-16T10:00:00Z', prop: 'bench', place: 'A', dyaw: 1, dpos: 1 }
  console.log('[1] lamp per file')
  check('no sidecar → grey', S.clipLamp({ has_sidecar: false, orientation: { checked: CK } }), 'grey')
  check('checked → green', S.clipLamp({ has_sidecar: true, orientation: { checked: CK } }), 'green')
  check('sidecar, no check → yellow', S.clipLamp({ has_sidecar: true, orientation: {} }), 'yellow')
  check('sidecar, checked null → yellow', S.clipLamp({ has_sidecar: true, orientation: { checked: null } }), 'yellow')

  console.log('[2] lamp per kind')
  check('pair, A checked, B not → green', S.kindLamp([
    { role: 'a', has_sidecar: true, orientation: { checked: CK } }, { role: 'b', has_sidecar: true }]), 'green')
  check('solo, one variant unchecked → yellow', S.kindLamp([
    { has_sidecar: true, orientation: { checked: CK } }, { has_sidecar: true }]), 'yellow')
  check('solo, one without sidecar → grey', S.kindLamp([
    { has_sidecar: true, orientation: { checked: CK } }, { has_sidecar: false }]), 'grey')
  check('no file → grey', S.kindLamp([]), 'grey')

  console.log('[3] set letters')
  check('n f m a', ['', 'female', 'male', 'animal'].map(S.setLetter), ['n', 'f', 'm', 'a'])

  console.log('[4] finale kinds')
  const poses = [
    { animation: 'sit', finale_animation: 'sit-up' },
    { animation: 'sit', finale_animation: '', finale_auto: 'sit-climax' },
    { animation: 'sit', finale_animation: 'sit' },
    { animation: 'sit', finale_animation: 'Sit-Up' },
    { animation: 'lie', finale_animation: 'lie-up' },
  ]
  const clips = [
    { kind: 'sit-up', set: '', library: 'free' },
    { kind: 'sit-climax', set: 'male', library: 'free' },
    { kind: 'lie-up', set: '', library: 'free' },
  ]
  check('neutral/free', S.finaleKinds(poses, 'sit', { set: '', library: 'free' }, clips), ['sit-up'])
  check('male/free', S.finaleKinds(poses, 'sit', { set: 'male', library: 'free' }, clips), ['sit-climax'])
  check('neutral/licensed', S.finaleKinds(poses, 'sit', { set: '', library: 'licensed' }, clips), [])

  console.log('[5] save steps')
  const base = { bake: false, shift: false, heights: false, finales: 0, greenCheck: false, savedCheck: false }
  check('nothing', S.saveSteps(base), [])
  check('check only', S.saveSteps({ ...base, greenCheck: true }), ['check'])
  check('everything, green', S.saveSteps({ bake: true, shift: true, heights: true, finales: 2, greenCheck: true, savedCheck: true }),
    ['bake', 'shift', 'heights', 'finales', 'check'])
  check('bake over a stored check, not green', S.saveSteps({ ...base, bake: true, savedCheck: true }), ['bake', 'clear-check'])
  check('shift over a stored check', S.saveSteps({ ...base, shift: true, savedCheck: true, finales: 1 }), ['shift', 'finales', 'clear-check'])
  check('heights only keep the check', S.saveSteps({ ...base, heights: true, savedCheck: true }), ['heights'])
  check('finales alone write nothing', S.saveSteps({ ...base, finales: 3 }), [])
} finally {
  await rm(dir, { recursive: true, force: true })
}
console.log(failures ? `FAILED: ${failures}` : 'all OK')
process.exit(failures ? 1 : 0)
