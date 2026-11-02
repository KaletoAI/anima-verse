/** Framing arithmetic only: no world state, rendering or network access. */
import * as THREE from 'three';
import type { PhotoView } from '@anima/player-ui';

export interface PhotoSubject {
  name: string;
  head: [number, number, number];
}

export function photoView(camera: THREE.PerspectiveCamera, subjects: PhotoSubject[], floorY: number): PhotoView {
  camera.updateWorldMatrix(true, false);
  const forward = camera.getWorldDirection(new THREE.Vector3());
  const point = new THREE.Vector3();
  const visible: PhotoView['visible'] = [];
  for (const subject of subjects) {
    point.fromArray(subject.head);
    const depth = point.distanceTo(camera.position);
    if (point.clone().sub(camera.position).dot(forward) <= 0) continue;
    point.project(camera);
    // A tiny tolerance keeps mathematically exact frustum edges inside.
    if (Math.max(Math.abs(point.x), Math.abs(point.y), Math.abs(point.z)) > 1 + 1e-9) continue;
    visible.push({ name: subject.name,
      screen_x: THREE.MathUtils.clamp((point.x + 1) / 2, 0, 1),
      screen_y: THREE.MathUtils.clamp((1 - point.y) / 2, 0, 1), depth_m: depth });
  }
  return { visible, camera: {
    pitch_deg: THREE.MathUtils.radToDeg(Math.asin(THREE.MathUtils.clamp(forward.y, -1, 1))),
    height_m: Math.max(0, camera.position.y - floorY), fov_deg: camera.getEffectiveFOV(),
  } };
}
