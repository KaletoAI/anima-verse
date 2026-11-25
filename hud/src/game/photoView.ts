/** Framing arithmetic only: no world state, rendering or network access. */
import * as THREE from 'three';
import type { PhotoView } from '@anima/player-ui';

export interface PhotoSubject {
  name: string;
  head: [number, number, number];
}

/** Integer pixels of the original frozen render buffer, before any downscale. */
export interface PhotoRect { x: number; y: number; width: number; height: number; }

export function cropPhotoView(view: PhotoView, rect: PhotoRect, width: number, height: number): PhotoView {
  if (rect.x === 0 && rect.y === 0 && rect.width === width && rect.height === height) return view;
  const left = rect.x / width, top = rect.y / height;
  const w = rect.width / width, h = rect.height / height;
  const tan = Math.tan(view.camera.fov_deg * Math.PI / 360);
  const rx = (2 * (left + w / 2) - 1) * width / height * tan;
  const ry = (1 - 2 * (top + h / 2)) * tan;
  const pitch = view.camera.pitch_deg * Math.PI / 180;
  return {
    visible: view.visible.filter(v => v.screen_x >= left - 1e-9 && v.screen_x <= left + w + 1e-9
      && v.screen_y >= top - 1e-9 && v.screen_y <= top + h + 1e-9).map(v => ({ ...v,
      screen_x: THREE.MathUtils.clamp((v.screen_x - left) / w, 0, 1),
      screen_y: THREE.MathUtils.clamp((v.screen_y - top) / h, 0, 1),
    })),
    camera: { ...view.camera, fov_deg: 2 * Math.atan(tan * h) * 180 / Math.PI,
      pitch_deg: Math.asin(THREE.MathUtils.clamp((Math.sin(pitch) + ry * Math.cos(pitch))
        / Math.hypot(1, rx, ry), -1, 1)) * 180 / Math.PI },
  };
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
