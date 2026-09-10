import{i as e}from"./react-BRNZa73l.js";var t=315,n=45,r=.35,i=1,a=1,o=Math.PI/180;function s(e,t){return typeof e==`number`&&Number.isFinite(e)?e:t}function c(e,t,n){let r=e[t]?.[n];return typeof r==`number`&&Number.isFinite(r)?r:0}function l(e,l){let u=e?.heights;if(!u||u.length<2)return null;let d=u.length,f=u[0]?.length||0;if(f<2)return null;let p=e?.step_m??0;if(!(p>0))return null;let m=s(l?.azimuthDeg,t)*o,h=Math.min(90,Math.max(a,s(l?.altitudeDeg,n)))*o,g=Math.min(1,Math.max(0,s(l?.maxAlpha,r))),_=Math.max(0,s(l?.zFactor,i)),v=Math.cos(h),y=v*Math.sin(m),b=Math.sin(h),x=-v*Math.cos(m),S=b,C=new Uint8ClampedArray(f*d*4);for(let e=0;e<d;e+=1){let t=e>0?e-1:e,n=e<d-1?e+1:e,r=(n-t)*p;for(let i=0;i<f;i+=1){let a=i>0?i-1:i,o=i<f-1?i+1:i,s=(o-a)*p,l=_*(c(u,e,o)-c(u,e,a))/s,d=_*(c(u,n,i)-c(u,t,i))/r,m=Math.sqrt(l*l+d*d),h=Math.sqrt(m*m+1),v=(-l*y+b-d*x)/h,w=Math.min(1,.5*(v>0?v:0)/S),T=Math.round(255*w),E=Math.round(255*g*(m/h)),D=(e*f+i)*4;C[D]=T,C[D+1]=T,C[D+2]=T,C[D+3]=E}}return{cols:f,rows:d,data:C}}function u(e,t,n,r=0){if(t!==`aligned`)return e*Math.PI*2;let i=Number.isFinite(Number(n))?Number(n)*Math.PI/180:0,a=Number.isFinite(r)?r:0,o=Math.PI*2;return((a+i)%o+o)%o}var d=2e3;function f(e,t,n){return`terrain:scatter:${e}:${t}${p(n)}`}function p(e){return Number.isFinite(e)?`:e${e}`:``}function m(e,t){let n=Number(t);if(!Number.isFinite(n)||n<=0)return;let r=Number(e);if(Number.isFinite(r))return Math.floor(r/(n*60))}function h(e){let t=2166136261;for(let n=0;n<e.length;n+=1)t^=e.charCodeAt(n),t=Math.imul(t,16777619);return t>>>0}function g(e,t,n){let r=Math.floor(Number(n));if(!Number.isFinite(r)||r<=1)return 0;let i=Math.floor(Number(t));return Number.isFinite(i)?((h(e)+i)%r+r)%r:0}function _(e,t){if(typeof e!=`number`||!Number.isFinite(e))return-1;let n=Math.floor(Number(t));return!Number.isFinite(n)||n<1?-1:Math.min(Math.max(Math.floor(e),0),n-1)}function v(e){let t=h(e)|0;return()=>(t=Math.imul(t^t>>>15,2246822519),t=Math.imul(t^t>>>13,3266489917),((t^=t>>>16)>>>0)/4294967296)}function y(e,t,n){let r=!1,i=n?.length??0;for(let a=0,o=i-1;a<i;o=a,a+=1){let[i,s]=n[a],[c,l]=n[o];s>t!=l>t&&e<(c-i)*(t-s)/(l-s)+i&&(r=!r)}return r}function b(e,t,n,r,i){let a=Math.cos(n),o=Math.sin(n),s=r-e,c=i-t;return{x:s*a-c*o,z:s*o+c*a}}function x(e,t,n){let r=e?.points,i=r?.length??0;if(i<3||!Number.isFinite(t)||!Number.isFinite(n))return!1;let a=!1;for(let e=0,o=i-1;e<i;o=e,e+=1){let i=r[e],s=r[o];if(!i||!s||i.length<2||s.length<2)return!1;let c=i[0],l=i[1],u=s[0],d=s[1];if(!Number.isFinite(c)||!Number.isFinite(l)||!Number.isFinite(u)||!Number.isFinite(d))return!1;l>n!=d>n&&t<(u-c)*(n-l)/(d-l)+c&&(a=!a)}return a}function S(e,t,n){let r=e?.points,i=r?.length??0;if(i<3||!Number.isFinite(t)||!Number.isFinite(n))return 1/0;let a=!1,o=1/0;for(let e=0,s=i-1;e<i;s=e,e+=1){let i=r[e],c=r[s];if(!i||!c||i.length<2||c.length<2)return 1/0;let l=i[0],u=i[1],d=c[0],f=c[1];if(!Number.isFinite(l)||!Number.isFinite(u)||!Number.isFinite(d)||!Number.isFinite(f))return 1/0;u>n!=f>n&&t<(d-l)*(n-u)/(f-u)+l&&(a=!a);let p=l-d,m=u-f,h=p*p+m*m,g=h<1e-18?0:((t-d)*p+(n-f)*m)/h;g=g<0?0:g>1?1:g;let _=t-(d+g*p),v=n-(f+g*m),y=Math.sqrt(_*_+v*v);y<o&&(o=y)}return a?0:o}function C(e,t,n,r){let i=Number(r);return i>0?S(e,t,n)<i:x(e,t,n)}var w=.5;function T(e,t){let n=Number(t);if(Number.isFinite(n)&&n>0)return n/2;let r=Number(e);return!Number.isFinite(r)||r<=0?0:r*w}function E(e){let t=Number(e?.x),n=Number(e?.z),r=Number(e?.half_w),i=Number(e?.half_d),a=Number(e?.yaw_deg);if(!Number.isFinite(t)||!Number.isFinite(n)||!(r>0)||!(i>0))return null;let o=(Number.isFinite(a)?a:0)*Math.PI/180,s=Math.cos(o),c=Math.sin(o),l=(e,r)=>[t+e*s+r*c,n-e*c+r*s];return{points:[l(-r,-i),l(r,-i),l(r,i),l(-r,i)]}}function D(e){let t=[];for(let n of e??[]){let e=E(n);e&&t.push(e)}return t}function O(e,t){let n=Number(e??t);return Number.isFinite(n)&&n>0?n:0}function k(e,t,n){let r=Number(t),i=Number(e);if(!Number.isFinite(r)||r<=0||!Number.isFinite(i)||i<=0)return 0;let a=n??2e3,o=Math.min(Math.round(i/100*r),a);return o>=1?o:0}function A(e){let t=e.ring??[],n=Number(e.densityPer100m2),r=Number(e.areaM2);if(t.length<3||!Number.isFinite(n)||n<=0||!Number.isFinite(r)||r<=0)return[];let i=k(r,n,e.maxPoints);if(i<1)return[];let a=1/0,o=1/0,s=-1/0,c=-1/0;for(let[e,n]of t)e<a&&(a=e),e>s&&(s=e),n<o&&(o=n),n>c&&(c=n);if(!Number.isFinite(a)||!Number.isFinite(o))return[];let l=e.rng??v(e.seed),d=e.footprints??[],f=e.clearM,p=e.occluders??[],m=Number(e.minSpacingM),h=Number.isFinite(m)&&m>0,b=m*m,x=h?new Map:null,S=Math.floor(Number(e.variantCount)),w=Number.isFinite(S)&&S>1,T=w?_(e.variant,S):-1,E=e.yawMode===`aligned`?e.axisAt:void 0,D=e.occupied,A=O(e.occupyR,e.clearM),j=e.occupyTag??e.seed,M=[],N=i*(e.triesPerPoint??12),P=0;for(;M.length<i&&N>0;){--N;let n=P;P+=1;let r=a+l()*(s-a),i=o+l()*(c-o),h=l();if(!y(r,i,t))continue;let _=!1;for(let e of p)if((e?.length??0)>=3&&y(r,i,e)){_=!0;break}if(_)continue;let v=!1;for(let e of d)if(C(e,r,i,f)){v=!0;break}if(v)continue;if(x){let e=Math.floor(r/m),t=Math.floor(i/m),n=!1;for(let a=-1;a<=1&&!n;a+=1)for(let o=-1;o<=1&&!n;o+=1){let s=x.get(`${e+o},${t+a}`);if(s)for(let[e,t]of s){let a=r-e,o=i-t;if(a*a+o*o<b){n=!0;break}}}if(n)continue}if(D&&D.blocks(r,i,A,j))continue;if(x){let e=`${Math.floor(r/m)},${Math.floor(i/m)}`,t=x.get(e);t?t.push([r,i]):x.set(e,[[r,i]])}D&&D.add(r,i,A,j);let O=u(h,e.yawMode,e.yawDeg,E?E(r,i):0);M.push(w?{x:r,z:i,yaw:O,variant:T>=0?T:g(e.seed,n,S)}:{x:r,z:i,yaw:O})}return M}var j=4e3,M=4096;function N(e){return Math.floor(e/64)}function P(e,t,n,r,i){return`terrain:scatter:${e}:${t}:${n},${r}${p(i)}`}function ee(e,t){let n=e*64,r=t*64,i=n+64,a=r+64;return[[n,r],[i,r],[i,a],[n,a]]}function F(e,t,n,r){if(![e,t,n,r].every(e=>Number.isFinite(e))||n<e||r<t)return 0;let i=N(n)-N(e)+1,a=N(r)-N(t)+1;return!(i>0)||!(a>0)?0:i*a}function te(e,t,n,r,i=M){let a=F(e,t,n,r);if(a<=0||a>i)return[];let o=N(e),s=N(n),c=N(t),l=N(r),u=[];for(let e=c;e<=l;e+=1)for(let t=o;t<=s;t+=1)u.push([t,e]);return u}function ne(e){let t=e.ring??[];if(t.length<3)return[];let n=e.occupied;return A({ring:ee(e.cx,e.cz),areaM2:4096,densityPer100m2:e.densityPer100m2,seed:e.seed,footprints:e.footprints,clearM:e.clearM,occluders:e.occluders,minSpacingM:e.minSpacingM,maxPoints:e.maxPoints??4e3,triesPerPoint:1,variantCount:e.variantCount,variant:e.variant,rng:e.rng,yawMode:e.yawMode,yawDeg:e.yawDeg,axisAt:e.axisAt,occupied:n?{blocks:(e,t,r,i)=>n.blocks(e,t,r,i),add:(e,r,i,a)=>{y(e,r,t)&&n.add(e,r,i,a)}}:void 0,occupyR:e.occupyR,occupyTag:e.occupyTag}).filter(e=>y(e.x,e.z,t))}var I=Math.PI*2,L=1e-4,R=1e-9,re=1e5;function z(e){return(e%I+I)%I}function B(e,t,n,r,i,a){let o=i-n,s=a-r,c=o*o+s*s,l=c<1e-18?0:((e-n)*o+(t-r)*s)/c;l=l<0?0:l>1?1:l;let u=e-(n+l*o),d=t-(r+l*s);return Math.sqrt(u*u+d*d)}function ie(e,t,n,r,i){let a=r-t,o=i-n,s=Math.hypot(a,o);if(!(s>0))return 0;let c=Math.atan2(a,o),l=(t+r)/2,u=(n+i)/2,d=o/s,f=-a/s;return z(y(l+d*L,u+f*L,e)?c:c+Math.PI)}function ae(e,t,n){let r=e?.length??0;if(r<3)return 0;let i=1/0,a=-1;for(let o=0,s=r-1;o<r;s=o,o+=1){let r=B(t,n,e[s][0],e[s][1],e[o][0],e[o][1]);r<i&&(i=r,a=o)}if(a<0)return 0;let o=a===0?r-1:a-1;return ie(e,e[o][0],e[o][1],e[a][0],e[a][1])}function oe(e,t,n){let r=e?.length??0;if(r<2)return 0;let i=1/0,a=0;for(let o=1;o<r;o+=1){let[r,s]=e[o-1],[c,l]=e[o],u=c-r,d=l-s;if(u*u+d*d<1e-18)continue;let f=B(t,n,r,s,c,l);f<i&&(i=f,a=z(Math.atan2(u,d)))}return a}function se(e,t){return e?(t,n)=>oe(e,t,n):(e,n)=>ae(t,e,n)}function ce(e,t,n){let r=e.length,i=1/0;for(let a=0,o=r-1;a<r;o=a,a+=1){let r=B(t,n,e[o][0],e[o][1],e[a][0],e[a][1]);r<i&&(i=r)}return y(t,n,e)?i:-i}function V(e,t,n,r){let i=ce(e,t,n);return{x:t,z:n,h:r,d:i,max:i+r*Math.SQRT2}}function H(e,t){e.push(t);let n=e.length-1;for(;n>0;){let t=n-1>>1;if(e[t].max>=e[n].max)break;let r=e[t];e[t]=e[n],e[n]=r,n=t}}function le(e){let t=e[0],n=e.pop();if(e.length===0||n===void 0)return t;e[0]=n;let r=0;for(;;){let t=r*2+1,n=t+1,i=r;if(t<e.length&&e[t].max>e[i].max&&(i=t),n<e.length&&e[n].max>e[i].max&&(i=n),i===r)break;let a=e[i];e[i]=e[r],e[r]=a,r=i}return t}function ue(e,t=.5){let n=e?.length??0;if(n<3)return{x:0,z:0,d:0};let r=1/0,i=1/0,a=-1/0,o=-1/0;for(let[t,n]of e){if(!Number.isFinite(t)||!Number.isFinite(n))return{x:0,z:0,d:0};t<r&&(r=t),t>a&&(a=t),n<i&&(i=n),n>o&&(o=n)}let s=a-r,c=o-i,l=Math.min(s,c);if(!(l>0))return{x:r+s/2,z:i+c/2,d:0};let u=Number.isFinite(t)&&t>0?t:.5,d=l/2,f=0,p=0,m=0;for(let t=0,r=n-1;t<n;r=t,t+=1){let[n,i]=e[t],[a,o]=e[r],s=n*o-a*i;f+=s,p+=(n+a)*s,m+=(i+o)*s}let h=Math.abs(f)>1e-12?V(e,p/(3*f),m/(3*f),0):V(e,r+s/2,i+c/2,0),g=V(e,r+s/2,i+c/2,0);g.d>h.d&&(h=g);let _=[];for(let t=r;t<a;t+=l)for(let n=i;n<o;n+=l)H(_,V(e,t+d,n+d,d));let v=_.length;for(;_.length>0&&v<re;){let t=le(_);if(!t)break;if(t.d>h.d&&(h=t),t.max-h.d<=u)continue;let n=t.h/2;H(_,V(e,t.x-n,t.z-n,n)),H(_,V(e,t.x+n,t.z-n,n)),H(_,V(e,t.x-n,t.z+n,n)),H(_,V(e,t.x+n,t.z+n,n)),v+=4}return{x:h.x,z:h.z,d:h.d}}function de(e){let t=[];for(let n of e??[]){if(!n||n.length<2)return[];let[e,r]=n;if(!Number.isFinite(e)||!Number.isFinite(r))return[];let i=t[t.length-1];i&&Math.abs(i[0]-e)<R&&Math.abs(i[1]-r)<R||t.push([e,r])}let n=t[0],r=t[t.length-1];if(t.length>1&&Math.abs(n[0]-r[0])<R&&Math.abs(n[1]-r[1])<R&&t.pop(),t.length<3)return[];let i=[],a=0;for(let e=0;e<t.length;e+=1){let[n,r]=t[e],[o,s]=t[(e+1)%t.length],c=Math.hypot(o-n,s-r);c>R&&(i.push({ax:n,az:r,bx:o,bz:s,len:c,start:a,end:a+c}),a+=c)}return i}function fe(e,t){let n=Number(t?.spacingM);if(!Number.isFinite(n)||n<=0)return[];let r=t?.offsetM===void 0?0:Number(t.offsetM);if(!Number.isFinite(r)||r<0)return[];let i=de(e);if(i.length<3)return[];let a=i[i.length-1].end,o=typeof t.startM==`number`&&Number.isFinite(t.startM)&&t.startM>=0?Math.min(t.startM,n):n/2,s=t.maxPoints??2e3,c=Array(i.length).fill(NaN),l=[],u=0;for(let t=0;;t+=1){let d=o+t*n;if(!(d<a-R)||l.length>=s)break;for(;u<i.length-1&&d>=i[u].end;)u+=1;let f=i[u],p=(d-f.start)/f.len;p=p<0?0:p>1?1:p;let m=f.ax+p*(f.bx-f.ax),h=f.az+p*(f.bz-f.az);Number.isNaN(c[u])&&(c[u]=ie(e,f.ax,f.az,f.bx,f.bz));let g=c[u],_=g+Math.PI/2;l.push({x:m+Math.sin(_)*r,z:h+Math.cos(_)*r,axis:g,ordinal:t})}return l}function U(e,t,n){for(let r of e)if((r?.length??0)>=3&&y(t,n,r))return!0;return!1}function W(e,t,n,r){for(let i of e)if(C(i,t,n,r))return!0;return!1}function pe(e,t){let n=fe(e,t);if(n.length===0)return[];let r=t.rng??v(t.seed),i=t.footprints??[],a=t.occluders??[],o=t.occupied,s=O(t.occupyR,t.clearM),c=t.occupyTag??t.seed,l=Math.floor(Number(t.variantCount)),d=Number.isFinite(l)&&l>1,f=d?_(t.variant,l):-1,p=[];for(let m of n){let n=r(),{x:h,z:_}=m,v=m.axis+Math.PI/2;if(!y(h+Math.sin(v)*L,_+Math.cos(v)*L,e)||U(a,h,_)||W(i,h,_,t.clearM)||o&&o.blocks(h,_,s,c))continue;o&&o.add(h,_,s,c);let b=u(n,t.yawMode,t.yawDeg,m.axis);p.push(d?{x:h,z:_,yaw:b,variant:f>=0?f:g(t.seed,m.ordinal,l)}:{x:h,z:_,yaw:b})}return p}function me(e,t){if((e?.length??0)<3)return[];let n=ue(e);if(!(n.d>0))return[];let r=(t.rng??v(t.seed))(),{x:i,z:a}=n;if(U(t.occluders??[],i,a)||W(t.footprints??[],i,a,t.clearM))return[];let o=O(t.occupyR,t.clearM),s=t.occupyTag??t.seed;if(t.occupied&&t.occupied.blocks(i,a,o,s))return[];t.occupied&&t.occupied.add(i,a,o,s);let c=t.yawMode===`aligned`?t.axisAt?t.axisAt(i,a):ae(e,i,a):0,l=u(r,t.yawMode,t.yawDeg,c),d=Math.floor(Number(t.variantCount));if(!Number.isFinite(d)||d<=1)return[{x:i,z:a,yaw:l}];let f=_(t.variant,d);return[{x:i,z:a,yaw:l,variant:f>=0?f:g(t.seed,0,d)}]}var he=.5,G={value:0},ge={value:{r:.62,g:.78,b:.91}};function K(e){G.value=(G.value+(e||0))%3600}var q=null,_e=null;function ve(e){let t=document.createElement(`canvas`);t.width=t.height=1;let n=t.getContext(`2d`);n.fillStyle=`#fff`,n.fillRect(0,0,1,1);let r=new e.CanvasTexture(t);return r.needsUpdate=!0,r}function ye(e){let t=document.createElement(`canvas`);t.width=t.height=256;let n=t.getContext(`2d`),r=n.createImageData(256,256),i=[[1,2,1,0],[2,-1,.7,1.7],[3,2,.4,3.1],[-2,3,.3,5]],a=(e,t)=>{let n=0;for(let[r,a,o,s]of i)n+=o*Math.sin(2*Math.PI*(r*e+a*t)+s);return n},o=1/256;for(let e=0;e<256;e++)for(let t=0;t<256;t++){let n=t/256,i=e/256,s=(a(n+o,i)-a(n-o,i))/(2*o),c=(a(n,i+o)-a(n,i-o))/(2*o),l=.02,u=-s*l,d=-c*l,f=Math.hypot(u,d,1)||1;u/=f,d/=f;let p=(e*256+t)*4;r.data[p]=Math.round((u*.5+.5)*255),r.data[p+1]=Math.round((d*.5+.5)*255),r.data[p+2]=Math.round((1/f*.5+.5)*255),r.data[p+3]=255}n.putImageData(r,0,0);let s=new e.CanvasTexture(t);return s.wrapS=s.wrapT=e.RepeatWrapping,s.anisotropy=4,s.needsUpdate=!0,s}var J=`#include <begin_vertex>`,Y=`#include <normal_fragment_maps>`,X=`#include <map_fragment>`,Z=`#include <roughnessmap_fragment>`,Q=`#include <opaque_fragment>`,be=!1;function $(e){be||(be=!0,console.warn(`[scene-render] water shader: anchor "${e}" not found in this three version — the surface renders matte instead. One line to re-point.`))}function xe(e,t){return t==null?new e.Color(16777215):typeof t==`number`||typeof t==`string`?new e.Color(t):new e.Color(t.r,t.g,t.b)}function Se(e){let t=parseInt((e||`#3f7fb8`).slice(1),16);return{r:(t>>16&255)/255,g:(t>>8&255)/255,b:(t&255)/255}}function Ce(e,t,n){let r={value:Math.max(t.wave_m??1.6,.05)},i={value:t.speed??.05},a={value:t.flow_speed??.5},o={value:t.sky_mix??.55},s={value:Se(t.tint)},c={value:t.map_strength??.75},l={value:n};e.onBeforeCompile=e=>{if(e.uniforms.uTime=G,e.uniforms.uSky=ge,e.uniforms.uWaveM=r,e.uniforms.uSpeed=i,e.uniforms.uFlowSpeed=a,e.uniforms.uSkyMix=o,e.uniforms.uTint=s,e.uniforms.uMapStrength=c,e.uniforms.uMask=l,e.vertexShader.includes(J))e.vertexShader=`attribute vec2 aWaterFlow;
varying vec2 vWaterWorld;
varying vec2 vWaterUv;
varying vec2 vWaterFlow;
`+e.vertexShader.replace(J,`${J}\n  vWaterWorld = ( modelMatrix * vec4( transformed, 1.0 ) ).xz;
  vWaterUv = uv;
  vWaterFlow = aWaterFlow;`);else{$(J);return}e.fragmentShader=`varying vec2 vWaterWorld;
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
`+e.fragmentShader,e.fragmentShader.includes(Y)?e.fragmentShader=e.fragmentShader.replace(Y,`
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
  #endif`):$(Y),e.fragmentShader.includes(X)?e.fragmentShader=e.fragmentShader.replace(X,`${X}\n  diffuseColor.rgb = mix( uTint, diffuseColor.rgb, mix( 1.0, uMapStrength, texture2D( uMask, vWaterUv ).r ) );`):$(X),e.fragmentShader.includes(Z)?e.fragmentShader=e.fragmentShader.replace(Z,`${Z}\n  roughnessFactor = mix( 0.85, roughnessFactor, texture2D( uMask, vWaterUv ).r );`):$(Z),e.fragmentShader.includes(Q)?e.fragmentShader=e.fragmentShader.replace(Q,`
  {
    float wFres = pow( 1.0 - saturate( dot( normalize( vViewPosition ), normal ) ), 3.0 );
    outgoingLight = mix( outgoingLight, uSky,
                         clamp( wFres * uSkyMix, 0.0, 1.0 )
                         * texture2D( uMask, vWaterUv ).r );
  }
  ${Q}`):$(Q)},e.customProgramCacheKey=()=>`anima-water`}function we(e,t){let n=t.material||null,r=n?.class||`matte`,i=r===`water`||r===`ice`,a={roughness:n?.roughness??(i?.08:r===`gloss`?.25:.85),metalness:n?.metalness??(i?.15:.02)};t.map?a.map=t.map:a.color=xe(e,t.color??(i?n?.tint:16777215)),t.transparent&&(a.transparent=!0),t.opacity!==void 0&&(a.opacity=t.opacity),t.side!==void 0&&(a.side=t.side),t.depthWrite!==void 0&&(a.depthWrite=t.depthWrite);let o=new e.MeshStandardMaterial(a);return r===`glow`&&(o.emissive=xe(e,n?.tint??16777215),o.emissiveIntensity=n?.glow??1,t.map&&(o.emissiveMap=t.map)),i&&(q||=ye(e),o.normalMap=q,o.normalScale=new e.Vector2(1,1),_e||=ve(e),Ce(o,n,t.mask||_e)),o}var Te=e({AREA_EPS_M2:()=>AREA_EPS_M2,CLIP_MAX_POINTS:()=>64,CUTOUT_MAX_POINTS:()=>64,CUTOUT_MAX_POLYS:()=>16,FIGURE_HEIGHT_M:()=>FIGURE_HEIGHT_M,MAP_RELIEF_Z_FACTOR:()=>3,MAX_DECORATED_POINTS:()=>MAX_DECORATED_POINTS,SCATTER_CELLS_MAX:()=>M,SCATTER_CELL_M:()=>64,SCATTER_CLEAR_HEIGHT_RATIO:()=>w,SCATTER_MAX_PER_CELL:()=>j,SCATTER_MAX_PER_ENTRY:()=>d,SCATTER_TRIES_PER_POINT:()=>12,STROKE_AMPLITUDE_DEFAULT_M:()=>2,STROKE_SPACING_DEFAULT_M:()=>10,VERIFY_EPS:()=>VERIFY_EPS,WATERFALL_MIN_DROP_M:()=>1,WATERFALL_MIN_SLOPE:()=>WATERFALL_MIN_SLOPE,WATER_FLOW_FACTOR_MIN:()=>WATER_FLOW_FACTOR_MIN,WATER_FLOW_SPEED_DEFAULT_M_S:()=>he,WATER_FLOW_SPEED_MAX_M_S:()=>2,surfaceMaterial:()=>we,updateSurfaceMaterials:()=>K});export{f as C,v as D,p as E,b as O,O as S,k as T,ne as _,me as a,T as b,j as c,y as d,E as f,F as g,N as h,se as i,l as k,d as l,m,we as n,pe as o,D as p,K as r,M as s,Te as t,C as u,P as v,g as w,A as x,te as y};
//# sourceMappingURL=src-BsAtQdTm.js.map