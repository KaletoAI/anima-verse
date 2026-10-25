import * as THREE from 'three';
import type { SceneModelSpec } from '@anima/scene-render';

type Light = NonNullable<SceneModelSpec['light']>;
type Point = { x: number; y: number; z: number };

/** Selection needs only placement and visibility data, so it can run without a scene. */
export interface LightSourceView {
  id: string;
  pos: Point;
  range_m: number;
  when: Light['when'];
  room_id?: string;
}

/** Three compiles the light count into every lit shader; keep six slots alive to avoid recompiles. */
export const LIGHT_POOL_SIZE = 6;

// Reuse the fire dip colour rather than allocating one for every active slot each frame.
const FIRE_COLOR = new THREE.Color('#ff6a20');

/** Keep surviving winners in their slots so nearby movement does not restart their fades. */
export function pickLights(sources: LightSourceView[], focus: Point, n: number, night: number,
                           visibleRooms: Set<string>, previous: string[] = []): string[] {
  const distance = (s: LightSourceView) => Math.hypot(
    s.pos.x - focus.x, s.pos.y - focus.y, s.pos.z - focus.z,
  );
  const winners = sources.filter(s => (s.when !== 'night' || night > .3)
    && (!s.room_id || visibleRooms.has(s.room_id)) && distance(s) <= s.range_m + 30)
    .sort((a, b) => distance(a) - distance(b))
    .slice(0, n)
    .map(s => s.id);
  const slots = Array.from({ length: n }, (_, i) => winners.includes(previous[i]) ? previous[i] : '');
  const free = winners.filter(id => !slots.includes(id));
  const assigned = slots.map(id => id || free.shift() || '');
  while (assigned.length && !assigned[assigned.length - 1]) assigned.pop();
  return assigned;
}

/** Two phased waves give candle/fire variation without frame-dependent random jumps. */
export function flickerFactor(kind: Light['flicker'], t: number, phase: number): number {
  const hz = kind === 'candle' ? 8 : 4;
  const a = kind === 'candle' ? .08 : kind === 'fire' ? .25 : 0;
  const t0 = t * hz * Math.PI * 2 + phase;
  return 1 + a * (Math.sin(t0) + Math.sin(t0 * Math.SQRT2)) / 2;
}

/**
 * Transform the base anchor rather than the mesh origin, which may be centred.
 * Add height_m afterward because it is base-relative in world metres; offsets
 * are already yawed by the server and must not rotate with the parent again.
 */
export function placementLightPosition(parent: THREE.Object3D, anchor: number[], bottom: number, light: Light): THREE.Vector3 {
  parent.updateWorldMatrix(true, false);
  const [x, y, z] = lightPositionInFrame(parent.matrixWorld.elements, anchor, bottom, light);
  return new THREE.Vector3(x, y, z);
}

/**
 * `placementLightPosition` as plain arithmetic: `frame` is the parent's world
 * matrix, column-major (three's `elements`). The base anchor (anchor x,
 * bottom, anchor z) goes through the frame, then the world offset is added.
 */
export function lightPositionInFrame(frame: ArrayLike<number>, anchor: readonly number[], bottom: number,
                                     light: Pick<Light, 'offset_m' | 'height_m'>): [number, number, number] {
  const ax = anchor[0], ay = bottom, az = anchor[1];
  const w = frame[3] * ax + frame[7] * ay + frame[11] * az + frame[15];
  return [
    (frame[0] * ax + frame[4] * ay + frame[8] * az + frame[12]) / w + light.offset_m[0],
    (frame[1] * ax + frame[5] * ay + frame[9] * az + frame[13]) / w + light.height_m,
    (frame[2] * ax + frame[6] * ay + frame[10] * az + frame[14]) / w + light.offset_m[1],
  ];
}

/** three's `MathUtils.smoothstep`: 0 at or below `lo`, 1 at or above `hi`, the cubic in between. */
function smoothstep(x: number, lo: number, hi: number): number {
  if (x <= lo) return 0;
  if (x >= hi) return 1;
  const t = (x - lo) / (hi - lo);
  return t * t * (3 - 2 * t);
}

/** A night lamp fades in between night .3 and .6; every other lamp is at full gain. */
export function nightLightGain(when: Light['when'], night: number): number {
  return when === 'night' ? smoothstep(night, .3, .6) : 1;
}

/** A halo shows while its room is shown and, for a night lamp, once the night passes .3. */
export function haloVisible(roomShown: boolean, when: Light['when'], night: number): boolean {
  return roomShown && (when !== 'night' || night > .3);
}

/** How far a fire's colour leans towards the dip colour #ff6a20: 0.1 at the deepest dip, 0 on the upswing. */
export function fireColourMix(t: number, phase: number): number {
  return Math.max(0, (1 - flickerFactor('fire', t, phase)) / .25) * .1;
}

/** One pool slot as the fade sees it: which source it shows and at what gain. */
export interface LightSlotState { id: string; gain: number }

/**
 * One frame of a slot's fade (0.4 s each way): a slot whose source is not the
 * wanted one fades OUT first and takes the wanted source only at gain 0, so a
 * lamp never jumps to another position while lit; a slot showing the wanted
 * source fades in to 1.
 */
export function stepLightSlot(slot: LightSlotState, wanted: string, dt: number): LightSlotState {
  if (slot.id !== wanted) {
    const gain = Math.max(0, slot.gain - dt / .4);
    return { id: gain === 0 ? wanted : slot.id, gain };
  }
  return { id: slot.id, gain: Math.min(1, slot.gain + dt / .4) };
}

let haloTexture: THREE.CanvasTexture | undefined;

/** Share the radial map; individual mounts own only their halo materials. */
function texture(): THREE.CanvasTexture {
  if (!haloTexture) {
    const canvas = document.createElement('canvas');
    canvas.width = canvas.height = 64;
    const ctx = canvas.getContext('2d')!;
    const g = ctx.createRadialGradient(32, 32, 0, 32, 32, 32);
    g.addColorStop(0, 'rgba(255,255,255,1)');
    g.addColorStop(1, 'rgba(255,255,255,0)');
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, 64, 64);
    haloTexture = new THREE.CanvasTexture(canvas);
  }
  return haloTexture;
}

/** Mounts retain a handle so relifts and teardown update both lighting and glow. */
export interface LightHandle {
  move(pos: Point): void;
  remove(): void;
}

interface Source extends LightSourceView {
  light: Light;
  phase: number;
  halo?: THREE.Sprite;
}

/**
 * Bound shader light cost with permanent slots while retaining every source.
 * Halos are sprites, so they are not limited by the pool: distant lamps can
 * still glow even when their illumination is outside the nearest six.
 */
export class LightPool {
  private sources = new Map<string, Source>();
  private slots = Array.from({ length: LIGHT_POOL_SIZE }, () => ({
    lamp: new THREE.PointLight(0xffffff, 0, 0, 2),
    id: '',
    gain: 0,
  }));
  private selected: string[] = [];
  private elapsed = .2;
  private time = 0;
  private serial = 0;

  constructor(private scene: THREE.Scene) {
    for (const s of this.slots) {
      s.lamp.castShadow = false;
      scene.add(s.lamp);
    }
  }

  /** Register independently of mesh availability so a failed model still emits light. */
  register(light: Light, pos: Point, room_id?: string, ownHalo?: (sprite: THREE.Sprite) => () => void): LightHandle {
    const id = String(++this.serial);
    const source: Source = {
      id, pos: { ...pos }, range_m: light.range_m, when: light.when,
      room_id, light, phase: Math.random() * Math.PI * 2,
    };
    if (light.glow_m > 0) {
      const material = new THREE.SpriteMaterial({
        map: texture(), color: light.color, blending: THREE.AdditiveBlending,
        depthWrite: false, fog: true,
      });
      source.halo = new THREE.Sprite(material);
      source.halo.scale.setScalar(2 * light.glow_m);
      source.halo.position.copy(pos);
      this.scene.add(source.halo);
    }
    const releaseHalo = source.halo ? ownHalo?.(source.halo) : undefined;
    this.sources.set(id, source);
    this.elapsed = .2;
    return {
      move(p) {
        source.pos = { ...p };
        source.halo?.position.copy(p);
      },
      remove: () => {
        if (!this.sources.delete(id)) return;
        source.halo?.removeFromParent();
        if (releaseHalo) releaseHalo();
        else source.halo?.material.dispose();
        this.elapsed = .2;
      },
    };
  }

  /** Select at 5 Hz, but fade and flicker each frame so slot changes stay smooth. */
  update(dt: number, focus: Point, night: number, visibleRooms: Set<string>): void {
    this.time += dt;
    this.elapsed += dt;
    if (this.elapsed >= .2) {
      this.elapsed = 0;
      this.selected = pickLights([...this.sources.values()], focus, LIGHT_POOL_SIZE, night, visibleRooms, this.selected);
    }
    const active = (s: Source) => !s.room_id || visibleRooms.has(s.room_id);
    const factor = (s: Source) => flickerFactor(s.light.flicker, this.time, s.phase)
      * nightLightGain(s.when, night);
    for (const s of this.sources.values()) {
      if (s.halo) {
        s.halo.visible = haloVisible(active(s), s.when, night);
        s.halo.material.opacity = factor(s);
      }
    }
    this.slots.forEach((slot, i) => {
      const wanted = this.selected[i] || '';
      // Fade the old source to zero before assigning the new source's position.
      const next = stepLightSlot(slot, wanted, dt);
      slot.id = next.id;
      slot.gain = next.gain;
      const s = this.sources.get(slot.id);
      if (!s) {
        slot.lamp.intensity = 0;
        return;
      }
      slot.lamp.position.copy(s.pos);
      slot.lamp.distance = s.range_m;
      slot.lamp.color.set(s.light.color);
      const f = factor(s);
      if (s.light.flicker === 'fire') {
        slot.lamp.color.lerp(FIRE_COLOR, fireColourMix(this.time, s.phase));
      }
      slot.lamp.intensity = active(s) ? s.light.intensity * slot.gain * f : 0;
    });
  }
}

/** The engine owns the fixed pool; mounts own and release their source handles. */
export let propLightPool: LightPool | undefined;

/** Publish the engine's pool so recipe and world-prop mounts share one shader budget. */
export function createPropLightPool(scene: THREE.Scene): LightPool {
  propLightPool = new LightPool(scene);
  return propLightPool;
}
