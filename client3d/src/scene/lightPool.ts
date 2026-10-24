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
  return parent.localToWorld(new THREE.Vector3(anchor[0], bottom, anchor[1]))
    .add(new THREE.Vector3(light.offset_m[0], light.height_m, light.offset_m[1]));
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
      * (s.when === 'night' ? THREE.MathUtils.smoothstep(night, .3, .6) : 1);
    for (const s of this.sources.values()) {
      if (s.halo) {
        s.halo.visible = active(s) && (s.when !== 'night' || night > .3);
        s.halo.material.opacity = factor(s);
      }
    }
    this.slots.forEach((slot, i) => {
      const wanted = this.selected[i] || '';
      // Fade the old source to zero before assigning the new source's position.
      if (slot.id !== wanted) {
        slot.gain = Math.max(0, slot.gain - dt / .4);
        if (slot.gain === 0) slot.id = wanted;
      } else {
        slot.gain = Math.min(1, slot.gain + dt / .4);
      }
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
        slot.lamp.color.lerp(FIRE_COLOR,
          Math.max(0, (1 - flickerFactor('fire', this.time, s.phase)) / .25) * .1);
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
