#!/usr/bin/env node
/**
 * Ruling A129.9: the attached part alone (`packages/scene-render/src/attachedPart.ts`). Numbers derived BY HAND.
 *
 * Usage: node scripts/smoke_attached_part.mjs   (no server, no world; bundles scene-render with esbuild)
 *
 * FIXTURE. Bones 0 = hips (body), 5 and 6 = the part's chain. Five vertices (4 influences each):
 *   v0: 1.0 on 0              → share 0
 *   v1: 0.6 on 5, 0.4 on 0    → 0.6
 *   v2: 1.0 on 6              → 1.0
 *   v3: 0.5 on 5, 0.5 on 0    → 0.5 (exactly the default share: in)
 *   v4: 0.3 on 6, 0.7 on 0    → 0.3
 *   Triangles: (0,1,2) (1,2,3) (2,3,4) (3,1,2).
 *   [1] share 0.5: (1,2,3) and (3,1,2) are in; (0,1,2) has v0, (2,3,4) has v4 → out. Index = [1,2,3, 3,1,2].
 *   [2] share 0.55: v3 (0.5) drops out → no triangle left.
 *   [3] partBoneNames: groups {chain: op attached_part, bones [b1, b2]}, {hair: no op, bones [h]} → {b1, b2}.
 */
import assert from 'node:assert/strict'
import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '..')
const dir = await mkdtemp(join(ROOT, 'scripts/.smoke-attached-part-'))
let SR
try {
  const esbuild = await import(join(ROOT, 'node_modules/esbuild/lib/main.js'))
  const built = await esbuild.build({
    stdin: { contents: "export * from '@anima/scene-render';", resolveDir: join(ROOT, 'client3d'), loader: 'ts' },
    bundle: true, platform: 'node', format: 'esm', write: false, outfile: join(dir, 'sr.mjs'),
    external: ['three', 'three/*'], logLevel: 'error',
  })
  await writeFile(join(dir, 'sr.mjs'), built.outputFiles[0].text, 'utf8')
  SR = await import(`file://${join(dir, 'sr.mjs')}`)
} finally {
  await rm(dir, { recursive: true, force: true })
}
const skinIndex = [0, 0, 0, 0, 5, 0, 0, 0, 6, 0, 0, 0, 5, 0, 0, 0, 6, 0, 0, 0]
const skinWeight = [1, 0, 0, 0, 0.6, 0.4, 0, 0, 1, 0, 0, 0, 0.5, 0.5, 0, 0, 0.3, 0.7, 0, 0]
const index = [0, 1, 2, 1, 2, 3, 2, 3, 4, 3, 1, 2]
const part = new Set([5, 6])
assert.deepEqual(SR.attachedPartIndex(index, skinIndex, skinWeight, part), [1, 2, 3, 3, 1, 2])   // [1]
assert.deepEqual(SR.attachedPartIndex(index, skinIndex, skinWeight, part, 0.55), [])            // [2]
assert.deepEqual([...SR.partBoneNames({ chain: { op: 'attached_part', bones: ['b1', 'b2'] }, hair: { bones: ['h'] } })],
  ['b1', 'b2'])                                                                                    // [3]
console.log('smoke_attached_part: OK')
