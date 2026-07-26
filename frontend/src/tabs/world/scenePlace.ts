/**
 * scenePlace — the ONE place() routine of contract § B2, shared by the 3D
 * floor-plan preview and the 2D top-down underlay so a model lands at
 * IDENTICAL world coordinates in both (finding 2026-07-25: the underlay
 * still ran the legacy fit chain and drifted from the preview).
 *
 * Pure geometry: clone the source, apply the orientation fix, measure,
 * scale per scale_mode, yaw as the PARENT rotation (never combined into one
 * Euler — an x/z fix would tilt with it), then seat the result's BBox on
 * bottom_y / anchor, and — when the spec asks for it — clip the result to the
 * room shell. No scene wiring, no verify — the callers do that.
 */
import type { Material, Mesh, Object3D,
  WebGLProgramParametersWithUniforms } from 'three'
import type { SceneModelSpec } from './worldTypes'

/** The ONE geometry number that stays client-side: contract § B2 puts the
 *  0.96 fit margin into the consumer's place() routine (fit_box fallback). */
export const FIT_BOX_MARGIN = 0.96

/** Same cap as the composer's ``CLIP_OUTLINE_MAX_POINTS`` — the test runs per
 *  fragment, so the server never sends more and we never compile more. */
const CLIP_MAX_POINTS = 32

/** Point-in-polygon by ray-casting parity, injected in front of the fragment
 *  main's clipping chunk. ``clipPrev`` walks the edge (i-1 → i) instead of
 *  indexing ``uClip`` twice: only the loop index and constant expressions may
 *  index a uniform array in GLSL ES 1.0. The && short-circuits, so the
 *  division never sees the straddle-free (and therefore zero) case. */
const CLIP_TEST = /* glsl */`
  vec2 clipP = vec2( vClipWorld.x, vClipWorld.z );
  bool clipInside = false;
  vec2 clipPrev = uClip[ CLIP_N - 1 ];
  for ( int i = 0; i < CLIP_N; i ++ ) {
    vec2 clipCur = uClip[ i ];
    if ( ( ( clipCur.y > clipP.y ) != ( clipPrev.y > clipP.y ) ) &&
         ( clipP.x < ( clipPrev.x - clipCur.x ) * ( clipP.y - clipCur.y ) /
                     ( clipPrev.y - clipCur.y ) + clipCur.x ) ) {
      clipInside = ! clipInside;
    }
    clipPrev = clipCur;
  }
  if ( ! clipInside ) discard;
`

/**
 * Clip a placed model to a WORLD-space polygon (contract § B1
 * ``clip_outline``): every fragment outside the room shell is discarded, so a
 * diorama that overhangs its floor plan ends at the shell.
 *
 * No transformation of the points: the polygon is world, the fragment's
 * position is world — the shader compares them directly. Cut faces stay open
 * (there is no cap geometry), which is why the materials go to DoubleSide:
 * without it a cut room shows nothing at all from the outside.
 *
 * Materials are CLONED before patching — the source object shares them with
 * the model cache, and a patched cache material would keep clipping after the
 * flag is switched off. ``disposeClipMaterials`` frees the clones again.
 */
export function applyClipOutline(THREE: typeof import('three'),
                                 obj: Object3D,
                                 outline: Array<[number, number]>): void {
  const pts = (outline || []).slice(0, CLIP_MAX_POINTS)
  if (pts.length < 3) return
  const n = pts.length
  const uClip = { value: pts.map((p) => new THREE.Vector2(p[0], p[1])) }
  const patch = (shader: WebGLProgramParametersWithUniforms) => {
    shader.uniforms.uClip = uClip
    shader.vertexShader = `varying vec3 vClipWorld;\n${shader.vertexShader}`
      .replace('#include <project_vertex>',
        '#include <project_vertex>\n\tvClipWorld = ( modelMatrix * vec4( transformed, 1.0 ) ).xyz;')
    const head = `#define CLIP_N ${n}\nuniform vec2 uClip[ CLIP_N ];\n`
      + 'varying vec3 vClipWorld;\n'
    const body = head + shader.fragmentShader
    shader.fragmentShader = body.includes('#include <clipping_planes_fragment>')
      ? body.replace('#include <clipping_planes_fragment>',
                     `${CLIP_TEST}\n#include <clipping_planes_fragment>`)
      : body.replace('void main() {', `void main() {\n${CLIP_TEST}`)
  }
  obj.traverse((o: Object3D) => {
    const mesh = o as Mesh
    if (!mesh.isMesh) return
    const clipOne = (src: Material): Material => {
      const mat = src.clone()
      mat.side = THREE.DoubleSide
      mat.userData = { ...mat.userData, __clipClone: true }
      mat.onBeforeCompile = patch
      // Three caches compiled programs across materials — without a key that
      // carries the polygon length the variants would share one program.
      mat.customProgramCacheKey = () => `clip:${n}`
      mat.needsUpdate = true
      return mat
    }
    mesh.material = Array.isArray(mesh.material)
      ? mesh.material.map(clipOne)
      : clipOne(mesh.material)
  })
}

/** Dispose the material clones ``applyClipOutline`` made (their textures are
 *  shared with the cache and are deliberately left alone). */
export function disposeClipMaterials(obj: Object3D): void {
  obj.traverse((o: Object3D) => {
    const mesh = o as Mesh
    if (!mesh.isMesh) return
    const mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material]
    for (const m of mats) if (m?.userData?.__clipClone) m.dispose?.()
  })
}

export function placeModelSpec(THREE: typeof import('three'),
                               source: Object3D,
                               spec: SceneModelSpec): Object3D {
  const deg = (v?: number) => ((v || 0) * Math.PI) / 180
  const fix = new THREE.Group()
  fix.add(source.clone(true))
  fix.rotation.set(deg(spec.fix_euler?.x), deg(spec.fix_euler?.y),
                   deg(spec.fix_euler?.z))
  fix.updateMatrixWorld(true)
  const sFix = new THREE.Box3().setFromObject(fix).getSize(new THREE.Vector3())

  const yawG = new THREE.Group()
  yawG.add(fix)
  yawG.rotation.y = -deg(spec.yaw_deg)
  yawG.updateMatrixWorld(true)
  const sYaw = new THREE.Box3().setFromObject(yawG).getSize(new THREE.Vector3())

  const outer = new THREE.Group()
  outer.add(yawG)
  if (spec.scale_axes) {
    // Server-measured mesh: the factors come ready (contract § B4).
    outer.scale.set(spec.scale_axes.xz, spec.scale_axes.y, spec.scale_axes.xz)
  } else if (spec.scale_mode === 'tile_fit') {
    // Buildings fill their tile per AXIS, measured on the ROTATED box:
    // the footprint follows the plan, the height its declared metres.
    const kxz = (spec.box?.xz || 1) / (Math.max(sYaw.x, sYaw.z) || 1)
    const ky = spec.box?.y ? spec.box.y / (sYaw.y || 1) : kxz
    outer.scale.set(kxz, ky, kxz)
  } else if (spec.scale_mode === 'real_size') {
    // ONE law of scale: real metres over the largest measured extent.
    // measure_axes 'xz' ignores the height (dioramas, § B2a).
    const maxExtent = (spec.measure_axes === 'xz'
      ? Math.max(sFix.x, sFix.z)
      : Math.max(sFix.x, sFix.y, sFix.z)) || 1
    outer.scale.setScalar((spec.max_m || 1) / maxExtent)
  } else {
    // fit_box fallback: fit the UNROTATED footprint into the target box.
    outer.scale.setScalar(Math.min((spec.box?.w || 1) / (sFix.x || 1),
                                   (spec.box?.d || 1) / (sFix.z || 1))
                          * FIT_BOX_MARGIN)
  }
  outer.updateMatrixWorld(true)
  const bOut = new THREE.Box3().setFromObject(outer)
  const cOut = bOut.getCenter(new THREE.Vector3())
  outer.position.set(spec.anchor[0] - cOut.x,
                     spec.bottom_y - bOut.min.y,
                     spec.anchor[1] - cOut.z)
  // Shell clip LAST: the shader compares world positions, so the model has to
  // sit where it belongs first (§ B1).
  if (spec.clip_outline?.length) applyClipOutline(THREE, outer, spec.clip_outline)
  return outer
}
