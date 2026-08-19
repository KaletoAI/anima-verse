import{i as e}from"./react-BRNZa73l.js";var t=315,n=45,r=.35,i=1,a=1,o=Math.PI/180;function s(e,t){return typeof e==`number`&&Number.isFinite(e)?e:t}function c(e,t,n){let r=e[t]?.[n];return typeof r==`number`&&Number.isFinite(r)?r:0}function l(e,l){let u=e?.heights;if(!u||u.length<2)return null;let d=u.length,f=u[0]?.length||0;if(f<2)return null;let p=e?.step_m??0;if(!(p>0))return null;let m=s(l?.azimuthDeg,t)*o,h=Math.min(90,Math.max(a,s(l?.altitudeDeg,n)))*o,g=Math.min(1,Math.max(0,s(l?.maxAlpha,r))),_=Math.max(0,s(l?.zFactor,i)),v=Math.cos(h),y=v*Math.sin(m),b=Math.sin(h),x=-v*Math.cos(m),S=b,C=new Uint8ClampedArray(f*d*4);for(let e=0;e<d;e+=1){let t=e>0?e-1:e,n=e<d-1?e+1:e,r=(n-t)*p;for(let i=0;i<f;i+=1){let a=i>0?i-1:i,o=i<f-1?i+1:i,s=(o-a)*p,l=_*(c(u,e,o)-c(u,e,a))/s,d=_*(c(u,n,i)-c(u,t,i))/r,m=Math.sqrt(l*l+d*d),h=Math.sqrt(m*m+1),v=(-l*y+b-d*x)/h,w=Math.min(1,.5*(v>0?v:0)/S),T=Math.round(255*w),E=Math.round(255*g*(m/h)),D=(e*f+i)*4;C[D]=T,C[D+1]=T,C[D+2]=T,C[D+3]=E}}return{cols:f,rows:d,data:C}}var u={value:0},d={value:{r:.62,g:.78,b:.91}};function f(e){u.value=(u.value+(e||0))%3600}var p=null,m=null;function h(e){let t=document.createElement(`canvas`);t.width=t.height=1;let n=t.getContext(`2d`);n.fillStyle=`#fff`,n.fillRect(0,0,1,1);let r=new e.CanvasTexture(t);return r.needsUpdate=!0,r}function g(e){let t=document.createElement(`canvas`);t.width=t.height=256;let n=t.getContext(`2d`),r=n.createImageData(256,256),i=[[1,2,1,0],[2,-1,.7,1.7],[3,2,.4,3.1],[-2,3,.3,5]],a=(e,t)=>{let n=0;for(let[r,a,o,s]of i)n+=o*Math.sin(2*Math.PI*(r*e+a*t)+s);return n},o=1/256;for(let e=0;e<256;e++)for(let t=0;t<256;t++){let n=t/256,i=e/256,s=(a(n+o,i)-a(n-o,i))/(2*o),c=(a(n,i+o)-a(n,i-o))/(2*o),l=.02,u=-s*l,d=-c*l,f=Math.hypot(u,d,1)||1;u/=f,d/=f;let p=(e*256+t)*4;r.data[p]=Math.round((u*.5+.5)*255),r.data[p+1]=Math.round((d*.5+.5)*255),r.data[p+2]=Math.round((1/f*.5+.5)*255),r.data[p+3]=255}n.putImageData(r,0,0);let s=new e.CanvasTexture(t);return s.wrapS=s.wrapT=e.RepeatWrapping,s.needsUpdate=!0,s}var _=`#include <begin_vertex>`,v=`#include <normal_fragment_maps>`,y=`#include <map_fragment>`,b=`#include <roughnessmap_fragment>`,x=`#include <opaque_fragment>`,S=!1;function C(e){S||(S=!0,console.warn(`[scene-render] water shader: anchor "${e}" not found in this three version — the surface renders matte instead. One line to re-point.`))}function w(e,t){return t==null?new e.Color(16777215):typeof t==`number`||typeof t==`string`?new e.Color(t):new e.Color(t.r,t.g,t.b)}function T(e){let t=parseInt((e||`#3f7fb8`).slice(1),16);return{r:(t>>16&255)/255,g:(t>>8&255)/255,b:(t&255)/255}}function E(e,t,n){let r={value:Math.max(t.wave_m??1.6,.05)},i={value:t.speed??.05},a={value:t.sky_mix??.55},o={value:T(t.tint)},s={value:t.map_strength??.75},c={value:n};e.onBeforeCompile=e=>{if(e.uniforms.uTime=u,e.uniforms.uSky=d,e.uniforms.uWaveM=r,e.uniforms.uSpeed=i,e.uniforms.uSkyMix=a,e.uniforms.uTint=o,e.uniforms.uMapStrength=s,e.uniforms.uMask=c,e.vertexShader.includes(_))e.vertexShader=`varying vec2 vWaterWorld;
varying vec2 vWaterUv;
`+e.vertexShader.replace(_,`${_}\n  vWaterWorld = ( modelMatrix * vec4( transformed, 1.0 ) ).xz;
  vWaterUv = uv;`);else{C(_);return}e.fragmentShader=`varying vec2 vWaterWorld;
varying vec2 vWaterUv;
uniform float uTime;
uniform vec3 uSky;
uniform float uWaveM;
uniform float uSpeed;
uniform float uSkyMix;
uniform vec3 uTint;
uniform float uMapStrength;
uniform sampler2D uMask;
`+e.fragmentShader,e.fragmentShader.includes(v)?e.fragmentShader=e.fragmentShader.replace(v,`
  // tbn stammt aus normal_fragment_begin und existiert nur mit diesem
  // Define — ohne die Klammer waere es ein Compile-Fehler statt eines
  // matten Materials.
  #ifdef USE_NORMALMAP_TANGENTSPACE
  {
    float wMask = texture2D( uMask, vWaterUv ).r;
    // Der Versatz wird durch die Wellenlänge der JEWEILIGEN Lage geteilt —
    // dadurch ist uSpeed echte METER PRO SEKUNDE, und beide Lagen driften
    // gleich schnell, obwohl ihre Wellenlängen verschieden sind. Ohne die
    // Division war uSpeed "Wellenlängen pro Sekunde": 0,05 hieß ein Wellenberg
    // alle 20 Sekunden, auf der Karte 1,7 cm/s — vorhanden, aber unsichtbar.
    float wDriftA = uTime * uSpeed / uWaveM;
    float wDriftB = uTime * uSpeed / ( uWaveM * 0.63 );
    vec2 wUvA = vWaterWorld / uWaveM + vec2( wDriftA, wDriftA * 0.6 );
    vec2 wUvB = vWaterWorld / ( uWaveM * 0.63 ) - vec2( wDriftB * 0.8, wDriftB * 1.3 );
    vec3 wN = normalize( ( texture2D( normalMap, wUvA ).xyz * 2.0 - 1.0 )
                       + ( texture2D( normalMap, wUvB ).xyz * 2.0 - 1.0 ) );
    wN = mix( vec3( 0.0, 0.0, 1.0 ), wN, wMask );
    wN.xy *= normalScale;
    normal = normalize( tbn * wN );
  }
  #endif`):C(v),e.fragmentShader.includes(y)?e.fragmentShader=e.fragmentShader.replace(y,`${y}\n  diffuseColor.rgb = mix( uTint, diffuseColor.rgb, mix( 1.0, uMapStrength, texture2D( uMask, vWaterUv ).r ) );`):C(y),e.fragmentShader.includes(b)?e.fragmentShader=e.fragmentShader.replace(b,`${b}\n  roughnessFactor = mix( 0.85, roughnessFactor, texture2D( uMask, vWaterUv ).r );`):C(b),e.fragmentShader.includes(x)?e.fragmentShader=e.fragmentShader.replace(x,`
  {
    float wFres = pow( 1.0 - saturate( dot( normalize( vViewPosition ), normal ) ), 3.0 );
    outgoingLight = mix( outgoingLight, uSky,
                         clamp( wFres * uSkyMix, 0.0, 1.0 )
                         * texture2D( uMask, vWaterUv ).r );
  }
  ${x}`):C(x)},e.customProgramCacheKey=()=>`anima-water`}function D(e,t){let n=t.material||null,r=n?.class||`matte`,i=r===`water`||r===`ice`,a={roughness:n?.roughness??(i?.08:r===`gloss`?.25:.85),metalness:n?.metalness??(i?.15:.02)};t.map?a.map=t.map:a.color=w(e,t.color??(i?n?.tint:16777215)),t.transparent&&(a.transparent=!0),t.opacity!==void 0&&(a.opacity=t.opacity),t.side!==void 0&&(a.side=t.side);let o=new e.MeshStandardMaterial(a);return r===`glow`&&(o.emissive=w(e,n?.tint??16777215),o.emissiveIntensity=n?.glow??1,t.map&&(o.emissiveMap=t.map)),i&&(p||=g(e),o.normalMap=p,o.normalScale=new e.Vector2(1,1),m||=h(e),E(o,n,t.mask||m)),o}var O=e({AREA_EPS_M2:()=>AREA_EPS_M2,AREA_POLYGON_OFFSET:()=>1,CLIP_MAX_POINTS:()=>64,CUTOUT_MAX_POINTS:()=>64,CUTOUT_MAX_POLYS:()=>16,GRID_MAX_CELLS:()=>GRID_MAX_CELLS,MAP_RELIEF_Z_FACTOR:()=>3,SCATTER_CELLS_MAX:()=>SCATTER_CELLS_MAX,SCATTER_CELL_M:()=>64,SCATTER_MAX_PER_CELL:()=>SCATTER_MAX_PER_CELL,SCATTER_MAX_PER_ENTRY:()=>SCATTER_MAX_PER_ENTRY,SCATTER_TRIES_PER_POINT:()=>12,TERRAIN_CELLS:()=>16,VERIFY_EPS:()=>VERIFY_EPS,surfaceMaterial:()=>D,updateSurfaceMaterials:()=>f});export{l as i,D as n,f as r,O as t};
//# sourceMappingURL=src-fgd9zMUh.js.map