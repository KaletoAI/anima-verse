/**
 * figure.ts — WHERE A FIGURE MEETS A MARKED SURFACE. One rule, three
 * renderers (§ A4 / § A16.9).
 *
 * A marker names the SURFACE: the seat of a bench, the mattress of a bed.
 * WHERE the body touches that surface is a property of the PLACE TYPE, and
 * it is nowhere near the feet — a seated body touches at the buttocks. The
 * scene payload therefore ships `root_offset` beside every marker (world
 * metres: the pose catalog's `groups[group].root_drop × 1.70 m`, computed
 * by the server — the catalog is the ONE source, there is no table here or
 * in the recipe), and the consumer subtracts it:
 *
 *     figure root y = surface y − root drop
 *
 * "Root" is the figure ANCHORED IN ITS BIND POSE — soles on 0, XZ centred —
 * exactly what `client3d/src/scene/figures.Figure` does once in its
 * constructor and never again. That is the whole contract, and it only holds
 * if nobody re-grounds the figure per clip: a `sleep` clip is animated ON A
 * BED and carries the body 0.6 × H over its own root, so dropping the posed
 * body onto the mattress would bury the sleeper by a metre.
 *
 * WHY THIS LIVES HERE (finding 2026-08-21). The rule existed three times:
 *
 *   * `client3d` — bind anchor, `y_world − root_offset`. Correct.
 *   * the admin floor-plan preview — the same, but derived by accident: it
 *     grounded on `Box3.setFromObject` of the POSED figure, and that box
 *     ignores skinning, so it silently returned the bind box.
 *   * the admin prop viewer — its own law: anchor the HIPS BONE minus
 *     0.03 × H, read off the "posed skeleton". But every clip is played in
 *     place (the Mixamo hips POSITION track is dropped — it is in
 *     centimetres), so the hips joint never moves vertically and that
 *     reading is one constant for every clip alike: measured on x-bot.fbx,
 *     0.9288 m at H = 1.70 m, whatever is playing. Against the payload's own
 *     numbers that put the seated figure 0.395 m too low, the sleeper
 *     0.144 m too high and a lying figure 0.842 m too low — the sit case is
 *     what the user saw as "the figure is not where I put the marker".
 *
 * So: the drop comes from the DATA — the payload's `root_offset`, or for a
 * viewer with no payload (the prop tab renders one prop, not a scene) the
 * catalog group's `root_drop` × its figure height, fetched by the caller —
 * and the anchor is the bind pose. No renderer measures a pose to decide a
 * height, and none carries a kind → drop table of its own (the shadow copy
 * that lived here was deleted 2026-08-28: it had already drifted from the
 * catalog's groups).
 */
import type { Object3D } from 'three'

/** The figure of this contract: 1.70 m, everywhere and always (§ A3). */
export const FIGURE_HEIGHT_M = 1.7

/**
 * The y a figure's bind-pose root sits at, for a marker naming `surfaceY`.
 *
 * `rootOffset` is the ONLY input: the scene payload's own `root_offset`
 * (already the group's share × the figure height, in the caller's unit), or
 * what a payload-less viewer computed from the catalog group. Absent or
 * not a number = 0, the root on the surface — a standing spot, or a marker
 * whose group the caller does not know yet.
 */
export function figureRootY(surfaceY: number, rootOffset?: number | null): number {
  const drop = typeof rootOffset === 'number' && Number.isFinite(rootOffset) ? rootOffset : 0
  return surfaceY - drop
}

/**
 * Scale a figure to `figureHeight` and anchor it in its BIND POSE: soles on
 * y = 0, XZ centred on the origin. Returns the scale factor applied.
 *
 * CALL THIS BEFORE THE CLIP IS PLAYED. The measurement is deliberately
 * `Box3.setFromObject`, which reads the geometry's bind bounding box and not
 * the skinned pose — but relying on that side effect is how the floor-plan
 * preview came to have the right answer for the wrong reason, so the order is
 * part of the contract instead.
 *
 * `pivot` is the group the figure hangs in, including any up-axis fix; its
 * scale and position are OWNED by this routine.
 */
export function anchorFigureBind(THREE: typeof import('three'),
                                 pivot: Object3D,
                                 figureHeight: number): number {
  pivot.scale.setScalar(1)
  pivot.position.set(0, 0, 0)
  pivot.updateMatrixWorld(true)
  const box = new THREE.Box3().setFromObject(pivot)
  const size = box.getSize(new THREE.Vector3())
  const centre = box.getCenter(new THREE.Vector3())
  const k = figureHeight / (size.y || 1)
  pivot.scale.setScalar(k)
  pivot.position.set(-centre.x * k, -box.min.y * k, -centre.z * k)
  pivot.updateMatrixWorld(true)
  return k
}
