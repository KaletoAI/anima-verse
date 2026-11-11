#!/usr/bin/env node
/** Game-Admin -> Setup: a schema select shows its `choice_labels` (plan 2026-11-09-hairdeck-hair, Task 4 fix 1).
 *
 * Usage:  node scripts/smoke_setup_choice_labels.mjs   (from the repo root; bundles with node_modules/esbuild)
 *
 * Expected, by hand from the schema field `base_body.hair_method` (choices ["body", "edit_chain", "hairdeck",
 * "subtract"] — `body` first, the default since the hair-from-body spec 2026-11-11 — choice_labels
 * {body: "From the body mesh", edit_chain: "Hair views → mesh (image edits + one mesh)",
 *  hairdeck: "HairDeck (one image → hair cards)", subtract: "Subtract (haired mesh − bald base)"}):
 *   1. The world schema the Setup page receives (config_scope.schema_for(WORLD), read through Python) still
 *      carries exactly those choices and labels.
 *   2. selectOptions(choices, labels) -> [{value "body", label "From the body mesh"}, {value "edit_chain",
 *      label "Hair views → mesh (image edits + one mesh)"}, {value "hairdeck", label "HairDeck (one image →
 *      hair cards)"}, {value "subtract", label "Subtract (haired mesh − bald base)"}] — the VALUE stays the raw
 *      choice.
 *   3. Without labels (or a choice the labels miss) the label is the choice itself: [1, "b"] with {b: "Bee"}
 *      -> [{1, "1"}, {"b", "Bee"}]; no choices -> [].
 *   4. The Setup field renderer (SchemaNode.tsx) builds its <option>s from selectOptions(field.choices,
 *      field.choice_labels) and declares `choice_labels` on its field type (source check: the renderer is
 *      what the user sees, and a JSX render needs no DOM for this one map).
 */
import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

const CHOICES = ['body', 'edit_chain', 'hairdeck', 'subtract']
const LABELS = {
  body: 'From the body mesh',
  edit_chain: 'Hair views → mesh (image edits + one mesh)',
  hairdeck: 'HairDeck (one image → hair cards)',
  subtract: 'Subtract (haired mesh − bald base)',
}

if (!process.env.SETUP_CHOICE_LABELS_BUNDLED) {
  const tmp = mkdtempSync(join(tmpdir(), 'setup-choice-labels-'))
  try {
    const py = spawnSync('./.venv/bin/python', ['-c', [
      'import json',
      'from app.core import config_scope',
      'f = config_scope.schema_for(config_scope.WORLD)["base_body"]["fields"]["hair_method"]',
      'print(json.dumps({"choices": f["choices"], "choice_labels": f.get("choice_labels")}))',
    ].join('\n')], { encoding: 'utf8', env: { ...process.env, STORAGE_DIR: tmp, INSTANCE_DIR: tmp } })
    assert.equal(py.status, 0, py.stderr)
    const field = JSON.parse(py.stdout.trim().split('\n').pop())
    assert.deepEqual(field, { choices: CHOICES, choice_labels: LABELS })
    const output = join(tmp, 'smoke.mjs')
    const built = spawnSync('node_modules/esbuild/bin/esbuild', [fileURLToPath(import.meta.url), '--bundle',
      '--platform=node', '--format=esm', `--outfile=${output}`], { stdio: 'inherit' })
    assert.equal(built.status, 0)
    const run = spawnSync('node', [output], { stdio: 'inherit',
      env: { ...process.env, SETUP_CHOICE_LABELS_BUNDLED: '1', SETUP_FIELD: JSON.stringify(field) } })
    process.exitCode = run.status ?? 1
  } finally { rmSync(tmp, { recursive: true, force: true }) }
} else {
  const { selectOptions } = await import('../frontend/src/tabs/setup/schemaValues.ts')
  const field = JSON.parse(process.env.SETUP_FIELD)
  assert.deepEqual(selectOptions(field.choices, field.choice_labels),
    CHOICES.map(value => ({ value, label: LABELS[value] })))
  assert.deepEqual(selectOptions([1, 'b'], { b: 'Bee' }), [{ value: 1, label: '1' }, { value: 'b', label: 'Bee' }])
  assert.deepEqual(selectOptions(['x']), [{ value: 'x', label: 'x' }])
  assert.deepEqual(selectOptions(undefined, LABELS), [])
  const source = readFileSync('frontend/src/tabs/setup/SchemaNode.tsx', 'utf8')
  assert.match(source, /selectOptions\(field\.choices, field\.choice_labels\)\.map\(option =>\s*<option key=\{option\.value\} value=\{option\.value\}>\{option\.label\}<\/option>/)
  assert.match(source, /choice_labels\?: Record<string, string>/)
  console.log('PASS setup choice labels: schema labels reach the Setup select, value stays the raw choice')
}
