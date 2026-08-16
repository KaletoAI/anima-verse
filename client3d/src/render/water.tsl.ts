/**
 * Water/ice surface as a TSL node material — the WebGPU port of
 * `applyWaterShader` (packages/scene-render/src/materials.ts). Same
 * parameters, same numbers, same shared clock; the GLSL anchors become node
 * slots:
 *
 *   begin_vertex          -> positionWorld.xz / uv()   (varyings are implicit)
 *   normal_fragment_maps  -> normalNode    (two scrolling layers, masked)
 *   map_fragment          -> colorNode     (tint mix, masked)
 *   roughnessmap_fragment -> roughnessNode (roughness floor, masked)
 *   opaque_fragment       -> setupOutput() override — fresnel towards the sky
 *                            on the LIT colour, BEFORE fog and colour space,
 *                            alpha untouched (the documented extension point
 *                            of NodeMaterial; `outputNode` would sit AFTER fog)
 *
 * The shared package stays renderer-neutral (its GLSL patch keeps serving the
 * WebGL client and the admin previews); this file is client-only. The WebGPU
 * renderer never calls `onBeforeCompile`, so a classic water material would
 * render matte there — this class is what the factory switch in
 * `render/surface.ts` hands out instead.
 *
 * Research notes (three 0.185.1): `normalMap(node, scale)` expects the RAW
 * 0..1 sample and unpacks (`*2-1`) itself, so the blended tangent normal goes
 * back to 0..1 before it; without a `tangent` attribute three builds the TBN
 * from screen derivatives (`tangentViewFrame`) — the same frame the GLSL
 * `tbn` had. `materialColor` already contains `map`, `materialRoughness` the
 * roughness map. `time` of three would tick on its own; the port reads the
 * package clock instead so WebGL water, WebGPU water and the grass sway agree.
 */
import * as THREE from 'three';
import { MeshStandardNodeMaterial, type Node, type NodeBuilder } from 'three/webgpu';
import { clamp, dot, float, materialColor, materialRoughness, mix, normalMap,
         positionViewDirection, positionWorld, renderGroup, texture, transformedNormalView,
         uniform, uv, vec2, vec3, vec4 } from 'three/tsl';
import { surfaceTimeUniform, type SurfaceMaterialSpec } from '@anima/scene-render';

/** Wavelength of the second, counter-drifting layer relative to the first
 *  (materials.ts: `uWaveM * 0.63`). */
export const WATER_LAYER_B = 0.63;

/** ONE clock for every water surface — fed from the same object the WebGL
 *  water and the grass sway read, so both renderers agree on "now". Updated
 *  once per render pass by three (`renderGroup`), not per material. */
export const waterTime = uniform(0).setGroup(renderGroup).onRenderUpdate(() => tickWaterTime());

/** Copy the package clock into the node uniform; returns the value. */
export function tickWaterTime(): number {
  waterTime.value = surfaceTimeUniform.value;
  return waterTime.value;
}

/** Sky colour for the fresnel share — the TSL twin of `setSurfaceSky`. */
const uSky = uniform(new THREE.Color(0.62, 0.78, 0.91)).setGroup(renderGroup);
export function setWaterSky(hex: number): void {
  uSky.value.setHex(hex);
}

export interface WaterUniforms {
  uWaveM: { value: number };
  uSpeed: { value: number };
  uSkyMix: { value: number };
  uMapStrength: { value: number };
  uTint: { value: THREE.Color };
}

export interface WaterOptions {
  map?: THREE.Texture | null;
  color?: THREE.Color;
  /** tile mask (red = water share); missing = water everywhere */
  mask?: THREE.Texture | null;
  transparent?: boolean;
  opacity?: number;
  side?: THREE.Side;
  /** the shared procedural wave normal map */
  normalMap: THREE.Texture;
}

let white: THREE.DataTexture | null = null;
/** 1×1 white: without a mask the class holds everywhere — a stand-in texture
 *  instead of a second shader branch (same rule as the GLSL patch). */
function whiteMask(): THREE.Texture {
  if (!white) {
    white = new THREE.DataTexture(new Uint8Array([255, 255, 255, 255]), 1, 1);
    white.needsUpdate = true;
  }
  return white;
}

export class WaterNodeMaterial extends MeshStandardNodeMaterial {
  readonly isWaterNodeMaterial = true;
  readonly waterUniforms: WaterUniforms;
  private readonly maskR: Node<'float'>;
  private readonly uSkyMixNode: Node<'float'>;

  constructor(spec: SurfaceMaterialSpec, opts: WaterOptions) {
    super();
    const uWaveM = uniform(Math.max(spec.wave_m ?? 1.6, 0.05));
    const uSpeed = uniform(spec.speed ?? 0.05);
    const uSkyMix = uniform(spec.sky_mix ?? 0.55);
    const uMapStrength = uniform(spec.map_strength ?? 0.75);
    const uTint = uniform(new THREE.Color(spec.tint ?? '#3f7fb8'));
    this.waterUniforms = { uWaveM, uSpeed, uSkyMix, uMapStrength, uTint };
    this.uSkyMixNode = uSkyMix;

    // the classic parameters of `surfaceMaterial` for a rippled class
    this.roughness = spec.roughness ?? 0.08;
    this.metalness = spec.metalness ?? 0.15;
    if (opts.map) this.map = opts.map;
    else this.color.copy(opts.color ?? uTint.value);
    if (opts.transparent) this.transparent = true;
    if (opts.opacity !== undefined) this.opacity = opts.opacity;
    if (opts.side !== undefined) this.side = opts.side;
    this.normalMap = opts.normalMap;
    this.normalScale = new THREE.Vector2(1, 1);

    // Mask: red channel at the TILE uv (the mask belongs to this one tile);
    // the ripple runs over WORLD xz (crossing tile seams without a visible
    // joint) — two different things, as in the GLSL patch.
    const maskR = texture(opts.mask ?? whiteMask(), uv()).r;
    this.maskR = maskR;
    const world = positionWorld.xz;
    // uSpeed is metres per second: the drift is divided by the wavelength of
    // the RESPECTIVE layer, so both layers drift equally fast.
    const driftA = waterTime.mul(uSpeed).div(uWaveM);
    const waveB = uWaveM.mul(WATER_LAYER_B);
    const driftB = waterTime.mul(uSpeed).div(waveB);
    const uvA = world.div(uWaveM).add(vec2(driftA, driftA.mul(0.6)));
    const uvB = world.div(waveB).sub(vec2(driftB.mul(0.8), driftB.mul(1.3)));
    const nA = texture(opts.normalMap, uvA).xyz.mul(2).sub(1);
    const nB = texture(opts.normalMap, uvB).xyz.mul(2).sub(1);
    const wN = mix(vec3(0, 0, 1), nA.add(nB).normalize(), maskR);
    // `normalMap()` unpacks 0..1 -> -1..1 itself, so hand the blend back in
    // 0..1; the scale is the material's normalScale, as three wires it.
    this.normalNode = normalMap(wN.mul(0.5).add(0.5), uniform(this.normalScale));

    // Texture against the base tone — a generated water texture with baked
    // highlights must not compete with the shader; outside the mask untouched.
    this.colorNode = mix(uTint, materialColor, mix(float(1), uMapStrength, maskR));
    // Roughness only lowered inside the water share — the sand strip of a
    // coast must not shine like wet glass.
    this.roughnessNode = mix(float(0.85), materialRoughness, maskR);
  }

  /** Fresnel towards the sky colour on the LIT colour, alpha untouched — the
   *  place of `opaque_fragment`: before fog and before the colour-space output
   *  that `super.setupOutput` applies. */
  setupOutput(builder: NodeBuilder, outputNode: Node): Node {
    // NodeMaterial always hands a vec4 in here (`vec4(outgoingLight, alpha)`);
    // the base signature is just untyped.
    const out = outputNode as Node<'vec4'>;
    const facing = clamp(dot(positionViewDirection, transformedNormalView), 0, 1);
    const fres = float(1).sub(facing).pow(3);
    const k = clamp(fres.mul(this.uSkyMixNode), 0, 1).mul(this.maskR);
    const rgb = mix(out.rgb, uSky, k);
    return super.setupOutput(builder, vec4(rgb, out.a));
  }
}

/** The water/ice material for a spec — refuses every other class loudly, the
 *  factory (`render/surface.ts`) decides who comes here. */
export function waterNodeMaterial(spec: SurfaceMaterialSpec, opts: WaterOptions): WaterNodeMaterial {
  if (spec.class !== 'water' && spec.class !== 'ice') {
    throw new Error(`waterNodeMaterial: class "${spec.class}" is not a rippled surface`);
  }
  return new WaterNodeMaterial(spec, opts);
}

export function isWaterNodeMaterial(m: THREE.Material): m is WaterNodeMaterial {
  return (m as { isWaterNodeMaterial?: boolean }).isWaterNodeMaterial === true;
}
