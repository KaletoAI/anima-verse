#!/usr/bin/env node
/**
 * Usage: node client3d/scripts/smoke_secondary_motion.mjs
 * Hand derivation, metres/seconds, Y-up gravity (0,-9.81,0):
 * omega²=(4*pi)²=157.9136704. With m=2 upright a_g=(0,-9.81,0)
 * gives e_y=-9.81/omega²=-0.06212255072; m=1 gives 0 and m=.5 gives
 * +0.03106127536. Group gravity scales both baked and current gravity.
 * Direct targets replace the old force-based flatten/spill expectations:
 * f_in=clamp(-g_hat.dot(u),0,1), s=1-flatten*(1-min)*f_in.
 * f_in=1, flatten=1, min=.5 gives s=.5 at 1.5 and 4 Hz;
 * f_in=.5 gives .75. Spill=.5 and spill_max=30 (sag=5) gives 15 degrees
 * outward with opposite X signs. Paired width compensation is 1/s.
 * Remaining inward axial force is removed, transverse e=force/omega²
 * rotates the lever while preserving the direct target length.
 * Translate=1 moves the head by sin(atan(d))*lever_length for a unit
 * horizontal lever and d=9.81/(4*pi)^2; translate=0 keeps its head fixed.
 * Static T' uses the bounded sag direction and direct length target,
 * independently of gain and dynamic max_deg. Resets, far
 * LOD and gain zero retain T'. Rest rotation blends over 1.5 real seconds.
 * Static sag_max_deg and squash bound T'; dynamic angles are linear up to
 * max_deg/2, then max_deg/2*(1+tanh((angle-max_deg/2)/(max_deg/2))).
 * This C1 function is strictly monotonic and bounded by max_deg. Gain is
 * applied AFTER saturation. A critical spring with body velocity V has
 * d=-V*t*exp(-omega*t), independent of gravity: at V=3,t=1/30,
 * d_x=-0.065778376882. Bent-forward gravity 0/3 share this raw dynamic
 * response; the rendered transverse swing preserves each static length.
 * Weighted centroid (.25*z1+.75*z3)=2.5; after -90 X direction=(0,2.5,-d), length=2.5.
 * f=20 has 1/100 of the f=2 offset; damping does not change equilibrium.
 * Client centering subtracts 1 from Y after -90 X.
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
  const result = await build({ stdin: { contents: "export * from '@anima/scene-render'; export { Figure, adaptExternalClips } from './client3d/src/scene/figures'", resolveDir: process.cwd(), loader: 'ts' }, bundle: true, platform: 'node', format: 'esm', write: false, external: ['three','three/*'] });
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

  const defaults = { bones: ['extra'], freq_hz: 2, zeta: 1, gravity: 1, gravity_scale: 1, translate: 0, flatten: 0, sag_max_deg: 180, spill: 0, gain: 1, max_deg: 180, squash: [0.1,3], rest_deg: 0, rest_max_deg: 90 };
  const payload = (params={}) => ({ rev: JSON.stringify(params), groups: { test: { ...defaults, ...params } } });
  function fixture(params={}) {
    const root = new THREE.Group(), anchor = new THREE.Bone(), bone = new THREE.Bone();
    root.add(anchor); bone.name='extra'; anchor.add(bone);
    // Attachment points forward while the driven head remains at the origin.
    const mount=new THREE.Bone(); mount.position.z=-1; anchor.add(mount); mount.add(bone); bone.position.z=1;
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
  // f_in=1 at -90 X, .5 at -30 X: 1-flatten*(1-min)*f_in.
  for (const freq_hz of [0,1.5,4]) for (const [angle,length] of [[-90,.5],[-30,.75]]) {
    const probe=fixture({freq_hz,flatten:1,squash:[.5,2],gravity:0});
    probe.anchor.rotation.x=angle*Math.PI/180;probe.solver.update(0);
    near(probe.point().length(),length);probe.solver.dispose();
  }
  console.log('ok direct flatten targets: .5 at 1.5/4 Hz; .75 at f_in=.5');
  for(const translate of [0,.6,1]) {
    const probe=fixture({gravity_scale:2,translate,sag_max_deg:30,max_deg:30});probe.solver.update(0);
    const d=9.81/(4*Math.PI)**2, distance=d/Math.hypot(1,d);
    const head=probe.bone.getWorldPosition(new THREE.Vector3());
    near(head.y,-translate*distance,1e-10);
    if(translate===1)near(probe.point().clone().sub(head).angleTo(new THREE.Vector3(0,0,1)),0,1e-10);
    else if(translate===0)near(Math.atan2(probe.point().y,probe.point().z),-Math.atan(d),1e-10);
    console.log('translate static metres',JSON.stringify({translate,headY:head.y,derived:-translate*distance}));probe.solver.dispose();
  }
  // Dynamic critical response d=-3*t*exp(-4*pi*t). After limits/gain,
  // the unit lever's transverse displacement is d/hypot(1,d).
  const moving=fixture({gravity:0,translate:1,max_deg:30});moving.solver.update(0);
  moving.root.position.y=.1;moving.solver.update(1/30);
  const dynamicD=-.1*Math.exp(-4*Math.PI/30), movingHead=moving.bone.getWorldPosition(new THREE.Vector3());
  near(movingHead.y,.1+dynamicD/Math.hypot(1,dynamicD),1e-10);
  near(moving.point().z,1,1e-10);moving.solver.dispose();
  // Combined sag and transverse impulse must share the rest lever projection.
  // At translate=1 both transverse components leave rotation zero; axial
  // length still follows 1+d.dot(staticUnit), independently of the split.
  const combined=fixture({gravity_scale:2,translate:1,sag_max_deg:30,max_deg:30});combined.solver.update(0);
  combined.root.position.y=.1;combined.solver.update(1/30);
  const combinedHead=combined.bone.getWorldPosition(new THREE.Vector3());
  const combinedLever=combined.point().clone().sub(combinedHead.clone().sub(combined.root.position));
  near(combinedLever.angleTo(new THREE.Vector3(0,0,1)),0,1e-10);
  combined.solver.dispose();
  for(const direction of [new THREE.Vector3(0,1,0),new THREE.Vector3(0,0,1)]) {
    const lengths=[];
    for(const translate of [0,1]) {
      const probe=fixture({gravity_scale:2,translate,sag_max_deg:30,max_deg:30});probe.solver.update(0);
      probe.root.position.copy(direction).multiplyScalar(.1);probe.solver.update(1/30);
      const localHead=probe.bone.getWorldPosition(new THREE.Vector3()).sub(probe.root.position);
      lengths.push(probe.point().sub(localHead).length());probe.solver.dispose();
    }
    near(lengths[0],lengths[1],1e-10);
  }
  // A saturated force has angle 30 degrees, unit lever, so translated
  // head magnitude cannot exceed sin(30)=.5; gain=0 keeps the static term.
  const capped=fixture({gravity_scale:3,gravity:100,translate:1,sag_max_deg:30,gain:0});capped.solver.update(0);
  near(capped.bone.getWorldPosition(new THREE.Vector3()).length(),.5,1e-10);capped.solver.dispose();



  assert.equal(hints.motionFieldPreview.axis_gain,'motion');
  // d=-3*t*exp(-4*pi*t)=-.065778376882 at t=1/30. Length=1+d_long;
  // transverse rotation=atan(d_transverse), with no dynamic length change.
  const displacement=-3/30*Math.exp(-4*Math.PI/30);
  const impulse=(direction,axis_gain)=>{
    const f=fixture({gravity:0,axis_gain}); f.solver.update(0);
    f.root.position.copy(direction).multiplyScalar(.1);f.solver.update(1/30);
    const tip=f.point();f.solver.dispose();return tip;
  };
  const full=impulse(new THREE.Vector3(0,0,1),[1,1,1]);
  const reduced=impulse(new THREE.Vector3(0,0,1),[1,1,.2]);
  near(full.length()-1,displacement,1e-10);near(reduced.length()-1,.2*displacement,1e-10);
  const upFull=impulse(new THREE.Vector3(0,1,0),[1,1,1]);
  const upReduced=impulse(new THREE.Vector3(0,1,0),[1,1,.2]);
  near(upFull.distanceTo(upReduced),0,1e-10);near(upFull.length(),1,1e-10);
  near(Math.atan2(upFull.y,upFull.z),Math.atan(displacement),1e-10);
  const side=impulse(new THREE.Vector3(1,0,0),[.5,1,1]);
  near(Math.atan2(side.x,side.z),Math.atan(.5*displacement),1e-10);near(side.length(),1,1e-10);
  for(const params of [{gravity_scale:2},{rest_deg:45},{flatten:.5,spill:.5}]){
    const a=fixture(params),b=fixture({...params,axis_gain:[0,0,0]});
    a.anchor.rotation.x=b.anchor.rotation.x=-Math.PI/2;
    a.solver.update(0);b.solver.update(0);near(a.point().distanceTo(b.point()),0,1e-10);
    a.solver.dispose();b.solver.dispose();
  }
  console.log('axis_gain numbers',JSON.stringify({lengthFull:full.length()-1,lengthReduced:reduced.length()-1,verticalAngle:Math.atan2(upFull.y,upFull.z),lateralHalfAngle:Math.atan2(side.x,side.z)}));
  // Rolled imported axes and a moved anchor: body up follows Rx(-90),
  // hence world -Z is vertical for the resulting +Y lever.
  for(const [lever,rotation,axis,expectedGain] of [
    [[0,0,1],-Math.PI/2,[0,0,-1],.3],
    [[0,1,0],0,[0,0,1],.3], // vertical lever uses body front +Z
    [[0,1,0],0,[1,0,0],.5],
  ]){
    const f=fixture();f.solver.dispose();
    f.mesh.geometry.setAttribute('position',new THREE.Float32BufferAttribute([...lever,...lever,...lever],3));
    f.solver=C.createSecondaryMotion(THREE,f.root,payload({gravity:0,axis_gain:[.5,.3,.2]}));
    f.anchor.rotation.x=rotation;f.solver.update(0);
    const base=f.mesh.applyBoneTransform(2,new THREE.Vector3(...lever)).normalize();
    f.root.position.set(...axis).multiplyScalar(.1);f.solver.update(1/30);
    const tip=f.mesh.applyBoneTransform(2,new THREE.Vector3(...lever));
    near(tip.length(),1,1e-10);
    near(tip.angleTo(base),Math.atan(-displacement*expectedGain),1e-10);f.solver.dispose();
  }
  // Live field change filters the retained particle, without resetting it.
  const liveAxis=fixture({gravity:0});liveAxis.solver.update(0);
  liveAxis.root.position.z=.1;liveAxis.solver.update(1/30);
  liveAxis.solver.configure(payload({gravity:0,axis_gain:[1,1,.2]}));liveAxis.solver.update(0);
  near(liveAxis.point().length()-1,.2*displacement,1e-10);liveAxis.solver.dispose();
  const strongAxial=fixture({gravity:0});strongAxial.solver.update(0);
  // V=60 gives d=-1.31556753764: squash min=.1, pure compression has no swing.
  strongAxial.root.position.z=2;strongAxial.solver.update(1/30);
  near(strongAxial.point().z,.1,1e-10);near(strongAxial.point().x,0,1e-10);near(strongAxial.point().y,0,1e-10);
  strongAxial.solver.dispose();
  console.log('ok anchor-rotated body frame, vertical-lever front fallback and live axis reconfigure');
  console.log('ok axial .2 ratio, identical vertical rotation, lateral .5, transverse length invariant, static unchanged');
  // Rx(-a)*(0,-1,0)=(0,-cos(a),sin(a)); Rx(-a)*(0,0,1)=(0,sin(a),cos(a)).
  for (const [lever, angle, limit, expected] of [
    [[0,-1,0],90,180,[0,0,1]], [[0,-1,0],-90,180,[0,0,-1]],
    [[0,0,1],45,180,[0,Math.SQRT1_2,Math.SQRT1_2]],
    [[0,-1,0],170,180,[0,-Math.cos(170*Math.PI/180),Math.sin(170*Math.PI/180)]],
    [[0,-1,0],170,90,[0,0,1]],
  ]) {
    const f=fixture(); f.solver.dispose();
    f.mesh.geometry.setAttribute('position',new THREE.Float32BufferAttribute([...lever,...lever,...lever],3));
    f.solver=C.createSecondaryMotion(THREE,f.root,payload({gravity:0,gain:0,rest_deg:angle,rest_max_deg:limit}));
    f.solver.update(0);
    const actual=f.mesh.applyBoneTransform(2,new THREE.Vector3(...lever));
    near(actual.distanceTo(new THREE.Vector3(...expected)),0); f.solver.dispose();
  }
  console.log('ok signed front/up rest convention and effective 170/180 versus 170/90 clamp');
  // Real Figure oracle: bind link rotated toward horizontal attachment offset.
  // Rest 30/60/90 must survive max_deg=35; child local rotation stays bind.
  // Optional real-model oracle (needs a rigged GLB outside the repo):
  //   SECONDARY_RIG_PATH=<file.glb> SECONDARY_RIG_BONES=<root bone>,<child bone>
  const realRigPath=process.env.SECONDARY_RIG_PATH||'';
  const realRigBones=(process.env.SECONDARY_RIG_BONES||'').split(',').map(s=>s.trim()).filter(Boolean);
  if(!realRigPath||realRigBones.length<2){console.log('skip real Figure rest oracle: set SECONDARY_RIG_PATH and SECONDARY_RIG_BONES');}
  else {
  globalThis.self=globalThis;
  const {GLTFLoader}=await import('three/addons/loaders/GLTFLoader.js');
  const loader=new GLTFLoader();loader.register(()=>({name:'geometry_only',loadTexture:()=>Promise.resolve(null)}));
  const path=realRigPath;
  const bytes=await readFile(path),rig=(await loader.parseAsync(bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength),'')).scene;
  const names=realRigBones;
  for(const yaw of [0,Math.PI])for(const angle of [30,60,90,-45]){
    const params={bones:names,gravity:0,gain:1,max_deg:35,rest_max_deg:180,squash:[1,1]};
    const holder={payload:payload({...params,rest_deg:0})};
    const fig=new C.Figure({name:'rig-smoke',template:rig,clips:[],scale:1,height:1,assignOnly:true,noClips:true,tier:'full',libraryFits:true,motion:holder});
    fig.faceTowards(new THREE.Vector3(Math.sin(yaw),0,Math.cos(yaw)),true);fig.update(0,{realDelta:0});
    const bones=names.map(name=>{let b;fig.root.traverse(o=>{if(o.isBone&&o.name===THREE.PropertyBinding.sanitizeNodeName(name))b=o;});assert.ok(b);return b;});
    const [r,c]=bones,head=o=>o.getWorldPosition(new THREE.Vector3()),direction=()=>head(c).sub(head(r)).normalize();
    const centroid=()=>{const sum=new THREE.Vector3();let total=0;fig.root.updateMatrixWorld(true);fig.root.traverse(m=>{if(!m.isSkinnedMesh)return;const pos=m.geometry.getAttribute('position'),idx=m.geometry.getAttribute('skinIndex'),w=m.geometry.getAttribute('skinWeight');for(let i=0;i<pos.count;i++){let weight=0;for(let j=0;j<4;j++)if(bones.includes(m.skeleton.bones[idx.getComponent(i,j)]))weight+=w.getComponent(i,j);if(weight>0){sum.addScaledVector(m.applyBoneTransform(i,new THREE.Vector3().fromBufferAttribute(pos,i)).applyMatrix4(m.matrixWorld),weight);total+=weight;}}});return sum.divideScalar(total);};
    const front=head(r).sub(head(r.parent));front.y=0;front.normalize();
    const before=direction(),centre=centroid(),local=new THREE.Quaternion().setFromRotationMatrix(c.matrix).normalize(),axis=before.clone().cross(front).normalize();
    holder.payload=payload({...params,rest_deg:angle});for(let i=0;i<720;i++)fig.update(0,{realDelta:1/120});
    const actual=direction(),delta=centroid().sub(centre),measured=Math.atan2(actual.dot(axis.clone().cross(before)),actual.dot(before))*180/Math.PI;
    const kink=new THREE.Quaternion().setFromRotationMatrix(c.matrix).normalize().angleTo(local)*180/Math.PI;
    console.log('real Figure rest',JSON.stringify({yaw:yaw*180/Math.PI,requested:angle,measured,kink,front:delta.dot(front),up:delta.y}));
    near(actual.angleTo(before.clone().applyAxisAngle(axis,angle*Math.PI/180))*180/Math.PI,0,2);near(kink,0,2);assert.ok(angle>0?delta.dot(front)>0&&delta.y>0:delta.dot(front)<0);fig.dispose();
  }
  }
  const walkRigPath=process.env.SECONDARY_WALK_RIG_PATH;
  const walkNames=(process.env.SECONDARY_WALK_BONES||'').split(',').map(s=>s.trim()).filter(Boolean);
  const walkClipPath=process.env.SECONDARY_WALK_CLIP;
  if(!walkRigPath||!walkNames.length){
    console.log('skip real static/walk oracle: set SECONDARY_WALK_RIG_PATH and SECONDARY_WALK_BONES; walk also needs SECONDARY_WALK_CLIP');
  }else{
    assert.equal(walkNames.length,2,'walk oracle requires exactly the two paired bones');
    globalThis.self=globalThis;
    const {GLTFLoader}=await import('three/addons/loaders/GLTFLoader.js');
    const {FBXLoader}=await import('three/addons/loaders/FBXLoader.js');
    const buffer=bytes=>bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength);
    const loader=new GLTFLoader();loader.register(()=>({name:'geometry_only',loadTexture:()=>Promise.resolve(null)}));
    const rig=(await loader.parseAsync(buffer(await readFile(walkRigPath)), '')).scene;
    // Real path uses only command-line environment inputs. Measure actual
    // skinned vertices, including the weighted border and the upper subset.
    const measureStatic=(translate,lying=false,active=true)=>{
      const params={bones:walkNames,freq_hz:2.2,zeta:.15,gravity:active ? .35 : 0,
        gravity_scale:2,translate,flatten:lying&&active?1:0,spill:0,
        sag_max_deg:30,max_deg:30,squash:[.5,1.4],gain:0};
      const fig=new C.Figure({name:'static-oracle',template:rig,clips:[new THREE.AnimationClip('idle',1,[])],scale:1,height:1,
        assignOnly:true,noClips:false,tier:'full',libraryFits:true,motion:{payload:payload(params)}});
      try{
        fig.faceTowards(new THREE.Vector3(0,0,1),true);fig.update(0,{realDelta:0});
        const bones=walkNames.map(name=>{let b;fig.root.traverse(o=>{if(o.isBone&&C.normBoneName(o.name)===C.normBoneName(name))b=o;});assert.ok(b);return b;});
        const samples=[];fig.root.traverse(m=>{if(!m.isSkinnedMesh)return;
          const pos=m.geometry.getAttribute('position'),idx=m.geometry.getAttribute('skinIndex'),w=m.geometry.getAttribute('skinWeight');
          for(let i=0;i<pos.count;i++)for(let side=0;side<2;side++){
            let weight=0;for(let j=0;j<4;j++)if(m.skeleton.bones[idx.getComponent(i,j)]===bones[side])weight+=w.getComponent(i,j);
            if(weight>0)samples.push({m,i,side,weight,upper:new THREE.Vector3().fromBufferAttribute(pos,i).applyMatrix4(m.matrixWorld).y>bones[side].getWorldPosition(new THREE.Vector3()).y});
          }
        });
        if(lying){fig.setLean(-90,0);fig.update(0,{realDelta:0});}
        const heads=bones.map(b=>b.getWorldPosition(new THREE.Vector3()));
        const totals=bones.map(()=>({sum:new THREE.Vector3(),weight:0}));
        for(const a of samples){const bi=a.m.skeleton.bones.indexOf(bones[a.side]);const p=new THREE.Vector3().fromBufferAttribute(a.m.geometry.getAttribute('position'),a.i).applyMatrix4(a.m.bindMatrix).applyMatrix4(a.m.skeleton.boneInverses[bi]);totals[a.side].sum.addScaledVector(p,a.weight);totals[a.side].weight+=a.weight;}
        const axes=totals.map((a,i)=>a.sum.divideScalar(a.weight).applyMatrix4(bones[i].matrixWorld).sub(heads[i]).normalize());
        let total=0,sum=0,upperTotal=0,upperSum=0;const extents=bones.map(()=>[Infinity,-Infinity]), allExtents=bones.map(()=>[Infinity,-Infinity]);
        for(const a of samples){const p=a.m.applyBoneTransform(a.i,new THREE.Vector3().fromBufferAttribute(a.m.geometry.getAttribute('position'),a.i)).applyMatrix4(a.m.matrixWorld);total+=a.weight;sum+=a.weight*p.y;if(a.upper){upperTotal+=a.weight;upperSum+=a.weight*p.y;}
          const along=p.clone().sub(heads[a.side]).dot(axes[a.side]);
          allExtents[a.side][0]=Math.min(allExtents[a.side][0],along);allExtents[a.side][1]=Math.max(allExtents[a.side][1],along);
          // Core weights >= .9 exclude the deliberately blended border.
          if(a.weight>=.9){const t=p.clone().sub(heads[a.side]).dot(axes[a.side]);extents[a.side][0]=Math.min(extents[a.side][0],t);extents[a.side][1]=Math.max(extents[a.side][1],t);}
        }
        assert.ok(upperTotal>0,'real rig must have weighted vertices above the head');
        for(const extent of extents)assert.ok(Number.isFinite(extent[0])&&extent[1]>extent[0],'height oracle requires a core with weights >= .9');
        return {centroidY:sum/total,upperY:upperSum/upperTotal,heights:extents.map(e=>e[1]-e[0]),allHeights:allExtents.map(e=>e[1]-e[0])};
      }finally{fig.dispose();}
    };
    const baseline=measureStatic(0,false,false), rotation=measureStatic(0), translated=measureStatic(.6);
    const movement=value=>({centroidDown:value.centroidY-baseline.centroidY,upperDown:value.upperY-baseline.upperY});
    console.log('real static standing metres',JSON.stringify({translate0:movement(rotation),translate06:movement(translated)}));
    assert.ok(translated.centroidY<baseline.centroidY&&translated.upperY<baseline.upperY,'whole group and upper subset must move down');
    assert.ok(translated.upperY<rotation.upperY,'translation lowers upper subset relative to rotation');
    const lyingBase=measureStatic(0,true,false),lyingFlat=measureStatic(0,true,true);
    const ratios=lyingFlat.heights.map((h,i)=>h/lyingBase.heights[i]);
    console.log('real static lying core (weights >= .9) lever extents metres',JSON.stringify({before:lyingBase.heights,after:lyingFlat.heights,ratios}));
    console.log('real static lying full border lever extents metres',JSON.stringify({before:lyingBase.allHeights,after:lyingFlat.allHeights,ratios:lyingFlat.allHeights.map((h,i)=>h/lyingBase.allHeights[i])}));
    for(const ratio of ratios)near(ratio,.5,.08);
    if(!walkClipPath){console.log('skip real walk oracle: set SECONDARY_WALK_CLIP');}else{
    const donor=new FBXLoader().parse(buffer(await readFile(walkClipPath)), '');
    assert.ok(donor.animations.length,'walk FBX must contain an animation');
    const clip=donor.animations[0].clone();clip.name='walk';
    const clips=C.adaptExternalClips([clip],rig);
    assert.equal(clips.length,1,'walk must adapt onto the real rig');
    const results=[];
    for(const axis_gain of [[1,1,1],[.5,1,.15]]){
      const fig=new C.Figure({name:'walk-oracle',template:rig,clips,scale:1,height:1,
        assignOnly:true,noClips:false,tier:'full',libraryFits:true,
        motion:{payload:payload({bones:walkNames,axis_gain,freq_hz:2.2,zeta:.15,gravity:.35,
          flatten:0,spill:0,sag_max_deg:25,max_deg:25,squash:[.6,1.4]})}});
      try{
        const bones=walkNames.map(name=>{let found;fig.root.traverse(o=>{
          if(o.isBone&&C.normBoneName(o.name)===C.normBoneName(name))found=o;
        });assert.ok(found,'missing requested paired bone');return found;});
        assert.equal(bones[0].parent,bones[1].parent,'paired roots must share the body anchor');
        const body=bones[0].parent;
        // Weighted bind centroid is a reproducible tip proxy, independently
        // derived from bind vertices. BODY = animated common parent frame.
        const tips=bones.map(bone=>{
          const sum=new THREE.Vector3();let total=0;
          fig.root.traverse(m=>{if(!m.isSkinnedMesh)return;
            const pos=m.geometry.getAttribute('position'),idx=m.geometry.getAttribute('skinIndex'),w=m.geometry.getAttribute('skinWeight');
            const bi=m.skeleton.bones.indexOf(bone);if(bi<0)return;
            const intoBone=m.skeleton.boneInverses[bi].clone().multiply(m.bindMatrix);
            for(let i=0;i<pos.count;i++)for(let j=0;j<4;j++)if(idx.getComponent(i,j)===bi){
              const weight=w.getComponent(i,j);if(weight<=0)continue;
              sum.addScaledVector(new THREE.Vector3().fromBufferAttribute(pos,i).applyMatrix4(intoBone),weight);total+=weight;
            }
          });assert.ok(total>0,'requested bone must influence mesh');return sum.divideScalar(total);
        });
        fig.root.updateMatrixWorld(true);
        const bindBodyQ=body.getWorldQuaternion(new THREE.Quaternion()).invert();
        const up=new THREE.Vector3(0,1,0).applyQuaternion(bindBodyQ);
        const front=new THREE.Vector3();
        for(const bone of bones)front.add(bone.getWorldPosition(new THREE.Vector3()).sub(body.getWorldPosition(new THREE.Vector3())));
        front.y=0;
        if(front.lengthSq()<1e-10){for(let i=0;i<2;i++)front.add(tips[i].clone().applyMatrix4(bones[i].matrixWorld).sub(bones[i].getWorldPosition(new THREE.Vector3())));front.y=0;}
        assert.ok(front.lengthSq()>1e-10,'pair must define body front');front.normalize().applyQuaternion(bindBodyQ);
        const bounds=bones.map(()=>({vertical:[Infinity,-Infinity],forward:[Infinity,-Infinity]}));
        fig.play('walk');const dt=1/120,cycle=clips[0].duration;
        assert.ok(cycle>0);
        for(let frame=0;frame<Math.ceil(8*cycle/dt);frame++){
          fig.update(dt,{realDelta:dt});if(frame*dt<2*cycle)continue;
          const bodyInverse=body.matrixWorld.clone().invert();
          for(let i=0;i<2;i++){
            const point=tips[i].clone().applyMatrix4(bones[i].matrixWorld).applyMatrix4(bodyInverse);
            for(const [key,value] of [['vertical',point.dot(up)],['forward',point.dot(front)]]){
              bounds[i][key][0]=Math.min(bounds[i][key][0],value);bounds[i][key][1]=Math.max(bounds[i][key][1],value);
            }
          }
        }
        const amplitudes=bounds.map((b,i)=>({bone:walkNames[i],vertical:b.vertical[1]-b.vertical[0],forward:b.forward[1]-b.forward[0]}));
        console.log('real Figure walk BODY peak-to-peak (metres)',JSON.stringify({axis_gain,amplitudes}));
        results.push(amplitudes);
      }finally{fig.dispose();}
    }
    for(const value of results[1])assert.ok(value.vertical>value.forward,'filtered walk must bob more vertically than forward');
    }
  }
  // At +45 rest a +Z lever is (0,q,q). Remove the inward axial
  // projection of the rotated gravity difference before normalizing.
  // Static sag remains around rotated rest even at max_deg=0 and gain=0.
  const restSag=fixture({rest_deg:45,gain:0,max_deg:0});restSag.solver.update(0);
  const restD=9.81/(4*Math.PI)**2;
  const restU=new THREE.Vector3(0,Math.SQRT1_2,Math.SQRT1_2);
  const restForce=new THREE.Vector3(0,-restD*(1-Math.SQRT1_2),-restD*Math.SQRT1_2);
  restForce.addScaledVector(restU,-restForce.dot(restU));
  const restExpected=restU.clone().add(restForce).normalize();
  near(restSag.point().distanceTo(restExpected),0);restSag.solver.dispose();
  console.log('ok static sag uses rotated rest independently of dynamic max_deg');
  const tilted = fixture({ gain: 0, flatten:1, squash:[.5,3] });
  hints.applyPreviewTilt(tilted.root, 90, 0);
  tilted.solver.update(0);
  const tiltD = 9.81 / (4 * Math.PI) ** 2;
  near(tilted.point().length(), .5);
  assert.ok(tilted.point().length() < 1, 'lying Tilt with flatten shortens');
  tilted.solver.dispose();
  console.log('ok preview hints cover payload fields; Tilt before solver shortens to 0.5');
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
  near(blended.flatten,.1); near(blended.spill,.4); near(blended.zeta,.5);
  near(C.blendMotionParams(defaults,{...defaults,gain:0},1.5).gain,0);
  console.log('ok P4 multipliers blend at hand-derived midpoint and endpoint');
  const zero=C.stepSecondaryParticle(new THREE.Vector3(1,0,0),new THREE.Vector3(2,0,0),new THREE.Vector3(),new THREE.Vector3(),{...defaults,freq_hz:0,zeta:5},.25);
  near(zero.p.x,1.5); near(zero.v.x,2);
  const noSpring=fixture({freq_hz:0,zeta:5}); noSpring.anchor.rotation.x=-Math.PI/2; settle(noSpring);
  near(noSpring.point().distanceTo(new THREE.Vector3(0,1,0)),0);
  console.log('ok P4 explicit zero frequency stays finite');
  let probe=fixture({gravity_scale:2}); settle(probe); near(probe.point().y,-9.81/(4*Math.PI)**2/Math.hypot(1,9.81/(4*Math.PI)**2)); console.log('ok upright m=2 sag');
  let f=fixture(); settle(f); near(f.point().distanceTo(new THREE.Vector3(0,0,1)),0); console.log('ok upright: zero displacement');
  f.anchor.rotation.x=-Math.PI/2; f.solver.reset(); settle(f);
  near(f.point().distanceTo(new THREE.Vector3(0,1,-9.81/(4*Math.PI)**2).normalize()),0); near(f.point().length(),1); console.log('ok static tilt equilibrium preserves direct target length');
  near(f.bone.matrix.determinant(),1); console.log('ok directional scale preserves volume');
  // Roots +/-0.2 X; bind lever (0,-q,q), q=sqrt(1/2). After -90 X
  // lever=(0,q,q), dG=(0,-9.81,-9.81), purely inward magnitude 9.81 sqrt(2).
  // f_in=q, so the direct outward angle is spill*180*q degrees.
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
  for(const freq_hz of [1.5,4]) {
    const direct=pairFixture(.5,true,{freq_hz,gravity:0,flatten:1,squash:[.5,2],sag_max_deg:5,spill_max_deg:30});
    // Pair lever +Y after -135 X, so f_in=1 and spill=.5*30=15 deg.
    direct.anchor.rotation.x=-3*Math.PI/4;direct.solver.update(0);
    for(let i=0;i<2;i++) {
      near(direct.point(i).y,.5*Math.cos(Math.PI/12));
      near(direct.point(i).x,(i===0?-1:1)*(.2+.5*Math.sin(Math.PI/12)));
    }
    console.log('direct pair targets',JSON.stringify({freq_hz,length:.5,outwardDegrees:15,offset:.5*Math.sin(Math.PI/12)}));
    direct.solver.dispose();
  }
  // Paired mean attachment is zero: mean centroid selects +Z front.
  // Each lever (0,-q,q) rotates about its own -X axis: at 60 degrees
  // y=sin(15 degrees), z=cos(15 degrees); max_deg=0 cannot limit rest.
  const restPair=pairFixture(0,true,{gravity:0,gain:1,max_deg:0,rest_deg:60,squash:[1,1]});
  restPair.solver.update(0);
  for(let i=0;i<2;i++){near(restPair.point(i).x,i===0?-.2:.2);near(restPair.point(i).y,Math.sin(Math.PI/12));near(restPair.point(i).z,Math.cos(Math.PI/12));}
  restPair.solver.dispose();console.log('ok paired centroid-derived front and independent root rest axes');
  for(const spill of [0,.5]) {
    const pair=pairFixture(spill); settle(pair);
    for(let i=0;i<2;i++) near(pair.point(i).x,i===0?-.2:.2);
    pair.anchor.rotation.x=-Math.PI/2; pair.solver.reset(); settle(pair);
    const spillRadians=spill*Math.PI*Math.SQRT1_2;
    const outward=Math.sin(spillRadians);
    for(let i=0;i<2;i++) {
      near(pair.point(i).x,(i===0?-1:1)*(.2+outward));
      near(pair.point(i).y,Math.SQRT1_2*Math.cos(spillRadians)); near(pair.point(i).z,Math.SQRT1_2*Math.cos(spillRadians));
      if(spill===0) near(pair.point(i).distanceTo(new THREE.Vector3(i===0?-.2:.2,0,0)),1);
    }
    pair.solver.dispose();
  }
  const single=pairFixture(.5,false); single.anchor.rotation.x=-Math.PI/2; settle(single);
  near(single.point(0).y,Math.SQRT1_2); near(single.point(0).x,-.2);
  console.log('ok spill pair equilibrium, no inward collapse, upright and single-chain behavior');
  const flatPair=pairFixture(.5,true,{flatten:.5});
  flatPair.anchor.rotation.x=-Math.PI/2; settle(flatPair);
  const flatLength=1-.5*.9*Math.SQRT1_2;
  const spillRadians=.5*Math.PI*Math.SQRT1_2;
  const axialLength=flatLength*Math.cos(spillRadians), lateralOffset=flatLength*Math.sin(spillRadians);
  for(let i=0;i<2;i++) {
    near(flatPair.point(i).x,(i===0?-1:1)*(.2+lateralOffset));
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
  const axisFlat=pairFixture(.5,true,{flatten:.5,axis_gain:[0,0,0]});
  axisFlat.anchor.rotation.x=-Math.PI/2;settle(axisFlat);
  for(let i=0;i<2;i++)near(axisFlat.point(i).distanceTo(new THREE.Vector3(
    (i===0?-1:1)*(.2+lateralOffset),Math.SQRT1_2*axialLength,Math.SQRT1_2*axialLength)),0,1e-7);
  axisFlat.solver.dispose();
  console.log('ok paired static flatten/spill unchanged with zero axis gains');
  // At -90 X, original lever is +Y and bounded force displacement is
  // (0, 1/hypot(1,d)-1, -d/hypot(1,d)). Bind body up is -Z.
  // head_sag=.3 changes only Z to -.3*d/hypot(1,d), preserving Y.
  const headProbe=fixture({head_sag:.3,squash:[1,1]});headProbe.anchor.rotation.x=-Math.PI/2;headProbe.solver.update(0);
  const headD=9.81/(4*Math.PI)**2;
  near(headProbe.point().y,1/Math.hypot(1,headD),1e-10);
  near(headProbe.point().z,-.3*headD/Math.hypot(1,headD),1e-10);
  console.log('head_sag numbers',JSON.stringify({bodyUpBefore:-headD/Math.hypot(1,headD),bodyUpAfter:headProbe.point().z,otherComponent:headProbe.point().y}));
  headProbe.solver.dispose();console.log('ok head_sag .3 scales only bind-up static displacement, even with squash [1,1]');
  const headDynamic=fixture({gravity:0,head_sag:.3,translate:1,max_deg:30});headDynamic.solver.update(0);
  headDynamic.root.position.y=.1;headDynamic.solver.update(1/30);
  near(headDynamic.bone.getWorldPosition(new THREE.Vector3()).y,.1+dynamicD/Math.hypot(1,dynamicD),1e-10);
  headDynamic.solver.dispose();
  const headDirect=pairFixture(.5,true,{gravity:0,head_sag:.3,sag_max_deg:5,spill_max_deg:30,flatten:1,squash:[.5,2]});
  headDirect.anchor.rotation.x=-3*Math.PI/4;headDirect.solver.update(0);
  near(headDirect.point(0).y,.5*Math.cos(Math.PI/12));near(headDirect.point(0).x,-.2-.5*Math.sin(Math.PI/12));
  headDirect.solver.dispose();console.log('ok head_sag leaves dynamics, flatten and spill unchanged');
  // Server resolution is consumed once by the client. Hand derivation:
  // b=1.25 -> f=4/sqrt(1.25), gain=.6*1.25=.75; w=.8 -> g=1.6.
  // For upright gravity_scale=2, bounded d=g*9.81/(2*pi*f)^2.
  // These are the same hand-derived effective numbers pinned in the Python P3 smoke.
  const effectivePayload=payload({gain:.75,max_deg:25,freq_hz:4/Math.sqrt(1.25),
    zeta:.5/Math.sqrt(1.25),gravity:1.6,gravity_scale:2,sag_max_deg:4,
    spill_max_deg:24,head_sag:1,flatten:.4,translate:.48});
  const effective=effectivePayload.groups.test;
  for(const [key,value] of Object.entries({gain:.75,max_deg:25,freq_hz:4/Math.sqrt(1.25),zeta:.5/Math.sqrt(1.25),gravity:1.6,sag_max_deg:4,spill_max_deg:24,flatten:.4,translate:.48}))near(effective[key],value,1e-12);
  const calibrated=fixture();calibrated.solver.configure(effectivePayload);
  calibrated.solver.update(1.5,{far:true});
  const calibratedD=1.6*9.81/(2*Math.PI*(4/Math.sqrt(1.25)))**2;
  near(calibrated.bone.getWorldPosition(new THREE.Vector3()).y,-.48*calibratedD/Math.hypot(1,calibratedD),1e-10);
  calibrated.solver.dispose();console.log('ok effective bounce/weight payload in client solver: applied exactly once');
  const lift=fixture({gravity_scale:.5}); settle(lift);
  near(lift.point().y,.5*9.81/(4*Math.PI)**2/Math.hypot(1,.5*9.81/(4*Math.PI)**2));
  const still=fixture({gravity_scale:2,gain:0,max_deg:0}); settle(still);
  near(still.point().y,-9.81/(4*Math.PI)**2/Math.hypot(1,9.81/(4*Math.PI)**2));
  const defaultSingle=fixture({flatten:0}); defaultSingle.anchor.rotation.x=-Math.PI/2; settle(defaultSingle);
  near(defaultSingle.point().distanceTo(new THREE.Vector3(0,1,-9.81/(4*Math.PI)**2).normalize()),0);
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
  const lengths=[swing0.point().length(),swing3.point().length()];
  const inferredTransverse=(f,L)=>f.point().x*L/Math.sqrt(L*L-f.point().x*f.point().x);
  let peak0=0,peak3=0;
  for(let i=0;i<120;i++) {
    for(const swing of [swing0,swing3]) {swing.root.position.x=.1; swing.solver.update(1/30);}
    // Points are mesh-local, so d_x is the visible offset from the moved anchor.
    near(inferredTransverse(swing0,lengths[0]),inferredTransverse(swing3,lengths[1]),1e-8);
    if(i===0) near(inferredTransverse(swing0,lengths[0]),-.065778376882,1e-9);
    peak0=Math.max(peak0,Math.abs(inferredTransverse(swing0,lengths[0]))); peak3=Math.max(peak3,Math.abs(inferredTransverse(swing3,lengths[1])));
  }
  near(peak0,peak3,1e-8);
  console.log('ok same body impulse has identical swing for bent-forward gravity 0 and 3');

  f=fixture({gravity:0,gain:0,rest_deg:30}); settle(f); near(f.point().length(),1); near(f.point().z,Math.cos(Math.PI/6)); console.log('ok gain zero retains rest rotation');
  f=fixture({gravity:100,max_deg:5,sag_max_deg:5,squash:[0.95,1.05]}); f.anchor.rotation.x=-Math.PI/2; f.solver.reset(); settle(f);
  near(f.point().length(),1); near(f.point().angleTo(new THREE.Vector3(0,1,0)),5*Math.PI/180); console.log('ok dynamic angle and squash clamps');
  f=fixture({gravity:0,gain:0,rest_deg:80,rest_max_deg:20,max_deg:0}); settle(f); near(f.point().z,Math.cos(Math.PI/9)); console.log('ok independent rest clamp');
  f=fixture({freq_hz:20,zeta:5}); f.anchor.rotation.x=-Math.PI/2; f.solver.reset(); settle(f); near(f.point().distanceTo(new THREE.Vector3(0,1,0)),9.81/(40*Math.PI)**2,1e-6); console.log('ok overdamped spring remains stable');
  const a=fixture(),b=fixture(); for(const x of [a,b]) {x.anchor.rotation.x=-Math.PI/2; x.solver.reset(); x.solver.update(0);}
  a.solver.update(1/30); for(let i=0;i<4;i++) b.solver.update(1/120); near(a.point().distanceTo(b.point()),0,1e-8); console.log('ok frame partition');
  a.solver.update(0.251); near(a.point().distanceTo(new THREE.Vector3(0,1,-9.81/(4*Math.PI)**2).normalize()),0); console.log('ok gap resets');
  a.solver.update(1/30); const before=a.point(); a.solver.update(1,{frozen:true}); near(a.point().distanceTo(before),0); console.log('ok frozen dynamics');
  a.root.position.x=0.4; a.solver.update(0.1,{frozen:true}); near(a.bone.matrix.elements[12],0);
  const frozenWorld=a.point().applyMatrix4(a.mesh.matrixWorld); near(frozenWorld.x,0.4); near(frozenWorld.y,before.y); console.log('ok freeze transports displacement with anchor');
  a.solver.update(1/30,{far:true}); near(a.point().distanceTo(new THREE.Vector3(0,1,-9.81/(4*Math.PI)**2).normalize()),0); console.log('ok far LOD reset');
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
  near(weightedCentre.distanceTo(new THREE.Vector3(0,2.5,-9.81/(4*Math.PI)**2).normalize().multiplyScalar(2.5)),0); console.log('ok centroid uses positive skin weights');
  const movingA=fixture(),movingB=fixture(); movingA.solver.update(0); movingB.solver.update(0);
  movingA.root.position.x=0.1; movingA.solver.update(1/30);
  for(let i=1;i<=4;i++){movingB.root.position.x=i*0.025; movingB.solver.update(1/120);}
  near(movingA.point().x,displacement/Math.sqrt(1+displacement**2),1e-9);
  near(movingA.point().distanceTo(movingB.point()),0,1e-8); console.log('ok moving-target frame partition and target velocity');
  f=fixture(); f.anchor.rotation.x=-Math.PI/2; settle(f);
  const held=f.point(); f.solver.configure(payload({gravity:0.5})); f.solver.update(0); near(f.point().distanceTo(held),0); console.log('ok live reconfigure retains particle state');
  for(let i=0;i<6;i++) f.solver.update(.25,{far:true}); f.solver.reset(); f.solver.update(0); near(f.point().distanceTo(new THREE.Vector3(0,1,-.5*9.81/(4*Math.PI)**2).normalize()),0); console.log('ok explicit teleport reset');
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
  near(livePoint().y,1/Math.hypot(1,9.81/(4*Math.PI)**2)-1); near(livePoint().z,-9.81/(4*Math.PI)**2/Math.hypot(1,9.81/(4*Math.PI)**2)); console.log('ok client runs solver after final root lean');
  holder.payload=payload({gravity:0,gain:0}); for(let i=0;i<600;i++) figure.update(0,{realDelta:1/120}); near(livePoint().length(),0); assert.equal(liveMesh.geometry,f.mesh.geometry); console.log('ok client live motion revision keeps mesh');
  holder.payload=payload({gravity:0,gain:0,rest_deg:30}); for(let i=0;i<180;i++) figure.update(0,{realDelta:1/120});
  near(livePoint().y,Math.cos(Math.PI/6)-1); near(livePoint().z,-0.5); console.log('ok client live rest blend');
  let disposed=0; f.mesh.geometry.addEventListener('dispose',()=>disposed++); figure.dispose(); assert.equal(disposed,0); console.log('ok client solver disposal preserves template geometry');


  const farFigure=new C.Figure({...model,tier:'low'});
  farFigure.faceTowards(new THREE.Vector3(0,0,1),true); farFigure.setLean(-90,0);
  for(let i=0;i<200;i++) farFigure.update(0,{realDelta:1/120});
  let farMesh; farFigure.root.traverse(o=>{if(o.isSkinnedMesh) farMesh=o;});
  const farPoint=farMesh.applyBoneTransform(2,new THREE.Vector3(0,0,1)).applyMatrix4(farMesh.matrixWorld);
  near(farPoint.y,Math.cos(Math.PI/6)-1); near(farPoint.z,-0.5); farFigure.dispose(); console.log('ok client low tier retains rest without dynamics');
  const chain=fixture(); chain.solver.dispose();
  const child=new THREE.Bone(); child.name='extra_child'; child.position.z=0.5; chain.bone.add(child);
  chain.mesh.geometry.setAttribute('position',new THREE.Float32BufferAttribute([-0.1,0,1, 0.1,0,1, 0.3,0,1.5],3));
  chain.mesh.geometry.setAttribute('skinIndex',new THREE.Uint16BufferAttribute([1,0,0,0, 1,0,0,0, 2,0,0,0],4));
  chain.root.updateMatrixWorld(true); chain.mesh.bind(new THREE.Skeleton([chain.anchor,chain.bone,child]));
  const childBind=child.matrix.clone();
  // Two links under one root remain a single chain: no lateral spill;
  // inward force removed and the transverse sag retains unit length.
  const singleChain=C.createSecondaryMotion(THREE,chain.root,{rev:'single-chain',groups:{
    chain:{...defaults,bones:['extra','extra_child'],spill:0},
  }});
  chain.anchor.rotation.x=-Math.PI/2;
  for(let i=0;i<600;i++) singleChain.update(1/120);
  const chainCentre=new THREE.Vector3(0,0,1).applyMatrix4(chain.mesh.skeleton.boneInverses[1]).applyMatrix4(chain.bone.matrixWorld);
  near(chainCentre.distanceTo(new THREE.Vector3(0,1,-9.81/(4*Math.PI)**2).normalize()),0);
  singleChain.dispose(); chain.anchor.rotation.x=0; chain.root.updateMatrixWorld(true);
  console.log('ok multiple links under one root keep single-chain transverse sag');
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
    rebuilt.update(0,{realDelta:0});near(renderedPoint(rebuilt.root).length(),Math.sqrt(2-2/Math.hypot(1,9.81/(4*Math.PI)**2)));
    if(tier==='low'){for(let i=0;i<20;i++)rebuilt.update(0,{realDelta:1/120});near(renderedPoint(rebuilt.root).length(),Math.sqrt(2-2/Math.hypot(1,9.81/(4*Math.PI)**2)));}
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
  const defaults={axis_gain:[1,1,1],freq_hz:2,zeta:.7,gravity:1,gain:.9,max_deg:30,sag_max_deg:30,spill_max_deg:30,head_sag:1,flatten:1,spill:0,translate:0,rest_max_deg:45,squash:[.8,1.2]};
  const props={defaults,overrides:{},disabled:false,onSave:async value=>{editorCalls.push(value);return true}};
  const allNodes=node=>Array.isArray(node)?node.flatMap(allNodes):node?.children?[node,...node.children.flatMap(allNodes)]:[];
  const nodes=()=>allNodes(renderEditor(props));
  const input=label=>nodes().find(node=>node.tag==='label'&&node.children[0]===label).children.find(node=>node?.tag==='input');
  assert.equal(nodes().find(node=>node.tag==='details').props?.open,undefined);
  for(const label of ['Bounce','Weight']) {
    const slider=input(label);assert.equal(slider.props.type,'range');assert.equal(slider.props.min,.5);assert.equal(slider.props.max,1.5);assert.equal(slider.props.step,.05);
  }
  input('Bounce').props.onChange({target:{value:'1.25'}});
  input('Weight').props.onChange({target:{value:'.8'}});
  nodes().find(node=>node.tag==='button'&&node.children[0]==='Save').props.onClick();
  await Promise.resolve();assert.deepEqual(editorCalls.pop(),{bounce:1.25,weight:.8});
  nodes().find(node=>node.tag==='button'&&node.children[0]==='Reset').props.onClick();
  await Promise.resolve();assert.equal(editorCalls.pop(),undefined);
  assert.equal(input('Bounce').props.value,'1');assert.equal(input('Weight').props.value,'1');
  assert.equal(input('Gain').props.value,'0.9','editor starts with pre-clothing values');
  input('Gain').props.onChange({target:{value:'.8'}});
  props.defaults={...defaults,gain:.216};
  assert.equal(input('Gain').props.value,'.8','poll must preserve pending draft');
  assert.equal(editorCalls.length,0,'typing does not save');
  input('Gain').props.onKeyDown({key:'Enter',preventDefault(){}});
  await Promise.resolve();
  assert.deepEqual(editorCalls.pop(),{gain:.8},'Enter sends exactly edited overrides');
  input('Longitudinal gain').props.onChange({target:{value:'2'}});
  assert.equal(input('Longitudinal gain').props['aria-invalid'],true);
  input('Longitudinal gain').props.onChange({target:{value:'.15'}});
  input('Longitudinal gain').props.onKeyDown({key:'Enter',preventDefault(){}});
  await Promise.resolve();assert.deepEqual(editorCalls.pop(),{axis_gain:[1,1,.15]});
  input('Translation fraction').props.onChange({target:{value:'.6'}});
  input('Translation fraction').props.onKeyDown({key:'Enter',preventDefault(){}});
  await Promise.resolve();assert.equal(editorCalls.pop().translate,.6);
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
  // Removing the inward axial force gives direction (1+d/2,d,1-d/2).
  // Forced length 1.4 gives D=Q*[a I+(1.4-a)uu^T], a=1/sqrt(1.4).
  // Child T=Rx(-90)*D*(offset+c_child); pure R=Rx(-90)*Q.
  // Child direction includes projected [g-R*g]/omega²; length remains its
  // direct target, independent of parent shear in the gravity rotation.
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
  const pq=new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(1,0,1).normalize(),new THREE.Vector3(1+d/2,d,1-d/2).normalize());
  const rq=new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1,0,0),-Math.PI/2);
  const axis=new THREE.Vector3(1,0,1).normalize(), transverse=1/Math.sqrt(1.4);
  const scaleVector=v=>v.clone().multiplyScalar(transverse).addScaledVector(axis,(1.4-transverse)*v.dot(axis));
  const expected=scaleVector(new THREE.Vector3(1.2,0,2)).applyQuaternion(pq).applyQuaternion(rq);
  const childHead=scaleVector(new THREE.Vector3(.2,0,.5)).applyQuaternion(pq).applyQuaternion(rq);
  const childLever=expected.clone().sub(childHead), childU=childLever.clone().normalize();
  const childForce=new THREE.Vector3(0,-9.81,0).sub(new THREE.Vector3(0,-9.81,0).applyQuaternion(rq.clone().multiply(pq)));
  if(childForce.dot(childU)<0)childForce.addScaledVector(childU,-childForce.dot(childU));
  expected.copy(childLever).addScaledVector(childForce,1/(4*Math.PI)**2).normalize().multiplyScalar(childLever.length()).add(childHead);
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
  near(multiCentre.distanceTo(new THREE.Vector3(0,2,-d).normalize().multiplyScalar(2)),0);
  console.log('ok multi-mesh centroid and non-identity bind matrix');

  const replacement=fixture();replacement.anchor.rotation.x=-Math.PI/2;replacement.solver.update(0);
  near(replacement.point().distanceTo(new THREE.Vector3(0,1,-9.81/(4*Math.PI)**2).normalize()),0);
  replacement.solver.update(1/120,{far:true});near(replacement.point().distanceTo(new THREE.Vector3(0,1,-9.81/(4*Math.PI)**2).normalize()),0);
  replacement.solver.update(0,{far:false});near(replacement.point().distanceTo(new THREE.Vector3(0,1,-9.81/(4*Math.PI)**2).normalize()),0);
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
