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
  /** true = keine Spender-Clips retargeten (Figur bleibt in Rest-Pose) */
  noClips?: boolean;
}

interface Manifest {
  defaultHeight?: number;
  models: ManifestModel[];
  assignments?: Record<string, string>;
  /** Mixamo-Animations-Dateien (FBX/GLB), direkt auf Mixamo-Rigs anwendbar:
   *  {"run": "/models/StandardRun.fbx", ...} — Key = Clip-Kategorie */
  clipFiles?: Record<string, string>;
}

interface LoadedModel {
  name: string;
  template: THREE.Group;
  clips: THREE.AnimationClip[];
  scale: number;
  height: number; // Welthöhe nach Skalierung
  assignOnly: boolean;
  noClips: boolean;
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

  // Hierarchisches FK-Retargeting: Spender-Clip framebasiert abtasten,
  // Welt-Rotations-Deltas top-down auf das Ziel-Skelett heben. Im Gegensatz
  // zum Rest-Pose-Konjugieren werden dabei die bereits animierten
  // ELTERN-Rotationen des Ziels berücksichtigt — sonst verrenken sich Ketten
  // (Schulter/Arm), sobald sich Knochenkonventionen unterscheiden.
  const FPS = 24;

  // Spender-Klon zum Abtasten (Template nicht mutieren)
  const donorClone = SkeletonUtils.clone(donor);
  donorClone.updateMatrixWorld(true);
  const donorSkinClone = findSkinnedMesh(donorClone)!;
  target.updateMatrixWorld(true);

  const donorRestW = new Map<string, THREE.Quaternion>();
  for (const b of donorSkinClone.skeleton.bones) {
    donorRestW.set(b.name, b.getWorldQuaternion(new THREE.Quaternion()));
  }

  // Ziel-Knochen: Rest-Welt-Rotationen + Hierarchie-Reihenfolge (Eltern zuerst)
  const targetBones: THREE.Bone[] = [];
  const collect = (o: THREE.Object3D) => {
    if ((o as THREE.Bone).isBone) targetBones.push(o as THREE.Bone);
    for (const c of o.children) collect(c);
  };
  // ab Wurzel sammeln, damit die Reihenfolge Eltern->Kind garantiert ist
  let skRoot: THREE.Object3D = targetSkin.skeleton.bones[0];
  while (skRoot.parent && (skRoot.parent as THREE.Bone).isBone) skRoot = skRoot.parent;
  collect(skRoot);

  const targetRestW = new Map<THREE.Bone, THREE.Quaternion>();
  for (const b of targetBones) targetRestW.set(b, b.getWorldQuaternion(new THREE.Quaternion()));

  // Zuordnung Ziel-Knochen -> Spender-Knochen (mixamorig-Präfix tolerant)
  const donorByKey = new Map<string, THREE.Bone>();
  for (const b of donorSkinClone.skeleton.bones) {
    donorByKey.set(b.name.replace(/^mixamorig:?/i, '').toLowerCase(), b as THREE.Bone);
  }
  // Spiegel-Erkennung: sitzt der "Left*"-Knochen des Ziels auf der anderen
  // Welt-Seite als beim Spender, Links/Rechts in der Zuordnung tauschen.
  const worldX = (b: THREE.Object3D) => b.getWorldPosition(new THREE.Vector3()).x;
  const pair = new Map<THREE.Bone, THREE.Bone>();
  for (const tb of targetBones) {
    const key = tb.name.replace(/^mixamorig:?/i, '').toLowerCase();
    let db = donorByKey.get(key);
    if (db && /left|right/.test(key)) {
      const tx = worldX(tb);
      const dx = worldX(db);
      if (Math.abs(tx) > 1e-3 && Math.abs(dx) > 1e-3 && Math.sign(tx) !== Math.sign(dx)) {
        const mirrored = key.includes('left') ? key.replace('left', 'right') : key.replace('right', 'left');
        db = donorByKey.get(mirrored) ?? db;
      }
    }
    if (db) pair.set(tb, db);
  }
  if (pair.size < 8) return [];

  // Hüfte für Positions-Track (Lauf-Bounce), skaliert über Hüfthöhen-Verhältnis
  const targetHips = targetBones.find((b) => /hips$/i.test(b.name));
  const donorHips = donorHipsBone(donorSkinClone);
  const tHipsRestPos = targetHips?.getWorldPosition(new THREE.Vector3());
  const dHipsRestPos = donorHips?.getWorldPosition(new THREE.Vector3());
  const hipScale = tHipsRestPos && dHipsRestPos && dHipsRestPos.y > 1e-6 ? tHipsRestPos.y / dHipsRestPos.y : 1;
  const hipsParentInv = targetHips
    ? new THREE.Matrix4().copy((targetHips.parent as THREE.Object3D).matrixWorld).invert()
    : null;

  // Aim-Retargeting: pro Knochen die Richtung zum Kind übertragen statt
  // Rotations-Deltas — robust gegen gespiegelte/abweichende Knochen-Frames.
  const firstBoneChild = (b: THREE.Object3D): THREE.Bone | undefined =>
    b.children.find((c) => (c as THREE.Bone).isBone) as THREE.Bone | undefined;
  const donorChild = new Map<THREE.Bone, THREE.Bone>();
  for (const db of donorSkinClone.skeleton.bones) {
    const c = firstBoneChild(db);
    if (c) donorChild.set(db as THREE.Bone, c);
  }
  const targetRestDir = new Map<THREE.Bone, THREE.Vector3>();
  for (const tb of targetBones) {
    const c = firstBoneChild(tb);
    if (!c) continue;
    const dir = c.getWorldPosition(new THREE.Vector3()).sub(tb.getWorldPosition(new THREE.Vector3()));
    if (dir.lengthSq() > 1e-10) targetRestDir.set(tb, dir.normalize());
  }

  const mixer = new THREE.AnimationMixer(donorClone);
  const out: THREE.AnimationClip[] = [];
  const desired = new THREE.Quaternion();
  const qLocal = new THREE.Quaternion();
  const vA = new THREE.Vector3();
  const vB = new THREE.Vector3();
  const qAlign = new THREE.Quaternion();

  for (const clip of clips) {
    const action = mixer.clipAction(clip);
    action.play();
    const frames = Math.max(2, Math.round(clip.duration * FPS) + 1);
    const times = new Float32Array(frames);
    const values = new Map<THREE.Bone, Float32Array>();
    for (const tb of pair.keys()) values.set(tb, new Float32Array(frames * 4));
    const hipPos = targetHips ? new Float32Array(frames * 3) : null;

    for (let f = 0; f < frames; f++) {
      const t = Math.min(clip.duration, f / FPS);
      times[f] = t;
      mixer.setTime(t);
      donorClone.updateMatrixWorld(true);

      // Ziel-Welt-Rotationen dieses Frames, top-down aufgebaut
      const worldQ = new Map<THREE.Object3D, THREE.Quaternion>();
      for (const tb of targetBones) {
        const parent = tb.parent as THREE.Object3D;
        const pW = (parent as THREE.Bone).isBone
          ? worldQ.get(parent) ?? targetRestW.get(parent as THREE.Bone)!
          : parent.getWorldQuaternion(new THREE.Quaternion());
        const db = pair.get(tb);
        if (!db) {
          // unanimierter Knochen: Rest-Lokalrotation beibehalten
          worldQ.set(tb, pW.clone().multiply(tb.quaternion));
          continue;
        }
        const dc = donorChild.get(db);
        const restDir = targetRestDir.get(tb);
        if (dc && restDir) {
          // Aim: Ziel-Knochen so drehen, dass er in die Welt-Richtung des
          // Spender-Knochens zeigt (Rest-Richtung -> aktuelle Richtung)
          dc.getWorldPosition(vA);
          db.getWorldPosition(vB);
          vA.sub(vB);
          if (vA.lengthSq() > 1e-10) {
            qAlign.setFromUnitVectors(restDir, vA.normalize());
            desired.copy(qAlign).multiply(targetRestW.get(tb)!);
          } else {
            desired.copy(targetRestW.get(tb)!);
          }
        } else {
          // End-Knochen (Hände, Zehen): Eltern-Bewegung erben, Rest-Lokalrotation halten
          worldQ.set(tb, pW.clone().multiply(tb.quaternion));
          const rest = new THREE.Quaternion().copy(tb.quaternion);
          rest.toArray(values.get(tb)!, f * 4);
          continue;
        }
        qLocal.copy(pW).invert().multiply(desired);
        worldQ.set(tb, desired.clone());
        qLocal.toArray(values.get(tb)!, f * 4);
      }

      if (targetHips && donorHips && hipPos && tHipsRestPos && dHipsRestPos && hipsParentInv) {
        const dPos = donorHips.getWorldPosition(new THREE.Vector3());
        const worldPos = tHipsRestPos.clone().add(dPos.sub(dHipsRestPos).multiplyScalar(hipScale));
        worldPos.applyMatrix4(hipsParentInv);
        worldPos.toArray(hipPos, f * 3);
      }
    }

    const tracks: THREE.KeyframeTrack[] = [];
    for (const [tb, vals] of values) {
      tracks.push(new THREE.QuaternionKeyframeTrack(`${tb.name}.quaternion`, [...times], [...vals]));
    }
    if (targetHips && hipPos) {
      tracks.push(new THREE.VectorKeyframeTrack(`${targetHips.name}.position`, [...times], [...hipPos]));
    }
    action.stop();
    mixer.uncacheClip(clip);
    if (tracks.length >= 8) out.push(new THREE.AnimationClip(clip.name, clip.duration, tracks));
  }
  return out;
}

function donorHipsBone(skin: THREE.SkinnedMesh): THREE.Bone | undefined {
  return skin.skeleton.bones.find((b) => /hips$/i.test(b.name.replace(/^mixamorig:?/i, '')));
}

/**
 * Mixamo-Animations-Clips (aus FBX) direkt auf ein Mixamo-Rig anwenden:
 * Tracknamen auf die tatsächlichen Knochennamen des Ziels normalisieren,
 * Hips-Positions-Track auf die Rig-Größe skalieren, übrige Positions-/
 * Scale-Tracks verwerfen. Kein Retargeting — funktioniert, weil beide Seiten
 * dieselbe Mixamo-Bind-Pose verwenden.
 */
function adaptExternalClips(clips: THREE.AnimationClip[], target: THREE.Object3D): THREE.AnimationClip[] {
  const norm = (s: string) => s.replace(/^mixamorig:?/i, '').replace(/:/g, '').toLowerCase();
  const boneByKey = new Map<string, THREE.Bone>();
  target.traverse((o) => {
    if ((o as THREE.Bone).isBone) boneByKey.set(norm(o.name), o as THREE.Bone);
  });
  if (!boneByKey.size) return [];
  const hips = [...boneByKey.entries()].find(([k]) => /hips$/.test(k))?.[1];

  // Hüfte: Mixamo-Clips sind für ein Rig ohne Armature-Rotation autoriert
  // (Hüft-Rest ~ Identität). Unsere Rigs kompensieren die +90°-Armature-
  // Rotation in der Hüft-Ruhe-Rotation — direktes Kopieren überschreibt die
  // Kompensation und kippt die Figur auf den Bauch. Deshalb: Clip-Werte in
  // den Eltern-Raum der Ziel-Hüfte heben (Rotation UND Position).
  target.updateMatrixWorld(true);
  let hipsRotFix = new THREE.Quaternion();
  let hipsPosMatrix: THREE.Matrix4 | null = null;
  let hipsPosScale = 1;
  if (hips && hips.parent) {
    const parent = hips.parent as THREE.Object3D;
    hipsRotFix = parent.getWorldQuaternion(new THREE.Quaternion()).invert();
    hipsPosMatrix = parent.matrixWorld.clone().invert();
    const restWorldY = hips.getWorldPosition(new THREE.Vector3()).y;
    // Mixamo-Hüfthöhe (~98cm) auf die Welthöhe des Ziel-Rigs skalieren
    hipsPosScale = restWorldY > 1e-6 ? restWorldY : 1;
  }

  const q = new THREE.Quaternion();
  const v = new THREE.Vector3();
  const out: THREE.AnimationClip[] = [];
  for (const clip of clips) {
    const tracks: THREE.KeyframeTrack[] = [];
    let clipHipsY = 0;
    // Referenz: Hüfthöhe des Clips im ersten Frame (für die Skalierung)
    for (const track of clip.tracks) {
      if (track.name.endsWith('.position') && /hips\./i.test(track.name.replace(/^mixamorig:?/i, ''))) {
        clipHipsY = Math.abs(track.values[1]) || Math.abs(track.values[0]) || 1;
        break;
      }
    }
    for (const track of clip.tracks) {
      const dot = track.name.lastIndexOf('.');
      const node = track.name.slice(0, dot);
      const prop = track.name.slice(dot + 1);
      const bone = boneByKey.get(norm(node));
      if (!bone) continue;
      if (prop === 'quaternion') {
        if (bone === hips) {
          const vals = new Float32Array(track.values.length);
          for (let i = 0; i < track.values.length; i += 4) {
            q.fromArray(track.values, i).premultiply(hipsRotFix);
            q.toArray(vals, i);
          }
          tracks.push(new THREE.QuaternionKeyframeTrack(`${bone.name}.quaternion`, [...track.times], [...vals]));
        } else {
          const t = track.clone();
          t.name = `${bone.name}.quaternion`;
          tracks.push(t);
        }
      } else if (prop === 'position' && bone === hips && hips && hipsPosMatrix && clipHipsY > 1e-6) {
        // Nur das vertikale Wippen übernehmen (relativ zum ersten Frame),
        // Lokomotion/Drift verwerfen — die Wurzel bewegt der Client selbst.
        const k = hipsPosScale / clipHipsY;
        const y0 = track.values[1];
        const rest = hips.position;
        const vals = new Float32Array(track.values.length);
        for (let i = 0; i < track.values.length; i += 3) {
          const bounce = (track.values[i + 1] - y0) * k; // Welt-Delta in m
          v.set(0, bounce, 0).applyMatrix4(hipsPosMatrix); // in Eltern-Raum (Richtung+Skala)
          v.sub(new THREE.Vector3().setFromMatrixPosition(hipsPosMatrix!)); // nur Richtungsanteil
          v.add(rest);
          v.toArray(vals, i);
        }
        tracks.push(new THREE.VectorKeyframeTrack(`${bone.name}.position`, [...track.times], [...vals]));
      }
    }
    if (tracks.length >= 8) out.push(new THREE.AnimationClip(clip.name, clip.duration, tracks));
  }
  return out;
}

type ClipKind = 'idle' | 'walk' | 'run' | 'sit' | 'dance' | 'wave' | 'cmuwalk';

const CLIP_SYNONYMS: Record<ClipKind, string[]> = {
  cmuwalk: ['cmuwalk'],
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
  if (/sit|sitz|eat|ess|meeting|read|les|sleep|schlaf/.test(a)) return 'sit';
  if (/dance|tanz|party|feier/.test(a)) return 'dance';
  if (/wave|wink|greet|begrüß/.test(a)) return 'wave';
  return 'idle';
}

export class FigureLibrary {
  private models: LoadedModel[] = [];
  private assignments: Record<string, string> = {};

  /** true, wenn mindestens ein Modell nutzbar ist; sonst Portrait-Fallback.
   *  opts.only: nur dieses Modell laden (Name oder Charaktername) —
   *  sonst alle Standard-Modelle + zugewiesene (assignOnly ohne Zuweisung
   *  wird übersprungen; Test-Modelle blähen sonst jeden Seitenaufruf auf). */
  async load(opts: { only?: string } = {}): Promise<boolean> {
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

    let wanted = manifest.models ?? [];
    if (opts.only) {
      const name = this.assignments[opts.only] ?? opts.only;
      wanted = wanted.filter((m) => m.name === name);
    } else {
      const assigned = new Set(Object.values(this.assignments));
      wanted = wanted.filter((m) => !m.assignOnly || assigned.has(m.name));
    }

    const results = await Promise.allSettled(
      wanted.map(async (m): Promise<LoadedModel> => {
        const gltf = await loadFile(m.url);
        const template = gltf.scene;
        // Z-up-Exporte (Blender/FBX-Route) automatisch aufrichten
        {
          const b = new THREE.Box3().setFromObject(template);
          const s = b.getSize(new THREE.Vector3());
          if (s.z > s.y * 1.5) {
            template.rotation.x = -Math.PI / 2;
            template.updateMatrixWorld(true);
          }
        }
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
        return { name: m.name, template, clips: usable, scale: height / rawHeight, height, assignOnly: !!m.assignOnly, noClips: !!m.noClips };
      })
    );
    for (const r of results) {
      if (r.status === 'fulfilled') this.models.push(r.value);
      else console.warn('[figures]', r.reason);
    }

    // Modelle mit Skelett, aber ohne Clips (z.B. Make-It-Animatable-Rigs):
    // Clips vom ersten Modell MIT Animationen leihen und auf die
    // Ziel-Knochennamen umschreiben (mixamorig-Präfix-Mapping).
    // Externe Mixamo-Clips laden (passen ohne Retargeting auf Mixamo-Rigs)
    const externalClips: THREE.AnimationClip[] = [];
    for (const [kind, url] of Object.entries(manifest.clipFiles ?? {})) {
      try {
        const { animations } = await loadFile(url);
        if (animations[0]) {
          const c = animations[0].clone();
          c.name = kind;
          externalClips.push(c);
        }
      } catch (e) {
        console.warn('[figures] clipFile nicht ladbar:', url, e);
      }
    }

    const donor = this.models.find((m) => m.clips.length > 0);
    for (const m of this.models) {
      if (m.clips.length || m.noClips || !boneNames(m.template).size) continue;
      if (externalClips.length) {
        m.clips = adaptExternalClips(externalClips, m.template);
        if (m.clips.length) {
          console.info(`[figures] ${m.name}: ${m.clips.length} Mixamo-Clips direkt angewandt`);
          continue;
        }
      }
      if (!donor) continue;
      m.clips = retargetClips(m.template, donor.template, donor.clips);
      if (!m.clips.length) console.warn(`[figures] ${m.name}: Clip-Retargeting fehlgeschlagen`);
      else console.info(`[figures] ${m.name}: ${m.clips.length} Clips von ${donor.name} retargetet`);
    }
    return this.models.length > 0;
  }

  /** Modellwahl: explizites Assignment, sonst deterministisch per Namens-Hash. */
  instantiate(charName: string): Figure | null {
    if (!this.models.length) return null;
    const assigned = this.assignments[charName] ?? charName; // direkter Modellname zählt auch
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
    const resolved = this.actions.get(kind) ?? this.actions.get('idle') ?? [...this.actions.values()][0];
    if (!resolved || resolved === this.current) {
      this.currentKind = kind;
      // Fallback-Fall: gleicher Clip, aber ggf. Tempo anpassen (siehe unten)
      if (this.current) this.current.timeScale = kind === 'idle' && !this.actions.has('idle') ? 0.1 : 1;
      return;
    }
    // Fallback-Tempo: fehlender Idle-Clip -> Zeitlupe (wirkt wie Wippen);
    // fehlender Run-Clip -> Walk beschleunigt
    resolved.timeScale = kind === 'idle' && !this.actions.has('idle') ? 0.1
      : kind === 'run' && !this.actions.has('run') ? 1.5 : 1;
    resolved.reset().fadeIn(0.25).play();
    this.current?.fadeOut(0.25);
    this.current = resolved;
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
