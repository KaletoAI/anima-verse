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
  // The mirror's own module, for the two questions `applySlotMaterials` alone
  // cannot answer: WHICH faces were measured, and does a second attach on the
  // same pane free the first.
  const { attachMirror, disposeMirror, mirrorPlaneOf } =
    await import('../packages/scene-render/src/mirrorSurface.ts')

  /** Run `fn` with console.warn captured; returns everything it said. */
  const capturingWarnings = (fn) => {
    const said = []
    const real = console.warn
    console.warn = (...args) => { said.push(args.join(' ')) }
    try { fn() } finally { console.warn = real }
    return said
  }

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
  check('glass is the first preset the package knows',
        MATERIAL_PRESETS[0] === 'glass', MATERIAL_PRESETS.join(','))
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
     { glass: { preset: 'chrome' } }, false],
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

  console.log('\n[8] a material `slot_<name>` IS the slot `<name>`')
  // The server already strips the prefix: `detect_slots` turns the GLB
  // material `slot_picture_1` into the slot `picture_1`, and the recipe keys
  // `models[].slots` by that SLOT name. A split picture prop therefore always
  // arrives as `{picture_1: …, glass_1: …}` over materials that still carry
  // the prefix — so the lookup has to strip it here too, or neither renderer
  // ever hangs the picture (Befund 2026-08-27, Ruling R11).
  // Hand-derived: materials ["wood", "slot_picture_1", "slot_glass_1"] with
  // slots {picture_1: {image}, glass_1: {preset:"glass"}} → the two prefixed
  // materials are replaced by clones (map / glass preset), "wood" stays the
  // very same object, and exactly 2 clones come back.
  const w8 = new FakeMaterial('wood')
  const pic8 = new FakeMaterial('slot_picture_1')
  const gls8 = new FakeMaterial('slot_glass_1', { transmission: 0 })
  const g8 = groupOver([w8, pic8, gls8])
  const clones8 = applySlotMaterials(THREE, g8, {
    picture_1: { image: '/world/locations/demo/gallery/x.png' },
    glass_1: { preset: 'glass' },
  }, loadTexture)
  check('`slot_picture_1` is filled by the payload key `picture_1`',
        g8.meshes[1].material !== pic8
        && g8.meshes[1].material.map?.__texture
           === '/world/locations/demo/gallery/x.png',
        String(g8.meshes[1].material.map?.__texture))
  check('`slot_glass_1` is filled by the payload key `glass_1`',
        g8.meshes[2].material !== gls8
        && g8.meshes[2].material.transparent === true
        && g8.meshes[2].material.transmission === GLASS_PRESET.transmission,
        String(g8.meshes[2].material.transmission))
  check('the unprefixed `wood` is the very same object',
        g8.meshes[0].material === w8)
  check('exactly two clones come back', clones8.length === 2,
        String(clones8.length))

  // The RAW material name must NOT be required as the key — that is the shape
  // the server never sends, and demanding it is the defect itself.
  const pic8b = new FakeMaterial('slot_picture_1')
  const g8b = groupOver([pic8b])
  applySlotMaterials(THREE, g8b,
    { slot_picture_1: { image: '/world/locations/demo/gallery/x.png' } },
    loadTexture)
  check('ROTE PROBE: the raw name `slot_picture_1` as a key matches nothing',
        g8b.meshes[0].material === pic8b)

  // ...and the prefix is a PREFIX, not a substring: only one leading `slot_`
  // goes, and only when the underscore is really there.
  const near = new FakeMaterial('slotpicture_1')
  const gNear = groupOver([near])
  check('ROTE PROBE: `slotpicture_1` (no underscore) is not the slot `picture_1`',
        applySlotMaterials(THREE, gNear,
          { picture_1: { image: '/world/locations/demo/gallery/x.png' } },
          loadTexture).length === 0
        && gNear.meshes[0].material === near)
  const twice = new FakeMaterial('slot_slot_sign')
  const gTwice = groupOver([twice])
  check('exactly ONE prefix is stripped: `slot_slot_sign` is the slot `slot_sign`',
        applySlotMaterials(THREE, gTwice,
          { slot_sign: { image: '/world/locations/demo/gallery/s.png' } },
          loadTexture).length === 1
        && gTwice.meshes[0].material !== twice)
  // The server trims BEHIND the prefix as well (`props.detect_slots`), so a
  // modeller's `slot_ picture_1` is the same slot, not a name with a space.
  const spaced = new FakeMaterial('slot_ picture_1')
  const gSpaced = groupOver([spaced])
  check('...and the name behind the prefix is trimmed, like on the server',
        applySlotMaterials(THREE, gSpaced,
          { picture_1: { image: '/world/locations/demo/gallery/x.png' } },
          loadTexture).length === 1
        && gSpaced.meshes[0].material !== spaced)

  console.log('\n[9] preset "mirror" turns the pane into a reflector on its own faces')
  // The mirror path constructs a handful of three classes; each stub below
  // records what it was given and nothing more. `renderMirror` is never CALLED
  // here (the hook is only installed), so only the constructor path has to run.
  class StubVec3 { constructor(x = 0, y = 0, z = 0) { this.x = x; this.y = y; this.z = z }
    set(x, y, z) { this.x = x; this.y = y; this.z = z; return this } copy(v) { return this.set(v.x, v.y, v.z) } }
  class StubRT { constructor(w, h, o) { this.width = w; this.height = h; this.options = o; this.texture = { rt: this }; this.disposed = false } dispose() { this.disposed = true } }
  class StubShaderMaterial extends FakeMaterial {
    constructor(params) { super('shader'); this.isShaderMaterial = true; Object.assign(this, params); this.uniforms = params.uniforms }
    clone() { const m = new StubShaderMaterial({ ...this, uniforms: { ...this.uniforms } }); m.userData = JSON.parse(JSON.stringify(this.userData)); return m }
  }
  const THREE2 = {
    ...THREE, HalfFloatType: 'half-token',
    Vector3: StubVec3, Vector4: StubVec3, Matrix4: class { set() { return this } multiply() { return this } copy() { return this } extractRotation() { return this } },
    Matrix3: class { getNormalMatrix() { return this } }, Plane: class { setFromNormalAndCoplanarPoint() { return this } applyMatrix4() { return this } },
    Color: class { constructor(hex) { this.hex = hex } }, WebGLRenderTarget: StubRT, ShaderMaterial: StubShaderMaterial,
    UniformsUtils: { clone: (u) => JSON.parse(JSON.stringify(u)) },
  }
  // A mesh with TWO material groups: the frame (group 0) and the pane
  // (group 1, the rectangle of scripts/smoke_mirror_plane.mjs [1]).
  const mirrorFrame = new FakeMaterial('wood')
  const mirrorPane = new FakeMaterial('slot_glass_1')
  const mirrorGeometry = {
    attributes: { position: { array: new Float32Array([0, 0, 5, 1, 0, 5, 0, 1, 5,
      -0.15, -0.2, 0.2, 0.35, -0.2, 0.2, 0.35, 0.8, 0.2, -0.15, 0.8, 0.2]), count: 7 } },
    index: { array: new Uint16Array([0, 1, 2, 3, 4, 5, 3, 5, 6]), count: 9 },
    groups: [{ start: 0, count: 3, materialIndex: 0 }, { start: 3, count: 6, materialIndex: 1 }],
  }
  const before = () => {}
  const mirrorMesh = { isMesh: true, material: [mirrorFrame, mirrorPane], geometry: mirrorGeometry,
                       onBeforeRender: before, visible: true }
  const g9 = { traverse(cb) { cb(mirrorMesh) } }
  const clones9 = applySlotMaterials(THREE2, g9, { glass_1: { preset: 'mirror' } }, loadTexture,
                                     { textureSize: 256, maxPerFrame: 1, maxDistanceM: 9 })
  const mirrorMat = mirrorMesh.material[1]
  check('the pane material became a ShaderMaterial', mirrorMat.isShaderMaterial === true)
  check('...marked with its slot name (JSON-safe, survives Material.copy)', mirrorMat.userData.__mirror === 'glass_1')
  check('...and counted as a slot clone', mirrorMat.userData.__slotClone === true)
  check('the frame material is the very same object', mirrorMesh.material[0] === mirrorFrame)
  check('the source pane material was not written to', mirrorPane.map === null && !mirrorPane.isShaderMaterial)
  check('the render target uses the option size', mirrorMat.uniforms.tDiffuse.value.rt.width === 256, String(mirrorMat.uniforms.tDiffuse.value.rt?.width))
  check('the pane is double-sided (both sides of a mirror reflect)',
        mirrorMat.side === 'double-token', String(mirrorMat.side))
  check('the mesh got a render hook chained in front of its own', typeof mirrorMesh.onBeforeRender === 'function' && mirrorMesh.onBeforeRender !== before)
  check('exactly one clone is returned', clones9.length === 1 && clones9[0] === mirrorMat)
  // WHICH faces were measured. Group 1 is the rectangle of
  // scripts/smoke_mirror_plane.mjs [1] — centroid (0.1, 0.3, 0.2), normal
  // (0, 0, ±1). Group 0 is a triangle at z = 5; measuring the WHOLE mesh
  // instead of the pane's own group would put the centroid near z ≈ 1.8 and
  // is exactly the defect this assertion exists for.
  const info9 = mirrorPlaneOf(mirrorMat)
  const nearAt = (a, b) => Math.abs(a - b) <= 1e-6
  check('the plane is the PANE\'s group, not the whole mesh',
        !!info9 && nearAt(info9.plane.point[0], 0.1)
        && nearAt(info9.plane.point[1], 0.3) && nearAt(info9.plane.point[2], 0.2)
        && nearAt(Math.abs(info9.plane.normal[2]), 1),
        JSON.stringify(info9?.plane))
  check('the cost options reached the state', info9?.maxPerFrame === 1
        && info9?.maxDistanceM === 9,
        `${info9?.maxPerFrame}/${info9?.maxDistanceM}`)
  const rt9 = mirrorMat.uniforms.tDiffuse.value.rt
  disposeSlotMaterials(clones9)
  check('dispose frees the render target and the material', rt9.disposed === true && mirrorMat.disposed === true)
  check('after dispose the mesh hook is the original again', mirrorMesh.onBeforeRender === before)
  check('...and the material no longer answers as a mirror',
        mirrorPlaneOf(mirrorMat) === undefined)

  console.log('\n[10] a pane without measurable faces stays as modelled')
  const flatPane = new FakeMaterial('glass')
  const degenerate = { isMesh: true, material: flatPane, geometry: {
    attributes: { position: { array: new Float32Array([1, 1, 1, 1, 1, 1, 1, 1, 1]), count: 3 } }, index: null, groups: [] },
    onBeforeRender: before, visible: true }
  let clones10 = []
  const said10 = capturingWarnings(() => {
    clones10 = applySlotMaterials(THREE2, { traverse(cb) { cb(degenerate) } }, { glass: { preset: 'mirror' } }, loadTexture)
  })
  check('material untouched, nothing returned', degenerate.material === flatPane && clones10.length === 0)
  check('...and no hook was installed', degenerate.onBeforeRender === before)
  // Silence here would be the worst answer available: the author picked
  // `mirror` in the admin and would see a plain pane with nothing anywhere to
  // say that the MODEL is the problem, not the setting.
  check('...but it SAID so, once, naming the slot and the reason',
        said10.length === 1 && said10[0].includes('mirror slot "glass"')
        && said10[0].includes('no face of the group has any area')
        && said10[0].includes('left as modelled'),
        JSON.stringify(said10))

  console.log('\n[11] the preset list names mirror after glass')
  check('MATERIAL_PRESETS = [glass, mirror]', JSON.stringify(MATERIAL_PRESETS) === '["glass","mirror"]', JSON.stringify(MATERIAL_PRESETS))

  console.log('\n[12] attaching the same pane twice frees the first one')
  // A re-applied placement can hand the same mesh+slot to `attachMirror`
  // again. Without a guard the first render target would leak and the mesh's
  // hook bookkeeping would count a state no material points at any more — so
  // ONE dispose would no longer be enough to unhook the mesh.
  const reFrame = new FakeMaterial('wood')
  const rePane = new FakeMaterial('slot_glass_1')
  const reMesh = { isMesh: true, material: [reFrame, rePane], geometry: mirrorGeometry,
                   onBeforeRender: before, visible: true }
  const first = attachMirror(THREE2, reMesh, rePane, 1, 'glass_1', { textureSize: 64 })
  const firstRt = first.uniforms.tDiffuse.value.rt
  const second = attachMirror(THREE2, reMesh, rePane, 1, 'glass_1', { textureSize: 32 })
  check('the mesh carries the second material now',
        second !== null && second !== first && reMesh.material[1] === second)
  check('the first pane was freed — render target AND material',
        firstRt.disposed === true && first.disposed === true)
  check('...and no longer answers as a mirror', mirrorPlaneOf(first) === undefined)
  check('the second one does, with its own defaults',
        mirrorPlaneOf(second)?.maxPerFrame === Infinity
        && mirrorPlaneOf(second)?.maxDistanceM === Infinity,
        JSON.stringify(mirrorPlaneOf(second)))
  disposeMirror(second)
  check('ONE dispose is enough to unhook the mesh (no stale state left over)',
        reMesh.onBeforeRender === before)

  console.log(`\n${failures.length
    ? 'FAILED: ' + failures.join(', ') : 'all checks passed'}`)
  process.exit(failures.length ? 1 : 0)
}

void main()
