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
  url: string;   // .glb oder .fbx
  height?: number;
  /** true = nur über assignments nutzbar, nicht im Zufalls-Pool (Charakter-Modelle) */
  assignOnly?: boolean;
  /** Textur separat anwenden (z.B. FBX mit externer Referenz + Bake aus GLB) */
  texture?: string;
  /** V-Flip der separaten Textur (FBX/GLB-UV-Konventionen), Default false */
  textureFlipY?: boolean;
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
  assignOnly: boolean;
}

/** Alle Knochennamen (Node-Namen unterhalb von Skinnen) eines Modells. */
function boneNames(root: THREE.Object3D): Set<string> {
  const names = new Set<string>();
  root.traverse((o) => {
    if ((o as THREE.Bone).isBone) names.add(o.name);
  });
  return names;
}

function findSkinnedMesh(root: THREE.Object3D): THREE.SkinnedMesh | null {
  let skin: THREE.SkinnedMesh | null = null;
  root.traverse((o) => {
    if (!skin && (o as THREE.SkinnedMesh).isSkinnedMesh) skin = o as THREE.SkinnedMesh;
  });
  return skin;
}

/**
 * Clips eines Spender-Modells auf ein anderes Skelett übertragen.
 * SkeletonUtils.retargetClip arbeitet über Welt-Transformationen und
 * kompensiert damit unterschiedliche Bind-Posen (naives Track-Kopieren
 * verrenkt die Figur, sobald die Ruhe-Rotationen der Knochen abweichen).
 * Knochennamen müssen übereinstimmen (Mixamo-Standard; das mixamorig:-Präfix
 * wird beim Ziel notfalls abgeschnitten).
 */
function retargetClips(
  target: THREE.Object3D,
  donor: THREE.Object3D,
  clips: THREE.AnimationClip[]
): THREE.AnimationClip[] {
  const targetSkin = findSkinnedMesh(target);
  const donorSkin = findSkinnedMesh(donor);
  if (!targetSkin || !donorSkin) return [];

  // Welt-Rest-Rotationen beider Skelette (Templates stehen in Bind-Pose)
  target.updateMatrixWorld(true);
  donor.updateMatrixWorld(true);
  const restOf = (skin: THREE.SkinnedMesh) => {
    const map = new Map<string, { q: THREE.Quaternion; parent: THREE.Quaternion }>();
    for (const bone of skin.skeleton.bones) {
      const q = bone.getWorldQuaternion(new THREE.Quaternion());
      const parent = bone.parent
        ? bone.parent.getWorldQuaternion(new THREE.Quaternion())
        : new THREE.Quaternion();
      map.set(bone.name, { q, parent });
    }
    return map;
  };
  const targetRest = restOf(targetSkin);
  const donorRest = restOf(donorSkin);

  // Quell-Knochenname -> Ziel-Knochenname (mixamorig-Präfix tolerant)
  const toTarget = new Map<string, string>();
  for (const donorName of donorRest.keys()) {
    if (targetRest.has(donorName)) toTarget.set(donorName, donorName);
    else {
      const stripped = donorName.replace(/^mixamorig:?/i, '');
      const match = [...targetRest.keys()].find((t) => t === stripped || t.replace(/^mixamorig:?/i, '') === stripped);
      if (match) toTarget.set(donorName, match);
    }
  }
  if (toTarget.size < 8) return [];

  // Pro Keyframe: q_target = inv(Rp_t) * (Rp_s * q_s * inv(R_s)) * R_t
  // (Delta der Quell-Lokalrotation in Weltkoordinaten, auf Ziel-Restpose gehoben —
  // das Verfahren aus dem three-vrm Mixamo-Beispiel, verallgemeinert auf
  // nicht-normalisierte Ziel-Rigs.)
  const out: THREE.AnimationClip[] = [];
  const qS = new THREE.Quaternion();
  for (const clip of clips) {
    const tracks: THREE.KeyframeTrack[] = [];
    for (const track of clip.tracks) {
      if (!(track instanceof THREE.QuaternionKeyframeTrack)) continue;
      const nodeName = track.name.slice(0, track.name.lastIndexOf('.'));
      const targetName = toTarget.get(nodeName);
      if (!targetName) continue;
      const dr = donorRest.get(nodeName)!;
      const tr = targetRest.get(targetName)!;
      const invRs = dr.q.clone().invert();
      const invRpT = tr.parent.clone().invert();
      const values = new Float32Array(track.values.length);
      for (let i = 0; i < track.values.length; i += 4) {
        qS.fromArray(track.values, i);
        qS.premultiply(dr.parent).multiply(invRs);   // Welt-Delta der Quelle
        qS.premultiply(invRpT).multiply(tr.q);       // in Ziel-Lokalraum heben
        qS.toArray(values, i);
      }
      tracks.push(new THREE.QuaternionKeyframeTrack(`${targetName}.quaternion`, [...track.times], [...values]));
    }
    if (tracks.length >= 8) out.push(new THREE.AnimationClip(clip.name, clip.duration, tracks));
  }
  return out;
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

    const loadFile = async (url: string): Promise<{ scene: THREE.Group; animations: THREE.AnimationClip[] }> => {
      if (/\.fbx(\?|$)/i.test(url)) {
        const { FBXLoader } = await import('three/addons/loaders/FBXLoader.js');
        const obj = await new FBXLoader().loadAsync(url);
        return { scene: obj, animations: obj.animations ?? [] };
      }
      const gltf = await loader.loadAsync(url);
      return { scene: gltf.scene, animations: gltf.animations };
    };

    const results = await Promise.allSettled(
      (manifest.models ?? []).map(async (m): Promise<LoadedModel> => {
        const gltf = await loadFile(m.url);
        const template = gltf.scene;
        if (m.texture) {
          const tex = await new THREE.TextureLoader().loadAsync(m.texture);
          tex.colorSpace = THREE.SRGBColorSpace;
          tex.flipY = !!m.textureFlipY;
          template.traverse((o) => {
            if ((o as THREE.Mesh).isMesh) {
              (o as THREE.Mesh).material = new THREE.MeshStandardMaterial({ map: tex, roughness: 0.85, metalness: 0.0 });
            }
          });
        }
        const bbox = new THREE.Box3().setFromObject(template);
        const rawHeight = Math.max(bbox.max.y - bbox.min.y, 0.01);
        const height = m.height ?? defaultHeight;
        const usable = gltf.animations.filter((c) => c.tracks.length > 0);
        // Auch statische Meshes (ohne Skelett/Clips) zulassen — Interimszustand,
        // bis ein geriggtes Modell vorliegt; solche Figuren gleiten ohne Laufanimation.
        console.info(`[figures] ${m.name}: rawHeight=${rawHeight.toFixed(3)} -> scale=${(height / rawHeight).toFixed(3)}, clips=${usable.length}, bones=${boneNames(template).size}`);
        return { name: m.name, template, clips: usable, scale: height / rawHeight, height, assignOnly: !!m.assignOnly };
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
      if (m.clips.length || !donor || !boneNames(m.template).size) continue;
      m.clips = retargetClips(m.template, donor.template, donor.clips);
      if (!m.clips.length) console.warn(`[figures] ${m.name}: Clip-Retargeting fehlgeschlagen`);
      else console.info(`[figures] ${m.name}: ${m.clips.length} Clips von ${donor.name} retargetet`);
    }
    return this.models.length > 0;
  }

  /** Modellwahl: explizites Assignment, sonst deterministisch per Namens-Hash. */
  instantiate(charName: string): Figure | null {
    if (!this.models.length) return null;
    const assigned = this.assignments[charName];
    let model = this.models.find((m) => m.name === assigned);
    if (!model) {
      const pool = this.models.filter((m) => !m.assignOnly);
      if (!pool.length) return null;
      const rnd = seededRandom('model:' + charName);
      model = pool[Math.floor(rnd() * pool.length)];
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
    // Mesh-Origin liegt nicht immer bei den Füßen: XZ zentrieren, Füße auf y=0
    inst.updateMatrixWorld(true);
    const box = new THREE.Box3().setFromObject(inst);
    if (!box.isEmpty()) {
      const center = box.getCenter(new THREE.Vector3());
      inst.position.x -= center.x;
      inst.position.z -= center.z;
      inst.position.y -= box.min.y;
    }
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
