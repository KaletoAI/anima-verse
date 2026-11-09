/**
 * Garment collision — garment vertices pushed out of the body's collision
 * capsules after skinning, on the GPU (spec
 * `docs/superpowers/specs/2026-11-08-collision-capsules-design.md`, contract
 * `docs/schnittstellen-3d.md` "Collision capsules (`collision`)").
 *
 * WHAT IS PUSHED. Every SKINNED mesh inside a garment subtree (`inGarment`,
 * § A3a) — a dress or hair grafted onto the body — has its vertex shader patched:
 * after `skinning_vertex` the skinned position `transformed` (mesh-local
 * space) is pushed radially out of each capsule it lies inside, closest
 * point on the capsule axis outwards to the radius, in payload order, in
 * `COLLIDE_PASSES` passes. The body itself is never pushed. The optional
 * glTF vertex attribute `_COLLIDE` (three: `_collide`, 0..1) scales the
 * whole push of a vertex (`mix(p, pushed(p), w)`); absent = 1.
 *
 * WHICH CAPSULES. `garmentCapsules` decides per garment kind: hair the
 * torso, arm and head capsules (`HAIR_REGIONS`), every other kind all but
 * the arm capsules (an arm passes through cloth; pushing the cloth out of
 * the arm drives it into the body — the numbers are on the function). At
 * most `COLLIDE_MAX` per mesh, the FIRST ones in payload order —
 * deterministic, and the server table has 12 (`app/core/collision.py`).
 *
 * BIND RULE (hair, `garmentBindRule`). A vertex is never pushed further from
 * a capsule than it lay in the BIND pose: the radius is capped per vertex
 * and capsule at the vertex's bind distance (computed in the shader from the
 * unskinned `position` and the bind-pose capsule, `BoundCapsule.bind`).
 * Card hair is rooted INTO the scalp and lies on the shoulders inside the
 * upper-arm caps; the plain push would lift it there in every frame. The
 * bind rule keeps the fit as it is (no push at all in the bind pose) and
 * pushes only what a pose drives deeper — it also covers the scalp under the
 * head capsule, so no Head-weight exclusion or height cut is needed.
 *
 * WHERE THE CAPSULES COME FROM. `bindCollision` (`collision.ts`, the ONE
 * endpoint rule) gives them in world space; per garment mesh they are taken
 * into that mesh's local space (`capsuleInFrame`, inverse `matrixWorld`) —
 * the space `transformed` is in after skinning, attached and detached bind
 * mode alike. The update runs in the garment mesh's `onBeforeShadow` /
 * `onBeforeRender`, i.e. inside `renderer.render` after
 * `scene.updateMatrixWorld` and the skeleton update — the bones it reads are
 * exactly the ones the shader skins with (no frame of lag), once per frame.
 *
 * ONE SOURCE. The push exists twice — `pushOutOfCapsules` (TypeScript; the
 * motion check `scripts/check_garment_collision.mjs` runs it) and
 * `COLLIDE_GLSL_FUNCTION` (the shader). The GLSL is written in scalar
 * statements so `scripts/smoke_garment_collision.mjs` can execute THAT
 * string (a mechanical GLSL→JS rewrite) and assert both give the same
 * points; the constants of both come from the exports here.
 *
 * SHADOWS. Each patched mesh gets its own `customDepthMaterial` /
 * `customDistanceMaterial` with the same patch and the SAME uniform objects,
 * so the shadow is cast by the pushed garment (three copies map, alphaTest,
 * side … onto a custom depth material itself).
 *
 * OWNERSHIP. Figures in the 3D client are `SkeletonUtils.clone`s that SHARE
 * their template's materials, but capsule uniforms are per figure — so every
 * patched material is a CLONE owned by this handle, and `dispose()` puts the
 * original materials and hooks back and frees exactly those clones (never a
 * shared template material, never a texture).
 *
 * INERT. No collision payload, no capsule bound, or no skinned garment mesh
 * → `createGarmentCollision` returns null: nothing patched, no hook, no
 * per-frame work.
 *
 * `three` is injected, never imported.
 */
import type { Material, Object3D, SkinnedMesh, Vector4, WebGLProgramParametersWithUniforms } from 'three'
import { bindCollision, linearScale, transformPoint } from './collision'
import type { BoundCapsule, CapsuleNow, CollisionBinding, CollisionPayload, Mat4, Vec3 } from './collision'
import { isGarmentNode } from './figure'

type Three = typeof import('three')

/** Capsules one garment mesh's shader holds (uniform array length). */
export const COLLIDE_MAX = 16
/** Passes over all capsules (a vertex pushed out of one capsule into a neighbour is pushed again). */
export const COLLIDE_PASSES = 2
/** Squared axis length below which a capsule counts as a sphere around `a`. */
export const COLLIDE_EPS = 1e-12
/** A vertex this close to the axis has no outward direction and stays where it is. */
export const COLLIDE_MIN_D = 1e-6

/** The GLSL float literal of a number (always with a decimal point or exponent). */
function glslFloat(v: number): string {
  const s = String(v)
  return /[.e]/.test(s) ? s : `${s}.0`
}

/** `#define`s + uniforms (+ the optional weight attribute) — after `#include <common>`. */
export const COLLIDE_GLSL_DECLARATIONS = [
  `#define COLLIDE_MAX ${COLLIDE_MAX}`,
  `#define COLLIDE_PASSES ${COLLIDE_PASSES}`,
  `#define COLLIDE_EPS ${glslFloat(COLLIDE_EPS)}`,
  `#define COLLIDE_MIN_D ${glslFloat(COLLIDE_MIN_D)}`,
  'uniform vec4 collideA[ COLLIDE_MAX ];',
  'uniform vec4 collideB[ COLLIDE_MAX ];',
  'uniform vec4 collideBindA[ COLLIDE_MAX ];',
  'uniform vec4 collideBindB[ COLLIDE_MAX ];',
  'uniform int collideCount;',
  '#ifdef COLLIDE_WEIGHT',
  'attribute float _collide;',
  '#endif',
].join('\n')

/**
 * THE PUSH, shader edition. Capsule i: axis `collideA[i].xyz` →
 * `collideB[i].xyz`, radius `collideA[i].w`, all in mesh-local space.
 * BIND RULE (`collideBindA[i].w` ≥ 0): the same capsule in the BIND pose,
 * `collideBindA[i].xyz` → `collideBindB[i].xyz` in the mesh's geometry
 * space; the vertex's bind distance `d0` to it (from the unskinned
 * `position`) caps the radius — `rr = min(r, d0)`: the vertex is pushed back
 * to where it lay from that capsule in the bind pose, never further. What
 * the fit put inside a capsule (hair on the scalp, on the shoulders) stays
 * where it is; only what the pose drives deeper is pushed (module docstring).
 * Scalar statements on purpose (see "ONE SOURCE" above) — keep it that way.
 */
export const COLLIDE_GLSL_FUNCTION = `
vec3 collidePush( vec3 p ) {
  for ( int it = 0; it < COLLIDE_PASSES; it ++ ) {
    for ( int i = 0; i < COLLIDE_MAX; i ++ ) {
      if ( i >= collideCount ) break;
      float ax = collideA[ i ].x;
      float ay = collideA[ i ].y;
      float az = collideA[ i ].z;
      float r = collideA[ i ].w;
      if ( collideBindA[ i ].w >= 0.0 ) {
        float bx = collideBindA[ i ].x;
        float by = collideBindA[ i ].y;
        float bz = collideBindA[ i ].z;
        float bbx = collideBindB[ i ].x - bx;
        float bby = collideBindB[ i ].y - by;
        float bbz = collideBindB[ i ].z - bz;
        float bpx = position.x - bx;
        float bpy = position.y - by;
        float bpz = position.z - bz;
        float bl2 = bbx * bbx + bby * bby + bbz * bbz;
        float bt = bl2 > COLLIDE_EPS ? clamp( ( bpx * bbx + bpy * bby + bpz * bbz ) / bl2, 0.0, 1.0 ) : 0.0;
        float ex = bpx - bbx * bt;
        float ey = bpy - bby * bt;
        float ez = bpz - bbz * bt;
        r = min( r, sqrt( ex * ex + ey * ey + ez * ez ) );
      }
      float abx = collideB[ i ].x - ax;
      float aby = collideB[ i ].y - ay;
      float abz = collideB[ i ].z - az;
      float apx = p.x - ax;
      float apy = p.y - ay;
      float apz = p.z - az;
      float len2 = abx * abx + aby * aby + abz * abz;
      float t = len2 > COLLIDE_EPS ? clamp( ( apx * abx + apy * aby + apz * abz ) / len2, 0.0, 1.0 ) : 0.0;
      float dx = apx - abx * t;
      float dy = apy - aby * t;
      float dz = apz - abz * t;
      float d = sqrt( dx * dx + dy * dy + dz * dz );
      if ( d < r && d > COLLIDE_MIN_D ) {
        float k = r / d - 1.0;
        p.x += dx * k;
        p.y += dy * k;
        p.z += dz * k;
      }
    }
  }
  return p;
}
`

/** The call — after `#include <skinning_vertex>` (and before displacement / projection). */
export const COLLIDE_GLSL_APPLY = `
#ifdef COLLIDE_WEIGHT
  transformed = mix( transformed, collidePush( transformed ), clamp( _collide, 0.0, 1.0 ) );
#else
  transformed = collidePush( transformed );
#endif
`

/**
 * A capsule as the shader holds it: mesh-local now (`a`, `b`, `r`), plus —
 * under the BIND RULE — the same capsule in the bind pose in the mesh's
 * geometry space (`bind`; absent = no bind rule, `collideBindA[i].w` = −1).
 */
export interface CollideCapsule extends CapsuleNow { bind?: { a: Vec3; b: Vec3 } }

/** Distance from `p` to the segment a→b (a == b: to the point). */
function segmentDistance(p: Vec3, a: Vec3, b: Vec3): number {
  const abx = b[0] - a[0], aby = b[1] - a[1], abz = b[2] - a[2]
  const apx = p[0] - a[0], apy = p[1] - a[1], apz = p[2] - a[2]
  const len2 = abx * abx + aby * aby + abz * abz
  const t = len2 > COLLIDE_EPS ? Math.min(1, Math.max(0, (apx * abx + apy * aby + apz * abz) / len2)) : 0
  return Math.hypot(apx - abx * t, apy - aby * t, apz - abz * t)
}

/**
 * THE PUSH, TypeScript edition — the same steps as `COLLIDE_GLSL_FUNCTION`
 * (the smoke runs both): `p` pushed out of the first `COLLIDE_MAX` capsules,
 * `COLLIDE_PASSES` passes, then `weight` (0..1, the `_COLLIDE` value) blends
 * between the original and the pushed point. Capsules and point in one space;
 * `bindP` = the vertex's unskinned position (geometry space) for the BIND
 * RULE of a capsule carrying `bind` (radius capped at the bind distance;
 * without `bindP` the rule is not applied).
 */
export function pushOutOfCapsules(p: Vec3, capsules: readonly CollideCapsule[], weight = 1, bindP?: Vec3): Vec3 {
  let x = p[0], y = p[1], z = p[2]
  const n = Math.min(capsules.length, COLLIDE_MAX)
  const radii = capsules.slice(0, n).map(c => (c.bind && bindP ? Math.min(c.r, segmentDistance(bindP, c.bind.a, c.bind.b)) : c.r))
  for (let it = 0; it < COLLIDE_PASSES; it++) {
    for (let i = 0; i < n; i++) {
      const { a, b } = capsules[i]
      const r = radii[i]
      const abx = b[0] - a[0], aby = b[1] - a[1], abz = b[2] - a[2]
      const apx = x - a[0], apy = y - a[1], apz = z - a[2]
      const len2 = abx * abx + aby * aby + abz * abz
      const t = len2 > COLLIDE_EPS ? Math.min(1, Math.max(0, (apx * abx + apy * aby + apz * abz) / len2)) : 0
      const dx = apx - abx * t, dy = apy - aby * t, dz = apz - abz * t
      const d = Math.sqrt(dx * dx + dy * dy + dz * dz)
      if (d < r && d > COLLIDE_MIN_D) {
        const k = r / d - 1
        x += dx * k; y += dy * k; z += dz * k
      }
    }
  }
  const w = Math.min(1, Math.max(0, weight))
  return [p[0] + (x - p[0]) * w, p[1] + (y - p[1]) * w, p[2] + (z - p[2]) * w]
}

/** A capsule taken through `m` (e.g. world → mesh-local): endpoints transformed, radius × `m`'s scale. */
export function capsuleInFrame(capsule: CapsuleNow, m: Mat4): CapsuleNow {
  return { a: transformPoint(m, capsule.a), b: transformPoint(m, capsule.b), r: capsule.r * linearScale(m) }
}

/** Patch a vertex shader source (idempotent): declarations after `common`, the push after `skinning_vertex`. */
export function patchCollisionVertexShader(source: string): string {
  if (source.includes('collidePush(')) return source
  if (!source.includes('#include <common>') || !source.includes('#include <skinning_vertex>')) return source
  return source
    .replace('#include <common>', `#include <common>\n${COLLIDE_GLSL_DECLARATIONS}\n${COLLIDE_GLSL_FUNCTION}`)
    .replace('#include <skinning_vertex>', `#include <skinning_vertex>\n${COLLIDE_GLSL_APPLY}`)
}

/** The garment kind of a node inside a garment subtree (`extras.garment.kind`, else the `garment_<kind>_…` name). */
export function garmentKind(o: Object3D): string | null {
  let n: Object3D | null = o
  while (n && !isGarmentNode(n)) n = n.parent
  if (!n) return null
  const g = (n.userData as { garment?: { kind?: unknown } }).garment
  if (g && typeof g.kind === 'string' && g.kind) return g.kind
  const m = /^garment_([^_]+)_/.exec(n.name)
  return m ? m[1] : ''
}

/**
 * Capsule regions that push HAIR (`garmentCapsules`). The legs are not
 * among them (hair does not reach them standing or sitting). Measured with
 * `scripts/check_garment_collision.mjs` (8 samples, max; share > 5 mm inside
 * beyond the vertex's bind depth) on Kira's HairDeck hair and the S1 spike
 * hair: the arm capsules are what moves hair at all — celebrating Kira
 * 7.91 → 7.91 % without them, → 7.59 % with; spike 28.6 → 28.0 % / → 23.4 %,
 * spike walk 0.77 → 0.77 / → 0.13 %. Under the bind rule they lift nothing
 * in the bind pose (without it: 5.6 % of Kira's hair lifted up to 27 mm off
 * the shoulders by the upper-arm caps).
 */
export const HAIR_REGIONS: readonly string[] = ['torso', 'arm', 'head']

/**
 * Which bound capsules push a garment of `kind`, in payload order, at most
 * `COLLIDE_MAX`.
 *  - hair: the `HAIR_REGIONS`, under the bind rule (`garmentBindRule`);
 *  - every other kind: all regions EXCEPT the arms. Cloth lies ON the body,
 *    and an arm that swings or rests against it is the arm passing through
 *    the cloth, not the cloth through the arm: pushed out of the arm capsule
 *    the cloth goes INTO the body. Measured on the S1 dress
 *    (`scripts/check_garment_collision.mjs`): walk 0.87 → 0.99 % with the arm
 *    capsules (armpit cloth driven into the chest), sit hip sides 1.4 → 4.7 %
 *    (the forearms on the lap press the skirt into the thighs).
 */
export function garmentCapsules<T extends { capsule: { region: string } }>(kind: string | null, bound: readonly T[]): T[] {
  if (kind === 'hair') return bound.filter(entry => HAIR_REGIONS.includes(entry.capsule.region)).slice(0, COLLIDE_MAX)
  return bound.filter(entry => entry.capsule.region !== 'arm').slice(0, COLLIDE_MAX)
}

/**
 * Whether the BIND RULE applies to a garment of `kind` (module docstring,
 * `COLLIDE_GLSL_FUNCTION`): HAIR. Measured on Kira's HairDeck hair: without
 * it 6.65 % of the hair moves > 1 mm in the BIND pose (p99 17 mm, max 27 mm:
 * the upper-arm caps over the shoulders, the head capsule over the scalp
 * roots); with it 0 %, and the motion numbers stay the same (celebrating
 * 7.57 vs 7.59 %). A Head-weight exclusion of the head capsule alone
 * (measured first) left the upper-arm lift in place. Cloth keeps the plain
 * push measured for it (Task 3).
 */
export function garmentBindRule(kind: string | null): boolean {
  return kind === 'hair'
}

/** The skinned garment meshes under `root` that collide at all (`garmentCapsules` gives their kind capsules). */
export function collidingGarmentMeshes(root: Object3D): SkinnedMesh[] {
  const out: SkinnedMesh[] = []
  const probe = [{ capsule: { region: 'torso' } }]
  root.traverse(o => {
    const mesh = o as SkinnedMesh
    if (!mesh.isSkinnedMesh) return
    const kind = garmentKind(mesh)
    if (kind !== null && garmentCapsules(kind, probe).length) out.push(mesh)
  })
  return out
}

interface CollideUniforms {
  collideA: { value: Vector4[] }
  collideB: { value: Vector4[] }
  collideBindA: { value: Vector4[] }
  collideBindB: { value: Vector4[] }
  collideCount: { value: number }
}

/** One patched garment mesh. */
export interface GarmentCollisionEntry {
  readonly mesh: SkinnedMesh
  readonly kind: string | null
  /** The bound capsules this mesh is pushed out of (payload order). */
  readonly capsules: readonly BoundCapsule[]
  /** The capsules in this mesh's local space as of the last update — what the shader holds (`bind` under the bind rule). */
  readonly local: readonly CollideCapsule[]
}

export interface GarmentCollision {
  readonly binding: CollisionBinding
  readonly entries: readonly GarmentCollisionEntry[]
  /** Recompute from the CURRENT matrices now (the render hooks do this by themselves once per frame). */
  update(): void
  /** Restore the original materials and hooks, free the owned clones. */
  dispose(): void
}

/**
 * Patch the skinned garment meshes under `root` so they are pushed out of
 * the `payload`'s capsules (module docstring). Null = inert.
 */
export function createGarmentCollision(three: Three, root: Object3D,
  payload: CollisionPayload | null | undefined): GarmentCollision | null {
  const garments = collidingGarmentMeshes(root)
  if (!garments.length) return null
  const binding = bindCollision(three, root, payload)
  if (!binding) return null

  interface State {
    entry: { mesh: SkinnedMesh; kind: string | null; capsules: BoundCapsule[]; local: CollideCapsule[] }
    binds: Array<{ a: Vec3; b: Vec3 }> | null
    uniforms: CollideUniforms
    original: Material | Material[]
    owned: Material[]
    depth: Material | undefined
    distance: Material | undefined
    ownHooks: { render: boolean; shadow: boolean }
    beforeRender: SkinnedMesh['onBeforeRender']
    beforeShadow: SkinnedMesh['onBeforeShadow']
    frame: number
  }
  const DEFAULT_CACHE_KEY = three.Material.prototype.customProgramCacheKey
  // `source` = the material `mat` was cloned from: `Material.clone()` copies neither `onBeforeCompile` nor
  // `customProgramCacheKey`, so a compile hook the template's material carries is chained from there.
  const patch = (mat: Material, uniforms: CollideUniforms, weighted: boolean, source: Material = mat) => {
    const prevCompile = source.onBeforeCompile
    const prevKey = source.customProgramCacheKey
    // three's default cache key IS `onBeforeCompile.toString()` — snapshot it
    // before this patch replaces the function (the pattern of client3d's
    // spotHighlight), so different compile hooks never collapse onto one program.
    const baseKey = prevKey === DEFAULT_CACHE_KEY ? prevCompile.toString() : null
    mat.onBeforeCompile = (shader: WebGLProgramParametersWithUniforms, renderer) => {
      prevCompile.call(source, shader, renderer)
      shader.uniforms.collideA = uniforms.collideA
      shader.uniforms.collideB = uniforms.collideB
      shader.uniforms.collideBindA = uniforms.collideBindA
      shader.uniforms.collideBindB = uniforms.collideBindB
      shader.uniforms.collideCount = uniforms.collideCount
      shader.vertexShader = patchCollisionVertexShader(shader.vertexShader)
    }
    mat.customProgramCacheKey = () => `${baseKey ?? prevKey.call(source)}|collide${weighted ? 'W' : ''}`
    if (weighted) mat.defines = { ...(mat.defines ?? {}), COLLIDE_WEIGHT: '' }
    mat.needsUpdate = true
    return mat
  }

  const states: State[] = []
  let lastBindingFrame = -1
  const writeUniforms = (state: State) => {
    const { mesh, capsules } = state.entry
    const inv = new three.Matrix4().copy(mesh.matrixWorld).invert().elements
    state.entry.local = capsules.map((c, i) => {
      const l: CollideCapsule = capsuleInFrame(c.now, inv)
      if (state.binds) l.bind = state.binds[i]
      return l
    })
    state.entry.local.forEach((c, i) => {
      state.uniforms.collideA.value[i].set(c.a[0], c.a[1], c.a[2], c.r)
      state.uniforms.collideB.value[i].set(c.b[0], c.b[1], c.b[2], 0)
      if (c.bind) {
        state.uniforms.collideBindA.value[i].set(c.bind.a[0], c.bind.a[1], c.bind.a[2], 0)
        state.uniforms.collideBindB.value[i].set(c.bind.b[0], c.bind.b[1], c.bind.b[2], 0)
      } else state.uniforms.collideBindA.value[i].set(0, 0, 0, -1)
    })
    state.uniforms.collideCount.value = state.entry.local.length
  }
  const frameUpdate = (state: State, frame: number) => {
    if (state.frame === frame) return
    state.frame = frame
    if (lastBindingFrame !== frame) {
      lastBindingFrame = frame
      binding.update()
    }
    writeUniforms(state)
  }

  for (const mesh of garments) {
    const kind = garmentKind(mesh)
    const capsules = garmentCapsules(kind, binding.capsules)
    if (!capsules.length) continue
    // Bind rule: the bind-pose capsules (body bind world) in THIS mesh's geometry space — where `position` is.
    const binds = garmentBindRule(kind)
      ? capsules.map(c => capsuleInFrame(c.bind, mesh.bindMatrixInverse.elements)) : null
    const uniforms: CollideUniforms = {
      collideA: { value: Array.from({ length: COLLIDE_MAX }, () => new three.Vector4()) },
      collideB: { value: Array.from({ length: COLLIDE_MAX }, () => new three.Vector4()) },
      collideBindA: { value: Array.from({ length: COLLIDE_MAX }, () => new three.Vector4(0, 0, 0, -1)) },
      collideBindB: { value: Array.from({ length: COLLIDE_MAX }, () => new three.Vector4()) },
      collideCount: { value: 0 },
    }
    const weighted = !!mesh.geometry?.getAttribute('_collide')
    const original = mesh.material
    const owned: Material[] = []
    const cloneOf = (m: Material) => { const c = patch(m.clone(), uniforms, weighted, m); owned.push(c); return c }
    mesh.material = Array.isArray(original) ? original.map(cloneOf) : cloneOf(original)
    const depth = patch(new three.MeshDepthMaterial({ depthPacking: three.RGBADepthPacking }), uniforms, weighted)
    const distance = patch(new three.MeshDistanceMaterial(), uniforms, weighted)
    owned.push(depth, distance)
    const state: State = {
      entry: { mesh, kind, capsules, local: [] }, binds, uniforms, original, owned,
      depth: mesh.customDepthMaterial, distance: mesh.customDistanceMaterial,
      ownHooks: { render: Object.prototype.hasOwnProperty.call(mesh, 'onBeforeRender'), shadow: Object.prototype.hasOwnProperty.call(mesh, 'onBeforeShadow') },
      beforeRender: mesh.onBeforeRender, beforeShadow: mesh.onBeforeShadow, frame: -1,
    }
    mesh.customDepthMaterial = depth
    mesh.customDistanceMaterial = distance
    const prevRender = state.beforeRender
    const prevShadow = state.beforeShadow
    mesh.onBeforeRender = function (renderer, scene, camera, geometry, material, group) {
      frameUpdate(state, renderer.info.render.frame)
      prevRender.call(this, renderer, scene, camera, geometry, material, group)
    }
    mesh.onBeforeShadow = function (renderer, object, camera, shadowCamera, geometry, depthMaterial, group) {
      frameUpdate(state, renderer.info.render.frame)
      prevShadow.call(this, renderer, object, camera, shadowCamera, geometry, depthMaterial, group)
    }
    writeUniforms(state)
    states.push(state)
  }
  if (!states.length) return null

  return {
    binding,
    get entries() { return states.map(s => s.entry) },
    update() {
      binding.update()
      for (const state of states) writeUniforms(state)
    },
    dispose() {
      for (const state of states) {
        const { mesh } = state.entry
        mesh.material = state.original
        mesh.customDepthMaterial = state.depth
        mesh.customDistanceMaterial = state.distance
        // A hook the mesh did not own came from the prototype: drop ours, do not pin a copy.
        if (state.ownHooks.render) mesh.onBeforeRender = state.beforeRender
        else delete (mesh as Partial<Pick<SkinnedMesh, 'onBeforeRender'>>).onBeforeRender
        if (state.ownHooks.shadow) mesh.onBeforeShadow = state.beforeShadow
        else delete (mesh as Partial<Pick<SkinnedMesh, 'onBeforeShadow'>>).onBeforeShadow
        for (const m of state.owned) m.dispose()
      }
      states.length = 0
    },
  }
}
