/**
 * THE VEIL — haze over the ground the avatar has never walked.
 *
 * `plan-fog-schleier-v2.md`, the successor of the fog that was deleted whole
 * on 2026-08-19 (decision E1.3). What went then was cloud quads and a veil
 * geometry cut to the known footprints — a cover, and one that had to be
 * rebuilt out of triangles whenever the world was discovered a little
 * further. This is not that. It is FOUR UNIFORMS AND ONE TEXTURE FETCH in the
 * ground shader:
 *
 *   - the avatar's explored cells reach the GPU as ONE data texture, one texel
 *     per 64 m cell (`GET /play/explored`, § A12);
 *   - the fragment mixes its own lit colour towards a haze colour by
 *     `alpha · (1 − explored)`, so the terrain KEEPS ITS SHAPE under the veil:
 *     a ridge stays a ridge, a lake stays darker than the meadow. "Dunst,
 *     nicht schwarz" is the whole point of the round;
 *   - the linear filter of that texture IS the soft cell edge — 32 m, half a
 *     cell, without a blur pass or a single triangle (`fogVeilMath.ts`);
 *   - and the strength follows the CAMERA HEIGHT, so the veil belongs to the
 *     overview and is exactly gone by the time one is embodied.
 *
 * NO GEOMETRY, NO SECOND DRAW CALL, NO PER-FRAME ALLOCATION. The only thing
 * this module allocates is the cells texture, and only when the explored set
 * really changed (`explored_sig`).
 *
 * ── WHAT IT IS PATCHED ONTO ────────────────────────────────────────────────
 * The OPEN WORLD's ground and nothing else — exactly the list of
 * `applyNaturalGround` (the CDLOD terrain and the non-water ground pieces of
 * `scene/ground.ts`). Deliberately NOT patched:
 *
 *   - PROPS, SCATTER, UNDERGROWTH (plan § 4): they stay drawn. They are part
 *     of the shape of the land under the haze, and hiding them would be a
 *     second culling path for a decision the haze already makes.
 *   - LOCATION TILES — buildings, floor plates, interiors. A known place stays
 *     visible as it always was (§ A12): the veil answers "have I WALKED
 *     there", the location filter answers "do I KNOW this place", and a
 *     building drawn on hazy ground is exactly the honest picture of a place
 *     one has heard of but never visited.
 *   - FIGURES. They are not hidden here because they never arrive: the server
 *     drops every character standing on unexplored ground out of the player's
 *     worldmap payload (`app/core/world_ops.py`). A veil a client could switch
 *     off would otherwise be a curtain with a hole in it.
 *
 * ── THE ONE PATCH RULE ─────────────────────────────────────────────────────
 * `onBeforeCompile` is ONE slot: the previous callback is captured and called
 * FIRST, the cache keys are combined, and a WeakSet keeps a second application
 * from declaring the varying twice — the rule of `patchHole`,
 * `applyNaturalGround` and `patchTerrainLod`, learned the hard way when the
 * water shader was built and thrown away one line later.
 *
 * The insertion point is `#include <opaque_fragment>` and the value written is
 * `outgoingLight` — the same anchor the water's sky fresnel uses
 * (`@anima/scene-render` `materials.ts`). It is the LIT colour, after every
 * albedo stage and after the lighting: haze does not tint a texture, it stands
 * between the eye and a finished surface.
 *
 * ── LIVE UPDATES WITHOUT A POP ─────────────────────────────────────────────
 * Two cells textures are bound at once and the shader mixes between them
 * (`uFogMix`, `FOG_FADE_S`). When the memory grows, the new set becomes B, the
 * previous one A, and the mix runs 0 -> 1 over half a second: every cell that
 * did NOT change reads the same in both, so nothing but the newly explored
 * ground moves. When the fade has finished both samplers point at the same
 * texture again and the old one is freed.
 *
 * A change that arrives DURING a fade restarts it from the interrupted state
 * (A becomes the half-shown B). The cells that were opening then snap open —
 * measured against the alternative (a queue of textures, each with its own
 * clock) that is a fair trade: the memory only grows when the avatar crosses a
 * 64 m cell border, which is seconds apart at walking pace.
 */
import * as THREE from 'three';
import { FOG_ALPHA_MAX, FOG_CELL_M, FOG_FADE_S, fogGrid, fogHeightAlpha,
  fogParseCell, fogTexIndex } from './fogVeilMath';

/** The cache key this patch contributes — constant, so every veiled ground
 *  compiles to ONE program (every number of the effect is a shared uniform or
 *  a GLSL literal). Exported for the smoke, which pins the COMBINED key. */
export const FOG_VEIL_CACHE_KEY = 'fog-veil';

// ── The shared uniforms ────────────────────────────────────────────────────
// ONE object per value for every patched material — the pattern of
// `naturalGround.ts`. A world with two hundred ground pieces costs ONE upload
// when the memory grows, and nothing recompiles.

/** A cells texture, read the way the soft edge needs it: LINEARLY filtered
 *  (that filter IS the blend, see `fogVeilMath`) and CLAMPED at the edge —
 *  outside the grid lies the zero ring, and clamping extends exactly that. */
function makeCells(data: Uint8Array, cols: number, rows: number): THREE.DataTexture {
  const tex = new THREE.DataTexture(data, cols, rows, THREE.RedFormat);
  tex.minFilter = THREE.LinearFilter;
  tex.magFilter = THREE.LinearFilter;
  tex.wrapS = THREE.ClampToEdgeWrapping;
  tex.wrapT = THREE.ClampToEdgeWrapping;
  tex.generateMipmaps = false;
  // One byte per texel: the default unpack alignment of 4 would tear every
  // grid whose column count is not a multiple of four into a diagonal smear.
  tex.unpackAlignment = 1;
  tex.needsUpdate = true;
  return tex;
}

/** "Nothing is explored" — one zero texel. It is the boot state (before the
 *  first `GET /play/explored` answers), the answer for an empty memory, and
 *  the state after teardown. Never disposed: it is what everything falls back
 *  to. With clamp-to-edge the whole world samples this one zero, which is a
 *  world nobody has walked yet — the correct picture, not a placeholder. */
const neutralCells = makeCells(new Uint8Array(1), 1, 1);

const uFogCellsA: { value: THREE.DataTexture } = { value: neutralCells };
const uFogCellsB: { value: THREE.DataTexture } = { value: neutralCells };
/** Where each grid lies, in CELLS: (cx0, cz0, cols, rows) — the four numbers
 *  `fogTexUv` needs. */
const uFogGeomA = { value: new THREE.Vector4(0, 0, 1, 1) };
const uFogGeomB = { value: new THREE.Vector4(0, 0, 1, 1) };
/** 0 = show A, 1 = show B; the crossfade of a growing memory. */
const uFogMix = { value: 1 };
/**
 * How much of the ground colour the haze may take HERE AND NOW — the height
 * ramp times `FOG_ALPHA_MAX`, or 0.
 *
 * THE NEUTRALITY SWITCH, and a uniform rather than a define so that stepping
 * out of the embodied mode does not recompile a single program: the shader's
 * own `if ( uFogAlpha > 0.0 )` then costs one comparison and reads no texture
 * at all — the same promise the natural-ground stages make for a flat world.
 */
const uFogAlpha = { value: 0 };
/** The haze colour. Follows the SKY (`Engine.setGameHour`), so the veil is
 *  pale blue by day, orange at dusk and near-black at night instead of being
 *  one grey that is wrong twice a day. */
const uFogColor = { value: new THREE.Color(0x9fc7e8) };

// ── What the veil's strength is made of ────────────────────────────────────
// Three inputs, one output (`pushAlpha`). Kept apart so that each can be
// written when it changes and none has to remember the others' values.

/** Camera height above the point it looks at, in metres — written per frame. */
let camHeightM = 0;
/** Does the payload this client polls carry the FILTER at all? The admin's
 *  unfiltered "show all" view does not, and hazing a view in which nothing is
 *  withheld would be a picture of a rule that is not running. */
let fogged = true;
/** The isolation panel's toggle 20 (`debug3d.ts`). */
let debugOff = false;

function pushAlpha(): void {
  uFogAlpha.value = (debugOff || !fogged)
    ? 0 : FOG_ALPHA_MAX * fogHeightAlpha(camHeightM);
}

/** How high the camera stands above the point it looks at. Called per frame
 *  from the frame hook; writing a uniform is free, so there is no threshold
 *  here that could make the veil lag behind the wheel. */
export function setFogVeilCameraHeight(metres: number): void {
  camHeightM = Number.isFinite(metres) ? metres : 0;
  pushAlpha();
}

/** Is this the FILTERED view (`WorldMap.fogged`)? The admin's unfiltered one
 *  gets no veil — see the field above. */
export function setFogVeilFogged(on: boolean): void {
  fogged = !!on;
  pushAlpha();
}

/** Switch the whole veil off — the isolation panel and nothing else. A
 *  uniform, so no program is rebuilt; switching it back on restores whatever
 *  the camera and the payload say NOW, not what they said when it was
 *  flipped. */
export function setFogVeilDebugOff(on: boolean): void {
  debugOff = on;
  pushAlpha();
}

/** …and the sky colour the haze takes, called beside `setSurfaceSky`. */
export function setFogVeilSky(hex: number): void {
  uFogColor.value.setHex(hex);
}

// ── The explored set ───────────────────────────────────────────────────────

/** Free a texture unless it is the shared neutral one or still bound. */
function retire(tex: THREE.DataTexture): void {
  if (tex === neutralCells || tex === uFogCellsA.value
      || tex === uFogCellsB.value) return;
  tex.dispose();
}

/**
 * Take over the avatar's exploration memory — called when `explored_sig`
 * moves and the refetch has answered, and with an empty list on teardown or
 * when there is no avatar.
 *
 * The whole set arrives every time (§ A12: the payload is flat and complete),
 * so this builds the grid from scratch rather than trying to patch texels: a
 * few tens of thousands of `Uint8Array` writes are cheaper than any bookkeeping
 * that could disagree with the server about which cells are in.
 */
export function setFogVeilCells(cells: readonly string[]): void {
  const grid = fogGrid(cells ?? []);
  let next = neutralCells;
  if (grid) {
    const data = new Uint8Array(grid.cols * grid.rows);
    for (const key of cells) {
      const cell = fogParseCell(key);
      if (!cell) continue;
      const at = fogTexIndex(cell[0], cell[1], grid);
      if (at >= 0) data[at] = 255;
    }
    next = makeCells(data, grid.cols, grid.rows);
  }
  const previousA = uFogCellsA.value;
  uFogCellsA.value = uFogCellsB.value;
  uFogGeomA.value.copy(uFogGeomB.value);
  uFogCellsB.value = next;
  if (grid) uFogGeomB.value.set(grid.cx0, grid.cz0, grid.cols, grid.rows);
  else uFogGeomB.value.set(0, 0, 1, 1);
  uFogMix.value = 0;
  retire(previousA);
}

/** Advance the crossfade — one line per frame, from the frame hook. */
export function tickFogVeil(dt: number): void {
  if (uFogMix.value >= 1) return;
  uFogMix.value = Math.min(1, uFogMix.value + (dt > 0 ? dt : 0) / FOG_FADE_S);
  if (uFogMix.value < 1) return;
  // Settled: both samplers point at the new set, and the old one is freed.
  // Doing this HERE rather than in `setFogVeilCells` is what makes the fade a
  // real crossfade — the previous texture has to stay alive while it is shown.
  const old = uFogCellsA.value;
  uFogCellsA.value = uFogCellsB.value;
  uFogGeomA.value.copy(uFogGeomB.value);
  retire(old);
}

/** Back to "nothing explored" and no GPU memory held — teardown. */
export function releaseFogVeil(): void {
  const a = uFogCellsA.value;
  const b = uFogCellsB.value;
  uFogCellsA.value = neutralCells;
  uFogCellsB.value = neutralCells;
  uFogGeomA.value.set(0, 0, 1, 1);
  uFogGeomB.value.set(0, 0, 1, 1);
  uFogMix.value = 1;
  retire(a);
  retire(b);
}

// ── The shader patch ───────────────────────────────────────────────────────

/** Materials that already carry the patch — a second application would
 *  declare `vFogWorld` twice and the shader would not compile. */
const patched = new WeakSet<THREE.Material>();

/** Where the world position is taken: AFTER `project_vertex`, like the hole,
 *  the corridor and the natural ground — the terrain displaces its vertices in
 *  the vertex shader, and a patch that measured before that displacement would
 *  haze the ground where it used to be. */
const ANCHOR_VERT = '#include <project_vertex>';
/** …and the colour work goes BEFORE `opaque_fragment`, on `outgoingLight`:
 *  the finished lit colour, see the file header. */
const ANCHOR_FRAG = '#include <opaque_fragment>';

/**
 * Give a ground material the veil. Chained, never assigned.
 *
 * In `scene/ground.ts` the material arrives with `patchHole` already in the
 * slot, so the combined key reads `ground-hole+fog-veil` (+ whatever is
 * chained after). The ORDER against the other ground patches does not matter
 * here and that is by design: they all write `diffuseColor` at
 * `#include <map_fragment>`, this one writes `outgoingLight` several chunks
 * later, so no two of them can race for the same anchor.
 */
export function applyFogVeil(mat: THREE.Material): void {
  if (patched.has(mat)) return;
  patched.add(mat);
  const prev = mat.onBeforeCompile;
  // three's DEFAULT `customProgramCacheKey` returns `onBeforeCompile.toString()`
  // — only a patch with a key of its OWN is worth carrying. Read here, before
  // the slot below is overwritten.
  const prevKey = Object.prototype.hasOwnProperty.call(mat, 'customProgramCacheKey')
    ? String(mat.customProgramCacheKey())
    : '';
  mat.onBeforeCompile = (shader, renderer) => {
    prev.call(mat, shader, renderer);
    shader.uniforms.uFogCellsA = uFogCellsA;
    shader.uniforms.uFogCellsB = uFogCellsB;
    shader.uniforms.uFogGeomA = uFogGeomA;
    shader.uniforms.uFogGeomB = uFogGeomB;
    shader.uniforms.uFogMix = uFogMix;
    shader.uniforms.uFogAlpha = uFogAlpha;
    shader.uniforms.uFogColor = uFogColor;
    // A three version without the anchors leaves the material UNPATCHED as a
    // whole: the fragment side alone would read a varying nobody wrote.
    if (!shader.vertexShader.includes(ANCHOR_VERT)) return;
    if (!shader.fragmentShader.includes(ANCHOR_FRAG)) return;

    shader.vertexShader = 'varying vec2 vFogWorld;\n' + shader.vertexShader
      .replace(ANCHOR_VERT, `${ANCHOR_VERT}
\tvFogWorld = ( modelMatrix * vec4( transformed, 1.0 ) ).xz;`);

    const head = `
uniform sampler2D uFogCellsA;
uniform sampler2D uFogCellsB;
uniform vec4 uFogGeomA;
uniform vec4 uFogGeomB;
uniform float uFogMix;
uniform float uFogAlpha;
uniform vec3 uFogColor;
varying vec2 vFogWorld;
/**
 * How explored the ground at a plan point is, 0…1 — the GLSL twin of
 * fogTexUv(): texel centres sit on CELL centres, so the linear filter of the
 * texture ramps over the 64 m between two of them and crosses 0.5 exactly on
 * the cell boundary. That ramp IS the soft edge; there is no blur anywhere.
 */
float fogExploredAt( sampler2D cells, vec4 geom, vec2 p ) {
  vec2 uv = ( p / ${FOG_CELL_M.toFixed(1)} - geom.xy ) / geom.zw;
  return texture2D( cells, uv ).r;
}
`;

    const body = `
  if ( uFogAlpha > 0.0 ) {
    // The crossfade of a growing memory: every cell that did not change reads
    // the same in both grids, so only the newly explored ground moves.
    float fogSeen = mix( fogExploredAt( uFogCellsA, uFogGeomA, vFogWorld ),
                         fogExploredAt( uFogCellsB, uFogGeomB, vFogWorld ),
                         uFogMix );
    // MIX, not multiply: the haze stands BETWEEN the eye and a finished
    // surface, so what is left of the ground keeps its own shading and the
    // silhouette of the land stays readable. A multiply would darken the
    // unexplored world into a black hole, which is the picture this round
    // exists to replace.
    outgoingLight = mix( outgoingLight, uFogColor,
                         uFogAlpha * ( 1.0 - clamp( fogSeen, 0.0, 1.0 ) ) );
  }
`;
    shader.fragmentShader = head + shader.fragmentShader
      .replace(ANCHOR_FRAG, `${body}\n${ANCHOR_FRAG}`);
  };
  mat.customProgramCacheKey = () => (prevKey
    ? `${prevKey}+${FOG_VEIL_CACHE_KEY}`
    : FOG_VEIL_CACHE_KEY);
}
