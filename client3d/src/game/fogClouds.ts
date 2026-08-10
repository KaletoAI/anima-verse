/**
 * The LOOK of the fog of war — a cloud cover, not a lid.
 *
 * `game/fog.ts` says WHICH part of the world plane is unknown and cuts it into
 * rectangles; it stays pure and knows nothing about rendering. This module is
 * the other half: it makes the one material and the one texture those
 * rectangles are drawn with, so `main.ts` only has to place quads. Splitting it
 * this way keeps the maths checkable by `client3d/scripts/smoke_walk_math.mjs` (no
 * `three`, no DOM) while the pixels live somewhere they can be read on their
 * own.
 *
 * WHY IT LOOKS LIKE THIS. The first version was a flat dark quad per rectangle
 * and read as what it was: empty boxes laid over the map. Weather is the
 * picture everybody already understands for "you cannot see what is under
 * there", so the veil is an overcast layer:
 *
 * - ONE procedural fBm cloud texture (256², tileable in both directions),
 *   sampled in WORLD coordinates. World-space UVs are the reason the cover has
 *   no seams: neighbouring quads of different sizes continue the same pattern
 *   instead of each restarting it at their own corner.
 * - Soft, ragged edges. Each quad is drawn `FOG_OVERHANG_M` metres larger than
 *   its rectangle on every side, and the alpha ramps up across exactly that
 *   margin, bitten into by the same noise so the border is a lobed cloud edge
 *   and not a straight line.
 * - OPAQUE inside. `FOG_FEATHER_M + FOG_RAGGED_M === FOG_OVERHANG_M` is the
 *   load-bearing identity: alpha reaches 1 at the true rectangle border in the
 *   worst case of the bite, so where two rectangles meet BOTH are fully opaque
 *   and the overdraw can never open a translucent seam through the interior.
 *   Nothing under the cover is ever visible.
 * - Slow drift and a night tint, both driven from the caller's frame loop —
 *   this module owns no timer.
 *
 * `MeshBasicMaterial` + `onBeforeCompile` rather than a `ShaderMaterial` on
 * purpose: the veil is unlit, and patching the stock material inherits scene
 * fog, tone mapping and the output colour space instead of re-deriving three
 * things that are easy to get subtly wrong.
 */
import * as THREE from 'three';
// The four numbers this module is built from live in the PURE half (E4 task
// 6): they used to be multiples of the grid cell, they are absolute metres
// now, and `game/fog.ts` is the only place a smoke can read them — this file
// needs `three` and a canvas and can never be loaded without a browser.
import { FOG_FEATHER_M, FOG_OVERHANG_M, FOG_RAGGED_M, FOG_TEX_METRES } from './fog';
import { seededRandom } from '../scene/textures';

/** Drift in metres per second (world x / z). A cloud shadow crossing ten
 *  metres takes half a minute — movement one notices only by looking twice. */
const DRIFT_X = 0.28;
const DRIFT_Z = 0.11;

/** The cover as `main.ts` uses it: one material, one geometry factory, one
 *  per-frame nudge. */
export interface FogClouds {
  /** Shared by every quad — one material, one program, one draw state. */
  material: THREE.Material;
  /** A flat quad for a rectangle of `widthM` × `depthM` metres, already
   *  enlarged by the overhang, lying in the XZ plane and carrying the extents
   *  the edge fade needs. */
  quadGeometry(widthM: number, depthM: number): THREE.BufferGeometry;
  /** Advance the drift and take the night factor over. Call once per frame
   *  from the existing render loop. */
  advance(dt: number, night: number): void;
  dispose(): void;
}

export function createFogClouds(): FogClouds {
  const tex = cloudTexture(256);
  const uniforms = {
    uDrift: { value: new THREE.Vector2(0, 0) },
    uInvScale: { value: 1 / FOG_TEX_METRES },
    uFeather: { value: FOG_FEATHER_M },
    uRagged: { value: FOG_RAGGED_M },
    uNight: { value: 0 },
  };

  const material = new THREE.MeshBasicMaterial({
    map: tex, transparent: true, depthWrite: false,
  });
  material.onBeforeCompile = (shader) => {
    Object.assign(shader.uniforms, uniforms);
    // `vMapUv` is declared by <uv_pars_vertex> because the material has a map;
    // overwriting it right after <uv_vertex> is what turns the per-quad UVs
    // into world-space ones. `aHalf` carries the quad's half extents — the
    // same value on all four corners, so the fragment stage gets them as a
    // constant and can measure its distance to the border.
    shader.vertexShader = `
      attribute vec2 aHalf;
      uniform vec2 uDrift;
      uniform float uInvScale;
      varying vec2 vLocal;
      varying vec2 vHalf;
    ` + shader.vertexShader.replace('#include <uv_vertex>', `
      #include <uv_vertex>
      vLocal = position.xz;
      vHalf = aHalf;
      vMapUv = ( modelMatrix * vec4( position, 1.0 ) ).xz * uInvScale + uDrift;
    `);
    shader.fragmentShader = `
      uniform float uFeather;
      uniform float uRagged;
      uniform float uNight;
      varying vec2 vLocal;
      varying vec2 vHalf;
    ` + shader.fragmentShader.replace('#include <map_fragment>', `
      #include <map_fragment>
      // A second, much wider sample of the same texture. One octave of a
      // 256px tile alone shows its repeat from a high camera; blending in a
      // sample three times the size breaks the grid without a second texture.
      vec3 wide = texture2D( map, vMapUv * 0.31 + vec2( 0.57, 0.23 ) ).rgb;
      diffuseColor.rgb = mix( diffuseColor.rgb, wide, 0.40 );
      // Distance to the (enlarged) border, minus a noise bite out of the
      // margin: a lobed edge instead of a straight one.
      float edge = min( vHalf.x - abs( vLocal.x ), vHalf.y - abs( vLocal.y ) );
      float bite = texture2D( map, vMapUv * 0.6 + vec2( 0.13, 0.41 ) ).g;
      diffuseColor.a *= smoothstep( 0.0, uFeather, edge - uRagged * bite );
      // Night: clouds go slate, they do not go black — the cover must stay
      // readable as weather after sundown and not fall back to a dark box.
      diffuseColor.rgb = mix( diffuseColor.rgb,
                              diffuseColor.rgb * vec3( 0.34, 0.38, 0.50 ),
                              uNight * 0.75 );
    `);
  };

  return {
    material,
    quadGeometry(widthM: number, depthM: number) {
      const hw = widthM / 2 + FOG_OVERHANG_M;
      const hh = depthM / 2 + FOG_OVERHANG_M;
      const geo = new THREE.PlaneGeometry(hw * 2, hh * 2).rotateX(-Math.PI / 2);
      geo.setAttribute('aHalf', new THREE.BufferAttribute(
        new Float32Array([hw, hh, hw, hh, hw, hh, hw, hh]), 2));
      return geo;
    },
    advance(dt: number, night: number) {
      // Wrapped into [0,1): the offset runs for as long as the session does,
      // and a float that grows without bound loses its fractional precision.
      const d = uniforms.uDrift.value;
      d.x = (d.x + (dt * DRIFT_X) / FOG_TEX_METRES) % 1;
      d.y = (d.y + (dt * DRIFT_Z) / FOG_TEX_METRES) % 1;
      uniforms.uNight.value = night;
    },
    dispose() {
      material.dispose();
      tex.dispose();
    },
  };
}

/**
 * The cloud texture: fractal value noise, seamless in both directions.
 *
 * Tileable because every octave is a lattice of `freq` × `freq` values whose
 * indices are taken modulo `freq` — the right edge interpolates back into the
 * left one, so the pattern continues across quad borders as well as across its
 * own. `freq` doubles per octave and always divides 256, which is what keeps
 * the lattice aligned to whole pixels.
 */
function cloudTexture(size: number): THREE.CanvasTexture {
  const field = new Float32Array(size * size);
  let amp = 1;
  let sum = 0;
  for (let freq = 4; freq <= 64; freq *= 2) {
    const octave = valueNoise(size, freq, seededRandom(`fogcloud-${freq}`));
    for (let i = 0; i < field.length; i++) field[i] += octave[i] * amp;
    sum += amp;
    amp *= 0.5;
  }

  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext('2d')!;
  const img = ctx.createImageData(size, size);
  for (let i = 0; i < field.length; i++) {
    // The contrast curve is what makes lobes out of a smooth field: below the
    // lower edge everything is shadow, above the upper one everything is lit
    // top, and only the band between them is gradient.
    const n = smoothstep(0.34, 0.72, field[i] / sum);
    const p = i * 4;
    // Shadowed grey-blue #9aa2b0 up to a lit white #ffffff. Each channel ends
    // exactly at 255: an unequal ceiling would tint the brightest tops.
    img.data[p] = 154 + n * 101;
    img.data[p + 1] = 162 + n * 93;
    img.data[p + 2] = 176 + n * 79;
    img.data[p + 3] = 255;             // the cover's own alpha is the shader's
  }
  ctx.putImageData(img, 0, 0);

  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
  tex.anisotropy = 4;
  return tex;
}

/** One octave: a `freq` × `freq` lattice of random values, bilinearly
 *  interpolated to `size` × `size` with wrap-around indices. */
function valueNoise(size: number, freq: number, rnd: () => number): Float32Array {
  const lattice = new Float32Array(freq * freq);
  for (let i = 0; i < lattice.length; i++) lattice[i] = rnd();
  const out = new Float32Array(size * size);
  const step = freq / size;
  for (let y = 0; y < size; y++) {
    const fy = y * step;
    const y0 = Math.floor(fy);
    const ty = fade(fy - y0);
    const rowA = (y0 % freq) * freq;
    const rowB = ((y0 + 1) % freq) * freq;
    for (let x = 0; x < size; x++) {
      const fx = x * step;
      const x0 = Math.floor(fx);
      const tx = fade(fx - x0);
      const xa = x0 % freq;
      const xb = (x0 + 1) % freq;
      const top = mix(lattice[rowA + xa], lattice[rowA + xb], tx);
      const bot = mix(lattice[rowB + xa], lattice[rowB + xb], tx);
      out[y * size + x] = mix(top, bot, ty);
    }
  }
  return out;
}

/** Smooth Hermite ramp — the classic `3t² - 2t³`, so lattice corners do not
 *  show up as creases. */
function fade(t: number): number { return t * t * (3 - 2 * t); }
function mix(a: number, b: number, t: number): number { return a + (b - a) * t; }
function smoothstep(edge0: number, edge1: number, x: number): number {
  const t = Math.min(1, Math.max(0, (x - edge0) / (edge1 - edge0)));
  return fade(t);
}
