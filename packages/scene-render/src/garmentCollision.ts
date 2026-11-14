/**
 * Garment collision — garment vertices pushed out of the body's collision
 * capsules after skinning, on the GPU (spec
 * `docs/superpowers/specs/2026-11-08-collision-capsules-design.md`, contract
 * `docs/schnittstellen-3d.md` "Collision capsules (`collision`)").
 *
 * WHAT IS PUSHED. Every SKINNED mesh inside a garment subtree (`inGarment`,
 * § A3a) — a dress or hair grafted onto the body — has its vertex shader patched:
 * after `skinning_vertex` the skinned position `transformed` (mesh-local
 * space) is pushed radially out of each capsule it lies inside, closest
 * point on the capsule axis outwards to the radius, in payload order, in
 * `COLLIDE_PASSES` passes. The body itself is never pushed. The optional
 * glTF vertex attribute `_COLLIDE` (three: `_collide`, 0..1) scales the
 * whole push of a vertex (`mix(p, pushed(p), w)`); absent = 1.
 *
 * WHICH CAPSULES. `garmentCapsules` decides per garment kind: hair the
 * torso, arm, head and hair-only chest capsules (`HAIR_REGIONS`), footwear none (a
 * rigid shoe is never pushed), every other kind all
 * but `CLOTH_EXCLUDED_REGIONS` (an arm passes through cloth; pushing the
 * cloth out of the arm drives it into the body — the numbers are on the
 * constants). At most `COLLIDE_MAX` per mesh, the FIRST ones in payload
 * order — deterministic: the server's table (18; its four partner-only
 * `outer_trunk` capsules push no garment, `PARTNER_ONLY_REGIONS`) comes
 * first, the extension capsules (one per chain bone, `app/core/collision.py`)
 * after it.
 *
 * BIND RULE (every garment). A vertex is never pushed further from a
 * capsule than it lay in the BIND pose: the radius is capped per vertex and
 * capsule at the vertex's bind distance (computed in the shader from the
 * unskinned `position` and the bind-pose capsule, `BoundCapsule.bind`). The
 * fit is authoritative where it put the garment: the push moves nothing in
 * the bind pose and only pushes what a pose drives deeper. Measured
 * (`scripts/check_garment_collision.mjs`, share moved > 1 mm in the bind
 * pose): Kira's HairDeck hair 6.65 % → 0 % (p99 17 mm, max 27 mm — card hair
 * rooted into the scalp under the head capsule, lying on the shoulders inside
 * the upper-arm caps); the S1 phase-5 dress 8.26 % → 0 % (p99 20 mm, max
 * 35 mm — the dress puffed out to the capsule radii in the rest pose). The
 * motion numbers stay the same (dress walk 1.22 / run 0.79 / sit 6.77 %,
 * hair celebrating 7.59 vs 7.57 %). It also covers the scalp under the head
 * capsule, so hair needs no Head-weight exclusion or height cut (an
 * exclusion of the head capsule alone, measured first, left the upper-arm
 * lift in place).
 *
 * SQUEEZE (hair only — plan R10, spec
 * `docs/superpowers/specs/2026-11-13-cross-person-collision-design.md` "Added
 * 2026-11-13 — squeeze rule"). The passes resolve one capsule after the
 * other, so a point squeezed between two (hair a raised upper arm presses
 * onto the chest) ends where the LAST applied capsule put it — inside the
 * other. A hair vertex (`#ifdef COLLIDE_SQUEEZE`, the define set for kind
 * hair) and a hair chain tip (`secondaryMotion.ts` `keepHairTipOutside`)
 * resolve them together (`PushOptions.squeeze`), radii capped by the bind
 * rule:
 *  1. S = the capsules containing p; none → p stays.
 *  2. Per round (at most `SQUEEZE_ROUNDS`): one capsule in round 1 → the
 *     exact radial push; otherwise N = unit(Σ n_i), n_i the unit vector from
 *     capsule i's closest axis point to the ORIGINAL p; |Σ n_i| <
 *     `SQUEEZE_MIN_N` (opposite normals) → the ordinary passes; the exit t by
 *     `SQUEEZE_STEPS` bisection steps on [0, 2·max r_S] for "p + tN outside
 *     every capsule of S" (2·max r_S not outside them all → the ordinary
 *     passes); q = p + t·N. q inside capsules not in S → they join S, next
 *     round; otherwise (or after the last round) q.
 *  3. Without `squeeze` (cloth, extension tips): the passes, unchanged.
 * SQUEEZE_MEASURED (2026-11-14, `scripts/check_garment_collision.mjs`, the
 * spec's case: a copy of Kira's draped hair model with its served-equivalent
 * payload, "celebrating" sample t = 18.525 s, static; `--no-squeeze` for
 * before): the hair vertices deeper than 5 mm beyond their bind depth (the
 * check's `excess`) 457 → 304 (0.85 → 0.57 % of the hair), their depth below
 * the skin p50/p90/max 12.3/26.7/52.5 → 11.5/31.2/52.5 mm (`excess_depth_mm`);
 * next to the chest_hair extension capsule 225 → 87, the Spine2 skin 179 →
 * 163, the arm 39 → 44. The other samples are unchanged; show-through at
 * t = 18.525 s 5.96 → 3.94 %. The rule moves a point out of the capsules
 * only: where their surfaces end inside the skin, a point outside every
 * capsule still counts as under the skin (the max did not move).
 *
 * PARTNERS (hair only — spec
 * `docs/superpowers/specs/2026-11-13-cross-person-collision-design.md`
 * Parts 2–3, plan Task 6). A hair mesh is also pushed out of OTHER figures'
 * capsules, so hair without swing (no hair group in the motion payload) keeps
 * out of a partner too. `setPartners` hands them in (world space); in each
 * hair mesh's render hooks the `PARTNER_COLLIDE_MAX` nearest to the mesh's
 * world bounding sphere (`nearestCapsules`; the geometry's sphere carried by
 * the joint with the most skin weight) go into the mesh's frame, a SECOND
 * uniform block (`partnerA/B`, `partnerCount`) under `#ifdef COLLIDE_PARTNER`
 * — only the count changes from frame to frame: no recompile. The rule:
 *  - no bind rule (a partner has no bind relation to this figure);
 *  - push only, faded per vertex (D7): d = the vertex's distance from the
 *    axis where the push starts, depth = r − d, f = clamp((1.5·M − depth) /
 *    (0.5·M), 0, 1) with M = `PARTNER_PUSH_MAX_M`, radius r' = d + depth·f
 *    (fixed for the vertex, so a second pass does not undo the fade); a push
 *    of more than 1.5·M is none — a partner driven deep through the hair
 *    leaves it inside rather than flipping it across;
 *  - in every pass the partner capsules come FIRST, the own ones after: the
 *    own body has the last word (a strand trapped between the two bodies ends
 *    on the partner's surface, never inside its own body);
 *  - the squeeze sets hold the partner capsules with f > 0 (r' = 0 otherwise)
 *    along with the own ones (`COLLIDE_GLSL_FUNCTION_SQUEEZE_PARTNER`).
 * No other garment kind uses the block: pushed out of a partner's limb, cloth
 * would be driven into its own body, pair clips author intended contact, and
 * the own set already fills its uniform budget (spec Part 2). The strand hair
 * gets the same capsules through `StrandHair.setPartners` (`hairSim.ts`).
 *
 * WHERE THE CAPSULES COME FROM. `bindCollision` (`collision.ts`, the ONE
 * endpoint rule) gives them in world space; per garment mesh they are taken
 * into that mesh's local space (`capsuleInFrame`, inverse `matrixWorld`) —
 * the space `transformed` is in after skinning, attached and detached bind
 * mode alike. The update runs in the garment mesh's `onBeforeShadow` /
 * `onBeforeRender`, i.e. inside `renderer.render` after
 * `scene.updateMatrixWorld` and the skeleton update — the bones it reads are
 * exactly the ones the shader skins with (no frame of lag), once per frame.
 *
 * ONE SOURCE. The push exists twice — `pushOutOfCapsules` (TypeScript; the
 * motion check `scripts/check_garment_collision.mjs` runs it) and
 * `COLLIDE_GLSL_FUNCTION` / `COLLIDE_GLSL_FUNCTION_SQUEEZE` /
 * `COLLIDE_GLSL_FUNCTION_SQUEEZE_PARTNER` (the shader). The GLSL is written in
 * scalar statements (the squeeze editions add local float arrays — two per
 * capsule list) so `scripts/smoke_garment_collision.mjs`,
 * `scripts/smoke_collision_squeeze.mjs` and
 * `scripts/smoke_partner_hair_push.mjs` can execute THAT string (a
 * mechanical GLSL→JS rewrite) and assert both give the same points; the
 * constants of both come from the exports here.
 *
 * SHADOWS. Each patched mesh gets its own `customDepthMaterial` /
 * `customDistanceMaterial` with the same patch and the SAME uniform objects,
 * so the shadow is cast by the pushed garment (three copies map, alphaTest,
 * side … onto a custom depth material itself at each shadow pass). An
 * alpha-tested garment (hair cards, glTF MASK) hands its map and cutoff to
 * both depth materials at creation as well, so they are right before the
 * first shadow pass and `applyAlphaCutoff` (materials.ts) finds them MASK.
 *
 * OWNERSHIP. Figures in the 3D client are `SkeletonUtils.clone`s that SHARE
 * their template's materials, but capsule uniforms are per figure — so every
 * patched material is a CLONE owned by this handle, and `dispose()` puts the
 * original materials and hooks back and frees exactly those clones (never a
 * shared template material, never a texture).
 *
 * EXCLUSION. `excludeMesh(mesh, true)` takes one patched mesh out of the
 * push for a while (its original materials back, no uniform update) and
 * `false` puts the same patched clones back — the strand hair, whose sim
 * collides by itself (strand-hair spec § 6.2.2).
 *
 * INERT. No collision payload, no capsule bound, or no skinned garment mesh
 * → `createGarmentCollision` returns null: nothing patched, no hook, no
 * per-frame work.
 *
 * `three` is injected, never imported.
 */
import type { Material, Object3D, SkinnedMesh, Texture, Vector4, WebGLProgramParametersWithUniforms } from 'three'
import { bindCollision, HAIR_ONLY_REGIONS, jointNowFrom, linearScale, PARTNER_ONLY_REGIONS, transformPoint } from './collision'
import type { BoundCapsule, CapsuleNow, CollisionBinding, CollisionPayload, Mat4, Vec3 } from './collision'
import { isGarmentNode } from './figure'
import { nearestCapsules, PARTNER_COLLIDE_MAX, PARTNER_PUSH_MAX_M } from './partnerContact'
import type { Sphere } from './partnerContact'

type Three = typeof import('three')

/**
 * Capsules one garment mesh's shader holds (uniform array length). Kept at
 * 16 with collision v2–v6: the most a kind selects today is cloth 8 (table
 * without the arms, the hair-only shoulders and the partner-only outer
 * trunk) + 2 chest + 5 links of one
 * chain = 15 — one chain's links are `attached_part` (built) or `appendage`
 * (drawn), the slot's switch picks the op — hair 3 + 4 + 1 +
 * 2 shoulder_hair + 2 chest_hair = 12, footwear 0. A body with more extension
 * links than fit keeps the FIRST in payload order (`garmentCapsules`) —
 * deterministic, the table's capsules never drop.
 */
export const COLLIDE_MAX = 16
/** Passes over all capsules (a vertex pushed out of one capsule into a neighbour is pushed again). */
export const COLLIDE_PASSES = 2
/** Squared axis length below which a capsule counts as a sphere around `a`. */
export const COLLIDE_EPS = 1e-12
/** A vertex this close to the axis has no outward direction and stays where it is. */
export const COLLIDE_MIN_D = 1e-6
/** SQUEEZE: rounds at most (a round's exit point inside further capsules adds them to S and runs again). */
export const SQUEEZE_ROUNDS = 3
/** SQUEEZE: bisection steps on [0, 2·max r_S] for the exit along the combined normal. */
export const SQUEEZE_STEPS = 16
/** SQUEEZE: a combined normal shorter than this (opposite normals) has no direction — the ordinary passes apply. */
export const SQUEEZE_MIN_N = 1e-3

/** The GLSL float literal of a number (always with a decimal point or exponent). */
function glslFloat(v: number): string {
  const s = String(v)
  return /[.e]/.test(s) ? s : `${s}.0`
}

/** `#define`s + uniforms (+ the optional weight attribute) — after `#include <common>`. */
export const COLLIDE_GLSL_DECLARATIONS = [
  `#define COLLIDE_MAX ${COLLIDE_MAX}`,
  `#define COLLIDE_PASSES ${COLLIDE_PASSES}`,
  `#define COLLIDE_EPS ${glslFloat(COLLIDE_EPS)}`,
  `#define COLLIDE_MIN_D ${glslFloat(COLLIDE_MIN_D)}`,
  'uniform vec4 collideA[ COLLIDE_MAX ];',
  'uniform vec4 collideB[ COLLIDE_MAX ];',
  'uniform vec4 collideBindA[ COLLIDE_MAX ];',
  'uniform vec4 collideBindB[ COLLIDE_MAX ];',
  'uniform int collideCount;',
  '#ifdef COLLIDE_WEIGHT',
  'attribute float _collide;',
  '#endif',
].join('\n')

/**
 * The partner block's `#define`s + uniforms (PARTNERS, module docstring) —
 * after `COLLIDE_GLSL_DECLARATIONS`, under `#ifdef COLLIDE_PARTNER`, only in a
 * patch made with `partner` (hair). `partnerB[i].w` is unused.
 */
export const COLLIDE_GLSL_PARTNER_DECLARATIONS = [
  '#ifdef COLLIDE_PARTNER',
  `#define PARTNER_COLLIDE_MAX ${PARTNER_COLLIDE_MAX}`,
  `#define COLLIDE_PARTNER_PUSH_MAX ${glslFloat(PARTNER_PUSH_MAX_M)}`,
  'uniform vec4 partnerA[ PARTNER_COLLIDE_MAX ];',
  'uniform vec4 partnerB[ PARTNER_COLLIDE_MAX ];',
  'uniform int partnerCount;',
  '#endif',
].join('\n')

/** One pass over the own list (scalar statements), bind rule included. */
const GLSL_PASS_OWN = `    for ( int i = 0; i < COLLIDE_MAX; i ++ ) {
      if ( i >= collideCount ) break;
      float ax = collideA[ i ].x;
      float ay = collideA[ i ].y;
      float az = collideA[ i ].z;
      float r = collideA[ i ].w;
      if ( collideBindA[ i ].w >= 0.0 ) {
        float bx = collideBindA[ i ].x;
        float by = collideBindA[ i ].y;
        float bz = collideBindA[ i ].z;
        float bbx = collideBindB[ i ].x - bx;
        float bby = collideBindB[ i ].y - by;
        float bbz = collideBindB[ i ].z - bz;
        float bpx = position.x - bx;
        float bpy = position.y - by;
        float bpz = position.z - bz;
        float bl2 = bbx * bbx + bby * bby + bbz * bbz;
        float bt = bl2 > COLLIDE_EPS ? clamp( ( bpx * bbx + bpy * bby + bpz * bbz ) / bl2, 0.0, 1.0 ) : 0.0;
        float ex = bpx - bbx * bt;
        float ey = bpy - bby * bt;
        float ez = bpz - bbz * bt;
        r = min( r, sqrt( ex * ex + ey * ey + ez * ez ) );
      }
      float abx = collideB[ i ].x - ax;
      float aby = collideB[ i ].y - ay;
      float abz = collideB[ i ].z - az;
      float apx = p.x - ax;
      float apy = p.y - ay;
      float apz = p.z - az;
      float len2 = abx * abx + aby * aby + abz * abz;
      float t = len2 > COLLIDE_EPS ? clamp( ( apx * abx + apy * aby + apz * abz ) / len2, 0.0, 1.0 ) : 0.0;
      float dx = apx - abx * t;
      float dy = apy - aby * t;
      float dz = apz - abz * t;
      float d = sqrt( dx * dx + dy * dy + dz * dz );
      if ( d < r && d > COLLIDE_MIN_D ) {
        float k = r / d - 1.0;
        p.x += dx * k;
        p.y += dy * k;
        p.z += dz * k;
      }
    }
`

/** The ordinary passes (scalar statements): the body of the plain edition of `collidePush`, the squeeze one's fallback. */
const COLLIDE_GLSL_PASSES = `  for ( int it = 0; it < COLLIDE_PASSES; it ++ ) {
${GLSL_PASS_OWN}  }
`

/**
 * THE PUSH, shader edition. Capsule i: axis `collideA[i].xyz` →
 * `collideB[i].xyz`, radius `collideA[i].w`, all in mesh-local space.
 * BIND RULE (`collideBindA[i].w` ≥ 0): the same capsule in the BIND pose,
 * `collideBindA[i].xyz` → `collideBindB[i].xyz` in the mesh's geometry
 * space; the vertex's bind distance `d0` to it (from the unskinned
 * `position`) caps the radius — `rr = min(r, d0)`: the vertex is pushed back
 * to where it lay from that capsule in the bind pose, never further. What
 * the fit put inside a capsule (hair on the scalp, on the shoulders) stays
 * where it is; only what the pose drives deeper is pushed (module docstring).
 * Scalar statements on purpose (see "ONE SOURCE" above) — keep it that way.
 */
export const COLLIDE_GLSL_FUNCTION = `
vec3 collidePush( vec3 p ) {
${COLLIDE_GLSL_PASSES}  return p;
}
`

/**
 * One capsule list of the shader: its uniforms, length (define), count
 * (uniform) and — in the squeeze editions — its local arrays of membership in
 * S and of the effective radius. The own list (`collide*`) and the partner
 * list (`partner*`, `#ifdef COLLIDE_PARTNER`).
 */
interface GlslList { A: string; B: string; max: string; count: string; inS: string; r: string }
const GLSL_OWN: GlslList = { A: 'collideA', B: 'collideB', max: 'COLLIDE_MAX', count: 'collideCount', inS: 'sIn', r: 'sr' }
const GLSL_PARTNER: GlslList = {
  A: 'partnerA', B: 'partnerB', max: 'PARTNER_COLLIDE_MAX', count: 'partnerCount', inS: 'pIn', r: 'pr',
}

/** GLSL statements: (dx, dy, dz) = point (x, y, z) minus capsule `i`'s closest axis point, `d` its length. */
function glslAxisOffset(x: string, y: string, z: string, pad: string, list: GlslList = GLSL_OWN): string {
  return [
    `float ax = ${list.A}[ i ].x;`,
    `float ay = ${list.A}[ i ].y;`,
    `float az = ${list.A}[ i ].z;`,
    `float abx = ${list.B}[ i ].x - ax;`,
    `float aby = ${list.B}[ i ].y - ay;`,
    `float abz = ${list.B}[ i ].z - az;`,
    `float apx = ${x} - ax;`,
    `float apy = ${y} - ay;`,
    `float apz = ${z} - az;`,
    'float len2 = abx * abx + aby * aby + abz * abz;',
    'float t = len2 > COLLIDE_EPS ? clamp( ( apx * abx + apy * aby + apz * abz ) / len2, 0.0, 1.0 ) : 0.0;',
    'float dx = apx - abx * t;',
    'float dy = apy - aby * t;',
    'float dz = apz - abz * t;',
    'float d = sqrt( dx * dx + dy * dy + dz * dz );',
  ].map(line => pad + line).join('\n')
}

/**
 * THE PUSH, shader edition WITH the SQUEEZE rule (module docstring) — the
 * same function name and signature as `COLLIDE_GLSL_FUNCTION`; the patch
 * compiles it under `#ifdef COLLIDE_SQUEEZE` (hair only). S (`sIn`) = the
 * capsules `p` lies inside, radii capped by the bind rule (`sr`); a point in
 * none stays and skips the passes. Each round (`SQUEEZE_ROUNDS`): one capsule
 * in round 1 → the exact radial push; otherwise along N = unit(Σ n_i) (n_i
 * from capsule i's closest axis point to the ORIGINAL `p`), the exit `hi`
 * found by `SQUEEZE_STEPS` bisection steps on [0, 2·max r_S] (step 0 tests
 * `hi` itself). |Σ n_i| < `SQUEEZE_MIN_N` or 2·max r_S not outside them all
 * → `fail`: `p` untouched, the ordinary passes run. The exit point inside
 * capsules not in S → they join S, next round; otherwise (or after the last
 * round) it is the result. Scalar statements plus two local float arrays —
 * `scripts/smoke_collision_squeeze.mjs` executes this string.
 */
/**
 * One GLSL `for` over a capsule list per entry of `lists` (in that order),
 * the body written by `body` for that list (lines ending in a newline).
 */
function glslEach(lists: readonly GlslList[], pad: string, body: (list: GlslList) => string): string {
  return lists.map(L => `${pad}for ( int i = 0; i < ${L.max}; i ++ ) {\n${pad}  if ( i >= ${L.count} ) break;\n${body(L)}${pad}}\n`)
    .join('')
}

/** The squeeze set's setup of the own list: the radius capped by the bind rule (`sr`), membership in S (`sIn`). */
const GLSL_SETUP_OWN = `    float r = collideA[ i ].w;
    if ( collideBindA[ i ].w >= 0.0 ) {
      float bx = collideBindA[ i ].x;
      float by = collideBindA[ i ].y;
      float bz = collideBindA[ i ].z;
      float bbx = collideBindB[ i ].x - bx;
      float bby = collideBindB[ i ].y - by;
      float bbz = collideBindB[ i ].z - bz;
      float bpx = position.x - bx;
      float bpy = position.y - by;
      float bpz = position.z - bz;
      float bl2 = bbx * bbx + bby * bby + bbz * bbz;
      float bt = bl2 > COLLIDE_EPS ? clamp( ( bpx * bbx + bpy * bby + bpz * bbz ) / bl2, 0.0, 1.0 ) : 0.0;
      float ex = bpx - bbx * bt;
      float ey = bpy - bby * bt;
      float ez = bpz - bbz * bt;
      r = min( r, sqrt( ex * ex + ey * ey + ez * ez ) );
    }
    sr[ i ] = r;
${glslAxisOffset('p.x', 'p.y', 'p.z', '    ')}
    sIn[ i ] = d < r ? 1.0 : 0.0;
    sCount += sIn[ i ];
`

/**
 * The squeeze set's setup of the partner list (PARTNERS, module docstring):
 * no bind rule; the radius from the point the push starts with — depth
 * = r − d, f = clamp((1.5·M − depth) / (0.5·M), 0, 1), r' = d + depth·f
 * (`pr`), 0 when f = 0 (the capsule is left out); membership in S (`pIn`).
 */
const GLSL_SETUP_PARTNER = `${glslAxisOffset('p.x', 'p.y', 'p.z', '    ', GLSL_PARTNER)}
    float depth = partnerA[ i ].w - d;
    float f = clamp( ( 1.5 * COLLIDE_PARTNER_PUSH_MAX - depth ) / ( 0.5 * COLLIDE_PARTNER_PUSH_MAX ), 0.0, 1.0 );
    float r = f > 0.0 ? d + depth * f : 0.0;
    pr[ i ] = r;
    pIn[ i ] = d < r ? 1.0 : 0.0;
    sCount += pIn[ i ];
`

/** One pass over the partner list with its fixed radii `pr` (the partner edition's passes run it before the own list). */
const GLSL_PASS_PARTNER = `    for ( int i = 0; i < PARTNER_COLLIDE_MAX; i ++ ) {
      if ( i >= partnerCount ) break;
${glslAxisOffset('p.x', 'p.y', 'p.z', '      ', GLSL_PARTNER)}
      if ( d < pr[ i ] && d > COLLIDE_MIN_D ) {
        float k = pr[ i ] / d - 1.0;
        p.x += dx * k;
        p.y += dy * k;
        p.z += dz * k;
      }
    }
`

/** The squeeze edition over `lists` (own; partner + own), with `passes` as its fallback (module docstring). */
function glslSqueezeFunction(lists: readonly GlslList[], passes: string): string {
  const setup = (L: GlslList) => (L === GLSL_PARTNER ? GLSL_SETUP_PARTNER : GLSL_SETUP_OWN)
  const arrays = lists.map(L => `  float ${L.r}[ ${L.max} ];\n  float ${L.inS}[ ${L.max} ];\n`).join('')
  return `
vec3 collidePush( vec3 p ) {
${arrays}  float sCount = 0.0;
${glslEach(lists, '  ', setup)}  float sDone = sCount < 0.5 ? 1.0 : 0.0;
  float qx = p.x;
  float qy = p.y;
  float qz = p.z;
  for ( int k = 0; k < SQUEEZE_ROUNDS; k ++ ) {
    if ( sDone > 0.5 ) break;
    float fail = 0.0;
    if ( k == 0 && sCount < 1.5 ) {
${glslEach(lists, '      ', L => `        if ( ${L.inS}[ i ] > 0.5 ) {
${glslAxisOffset('p.x', 'p.y', 'p.z', '          ', L)}
          if ( d > COLLIDE_MIN_D ) {
            float kk = ${L.r}[ i ] / d - 1.0;
            qx = p.x + dx * kk;
            qy = p.y + dy * kk;
            qz = p.z + dz * kk;
          }
        }
`)}    } else {
      float nx = 0.0;
      float ny = 0.0;
      float nz = 0.0;
      float rMax = 0.0;
${glslEach(lists, '      ', L => `        if ( ${L.inS}[ i ] > 0.5 ) {
${glslAxisOffset('p.x', 'p.y', 'p.z', '          ', L)}
          if ( d > COLLIDE_MIN_D ) {
            nx += dx / d;
            ny += dy / d;
            nz += dz / d;
          }
          rMax = ${L.r}[ i ] > rMax ? ${L.r}[ i ] : rMax;
        }
`)}      float nl = sqrt( nx * nx + ny * ny + nz * nz );
      if ( nl < SQUEEZE_MIN_N ) {
        fail = 1.0;
      } else {
        nx = nx / nl;
        ny = ny / nl;
        nz = nz / nl;
        float lo = 0.0;
        float hi = 2.0 * rMax;
        for ( int s = 0; s <= SQUEEZE_STEPS; s ++ ) {
          float tt = s == 0 ? hi : 0.5 * ( lo + hi );
          float ox = p.x + nx * tt;
          float oy = p.y + ny * tt;
          float oz = p.z + nz * tt;
          float clear = 1.0;
${glslEach(lists, '          ', L => `            if ( ${L.inS}[ i ] > 0.5 ) {
${glslAxisOffset('ox', 'oy', 'oz', '              ', L)}
              if ( d < ${L.r}[ i ] ) clear = 0.0;
            }
`)}          if ( s == 0 ) {
            if ( clear < 0.5 ) {
              fail = 1.0;
              break;
            }
          } else if ( clear > 0.5 ) {
            hi = tt;
          } else {
            lo = tt;
          }
        }
        qx = p.x + nx * hi;
        qy = p.y + ny * hi;
        qz = p.z + nz * hi;
      }
    }
    if ( fail > 0.5 ) break;
    float added = 0.0;
${glslEach(lists, '    ', L => `      if ( ${L.inS}[ i ] < 0.5 ) {
${glslAxisOffset('qx', 'qy', 'qz', '        ', L)}
        if ( d < ${L.r}[ i ] ) {
          ${L.inS}[ i ] = 1.0;
          added += 1.0;
        }
      }
`)}    sCount += added;
    if ( added < 0.5 || k == SQUEEZE_ROUNDS - 1 ) sDone = 1.0;
  }
  if ( sDone > 0.5 ) {
    p.x = qx;
    p.y = qy;
    p.z = qz;
  } else {
${passes}  }
  return p;
}
`
}

/**
 * THE PUSH, shader edition WITH the SQUEEZE rule (module docstring) — the
 * same function name and signature as `COLLIDE_GLSL_FUNCTION`; the patch
 * compiles it under `#ifdef COLLIDE_SQUEEZE` (hair only). S (`sIn`) = the
 * capsules `p` lies inside, radii capped by the bind rule (`sr`); a point in
 * none stays and skips the passes. Each round (`SQUEEZE_ROUNDS`): one capsule
 * in round 1 → the exact radial push; otherwise along N = unit(Σ n_i) (n_i
 * from capsule i's closest axis point to the ORIGINAL `p`), the exit `hi`
 * found by `SQUEEZE_STEPS` bisection steps on [0, 2·max r_S] (step 0 tests
 * `hi` itself). |Σ n_i| < `SQUEEZE_MIN_N` or 2·max r_S not outside them all
 * → `fail`: `p` untouched, the ordinary passes run. The exit point inside
 * capsules not in S → they join S, next round; otherwise (or after the last
 * round) it is the result. Scalar statements plus two local float arrays —
 * `scripts/smoke_collision_squeeze.mjs` executes this string.
 */
export const COLLIDE_GLSL_FUNCTION_SQUEEZE = glslSqueezeFunction([GLSL_OWN], COLLIDE_GLSL_PASSES)

/**
 * THE PUSH, shader edition with the SQUEEZE rule AND the partner block
 * (PARTNERS, module docstring) — compiled under `#ifdef COLLIDE_PARTNER`
 * inside the squeeze block (hair only). The same steps as
 * `COLLIDE_GLSL_FUNCTION_SQUEEZE` over two lists, the partner capsules
 * (`partnerA/B`, `partnerCount`; radius `pr` faded by the required push,
 * no bind rule) before the own ones in every loop — S holds both, the
 * fallback passes push out of the partner capsules first, then out of the
 * own ones. `partnerCount` 0 gives the squeeze edition's points.
 * `scripts/smoke_partner_hair_push.mjs` and `smoke_garment_collision.mjs`
 * execute this string.
 */
export const COLLIDE_GLSL_FUNCTION_SQUEEZE_PARTNER = glslSqueezeFunction([GLSL_PARTNER, GLSL_OWN],
  `  for ( int it = 0; it < COLLIDE_PASSES; it ++ ) {
${GLSL_PASS_PARTNER}${GLSL_PASS_OWN}  }
`)

/** The call — after `#include <skinning_vertex>` (and before displacement / projection). */
export const COLLIDE_GLSL_APPLY = `
#ifdef COLLIDE_WEIGHT
  transformed = mix( transformed, collidePush( transformed ), clamp( _collide, 0.0, 1.0 ) );
#else
  transformed = collidePush( transformed );
#endif
`

/**
 * A capsule as the shader holds it: mesh-local now (`a`, `b`, `r`), plus —
 * under the BIND RULE — the same capsule in the bind pose in the mesh's
 * geometry space (`bind`; absent = no bind rule, `collideBindA[i].w` = −1).
 */
export interface CollideCapsule extends CapsuleNow { bind?: { a: Vec3; b: Vec3 } }

/** Distance from `p` to the segment a→b (a == b: to the point). */
function segmentDistance(p: Vec3, a: Vec3, b: Vec3): number {
  const abx = b[0] - a[0], aby = b[1] - a[1], abz = b[2] - a[2]
  const apx = p[0] - a[0], apy = p[1] - a[1], apz = p[2] - a[2]
  const len2 = abx * abx + aby * aby + abz * abz
  const t = len2 > COLLIDE_EPS ? Math.min(1, Math.max(0, (apx * abx + apy * aby + apz * abz) / len2)) : 0
  return Math.hypot(apx - abx * t, apy - aby * t, apz - abz * t)
}

/** Options of `pushOutOfCapsules`. */
export interface PushOptions {
  /**
   * The SQUEEZE rule (module docstring; hair only, plan R10): a point inside
   * several capsules leaves along their combined normal instead of the
   * ordinary passes' "last applied capsule wins". Absent = the ordinary passes.
   */
  squeeze?: boolean
  /**
   * Other figures' capsules (PARTNERS, module docstring; the space of `p`):
   * no bind rule, each radius faded by the push it requires (D7 — r' =
   * d + (r − d)·f, f = clamp((1.5·M − (r − d)) / (0.5·M), 0, 1), M =
   * `PARTNER_PUSH_MAX_M`, d from the starting point), applied BEFORE the own
   * capsules in every pass and part of the squeeze sets. The first
   * `PARTNER_COLLIDE_MAX` are used, as the shader's uniform block holds them:
   * order them nearest first (`nearestCapsules`) so a cut drops the farthest.
   * Absent or empty = the push without partners, bit for bit.
   */
  partners?: readonly CapsuleNow[]
}

/** (dx, dy, dz, d) of `p` from capsule `c`'s closest axis point — the shader's arithmetic, step for step. */
function axisOffset(x: number, y: number, z: number, c: CapsuleNow, out: Float64Array): Float64Array {
  const ax = c.a[0], ay = c.a[1], az = c.a[2]
  const abx = c.b[0] - ax, aby = c.b[1] - ay, abz = c.b[2] - az
  const apx = x - ax, apy = y - ay, apz = z - az
  const len2 = abx * abx + aby * aby + abz * abz
  const t = len2 > COLLIDE_EPS ? Math.min(1, Math.max(0, (apx * abx + apy * aby + apz * abz) / len2)) : 0
  const dx = apx - abx * t, dy = apy - aby * t, dz = apz - abz * t
  out[0] = dx; out[1] = dy; out[2] = dz; out[3] = Math.sqrt(dx * dx + dy * dy + dz * dz)
  return out
}

/**
 * A partner capsule's radius for the point `p` the push starts with (D7,
 * `GLSL_SETUP_PARTNER` step for step): depth = r − d, f = clamp((1.5·M −
 * depth) / (0.5·M), 0, 1), r' = d + depth·f; 0 when f = 0 (left out).
 */
function partnerRadius(p: Vec3, c: CapsuleNow, off: Float64Array): number {
  const d = axisOffset(p[0], p[1], p[2], c, off)[3]
  const depth = c.r - d
  const f = Math.min(1, Math.max(0, (1.5 * PARTNER_PUSH_MAX_M - depth) / (0.5 * PARTNER_PUSH_MAX_M)))
  return f > 0 ? d + depth * f : 0
}

/** The ordinary passes: `COLLIDE_PASSES` passes over the capsules in payload order (`COLLIDE_GLSL_PASSES`). */
function ordinaryPasses(p: Vec3, capsules: readonly CollideCapsule[], radii: readonly number[]): Vec3 {
  let x = p[0], y = p[1], z = p[2]
  const n = radii.length
  for (let it = 0; it < COLLIDE_PASSES; it++) {
    for (let i = 0; i < n; i++) {
      const { a, b } = capsules[i]
      const r = radii[i]
      const abx = b[0] - a[0], aby = b[1] - a[1], abz = b[2] - a[2]
      const apx = x - a[0], apy = y - a[1], apz = z - a[2]
      const len2 = abx * abx + aby * aby + abz * abz
      const t = len2 > COLLIDE_EPS ? Math.min(1, Math.max(0, (apx * abx + apy * aby + apz * abz) / len2)) : 0
      const dx = apx - abx * t, dy = apy - aby * t, dz = apz - abz * t
      const d = Math.sqrt(dx * dx + dy * dy + dz * dz)
      if (d < r && d > COLLIDE_MIN_D) {
        const k = r / d - 1
        x += dx * k; y += dy * k; z += dz * k
      }
    }
  }
  return [x, y, z]
}

/**
 * The SQUEEZE rule (`COLLIDE_GLSL_FUNCTION_SQUEEZE`, the same steps): the
 * squeezed point, or null when the ordinary passes apply (|Σ n_i| below
 * `SQUEEZE_MIN_N`, or 2·max r_S not outside every capsule of S).
 */
function squeezeOut(p: Vec3, capsules: readonly CollideCapsule[], radii: readonly number[]): Vec3 | null {
  const n = radii.length
  const off = new Float64Array(4)
  const inS = new Uint8Array(n)
  let count = 0
  for (let i = 0; i < n; i++) {
    if (axisOffset(p[0], p[1], p[2], capsules[i], off)[3] < radii[i]) { inS[i] = 1; count++ }
  }
  if (!count) return [p[0], p[1], p[2]]
  let qx = p[0], qy = p[1], qz = p[2]
  for (let k = 0; k < SQUEEZE_ROUNDS; k++) {
    if (k === 0 && count === 1) {
      // the exact radial push out of the one capsule
      for (let i = 0; i < n; i++) {
        if (!inS[i]) continue
        const [dx, dy, dz, d] = axisOffset(p[0], p[1], p[2], capsules[i], off)
        if (d > COLLIDE_MIN_D) {
          const kk = radii[i] / d - 1
          qx = p[0] + dx * kk; qy = p[1] + dy * kk; qz = p[2] + dz * kk
        }
      }
    } else {
      let nx = 0, ny = 0, nz = 0, rMax = 0
      for (let i = 0; i < n; i++) {
        if (!inS[i]) continue
        const [dx, dy, dz, d] = axisOffset(p[0], p[1], p[2], capsules[i], off)
        if (d > COLLIDE_MIN_D) { nx += dx / d; ny += dy / d; nz += dz / d }
        rMax = radii[i] > rMax ? radii[i] : rMax
      }
      const nl = Math.sqrt(nx * nx + ny * ny + nz * nz)
      if (nl < SQUEEZE_MIN_N) return null
      nx = nx / nl; ny = ny / nl; nz = nz / nl
      let lo = 0, hi = 2 * rMax
      for (let s = 0; s <= SQUEEZE_STEPS; s++) {
        const tt = s === 0 ? hi : 0.5 * (lo + hi)
        const ox = p[0] + nx * tt, oy = p[1] + ny * tt, oz = p[2] + nz * tt
        let clear = true
        for (let i = 0; i < n; i++) {
          if (inS[i] && axisOffset(ox, oy, oz, capsules[i], off)[3] < radii[i]) clear = false
        }
        if (s === 0) { if (!clear) return null }
        else if (clear) hi = tt
        else lo = tt
      }
      qx = p[0] + nx * hi; qy = p[1] + ny * hi; qz = p[2] + nz * hi
    }
    let added = 0
    for (let i = 0; i < n; i++) {
      if (!inS[i] && axisOffset(qx, qy, qz, capsules[i], off)[3] < radii[i]) { inS[i] = 1; added++ }
    }
    count += added
    if (!added || k === SQUEEZE_ROUNDS - 1) break
  }
  return [qx, qy, qz]
}

/**
 * THE PUSH, TypeScript edition — the same steps as `COLLIDE_GLSL_FUNCTION`
 * (the smoke runs both): `p` pushed out of the first `COLLIDE_MAX` capsules,
 * `COLLIDE_PASSES` passes, then `weight` (0..1, the `_COLLIDE` value) blends
 * between the original and the pushed point. Capsules and point in one space;
 * `bindP` = the vertex's unskinned position (geometry space) for the BIND
 * RULE of a capsule carrying `bind` (radius capped at the bind distance;
 * without `bindP` the rule is not applied). `options.squeeze` = the SQUEEZE
 * rule first (`COLLIDE_GLSL_FUNCTION_SQUEEZE`, module docstring), the
 * passes only where it does not apply; without it the passes alone.
 * `options.partners` = the first `PARTNER_COLLIDE_MAX` partner capsules
 * (PARTNERS, module docstring) ahead of the own ones in every pass and
 * squeeze set — with `squeeze` the twin of `COLLIDE_GLSL_FUNCTION_SQUEEZE_PARTNER`.
 */
export function pushOutOfCapsules(p: Vec3, capsules: readonly CollideCapsule[], weight = 1, bindP?: Vec3,
  options?: PushOptions): Vec3 {
  const n = Math.min(capsules.length, COLLIDE_MAX)
  let used: readonly CollideCapsule[] = capsules
  let radii = capsules.slice(0, n).map(c => (c.bind && bindP ? Math.min(c.r, segmentDistance(bindP, c.bind.a, c.bind.b)) : c.r))
  const partners = options?.partners?.length ? options.partners.slice(0, PARTNER_COLLIDE_MAX) : null
  if (partners) {
    // One list, partners first — the shader runs the partner loop before the own one everywhere.
    const off = new Float64Array(4)
    used = [...partners, ...capsules.slice(0, n)]
    radii = [...partners.map(c => partnerRadius(p, c, off)), ...radii]
  }
  const [x, y, z] = (options?.squeeze ? squeezeOut(p, used, radii) : null) ?? ordinaryPasses(p, used, radii)
  const w = Math.min(1, Math.max(0, weight))
  return [p[0] + (x - p[0]) * w, p[1] + (y - p[1]) * w, p[2] + (z - p[2]) * w]
}

/** A capsule taken through `m` (e.g. world → mesh-local): endpoints transformed, radius × `m`'s scale. */
export function capsuleInFrame(capsule: CapsuleNow, m: Mat4): CapsuleNow {
  return { a: transformPoint(m, capsule.a), b: transformPoint(m, capsule.b), r: capsule.r * linearScale(m) }
}

/**
 * The push's function block of the patch: the plain edition, or — `squeeze`
 * (hair) — the squeeze edition with its constants under
 * `#ifdef COLLIDE_SQUEEZE` (the material's define) and the plain one under
 * `#else`. Without `squeeze` the block names no `COLLIDE_SQUEEZE` at all.
 * `partner` (with `squeeze`; hair) puts the partner edition under
 * `#ifdef COLLIDE_PARTNER` inside the squeeze block, the squeeze edition under
 * its `#else`; without it nothing names `COLLIDE_PARTNER`.
 */
function collideFunctionBlock(squeeze: boolean, partner: boolean): string {
  if (!squeeze) return COLLIDE_GLSL_FUNCTION
  const edition = partner
    ? ['#ifdef COLLIDE_PARTNER', COLLIDE_GLSL_FUNCTION_SQUEEZE_PARTNER, '#else', COLLIDE_GLSL_FUNCTION_SQUEEZE, '#endif']
    : [COLLIDE_GLSL_FUNCTION_SQUEEZE]
  return [
    '#ifdef COLLIDE_SQUEEZE',
    `#define SQUEEZE_ROUNDS ${SQUEEZE_ROUNDS}`,
    `#define SQUEEZE_STEPS ${SQUEEZE_STEPS}`,
    `#define SQUEEZE_MIN_N ${glslFloat(SQUEEZE_MIN_N)}`,
    ...edition,
    '#else',
    COLLIDE_GLSL_FUNCTION,
    '#endif',
  ].join('\n')
}

/**
 * Patch a vertex shader source (idempotent): declarations after `common`, the push after `skinning_vertex`;
 * `squeeze` (hair) brings the SQUEEZE edition of the push, `partner` (with `squeeze`; hair) the partner
 * declarations and edition (`collideFunctionBlock`). `partner` without `squeeze` is ignored — only the squeeze
 * block has a partner edition, and hair, the one kind with partners, always squeezes.
 */
export function patchCollisionVertexShader(source: string, squeeze = false, partner = false): string {
  if (source.includes('collidePush(')) return source
  if (!source.includes('#include <common>') || !source.includes('#include <skinning_vertex>')) return source
  const withPartner = squeeze && partner
  const declarations = withPartner ? `${COLLIDE_GLSL_DECLARATIONS}\n${COLLIDE_GLSL_PARTNER_DECLARATIONS}` : COLLIDE_GLSL_DECLARATIONS
  return source
    .replace('#include <common>', `#include <common>\n${declarations}\n${collideFunctionBlock(squeeze, withPartner)}`)
    .replace('#include <skinning_vertex>', `#include <skinning_vertex>\n${COLLIDE_GLSL_APPLY}`)
}

/** The garment kind of a node inside a garment subtree (`extras.garment.kind`, else the `garment_<kind>_…` name). */
export function garmentKind(o: Object3D): string | null {
  let n: Object3D | null = o
  while (n && !isGarmentNode(n)) n = n.parent
  if (!n) return null
  const g = (n.userData as { garment?: { kind?: unknown } }).garment
  if (g && typeof g.kind === 'string' && g.kind) return g.kind
  const m = /^garment_([^_]+)_/.exec(n.name)
  return m ? m[1] : ''
}

/**
 * Capsule regions that push HAIR (`garmentCapsules`). The legs are not
 * among them (hair does not reach them standing or sitting). Measured with
 * `scripts/check_garment_collision.mjs` (8 samples, max; share > 5 mm inside
 * beyond the vertex's bind depth) on Kira's HairDeck hair and the S1 spike
 * hair: the arm capsules are what moves hair at all — celebrating Kira
 * 7.91 → 7.91 % without them, → 7.59 % with; spike 28.6 → 28.0 % / → 23.4 %,
 * spike walk 0.77 → 0.77 / → 0.13 %. Under the bind rule they lift nothing
 * in the bind pose (without it: 5.6 % of Kira's hair lifted up to 27 mm off
 * the shoulders by the upper-arm caps).
 * `chest_hair` (collision v3), not `chest`: long hair lying in front sinks
 * into the protruding chest region in motion, and the inside-skin `chest`
 * capsules (p50, r 1.8/1.9 cm on Kira) barely catch it. CHEST_MEASURED
 * (2026-11-11, Kira's base with the long S1 spike hair, walk/sit/celebrating
 * with the secondary motion, hair vertices over the chest region = nearest
 * bind body vertex dominated by the chest chain, share > 5 mm inside beyond
 * the bind depth, worst of 8 samples):
 *  - `chest` (p50): walk 29.9 %, sit 5.5 %, celebrating 28.2 %;
 *  - `chest_hair` p90 + 6 mm: 5.3 / 4.4 / 24.1 %; p95 + 6 mm (the default,
 *    r 6.4 cm): 3.0 / 4.4 / 24.1 %; p99 + 6 mm: 1.3 / 3.5 / 24.1 %;
 *  - the default at scale 1.2: 3.3 / 2.7 / 23.5 %; at 1.5: 4.0 / 3.2 / 19.3 %
 *    (celebrating's rest is the arms crossing the hair, not the chest).
 * Bind lift > 1 mm 0.00 % in every variant up to scale 1.5: the bind rule
 * caps each push at the vertex's bind distance, so no size lifts hair in
 * the bind pose. The default's surface lies out to the skin plus the fit's
 * clearance (outside p95 6.7 mm on Kira — `EXTENSION_MEASURED`).
 * Never `attached_part` or `appendage` (hair does not reach them), never the
 * partner-only `outer_trunk` (`PARTNER_ONLY_REGIONS`: it reaches past the
 * figure's own back and sides).
 * `shoulder_hair` (collision v4): the top of the shoulders, which no other
 * capsule covers — hair lying there and swinging HairDeck chains sank in
 * (`app/core/collision.py` SHOULDER_MEASURED).
 */
export const HAIR_REGIONS: readonly string[] = ['torso', 'arm', 'head', 'shoulder_hair', 'chest_hair']

/** The extension regions (`app/core/collision.py` `EXTENSION_CAPSULES`): capsules on spring-driven bones. */
export const EXTENSION_REGIONS: readonly string[] = ['chest', 'chest_hair', 'attached_part', 'appendage']

/**
 * Capsule regions that never push CLOTH (every kind but hair and footwear,
 * `garmentCapsules`). The arms: cloth lies ON the body, and an arm that swings
 * or rests against it is the arm passing through the cloth, not the cloth
 * through the arm: pushed out of the arm capsule the cloth goes INTO the
 * body. Measured on the S1 dress (`scripts/check_garment_collision.mjs`):
 * walk 0.87 → 0.99 % with the arm capsules (armpit cloth driven into the
 * chest), sit hip sides 1.4 → 4.7 % (the forearms on the lap press the skirt
 * into the thighs). The extension regions push cloth — CLOTH_MEASURED
 * (2026-11-11, share of the cloth over the region > 5 mm inside beyond its
 * bind depth, worst of 8 samples, with the secondary motion; bind lift > 1 mm
 * 0.00 % with and without them):
 *  - `attached_part`: the S1 dress placed on Stefan Grahl's generated model
 *    (an `attached_part` chain of 5 links): walk 19.7 → 8.8 %, run 14.3 →
 *    8.3 % (without motion 19.8 → 4.8 / 15.4 → 4.6 %), sit 0 → 0 %;
 *  - `chest`: the phase-5 dress on Kira's base: run 19.5 → 18.8 %, walk /
 *    sit / celebrating unchanged (7.7 / 0 / 19.4 %) — the dress carries no
 *    chest weights, its fabric lies 10.6 mm (p5) off the tissue.
 * Neither floats cloth fitted over it at bind (the bind rule caps the radius
 * at the vertex's bind distance). The hair-only regions (`HAIR_ONLY_REGIONS`,
 * out to the skin plus the hair clearance) never push cloth: cloth keeps the
 * inside-skin `chest` set. Nor do the partner-only regions
 * (`PARTNER_ONLY_REGIONS`, collision v6): the outer trunk set is another
 * figure's collider, around this one it would float the cloth off the back.
 */
export const CLOTH_EXCLUDED_REGIONS: readonly string[] = ['arm', ...HAIR_ONLY_REGIONS, ...PARTNER_ONLY_REGIONS]

/**
 * Which bound capsules push a garment of `kind`, in payload order (the
 * server's table first, then the extension capsules), at most `COLLIDE_MAX`
 * — deterministic:
 *  - hair: the `HAIR_REGIONS`;
 *  - footwear: none. A fitted shoe is rigid on Foot/ToeBase (footwear spec
 *    `docs/superpowers/specs/2026-11-10-footwear-rigid-shoes-design.md`
 *    § 7.2): a push would deform it, so `collidingGarmentMeshes` skips it
 *    and its material is never patched. A boot's shaft node (kind footwear,
 *    `part: "shaft"`) is rigid on the Leg between the ankle band and the knee
 *    and gets none either (boots spec § 10: it never moves deeper into the
 *    shin capsule than in the bind pose, where the bind rule caps a push at 0);
 *  - every other kind: all regions except `CLOTH_EXCLUDED_REGIONS`.
 */
export function garmentCapsules<T extends { capsule: { region: string } }>(kind: string | null, bound: readonly T[]): T[] {
  if (kind === 'footwear') return []
  if (kind === 'hair') return bound.filter(entry => HAIR_REGIONS.includes(entry.capsule.region)).slice(0, COLLIDE_MAX)
  const cloth = bound.filter(entry => !CLOTH_EXCLUDED_REGIONS.includes(entry.capsule.region))
  return cloth.slice(0, COLLIDE_MAX)
}

/** The skinned garment meshes under `root` that collide at all (`garmentCapsules` gives their kind capsules). */
export function collidingGarmentMeshes(root: Object3D): SkinnedMesh[] {
  const out: SkinnedMesh[] = []
  const probe = [{ capsule: { region: 'torso' } }]
  root.traverse(o => {
    const mesh = o as SkinnedMesh
    if (!mesh.isSkinnedMesh) return
    const kind = garmentKind(mesh)
    if (kind !== null && garmentCapsules(kind, probe).length) out.push(mesh)
  })
  return out
}

interface CollideUniforms {
  collideA: { value: Vector4[] }
  collideB: { value: Vector4[] }
  collideBindA: { value: Vector4[] }
  collideBindB: { value: Vector4[] }
  collideCount: { value: number }
}

/** The partner block's uniforms (hair only; PARTNERS, module docstring). */
interface PartnerUniforms {
  partnerA: { value: Vector4[] }
  partnerB: { value: Vector4[] }
  partnerCount: { value: number }
}

/**
 * A skinned mesh's bounding sphere in its geometry space, and the joint with
 * the most skin weight that carries it into the world (`meshSphereNow`).
 * Ties keep the lower joint index; no skin attributes → joint 0.
 */
function meshSphereBind(mesh: SkinnedMesh): { c: Vec3; r: number; joint: number } {
  const pos = mesh.geometry.getAttribute('position')
  let lo: Vec3 = [Infinity, Infinity, Infinity], hi: Vec3 = [-Infinity, -Infinity, -Infinity]
  for (let i = 0; i < pos.count; i++) {
    const x = pos.getX(i), y = pos.getY(i), z = pos.getZ(i)
    lo = [Math.min(lo[0], x), Math.min(lo[1], y), Math.min(lo[2], z)]
    hi = [Math.max(hi[0], x), Math.max(hi[1], y), Math.max(hi[2], z)]
  }
  const c: Vec3 = pos.count ? [(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, (lo[2] + hi[2]) / 2] : [0, 0, 0]
  let r = 0
  for (let i = 0; i < pos.count; i++) r = Math.max(r, Math.hypot(pos.getX(i) - c[0], pos.getY(i) - c[1], pos.getZ(i) - c[2]))
  const si = mesh.geometry.getAttribute('skinIndex'), sw = mesh.geometry.getAttribute('skinWeight')
  const weight = new Map<number, number>()
  if (si && sw) {
    for (let i = 0; i < si.count; i++) {
      for (let k = 0; k < 4; k++) {
        const j = si.getComponent(i, k), w = sw.getComponent(i, k)
        if (w > 0) weight.set(j, (weight.get(j) ?? 0) + w)
      }
    }
  }
  let joint = 0, best = -1
  for (const [j, w] of [...weight.entries()].sort((p, q) => p[0] - q[0])) if (w > best) { joint = j; best = w }
  return { c, r, joint }
}

/** The bounding sphere of `meshSphereBind` in the world now: through its joint's bind→world (`jointNowFrom`). */
function meshSphereNow(mesh: SkinnedMesh, bind: { c: Vec3; r: number; joint: number }): Sphere {
  const bones = mesh.skeleton?.bones ?? []
  const j = bind.joint < bones.length ? bind.joint : -1
  const m = j >= 0
    ? jointNowFrom(mesh.matrixWorld.elements, mesh.bindMatrixInverse.elements, bones[j].matrixWorld.elements,
      mesh.skeleton.boneInverses[j].elements, mesh.bindMatrix.elements).bindToWorld
    : mesh.matrixWorld.elements
  return { c: transformPoint(m, bind.c), r: bind.r * linearScale(m) }
}

/** One patched garment mesh. */
export interface GarmentCollisionEntry {
  readonly mesh: SkinnedMesh
  readonly kind: string | null
  /** The bound capsules this mesh is pushed out of (payload order). */
  readonly capsules: readonly BoundCapsule[]
  /** The capsules in this mesh's local space as of the last update — what the shader holds (incl. `bind`). */
  readonly local: readonly CollideCapsule[]
  /**
   * Hair: the mesh's world bounding sphere as of the last update (its geometry's sphere carried by the joint with
   * the most skin weight) — what the partner capsules are ranked against. Null for every other kind.
   */
  readonly sphere: Sphere | null
  /** Hair: the partner capsules in this mesh's local space as of the last update, nearest first — what the
   *  partner block holds (PARTNERS, module docstring). Always empty for every other kind. */
  readonly partners: readonly CapsuleNow[]
}

export interface GarmentCollision {
  readonly binding: CollisionBinding
  readonly entries: readonly GarmentCollisionEntry[]
  /** Recompute from the CURRENT matrices now (the render hooks do this by themselves once per frame). */
  update(): void
  /**
   * Leave one patched mesh out of the push (`on`) or put it back: excluded, it wears its ORIGINAL material and depth
   * materials again (the template's, unpatched) and its hooks skip the uniform update; back in, it wears this
   * handle's patched clones again (kept, not rebuilt). A mesh this handle did not patch is ignored. The strand hair
   * (`hairSim.ts`) uses it — its sim collides itself, and the push's bind rule assumes the static bind mesh
   * (strand-hair spec § 6.2.2).
   */
  excludeMesh(mesh: SkinnedMesh, on: boolean): void
  /**
   * Other figures' capsules (world space) for the hair meshes' partner block (PARTNERS, module docstring); null or
   * `[]` = none. Kept until the next call; each hair mesh's render hooks take the `PARTNER_COLLIDE_MAX` nearest to
   * its world bounding sphere into its frame. Only `partnerCount` and the partner uniforms change: no recompile, the
   * program cache key stays. Every other garment kind ignores them.
   */
  setPartners(capsules: readonly CapsuleNow[] | null): void
  /** Restore the original materials and hooks, free the owned clones. */
  dispose(): void
}

/**
 * Patch the skinned garment meshes under `root` so they are pushed out of
 * the `payload`'s capsules (module docstring). Null = inert.
 */
export function createGarmentCollision(three: Three, root: Object3D,
  payload: CollisionPayload | null | undefined): GarmentCollision | null {
  const garments = collidingGarmentMeshes(root)
  if (!garments.length) return null
  const binding = bindCollision(three, root, payload)
  if (!binding) return null

  interface State {
    entry: { mesh: SkinnedMesh; kind: string | null; capsules: BoundCapsule[]; local: CollideCapsule[];
      sphere: Sphere | null; partners: CapsuleNow[] }
    binds: Array<{ a: Vec3; b: Vec3 }>
    uniforms: CollideUniforms
    /** Hair: the partner block's uniforms and the bind sphere it ranks against; null for every other kind. */
    partner: { uniforms: PartnerUniforms; bindSphere: { c: Vec3; r: number; joint: number } } | null
    original: Material | Material[]
    owned: Material[]
    depth: Material | undefined
    distance: Material | undefined
    ownHooks: { render: boolean; shadow: boolean }
    beforeRender: SkinnedMesh['onBeforeRender']
    beforeShadow: SkinnedMesh['onBeforeShadow']
    frame: number
    /** The patched material(s) and depth materials this handle put on (`excludeMesh` swaps them back in). */
    patched: { material: Material | Material[]; depth: Material; distance: Material }
    excluded: boolean
  }
  const DEFAULT_CACHE_KEY = three.Material.prototype.customProgramCacheKey
  // `source` = the material `mat` was cloned from: `Material.clone()` copies neither `onBeforeCompile` nor
  // `customProgramCacheKey`, so a compile hook the template's material carries is chained from there.
  const patch = (mat: Material, uniforms: CollideUniforms, partner: PartnerUniforms | null, weighted: boolean,
    squeeze: boolean, source: Material = mat) => {
    const prevCompile = source.onBeforeCompile
    const prevKey = source.customProgramCacheKey
    // three's default cache key IS `onBeforeCompile.toString()` — snapshot it
    // before this patch replaces the function (the pattern of client3d's
    // spotHighlight), so different compile hooks never collapse onto one program.
    const baseKey = prevKey === DEFAULT_CACHE_KEY ? prevCompile.toString() : null
    mat.onBeforeCompile = (shader: WebGLProgramParametersWithUniforms, renderer) => {
      prevCompile.call(source, shader, renderer)
      shader.uniforms.collideA = uniforms.collideA
      shader.uniforms.collideB = uniforms.collideB
      shader.uniforms.collideBindA = uniforms.collideBindA
      shader.uniforms.collideBindB = uniforms.collideBindB
      shader.uniforms.collideCount = uniforms.collideCount
      if (partner) {
        shader.uniforms.partnerA = partner.partnerA
        shader.uniforms.partnerB = partner.partnerB
        shader.uniforms.partnerCount = partner.partnerCount
      }
      shader.vertexShader = patchCollisionVertexShader(shader.vertexShader, squeeze, !!partner)
    }
    mat.customProgramCacheKey = () => `${baseKey ?? prevKey.call(source)}|collide${weighted ? 'W' : ''}${squeeze ? 'S' : ''}`
    if (weighted) mat.defines = { ...(mat.defines ?? {}), COLLIDE_WEIGHT: '' }
    if (squeeze) mat.defines = { ...(mat.defines ?? {}), COLLIDE_SQUEEZE: '' }
    if (partner) mat.defines = { ...(mat.defines ?? {}), COLLIDE_PARTNER: '' }
    mat.needsUpdate = true
    return mat
  }

  const states: State[] = []
  let lastBindingFrame = -1
  /** The partner capsules of `setPartners` (world), shared by every hair mesh. */
  let partnerWorld: readonly CapsuleNow[] = []
  /** Hair: the sphere now, then the `PARTNER_COLLIDE_MAX` nearest partner capsules into the mesh's frame `inv`. */
  const writePartners = (state: State, inv: Mat4) => {
    const partner = state.partner
    if (!partner) return
    const { mesh } = state.entry
    const sphere = meshSphereNow(mesh, partner.bindSphere)
    state.entry.sphere = sphere
    const picked = partnerWorld.length ? nearestCapsules(sphere, partnerWorld, PARTNER_COLLIDE_MAX) : []
    state.entry.partners = picked.map(k => capsuleInFrame(partnerWorld[k], inv))
    state.entry.partners.forEach((c, i) => {
      partner.uniforms.partnerA.value[i].set(c.a[0], c.a[1], c.a[2], c.r)
      partner.uniforms.partnerB.value[i].set(c.b[0], c.b[1], c.b[2], 0)
    })
    partner.uniforms.partnerCount.value = state.entry.partners.length
  }
  const writeUniforms = (state: State) => {
    const { mesh, capsules } = state.entry
    const inv = new three.Matrix4().copy(mesh.matrixWorld).invert().elements
    state.entry.local = capsules.map((c, i) => {
      const l: CollideCapsule = capsuleInFrame(c.now, inv)
      l.bind = state.binds[i]
      return l
    })
    state.entry.local.forEach((c, i) => {
      state.uniforms.collideA.value[i].set(c.a[0], c.a[1], c.a[2], c.r)
      state.uniforms.collideB.value[i].set(c.b[0], c.b[1], c.b[2], 0)
      const bind = c.bind ?? c   // always set here (bind rule for every garment)
      state.uniforms.collideBindA.value[i].set(bind.a[0], bind.a[1], bind.a[2], 0)
      state.uniforms.collideBindB.value[i].set(bind.b[0], bind.b[1], bind.b[2], 0)
    })
    state.uniforms.collideCount.value = state.entry.local.length
    writePartners(state, inv)
  }
  const frameUpdate = (state: State, frame: number) => {
    if (state.frame === frame) return
    state.frame = frame
    if (lastBindingFrame !== frame) {
      lastBindingFrame = frame
      binding.update()
    }
    writeUniforms(state)
  }

  for (const mesh of garments) {
    const kind = garmentKind(mesh)
    const capsules = garmentCapsules(kind, binding.capsules)
    if (!capsules.length) continue
    // Bind rule: the bind-pose capsules (body bind world) in THIS mesh's geometry space — where `position` is:
    // inverse(bindMatrix), not the attached mode's `bindMatrixInverse` (inverse(matrixWorld) now, which follows
    // where the figure stands).
    const geometryFromBind = new three.Matrix4().copy(mesh.bindMatrix).invert().elements
    const binds = capsules.map(c => capsuleInFrame(c.bind, geometryFromBind))
    const uniforms: CollideUniforms = {
      collideA: { value: Array.from({ length: COLLIDE_MAX }, () => new three.Vector4()) },
      collideB: { value: Array.from({ length: COLLIDE_MAX }, () => new three.Vector4()) },
      collideBindA: { value: Array.from({ length: COLLIDE_MAX }, () => new three.Vector4(0, 0, 0, -1)) },
      collideBindB: { value: Array.from({ length: COLLIDE_MAX }, () => new three.Vector4()) },
      collideCount: { value: 0 },
    }
    const weighted = !!mesh.geometry?.getAttribute('_collide')
    // The SQUEEZE rule pushes hair only (plan R10): cloth keeps the ordinary passes.
    const squeeze = kind === 'hair'
    // The partner block, hair only (spec Part 2): no other garment kind is pushed out of a partner.
    const partner: State['partner'] = kind === 'hair' ? {
      uniforms: {
        partnerA: { value: Array.from({ length: PARTNER_COLLIDE_MAX }, () => new three.Vector4()) },
        partnerB: { value: Array.from({ length: PARTNER_COLLIDE_MAX }, () => new three.Vector4()) },
        partnerCount: { value: 0 },
      },
      bindSphere: meshSphereBind(mesh),
    } : null
    const original = mesh.material
    const owned: Material[] = []
    const cloneOf = (m: Material) => {
      const c = patch(m.clone(), uniforms, partner?.uniforms ?? null, weighted, squeeze, m)
      owned.push(c)
      return c
    }
    mesh.material = Array.isArray(original) ? original.map(cloneOf) : cloneOf(original)
    const depthMat = new three.MeshDepthMaterial({ depthPacking: three.RGBADepthPacking })
    const distanceMat = new three.MeshDistanceMaterial()
    // An alpha-tested garment (hair cards, glTF MASK — strand-hair spec § 6.1): the depth passes cut the
    // same texels as the colour pass — the same map object and cutoff, never a cutoff of their own.
    const masked = (Array.isArray(mesh.material) ? mesh.material : [mesh.material])
      .find(m => m.alphaTest > 0) as (Material & { map?: Texture | null }) | undefined
    if (masked) {
      for (const d of [depthMat, distanceMat]) {
        d.map = masked.map ?? null
        d.alphaTest = masked.alphaTest
      }
    }
    const depth = patch(depthMat, uniforms, partner?.uniforms ?? null, weighted, squeeze)
    const distance = patch(distanceMat, uniforms, partner?.uniforms ?? null, weighted, squeeze)
    owned.push(depth, distance)
    const state: State = {
      entry: { mesh, kind, capsules, local: [], sphere: null, partners: [] }, binds, uniforms, partner, original, owned,
      depth: mesh.customDepthMaterial, distance: mesh.customDistanceMaterial,
      ownHooks: { render: Object.prototype.hasOwnProperty.call(mesh, 'onBeforeRender'), shadow: Object.prototype.hasOwnProperty.call(mesh, 'onBeforeShadow') },
      beforeRender: mesh.onBeforeRender, beforeShadow: mesh.onBeforeShadow, frame: -1,
      patched: { material: mesh.material, depth, distance }, excluded: false,
    }
    mesh.customDepthMaterial = depth
    mesh.customDistanceMaterial = distance
    const prevRender = state.beforeRender
    const prevShadow = state.beforeShadow
    mesh.onBeforeRender = function (renderer, scene, camera, geometry, material, group) {
      if (!state.excluded) frameUpdate(state, renderer.info.render.frame)
      prevRender.call(this, renderer, scene, camera, geometry, material, group)
    }
    mesh.onBeforeShadow = function (renderer, object, camera, shadowCamera, geometry, depthMaterial, group) {
      if (!state.excluded) frameUpdate(state, renderer.info.render.frame)
      prevShadow.call(this, renderer, object, camera, shadowCamera, geometry, depthMaterial, group)
    }
    writeUniforms(state)
    states.push(state)
  }
  if (!states.length) return null

  return {
    binding,
    get entries() { return states.map(s => s.entry) },
    update() {
      binding.update()
      for (const state of states) writeUniforms(state)
    },
    excludeMesh(mesh: SkinnedMesh, on: boolean) {
      const state = states.find(s => s.entry.mesh === mesh)
      if (!state || state.excluded === on) return
      state.excluded = on
      mesh.material = on ? state.original : state.patched.material
      mesh.customDepthMaterial = on ? state.depth : state.patched.depth
      mesh.customDistanceMaterial = on ? state.distance : state.patched.distance
      if (!on) state.frame = -1   // the next render writes the uniforms from the current matrices
    },
    setPartners(capsules: readonly CapsuleNow[] | null) {
      partnerWorld = capsules?.length ? [...capsules] : []
      // the next hook of a hair mesh writes them, also within a frame whose uniforms were already written
      for (const state of states) if (state.partner) state.frame = -1
    },
    dispose() {
      for (const state of states) {
        const { mesh } = state.entry
        mesh.material = state.original
        mesh.customDepthMaterial = state.depth
        mesh.customDistanceMaterial = state.distance
        // A hook the mesh did not own came from the prototype: drop ours, do not pin a copy.
        if (state.ownHooks.render) mesh.onBeforeRender = state.beforeRender
        else delete (mesh as Partial<Pick<SkinnedMesh, 'onBeforeRender'>>).onBeforeRender
        if (state.ownHooks.shadow) mesh.onBeforeShadow = state.beforeShadow
        else delete (mesh as Partial<Pick<SkinnedMesh, 'onBeforeShadow'>>).onBeforeShadow
        for (const m of state.owned) m.dispose()
      }
      states.length = 0
      partnerWorld = []
    },
  }
}
