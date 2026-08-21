/**
 * naturalGround — the OPEN WORLD's ground, made to look like ground.
 *
 * A painted area is one texture repeated over hundreds of metres and one flat
 * colour where no texture exists, lit by a sun that knows nothing about the
 * relief under it. From eye level that reads as wallpaper: the same tuft of
 * grass every four metres in a perfect lattice, a meadow that is the identical
 * green from one end of the world to the other, and a hollow that is exactly
 * as bright as the ridge beside it.
 *
 * Three stages fix that, and all three are SHADER work on the materials the
 * ground already has — no new geometry, no second draw call, one extra texture
 * fetch and some noise per fragment. What each stage does and every number it
 * spends is in `naturalGroundMath.ts`; this file is how those numbers reach
 * the GPU.
 *
 * ONE PATCH, CHAINED. The rule of this repo's shader patches, learned the hard
 * way when the water shader was built and thrown away one line later (see
 * `patchHole` in `scene/ground.ts`): `onBeforeCompile` is ONE slot, so the
 * previous callback is captured and called FIRST, the cache keys are combined,
 * and a WeakSet keeps a second application from declaring the varyings twice.
 *
 * WHAT IS PATCHED, and the list is deliberately short: the base plate and the
 * painted area drapes of `scene/ground.ts`, and nothing else. NOT the water
 * and ice areas (they carry their own shader — `isWaterClass`), not the
 * building shells or the location tiles, and not the interiors
 * of the detail scenes: those are floors of a room, and a room floor shaded by
 * the world's relief would darken because the house stands in a dip.
 *
 * THE ADMIN PREVIEWS STAY UNTOUCHED. This is view polish, not geometry, so it
 * does not belong in `@anima/scene-render` — the shared package is for what
 * both renderers must AGREE on (§ B2/B5a), and a floor-plan preview that shows
 * the ground a shade darker in a hollow tells the author nothing.
 *
 * THREE STAGES SINCE E3, and the fourth is worth naming because it is gone: a
 * painted area used to fade out over a per-vertex distance to its own ring
 * (`aEdgeDist`), which is what made every drape a transparent mesh and every
 * ground boundary a sorting problem. A boundary is now a CUT in the one terrain
 * surface, its softness the layer's own `edge_blend_m` acting on the baked
 * signed distance (`@anima/scene-render` `layerCut.ts`). What is left here
 * reads nothing but the fragment's own world position, so it patches ONE
 * material — the terrain's — and takes no arguments at all.
 *
 * THE HEIGHT FIELD ARRIVES AS A DATA TEXTURE, and that is the only resource
 * this file allocates: the OVERVIEW field the client already holds
 * (`ground.ts` `relief.overview`), packed into an R16F texture and uploaded
 * again whenever `height_sig` moves. Half float rather than full: WebGL2
 * filters R16F in core, while linear filtering of R32F needs an extension —
 * and the AO reads the field bilinearly. Its precision is centimetres at the
 * heights a world is shaped in, which is two orders finer than the two-metre
 * span the shading is spent over.
 *
 * THE ONE LIMIT OF THE AO, named because it is a decision and not an oversight:
 * it reads the OVERVIEW, and the overview is coarsenable (§ A16.3 — 8, 16, 32 m
 * between support points on a large world), while the ground the player sees is
 * the composite of overview and fine tiles. Two things follow. The shading
 * drifts against the drawn surface wherever a tile sharpens it — the ridge is
 * lit half a support cell beside where it is. And, more visibly, once the step
 * grows past the 3 m ring the four taps fall inside ONE bilinear cell, where
 * the field is linear along both axes: the mean of two symmetric taps is then
 * exactly the centre value, the difference is exactly 0, and the stage
 * collapses to thin bands of shading along the raster lines, with flat nothing
 * between them. That is the price of reading a field the client already holds
 * instead of allocating a second one at tile resolution, and on the worlds this
 * is spent on (step 2–4 m) the ring still crosses cells. If a world ever ships
 * a 16 m overview and its hollows go flat, this paragraph is the reason.
 */
import * as THREE from 'three';
import type { WorldHeightField } from '@anima/scene-render';
import { ngAoTaps, NG_AO_DOWN, NG_AO_SPAN_M, NG_AO_UP, NG_DETAIL_OFFSET,
  NG_DETAIL_SCALE, NG_MIX_M, NG_MIX_MAX, NG_TINT_AMP,
  NG_TINT_M } from './naturalGroundMath';

/** The cache key this patch contributes. Exported so the smoke can pin the
 *  COMBINED key without carrying a copy of the string. CONSTANT on purpose:
 *  every number of the effect is either a GLSL literal that never changes or a
 *  shared uniform, so all patched ground materials compile to ONE program. */
export const NG_CACHE_KEY = 'natural-ground';

// ── The shared uniforms ────────────────────────────────────────────────────
// ONE object per value for every patched material — the `surfaceTimeUniform`
// pattern of @anima/scene-render and the shared corridor of `occlusion.ts`.
// A world with two hundred painted areas therefore costs ONE upload when the
// relief changes, and nothing recompiles.

/**
 * One R16F height texture, read the way the AO needs it: LINEARLY filtered (the
 * field is defined bilinear, § A16, and a nearest tap would shade the world in
 * squares) and CLAMPED at the edge (outside the raster the world is flat, which
 * is what the border value says).
 */
function makeField(data: Uint16Array, cols: number, rows: number): THREE.DataTexture {
  const tex = new THREE.DataTexture(data, cols, rows,
                                    THREE.RedFormat, THREE.HalfFloatType);
  tex.minFilter = THREE.LinearFilter;
  tex.magFilter = THREE.LinearFilter;
  tex.wrapS = THREE.ClampToEdgeWrapping;
  tex.wrapT = THREE.ClampToEdgeWrapping;
  tex.generateMipmaps = false;
  // Two bytes per texel and no padding: the default alignment of 4 would tear
  // every field with an odd number of columns into a diagonal smear.
  tex.unpackAlignment = 1;
  tex.needsUpdate = true;
  return tex;
}

/** A field that says nothing, so the sampler is never unbound. One texel of
 *  zero: with `uNgStrength` at 0 nothing reads it, and a driver handed a null
 *  sampler is a warning at best and a black ground at worst. Built once and
 *  never freed — it is what every neutral state falls back to. */
const neutralFallback = makeField(new Uint16Array(1), 1, 1);

/** The world's heights, one texel per support point of the OVERVIEW. */
export const ngHeightTex: { value: THREE.DataTexture } = { value: neutralFallback };
/** Where that texture lies in the world: origin x, origin z, metres per
 *  support point — the three numbers `ngFieldUv` needs. */
export const ngField = { value: new THREE.Vector4(0, 0, 1, 0) };
/** …and how many texels it has: columns, rows. */
export const ngFieldSize = { value: new THREE.Vector2(1, 1) };
/**
 * How much of the height AO is spent — 0 while there is no relief to read.
 *
 * THE NEUTRALITY SWITCH, and it is a uniform rather than a define so that a
 * world whose field arrives late does not recompile a single program. The
 * shader's own guard (`if ( uNgStrength > 0.0 )`) then costs one comparison
 * and reads nothing at all, which is the same promise the corridor makes for
 * an unembodied client.
 */
export const ngStrength = { value: 0 };

/** The texture we own and have to free before replacing it. The neutral one is
 *  never disposed: it is the fallback every future field falls back to. */
let ownedField: THREE.DataTexture | null = null;

/**
 * Take over the world's height overview — called when `height_sig` moves
 * (`scene/ground.ts` `reloadHeight`), and with `null` on teardown.
 *
 * A FLAT WORLD SWITCHES THE STAGE OFF, exactly (the alpha-0 principle of the
 * hillshade): a field whose highest and lowest support point are the same
 * height can only ever produce a shading term of zero, so it produces it once
 * here instead of on every fragment for ever. Same for a field too small to
 * have an interior, and for one that never arrived.
 *
 * The FINE tiles are deliberately not read. They are a 560 m window that
 * follows the player and would re-upload the whole texture whenever it moved;
 * the AO is a broad shading over metres of terrain, and the overview carries
 * exactly that. What the tiles sharpen is where the ground IS — the geometry
 * the player stands on — and that is `ground.ts`'s business, not this one's.
 */
export function setNaturalGroundField(field: WorldHeightField | null): void {
  const rows = field?.rows ?? 0;
  const cols = field?.cols ?? 0;
  const step = field?.step_m ?? 0;
  const heights = field?.heights;
  if (!field || rows < 2 || cols < 2 || !(step > 0) || !Array.isArray(heights)) {
    releaseField();
    return;
  }
  const data = new Uint16Array(rows * cols);
  let min = Infinity;
  let max = -Infinity;
  for (let j = 0; j < rows; j += 1) {
    const row = heights[j];
    for (let i = 0; i < cols; i += 1) {
      // A gap in the payload is FLAT ground, never a NaN: `toHalfFloat` would
      // hand the sampler a quiet NaN and the fragment would come out black.
      const h = Number(row?.[i]);
      const v = Number.isFinite(h) ? h : 0;
      if (v < min) min = v;
      if (v > max) max = v;
      data[j * cols + i] = THREE.DataUtils.toHalfFloat(v);
    }
  }
  if (!(max > min)) {   // a world nobody has shaped — see the doc comment
    releaseField();
    return;
  }
  const tex = makeField(data, cols, rows);
  ownedField?.dispose();
  ownedField = tex;
  ngHeightTex.value = tex;
  ngField.value.set(field.origin_x, field.origin_z, step, 0);
  ngFieldSize.value.set(cols, rows);
  ngStrength.value = 1;
}

/** Back to "no relief": the stage is neutral and the GPU memory is gone. */
function releaseField(): void {
  ownedField?.dispose();
  ownedField = null;
  ngHeightTex.value = neutralFallback;
  ngField.value.set(0, 0, 1, 0);
  ngFieldSize.value.set(1, 1);
  ngStrength.value = 0;
}

/** Materials that already carry the patch. Applying it twice would declare
 *  `vNgWorld` and the noise functions a second time and the shader would not
 *  compile — the guard `patchHole`, `applySway` and `applyOcclusionFade` all
 *  keep, for the same reason. */
const ngPatched = new WeakSet<THREE.Material>();

/** Where the world position is taken. AFTER `project_vertex`, like the hole
 *  and the corridor: the ground is never displaced in the vertex shader today,
 *  and a patch that measured before a future displacement would shade the
 *  ground where it used to be. */
const ANCHOR_VERT = '#include <project_vertex>';
/** …and the colour work goes AFTER the map chunk, because that is the line
 *  that puts the texture into `diffuseColor` — everything here modifies what
 *  the ground already is. */
const ANCHOR_FRAG = '#include <map_fragment>';

/**
 * GLSL literals out of the shared constants — one source for the number the
 * hand check reads and the number the GPU spends (see the math module's
 * header).
 *
 * TWO DECIMALS, AND THE ASSERT IS WHAT MAKES THAT HONEST. `toFixed` rounds
 * silently: a constant of 0.125 would reach the maths as 0.125 and the GPU as
 * 0.13, and the "one number" the whole arrangement rests on would quietly
 * become two. Rather than print more decimals (which reads as noise in a
 * shader) the printer refuses a number it cannot print exactly.
 */
export function ngLit(v: number): string {
  const s = v.toFixed(2);
  if (Number(s) !== v) {
    throw new Error(`naturalGround: ${v} does not survive two decimals as "${s}" — `
      + 'the shader would spend a different number than the maths');
  }
  return s;
}
const lit = ngLit;

/**
 * Every amount that is printed into the shader, checked ONCE AT LOAD.
 *
 * `lit` is called while a material compiles, which is deep inside a frame and
 * on some machines only after a texture has arrived; a constant that cannot be
 * printed exactly has to be a loud failure at startup, not a shader that never
 * comes back. The list is the module's own import list from
 * `naturalGroundMath` — the smoke pins that it stays that.
 */
const NG_PRINTED_AMOUNTS = [NG_AO_DOWN, NG_AO_SPAN_M, NG_AO_UP, NG_DETAIL_OFFSET,
  NG_DETAIL_SCALE, NG_MIX_M, NG_MIX_MAX, NG_TINT_AMP, NG_TINT_M];
for (const v of NG_PRINTED_AMOUNTS) lit(v);

/**
 * Give a ground material the stages.
 *
 * CHAINED, never assigned (see the file header). In `scene/ground.ts` the
 * material arrives with `patchHole` already in the slot, so the combined key
 * reads `ground-hole+natural-ground`.
 *
 * NO ARGUMENTS SINCE E3. The one it had (`edgeFade`) split the program for the
 * alpha fringe of a painted-area drape; there are no drapes any more, the
 * ground is opaque, and every number of the effect is either a GLSL literal or
 * a shared uniform — so every patched ground compiles to ONE program.
 *
 * THE ANTI-TILE STAGE IS GUARDED BY `USE_MAP`, which is what makes the promise
 * "a single-coloured kind gets only the colour patches" true without a second
 * entry point: three defines it exactly when the material carries a texture,
 * and one program serves both cases because three keys the map into its own
 * program parameters already.
 */
export function applyNaturalGround(mat: THREE.Material): void {
  if (ngPatched.has(mat)) return;
  ngPatched.add(mat);
  const prev = mat.onBeforeCompile;
  // three's DEFAULT `customProgramCacheKey` returns `onBeforeCompile.toString()`
  // — only a patch with a key of its OWN is worth carrying. Read here, before
  // the slot below is overwritten.
  const prevKey = Object.prototype.hasOwnProperty.call(mat, 'customProgramCacheKey')
    ? String(mat.customProgramCacheKey())
    : '';
  mat.onBeforeCompile = (shader, renderer) => {
    prev.call(mat, shader, renderer);
    shader.uniforms.uNgHeight = ngHeightTex;
    shader.uniforms.uNgField = ngField;
    shader.uniforms.uNgFieldSize = ngFieldSize;
    shader.uniforms.uNgStrength = ngStrength;
    // A three version without the anchors leaves the material UNPATCHED whole:
    // the fragment side alone would read a varying the vertex side never wrote.
    if (!shader.vertexShader.includes(ANCHOR_VERT)) return;
    if (!shader.fragmentShader.includes(ANCHOR_FRAG)) return;

    // The WORLD position, in two floats: everything below is a plan question
    // (which patch of ground, which hollow), and the height comes out of the
    // field rather than out of the geometry. Beside it, on a DRAPE only, the
    // distance to the area's own ring — measured per vertex when the drape was
    // built, because the ring exists there and nowhere else.
    shader.vertexShader = 'varying vec2 vNgWorld;\n' + shader.vertexShader
      .replace(ANCHOR_VERT, `${ANCHOR_VERT}
\tvNgWorld = ( modelMatrix * vec4( transformed, 1.0 ) ).xz;`);

    // Value noise over WORLD metres: a fract-sin hash on the lattice, smoothly
    // interpolated — the same family the wind draws its phase from
    // (`applySway`), and deliberately NOT a second image. A texture would be a
    // download, a cache entry and a resolution; this is eight instructions and
    // it is the same everywhere in the world, on every client, for ever.
    const head = `
uniform sampler2D uNgHeight;
uniform vec4 uNgField;
uniform vec2 uNgFieldSize;
uniform float uNgStrength;
varying vec2 vNgWorld;
float ngHash( vec2 p ) {
  return fract( sin( dot( p, vec2( 12.9898, 78.233 ) ) ) * 43758.5453 );
}
float ngNoise( vec2 p ) {
  vec2 ngI = floor( p );
  vec2 ngF = fract( p );
  vec2 ngW = ngF * ngF * ( 3.0 - 2.0 * ngF );
  return mix( mix( ngHash( ngI ), ngHash( ngI + vec2( 1.0, 0.0 ) ), ngW.x ),
              mix( ngHash( ngI + vec2( 0.0, 1.0 ) ), ngHash( ngI + vec2( 1.0, 1.0 ) ), ngW.x ),
              ngW.y );
}
/**
 * World point -> texture coordinate of the height field, ONCE.
 *
 * The mapping is ngFieldUv of the maths module, and the '+ 0.5' is the half
 * texel that puts support point i on the CENTRE of texel i. It stands in one
 * function because it is needed twice — the height itself and the test whether
 * the fragment is over the raster at all — and two copies of a half-texel
 * offset are two chances to shift the whole shading by half a support cell.
 */
vec2 ngFieldUvOf( vec2 p ) {
  return ( ( p - uNgField.xy ) / uNgField.z + 0.5 ) / uNgFieldSize;
}
/** The world's height at a plan point, bilinear out of the data texture. */
float ngHeightAt( vec2 p ) {
  return texture2D( uNgHeight, ngFieldUvOf( p ) ).r;
}
`;

    // The ring of the AO, PRINTED from the very list the maths describes it
    // with: tap count, tap offsets and the mean's divisor are one statement in
    // one place. Four hand-written reads and a hand-written 0.25 beside a
    // function that says "four taps" is two statements that can disagree.
    const taps = ngAoTaps();
    const tapReads = taps.map(([dx, dz]) =>
      `ngHeightAt( vNgWorld + vec2( ${lit(dx)}, ${lit(dz)} ) )`)
      .join('\n        + ');

    const body = `
  {
    // (1) ANTI-TILE — the same image at a second, much broader scale, shifted
    //     half a UV so the two never agree, blended by a patchy noise. Only
    //     where there IS an image: a single-coloured kind has no repeat to
    //     break and falls straight through to (2).
    #ifdef USE_MAP
      float ngMix = ngNoise( vNgWorld / ${lit(NG_MIX_M)} ) * ${lit(NG_MIX_MAX)};
      vec4 ngWide = texture2D( map, vMapUv * ${lit(NG_DETAIL_SCALE)} + ${lit(NG_DETAIL_OFFSET)} );
      // Times \`diffuse\`, because that is what the map chunk did to the first
      // sample one line up: a ground that carries a texture AND a tint would
      // otherwise lose the tint exactly where the blend is strongest.
      diffuseColor.rgb = mix( diffuseColor.rgb, ngWide.rgb * diffuse, ngMix );
    #endif
    // (2) COLOUR PATCHES — brightness and saturation over a long wavelength,
    //     drawn from two DECORRELATED readings of the same noise (the offset
    //     is what decorrelates them: one reading would make every bright patch
    //     a colourful one, which reads as a lighting error rather than as
    //     ground). Hue is never touched: the brightness is a scale and the
    //     saturation a mix through the fragment's own luminance.
    float ngTint = ngNoise( vNgWorld / ${lit(NG_TINT_M)} ) * 2.0 - 1.0;
    float ngSat = ngNoise( vNgWorld / ${lit(NG_TINT_M)} + vec2( 37.0, 11.0 ) ) * 2.0 - 1.0;
    diffuseColor.rgb *= 1.0 + ${lit(NG_TINT_AMP)} * ngTint;
    float ngLum = dot( diffuseColor.rgb, vec3( 0.2126, 0.7152, 0.0722 ) );
    diffuseColor.rgb = mix( vec3( ngLum ), diffuseColor.rgb, 1.0 + ${lit(NG_TINT_AMP)} * ngSat );
    // (3) HEIGHT AO — the four taps of the ring against the fragment's own
    //     height. A positive difference means the surroundings stand HIGHER,
    //     i.e. the fragment lies in a hollow, and a hollow is DARKER; turn the
    //     sign around and the ditches light up while the ridges go grey.
    if ( uNgStrength > 0.0 ) {
      float ngOwn = ngHeightAt( vNgWorld );
      float ngAround = ( 1.0 / ${taps.length}.0 ) * (
          ${tapReads} );
      float ngT = clamp( ( ngAround - ngOwn ) / ${lit(NG_AO_SPAN_M)}, -1.0, 1.0 );
      float ngShade = ngT > 0.0 ? -${lit(NG_AO_DOWN)} * ngT : -${lit(NG_AO_UP)} * ngT;
      // Outside the raster the world is the flat border the server pins to 0,
      // and shading it against its own edge would draw a rim around the map.
      vec2 ngUv = ngFieldUvOf( vNgWorld );
      float ngIn = step( 0.0, ngUv.x ) * step( ngUv.x, 1.0 )
                 * step( 0.0, ngUv.y ) * step( ngUv.y, 1.0 );
      diffuseColor.rgb *= 1.0 + ngShade * uNgStrength * ngIn;
    }
    // An albedo above 1 is not a colour, and the brightening of (2) and (3)
    // can reach one on a ground that was already white.
    diffuseColor.rgb = clamp( diffuseColor.rgb, 0.0, 1.0 );
    // THE FOURTH STAGE — the alpha fringe a painted area faded out over — is
    // GONE with E3. A ground boundary is no longer where two transparent
    // meshes overlap but a CUT in the one terrain surface, and how soft it is
    // is the layer's own edge_blend_m acting on the baked signed distance
    // (scene-render layerCut). The noise that kept the border organic survives
    // there, unchanged, pushing the LINE instead of the alpha.
  }
`;
    shader.fragmentShader = head + shader.fragmentShader
      .replace(ANCHOR_FRAG, `${ANCHOR_FRAG}\n${body}`);
  };
  // ONE cache key for every patched ground — see `patchHole`: three keys the
  // compiled program on this string PLUS the material's own defines, and the
  // ground materials differ in maps and colours, not in the patch. The fringe
  // used to be the exception; it is gone, so there is one program again.
  mat.customProgramCacheKey = () => (prevKey
    ? `${prevKey}+${NG_CACHE_KEY}`
    : NG_CACHE_KEY);
}
