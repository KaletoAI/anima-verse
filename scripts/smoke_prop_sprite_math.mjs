#!/usr/bin/env node
/**
 * Smoke run for the map editor's "Props from above" arithmetic —
 * `frontend/src/tabs/map/propSpriteMath.ts`: how big a top-down prop sprite
 * is drawn, how it is TURNED so that it faces the way the prop's direction
 * pin points, and which mesh URL a placement or a scatter instance shows.
 *
 * Usage:  node scripts/smoke_prop_sprite_math.mjs
 *
 * Same discipline as `scripts/smoke_scatter_preview.mjs`: every expected
 * number is derived BY HAND below and never recorded from the current output.
 * The rendering itself (WebGL) is not smoked — only the numbers the layer
 * feeds it and reads back from it.
 *
 * ============================================================================
 * (A) THE SIZE — `scale = target height / model height`
 * ============================================================================
 * `renderPropTopDown` measures the model's bounding box at scale 1 and hands
 * back (widthM, heightM, depthM). The layer scales UNIFORMLY until the box is
 * as tall as the entry says — the very law the 3D client plants a scatter
 * mesh by (`scatterTargetH` → `targetH / bbox height`).
 *
 * (A1) bbox 2 × 1 × 4 (w × h × d), `prop_height_m` 2:
 *        scale = 2 / 1 = 2   →   sprite 4 m × 8 m
 * (A2) the picture is SQUARE and holds max(w, d) plus 5 % margin, so its
 *      side at scale 1 is 4 · 1.05 = 4.2 m and, drawn, 4.2 · 2 = 8.4 m;
 *      at 10 px per metre that is 84 px — the w × d rectangle inside it is
 *      40 × 80 px.
 * (A3) the target height mirrors the client's `scatterTargetH` (Task 9,
 *      2026-09-10: the prop's own height, nothing authored on the row):
 *      `prop_height_m` 8 → 8; no prop record (undefined, 0, NaN) → the flat
 *      2 m fallback. There is no `height_m` argument any more — a row that
 *      still carries one in an old payload is not read.
 * (A4) junk is not a scale: a model with no height (0) scales by 0, so the
 *      layer draws nothing rather than a NaN-sized image.
 *
 * ============================================================================
 * (B) THE ROTATION — derived from the pin, not chosen
 * ============================================================================
 * THE SCREEN AXES (`mapMath.worldToScreen`, pinned on its source below):
 *
 *     sx = w/2 + (x − cx) · pxPerM        east  (+x) = right
 *     sy = h/2 + (z − cz) · pxPerM        south (+z) = DOWN
 *
 * THE PIN (`WorldPropLayer`, pinned on its source below): with
 * rad = yaw_deg · π / 180 the pin end is
 *
 *     fx = px − FACE_PX · sin(rad)
 *     fy = py − FACE_PX · cos(rad)
 *
 * i.e. the pin's screen direction is  d_pin(θ) = (−sin θ, −cos θ). In world
 * terms that is R_y(θ) · (0, 0, −1): the model's LOCAL −z, turned by the yaw
 * exactly as `placeModelSpec` turns it (`rotation.y = yaw`). So the pin shows
 * where local −z points.
 *
 * THE PICTURE: the renderer looks straight down with `up = −z`, as the roof
 * snapshots do — image top = local −z, image right = local +x. Unrotated, the
 * picture's "top" is the screen vector (0, −1).
 *
 * SVG `rotate(a)` on a y-down screen maps (x, y) → (x·cos a − y·sin a,
 * x·sin a + y·cos a), so the picture's top becomes (sin a, −cos a). It has
 * to equal d_pin(θ) = (−sin θ, −cos θ):
 *
 *     sin a = −sin θ  and  cos a = cos θ   ⇔   a = −θ
 *
 * Hence `rotate(−yaw_deg)` — the same sign the footprint squares of
 * `PlacementLayer` use for the same reason.
 *
 * (B1) yaw 90:   pin (−sin 90, −cos 90) = (−1, 0), LEFT;
 *                rotate(−90): (sin −90, −cos −90) = (−1, 0)   ✔
 * (B2) yaw 0:    pin (0, −1), UP; rotate(0) leaves the top up          ✔
 * (B3) yaw 180:  pin (0, 1), DOWN; rotate(−180): (0, −cos 180) = (0, 1) ✔
 * (B4) an odd angle, yaw 37: the two vectors agree to 1e-9 — the identity
 *      holds for every θ, not only the quarter turns.
 * (B5) the transform string the layer writes: translate first, then the
 *      rotation ABOUT that point — `translate(100 50) rotate(-90)`.
 *
 * ============================================================================
 * (C) THE MESH URL — the client's variant rule, mirrored
 * ============================================================================
 * `ground.ts readVariantMaps`: `model_variants` when the server ships a list,
 * else the one `variants` map, else `{}`; the primary variant falls back to
 * the authored `model` URL, the further ones do not (`pickVariant` picks the
 * `full` tier).
 *
 * (C1) a scatter entry with `model_variants` [A, B, C] and instance variant 1
 *      → B's full tier. Variant count 3.
 * (C2) the same entry, variant absent → A (position 0).
 * (C3) an entry with only `variants` → that map's full tier; count 1.
 * (C4) an entry with neither but a `model` → the authored URL; count 1.
 * (C5) an entry with nothing → '' (no sprite, a tuft has no mesh).
 * (C6) a WORLD PROP: position 0 is the bare model URL plus `?tier=full`;
 *      position 2 with store indices [0, 3, 5] is `?variant=5&tier=full` —
 *      the server's own URL rule (`world_props._prop_facts`, position 0 keeps
 *      the bare URL, every other position names its STORE index). `variant`
 *      null takes the server's `variant_auto`; a `missing` placement has no
 *      mesh at all.
 *
 * ============================================================================
 * (D) THE ANCHOR — origin for a scatter instance, box centre for a world prop
 * ============================================================================
 * The picture is centred on the model's BOX. A world prop hangs on that box
 * centre (`place()` recentres, `packages/scene-render/src/place.ts`), so its
 * picture sits on the placement point. A SCATTER instance stands the mesh on
 * its FILE ORIGIN (`ground.ts groundedGeometry` scales and lifts in y only),
 * so its picture's centre is the origin PLUS the box centre's offset, scaled
 * with the instance and turned by its yaw — the contract's own rotation
 * (`mapMath` header): x = lx·cos yaw + lz·sin yaw, z = −lx·sin yaw + lz·cos yaw.
 *
 * (D1) box centre (1, 0.5) at scale 1, scale 2, yaw 0:
 *        local (2, 1) → world shift (2, 1).
 * (D2) the same at yaw 90 (cos 0, sin 1):
 *        x = 2·0 + 1·1 = 1,  z = −2·1 + 1·0 = −2 → (1, −2).
 *      Check against the convention: local +z faces (sin 90, cos 90) = +x,
 *      and the local z-part (1) indeed lands on +x; local +x turns to −z.
 * (D3) yaw 180: (−2, −1) — the mirror of D1.
 * (D4) a WORLD PROP source (anchor 'centre') shifts by nothing, whatever
 *      the box says: (0, 0).
 */
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = fileURLToPath(new URL('..', import.meta.url));
const SRC = join(ROOT, 'frontend/src/tabs/map/propSpriteMath.ts');
const PIN_SRC = join(ROOT, 'frontend/src/tabs/map/WorldPropLayer.tsx');
const MATH_SRC = join(ROOT, 'frontend/src/tabs/map/mapMath.ts');

/** Bundled and imported — the module pulls in `@anima/scene-render`
 *  (`pickVariant`), which esbuild resolves and inlines. */
async function loadBundled(src, prefix) {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(tmpdir(), prefix));
  try {
    const file = join(dir, 'module.mjs');
    await esbuild.build({
      entryPoints: [src], outfile: file, bundle: true, format: 'esm',
      platform: 'neutral', logLevel: 'silent', absWorkingDir: ROOT,
    });
    return await import(`file://${file}`);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

let failed = 0;
let passed = 0;
function check(label, actual, expected) {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  if (ok) {
    passed += 1;
    console.log(`  ok   ${label}`);
  } else {
    failed += 1;
    console.log(`  FAIL ${label}\n       expected ${JSON.stringify(expected)}`
      + `\n       actual   ${JSON.stringify(actual)}`);
  }
}
const r9 = (v) => Math.round(v * 1e9) / 1e9 || 0;

async function main() {
  const m = await loadBundled(SRC, 'propsprite-');
  const {
    PROP_SPRITE_MAX, propSpriteFieldM, propSpriteScale, propSpriteSizeM,
    propSpriteRotateDeg, propSpriteTransform, propSpriteTargetH,
    propSpriteAnchorShift,
    scatterModelUrl, scatterVariantCount, worldPropModelUrl,
  } = m;

  console.log('(A) the size');
  const BOX = { widthM: 2, heightM: 1, depthM: 4 };
  check('A1 scale = 2 / 1 = 2', propSpriteScale(1, 2), 2);
  const size = propSpriteSizeM(BOX, 2);
  check('A1 sprite 4 m × 8 m', [size.widthM, size.depthM], [4, 8]);
  check('A2 field 4 · 1.05 = 4.2 m at scale 1', r9(propSpriteFieldM(2, 4)), 4.2);
  check('A2 …drawn 8.4 m, i.e. 84 px at 10 px/m',
    [r9(size.fieldM), r9(size.fieldM * 10)], [8.4, 84]);
  check('A2 …the rectangle inside it 40 × 80 px',
    [size.widthM * 10, size.depthM * 10], [40, 80]);
  check('A3 the prop\'s 8; without a prop record 2',
    [propSpriteTargetH(8), propSpriteTargetH(undefined),
      propSpriteTargetH(0), propSpriteTargetH(NaN)],
    [8, 2, 2, 2]);
  check('A3 …and it takes ONE argument: the row has no height of its own',
    propSpriteTargetH.length, 1);
  check('A4 a heightless model scales by 0, never NaN',
    [propSpriteScale(0, 2), propSpriteScale(NaN, 2),
      propSpriteSizeM({ widthM: 2, heightM: 0, depthM: 4 }, 2).fieldM],
    [0, 0, 0]);
  check('A budget constant is 2 000 sprites per render', PROP_SPRITE_MAX, 2000);

  console.log('(B) the rotation, against the pin');
  // THE PIN and THE AXES, pinned on their SOURCE TEXT — the formula is
  // referenced, not copied: if either line changes, this smoke goes red and
  // the derivation above has to be redone.
  const pinSrc = await readFile(PIN_SRC, 'utf8');
  const mathSrc = await readFile(MATH_SRC, 'utf8');
  check('B0 WorldPropLayer draws the pin at (px − F·sin, py − F·cos)',
    [pinSrc.includes('const fx = p.x - FACE_PX * Math.sin(rad)'),
      pinSrc.includes('const fy = p.y - FACE_PX * Math.cos(rad)'),
      pinSrc.includes('const rad = ((wp.yaw_deg || 0) * Math.PI) / 180')],
    [true, true, true]);
  check('B0 …and worldToScreen maps +x right, +z DOWN (no flip)',
    [mathSrc.includes('x: w / 2 + (x - view.cx) * view.pxPerM'),
      mathSrc.includes('y: h / 2 + (z - view.cz) * view.pxPerM')],
    [true, true]);
  // The pin's screen direction from that formula, and the picture's top after
  // the layer's rotate() — SVG's y-down rotation, written out.
  const pinDir = (yawDeg) => {
    const rad = (yawDeg * Math.PI) / 180;
    return [r9(-Math.sin(rad)), r9(-Math.cos(rad))];
  };
  const topAfter = (a) => {
    const rad = (a * Math.PI) / 180;
    const [x, y] = [0, -1];
    return [r9(x * Math.cos(rad) - y * Math.sin(rad)),
      r9(x * Math.sin(rad) + y * Math.cos(rad))];
  };
  check('B1 yaw 90 → rotate(−90); pin (−1, 0), picture top (−1, 0)',
    [propSpriteRotateDeg(90), pinDir(90), topAfter(propSpriteRotateDeg(90))],
    [-90, [-1, 0], [-1, 0]]);
  check('B2 yaw 0 → rotate(0); pin and top both (0, −1)',
    [propSpriteRotateDeg(0), pinDir(0), topAfter(propSpriteRotateDeg(0))],
    [0, [0, -1], [0, -1]]);
  check('B3 yaw 180 → rotate(−180); pin and top both (0, 1)',
    [propSpriteRotateDeg(180), pinDir(180), topAfter(propSpriteRotateDeg(180))],
    [-180, [0, 1], [0, 1]]);
  check('B4 yaw 37: the picture top IS the pin direction',
    topAfter(propSpriteRotateDeg(37)), pinDir(37));
  check('B5 the transform string: translate, then rotate about that point',
    propSpriteTransform(100, 50, 90), 'translate(100 50) rotate(-90)');
  check('B5 …junk yaw turns nothing', propSpriteTransform(1, 2, NaN),
    'translate(1 2) rotate(0)');

  console.log('(C) the mesh URL');
  const A = { full: '/assets/props/p1/model?tier=full', low: '/assets/props/p1/model?tier=low' };
  const B = { full: '/assets/props/p1/model?variant=3&tier=full' };
  const C = { full: '/assets/props/p1/model?variant=5&tier=full' };
  const listed = { density_per_100m2: 1, model: '/assets/props/p1/model',
    variants: A, model_variants: [A, B, C] };
  check('C1 variant 1 of [A, B, C] is B, count 3',
    [scatterModelUrl(listed, 1), scatterVariantCount(listed)], [B.full, 3]);
  check('C2 no variant is the primary A', scatterModelUrl(listed, undefined), A.full);
  check('C3 only `variants` → its full tier, count 1',
    [scatterModelUrl({ density_per_100m2: 1, model: '/x', variants: A }, 0),
      scatterVariantCount({ density_per_100m2: 1, variants: A })], [A.full, 1]);
  check('C4 neither → the authored model URL, count 1',
    [scatterModelUrl({ density_per_100m2: 1, model: '/assets/props/p1/model' }, 0),
      scatterVariantCount({ density_per_100m2: 1 })], ['/assets/props/p1/model', 1]);
  check('C5 nothing at all → no sprite', scatterModelUrl({ density_per_100m2: 1 }, 0), '');
  const wp = (over) => ({ id: 'w1', prop_id: 'p1', x: 0, z: 0, yaw_deg: 0, offset_y: 0,
    variant: null, variant_count: 3, variant_indices: [0, 3, 5], variant_auto: 0, ...over });
  check('C6 position 0 → the bare URL with the full tier',
    worldPropModelUrl(wp({ variant: 0 })), '/assets/props/p1/model?tier=full');
  check('C6 position 2 → store index 5', worldPropModelUrl(wp({ variant: 2 })),
    '/assets/props/p1/model?variant=5&tier=full');
  check('C6 null takes variant_auto (1 → store 3)',
    worldPropModelUrl(wp({ variant: null, variant_auto: 1 })),
    '/assets/props/p1/model?variant=3&tier=full');
  check('C6 a missing placement has no mesh', worldPropModelUrl(wp({ missing: true })), '');
  check('C6 a position past the list wraps (4 of 3 → 1 → store 3)',
    worldPropModelUrl(wp({ variant: 4 })), '/assets/props/p1/model?variant=3&tier=full');

  console.log('(D) the anchor');
  const shift = (yaw, anchor = 'origin') => {
    const v = propSpriteAnchorShift(1, 0.5, 2, yaw, anchor);
    return [r9(v.dx), r9(v.dz)];
  };
  check('D1 centre (1, 0.5) · scale 2, yaw 0 → shift (2, 1)', shift(0), [2, 1]);
  check('D2 yaw 90 → (1, −2): the local z-part lands on +x', shift(90), [1, -2]);
  check('D3 yaw 180 → (−2, −1)', shift(180), [-2, -1]);
  check('D4 a world prop (anchor centre) shifts by nothing', shift(90, 'centre'), [0, 0]);
  check('D4 …a centre that is not a number shifts by nothing; a junk yaw turns nothing',
    [(() => { const v = propSpriteAnchorShift(NaN, 0, 2, 0, 'origin'); return [v.dx, v.dz]; })(),
      shift(NaN)],
    [[0, 0], [2, 1]]);

  console.log(`\n${passed} ok, ${failed} failed`);
  process.exit(failed ? 1 : 0);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
