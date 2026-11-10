#!/usr/bin/env node
/**
 * Extension-bone tips kept outside the body's collision capsules
 * (`createSecondaryMotion(...).setCollision`, packages/scene-render/src/secondaryMotion.ts;
 * contract docs/schnittstellen-3d.md "Collision capsules"). Hand-derived.
 *
 * Usage: node scripts/smoke_extension_collision.mjs   (no server, no world; bundles itself with esbuild)
 *
 * FIXTURE (metres, every bind rotation identity, one body skin with all bones):
 *   Hips (0,0,0) → Spine2 (0,1,0) → Neck (0,1.5,0); Spine2 → Ext at local (0,0,0.1) = world (0,1,0.1).
 *   Hips → LeftArm at (1,1.05,0.5) → LeftForeArm at local (1,0,0) = world (2,1.05,0.5).
 *   Hips → Probe at (0,1,0) (a non-ancestor joint at Spine2's place).
 *   Two vertices weighted 1 to Ext, at its joint (0,1,0.1) and at (0,1,0.5): centroid lever (0,0,0.2);
 *   tip = the own vertex (weight > 0.5) reaching farthest along that lever = (0,0,0.4) in Ext's frame
 *   = world (0,1,0.5) in the bind pose; lever length 0.4.
 *
 * [1] pure: `extensionCapsules` drops a capsule whose start joint is an ancestor (prefix-insensitive);
 *     `tipBindFactors` — tip (0,1,0.5) vs capsule (0,1,0)→(0,1.5,0) r 0.6: d0 = 0.5 → factor 0.5/0.6;
 *     vs the arm capsule r 0.1 (d0 = |(0,1,0.5)−(1,1.05,0.5)| = 1.00125) → 1.
 * [2] ARM CONTACT (gravity 0, gain 0 — the link is static): LeftArm turned 180° about +Y puts the
 *     forearm axis on (1,1.05,0.5)→(0,1.05,0.5), r 0.1; the tip (0,1,0.5) lies 0.05 below its end
 *     → inside. The push points −Y, the link turns about +X through its joint (0,1,0.1) by φ:
 *     tip = (0, 1 − 0.4 sinφ, 0.1 + 0.4 cosφ); the closest axis point stays the end (0,1.05,0.5), so
 *     the smallest φ with the tip on the surface solves (0.05 + 0.4 sinφ)² + (0.4 − 0.4 cosφ)² = 0.1²:
 *     with (1−cosφ)² ≈ 6.1e-5 → 0.16 s² + 0.04 s − 0.0074902 = 0 → s = 0.124877, φ = 7.174°,
 *     tip = (0, 0.950049, 0.496868); lever length stays 0.4. Without the payload: tip (0,1,0.5).
 * [3] BIND RULE: the same arm capsule moved over the bind-pose tip by its OWN bind (LeftArm at
 *     (−0.5,1.0,0.5) in the bind pose, so the tip lies 0.05 from the axis at bind: factor 0.5) — in the
 *     bind pose nothing moves (tip (0,1,0.5)).
 * [4] ANCESTOR CAPSULE (Review Focus 2): gravity_scale 2, gravity 1, freq 2 Hz, gain 0 → static sag
 *     a = g/ω² = 9.81/(4π)² = 0.062126 m on the centroid lever 0.2 → the link turns down by
 *     atan(0.062126/0.2) = 17.256°: tip = (0, 1 − 0.4 sin17.256°, 0.1 + 0.4 cos17.256°)
 *     = (0, 0.881347, 0.481997). Its distance to (0,1,0) shrinks from 0.5 to 0.49639.
 *     Capsule Spine2→Neck r 0.6 (bind factor 0.5/0.6 → effective 0.5): Spine2 is the chain's parent →
 *     EXCLUDED, the sag stays exactly as without a payload. Control: the same capsule from Probe
 *     (not an ancestor) → the sag is turned back until the tip is 0.5 from (0,1,0) again (at most
 *     sag_max_deg, 45°). Distance² = 0.17 + 0.08 cosθ (θ = the remaining sag) is largest at θ = 0, so
 *     the only outside window is around the bind tip: depth ≈ 0.04 θ² < the 1e-6 m slack for
 *     |θ| < 0.005 rad → tip within 0.4 × 0.005 = 2 mm of (0,1,0.5) and ≥ 0.5 − 1e-6 from (0,1,0).
 * [4b] OWN CHAIN (the chain's own bone and its child bones are never pushers): extra bones Low under Hips
 *     at (0,0.8,0.5), Twin under Spine2 at local (0,0,0.1) = Ext's joint, Kid under Ext at local (0,0,0)
 *     (all after Ext in the skin, so the fixture's indices hold). Capsule X → Low, r 0.3, X at (0,1,0.1):
 *     axis (0,−0.2,0.4); bind tip (0,1,0.5): t = 0.16/0.2 = 0.8 → closest (0,0.84,0.42), d0 = 0.178885 →
 *     effective radius 0.178885 (bind rule). Sagged tip (0,0.881347,0.481997): t = 0.882810 → closest
 *     (0,0.823438,0.453124), d = 0.064737 < 0.178885 → inside. X = Ext (the chain bone) and X = Kid (its child;
 *     it sits on Ext's joint, so the capsule is the same) → EXCLUDED, the sag stays exactly as without a
 *     payload. Control X = Twin (same place, not in the chain) → the tip is turned back to the effective
 *     surface: distance to the axis ≥ 0.178885 − 1e-6, and it moved off the free sag.
 *     The control's capsule with region `chest_hair` (HAIR_ONLY_REGIONS) → excluded, the sag as without it.
 * [5] INERT: no extension bone → `setCollision` binds nothing (no capsule joint lookups: the root is
 *     never traversed after creation); a null payload → bit-identical to never calling it; far LOD →
 *     no contact (tip as without payload).
 */
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { existsSync } from 'node:fs'
import assert from 'node:assert/strict'

if (!process.env.EXT_COLLISION_BUNDLED) {
  const bin = ['client3d/node_modules/esbuild/bin/esbuild', 'node_modules/esbuild/bin/esbuild'].find(existsSync)
  assert.ok(bin, 'esbuild unavailable (npm install) — nothing was checked')
  const output = '/tmp/smoke_extension_collision.mjs'
  const built = spawnSync(bin, [fileURLToPath(import.meta.url), '--bundle', '--platform=node', '--format=esm',
    `--outfile=${output}`, '--log-level=error'], { stdio: 'inherit' })
  assert.equal(built.status, 0)
  const run = spawnSync('node', [output], { stdio: 'inherit', env: { ...process.env, EXT_COLLISION_BUNDLED: '1' } })
  process.exit(run.status ?? 1)
}
const THREE = await import('three')
const { createSecondaryMotion, extensionCapsules, tipBindFactors } = await import('../packages/scene-render/src/secondaryMotion.ts')

const defaults = { freq_hz: 2, zeta: 1, gravity: 0, gravity_scale: 1, gain: 0,
  max_deg: 30, sag_max_deg: 45, spill_max_deg: 0, head_sag: 1, axis_gain: [1, 1, 1],
  flatten: 0, stretch: 0, spread: 0, flatten_floor: 1, spill: 0, translate: 0,
  squash: [1, 1], length: 1, girth: 1, rest_deg: 0, rest_max_deg: 90,
  straighten_deg: 0, freetext_clothing_gain: 1 }
let failures = 0
const check = (label, ok, detail = '') => {
  console.log(`${ok ? 'OK  ' : 'FAIL'} ${label}${detail ? ` — ${detail}` : ''}`)
  if (!ok) failures++
}
const fmt = (v) => `(${v.toArray().map((x) => x.toFixed(6)).join(', ')})`

function rig({ armAt = [1, 1.05, 0.5], extension = true, extras = false } = {}) {
  const root = new THREE.Group()
  const bone = (name, parent, at) => {
    const b = new THREE.Bone(); b.name = name; b.position.set(...at); (parent ?? root).add(b); return b
  }
  const hips = bone('mixamorig:Hips', null, [0, 0, 0])
  const spine2 = bone('mixamorig:Spine2', hips, [0, 1, 0])
  const neck = bone('mixamorig:Neck', spine2, [0, 0.5, 0])
  const arm = bone('mixamorig:LeftArm', hips, armAt)
  const fore = bone('mixamorig:LeftForeArm', arm, [1, 0, 0])
  const probe = bone('mixamorig:Probe', hips, [0, 1, 0])
  const bones = [hips, spine2, neck, arm, fore, probe]
  let ext = null
  if (extension) { ext = bone('mixamorig:Ext', spine2, [0, 0, 0.1]); bones.push(ext) }
  if (extension && extras) {
    bones.push(bone('mixamorig:Low', hips, [0, 0.8, 0.5]), bone('mixamorig:Twin', spine2, [0, 0, 0.1]),
      bone('mixamorig:Kid', ext, [0, 0, 0]))
  }
  const geo = new THREE.BufferGeometry()
  geo.setAttribute('position', new THREE.Float32BufferAttribute([0, 1, 0.1, 0, 1, 0.5], 3))
  const own = extension ? 6 : 1
  geo.setAttribute('skinIndex', new THREE.Uint16BufferAttribute([own, 0, 0, 0, own, 0, 0, 0], 4))
  geo.setAttribute('skinWeight', new THREE.Float32BufferAttribute([1, 0, 0, 0, 1, 0, 0, 0], 4))
  const mesh = new THREE.SkinnedMesh(geo, new THREE.MeshBasicMaterial())
  root.add(mesh); root.updateMatrixWorld(true)
  mesh.bind(new THREE.Skeleton(bones))
  return { root, hips, spine2, neck, arm, fore, probe, ext }
}
const tipOf = (ext) => { ext.updateWorldMatrix(true, false); return new THREE.Vector3(0, 0, 0.4).applyMatrix4(ext.matrixWorld) }
const headOf = (ext) => new THREE.Vector3().setFromMatrixPosition(ext.matrixWorld)
const group = (over = {}) => ({ rev: 'fixture', groups: { g: { ...defaults, bones: ['Ext'], ...over } } })
const armCapsule = { id: 'left_upper_arm', a: 'mixamorig:LeftArm', b: 'mixamorig:LeftForeArm', r: 0.1, region: 'arm' }
const payload = (...capsules) => ({ version: 3, capsules })

console.log('--- [1] pure helpers ---')
{
  const bound = [{ capsule: { a: 'mixamorig:Spine2' } }, { capsule: { a: 'LeftArm' } }, { capsule: { a: 'Hips' } }]
  const kept = extensionCapsules(bound, new Set(['spine2', 'hips']))
  check('ancestor start joints dropped, order kept', kept.length === 1 && kept[0].capsule.a === 'LeftArm')
  const f = tipBindFactors([0, 1, 0.5], [{ a: [0, 1, 0], b: [0, 1.5, 0], r: 0.6 }, { a: [1, 1.05, 0.5], b: [2, 1.05, 0.5], r: 0.1 }])
  check('bind factor inside = d0/r', Math.abs(f[0] - 0.5 / 0.6) < 1e-12, String(f[0]))
  check('bind factor outside = 1', f[1] === 1)
  check('degenerate capsule (a == b): sphere distance', Math.abs(tipBindFactors([0, 0, 0.05], [{ a: [0, 0, 0], b: [0, 0, 0], r: 0.1 }])[0] - 0.5) < 1e-12)
}

console.log('--- [2] arm contact ---')
{
  const f = rig()
  const motion = createSecondaryMotion(THREE, f.root, group())
  motion.setCollision(payload(armCapsule))
  motion.update(1 / 60)
  check('bind pose: tip unchanged', tipOf(f.ext).distanceTo(new THREE.Vector3(0, 1, 0.5)) < 1e-6, fmt(tipOf(f.ext)))
  f.arm.quaternion.setFromAxisAngle(new THREE.Vector3(0, 1, 0), Math.PI)
  motion.update(1 / 60)
  const tip = tipOf(f.ext)
  check('tip turned out to the surface', tip.distanceTo(new THREE.Vector3(0, 0.950049, 0.496868)) < 1e-4, fmt(tip))
  check('lever length kept (0.4)', Math.abs(tip.distanceTo(headOf(f.ext)) - 0.4) < 1e-6)
  check('distance to the forearm end = r', Math.abs(tip.distanceTo(new THREE.Vector3(0, 1.05, 0.5)) - 0.1) < 1e-4,
    tip.distanceTo(new THREE.Vector3(0, 1.05, 0.5)).toFixed(6))
  motion.setCollision(null)
  motion.update(1 / 60)
  check('payload off: tip back at (0,1,0.5)', tipOf(f.ext).distanceTo(new THREE.Vector3(0, 1, 0.5)) < 1e-6, fmt(tipOf(f.ext)))
  motion.setCollision(payload(armCapsule))
  motion.update(1 / 60, { far: true })
  check('far LOD: no contact', tipOf(f.ext).distanceTo(new THREE.Vector3(0, 1, 0.5)) < 1e-6, fmt(tipOf(f.ext)))
  motion.dispose()
}

console.log('--- [3] bind rule ---')
{
  const f = rig({ armAt: [-0.5, 1.05, 0.5] })   // forearm axis (−0.5..0.5, 1.05, 0.5): the tip 0.05 below it at bind
  const motion = createSecondaryMotion(THREE, f.root, group())
  motion.setCollision(payload(armCapsule))
  motion.update(1 / 60)
  check('capsule over the bind tip: nothing moves', tipOf(f.ext).distanceTo(new THREE.Vector3(0, 1, 0.5)) < 1e-6, fmt(tipOf(f.ext)))
  motion.dispose()
}

console.log('--- [4] ancestor capsule ---')
{
  const sag = { gravity: 1, gravity_scale: 2 }
  const s = Math.sin(Math.atan(9.81 / (4 * Math.PI) ** 2 / 0.2)), c = Math.cos(Math.atan(9.81 / (4 * Math.PI) ** 2 / 0.2))
  const sagged = new THREE.Vector3(0, 1 - 0.4 * s, 0.1 + 0.4 * c)
  const run = (capsule) => {
    const f = rig()
    const motion = createSecondaryMotion(THREE, f.root, group(sag))
    if (capsule) motion.setCollision(payload(capsule))
    motion.update(1 / 60)
    const tip = tipOf(f.ext)
    motion.dispose()
    return tip
  }
  const free = run(null)
  check('sag without payload = hand value (0, 0.881347, 0.481997)', free.distanceTo(sagged) < 1e-5, fmt(free))
  const chest = { id: 'chest', a: 'mixamorig:Spine2', b: 'mixamorig:Neck', r: 0.6, region: 'torso' }
  const excluded = run(chest)
  check('ancestor capsule (Spine2→Neck) excluded: sag unchanged', excluded.distanceTo(free) < 1e-9, fmt(excluded))
  const control = run({ ...chest, a: 'mixamorig:Probe' })
  check('control (Probe→Neck, not an ancestor): sag turned back to the bind tip',
    control.distanceTo(new THREE.Vector3(0, 1, 0.5)) < 0.002 && control.distanceTo(new THREE.Vector3(0, 1, 0)) >= 0.5 - 1e-6,
    `${fmt(control)}, ${control.distanceTo(new THREE.Vector3(0, 1, 0)).toFixed(7)} from (0,1,0)`)
}

console.log('--- [4b] own chain ---')
{
  const sag = { gravity: 1, gravity_scale: 2 }
  const run = (a) => {
    const f = rig({ extras: true })
    const motion = createSecondaryMotion(THREE, f.root, group(sag))
    if (a) motion.setCollision(payload({ id: 'x', a, b: 'mixamorig:Low', r: 0.3, region: 'chest' }))
    motion.update(1 / 60)
    const tip = tipOf(f.ext)
    motion.dispose()
    return tip
  }
  const free = run(null)
  const own = run('mixamorig:Ext')
  check('capsule from the chain bone itself: excluded', own.distanceTo(free) < 1e-9, fmt(own))
  const kid = run('mixamorig:Kid')
  check('capsule from a child bone of the chain: excluded', kid.distanceTo(free) < 1e-9, fmt(kid))
  const hairOnly = (() => {
    const f = rig({ extras: true })
    const motion = createSecondaryMotion(THREE, f.root, group(sag))
    motion.setCollision(payload({ id: 'x', a: 'mixamorig:Twin', b: 'mixamorig:Low', r: 0.3, region: 'chest_hair' }))
    motion.update(1 / 60)
    const tip = tipOf(f.ext)
    motion.dispose()
    return tip
  })()
  check('hair-only region (chest_hair) never turns a tip', hairOnly.distanceTo(free) < 1e-9, fmt(hairOnly))
  const control = run('mixamorig:Twin')
  const a = new THREE.Vector3(0, 1, 0.1), ab = new THREE.Vector3(0, -0.2, 0.4)
  const t = Math.min(1, Math.max(0, control.clone().sub(a).dot(ab) / ab.lengthSq()))
  const d = control.distanceTo(a.clone().addScaledVector(ab, t))
  check('control (Twin, not in the chain): turned out to the effective surface',
    d >= Math.sqrt(0.032) - 1e-6 && control.distanceTo(free) > 1e-3, `${fmt(control)}, d ${d.toFixed(6)}`)
}

console.log('--- [5] inert ---')
{
  const f = rig({ extension: false })
  let traversals = 0
  const motion = createSecondaryMotion(THREE, f.root, group())
  const original = f.root.traverse.bind(f.root)
  f.root.traverse = (cb) => { traversals++; return original(cb) }
  motion.setCollision(payload(armCapsule))
  motion.update(1 / 60)
  check('no extension bone: setCollision binds nothing', traversals === 0, `${traversals} traversals`)
  motion.dispose()

  const a = rig(), b = rig()
  const ma = createSecondaryMotion(THREE, a.root, group({ gain: 1, gravity: 1, gravity_scale: 2 }))
  const mb = createSecondaryMotion(THREE, b.root, group({ gain: 1, gravity: 1, gravity_scale: 2 }))
  mb.setCollision(null)
  for (const x of [a, b]) x.spine2.quaternion.setFromAxisAngle(new THREE.Vector3(0, 0, 1), 0.3)
  for (let i = 0; i < 30; i++) { ma.update(1 / 60); mb.update(1 / 60) }
  check('null payload: bit-identical to never set', a.ext.matrixWorld.equals(b.ext.matrixWorld))
  ma.dispose(); mb.dispose()
}

if (failures) {
  console.error(`FAIL smoke_extension_collision: ${failures} check(s) failed`)
  process.exit(1)
}
console.log('PASS smoke_extension_collision: arm contact turns the tip to the surface, bind rule, ancestor and own-chain capsules excluded, inert')
