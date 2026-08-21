/**
 * Pure arithmetic of the NATURAL GROUND — the numbers the shader patch of
 * `scene/naturalGround.ts` is built from, and the only half of it that can be
 * checked without a GPU.
 *
 * Everything here is a function of its arguments: no Three.js, no module
 * state, no DOM — the discipline of `scene/scatterLod.ts`, and what lets
 * `client3d/scripts/smoke_natural_ground.mjs` transpile this file and pin it
 * with hand-derived numbers. It must stay IMPORT-FREE.
 *
 * IT IS ALSO THE SINGLE SOURCE OF THE GLSL CONSTANTS. `naturalGround.ts`
 * prints its shader out of the very constants below, so a hand check on the
 * function and a string check on the composed shader measure ONE number — a
 * mutant that turns the AO around here turns it around in the shader too.
 * That is the whole reason the amplitudes do not live beside the GLSL that
 * spends them.
 *
 * WHAT THE GROUND GETS, in the order the fragment applies it:
 *  (1) ANTI-TILE — the ground texture sampled a second time at a much broader
 *      scale and shifted half a UV, blended by value noise. One texture, two
 *      scales: the eye stops finding the repeat because there is no single
 *      period left to find.
 *  (2) COLOUR PATCHES — a slow, large modulation of brightness and saturation
 *      (never of hue: a green meadow with blue patches is a bug, not weather).
 *      This is the ONE stage a single-coloured kind gets as well, and the
 *      reason it is separate from (1).
 *  (3) HEIGHT AO — a fragment lying lower than its surroundings darkens, one
 *      lying higher brightens a little. It reads the world's own heightfield,
 *      so a flat world is neutral by arithmetic and not by a switch.
 *
 * THERE WAS A FOURTH STAGE and it is worth naming: a painted area used to fade
 * out over the last metre and a half of itself, which is what made every one of
 * them a transparent mesh. It is gone with E3 — a ground boundary is a CUT in
 * the one terrain surface now, and its width is the layer's own `edge_blend_m`
 * (`@anima/scene-render` `layerCut.ts`). See the note where it used to stand.
 *
 * NO SLIDERS. These are numbers of the VIEW, like the corridor's
 * (`scene/occlusion.ts`) and the wind's — a world that ships a knob for the
 * blend weight of its ground texture has a knob nobody can judge.
 */

// ── (1) Anti-tile ───────────────────────────────────────────────────────────

/** Scale of the SECOND sample, as a factor on the first one's UV. 0.23 makes
 *  its features roughly 4.3 times as wide, which is far enough from 1 that the
 *  two periods share no visible common multiple — the point of the whole
 *  exercise. Anything nearer 1 beats against the base sample instead of
 *  breaking it up. */
export const NG_DETAIL_SCALE = 0.23;
/** …and shifted half a UV unit, so the two samples never show the same texel
 *  of the source image at the same place. Without the shift both samples agree
 *  exactly at the origin of every tile and the repeat survives the blend. */
export const NG_DETAIL_OFFSET = 0.5;
/** Wavelength of the noise that blends the two samples, in world metres. A
 *  patch of ground the size of a small clearing: short enough that a single
 *  screen shows several of them, long enough not to read as dirt. */
export const NG_MIX_M = 7;
/** How much of the broad sample the blend may reach — HALF, never all of it.
 *  The base sample is the ground the world was authored with; the second one
 *  breaks its rhythm and must not replace it. */
export const NG_MIX_MAX = 0.5;

/** The UV of the second sample. Trivial arithmetic, kept here because the two
 *  constants above are what a reader wants pinned by a number rather than by
 *  reading a shader string. */
export function ngDetailUv(u: number, v: number): [number, number] {
  return [u * NG_DETAIL_SCALE + NG_DETAIL_OFFSET,
          v * NG_DETAIL_SCALE + NG_DETAIL_OFFSET];
}

// ── (2) Colour patches ──────────────────────────────────────────────────────

/** Wavelength of the colour modulation, in world metres — a walk of half a
 *  minute crosses one patch. Deliberately far longer than the anti-tile noise:
 *  the two stages must not share a rhythm, or the ground would breathe. */
export const NG_TINT_M = 25;
/** How far brightness and saturation swing, as a share of the value they
 *  modulate. ±8 % is a ground that has weather; ±20 % is a ground somebody
 *  spilled something on. */
export const NG_TINT_AMP = 0.08;

/** The two factors of the colour stage for a pair of noise readings in 0..1.
 *
 *  Both are multipliers around 1: `brightness` scales the albedo, `saturation`
 *  is the mix weight AWAY from the fragment's own luminance (1 = untouched,
 *  >1 = more colourful). Neither touches hue, which is what keeps a meadow
 *  green in every patch of it. */
export function ngTintFactors(nBright: number, nSat: number
): { brightness: number; saturation: number } {
  return {
    brightness: 1 + NG_TINT_AMP * (nBright * 2 - 1),
    saturation: 1 + NG_TINT_AMP * (nSat * 2 - 1),
  };
}

// ── (3) Height AO ───────────────────────────────────────────────────────────

/** Radius of the ring the surroundings are read at, in world metres. Three
 *  metres is a step or four: near enough that a hollow a figure stands in is
 *  really measured, far enough that the tap does not simply read the
 *  fragment's own cell back. */
export const NG_AO_RING_M = 3;
/** The height difference at which the shading is fully spent, in metres. A
 *  two-metre dip is a hollow; anything deeper is a valley and gets no more
 *  than the hollow does. */
export const NG_AO_SPAN_M = 2;
/** How far down a fragment BELOW its surroundings goes, as a share of its
 *  albedo. */
export const NG_AO_DOWN = 0.12;
/** …and how far up one ABOVE them goes. Half the darkening on purpose: a rim
 *  catching light is a hint, a rim glowing is a bug. */
export const NG_AO_UP = 0.06;

/** Where the four taps sit, relative to the fragment, in world metres. Four
 *  and not eight: this is a shading hint, not an ambient-occlusion solver, and
 *  every tap is a texture fetch on every ground fragment on screen. */
export function ngAoTaps(ringM: number = NG_AO_RING_M): [number, number][] {
  return [[ringM, 0], [-ringM, 0], [0, ringM], [0, -ringM]];
}

/**
 * The AO term for one fragment: what its albedo is multiplied by, minus one.
 *
 * `ringMean` is the mean of the four taps, `own` the fragment's own height.
 * SIGN: the surroundings standing HIGHER than the fragment means the fragment
 * lies in a hollow, and a hollow is darker — so a positive difference gives a
 * NEGATIVE term. Turning that around lights the ditches and shades the ridges,
 * which is exactly the picture the stage exists to avoid.
 *
 * Flat ground answers 0 to the last bit, which is the neutrality promise: a
 * world nobody has shaped is not merely almost untouched.
 */
export function ngAoShade(ringMean: number, own: number): number {
  const t = Math.min(Math.max((ringMean - own) / NG_AO_SPAN_M, -1), 1);
  return t > 0 ? -NG_AO_DOWN * t : -NG_AO_UP * t;
}

/** The heightfield as the shader has to address it — the overview's own
 *  header, and nothing else. */
export interface NgFieldSpec {
  origin_x: number;
  origin_z: number;
  step_m: number;
  rows: number;
  cols: number;
}

/**
 * World point → texture coordinate of the height data texture.
 *
 * TEXEL CENTRES, not corners: support point `i` of the field lies at
 * `origin + i · step` and is the CENTRE of texel `i`, so its coordinate is
 * `(i + 0.5) / cols`. Getting that half wrong shifts the whole shading by half
 * a support cell — invisible in a screenshot, and a systematic lie about where
 * the hill is.
 *
 * `inside` is false beyond the field, where the stage has to be exactly
 * neutral: the world outside the raster is the flat border the server pins to
 * 0, and shading it against its own edge would draw a rim around the map.
 */
export function ngFieldUv(x: number, z: number, field: NgFieldSpec
): { u: number; v: number; inside: boolean } {
  const u = ((x - field.origin_x) / field.step_m + 0.5) / field.cols;
  const v = ((z - field.origin_z) / field.step_m + 0.5) / field.rows;
  return { u, v, inside: u >= 0 && u <= 1 && v >= 0 && v <= 1 };
}

// ── (4) THE SOFT AREA EDGE IS GONE — it became a CUT ────────────────────────
//
// Everything that used to stand here belonged to ONE mechanism: a painted area
// was a transparent mesh that faded out over the last 1.5 m of itself
// (`NG_EDGE_BAND_M`), so the band needed a per-vertex distance to the area's
// ring (`ngEdgeDistance`), an alpha curve (`ngEdgeAlpha`) and — because a
// triangle with all three corners ON the ring interpolates "0, 0, 0" and would
// fade the whole area away — a refinement pass that split the drape's triangles
// until that distance could be read linearly (`ngRefineEdgeBand`, eight passes,
// up to 20 000 triangles).
//
// Since E3 (plan-ein-boden.md § G3) a ground boundary is not an overlap of two
// meshes but a CUT in the one terrain surface, and how soft it is is the
// layer's own `edge_blend_m` acting on a signed distance the SERVER bakes
// (`app/core/terrain_layers.py`, read by `@anima/scene-render` `layerCut.ts`).
// The two numbers that made the border organic rather than a drawn outline —
// half a metre of push over a two-metre wavelength — moved there unchanged
// (`LC_EDGE_NOISE_M` / `LC_EDGE_WAVE_M`); they now push the LINE instead of the
// alpha, which costs one add and no transparency at all.

/**
 * Does this surface class carry its own shader already?
 *
 * Water and ice are ONE surface in `@anima/scene-render/materials.ts` (ice is
 * water that stands still), and that surface is a full shader of its own:
 * scrolling normal maps, a sky fresnel, a roughness mask. Blending a second
 * sample of a water texture into it and then shading it by the ground's relief
 * would fight every one of those — the ripples are the surface, not the
 * texture under them.
 *
 * The predicate is here rather than beside the patch so the smoke can ask it
 * directly instead of reading a regular expression out of `ground.ts`.
 */
export function isWaterClass(cls: string | null | undefined): boolean {
  const c = (cls || '').toLowerCase();
  return c === 'water' || c === 'ice';
}
