/**
 * Smoke: filling a prop's TEXTURE SLOTS must never leak into the loader cache.
 *
 * Usage: direct node call, self-bundling via esbuild (run from anywhere):
 *     node scripts/smoke_slot_materials.mjs
 *
 * WHY THIS CHECK EXISTS. `propAssets.loadGlb` keeps ONE `THREE.Group` per URL
 * and hands it to every placement; `Object3D.clone()` copies the nodes but
 * SHARES the material instances. So a routine that writes a picture onto a
 * material by name would paint that picture onto every other placement of the
 * same prop — the hall's poster would appear in the kitchen. The rule is
 * therefore: clone the material FOR THIS PLACEMENT, then write. The decisive
 * assertion below is that two placements built from the same cached group end
 * up with two DIFFERENT material objects.
 *
 * three is a PARAMETER of the routine (package rule), so this runs against a
 * hand-built stub — no WebGL, no DOM, no three install involved. That is also
 * what makes the "same object / different object" question answerable at all:
 * the stub's `clone()` is the only cloner in the picture.
 *
 * The package is TypeScript, so the script bundles itself into /tmp on EVERY
 * run and executes that (same harness as
 * `client3d/scripts/smoke_place_rotation.mjs`, including the esbuild lookup
 * that file fixed on 2026-08-27 — a missing binary must be LOUD, never a
 * silent exit 0).
 */
import { spawnSync } from 'child_process'
import * as fs from 'fs'
import * as path from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

async function main() {
  if (!process.env.SMOKE_BUNDLED) {
    const bundlePath = '/tmp/smoke_slot_materials_bundled.mjs'
    const root = path.join(__dirname, '../')
    const bin = ['client3d/node_modules/.bin/esbuild',
                 'node_modules/.bin/esbuild']
      .map((rel) => path.join(root, rel)).find((p) => fs.existsSync(p))
    if (!bin) {
      console.error('esbuild not found (npm install) — nothing was checked')
      process.exit(1)
    }
    const built = spawnSync(bin, [
      __filename, '--bundle', '--platform=node', '--format=esm',
      `--outfile=${bundlePath}`,
    ], { cwd: root, stdio: 'inherit' })
    if (built.status !== 0) process.exit(built.status ?? 1)
    const run = spawnSync('node', [bundlePath], {
      stdio: 'inherit', env: { ...process.env, SMOKE_BUNDLED: '1' },
    })
    process.exit(run.status ?? 1)
  }

  const { applySlotMaterials, disposeSlotMaterials, GLASS_PRESET,
          MATERIAL_PRESETS } =
    await import('../packages/scene-render/src/slotMaterials.ts')

  const failures = []
  const check = (label, ok, detail = '') => {
    console.log(`  ${ok ? '✓' : '✗'} ${label}${detail ? ` — ${detail}` : ''}`)
    if (!ok) failures.push(label)
  }

  // ── The stub three ────────────────────────────────────────────────────
  // Only what the routine touches. `SRGBColorSpace` and `DoubleSide` are
  // opaque tokens here: what matters is that the routine sets THE ONE three
  // hands it, not some string of its own.
  const THREE = { SRGBColorSpace: 'srgb-token', DoubleSide: 'double-token' }

  let textures = 0
  const loadTexture = (url) => {
    textures += 1
    return { __texture: url, colorSpace: 'linear-token', flipY: true,
             disposed: false, dispose() { this.disposed = true } }
  }

  class FakeMaterial {
    constructor(name, extra = {}) {
      this.name = name
      this.userData = {}
      // three's Color, reduced to what the routine uses: it READS the
      // source tint (to put it back if the picture fails) and WRITES white.
      this.color = { hex: 0x808080, set(v) { this.hex = v },
                     getHex() { return this.hex } }
      this.map = null
      this.transparent = false
      this.opacity = 1
      this.roughness = 1
      this.metalness = 1
      this.needsUpdate = false
      this.disposed = false
      Object.assign(this, extra)
    }
    clone() {
      const m = new FakeMaterial(this.name)
      m.color = { hex: this.color.hex, set(v) { this.hex = v },
                  getHex() { return this.hex } }
      m.userData = { ...this.userData }
      if ('transmission' in this) m.transmission = this.transmission
      return m
    }
    dispose() { this.disposed = true }
  }

  const mesh = (material) => ({ isMesh: true, material })
  /** A group whose meshes SHARE the given material instances — exactly what
   *  `THREE.Group.clone()` produces off the loader cache. */
  const groupOver = (mats) => {
    const meshes = mats.map(mesh)
    return { meshes, traverse(cb) { for (const m of meshes) cb(m) } }
  }

  console.log('\n[1] the picture lands, the rest of the mesh is untouched')
  const wood = new FakeMaterial('wood')
  const picture = new FakeMaterial('picture')
  const g1 = groupOver([wood, picture])
  const clones1 = applySlotMaterials(THREE, g1,
    { picture: { image: '/world/locations/loc/gallery/poster.png' } },
    loadTexture)
  check('the picture material was REPLACED by a clone',
        g1.meshes[1].material !== picture)
  check('...carrying the loaded texture as its map',
        g1.meshes[1].material.map?.__texture
        === '/world/locations/loc/gallery/poster.png',
        String(g1.meshes[1].material.map?.__texture))
  check('the texture is sRGB and NOT flipped (glTF UV convention)',
        g1.meshes[1].material.map.colorSpace === 'srgb-token'
        && g1.meshes[1].material.map.flipY === false,
        `${g1.meshes[1].material.map.colorSpace}/${g1.meshes[1].material.map.flipY}`)
  check('the tint is neutralised so the picture is not multiplied down',
        g1.meshes[1].material.color.hex === 0xffffff,
        String(g1.meshes[1].material.color.hex))
  check('the material NOT named by a slot is the very same object',
        g1.meshes[0].material === wood)
  check('the source material was not written to',
        picture.map === null && picture.color.hex === 0x808080)
  check('exactly one clone is returned for disposal',
        clones1.length === 1 && clones1[0] === g1.meshes[1].material,
        String(clones1.length))

  console.log('\n[2] THE CACHE TEST — two placements, two material instances')
  // Both groups are built over the SAME material objects, which is what the
  // GLB loader cache hands out.
  const shared = [new FakeMaterial('wood'), new FakeMaterial('picture')]
  const a = groupOver(shared)
  const b = groupOver(shared)
  const values = { picture: { image: '/characters/demo/images/portrait.png' } }
  applySlotMaterials(THREE, a, values, loadTexture)
  applySlotMaterials(THREE, b, values, loadTexture)
  check('the two placements do not share the swapped material',
        a.meshes[1].material !== b.meshes[1].material)
  check('...nor the texture object (each owns what it disposes)',
        a.meshes[1].material.map !== b.meshes[1].material.map)
  check('neither of them is the cached material',
        a.meshes[1].material !== shared[1] && b.meshes[1].material !== shared[1])
  check('the cached material is still bare', shared[1].map === null)

  console.log('\n[3] the glass preset — constants, from ONE place')
  const pane = new FakeMaterial('glass', { transmission: 0 })
  const g3 = groupOver([pane])
  const clones3 = applySlotMaterials(THREE, g3, { glass: { preset: 'glass' } },
                                     loadTexture)
  const m3 = g3.meshes[0].material
  check('glass is the preset the package knows',
        MATERIAL_PRESETS.length === 1 && MATERIAL_PRESETS[0] === 'glass',
        MATERIAL_PRESETS.join(','))
  check('the pane is transparent', m3.transparent === true)
  check('opacity/roughness/metalness are the declared constants',
        m3.opacity === GLASS_PRESET.opacity
        && m3.roughness === GLASS_PRESET.roughness
        && m3.metalness === GLASS_PRESET.metalness,
        `${m3.opacity}/${m3.roughness}/${m3.metalness}`)
  check('a material that HAS transmission gets the declared value',
        m3.transmission === GLASS_PRESET.transmission, String(m3.transmission))
  check('the pane is double-sided (a single-sided plane vanishes from behind)',
        m3.side === 'double-token', String(m3.side))
  check('it is a clone, and it is returned',
        m3 !== pane && clones3.length === 1 && clones3[0] === m3)
  // RED PROBE: a material WITHOUT a transmission field must not grow one —
  // three's MeshStandardMaterial ignores the property and the stray key would
  // only lie about what is being drawn.
  const plain = new FakeMaterial('glass')
  const g3b = groupOver([plain])
  applySlotMaterials(THREE, g3b, { glass: { preset: 'glass' } }, loadTexture)
  check('a material without transmission does not grow the field',
        !('transmission' in g3b.meshes[0].material),
        String(g3b.meshes[0].material.transmission))

  console.log('\n[4] what must NOT match')
  const cases = [
    ['an unmatched slot name touches nothing', 'wood',
     { picture: { image: '/world/locations/l/gallery/a.png' } }, false],
    ['a value with neither image nor preset touches nothing', 'picture',
     { picture: {} }, false],
    ['an unknown preset touches nothing', 'glass',
     { glass: { preset: 'mirror' } }, false],
    ['the match is case-insensitive on the MATERIAL name', 'Picture',
     { picture: { image: '/world/locations/l/gallery/a.png' } }, true],
    ['...and on the SLOT name', 'picture',
     { Picture: { image: '/world/locations/l/gallery/a.png' } }, true],
  ]
  for (const [label, matName, values4, shouldSwap] of cases) {
    const src = new FakeMaterial(matName)
    const g = groupOver([src])
    const got = applySlotMaterials(THREE, g, values4, loadTexture)
    check(label, (g.meshes[0].material !== src) === shouldSwap
                 && got.length === (shouldSwap ? 1 : 0),
          `swapped=${g.meshes[0].material !== src}`)
  }
  const empty = new FakeMaterial('picture')
  const gEmpty = groupOver([empty])
  check('no slots at all is a no-op',
        applySlotMaterials(THREE, gEmpty, undefined, loadTexture).length === 0
        && gEmpty.meshes[0].material === empty)

  console.log('\n[5] a mesh with a material ARRAY')
  const arrWood = new FakeMaterial('wood')
  const arrPic = new FakeMaterial('sign')
  const multi = { isMesh: true, material: [arrWood, arrPic] }
  const g5 = { traverse(cb) { cb(multi) } }
  applySlotMaterials(THREE, g5, { sign: { image: '/world/locations/l/gallery/s.png' } },
                     loadTexture)
  check('only the named slot of the array is replaced',
        multi.material[0] === arrWood && multi.material[1] !== arrPic
        && multi.material[1].map?.__texture === '/world/locations/l/gallery/s.png',
        String(multi.material[1].map?.__texture))

  console.log('\n[6] a picture that never arrives puts the material back')
  // The loader's ERROR callback is the routine's own: without it a 404 (a
  // gallery image deleted after the placement was authored) leaves the clone
  // with the neutralised white tint and no map — a bright white rectangle
  // where the modelled surface was. The stub keeps the callback instead of
  // calling it, so the state BEFORE and AFTER the failure are both checkable.
  let failLoad = null
  const failingLoader = (url, onError) => {
    failLoad = onError
    return { __texture: url, colorSpace: 'linear-token', flipY: true,
             disposed: false, dispose() { this.disposed = true } }
  }
  const frame = new FakeMaterial('picture')          // source tint 0x808080
  const g6 = groupOver([frame])
  applySlotMaterials(THREE, g6, { picture: { image: '/world/locations/l/gallery/gone.png' } },
                     failingLoader)
  const m6 = g6.meshes[0].material
  check('while it is loading the clone holds the map and the white tint',
        m6.map?.__texture === '/world/locations/l/gallery/gone.png'
        && m6.color.hex === 0xffffff, String(m6.color.hex))
  m6.needsUpdate = false
  check('the routine handed the loader an error callback',
        typeof failLoad === 'function', String(typeof failLoad))
  failLoad?.()
  check('on error the map is dropped', m6.map === null, String(m6.map))
  check('...the SOURCE tint is restored, not white',
        m6.color.hex === 0x808080, String(m6.color.hex))
  check('...and the material is flagged for an upload', m6.needsUpdate === true)
  check('the source material is still untouched',
        frame.map === null && frame.color.hex === 0x808080)

  console.log('\n[7] disposal frees the clone AND the texture it owns')
  const tex = clones1[0].map
  disposeSlotMaterials(clones1)
  check('the material clone is disposed', clones1[0].disposed === true)
  check('...and its texture with it', tex.disposed === true)
  check('disposing an empty/undefined list is harmless',
        (disposeSlotMaterials([]), disposeSlotMaterials(undefined), true))

  console.log(`\n${failures.length
    ? 'FAILED: ' + failures.join(', ') : 'all checks passed'}`)
  process.exit(failures.length ? 1 : 0)
}

void main()
