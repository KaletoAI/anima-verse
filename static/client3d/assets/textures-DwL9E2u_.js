import{a as e}from"./client-B0UadwRQ.js";import{$ as t,$a as n,$i as r,$n as i,$r as a,$t as o,A as s,Aa as c,Ai as l,An as u,Ar as d,At as f,B as p,Ba as m,Bi as h,Bn as g,Br as _,Bt as v,C as y,Ca as b,Ci as x,Cn as S,Co as C,Cr as w,Ct as T,D as E,Da as D,Di as O,Dn as k,Do as ee,Dr as A,Dt as te,E as j,Ea as M,Ei as N,En as ne,Eo as P,Er as re,Et as ie,F as ae,Fa as oe,Fi as F,Fn as I,Fr as L,Ft as R,G as z,Ga as se,Gi as B,Gn as ce,Gr as le,Gt as ue,H as de,Ha as fe,Hi as pe,Hn as V,Hr as H,Ht as me,I as he,Ia as ge,Ii as _e,In as ve,Ir as ye,It as U,J as be,Ja as xe,Ji as Se,Jn as W,Jr as Ce,Jt as G,K,Ka as we,Ki as Te,Kn as Ee,Kr as De,Kt as Oe,L as ke,La as Ae,Li as je,Ln as Me,Lr as Ne,Lt as Pe,M as Fe,Ma as Ie,Mi as Le,Mn as Re,Mr as ze,Mt as Be,N as Ve,Na as He,Ni as Ue,Nn as q,Nr as We,Nt as J,O as Ge,Oa as Ke,Oi as qe,On as Je,Or as Ye,Ot as Xe,P as Ze,Pa as Qe,Pi as $e,Pn as et,Pr as tt,Pt as nt,Q as rt,Qa as it,Qi as at,Qn as ot,Qr as st,Qt as ct,R as lt,Ra as ut,Ri as dt,Rn as ft,Rr as pt,Rt as mt,S as ht,Sa as gt,Si as _t,Sn as vt,So as yt,Sr as bt,St as xt,T as St,Ta as Ct,Ti as wt,Tn as Tt,To as Et,Tr as Dt,Tt as Ot,U as kt,Ua as At,Ui as jt,Un as Mt,Ur as Nt,Ut as Pt,V as Ft,Va as It,Vi as Lt,Vn as Rt,Vr as zt,Vt as Bt,W as Vt,Wa as Ht,Wi as Ut,Wn as Wt,Wr as Gt,Wt as Kt,X as qt,Xa as Jt,Xi as Yt,Xn as Xt,Xr as Zt,Xt as Qt,Y as $t,Ya as en,Yi as tn,Yn as nn,Yr as rn,Yt as an,Z as on,Za as sn,Zi as cn,Zn as ln,Zr as un,Zt as dn,_ as fn,_a as pn,_i as mn,_n as hn,_o as gn,_r as _n,_t as vn,a as yn,aa as bn,ai as xn,an as Sn,ao as Cn,ar as wn,at as Tn,b as En,ba as Dn,bi as On,bn as kn,bo as An,br as jn,bt as Mn,c as Nn,ca as Pn,ci as Fn,cn as In,co as Ln,cr as Rn,ct as zn,d as Bn,da as Vn,di as Hn,dn as Un,do as Wn,dr as Gn,dt as Kn,ea as qn,ei as Jn,en as Yn,eo as Y,er as Xn,et as Zn,f as Qn,fa as $n,fi as er,fn as tr,fo as nr,fr as rr,ft as ir,g as ar,ga as or,gi as sr,gn as cr,go as lr,gr as ur,gt as dr,h as fr,ha as pr,hi as mr,hn as hr,ho as gr,hr as _r,ht as vr,i as yr,ia as br,ii as xr,in as Sr,io as Cr,ir as wr,it as Tr,j as Er,ja as Dr,ji as Or,jn as kr,jr as Ar,jt as jr,k as Mr,ka as Nr,ki as Pr,kn as Fr,kr as Ir,kt as Lr,l as Rr,la as zr,li as Br,ln as Vr,lo as Hr,lr as Ur,lt as Wr,m as Gr,ma as Kr,mi as qr,mn as Jr,mo as Yr,mr as Xr,mt as Zr,n as Qr,na as $r,ni as ei,nn as ti,no as ni,nr as X,nt as ri,o as ii,oa as ai,oi,on as si,oo as ci,or as li,ot as ui,p as di,pa as fi,pi,pn as mi,po as hi,pr as gi,pt as _i,q as vi,qa as yi,qi as bi,qn as xi,qr as Si,qt as Ci,r as wi,ra as Ti,ri as Ei,rn as Di,ro as Oi,rr as ki,rt as Ai,s as ji,sa as Mi,si as Ni,sn as Pi,so as Fi,sr as Ii,st as Li,t as Ri,ta as zi,ti as Bi,tn as Vi,to as Hi,tr as Ui,tt as Wi,u as Gi,ua as Ki,ui as qi,un as Ji,uo as Yi,ur as Xi,ut as Zi,v as Qi,va as $i,vi as ea,vn as ta,vo as na,vr as ra,vt as ia,w as aa,wa as oa,wi as sa,wn as ca,wo as la,wr as ua,wt as da,x as fa,xa as pa,xi as ma,xn as ha,xo as ga,xr as _a,xt as va,y as ya,ya as ba,yi as xa,yn as Sa,yo as Ca,yr as wa,yt as Ta,z as Ea,za as Da,zi as Oa,zn as ka,zr as Aa,zt as ja}from"./three.core-Co-9pgkG.js";function Ma(e,t){let n=-Math.sin(t),r=-Math.cos(t),i=-r,a=n,o=0,s=0;(e.has(`w`)||e.has(`arrowup`))&&(o+=n,s+=r),(e.has(`s`)||e.has(`arrowdown`))&&(o-=n,s-=r),(e.has(`d`)||e.has(`arrowright`))&&(o+=i,s+=a),(e.has(`a`)||e.has(`arrowleft`))&&(o-=i,s-=a);let c=Math.hypot(o,s);return c<1e-6?null:{x:o/c,z:s/c}}function Na(e,t){return t!==null&&e.has(`shift`)}function Pa(e,t){return!t&&!e}function Fa(e,t){return t===null?e===null?`wilderness`:e?`open`:`built`:t?`open`:`built`}var Ia=.25,La=.05;function Ra(e,t){return!Number.isFinite(e)||t===`built`||t===`open`&&e<=0?1:Math.max(e,Ia)}var za=[`standing`,`walking`,`running`,`swimming`,`treading_water`,`crawling`,`crawling_rest`],Ba={standing:`idle`,walking:`walk`,running:`run`,swimming:`breast-stroke`,treading_water:`treading-water`,crawling:`crawl`,crawling_rest:`crawl-rest`};function Va(e){let t=e&&typeof e==`object`?e:{},n=(e,t)=>typeof e==`string`&&e.trim()?e.trim().toLowerCase():t;return Object.fromEntries(za.map(e=>{let r=t[e],i=r&&typeof r==`object`?r:{};return[e,{kind:n(i.kind,Ba[e]),publicKind:n(i.public_kind,Ba[e])}]}))}var Ha=Va(null);function Ua(e){return Ha=Va(e),Object.fromEntries(za.map(e=>[e,{...Ha[e]}]))}function Wa(e,t=Ha){return t[e].kind}function Ga(e,t=Ha){return t[e].publicKind}function Ka(e,t=Ha){let n=(e??``).trim().toLowerCase();return za.find(e=>Wa(e,t)===n)||za.find(e=>Ga(e,t)===n)||``}function qa(e,t){return t!==`built`&&(e===`walk_run`||e===`walk`||e===`swim`||e===`crawl`)?e:`walk_run`}function Ja(e){return e===`walk_run`}function Ya(e,t,n=Ha){return Wa(e===`swim`?`swimming`:e===`crawl`?`crawling`:Ja(e)&&t?`running`:`walking`,n)}function Xa(e,t,n,r=Ha){if(!t)return e;let i=e===Wa(`walking`,r)?t.walk:e===Wa(`running`,r)?t.run:void 0;return i&&n(i)?i:e}var Za=`*`,Qa=[];function $a(e){return Qa=eo(e),Qa}function eo(e){return(Array.isArray(e)?e:[]).flatMap(e=>{if(!e||typeof e!=`object`)return[];let t=e,n=String(t.from??``).trim().toLowerCase(),r=String(t.to??``).trim().toLowerCase(),i=String(t.kind??``).trim().toLowerCase(),a=Number(t.accel);return n&&r&&i?[{from:n,to:r,kind:i,accel:Number.isFinite(a)&&a>0?Math.min(a,8):0}]:[]})}function to(e,t,n=Qa){let r=String(e??``).trim().toLowerCase(),i=String(t??``).trim().toLowerCase();if(!r||!i||r===i)return null;let a=null,o=null;for(let e of n){if(e.from===r&&e.to===i)return e;e.from===r&&e.to===Za&&!a?a=e:e.from===Za&&e.to===i&&!o&&(o=e)}return a||o}var no=.02;function ro(e,t){return!!e&&e.toLowerCase()===t.toLowerCase()}function io(e,t){return!Number.isFinite(e)||e<=0?0:Math.min(1,Math.max(no,e*(Number.isFinite(t)&&t>0?t:0)))}function ao(e,t=Ha){return e===`swim`?Wa(`treading_water`,t):e===`crawl`?Wa(`crawling_rest`,t):``}function oo(e,t,n=Ha){return t||e||Wa(`standing`,n)}function so(e,t){return!Number.isFinite(e)||e<=0||t===`built`?0:e}function co(e,t,n){return e?n.move:t?n.idle:0}function lo(e,t){return e===null||!Number.isFinite(e)||t===`built`?null:e}function uo(e,t,n,r){return r?po({movement:`swim`,sink:{move:.35,idle:1.3},water:r.y},r.groundY??t,r.swim_from_m):po(e,t,n)}function fo(e,t){return t?Math.max(e,t.y):e}function po(e,t,n){let r=e.water;return r===null||!Number.isFinite(r)||!Number.isFinite(t)||r-t>=mo(n)?e:{movement:`walk_run`,sink:{move:0,idle:0},water:null}}function mo(e){return typeof e==`number`&&Number.isFinite(e)&&e>=0?e:1}function ho(e,t,n){let r=Number.isFinite(n)&&n>0?n:0;return t===null||!Number.isFinite(t)?e:Math.max(e+r,t)}var go=.05;function _o(e,t){return t===null||!Number.isFinite(t)||!Number.isFinite(e)?!1:t-e>=go}function vo(e,t){return _o(e,t)?t:null}function yo(e,t){return t>0?e:NaN}function bo(e,t,n,r){let i=e;return i>0?t<1&&i>n||Math.atan2(i,t)*180/Math.PI>r:!1}function xo(e,t,n){let r=Number.isFinite(e)?e:Number.isFinite(t)?t:NaN;return Number.isFinite(r)?Number.isFinite(n)?Math.max(r,n):r:n}function So(e,t){return e.filter(e=>(t(e.roomId)??0)===0)}function Co(e,t,n){if(!n(t.x,t.z))return t;let r=t.x-e.x,i=t.z-e.z,a={x:t.x,z:e.z},o={x:e.x,z:t.z},s=Math.abs(r)>=Math.abs(i)?a:o,c=s===a?o:a;return(s===a?r:i)!==0&&!n(s.x,s.z)?s:(c===a?r:i)!==0&&!n(c.x,c.z)?c:{x:e.x,z:e.z}}var wo=[1,0,0,0],To=(e,t)=>[e[0]-t[0],e[1]-t[1],e[2]-t[2]],Eo=(e,t)=>[e[0]+t[0],e[1]+t[1],e[2]+t[2]],Do=(e,t)=>[e[0]*t,e[1]*t,e[2]*t],Oo=(e,t)=>e[0]*t[0]+e[1]*t[1]+e[2]*t[2],ko=(e,t)=>[e[1]*t[2]-e[2]*t[1],e[2]*t[0]-e[0]*t[2],e[0]*t[1]-e[1]*t[0]],Ao=e=>Math.sqrt(Oo(e,e)),jo=e=>{let t=Ao(e);return t>1e-12?Do(e,1/t):[0,0,0]};function Mo(e,t){let[n,r,i,a]=e,o=[r,i,a],s=Do(ko(o,t),2);return Eo(Eo(t,Do(s,n)),ko(o,s))}function No(e,t){let n=jo(e),r=jo(t),i=Oo(n,r);if(i<-.999999999999){let e=ko(n,[1,0,0]);return Ao(e)<1e-6&&(e=ko(n,[0,1,0])),e=jo(e),[0,e[0],e[1],e[2]]}let a=ko(n,r),o=[1+i,a[0],a[1],a[2]],s=Math.hypot(o[0],o[1],o[2],o[3]);return[o[0]/s,o[1]/s,o[2]/s,o[3]/s]}function Po(e,t,n,r,i){let a=Ao(To(t,e)),o=Ao(To(n,t)),s=To(r,e),c=Ao(s);if(a<1e-9||o<1e-9||c<1e-9)return{upper:wo,lower:wo};let l=Do(s,1/c);c=Math.min(Math.max(c,Math.abs(a-o)+1e-9),a+o);let u=To(i,e),d=To(u,Do(l,Oo(u,l)));Ao(d)<1e-9&&(d=ko(l,[1,0,0]),Ao(d)<1e-6&&(d=ko(l,[0,0,1]))),d=jo(d);let f=Math.max(-1,Math.min(1,(a*a+c*c-o*o)/(2*a*c))),p=Math.sqrt(Math.max(0,1-f*f)),m=Eo(e,Eo(Do(l,a*f),Do(d,a*p))),h=Eo(e,Do(l,c)),g=No(To(t,e),To(m,e));return{upper:g,lower:No(Mo(g,To(n,t)),To(h,m))}}var Fo=1.7;function Io(e,t=0){let n=typeof e?.[0]==`number`&&Number.isFinite(e[0])?e[0]/100:0,r=typeof e?.[1]==`number`&&Number.isFinite(e[1])?e[1]/100:0;return{x:n*Math.cos(t)+r*Math.sin(t),z:-n*Math.sin(t)+r*Math.cos(t)}}function Lo(e){return e===`seat`||e===`lie`?e:`ground`}function Ro(e,t,n=Fo){let r=e?.[Lo(t)];return typeof r==`number`&&Number.isFinite(r)?r/100*n/Fo:0}function zo(e){let t=[];for(let n of e?.tracks||[]){if(!n.name.endsWith(`.position`)||!/hips\./i.test(n.name.replace(/^mixamorig:?/i,``)))continue;let e=n.values;for(let n=1;n<e.length;n+=3)t.push(Math.abs(e[n]))}return t.length?(t.sort((e,t)=>e-t),t[Math.floor(t.length/2)]):null}function Bo(e,t){t.updateMatrixWorld(!0);let n;return t.traverse(e=>{!n&&e.isBone&&/hips$/.test(Z(e.name))&&(n=e)}),n?n.getWorldPosition(new e.Vector3).y:void 0}function Vo(e,t){let n=e=>typeof e==`number`&&Number.isFinite(e)&&e>0;return n(e)?{ref:e,source:`rig`}:n(t)?{ref:t,source:`idle`}:{ref:null,source:`none`}}function Ho(e){let t=e.userData?.garment;return!!t&&typeof t==`object`||e.name.startsWith(`garment_`)}function Uo(e){for(let t=e;t;t=t.parent)if(Ho(t))return!0;return!1}function Wo(e,t,n){let r=is(e,n,t);if(r)return t.updateWorldMatrix(!0,!1),r.box.applyMatrix4(t.matrixWorld);let i=!1;t.traverse(e=>{Ho(e)&&(i=!0)});let a=new e.Box3;if(!i)return a.setFromObject(t);let o=new e.Box3,s=e=>{if(Ho(e))return;e.updateWorldMatrix(!1,!1);let t=e;t.geometry!==void 0&&(t.boundingBox===void 0?(t.geometry.boundingBox===null&&t.geometry.computeBoundingBox(),o.copy(t.geometry.boundingBox)):(t.boundingBox===null&&t.computeBoundingBox?.(),t.boundingBox?o.copy(t.boundingBox):o.makeEmpty()),o.applyMatrix4(e.matrixWorld),a.union(o));for(let t of e.children)s(t)};return s(t),a}var Go=[`chest_hair`,`shoulder_hair`],Ko=[`outer_trunk`];function qo(e,t){let n=Array(16);for(let r=0;r<4;r++)for(let i=0;i<4;i++){let a=0;for(let n=0;n<4;n++)a+=e[n*4+i]*t[r*4+n];n[r*4+i]=a}return n}function Jo(e,t){let[n,r,i]=t,a=e[3]*n+e[7]*r+e[11]*i+e[15]||1;return[(e[0]*n+e[4]*r+e[8]*i+e[12])/a,(e[1]*n+e[5]*r+e[9]*i+e[13])/a,(e[2]*n+e[6]*r+e[10]*i+e[14])/a]}function Yo(e){let t=0;for(let n=0;n<3;n++)t+=Math.hypot(e[n*4],e[n*4+1],e[n*4+2]);return t/3}function Xo(e,t,n,r,i){let a=qo(qo(e,t),n);return{position:[a[12],a[13],a[14]],bindToWorld:qo(qo(a,r),i)}}function Zo(e,t,n){return{a:e.a_pos?Jo(t.bindToWorld,e.a_pos):[...t.position],b:e.b_pos?Jo(n.bindToWorld,e.b_pos):[...n.position],r:e.r*Yo(t.bindToWorld)}}function Qo(e){let t=new Map;return e.traverse(e=>{let n=e;!n.isSkinnedMesh||!n.skeleton||Uo(n)||n.skeleton.bones.forEach((e,r)=>{let i=Z(e.name);t.has(i)||t.set(i,{mesh:n,index:r})})}),t}function $o(e){return Xo(e.mesh.matrixWorld.elements,e.mesh.bindMatrixInverse.elements,e.mesh.skeleton.bones[e.index].matrixWorld.elements,e.mesh.skeleton.boneInverses[e.index].elements,e.mesh.bindMatrix.elements)}function es(e,t,n){if(!n||n.version!==8||!n.capsules?.length)return null;let r=Qo(t),i=t=>Xo(t.mesh.bindMatrix.elements,new e.Matrix4().copy(t.mesh.bindMatrix).invert().elements,new e.Matrix4().copy(t.mesh.skeleton.boneInverses[t.index]).invert().elements,t.mesh.skeleton.boneInverses[t.index].elements,t.mesh.bindMatrix.elements),a=[],o=[];for(let e of n.capsules){let t=r.get(Z(e.a)),n=r.get(Z(e.b));if(!t||!n||!(e.r>0)){o.push(e.id);continue}a.push({capsule:e,ja:t,jb:n,now:{a:[0,0,0],b:[0,0,0],r:e.r},bind:Zo(e,i(t),i(n))})}let s=()=>{for(let e of a)e.now=Zo(e.capsule,$o(e.ja),$o(e.jb))};return s(),{capsules:a,missing:o,update:s}}var ts=[`left`,`right`];function ns(e){return!!e&&e.version===1&&!!e.source&&typeof e.source.fsig==`string`}var rs=e=>Array.isArray(e)&&e.length===3&&e.every(e=>typeof e==`number`&&Number.isFinite(e));function is(e,t,n){if(!ns(t)||!t.rest||typeof t.rest!=`object`)return null;let{box:r,soles:i}=t.rest;if(!r||!rs(r.min)||!rs(r.max)||n&&!ds(n,t))return null;let a=new Map;for(let t of ts){let n=i?.[t];!n||!rs(n.heel)||!rs(n.toe)||a.set(t,{heel:new e.Vector3(...n.heel),toe:new e.Vector3(...n.toe)})}return{box:new e.Box3(new e.Vector3(...r.min),new e.Vector3(...r.max)),soles:a}}function as(e,t){let n=new Map;for(let[r,i]of Object.entries(t.bones??{})){let t=i?.axis,a=i?.deg;if(!Array.isArray(t)||t.length!==3||typeof a!=`number`||!Number.isFinite(a))continue;let o=new e.Vector3(t[0],t[1],t[2]),s=o.length();!(s>1e-12)||!Number.isFinite(s)||n.set(Z(r),new e.Quaternion().setFromAxisAngle(o.divideScalar(s),a*Math.PI/180))}return n}function os(e,t,n){let r=new e.Quaternion,i=t?.world.get(n),a=t?.parent.get(n);return i&&a&&r.copy(a).invert().multiply(i),r}function ss(e,t,n,r,i,a,o){if(!a||!o)return n;let s=a.world.get(t),c=o.parent.get(t),l=o.world.get(t);if(!s||!c||!l)return n;let u=!1;for(let e=a.parentBone.get(t);e;e=a.parentBone.get(e))if(i.has(e)){u=!0;break}let d=os(e,a,t),f=r?new e.Quaternion().copy(c).invert().multiply(l):d;return(u?new e.Quaternion().copy(d).invert().multiply(f):new e.Quaternion().copy(s).invert().multiply(c).multiply(f)).invert().multiply(n)}function cs(e,t,n,r,i){if(!ns(n)||t.userData?.footPosed)return t;let a=as(e,n),o=new Set(a.keys()),s=[],c=new Set,l=new e.Quaternion;for(let n of t.tracks){let t=n.name.lastIndexOf(`.`),u=t>0&&n.name.slice(t+1)===`quaternion`?Z(n.name.slice(0,t)):``,d=u?a.get(u):void 0;if(!d){s.push(n);continue}c.add(u);let f=ss(e,u,d,!0,o,r,i),p=new Float32Array(n.values.length);for(let e=0;e+3<n.values.length;e+=4)l.set(n.values[e],n.values[e+1],n.values[e+2],n.values[e+3]).multiply(f),p[e]=l.x,p[e+1]=l.y,p[e+2]=l.z,p[e+3]=l.w;s.push(new e.QuaternionKeyframeTrack(n.name,n.times,p))}for(let[t]of Object.entries(n.bones??{})){let n=Z(t),l=a.get(n);if(!l||c.has(n))continue;c.add(n);let u=os(e,r,n).multiply(ss(e,n,l,!1,o,r,i)),d=e.PropertyBinding.sanitizeNodeName(t);s.push(new e.QuaternionKeyframeTrack(`${d}.quaternion`,[0],[u.x,u.y,u.z,u.w]))}let u=new e.AnimationClip(t.name,t.duration,s,t.blendMode);return u.userData={...t.userData??{},footPosed:n.source.fsig},u}function ls(e,t,n){if(!ns(n)||t.userData.footPosed)return;let r=as(e,n);t.traverse(e=>{if(!e.isBone)return;let t=r.get(Z(e.name));t&&e.quaternion.multiply(t)}),t.userData.footPosed=n.source.fsig}function us(e,t,n=Fo){if(!ns(e)||Lo(t)!==`ground`)return 0;let r=e.root_lift_m;return typeof r!=`number`||!Number.isFinite(r)?0:r*n/Fo}function ds(e,t){if(!ns(t))return!1;let n=!1;return e.traverse(e=>{if(n)return;let r=e.userData?.garment;r&&r.kind===`footwear`&&r.fsig===t.source.fsig&&r.item_id===t.source.item_id&&(n=!0)}),n}function fs(e,t,n,r){let i=r??{left:[],right:[]};if(!ns(n))return i.left.length=0,i.right.length=0,i;let a=new Map;t.traverse(e=>{let t=e;!t.isSkinnedMesh||!t.skeleton||Uo(t)||t.skeleton.bones.forEach((e,n)=>{let r=Z(e.name);a.has(r)||a.set(r,{mesh:t,index:n})})});for(let t of ts){let r=i[t]??(i[t]=[]),o=0;for(let i of n.contacts?.[t]??[]){let t=a.get(Z(i.bone));if(!t||!Array.isArray(i.pos)||i.pos.length!==3)continue;let{mesh:n,index:s}=t,c=Jo(Xo(n.matrixWorld.elements,n.bindMatrixInverse.elements,n.skeleton.bones[s].matrixWorld.elements,n.skeleton.boneInverses[s].elements,n.bindMatrix.elements).bindToWorld,i.pos);(r[o]??(r[o]=new e.Vector3)).set(c[0],c[1],c[2]),o+=1}r.length=o}return i}var ps=.015;function ms(e){if(e<=-.015)return 0;if(e>=.015)return e;let t=e+ps;return t*t/(4*ps)}function hs(e,t,n,r){let i={left:0,right:0};if(!ns(n))return i;t.updateMatrixWorld(!0);let a=fs(e,t,n),o=new Map;t.traverse(e=>{if(!e.isBone)return;let t=Z(e.name);o.has(t)||o.set(t,e)});let s=e=>[e.x,e.y,e.z],c=t=>new e.Quaternion(t[1],t[2],t[3],t[0]);for(let t of ts){let n=a[t];if(!n.length)continue;let l=1/0;for(let e of n)e.y<l&&(l=e.y);let u=ms(r-l);if(u<=0)continue;let d=o.get(`${t}upleg`),f=o.get(`${t}leg`),p=o.get(`${t}foot`);if(!d||!f||!p||f.parent!==d||p.parent!==f)continue;let m=d.getWorldPosition(new e.Vector3),h=f.getWorldPosition(new e.Vector3),g=p.getWorldPosition(new e.Vector3),_=Po(s(m),s(h),s(g),[g.x,g.y+u,g.z],s(h)),v=c(_.upper),y=c(_.lower),b=d.getWorldQuaternion(new e.Quaternion),x=d.parent?d.parent.getWorldQuaternion(new e.Quaternion):new e.Quaternion,S=f.getWorldQuaternion(new e.Quaternion),C=p.getWorldQuaternion(new e.Quaternion),w=v.clone().multiply(b),T=y.clone().multiply(v).multiply(S);d.quaternion.copy(x.clone().invert().multiply(w)),f.quaternion.copy(w.clone().invert().multiply(T)),p.quaternion.copy(T.clone().invert().multiply(C)),d.updateMatrixWorld(!0),i[t]=u}return i}function Z(e){return e.replace(/^mixamorig:?/i,``).replace(/:/g,``).toLowerCase()}function gs(e,t){let n=new Map,r=new Map,i=new Map,a=new Map,o=(t,s,c,l)=>{let u=new e.Quaternion().copy(s).multiply(t.quaternion),d=new e.Matrix4().copy(c).multiply(new e.Matrix4().compose(t.position,t.quaternion,t.scale)),f=!!t.isBone,p=f?Z(t.name):``;f&&!n.has(p)&&(n.set(p,u),r.set(p,s),i.set(p,l),a.set(p,new e.Vector3().setFromMatrixPosition(d)));for(let e of t.children)o(e,u,d,f?p:l)};return o(t,new e.Quaternion,new e.Matrix4,null),{world:n,parent:r,parentBone:i,position:a}}function _s(e,t,n,r){let i=new Map,a=new Map,o=new Map,s=new Map(n.parentBone),c=n=>{let r=t.world.get(n),i=t.parent.get(n);return r&&i?new e.Quaternion().copy(i).invert().multiply(r):void 0},l=t=>new e.Quaternion().copy(n.parent.get(t)).invert().multiply(n.world.get(t)),u=t=>{if(i.has(t))return;let s=n.parentBone.get(t)??null,d,f=null;s===null?d=n.parent.get(t):(u(s),d=i.get(s),f=o.get(s));let p=r.get(t),m=c(t),h;h=p&&m?new e.Quaternion().copy(p.left).multiply(m).multiply(p.right):m||l(t);let g=new e.Quaternion().copy(d).multiply(h);if(i.set(t,g),a.set(t,d),f===null)o.set(t,n.position.get(t).clone());else{let r=n.position.get(t).clone().sub(n.position.get(s)).applyQuaternion(new e.Quaternion().copy(n.parent.get(t)).invert());o.set(t,r.applyQuaternion(d).add(f))}};for(let e of n.world.keys())u(e);return{world:i,parent:a,parentBone:s,position:o}}function vs(e){return 2*Math.acos(Math.min(1,Math.abs(e.w)))*(180/Math.PI)}function ys(e,t,n,r,i){let a=new Map,o=(e,t,n)=>{let r=e.position.get(`${n}upleg`),i=e.position.get(`${n}foot`);if(!r||!i)return null;let a=i.clone().sub(r);return t&&a.applyQuaternion(t.clone().invert()),Math.atan2(a.x,-a.y)},s=[`left`,`right`].map(a=>{let s=n.position.get(`${a}upleg`),c=o(n,i,a),l=o(t,r,a);if(!s||c===null||l===null)return null;let u=s.clone();i&&u.applyQuaternion(i.clone().invert());let d=[...n.parentBone].find(([,e])=>e===null)?.[0],f=d?n.position.get(d).clone():new e.Vector3;i&&f.applyQuaternion(i.clone().invert());let p=Math.sign(u.x-f.x)||1;return{side:a,delta:l-c,outward:p*(c-l)}});if(s.some(e=>e===null))return a;let c=(s[0].outward+s[1].outward)/2;if(Math.abs(c)*180/Math.PI<=3)return a;for(let t of s){let r=new e.Quaternion().setFromAxisAngle(new e.Vector3(0,0,1),t.delta),i=`${t.side}upleg`;for(let e of n.world.keys()){let t=e;for(;t&&t!==i;)t=n.parentBone.get(t);t===i&&a.set(e,r)}}return a}function bs(e,t,n,r,i){let a=new Map,o=[`spine`,`spine1`,`spine2`,`neck`,`head`];if(o.some(e=>!t.position.has(e)||!n.position.has(e)))return a;let s=(e,t,n)=>{let r=e.position.get(o[n+1]).clone().sub(e.position.get(o[n]));return t&&r.applyQuaternion(t.clone().invert()),Math.atan2(r.z,r.y)},c=o.slice(0,-1).map((e,a)=>s(t,r,a)-s(n,i,a)),l=(c[0]+c[1]+c[2])/3;if(Math.abs(l)*180/Math.PI<=6)return a;let u=new Map(o.slice(0,-1).map((t,n)=>[t,new e.Quaternion().setFromAxisAngle(new e.Vector3(1,0,0),c[n])]));for(let e of n.world.keys()){let t=e;for(;t&&!u.has(t);)t=n.parentBone.get(t);t&&a.set(e,u.get(t))}return a}function xs(e,t,n){let r;for(let[e,t]of n.parentBone)if(t===null){r=n.world.get(e);break}let i=r?.clone().invert(),a=[`left`,`right`].map(t=>{let r=n.position.get(`${t}foot`)?.clone(),a=n.position.get(`${t}toebase`)?.clone();return!r||!a?null:(i&&(r.applyQuaternion(i),a.applyQuaternion(i)),{side:t,ankle:r,ball:a,heel:new e.Vector3(0,1/0,0),toe:new e.Vector3(0,1/0,0)})});if(a.some(e=>e===null))return new Map;t.updateMatrixWorld(!0);let o=new e.Vector3;t.traverse(e=>{if(!e.isSkinnedMesh||Uo(e))return;let t=e,n=t.geometry.getAttribute(`position`),r=t.geometry.getAttribute(`skinIndex`),s=t.geometry.getAttribute(`skinWeight`);if(!n||!r||!s)return;let c=t.skeleton.bones.map(e=>{let t=Z(e.name);return a.find(e=>t===`${e.side}foot`||t.startsWith(`${e.side}toe`))});for(let e=0;e<n.count;e++){let n=0;for(let t=1;t<4;t++)s.getComponent(e,t)>s.getComponent(e,n)&&(n=t);let a=c[r.getComponent(e,n)];!a||s.getComponent(e,n)<=0||(t.getVertexPosition(e,o).applyMatrix4(t.matrixWorld),i&&o.applyQuaternion(i),o.z<a.ankle.z&&o.y<a.heel.y&&a.heel.copy(o),o.z>a.ball.z&&o.y<a.toe.y&&a.toe.copy(o))}});let s=new Map;for(let e of a)Number.isFinite(e.heel.y)&&Number.isFinite(e.toe.y)&&s.set(e.side,{heel:e.heel,toe:e.toe});return s}function Ss(e,t,n,r){let i=new Map,a=n?.clone().invert(),o=[`left`,`right`].map(n=>{let r=t.position.get(`${n}foot`)?.clone(),i=t.position.get(`${n}toebase`)?.clone();return!r||!i?null:(a&&(r.applyQuaternion(a),i.applyQuaternion(a)),{side:n,ankle:r,ball:i,heel:new e.Vector3(0,1/0,0),toe:new e.Vector3(0,1/0,0)})});if(o.some(e=>e===null))return i;for(let e of o){let n=t.soles?.get(e.side);if(!n)return i;e.heel.copy(n.heel),e.toe.copy(n.toe)}if(o.some(e=>!Number.isFinite(e.heel.y)||!Number.isFinite(e.toe.y)))return i;let s=(e,t)=>Math.atan2(e.y-t.y,Math.abs(t.z-e.z)),c=o.map(e=>{let t=r.get(`${e.side}foot`),n=e.heel.clone().sub(e.ankle),i=e.toe.clone().sub(e.ankle);return t&&(n.applyQuaternion(t),i.applyQuaternion(t)),s(n,i)});if((c[0]+c[1])/2*180/Math.PI<=6)return i;for(let[n,a]of o.entries()){let o=`${a.side}foot`,s=r.get(o),l=new e.Quaternion().setFromAxisAngle(new e.Vector3(1,0,0),-c[n]);s&&l.multiply(s);for(let e of t.world.keys()){let n=e;for(;n&&n!==o;)n=t.parentBone.get(n);n===o&&i.set(e,l)}}return i}function Cs(e,t,n,r=.05,i){let a=new Map;if(!t.world.size)return a;let o=`world`in n?n:gs(e,n);`world`in n||(o.soles=is(e,i,n)?.soles??xs(e,n,o));let s=e=>{for(let[t,n]of e.parentBone)if(n===null)return e.world.get(t)},c=s(t),l=s(o),u=(t,n)=>{let r=new e.Quaternion().copy(n);return t?r.premultiply(new e.Quaternion().copy(t).invert()):r},d=ys(e,t,o,c,l);for(let[n,r]of bs(e,t,o,c,l))d.has(n)||d.set(n,r);for(let[t,n]of Ss(e,o,l,d))d.set(t,n);let f=new Map;for(let[e,n]of o.world){let r=t.world.get(e);if(!r)continue;let i=u(c,r).invert(),a=d.get(e);a&&i.multiply(a),f.set(e,i.multiply(u(l,n)))}for(let[n,i]of f){let s=o.parentBone.get(n)??null,c;if(s===null){let r=t.parent.get(n),i=o.parent.get(n);if(!r||!i)continue;c=new e.Quaternion().copy(r).invert().multiply(i).invert()}else{let e=f.get(s);if(!e)continue;c=e.clone().invert()}(vs(i)>r||vs(c)>r)&&a.set(n,{left:c,right:i})}return a}function ws(e,t,n){if(!n)return null;let r=new Float32Array(t.length),i=new e.Quaternion;for(let e=0;e+3<t.length;e+=4)i.set(t[e],t[e+1],t[e+2],t[e+3]).premultiply(n.left).multiply(n.right),r[e]=i.x,r[e+1]=i.y,r[e+2]=i.z,r[e+3]=i.w;return r}var Ts=315,Es=45,Ds=.35,Os=1,ks=1,As=Math.PI/180;function js(e,t){return typeof e==`number`&&Number.isFinite(e)?e:t}function Ms(e,t,n){let r=e[t]?.[n];return typeof r==`number`&&Number.isFinite(r)?r:0}function Ns(e,t){let n=e?.heights;if(!n||n.length<2)return null;let r=n.length,i=n[0]?.length||0;if(i<2)return null;let a=e?.step_m??0;if(!(a>0))return null;let o=js(t?.azimuthDeg,Ts)*As,s=Math.min(90,Math.max(ks,js(t?.altitudeDeg,Es)))*As,c=Math.min(1,Math.max(0,js(t?.maxAlpha,Ds))),l=Math.max(0,js(t?.zFactor,Os)),u=Math.cos(s),d=u*Math.sin(o),f=Math.sin(s),p=-u*Math.cos(o),m=f,h=new Uint8ClampedArray(i*r*4);for(let e=0;e<r;e+=1){let t=e>0?e-1:e,o=e<r-1?e+1:e,s=(o-t)*a;for(let r=0;r<i;r+=1){let u=r>0?r-1:r,g=r<i-1?r+1:r,_=(g-u)*a,v=l*(Ms(n,e,g)-Ms(n,e,u))/_,y=l*(Ms(n,o,r)-Ms(n,t,r))/s,b=Math.sqrt(v*v+y*y),x=Math.sqrt(b*b+1),S=(-v*d+f-y*p)/x,C=Math.min(1,.5*(S>0?S:0)/m),w=Math.round(255*C),T=Math.round(255*c*(b/x)),E=(e*i+r)*4;h[E]=w,h[E+1]=w,h[E+2]=w,h[E+3]=T}}return{cols:i,rows:r,data:h}}function Ps(e,t,n,r=0){if(t!==`aligned`)return e*Math.PI*2;let i=Number.isFinite(Number(n))?Number(n)*Math.PI/180:0,a=Number.isFinite(r)?r:0,o=Math.PI*2;return((a+i)%o+o)%o}var Fs=2e3;function Is(e,t,n){return`terrain:scatter:${e}:${t}${Ls(n)}`}function Ls(e){return Number.isFinite(e)?`:e${e}`:``}function Rs(e,t){let n=Number(t);if(!Number.isFinite(n)||n<=0)return;let r=Number(e);if(Number.isFinite(r))return Math.floor(r/(n*60))}function zs(e){let t=2166136261;for(let n=0;n<e.length;n+=1)t^=e.charCodeAt(n),t=Math.imul(t,16777619);return t>>>0}function Bs(e,t,n){let r=Math.floor(Number(n));if(!Number.isFinite(r)||r<=1)return 0;let i=Math.floor(Number(t));return Number.isFinite(i)?((zs(e)+i)%r+r)%r:0}function Vs(e,t){if(typeof e!=`number`||!Number.isFinite(e))return-1;let n=Math.floor(Number(t));return!Number.isFinite(n)||n<1?-1:Math.min(Math.max(Math.floor(e),0),n-1)}function Hs(e){let t=zs(e)|0;return()=>(t=Math.imul(t^t>>>15,2246822519),t=Math.imul(t^t>>>13,3266489917),((t^=t>>>16)>>>0)/4294967296)}function Us(e,t,n){let r=!1,i=n?.length??0;for(let a=0,o=i-1;a<i;o=a,a+=1){let[i,s]=n[a],[c,l]=n[o];s>t!=l>t&&e<(c-i)*(t-s)/(l-s)+i&&(r=!r)}return r}function Ws(e,t,n,r,i){let a=Math.cos(n),o=Math.sin(n),s=r-e,c=i-t;return{x:s*a-c*o,z:s*o+c*a}}function Gs(e,t,n){let r=e?.points,i=r?.length??0;if(i<3||!Number.isFinite(t)||!Number.isFinite(n))return!1;let a=!1;for(let e=0,o=i-1;e<i;o=e,e+=1){let i=r[e],s=r[o];if(!i||!s||i.length<2||s.length<2)return!1;let c=i[0],l=i[1],u=s[0],d=s[1];if(!Number.isFinite(c)||!Number.isFinite(l)||!Number.isFinite(u)||!Number.isFinite(d))return!1;l>n!=d>n&&t<(u-c)*(n-l)/(d-l)+c&&(a=!a)}return a}function Ks(e,t,n){let r=e?.points,i=r?.length??0;if(i<3||!Number.isFinite(t)||!Number.isFinite(n))return 1/0;let a=!1,o=1/0;for(let e=0,s=i-1;e<i;s=e,e+=1){let i=r[e],c=r[s];if(!i||!c||i.length<2||c.length<2)return 1/0;let l=i[0],u=i[1],d=c[0],f=c[1];if(!Number.isFinite(l)||!Number.isFinite(u)||!Number.isFinite(d)||!Number.isFinite(f))return 1/0;u>n!=f>n&&t<(d-l)*(n-u)/(f-u)+l&&(a=!a);let p=l-d,m=u-f,h=p*p+m*m,g=h<1e-18?0:((t-d)*p+(n-f)*m)/h;g=g<0?0:g>1?1:g;let _=t-(d+g*p),v=n-(f+g*m),y=Math.sqrt(_*_+v*v);y<o&&(o=y)}return a?0:o}function qs(e,t,n,r){let i=Number(r);return i>0?Ks(e,t,n)<i:Gs(e,t,n)}var Js=.5;function Ys(e,t){let n=Number(t);if(Number.isFinite(n)&&n>0)return n/2;let r=Number(e);return!Number.isFinite(r)||r<=0?0:r*Js}function Xs(e){let t=Number(e?.x),n=Number(e?.z),r=Number(e?.half_w),i=Number(e?.half_d),a=Number(e?.yaw_deg);if(!Number.isFinite(t)||!Number.isFinite(n)||!(r>0)||!(i>0))return null;let o=(Number.isFinite(a)?a:0)*Math.PI/180,s=Math.cos(o),c=Math.sin(o),l=(e,r)=>[t+e*s+r*c,n-e*c+r*s];return{points:[l(-r,-i),l(r,-i),l(r,i),l(-r,i)]}}function Zs(e){let t=[];for(let n of e??[]){let e=Xs(n);e&&t.push(e)}return t}function Qs(e,t){let n=Number(e??t);return Number.isFinite(n)&&n>0?n:0}function $s(e,t,n){let r=Number(t),i=Number(e);if(!Number.isFinite(r)||r<=0||!Number.isFinite(i)||i<=0)return 0;let a=n??2e3,o=Math.min(Math.round(i/100*r),a);return o>=1?o:0}function ec(e){let t=e.ring??[],n=Number(e.densityPer100m2),r=Number(e.areaM2);if(t.length<3||!Number.isFinite(n)||n<=0||!Number.isFinite(r)||r<=0)return[];let i=$s(r,n,e.maxPoints);if(i<1)return[];let a=1/0,o=1/0,s=-1/0,c=-1/0;for(let[e,n]of t)e<a&&(a=e),e>s&&(s=e),n<o&&(o=n),n>c&&(c=n);if(!Number.isFinite(a)||!Number.isFinite(o))return[];let l=e.rng??Hs(e.seed),u=e.footprints??[],d=e.clearM,f=e.occluders??[],p=Number(e.minSpacingM),m=Number.isFinite(p)&&p>0,h=p*p,g=m?new Map:null,_=Math.floor(Number(e.variantCount)),v=Number.isFinite(_)&&_>1,y=v?Vs(e.variant,_):-1,b=e.yawMode===`aligned`?e.axisAt:void 0,x=e.occupied,S=Qs(e.occupyR,e.clearM),C=e.occupyTag??e.seed,w=[],T=i*(e.triesPerPoint??12),E=0;for(;w.length<i&&T>0;){--T;let n=E;E+=1;let r=a+l()*(s-a),i=o+l()*(c-o),m=l();if(!Us(r,i,t))continue;let D=!1;for(let e of f)if((e?.length??0)>=3&&Us(r,i,e)){D=!0;break}if(D)continue;let O=!1;for(let e of u)if(qs(e,r,i,d)){O=!0;break}if(O)continue;if(g){let e=Math.floor(r/p),t=Math.floor(i/p),n=!1;for(let a=-1;a<=1&&!n;a+=1)for(let o=-1;o<=1&&!n;o+=1){let s=g.get(`${e+o},${t+a}`);if(s)for(let[e,t]of s){let a=r-e,o=i-t;if(a*a+o*o<h){n=!0;break}}}if(n)continue}if(x&&x.blocks(r,i,S,C))continue;if(g){let e=`${Math.floor(r/p)},${Math.floor(i/p)}`,t=g.get(e);t?t.push([r,i]):g.set(e,[[r,i]])}x&&x.add(r,i,S,C);let k=Ps(m,e.yawMode,e.yawDeg,b?b(r,i):0);w.push(v?{x:r,z:i,yaw:k,variant:y>=0?y:Bs(e.seed,n,_)}:{x:r,z:i,yaw:k})}return w}function tc(e,t,n){let r=Number(e),i=Number(t);if(!Number.isFinite(r)||!Number.isFinite(i))return{scale:1,offsetY:0};let a=i-r,o=Number(n),s=Number.isFinite(o)&&o>0&&a>1e-6?o/a:1;return{scale:s,offsetY:-r*s}}var nc=4096;function rc(e){return Math.floor(e/64)}function ic(e,t,n,r,i){return`terrain:scatter:${e}:${t}:${n},${r}${Ls(i)}`}function ac(e,t){let n=e*64,r=t*64,i=n+64,a=r+64;return[[n,r],[i,r],[i,a],[n,a]]}function oc(e){let t=Number(e);return!Number.isFinite(t)||t<=0?1:Math.max(1,Math.min(Math.ceil(t/64),Math.floor(Math.sqrt(nc)/2)))}function sc(e,t,n){if(!Number.isFinite(e)||!Number.isFinite(t))return[];let r=oc(n),i=rc(e),a=rc(t),o=[];for(let e=-r;e<=r;e+=1)for(let t=-r;t<=r;t+=1)o.push([i+t,a+e]);return o}function cc(e){let t=e.ring??[];if(t.length<3)return[];let n=e.occupied;return ec({ring:ac(e.cx,e.cz),areaM2:4096,densityPer100m2:e.densityPer100m2,seed:e.seed,footprints:e.footprints,clearM:e.clearM,occluders:e.occluders,minSpacingM:e.minSpacingM,maxPoints:e.maxPoints??4e3,triesPerPoint:1,variantCount:e.variantCount,variant:e.variant,rng:e.rng,yawMode:e.yawMode,yawDeg:e.yawDeg,axisAt:e.axisAt,occupied:n?{blocks:(e,t,r,i)=>n.blocks(e,t,r,i),add:(e,r,i,a)=>{Us(e,r,t)&&n.add(e,r,i,a)}}:void 0,occupyR:e.occupyR,occupyTag:e.occupyTag}).filter(e=>Us(e.x,e.z,t))}var lc=Math.PI*2,uc=1e-4,dc=1e-9,fc=1e5;function pc(e){return(e%lc+lc)%lc}function mc(e,t,n,r,i,a){let o=i-n,s=a-r,c=o*o+s*s,l=c<1e-18?0:((e-n)*o+(t-r)*s)/c;l=l<0?0:l>1?1:l;let u=e-(n+l*o),d=t-(r+l*s);return Math.sqrt(u*u+d*d)}function hc(e,t,n,r,i){let a=r-t,o=i-n,s=Math.hypot(a,o);if(!(s>0))return 0;let c=Math.atan2(a,o),l=(t+r)/2,u=(n+i)/2,d=o/s,f=-a/s;return pc(Us(l+d*uc,u+f*uc,e)?c:c+Math.PI)}function gc(e,t){let n=e?.length??0;if(n<3)return[];let r=Array.from({length:n},(e,t)=>t);if(t!==`longest`&&t!==`opposite`)return r;let i=r.map(t=>{let[r,i]=e[t],[a,o]=e[(t+1)%n],s=Math.hypot(a-r,o-i);return Number.isFinite(s)?s:0}),a=0;for(let e=1;e<n;e+=1)i[e]>i[a]&&(a=e);if(t===`longest`)return[a];let o=-1;for(let e=0;e<n;e+=1)e!==a&&(o<0||i[e]>i[o])&&(o=e);return a<o?[a,o]:[o,a]}function _c(e,t){let n=e?.length??0;if(n<3)return[];let r=()=>Array.from({length:n},(e,t)=>t);if(t!==`longest`&&t!==`opposite`||n%2!=0)return r();let i=n/2,a=t=>{let[r,i]=e[t],[a,o]=e[(t+1)%n],s=Math.hypot(a-r,o-i);return Number.isFinite(s)?s:0},o=[],s=[],c=0,l=0;for(let e=0;e<=i-2;e+=1)o.push(e),c+=a(e);for(let e=i;e<=2*i-2;e+=1)s.push(e),l+=a(e);return t===`opposite`?[...o,...s]:l>c?s:o}function vc(e,t,n,r){let i=e?.length??0;if(i<3)return 0;let a=1/0,o=-1;for(let s=0,c=i-1;s<i;c=s,s+=1){if(r&&!r.includes(c))continue;let i=mc(t,n,e[c][0],e[c][1],e[s][0],e[s][1]);i<a&&(a=i,o=s)}if(o<0)return 0;let s=o===0?i-1:o-1;return hc(e,e[s][0],e[s][1],e[o][0],e[o][1])}function yc(e,t,n){let r=e?.length??0;if(r<2)return 0;let i=1/0,a=0;for(let o=1;o<r;o+=1){let[r,s]=e[o-1],[c,l]=e[o],u=c-r,d=l-s;if(u*u+d*d<1e-18)continue;let f=mc(t,n,r,s,c,l);f<i&&(i=f,a=pc(Math.atan2(u,d)))}return a}function bc(e,t,n){if(e)return(t,n)=>yc(e,t,n);let r=n===`longest`||n===`opposite`?gc(t,n):void 0;return(e,n)=>vc(t,e,n,r)}function xc(e,t,n){let r=e.length,i=1/0;for(let a=0,o=r-1;a<r;o=a,a+=1){let r=mc(t,n,e[o][0],e[o][1],e[a][0],e[a][1]);r<i&&(i=r)}return Us(t,n,e)?i:-i}function Sc(e,t,n,r){let i=xc(e,t,n);return{x:t,z:n,h:r,d:i,max:i+r*Math.SQRT2}}function Cc(e,t){e.push(t);let n=e.length-1;for(;n>0;){let t=n-1>>1;if(e[t].max>=e[n].max)break;let r=e[t];e[t]=e[n],e[n]=r,n=t}}function wc(e){let t=e[0],n=e.pop();if(e.length===0||n===void 0)return t;e[0]=n;let r=0;for(;;){let t=r*2+1,n=t+1,i=r;if(t<e.length&&e[t].max>e[i].max&&(i=t),n<e.length&&e[n].max>e[i].max&&(i=n),i===r)break;let a=e[i];e[i]=e[r],e[r]=a,r=i}return t}function Tc(e,t=.5){let n=e?.length??0;if(n<3)return{x:0,z:0,d:0};let r=1/0,i=1/0,a=-1/0,o=-1/0;for(let[t,n]of e){if(!Number.isFinite(t)||!Number.isFinite(n))return{x:0,z:0,d:0};t<r&&(r=t),t>a&&(a=t),n<i&&(i=n),n>o&&(o=n)}let s=a-r,c=o-i,l=Math.min(s,c);if(!(l>0))return{x:r+s/2,z:i+c/2,d:0};let u=Number.isFinite(t)&&t>0?t:.5,d=l/2,f=0,p=0,m=0;for(let t=0,r=n-1;t<n;r=t,t+=1){let[n,i]=e[t],[a,o]=e[r],s=n*o-a*i;f+=s,p+=(n+a)*s,m+=(i+o)*s}let h=Math.abs(f)>1e-12?Sc(e,p/(3*f),m/(3*f),0):Sc(e,r+s/2,i+c/2,0),g=Sc(e,r+s/2,i+c/2,0);g.d>h.d&&(h=g);let _=[];for(let t=r;t<a;t+=l)for(let n=i;n<o;n+=l)Cc(_,Sc(e,t+d,n+d,d));let v=_.length;for(;_.length>0&&v<fc;){let t=wc(_);if(!t)break;if(t.d>h.d&&(h=t),t.max-h.d<=u)continue;let n=t.h/2;Cc(_,Sc(e,t.x-n,t.z-n,n)),Cc(_,Sc(e,t.x+n,t.z-n,n)),Cc(_,Sc(e,t.x-n,t.z+n,n)),Cc(_,Sc(e,t.x+n,t.z+n,n)),v+=4}return{x:h.x,z:h.z,d:h.d}}function Ec(e){let t=[],n=0;for(let r of e??[]){if(!r||r.length<2)return[];let[e,i]=r;if(!Number.isFinite(e)||!Number.isFinite(i))return[];let a=t[t.length-1];a&&Math.abs(a.x-e)<dc&&Math.abs(a.z-i)<dc?a.index=n:t.push({x:e,z:i,index:n}),n+=1}let r=t[0],i=t[t.length-1];if(t.length>1&&Math.abs(r.x-i.x)<dc&&Math.abs(r.z-i.z)<dc&&t.pop(),t.length<3)return[];let a=[],o=0;for(let e=0;e<t.length;e+=1){let{x:n,z:r,index:i}=t[e],{x:s,z:c}=t[(e+1)%t.length],l=Math.hypot(s-n,c-r);l>dc&&(a.push({ax:n,az:r,bx:s,bz:c,len:l,start:o,end:o+l,index:i}),o+=l)}return a}function Dc(e,t){let n=Number(t?.spacingM);if(!Number.isFinite(n)||n<=0)return[];let r=t?.offsetM===void 0?0:Number(t.offsetM);if(!Number.isFinite(r)||r<0)return[];let i=Ec(e);if(i.length<3)return[];let a=typeof t.startM==`number`&&Number.isFinite(t.startM)&&t.startM>=0?Math.min(t.startM,n):n/2,o=t.maxPoints??2e3,s=Number(t.jitterM),c=s>0?t.jitterRng??Hs(`${t.seed??``}:jitter`):null,l=new Map,u=[],d=(t,i)=>{let d=0,f=0;for(let p=0;;p+=1){if(c){let e=(2*c()-1)*s;f=p===0?a+e:f+n+e,f<0&&(f=0)}else f=a+p*n;if(!(f<i-dc)||u.length>=o)break;for(;d<t.length-1&&f>=t[d].end;)d+=1;let m=t[d],h=(f-m.start)/m.len;h=h<0?0:h>1?1:h;let g=m.ax+h*(m.bx-m.ax),_=m.az+h*(m.bz-m.az),v=l.get(m.index);v===void 0&&(v=hc(e,m.ax,m.az,m.bx,m.bz),l.set(m.index,v));let y=v+Math.PI/2;u.push({x:g+Math.sin(y)*r,z:_+Math.cos(y)*r,axis:v,ordinal:u.length})}},f=e=>{for(let t of e){let e=0,n=t.map(t=>{let n={...t,start:e,end:e+t.len};return e+=t.len,n});if(e>dc&&(d(n,e),u.length>=o))break}},p=t.edges;if(p){let e=new Set(p),t=[],n=null;for(let r of i){if(!e.has(r.index)){n=null;continue}n?n.push(r):(n=[r],t.push(n))}return f(t),u}let m=t.sides;return m!==`longest`&&m!==`opposite`?(d(i,i[i.length-1].end),u):(f(gc(e,m).map(e=>i.filter(t=>t.index===e))),u)}function Oc(e,t,n){for(let r of e)if((r?.length??0)>=3&&Us(t,n,r))return!0;return!1}function kc(e,t,n,r){for(let i of e)if(qs(i,t,n,r))return!0;return!1}function Ac(e,t){let n=Dc(e,t);if(n.length===0)return[];let r=t.rng??Hs(t.seed),i=t.footprints??[],a=t.occluders??[],o=t.occupied,s=Qs(t.occupyR,t.clearM),c=t.occupyTag??t.seed,l=Math.floor(Number(t.variantCount)),u=Number.isFinite(l)&&l>1,d=u?Vs(t.variant,l):-1,f=[];for(let p of n){let n=r(),{x:m,z:h}=p,g=p.axis+Math.PI/2;if(!Us(m+Math.sin(g)*uc,h+Math.cos(g)*uc,e)||Oc(a,m,h)||kc(i,m,h,t.clearM)||o&&o.blocks(m,h,s,c))continue;o&&o.add(m,h,s,c);let _=Ps(n,t.yawMode,t.yawDeg,p.axis);f.push(u?{x:m,z:h,yaw:_,variant:d>=0?d:Bs(t.seed,p.ordinal,l)}:{x:m,z:h,yaw:_})}return f}function jc(e,t){if((e?.length??0)<3)return[];let n=Tc(e);if(!(n.d>0))return[];let r=(t.rng??Hs(t.seed))(),{x:i,z:a}=n;if(Oc(t.occluders??[],i,a)||kc(t.footprints??[],i,a,t.clearM))return[];let o=Qs(t.occupyR,t.clearM),s=t.occupyTag??t.seed;if(t.occupied&&t.occupied.blocks(i,a,o,s))return[];t.occupied&&t.occupied.add(i,a,o,s);let c=t.yawMode===`aligned`?t.axisAt?t.axisAt(i,a):vc(e,i,a):0,l=Ps(r,t.yawMode,t.yawDeg,c),u=Math.floor(Number(t.variantCount));if(!Number.isFinite(u)||u<=1)return[{x:i,z:a,yaw:l}];let d=Vs(t.variant,u);return[{x:i,z:a,yaw:l,variant:d>=0?d:Bs(t.seed,0,u)}]}Object.freeze({yawDeg:0,tiltDeg:0,rollDeg:0,shiftCm:[0,0],roleShiftM:{},heightCm:{}}),Math.PI/180;function Mc(e,t,n){let r=Math.cos(e),i=Math.sin(e),a=Math.cos(t),o=Math.sin(t),s=Math.cos(n),c=Math.sin(n);return[a*s+o*i*c,-a*c+o*i*s,o*r,r*c,r*s,-i,-o*s+a*i*c,o*c+a*i*s,a*r]}var Nc=.5,Pc={value:0},Fc={value:{r:.62,g:.78,b:.91}},Ic=Fc;function Lc(e){Pc.value=(Pc.value+(e||0))%3600}function Rc(e){Ic.value={r:(e>>16&255)/255,g:(e>>8&255)/255,b:(e&255)/255}}var zc=null,Bc=null;function Vc(e){let t=document.createElement(`canvas`);t.width=t.height=1;let n=t.getContext(`2d`);n.fillStyle=`#fff`,n.fillRect(0,0,1,1);let r=new e.CanvasTexture(t);return r.needsUpdate=!0,r}function Hc(e){let t=document.createElement(`canvas`);t.width=t.height=256;let n=t.getContext(`2d`),r=n.createImageData(256,256);for(let e=0;e<256;e++)for(let t=0;t<256;t++){let n=Uc(t,e,256),i=(e*256+t)*4;r.data[i]=n[0],r.data[i+1]=n[1],r.data[i+2]=n[2],r.data[i+3]=n[3]}n.putImageData(r,0,0);let i=new e.CanvasTexture(t);return i.wrapS=i.wrapT=e.RepeatWrapping,i.anisotropy=4,i.needsUpdate=!0,i}function Uc(e,t,n=256){let r=[[1,2,1,0],[2,-1,.7,1.7],[3,2,.4,3.1],[-2,3,.3,5]],i=(e,t)=>{let n=0;for(let[i,a,o,s]of r)n+=o*Math.sin(2*Math.PI*(i*e+a*t)+s);return n},a=1/n,o=e/n,s=t/n,c=(i(o+a,s)-i(o-a,s))/(2*a),l=(i(o,s+a)-i(o,s-a))/(2*a),u=.02,d=-c*u,f=-l*u,p=Math.hypot(d,f,1)||1;return d/=p,f/=p,[Math.round((d*.5+.5)*255),Math.round((f*.5+.5)*255),Math.round((1/p*.5+.5)*255),255]}function Wc(e){return zc||=Hc(e),zc}var Gc=`#include <begin_vertex>`,Kc=`#include <normal_fragment_maps>`,qc=`#include <map_fragment>`,Jc=`#include <roughnessmap_fragment>`,Yc=`#include <opaque_fragment>`,Xc=!1;function Zc(e){Xc||(Xc=!0,console.warn(`[scene-render] water shader: anchor "${e}" not found in this three version — the surface renders matte instead. One line to re-point.`))}function Qc(e,t){return t==null?new e.Color(16777215):typeof t==`number`||typeof t==`string`?new e.Color(t):new e.Color(t.r,t.g,t.b)}function $c(e){let t=parseInt((e||`#3f7fb8`).slice(1),16);return{r:(t>>16&255)/255,g:(t>>8&255)/255,b:(t&255)/255}}function el(e,t,n){let r={value:Math.max(t.wave_m??1.6,.05)},i={value:t.speed??.05},a={value:t.flow_speed??.5},o={value:t.sky_mix??.55},s={value:$c(t.tint)},c={value:t.map_strength??.75},l={value:n};e.onBeforeCompile=e=>{if(e.uniforms.uTime=Pc,e.uniforms.uSky=Ic,e.uniforms.uWaveM=r,e.uniforms.uSpeed=i,e.uniforms.uFlowSpeed=a,e.uniforms.uSkyMix=o,e.uniforms.uTint=s,e.uniforms.uMapStrength=c,e.uniforms.uMask=l,e.vertexShader.includes(Gc))e.vertexShader=`attribute vec2 aWaterFlow;
varying vec2 vWaterWorld;
varying vec2 vWaterUv;
varying vec2 vWaterFlow;
`+e.vertexShader.replace(Gc,`${Gc}\n  vWaterWorld = ( modelMatrix * vec4( transformed, 1.0 ) ).xz;
  vWaterUv = uv;
  vWaterFlow = aWaterFlow;`);else{Zc(Gc);return}e.fragmentShader=`varying vec2 vWaterWorld;
varying vec2 vWaterUv;
varying vec2 vWaterFlow;
uniform float uTime;
uniform vec3 uSky;
uniform float uWaveM;
uniform float uSpeed;
uniform float uFlowSpeed;
uniform float uSkyMix;
uniform vec3 uTint;
uniform float uMapStrength;
uniform sampler2D uMask;
`+e.fragmentShader,e.fragmentShader.includes(Kc)?e.fragmentShader=e.fragmentShader.replace(Kc,`
  // tbn comes from normal_fragment_begin and exists only with this define
  // — without the guard this would be a compile error instead of a matte
  // material.
  #ifdef USE_NORMALMAP_TANGENTSPACE
  {
    float wMask = texture2D( uMask, vWaterUv ).r;
    // HOW MUCH OF THE RIPPLE THIS PIXEL CAN STILL RESOLVE (finding round
    // 2026-08-21). One pixel covers wPx metres of water; once that reaches a
    // whole wavelength the normal map carries no signal a pixel could show, and
    // what is left is sampling noise — which at roughness 0.08 lands in a
    // specular lobe narrow enough to turn every noisy texel into a spark. The
    // mip chain does not save it: averaging normals SHORTENS them instead of
    // widening the lobe, so the highlights stay as tight as they were. Fading
    // the perturbation back to flat over that same footprint is the cheap,
    // standard answer, and it is also the truthful picture — a lake a
    // kilometre off is a mirror, not a texture.
    //
    // MEASURED ON THE WORLD POSITION, never on the sampled normal: vWaterWorld
    // is continuous by construction (the mirror is a plane), while a derivative
    // of what comes back from a texture jumps wherever the texture does — the
    // very lesson scene-render layerCut.ts spells out.
    float wPx = max( length( dFdx( vWaterWorld ) ), length( dFdy( vWaterWorld ) ) );
    float wDetail = clamp( 1.0 - wPx / uWaveM, 0.0, 1.0 );
    // THE DIRECTION THE TWO LAYERS SCROLL IN (W2 no. 2). The frame is the
    // FLOW's: wAx points downstream, wAy across it. With no flow (vWaterFlow
    // == (0, 0), i.e. a lake, an ice sheet, or any surface that carries no
    // attribute at all) the frame is the world's own axes and every ternary
    // below takes its still branch — which reproduces, constant for constant,
    // the shader that stood here before.
    //
    // The division is by a FLOORED length, never by the raw one: a still
    // surface hands over (0, 0), and a normalize() of that is a NaN that the
    // ternary would not reliably keep out of the result.
    float wLen = length( vWaterFlow );
    bool wStill = wLen < 1e-4;
    vec2 wAx = wStill ? vec2( 1.0, 0.0 ) : vWaterFlow / max( wLen, 1e-4 );
    vec2 wAy = vec2( -wAx.y, wAx.x );
    // TWO SPEEDS, NOT ONE (user finding 2026-08-23: "the water flows too fast
    // and the direction is not clearly recognisable"). A lake counter-scrolls
    // its two layers, so they cancel and the net motion reads slow; a river
    // sends BOTH downstream, so the identical number reads several times
    // faster. One dial cannot serve both, and lowering it would freeze the
    // lakes. uSpeed stays the still-water number, uFlowSpeed is the river's.
    //
    // …AND THE LENGTH OF THE FLOW IS THE AREA'S OWN FACTOR (finding
    // 2026-08-23 no. 2, meta.flow_speed_m_s). The attribute has always been
    // a UNIT tangent, so wLen was 1.0 on every flowing water and this
    // multiplication changes not one existing pixel; an area that authors its
    // own speed sends the ratio (area m/s ÷ kind m/s) as that length instead,
    // and uFlowSpeed · wLen is the area's metres per second again. The
    // DIRECTION is untouched — wAx divides the very same vector by wLen — and
    // so is the still branch: the encoder floors the factor at 1e-3, ten times
    // the 1e-4 threshold below, so a river dialled to 0 never turns into a
    // lake drifting at uSpeed.
    float wSpeed = wStill ? uSpeed : uFlowSpeed * wLen;
    // The offset is divided by the wavelength of the RESPECTIVE layer —
    // which makes the speed real METRES PER SECOND, and both layers drift at
    // the same rate although their wavelengths differ. Without the division it
    // would be "wavelengths per second": 0.05 meant one crest every 20
    // seconds, 1.7 cm/s on the map — present, but invisible.
    //
    // AND THE SIGN. Adding v·t to a SAMPLE coordinate slides the picture the
    // OTHER way — uv + vec2( t, 0 ) is the classic leftward scroll. So the
    // offset that has stood here since the lake was written carries the crests
    // AGAINST wDirA, i.e. upstream on a river, which is the second half of
    // "the flow direction is not clearly recognisable": the ripple ran the
    // wrong way. Flowing water therefore drifts by −1, and the crests travel
    // along wDirA the way the vector says.
    //
    // Still water keeps the +1 it always had, deliberately: a lake has no
    // reference direction — its two sheets counter-scroll either way, and the
    // requirement is that it looks EXACTLY as it did, not that it agrees with
    // a river about a sign nobody can see on it.
    float wFlowSign = wStill ? 1.0 : -1.0;
    float wDriftA = uTime * wSpeed * wFlowSign / uWaveM;
    float wDriftB = uTime * wSpeed * wFlowSign / ( uWaveM * 0.63 );
    // THE CROSS COMPONENTS. Still water wants the two sheets to run across
    // each other — (1, 0.6) and −(0.8, 1.3) counter-scrolling is what a lake
    // looks like. A river must not: those cross components are 31° and 58° off
    // the flow, and 58° is not a stream, it is the diagonal shimmer the finding
    // names. Flowing water therefore keeps the ALONG components (1.0 and 0.8)
    // and shrinks the cross ones to 0.15 and 0.3 — 8.5° and 20.6° off the flow,
    // both plainly downstream, yet still of OPPOSITE SIGN and of different
    // magnitude, so the two sheets go on beating against each other instead of
    // sliding as one rigid photograph.
    //
    // Layer A's along component is exactly 1.0, so on flowing water uFlowSpeed
    // IS the downstream metres per second of the leading layer; B follows at
    // 0.8 of it. (On still water the old lengths √1.36 / √2.33 are untouched.)
    float wCrossA = wStill ? 0.6 : 0.15;
    float wCrossB = wStill ? 1.3 : 0.3;
    vec2 wDirA = wAx + wAy * wCrossA;
    vec2 wDirB = wStill ? -( wAx * 0.8 + wAy * wCrossB ) : wAx * 0.8 - wAy * wCrossB;
    vec2 wRawA = vWaterWorld / uWaveM + wDirA * wDriftA;
    vec2 wRawB = vWaterWorld / ( uWaveM * 0.63 ) + wDirB * wDriftB;
    // ANISOTROPY: a current does not ripple in circles, it draws STREAKS. The
    // wave normal map is isotropic, so the stretch happens in the lookup —
    // squeeze the ALONG-flow coordinate by 3, leave the cross one alone, and
    // every crest comes out three times as long as it is wide, pulled down the
    // stream. 3 is the smallest ratio that reads as a direction at a glance;
    // more and the map's own frequencies smear into bands.
    //
    // The squeeze is applied to the WHOLE sample coordinate, drift included,
    // and that is what keeps the metres per second honest: the map is linear,
    // so squeezing (world/λ + dir·drift) is the same field, stretched, sampled
    // at the same argument — the crests still travel at wSpeed · |dir| m/s.
    // Still water squeezes by 1 in the world's own frame, i.e. not at all.
    float wAniso = 3.0;
    vec2 wUvA = wStill ? wRawA
      : wAx * ( dot( wRawA, wAx ) / wAniso ) + wAy * dot( wRawA, wAy );
    vec2 wUvB = wStill ? wRawB
      : wAx * ( dot( wRawB, wAx ) / wAniso ) + wAy * dot( wRawB, wAy );
    // A THIRD, FAINT LAYER: the same map read as a long ribbon — 2 λ across
    // the flow, 8 × that along it — sliding downstream at the same speed. Its
    // crests are lines PARALLEL to the current, so the direction reads even in
    // flat light, where no highlight moves and the two ripple sheets say
    // nothing. Weight 0.35 against the two full-strength layers: visible as
    // texture, never as a second wave. Exactly 0 on still water, so the sum
    // below is bit for bit the lake it always was (the tap itself stays
    // unconditional — a texture fetch under non-uniform control flow has no
    // defined derivatives).
    float wStreak = wStill ? 0.0 : 0.35;
    vec2 wRawC = ( vWaterWorld + wAx * ( uTime * wSpeed * wFlowSign ) )
                 / ( uWaveM * 2.0 );
    vec2 wUvC = wAx * ( dot( wRawC, wAx ) / 8.0 ) + wAy * dot( wRawC, wAy );
    vec3 wN = normalize( ( texture2D( normalMap, wUvA ).xyz * 2.0 - 1.0 )
                       + ( texture2D( normalMap, wUvB ).xyz * 2.0 - 1.0 )
                       + ( texture2D( normalMap, wUvC ).xyz * 2.0 - 1.0 )
                         * wStreak );
    wN = mix( vec3( 0.0, 0.0, 1.0 ), wN, wMask * wDetail );
    wN.xy *= normalScale;
    normal = normalize( tbn * wN );
  }
  #endif`):Zc(Kc),e.fragmentShader.includes(qc)?e.fragmentShader=e.fragmentShader.replace(qc,`${qc}\n  diffuseColor.rgb = mix( uTint, diffuseColor.rgb, mix( 1.0, uMapStrength, texture2D( uMask, vWaterUv ).r ) );`):Zc(qc),e.fragmentShader.includes(Jc)?e.fragmentShader=e.fragmentShader.replace(Jc,`${Jc}\n  roughnessFactor = mix( 0.85, roughnessFactor, texture2D( uMask, vWaterUv ).r );`):Zc(Jc),e.fragmentShader.includes(Yc)?e.fragmentShader=e.fragmentShader.replace(Yc,`
  {
    float wFres = pow( 1.0 - saturate( dot( normalize( vViewPosition ), normal ) ), 3.0 );
    outgoingLight = mix( outgoingLight, uSky,
                         clamp( wFres * uSkyMix, 0.0, 1.0 )
                         * texture2D( uMask, vWaterUv ).r );
  }
  ${Yc}`):Zc(Yc)},e.customProgramCacheKey=()=>`anima-water`}function tl(e){let t=e?.class||`matte`,n=t===`water`||t===`ice`;return{roughness:e?.roughness??(n?.08:t===`gloss`?.25:.85),metalness:e?.metalness??(n?.15:.02),...t===`glow`?{emissiveIntensity:e?.glow??1}:{}}}function nl(e,t){let n=t.material||null,r=n?.class||`matte`,i=r===`water`||r===`ice`,a={...tl(n)};t.map?a.map=t.map:a.color=Qc(e,t.color??(i?n?.tint:16777215)),t.transparent&&(a.transparent=!0),t.opacity!==void 0&&(a.opacity=t.opacity),t.side!==void 0&&(a.side=t.side),t.depthWrite!==void 0&&(a.depthWrite=t.depthWrite);let o=new e.MeshStandardMaterial(a);return r===`glow`&&(o.emissive=Qc(e,n?.tint??16777215),o.emissiveIntensity=tl(n).emissiveIntensity,t.map&&(o.emissiveMap=t.map)),i&&(zc||=Hc(e),o.normalMap=zc,o.normalScale=new e.Vector2(1,1),Bc||=Vc(e),el(o,n,t.mask||Bc)),o}var rl=[`hand_left`,`hand_right`],il=[`attached_part`,`appendage_chain`],al=Object.freeze({hand_left:.025,hand_right:.025}),ol=`mouth`,sl=Object.freeze({forward:.5,up:.15,lengthM:.2,depth:.5,radius:.1,funnel:.15,coneDeg:35,minLength:0,compressMin:.6});function cl(e){return typeof e==`string`&&rl.includes(e)}var ll=[`lefthand`,`lefthandmiddle1`,`lefthandindex1`,`lefthandpinky1`,`righthand`,`righthandmiddle1`,`righthandindex1`,`righthandpinky1`,`head`,`headtop_end`,`lefteye`,`righteye`],ul=(e,t)=>[e[0]-t[0],e[1]-t[1],e[2]-t[2]],dl=(e,t)=>[e[0]+t[0],e[1]+t[1],e[2]+t[2]],fl=(e,t)=>[e[0]*t,e[1]*t,e[2]*t],pl=(e,t)=>e[0]*t[0]+e[1]*t[1]+e[2]*t[2],ml=e=>Math.hypot(e[0],e[1],e[2]),hl=e=>{let t=ml(e);return t>1e-9?fl(e,1/t):null};function gl(e,t){let n=e===`hand_left`?`left`:`right`,r=t[`${n}hand`],i=t[`${n}handindex1`],a=t[`${n}handpinky1`];if(!r||!i||!a)return null;let o=t[`${n}handmiddle1`]??fl(dl(i,a),.5),s=hl(ul(a,i));return s?{id:e,o:fl(dl(r,o),.5),u:s,r:al[e]}:null}function _l(e){let t=e.head;if(!t)return null;let n=e.headtop_end,r=n?ml(ul(n,t)):sl.lengthM*(e.headY?ml(e.headY):1);if(!(r>1e-6))return null;let i=n&&hl(ul(n,t))||e.headY&&hl(e.headY)||[0,1,0],a=null;return e.lefteye&&e.righteye?a=ul(fl(dl(e.lefteye,e.righteye),.5),t):e.headZ&&(a=e.headZ),a?(a=hl(ul(a,fl(i,pl(a,i)))),a?{H:t,L:r,h:i,f:a}:null):null}function vl(e,t=new Set){let n=_l(e);if(!n)return null;let{H:r,L:i,h:a,f:o}=n;return{id:ol,o:dl(dl(r,fl(o,sl.forward*i)),fl(a,sl.up*i)),u:fl(o,-1),depth:sl.depth*i,r:sl.radius*i,coneDeg:sl.coneDeg,funnel:sl.funnel*i,accepts:il,minLength:sl.minLength,compressMin:sl.compressMin,kinds:null,suppress:t}}function yl(e){return rl.map(t=>gl(t,e)).filter(e=>!!e)}function bl(e,t,n,r){return e!==`hand_left`&&e!==`hand_right`?t:pl(t,ul(n,r))<0?fl(t,-1):t}var xl=.2,Sl=Object.freeze({h:.005,deg:10,pastBottom:!0}),Cl=Math.PI/180,wl=64,Tl=48,El=1e-9,Dl=(e,t)=>[e[0]-t[0],e[1]-t[1],e[2]-t[2]],Ol=(e,t)=>[e[0]+t[0],e[1]+t[1],e[2]+t[2]],kl=(e,t)=>[e[0]*t,e[1]*t,e[2]*t],Al=(e,t)=>e[0]*t[0]+e[1]*t[1]+e[2]*t[2],jl=(e,t)=>[e[1]*t[2]-e[2]*t[1],e[2]*t[0]-e[0]*t[2],e[0]*t[1]-e[1]*t[0]],Ml=e=>Math.hypot(e[0],e[1],e[2]);function Nl(e,t,n){let r=Math.cos(n),i=Math.sin(n),a=jl(t,e),o=Al(t,e);return[e[0]*r+a[0]*i+t[0]*o*(1-r),e[1]*r+a[1]*i+t[1]*o*(1-r),e[2]*r+a[2]*i+t[2]*o*(1-r)]}function Pl(e,t){let n=Dl(e,t.o),r=Al(n,t.u);return{s:r,rho:Ml(Dl(n,kl(t.u,r)))}}function Fl(e,t,n,r){let i=r?.h??0,a=(n.coneDeg+(r?.deg??0))*Cl;return e>=0?(e<=n.depth||r?.pastBottom)&&t<=n.r+i?`cylinder`:null:e>=-(n.funnel+i)&&t<=n.r+i+-e*Math.tan(a)?`funnel`:null}function Il(e,t,n){let r=e<0?t.r+-e*Math.tan(t.coneDeg*Cl):t.r;return Math.max(0,r-n)}function Ll(e,t,n,r){let i=Dl(t,e),a=Ml(i);if(!(a>1e-12))return null;let{s:o,rho:s}=Pl(t,n);if(o<-n.funnel)return null;let c=e=>{let t=Pl(e,n);return t.rho-Il(t.s,n,r)},l=s-Il(o,n,r);if(l<=El)return null;let u=kl(Dl(Dl(t,n.o),kl(n.u,o)),1/s),d=jl(u,i);Ml(d)<1e-9*a&&(d=jl(u,n.u)),d=kl(d,1/Ml(d));let f=t=>c(Ol(e,Nl(i,d,t))),p=Math.PI/wl,m=0,h=l;for(let e=1;e<=wl;e++){let t=e*p,n=f(t);if(n<=0){let e=t-p,n=t;for(let t=0;t<Tl;t++){let t=(e+n)/2;f(t)<=0?n=t:e=t}return{angle:n,axis:d}}n<h&&(m=t,h=n)}if(!(m>0))return null;let g=Math.max(0,m-p),_=Math.min(Math.PI,m+p);for(let e=0;e<Tl;e++){let e=g+(_-g)/3,t=_-(_-g)/3;f(e)<=f(t)?_=t:g=e}return{angle:(g+_)/2,axis:d}}function Rl(e){let t=-1;for(let n=0;n<e.length;n++){if(e[n]>=0)return n;(t<0||e[n]>=e[t])&&(t=n)}return t}function zl(e,t,n,r){let i=n.depth-r;return!(e>i)||!(e-t>1e-12)?1:Math.min(1,Math.max(n.compressMin,(i-t)/(e-t)))}function Bl(e,t,n,r){let i=e.engaged?t.gate&&t.tipInGrownZone:t.gate&&t.tipInZone&&t.leverAngleDeg<=n.coneDeg,a=Math.max(0,r)/xl;return{engaged:i,w:i?Math.min(1,e.w+a):Math.max(0,e.w-a)}}function Vl(e,t,n,r){if(!e.op||!t.accepts.includes(e.op)||!(e.length>=t.minLength))return!1;let i=n.interaction,a=r.interaction;return!i||!a||i.id!==a.id?!1:t.kinds===null||t.kinds.includes(a.kind)}var Hl=.035;function Ul(e,t,n,r,i=32,a=Hl){let o=[],s=a*a,c=Math.floor(e.length/3);for(let t=0;t<c;t++){let n=e[t*3]-r[0],a=e[t*3+1]-r[1],c=e[t*3+2]-r[2],l=n*n+a*a+c*c;l>s||(o.length<i?(o.push([l,t]),o.sort((e,t)=>e[0]-t[0])):l<o[i-1][0]&&(o[i-1]=[l,t],o.sort((e,t)=>e[0]-t[0])))}let l=new Map,u=0;for(let[,e]of o)for(let r=0;r<4;r++){let i=n[e*4+r];if(!(i>0))continue;let a=t[e*4+r];l.set(a,(l.get(a)??0)+i),u+=i}if(!(u>0))return null;for(let[e,t]of l)l.set(e,t/u);return l}function Wl(e,t){let n=Array(16).fill(0);for(let[r,i]of t){let t=e.skeleton.bones[r];if(!t)continue;let a=Xo(e.matrixWorld.elements,e.bindMatrixInverse.elements,t.matrixWorld.elements,e.skeleton.boneInverses[r].elements,e.bindMatrix.elements).bindToWorld;for(let e=0;e<16;e++)n[e]+=i*a[e]}return n}function Gl(e,t){let n=e.geometry,r=n?.attributes?.position,i=n?.attributes?.skinIndex,a=n?.attributes?.skinWeight;if(!r||!i||!a)return null;let o=Ul(r.array,i.array,a.array,t,32,1/0);return o?{mesh:e,weights:o}:null}function Kl(e,t){let n=null,r=0;for(let i of e){let e=i.geometry,a=e?.attributes?.position,o=e?.attributes?.skinIndex,s=e?.attributes?.skinWeight;if(!a||!o||!s||a.itemSize!==3||o.itemSize!==4||s.itemSize!==4||[a,o,s].some(e=>e.isInterleavedBufferAttribute))continue;let c=a.array,l=Hl*Hl,u=0;for(let e=0;e<c.length;e+=3){let n=c[e]-t[0],r=c[e+1]-t[1],i=c[e+2]-t[2];n*n+r*r+i*i<=l&&u++}if(u<=r)continue;let d=Ul(c,o.array,s.array,t);d&&(n={mesh:i,weights:d},r=u)}return n}function ql(e,t,n){if(!n||n.version!==8)return null;let r=Qo(t),i=[],a=[];t.traverse(e=>{let t=e;t.isSkinnedMesh&&t.skeleton&&!Uo(t)&&a.push(t)});for(let e of n.channels??[]){let t=r.get(Z(e.a)),n=r.get(Z(e.b));if(!t||!n||!(e.r>0))continue;let o=Kl(a,e.a_pos),s=o?Gl(o.mesh,e.b_pos):null;i.push({record:e,ja:t,jb:n,suppress:new Set(e.suppress),wa:o,wb:s})}let o=e=>{let{record:t}=e,n=Zo(t,$o(e.ja),$o(e.jb));e.wa&&(n.a=Jo(Wl(e.wa.mesh,e.wa.weights),t.a_pos)),e.wb&&(n.b=Jo(Wl(e.wb.mesh,e.wb.weights),t.b_pos));let r=Dl(n.b,n.a),i=Ml(r);return i>1e-12?{id:t.id,o:n.a,u:kl(r,1/i),depth:i,r:n.r,coneDeg:t.cone_deg,funnel:t.funnel*(n.r/t.r),accepts:t.accepts,minLength:t.min_length,compressMin:t.compress_min,kinds:t.interaction_kinds??null,suppress:e.suppress}:null},s=i.filter(e=>o(e)!==null),c=new Map;t.traverse(e=>{if(!e.isBone)return;let t=Z(e.name);(t===`head`||t===`headtop_end`||t===`lefteye`||t===`righteye`)&&!c.has(t)&&c.set(t,e)});let l=new Set(n.capsules.filter(e=>e.region===`head`).map(e=>e.id)),u=()=>{if(!c.has(`head`))return null;let e={};for(let[t,n]of c){let r=n.matrixWorld.elements;if(e[t]=[r[12],r[13],r[14]],t===`head`){let t=Math.hypot(r[8],r[9],r[10])||1;e.headZ=[r[8]/t,r[9]/t,r[10]/t],e.headY=[r[4],r[5],r[6]]}}return vl(e,l)},d=u()!==null;if(!s.length&&!d)return null;let f=[],p=()=>{if(s.forEach((e,t)=>{let n=o(e);n&&(f[t]=n)}),d){let e=u();e&&(f[s.length]=e)}};return p(),{channels:f,update:p}}var Jl=.04,Yl=.0015,Xl=1e-6,Zl=12,Ql=14;function $l(e,t){return Math.hypot(e[0]-t[0],e[1]-t[1],e[2]-t[2])}function eu(e,t,n){let r=n[0]-t[0],i=n[1]-t[1],a=n[2]-t[2],o=e[0]-t[0],s=e[1]-t[1],c=e[2]-t[2],l=r*r+i*i+a*a,u=l>1e-12?Math.min(1,Math.max(0,(o*r+s*i+c*a)/l)):0;return Math.hypot(o-r*u,s-i*u,c-a*u)}function tu(e){if(!e.length)return null;let t=0,n=0,r=0;for(let{a:i,b:a}of e)t+=i[0]+a[0],n+=i[1]+a[1],r+=i[2]+a[2];let i=2*e.length,a=[t/i,n/i,r/i],o=0;for(let t of e)o=Math.max(o,Math.max($l(t.a,a),$l(t.b,a))+t.r);return{c:a,r:o}}function nu(e,t,n){let r=e.r+Math.max(0,t);for(let t of n??[])r=Math.max(r,$l(t.c,e.c)+t.r);return{c:[e.c[0],e.c[1],e.c[2]],r}}function ru(e,t,n,r=4){let i=[];return n.forEach((n,r)=>{let a=$l(n.body.c,e.c)-e.r-n.body.r;a<=0&&i.push({name:n.name,member:t.has(n.name),gap:a,order:r})}),i.sort((e,t)=>(e.member===t.member?0:e.member?-1:1)||e.gap-t.gap||e.order-t.order),i.slice(0,Math.max(0,r)).map(e=>e.name)}function iu(e,t){let n=t.some(e=>e.capsule.region===`outer_trunk`);return t.filter(t=>{let r=t.capsule.region;return n&&r===`torso`?!1:e===`hair`||!Go.includes(r)})}function au(e,t,n){return t.map((t,n)=>({i:n,d:eu(e.c,t.a,t.b)-t.r})).sort((e,t)=>e.d-t.d||e.i-t.i).slice(0,Math.max(0,n)).map(e=>e.i)}var ou=8,su=1e-6;function cu(){return{n:0,keys:[],nows:[],seg:new Float64Array}}function lu(e,t){if(e.seg.length>=t*ou)return;let n=new Float64Array(Math.max(t,2*e.seg.length/ou,16)*ou);n.set(e.seg),e.seg=n}function uu(e,t,n){lu(e,e.n+1);let r=e.n*ou,i=e.seg,{a,b:o}=n;i[r]=a[0],i[r+1]=a[1],i[r+2]=a[2],i[r+3]=o[0]-a[0],i[r+4]=o[1]-a[1],i[r+5]=o[2]-a[2],i[r+6]=i[r+3]*i[r+3]+i[r+4]*i[r+4]+i[r+5]*i[r+5],i[r+7]=n.r,e.keys[e.n]=t,e.nows[e.n]=n,e.n++}function du(e,t,n,r,i){let a=e[t+3],o=e[t+4],s=e[t+5],c=e[t+6],l=n-e[t],u=r-e[t+1],d=i-e[t+2],f=c>1e-12?Math.min(1,Math.max(0,(l*a+u*o+d*s)/c)):0;return Math.hypot(l-a*f,u-o*f,d-s*f)}function fu(e,t,n,r,i,a){let o=e[t+3],s=e[t+4],c=e[t+5],l=e[t+6],u=n-e[t],d=r-e[t+1],f=i-e[t+2],p=l>1e-12?Math.min(1,Math.max(0,(u*o+d*s+f*c)/l)):0,m=u-o*p,h=d-s*p,g=f-c*p,_=Math.sqrt(m*m+h*h+g*g),v=pu+mu*_;return _>a+v?1:_<a-v?-1:0}var pu=1e-9,mu=1e-9,hu=new WeakMap;function gu(e){let t=hu.get(e);if(t&&t.capsules===e.capsules)return t;let n=e.capsules.map(e=>({capsule:e})),r={capsules:e.capsules,hair:cu(),extension:cu()};for(let t of[`hair`,`extension`])for(let{capsule:i}of iu(t,n))uu(r[t],`${e.name}:${i.id}`,i.now);return hu.set(e,r),r}function _u(e,t,n){e.n=0;let r=0;for(let e of n)r+=gu(e)[t].n;lu(e,r);for(let r of n){let n=gu(r)[t];e.seg.set(n.seg.subarray(0,n.n*ou),e.n*ou);for(let t=0;t<n.n;t++)e.keys[e.n+t]=n.keys[t],e.nows[e.n+t]=n.nows[t];e.n+=n.n}return e.keys.length=e.n,e.nows.length=e.n,e}function vu(e,t){let n=[];for(let r of t){let t=gu(r)[e];for(let e=0;e<t.n;e++)n.push(t.nows[e])}return n}function yu(e,t,n,r){r.n=0,lu(r,e.n);for(let i=0;i<e.n;i++){let a=i*ou;fu(e.seg,a,t[0],t[1],t[2],n+e.seg[a+7]+su)>0||(r.seg.set(e.seg.subarray(a,a+ou),r.n*ou),r.keys[r.n]=e.keys[i],r.nows[r.n]=e.nows[i],r.n++)}return r.keys.length=r.n,r.nows.length=r.n,r}function bu(e,t,n,r,i,a){let o=e.seg,[s,c,l]=t,u=0;for(let t=0;t<e.n;t++){let e=t*ou,r=o[e+7],d=n+r,f=fu(o,e,s,c,l,d);if(f>0)continue;if(f<0){i[u]=t,a[u]=NaN,u++;continue}let p=du(o,e,s,c,l);p<=d&&(i[u]=t,a[u]=p-r,u++)}let d=Math.max(0,r);if(u<=d)return u;for(let e=0;e<u;e++)if(Number.isNaN(a[e])){let t=i[e]*ou;a[e]=du(o,t,s,c,l)-o[t+7]}for(let e=1;e<u;e++){let t=i[e],n=a[e],r=e-1;for(;r>=0&&a[r]>n;r--)i[r+1]=i[r],a[r+1]=a[r];i[r+1]=t,a[r+1]=n}for(let e=1;e<d;e++){let t=i[e],n=e-1;for(;n>=0&&i[n]>t;n--)i[n+1]=i[n];i[n+1]=t}return d}function xu(e,t){let n=e[0]<Xl?0:e[0],r=t[0]<Xl?0:t[0];return n===r?(e[1]<Xl?0:e[1])<(t[1]<Xl?0:t[1]):n<r}var Su=e=>e[0]<Xl&&e[1]<Xl;function Cu(e,t,n){if(!(n>0)||Su(t))return null;let r=n/Zl,i=0,a=-1,o=0,s=t;for(let t=1;t<=Zl;t++){let n=e(t*r);if(Su(n)){a=t*r;break}i=t*r,xu(n,s)&&(o=t*r,s=n)}if(a>0){for(let t=0;t<Ql;t++){let t=(i+a)/2;Su(e(t))?a=t:i=t}return a}let c=Math.max(0,o-r),l=Math.min(n,o+r);for(let t=0;t<Ql;t++){let t=c+(l-c)/3,n=l-(l-c)/3;xu(e(n),e(t))?c=t:l=n}let u=(c+l)/2,d=e(u);if(!xu(d,t))return null;if(Su(d)){let t=Math.max(0,o-r);for(let n=0;n<Ql;n++){let n=(t+u)/2;Su(e(n))?u=n:t=n}}return u}function wu(e,t,n){return Math.max(t,e-90*Math.max(0,n),0)}function Tu(e,t,n){return t.update(),{name:e,capsules:t.capsules.map(e=>({id:e.capsule.id,region:e.capsule.region,now:e.now})),channels:[],interaction:n}}var Eu=1e-12,Du=1e-6,Ou=.001;function ku(e){let t=String(e);return/[.e]/.test(t)?t:`${t}.0`}var Au=[`#define COLLIDE_MAX 16`,`#define COLLIDE_PASSES 2`,`#define COLLIDE_EPS ${ku(Eu)}`,`#define COLLIDE_MIN_D ${ku(Du)}`,`uniform vec4 collideA[ COLLIDE_MAX ];`,`uniform vec4 collideB[ COLLIDE_MAX ];`,`uniform vec4 collideBindA[ COLLIDE_MAX ];`,`uniform vec4 collideBindB[ COLLIDE_MAX ];`,`uniform int collideCount;`,`#ifdef COLLIDE_WEIGHT`,`attribute float _collide;`,`#endif`].join(`
`),ju=[`#ifdef COLLIDE_PARTNER`,`#define PARTNER_COLLIDE_MAX 8`,`#define COLLIDE_PARTNER_PUSH_MAX ${ku(Jl)}`,`uniform vec4 partnerA[ PARTNER_COLLIDE_MAX ];`,`uniform vec4 partnerB[ PARTNER_COLLIDE_MAX ];`,`uniform int partnerCount;`,`#endif`].join(`
`),Mu=`    for ( int i = 0; i < COLLIDE_MAX; i ++ ) {
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
`,Nu=`  for ( int it = 0; it < COLLIDE_PASSES; it ++ ) {
${Mu}  }
`,Pu=`
vec3 collidePush( vec3 p ) {
${Nu}  return p;
}
`,Fu={A:`collideA`,B:`collideB`,max:`COLLIDE_MAX`,count:`collideCount`,inS:`sIn`,r:`sr`},Iu={A:`partnerA`,B:`partnerB`,max:`PARTNER_COLLIDE_MAX`,count:`partnerCount`,inS:`pIn`,r:`pr`};function Lu(e,t,n,r,i=Fu){return[`float ax = ${i.A}[ i ].x;`,`float ay = ${i.A}[ i ].y;`,`float az = ${i.A}[ i ].z;`,`float abx = ${i.B}[ i ].x - ax;`,`float aby = ${i.B}[ i ].y - ay;`,`float abz = ${i.B}[ i ].z - az;`,`float apx = ${e} - ax;`,`float apy = ${t} - ay;`,`float apz = ${n} - az;`,`float len2 = abx * abx + aby * aby + abz * abz;`,`float t = len2 > COLLIDE_EPS ? clamp( ( apx * abx + apy * aby + apz * abz ) / len2, 0.0, 1.0 ) : 0.0;`,`float dx = apx - abx * t;`,`float dy = apy - aby * t;`,`float dz = apz - abz * t;`,`float d = sqrt( dx * dx + dy * dy + dz * dz );`].map(e=>r+e).join(`
`)}function Ru(e,t,n){return e.map(e=>`${t}for ( int i = 0; i < ${e.max}; i ++ ) {\n${t}  if ( i >= ${e.count} ) break;\n${n(e)}${t}}\n`).join(``)}var zu=`    float r = collideA[ i ].w;
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
${Lu(`p.x`,`p.y`,`p.z`,`    `)}
    sIn[ i ] = d < r ? 1.0 : 0.0;
    sCount += sIn[ i ];
`,Bu=`${Lu(`p.x`,`p.y`,`p.z`,`    `,Iu)}
    float depth = partnerA[ i ].w - d;
    float f = clamp( ( 1.5 * COLLIDE_PARTNER_PUSH_MAX - depth ) / ( 0.5 * COLLIDE_PARTNER_PUSH_MAX ), 0.0, 1.0 );
    float r = f > 0.0 ? d + depth * f : 0.0;
    pr[ i ] = r;
    pIn[ i ] = d < r ? 1.0 : 0.0;
    sCount += pIn[ i ];
`,Vu=`    for ( int i = 0; i < PARTNER_COLLIDE_MAX; i ++ ) {
      if ( i >= partnerCount ) break;
${Lu(`p.x`,`p.y`,`p.z`,`      `,Iu)}
      if ( d < pr[ i ] && d > COLLIDE_MIN_D ) {
        float k = pr[ i ] / d - 1.0;
        p.x += dx * k;
        p.y += dy * k;
        p.z += dz * k;
      }
    }
`;function Hu(e,t){return`
vec3 collidePush( vec3 p ) {
${e.map(e=>`  float ${e.r}[ ${e.max} ];\n  float ${e.inS}[ ${e.max} ];\n`).join(``)}  float sCount = 0.0;
${Ru(e,`  `,e=>e===Iu?Bu:zu)}  float sDone = sCount < 0.5 ? 1.0 : 0.0;
  float qx = p.x;
  float qy = p.y;
  float qz = p.z;
  for ( int k = 0; k < SQUEEZE_ROUNDS; k ++ ) {
    if ( sDone > 0.5 ) break;
    float fail = 0.0;
    if ( k == 0 && sCount < 1.5 ) {
${Ru(e,`      `,e=>`        if ( ${e.inS}[ i ] > 0.5 ) {
${Lu(`p.x`,`p.y`,`p.z`,`          `,e)}
          if ( d > COLLIDE_MIN_D ) {
            float kk = ${e.r}[ i ] / d - 1.0;
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
${Ru(e,`      `,e=>`        if ( ${e.inS}[ i ] > 0.5 ) {
${Lu(`p.x`,`p.y`,`p.z`,`          `,e)}
          if ( d > COLLIDE_MIN_D ) {
            nx += dx / d;
            ny += dy / d;
            nz += dz / d;
          }
          rMax = ${e.r}[ i ] > rMax ? ${e.r}[ i ] : rMax;
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
${Ru(e,`          `,e=>`            if ( ${e.inS}[ i ] > 0.5 ) {
${Lu(`ox`,`oy`,`oz`,`              `,e)}
              if ( d < ${e.r}[ i ] ) clear = 0.0;
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
${Ru(e,`    `,e=>`      if ( ${e.inS}[ i ] < 0.5 ) {
${Lu(`qx`,`qy`,`qz`,`        `,e)}
        if ( d < ${e.r}[ i ] ) {
          ${e.inS}[ i ] = 1.0;
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
${t}  }
  return p;
}
`}var Uu=Hu([Fu],Nu),Wu=Hu([Iu,Fu],`  for ( int it = 0; it < COLLIDE_PASSES; it ++ ) {
${Vu}${Mu}  }
`),Gu=`
#ifdef COLLIDE_WEIGHT
  transformed = mix( transformed, collidePush( transformed ), clamp( _collide, 0.0, 1.0 ) );
#else
  transformed = collidePush( transformed );
#endif
`;function Ku(e,t,n){let r=n[0]-t[0],i=n[1]-t[1],a=n[2]-t[2],o=e[0]-t[0],s=e[1]-t[1],c=e[2]-t[2],l=r*r+i*i+a*a,u=l>1e-12?Math.min(1,Math.max(0,(o*r+s*i+c*a)/l)):0;return Math.hypot(o-r*u,s-i*u,c-a*u)}function qu(e,t,n,r,i){let a=r.a[0],o=r.a[1],s=r.a[2],c=r.b[0]-a,l=r.b[1]-o,u=r.b[2]-s,d=e-a,f=t-o,p=n-s,m=c*c+l*l+u*u,h=m>1e-12?Math.min(1,Math.max(0,(d*c+f*l+p*u)/m)):0,g=d-c*h,_=f-l*h,v=p-u*h;return i[0]=g,i[1]=_,i[2]=v,i[3]=Math.sqrt(g*g+_*_+v*v),i}function Ju(e,t,n){let r=qu(e[0],e[1],e[2],t,n)[3],i=t.r-r,a=Math.min(1,Math.max(0,(1.5*Jl-i)/(.5*Jl)));return a>0?r+i*a:0}function Yu(e,t,n,r){let i=e[0],a=e[1],o=e[2];for(let e=0;e<2;e++){let e=!1;for(let s=0;s<r;s++){let{a:r,b:c}=t[s],l=n[s],u=c[0]-r[0],d=c[1]-r[1],f=c[2]-r[2],p=i-r[0],m=a-r[1],h=o-r[2],g=u*u+d*d+f*f,_=g>1e-12?Math.min(1,Math.max(0,(p*u+m*d+h*f)/g)):0,v=p-u*_,y=m-d*_,b=h-f*_,x=Math.sqrt(v*v+y*y+b*b);if(x<l&&x>1e-6){let t=l/x-1;i+=v*t,a+=y*t,o+=b*t,e=!0}}if(!e)break}return[i,a,o]}var Xu=new Float64Array(4),Zu=new Uint8Array(24),Qu=new Float64Array(16);function $u(e,t,n,r){let i=Xu,a=Zu.fill(0,0,r),o=0;for(let s=0;s<r;s++)qu(e[0],e[1],e[2],t[s],i)[3]<n[s]&&(a[s]=1,o++);if(!o)return[e[0],e[1],e[2]];let s=e[0],c=e[1],l=e[2];for(let u=0;u<3;u++){if(u===0&&o===1)for(let o=0;o<r;o++){if(!a[o])continue;let[r,u,d,f]=qu(e[0],e[1],e[2],t[o],i);if(f>1e-6){let t=n[o]/f-1;s=e[0]+r*t,c=e[1]+u*t,l=e[2]+d*t}}else{let o=0,u=0,d=0,f=0;for(let s=0;s<r;s++){if(!a[s])continue;let[r,c,l,p]=qu(e[0],e[1],e[2],t[s],i);p>1e-6&&(o+=r/p,u+=c/p,d+=l/p),f=n[s]>f?n[s]:f}let p=Math.sqrt(o*o+u*u+d*d);if(p<.001)return null;o/=p,u/=p,d/=p;let m=0,h=2*f;for(let s=0;s<=16;s++){let c=s===0?h:.5*(m+h),l=e[0]+o*c,f=e[1]+u*c,p=e[2]+d*c,g=!0;for(let e=0;e<r;e++)a[e]&&qu(l,f,p,t[e],i)[3]<n[e]&&(g=!1);if(s===0){if(!g)return null}else g?h=c:m=c}s=e[0]+o*h,c=e[1]+u*h,l=e[2]+d*h}let d=0;for(let e=0;e<r;e++)!a[e]&&qu(s,c,l,t[e],i)[3]<n[e]&&(a[e]=1,d++);if(o+=d,!d||u===2)break}return[s,c,l]}function ed(e,t,n=1,r,i){let a=Math.min(t.length,16),o=t,s=Qu,c=a;for(let e=0;e<a;e++){let n=t[e];Qu[e]=n.bind&&r?Math.min(n.r,Ku(r,n.bind.a,n.bind.b)):n.r}let l=i?.partners?.length?i.partners.slice(0,8):null;if(l){let n=new Float64Array(4);o=[...l,...t.slice(0,a)],s=[...l.map(t=>Ju(e,t,n)),...Array.from(Qu.subarray(0,a))],c=o.length}let[u,d,f]=(i?.squeeze?$u(e,o,s,c):null)??Yu(e,o,s,c),p=Math.min(1,Math.max(0,n));return[e[0]+(u-e[0])*p,e[1]+(d-e[1])*p,e[2]+(f-e[2])*p]}function td(e,t){return{a:Jo(t,e.a),b:Jo(t,e.b),r:e.r*Yo(t)}}function nd(e,t){if(!e)return Pu;let n=t?[`#ifdef COLLIDE_PARTNER`,Wu,`#else`,Uu,`#endif`]:[Uu];return[`#ifdef COLLIDE_SQUEEZE`,`#define SQUEEZE_ROUNDS 3`,`#define SQUEEZE_STEPS 16`,`#define SQUEEZE_MIN_N ${ku(Ou)}`,...n,`#else`,Pu,`#endif`].join(`
`)}function rd(e,t=!1,n=!1){if(e.includes(`collidePush(`)||!e.includes(`#include <common>`)||!e.includes(`#include <skinning_vertex>`))return e;let r=t&&n,i=r?`${Au}\n${ju}`:Au;return e.replace(`#include <common>`,`#include <common>\n${i}\n${nd(t,r)}`).replace(`#include <skinning_vertex>`,`#include <skinning_vertex>\n${Gu}`)}function id(e){let t=e;for(;t&&!Ho(t);)t=t.parent;if(!t)return null;let n=t.userData.garment;if(n&&typeof n.kind==`string`&&n.kind)return n.kind;let r=/^garment_([^_]+)_/.exec(t.name);return r?r[1]:``}var ad=[`torso`,`arm`,`head`,`shoulder_hair`,`chest_hair`],od=[`arm`,...Go,...Ko];function sd(e,t){return e===`footwear`?[]:e===`hair`?t.filter(e=>ad.includes(e.capsule.region)).slice(0,16):t.filter(e=>!od.includes(e.capsule.region)).slice(0,16)}function cd(e){let t=[],n=[{capsule:{region:`torso`}}];return e.traverse(e=>{let r=e;if(!r.isSkinnedMesh)return;let i=id(r);i!==null&&sd(i,n).length&&t.push(r)}),t}function ld(e){let t=e.geometry.getAttribute(`position`),n=[1/0,1/0,1/0],r=[-1/0,-1/0,-1/0];for(let e=0;e<t.count;e++){let i=t.getX(e),a=t.getY(e),o=t.getZ(e);n=[Math.min(n[0],i),Math.min(n[1],a),Math.min(n[2],o)],r=[Math.max(r[0],i),Math.max(r[1],a),Math.max(r[2],o)]}let i=t.count?[(n[0]+r[0])/2,(n[1]+r[1])/2,(n[2]+r[2])/2]:[0,0,0],a=0;for(let e=0;e<t.count;e++)a=Math.max(a,Math.hypot(t.getX(e)-i[0],t.getY(e)-i[1],t.getZ(e)-i[2]));let o=e.geometry.getAttribute(`skinIndex`),s=e.geometry.getAttribute(`skinWeight`),c=new Map;if(o&&s)for(let e=0;e<o.count;e++)for(let t=0;t<4;t++){let n=o.getComponent(e,t),r=s.getComponent(e,t);r>0&&c.set(n,(c.get(n)??0)+r)}let l=0,u=-1;for(let[e,t]of[...c.entries()].sort((e,t)=>e[0]-t[0]))t>u&&(l=e,u=t);return{c:i,r:a,joint:l}}function ud(e,t){let n=e.skeleton?.bones??[],r=t.joint<n.length?t.joint:-1,i=r>=0?Xo(e.matrixWorld.elements,e.bindMatrixInverse.elements,n[r].matrixWorld.elements,e.skeleton.boneInverses[r].elements,e.bindMatrix.elements).bindToWorld:e.matrixWorld.elements;return{c:Jo(i,t.c),r:t.r*Yo(i)}}function dd(e,t,n){let r=cd(t);if(!r.length)return null;let i=es(e,t,n);if(!i)return null;let a=e.Material.prototype.customProgramCacheKey,o=(e,t,n,r,i,o=e)=>{let s=o.onBeforeCompile,c=o.customProgramCacheKey,l=c===a?s.toString():null;return e.onBeforeCompile=(e,r)=>{s.call(o,e,r),e.uniforms.collideA=t.collideA,e.uniforms.collideB=t.collideB,e.uniforms.collideBindA=t.collideBindA,e.uniforms.collideBindB=t.collideBindB,e.uniforms.collideCount=t.collideCount,n&&(e.uniforms.partnerA=n.partnerA,e.uniforms.partnerB=n.partnerB,e.uniforms.partnerCount=n.partnerCount),e.vertexShader=rd(e.vertexShader,i,!!n)},e.customProgramCacheKey=()=>`${l??c.call(o)}|collide${r?`W`:``}${i?`S`:``}`,r&&(e.defines={...e.defines??{},COLLIDE_WEIGHT:``}),i&&(e.defines={...e.defines??{},COLLIDE_SQUEEZE:``}),n&&(e.defines={...e.defines??{},COLLIDE_PARTNER:``}),e.needsUpdate=!0,e},s=[],c=-1,l=[],u=(e,t)=>{let n=e.partner;if(!n)return;let{mesh:r}=e.entry,i=ud(r,n.bindSphere);e.entry.sphere=i;let a=l.length?au(i,l,8):[];e.entry.partners=a.map(e=>td(l[e],t)),e.entry.partners.forEach((e,t)=>{n.uniforms.partnerA.value[t].set(e.a[0],e.a[1],e.a[2],e.r),n.uniforms.partnerB.value[t].set(e.b[0],e.b[1],e.b[2],0)}),n.uniforms.partnerCount.value=e.entry.partners.length},d=t=>{let{mesh:n,capsules:r}=t.entry,i=new e.Matrix4().copy(n.matrixWorld).invert().elements;t.entry.local=r.map((e,n)=>{let r=td(e.now,i);return r.bind=t.binds[n],r}),t.entry.local.forEach((e,n)=>{t.uniforms.collideA.value[n].set(e.a[0],e.a[1],e.a[2],e.r),t.uniforms.collideB.value[n].set(e.b[0],e.b[1],e.b[2],0);let r=e.bind??e;t.uniforms.collideBindA.value[n].set(r.a[0],r.a[1],r.a[2],0),t.uniforms.collideBindB.value[n].set(r.b[0],r.b[1],r.b[2],0)}),t.uniforms.collideCount.value=t.entry.local.length,u(t,i)},f=(e,t)=>{e.frame!==t&&(e.frame=t,c!==t&&(c=t,i.update()),d(e))};for(let t of r){let n=id(t),r=sd(n,i.capsules);if(!r.length)continue;let a=new e.Matrix4().copy(t.bindMatrix).invert().elements,c=r.map(e=>td(e.bind,a)),l={collideA:{value:Array.from({length:16},()=>new e.Vector4)},collideB:{value:Array.from({length:16},()=>new e.Vector4)},collideBindA:{value:Array.from({length:16},()=>new e.Vector4(0,0,0,-1))},collideBindB:{value:Array.from({length:16},()=>new e.Vector4)},collideCount:{value:0}},u=!!t.geometry?.getAttribute(`_collide`),p=n===`hair`,m=n===`hair`?{uniforms:{partnerA:{value:Array.from({length:8},()=>new e.Vector4)},partnerB:{value:Array.from({length:8},()=>new e.Vector4)},partnerCount:{value:0}},bindSphere:ld(t)}:null,h=t.material,g=[],_=e=>{let t=o(e.clone(),l,m?.uniforms??null,u,p,e);return g.push(t),t};t.material=Array.isArray(h)?h.map(_):_(h);let v=new e.MeshDepthMaterial({depthPacking:e.RGBADepthPacking}),y=new e.MeshDistanceMaterial,b=(Array.isArray(t.material)?t.material:[t.material]).find(e=>e.alphaTest>0);if(b)for(let e of[v,y])e.map=b.map??null,e.alphaTest=b.alphaTest;let x=o(v,l,m?.uniforms??null,u,p),S=o(y,l,m?.uniforms??null,u,p);g.push(x,S);let C={entry:{mesh:t,kind:n,capsules:r,local:[],sphere:null,partners:[]},binds:c,uniforms:l,partner:m,original:h,owned:g,depth:t.customDepthMaterial,distance:t.customDistanceMaterial,ownHooks:{render:Object.prototype.hasOwnProperty.call(t,`onBeforeRender`),shadow:Object.prototype.hasOwnProperty.call(t,`onBeforeShadow`)},beforeRender:t.onBeforeRender,beforeShadow:t.onBeforeShadow,frame:-1,patched:{material:t.material,depth:x,distance:S},excluded:!1};t.customDepthMaterial=x,t.customDistanceMaterial=S;let w=C.beforeRender,T=C.beforeShadow;t.onBeforeRender=function(e,t,n,r,i,a){C.excluded||f(C,e.info.render.frame),w.call(this,e,t,n,r,i,a)},t.onBeforeShadow=function(e,t,n,r,i,a,o){C.excluded||f(C,e.info.render.frame),T.call(this,e,t,n,r,i,a,o)},d(C),s.push(C)}return s.length?{binding:i,get entries(){return s.map(e=>e.entry)},update(){i.update();for(let e of s)d(e)},excludeMesh(e,t){let n=s.find(t=>t.entry.mesh===e);!n||n.excluded===t||(n.excluded=t,e.material=t?n.original:n.patched.material,e.customDepthMaterial=t?n.depth:n.patched.depth,e.customDistanceMaterial=t?n.distance:n.patched.distance,t||(n.frame=-1))},setPartners(e){l=e?.length?[...e]:[];for(let e of s)e.partner&&(e.frame=-1)},dispose(){for(let e of s){let{mesh:t}=e.entry;t.material=e.original,t.customDepthMaterial=e.depth,t.customDistanceMaterial=e.distance,e.ownHooks.render?t.onBeforeRender=e.beforeRender:delete t.onBeforeRender,e.ownHooks.shadow?t.onBeforeShadow=e.beforeShadow:delete t.onBeforeShadow;for(let t of e.owned)t.dispose()}s.length=0,l=[]}}:null}var fd=12,pd=14,md=1e-6,hd={squeeze:!0},gd=[`chest`,`attached_part`,`appendage`];function _d(e,t,n){let r=n/fd,i=0,a=-1,o=0,s=t;for(let t=1;t<=fd;t++){let n=e(t*r);if(n<md){a=t*r;break}i=t*r,n<s&&(o=t*r,s=n)}let c;if(a>0){for(let t=0;t<pd;t++){let t=(i+a)/2;e(t)<md?a=t:i=t}c=a}else{let i=Math.max(0,o-r),a=Math.min(n,o+r);for(let t=0;t<pd;t++){let t=i+(a-i)/3,n=a-(a-i)/3;e(t)<=e(n)?a=n:i=t}c=(i+a)/2;let s=e(c);if(!(s<t))return null;if(s<md){let t=Math.max(0,o-r);for(let n=0;n<pd;n++){let n=(t+c)/2;e(n)<md?c=n:t=n}}}return c}function vd(e,t){return e.filter(e=>!t.has(Z(e.capsule.a))&&!Go.includes(e.capsule.region??``)&&!Ko.includes(e.capsule.region??``))}function yd(e){return e.filter(e=>ad.includes(e.capsule.region??``))}var bd=new WeakMap;function xd(e){if(!e)return e;let t=bd.get(e);if(!t){let n={};for(let[t,r]of Object.entries(e.groups??{}))r.hair||(n[t]=r);t={...e,rev:`${e.rev}:strands`,groups:n},bd.set(e,t)}return t}function Sd(e,t){return t.map(t=>{if(!(t.r>0))return 1;let n=t.b[0]-t.a[0],r=t.b[1]-t.a[1],i=t.b[2]-t.a[2],a=e[0]-t.a[0],o=e[1]-t.a[1],s=e[2]-t.a[2],c=n*n+r*r+i*i,l=c>1e-12?Math.min(1,Math.max(0,(a*n+o*r+s*i)/c)):0;return Math.min(1,Math.hypot(a-n*l,o-r*l,s-i*l)/t.r)})}function Cd(e,t,n,r,i,a,o){let s=2*Math.PI*i.freq_hz,c=(o?.x??e.clone()).copy(e).sub(n),l=(o?.w??t.clone()).copy(t).sub(r),u=i.zeta*s,d,f,p,m;if(s*s<1e-12)d=m=1,f=a,p=0;else if(i.zeta>1){let e=i.zeta+Math.sqrt(i.zeta*i.zeta-1),t=-s/e,n=-s*e,r=Math.exp(t*a),o=Math.exp(n*a),c=t-n;d=(t*o-n*r)/c,f=(r-o)/c,p=s*s*(o-r)/c,m=(t*r-n*o)/c}else{let e=s*Math.sqrt(1-i.zeta*i.zeta),t=Math.exp(-u*a),n=Math.cos(e*a),r=e===0?a:Math.sin(e*a)/e;d=t*(n+u*r),f=t*r,p=-s*s*f,m=t*(n-u*r)}let h=o??{p:n.clone(),v:r.clone()};return h.p.copy(n).addScaledVector(r,a).addScaledVector(c,d).addScaledVector(l,f),h.v.copy(r).addScaledVector(c,p).addScaledVector(l,m),h}var wd=.1,Td=3,Ed=1.6,Dd=[1,1,1],Od=[`gravity`,`freq_hz`,`zeta`,`gain`,`flatten`,`stretch`,`spread`,`flatten_floor`,`spill`,`translate`,`head_sag`,`length`,`girth`];function kd(e,t,n,r){let i=Math.max(0,Math.min(1,n/1.5)),a=i*i*(3-2*i),o=r??{...t};for(let n of Od){let r=n===`head_sag`||n===`length`||n===`girth`?1:n===`flatten_floor`?t.squash[0]:n===`spread`?.5:0;o[n]=(e[n]??r)+((t[n]??r)-(e[n]??r))*a}return o}var Ad=new WeakMap,jd=.5,Md=(e,t,n)=>Math.max(t,Math.min(n,e)),Nd=(e,t)=>{if(t<=0)return 0;let n=t/2;return e<=n?e:n+n*Math.tanh((e-n)/n)},Pd=(e,t)=>{let n=t>0?Md(Math.abs(e)*180/Math.PI/t,0,1):0;return n*n*(3-2*n)},Fd=e=>Md(e.rest_deg,-e.rest_max_deg,e.rest_max_deg)*Math.PI/180;function Id(e,t,n,r){let i=e=>[...e.bones,...Object.keys(e.anchor_blend??{})].map(Z),a=new Set(Object.values(n?.groups??{}).flatMap(i)),o=!1;if(a.size&&t.traverse(e=>{e.isBone&&a.has(Z(e.name))&&(o=!0)}),!o){let n,a=!1,o;return{configure(s){if(a)return;if(n){n.configure(s);return}let c=new Set(Object.values(s?.groups??{}).flatMap(i)),l=!1;c.size&&t.traverse(e=>{e.isBone&&c.has(Z(e.name))&&(l=!0)}),l&&(n=Id(e,t,s,r),o&&n.setCollision(o))},update(e,t){n?.update(e,t)},setCollision(e){a||(o=e,n?.setCollision(e))},contactTips(){return n?.contactTips()??[]},channelOccupants(){return n?.channelOccupants()??[]},opChains(){return n?.opChains()??[]},bendChain(e,t){n?.bendChain(e,t)},reach(){return n?.reach()??0},reset(){n?.reset()},dispose(){n?.dispose(),a=!0}}}t.updateWorldMatrix(!0,!1),t.updateMatrixWorld(!0);let s=new e.Vector3(0,-9.81,0),c=new Map,l=new Map,u=new Map,d=new e.Vector3(0,1,0),f=r&&Ad.get(r);t.traverse(t=>{let n=t;if(!n.isSkinnedMesh)return;let r=n.geometry.getAttribute(`position`),i=n.geometry.getAttribute(`skinIndex`),a=n.geometry.getAttribute(`skinWeight`);if(!r||!i||!a)return;let o=!Uo(n);if(n.skeleton.bones.forEach((t,r)=>{if(o&&!l.has(t)&&n.skeleton.boneInverses[r]&&l.set(t,n.skeleton.boneInverses[r]),!c.has(t)){let n=t.getWorldQuaternion(new e.Quaternion).invert(),r=0;for(let e=t.parent;e;e=e.parent)r++;c.set(t,{bone:t,local:t.matrix.clone(),centroid:new e.Vector3,mass:0,reach:new e.Vector3,scaleAxis:new e.Vector3,centroidWorld:new e.Vector3,gravityRest:s.clone().applyQuaternion(n),gravityProjection:0,bodyFront:new e.Vector3,head:t.getWorldPosition(new e.Vector3),parentHead:t.parent.getWorldPosition(new e.Vector3),worldRotation:n.clone().invert(),pureWorld:new e.Matrix4,singleLateral:new e.Vector3,centeringRotation:new e.Quaternion,lateral:new e.Vector3,pairedLateral:new e.Vector3,auto:t.matrixAutoUpdate,depth:r,rotation:new e.Quaternion,straightenRotation:new e.Quaternion,localRotation:t.quaternion.clone(),bindWorldInverse:t.matrixWorld.clone().invert()})}}),f)return;let d=n.skeleton.boneInverses.map(e=>e.clone().multiply(n.bindMatrix)),p=new e.Vector3;for(let t=0;t<r.count;t++)for(let o=0;o<4;o++){let s=a.getComponent(t,o),c=i.getComponent(t,o),l=n.skeleton.bones[c];if(s<=0||!l)continue;let f=u.get(l)??{sum:new e.Vector3,weight:0};p.fromBufferAttribute(r,t).applyMatrix4(d[c]),f.sum.addScaledVector(p,s),f.weight+=s,u.set(l,f)}});for(let[e,t]of u)t.weight>0&&(c.get(e).centroid.copy(t.sum).divideScalar(t.weight),c.get(e).mass=t.weight);if(!f){let n=new Map;t.traverse(t=>{let r=t;if(!r.isSkinnedMesh)return;let i=r.geometry.getAttribute(`position`),a=r.geometry.getAttribute(`skinIndex`),o=r.geometry.getAttribute(`skinWeight`);if(!i||!a||!o)return;let s=r.skeleton.boneInverses.map(e=>e.clone().multiply(r.bindMatrix)),l=new e.Vector3;for(let e=0;e<i.count;e++)for(let t=0;t<4;t++){if(o.getComponent(e,t)<=jd)continue;let u=a.getComponent(e,t),d=c.get(r.skeleton.bones[u]);if(!d||d.mass<=0)continue;l.fromBufferAttribute(i,e).applyMatrix4(s[u]);let f=l.dot(d.centroid);f>(n.get(d.bone)??-1/0)&&(n.set(d.bone,f),d.reach.copy(l))}})}f?[...c.values()].forEach((e,t)=>{e.centroid.copy(f[t].centroid),e.mass=f[t].mass,e.reach.copy(f[t].reach)}):r&&Ad.set(r,[...c.values()].map(e=>({centroid:e.centroid.clone(),mass:e.mass,reach:e.reach.clone()})));for(let e of c.values())e.centroidWorld.copy(e.centroid).applyMatrix4(e.bone.matrixWorld),e.gravityProjection=s.dot(e.centroidWorld.clone().sub(e.head).normalize())/9.81;let p=new Map;t.traverse(t=>{t.isBone&&p.set(t,t.getWorldPosition(new e.Vector3))});let m=new Map([...c.values()].map(e=>[Z(e.bone.name),e])),h=(e,t)=>{if(!t||typeof t!=`object`)return;let n=Object.entries(t).map(([e,t])=>({bind:m.get(Z(e)),share:Number(t)})).filter(t=>!!t.bind&&t.bind!==e&&Number.isFinite(t.share)&&t.share>0),r=n.reduce((e,t)=>e+t.share,0);return r>0?n.map(e=>({bind:e.bind,share:e.share/r})):void 0};for(let e of c.values()){let t=h(e,e.bone.userData?.anchor_blend);t&&(e.anchorBlend=t)}let g=[],_=[],v=[],y=!1,b=!1,x,S=null,C=()=>{for(let e of g){let t=Z(e.bind.bone.name),n=x?.version===8?x.capsules?.find(e=>gd.includes(e.region)&&Z(e.a)===t):void 0;e.linkR=n&&n.r>0?n.r:0,e.linkSurfaceR=e.linkR>0?Math.max(e.linkR,n?.r_surface??0):0}if(!x||!g.length){S=null;for(let e of g)e.contacts=[];return}S??=es(e,t,x);let n=new e.Vector3;for(let t of g){t.contacts=[];let r=Math.max(t.paramsTo.max_deg??0,t.paramsTo.sag_max_deg??0);if(!S||!(r>0))continue;let i=t.paramsTo.hair?yd(S.capsules):vd(S.capsules,t.ancestors),a=l.get(t.bind.bone),o=i.map(()=>1);a&&(n.copy(t.tipLocal).applyMatrix4(new e.Matrix4().copy(a).invert()),o=Sd([n.x,n.y,n.z],i.map(e=>e.bind))),t.contacts=i.map((e,t)=>({bound:e,factor:o[t]}))}g.some(e=>e.contacts.length)||(S=null)},w=e=>{e.bone.matrix.copy(e.local),e.bone.matrixAutoUpdate=e.auto,e.bone.matrixWorldNeedsUpdate=!0},T=t=>{if(b)return;let n=new Map(g.map(e=>[e.bind.bone,e])),r=new Set,i=new Set(Object.values(t?.groups??{}).flatMap(e=>e.bones.map(Z))),a=[],o=[],s=[],l=new Map;for(let e of v)e.todayBlend=void 0;for(let u of Object.values(t?.groups??{})){let t=u.bones.map(e=>m.get(Z(e)));if(t.some(e=>!e||e.centroid.lengthSq()<1e-12))continue;let f=new Set(t.map(e=>e.bone)),g=t.filter(e=>!f.has(e.bone.parent));if(u.hair&&u.anchor_blend){let e=Z(u.anchor_from??``);for(let[t,n]of Object.entries(u.anchor_blend)){let r=m.get(Z(t));!r||s.includes(r)||(r.todayBlend=h(r,n),r.todayBlend&&(r.swingShare=r.todayBlend.filter(t=>Z(t.bind.bone.name)===e).reduce((e,t)=>e+t.share,0),s.push(r)))}}if(!t.length)continue;for(let e of t){let n=t.find(t=>t.bone.parent===e.bone);n?e.scaleAxis.setFromMatrixPosition(n.local):u.scale_axis===`bone`?e.scaleAxis.set(0,1,0):e.scaleAxis.copy(e.centroid),e.scaleAxis.lengthSq()<1e-12&&e.scaleAxis.copy(e.centroid),e.scaleAxis.normalize()}let _=new e.Vector3,v=new e.Vector3,y=new e.Vector3;for(let e of g)_.add(e.head),v.add(e.parentHead);_.divideScalar(g.length),v.divideScalar(g.length);for(let e of t)y.add(e.centroidWorld);y.divideScalar(t.length);let b=_.clone().sub(v);if(b.addScaledVector(d,-b.dot(d)),b.lengthSq()<1e-10&&(b.copy(y).sub(_),b.addScaledVector(d,-b.dot(d))),b.normalize(),g.length===1){let t=g[0].bone.parent.children.filter(e=>e.isBone&&e!==g[0].bone&&!i.has(Z(e.name))),n=e=>e.addScaledVector(d,-e.dot(d)),r=0,a=0,o=new e.Vector3;for(let e=0;e<t.length;e++){let i=p.get(t[e]);r=Math.max(r,n(i.clone().sub(g[0].parentHead)).length());for(let r=0;r<e;r++){let e=n(i.clone().sub(p.get(t[r]))),s=e.length();s>a&&(a=s,o.copy(e))}}if(a>1e-4&&a>=.25*r){let e=d.clone().cross(o.normalize()).normalize(),t=n(y.clone().sub(g[0].parentHead)),r=t.length()<1e-6?b:t.normalize(),i=e.dot(r);Math.abs(i)>=1e-6&&b.copy(i>0?e:e.negate())}}for(let e of t){e.bodyFront.copy(b),e.bodyFront.lengthSq()<1e-10&&e.bodyFront.set(0,0,1),e.bodyFront.applyQuaternion(e.worldRotation.clone().invert());let n=e;for(let t=e.bone.parent;t&&f.has(t);t=t.parent)n=c.get(t);if(e.pairedLateral.set(0,0,0),g.length>=2&&(e.pairedLateral.copy(n.head).sub(_),e.pairedLateral.addScaledVector(d,-e.pairedLateral.dot(d)).normalize(),e.pairedLateral.applyQuaternion(e.worldRotation.clone().invert())),e.straightenRotation.identity(),!g.includes(e)){let n=c.get(e.bone.parent),r=t.find(t=>t.bone.parent===e.bone),i=r?r.head.clone().sub(e.head):e.centroidWorld.clone().sub(e.head),a=e.head.clone().sub(n.head);if(i.lengthSq()>1e-12&&a.lengthSq()>1e-12){let t=e.worldRotation.clone().invert();e.straightenRotation.setFromUnitVectors(i.normalize().applyQuaternion(t),a.normalize().applyQuaternion(t))}}if(e.lateral.set(0,0,0),!g.includes(e))continue;let r=t.find(t=>t.bone.parent===e.bone),i=r?r.head.clone().sub(e.head):e.centroidWorld.clone().sub(e.head);i.normalize();let a=b.clone().addScaledVector(i,-b.dot(i));if(a.lengthSq()<1e-10&&a.copy(d).addScaledVector(i,-d.dot(i)),e.lateral.crossVectors(i,a).normalize().applyQuaternion(e.worldRotation.clone().invert()),g.length===1){let t=e.worldRotation.clone().invert(),n=b.clone().cross(d).normalize();n.dot(i.clone().cross(a))<0&&n.negate();let r=i.clone().addScaledVector(n,-i.dot(n));e.singleLateral.copy(n).applyQuaternion(t),e.centeringRotation.identity(),r.lengthSq()>1e-12&&e.centeringRotation.setFromUnitVectors(i.clone().applyQuaternion(t),r.normalize().applyQuaternion(t))}}let x=Math.max(0,Math.floor(u.rigid_tail??0)),S=e=>{let n=t.find(t=>t.bone.parent===e.bone);return n?1+S(n):0};for(let i of t){if(r.has(i.bone))continue;if(x>0&&!g.includes(i)&&S(i)<x){r.add(i.bone),i.bone.matrixAutoUpdate=!1,o.push(i);continue}r.add(i.bone);let s=Fd(u),d=n.get(i.bone)??{bind:i,roots:g,motionShare:1,params:u,paramsFrom:u,paramsTo:u,paramsBlend:1.5,p:null,v:new e.Vector3,target:null,anchorRotation:null,rest:s,restFrom:s,restTo:s,blend:1.5,straighten:Pd(s,u.straighten_deg??0),straightenFrom:Pd(s,u.straighten_deg??0),straightenRestFrom:Math.abs(s),straightenBlend:1.5,straightenThreshold:u.straighten_deg??0,staticFrequency:u.freq_hz,staticFrequencyFrom:u.freq_hz,staticFrequencyTo:u.freq_hz,staticWeight:(2*Math.PI*u.freq_hz)**2<1e-12?0:1,staticWeightFrom:(2*Math.PI*u.freq_hz)**2<1e-12?0:1,staticWeightTo:(2*Math.PI*u.freq_hz)**2<1e-12?0:1,tipLocal:new e.Vector3,ancestors:new Set,contacts:[],chainRoot:null,chainLinks:[],partnerFrame:0,partnerNearKeys:[],partnerNearNows:[],partnerPushed:[],partnerDeg:0,partnerAxis:null,linkR:0,linkSurfaceR:0,channels:null};d.restTo!==s&&(d.restFrom=d.rest,d.restTo=s,d.blend=0),d.straightenThreshold!==(u.straighten_deg??0)&&(d.straightenFrom=d.straighten,d.straightenRestFrom=Math.abs(d.rest),d.straightenThreshold=u.straighten_deg??0,d.straightenBlend=0),d.roots=g;let p=t.find(e=>e.bone.parent===i.bone);p?d.tipLocal.setFromMatrixPosition(p.local):i.reach.lengthSq()>1e-12?d.tipLocal.copy(i.reach):d.tipLocal.copy(i.centroid).multiplyScalar(2);let m=i;for(let e=i.bone.parent;e&&f.has(e);e=e.parent)m=c.get(e);l.set(d,m),d.ancestors.clear();for(let e=m.bone.parent;e;e=e.parent)e.isBone&&d.ancestors.add(Z(e.name));for(let e of[m.anchorBlend,i.anchorBlend])for(let t of e??[])d.ancestors.add(Z(t.bind.bone.name));if(m.bone.traverse(e=>{e.isBone&&d.ancestors.add(Z(e.name))}),Od.some(e=>d.paramsTo[e]!==u[e])){d.paramsFrom={...d.params};let e=(2*Math.PI*u.freq_hz)**2<1e-12;d.staticFrequencyTo=e?d.staticFrequency:u.freq_hz,d.staticFrequencyFrom=d.staticWeight===0?d.staticFrequencyTo:d.staticFrequency,d.staticWeightFrom=d.staticWeight,d.staticWeightTo=+!e,d.paramsBlend=0}d.paramsTo={...u,bones:[...u.bones],squash:[...u.squash]},d.params=kd(d.paramsFrom,d.paramsTo,d.paramsBlend),i.bone.matrixAutoUpdate=!1,a.push(d)}}for(let t of a.filter(e=>e.roots.includes(e.bind))){let n=a.filter(e=>{if(e.roots!==t.roots)return!1;for(let n=e.bind.bone;n;n=n.parent)if(n===t.bind.bone)return!0;return!1}).sort((e,t)=>e.bind.depth-t.bind.depth),r=n.map((e,t)=>t+1<n.length?e.bind.head.distanceTo(n[t+1].bind.head):2*e.bind.centroidWorld.distanceTo(e.bind.head)),i=0,o=0;for(let e=n.length-1;e>=0;e--)i+=r[e],n[e].motionShare=i*i*r[e],o+=n[e].motionShare;for(let t of n)t.chain=n,t.motionShare=n.length===1?1:o>0?t.motionShare/o:1/n.length,n.length>=2&&(t.sag??={frame:new e.Matrix4,rotation:new e.Quaternion,head:new e.Vector3,centre:new e.Vector3,force:new e.Vector3,torque:new e.Vector3,weight:0,q:new e.Quaternion})}for(let e of s)r.has(e.bone)||(r.add(e.bone),e.bone.matrixAutoUpdate=!1);for(let e of[...g.map(e=>e.bind),..._,...v])r.has(e.bone)||(w(e),e.bone.updateWorldMatrix(!1,!0));_=o.sort((e,t)=>e.depth-t.depth),v=s.sort((e,t)=>e.depth-t.depth);let u=new Set(a.map(e=>e.bind.bone)),f=e=>{let t=0;for(let n=e.bind.bone.parent;n;n=n.parent)u.has(n)&&t++;return t};g=a.sort((e,t)=>f(e)-f(t));let y=new Map(g.map(e=>[e.bind,e]));for(let e of g)e.chainLinks=[],e.partnerFrame=0,e.partnerNearKeys=[],e.partnerNearNows=[];for(let e of g)e.chainRoot=y.get(l.get(e)??e.bind)??e,e.chainRoot.chainLinks.push(e),e.hangJoint=void 0;for(let e of g)e.chainRoot!==e&&(e.channels=null);C()},E=()=>{for(let e of g)e.p=null,e.target=null,e.anchorRotation=null,e.v.set(0,0,0),e.partnerDeg=0,e.partnerPushed=[],e.channels=null;D=0,k=0},D=0,O=!1,k=0,ee=(e,t)=>{let n=e.bind.bone.parent?.matrixWorld.getMaxScaleOnAxis()??1,r=0;for(let n of e.chainLinks)r+=n.tipLocal.length()*Math.max(0,n.params.length??1)*(t?Math.max(1,n.params.squash[1]):1);return r*n},A=new e.Vector3,te=new e.Vector3,j=new e.Quaternion,M=new e.Matrix4,N=new e.Matrix4,ne=new e.Matrix4,P=new e.Matrix4,re=new e.Matrix4,ie=new e.Matrix4,ae=new e.Matrix4,oe=new e.Matrix4,F=new e.Quaternion,I=new e.Quaternion,L=new e.Quaternion,R=new e.Quaternion,z=new e.Vector3,se=new e.Vector3,B=new e.Vector3,ce=new e.Vector3,le=new e.Vector3,ue=new e.Vector3,de=new e.Vector3,fe=new e.Vector3,pe=new e.Vector3,V=new e.Vector3,H=new e.Vector3,me=new e.Vector3,he=new e.Vector3,ge=new e.Vector3,_e=new e.Vector3,ve=new e.Vector3,ye=new e.Vector3,U=new e.Vector3,be=new e.Matrix4,xe=new e.Vector3,Se=new e.Vector3,W=new e.Vector3,Ce=new e.Vector3,G=new e.Quaternion,K=new e.Vector3,we={p:new e.Vector3,v:new e.Vector3,x:new e.Vector3,w:new e.Vector3},Te=new e.Quaternion,Ee=new e.Vector3,De=new e.Vector3,Oe=new Map,ke=new e.Matrix4,Ae=new e.Matrix4,je=new e.Matrix4,Me=new e.Matrix4,Ne=0,Pe=new e.Quaternion,Fe=new e.Quaternion,Ie=new e.Quaternion,Le=new e.Vector3,Re=new e.Vector3,ze=new e.Vector3,Be=new e.Matrix4,Ve=new e.Matrix4,He=new e.Quaternion,Ue=new e.Vector3,q=new e.Vector3,We=new e.Vector3,J=new e.Vector3,Ge=(e,t,n,r)=>{if(!(r>0))return;let i=e.contacts.map(({bound:e,factor:t})=>({a:e.now.a,b:e.now.b,r:e.now.r*t}));Be.makeRotationFromQuaternion(He.copy(t).multiply(n)).premultiply(be).multiply(ae),Ue.copy(e.tipLocal).applyMatrix4(Be),q.copy(Ue).applyMatrix4(P);let a=ed([q.x,q.y,q.z],i),o=Math.hypot(a[0]-q.x,a[1]-q.y,a[2]-q.z);if(o<md||(Ve.copy(P).invert(),We.copy(Ue).sub(ye),J.set(a[0],a[1],a[2]).applyMatrix4(Ve).sub(Ue),J.crossVectors(We,J),J.lengthSq()<1e-20||We.lengthSq()<1e-12))return;J.normalize();let s=_d(e=>{q.copy(We).applyAxisAngle(J,e).add(ye).applyMatrix4(P);let t=ed([q.x,q.y,q.z],i);return Math.hypot(t[0]-q.x,t[1]-q.y,t[2]-q.z)},o,r);s!==null&&t.premultiply(He.setFromAxisAngle(J,s))},Ke=(e,t,n)=>{if(!(n>0))return;let r=e.contacts.map(({bound:e,factor:t})=>({a:e.now.a,b:e.now.b,r:e.now.r*t}));B.setFromMatrixPosition(t),q.copy(e.tipLocal).applyMatrix4(t);let i=ed([q.x,q.y,q.z],r,1,void 0,hd),a=Math.hypot(i[0]-q.x,i[1]-q.y,i[2]-q.z);if(a<md||(We.copy(q).sub(B),J.set(i[0],i[1],i[2]).sub(q),J.crossVectors(We,J),J.lengthSq()<1e-20||We.lengthSq()<1e-12))return;J.normalize();let o=_d(e=>{q.copy(We).applyAxisAngle(J,e).add(B);let t=ed([q.x,q.y,q.z],r,1,void 0,hd);return Math.hypot(t[0]-q.x,t[1]-q.y,t[2]-q.z)},a,n);o!==null&&(oe.makeRotationAxis(J,o),t.premultiply(be.makeTranslation(-B.x,-B.y,-B.z)).premultiply(oe).premultiply(be.makeTranslation(B.x,B.y,B.z)))},qe={hair:cu(),extension:cu()},Je=0,Ye=e=>{Je++,_u(qe.hair,`hair`,e),_u(qe.extension,`extension`,e)},Xe={hair:{frame:0,centre:[0,0,0],radius:-1,list:cu()},extension:{frame:0,centre:[0,0,0],radius:-1,list:cu()}},Ze=e=>{let t=Xe[e];if(t.frame===Je)return t;t.frame=Je;let n=t.centre,r=0;n[0]=0,n[1]=0,n[2]=0;for(let t of g){if(t.chainRoot!==t||(t.paramsTo.hair?`hair`:`extension`)!==e)continue;let i=t.bind.bone.matrixWorld.elements;n[0]+=i[12],n[1]+=i[13],n[2]+=i[14],r++}if(r<Td)return t.radius=-1,t.list.n=0,t;n[0]/=r,n[1]/=r,n[2]/=r;let i=0;for(let t of g){if(t.chainRoot!==t||(t.paramsTo.hair?`hair`:`extension`)!==e)continue;let r=t.bind.bone.matrixWorld.elements;i=Math.max(i,Math.hypot(r[12]-n[0],r[13]-n[1],r[14]-n[2])+ee(t,!0)+Yl)}return t.radius=i+wd,yu(qe[e],n,t.radius,t.list),t},Qe=[],$e=[],et=[],tt=[],nt=[],rt=[],it=new e.Vector3,at=(e,t,n,r=null)=>{if(et.length=0,tt.length=0,nt.length=0,t)for(let{bound:t,factor:n}of e.contacts)et.push({a:t.now.a,b:t.now.b,r:t.now.r*n});let i=e.chainRoot??e,a=e.paramsTo.hair?`hair`:`extension`;if(i.partnerFrame!==Je){i!==e&&(n=it.setFromMatrixPosition(i.bind.bone.matrixWorld)),i.partnerFrame=Je,i.partnerNearKeys.length=0,i.partnerNearNows.length=0;let t=qe[a];if(t.n){let e=[n.x,n.y,n.z],r=ee(i,!0)+Yl,o=Ze(a),s=o.radius>=0&&Math.hypot(e[0]-o.centre[0],e[1]-o.centre[1],e[2]-o.centre[2])+r<=o.radius?o.list:t,c=bu(s,e,r,16,Qe,$e);for(let e=0;e<c;e++)i.partnerNearKeys.push(s.keys[Qe[e]]),i.partnerNearNows.push(s.nows[Qe[e]])}}let o=i.partnerNearKeys,s=i.partnerNearNows;for(let t=0;t<o.length;t++){let n=s[t],i=r===null?1:r.get(o[t])??1;if(!(i>0))continue;let a=rt[tt.length]??={a:n.a,b:n.b,r:0};a.a=n.a,a.b=n.b,a.r=(i===1?n.r:n.r*i)+(e.partnerPushed.includes(o[t])?Yl:0),tt.push(a),nt.push(o[t])}},ot=e=>{let t=[q.x,q.y,q.z],n=et.length?ed(t,et,1,void 0,e):t,r=tt.length?ed(t,tt):t;return[Math.hypot(n[0]-t[0],n[1]-t[1],n[2]-t[2]),Math.hypot(r[0]-t[0],r[1]-t[1],r[2]-t[2])]},st=e=>{let t=[q.x,q.y,q.z],n=tt.length?ed(t,tt):t;return et.length?ed(n,et,1,void 0,e):n},ct=()=>{let e=[],t=q.x,n=q.y,r=q.z;for(let i=0;i<tt.length;i++){let a=tt[i],o=a.b[0]-a.a[0],s=a.b[1]-a.a[1],c=a.b[2]-a.a[2],l=t-a.a[0],u=n-a.a[1],d=r-a.a[2],f=o*o+s*s+c*c,p=f>1e-12?Math.min(1,Math.max(0,(l*o+u*s+d*c)/f)):0,m=l-o*p,h=u-s*p,g=d-c*p,_=Math.sqrt(m*m+h*h+g*g);a.r-_<md-1e-9-1e-9*_||a.r-Math.hypot(m,h,g)>=md&&e.push(nt[i])}return e},lt=(e,t,n,r,i,a,o,s)=>{i(0);let c=ot(r),l=ct(),u=0,d=!1;if((c[0]>=md||c[1]>=md)&&(d=a(st(r)),d)){let e=Cu(e=>(i(e),ot(r)),c,t);e!==null&&(u=e)}let f=u,p=Math.min(t,wu(e.partnerDeg,u*180/Math.PI,n)*Math.PI/180);if(p>u&&(d||e.partnerAxis)){d||s(),i(u);let e=et.length?ot(r)[0]:0;i(p),(et.length?ot(r)[0]:0)<=Math.max(e,md)&&(f=p,d=!0)}return f>0&&d&&o(),e.partnerDeg=l.length||f>u?f*180/Math.PI:0,e.partnerPushed=l,d?f:0},ut=(t,n,r,i,a,o,s=null)=>{if(!(i>0)){t.partnerDeg=0,t.partnerPushed=[];return}if(at(t,o,it.setFromMatrixPosition(P),s),!tt.length&&t.partnerDeg===0){t.partnerPushed=[],o&&t.contacts.length&&Ge(t,n,r,i);return}Be.makeRotationFromQuaternion(He.copy(n).multiply(r)).premultiply(be).multiply(ae),Ue.copy(t.tipLocal).applyMatrix4(Be),We.copy(Ue).sub(ye),Ve.copy(P).invert();let c=lt(t,i,a,void 0,e=>{q.copy(We).applyAxisAngle(J,e).add(ye).applyMatrix4(P)},e=>(J.set(e[0],e[1],e[2]).applyMatrix4(Ve).sub(Ue),J.crossVectors(We,J),J.lengthSq()<1e-20||We.lengthSq()<1e-12?!1:(J.normalize(),!0)),()=>{(t.partnerAxis??=new e.Vector3).copy(J)},()=>{J.copy(t.partnerAxis)});c>0&&n.premultiply(He.setFromAxisAngle(J,c))},dt=(t,n,r,i,a)=>{if(!(r>0)){t.partnerDeg=0,t.partnerPushed=[];return}if(B.setFromMatrixPosition(n),at(t,a,B),!tt.length&&t.partnerDeg===0){t.partnerPushed=[],a&&t.contacts.length&&Ke(t,n,r);return}q.copy(t.tipLocal).applyMatrix4(n),We.copy(q).sub(B);let o=lt(t,r,i,hd,e=>{q.copy(We).applyAxisAngle(J,e).add(B)},e=>(q.copy(We).add(B),J.set(e[0],e[1],e[2]).sub(q),J.crossVectors(We,J),J.lengthSq()<1e-20||We.lengthSq()<1e-12?!1:(J.normalize(),!0)),()=>{(t.partnerAxis??=new e.Vector3).copy(J).transformDirection(Ve.copy(n).invert())},()=>{J.copy(t.partnerAxis).transformDirection(n)});o>0&&(oe.makeRotationAxis(J,o),n.premultiply(be.makeTranslation(-B.x,-B.y,-B.z)).premultiply(oe).premultiply(be.makeTranslation(B.x,B.y,B.z)))},ft=null,pt=(e,n,r=!1)=>{if(!(e.linkR>0))return 0;if(n.hangJoint===void 0){let e=n.bind.bone.parent;ft??=Qo(t),n.hangJoint=e?ft.get(Z(e.name))??null:null}let i=n.hangJoint?Yo($o(n.hangJoint).bindToWorld):1;return(r?e.linkSurfaceR:e.linkR)*i*Math.max(0,e.params.girth??1)},mt=(e,t,n)=>{let r={interaction:t},i=0;for(let t of g){if(t.chainRoot!==t)continue;let a=t.paramsTo.op;if(a&&!t.paramsTo.hair){for(let n of e)if(n.channels?.length)for(let e of n.channels){if(!Vl({op:a,length:t.params.length??1},e,r,n))continue;let i=`${n.name}:${e.id}`,o=t.channels??=[],s=o.find(e=>e.key===i);s||(s={key:i,partner:n.name,ch:e,gate:0,engaged:!1,w:0,inZone:!1,inGrown:!1,leverDeg:1/0,k:1,suppressKeys:[],suppressFrom:null},o.push(s)),s.ch=e,s.gate=Je,s.suppressFrom!==e.suppress&&(s.suppressKeys=[...e.suppress].map(e=>`${n.name}:${e}`),s.suppressFrom=e.suppress)}}let o=t.channels;if(o){for(let e=o.length-1;e>=0;e--){let t=o[e],r=t.gate===Je,i=Bl(t,{gate:r,tipInZone:t.inZone,tipInGrownZone:t.inGrown,leverAngleDeg:t.leverDeg},t.ch,n);t.engaged=i.engaged,t.w=i.w,!r&&!i.engaged&&!(i.w>0)&&o.splice(e,1)}o.length?i+=o.length:t.channels=null}}k=i},ht=new e.Vector3,gt=new e.Vector3,_t=new Map,vt=(e,t,n)=>{Be.makeRotationFromQuaternion(He.copy(t).multiply(n)).premultiply(be).multiply(ae),q.copy(e.tipLocal).applyMatrix4(Be).applyMatrix4(P)},yt=(e,t,n,r,i)=>{_t.clear();let a=-1;for(let o of t.channels){if(!(o.w>0))continue;let s=o.ch;if(a<0&&(a=pt(e,t)),vt(e,n,r),i>0){ht.copy(ye).applyMatrix4(P);let t=Ll([ht.x,ht.y,ht.z],[q.x,q.y,q.z],s,a),c=t?Math.min(t.angle*o.w,i):0;t&&c>0&&(gt.set(t.axis[0],t.axis[1],t.axis[2]).transformDirection(Ve.copy(P).invert()),n.premultiply(He.setFromAxisAngle(gt,c)),vt(e,n,r))}let{s:c,rho:l}=Pl([q.x,q.y,q.z],s);if(Fl(c,l,s)===`cylinder`)for(let e of o.suppressKeys)_t.set(e,Math.min(_t.get(e)??1,1-o.w))}return _t.size?_t:null},bt=new e.Vector3,xt=new e.Vector3,St=new e.Vector3,Ct=[],wt=new e.Vector3,Tt=new e.Matrix4,Et=new e.Matrix4,Dt=(e,t)=>{for(let n=e;n;n=n.parent)if(n===t)return!0;return!1},Ot=e=>{let t=e.chainLinks,n=t[t.length-1];for(let r of e.channels){if(r.k=1,!(r.w>0))continue;let i=r.ch,a=e=>(e.x-i.o[0])*i.u[0]+(e.y-i.o[1])*i.u[1]+(e.z-i.o[2])*i.u[2];Ct.length=t.length;for(let e=0;e<t.length;e++)Ct[e]=a(bt.setFromMatrixPosition(t[e].bind.bone.matrixWorld));let o=Rl(Ct);if(o<0)continue;let s=t[o].bind.bone;xt.setFromMatrixPosition(s.matrixWorld);let c=zl(a(St.copy(n.tipLocal).applyMatrix4(n.bind.bone.matrixWorld)),a(xt),i,pt(n,e)),l=1+r.w*(c-1);if(l<1){r.k=l;for(let e=o;e<t.length;e++){let n=t[e],r=n.bind.bone;if(e>o&&!Dt(r,s))continue;let i=r.matrixWorld;bt.setFromMatrixPosition(i).sub(xt).multiplyScalar(l).add(xt),wt.copy(n.tipLocal).normalize();let a=wt;Tt.set(1+(l-1)*a.x*a.x,(l-1)*a.x*a.y,(l-1)*a.x*a.z,0,(l-1)*a.y*a.x,1+(l-1)*a.y*a.y,(l-1)*a.y*a.z,0,(l-1)*a.z*a.x,(l-1)*a.z*a.y,1+(l-1)*a.z*a.z,0,0,0,0,1),i.multiply(Tt).setPosition(bt),n.bind.pureWorld.setPosition(bt),r.matrix.copy(Et.copy(r.parent.matrixWorld).invert()).multiply(i),r.matrixWorldNeedsUpdate=!0}}}for(let n of e.channels){let e=n.ch,r=!1,i=!1,a=1/0;for(let n of t){let t=n.bind.bone.matrixWorld;bt.setFromMatrixPosition(t),St.copy(n.tipLocal).applyMatrix4(t);let{s:o,rho:s}=Pl([St.x,St.y,St.z],e);if(Fl(o,s,e,Sl)&&(i=!0),!Fl(o,s,e))continue;r=!0,St.sub(bt);let c=St.length();if(c>1e-12){let t=(St.x*e.u[0]+St.y*e.u[1]+St.z*e.u[2])/c;a=Math.min(a,Math.acos(Math.max(-1,Math.min(1,t)))*180/Math.PI)}}n.inZone=r,n.inGrown=i,n.leverDeg=a}},kt=e=>{let t=null;for(let n of e.chainRoot?.channels??[])n.w>0&&(!t||n.w>t.w)&&(t=n);return t?{id:t.ch.id,w:t.w,k:t.k}:null},At=e=>{Pe.set(0,0,0,0),Le.set(0,0,0),e.anchorBlend.forEach(({bind:t,share:n},r)=>{ke.copy(t.bone.matrixWorld).multiply(t.bindWorldInverse),Le.addScaledVector(H.copy(e.head).applyMatrix4(ke),n),ke.decompose(Re,Fe,ze),r===0?Ie.copy(Fe):Ie.dot(Fe)<0&&Fe.set(-Fe.x,-Fe.y,-Fe.z,-Fe.w),Pe.set(Pe.x+n*Fe.x,Pe.y+n*Fe.y,Pe.z+n*Fe.z,Pe.w+n*Fe.w)}),Pe.normalize(),F.copy(Pe).multiply(e.worldRotation),P.decompose(Re,Fe,ze),P.compose(Le,F,ze),re.copy(P)},jt=e=>{F.identity();for(let t=e;t;t=t.parent){let e=Oe.get(t);if(e)return F.premultiply(e.bind.rotation);F.premultiply(t.quaternion)}return F};return T(n),{configure:T,reset:E,setCollision(e){b||(x=e,S=null,C())},channelOccupants(){let t=[];if(!(k>0))return t;let n=new e.Vector3,r=new e.Vector3;for(let e of g)if(!(e.chainRoot!==e||!e.channels))for(let i of e.channels){if(!(i.w>0))continue;let a=[];for(let t of e.chainLinks){let i=pt(t,e,!0);i>0&&(n.setFromMatrixPosition(t.bind.bone.matrixWorld),r.copy(t.tipLocal).applyMatrix4(t.bind.bone.matrixWorld),a.push({a:[n.x,n.y,n.z],b:[r.x,r.y,r.z],r:i}))}a.length&&t.push({partner:i.partner,channel:i.ch.id,w:i.w,segments:a})}return t},opChains(){let t=[],n=new e.Vector3,r=new e.Vector3;for(let e of g){let i=e.paramsTo.op;if(e.chainRoot!==e||!i||e.paramsTo.hair)continue;let a=[];for(let t of e.chainLinks)n.setFromMatrixPosition(t.bind.bone.matrixWorld),r.copy(t.tipLocal).applyMatrix4(t.bind.bone.matrixWorld),a.push({a:[n.x,n.y,n.z],b:[r.x,r.y,r.z],r:Math.max(0,pt(t,e)||0)});a.length&&t.push({op:i,segments:a,raised:e.straighten})}return t},bendChain(e,t){let n=-1;for(let r of g){let i=r.paramsTo.op;if(r.chainRoot!==r||!i||r.paramsTo.hair||!r.chainLinks.length||++n!==e)continue;let a=[...t].sort((e,t)=>e.joint-t.joint);for(let e of a){let t=r.chainLinks[e.joint];if(!t||!(Math.abs(e.q[3])<.999999999999))continue;let n=t.bind.bone,i=A.setFromMatrixPosition(n.matrixWorld);j.set(e.q[0],e.q[1],e.q[2],e.q[3]),M.makeRotationFromQuaternion(j),M.setPosition(te.copy(i).applyQuaternion(j).negate().add(i)),N.multiplyMatrices(M,n.matrixWorld),n.parent?ne.copy(n.parent.matrixWorld).invert():ne.identity(),n.matrix.multiplyMatrices(ne,N),n.matrix.decompose(n.position,n.quaternion,n.scale),n.updateMatrixWorld(!0)}return}},contactTips(){let t=new e.Vector3,n=[];for(let e of g){let r=k>0?kt(e):null;(e.contacts.length||e.partnerPushed.length||e.partnerDeg>0||r)&&(t.copy(e.tipLocal).applyMatrix4(e.bind.bone.matrixWorld),n.push({bone:e.bind.bone.name,tip:[t.x,t.y,t.z],tipLocal:[e.tipLocal.x,e.tipLocal.y,e.tipLocal.z],capsules:e.contacts.map(e=>e.bound.capsule.id),partner:[...e.partnerPushed],...r?{channel:r}:{}}))}return n},reach(){let e=0;for(let t of g)t.chainRoot===t&&(e=Math.max(e,ee(t,!1)));return e},update(n,r={}){if(b||!g.length&&!v.length)return;let i=Number.isFinite(n)?Math.max(0,n):0;!!r.far!==y&&(y=!!r.far,E()),t.updateWorldMatrix(!0,!1),t.updateMatrixWorld(!0);let a=!!S&&!y;a&&S.update();let o=r.partners,l=!y&&(!!o?.length||D>0||k>0);if(l)Ye(o??[]);else if(O)for(let e of g)e.partnerPushed=[],e.partnerDeg=0;O=l;let u=!1;if(l){if(k>0)u=!0;else for(let e of o??[])if(e.channels?.length){u=!0;break}}Oe.clear();for(let e of v)e.bone.matrix.copy(e.local);for(let e of g){e.paramsBlend=Math.min(1.5,e.paramsBlend+i),e.params=kd(e.paramsFrom,e.paramsTo,e.paramsBlend,e.params),e.blend=Math.min(1.5,e.blend+i);let t=e.blend/1.5,n=e.params.rest_max_deg*Math.PI/180;e.rest=Md(e.restFrom+(e.restTo-e.restFrom)*t*t*(3-2*t),-n,n),e.straightenBlend=Math.min(1.5,e.straightenBlend+i);let r=e.straightenBlend/1.5,a=r*r*(3-2*r),o=Pd(e.rest,e.straightenThreshold),s=e.straightenFrom*Pd(e.rest,e.straightenRestFrom*180/Math.PI);e.straighten=s+(o-s)*a}u&&mt(o??[],r.interaction??null,i);for(let t of g){let n=t.bind,o=t.params.max_deg*t.motionShare*Math.PI/180;P.copy(n.local),re.copy(n.local);let c=!1;for(let e=n.bone.parent;e;e=e.parent){let t=Oe.get(e);if(t){P.premultiply(t.bind.pureWorld),re.premultiply(e.matrixWorld),c=!0;break}P.premultiply(e.matrix),re.premultiply(e.matrix)}c&&P.setPosition(H.setFromMatrixPosition(re)),jt(n.bone.parent).multiply(n.localRotation);let u=!c&&!!n.anchorBlend;if(u&&At(n),t.roots.length===1&&t.roots[0]===n&&n.singleLateral.lengthSq()>1e-12?(Te.identity().slerp(n.centeringRotation,t.straighten),I.setFromAxisAngle(n.singleLateral,t.rest).multiply(Te)):t.roots.includes(n)&&n.lateral.lengthSq()>1e-12?I.setFromAxisAngle(n.lateral,t.rest):I.identity().slerp(n.straightenRotation,t.straighten),t.chain&&t.chain.length>=2&&t.chain[0]===t){let e=t.chain,n=0,r=Ee.set(0,0,0),i=De.set(0,0,0);for(let a of e){let o=a.sag,c=a.bind,l=e.find(e=>e.bind.bone===c.bone.parent);l?(o.frame.copy(l.sag.frame).multiply(c.local),o.rotation.copy(l.sag.rotation).multiply(c.localRotation)):(o.frame.copy(P),o.rotation.copy(F)),a===t?o.q.copy(I):o.q.identity().slerp(c.straightenRotation,a.straighten),o.head.setFromMatrixPosition(o.frame),o.centre.copy(c.centroid).applyQuaternion(o.q).applyMatrix4(o.frame),V.copy(o.centre).sub(o.head).normalize(),o.force.copy(s).multiplyScalar(a.params.gravity_scale??1).sub(H.copy(c.gravityRest).applyQuaternion(o.q).applyQuaternion(o.rotation)).multiplyScalar(a.params.gravity);let u=o.force.dot(V);u<0&&o.force.addScaledVector(V,-u),r.addScaledVector(o.centre,c.mass),i.addScaledVector(o.force,c.mass),n+=c.mass,oe.makeRotationFromQuaternion(o.q),o.frame.multiply(oe),o.rotation.multiply(o.q)}U.copy(r).divideScalar(n).sub(B.setFromMatrixPosition(P));let a=Md(t.paramsBlend/1.5,0,1),o=a*a*(3-2*a),c=t.staticFrequencyFrom+(t.staticFrequencyTo-t.staticFrequencyFrom)*o,l=(2*Math.PI*c)**2;Ce.copy(i).divideScalar(n).multiplyScalar(l>=1e-12?1/l:0);let u=Math.min(U.angleTo(H.copy(U).add(Ce)),(t.params.sag_max_deg??t.params.max_deg)*Math.PI/180),d=0;for(let t=0;t<e.length;t++){let n=e[t].sag;n.torque.set(0,0,0);for(let r=t;r<e.length;r++){let t=e[r];n.torque.addScaledVector(H.copy(t.sag.centre).sub(n.head).cross(t.sag.force),t.bind.mass)}let r=t+1<e.length?n.head.distanceTo(e[t+1].sag.head):2*n.centre.distanceTo(n.head);n.weight=n.torque.length()*r,d+=n.weight}for(let t of e){let e=t.sag;e.q.identity(),d>1e-12&&e.q.setFromAxisAngle(e.torque.normalize(),u*e.weight/d)}}z.copy(n.centroid).applyQuaternion(I),se.copy(z).applyMatrix4(P),B.setFromMatrixPosition(P),V.copy(se).sub(B).normalize(),xe.set(0,0,0),t.roots.length>=2&&(xe.copy(n.pairedLateral).applyQuaternion(F),xe.addScaledVector(V,-xe.dot(V)).normalize()),le.copy(s).multiplyScalar(t.params.gravity_scale??1).sub(H.copy(n.gravityRest).applyQuaternion(I).applyQuaternion(F)).multiplyScalar(t.params.gravity);let d=n.gravityProjection,f=s.dot(V)/9.81,p=Md(-f-Math.max(0,-d),0,1),m=Md(f-Math.max(0,d),0,1),h=le.dot(V);h<0&&le.addScaledVector(V,-h);let g=Md(t.paramsBlend/1.5,0,1),_=g*g*(3-2*g);t.staticFrequency=t.staticFrequencyFrom+(t.staticFrequencyTo-t.staticFrequencyFrom)*_,t.staticWeight=t.staticWeightFrom+(t.staticWeightTo-t.staticWeightFrom)*_;let v=(2*Math.PI*t.staticFrequency)**2;Ce.copy(le).multiplyScalar(v>=1e-12?1/v:0),U.copy(se).sub(B);let b=U.length();W.copy(U).add(Ce);let x=(t.params.sag_max_deg??t.params.max_deg)*Math.PI/180;if(t.chain&&t.chain.length>=2)L.copy(t.sag.q);else{L.setFromUnitVectors(V,H.copy(W).normalize());let e=L.angleTo(R);e>x&&L.slerp(R,1-x/e)}L.slerp(R,1-t.staticWeight);let S=Math.max(1e-12,b*(1-(t.params.flatten??0)*(1-(t.params.flatten_floor??t.params.squash[0]))*p+(t.params.stretch??0)*(t.params.squash[1]-1)*m));W.copy(V).applyQuaternion(L).multiplyScalar(b).sub(U),me.copy(n.gravityRest).multiplyScalar(-1/9.81).applyQuaternion(F).normalize(),W.addScaledVector(me,((t.params.head_sag??1)-1)*W.dot(me)),W.add(U);let C=(t.params.spill??0)*(t.params.spill_max_deg??t.params.sag_max_deg??t.params.max_deg)*Math.PI/180*p;xe.lengthSq()>1e-12&&(H.copy(V).cross(xe).normalize(),W.applyAxisAngle(H,C)),W.multiplyScalar(b>1e-12?S/b:1),se.copy(B).add(W);let w=i>0&&t.anchorRotation!==null&&t.anchorRotation.angleTo(F)/i>2*Math.PI;if(y||!t.p||!t.target||!r.frozen&&i>.25)(t.p??=new e.Vector3).copy(se),t.v.set(0,0,0);else if(r.frozen)t.p.add(H.copy(se).sub(t.target));else if(i>0){ce.copy(se).sub(t.target).divideScalar(i);let e=Math.ceil(i/(1/240)),n=i/e;for(let r=0;r<e;r++){ue.copy(t.target).lerp(se,r/e),ge.copy(t.p).sub(ue);let i=Cd(t.p,t.v,ue,ce,t.params,n,we);if(w){let e=W.length()*Math.sin(Math.min(Math.PI/2,o));_e.copy(i.p).sub(ue).addScaledVector(ce,-n),H.copy(_e).sub(ge).clampLength(0,e*Math.min(1,n*120)),_e.copy(ge).add(H).clampLength(0,e),H.copy(ue).addScaledVector(ce,n).add(_e),H.distanceToSquared(i.p)>1e-20&&i.v.copy(ce),i.p.copy(H)}(!Number.isFinite(i.p.lengthSq())||!Number.isFinite(i.v.lengthSq()))&&(i.p.copy(ue).addScaledVector(ce,n),i.v.set(0,0,0)),t.p.copy(i.p),t.v.copy(i.v)}}(t.anchorRotation??=new e.Quaternion).copy(F),(t.target??=new e.Vector3).copy(se),de.copy(se).sub(B),V.copy(de).normalize(),me.copy(n.gravityRest).multiplyScalar(-1/9.81).applyQuaternion(F),me.addScaledVector(V,-me.dot(V)),me.lengthSq()<1e-10&&(me.copy(n.bodyFront).applyQuaternion(F),me.addScaledVector(V,-me.dot(V))),me.normalize(),he.copy(t.p).sub(se);let T=t.params.axis_gain??Dd,E=he.dot(V),D=he.dot(me);he.multiplyScalar(T[0]).addScaledVector(me,(T[1]-T[0])*D).addScaledVector(V,(T[2]-T[0])*E),fe.copy(de).add(he),fe.addScaledVector(V,Math.max(0,1e-12-de.length()-T[2]*E)),L.setFromUnitVectors(H.copy(de).normalize(),V.copy(fe).normalize());let O=L.angleTo(R),k=Nd(O,o);O>0&&L.slerp(R,1-k/O);let ee=Math.max(1e-12,de.length()+T[2]*E);fe.copy(de).applyQuaternion(L).multiplyScalar(ee/de.length());let A=y?0:t.params.gain;fe.sub(de).multiplyScalar(A).add(de),fe.normalize().multiplyScalar(Math.max(1e-12,de.length()+A*T[2]*E));let te=t.params.translate??0;ve.copy(de).sub(U),H.copy(U).normalize(),ve.addScaledVector(H,-ve.dot(H)),ve.clampLength(0,b*Math.max(0,Math.sin(x))),ye.copy(fe).sub(de),H.copy(U).normalize(),ye.addScaledVector(H,-ye.dot(H)),ye.clampLength(0,de.length()*Math.max(0,Math.sin(o))),ve.add(ye).multiplyScalar(te);let j=fe.length();fe.sub(ve).normalize().multiplyScalar(j),pe.copy(fe).add(B).applyMatrix4(ie.copy(P).invert()),L.setFromUnitVectors(H.copy(z).normalize(),V.copy(pe).normalize());let M=H.copy(se).applyMatrix4(ie).length()/z.length(),N=Md(pe.length()/z.length(),Math.min(t.params.squash[0],M),t.params.squash[1]),ne=t.params.spread??.5,ke=N<1?Math.min(Ed,1+ne*(1/Math.sqrt(N)-1)):1/Math.sqrt(N);V.copy(n.scaleAxis),ae.identity();let je=ae.elements,Me=Math.min(Ed,1+ne*(1/N-1));G.copy(L).multiply(I).invert(),K.copy(n.bodyFront).applyQuaternion(G).normalize(),Se.copy(xe).transformDirection(ie.copy(P).invert()).applyQuaternion(G),Se.addScaledVector(K,-Se.dot(K)),Se.lengthSq()>1e-12?Se.normalize():Se.set(0,0,0);let Ne=N<1&&t.roots.length>=2&&Se.lengthSq()>1e-12;for(let e=0;e<3;e++)for(let t=0;t<3;t++)je[t*4+e]=Ne?+(e===t)+(N-1)*K.getComponent(e)*K.getComponent(t)+(Me-1)*Se.getComponent(e)*Se.getComponent(t):(e===t?ke:0)+(N-ke)*V.getComponent(e)*V.getComponent(t);let Pe=t.params.length??1,Fe=t.params.girth??1;for(let e=0;e<3;e++)for(let t=0;t<3;t++)je[t*4+e]=Fe*je[t*4+e]+(Pe-Fe)*N*V.getComponent(e)*V.getComponent(t);if(ye.copy(B).add(ve).applyMatrix4(ie),be.makeTranslation(ye.x,ye.y,ye.z),l&&!n.todayBlend){let e=Math.max(t.params.max_deg,t.params.sag_max_deg??0)*t.motionShare*Math.PI/180,n=t.chainRoot??t,r=n.channels?yt(t,n,L,I,e):null;ut(t,L,I,e,i,a,r)}else a&&t.contacts.length&&!n.todayBlend&&Ge(t,L,I,Math.max(t.params.max_deg,t.params.sag_max_deg??0)*t.motionShare*Math.PI/180);n.bone.matrix.copy(u?Ae.copy(n.bone.parent.matrixWorld).invert().multiply(P):n.local).multiply(be).multiply(oe.makeRotationFromQuaternion(L.multiply(I))).multiply(ae),n.rotation.copy(F).multiply(L),Oe.set(n.bone,t),n.bone.matrixWorldNeedsUpdate=!0,n.pureWorld.copy(P).multiply(be).multiply(oe),n.bone.matrixWorld.copy(n.pureWorld).multiply(ae),c&&n.bone.matrix.copy(n.local).multiply(ie.copy(re).invert()).multiply(n.bone.matrixWorld),l&&t.chainRoot?.channels&&t===t.chainRoot.chainLinks[t.chainRoot.chainLinks.length-1]&&Ot(t.chainRoot)}for(let e of _){let t=e.bone.parent,n=Oe.get(t);re.copy(t.matrixWorld).multiply(e.local),P.copy(n?n.bind.pureWorld:t.matrixWorld).multiply(e.local),P.setPosition(H.setFromMatrixPosition(re)),e.bone.matrixWorld.copy(P),e.pureWorld.copy(P),e.bone.matrix.copy(ie.copy(t.matrixWorld).invert()).multiply(P),e.bone.matrixWorldNeedsUpdate=!0}if(!y&&v.length){Ne++;for(let t of v){let n=Oe.get(t.bone),r=t.bone.parent,o=c.get(r),s=o?.today?.frame===Ne?o.today:void 0;s||r.updateWorldMatrix(!1,!1);let u=t.today??={frame:0,rest:new e.Matrix4,world:new e.Matrix4,bind:t.bindWorldInverse.clone().invert()};u.frame=Ne;let d=u.rest.copy(s?s.rest:r.matrixWorld).multiply(t.local);n?je.copy(d).invert().multiply(t.bone.matrixWorld):je.identity(),je.decompose(Re,Fe,ze),Fe.slerp(R,1-t.swingShare),je.compose(Re.multiplyScalar(t.swingShare),Fe,ze),Me.set(0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0);for(let{bind:e,share:n}of t.todayBlend){ke.copy(e.bone.matrixWorld).multiply(e.bindWorldInverse);for(let e=0;e<16;e++)Me.elements[e]+=n*ke.elements[e]}let f=u.world.copy(Me).multiply(u.bind).multiply(je);n&&l?dt(n,f,Math.max(n.params.max_deg,n.params.sag_max_deg??0)*n.motionShare*Math.PI/180,i,a):n&&a&&n.contacts.length&&Ke(n,f,Math.max(n.params.max_deg,n.params.sag_max_deg??0)*n.motionShare*Math.PI/180),t.bone.matrix.copy(Ae.copy(s?s.world:r.matrixWorld).invert().multiply(f)),t.bone.matrixWorld.copy(f),t.bone.matrixWorldNeedsUpdate=!0}}if(l){D=0;for(let e of g)e.partnerDeg>0&&D++}t.updateMatrixWorld(!0)},dispose(){for(let e of g)w(e.bind);for(let e of _)w(e);for(let e of v)w(e);g=[],_=[],v=[],c.clear(),u.clear(),m.clear(),l.clear(),S=null,b=!0}}}var Ld=.02,Rd=.015,zd=1.5,Bd=.08,Vd=.01,Hd=.001,Ud=.5,Wd=1e-6;function Gd(e,t=Rd,n=0){return Math.max(t,zd*Math.max(e,n))}function Kd(e,t,n={},r=0){let i=t+(n.margin??.002),a=i+Gd(t,n.band,r);if(e>=a)return e;let o=1-Math.max(0,e)/a;return e+i*o*o}function qd(e,t,n=Ld){let r=e>t.depth?e-t.depth:e<-t.funnel?-t.funnel-e:0;if(r<=0)return 1;if(!(n>0)||r>=n)return 0;let i=r/n;return 1-i*i*(3-2*i)}function Jd(e,t,n=Ld,r=Bd){let i=[];for(let a=0,o=Math.floor(e.length/3);a<o;a++){let{s:o,rho:s}=Pl([e[3*a],e[3*a+1],e[3*a+2]],t);o>=-t.funnel-n&&o<=t.depth+n&&s<=t.r+n+r&&i.push(a)}return i}function Yd(e,t,n,r={}){if(!n.length)return null;let{s:i}=Pl(e,t),a=qd(i,t,r.falloff??.02);if(!(a>0))return null;let o=1/0,s=e,c=0;for(let t of n){let n=[t.b[0]-t.a[0],t.b[1]-t.a[1],t.b[2]-t.a[2]],r=n[0]*n[0]+n[1]*n[1]+n[2]*n[2],i=r>0?Math.max(0,Math.min(1,((e[0]-t.a[0])*n[0]+(e[1]-t.a[1])*n[1]+(e[2]-t.a[2])*n[2])/r)):0,a=[t.a[0]+n[0]*i,t.a[1]+n[1]*i,t.a[2]+n[2]*i],l=Math.hypot(e[0]-a[0],e[1]-a[1],e[2]-a[2]);l-t.r<o&&(o=l-t.r,s=a,c=t.r)}let l=[e[0]-s[0],e[1]-s[1],e[2]-s[2]],u=Math.hypot(l[0],l[1],l[2]),d=a*(Kd(u,c,r,t.r)-u);if(!(d>Wd))return null;if(u>1e-9)l=[l[0]/u,l[1]/u,l[2]/u];else{let n=[e[0]-t.o[0]-t.u[0]*i,e[1]-t.o[1]-t.u[1]*i,e[2]-t.o[2]-t.u[2]*i],r=Math.hypot(n[0],n[1],n[2]);if(r>1e-9)l=[n[0]/r,n[1]/r,n[2]/r];else{let e=Math.abs(t.u[0])<.9?[1,0,0]:[0,1,0],n=[t.u[1]*e[2]-t.u[2]*e[1],t.u[2]*e[0]-t.u[0]*e[2],t.u[0]*e[1]-t.u[1]*e[0]],r=Math.hypot(n[0],n[1],n[2]);l=[n[0]/r,n[1]/r,n[2]/r]}}return[l[0]*d,l[1]*d,l[2]*d]}function Xd(e,t,n={},r=Vd){let i=1/0,a=-1/0,o=0,s=0;for(let r of e){for(let e of[r.a,r.b]){let{s:n,rho:r}=Pl(e,t);i=Math.min(i,n),a=Math.max(a,n),o=Math.max(o,r)}s=Math.max(s,r.r+(n.margin??.002)+Gd(r.r,n.band,t.r))}return{sMin:i-s-r,sMax:a+s+r,rhoMax:o+s+r}}function Zd(e,t,n,r,i,a,o){let s=e-r.o[0],c=t-r.o[1],l=n-r.o[2],u=qd(s*r.u[0]+c*r.u[1]+l*r.u[2],r,a.falloff??.02);if(!(u>0))return 0;let d=1/0,f=0,p=0,m=0,h=0;for(let r of i){let i=r.a[0],a=r.a[1],o=r.a[2],s=r.b[0]-i,c=r.b[1]-a,l=r.b[2]-o,u=s*s+c*c+l*l,g=u>0?((e-i)*s+(t-a)*c+(n-o)*l)/u:0;g=g<0?0:g>1?1:g;let _=i+s*g,v=a+c*g,y=o+l*g,b=Math.hypot(e-_,t-v,n-y);b-r.r<d&&(d=b-r.r,f=_,p=v,m=y,h=r.r)}let g=e-f,_=t-p,v=n-m,y=Math.hypot(g,_,v),b=u*(Kd(y,h,a,r.r)-y);if(!(b>Wd))return 0;if(y>1e-9)return o[0]=g/y*b,o[1]=_/y*b,o[2]=v/y*b,b;let x=Yd([e,t,n],r,i,a);return x?(o[0]=x[0],o[1]=x[1],o[2]=x[2],b):0}function Qd(e,t){let n=e.geometry.attributes.skinIndex,r=e.geometry.attributes.skinWeight,i=new Uint16Array(t.length*4),a=new Float32Array(t.length*4),o=new Set;return t.forEach((e,t)=>{for(let s=0;s<4;s++){let c=r?r.getComponent(e,s):0,l=n?n.getComponent(e,s):0;i[4*t+s]=l,a[4*t+s]=c,c>0&&o.add(l)}}),{skinI:i,skinW:a,usedBones:[...o]}}function $d(e,t,n,r={}){t.updateMatrixWorld(!0);let i=r.falloff??.02,a=[];t.traverse(e=>{let t=e;t.isSkinnedMesh&&t.skeleton&&!Uo(t)&&t.geometry?.attributes?.position&&a.push(t)});let o=new e.Vector3,s=[];for(let e of a){let t=e.geometry.attributes.position,a=new Float32Array(t.count*3);for(let n=0;n<t.count;n++)e.getVertexPosition(n,o).applyMatrix4(e.matrixWorld),a[3*n]=o.x,a[3*n+1]=o.y,a[3*n+2]=o.z;let c=Jd(a,n,i,r.slack??.08);if(!c.length)continue;let l=new Int32Array(t.count).fill(-1);c.forEach((e,t)=>{l[e]=t});let u=new Float32Array(c.length),d=new Float32Array(c.length);c.forEach((e,t)=>{let r=Pl([a[3*e],a[3*e+1],a[3*e+2]],n);u[t]=r.s,d[t]=r.rho});let f=e.geometry.index,p=[],m=Math.floor((f?f.count:t.count)/3);for(let e=0;e<m;e++){let t=f?f.getX(3*e):3*e,n=f?f.getX(3*e+1):3*e+1,r=f?f.getX(3*e+2):3*e+2;(l[t]>=0||l[n]>=0||l[r]>=0)&&p.push(t,n,r)}let h=new Map,g=new Int32Array(c.length);c.forEach((e,n)=>{let r=`${t.getX(e).toFixed(6)},${t.getY(e).toFixed(6)},${t.getZ(e).toFixed(6)}`,i=h.get(r);i===void 0&&(i=h.size,h.set(r,i)),g[n]=i}),s.push({mesh:e,original:e.geometry,clone:null,idx:c,sBind:u,rhoBind:d,rest:new Float32Array(c.length*3),restNormal:null,tris:new Uint32Array(p),slot:l,group:g,groups:h.size,moved:new Uint8Array(c.length),...Qd(e,c),m:new Float64Array(16),accN:new Float64Array(h.size*3),touched:new Uint8Array(h.size)})}if(!s.length)return null;let c=new e.Matrix4,l=new e.Matrix4,u=new Map,d=e=>{let t=e.mesh.skeleton.bones,n=e.mesh.skeleton.boneInverses,r=u.get(e.mesh);r||(r=new Float64Array(t.length*16),u.set(e.mesh,r)),l.multiplyMatrices(e.mesh.matrixWorld,e.mesh.bindMatrixInverse);for(let i of e.usedBones)if(t[i]){c.multiplyMatrices(t[i].matrixWorld,n[i]).premultiply(l).multiply(e.mesh.bindMatrix);for(let e=0;e<16;e++)r[16*i+e]=c.elements[e]}return r},f=new Float64Array(3),p=null,m=new Float64Array(6),h=new Map,g=(e,t)=>{p=new Float64Array(t.length*7),t.forEach((e,t)=>{p.set([...e.a,...e.b,e.r],7*t)}),m.set([...e.o,...e.u]);for(let e of s){let t=e.mesh.skeleton.bones,n=h.get(e);n||(n=new Float64Array(e.usedBones.length*16),h.set(e,n)),e.usedBones.forEach((e,r)=>{t[e]&&n.set(t[e].matrixWorld.elements,16*r)})}},_=(e,t,n,r,i)=>{if(Math.hypot(e[12]-t[n+12],e[13]-t[n+13],e[14]-t[n+14])>r)return!0;for(let r=0;r<3;r++){let a=Math.hypot(e[4*r],e[4*r+1],e[4*r+2])||1;if(Math.hypot(e[4*r]-t[n+4*r],e[4*r+1]-t[n+4*r+1],e[4*r+2]-t[n+4*r+2])/a>i)return!0}return!1},v=(e,t,n,r)=>{if(!y||!p||p.length!==t.length*7)return!0;let i=2*Math.sin(r*Math.PI/360);for(let e=0;e<t.length;e++){let r=t[e],i=7*e;if(Math.hypot(r.a[0]-p[i],r.a[1]-p[i+1],r.a[2]-p[i+2])>n||Math.hypot(r.b[0]-p[i+3],r.b[1]-p[i+4],r.b[2]-p[i+5])>n||Math.abs(r.r-p[i+6])>n)return!0}if(Math.hypot(e.o[0]-m[0],e.o[1]-m[1],e.o[2]-m[2])>n||Math.hypot(e.u[0]-m[3],e.u[1]-m[4],e.u[2]-m[5])>i)return!0;for(let e of s){let t=h.get(e);if(!t)return!0;let r=e.mesh.skeleton.bones;for(let a=0;a<e.usedBones.length;a++){let o=r[e.usedBones[a]];if(o&&_(o.matrixWorld.elements,t,16*a,n,i))return!0}}return!1},y=!1,b=()=>{for(let e of s){if(!e.clone)continue;let t=e.clone.attributes.position,n=e.clone.attributes.normal;e.idx.forEach((r,i)=>{t.setXYZ(r,e.rest[3*i],e.rest[3*i+1],e.rest[3*i+2]),n&&e.restNormal&&n.setXYZ(r,e.restNormal[3*i],e.restNormal[3*i+1],e.restNormal[3*i+2])}),t.needsUpdate=!0,n&&(n.needsUpdate=!0),e.mesh.geometry=e.original}y=!1},x=(e,t,n)=>{let r=e.accN.fill(0),i=e.touched.fill(0),a=t.array,o=!t.isInterleavedBufferAttribute&&t.itemSize===3,s=e=>o?a[3*e]:t.getX(e),c=e=>o?a[3*e+1]:t.getY(e),l=e=>o?a[3*e+2]:t.getZ(e),u=e.tris,d=e.slot,f=e.moved,p=e.group;for(let e=0;e<u.length;e+=3){let t=u[e],n=u[e+1],a=u[e+2],o=d[t],m=d[n],h=d[a],g=o>=0&&f[o]===1||m>=0&&f[m]===1||h>=0&&f[h]===1;if(!g&&!(o>=0&&f[o]===2)&&!(m>=0&&f[m]===2)&&!(h>=0&&f[h]===2))continue;let _=s(t),v=c(t),y=l(t),b=s(n)-_,x=c(n)-v,S=l(n)-y,C=s(a)-_,w=c(a)-v,T=l(a)-y,E=x*T-S*w,D=S*C-b*T,O=b*w-x*C;if(o>=0){let e=p[o];r[3*e]+=E,r[3*e+1]+=D,r[3*e+2]+=O,g&&(i[e]=1)}if(m>=0){let e=p[m];r[3*e]+=E,r[3*e+1]+=D,r[3*e+2]+=O,g&&(i[e]=1)}if(h>=0){let e=p[h];r[3*e]+=E,r[3*e+1]+=D,r[3*e+2]+=O,g&&(i[e]=1)}}for(let t=0;t<e.idx.length;t++){let a=p[t];if(!i[a])continue;let o=Math.hypot(r[3*a],r[3*a+1],r[3*a+2]);o>0&&n.setXYZ(e.idx[t],r[3*a]/o,r[3*a+1]/o,r[3*a+2]/o)}n.needsUpdate=!0};return{channel:n.id,candidates:s.reduce((e,t)=>e+t.idx.length,0),apply(e,t,n=r){if(!t.length)return y&&b(),{maxPush:0,moved:0,visited:0};let i=Xd(t,e,n),a=0,o=0,c=0;for(let r of s){r.clone||=r.original.clone();let s=r.clone.attributes.position,l=r.clone.attributes.normal;y||(r.idx.forEach((e,t)=>{r.rest[3*t]=s.getX(e),r.rest[3*t+1]=s.getY(e),r.rest[3*t+2]=s.getZ(e)}),l&&(r.restNormal??=new Float32Array(r.idx.length*3),r.idx.forEach((e,t)=>{r.restNormal[3*t]=l.getX(e),r.restNormal[3*t+1]=l.getY(e),r.restNormal[3*t+2]=l.getZ(e)}))),r.mesh.geometry=r.clone;let u=!1,p=d(r),m=r.m;for(let d=0;d<r.idx.length;d++){let h=r.idx[d],g=r.rest[3*d],_=r.rest[3*d+1],v=r.rest[3*d+2];if(r.moved[d]===1?(s.setXYZ(h,g,_,v),l&&r.restNormal&&l.setXYZ(h,r.restNormal[3*d],r.restNormal[3*d+1],r.restNormal[3*d+2]),r.moved[d]=2):r.moved[d]=0,r.sBind[d]<i.sMin||r.sBind[d]>i.sMax||r.rhoBind[d]>i.rhoMax)continue;c++,m.fill(0);for(let e=0;e<4;e++){let t=r.skinW[4*d+e];if(!(t>0))continue;let n=16*r.skinI[4*d+e];for(let e=0;e<16;e++)m[e]+=p[n+e]*t}let y=Zd(m[0]*g+m[4]*_+m[8]*v+m[12],m[1]*g+m[5]*_+m[9]*v+m[13],m[2]*g+m[6]*_+m[10]*v+m[14],e,t,n,f);if(!(y>0))continue;o++,r.moved[d]=1,y>a&&(a=y);let b=m[0],x=m[4],S=m[8],C=m[1],w=m[5],T=m[9],E=m[2],D=m[6],O=m[10],k=w*O-T*D,ee=-(C*O-T*E),A=C*D-w*E,te=b*k+x*ee+S*A;if(!(Math.abs(te)>1e-20))continue;let j=f[0],M=f[1],N=f[2],ne=(k*j+(S*D-x*O)*M+(x*T-S*w)*N)/te,P=(ee*j+(b*O-S*E)*M+(S*C-b*T)*N)/te,re=(A*j+(x*E-b*D)*M+(b*w-x*C)*N)/te;s.setXYZ(h,g+ne,_+P,v+re),u=!0}s.needsUpdate=!0,l&&(u||r.moved.includes(2)?x(r,s,l):l.needsUpdate=!0)}return y=!0,g(e,t),{maxPush:a,moved:o,visited:c}},changed(e,t,n=Hd,r=Ud){return v(e,t,n,r)},restore(){y&&b()},dispose(){b();for(let e of s)e.clone?.dispose(),e.clone=null}}}var ef=17,tf=9.81,nf=.03,rf=.03,af=.003,of=.127,sf=.002,cf=.02,lf=4,uf=5e-4,df=20,ff=45,pf=Math.cos(df*Math.PI/180),mf=Math.cos(ff*Math.PI/180);function hf(e){if(e>=pf)return 0;if(e<=mf)return 1;let t=(pf-e)/(pf-mf);return t*t*(3-2*t)}var gf=1.05,_f={accel:.25*Math.PI*Math.PI,angAccel:15*Math.PI/180*Math.PI*Math.PI};function vf(e){let t=t=>Number(e[t]);return{damping:t(`damping`),stiffness:t(`stiffness`),bend:t(`bend`),iterations:t(`iterations`),rootDeg:t(`root_deg`),rootFrac:t(`root_frac`),flySoft:!!e.fly_soft,flyArc:t(`fly_arc`),tether:!!e.tether,tetherR0:t(`tether_r0`),tetherR1:t(`tether_r1`),tetherHead:t(`tether_head`),headClr:t(`head_clr`),faceBox:!!e.face_box}}var yf=class extends Error{constructor(e){super(e),this.name=`StrandMismatch`}};function bf(e){let t=e[0],n=e[4],r=e[8],i=e[1],a=e[5],o=e[9],s=e[2],c=e[6],l=e[10],u=a*l-o*c,d=o*s-i*l,f=i*c-a*s,p=t*u+n*d+r*f;if(!p)return Array(16).fill(0);let m=1/p,h=[u*m,d*m,f*m,0,(r*c-n*l)*m,(t*l-r*s)*m,(n*s-t*c)*m,0,(n*o-r*a)*m,(r*i-t*o)*m,(t*a-n*i)*m,0,0,0,0,1],g=e[12],_=e[13],v=e[14];return h[12]=-(h[0]*g+h[4]*_+h[8]*v),h[13]=-(h[1]*g+h[5]*_+h[9]*v),h[14]=-(h[2]*g+h[6]*_+h[10]*v),h}function xf(e){let t=e[0],n=e[4],r=e[8],i=e[1],a=e[5],o=e[9],s=e[2],c=e[6],l=e[10],u=t+a+l;if(u>0){let e=.5/Math.sqrt(u+1);return[(c-o)*e,(r-s)*e,(i-n)*e,.25/e]}if(t>a&&t>l){let e=2*Math.sqrt(1+t-a-l);return[.25*e,(n+i)/e,(r+s)/e,(c-o)/e]}if(a>l){let e=2*Math.sqrt(1+a-t-l);return[(n+i)/e,.25*e,(o+c)/e,(r-s)/e]}let d=2*Math.sqrt(1+l-t-a);return[(r+s)/d,(o+c)/d,.25*d,(i-n)/d]}function Sf(e,t,n,r){if(n<=0||n>=1){let i=n<=0?e:t;for(let e=0;e<16;e++)r[e]=i[e];return r}let i=[0,0,0],a=[0,0,0],o=Array(11).fill(0),s=Array(11).fill(0);for(let n=0;n<3;n++){i[n]=Math.hypot(e[4*n],e[4*n+1],e[4*n+2])||1,a[n]=Math.hypot(t[4*n],t[4*n+1],t[4*n+2])||1;for(let r=0;r<3;r++)o[4*n+r]=e[4*n+r]/i[n],s[4*n+r]=t[4*n+r]/a[n]}let c=xf(o),l=xf(s),u=c[0]*l[0]+c[1]*l[1]+c[2]*l[2]+c[3]*l[3];if(u<0){u=-u;for(let e=0;e<4;e++)l[e]=-l[e]}let d=1-n,f=n;if(u<.9995){let e=Math.acos(Math.min(1,u)),t=Math.sin(e);d=Math.sin((1-n)*e)/t,f=Math.sin(n*e)/t}let p=d*c[0]+f*l[0],m=d*c[1]+f*l[1],h=d*c[2]+f*l[2],g=d*c[3]+f*l[3],_=Math.hypot(p,m,h,g)||1;p/=_,m/=_,h/=_,g/=_;let v=[1-2*(m*m+h*h),2*(p*m+g*h),2*(p*h-g*m),2*(p*m-g*h),1-2*(p*p+h*h),2*(m*h+g*p),2*(p*h+g*m),2*(m*h-g*p),1-2*(p*p+m*m)];for(let e=0;e<3;e++){let t=i[e]+(a[e]-i[e])*n;r[4*e]=v[3*e]*t,r[4*e+1]=v[3*e+1]*t,r[4*e+2]=v[3*e+2]*t,r[4*e+3]=0}return r[12]=e[12]+(t[12]-e[12])*n,r[13]=e[13]+(t[13]-e[13])*n,r[14]=e[14]+(t[14]-e[14])*n,r[15]=1,r}function Cf(e,t,n,r,i,a){let o=r,s=i,c=a;for(let r=0;r<ef;r++){let i=t+3*Math.min(r,ef-2),a=i+3,l=e[a]-e[i],u=e[a+1]-e[i+1],d=e[a+2]-e[i+2],f=Math.hypot(l,u,d)||1e-9;l/=f,u/=f,d/=f;let p=o*l+s*u+c*d;o-=p*l,s-=p*u,c-=p*d,f=Math.hypot(o,s,c),f<1e-9&&(Math.abs(l)<.9?(o=0,s=-d,c=u):(o=d,s=0,c=-l),f=Math.hypot(o,s,c)),o/=f,s/=f,c/=f;let m=9*r;n[m]=l,n[m+1]=u,n[m+2]=d,n[m+3]=o,n[m+4]=s,n[m+5]=c,n[m+6]=u*c-d*s,n[m+7]=d*o-l*c,n[m+8]=l*s-u*o}}function wf(e,t,n,r){if(t<=e[0]||t>=e[1]||n<=e[2]||n>=e[3]||r<=e[4])return[0,-1];let i=t-e[0],a=0;return e[1]-t<i&&(i=e[1]-t,a=1),e[3]-n<i&&(i=e[3]-n,a=2),[i,a]}function Tf(e,t,n){let r=n[0]-t[0],i=n[1]-t[1],a=n[2]-t[2],o=e[0]-t[0],s=e[1]-t[1],c=e[2]-t[2],l=r*r+i*i+a*a,u=l>1e-12?Math.min(1,Math.max(0,(o*r+s*i+c*a)/l)):0;return Math.hypot(o-r*u,s-i*u,c-a*u)}function Ef(e){let t=atob(e.data),n=new Int8Array(t.length);for(let e=0;e<t.length;e++)n[e]=t.charCodeAt(e)<<24>>24;let[r,i,a]=e.dims;if(n.length!==r*i*a)throw new yf(`SDF holds ${n.length} values for ${r}×${i}×${a}`);return{q:n,dims:[r,i,a],lo:[e.lo[0],e.lo[1],e.lo[2]],vox:e.vox}}function Df(e,t,n,r,i){let[a,o,s]=e.dims,c=e.vox,l=(t-e.lo[0])/c,u=(n-e.lo[1])/c,d=(r-e.lo[2])/c;if(l<0||u<0||d<0||l>a-1.001||u>o-1.001||d>s-1.001)return i&&(i[0]=0,i[1]=0,i[2]=0),of;let f=l|0,p=u|0,m=d|0,h=l-f,g=u-p,_=d-m,v=e.q,y=a,b=a*o,x=f+a*(p+o*m),S=v[x],C=v[x+1],w=v[x+y],T=v[x+1+y],E=v[x+b],D=v[x+1+b],O=v[x+y+b],k=v[x+1+y+b],ee=S+(C-S)*h,A=w+(T-w)*h,te=E+(D-E)*h,j=O+(k-O)*h,M=ee+(A-ee)*g,N=te+(j-te)*g;return i&&(i[0]=(C-S)*(1-g)*(1-_)+(T-w)*g*(1-_)+(D-E)*(1-g)*_+(k-O)*g*_,i[1]=(A-ee)*(1-_)+(j-te)*_,i[2]=N-M),(M+(N-M)*_)*.001}function Of(e,t,n,r,i){let a=r.length,o=e.cards;if(t.length!==3*a||n.length!==3*a||i.length!==a)throw new yf(`attribute lengths differ: ${t.length/3} positions, ${n.length/3} normals, ${a} cards, ${i.length} u`);if(!(o>0)||e.rows!==ef||e.rest.length!==o*ef*3||e.pins.length!==o||e.free_arc.length!==o*ef||e.free_frac.length!==o*ef||e.follow.w.length!==o*ef*e.follow.bones.length)throw new yf(`the record's arrays do not fit ${o} cards of ${ef} rows`);let s=0;for(let e=0;e<a;e++)r[e]>s&&(s=r[e]);if(s-1>=o)throw new yf(`_STRAND_CARD ${s} names card ${s-1}; the record has ${o} cards`);let c=Float32Array.from(e.rest),l=new Int32Array(a),u=new Uint8Array(a),d=new Float64Array(a);for(let e=0;e<a;e++){let t=r[e]-1;if(l[e]=t,t<0)continue;let n=Math.min(ef-1,Math.max(0,i[e])),a=Math.min(ef-2,Math.floor(n));u[e]=a;let o=Math.min(1,Math.max(0,n-a));d[e]=o<1e-6?0:o}let f=new Int32Array(o+1),p=new Int32Array(a);for(let e=0;e<a;e++)l[e]>=0&&f[l[e]+1]++;for(let e=0;e<o;e++)f[e+1]+=f[e];let m=f.slice(0,o),h=[];for(let e=0;e<a;e++)l[e]>=0?p[m[l[e]]++]=e:h.push(e);let g=new Float64Array(o*3),_=new Float64Array(ef*9),v=new Float64Array(a*6),y=new Float64Array(a*6);for(let e=0;e<o;e++){let r=e*ef*3,i=c[r+3]-c[r],a=-(c[r+5]-c[r+2]),o=i,s=Math.hypot(a,o);s<1e-6&&(a=1,o=0,s=1),g[3*e]=a/s,g[3*e+1]=0,g[3*e+2]=o/s,Cf(c,r,_,g[3*e],g[3*e+1],g[3*e+2]);for(let i=f[e];i<f[e+1];i++){let e=p[i];for(let i=0;i<2&&!(i&&!d[e]);i++){let a=u[e]+i,o=r+3*a,s=9*a,l=6*e+3*i,d=t[3*e]-c[o],f=t[3*e+1]-c[o+1],p=t[3*e+2]-c[o+2];for(let t=0;t<3;t++)v[l+t]=d*_[s+3*t]+f*_[s+3*t+1]+p*_[s+3*t+2],y[l+t]=n[3*e]*_[s+3*t]+n[3*e+1]*_[s+3*t+1]+n[3*e+2]*_[s+3*t+2]}}}return{S:o,C0:c,N00:g,vk:l,va:u,vt:d,off:v,noff:y,cStart:f,cVerts:p,rigid:Int32Array.from(h),pos0:Float32Array.from(t),nrm0:Float32Array.from(n)}}var kf=new WeakMap;function Af(e,t,n){let r=kf.get(e);r||(r={rest:Float64Array.from(e.rest),w:Float64Array.from(e.follow.w)},kf.set(e,r));let{rest:i,w:a}=r,o=e.follow.bones.length,s=i.length/3;if(t.length!==o)throw new yf(`${t.length} follow matrices for ${o} bones`);for(let e=0;e<s;e++){let r=i[3*e],s=i[3*e+1],c=i[3*e+2],l=0,u=0,d=0;for(let n=0;n<o;n++){let i=a[e*o+n];if(!i)continue;let f=t[n];l+=i*(f[0]*r+f[4]*s+f[8]*c+f[12]),u+=i*(f[1]*r+f[5]*s+f[9]*c+f[13]),d+=i*(f[2]*r+f[6]*s+f[10]*c+f[14])}n[3*e]=l,n[3*e+1]=u,n[3*e+2]=d}}var jf=new Float64Array(3);function Mf(e,t,n,r,i,a,o,s,c,l){let u=Math.hypot(o,s,c)||1e-9;o/=u,s/=u,c/=u;let d=r-e,f=i-t,p=a-n,m=Math.hypot(d,f,p);if(m<1e-9)return!1;d/=m,f/=m,p/=m;let h=d*o+f*s+p*c;if(h>=l)return!1;let g=d-h*o,_=f-h*s,v=p-h*c,y=Math.hypot(g,_,v);y<1e-9?(g=0,_=0,v=0):(g/=y,_/=y,v/=y);let b=Math.sqrt(Math.max(0,1-l*l));return jf[0]=e+m*(o*l+g*b),jf[1]=t+m*(s*l+_*b),jf[2]=n+m*(c*l+v*b),!0}function Nf(e){return(e.capsules?.capsules??[]).filter(e=>ad.includes(e.region)).slice(0,16)}var Pf=class{binding;n;X;Xp;pin;f;sdf;sdf0;faceBox;k;arcFree;clr;fly;onHead;boxD0;L1;L2;cosLim;kb2;kFly;limKey=``;flyKey=NaN;g=new Float32Array(3);capKey=[];capFactors=new Float32Array;frames=new Float64Array(ef*9);Tp;tpOk=!1;Cl;hang;fw;nb;downs;constructor(e,t){let n=e.S,r=n*ef;if(t.cards!==n)throw new yf(`binding of ${n} cards for a record of ${t.cards}`);this.binding=e,this.n=r,this.X=new Float32Array(3*r),this.Xp=new Float32Array(3*r),this.Tp=new Float32Array(3*r),this.pin=new Uint8Array(r),this.f=Float32Array.from(t.free_frac),this.arcFree=Float32Array.from(t.free_arc),this.k=new Float32Array(r),this.clr=new Float32Array(r),this.fly=new Uint8Array(r),this.onHead=new Float32Array(r),this.boxD0=new Float32Array(r),this.sdf0=new Float32Array(r),this.L1=new Float32Array(r),this.L2=new Float32Array(r),this.cosLim=new Float32Array(r),this.kb2=new Float32Array(r),this.kFly=new Float32Array(r),this.Cl=new Float64Array(3*r),this.hang=new Float32Array(3*r),this.nb=Math.max(1,t.follow?.bones?.length??1),this.fw=Float32Array.from(t.follow?.w??[]),this.downs=new Float64Array(3*this.nb),this.sdf=Ef(t.sdf),this.faceBox=t.face_box.slice(0,5);let i=e.C0,a=t.ear_y;for(let e=0;e<n;e++){let n=Math.max(1,t.pins[e]);for(let t=0;t<ef;t++){let r=e*ef+t,o=i[3*r],s=i[3*r+1],c=i[3*r+2],l=t<n;this.pin[r]=+!!l,this.k[r]=tf/Math.max(this.arcFree[r],nf);let u=Df(this.sdf,o,s,c);this.sdf0[r]=u,this.clr[r]=Math.min(af,u),this.fly[r]=+(!l&&s>a&&u>rf),this.onHead[r]=!l&&s>a?Math.max(u,1e-4):0,this.boxD0[r]=wf(this.faceBox,o,s,c)[0]}}this.X.set(i),this.Xp.set(i),this.hang.set(i)}reset(e){this.X.set(e.subarray(0,3*this.n)),this.Xp.set(e.subarray(0,3*this.n)),this.Tp.set(e.subarray(0,3*this.n)),this.tpOk=!0,this.hang.set(e.subarray(0,3*this.n))}carry(e){for(let t of[this.X,this.Xp,this.Tp])for(let n=0;n<t.length;n+=3){let r=t[n],i=t[n+1],a=t[n+2];t[n]=e[0]*r+e[4]*i+e[8]*a+e[12],t[n+1]=e[1]*r+e[5]*i+e[9]*a+e[13],t[n+2]=e[2]*r+e[6]*i+e[10]*a+e[14]}}step(e,t,n){let{X:r,Xp:i,Tp:a,pin:o,k:s,L1:c,L2:l,n:u}=this,d=t.targets;this.tpOk||=(a.set(d.subarray(0,3*u)),!0);let f=n.damping,p=e*e,m=n.stiffness,h=n.bend,g=n.flySoft;if(g&&this.flyKey!==n.flyArc){this.flyKey=n.flyArc;for(let e=0;e<u;e++)this.kFly[e]=tf/Math.max(this.arcFree[e],n.flyArc)}for(let e=0;e<u;e++){let t=e%ef,n=3*e;c[e]=t>0?Math.hypot(d[n]-d[n-3],d[n+1]-d[n-2],d[n+2]-d[n-1]):0,l[e]=t>1?Math.hypot(d[n]-d[n-6],d[n+1]-d[n-5],d[n+2]-d[n-4]):0}let _=this.hang;this.colliders(t,n),this.gravity(t,n);for(let e=0;e<u;e++){let t=3*e;if(o[e]){r[t]=i[t]=d[t],r[t+1]=i[t+1]=d[t+1],r[t+2]=i[t+2]=d[t+2];continue}let n=(g&&this.fly[e]?this.kFly[e]:s[e])*m*p;for(let e=0;e<3;e++){let o=r[t+e],s=d[t+e]-a[t+e],c=o+(o-i[t+e]-s)*(1-f)+s-n*(o-a[t+e]-(_[t+e]-d[t+e]));i[t+e]=o,r[t+e]=c}}let v=n.rootDeg>0;v&&this.limits(n);for(let e=0;e<n.iterations;e++)for(let e=0;e<u;e+=ef)for(let t=1;t<ef;t++)if(this.dist(e+t-1,e+t,c[e+t],1),t>1){let n=v&&!(g&&this.fly[e+t])?this.kb2[e+t]:h;n>0&&this.dist(e+t-2,e+t,l[e+t],n)}v&&this.angleLimit(_,g),this.collide(),n.tether&&this.tether(_,n,Yo(t.head)),this.clampLengths(),a.set(d.subarray(0,3*u))}gravity(e,t){let{hang:n,pin:r,arcFree:i,fw:a,downs:o,onHead:s,n:c}=this,l=e.targets,u=e.follow&&e.follow.length===this.nb?e.follow:null,d=u?this.nb:1;for(let t=0;t<d;t++){let n=u?u[t]:e.head,r=-n[4],i=-n[5],a=-n[6],s=Math.hypot(r,i,a)||1;o[3*t]=r/s,o[3*t+1]=i/s,o[3*t+2]=a/s}let f=t.stiffness>.001?t.stiffness:.001,p=1,m=0,h=!0;for(let e=0;e<c;e++){let c=3*e,g=e%ef;g===0&&(m=0,h=!0,p=1),n[c]=l[c],n[c+1]=l[c+1],n[c+2]=l[c+2],r[e]||h&&s[e]>0&&s[e]<t.headClr?m=i[e]:h=!1;let _=r[e]?0:(i[e]-m)/f;if(_>0){let t=0,r=0,i=0;if(u){for(let n=0;n<d;n++){let s=a[e*d+n];s&&(t+=s*o[3*n],r+=s*o[3*n+1],i+=s*o[3*n+2])}let n=Math.hypot(t,r,i)||1;t/=n,r/=n,i/=n}else t=o[0],r=o[1],i=o[2];let s=hf(-r);if(t=-s*t,r=s*(-1-r),i=-s*i,Math.abs(t)>=1e-6||Math.abs(r)>=1e-6||Math.abs(i)>=1e-6){let a=_*Math.hypot(t,r,i);if(a>=sf){let o=Math.min(lf,Math.ceil(a/cf)),s=1;for(;s<=o&&s/o<=p;s++){let a=_*s/o;if(n[c]=l[c]+a*t,n[c+1]=l[c+1]+a*r,n[c+2]=l[c+2]+a*i,!this.clearOf(e,n))break}p=Math.min(p,(s-1)/o)}n[c]=l[c]+_*t,n[c+1]=l[c+1]+_*r,n[c+2]=l[c+2]+_*i}}if(g===ef-1)for(let t=e-(ef-1);t<=e;t++){let e=3*t,r=l[e],i=l[e+1],a=l[e+2];n[e]===r&&n[e+1]===i&&n[e+2]===a||(p<1&&(n[e]=r+p*(n[e]-r),n[e+1]=i+p*(n[e+1]-i),n[e+2]=a+p*(n[e+2]-a)),Math.hypot(n[e]-r,n[e+1]-i,n[e+2]-a)>=sf&&this.pushRow(t,!0,2,n))}}}clearOf(e,t){let n=this.col;if(!n)return!0;let{inv:r,local:i,fac:a}=n,o=3*e,s=i.length,c=t[o],l=t[o+1],u=t[o+2],d=[r[0]*c+r[4]*l+r[8]*u+r[12],r[1]*c+r[5]*l+r[9]*u+r[13],r[2]*c+r[6]*l+r[10]*u+r[14]];if(Df(this.sdf,d[0],d[1],d[2],this.g)<this.clr[e]-uf)return!1;for(let t=0;t<s;t++)if(Tf(d,i[t].a,i[t].b)<i[t].r*a[e*s+t]-uf)return!1;return!0}clampLengths(){let{X:e,pin:t,L1:n,n:r}=this;for(let i=0;i<r;i+=ef)for(let r=1;r<ef;r++){let a=i+r;if(t[a])continue;let o=3*a,s=o-3,c=n[a]*gf,l=e[o]-e[s],u=e[o+1]-e[s+1],d=e[o+2]-e[s+2],f=Math.hypot(l,u,d);if(f<=c)continue;let p=c/f;e[o]=e[s]+l*p,e[o+1]=e[s+1]+u*p,e[o+2]=e[s+2]+d*p,this.pushRow(a);let m=e[o]-e[s],h=e[o+1]-e[s+1],g=e[o+2]-e[s+2],_=Math.hypot(m,h,g);if(_<=c)continue;let v=c/_;e[o]=e[s]+m*v,e[o+1]=e[s+1]+h*v,e[o+2]=e[s+2]+g*v,this.pushRow(a,!1,2)}}rebuild(e,t,n){let r=this.binding,i=this.X,a=this.Cl,o=this.frames,s=r.off,c=r.noff,l=e;for(let e=0;e<i.length;e+=3){let t=i[e],n=i[e+1],r=i[e+2];a[e]=l[0]*t+l[4]*n+l[8]*r+l[12],a[e+1]=l[1]*t+l[5]*n+l[9]*r+l[13],a[e+2]=l[2]*t+l[6]*n+l[10]*r+l[14]}for(let e of r.rigid)for(let i=0;i<3;i++)t[3*e+i]=r.pos0[3*e+i],n[3*e+i]=r.nrm0[3*e+i];for(let e=0;e<r.S;e++){let i=e*ef*3;Cf(a,i,o,r.N00[3*e],r.N00[3*e+1],r.N00[3*e+2]);for(let l=r.cStart[e];l<r.cStart[e+1];l++){let e=r.cVerts[l],u=r.va[e],d=r.vt[e],f=i+3*u,p=9*u,m=6*e;for(let r=0;r<3;r++){let i=a[f+r]+s[m]*o[p+r]+s[m+1]*o[p+3+r]+s[m+2]*o[p+6+r],l=c[m]*o[p+r]+c[m+1]*o[p+3+r]+c[m+2]*o[p+6+r];if(d){let e=f+3,t=p+9,n=m+3,u=a[e+r]+s[n]*o[t+r]+s[n+1]*o[t+3+r]+s[n+2]*o[t+6+r],h=c[n]*o[t+r]+c[n+1]*o[t+3+r]+c[n+2]*o[t+6+r];i+=d*(u-i),l+=d*(h-l)}t[3*e+r]=i,n[3*e+r]=l}}}}limits(e){let t=`${e.rootDeg}:${e.rootFrac}:${e.bend}`;if(t!==this.limKey){this.limKey=t;for(let t=0;t<this.n;t++){let n=this.f[t],r=n<=e.rootFrac?e.rootDeg:e.rootDeg+(180-e.rootDeg)*(n-e.rootFrac)/(1-e.rootFrac);this.cosLim[t]=Math.cos(Math.min(180,r)*Math.PI/180);let i=Math.max(0,1-n/.5);this.kb2[t]=e.bend+(1-e.bend)*i*i}}}dist(e,t,n,r){let i=this.X,a=+!this.pin[e],o=+!this.pin[t],s=a+o;if(!s)return;let c=3*e,l=3*t,u=i[l]-i[c],d=i[l+1]-i[c+1],f=i[l+2]-i[c+2],p=Math.hypot(u,d,f);if(p<1e-9)return;let m=r*(p-n)/(p*s);i[c]+=a*m*u,i[c+1]+=a*m*d,i[c+2]+=a*m*f,i[l]-=o*m*u,i[l+1]-=o*m*d,i[l+2]-=o*m*f}angleLimit(e,t){let{X:n,pin:r,cosLim:i,n:a}=this;for(let o=0;o<a;o+=ef){let a=0,s=0,c=0;for(let l=1;l<ef;l++){let u=o+l,d=3*u,f=d-3;r[u]||(n[d]+=a,n[d+1]+=s,n[d+2]+=c,!(i[u]<=-.999||t&&this.fly[u])&&Mf(n[f],n[f+1],n[f+2],n[d],n[d+1],n[d+2],e[d]-e[f],e[d+1]-e[f+1],e[d+2]-e[f+2],i[u])&&(a+=jf[0]-n[d],s+=jf[1]-n[d+1],c+=jf[2]-n[d+2],n[d]=jf[0],n[d+1]=jf[1],n[d+2]=jf[2]))}}}factors(e,t){let n=e.map(e=>e.bind);if(n.length===this.capKey.length&&n.every((e,t)=>e===this.capKey[t]))return this.capFactors;let r=e.length,i=this.binding.C0,a=new Float32Array(this.n*r).fill(1),o=e.map((e,n)=>e.bind?{a:e.bind.a,b:e.bind.b,r:t[n].r}:null),s=o.filter(e=>e!==null),c=o.map((e,t)=>e?t:-1).filter(e=>e>=0);if(s.length)for(let e=0;e<this.n;e++){let t=Sd([i[3*e],i[3*e+1],i[3*e+2]],s);for(let n=0;n<c.length;n++)a[e*r+c[n]]=t[n]}return this.capKey=n,this.capFactors=a,a}col=null;colliders(e,t){let n=e.head,r=bf(n),i=e.capsules??[],a=i.map(e=>td(e,r)),o=i.length?this.factors(i,a):this.capFactors,s=a.map(e=>({a:e.a,b:e.b,r:e.r}));this.col={m:n,inv:r,local:a,fac:o,scratch:s,box:t.faceBox}}collide(){let{pin:e,n:t}=this;for(let n=0;n<t;n++)e[n]||this.pushRow(n)}pushRow(e,t=!0,n=1,r=this.X){let i=this.col;if(!i)return;let{clr:a,g:o,sdf:s,L1:c}=this,{m:l,inv:u,local:d,fac:f,scratch:p}=i,m=d.length,h=this.faceBox,g=this.boxD0,_=e=>{let t=r[e],n=r[e+1],i=r[e+2];return[u[0]*t+u[4]*n+u[8]*i+u[12],u[1]*t+u[5]*n+u[9]*i+u[13],u[2]*t+u[6]*n+u[10]*i+u[14]]},v=3*e,[y,b,x]=_(v),S=_(v-3),C=r===this.X?c[e]*gf:1/0,w=y,T=b,E=x,D=()=>{let t=Df(s,w,T,E,o);if(t>=a[e])return;let n=Math.hypot(o[0],o[1],o[2]);if(n<1e-9)return;let r=(a[e]-t)/n;w+=o[0]*r,T+=o[1]*r,E+=o[2]*r};for(let e=0;e<n;e++)D();let O=w,k=T,ee=E;if(m&&t){let t=!1,n=[w,T,E];for(let r=0;r<m;r++){let i=d[r].r*f[e*m+r];Tf(n,d[r].a,d[r].b)<i?(t=!0,p[r].r=Math.min(i,Tf(S,d[r].a,d[r].b)+C)):p[r].r=i}if(t){let e=ed(n,p,1);w=e[0],T=e[1],E=e[2]}}if(i.box&&t){let[t,n]=wf(h,w,T,E),r=n>=0&&t>g[e]?Math.max(g[e],wf(h,S[0],S[1],S[2])[0]-C):g[e];if(n>=0&&t>r){let e=t-r;n===0?w-=e:n===1?w+=e:T+=e}}if((w!==O||T!==k||E!==ee)&&D(),w===y&&T===b&&E===x)return;let A=w-y,te=T-b,j=E-x;r[v]+=l[0]*A+l[4]*te+l[8]*j,r[v+1]+=l[1]*A+l[5]*te+l[9]*j,r[v+2]+=l[2]*A+l[6]*te+l[10]*j}tether(e,t,n){let{X:r,pin:i,f:a,onHead:o,n:s}=this,c=t.tetherR0,l=t.tetherR1;for(let u=0;u<s;u+=ef){let s=t.tetherHead>0;for(let d=1;d<ef;d++){let f=u+d;if(i[f]||(s=s&&o[f]>0&&o[f]<t.headClr,t.flySoft&&this.fly[f]))continue;let p=a[f]<=1/3,m=s;if(!p&&!m)continue;let h=3*f,g=e[h],_=e[h+1],v=e[h+2],y=r[h]-g,b=r[h+1]-_,x=r[h+2]-v,S=Math.hypot(y,b,x),C=Math.min(p?c+(l-c)*3*a[f]:1/0,m?t.tetherHead:1/0)*n;if(S<=C)continue;let w=C/S;r[h]=g+y*w,r[h+1]=_+b*w,r[h+2]=v+x*w,this.pushRow(f)}}}};function Ff(e){let t=Array(16).fill(0);for(let n=0;n<3;n++){let r=Math.hypot(e[4*n],e[4*n+1],e[4*n+2])||1;t[4*n]=e[4*n]/r,t[4*n+1]=e[4*n+1]/r,t[4*n+2]=e[4*n+2]/r}return t[12]=e[12],t[13]=e[13],t[14]=e[14],t[15]=1,t}function If(e,t){let n=Array(16);for(let r=0;r<4;r++)for(let i=0;i<4;i++)n[4*r+i]=e[i]*t[4*r]+e[4+i]*t[4*r+1]+e[8+i]*t[4*r+2]+e[12+i]*t[4*r+3];return n}function Lf(e){let t=e[0]+e[5]+e[10],n=Math.acos(Math.max(-1,Math.min(1,(t-1)/2)));if(n<1e-9)return[0,0,0];let r=e[6]-e[9],i=e[8]-e[2],a=e[1]-e[4],o=Math.hypot(r,i,a);if(o<1e-6){r=Math.sqrt(Math.max(0,(e[0]+1)/2)),i=Math.sqrt(Math.max(0,(e[5]+1)/2)),a=Math.sqrt(Math.max(0,(e[10]+1)/2)),r>=i&&r>=a?(i=Math.sign(e[1]+e[4])*i||i,a=Math.sign(e[2]+e[8])*a||a):i>=a?(r=Math.sign(e[1]+e[4])*r||r,a=Math.sign(e[6]+e[9])*a||a):(r=Math.sign(e[2]+e[8])*r||r,i=Math.sign(e[6]+e[9])*i||i);let t=Math.hypot(r,i,a)||1;return[r/t*n,i/t*n,a/t*n]}return[r/o*n,i/o*n,a/o*n]}function Rf(e,t){let n=Math.hypot(e[0],e[1],e[2]),r=[1,0,0,0,0,1,0,0,0,0,1,0,t[0],t[1],t[2],1];if(n<1e-12)return r;let i=e[0]/n,a=e[1]/n,o=e[2]/n,s=Math.cos(n),c=Math.sin(n),l=1-s;return r[0]=s+i*i*l,r[1]=a*i*l+o*c,r[2]=o*i*l-a*c,r[4]=i*a*l-o*c,r[5]=s+a*a*l,r[6]=o*a*l+i*c,r[8]=i*o*l+a*c,r[9]=a*o*l-i*c,r[10]=s+o*o*l,r}function zf(e){let t=[e[0],e[4],e[8],0,e[1],e[5],e[9],0,e[2],e[6],e[10],0,0,0,0,1];return t[12]=-(t[0]*e[12]+t[4]*e[13]+t[8]*e[14]),t[13]=-(t[1]*e[12]+t[5]*e[13]+t[9]*e[14]),t[14]=-(t[2]*e[12]+t[6]*e[13]+t[10]*e[14]),t}var Bf=(e,t,n)=>{let r=t[0]-e[0],i=t[1]-e[1],a=t[2]-e[2],o=Math.hypot(r,i,a),s=o>n?n/o:1;return[e[0]+r*s,e[1]+i*s,e[2]+a*s]},Vf=class{limits;prev=null;v=[0,0,0];w=[0,0,0];fresh=!0;constructor(e=_f){this.limits=e}reset(){this.prev=null,this.fresh=!0,this.v=[0,0,0],this.w=[0,0,0]}update(e,t){let n=Ff(e),r=this.prev;if(this.prev=n,!r||!(t>0))return null;let i=If(zf(r),n),a=Lf(i),o=[i[12]/t,i[13]/t,i[14]/t],s=[a[0]/t,a[1]/t,a[2]/t];return this.fresh?(this.fresh=!1,this.v=o):this.v=Bf(this.v,o,this.limits.accel*t),this.w=Bf(this.w,s,this.limits.angAccel*t),If(If(n,zf(Rf([this.w[0]*t,this.w[1]*t,this.w[2]*t],[this.v[0]*t,this.v[1]*t,this.v[2]*t]))),zf(r))}},Hf={maxFigures:2,cutoffM:8,leaveM:9,budgetMs:8};function Uf(e,t=Hf){let n=e.filter(e=>e.distance<=(e.running?t.leaveM:t.cutoffM)).sort((e,t)=>e.distance-t.distance||(e.name<t.name?-1:+(e.name>t.name))),r=new Set,i=0;for(let e of n){if(r.size&&(r.size+1>t.maxFigures||i+e.costMs>t.budgetMs))break;r.add(e.name),i+=e.costMs}return r}var Wf=1/60,Gf=.015,Kf=.1,qf=`head`;function Jf(e,t){let n=(t.vertex_attributes?.card??`_STRAND_CARD`).toLowerCase(),r=(t.vertex_attributes?.u??`_STRAND_U`).toLowerCase(),i=null;return e.traverse(e=>{let t=e;i||!t.isSkinnedMesh||!t.geometry||t.geometry.getAttribute(n)&&t.geometry.getAttribute(r)&&(i=t)}),i}function Yf(e,t,n=e.itemSize){let r=new t(e.count*n);for(let t=0;t<e.count;t++)r[t*n]=e.getX(t),n>1&&(r[t*n+1]=e.getY(t)),n>2&&(r[t*n+2]=e.getZ(t));return r}function Xf(e,t,n){let r=Jf(t,n);if(!r)return null;let i=r.geometry,a=r.skeleton.bones,o=e=>{let t=Z(e);return a.findIndex(e=>Z(e.name)===t)},s=o(n.head_bone),c=(n.follow?.bones??[]).map(o);if(s<0||!c.length||c.some(e=>e<0))return null;let l=n.vertex_attributes??{card:`_STRAND_CARD`,u:`_STRAND_U`},u=i.getAttribute(`position`),d=i.getAttribute(`normal`);if(!u||!d)return null;let f=Yf(u,Float32Array,3),p=Yf(d,Float32Array,3),m;try{m=new Pf(Of(n,f,p,Yf(i.getAttribute(l.card.toLowerCase()),Uint16Array,1),Yf(i.getAttribute(l.u.toLowerCase()),Float32Array,1)),n)}catch(e){if(e instanceof yf)return null;throw e}let h=vf(n.params),g={...h},_=Nf(n).filter(e=>e.region!==qf),v=_.length?es(e,t,{version:8,capsules:_}):null,y=new e.Matrix4().copy(r.bindMatrix).invert().elements,b=(v?.capsules??[]).map(e=>{let t=td(e.bind,y);return{a:t.a,b:t.b}}),x=b.map(e=>({a:[0,0,0],b:[0,0,0],r:0,bind:e})),S=Math.max(0,Math.min(8,16-x.length)),C=Array.from({length:S},()=>({a:[0,0,0],b:[0,0,0],r:0})),w=[...C,...x],T=[],E=(()=>{let e=[1/0,1/0,1/0],t=[-1/0,-1/0,-1/0];for(let r=0;r+2<n.rest.length;r+=3)for(let i=0;i<3;i++)e[i]=Math.min(e[i],n.rest[r+i]),t[i]=Math.max(t[i],n.rest[r+i]);return e[0]<=t[0]?[(e[0]+t[0])/2,(e[1]+t[1])/2,(e[2]+t[2])/2]:[0,0,0]})(),D=()=>{if(!T.length||!S)return x;let e=au({c:Jo(j,E),r:0},T,S);return C.forEach((t,n)=>{let r=n<e.length?T[e[n]]:null;for(let e=0;e<3;e++)t.a[e]=r?r.a[e]:0,t.b[e]=r?r.b[e]:0;t.r=r?r.r:0}),w},O=()=>Array(16).fill(0),k=new Float32Array(m.n*3),ee=c.map(O),A=c.map(O),te=c.map(O),j=O(),M=O(),N=O(),ne=()=>b.map(()=>({a:[0,0,0],b:[0,0,0],r:0})),P=ne(),re=ne(),ie=(e,t)=>{for(let n=0;n<16;n++)t[n]=e[n]},ae=e=>Xo(r.matrixWorld.elements,r.bindMatrixInverse.elements,a[e].matrixWorld.elements,r.skeleton.boneInverses[e].elements,r.bindMatrix.elements).bindToWorld,oe=()=>{c.forEach((e,t)=>ie(ae(e),ee[t])),ie(ae(s),j),v&&(v.update(),v.capsules.forEach((e,t)=>{let n=P[t];for(let t=0;t<3;t++)n.a[t]=e.now.a[t],n.b[t]=e.now.b[t];n.r=e.now.r}))},F=e=>{let t=e>=.999999999?1:e;c.forEach((e,n)=>Sf(A[n],ee[n],t,te[n])),Sf(M,j,t,N),Af(n,te,k),x.forEach((e,n)=>{let r=re[n],i=P[n];for(let n=0;n<3;n++)e.a[n]=r.a[n]+(i.a[n]-r.a[n])*t,e.b[n]=r.b[n]+(i.b[n]-r.b[n])*t;e.r=r.r+(i.r-r.r)*t})},I=()=>{c.forEach((e,t)=>ie(ee[t],A[t])),ie(j,M),P.forEach((e,t)=>{let n=re[t];for(let t=0;t<3;t++)n.a[t]=e.a[t],n.b[t]=e.b[t];n.r=e.r})},L=(e,t,n=0)=>{let r=t[n],i=t[n+1],a=t[n+2];t[n]=e[0]*r+e[4]*i+e[8]*a+e[12],t[n+1]=e[1]*r+e[5]*i+e[9]*a+e[13],t[n+2]=e[2]*r+e[6]*i+e[10]*a+e[14]},R=O(),z=(e,t,n)=>{let r=R;for(let n=0;n<4;n++)for(let i=0;i<4;i++)r[4*n+i]=e[i]*t[4*n]+e[4+i]*t[4*n+1]+e[8+i]*t[4*n+2]+e[12+i]*t[4*n+3];return ie(r,n),n},se=(e,t)=>{m.carry(e);for(let t=0;t<k.length;t+=3)L(e,k,t);t&&(A.forEach(t=>z(e,t,t)),z(e,M,M),re.forEach(t=>{L(e,t.a),L(e,t.b)}))},B=()=>{c.forEach((e,t)=>ie(te[t],A[t])),ie(N,M),x.forEach((e,t)=>{let n=re[t];for(let t=0;t<3;t++)n.a[t]=e.a[t],n.b[t]=e.b[t];n.r=e.r})},ce=null,le=null,ue=null,de=0,fe=null,pe=n.cards*Gf,V=!1,H=new Vf,me=()=>{!le||!ue||(m.rebuild(bf(N),le.array,ue.array),le.needsUpdate=!0,ue.needsUpdate=!0)},he=()=>{I(),F(1),m.reset(k),de=0,H.reset(),H.update(t.matrixWorld.elements,0),me()},ge={mesh:r,sim:m,targets:k,capsuleIds:(v?.capsules??[]).map(e=>e.capsule.id),get enabled(){return ce!==null},get costMs(){return pe},setEnabled(n){if(n!==(ce!==null))if(n){let n=i.clone();le=new e.BufferAttribute(Float32Array.from(f),3),ue=new e.BufferAttribute(Float32Array.from(p),3),n.setAttribute(`position`,le),n.setAttribute(`normal`,ue);let a=n.getAttribute(`skinIndex`),o=n.getAttribute(`skinWeight`),c=m.binding.vk;for(let e=0;e<c.length;e++)c[e]<0||(a.setXYZW(e,s,0,0,0),o.setXYZW(e,1,0,0,0));a.needsUpdate=!0,o.needsUpdate=!0,ce=n,r.geometry=n,t.updateWorldMatrix(!0,!0),oe(),fe=[j[12],j[13],j[14]],he()}else r.geometry=i,ce?.dispose(),ce=null,le=null,ue=null,fe=null,de=0},setStiffness(e){g.stiffness=h.stiffness*(Number.isFinite(e)&&e>0?e:1)},setPartners(e){T=e?.length?[...e]:[]},update(e,n={}){if(!ce||n.frozen)return;let r=performance.now();oe();let i=[j[12],j[13],j[14]],a=fe?Math.hypot(i[0]-fe[0],i[1]-fe[1],i[2]-fe[2]):0;if(fe=i,!(e<=.25)||a>.5){he();return}let o=H.update(t.matrixWorld.elements,e);o&&se(o,!0);let s=Math.max(0,e),c=Math.floor((de+s)/Wf+1e-6),l=-de,u=s;c>4?(c=4,F(1-c*Wf/s),se(z(N,bf(M),O()),!1),B(),l=0,u=c*Wf,de=0):de=Math.max(0,de+s-c*Wf);let d=c?D():x;for(let e=1;e<=c;e++)F((l+e*Wf)/u),m.step(Wf,{targets:k,head:N,capsules:d,follow:te},g);if(I(),!c)return;me();let f=performance.now()-r;pe=V?pe+(f-pe)*Kf:f,V=!0},dispose(){ge.setEnabled(!1),T=[]}};return ge}var Zf=Object.freeze({raised:Object.freeze({jointDeg:15,totalDeg:35}),resting:Object.freeze({jointDeg:45,totalDeg:120})}),Qf=(e,t)=>[e[0]-t[0],e[1]-t[1],e[2]-t[2]],$f=(e,t)=>[e[0]+t[0],e[1]+t[1],e[2]+t[2]],ep=(e,t)=>[e[0]*t,e[1]*t,e[2]*t],tp=(e,t)=>e[0]*t[0]+e[1]*t[1]+e[2]*t[2],np=(e,t)=>[e[1]*t[2]-e[2]*t[1],e[2]*t[0]-e[0]*t[2],e[0]*t[1]-e[1]*t[0]],rp=e=>Math.hypot(e[0],e[1],e[2]),ip=Math.PI/180;function ap(e){let t=rp(e);if(t<1e-12)return[0,0,0,1];let n=Math.sin(t/2)/t;return[e[0]*n,e[1]*n,e[2]*n,Math.cos(t/2)]}function op(e,t){return[e[3]*t[0]+e[0]*t[3]+e[1]*t[2]-e[2]*t[1],e[3]*t[1]-e[0]*t[2]+e[1]*t[3]+e[2]*t[0],e[3]*t[2]+e[0]*t[1]-e[1]*t[0]+e[2]*t[3],e[3]*t[3]-e[0]*t[0]-e[1]*t[1]-e[2]*t[2]]}var sp=e=>[-e[0],-e[1],-e[2],e[3]];function cp(e,t){let n=op(op(e,[t[0],t[1],t[2],0]),sp(e));return[n[0],n[1],n[2]]}function lp(e){return 2*Math.acos(Math.min(1,Math.abs(e[3])))}function up(e,t){let n=Math.max(0,Math.min(1,Number.isFinite(t)?t:0)),r=t=>(e.resting[t]??0)+((e.raised[t]??0)-(e.resting[t]??0))*n;return{jointDeg:r(`jointDeg`),totalDeg:r(`totalDeg`)}}function dp(e){let t=[];for(let n=Math.max(1,e-3);n<=e-1;n++)t.push(n);return t}function fp(e,t,n,r,i={}){let a=e.map(e=>[e[0],e[1],e[2]]),o=a.length-1,s=i.joints??dp(o),c=s.map(()=>[0,0,0,1]),l=Math.max(0,r.jointDeg)*ip,u=Math.max(0,r.totalDeg)*ip,d=()=>c.reduce((e,t)=>e+lp(t),0),f=e=>$f(t,ep(n,tp(Qf(e,t),n))),p=!!i.channel&&o>=1&&tp(Qf(a[o],t),n)>=-.03;if(o>=1&&l>0&&u>0)for(let e=0;e<(i.sweeps??8);e++)for(let e=s.length-1;e>=0;e--){let r=s[e],i=a[r],m=[o];if(p)for(let e=r+1;e<o;e++)(e===o-1||tp(Qf(a[e],t),n)>0)&&m.push(e);let h=[0,0,0];for(let e of m){let t=Qf(a[e],i),n=Qf(f(a[e]),i),r=rp(t),o=rp(n);if(r<1e-9||o<1e-9)continue;let s=np(t,n),c=rp(s);if(c<1e-12)continue;let l=Math.atan2(c,tp(t,n));h=$f(h,ep(s,l/c/m.length))}if(rp(h)<1e-9)continue;let g=d()-lp(c[e]),_=t=>{let n=ap(ep(h,t)),r=lp(op(n,c[e]));return r<=l+1e-9&&g+r<=u+1e-9?n:null},v=_(1);if(!v){let e=0,t=1;for(let n=0;n<16;n++){let n=(e+t)/2;_(n)?e=n:t=n}v=e>0?_(e):null}if(v){for(let e=r+1;e<=o;e++)a[e]=$f(i,cp(v,Qf(a[e],i)));c[e]=op(v,c[e]);for(let t=e+1;t<s.length;t++)c[t]=op(op(v,c[t]),sp(v))}}let m=c.map(e=>lp(e)/ip),h=m.reduce((e,t)=>e+t,0),g=r.totalDeg>0&&h>=.98*r.totalDeg||m.length>0&&m.every(e=>e>=.98*r.jointDeg);return{points:a,turns:s.map((e,t)=>({joint:e,q:c[t]})),jointDeg:m,totalDeg:h,limit:r,atLimit:g}}function pp(e,t,n){let r=e.length-1;if(!n||r<1)return null;let i=(e,t)=>Number.isFinite(e)?Math.max(-t,Math.min(t,e)):0,a=i(n.pitchDeg,60)*ip,o=i(n.yawDeg,30)*ip;if(Math.abs(a)+Math.abs(o)<1e-12)return null;let s=e[0],c=op(ap(ep(t.up,-o)),ap(ep(t.side,-a)));return{q:c,points:e.map((e,t)=>t===0?[e[0],e[1],e[2]]:$f(s,cp(c,Qf(e,s))))}}function mp(e,t,n,r){let i=Qf(n,r),a=rp(i);if(a<1e-6)return null;let o=ep(i,1/a),s=Qf(t,e),c=Qf(s,ep(o,tp(s,o))),l=rp(c);return l<1e-6?null:{side:o,up:ep(c,1/l)}}function hp(e){let t=e&&typeof e==`object`?e:{},n=e=>typeof t[e]==`number`&&Number.isFinite(t[e])?t[e]:0;return{pitchDeg:n(`pitch_deg`),yawDeg:n(`yaw_deg`)}}function gp(e,t=Zf){let n=(e,t)=>{let n=e&&typeof e==`object`?e:{},r=(e,t)=>typeof n[e]==`number`&&Number.isFinite(n[e])?n[e]:t;return{jointDeg:r(`joint_deg`,t.jointDeg),totalDeg:r(`total_deg`,t.totalDeg)}},r=e&&typeof e==`object`?e:{};return{raised:n(r.raised,t.raised),resting:n(r.resting,t.resting)}}function _p(e,t,n){let r=[];for(let i of t){let t=0;for(let n=0;n<e.length;n++){let r=e[n],a=i.dirs[n],o=Math.max(-1,Math.min(1,r[0]*a[0]+r[1]*a[1]+r[2]*a[2]));t+=Math.acos(o)**2}r.push(Math.exp(-t/(2*n*n)))}let i=r.reduce((e,t)=>e+t,0)||1,a={};return t.forEach((e,t)=>{e.target&&(a[e.target]=(a[e.target]??0)+r[t]/i)}),a}function vp(e){let t=e;return!!t&&typeof t==`object`&&typeof t.frame==`string`&&Array.isArray(t.segments)&&t.segments.length>0&&typeof t.sigma==`number`&&t.sigma>0&&Array.isArray(t.samples)&&t.samples.length>0&&t.samples.every(e=>Array.isArray(e.dirs)&&e.dirs.length===t.segments.length)}function yp(e){let t=e;return!!t&&typeof t==`object`&&t.version===2&&Array.isArray(t.groups)&&t.groups.length>0&&t.groups.every(vp)}function bp(e,t){let n=[],r=new e.Matrix4,i=new e.Vector3;if(t.traverse(t=>{let a=t,o=a.userData?.garment?.pose_shapes;if(!a.isSkinnedMesh||!a.morphTargetInfluences||!a.morphTargetDictionary||!yp(o))return;let s=new Map;a.skeleton.bones.forEach((e,t)=>s.set(Z(e.name),{bone:e,index:t}));let c=new Map;for(let e of o.targets){let t=a.morphTargetDictionary[e];t!==void 0&&c.set(e,t)}let l=[];for(let t of o.groups){let n=s.get(Z(t.frame)),o=t.segments.map(([e,t])=>[s.get(Z(e)),s.get(Z(t))]);if(!n||o.some(([e,t])=>!e||!t))continue;let c=new e.Quaternion;r.copy(a.skeleton.boneInverses[n.index]).invert().decompose(i,c,new e.Vector3),l.push({group:t,frame:n,segments:o,bindFrame:c})}c.size&&l.length&&n.push({mesh:a,groups:l,slots:c})}),!n.length)return null;let a=new e.Quaternion,o=new e.Quaternion,s=new e.Vector3,c=new e.Vector3,l=new e.Vector3,u=new e.Vector3,d=new Set;for(let e of n)for(let t of e.groups)for(let[,e]of t.segments)d.add(e.bone);let f=null;return{get last(){return f},update(){for(let e of d)e.updateWorldMatrix(!0,!1);let e=[],t={};n.forEach((n,r)=>{let d=n.mesh.morphTargetInfluences,f=[];for(let e of n.groups){e.frame.bone.matrixWorld.decompose(i,a,u),o.copy(a).invert().premultiply(e.bindFrame);let n=[];for(let[t,r]of e.segments)s.setFromMatrixPosition(t.bone.matrixWorld),c.setFromMatrixPosition(r.bone.matrixWorld),l.subVectors(c,s).applyQuaternion(o).normalize(),n.push([l.x,l.y,l.z]);f.push(n),Object.assign(t,_p(n,e.group.samples,e.group.sigma))}for(let[e,r]of n.slots)d[r]=t[e]??0;r===0&&(e=f)}),f={features:e,influences:t}}}}var xp=class{secondary;three;root;motionNow;collisionPayload;retired;tier;bindRadius;garmentCollision;poseShapes;secondaryRev;secondaryTime=performance.now();secondaryPosition;secondaryNextPosition;frameScratch;secondaryPlaced=!1;secondaryFar;pendingSecondary=null;disposed=!1;rootAngle=null;loadStrandRecord;strand=null;strandRefused=!1;strandOn=!1;strandBlocked=!1;partnerBinding=null;partnerBoundOn=null;partnerRefused=!1;partnerChannels=null;openings=new Map;openingsOn=null;openingState=new Map;strandPartners=!1;gpuPartners=!1;constructor(e,t){this.three=e,this.root=t.root,this.motionNow=t.motion,this.collisionPayload=t.collision??null,this.retired=t.retired??(()=>!1),this.tier=t.tier,this.bindRadius=t.bindRadius,this.secondaryPosition=new e.Vector3,this.secondaryNextPosition=new e.Vector3,this.frameScratch=new e.Vector3;let n=this.motionNow();this.secondary=Id(e,this.root,n,t.template),this.secondary.setCollision(t.collision??void 0),this.secondaryRev=n?.rev;let r=this.instance;this.garmentCollision=r?dd(e,r,t.collision):null,this.poseShapes=r?bp(e,r):null,this.secondaryFar=t.tier===`low`}get instance(){return this.root.children[0]??null}reset(){this.secondary.reset(),this.secondaryPlaced=!1,this.secondaryTime=performance.now()}poseStep(e={}){let t=performance.now();this.poseShapes?.update();let n=e.realDelta??(t-this.secondaryTime)/1e3;this.secondaryTime=t;let r=this.motionNow(),i=this.strandOn?xd(r):r;this.secondaryRev!==i?.rev&&(this.secondary.configure(i),this.secondaryRev=i?.rev);let a=this.root.getWorldPosition(this.secondaryNextPosition);this.secondaryPlaced&&a.distanceTo(this.secondaryPosition)>2&&this.secondary.reset(),this.secondaryPosition.copy(a),this.secondaryPlaced=!0;let o=this.pendingSecondary;this.pendingSecondary={realDelta:(o?.realDelta??0)+n,frozen:!!e.frozen,far:e.far??this.secondaryFar}}updateSecondary(e,t=null){let n=this.pendingSecondary;return!n||(this.pendingSecondary=null,this.disposed)?!1:(this.strandOn&&this.strand&&(e.length?(this.strand.setPartners(vu(`hair`,e)),this.strandPartners=!0):this.strandPartners&&=(this.strand.setPartners(null),!1),this.root.updateMatrixWorld(!0),this.strand.update(n.realDelta,{frozen:n.frozen})),this.secondary.update(n.realDelta,{frozen:n.frozen,far:n.far,partners:e,interaction:t}),this.applyRootAngle(),!0)}setRootAngle(e){this.rootAngle=e&&(e.pitchDeg||e.yawDeg)?{pitchDeg:e.pitchDeg,yawDeg:e.yawDeg}:null}applyRootAngle(){let e=this.rootAngle;if(!e||this.disposed)return;let t=this.secondary.opChains(),n=t.findIndex(e=>e.segments.length>0&&il.includes(e.op));if(n<0)return;let r=t[n].segments,i=pp([...r.map(e=>e.a),r[r.length-1].b],this.bodyFrame(),e);i&&this.secondary.bendChain(n,[{joint:0,q:i.q}])}bodyBoneRefs={on:null,bones:new Map};bodyFrame(){let e=this.instance;if(e&&this.bodyBoneRefs.on!==e){let t=new Map,n=new Set([`hips`,`spine`,`leftupleg`,`rightupleg`]);e.traverse(e=>{let r=Z(e.name);n.has(r)&&!t.has(r)&&t.set(r,e)}),this.bodyBoneRefs={on:e,bones:t}}let t=e=>{let t=this.bodyBoneRefs.bones.get(e)?.matrixWorld.elements;return t?[t[12],t[13],t[14]]:null},n=t(`hips`),r=t(`spine`),i=t(`leftupleg`),a=t(`rightupleg`),o=n&&r&&i&&a?mp(n,r,i,a):null;if(o)return o;let s=this.root.matrixWorld.elements,c=(e,t,n)=>{let r=Math.hypot(e,t,n)||1;return[e/r,t/r,n/r]};return{side:c(s[0],s[1],s[2]),up:c(s[4],s[5],s[6])}}channelOccupants(){return this.disposed?[]:this.secondary.channelOccupants()}dropOpenings(){for(let e of this.openings.values())e?.dispose();this.openings.clear(),this.openingsOn=null}applyChannelOpenings(e,t={left:1/0}){let n=this.openingState;if(this.openingState=new Map,!e.length&&!this.openings.size)return;let r=this.instance,i=this.partnerChannels;if(!((this.disposed||this.retired()||!i||!r||this.openingsOn&&this.openingsOn!==r)&&(this.dropOpenings(),this.disposed||this.retired()||!i||!r))){this.openingsOn=r,i.update();for(let a of i.channels){let i=[];for(let t of e)if(t.channel===a.id)for(let e of t.segments)i.push({a:e.a,b:e.b,r:e.r*t.w});let o=this.openings.get(a.id);if(!i.length){o?.restore();continue}let s={channel:a.id,radius:Math.max(...i.map(e=>e.r)),segments:i.length,applied:!1,maxPush:n.get(a.id)?.maxPush??0};if(this.openingState.set(a.id,s),o===void 0){if(!(t.left>0))continue;t.left--,o=$d(this.three,r,a),this.openings.set(a.id,o)}!o||!o.changed(a,i)||!(t.left>0)||(t.left--,s.maxPush=o.apply(a,i).maxPush,s.applied=!0)}}}inspect(){let e=this.boundPartner();if(!e)return null;let t=this.partnerChannels;t?.update();let n=e=>[e[0],e[1],e[2]];return{capsules:e.capsules.map(e=>({id:e.capsule.id,region:e.capsule.region,now:{a:n(e.now.a),b:n(e.now.b),r:e.now.r}})),channels:(t?.channels??[]).map(e=>({id:e.id,o:n(e.o),u:n(e.u),r:e.r,depth:e.depth,funnel:e.funnel,coneDeg:e.coneDeg,accepts:[...e.accepts],suppress:[...e.suppress]})),chains:this.disposed?[]:this.secondary.opChains().map(e=>({op:e.op,raised:e.raised,segments:e.segments.map(e=>({a:n(e.a),b:n(e.b),r:e.r}))})),engaged:this.channelOccupants().map(e=>({partner:e.partner,channel:e.channel,w:e.w,radius:e.segments.length?Math.max(...e.segments.map(e=>e.r)):0})),openings:[...this.openingState.values()].map(e=>({...e})),targets:this.disposed?[]:this.targetsNow()}}bendChain(e,t){this.disposed||!t.length||this.secondary.bendChain(e,t)}targetBoneRefs={on:null,bones:new Map};targetsNow(){let e=this.instance;if(!e)return[];if(this.targetBoneRefs.on!==e){let t=new Map,n=new Set(ll);e.traverse(e=>{if(!e.isBone)return;let r=Z(e.name);n.has(r)&&!t.has(r)&&t.set(r,e)}),this.targetBoneRefs={on:e,bones:t}}let t={};for(let[e,n]of this.targetBoneRefs.bones){let r=n.matrixWorld.elements;if(t[e]=[r[12],r[13],r[14]],e===`head`){let e=Math.hypot(r[8],r[9],r[10])||1;t.headZ=[r[8]/e,r[9]/e,r[10]/e]}}return yl(t)}boundPartner(e=!0){if(this.disposed||this.retired())return this.partnerBinding=null,this.partnerBoundOn=null,this.partnerChannels=null,null;if(this.partnerRefused||!this.collisionPayload)return null;let t=this.instance;return t?this.partnerBoundOn!==t&&(this.partnerBinding=es(this.three,t,this.collisionPayload),this.partnerBoundOn=this.partnerBinding?t:null,this.partnerChannels=this.partnerBinding?ql(this.three,t,this.collisionPayload):null,!this.partnerBinding)?(this.partnerRefused=!0,null):(this.root.updateWorldMatrix(!0,!1),this.root.updateMatrixWorld(!0),e&&this.partnerBinding.update(),this.partnerBinding):null}frameFigure(e=``,t=[]){let n=this.collisionPayload;if(this.disposed||this.retired()||this.partnerRefused||!n||n.version!==8||!n.capsules?.length)return null;let r=this.root.getWorldPosition(this.frameScratch),i=this.secondary.reach(),a=!!this.pendingSecondary&&!this.pendingSecondary.far&&(i>0||this.strandOn||this.hasHairPush),o,s=()=>{if(o===void 0){let e=this.boundPartner();o=e?tu(e.capsules.map(e=>e.now)):null}return o};return{name:e,members:t,reader:a,lever:i,root:[r.x,r.y,r.z],bindRadius:this.bindRadius,body:s,reach:()=>{let e=s();return e?nu(e,i,this.hairSpheres()):null}}}hairSpheres(){let e=[];for(let t of this.garmentCollision?.entries??[])t.sphere&&!this.strandRuns(t.mesh)&&e.push(t.sphere);if(this.strandOn&&this.strand){let t=this.strand.targets,n=[1/0,1/0,1/0],r=[-1/0,-1/0,-1/0];for(let e=0;e+2<t.length;e+=3)for(let i=0;i<3;i++)n[i]=Math.min(n[i],t[e+i]),r[i]=Math.max(r[i],t[e+i]);if(n[0]<=r[0]){let t=[(n[0]+r[0])/2,(n[1]+r[1])/2,(n[2]+r[2])/2];e.push({c:t,r:Math.hypot(r[0]-t[0],r[1]-t[1],r[2]-t[2])})}}return e}partnerSnapshot(e,t=``){let n=this.boundPartner(!1);if(!n)return null;let r=Tu(t,n,e),i=this.partnerChannels;return i?(i.update(),{...r,channels:[...i.channels]}):r}strandRuns(e){return this.strandOn&&!!this.strand&&this.strand.mesh===e}get hasHairPush(){return!!this.garmentCollision?.entries.some(e=>e.kind===`hair`&&!this.strandRuns(e.mesh))}setGpuPartners(e){let t=!!e?.length;!t&&!this.gpuPartners||(this.gpuPartners=t,this.garmentCollision?.setPartners(t?e:null))}get strandHair(){return this.strand}get strandRunning(){return this.strandOn}get strandCostMs(){return this.strand?.costMs??Hf.budgetMs}prepareStrandHair(){if(this.strand)return!0;if(this.strandRefused||this.tier!==`full`||!this.loadStrandRecord)return!1;let e=this.loadStrandRecord();if(e===void 0)return!1;let t=this.instance,n=e&&t?Xf(this.three,t,e):null;return n?(this.strand=n,!0):(this.strandRefused=!0,e&&console.warn(`[figures] ${e.item_id}: the hair mesh does not carry the strand binding of record ${e.fit_sha256.slice(0,12)} — the hair stays on its chains`),!1)}setStrandBlocked(e){this.strandBlocked=e,e&&this.setStrandHair(!1)}setStrandHair(e){let t=e&&!!this.strand&&!this.strandBlocked;t===this.strandOn||!this.strand||(this.strandOn=t,this.strand.setEnabled(t),this.garmentCollision?.excludeMesh(this.strand.mesh,t))}dispose(){this.disposed=!0,this.dropOpenings(),this.pendingSecondary=null,this.partnerBinding=null,this.partnerBoundOn=null,this.partnerChannels=null,this.secondary.dispose(),this.strand?.dispose(),this.strand=null,this.strandOn=!1,this.garmentCollision?.dispose(),this.garmentCollision=null}};function Sp(e,t){return new xp(e,t)}var Cp=Object.freeze({bandM:.04,floatM:.015,sinkM:.01,weight:300,turnCostM:.15,edgeM:.002}),wp=[`left_thigh`,`left_shin`,`right_thigh`,`right_shin`,`hips`,`spine`,`chest`,`outer_hips`,`outer_waist`,`outer_spine`,`outer_chest`,`left_upper_arm`,`right_upper_arm`,`left_forearm`,`right_forearm`,`head`],Tp=Object.freeze({stand:3,lie:5});function Ep(e,t){let n=e?Tp[e]:void 0;return n===void 0?t:Math.min(t,n)}function Dp(e,t={}){let n=t.map??(e=>[e[0],e[1],e[2]]),r=e.filter(e=>wp.includes(e.id)).map(e=>{let t=n(e.now.a),r=n(e.now.b);return{id:e.id,a:t,b:r,r:e.now.r,low:Math.min(t[1],r[1])-e.now.r}});if(!r.length)return null;let i=t.ids?r.filter(e=>t.ids.includes(e.id)):[];if(!i.length){let e=Math.min(...r.map(e=>e.low));i=r.filter(t=>t.low<=e+Cp.bandM)}return{ids:i.map(e=>e.id),pts:i.flatMap(e=>[e.a,e.b]),r:i.flatMap(e=>[e.r,e.r]),...t.surface===void 0?{}:{surface:t.surface}}}function Op(e,t){let n=1/0;for(let r=0;r<e.length;r++)n=Math.min(n,e[r][1]-t[r]);return n}function kp(e){return e>Cp.floatM?e-Cp.floatM:e<-Cp.sinkM?e+Cp.sinkM:0}var Ap=.05;Object.freeze({maxShiftM:.5,maxAngleDeg:20});var jp=Object.freeze({maxShiftM:.05,maxAngleDeg:10}),Mp=Object.freeze({maxM:.02,gain:.8,nearM:.03,decay:.9,bins:24}),Np=Object.freeze({shift:[0,0,0],turn:[0,0,0]}),Pp=(e,t)=>[e[0]-t[0],e[1]-t[1],e[2]-t[2]],Fp=(e,t)=>[e[0]+t[0],e[1]+t[1],e[2]+t[2]],Ip=(e,t)=>[e[0]*t,e[1]*t,e[2]*t],Lp=(e,t)=>e[0]*t[0]+e[1]*t[1]+e[2]*t[2],Rp=e=>Math.hypot(e[0],e[1],e[2]),zp=(e,t)=>Pp(e,Ip(t,Lp(e,t))),Bp=(e,t)=>Math.max(-t,Math.min(t,e));function Vp(e){let t=Rp(e);if(t<1e-12)return[1,0,0,0,1,0,0,0,1];let[n,r,i]=Ip(e,1/t),a=Math.cos(t),o=Math.sin(t),s=1-a;return[a+n*n*s,n*r*s-i*o,n*i*s+r*o,r*n*s+i*o,a+r*r*s,r*i*s-n*o,i*n*s-r*o,i*r*s+n*o,a+i*i*s]}var Hp=(e,t)=>[e[0]*t[0]+e[1]*t[1]+e[2]*t[2],e[3]*t[0]+e[4]*t[1]+e[5]*t[2],e[6]*t[0]+e[7]*t[1]+e[8]*t[2]],Up=(e,t)=>[e[0]*t[0]+e[3]*t[1]+e[6]*t[2],e[1]*t[0]+e[4]*t[1]+e[7]*t[2],e[2]*t[0]+e[5]*t[1]+e[8]*t[2]];function Wp(e,t,n){return Fp(Fp(Hp(Vp(e.turn),Pp(n,t)),t),e.shift)}function Gp(e,t,n){return Fp(Up(Vp(e.turn),Pp(Pp(n,t),e.shift)),t)}function Kp(e,t){return{...e,tip:Wp(t,e.pivot,e.tip),base:Wp(t,e.pivot,e.base),...e.chain?{chain:e.chain.map(n=>Wp(t,e.pivot,n))}:{},...e.support?{support:{...e.support,pts:e.support.pts.map(n=>Wp(t,e.pivot,n)),base:e.support.base??Op(e.support.pts,e.support.r)}}:{}}}function qp(e,t){if(!e.support)return null;let n=e.support.base??Op(e.support.pts,e.support.r);return Op(e.support.pts.map(n=>Wp(t,e.pivot,n)),e.support.r)-n}function Jp(e,t){if(!e.chain||e.chain.length<2)return{sample:e,bend:null};let n=fp(e.chain,e.o,e.u,up(t,e.raised??0),{channel:!!e.channel}),r=n.points;return{sample:{...e,chain:r,tip:r[r.length-1],base:r[0]},bend:n}}function Yp(e,t){let n=Vp(e.turn),r=Vp(t.turn),i=[0,0,0,0,0,0,0,0,0];for(let e=0;e<3;e++)for(let t=0;t<3;t++)for(let a=0;a<3;a++)i[e*3+t]+=r[e*3+a]*n[a*3+t];return{shift:Fp(Hp(r,e.shift),t.shift),turn:Xp(i)}}function Xp(e){let t=Math.max(-1,Math.min(1,(e[0]+e[4]+e[8]-1)/2)),n=Math.acos(t);if(n<1e-9)return[0,0,0];let r=[e[7]-e[5],e[2]-e[6],e[3]-e[1]],i=Rp(r);return i<1e-12?[0,0,0]:Ip(r,n/i)}function Zp(e,t,n){let r=Rp(e.turn),i=r/2,a=r>1e-12?Math.sin(i)/r:.5;return{position:Wp(e,t,n),quaternion:[e.turn[0]*a,e.turn[1]*a,e.turn[2]*a,Math.cos(i)]}}function Qp(e,t,n,r,i=null,a=!1){let o=[],s=-1,c=1/0,l=e.map(e=>i?Jp(Kp(e,t),i).sample:Kp(e,t));l.forEach((e,t)=>{let n=Lp(Pp(e.tip,e.o),e.u);n<c&&(c=n,s=t)});for(let e of l){let t=zp(Pp(e.tip,e.o),e.u);o.push(t[0],t[1],t[2]);let r=i&&e.chain&&e.chain.length>=2?e.chain:null,a=r?Pp(r[r.length-1],r[r.length-2]):Pp(e.tip,e.base),s=Rp(a),c=s>0?zp(Ip(a,1/s),e.u):[0,0,0];o.push(n*c[0],n*c[1],n*c[2])}if(s>=0&&o.push(Math.sqrt(r)*c),i){let r=Ap*Math.sqrt(e.length);o.push(r*t.shift[0],r*t.shift[1],r*t.shift[2],r*n*t.turn[0],r*n*t.turn[1],r*n*t.turn[2])}if(a){for(let n of e){let e=qp(n,t);e!==null&&o.push(Cp.weight*kp(e))}let n=Cp.turnCostM*Math.sqrt(e.length);o.push(n*t.turn[0],n*t.turn[1],n*t.turn[2])}return o}function $p(e,t){let n=t.length,r=e.map((e,n)=>[...e,t[n]]);for(let e=0;e<n;e++){let t=e;for(let i=e+1;i<n;i++)Math.abs(r[i][e])>Math.abs(r[t][e])&&(t=i);if(Math.abs(r[t][e])<1e-15)return null;[r[e],r[t]]=[r[t],r[e]];for(let t=0;t<n;t++){if(t===e)continue;let i=r[t][e]/r[e][e];for(let a=e;a<=n;a++)r[t][a]-=i*r[e][a]}}return r.map((e,t)=>e[n]/e[t])}function em(e,t){if(!e.length)return Np;let n=t.angleWeightM??.02,r=(t.entryWeight??10)*e.length,i=t.axes,a=3+i.length,o=t.posture!==!1&&e.some(e=>!!e.support),s=(o?Ep(t.group,t.maxAngleDeg):t.maxAngleDeg)*Math.PI/180,c=e=>{let t=[0,0,0];return i.forEach((n,r)=>{t[0]+=n[0]*e[3+r],t[1]+=n[1]*e[3+r],t[2]+=n[2]*e[3+r]}),{shift:[e[0],e[1],e[2]],turn:t}},l=e=>e.map((e,n)=>Bp(e,n<3?t.maxShiftM:s)),u=Array(a).fill(0),d=e=>e.reduce((e,t)=>e+t*t,0),f=t.bend??null,p=Qp(e,c(u),n,r,f,o),m=d(p),h=t.iterations??20;for(let t=0;t<h;t++){let t=[];for(let i=0;i<a;i++){let a=u.slice();a[i]+=1e-6;let s=Qp(e,c(a),n,r,f,o);t.push(s.map((e,t)=>(e-p[t])/1e-6))}let i=$p(Array.from({length:a},(e,n)=>Array.from({length:a},(e,r)=>{let i=0;for(let e=0;e<p.length;e++)i+=t[n][e]*t[r][e];return i+(n===r?1e-9:0)})),Array.from({length:a},(e,n)=>{let r=0;for(let e=0;e<p.length;e++)r-=t[n][e]*p[e];return r}));if(!i)break;let s=1,h=!1;for(let t=0;t<8;t++){let t=l(u.map((e,t)=>e+s*i[t])),a=Qp(e,c(t),n,r,f,o),g=d(a);if(g<m){let e=Math.max(...t.map((e,t)=>Math.abs(e-u[t])));u=t,p=a,m=g,h=e>1e-7;break}s/=2}if(!h)break}return c(u)}function tm(e){return[[e[0],e[3],e[6]],[e[2],e[5],e[8]]]}function nm(e,t,n){let[r,i]=tm(n),a=e*Math.PI/180,o=t*Math.PI/180;return{shift:[0,0,0],turn:[r[0]*a+i[0]*o,r[1]*a+i[1]*o,r[2]*a+i[2]*o]}}function rm(e,t,n){return[e[0]+t[0]*n[0]+t[1]*n[1]+t[2]*n[2],e[1]+t[3]*n[0]+t[4]*n[1]+t[5]*n[2],e[2]+t[6]*n[0]+t[7]*n[1]+t[8]*n[2]]}function im(e=null,t=null){return{phase:`collect`,samples:[],fix:Np,follow:[0,0,0],followTable:Array.from({length:Mp.bins},()=>[0,0,0]),period:0,lastPhase:-1,armed:!1,lateralMm:[],bend:e,bendDeg:[],bendLimitDeg:0,bendAtLimit:0,group:t,supportMm:[]}}var am=(e,t)=>Math.max(0,Math.min(Mp.bins-1,Math.floor(t/(e.period||1)*Mp.bins)));function om(e,t){let n=e.phase===`fitted`&&t!==void 0&&e.period>0?e.followTable[am(e,t)]:[0,0,0];return{shift:Fp(e.fix.shift,n),turn:e.fix.turn}}function sm(e,t,n,r,i=jp,a=!0){let o=e.lastPhase>=0&&n<e.lastPhase;if(o&&(e.period=Math.max(e.period,e.lastPhase)),e.phase===`collect`){let a=om(e),s={...t,tip:Gp(a,t.pivot,t.tip),base:Gp(a,t.pivot,t.base),...t.chain?{chain:t.chain.map(e=>Gp(a,t.pivot,e))}:{},...t.support?{support:{...t.support,pts:t.support.pts.map(e=>Gp(a,t.pivot,e))}}:{}};if(o&&e.armed&&e.samples.length>=8){e.fix=em(e.samples,{...i,axes:r,bend:e.bend,group:e.group}),e.phase=`fitted`,e.lastPhase=n;return}o&&(e.armed=!0),e.armed&&e.samples.push(s)}if(e.lastPhase=n,e.phase!==`fitted`)return;let s=null;if(t.support){let r=t.support,i=om(e,n),a=r.base??Op(r.pts.map(e=>Gp(i,t.pivot,e)),r.r);s=Op(r.pts,r.r)-a,e.supportMm.push(s*1e3)}if(e.bend&&t.chain){let n=Jp(t,e.bend);t=n.sample,n.bend&&(e.bendDeg.push(n.bend.totalDeg),e.bendLimitDeg=n.bend.limit.totalDeg,n.bend.atLimit&&e.bendAtLimit++)}let c=Pp(t.tip,t.o),l=Lp(c,t.u),u=zp(c,t.u);l>=0&&e.lateralMm.push(Rp(u)*1e3);let d=am(e,n),f=e.followTable[d];if(!a){e.followTable[d]=[0,0,0],e.follow=[0,0,0];return}let p=l>=-Mp.nearM?[0,1,2].map(e=>Bp(f[e]-Mp.gain*u[e],Mp.maxM)):Ip(f,Mp.decay);s!==null&&(p[1]=Math.max(f[1]-s-Cp.sinkM,Math.min(f[1]-s+Cp.floatM,p[1]))),e.followTable[d]=p,e.follow=e.followTable[d]}function cm(e,t,n=`channel`){if(n===`none`)return null;if(cl(n)){if(!t.targets?.some(e=>e.id===n))return null;let r=e.chains.findIndex(e=>e.segments.length>0&&il.includes(e.op));return r>=0?{chain:r,channel:n}:null}let r=e=>n===`mouth`?e===ol:e!==ol;for(let n=0;n<e.chains.length;n++){let i=t.channels.find(t=>r(t.id)&&t.accepts.includes(e.chains[n].op));if(i&&e.chains[n].segments.length)return{chain:n,channel:i.id}}return null}function lm(e,t,n,r){let i=e.chains[n.chain],a=cl(n.channel)?t.targets?.find(e=>e.id===n.channel):t.channels.find(e=>e.id===n.channel);if(!i?.segments.length||!a)return null;let o=e=>[e[0],e[1],e[2]],s=o(a.u),c=Rp(s)||1,l=o(i.segments[i.segments.length-1].b),u=o(i.segments[0].a),d=[...i.segments.map(e=>o(e.a)),l],f=e.capsules?Dp(e.capsules):null;return{tip:l,base:u,o:o(a.o),u:bl(n.channel,Ip(s,1/c),l,u),pivot:r,chain:d,raised:i.raised??0,channel:!cl(n.channel),...f?{support:f}:{}}}var um=e({ACESFilmicToneMapping:()=>4,AddEquation:()=>100,AddOperation:()=>2,AdditiveAnimationBlendMode:()=>Ri,AdditiveBlending:()=>2,AgXToneMapping:()=>6,AlphaFormat:()=>Qr,AlwaysCompare:()=>519,AlwaysDepth:()=>1,AlwaysStencilFunc:()=>519,AmbientLight:()=>wi,AnimationAction:()=>yr,AnimationClip:()=>yn,AnimationLoader:()=>ii,AnimationMixer:()=>ji,AnimationObjectGroup:()=>Nn,AnimationUtils:()=>Rr,ArcCurve:()=>Gi,ArrayCamera:()=>Bn,ArrowHelper:()=>Qn,AttachedBindMode:()=>di,Audio:()=>Gr,AudioAnalyser:()=>fr,AudioContext:()=>ar,AudioListener:()=>fn,AudioLoader:()=>Qi,AxesHelper:()=>ya,BackSide:()=>1,BasicDepthPacking:()=>En,BasicShadowMap:()=>0,BatchedMesh:()=>fa,BezierInterpolant:()=>ht,Bone:()=>y,BooleanKeyframeTrack:()=>aa,Box2:()=>St,Box3:()=>j,Box3Helper:()=>E,BoxGeometry:()=>Ge,BoxHelper:()=>Mr,BufferAttribute:()=>s,BufferGeometry:()=>Er,BufferGeometryLoader:()=>Fe,ByteType:()=>Ve,Cache:()=>Ze,Camera:()=>ae,CameraHelper:()=>he,CanvasTexture:()=>ke,CapsuleGeometry:()=>lt,CatmullRomCurve3:()=>Ea,CineonToneMapping:()=>3,CircleGeometry:()=>p,ClampToEdgeWrapping:()=>Ft,Clock:()=>de,Color:()=>kt,ColorKeyframeTrack:()=>Vt,ColorManagement:()=>z,Compatibility:()=>K,CompressedArrayTexture:()=>vi,CompressedCubeTexture:()=>be,CompressedTexture:()=>$t,CompressedTextureLoader:()=>qt,ConeGeometry:()=>on,ConstantAlphaFactor:()=>213,ConstantColorFactor:()=>211,Controls:()=>rt,CubeCamera:()=>t,CubeDepthTexture:()=>Zn,CubeReflectionMapping:()=>301,CubeRefractionMapping:()=>302,CubeTexture:()=>Wi,CubeTextureLoader:()=>ri,CubeUVReflectionMapping:()=>306,CubicBezierCurve:()=>Ai,CubicBezierCurve3:()=>Tr,CubicInterpolant:()=>Tn,CullFaceBack:()=>1,CullFaceFront:()=>2,CullFaceFrontBack:()=>3,CullFaceNone:()=>0,Curve:()=>ui,CurvePath:()=>Li,CustomBlending:()=>5,CustomToneMapping:()=>5,CylinderGeometry:()=>zn,Cylindrical:()=>Wr,Data3DTexture:()=>Zi,DataArrayTexture:()=>Kn,DataTexture:()=>ir,DataTextureLoader:()=>_i,DataUtils:()=>Zr,DecrementStencilOp:()=>vr,DecrementWrapStencilOp:()=>dr,DefaultLoadingManager:()=>vn,DepthFormat:()=>ia,DepthStencilFormat:()=>Ta,DepthTexture:()=>Mn,DetachedBindMode:()=>va,DirectionalLight:()=>xt,DirectionalLightHelper:()=>T,DiscreteInterpolant:()=>da,DodecahedronGeometry:()=>Ot,DoubleSide:()=>2,DstAlphaFactor:()=>206,DstColorFactor:()=>208,DynamicCopyUsage:()=>ie,DynamicDrawUsage:()=>te,DynamicReadUsage:()=>Xe,EdgesGeometry:()=>Lr,EllipseCurve:()=>f,EqualCompare:()=>514,EqualDepth:()=>4,EqualStencilFunc:()=>514,EquirectangularReflectionMapping:()=>303,EquirectangularRefractionMapping:()=>304,Euler:()=>jr,EventDispatcher:()=>Be,ExternalTexture:()=>J,ExtrudeGeometry:()=>nt,FileLoader:()=>R,Float16BufferAttribute:()=>U,Float32BufferAttribute:()=>Pe,FloatType:()=>mt,Fog:()=>ja,FogExp2:()=>v,FramebufferTexture:()=>Bt,FrontSide:()=>0,Frustum:()=>me,FrustumArray:()=>Pt,GLBufferAttribute:()=>Kt,GLSL1:()=>`100`,GLSL3:()=>ue,GreaterCompare:()=>516,GreaterDepth:()=>6,GreaterEqualCompare:()=>518,GreaterEqualDepth:()=>5,GreaterEqualStencilFunc:()=>518,GreaterStencilFunc:()=>516,GridHelper:()=>Oe,Group:()=>Ci,HTMLTexture:()=>G,HalfFloatType:()=>an,HemisphereLight:()=>Qt,HemisphereLightHelper:()=>dn,IcosahedronGeometry:()=>ct,ImageBitmapLoader:()=>o,ImageLoader:()=>Yn,ImageUtils:()=>Vi,IncrementStencilOp:()=>ti,IncrementWrapStencilOp:()=>Di,InstancedBufferAttribute:()=>Sr,InstancedBufferGeometry:()=>Sn,InstancedInterleavedBuffer:()=>si,InstancedMesh:()=>Pi,Int16BufferAttribute:()=>In,Int32BufferAttribute:()=>Vr,Int8BufferAttribute:()=>Ji,IntType:()=>Un,InterleavedBuffer:()=>tr,InterleavedBufferAttribute:()=>mi,Interpolant:()=>Jr,InterpolateBezier:()=>hr,InterpolateDiscrete:()=>cr,InterpolateLinear:()=>hn,InterpolateSmooth:()=>ta,InterpolationSamplingMode:()=>Sa,InterpolationSamplingType:()=>kn,InvertStencilOp:()=>ha,KeepStencilOp:()=>vt,KeyframeTrack:()=>S,LOD:()=>ca,LatheGeometry:()=>Tt,Layers:()=>ne,LessCompare:()=>513,LessDepth:()=>2,LessEqualCompare:()=>515,LessEqualDepth:()=>3,LessEqualStencilFunc:()=>515,LessStencilFunc:()=>513,Light:()=>k,LightProbe:()=>Je,Line:()=>Fr,Line3:()=>u,LineBasicMaterial:()=>kr,LineCurve:()=>Re,LineCurve3:()=>q,LineDashedMaterial:()=>et,LineLoop:()=>I,LineSegments:()=>ve,LinearFilter:()=>Me,LinearInterpolant:()=>ft,LinearMipMapLinearFilter:()=>ka,LinearMipMapNearestFilter:()=>g,LinearMipmapLinearFilter:()=>Rt,LinearMipmapNearestFilter:()=>V,LinearSRGBColorSpace:()=>Mt,LinearToneMapping:()=>1,LinearTransfer:()=>Wt,Loader:()=>ce,LoaderUtils:()=>Ee,LoadingManager:()=>xi,LoopOnce:()=>W,LoopPingPong:()=>nn,LoopRepeat:()=>Xt,MOUSE:()=>ln,Material:()=>ot,MaterialBlending:()=>6,MaterialLoader:()=>i,MathUtils:()=>Xn,Matrix2:()=>Ui,Matrix3:()=>X,Matrix4:()=>ki,MaxEquation:()=>104,Mesh:()=>wr,MeshBasicMaterial:()=>wn,MeshDepthMaterial:()=>li,MeshDistanceMaterial:()=>Ii,MeshLambertMaterial:()=>Rn,MeshMatcapMaterial:()=>Ur,MeshNormalMaterial:()=>Xi,MeshPhongMaterial:()=>Gn,MeshPhysicalMaterial:()=>rr,MeshStandardMaterial:()=>gi,MeshToonMaterial:()=>Xr,MinEquation:()=>103,MirroredRepeatWrapping:()=>_r,MixOperation:()=>1,MultiplyBlending:()=>4,MultiplyOperation:()=>0,NearestFilter:()=>ur,NearestMipMapLinearFilter:()=>_n,NearestMipMapNearestFilter:()=>ra,NearestMipmapLinearFilter:()=>wa,NearestMipmapNearestFilter:()=>jn,NeutralToneMapping:()=>7,NeverCompare:()=>512,NeverDepth:()=>0,NeverStencilFunc:()=>512,NoBlending:()=>0,NoColorSpace:()=>``,NoNormalPacking:()=>``,NoToneMapping:()=>0,NormalAnimationBlendMode:()=>_a,NormalBlending:()=>1,NormalGAPacking:()=>`ga`,NormalRGPacking:()=>`rg`,NotEqualCompare:()=>517,NotEqualDepth:()=>7,NotEqualStencilFunc:()=>517,NumberKeyframeTrack:()=>bt,Object3D:()=>w,ObjectLoader:()=>ua,ObjectSpaceNormalMap:()=>1,OctahedronGeometry:()=>Dt,OneFactor:()=>201,OneMinusConstantAlphaFactor:()=>214,OneMinusConstantColorFactor:()=>212,OneMinusDstAlphaFactor:()=>207,OneMinusDstColorFactor:()=>209,OneMinusSrcAlphaFactor:()=>205,OneMinusSrcColorFactor:()=>203,OrthographicCamera:()=>re,PCFShadowMap:()=>1,PCFSoftShadowMap:()=>2,PMREMGenerator:()=>Nm,Path:()=>A,PerspectiveCamera:()=>Ye,Plane:()=>Ir,PlaneGeometry:()=>d,PlaneHelper:()=>Ar,PointLight:()=>ze,PointLightHelper:()=>We,Points:()=>tt,PointsMaterial:()=>L,PolarGridHelper:()=>ye,PolyhedronGeometry:()=>Ne,PositionalAudio:()=>pt,PropertyBinding:()=>Aa,PropertyMixer:()=>_,QuadraticBezierCurve:()=>zt,QuadraticBezierCurve3:()=>H,Quaternion:()=>Nt,QuaternionKeyframeTrack:()=>Gt,QuaternionLinearInterpolant:()=>le,R11_EAC_Format:()=>De,RED_GREEN_RGTC2_Format:()=>Ce,RED_RGTC1_Format:()=>rn,REVISION:()=>`185`,RG11_EAC_Format:()=>Zt,RGBADepthPacking:()=>un,RGBAFormat:()=>st,RGBAIntegerFormat:()=>a,RGBA_ASTC_10x10_Format:()=>Jn,RGBA_ASTC_10x5_Format:()=>Bi,RGBA_ASTC_10x6_Format:()=>ei,RGBA_ASTC_10x8_Format:()=>Ei,RGBA_ASTC_12x10_Format:()=>xr,RGBA_ASTC_12x12_Format:()=>xn,RGBA_ASTC_4x4_Format:()=>oi,RGBA_ASTC_5x4_Format:()=>Ni,RGBA_ASTC_5x5_Format:()=>Fn,RGBA_ASTC_6x5_Format:()=>Br,RGBA_ASTC_6x6_Format:()=>qi,RGBA_ASTC_8x5_Format:()=>Hn,RGBA_ASTC_8x6_Format:()=>er,RGBA_ASTC_8x8_Format:()=>pi,RGBA_BPTC_Format:()=>qr,RGBA_ETC2_EAC_Format:()=>mr,RGBA_PVRTC_2BPPV1_Format:()=>sr,RGBA_PVRTC_4BPPV1_Format:()=>mn,RGBA_S3TC_DXT1_Format:()=>ea,RGBA_S3TC_DXT3_Format:()=>xa,RGBA_S3TC_DXT5_Format:()=>On,RGBDepthPacking:()=>ma,RGBFormat:()=>_t,RGBIntegerFormat:()=>x,RGB_BPTC_SIGNED_Format:()=>sa,RGB_BPTC_UNSIGNED_Format:()=>wt,RGB_ETC1_Format:()=>N,RGB_ETC2_Format:()=>O,RGB_PVRTC_2BPPV1_Format:()=>qe,RGB_PVRTC_4BPPV1_Format:()=>Pr,RGB_S3TC_DXT1_Format:()=>l,RGDepthPacking:()=>Or,RGFormat:()=>Le,RGIntegerFormat:()=>Ue,RawShaderMaterial:()=>$e,Ray:()=>F,Raycaster:()=>_e,RectAreaLight:()=>je,RedFormat:()=>dt,RedIntegerFormat:()=>Oa,ReinhardToneMapping:()=>2,RenderTarget:()=>h,RenderTarget3D:()=>Lt,RepeatWrapping:()=>pe,ReplaceStencilOp:()=>jt,ReverseSubtractEquation:()=>102,RingGeometry:()=>B,SIGNED_R11_EAC_Format:()=>Te,SIGNED_RED_GREEN_RGTC2_Format:()=>bi,SIGNED_RED_RGTC1_Format:()=>Se,SIGNED_RG11_EAC_Format:()=>tn,SRGBColorSpace:()=>Yt,SRGBTransfer:()=>cn,Scene:()=>at,ShaderChunk:()=>Q,ShaderLib:()=>pm,ShaderMaterial:()=>r,ShadowMaterial:()=>qn,Shape:()=>zi,ShapeGeometry:()=>$r,ShapePath:()=>Ti,ShapeUtils:()=>br,ShortType:()=>bn,Skeleton:()=>ai,SkeletonHelper:()=>Mi,SkinnedMesh:()=>Pn,Source:()=>zr,Sphere:()=>Ki,SphereGeometry:()=>Vn,Spherical:()=>$n,SphericalHarmonics3:()=>fi,SplineCurve:()=>Kr,SpotLight:()=>pr,SpotLightHelper:()=>or,Sprite:()=>pn,SpriteMaterial:()=>$i,SrcAlphaFactor:()=>204,SrcAlphaSaturateFactor:()=>210,SrcColorFactor:()=>202,StaticCopyUsage:()=>ba,StaticDrawUsage:()=>Dn,StaticReadUsage:()=>pa,StereoCamera:()=>gt,StreamCopyUsage:()=>b,StreamDrawUsage:()=>oa,StreamReadUsage:()=>Ct,StringKeyframeTrack:()=>M,SubtractEquation:()=>101,SubtractiveBlending:()=>3,TOUCH:()=>D,TangentSpaceNormalMap:()=>0,TetrahedronGeometry:()=>Ke,Texture:()=>Nr,TextureLoader:()=>c,TextureUtils:()=>Dr,Timer:()=>Ie,TimestampQuery:()=>He,TorusGeometry:()=>Qe,TorusKnotGeometry:()=>oe,Triangle:()=>ge,TriangleFanDrawMode:()=>2,TriangleStripDrawMode:()=>1,TrianglesDrawMode:()=>0,TubeGeometry:()=>Ae,UVMapping:()=>300,Uint16BufferAttribute:()=>ut,Uint32BufferAttribute:()=>Da,Uint8BufferAttribute:()=>m,Uint8ClampedBufferAttribute:()=>It,Uniform:()=>fe,UniformsGroup:()=>At,UniformsLib:()=>$,UniformsUtils:()=>Ht,UnsignedByteType:()=>se,UnsignedInt101111Type:()=>we,UnsignedInt248Type:()=>yi,UnsignedInt5999Type:()=>xe,UnsignedIntType:()=>en,UnsignedShort4444Type:()=>Jt,UnsignedShort5551Type:()=>sn,UnsignedShortType:()=>it,VSMShadowMap:()=>3,Vector2:()=>n,Vector3:()=>Y,Vector4:()=>Hi,VectorKeyframeTrack:()=>ni,VideoFrameTexture:()=>Oi,VideoTexture:()=>Cr,WebGL3DRenderTarget:()=>Cn,WebGLArrayRenderTarget:()=>ci,WebGLCoordinateSystem:()=>Fi,WebGLCubeRenderTarget:()=>Hm,WebGLRenderTarget:()=>Ln,WebGLRenderer:()=>E_,WebGLUtils:()=>m_,WebGPUCoordinateSystem:()=>Hr,WebXRController:()=>Yi,WireframeGeometry:()=>Wn,WrapAroundEnding:()=>nr,ZeroCurvatureEnding:()=>hi,ZeroFactor:()=>200,ZeroSlopeEnding:()=>Yr,ZeroStencilOp:()=>0,createCanvasElement:()=>lr,error:()=>na,getConsoleFunction:()=>An,log:()=>yt,setConsoleFunction:()=>Et,warn:()=>P,warnOnce:()=>ee});function dm(){let e=null,t=!1,n=null,r=null;function i(t,a){n(t,a),r=e.requestAnimationFrame(i)}return{start:function(){t!==!0&&n!==null&&e!==null&&(r=e.requestAnimationFrame(i),t=!0)},stop:function(){e!==null&&e.cancelAnimationFrame(r),t=!1},setAnimationLoop:function(e){n=e},setContext:function(t){e=t}}}function fm(e){let t=new WeakMap;function n(t,n){let r=t.array,i=t.usage,a=r.byteLength,o=e.createBuffer();e.bindBuffer(n,o),e.bufferData(n,r,i),t.onUploadCallback();let s;if(r instanceof Float32Array)s=e.FLOAT;else if(typeof Float16Array<`u`&&r instanceof Float16Array)s=e.HALF_FLOAT;else if(r instanceof Uint16Array)s=t.isFloat16BufferAttribute?e.HALF_FLOAT:e.UNSIGNED_SHORT;else if(r instanceof Int16Array)s=e.SHORT;else if(r instanceof Uint32Array)s=e.UNSIGNED_INT;else if(r instanceof Int32Array)s=e.INT;else if(r instanceof Int8Array)s=e.BYTE;else if(r instanceof Uint8Array)s=e.UNSIGNED_BYTE;else if(r instanceof Uint8ClampedArray)s=e.UNSIGNED_BYTE;else throw Error(`THREE.WebGLAttributes: Unsupported buffer data format: `+r);return{buffer:o,type:s,bytesPerElement:r.BYTES_PER_ELEMENT,version:t.version,size:a}}function r(t,n,r){let i=n.array,a=n.updateRanges;if(e.bindBuffer(r,t),a.length===0)e.bufferSubData(r,0,i);else{a.sort((e,t)=>e.start-t.start);let t=0;for(let e=1;e<a.length;e++){let n=a[t],r=a[e];r.start<=n.start+n.count+1?n.count=Math.max(n.count,r.start+r.count-n.start):(++t,a[t]=r)}a.length=t+1;for(let t=0,n=a.length;t<n;t++){let n=a[t];e.bufferSubData(r,n.start*i.BYTES_PER_ELEMENT,i,n.start,n.count)}n.clearUpdateRanges()}n.onUploadCallback()}function i(e){return e.isInterleavedBufferAttribute&&(e=e.data),t.get(e)}function a(n){n.isInterleavedBufferAttribute&&(n=n.data);let r=t.get(n);r&&(e.deleteBuffer(r.buffer),t.delete(n))}function o(e,i){if(e.isInterleavedBufferAttribute&&(e=e.data),e.isGLBufferAttribute){let n=t.get(e);(!n||n.version<e.version)&&t.set(e,{buffer:e.buffer,type:e.type,bytesPerElement:e.elementSize,version:e.version});return}let a=t.get(e);if(a===void 0)t.set(e,n(e,i));else if(a.version<e.version){if(a.size!==e.array.byteLength)throw Error(`THREE.WebGLAttributes: The size of the buffer attribute's array buffer does not match the original size. Resizing buffer attributes is not supported.`);r(a.buffer,e,i),a.version=e.version}}return{get:i,remove:a,update:o}}var Q={alphahash_fragment:`#ifdef USE_ALPHAHASH
	if ( diffuseColor.a < getAlphaHashThreshold( vPosition ) ) discard;
#endif`,alphahash_pars_fragment:`#ifdef USE_ALPHAHASH
	const float ALPHA_HASH_SCALE = 0.05;
	float hash2D( vec2 value ) {
		return fract( 1.0e4 * sin( 17.0 * value.x + 0.1 * value.y ) * ( 0.1 + abs( sin( 13.0 * value.y + value.x ) ) ) );
	}
	float hash3D( vec3 value ) {
		return hash2D( vec2( hash2D( value.xy ), value.z ) );
	}
	float getAlphaHashThreshold( vec3 position ) {
		float maxDeriv = max(
			length( dFdx( position.xyz ) ),
			length( dFdy( position.xyz ) )
		);
		float pixScale = 1.0 / ( ALPHA_HASH_SCALE * maxDeriv );
		vec2 pixScales = vec2(
			exp2( floor( log2( pixScale ) ) ),
			exp2( ceil( log2( pixScale ) ) )
		);
		vec2 alpha = vec2(
			hash3D( floor( pixScales.x * position.xyz ) ),
			hash3D( floor( pixScales.y * position.xyz ) )
		);
		float lerpFactor = fract( log2( pixScale ) );
		float x = ( 1.0 - lerpFactor ) * alpha.x + lerpFactor * alpha.y;
		float a = min( lerpFactor, 1.0 - lerpFactor );
		vec3 cases = vec3(
			x * x / ( 2.0 * a * ( 1.0 - a ) ),
			( x - 0.5 * a ) / ( 1.0 - a ),
			1.0 - ( ( 1.0 - x ) * ( 1.0 - x ) / ( 2.0 * a * ( 1.0 - a ) ) )
		);
		float threshold = ( x < ( 1.0 - a ) )
			? ( ( x < a ) ? cases.x : cases.y )
			: cases.z;
		return clamp( threshold , 1.0e-6, 1.0 );
	}
#endif`,alphamap_fragment:`#ifdef USE_ALPHAMAP
	diffuseColor.a *= texture2D( alphaMap, vAlphaMapUv ).g;
#endif`,alphamap_pars_fragment:`#ifdef USE_ALPHAMAP
	uniform sampler2D alphaMap;
#endif`,alphatest_fragment:`#ifdef USE_ALPHATEST
	#ifdef ALPHA_TO_COVERAGE
	diffuseColor.a = smoothstep( alphaTest, alphaTest + fwidth( diffuseColor.a ), diffuseColor.a );
	if ( diffuseColor.a == 0.0 ) discard;
	#else
	if ( diffuseColor.a < alphaTest ) discard;
	#endif
#endif`,alphatest_pars_fragment:`#ifdef USE_ALPHATEST
	uniform float alphaTest;
#endif`,aomap_fragment:`#ifdef USE_AOMAP
	float ambientOcclusion = ( texture2D( aoMap, vAoMapUv ).r - 1.0 ) * aoMapIntensity + 1.0;
	reflectedLight.indirectDiffuse *= ambientOcclusion;
	#if defined( USE_CLEARCOAT ) 
		clearcoatSpecularIndirect *= ambientOcclusion;
	#endif
	#if defined( USE_SHEEN ) 
		sheenSpecularIndirect *= ambientOcclusion;
	#endif
	#if defined( USE_ENVMAP ) && defined( STANDARD )
		float dotNV = saturate( dot( geometryNormal, geometryViewDir ) );
		reflectedLight.indirectSpecular *= computeSpecularOcclusion( dotNV, ambientOcclusion, material.roughness );
	#endif
#endif`,aomap_pars_fragment:`#ifdef USE_AOMAP
	uniform sampler2D aoMap;
	uniform float aoMapIntensity;
#endif`,batching_pars_vertex:`#ifdef USE_BATCHING
	#if ! defined( GL_ANGLE_multi_draw )
	#define gl_DrawID _gl_DrawID
	uniform int _gl_DrawID;
	#endif
	uniform highp sampler2D batchingTexture;
	uniform highp usampler2D batchingIdTexture;
	mat4 getBatchingMatrix( const in float i ) {
		int size = textureSize( batchingTexture, 0 ).x;
		int j = int( i ) * 4;
		int x = j % size;
		int y = j / size;
		vec4 v1 = texelFetch( batchingTexture, ivec2( x, y ), 0 );
		vec4 v2 = texelFetch( batchingTexture, ivec2( x + 1, y ), 0 );
		vec4 v3 = texelFetch( batchingTexture, ivec2( x + 2, y ), 0 );
		vec4 v4 = texelFetch( batchingTexture, ivec2( x + 3, y ), 0 );
		return mat4( v1, v2, v3, v4 );
	}
	float getIndirectIndex( const in int i ) {
		int size = textureSize( batchingIdTexture, 0 ).x;
		int x = i % size;
		int y = i / size;
		return float( texelFetch( batchingIdTexture, ivec2( x, y ), 0 ).r );
	}
#endif
#ifdef USE_BATCHING_COLOR
	uniform sampler2D batchingColorTexture;
	vec4 getBatchingColor( const in float i ) {
		int size = textureSize( batchingColorTexture, 0 ).x;
		int j = int( i );
		int x = j % size;
		int y = j / size;
		return texelFetch( batchingColorTexture, ivec2( x, y ), 0 );
	}
#endif`,batching_vertex:`#ifdef USE_BATCHING
	mat4 batchingMatrix = getBatchingMatrix( getIndirectIndex( gl_DrawID ) );
#endif`,begin_vertex:`vec3 transformed = vec3( position );
#ifdef USE_ALPHAHASH
	vPosition = vec3( position );
#endif`,beginnormal_vertex:`vec3 objectNormal = vec3( normal );
#ifdef USE_TANGENT
	vec3 objectTangent = vec3( tangent.xyz );
#endif`,bsdfs:`float G_BlinnPhong_Implicit( ) {
	return 0.25;
}
float D_BlinnPhong( const in float shininess, const in float dotNH ) {
	return RECIPROCAL_PI * ( shininess * 0.5 + 1.0 ) * pow( dotNH, shininess );
}
vec3 BRDF_BlinnPhong( const in vec3 lightDir, const in vec3 viewDir, const in vec3 normal, const in vec3 specularColor, const in float shininess ) {
	vec3 halfDir = normalize( lightDir + viewDir );
	float dotNH = saturate( dot( normal, halfDir ) );
	float dotVH = saturate( dot( viewDir, halfDir ) );
	vec3 F = F_Schlick( specularColor, 1.0, dotVH );
	float G = G_BlinnPhong_Implicit( );
	float D = D_BlinnPhong( shininess, dotNH );
	return F * ( G * D );
} // validated`,iridescence_fragment:`#ifdef USE_IRIDESCENCE
	const mat3 XYZ_TO_REC709 = mat3(
		 3.2404542, -0.9692660,  0.0556434,
		-1.5371385,  1.8760108, -0.2040259,
		-0.4985314,  0.0415560,  1.0572252
	);
	vec3 Fresnel0ToIor( vec3 fresnel0 ) {
		vec3 sqrtF0 = sqrt( fresnel0 );
		return ( vec3( 1.0 ) + sqrtF0 ) / ( vec3( 1.0 ) - sqrtF0 );
	}
	vec3 IorToFresnel0( vec3 transmittedIor, float incidentIor ) {
		return pow2( ( transmittedIor - vec3( incidentIor ) ) / ( transmittedIor + vec3( incidentIor ) ) );
	}
	float IorToFresnel0( float transmittedIor, float incidentIor ) {
		return pow2( ( transmittedIor - incidentIor ) / ( transmittedIor + incidentIor ));
	}
	vec3 evalSensitivity( float OPD, vec3 shift ) {
		float phase = 2.0 * PI * OPD * 1.0e-9;
		vec3 val = vec3( 5.4856e-13, 4.4201e-13, 5.2481e-13 );
		vec3 pos = vec3( 1.6810e+06, 1.7953e+06, 2.2084e+06 );
		vec3 var = vec3( 4.3278e+09, 9.3046e+09, 6.6121e+09 );
		vec3 xyz = val * sqrt( 2.0 * PI * var ) * cos( pos * phase + shift ) * exp( - pow2( phase ) * var );
		xyz.x += 9.7470e-14 * sqrt( 2.0 * PI * 4.5282e+09 ) * cos( 2.2399e+06 * phase + shift[ 0 ] ) * exp( - 4.5282e+09 * pow2( phase ) );
		xyz /= 1.0685e-7;
		vec3 rgb = XYZ_TO_REC709 * xyz;
		return rgb;
	}
	vec3 evalIridescence( float outsideIOR, float eta2, float cosTheta1, float thinFilmThickness, vec3 baseF0 ) {
		vec3 I;
		float iridescenceIOR = mix( outsideIOR, eta2, smoothstep( 0.0, 0.03, thinFilmThickness ) );
		float sinTheta2Sq = pow2( outsideIOR / iridescenceIOR ) * ( 1.0 - pow2( cosTheta1 ) );
		float cosTheta2Sq = 1.0 - sinTheta2Sq;
		if ( cosTheta2Sq < 0.0 ) {
			return vec3( 1.0 );
		}
		float cosTheta2 = sqrt( cosTheta2Sq );
		float R0 = IorToFresnel0( iridescenceIOR, outsideIOR );
		float R12 = F_Schlick( R0, 1.0, cosTheta1 );
		float T121 = 1.0 - R12;
		float phi12 = 0.0;
		if ( iridescenceIOR < outsideIOR ) phi12 = PI;
		float phi21 = PI - phi12;
		vec3 baseIOR = Fresnel0ToIor( clamp( baseF0, 0.0, 0.9999 ) );		vec3 R1 = IorToFresnel0( baseIOR, iridescenceIOR );
		vec3 R23 = F_Schlick( R1, 1.0, cosTheta2 );
		vec3 phi23 = vec3( 0.0 );
		if ( baseIOR[ 0 ] < iridescenceIOR ) phi23[ 0 ] = PI;
		if ( baseIOR[ 1 ] < iridescenceIOR ) phi23[ 1 ] = PI;
		if ( baseIOR[ 2 ] < iridescenceIOR ) phi23[ 2 ] = PI;
		float OPD = 2.0 * iridescenceIOR * thinFilmThickness * cosTheta2;
		vec3 phi = vec3( phi21 ) + phi23;
		vec3 R123 = clamp( R12 * R23, 1e-5, 0.9999 );
		vec3 r123 = sqrt( R123 );
		vec3 Rs = pow2( T121 ) * R23 / ( vec3( 1.0 ) - R123 );
		vec3 C0 = R12 + Rs;
		I = C0;
		vec3 Cm = Rs - T121;
		for ( int m = 1; m <= 2; ++ m ) {
			Cm *= r123;
			vec3 Sm = 2.0 * evalSensitivity( float( m ) * OPD, float( m ) * phi );
			I += Cm * Sm;
		}
		return max( I, vec3( 0.0 ) );
	}
#endif`,bumpmap_pars_fragment:`#ifdef USE_BUMPMAP
	uniform sampler2D bumpMap;
	uniform float bumpScale;
	vec2 dHdxy_fwd() {
		vec2 dSTdx = dFdx( vBumpMapUv );
		vec2 dSTdy = dFdy( vBumpMapUv );
		float Hll = bumpScale * texture2D( bumpMap, vBumpMapUv ).x;
		float dBx = bumpScale * texture2D( bumpMap, vBumpMapUv + dSTdx ).x - Hll;
		float dBy = bumpScale * texture2D( bumpMap, vBumpMapUv + dSTdy ).x - Hll;
		return vec2( dBx, dBy );
	}
	vec3 perturbNormalArb( vec3 surf_pos, vec3 surf_norm, vec2 dHdxy, float faceDirection ) {
		vec3 vSigmaX = normalize( dFdx( surf_pos.xyz ) );
		vec3 vSigmaY = normalize( dFdy( surf_pos.xyz ) );
		vec3 vN = surf_norm;
		vec3 R1 = cross( vSigmaY, vN );
		vec3 R2 = cross( vN, vSigmaX );
		float fDet = dot( vSigmaX, R1 ) * faceDirection;
		vec3 vGrad = sign( fDet ) * ( dHdxy.x * R1 + dHdxy.y * R2 );
		return normalize( abs( fDet ) * surf_norm - vGrad );
	}
#endif`,clipping_planes_fragment:`#if NUM_CLIPPING_PLANES > 0
	vec4 plane;
	#ifdef ALPHA_TO_COVERAGE
		float distanceToPlane, distanceGradient;
		float clipOpacity = 1.0;
		#pragma unroll_loop_start
		for ( int i = 0; i < UNION_CLIPPING_PLANES; i ++ ) {
			plane = clippingPlanes[ i ];
			distanceToPlane = - dot( vClipPosition, plane.xyz ) + plane.w;
			distanceGradient = fwidth( distanceToPlane ) / 2.0;
			clipOpacity *= smoothstep( - distanceGradient, distanceGradient, distanceToPlane );
			if ( clipOpacity == 0.0 ) discard;
		}
		#pragma unroll_loop_end
		#if UNION_CLIPPING_PLANES < NUM_CLIPPING_PLANES
			float unionClipOpacity = 1.0;
			#pragma unroll_loop_start
			for ( int i = UNION_CLIPPING_PLANES; i < NUM_CLIPPING_PLANES; i ++ ) {
				plane = clippingPlanes[ i ];
				distanceToPlane = - dot( vClipPosition, plane.xyz ) + plane.w;
				distanceGradient = fwidth( distanceToPlane ) / 2.0;
				unionClipOpacity *= 1.0 - smoothstep( - distanceGradient, distanceGradient, distanceToPlane );
			}
			#pragma unroll_loop_end
			clipOpacity *= 1.0 - unionClipOpacity;
		#endif
		diffuseColor.a *= clipOpacity;
		if ( diffuseColor.a == 0.0 ) discard;
	#else
		#pragma unroll_loop_start
		for ( int i = 0; i < UNION_CLIPPING_PLANES; i ++ ) {
			plane = clippingPlanes[ i ];
			if ( dot( vClipPosition, plane.xyz ) > plane.w ) discard;
		}
		#pragma unroll_loop_end
		#if UNION_CLIPPING_PLANES < NUM_CLIPPING_PLANES
			bool clipped = true;
			#pragma unroll_loop_start
			for ( int i = UNION_CLIPPING_PLANES; i < NUM_CLIPPING_PLANES; i ++ ) {
				plane = clippingPlanes[ i ];
				clipped = ( dot( vClipPosition, plane.xyz ) > plane.w ) && clipped;
			}
			#pragma unroll_loop_end
			if ( clipped ) discard;
		#endif
	#endif
#endif`,clipping_planes_pars_fragment:`#if NUM_CLIPPING_PLANES > 0
	varying vec3 vClipPosition;
	uniform vec4 clippingPlanes[ NUM_CLIPPING_PLANES ];
#endif`,clipping_planes_pars_vertex:`#if NUM_CLIPPING_PLANES > 0
	varying vec3 vClipPosition;
#endif`,clipping_planes_vertex:`#if NUM_CLIPPING_PLANES > 0
	vClipPosition = - mvPosition.xyz;
#endif`,color_fragment:`#if defined( USE_COLOR ) || defined( USE_COLOR_ALPHA )
	diffuseColor *= vColor;
#endif`,color_pars_fragment:`#if defined( USE_COLOR ) || defined( USE_COLOR_ALPHA )
	varying vec4 vColor;
#endif`,color_pars_vertex:`#if defined( USE_COLOR ) || defined( USE_COLOR_ALPHA ) || defined( USE_INSTANCING_COLOR ) || defined( USE_BATCHING_COLOR )
	varying vec4 vColor;
#endif`,color_vertex:`#if defined( USE_COLOR ) || defined( USE_COLOR_ALPHA ) || defined( USE_INSTANCING_COLOR ) || defined( USE_BATCHING_COLOR )
	vColor = vec4( 1.0 );
#endif
#ifdef USE_COLOR_ALPHA
	vColor *= color;
#elif defined( USE_COLOR )
	vColor.rgb *= color;
#endif
#ifdef USE_INSTANCING_COLOR
	vColor.rgb *= instanceColor.rgb;
#endif
#ifdef USE_BATCHING_COLOR
	vColor *= getBatchingColor( getIndirectIndex( gl_DrawID ) );
#endif`,common:`#define PI 3.141592653589793
#define PI2 6.283185307179586
#define PI_HALF 1.5707963267948966
#define RECIPROCAL_PI 0.3183098861837907
#define RECIPROCAL_PI2 0.15915494309189535
#define EPSILON 1e-6
#ifndef saturate
#define saturate( a ) clamp( a, 0.0, 1.0 )
#endif
#define whiteComplement( a ) ( 1.0 - saturate( a ) )
float pow2( const in float x ) { return x*x; }
vec3 pow2( const in vec3 x ) { return x*x; }
float pow3( const in float x ) { return x*x*x; }
float pow4( const in float x ) { float x2 = x*x; return x2*x2; }
float max3( const in vec3 v ) { return max( max( v.x, v.y ), v.z ); }
float average( const in vec3 v ) { return dot( v, vec3( 0.3333333 ) ); }
highp float rand( const in vec2 uv ) {
	const highp float a = 12.9898, b = 78.233, c = 43758.5453;
	highp float dt = dot( uv.xy, vec2( a,b ) ), sn = mod( dt, PI );
	return fract( sin( sn ) * c );
}
#ifdef HIGH_PRECISION
	float precisionSafeLength( vec3 v ) { return length( v ); }
#else
	float precisionSafeLength( vec3 v ) {
		float maxComponent = max3( abs( v ) );
		return length( v / maxComponent ) * maxComponent;
	}
#endif
struct IncidentLight {
	vec3 color;
	vec3 direction;
	bool visible;
};
struct ReflectedLight {
	vec3 directDiffuse;
	vec3 directSpecular;
	vec3 indirectDiffuse;
	vec3 indirectSpecular;
};
#ifdef USE_ALPHAHASH
	varying vec3 vPosition;
#endif
vec3 transformDirection( in vec3 dir, in mat4 matrix ) {
	return normalize( ( matrix * vec4( dir, 0.0 ) ).xyz );
}
#define inverseTransformDirection transformDirectionByInverseViewMatrix
vec3 transformNormalByInverseViewMatrix( in vec3 normal, in mat4 viewMatrix ) {
	return normalize( ( vec4( normal, 0.0 ) * viewMatrix ).xyz );
}
vec3 transformDirectionByInverseViewMatrix( in vec3 dir, in mat4 viewMatrix ) {
	return normalize( ( vec4( dir, 0.0 ) * viewMatrix ).xyz );
}
bool isPerspectiveMatrix( mat4 m ) {
	return m[ 2 ][ 3 ] == - 1.0;
}
vec2 equirectUv( in vec3 dir ) {
	float u = atan( dir.z, dir.x ) * RECIPROCAL_PI2 + 0.5;
	float v = asin( clamp( dir.y, - 1.0, 1.0 ) ) * RECIPROCAL_PI + 0.5;
	return vec2( u, v );
}
vec3 BRDF_Lambert( const in vec3 diffuseColor ) {
	return RECIPROCAL_PI * diffuseColor;
}
vec3 F_Schlick( const in vec3 f0, const in float f90, const in float dotVH ) {
	float fresnel = exp2( ( - 5.55473 * dotVH - 6.98316 ) * dotVH );
	return f0 * ( 1.0 - fresnel ) + ( f90 * fresnel );
}
float F_Schlick( const in float f0, const in float f90, const in float dotVH ) {
	float fresnel = exp2( ( - 5.55473 * dotVH - 6.98316 ) * dotVH );
	return f0 * ( 1.0 - fresnel ) + ( f90 * fresnel );
} // validated`,cube_uv_reflection_fragment:`#ifdef ENVMAP_TYPE_CUBE_UV
	#define cubeUV_minMipLevel 4.0
	#define cubeUV_minTileSize 16.0
	float getFace( vec3 direction ) {
		vec3 absDirection = abs( direction );
		float face = - 1.0;
		if ( absDirection.x > absDirection.z ) {
			if ( absDirection.x > absDirection.y )
				face = direction.x > 0.0 ? 0.0 : 3.0;
			else
				face = direction.y > 0.0 ? 1.0 : 4.0;
		} else {
			if ( absDirection.z > absDirection.y )
				face = direction.z > 0.0 ? 2.0 : 5.0;
			else
				face = direction.y > 0.0 ? 1.0 : 4.0;
		}
		return face;
	}
	vec2 getUV( vec3 direction, float face ) {
		vec2 uv;
		if ( face == 0.0 ) {
			uv = vec2( direction.z, direction.y ) / abs( direction.x );
		} else if ( face == 1.0 ) {
			uv = vec2( - direction.x, - direction.z ) / abs( direction.y );
		} else if ( face == 2.0 ) {
			uv = vec2( - direction.x, direction.y ) / abs( direction.z );
		} else if ( face == 3.0 ) {
			uv = vec2( - direction.z, direction.y ) / abs( direction.x );
		} else if ( face == 4.0 ) {
			uv = vec2( - direction.x, direction.z ) / abs( direction.y );
		} else {
			uv = vec2( direction.x, direction.y ) / abs( direction.z );
		}
		return 0.5 * ( uv + 1.0 );
	}
	vec3 bilinearCubeUV( sampler2D envMap, vec3 direction, float mipInt ) {
		float face = getFace( direction );
		float filterInt = max( cubeUV_minMipLevel - mipInt, 0.0 );
		mipInt = max( mipInt, cubeUV_minMipLevel );
		float faceSize = exp2( mipInt );
		highp vec2 uv = getUV( direction, face ) * ( faceSize - 2.0 ) + 1.0;
		if ( face > 2.0 ) {
			uv.y += faceSize;
			face -= 3.0;
		}
		uv.x += face * faceSize;
		uv.x += filterInt * 3.0 * cubeUV_minTileSize;
		uv.y += 4.0 * ( exp2( CUBEUV_MAX_MIP ) - faceSize );
		uv.x *= CUBEUV_TEXEL_WIDTH;
		uv.y *= CUBEUV_TEXEL_HEIGHT;
		#ifdef texture2DGradEXT
			return texture2DGradEXT( envMap, uv, vec2( 0.0 ), vec2( 0.0 ) ).rgb;
		#else
			return texture2D( envMap, uv ).rgb;
		#endif
	}
	#define cubeUV_r0 1.0
	#define cubeUV_m0 - 2.0
	#define cubeUV_r1 0.8
	#define cubeUV_m1 - 1.0
	#define cubeUV_r4 0.4
	#define cubeUV_m4 2.0
	#define cubeUV_r5 0.305
	#define cubeUV_m5 3.0
	#define cubeUV_r6 0.21
	#define cubeUV_m6 4.0
	float roughnessToMip( float roughness ) {
		float mip = 0.0;
		if ( roughness >= cubeUV_r1 ) {
			mip = ( cubeUV_r0 - roughness ) * ( cubeUV_m1 - cubeUV_m0 ) / ( cubeUV_r0 - cubeUV_r1 ) + cubeUV_m0;
		} else if ( roughness >= cubeUV_r4 ) {
			mip = ( cubeUV_r1 - roughness ) * ( cubeUV_m4 - cubeUV_m1 ) / ( cubeUV_r1 - cubeUV_r4 ) + cubeUV_m1;
		} else if ( roughness >= cubeUV_r5 ) {
			mip = ( cubeUV_r4 - roughness ) * ( cubeUV_m5 - cubeUV_m4 ) / ( cubeUV_r4 - cubeUV_r5 ) + cubeUV_m4;
		} else if ( roughness >= cubeUV_r6 ) {
			mip = ( cubeUV_r5 - roughness ) * ( cubeUV_m6 - cubeUV_m5 ) / ( cubeUV_r5 - cubeUV_r6 ) + cubeUV_m5;
		} else {
			mip = - 2.0 * log2( 1.16 * roughness );		}
		return mip;
	}
	vec4 textureCubeUV( sampler2D envMap, vec3 sampleDir, float roughness ) {
		float mip = clamp( roughnessToMip( roughness ), cubeUV_m0, CUBEUV_MAX_MIP );
		float mipF = fract( mip );
		float mipInt = floor( mip );
		vec3 color0 = bilinearCubeUV( envMap, sampleDir, mipInt );
		if ( mipF == 0.0 ) {
			return vec4( color0, 1.0 );
		} else {
			vec3 color1 = bilinearCubeUV( envMap, sampleDir, mipInt + 1.0 );
			return vec4( mix( color0, color1, mipF ), 1.0 );
		}
	}
#endif`,defaultnormal_vertex:`vec3 transformedNormal = objectNormal;
#ifdef USE_TANGENT
	vec3 transformedTangent = objectTangent;
#endif
#ifdef USE_BATCHING
	mat3 bm = mat3( batchingMatrix );
	transformedNormal /= vec3( dot( bm[ 0 ], bm[ 0 ] ), dot( bm[ 1 ], bm[ 1 ] ), dot( bm[ 2 ], bm[ 2 ] ) );
	transformedNormal = bm * transformedNormal;
	#ifdef USE_TANGENT
		transformedTangent = bm * transformedTangent;
	#endif
#endif
#ifdef USE_INSTANCING
	mat3 im = mat3( instanceMatrix );
	transformedNormal /= vec3( dot( im[ 0 ], im[ 0 ] ), dot( im[ 1 ], im[ 1 ] ), dot( im[ 2 ], im[ 2 ] ) );
	transformedNormal = im * transformedNormal;
	#ifdef USE_TANGENT
		transformedTangent = im * transformedTangent;
	#endif
#endif
transformedNormal = normalMatrix * transformedNormal;
#ifdef FLIP_SIDED
	transformedNormal = - transformedNormal;
#endif
#ifdef USE_TANGENT
	transformedTangent = ( modelViewMatrix * vec4( transformedTangent, 0.0 ) ).xyz;
#endif`,displacementmap_pars_vertex:`#ifdef USE_DISPLACEMENTMAP
	uniform sampler2D displacementMap;
	uniform float displacementScale;
	uniform float displacementBias;
#endif`,displacementmap_vertex:`#ifdef USE_DISPLACEMENTMAP
	transformed += normalize( objectNormal ) * ( texture2D( displacementMap, vDisplacementMapUv ).x * displacementScale + displacementBias );
#endif`,emissivemap_fragment:`#ifdef USE_EMISSIVEMAP
	vec4 emissiveColor = texture2D( emissiveMap, vEmissiveMapUv );
	#ifdef DECODE_VIDEO_TEXTURE_EMISSIVE
		emissiveColor = sRGBTransferEOTF( emissiveColor );
	#endif
	totalEmissiveRadiance *= emissiveColor.rgb;
#endif`,emissivemap_pars_fragment:`#ifdef USE_EMISSIVEMAP
	uniform sampler2D emissiveMap;
#endif`,colorspace_fragment:`gl_FragColor = linearToOutputTexel( gl_FragColor );`,colorspace_pars_fragment:`vec4 LinearTransferOETF( in vec4 value ) {
	return value;
}
vec4 sRGBTransferEOTF( in vec4 value ) {
	return vec4( mix( pow( value.rgb * 0.9478672986 + vec3( 0.0521327014 ), vec3( 2.4 ) ), value.rgb * 0.0773993808, vec3( lessThanEqual( value.rgb, vec3( 0.04045 ) ) ) ), value.a );
}
vec4 sRGBTransferOETF( in vec4 value ) {
	return vec4( mix( pow( value.rgb, vec3( 0.41666 ) ) * 1.055 - vec3( 0.055 ), value.rgb * 12.92, vec3( lessThanEqual( value.rgb, vec3( 0.0031308 ) ) ) ), value.a );
}`,envmap_fragment:`#ifdef USE_ENVMAP
	#ifdef ENV_WORLDPOS
		vec3 cameraToFrag;
		if ( isOrthographic ) {
			cameraToFrag = normalize( vec3( - viewMatrix[ 0 ][ 2 ], - viewMatrix[ 1 ][ 2 ], - viewMatrix[ 2 ][ 2 ] ) );
		} else {
			cameraToFrag = normalize( vWorldPosition - cameraPosition );
		}
		vec3 worldNormal = transformNormalByInverseViewMatrix( normal, viewMatrix );
		#ifdef ENVMAP_MODE_REFLECTION
			vec3 reflectVec = reflect( cameraToFrag, worldNormal );
		#else
			vec3 reflectVec = refract( cameraToFrag, worldNormal, refractionRatio );
		#endif
	#else
		vec3 reflectVec = vReflect;
	#endif
	#ifdef ENVMAP_TYPE_CUBE
		vec4 envColor = textureCube( envMap, envMapRotation * reflectVec );
		#ifdef ENVMAP_BLENDING_MULTIPLY
			outgoingLight = mix( outgoingLight, outgoingLight * envColor.xyz, specularStrength * reflectivity );
		#elif defined( ENVMAP_BLENDING_MIX )
			outgoingLight = mix( outgoingLight, envColor.xyz, specularStrength * reflectivity );
		#elif defined( ENVMAP_BLENDING_ADD )
			outgoingLight += envColor.xyz * specularStrength * reflectivity;
		#endif
	#endif
#endif`,envmap_common_pars_fragment:`#ifdef USE_ENVMAP
	uniform float envMapIntensity;
	uniform mat3 envMapRotation;
	#ifdef ENVMAP_TYPE_CUBE
		uniform samplerCube envMap;
	#else
		uniform sampler2D envMap;
	#endif
#endif`,envmap_pars_fragment:`#ifdef USE_ENVMAP
	uniform float reflectivity;
	#if defined( USE_BUMPMAP ) || defined( USE_NORMALMAP ) || defined( PHONG ) || defined( LAMBERT )
		#define ENV_WORLDPOS
	#endif
	#ifdef ENV_WORLDPOS
		varying vec3 vWorldPosition;
		uniform float refractionRatio;
	#else
		varying vec3 vReflect;
	#endif
#endif`,envmap_pars_vertex:`#ifdef USE_ENVMAP
	#if defined( USE_BUMPMAP ) || defined( USE_NORMALMAP ) || defined( PHONG ) || defined( LAMBERT )
		#define ENV_WORLDPOS
	#endif
	#ifdef ENV_WORLDPOS
		
		varying vec3 vWorldPosition;
	#else
		varying vec3 vReflect;
		uniform float refractionRatio;
	#endif
#endif`,envmap_physical_pars_fragment:`#ifdef USE_ENVMAP
	vec3 getIBLIrradiance( const in vec3 normal ) {
		#ifdef ENVMAP_TYPE_CUBE_UV
			vec3 worldNormal = transformNormalByInverseViewMatrix( normal, viewMatrix );
			vec4 envMapColor = textureCubeUV( envMap, envMapRotation * worldNormal, 1.0 );
			return PI * envMapColor.rgb * envMapIntensity;
		#else
			return vec3( 0.0 );
		#endif
	}
	vec3 getIBLRadiance( const in vec3 viewDir, const in vec3 normal, const in float roughness ) {
		#ifdef ENVMAP_TYPE_CUBE_UV
			vec3 reflectVec = reflect( - viewDir, normal );
			reflectVec = normalize( mix( reflectVec, normal, pow4( roughness ) ) );
			reflectVec = transformDirectionByInverseViewMatrix( reflectVec, viewMatrix );
			vec4 envMapColor = textureCubeUV( envMap, envMapRotation * reflectVec, roughness );
			return envMapColor.rgb * envMapIntensity;
		#else
			return vec3( 0.0 );
		#endif
	}
	#ifdef USE_ANISOTROPY
		vec3 getIBLAnisotropyRadiance( const in vec3 viewDir, const in vec3 normal, const in float roughness, const in vec3 bitangent, const in float anisotropy ) {
			#ifdef ENVMAP_TYPE_CUBE_UV
				vec3 bentNormal = cross( bitangent, viewDir );
				bentNormal = normalize( cross( bentNormal, bitangent ) );
				bentNormal = normalize( mix( bentNormal, normal, pow2( pow2( 1.0 - anisotropy * ( 1.0 - roughness ) ) ) ) );
				return getIBLRadiance( viewDir, bentNormal, roughness );
			#else
				return vec3( 0.0 );
			#endif
		}
	#endif
#endif`,envmap_vertex:`#ifdef USE_ENVMAP
	#ifdef ENV_WORLDPOS
		vWorldPosition = worldPosition.xyz;
	#else
		vec3 cameraToVertex;
		if ( isOrthographic ) {
			cameraToVertex = normalize( vec3( - viewMatrix[ 0 ][ 2 ], - viewMatrix[ 1 ][ 2 ], - viewMatrix[ 2 ][ 2 ] ) );
		} else {
			cameraToVertex = normalize( worldPosition.xyz - cameraPosition );
		}
		vec3 worldNormal = transformNormalByInverseViewMatrix( transformedNormal, viewMatrix );
		#ifdef ENVMAP_MODE_REFLECTION
			vReflect = reflect( cameraToVertex, worldNormal );
		#else
			vReflect = refract( cameraToVertex, worldNormal, refractionRatio );
		#endif
	#endif
#endif`,fog_vertex:`#ifdef USE_FOG
	vFogDepth = - mvPosition.z;
#endif`,fog_pars_vertex:`#ifdef USE_FOG
	varying float vFogDepth;
#endif`,fog_fragment:`#ifdef USE_FOG
	#ifdef FOG_EXP2
		float fogFactor = 1.0 - exp( - fogDensity * fogDensity * vFogDepth * vFogDepth );
	#else
		float fogFactor = smoothstep( fogNear, fogFar, vFogDepth );
	#endif
	gl_FragColor.rgb = mix( gl_FragColor.rgb, fogColor, fogFactor );
#endif`,fog_pars_fragment:`#ifdef USE_FOG
	uniform vec3 fogColor;
	varying float vFogDepth;
	#ifdef FOG_EXP2
		uniform float fogDensity;
	#else
		uniform float fogNear;
		uniform float fogFar;
	#endif
#endif`,gradientmap_pars_fragment:`#ifdef USE_GRADIENTMAP
	uniform sampler2D gradientMap;
#endif
vec3 getGradientIrradiance( vec3 normal, vec3 lightDirection ) {
	float dotNL = dot( normal, lightDirection );
	vec2 coord = vec2( dotNL * 0.5 + 0.5, 0.0 );
	#ifdef USE_GRADIENTMAP
		return vec3( texture2D( gradientMap, coord ).r );
	#else
		vec2 fw = fwidth( coord ) * 0.5;
		return mix( vec3( 0.7 ), vec3( 1.0 ), smoothstep( 0.7 - fw.x, 0.7 + fw.x, coord.x ) );
	#endif
}`,lightmap_pars_fragment:`#ifdef USE_LIGHTMAP
	uniform sampler2D lightMap;
	uniform float lightMapIntensity;
#endif`,lights_lambert_fragment:`LambertMaterial material;
material.diffuseColor = diffuseColor.rgb;
material.specularStrength = specularStrength;`,lights_lambert_pars_fragment:`varying vec3 vViewPosition;
struct LambertMaterial {
	vec3 diffuseColor;
	float specularStrength;
};
void RE_Direct_Lambert( const in IncidentLight directLight, const in vec3 geometryPosition, const in vec3 geometryNormal, const in vec3 geometryViewDir, const in vec3 geometryClearcoatNormal, const in LambertMaterial material, inout ReflectedLight reflectedLight ) {
	float dotNL = saturate( dot( geometryNormal, directLight.direction ) );
	vec3 irradiance = dotNL * directLight.color;
	reflectedLight.directDiffuse += irradiance * BRDF_Lambert( material.diffuseColor );
}
void RE_IndirectDiffuse_Lambert( const in vec3 irradiance, const in vec3 geometryPosition, const in vec3 geometryNormal, const in vec3 geometryViewDir, const in vec3 geometryClearcoatNormal, const in LambertMaterial material, inout ReflectedLight reflectedLight ) {
	reflectedLight.indirectDiffuse += irradiance * BRDF_Lambert( material.diffuseColor );
}
#define RE_Direct				RE_Direct_Lambert
#define RE_IndirectDiffuse		RE_IndirectDiffuse_Lambert`,lights_pars_begin:`uniform bool receiveShadow;
uniform vec3 ambientLightColor;
#if defined( USE_LIGHT_PROBES )
	uniform vec3 lightProbe[ 9 ];
#endif
vec3 shGetIrradianceAt( in vec3 normal, in vec3 shCoefficients[ 9 ] ) {
	float x = normal.x, y = normal.y, z = normal.z;
	vec3 result = shCoefficients[ 0 ] * 0.886227;
	result += shCoefficients[ 1 ] * 2.0 * 0.511664 * y;
	result += shCoefficients[ 2 ] * 2.0 * 0.511664 * z;
	result += shCoefficients[ 3 ] * 2.0 * 0.511664 * x;
	result += shCoefficients[ 4 ] * 2.0 * 0.429043 * x * y;
	result += shCoefficients[ 5 ] * 2.0 * 0.429043 * y * z;
	result += shCoefficients[ 6 ] * ( 0.743125 * z * z - 0.247708 );
	result += shCoefficients[ 7 ] * 2.0 * 0.429043 * x * z;
	result += shCoefficients[ 8 ] * 0.429043 * ( x * x - y * y );
	return result;
}
vec3 getLightProbeIrradiance( const in vec3 lightProbe[ 9 ], const in vec3 normal ) {
	vec3 worldNormal = transformNormalByInverseViewMatrix( normal, viewMatrix );
	vec3 irradiance = shGetIrradianceAt( worldNormal, lightProbe );
	return irradiance;
}
vec3 getAmbientLightIrradiance( const in vec3 ambientLightColor ) {
	vec3 irradiance = ambientLightColor;
	return irradiance;
}
float getDistanceAttenuation( const in float lightDistance, const in float cutoffDistance, const in float decayExponent ) {
	float distanceFalloff = 1.0 / max( pow( lightDistance, decayExponent ), 0.01 );
	if ( cutoffDistance > 0.0 ) {
		distanceFalloff *= pow2( saturate( 1.0 - pow4( lightDistance / cutoffDistance ) ) );
	}
	return distanceFalloff;
}
float getSpotAttenuation( const in float coneCosine, const in float penumbraCosine, const in float angleCosine ) {
	return smoothstep( coneCosine, penumbraCosine, angleCosine );
}
#if NUM_DIR_LIGHTS > 0
	struct DirectionalLight {
		vec3 direction;
		vec3 color;
	};
	uniform DirectionalLight directionalLights[ NUM_DIR_LIGHTS ];
	void getDirectionalLightInfo( const in DirectionalLight directionalLight, out IncidentLight light ) {
		light.color = directionalLight.color;
		light.direction = directionalLight.direction;
		light.visible = true;
	}
#endif
#if NUM_POINT_LIGHTS > 0
	struct PointLight {
		vec3 position;
		vec3 color;
		float distance;
		float decay;
	};
	uniform PointLight pointLights[ NUM_POINT_LIGHTS ];
	void getPointLightInfo( const in PointLight pointLight, const in vec3 geometryPosition, out IncidentLight light ) {
		vec3 lVector = pointLight.position - geometryPosition;
		light.direction = normalize( lVector );
		float lightDistance = length( lVector );
		light.color = pointLight.color;
		light.color *= getDistanceAttenuation( lightDistance, pointLight.distance, pointLight.decay );
		light.visible = ( light.color != vec3( 0.0 ) );
	}
#endif
#if NUM_SPOT_LIGHTS > 0
	struct SpotLight {
		vec3 position;
		vec3 direction;
		vec3 color;
		float distance;
		float decay;
		float coneCos;
		float penumbraCos;
	};
	uniform SpotLight spotLights[ NUM_SPOT_LIGHTS ];
	void getSpotLightInfo( const in SpotLight spotLight, const in vec3 geometryPosition, out IncidentLight light ) {
		vec3 lVector = spotLight.position - geometryPosition;
		light.direction = normalize( lVector );
		float angleCos = dot( light.direction, spotLight.direction );
		float spotAttenuation = getSpotAttenuation( spotLight.coneCos, spotLight.penumbraCos, angleCos );
		if ( spotAttenuation > 0.0 ) {
			float lightDistance = length( lVector );
			light.color = spotLight.color * spotAttenuation;
			light.color *= getDistanceAttenuation( lightDistance, spotLight.distance, spotLight.decay );
			light.visible = ( light.color != vec3( 0.0 ) );
		} else {
			light.color = vec3( 0.0 );
			light.visible = false;
		}
	}
#endif
#if NUM_RECT_AREA_LIGHTS > 0
	struct RectAreaLight {
		vec3 color;
		vec3 position;
		vec3 halfWidth;
		vec3 halfHeight;
	};
	uniform sampler2D ltc_1;	uniform sampler2D ltc_2;
	uniform RectAreaLight rectAreaLights[ NUM_RECT_AREA_LIGHTS ];
#endif
#if NUM_HEMI_LIGHTS > 0
	struct HemisphereLight {
		vec3 direction;
		vec3 skyColor;
		vec3 groundColor;
	};
	uniform HemisphereLight hemisphereLights[ NUM_HEMI_LIGHTS ];
	vec3 getHemisphereLightIrradiance( const in HemisphereLight hemiLight, const in vec3 normal ) {
		float dotNL = dot( normal, hemiLight.direction );
		float hemiDiffuseWeight = 0.5 * dotNL + 0.5;
		vec3 irradiance = mix( hemiLight.groundColor, hemiLight.skyColor, hemiDiffuseWeight );
		return irradiance;
	}
#endif
#include <lightprobes_pars_fragment>`,lights_toon_fragment:`ToonMaterial material;
material.diffuseColor = diffuseColor.rgb;`,lights_toon_pars_fragment:`varying vec3 vViewPosition;
struct ToonMaterial {
	vec3 diffuseColor;
};
void RE_Direct_Toon( const in IncidentLight directLight, const in vec3 geometryPosition, const in vec3 geometryNormal, const in vec3 geometryViewDir, const in vec3 geometryClearcoatNormal, const in ToonMaterial material, inout ReflectedLight reflectedLight ) {
	vec3 irradiance = getGradientIrradiance( geometryNormal, directLight.direction ) * directLight.color;
	reflectedLight.directDiffuse += irradiance * BRDF_Lambert( material.diffuseColor );
}
void RE_IndirectDiffuse_Toon( const in vec3 irradiance, const in vec3 geometryPosition, const in vec3 geometryNormal, const in vec3 geometryViewDir, const in vec3 geometryClearcoatNormal, const in ToonMaterial material, inout ReflectedLight reflectedLight ) {
	reflectedLight.indirectDiffuse += irradiance * BRDF_Lambert( material.diffuseColor );
}
#define RE_Direct				RE_Direct_Toon
#define RE_IndirectDiffuse		RE_IndirectDiffuse_Toon`,lights_phong_fragment:`BlinnPhongMaterial material;
material.diffuseColor = diffuseColor.rgb;
material.specularColor = specular;
material.specularShininess = shininess;
material.specularStrength = specularStrength;`,lights_phong_pars_fragment:`varying vec3 vViewPosition;
struct BlinnPhongMaterial {
	vec3 diffuseColor;
	vec3 specularColor;
	float specularShininess;
	float specularStrength;
};
void RE_Direct_BlinnPhong( const in IncidentLight directLight, const in vec3 geometryPosition, const in vec3 geometryNormal, const in vec3 geometryViewDir, const in vec3 geometryClearcoatNormal, const in BlinnPhongMaterial material, inout ReflectedLight reflectedLight ) {
	float dotNL = saturate( dot( geometryNormal, directLight.direction ) );
	vec3 irradiance = dotNL * directLight.color;
	reflectedLight.directDiffuse += irradiance * BRDF_Lambert( material.diffuseColor );
	reflectedLight.directSpecular += irradiance * BRDF_BlinnPhong( directLight.direction, geometryViewDir, geometryNormal, material.specularColor, material.specularShininess ) * material.specularStrength;
}
void RE_IndirectDiffuse_BlinnPhong( const in vec3 irradiance, const in vec3 geometryPosition, const in vec3 geometryNormal, const in vec3 geometryViewDir, const in vec3 geometryClearcoatNormal, const in BlinnPhongMaterial material, inout ReflectedLight reflectedLight ) {
	reflectedLight.indirectDiffuse += irradiance * BRDF_Lambert( material.diffuseColor );
}
#define RE_Direct				RE_Direct_BlinnPhong
#define RE_IndirectDiffuse		RE_IndirectDiffuse_BlinnPhong`,lights_physical_fragment:`PhysicalMaterial material;
material.diffuseColor = diffuseColor.rgb;
material.diffuseContribution = diffuseColor.rgb * ( 1.0 - metalnessFactor );
material.metalness = metalnessFactor;
vec3 dxy = max( abs( dFdx( nonPerturbedNormal ) ), abs( dFdy( nonPerturbedNormal ) ) );
float geometryRoughness = max( max( dxy.x, dxy.y ), dxy.z );
material.roughness = max( roughnessFactor, 0.0525 );material.roughness += geometryRoughness;
material.roughness = min( material.roughness, 1.0 );
#ifdef IOR
	material.ior = ior;
	#ifdef USE_SPECULAR
		float specularIntensityFactor = specularIntensity;
		vec3 specularColorFactor = specularColor;
		#ifdef USE_SPECULAR_COLORMAP
			specularColorFactor *= texture2D( specularColorMap, vSpecularColorMapUv ).rgb;
		#endif
		#ifdef USE_SPECULAR_INTENSITYMAP
			specularIntensityFactor *= texture2D( specularIntensityMap, vSpecularIntensityMapUv ).a;
		#endif
		material.specularF90 = mix( specularIntensityFactor, 1.0, metalnessFactor );
	#else
		float specularIntensityFactor = 1.0;
		vec3 specularColorFactor = vec3( 1.0 );
		material.specularF90 = 1.0;
	#endif
	material.specularColor = min( pow2( ( material.ior - 1.0 ) / ( material.ior + 1.0 ) ) * specularColorFactor, vec3( 1.0 ) ) * specularIntensityFactor;
	material.specularColorBlended = mix( material.specularColor, diffuseColor.rgb, metalnessFactor );
#else
	material.specularColor = vec3( 0.04 );
	material.specularColorBlended = mix( material.specularColor, diffuseColor.rgb, metalnessFactor );
	material.specularF90 = 1.0;
#endif
#ifdef USE_CLEARCOAT
	material.clearcoat = clearcoat;
	material.clearcoatRoughness = clearcoatRoughness;
	material.clearcoatF0 = vec3( 0.04 );
	material.clearcoatF90 = 1.0;
	#ifdef USE_CLEARCOATMAP
		material.clearcoat *= texture2D( clearcoatMap, vClearcoatMapUv ).x;
	#endif
	#ifdef USE_CLEARCOAT_ROUGHNESSMAP
		material.clearcoatRoughness *= texture2D( clearcoatRoughnessMap, vClearcoatRoughnessMapUv ).y;
	#endif
	material.clearcoat = saturate( material.clearcoat );	material.clearcoatRoughness = max( material.clearcoatRoughness, 0.0525 );
	material.clearcoatRoughness += geometryRoughness;
	material.clearcoatRoughness = min( material.clearcoatRoughness, 1.0 );
#endif
#ifdef USE_DISPERSION
	material.dispersion = dispersion;
#endif
#ifdef USE_IRIDESCENCE
	material.iridescence = iridescence;
	material.iridescenceIOR = iridescenceIOR;
	#ifdef USE_IRIDESCENCEMAP
		material.iridescence *= texture2D( iridescenceMap, vIridescenceMapUv ).r;
	#endif
	#ifdef USE_IRIDESCENCE_THICKNESSMAP
		material.iridescenceThickness = (iridescenceThicknessMaximum - iridescenceThicknessMinimum) * texture2D( iridescenceThicknessMap, vIridescenceThicknessMapUv ).g + iridescenceThicknessMinimum;
	#else
		material.iridescenceThickness = iridescenceThicknessMaximum;
	#endif
#endif
#ifdef USE_SHEEN
	material.sheenColor = sheenColor;
	#ifdef USE_SHEEN_COLORMAP
		material.sheenColor *= texture2D( sheenColorMap, vSheenColorMapUv ).rgb;
	#endif
	material.sheenRoughness = clamp( sheenRoughness, 0.0001, 1.0 );
	#ifdef USE_SHEEN_ROUGHNESSMAP
		material.sheenRoughness *= texture2D( sheenRoughnessMap, vSheenRoughnessMapUv ).a;
	#endif
#endif
#ifdef USE_ANISOTROPY
	#ifdef USE_ANISOTROPYMAP
		mat2 anisotropyMat = mat2( anisotropyVector.x, anisotropyVector.y, - anisotropyVector.y, anisotropyVector.x );
		vec3 anisotropyPolar = texture2D( anisotropyMap, vAnisotropyMapUv ).rgb;
		vec2 anisotropyV = anisotropyMat * normalize( 2.0 * anisotropyPolar.rg - vec2( 1.0 ) ) * anisotropyPolar.b;
	#else
		vec2 anisotropyV = anisotropyVector;
	#endif
	material.anisotropy = length( anisotropyV );
	if( material.anisotropy == 0.0 ) {
		anisotropyV = vec2( 1.0, 0.0 );
	} else {
		anisotropyV /= material.anisotropy;
		material.anisotropy = saturate( material.anisotropy );
	}
	material.alphaT = mix( pow2( material.roughness ), 1.0, pow2( material.anisotropy ) );
	material.anisotropyT = tbn[ 0 ] * anisotropyV.x + tbn[ 1 ] * anisotropyV.y;
	material.anisotropyB = tbn[ 1 ] * anisotropyV.x - tbn[ 0 ] * anisotropyV.y;
#endif`,lights_physical_pars_fragment:`uniform sampler2D dfgLUT;
struct PhysicalMaterial {
	vec3 diffuseColor;
	vec3 diffuseContribution;
	vec3 specularColor;
	vec3 specularColorBlended;
	float roughness;
	float metalness;
	float specularF90;
	float dispersion;
	#ifdef USE_CLEARCOAT
		float clearcoat;
		float clearcoatRoughness;
		vec3 clearcoatF0;
		float clearcoatF90;
	#endif
	#ifdef USE_IRIDESCENCE
		float iridescence;
		float iridescenceIOR;
		float iridescenceThickness;
		vec3 iridescenceFresnel;
		vec3 iridescenceF0;
		vec3 iridescenceFresnelDielectric;
		vec3 iridescenceFresnelMetallic;
	#endif
	#ifdef USE_SHEEN
		vec3 sheenColor;
		float sheenRoughness;
	#endif
	#ifdef IOR
		float ior;
	#endif
	#ifdef USE_TRANSMISSION
		float transmission;
		float transmissionAlpha;
		float thickness;
		float attenuationDistance;
		vec3 attenuationColor;
	#endif
	#ifdef USE_ANISOTROPY
		float anisotropy;
		float alphaT;
		vec3 anisotropyT;
		vec3 anisotropyB;
	#endif
};
vec3 clearcoatSpecularDirect = vec3( 0.0 );
vec3 clearcoatSpecularIndirect = vec3( 0.0 );
vec3 sheenSpecularDirect = vec3( 0.0 );
vec3 sheenSpecularIndirect = vec3(0.0 );
vec3 Schlick_to_F0( const in vec3 f, const in float f90, const in float dotVH ) {
    float x = clamp( 1.0 - dotVH, 0.0, 1.0 );
    float x2 = x * x;
    float x5 = clamp( x * x2 * x2, 0.0, 0.9999 );
    return ( f - vec3( f90 ) * x5 ) / ( 1.0 - x5 );
}
float V_GGX_SmithCorrelated( const in float alpha, const in float dotNL, const in float dotNV ) {
	float a2 = pow2( alpha );
	float gv = dotNL * sqrt( a2 + ( 1.0 - a2 ) * pow2( dotNV ) );
	float gl = dotNV * sqrt( a2 + ( 1.0 - a2 ) * pow2( dotNL ) );
	return 0.5 / max( gv + gl, EPSILON );
}
float D_GGX( const in float alpha, const in float dotNH ) {
	float a2 = pow2( alpha );
	float denom = pow2( dotNH ) * ( a2 - 1.0 ) + 1.0;
	return RECIPROCAL_PI * a2 / pow2( denom );
}
#ifdef USE_ANISOTROPY
	float V_GGX_SmithCorrelated_Anisotropic( const in float alphaT, const in float alphaB, const in float dotTV, const in float dotBV, const in float dotTL, const in float dotBL, const in float dotNV, const in float dotNL ) {
		float gv = dotNL * length( vec3( alphaT * dotTV, alphaB * dotBV, dotNV ) );
		float gl = dotNV * length( vec3( alphaT * dotTL, alphaB * dotBL, dotNL ) );
		return 0.5 / max( gv + gl, EPSILON );
	}
	float D_GGX_Anisotropic( const in float alphaT, const in float alphaB, const in float dotNH, const in float dotTH, const in float dotBH ) {
		float a2 = alphaT * alphaB;
		highp vec3 v = vec3( alphaB * dotTH, alphaT * dotBH, a2 * dotNH );
		highp float v2 = dot( v, v );
		float w2 = a2 / v2;
		return RECIPROCAL_PI * a2 * pow2 ( w2 );
	}
#endif
#ifdef USE_CLEARCOAT
	vec3 BRDF_GGX_Clearcoat( const in vec3 lightDir, const in vec3 viewDir, const in vec3 normal, const in PhysicalMaterial material) {
		vec3 f0 = material.clearcoatF0;
		float f90 = material.clearcoatF90;
		float roughness = material.clearcoatRoughness;
		float alpha = pow2( roughness );
		vec3 halfDir = normalize( lightDir + viewDir );
		float dotNL = saturate( dot( normal, lightDir ) );
		float dotNV = saturate( dot( normal, viewDir ) );
		float dotNH = saturate( dot( normal, halfDir ) );
		float dotVH = saturate( dot( viewDir, halfDir ) );
		vec3 F = F_Schlick( f0, f90, dotVH );
		float V = V_GGX_SmithCorrelated( alpha, dotNL, dotNV );
		float D = D_GGX( alpha, dotNH );
		return F * ( V * D );
	}
#endif
vec3 BRDF_GGX( const in vec3 lightDir, const in vec3 viewDir, const in vec3 normal, const in PhysicalMaterial material ) {
	vec3 f0 = material.specularColorBlended;
	float f90 = material.specularF90;
	float roughness = material.roughness;
	float alpha = pow2( roughness );
	vec3 halfDir = normalize( lightDir + viewDir );
	float dotNL = saturate( dot( normal, lightDir ) );
	float dotNV = saturate( dot( normal, viewDir ) );
	float dotNH = saturate( dot( normal, halfDir ) );
	float dotVH = saturate( dot( viewDir, halfDir ) );
	vec3 F = F_Schlick( f0, f90, dotVH );
	#ifdef USE_IRIDESCENCE
		F = mix( F, material.iridescenceFresnel, material.iridescence );
	#endif
	#ifdef USE_ANISOTROPY
		float dotTL = dot( material.anisotropyT, lightDir );
		float dotTV = dot( material.anisotropyT, viewDir );
		float dotTH = dot( material.anisotropyT, halfDir );
		float dotBL = dot( material.anisotropyB, lightDir );
		float dotBV = dot( material.anisotropyB, viewDir );
		float dotBH = dot( material.anisotropyB, halfDir );
		float V = V_GGX_SmithCorrelated_Anisotropic( material.alphaT, alpha, dotTV, dotBV, dotTL, dotBL, dotNV, dotNL );
		float D = D_GGX_Anisotropic( material.alphaT, alpha, dotNH, dotTH, dotBH );
	#else
		float V = V_GGX_SmithCorrelated( alpha, dotNL, dotNV );
		float D = D_GGX( alpha, dotNH );
	#endif
	return F * ( V * D );
}
vec2 LTC_Uv( const in vec3 N, const in vec3 V, const in float roughness ) {
	const float LUT_SIZE = 64.0;
	const float LUT_SCALE = ( LUT_SIZE - 1.0 ) / LUT_SIZE;
	const float LUT_BIAS = 0.5 / LUT_SIZE;
	float dotNV = saturate( dot( N, V ) );
	vec2 uv = vec2( roughness, sqrt( 1.0 - dotNV ) );
	uv = uv * LUT_SCALE + LUT_BIAS;
	return uv;
}
float LTC_ClippedSphereFormFactor( const in vec3 f ) {
	float l = length( f );
	return max( ( l * l + f.z ) / ( l + 1.0 ), 0.0 );
}
vec3 LTC_EdgeVectorFormFactor( const in vec3 v1, const in vec3 v2 ) {
	float x = dot( v1, v2 );
	float y = abs( x );
	float a = 0.8543985 + ( 0.4965155 + 0.0145206 * y ) * y;
	float b = 3.4175940 + ( 4.1616724 + y ) * y;
	float v = a / b;
	float theta_sintheta = ( x > 0.0 ) ? v : 0.5 * inversesqrt( max( 1.0 - x * x, 1e-7 ) ) - v;
	return cross( v1, v2 ) * theta_sintheta;
}
vec3 LTC_Evaluate( const in vec3 N, const in vec3 V, const in vec3 P, const in mat3 mInv, const in vec3 rectCoords[ 4 ] ) {
	vec3 v1 = rectCoords[ 1 ] - rectCoords[ 0 ];
	vec3 v2 = rectCoords[ 3 ] - rectCoords[ 0 ];
	vec3 lightNormal = cross( v1, v2 );
	if( dot( lightNormal, P - rectCoords[ 0 ] ) < 0.0 ) return vec3( 0.0 );
	vec3 T1, T2;
	T1 = normalize( V - N * dot( V, N ) );
	T2 = - cross( N, T1 );
	mat3 mat = mInv * transpose( mat3( T1, T2, N ) );
	vec3 coords[ 4 ];
	coords[ 0 ] = mat * ( rectCoords[ 0 ] - P );
	coords[ 1 ] = mat * ( rectCoords[ 1 ] - P );
	coords[ 2 ] = mat * ( rectCoords[ 2 ] - P );
	coords[ 3 ] = mat * ( rectCoords[ 3 ] - P );
	coords[ 0 ] = normalize( coords[ 0 ] );
	coords[ 1 ] = normalize( coords[ 1 ] );
	coords[ 2 ] = normalize( coords[ 2 ] );
	coords[ 3 ] = normalize( coords[ 3 ] );
	vec3 vectorFormFactor = vec3( 0.0 );
	vectorFormFactor += LTC_EdgeVectorFormFactor( coords[ 0 ], coords[ 1 ] );
	vectorFormFactor += LTC_EdgeVectorFormFactor( coords[ 1 ], coords[ 2 ] );
	vectorFormFactor += LTC_EdgeVectorFormFactor( coords[ 2 ], coords[ 3 ] );
	vectorFormFactor += LTC_EdgeVectorFormFactor( coords[ 3 ], coords[ 0 ] );
	float result = LTC_ClippedSphereFormFactor( vectorFormFactor );
	return vec3( result );
}
#if defined( USE_SHEEN )
float D_Charlie( float roughness, float dotNH ) {
	float alpha = pow2( roughness );
	float invAlpha = 1.0 / alpha;
	float cos2h = dotNH * dotNH;
	float sin2h = max( 1.0 - cos2h, 0.0078125 );
	return ( 2.0 + invAlpha ) * pow( sin2h, invAlpha * 0.5 ) / ( 2.0 * PI );
}
float V_Neubelt( float dotNV, float dotNL ) {
	return saturate( 1.0 / ( 4.0 * ( dotNL + dotNV - dotNL * dotNV ) ) );
}
vec3 BRDF_Sheen( const in vec3 lightDir, const in vec3 viewDir, const in vec3 normal, vec3 sheenColor, const in float sheenRoughness ) {
	vec3 halfDir = normalize( lightDir + viewDir );
	float dotNL = saturate( dot( normal, lightDir ) );
	float dotNV = saturate( dot( normal, viewDir ) );
	float dotNH = saturate( dot( normal, halfDir ) );
	float D = D_Charlie( sheenRoughness, dotNH );
	float V = V_Neubelt( dotNV, dotNL );
	return sheenColor * ( D * V );
}
#endif
float IBLSheenBRDF( const in vec3 normal, const in vec3 viewDir, const in float roughness ) {
	float dotNV = saturate( dot( normal, viewDir ) );
	float r2 = roughness * roughness;
	float rInv = 1.0 / ( roughness + 0.1 );
	float a = -1.9362 + 1.0678 * roughness + 0.4573 * r2 - 0.8469 * rInv;
	float b = -0.6014 + 0.5538 * roughness - 0.4670 * r2 - 0.1255 * rInv;
	float DG = exp( a * dotNV + b );
	return saturate( DG );
}
vec3 EnvironmentBRDF( const in vec3 normal, const in vec3 viewDir, const in vec3 specularColor, const in float specularF90, const in float roughness ) {
	float dotNV = saturate( dot( normal, viewDir ) );
	vec2 fab = texture2D( dfgLUT, vec2( roughness, dotNV ) ).rg;
	return specularColor * fab.x + specularF90 * fab.y;
}
#ifdef USE_IRIDESCENCE
void computeMultiscatteringIridescence( const in vec3 normal, const in vec3 viewDir, const in vec3 specularColor, const in float specularF90, const in float iridescence, const in vec3 iridescenceF0, const in float roughness, inout vec3 singleScatter, inout vec3 multiScatter ) {
#else
void computeMultiscattering( const in vec3 normal, const in vec3 viewDir, const in vec3 specularColor, const in float specularF90, const in float roughness, inout vec3 singleScatter, inout vec3 multiScatter ) {
#endif
	float dotNV = saturate( dot( normal, viewDir ) );
	vec2 fab = texture2D( dfgLUT, vec2( roughness, dotNV ) ).rg;
	#ifdef USE_IRIDESCENCE
		vec3 Fr = mix( specularColor, iridescenceF0, iridescence );
	#else
		vec3 Fr = specularColor;
	#endif
	vec3 FssEss = Fr * fab.x + specularF90 * fab.y;
	float Ess = fab.x + fab.y;
	float Ems = 1.0 - Ess;
	vec3 Favg = Fr + ( 1.0 - Fr ) * 0.047619;	vec3 Fms = FssEss * Favg / ( 1.0 - Ems * Favg );
	singleScatter += FssEss;
	multiScatter += Fms * Ems;
}
vec3 BRDF_GGX_Multiscatter( const in vec3 lightDir, const in vec3 viewDir, const in vec3 normal, const in PhysicalMaterial material ) {
	vec3 singleScatter = BRDF_GGX( lightDir, viewDir, normal, material );
	float dotNL = saturate( dot( normal, lightDir ) );
	float dotNV = saturate( dot( normal, viewDir ) );
	vec2 dfgV = texture2D( dfgLUT, vec2( material.roughness, dotNV ) ).rg;
	vec2 dfgL = texture2D( dfgLUT, vec2( material.roughness, dotNL ) ).rg;
	vec3 FssEss_V = material.specularColorBlended * dfgV.x + material.specularF90 * dfgV.y;
	vec3 FssEss_L = material.specularColorBlended * dfgL.x + material.specularF90 * dfgL.y;
	float Ess_V = dfgV.x + dfgV.y;
	float Ess_L = dfgL.x + dfgL.y;
	float Ems_V = 1.0 - Ess_V;
	float Ems_L = 1.0 - Ess_L;
	vec3 Favg = material.specularColorBlended + ( 1.0 - material.specularColorBlended ) * 0.047619;
	vec3 Fms = FssEss_V * FssEss_L * Favg / ( 1.0 - Ems_V * Ems_L * Favg + EPSILON );
	float compensationFactor = Ems_V * Ems_L;
	vec3 multiScatter = Fms * compensationFactor;
	return singleScatter + multiScatter;
}
#if NUM_RECT_AREA_LIGHTS > 0
	void RE_Direct_RectArea_Physical( const in RectAreaLight rectAreaLight, const in vec3 geometryPosition, const in vec3 geometryNormal, const in vec3 geometryViewDir, const in vec3 geometryClearcoatNormal, const in PhysicalMaterial material, inout ReflectedLight reflectedLight ) {
		vec3 normal = geometryNormal;
		vec3 viewDir = geometryViewDir;
		vec3 position = geometryPosition;
		vec3 lightPos = rectAreaLight.position;
		vec3 halfWidth = rectAreaLight.halfWidth;
		vec3 halfHeight = rectAreaLight.halfHeight;
		vec3 lightColor = rectAreaLight.color;
		float roughness = material.roughness;
		vec3 rectCoords[ 4 ];
		rectCoords[ 0 ] = lightPos + halfWidth - halfHeight;		rectCoords[ 1 ] = lightPos - halfWidth - halfHeight;
		rectCoords[ 2 ] = lightPos - halfWidth + halfHeight;
		rectCoords[ 3 ] = lightPos + halfWidth + halfHeight;
		vec2 uv = LTC_Uv( normal, viewDir, roughness );
		vec4 t1 = texture2D( ltc_1, uv );
		vec4 t2 = texture2D( ltc_2, uv );
		mat3 mInv = mat3(
			vec3( t1.x, 0, t1.y ),
			vec3(    0, 1,    0 ),
			vec3( t1.z, 0, t1.w )
		);
		vec3 fresnel = ( material.specularColorBlended * t2.x + ( material.specularF90 - material.specularColorBlended ) * t2.y );
		reflectedLight.directSpecular += lightColor * fresnel * LTC_Evaluate( normal, viewDir, position, mInv, rectCoords );
		reflectedLight.directDiffuse += lightColor * material.diffuseContribution * LTC_Evaluate( normal, viewDir, position, mat3( 1.0 ), rectCoords );
		#ifdef USE_CLEARCOAT
			vec3 Ncc = geometryClearcoatNormal;
			vec2 uvClearcoat = LTC_Uv( Ncc, viewDir, material.clearcoatRoughness );
			vec4 t1Clearcoat = texture2D( ltc_1, uvClearcoat );
			vec4 t2Clearcoat = texture2D( ltc_2, uvClearcoat );
			mat3 mInvClearcoat = mat3(
				vec3( t1Clearcoat.x, 0, t1Clearcoat.y ),
				vec3(             0, 1,             0 ),
				vec3( t1Clearcoat.z, 0, t1Clearcoat.w )
			);
			vec3 fresnelClearcoat = material.clearcoatF0 * t2Clearcoat.x + ( material.clearcoatF90 - material.clearcoatF0 ) * t2Clearcoat.y;
			clearcoatSpecularDirect += lightColor * fresnelClearcoat * LTC_Evaluate( Ncc, viewDir, position, mInvClearcoat, rectCoords );
		#endif
	}
#endif
void RE_Direct_Physical( const in IncidentLight directLight, const in vec3 geometryPosition, const in vec3 geometryNormal, const in vec3 geometryViewDir, const in vec3 geometryClearcoatNormal, const in PhysicalMaterial material, inout ReflectedLight reflectedLight ) {
	float dotNL = saturate( dot( geometryNormal, directLight.direction ) );
	vec3 irradiance = dotNL * directLight.color;
	#ifdef USE_CLEARCOAT
		float dotNLcc = saturate( dot( geometryClearcoatNormal, directLight.direction ) );
		vec3 ccIrradiance = dotNLcc * directLight.color;
		clearcoatSpecularDirect += ccIrradiance * BRDF_GGX_Clearcoat( directLight.direction, geometryViewDir, geometryClearcoatNormal, material );
	#endif
	#ifdef USE_SHEEN
 
 		sheenSpecularDirect += irradiance * BRDF_Sheen( directLight.direction, geometryViewDir, geometryNormal, material.sheenColor, material.sheenRoughness );
 
 		float sheenAlbedoV = IBLSheenBRDF( geometryNormal, geometryViewDir, material.sheenRoughness );
 		float sheenAlbedoL = IBLSheenBRDF( geometryNormal, directLight.direction, material.sheenRoughness );
 
 		float sheenEnergyComp = 1.0 - max3( material.sheenColor ) * max( sheenAlbedoV, sheenAlbedoL );
 
 		irradiance *= sheenEnergyComp;
 
 	#endif
	reflectedLight.directSpecular += irradiance * BRDF_GGX_Multiscatter( directLight.direction, geometryViewDir, geometryNormal, material );
	reflectedLight.directDiffuse += irradiance * BRDF_Lambert( material.diffuseContribution );
}
void RE_IndirectDiffuse_Physical( const in vec3 irradiance, const in vec3 geometryPosition, const in vec3 geometryNormal, const in vec3 geometryViewDir, const in vec3 geometryClearcoatNormal, const in PhysicalMaterial material, inout ReflectedLight reflectedLight ) {
	vec3 diffuse = irradiance * BRDF_Lambert( material.diffuseContribution );
	#ifdef USE_SHEEN
		float sheenAlbedo = IBLSheenBRDF( geometryNormal, geometryViewDir, material.sheenRoughness );
		float sheenEnergyComp = 1.0 - max3( material.sheenColor ) * sheenAlbedo;
		diffuse *= sheenEnergyComp;
	#endif
	reflectedLight.indirectDiffuse += diffuse;
}
void RE_IndirectSpecular_Physical( const in vec3 radiance, const in vec3 irradiance, const in vec3 clearcoatRadiance, const in vec3 geometryPosition, const in vec3 geometryNormal, const in vec3 geometryViewDir, const in vec3 geometryClearcoatNormal, const in PhysicalMaterial material, inout ReflectedLight reflectedLight) {
	#ifdef USE_CLEARCOAT
		clearcoatSpecularIndirect += clearcoatRadiance * EnvironmentBRDF( geometryClearcoatNormal, geometryViewDir, material.clearcoatF0, material.clearcoatF90, material.clearcoatRoughness );
	#endif
	#ifdef USE_SHEEN
		sheenSpecularIndirect += irradiance * material.sheenColor * IBLSheenBRDF( geometryNormal, geometryViewDir, material.sheenRoughness ) * RECIPROCAL_PI;
 	#endif
	vec3 singleScatteringDielectric = vec3( 0.0 );
	vec3 multiScatteringDielectric = vec3( 0.0 );
	vec3 singleScatteringMetallic = vec3( 0.0 );
	vec3 multiScatteringMetallic = vec3( 0.0 );
	#ifdef USE_IRIDESCENCE
		computeMultiscatteringIridescence( geometryNormal, geometryViewDir, material.specularColor, material.specularF90, material.iridescence, material.iridescenceFresnelDielectric, material.roughness, singleScatteringDielectric, multiScatteringDielectric );
		computeMultiscatteringIridescence( geometryNormal, geometryViewDir, material.diffuseColor, material.specularF90, material.iridescence, material.iridescenceFresnelMetallic, material.roughness, singleScatteringMetallic, multiScatteringMetallic );
	#else
		computeMultiscattering( geometryNormal, geometryViewDir, material.specularColor, material.specularF90, material.roughness, singleScatteringDielectric, multiScatteringDielectric );
		computeMultiscattering( geometryNormal, geometryViewDir, material.diffuseColor, material.specularF90, material.roughness, singleScatteringMetallic, multiScatteringMetallic );
	#endif
	vec3 singleScattering = mix( singleScatteringDielectric, singleScatteringMetallic, material.metalness );
	vec3 multiScattering = mix( multiScatteringDielectric, multiScatteringMetallic, material.metalness );
	vec3 totalScatteringDielectric = singleScatteringDielectric + multiScatteringDielectric;
	vec3 diffuse = material.diffuseContribution * ( 1.0 - totalScatteringDielectric );
	vec3 cosineWeightedIrradiance = irradiance * RECIPROCAL_PI;
	vec3 indirectSpecular = radiance * singleScattering;
	indirectSpecular += multiScattering * cosineWeightedIrradiance;
	vec3 indirectDiffuse = diffuse * cosineWeightedIrradiance;
	#ifdef USE_SHEEN
		float sheenAlbedo = IBLSheenBRDF( geometryNormal, geometryViewDir, material.sheenRoughness );
		float sheenEnergyComp = 1.0 - max3( material.sheenColor ) * sheenAlbedo;
		indirectSpecular *= sheenEnergyComp;
		indirectDiffuse *= sheenEnergyComp;
	#endif
	reflectedLight.indirectSpecular += indirectSpecular;
	reflectedLight.indirectDiffuse += indirectDiffuse;
}
#define RE_Direct				RE_Direct_Physical
#define RE_Direct_RectArea		RE_Direct_RectArea_Physical
#define RE_IndirectDiffuse		RE_IndirectDiffuse_Physical
#define RE_IndirectSpecular		RE_IndirectSpecular_Physical
float computeSpecularOcclusion( const in float dotNV, const in float ambientOcclusion, const in float roughness ) {
	return saturate( pow( dotNV + ambientOcclusion, exp2( - 16.0 * roughness - 1.0 ) ) - 1.0 + ambientOcclusion );
}`,lights_fragment_begin:`
vec3 geometryPosition = - vViewPosition;
vec3 geometryNormal = normal;
vec3 geometryViewDir = ( isOrthographic ) ? vec3( 0, 0, 1 ) : normalize( vViewPosition );
vec3 geometryClearcoatNormal = vec3( 0.0 );
#ifdef USE_CLEARCOAT
	geometryClearcoatNormal = clearcoatNormal;
#endif
#ifdef USE_IRIDESCENCE
	float dotNVi = saturate( dot( normal, geometryViewDir ) );
	if ( material.iridescenceThickness == 0.0 ) {
		material.iridescence = 0.0;
	} else {
		material.iridescence = saturate( material.iridescence );
	}
	if ( material.iridescence > 0.0 ) {
		material.iridescenceFresnelDielectric = evalIridescence( 1.0, material.iridescenceIOR, dotNVi, material.iridescenceThickness, material.specularColor );
		material.iridescenceFresnelMetallic = evalIridescence( 1.0, material.iridescenceIOR, dotNVi, material.iridescenceThickness, material.diffuseColor );
		material.iridescenceFresnel = mix( material.iridescenceFresnelDielectric, material.iridescenceFresnelMetallic, material.metalness );
		material.iridescenceF0 = Schlick_to_F0( material.iridescenceFresnel, 1.0, dotNVi );
	}
#endif
IncidentLight directLight;
#if ( NUM_POINT_LIGHTS > 0 ) && defined( RE_Direct )
	PointLight pointLight;
	#if defined( USE_SHADOWMAP ) && NUM_POINT_LIGHT_SHADOWS > 0
	PointLightShadow pointLightShadow;
	#endif
	#pragma unroll_loop_start
	for ( int i = 0; i < NUM_POINT_LIGHTS; i ++ ) {
		pointLight = pointLights[ i ];
		getPointLightInfo( pointLight, geometryPosition, directLight );
		#if defined( USE_SHADOWMAP ) && ( UNROLLED_LOOP_INDEX < NUM_POINT_LIGHT_SHADOWS ) && ( defined( SHADOWMAP_TYPE_PCF ) || defined( SHADOWMAP_TYPE_BASIC ) )
		pointLightShadow = pointLightShadows[ i ];
		directLight.color *= ( directLight.visible && receiveShadow ) ? getPointShadow( pointShadowMap[ i ], pointLightShadow.shadowMapSize, pointLightShadow.shadowIntensity, pointLightShadow.shadowBias, pointLightShadow.shadowRadius, vPointShadowCoord[ i ], pointLightShadow.shadowCameraNear, pointLightShadow.shadowCameraFar ) : 1.0;
		#endif
		RE_Direct( directLight, geometryPosition, geometryNormal, geometryViewDir, geometryClearcoatNormal, material, reflectedLight );
	}
	#pragma unroll_loop_end
#endif
#if ( NUM_SPOT_LIGHTS > 0 ) && defined( RE_Direct )
	SpotLight spotLight;
	vec4 spotColor;
	vec3 spotLightCoord;
	bool inSpotLightMap;
	#if defined( USE_SHADOWMAP ) && NUM_SPOT_LIGHT_SHADOWS > 0
	SpotLightShadow spotLightShadow;
	#endif
	#pragma unroll_loop_start
	for ( int i = 0; i < NUM_SPOT_LIGHTS; i ++ ) {
		spotLight = spotLights[ i ];
		getSpotLightInfo( spotLight, geometryPosition, directLight );
		#if ( UNROLLED_LOOP_INDEX < NUM_SPOT_LIGHT_SHADOWS_WITH_MAPS )
		#define SPOT_LIGHT_MAP_INDEX UNROLLED_LOOP_INDEX
		#elif ( UNROLLED_LOOP_INDEX < NUM_SPOT_LIGHT_SHADOWS )
		#define SPOT_LIGHT_MAP_INDEX NUM_SPOT_LIGHT_MAPS
		#else
		#define SPOT_LIGHT_MAP_INDEX ( UNROLLED_LOOP_INDEX - NUM_SPOT_LIGHT_SHADOWS + NUM_SPOT_LIGHT_SHADOWS_WITH_MAPS )
		#endif
		#if ( SPOT_LIGHT_MAP_INDEX < NUM_SPOT_LIGHT_MAPS )
			spotLightCoord = vSpotLightCoord[ i ].xyz / vSpotLightCoord[ i ].w;
			inSpotLightMap = all( lessThan( abs( spotLightCoord * 2. - 1. ), vec3( 1.0 ) ) );
			spotColor = texture2D( spotLightMap[ SPOT_LIGHT_MAP_INDEX ], spotLightCoord.xy );
			directLight.color = inSpotLightMap ? directLight.color * spotColor.rgb : directLight.color;
		#endif
		#undef SPOT_LIGHT_MAP_INDEX
		#if defined( USE_SHADOWMAP ) && ( UNROLLED_LOOP_INDEX < NUM_SPOT_LIGHT_SHADOWS )
		spotLightShadow = spotLightShadows[ i ];
		directLight.color *= ( directLight.visible && receiveShadow ) ? getShadow( spotShadowMap[ i ], spotLightShadow.shadowMapSize, spotLightShadow.shadowIntensity, spotLightShadow.shadowBias, spotLightShadow.shadowRadius, vSpotLightCoord[ i ] ) : 1.0;
		#endif
		RE_Direct( directLight, geometryPosition, geometryNormal, geometryViewDir, geometryClearcoatNormal, material, reflectedLight );
	}
	#pragma unroll_loop_end
#endif
#if ( NUM_DIR_LIGHTS > 0 ) && defined( RE_Direct )
	DirectionalLight directionalLight;
	#if defined( USE_SHADOWMAP ) && NUM_DIR_LIGHT_SHADOWS > 0
	DirectionalLightShadow directionalLightShadow;
	#endif
	#pragma unroll_loop_start
	for ( int i = 0; i < NUM_DIR_LIGHTS; i ++ ) {
		directionalLight = directionalLights[ i ];
		getDirectionalLightInfo( directionalLight, directLight );
		#if defined( USE_SHADOWMAP ) && ( UNROLLED_LOOP_INDEX < NUM_DIR_LIGHT_SHADOWS )
		directionalLightShadow = directionalLightShadows[ i ];
		directLight.color *= ( directLight.visible && receiveShadow ) ? getShadow( directionalShadowMap[ i ], directionalLightShadow.shadowMapSize, directionalLightShadow.shadowIntensity, directionalLightShadow.shadowBias, directionalLightShadow.shadowRadius, vDirectionalShadowCoord[ i ] ) : 1.0;
		#endif
		RE_Direct( directLight, geometryPosition, geometryNormal, geometryViewDir, geometryClearcoatNormal, material, reflectedLight );
	}
	#pragma unroll_loop_end
#endif
#if ( NUM_RECT_AREA_LIGHTS > 0 ) && defined( RE_Direct_RectArea )
	RectAreaLight rectAreaLight;
	#pragma unroll_loop_start
	for ( int i = 0; i < NUM_RECT_AREA_LIGHTS; i ++ ) {
		rectAreaLight = rectAreaLights[ i ];
		RE_Direct_RectArea( rectAreaLight, geometryPosition, geometryNormal, geometryViewDir, geometryClearcoatNormal, material, reflectedLight );
	}
	#pragma unroll_loop_end
#endif
#if defined( RE_IndirectDiffuse )
	vec3 iblIrradiance = vec3( 0.0 );
	vec3 irradiance = getAmbientLightIrradiance( ambientLightColor );
	#if defined( USE_LIGHT_PROBES )
		irradiance += getLightProbeIrradiance( lightProbe, geometryNormal );
	#endif
	#if ( NUM_HEMI_LIGHTS > 0 )
		#pragma unroll_loop_start
		for ( int i = 0; i < NUM_HEMI_LIGHTS; i ++ ) {
			irradiance += getHemisphereLightIrradiance( hemisphereLights[ i ], geometryNormal );
		}
		#pragma unroll_loop_end
	#endif
	#ifdef USE_LIGHT_PROBES_GRID
		vec3 probeWorldPos = ( ( vec4( geometryPosition, 1.0 ) - viewMatrix[ 3 ] ) * viewMatrix ).xyz;
		vec3 probeWorldNormal = transformNormalByInverseViewMatrix( geometryNormal, viewMatrix );
		irradiance += getLightProbeGridIrradiance( probeWorldPos, probeWorldNormal );
	#endif
#endif
#if defined( RE_IndirectSpecular )
	vec3 radiance = vec3( 0.0 );
	vec3 clearcoatRadiance = vec3( 0.0 );
#endif`,lights_fragment_maps:`#if defined( RE_IndirectDiffuse )
	#ifdef USE_LIGHTMAP
		vec4 lightMapTexel = texture2D( lightMap, vLightMapUv );
		vec3 lightMapIrradiance = lightMapTexel.rgb * lightMapIntensity;
		irradiance += lightMapIrradiance;
	#endif
	#if defined( USE_ENVMAP ) && defined( ENVMAP_TYPE_CUBE_UV )
		#if defined( STANDARD ) || defined( LAMBERT ) || defined( PHONG )
			iblIrradiance += getIBLIrradiance( geometryNormal );
		#endif
	#endif
#endif
#if defined( USE_ENVMAP ) && defined( RE_IndirectSpecular )
	#ifdef USE_ANISOTROPY
		radiance += getIBLAnisotropyRadiance( geometryViewDir, geometryNormal, material.roughness, material.anisotropyB, material.anisotropy );
	#else
		radiance += getIBLRadiance( geometryViewDir, geometryNormal, material.roughness );
	#endif
	#ifdef USE_CLEARCOAT
		clearcoatRadiance += getIBLRadiance( geometryViewDir, geometryClearcoatNormal, material.clearcoatRoughness );
	#endif
#endif`,lights_fragment_end:`#if defined( RE_IndirectDiffuse )
	#if defined( LAMBERT ) || defined( PHONG )
		irradiance += iblIrradiance;
	#endif
	RE_IndirectDiffuse( irradiance, geometryPosition, geometryNormal, geometryViewDir, geometryClearcoatNormal, material, reflectedLight );
#endif
#if defined( RE_IndirectSpecular )
	RE_IndirectSpecular( radiance, iblIrradiance, clearcoatRadiance, geometryPosition, geometryNormal, geometryViewDir, geometryClearcoatNormal, material, reflectedLight );
#endif`,lightprobes_pars_fragment:`#ifdef USE_LIGHT_PROBES_GRID
uniform highp sampler3D probesSH;
uniform vec3 probesMin;
uniform vec3 probesMax;
uniform vec3 probesResolution;
vec3 getLightProbeGridIrradiance( vec3 worldPos, vec3 worldNormal ) {
	vec3 res = probesResolution;
	vec3 gridRange = probesMax - probesMin;
	vec3 resMinusOne = res - 1.0;
	vec3 probeSpacing = gridRange / resMinusOne;
	vec3 samplePos = worldPos + worldNormal * probeSpacing * 0.5;
	vec3 uvw = clamp( ( samplePos - probesMin ) / gridRange, 0.0, 1.0 );
	uvw = uvw * resMinusOne / res + 0.5 / res;
	float nz          = res.z;
	float paddedSlices = nz + 2.0;
	float atlasDepth  = 7.0 * paddedSlices;
	float uvZBase     = uvw.z * nz + 1.0;
	vec4 s0 = texture( probesSH, vec3( uvw.xy, ( uvZBase                       ) / atlasDepth ) );
	vec4 s1 = texture( probesSH, vec3( uvw.xy, ( uvZBase +       paddedSlices   ) / atlasDepth ) );
	vec4 s2 = texture( probesSH, vec3( uvw.xy, ( uvZBase + 2.0 * paddedSlices   ) / atlasDepth ) );
	vec4 s3 = texture( probesSH, vec3( uvw.xy, ( uvZBase + 3.0 * paddedSlices   ) / atlasDepth ) );
	vec4 s4 = texture( probesSH, vec3( uvw.xy, ( uvZBase + 4.0 * paddedSlices   ) / atlasDepth ) );
	vec4 s5 = texture( probesSH, vec3( uvw.xy, ( uvZBase + 5.0 * paddedSlices   ) / atlasDepth ) );
	vec4 s6 = texture( probesSH, vec3( uvw.xy, ( uvZBase + 6.0 * paddedSlices   ) / atlasDepth ) );
	vec3 c0 = s0.xyz;
	vec3 c1 = vec3( s0.w, s1.xy );
	vec3 c2 = vec3( s1.zw, s2.x );
	vec3 c3 = s2.yzw;
	vec3 c4 = s3.xyz;
	vec3 c5 = vec3( s3.w, s4.xy );
	vec3 c6 = vec3( s4.zw, s5.x );
	vec3 c7 = s5.yzw;
	vec3 c8 = s6.xyz;
	float x = worldNormal.x, y = worldNormal.y, z = worldNormal.z;
	vec3 result = c0 * 0.886227;
	result += c1 * 2.0 * 0.511664 * y;
	result += c2 * 2.0 * 0.511664 * z;
	result += c3 * 2.0 * 0.511664 * x;
	result += c4 * 2.0 * 0.429043 * x * y;
	result += c5 * 2.0 * 0.429043 * y * z;
	result += c6 * ( 0.743125 * z * z - 0.247708 );
	result += c7 * 2.0 * 0.429043 * x * z;
	result += c8 * 0.429043 * ( x * x - y * y );
	return max( result, vec3( 0.0 ) );
}
#endif`,logdepthbuf_fragment:`#if defined( USE_LOGARITHMIC_DEPTH_BUFFER )
	gl_FragDepth = vIsPerspective == 0.0 ? gl_FragCoord.z : log2( vFragDepth ) * logDepthBufFC * 0.5;
#endif`,logdepthbuf_pars_fragment:`#if defined( USE_LOGARITHMIC_DEPTH_BUFFER )
	uniform float logDepthBufFC;
	varying float vFragDepth;
	varying float vIsPerspective;
#endif`,logdepthbuf_pars_vertex:`#ifdef USE_LOGARITHMIC_DEPTH_BUFFER
	varying float vFragDepth;
	varying float vIsPerspective;
#endif`,logdepthbuf_vertex:`#ifdef USE_LOGARITHMIC_DEPTH_BUFFER
	vFragDepth = 1.0 + gl_Position.w;
	vIsPerspective = float( isPerspectiveMatrix( projectionMatrix ) );
#endif`,map_fragment:`#ifdef USE_MAP
	vec4 sampledDiffuseColor = texture2D( map, vMapUv );
	#ifdef DECODE_VIDEO_TEXTURE
		sampledDiffuseColor = sRGBTransferEOTF( sampledDiffuseColor );
	#endif
	diffuseColor *= sampledDiffuseColor;
#endif`,map_pars_fragment:`#ifdef USE_MAP
	uniform sampler2D map;
#endif`,map_particle_fragment:`#if defined( USE_MAP ) || defined( USE_ALPHAMAP )
	#if defined( USE_POINTS_UV )
		vec2 uv = vUv;
	#else
		vec2 uv = ( uvTransform * vec3( gl_PointCoord.x, 1.0 - gl_PointCoord.y, 1 ) ).xy;
	#endif
#endif
#ifdef USE_MAP
	diffuseColor *= texture2D( map, uv );
#endif
#ifdef USE_ALPHAMAP
	diffuseColor.a *= texture2D( alphaMap, uv ).g;
#endif`,map_particle_pars_fragment:`#if defined( USE_POINTS_UV )
	varying vec2 vUv;
#else
	#if defined( USE_MAP ) || defined( USE_ALPHAMAP )
		uniform mat3 uvTransform;
	#endif
#endif
#ifdef USE_MAP
	uniform sampler2D map;
#endif
#ifdef USE_ALPHAMAP
	uniform sampler2D alphaMap;
#endif`,metalnessmap_fragment:`float metalnessFactor = metalness;
#ifdef USE_METALNESSMAP
	vec4 texelMetalness = texture2D( metalnessMap, vMetalnessMapUv );
	metalnessFactor *= texelMetalness.b;
#endif`,metalnessmap_pars_fragment:`#ifdef USE_METALNESSMAP
	uniform sampler2D metalnessMap;
#endif`,morphinstance_vertex:`#ifdef USE_INSTANCING_MORPH
	float morphTargetInfluences[ MORPHTARGETS_COUNT ];
	float morphTargetBaseInfluence = texelFetch( morphTexture, ivec2( 0, gl_InstanceID ), 0 ).r;
	for ( int i = 0; i < MORPHTARGETS_COUNT; i ++ ) {
		morphTargetInfluences[i] =  texelFetch( morphTexture, ivec2( i + 1, gl_InstanceID ), 0 ).r;
	}
#endif`,morphcolor_vertex:`#if defined( USE_MORPHCOLORS )
	vColor *= morphTargetBaseInfluence;
	for ( int i = 0; i < MORPHTARGETS_COUNT; i ++ ) {
		#if defined( USE_COLOR_ALPHA )
			if ( morphTargetInfluences[ i ] != 0.0 ) vColor += getMorph( gl_VertexID, i, 2 ) * morphTargetInfluences[ i ];
		#elif defined( USE_COLOR )
			if ( morphTargetInfluences[ i ] != 0.0 ) vColor += getMorph( gl_VertexID, i, 2 ).rgb * morphTargetInfluences[ i ];
		#endif
	}
#endif`,morphnormal_vertex:`#ifdef USE_MORPHNORMALS
	objectNormal *= morphTargetBaseInfluence;
	for ( int i = 0; i < MORPHTARGETS_COUNT; i ++ ) {
		if ( morphTargetInfluences[ i ] != 0.0 ) objectNormal += getMorph( gl_VertexID, i, 1 ).xyz * morphTargetInfluences[ i ];
	}
#endif`,morphtarget_pars_vertex:`#ifdef USE_MORPHTARGETS
	#ifndef USE_INSTANCING_MORPH
		uniform float morphTargetBaseInfluence;
		uniform float morphTargetInfluences[ MORPHTARGETS_COUNT ];
	#endif
	uniform sampler2DArray morphTargetsTexture;
	uniform ivec2 morphTargetsTextureSize;
	vec4 getMorph( const in int vertexIndex, const in int morphTargetIndex, const in int offset ) {
		int texelIndex = vertexIndex * MORPHTARGETS_TEXTURE_STRIDE + offset;
		int y = texelIndex / morphTargetsTextureSize.x;
		int x = texelIndex - y * morphTargetsTextureSize.x;
		ivec3 morphUV = ivec3( x, y, morphTargetIndex );
		return texelFetch( morphTargetsTexture, morphUV, 0 );
	}
#endif`,morphtarget_vertex:`#ifdef USE_MORPHTARGETS
	transformed *= morphTargetBaseInfluence;
	for ( int i = 0; i < MORPHTARGETS_COUNT; i ++ ) {
		if ( morphTargetInfluences[ i ] != 0.0 ) transformed += getMorph( gl_VertexID, i, 0 ).xyz * morphTargetInfluences[ i ];
	}
#endif`,normal_fragment_begin:`float faceDirection = gl_FrontFacing ? 1.0 : - 1.0;
#ifdef FLAT_SHADED
	vec3 fdx = dFdx( vViewPosition );
	vec3 fdy = dFdy( vViewPosition );
	vec3 normal = normalize( cross( fdx, fdy ) );
#else
	vec3 normal = normalize( vNormal );
	#ifdef DOUBLE_SIDED
		normal *= faceDirection;
	#endif
#endif
#if defined( USE_NORMALMAP_TANGENTSPACE ) || defined( USE_CLEARCOAT_NORMALMAP ) || defined( USE_ANISOTROPY )
	#ifdef USE_TANGENT
		mat3 tbn = mat3( normalize( vTangent ), normalize( vBitangent ), normal );
	#else
		mat3 tbn = getTangentFrame( - vViewPosition, normal,
		#if defined( USE_NORMALMAP )
			vNormalMapUv
		#elif defined( USE_CLEARCOAT_NORMALMAP )
			vClearcoatNormalMapUv
		#else
			vUv
		#endif
		);
	#endif
	#ifdef DOUBLE_SIDED
		tbn[0] *= faceDirection;
		tbn[1] *= faceDirection;
	#endif
#endif
#ifdef USE_CLEARCOAT_NORMALMAP
	#ifdef USE_TANGENT
		mat3 tbn2 = mat3( normalize( vTangent ), normalize( vBitangent ), normal );
	#else
		mat3 tbn2 = getTangentFrame( - vViewPosition, normal, vClearcoatNormalMapUv );
	#endif
	#ifdef DOUBLE_SIDED
		tbn2[0] *= faceDirection;
		tbn2[1] *= faceDirection;
	#endif
#endif
vec3 nonPerturbedNormal = normal;`,normal_fragment_maps:`#ifdef USE_NORMALMAP_OBJECTSPACE
	normal = texture2D( normalMap, vNormalMapUv ).xyz * 2.0 - 1.0;
	#ifdef FLIP_SIDED
		normal = - normal;
	#endif
	#ifdef DOUBLE_SIDED
		normal = normal * faceDirection;
	#endif
	normal = normalize( normalMatrix * normal );
#elif defined( USE_NORMALMAP_TANGENTSPACE )
	vec3 mapN = texture2D( normalMap, vNormalMapUv ).xyz * 2.0 - 1.0;
	#if defined( USE_PACKED_NORMALMAP )
		mapN = vec3( mapN.xy, sqrt( saturate( 1.0 - dot( mapN.xy, mapN.xy ) ) ) );
	#endif
	mapN.xy *= normalScale;
	normal = normalize( tbn * mapN );
#elif defined( USE_BUMPMAP )
	normal = perturbNormalArb( - vViewPosition, normal, dHdxy_fwd(), faceDirection );
#endif`,normal_pars_fragment:`#ifndef FLAT_SHADED
	varying vec3 vNormal;
	#ifdef USE_TANGENT
		varying vec3 vTangent;
		varying vec3 vBitangent;
	#endif
#endif`,normal_pars_vertex:`#ifndef FLAT_SHADED
	varying vec3 vNormal;
	#ifdef USE_TANGENT
		varying vec3 vTangent;
		varying vec3 vBitangent;
	#endif
#endif`,normal_vertex:`#ifndef FLAT_SHADED
	vNormal = normalize( transformedNormal );
	#ifdef USE_TANGENT
		vTangent = normalize( transformedTangent );
		vBitangent = normalize( cross( vNormal, vTangent ) * tangent.w );
		#ifdef FLIP_SIDED
			vBitangent = - vBitangent;
		#endif
	#endif
#endif`,normalmap_pars_fragment:`#ifdef USE_NORMALMAP
	uniform sampler2D normalMap;
	uniform vec2 normalScale;
#endif
#ifdef USE_NORMALMAP_OBJECTSPACE
	uniform mat3 normalMatrix;
#endif
#if ! defined ( USE_TANGENT ) && ( defined ( USE_NORMALMAP_TANGENTSPACE ) || defined ( USE_CLEARCOAT_NORMALMAP ) || defined( USE_ANISOTROPY ) )
	mat3 getTangentFrame( vec3 eye_pos, vec3 surf_norm, vec2 uv ) {
		vec3 q0 = dFdx( eye_pos.xyz );
		vec3 q1 = dFdy( eye_pos.xyz );
		vec2 st0 = dFdx( uv.st );
		vec2 st1 = dFdy( uv.st );
		vec3 N = surf_norm;
		vec3 q1perp = cross( q1, N );
		vec3 q0perp = cross( N, q0 );
		vec3 T = q1perp * st0.x + q0perp * st1.x;
		vec3 B = q1perp * st0.y + q0perp * st1.y;
		float det = max( dot( T, T ), dot( B, B ) );
		float scale = ( det == 0.0 ) ? 0.0 : inversesqrt( det );
		return mat3( T * scale, B * scale, N );
	}
#endif`,clearcoat_normal_fragment_begin:`#ifdef USE_CLEARCOAT
	vec3 clearcoatNormal = nonPerturbedNormal;
#endif`,clearcoat_normal_fragment_maps:`#ifdef USE_CLEARCOAT_NORMALMAP
	vec3 clearcoatMapN = texture2D( clearcoatNormalMap, vClearcoatNormalMapUv ).xyz * 2.0 - 1.0;
	clearcoatMapN.xy *= clearcoatNormalScale;
	clearcoatNormal = normalize( tbn2 * clearcoatMapN );
#endif`,clearcoat_pars_fragment:`#ifdef USE_CLEARCOATMAP
	uniform sampler2D clearcoatMap;
#endif
#ifdef USE_CLEARCOAT_NORMALMAP
	uniform sampler2D clearcoatNormalMap;
	uniform vec2 clearcoatNormalScale;
#endif
#ifdef USE_CLEARCOAT_ROUGHNESSMAP
	uniform sampler2D clearcoatRoughnessMap;
#endif`,iridescence_pars_fragment:`#ifdef USE_IRIDESCENCEMAP
	uniform sampler2D iridescenceMap;
#endif
#ifdef USE_IRIDESCENCE_THICKNESSMAP
	uniform sampler2D iridescenceThicknessMap;
#endif`,opaque_fragment:`#ifdef OPAQUE
diffuseColor.a = 1.0;
#endif
#ifdef USE_TRANSMISSION
diffuseColor.a *= material.transmissionAlpha;
#endif
gl_FragColor = vec4( outgoingLight, diffuseColor.a );`,packing:`vec3 packNormalToRGB( const in vec3 normal ) {
	return normalize( normal ) * 0.5 + 0.5;
}
vec3 unpackRGBToNormal( const in vec3 rgb ) {
	return 2.0 * rgb.xyz - 1.0;
}
const float PackUpscale = 256. / 255.;const float UnpackDownscale = 255. / 256.;const float ShiftRight8 = 1. / 256.;
const float Inv255 = 1. / 255.;
const vec4 PackFactors = vec4( 1.0, 256.0, 256.0 * 256.0, 256.0 * 256.0 * 256.0 );
const vec2 UnpackFactors2 = vec2( UnpackDownscale, 1.0 / PackFactors.g );
const vec3 UnpackFactors3 = vec3( UnpackDownscale / PackFactors.rg, 1.0 / PackFactors.b );
const vec4 UnpackFactors4 = vec4( UnpackDownscale / PackFactors.rgb, 1.0 / PackFactors.a );
vec4 packDepthToRGBA( const in float v ) {
	if( v <= 0.0 )
		return vec4( 0., 0., 0., 0. );
	if( v >= 1.0 )
		return vec4( 1., 1., 1., 1. );
	float vuf;
	float af = modf( v * PackFactors.a, vuf );
	float bf = modf( vuf * ShiftRight8, vuf );
	float gf = modf( vuf * ShiftRight8, vuf );
	return vec4( vuf * Inv255, gf * PackUpscale, bf * PackUpscale, af );
}
vec3 packDepthToRGB( const in float v ) {
	if( v <= 0.0 )
		return vec3( 0., 0., 0. );
	if( v >= 1.0 )
		return vec3( 1., 1., 1. );
	float vuf;
	float bf = modf( v * PackFactors.b, vuf );
	float gf = modf( vuf * ShiftRight8, vuf );
	return vec3( vuf * Inv255, gf * PackUpscale, bf );
}
vec2 packDepthToRG( const in float v ) {
	if( v <= 0.0 )
		return vec2( 0., 0. );
	if( v >= 1.0 )
		return vec2( 1., 1. );
	float vuf;
	float gf = modf( v * 256., vuf );
	return vec2( vuf * Inv255, gf );
}
float unpackRGBAToDepth( const in vec4 v ) {
	return dot( v, UnpackFactors4 );
}
float unpackRGBToDepth( const in vec3 v ) {
	return dot( v, UnpackFactors3 );
}
float unpackRGToDepth( const in vec2 v ) {
	return v.r * UnpackFactors2.r + v.g * UnpackFactors2.g;
}
vec4 pack2HalfToRGBA( const in vec2 v ) {
	vec4 r = vec4( v.x, fract( v.x * 255.0 ), v.y, fract( v.y * 255.0 ) );
	return vec4( r.x - r.y / 255.0, r.y, r.z - r.w / 255.0, r.w );
}
vec2 unpackRGBATo2Half( const in vec4 v ) {
	return vec2( v.x + ( v.y / 255.0 ), v.z + ( v.w / 255.0 ) );
}
float viewZToOrthographicDepth( const in float viewZ, const in float near, const in float far ) {
	return ( viewZ + near ) / ( near - far );
}
float orthographicDepthToViewZ( const in float depth, const in float near, const in float far ) {
	#ifdef USE_REVERSED_DEPTH_BUFFER
	
		return depth * ( far - near ) - far;
	#else
		return depth * ( near - far ) - near;
	#endif
}
float viewZToPerspectiveDepth( const in float viewZ, const in float near, const in float far ) {
	return ( ( near + viewZ ) * far ) / ( ( far - near ) * viewZ );
}
float perspectiveDepthToViewZ( const in float depth, const in float near, const in float far ) {
	
	#ifdef USE_REVERSED_DEPTH_BUFFER
		return ( near * far ) / ( ( near - far ) * depth - near );
	#else
		return ( near * far ) / ( ( far - near ) * depth - far );
	#endif
}`,premultiplied_alpha_fragment:`#ifdef PREMULTIPLIED_ALPHA
	gl_FragColor.rgb *= gl_FragColor.a;
#endif`,project_vertex:`vec4 mvPosition = vec4( transformed, 1.0 );
#ifdef USE_BATCHING
	mvPosition = batchingMatrix * mvPosition;
#endif
#ifdef USE_INSTANCING
	mvPosition = instanceMatrix * mvPosition;
#endif
mvPosition = modelViewMatrix * mvPosition;
gl_Position = projectionMatrix * mvPosition;`,dithering_fragment:`#ifdef DITHERING
	gl_FragColor.rgb = dithering( gl_FragColor.rgb );
#endif`,dithering_pars_fragment:`#ifdef DITHERING
	vec3 dithering( vec3 color ) {
		float grid_position = rand( gl_FragCoord.xy );
		vec3 dither_shift_RGB = vec3( 0.25 / 255.0, -0.25 / 255.0, 0.25 / 255.0 );
		dither_shift_RGB = mix( 2.0 * dither_shift_RGB, -2.0 * dither_shift_RGB, grid_position );
		return color + dither_shift_RGB;
	}
#endif`,roughnessmap_fragment:`float roughnessFactor = roughness;
#ifdef USE_ROUGHNESSMAP
	vec4 texelRoughness = texture2D( roughnessMap, vRoughnessMapUv );
	roughnessFactor *= texelRoughness.g;
#endif`,roughnessmap_pars_fragment:`#ifdef USE_ROUGHNESSMAP
	uniform sampler2D roughnessMap;
#endif`,shadowmap_pars_fragment:`#if NUM_SPOT_LIGHT_COORDS > 0
	varying vec4 vSpotLightCoord[ NUM_SPOT_LIGHT_COORDS ];
#endif
#if NUM_SPOT_LIGHT_MAPS > 0
	uniform sampler2D spotLightMap[ NUM_SPOT_LIGHT_MAPS ];
#endif
#ifdef USE_SHADOWMAP
	#if NUM_DIR_LIGHT_SHADOWS > 0
		#if defined( SHADOWMAP_TYPE_PCF )
			uniform sampler2DShadow directionalShadowMap[ NUM_DIR_LIGHT_SHADOWS ];
		#else
			uniform sampler2D directionalShadowMap[ NUM_DIR_LIGHT_SHADOWS ];
		#endif
		varying vec4 vDirectionalShadowCoord[ NUM_DIR_LIGHT_SHADOWS ];
		struct DirectionalLightShadow {
			float shadowIntensity;
			float shadowBias;
			float shadowNormalBias;
			float shadowRadius;
			vec2 shadowMapSize;
		};
		uniform DirectionalLightShadow directionalLightShadows[ NUM_DIR_LIGHT_SHADOWS ];
	#endif
	#if NUM_SPOT_LIGHT_SHADOWS > 0
		#if defined( SHADOWMAP_TYPE_PCF )
			uniform sampler2DShadow spotShadowMap[ NUM_SPOT_LIGHT_SHADOWS ];
		#else
			uniform sampler2D spotShadowMap[ NUM_SPOT_LIGHT_SHADOWS ];
		#endif
		struct SpotLightShadow {
			float shadowIntensity;
			float shadowBias;
			float shadowNormalBias;
			float shadowRadius;
			vec2 shadowMapSize;
		};
		uniform SpotLightShadow spotLightShadows[ NUM_SPOT_LIGHT_SHADOWS ];
	#endif
	#if NUM_POINT_LIGHT_SHADOWS > 0
		#if defined( SHADOWMAP_TYPE_PCF )
			uniform samplerCubeShadow pointShadowMap[ NUM_POINT_LIGHT_SHADOWS ];
		#elif defined( SHADOWMAP_TYPE_BASIC )
			uniform samplerCube pointShadowMap[ NUM_POINT_LIGHT_SHADOWS ];
		#endif
		varying vec4 vPointShadowCoord[ NUM_POINT_LIGHT_SHADOWS ];
		struct PointLightShadow {
			float shadowIntensity;
			float shadowBias;
			float shadowNormalBias;
			float shadowRadius;
			vec2 shadowMapSize;
			float shadowCameraNear;
			float shadowCameraFar;
		};
		uniform PointLightShadow pointLightShadows[ NUM_POINT_LIGHT_SHADOWS ];
	#endif
	#if defined( SHADOWMAP_TYPE_PCF )
		float interleavedGradientNoise( vec2 position ) {
			return fract( 52.9829189 * fract( dot( position, vec2( 0.06711056, 0.00583715 ) ) ) );
		}
		vec2 vogelDiskSample( int sampleIndex, int samplesCount, float phi ) {
			const float goldenAngle = 2.399963229728653;
			float r = sqrt( ( float( sampleIndex ) + 0.5 ) / float( samplesCount ) );
			float theta = float( sampleIndex ) * goldenAngle + phi;
			return vec2( cos( theta ), sin( theta ) ) * r;
		}
	#endif
	#if defined( SHADOWMAP_TYPE_PCF )
		float getShadow( sampler2DShadow shadowMap, vec2 shadowMapSize, float shadowIntensity, float shadowBias, float shadowRadius, vec4 shadowCoord ) {
			float shadow = 1.0;
			shadowCoord.xyz /= shadowCoord.w;
			shadowCoord.z += shadowBias;
			bool inFrustum = shadowCoord.x >= 0.0 && shadowCoord.x <= 1.0 && shadowCoord.y >= 0.0 && shadowCoord.y <= 1.0;
			bool frustumTest = inFrustum && shadowCoord.z <= 1.0;
			if ( frustumTest ) {
				vec2 texelSize = vec2( 1.0 ) / shadowMapSize;
				float radius = shadowRadius * texelSize.x;
				float phi = interleavedGradientNoise( gl_FragCoord.xy ) * PI2;
				shadow = (
					texture( shadowMap, vec3( shadowCoord.xy + vogelDiskSample( 0, 5, phi ) * radius, shadowCoord.z ) ) +
					texture( shadowMap, vec3( shadowCoord.xy + vogelDiskSample( 1, 5, phi ) * radius, shadowCoord.z ) ) +
					texture( shadowMap, vec3( shadowCoord.xy + vogelDiskSample( 2, 5, phi ) * radius, shadowCoord.z ) ) +
					texture( shadowMap, vec3( shadowCoord.xy + vogelDiskSample( 3, 5, phi ) * radius, shadowCoord.z ) ) +
					texture( shadowMap, vec3( shadowCoord.xy + vogelDiskSample( 4, 5, phi ) * radius, shadowCoord.z ) )
				) * 0.2;
			}
			return mix( 1.0, shadow, shadowIntensity );
		}
	#elif defined( SHADOWMAP_TYPE_VSM )
		float getShadow( sampler2D shadowMap, vec2 shadowMapSize, float shadowIntensity, float shadowBias, float shadowRadius, vec4 shadowCoord ) {
			float shadow = 1.0;
			shadowCoord.xyz /= shadowCoord.w;
			#ifdef USE_REVERSED_DEPTH_BUFFER
				shadowCoord.z -= shadowBias;
			#else
				shadowCoord.z += shadowBias;
			#endif
			bool inFrustum = shadowCoord.x >= 0.0 && shadowCoord.x <= 1.0 && shadowCoord.y >= 0.0 && shadowCoord.y <= 1.0;
			bool frustumTest = inFrustum && shadowCoord.z <= 1.0;
			if ( frustumTest ) {
				vec2 distribution = texture2D( shadowMap, shadowCoord.xy ).rg;
				float mean = distribution.x;
				float variance = distribution.y * distribution.y;
				#ifdef USE_REVERSED_DEPTH_BUFFER
					float hard_shadow = step( mean, shadowCoord.z );
				#else
					float hard_shadow = step( shadowCoord.z, mean );
				#endif
				
				if ( hard_shadow == 1.0 ) {
					shadow = 1.0;
				} else {
					variance = max( variance, 0.0000001 );
					float d = shadowCoord.z - mean;
					float p_max = variance / ( variance + d * d );
					p_max = clamp( ( p_max - 0.3 ) / 0.65, 0.0, 1.0 );
					shadow = max( hard_shadow, p_max );
				}
			}
			return mix( 1.0, shadow, shadowIntensity );
		}
	#else
		float getShadow( sampler2D shadowMap, vec2 shadowMapSize, float shadowIntensity, float shadowBias, float shadowRadius, vec4 shadowCoord ) {
			float shadow = 1.0;
			shadowCoord.xyz /= shadowCoord.w;
			#ifdef USE_REVERSED_DEPTH_BUFFER
				shadowCoord.z -= shadowBias;
			#else
				shadowCoord.z += shadowBias;
			#endif
			bool inFrustum = shadowCoord.x >= 0.0 && shadowCoord.x <= 1.0 && shadowCoord.y >= 0.0 && shadowCoord.y <= 1.0;
			bool frustumTest = inFrustum && shadowCoord.z <= 1.0;
			if ( frustumTest ) {
				float depth = texture2D( shadowMap, shadowCoord.xy ).r;
				#ifdef USE_REVERSED_DEPTH_BUFFER
					shadow = step( depth, shadowCoord.z );
				#else
					shadow = step( shadowCoord.z, depth );
				#endif
			}
			return mix( 1.0, shadow, shadowIntensity );
		}
	#endif
	#if NUM_POINT_LIGHT_SHADOWS > 0
	#if defined( SHADOWMAP_TYPE_PCF )
	float getPointShadow( samplerCubeShadow shadowMap, vec2 shadowMapSize, float shadowIntensity, float shadowBias, float shadowRadius, vec4 shadowCoord, float shadowCameraNear, float shadowCameraFar ) {
		float shadow = 1.0;
		vec3 lightToPosition = shadowCoord.xyz;
		vec3 bd3D = normalize( lightToPosition );
		vec3 absVec = abs( lightToPosition );
		float viewSpaceZ = max( max( absVec.x, absVec.y ), absVec.z );
		if ( viewSpaceZ - shadowCameraFar <= 0.0 && viewSpaceZ - shadowCameraNear >= 0.0 ) {
			#ifdef USE_REVERSED_DEPTH_BUFFER
				float dp = ( shadowCameraNear * ( shadowCameraFar - viewSpaceZ ) ) / ( viewSpaceZ * ( shadowCameraFar - shadowCameraNear ) );
				dp -= shadowBias;
			#else
				float dp = ( shadowCameraFar * ( viewSpaceZ - shadowCameraNear ) ) / ( viewSpaceZ * ( shadowCameraFar - shadowCameraNear ) );
				dp += shadowBias;
			#endif
			float texelSize = shadowRadius / shadowMapSize.x;
			vec3 absDir = abs( bd3D );
			vec3 tangent = absDir.x > absDir.z ? vec3( 0.0, 1.0, 0.0 ) : vec3( 1.0, 0.0, 0.0 );
			tangent = normalize( cross( bd3D, tangent ) );
			vec3 bitangent = cross( bd3D, tangent );
			float phi = interleavedGradientNoise( gl_FragCoord.xy ) * PI2;
			vec2 sample0 = vogelDiskSample( 0, 5, phi );
			vec2 sample1 = vogelDiskSample( 1, 5, phi );
			vec2 sample2 = vogelDiskSample( 2, 5, phi );
			vec2 sample3 = vogelDiskSample( 3, 5, phi );
			vec2 sample4 = vogelDiskSample( 4, 5, phi );
			shadow = (
				texture( shadowMap, vec4( bd3D + ( tangent * sample0.x + bitangent * sample0.y ) * texelSize, dp ) ) +
				texture( shadowMap, vec4( bd3D + ( tangent * sample1.x + bitangent * sample1.y ) * texelSize, dp ) ) +
				texture( shadowMap, vec4( bd3D + ( tangent * sample2.x + bitangent * sample2.y ) * texelSize, dp ) ) +
				texture( shadowMap, vec4( bd3D + ( tangent * sample3.x + bitangent * sample3.y ) * texelSize, dp ) ) +
				texture( shadowMap, vec4( bd3D + ( tangent * sample4.x + bitangent * sample4.y ) * texelSize, dp ) )
			) * 0.2;
		}
		return mix( 1.0, shadow, shadowIntensity );
	}
	#elif defined( SHADOWMAP_TYPE_BASIC )
	float getPointShadow( samplerCube shadowMap, vec2 shadowMapSize, float shadowIntensity, float shadowBias, float shadowRadius, vec4 shadowCoord, float shadowCameraNear, float shadowCameraFar ) {
		float shadow = 1.0;
		vec3 lightToPosition = shadowCoord.xyz;
		vec3 absVec = abs( lightToPosition );
		float viewSpaceZ = max( max( absVec.x, absVec.y ), absVec.z );
		if ( viewSpaceZ - shadowCameraFar <= 0.0 && viewSpaceZ - shadowCameraNear >= 0.0 ) {
			float dp = ( shadowCameraFar * ( viewSpaceZ - shadowCameraNear ) ) / ( viewSpaceZ * ( shadowCameraFar - shadowCameraNear ) );
			dp += shadowBias;
			vec3 bd3D = normalize( lightToPosition );
			float depth = textureCube( shadowMap, bd3D ).r;
			#ifdef USE_REVERSED_DEPTH_BUFFER
				depth = 1.0 - depth;
			#endif
			shadow = step( dp, depth );
		}
		return mix( 1.0, shadow, shadowIntensity );
	}
	#endif
	#endif
#endif`,shadowmap_pars_vertex:`#if NUM_SPOT_LIGHT_COORDS > 0
	uniform mat4 spotLightMatrix[ NUM_SPOT_LIGHT_COORDS ];
	varying vec4 vSpotLightCoord[ NUM_SPOT_LIGHT_COORDS ];
#endif
#ifdef USE_SHADOWMAP
	#if NUM_DIR_LIGHT_SHADOWS > 0
		uniform mat4 directionalShadowMatrix[ NUM_DIR_LIGHT_SHADOWS ];
		varying vec4 vDirectionalShadowCoord[ NUM_DIR_LIGHT_SHADOWS ];
		struct DirectionalLightShadow {
			float shadowIntensity;
			float shadowBias;
			float shadowNormalBias;
			float shadowRadius;
			vec2 shadowMapSize;
		};
		uniform DirectionalLightShadow directionalLightShadows[ NUM_DIR_LIGHT_SHADOWS ];
	#endif
	#if NUM_SPOT_LIGHT_SHADOWS > 0
		struct SpotLightShadow {
			float shadowIntensity;
			float shadowBias;
			float shadowNormalBias;
			float shadowRadius;
			vec2 shadowMapSize;
		};
		uniform SpotLightShadow spotLightShadows[ NUM_SPOT_LIGHT_SHADOWS ];
	#endif
	#if NUM_POINT_LIGHT_SHADOWS > 0
		uniform mat4 pointShadowMatrix[ NUM_POINT_LIGHT_SHADOWS ];
		varying vec4 vPointShadowCoord[ NUM_POINT_LIGHT_SHADOWS ];
		struct PointLightShadow {
			float shadowIntensity;
			float shadowBias;
			float shadowNormalBias;
			float shadowRadius;
			vec2 shadowMapSize;
			float shadowCameraNear;
			float shadowCameraFar;
		};
		uniform PointLightShadow pointLightShadows[ NUM_POINT_LIGHT_SHADOWS ];
	#endif
#endif`,shadowmap_vertex:`#if ( defined( USE_SHADOWMAP ) && ( NUM_DIR_LIGHT_SHADOWS > 0 || NUM_POINT_LIGHT_SHADOWS > 0 ) ) || ( NUM_SPOT_LIGHT_COORDS > 0 )
	#ifdef HAS_NORMAL
		vec3 shadowWorldNormal = transformNormalByInverseViewMatrix( transformedNormal, viewMatrix );
	#else
		vec3 shadowWorldNormal = vec3( 0.0 );
	#endif
	vec4 shadowWorldPosition;
#endif
#if defined( USE_SHADOWMAP )
	#if NUM_DIR_LIGHT_SHADOWS > 0
		#pragma unroll_loop_start
		for ( int i = 0; i < NUM_DIR_LIGHT_SHADOWS; i ++ ) {
			shadowWorldPosition = worldPosition + vec4( shadowWorldNormal * directionalLightShadows[ i ].shadowNormalBias, 0 );
			vDirectionalShadowCoord[ i ] = directionalShadowMatrix[ i ] * shadowWorldPosition;
		}
		#pragma unroll_loop_end
	#endif
	#if NUM_POINT_LIGHT_SHADOWS > 0
		#pragma unroll_loop_start
		for ( int i = 0; i < NUM_POINT_LIGHT_SHADOWS; i ++ ) {
			shadowWorldPosition = worldPosition + vec4( shadowWorldNormal * pointLightShadows[ i ].shadowNormalBias, 0 );
			vPointShadowCoord[ i ] = pointShadowMatrix[ i ] * shadowWorldPosition;
		}
		#pragma unroll_loop_end
	#endif
#endif
#if NUM_SPOT_LIGHT_COORDS > 0
	#pragma unroll_loop_start
	for ( int i = 0; i < NUM_SPOT_LIGHT_COORDS; i ++ ) {
		shadowWorldPosition = worldPosition;
		#if ( defined( USE_SHADOWMAP ) && UNROLLED_LOOP_INDEX < NUM_SPOT_LIGHT_SHADOWS )
			shadowWorldPosition.xyz += shadowWorldNormal * spotLightShadows[ i ].shadowNormalBias;
		#endif
		vSpotLightCoord[ i ] = spotLightMatrix[ i ] * shadowWorldPosition;
	}
	#pragma unroll_loop_end
#endif`,shadowmask_pars_fragment:`float getShadowMask() {
	float shadow = 1.0;
	#ifdef USE_SHADOWMAP
	#if NUM_DIR_LIGHT_SHADOWS > 0
	DirectionalLightShadow directionalLight;
	#pragma unroll_loop_start
	for ( int i = 0; i < NUM_DIR_LIGHT_SHADOWS; i ++ ) {
		directionalLight = directionalLightShadows[ i ];
		shadow *= receiveShadow ? getShadow( directionalShadowMap[ i ], directionalLight.shadowMapSize, directionalLight.shadowIntensity, directionalLight.shadowBias, directionalLight.shadowRadius, vDirectionalShadowCoord[ i ] ) : 1.0;
	}
	#pragma unroll_loop_end
	#endif
	#if NUM_SPOT_LIGHT_SHADOWS > 0
	SpotLightShadow spotLight;
	#pragma unroll_loop_start
	for ( int i = 0; i < NUM_SPOT_LIGHT_SHADOWS; i ++ ) {
		spotLight = spotLightShadows[ i ];
		shadow *= receiveShadow ? getShadow( spotShadowMap[ i ], spotLight.shadowMapSize, spotLight.shadowIntensity, spotLight.shadowBias, spotLight.shadowRadius, vSpotLightCoord[ i ] ) : 1.0;
	}
	#pragma unroll_loop_end
	#endif
	#if NUM_POINT_LIGHT_SHADOWS > 0 && ( defined( SHADOWMAP_TYPE_PCF ) || defined( SHADOWMAP_TYPE_BASIC ) )
	PointLightShadow pointLight;
	#pragma unroll_loop_start
	for ( int i = 0; i < NUM_POINT_LIGHT_SHADOWS; i ++ ) {
		pointLight = pointLightShadows[ i ];
		shadow *= receiveShadow ? getPointShadow( pointShadowMap[ i ], pointLight.shadowMapSize, pointLight.shadowIntensity, pointLight.shadowBias, pointLight.shadowRadius, vPointShadowCoord[ i ], pointLight.shadowCameraNear, pointLight.shadowCameraFar ) : 1.0;
	}
	#pragma unroll_loop_end
	#endif
	#endif
	return shadow;
}`,skinbase_vertex:`#ifdef USE_SKINNING
	mat4 boneMatX = getBoneMatrix( skinIndex.x );
	mat4 boneMatY = getBoneMatrix( skinIndex.y );
	mat4 boneMatZ = getBoneMatrix( skinIndex.z );
	mat4 boneMatW = getBoneMatrix( skinIndex.w );
#endif`,skinning_pars_vertex:`#ifdef USE_SKINNING
	uniform mat4 bindMatrix;
	uniform mat4 bindMatrixInverse;
	uniform highp sampler2D boneTexture;
	mat4 getBoneMatrix( const in float i ) {
		int size = textureSize( boneTexture, 0 ).x;
		int j = int( i ) * 4;
		int x = j % size;
		int y = j / size;
		vec4 v1 = texelFetch( boneTexture, ivec2( x, y ), 0 );
		vec4 v2 = texelFetch( boneTexture, ivec2( x + 1, y ), 0 );
		vec4 v3 = texelFetch( boneTexture, ivec2( x + 2, y ), 0 );
		vec4 v4 = texelFetch( boneTexture, ivec2( x + 3, y ), 0 );
		return mat4( v1, v2, v3, v4 );
	}
#endif`,skinning_vertex:`#ifdef USE_SKINNING
	vec4 skinVertex = bindMatrix * vec4( transformed, 1.0 );
	vec4 skinned = vec4( 0.0 );
	skinned += boneMatX * skinVertex * skinWeight.x;
	skinned += boneMatY * skinVertex * skinWeight.y;
	skinned += boneMatZ * skinVertex * skinWeight.z;
	skinned += boneMatW * skinVertex * skinWeight.w;
	transformed = ( bindMatrixInverse * skinned ).xyz;
#endif`,skinnormal_vertex:`#ifdef USE_SKINNING
	mat4 skinMatrix = mat4( 0.0 );
	skinMatrix += skinWeight.x * boneMatX;
	skinMatrix += skinWeight.y * boneMatY;
	skinMatrix += skinWeight.z * boneMatZ;
	skinMatrix += skinWeight.w * boneMatW;
	skinMatrix = bindMatrixInverse * skinMatrix * bindMatrix;
	objectNormal = vec4( skinMatrix * vec4( objectNormal, 0.0 ) ).xyz;
	#ifdef USE_TANGENT
		objectTangent = vec4( skinMatrix * vec4( objectTangent, 0.0 ) ).xyz;
	#endif
#endif`,specularmap_fragment:`float specularStrength;
#ifdef USE_SPECULARMAP
	vec4 texelSpecular = texture2D( specularMap, vSpecularMapUv );
	specularStrength = texelSpecular.r;
#else
	specularStrength = 1.0;
#endif`,specularmap_pars_fragment:`#ifdef USE_SPECULARMAP
	uniform sampler2D specularMap;
#endif`,tonemapping_fragment:`#if defined( TONE_MAPPING )
	gl_FragColor.rgb = toneMapping( gl_FragColor.rgb );
#endif`,tonemapping_pars_fragment:`#ifndef saturate
#define saturate( a ) clamp( a, 0.0, 1.0 )
#endif
uniform float toneMappingExposure;
vec3 LinearToneMapping( vec3 color ) {
	return saturate( toneMappingExposure * color );
}
vec3 ReinhardToneMapping( vec3 color ) {
	color *= toneMappingExposure;
	return saturate( color / ( vec3( 1.0 ) + color ) );
}
vec3 CineonToneMapping( vec3 color ) {
	color *= toneMappingExposure;
	color = max( vec3( 0.0 ), color - 0.004 );
	return pow( ( color * ( 6.2 * color + 0.5 ) ) / ( color * ( 6.2 * color + 1.7 ) + 0.06 ), vec3( 2.2 ) );
}
vec3 RRTAndODTFit( vec3 v ) {
	vec3 a = v * ( v + 0.0245786 ) - 0.000090537;
	vec3 b = v * ( 0.983729 * v + 0.4329510 ) + 0.238081;
	return a / b;
}
vec3 ACESFilmicToneMapping( vec3 color ) {
	const mat3 ACESInputMat = mat3(
		vec3( 0.59719, 0.07600, 0.02840 ),		vec3( 0.35458, 0.90834, 0.13383 ),
		vec3( 0.04823, 0.01566, 0.83777 )
	);
	const mat3 ACESOutputMat = mat3(
		vec3(  1.60475, -0.10208, -0.00327 ),		vec3( -0.53108,  1.10813, -0.07276 ),
		vec3( -0.07367, -0.00605,  1.07602 )
	);
	color *= toneMappingExposure / 0.6;
	color = ACESInputMat * color;
	color = RRTAndODTFit( color );
	color = ACESOutputMat * color;
	return saturate( color );
}
const mat3 LINEAR_REC2020_TO_LINEAR_SRGB = mat3(
	vec3( 1.6605, - 0.1246, - 0.0182 ),
	vec3( - 0.5876, 1.1329, - 0.1006 ),
	vec3( - 0.0728, - 0.0083, 1.1187 )
);
const mat3 LINEAR_SRGB_TO_LINEAR_REC2020 = mat3(
	vec3( 0.6274, 0.0691, 0.0164 ),
	vec3( 0.3293, 0.9195, 0.0880 ),
	vec3( 0.0433, 0.0113, 0.8956 )
);
vec3 agxDefaultContrastApprox( vec3 x ) {
	vec3 x2 = x * x;
	vec3 x4 = x2 * x2;
	return + 15.5 * x4 * x2
		- 40.14 * x4 * x
		+ 31.96 * x4
		- 6.868 * x2 * x
		+ 0.4298 * x2
		+ 0.1191 * x
		- 0.00232;
}
vec3 AgXToneMapping( vec3 color ) {
	const mat3 AgXInsetMatrix = mat3(
		vec3( 0.856627153315983, 0.137318972929847, 0.11189821299995 ),
		vec3( 0.0951212405381588, 0.761241990602591, 0.0767994186031903 ),
		vec3( 0.0482516061458583, 0.101439036467562, 0.811302368396859 )
	);
	const mat3 AgXOutsetMatrix = mat3(
		vec3( 1.1271005818144368, - 0.1413297634984383, - 0.14132976349843826 ),
		vec3( - 0.11060664309660323, 1.157823702216272, - 0.11060664309660294 ),
		vec3( - 0.016493938717834573, - 0.016493938717834257, 1.2519364065950405 )
	);
	const float AgxMinEv = - 12.47393;	const float AgxMaxEv = 4.026069;
	color *= toneMappingExposure;
	color = LINEAR_SRGB_TO_LINEAR_REC2020 * color;
	color = AgXInsetMatrix * color;
	color = max( color, 1e-10 );	color = log2( color );
	color = ( color - AgxMinEv ) / ( AgxMaxEv - AgxMinEv );
	color = clamp( color, 0.0, 1.0 );
	color = agxDefaultContrastApprox( color );
	color = AgXOutsetMatrix * color;
	color = pow( max( vec3( 0.0 ), color ), vec3( 2.2 ) );
	color = LINEAR_REC2020_TO_LINEAR_SRGB * color;
	color = clamp( color, 0.0, 1.0 );
	return color;
}
vec3 NeutralToneMapping( vec3 color ) {
	const float StartCompression = 0.8 - 0.04;
	const float Desaturation = 0.15;
	color *= toneMappingExposure;
	float x = min( color.r, min( color.g, color.b ) );
	float offset = x < 0.08 ? x - 6.25 * x * x : 0.04;
	color -= offset;
	float peak = max( color.r, max( color.g, color.b ) );
	if ( peak < StartCompression ) return color;
	float d = 1. - StartCompression;
	float newPeak = 1. - d * d / ( peak + d - StartCompression );
	color *= newPeak / peak;
	float g = 1. - 1. / ( Desaturation * ( peak - newPeak ) + 1. );
	return mix( color, vec3( newPeak ), g );
}
vec3 CustomToneMapping( vec3 color ) { return color; }`,transmission_fragment:`#ifdef USE_TRANSMISSION
	material.transmission = transmission;
	material.transmissionAlpha = 1.0;
	material.thickness = thickness;
	material.attenuationDistance = attenuationDistance;
	material.attenuationColor = attenuationColor;
	#ifdef USE_TRANSMISSIONMAP
		material.transmission *= texture2D( transmissionMap, vTransmissionMapUv ).r;
	#endif
	#ifdef USE_THICKNESSMAP
		material.thickness *= texture2D( thicknessMap, vThicknessMapUv ).g;
	#endif
	vec3 pos = vWorldPosition;
	vec3 v = normalize( cameraPosition - pos );
	vec3 n = transformNormalByInverseViewMatrix( normal, viewMatrix );
	vec4 transmitted = getIBLVolumeRefraction(
		n, v, material.roughness, material.diffuseContribution, material.specularColorBlended, material.specularF90,
		pos, modelMatrix, viewMatrix, projectionMatrix, material.dispersion, material.ior, material.thickness,
		material.attenuationColor, material.attenuationDistance );
	material.transmissionAlpha = mix( material.transmissionAlpha, transmitted.a, material.transmission );
	totalDiffuse = mix( totalDiffuse, transmitted.rgb, material.transmission );
#endif`,transmission_pars_fragment:`#ifdef USE_TRANSMISSION
	uniform float transmission;
	uniform float thickness;
	uniform float attenuationDistance;
	uniform vec3 attenuationColor;
	#ifdef USE_TRANSMISSIONMAP
		uniform sampler2D transmissionMap;
	#endif
	#ifdef USE_THICKNESSMAP
		uniform sampler2D thicknessMap;
	#endif
	uniform vec2 transmissionSamplerSize;
	uniform sampler2D transmissionSamplerMap;
	uniform mat4 modelMatrix;
	uniform mat4 projectionMatrix;
	varying vec3 vWorldPosition;
	float w0( float a ) {
		return ( 1.0 / 6.0 ) * ( a * ( a * ( - a + 3.0 ) - 3.0 ) + 1.0 );
	}
	float w1( float a ) {
		return ( 1.0 / 6.0 ) * ( a *  a * ( 3.0 * a - 6.0 ) + 4.0 );
	}
	float w2( float a ){
		return ( 1.0 / 6.0 ) * ( a * ( a * ( - 3.0 * a + 3.0 ) + 3.0 ) + 1.0 );
	}
	float w3( float a ) {
		return ( 1.0 / 6.0 ) * ( a * a * a );
	}
	float g0( float a ) {
		return w0( a ) + w1( a );
	}
	float g1( float a ) {
		return w2( a ) + w3( a );
	}
	float h0( float a ) {
		return - 1.0 + w1( a ) / ( w0( a ) + w1( a ) );
	}
	float h1( float a ) {
		return 1.0 + w3( a ) / ( w2( a ) + w3( a ) );
	}
	vec4 bicubic( sampler2D tex, vec2 uv, vec4 texelSize, float lod ) {
		uv = uv * texelSize.zw + 0.5;
		vec2 iuv = floor( uv );
		vec2 fuv = fract( uv );
		float g0x = g0( fuv.x );
		float g1x = g1( fuv.x );
		float h0x = h0( fuv.x );
		float h1x = h1( fuv.x );
		float h0y = h0( fuv.y );
		float h1y = h1( fuv.y );
		vec2 p0 = ( vec2( iuv.x + h0x, iuv.y + h0y ) - 0.5 ) * texelSize.xy;
		vec2 p1 = ( vec2( iuv.x + h1x, iuv.y + h0y ) - 0.5 ) * texelSize.xy;
		vec2 p2 = ( vec2( iuv.x + h0x, iuv.y + h1y ) - 0.5 ) * texelSize.xy;
		vec2 p3 = ( vec2( iuv.x + h1x, iuv.y + h1y ) - 0.5 ) * texelSize.xy;
		return g0( fuv.y ) * ( g0x * textureLod( tex, p0, lod ) + g1x * textureLod( tex, p1, lod ) ) +
			g1( fuv.y ) * ( g0x * textureLod( tex, p2, lod ) + g1x * textureLod( tex, p3, lod ) );
	}
	vec4 textureBicubic( sampler2D sampler, vec2 uv, float lod ) {
		vec2 fLodSize = vec2( textureSize( sampler, int( lod ) ) );
		vec2 cLodSize = vec2( textureSize( sampler, int( lod + 1.0 ) ) );
		vec2 fLodSizeInv = 1.0 / fLodSize;
		vec2 cLodSizeInv = 1.0 / cLodSize;
		vec4 fSample = bicubic( sampler, uv, vec4( fLodSizeInv, fLodSize ), floor( lod ) );
		vec4 cSample = bicubic( sampler, uv, vec4( cLodSizeInv, cLodSize ), ceil( lod ) );
		return mix( fSample, cSample, fract( lod ) );
	}
	vec3 getVolumeTransmissionRay( const in vec3 n, const in vec3 v, const in float thickness, const in float ior, const in mat4 modelMatrix ) {
		vec3 refractionVector = refract( - v, normalize( n ), 1.0 / ior );
		vec3 modelScale;
		modelScale.x = length( vec3( modelMatrix[ 0 ].xyz ) );
		modelScale.y = length( vec3( modelMatrix[ 1 ].xyz ) );
		modelScale.z = length( vec3( modelMatrix[ 2 ].xyz ) );
		return normalize( refractionVector ) * thickness * modelScale;
	}
	float applyIorToRoughness( const in float roughness, const in float ior ) {
		return roughness * clamp( ior * 2.0 - 2.0, 0.0, 1.0 );
	}
	vec4 getTransmissionSample( const in vec2 fragCoord, const in float roughness, const in float ior ) {
		float lod = log2( transmissionSamplerSize.x ) * applyIorToRoughness( roughness, ior );
		return textureBicubic( transmissionSamplerMap, fragCoord.xy, lod );
	}
	vec3 volumeAttenuation( const in float transmissionDistance, const in vec3 attenuationColor, const in float attenuationDistance ) {
		if ( isinf( attenuationDistance ) ) {
			return vec3( 1.0 );
		} else {
			vec3 attenuationCoefficient = -log( attenuationColor ) / attenuationDistance;
			vec3 transmittance = exp( - attenuationCoefficient * transmissionDistance );			return transmittance;
		}
	}
	vec4 getIBLVolumeRefraction( const in vec3 n, const in vec3 v, const in float roughness, const in vec3 diffuseColor,
		const in vec3 specularColor, const in float specularF90, const in vec3 position, const in mat4 modelMatrix,
		const in mat4 viewMatrix, const in mat4 projMatrix, const in float dispersion, const in float ior, const in float thickness,
		const in vec3 attenuationColor, const in float attenuationDistance ) {
		vec4 transmittedLight;
		vec3 transmittance;
		#ifdef USE_DISPERSION
			float halfSpread = ( ior - 1.0 ) * 0.025 * dispersion;
			vec3 iors = vec3( ior - halfSpread, ior, ior + halfSpread );
			for ( int i = 0; i < 3; i ++ ) {
				vec3 transmissionRay = getVolumeTransmissionRay( n, v, thickness, iors[ i ], modelMatrix );
				vec3 refractedRayExit = position + transmissionRay;
				vec4 ndcPos = projMatrix * viewMatrix * vec4( refractedRayExit, 1.0 );
				vec2 refractionCoords = ndcPos.xy / ndcPos.w;
				refractionCoords += 1.0;
				refractionCoords /= 2.0;
				vec4 transmissionSample = getTransmissionSample( refractionCoords, roughness, iors[ i ] );
				transmittedLight[ i ] = transmissionSample[ i ];
				transmittedLight.a += transmissionSample.a;
				transmittance[ i ] = diffuseColor[ i ] * volumeAttenuation( length( transmissionRay ), attenuationColor, attenuationDistance )[ i ];
			}
			transmittedLight.a /= 3.0;
		#else
			vec3 transmissionRay = getVolumeTransmissionRay( n, v, thickness, ior, modelMatrix );
			vec3 refractedRayExit = position + transmissionRay;
			vec4 ndcPos = projMatrix * viewMatrix * vec4( refractedRayExit, 1.0 );
			vec2 refractionCoords = ndcPos.xy / ndcPos.w;
			refractionCoords += 1.0;
			refractionCoords /= 2.0;
			transmittedLight = getTransmissionSample( refractionCoords, roughness, ior );
			transmittance = diffuseColor * volumeAttenuation( length( transmissionRay ), attenuationColor, attenuationDistance );
		#endif
		vec3 attenuatedColor = transmittance * transmittedLight.rgb;
		vec3 F = EnvironmentBRDF( n, v, specularColor, specularF90, roughness );
		float transmittanceFactor = ( transmittance.r + transmittance.g + transmittance.b ) / 3.0;
		return vec4( ( 1.0 - F ) * attenuatedColor, 1.0 - ( 1.0 - transmittedLight.a ) * transmittanceFactor );
	}
#endif`,uv_pars_fragment:`#if defined( USE_UV ) || defined( USE_ANISOTROPY )
	varying vec2 vUv;
#endif
#ifdef USE_MAP
	varying vec2 vMapUv;
#endif
#ifdef USE_ALPHAMAP
	varying vec2 vAlphaMapUv;
#endif
#ifdef USE_LIGHTMAP
	varying vec2 vLightMapUv;
#endif
#ifdef USE_AOMAP
	varying vec2 vAoMapUv;
#endif
#ifdef USE_BUMPMAP
	varying vec2 vBumpMapUv;
#endif
#ifdef USE_NORMALMAP
	varying vec2 vNormalMapUv;
#endif
#ifdef USE_EMISSIVEMAP
	varying vec2 vEmissiveMapUv;
#endif
#ifdef USE_METALNESSMAP
	varying vec2 vMetalnessMapUv;
#endif
#ifdef USE_ROUGHNESSMAP
	varying vec2 vRoughnessMapUv;
#endif
#ifdef USE_ANISOTROPYMAP
	varying vec2 vAnisotropyMapUv;
#endif
#ifdef USE_CLEARCOATMAP
	varying vec2 vClearcoatMapUv;
#endif
#ifdef USE_CLEARCOAT_NORMALMAP
	varying vec2 vClearcoatNormalMapUv;
#endif
#ifdef USE_CLEARCOAT_ROUGHNESSMAP
	varying vec2 vClearcoatRoughnessMapUv;
#endif
#ifdef USE_IRIDESCENCEMAP
	varying vec2 vIridescenceMapUv;
#endif
#ifdef USE_IRIDESCENCE_THICKNESSMAP
	varying vec2 vIridescenceThicknessMapUv;
#endif
#ifdef USE_SHEEN_COLORMAP
	varying vec2 vSheenColorMapUv;
#endif
#ifdef USE_SHEEN_ROUGHNESSMAP
	varying vec2 vSheenRoughnessMapUv;
#endif
#ifdef USE_SPECULARMAP
	varying vec2 vSpecularMapUv;
#endif
#ifdef USE_SPECULAR_COLORMAP
	varying vec2 vSpecularColorMapUv;
#endif
#ifdef USE_SPECULAR_INTENSITYMAP
	varying vec2 vSpecularIntensityMapUv;
#endif
#ifdef USE_TRANSMISSIONMAP
	uniform mat3 transmissionMapTransform;
	varying vec2 vTransmissionMapUv;
#endif
#ifdef USE_THICKNESSMAP
	uniform mat3 thicknessMapTransform;
	varying vec2 vThicknessMapUv;
#endif`,uv_pars_vertex:`#if defined( USE_UV ) || defined( USE_ANISOTROPY )
	varying vec2 vUv;
#endif
#ifdef USE_MAP
	uniform mat3 mapTransform;
	varying vec2 vMapUv;
#endif
#ifdef USE_ALPHAMAP
	uniform mat3 alphaMapTransform;
	varying vec2 vAlphaMapUv;
#endif
#ifdef USE_LIGHTMAP
	uniform mat3 lightMapTransform;
	varying vec2 vLightMapUv;
#endif
#ifdef USE_AOMAP
	uniform mat3 aoMapTransform;
	varying vec2 vAoMapUv;
#endif
#ifdef USE_BUMPMAP
	uniform mat3 bumpMapTransform;
	varying vec2 vBumpMapUv;
#endif
#ifdef USE_NORMALMAP
	uniform mat3 normalMapTransform;
	varying vec2 vNormalMapUv;
#endif
#ifdef USE_DISPLACEMENTMAP
	uniform mat3 displacementMapTransform;
	varying vec2 vDisplacementMapUv;
#endif
#ifdef USE_EMISSIVEMAP
	uniform mat3 emissiveMapTransform;
	varying vec2 vEmissiveMapUv;
#endif
#ifdef USE_METALNESSMAP
	uniform mat3 metalnessMapTransform;
	varying vec2 vMetalnessMapUv;
#endif
#ifdef USE_ROUGHNESSMAP
	uniform mat3 roughnessMapTransform;
	varying vec2 vRoughnessMapUv;
#endif
#ifdef USE_ANISOTROPYMAP
	uniform mat3 anisotropyMapTransform;
	varying vec2 vAnisotropyMapUv;
#endif
#ifdef USE_CLEARCOATMAP
	uniform mat3 clearcoatMapTransform;
	varying vec2 vClearcoatMapUv;
#endif
#ifdef USE_CLEARCOAT_NORMALMAP
	uniform mat3 clearcoatNormalMapTransform;
	varying vec2 vClearcoatNormalMapUv;
#endif
#ifdef USE_CLEARCOAT_ROUGHNESSMAP
	uniform mat3 clearcoatRoughnessMapTransform;
	varying vec2 vClearcoatRoughnessMapUv;
#endif
#ifdef USE_SHEEN_COLORMAP
	uniform mat3 sheenColorMapTransform;
	varying vec2 vSheenColorMapUv;
#endif
#ifdef USE_SHEEN_ROUGHNESSMAP
	uniform mat3 sheenRoughnessMapTransform;
	varying vec2 vSheenRoughnessMapUv;
#endif
#ifdef USE_IRIDESCENCEMAP
	uniform mat3 iridescenceMapTransform;
	varying vec2 vIridescenceMapUv;
#endif
#ifdef USE_IRIDESCENCE_THICKNESSMAP
	uniform mat3 iridescenceThicknessMapTransform;
	varying vec2 vIridescenceThicknessMapUv;
#endif
#ifdef USE_SPECULARMAP
	uniform mat3 specularMapTransform;
	varying vec2 vSpecularMapUv;
#endif
#ifdef USE_SPECULAR_COLORMAP
	uniform mat3 specularColorMapTransform;
	varying vec2 vSpecularColorMapUv;
#endif
#ifdef USE_SPECULAR_INTENSITYMAP
	uniform mat3 specularIntensityMapTransform;
	varying vec2 vSpecularIntensityMapUv;
#endif
#ifdef USE_TRANSMISSIONMAP
	uniform mat3 transmissionMapTransform;
	varying vec2 vTransmissionMapUv;
#endif
#ifdef USE_THICKNESSMAP
	uniform mat3 thicknessMapTransform;
	varying vec2 vThicknessMapUv;
#endif`,uv_vertex:`#if defined( USE_UV ) || defined( USE_ANISOTROPY )
	vUv = vec3( uv, 1 ).xy;
#endif
#ifdef USE_MAP
	vMapUv = ( mapTransform * vec3( MAP_UV, 1 ) ).xy;
#endif
#ifdef USE_ALPHAMAP
	vAlphaMapUv = ( alphaMapTransform * vec3( ALPHAMAP_UV, 1 ) ).xy;
#endif
#ifdef USE_LIGHTMAP
	vLightMapUv = ( lightMapTransform * vec3( LIGHTMAP_UV, 1 ) ).xy;
#endif
#ifdef USE_AOMAP
	vAoMapUv = ( aoMapTransform * vec3( AOMAP_UV, 1 ) ).xy;
#endif
#ifdef USE_BUMPMAP
	vBumpMapUv = ( bumpMapTransform * vec3( BUMPMAP_UV, 1 ) ).xy;
#endif
#ifdef USE_NORMALMAP
	vNormalMapUv = ( normalMapTransform * vec3( NORMALMAP_UV, 1 ) ).xy;
#endif
#ifdef USE_DISPLACEMENTMAP
	vDisplacementMapUv = ( displacementMapTransform * vec3( DISPLACEMENTMAP_UV, 1 ) ).xy;
#endif
#ifdef USE_EMISSIVEMAP
	vEmissiveMapUv = ( emissiveMapTransform * vec3( EMISSIVEMAP_UV, 1 ) ).xy;
#endif
#ifdef USE_METALNESSMAP
	vMetalnessMapUv = ( metalnessMapTransform * vec3( METALNESSMAP_UV, 1 ) ).xy;
#endif
#ifdef USE_ROUGHNESSMAP
	vRoughnessMapUv = ( roughnessMapTransform * vec3( ROUGHNESSMAP_UV, 1 ) ).xy;
#endif
#ifdef USE_ANISOTROPYMAP
	vAnisotropyMapUv = ( anisotropyMapTransform * vec3( ANISOTROPYMAP_UV, 1 ) ).xy;
#endif
#ifdef USE_CLEARCOATMAP
	vClearcoatMapUv = ( clearcoatMapTransform * vec3( CLEARCOATMAP_UV, 1 ) ).xy;
#endif
#ifdef USE_CLEARCOAT_NORMALMAP
	vClearcoatNormalMapUv = ( clearcoatNormalMapTransform * vec3( CLEARCOAT_NORMALMAP_UV, 1 ) ).xy;
#endif
#ifdef USE_CLEARCOAT_ROUGHNESSMAP
	vClearcoatRoughnessMapUv = ( clearcoatRoughnessMapTransform * vec3( CLEARCOAT_ROUGHNESSMAP_UV, 1 ) ).xy;
#endif
#ifdef USE_IRIDESCENCEMAP
	vIridescenceMapUv = ( iridescenceMapTransform * vec3( IRIDESCENCEMAP_UV, 1 ) ).xy;
#endif
#ifdef USE_IRIDESCENCE_THICKNESSMAP
	vIridescenceThicknessMapUv = ( iridescenceThicknessMapTransform * vec3( IRIDESCENCE_THICKNESSMAP_UV, 1 ) ).xy;
#endif
#ifdef USE_SHEEN_COLORMAP
	vSheenColorMapUv = ( sheenColorMapTransform * vec3( SHEEN_COLORMAP_UV, 1 ) ).xy;
#endif
#ifdef USE_SHEEN_ROUGHNESSMAP
	vSheenRoughnessMapUv = ( sheenRoughnessMapTransform * vec3( SHEEN_ROUGHNESSMAP_UV, 1 ) ).xy;
#endif
#ifdef USE_SPECULARMAP
	vSpecularMapUv = ( specularMapTransform * vec3( SPECULARMAP_UV, 1 ) ).xy;
#endif
#ifdef USE_SPECULAR_COLORMAP
	vSpecularColorMapUv = ( specularColorMapTransform * vec3( SPECULAR_COLORMAP_UV, 1 ) ).xy;
#endif
#ifdef USE_SPECULAR_INTENSITYMAP
	vSpecularIntensityMapUv = ( specularIntensityMapTransform * vec3( SPECULAR_INTENSITYMAP_UV, 1 ) ).xy;
#endif
#ifdef USE_TRANSMISSIONMAP
	vTransmissionMapUv = ( transmissionMapTransform * vec3( TRANSMISSIONMAP_UV, 1 ) ).xy;
#endif
#ifdef USE_THICKNESSMAP
	vThicknessMapUv = ( thicknessMapTransform * vec3( THICKNESSMAP_UV, 1 ) ).xy;
#endif`,worldpos_vertex:`#if defined( USE_ENVMAP ) || defined( DISTANCE ) || defined ( USE_SHADOWMAP ) || defined ( USE_TRANSMISSION ) || NUM_SPOT_LIGHT_COORDS > 0
	vec4 worldPosition = vec4( transformed, 1.0 );
	#ifdef USE_BATCHING
		worldPosition = batchingMatrix * worldPosition;
	#endif
	#ifdef USE_INSTANCING
		worldPosition = instanceMatrix * worldPosition;
	#endif
	worldPosition = modelMatrix * worldPosition;
#endif`,background_vert:`varying vec2 vUv;
uniform mat3 uvTransform;
void main() {
	vUv = ( uvTransform * vec3( uv, 1 ) ).xy;
	gl_Position = vec4( position.xy, 1.0, 1.0 );
}`,background_frag:`uniform sampler2D t2D;
uniform float backgroundIntensity;
varying vec2 vUv;
void main() {
	vec4 texColor = texture2D( t2D, vUv );
	#ifdef DECODE_VIDEO_TEXTURE
		texColor = vec4( mix( pow( texColor.rgb * 0.9478672986 + vec3( 0.0521327014 ), vec3( 2.4 ) ), texColor.rgb * 0.0773993808, vec3( lessThanEqual( texColor.rgb, vec3( 0.04045 ) ) ) ), texColor.w );
	#endif
	texColor.rgb *= backgroundIntensity;
	gl_FragColor = texColor;
	#include <tonemapping_fragment>
	#include <colorspace_fragment>
}`,backgroundCube_vert:`varying vec3 vWorldDirection;
#include <common>
void main() {
	vWorldDirection = transformDirection( position, modelMatrix );
	#include <begin_vertex>
	#include <project_vertex>
	gl_Position.z = gl_Position.w;
}`,backgroundCube_frag:`#ifdef ENVMAP_TYPE_CUBE
	uniform samplerCube envMap;
#elif defined( ENVMAP_TYPE_CUBE_UV )
	uniform sampler2D envMap;
#endif
uniform float backgroundBlurriness;
uniform float backgroundIntensity;
uniform mat3 backgroundRotation;
varying vec3 vWorldDirection;
#include <cube_uv_reflection_fragment>
void main() {
	#ifdef ENVMAP_TYPE_CUBE
		vec4 texColor = textureCube( envMap, backgroundRotation * vWorldDirection );
	#elif defined( ENVMAP_TYPE_CUBE_UV )
		vec4 texColor = textureCubeUV( envMap, backgroundRotation * vWorldDirection, backgroundBlurriness );
	#else
		vec4 texColor = vec4( 0.0, 0.0, 0.0, 1.0 );
	#endif
	texColor.rgb *= backgroundIntensity;
	gl_FragColor = texColor;
	#include <tonemapping_fragment>
	#include <colorspace_fragment>
}`,cube_vert:`varying vec3 vWorldDirection;
#include <common>
void main() {
	vWorldDirection = transformDirection( position, modelMatrix );
	#include <begin_vertex>
	#include <project_vertex>
	gl_Position.z = gl_Position.w;
}`,cube_frag:`uniform samplerCube tCube;
uniform float tFlip;
uniform float opacity;
varying vec3 vWorldDirection;
void main() {
	vec4 texColor = textureCube( tCube, vec3( tFlip * vWorldDirection.x, vWorldDirection.yz ) );
	gl_FragColor = texColor;
	gl_FragColor.a *= opacity;
	#include <tonemapping_fragment>
	#include <colorspace_fragment>
}`,depth_vert:`#include <common>
#include <batching_pars_vertex>
#include <uv_pars_vertex>
#include <displacementmap_pars_vertex>
#include <morphtarget_pars_vertex>
#include <skinning_pars_vertex>
#include <logdepthbuf_pars_vertex>
#include <clipping_planes_pars_vertex>
varying vec2 vHighPrecisionZW;
void main() {
	#include <uv_vertex>
	#include <batching_vertex>
	#include <skinbase_vertex>
	#include <morphinstance_vertex>
	#ifdef USE_DISPLACEMENTMAP
		#include <beginnormal_vertex>
		#include <morphnormal_vertex>
		#include <skinnormal_vertex>
	#endif
	#include <begin_vertex>
	#include <morphtarget_vertex>
	#include <skinning_vertex>
	#include <displacementmap_vertex>
	#include <project_vertex>
	#include <logdepthbuf_vertex>
	#include <clipping_planes_vertex>
	vHighPrecisionZW = gl_Position.zw;
}`,depth_frag:`#if DEPTH_PACKING == 3200
	uniform float opacity;
#endif
#include <common>
#include <packing>
#include <uv_pars_fragment>
#include <map_pars_fragment>
#include <alphamap_pars_fragment>
#include <alphatest_pars_fragment>
#include <alphahash_pars_fragment>
#include <logdepthbuf_pars_fragment>
#include <clipping_planes_pars_fragment>
varying vec2 vHighPrecisionZW;
void main() {
	vec4 diffuseColor = vec4( 1.0 );
	#include <clipping_planes_fragment>
	#if DEPTH_PACKING == 3200
		diffuseColor.a = opacity;
	#endif
	#include <map_fragment>
	#include <alphamap_fragment>
	#include <alphatest_fragment>
	#include <alphahash_fragment>
	#include <logdepthbuf_fragment>
	#ifdef USE_REVERSED_DEPTH_BUFFER
		float fragCoordZ = vHighPrecisionZW[ 0 ] / vHighPrecisionZW[ 1 ];
	#else
		float fragCoordZ = 0.5 * vHighPrecisionZW[ 0 ] / vHighPrecisionZW[ 1 ] + 0.5;
	#endif
	#if DEPTH_PACKING == 3200
		gl_FragColor = vec4( vec3( 1.0 - fragCoordZ ), opacity );
	#elif DEPTH_PACKING == 3201
		gl_FragColor = packDepthToRGBA( fragCoordZ );
	#elif DEPTH_PACKING == 3202
		gl_FragColor = vec4( packDepthToRGB( fragCoordZ ), 1.0 );
	#elif DEPTH_PACKING == 3203
		gl_FragColor = vec4( packDepthToRG( fragCoordZ ), 0.0, 1.0 );
	#endif
}`,distance_vert:`#define DISTANCE
varying vec3 vWorldPosition;
#include <common>
#include <batching_pars_vertex>
#include <uv_pars_vertex>
#include <displacementmap_pars_vertex>
#include <morphtarget_pars_vertex>
#include <skinning_pars_vertex>
#include <clipping_planes_pars_vertex>
void main() {
	#include <uv_vertex>
	#include <batching_vertex>
	#include <skinbase_vertex>
	#include <morphinstance_vertex>
	#ifdef USE_DISPLACEMENTMAP
		#include <beginnormal_vertex>
		#include <morphnormal_vertex>
		#include <skinnormal_vertex>
	#endif
	#include <begin_vertex>
	#include <morphtarget_vertex>
	#include <skinning_vertex>
	#include <displacementmap_vertex>
	#include <project_vertex>
	#include <worldpos_vertex>
	#include <clipping_planes_vertex>
	vWorldPosition = worldPosition.xyz;
}`,distance_frag:`#define DISTANCE
uniform vec3 referencePosition;
uniform float nearDistance;
uniform float farDistance;
varying vec3 vWorldPosition;
#include <common>
#include <uv_pars_fragment>
#include <map_pars_fragment>
#include <alphamap_pars_fragment>
#include <alphatest_pars_fragment>
#include <alphahash_pars_fragment>
#include <clipping_planes_pars_fragment>
void main() {
	vec4 diffuseColor = vec4( 1.0 );
	#include <clipping_planes_fragment>
	#include <map_fragment>
	#include <alphamap_fragment>
	#include <alphatest_fragment>
	#include <alphahash_fragment>
	float dist = length( vWorldPosition - referencePosition );
	dist = ( dist - nearDistance ) / ( farDistance - nearDistance );
	dist = saturate( dist );
	gl_FragColor = vec4( dist, 0.0, 0.0, 1.0 );
}`,equirect_vert:`varying vec3 vWorldDirection;
#include <common>
void main() {
	vWorldDirection = transformDirection( position, modelMatrix );
	#include <begin_vertex>
	#include <project_vertex>
}`,equirect_frag:`uniform sampler2D tEquirect;
varying vec3 vWorldDirection;
#include <common>
void main() {
	vec3 direction = normalize( vWorldDirection );
	vec2 sampleUV = equirectUv( direction );
	gl_FragColor = texture2D( tEquirect, sampleUV );
	#include <tonemapping_fragment>
	#include <colorspace_fragment>
}`,linedashed_vert:`uniform float scale;
attribute float lineDistance;
varying float vLineDistance;
#include <common>
#include <uv_pars_vertex>
#include <color_pars_vertex>
#include <fog_pars_vertex>
#include <morphtarget_pars_vertex>
#include <logdepthbuf_pars_vertex>
#include <clipping_planes_pars_vertex>
void main() {
	vLineDistance = scale * lineDistance;
	#include <uv_vertex>
	#include <color_vertex>
	#include <morphinstance_vertex>
	#include <morphcolor_vertex>
	#include <begin_vertex>
	#include <morphtarget_vertex>
	#include <project_vertex>
	#include <logdepthbuf_vertex>
	#include <clipping_planes_vertex>
	#include <fog_vertex>
}`,linedashed_frag:`uniform vec3 diffuse;
uniform float opacity;
uniform float dashSize;
uniform float totalSize;
varying float vLineDistance;
#include <common>
#include <color_pars_fragment>
#include <uv_pars_fragment>
#include <map_pars_fragment>
#include <fog_pars_fragment>
#include <logdepthbuf_pars_fragment>
#include <clipping_planes_pars_fragment>
void main() {
	vec4 diffuseColor = vec4( diffuse, opacity );
	#include <clipping_planes_fragment>
	if ( mod( vLineDistance, totalSize ) > dashSize ) {
		discard;
	}
	vec3 outgoingLight = vec3( 0.0 );
	#include <logdepthbuf_fragment>
	#include <map_fragment>
	#include <color_fragment>
	outgoingLight = diffuseColor.rgb;
	#include <opaque_fragment>
	#include <tonemapping_fragment>
	#include <colorspace_fragment>
	#include <fog_fragment>
	#include <premultiplied_alpha_fragment>
}`,meshbasic_vert:`#include <common>
#include <batching_pars_vertex>
#include <uv_pars_vertex>
#include <envmap_pars_vertex>
#include <color_pars_vertex>
#include <fog_pars_vertex>
#include <morphtarget_pars_vertex>
#include <skinning_pars_vertex>
#include <logdepthbuf_pars_vertex>
#include <clipping_planes_pars_vertex>
void main() {
	#include <uv_vertex>
	#include <color_vertex>
	#include <morphinstance_vertex>
	#include <morphcolor_vertex>
	#include <batching_vertex>
	#if defined ( USE_ENVMAP ) || defined ( USE_SKINNING )
		#include <beginnormal_vertex>
		#include <morphnormal_vertex>
		#include <skinbase_vertex>
		#include <skinnormal_vertex>
		#include <defaultnormal_vertex>
	#endif
	#include <begin_vertex>
	#include <morphtarget_vertex>
	#include <skinning_vertex>
	#include <project_vertex>
	#include <logdepthbuf_vertex>
	#include <clipping_planes_vertex>
	#include <worldpos_vertex>
	#include <envmap_vertex>
	#include <fog_vertex>
}`,meshbasic_frag:`uniform vec3 diffuse;
uniform float opacity;
#ifndef FLAT_SHADED
	varying vec3 vNormal;
#endif
#include <common>
#include <dithering_pars_fragment>
#include <color_pars_fragment>
#include <uv_pars_fragment>
#include <map_pars_fragment>
#include <alphamap_pars_fragment>
#include <alphatest_pars_fragment>
#include <alphahash_pars_fragment>
#include <aomap_pars_fragment>
#include <lightmap_pars_fragment>
#include <envmap_common_pars_fragment>
#include <envmap_pars_fragment>
#include <fog_pars_fragment>
#include <specularmap_pars_fragment>
#include <logdepthbuf_pars_fragment>
#include <clipping_planes_pars_fragment>
void main() {
	vec4 diffuseColor = vec4( diffuse, opacity );
	#include <clipping_planes_fragment>
	#include <logdepthbuf_fragment>
	#include <map_fragment>
	#include <color_fragment>
	#include <alphamap_fragment>
	#include <alphatest_fragment>
	#include <alphahash_fragment>
	#include <specularmap_fragment>
	ReflectedLight reflectedLight = ReflectedLight( vec3( 0.0 ), vec3( 0.0 ), vec3( 0.0 ), vec3( 0.0 ) );
	#ifdef USE_LIGHTMAP
		vec4 lightMapTexel = texture2D( lightMap, vLightMapUv );
		reflectedLight.indirectDiffuse += lightMapTexel.rgb * lightMapIntensity * RECIPROCAL_PI;
	#else
		reflectedLight.indirectDiffuse += vec3( 1.0 );
	#endif
	#include <aomap_fragment>
	reflectedLight.indirectDiffuse *= diffuseColor.rgb;
	vec3 outgoingLight = reflectedLight.indirectDiffuse;
	#include <envmap_fragment>
	#include <opaque_fragment>
	#include <tonemapping_fragment>
	#include <colorspace_fragment>
	#include <fog_fragment>
	#include <premultiplied_alpha_fragment>
	#include <dithering_fragment>
}`,meshlambert_vert:`#define LAMBERT
varying vec3 vViewPosition;
#include <common>
#include <batching_pars_vertex>
#include <uv_pars_vertex>
#include <displacementmap_pars_vertex>
#include <envmap_pars_vertex>
#include <color_pars_vertex>
#include <fog_pars_vertex>
#include <normal_pars_vertex>
#include <morphtarget_pars_vertex>
#include <skinning_pars_vertex>
#include <shadowmap_pars_vertex>
#include <logdepthbuf_pars_vertex>
#include <clipping_planes_pars_vertex>
void main() {
	#include <uv_vertex>
	#include <color_vertex>
	#include <morphinstance_vertex>
	#include <morphcolor_vertex>
	#include <batching_vertex>
	#include <beginnormal_vertex>
	#include <morphnormal_vertex>
	#include <skinbase_vertex>
	#include <skinnormal_vertex>
	#include <defaultnormal_vertex>
	#include <normal_vertex>
	#include <begin_vertex>
	#include <morphtarget_vertex>
	#include <skinning_vertex>
	#include <displacementmap_vertex>
	#include <project_vertex>
	#include <logdepthbuf_vertex>
	#include <clipping_planes_vertex>
	vViewPosition = - mvPosition.xyz;
	#include <worldpos_vertex>
	#include <envmap_vertex>
	#include <shadowmap_vertex>
	#include <fog_vertex>
}`,meshlambert_frag:`#define LAMBERT
uniform vec3 diffuse;
uniform vec3 emissive;
uniform float opacity;
#include <common>
#include <dithering_pars_fragment>
#include <color_pars_fragment>
#include <uv_pars_fragment>
#include <map_pars_fragment>
#include <alphamap_pars_fragment>
#include <alphatest_pars_fragment>
#include <alphahash_pars_fragment>
#include <aomap_pars_fragment>
#include <lightmap_pars_fragment>
#include <emissivemap_pars_fragment>
#include <cube_uv_reflection_fragment>
#include <envmap_common_pars_fragment>
#include <envmap_pars_fragment>
#include <envmap_physical_pars_fragment>
#include <fog_pars_fragment>
#include <bsdfs>
#include <lights_pars_begin>
#include <normal_pars_fragment>
#include <lights_lambert_pars_fragment>
#include <shadowmap_pars_fragment>
#include <bumpmap_pars_fragment>
#include <normalmap_pars_fragment>
#include <specularmap_pars_fragment>
#include <logdepthbuf_pars_fragment>
#include <clipping_planes_pars_fragment>
void main() {
	vec4 diffuseColor = vec4( diffuse, opacity );
	#include <clipping_planes_fragment>
	ReflectedLight reflectedLight = ReflectedLight( vec3( 0.0 ), vec3( 0.0 ), vec3( 0.0 ), vec3( 0.0 ) );
	vec3 totalEmissiveRadiance = emissive;
	#include <logdepthbuf_fragment>
	#include <map_fragment>
	#include <color_fragment>
	#include <alphamap_fragment>
	#include <alphatest_fragment>
	#include <alphahash_fragment>
	#include <specularmap_fragment>
	#include <normal_fragment_begin>
	#include <normal_fragment_maps>
	#include <emissivemap_fragment>
	#include <lights_lambert_fragment>
	#include <lights_fragment_begin>
	#include <lights_fragment_maps>
	#include <lights_fragment_end>
	#include <aomap_fragment>
	vec3 outgoingLight = reflectedLight.directDiffuse + reflectedLight.indirectDiffuse + totalEmissiveRadiance;
	#include <envmap_fragment>
	#include <opaque_fragment>
	#include <tonemapping_fragment>
	#include <colorspace_fragment>
	#include <fog_fragment>
	#include <premultiplied_alpha_fragment>
	#include <dithering_fragment>
}`,meshmatcap_vert:`#define MATCAP
varying vec3 vViewPosition;
#include <common>
#include <batching_pars_vertex>
#include <uv_pars_vertex>
#include <color_pars_vertex>
#include <displacementmap_pars_vertex>
#include <fog_pars_vertex>
#include <normal_pars_vertex>
#include <morphtarget_pars_vertex>
#include <skinning_pars_vertex>
#include <logdepthbuf_pars_vertex>
#include <clipping_planes_pars_vertex>
void main() {
	#include <uv_vertex>
	#include <color_vertex>
	#include <morphinstance_vertex>
	#include <morphcolor_vertex>
	#include <batching_vertex>
	#include <beginnormal_vertex>
	#include <morphnormal_vertex>
	#include <skinbase_vertex>
	#include <skinnormal_vertex>
	#include <defaultnormal_vertex>
	#include <normal_vertex>
	#include <begin_vertex>
	#include <morphtarget_vertex>
	#include <skinning_vertex>
	#include <displacementmap_vertex>
	#include <project_vertex>
	#include <logdepthbuf_vertex>
	#include <clipping_planes_vertex>
	#include <fog_vertex>
	vViewPosition = - mvPosition.xyz;
}`,meshmatcap_frag:`#define MATCAP
uniform vec3 diffuse;
uniform float opacity;
uniform sampler2D matcap;
varying vec3 vViewPosition;
#include <common>
#include <dithering_pars_fragment>
#include <color_pars_fragment>
#include <uv_pars_fragment>
#include <map_pars_fragment>
#include <alphamap_pars_fragment>
#include <alphatest_pars_fragment>
#include <alphahash_pars_fragment>
#include <fog_pars_fragment>
#include <normal_pars_fragment>
#include <bumpmap_pars_fragment>
#include <normalmap_pars_fragment>
#include <logdepthbuf_pars_fragment>
#include <clipping_planes_pars_fragment>
void main() {
	vec4 diffuseColor = vec4( diffuse, opacity );
	#include <clipping_planes_fragment>
	#include <logdepthbuf_fragment>
	#include <map_fragment>
	#include <color_fragment>
	#include <alphamap_fragment>
	#include <alphatest_fragment>
	#include <alphahash_fragment>
	#include <normal_fragment_begin>
	#include <normal_fragment_maps>
	vec3 viewDir = normalize( vViewPosition );
	vec3 x = normalize( vec3( viewDir.z, 0.0, - viewDir.x ) );
	vec3 y = cross( viewDir, x );
	vec2 uv = vec2( dot( x, normal ), dot( y, normal ) ) * 0.495 + 0.5;
	#ifdef USE_MATCAP
		vec4 matcapColor = texture2D( matcap, uv );
	#else
		vec4 matcapColor = vec4( vec3( mix( 0.2, 0.8, uv.y ) ), 1.0 );
	#endif
	vec3 outgoingLight = diffuseColor.rgb * matcapColor.rgb;
	#include <opaque_fragment>
	#include <tonemapping_fragment>
	#include <colorspace_fragment>
	#include <fog_fragment>
	#include <premultiplied_alpha_fragment>
	#include <dithering_fragment>
}`,meshnormal_vert:`#define NORMAL
#if defined( FLAT_SHADED ) || defined( USE_BUMPMAP ) || defined( USE_NORMALMAP_TANGENTSPACE )
	varying vec3 vViewPosition;
#endif
#include <common>
#include <batching_pars_vertex>
#include <uv_pars_vertex>
#include <displacementmap_pars_vertex>
#include <normal_pars_vertex>
#include <morphtarget_pars_vertex>
#include <skinning_pars_vertex>
#include <logdepthbuf_pars_vertex>
#include <clipping_planes_pars_vertex>
void main() {
	#include <uv_vertex>
	#include <batching_vertex>
	#include <beginnormal_vertex>
	#include <morphinstance_vertex>
	#include <morphnormal_vertex>
	#include <skinbase_vertex>
	#include <skinnormal_vertex>
	#include <defaultnormal_vertex>
	#include <normal_vertex>
	#include <begin_vertex>
	#include <morphtarget_vertex>
	#include <skinning_vertex>
	#include <displacementmap_vertex>
	#include <project_vertex>
	#include <logdepthbuf_vertex>
	#include <clipping_planes_vertex>
#if defined( FLAT_SHADED ) || defined( USE_BUMPMAP ) || defined( USE_NORMALMAP_TANGENTSPACE )
	vViewPosition = - mvPosition.xyz;
#endif
}`,meshnormal_frag:`#define NORMAL
uniform float opacity;
#if defined( FLAT_SHADED ) || defined( USE_BUMPMAP ) || defined( USE_NORMALMAP_TANGENTSPACE )
	varying vec3 vViewPosition;
#endif
#include <uv_pars_fragment>
#include <normal_pars_fragment>
#include <bumpmap_pars_fragment>
#include <normalmap_pars_fragment>
#include <logdepthbuf_pars_fragment>
#include <clipping_planes_pars_fragment>
void main() {
	vec4 diffuseColor = vec4( 0.0, 0.0, 0.0, opacity );
	#include <clipping_planes_fragment>
	#include <logdepthbuf_fragment>
	#include <normal_fragment_begin>
	#include <normal_fragment_maps>
	gl_FragColor = vec4( normalize( normal ) * 0.5 + 0.5, diffuseColor.a );
	#ifdef OPAQUE
		gl_FragColor.a = 1.0;
	#endif
}`,meshphong_vert:`#define PHONG
varying vec3 vViewPosition;
#include <common>
#include <batching_pars_vertex>
#include <uv_pars_vertex>
#include <displacementmap_pars_vertex>
#include <envmap_pars_vertex>
#include <color_pars_vertex>
#include <fog_pars_vertex>
#include <normal_pars_vertex>
#include <morphtarget_pars_vertex>
#include <skinning_pars_vertex>
#include <shadowmap_pars_vertex>
#include <logdepthbuf_pars_vertex>
#include <clipping_planes_pars_vertex>
void main() {
	#include <uv_vertex>
	#include <color_vertex>
	#include <morphcolor_vertex>
	#include <batching_vertex>
	#include <beginnormal_vertex>
	#include <morphinstance_vertex>
	#include <morphnormal_vertex>
	#include <skinbase_vertex>
	#include <skinnormal_vertex>
	#include <defaultnormal_vertex>
	#include <normal_vertex>
	#include <begin_vertex>
	#include <morphtarget_vertex>
	#include <skinning_vertex>
	#include <displacementmap_vertex>
	#include <project_vertex>
	#include <logdepthbuf_vertex>
	#include <clipping_planes_vertex>
	vViewPosition = - mvPosition.xyz;
	#include <worldpos_vertex>
	#include <envmap_vertex>
	#include <shadowmap_vertex>
	#include <fog_vertex>
}`,meshphong_frag:`#define PHONG
uniform vec3 diffuse;
uniform vec3 emissive;
uniform vec3 specular;
uniform float shininess;
uniform float opacity;
#include <common>
#include <dithering_pars_fragment>
#include <color_pars_fragment>
#include <uv_pars_fragment>
#include <map_pars_fragment>
#include <alphamap_pars_fragment>
#include <alphatest_pars_fragment>
#include <alphahash_pars_fragment>
#include <aomap_pars_fragment>
#include <lightmap_pars_fragment>
#include <emissivemap_pars_fragment>
#include <cube_uv_reflection_fragment>
#include <envmap_common_pars_fragment>
#include <envmap_pars_fragment>
#include <envmap_physical_pars_fragment>
#include <fog_pars_fragment>
#include <bsdfs>
#include <lights_pars_begin>
#include <normal_pars_fragment>
#include <lights_phong_pars_fragment>
#include <shadowmap_pars_fragment>
#include <bumpmap_pars_fragment>
#include <normalmap_pars_fragment>
#include <specularmap_pars_fragment>
#include <logdepthbuf_pars_fragment>
#include <clipping_planes_pars_fragment>
void main() {
	vec4 diffuseColor = vec4( diffuse, opacity );
	#include <clipping_planes_fragment>
	ReflectedLight reflectedLight = ReflectedLight( vec3( 0.0 ), vec3( 0.0 ), vec3( 0.0 ), vec3( 0.0 ) );
	vec3 totalEmissiveRadiance = emissive;
	#include <logdepthbuf_fragment>
	#include <map_fragment>
	#include <color_fragment>
	#include <alphamap_fragment>
	#include <alphatest_fragment>
	#include <alphahash_fragment>
	#include <specularmap_fragment>
	#include <normal_fragment_begin>
	#include <normal_fragment_maps>
	#include <emissivemap_fragment>
	#include <lights_phong_fragment>
	#include <lights_fragment_begin>
	#include <lights_fragment_maps>
	#include <lights_fragment_end>
	#include <aomap_fragment>
	vec3 outgoingLight = reflectedLight.directDiffuse + reflectedLight.indirectDiffuse + reflectedLight.directSpecular + reflectedLight.indirectSpecular + totalEmissiveRadiance;
	#include <envmap_fragment>
	#include <opaque_fragment>
	#include <tonemapping_fragment>
	#include <colorspace_fragment>
	#include <fog_fragment>
	#include <premultiplied_alpha_fragment>
	#include <dithering_fragment>
}`,meshphysical_vert:`#define STANDARD
varying vec3 vViewPosition;
#ifdef USE_TRANSMISSION
	varying vec3 vWorldPosition;
#endif
#include <common>
#include <batching_pars_vertex>
#include <uv_pars_vertex>
#include <displacementmap_pars_vertex>
#include <color_pars_vertex>
#include <fog_pars_vertex>
#include <normal_pars_vertex>
#include <morphtarget_pars_vertex>
#include <skinning_pars_vertex>
#include <shadowmap_pars_vertex>
#include <logdepthbuf_pars_vertex>
#include <clipping_planes_pars_vertex>
void main() {
	#include <uv_vertex>
	#include <color_vertex>
	#include <morphinstance_vertex>
	#include <morphcolor_vertex>
	#include <batching_vertex>
	#include <beginnormal_vertex>
	#include <morphnormal_vertex>
	#include <skinbase_vertex>
	#include <skinnormal_vertex>
	#include <defaultnormal_vertex>
	#include <normal_vertex>
	#include <begin_vertex>
	#include <morphtarget_vertex>
	#include <skinning_vertex>
	#include <displacementmap_vertex>
	#include <project_vertex>
	#include <logdepthbuf_vertex>
	#include <clipping_planes_vertex>
	vViewPosition = - mvPosition.xyz;
	#include <worldpos_vertex>
	#include <shadowmap_vertex>
	#include <fog_vertex>
#ifdef USE_TRANSMISSION
	vWorldPosition = worldPosition.xyz;
#endif
}`,meshphysical_frag:`#define STANDARD
#ifdef PHYSICAL
	#define IOR
	#define USE_SPECULAR
#endif
uniform vec3 diffuse;
uniform vec3 emissive;
uniform float roughness;
uniform float metalness;
uniform float opacity;
#ifdef IOR
	uniform float ior;
#endif
#ifdef USE_SPECULAR
	uniform float specularIntensity;
	uniform vec3 specularColor;
	#ifdef USE_SPECULAR_COLORMAP
		uniform sampler2D specularColorMap;
	#endif
	#ifdef USE_SPECULAR_INTENSITYMAP
		uniform sampler2D specularIntensityMap;
	#endif
#endif
#ifdef USE_CLEARCOAT
	uniform float clearcoat;
	uniform float clearcoatRoughness;
#endif
#ifdef USE_DISPERSION
	uniform float dispersion;
#endif
#ifdef USE_IRIDESCENCE
	uniform float iridescence;
	uniform float iridescenceIOR;
	uniform float iridescenceThicknessMinimum;
	uniform float iridescenceThicknessMaximum;
#endif
#ifdef USE_SHEEN
	uniform vec3 sheenColor;
	uniform float sheenRoughness;
	#ifdef USE_SHEEN_COLORMAP
		uniform sampler2D sheenColorMap;
	#endif
	#ifdef USE_SHEEN_ROUGHNESSMAP
		uniform sampler2D sheenRoughnessMap;
	#endif
#endif
#ifdef USE_ANISOTROPY
	uniform vec2 anisotropyVector;
	#ifdef USE_ANISOTROPYMAP
		uniform sampler2D anisotropyMap;
	#endif
#endif
varying vec3 vViewPosition;
#include <common>
#include <dithering_pars_fragment>
#include <color_pars_fragment>
#include <uv_pars_fragment>
#include <map_pars_fragment>
#include <alphamap_pars_fragment>
#include <alphatest_pars_fragment>
#include <alphahash_pars_fragment>
#include <aomap_pars_fragment>
#include <lightmap_pars_fragment>
#include <emissivemap_pars_fragment>
#include <iridescence_fragment>
#include <cube_uv_reflection_fragment>
#include <envmap_common_pars_fragment>
#include <envmap_physical_pars_fragment>
#include <fog_pars_fragment>
#include <lights_pars_begin>
#include <normal_pars_fragment>
#include <lights_physical_pars_fragment>
#include <transmission_pars_fragment>
#include <shadowmap_pars_fragment>
#include <bumpmap_pars_fragment>
#include <normalmap_pars_fragment>
#include <clearcoat_pars_fragment>
#include <iridescence_pars_fragment>
#include <roughnessmap_pars_fragment>
#include <metalnessmap_pars_fragment>
#include <logdepthbuf_pars_fragment>
#include <clipping_planes_pars_fragment>
void main() {
	vec4 diffuseColor = vec4( diffuse, opacity );
	#include <clipping_planes_fragment>
	ReflectedLight reflectedLight = ReflectedLight( vec3( 0.0 ), vec3( 0.0 ), vec3( 0.0 ), vec3( 0.0 ) );
	vec3 totalEmissiveRadiance = emissive;
	#include <logdepthbuf_fragment>
	#include <map_fragment>
	#include <color_fragment>
	#include <alphamap_fragment>
	#include <alphatest_fragment>
	#include <alphahash_fragment>
	#include <roughnessmap_fragment>
	#include <metalnessmap_fragment>
	#include <normal_fragment_begin>
	#include <normal_fragment_maps>
	#include <clearcoat_normal_fragment_begin>
	#include <clearcoat_normal_fragment_maps>
	#include <emissivemap_fragment>
	#include <lights_physical_fragment>
	#include <lights_fragment_begin>
	#include <lights_fragment_maps>
	#include <lights_fragment_end>
	#include <aomap_fragment>
	vec3 totalDiffuse = reflectedLight.directDiffuse + reflectedLight.indirectDiffuse;
	vec3 totalSpecular = reflectedLight.directSpecular + reflectedLight.indirectSpecular;
	#include <transmission_fragment>
	vec3 outgoingLight = totalDiffuse + totalSpecular + totalEmissiveRadiance;
	#ifdef USE_SHEEN
 
		outgoingLight = outgoingLight + sheenSpecularDirect + sheenSpecularIndirect;
 
 	#endif
	#ifdef USE_CLEARCOAT
		float dotNVcc = saturate( dot( geometryClearcoatNormal, geometryViewDir ) );
		vec3 Fcc = F_Schlick( material.clearcoatF0, material.clearcoatF90, dotNVcc );
		outgoingLight = outgoingLight * ( 1.0 - material.clearcoat * Fcc ) + ( clearcoatSpecularDirect + clearcoatSpecularIndirect ) * material.clearcoat;
	#endif
	#include <opaque_fragment>
	#include <tonemapping_fragment>
	#include <colorspace_fragment>
	#include <fog_fragment>
	#include <premultiplied_alpha_fragment>
	#include <dithering_fragment>
}`,meshtoon_vert:`#define TOON
varying vec3 vViewPosition;
#include <common>
#include <batching_pars_vertex>
#include <uv_pars_vertex>
#include <displacementmap_pars_vertex>
#include <color_pars_vertex>
#include <fog_pars_vertex>
#include <normal_pars_vertex>
#include <morphtarget_pars_vertex>
#include <skinning_pars_vertex>
#include <shadowmap_pars_vertex>
#include <logdepthbuf_pars_vertex>
#include <clipping_planes_pars_vertex>
void main() {
	#include <uv_vertex>
	#include <color_vertex>
	#include <morphinstance_vertex>
	#include <morphcolor_vertex>
	#include <batching_vertex>
	#include <beginnormal_vertex>
	#include <morphnormal_vertex>
	#include <skinbase_vertex>
	#include <skinnormal_vertex>
	#include <defaultnormal_vertex>
	#include <normal_vertex>
	#include <begin_vertex>
	#include <morphtarget_vertex>
	#include <skinning_vertex>
	#include <displacementmap_vertex>
	#include <project_vertex>
	#include <logdepthbuf_vertex>
	#include <clipping_planes_vertex>
	vViewPosition = - mvPosition.xyz;
	#include <worldpos_vertex>
	#include <shadowmap_vertex>
	#include <fog_vertex>
}`,meshtoon_frag:`#define TOON
uniform vec3 diffuse;
uniform vec3 emissive;
uniform float opacity;
#include <common>
#include <dithering_pars_fragment>
#include <color_pars_fragment>
#include <uv_pars_fragment>
#include <map_pars_fragment>
#include <alphamap_pars_fragment>
#include <alphatest_pars_fragment>
#include <alphahash_pars_fragment>
#include <aomap_pars_fragment>
#include <lightmap_pars_fragment>
#include <emissivemap_pars_fragment>
#include <gradientmap_pars_fragment>
#include <fog_pars_fragment>
#include <bsdfs>
#include <lights_pars_begin>
#include <normal_pars_fragment>
#include <lights_toon_pars_fragment>
#include <shadowmap_pars_fragment>
#include <bumpmap_pars_fragment>
#include <normalmap_pars_fragment>
#include <logdepthbuf_pars_fragment>
#include <clipping_planes_pars_fragment>
void main() {
	vec4 diffuseColor = vec4( diffuse, opacity );
	#include <clipping_planes_fragment>
	ReflectedLight reflectedLight = ReflectedLight( vec3( 0.0 ), vec3( 0.0 ), vec3( 0.0 ), vec3( 0.0 ) );
	vec3 totalEmissiveRadiance = emissive;
	#include <logdepthbuf_fragment>
	#include <map_fragment>
	#include <color_fragment>
	#include <alphamap_fragment>
	#include <alphatest_fragment>
	#include <alphahash_fragment>
	#include <normal_fragment_begin>
	#include <normal_fragment_maps>
	#include <emissivemap_fragment>
	#include <lights_toon_fragment>
	#include <lights_fragment_begin>
	#include <lights_fragment_maps>
	#include <lights_fragment_end>
	#include <aomap_fragment>
	vec3 outgoingLight = reflectedLight.directDiffuse + reflectedLight.indirectDiffuse + totalEmissiveRadiance;
	#include <opaque_fragment>
	#include <tonemapping_fragment>
	#include <colorspace_fragment>
	#include <fog_fragment>
	#include <premultiplied_alpha_fragment>
	#include <dithering_fragment>
}`,points_vert:`uniform float size;
uniform float scale;
#include <common>
#include <color_pars_vertex>
#include <fog_pars_vertex>
#include <morphtarget_pars_vertex>
#include <logdepthbuf_pars_vertex>
#include <clipping_planes_pars_vertex>
#ifdef USE_POINTS_UV
	varying vec2 vUv;
	uniform mat3 uvTransform;
#endif
void main() {
	#ifdef USE_POINTS_UV
		vUv = ( uvTransform * vec3( uv, 1 ) ).xy;
	#endif
	#include <color_vertex>
	#include <morphinstance_vertex>
	#include <morphcolor_vertex>
	#include <begin_vertex>
	#include <morphtarget_vertex>
	#include <project_vertex>
	gl_PointSize = size;
	#ifdef USE_SIZEATTENUATION
		bool isPerspective = isPerspectiveMatrix( projectionMatrix );
		if ( isPerspective ) gl_PointSize *= ( scale / - mvPosition.z );
	#endif
	#include <logdepthbuf_vertex>
	#include <clipping_planes_vertex>
	#include <worldpos_vertex>
	#include <fog_vertex>
}`,points_frag:`uniform vec3 diffuse;
uniform float opacity;
#include <common>
#include <color_pars_fragment>
#include <map_particle_pars_fragment>
#include <alphatest_pars_fragment>
#include <alphahash_pars_fragment>
#include <fog_pars_fragment>
#include <logdepthbuf_pars_fragment>
#include <clipping_planes_pars_fragment>
void main() {
	vec4 diffuseColor = vec4( diffuse, opacity );
	#include <clipping_planes_fragment>
	vec3 outgoingLight = vec3( 0.0 );
	#include <logdepthbuf_fragment>
	#include <map_particle_fragment>
	#include <color_fragment>
	#include <alphatest_fragment>
	#include <alphahash_fragment>
	outgoingLight = diffuseColor.rgb;
	#include <opaque_fragment>
	#include <tonemapping_fragment>
	#include <colorspace_fragment>
	#include <fog_fragment>
	#include <premultiplied_alpha_fragment>
}`,shadow_vert:`#include <common>
#include <batching_pars_vertex>
#include <fog_pars_vertex>
#include <morphtarget_pars_vertex>
#include <skinning_pars_vertex>
#include <logdepthbuf_pars_vertex>
#include <shadowmap_pars_vertex>
void main() {
	#include <batching_vertex>
	#include <beginnormal_vertex>
	#include <morphinstance_vertex>
	#include <morphnormal_vertex>
	#include <skinbase_vertex>
	#include <skinnormal_vertex>
	#include <defaultnormal_vertex>
	#include <begin_vertex>
	#include <morphtarget_vertex>
	#include <skinning_vertex>
	#include <project_vertex>
	#include <logdepthbuf_vertex>
	#include <worldpos_vertex>
	#include <shadowmap_vertex>
	#include <fog_vertex>
}`,shadow_frag:`uniform vec3 color;
uniform float opacity;
#include <common>
#include <fog_pars_fragment>
#include <bsdfs>
#include <lights_pars_begin>
#include <logdepthbuf_pars_fragment>
#include <shadowmap_pars_fragment>
#include <shadowmask_pars_fragment>
void main() {
	#include <logdepthbuf_fragment>
	gl_FragColor = vec4( color, opacity * ( 1.0 - getShadowMask() ) );
	#include <tonemapping_fragment>
	#include <colorspace_fragment>
	#include <fog_fragment>
	#include <premultiplied_alpha_fragment>
}`,sprite_vert:`uniform float rotation;
uniform vec2 center;
#include <common>
#include <uv_pars_vertex>
#include <fog_pars_vertex>
#include <logdepthbuf_pars_vertex>
#include <clipping_planes_pars_vertex>
void main() {
	#include <uv_vertex>
	vec4 mvPosition = modelViewMatrix[ 3 ];
	vec2 scale = vec2( length( modelMatrix[ 0 ].xyz ), length( modelMatrix[ 1 ].xyz ) );
	#ifndef USE_SIZEATTENUATION
		bool isPerspective = isPerspectiveMatrix( projectionMatrix );
		if ( isPerspective ) scale *= - mvPosition.z;
	#endif
	vec2 alignedPosition = ( position.xy - ( center - vec2( 0.5 ) ) ) * scale;
	vec2 rotatedPosition;
	rotatedPosition.x = cos( rotation ) * alignedPosition.x - sin( rotation ) * alignedPosition.y;
	rotatedPosition.y = sin( rotation ) * alignedPosition.x + cos( rotation ) * alignedPosition.y;
	mvPosition.xy += rotatedPosition;
	gl_Position = projectionMatrix * mvPosition;
	#include <logdepthbuf_vertex>
	#include <clipping_planes_vertex>
	#include <fog_vertex>
}`,sprite_frag:`uniform vec3 diffuse;
uniform float opacity;
#include <common>
#include <uv_pars_fragment>
#include <map_pars_fragment>
#include <alphamap_pars_fragment>
#include <alphatest_pars_fragment>
#include <alphahash_pars_fragment>
#include <fog_pars_fragment>
#include <logdepthbuf_pars_fragment>
#include <clipping_planes_pars_fragment>
void main() {
	vec4 diffuseColor = vec4( diffuse, opacity );
	#include <clipping_planes_fragment>
	vec3 outgoingLight = vec3( 0.0 );
	#include <logdepthbuf_fragment>
	#include <map_fragment>
	#include <alphamap_fragment>
	#include <alphatest_fragment>
	#include <alphahash_fragment>
	outgoingLight = diffuseColor.rgb;
	#include <opaque_fragment>
	#include <tonemapping_fragment>
	#include <colorspace_fragment>
	#include <fog_fragment>
}`},$={common:{diffuse:{value:new kt(16777215)},opacity:{value:1},map:{value:null},mapTransform:{value:new X},alphaMap:{value:null},alphaMapTransform:{value:new X},alphaTest:{value:0}},specularmap:{specularMap:{value:null},specularMapTransform:{value:new X}},envmap:{envMap:{value:null},envMapRotation:{value:new X},reflectivity:{value:1},ior:{value:1.5},refractionRatio:{value:.98},dfgLUT:{value:null}},aomap:{aoMap:{value:null},aoMapIntensity:{value:1},aoMapTransform:{value:new X}},lightmap:{lightMap:{value:null},lightMapIntensity:{value:1},lightMapTransform:{value:new X}},bumpmap:{bumpMap:{value:null},bumpMapTransform:{value:new X},bumpScale:{value:1}},normalmap:{normalMap:{value:null},normalMapTransform:{value:new X},normalScale:{value:new n(1,1)}},displacementmap:{displacementMap:{value:null},displacementMapTransform:{value:new X},displacementScale:{value:1},displacementBias:{value:0}},emissivemap:{emissiveMap:{value:null},emissiveMapTransform:{value:new X}},metalnessmap:{metalnessMap:{value:null},metalnessMapTransform:{value:new X}},roughnessmap:{roughnessMap:{value:null},roughnessMapTransform:{value:new X}},gradientmap:{gradientMap:{value:null}},fog:{fogDensity:{value:25e-5},fogNear:{value:1},fogFar:{value:2e3},fogColor:{value:new kt(16777215)}},lights:{ambientLightColor:{value:[]},lightProbe:{value:[]},directionalLights:{value:[],properties:{direction:{},color:{}}},directionalLightShadows:{value:[],properties:{shadowIntensity:1,shadowBias:{},shadowNormalBias:{},shadowRadius:{},shadowMapSize:{}}},directionalShadowMatrix:{value:[]},spotLights:{value:[],properties:{color:{},position:{},direction:{},distance:{},coneCos:{},penumbraCos:{},decay:{}}},spotLightShadows:{value:[],properties:{shadowIntensity:1,shadowBias:{},shadowNormalBias:{},shadowRadius:{},shadowMapSize:{}}},spotLightMap:{value:[]},spotLightMatrix:{value:[]},pointLights:{value:[],properties:{color:{},position:{},decay:{},distance:{}}},pointLightShadows:{value:[],properties:{shadowIntensity:1,shadowBias:{},shadowNormalBias:{},shadowRadius:{},shadowMapSize:{},shadowCameraNear:{},shadowCameraFar:{}}},pointShadowMatrix:{value:[]},hemisphereLights:{value:[],properties:{direction:{},skyColor:{},groundColor:{}}},rectAreaLights:{value:[],properties:{color:{},position:{},width:{},height:{}}},ltc_1:{value:null},ltc_2:{value:null},probesSH:{value:null},probesMin:{value:new Y},probesMax:{value:new Y},probesResolution:{value:new Y}},points:{diffuse:{value:new kt(16777215)},opacity:{value:1},size:{value:1},scale:{value:1},map:{value:null},alphaMap:{value:null},alphaMapTransform:{value:new X},alphaTest:{value:0},uvTransform:{value:new X}},sprite:{diffuse:{value:new kt(16777215)},opacity:{value:1},center:{value:new n(.5,.5)},rotation:{value:0},map:{value:null},mapTransform:{value:new X},alphaMap:{value:null},alphaMapTransform:{value:new X},alphaTest:{value:0}}},pm={basic:{uniforms:C([$.common,$.specularmap,$.envmap,$.aomap,$.lightmap,$.fog]),vertexShader:Q.meshbasic_vert,fragmentShader:Q.meshbasic_frag},lambert:{uniforms:C([$.common,$.specularmap,$.envmap,$.aomap,$.lightmap,$.emissivemap,$.bumpmap,$.normalmap,$.displacementmap,$.fog,$.lights,{emissive:{value:new kt(0)},envMapIntensity:{value:1}}]),vertexShader:Q.meshlambert_vert,fragmentShader:Q.meshlambert_frag},phong:{uniforms:C([$.common,$.specularmap,$.envmap,$.aomap,$.lightmap,$.emissivemap,$.bumpmap,$.normalmap,$.displacementmap,$.fog,$.lights,{emissive:{value:new kt(0)},specular:{value:new kt(1118481)},shininess:{value:30},envMapIntensity:{value:1}}]),vertexShader:Q.meshphong_vert,fragmentShader:Q.meshphong_frag},standard:{uniforms:C([$.common,$.envmap,$.aomap,$.lightmap,$.emissivemap,$.bumpmap,$.normalmap,$.displacementmap,$.roughnessmap,$.metalnessmap,$.fog,$.lights,{emissive:{value:new kt(0)},roughness:{value:1},metalness:{value:0},envMapIntensity:{value:1}}]),vertexShader:Q.meshphysical_vert,fragmentShader:Q.meshphysical_frag},toon:{uniforms:C([$.common,$.aomap,$.lightmap,$.emissivemap,$.bumpmap,$.normalmap,$.displacementmap,$.gradientmap,$.fog,$.lights,{emissive:{value:new kt(0)}}]),vertexShader:Q.meshtoon_vert,fragmentShader:Q.meshtoon_frag},matcap:{uniforms:C([$.common,$.bumpmap,$.normalmap,$.displacementmap,$.fog,{matcap:{value:null}}]),vertexShader:Q.meshmatcap_vert,fragmentShader:Q.meshmatcap_frag},points:{uniforms:C([$.points,$.fog]),vertexShader:Q.points_vert,fragmentShader:Q.points_frag},dashed:{uniforms:C([$.common,$.fog,{scale:{value:1},dashSize:{value:1},totalSize:{value:2}}]),vertexShader:Q.linedashed_vert,fragmentShader:Q.linedashed_frag},depth:{uniforms:C([$.common,$.displacementmap]),vertexShader:Q.depth_vert,fragmentShader:Q.depth_frag},normal:{uniforms:C([$.common,$.bumpmap,$.normalmap,$.displacementmap,{opacity:{value:1}}]),vertexShader:Q.meshnormal_vert,fragmentShader:Q.meshnormal_frag},sprite:{uniforms:C([$.sprite,$.fog]),vertexShader:Q.sprite_vert,fragmentShader:Q.sprite_frag},background:{uniforms:{uvTransform:{value:new X},t2D:{value:null},backgroundIntensity:{value:1}},vertexShader:Q.background_vert,fragmentShader:Q.background_frag},backgroundCube:{uniforms:{envMap:{value:null},backgroundBlurriness:{value:0},backgroundIntensity:{value:1},backgroundRotation:{value:new X}},vertexShader:Q.backgroundCube_vert,fragmentShader:Q.backgroundCube_frag},cube:{uniforms:{tCube:{value:null},tFlip:{value:-1},opacity:{value:1}},vertexShader:Q.cube_vert,fragmentShader:Q.cube_frag},equirect:{uniforms:{tEquirect:{value:null}},vertexShader:Q.equirect_vert,fragmentShader:Q.equirect_frag},distance:{uniforms:C([$.common,$.displacementmap,{referencePosition:{value:new Y},nearDistance:{value:1},farDistance:{value:1e3}}]),vertexShader:Q.distance_vert,fragmentShader:Q.distance_frag},shadow:{uniforms:C([$.lights,$.fog,{color:{value:new kt(0)},opacity:{value:1}}]),vertexShader:Q.shadow_vert,fragmentShader:Q.shadow_frag}};pm.physical={uniforms:C([pm.standard.uniforms,{clearcoat:{value:0},clearcoatMap:{value:null},clearcoatMapTransform:{value:new X},clearcoatNormalMap:{value:null},clearcoatNormalMapTransform:{value:new X},clearcoatNormalScale:{value:new n(1,1)},clearcoatRoughness:{value:0},clearcoatRoughnessMap:{value:null},clearcoatRoughnessMapTransform:{value:new X},dispersion:{value:0},iridescence:{value:0},iridescenceMap:{value:null},iridescenceMapTransform:{value:new X},iridescenceIOR:{value:1.3},iridescenceThicknessMinimum:{value:100},iridescenceThicknessMaximum:{value:400},iridescenceThicknessMap:{value:null},iridescenceThicknessMapTransform:{value:new X},sheen:{value:0},sheenColor:{value:new kt(0)},sheenColorMap:{value:null},sheenColorMapTransform:{value:new X},sheenRoughness:{value:1},sheenRoughnessMap:{value:null},sheenRoughnessMapTransform:{value:new X},transmission:{value:0},transmissionMap:{value:null},transmissionMapTransform:{value:new X},transmissionSamplerSize:{value:new n},transmissionSamplerMap:{value:null},thickness:{value:0},thicknessMap:{value:null},thicknessMapTransform:{value:new X},attenuationDistance:{value:0},attenuationColor:{value:new kt(0)},specularColor:{value:new kt(1,1,1)},specularColorMap:{value:null},specularColorMapTransform:{value:new X},specularIntensity:{value:1},specularIntensityMap:{value:null},specularIntensityMapTransform:{value:new X},anisotropyVector:{value:new n},anisotropyMap:{value:null},anisotropyMapTransform:{value:new X}}]),vertexShader:Q.meshphysical_vert,fragmentShader:Q.meshphysical_frag};var mm={r:0,b:0,g:0},hm=new ki,gm=new X;gm.set(-1,0,0,0,1,0,0,0,1);function _m(e,t,n,i,a,o){let s=new kt(0),c=a===!0?0:1,l,u,f=null,p=0,m=null;function h(e){let n=e.isScene===!0?e.background:null;if(n&&n.isTexture){let r=e.backgroundBlurriness>0;n=t.get(n,r)}return n}function g(t){let r=!1,i=h(t);i===null?v(s,c):i&&i.isColor&&(v(i,1),r=!0);let a=e.xr.getEnvironmentBlendMode();a===`additive`?n.buffers.color.setClear(0,0,0,1,o):a===`alpha-blend`&&n.buffers.color.setClear(0,0,0,0,o),(e.autoClear||r)&&(n.buffers.depth.setTest(!0),n.buffers.depth.setMask(!0),n.buffers.color.setMask(!0),e.clear(e.autoClearColor,e.autoClearDepth,e.autoClearStencil))}function _(t,n){let a=h(n);a&&(a.isCubeTexture||a.mapping===306)?(u===void 0&&(u=new wr(new Ge(1,1,1),new r({name:`BackgroundCubeMaterial`,uniforms:gr(pm.backgroundCube.uniforms),vertexShader:pm.backgroundCube.vertexShader,fragmentShader:pm.backgroundCube.fragmentShader,side:1,depthTest:!1,depthWrite:!1,fog:!1,allowOverride:!1})),u.geometry.deleteAttribute(`normal`),u.geometry.deleteAttribute(`uv`),u.onBeforeRender=function(e,t,n){this.matrixWorld.copyPosition(n.matrixWorld)},Object.defineProperty(u.material,"envMap",{get:function(){return this.uniforms.envMap.value}}),i.update(u)),u.material.uniforms.envMap.value=a,u.material.uniforms.backgroundBlurriness.value=n.backgroundBlurriness,u.material.uniforms.backgroundIntensity.value=n.backgroundIntensity,u.material.uniforms.backgroundRotation.value.setFromMatrix4(hm.makeRotationFromEuler(n.backgroundRotation)).transpose(),a.isCubeTexture&&a.isRenderTargetTexture===!1&&u.material.uniforms.backgroundRotation.value.premultiply(gm),u.material.toneMapped=z.getTransfer(a.colorSpace)!==cn,(f!==a||p!==a.version||m!==e.toneMapping)&&(u.material.needsUpdate=!0,f=a,p=a.version,m=e.toneMapping),u.layers.enableAll(),t.unshift(u,u.geometry,u.material,0,0,null)):a&&a.isTexture&&(l===void 0&&(l=new wr(new d(2,2),new r({name:`BackgroundMaterial`,uniforms:gr(pm.background.uniforms),vertexShader:pm.background.vertexShader,fragmentShader:pm.background.fragmentShader,side:0,depthTest:!1,depthWrite:!1,fog:!1,allowOverride:!1})),l.geometry.deleteAttribute(`normal`),Object.defineProperty(l.material,"map",{get:function(){return this.uniforms.t2D.value}}),i.update(l)),l.material.uniforms.t2D.value=a,l.material.uniforms.backgroundIntensity.value=n.backgroundIntensity,l.material.toneMapped=z.getTransfer(a.colorSpace)!==cn,a.matrixAutoUpdate===!0&&a.updateMatrix(),l.material.uniforms.uvTransform.value.copy(a.matrix),(f!==a||p!==a.version||m!==e.toneMapping)&&(l.material.needsUpdate=!0,f=a,p=a.version,m=e.toneMapping),l.layers.enableAll(),t.unshift(l,l.geometry,l.material,0,0,null))}function v(t,r){t.getRGB(mm,ga(e)),n.buffers.color.setClear(mm.r,mm.g,mm.b,r,o)}function y(){u!==void 0&&(u.geometry.dispose(),u.material.dispose(),u=void 0),l!==void 0&&(l.geometry.dispose(),l.material.dispose(),l=void 0)}return{getClearColor:function(){return s},setClearColor:function(e,t=1){s.set(e),c=t,v(s,c)},getClearAlpha:function(){return c},setClearAlpha:function(e){c=e,v(s,c)},render:g,addToRenderList:_,dispose:y}}function vm(e,t){let n=e.getParameter(e.MAX_VERTEX_ATTRIBS),r={},i=f(null),a=i,o=!1;function s(n,r,i,s,c){let u=!1,f=d(n,s,i,r);a!==f&&(a=f,l(a.object)),u=p(n,s,i,c),u&&m(n,s,i,c),c!==null&&t.update(c,e.ELEMENT_ARRAY_BUFFER),(u||o)&&(o=!1,b(n,r,i,s),c!==null&&e.bindBuffer(e.ELEMENT_ARRAY_BUFFER,t.get(c).buffer))}function c(){return e.createVertexArray()}function l(t){return e.bindVertexArray(t)}function u(t){return e.deleteVertexArray(t)}function d(e,t,n,i){let a=i.wireframe===!0,o=r[t.id];o===void 0&&(o={},r[t.id]=o);let s=e.isInstancedMesh===!0?e.id:0,l=o[s];l===void 0&&(l={},o[s]=l);let u=l[n.id];u===void 0&&(u={},l[n.id]=u);let d=u[a];return d===void 0&&(d=f(c()),u[a]=d),d}function f(e){let t=[],r=[],i=[];for(let e=0;e<n;e++)t[e]=0,r[e]=0,i[e]=0;return{geometry:null,program:null,wireframe:!1,newAttributes:t,enabledAttributes:r,attributeDivisors:i,object:e,attributes:{},index:null}}function p(e,t,n,r){let i=a.attributes,o=t.attributes,s=0,c=n.getAttributes();for(let t in c)if(c[t].location>=0){let n=i[t],r=o[t];if(r===void 0&&(t===`instanceMatrix`&&e.instanceMatrix&&(r=e.instanceMatrix),t===`instanceColor`&&e.instanceColor&&(r=e.instanceColor)),n===void 0||n.attribute!==r||r&&n.data!==r.data)return!0;s++}return a.attributesNum!==s||a.index!==r}function m(e,t,n,r){let i={},o=t.attributes,s=0,c=n.getAttributes();for(let t in c)if(c[t].location>=0){let n=o[t];n===void 0&&(t===`instanceMatrix`&&e.instanceMatrix&&(n=e.instanceMatrix),t===`instanceColor`&&e.instanceColor&&(n=e.instanceColor));let r={};r.attribute=n,n&&n.data&&(r.data=n.data),i[t]=r,s++}a.attributes=i,a.attributesNum=s,a.index=r}function h(){let e=a.newAttributes;for(let t=0,n=e.length;t<n;t++)e[t]=0}function g(e){_(e,0)}function _(t,n){let r=a.newAttributes,i=a.enabledAttributes,o=a.attributeDivisors;r[t]=1,i[t]===0&&(e.enableVertexAttribArray(t),i[t]=1),o[t]!==n&&(e.vertexAttribDivisor(t,n),o[t]=n)}function v(){let t=a.newAttributes,n=a.enabledAttributes;for(let r=0,i=n.length;r<i;r++)n[r]!==t[r]&&(e.disableVertexAttribArray(r),n[r]=0)}function y(t,n,r,i,a,o,s){s===!0?e.vertexAttribIPointer(t,n,r,a,o):e.vertexAttribPointer(t,n,r,i,a,o)}function b(n,r,i,a){h();let o=a.attributes,s=i.getAttributes(),c=r.defaultAttributeValues;for(let r in s){let i=s[r];if(i.location>=0){let s=o[r];if(s===void 0&&(r===`instanceMatrix`&&n.instanceMatrix&&(s=n.instanceMatrix),r===`instanceColor`&&n.instanceColor&&(s=n.instanceColor)),s!==void 0){let r=s.normalized,o=s.itemSize,c=t.get(s);if(c===void 0)continue;let l=c.buffer,u=c.type,d=c.bytesPerElement,f=u===e.INT||u===e.UNSIGNED_INT||s.gpuType===1013;if(s.isInterleavedBufferAttribute){let t=s.data,c=t.stride,p=s.offset;if(t.isInstancedInterleavedBuffer){for(let e=0;e<i.locationSize;e++)_(i.location+e,t.meshPerAttribute);n.isInstancedMesh!==!0&&a._maxInstanceCount===void 0&&(a._maxInstanceCount=t.meshPerAttribute*t.count)}else for(let e=0;e<i.locationSize;e++)g(i.location+e);e.bindBuffer(e.ARRAY_BUFFER,l);for(let e=0;e<i.locationSize;e++)y(i.location+e,o/i.locationSize,u,r,c*d,(p+o/i.locationSize*e)*d,f)}else{if(s.isInstancedBufferAttribute){for(let e=0;e<i.locationSize;e++)_(i.location+e,s.meshPerAttribute);n.isInstancedMesh!==!0&&a._maxInstanceCount===void 0&&(a._maxInstanceCount=s.meshPerAttribute*s.count)}else for(let e=0;e<i.locationSize;e++)g(i.location+e);e.bindBuffer(e.ARRAY_BUFFER,l);for(let e=0;e<i.locationSize;e++)y(i.location+e,o/i.locationSize,u,r,o*d,o/i.locationSize*e*d,f)}}else if(c!==void 0){let t=c[r];if(t!==void 0)switch(t.length){case 2:e.vertexAttrib2fv(i.location,t);break;case 3:e.vertexAttrib3fv(i.location,t);break;case 4:e.vertexAttrib4fv(i.location,t);break;default:e.vertexAttrib1fv(i.location,t)}}}}v()}function x(){T();for(let e in r){let t=r[e];for(let e in t){let n=t[e];for(let e in n){let t=n[e];for(let e in t)u(t[e].object),delete t[e];delete n[e]}}delete r[e]}}function S(e){if(r[e.id]===void 0)return;let t=r[e.id];for(let e in t){let n=t[e];for(let e in n){let t=n[e];for(let e in t)u(t[e].object),delete t[e];delete n[e]}}delete r[e.id]}function C(e){for(let t in r){let n=r[t];for(let t in n){let r=n[t];if(r[e.id]===void 0)continue;let i=r[e.id];for(let e in i)u(i[e].object),delete i[e];delete r[e.id]}}}function w(e){for(let t in r){let n=r[t],i=e.isInstancedMesh===!0?e.id:0,a=n[i];if(a!==void 0){for(let e in a){let t=a[e];for(let e in t)u(t[e].object),delete t[e];delete a[e]}delete n[i],Object.keys(n).length===0&&delete r[t]}}}function T(){E(),o=!0,a!==i&&(a=i,l(a.object))}function E(){i.geometry=null,i.program=null,i.wireframe=!1}return{setup:s,reset:T,resetDefaultState:E,dispose:x,releaseStatesOfGeometry:S,releaseStatesOfObject:w,releaseStatesOfProgram:C,initAttributes:h,enableAttribute:g,disableUnusedAttributes:v}}function ym(e,t,n){let r;function i(e){r=e}function a(t,i){e.drawArrays(r,t,i),n.update(i,r,1)}function o(t,i,a){a!==0&&(e.drawArraysInstanced(r,t,i,a),n.update(i,r,a))}function s(e,i,a){if(a===0)return;t.get(`WEBGL_multi_draw`).multiDrawArraysWEBGL(r,e,0,i,0,a);let o=0;for(let e=0;e<a;e++)o+=i[e];n.update(o,r,1)}this.setMode=i,this.render=a,this.renderInstances=o,this.renderMultiDraw=s}function bm(e,t,n,r){let i;function a(){if(i!==void 0)return i;if(t.has(`EXT_texture_filter_anisotropic`)===!0){let n=t.get(`EXT_texture_filter_anisotropic`);i=e.getParameter(n.MAX_TEXTURE_MAX_ANISOTROPY_EXT)}else i=0;return i}function o(t){return!(t!==1023&&r.convert(t)!==e.getParameter(e.IMPLEMENTATION_COLOR_READ_FORMAT))}function s(n){let i=n===1016&&(t.has(`EXT_color_buffer_half_float`)||t.has(`EXT_color_buffer_float`));return!(n!==1009&&r.convert(n)!==e.getParameter(e.IMPLEMENTATION_COLOR_READ_TYPE)&&n!==1015&&!i)}function c(t){if(t===`highp`){if(e.getShaderPrecisionFormat(e.VERTEX_SHADER,e.HIGH_FLOAT).precision>0&&e.getShaderPrecisionFormat(e.FRAGMENT_SHADER,e.HIGH_FLOAT).precision>0)return`highp`;t=`mediump`}return t===`mediump`&&e.getShaderPrecisionFormat(e.VERTEX_SHADER,e.MEDIUM_FLOAT).precision>0&&e.getShaderPrecisionFormat(e.FRAGMENT_SHADER,e.MEDIUM_FLOAT).precision>0?`mediump`:`lowp`}let l=n.precision===void 0?`highp`:n.precision,u=c(l);u!==l&&(P(`WebGLRenderer:`,l,`not supported, using`,u,`instead.`),l=u);let d=n.logarithmicDepthBuffer===!0,f=n.reversedDepthBuffer===!0&&t.has(`EXT_clip_control`);n.reversedDepthBuffer===!0&&f===!1&&P(`WebGLRenderer: Unable to use reversed depth buffer due to missing EXT_clip_control extension. Fallback to default depth buffer.`);let p=e.getParameter(e.MAX_TEXTURE_IMAGE_UNITS),m=e.getParameter(e.MAX_VERTEX_TEXTURE_IMAGE_UNITS),h=e.getParameter(e.MAX_TEXTURE_SIZE),g=e.getParameter(e.MAX_CUBE_MAP_TEXTURE_SIZE),_=e.getParameter(e.MAX_VERTEX_ATTRIBS),v=e.getParameter(e.MAX_VERTEX_UNIFORM_VECTORS),y=e.getParameter(e.MAX_VARYING_VECTORS),b=e.getParameter(e.MAX_FRAGMENT_UNIFORM_VECTORS),x=e.getParameter(e.MAX_SAMPLES),S=e.getParameter(e.SAMPLES);return{isWebGL2:!0,getMaxAnisotropy:a,getMaxPrecision:c,textureFormatReadable:o,textureTypeReadable:s,precision:l,logarithmicDepthBuffer:d,reversedDepthBuffer:f,maxTextures:p,maxVertexTextures:m,maxTextureSize:h,maxCubemapSize:g,maxAttributes:_,maxVertexUniforms:v,maxVaryings:y,maxFragmentUniforms:b,maxSamples:x,samples:S}}function xm(e){let t=this,n=null,r=0,i=!1,a=!1,o=new Ir,s=new X,c={value:null,needsUpdate:!1};this.uniform=c,this.numPlanes=0,this.numIntersection=0,this.init=function(e,t){let n=e.length!==0||t||r!==0||i;return i=t,r=e.length,n},this.beginShadows=function(){a=!0,u(null)},this.endShadows=function(){a=!1},this.setGlobalState=function(e,t){n=u(e,t,0)},this.setState=function(t,o,s){let d=t.clippingPlanes,f=t.clipIntersection,p=t.clipShadows,m=e.get(t);if(!i||d===null||d.length===0||a&&!p)a?u(null):l();else{let e=a?0:r,t=e*4,i=m.clippingState||null;c.value=i,i=u(d,o,t,s);for(let e=0;e!==t;++e)i[e]=n[e];m.clippingState=i,this.numIntersection=f?this.numPlanes:0,this.numPlanes+=e}};function l(){c.value!==n&&(c.value=n,c.needsUpdate=r>0),t.numPlanes=r,t.numIntersection=0}function u(e,n,r,i){let a=e===null?0:e.length,l=null;if(a!==0){if(l=c.value,i!==!0||l===null){let t=r+a*4,i=n.matrixWorldInverse;s.getNormalMatrix(i),(l===null||l.length<t)&&(l=new Float32Array(t));for(let t=0,n=r;t!==a;++t,n+=4)o.copy(e[t]).applyMatrix4(i,s),o.normal.toArray(l,n),l[n+3]=o.constant}c.value=l,c.needsUpdate=!0}return t.numPlanes=a,t.numIntersection=0,l}}var Sm=4,Cm=[.125,.215,.35,.446,.526,.582],wm=20,Tm=256,Em=new re,Dm=new kt,Om=null,km=0,Am=0,jm=!1,Mm=new Y,Nm=class{constructor(e){this._renderer=e,this._pingPongRenderTarget=null,this._lodMax=0,this._cubeSize=0,this._sizeLods=[],this._sigmas=[],this._lodMeshes=[],this._backgroundBox=null,this._cubemapMaterial=null,this._equirectMaterial=null,this._blurMaterial=null,this._ggxMaterial=null}fromScene(e,t=0,n=.1,r=100,i={}){let{size:a=256,position:o=Mm}=i;Om=this._renderer.getRenderTarget(),km=this._renderer.getActiveCubeFace(),Am=this._renderer.getActiveMipmapLevel(),jm=this._renderer.xr.enabled,this._renderer.xr.enabled=!1,this._setSize(a);let s=this._allocateTargets();return s.depthBuffer=!0,this._sceneToCubeUV(e,n,r,s,o),t>0&&this._blur(s,0,0,t),this._applyPMREM(s),this._cleanup(s),s}fromEquirectangular(e,t=null){return this._fromTexture(e,t)}fromCubemap(e,t=null){return this._fromTexture(e,t)}compileCubemapShader(){this._cubemapMaterial===null&&(this._cubemapMaterial=Bm(),this._compileMaterial(this._cubemapMaterial))}compileEquirectangularShader(){this._equirectMaterial===null&&(this._equirectMaterial=zm(),this._compileMaterial(this._equirectMaterial))}dispose(){this._dispose(),this._cubemapMaterial!==null&&this._cubemapMaterial.dispose(),this._equirectMaterial!==null&&this._equirectMaterial.dispose(),this._backgroundBox!==null&&(this._backgroundBox.geometry.dispose(),this._backgroundBox.material.dispose())}_setSize(e){this._lodMax=Math.floor(Math.log2(e)),this._cubeSize=2**this._lodMax}_dispose(){this._blurMaterial!==null&&this._blurMaterial.dispose(),this._ggxMaterial!==null&&this._ggxMaterial.dispose(),this._pingPongRenderTarget!==null&&this._pingPongRenderTarget.dispose();for(let e=0;e<this._lodMeshes.length;e++)this._lodMeshes[e].geometry.dispose()}_cleanup(e){this._renderer.setRenderTarget(Om,km,Am),this._renderer.xr.enabled=jm,e.scissorTest=!1,Im(e,0,0,e.width,e.height)}_fromTexture(e,t){e.mapping===301||e.mapping===302?this._setSize(e.image.length===0?16:e.image[0].width||e.image[0].image.width):this._setSize(e.image.width/4),Om=this._renderer.getRenderTarget(),km=this._renderer.getActiveCubeFace(),Am=this._renderer.getActiveMipmapLevel(),jm=this._renderer.xr.enabled,this._renderer.xr.enabled=!1;let n=t||this._allocateTargets();return this._textureToCubeUV(e,n),this._applyPMREM(n),this._cleanup(n),n}_allocateTargets(){let e=3*Math.max(this._cubeSize,112),t=4*this._cubeSize,n={magFilter:Me,minFilter:Me,generateMipmaps:!1,type:an,format:st,colorSpace:Mt,depthBuffer:!1},r=Fm(e,t,n);if(this._pingPongRenderTarget===null||this._pingPongRenderTarget.width!==e||this._pingPongRenderTarget.height!==t){this._pingPongRenderTarget!==null&&this._dispose(),this._pingPongRenderTarget=Fm(e,t,n);let{_lodMax:r}=this;({lodMeshes:this._lodMeshes,sizeLods:this._sizeLods,sigmas:this._sigmas}=Pm(r)),this._blurMaterial=Rm(r,e,t),this._ggxMaterial=Lm(r,e,t)}return r}_compileMaterial(e){let t=new wr(new Er,e);this._renderer.compile(t,Em)}_sceneToCubeUV(e,t,n,r,i){let a=new Ye(90,1,t,n),o=[1,-1,1,1,1,1],s=[1,1,1,-1,-1,-1],c=this._renderer,l=c.autoClear,u=c.toneMapping;c.getClearColor(Dm),c.toneMapping=0,c.autoClear=!1,c.state.buffers.depth.getReversed()&&(c.setRenderTarget(r),c.clearDepth(),c.setRenderTarget(null)),this._backgroundBox===null&&(this._backgroundBox=new wr(new Ge,new wn({name:`PMREM.Background`,side:1,depthWrite:!1,depthTest:!1})));let d=this._backgroundBox,f=d.material,p=!1,m=e.background;m?m.isColor&&(f.color.copy(m),e.background=null,p=!0):(f.color.copy(Dm),p=!0);for(let t=0;t<6;t++){let n=t%3;n===0?(a.up.set(0,o[t],0),a.position.set(i.x,i.y,i.z),a.lookAt(i.x+s[t],i.y,i.z)):n===1?(a.up.set(0,0,o[t]),a.position.set(i.x,i.y,i.z),a.lookAt(i.x,i.y+s[t],i.z)):(a.up.set(0,o[t],0),a.position.set(i.x,i.y,i.z),a.lookAt(i.x,i.y,i.z+s[t]));let l=this._cubeSize;Im(r,n*l,t>2?l:0,l,l),c.setRenderTarget(r),p&&c.render(d,a),c.render(e,a)}c.toneMapping=u,c.autoClear=l,e.background=m}_textureToCubeUV(e,t){let n=this._renderer,r=e.mapping===301||e.mapping===302;r?(this._cubemapMaterial===null&&(this._cubemapMaterial=Bm()),this._cubemapMaterial.uniforms.flipEnvMap.value=e.isRenderTargetTexture===!1?-1:1):this._equirectMaterial===null&&(this._equirectMaterial=zm());let i=r?this._cubemapMaterial:this._equirectMaterial,a=this._lodMeshes[0];a.material=i;let o=i.uniforms;o.envMap.value=e;let s=this._cubeSize;Im(t,0,0,3*s,2*s),n.setRenderTarget(t),n.render(a,Em)}_applyPMREM(e){let t=this._renderer,n=t.autoClear;t.autoClear=!1;let r=this._lodMeshes.length;for(let t=1;t<r;t++)this._applyGGXFilter(e,t-1,t);t.autoClear=n}_applyGGXFilter(e,t,n){let r=this._renderer,i=this._pingPongRenderTarget,a=this._ggxMaterial,o=this._lodMeshes[n];o.material=a;let s=a.uniforms,c=n/(this._lodMeshes.length-1),l=t/(this._lodMeshes.length-1),u=Math.sqrt(c*c-l*l)*(0+c*1.25),{_lodMax:d}=this,f=this._sizeLods[n],p=3*f*(n>d-Sm?n-d+Sm:0),m=4*(this._cubeSize-f);s.envMap.value=e.texture,s.roughness.value=u,s.mipInt.value=d-t,Im(i,p,m,3*f,2*f),r.setRenderTarget(i),r.render(o,Em),s.envMap.value=i.texture,s.roughness.value=0,s.mipInt.value=d-n,Im(e,p,m,3*f,2*f),r.setRenderTarget(e),r.render(o,Em)}_blur(e,t,n,r,i){let a=this._pingPongRenderTarget;this._halfBlur(e,a,t,n,r,`latitudinal`,i),this._halfBlur(a,e,n,n,r,`longitudinal`,i)}_halfBlur(e,t,n,r,i,a,o){let s=this._renderer,c=this._blurMaterial;a!==`latitudinal`&&a!==`longitudinal`&&na(`blur direction must be either latitudinal or longitudinal!`);let l=this._lodMeshes[r];l.material=c;let u=c.uniforms,d=this._sizeLods[n]-1,f=isFinite(i)?Math.PI/(2*d):2*Math.PI/(2*wm-1),p=i/f,m=isFinite(i)?1+Math.floor(3*p):wm;m>wm&&P(`sigmaRadians, ${i}, is too large and will clip, as it requested ${m} samples when the maximum is set to ${wm}`);let h=[],g=0;for(let e=0;e<wm;++e){let t=e/p,n=Math.exp(-t*t/2);h.push(n),e===0?g+=n:e<m&&(g+=2*n)}for(let e=0;e<h.length;e++)h[e]=h[e]/g;u.envMap.value=e.texture,u.samples.value=m,u.weights.value=h,u.latitudinal.value=a===`latitudinal`,o&&(u.poleAxis.value=o);let{_lodMax:_}=this;u.dTheta.value=f,u.mipInt.value=_-n;let v=this._sizeLods[r];Im(t,3*v*(r>_-Sm?r-_+Sm:0),4*(this._cubeSize-v),3*v,2*v),s.setRenderTarget(t),s.render(l,Em)}};function Pm(e){let t=[],n=[],r=[],i=e,a=e-Sm+1+Cm.length;for(let o=0;o<a;o++){let a=2**i;t.push(a);let c=1/a;o>e-Sm?c=Cm[o-e+Sm-1]:o===0&&(c=0),n.push(c);let l=1/(a-2),u=-l,d=1+l,f=[u,u,d,u,d,d,u,u,d,d,u,d],p=new Float32Array(108),m=new Float32Array(72),h=new Float32Array(36);for(let e=0;e<6;e++){let t=e%3*2/3-1,n=e>2?0:-1,r=[t,n,0,t+2/3,n,0,t+2/3,n+1,0,t,n,0,t+2/3,n+1,0,t,n+1,0];p.set(r,18*e),m.set(f,12*e);let i=[e,e,e,e,e,e];h.set(i,6*e)}let g=new Er;g.setAttribute(`position`,new s(p,3)),g.setAttribute(`uv`,new s(m,2)),g.setAttribute(`faceIndex`,new s(h,1)),r.push(new wr(g,null)),i>Sm&&i--}return{lodMeshes:r,sizeLods:t,sigmas:n}}function Fm(e,t,n){let r=new Ln(e,t,n);return r.texture.mapping=306,r.texture.name=`PMREM.cubeUv`,r.scissorTest=!0,r}function Im(e,t,n,r,i){e.viewport.set(t,n,r,i),e.scissor.set(t,n,r,i)}function Lm(e,t,n){return new r({name:`PMREMGGXConvolution`,defines:{GGX_SAMPLES:Tm,CUBEUV_TEXEL_WIDTH:1/t,CUBEUV_TEXEL_HEIGHT:1/n,CUBEUV_MAX_MIP:`${e}.0`},uniforms:{envMap:{value:null},roughness:{value:0},mipInt:{value:0}},vertexShader:Vm(),fragmentShader:`

			precision highp float;
			precision highp int;

			varying vec3 vOutputDirection;

			uniform sampler2D envMap;
			uniform float roughness;
			uniform float mipInt;

			#define ENVMAP_TYPE_CUBE_UV
			#include <cube_uv_reflection_fragment>

			#define PI 3.14159265359

			// Van der Corput radical inverse
			float radicalInverse_VdC(uint bits) {
				bits = (bits << 16u) | (bits >> 16u);
				bits = ((bits & 0x55555555u) << 1u) | ((bits & 0xAAAAAAAAu) >> 1u);
				bits = ((bits & 0x33333333u) << 2u) | ((bits & 0xCCCCCCCCu) >> 2u);
				bits = ((bits & 0x0F0F0F0Fu) << 4u) | ((bits & 0xF0F0F0F0u) >> 4u);
				bits = ((bits & 0x00FF00FFu) << 8u) | ((bits & 0xFF00FF00u) >> 8u);
				return float(bits) * 2.3283064365386963e-10; // / 0x100000000
			}

			// Hammersley sequence
			vec2 hammersley(uint i, uint N) {
				return vec2(float(i) / float(N), radicalInverse_VdC(i));
			}

			// GGX VNDF importance sampling (Eric Heitz 2018)
			// "Sampling the GGX Distribution of Visible Normals"
			// https://jcgt.org/published/0007/04/01/
			vec3 importanceSampleGGX_VNDF(vec2 Xi, vec3 V, float roughness) {
				float alpha = roughness * roughness;

				// Section 4.1: Orthonormal basis
				vec3 T1 = vec3(1.0, 0.0, 0.0);
				vec3 T2 = cross(V, T1);

				// Section 4.2: Parameterization of projected area
				float r = sqrt(Xi.x);
				float phi = 2.0 * PI * Xi.y;
				float t1 = r * cos(phi);
				float t2 = r * sin(phi);
				float s = 0.5 * (1.0 + V.z);
				t2 = (1.0 - s) * sqrt(1.0 - t1 * t1) + s * t2;

				// Section 4.3: Reprojection onto hemisphere
				vec3 Nh = t1 * T1 + t2 * T2 + sqrt(max(0.0, 1.0 - t1 * t1 - t2 * t2)) * V;

				// Section 3.4: Transform back to ellipsoid configuration
				return normalize(vec3(alpha * Nh.x, alpha * Nh.y, max(0.0, Nh.z)));
			}

			void main() {
				vec3 N = normalize(vOutputDirection);
				vec3 V = N; // Assume view direction equals normal for pre-filtering

				vec3 prefilteredColor = vec3(0.0);
				float totalWeight = 0.0;

				// For very low roughness, just sample the environment directly
				if (roughness < 0.001) {
					gl_FragColor = vec4(bilinearCubeUV(envMap, N, mipInt), 1.0);
					return;
				}

				// Tangent space basis for VNDF sampling
				vec3 up = abs(N.z) < 0.999 ? vec3(0.0, 0.0, 1.0) : vec3(1.0, 0.0, 0.0);
				vec3 tangent = normalize(cross(up, N));
				vec3 bitangent = cross(N, tangent);

				for(uint i = 0u; i < uint(GGX_SAMPLES); i++) {
					vec2 Xi = hammersley(i, uint(GGX_SAMPLES));

					// For PMREM, V = N, so in tangent space V is always (0, 0, 1)
					vec3 H_tangent = importanceSampleGGX_VNDF(Xi, vec3(0.0, 0.0, 1.0), roughness);

					// Transform H back to world space
					vec3 H = normalize(tangent * H_tangent.x + bitangent * H_tangent.y + N * H_tangent.z);
					vec3 L = normalize(2.0 * dot(V, H) * H - V);

					float NdotL = max(dot(N, L), 0.0);

					if(NdotL > 0.0) {
						// Sample environment at fixed mip level
						// VNDF importance sampling handles the distribution filtering
						vec3 sampleColor = bilinearCubeUV(envMap, L, mipInt);

						// Weight by NdotL for the split-sum approximation
						// VNDF PDF naturally accounts for the visible microfacet distribution
						prefilteredColor += sampleColor * NdotL;
						totalWeight += NdotL;
					}
				}

				if (totalWeight > 0.0) {
					prefilteredColor = prefilteredColor / totalWeight;
				}

				gl_FragColor = vec4(prefilteredColor, 1.0);
			}
		`,blending:0,depthTest:!1,depthWrite:!1})}function Rm(e,t,n){let i=new Float32Array(wm),a=new Y(0,1,0);return new r({name:`SphericalGaussianBlur`,defines:{n:wm,CUBEUV_TEXEL_WIDTH:1/t,CUBEUV_TEXEL_HEIGHT:1/n,CUBEUV_MAX_MIP:`${e}.0`},uniforms:{envMap:{value:null},samples:{value:1},weights:{value:i},latitudinal:{value:!1},dTheta:{value:0},mipInt:{value:0},poleAxis:{value:a}},vertexShader:Vm(),fragmentShader:`

			precision mediump float;
			precision mediump int;

			varying vec3 vOutputDirection;

			uniform sampler2D envMap;
			uniform int samples;
			uniform float weights[ n ];
			uniform bool latitudinal;
			uniform float dTheta;
			uniform float mipInt;
			uniform vec3 poleAxis;

			#define ENVMAP_TYPE_CUBE_UV
			#include <cube_uv_reflection_fragment>

			vec3 getSample( float theta, vec3 axis ) {

				float cosTheta = cos( theta );
				// Rodrigues' axis-angle rotation
				vec3 sampleDirection = vOutputDirection * cosTheta
					+ cross( axis, vOutputDirection ) * sin( theta )
					+ axis * dot( axis, vOutputDirection ) * ( 1.0 - cosTheta );

				return bilinearCubeUV( envMap, sampleDirection, mipInt );

			}

			void main() {

				vec3 axis = latitudinal ? poleAxis : cross( poleAxis, vOutputDirection );

				if ( all( equal( axis, vec3( 0.0 ) ) ) ) {

					axis = vec3( vOutputDirection.z, 0.0, - vOutputDirection.x );

				}

				axis = normalize( axis );

				gl_FragColor = vec4( 0.0, 0.0, 0.0, 1.0 );
				gl_FragColor.rgb += weights[ 0 ] * getSample( 0.0, axis );

				for ( int i = 1; i < n; i++ ) {

					if ( i >= samples ) {

						break;

					}

					float theta = dTheta * float( i );
					gl_FragColor.rgb += weights[ i ] * getSample( -1.0 * theta, axis );
					gl_FragColor.rgb += weights[ i ] * getSample( theta, axis );

				}

			}
		`,blending:0,depthTest:!1,depthWrite:!1})}function zm(){return new r({name:`EquirectangularToCubeUV`,uniforms:{envMap:{value:null}},vertexShader:Vm(),fragmentShader:`

			precision mediump float;
			precision mediump int;

			varying vec3 vOutputDirection;

			uniform sampler2D envMap;

			#include <common>

			void main() {

				vec3 outputDirection = normalize( vOutputDirection );
				vec2 uv = equirectUv( outputDirection );

				gl_FragColor = vec4( texture2D ( envMap, uv ).rgb, 1.0 );

			}
		`,blending:0,depthTest:!1,depthWrite:!1})}function Bm(){return new r({name:`CubemapToCubeUV`,uniforms:{envMap:{value:null},flipEnvMap:{value:-1}},vertexShader:Vm(),fragmentShader:`

			precision mediump float;
			precision mediump int;

			uniform float flipEnvMap;

			varying vec3 vOutputDirection;

			uniform samplerCube envMap;

			void main() {

				gl_FragColor = textureCube( envMap, vec3( flipEnvMap * vOutputDirection.x, vOutputDirection.yz ) );

			}
		`,blending:0,depthTest:!1,depthWrite:!1})}function Vm(){return`

		precision mediump float;
		precision mediump int;

		attribute float faceIndex;

		varying vec3 vOutputDirection;

		// RH coordinate system; PMREM face-indexing convention
		vec3 getDirection( vec2 uv, float face ) {

			uv = 2.0 * uv - 1.0;

			vec3 direction = vec3( uv, 1.0 );

			if ( face == 0.0 ) {

				direction = direction.zyx; // ( 1, v, u ) pos x

			} else if ( face == 1.0 ) {

				direction = direction.xzy;
				direction.xz *= -1.0; // ( -u, 1, -v ) pos y

			} else if ( face == 2.0 ) {

				direction.x *= -1.0; // ( -u, v, 1 ) pos z

			} else if ( face == 3.0 ) {

				direction = direction.zyx;
				direction.xz *= -1.0; // ( -1, v, -u ) neg x

			} else if ( face == 4.0 ) {

				direction = direction.xzy;
				direction.xy *= -1.0; // ( -u, -1, v ) neg y

			} else if ( face == 5.0 ) {

				direction.z *= -1.0; // ( u, v, -1 ) neg z

			}

			return direction;

		}

		void main() {

			vOutputDirection = getDirection( uv, faceIndex );
			gl_Position = vec4( position, 1.0 );

		}
	`}var Hm=class extends Ln{constructor(e=1,t={}){super(e,e,t),this.isWebGLCubeRenderTarget=!0;let n={width:e,height:e,depth:1},r=[n,n,n,n,n,n];this.texture=new Wi(r),this._setTextureOptions(t),this.texture.isRenderTargetTexture=!0}fromEquirectangularTexture(e,n){this.texture.type=n.type,this.texture.colorSpace=n.colorSpace,this.texture.generateMipmaps=n.generateMipmaps,this.texture.minFilter=n.minFilter,this.texture.magFilter=n.magFilter;let i={uniforms:{tEquirect:{value:null}},vertexShader:`

				varying vec3 vWorldDirection;

				vec3 transformDirection( in vec3 dir, in mat4 matrix ) {

					return normalize( ( matrix * vec4( dir, 0.0 ) ).xyz );

				}

				void main() {

					vWorldDirection = transformDirection( position, modelMatrix );

					#include <begin_vertex>
					#include <project_vertex>

				}
			`,fragmentShader:`

				uniform sampler2D tEquirect;

				varying vec3 vWorldDirection;

				#include <common>

				void main() {

					vec3 direction = normalize( vWorldDirection );

					vec2 sampleUV = equirectUv( direction );

					gl_FragColor = texture2D( tEquirect, sampleUV );

				}
			`},a=new Ge(5,5,5),o=new r({name:`CubemapFromEquirect`,uniforms:gr(i.uniforms),vertexShader:i.vertexShader,fragmentShader:i.fragmentShader,side:1,blending:0});o.uniforms.tEquirect.value=n;let s=new wr(a,o),c=n.minFilter;return n.minFilter===1008&&(n.minFilter=Me),new t(1,10,this).update(e,s),n.minFilter=c,s.geometry.dispose(),s.material.dispose(),this}clear(e,t=!0,n=!0,r=!0){let i=e.getRenderTarget();for(let i=0;i<6;i++)e.setRenderTarget(this,i),e.clear(t,n,r);e.setRenderTarget(i)}};function Um(e){let t=new WeakMap,n=new WeakMap,r=null;function i(e,t=!1){return e==null?null:t?o(e):a(e)}function a(n){if(n&&n.isTexture){let r=n.mapping;if(r===303||r===304)if(t.has(n)){let e=t.get(n).texture;return s(e,n.mapping)}else{let r=n.image;if(r&&r.height>0){let i=new Hm(r.height);return i.fromEquirectangularTexture(e,n),t.set(n,i),n.addEventListener(`dispose`,l),s(i.texture,n.mapping)}else return null}}return n}function o(t){if(t&&t.isTexture){let i=t.mapping,a=i===303||i===304,o=i===301||i===302;if(a||o){let i=n.get(t),s=i===void 0?0:i.texture.pmremVersion;if(t.isRenderTargetTexture&&t.pmremVersion!==s)return r===null&&(r=new Nm(e)),i=a?r.fromEquirectangular(t,i):r.fromCubemap(t,i),i.texture.pmremVersion=t.pmremVersion,n.set(t,i),i.texture;if(i!==void 0)return i.texture;{let s=t.image;return a&&s&&s.height>0||o&&s&&c(s)?(r===null&&(r=new Nm(e)),i=a?r.fromEquirectangular(t):r.fromCubemap(t),i.texture.pmremVersion=t.pmremVersion,n.set(t,i),t.addEventListener(`dispose`,u),i.texture):null}}}return t}function s(e,t){return t===303?e.mapping=301:t===304&&(e.mapping=302),e}function c(e){let t=0;for(let n=0;n<6;n++)e[n]!==void 0&&t++;return t===6}function l(e){let n=e.target;n.removeEventListener(`dispose`,l);let r=t.get(n);r!==void 0&&(t.delete(n),r.dispose())}function u(e){let t=e.target;t.removeEventListener(`dispose`,u);let r=n.get(t);r!==void 0&&(n.delete(t),r.dispose())}function d(){t=new WeakMap,n=new WeakMap,r!==null&&(r.dispose(),r=null)}return{get:i,dispose:d}}function Wm(e){let t={};function n(n){if(t[n]!==void 0)return t[n];let r=e.getExtension(n);return t[n]=r,r}return{has:function(e){return n(e)!==null},init:function(){n(`EXT_color_buffer_float`),n(`WEBGL_clip_cull_distance`),n(`OES_texture_float_linear`),n(`EXT_color_buffer_half_float`),n(`WEBGL_multisampled_render_to_texture`),n(`WEBGL_render_shared_exponent`)},get:function(e){let t=n(e);return t===null&&ee(`WebGLRenderer: `+e+` extension not supported.`),t}}}function Gm(e,t,n,r){let i={},a=new WeakMap;function o(e){let s=e.target;s.index!==null&&t.remove(s.index);for(let e in s.attributes)t.remove(s.attributes[e]);s.removeEventListener(`dispose`,o),delete i[s.id];let c=a.get(s);c&&(t.remove(c),a.delete(s)),r.releaseStatesOfGeometry(s),s.isInstancedBufferGeometry===!0&&delete s._maxInstanceCount,n.memory.geometries--}function s(e,t){return i[t.id]===!0?t:(t.addEventListener(`dispose`,o),i[t.id]=!0,n.memory.geometries++,t)}function c(n){let r=n.attributes;for(let n in r)t.update(r[n],e.ARRAY_BUFFER)}function l(e){let n=[],r=e.index,i=e.attributes.position,o=0;if(i===void 0)return;if(r!==null){let e=r.array;o=r.version;for(let t=0,r=e.length;t<r;t+=3){let r=e[t+0],i=e[t+1],a=e[t+2];n.push(r,i,i,a,a,r)}}else{let e=i.array;o=i.version;for(let t=0,r=e.length/3-1;t<r;t+=3){let e=t+0,r=t+1,i=t+2;n.push(e,r,r,i,i,e)}}let s=new(i.count>=65535?Da:ut)(n,1);s.version=o;let c=a.get(e);c&&t.remove(c),a.set(e,s)}function u(e){let t=a.get(e);if(t){let n=e.index;n!==null&&t.version<n.version&&l(e)}else l(e);return a.get(e)}return{get:s,update:c,getWireframeAttribute:u}}function Km(e,t,n){let r;function i(e){r=e}let a,o;function s(e){a=e.type,o=e.bytesPerElement}function c(t,i){e.drawElements(r,i,a,t*o),n.update(i,r,1)}function l(t,i,s){s!==0&&(e.drawElementsInstanced(r,i,a,t*o,s),n.update(i,r,s))}function u(e,i,o){if(o===0)return;t.get(`WEBGL_multi_draw`).multiDrawElementsWEBGL(r,i,0,a,e,0,o);let s=0;for(let e=0;e<o;e++)s+=i[e];n.update(s,r,1)}this.setMode=i,this.setIndex=s,this.render=c,this.renderInstances=l,this.renderMultiDraw=u}function qm(e){let t={geometries:0,textures:0},n={frame:0,calls:0,triangles:0,points:0,lines:0};function r(t,r,i){switch(n.calls++,r){case e.TRIANGLES:n.triangles+=t/3*i;break;case e.LINES:n.lines+=t/2*i;break;case e.LINE_STRIP:n.lines+=i*(t-1);break;case e.LINE_LOOP:n.lines+=i*t;break;case e.POINTS:n.points+=i*t;break;default:na(`WebGLInfo: Unknown draw mode:`,r);break}}function i(){n.calls=0,n.triangles=0,n.points=0,n.lines=0}return{memory:t,render:n,programs:null,autoReset:!0,reset:i,update:r}}function Jm(e,t,r){let i=new WeakMap,a=new Hi;function o(o,s,c){let l=o.morphTargetInfluences,u=s.morphAttributes.position||s.morphAttributes.normal||s.morphAttributes.color,d=u===void 0?0:u.length,f=i.get(s);if(f===void 0||f.count!==d){f!==void 0&&f.texture.dispose();let e=s.morphAttributes.position!==void 0,r=s.morphAttributes.normal!==void 0,o=s.morphAttributes.color!==void 0,c=s.morphAttributes.position||[],l=s.morphAttributes.normal||[],u=s.morphAttributes.color||[],p=0;e===!0&&(p=1),r===!0&&(p=2),o===!0&&(p=3);let m=s.attributes.position.count*p,h=1;m>t.maxTextureSize&&(h=Math.ceil(m/t.maxTextureSize),m=t.maxTextureSize);let g=new Float32Array(m*h*4*d),_=new Kn(g,m,h,d);_.type=mt,_.needsUpdate=!0;let v=p*4;for(let t=0;t<d;t++){let n=c[t],i=l[t],s=u[t],d=m*h*4*t;for(let t=0;t<n.count;t++){let c=t*v;e===!0&&(a.fromBufferAttribute(n,t),g[d+c+0]=a.x,g[d+c+1]=a.y,g[d+c+2]=a.z,g[d+c+3]=0),r===!0&&(a.fromBufferAttribute(i,t),g[d+c+4]=a.x,g[d+c+5]=a.y,g[d+c+6]=a.z,g[d+c+7]=0),o===!0&&(a.fromBufferAttribute(s,t),g[d+c+8]=a.x,g[d+c+9]=a.y,g[d+c+10]=a.z,g[d+c+11]=s.itemSize===4?a.w:1)}}f={count:d,texture:_,size:new n(m,h)},i.set(s,f);function y(){_.dispose(),i.delete(s),s.removeEventListener(`dispose`,y)}s.addEventListener(`dispose`,y)}if(o.isInstancedMesh===!0&&o.morphTexture!==null)c.getUniforms().setValue(e,`morphTexture`,o.morphTexture,r);else{let t=0;for(let e=0;e<l.length;e++)t+=l[e];let n=s.morphTargetsRelative?1:1-t;c.getUniforms().setValue(e,`morphTargetBaseInfluence`,n),c.getUniforms().setValue(e,`morphTargetInfluences`,l)}c.getUniforms().setValue(e,`morphTargetsTexture`,f.texture,r),c.getUniforms().setValue(e,`morphTargetsTextureSize`,f.size)}return{update:o}}function Ym(e,t,n,r,i){let a=new WeakMap;function o(r){let o=i.render.frame,s=r.geometry,l=t.get(r,s);if(a.get(l)!==o&&(t.update(l),a.set(l,o)),r.isInstancedMesh&&(r.hasEventListener(`dispose`,c)===!1&&r.addEventListener(`dispose`,c),a.get(r)!==o&&(n.update(r.instanceMatrix,e.ARRAY_BUFFER),r.instanceColor!==null&&n.update(r.instanceColor,e.ARRAY_BUFFER),a.set(r,o))),r.isSkinnedMesh){let e=r.skeleton;a.get(e)!==o&&(e.update(),a.set(e,o))}return l}function s(){a=new WeakMap}function c(e){let t=e.target;t.removeEventListener(`dispose`,c),r.releaseStatesOfObject(t),n.remove(t.instanceMatrix),t.instanceColor!==null&&n.remove(t.instanceColor)}return{update:o,dispose:s}}var Xm={1:`LINEAR_TONE_MAPPING`,2:`REINHARD_TONE_MAPPING`,3:`CINEON_TONE_MAPPING`,4:`ACES_FILMIC_TONE_MAPPING`,6:`AGX_TONE_MAPPING`,7:`NEUTRAL_TONE_MAPPING`,5:`CUSTOM_TONE_MAPPING`};function Zm(e,t,n,r,i,a){let o=new Ln(t,n,{type:e,depthBuffer:i,stencilBuffer:a,samples:r?4:0,depthTexture:i?new Mn(t,n):void 0}),s=new Ln(t,n,{type:an,depthBuffer:!1,stencilBuffer:!1}),c=new Er;c.setAttribute(`position`,new Pe([-1,3,0,-1,-1,0,3,-1,0],3)),c.setAttribute(`uv`,new Pe([0,2,0,0,2,0],2));let l=new $e({uniforms:{tDiffuse:{value:null}},vertexShader:`
			precision highp float;

			uniform mat4 modelViewMatrix;
			uniform mat4 projectionMatrix;

			attribute vec3 position;
			attribute vec2 uv;

			varying vec2 vUv;

			void main() {
				vUv = uv;
				gl_Position = projectionMatrix * modelViewMatrix * vec4( position, 1.0 );
			}`,fragmentShader:`
			precision highp float;

			uniform sampler2D tDiffuse;

			varying vec2 vUv;

			#include <tonemapping_pars_fragment>
			#include <colorspace_pars_fragment>

			void main() {
				gl_FragColor = texture2D( tDiffuse, vUv );

				#ifdef LINEAR_TONE_MAPPING
					gl_FragColor.rgb = LinearToneMapping( gl_FragColor.rgb );
				#elif defined( REINHARD_TONE_MAPPING )
					gl_FragColor.rgb = ReinhardToneMapping( gl_FragColor.rgb );
				#elif defined( CINEON_TONE_MAPPING )
					gl_FragColor.rgb = CineonToneMapping( gl_FragColor.rgb );
				#elif defined( ACES_FILMIC_TONE_MAPPING )
					gl_FragColor.rgb = ACESFilmicToneMapping( gl_FragColor.rgb );
				#elif defined( AGX_TONE_MAPPING )
					gl_FragColor.rgb = AgXToneMapping( gl_FragColor.rgb );
				#elif defined( NEUTRAL_TONE_MAPPING )
					gl_FragColor.rgb = NeutralToneMapping( gl_FragColor.rgb );
				#elif defined( CUSTOM_TONE_MAPPING )
					gl_FragColor.rgb = CustomToneMapping( gl_FragColor.rgb );
				#endif

				#ifdef SRGB_TRANSFER
					gl_FragColor = sRGBTransferOETF( gl_FragColor );
				#endif
			}`,depthTest:!1,depthWrite:!1}),u=new wr(c,l),d=new re(-1,1,1,-1,0,1),f=null,p=null,m=!1,h,g=null,_=[],v=!1;this.setSize=function(e,t){o.setSize(e,t),s.setSize(e,t);for(let n=0;n<_.length;n++){let r=_[n];r.setSize&&r.setSize(e,t)}},this.setEffects=function(e){_=e,v=_.length>0&&_[0].isRenderPass===!0;let t=o.width,n=o.height;for(let e=0;e<_.length;e++){let r=_[e];r.setSize&&r.setSize(t,n)}},this.begin=function(e,t){if(m||e.toneMapping===0&&_.length===0)return!1;if(g=t,t!==null){let e=t.width,n=t.height;(o.width!==e||o.height!==n)&&this.setSize(e,n)}return v===!1&&e.setRenderTarget(o),h=e.toneMapping,e.toneMapping=0,!0},this.hasRenderPass=function(){return v},this.end=function(e,t){e.toneMapping=h,m=!0;let n=o,r=s;for(let i=0;i<_.length;i++){let a=_[i];if(a.enabled!==!1&&(a.render(e,r,n,t),a.needsSwap!==!1)){let e=n;n=r,r=e}}if(f!==e.outputColorSpace||p!==e.toneMapping){f=e.outputColorSpace,p=e.toneMapping,l.defines={},z.getTransfer(f)===`srgb`&&(l.defines.SRGB_TRANSFER=``);let t=Xm[p];t&&(l.defines[t]=``),l.needsUpdate=!0}l.uniforms.tDiffuse.value=n.texture,e.setRenderTarget(g),e.render(u,d),g=null,m=!1},this.isCompositing=function(){return m},this.dispose=function(){o.depthTexture&&o.depthTexture.dispose(),o.dispose(),s.dispose(),c.dispose(),l.dispose()}}var Qm=new Nr,$m=new Mn(1,1),eh=new Kn,th=new Zi,nh=new Wi,rh=[],ih=[],ah=new Float32Array(16),oh=new Float32Array(9),sh=new Float32Array(4);function ch(e,t,n){let r=e[0];if(r<=0||r>0)return e;let i=t*n,a=rh[i];if(a===void 0&&(a=new Float32Array(i),rh[i]=a),t!==0){r.toArray(a,0);for(let r=1,i=0;r!==t;++r)i+=n,e[r].toArray(a,i)}return a}function lh(e,t){if(e.length!==t.length)return!1;for(let n=0,r=e.length;n<r;n++)if(e[n]!==t[n])return!1;return!0}function uh(e,t){for(let n=0,r=t.length;n<r;n++)e[n]=t[n]}function dh(e,t){let n=ih[t];n===void 0&&(n=new Int32Array(t),ih[t]=n);for(let r=0;r!==t;++r)n[r]=e.allocateTextureUnit();return n}function fh(e,t){let n=this.cache;n[0]!==t&&(e.uniform1f(this.addr,t),n[0]=t)}function ph(e,t){let n=this.cache;if(t.x!==void 0)(n[0]!==t.x||n[1]!==t.y)&&(e.uniform2f(this.addr,t.x,t.y),n[0]=t.x,n[1]=t.y);else{if(lh(n,t))return;e.uniform2fv(this.addr,t),uh(n,t)}}function mh(e,t){let n=this.cache;if(t.x!==void 0)(n[0]!==t.x||n[1]!==t.y||n[2]!==t.z)&&(e.uniform3f(this.addr,t.x,t.y,t.z),n[0]=t.x,n[1]=t.y,n[2]=t.z);else if(t.r!==void 0)(n[0]!==t.r||n[1]!==t.g||n[2]!==t.b)&&(e.uniform3f(this.addr,t.r,t.g,t.b),n[0]=t.r,n[1]=t.g,n[2]=t.b);else{if(lh(n,t))return;e.uniform3fv(this.addr,t),uh(n,t)}}function hh(e,t){let n=this.cache;if(t.x!==void 0)(n[0]!==t.x||n[1]!==t.y||n[2]!==t.z||n[3]!==t.w)&&(e.uniform4f(this.addr,t.x,t.y,t.z,t.w),n[0]=t.x,n[1]=t.y,n[2]=t.z,n[3]=t.w);else{if(lh(n,t))return;e.uniform4fv(this.addr,t),uh(n,t)}}function gh(e,t){let n=this.cache,r=t.elements;if(r===void 0){if(lh(n,t))return;e.uniformMatrix2fv(this.addr,!1,t),uh(n,t)}else{if(lh(n,r))return;sh.set(r),e.uniformMatrix2fv(this.addr,!1,sh),uh(n,r)}}function _h(e,t){let n=this.cache,r=t.elements;if(r===void 0){if(lh(n,t))return;e.uniformMatrix3fv(this.addr,!1,t),uh(n,t)}else{if(lh(n,r))return;oh.set(r),e.uniformMatrix3fv(this.addr,!1,oh),uh(n,r)}}function vh(e,t){let n=this.cache,r=t.elements;if(r===void 0){if(lh(n,t))return;e.uniformMatrix4fv(this.addr,!1,t),uh(n,t)}else{if(lh(n,r))return;ah.set(r),e.uniformMatrix4fv(this.addr,!1,ah),uh(n,r)}}function yh(e,t){let n=this.cache;n[0]!==t&&(e.uniform1i(this.addr,t),n[0]=t)}function bh(e,t){let n=this.cache;if(t.x!==void 0)(n[0]!==t.x||n[1]!==t.y)&&(e.uniform2i(this.addr,t.x,t.y),n[0]=t.x,n[1]=t.y);else{if(lh(n,t))return;e.uniform2iv(this.addr,t),uh(n,t)}}function xh(e,t){let n=this.cache;if(t.x!==void 0)(n[0]!==t.x||n[1]!==t.y||n[2]!==t.z)&&(e.uniform3i(this.addr,t.x,t.y,t.z),n[0]=t.x,n[1]=t.y,n[2]=t.z);else{if(lh(n,t))return;e.uniform3iv(this.addr,t),uh(n,t)}}function Sh(e,t){let n=this.cache;if(t.x!==void 0)(n[0]!==t.x||n[1]!==t.y||n[2]!==t.z||n[3]!==t.w)&&(e.uniform4i(this.addr,t.x,t.y,t.z,t.w),n[0]=t.x,n[1]=t.y,n[2]=t.z,n[3]=t.w);else{if(lh(n,t))return;e.uniform4iv(this.addr,t),uh(n,t)}}function Ch(e,t){let n=this.cache;n[0]!==t&&(e.uniform1ui(this.addr,t),n[0]=t)}function wh(e,t){let n=this.cache;if(t.x!==void 0)(n[0]!==t.x||n[1]!==t.y)&&(e.uniform2ui(this.addr,t.x,t.y),n[0]=t.x,n[1]=t.y);else{if(lh(n,t))return;e.uniform2uiv(this.addr,t),uh(n,t)}}function Th(e,t){let n=this.cache;if(t.x!==void 0)(n[0]!==t.x||n[1]!==t.y||n[2]!==t.z)&&(e.uniform3ui(this.addr,t.x,t.y,t.z),n[0]=t.x,n[1]=t.y,n[2]=t.z);else{if(lh(n,t))return;e.uniform3uiv(this.addr,t),uh(n,t)}}function Eh(e,t){let n=this.cache;if(t.x!==void 0)(n[0]!==t.x||n[1]!==t.y||n[2]!==t.z||n[3]!==t.w)&&(e.uniform4ui(this.addr,t.x,t.y,t.z,t.w),n[0]=t.x,n[1]=t.y,n[2]=t.z,n[3]=t.w);else{if(lh(n,t))return;e.uniform4uiv(this.addr,t),uh(n,t)}}function Dh(e,t,n){let r=this.cache,i=n.allocateTextureUnit();r[0]!==i&&(e.uniform1i(this.addr,i),r[0]=i);let a;this.type===e.SAMPLER_2D_SHADOW?($m.compareFunction=n.isReversedDepthBuffer()?518:515,a=$m):a=Qm,n.setTexture2D(t||a,i)}function Oh(e,t,n){let r=this.cache,i=n.allocateTextureUnit();r[0]!==i&&(e.uniform1i(this.addr,i),r[0]=i),n.setTexture3D(t||th,i)}function kh(e,t,n){let r=this.cache,i=n.allocateTextureUnit();r[0]!==i&&(e.uniform1i(this.addr,i),r[0]=i),n.setTextureCube(t||nh,i)}function Ah(e,t,n){let r=this.cache,i=n.allocateTextureUnit();r[0]!==i&&(e.uniform1i(this.addr,i),r[0]=i),n.setTexture2DArray(t||eh,i)}function jh(e){switch(e){case 5126:return fh;case 35664:return ph;case 35665:return mh;case 35666:return hh;case 35674:return gh;case 35675:return _h;case 35676:return vh;case 5124:case 35670:return yh;case 35667:case 35671:return bh;case 35668:case 35672:return xh;case 35669:case 35673:return Sh;case 5125:return Ch;case 36294:return wh;case 36295:return Th;case 36296:return Eh;case 35678:case 36198:case 36298:case 36306:case 35682:return Dh;case 35679:case 36299:case 36307:return Oh;case 35680:case 36300:case 36308:case 36293:return kh;case 36289:case 36303:case 36311:case 36292:return Ah}}function Mh(e,t){e.uniform1fv(this.addr,t)}function Nh(e,t){let n=ch(t,this.size,2);e.uniform2fv(this.addr,n)}function Ph(e,t){let n=ch(t,this.size,3);e.uniform3fv(this.addr,n)}function Fh(e,t){let n=ch(t,this.size,4);e.uniform4fv(this.addr,n)}function Ih(e,t){let n=ch(t,this.size,4);e.uniformMatrix2fv(this.addr,!1,n)}function Lh(e,t){let n=ch(t,this.size,9);e.uniformMatrix3fv(this.addr,!1,n)}function Rh(e,t){let n=ch(t,this.size,16);e.uniformMatrix4fv(this.addr,!1,n)}function zh(e,t){e.uniform1iv(this.addr,t)}function Bh(e,t){e.uniform2iv(this.addr,t)}function Vh(e,t){e.uniform3iv(this.addr,t)}function Hh(e,t){e.uniform4iv(this.addr,t)}function Uh(e,t){e.uniform1uiv(this.addr,t)}function Wh(e,t){e.uniform2uiv(this.addr,t)}function Gh(e,t){e.uniform3uiv(this.addr,t)}function Kh(e,t){e.uniform4uiv(this.addr,t)}function qh(e,t,n){let r=this.cache,i=t.length,a=dh(n,i);lh(r,a)||(e.uniform1iv(this.addr,a),uh(r,a));let o;o=this.type===e.SAMPLER_2D_SHADOW?$m:Qm;for(let e=0;e!==i;++e)n.setTexture2D(t[e]||o,a[e])}function Jh(e,t,n){let r=this.cache,i=t.length,a=dh(n,i);lh(r,a)||(e.uniform1iv(this.addr,a),uh(r,a));for(let e=0;e!==i;++e)n.setTexture3D(t[e]||th,a[e])}function Yh(e,t,n){let r=this.cache,i=t.length,a=dh(n,i);lh(r,a)||(e.uniform1iv(this.addr,a),uh(r,a));for(let e=0;e!==i;++e)n.setTextureCube(t[e]||nh,a[e])}function Xh(e,t,n){let r=this.cache,i=t.length,a=dh(n,i);lh(r,a)||(e.uniform1iv(this.addr,a),uh(r,a));for(let e=0;e!==i;++e)n.setTexture2DArray(t[e]||eh,a[e])}function Zh(e){switch(e){case 5126:return Mh;case 35664:return Nh;case 35665:return Ph;case 35666:return Fh;case 35674:return Ih;case 35675:return Lh;case 35676:return Rh;case 5124:case 35670:return zh;case 35667:case 35671:return Bh;case 35668:case 35672:return Vh;case 35669:case 35673:return Hh;case 5125:return Uh;case 36294:return Wh;case 36295:return Gh;case 36296:return Kh;case 35678:case 36198:case 36298:case 36306:case 35682:return qh;case 35679:case 36299:case 36307:return Jh;case 35680:case 36300:case 36308:case 36293:return Yh;case 36289:case 36303:case 36311:case 36292:return Xh}}var Qh=class{constructor(e,t,n){this.id=e,this.addr=n,this.cache=[],this.type=t.type,this.setValue=jh(t.type)}},$h=class{constructor(e,t,n){this.id=e,this.addr=n,this.cache=[],this.type=t.type,this.size=t.size,this.setValue=Zh(t.type)}},eg=class{constructor(e){this.id=e,this.seq=[],this.map={}}setValue(e,t,n){let r=this.seq;for(let i=0,a=r.length;i!==a;++i){let a=r[i];a.setValue(e,t[a.id],n)}}},tg=/(\w+)(\])?(\[|\.)?/g;function ng(e,t){e.seq.push(t),e.map[t.id]=t}function rg(e,t,n){let r=e.name,i=r.length;for(tg.lastIndex=0;;){let a=tg.exec(r),o=tg.lastIndex,s=a[1],c=a[2]===`]`,l=a[3];if(c&&(s|=0),l===void 0||l===`[`&&o+2===i){ng(n,l===void 0?new Qh(s,e,t):new $h(s,e,t));break}else{let e=n.map[s];e===void 0&&(e=new eg(s),ng(n,e)),n=e}}}var ig=class{constructor(e,t){this.seq=[],this.map={};let n=e.getProgramParameter(t,e.ACTIVE_UNIFORMS);for(let r=0;r<n;++r){let n=e.getActiveUniform(t,r);rg(n,e.getUniformLocation(t,n.name),this)}let r=[],i=[];for(let t of this.seq)t.type===e.SAMPLER_2D_SHADOW||t.type===e.SAMPLER_CUBE_SHADOW||t.type===e.SAMPLER_2D_ARRAY_SHADOW?r.push(t):i.push(t);r.length>0&&(this.seq=r.concat(i))}setValue(e,t,n,r){let i=this.map[t];i!==void 0&&i.setValue(e,n,r)}setOptional(e,t,n){let r=t[n];r!==void 0&&this.setValue(e,n,r)}static upload(e,t,n,r){for(let i=0,a=t.length;i!==a;++i){let a=t[i],o=n[a.id];o.needsUpdate!==!1&&a.setValue(e,o.value,r)}}static seqWithValue(e,t){let n=[];for(let r=0,i=e.length;r!==i;++r){let i=e[r];i.id in t&&n.push(i)}return n}};function ag(e,t,n){let r=e.createShader(t);return e.shaderSource(r,n),e.compileShader(r),r}var og=37297,sg=0;function cg(e,t){let n=e.split(`
`),r=[],i=Math.max(t-6,0),a=Math.min(t+6,n.length);for(let e=i;e<a;e++){let i=e+1;r.push(`${i===t?`>`:` `} ${i}: ${n[e]}`)}return r.join(`
`)}var lg=new X;function ug(e){z._getMatrix(lg,z.workingColorSpace,e);let t=`mat3( ${lg.elements.map(e=>e.toFixed(4))} )`;switch(z.getTransfer(e)){case Wt:return[t,`LinearTransferOETF`];case cn:return[t,`sRGBTransferOETF`];default:return P(`WebGLProgram: Unsupported color space: `,e),[t,`LinearTransferOETF`]}}function dg(e,t,n){let r=e.getShaderParameter(t,e.COMPILE_STATUS),i=(e.getShaderInfoLog(t)||``).trim();if(r&&i===``)return``;let a=/ERROR: 0:(\d+)/.exec(i);if(a){let r=parseInt(a[1]);return n.toUpperCase()+`

`+i+`

`+cg(e.getShaderSource(t),r)}else return i}function fg(e,t){let n=ug(t);return[`vec4 ${e}( vec4 value ) {`,`	return ${n[1]}( vec4( value.rgb * ${n[0]}, value.a ) );`,`}`].join(`
`)}var pg={1:`Linear`,2:`Reinhard`,3:`Cineon`,4:`ACESFilmic`,6:`AgX`,7:`Neutral`,5:`Custom`};function mg(e,t){let n=pg[t];return n===void 0?(P(`WebGLProgram: Unsupported toneMapping:`,t),`vec3 `+e+`( vec3 color ) { return LinearToneMapping( color ); }`):`vec3 `+e+`( vec3 color ) { return `+n+`ToneMapping( color ); }`}var hg=new Y;function gg(){return z.getLuminanceCoefficients(hg),[`float luminance( const in vec3 rgb ) {`,`	const vec3 weights = vec3( ${hg.x.toFixed(4)}, ${hg.y.toFixed(4)}, ${hg.z.toFixed(4)} );`,`	return dot( weights, rgb );`,`}`].join(`
`)}function _g(e){return[e.extensionClipCullDistance?`#extension GL_ANGLE_clip_cull_distance : require`:``,e.extensionMultiDraw?`#extension GL_ANGLE_multi_draw : require`:``].filter(bg).join(`
`)}function vg(e){let t=[];for(let n in e){let r=e[n];r!==!1&&t.push(`#define `+n+` `+r)}return t.join(`
`)}function yg(e,t){let n={},r=e.getProgramParameter(t,e.ACTIVE_ATTRIBUTES);for(let i=0;i<r;i++){let r=e.getActiveAttrib(t,i),a=r.name,o=1;r.type===e.FLOAT_MAT2&&(o=2),r.type===e.FLOAT_MAT3&&(o=3),r.type===e.FLOAT_MAT4&&(o=4),n[a]={type:r.type,location:e.getAttribLocation(t,a),locationSize:o}}return n}function bg(e){return e!==``}function xg(e,t){let n=t.numSpotLightShadows+t.numSpotLightMaps-t.numSpotLightShadowsWithMaps;return e.replace(/NUM_DIR_LIGHTS/g,t.numDirLights).replace(/NUM_SPOT_LIGHTS/g,t.numSpotLights).replace(/NUM_SPOT_LIGHT_MAPS/g,t.numSpotLightMaps).replace(/NUM_SPOT_LIGHT_COORDS/g,n).replace(/NUM_RECT_AREA_LIGHTS/g,t.numRectAreaLights).replace(/NUM_POINT_LIGHTS/g,t.numPointLights).replace(/NUM_HEMI_LIGHTS/g,t.numHemiLights).replace(/NUM_DIR_LIGHT_SHADOWS/g,t.numDirLightShadows).replace(/NUM_SPOT_LIGHT_SHADOWS_WITH_MAPS/g,t.numSpotLightShadowsWithMaps).replace(/NUM_SPOT_LIGHT_SHADOWS/g,t.numSpotLightShadows).replace(/NUM_POINT_LIGHT_SHADOWS/g,t.numPointLightShadows)}function Sg(e,t){return e.replace(/NUM_CLIPPING_PLANES/g,t.numClippingPlanes).replace(/UNION_CLIPPING_PLANES/g,t.numClippingPlanes-t.numClipIntersection)}var Cg=/^[ \t]*#include +<([\w\d./]+)>/gm;function wg(e){return e.replace(Cg,Eg)}var Tg=new Map;function Eg(e,t){let n=Q[t];if(n===void 0){let e=Tg.get(t);if(e!==void 0)n=Q[e],P(`WebGLRenderer: Shader chunk "%s" has been deprecated. Use "%s" instead.`,t,e);else throw Error(`THREE.WebGLProgram: Can not resolve #include <`+t+`>`)}return wg(n)}var Dg=/#pragma unroll_loop_start\s+for\s*\(\s*int\s+i\s*=\s*(\d+)\s*;\s*i\s*<\s*(\d+)\s*;\s*i\s*\+\+\s*\)\s*{([\s\S]+?)}\s+#pragma unroll_loop_end/g;function Og(e){return e.replace(Dg,kg)}function kg(e,t,n,r){let i=``;for(let e=parseInt(t);e<parseInt(n);e++)i+=r.replace(/\[\s*i\s*\]/g,`[ `+e+` ]`).replace(/UNROLLED_LOOP_INDEX/g,e);return i}function Ag(e){let t=`precision ${e.precision} float;
	precision ${e.precision} int;
	precision ${e.precision} sampler2D;
	precision ${e.precision} samplerCube;
	precision ${e.precision} sampler3D;
	precision ${e.precision} sampler2DArray;
	precision ${e.precision} sampler2DShadow;
	precision ${e.precision} samplerCubeShadow;
	precision ${e.precision} sampler2DArrayShadow;
	precision ${e.precision} isampler2D;
	precision ${e.precision} isampler3D;
	precision ${e.precision} isamplerCube;
	precision ${e.precision} isampler2DArray;
	precision ${e.precision} usampler2D;
	precision ${e.precision} usampler3D;
	precision ${e.precision} usamplerCube;
	precision ${e.precision} usampler2DArray;
	`;return e.precision===`highp`?t+=`
#define HIGH_PRECISION`:e.precision===`mediump`?t+=`
#define MEDIUM_PRECISION`:e.precision===`lowp`&&(t+=`
#define LOW_PRECISION`),t}var jg={1:`SHADOWMAP_TYPE_PCF`,3:`SHADOWMAP_TYPE_VSM`};function Mg(e){return jg[e.shadowMapType]||`SHADOWMAP_TYPE_BASIC`}var Ng={301:`ENVMAP_TYPE_CUBE`,302:`ENVMAP_TYPE_CUBE`,306:`ENVMAP_TYPE_CUBE_UV`};function Pg(e){return e.envMap===!1?`ENVMAP_TYPE_CUBE`:Ng[e.envMapMode]||`ENVMAP_TYPE_CUBE`}var Fg={302:`ENVMAP_MODE_REFRACTION`};function Ig(e){return e.envMap===!1?`ENVMAP_MODE_REFLECTION`:Fg[e.envMapMode]||`ENVMAP_MODE_REFLECTION`}var Lg={0:`ENVMAP_BLENDING_MULTIPLY`,1:`ENVMAP_BLENDING_MIX`,2:`ENVMAP_BLENDING_ADD`};function Rg(e){return e.envMap===!1?`ENVMAP_BLENDING_NONE`:Lg[e.combine]||`ENVMAP_BLENDING_NONE`}function zg(e){let t=e.envMapCubeUVHeight;if(t===null)return null;let n=Math.log2(t)-2,r=1/t;return{texelWidth:1/(3*Math.max(2**n,112)),texelHeight:r,maxMip:n}}function Bg(e,t,n,r){let i=e.getContext(),a=n.defines,o=n.vertexShader,s=n.fragmentShader,c=Mg(n),l=Pg(n),u=Ig(n),d=Rg(n),f=zg(n),p=_g(n),m=vg(a),h=i.createProgram(),g,_,v=n.glslVersion?`#version `+n.glslVersion+`
`:``;n.isRawShaderMaterial?(g=[`#define SHADER_TYPE `+n.shaderType,`#define SHADER_NAME `+n.shaderName,m].filter(bg).join(`
`),g.length>0&&(g+=`
`),_=[`#define SHADER_TYPE `+n.shaderType,`#define SHADER_NAME `+n.shaderName,m].filter(bg).join(`
`),_.length>0&&(_+=`
`)):(g=[Ag(n),`#define SHADER_TYPE `+n.shaderType,`#define SHADER_NAME `+n.shaderName,m,n.extensionClipCullDistance?`#define USE_CLIP_DISTANCE`:``,n.batching?`#define USE_BATCHING`:``,n.batchingColor?`#define USE_BATCHING_COLOR`:``,n.instancing?`#define USE_INSTANCING`:``,n.instancingColor?`#define USE_INSTANCING_COLOR`:``,n.instancingMorph?`#define USE_INSTANCING_MORPH`:``,n.useFog&&n.fog?`#define USE_FOG`:``,n.useFog&&n.fogExp2?`#define FOG_EXP2`:``,n.map?`#define USE_MAP`:``,n.envMap?`#define USE_ENVMAP`:``,n.envMap?`#define `+u:``,n.lightMap?`#define USE_LIGHTMAP`:``,n.aoMap?`#define USE_AOMAP`:``,n.bumpMap?`#define USE_BUMPMAP`:``,n.normalMap?`#define USE_NORMALMAP`:``,n.normalMapObjectSpace?`#define USE_NORMALMAP_OBJECTSPACE`:``,n.normalMapTangentSpace?`#define USE_NORMALMAP_TANGENTSPACE`:``,n.displacementMap?`#define USE_DISPLACEMENTMAP`:``,n.emissiveMap?`#define USE_EMISSIVEMAP`:``,n.anisotropy?`#define USE_ANISOTROPY`:``,n.anisotropyMap?`#define USE_ANISOTROPYMAP`:``,n.clearcoatMap?`#define USE_CLEARCOATMAP`:``,n.clearcoatRoughnessMap?`#define USE_CLEARCOAT_ROUGHNESSMAP`:``,n.clearcoatNormalMap?`#define USE_CLEARCOAT_NORMALMAP`:``,n.iridescenceMap?`#define USE_IRIDESCENCEMAP`:``,n.iridescenceThicknessMap?`#define USE_IRIDESCENCE_THICKNESSMAP`:``,n.specularMap?`#define USE_SPECULARMAP`:``,n.specularColorMap?`#define USE_SPECULAR_COLORMAP`:``,n.specularIntensityMap?`#define USE_SPECULAR_INTENSITYMAP`:``,n.roughnessMap?`#define USE_ROUGHNESSMAP`:``,n.metalnessMap?`#define USE_METALNESSMAP`:``,n.alphaMap?`#define USE_ALPHAMAP`:``,n.alphaHash?`#define USE_ALPHAHASH`:``,n.transmission?`#define USE_TRANSMISSION`:``,n.transmissionMap?`#define USE_TRANSMISSIONMAP`:``,n.thicknessMap?`#define USE_THICKNESSMAP`:``,n.sheenColorMap?`#define USE_SHEEN_COLORMAP`:``,n.sheenRoughnessMap?`#define USE_SHEEN_ROUGHNESSMAP`:``,n.mapUv?`#define MAP_UV `+n.mapUv:``,n.alphaMapUv?`#define ALPHAMAP_UV `+n.alphaMapUv:``,n.lightMapUv?`#define LIGHTMAP_UV `+n.lightMapUv:``,n.aoMapUv?`#define AOMAP_UV `+n.aoMapUv:``,n.emissiveMapUv?`#define EMISSIVEMAP_UV `+n.emissiveMapUv:``,n.bumpMapUv?`#define BUMPMAP_UV `+n.bumpMapUv:``,n.normalMapUv?`#define NORMALMAP_UV `+n.normalMapUv:``,n.displacementMapUv?`#define DISPLACEMENTMAP_UV `+n.displacementMapUv:``,n.metalnessMapUv?`#define METALNESSMAP_UV `+n.metalnessMapUv:``,n.roughnessMapUv?`#define ROUGHNESSMAP_UV `+n.roughnessMapUv:``,n.anisotropyMapUv?`#define ANISOTROPYMAP_UV `+n.anisotropyMapUv:``,n.clearcoatMapUv?`#define CLEARCOATMAP_UV `+n.clearcoatMapUv:``,n.clearcoatNormalMapUv?`#define CLEARCOAT_NORMALMAP_UV `+n.clearcoatNormalMapUv:``,n.clearcoatRoughnessMapUv?`#define CLEARCOAT_ROUGHNESSMAP_UV `+n.clearcoatRoughnessMapUv:``,n.iridescenceMapUv?`#define IRIDESCENCEMAP_UV `+n.iridescenceMapUv:``,n.iridescenceThicknessMapUv?`#define IRIDESCENCE_THICKNESSMAP_UV `+n.iridescenceThicknessMapUv:``,n.sheenColorMapUv?`#define SHEEN_COLORMAP_UV `+n.sheenColorMapUv:``,n.sheenRoughnessMapUv?`#define SHEEN_ROUGHNESSMAP_UV `+n.sheenRoughnessMapUv:``,n.specularMapUv?`#define SPECULARMAP_UV `+n.specularMapUv:``,n.specularColorMapUv?`#define SPECULAR_COLORMAP_UV `+n.specularColorMapUv:``,n.specularIntensityMapUv?`#define SPECULAR_INTENSITYMAP_UV `+n.specularIntensityMapUv:``,n.transmissionMapUv?`#define TRANSMISSIONMAP_UV `+n.transmissionMapUv:``,n.thicknessMapUv?`#define THICKNESSMAP_UV `+n.thicknessMapUv:``,n.vertexTangents&&n.flatShading===!1?`#define USE_TANGENT`:``,n.vertexNormals?`#define HAS_NORMAL`:``,n.vertexColors?`#define USE_COLOR`:``,n.vertexAlphas?`#define USE_COLOR_ALPHA`:``,n.vertexUv1s?`#define USE_UV1`:``,n.vertexUv2s?`#define USE_UV2`:``,n.vertexUv3s?`#define USE_UV3`:``,n.pointsUvs?`#define USE_POINTS_UV`:``,n.flatShading?`#define FLAT_SHADED`:``,n.skinning?`#define USE_SKINNING`:``,n.morphTargets?`#define USE_MORPHTARGETS`:``,n.morphNormals&&n.flatShading===!1?`#define USE_MORPHNORMALS`:``,n.morphColors?`#define USE_MORPHCOLORS`:``,n.morphTargetsCount>0?`#define MORPHTARGETS_TEXTURE_STRIDE `+n.morphTextureStride:``,n.morphTargetsCount>0?`#define MORPHTARGETS_COUNT `+n.morphTargetsCount:``,n.doubleSided?`#define DOUBLE_SIDED`:``,n.flipSided?`#define FLIP_SIDED`:``,n.shadowMapEnabled?`#define USE_SHADOWMAP`:``,n.shadowMapEnabled?`#define `+c:``,n.sizeAttenuation?`#define USE_SIZEATTENUATION`:``,n.numLightProbes>0?`#define USE_LIGHT_PROBES`:``,n.logarithmicDepthBuffer?`#define USE_LOGARITHMIC_DEPTH_BUFFER`:``,n.reversedDepthBuffer?`#define USE_REVERSED_DEPTH_BUFFER`:``,`uniform mat4 modelMatrix;`,`uniform mat4 modelViewMatrix;`,`uniform mat4 projectionMatrix;`,`uniform mat4 viewMatrix;`,`uniform mat3 normalMatrix;`,`uniform vec3 cameraPosition;`,`uniform bool isOrthographic;`,`#ifdef USE_INSTANCING`,`	attribute mat4 instanceMatrix;`,`#endif`,`#ifdef USE_INSTANCING_COLOR`,`	attribute vec3 instanceColor;`,`#endif`,`#ifdef USE_INSTANCING_MORPH`,`	uniform sampler2D morphTexture;`,`#endif`,`attribute vec3 position;`,`attribute vec3 normal;`,`attribute vec2 uv;`,`#ifdef USE_UV1`,`	attribute vec2 uv1;`,`#endif`,`#ifdef USE_UV2`,`	attribute vec2 uv2;`,`#endif`,`#ifdef USE_UV3`,`	attribute vec2 uv3;`,`#endif`,`#ifdef USE_TANGENT`,`	attribute vec4 tangent;`,`#endif`,`#if defined( USE_COLOR_ALPHA )`,`	attribute vec4 color;`,`#elif defined( USE_COLOR )`,`	attribute vec3 color;`,`#endif`,`#ifdef USE_SKINNING`,`	attribute vec4 skinIndex;`,`	attribute vec4 skinWeight;`,`#endif`,`
`].filter(bg).join(`
`),_=[Ag(n),`#define SHADER_TYPE `+n.shaderType,`#define SHADER_NAME `+n.shaderName,m,n.useFog&&n.fog?`#define USE_FOG`:``,n.useFog&&n.fogExp2?`#define FOG_EXP2`:``,n.alphaToCoverage?`#define ALPHA_TO_COVERAGE`:``,n.map?`#define USE_MAP`:``,n.matcap?`#define USE_MATCAP`:``,n.envMap?`#define USE_ENVMAP`:``,n.envMap?`#define `+l:``,n.envMap?`#define `+u:``,n.envMap?`#define `+d:``,f?`#define CUBEUV_TEXEL_WIDTH `+f.texelWidth:``,f?`#define CUBEUV_TEXEL_HEIGHT `+f.texelHeight:``,f?`#define CUBEUV_MAX_MIP `+f.maxMip+`.0`:``,n.lightMap?`#define USE_LIGHTMAP`:``,n.aoMap?`#define USE_AOMAP`:``,n.bumpMap?`#define USE_BUMPMAP`:``,n.normalMap?`#define USE_NORMALMAP`:``,n.normalMapObjectSpace?`#define USE_NORMALMAP_OBJECTSPACE`:``,n.normalMapTangentSpace?`#define USE_NORMALMAP_TANGENTSPACE`:``,n.packedNormalMap?`#define USE_PACKED_NORMALMAP`:``,n.emissiveMap?`#define USE_EMISSIVEMAP`:``,n.anisotropy?`#define USE_ANISOTROPY`:``,n.anisotropyMap?`#define USE_ANISOTROPYMAP`:``,n.clearcoat?`#define USE_CLEARCOAT`:``,n.clearcoatMap?`#define USE_CLEARCOATMAP`:``,n.clearcoatRoughnessMap?`#define USE_CLEARCOAT_ROUGHNESSMAP`:``,n.clearcoatNormalMap?`#define USE_CLEARCOAT_NORMALMAP`:``,n.dispersion?`#define USE_DISPERSION`:``,n.iridescence?`#define USE_IRIDESCENCE`:``,n.iridescenceMap?`#define USE_IRIDESCENCEMAP`:``,n.iridescenceThicknessMap?`#define USE_IRIDESCENCE_THICKNESSMAP`:``,n.specularMap?`#define USE_SPECULARMAP`:``,n.specularColorMap?`#define USE_SPECULAR_COLORMAP`:``,n.specularIntensityMap?`#define USE_SPECULAR_INTENSITYMAP`:``,n.roughnessMap?`#define USE_ROUGHNESSMAP`:``,n.metalnessMap?`#define USE_METALNESSMAP`:``,n.alphaMap?`#define USE_ALPHAMAP`:``,n.alphaTest?`#define USE_ALPHATEST`:``,n.alphaHash?`#define USE_ALPHAHASH`:``,n.sheen?`#define USE_SHEEN`:``,n.sheenColorMap?`#define USE_SHEEN_COLORMAP`:``,n.sheenRoughnessMap?`#define USE_SHEEN_ROUGHNESSMAP`:``,n.transmission?`#define USE_TRANSMISSION`:``,n.transmissionMap?`#define USE_TRANSMISSIONMAP`:``,n.thicknessMap?`#define USE_THICKNESSMAP`:``,n.vertexTangents&&n.flatShading===!1?`#define USE_TANGENT`:``,n.vertexColors||n.instancingColor?`#define USE_COLOR`:``,n.vertexAlphas||n.batchingColor?`#define USE_COLOR_ALPHA`:``,n.vertexUv1s?`#define USE_UV1`:``,n.vertexUv2s?`#define USE_UV2`:``,n.vertexUv3s?`#define USE_UV3`:``,n.pointsUvs?`#define USE_POINTS_UV`:``,n.gradientMap?`#define USE_GRADIENTMAP`:``,n.flatShading?`#define FLAT_SHADED`:``,n.doubleSided?`#define DOUBLE_SIDED`:``,n.flipSided?`#define FLIP_SIDED`:``,n.shadowMapEnabled?`#define USE_SHADOWMAP`:``,n.shadowMapEnabled?`#define `+c:``,n.premultipliedAlpha?`#define PREMULTIPLIED_ALPHA`:``,n.numLightProbes>0?`#define USE_LIGHT_PROBES`:``,n.numLightProbeGrids>0?`#define USE_LIGHT_PROBES_GRID`:``,n.decodeVideoTexture?`#define DECODE_VIDEO_TEXTURE`:``,n.decodeVideoTextureEmissive?`#define DECODE_VIDEO_TEXTURE_EMISSIVE`:``,n.logarithmicDepthBuffer?`#define USE_LOGARITHMIC_DEPTH_BUFFER`:``,n.reversedDepthBuffer?`#define USE_REVERSED_DEPTH_BUFFER`:``,`uniform mat4 viewMatrix;`,`uniform vec3 cameraPosition;`,`uniform bool isOrthographic;`,n.toneMapping===0?``:`#define TONE_MAPPING`,n.toneMapping===0?``:Q.tonemapping_pars_fragment,n.toneMapping===0?``:mg(`toneMapping`,n.toneMapping),n.dithering?`#define DITHERING`:``,n.opaque?`#define OPAQUE`:``,Q.colorspace_pars_fragment,fg(`linearToOutputTexel`,n.outputColorSpace),gg(),n.useDepthPacking?`#define DEPTH_PACKING `+n.depthPacking:``,`
`].filter(bg).join(`
`)),o=wg(o),o=xg(o,n),o=Sg(o,n),s=wg(s),s=xg(s,n),s=Sg(s,n),o=Og(o),s=Og(s),n.isRawShaderMaterial!==!0&&(v=`#version 300 es
`,g=[p,`#define attribute in`,`#define varying out`,`#define texture2D texture`].join(`
`)+`
`+g,_=[`#define varying in`,n.glslVersion===`300 es`?``:`layout(location = 0) out highp vec4 pc_fragColor;`,n.glslVersion===`300 es`?``:`#define gl_FragColor pc_fragColor`,`#define gl_FragDepthEXT gl_FragDepth`,`#define texture2D texture`,`#define textureCube texture`,`#define texture2DProj textureProj`,`#define texture2DLodEXT textureLod`,`#define texture2DProjLodEXT textureProjLod`,`#define textureCubeLodEXT textureLod`,`#define texture2DGradEXT textureGrad`,`#define texture2DProjGradEXT textureProjGrad`,`#define textureCubeGradEXT textureGrad`].join(`
`)+`
`+_);let y=v+g+o,b=v+_+s,x=ag(i,i.VERTEX_SHADER,y),S=ag(i,i.FRAGMENT_SHADER,b);i.attachShader(h,x),i.attachShader(h,S),n.index0AttributeName===void 0?n.hasPositionAttribute===!0&&i.bindAttribLocation(h,0,`position`):i.bindAttribLocation(h,0,n.index0AttributeName),i.linkProgram(h);function C(t){if(e.debug.checkShaderErrors){let n=i.getProgramInfoLog(h)||``,r=i.getShaderInfoLog(x)||``,a=i.getShaderInfoLog(S)||``,o=n.trim(),s=r.trim(),c=a.trim(),l=!0,u=!0;if(i.getProgramParameter(h,i.LINK_STATUS)===!1)if(l=!1,typeof e.debug.onShaderError==`function`)e.debug.onShaderError(i,h,x,S);else{let e=dg(i,x,`vertex`),n=dg(i,S,`fragment`);na(`WebGLProgram: Shader Error `+i.getError()+` - VALIDATE_STATUS `+i.getProgramParameter(h,i.VALIDATE_STATUS)+`

Material Name: `+t.name+`
Material Type: `+t.type+`

Program Info Log: `+o+`
`+e+`
`+n)}else o===``?(s===``||c===``)&&(u=!1):P(`WebGLProgram: Program Info Log:`,o);u&&(t.diagnostics={runnable:l,programLog:o,vertexShader:{log:s,prefix:g},fragmentShader:{log:c,prefix:_}})}i.deleteShader(x),i.deleteShader(S),w=new ig(i,h),T=yg(i,h)}let w;this.getUniforms=function(){return w===void 0&&C(this),w};let T;this.getAttributes=function(){return T===void 0&&C(this),T};let E=n.rendererExtensionParallelShaderCompile===!1;return this.isReady=function(){return E===!1&&(E=i.getProgramParameter(h,og)),E},this.destroy=function(){r.releaseStatesOfProgram(this),i.deleteProgram(h),this.program=void 0},this.type=n.shaderType,this.name=n.shaderName,this.id=sg++,this.cacheKey=t,this.usedTimes=1,this.program=h,this.vertexShader=x,this.fragmentShader=S,this}var Vg=0,Hg=class{constructor(){this.shaderCache=new Map,this.materialCache=new Map}update(e,t,n){let r=this._getShaderCacheForMaterial(e);return r.has(t)===!1&&(r.add(t),t.usedTimes++),r.has(n)===!1&&(r.add(n),n.usedTimes++),this}remove(e){let t=this.materialCache.get(e);for(let e of t)e.usedTimes--,e.usedTimes===0&&this.shaderCache.delete(e.code);return this.materialCache.delete(e),this}getVertexShaderStage(e){return this._getShaderStage(e.vertexShader)}getFragmentShaderStage(e){return this._getShaderStage(e.fragmentShader)}dispose(){this.shaderCache.clear(),this.materialCache.clear()}_getShaderCacheForMaterial(e){let t=this.materialCache,n=t.get(e);return n===void 0&&(n=new Set,t.set(e,n)),n}_getShaderStage(e){let t=this.shaderCache,n=t.get(e);return n===void 0&&(n=new Ug(e),t.set(e,n)),n}},Ug=class{constructor(e){this.id=Vg++,this.code=e,this.usedTimes=0}};function Wg(e){return e===1030||e===37490||e===36285}function Gg(e,t,n,r,i,a){let o=new ne,s=new Hg,c=new Set,l=[],u=new Map,d=r.logarithmicDepthBuffer,f=r.precision,p={MeshDepthMaterial:`depth`,MeshDistanceMaterial:`distance`,MeshNormalMaterial:`normal`,MeshBasicMaterial:`basic`,MeshLambertMaterial:`lambert`,MeshPhongMaterial:`phong`,MeshToonMaterial:`toon`,MeshStandardMaterial:`physical`,MeshPhysicalMaterial:`physical`,MeshMatcapMaterial:`matcap`,LineBasicMaterial:`basic`,LineDashedMaterial:`dashed`,PointsMaterial:`points`,ShadowMaterial:`shadow`,SpriteMaterial:`sprite`};function m(e){return c.add(e),e===0?`uv`:`uv${e}`}function h(i,o,l,u,h,g){let _=u.fog,v=h.geometry,y=i.isMeshStandardMaterial||i.isMeshLambertMaterial||i.isMeshPhongMaterial?u.environment:null,b=i.isMeshStandardMaterial||i.isMeshLambertMaterial&&!i.envMap||i.isMeshPhongMaterial&&!i.envMap,x=t.get(i.envMap||y,b),S=x&&x.mapping===306?x.image.height:null,C=p[i.type];i.precision!==null&&(f=r.getMaxPrecision(i.precision),f!==i.precision&&P(`WebGLProgram.getParameters:`,i.precision,`not supported, using`,f,`instead.`));let w=v.morphAttributes.position||v.morphAttributes.normal||v.morphAttributes.color,T=w===void 0?0:w.length,E=0;v.morphAttributes.position!==void 0&&(E=1),v.morphAttributes.normal!==void 0&&(E=2),v.morphAttributes.color!==void 0&&(E=3);let D,O,k,ee;if(C){let e=pm[C];D=e.vertexShader,O=e.fragmentShader}else{D=i.vertexShader,O=i.fragmentShader;let e=s.getVertexShaderStage(i),t=s.getFragmentShaderStage(i);s.update(i,e,t),k=e.id,ee=t.id}let A=e.getRenderTarget(),te=e.state.buffers.depth.getReversed(),j=h.isInstancedMesh===!0,M=h.isBatchedMesh===!0,N=!!i.map,ne=!!i.matcap,re=!!x,ie=!!i.aoMap,ae=!!i.lightMap,oe=!!i.bumpMap&&i.wireframe===!1,F=!!i.normalMap,I=!!i.displacementMap,L=!!i.emissiveMap,R=!!i.metalnessMap,se=!!i.roughnessMap,B=i.anisotropy>0,ce=i.clearcoat>0,le=i.dispersion>0,ue=i.iridescence>0,de=i.sheen>0,fe=i.transmission>0,pe=B&&!!i.anisotropyMap,V=ce&&!!i.clearcoatMap,H=ce&&!!i.clearcoatNormalMap,me=ce&&!!i.clearcoatRoughnessMap,he=ue&&!!i.iridescenceMap,ge=ue&&!!i.iridescenceThicknessMap,_e=de&&!!i.sheenColorMap,ve=de&&!!i.sheenRoughnessMap,ye=!!i.specularMap,U=!!i.specularColorMap,be=!!i.specularIntensityMap,xe=fe&&!!i.transmissionMap,Se=fe&&!!i.thicknessMap,W=!!i.gradientMap,Ce=!!i.alphaMap,G=i.alphaTest>0,K=!!i.alphaHash,we=!!i.extensions,Te=0;i.toneMapped&&(A===null||A.isXRRenderTarget===!0)&&(Te=e.toneMapping);let Ee={shaderID:C,shaderType:i.type,shaderName:i.name,vertexShader:D,fragmentShader:O,defines:i.defines,customVertexShaderID:k,customFragmentShaderID:ee,isRawShaderMaterial:i.isRawShaderMaterial===!0,glslVersion:i.glslVersion,precision:f,batching:M,batchingColor:M&&h._colorsTexture!==null,instancing:j,instancingColor:j&&h.instanceColor!==null,instancingMorph:j&&h.morphTexture!==null,outputColorSpace:A===null?e.outputColorSpace:A.isXRRenderTarget===!0?A.texture.colorSpace:z.workingColorSpace,alphaToCoverage:!!i.alphaToCoverage,map:N,matcap:ne,envMap:re,envMapMode:re&&x.mapping,envMapCubeUVHeight:S,aoMap:ie,lightMap:ae,bumpMap:oe,normalMap:F,displacementMap:I,emissiveMap:L,normalMapObjectSpace:F&&i.normalMapType===1,normalMapTangentSpace:F&&i.normalMapType===0,packedNormalMap:F&&i.normalMapType===0&&Wg(i.normalMap.format),metalnessMap:R,roughnessMap:se,anisotropy:B,anisotropyMap:pe,clearcoat:ce,clearcoatMap:V,clearcoatNormalMap:H,clearcoatRoughnessMap:me,dispersion:le,iridescence:ue,iridescenceMap:he,iridescenceThicknessMap:ge,sheen:de,sheenColorMap:_e,sheenRoughnessMap:ve,specularMap:ye,specularColorMap:U,specularIntensityMap:be,transmission:fe,transmissionMap:xe,thicknessMap:Se,gradientMap:W,opaque:i.transparent===!1&&i.blending===1&&i.alphaToCoverage===!1,alphaMap:Ce,alphaTest:G,alphaHash:K,combine:i.combine,mapUv:N&&m(i.map.channel),aoMapUv:ie&&m(i.aoMap.channel),lightMapUv:ae&&m(i.lightMap.channel),bumpMapUv:oe&&m(i.bumpMap.channel),normalMapUv:F&&m(i.normalMap.channel),displacementMapUv:I&&m(i.displacementMap.channel),emissiveMapUv:L&&m(i.emissiveMap.channel),metalnessMapUv:R&&m(i.metalnessMap.channel),roughnessMapUv:se&&m(i.roughnessMap.channel),anisotropyMapUv:pe&&m(i.anisotropyMap.channel),clearcoatMapUv:V&&m(i.clearcoatMap.channel),clearcoatNormalMapUv:H&&m(i.clearcoatNormalMap.channel),clearcoatRoughnessMapUv:me&&m(i.clearcoatRoughnessMap.channel),iridescenceMapUv:he&&m(i.iridescenceMap.channel),iridescenceThicknessMapUv:ge&&m(i.iridescenceThicknessMap.channel),sheenColorMapUv:_e&&m(i.sheenColorMap.channel),sheenRoughnessMapUv:ve&&m(i.sheenRoughnessMap.channel),specularMapUv:ye&&m(i.specularMap.channel),specularColorMapUv:U&&m(i.specularColorMap.channel),specularIntensityMapUv:be&&m(i.specularIntensityMap.channel),transmissionMapUv:xe&&m(i.transmissionMap.channel),thicknessMapUv:Se&&m(i.thicknessMap.channel),alphaMapUv:Ce&&m(i.alphaMap.channel),vertexTangents:!!v.attributes.tangent&&(F||B),vertexNormals:!!v.attributes.normal,vertexColors:i.vertexColors,vertexAlphas:i.vertexColors===!0&&!!v.attributes.color&&v.attributes.color.itemSize===4,pointsUvs:h.isPoints===!0&&!!v.attributes.uv&&(N||Ce),fog:!!_,useFog:i.fog===!0,fogExp2:!!_&&_.isFogExp2,flatShading:i.wireframe===!1&&(i.flatShading===!0||v.attributes.normal===void 0&&F===!1&&(i.isMeshLambertMaterial||i.isMeshPhongMaterial||i.isMeshStandardMaterial||i.isMeshPhysicalMaterial)),sizeAttenuation:i.sizeAttenuation===!0,logarithmicDepthBuffer:d,reversedDepthBuffer:te,skinning:h.isSkinnedMesh===!0,hasPositionAttribute:v.attributes.position!==void 0,morphTargets:v.morphAttributes.position!==void 0,morphNormals:v.morphAttributes.normal!==void 0,morphColors:v.morphAttributes.color!==void 0,morphTargetsCount:T,morphTextureStride:E,numDirLights:o.directional.length,numPointLights:o.point.length,numSpotLights:o.spot.length,numSpotLightMaps:o.spotLightMap.length,numRectAreaLights:o.rectArea.length,numHemiLights:o.hemi.length,numDirLightShadows:o.directionalShadowMap.length,numPointLightShadows:o.pointShadowMap.length,numSpotLightShadows:o.spotShadowMap.length,numSpotLightShadowsWithMaps:o.numSpotLightShadowsWithMaps,numLightProbes:o.numLightProbes,numLightProbeGrids:g.length,numClippingPlanes:a.numPlanes,numClipIntersection:a.numIntersection,dithering:i.dithering,shadowMapEnabled:e.shadowMap.enabled&&l.length>0,shadowMapType:e.shadowMap.type,toneMapping:Te,decodeVideoTexture:N&&i.map.isVideoTexture===!0&&z.getTransfer(i.map.colorSpace)===`srgb`,decodeVideoTextureEmissive:L&&i.emissiveMap.isVideoTexture===!0&&z.getTransfer(i.emissiveMap.colorSpace)===`srgb`,premultipliedAlpha:i.premultipliedAlpha,doubleSided:i.side===2,flipSided:i.side===1,useDepthPacking:i.depthPacking>=0,depthPacking:i.depthPacking||0,index0AttributeName:i.index0AttributeName,extensionClipCullDistance:we&&i.extensions.clipCullDistance===!0&&n.has(`WEBGL_clip_cull_distance`),extensionMultiDraw:(we&&i.extensions.multiDraw===!0||M)&&n.has(`WEBGL_multi_draw`),rendererExtensionParallelShaderCompile:n.has(`KHR_parallel_shader_compile`),customProgramCacheKey:i.customProgramCacheKey()};return Ee.vertexUv1s=c.has(1),Ee.vertexUv2s=c.has(2),Ee.vertexUv3s=c.has(3),c.clear(),Ee}function g(t){let n=[];if(t.shaderID?n.push(t.shaderID):(n.push(t.customVertexShaderID),n.push(t.customFragmentShaderID)),t.defines!==void 0)for(let e in t.defines)n.push(e),n.push(t.defines[e]);return t.isRawShaderMaterial===!1&&(_(n,t),v(n,t),n.push(e.outputColorSpace)),n.push(t.customProgramCacheKey),n.join()}function _(e,t){e.push(t.precision),e.push(t.outputColorSpace),e.push(t.envMapMode),e.push(t.envMapCubeUVHeight),e.push(t.mapUv),e.push(t.alphaMapUv),e.push(t.lightMapUv),e.push(t.aoMapUv),e.push(t.bumpMapUv),e.push(t.normalMapUv),e.push(t.displacementMapUv),e.push(t.emissiveMapUv),e.push(t.metalnessMapUv),e.push(t.roughnessMapUv),e.push(t.anisotropyMapUv),e.push(t.clearcoatMapUv),e.push(t.clearcoatNormalMapUv),e.push(t.clearcoatRoughnessMapUv),e.push(t.iridescenceMapUv),e.push(t.iridescenceThicknessMapUv),e.push(t.sheenColorMapUv),e.push(t.sheenRoughnessMapUv),e.push(t.specularMapUv),e.push(t.specularColorMapUv),e.push(t.specularIntensityMapUv),e.push(t.transmissionMapUv),e.push(t.thicknessMapUv),e.push(t.combine),e.push(t.fogExp2),e.push(t.sizeAttenuation),e.push(t.morphTargetsCount),e.push(t.morphAttributeCount),e.push(t.numDirLights),e.push(t.numPointLights),e.push(t.numSpotLights),e.push(t.numSpotLightMaps),e.push(t.numHemiLights),e.push(t.numRectAreaLights),e.push(t.numDirLightShadows),e.push(t.numPointLightShadows),e.push(t.numSpotLightShadows),e.push(t.numSpotLightShadowsWithMaps),e.push(t.numLightProbes),e.push(t.shadowMapType),e.push(t.toneMapping),e.push(t.numClippingPlanes),e.push(t.numClipIntersection),e.push(t.depthPacking)}function v(e,t){o.disableAll(),t.instancing&&o.enable(0),t.instancingColor&&o.enable(1),t.instancingMorph&&o.enable(2),t.matcap&&o.enable(3),t.envMap&&o.enable(4),t.normalMapObjectSpace&&o.enable(5),t.normalMapTangentSpace&&o.enable(6),t.clearcoat&&o.enable(7),t.iridescence&&o.enable(8),t.alphaTest&&o.enable(9),t.vertexColors&&o.enable(10),t.vertexAlphas&&o.enable(11),t.vertexUv1s&&o.enable(12),t.vertexUv2s&&o.enable(13),t.vertexUv3s&&o.enable(14),t.vertexTangents&&o.enable(15),t.anisotropy&&o.enable(16),t.alphaHash&&o.enable(17),t.batching&&o.enable(18),t.dispersion&&o.enable(19),t.batchingColor&&o.enable(20),t.gradientMap&&o.enable(21),t.packedNormalMap&&o.enable(22),t.vertexNormals&&o.enable(23),e.push(o.mask),o.disableAll(),t.fog&&o.enable(0),t.useFog&&o.enable(1),t.flatShading&&o.enable(2),t.logarithmicDepthBuffer&&o.enable(3),t.reversedDepthBuffer&&o.enable(4),t.skinning&&o.enable(5),t.morphTargets&&o.enable(6),t.morphNormals&&o.enable(7),t.morphColors&&o.enable(8),t.premultipliedAlpha&&o.enable(9),t.shadowMapEnabled&&o.enable(10),t.doubleSided&&o.enable(11),t.flipSided&&o.enable(12),t.useDepthPacking&&o.enable(13),t.dithering&&o.enable(14),t.transmission&&o.enable(15),t.sheen&&o.enable(16),t.opaque&&o.enable(17),t.pointsUvs&&o.enable(18),t.decodeVideoTexture&&o.enable(19),t.decodeVideoTextureEmissive&&o.enable(20),t.alphaToCoverage&&o.enable(21),t.numLightProbeGrids>0&&o.enable(22),t.hasPositionAttribute&&o.enable(23),e.push(o.mask)}function y(e){let t=p[e.type],n;if(t){let e=pm[t];n=Ht.clone(e.uniforms)}else n=e.uniforms;return n}function b(t,n){let r=u.get(n);return r===void 0?(r=new Bg(e,n,t,i),l.push(r),u.set(n,r)):++r.usedTimes,r}function x(e){if(--e.usedTimes===0){let t=l.indexOf(e);l[t]=l[l.length-1],l.pop(),u.delete(e.cacheKey),e.destroy()}}function S(e){s.remove(e)}function C(){s.dispose()}return{getParameters:h,getProgramCacheKey:g,getUniforms:y,acquireProgram:b,releaseProgram:x,releaseShaderCache:S,programs:l,dispose:C}}function Kg(){let e=new WeakMap;function t(t){return e.has(t)}function n(t){let n=e.get(t);return n===void 0&&(n={},e.set(t,n)),n}function r(t){e.delete(t)}function i(t,n,r){e.get(t)[n]=r}function a(){e=new WeakMap}return{has:t,get:n,remove:r,update:i,dispose:a}}function qg(e,t){return e.groupOrder===t.groupOrder?e.renderOrder===t.renderOrder?e.material.id===t.material.id?e.materialVariant===t.materialVariant?e.z===t.z?e.id-t.id:e.z-t.z:e.materialVariant-t.materialVariant:e.material.id-t.material.id:e.renderOrder-t.renderOrder:e.groupOrder-t.groupOrder}function Jg(e,t){return e.groupOrder===t.groupOrder?e.renderOrder===t.renderOrder?e.z===t.z?e.id-t.id:t.z-e.z:e.renderOrder-t.renderOrder:e.groupOrder-t.groupOrder}function Yg(){let e=[],t=0,n=[],r=[],i=[];function a(){t=0,n.length=0,r.length=0,i.length=0}function o(e){let t=0;return e.isInstancedMesh&&(t+=2),e.isSkinnedMesh&&(t+=1),t}function s(n,r,i,a,s,c){let l=e[t];return l===void 0?(l={id:n.id,object:n,geometry:r,material:i,materialVariant:o(n),groupOrder:a,renderOrder:n.renderOrder,z:s,group:c},e[t]=l):(l.id=n.id,l.object=n,l.geometry=r,l.material=i,l.materialVariant=o(n),l.groupOrder=a,l.renderOrder=n.renderOrder,l.z=s,l.group=c),t++,l}function c(e,t,a,o,c,l){let u=s(e,t,a,o,c,l);a.transmission>0?r.push(u):a.transparent===!0?i.push(u):n.push(u)}function l(e,t,a,o,c,l){let u=s(e,t,a,o,c,l);a.transmission>0?r.unshift(u):a.transparent===!0?i.unshift(u):n.unshift(u)}function u(e,t,a){n.length>1&&n.sort(e||qg),r.length>1&&r.sort(t||Jg),i.length>1&&i.sort(t||Jg),a&&(n.reverse(),r.reverse(),i.reverse())}function d(){for(let n=t,r=e.length;n<r;n++){let t=e[n];if(t.id===null)break;t.id=null,t.object=null,t.geometry=null,t.material=null,t.group=null}}return{opaque:n,transmissive:r,transparent:i,init:a,push:c,unshift:l,finish:d,sort:u}}function Xg(){let e=new WeakMap;function t(t,n){let r=e.get(t),i;return r===void 0?(i=new Yg,e.set(t,[i])):n>=r.length?(i=new Yg,r.push(i)):i=r[n],i}function n(){e=new WeakMap}return{get:t,dispose:n}}function Zg(){let e={};return{get:function(t){if(e[t.id]!==void 0)return e[t.id];let n;switch(t.type){case`DirectionalLight`:n={direction:new Y,color:new kt};break;case`SpotLight`:n={position:new Y,direction:new Y,color:new kt,distance:0,coneCos:0,penumbraCos:0,decay:0};break;case`PointLight`:n={position:new Y,color:new kt,distance:0,decay:0};break;case`HemisphereLight`:n={direction:new Y,skyColor:new kt,groundColor:new kt};break;case`RectAreaLight`:n={color:new kt,position:new Y,halfWidth:new Y,halfHeight:new Y};break}return e[t.id]=n,n}}}function Qg(){let e={};return{get:function(t){if(e[t.id]!==void 0)return e[t.id];let r;switch(t.type){case`DirectionalLight`:r={shadowIntensity:1,shadowBias:0,shadowNormalBias:0,shadowRadius:1,shadowMapSize:new n};break;case`SpotLight`:r={shadowIntensity:1,shadowBias:0,shadowNormalBias:0,shadowRadius:1,shadowMapSize:new n};break;case`PointLight`:r={shadowIntensity:1,shadowBias:0,shadowNormalBias:0,shadowRadius:1,shadowMapSize:new n,shadowCameraNear:1,shadowCameraFar:1e3};break}return e[t.id]=r,r}}}var $g=0;function e_(e,t){return(t.castShadow?2:0)-(e.castShadow?2:0)+ +!!t.map-!!e.map}function t_(e){let t=new Zg,n=Qg(),r={version:0,hash:{directionalLength:-1,pointLength:-1,spotLength:-1,rectAreaLength:-1,hemiLength:-1,numDirectionalShadows:-1,numPointShadows:-1,numSpotShadows:-1,numSpotMaps:-1,numLightProbes:-1},ambient:[0,0,0],probe:[],directional:[],directionalShadow:[],directionalShadowMap:[],directionalShadowMatrix:[],spot:[],spotLightMap:[],spotShadow:[],spotShadowMap:[],spotLightMatrix:[],rectArea:[],rectAreaLTC1:null,rectAreaLTC2:null,point:[],pointShadow:[],pointShadowMap:[],pointShadowMatrix:[],hemi:[],numSpotLightShadowsWithMaps:0,numLightProbes:0};for(let e=0;e<9;e++)r.probe.push(new Y);let i=new Y,a=new ki,o=new ki;function s(i){let a=0,o=0,s=0;for(let e=0;e<9;e++)r.probe[e].set(0,0,0);let c=0,l=0,u=0,d=0,f=0,p=0,m=0,h=0,g=0,_=0,v=0;i.sort(e_);for(let e=0,y=i.length;e<y;e++){let y=i[e],b=y.color,x=y.intensity,S=y.distance,C=null;if(y.shadow&&y.shadow.map&&(C=y.shadow.map.texture.format===1030?y.shadow.map.texture:y.shadow.map.depthTexture||y.shadow.map.texture),y.isAmbientLight)a+=b.r*x,o+=b.g*x,s+=b.b*x;else if(y.isLightProbe){for(let e=0;e<9;e++)r.probe[e].addScaledVector(y.sh.coefficients[e],x);v++}else if(y.isDirectionalLight){let e=t.get(y);if(e.color.copy(y.color).multiplyScalar(y.intensity),y.castShadow){let e=y.shadow,t=n.get(y);t.shadowIntensity=e.intensity,t.shadowBias=e.bias,t.shadowNormalBias=e.normalBias,t.shadowRadius=e.radius,t.shadowMapSize=e.mapSize,r.directionalShadow[c]=t,r.directionalShadowMap[c]=C,r.directionalShadowMatrix[c]=y.shadow.matrix,p++}r.directional[c]=e,c++}else if(y.isSpotLight){let e=t.get(y);e.position.setFromMatrixPosition(y.matrixWorld),e.color.copy(b).multiplyScalar(x),e.distance=S,e.coneCos=Math.cos(y.angle),e.penumbraCos=Math.cos(y.angle*(1-y.penumbra)),e.decay=y.decay,r.spot[u]=e;let i=y.shadow;if(y.map&&(r.spotLightMap[g]=y.map,g++,i.updateMatrices(y),y.castShadow&&_++),r.spotLightMatrix[u]=i.matrix,y.castShadow){let e=n.get(y);e.shadowIntensity=i.intensity,e.shadowBias=i.bias,e.shadowNormalBias=i.normalBias,e.shadowRadius=i.radius,e.shadowMapSize=i.mapSize,r.spotShadow[u]=e,r.spotShadowMap[u]=C,h++}u++}else if(y.isRectAreaLight){let e=t.get(y);e.color.copy(b).multiplyScalar(x),e.halfWidth.set(y.width*.5,0,0),e.halfHeight.set(0,y.height*.5,0),r.rectArea[d]=e,d++}else if(y.isPointLight){let e=t.get(y);if(e.color.copy(y.color).multiplyScalar(y.intensity),e.distance=y.distance,e.decay=y.decay,y.castShadow){let e=y.shadow,t=n.get(y);t.shadowIntensity=e.intensity,t.shadowBias=e.bias,t.shadowNormalBias=e.normalBias,t.shadowRadius=e.radius,t.shadowMapSize=e.mapSize,t.shadowCameraNear=e.camera.near,t.shadowCameraFar=e.camera.far,r.pointShadow[l]=t,r.pointShadowMap[l]=C,r.pointShadowMatrix[l]=y.shadow.matrix,m++}r.point[l]=e,l++}else if(y.isHemisphereLight){let e=t.get(y);e.skyColor.copy(y.color).multiplyScalar(x),e.groundColor.copy(y.groundColor).multiplyScalar(x),r.hemi[f]=e,f++}}d>0&&(e.has(`OES_texture_float_linear`)===!0?(r.rectAreaLTC1=$.LTC_FLOAT_1,r.rectAreaLTC2=$.LTC_FLOAT_2):(r.rectAreaLTC1=$.LTC_HALF_1,r.rectAreaLTC2=$.LTC_HALF_2)),r.ambient[0]=a,r.ambient[1]=o,r.ambient[2]=s;let y=r.hash;(y.directionalLength!==c||y.pointLength!==l||y.spotLength!==u||y.rectAreaLength!==d||y.hemiLength!==f||y.numDirectionalShadows!==p||y.numPointShadows!==m||y.numSpotShadows!==h||y.numSpotMaps!==g||y.numLightProbes!==v)&&(r.directional.length=c,r.spot.length=u,r.rectArea.length=d,r.point.length=l,r.hemi.length=f,r.directionalShadow.length=p,r.directionalShadowMap.length=p,r.pointShadow.length=m,r.pointShadowMap.length=m,r.spotShadow.length=h,r.spotShadowMap.length=h,r.directionalShadowMatrix.length=p,r.pointShadowMatrix.length=m,r.spotLightMatrix.length=h+g-_,r.spotLightMap.length=g,r.numSpotLightShadowsWithMaps=_,r.numLightProbes=v,y.directionalLength=c,y.pointLength=l,y.spotLength=u,y.rectAreaLength=d,y.hemiLength=f,y.numDirectionalShadows=p,y.numPointShadows=m,y.numSpotShadows=h,y.numSpotMaps=g,y.numLightProbes=v,r.version=$g++)}function c(e,t){let n=0,s=0,c=0,l=0,u=0,d=t.matrixWorldInverse;for(let t=0,f=e.length;t<f;t++){let f=e[t];if(f.isDirectionalLight){let e=r.directional[n];e.direction.setFromMatrixPosition(f.matrixWorld),i.setFromMatrixPosition(f.target.matrixWorld),e.direction.sub(i),e.direction.transformDirection(d),n++}else if(f.isSpotLight){let e=r.spot[c];e.position.setFromMatrixPosition(f.matrixWorld),e.position.applyMatrix4(d),e.direction.setFromMatrixPosition(f.matrixWorld),i.setFromMatrixPosition(f.target.matrixWorld),e.direction.sub(i),e.direction.transformDirection(d),c++}else if(f.isRectAreaLight){let e=r.rectArea[l];e.position.setFromMatrixPosition(f.matrixWorld),e.position.applyMatrix4(d),o.identity(),a.copy(f.matrixWorld),a.premultiply(d),o.extractRotation(a),e.halfWidth.set(f.width*.5,0,0),e.halfHeight.set(0,f.height*.5,0),e.halfWidth.applyMatrix4(o),e.halfHeight.applyMatrix4(o),l++}else if(f.isPointLight){let e=r.point[s];e.position.setFromMatrixPosition(f.matrixWorld),e.position.applyMatrix4(d),s++}else if(f.isHemisphereLight){let e=r.hemi[u];e.direction.setFromMatrixPosition(f.matrixWorld),e.direction.transformDirection(d),u++}}}return{setup:s,setupView:c,state:r}}function n_(e){let t=new t_(e),n=[],r=[],i=[];function a(e){d.camera=e,n.length=0,r.length=0,i.length=0}function o(e){n.push(e)}function s(e){r.push(e)}function c(e){i.push(e)}function l(){t.setup(n)}function u(e){t.setupView(n,e)}let d={lightsArray:n,shadowsArray:r,lightProbeGridArray:i,camera:null,lights:t,transmissionRenderTarget:{},textureUnits:0};return{init:a,state:d,setupLights:l,setupLightsView:u,pushLight:o,pushShadow:s,pushLightProbeGrid:c}}function r_(e){let t=new WeakMap;function n(n,r=0){let i=t.get(n),a;return i===void 0?(a=new n_(e),t.set(n,[a])):r>=i.length?(a=new n_(e),i.push(a)):a=i[r],a}function r(){t=new WeakMap}return{get:n,dispose:r}}var i_=`void main() {
	gl_Position = vec4( position, 1.0 );
}`,a_=`uniform sampler2D shadow_pass;
uniform vec2 resolution;
uniform float radius;
void main() {
	const float samples = float( VSM_SAMPLES );
	float mean = 0.0;
	float squared_mean = 0.0;
	float uvStride = samples <= 1.0 ? 0.0 : 2.0 / ( samples - 1.0 );
	float uvStart = samples <= 1.0 ? 0.0 : - 1.0;
	for ( float i = 0.0; i < samples; i ++ ) {
		float uvOffset = uvStart + i * uvStride;
		#ifdef HORIZONTAL_PASS
			vec2 distribution = texture2D( shadow_pass, ( gl_FragCoord.xy + vec2( uvOffset, 0.0 ) * radius ) / resolution ).rg;
			mean += distribution.x;
			squared_mean += distribution.y * distribution.y + distribution.x * distribution.x;
		#else
			float depth = texture2D( shadow_pass, ( gl_FragCoord.xy + vec2( 0.0, uvOffset ) * radius ) / resolution ).r;
			mean += depth;
			squared_mean += depth * depth;
		#endif
	}
	mean = mean / samples;
	squared_mean = squared_mean / samples;
	float std_dev = sqrt( max( 0.0, squared_mean - mean * mean ) );
	gl_FragColor = vec4( mean, std_dev, 0.0, 1.0 );
}`,o_=[new Y(1,0,0),new Y(-1,0,0),new Y(0,1,0),new Y(0,-1,0),new Y(0,0,1),new Y(0,0,-1)],s_=[new Y(0,-1,0),new Y(0,-1,0),new Y(0,0,1),new Y(0,0,-1),new Y(0,-1,0),new Y(0,-1,0)],c_=new ki,l_=new Y,u_=new Y;function d_(e,t,i){let a=new me,o=new n,c=new n,l=new Hi,u=new li,d=new Ii,f={},p=i.maxTextureSize,m={0:1,1:0,2:2},h=new r({defines:{VSM_SAMPLES:8},uniforms:{shadow_pass:{value:null},resolution:{value:new n},radius:{value:4}},vertexShader:i_,fragmentShader:a_}),g=h.clone();g.defines.HORIZONTAL_PASS=1;let _=new Er;_.setAttribute(`position`,new s(new Float32Array([-1,-1,.5,3,-1,.5,-1,3,.5]),3));let v=new wr(_,h),y=this;this.enabled=!1,this.autoUpdate=!0,this.needsUpdate=!1,this.type=1;let b=this.type;this.render=function(t,n,r){if(y.enabled===!1||y.autoUpdate===!1&&y.needsUpdate===!1||t.length===0)return;this.type===2&&(P(`WebGLShadowMap: PCFSoftShadowMap has been deprecated. Using PCFShadowMap instead.`),this.type=1);let i=e.getRenderTarget(),s=e.getActiveCubeFace(),u=e.getActiveMipmapLevel(),d=e.state;d.setBlending(0),d.buffers.depth.getReversed()===!0?d.buffers.color.setClear(0,0,0,0):d.buffers.color.setClear(1,1,1,1),d.buffers.depth.setTest(!0),d.setScissorTest(!1);let f=b!==this.type;f&&n.traverse(function(e){e.material&&(Array.isArray(e.material)?e.material.forEach(e=>e.needsUpdate=!0):e.material.needsUpdate=!0)});for(let i=0,s=t.length;i<s;i++){let s=t[i],u=s.shadow;if(u===void 0){P(`WebGLShadowMap:`,s,`has no shadow.`);continue}if(u.autoUpdate===!1&&u.needsUpdate===!1)continue;o.copy(u.mapSize);let m=u.getFrameExtents();o.multiply(m),c.copy(u.mapSize),(o.x>p||o.y>p)&&(o.x>p&&(c.x=Math.floor(p/m.x),o.x=c.x*m.x,u.mapSize.x=c.x),o.y>p&&(c.y=Math.floor(p/m.y),o.y=c.y*m.y,u.mapSize.y=c.y));let h=e.state.buffers.depth.getReversed();if(u.camera._reversedDepth=h,u.map===null||f===!0){if(u.map!==null&&(u.map.depthTexture!==null&&(u.map.depthTexture.dispose(),u.map.depthTexture=null),u.map.dispose()),this.type===3){if(s.isPointLight){P(`WebGLShadowMap: VSM shadow maps are not supported for PointLights. Use PCF or BasicShadowMap instead.`);continue}u.map=new Ln(o.x,o.y,{format:Le,type:an,minFilter:Me,magFilter:Me,generateMipmaps:!1}),u.map.texture.name=s.name+`.shadowMap`,u.map.depthTexture=new Mn(o.x,o.y,mt),u.map.depthTexture.name=s.name+`.shadowMapDepth`,u.map.depthTexture.format=ia,u.map.depthTexture.compareFunction=null,u.map.depthTexture.minFilter=ur,u.map.depthTexture.magFilter=ur}else s.isPointLight?(u.map=new Hm(o.x),u.map.depthTexture=new Zn(o.x,en)):(u.map=new Ln(o.x,o.y),u.map.depthTexture=new Mn(o.x,o.y,en)),u.map.depthTexture.name=s.name+`.shadowMap`,u.map.depthTexture.format=ia,this.type===1?(u.map.depthTexture.compareFunction=h?518:515,u.map.depthTexture.minFilter=Me,u.map.depthTexture.magFilter=Me):(u.map.depthTexture.compareFunction=null,u.map.depthTexture.minFilter=ur,u.map.depthTexture.magFilter=ur);u.camera.updateProjectionMatrix()}let g=u.map.isWebGLCubeRenderTarget?6:1;for(let t=0;t<g;t++){if(u.map.isWebGLCubeRenderTarget)e.setRenderTarget(u.map,t),e.clear();else{t===0&&(e.setRenderTarget(u.map),e.clear());let n=u.getViewport(t);l.set(c.x*n.x,c.y*n.y,c.x*n.z,c.y*n.w),d.viewport(l)}if(s.isPointLight){let e=u.camera,n=u.matrix,r=s.distance||e.far;r!==e.far&&(e.far=r,e.updateProjectionMatrix()),l_.setFromMatrixPosition(s.matrixWorld),e.position.copy(l_),u_.copy(e.position),u_.add(o_[t]),e.up.copy(s_[t]),e.lookAt(u_),e.updateMatrixWorld(),n.makeTranslation(-l_.x,-l_.y,-l_.z),c_.multiplyMatrices(e.projectionMatrix,e.matrixWorldInverse),u._frustum.setFromProjectionMatrix(c_,e.coordinateSystem,e.reversedDepth)}else u.updateMatrices(s);a=u.getFrustum(),C(n,r,u.camera,s,this.type)}u.isPointLightShadow!==!0&&this.type===3&&x(u,r),u.needsUpdate=!1}b=this.type,y.needsUpdate=!1,e.setRenderTarget(i,s,u)};function x(n,r){let i=t.update(v);h.defines.VSM_SAMPLES!==n.blurSamples&&(h.defines.VSM_SAMPLES=n.blurSamples,g.defines.VSM_SAMPLES=n.blurSamples,h.needsUpdate=!0,g.needsUpdate=!0),n.mapPass===null&&(n.mapPass=new Ln(o.x,o.y,{format:Le,type:an})),h.uniforms.shadow_pass.value=n.map.depthTexture,h.uniforms.resolution.value=n.mapSize,h.uniforms.radius.value=n.radius,e.setRenderTarget(n.mapPass),e.clear(),e.renderBufferDirect(r,null,i,h,v,null),g.uniforms.shadow_pass.value=n.mapPass.texture,g.uniforms.resolution.value=n.mapSize,g.uniforms.radius.value=n.radius,e.setRenderTarget(n.map),e.clear(),e.renderBufferDirect(r,null,i,g,v,null)}function S(t,n,r,i){let a=null,o=r.isPointLight===!0?t.customDistanceMaterial:t.customDepthMaterial;if(o!==void 0)a=o;else if(a=r.isPointLight===!0?d:u,e.localClippingEnabled&&n.clipShadows===!0&&Array.isArray(n.clippingPlanes)&&n.clippingPlanes.length!==0||n.displacementMap&&n.displacementScale!==0||n.alphaMap&&n.alphaTest>0||n.map&&n.alphaTest>0||n.alphaToCoverage===!0){let e=a.uuid,t=n.uuid,r=f[e];r===void 0&&(r={},f[e]=r);let i=r[t];i===void 0&&(i=a.clone(),r[t]=i,n.addEventListener(`dispose`,w)),a=i}if(a.visible=n.visible,a.wireframe=n.wireframe,i===3?a.side=n.shadowSide===null?n.side:n.shadowSide:a.side=n.shadowSide===null?m[n.side]:n.shadowSide,a.alphaMap=n.alphaMap,a.alphaTest=n.alphaToCoverage===!0?.5:n.alphaTest,a.map=n.map,a.clipShadows=n.clipShadows,a.clippingPlanes=n.clippingPlanes,a.clipIntersection=n.clipIntersection,a.displacementMap=n.displacementMap,a.displacementScale=n.displacementScale,a.displacementBias=n.displacementBias,a.wireframeLinewidth=n.wireframeLinewidth,a.linewidth=n.linewidth,r.isPointLight===!0&&a.isMeshDistanceMaterial===!0){let t=e.properties.get(a);t.light=r}return a}function C(n,r,i,o,s){if(n.visible===!1)return;if(n.layers.test(r.layers)&&(n.isMesh||n.isLine||n.isPoints)&&(n.castShadow||n.receiveShadow&&s===3)&&(!n.frustumCulled||a.intersectsObject(n))){n.modelViewMatrix.multiplyMatrices(i.matrixWorldInverse,n.matrixWorld);let a=t.update(n),c=n.material;if(Array.isArray(c)){let t=a.groups;for(let l=0,u=t.length;l<u;l++){let u=t[l],d=c[u.materialIndex];if(d&&d.visible){let t=S(n,d,o,s);n.onBeforeShadow(e,n,r,i,a,t,u),e.renderBufferDirect(i,null,a,t,n,u),n.onAfterShadow(e,n,r,i,a,t,u)}}}else if(c.visible){let t=S(n,c,o,s);n.onBeforeShadow(e,n,r,i,a,t,null),e.renderBufferDirect(i,null,a,t,n,null),n.onAfterShadow(e,n,r,i,a,t,null)}}let c=n.children;for(let e=0,t=c.length;e<t;e++)C(c[e],r,i,o,s)}function w(e){e.target.removeEventListener(`dispose`,w);for(let t in f){let n=f[t],r=e.target.uuid;r in n&&(n[r].dispose(),delete n[r])}}}function f_(e,t){function n(){let t=!1,n=new Hi,r=null,i=new Hi(0,0,0,0);return{setMask:function(n){r!==n&&!t&&(e.colorMask(n,n,n,n),r=n)},setLocked:function(e){t=e},setClear:function(t,r,a,o,s){s===!0&&(t*=o,r*=o,a*=o),n.set(t,r,a,o),i.equals(n)===!1&&(e.clearColor(t,r,a,o),i.copy(n))},reset:function(){t=!1,r=null,i.set(-1,0,0,0)}}}function r(){let n=!1,r=!1,i=null,a=null,o=null;return{setReversed:function(e){if(r!==e){let n=t.get(`EXT_clip_control`);e?n.clipControlEXT(n.LOWER_LEFT_EXT,n.ZERO_TO_ONE_EXT):n.clipControlEXT(n.LOWER_LEFT_EXT,n.NEGATIVE_ONE_TO_ONE_EXT),r=e;let i=o;o=null,this.setClear(i)}},getReversed:function(){return r},setTest:function(t){t?L(e.DEPTH_TEST):R(e.DEPTH_TEST)},setMask:function(t){i!==t&&!n&&(e.depthMask(t),i=t)},setFunc:function(t){if(r&&(t=Ut[t]),a!==t){switch(t){case 0:e.depthFunc(e.NEVER);break;case 1:e.depthFunc(e.ALWAYS);break;case 2:e.depthFunc(e.LESS);break;case 3:e.depthFunc(e.LEQUAL);break;case 4:e.depthFunc(e.EQUAL);break;case 5:e.depthFunc(e.GEQUAL);break;case 6:e.depthFunc(e.GREATER);break;case 7:e.depthFunc(e.NOTEQUAL);break;default:e.depthFunc(e.LEQUAL)}a=t}},setLocked:function(e){n=e},setClear:function(t){o!==t&&(o=t,r&&(t=1-t),e.clearDepth(t))},reset:function(){n=!1,i=null,a=null,o=null,r=!1}}}function i(){let t=!1,n=null,r=null,i=null,a=null,o=null,s=null,c=null,l=null;return{setTest:function(n){t||(n?L(e.STENCIL_TEST):R(e.STENCIL_TEST))},setMask:function(r){n!==r&&!t&&(e.stencilMask(r),n=r)},setFunc:function(t,n,o){(r!==t||i!==n||a!==o)&&(e.stencilFunc(t,n,o),r=t,i=n,a=o)},setOp:function(t,n,r){(o!==t||s!==n||c!==r)&&(e.stencilOp(t,n,r),o=t,s=n,c=r)},setLocked:function(e){t=e},setClear:function(t){l!==t&&(e.clearStencil(t),l=t)},reset:function(){t=!1,n=null,r=null,i=null,a=null,o=null,s=null,c=null,l=null}}}let a=new n,o=new r,s=new i,c=new WeakMap,l=new WeakMap,u={},d={},f={},p=new WeakMap,m=[],h=null,g=!1,_=null,v=null,y=null,b=null,x=null,S=null,C=null,w=new kt(0,0,0),T=0,E=!1,D=null,O=null,k=null,ee=null,A=null,te=e.getParameter(e.MAX_COMBINED_TEXTURE_IMAGE_UNITS),j=!1,M=0,N=e.getParameter(e.VERSION);N.indexOf(`WebGL`)===-1?N.indexOf(`OpenGL ES`)!==-1&&(M=parseFloat(/^OpenGL ES (\d)/.exec(N)[1]),j=M>=2):(M=parseFloat(/^WebGL (\d)/.exec(N)[1]),j=M>=1);let ne=null,P={},re=e.getParameter(e.SCISSOR_BOX),ie=e.getParameter(e.VIEWPORT),ae=new Hi().fromArray(re),oe=new Hi().fromArray(ie);function F(t,n,r,i){let a=new Uint8Array(4),o=e.createTexture();e.bindTexture(t,o),e.texParameteri(t,e.TEXTURE_MIN_FILTER,e.NEAREST),e.texParameteri(t,e.TEXTURE_MAG_FILTER,e.NEAREST);for(let o=0;o<r;o++)t===e.TEXTURE_3D||t===e.TEXTURE_2D_ARRAY?e.texImage3D(n,0,e.RGBA,1,1,i,0,e.RGBA,e.UNSIGNED_BYTE,a):e.texImage2D(n+o,0,e.RGBA,1,1,0,e.RGBA,e.UNSIGNED_BYTE,a);return o}let I={};I[e.TEXTURE_2D]=F(e.TEXTURE_2D,e.TEXTURE_2D,1),I[e.TEXTURE_CUBE_MAP]=F(e.TEXTURE_CUBE_MAP,e.TEXTURE_CUBE_MAP_POSITIVE_X,6),I[e.TEXTURE_2D_ARRAY]=F(e.TEXTURE_2D_ARRAY,e.TEXTURE_2D_ARRAY,1,1),I[e.TEXTURE_3D]=F(e.TEXTURE_3D,e.TEXTURE_3D,1,1),a.setClear(0,0,0,1),o.setClear(1),s.setClear(0),L(e.DEPTH_TEST),o.setFunc(3),fe(!1),pe(1),L(e.CULL_FACE),ue(0);function L(t){u[t]!==!0&&(e.enable(t),u[t]=!0)}function R(t){u[t]!==!1&&(e.disable(t),u[t]=!1)}function z(t,n){return f[t]===n?!1:(e.bindFramebuffer(t,n),f[t]=n,t===e.DRAW_FRAMEBUFFER&&(f[e.FRAMEBUFFER]=n),t===e.FRAMEBUFFER&&(f[e.DRAW_FRAMEBUFFER]=n),!0)}function se(t,n){let r=m,i=!1;if(t){r=p.get(n),r===void 0&&(r=[],p.set(n,r));let a=t.textures;if(r.length!==a.length||r[0]!==e.COLOR_ATTACHMENT0){for(let t=0,n=a.length;t<n;t++)r[t]=e.COLOR_ATTACHMENT0+t;r.length=a.length,i=!0}}else r[0]!==e.BACK&&(r[0]=e.BACK,i=!0);i&&e.drawBuffers(r)}function B(t){return h===t?!1:(e.useProgram(t),h=t,!0)}let ce={100:e.FUNC_ADD,101:e.FUNC_SUBTRACT,102:e.FUNC_REVERSE_SUBTRACT};ce[103]=e.MIN,ce[104]=e.MAX;let le={200:e.ZERO,201:e.ONE,202:e.SRC_COLOR,204:e.SRC_ALPHA,210:e.SRC_ALPHA_SATURATE,208:e.DST_COLOR,206:e.DST_ALPHA,203:e.ONE_MINUS_SRC_COLOR,205:e.ONE_MINUS_SRC_ALPHA,209:e.ONE_MINUS_DST_COLOR,207:e.ONE_MINUS_DST_ALPHA,211:e.CONSTANT_COLOR,212:e.ONE_MINUS_CONSTANT_COLOR,213:e.CONSTANT_ALPHA,214:e.ONE_MINUS_CONSTANT_ALPHA};function ue(t,n,r,i,a,o,s,c,l,u){if(t===0){g===!0&&(R(e.BLEND),g=!1);return}if(g===!1&&(L(e.BLEND),g=!0),t!==5){if(t!==_||u!==E){if((v!==100||x!==100)&&(e.blendEquation(e.FUNC_ADD),v=100,x=100),u)switch(t){case 1:e.blendFuncSeparate(e.ONE,e.ONE_MINUS_SRC_ALPHA,e.ONE,e.ONE_MINUS_SRC_ALPHA);break;case 2:e.blendFunc(e.ONE,e.ONE);break;case 3:e.blendFuncSeparate(e.ZERO,e.ONE_MINUS_SRC_COLOR,e.ZERO,e.ONE);break;case 4:e.blendFuncSeparate(e.DST_COLOR,e.ONE_MINUS_SRC_ALPHA,e.ZERO,e.ONE);break;default:na(`WebGLState: Invalid blending: `,t);break}else switch(t){case 1:e.blendFuncSeparate(e.SRC_ALPHA,e.ONE_MINUS_SRC_ALPHA,e.ONE,e.ONE_MINUS_SRC_ALPHA);break;case 2:e.blendFuncSeparate(e.SRC_ALPHA,e.ONE,e.ONE,e.ONE);break;case 3:na(`WebGLState: SubtractiveBlending requires material.premultipliedAlpha = true`);break;case 4:na(`WebGLState: MultiplyBlending requires material.premultipliedAlpha = true`);break;default:na(`WebGLState: Invalid blending: `,t);break}y=null,b=null,S=null,C=null,w.set(0,0,0),T=0,_=t,E=u}return}a||=n,o||=r,s||=i,(n!==v||a!==x)&&(e.blendEquationSeparate(ce[n],ce[a]),v=n,x=a),(r!==y||i!==b||o!==S||s!==C)&&(e.blendFuncSeparate(le[r],le[i],le[o],le[s]),y=r,b=i,S=o,C=s),(c.equals(w)===!1||l!==T)&&(e.blendColor(c.r,c.g,c.b,l),w.copy(c),T=l),_=t,E=!1}function de(t,n){t.side===2?R(e.CULL_FACE):L(e.CULL_FACE);let r=t.side===1;n&&(r=!r),fe(r),t.blending===1&&t.transparent===!1?ue(0):ue(t.blending,t.blendEquation,t.blendSrc,t.blendDst,t.blendEquationAlpha,t.blendSrcAlpha,t.blendDstAlpha,t.blendColor,t.blendAlpha,t.premultipliedAlpha),o.setFunc(t.depthFunc),o.setTest(t.depthTest),o.setMask(t.depthWrite),a.setMask(t.colorWrite);let i=t.stencilWrite;s.setTest(i),i&&(s.setMask(t.stencilWriteMask),s.setFunc(t.stencilFunc,t.stencilRef,t.stencilFuncMask),s.setOp(t.stencilFail,t.stencilZFail,t.stencilZPass)),H(t.polygonOffset,t.polygonOffsetFactor,t.polygonOffsetUnits),t.alphaToCoverage===!0?L(e.SAMPLE_ALPHA_TO_COVERAGE):R(e.SAMPLE_ALPHA_TO_COVERAGE)}function fe(t){D!==t&&(t?e.frontFace(e.CW):e.frontFace(e.CCW),D=t)}function pe(t){t===0?R(e.CULL_FACE):(L(e.CULL_FACE),t!==O&&(t===1?e.cullFace(e.BACK):t===2?e.cullFace(e.FRONT):e.cullFace(e.FRONT_AND_BACK))),O=t}function V(t){t!==k&&(j&&e.lineWidth(t),k=t)}function H(t,n,r){t?(L(e.POLYGON_OFFSET_FILL),(ee!==n||A!==r)&&(ee=n,A=r,o.getReversed()&&(n=-n),e.polygonOffset(n,r))):R(e.POLYGON_OFFSET_FILL)}function me(t){t?L(e.SCISSOR_TEST):R(e.SCISSOR_TEST)}function he(t){t===void 0&&(t=e.TEXTURE0+te-1),ne!==t&&(e.activeTexture(t),ne=t)}function ge(t,n,r){r===void 0&&(r=ne===null?e.TEXTURE0+te-1:ne);let i=P[r];i===void 0&&(i={type:void 0,texture:void 0},P[r]=i),(i.type!==t||i.texture!==n)&&(ne!==r&&(e.activeTexture(r),ne=r),e.bindTexture(t,n||I[t]),i.type=t,i.texture=n)}function _e(){let t=P[ne];t!==void 0&&t.type!==void 0&&(e.bindTexture(t.type,null),t.type=void 0,t.texture=void 0)}function ve(){try{e.compressedTexImage2D(...arguments)}catch(e){na(`WebGLState:`,e)}}function ye(){try{e.compressedTexImage3D(...arguments)}catch(e){na(`WebGLState:`,e)}}function U(){try{e.texSubImage2D(...arguments)}catch(e){na(`WebGLState:`,e)}}function be(){try{e.texSubImage3D(...arguments)}catch(e){na(`WebGLState:`,e)}}function xe(){try{e.compressedTexSubImage2D(...arguments)}catch(e){na(`WebGLState:`,e)}}function Se(){try{e.compressedTexSubImage3D(...arguments)}catch(e){na(`WebGLState:`,e)}}function W(){try{e.texStorage2D(...arguments)}catch(e){na(`WebGLState:`,e)}}function Ce(){try{e.texStorage3D(...arguments)}catch(e){na(`WebGLState:`,e)}}function G(){try{e.texImage2D(...arguments)}catch(e){na(`WebGLState:`,e)}}function K(){try{e.texImage3D(...arguments)}catch(e){na(`WebGLState:`,e)}}function we(t){return d[t]===void 0?e.getParameter(t):d[t]}function Te(t,n){d[t]!==n&&(e.pixelStorei(t,n),d[t]=n)}function Ee(t){ae.equals(t)===!1&&(e.scissor(t.x,t.y,t.z,t.w),ae.copy(t))}function De(t){oe.equals(t)===!1&&(e.viewport(t.x,t.y,t.z,t.w),oe.copy(t))}function Oe(t,n){let r=l.get(n);r===void 0&&(r=new WeakMap,l.set(n,r));let i=r.get(t);i===void 0&&(i=e.getUniformBlockIndex(n,t.name),r.set(t,i))}function ke(t,n){let r=l.get(n).get(t);c.get(n)!==r&&(e.uniformBlockBinding(n,r,t.__bindingPointIndex),c.set(n,r))}function Ae(){e.disable(e.BLEND),e.disable(e.CULL_FACE),e.disable(e.DEPTH_TEST),e.disable(e.POLYGON_OFFSET_FILL),e.disable(e.SCISSOR_TEST),e.disable(e.STENCIL_TEST),e.disable(e.SAMPLE_ALPHA_TO_COVERAGE),e.blendEquation(e.FUNC_ADD),e.blendFunc(e.ONE,e.ZERO),e.blendFuncSeparate(e.ONE,e.ZERO,e.ONE,e.ZERO),e.blendColor(0,0,0,0),e.colorMask(!0,!0,!0,!0),e.clearColor(0,0,0,0),e.depthMask(!0),e.depthFunc(e.LESS),o.setReversed(!1),e.clearDepth(1),e.stencilMask(4294967295),e.stencilFunc(e.ALWAYS,0,4294967295),e.stencilOp(e.KEEP,e.KEEP,e.KEEP),e.clearStencil(0),e.cullFace(e.BACK),e.frontFace(e.CCW),e.polygonOffset(0,0),e.activeTexture(e.TEXTURE0),e.bindFramebuffer(e.FRAMEBUFFER,null),e.bindFramebuffer(e.DRAW_FRAMEBUFFER,null),e.bindFramebuffer(e.READ_FRAMEBUFFER,null),e.useProgram(null),e.lineWidth(1),e.scissor(0,0,e.canvas.width,e.canvas.height),e.viewport(0,0,e.canvas.width,e.canvas.height),e.pixelStorei(e.PACK_ALIGNMENT,4),e.pixelStorei(e.UNPACK_ALIGNMENT,4),e.pixelStorei(e.UNPACK_FLIP_Y_WEBGL,!1),e.pixelStorei(e.UNPACK_PREMULTIPLY_ALPHA_WEBGL,!1),e.pixelStorei(e.UNPACK_COLORSPACE_CONVERSION_WEBGL,e.BROWSER_DEFAULT_WEBGL),e.pixelStorei(e.PACK_ROW_LENGTH,0),e.pixelStorei(e.PACK_SKIP_PIXELS,0),e.pixelStorei(e.PACK_SKIP_ROWS,0),e.pixelStorei(e.UNPACK_ROW_LENGTH,0),e.pixelStorei(e.UNPACK_IMAGE_HEIGHT,0),e.pixelStorei(e.UNPACK_SKIP_PIXELS,0),e.pixelStorei(e.UNPACK_SKIP_ROWS,0),e.pixelStorei(e.UNPACK_SKIP_IMAGES,0),u={},d={},ne=null,P={},f={},p=new WeakMap,m=[],h=null,g=!1,_=null,v=null,y=null,b=null,x=null,S=null,C=null,w=new kt(0,0,0),T=0,E=!1,D=null,O=null,k=null,ee=null,A=null,ae.set(0,0,e.canvas.width,e.canvas.height),oe.set(0,0,e.canvas.width,e.canvas.height),a.reset(),o.reset(),s.reset()}return{buffers:{color:a,depth:o,stencil:s},enable:L,disable:R,bindFramebuffer:z,drawBuffers:se,useProgram:B,setBlending:ue,setMaterial:de,setFlipSided:fe,setCullFace:pe,setLineWidth:V,setPolygonOffset:H,setScissorTest:me,activeTexture:he,bindTexture:ge,unbindTexture:_e,compressedTexImage2D:ve,compressedTexImage3D:ye,texImage2D:G,texImage3D:K,pixelStorei:Te,getParameter:we,updateUBOMapping:Oe,uniformBlockBinding:ke,texStorage2D:W,texStorage3D:Ce,texSubImage2D:U,texSubImage3D:be,compressedTexSubImage2D:xe,compressedTexSubImage3D:Se,scissor:Ee,viewport:De,reset:Ae}}function p_(e,t,r,i,a,o,s){let c=t.has(`WEBGL_multisampled_render_to_texture`)?t.get(`WEBGL_multisampled_render_to_texture`):null,l=typeof navigator>`u`?!1:/OculusBrowser/g.test(navigator.userAgent),u=new n,d=new WeakMap,f=new Set,p,m=new WeakMap,h=!1;try{h=typeof OffscreenCanvas<`u`&&new OffscreenCanvas(1,1).getContext(`2d`)!==null}catch{}function g(e,t){return h?new OffscreenCanvas(e,t):gn(`canvas`)}function _(e,t,n){let r=1,i=Se(e);if((i.width>n||i.height>n)&&(r=n/Math.max(i.width,i.height)),r<1)if(typeof HTMLImageElement<`u`&&e instanceof HTMLImageElement||typeof HTMLCanvasElement<`u`&&e instanceof HTMLCanvasElement||typeof ImageBitmap<`u`&&e instanceof ImageBitmap||typeof VideoFrame<`u`&&e instanceof VideoFrame){let n=Math.floor(r*i.width),a=Math.floor(r*i.height);p===void 0&&(p=g(n,a));let o=t?g(n,a):p;return o.width=n,o.height=a,o.getContext(`2d`).drawImage(e,0,0,n,a),P(`WebGLRenderer: Texture has been resized from (`+i.width+`x`+i.height+`) to (`+n+`x`+a+`).`),o}else return`data`in e&&P(`WebGLRenderer: Image in DataTexture is too big (`+i.width+`x`+i.height+`).`),e;return e}function v(e){return e.generateMipmaps}function y(t){e.generateMipmap(t)}function b(t){return t.isWebGLCubeRenderTarget?e.TEXTURE_CUBE_MAP:t.isWebGL3DRenderTarget?e.TEXTURE_3D:t.isWebGLArrayRenderTarget||t.isCompressedArrayTexture?e.TEXTURE_2D_ARRAY:e.TEXTURE_2D}function x(n,r,i,a,o,s=!1){if(n!==null){if(e[n]!==void 0)return e[n];P(`WebGLRenderer: Attempt to use non-existing WebGL internal format '`+n+`'`)}let c;a&&(c=t.get(`EXT_texture_norm16`),c||P(`WebGLRenderer: Unable to use normalized textures without EXT_texture_norm16 extension`));let l=r;if(r===e.RED&&(i===e.FLOAT&&(l=e.R32F),i===e.HALF_FLOAT&&(l=e.R16F),i===e.UNSIGNED_BYTE&&(l=e.R8),i===e.UNSIGNED_SHORT&&c&&(l=c.R16_EXT),i===e.SHORT&&c&&(l=c.R16_SNORM_EXT)),r===e.RED_INTEGER&&(i===e.UNSIGNED_BYTE&&(l=e.R8UI),i===e.UNSIGNED_SHORT&&(l=e.R16UI),i===e.UNSIGNED_INT&&(l=e.R32UI),i===e.BYTE&&(l=e.R8I),i===e.SHORT&&(l=e.R16I),i===e.INT&&(l=e.R32I)),r===e.RG&&(i===e.FLOAT&&(l=e.RG32F),i===e.HALF_FLOAT&&(l=e.RG16F),i===e.UNSIGNED_BYTE&&(l=e.RG8),i===e.UNSIGNED_SHORT&&c&&(l=c.RG16_EXT),i===e.SHORT&&c&&(l=c.RG16_SNORM_EXT)),r===e.RG_INTEGER&&(i===e.UNSIGNED_BYTE&&(l=e.RG8UI),i===e.UNSIGNED_SHORT&&(l=e.RG16UI),i===e.UNSIGNED_INT&&(l=e.RG32UI),i===e.BYTE&&(l=e.RG8I),i===e.SHORT&&(l=e.RG16I),i===e.INT&&(l=e.RG32I)),r===e.RGB_INTEGER&&(i===e.UNSIGNED_BYTE&&(l=e.RGB8UI),i===e.UNSIGNED_SHORT&&(l=e.RGB16UI),i===e.UNSIGNED_INT&&(l=e.RGB32UI),i===e.BYTE&&(l=e.RGB8I),i===e.SHORT&&(l=e.RGB16I),i===e.INT&&(l=e.RGB32I)),r===e.RGBA_INTEGER&&(i===e.UNSIGNED_BYTE&&(l=e.RGBA8UI),i===e.UNSIGNED_SHORT&&(l=e.RGBA16UI),i===e.UNSIGNED_INT&&(l=e.RGBA32UI),i===e.BYTE&&(l=e.RGBA8I),i===e.SHORT&&(l=e.RGBA16I),i===e.INT&&(l=e.RGBA32I)),r===e.RGB&&(i===e.UNSIGNED_SHORT&&c&&(l=c.RGB16_EXT),i===e.SHORT&&c&&(l=c.RGB16_SNORM_EXT),i===e.UNSIGNED_INT_5_9_9_9_REV&&(l=e.RGB9_E5),i===e.UNSIGNED_INT_10F_11F_11F_REV&&(l=e.R11F_G11F_B10F)),r===e.RGBA){let t=s?Wt:z.getTransfer(o);i===e.FLOAT&&(l=e.RGBA32F),i===e.HALF_FLOAT&&(l=e.RGBA16F),i===e.UNSIGNED_BYTE&&(l=t===`srgb`?e.SRGB8_ALPHA8:e.RGBA8),i===e.UNSIGNED_SHORT&&c&&(l=c.RGBA16_EXT),i===e.SHORT&&c&&(l=c.RGBA16_SNORM_EXT),i===e.UNSIGNED_SHORT_4_4_4_4&&(l=e.RGBA4),i===e.UNSIGNED_SHORT_5_5_5_1&&(l=e.RGB5_A1)}return(l===e.R16F||l===e.R32F||l===e.RG16F||l===e.RG32F||l===e.RGBA16F||l===e.RGBA32F)&&t.get(`EXT_color_buffer_float`),l}function S(t,n){let r;return t?n===null||n===1014||n===1020?r=e.DEPTH24_STENCIL8:n===1015?r=e.DEPTH32F_STENCIL8:n===1012&&(r=e.DEPTH24_STENCIL8,P(`DepthTexture: 16 bit depth attachment is not supported with stencil. Using 24-bit attachment.`)):n===null||n===1014||n===1020?r=e.DEPTH_COMPONENT24:n===1015?r=e.DEPTH_COMPONENT32F:n===1012&&(r=e.DEPTH_COMPONENT16),r}function C(e,t){return v(e)===!0||e.isFramebufferTexture&&e.minFilter!==1003&&e.minFilter!==1006?Math.log2(Math.max(t.width,t.height))+1:e.mipmaps!==void 0&&e.mipmaps.length>0?e.mipmaps.length:e.isCompressedTexture&&Array.isArray(e.image)?t.mipmaps.length:1}function w(e){let t=e.target;t.removeEventListener(`dispose`,w),E(t),t.isVideoTexture&&d.delete(t),t.isHTMLTexture&&f.delete(t)}function T(e){let t=e.target;t.removeEventListener(`dispose`,T),O(t)}function E(e){let t=i.get(e);if(t.__webglInit===void 0)return;let n=e.source,r=m.get(n);if(r){let i=r[t.__cacheKey];i.usedTimes--,i.usedTimes===0&&D(e),Object.keys(r).length===0&&m.delete(n)}i.remove(e)}function D(t){let n=i.get(t);e.deleteTexture(n.__webglTexture);let r=t.source,a=m.get(r);delete a[n.__cacheKey],s.memory.textures--}function O(t){let n=i.get(t);if(t.depthTexture&&(t.depthTexture.dispose(),i.remove(t.depthTexture)),t.isWebGLCubeRenderTarget)for(let t=0;t<6;t++){if(Array.isArray(n.__webglFramebuffer[t]))for(let r=0;r<n.__webglFramebuffer[t].length;r++)e.deleteFramebuffer(n.__webglFramebuffer[t][r]);else e.deleteFramebuffer(n.__webglFramebuffer[t]);n.__webglDepthbuffer&&e.deleteRenderbuffer(n.__webglDepthbuffer[t])}else{if(Array.isArray(n.__webglFramebuffer))for(let t=0;t<n.__webglFramebuffer.length;t++)e.deleteFramebuffer(n.__webglFramebuffer[t]);else e.deleteFramebuffer(n.__webglFramebuffer);if(n.__webglDepthbuffer&&e.deleteRenderbuffer(n.__webglDepthbuffer),n.__webglMultisampledFramebuffer&&e.deleteFramebuffer(n.__webglMultisampledFramebuffer),n.__webglColorRenderbuffer)for(let t=0;t<n.__webglColorRenderbuffer.length;t++)n.__webglColorRenderbuffer[t]&&e.deleteRenderbuffer(n.__webglColorRenderbuffer[t]);n.__webglDepthRenderbuffer&&e.deleteRenderbuffer(n.__webglDepthRenderbuffer)}let r=t.textures;for(let t=0,n=r.length;t<n;t++){let n=i.get(r[t]);n.__webglTexture&&(e.deleteTexture(n.__webglTexture),s.memory.textures--),i.remove(r[t])}i.remove(t)}let k=0;function ee(){k=0}function A(){return k}function te(e){k=e}function j(){let e=k;return e>=a.maxTextures&&P(`WebGLTextures: Trying to use `+e+` texture units while this GPU supports only `+a.maxTextures),k+=1,e}function M(e){let t=[];return t.push(e.wrapS),t.push(e.wrapT),t.push(e.wrapR||0),t.push(e.magFilter),t.push(e.minFilter),t.push(e.anisotropy),t.push(e.internalFormat),t.push(e.format),t.push(e.type),t.push(e.generateMipmaps),t.push(e.premultiplyAlpha),t.push(e.flipY),t.push(e.unpackAlignment),t.push(e.colorSpace),t.join()}function N(t,n){let a=i.get(t);if(t.isVideoTexture&&be(t),t.isRenderTargetTexture===!1&&t.isExternalTexture!==!0&&t.version>0&&a.__version!==t.version){let e=t.image;if(e===null)P(`WebGLRenderer: Texture marked for update but no image data found.`);else if(e.complete===!1)P(`WebGLRenderer: Texture marked for update but image is incomplete`);else{B(a,t,n);return}}else t.isExternalTexture&&(a.__webglTexture=t.sourceTexture?t.sourceTexture:null);r.bindTexture(e.TEXTURE_2D,a.__webglTexture,e.TEXTURE0+n)}function ne(t,n){let a=i.get(t);if(t.isRenderTargetTexture===!1&&t.version>0&&a.__version!==t.version){B(a,t,n);return}else t.isExternalTexture&&(a.__webglTexture=t.sourceTexture?t.sourceTexture:null);r.bindTexture(e.TEXTURE_2D_ARRAY,a.__webglTexture,e.TEXTURE0+n)}function re(t,n){let a=i.get(t);if(t.isRenderTargetTexture===!1&&t.version>0&&a.__version!==t.version){B(a,t,n);return}r.bindTexture(e.TEXTURE_3D,a.__webglTexture,e.TEXTURE0+n)}function ie(t,n){let a=i.get(t);if(t.isCubeDepthTexture!==!0&&t.version>0&&a.__version!==t.version){ce(a,t,n);return}r.bindTexture(e.TEXTURE_CUBE_MAP,a.__webglTexture,e.TEXTURE0+n)}let ae={[pe]:e.REPEAT,[Ft]:e.CLAMP_TO_EDGE,[_r]:e.MIRRORED_REPEAT},oe={[ur]:e.NEAREST,[jn]:e.NEAREST_MIPMAP_NEAREST,[wa]:e.NEAREST_MIPMAP_LINEAR,[Me]:e.LINEAR,[V]:e.LINEAR_MIPMAP_NEAREST,[Rt]:e.LINEAR_MIPMAP_LINEAR},F={512:e.NEVER,519:e.ALWAYS,513:e.LESS,515:e.LEQUAL,514:e.EQUAL,518:e.GEQUAL,516:e.GREATER,517:e.NOTEQUAL};function I(n,r){if(r.type===1015&&t.has(`OES_texture_float_linear`)===!1&&(r.magFilter===1006||r.magFilter===1007||r.magFilter===1005||r.magFilter===1008||r.minFilter===1006||r.minFilter===1007||r.minFilter===1005||r.minFilter===1008)&&P(`WebGLRenderer: Unable to use linear filtering with floating point textures. OES_texture_float_linear not supported on this device.`),e.texParameteri(n,e.TEXTURE_WRAP_S,ae[r.wrapS]),e.texParameteri(n,e.TEXTURE_WRAP_T,ae[r.wrapT]),(n===e.TEXTURE_3D||n===e.TEXTURE_2D_ARRAY)&&e.texParameteri(n,e.TEXTURE_WRAP_R,ae[r.wrapR]),e.texParameteri(n,e.TEXTURE_MAG_FILTER,oe[r.magFilter]),e.texParameteri(n,e.TEXTURE_MIN_FILTER,oe[r.minFilter]),r.compareFunction&&(e.texParameteri(n,e.TEXTURE_COMPARE_MODE,e.COMPARE_REF_TO_TEXTURE),e.texParameteri(n,e.TEXTURE_COMPARE_FUNC,F[r.compareFunction])),t.has(`EXT_texture_filter_anisotropic`)===!0){if(r.magFilter===1003||r.minFilter!==1005&&r.minFilter!==1008||r.type===1015&&t.has(`OES_texture_float_linear`)===!1)return;if(r.anisotropy>1||i.get(r).__currentAnisotropy){let o=t.get(`EXT_texture_filter_anisotropic`);e.texParameterf(n,o.TEXTURE_MAX_ANISOTROPY_EXT,Math.min(r.anisotropy,a.getMaxAnisotropy())),i.get(r).__currentAnisotropy=r.anisotropy}}}function L(t,n){let r=!1;t.__webglInit===void 0&&(t.__webglInit=!0,n.addEventListener(`dispose`,w));let i=n.source,a=m.get(i);a===void 0&&(a={},m.set(i,a));let o=M(n);if(o!==t.__cacheKey){a[o]===void 0&&(a[o]={texture:e.createTexture(),usedTimes:0},s.memory.textures++,r=!0),a[o].usedTimes++;let i=a[t.__cacheKey];i!==void 0&&(a[t.__cacheKey].usedTimes--,i.usedTimes===0&&D(n)),t.__cacheKey=o,t.__webglTexture=a[o].texture}return r}function R(e,t,n){return Math.floor(Math.floor(e/n)/t)}function se(t,n,i,a){let o=t.updateRanges;if(o.length===0)r.texSubImage2D(e.TEXTURE_2D,0,0,0,n.width,n.height,i,a,n.data);else{o.sort((e,t)=>e.start-t.start);let s=0;for(let e=1;e<o.length;e++){let t=o[s],r=o[e],i=t.start+t.count,a=R(r.start,n.width,4),c=R(t.start,n.width,4);r.start<=i+1&&a===c&&R(r.start+r.count-1,n.width,4)===a?t.count=Math.max(t.count,r.start+r.count-t.start):(++s,o[s]=r)}o.length=s+1;let c=r.getParameter(e.UNPACK_ROW_LENGTH),l=r.getParameter(e.UNPACK_SKIP_PIXELS),u=r.getParameter(e.UNPACK_SKIP_ROWS);r.pixelStorei(e.UNPACK_ROW_LENGTH,n.width);for(let t=0,s=o.length;t<s;t++){let s=o[t],c=Math.floor(s.start/4),l=Math.ceil(s.count/4),u=c%n.width,d=Math.floor(c/n.width),f=l;r.pixelStorei(e.UNPACK_SKIP_PIXELS,u),r.pixelStorei(e.UNPACK_SKIP_ROWS,d),r.texSubImage2D(e.TEXTURE_2D,0,u,d,f,1,i,a,n.data)}t.clearUpdateRanges(),r.pixelStorei(e.UNPACK_ROW_LENGTH,c),r.pixelStorei(e.UNPACK_SKIP_PIXELS,l),r.pixelStorei(e.UNPACK_SKIP_ROWS,u)}}function B(t,n,s){let c=e.TEXTURE_2D;(n.isDataArrayTexture||n.isCompressedArrayTexture)&&(c=e.TEXTURE_2D_ARRAY),n.isData3DTexture&&(c=e.TEXTURE_3D);let l=L(t,n),u=n.source;r.bindTexture(c,t.__webglTexture,e.TEXTURE0+s);let d=i.get(u);if(u.version!==d.__version||l===!0){if(r.activeTexture(e.TEXTURE0+s),!(typeof ImageBitmap<`u`&&n.image instanceof ImageBitmap)){let t=z.getPrimaries(z.workingColorSpace),i=n.colorSpace===``?null:z.getPrimaries(n.colorSpace),a=n.colorSpace===``||t===i?e.NONE:e.BROWSER_DEFAULT_WEBGL;r.pixelStorei(e.UNPACK_FLIP_Y_WEBGL,n.flipY),r.pixelStorei(e.UNPACK_PREMULTIPLY_ALPHA_WEBGL,n.premultiplyAlpha),r.pixelStorei(e.UNPACK_COLORSPACE_CONVERSION_WEBGL,a)}r.pixelStorei(e.UNPACK_ALIGNMENT,n.unpackAlignment);let t=_(n.image,!1,a.maxTextureSize);t=xe(n,t);let i=o.convert(n.format,n.colorSpace),p=o.convert(n.type),m=x(n.internalFormat,i,p,n.normalized,n.colorSpace,n.isVideoTexture);I(c,n);let h,g=n.mipmaps,b=n.isVideoTexture!==!0,w=d.__version===void 0||l===!0,T=u.dataReady,E=C(n,t);if(n.isDepthTexture)m=S(n.format===Ta,n.type),w&&(b?r.texStorage2D(e.TEXTURE_2D,1,m,t.width,t.height):r.texImage2D(e.TEXTURE_2D,0,m,t.width,t.height,0,i,p,null));else if(n.isDataTexture)if(g.length>0){b&&w&&r.texStorage2D(e.TEXTURE_2D,E,m,g[0].width,g[0].height);for(let t=0,n=g.length;t<n;t++)h=g[t],b?T&&r.texSubImage2D(e.TEXTURE_2D,t,0,0,h.width,h.height,i,p,h.data):r.texImage2D(e.TEXTURE_2D,t,m,h.width,h.height,0,i,p,h.data);n.generateMipmaps=!1}else b?(w&&r.texStorage2D(e.TEXTURE_2D,E,m,t.width,t.height),T&&se(n,t,i,p)):r.texImage2D(e.TEXTURE_2D,0,m,t.width,t.height,0,i,p,t.data);else if(n.isCompressedTexture)if(n.isCompressedArrayTexture){b&&w&&r.texStorage3D(e.TEXTURE_2D_ARRAY,E,m,g[0].width,g[0].height,t.depth);for(let a=0,o=g.length;a<o;a++)if(h=g[a],n.format!==1023)if(i!==null)if(b){if(T)if(n.layerUpdates.size>0){let t=Ca(h.width,h.height,n.format,n.type);for(let o of n.layerUpdates){let n=h.data.subarray(o*t/h.data.BYTES_PER_ELEMENT,(o+1)*t/h.data.BYTES_PER_ELEMENT);r.compressedTexSubImage3D(e.TEXTURE_2D_ARRAY,a,0,0,o,h.width,h.height,1,i,n)}n.clearLayerUpdates()}else r.compressedTexSubImage3D(e.TEXTURE_2D_ARRAY,a,0,0,0,h.width,h.height,t.depth,i,h.data)}else r.compressedTexImage3D(e.TEXTURE_2D_ARRAY,a,m,h.width,h.height,t.depth,0,h.data,0,0);else P(`WebGLRenderer: Attempt to load unsupported compressed texture format in .uploadTexture()`);else b?T&&r.texSubImage3D(e.TEXTURE_2D_ARRAY,a,0,0,0,h.width,h.height,t.depth,i,p,h.data):r.texImage3D(e.TEXTURE_2D_ARRAY,a,m,h.width,h.height,t.depth,0,i,p,h.data)}else{b&&w&&r.texStorage2D(e.TEXTURE_2D,E,m,g[0].width,g[0].height);for(let t=0,a=g.length;t<a;t++)h=g[t],n.format===1023?b?T&&r.texSubImage2D(e.TEXTURE_2D,t,0,0,h.width,h.height,i,p,h.data):r.texImage2D(e.TEXTURE_2D,t,m,h.width,h.height,0,i,p,h.data):i===null?P(`WebGLRenderer: Attempt to load unsupported compressed texture format in .uploadTexture()`):b?T&&r.compressedTexSubImage2D(e.TEXTURE_2D,t,0,0,h.width,h.height,i,h.data):r.compressedTexImage2D(e.TEXTURE_2D,t,m,h.width,h.height,0,h.data)}else if(n.isDataArrayTexture)if(b){if(w&&r.texStorage3D(e.TEXTURE_2D_ARRAY,E,m,t.width,t.height,t.depth),T)if(n.layerUpdates.size>0){let a=Ca(t.width,t.height,n.format,n.type);for(let o of n.layerUpdates){let n=t.data.subarray(o*a/t.data.BYTES_PER_ELEMENT,(o+1)*a/t.data.BYTES_PER_ELEMENT);r.texSubImage3D(e.TEXTURE_2D_ARRAY,0,0,0,o,t.width,t.height,1,i,p,n)}n.clearLayerUpdates()}else r.texSubImage3D(e.TEXTURE_2D_ARRAY,0,0,0,0,t.width,t.height,t.depth,i,p,t.data)}else r.texImage3D(e.TEXTURE_2D_ARRAY,0,m,t.width,t.height,t.depth,0,i,p,t.data);else if(n.isData3DTexture)b?(w&&r.texStorage3D(e.TEXTURE_3D,E,m,t.width,t.height,t.depth),T&&r.texSubImage3D(e.TEXTURE_3D,0,0,0,0,t.width,t.height,t.depth,i,p,t.data)):r.texImage3D(e.TEXTURE_3D,0,m,t.width,t.height,t.depth,0,i,p,t.data);else if(n.isFramebufferTexture){if(w)if(b)r.texStorage2D(e.TEXTURE_2D,E,m,t.width,t.height);else{let n=t.width,a=t.height;for(let t=0;t<E;t++)r.texImage2D(e.TEXTURE_2D,t,m,n,a,0,i,p,null),n>>=1,a>>=1}}else if(n.isHTMLTexture){if(`texElementImage2D`in e){let r=e.canvas;if(r.hasAttribute(`layoutsubtree`)||r.setAttribute(`layoutsubtree`,`true`),t.parentNode!==r){r.appendChild(t),f.add(n),r.onpaint=e=>{let t=e.changedElements;for(let e of f)t.includes(e.image)&&(e.needsUpdate=!0)},r.requestPaint();return}if(e.texElementImage2D.length===3)e.texElementImage2D(e.TEXTURE_2D,e.RGBA8,t);else{let n=e.RGBA,r=e.RGBA,i=e.UNSIGNED_BYTE;e.texElementImage2D(e.TEXTURE_2D,0,n,r,i,t)}e.texParameteri(e.TEXTURE_2D,e.TEXTURE_MIN_FILTER,e.LINEAR),e.texParameteri(e.TEXTURE_2D,e.TEXTURE_WRAP_S,e.CLAMP_TO_EDGE),e.texParameteri(e.TEXTURE_2D,e.TEXTURE_WRAP_T,e.CLAMP_TO_EDGE)}}else if(g.length>0){if(b&&w){let t=Se(g[0]);r.texStorage2D(e.TEXTURE_2D,E,m,t.width,t.height)}for(let t=0,n=g.length;t<n;t++)h=g[t],b?T&&r.texSubImage2D(e.TEXTURE_2D,t,0,0,i,p,h):r.texImage2D(e.TEXTURE_2D,t,m,i,p,h);n.generateMipmaps=!1}else if(b){if(w){let n=Se(t);r.texStorage2D(e.TEXTURE_2D,E,m,n.width,n.height)}T&&r.texSubImage2D(e.TEXTURE_2D,0,0,0,i,p,t)}else r.texImage2D(e.TEXTURE_2D,0,m,i,p,t);v(n)&&y(c),d.__version=u.version,n.onUpdate&&n.onUpdate(n)}t.__version=n.version}function ce(t,n,s){if(n.image.length!==6)return;let c=L(t,n),l=n.source;r.bindTexture(e.TEXTURE_CUBE_MAP,t.__webglTexture,e.TEXTURE0+s);let u=i.get(l);if(l.version!==u.__version||c===!0){r.activeTexture(e.TEXTURE0+s);let t=z.getPrimaries(z.workingColorSpace),i=n.colorSpace===``?null:z.getPrimaries(n.colorSpace),d=n.colorSpace===``||t===i?e.NONE:e.BROWSER_DEFAULT_WEBGL;r.pixelStorei(e.UNPACK_FLIP_Y_WEBGL,n.flipY),r.pixelStorei(e.UNPACK_PREMULTIPLY_ALPHA_WEBGL,n.premultiplyAlpha),r.pixelStorei(e.UNPACK_ALIGNMENT,n.unpackAlignment),r.pixelStorei(e.UNPACK_COLORSPACE_CONVERSION_WEBGL,d);let f=n.isCompressedTexture||n.image[0].isCompressedTexture,p=n.image[0]&&n.image[0].isDataTexture,m=[];for(let e=0;e<6;e++)!f&&!p?m[e]=_(n.image[e],!0,a.maxCubemapSize):m[e]=p?n.image[e].image:n.image[e],m[e]=xe(n,m[e]);let h=m[0],g=o.convert(n.format,n.colorSpace),b=o.convert(n.type),S=x(n.internalFormat,g,b,n.normalized,n.colorSpace),w=n.isVideoTexture!==!0,T=u.__version===void 0||c===!0,E=l.dataReady,D=C(n,h);I(e.TEXTURE_CUBE_MAP,n);let O;if(f){w&&T&&r.texStorage2D(e.TEXTURE_CUBE_MAP,D,S,h.width,h.height);for(let t=0;t<6;t++){O=m[t].mipmaps;for(let i=0;i<O.length;i++){let a=O[i];n.format===1023?w?E&&r.texSubImage2D(e.TEXTURE_CUBE_MAP_POSITIVE_X+t,i,0,0,a.width,a.height,g,b,a.data):r.texImage2D(e.TEXTURE_CUBE_MAP_POSITIVE_X+t,i,S,a.width,a.height,0,g,b,a.data):g===null?P(`WebGLRenderer: Attempt to load unsupported compressed texture format in .setTextureCube()`):w?E&&r.compressedTexSubImage2D(e.TEXTURE_CUBE_MAP_POSITIVE_X+t,i,0,0,a.width,a.height,g,a.data):r.compressedTexImage2D(e.TEXTURE_CUBE_MAP_POSITIVE_X+t,i,S,a.width,a.height,0,a.data)}}}else{if(O=n.mipmaps,w&&T){O.length>0&&D++;let t=Se(m[0]);r.texStorage2D(e.TEXTURE_CUBE_MAP,D,S,t.width,t.height)}for(let t=0;t<6;t++)if(p){w?E&&r.texSubImage2D(e.TEXTURE_CUBE_MAP_POSITIVE_X+t,0,0,0,m[t].width,m[t].height,g,b,m[t].data):r.texImage2D(e.TEXTURE_CUBE_MAP_POSITIVE_X+t,0,S,m[t].width,m[t].height,0,g,b,m[t].data);for(let n=0;n<O.length;n++){let i=O[n].image[t].image;w?E&&r.texSubImage2D(e.TEXTURE_CUBE_MAP_POSITIVE_X+t,n+1,0,0,i.width,i.height,g,b,i.data):r.texImage2D(e.TEXTURE_CUBE_MAP_POSITIVE_X+t,n+1,S,i.width,i.height,0,g,b,i.data)}}else{w?E&&r.texSubImage2D(e.TEXTURE_CUBE_MAP_POSITIVE_X+t,0,0,0,g,b,m[t]):r.texImage2D(e.TEXTURE_CUBE_MAP_POSITIVE_X+t,0,S,g,b,m[t]);for(let n=0;n<O.length;n++){let i=O[n];w?E&&r.texSubImage2D(e.TEXTURE_CUBE_MAP_POSITIVE_X+t,n+1,0,0,g,b,i.image[t]):r.texImage2D(e.TEXTURE_CUBE_MAP_POSITIVE_X+t,n+1,S,g,b,i.image[t])}}}v(n)&&y(e.TEXTURE_CUBE_MAP),u.__version=l.version,n.onUpdate&&n.onUpdate(n)}t.__version=n.version}function le(t,n,a,s,l,u){let d=o.convert(a.format,a.colorSpace),f=o.convert(a.type),p=x(a.internalFormat,d,f,a.normalized,a.colorSpace),m=i.get(n),h=i.get(a);if(h.__renderTarget=n,!m.__hasExternalTextures){let t=Math.max(1,n.width>>u),i=Math.max(1,n.height>>u);l===e.TEXTURE_3D||l===e.TEXTURE_2D_ARRAY?r.texImage3D(l,u,p,t,i,n.depth,0,d,f,null):r.texImage2D(l,u,p,t,i,0,d,f,null)}r.bindFramebuffer(e.FRAMEBUFFER,t),U(n)?c.framebufferTexture2DMultisampleEXT(e.FRAMEBUFFER,s,l,h.__webglTexture,0,ye(n)):(l===e.TEXTURE_2D||l>=e.TEXTURE_CUBE_MAP_POSITIVE_X&&l<=e.TEXTURE_CUBE_MAP_NEGATIVE_Z)&&e.framebufferTexture2D(e.FRAMEBUFFER,s,l,h.__webglTexture,u),r.bindFramebuffer(e.FRAMEBUFFER,null)}function ue(t,n,r){if(e.bindRenderbuffer(e.RENDERBUFFER,t),n.depthBuffer){let i=n.depthTexture,a=i&&i.isDepthTexture?i.type:null,o=S(n.stencilBuffer,a),s=n.stencilBuffer?e.DEPTH_STENCIL_ATTACHMENT:e.DEPTH_ATTACHMENT;U(n)?c.renderbufferStorageMultisampleEXT(e.RENDERBUFFER,ye(n),o,n.width,n.height):r?e.renderbufferStorageMultisample(e.RENDERBUFFER,ye(n),o,n.width,n.height):e.renderbufferStorage(e.RENDERBUFFER,o,n.width,n.height),e.framebufferRenderbuffer(e.FRAMEBUFFER,s,e.RENDERBUFFER,t)}else{let t=n.textures;for(let i=0;i<t.length;i++){let a=t[i],s=o.convert(a.format,a.colorSpace),l=o.convert(a.type),u=x(a.internalFormat,s,l,a.normalized,a.colorSpace);U(n)?c.renderbufferStorageMultisampleEXT(e.RENDERBUFFER,ye(n),u,n.width,n.height):r?e.renderbufferStorageMultisample(e.RENDERBUFFER,ye(n),u,n.width,n.height):e.renderbufferStorage(e.RENDERBUFFER,u,n.width,n.height)}}e.bindRenderbuffer(e.RENDERBUFFER,null)}function de(t,n,a){let s=n.isWebGLCubeRenderTarget===!0;if(r.bindFramebuffer(e.FRAMEBUFFER,t),!(n.depthTexture&&n.depthTexture.isDepthTexture))throw Error(`THREE.WebGLTextures: renderTarget.depthTexture must be an instance of THREE.DepthTexture.`);let l=i.get(n.depthTexture);if(l.__renderTarget=n,(!l.__webglTexture||n.depthTexture.image.width!==n.width||n.depthTexture.image.height!==n.height)&&(n.depthTexture.image.width=n.width,n.depthTexture.image.height=n.height,n.depthTexture.needsUpdate=!0),s){if(l.__webglInit===void 0&&(l.__webglInit=!0,n.depthTexture.addEventListener(`dispose`,w)),l.__webglTexture===void 0){l.__webglTexture=e.createTexture(),r.bindTexture(e.TEXTURE_CUBE_MAP,l.__webglTexture),I(e.TEXTURE_CUBE_MAP,n.depthTexture);let t=o.convert(n.depthTexture.format),i=o.convert(n.depthTexture.type),a;n.depthTexture.format===1026?a=e.DEPTH_COMPONENT24:n.depthTexture.format===1027&&(a=e.DEPTH24_STENCIL8);for(let r=0;r<6;r++)e.texImage2D(e.TEXTURE_CUBE_MAP_POSITIVE_X+r,0,a,n.width,n.height,0,t,i,null)}}else N(n.depthTexture,0);let u=l.__webglTexture,d=ye(n),f=s?e.TEXTURE_CUBE_MAP_POSITIVE_X+a:e.TEXTURE_2D,p=n.depthTexture.format===1027?e.DEPTH_STENCIL_ATTACHMENT:e.DEPTH_ATTACHMENT;if(n.depthTexture.format===1026)U(n)?c.framebufferTexture2DMultisampleEXT(e.FRAMEBUFFER,p,f,u,0,d):e.framebufferTexture2D(e.FRAMEBUFFER,p,f,u,0);else if(n.depthTexture.format===1027)U(n)?c.framebufferTexture2DMultisampleEXT(e.FRAMEBUFFER,p,f,u,0,d):e.framebufferTexture2D(e.FRAMEBUFFER,p,f,u,0);else throw Error(`THREE.WebGLTextures: Unknown depthTexture format.`)}function fe(t){let n=i.get(t),a=t.isWebGLCubeRenderTarget===!0;if(n.__boundDepthTexture!==t.depthTexture){let e=t.depthTexture;if(n.__depthDisposeCallback&&n.__depthDisposeCallback(),e){let t=()=>{delete n.__boundDepthTexture,delete n.__depthDisposeCallback,e.removeEventListener(`dispose`,t)};e.addEventListener(`dispose`,t),n.__depthDisposeCallback=t}n.__boundDepthTexture=e}if(t.depthTexture&&!n.__autoAllocateDepthBuffer)if(a)for(let e=0;e<6;e++)de(n.__webglFramebuffer[e],t,e);else{let e=t.texture.mipmaps;e&&e.length>0?de(n.__webglFramebuffer[0],t,0):de(n.__webglFramebuffer,t,0)}else if(a){n.__webglDepthbuffer=[];for(let i=0;i<6;i++)if(r.bindFramebuffer(e.FRAMEBUFFER,n.__webglFramebuffer[i]),n.__webglDepthbuffer[i]===void 0)n.__webglDepthbuffer[i]=e.createRenderbuffer(),ue(n.__webglDepthbuffer[i],t,!1);else{let r=t.stencilBuffer?e.DEPTH_STENCIL_ATTACHMENT:e.DEPTH_ATTACHMENT,a=n.__webglDepthbuffer[i];e.bindRenderbuffer(e.RENDERBUFFER,a),e.framebufferRenderbuffer(e.FRAMEBUFFER,r,e.RENDERBUFFER,a)}}else{let i=t.texture.mipmaps;if(i&&i.length>0?r.bindFramebuffer(e.FRAMEBUFFER,n.__webglFramebuffer[0]):r.bindFramebuffer(e.FRAMEBUFFER,n.__webglFramebuffer),n.__webglDepthbuffer===void 0)n.__webglDepthbuffer=e.createRenderbuffer(),ue(n.__webglDepthbuffer,t,!1);else{let r=t.stencilBuffer?e.DEPTH_STENCIL_ATTACHMENT:e.DEPTH_ATTACHMENT,i=n.__webglDepthbuffer;e.bindRenderbuffer(e.RENDERBUFFER,i),e.framebufferRenderbuffer(e.FRAMEBUFFER,r,e.RENDERBUFFER,i)}}r.bindFramebuffer(e.FRAMEBUFFER,null)}function H(t,n,r){let a=i.get(t);n!==void 0&&le(a.__webglFramebuffer,t,t.texture,e.COLOR_ATTACHMENT0,e.TEXTURE_2D,0),r!==void 0&&fe(t)}function me(t){let n=t.texture,a=i.get(t),c=i.get(n);t.addEventListener(`dispose`,T);let l=t.textures,u=t.isWebGLCubeRenderTarget===!0,d=l.length>1;if(d||(c.__webglTexture===void 0&&(c.__webglTexture=e.createTexture()),c.__version=n.version,s.memory.textures++),u){a.__webglFramebuffer=[];for(let t=0;t<6;t++)if(n.mipmaps&&n.mipmaps.length>0){a.__webglFramebuffer[t]=[];for(let r=0;r<n.mipmaps.length;r++)a.__webglFramebuffer[t][r]=e.createFramebuffer()}else a.__webglFramebuffer[t]=e.createFramebuffer()}else{if(n.mipmaps&&n.mipmaps.length>0){a.__webglFramebuffer=[];for(let t=0;t<n.mipmaps.length;t++)a.__webglFramebuffer[t]=e.createFramebuffer()}else a.__webglFramebuffer=e.createFramebuffer();if(d)for(let t=0,n=l.length;t<n;t++){let n=i.get(l[t]);n.__webglTexture===void 0&&(n.__webglTexture=e.createTexture(),s.memory.textures++)}if(t.samples>0&&U(t)===!1){a.__webglMultisampledFramebuffer=e.createFramebuffer(),a.__webglColorRenderbuffer=[],r.bindFramebuffer(e.FRAMEBUFFER,a.__webglMultisampledFramebuffer);for(let n=0;n<l.length;n++){let r=l[n];a.__webglColorRenderbuffer[n]=e.createRenderbuffer(),e.bindRenderbuffer(e.RENDERBUFFER,a.__webglColorRenderbuffer[n]);let i=o.convert(r.format,r.colorSpace),s=o.convert(r.type),c=x(r.internalFormat,i,s,r.normalized,r.colorSpace,t.isXRRenderTarget===!0),u=ye(t);e.renderbufferStorageMultisample(e.RENDERBUFFER,u,c,t.width,t.height),e.framebufferRenderbuffer(e.FRAMEBUFFER,e.COLOR_ATTACHMENT0+n,e.RENDERBUFFER,a.__webglColorRenderbuffer[n])}e.bindRenderbuffer(e.RENDERBUFFER,null),t.depthBuffer&&(a.__webglDepthRenderbuffer=e.createRenderbuffer(),ue(a.__webglDepthRenderbuffer,t,!0)),r.bindFramebuffer(e.FRAMEBUFFER,null)}}if(u){r.bindTexture(e.TEXTURE_CUBE_MAP,c.__webglTexture),I(e.TEXTURE_CUBE_MAP,n);for(let r=0;r<6;r++)if(n.mipmaps&&n.mipmaps.length>0)for(let i=0;i<n.mipmaps.length;i++)le(a.__webglFramebuffer[r][i],t,n,e.COLOR_ATTACHMENT0,e.TEXTURE_CUBE_MAP_POSITIVE_X+r,i);else le(a.__webglFramebuffer[r],t,n,e.COLOR_ATTACHMENT0,e.TEXTURE_CUBE_MAP_POSITIVE_X+r,0);v(n)&&y(e.TEXTURE_CUBE_MAP),r.unbindTexture()}else if(d){for(let n=0,o=l.length;n<o;n++){let o=l[n],s=i.get(o),c=e.TEXTURE_2D;(t.isWebGL3DRenderTarget||t.isWebGLArrayRenderTarget)&&(c=t.isWebGL3DRenderTarget?e.TEXTURE_3D:e.TEXTURE_2D_ARRAY),r.bindTexture(c,s.__webglTexture),I(c,o),le(a.__webglFramebuffer,t,o,e.COLOR_ATTACHMENT0+n,c,0),v(o)&&y(c)}r.unbindTexture()}else{let i=e.TEXTURE_2D;if((t.isWebGL3DRenderTarget||t.isWebGLArrayRenderTarget)&&(i=t.isWebGL3DRenderTarget?e.TEXTURE_3D:e.TEXTURE_2D_ARRAY),r.bindTexture(i,c.__webglTexture),I(i,n),n.mipmaps&&n.mipmaps.length>0)for(let r=0;r<n.mipmaps.length;r++)le(a.__webglFramebuffer[r],t,n,e.COLOR_ATTACHMENT0,i,r);else le(a.__webglFramebuffer,t,n,e.COLOR_ATTACHMENT0,i,0);v(n)&&y(i),r.unbindTexture()}t.depthBuffer&&fe(t)}function he(e){let t=e.textures;for(let n=0,a=t.length;n<a;n++){let a=t[n];if(v(a)){let t=b(e),n=i.get(a).__webglTexture;r.bindTexture(t,n),y(t),r.unbindTexture()}}}let ge=[],_e=[];function ve(t){if(t.samples>0){if(U(t)===!1){let n=t.textures,a=t.width,o=t.height,s=e.COLOR_BUFFER_BIT,c=t.stencilBuffer?e.DEPTH_STENCIL_ATTACHMENT:e.DEPTH_ATTACHMENT,u=i.get(t),d=n.length>1;if(d)for(let t=0;t<n.length;t++)r.bindFramebuffer(e.FRAMEBUFFER,u.__webglMultisampledFramebuffer),e.framebufferRenderbuffer(e.FRAMEBUFFER,e.COLOR_ATTACHMENT0+t,e.RENDERBUFFER,null),r.bindFramebuffer(e.FRAMEBUFFER,u.__webglFramebuffer),e.framebufferTexture2D(e.DRAW_FRAMEBUFFER,e.COLOR_ATTACHMENT0+t,e.TEXTURE_2D,null,0);r.bindFramebuffer(e.READ_FRAMEBUFFER,u.__webglMultisampledFramebuffer);let f=t.texture.mipmaps;f&&f.length>0?r.bindFramebuffer(e.DRAW_FRAMEBUFFER,u.__webglFramebuffer[0]):r.bindFramebuffer(e.DRAW_FRAMEBUFFER,u.__webglFramebuffer);for(let r=0;r<n.length;r++){if(t.resolveDepthBuffer&&(t.depthBuffer&&(s|=e.DEPTH_BUFFER_BIT),t.stencilBuffer&&t.resolveStencilBuffer&&(s|=e.STENCIL_BUFFER_BIT)),d){e.framebufferRenderbuffer(e.READ_FRAMEBUFFER,e.COLOR_ATTACHMENT0,e.RENDERBUFFER,u.__webglColorRenderbuffer[r]);let t=i.get(n[r]).__webglTexture;e.framebufferTexture2D(e.DRAW_FRAMEBUFFER,e.COLOR_ATTACHMENT0,e.TEXTURE_2D,t,0)}e.blitFramebuffer(0,0,a,o,0,0,a,o,s,e.NEAREST),l===!0&&(ge.length=0,_e.length=0,ge.push(e.COLOR_ATTACHMENT0+r),t.depthBuffer&&t.resolveDepthBuffer===!1&&(ge.push(c),_e.push(c),e.invalidateFramebuffer(e.DRAW_FRAMEBUFFER,_e)),e.invalidateFramebuffer(e.READ_FRAMEBUFFER,ge))}if(r.bindFramebuffer(e.READ_FRAMEBUFFER,null),r.bindFramebuffer(e.DRAW_FRAMEBUFFER,null),d)for(let t=0;t<n.length;t++){r.bindFramebuffer(e.FRAMEBUFFER,u.__webglMultisampledFramebuffer),e.framebufferRenderbuffer(e.FRAMEBUFFER,e.COLOR_ATTACHMENT0+t,e.RENDERBUFFER,u.__webglColorRenderbuffer[t]);let a=i.get(n[t]).__webglTexture;r.bindFramebuffer(e.FRAMEBUFFER,u.__webglFramebuffer),e.framebufferTexture2D(e.DRAW_FRAMEBUFFER,e.COLOR_ATTACHMENT0+t,e.TEXTURE_2D,a,0)}r.bindFramebuffer(e.DRAW_FRAMEBUFFER,u.__webglMultisampledFramebuffer)}else if(t.depthBuffer&&t.resolveDepthBuffer===!1&&l){let n=t.stencilBuffer?e.DEPTH_STENCIL_ATTACHMENT:e.DEPTH_ATTACHMENT;e.invalidateFramebuffer(e.DRAW_FRAMEBUFFER,[n])}}}function ye(e){return Math.min(a.maxSamples,e.samples)}function U(e){let n=i.get(e);return e.samples>0&&t.has(`WEBGL_multisampled_render_to_texture`)===!0&&n.__useRenderToTexture!==!1}function be(e){let t=s.render.frame;d.get(e)!==t&&(d.set(e,t),e.update())}function xe(e,t){let n=e.colorSpace,r=e.format,i=e.type;return e.isCompressedTexture===!0||e.isVideoTexture===!0||n!==`srgb-linear`&&n!==``&&(z.getTransfer(n)===`srgb`?(r!==1023||i!==1009)&&P(`WebGLTextures: sRGB encoded textures have to use RGBAFormat and UnsignedByteType.`):na(`WebGLTextures: Unsupported texture color space:`,n)),t}function Se(e){return typeof HTMLImageElement<`u`&&e instanceof HTMLImageElement?(u.width=e.naturalWidth||e.width,u.height=e.naturalHeight||e.height):typeof VideoFrame<`u`&&e instanceof VideoFrame?(u.width=e.displayWidth,u.height=e.displayHeight):(u.width=e.width,u.height=e.height),u}this.allocateTextureUnit=j,this.resetTextureUnits=ee,this.getTextureUnits=A,this.setTextureUnits=te,this.setTexture2D=N,this.setTexture2DArray=ne,this.setTexture3D=re,this.setTextureCube=ie,this.rebindTextures=H,this.setupRenderTarget=me,this.updateRenderTargetMipmap=he,this.updateMultisampleRenderTarget=ve,this.setupDepthRenderbuffer=fe,this.setupFrameBufferTexture=le,this.useMultisampledRTT=U,this.isReversedDepthBuffer=function(){return r.buffers.depth.getReversed()}}function m_(e,t){function n(n,r=``){let i,a=z.getTransfer(r);if(n===1009)return e.UNSIGNED_BYTE;if(n===1017)return e.UNSIGNED_SHORT_4_4_4_4;if(n===1018)return e.UNSIGNED_SHORT_5_5_5_1;if(n===35902)return e.UNSIGNED_INT_5_9_9_9_REV;if(n===35899)return e.UNSIGNED_INT_10F_11F_11F_REV;if(n===1010)return e.BYTE;if(n===1011)return e.SHORT;if(n===1012)return e.UNSIGNED_SHORT;if(n===1013)return e.INT;if(n===1014)return e.UNSIGNED_INT;if(n===1015)return e.FLOAT;if(n===1016)return e.HALF_FLOAT;if(n===1021)return e.ALPHA;if(n===1022)return e.RGB;if(n===1023)return e.RGBA;if(n===1026)return e.DEPTH_COMPONENT;if(n===1027)return e.DEPTH_STENCIL;if(n===1028)return e.RED;if(n===1029)return e.RED_INTEGER;if(n===1030)return e.RG;if(n===1031)return e.RG_INTEGER;if(n===1033)return e.RGBA_INTEGER;if(n===33776||n===33777||n===33778||n===33779)if(a===`srgb`)if(i=t.get(`WEBGL_compressed_texture_s3tc_srgb`),i!==null){if(n===33776)return i.COMPRESSED_SRGB_S3TC_DXT1_EXT;if(n===33777)return i.COMPRESSED_SRGB_ALPHA_S3TC_DXT1_EXT;if(n===33778)return i.COMPRESSED_SRGB_ALPHA_S3TC_DXT3_EXT;if(n===33779)return i.COMPRESSED_SRGB_ALPHA_S3TC_DXT5_EXT}else return null;else if(i=t.get(`WEBGL_compressed_texture_s3tc`),i!==null){if(n===33776)return i.COMPRESSED_RGB_S3TC_DXT1_EXT;if(n===33777)return i.COMPRESSED_RGBA_S3TC_DXT1_EXT;if(n===33778)return i.COMPRESSED_RGBA_S3TC_DXT3_EXT;if(n===33779)return i.COMPRESSED_RGBA_S3TC_DXT5_EXT}else return null;if(n===35840||n===35841||n===35842||n===35843)if(i=t.get(`WEBGL_compressed_texture_pvrtc`),i!==null){if(n===35840)return i.COMPRESSED_RGB_PVRTC_4BPPV1_IMG;if(n===35841)return i.COMPRESSED_RGB_PVRTC_2BPPV1_IMG;if(n===35842)return i.COMPRESSED_RGBA_PVRTC_4BPPV1_IMG;if(n===35843)return i.COMPRESSED_RGBA_PVRTC_2BPPV1_IMG}else return null;if(n===36196||n===37492||n===37496||n===37488||n===37489||n===37490||n===37491)if(i=t.get(`WEBGL_compressed_texture_etc`),i!==null){if(n===36196||n===37492)return a===`srgb`?i.COMPRESSED_SRGB8_ETC2:i.COMPRESSED_RGB8_ETC2;if(n===37496)return a===`srgb`?i.COMPRESSED_SRGB8_ALPHA8_ETC2_EAC:i.COMPRESSED_RGBA8_ETC2_EAC;if(n===37488)return i.COMPRESSED_R11_EAC;if(n===37489)return i.COMPRESSED_SIGNED_R11_EAC;if(n===37490)return i.COMPRESSED_RG11_EAC;if(n===37491)return i.COMPRESSED_SIGNED_RG11_EAC}else return null;if(n===37808||n===37809||n===37810||n===37811||n===37812||n===37813||n===37814||n===37815||n===37816||n===37817||n===37818||n===37819||n===37820||n===37821)if(i=t.get(`WEBGL_compressed_texture_astc`),i!==null){if(n===37808)return a===`srgb`?i.COMPRESSED_SRGB8_ALPHA8_ASTC_4x4_KHR:i.COMPRESSED_RGBA_ASTC_4x4_KHR;if(n===37809)return a===`srgb`?i.COMPRESSED_SRGB8_ALPHA8_ASTC_5x4_KHR:i.COMPRESSED_RGBA_ASTC_5x4_KHR;if(n===37810)return a===`srgb`?i.COMPRESSED_SRGB8_ALPHA8_ASTC_5x5_KHR:i.COMPRESSED_RGBA_ASTC_5x5_KHR;if(n===37811)return a===`srgb`?i.COMPRESSED_SRGB8_ALPHA8_ASTC_6x5_KHR:i.COMPRESSED_RGBA_ASTC_6x5_KHR;if(n===37812)return a===`srgb`?i.COMPRESSED_SRGB8_ALPHA8_ASTC_6x6_KHR:i.COMPRESSED_RGBA_ASTC_6x6_KHR;if(n===37813)return a===`srgb`?i.COMPRESSED_SRGB8_ALPHA8_ASTC_8x5_KHR:i.COMPRESSED_RGBA_ASTC_8x5_KHR;if(n===37814)return a===`srgb`?i.COMPRESSED_SRGB8_ALPHA8_ASTC_8x6_KHR:i.COMPRESSED_RGBA_ASTC_8x6_KHR;if(n===37815)return a===`srgb`?i.COMPRESSED_SRGB8_ALPHA8_ASTC_8x8_KHR:i.COMPRESSED_RGBA_ASTC_8x8_KHR;if(n===37816)return a===`srgb`?i.COMPRESSED_SRGB8_ALPHA8_ASTC_10x5_KHR:i.COMPRESSED_RGBA_ASTC_10x5_KHR;if(n===37817)return a===`srgb`?i.COMPRESSED_SRGB8_ALPHA8_ASTC_10x6_KHR:i.COMPRESSED_RGBA_ASTC_10x6_KHR;if(n===37818)return a===`srgb`?i.COMPRESSED_SRGB8_ALPHA8_ASTC_10x8_KHR:i.COMPRESSED_RGBA_ASTC_10x8_KHR;if(n===37819)return a===`srgb`?i.COMPRESSED_SRGB8_ALPHA8_ASTC_10x10_KHR:i.COMPRESSED_RGBA_ASTC_10x10_KHR;if(n===37820)return a===`srgb`?i.COMPRESSED_SRGB8_ALPHA8_ASTC_12x10_KHR:i.COMPRESSED_RGBA_ASTC_12x10_KHR;if(n===37821)return a===`srgb`?i.COMPRESSED_SRGB8_ALPHA8_ASTC_12x12_KHR:i.COMPRESSED_RGBA_ASTC_12x12_KHR}else return null;if(n===36492||n===36494||n===36495)if(i=t.get(`EXT_texture_compression_bptc`),i!==null){if(n===36492)return a===`srgb`?i.COMPRESSED_SRGB_ALPHA_BPTC_UNORM_EXT:i.COMPRESSED_RGBA_BPTC_UNORM_EXT;if(n===36494)return i.COMPRESSED_RGB_BPTC_SIGNED_FLOAT_EXT;if(n===36495)return i.COMPRESSED_RGB_BPTC_UNSIGNED_FLOAT_EXT}else return null;if(n===36283||n===36284||n===36285||n===36286)if(i=t.get(`EXT_texture_compression_rgtc`),i!==null){if(n===36283)return i.COMPRESSED_RED_RGTC1_EXT;if(n===36284)return i.COMPRESSED_SIGNED_RED_RGTC1_EXT;if(n===36285)return i.COMPRESSED_RED_GREEN_RGTC2_EXT;if(n===36286)return i.COMPRESSED_SIGNED_RED_GREEN_RGTC2_EXT}else return null;return n===1020?e.UNSIGNED_INT_24_8:e[n]===void 0?null:e[n]}return{convert:n}}var h_=`
void main() {

	gl_Position = vec4( position, 1.0 );

}`,g_=`
uniform sampler2DArray depthColor;
uniform float depthWidth;
uniform float depthHeight;

void main() {

	vec2 coord = vec2( gl_FragCoord.x / depthWidth, gl_FragCoord.y / depthHeight );

	if ( coord.x >= 1.0 ) {

		gl_FragDepth = texture( depthColor, vec3( coord.x - 1.0, coord.y, 1 ) ).r;

	} else {

		gl_FragDepth = texture( depthColor, vec3( coord.x, coord.y, 0 ) ).r;

	}

}`,__=class{constructor(){this.texture=null,this.mesh=null,this.depthNear=0,this.depthFar=0}init(e,t){if(this.texture===null){let n=new J(e.texture);(e.depthNear!==t.depthNear||e.depthFar!==t.depthFar)&&(this.depthNear=e.depthNear,this.depthFar=e.depthFar),this.texture=n}}getMesh(e){if(this.texture!==null&&this.mesh===null){let t=e.cameras[0].viewport,n=new r({vertexShader:h_,fragmentShader:g_,uniforms:{depthColor:{value:this.texture},depthWidth:{value:t.z},depthHeight:{value:t.w}}});this.mesh=new wr(new d(20,20),n)}return this.mesh}reset(){this.texture=null,this.mesh=null}getDepthTexture(){return this.texture}},v_=class extends Be{constructor(e,t){super();let r=this,i=null,a=1,o=null,s=`local-floor`,c=1,l=null,u=null,d=null,f=null,p=null,m=null,h=typeof XRWebGLBinding<`u`,g=new __,_={},v=t.getContextAttributes(),y=null,b=null,x=[],S=[],C=new n,w=null,T=new Ye;T.viewport=new Hi;let E=new Ye;E.viewport=new Hi;let D=[T,E],O=new Bn,k=null,ee=null;this.cameraAutoUpdate=!0,this.enabled=!1,this.isPresenting=!1,this.getController=function(e){let t=x[e];return t===void 0&&(t=new Yi,x[e]=t),t.getTargetRaySpace()},this.getControllerGrip=function(e){let t=x[e];return t===void 0&&(t=new Yi,x[e]=t),t.getGripSpace()},this.getHand=function(e){let t=x[e];return t===void 0&&(t=new Yi,x[e]=t),t.getHandSpace()};function A(e){let t=S.indexOf(e.inputSource);if(t===-1)return;let n=x[t];n!==void 0&&(n.update(e.inputSource,e.frame,l||o),n.dispatchEvent({type:e.type,data:e.inputSource}))}function te(){i.removeEventListener(`select`,A),i.removeEventListener(`selectstart`,A),i.removeEventListener(`selectend`,A),i.removeEventListener(`squeeze`,A),i.removeEventListener(`squeezestart`,A),i.removeEventListener(`squeezeend`,A),i.removeEventListener(`end`,te),i.removeEventListener(`inputsourceschange`,j);for(let e=0;e<x.length;e++){let t=S[e];t!==null&&(S[e]=null,x[e].disconnect(t))}k=null,ee=null,g.reset();for(let e in _)delete _[e];e.setRenderTarget(y),p=null,f=null,d=null,i=null,b=null,F.stop(),r.isPresenting=!1,e.setPixelRatio(w),e.setSize(C.width,C.height,!1),r.dispatchEvent({type:`sessionend`})}this.setFramebufferScaleFactor=function(e){a=e,r.isPresenting===!0&&P(`WebXRManager: Cannot change framebuffer scale while presenting.`)},this.setReferenceSpaceType=function(e){s=e,r.isPresenting===!0&&P(`WebXRManager: Cannot change reference space type while presenting.`)},this.getReferenceSpace=function(){return l||o},this.setReferenceSpace=function(e){l=e},this.getBaseLayer=function(){return f===null?p:f},this.getBinding=function(){return d===null&&h&&(d=new XRWebGLBinding(i,t)),d},this.getFrame=function(){return m},this.getSession=function(){return i},this.setSession=async function(n){if(i=n,i!==null){if(y=e.getRenderTarget(),i.addEventListener(`select`,A),i.addEventListener(`selectstart`,A),i.addEventListener(`selectend`,A),i.addEventListener(`squeeze`,A),i.addEventListener(`squeezestart`,A),i.addEventListener(`squeezeend`,A),i.addEventListener(`end`,te),i.addEventListener(`inputsourceschange`,j),v.xrCompatible!==!0&&await t.makeXRCompatible(),w=e.getPixelRatio(),e.getSize(C),h&&`createProjectionLayer`in XRWebGLBinding.prototype){let n=null,r=null,o=null;v.depth&&(o=v.stencil?t.DEPTH24_STENCIL8:t.DEPTH_COMPONENT24,n=v.stencil?Ta:ia,r=v.stencil?yi:en);let s={colorFormat:t.RGBA8,depthFormat:o,scaleFactor:a};d=this.getBinding(),f=d.createProjectionLayer(s),i.updateRenderState({layers:[f]}),e.setPixelRatio(1),e.setSize(f.textureWidth,f.textureHeight,!1),b=new Ln(f.textureWidth,f.textureHeight,{format:st,type:se,depthTexture:new Mn(f.textureWidth,f.textureHeight,r,void 0,void 0,void 0,void 0,void 0,void 0,n),stencilBuffer:v.stencil,colorSpace:e.outputColorSpace,samples:v.antialias?4:0,resolveDepthBuffer:f.ignoreDepthValues===!1,resolveStencilBuffer:f.ignoreDepthValues===!1})}else{let n={antialias:v.antialias,alpha:!0,depth:v.depth,stencil:v.stencil,framebufferScaleFactor:a};p=new XRWebGLLayer(i,t,n),i.updateRenderState({baseLayer:p}),e.setPixelRatio(1),e.setSize(p.framebufferWidth,p.framebufferHeight,!1),b=new Ln(p.framebufferWidth,p.framebufferHeight,{format:st,type:se,colorSpace:e.outputColorSpace,stencilBuffer:v.stencil,resolveDepthBuffer:p.ignoreDepthValues===!1,resolveStencilBuffer:p.ignoreDepthValues===!1})}b.isXRRenderTarget=!0,this.setFoveation(c),l=null,o=await i.requestReferenceSpace(s),F.setContext(i),F.start(),r.isPresenting=!0,r.dispatchEvent({type:`sessionstart`})}},this.getEnvironmentBlendMode=function(){if(i!==null)return i.environmentBlendMode},this.getDepthTexture=function(){return g.getDepthTexture()};function j(e){for(let t=0;t<e.removed.length;t++){let n=e.removed[t],r=S.indexOf(n);r>=0&&(S[r]=null,x[r].disconnect(n))}for(let t=0;t<e.added.length;t++){let n=e.added[t],r=S.indexOf(n);if(r===-1){for(let e=0;e<x.length;e++)if(e>=S.length){S.push(n),r=e;break}else if(S[e]===null){S[e]=n,r=e;break}if(r===-1)break}let i=x[r];i&&i.connect(n)}}let M=new Y,N=new Y;function ne(e,t,n){M.setFromMatrixPosition(t.matrixWorld),N.setFromMatrixPosition(n.matrixWorld);let r=M.distanceTo(N),i=t.projectionMatrix.elements,a=n.projectionMatrix.elements,o=i[14]/(i[10]-1),s=i[14]/(i[10]+1),c=(i[9]+1)/i[5],l=(i[9]-1)/i[5],u=(i[8]-1)/i[0],d=(a[8]+1)/a[0],f=o*u,p=o*d,m=r/(-u+d),h=m*-u;if(t.matrixWorld.decompose(e.position,e.quaternion,e.scale),e.translateX(h),e.translateZ(m),e.matrixWorld.compose(e.position,e.quaternion,e.scale),e.matrixWorldInverse.copy(e.matrixWorld).invert(),i[10]===-1)e.projectionMatrix.copy(t.projectionMatrix),e.projectionMatrixInverse.copy(t.projectionMatrixInverse);else{let t=o+m,n=s+m,i=f-h,a=p+(r-h),u=c*s/n*t,d=l*s/n*t;e.projectionMatrix.makePerspective(i,a,u,d,t,n),e.projectionMatrixInverse.copy(e.projectionMatrix).invert()}}function re(e,t){t===null?e.matrixWorld.copy(e.matrix):e.matrixWorld.multiplyMatrices(t.matrixWorld,e.matrix),e.matrixWorldInverse.copy(e.matrixWorld).invert()}this.updateCamera=function(e){if(i===null)return;let t=e.near,n=e.far;g.texture!==null&&(g.depthNear>0&&(t=g.depthNear),g.depthFar>0&&(n=g.depthFar)),O.near=E.near=T.near=t,O.far=E.far=T.far=n,(k!==O.near||ee!==O.far)&&(i.updateRenderState({depthNear:O.near,depthFar:O.far}),k=O.near,ee=O.far),O.layers.mask=e.layers.mask|6,T.layers.mask=O.layers.mask&-5,E.layers.mask=O.layers.mask&-3;let r=e.parent,a=O.cameras;re(O,r);for(let e=0;e<a.length;e++)re(a[e],r);a.length===2?ne(O,T,E):O.projectionMatrix.copy(T.projectionMatrix),ie(e,O,r)};function ie(e,t,n){n===null?e.matrix.copy(t.matrixWorld):(e.matrix.copy(n.matrixWorld),e.matrix.invert(),e.matrix.multiply(t.matrixWorld)),e.matrix.decompose(e.position,e.quaternion,e.scale),e.updateMatrixWorld(!0),e.projectionMatrix.copy(t.projectionMatrix),e.projectionMatrixInverse.copy(t.projectionMatrixInverse),e.isPerspectiveCamera&&(e.fov=Si*2*Math.atan(1/e.projectionMatrix.elements[5]),e.zoom=1)}this.getCamera=function(){return O},this.getFoveation=function(){if(!(f===null&&p===null))return c},this.setFoveation=function(e){c=e,f!==null&&(f.fixedFoveation=e),p!==null&&p.fixedFoveation!==void 0&&(p.fixedFoveation=e)},this.hasDepthSensing=function(){return g.texture!==null},this.getDepthSensingMesh=function(){return g.getMesh(O)},this.getCameraTexture=function(e){return _[e]};let ae=null;function oe(t,n){if(u=n.getViewerPose(l||o),m=n,u!==null){let t=u.views;p!==null&&(e.setRenderTargetFramebuffer(b,p.framebuffer),e.setRenderTarget(b));let n=!1;t.length!==O.cameras.length&&(O.cameras.length=0,n=!0);for(let r=0;r<t.length;r++){let i=t[r],a=null;if(p!==null)a=p.getViewport(i);else{let t=d.getViewSubImage(f,i);a=t.viewport,r===0&&(e.setRenderTargetTextures(b,t.colorTexture,t.depthStencilTexture),e.setRenderTarget(b))}let o=D[r];o===void 0&&(o=new Ye,o.layers.enable(r),o.viewport=new Hi,D[r]=o),o.matrix.fromArray(i.transform.matrix),o.matrix.decompose(o.position,o.quaternion,o.scale),o.projectionMatrix.fromArray(i.projectionMatrix),o.projectionMatrixInverse.copy(o.projectionMatrix).invert(),o.viewport.set(a.x,a.y,a.width,a.height),r===0&&(O.matrix.copy(o.matrix),O.matrix.decompose(O.position,O.quaternion,O.scale)),n===!0&&O.cameras.push(o)}let a=i.enabledFeatures;if(a&&a.includes(`depth-sensing`)&&i.depthUsage==`gpu-optimized`&&h){d=r.getBinding();let e=d.getDepthInformation(t[0]);e&&e.isValid&&e.texture&&g.init(e,i.renderState)}if(a&&a.includes(`camera-access`)&&h){e.state.unbindTexture(),d=r.getBinding();for(let e=0;e<t.length;e++){let n=t[e].camera;if(n){let e=_[n];e||(e=new J,_[n]=e);let t=d.getCameraImage(n);e.sourceTexture=t}}}}for(let e=0;e<x.length;e++){let t=S[e],r=x[e];t!==null&&r!==void 0&&r.update(t,n,l||o)}ae&&ae(t,n),n.detectedPlanes&&r.dispatchEvent({type:`planesdetected`,data:n}),m=null}let F=new dm;F.setAnimationLoop(oe),this.setAnimationLoop=function(e){ae=e},this.dispose=function(){}}},y_=new ki,b_=new X;b_.set(-1,0,0,0,1,0,0,0,1);function x_(e,t){function n(e,t){e.matrixAutoUpdate===!0&&e.updateMatrix(),t.value.copy(e.matrix)}function r(t,n){n.color.getRGB(t.fogColor.value,ga(e)),n.isFog?(t.fogNear.value=n.near,t.fogFar.value=n.far):n.isFogExp2&&(t.fogDensity.value=n.density)}function i(e,t,n,r,i){t.isNodeMaterial?t.uniformsNeedUpdate=!1:t.isMeshBasicMaterial?a(e,t):t.isMeshLambertMaterial?(a(e,t),t.envMap&&(e.envMapIntensity.value=t.envMapIntensity)):t.isMeshToonMaterial?(a(e,t),d(e,t)):t.isMeshPhongMaterial?(a(e,t),u(e,t),t.envMap&&(e.envMapIntensity.value=t.envMapIntensity)):t.isMeshStandardMaterial?(a(e,t),f(e,t),t.isMeshPhysicalMaterial&&p(e,t,i)):t.isMeshMatcapMaterial?(a(e,t),m(e,t)):t.isMeshDepthMaterial?a(e,t):t.isMeshDistanceMaterial?(a(e,t),h(e,t)):t.isMeshNormalMaterial?a(e,t):t.isLineBasicMaterial?(o(e,t),t.isLineDashedMaterial&&s(e,t)):t.isPointsMaterial?c(e,t,n,r):t.isSpriteMaterial?l(e,t):t.isShadowMaterial?(e.color.value.copy(t.color),e.opacity.value=t.opacity):t.isShaderMaterial&&(t.uniformsNeedUpdate=!1)}function a(e,r){e.opacity.value=r.opacity,r.color&&e.diffuse.value.copy(r.color),r.emissive&&e.emissive.value.copy(r.emissive).multiplyScalar(r.emissiveIntensity),r.map&&(e.map.value=r.map,n(r.map,e.mapTransform)),r.alphaMap&&(e.alphaMap.value=r.alphaMap,n(r.alphaMap,e.alphaMapTransform)),r.bumpMap&&(e.bumpMap.value=r.bumpMap,n(r.bumpMap,e.bumpMapTransform),e.bumpScale.value=r.bumpScale,r.side===1&&(e.bumpScale.value*=-1)),r.normalMap&&(e.normalMap.value=r.normalMap,n(r.normalMap,e.normalMapTransform),e.normalScale.value.copy(r.normalScale),r.side===1&&e.normalScale.value.negate()),r.displacementMap&&(e.displacementMap.value=r.displacementMap,n(r.displacementMap,e.displacementMapTransform),e.displacementScale.value=r.displacementScale,e.displacementBias.value=r.displacementBias),r.emissiveMap&&(e.emissiveMap.value=r.emissiveMap,n(r.emissiveMap,e.emissiveMapTransform)),r.specularMap&&(e.specularMap.value=r.specularMap,n(r.specularMap,e.specularMapTransform)),r.alphaTest>0&&(e.alphaTest.value=r.alphaTest);let i=t.get(r),a=i.envMap,o=i.envMapRotation;a&&(e.envMap.value=a,e.envMapRotation.value.setFromMatrix4(y_.makeRotationFromEuler(o)).transpose(),a.isCubeTexture&&a.isRenderTargetTexture===!1&&e.envMapRotation.value.premultiply(b_),e.reflectivity.value=r.reflectivity,e.ior.value=r.ior,e.refractionRatio.value=r.refractionRatio),r.lightMap&&(e.lightMap.value=r.lightMap,e.lightMapIntensity.value=r.lightMapIntensity,n(r.lightMap,e.lightMapTransform)),r.aoMap&&(e.aoMap.value=r.aoMap,e.aoMapIntensity.value=r.aoMapIntensity,n(r.aoMap,e.aoMapTransform))}function o(e,t){e.diffuse.value.copy(t.color),e.opacity.value=t.opacity,t.map&&(e.map.value=t.map,n(t.map,e.mapTransform))}function s(e,t){e.dashSize.value=t.dashSize,e.totalSize.value=t.dashSize+t.gapSize,e.scale.value=t.scale}function c(e,t,r,i){e.diffuse.value.copy(t.color),e.opacity.value=t.opacity,e.size.value=t.size*r,e.scale.value=i*.5,t.map&&(e.map.value=t.map,n(t.map,e.uvTransform)),t.alphaMap&&(e.alphaMap.value=t.alphaMap,n(t.alphaMap,e.alphaMapTransform)),t.alphaTest>0&&(e.alphaTest.value=t.alphaTest)}function l(e,t){e.diffuse.value.copy(t.color),e.opacity.value=t.opacity,e.rotation.value=t.rotation,t.map&&(e.map.value=t.map,n(t.map,e.mapTransform)),t.alphaMap&&(e.alphaMap.value=t.alphaMap,n(t.alphaMap,e.alphaMapTransform)),t.alphaTest>0&&(e.alphaTest.value=t.alphaTest)}function u(e,t){e.specular.value.copy(t.specular),e.shininess.value=Math.max(t.shininess,1e-4)}function d(e,t){t.gradientMap&&(e.gradientMap.value=t.gradientMap)}function f(e,t){e.metalness.value=t.metalness,t.metalnessMap&&(e.metalnessMap.value=t.metalnessMap,n(t.metalnessMap,e.metalnessMapTransform)),e.roughness.value=t.roughness,t.roughnessMap&&(e.roughnessMap.value=t.roughnessMap,n(t.roughnessMap,e.roughnessMapTransform)),t.envMap&&(e.envMapIntensity.value=t.envMapIntensity)}function p(e,t,r){e.ior.value=t.ior,t.sheen>0&&(e.sheenColor.value.copy(t.sheenColor).multiplyScalar(t.sheen),e.sheenRoughness.value=t.sheenRoughness,t.sheenColorMap&&(e.sheenColorMap.value=t.sheenColorMap,n(t.sheenColorMap,e.sheenColorMapTransform)),t.sheenRoughnessMap&&(e.sheenRoughnessMap.value=t.sheenRoughnessMap,n(t.sheenRoughnessMap,e.sheenRoughnessMapTransform))),t.clearcoat>0&&(e.clearcoat.value=t.clearcoat,e.clearcoatRoughness.value=t.clearcoatRoughness,t.clearcoatMap&&(e.clearcoatMap.value=t.clearcoatMap,n(t.clearcoatMap,e.clearcoatMapTransform)),t.clearcoatRoughnessMap&&(e.clearcoatRoughnessMap.value=t.clearcoatRoughnessMap,n(t.clearcoatRoughnessMap,e.clearcoatRoughnessMapTransform)),t.clearcoatNormalMap&&(e.clearcoatNormalMap.value=t.clearcoatNormalMap,n(t.clearcoatNormalMap,e.clearcoatNormalMapTransform),e.clearcoatNormalScale.value.copy(t.clearcoatNormalScale),t.side===1&&e.clearcoatNormalScale.value.negate())),t.dispersion>0&&(e.dispersion.value=t.dispersion),t.iridescence>0&&(e.iridescence.value=t.iridescence,e.iridescenceIOR.value=t.iridescenceIOR,e.iridescenceThicknessMinimum.value=t.iridescenceThicknessRange[0],e.iridescenceThicknessMaximum.value=t.iridescenceThicknessRange[1],t.iridescenceMap&&(e.iridescenceMap.value=t.iridescenceMap,n(t.iridescenceMap,e.iridescenceMapTransform)),t.iridescenceThicknessMap&&(e.iridescenceThicknessMap.value=t.iridescenceThicknessMap,n(t.iridescenceThicknessMap,e.iridescenceThicknessMapTransform))),t.transmission>0&&(e.transmission.value=t.transmission,e.transmissionSamplerMap.value=r.texture,e.transmissionSamplerSize.value.set(r.width,r.height),t.transmissionMap&&(e.transmissionMap.value=t.transmissionMap,n(t.transmissionMap,e.transmissionMapTransform)),e.thickness.value=t.thickness,t.thicknessMap&&(e.thicknessMap.value=t.thicknessMap,n(t.thicknessMap,e.thicknessMapTransform)),e.attenuationDistance.value=t.attenuationDistance,e.attenuationColor.value.copy(t.attenuationColor)),t.anisotropy>0&&(e.anisotropyVector.value.set(t.anisotropy*Math.cos(t.anisotropyRotation),t.anisotropy*Math.sin(t.anisotropyRotation)),t.anisotropyMap&&(e.anisotropyMap.value=t.anisotropyMap,n(t.anisotropyMap,e.anisotropyMapTransform))),e.specularIntensity.value=t.specularIntensity,e.specularColor.value.copy(t.specularColor),t.specularColorMap&&(e.specularColorMap.value=t.specularColorMap,n(t.specularColorMap,e.specularColorMapTransform)),t.specularIntensityMap&&(e.specularIntensityMap.value=t.specularIntensityMap,n(t.specularIntensityMap,e.specularIntensityMapTransform))}function m(e,t){t.matcap&&(e.matcap.value=t.matcap)}function h(e,n){let r=t.get(n).light;e.referencePosition.value.setFromMatrixPosition(r.matrixWorld),e.nearDistance.value=r.shadow.camera.near,e.farDistance.value=r.shadow.camera.far}return{refreshFogUniforms:r,refreshMaterialUniforms:i}}function S_(e,t,n,r){let i={},a={},o=[],s=e.getParameter(e.MAX_UNIFORM_BUFFER_BINDINGS);function c(e,t){let n=t.program;r.uniformBlockBinding(e,n)}function l(e,n){let o=i[e.id];o===void 0&&(g(e),o=u(e),i[e.id]=o,e.addEventListener(`dispose`,v));let s=n.program;r.updateUBOMapping(e,s);let c=t.render.frame;a[e.id]!==c&&(f(e),a[e.id]=c)}function u(t){let n=d();t.__bindingPointIndex=n;let r=e.createBuffer(),i=t.__size,a=t.usage;return e.bindBuffer(e.UNIFORM_BUFFER,r),e.bufferData(e.UNIFORM_BUFFER,i,a),e.bindBuffer(e.UNIFORM_BUFFER,null),e.bindBufferBase(e.UNIFORM_BUFFER,n,r),r}function d(){for(let e=0;e<s;e++)if(o.indexOf(e)===-1)return o.push(e),e;return na(`WebGLRenderer: Maximum number of simultaneously usable uniforms groups reached.`),0}function f(t){let n=i[t.id],r=t.uniforms,a=t.__cache;e.bindBuffer(e.UNIFORM_BUFFER,n);for(let e=0,t=r.length;e<t;e++){let t=r[e];if(Array.isArray(t))for(let n=0,r=t.length;n<r;n++)p(t[n],e,n,a);else p(t,e,0,a)}e.bindBuffer(e.UNIFORM_BUFFER,null)}function p(t,n,r,i){if(h(t,n,r,i)===!0){let n=t.__offset,r=t.value;if(Array.isArray(r)){let e=0;for(let n=0;n<r.length;n++){let i=r[n],a=_(i);m(i,t.__data,e),typeof i!=`number`&&typeof i!=`boolean`&&!i.isMatrix3&&!ArrayBuffer.isView(i)&&(e+=a.storage/Float32Array.BYTES_PER_ELEMENT)}}else m(r,t.__data,0);e.bufferSubData(e.UNIFORM_BUFFER,n,t.__data)}}function m(e,t,n){typeof e==`number`||typeof e==`boolean`?t[0]=e:e.isMatrix3?(t[0]=e.elements[0],t[1]=e.elements[1],t[2]=e.elements[2],t[3]=0,t[4]=e.elements[3],t[5]=e.elements[4],t[6]=e.elements[5],t[7]=0,t[8]=e.elements[6],t[9]=e.elements[7],t[10]=e.elements[8],t[11]=0):ArrayBuffer.isView(e)?t.set(new e.constructor(e.buffer,e.byteOffset,t.length)):e.toArray(t,n)}function h(e,t,n,r){let i=e.value,a=t+`_`+n;if(r[a]===void 0)return typeof i==`number`||typeof i==`boolean`?r[a]=i:ArrayBuffer.isView(i)?r[a]=i.slice():r[a]=i.clone(),!0;{let e=r[a];if(typeof i==`number`||typeof i==`boolean`){if(e!==i)return r[a]=i,!0}else if(ArrayBuffer.isView(i))return!0;else if(e.equals(i)===!1)return e.copy(i),!0}return!1}function g(e){let t=e.uniforms,n=0;for(let e=0,r=t.length;e<r;e++){let r=Array.isArray(t[e])?t[e]:[t[e]];for(let e=0,t=r.length;e<t;e++){let t=r[e],i=Array.isArray(t.value)?t.value:[t.value];for(let e=0,r=i.length;e<r;e++){let r=i[e],a=_(r),o=n%16,s=o%a.boundary,c=o+s;n+=s,c!==0&&16-c<a.storage&&(n+=16-c),t.__data=new Float32Array(a.storage/Float32Array.BYTES_PER_ELEMENT),t.__offset=n,n+=a.storage}}}let r=n%16;return r>0&&(n+=16-r),e.__size=n,e.__cache={},this}function _(e){let t={boundary:0,storage:0};return typeof e==`number`||typeof e==`boolean`?(t.boundary=4,t.storage=4):e.isVector2?(t.boundary=8,t.storage=8):e.isVector3||e.isColor?(t.boundary=16,t.storage=12):e.isVector4?(t.boundary=16,t.storage=16):e.isMatrix3?(t.boundary=48,t.storage=48):e.isMatrix4?(t.boundary=64,t.storage=64):e.isTexture?P(`WebGLRenderer: Texture samplers can not be part of an uniforms group.`):ArrayBuffer.isView(e)?(t.boundary=16,t.storage=e.byteLength):P(`WebGLRenderer: Unsupported uniform value type.`,e),t}function v(t){let n=t.target;n.removeEventListener(`dispose`,v);let r=o.indexOf(n.__bindingPointIndex);o.splice(r,1),e.deleteBuffer(i[n.id]),delete i[n.id],delete a[n.id]}function y(){for(let t in i)e.deleteBuffer(i[t]);o=[],i={},a={}}return{bind:c,update:l,dispose:y}}var C_=new Uint16Array([12469,15057,12620,14925,13266,14620,13807,14376,14323,13990,14545,13625,14713,13328,14840,12882,14931,12528,14996,12233,15039,11829,15066,11525,15080,11295,15085,10976,15082,10705,15073,10495,13880,14564,13898,14542,13977,14430,14158,14124,14393,13732,14556,13410,14702,12996,14814,12596,14891,12291,14937,11834,14957,11489,14958,11194,14943,10803,14921,10506,14893,10278,14858,9960,14484,14039,14487,14025,14499,13941,14524,13740,14574,13468,14654,13106,14743,12678,14818,12344,14867,11893,14889,11509,14893,11180,14881,10751,14852,10428,14812,10128,14765,9754,14712,9466,14764,13480,14764,13475,14766,13440,14766,13347,14769,13070,14786,12713,14816,12387,14844,11957,14860,11549,14868,11215,14855,10751,14825,10403,14782,10044,14729,9651,14666,9352,14599,9029,14967,12835,14966,12831,14963,12804,14954,12723,14936,12564,14917,12347,14900,11958,14886,11569,14878,11247,14859,10765,14828,10401,14784,10011,14727,9600,14660,9289,14586,8893,14508,8533,15111,12234,15110,12234,15104,12216,15092,12156,15067,12010,15028,11776,14981,11500,14942,11205,14902,10752,14861,10393,14812,9991,14752,9570,14682,9252,14603,8808,14519,8445,14431,8145,15209,11449,15208,11451,15202,11451,15190,11438,15163,11384,15117,11274,15055,10979,14994,10648,14932,10343,14871,9936,14803,9532,14729,9218,14645,8742,14556,8381,14461,8020,14365,7603,15273,10603,15272,10607,15267,10619,15256,10631,15231,10614,15182,10535,15118,10389,15042,10167,14963,9787,14883,9447,14800,9115,14710,8665,14615,8318,14514,7911,14411,7507,14279,7198,15314,9675,15313,9683,15309,9712,15298,9759,15277,9797,15229,9773,15166,9668,15084,9487,14995,9274,14898,8910,14800,8539,14697,8234,14590,7790,14479,7409,14367,7067,14178,6621,15337,8619,15337,8631,15333,8677,15325,8769,15305,8871,15264,8940,15202,8909,15119,8775,15022,8565,14916,8328,14804,8009,14688,7614,14569,7287,14448,6888,14321,6483,14088,6171,15350,7402,15350,7419,15347,7480,15340,7613,15322,7804,15287,7973,15229,8057,15148,8012,15046,7846,14933,7611,14810,7357,14682,7069,14552,6656,14421,6316,14251,5948,14007,5528,15356,5942,15356,5977,15353,6119,15348,6294,15332,6551,15302,6824,15249,7044,15171,7122,15070,7050,14949,6861,14818,6611,14679,6349,14538,6067,14398,5651,14189,5311,13935,4958,15359,4123,15359,4153,15356,4296,15353,4646,15338,5160,15311,5508,15263,5829,15188,6042,15088,6094,14966,6001,14826,5796,14678,5543,14527,5287,14377,4985,14133,4586,13869,4257,15360,1563,15360,1642,15358,2076,15354,2636,15341,3350,15317,4019,15273,4429,15203,4732,15105,4911,14981,4932,14836,4818,14679,4621,14517,4386,14359,4156,14083,3795,13808,3437,15360,122,15360,137,15358,285,15355,636,15344,1274,15322,2177,15281,2765,15215,3223,15120,3451,14995,3569,14846,3567,14681,3466,14511,3305,14344,3121,14037,2800,13753,2467,15360,0,15360,1,15359,21,15355,89,15346,253,15325,479,15287,796,15225,1148,15133,1492,15008,1749,14856,1882,14685,1886,14506,1783,14324,1608,13996,1398,13702,1183]),w_=null;function T_(){return w_===null&&(w_=new ir(C_,16,16,Le,an),w_.name=`DFG_LUT`,w_.minFilter=Me,w_.magFilter=Me,w_.wrapS=Ft,w_.wrapT=Ft,w_.generateMipmaps=!1,w_.needsUpdate=!0),w_}var E_=class{constructor(e={}){let{canvas:t=lr(),context:n=null,depth:r=!0,stencil:i=!1,alpha:o=!1,antialias:s=!1,premultipliedAlpha:c=!0,preserveDrawingBuffer:l=!1,powerPreference:u=`default`,failIfMajorPerformanceCaveat:d=!1,reversedDepthBuffer:f=!1,outputBufferType:p=se}=e;this.isWebGLRenderer=!0;let m;if(n!==null){if(typeof WebGLRenderingContext<`u`&&n instanceof WebGLRenderingContext)throw Error(`THREE.WebGLRenderer: WebGL 1 is not supported since r163.`);m=n.getContextAttributes().alpha}else m=o;let h=p,g=new Set([a,Ue,Oa]),_=new Set([se,en,it,yi,Jt,sn]),v=new Uint32Array(4),y=new Int32Array(4),b=new Y,x=null,S=null,C=[],w=[],T=null;this.domElement=t,this.debug={checkShaderErrors:!0,onShaderError:null},this.autoClear=!0,this.autoClearColor=!0,this.autoClearDepth=!0,this.autoClearStencil=!0,this.sortObjects=!0,this.clippingPlanes=[],this.localClippingEnabled=!1,this.toneMapping=0,this.toneMappingExposure=1,this.transmissionResolutionScale=1;let E=this,D=!1,O=null,k=null,ee=null,A=null;this._outputColorSpace=Yt;let te=0,j=0,M=null,N=-1,ne=null,re=new Hi,ie=new Hi,ae=null,oe=new kt(0),F=0,I=t.width,L=t.height,R=1,B=null,ce=null,le=new Hi(0,0,I,L),ue=new Hi(0,0,I,L),de=!1,fe=new me,pe=!1,V=!1,H=new ki,he=new Y,ge=new Hi,_e={background:null,fog:null,environment:null,overrideMaterial:null,isScene:!0},ve=!1;function ye(){return M===null?R:1}let U=n;function be(e,n){return t.getContext(e,n)}try{let e={alpha:!0,depth:r,stencil:i,antialias:s,premultipliedAlpha:c,preserveDrawingBuffer:l,powerPreference:u,failIfMajorPerformanceCaveat:d};if(`setAttribute`in t&&t.setAttribute(`data-engine`,`three.js r185`),t.addEventListener(`webglcontextlost`,q,!1),t.addEventListener(`webglcontextrestored`,We,!1),t.addEventListener(`webglcontextcreationerror`,J,!1),U===null){let t=`webgl2`;if(U=be(t,e),U===null)throw be(t)?Error(`THREE.WebGLRenderer: Error creating WebGL context with your selected attributes.`):Error(`THREE.WebGLRenderer: Error creating WebGL context.`)}}catch(e){throw na(`WebGLRenderer: `+e.message),e}let xe,Se,W,Ce,G,K,we,Te,Ee,De,Oe,ke,Ae,je,Me,Ne,Pe,Fe,Ie,Le,Re,ze,Be;function Ve(){xe=new Wm(U),xe.init(),Re=new m_(U,xe),Se=new bm(U,xe,e,Re),W=new f_(U,xe),Se.reversedDepthBuffer&&f&&W.buffers.depth.setReversed(!0),k=U.createFramebuffer(),ee=U.createFramebuffer(),A=U.createFramebuffer(),Ce=new qm(U),G=new Kg,K=new p_(U,xe,W,G,Se,Re,Ce),we=new Um(E),Te=new fm(U),ze=new vm(U,Te),Ee=new Gm(U,Te,Ce,ze),De=new Ym(U,Ee,Te,ze,Ce),Fe=new Jm(U,Se,K),Me=new xm(G),Oe=new Gg(E,we,xe,Se,ze,Me),ke=new x_(E,G),Ae=new Xg,je=new r_(xe),Pe=new _m(E,we,W,De,m,c),Ne=new d_(E,De,Se),Be=new S_(U,Ce,Se,W),Ie=new ym(U,xe,Ce),Le=new Km(U,xe,Ce),Ce.programs=Oe.programs,E.capabilities=Se,E.extensions=xe,E.properties=G,E.renderLists=Ae,E.shadowMap=Ne,E.state=W,E.info=Ce}Ve(),h!==1009&&(T=new Zm(h,t.width,t.height,s,r,i));let He=new v_(E,U);this.xr=He,this.getContext=function(){return U},this.getContextAttributes=function(){return U.getContextAttributes()},this.forceContextLoss=function(){let e=xe.get(`WEBGL_lose_context`);e&&e.loseContext()},this.forceContextRestore=function(){let e=xe.get(`WEBGL_lose_context`);e&&e.restoreContext()},this.getPixelRatio=function(){return R},this.setPixelRatio=function(e){e!==void 0&&(R=e,this.setSize(I,L,!1))},this.getSize=function(e){return e.set(I,L)},this.setSize=function(e,n,r=!0){if(He.isPresenting){P(`WebGLRenderer: Can't change size while VR device is presenting.`);return}I=e,L=n,t.width=Math.floor(e*R),t.height=Math.floor(n*R),r===!0&&(t.style.width=e+`px`,t.style.height=n+`px`),T!==null&&T.setSize(t.width,t.height),this.setViewport(0,0,e,n)},this.getDrawingBufferSize=function(e){return e.set(I*R,L*R).floor()},this.setDrawingBufferSize=function(e,n,r){I=e,L=n,R=r,t.width=Math.floor(e*r),t.height=Math.floor(n*r),this.setViewport(0,0,e,n)},this.setEffects=function(e){if(h===1009){na(`WebGLRenderer: setEffects() requires outputBufferType set to HalfFloatType or FloatType.`);return}if(e){for(let t=0;t<e.length;t++)if(e[t].isOutputPass===!0){P(`WebGLRenderer: OutputPass is not needed in setEffects(). Tone mapping and color space conversion are applied automatically.`);break}}T.setEffects(e||[])},this.getCurrentViewport=function(e){return e.copy(re)},this.getViewport=function(e){return e.copy(le)},this.setViewport=function(e,t,n,r){e.isVector4?le.set(e.x,e.y,e.z,e.w):le.set(e,t,n,r),W.viewport(re.copy(le).multiplyScalar(R).round())},this.getScissor=function(e){return e.copy(ue)},this.setScissor=function(e,t,n,r){e.isVector4?ue.set(e.x,e.y,e.z,e.w):ue.set(e,t,n,r),W.scissor(ie.copy(ue).multiplyScalar(R).round())},this.getScissorTest=function(){return de},this.setScissorTest=function(e){W.setScissorTest(de=e)},this.setOpaqueSort=function(e){B=e},this.setTransparentSort=function(e){ce=e},this.getClearColor=function(e){return e.copy(Pe.getClearColor())},this.setClearColor=function(){Pe.setClearColor(...arguments)},this.getClearAlpha=function(){return Pe.getClearAlpha()},this.setClearAlpha=function(){Pe.setClearAlpha(...arguments)},this.clear=function(e=!0,t=!0,n=!0){let r=0;if(e){let e=!1;if(M!==null){let t=M.texture.format;e=g.has(t)}if(e){let e=M.texture.type,t=_.has(e),n=Pe.getClearColor(),r=Pe.getClearAlpha(),i=n.r,a=n.g,o=n.b;t?(v[0]=i,v[1]=a,v[2]=o,v[3]=r,U.clearBufferuiv(U.COLOR,0,v)):(y[0]=i,y[1]=a,y[2]=o,y[3]=r,U.clearBufferiv(U.COLOR,0,y))}else r|=U.COLOR_BUFFER_BIT}t&&(r|=U.DEPTH_BUFFER_BIT,this.state.buffers.depth.setMask(!0)),n&&(r|=U.STENCIL_BUFFER_BIT,this.state.buffers.stencil.setMask(4294967295)),r!==0&&U.clear(r)},this.clearColor=function(){this.clear(!0,!1,!1)},this.clearDepth=function(){this.clear(!1,!0,!1)},this.clearStencil=function(){this.clear(!1,!1,!0)},this.setNodesHandler=function(e){e.setRenderer(this),O=e},this.dispose=function(){t.removeEventListener(`webglcontextlost`,q,!1),t.removeEventListener(`webglcontextrestored`,We,!1),t.removeEventListener(`webglcontextcreationerror`,J,!1),Pe.dispose(),Ae.dispose(),je.dispose(),G.dispose(),we.dispose(),De.dispose(),ze.dispose(),Be.dispose(),Oe.dispose(),He.dispose(),He.removeEventListener(`sessionstart`,Ze),He.removeEventListener(`sessionend`,Qe),$e.stop()};function q(e){e.preventDefault(),yt(`WebGLRenderer: Context Lost.`),D=!0}function We(){yt(`WebGLRenderer: Context Restored.`),D=!1;let e=Ce.autoReset,t=Ne.enabled,n=Ne.autoUpdate,r=Ne.needsUpdate,i=Ne.type;Ve(),Ce.autoReset=e,Ne.enabled=t,Ne.autoUpdate=n,Ne.needsUpdate=r,Ne.type=i}function J(e){na(`WebGLRenderer: A WebGL context could not be created. Reason: `,e.statusMessage)}function Ge(e){let t=e.target;t.removeEventListener(`dispose`,Ge),Ke(t)}function Ke(e){qe(e),G.remove(e)}function qe(e){let t=G.get(e).programs;t!==void 0&&(t.forEach(function(e){Oe.releaseProgram(e)}),e.isShaderMaterial&&Oe.releaseShaderCache(e))}this.renderBufferDirect=function(e,t,n,r,i,a){t===null&&(t=_e);let o=i.isMesh&&i.matrixWorld.determinantAffine()<0,s=ut(e,t,n,r,i);W.setMaterial(r,o);let c=n.index,l=1;if(r.wireframe===!0){if(c=Ee.getWireframeAttribute(n),c===void 0)return;l=2}let u=n.drawRange,d=n.attributes.position,f=u.start*l,p=(u.start+u.count)*l;a!==null&&(f=Math.max(f,a.start*l),p=Math.min(p,(a.start+a.count)*l)),c===null?d!=null&&(f=Math.max(f,0),p=Math.min(p,d.count)):(f=Math.max(f,0),p=Math.min(p,c.count));let m=p-f;if(m<0||m===1/0)return;ze.setup(i,r,s,n,c);let h,g=Ie;if(c!==null&&(h=Te.get(c),g=Le,g.setIndex(h)),i.isMesh)r.wireframe===!0?(W.setLineWidth(r.wireframeLinewidth*ye()),g.setMode(U.LINES)):g.setMode(U.TRIANGLES);else if(i.isLine){let e=r.linewidth;e===void 0&&(e=1),W.setLineWidth(e*ye()),i.isLineSegments?g.setMode(U.LINES):i.isLineLoop?g.setMode(U.LINE_LOOP):g.setMode(U.LINE_STRIP)}else i.isPoints?g.setMode(U.POINTS):i.isSprite&&g.setMode(U.TRIANGLES);if(i.isBatchedMesh)if(xe.get(`WEBGL_multi_draw`))g.renderMultiDraw(i._multiDrawStarts,i._multiDrawCounts,i._multiDrawCount);else{let e=i._multiDrawStarts,t=i._multiDrawCounts,n=i._multiDrawCount,a=c?Te.get(c).bytesPerElement:1,o=G.get(r).currentProgram.getUniforms();for(let r=0;r<n;r++)o.setValue(U,`_gl_DrawID`,r),g.render(e[r]/a,t[r])}else if(i.isInstancedMesh)g.renderInstances(f,m,i.count);else if(n.isInstancedBufferGeometry){let e=n._maxInstanceCount===void 0?1/0:n._maxInstanceCount,t=Math.min(n.instanceCount,e);g.renderInstances(f,m,t)}else g.render(f,m)};function Je(e,t,n){e.transparent===!0&&e.side===2&&e.forceSinglePass===!1?(e.side=1,e.needsUpdate=!0,ot(e,t,n),e.side=0,e.needsUpdate=!0,ot(e,t,n),e.side=2):ot(e,t,n)}this.compile=function(e,t,n=null){n===null&&(n=e),S=je.get(n),S.init(t),w.push(S),n.traverseVisible(function(e){e.isLight&&e.layers.test(t.layers)&&(S.pushLight(e),e.castShadow&&S.pushShadow(e))}),e!==n&&e.traverseVisible(function(e){e.isLight&&e.layers.test(t.layers)&&(S.pushLight(e),e.castShadow&&S.pushShadow(e))}),S.setupLights();let r=new Set;return e.traverse(function(e){if(!(e.isMesh||e.isPoints||e.isLine||e.isSprite))return;let t=e.material;if(t)if(Array.isArray(t))for(let i=0;i<t.length;i++){let a=t[i];Je(a,n,e),r.add(a)}else Je(t,n,e),r.add(t)}),S=w.pop(),r},this.compileAsync=function(e,t,n=null){let r=this.compile(e,t,n);return new Promise(t=>{function n(){if(r.forEach(function(e){G.get(e).currentProgram.isReady()&&r.delete(e)}),r.size===0){t(e);return}setTimeout(n,10)}xe.get(`KHR_parallel_shader_compile`)===null?setTimeout(n,10):n()})};let Ye=null;function Xe(e){Ye&&Ye(e)}function Ze(){$e.stop()}function Qe(){$e.start()}let $e=new dm;$e.setAnimationLoop(Xe),typeof self<`u`&&$e.setContext(self),this.setAnimationLoop=function(e){Ye=e,He.setAnimationLoop(e),e===null?$e.stop():$e.start()},He.addEventListener(`sessionstart`,Ze),He.addEventListener(`sessionend`,Qe),this.render=function(e,t){if(t!==void 0&&t.isCamera!==!0){na(`WebGLRenderer.render: camera is not an instance of THREE.Camera.`);return}if(D===!0)return;O!==null&&O.renderStart(e,t);let n=He.enabled===!0&&He.isPresenting===!0,r=T!==null&&(M===null||n)&&T.begin(E,M);if(e.matrixWorldAutoUpdate===!0&&e.updateMatrixWorld(),t.parent===null&&t.matrixWorldAutoUpdate===!0&&t.updateMatrixWorld(),He.enabled===!0&&He.isPresenting===!0&&(T===null||T.isCompositing()===!1)&&(He.cameraAutoUpdate===!0&&He.updateCamera(t),t=He.getCamera()),e.isScene===!0&&e.onBeforeRender(E,e,t,M),S=je.get(e,w.length),S.init(t),S.state.textureUnits=K.getTextureUnits(),w.push(S),H.multiplyMatrices(t.projectionMatrix,t.matrixWorldInverse),fe.setFromProjectionMatrix(H,Fi,t.reversedDepth),V=this.localClippingEnabled,pe=Me.init(this.clippingPlanes,V),x=Ae.get(e,C.length),x.init(),C.push(x),He.enabled===!0&&He.isPresenting===!0){let e=E.xr.getDepthSensingMesh();e!==null&&et(e,t,-1/0,E.sortObjects)}et(e,t,0,E.sortObjects),x.finish(),E.sortObjects===!0&&x.sort(B,ce,t.reversedDepth),ve=He.enabled===!1||He.isPresenting===!1||He.hasDepthSensing()===!1,ve&&Pe.addToRenderList(x,e),this.info.render.frame++,this.info.autoReset===!0&&this.info.reset(),pe===!0&&Me.beginShadows();let i=S.state.shadowsArray;if(Ne.render(i,e,t),pe===!0&&Me.endShadows(),(r&&T.hasRenderPass())===!1){let n=x.opaque,r=x.transmissive;if(S.setupLights(),t.isArrayCamera){let i=t.cameras;if(r.length>0)for(let t=0,a=i.length;t<a;t++){let a=i[t];nt(n,r,e,a)}ve&&Pe.render(e);for(let t=0,n=i.length;t<n;t++){let n=i[t];tt(x,e,n,n.viewport)}}else r.length>0&&nt(n,r,e,t),ve&&Pe.render(e),tt(x,e,t)}M!==null&&j===0&&(K.updateMultisampleRenderTarget(M),K.updateRenderTargetMipmap(M)),r&&T.end(E),e.isScene===!0&&e.onAfterRender(E,e,t),ze.resetDefaultState(),N=-1,ne=null,w.pop(),w.length>0?(S=w[w.length-1],K.setTextureUnits(S.state.textureUnits),pe===!0&&Me.setGlobalState(E.clippingPlanes,S.state.camera)):S=null,C.pop(),x=C.length>0?C[C.length-1]:null,O!==null&&O.renderEnd()};function et(e,t,n,r){if(e.visible===!1)return;if(e.layers.test(t.layers)){if(e.isGroup)n=e.renderOrder;else if(e.isLOD)e.autoUpdate===!0&&e.update(t);else if(e.isLightProbeGrid)S.pushLightProbeGrid(e);else if(e.isLight)S.pushLight(e),e.castShadow&&S.pushShadow(e);else if(e.isSprite){if(!e.frustumCulled||fe.intersectsSprite(e)){r&&ge.setFromMatrixPosition(e.matrixWorld).applyMatrix4(H);let t=De.update(e),i=e.material;i.visible&&x.push(e,t,i,n,ge.z,null)}}else if((e.isMesh||e.isLine||e.isPoints)&&(!e.frustumCulled||fe.intersectsObject(e))){let t=De.update(e),i=e.material;if(r&&(e.boundingSphere===void 0?(t.boundingSphere===null&&t.computeBoundingSphere(),ge.copy(t.boundingSphere.center)):(e.boundingSphere===null&&e.computeBoundingSphere(),ge.copy(e.boundingSphere.center)),ge.applyMatrix4(e.matrixWorld).applyMatrix4(H)),Array.isArray(i)){let r=t.groups;for(let a=0,o=r.length;a<o;a++){let o=r[a],s=i[o.materialIndex];s&&s.visible&&x.push(e,t,s,n,ge.z,o)}}else i.visible&&x.push(e,t,i,n,ge.z,null)}}let i=e.children;for(let e=0,a=i.length;e<a;e++)et(i[e],t,n,r)}function tt(e,t,n,r){let{opaque:i,transmissive:a,transparent:o}=e;S.setupLightsView(n),pe===!0&&Me.setGlobalState(E.clippingPlanes,n),r&&W.viewport(re.copy(r)),i.length>0&&rt(i,t,n),a.length>0&&rt(a,t,n),o.length>0&&rt(o,t,n),W.buffers.depth.setTest(!0),W.buffers.depth.setMask(!0),W.buffers.color.setMask(!0),W.setPolygonOffset(!1)}function nt(e,t,n,r){if((n.isScene===!0?n.overrideMaterial:null)!==null)return;if(S.state.transmissionRenderTarget[r.id]===void 0){let e=xe.has(`EXT_color_buffer_half_float`)||xe.has(`EXT_color_buffer_float`);S.state.transmissionRenderTarget[r.id]=new Ln(1,1,{generateMipmaps:!0,type:e?an:se,minFilter:Rt,samples:Math.max(4,Se.samples),stencilBuffer:i,resolveDepthBuffer:!1,resolveStencilBuffer:!1,colorSpace:z.workingColorSpace})}let a=S.state.transmissionRenderTarget[r.id],o=r.viewport||re;a.setSize(o.z*E.transmissionResolutionScale,o.w*E.transmissionResolutionScale);let s=E.getRenderTarget(),c=E.getActiveCubeFace(),l=E.getActiveMipmapLevel();E.setRenderTarget(a),E.getClearColor(oe),F=E.getClearAlpha(),F<1&&E.setClearColor(16777215,.5),E.clear(),ve&&Pe.render(n);let u=E.toneMapping;E.toneMapping=0;let d=r.viewport;if(r.viewport!==void 0&&(r.viewport=void 0),S.setupLightsView(r),pe===!0&&Me.setGlobalState(E.clippingPlanes,r),rt(e,n,r),K.updateMultisampleRenderTarget(a),K.updateRenderTargetMipmap(a),xe.has(`WEBGL_multisampled_render_to_texture`)===!1){let e=!1;for(let i=0,a=t.length;i<a;i++){let{object:a,geometry:o,material:s,group:c}=t[i];if(s.side===2&&a.layers.test(r.layers)){let t=s.side;s.side=1,s.needsUpdate=!0,at(a,n,r,o,s,c),s.side=t,s.needsUpdate=!0,e=!0}}e===!0&&(K.updateMultisampleRenderTarget(a),K.updateRenderTargetMipmap(a))}E.setRenderTarget(s,c,l),E.setClearColor(oe,F),d!==void 0&&(r.viewport=d),E.toneMapping=u}function rt(e,t,n){let r=t.isScene===!0?t.overrideMaterial:null;for(let i=0,a=e.length;i<a;i++){let a=e[i],{object:o,geometry:s,group:c}=a,l=a.material;l.allowOverride===!0&&r!==null&&(l=r),o.layers.test(n.layers)&&at(o,t,n,s,l,c)}}function at(e,t,n,r,i,a){e.onBeforeRender(E,t,n,r,i,a),e.modelViewMatrix.multiplyMatrices(n.matrixWorldInverse,e.matrixWorld),e.normalMatrix.getNormalMatrix(e.modelViewMatrix),i.onBeforeRender(E,t,n,r,e,a),i.transparent===!0&&i.side===2&&i.forceSinglePass===!1?(i.side=1,i.needsUpdate=!0,E.renderBufferDirect(n,t,r,i,e,a),i.side=0,i.needsUpdate=!0,E.renderBufferDirect(n,t,r,i,e,a),i.side=2):E.renderBufferDirect(n,t,r,i,e,a),e.onAfterRender(E,t,n,r,i,a)}function ot(e,t,n){t.isScene!==!0&&(t=_e);let r=G.get(e),i=S.state.lights,a=S.state.shadowsArray,o=i.state.version,s=Oe.getParameters(e,i.state,a,t,n,S.state.lightProbeGridArray),c=Oe.getProgramCacheKey(s),l=r.programs;r.environment=e.isMeshStandardMaterial||e.isMeshLambertMaterial||e.isMeshPhongMaterial?t.environment:null,r.fog=t.fog;let u=e.isMeshStandardMaterial||e.isMeshLambertMaterial&&!e.envMap||e.isMeshPhongMaterial&&!e.envMap;r.envMap=we.get(e.envMap||r.environment,u),r.envMapRotation=r.environment!==null&&e.envMap===null?t.environmentRotation:e.envMapRotation,l===void 0&&(e.addEventListener(`dispose`,Ge),l=new Map,r.programs=l);let d=l.get(c);if(d!==void 0){if(r.currentProgram===d&&r.lightsStateVersion===o)return ct(e,s),d}else s.uniforms=Oe.getUniforms(e),O!==null&&e.isNodeMaterial&&O.build(e,n,s),e.onBeforeCompile(s,E),d=Oe.acquireProgram(s,c),l.set(c,d),r.uniforms=s.uniforms;let f=r.uniforms;return(!e.isShaderMaterial&&!e.isRawShaderMaterial||e.clipping===!0)&&(f.clippingPlanes=Me.uniform),ct(e,s),r.needsLights=ft(e),r.lightsStateVersion=o,r.needsLights&&(f.ambientLightColor.value=i.state.ambient,f.lightProbe.value=i.state.probe,f.directionalLights.value=i.state.directional,f.directionalLightShadows.value=i.state.directionalShadow,f.spotLights.value=i.state.spot,f.spotLightShadows.value=i.state.spotShadow,f.rectAreaLights.value=i.state.rectArea,f.ltc_1.value=i.state.rectAreaLTC1,f.ltc_2.value=i.state.rectAreaLTC2,f.pointLights.value=i.state.point,f.pointLightShadows.value=i.state.pointShadow,f.hemisphereLights.value=i.state.hemi,f.directionalShadowMatrix.value=i.state.directionalShadowMatrix,f.spotLightMatrix.value=i.state.spotLightMatrix,f.spotLightMap.value=i.state.spotLightMap,f.pointShadowMatrix.value=i.state.pointShadowMatrix),r.lightProbeGrid=S.state.lightProbeGridArray.length>0,r.currentProgram=d,r.uniformsList=null,d}function st(e){if(e.uniformsList===null){let t=e.currentProgram.getUniforms();e.uniformsList=ig.seqWithValue(t.seq,e.uniforms)}return e.uniformsList}function ct(e,t){let n=G.get(e);n.outputColorSpace=t.outputColorSpace,n.batching=t.batching,n.batchingColor=t.batchingColor,n.instancing=t.instancing,n.instancingColor=t.instancingColor,n.instancingMorph=t.instancingMorph,n.skinning=t.skinning,n.morphTargets=t.morphTargets,n.morphNormals=t.morphNormals,n.morphColors=t.morphColors,n.morphTargetsCount=t.morphTargetsCount,n.numClippingPlanes=t.numClippingPlanes,n.numIntersection=t.numClipIntersection,n.vertexAlphas=t.vertexAlphas,n.vertexTangents=t.vertexTangents,n.toneMapping=t.toneMapping}function lt(e,t){if(e.length===0)return null;if(e.length===1)return e[0].texture===null?null:e[0];b.setFromMatrixPosition(t.matrixWorld);for(let t=0,n=e.length;t<n;t++){let n=e[t];if(n.texture!==null&&n.boundingBox.containsPoint(b))return n}return null}function ut(e,t,n,r,i){t.isScene!==!0&&(t=_e),K.resetTextureUnits();let a=t.fog,o=r.isMeshStandardMaterial||r.isMeshLambertMaterial||r.isMeshPhongMaterial?t.environment:null,s=M===null?E.outputColorSpace:M.isXRRenderTarget===!0?M.texture.colorSpace:z.workingColorSpace,c=r.isMeshStandardMaterial||r.isMeshLambertMaterial&&!r.envMap||r.isMeshPhongMaterial&&!r.envMap,l=we.get(r.envMap||o,c),u=r.vertexColors===!0&&!!n.attributes.color&&n.attributes.color.itemSize===4,d=!!n.attributes.tangent&&(!!r.normalMap||r.anisotropy>0),f=!!n.morphAttributes.position,p=!!n.morphAttributes.normal,m=!!n.morphAttributes.color,h=0;r.toneMapped&&(M===null||M.isXRRenderTarget===!0)&&(h=E.toneMapping);let g=n.morphAttributes.position||n.morphAttributes.normal||n.morphAttributes.color,_=g===void 0?0:g.length,v=G.get(r),y=S.state.lights;if(pe===!0&&(V===!0||e!==ne)){let t=e===ne&&r.id===N;Me.setState(r,e,t)}let b=!1;r.version===v.__version?v.needsLights&&v.lightsStateVersion!==y.state.version?b=!0:v.outputColorSpace===s?i.isBatchedMesh&&v.batching===!1||!i.isBatchedMesh&&v.batching===!0||i.isBatchedMesh&&v.batchingColor===!0&&i.colorTexture===null||i.isBatchedMesh&&v.batchingColor===!1&&i.colorTexture!==null||i.isInstancedMesh&&v.instancing===!1||!i.isInstancedMesh&&v.instancing===!0||i.isSkinnedMesh&&v.skinning===!1||!i.isSkinnedMesh&&v.skinning===!0||i.isInstancedMesh&&v.instancingColor===!0&&i.instanceColor===null||i.isInstancedMesh&&v.instancingColor===!1&&i.instanceColor!==null||i.isInstancedMesh&&v.instancingMorph===!0&&i.morphTexture===null||i.isInstancedMesh&&v.instancingMorph===!1&&i.morphTexture!==null?b=!0:v.envMap===l?r.fog===!0&&v.fog!==a||v.numClippingPlanes!==void 0&&(v.numClippingPlanes!==Me.numPlanes||v.numIntersection!==Me.numIntersection)?b=!0:v.vertexAlphas===u&&v.vertexTangents===d&&v.morphTargets===f&&v.morphNormals===p&&v.morphColors===m&&v.toneMapping===h&&v.morphTargetsCount===_?!!v.lightProbeGrid!=S.state.lightProbeGridArray.length>0&&(b=!0):b=!0:b=!0:b=!0:(b=!0,v.__version=r.version);let x=v.currentProgram;b===!0&&(x=ot(r,t,i),O&&r.isNodeMaterial&&O.onUpdateProgram(r,x,v));let C=!1,w=!1,T=!1,D=x.getUniforms(),k=v.uniforms;if(W.useProgram(x.program)&&(C=!0,w=!0,T=!0),r.id!==N&&(N=r.id,w=!0),v.needsLights){let e=lt(S.state.lightProbeGridArray,i);v.lightProbeGrid!==e&&(v.lightProbeGrid=e,w=!0)}if(C||ne!==e){W.buffers.depth.getReversed()&&e.reversedDepth!==!0&&(e._reversedDepth=!0,e.updateProjectionMatrix()),D.setValue(U,`projectionMatrix`,e.projectionMatrix),D.setValue(U,`viewMatrix`,e.matrixWorldInverse);let t=D.map.cameraPosition;t!==void 0&&t.setValue(U,he.setFromMatrixPosition(e.matrixWorld)),Se.logarithmicDepthBuffer&&D.setValue(U,`logDepthBufFC`,2/(Math.log(e.far+1)/Math.LN2)),(r.isMeshPhongMaterial||r.isMeshToonMaterial||r.isMeshLambertMaterial||r.isMeshBasicMaterial||r.isMeshStandardMaterial||r.isShaderMaterial)&&D.setValue(U,`isOrthographic`,e.isOrthographicCamera===!0),ne!==e&&(ne=e,w=!0,T=!0)}if(v.needsLights&&(y.state.directionalShadowMap.length>0&&D.setValue(U,`directionalShadowMap`,y.state.directionalShadowMap,K),y.state.spotShadowMap.length>0&&D.setValue(U,`spotShadowMap`,y.state.spotShadowMap,K),y.state.pointShadowMap.length>0&&D.setValue(U,`pointShadowMap`,y.state.pointShadowMap,K)),i.isSkinnedMesh){D.setOptional(U,i,`bindMatrix`),D.setOptional(U,i,`bindMatrixInverse`);let e=i.skeleton;e&&(e.boneTexture===null&&e.computeBoneTexture(),D.setValue(U,`boneTexture`,e.boneTexture,K))}i.isBatchedMesh&&(D.setOptional(U,i,`batchingTexture`),D.setValue(U,`batchingTexture`,i._matricesTexture,K),D.setOptional(U,i,`batchingIdTexture`),D.setValue(U,`batchingIdTexture`,i._indirectTexture,K),D.setOptional(U,i,`batchingColorTexture`),i._colorsTexture!==null&&D.setValue(U,`batchingColorTexture`,i._colorsTexture,K));let ee=n.morphAttributes;if((ee.position!==void 0||ee.normal!==void 0||ee.color!==void 0)&&Fe.update(i,n,x),(w||v.receiveShadow!==i.receiveShadow)&&(v.receiveShadow=i.receiveShadow,D.setValue(U,`receiveShadow`,i.receiveShadow)),(r.isMeshStandardMaterial||r.isMeshLambertMaterial||r.isMeshPhongMaterial)&&r.envMap===null&&t.environment!==null&&(k.envMapIntensity.value=t.environmentIntensity),k.dfgLUT!==void 0&&(k.dfgLUT.value=T_()),w){if(D.setValue(U,`toneMappingExposure`,E.toneMappingExposure),v.needsLights&&dt(k,T),a&&r.fog===!0&&ke.refreshFogUniforms(k,a),ke.refreshMaterialUniforms(k,r,R,L,S.state.transmissionRenderTarget[e.id]),v.needsLights&&v.lightProbeGrid){let e=v.lightProbeGrid;k.probesSH.value=e.texture,k.probesMin.value.copy(e.boundingBox.min),k.probesMax.value.copy(e.boundingBox.max),k.probesResolution.value.copy(e.resolution)}ig.upload(U,st(v),k,K)}if(r.isShaderMaterial&&r.uniformsNeedUpdate===!0&&(ig.upload(U,st(v),k,K),r.uniformsNeedUpdate=!1),r.isSpriteMaterial&&D.setValue(U,`center`,i.center),D.setValue(U,`modelViewMatrix`,i.modelViewMatrix),D.setValue(U,`normalMatrix`,i.normalMatrix),D.setValue(U,`modelMatrix`,i.matrixWorld),r.uniformsGroups!==void 0){let e=r.uniformsGroups;for(let t=0,n=e.length;t<n;t++){let n=e[t];Be.update(n,x),Be.bind(n,x)}}return x}function dt(e,t){e.ambientLightColor.needsUpdate=t,e.lightProbe.needsUpdate=t,e.directionalLights.needsUpdate=t,e.directionalLightShadows.needsUpdate=t,e.pointLights.needsUpdate=t,e.pointLightShadows.needsUpdate=t,e.spotLights.needsUpdate=t,e.spotLightShadows.needsUpdate=t,e.rectAreaLights.needsUpdate=t,e.hemisphereLights.needsUpdate=t}function ft(e){return e.isMeshLambertMaterial||e.isMeshToonMaterial||e.isMeshPhongMaterial||e.isMeshStandardMaterial||e.isShadowMaterial||e.isShaderMaterial&&e.lights===!0}this.getActiveCubeFace=function(){return te},this.getActiveMipmapLevel=function(){return j},this.getRenderTarget=function(){return M},this.setRenderTargetTextures=function(e,t,n){let r=G.get(e);r.__autoAllocateDepthBuffer=e.resolveDepthBuffer===!1,r.__autoAllocateDepthBuffer===!1&&(r.__useRenderToTexture=!1),G.get(e.texture).__webglTexture=t,G.get(e.depthTexture).__webglTexture=r.__autoAllocateDepthBuffer?void 0:n,r.__hasExternalTextures=!0},this.setRenderTargetFramebuffer=function(e,t){let n=G.get(e);n.__webglFramebuffer=t,n.__useDefaultFramebuffer=t===void 0},this.setRenderTarget=function(e,t=0,n=0){M=e,te=t,j=n;let r=null,i=!1,a=!1;if(e){let o=G.get(e);if(o.__useDefaultFramebuffer!==void 0){W.bindFramebuffer(U.FRAMEBUFFER,o.__webglFramebuffer),re.copy(e.viewport),ie.copy(e.scissor),ae=e.scissorTest,W.viewport(re),W.scissor(ie),W.setScissorTest(ae),N=-1;return}else if(o.__webglFramebuffer===void 0)K.setupRenderTarget(e);else if(o.__hasExternalTextures)K.rebindTextures(e,G.get(e.texture).__webglTexture,G.get(e.depthTexture).__webglTexture);else if(e.depthBuffer){let t=e.depthTexture;if(o.__boundDepthTexture!==t){if(t!==null&&G.has(t)&&(e.width!==t.image.width||e.height!==t.image.height))throw Error(`THREE.WebGLRenderer: Attached DepthTexture is initialized to the incorrect size.`);K.setupDepthRenderbuffer(e)}}let s=e.texture;(s.isData3DTexture||s.isDataArrayTexture||s.isCompressedArrayTexture)&&(a=!0);let c=G.get(e).__webglFramebuffer;e.isWebGLCubeRenderTarget?(r=Array.isArray(c[t])?c[t][n]:c[t],i=!0):r=e.samples>0&&K.useMultisampledRTT(e)===!1?G.get(e).__webglMultisampledFramebuffer:Array.isArray(c)?c[n]:c,re.copy(e.viewport),ie.copy(e.scissor),ae=e.scissorTest}else re.copy(le).multiplyScalar(R).floor(),ie.copy(ue).multiplyScalar(R).floor(),ae=de;if(n!==0&&(r=k),W.bindFramebuffer(U.FRAMEBUFFER,r)&&W.drawBuffers(e,r),W.viewport(re),W.scissor(ie),W.setScissorTest(ae),i){let r=G.get(e.texture);U.framebufferTexture2D(U.FRAMEBUFFER,U.COLOR_ATTACHMENT0,U.TEXTURE_CUBE_MAP_POSITIVE_X+t,r.__webglTexture,n)}else if(a){let r=t;for(let t=0;t<e.textures.length;t++){let i=G.get(e.textures[t]);U.framebufferTextureLayer(U.FRAMEBUFFER,U.COLOR_ATTACHMENT0+t,i.__webglTexture,n,r)}}else if(e!==null&&n!==0){let t=G.get(e.texture);U.framebufferTexture2D(U.FRAMEBUFFER,U.COLOR_ATTACHMENT0,U.TEXTURE_2D,t.__webglTexture,n)}N=-1},this.readRenderTargetPixels=function(e,t,n,r,i,a,o,s=0){if(!(e&&e.isWebGLRenderTarget)){na(`WebGLRenderer.readRenderTargetPixels: renderTarget is not THREE.WebGLRenderTarget.`);return}let c=G.get(e).__webglFramebuffer;if(e.isWebGLCubeRenderTarget&&o!==void 0&&(c=c[o]),c){W.bindFramebuffer(U.FRAMEBUFFER,c);try{let o=e.textures[s],c=o.format,l=o.type;if(e.textures.length>1&&U.readBuffer(U.COLOR_ATTACHMENT0+s),!Se.textureFormatReadable(c)){na(`WebGLRenderer.readRenderTargetPixels: renderTarget is not in RGBA or implementation defined format.`);return}if(!Se.textureTypeReadable(l)){na(`WebGLRenderer.readRenderTargetPixels: renderTarget is not in UnsignedByteType or implementation defined type.`);return}t>=0&&t<=e.width-r&&n>=0&&n<=e.height-i&&U.readPixels(t,n,r,i,Re.convert(c),Re.convert(l),a)}finally{let e=M===null?null:G.get(M).__webglFramebuffer;W.bindFramebuffer(U.FRAMEBUFFER,e)}}},this.readRenderTargetPixelsAsync=async function(e,t,n,r,i,a,o,s=0){if(!(e&&e.isWebGLRenderTarget))throw Error(`THREE.WebGLRenderer.readRenderTargetPixels: renderTarget is not THREE.WebGLRenderTarget.`);let c=G.get(e).__webglFramebuffer;if(e.isWebGLCubeRenderTarget&&o!==void 0&&(c=c[o]),c)if(t>=0&&t<=e.width-r&&n>=0&&n<=e.height-i){W.bindFramebuffer(U.FRAMEBUFFER,c);let o=e.textures[s],l=o.format,u=o.type;if(e.textures.length>1&&U.readBuffer(U.COLOR_ATTACHMENT0+s),!Se.textureFormatReadable(l))throw Error(`THREE.WebGLRenderer.readRenderTargetPixelsAsync: renderTarget is not in RGBA or implementation defined format.`);if(!Se.textureTypeReadable(u))throw Error(`THREE.WebGLRenderer.readRenderTargetPixelsAsync: renderTarget is not in UnsignedByteType or implementation defined type.`);let d=U.createBuffer();U.bindBuffer(U.PIXEL_PACK_BUFFER,d),U.bufferData(U.PIXEL_PACK_BUFFER,a.byteLength,U.STREAM_READ),U.readPixels(t,n,r,i,Re.convert(l),Re.convert(u),0);let f=M===null?null:G.get(M).__webglFramebuffer;W.bindFramebuffer(U.FRAMEBUFFER,f);let p=U.fenceSync(U.SYNC_GPU_COMMANDS_COMPLETE,0);return U.flush(),await la(U,p,4),U.bindBuffer(U.PIXEL_PACK_BUFFER,d),U.getBufferSubData(U.PIXEL_PACK_BUFFER,0,a),U.deleteBuffer(d),U.deleteSync(p),a}else throw Error(`THREE.WebGLRenderer.readRenderTargetPixelsAsync: requested read bounds are out of range.`)},this.copyFramebufferToTexture=function(e,t=null,n=0){let r=2**-n,i=Math.floor(e.image.width*r),a=Math.floor(e.image.height*r),o=t===null?0:t.x,s=t===null?0:t.y;K.setTexture2D(e,0),U.copyTexSubImage2D(U.TEXTURE_2D,n,0,0,o,s,i,a),W.unbindTexture()},this.copyTextureToTexture=function(e,t,n=null,r=null,i=0,a=0){let o,s,c,l,u,d,f,p,m,h=e.isCompressedTexture?e.mipmaps[a]:e.image;if(n!==null)o=n.max.x-n.min.x,s=n.max.y-n.min.y,c=n.isBox3?n.max.z-n.min.z:1,l=n.min.x,u=n.min.y,d=n.isBox3?n.min.z:0;else{let t=2**-i;o=Math.floor(h.width*t),s=Math.floor(h.height*t),c=e.isDataArrayTexture?h.depth:e.isData3DTexture?Math.floor(h.depth*t):1,l=0,u=0,d=0}r===null?(f=0,p=0,m=0):(f=r.x,p=r.y,m=r.z);let g=Re.convert(t.format),_=Re.convert(t.type),v;t.isData3DTexture?(K.setTexture3D(t,0),v=U.TEXTURE_3D):t.isDataArrayTexture||t.isCompressedArrayTexture?(K.setTexture2DArray(t,0),v=U.TEXTURE_2D_ARRAY):(K.setTexture2D(t,0),v=U.TEXTURE_2D),W.activeTexture(U.TEXTURE0),W.pixelStorei(U.UNPACK_FLIP_Y_WEBGL,t.flipY),W.pixelStorei(U.UNPACK_PREMULTIPLY_ALPHA_WEBGL,t.premultiplyAlpha),W.pixelStorei(U.UNPACK_ALIGNMENT,t.unpackAlignment);let y=W.getParameter(U.UNPACK_ROW_LENGTH),b=W.getParameter(U.UNPACK_IMAGE_HEIGHT),x=W.getParameter(U.UNPACK_SKIP_PIXELS),S=W.getParameter(U.UNPACK_SKIP_ROWS),C=W.getParameter(U.UNPACK_SKIP_IMAGES);W.pixelStorei(U.UNPACK_ROW_LENGTH,h.width),W.pixelStorei(U.UNPACK_IMAGE_HEIGHT,h.height),W.pixelStorei(U.UNPACK_SKIP_PIXELS,l),W.pixelStorei(U.UNPACK_SKIP_ROWS,u),W.pixelStorei(U.UNPACK_SKIP_IMAGES,d);let w=e.isDataArrayTexture||e.isData3DTexture,T=t.isDataArrayTexture||t.isData3DTexture;if(e.isDepthTexture){let n=G.get(e),r=G.get(t),h=G.get(n.__renderTarget),g=G.get(r.__renderTarget);W.bindFramebuffer(U.READ_FRAMEBUFFER,h.__webglFramebuffer),W.bindFramebuffer(U.DRAW_FRAMEBUFFER,g.__webglFramebuffer);for(let n=0;n<c;n++)w&&(U.framebufferTextureLayer(U.READ_FRAMEBUFFER,U.COLOR_ATTACHMENT0,G.get(e).__webglTexture,i,d+n),U.framebufferTextureLayer(U.DRAW_FRAMEBUFFER,U.COLOR_ATTACHMENT0,G.get(t).__webglTexture,a,m+n)),U.blitFramebuffer(l,u,o,s,f,p,o,s,U.DEPTH_BUFFER_BIT,U.NEAREST);W.bindFramebuffer(U.READ_FRAMEBUFFER,null),W.bindFramebuffer(U.DRAW_FRAMEBUFFER,null)}else if(i!==0||e.isRenderTargetTexture||G.has(e)){let n=G.get(e),r=G.get(t);W.bindFramebuffer(U.READ_FRAMEBUFFER,ee),W.bindFramebuffer(U.DRAW_FRAMEBUFFER,A);for(let e=0;e<c;e++)w?U.framebufferTextureLayer(U.READ_FRAMEBUFFER,U.COLOR_ATTACHMENT0,n.__webglTexture,i,d+e):U.framebufferTexture2D(U.READ_FRAMEBUFFER,U.COLOR_ATTACHMENT0,U.TEXTURE_2D,n.__webglTexture,i),T?U.framebufferTextureLayer(U.DRAW_FRAMEBUFFER,U.COLOR_ATTACHMENT0,r.__webglTexture,a,m+e):U.framebufferTexture2D(U.DRAW_FRAMEBUFFER,U.COLOR_ATTACHMENT0,U.TEXTURE_2D,r.__webglTexture,a),i===0?T?U.copyTexSubImage3D(v,a,f,p,m+e,l,u,o,s):U.copyTexSubImage2D(v,a,f,p,l,u,o,s):U.blitFramebuffer(l,u,o,s,f,p,o,s,U.COLOR_BUFFER_BIT,U.NEAREST);W.bindFramebuffer(U.READ_FRAMEBUFFER,null),W.bindFramebuffer(U.DRAW_FRAMEBUFFER,null)}else T?e.isDataTexture||e.isData3DTexture?U.texSubImage3D(v,a,f,p,m,o,s,c,g,_,h.data):t.isCompressedArrayTexture?U.compressedTexSubImage3D(v,a,f,p,m,o,s,c,g,h.data):U.texSubImage3D(v,a,f,p,m,o,s,c,g,_,h):e.isDataTexture?U.texSubImage2D(U.TEXTURE_2D,a,f,p,o,s,g,_,h.data):e.isCompressedTexture?U.compressedTexSubImage2D(U.TEXTURE_2D,a,f,p,h.width,h.height,g,h.data):U.texSubImage2D(U.TEXTURE_2D,a,f,p,o,s,g,_,h);W.pixelStorei(U.UNPACK_ROW_LENGTH,y),W.pixelStorei(U.UNPACK_IMAGE_HEIGHT,b),W.pixelStorei(U.UNPACK_SKIP_PIXELS,x),W.pixelStorei(U.UNPACK_SKIP_ROWS,S),W.pixelStorei(U.UNPACK_SKIP_IMAGES,C),a===0&&t.generateMipmaps&&U.generateMipmap(v),W.unbindTexture()},this.initRenderTarget=function(e){G.get(e).__webglFramebuffer===void 0&&K.setupRenderTarget(e)},this.initTexture=function(e){e.isCubeTexture?K.setTextureCube(e,0):e.isData3DTexture?K.setTexture3D(e,0):e.isDataArrayTexture||e.isCompressedArrayTexture?K.setTexture2DArray(e,0):K.setTexture2D(e,0),W.unbindTexture()},this.resetState=function(){te=0,j=0,M=null,W.reset(),ze.reset()},typeof __THREE_DEVTOOLS__<`u`&&__THREE_DEVTOOLS__.dispatchEvent(new CustomEvent(`observe`,{detail:this}))}get coordinateSystem(){return Fi}get outputColorSpace(){return this._outputColorSpace}set outputColorSpace(e){this._outputColorSpace=e;let t=this.getContext();t.drawingBufferColorSpace=z._getDrawingBufferColorSpace(e),t.unpackColorSpace=z._getUnpackColorSpace()}},D_=2,O_=.75;function k_(e){let t=Number(e);return Math.max(1,(Number.isFinite(t)&&t>0?t:D_)*O_)}var A_=.6,j_=.6;function M_(e){if(e==null||e===``)return null;let t=Number(e);return Number.isFinite(t)?t:null}function N_(e){if(!Array.isArray(e)||e.length<1)return null;let t=[];for(let n of e){if(!Array.isArray(n)||n.length<4)return null;let e=M_(n[0]),r=M_(n[1]),i=M_(n[2]),a=M_(n[3]);if(e===null||r===null||i===null||a===null)return null;t.push([e,r,i,a])}return t}function P_(e){let t=e?.water_profile;if(!t||typeof t!=`object`)return null;let n=t,r=N_(n.axis),i=M_(n.level_up),a=M_(n.level_down),o=M_(n.axis_x),s=M_(n.axis_z),c=M_(n.dir_x),l=M_(n.dir_z),u=M_(n.s_min),d=M_(n.s_max);return r===null||i===null||a===null||o===null||s===null||c===null||l===null||u===null||d===null?null:{level_up:i,level_down:a,flow_dir_deg:M_(n.flow_dir_deg),axis_x:o,axis_z:s,dir_x:c,dir_z:l,s_min:u,s_max:d,axis:r}}function F_(e,t,n){let r=e[0][2],i=(t-e[0][0])*(t-e[0][0])+(n-e[0][1])*(n-e[0][1]);for(let a=1;a<e.length;a+=1){let[o,s,c]=e[a-1],[l,u,d]=e[a],f=l-o,p=u-s,m=f*f+p*p,h=m<=1e-18?0:((t-o)*f+(n-s)*p)/m;h=h<0?0:h>1?1:h;let g=o+f*h,_=s+p*h,v=(t-g)*(t-g)+(n-_)*(n-_);v<i&&(i=v,r=c+(d-c)*h)}return r}function I_(e,t){if(t<=e[0][2])return e[0][3];let n=e[e.length-1];if(t>=n[2])return n[3];for(let n=1;n<e.length;n+=1){let[,,r,i]=e[n-1],[,,a,o]=e[n];if(t<=a){let e=a-r;return e<=1e-12?o:i+(o-i)*((t-r)/e)}}return n[3]}function L_(e,t,n){return I_(e.axis,F_(e.axis,t,n))}var R_=.05;function z_(e,t){return typeof e==`number`&&Number.isFinite(e)?e:t}function B_(e){let t=typeof e==`string`&&/^#[0-9a-fA-F]{6}$/.test(e.trim())?e.trim():`#3f7fb8`,n=parseInt(t.slice(1),16);return[(n>>16&255)/255,(n>>8&255)/255,(n&255)/255]}function V_(e,t){return{tint:B_(e?.tint),skyMix:z_(e?.sky_mix,.55),waveM:Math.max(z_(e?.wave_m,1.6),.05),speed:z_(e?.speed,.05),flowSpeed:z_(e?.flow_speed,Nc),opaqueDepthM:k_(t),roughness:z_(e?.roughness,.08),metalness:z_(e?.metalness,.15)}}var H_=V_(null,null);function U_(e){let t=Math.max(1,e.length),n=new Float32Array(t*3*4);for(let r=0;r<t;r+=1){let t=e[r]??H_,i=r*3*4;n[i]=t.tint[0],n[i+1]=t.tint[1],n[i+2]=t.tint[2],n[i+3]=t.skyMix,n[i+4]=t.waveM,n[i+5]=t.speed,n[i+6]=t.flowSpeed,n[i+7]=t.opaqueDepthM,n[i+8]=t.roughness,n[i+9]=t.metalness}return n}var W_=.15,G_=.35,K_=.5;function q_(e){let t=Math.min(Math.max(e/K_,0),1);return t*t*(3-2*t)}function J_(){return`
uniform sampler2D uTlodWaterSd;

// What "outside every water" is worth. The TS twin is \`waterRaster.WATER_SD_DRY\`
// and the value is the same for the same reason: a plain bilinear mix of it
// with a real ring value stays far negative, and it is FINITE, so it cannot
// turn a mix into a NaN the way the level's dry sentinel would.
const float TW_SD_DRY = -1.0e4;

float twSdAt( vec2 p ) {
  if ( uTlodWaterGeom.w <= 0.0 ) return TW_SD_DRY;
  ivec2 sz = textureSize( uTlodWaterSd, 0 );
  float cols = float( sz.x );
  float rows = float( sz.y );
  float stepM = uTlodWaterGeom.z;
  if ( cols < 2.0 || rows < 2.0 || stepM <= 0.0 ) return TW_SD_DRY;
  float fx = ( p.x - uTlodWaterGeom.x ) / stepM;
  float fz = ( p.y - uTlodWaterGeom.y ) / stepM;
  if ( fx < 0.0 || fz < 0.0 || fx > cols - 1.0 || fz > rows - 1.0 ) return TW_SD_DRY;
  float fi = min( floor( fx ), cols - 2.0 );
  float fj = min( floor( fz ), rows - 2.0 );
  float tx = fx - fi;
  float tz = fz - fj;
  int i = int( fi );
  int j = int( fj );
  // PLAIN bilinear, all four corners read: the dry sentinel is a NUMBER here,
  // so a dry corner pulls the answer negative — which is the right direction —
  // instead of poisoning it the way the level's NaN would. It cannot pull a
  // point INSIDE an outline negative: the server's dilation guarantees all four
  // corners of such a point's cell carry a real distance (§ A16.5 point 3).
  float s00 = texelFetch( uTlodWaterSd, ivec2( i, j ), 0 ).r;
  float s10 = texelFetch( uTlodWaterSd, ivec2( i + 1, j ), 0 ).r;
  float s01 = texelFetch( uTlodWaterSd, ivec2( i, j + 1 ), 0 ).r;
  float s11 = texelFetch( uTlodWaterSd, ivec2( i + 1, j + 1 ), 0 ).r;
  return mix( mix( s00, s10, tx ), mix( s01, s11, tx ), tz );
}
`}function Y_(){return`
uniform sampler2D uTlodWaterKind;

// WHICH ROW OF THE LOOK TABLE this water pixel reads — the water raster's own
// kind, resolved to a row on the CPU (\`terrainLod.buildKindRows\`) and shipped
// on the water pyramid's BASE lattice, exactly like the flow and the sd.
//
// THE ID MASK IS GONE FROM THIS PATH (finding F-A, second half). It named the
// topmost PAINTED kind and the one under it, which is a statement about the
// GROUND: a river running under a forest area, a lake with a painted bed, any
// z-order in which the water is not the top layer handed back a pair with no
// water in it, and the pixel fell to the world's PRIMARY water — the wrong
// tint, the wrong opaque depth (the rim transparency that worked in some spots
// and not in others) and the wrong \`flow_speed\` (a river drifting at a lake's
// dial, or not at all). The kind of a water is the water field's business.
//
// NEAREST, NOT BILINEAR, and that is not an approximation: a look is per KIND,
// and the mean of two row indices is a third row nobody authored. At a border
// between two water kinds the nearest texel IS which of the two a pixel is in.
// The TS twin is \`waterRaster.nearestIndex\` / \`rasterKindAt\`.
int twKindRow( vec2 p ) {
  if ( uTlodWaterGeom.w <= 0.0 ) return 0;
  ivec2 sz = textureSize( uTlodWaterKind, 0 );
  float kcols = float( sz.x );
  float krows = float( sz.y );
  float stepM = uTlodWaterGeom.z;
  if ( kcols < 1.0 || krows < 1.0 || stepM <= 0.0 ) return 0;
  float fx = ( p.x - uTlodWaterGeom.x ) / stepM;
  float fz = ( p.y - uTlodWaterGeom.y ) / stepM;
  int i = int( clamp( floor( fx + 0.5 ), 0.0, kcols - 1.0 ) );
  int j = int( clamp( floor( fz + 0.5 ), 0.0, krows - 1.0 ) );
  // The row is written as a float and read back with a half-step round: the
  // field is R32F like every other field here, and an exact small integer
  // survives a float32 round trip bit for bit.
  return int( texelFetch( uTlodWaterKind, ivec2( i, j ), 0 ).r + 0.5 );
}
`}function X_(){return`
uniform sampler2D uTlodFlow;

// THE DOWNSTREAM VECTOR AT ONE POINT, on the water pyramid's BASE lattice — the
// axis tangent times the area's speed factor (\`heightfield.water_flow_factor\`),
// which is why the LENGTH is what \`twRipple\` turns into metres per second.
//
// PLAIN BILINEAR, all four corners read: the server writes (0, 0) at every dry
// lattice point rather than a sentinel, so there is no NaN to keep out and a dry
// corner correctly drags the answer toward still. The TS twin is
// \`terrainLod.gpuWaterFlowAt\`, arithmetic for arithmetic.
vec2 twFlowAt( vec2 p ) {
  if ( uTlodWaterGeom.w <= 0.0 ) return vec2( 0.0 );
  ivec2 sz = textureSize( uTlodFlow, 0 );
  float cols = float( sz.x );
  float rows = float( sz.y );
  float stepM = uTlodWaterGeom.z;
  if ( cols < 2.0 || rows < 2.0 || stepM <= 0.0 ) return vec2( 0.0 );
  float fx = ( p.x - uTlodWaterGeom.x ) / stepM;
  float fz = ( p.y - uTlodWaterGeom.y ) / stepM;
  if ( fx < 0.0 || fz < 0.0 || fx > cols - 1.0 || fz > rows - 1.0 ) return vec2( 0.0 );
  float fi = min( floor( fx ), cols - 2.0 );
  float fj = min( floor( fz ), rows - 2.0 );
  float tx = fx - fi;
  float tz = fz - fj;
  int i = int( fi );
  int j = int( fj );
  vec2 f00 = texelFetch( uTlodFlow, ivec2( i, j ), 0 ).rg;
  vec2 f10 = texelFetch( uTlodFlow, ivec2( i + 1, j ), 0 ).rg;
  vec2 f01 = texelFetch( uTlodFlow, ivec2( i, j + 1 ), 0 ).rg;
  vec2 f11 = texelFetch( uTlodFlow, ivec2( i + 1, j + 1 ), 0 ).rg;
  return mix( mix( f00, f10, tx ), mix( f01, f11, tx ), tz );
}
`}function Z_(){return`
float twSmooth( float t ) {
  float c = clamp( t, 0.0, 1.0 );
  return c * c * ( 3.0 - 2.0 * c );
}

// HOW MUCH WATER THIS POINT IS, 0…1 — the lift in the vertex stage, the look in
// the fragment stage. The TS twin and the whole argument are in \`waterInside\`.
float twInside( float sd ) {
  return twSmooth( sd / ${K_} );
}
`}function Q_(){return`
varying float vTlodWet;
uniform sampler2D uTlodWave;
uniform sampler2D uTlodWaterLook;
uniform vec4 uTlodWaterGeom;
uniform vec3 uTlodSky;
uniform float uTlodTime;
${J_()}${Z_()}${Y_()}${X_()}

// What tlodWaterSurface() measures and the two stages after it read. Globals
// and not a struct passed along: the three insertion points are three separate
// chunks of three's own shader and cannot hand each other a value.
//
// TWO SHARES, NOT ONE (finding H2, 2026-08-25). \`twA\` is HOW MUCH OF THE BED
// IS GONE — the depth curve — and it drives the COLOUR alone. \`twS\` is HOW
// MUCH OF THIS PIXEL IS A WATER SURFACE — the rim ramp times the shore gate,
// times the SHALLOW RAMP (the bed rule of the same day) — and it drives
// everything that belongs to the surface: the roughness, the metalness, the
// ripple's tilt and the fresnel share of sky. The shallow ramp never falls
// below \`WATER_SHALLOW_SURFACE_MIN\`, so H2's answer survives: a film of water
// is still a surface, at a third of one. \`twS >= twA\` everywhere by
// construction (twA = shore·rim, twS = (0.35 + 0.65·shore)·rim). The TS twins
// are \`waterAbsorb\` and \`waterSurface\`.
float twA;
float twS;
uniform float uWaterExtras;
float twFoam;
float twSkyMix;
vec3 twN;

// The FLOW FRAME, and the one place the anisotropy lives: squeeze the
// along-flow component of a vector, leave the cross one. Still water hands in
// the world's own axes and \`aniso\` 1, which makes this the identity — that is
// how the two branches of the mirror's shader (\`materials.applyWaterShader\`)
// become one expression here without changing either.
vec2 twFrame( vec2 v, vec2 ax, vec2 ay, float aniso ) {
  return ax * ( dot( v, ax ) / aniso ) + ay * dot( v, ay );
}

// THE RIPPLE, constant for constant the mirror's (\`materials.ts\`): two
// counter-scrolling sheets of the shared wave normal map plus a faint third
// one drawn as a long ribbon along the current, the speed in real metres per
// second (the drift is divided by each layer's own wavelength), the crests
// running DOWNSTREAM (the sign is negative on flowing water) and a 3:1 squeeze
// along the flow so a current draws streaks instead of circles.
//
// THE FRAME ARRIVES SMOOTHED (finding F-C). \`twFlowAt\` reads the raster's flow,
// and the bake now runs that field through a separable box of the dilation's own
// radius before it ships (\`heightfield.WATER_FLOW_BLUR_M\`): the axis tangent
// JUMPS across a medial axis, and two neighbouring lattice points handing this
// function two very different frames is what broke the surface into
// triangle-sized patches. Measured on an authored meander the worst adjacent
// pair is 1.49 deg after the blur (1.80 before); on a hairpin drawn inside a
// lake-sized polygon, 66 deg after 146. Nothing here changed for it — the
// FIELD is simply continuous now, and since the tap moved into the fragment
// every pixel reads that continuous field directly instead of a blend of three
// samples taken up to 64 m apart.
//
// WHICH WAY THE PATTERN REALLY TRAVELS — the sign, derived rather than
// asserted (finding H1, 2026-08-25). Each sheet's sample coordinate is
//
//     uv(p, t) = F( p / lam + dir * ( t * sp * sgn / lam ) )
//
// with F the flow frame's linear squeeze (\`twFrame\`), which is invertible. A
// FIXED FEATURE of the normal map sits at a fixed uv0; the world point that
// shows it is found by solving uv(p, t) = uv0:
//
//     F(p) = lam * uv0 − F(dir) * t * sp * sgn
//     d F(p) / dt = −F(dir) * sp * sgn        and F is linear, so
//     dp / dt = −dir * sp * sgn.
//
// Adding the drift to a SAMPLE coordinate therefore slides the picture the
// OTHER way — the classic leftward scroll of \`uv + vec2(t, 0)\`, and the exact
// bug the mirror carried until commit 09f2b29f. With \`sgn = −1\` on flowing
// water the feature travels at \`+dir * sp\`, i.e. DOWNSTREAM at sp·|dir| m/s;
// with \`sgn = +1\` it would travel upstream. The identity the smoke pins is the
// sharpest form of the same statement:
//
//     uv( p0 + dir * sp * t, t ) == uv( p0, 0 )   for every t, exactly
//
// — the crest rides the world at velocity \`dir · sp\`. Still water keeps the
// +1 it always had (a lake has no reference direction, and its two sheets
// counter-scroll either way), which is the mirror's accepted convention.
//
// TEXTUREGRAD AND NOT TEXTURE. Every fetch here sits under \`if ( d > 0.0 )\`,
// which differs across a quad at every shoreline, so an implicit derivative
// would be undefined. The gradients are taken from the WORLD POSITION at
// uniform control flow and pushed through the very same linear map the sample
// coordinate goes through — which is exact, because that map is linear.
vec3 twRipple( vec2 p, vec2 gx, vec2 gy, float waveM, float speed, float flowSpeed ) {
  // HOW MUCH OF THE RIPPLE THIS PIXEL CAN STILL RESOLVE: once one pixel covers
  // a whole wavelength the map carries no signal, and what is left is sampling
  // noise in a specular lobe narrow enough to turn every texel into a spark.
  float px = max( length( gx ), length( gy ) );
  float detail = clamp( 1.0 - px / waveM, 0.0, 1.0 );
  // THE FLOW IS THIS PIXEL'S OWN TAP OF THE FIELD (Task 7, 2026-08-27), not a
  // varying: \`p\` is \`vTlodXZ\`, so the current a fragment drifts at is the one
  // the raster really carries under it, at every level the piece may be drawn
  // at. The whole derivation — and the 175/224 alignments a 64 m vertex spacing
  // used to turn into standing water — is in \`waterFlowGlsl\`.
  //
  // The area's speed factor rides on the LENGTH of the flow vector (the server
  // bakes it there, \`heightfield.water_flow_factor\`), and a length below 1e-4
  // is STILL — a lake, which drifts at \`speed\` and counter-scrolls its sheets.
  vec2 flow = twFlowAt( p );
  float len = length( flow );
  bool still = len < 1e-4;
  vec2 ax = still ? vec2( 1.0, 0.0 ) : flow / max( len, 1e-4 );
  vec2 ay = vec2( -ax.y, ax.x );
  float sp = still ? speed : flowSpeed * len;
  float sgn = still ? 1.0 : -1.0;
  // ISOTROPIC on purpose since 2026-08-25 (user finding, twice measured with
  // the readout: the drift chain runs at ~1 m/s downstream, yet the visible
  // motion read SIDEWAYS). The 3:1 along-flow squeeze hid exactly the motion
  // it should have shown — a streak sliding along its own length displays
  // nothing, so only the small CROSS components of sheets A/B stayed
  // readable and the water appeared to drift sideways (or, where the squeeze
  // smeared the pattern, "voellig diffus"). With aniso 1 the crest shapes
  // keep their form and visibly travel downstream; the direction cue from
  // stretched STREAKS survives in sheet C, which keeps its own 8x squeeze.
  float aniso = 1.0;
  float crossA = still ? 0.6 : 0.15;
  float crossB = still ? 1.3 : 0.3;
  vec2 dirA = ax + ay * crossA;
  vec2 dirB = still ? -( ax * 0.8 + ay * crossB ) : ax * 0.8 - ay * crossB;
  float lamA = waveM;
  float lamB = waveM * 0.63;
  float lamC = waveM * 2.0;
  vec2 uvA = twFrame( p / lamA + dirA * ( uTlodTime * sp * sgn / lamA ), ax, ay, aniso );
  vec2 uvB = twFrame( p / lamB + dirB * ( uTlodTime * sp * sgn / lamB ), ax, ay, aniso );
  vec2 uvC = twFrame( ( p + ax * ( uTlodTime * sp * sgn ) ) / lamC, ax, ay, 8.0 );
  vec3 nA = textureGrad( uTlodWave, uvA, twFrame( gx, ax, ay, aniso ) / lamA,
                                         twFrame( gy, ax, ay, aniso ) / lamA ).xyz * 2.0 - 1.0;
  vec3 nB = textureGrad( uTlodWave, uvB, twFrame( gx, ax, ay, aniso ) / lamB,
                                         twFrame( gy, ax, ay, aniso ) / lamB ).xyz * 2.0 - 1.0;
  vec3 nC = textureGrad( uTlodWave, uvC, twFrame( gx, ax, ay, 8.0 ) / lamC,
                                         twFrame( gy, ax, ay, 8.0 ) / lamC ).xyz * 2.0 - 1.0;
  vec3 n = normalize( nA + nB + nC * ( still ? 0.0 : 0.35 ) );
  n = mix( vec3( 0.0, 0.0, 1.0 ), n, detail );
  // Tangent space (+z up) over a horizontal mirror whose uv IS the world xz:
  // tangent -> +x, bitangent -> +z, normal -> +y. That is the \`tbn\` of the
  // mirror mesh, written out, because this surface has no tangent attribute.
  return normalize( vec3( n.x, n.z, n.y ) );
}

// THE MEASUREMENT, once per fragment of the water variant. Everything that
// needs a derivative is taken BEFORE the dry branch returns, at uniform control
// flow: a dry pixel of a wet piece then pays two derivatives and one compare
// and keeps the ground it always had.
void tlodWaterSurface( inout vec4 diffuseColor, inout float roughnessFactor,
                       inout float metalnessFactor ) {
  twA = 0.0;
  twS = 0.0;
  twFoam = 0.0;
  twSkyMix = 0.0;
  twN = vec3( 0.0, 1.0, 0.0 );
  float d = vTlodWet;
  float edge = max( fwidth( d ), ${R_} );
  vec2 gx = dFdx( vTlodXZ );
  vec2 gy = dFdy( vTlodXZ );
  if ( d <= 0.0 ) return;
  int rows = textureSize( uTlodWaterLook, 0 ).y;
  // HOW MUCH WATER THIS PIXEL IS — the water raster's own signed distance, the
  // SAME field through the same sampler (\`waterSdGlsl\`) and through the SAME
  // curve (\`waterGateGlsl\`) the vertex stage scaled its lift by. That the two
  // stages share both texts is what keeps the drawn surface and the drawn look
  // on the same shore ramp (finding G1).
  float inside = twInside( twSdAt( vTlodXZ ) );
  // WHICH KIND'S LOOK — the water raster's OWN kind, read nearest off the same
  // lattice the level, the flow and the sd ride on (\`twKindRow\`). The ground
  // compositor's id mask answered this until bake v10 and answered it wrong
  // wherever the water was not the topmost PAINTED kind; see \`waterKindGlsl\`.
  //
  // OUTSIDE THE WATER WINDOW row 0 stands, which is the world's primary water:
  // the worst case out there is the wrong water and never a ground-coloured
  // lake — and a pixel out there was not lifted, so it never gets this far.
  int layer = clamp( twKindRow( vTlodXZ ), 0, rows - 1 );
  // The rim ramp: 0 exactly where the water ends, 1 one pixel of depth in —
  // and 0 outside the authored outline, where the lift no longer fires either.
  float rim = clamp( d / edge, 0.0, 1.0 ) * inside;
  if ( rim <= 0.0 ) return;
  vec4 look0 = texelFetch( uTlodWaterLook, ivec2( 0, layer ), 0 );
  vec4 look1 = texelFetch( uTlodWaterLook, ivec2( 1, layer ), 0 );
  vec4 look2 = texelFetch( uTlodWaterLook, ivec2( 2, layer ), 0 );
  float shore = twSmooth( d / max( look1.w, 1e-3 ) );
  // THE SURFACE SHARE is the rim, RAMPED BY THE SHALLOW CURVE (the bed rule of
  // 2026-08-25): a pixel inside the outline with water over it IS a water
  // surface however thin the film (finding H2), but a film gets a THIRD of one,
  // not a whole one — with the whole one, the sky wash and the ripple's tilt
  // carry a pixel whose bed the absorption has barely touched, and the bed
  // cannot be read through them. The curve is \`shore\` itself, so there is no
  // second curve and no second constant to keep in step; the TS twin is
  // \`waterShallowRamp\`.
  //
  // THE ABSORPTION is the rim narrowed by that same depth curve — how much of
  // the bed has gone. Everything below picks one of the two on purpose, and
  // \`twS >= twA\` still holds (0.35 + 0.65·s >= s for s in 0…1).
  twS = rim * mix( ${G_}, 1.0, shore );
  twA = shore * rim;
  // THE FOAM, and the COVER it is multiplied by — the mirror's own alpha, which
  // an opaque ground has nowhere else to put. See waterFoamAt: without it a
  // hand's width of water at the rim is painted 6.26× as white as the surface
  // this replaced, which is the white edge and the white lattice corner.
  twSkyMix = look0.w;
  if ( uWaterExtras > 0.5 ) {
    float rawFoam = 1.0 - twSmooth( d / ${A_} );
    twFoam = rawFoam * min( shore + rawFoam * ${W_}, 1.0 ) * rim;
    twN = twRipple( vTlodXZ, gx, gy, max( look1.x, 0.05 ), look1.y, look1.z );
  }
  // THE ABSORPTION, on the ALBEDO and not on the finished light: the bed the
  // compositor painted is blended toward the water's tint here, so the lighting
  // model shades the water itself — with the water's roughness and the water's
  // normal — instead of a flat patch of colour laid over a lit ground.
  //
  // AND THE COLOUR IS THE ONE TERM THE DEPTH KEEPS. That mix IS the
  // semi-transparent look the finding asks for: over a centimetre of water the
  // bed shows through almost whole, over a metre and a half it is gone.
  diffuseColor.rgb = mix( diffuseColor.rgb, look0.rgb, twA );
  // …while the two MATERIAL constants ride the SURFACE share. A film of water
  // over sand is a smooth, faintly metallic surface at any depth; giving these
  // the depth curve is what left shallow water with the roughness of dry
  // ground (0.847 of 0.85 at 5 cm) and no sheen at all (finding H2).
  roughnessFactor = mix( roughnessFactor, look2.x, twS );
  metalnessFactor = mix( metalnessFactor, look2.y, twS );
}

// THE SHADING NORMAL of a water pixel — a MACRO normal and a PERTURBATION,
// each on its own share (finding H2), and the one place K-A gives GPU work
// back rather than taking it.
//
// MACRO = mix( ground, up, twA ). "What shape does the light fall on" is a
// DEPTH question: where the bed is fully absorbed the surface is a flat
// mirror, and where the bed shows through, its own tilt is still the shape.
//
// PERTURBATION = ( twN − up ) · twS. The ripple's tilt off flat is all
// \`twRipple\` ever makes, and whether a surface ripples is not a depth
// question at all. Riding it on twA is what left a shore with 0.33 % of its
// ripple at 5 cm of water — a mirror-still, ground-rough bank, which is the
// other half of "the water does not flow" (finding H1: the DRIFT is correct,
// there was simply no water normal left to carry it).
//
// BOTH EARLY-OUTS SURVIVE, arithmetically identical to before:
//  * twS == 0 (dry, or outside the outline) -> macro + 0 == ground.
//  * twA == 1 -> macro == up and up + ( twN − up ) == twN, so the bed's normal
//    is not computed at all: \`tlodNormalAt\` is four \`tlodHeight\` calls, i.e.
//    SIXTEEN texelFetch, still skipped for every pixel below the opaque depth.
// The TS twin of the whole composition is \`waterShadeNormal\`.
vec3 tlodWaterNormal() {
  if ( twS <= 0.0 ) {
    return normalize( ( viewMatrix * vec4( tlodNormalAt( vTlodXZ ), 0.0 ) ).xyz );
  }
  if ( twA >= 1.0 ) {
    return normalize( ( viewMatrix * vec4( twN, 0.0 ) ).xyz );
  }
  vec3 up = vec3( 0.0, 1.0, 0.0 );
  vec3 macro = mix( tlodNormalAt( vTlodXZ ), up, twA );
  vec3 nw = normalize( macro + ( twN - up ) * twS );
  return normalize( ( viewMatrix * vec4( nw, 0.0 ) ).xyz );
}

// The two things that are not albedo, written on the finished light: the
// fresnel share of sky (the reflection this renderer can afford, § 3.4) and
// the foam lace at the rim. Same order as the mirror's shader — the foam is
// broken water lying ON the reflection, not under it.
//
// THE SKY SHARE RIDES twS AND NOT twA (finding H2). A wet road mirrors the
// sky, and it is a millimetre deep; the reflection off a water surface is a
// property of the INTERFACE, not of what stands under it. On the default lake
// at 5 cm the old coupling gave a sky share of 0.00089630 against 0.275 — i.e.
// none, which is precisely how shallow water came to read as land.
//
// …AND twS CARRIES THE SHALLOW RAMP, which is the other half of the same
// balance (the bed rule of 2026-08-25). At 10 cm of that lake the share is
// 0.275 · 0.35828148 = 0.09852741: a tenth of the way to the sky, not a
// quarter, so the bed's own texture is still what the eye reads there.
void tlodWaterOut( inout vec3 outgoingLight, vec3 n, vec3 viewPos ) {
  if ( twS <= 0.0 && twFoam <= 0.0 ) return;
  float fres = pow( 1.0 - clamp( dot( normalize( viewPos ), n ), 0.0, 1.0 ), 3.0 );
  outgoingLight = mix( outgoingLight, uTlodSky,
                       clamp( fres * twSkyMix, 0.0, 1.0 ) * twS );
  outgoingLight = mix( outgoingLight, vec3( 1.0 ), twFoam * ${j_} );
}
`}var $_=.4,ev=!1,tv=!1;function nv(e){tv=e;for(let e of rv)e.reapply()}var rv=new Set;function iv(e){if(e!==ev){ev=e;for(let e of rv)e.reapply()}}var av=!1;function ov(){av||(av=!0,console.warn(`[submergedGhost] the underwater ghost found no shader anchor — the waterline cut is not compiled in (three chunk renamed?)`))}var sv=class{root;meshes=[];built=!1;shown=!1;level=null;cut={value:0};constructor(e){this.root=e,rv.add(this)}set(e){this.level=e!==null&&Number.isFinite(e)?e:null,this.reapply()}reapply(){let e=this.level!==null&&!ev&&!tv;if(e&&(this.cut.value=this.level),e!==this.shown){this.shown=e,e&&!this.built&&this.build();for(let t of this.meshes)t.visible=e}}get count(){return this.meshes.length}get cutY(){return this.cut.value}get visible(){return this.shown}get parts(){return this.meshes}dispose(){rv.delete(this);for(let e of this.meshes){e.parent?.remove(e);let t=e.material;if(Array.isArray(t))for(let e of t)e.dispose();else t?.dispose()}this.meshes.length=0,this.built=!1,this.shown=!1}build(){this.built=!0;let e=[];this.root.traverse(t=>{let n=t;n.isMesh&&e.push(n)});for(let t of e){let e=this.twin(t);e.castShadow=!1,e.receiveShadow=!1,e.frustumCulled=t.frustumCulled,e.renderOrder=2,e.visible=!1,t.add(e),this.meshes.push(e)}}twin(e){let t=(Array.isArray(e.material)?e.material:[e.material]).map(e=>this.material(e)),n=Array.isArray(e.material)?t:t[0],r=e;if(r.isSkinnedMesh){let e=new Pn(r.geometry,n);return e.bindMode=r.bindMode,e.bind(r.skeleton,r.bindMatrix),e}return new wr(e.geometry,n)}material(e){let t=B_(void 0),n=e,r=this.cut,i=new wn({map:n?.map??null,color:new kt().setRGB(t[0],t[1],t[2]),transparent:!0,opacity:$_,depthFunc:6,depthWrite:!1,side:n?.side??0,vertexColors:!!n?.vertexColors,alphaTest:n?.alphaTest??0});return i.onBeforeCompile=e=>{e.uniforms.uGhostCutY=r,(!e.vertexShader.includes(`#include <fog_vertex>`)||!e.fragmentShader.includes(`#include <clipping_planes_fragment>`))&&ov(),e.vertexShader=`varying float vGhostY;\n${e.vertexShader}`.replace(`#include <fog_vertex>`,`#include <fog_vertex>
	vGhostY = ( modelMatrix * vec4( transformed, 1.0 ) ).y;`),e.fragmentShader=`varying float vGhostY;\nuniform float uGhostCutY;\n${e.fragmentShader}`.replace(`#include <clipping_planes_fragment>`,`#include <clipping_planes_fragment>
	if ( vGhostY > uGhostCutY ) discard;`)},i.customProgramCacheKey=()=>`av-water-ghost`,i}};function cv(e){let t=[],n=0,r=0,i=!1,a=()=>{let e=0;for(let n=1;n<t.length;n++){let r=t[n],i=t[e],a=r.priority===`avatar`?0:1,o=i.priority===`avatar`?0:1,s=r.distance(),c=i.distance(),l=Number.isNaN(s)?1/0:s,u=Number.isNaN(c)?1/0:c;(a===o?l===u?r.seq<i.seq:l<u:a<o)&&(e=n)}return t.splice(e,1)[0]},o=()=>{for(i=!1;n<e.max&&t.length;){let e=a();n++,Promise.resolve().then(e.run).catch(()=>{}).finally(()=>{n--,e.resolve(`done`),o()})}};return{push(e){return new Promise(n=>{t.push({...e,seq:r++,resolve:n}),i||(i=!0,queueMicrotask(o))})},cancel(e){let n=t.findIndex(t=>t.key===e);if(n<0)return!1;let[r]=t.splice(n,1);return r.resolve(`cancelled`),!0},size:()=>t.length,active:()=>n}}var lv=.8,uv=lv,dv=class{active=!1;pendingSeconds=0;update(e,t,n){return t?(this.active?e>=1.8:e<=1.2)?(this.pendingSeconds+=n,this.pendingSeconds>=.179999999&&(this.active=!this.active,this.pendingSeconds=0),this.active):(this.pendingSeconds=0,this.active):(this.active=!1,this.pendingSeconds=0,!1)}},fv=.94;function pv(e,t,n){return e<t?t:e>n?n:e}function mv(e,t=18){let n=pv((e-lv)/(150-lv),0,1);return t+(62-t)*Math.sqrt(n)}function hv(e){return e*fv}var gv=.45,_v=.055;function vv(e,t,n){let r=t?e[1]+(t[1]-e[1])*gv:hv(n);return[e[0],r,e[2]+n*_v]}function yv(e){return Math.atan2(-Math.sin(e),-Math.cos(e))}function bv(e,t,n=60){let r=(t-e)%(Math.PI*2);return r>Math.PI&&(r-=Math.PI*2),r<-Math.PI&&(r+=Math.PI*2),Math.abs(r)>n*Math.PI/180?t:null}function xv(e,t){let n=document.createElement(`canvas`);n.width=n.height=e,t(n.getContext(`2d`));let r=new ke(n);return r.colorSpace=Yt,r.wrapS=r.wrapT=pe,r.anisotropy=4,r}function Sv(){return xv(256,e=>{let t=Hs(`grass`);e.fillStyle=`#7fa055`,e.fillRect(0,0,256,256);for(let n=0;n<2600;n++){let n=130+Math.floor(t()*55);e.fillStyle=`rgb(${n-45},${n},${60+Math.floor(t()*30)})`,e.fillRect(t()*256,t()*256,2,2)}for(let n=0;n<14;n++)e.fillStyle=`rgba(110,130,70,${.12+t()*.1})`,e.beginPath(),e.ellipse(t()*256,t()*256,18+t()*30,12+t()*22,t()*Math.PI,0,Math.PI*2),e.fill()})}export{Mc as $,So as $t,lm as A,fs as At,Zf as B,Bo as Bt,P_ as C,ws as Ct,jp as D,_s as Dt,um as E,gs as Et,sm as F,Ro as Ft,vu as G,Ja as Gt,hp as H,Po as Ht,om as I,Io as It,nl as J,xo as Jt,ru as K,to as Kt,nm as L,Wo as Lt,cm as M,ds as Mt,rm as N,hs as Nt,Jp as O,cs as Ot,Zp as P,Lo as Pt,Lc as Q,so as Qt,tm as R,zo as Rt,L_ as S,Ns as St,E_ as T,Cs as Tt,Hf as U,La as Ut,gp as V,Vo as Vt,Uf as W,io as Wt,Pc as X,yo as Xt,Fc as Y,vo as Yt,Wc as Z,Fa as Zt,Z_ as _,ro as _n,Bs as _t,mv as a,Xa as an,qs as at,J_ as b,Ra as bn,sc as bt,vv as c,uo as cn,tc as ct,sv as d,Ua as dn,cc as dt,lo as en,bc as et,nv as f,co as fn,ic as ft,Q_ as g,oo as gn,Is as gt,U_ as h,Na as hn,Qs as ht,lv as i,Ka as in,Fs as it,im as j,us as jt,Yp as k,ls as kt,yv as l,Ga as ln,Rs as lt,H_ as m,bo as mn,ec as mt,uv as n,Ya as nn,jc as nt,bv as o,Wa as on,Us as ot,iv as p,Co as pn,Ys as pt,Rc as q,ho as qt,dv as r,qa as rn,Ac as rt,hv as s,fo as sn,Zs as st,Sv as t,ao as tn,_c as tt,cv as u,$a as un,rc as ut,q_ as v,mo as vn,Ls as vt,Nm as w,Z as wt,j_ as x,Ma as xn,Ws as xt,V_ as y,Pa as yn,Hs as yt,Sp as z,Uo as zt};