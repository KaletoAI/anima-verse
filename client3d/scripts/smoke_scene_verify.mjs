#!/usr/bin/env node
/**
 * Hand-derived verify oracles for shared/test-vectors/scene_verify.json.
 *
 * [1] BOX min=(1,2,3), max=(5,8,7). Subtract origin=(1,2,3):
 * min=0, max=(4,6,4). With origin=0 its centre=(3,5,5) and
 * half-size=(2,3,2). Inverse yaw90 maps centre x'=-5,z'=3,
 * so min=(-7,2,1), max=(-3,8,5). At yaw45 the smaller box
 * [1,2,1]..[3,4,3] has centre=(2,3,2), half-size=(1,1,1).
 * Inverse yaw gives x'=0,z'=2*sqrt(2)=2.8284271247461903.
 * Half-extents stay world-aligned: min=(-1,2,1.8284271247461903),
 * max=(1,4,3.8284271247461903). Angles pi/2 and pi/4 in radians
 * are 1.5707963267948966 and 0.7853981633974483.
 * [2] EPS=0.01, strict greater-than. Deltas 0,0.01,0.009 pass;
 * 2.01234-2=0.01234 and -0.01234-0=-0.01234 fail. Rounding
 * to 3 decimals produces +/-0.012, actual 2.012 and -0.012.
 * Five measurements mean checked=5 and exactly two rows.
 * [3] BOX sizes=(4,6,4), centre=(3,5,5), bottom=2.
 * Parallel xyz measures bottom, two anchor coordinates and max=6:
 * checked=4. xz/yawed_xz instead use max(4,4)=4. Their yaw90
 * remains parallel. Position=(99,0,99) is ignored in this branch.
 * Changing targets to bottom=1, anchor=(2,4), max=5 gives four
 * deltas +1 in that same order. Name is role:id = prop:p.
 * [4] Yaw45 checks the hanging point (3,999,5), ignoring its y;
 * max=100 is skipped: checked=3. Fine fix=(5,110,355) skips only
 * max, still checking geometry centre. A frame at yaw45 instead
 * checks world position=(sqrt(2),0,0), where sqrt(2)=1.4142135623730951;
 * inverse rotation gives (1,1). Both diagonal cases have no rows.
 * [5] Fit checks bottom and hinge=(1,3), not BOX centre=(3,5),
 * and adds opening width=max(4,4)=4, height=6: checked=5.
 * Diagonal yaw45 skips those last two: checked=3 even with sizes99.
 * Wrong sizes=(3,5) yield two +1 rows (width then height).
 * [6] Lift0.5 adds to bottom target1.5 to give2, so four pass.
 * max_m=0 is absent by the existing truthiness rule: checked=3.
 * [7] Wall from(0,2) to(4,2): midpoint=((0+4)/2,(2+2)/2)
 * =(2,2); base1 plus height3 gives top4. Diagonal from(1,2)
 * to(5,8): midpoint=(3,5); base-1 plus height2.5 gives top1.5.
 * The four target fields are base_y,top_y,centre.x,centre.z.
 *
 * Integration checks run these same vectors through SpecVerifier. Primitive
 * rows are passed through primitive()/check(); placement uses a real Group
 * containing a box at the vector's world bbox and an independent root at
 * its stated hanging point. No screenshot or measured golden output is used.
 */
import { createRequire } from 'node:module';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadVectors, runVectors } from '../../shared/test-vectors/vectors.mjs';
import * as THREE from 'three';
const root = fileURLToPath(new URL('../../', import.meta.url));
const require_ = createRequire(import.meta.url);
let esbuild;
for (const path of ['esbuild', join(root,'client3d/node_modules/esbuild')]) {
  try { esbuild=require_(path); break; } catch { /* Try workspace install. */ }
}
if (!esbuild) throw new Error('esbuild not found; nothing was checked');
const dir=await mkdtemp(join(tmpdir(),'smoke-scene-verify-'));
try {
  await esbuild.build({stdin:{contents:`export * from './packages/scene-render/src/verify.ts'; export { wallTargets } from './packages/scene-render/src/primitives.ts';`,resolveDir:root},bundle:true,platform:'node',format:'esm',outfile:join(dir,'verify.mjs'),logLevel:'silent'});
  const core=await import(`file://${join(dir,'verify.mjs')}`);
  const vectors=loadVectors('scene_verify');
  const wallTargets=(wall)=>core.wallTargets(wall).map(({field,target})=>({field,target}));
  const pure=runVectors(vectors,{...core,wallTargets});
  const viaVerifier={...core,wallTargets,
    primitiveRows(name,ms) {
      const v=new core.SpecVerifier(THREE);
      const mesh=new THREE.Mesh(new THREE.BoxGeometry(1,1,1));
      v.primitive(mesh,new THREE.Vector3(),name,ms.map(m=>({...m,actual:()=>m.actual})));
      return {checked:v.checked,rows:v.rows};
    },
    placementRows(box,position,spec,origin,frameYaw=0,lift=0) {
      const g=new THREE.Group();
      g.position.set(position.x,position.y,position.z);
      const mesh=new THREE.Mesh(new THREE.BoxGeometry(box.max.x-box.min.x,box.max.y-box.min.y,box.max.z-box.min.z));
      mesh.position.set((box.min.x+box.max.x)/2-position.x,(box.min.y+box.max.y)/2-position.y,(box.min.z+box.max.z)/2-position.z);
      g.add(mesh);
      const v=new core.SpecVerifier(THREE);
      v.placement(g,spec,new THREE.Vector3(origin.x,origin.y,origin.z),frameYaw,lift);
      return {checked:v.checked,rows:v.rows};
    }
  };
  const integration=runVectors(vectors,viaVerifier);
  console.log(`scene_verify: ${pure.passed} pure + ${integration.passed} integration ok`);
  process.exitCode=pure.failed||integration.failed?1:0;
} finally { await rm(dir,{recursive:true,force:true}); }
