#!/usr/bin/env node
/**
 * Smoke check for WHO THE NARRATOR IS in the voice-over filter
 * (`client3d/src/game/voiceover.ts`, bugrunde-2026-08-29 point 8) — numbers,
 * no listening (docs/schnittstellen-3d.md § B5a).
 *
 * Usage:  node client3d/scripts/smoke_voiceover_narrator.mjs
 *         (self-bundles through esbuild like its siblings)
 *
 * WHAT WAS WRONG. The filter carried a fixed list of narrator NAMES,
 * `['Storyteller', 'Erzaehler']`. But `speaker` on a storyteller row is a
 * LOCALISED display label: `/play/scene` rewrites it with
 * `t("Storyteller", lang)` before it sends the payload
 * (`app/routes/play.py`), and the translations live in
 * `shared/languages/<lang>.json`. A world in a third language therefore had
 * its narration READ ALOUD as if a person in the room had said it. The server
 * marks the kind separately and unconditionally — `meta.narrator === true` on
 * every storyteller line and on no other one, in every language — and that
 * mark is what `isNarratorLine` now asks. `hud/chatPanel.ts` already decided
 * the picture column this way; this is the same rule in the second place.
 *
 * Hand-derived expectations
 * -------------------------
 * `isNarratorLine` — the mark ALONE, three ways:
 *   [1] {meta:{narrator:true, speaker:'Erzaehler'}}   -> true
 *   [2] {meta:{narrator:true, speaker:'Rakonteur'}}   -> true   the point of
 *       the fix: an unknown language is still the narrator.
 *   [3] {speaker:'Storyteller'} with NO mark          -> false  a character a
 *       world named "Storyteller" is a voice in the room; only the server
 *       decides, and it did not.
 *
 * `speakableLines(lines, 'Kai')` over ONE hand-built transcript of 6 rows.
 * The filter keeps a row when ALL of these hold: `kind` is spoken
 * (in_room | spoken_self | nearby), it is not a narrator row, it carries no
 * note key (display_only | relationship | event_verdict), the speaker is
 * neither empty nor the avatar, and the text is non-empty.
 *
 *   r0 in_room     Mira      "Hallo."              -> KEPT
 *   r1 in_room     Rakonteur "Die Tuer knarrt."   narrator mark -> dropped
 *                            (the OLD code kept this one — the bug)
 *   r2 in_room     Kai       "Ich auch."          the avatar    -> dropped
 *   r3 whisper_meta Mira     "..."                not a spoken kind -> dropped
 *   r4 nearby      Bea       "Von drueben!"        -> KEPT
 *   r5 in_room     Mira      ""                   empty text    -> dropped
 *
 *   [4] the result is exactly two lines, in transcript order:
 *       [{Mira,'Hallo.'}, {Bea,'Von drueben!'}]
 *   [5] the narrator row r1 is absent BY ITS MARK, not by its name — the same
 *       row with speaker 'Storyteller' and no mark would be kept (checked as
 *       its own case, so a re-introduced name list would show up here).
 *   [6] a narrator row that ALSO carries a note key stays dropped (the two
 *       reasons must not cancel).
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
    const bundlePath = '/tmp/smoke_voiceover_narrator_bundled.mjs'
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

  const { isNarratorLine, speakableLines } = await import('../src/game/voiceover.ts')

  const FAILED = []
  function checkTrue(label, ok) {
    console.log(`  ${ok ? 'ok  ' : 'FAIL'} ${label}`)
    if (!ok) FAILED.push(label)
  }
  function checkJson(label, got, want) {
    const ok = JSON.stringify(got) === JSON.stringify(want)
    console.log(`  ${ok ? 'ok  ' : 'FAIL'} ${label}: ${JSON.stringify(got)}`
      + (ok ? '' : `  (expected ${JSON.stringify(want)})`))
    if (!ok) FAILED.push(label)
  }

  const ts = '2026-01-01T00:00:00'
  const row = (kind, speaker, content, meta) => ({ ts, kind, speaker, content, meta })

  console.log('isNarratorLine — the server mark alone')
  checkTrue('[1] marked, German label                -> true',
    isNarratorLine(row('in_room', 'Erzähler', 'x', { narrator: true })) === true)
  checkTrue('[2] marked, label of a third language   -> true',
    isNarratorLine(row('in_room', 'Rakonteur', 'x', { narrator: true })) === true)
  checkTrue('[3] named "Storyteller", NOT marked     -> false',
    isNarratorLine(row('in_room', 'Storyteller', 'x', undefined)) === false)

  console.log('speakableLines — one transcript, avatar "Kai"')
  const lines = [
    row('in_room', 'Mira', 'Hallo.'),
    row('in_room', 'Rakonteur', 'Die Tür knarrt.', { narrator: true }),
    row('in_room', 'Kai', 'Ich auch.'),
    row('whisper_meta', 'Mira', '…'),
    row('nearby', 'Bea', 'Von drüben!'),
    row('in_room', 'Mira', ''),
  ]
  checkJson('[4] two lines, in transcript order', speakableLines(lines, 'Kai'),
    [{ speaker: 'Mira', text: 'Hallo.' }, { speaker: 'Bea', text: 'Von drüben!' }])

  const unmarked = row('in_room', 'Storyteller', 'Die Tür knarrt.')
  checkJson('[5] the same row unmarked IS spoken', speakableLines([unmarked], 'Kai'),
    [{ speaker: 'Storyteller', text: 'Die Tür knarrt.' }])

  const both = row('in_room', 'Rakonteur', 'Kai ⇄ Mira', { narrator: true, relationship: true })
  checkJson('[6] narrator + note key stays dropped', speakableLines([both], 'Kai'), [])

  if (FAILED.length) {
    console.error(`\n${FAILED.length} check(s) FAILED: ${FAILED.join(', ')}`)
    process.exit(1)
  }
  console.log('\nall checks passed')
}

main()
