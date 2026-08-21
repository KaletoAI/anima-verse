/**
 * THE WATER MIRROR — one flat plane per painted lake ("Ein Boden" E4, § G4).
 *
 * WHAT IT REPLACES. Until E3 every painted ground was a transparent DRAPE laid
 * on the relief; E3 cut all of them into the one terrain material and left
 * exactly one behind, the water ripple, two centimetres over its own bed
 * (`ground.WATER_DRAPE_LIFT_M`). That drape was the last coplanar ground mesh
 * in the world, and it was also wrong in a way no lift could fix: a draped
 * surface FOLLOWS the bed, so a lake ran downhill and a swimmer floated over
 * the slope instead of on a water line.
 *
 * A lake has ONE height. Since E1 that height is a number in the payload
 * (`meta.water_level_effective`, § A16 addendum § 2), and the bed under it is
 * carved to `h ≤ level − ε` in EVERY mip level — so the mirror is a plain
 * earcut polygon at `y = level`, with no subdivision at all: a plane needs no
 * vertices in the middle.
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
 * every lake of one kind shares ONE material however many heights they stand
 * at — two lakes at two levels are two meshes, not two shaders.
 */
import * as THREE from 'three';
import { bindTerrainLodUniforms, terrainLodSampleGlsl } from './terrainLod';
import { WATER_FOAM_ALPHA, WATER_FOAM_BAND_M, WATER_FOAM_STRENGTH,
  WATER_SHORE_BAND_M, waterShoreBody, waterShoreGlsl } from './waterPlaneMath';

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
 * The mirror of ONE painted lake: its own flat earcut, raised to its level.
 *
 * `geometry` is what `buildAreaGeometry` already produced for this area — the
 * outline triangulated in the XZ plane at y = 0, which is EXACTLY a mirror and
 * needs nothing done to it. The mesh is simply moved up; the ownership of the
 * geometry passes to the caller's disposal bag as before.
 *
 * NO GRID SUBDIVISION. Every other ground mesh this client ever built was cut
 * along the height lattice so it could follow the relief; a mirror is a PLANE,
 * and the shore that used to need geometry is a fragment computation now. A
 * kilometre-wide lake is a handful of triangles.
 *
 * `depthWrite` stays off (set on the material) and `depthTest` on: the water is
 * drawn after the opaque terrain, is occluded by everything in front of it, and
 * occludes nothing itself — a bed seen through it is the point.
 */
export function buildWaterPlane(geometry: THREE.BufferGeometry, levelY: number,
                                material: THREE.Material): THREE.Mesh {
  const mesh = new THREE.Mesh(geometry, material);
  mesh.position.y = levelY;
  // A mirror takes shadows (a tree on the bank darkens the water) but casts
  // none — the same arrangement the drape had.
  mesh.receiveShadow = true;
  return mesh;
}
