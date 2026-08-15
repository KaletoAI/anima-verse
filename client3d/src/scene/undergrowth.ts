/**
 * THE UNDERGROWTH — the layer nobody authored, grown WHERE IT IS SEEN
 * (plan-undergrowth-rettung.md, 2026-08-16).
 *
 * A wood only reads as a wood when something stands BETWEEN the trunks. The
 * terrain KIND says how much of it there is (`meta.undergrowth`, 0..1, § A9)
 * and this file grows it — the whole layer, from the blade texture to the
 * meshes in the scene.
 *
 * WHAT WENT WRONG WITH THE FIRST BUILD, and what this file is the answer to.
 * The layer used to be sampled ONCE PER PAINTED AREA, over the whole shape,
 * with a ceiling of 20 000 instances to keep a lake-sized meadow from building
 * a ten-megabyte matrix buffer in one frame. On a square kilometre of deep
 * forest that ceiling is not a guard but the density: 90 000 wanted tufts
 * become 20 000, i.e. 0.02/m2, and the ground looks bare. The user's finding
 * word for word — "on the huge deep-forest area hardly noticeable, the area is
 * still very empty".
 *
 * SO THE UNIT IS NO LONGER THE SHAPE, IT IS THE CELL. The layer is invisible
 * beyond `UNDERGROWTH_CULL_M` (60 m), so nothing needs to exist further out
 * than that: the world is cut into an ORIGIN-ANCHORED 64 m raster and only the
 * cells within `UNDERGROWTH_CELL_RADIUS_M` (128 m) of the anchor are built.
 * Each cell samples at the FULL density over its own 4096 m2, so a 10 km2 wood
 * is locally exactly as dense as a small meadow, and the cost is constant
 * whatever the world looks like — about twenty cells of a thousand tufts.
 *
 * THE ANCHOR IS THE HEIGHT TILES' OWN (`scene/heightTiles.ts`, § A16.3): the
 * avatar while the player is in control of it, the camera's ground target
 * otherwise. One anchor for both windows, fed by `ground.ts` from the same
 * call — two "where is the play" answers would be two windows drifting apart.
 *
 * DETERMINISTIC PER CELL. The seed is `(area id, cell)`, so a cell built,
 * dropped and built again is the same tufts in the same places, and two
 * NEIGHBOURING cells are not copies of each other — the mistake the raster
 * invites, and the one `smoke_undergrowth.mjs` keeps a red counter-check for.
 *
 * WHERE THE POINTS COME FROM is still the ONE shared sampler
 * (`@anima/scene-render` `scatterInstances`) with the ring of the CELL and the
 * area's own ring as the filter behind it, the footprints of the placed
 * locations kept clear (finding B18) and the rings painted above it as
 * occluders — the very last-hit-wins order `terrain_query` reads. Nothing here
 * decides geometry that the shared module could decide.
 *
 * THE LOOK IS CROSS QUADS, NOT CONES. The first build drew a five-sided cone
 * per tuft, which from eye level reads as "strange pointed cones coming out of
 * the ground" (the other half of the same finding). Two crossed quads carrying
 * a procedurally generated blade texture with an alpha cut is what a grass
 * tuft is in every renderer that has one — and the texture is generated here,
 * from `undergrowthTexturePixels`, so it is a pure function of a size and
 * checkable by hand rather than an asset nobody can diff.
 *
 * THE AUTHORED SCATTER IS UNTOUCHED. `ground.ts` still grows the tuft cones of
 * `meta.scatter` exactly as before — those are what an author placed, and this
 * round is about the layer nobody placed.
 */
import * as THREE from 'three';
import { pointInRing, scatterInstances } from '@anima/scene-render';
import type { Point2, ScatterFootprint } from '@anima/scene-render';
import { applyOcclusionFade } from './occlusion';
import { UNDERGROWTH_CELL_M, UNDERGROWTH_CELL_RADIUS_M,
  undergrowthCellCount, UNDERGROWTH_CULL_M, undergrowthDensityPer100m2,
  undergrowthHeight, UNDERGROWTH_H_MAX, UNDERGROWTH_H_MIN,
  UNDERGROWTH_MAX_PER_CELL, undergrowthVisible } from './scatterLod';

/* ==========================================================================
 * (1) THE CELL RASTER — pure set maths, the `heightTiles.ts` pattern
 *
 * No fetching, no meshes, no three: keys in, keys out. That is what lets the
 * numbers below be derived by hand in `client3d/scripts/smoke_undergrowth.mjs`
 * instead of being read off a running client.
 * ========================================================================== */

/** Hard ceiling on cells per axis inside the radius — a guard, not a working
 *  limit. The working case is 128 m over 64 m cells, i.e. 5 columns; a
 *  hand-edited radius that made thousands of cells fall inside it would build
 *  a million meshes, and this stops the loop before it walks the candidates. */
const MAX_CELLS_PER_AXIS = 32;

/** The key of one cell — `"cx,cz"`, the shape the height tiles use for the
 *  same job. `wantedUndergrowthCells` is the ONE place that turns a place into
 *  such a key (`Math.floor`, so a cell owns its lower edge), and `buildCell`
 *  reads the pair back out of it — there is no second opinion about which
 *  square of the world a cell is. */
export function undergrowthCellKey(cx: number, cz: number): string {
  return `${cx},${cz}`;
}

/**
 * The cells worth holding around (x, z): every cell whose SQUARE comes within
 * `radiusM` of the point, nearest first.
 *
 * THE TEST IS SQUARE-TO-POINT, not centre-to-point, exactly as in
 * `heightTiles.wantedTiles`: a cell is 64 m across, so measuring from its
 * centre would drop the cell the player is standing at the edge of. `dx`/`dz`
 * are the distance from the point to the cell's box, 0 on the axes where the
 * point is inside it — which is why the anchor's own cell always comes first.
 *
 * NEAREST FIRST is not cosmetic here either: building a cell is the expensive
 * half of a border crossing, and the ground the player is about to see has to
 * be built before the rim of the window. Ties are broken by the key, so the
 * order is stable and a smoke can name it.
 */
export function wantedUndergrowthCells(
  x: number, z: number, radiusM: number = UNDERGROWTH_CELL_RADIUS_M,
): string[] {
  if (!Number.isFinite(x) || !Number.isFinite(z) || !(radiusM >= 0)) return [];
  const cell = UNDERGROWTH_CELL_M;
  const firstX = Math.floor((x - radiusM) / cell);
  const lastX = Math.floor((x + radiusM) / cell);
  const firstZ = Math.floor((z - radiusM) / cell);
  const lastZ = Math.floor((z + radiusM) / cell);
  if (lastX - firstX > MAX_CELLS_PER_AXIS || lastZ - firstZ > MAX_CELLS_PER_AXIS) {
    return [];
  }
  const reach = radiusM * radiusM;
  const hits: { key: string; d2: number }[] = [];
  for (let cz = firstZ; cz <= lastZ; cz += 1) {
    const dz = Math.max(cz * cell - z, 0, z - (cz + 1) * cell);
    for (let cx = firstX; cx <= lastX; cx += 1) {
      const dx = Math.max(cx * cell - x, 0, x - (cx + 1) * cell);
      const d2 = dx * dx + dz * dz;
      if (d2 > reach) continue;
      hits.push({ key: undergrowthCellKey(cx, cz), d2 });
    }
  }
  hits.sort((a, b) => (a.d2 - b.d2) || (a.key < b.key ? -1 : a.key > b.key ? 1 : 0));
  return hits.map((h) => h.key);
}

/**
 * The seed of ONE cell of ONE area — its own namespace AND its own place.
 *
 * TWO THINGS HANG ON THIS STRING. The namespace (`terrain:undergrowth:`) keeps
 * the layer out of the authored scatter's stream (`scatterSeed`), which is what
 * stops this feature from moving every tree of every wood. The CELL keeps
 * neighbouring cells apart: a seed of the area alone would draw the identical
 * sequence of random numbers in every cell, and since each cell maps those
 * numbers onto its OWN box the whole world would be one tuft pattern stamped
 * out every 64 m — visible as a grid the moment anyone looked along it, and
 * measurable in the smoke (the relative offsets inside two cells would be
 * identical to the last decimal).
 */
export function undergrowthCellSeed(areaId: string,
                                    cx: number, cz: number): string {
  return `terrain:undergrowth:${areaId}:${cx},${cz}`;
}

/* ==========================================================================
 * (2) THE BLADE TEXTURE — a pure pixel function
 *
 * Generated at runtime, once per session, out of arithmetic: no asset, no
 * fetch, no canvas needed to DERIVE it (the pixels are a plain RGBA array; the
 * client pours them into a `DataTexture` below). Everything about a blade is a
 * formula of its index, so the alpha at a named coordinate is a hand value and
 * the smoke checks the picture rather than a hash of it.
 * ========================================================================== */

/** Edge of the generated texture in texels. 64 is what a knee-high tuft is
 *  worth on screen: at 60 m it is a few pixels tall, at arm's length the blade
 *  edges are what one sees, and both are served by a mip chain that starts
 *  here. */
export const UNDERGROWTH_TEX_SIZE = 64;

/** How many blades one texture carries. Inside the 6-9 the design asked for:
 *  an ODD number, so the middle blade sits on the texture's centre line and
 *  the two crossed quads do not read as a repeated pair. */
export const UNDERGROWTH_BLADES = 7;

/** Half the width of a blade AT ITS ROOT, as a share of the texture edge. */
const BLADE_HALF_W = 0.045;
/** How far a blade's tip leans out of the vertical, as a share of the edge.
 *  The lean is QUADRATIC in the height, like the wind in `applySway`: the root
 *  stands still and the tip carries all of it, which is how a blade bends. */
const BLADE_BEND = 0.12;
/** The three blade heights, as shares of the texture edge, taken in turn. The
 *  tallest stops at 0.90 ON PURPOSE: the top tenth is headroom, so the alpha
 *  silhouette never touches the texture border — a blade cut off by the clamp
 *  would end on a straight line instead of a tip (the same reason the far
 *  impostors keep `IMPOSTOR_BAKE_PAD`). */
const BLADE_HEIGHTS = [0.55, 0.725, 0.90];
/** How dark the root is and how much brighter the tip gets. The texture is
 *  GREYSCALE — the colour comes from the material, which is tinted with the
 *  terrain kind's own — so this is the only shading it carries: a blade a
 *  little darker where it stands in its own shadow. */
const BLADE_SHADE_MIN = 0.7;
const BLADE_SHADE_SPAN = 0.3;

/**
 * The blade texture as RGBA texels, ROW 0 AT THE BOTTOM — the roots.
 *
 * That way round because a `DataTexture` is uploaded with `flipY = false`
 * (three's own default for it) and the UVs of `undergrowthGeometry` put v = 0
 * at the foot of the quad. Row 0 is therefore the row the blades grow OUT of,
 * and nothing has to be flipped anywhere: get this backwards and the grass
 * hangs from the sky.
 *
 * Blade `i` of `UNDERGROWTH_BLADES`:
 *
 *   rootX  = (i + 0.5) / N · size            evenly spaced, none on the border
 *   height = BLADE_HEIGHTS[i % 3] · size     three lengths, taken in turn
 *   bend   = ±BLADE_BEND · size              alternating, so the tuft is not combed
 *   x(t)   = rootX + bend · t²               t = height above the root, 0..1
 *   halfW(t) = BLADE_HALF_W · size · (1 − t) tapering to a point
 *
 * and a texel is covered by the blade when its centre lies within `halfW` of
 * `x(t)`, ANTIALIASED over one texel: `cov = clamp(halfW − |dx| + 0.5, 0, 1)`.
 * A texel gets the strongest coverage of any blade — the blades never overlap
 * at this spacing, so the maximum and a sum are the same picture, and the
 * maximum cannot exceed 1.
 *
 * THE ONE PROPERTY WORTH NAMING, because the whole look hangs on it: the
 * summed coverage of one ROW is exactly the summed WIDTH of the blades that
 * cross it (a unit box filter reproduces the area of a ramp of unit slope
 * exactly, whatever the phase). So "the tip is narrower than the foot" is not
 * an impression — it is 39.85 texels of ink in row 0 against 2.22 in row 46,
 * and the smoke derives both by hand.
 */
export function undergrowthTexturePixels(
  size: number = UNDERGROWTH_TEX_SIZE,
): Uint8ClampedArray {
  const n = Math.max(1, Math.floor(size));
  const out = new Uint8ClampedArray(n * n * 4);
  const blades = [];
  for (let i = 0; i < UNDERGROWTH_BLADES; i += 1) {
    blades.push({
      rootX: ((i + 0.5) / UNDERGROWTH_BLADES) * n,
      heightPx: BLADE_HEIGHTS[i % BLADE_HEIGHTS.length] * n,
      bend: BLADE_BEND * n * (i % 2 === 0 ? 1 : -1),
      halfW0: BLADE_HALF_W * n,
    });
  }
  for (let r = 0; r < n; r += 1) {
    // Height of this row's centre above the texture's BOTTOM edge, in texels —
    // row 0 IS the bottom, see the doc comment.
    const py = r + 0.5;
    // The grey is the row's own — it never depends on which blade won, so a
    // mip level that blends two blades blends one shade and not a seam.
    const grey = Math.round(255 * (BLADE_SHADE_MIN + BLADE_SHADE_SPAN * (py / n)));
    for (let c = 0; c < n; c += 1) {
      const px = c + 0.5;
      let cov = 0;
      for (const b of blades) {
        const t = py / b.heightPx;
        if (t > 1) continue;
        const x = b.rootX + b.bend * t * t;
        const halfW = b.halfW0 * (1 - t);
        const v = halfW - Math.abs(px - x) + 0.5;
        if (v > cov) cov = v > 1 ? 1 : v;
      }
      const o = (r * n + c) * 4;
      out[o] = grey;
      out[o + 1] = grey;
      out[o + 2] = grey;
      // The grey is written EVERYWHERE, the alpha only where a blade stands:
      // a transparent texel that is black bleeds a dark rim into every mip
      // level, and the alpha cut below cannot take that back.
      out[o + 3] = Math.round(255 * cov);
    }
  }
  return out;
}

/* ==========================================================================
 * (3) THE MESHES — geometry, material and the per-cell layers
 * ========================================================================== */

/** The height ONE tuft's geometry is built at, in metres: the middle of the
 *  span. Every instance is scaled from here to its own height
 *  (`undergrowthHeight`), so a whole meadow is one geometry and one draw call
 *  per cell and kind. */
export const UNDERGROWTH_H_REF_M = (UNDERGROWTH_H_MIN + UNDERGROWTH_H_MAX) / 2;

/** How wide a tuft is drawn, as a share of its height. A tuft of grass is
 *  about as wide as it is tall, and the texture spreads its seven blades over
 *  exactly this width — at the reference height that is a blade every 8 cm. */
const UNDERGROWTH_W_RATIO = 1.0;

/** The angle between the two crossed quads, in radians (80°).
 *
 *  NOT the perfect 90° the technique is usually drawn with: two quads at a
 *  right angle are symmetric under a quarter turn, so a field of them shows
 *  the same silhouette from four directions and the eye finds the pattern. A
 *  slight twist costs nothing and breaks it. */
const UNDERGROWTH_CROSS_RAD = (80 * Math.PI) / 180;

/** The alpha a texel needs to be drawn at all.
 *
 *  `alphaTest` AND NOT `transparent`, which is the whole reason the layer can
 *  be thousands of instances: an alpha-tested material stays in the OPAQUE
 *  pass, writes depth and needs no sorting, so a cell of a thousand tufts is
 *  one draw call whatever order they stand in. A transparent one would have to
 *  be sorted per frame and would still show the seams where two quads cross.
 *  0.35 sits below the antialiased edge of a blade (which reaches ~0.5 at the
 *  outermost covered texel) and well above the mip bleed between blades. */
export const UNDERGROWTH_ALPHA_TEST = 0.35;

/** How far a tuft reaches beyond the point it stands on, in metres — the
 *  tallest blade plus half the widest quad plus the wind's own maximum
 *  (`SWAY_MAX_M` in `ground.ts`, 0.5). Padding for the culling sphere only. */
const UNDERGROWTH_REACH_M = UNDERGROWTH_H_MAX
  + (UNDERGROWTH_H_MAX * UNDERGROWTH_W_RATIO) / 2 + 0.5;

/**
 * The crossed quads of ONE tuft, base at y = 0 (B16), `h` tall and
 * `h · UNDERGROWTH_W_RATIO` wide.
 *
 * Two cards, the second turned by `UNDERGROWTH_CROSS_RAD` about +Y. Both carry
 * the whole texture (0..1 in both UV axes), so a tuft is the same seven blades
 * seen from two directions rather than two different plants.
 *
 * THE NORMALS POINT STRAIGHT UP, all eight of them, and that is the one thing
 * about a grass card that is NOT its geometry. A card's true normal is
 * horizontal, and under a sun that stands overhead a horizontal normal means
 * `dot(N, L) = 0`: the whole carpet loses the sun at midday and is lit by the
 * hemisphere alone. With this world's noon lighting (`scene/engine.ts`: sun
 * 2.25 at the zenith, hemisphere 1.55, fill 0.5·… ≈ 0.25 at 27° elevation)
 * that is about 1.55 against the 4.05 the GROUND under it receives — the
 * carpet reads as a dark stain on a bright meadow, which is the finding this
 * line answers. Pointing them up is the usual grass-card trick: the tuft is
 * then lit exactly like the ground it grows out of, and the shading of a field
 * of them stays flat and even instead of flickering with the yaw of each card.
 *
 * AND THAT IS WHY EVERY CARD IS WOUND BOTH WAYS (24 indices over 8 vertices,
 * not 12). Both faces of a card have to be drawn — but three flips the normal
 * of a BACK face, so a single winding plus `DoubleSide` would give a tuft the
 * full 4.05 from one side and, with `N = (0, −1, 0)`, the hemisphere's GROUND
 * colour and no sun at all from the other: the same tuft would swing by a
 * factor of 2.6 as the camera orbits past it, which is worse than the even
 * gloom it replaced. The reversed triangles make both sides FRONT faces, so
 * the normal is never flipped and the material can stay `FrontSide`. It costs
 * twelve indices and no vertices, and back-face culling still draws exactly
 * four triangles per tuft from any one direction.
 */
export function undergrowthGeometry(h: number): THREE.BufferGeometry {
  const halfW = (h * UNDERGROWTH_W_RATIO) / 2;
  const c = Math.cos(UNDERGROWTH_CROSS_RAD);
  const s = Math.sin(UNDERGROWTH_CROSS_RAD);
  const pos: number[] = [
    // card A, in the xy-plane
    -halfW, 0, 0, halfW, 0, 0, halfW, h, 0, -halfW, h, 0,
    // card B, the same card turned about +Y: (1,0,0) -> (cos, 0, -sin)
    -halfW * c, 0, halfW * s, halfW * c, 0, -halfW * s,
    halfW * c, h, -halfW * s, -halfW * c, h, halfW * s,
  ];
  const uv = [0, 0, 1, 0, 1, 1, 0, 1, 0, 0, 1, 0, 1, 1, 0, 1];
  const normal: number[] = [];
  for (let i = 0; i < 8; i += 1) normal.push(0, 1, 0);
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  geo.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2));
  geo.setAttribute('normal', new THREE.Float32BufferAttribute(normal, 3));
  geo.setIndex([
    0, 1, 2, 0, 2, 3, 4, 5, 6, 4, 6, 7,
    // …and the same four triangles wound the other way round
    0, 2, 1, 0, 3, 2, 4, 6, 5, 4, 7, 6,
  ]);
  geo.computeBoundingSphere();
  return geo;
}

/** The ONE blade texture of the session — one `DataTexture` shared by every
 *  cell and every kind, because the tint is the MATERIAL's job. Built on first
 *  use and handed back by `dispose`. */
export function undergrowthTexture(): THREE.DataTexture {
  const n = UNDERGROWTH_TEX_SIZE;
  const tex = new THREE.DataTexture(new Uint8Array(undergrowthTexturePixels(n)),
                                    n, n, THREE.RGBAFormat);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.magFilter = THREE.LinearFilter;
  tex.minFilter = THREE.LinearMipmapLinearFilter;
  // A tuft is a few texels tall at 40 m and half the texture at arm's length,
  // so the mip chain is what keeps the blades from shimmering into noise.
  tex.generateMipmaps = true;
  // A `DataTexture` is uploaded UNFLIPPED (three's default for it), and the
  // pixel function writes row 0 at the bottom for exactly that reason — see
  // `undergrowthTexturePixels`. Nothing here may "correct" it.
  tex.needsUpdate = true;
  return tex;
}

/**
 * The tuft material of ONE terrain kind.
 *
 * The texture is greyscale, so `color` is the whole tint — the kind's own
 * colour, darkened by the same 0.75 the authored tuft uses, which is the
 * "existing tuft colour logic" this look inherits.
 *
 * THE 0.75 IS KEPT AFTER THE NORMALS WERE TURNED UP, and here is the reason it
 * became RIGHT rather than too dark. With the card's own horizontal normal the
 * tuft and the ground it stands on were lit differently — about 1.55 against
 * 4.05 at noon (see `undergrowthGeometry`) — so 0.75 was a tint riding on top
 * of a 2.6-fold lighting deficit and the carpet came out at roughly a quarter
 * of the ground's brightness. Now both carry `N = (0, 1, 0)` and receive the
 * SAME light, so the whole difference is albedo: the tuft is
 * `kind · 0.75 · grey`, and the texture's grey runs 0.70…1.00 over the blade's
 * height (mean ≈ 0.85), i.e. about 0.64 of the ground's own colour. A growth
 * roughly a third darker than the ground it comes out of is what reads as
 * growth; 1.0 would make the layer vanish into its ground and 0.5 would make a
 * meadow look burnt. No sight check was possible, so this is the arithmetic
 * the next acceptance round can argue against.
 *
 * `FrontSide` and not `DoubleSide`, and that is NOT a step back from "both
 * faces are drawn": the geometry carries every card with both windings, so
 * both faces ARE drawn and neither of them is a back face whose normal three
 * would flip. Read `undergrowthGeometry` — the two decisions are one.
 *
 * The two patches are CHAINED and in this order, like everything else that
 * stands on the ground: the wind first (`applySway`, handed in — it lives in
 * `ground.ts` and importing it here would close a cycle), the camera corridor
 * after it (`applyOcclusionFade`). Assigning either into `onBeforeCompile`
 * would throw the other away; the smoke pins both the order and the fact that
 * both are there.
 */
export function undergrowthMaterial(
  tex: THREE.Texture, color: string, swayM: number,
  applySway: (mat: THREE.Material, swayM: number, refH: number) => void,
): THREE.Material {
  const mat = new THREE.MeshStandardMaterial({
    map: tex,
    color: new THREE.Color(color).multiplyScalar(0.75),
    roughness: 0.95,
    alphaTest: UNDERGROWTH_ALPHA_TEST,
    side: THREE.FrontSide,
  });
  // IT BENDS BY THE GROUND'S OWN AMOUNT, with no prop factor in between: a
  // `sway_factor` says how much a PROP takes part in the wind, and the
  // undergrowth is not a prop — it is what the ground itself grows. The
  // reference height is the geometry's, whose top edge carries the whole
  // deflection; every instance is scaled to its own height and the shader
  // divides the amplitude by that scale (§ A9).
  applySway(mat, swayM, UNDERGROWTH_H_REF_M);
  applyOcclusionFade(mat);
  return mat;
}

/** One painted area, as much of it as the layer needs. Assembled by
 *  `ground.ts` once per terrain rebuild — everything here is already read out
 *  of the payload and the catalog, so the field never touches either.
 *
 *  THE LIST ORDER IS THE STACKING ORDER (the server sorts by `z_order`, then
 *  paint order), which is why no shape carries its own occluders: everything
 *  after it in the list IS painted over it, and the field takes the ones whose
 *  box really meets the cell it is sampling. */
export interface UndergrowthArea {
  id: string;
  kind: string;
  /** the CLEANED ring, `[x, z]` in world metres */
  ring: readonly Point2[];
  /** `[minX, minZ, maxX, maxZ]` of that ring — the cheap intersection test */
  bounds: readonly [number, number, number, number];
  /** `meta.undergrowth`, already clamped to 0..1; 0 grows nothing */
  value: number;
  /** the kind's colour, as the tint of the tuft material */
  color: string;
  /** the kind's `meta.sway_m`, already clamped */
  swayM: number;
}

/** One instanced layer: the tufts of ONE area inside ONE cell. */
interface CellLayer {
  mesh: THREE.InstancedMesh<THREE.BufferGeometry, THREE.Material>;
  /** how many tufts the sampler placed and the ring kept */
  baseCount: number;
  /** the instance matrices as built, 16 floats each — the SOURCE the buffer is
   *  filled from, never rewritten (which is what keeps the wind's phase, read
   *  off `instanceMatrix` in the shader, stable across every re-bin) */
  srcMatrix: Float32Array;
  /** world position of every tuft, 3 tight floats each — what the tick reads */
  pos: Float32Array;
  /** whether each tuft was in the buffer last tick: 0 = drawn, 1 = not. Only a
   *  change here costs a vertex-buffer upload. */
  slots: Uint8Array;
  /** bounding sphere over all of them, padded by the tuft's own reach —
   *  three.js culls against it, and the tick asks it first */
  sphere: THREE.Sphere;
  /** the layer is switched off whole by that sphere test */
  hidden: boolean;
}

export interface UndergrowthField {
  /** everything the layer owns, in one group the ground adds to the scene */
  readonly group: THREE.Group;
  /**
   * Take over the painted areas — called once per terrain (or relief) rebuild.
   *
   * Every cell that stands is rebuilt: the ground under it may have moved (a
   * new relief), the shapes on it may have changed and the kinds may have new
   * colours. Cheap enough to do outright — a cell is a thousand instances and
   * there are about twenty of them.
   */
  setAreas(areas: readonly UndergrowthArea[],
           footprints: readonly ScatterFootprint[]): void;
  /**
   * WHERE the play is, in world metres — the height tiles' own anchor.
   *
   * CHEAP TO CALL and meant to be called on a tick: it re-derives the want set
   * (25 candidate cells), builds the ones that came into range and drops the
   * ones that left it. Standing still costs the derivation and nothing else.
   */
  setAnchor(x: number, z: number): void;
  /** Re-decide which tufts are drawn, for a camera position — the 1 Hz LOD
   *  tick, the same beat the props are binned on. */
  tick(cam: THREE.Vector3): void;
  dispose(): void;
}

/**
 * The camera-local undergrowth of the whole world.
 *
 * `heightAt` is the ground sampler of `ground.ts` — the DRAWN surface, so a
 * tuft stands on the ground the player sees and not on the bilinear field
 * (§ A16). `applySway` is handed in for the same reason it is not imported:
 * it lives in `ground.ts`, which imports this file.
 */
export function createUndergrowthField(opts: {
  heightAt: (x: number, z: number) => number;
  applySway: (mat: THREE.Material, swayM: number, refH: number) => void;
}): UndergrowthField {
  const group = new THREE.Group();
  group.name = 'terrain-undergrowth';

  let areas: readonly UndergrowthArea[] = [];
  let footprints: readonly ScatterFootprint[] = [];
  /** every built cell, by key — each one holds one layer per area that shows
   *  ground in it */
  const cells = new Map<string, CellLayer[]>();
  /** where the play is, and whether it has ever been said. Nothing at all is
   *  built before the first anchor: the window follows the play, and before
   *  the first tick there is no play to follow. */
  let hasAnchor = false;
  let anchorX = 0;
  let anchorZ = 0;
  /** where the camera stood at the last tick, so a freshly built cell comes
   *  into the world binned instead of drawn in full */
  let lodCam: THREE.Vector3 | null = null;

  /** The ONE geometry and the ONE texture, built on first use and shared by
   *  every cell of every kind. The MATERIALS are per kind (colour and wind
   *  amplitude differ, and the amplitude is baked into the shader). */
  let geometry: THREE.BufferGeometry | null = null;
  let texture: THREE.DataTexture | null = null;
  const materials = new Map<string, THREE.Material>();

  function materialFor(area: UndergrowthArea): THREE.Material {
    const key = `${area.kind}|${area.color}|${area.swayM}`;
    const held = materials.get(key);
    if (held) return held;
    if (!texture) texture = undergrowthTexture();
    const mat = undergrowthMaterial(texture, area.color, area.swayM,
                                    opts.applySway);
    materials.set(key, mat);
    return mat;
  }

  /** The bounding sphere over the tufts of one layer, padded by how far a tuft
   *  reaches beyond the point it stands on. Centre and radius come from the
   *  AXIS-ALIGNED box, which is a hair larger than the tightest sphere and
   *  costs one pass instead of two — the rule `ground.ts` follows for the
   *  props. */
  function instanceSphere(pos: Float32Array): THREE.Sphere {
    let minX = Infinity; let minY = Infinity; let minZ = Infinity;
    let maxX = -Infinity; let maxY = -Infinity; let maxZ = -Infinity;
    for (let i = 0; i < pos.length; i += 3) {
      if (pos[i] < minX) minX = pos[i];
      if (pos[i] > maxX) maxX = pos[i];
      if (pos[i + 1] < minY) minY = pos[i + 1];
      if (pos[i + 1] > maxY) maxY = pos[i + 1];
      if (pos[i + 2] < minZ) minZ = pos[i + 2];
      if (pos[i + 2] > maxZ) maxZ = pos[i + 2];
    }
    const centre = new THREE.Vector3((minX + maxX) / 2, (minY + maxY) / 2,
                                     (minZ + maxZ) / 2);
    const radius = Math.hypot(maxX - minX, maxY - minY, maxZ - minZ) / 2
      + UNDERGROWTH_REACH_M;
    return new THREE.Sphere(centre, radius);
  }

  function copyMatrix(src: Float32Array, i: number,
                      dst: Float32Array, slot: number): void {
    const a = i * 16;
    const b = slot * 16;
    for (let j = 0; j < 16; j += 1) dst[b + j] = src[a + j];
  }

  /**
   * Build every layer of ONE cell.
   *
   * The sampler is given the CELL as its ring, so the density is the density
   * of the cell and not of the painted shape — that is the whole rescue. The
   * area's own ring is the filter behind it: a point is this area's when it
   * lies inside the area AND outside every area painted above it (the
   * occluders the sampler already rejects). A cell that is half wood and half
   * meadow therefore gets two layers, each at its own full density over its
   * own half, and the seam is the painted border and nothing else.
   */
  function buildCell(key: string): CellLayer[] {
    const [cxRaw, czRaw] = key.split(',');
    const cx = Number(cxRaw);
    const cz = Number(czRaw);
    const cell = UNDERGROWTH_CELL_M;
    const x0 = cx * cell;
    const z0 = cz * cell;
    const x1 = x0 + cell;
    const z1 = z0 + cell;
    const cellRing: Point2[] = [[x0, z0], [x1, z0], [x1, z1], [x0, z1]];
    /** Does that shape's bounding box meet this cell at all? The cheap
     *  rejection, and it is worth having twice over: a world has hundreds of
     *  painted shapes, and every one of them that is neither sampled nor
     *  tested as an occluder saves a point-in-ring per candidate. */
    const meetsCell = (b: readonly [number, number, number, number]): boolean => (
      b[2] >= x0 && b[0] <= x1 && b[3] >= z0 && b[1] <= z1);
    /**
     * The placed locations whose footprint can reach into this cell — the same
     * rejection once more, and the one that matters most.
     *
     * `pointInFootprint` turns the point into the square's own frame, i.e. two
     * multiplications and a sine per candidate PER LOCATION; a world with two
     * hundred places would spend that two hundred times on each of ~983
     * candidates of every cell, and building a cell is the one thing that
     * happens while the player walks.
     *
     * THE BOX IS THE TURNED SQUARE'S CIRCUMSCRIBED ONE (`half · √2` on both
     * axes), so the yaw never has to be read here and no footprint can be
     * dropped that would have blocked something: whatever the turn, the square
     * stays inside the circle of that radius. Anything that is not a square at
     * all (unplaced, no edge, junk) blocks nothing anywhere and goes now.
     */
    const nearFootprints = footprints.filter((fp) => {
      const cxp = fp?.pos_x;
      const czp = fp?.pos_z;
      const w = fp?.plan_width_m;
      if (typeof cxp !== 'number' || !Number.isFinite(cxp)) return false;
      if (typeof czp !== 'number' || !Number.isFinite(czp)) return false;
      if (typeof w !== 'number' || !(w > 0)) return false;
      const reach = (w / 2) * Math.SQRT2;
      return meetsCell([cxp - reach, czp - reach, cxp + reach, czp + reach]);
    });
    const out: CellLayer[] = [];
    areas.forEach((area, index) => {
      // A shape whose kind grows nothing, or whose value is so small that a
      // whole cell wants less than one tuft, is still in the list — as an
      // OCCLUDER of the shapes below it — but samples nothing itself.
      if (undergrowthCellCount(area.value) < 1) return;
      if (!meetsCell(area.bounds)) return;
      // Everything painted OVER this shape hides the ground it grows on, and
      // the list order IS the stacking order — the same last-hit-wins rule
      // `terrain_query` reads. Only the ones that reach into this cell can
      // hide anything in it.
      const occluders: (readonly Point2[])[] = [];
      for (let j = index + 1; j < areas.length; j += 1) {
        if (meetsCell(areas[j].bounds)) occluders.push(areas[j].ring);
      }
      const points = scatterInstances({
        ring: cellRing,
        areaM2: cell * cell,
        densityPer100m2: undergrowthDensityPer100m2(area.value),
        seed: undergrowthCellSeed(area.id, cx, cz),
        footprints: nearFootprints,
        occluders,
        maxPoints: UNDERGROWTH_MAX_PER_CELL,
        // ONE TRY PER WANTED TUFT, and that is the whole difference between
        // sampling a CELL and sampling a shape. The sampler's default of 12
        // exists because a ring fills only part of its bounding box, so a
        // candidate that misses the ring has to be re-rolled or the shape ends
        // up thinner than the density asks. Here the ring IS the box, so
        // NOTHING is ever re-rolled for that reason — and the only rejections
        // left are the ones that must SUBTRACT: a building's footprint and the
        // ground painted over this shape. Re-rolling those would squeeze a
        // whole cell's worth of tufts into the half of it that is still
        // visible, i.e. double the density right against the wall of a house.
        triesPerPoint: 1,
      });
      const kept = points.filter((p) => pointInRing(p.x, p.z, area.ring));
      if (!kept.length) return;

      if (!geometry) geometry = undergrowthGeometry(UNDERGROWTH_H_REF_M);
      const mesh: THREE.InstancedMesh<THREE.BufferGeometry, THREE.Material>
        = new THREE.InstancedMesh(geometry, materialFor(area), kept.length);
      const m = new THREE.Matrix4();
      const q = new THREE.Quaternion();
      const up = new THREE.Vector3(0, 1, 0);
      const at = new THREE.Vector3();
      const s = new THREE.Vector3();
      const srcMatrix = new Float32Array(kept.length * 16);
      const pos = new Float32Array(kept.length * 3);
      kept.forEach((p, i) => {
        q.setFromAxisAngle(up, p.yaw);
        // The height comes out of the instance's own yaw, so no second random
        // stream exists that could shift the first one.
        const scale = undergrowthHeight(p.yaw) / UNDERGROWTH_H_REF_M;
        s.set(scale, scale, scale);
        // Every tuft samples its own ground (§ A16) — a shared height would
        // float half a cell over the slope it grows on.
        const y = opts.heightAt(p.x, p.z);
        m.compose(at.set(p.x, y, p.z), q, s);
        m.toArray(srcMatrix, i * 16);
        pos[i * 3] = p.x;
        pos[i * 3 + 1] = y;
        pos[i * 3 + 2] = p.z;
      });
      mesh.castShadow = false;
      mesh.frustumCulled = true;
      // Nothing is drawn until the layer has been binned, exactly as for the
      // props: a mesh whose buffer holds the matrices of one camera position
      // must not be shown at the count of another.
      mesh.count = 0;
      mesh.visible = false;
      const layer: CellLayer = {
        mesh,
        baseCount: kept.length,
        srcMatrix,
        pos,
        // In NO buffer yet, so the first binning finds every tuft changed and
        // uploads once.
        slots: new Uint8Array(kept.length).fill(1),
        sphere: instanceSphere(pos),
        hidden: false,
      };
      // SET, never computed: three would derive the sphere from whatever
      // `count` happened to be at the first frustum test and keep that answer
      // for ever — after a binning that is the handful of tufts nearest the
      // camera, and the cell would be culled by their bounds.
      mesh.boundingSphere = layer.sphere;
      if (lodCam) binLayer(layer, lodCam);
      group.add(mesh);
      out.push(layer);
    });
    return out;
  }

  /** Take one cell out of the scene. The geometry, the texture and the
   *  materials are SHARED and stay; only the instance buffers go. */
  function dropCell(key: string): void {
    const layers = cells.get(key);
    if (!layers) return;
    for (const layer of layers) {
      group.remove(layer.mesh);
      layer.mesh.dispose();
    }
    cells.delete(key);
  }

  /**
   * Sort every tuft of one layer into the buffer or out of it — the whole
   * undergrowth LOD, once per layer per tick.
   *
   * ONE question per instance instead of the props' three: there is no mesh to
   * choose and no hysteresis to keep, because the thinning line reaches 0 at
   * the cull distance (`UNDERGROWTH_MIN_SHARE`) — a tuft is already gone when
   * the cull would take it, so nothing can pop across that line.
   *
   * The layer is answered against its own sphere first (a cell at the rim of
   * the 128 m window is switched off whole, and a tick that finds it already
   * off returns at once), the distance is compared SQUARED, and the buffer is
   * uploaded only when its set really changed.
   */
  function binLayer(layer: CellLayer, cam: THREE.Vector3): void {
    if (cam.distanceTo(layer.sphere.center) - layer.sphere.radius
        > UNDERGROWTH_CULL_M) {
      if (layer.hidden) return;
      layer.hidden = true;
      layer.slots.fill(1);
      layer.mesh.count = 0;
      layer.mesh.visible = false;
      return;
    }
    layer.hidden = false;
    const cull2 = UNDERGROWTH_CULL_M * UNDERGROWTH_CULL_M;
    const buf = layer.mesh.instanceMatrix.array as Float32Array;
    let n = 0;
    let dirty = false;
    for (let i = 0; i < layer.baseCount; i += 1) {
      const dx = layer.pos[i * 3] - cam.x;
      const dy = layer.pos[i * 3 + 1] - cam.y;
      const dz = layer.pos[i * 3 + 2] - cam.z;
      const d2 = dx * dx + dy * dy + dz * dz;
      // Negated on purpose, like the props': a NaN position draws nothing
      // instead of a NaN matrix.
      const slot = d2 <= cull2 && undergrowthVisible(i, Math.sqrt(d2)) ? 0 : 1;
      if (layer.slots[i] !== slot) {
        layer.slots[i] = slot;
        dirty = true;
      }
      if (slot === 0) {
        copyMatrix(layer.srcMatrix, i, buf, n);
        n += 1;
      }
    }
    layer.mesh.count = n;
    layer.mesh.visible = n > 0;
    if (dirty) layer.mesh.instanceMatrix.needsUpdate = true;
  }

  /** Build what the want set asks for and drop what it does not. The set is
   *  nearest first, so the ground the player is about to walk into is built
   *  before the rim of the window. */
  function refreshCells(): void {
    const want = wantedUndergrowthCells(anchorX, anchorZ);
    const keep = new Set(want);
    for (const key of [...cells.keys()]) {
      if (!keep.has(key)) dropCell(key);
    }
    for (const key of want) {
      if (cells.has(key)) continue;
      cells.set(key, buildCell(key));
    }
  }

  return {
    group,
    setAreas(next, fps) {
      areas = next;
      footprints = fps;
      for (const key of [...cells.keys()]) dropCell(key);
      // The kinds may have new colours and new wind, and the amplitude is
      // baked into the shader — so the materials go with the cells they were
      // built for rather than being reused across a rebuild.
      for (const mat of materials.values()) mat.dispose();
      materials.clear();
      if (hasAnchor) refreshCells();
    },
    setAnchor(x, z) {
      if (!Number.isFinite(x) || !Number.isFinite(z)) return;
      anchorX = x;
      anchorZ = z;
      hasAnchor = true;
      // ASKED ON EVERY TICK, not only when a cell border is crossed — the same
      // ruling `heightTiles.ts` writes down for its own window: the radius is
      // measured from the POINT, so the want set moves with every metre and a
      // crossing alone would let the rim of it fall behind a walker. What it
      // costs when nothing changed is 25 candidate cells and a map lookup
      // each; what it buys is that the set really is what the radius says.
      refreshCells();
    },
    tick(cam) {
      if (!lodCam) lodCam = new THREE.Vector3();
      lodCam.copy(cam);
      for (const layers of cells.values()) {
        for (const layer of layers) binLayer(layer, cam);
      }
    },
    dispose() {
      for (const key of [...cells.keys()]) dropCell(key);
      for (const mat of materials.values()) mat.dispose();
      materials.clear();
      geometry?.dispose();
      geometry = null;
      texture?.dispose();
      texture = null;
    },
  };
}
