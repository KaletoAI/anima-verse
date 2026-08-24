/**
 * THE WATERFALL — a curtain over the edge a river's own line falls over
 * ("Ein Wasser-Gesetz" W5).
 *
 * WHERE IT COMES FROM. Nowhere new: `waterfallsFrom` (`@anima/scene-render`)
 * reads the water's own flow axis (`meta.water_profile.axis`, W4a) and answers
 * which of its segments drops faster than water runs. This file only turns each
 * answer into two meshes — no author places a fall, no payload field carries
 * one, and an area whose axis has no steep segment builds nothing at all. Since
 * W5b that axis carries knots wherever the water level BENDS (the bake samples
 * the drawn line every 2 m and simplifies back), which is why a cliff an author
 * simply drew straight across has a segment to be found on at all.
 *
 * WHY A CURTAIN AND NOT PARTICLES (W5 decision). A fall is a SHEET of water
 * seen from tens of metres away, and a sheet is what the ground itself cannot
 * be at that one place: the water surface is a shading of the terrain (Wasser
 * v2 K-A, `scene/waterShade.ts`), so a five-metre drop over three metres of run
 * is a very steep piece of wet ground and nothing more. One quad with the
 * water's own normal map scrolling down it puts falling water there for two
 * triangles. Particles would need a system, a budget and a per-frame update;
 * the plan parks them, and so does this.
 *
 * WHAT IT REUSES, DELIBERATELY. The wave normal map is not built here — it is
 * THE one procedural map of the process (`surfaceWaveNormal`, `materials.ts`),
 * the very texture the terrain's own water pixels scroll (K-A E4), so a fall
 * carries the same water structure as the river above it and costs no second
 * texture. Until E5 it was read off the water MIRROR's material instead; the
 * mirror is gone and the source moved one step up, to where the map always
 * lived. The clock is `surfaceTimeUniform`, the one the ripple already advances
 * per frame, so this module has NO per-frame work and allocates nothing after
 * the build. And the foam at the foot is the shore's own whitening constant
 * (`WATER_FOAM_STRENGTH`), so broken water is the same white everywhere in the
 * world.
 *
 * LIFETIME. The meshes go into the caller's waterfall list and the materials
 * into its disposal bag, i.e. a fall lives exactly as long as the painted areas
 * it was derived from and dies with them on the next terrain payload
 * (`ground.clearAreas`).
 */
import * as THREE from 'three';
import { surfaceTimeUniform, surfaceWaveNormal } from '@anima/scene-render';
import type { Waterfall } from '@anima/scene-render';
import { WATER_FOAM_STRENGTH } from './waterPlaneMath';

/**
 * How far downstream the sheet leans per metre of fall.
 *
 * A jet leaving the lip at a walking pace is a parabola: it falls `h` metres in
 * `√(2h/g)` seconds and travels `v·√(2h/g)` metres while it does, which for
 * 1.5 m/s over a 5.8 m fall is 1.63 m — 0.28 of the height. A CONSTANT lean
 * rather than that `1/√h`, because the difference over the falls a world holds
 * is a hand's width and one number reads the same everywhere.
 *
 * IT IS ALSO WHAT GETS THE SHEET OUT OF THE HILL. The fall's own point is the
 * MIDDLE of the segment, where the bed sits halfway between top and bottom, so
 * a strictly vertical curtain would have its lower half buried in the slope in
 * front of it. Leaning the top back and the foot forward puts the sheet along
 * the bed instead of through it.
 */
const WATERFALL_LEAN = 0.3;

/**
 * How many metres one tile of the wave normal map spans on the curtain.
 *
 * 2.5 m against the water surface's own 1.6 m (`wave_m`): a falling sheet is
 * stretched by the acceleration that drives it — the water at the foot is faster
 * than the water at the lip, so the structure between them is pulled long. One
 * number rather than a per-fall stretch, because the eye reads the SPEED of a
 * fall off the scroll, not off the crest spacing.
 */
const WATERFALL_WAVE_M = 2.5;

/** Free fall, m/s². The one constant of the drift below. */
const WATERFALL_G = 9.81;

/**
 * How white the sheet already is where it leaves the lip (0…1).
 *
 * Not zero: water going over an edge is aerated before it has fallen at all.
 * It reaches full white at the foot, so the sheet brightens downward, which is
 * what a fall does as it breaks up.
 */
const WATERFALL_WHITE_TOP = 0.35;

/** How much of the sheet is drawn at all (0…1) — the material's own opacity,
 *  before the edge fade and the break-up modulate it. A curtain one can see the
 *  cliff through is a curtain; an opaque one is a wall painted white. */
const WATERFALL_OPACITY = 0.8;

/** The water the sheet is made of, before it whitens: the pale blue of aerated
 *  water rather than the surface's own tint, which is a REFLECTION colour and
 *  belongs to a surface seen from above. */
const WATERFALL_TINT = 0xc2dcea;

/**
 * How far the foam at the foot reaches, in metres of radius per metre of fall.
 *
 * Half a metre per metre — a 6 m fall throws white water about 3 m out into its
 * pool. Never narrower than the stream itself, or the foam would sit inside a
 * river wider than its own fall (`foamRadius` below).
 */
const WATERFALL_FOAM_RADIUS_PER_M = 0.5;

/** How far the foam disc floats over the water it lies on, in metres. The water
 *  is the ground surface itself now, so this IS a z-fight fix as well as a
 *  stacking one: 5 cm is the same hand's width the shore's own rim fade spends
 *  (`WATER_EDGE_FADE_M`) and is invisible at any camera distance. */
const WATERFALL_FOAM_LIFT_M = 0.05;

/** How many segments the foam disc is drawn with. It is a soft white blob under
 *  a moving sheet; 24 is round enough that nobody counts corners, and it is
 *  ONE disc per fall, of which a world holds a handful. */
const WATERFALL_FOAM_SEGMENTS = 24;

/** The cache key of the curtain patch — every curtain material carries the same
 *  source, so three compiles ONE program for all the falls in a world. */
const WATERFALL_CACHE_KEY = 'waterfall-curtain';

/**
 * The mean speed of the falling water, in metres per second.
 *
 * A body dropped from rest covers `h` in `√(2h/g)` seconds, so its AVERAGE
 * speed over the fall is `h / √(2h/g) = √(gh/2)` — 5.3 m/s over a 5.8 m fall,
 * 3.1 m/s over a 2 m one. The scroll is the sheet's own speed and not a taste
 * number, which is what makes a tall fall visibly faster than a short one
 * without a second dial.
 */
function fallSpeedMs(heightM: number): number {
  return Math.sqrt(WATERFALL_G * Math.max(heightM, 0) * 0.5);
}

/** How wide the white water at the foot reaches, in metres of radius. */
function foamRadius(fall: Waterfall, heightM: number): number {
  return Math.max(fall.width * 0.5,
                  WATERFALL_FOAM_RADIUS_PER_M * heightM);
}

/**
 * Give a curtain material its scroll — ONE insertion, at `#include
 * <map_fragment>`.
 *
 * That anchor is where a basic material would have multiplied its texture into
 * `diffuseColor`; replacing it means the map is sampled HERE, at coordinates of
 * our own, and `diffuseColor.rgb`/`.a` are both still writable. The uv is a
 * varying of our own too rather than three's `vMapUv`: a name out of the
 * library's chunks is a name that moves between versions, and this one is two
 * lines.
 *
 * THE SCROLL IS AN ADDITION TO A SAMPLE COORDINATE, which slides the picture
 * the OTHER way — `uv + vec2(0, t)` carries the crests toward SMALLER v, and v
 * is 0 at the foot. That is the downward drift, and it is the same sign trick
 * the terrain's own water ripple documents (`materials.ts`, "wFlowSign").
 *
 * TWO LAYERS, at different scales and rates, for the reason the lake has two:
 * one sheet of a tiling map reads as a tiling map. The second is half the
 * frequency and 0.6 of the rate, so the beat between them never repeats within
 * a fall's height.
 */
function patchCurtain(mat: THREE.Material, speedTilesS: number,
                      tilesX: number, tilesY: number): void {
  const uSpeed = { value: speedTilesS };
  const uTiles = { value: new THREE.Vector2(tilesX, tilesY) };
  mat.onBeforeCompile = (shader) => {
    shader.uniforms.uTime = surfaceTimeUniform;
    shader.uniforms.uWfSpeed = uSpeed;
    shader.uniforms.uWfTiles = uTiles;
    if (!shader.vertexShader.includes('#include <begin_vertex>')
        || !shader.fragmentShader.includes('#include <map_fragment>')) return;
    shader.vertexShader = 'varying vec2 vWfUv;\n'
      + shader.vertexShader.replace('#include <begin_vertex>',
        '#include <begin_vertex>\n\tvWfUv = uv;');
    shader.fragmentShader = 'varying vec2 vWfUv;\nuniform float uTime;\n'
      + 'uniform float uWfSpeed;\nuniform vec2 uWfTiles;\n'
      + shader.fragmentShader.replace('#include <map_fragment>', `
  {
    vec2 wfUv = vWfUv * uWfTiles;
    float wfT = uTime * uWfSpeed;
    // The map is a NORMAL map: its xy is the slope of the water's surface, so
    // a large |xy| is a steep crest — which is exactly where a falling sheet
    // tears open and goes white.
    vec2 wfA = ( texture2D( map, wfUv + vec2( 0.0, wfT ) ).xy * 2.0 - 1.0 );
    vec2 wfB = ( texture2D( map, wfUv * 0.5 + vec2( 0.17, wfT * 0.6 ) ).xy
                 * 2.0 - 1.0 );
    float wfBreak = clamp( ( abs( wfA.x + wfB.x ) + abs( wfA.y + wfB.y ) )
                           * 1.6, 0.0, 1.0 );
    // …and it is whiter the further it has fallen: vWfUv.y is 1 at the lip.
    float wfDown = 1.0 - vWfUv.y;
    float wfWhite = clamp( ${WATERFALL_WHITE_TOP}
                           + ( 1.0 - ${WATERFALL_WHITE_TOP} ) * wfDown * 0.7
                           + wfBreak * 0.4, 0.0, 1.0 );
    diffuseColor.rgb = mix( diffuseColor.rgb, vec3( 1.0 ), wfWhite );
    // A sheet with two hard vertical borders is a poster of a waterfall: the
    // outer eighth of the width fades, and so does the last of the lip, where
    // the ground above is still shaded as the same water.
    // (Both edge pairs ASCENDING: smoothstep with edge0 >= edge1 is undefined
    // in GLSL, so the lip fade is written as one minus the rising ramp.)
    float wfEdge = smoothstep( 0.0, 0.12, vWfUv.x )
                 * smoothstep( 0.0, 0.12, 1.0 - vWfUv.x )
                 * ( 1.0 - smoothstep( 0.94, 1.0, vWfUv.y ) );
    diffuseColor.a *= wfEdge * ( 0.6 + 0.4 * wfBreak );
  }
`);
  };
  mat.customProgramCacheKey = () => WATERFALL_CACHE_KEY;
}

/**
 * The two meshes of ONE fall: the curtain and the white water at its foot.
 *
 * `sink` takes the two materials this builds; the geometries belong to the
 * returned meshes and are freed by whoever disposes them (`ground.clearAreas`
 * does, with the areas the falls were derived from).
 *
 * THE GEOMETRY IS FOUR VERTICES IN WORLD COORDINATES, mesh at the origin —
 * for the reason every water height here is absolute: the levels in the payload
 * are, and a mesh position under them would be a second place a height could be
 * wrong. `across` is the horizontal perpendicular of the flow, so the strip
 * spans the river; the lean puts the lip edge upstream of the fall's point and
 * the foot downstream of it.
 *
 * An empty list comes back for a fall of no height — the detection cannot
 * produce one (it needs a drop over a metre), so this only ever fires on a
 * hand-made call.
 */
export function buildWaterfall(fall: Waterfall,
                               sink: { dispose(): void }[]): THREE.Mesh[] {
  const height = fall.topY - fall.bottomY;
  if (!(height > 0) || !(fall.width > 0)) return [];
  // THE one wave normal map of the process, built on first ask and shared with
  // every water pixel the terrain shades (K-A E4).
  const map = surfaceWaveNormal(THREE) as THREE.Texture;

  // ── the curtain ──────────────────────────────────────────────────────────
  const acrossX = fall.dirZ;
  const acrossZ = -fall.dirX;
  const halfW = fall.width * 0.5;
  const lean = WATERFALL_LEAN * height * 0.5;
  const topX = fall.x - fall.dirX * lean;
  const topZ = fall.z - fall.dirZ * lean;
  const botX = fall.x + fall.dirX * lean;
  const botZ = fall.z + fall.dirZ * lean;
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array([
    topX - acrossX * halfW, fall.topY, topZ - acrossZ * halfW,
    topX + acrossX * halfW, fall.topY, topZ + acrossZ * halfW,
    botX - acrossX * halfW, fall.bottomY, botZ - acrossZ * halfW,
    botX + acrossX * halfW, fall.bottomY, botZ + acrossZ * halfW,
  ]), 3));
  // u across the stream, v from the pool (0) up to the lip (1) — the shader
  // reads both, and the drift is in v.
  geo.setAttribute('uv', new THREE.BufferAttribute(new Float32Array([
    0, 1, 1, 1, 0, 0, 1, 0,
  ]), 2));
  geo.setIndex([0, 2, 1, 2, 3, 1]);
  geo.computeBoundingSphere();
  const curtainMat = new THREE.MeshBasicMaterial({
    map,
    color: WATERFALL_TINT,
    transparent: true,
    opacity: WATERFALL_OPACITY,
    // A sheet of water is seen from both banks and from behind the fall.
    side: THREE.DoubleSide,
    // The world behind a curtain of water stays visible, and
    // nothing sorts itself against a thing that writes no depth.
    depthWrite: false,
  });
  // The sheet's own drift: the mean speed of the falling water, in tiles of the
  // wave map per second.
  patchCurtain(curtainMat, fallSpeedMs(height) / WATERFALL_WAVE_M,
               fall.width / WATERFALL_WAVE_M, height / WATERFALL_WAVE_M);
  sink.push(curtainMat);
  const curtain = new THREE.Mesh(geo, curtainMat);
  // A curtain of water neither casts nor takes a shadow — it is drawn from its
  // own whitening, and a shadow on falling water is a shadow on nothing.
  curtain.receiveShadow = false;
  curtain.castShadow = false;

  // ── the white water at the foot ──────────────────────────────────────────
  // A disc, alpha at its centre and nothing at its rim — the radial fade is in
  // the VERTEX COLOURS (a four-component colour attribute carries alpha), so
  // the foam needs no texture and no second shader patch. `CircleGeometry`
  // puts the centre first and the rim after it, which is exactly that fade.
  const radius = foamRadius(fall, height);
  const disc = new THREE.CircleGeometry(radius, WATERFALL_FOAM_SEGMENTS);
  disc.rotateX(-Math.PI / 2);
  const count = disc.getAttribute('position').count;
  const colors = new Float32Array(count * 4);
  for (let i = 0; i < count; i += 1) {
    colors[i * 4] = 1;
    colors[i * 4 + 1] = 1;
    colors[i * 4 + 2] = 1;
    colors[i * 4 + 3] = i === 0 ? WATER_FOAM_STRENGTH : 0;
  }
  disc.setAttribute('color', new THREE.BufferAttribute(colors, 4));
  disc.translate(botX, fall.bottomY + WATERFALL_FOAM_LIFT_M, botZ);
  disc.computeBoundingSphere();
  const foamMat = new THREE.MeshBasicMaterial({
    color: 0xffffff,
    vertexColors: true,
    transparent: true,
    depthWrite: false,
  });
  sink.push(foamMat);
  const foam = new THREE.Mesh(disc, foamMat);
  foam.receiveShadow = false;
  foam.castShadow = false;

  return [curtain, foam];
}
