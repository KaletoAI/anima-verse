/**
 * THE POINT LIGHT ON A ROOM DIORAMA (plan-diorama-hover.md, user decision
 * 2026-08-29): a place that sits on a piece of furniture INSIDE a diorama has
 * no mesh of its own — the whole room is one model. So the hover cannot
 * brighten "the prop": it brightens a RADIUS around the hovered slot, and the
 * chair under the pointer reads as "this one" while the rest of the room
 * stays as it was.
 *
 * WHY UNIFORMS AND NOT A MATERIAL CLONE. `highlightProp` swaps in emissive
 * clones, which on a diorama would light the entire room — and worse,
 * `Material.clone()` copies neither `onBeforeCompile` nor
 * `customProgramCacheKey`, so the clone would silently lose the shell clip
 * (`packages/scene-render/src/clip.ts`) and the depth cut the diorama already
 * wears. This module therefore patches the material the mesh ALREADY has, in
 * place and exactly once, and a hover only writes three numbers into it.
 *
 * The patch CHAINS: whatever `onBeforeCompile` the clip or the cut installed
 * runs FIRST and this one extends its result, and the program cache key keeps
 * the old key with `|spot` appended — two materials that differ in the old
 * key keep two programs, as before.
 *
 * The GLSL text transforms are pure and hand-derived in
 * `client3d/scripts/smoke_spot_highlight.mjs`.
 */
import * as THREE from 'three';
import { HOVER_EMISSIVE } from './placeGlyphs';

/** The spot's colour — the SAME one a hovered prop gains
 *  (`HOVER_EMISSIVE`): a seat on a diorama and a seat on a bench must read
 *  identically, they are the same offer. */
const SPOT_COLOR_GLSL = [16, 8, 0]
  .map((shift) => (((HOVER_EMISSIVE >> shift) & 0xff) / 255).toFixed(6))
  .join(', ');

/** The vertex anchor: `applyClipOutline` passes `vClipWorld` through at the
 *  very same chunk, and for the same reason — `transformed` is final after
 *  `project_vertex`, so the world position derived there is the one the
 *  fragment shades. */
const VERTEX_ANCHOR = '#include <project_vertex>';
/** The fragment anchor: after the emissive chunk `totalEmissiveRadiance`
 *  exists and is still summed into the outgoing light. A material without
 *  this chunk (a basic/line material) has nothing to add to and is left
 *  alone — see `installSpotHighlight`. */
const FRAGMENT_ANCHOR = '#include <emissivemap_fragment>';

/** Pass the world position of the fragment through. Unchanged when the
 *  anchor is missing, and idempotent: `onBeforeCompile` runs again on every
 *  recompile, and a second `varying` declaration is a redeclaration error. */
export function spotVertex(src: string): string {
  if (src.includes('vSpotWorld')) return src;
  if (!src.includes(VERTEX_ANCHOR)) return src;
  return `varying vec3 vSpotWorld;\n${src}`.replace(VERTEX_ANCHOR,
    `${VERTEX_ANCHOR}\n\tvSpotWorld = ( modelMatrix * vec4( transformed, 1.0 ) ).xyz;`);
}

/** Add the spot to the emissive term: full colour on the slot point, fading
 *  out between half the radius and the radius, nothing beyond it —
 *  `1 − smoothstep(r · 0.5, r, dist)`. `uSpotStrength` 0 is the off state and
 *  the value the install leaves behind. Unchanged without the anchor,
 *  idempotent, same as `spotVertex`. */
export function spotFragment(src: string): string {
  if (src.includes('uSpotStrength')) return src;
  if (!src.includes(FRAGMENT_ANCHOR)) return src;
  const head = 'uniform vec3 uSpotPoint;\n'
    + 'uniform float uSpotRadius;\n'
    + 'uniform float uSpotStrength;\n'
    + 'varying vec3 vSpotWorld;\n'
    + `const vec3 SPOT_COLOR = vec3( ${SPOT_COLOR_GLSL} );\n`;
  return (head + src).replace(FRAGMENT_ANCHOR,
    `${FRAGMENT_ANCHOR}\n\ttotalEmissiveRadiance += SPOT_COLOR * uSpotStrength`
    + ' * ( 1.0 - smoothstep( uSpotRadius * 0.5, uSpotRadius,'
    + ' distance( vSpotWorld, uSpotPoint ) ) );');
}

/** The three uniforms of one patched material, held by the module so a
 *  `setSpot` reaches them without touching `userData` — `Material.copy()`
 *  JSON-clones `userData`, which would turn a live uniform into a dead
 *  plain object on the next tier swap. */
interface SpotUniforms {
  uSpotPoint: { value: THREE.Vector3 };
  uSpotRadius: { value: number };
  uSpotStrength: { value: number };
}
const patched = new WeakMap<THREE.Material, SpotUniforms>();
/** Three's own `customProgramCacheKey`, i.e. "this material has none of its
 *  own" — see the snapshot in `patchMaterial`. */
const DEFAULT_CACHE_KEY = THREE.Material.prototype.customProgramCacheKey;

function patchMaterial(mat: THREE.Material): void {
  // No emissive channel, no `totalEmissiveRadiance` — the same gate
  // `highlightProp` applies, and the reason `spotFragment` finds no anchor.
  if (!('emissive' in mat) || patched.has(mat)) return;
  const u: SpotUniforms = {
    uSpotPoint: { value: new THREE.Vector3() },
    uSpotRadius: { value: 1 },
    uSpotStrength: { value: 0 },
  };
  patched.set(mat, u);
  const prevCompile = mat.onBeforeCompile;
  const prevKey = mat.customProgramCacheKey;
  // Three's DEFAULT cache key IS `this.onBeforeCompile.toString()`, so it has
  // to be snapshotted BEFORE the chain replaces that function: read later it
  // would answer this patch's own source for every material that had no key
  // of its own, and materials that differ in their compile hook would collapse
  // onto one program. A material with a key of its own (the clip, the cut)
  // keeps answering it, whenever it is asked.
  const baseKey = prevKey === DEFAULT_CACHE_KEY ? prevCompile.toString() : null;
  mat.onBeforeCompile = (shader, renderer) => {
    prevCompile.call(mat, shader, renderer);
    shader.uniforms.uSpotPoint = u.uSpotPoint;
    shader.uniforms.uSpotRadius = u.uSpotRadius;
    shader.uniforms.uSpotStrength = u.uSpotStrength;
    shader.vertexShader = spotVertex(shader.vertexShader);
    shader.fragmentShader = spotFragment(shader.fragmentShader);
  };
  mat.customProgramCacheKey = () => `${baseKey ?? prevKey.call(mat)}|spot`;
  mat.needsUpdate = true;
}

function forEachMaterial(root: THREE.Object3D, fn: (mat: THREE.Material) => void): void {
  root.traverse((o) => {
    const mesh = o as THREE.Mesh;
    if (!mesh.isMesh || !mesh.material) return;
    const list = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
    for (const mat of list) if (mat) fn(mat);
  });
}

/** Install the spot on every material under `root` — at MOUNT and again
 *  after a LOD swap, which builds a fresh group with fresh clones. Cheap to
 *  repeat: a material that already carries the patch is skipped, so the
 *  caller may simply run it on every rebuild. */
export function installSpotHighlight(root: THREE.Object3D): void {
  forEachMaterial(root, patchMaterial);
}

/** Move the spot (world metres) or switch it off (`point: null`). Uniforms
 *  only — no recompile, no material swap, nothing to undo. */
export function setSpot(root: THREE.Object3D, point: THREE.Vector3 | null,
                        radius: number): void {
  forEachMaterial(root, (mat) => {
    const u = patched.get(mat);
    if (!u) return;
    if (!point) {
      u.uSpotStrength.value = 0;
      return;
    }
    u.uSpotPoint.value.copy(point);
    u.uSpotRadius.value = radius;
    u.uSpotStrength.value = 1;
  });
}
