import * as THREE from 'three';
import { CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';
import { tileDatumStep } from '@anima/scene-render';
import type { WorldLocation } from '../types';
import { polygonArea } from '../game/polygon';
import { locationLabelLift } from './nameTags';
import { detectStyle, footprintBoundary, footprintCentre, footprintWidth,
  footprintYaw, isAreaLocation, worldGroundSampler, type Tile } from './tiles';

/** Persistent location data, independent of its mounted scene. */
export interface PlaceRecord {
  loc: WorldLocation;
  center: THREE.Vector3;
  boundary: [number, number][] | null;
  area: number;
  width: number;
  yaw: number;
  isBuilding: boolean;
  isArea: boolean;
  natureSite?: boolean;
  height: number;
  anchor: THREE.Group;
  labelObj?: CSS2DObject;
}
export type ResidentRing = 'near' | 'far';
export interface Resident {
  tile: Tile;
  ring: ResidentRing;
  gen: number;
  ready: boolean;
}

/** Compute the footprint and label without mounting a scene. */
export function buildPlace(loc: WorldLocation): PlaceRecord {
  const style = detectStyle(loc);
  const isArea = isAreaLocation(loc);
  const isBuilding = !isArea;
  const boundary = footprintBoundary(loc);
  const width = footprintWidth(loc);
  const yaw = footprintYaw(loc);
  const placed = footprintCentre(loc);
  if (!placed) console.warn(`[places] ${loc.name || loc.id}: built without a position`
    + ' (pos_x/pos_z) — the place stands on the world origin (§ A1.1)');
  const center = placed ?? new THREE.Vector3(0, 0, 0);
  const anchor = new THREE.Group();
  anchor.position.copy(center);
  anchor.rotation.y = yaw;
  anchor.userData.locationId = loc.id;
  const natureSite = isBuilding && (style === 'water' || style === 'forest'
    || style === 'grass' || style === 'road');
  const height = !isBuilding ? (style === 'forest' ? 3 : 0.3)
    : natureSite ? (style === 'forest' ? 3 : 0.6) : 4;
  let labelObj: CSS2DObject | undefined;
  if (isBuilding) {
    const el = document.createElement('div');
    el.className = 'loc-label';
    el.textContent = loc.name;
    labelObj = new CSS2DObject(el);
    labelObj.position.set(0, locationLabelLift(height), 0);
    anchor.add(labelObj);
  }
  return { loc, center, boundary, area: polygonArea(boundary), width, yaw,
    isBuilding, isArea, natureSite, height, anchor, labelObj };
}

/** Apply the terrain datum law even when no scene is resident. */
export function redatumPlace(place: PlaceRecord): number {
  const step = tileDatumStep(place.center.y, place.center.x, place.center.z,
    worldGroundSampler());
  if (!step.delta) return 0;
  place.center.y = step.datum;
  place.anchor.position.y = step.datum;
  return step.delta;
}
