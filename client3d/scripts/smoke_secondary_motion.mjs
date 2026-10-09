#!/usr/bin/env node
/**
 * Usage: node client3d/scripts/smoke_secondary_motion.mjs
 * Hand derivation, metres/seconds, Y-up gravity (0,-9.81,0):
 * omega²=(4*pi)²=157.9136704. With m=2 upright a_g=(0,-9.81,0)
 * gives e_y=-9.81/omega²=-0.06212255072; m=1 gives 0 and m=.5 gives
 * +0.03106127536. Group gravity scales both baked and current gravity.
 * The single-chain probes explicitly use flatten=1: at -90 X,
 * e=(0,-d,-d), d=9.81/omega². A unit +Z lever becomes +Y, so the
 * centroid is (0,1-d,-d), length=sqrt((1-d)²+d²)=0.93993263.
 * Pair bind lever (0,-q,q), q=1/sqrt(2), becomes (0,q,q) at -90 X.
 * a_g=(0,-9.81,-9.81)=-9.81*sqrt(2)*u. Let D=9.81*sqrt(2)/omega².
 * flatten=.5 retains -.5*D*u; spill=.5 redirects .25*D*L. Thus the
 * centroid is (+/-[.2+.25*D],q*(1-.5*D),q*(1-.5*D)), and length
 * s=sqrt((1-.5*D)²+(.25*D)²). Volume compensation is 1/s along L,
 * 1 along the orthogonal third axis: determinant s*(1/s)*1=1.
 * flatten=0 removes inward acceleration even for a single chain;
 * without paired roots its removed part contributes no lateral offset.
 * Static T'=T+e is independent of gain and dynamic max_deg. Resets, far
 * LOD and gain zero retain T'. Rest rotation blends over 1.5 real seconds.
 * Static sag_max_deg and squash bound T'; dynamic angles are linear up to
 * max_deg/2, then max_deg/2*(1+tanh((angle-max_deg/2)/(max_deg/2))).
 * This C1 function is strictly monotonic and bounded by max_deg. Gain is
 * applied AFTER saturation. A critical spring with body velocity V has
 * d=-V*t*exp(-omega*t), independent of gravity: at V=3,t=1/30,
 * d_x=-0.065778376882. Bent-forward gravity 0/3 must share this response.
 * Weighted centroid (.25*z1+.75*z3)=2.5; after -90 X it is (0,2.5-d,-d).
 * f=20 has 1/100 of the f=2 offset; damping does not change equilibrium.
 * Client centering subtracts 1 from Y after -90 X: equilibrium=(0,-d,-d).
 * P4: numeric fields use smoothstep(t/1.5), so at .75 s gravity 1→.4
 * becomes .7, gain 1→0 becomes .5, frequency 2→0 becomes 1.
 * At zero frequency there is no static spring equilibrium: e=0; propagation
 * is ballistic p(t)=p(0)+v*t, including overdamped parameter values.
 * Both renderers share the solver; matrices preserve volume, inverse-transpose
 * normals, immutable bind transforms, chain FK, and instance ownership.
 */
import assert from 'node:assert/strict';
import * as THREE from 'three';
import { build, transform } from 'esbuild';
import { clone as cloneSkeleton } from 'three/examples/jsm/utils/SkeletonUtils.js';
import { mkdtemp, readFile, writeFile, rm } from 'node:fs/promises';
import { join } from 'node:path';
const dir = await mkdtemp(join(process.cwd(), 'client3d/scripts/.smoke-secondary-'));
try {
  const result = await build({ stdin: { contents: "export * from '@anima/scene-render'; export { Figure } from './client3d/src/scene/figures'", resolveDir: process.cwd(), loader: 'ts' }, bundle: true, platform: 'node', format: 'esm', write: false, external: ['three','three/*'] });
  const file = join(dir, 'solver.mjs');
  await writeFile(file, result.outputFiles[0].text);
  const C = await import(file);
  assert.equal(typeof C.createSecondaryMotion, 'function', 'shared solver must exist');
  const hintsBuild = await build({ entryPoints: ['frontend/src/tabs/characters/motionFieldPreview.ts'], bundle: true, platform: 'node', format: 'esm', write: false });
  const hintsFile = join(dir, 'hints.mjs');
  await writeFile(hintsFile, hintsBuild.outputFiles[0].text);
  const hints = await import(hintsFile);
  const motionType = await readFile('packages/scene-render/src/secondaryMotion.ts', 'utf8');
  const fields = [...motionType.match(/interface MotionGroup \{([\s\S]*?)\}/)[1].matchAll(/^  (\w+):/gm)].map(match => match[1]).filter(field => field !== 'bones');
  for (const field of fields) assert.ok(hints.motionFieldPreview[field], `missing preview category: ${field}`);
  const tiltViewerSource = await readFile('frontend/src/tabs/characters/Model3DViewer.tsx', 'utf8');
  assert.ok(tiltViewerSource.includes('applyPreviewTilt(previewRoot') && tiltViewerSource.indexOf('applyPreviewTilt(previewRoot') < tiltViewerSource.indexOf('secondary?.update(realDelta)'), 'tilt before solver');

  const fieldSource=await readFile('frontend/src/tabs/characters/FieldModel3D.tsx','utf8');
  assert.match(fieldSource,/motion=\{st.motion\}/,'status root must reach viewer');
  assert.equal(typeof C.installSkinnedNormalCorrection,'function');
  C.installSkinnedNormalCorrection(THREE);
  assert.match(THREE.ShaderChunk.skinnormal_vertex,/inverse\(transpose\(mat3\(skinMatrix\)\)\)/);

  const defaults = { bones: ['extra'], freq_hz: 2, zeta: 1, gravity: 1, gravity_scale: 1, flatten: 1, sag_max_deg: 180, spill: 0, gain: 1, max_deg: 180, squash: [0.1,3], rest_deg: 0, rest_max_deg: 90 };
  const payload = (params={}) => ({ rev: JSON.stringify(params), groups: { test: { ...defaults, ...params } } });
  function fixture(params={}) {
    const root = new THREE.Group(), anchor = new THREE.Bone(), bone = new THREE.Bone();
    root.add(anchor); bone.name='extra'; anchor.add(bone);
    // Rolled frame: the weighted centroid still points along world +Z.
    bone.rotation.z=0.7;
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position',new THREE.Float32BufferAttribute([-0.1,0,1, 0.1,0,1, 0,0,1],3));
    geometry.setAttribute('skinIndex',new THREE.Uint16BufferAttribute([1,0,0,0, 1,0,0,0, 1,0,0,0],4));
    geometry.setAttribute('skinWeight',new THREE.Float32BufferAttribute([1,0,0,0, 1,0,0,0, 1,0,0,0],4));
    const mesh=new THREE.SkinnedMesh(geometry,new THREE.MeshBasicMaterial()); root.add(mesh);
    root.updateMatrixWorld(true); mesh.bind(new THREE.Skeleton([anchor,bone]));
    const solver=C.createSecondaryMotion(THREE,root,payload(params));
    const point=()=>mesh.applyBoneTransform(2,new THREE.Vector3(0,0,1));
    return {root,anchor,bone,mesh,solver,point};
  }
  const near=(actual,expected,eps=1e-5)=>assert.ok(Math.abs(actual-expected)<eps,`${actual} vs ${expected} ±${eps}`);
  const tilted = fixture({ gain: 0 });
  hints.applyPreviewTilt(tilted.root, 90, 0);
  tilted.solver.update(0);
  const tiltD = 9.81 / (4 * Math.PI) ** 2;
  near(tilted.point().length(), Math.sqrt((1 - tiltD) ** 2 + tiltD ** 2));
  assert.ok(tilted.point().length() < 1, 'lying Tilt with flatten shortens');
  tilted.solver.dispose();
  console.log('ok preview hints cover payload fields; Tilt before solver shortens to 0.93993263');
  // A unit lever with squash=[1,1], sag limit pi/2 and no dynamics:
  // smoothstep derivative <=1.5/1.5=1 per second, so a bounded arc
  // transition moves <=(pi/2)/120 per 120 Hz frame (plus numeric tolerance).
  for (const [from,to] of [[2,0],[0,2]]) {
    const probe=fixture({freq_hz:from,gain:0,squash:[1,1],sag_max_deg:90});
    probe.anchor.rotation.x=-Math.PI/2;probe.solver.update(0);
    probe.solver.configure(payload({freq_hz:to,gain:0,squash:[1,1],sag_max_deg:90}));
    let last=probe.point(), jump=0;
    for(let i=0;i<181;i++) {
      probe.solver.update(1/120,{far:true});
      const point=probe.point();jump=Math.max(jump,point.distanceTo(last));last=point;
      assert.ok(point.toArray().every(Number.isFinite));
    }
    assert.ok(jump <= Math.PI/240+1e-5, `zero-frequency transition jump ${jump}`);
    probe.solver.dispose();
  }
  const interrupted=fixture({gain:0,squash:[1,1],sag_max_deg:90});
  interrupted.anchor.rotation.x=-Math.PI/2;interrupted.solver.update(0);
  interrupted.solver.configure(payload({freq_hz:0,gain:0,squash:[1,1],sag_max_deg:90}));
  for(let i=0;i<90;i++)interrupted.solver.update(1/120,{far:true});
  const interruptedPoint=interrupted.point();
  interrupted.solver.configure(payload({freq_hz:0,gravity:.8,gain:0,squash:[1,1],sag_max_deg:90}));
  interrupted.solver.update(0,{far:true});
  near(interrupted.point().distanceTo(interruptedPoint),0);
  interrupted.solver.configure(payload({freq_hz:2,gain:0,squash:[1,1],sag_max_deg:90}));
  interrupted.solver.update(0,{far:true});
  near(interrupted.point().distanceTo(interruptedPoint),0);
  interrupted.solver.dispose();
  console.log('ok interrupted zero-frequency blends preserve the current static offset');
  for (const freq_hz of [1e-200,0,20]) {
    const probe=fixture({freq_hz,zeta:10,gravity:10});
    probe.anchor.rotation.x=-Math.PI/2;
    for(let i=0;i<240;i++)probe.solver.update(1/120);
    assert.ok(probe.point().toArray().every(Number.isFinite),'tiny denominator stays finite');
    probe.solver.dispose();
  }
  console.log('ok finite extremes and bounded zero-frequency transition (pi/240 per frame)');
  const settle=f=>{for(let i=0;i<600;i++) f.solver.update(1/120);};
  const blended=C.blendMotionParams(defaults,{...defaults,gravity:.4,gain:0,freq_hz:0,flatten:.2,spill:.8,zeta:0},.75);
  near(blended.gravity,.7); near(blended.gain,.5); near(blended.freq_hz,1);
  near(blended.flatten,.6); near(blended.spill,.4); near(blended.zeta,.5);
  near(C.blendMotionParams(defaults,{...defaults,gain:0},1.5).gain,0);
  console.log('ok P4 multipliers blend at hand-derived midpoint and endpoint');
  const zero=C.stepSecondaryParticle(new THREE.Vector3(1,0,0),new THREE.Vector3(2,0,0),new THREE.Vector3(),new THREE.Vector3(),{...defaults,freq_hz:0,zeta:5},.25);
  near(zero.p.x,1.5); near(zero.v.x,2);
  const noSpring=fixture({freq_hz:0,zeta:5}); noSpring.anchor.rotation.x=-Math.PI/2; settle(noSpring);
  near(noSpring.point().distanceTo(new THREE.Vector3(0,1,0)),0);
  console.log('ok P4 explicit zero frequency stays finite');
  let probe=fixture({gravity_scale:2}); settle(probe); near(probe.point().y,-9.81/(4*Math.PI)**2); console.log('ok upright m=2 sag');
  let f=fixture(); settle(f); near(f.point().distanceTo(new THREE.Vector3(0,0,1)),0); console.log('ok upright: zero displacement');
  f.anchor.rotation.x=-Math.PI/2; f.solver.reset(); settle(f);
  near(f.point().distanceTo(new THREE.Vector3(0,1,0)),0.08785456); near(f.point().length(),0.93993263); console.log('ok static tilt equilibrium and shortening');
  near(f.bone.matrix.determinant(),1); console.log('ok directional scale preserves volume');
  // Roots +/-0.2 X; bind lever (0,-q,q), q=sqrt(1/2). After -90 X
  // lever=(0,q,q), dG=(0,-9.81,-9.81), purely inward magnitude 9.81 sqrt(2).
  // Equilibrium outward = spill*9.81*sqrt(2)/(4*pi)^2 (0.04392728 at .5).
  function pairFixture(spill, paired=true, params={}) {
    const root=new THREE.Group(), anchor=new THREE.Bone(); root.add(anchor);
    const bones=[new THREE.Bone(),new THREE.Bone()];
    bones.forEach((b,i)=>{b.name=`pair${i}`; b.position.x=i===0?-.2:.2; anchor.add(b);});
    const q=Math.SQRT1_2, geometry=new THREE.BufferGeometry();
    geometry.setAttribute('position',new THREE.Float32BufferAttribute([-.2,-q,q, .2,-q,q],3));
    geometry.setAttribute('skinIndex',new THREE.Uint16BufferAttribute([1,0,0,0, 2,0,0,0],4));
    geometry.setAttribute('skinWeight',new THREE.Float32BufferAttribute([1,0,0,0, 1,0,0,0],4));
    const mesh=new THREE.SkinnedMesh(geometry,new THREE.MeshBasicMaterial()); root.add(mesh);
    root.updateMatrixWorld(true); mesh.bind(new THREE.Skeleton([anchor,...bones]));
    const solver=C.createSecondaryMotion(THREE,root,{rev:'pair',groups:{pair:{...defaults,flatten:0,spill,...params,bones:paired?['pair0','pair1']:['pair0']}}});
    const point=i=>new THREE.Vector3(i===0?-.2:.2,-q,q).applyMatrix4(mesh.skeleton.boneInverses[i+1]).applyMatrix4(bones[i].matrixWorld);
    return {root,anchor,bones,solver,point};
  }
  for(const spill of [0,.5]) {
    const pair=pairFixture(spill); settle(pair);
    for(let i=0;i<2;i++) near(pair.point(i).x,i===0?-.2:.2);
    pair.anchor.rotation.x=-Math.PI/2; pair.solver.reset(); settle(pair);
    const outward=spill*9.81*Math.SQRT2/(4*Math.PI)**2;
    for(let i=0;i<2;i++) {
      near(pair.point(i).x,(i===0?-1:1)*(.2+outward));
      near(pair.point(i).y,Math.SQRT1_2); near(pair.point(i).z,Math.SQRT1_2);
      if(spill===0) near(pair.point(i).distanceTo(new THREE.Vector3(i===0?-.2:.2,0,0)),1);
    }
    pair.solver.dispose();
  }
  const single=pairFixture(.5,false); single.anchor.rotation.x=-Math.PI/2; settle(single);
  near(single.point(0).y,Math.SQRT1_2); near(single.point(0).x,-.2);
  console.log('ok spill pair equilibrium, no inward collapse, upright and single-chain behavior');
  const flatPair=pairFixture(.5,true,{flatten:.5});
  flatPair.anchor.rotation.x=-Math.PI/2; settle(flatPair);
  const D=9.81*Math.SQRT2/(4*Math.PI)**2, axialLength=1-.5*D;
  const flatLength=Math.hypot(axialLength,.25*D);
  for(let i=0;i<2;i++) {
    near(flatPair.point(i).x,(i===0?-1:1)*(.2+.25*D));
    near(flatPair.point(i).y,Math.SQRT1_2*axialLength);
    near(flatPair.point(i).z,Math.SQRT1_2*axialLength);
    const M=new THREE.Matrix3().setFromMatrix4(flatPair.bones[i].matrix);
    near(new THREE.Vector3(0,-Math.SQRT1_2,Math.SQRT1_2).applyMatrix3(M).length(),flatLength);
    near(new THREE.Vector3(1,0,0).applyMatrix3(M).length(),1/flatLength);
    near(new THREE.Vector3(0,Math.SQRT1_2,Math.SQRT1_2).applyMatrix3(M).length(),1);
    near(flatPair.bones[i].matrix.determinant(),1);
  }
  flatPair.solver.dispose();
  console.log('ok hand-derived flatten .5 / spill .5 length, lateral offset and one-axis width');
  const lift=fixture({gravity_scale:.5}); settle(lift);
  near(lift.point().y,.5*9.81/(4*Math.PI)**2);
  const still=fixture({gravity_scale:2,gain:0,max_deg:0}); settle(still);
  near(still.point().y,-9.81/(4*Math.PI)**2);
  const defaultSingle=fixture({flatten:0}); defaultSingle.anchor.rotation.x=-Math.PI/2; settle(defaultSingle);
  near(defaultSingle.point().y,1); near(defaultSingle.point().z,-9.81/(4*Math.PI)**2);
  console.log('ok m=.5 lift, static sag independent of gain/max_deg, default single flatten');
  const limit=Math.PI/18;
  let previous=-1;
  for(const angle of [0,.01,.05,.08,.1,.2,.4,1,3]) {
    const saturated=C.softMotionAngle(angle,limit);
    assert.ok(saturated>previous && saturated<=limit);
    previous=saturated;
  }
  near(C.softMotionAngle(limit,limit),limit/2*(1+Math.tanh(1)),1e-12);
  assert.equal(C.softMotionAngle(1,0),0);
  console.log('ok soft limit hand-derived, monotonic and bounded');
  const swing0=fixture({gravity:0}), swing3=fixture({gravity:3});
  for(const swing of [swing0,swing3]) {swing.anchor.rotation.x=-Math.PI/4; settle(swing);}
  let peak0=0,peak3=0;
  for(let i=0;i<120;i++) {
    for(const swing of [swing0,swing3]) {swing.root.position.x=.1; swing.solver.update(1/30);}
    // Points are mesh-local, so d_x is the visible offset from the moved anchor.
    near(swing0.point().x,swing3.point().x,1e-8);
    if(i===0) near(swing0.point().x,-.065778376882,1e-9);
    peak0=Math.max(peak0,Math.abs(swing0.point().x)); peak3=Math.max(peak3,Math.abs(swing3.point().x));
  }
  near(peak0,peak3,1e-8);
  console.log('ok same body impulse has identical swing for bent-forward gravity 0 and 3');

  f=fixture({gravity:0,gain:0,rest_deg:30}); settle(f); near(f.point().length(),1); near(f.point().z,Math.cos(Math.PI/6)); console.log('ok gain zero retains rest rotation');
  f=fixture({gravity:100,max_deg:5,sag_max_deg:5,squash:[0.95,1.05]}); f.anchor.rotation.x=-Math.PI/2; f.solver.reset(); settle(f);
  near(f.point().length(),1.05); near(f.point().angleTo(new THREE.Vector3(0,1,0)),5*Math.PI/180); console.log('ok dynamic angle and squash clamps');
  f=fixture({gravity:0,gain:0,rest_deg:80,rest_max_deg:20,max_deg:0}); settle(f); near(f.point().z,Math.cos(Math.PI/9)); console.log('ok independent rest clamp');
  f=fixture({freq_hz:20,zeta:5}); f.anchor.rotation.x=-Math.PI/2; f.solver.reset(); settle(f); near(f.point().distanceTo(new THREE.Vector3(0,1,0)),0.0008785456,1e-6); console.log('ok overdamped spring remains stable');
  const a=fixture(),b=fixture(); for(const x of [a,b]) {x.anchor.rotation.x=-Math.PI/2; x.solver.reset(); x.solver.update(0);}
  a.solver.update(1/30); for(let i=0;i<4;i++) b.solver.update(1/120); near(a.point().distanceTo(b.point()),0,1e-8); console.log('ok frame partition');
  a.solver.update(0.251); near(a.point().distanceTo(new THREE.Vector3(0,1-9.81/(4*Math.PI)**2,-9.81/(4*Math.PI)**2)),0); console.log('ok gap resets');
  a.solver.update(1/30); const before=a.point(); a.solver.update(1,{frozen:true}); near(a.point().distanceTo(before),0); console.log('ok frozen dynamics');
  a.root.position.x=0.4; a.solver.update(0.1,{frozen:true}); near(a.bone.matrix.elements[12],0);
  const frozenWorld=a.point().applyMatrix4(a.mesh.matrixWorld); near(frozenWorld.x,0.4); near(frozenWorld.y,before.y); console.log('ok freeze transports displacement with anchor');
  a.solver.update(1/30,{far:true}); near(a.point().distanceTo(new THREE.Vector3(0,1-9.81/(4*Math.PI)**2,-9.81/(4*Math.PI)**2)),0); console.log('ok far LOD reset');
  f=fixture(); f.solver.configure(payload({gravity:0,rest_deg:30,gain:0})); f.solver.update(0.2); assert.ok(f.point().z>Math.cos(Math.PI/6)); for(let i=0;i<7;i++) f.solver.update(0.2); near(f.point().z,Math.cos(Math.PI/6)); console.log('ok live 1.5 s rest blend');
  f=fixture({gravity:0,gain:0,rest_deg:80}); f.solver.update(0); f.solver.configure(payload({gravity:0,gain:0,rest_deg:80,rest_max_deg:20})); f.solver.update(0); near(f.point().z,Math.cos(Math.PI/9)); console.log('ok reduced rest limit clamps during blend');
  f.solver.dispose(); assert.equal(f.bone.matrixAutoUpdate,true); console.log('ok ownership restored');
  f=fixture(); f.solver.dispose();
  f.mesh.geometry.setAttribute('position',new THREE.Float32BufferAttribute([0,0,1, 0,0,3, 0,0,1],3));
  f.mesh.geometry.setAttribute('skinWeight',new THREE.Float32BufferAttribute([0.25,0.75,0,0, 0.75,0.25,0,0, 0,1,0,0],4));
  // Remaining influence belongs to the anchor, not the driven bone.
  f.solver=C.createSecondaryMotion(THREE,f.root,payload());
  f.anchor.rotation.x=-Math.PI/2; settle(f);
  const weightedCentre=new THREE.Vector3(0,0,2.5).applyMatrix4(f.mesh.skeleton.boneInverses[1]).applyMatrix4(f.bone.matrixWorld);
  near(weightedCentre.y,2.43787745); near(weightedCentre.z,-0.06212255); console.log('ok centroid uses positive skin weights');
  const movingA=fixture(),movingB=fixture(); movingA.solver.update(0); movingB.solver.update(0);
  movingA.root.position.x=0.1; movingA.solver.update(1/30);
  for(let i=1;i<=4;i++){movingB.root.position.x=i*0.025; movingB.solver.update(1/120);}
  near(movingA.point().x,-0.065778376882,1e-9);
  near(movingA.point().distanceTo(movingB.point()),0,1e-8); console.log('ok moving-target frame partition and target velocity');
  f=fixture(); f.anchor.rotation.x=-Math.PI/2; settle(f);
  const held=f.point(); f.solver.configure(payload({gravity:0.5})); f.solver.update(0); near(f.point().distanceTo(held),0); console.log('ok live reconfigure retains particle state');
  for(let i=0;i<6;i++) f.solver.update(.25,{far:true}); f.solver.reset(); f.solver.update(0); near(f.point().distanceTo(new THREE.Vector3(0,1-.5*9.81/(4*Math.PI)**2,-.5*9.81/(4*Math.PI)**2)),0); console.log('ok explicit teleport reset');
  f.solver.configure({rev:'absent',groups:{test:{...defaults,bones:['absent']}}}); assert.equal(f.bone.matrixAutoUpdate,true); f.solver.update(1/30); console.log('ok absent group skipped and bind restored');
  f=fixture(); f.solver.dispose();
  const clip=new THREE.AnimationClip('idle',1,[new THREE.QuaternionKeyframeTrack('extra.quaternion',[0,1],[0,0,Math.sin(0.35),Math.cos(0.35),0,0,Math.sin(0.35),Math.cos(0.35)])]);
  const holder={payload:payload()};
  const model={name:'secondary-smoke',template:f.root,clips:[clip],scale:1,height:1,assignOnly:true,noClips:false,tier:'full',libraryFits:true,motion:holder};
  const figure=new C.Figure(model);
  figure.faceTowards(new THREE.Vector3(0,0,1),true); figure.setLean(-90,0);
  for(let i=0;i<600;i++) figure.update(0,{realDelta:1/120});
  let liveMesh; figure.root.traverse(o=>{if(o.isSkinnedMesh) liveMesh=o;});
  const livePoint=()=>liveMesh.applyBoneTransform(2,new THREE.Vector3(0,0,1)).applyMatrix4(liveMesh.matrixWorld);
  near(livePoint().y,-0.06212255); near(livePoint().z,-0.06212255); console.log('ok client runs solver after final root lean');
  holder.payload=payload({gravity:0,gain:0}); for(let i=0;i<600;i++) figure.update(0,{realDelta:1/120}); near(livePoint().length(),0); assert.equal(liveMesh.geometry,f.mesh.geometry); console.log('ok client live motion revision keeps mesh');
  holder.payload=payload({gravity:0,gain:0,rest_deg:30}); for(let i=0;i<180;i++) figure.update(0,{realDelta:1/120});
  near(livePoint().y,Math.cos(Math.PI/6)-1); near(livePoint().z,0.5); console.log('ok client live rest blend');
  let disposed=0; f.mesh.geometry.addEventListener('dispose',()=>disposed++); figure.dispose(); assert.equal(disposed,0); console.log('ok client solver disposal preserves template geometry');


  const farFigure=new C.Figure({...model,tier:'low'});
  farFigure.faceTowards(new THREE.Vector3(0,0,1),true); farFigure.setLean(-90,0);
  for(let i=0;i<200;i++) farFigure.update(0,{realDelta:1/120});
  let farMesh; farFigure.root.traverse(o=>{if(o.isSkinnedMesh) farMesh=o;});
  const farPoint=farMesh.applyBoneTransform(2,new THREE.Vector3(0,0,1)).applyMatrix4(farMesh.matrixWorld);
  near(farPoint.y,Math.cos(Math.PI/6)-1); near(farPoint.z,0.5); farFigure.dispose(); console.log('ok client low tier retains rest without dynamics');
  const chain=fixture(); chain.solver.dispose();
  const child=new THREE.Bone(); child.name='extra_child'; child.position.z=0.5; chain.bone.add(child);
  chain.mesh.geometry.setAttribute('position',new THREE.Float32BufferAttribute([-0.1,0,1, 0.1,0,1, 0.3,0,1.5],3));
  chain.mesh.geometry.setAttribute('skinIndex',new THREE.Uint16BufferAttribute([1,0,0,0, 1,0,0,0, 2,0,0,0],4));
  chain.root.updateMatrixWorld(true); chain.mesh.bind(new THREE.Skeleton([chain.anchor,chain.bone,child]));
  const childBind=child.matrix.clone();
  // Two links under one root remain a single chain: flatten=1 retains
  // the original parent equilibrium (0,.93787745,-.06212255).
  const singleChain=C.createSecondaryMotion(THREE,chain.root,{rev:'single-chain',groups:{
    chain:{...defaults,bones:['extra','extra_child'],spill:0},
  }});
  chain.anchor.rotation.x=-Math.PI/2;
  for(let i=0;i<600;i++) singleChain.update(1/120);
  const chainCentre=new THREE.Vector3(0,0,1).applyMatrix4(chain.mesh.skeleton.boneInverses[1]).applyMatrix4(chain.bone.matrixWorld);
  near(chainCentre.y,.93787745); near(chainCentre.z,-.06212255);
  singleChain.dispose(); chain.anchor.rotation.x=0; chain.root.updateMatrixWorld(true);
  console.log('ok multiple links under one root keep explicitly retained single-chain axial gravity');
  // Child intentionally appears first in the payload: setup must order FK.
  const chainSolver=C.createSecondaryMotion(THREE,chain.root,{rev:'chain',groups:{
    child:{...defaults,bones:['extra_child'],gravity:0},
    parent:{...defaults,gravity:0,gain:0,rest_deg:30},
  }});
  chainSolver.update(0); chainSolver.update(1/30);
  for(let i=0;i<16;i++) near(child.matrix.elements[i],childBind.elements[i],1e-8);
  console.log('ok chains apply parent first using immutable bind transforms');
  const clonedParentMatrix=chain.bone.matrix.clone(); chainSolver.update(1/30);
  for(let i=0;i<16;i++) near(chain.bone.matrix.elements[i],clonedParentMatrix.elements[i],1e-8);
  console.log('ok rest does not accumulate across frames');
  for(const path of ['client3d/src/scene/figures.ts','frontend/src/tabs/characters/Model3DViewer.tsx']) {
    const src=await readFile(path,'utf8'); assert.match(src,/createSecondaryMotion/); assert.match(src,/from ['"]@anima\/scene-render['"]/);
  }
  console.log('ok both renderers import identical module');
  // Execute the actual field JSX prop expression and viewer toggle conditions.
  const response={model:{url:'/characters/demo/model3d/file',extension_rig:{status:'applied'}},motion:payload()};
  const fieldJSX=fieldSource.match(/<Model3DViewer[\s\S]*?\/>/)[0];
  const compiledField=await transform(`return (${fieldJSX})`,{loader:'tsx',jsxFactory:'h'});
  const h=(tag,props,...children)=>({tag,props,children});
  const viewerElement=new Function('h','Model3DViewer','st','model','viewerUrl','mixamo','clipUrl','bust',compiledField.code)(h,'Model3DViewer',response,response.model,response.model.url,false,'','revision');
  const adminMotion=viewerElement.props.motion;
  assert.equal(adminMotion,response.motion);
  const viewerSource=await readFile('frontend/src/tabs/characters/Model3DViewer.tsx','utf8');
  const initialEnabled=viewerSource.match(/\[secondaryOn, setSecondaryOn\] = useState\(([^)]+)\)/)[1];
  let enabled=new Function(`return ${initialEnabled}`)();
  const toggleJSX=viewerSource.match(/\{motion \? \([\s\S]*?\) : null\}/)[0].slice(1,-1);
  const compiledToggle=await transform(`return (${toggleJSX})`,{loader:'tsx',jsxFactory:'h'});
  const renderToggle=motion=>new Function('h','motion','secondaryOn','setSecondaryOn','t',compiledToggle.code)(h,motion,enabled,fn=>{enabled=fn(enabled);},x=>x);
  assert.equal(renderToggle(adminMotion).props['aria-pressed'],true);
  assert.equal(renderToggle(undefined),null);
  renderToggle(adminMotion).props.onClick();assert.equal(enabled,false);
  renderToggle(adminMotion).props.onClick();assert.equal(enabled,true);
  const parityFixture=fixture();parityFixture.solver.dispose();
  const parityHolder={payload:response.motion};
  const parityFigure=new C.Figure({...model,template:parityFixture.root,motion:parityHolder});
  // Clone its centered bind placement for the admin, then apply the same final rotation.
  const adminRoot=cloneSkeleton(parityFigure.root);
  const adminSolver=C.createSecondaryMotion(THREE,adminRoot,adminMotion);
  parityFigure.faceTowards(new THREE.Vector3(0,0,1),true);parityFigure.setLean(-90,0);
  adminRoot.rotation.copy(parityFigure.root.rotation);
  for(let i=0;i<600;i++){parityFigure.update(0,{realDelta:1/120});adminSolver.update(1/120);}
  const renderedPoint=root=>{let mesh;root.traverse(o=>{if(o.isSkinnedMesh)mesh=o;});return mesh.applyBoneTransform(2,new THREE.Vector3(0,0,1)).applyMatrix4(mesh.matrixWorld);};
  near(renderedPoint(parityFigure.root).distanceTo(renderedPoint(adminRoot)),0,1e-10);
  renderToggle(adminMotion).props.onClick();adminSolver.configure(enabled?adminMotion:undefined);adminSolver.update(0);
  near(renderedPoint(adminRoot).length(),0);parityFigure.dispose();adminSolver.dispose();
  const newSkeleton=fixture();newSkeleton.solver.dispose();
  for(const tier of ['low','full']) {
    const rebuilt=new C.Figure({...model,template:newSkeleton.root,tier,motion:{payload:payload()}});
    rebuilt.faceTowards(new THREE.Vector3(0,0,1),true);rebuilt.setLean(-90,0);
    rebuilt.update(0,{realDelta:0});near(renderedPoint(rebuilt.root).length(),Math.SQRT2*9.81/(4*Math.PI)**2);
    if(tier==='low'){for(let i=0;i<20;i++)rebuilt.update(0,{realDelta:1/120});near(renderedPoint(rebuilt.root).length(),Math.SQRT2*9.81/(4*Math.PI)**2);}
    rebuilt.dispose();
  }
  console.log('ok model3d root prop, extended-model toggle, numeric admin/client parity and toggle off');
  {
  // Execute the group editor with a persistent local state slot across polls.
  const helperSource=await readFile('frontend/src/lib/motionDraft.ts','utf8');
  const helperCode=await transform(helperSource.replace(/export /g,''),{loader:'ts'});
  const helpers=new Function(helperCode.code+'; return {makeDraft, editDraft, draftChanged, draftOverrides, validNumber}')();
  const editorSource=await readFile('frontend/src/tabs/characters/ExtensionMotionDraft.tsx','utf8');
  const editorCode=await transform(editorSource.replace(/^import .*$/gm,'').replace(/export /g,''),{loader:'tsx',jsxFactory:'h',jsxFragment:'Fragment'});
  let editorState;
  const useState=initial=>{editorState ??= initial();return [editorState,next=>{editorState=typeof next==='function'?next(editorState):next}];};
  const renderEditor=new Function('h','Fragment','useState','useI18n','MotionPreviewHint',...Object.keys(helpers),editorCode.code+'; return ExtensionMotionDraft')(
    h,'fragment',useState,()=>({t:x=>x}),'preview-hint',...Object.values(helpers));
  const editorCalls=[];
  const defaults={freq_hz:2,zeta:.7,gravity:1,gain:.9,max_deg:30,sag_max_deg:30,flatten:1,spill:0,rest_max_deg:45,squash:[.8,1.2]};
  const props={defaults,overrides:{},disabled:false,onSave:async value=>{editorCalls.push(value);return true}};
  const allNodes=node=>Array.isArray(node)?node.flatMap(allNodes):node?.children?[node,...node.children.flatMap(allNodes)]:[];
  const nodes=()=>allNodes(renderEditor(props));
  const input=label=>nodes().find(node=>node.tag==='label'&&node.children[0]===label).children.find(node=>node?.tag==='input');
  assert.equal(input('Gain').props.value,'0.9','editor starts with pre-clothing values');
  input('Gain').props.onChange({target:{value:'.8'}});
  props.defaults={...defaults,gain:.216};
  assert.equal(input('Gain').props.value,'.8','poll must preserve pending draft');
  assert.equal(editorCalls.length,0,'typing does not save');
  input('Gain').props.onKeyDown({key:'Enter',preventDefault(){}});
  await Promise.resolve();
  assert.deepEqual(editorCalls.pop(),{gain:.8},'Enter sends exactly edited overrides');
  input('Flatten').props.onChange({target:{value:'2'}});
  assert.equal(input('Flatten').props['aria-invalid'],true);
  assert.equal(nodes().find(node=>node.tag==='button'&&node.children[0]==='Save').props.disabled,true);
  nodes().find(node=>node.tag==='button'&&node.children[0]==='Reset').props.onClick();
  await Promise.resolve();
  assert.equal(editorCalls.pop(),undefined,'Reset deletes overrides');
  assert.match(fieldSource,/key=\{`\$\{character\}:\$\{st.model\?\.signature/);
  console.log('ok character draft survives polling, Enter saves edited overrides, validates and resets');
  }


  // n=(1,0,1)/sqrt(2), t=(1,0,-1)/sqrt(2). Stock dot is (2-.25)/2=.875.
  const S=new THREE.Matrix3().set(Math.SQRT2,0,0,0,Math.SQRT2,0,0,0,.5);
  const n=new THREE.Vector3(1,0,1).normalize(), tangent=new THREE.Vector3(1,0,-1).normalize();
  const transformedT=tangent.clone().applyMatrix3(S);
  near(n.clone().applyMatrix3(S).dot(transformedT),.875,1e-12);
  near(n.clone().applyMatrix3(S.clone().transpose().invert()).normalize().dot(transformedT),0,1e-12);
  for(const uniform of [1,2]) {
    const R=new THREE.Matrix3().setFromMatrix4(new THREE.Matrix4().makeRotationY(.7)).multiplyScalar(uniform);
    near(n.clone().applyMatrix3(R).normalize().distanceTo(n.clone().applyMatrix3(R.clone().transpose().invert()).normalize()),0,1e-12);
  }
  const installedChunk=THREE.ShaderChunk.skinnormal_vertex; C.installSkinnedNormalCorrection(THREE);
  assert.equal(THREE.ShaderChunk.skinnormal_vertex,installedChunk);
  assert.match(installedChunk,/objectTangent = normalize\(mat3\(skinMatrix\) \* objectTangent\)/);
  console.log('ok GLSL mirrored inverse-transpose, tangent perpendicularity, rigid/uniform parity and one-time installation');

  // Oblique parent c=(1,0,1), root Rx(-90). Let d=9.81/omega².
  // Parent unconstrained local equilibrium=(1,d,1-d); Q maps c to it.
  // Forced length 1.4 gives D=Q*[a I+(1.4-a)uu^T], a=1/sqrt(1.4).
  // Child T=Rx(-90)*D*(offset+c_child); pure R=Rx(-90)*Q.
  // Child equilibrium=T+[g-R*g]/omega², independent of parent's shear.
  const cr=new THREE.Group(), ca=new THREE.Bone(), cp=new THREE.Bone(), cc=new THREE.Bone();
  cr.add(ca); ca.add(cp); cp.add(cc); cp.name='extra'; cc.name='extra_child'; cc.position.set(.2,0,.5);
  const cg=new THREE.BufferGeometry();
  cg.setAttribute('position',new THREE.Float32BufferAttribute([1,0,1,1.2,0,2],3));
  cg.setAttribute('skinIndex',new THREE.Uint16BufferAttribute([1,0,0,0,2,0,0,0],4));
  cg.setAttribute('skinWeight',new THREE.Float32BufferAttribute([1,0,0,0,1,0,0,0],4));
  const cm=new THREE.SkinnedMesh(cg,new THREE.MeshBasicMaterial());cr.add(cm);cr.updateMatrixWorld(true);cm.bind(new THREE.Skeleton([ca,cp,cc]));
  const cs=C.createSecondaryMotion(THREE,cr,{rev:'oblique-chain',groups:{child:{...defaults,bones:['extra_child']},parent:{...defaults,squash:[1.4,1.4]}}});
  ca.rotation.x=-Math.PI/2;for(let i=0;i<1800;i++)cs.update(1/120);
  const d=9.81/(4*Math.PI)**2;
  const pq=new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(1,0,1).normalize(),new THREE.Vector3(1,d,1-d).normalize());
  const rq=new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1,0,0),-Math.PI/2);
  const axis=new THREE.Vector3(1,0,1).normalize(), transverse=1/Math.sqrt(1.4);
  const scaleVector=v=>v.clone().multiplyScalar(transverse).addScaledVector(axis,(1.4-transverse)*v.dot(axis));
  const expected=scaleVector(new THREE.Vector3(1.2,0,2)).applyQuaternion(pq).applyQuaternion(rq);
  expected.add(new THREE.Vector3(0,-9.81,0).sub(new THREE.Vector3(0,-9.81,0).applyQuaternion(rq.clone().multiply(pq))).multiplyScalar(1/(4*Math.PI)**2));
  const actual=cm.applyBoneTransform(1,new THREE.Vector3(1.2,0,2));near(actual.distanceTo(expected),0,2e-5);
  console.log('ok hand-derived oblique stretched chain with parent dynamics and child gravity');

  // Two primitives: c1=(0,0,1), c2=bindMatrix*(-2,0,3)=(0,0,3); average=(0,0,2).
  const multi=fixture();multi.solver.dispose();multi.bone.rotation.set(0,0,0);multi.root.updateMatrixWorld(true);
  multi.mesh.geometry.setAttribute('position',new THREE.Float32BufferAttribute([0,0,1,0,0,1,0,0,1],3));
  multi.mesh.bind(new THREE.Skeleton([multi.anchor,multi.bone]));
  const otherGeometry=multi.mesh.geometry.clone();otherGeometry.setAttribute('position',new THREE.Float32BufferAttribute([-2,0,3,-2,0,3,-2,0,3],3));
  const other=new THREE.SkinnedMesh(otherGeometry,new THREE.MeshBasicMaterial());multi.root.add(other);
  other.bind(multi.mesh.skeleton,new THREE.Matrix4().makeTranslation(2,0,0));
  multi.solver=C.createSecondaryMotion(THREE,multi.root,payload());multi.anchor.rotation.x=-Math.PI/2;settle(multi);
  const multiCentre=new THREE.Vector3(0,0,2).applyMatrix4(multi.bone.matrixWorld);
  near(multiCentre.y,2-d);near(multiCentre.z,-d);
  console.log('ok multi-mesh centroid and non-identity bind matrix');

  const replacement=fixture();replacement.anchor.rotation.x=-Math.PI/2;replacement.solver.update(0);
  near(replacement.point().distanceTo(new THREE.Vector3(0,1-9.81/(4*Math.PI)**2,-9.81/(4*Math.PI)**2)),0);
  replacement.solver.update(1/120,{far:true});near(replacement.point().distanceTo(new THREE.Vector3(0,1-9.81/(4*Math.PI)**2,-9.81/(4*Math.PI)**2)),0);
  replacement.solver.update(0,{far:false});near(replacement.point().distanceTo(new THREE.Vector3(0,1-9.81/(4*Math.PI)**2,-9.81/(4*Math.PI)**2)),0);
  cs.dispose();assert.equal(cc.matrixAutoUpdate,true);
  console.log('ok skeleton replacement and tier transition start with fresh particles');
  const cacheFixture=fixture();cacheFixture.solver.dispose();
  const weightAttribute=cacheFixture.mesh.geometry.getAttribute('skinWeight');
  const originalComponent=weightAttribute.getComponent.bind(weightAttribute);let reads=0;
  weightAttribute.getComponent=(...args)=>{reads++;return originalComponent(...args);};
  const cachedA=C.createSecondaryMotion(THREE,cloneSkeleton(cacheFixture.root),payload(),cacheFixture.root);
  assert.ok(reads>0);const firstReads=reads;
  const cachedB=C.createSecondaryMotion(THREE,cloneSkeleton(cacheFixture.root),payload(),cacheFixture.root);
  assert.equal(reads,firstReads);cachedA.dispose();cachedB.dispose();
  weightAttribute.getComponent=originalComponent;
  const counts={vectors:0,quaternions:0,matrices:0};
  const injected={...THREE,
    Vector3:class extends THREE.Vector3{constructor(...args){super(...args);counts.vectors++;}},
    Quaternion:class extends THREE.Quaternion{constructor(...args){super(...args);counts.quaternions++;}},
    Matrix4:class extends THREE.Matrix4{constructor(...args){super(...args);counts.matrices++;}},
  };
  const fast=fixture();fast.solver.dispose();
  const empty=C.createSecondaryMotion(injected,fast.root,undefined);
  const absent=C.createSecondaryMotion(injected,fast.root,payload({bones:['missing']}));
  empty.update(1/120);absent.configure(payload({bones:['missing']}));absent.update(1/120);
  assert.deepEqual(counts,{vectors:0,quaternions:0,matrices:0});empty.dispose();absent.dispose();
  const active=C.createSecondaryMotion(injected,fast.root,payload());active.update(0);
  counts.vectors=counts.quaternions=counts.matrices=0;fast.anchor.rotation.x=-.7;
  for(let i=0;i<20;i++)active.update(1/30);
  assert.deepEqual(counts,{vectors:0,quaternions:0,matrices:0});active.dispose();
  console.log('ok template centroid cache, empty/unmatched setup skips and allocation-free frame/substep scratch');
  console.log('secondary motion: all checks passed');
} finally {await rm(dir,{recursive:true,force:true});}
