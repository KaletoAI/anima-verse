#!/usr/bin/env node
/**
 * Reference values for the native client's rest-pose correction, computed by
 * the BROWSER'S OWN CODE: `restPoseOf` / `restCorrections` / `bindRelativeValues`
 * of `packages/scene-render/src/clipRetarget.ts` (what client3d's
 * `figures.fitLibraryAsync` → `adaptExternalClips` runs), on three.js' own
 * loaders, with the same files the native `--check` uses:
 *
 *   donor rest   shared/models/rig/reference.fbx          (= /assets/animation-rig)
 *   targets      three tracked demo-world bakes (images stripped before parsing —
 *                node has no image decoder; geometry, skin and skeleton untouched):
 *                Minerva McGonagall (the --check figure; no stance rule fires),
 *                Johanna Falk (the LEG stance fires), Rubeus Hagrid (the FOOT stance fires)
 *   clips        shared/models/clips/idle.fbx, shared/models/clips/walk.fbx
 *
 * Output: native/fixtures/rest_reference.json — per target model: which bones
 * got a correction and which a stance rule (leg/torso/foot) changed, and per
 * clip and sample time the clip's raw local quaternion and the corrected one
 * `q = K_p⁻¹·c·K_b` for a set of bones (xyzw — three's convention = Godot's).
 * `Check/CheckRunner.cs` demands its own retarget to land within 0.5° of these.
 *
 * Usage (from the repository root, needs `npm install` for three + esbuild):
 *   node native/fixtures/rest_reference.mjs
 * It bundles itself with esbuild (the TypeScript source is imported directly),
 * the same way scripts/smoke_clip_retarget.mjs does. Read-only on every input.
 */
import { spawnSync } from 'child_process'
import * as fs from 'fs'
import * as path from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)
const ROOT = path.join(__dirname, '../../')

const BONES = ['Hips', 'Spine', 'Spine2', 'Neck', 'Head', 'LeftShoulder', 'LeftArm', 'RightArm', 'RightForeArm',
  'RightHand', 'RightHandIndex2', 'LeftUpLeg', 'LeftLeg', 'RightLeg', 'LeftFoot', 'RightToeBase']
const MODELS = [
  { name: 'Minerva McGonagall', file: 'worlds/demo/characters/Minerva McGonagall/model3d/aa1f6d51558d.glb' },
  { name: 'Johanna Falk', file: 'worlds/demo/characters/Johanna Falk/model3d/b852a46d5ffc.glb' },
  { name: 'Rubeus Hagrid', file: 'worlds/demo/characters/Rubeus Hagrid/model3d/a4595b432ee3.glb' },
]
const SAMPLES = [{ clip: 'idle', file: 'shared/models/clips/idle.fbx', times: [0, 5] },
                 { clip: 'walk', file: 'shared/models/clips/walk.fbx', times: [0, 0.4] }]

async function main() {
  if (!process.env.REST_REFERENCE_BUNDLED) {
    const bundlePath = '/tmp/anima_native_rest_reference_bundled.mjs'
    const bin = ['client3d/node_modules/.bin/esbuild', 'frontend/node_modules/.bin/esbuild', 'node_modules/.bin/esbuild']
      .map((rel) => path.join(ROOT, rel)).find((p) => fs.existsSync(p))
    if (!bin) { console.error('esbuild not found (npm install)'); process.exit(1) }
    const built = spawnSync(bin, [__filename, '--bundle', '--platform=node', '--format=esm',
      `--outfile=${bundlePath}`, '--log-level=warning'], { cwd: ROOT, stdio: 'inherit' })
    if (built.status !== 0) process.exit(built.status ?? 1)
    const run = spawnSync('node', [bundlePath], {
      stdio: 'inherit', cwd: ROOT,
      env: { ...process.env, REST_REFERENCE_BUNDLED: '1', REST_REFERENCE_ROOT: ROOT },
    })
    process.exit(run.status ?? 1)
  }

  const root = process.env.REST_REFERENCE_ROOT
  const THREE = await import('three')
  const { FBXLoader } = await import('three/examples/jsm/loaders/FBXLoader.js')
  const { GLTFLoader } = await import('three/examples/jsm/loaders/GLTFLoader.js')
  const { restPoseOf, restCorrections, bindRelativeValues, normBoneName } =
    await import('../../packages/scene-render/src/clipRetarget.ts')

  const read = (rel) => {
    const b = fs.readFileSync(path.join(root, rel))
    return b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength)
  }
  const fbx = (rel) => new FBXLoader().parse(read(rel), '')

  /** The GLB without images/textures/materials (node cannot decode images). */
  const stripGlb = (buf) => {
    const dv = new DataView(buf)
    const jsonLen = dv.getUint32(12, true)
    const json = JSON.parse(new TextDecoder().decode(new Uint8Array(buf, 20, jsonLen)))
    delete json.images; delete json.textures; delete json.samplers; delete json.materials
    for (const m of json.meshes ?? []) for (const p of m.primitives) delete p.material
    let text = JSON.stringify(json)
    while (text.length % 4) text += ' '
    const jsonBytes = new TextEncoder().encode(text)
    const rest = new Uint8Array(buf, 20 + jsonLen)   // the BIN chunk header + data
    const out = new Uint8Array(12 + 8 + jsonBytes.length + rest.length)
    const odv = new DataView(out.buffer)
    odv.setUint32(0, 0x46546c67, true); odv.setUint32(4, 2, true); odv.setUint32(8, out.length, true)
    odv.setUint32(12, jsonBytes.length, true); odv.setUint32(16, 0x4e4f534a, true)
    out.set(jsonBytes, 20); out.set(rest, 20 + jsonBytes.length)
    return out.buffer
  }
  const glb = (rel) => new Promise((resolve, reject) =>
    new GLTFLoader().parse(stripGlb(read(rel)), '', resolve, reject))

  const rig = fbx('shared/models/rig/reference.fbx')
  const donor = restPoseOf(THREE, rig)
  const rootOf = (pose) => { for (const [k, a] of pose.parentBone) if (a === null) return pose.world.get(k) }
  const clips = SAMPLES.map((s) => ({ ...s, anim: fbx(s.file).animations[0] }))
  const out = {
    generated_by: 'native/fixtures/rest_reference.mjs (packages/scene-render/src/clipRetarget.ts on three r' + THREE.REVISION + ')',
    models: [],
  }
  for (const m of MODELS) {
    const target = (await glb(m.file)).scene
    const corrections = restCorrections(THREE, donor, target)
    // Which bones a stance rule changed: compare K_b with the plain root-frame K.
    const self = restPoseOf(THREE, target)
    const dr = rootOf(donor).clone().invert(), tr = rootOf(self).clone().invert()
    const stanced = []
    for (const [key, tw] of self.world) {
      const dw = donor.world.get(key)
      const c = corrections.get(key)
      if (!dw || !c) continue
      const plain = dr.clone().multiply(dw).invert().multiply(tr.clone().multiply(tw))
      // Normalised first: glTF rests are float32 and not exactly unit, which alone
      // reads as a few hundredths of a degree; a stance turn is degrees.
      const dot = plain.clone().normalize().dot(c.right.clone().normalize())
      if (2 * Math.acos(Math.min(1, Math.abs(dot))) * 180 / Math.PI > 0.1) stanced.push(key)
    }
    const entry = { name: m.name, file: m.file, corrected_bones: corrections.size, stance_bones: stanced.sort(), samples: [] }
    for (const s of clips) {
      for (const t of s.times) {
        const bones = {}
        for (const bone of BONES) {
          const key = normBoneName(bone)
          const track = s.anim.tracks.find((tr) => tr.name.endsWith('.quaternion')
            && normBoneName(tr.name.slice(0, tr.name.lastIndexOf('.'))) === key)
          if (!track) continue
          const c = Array.from(track.createInterpolant().evaluate(t))
          const q = bindRelativeValues(THREE, c, corrections.get(key))
          bones[bone] = { clip: c.map((v) => +v.toFixed(7)), corrected: Array.from(q ?? c).map((v) => +v.toFixed(7)) }
        }
        entry.samples.push({ clip: s.clip, time: t, bones })
      }
    }
    out.models.push(entry)
    console.log(`${m.name}: ${entry.corrected_bones} corrected bones, stance on ${stanced.length} (${stanced.join(', ') || 'none'})`)
  }
  const file = path.join(root, 'native/fixtures/rest_reference.json')
  fs.writeFileSync(file, JSON.stringify(out, null, 1) + '\n')
  console.log(`wrote ${path.relative(root, file)}`)
}

main().catch((e) => { console.error(e); process.exit(1) })
