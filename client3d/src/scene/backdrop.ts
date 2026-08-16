/**
 * The far backdrop (§ A17): a ring of mountain silhouettes at the world's
 * horizon — pure scenery, no collision, no navigation, nothing one could walk
 * to. Whoever wants to close the far side of the world paints impassable
 * terrain; this closes the VIEW.
 *
 * WHY A CAMERA-ANCHORED RING. The world plate ends at `world_bounds` grown by
 * `BASE_MARGIN_M` (60 m) and behind it there is nothing at all — the map
 * simply stops in mid-air. A backdrop built at the plate's real edge would
 * have to be as big as the world (a 16 km world would need a 16 km ring), and
 * in a small world one could walk up to it and see it for the flat cut-out it
 * is. So the ring hangs off the CAMERA TARGET at a fixed 380 m
 * (`BACKDROP_DIST_M`) and travels with it, which makes the picture independent
 * of how big the world is. Its ROTATION is never touched: the vertices are
 * built in world directions and the group only ever TRANSLATES, so north stays
 * north while one walks — the range does not turn with the player.
 *
 * WHY 380 m AND NO ENGINE CHANGE. `engine.ts` fogs the scene from 220 to
 * 520 m and the camera sees to 800 m. A ring at 380 m is therefore already
 * hazed by the scene's own fog, which is exactly the look a distant range
 * has, and nothing about the fog or the far plane has to move for it. The
 * consequence is deliberate: with the camera far out (up to 150 m from its
 * target) the ring's far side reaches ~530 m and dissolves into the sky
 * completely, while its near side at ~230 m is barely hazed. That gradient IS
 * the depth cue.
 *
 * WHERE the ridge stands and how high is `scene/backdropProfile.ts` — pure,
 * import-free and checked by `client3d/scripts/smoke_backdrop_math.mjs`. This
 * file owns nothing but the triangles, the two materials and the tint.
 */
import * as THREE from 'three';
import {
  BACKDROP_LAYERS, layerRadiusM, ridgeDirection, ridgeProfile, type RidgePoint,
} from './backdropProfile';
import type { BackdropSpec } from '../types';

/** Base rock colour per ring, before the sky is mixed in. The back ring is
 *  lighter to begin with: aerial perspective washes distance out, and a back
 *  ridge in the front ridge's colour reads as one flat cut-out. */
const LAYER_BASE_COLOR = [0x5f6d84, 0x76859c];

/** How much of the CURRENT sky colour is mixed into the rock by day. A third
 *  is the daylight haze — enough to sit the range behind the world's air
 *  instead of in front of it. */
const SKY_MIX_DAY = 0.30;
/** …and how much more of it at deep night. Together (0.85) the range is very
 *  nearly the night sky itself: a silhouette one can just make out. Without
 *  this the unlit material would keep its daylight rock colour and the ring
 *  would GLOW over a dark world. */
const SKY_MIX_NIGHT = 0.55;
/** Extra sky share of the back ring — the same aerial perspective again, now
 *  as the difference between the two rings. */
const SKY_MIX_PER_LAYER = 0.18;

export interface Backdrop {
  /** Add once to the scene; follow `engine.target` with it per frame. */
  group: THREE.Group;
  /** Take over a worldmap payload's `backdrop` block. `null`/`undefined` (the
   *  setting is off, or the server is older) removes the ring. Rebuilds only
   *  when the payload actually changed. */
  sync(spec: BackdropSpec | null | undefined): void;
  /** The engine's `nightFactor` and the sky colour it just set. */
  setDayNight(night: number, sky: THREE.Color): void;
  dispose(): void;
}

export function createBackdrop(): Backdrop {
  const group = new THREE.Group();
  group.name = 'backdrop';

  const meshes: THREE.Mesh[] = [];
  const materials: THREE.MeshBasicMaterial[] = [];
  /** What the ring standing was built from — `null` until the first build, so
   *  the sentinel is not a possible key (`''` is: the ring being off). */
  let builtKey: string | null = null;
  let night = 0;
  const sky = new THREE.Color(0x9fc7e8);

  function applyTint(): void {
    for (let layer = 0; layer < materials.length; layer += 1) {
      // A ring whose profile had nothing to draw leaves a hole in the array —
      // the tint must not depend on both rings existing.
      if (!materials[layer]) continue;
      const mix = Math.min(0.92,
        SKY_MIX_DAY + SKY_MIX_NIGHT * night + SKY_MIX_PER_LAYER * layer);
      materials[layer].color.set(LAYER_BASE_COLOR[layer] ?? LAYER_BASE_COLOR[0]).lerp(sky, mix);
    }
  }

  function clear(): void {
    for (const m of meshes) {
      group.remove(m);
      m.geometry.dispose();
    }
    for (const mat of materials) mat?.dispose();   // holes: see `applyTint`
    meshes.length = 0;
    materials.length = 0;
  }

  return {
    group,
    sync(spec) {
      const key = spec
        ? JSON.stringify([spec.height_m, spec.seed, spec.arcs])
        : '';
      if (key === builtKey) return;
      builtKey = key;
      clear();
      if (!spec) return;

      const profile = ridgeProfile(spec.seed, spec.arcs ?? [], spec.height_m);
      for (let layer = 0; layer < BACKDROP_LAYERS; layer += 1) {
        const geo = ridgeGeometry(profile, layer);
        if (!geo) continue;
        const mat = new THREE.MeshBasicMaterial({
          // `fog: true` is the point of the whole material: the distance haze
          // is the ENGINE's, so the ring darkens and fades with the very same
          // fog the rest of the world uses.
          fog: true,
          side: THREE.FrontSide,
        });
        const mesh = new THREE.Mesh(geo, mat);
        // Scenery, and nothing else: no shadow either way (an unlit material
        // could not show one, and a 380 m ring in the sun's 300 m shadow
        // camera would cost a pass for nothing) and never pickable.
        mesh.castShadow = false;
        mesh.receiveShadow = false;
        mesh.raycast = () => {};       // never pickable — it is not a place
        mesh.renderOrder = -1;         // behind everything else in the world
        materials[layer] = mat;
        meshes.push(mesh);
        group.add(mesh);
      }
      applyTint();
    },
    setDayNight(n, color) {
      night = Number.isFinite(n) ? Math.min(1, Math.max(0, n)) : 0;
      sky.copy(color);
      applyTint();
    },
    dispose() {
      clear();
      builtKey = null;
    },
  };
}

/**
 * One ring as a low-poly strip: per pair of neighbouring ridge points a quad
 * from the ground (y = 0) up to the two peaks.
 *
 * The winding is the load-bearing detail — the camera stands INSIDE the ring,
 * so the faces have to point inward and a `FrontSide` material is enough (no
 * `DoubleSide`, no doubled fill rate). With the compass of § A1.8 a point sits
 * at `(R·sin a, y, R·cos a)`; for two angles a < b the order
 * `A, A', B'` / `A, B', B` (A = foot at a, A' = its peak) gives a normal
 * pointing at the ring's centre. The reverse order would face outward and the
 * whole range would be invisible from the only place one ever looks at it.
 *
 * A pair whose two peaks are BOTH on the ground is skipped: those are the
 * joins between two separate arcs (every arc ends at peakH 0), and drawing
 * them would mean degenerate triangles between "N" and "S".
 */
function ridgeGeometry(profile: RidgePoint[], layer: number): THREE.BufferGeometry | null {
  const pts = profile.filter((p) => p.layer === layer);
  if (pts.length < 2) return null;
  const r = layerRadiusM(layer);
  const pos: number[] = [];
  const idx: number[] = [];
  for (let i = 0; i + 1 < pts.length; i += 1) {
    const p = pts[i];
    const q = pts[i + 1];
    if (p.peakH <= 0 && q.peakH <= 0) continue;
    const [pdx, pdz] = ridgeDirection(p.angleDeg);
    const [qdx, qdz] = ridgeDirection(q.angleDeg);
    const px = pdx * r, pz = pdz * r;
    const qx = qdx * r, qz = qdz * r;
    const b = pos.length / 3;
    pos.push(px, 0, pz, px, p.peakH, pz, qx, 0, qz, qx, q.peakH, qz);
    idx.push(b, b + 1, b + 3, b, b + 3, b + 2);
  }
  if (!idx.length) return null;
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  geo.setIndex(idx);
  return geo;
}
