/**
 * place() — THE placement routine of the contract (§ B2), once for both
 * renderers. It used to exist twice: `placeModelSpec` in the admin preview and
 * `placeSpec` in the 3D client, line for line the same arithmetic.
 *
 * Pure geometry: take the source, apply the orientation fix, measure, scale
 * UNIFORMLY to `max_m`, hang the object on its OWN centre, yaw as a PARENT
 * rotation about exactly that point (never combined into one Euler — an x/z
 * fix would tip along), then set it on `anchor` / `bottom_y` and, if the spec
 * asks for it, clip it against the room hull. No scene wiring, no verify —
 * that is the callers' business.
 *
 * `measure: 'fit'` (v5, door props) is the ONE spec that does not scale
 * uniformly and does not hang on its centre: it is fitted into an opening
 * (`size_m`) and hung on its HINGE edge, so the caller can swing the returned
 * group about its own origin. Everything else about the chain is unchanged.
 *
 * Returns: a wrapper around `source`. The caller hangs it into a group WITHOUT
 * a transform of its own (the grounding measures in the parent frame, and the
 * spec numbers are stated around the tile centre).
 *
 * THREE comes in as a parameter instead of an import: the admin page loads
 * three lazily, and a static import would pull the library into its main
 * bundle. The client simply passes its imported module through.
 */
import type { Group, Object3D } from 'three'
import { applyClipOutline } from './clip'
import type { SceneModelSpec } from './types'

export interface PlaceOptions {
  /** Clone the source before placing it. Default true — the admin preview
   *  places the same cached object several times over. The 3D client hands
   *  the object over for good and therefore passes false. */
  clone?: boolean
  /** Apply `spec.clip_outline` right away. Default true. The 3D client clips
   *  itself, after it has hung the model in, and passes false. */
  clip?: boolean
}

export function placeModelSpec(THREE: typeof import('three'),
                               source: Object3D,
                               spec: SceneModelSpec,
                               opts: PlaceOptions = {}): Group {
  const { clone = true, clip = true } = opts
  const deg = (v?: number) => ((v || 0) * Math.PI) / 180

  const fit = spec.measure === 'fit'

  const fix = new THREE.Group()
  fix.add(clone ? source.clone(true) : source)

  // How BIG an object is must not depend on how it is TURNED. The axis-aligned
  // hull of a turned box is larger than the box — the mermaid stand grew from
  // 1.000 to 1.306 through the fix 0/110/357 and the model came out 23 %
  // smaller for it (user finding 2026-07-28). OBJECT SIZES (`xz`/`xyz`) are
  // therefore measured with the fix rounded to 90°: the axis assignment
  // counts, the fine angle does not.
  const snap = (v?: number) => Math.round((v || 0) / 90) * 90
  // Order 'YXZ' (2026-07-28): yaw outermost, tilt (x) and roll (z) after it in
  // the ALREADY turned frame. With three's default 'XYZ' the x dial acted in
  // world axes — after a y turn it no longer tipped the model about its own
  // axis but across it (user finding). The marker tilt uses the same order, so
  // that "tip forward" means the same thing everywhere. With only ONE axis in
  // play both orders are identical.
  fix.rotation.order = 'YXZ'
  fix.rotation.set(deg(snap(spec.fix_euler?.x)), deg(snap(spec.fix_euler?.y)),
                   deg(snap(spec.fix_euler?.z)))
  fix.updateMatrixWorld(true)
  const sObj = new THREE.Box3().setFromObject(fix).getSize(new THREE.Vector3())

  // The FIT scale lives INSIDE the yaw (v5): it is not one factor, so it has
  // to act in the model's own axes — a non-uniform scale outside the rotation
  // would shear the leaf at every yaw that is not a multiple of 90°. Identity
  // for every other measure, which leaves their chain exactly as it was.
  const fitG = new THREE.Group()
  fitG.add(fix)

  const yawG = new THREE.Group()
  yawG.add(fitG)
  // PLUS, since E4 (§ A1.1, decided 2026-08-07): the world map's turning sense
  // is THE turning sense of this contract, for map and scene alike. three.js'
  // Ry(+θ) maps a local point to
  //     x = lx·cos θ + lz·sin θ,   z = −lx·sin θ + lz·cos θ
  // which IS the server's `world_geometry.local_to_world` — so `+rad` is what
  // makes both renderers reproduce the server's own maths instead of mirroring
  // it. The old minus was the map-yaw chain of § A1.8, and it flipped here, in
  // `sceneRecipe.ts` and in the admin's model viewer in ONE commit: two
  // renderers disagreeing about a sign is a mirrored world.
  // That chain (`map3d.rotation` → `map_rotation_2d`) is GONE with v6 Nr. 10 —
  // a BUILDING spec now always carries `yaw_deg` 0 and is turned by its
  // sidecar fix alone. Rooms, props and extras keep their own placement yaw,
  // which is what this line still serves.
  yawG.rotation.y = deg(spec.yaw_deg)
  yawG.updateMatrixWorld(true)
  // A building fills its frame AFTER the YAW — there the turned hull is
  // exactly the right measurement (a house set at an angle should still fit on
  // its plot), which is why `yawed_xz` stays on sYaw. The ORIENTATION FIX is
  // in there rounded to 90° as well (2026-07-28): otherwise a fine angle in
  // the fix would inflate the axis-aligned hull here too and the location
  // model would shrink as it was turned — the same finding as before on the
  // room models, one measurement further along.
  const sYaw = new THREE.Box3().setFromObject(yawG).getSize(new THREE.Vector3())

  // From here on the REAL fix applies — measured rounded, drawn exactly as
  // dialled.
  fix.rotation.set(deg(spec.fix_euler?.x), deg(spec.fix_euler?.y),
                   deg(spec.fix_euler?.z))
  yawG.updateMatrixWorld(true)

  // SEATING DATUM (§ B2 step 4, revised 2026-08-20): what is anchored is the
  // box the object has BEFORE the yaw — the yaw then turns it about exactly
  // that point. Before, the FINISHED, turned hull was centred on the anchor,
  // which made an object's position depend on its angle (measured: the
  // sectional sofa slid 0.50 m at yaw 45°, the cable-crossover station
  // 0.33 m, the bed 0.12 m — and back to zero at 90°). That is also precisely
  // the datum the SERVER cannot reproduce: it knows the prop's `bbox`, never
  // the turned hull of the mesh. Its composed prop markers (§ A4) therefore
  // landed beside their prop by that very amount. A yaw of 0/90/180/270 does
  // not move at all under this change — there both boxes are the same one.
  yawG.rotation.y = 0
  yawG.updateMatrixWorld(true)
  const bFix = new THREE.Box3().setFromObject(fix)
  const cFix = bFix.getCenter(new THREE.Vector3())
  // A FITTED model hangs on the edge it turns about, not on its centre: its
  // local −x edge and its underside go into the origin (z stays centred, the
  // leaf's thickness straddles the wall plane). Together with the server's
  // yaw — local +x onto the direction the leaf RUNS, away from its hinge —
  // that puts the mesh exactly in the hole while the group's origin stays the
  // hinge a renderer swings it about.
  fix.position.set(fit ? -bFix.min.x : -cFix.x,
                   fit ? -bFix.min.y : -cFix.y,
                   -cFix.z)
  if (fit) {
    // x to the width, y to the height, z with the SAME factor as x — the one
    // sanctioned exception to the uniform scale law below: an opening is a
    // hole with two given sides, and a door that fills only one of them
    // leaves a lit gap. The depth keeps its proportion to the width.
    const sx = (spec.size_m?.[0] || 1) / (sObj.x || 1)
    fitG.scale.set(sx, (spec.size_m?.[1] || 1) / (sObj.y || 1), sx)
  }
  yawG.rotation.y = deg(spec.yaw_deg)
  yawG.updateMatrixWorld(true)

  // ONE scale law, ONE factor on all three axes (2026-07-28): the spec says
  // WHAT is measured, and the rest is a division. Nothing is squeezed in one
  // dimension any more — the old modes (tile_fit with its own y target,
  // fit_box, scale_axes) are gone without replacement, and with them the
  // possibility of two renderers differing in height.
  const outer = new THREE.Group()
  outer.add(yawG)
  if (!fit) {
    const extent = (spec.measure === 'yawed_xz' ? Math.max(sYaw.x, sYaw.z)
      : spec.measure === 'xz' ? Math.max(sObj.x, sObj.z)
        : Math.max(sObj.x, sObj.y, sObj.z)) || 1
    outer.scale.setScalar((spec.max_m || 1) / extent)
  }
  outer.updateMatrixWorld(true)
  // The object stands with its own centre in the origin of `outer` (see the
  // seating datum above), so that group's position IS the anchor. Only the
  // bottom edge still has to be measured — and that one is yaw-independent.
  const bOut = new THREE.Box3().setFromObject(outer)
  outer.position.set(spec.anchor[0],
                     spec.bottom_y - bOut.min.y,
                     spec.anchor[1])
  // Hull clip LAST: the shader compares world positions, so the model has to
  // sit where it belongs first (§ B1).
  if (clip && spec.clip_outline?.length) {
    applyClipOutline(THREE, outer, spec.clip_outline)
  }
  return outer
}
