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
 * The CLIP's own hips height is the second, independent term, and it is NOT
 * in `root_offset` — see `clipHipsDrop` below. A renderer that plays clips in
 * place (both admin previews) has to put it back by hand; the 3D client gets
 * it by keeping and rescaling the hips track. Missing it is what drew a
 * seated figure 0.43 m over its chair in the prop viewer until 2026-08-29.
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
 *     reading is one constant for every clip alike: measured on the project's
 *     reference figure, 0.9288 m at H = 1.70 m, whatever is playing. Against the payload's own
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
import type { AnimationClip, Object3D } from 'three'

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
 * The standing hips height a clip is played at, in the CLIP's own units
 * (Mixamo centimetres) — the median of |y| over the `…hips….position` track,
 * or `null` when the clip has no such track at all.
 *
 * The same measurement `client3d/src/scene/figures.adaptExternalClips` takes
 * (`hipMedian` there), deliberately to the letter: the median, not the mean
 * and not the maximum — a single mis-scaled export once became the reference
 * and pushed EVERY figure into the ground (finding 2026-07-26). Admin and
 * client must read the same number off the same file, so this rule exists
 * once and both call it.
 *
 * `null` is not zero: a clip without the track carries no height information,
 * and a zero would read as "hips on the floor".
 */
export function hipsTrackMedian(clip: AnimationClip | null | undefined): number | null {
  const ys: number[] = []
  for (const track of clip?.tracks || []) {
    if (!track.name.endsWith('.position')) continue
    if (!/hips\./i.test(track.name.replace(/^mixamorig:?/i, ''))) continue
    const values = track.values as ArrayLike<number>
    for (let i = 1; i < values.length; i += 3) ys.push(Math.abs(values[i]))
  }
  if (!ys.length) return null
  ys.sort((a, b) => a - b)
  return ys[Math.floor(ys.length / 2)]
}

/**
 * How far a figure playing this clip has to SINK so its hips end up where the
 * clip puts them — in the unit `hipsBindY` is given in (mesh units, metres).
 *
 *     drop = hipsBindY × (1 − hipsMedian / standRef)
 *
 * WHY THIS IS NEEDED AT ALL. Every renderer here drops the Mixamo hips
 * POSITION track before playing a clip: it is in centimetres and would fling
 * the body a hundred metres sideways ("play in place"). But that track is not
 * only locomotion — it also carries the clip's OWN hips HEIGHT, and that is
 * real information: a sit clip holds the hips at 62 cm where an idle clip
 * holds them at 110. Drop the track and every pose is drawn at the same bind
 * height, so a seated figure floats 0.43 m over its chair.
 *
 * `figureRootY` does NOT cover this. It places the figure's bind-pose ROOT
 * relative to the marked surface (the place type's share, from the catalog);
 * this is the second, independent term, and it belongs to the CLIP. The 3D
 * client gets it by KEEPING the hips track and rescaling it against the same
 * standing reference (`figures.adaptExternalClips`); a renderer that plays in
 * place instead subtracts this drop once, which comes to the same height.
 *
 * `standRef` is what a STANDING actor's hips measure in that same clip
 * library — `hipsTrackMedian` of the idle clip. A clip at exactly that height
 * yields 0 (nothing to put back), a sleep clip animated ON a bed yields a
 * NEGATIVE drop and must: it is played above its own standing hips.
 *
 * Any missing or unusable input (no bind height, no track, no reference,
 * a zero reference) = 0, never a NaN into a position.
 */
export function clipHipsDrop(hipsBindY?: number | null,
                             hipsMedian?: number | null,
                             standRef?: number | null): number {
  const ok = (v?: number | null): v is number =>
    typeof v === 'number' && Number.isFinite(v)
  if (!ok(hipsBindY) || !ok(hipsMedian) || !ok(standRef) || standRef <= 0) return 0
  return hipsBindY * (1 - hipsMedian / standRef)
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
