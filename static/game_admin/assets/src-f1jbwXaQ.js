import{i as e}from"./react-BRNZa73l.js";var t=315,n=45,r=.35,i=1,a=1,o=Math.PI/180;function s(e,t){return typeof e==`number`&&Number.isFinite(e)?e:t}function c(e,t,n){let r=e[t]?.[n];return typeof r==`number`&&Number.isFinite(r)?r:0}function l(e,l){let u=e?.heights;if(!u||u.length<2)return null;let d=u.length,f=u[0]?.length||0;if(f<2)return null;let p=e?.step_m??0;if(!(p>0))return null;let m=s(l?.azimuthDeg,t)*o,h=Math.min(90,Math.max(a,s(l?.altitudeDeg,n)))*o,g=Math.min(1,Math.max(0,s(l?.maxAlpha,r))),_=Math.max(0,s(l?.zFactor,i)),v=Math.cos(h),y=v*Math.sin(m),b=Math.sin(h),x=-v*Math.cos(m),S=b,C=new Uint8ClampedArray(f*d*4);for(let e=0;e<d;e+=1){let t=e>0?e-1:e,n=e<d-1?e+1:e,r=(n-t)*p;for(let i=0;i<f;i+=1){let a=i>0?i-1:i,o=i<f-1?i+1:i,s=(o-a)*p,l=_*(c(u,e,o)-c(u,e,a))/s,d=_*(c(u,n,i)-c(u,t,i))/r,m=Math.sqrt(l*l+d*d),h=Math.sqrt(m*m+1),v=(-l*y+b-d*x)/h,w=Math.min(1,.5*(v>0?v:0)/S),T=Math.round(255*w),E=Math.round(255*g*(m/h)),D=(e*f+i)*4;C[D]=T,C[D+1]=T,C[D+2]=T,C[D+3]=E}}return{cols:f,rows:d,data:C}}var u=.5,d={value:0},f={value:{r:.62,g:.78,b:.91}};function p(e){d.value=(d.value+(e||0))%3600}var m=null,h=null;function g(e){let t=document.createElement(`canvas`);t.width=t.height=1;let n=t.getContext(`2d`);n.fillStyle=`#fff`,n.fillRect(0,0,1,1);let r=new e.CanvasTexture(t);return r.needsUpdate=!0,r}function _(e){let t=document.createElement(`canvas`);t.width=t.height=256;let n=t.getContext(`2d`),r=n.createImageData(256,256),i=[[1,2,1,0],[2,-1,.7,1.7],[3,2,.4,3.1],[-2,3,.3,5]],a=(e,t)=>{let n=0;for(let[r,a,o,s]of i)n+=o*Math.sin(2*Math.PI*(r*e+a*t)+s);return n},o=1/256;for(let e=0;e<256;e++)for(let t=0;t<256;t++){let n=t/256,i=e/256,s=(a(n+o,i)-a(n-o,i))/(2*o),c=(a(n,i+o)-a(n,i-o))/(2*o),l=.02,u=-s*l,d=-c*l,f=Math.hypot(u,d,1)||1;u/=f,d/=f;let p=(e*256+t)*4;r.data[p]=Math.round((u*.5+.5)*255),r.data[p+1]=Math.round((d*.5+.5)*255),r.data[p+2]=Math.round((1/f*.5+.5)*255),r.data[p+3]=255}n.putImageData(r,0,0);let s=new e.CanvasTexture(t);return s.wrapS=s.wrapT=e.RepeatWrapping,s.anisotropy=4,s.needsUpdate=!0,s}var v=`#include <begin_vertex>`,y=`#include <normal_fragment_maps>`,b=`#include <map_fragment>`,x=`#include <roughnessmap_fragment>`,S=`#include <opaque_fragment>`,C=!1;function w(e){C||(C=!0,console.warn(`[scene-render] water shader: anchor "${e}" not found in this three version — the surface renders matte instead. One line to re-point.`))}function T(e,t){return t==null?new e.Color(16777215):typeof t==`number`||typeof t==`string`?new e.Color(t):new e.Color(t.r,t.g,t.b)}function E(e){let t=parseInt((e||`#3f7fb8`).slice(1),16);return{r:(t>>16&255)/255,g:(t>>8&255)/255,b:(t&255)/255}}function D(e,t,n){let r={value:Math.max(t.wave_m??1.6,.05)},i={value:t.speed??.05},a={value:t.flow_speed??.5},o={value:t.sky_mix??.55},s={value:E(t.tint)},c={value:t.map_strength??.75},l={value:n};e.onBeforeCompile=e=>{if(e.uniforms.uTime=d,e.uniforms.uSky=f,e.uniforms.uWaveM=r,e.uniforms.uSpeed=i,e.uniforms.uFlowSpeed=a,e.uniforms.uSkyMix=o,e.uniforms.uTint=s,e.uniforms.uMapStrength=c,e.uniforms.uMask=l,e.vertexShader.includes(v))e.vertexShader=`attribute vec2 aWaterFlow;
varying vec2 vWaterWorld;
varying vec2 vWaterUv;
varying vec2 vWaterFlow;
`+e.vertexShader.replace(v,`${v}\n  vWaterWorld = ( modelMatrix * vec4( transformed, 1.0 ) ).xz;
  vWaterUv = uv;
  vWaterFlow = aWaterFlow;`);else{w(v);return}e.fragmentShader=`varying vec2 vWaterWorld;
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
`+e.fragmentShader,e.fragmentShader.includes(y)?e.fragmentShader=e.fragmentShader.replace(y,`
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
  #endif`):w(y),e.fragmentShader.includes(b)?e.fragmentShader=e.fragmentShader.replace(b,`${b}\n  diffuseColor.rgb = mix( uTint, diffuseColor.rgb, mix( 1.0, uMapStrength, texture2D( uMask, vWaterUv ).r ) );`):w(b),e.fragmentShader.includes(x)?e.fragmentShader=e.fragmentShader.replace(x,`${x}\n  roughnessFactor = mix( 0.85, roughnessFactor, texture2D( uMask, vWaterUv ).r );`):w(x),e.fragmentShader.includes(S)?e.fragmentShader=e.fragmentShader.replace(S,`
  {
    float wFres = pow( 1.0 - saturate( dot( normalize( vViewPosition ), normal ) ), 3.0 );
    outgoingLight = mix( outgoingLight, uSky,
                         clamp( wFres * uSkyMix, 0.0, 1.0 )
                         * texture2D( uMask, vWaterUv ).r );
  }
  ${S}`):w(S)},e.customProgramCacheKey=()=>`anima-water`}function O(e,t){let n=t.material||null,r=n?.class||`matte`,i=r===`water`||r===`ice`,a={roughness:n?.roughness??(i?.08:r===`gloss`?.25:.85),metalness:n?.metalness??(i?.15:.02)};t.map?a.map=t.map:a.color=T(e,t.color??(i?n?.tint:16777215)),t.transparent&&(a.transparent=!0),t.opacity!==void 0&&(a.opacity=t.opacity),t.side!==void 0&&(a.side=t.side),t.depthWrite!==void 0&&(a.depthWrite=t.depthWrite);let o=new e.MeshStandardMaterial(a);return r===`glow`&&(o.emissive=T(e,n?.tint??16777215),o.emissiveIntensity=n?.glow??1,t.map&&(o.emissiveMap=t.map)),i&&(m||=_(e),o.normalMap=m,o.normalScale=new e.Vector2(1,1),h||=g(e),D(o,n,t.mask||h)),o}var k=e({AREA_EPS_M2:()=>AREA_EPS_M2,CLIP_MAX_POINTS:()=>64,CUTOUT_MAX_POINTS:()=>64,CUTOUT_MAX_POLYS:()=>16,FIGURE_HEIGHT_M:()=>FIGURE_HEIGHT_M,MAP_RELIEF_Z_FACTOR:()=>3,SCATTER_CELLS_MAX:()=>SCATTER_CELLS_MAX,SCATTER_CELL_M:()=>64,SCATTER_CLEAR_HEIGHT_RATIO:()=>SCATTER_CLEAR_HEIGHT_RATIO,SCATTER_MAX_PER_CELL:()=>SCATTER_MAX_PER_CELL,SCATTER_MAX_PER_ENTRY:()=>SCATTER_MAX_PER_ENTRY,SCATTER_TRIES_PER_POINT:()=>12,VERIFY_EPS:()=>VERIFY_EPS,WATERFALL_MIN_DROP_M:()=>1,WATERFALL_MIN_SLOPE:()=>WATERFALL_MIN_SLOPE,WATER_FLOW_FACTOR_MIN:()=>WATER_FLOW_FACTOR_MIN,WATER_FLOW_SPEED_DEFAULT_M_S:()=>u,WATER_FLOW_SPEED_MAX_M_S:()=>2,surfaceMaterial:()=>O,updateSurfaceMaterials:()=>p});export{l as i,O as n,p as r,k as t};
//# sourceMappingURL=src-f1jbwXaQ.js.map