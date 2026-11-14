#!/usr/bin/env node
/**
 * Check: the confirmation before a piece leaves its own mesh (Ruling A63) — the pure helpers `leavesOwnMesh` /
 * `switchOffWarning` of frontend/src/tabs/characters/figureModel.ts plus the source rules of the Wardrobe's mode select.
 *
 * Usage:  node scripts/check_mode_switch_warning.mjs      (no server; esbuild from the workspace bundles the module)
 *
 * THE CASES, DERIVED BY HAND
 * --------------------------
 * [1] leavesOwnMesh: own_mesh → painted / in_body true; own_mesh → own_mesh, painted → in_body, in_body → painted,
 *     painted → own_mesh false (Painted ↔ In the body drops no own-mesh file: the server counts 0 for a piece that
 *     is no own mesh — scripts/smoke_own_mesh_switch_warning.py [3]).
 * [2] switchOffWarning → null (no confirmation): painted → in_body whatever the count; own_mesh → painted with
 *     files 0 (nothing stored).
 * [3] The dress of smoke_own_mesh_switch_warning.py [1]: files 7, bytes 1001000, hub_jobs 14, stored for Bea and Demo.
 *     sizeLabel: 1001000 < 1024² → round(1001000 / 1024 = 977.54) = "978 KB". own_mesh → painted:
 *       title   "Switch to “Painted”?"
 *       message "This piece’s own mesh and its fits (7 files, 978 KB) will be removed by the next cleanup. Switching
 *                back to Own mesh later costs up to 14 hub jobs (mesh) plus the fit on the CPU. Stored for Bea, Demo."
 *     The shoes of [2] there: files 5, bytes 1002000 (978.52 → "979 KB"), hub_jobs 2, one character (no
 *     "Stored for"), own_mesh → in_body: title "Switch to “In the body”?", message "… (5 files, 979 KB) … up to 2 hub
 *     jobs (mesh) …".
 *     One file of 1572864 B (1.5 · 1024²) and 1 hub job: "(1 file, 1.5 MB)" and "up to 1 hub job (mesh)".
 *     hub_jobs null, note "Demo: Demo is not on the base-body pipeline": "Switching back to Own mesh later costs hub
 *     jobs again (count unknown: Demo: Demo is not on the base-body pipeline) plus the fit on the CPU."
 *     The count unreadable (info null, error "HTTP 500"): a confirmation all the same — "The stored files of its own
 *     mesh could not be counted (HTTP 500). The next cleanup may remove them; switching back to Own mesh would then
 *     cost hub jobs again."
 * [4] German (shared/languages/de.json through t): the dress → title "Modus auf „Aufgemalt“ umstellen?", message
 *     "Das eigene Mesh dieses Teils und seine Anpassungen (7 Dateien, 978 KB) werden beim nächsten Aufräumen
 *     gelöscht. Später zurück auf Eigenes Mesh kostet bis zu 14 Hub-Jobs (Mesh) plus die Anpassung auf der CPU.
 *     Gespeichert für Bea, Demo."; every English string of the helper and the select has a de.json key.
 * [5] Sources: MeshModeSelect asks `/own-mesh-files` only when leaving Own mesh, shows the in-app ConfirmDialog
 *     (confirmLabel "Switch anyway", Cancel = onClose → setAsk(null), nothing saved), saves (`save(next)`, the one
 *     PUT of mesh_mode) from onConfirm or when there is nothing to confirm; no window.confirm; the route
 *     `/items/{item_id}/own-mesh-files` exists, admin-only, and calls `artefact_graph.own_mesh_files`.
 */
import { readFileSync } from 'node:fs'
import { mkdtemp, rm } from 'node:fs/promises'
import { createRequire } from 'node:module'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = fileURLToPath(new URL('..', import.meta.url))
const require_ = createRequire(import.meta.url)

function esbuildModule() {
  for (const cand of ['esbuild', join(ROOT, 'frontend/node_modules/esbuild'), join(ROOT, 'client3d/node_modules/esbuild')]) {
    try { return require_(cand) } catch { /* next candidate */ }
  }
  console.error('esbuild not found (npm install) — nothing was checked')
  process.exit(1)
}

async function loadBundled(src) {
  const dir = await mkdtemp(join(tmpdir(), 'check-mode-switch-'))
  try {
    const file = join(dir, 'module.mjs')
    await esbuildModule().build({ entryPoints: [src], outfile: file, bundle: true, format: 'esm', platform: 'neutral',
      logLevel: 'silent', absWorkingDir: ROOT })
    return await import(`file://${file}`)
  } finally {
    await rm(dir, { recursive: true, force: true })
  }
}

const failures = []
function check(label, got, want) {
  const g = JSON.stringify(got)
  const w = JSON.stringify(want)
  if (g !== w) failures.push(`${label}: got ${g}, want ${w}`)
  else console.log(`ok  ${label}`)
}

const m = await loadBundled(join(ROOT, 'frontend/src/tabs/characters/figureModel.ts'))
const info = (files, bytes, hub, names = ['Demo'], note = '') => ({
  item_id: 'x', mode: 'own_mesh', kind: 'clothing', files, bytes, hub_jobs: hub, note,
  characters: names.map((name) => ({ name, files: 1, bytes: 1, hub_jobs: hub, note: '' })), world: { files: 0, bytes: 0 },
})

// [1]
for (const [a, b, want] of [['own_mesh', 'painted', true], ['own_mesh', 'in_body', true], ['own_mesh', 'own_mesh', false],
  ['painted', 'in_body', false], ['in_body', 'painted', false], ['painted', 'own_mesh', false]]) {
  check(`[1] leavesOwnMesh ${a} → ${b}`, m.leavesOwnMesh(a, b), want)
}
// [2]
check('[2] painted → in_body: no confirmation', m.switchOffWarning('painted', 'in_body', info(7, 1001000, 14)), null)
check('[2] no files: no confirmation', m.switchOffWarning('own_mesh', 'painted', info(0, 0, 0, [])), null)
// [3]
const dress = info(7, 1001000, 14, ['Bea', 'Demo'])
check('[3] dress', m.switchOffWarning('own_mesh', 'painted', dress), {
  title: 'Switch to “Painted”?',
  message: 'This piece’s own mesh and its fits (7 files, 978 KB) will be removed by the next cleanup. Switching back '
    + 'to Own mesh later costs up to 14 hub jobs (mesh) plus the fit on the CPU. Stored for Bea, Demo.',
})
check('[3] shoes', m.switchOffWarning('own_mesh', 'in_body', info(5, 1002000, 2)), {
  title: 'Switch to “In the body”?',
  message: 'This piece’s own mesh and its fits (5 files, 979 KB) will be removed by the next cleanup. Switching back '
    + 'to Own mesh later costs up to 2 hub jobs (mesh) plus the fit on the CPU.',
})
check('[3] one file, one job', m.switchOffWarning('own_mesh', 'painted', info(1, 1572864, 1)).message,
  'This piece’s own mesh and its fits (1 file, 1.5 MB) will be removed by the next cleanup. Switching back to Own '
  + 'mesh later costs up to 1 hub job (mesh) plus the fit on the CPU.')
check('[3] cost unknown', m.switchOffWarning('own_mesh', 'painted',
  info(2, 2048, null, ['Demo'], 'Demo: Demo is not on the base-body pipeline')).message,
'This piece’s own mesh and its fits (2 files, 2 KB) will be removed by the next cleanup. Switching back to Own mesh '
  + 'later costs hub jobs again (count unknown: Demo: Demo is not on the base-body pipeline) plus the fit on the CPU.')
check('[3] count unreadable', m.switchOffWarning('own_mesh', 'painted', null, 'HTTP 500'), {
  title: 'Switch to “Painted”?',
  message: 'The stored files of its own mesh could not be counted (HTTP 500). The next cleanup may remove them; '
    + 'switching back to Own mesh would then cost hub jobs again.',
})
// [4]
const de = JSON.parse(readFileSync(join(ROOT, 'shared/languages/de.json'), 'utf8')).translations
const tDe = (s) => de[s] ?? `<<missing ${s}>>`
check('[4] German', m.switchOffWarning('own_mesh', 'painted', dress, '', tDe), {
  title: 'Modus auf „Aufgemalt“ umstellen?',
  message: 'Das eigene Mesh dieses Teils und seine Anpassungen (7 Dateien, 978 KB) werden beim nächsten Aufräumen '
    + 'gelöscht. Später zurück auf Eigenes Mesh kostet bis zu 14 Hub-Jobs (Mesh) plus die Anpassung auf der CPU. '
    + 'Gespeichert für Bea, Demo.',
})
const missing = []
for (const args of [['own_mesh', 'in_body', info(1, 1572864, 1)], ['own_mesh', 'painted', info(2, 9, null, ['A'], 'n')],
  ['own_mesh', 'painted', null, 'e']]) {
  const w = m.switchOffWarning(args[0], args[1], args[2], args[3] || '', tDe)
  for (const part of [w.title, w.message]) if (part.includes('<<missing')) missing.push(part)
}
for (const s of ['Switch anyway', 'Cancel']) if (!(s in de)) missing.push(s)
check('[4] every string has a de.json key', missing, [])

// [5]
const wg = readFileSync(join(ROOT, 'frontend/src/tabs/characters/WardrobeGarment.tsx'), 'utf8')
const sel = wg.slice(wg.indexOf('export function MeshModeSelect'), wg.indexOf('const MATERIAL_LABELS'))
check('[5] asks the count only when leaving Own mesh',
  /if \(leavesOwnMesh\(mode, next\)\) \{[\s\S]*?apiGet<OwnMeshFiles>\(`\$\{url\}\/own-mesh-files`\)/.test(sel), true)
check('[5] a confirmation waits instead of saving', /if \(warning\) \{\s*setAsk\(\{ next, \.\.\.warning \}\)\s*return\s*\}/.test(sel), true)
check('[5] in-app ConfirmDialog, "Switch anyway"', /<ConfirmDialog[\s\S]*?confirmLabel=\{t\('Switch anyway'\)\}/.test(sel), true)
check('[5] Cancel saves nothing', /onClose=\{\(\) => setAsk\(null\)\}/.test(sel), true)
check('[5] confirm saves the mode', /onConfirm=\{\(\) => \{ const next = ask\?\.next; setAsk\(null\); if \(next\) void save\(next\) \}\}/.test(sel), true)
check('[5] one PUT of mesh_mode, in save()', (sel.match(/mesh_mode: next/g) || []).length === 1
  && /const save = async[\s\S]*?mesh_mode: next/.test(sel), true)
check('[5] no native dialog', /window\.(confirm|alert|prompt)|\bconfirm\(/.test(sel), false)
const inv = readFileSync(join(ROOT, 'app/routes/inventory.py'), 'utf8')
check('[5] the route', /@router\.get\("\/items\/\{item_id\}\/own-mesh-files"\)\ndef \w+\(item_id: str, _admin=Depends\(require_admin\)\)[\s\S]*?artefact_graph\.own_mesh_files\(item_id\)/.test(inv), true)

if (failures.length) {
  console.error(`\nFAILED (${failures.length}):\n  ` + failures.join('\n  '))
  process.exit(1)
}
console.log('\nALL OK')
