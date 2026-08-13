import{i as e}from"./react-BRNZa73l.js";var t={value:0},n={value:{r:.62,g:.78,b:.91}};function r(e){t.value=(t.value+(e||0))%3600}var i=null,a=null;function o(e){let t=document.createElement(`canvas`);t.width=t.height=1;let n=t.getContext(`2d`);n.fillStyle=`#fff`,n.fillRect(0,0,1,1);let r=new e.CanvasTexture(t);return r.needsUpdate=!0,r}function s(e){let t=document.createElement(`canvas`);t.width=t.height=256;let n=t.getContext(`2d`),r=n.createImageData(256,256),i=[[1,2,1,0],[2,-1,.7,1.7],[3,2,.4,3.1],[-2,3,.3,5]],a=(e,t)=>{let n=0;for(let[r,a,o,s]of i)n+=o*Math.sin(2*Math.PI*(r*e+a*t)+s);return n},o=1/256;for(let e=0;e<256;e++)for(let t=0;t<256;t++){let n=t/256,i=e/256,s=(a(n+o,i)-a(n-o,i))/(2*o),c=(a(n,i+o)-a(n,i-o))/(2*o),l=.02,u=-s*l,d=-c*l,f=Math.hypot(u,d,1)||1;u/=f,d/=f;let p=(e*256+t)*4;r.data[p]=Math.round((u*.5+.5)*255),r.data[p+1]=Math.round((d*.5+.5)*255),r.data[p+2]=Math.round((1/f*.5+.5)*255),r.data[p+3]=255}n.putImageData(r,0,0);let s=new e.CanvasTexture(t);return s.wrapS=s.wrapT=e.RepeatWrapping,s.needsUpdate=!0,s}var c=`#include <begin_vertex>`,l=`#include <normal_fragment_maps>`,u=`#include <map_fragment>`,d=`#include <roughnessmap_fragment>`,f=`#include <opaque_fragment>`,p=!1;function m(e){p||(p=!0,console.warn(`[scene-render] water shader: anchor "${e}" not found in this three version — the surface renders matte instead. One line to re-point.`))}function h(e,t){return t==null?new e.Color(16777215):typeof t==`number`||typeof t==`string`?new e.Color(t):new e.Color(t.r,t.g,t.b)}function g(e){let t=parseInt((e||`#3f7fb8`).slice(1),16);return{r:(t>>16&255)/255,g:(t>>8&255)/255,b:(t&255)/255}}function _(e,r,i){let a={value:Math.max(r.wave_m??1.6,.05)},o={value:r.speed??.05},s={value:r.sky_mix??.55},p={value:g(r.tint)},h={value:r.map_strength??.75},_={value:i};e.onBeforeCompile=e=>{if(e.uniforms.uTime=t,e.uniforms.uSky=n,e.uniforms.uWaveM=a,e.uniforms.uSpeed=o,e.uniforms.uSkyMix=s,e.uniforms.uTint=p,e.uniforms.uMapStrength=h,e.uniforms.uMask=_,e.vertexShader.includes(c))e.vertexShader=`varying vec2 vWaterWorld;
varying vec2 vWaterUv;
`+e.vertexShader.replace(c,`${c}\n  vWaterWorld = ( modelMatrix * vec4( transformed, 1.0 ) ).xz;
  vWaterUv = uv;`);else{m(c);return}e.fragmentShader=`varying vec2 vWaterWorld;
varying vec2 vWaterUv;
uniform float uTime;
uniform vec3 uSky;
uniform float uWaveM;
uniform float uSpeed;
uniform float uSkyMix;
uniform vec3 uTint;
uniform float uMapStrength;
uniform sampler2D uMask;
`+e.fragmentShader,e.fragmentShader.includes(l)?e.fragmentShader=e.fragmentShader.replace(l,`
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
  #endif`):m(l),e.fragmentShader.includes(u)?e.fragmentShader=e.fragmentShader.replace(u,`${u}\n  diffuseColor.rgb = mix( uTint, diffuseColor.rgb, mix( 1.0, uMapStrength, texture2D( uMask, vWaterUv ).r ) );`):m(u),e.fragmentShader.includes(d)?e.fragmentShader=e.fragmentShader.replace(d,`${d}\n  roughnessFactor = mix( 0.85, roughnessFactor, texture2D( uMask, vWaterUv ).r );`):m(d),e.fragmentShader.includes(f)?e.fragmentShader=e.fragmentShader.replace(f,`
  {
    float wFres = pow( 1.0 - saturate( dot( normalize( vViewPosition ), normal ) ), 3.0 );
    outgoingLight = mix( outgoingLight, uSky,
                         clamp( wFres * uSkyMix, 0.0, 1.0 )
                         * texture2D( uMask, vWaterUv ).r );
  }
  ${f}`):m(f)},e.customProgramCacheKey=()=>`anima-water`}function v(e,t){let n=t.material||null,r=n?.class||`matte`,c=r===`water`||r===`ice`,l={roughness:n?.roughness??(c?.08:r===`gloss`?.25:.85),metalness:n?.metalness??(c?.15:.02)};t.map?l.map=t.map:l.color=h(e,t.color??(c?n?.tint:16777215)),t.transparent&&(l.transparent=!0),t.opacity!==void 0&&(l.opacity=t.opacity),t.side!==void 0&&(l.side=t.side);let u=new e.MeshStandardMaterial(l);return r===`glow`&&(u.emissive=h(e,n?.tint??16777215),u.emissiveIntensity=n?.glow??1,t.map&&(u.emissiveMap=t.map)),c&&(i||=s(e),u.normalMap=i,u.normalScale=new e.Vector2(1,1),a||=o(e),_(u,n,t.mask||a)),u}var y=e({AREA_EPS_M2:()=>AREA_EPS_M2,AREA_POLYGON_OFFSET:()=>1,CLIP_MAX_POINTS:()=>64,CUTOUT_MAX_POINTS:()=>64,CUTOUT_MAX_POLYS:()=>16,GRID_MAX_CELLS:()=>GRID_MAX_CELLS,SCATTER_MAX_PER_ENTRY:()=>SCATTER_MAX_PER_ENTRY,SCATTER_TRIES_PER_POINT:()=>12,TERRAIN_CELLS:()=>16,VERIFY_EPS:()=>VERIFY_EPS,surfaceMaterial:()=>v,updateSurfaceMaterials:()=>r});export{v as n,r,y as t};
//# sourceMappingURL=src-NAmxZVAd.js.map