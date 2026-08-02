/**
 * Raum-Clipping des Vertrags (§ B1 `clip_outline`) — EINE Implementierung.
 *
 * Vorgeschichte: diese Routine wurde zweimal unabhängig gebaut (Admin-Vorschau
 * und 3D-Client) und lief danach in zwei Varianten auseinander. Übernommen ist
 * die Admin-Variante, weil sie in drei Punkten besser ist:
 *
 *   1. `CLIP_N` ist eine Compile-Zeit-Konstante → das Uniform-Array ist genau
 *      so groß wie das Polygon, und der Loop hat eine konstante Schranke.
 *      Die Client-Variante lud immer 33 Punkte und brach dynamisch per
 *      `if (i >= uClipCount) break;` ab.
 *   2. Es gibt `disposeClipMaterials` — die Client-Variante klonte Materialien
 *      ohne sie je wieder freizugeben.
 *   3. Der Test läuft VOR `<clipping_planes_fragment>`: ein verworfenes
 *      Fragment durchläuft die restliche Kette gar nicht erst.
 *
 * Warum Fragment-Discard und nicht `clippingPlanes`: der Grundriss ist ein
 * beliebiges Polygon, keine Handvoll Halbräume — Ebenen bräuchten je Kante
 * eine und würden bei konkaven Umrissen falsch schneiden. Der Paritätstest
 * (Punkt-im-Polygon) ist exakt und kostet einen kurzen Loop.
 *
 * Die Schnittkanten bleiben OFFEN (es gibt keine Deckelgeometrie) — deshalb
 * DoubleSide, sonst schaut man von außen durch die Rückseite ins Nichts.
 * Bekannt und laut Auftrag akzeptiert.
 */
import type { Material, Mesh, Object3D,
  WebGLProgramParametersWithUniforms } from 'three'

/** Gleiche Obergrenze wie `CLIP_OUTLINE_MAX_POINTS` im Composer — der Test
 *  läuft je Fragment, deshalb schickt der Server nie mehr und wir compilieren
 *  nie mehr. 32 → 64 mit Vertrag v5.2 Nr. 11 (tessellierte Kurven-Hüllen):
 *  MUSS dem Composer-Cap folgen, sonst schneidet der Client still ab. */
export const CLIP_MAX_POINTS = 64

/** Punkt-im-Polygon per Strahl-Paritätstest, vor den Clipping-Chunk des
 *  Fragment-`main` injiziert. `clipPrev` läuft die Kante (i-1 → i) mit,
 *  statt `uClip` zweimal zu indizieren: in GLSL ES 1.0 dürfen nur der
 *  Loop-Index und konstante Ausdrücke ein Uniform-Array indizieren. Das &&
 *  kurzschließt, deshalb sieht die Division den straddle-freien (und damit
 *  Null-) Fall nie. */
const CLIP_TEST = /* glsl */`
  vec2 clipP = vec2( vClipWorld.x, vClipWorld.z );
  bool clipInside = false;
  vec2 clipPrev = uClip[ CLIP_N - 1 ];
  for ( int i = 0; i < CLIP_N; i ++ ) {
    vec2 clipCur = uClip[ i ];
    if ( ( ( clipCur.y > clipP.y ) != ( clipPrev.y > clipP.y ) ) &&
         ( clipP.x < ( clipPrev.x - clipCur.x ) * ( clipP.y - clipCur.y ) /
                     ( clipPrev.y - clipCur.y ) + clipCur.x ) ) {
      clipInside = ! clipInside;
    }
    clipPrev = clipCur;
  }
  if ( ! clipInside ) discard;
`

/**
 * Ein platziertes Modell auf ein WELT-Polygon beschneiden: jedes Fragment
 * außerhalb der Raumhülle wird verworfen, ein überstehendes Diorama endet am
 * Grundriss.
 *
 * Keine Transformation der Punkte: das Polygon ist Welt, die Fragment-Position
 * ist Welt — der Shader vergleicht direkt. Deshalb muss das Modell VORHER an
 * seinem Platz sitzen.
 *
 * Materialien werden GEKLONT, bevor gepatcht wird: das Quellobjekt teilt sie
 * mit dem Modell-Cache, und ein gepatchtes Cache-Material würde weiterclippen,
 * nachdem das Flag abgeschaltet wurde. `disposeClipMaterials` gibt die Klone
 * wieder frei.
 */
export function applyClipOutline(THREE: typeof import('three'),
                                 obj: Object3D,
                                 outline: Array<[number, number]>): void {
  const pts = (outline || []).slice(0, CLIP_MAX_POINTS)
  if (pts.length < 3) return
  const n = pts.length
  const uClip = { value: pts.map((p) => new THREE.Vector2(p[0], p[1])) }
  const patch = (shader: WebGLProgramParametersWithUniforms) => {
    shader.uniforms.uClip = uClip
    shader.vertexShader = `varying vec3 vClipWorld;\n${shader.vertexShader}`
      .replace('#include <project_vertex>',
        '#include <project_vertex>\n\tvClipWorld = ( modelMatrix * vec4( transformed, 1.0 ) ).xyz;')
    const head = `#define CLIP_N ${n}\nuniform vec2 uClip[ CLIP_N ];\n`
      + 'varying vec3 vClipWorld;\n'
    const body = head + shader.fragmentShader
    shader.fragmentShader = body.includes('#include <clipping_planes_fragment>')
      ? body.replace('#include <clipping_planes_fragment>',
                     `${CLIP_TEST}\n#include <clipping_planes_fragment>`)
      : body.replace('void main() {', `void main() {\n${CLIP_TEST}`)
  }
  obj.traverse((o: Object3D) => {
    const mesh = o as Mesh
    if (!mesh.isMesh) return
    const clipOne = (src: Material): Material => {
      const mat = src.clone()
      mat.side = THREE.DoubleSide
      mat.userData = { ...mat.userData, __clipClone: true }
      mat.onBeforeCompile = patch
      // Three cacht compilierte Programme über Materialien hinweg — ohne einen
      // Schlüssel, der die Polygonlänge trägt, teilten sich die Varianten ein
      // Programm.
      mat.customProgramCacheKey = () => `clip:${n}`
      mat.needsUpdate = true
      return mat
    }
    mesh.material = Array.isArray(mesh.material)
      ? mesh.material.map(clipOne)
      : clipOne(mesh.material)
  })
}

/** Die Material-Klone von `applyClipOutline` freigeben (ihre Texturen sind mit
 *  dem Cache geteilt und bleiben bewusst unangetastet). */
export function disposeClipMaterials(obj: Object3D): void {
  obj.traverse((o: Object3D) => {
    const mesh = o as Mesh
    if (!mesh.isMesh) return
    const mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material]
    for (const m of mats) if (m?.userData?.__clipClone) m.dispose?.()
  })
}
