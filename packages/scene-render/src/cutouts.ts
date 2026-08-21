/**
 * Cutouts for AREA locations (plan-area-locations.md) — the inverted twin of
 * the room clip in `clip.ts`.
 *
 * A village or a lake is not a building: fading its model out for the interior
 * view would delete the place. So the model STAYS and gets holes instead — the
 * building floor plan as a whole, plus every indoor room placed outside it.
 * Inside the holes stands the ordinary recipe interior (storey plate, contour
 * walls, rooms).
 *
 * Two differences to `applyClipOutline`, both load-bearing:
 *
 *   1. **Inverted test.** The clip keeps what is INSIDE its polygon; a cutout
 *      discards what is inside ANY of its polygons — a union, not one shape.
 *   2. **Switchable.** The far view must show the model intact, the interior
 *      view the holes. That is a uniform (`uCutOn`), not a second material:
 *      flipping a float leaves the compiled program alone, re-patching would
 *      churn shaders on every zoom.
 *
 * The polygon count and every polygon length are COMPILE-TIME constants, like
 * CLIP_N — the loops keep constant bounds and `customProgramCacheKey` carries
 * the whole shape, so two locations with different cutouts never share a
 * program. Points live in one flat vec2 array with per-polygon offsets,
 * because GLSL ES 1.0 has no arrays of arrays.
 *
 * No transformation of the points: the polygons are world metres, the fragment
 * position is world — the shader compares directly, so the model has to sit in
 * its final place before this is applied (same rule as the clip).
 *
 * Known and accepted (as with the clip): the cut edges stay OPEN, there is no
 * cap geometry, hence DoubleSide.
 */
import type { Material, Mesh, Object3D,
  WebGLProgramParametersWithUniforms } from 'three'

/** Same ceiling as ``CUTOUT_MAX_POLYS`` in the composer — the test runs per
 *  fragment, so the server never sends more and we never compile more. */
export const CUTOUT_MAX_POLYS = 16
/** Per-polygon ceiling, shared with the room clip. 32 → 64 with contract
 *  v5.2 item 11 (tessellated curved hulls) — must follow the composer cap,
 *  or the client truncates silently. */
export const CUTOUT_MAX_POINTS = 64

export interface CutoutHandle {
  /** Holes on (interior view) or off (far view: the model is intact). */
  setEnabled(on: boolean): void
  /** Release the material clones this handle created. */
  dispose(): void
}

/** Parity test per polygon over a flat point array. `uCutOff[p]` is the first
 *  index of polygon p, `uCutLen[p]` its length — walked with a constant outer
 *  bound and an inner `if (i >= len) break;`, which is the only dynamic part
 *  and the price of packing polygons of different lengths into one array. */
const CUT_TEST = /* glsl */`
  if ( uCutOn > 0.5 ) {
    vec2 cutP = vec2( vCutWorld.x, vCutWorld.z );
    bool cutHit = false;
    for ( int p = 0; p < CUT_POLYS; p ++ ) {
      int off = uCutOff[ p ];
      int len = uCutLen[ p ];
      if ( len < 3 ) continue;
      bool inside = false;
      vec2 prev = uCut[ off + len - 1 ];
      for ( int i = 0; i < CUT_MAX_LEN; i ++ ) {
        if ( i >= len ) break;
        vec2 cur = uCut[ off + i ];
        if ( ( ( cur.y > cutP.y ) != ( prev.y > cutP.y ) ) &&
             ( cutP.x < ( prev.x - cur.x ) * ( cutP.y - cur.y ) /
                        ( prev.y - cur.y ) + cur.x ) ) {
          inside = ! inside;
        }
        prev = cur;
      }
      if ( inside ) { cutHit = true; }
    }
    if ( cutHit ) discard;
  }
`

/**
 * Cut world polygons out of a placed model. Returns a handle: `setEnabled`
 * switches the holes (the caller ties that to its interior-view fade),
 * `dispose` frees the material clones.
 *
 * Materials are CLONED before patching — the source shares them with the model
 * cache, and a patched cache material would keep cutting after the flag went
 * away.
 */
export function applyCutouts(THREE: typeof import('three'),
                             obj: Object3D,
                             outlines: Array<Array<[number, number]>>,
                             ): CutoutHandle {
  const polys = (outlines || [])
    .map((o) => (o || []).slice(0, CUTOUT_MAX_POINTS))
    .filter((o) => o.length >= 3)
    .slice(0, CUTOUT_MAX_POLYS)
  const noop: CutoutHandle = { setEnabled: () => {}, dispose: () => {} }
  if (!polys.length) return noop

  const points: InstanceType<typeof THREE.Vector2>[] = []
  const offsets: number[] = []
  const lengths: number[] = []
  for (const poly of polys) {
    offsets.push(points.length)
    lengths.push(poly.length)
    for (const p of poly) points.push(new THREE.Vector2(p[0], p[1]))
  }
  const maxLen = Math.max(...lengths)
  const shape = `${polys.length}:${lengths.join(',')}`

  const uCut = { value: points }
  const uCutOff = { value: offsets }
  const uCutLen = { value: lengths }
  // Starts OFF: a tile is built in the far view, and the model should not
  // flash with holes for the frames before the fade state is applied.
  const uCutOn = { value: 0 }

  const patch = (shader: WebGLProgramParametersWithUniforms) => {
    shader.uniforms.uCut = uCut
    shader.uniforms.uCutOff = uCutOff
    shader.uniforms.uCutLen = uCutLen
    shader.uniforms.uCutOn = uCutOn
    shader.vertexShader = `varying vec3 vCutWorld;\n${shader.vertexShader}`
      .replace('#include <project_vertex>',
        '#include <project_vertex>\n\tvCutWorld = ( modelMatrix * vec4( transformed, 1.0 ) ).xyz;')
    const head = `#define CUT_POLYS ${polys.length}\n`
      + `#define CUT_MAX_LEN ${maxLen}\n`
      + `uniform vec2 uCut[ ${points.length} ];\n`
      + 'uniform int uCutOff[ CUT_POLYS ];\n'
      + 'uniform int uCutLen[ CUT_POLYS ];\n'
      + 'uniform float uCutOn;\n'
      + 'varying vec3 vCutWorld;\n'
    const body = head + shader.fragmentShader
    // Before the clipping chunk: a discarded fragment never walks the rest.
    shader.fragmentShader = body.includes('#include <clipping_planes_fragment>')
      ? body.replace('#include <clipping_planes_fragment>',
                     `${CUT_TEST}\n#include <clipping_planes_fragment>`)
      : body.replace('void main() {', `void main() {\n${CUT_TEST}`)
  }

  const clones: Material[] = []
  obj.traverse((o: Object3D) => {
    const mesh = o as Mesh
    if (!mesh.isMesh) return
    const cutOne = (src: Material): Material => {
      const mat = src.clone()
      mat.side = THREE.DoubleSide
      mat.userData = { ...mat.userData, __cutoutClone: true }
      mat.onBeforeCompile = patch
      mat.customProgramCacheKey = () => `cutout:${shape}`
      mat.needsUpdate = true
      clones.push(mat)
      return mat
    }
    mesh.material = Array.isArray(mesh.material)
      ? mesh.material.map(cutOne)
      : cutOne(mesh.material)
  })

  return {
    setEnabled(on: boolean) { uCutOn.value = on ? 1 : 0 },
    dispose() {
      for (const m of clones) m.dispose?.()
      clones.length = 0
    },
  }
}
