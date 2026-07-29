/**
 * materials — wie eine Oberflächen-ART gemalt wird, für BEIDE Renderer.
 *
 * Das Paket sagte im Kopf lange „Geometrie hier, Material vom Aufrufer". Diese
 * Zeile gilt für Primitive weiter; das Aussehen einer ART ist aber geteilte
 * Wahrheit — beide Renderer zeigen denselben See. Sie lag bisher doppelt vor
 * (client3d `sceneRecipe.plateMaterial/wallMaterial`, Admin-Vorschau inline in
 * `FloorPlanPreview`), mit unterschiedlichen Vorgaben. Nur Sicht-Zustand
 * (Kamera, LOD, Fades, Culling, Labels) bleibt pro App.
 *
 * Klasse `water` (plan-water-rendering.md): Wasser wird nicht an seiner Farbe
 * erkannt, sondern daran, was es SPIEGELT und wie es sich BEWEGT. Eine
 * Colormap auf `roughness 0.85` liefert beides nicht. Statt eines eigenen
 * ShaderMaterials wird das Standardmaterial gepatcht (`onBeforeCompile`) —
 * damit bleiben Lichter, Schatten, Nebel, Tone-Mapping und die
 * Opazitäts-Steuerung der Kachel-Fades unangetastet.
 *
 * three ist überall ein PARAMETER, nie ein Import.
 */
import type { Material, Texture } from 'three'

type THREE = typeof import('three')

/** Deklaration einer Art (Bibliothek → /assets/surface-textures).
 *
 *  Nur `water`/`ice` brauchen den Shader, und nur wegen der Bewegung bzw. der
 *  Fresnel-Spiegelung. `gloss` und `glow` sind reine Materialwerte — das
 *  Standardmaterial kann beides von Haus aus. */
export interface SurfaceMaterialSpec {
  class: 'matte' | 'water' | 'ice' | 'gloss' | 'glow'
  tint?: string
  map_strength?: number
  wave_m?: number
  speed?: number
  sky_mix?: number
  roughness?: number
  metalness?: number
  /** Leuchtstärke der Klasse `glow` (0 = aus). */
  glow?: number
}

export interface SurfaceMaterialOptions {
  /** Deklaration der Art; fehlt = matt, also genau wie bisher. */
  material?: SurfaceMaterialSpec | null
  map?: Texture | null
  /** Maske für ZUSAMMENGESETZTE Flächen (Küste): rot = 1, wo die Klasse gilt,
   *  0 sonst. Eine Zusammenstellung ist EINE Platte mit EINER Textur — ohne
   *  Maske kräuselte der Sandstreifen einer Küste mit. Fehlt sie, gilt die
   *  Klasse überall. Gelesen über die KACHEL-UV, nicht über die Weltlage: die
   *  Maske gehört zur Kachel, die Wellen laufen über Kachelgrenzen hinweg. */
  mask?: Texture | null
  /** Fallback-Farbe ohne Textur (Payload-Style): Zahl 0xrrggbb, '#rrggbb'
   *  oder eine fertige THREE.Color — die Aufrufer haben alle drei. */
  color?: number | string | { r: number; g: number; b: number }
  transparent?: boolean
  opacity?: number
  side?: number
  /** Welt-Meter pro Textur-Kachel — nur informativ für die Wellenlänge. */
  roughnessOverride?: number
}

// ── Geteilte Uniforms ───────────────────────────────────────────────────
// EIN Objekt für alle Wasserflächen: `updateSurfaceMaterials` rückt die Zeit
// vor, und 50 Kacheln kosten damit so viel wie eine.
const uTime = { value: 0 }
const uSky = { value: { r: 0.62, g: 0.78, b: 0.91 } }

/** Zeit vorrücken — einmal pro Frame, aus der Render-Schleife der App. */
export function updateSurfaceMaterials(dt: number): void {
  uTime.value = (uTime.value + (dt || 0)) % 3600
}

/** Himmelsfarbe für den Fresnel-Anteil (0xrrggbb). Der 3D-Client reicht seine
 *  Tageszeit-Farbe durch, die Admin-Vorschau einen festen Tagwert — Wasser
 *  wird abends orange und nachts dunkel, ohne dass jemand das extra baut. */
export function setSurfaceSky(hex: number): void {
  uSky.value = {
    r: ((hex >> 16) & 255) / 255,
    g: ((hex >> 8) & 255) / 255,
    b: (hex & 255) / 255,
  }
}

// ── Wellen-Normalmap ────────────────────────────────────────────────────
// Prozedural, nahtlos, deterministisch: Summe von Sinus-Lagen mit GANZZAHLIGEN
// Frequenzen kachelt garantiert. Kein Asset, kein Download.
let waveNormal: Texture | null = null
/** 1×1 weiß: ohne Maske gilt die Klasse überall. Eine Ersatztextur statt eines
 *  zweiten Shader-Zweigs — so bleibt es EIN Programm für alle Wasserflächen. */
let fullMask: Texture | null = null

function makeFullMask(T: THREE): Texture {
  const c = document.createElement('canvas')
  c.width = c.height = 1
  const cx = c.getContext('2d')!
  cx.fillStyle = '#fff'
  cx.fillRect(0, 0, 1, 1)
  const tex = new T.CanvasTexture(c)
  tex.needsUpdate = true
  return tex
}

function makeWaveNormal(T: THREE): Texture {
  const N = 256
  const canvas = document.createElement('canvas')
  canvas.width = canvas.height = N
  const ctx = canvas.getContext('2d')!
  const img = ctx.createImageData(N, N)
  // fx, fy ganzzahlig -> die Höhe ist auf dem Einheitsquadrat periodisch.
  const layers: [number, number, number, number][] = [
    // fx, fy, Amplitude, Phase
    [1, 2, 1.0, 0.0],
    [2, -1, 0.7, 1.7],
    [3, 2, 0.4, 3.1],
    [-2, 3, 0.3, 5.0],
  ]
  const h = (u: number, v: number) => {
    let s = 0
    for (const [fx, fy, a, ph] of layers) {
      s += a * Math.sin(2 * Math.PI * (fx * u + fy * v) + ph)
    }
    return s
  }
  const d = 1 / N
  for (let y = 0; y < N; y++) {
    for (let x = 0; x < N; x++) {
      const u = x / N
      const v = y / N
      // Zentrale Differenzen -> Gradient -> Normale (Tangentenraum, +z oben).
      const dx = (h(u + d, v) - h(u - d, v)) / (2 * d)
      const dy = (h(u, v + d) - h(u, v - d)) / (2 * d)
      const sc = 0.02
      let nx = -dx * sc
      let ny = -dy * sc
      const nz = 1
      const len = Math.hypot(nx, ny, nz) || 1
      nx /= len
      ny /= len
      const i = (y * N + x) * 4
      img.data[i] = Math.round((nx * 0.5 + 0.5) * 255)
      img.data[i + 1] = Math.round((ny * 0.5 + 0.5) * 255)
      img.data[i + 2] = Math.round((nz / len * 0.5 + 0.5) * 255)
      img.data[i + 3] = 255
    }
  }
  ctx.putImageData(img, 0, 0)
  const tex = new T.CanvasTexture(canvas)
  tex.wrapS = tex.wrapT = T.RepeatWrapping
  tex.needsUpdate = true
  return tex
}

// ── Shader-Patch ────────────────────────────────────────────────────────
// Die drei Anker im Standard-Shader. Findet einer sich nicht (Three-Upgrade),
// wird NUR dieser Teil übersprungen — lieber matt als kaputt.
const ANCHOR_VERT = '#include <begin_vertex>'
const ANCHOR_NORMAL =
  'vec3 mapN = texture2D( normalMap, vNormalMapUv ).xyz * 2.0 - 1.0;'
const ANCHOR_MAP = '#include <map_fragment>'
const ANCHOR_ROUGH = '#include <roughnessmap_fragment>'
const ANCHOR_OUT = '#include <opaque_fragment>'

let warned = false
function warnOnce(what: string): void {
  if (warned) return
  warned = true
  console.warn(`[scene-render] water shader: anchor "${what}" not found in this `
    + 'three version — the surface renders matte instead. One line to re-point.')
}

/** Whatever the caller has -> a THREE.Color. */
function toColor(T: THREE, c: number | string | { r: number; g: number; b: number } | undefined) {
  if (c === undefined || c === null) return new T.Color(0xffffff)
  if (typeof c === 'number') return new T.Color(c)
  if (typeof c === 'string') return new T.Color(c)
  return new T.Color(c.r, c.g, c.b)
}

function hex3(hex?: string): { r: number; g: number; b: number } {
  const v = parseInt((hex || '#3f7fb8').slice(1), 16)
  return { r: ((v >> 16) & 255) / 255, g: ((v >> 8) & 255) / 255, b: (v & 255) / 255 }
}

function applyWaterShader(mat: any, spec: SurfaceMaterialSpec,
                          mask: Texture): void {
  const uWave = { value: Math.max(spec.wave_m ?? 1.6, 0.05) }
  const uSpeed = { value: spec.speed ?? 0.05 }
  const uSkyMix = { value: spec.sky_mix ?? 0.55 }
  const uTint = { value: hex3(spec.tint) }
  const uMapStrength = { value: spec.map_strength ?? 0.75 }
  const uMask = { value: mask }

  mat.onBeforeCompile = (shader: any) => {
    shader.uniforms.uTime = uTime
    shader.uniforms.uSky = uSky
    shader.uniforms.uWaveM = uWave
    shader.uniforms.uSpeed = uSpeed
    shader.uniforms.uSkyMix = uSkyMix
    shader.uniforms.uTint = uTint
    shader.uniforms.uMapStrength = uMapStrength
    shader.uniforms.uMask = uMask

    // Zwei eigene Varyings, weil sie zwei verschiedene Dinge sind:
    // vWaterWorld ist die WELTLAGE (die Kräuselung läuft über Kachelgrenzen
    // hinweg, aus Platten-UVs gäbe es eine sichtbare Naht), vWaterUv die
    // KACHEL-UV (die Maske gehört zu dieser einen Kachel).
    if (shader.vertexShader.includes(ANCHOR_VERT)) {
      shader.vertexShader = 'varying vec2 vWaterWorld;\nvarying vec2 vWaterUv;\n'
        + shader.vertexShader.replace(ANCHOR_VERT,
          `${ANCHOR_VERT}\n  vWaterWorld = ( modelMatrix * vec4( transformed, 1.0 ) ).xz;`
          + '\n  vWaterUv = uv;')
    } else {
      warnOnce(ANCHOR_VERT)
      return
    }

    shader.fragmentShader = 'varying vec2 vWaterWorld;\nvarying vec2 vWaterUv;\n'
      + 'uniform float uTime;\nuniform vec3 uSky;\nuniform float uWaveM;\n'
      + 'uniform float uSpeed;\nuniform float uSkyMix;\nuniform vec3 uTint;\n'
      + 'uniform float uMapStrength;\nuniform sampler2D uMask;\n'
      + shader.fragmentShader

    // 1) Zwei gegenläufig scrollende Lagen derselben Normalmap — auf den
    //    Wasseranteil begrenzt, sonst kräuselt der Sand einer Küste mit.
    if (shader.fragmentShader.includes(ANCHOR_NORMAL)) {
      shader.fragmentShader = shader.fragmentShader.replace(ANCHOR_NORMAL, `
    float wMask = texture2D( uMask, vWaterUv ).r;
    vec2 wUvA = vWaterWorld / uWaveM + vec2( uTime * uSpeed, uTime * uSpeed * 0.6 );
    vec2 wUvB = vWaterWorld / ( uWaveM * 0.63 ) - vec2( uTime * uSpeed * 0.8, uTime * uSpeed * 1.3 );
    vec3 mapN = normalize( ( texture2D( normalMap, wUvA ).xyz * 2.0 - 1.0 )
                         + ( texture2D( normalMap, wUvB ).xyz * 2.0 - 1.0 ) );
    mapN = mix( vec3( 0.0, 0.0, 1.0 ), mapN, wMask );`)
    } else {
      warnOnce(ANCHOR_NORMAL)
    }

    // 2) Textur gegen den Grundton mischen — eine generierte Wassertextur mit
    //    eingebackenen Glanzlichtern soll nicht mit dem Shader konkurrieren.
    //    Außerhalb der Maske bleibt die Textur unangetastet.
    if (shader.fragmentShader.includes(ANCHOR_MAP)) {
      shader.fragmentShader = shader.fragmentShader.replace(ANCHOR_MAP,
        `${ANCHOR_MAP}\n  diffuseColor.rgb = mix( uTint, diffuseColor.rgb,`
        + ' mix( 1.0, uMapStrength, texture2D( uMask, vWaterUv ).r ) );')
    } else {
      warnOnce(ANCHOR_MAP)
    }

    // 2b) Rauheit nur im Wasseranteil absenken — sonst glänzt der Sandstreifen
    //     wie nasses Glas.
    if (shader.fragmentShader.includes(ANCHOR_ROUGH)) {
      shader.fragmentShader = shader.fragmentShader.replace(ANCHOR_ROUGH,
        `${ANCHOR_ROUGH}\n  roughnessFactor = mix( 0.85, roughnessFactor,`
        + ' texture2D( uMask, vWaterUv ).r );')
    } else {
      warnOnce(ANCHOR_ROUGH)
    }

    // 3) Fresnel Richtung Himmelsfarbe. NUR die Farbe — Alpha bleibt der
    //    Standardpfad, sonst bräche die Fade-Steuerung der Kacheln.
    if (shader.fragmentShader.includes(ANCHOR_OUT)) {
      shader.fragmentShader = shader.fragmentShader.replace(ANCHOR_OUT, `
  {
    float wFres = pow( 1.0 - saturate( dot( normalize( vViewPosition ), normal ) ), 3.0 );
    outgoingLight = mix( outgoingLight, uSky,
                         clamp( wFres * uSkyMix, 0.0, 1.0 )
                         * texture2D( uMask, vWaterUv ).r );
  }
  ${ANCHOR_OUT}`)
    } else {
      warnOnce(ANCHOR_OUT)
    }
  }
  // Ohne den Schlüssel kompiliert three je Material neu.
  mat.customProgramCacheKey = () => 'anima-water'
}

/**
 * Das Material EINER Oberfläche. `matte` (Default) ist exakt das bisherige
 * Standardmaterial — die Funktion ist dann nur die eine Stelle, an der die
 * Vorgaben stehen statt dreier Stellen in zwei Apps.
 */
export function surfaceMaterial(T: THREE, opts: SurfaceMaterialOptions): Material {
  const spec = opts.material || null
  const cls = spec?.class || 'matte'
  // Wasser und Eis sind dieselbe Fläche — Eis steht nur still (speed 0). Das
  // ist keine Bequemlichkeit: eine gefrorene Fläche spiegelt und trägt
  // Oberflächenstruktur, sie fließt bloß nicht.
  const rippled = cls === 'water' || cls === 'ice'
  const params: Record<string, unknown> = {
    roughness: spec?.roughness ?? (rippled ? 0.08 : cls === 'gloss' ? 0.25 : 0.85),
    metalness: spec?.metalness ?? (rippled ? 0.15 : 0.02),
  }
  if (opts.map) params.map = opts.map
  else params.color = toColor(T, opts.color ?? (rippled ? spec?.tint : 0xffffff))
  if (opts.transparent) params.transparent = true
  if (opts.opacity !== undefined) params.opacity = opts.opacity
  if (opts.side !== undefined) params.side = opts.side

  const mat = new T.MeshStandardMaterial(params as never)

  if (cls === 'glow') {
    // Die Textur leuchtet SELBST: dasselbe Bild als emissiveMap, der Ton als
    // Farbe. Ohne das ist Neon nur hell gemalt und bleibt in einer
    // Nachtszene genauso dunkel wie der Boden daneben.
    const c = toColor(T, spec?.tint ?? 0xffffff)
    mat.emissive = c
    mat.emissiveIntensity = spec?.glow ?? 1
    if (opts.map) mat.emissiveMap = opts.map
  }

  if (rippled) {
    if (!waveNormal) waveNormal = makeWaveNormal(T)
    mat.normalMap = waveNormal as Texture
    mat.normalScale = new T.Vector2(1, 1)
    if (!fullMask) fullMask = makeFullMask(T)
    applyWaterShader(mat, spec as SurfaceMaterialSpec,
                     (opts.mask || fullMask) as Texture)
  }
  return mat
}

/** Die geteilten Hilfstexturen freigeben (App-Teardown). */
export function disposeSurfaceMaterials(): void {
  waveNormal?.dispose()
  waveNormal = null
  fullMask?.dispose()
  fullMask = null
}
