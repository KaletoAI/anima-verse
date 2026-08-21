/**
 * THE WATER MIRROR — one RULED surface per painted water ("Ein Boden" E4,
 * § G4; tilted since "Ein Wasser-Gesetz" W2).
 *
 * WHAT IT REPLACES. Until E3 every painted ground was a transparent DRAPE laid
 * on the relief; E3 cut all of them into the one terrain material and left
 * exactly one behind, the water ripple, two centimetres over its own bed
 * (`ground.WATER_DRAPE_LIFT_M`). That drape was the last coplanar ground mesh
 * in the world, and it was also wrong in a way no lift could fix: a draped
 * surface FOLLOWS the bed, so a lake ran downhill and a swimmer floated over
 * the slope instead of on a water line.
 *
 * A LAKE HAS ONE HEIGHT, A RIVER HAS A PROFILE. Since W1 both are the same
 * nine numbers in the payload (`meta.water_profile`, § A16.3), and the bed
 * under them is carved to `h ≤ water_level_at(x, z) − ε` in EVERY mip level —
 * so the mirror is a plain earcut polygon whose vertices are each lifted to the
 * level of their own place (`liftToWaterProfile`), with no subdivision at all:
 * a ruled surface needs no vertices in the middle either.
 *
 * THE SHORE COMES OUT OF THE DATA. `depth(x, z) = level − h(x, z)`, sampled in
 * the fragment shader from the very R32F pyramids the terrain's vertices are
 * placed by (`terrainLod.terrainLodSampleGlsl`), ramps the alpha over
 * `WATER_SHORE_BAND_M` and lays a foam lace over the first half metre
 * (`waterPlaneMath.ts`, every number hand-derived there). No depth prepass, no
 * screen-space depth texture, no second render target — the ground is already
 * a function we can ask.
 *
 * THE LEVEL IS THE GEOMETRY. The fragment reads the plane's own world `y`, so
 * every water of one kind shares ONE material however many heights they stand
 * at — two lakes at two levels are two meshes, not two shaders, and a tilted
 * river is a third mesh on the same material. That is also why the SHORE did
 * not have to change one line for W2: it always measured against the geometry.
 *
 * THE FLOW IS AN ATTRIBUTE, for the same reason. The ripple has to scroll
 * downstream, and the flow direction belongs to the AREA while the material
 * belongs to the KIND — a uniform would therefore have forced one material per
 * area (and with it one compiled program's worth of state per lake) to say a
 * thing that costs two floats. `aWaterFlow` is those two floats, constant over
 * a mesh of a dozen vertices; a geometry that does not carry it reads (0, 0),
 * which the shader spells "still water, keep the lake's crossing drift".
 */
import * as THREE from 'three';
import { bindTerrainLodUniforms, terrainLodSampleGlsl } from './terrainLod';
import { WATER_FOAM_ALPHA, WATER_FOAM_BAND_M, WATER_FOAM_STRENGTH,
  WATER_SHORE_BAND_M, liftToWaterProfile, waterFlowVector, waterShoreBody,
  waterShoreGlsl } from './waterPlaneMath';
import type { WaterProfile } from './waterPlaneMath';

/** The cache key this patch contributes, exported so the smoke can pin the
 *  combined key without carrying a copy of the string. */
export const WATER_SHORE_CACHE_KEY = 'water-shore';

/** Materials that already carry the shore. The patch CHAINS onto whatever sits
 *  in the slot (the ripple of `@anima/scene-render` `materials.ts`, then the
 *  basement hole of `ground.patchHole`), so applying it twice would declare
 *  `vWaterPlane` a second time and the shader would not compile. */
const shorePatched = new WeakSet<THREE.Material>();

/** The four shore numbers as shared uniform objects — ONE per value for every
 *  water material, the pattern of `naturalGround.ts` and `terrainLod.ts`. They
 *  are constants today; being uniforms costs nothing and is what would let a
 *  kind carry its own band without a recompile. */
const uShoreBand = { value: WATER_SHORE_BAND_M };
const uFoamBand = { value: WATER_FOAM_BAND_M };
const uFoamStrength = { value: WATER_FOAM_STRENGTH };
const uFoamAlpha = { value: WATER_FOAM_ALPHA };

/**
 * Give a water material its shore.
 *
 * ONE INSERTION POINT, right before `#include <opaque_fragment>`: that is the
 * last chunk in which `diffuseColor.a` and `outgoingLight` are both still
 * writable, so the alpha ramp and the foam tint are one block instead of three
 * anchors that could drift apart. It also lands AFTER the ripple's own sky
 * fresnel (that patch inserted its block before the same anchor earlier, so it
 * now sits above this one) — foam over reflection, which is the right order.
 *
 * The vertex half is the world position, taken at `#include <begin_vertex>`
 * like the ripple's own `vWaterWorld`. Both anchors are `#include` LINES on
 * purpose (the finding of 2026-07-29): `onBeforeCompile` sees the shader
 * BEFORE three resolves its includes, so an anchor from a chunk's body is a
 * line that is never there.
 */
export function patchWaterShore(mat: THREE.Material): void {
  if (shorePatched.has(mat)) return;
  shorePatched.add(mat);
  const prev = mat.onBeforeCompile;
  const prevKey = Object.prototype.hasOwnProperty.call(mat, 'customProgramCacheKey')
    ? String(mat.customProgramCacheKey())
    : '';
  mat.onBeforeCompile = (shader, renderer) => {
    prev.call(mat, shader, renderer);
    // The SAME uniform objects the terrain reads its height through: a pyramid
    // swap must reach both, or the lake measures its depth against yesterday's
    // ground for as long as the world stands.
    bindTerrainLodUniforms(shader.uniforms as unknown as Record<string, unknown>);
    shader.uniforms.uShoreBandM = uShoreBand;
    shader.uniforms.uFoamBandM = uFoamBand;
    shader.uniforms.uFoamStrength = uFoamStrength;
    shader.uniforms.uFoamAlpha = uFoamAlpha;
    if (!shader.vertexShader.includes('#include <begin_vertex>')
        || !shader.fragmentShader.includes('#include <opaque_fragment>')) return;
    shader.vertexShader = `varying vec3 vWaterPlane;\n${shader.vertexShader}`
      .replace('#include <begin_vertex>',
        '#include <begin_vertex>\n\tvWaterPlane = ( modelMatrix * vec4( transformed, 1.0 ) ).xyz;');
    shader.fragmentShader = terrainLodSampleGlsl() + waterShoreGlsl()
      + shader.fragmentShader.replace('#include <opaque_fragment>',
        `${waterShoreBody()}\n#include <opaque_fragment>`);
  };
  mat.customProgramCacheKey = () => (prevKey
    ? `${prevKey}+${WATER_SHORE_CACHE_KEY}`
    : WATER_SHORE_CACHE_KEY);
}

/**
 * The mirror of ONE painted water: its own earcut, every vertex lifted to the
 * level of its own place.
 *
 * `geometry` is what `buildAreaGeometry` already produced for this area — the
 * outline triangulated in the XZ plane, with a `y` that means nothing. This
 * WRITES that `y`: `liftToWaterProfile` gives each vertex `waterLevelAt(x, z)`,
 * which for a lake is one constant (the flat plane of E4, unchanged to the last
 * bit) and for a river is the tilted plane its bed was carved against. The mesh
 * itself stays at the origin — moving it would add a translation to a height
 * that is already absolute. Ownership of the geometry passes to the caller's
 * disposal bag as before.
 *
 * NO GRID SUBDIVISION. Every other ground mesh this client ever built was cut
 * along the height lattice so it could follow the relief; a mirror is a RULED
 * SURFACE, linear between its own outline vertices, and the shore that used to
 * need geometry is a fragment computation now. A kilometre-long river is a
 * handful of triangles.
 *
 * `depthWrite` stays off (set on the material) and `depthTest` on: the water is
 * drawn after the opaque terrain, is occluded by everything in front of it, and
 * occludes nothing itself — a bed seen through it is the point.
 */
export function buildWaterPlane(geometry: THREE.BufferGeometry,
                                profile: WaterProfile,
                                material: THREE.Material): THREE.Mesh {
  const pos = geometry.getAttribute('position') as THREE.BufferAttribute;
  liftToWaterProfile(pos.array as unknown as { length: number;
                                               [index: number]: number },
                     profile);
  pos.needsUpdate = true;
  // The bounding sphere was computed for a flat polygon at y ≈ 0; a river that
  // climbs eight metres over its length would be culled by a sphere that does
  // not contain it.
  geometry.computeBoundingSphere();
  // THE FLOW, one vec2 per vertex — see the file header for why it is not a
  // uniform. It is constant over the mesh; the interpolator hands the fragment
  // back exactly what was written.
  const [fx, fz] = waterFlowVector(profile);
  const flow = new Float32Array(pos.count * 2);
  for (let i = 0; i < pos.count; i += 1) {
    flow[i * 2] = fx;
    flow[i * 2 + 1] = fz;
  }
  geometry.setAttribute('aWaterFlow', new THREE.BufferAttribute(flow, 2));
  const mesh = new THREE.Mesh(geometry, material);
  // A mirror takes shadows (a tree on the bank darkens the water) but casts
  // none — the same arrangement the drape had.
  mesh.receiveShadow = true;
  return mesh;
}
