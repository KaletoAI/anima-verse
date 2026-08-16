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
 * THE LOOK IS A STAR OF QUADS, NOT CONES. The first build drew a five-sided
 * cone per tuft, which from eye level reads as "strange pointed cones coming
 * out of the ground" (the other half of the same finding). Crossed quads
 * carrying a procedurally generated blade texture with an alpha cut is what a
 * grass tuft is in every renderer that has one — and the texture is generated
 * here, from `undergrowthTexturePixels`, so it is a pure function of a size and
 * checkable by hand rather than an asset nobody can diff.
 *
 * THREE PLANES SINCE THE SIGHT ROUND OF 2026-08-16, not two, and the tuft is
 * 60 % of the size it was. Word for word: "one sees very much that it is
 * always a ROW of blades, and it lacks volume — the blades could be a little
 * smaller (60 %) and they should have different shades of colour." Two cards
 * seen from the side ARE a row: one of them is edge-on and the other is a flat
 * board. A third plane means no direction can catch fewer than two of them at
 * a useful angle, which is what "volume" means for a card tuft. The three
 * answers to that finding live in `undergrowthGeometry` (the star),
 * `UNDERGROWTH_H_MIN/MAX` in `scene/scatterLod.ts` (the size) and
 * `undergrowthTint` (the shades).
 *
 * THE AUTHORED SCATTER IS UNTOUCHED. `ground.ts` still grows the tuft cones of
 * `meta.scatter` exactly as before — those are what an author placed, and this
 * round is about the layer nobody placed.
 */
import * as THREE from 'three';
import { pointInRing, scatterInstances } from '@anima/scene-render';
import type { Point2, ScatterFootprint } from '@anima/scene-render';
import { applyOcclusionFade } from './occlusion';
import { instanceHash, UNDERGROWTH_CELL_M, UNDERGROWTH_CELL_RADIUS_M,
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

/** Edge of the generated texture in texels. 64 is what a shin-high tuft is
 *  worth on screen: at 60 m it is a pixel or two tall, at arm's length the
 *  blade edges are what one sees, and both are served by a mip chain that
 *  starts here. */
export const UNDERGROWTH_TEX_SIZE = 64;

/** How many blades one texture carries — raised from 7 with the density
 *  (2026-08-16): a fuller tuft is the second half of "a closed floor instead
 *  of separate bushes", because a denser field of THIN tufts still reads as a
 *  field of tufts. An ODD number, so the middle blade sits on the texture's
 *  centre line and the planes of the star do not read as a repeated pair.
 *
 *  NINE IS THE CEILING OF THE GEOMETRY, not a taste: a blade is
 *  `BLADE_HALF_W` wide at the root and antialiased over one further texel, so
 *  it covers 2 · (0.045 · 64 + 0.5) = 6.68 texels, against a root spacing of
 *  64/N. At N = 9 that spacing is 7.11 texels and the roots still stand APART
 *  — which is what keeps "the strongest blade wins" and "the summed width of
 *  the blades" the same picture (the row-ink property the smoke measures) and
 *  keeps the outermost blade inside the texture. At N = 11 (5.82) the roots
 *  would run into each other and the layer would need a thinner blade to go
 *  with it, which is a second knob for no visible gain. */
export const UNDERGROWTH_BLADES = 9;

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
 * an impression — it is 51.26 texels of ink in row 0 against 2.22 in row 46,
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

/** How wide a tuft is drawn, as a share of its height — a QUARTER wider than
 *  the 1.0 it was until 2026-08-16, so that a tuft keeps the proportions of a
 *  spreading clump rather than a single stalk.
 *
 *  IT IS A RATIO AND STAYS ONE, which is what made the 60 % size reduction of
 *  the sight round a single edit: the height span moved to 0.24 … 0.42 m and
 *  the absolute width followed by itself, from 0.69 m to 0.41 m at the
 *  reference height. What did NOT follow is the density (`scatterLod.ts`), so
 *  the neighbours 1.1 m apart no longer touch — see the note there; the volume
 *  now comes from the third plane below and not from the width of one tuft.
 *
 *  The texture spreads its nine blades over exactly this width: at the
 *  reference height that is a blade every 4.6 cm. */
const UNDERGROWTH_W_RATIO = 1.25;

/**
 * The three planes of one tuft, in DEGREES about +Y — a star, not a cross.
 *
 * TWO CARDS ARE A ROW SEEN FROM THE SIDE, and that is the finding this list
 * answers: with two planes there is always a direction that catches one of
 * them edge-on (invisible) and the other flat-on (a board), and a field of
 * them reads as rows of flat blades. A plane is edge-on exactly when the view
 * runs along it, so with the gaps below the WORST direction (straight along
 * one plane) still meets the other two at 55° and 63°, i.e. both of them show
 * sin 55° = 0.82 and sin 63° = 0.89 of their full width. There is no direction
 * left from which a tuft is a flat board, which is what "volume" means here.
 *
 * 0 / 55 / 118 AND NOT 0 / 60 / 120, for the reason the old pair was 80° and
 * not 90°: three planes at exactly 60° are symmetric under a third of a turn,
 * so a field of them shows the same silhouette from six directions and the eye
 * finds the grid. The uneven gaps (55°, 63°, 62°) cost nothing and break it —
 * and they are what the smoke's red counter-check measures, since a
 * fully symmetric star differs from this one only in the angle.
 */
const UNDERGROWTH_STAR_DEG = [0, 55, 118];

/** The alpha a texel needs to be drawn at all.
 *
 *  `alphaTest` AND NOT `transparent`, which is the whole reason the layer can
 *  be thousands of instances: an alpha-tested material stays in the OPAQUE
 *  pass, writes depth and needs no sorting, so a cell of a thousand tufts is
 *  one draw call whatever order they stand in. A transparent one would have to
 *  be sorted per frame and would still show the seams where the quads cross.
 *  0.35 sits below the antialiased edge of a blade (which reaches ~0.5 at the
 *  outermost covered texel) and well above the mip bleed between blades. */
export const UNDERGROWTH_ALPHA_TEST = 0.35;

/** How far a tuft reaches beyond the point it stands on, in metres — the
 *  tallest blade plus half the widest quad plus the wind's own maximum
 *  (`SWAY_MAX_M` in `ground.ts`, 0.5). Padding for the culling sphere only. */
const UNDERGROWTH_REACH_M = UNDERGROWTH_H_MAX
  + (UNDERGROWTH_H_MAX * UNDERGROWTH_W_RATIO) / 2 + 0.5;

/**
 * The star of quads of ONE tuft, base at y = 0 (B16), `h` tall and
 * `h · UNDERGROWTH_W_RATIO` wide.
 *
 * THREE cards, turned by `UNDERGROWTH_STAR_DEG` about +Y. All of them carry
 * the whole texture (0..1 in both UV axes), so a tuft is the same nine blades
 * seen from three directions rather than three different plants.
 *
 * WHAT THE THIRD PLANE COSTS, since it is fill rate and not draw calls: one
 * quad covers `h · 1.25 · h` of screen at a given distance, so the star is
 * 3/2 of the old pair's area at equal size — but the tuft shrank to 60 %, i.e.
 * 36 % of the area PER QUAD, and 3 · 0.36 / (2 · 1.00) = 0.54. The layer
 * therefore draws just over HALF the pixels it did before this round, at 1.5×
 * the vertex and index work (12 vertices and 36 indices per tuft against 8 and
 * 24, six drawn triangles after back-face culling against four).
 *
 * THE NORMALS POINT STRAIGHT UP, all twelve of them, and that is the one thing
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
 * AND THAT IS WHY EVERY CARD IS WOUND BOTH WAYS (36 indices over 12 vertices,
 * not 18). Both faces of a card have to be drawn — but three flips the normal
 * of a BACK face, so a single winding plus `DoubleSide` would give a tuft the
 * full 4.05 from one side and, with `N = (0, −1, 0)`, the hemisphere's GROUND
 * colour and no sun at all from the other: the same tuft would swing by a
 * factor of 2.6 as the camera orbits past it, which is worse than the even
 * gloom it replaced. The reversed triangles make both sides FRONT faces, so
 * the normal is never flipped and the material can stay `FrontSide`. It costs
 * eighteen indices and no vertices, and back-face culling still draws exactly
 * six triangles per tuft from any one direction.
 *
 * The forward windings come FIRST, all of them, and the reversed ones after —
 * so "the second half is the first half reversed" stays one assertion however
 * many planes the star has.
 */
export function undergrowthGeometry(h: number): THREE.BufferGeometry {
  const halfW = (h * UNDERGROWTH_W_RATIO) / 2;
  const pos: number[] = [];
  const uv: number[] = [];
  const normal: number[] = [];
  for (const deg of UNDERGROWTH_STAR_DEG) {
    // The card turned about +Y: its own +X axis is (cos, 0, −sin), so the
    // plane at 0° is the xy-plane and nothing is special about the first one.
    const c = Math.cos((deg * Math.PI) / 180);
    const s = Math.sin((deg * Math.PI) / 180);
    pos.push(-halfW * c, 0, halfW * s, halfW * c, 0, -halfW * s,
             halfW * c, h, -halfW * s, -halfW * c, h, halfW * s);
    uv.push(0, 0, 1, 0, 1, 1, 0, 1);
    for (let i = 0; i < 4; i += 1) normal.push(0, 1, 0);
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  geo.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2));
  geo.setAttribute('normal', new THREE.Float32BufferAttribute(normal, 3));
  const index: number[] = [];
  for (let q = 0; q < UNDERGROWTH_STAR_DEG.length; q += 1) {
    const v = q * 4;
    index.push(v, v + 1, v + 2, v, v + 2, v + 3);
  }
  // …and the same triangles wound the other way round, in the same order.
  // The bound is read ONCE: `index.length` grows with every push, and the
  // loop would otherwise reverse its own reversals for ever.
  const forward = index.length;
  for (let t = 0; t < forward; t += 3) {
    index.push(index[t], index[t + 2], index[t + 1]);
  }
  geo.setIndex(index);
  geo.computeBoundingSphere();
  return geo;
}

/* ==========================================================================
 * (3b) THE SHADE OF ONE TUFT — why a carpet of one colour reads as a texture
 *
 * "They should have different shades of colour" (sight round 2026-08-16). A
 * field of instances of ONE material is one colour to the last pixel, and at
 * the density of this layer that is what makes it read as a printed texture
 * rather than as growth: real grass is a hundred slightly different greens.
 *
 * THE MECHANISM IS `instanceColor`, three's own per-instance tint — one extra
 * vec3 attribute, no second material, no second draw call. In three 0.185 it
 * arrives through `color_vertex` (`vColor.rgb *= instanceColor.rgb` under
 * `USE_INSTANCING_COLOR`) and is applied in the fragment shader as
 * `diffuseColor *= vColor` (`WebGLProgram` defines `USE_COLOR` for the
 * fragment prefix whenever `instancingColor` is on). Neither chunk is anywhere
 * near the two anchors this file's patches replace — `applySway` inserts after
 * `begin_vertex`, `applyOcclusionFade` after `project_vertex` and before
 * `clipping_planes_fragment` — so the chain and the tint are independent, and
 * the shade is a MULTIPLIER on the material colour, not a replacement of it.
 * ========================================================================== */

/** How far the shade swings in brightness, as a share. ±12 % on the material
 *  colour, and it is worth naming that this is a LINEAR multiplier (the tint
 *  meets `diffuseColor`, which is in the working colour space): ±12 % of light
 *  is about ±5 % of an sRGB code value, i.e. deliberately a shading and not a
 *  patchwork. */
const SHADE_BRIGHT = 0.12;
/** …and how far it swings in hue, on the same scale: the red channel up and
 *  the blue down is a step towards yellow-green, the other way round is a step
 *  towards a deeper, colder green. Half the brightness swing, because a
 *  meadow's greens differ mostly in light and only a little in hue. */
const SHADE_HUE = 0.06;

/**
 * The two ends of the shade, as per-channel multipliers on the material
 * colour.
 *
 * THEY SUM TO EXACTLY (2, 2, 2), and that is the whole no-drift argument: the
 * mix parameter is a hash, i.e. uniform on [0, 1], so the MEAN tint over a
 * field is (A + B)/2 = (1, 1, 1) — the material colour itself, unchanged. Any
 * other pair (say a multiplicative brightness with a hue factor riding on top)
 * would leave a residue in the mean and the whole carpet would drift away from
 * the terrain kind's own green, which is the one thing this feature must not
 * do. Written as `1 ∓ (bright ± hue)` per channel so the sum is exact by
 * construction and not by rounding:
 *   A = (1 − 0.12 − 0.06, 1 − 0.12, 1 − 0.12 + 0.06) = (0.82, 0.88, 0.94)
 *   B = (1 + 0.12 + 0.06, 1 + 0.12, 1 + 0.12 − 0.06) = (1.18, 1.12, 1.06)
 * A is the darker, colder end and B the brighter, yellower one.
 */
export const UNDERGROWTH_TINT_A: readonly [number, number, number] = [
  1 - SHADE_BRIGHT - SHADE_HUE, 1 - SHADE_BRIGHT, 1 - SHADE_BRIGHT + SHADE_HUE,
];
export const UNDERGROWTH_TINT_B: readonly [number, number, number] = [
  1 + SHADE_BRIGHT + SHADE_HUE, 1 + SHADE_BRIGHT, 1 + SHADE_BRIGHT - SHADE_HUE,
];

/**
 * The shade of ONE tuft as a number in [0, 1) — hashed from WHERE IT STANDS.
 *
 * NOT FROM ITS INDEX, and that is not a matter of taste. The LOD thins the
 * layer by `instanceHash(index) < share` (`undergrowthVisible`), so a shade
 * keyed on the index would be perfectly correlated with the thinning: at
 * share 0.5 exactly the instances with hash < 0.5 survive, i.e. only the DARK
 * half of the palette would be left, and the carpet would visibly turn colour
 * between 30 m and 60 m. The position is independent of the index, so the
 * thinned-out field keeps the full spread of shades.
 *
 * A tuft also keeps its shade when its cell is dropped and rebuilt (the
 * position is the same), which is what stops the whole window from repainting
 * itself at a cell border.
 *
 * The coordinates are folded into one 32-bit key at CENTIMETRE resolution —
 * finer than any two tufts of this layer will ever stand apart — with the two
 * odd primes a spatial hash uses, and the mixing is `instanceHash`'s own
 * murmur3 finaliser. A junk coordinate gives the middle of the palette rather
 * than a NaN colour, for the reason `undergrowthHeight` gives the shortest
 * blade: an instance must never be removed by arithmetic.
 *
 * `Math.fround` FIRST, and it is not decoration: the position the instance
 * buffer carries is a float32, and a candidate whose centimetre rounding falls
 * within one ulp of a boundary (about one tuft in six hundred at these world
 * coordinates) would hash differently before and after that round trip. Keying
 * on the position AS STORED makes the shade re-derivable from the instance
 * buffer alone — which is exactly how the smoke measures it, at the consumer
 * rather than at the producer.
 */
export function undergrowthShade(x: number, z: number): number {
  const xv = Math.fround(Number(x));
  const zv = Math.fround(Number(z));
  if (!Number.isFinite(xv) || !Number.isFinite(zv)) return 0.5;
  const xi = Math.round(xv * 100) | 0;
  const zi = Math.round(zv * 100) | 0;
  return instanceHash((Math.imul(xi, 73856093) ^ Math.imul(zi, 19349663)) | 0);
}

/**
 * The per-channel multiplier of a tuft whose shade is `h` — a straight mix
 * between the two ends, so `h = 0` is A, `h = 1` is B and `h = 0.5` is exactly
 * the material colour.
 *
 * PLAIN RGB, no HSL round trip. A hue conversion per instance would be three
 * branches and a division inside the build loop of a few thousand tufts per
 * cell, for a difference nobody can see at ±6 % of one channel.
 */
export function undergrowthTint(h: number): [number, number, number] {
  const v = Number(h);
  const t = Number.isFinite(v) ? Math.min(Math.max(v, 0), 1) : 0.5;
  return [
    UNDERGROWTH_TINT_A[0] + (UNDERGROWTH_TINT_B[0] - UNDERGROWTH_TINT_A[0]) * t,
    UNDERGROWTH_TINT_A[1] + (UNDERGROWTH_TINT_B[1] - UNDERGROWTH_TINT_A[1]) * t,
    UNDERGROWTH_TINT_A[2] + (UNDERGROWTH_TINT_B[2] - UNDERGROWTH_TINT_A[2]) * t,
  ];
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
 * AND THE PER-TUFT SHADE RIDES ON TOP OF IT WITHOUT MOVING IT: `instanceColor`
 * multiplies this colour per instance, and the two ends of that mix sum to
 * exactly (2, 2, 2), so the MEAN over a field is this colour to the last bit
 * (`undergrowthTint`). The number above therefore still says what the layer
 * looks like as a whole.
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
  /** the per-tuft shade as built, 3 floats each — the SOURCE of
   *  `mesh.instanceColor`, and it exists for the same reason `srcMatrix` does.
   *  The binning COMPACTS the drawn instances into the front of the buffer, so
   *  a tuft's slot is not its index; a colour buffer left in index order would
   *  hand every tuft its neighbour's shade and repaint the whole carpet on
   *  every LOD tick. */
  srcColor: Float32Array;
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

  /** …and the same for the shade, which has to travel with the matrix into
   *  the same slot — see `CellLayer.srcColor`. */
  function copyColor(src: Float32Array, i: number,
                     dst: Float32Array, slot: number): void {
    const a = i * 3;
    const b = slot * 3;
    dst[b] = src[a];
    dst[b + 1] = src[a + 1];
    dst[b + 2] = src[a + 2];
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
     * hundred places would spend that two hundred times on each of ~2000
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
      const tint = new THREE.Color();
      const srcMatrix = new Float32Array(kept.length * 16);
      const srcColor = new Float32Array(kept.length * 3);
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
        // The shade of this tuft, hashed from where it stands and NOT from its
        // index — see `undergrowthShade`. `setColorAt` is what brings
        // `mesh.instanceColor` into existence at all; the values are written
        // into `srcColor` in the same pass, because from the first binning on
        // the buffer is filled by slot and no longer by index.
        // `setRGB` without a colour space writes the working space, i.e. the
        // multiplier reaches `diffuseColor` exactly as it is meant here.
        const [tr, tg, tb] = undergrowthTint(undergrowthShade(p.x, p.z));
        mesh.setColorAt(i, tint.setRGB(tr, tg, tb));
        srcColor[i * 3] = tr;
        srcColor[i * 3 + 1] = tg;
        srcColor[i * 3 + 2] = tb;
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
        srcColor,
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
    // The shade travels into the SAME slot as the matrix. `instanceColor` is
    // built by `setColorAt` in `buildCell` and is never null here; a layer
    // whose colours stayed in index order would give every drawn tuft the
    // shade of whichever tuft the compaction happened to displace, i.e. a
    // carpet that repaints itself once a second while the player walks.
    const colBuf = layer.mesh.instanceColor?.array as Float32Array | undefined;
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
        if (colBuf) copyColor(layer.srcColor, i, colBuf, n);
        n += 1;
      }
    }
    layer.mesh.count = n;
    layer.mesh.visible = n > 0;
    if (dirty) {
      layer.mesh.instanceMatrix.needsUpdate = true;
      if (layer.mesh.instanceColor) layer.mesh.instanceColor.needsUpdate = true;
    }
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
