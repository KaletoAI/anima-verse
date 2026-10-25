#!/usr/bin/env node
/**
 * Shared scene-model hand oracles. All expectations live in scene_models.json.
 * [M] Primary URLs are /assets/props/pine-abc123/model?tier=full/low;
 * list positions 1/2 use store indices 2/3, and 2 lacks low. No/empty list
 * uses primary; equality to pickVariant is true for single/missing index;
 * selected third fallback differs from primary low (containment=true).
 * Missing/invalid index is zero. Modulo three: 3=0,4=1,7=1,
 * -1=2,-4=2. Missing low/unknown tier uses the chosen full, never another
 * mesh. Seed7 instances0..5 give 1,2,0,1,2,0, hence two of each URL.
 * [L] Leaf box min(.1,.1,-.02),max(.9,2.1,0): centre z=-.01. In fixed
 * frame take min x,min y,centre z then inverse YXZ rotation. Zero gives
 * (.1,.1,-.01),axis(0,1,0); yaw180 chooses raw max x=.9; yaw90 chooses
 * raw min z=-.02 at mid x=(.1+.9)/2=.5. Pitch90 chooses mid y=1.1,z=0,
 * axis -z. Roll90 chooses raw max y=2.1,axis+x. Missing fix is zero.
 * [G] Ground1 minus datum.25=.75. Only ground/default level lifts; +/-1
 * stand on plates. No sampler means zero at mount, preserve .75 on relift.
 * Applied.4 -> .75-.4=.35; applied.75 -> delta0; plate removes .75.
 * Tile datum.25 ->1 gives delta.75; no sampler holds datum.25,delta0.
 * [K] Marker(1.4,2),prop anchor(1,2): prop uses anchor; null/absent/non-finite anchor uses marker.
 * [S] Slots(-2,0,-3.6),(-2,0,-3),(-2,0,-2.4): numbered1/2 choose own;
 * pair mean=(-2,0,(-3.6-3-2.4)/3)=(-2,0,-3). Indices7/-1 use0;
 * empty numbered/pair is absent (serialized null). Identity remains in old smoke.
 * [Y] floor(1,2,3),anchored prop(4,5,6),old anchorless prop(7,8,9),
 * diorama(10,11,12),all room a: anchored prop never draws; diorama draws
 * unless room a is mounted. Skip floor leaves old only. Each ring raises y
 * .03: 2.03,8.03,11.03. Seat gold 0xf2cd6e=15912302. Empty entries=[] rows.
 * Ring inner/outer radii .25/.32,32 segments,lift.03,renderOrder20,rotation
 * -pi/2=-1.5707963267948966; opacity.85,transparent,depthTest/depthWrite off,
 * double side2. Lie0x8fb3ff=9417727,ground0x9fd48a=10474634,
 * stand0xd9d0bd=14274749,unknown0x9a9a9a=10132122.
 * [H] Surface step1,origin(-1,-1),box[-1,0,-1]..[1,1,1],extent(2,1,2),
 * rows [0,100,200],[0,100,200],[null,100,200] cm; placement anchor(4,-3),
 * yaw90,bottom.5,max4,xz -> scale2; inverse lx=-qz,lz=qx. A anchor has
 * u=v=1,value100 ->.5+2=2.5. B(4,-5):u2,v1,value200 ->4.5.
 * C(2,-2.5):u.75,v0,value75 ->.5+1.5=2. D(5,-2) touches null(0,2)
 * ->null. E(4,-6):u2.5>2 ->null. F xyz extent(2,3,2) scale4/3 ->
 * .5+4/3=1.8333333333333333. G yaw0 at(3.5,-5):same u.75,v0 ->2.
 * H truncated values lacks corners4,5,7,8 ->null. I lift.75 adds to2.5=3.25;
 * zero lift remains2.5. Highest of bottom.5/1 answers max(2.5,3)=3 at A,
 * null at D. Ignoring an all-null lattice leaves2.5. Own lifts .75/0 give
 * max(3.25,2.5)=3.25; the unlifted entry alone remains2.5.
 * [P,W,E] Hex colours are integer RGB: #123456=1193046,#010203=66051,
 * #112233=1122867,#000001=1,#000002=2,white=16777215. Plate upper uses
 * declared .4,transparent true; solid thickness.2 front side0,flat double2.
 * Wall glass defaults .25,roughness.3,metalness.02; leaf fallback #4a3a2e
 * =4864558,roughness.75. Upper wall uses declared .6; ordinary wall opaque1.
 * Extra glass .22 fallback,or glass_opacity.4,or elevator override.1; cabin
 * declared.8. Stair fallback #8a7a66=9075302; pad/frame use own colours;
 * all opaque1 unless opacity<1. Ordinary roughness.85,metalness.02.
 * Placeholder #9a9a9a=10132122,roughness.9,metalness.02,transparent opacity.5.
 * [X] Missing/invalid hex ->white; parseInt('12zz',16)=0x12=18; black=0.
 * [F] Matte/glow defaults roughness.85/metalness.02; gloss roughness.25;
 * water/ice .08/.15. Glow emissive1,explicit zero kept. Overrides .1/.2 kept.
 * [N] No metalness map and metalness> .5 ->0; exactly.5 kept. A real map
 * keeps metalness1; environment present sets intensity.7,absent changes none.
 * [D] Absent/zero normal ->null. Normal(2,0,0) normalized to(1,0,0),constant
 * -3 unchanged. Plane x=2,frame Ry90+translation(10,3,20): z=18,normal-z,
 * constant18. Scale(3,2,4)+translation: x=16,normal+x,constant-16.
 * [C] Square(0,0),(2,0),(2,2),(0,2) parity keeps(1,1),left boundary(0,1),
 * excludes(3,1),right boundary(2,1). Fewer than3 points does not clip.
 * Cutout union reverses keep: inside discarded,outside2.1 kept without pad.
 * Pad.25 includes x2.25 (distance.25),excludes2.26; corner(2.375,2.5) has
 * distance sqrt(.375²+.5²)=.625,discarded with pad.625. Disabled never discards. Second square
 * 10..12 discards(11,11). Model padding.2*world scale3=.6; negative/string=0.
 */
import { build } from 'esbuild';
import { mkdtemp, writeFile, rm } from 'node:fs/promises';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadVectors, runVectors } from '../../shared/test-vectors/vectors.mjs';
const ROOT = join(dirname(fileURLToPath(import.meta.url)), '../..');
export async function modelFunctions() {
  const dir = await mkdtemp(join(ROOT, 'client3d/scripts/.smoke-models-'));
  try {
    const result = await build({ stdin: { contents: `
      export { pickModelVariant, pickVariant } from './packages/scene-render/src/types';
      export { leafPivot } from './packages/scene-render/src/leafPivot';
      export * from './packages/scene-render/src/storeyGround';
      export * from './packages/scene-render/src/surface';
      export * from './packages/scene-render/src/clipMath';
      export { cutPlaneData } from './packages/scene-render/src/depthCutMath';
      export { surfaceFinish } from './packages/scene-render/src/materials';
      export * from './client3d/src/scene/materialLooks';
      export { markerLiftPoint } from './client3d/src/game/placement';
      export { slotFor } from './client3d/src/scene/placeSlot';
      export { glyphRows, glyphParameters } from './client3d/src/scene/placeGlyphs';
      export { Vector3 } from 'three';
    `, resolveDir: ROOT, loader: 'ts' }, bundle: true, platform: 'node', format: 'esm', write: false });
    const file = join(dir, 'models.mjs');
    await writeFile(file, result.outputFiles[0].text);
    const m = await import(`file://${file}`);
    const sample = n => n === null || n === undefined ? undefined : () => n;
    return { ...m,
      markerLiftPointInvalidAnchor: at => m.markerLiftPoint(at, { x: NaN, z: 2 }),
      variantMatchesPlain: (s,tier) => m.pickModelVariant(s,tier) === m.pickVariant(s.variants,tier),
      variantContained: (s,tier) => m.pickModelVariant(s,tier) !== s.variants.low,
      variantScatter: (s, indices) => indices.map(variant => m.pickModelVariant({ ...s, variant }, 'full')),
      variantCounts: (s, indices) => [0,1,2].map(v => indices.map(variant => m.pickModelVariant({ ...s, variant }, 'full')).filter(url => url === m.pickModelVariant({ ...s, variant: v }, 'full')).length),
      storeyGroundLift: (level,x,z,datum,s) => m.storeyGroundLift(level,x,z,datum,sample(s)),
      storeyGroundRelift: (applied,level,x,z,datum,s) => m.storeyGroundRelift(applied,level,x,z,datum,sample(s)),
      tileDatumStep: (applied,x,z,s) => m.tileDatumStep(applied,x,z,sample(s)),
      slotFor: (slots,slot) => m.slotFor({ slots: slots.map(p => new m.Vector3(...p)) },slot)?.toArray() ?? null,
      buildGlyphs: (entries,offers,skip='',rooms=[]) => m.glyphRows(entries ? new Map(Object.entries(entries).map(([id,e]) => [id,{ ...e, slots:e.slots.map(([x,y,z]) => ({x,y,z})) }])) : undefined, offers, skip, new Set(rooms)),
      cutPlaneFor: m.cutPlaneData,
    };
  } finally { await rm(dir, { recursive: true, force: true }); }
}
export async function runModelVectors(filter = () => true) {
  const vectors = loadVectors('scene_models');
  return runVectors({ ...vectors, cases: vectors.cases.filter(filter) }, await modelFunctions());
}
if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const { passed, failed } = await runModelVectors();
  console.log(`\n${passed} passed, ${failed} failed`);
  process.exitCode = failed ? 1 : 0;
}
