/**
 * Smoke: WHICH mesh a placement shows when a prop has several model variants.
 *
 * Usage: direct node call, self-bundling via esbuild:
 *     node client3d/scripts/smoke_model_variant.mjs
 *
 * The package is TypeScript, so the script bundles itself on first run and
 * then executes the bundled version (set REBUNDLE=1 to force re-bundling).
 *
 * Runs headless against the SHARED `pickModelVariant` — the one routine both
 * renderers use to turn a placement spec into a URL (§ B2 addendum,
 * "Nachtrag 2026-08-19"). No three.js, no DOM: this is string arithmetic.
 *
 * The rule, and every expected value below derived by hand from it:
 *
 *   1. Without `model_variants` the answer is character for character the old
 *      `pickVariant(spec.variants, tier)` — a prop with ONE variant must not
 *      notice that the list exists.
 *   2. With `model_variants`, the map at index `variant` is taken FIRST, the
 *      resolution tier out of that map SECOND. Both steps, in that order.
 *   3. `variants` is `model_variants[0]` by contract, so `variant: 0` and a
 *      missing `variant` both answer with the primary variant's URL.
 *   4. The index is MODULO, not clamped, and negative indices wrap forward:
 *      the variant count moves when an admin adds or deletes a mesh, and a
 *      placement must not disappear because of it.
 *   5. The tier fallback of `pickVariant` still applies INSIDE the chosen
 *      variant: a variant without `low` answers with its `full` URL, it never
 *      falls through to another variant's low mesh (that would draw a
 *      different object at distance).
 */

import { spawnSync } from 'child_process'
import * as fs from 'fs'
import * as path from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

async function main() {
  if (!process.env.SMOKE_BUNDLED) {
    const bundlePath = '/tmp/smoke_model_variant_bundled.mjs'
    const needsBundle = !fs.existsSync(bundlePath) || process.env.REBUNDLE
    if (needsBundle) {
      const esbuildResult = spawnSync('node_modules/.bin/esbuild', [
        __filename,
        '--bundle',
        '--platform=node',
        '--format=esm',
        `--outfile=${bundlePath}`,
      ], { cwd: path.join(__dirname, '../../'), stdio: 'inherit' })
      if (esbuildResult.status !== 0) process.exit(esbuildResult.status)
    }
    const runResult = spawnSync('node', [bundlePath], {
      stdio: 'inherit',
      env: { ...process.env, SMOKE_BUNDLED: '1' },
    })
    process.exit(runResult.status)
  }

  const { pickModelVariant, pickVariant } =
    await import('../../packages/scene-render/src/types.ts')

  const FAILED = []
  function check(label, got, want) {
    const ok = got === want
    console.log(`  ${ok ? 'ok  ' : 'FAIL'} ${label}: ${got || '(empty)'}`
      + (ok ? '' : `  (expected ${want || '(empty)'})`))
    if (!ok) FAILED.push(label)
  }

  // The payload of a prop with THREE active variants, exactly as
  // `app/core/scene_recipe.py _prop_models` writes it: the primary variant
  // keeps the bare URL, the others carry `?variant=<store index>&tier=<t>`.
  // Variant 1 was switched off in the admin, so the store indices in the URLs
  // are 0, 2, 3 while the LIST positions are 0, 1, 2.
  const P = '/assets/props/pine-abc123/model'
  const primary = { full: `${P}?tier=full`, low: `${P}?tier=low` }
  const second = { full: `${P}?variant=2&tier=full`, low: `${P}?variant=2&tier=low` }
  const third = { full: `${P}?variant=3&tier=full` }          // no low mesh yet
  const spec = (variant) => ({
    variants: primary,
    model_variants: [primary, second, third],
    ...(variant === undefined ? {} : { variant }),
  })

  console.log('\n[1] a prop with ONE variant is untouched by the feature')
  const lone = { variants: primary }
  check('no model_variants -> the plain tier map, full',
    pickModelVariant(lone, 'full'), `${P}?tier=full`)
  check('no model_variants -> the plain tier map, low',
    pickModelVariant(lone, 'low'), `${P}?tier=low`)
  check('...identical to pickVariant, character for character',
    pickModelVariant(lone, 'low'), pickVariant(lone.variants, 'low'))
  check('an EMPTY list is no list either',
    pickModelVariant({ variants: primary, model_variants: [] }, 'full'),
    `${P}?tier=full`)

  console.log('\n[2] variant first, tier second')
  check('variant 0, full = the primary bare URL',
    pickModelVariant(spec(0), 'full'), `${P}?tier=full`)
  check('variant 0, low  = the primary bare URL',
    pickModelVariant(spec(0), 'low'), `${P}?tier=low`)
  check('variant 1, full = list position 1 = store index 2',
    pickModelVariant(spec(1), 'full'), `${P}?variant=2&tier=full`)
  check('variant 1, low  = the same variant, its own low mesh',
    pickModelVariant(spec(1), 'low'), `${P}?variant=2&tier=low`)
  check('variant 2, full = list position 2 = store index 3',
    pickModelVariant(spec(2), 'full'), `${P}?variant=3&tier=full`)

  console.log('\n[3] a missing index is the primary variant')
  check('no variant field at all', pickModelVariant(spec(undefined), 'full'),
    `${P}?tier=full`)
  check('...and that IS spec.variants (the primary-variant contract)',
    pickModelVariant(spec(undefined), 'full'), pickVariant(primary, 'full'))
  check('a non-number is 0, not NaN',
    pickModelVariant({ ...spec(0), variant: 'x' }, 'full'), `${P}?tier=full`)

  console.log('\n[4] the index wraps (3 variants): modulo, not clamp')
  // Hand-derived: 3 mod 3 = 0, 4 mod 3 = 1, 7 mod 3 = 1, -1 -> 2, -4 -> 2.
  check('3 -> 0', pickModelVariant(spec(3), 'full'), `${P}?tier=full`)
  check('4 -> 1', pickModelVariant(spec(4), 'full'), `${P}?variant=2&tier=full`)
  check('7 -> 1', pickModelVariant(spec(7), 'full'), `${P}?variant=2&tier=full`)
  check('-1 -> 2', pickModelVariant(spec(-1), 'full'), `${P}?variant=3&tier=full`)
  check('-4 -> 2', pickModelVariant(spec(-4), 'full'), `${P}?variant=3&tier=full`)

  console.log('\n[5] the tier fallback stays INSIDE the chosen variant')
  check('variant 2 has no low -> its own full mesh',
    pickModelVariant(spec(2), 'low'), `${P}?variant=3&tier=full`)
  check('...never another variant\'s low mesh',
    pickModelVariant(spec(2), 'low') === `${P}?tier=low` ? 'leaked' : 'contained',
    'contained')
  check('an unknown tier falls back the same way',
    pickModelVariant(spec(1), 'ultra'), `${P}?variant=2&tier=full`)

  console.log('\n[6] the scatter arrangement, end to end')
  // The server resolves `(scatter_seed + instance) mod count` (§ B2 addendum);
  // the renderer only reads the number. Hand calculation for seed 7, 3
  // variants, instances 0..5:  1, 2, 0, 1, 2, 0.
  const wanted = [1, 2, 0, 1, 2, 0]
  const urls = wanted.map((v) => pickModelVariant(spec(v), 'full'))
  const byIndex = [`${P}?tier=full`, `${P}?variant=2&tier=full`,
    `${P}?variant=3&tier=full`]
  check('six copies -> the 1,2,0,1,2,0 arrangement of meshes',
    urls.join(' | '), wanted.map((v) => byIndex[v]).join(' | '))
  check('...which is exactly two of each',
    [0, 1, 2].map((v) => urls.filter((u) => u === byIndex[v]).length).join(','),
    '2,2,2')

  console.log()
  if (FAILED.length) {
    console.log(`FAILED (${FAILED.length}): ${FAILED.join('; ')}`)
    process.exit(1)
  }
  console.log('all checks passed')
}

main()
