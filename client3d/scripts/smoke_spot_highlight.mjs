#!/usr/bin/env node
/**
 * Smoke check for the POINT LIGHT on a room diorama
 * (`client3d/src/scene/spotHighlight.ts`, plan-diorama-hover.md Task 2):
 * the GLSL text transform and the material patch that carries it.
 *
 * Usage:  node client3d/scripts/smoke_spot_highlight.mjs
 *         (self-bundles through esbuild like its siblings)
 *
 * WHY A UNIFORM PATCH AND NOT A MATERIAL CLONE. A diorama is ONE mesh per
 * room: `highlightProp`'s emissive clone would brighten the whole room
 * instead of the chair under the pointer, and `Material.clone()` copies
 * neither `onBeforeCompile` nor `customProgramCacheKey` — the clone would
 * lose the shell clip (`packages/scene-render/src/clip.ts`) and the depth cut
 * with it. So the spot is three uniforms on the material the diorama already
 * wears, and a hover only writes numbers into them.
 *
 * Hand-derived expectations
 * -------------------------
 * [1] `spotFragment(src)` — the fragment transform. Its ONE anchor is
 *     `#include <emissivemap_fragment>`, the chunk after which
 *     `totalEmissiveRadiance` exists and is still summed:
 *       - the three uniform declarations (`uSpotPoint`, `uSpotRadius`,
 *         `uSpotStrength`) and the `vSpotWorld` varying stand BEFORE
 *         `void main()`, i.e. in the prepended head;
 *       - the `totalEmissiveRadiance +=` line stands directly AFTER the
 *         include line, nowhere else;
 *       - the falloff is the plan's: `1 − smoothstep(r · 0.5, r, distance)`,
 *         so a fragment ON the slot point gets the full colour, one at half
 *         the radius still gets it, and one at or beyond the radius gets
 *         nothing.
 * [2] A source WITHOUT the include is returned UNCHANGED (identity of the
 *     string): a `MeshBasicMaterial` has no emissive channel to add to, and
 *     inventing an anchor would put the line where `totalEmissiveRadiance`
 *     does not exist and break the compile of the whole diorama.
 * [3] IDEMPOTENT: `spotFragment(spotFragment(src)) === spotFragment(src)`.
 *     `onBeforeCompile` runs again on every recompile (a `needsUpdate`, a
 *     LOD swap that re-patches), and a second copy of the uniform block is a
 *     redeclaration error, not a brighter light.
 * [4] `spotVertex(src)` passes the world position through, anchored on
 *     `#include <project_vertex>` — the same anchor `applyClipOutline` uses
 *     for `vClipWorld`, and for the same reason: `transformed` is final
 *     there. Same three properties (head, insert after the anchor,
 *     idempotent, unchanged without the anchor).
 * [5] CHAINING on a stub material that already carries an `onBeforeCompile`
 *     and a `customProgramCacheKey` (the state a clipped diorama material is
 *     in): after `installSpotHighlight`
 *       - both run, OLD FIRST — the clip prepends its own head and the spot
 *         patch must see the shader the clip produced, never the other way
 *         round (the order is recorded by the two patches appending their
 *         names to a list);
 *       - the cache key ENDS on `|spot` and still starts with the old key,
 *         so two materials that differ only in the old key keep two
 *         programs (`'clip:8'` -> `'clip:8|spot'`);
 *         a material WITHOUT a key of its own keeps three's default meaning
 *         (`onBeforeCompile.toString()`), snapshotted from the ORIGINAL hook
 *         — see [8];
 *       - the three uniforms are on `shader.uniforms` after the call;
 *       - the material is NOT cloned (identity) and `needsUpdate` is set.
 * [6] `setSpot(root, point, radius)` writes ONLY uniforms: the point, the
 *     radius and strength 1; `setSpot(root, null, r)` puts strength back to
 *     0 (the "off" state, the value the patch installs). No recompile is
 *     triggered — `needsUpdate` stays false after the install cleared it.
 * [7] A material WITHOUT an emissive channel is never patched (no
 *     `onBeforeCompile` of ours, no cache key, no uniforms): it has no
 *     `totalEmissiveRadiance`, see [2].
 * [8] Installing TWICE patches once — the same recompile argument as [3],
 *     and `rebuildPlaceGlyphs` calls the install on every worldmap poll.
 */
import { spawnSync } from 'child_process'
import * as fs from 'fs'
import * as path from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

async function main() {
  if (!process.env.SMOKE_BUNDLED) {
    const bundlePath = '/tmp/smoke_spot_highlight_bundled.mjs'
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

  const THREE = await import('three')
  const { installSpotHighlight, setSpot, spotFragment, spotVertex } =
    await import('../src/scene/spotHighlight.ts')

  const FAILED = []
  function checkTrue(label, ok) {
    console.log(`  ${ok ? 'ok  ' : 'FAIL'} ${label}`)
    if (!ok) FAILED.push(label)
  }
  function checkEq(label, got, want) {
    const ok = got === want
    console.log(`  ${ok ? 'ok  ' : 'FAIL'} ${label}`
      + (ok ? '' : `\n       expected ${JSON.stringify(want)}`
              + `\n       actual   ${JSON.stringify(got)}`))
    if (!ok) FAILED.push(label)
  }

  // The shape of a three fragment shader as far as this patch cares: a head,
  // `void main()`, and the emissive chunk somewhere inside it.
  const FRAG = [
    'uniform vec3 diffuse;',
    'void main() {',
    '\tvec3 totalEmissiveRadiance = emissive;',
    '\t#include <emissivemap_fragment>',
    '\t#include <lights_fragment_begin>',
    '}',
  ].join('\n')
  const VERT = [
    'void main() {',
    '\t#include <project_vertex>',
    '\t#include <fog_vertex>',
    '}',
  ].join('\n')

  console.log('[1] spotFragment: the head declares, the body adds after the include')
  const frag = spotFragment(FRAG)
  for (const decl of ['uniform vec3 uSpotPoint;', 'uniform float uSpotRadius;',
                      'uniform float uSpotStrength;', 'varying vec3 vSpotWorld;']) {
    checkTrue(`the head declares ${decl}`,
      frag.includes(decl) && frag.indexOf(decl) < frag.indexOf('void main()'))
  }
  const lines = frag.split('\n')
  const at = lines.findIndex((l) => l.includes('#include <emissivemap_fragment>'))
  checkTrue('the emissive line stands directly after the include',
    at >= 0 && lines[at + 1].includes('totalEmissiveRadiance +='))
  checkEq('...and exactly once',
    frag.split('totalEmissiveRadiance +=').length - 1, 1)
  checkTrue('the falloff is 1 − smoothstep(r · 0.5, r, distance)',
    lines[at + 1].includes('smoothstep( uSpotRadius * 0.5, uSpotRadius,'
      + ' distance( vSpotWorld, uSpotPoint ) )')
    && lines[at + 1].includes('1.0 -'))
  checkTrue('...scaled by the strength uniform',
    lines[at + 1].includes('uSpotStrength'))

  console.log('[2] a source without the anchor is returned unchanged')
  checkEq('spotFragment(no include) === the source',
    spotFragment('void main() {}'), 'void main() {}')
  checkEq('spotVertex(no include) === the source',
    spotVertex('void main() {}'), 'void main() {}')

  console.log('[3] the transforms are idempotent')
  checkEq('spotFragment twice === once', spotFragment(frag), frag)
  const vert = spotVertex(VERT)
  checkEq('spotVertex twice === once', spotVertex(vert), vert)

  console.log('[4] spotVertex passes the world position through')
  checkTrue('the head declares the varying',
    vert.includes('varying vec3 vSpotWorld;')
    && vert.indexOf('varying vec3 vSpotWorld;') < vert.indexOf('void main()'))
  const vlines = vert.split('\n')
  const vat = vlines.findIndex((l) => l.includes('#include <project_vertex>'))
  checkTrue('the assignment stands directly after the anchor',
    vat >= 0 && vlines[vat + 1].includes('vSpotWorld = ( modelMatrix'))

  console.log('[5] the patch CHAINS the clip that is already on the material')
  const order = []
  const stub = new THREE.MeshStandardMaterial()
  stub.onBeforeCompile = (shader) => {
    order.push('clip')
    shader.fragmentShader = `// clip head\n${shader.fragmentShader}`
  }
  stub.customProgramCacheKey = () => 'clip:8'
  stub.needsUpdate = false
  const mesh = new THREE.Mesh(new THREE.BufferGeometry(), stub)
  const root = new THREE.Group()
  root.add(mesh)
  installSpotHighlight(root)
  checkTrue('the material is not cloned', mesh.material === stub)
  checkTrue('needsUpdate was raised', stub.version > 0)
  checkEq('the cache key extends the old one', stub.customProgramCacheKey(), 'clip:8|spot')
  const shader = { uniforms: {}, vertexShader: VERT, fragmentShader: FRAG }
  stub.onBeforeCompile(shader)
  order.push('spot')
  checkEq('the old patch ran FIRST', order.join('>'), 'clip>spot')
  checkTrue('the clip head survives', shader.fragmentShader.includes('// clip head'))
  checkTrue('...and the spot line was added on top',
    shader.fragmentShader.includes('totalEmissiveRadiance +='))
  for (const u of ['uSpotPoint', 'uSpotRadius', 'uSpotStrength']) {
    checkTrue(`shader.uniforms.${u} is bound`, !!shader.uniforms[u])
  }
  checkEq('the light is OFF until a hover asks for it',
    shader.uniforms.uSpotStrength.value, 0)

  console.log('[6] setSpot writes uniforms only')
  const before = stub.version
  setSpot(root, new THREE.Vector3(1, 2, 3), 0.6)
  checkEq('the point', [shader.uniforms.uSpotPoint.value.x,
    shader.uniforms.uSpotPoint.value.y, shader.uniforms.uSpotPoint.value.z].join(','), '1,2,3')
  checkEq('the radius', shader.uniforms.uSpotRadius.value, 0.6)
  checkEq('the strength', shader.uniforms.uSpotStrength.value, 1)
  setSpot(root, null, 0.6)
  checkEq('null puts the strength back to 0', shader.uniforms.uSpotStrength.value, 0)
  checkEq('no recompile was triggered', stub.version, before)

  console.log('[7] a material without an emissive channel is left alone')
  const basic = new THREE.MeshBasicMaterial()
  const plain = new THREE.Mesh(new THREE.BufferGeometry(), basic)
  const root2 = new THREE.Group()
  root2.add(plain)
  const untouched = basic.onBeforeCompile
  installSpotHighlight(root2)
  checkTrue('onBeforeCompile untouched', basic.onBeforeCompile === untouched)
  checkTrue('no cache key of its own', !Object.hasOwn(basic, 'customProgramCacheKey'))

  console.log('[8] installing twice patches once')
  const twice = new THREE.MeshStandardMaterial()
  const m2 = new THREE.Mesh(new THREE.BufferGeometry(), twice)
  const root3 = new THREE.Group()
  root3.add(m2)
  // Three's DEFAULT `customProgramCacheKey` returns `onBeforeCompile.toString()`
  // — the ORIGINAL hook's source, snapshotted before the chain replaced it.
  // Read afterwards it would answer the spot patch's own source, and two
  // materials with different compile hooks would share one program.
  const original = twice.onBeforeCompile
  installSpotHighlight(root3)
  const patchedHook = twice.onBeforeCompile
  installSpotHighlight(root3)
  checkTrue('the same patch is still on the material', twice.onBeforeCompile === patchedHook)
  checkEq('the cache key was extended once, over the ORIGINAL hook',
    twice.customProgramCacheKey(), `${original.toString()}|spot`)

  if (FAILED.length) {
    console.error(`\n${FAILED.length} check(s) FAILED: ${FAILED.join(', ')}`)
    process.exit(1)
  }
  console.log('\nall spot-highlight checks passed')
}

main().catch((e) => { console.error(e); process.exit(1) })
