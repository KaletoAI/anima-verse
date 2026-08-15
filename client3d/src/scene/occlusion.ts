/**
 * occlusion — THE CORRIDOR between the camera and the embodied avatar.
 *
 * Standing in a wood, the player looks at leaves: the tree the camera hangs
 * behind is between the eye and the figure, and no amount of camera logic gets
 * rid of it — the trees are INSTANCED, and an instanced mesh has no per-instance
 * opacity to turn down. Picking the offenders by raycast would mean a ledger per
 * instance, a hysteresis to stop them flickering, and a rebuilt instance buffer
 * on every step.
 *
 * So the geometry decides, per fragment: everything whose WORLD position lies
 * within `uOccRadius` of the segment camera→avatar-chest is thinned out by an
 * ordered (Bayer 4×4) dither and discarded. A screen door, not transparency —
 * so there is no sorting problem, no second draw pass and no material state to
 * restore. It is a continuous function of the geometry, which is why it needs no
 * hysteresis at all: walk half a metre and half a bush more is gone.
 *
 * WHAT IS PATCHED is decided by the callers, and deliberately narrow: the
 * scattered props of the painted ground (`scene/ground.ts`) and the building
 * shells of the world view (`scene/tiles.ts`, and the server model in
 * `scene/sceneRecipe.ts`). NOT the ground itself, not the figures, not the
 * interior geometry of the open detail view (the existing tile fade rules
 * there), not water and not the fog veil.
 *
 * THE UNIFORMS ARE SHARED, exactly like the surface clock `surfaceTimeUniform`
 * of @anima/scene-render: one object per value, written ONCE per frame by
 * `updateOcclusion` (from `main.ts`), read by every patched material. Fifty
 * patched materials therefore cost one uniform update, and the patch's cache key
 * is a CONSTANT — the corridor moves through the uniforms, never through the
 * compiled program.
 *
 * NO SETTING, no slider. These are numbers of the view, not of the world.
 */
import * as THREE from 'three';

/** Half-width of the corridor in metres. One metre is a shoulder's worth to
 *  either side of the line of sight: wide enough that a trunk dead ahead really
 *  opens up, narrow enough that the wood around it stays a wood. */
export const OCC_RADIUS_M = 1.0;
/** Beyond this camera distance to the avatar nothing is thinned at all — the
 *  overview is a MAP, and a corridor cut through a distant town would be a
 *  visible scar for a figure nobody is looking at from behind. */
export const OCC_GATE_M = 25;
/** …and it does not switch off at the gate: from here to the gate the strength
 *  fades to zero, so a wheel turn past 25 m dissolves the corridor instead of
 *  popping a tree back into the picture. */
export const OCC_FADE_FROM_M = 20;
/** The corridor STARTS this far in front of the camera. Without the gap the
 *  segment would reach the lens and a wall the camera is pressed against would
 *  dissolve into a dither pattern that fills the screen. */
export const OCC_CAM_CLEAR_M = 0.5;
/** …and it ENDS at the avatar's chest, not at its feet: the figure itself and
 *  the ground behind it must stay whole, and a segment ending on the floor
 *  would cut a hole around the feet. 1.2 m is chest height on the 1.70 m
 *  reference figure. */
export const OCC_CHEST_M = 1.2;

/** The cache key this patch contributes. Exported so the smoke can pin the
 *  COMBINED key without carrying a copy of the string. Constant on purpose: the
 *  corridor is steered by uniforms, so a key per frame would recompile every
 *  patched program sixty times a second. */
export const OCC_CACHE_KEY = 'occlusion-corridor';

/** What the callers hand in — a plain point, so the arithmetic below is
 *  testable without three (the smoke calls it with object literals). */
export interface OccPoint { x: number; y: number; z: number }

/** What one frame's evaluation yields: the two ends of the segment in world
 *  metres, the radius, and how much of the corridor is taken away (0 = nothing,
 *  the patch is then provably neutral). Plain numbers — this is the whole
 *  TS-side decision, and the smoke checks it by hand. */
export interface OccState {
  a: [number, number, number];
  b: [number, number, number];
  radius: number;
  strength: number;
}

/**
 * The corridor of ONE frame — pure arithmetic, no three, no side effect.
 *
 * `embodied` is the switch that keeps an unembodied client at exactly today's
 * picture: strength 0, and the shader's own guard then discards nothing.
 * Without an avatar position (the figure has not arrived on the map yet) the
 * answer is the same.
 */
export function occlusionUniforms(cam: OccPoint, avatar: OccPoint | null,
                                  embodied: boolean): OccState {
  const b: [number, number, number] = avatar
    ? [avatar.x, avatar.y + OCC_CHEST_M, avatar.z]
    : [0, 0, 0];
  if (!embodied || !avatar) {
    return { a: b, b, radius: OCC_RADIUS_M, strength: 0 };
  }
  const dx = b[0] - cam.x;
  const dy = b[1] - cam.y;
  const dz = b[2] - cam.z;
  const d = Math.hypot(dx, dy, dz);
  // The gate is measured to the SAME point the corridor ends at, so one
  // distance answers both questions and they can never disagree.
  const strength = Math.min(Math.max((OCC_GATE_M - d) / (OCC_GATE_M - OCC_FADE_FROM_M), 0), 1);
  // Camera end: `OCC_CAM_CLEAR_M` along the line of sight. A camera closer than
  // that to the chest has no corridor left to speak of — the segment collapses
  // onto the chest rather than turning round.
  const a: [number, number, number] = d > OCC_CAM_CLEAR_M
    ? [cam.x + (dx / d) * OCC_CAM_CLEAR_M,
       cam.y + (dy / d) * OCC_CAM_CLEAR_M,
       cam.z + (dz / d) * OCC_CAM_CLEAR_M]
    : b;
  return { a, b, radius: OCC_RADIUS_M, strength };
}

// ── The shared uniforms ────────────────────────────────────────────────────
// ONE object per value for every patched material — the `surfaceTimeUniform`
// pattern of @anima/scene-render. Exported for the smoke; the app writes them
// through `updateOcclusion` alone.
export const occA = { value: new THREE.Vector3() };
export const occB = { value: new THREE.Vector3() };
export const occRadius = { value: OCC_RADIUS_M };
export const occStrength = { value: 0 };

/** Evaluate the corridor and write the shared uniforms — ONCE per frame, from
 *  the frame hook in `main.ts`. Nothing else may write them. */
export function updateOcclusion(cam: OccPoint, avatar: OccPoint | null,
                                embodied: boolean): OccState {
  const st = occlusionUniforms(cam, avatar, embodied);
  occA.value.set(st.a[0], st.a[1], st.a[2]);
  occB.value.set(st.b[0], st.b[1], st.b[2]);
  occRadius.value = st.radius;
  occStrength.value = st.strength;
  return st;
}

/** Materials that already carry the corridor test. The patch CHAINS onto
 *  whatever sits in the slot, so applying it twice would declare `vOccWorld`
 *  twice and the shader would not compile — same guard, same reason as
 *  `patchHole`/`applySway` in `scene/ground.ts`. */
const occPatched = new WeakSet<THREE.Material>();

/** Where the world position is taken. AFTER `project_vertex`, not at
 *  `begin_vertex`: the sway patch displaces `transformed` at the earlier anchor
 *  and a corridor measured before it would test the unbent blade. */
const ANCHOR_VERT = '#include <project_vertex>';
/** …and the discard goes before the clipping include, exactly where the hole
 *  test goes: a fragment that is gone should cost nothing after it. */
const ANCHOR_FRAG = '#include <clipping_planes_fragment>';

/**
 * Give a material the corridor test.
 *
 * CHAINED, never assigned — the rule of this repo's shader patches (see
 * `patchHole` in `scene/ground.ts` for the finding that made it a rule: one
 * slot, two writers, last one wins, and the water shader was built and thrown
 * away one line later). A scatter material arrives here with `applySway`
 * already in the slot, so the previous callback runs FIRST and the keys are
 * combined.
 *
 * THE CALLER OWNS THE MATERIAL. `loadGlb` caches the loaded file, so a material
 * that came out of it belongs to every other user of that prop — patching it
 * would make a placed tree in a scene dissolve too. The scatter path therefore
 * clones per entry (`mountUrl`), the tile shells are built per tile anyway, and
 * the server model is patched on the clones `applySceneBuilding` makes.
 */
export function applyOcclusionFade(mat: THREE.Material): void {
  if (occPatched.has(mat)) return;
  occPatched.add(mat);
  const prev = mat.onBeforeCompile;
  // three's DEFAULT `customProgramCacheKey` returns `onBeforeCompile.toString()`
  // — only a patch with a key of its OWN is worth carrying. Read here, before
  // the slot below is overwritten.
  const prevKey = Object.prototype.hasOwnProperty.call(mat, 'customProgramCacheKey')
    ? String(mat.customProgramCacheKey())
    : '';
  mat.onBeforeCompile = (shader, renderer) => {
    prev.call(mat, shader, renderer);
    shader.uniforms.uOccA = occA;
    shader.uniforms.uOccB = occB;
    shader.uniforms.uOccRadius = occRadius;
    shader.uniforms.uOccStrength = occStrength;
    // A three version without the anchor leaves the material UNPATCHED whole:
    // the fragment side alone would read a varying the vertex side never wrote.
    if (!shader.vertexShader.includes(ANCHOR_VERT)) return;
    // The instancing branch is not cosmetic: at `project_vertex` the chunk
    // itself applies `instanceMatrix`, so `transformed` is still the untouched
    // prototype position. Without the branch every blade of a meadow would
    // report the position of the mesh's origin and the whole entry would blink
    // as one.
    const world = `
  #ifdef USE_INSTANCING
    vOccWorld = ( modelMatrix * instanceMatrix * vec4( transformed, 1.0 ) ).xyz;
  #else
    vOccWorld = ( modelMatrix * vec4( transformed, 1.0 ) ).xyz;
  #endif
`;
    shader.vertexShader = `varying vec3 vOccWorld;\n${shader.vertexShader}`
      .replace(ANCHOR_VERT, `${ANCHOR_VERT}\n${world}`);

    const head = 'uniform vec3 uOccA;\nuniform vec3 uOccB;\n'
      + 'uniform float uOccRadius;\nuniform float uOccStrength;\n'
      + 'varying vec3 vOccWorld;\n';
    // Point-to-SEGMENT distance, not point-to-line: the corridor has two ends,
    // and a line would keep thinning props behind the avatar and behind the
    // camera. `occT` is the projection clamped to [0,1] — that clamp IS the
    // difference.
    //
    // The threshold is an ORDERED 4×4 Bayer matrix, computed instead of looked
    // up: GLSL ES 1.00 has neither bitwise operators nor dynamic indexing into
    // a const array, and the classic index (bit-reverse of the interleaved
    // coordinates) is four `mod`s and two `abs`s in float arithmetic. Ordered
    // rather than random because a fixed pattern stands still while the camera
    // moves — noise would boil.
    const test = `
  if ( uOccStrength > 0.0 ) {
    vec3 occAB = uOccB - uOccA;
    float occLen2 = max( dot( occAB, occAB ), 1e-6 );
    float occT = clamp( dot( vOccWorld - uOccA, occAB ) / occLen2, 0.0, 1.0 );
    float occDist = distance( vOccWorld, uOccA + occAB * occT );
    // Soft edge: full inside half the radius, nothing outside it — a hard rim
    // would draw a circle of dither on the ground cover.
    float occHide = uOccStrength * ( 1.0 - smoothstep( uOccRadius * 0.5, uOccRadius, occDist ) );
    vec2 occPix = mod( floor( gl_FragCoord.xy ), 4.0 );
    float occX0 = mod( occPix.x, 2.0 );
    float occX1 = mod( floor( occPix.x / 2.0 ), 2.0 );
    float occY0 = mod( occPix.y, 2.0 );
    float occY1 = mod( floor( occPix.y / 2.0 ), 2.0 );
    float occThreshold = ( abs( occY0 - occX0 ) * 8.0 + occY0 * 4.0
                         + abs( occY1 - occX1 ) * 2.0 + occY1 ) / 16.0;
    if ( occHide > occThreshold ) discard;
  }
`;
    const body = head + shader.fragmentShader;
    shader.fragmentShader = body.includes(ANCHOR_FRAG)
      ? body.replace(ANCHOR_FRAG, `${test}\n${ANCHOR_FRAG}`)
      : body.replace('void main() {', `void main() {\n${test}`);
  };
  mat.customProgramCacheKey = () => (prevKey ? `${prevKey}+${OCC_CACHE_KEY}` : OCC_CACHE_KEY);
}
