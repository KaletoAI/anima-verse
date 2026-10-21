#!/usr/bin/env node
/** Hand-derived visibility: two AND conditions admit exactly the inset/neutral
 * profile; null admits an empty type. Changing type hides the control while its
 * stored value remains medium. Scalar conditions use trimmed, case-insensitive text matching.
 */
import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

if (!process.env.BODY_VISIBILITY_BUNDLED) {
  const tmp = mkdtempSync(join(tmpdir(), 'body-visibility-'))
  try {
    const output = join(tmp, 'smoke.mjs')
    const built = spawnSync('node_modules/esbuild/bin/esbuild', [fileURLToPath(import.meta.url), '--bundle', '--platform=node', '--format=esm', `--outfile=${output}`], { stdio: 'inherit' })
    assert.equal(built.status, 0)
    const run = spawnSync('node', [output], { stdio: 'inherit', env: { ...process.env, BODY_VISIBILITY_BUNDLED: '1' } })
    process.exitCode = run.status ?? 1
  } finally { rmSync(tmp, { recursive: true, force: true }) }
} else {
  const { bodyAttributeVisible } = await import('../frontend/src/lib/bodyAttributeVisibility.ts')
  const conditions = { 'attributes.type': ['inset', null], category: ['neutral'] }
  const values = { type: 'inset', inner_size: 'medium' }
  assert.equal(bodyAttributeVisible(conditions, values, { category: 'neutral' }), true)
  assert.equal(bodyAttributeVisible(conditions, { ...values, type: 'attached' }, { category: 'neutral' }), false)
  assert.equal(values.inner_size, 'medium')
  for (const type of ['', null, undefined]) assert.equal(bodyAttributeVisible(conditions, { type }, { category: 'neutral' }), true)
  assert.equal(bodyAttributeVisible(conditions, values, { category: 'other' }), false)
  assert.equal(bodyAttributeVisible(undefined, {}, {}), true)
  assert.equal(bodyAttributeVisible({ category: [null] }, {}, {}), true)
  assert.equal(bodyAttributeVisible({ category: ['0'] }, {}, { category: 0 }), true)
  assert.equal(bodyAttributeVisible({ category: ['NEUTRAL'] }, {}, { category: ' neutral ' }), true)
  console.log('PASS body attribute visibility: live type, empty/null, profile AND, retained value')
}
