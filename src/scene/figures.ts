import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import * as SkeletonUtils from 'three/addons/utils/SkeletonUtils.js';
import { seededRandom } from './textures';

/**
 * Animierte 3D-Figuren für NPCs (Stufe 1 von AV3D-5): Modelle kommen aus
 * /models/manifest.json (gebundelte Beispiel-GLBs). Später ersetzt
 * GET /characters/{name}/model diese Quelle; die Fallback-Kette
 * (Figur -> Portrait-Sprite) bleibt dieselbe.
 */

interface ManifestModel {
  name: string;
  url: string;
  height?: number;
}

interface Manifest {
  defaultHeight?: number;
  models: ManifestModel[];
  assignments?: Record<string, string>;
}

interface LoadedModel {
  name: string;
  template: THREE.Group;
  clips: THREE.AnimationClip[];
  scale: number;
  height: number; // Welthöhe nach Skalierung
}

/** Alle Knochennamen (Node-Namen unterhalb von Skinnen) eines Modells. */
function boneNames(root: THREE.Object3D): Set<string> {
  const names = new Set<string>();
  root.traverse((o) => {
    if ((o as THREE.Bone).isBone) names.add(o.name);
  });
  return names;
}

/**
 * Mixamo-Clips auf ein Skelett mit anderen Knochennamen umschreiben
 * (z.B. "mixamorig:Hips" -> "Hips" bei Make-It-Animatable-Rigs).
 * Positions-Tracks außer Hips werden verworfen (Proportionsunterschiede);
 * Rotations-Tracks übertragen sauber, solange die Skeleton-Topologie
 * (Mixamo-Standard) gleich ist.
 */
function retargetClip(clip: THREE.AnimationClip, targetBones: Set<string>): THREE.AnimationClip | null {
  const tracks: THREE.KeyframeTrack[] = [];
  for (const track of clip.tracks) {
    const dot = track.name.lastIndexOf('.');
    const nodeName = track.name.slice(0, dot);
    const prop = track.name.slice(dot + 1);
    let target = nodeName;
    if (!targetBones.has(target)) {
      target = nodeName.replace(/^mixamorig:?/i, '');
      if (!targetBones.has(target)) continue;
    }
    if (prop === 'position' || prop === 'scale') continue;
    const cloned = track.clone();
    cloned.name = `${target}.${prop}`;
    tracks.push(cloned);
  }
  if (tracks.length < 8) return null; // zu wenig übertragen -> unbrauchbar
  return new THREE.AnimationClip(clip.name, clip.duration, tracks);
}

type ClipKind = 'idle' | 'walk' | 'run' | 'sit' | 'dance' | 'wave';

const CLIP_SYNONYMS: Record<ClipKind, string[]> = {
  idle: ['idle', 'stand', 'breath'],
  walk: ['walk'],
  run: ['run'],
  sit: ['sit'],
  dance: ['dance', 'samba'],
  wave: ['wave', 'greet'],
};

/** Freitext-Activity -> Animations-Kategorie (Client-Workaround für AV3D-6). */
export function activityToClipKind(activity: string): ClipKind {
  const a = activity.toLowerCase();
  if (/sit|sitz|coffee|kaffee|eat|ess|meeting|read|les/.test(a)) return 'sit';
  if (/dance|tanz|party|feier/.test(a)) return 'dance';
  if (/wave|wink|greet|begrüß/.test(a)) return 'wave';
  return 'idle';
}

export class FigureLibrary {
  private models: LoadedModel[] = [];
  private assignments: Record<string, string> = {};

  /** true, wenn mindestens ein Modell nutzbar ist; sonst Portrait-Fallback. */
  async load(): Promise<boolean> {
    let manifest: Manifest;
    try {
      const res = await fetch('/models/manifest.json');
      if (!res.ok) return false;
      manifest = await res.json();
    } catch {
      return false;
    }
    this.assignments = manifest.assignments ?? {};
    const loader = new GLTFLoader();
    const defaultHeight = manifest.defaultHeight ?? 1.75;

    const results = await Promise.allSettled(
      (manifest.models ?? []).map(async (m): Promise<LoadedModel> => {
        const gltf = await loader.loadAsync(m.url);
        const template = gltf.scene;
        const bbox = new THREE.Box3().setFromObject(template);
        const rawHeight = Math.max(bbox.max.y - bbox.min.y, 0.01);
        const height = m.height ?? defaultHeight;
        const usable = gltf.animations.filter((c) => c.tracks.length > 0);
        const skinned = boneNames(template).size > 0;
        if (!usable.length && !skinned) throw new Error(`${m.name}: weder Animationen noch Skelett`);
        return { name: m.name, template, clips: usable, scale: height / rawHeight, height };
      })
    );
    for (const r of results) {
      if (r.status === 'fulfilled') this.models.push(r.value);
      else console.warn('[figures]', r.reason);
    }

    // Modelle mit Skelett, aber ohne Clips (z.B. Make-It-Animatable-Rigs):
    // Clips vom ersten Modell MIT Animationen leihen und auf die
    // Ziel-Knochennamen umschreiben (mixamorig-Präfix-Mapping).
    const donor = this.models.find((m) => m.clips.length > 0);
    for (const m of this.models) {
      if (m.clips.length || !donor) continue;
      const bones = boneNames(m.template);
      m.clips = donor.clips
        .map((c) => retargetClip(c, bones))
        .filter((c): c is THREE.AnimationClip => !!c);
      if (!m.clips.length) console.warn(`[figures] ${m.name}: Clip-Retargeting fehlgeschlagen`);
    }
    this.models = this.models.filter((m) => m.clips.length > 0);
    return this.models.length > 0;
  }

  /** Modellwahl: explizites Assignment, sonst deterministisch per Namens-Hash. */
  instantiate(charName: string): Figure | null {
    if (!this.models.length) return null;
    const assigned = this.assignments[charName];
    let model = this.models.find((m) => m.name === assigned);
    if (!model) {
      const rnd = seededRandom('model:' + charName);
      model = this.models[Math.floor(rnd() * this.models.length)];
    }
    return new Figure(model);
  }
}

export class Figure {
  root = new THREE.Group();
  height: number;
  private mixer: THREE.AnimationMixer;
  private actions = new Map<ClipKind, THREE.AnimationAction>();
  private current: THREE.AnimationAction | null = null;
  private currentKind: ClipKind | null = null;
  private targetYaw = Math.PI; // Default: Richtung Süden (Kamera-Grundstellung)

  constructor(model: LoadedModel) {
    this.height = model.height;
    const inst = SkeletonUtils.clone(model.template);
    inst.scale.setScalar(model.scale);
    inst.traverse((o) => {
      if ((o as THREE.Mesh).isMesh) {
        o.castShadow = true;
        o.receiveShadow = false;
        o.frustumCulled = false; // Skinned-Mesh-Bounds stimmen sonst beim Laufen nicht
      }
    });
    this.root.add(inst);

    this.mixer = new THREE.AnimationMixer(inst);
    const byName = new Map(model.clips.map((c) => [c.name.toLowerCase(), c]));
    for (const [kind, needles] of Object.entries(CLIP_SYNONYMS) as [ClipKind, string[]][]) {
      for (const needle of needles) {
        const clip = [...byName.entries()].find(([n]) => n.includes(needle))?.[1];
        if (clip) {
          this.actions.set(kind, this.mixer.clipAction(clip));
          break;
        }
      }
    }
    this.play('idle');
  }

  /** Clip mit Crossfade wechseln; fehlt der Clip, auf idle zurückfallen. */
  play(kind: ClipKind) {
    if (this.currentKind === kind) return;
    const action = this.actions.get(kind) ?? this.actions.get('idle') ?? [...this.actions.values()][0];
    if (!action || action === this.current) {
      this.currentKind = kind;
      return;
    }
    action.reset().fadeIn(0.25).play();
    this.current?.fadeOut(0.25);
    this.current = action;
    this.currentKind = kind;
  }

  faceTowards(dir: THREE.Vector3) {
    if (dir.lengthSq() < 1e-6) return;
    this.targetYaw = Math.atan2(dir.x, dir.z);
  }

  update(dt: number) {
    // kürzesten Drehweg nehmen
    let d = this.targetYaw - this.root.rotation.y;
    while (d > Math.PI) d -= Math.PI * 2;
    while (d < -Math.PI) d += Math.PI * 2;
    this.root.rotation.y += d * Math.min(1, dt * 10);
    this.mixer.update(dt);
  }
}
