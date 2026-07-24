import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import * as SkeletonUtils from 'three/addons/utils/SkeletonUtils.js';
import { seededRandom } from './textures';
import type { ApiModel } from '../api';
import { getAnimationClips, getCharacterModel } from '../api';

/**
 * Animierte 3D-Figuren für NPCs (AV3D-5): Modelle kommen vom Server
 * (GET /characters/{name}/model3d), /models/manifest.json ist nur noch
 * Dev-/Offline-Fallback. Die Fallback-Kette (Figur -> Portrait-Sprite)
 * bleibt dieselbe.
 */

/** Basishöhe einer Figur ohne height_cm, in REALEN Metern.
 *  Vertrag schnittstellen-3d.md § A3 — Welthöhe = dieser Wert x k
 *  (roomFigureScale). Nicht auf 1,75 zurückdrehen: die Admin-Vorschau
 *  und die Prop-/Diorama-Maßstäbe rechnen mit 1,70. */
export const BASE_FIGURE_HEIGHT_M = 1.70;

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
  // Steh-Referenz der Quelle: MAXIMALE Hüfthöhe über ALLE Clips des Sets.
  // Ein einzelner In-Pose-Clip (Sitzen/Liegen startet abgesenkt) hat keine
  // eigene Referenz — mit dem ersten Frame als Bezug blieb die Hüfte beim
  // Sitzen auf Stehhöhe hängen. Walk/Idle im Set liefern die echte Stehhöhe.
  let sourceRest = 0;
  for (const clip of clips) {
    for (const track of clip.tracks) {
      if (track.name.endsWith('.position') && /hips\./i.test(track.name.replace(/^mixamorig:?/i, ''))) {
        for (let i = 1; i < track.values.length; i += 3) {
          sourceRest = Math.max(sourceRest, Math.abs(track.values[i]));
        }
      }
    }
  }
  const out: THREE.AnimationClip[] = [];
  for (const clip of clips) {
    const tracks: THREE.KeyframeTrack[] = [];
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
      } else if (prop === 'position' && bone === hips && hips && hipsPosMatrix && sourceRest > 1e-6) {
        // Nur die vertikale Hüftbewegung übernehmen (relativ zur STEH-
        // Referenz der Quelle — so senken Sitz-/Liege-Clips die Hüfte ab),
        // Lokomotion/Drift verwerfen — die Wurzel bewegt der Client selbst.
        const k = hipsPosScale / sourceRest;
        const rest = hips.position;
        const vals = new Float32Array(track.values.length);
        for (let i = 0; i < track.values.length; i += 3) {
          const bounce = (Math.abs(track.values[i + 1]) - sourceRest) * k; // Welt-Delta in m
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

type ClipKind = string;   // offenes Vokabular — der Server bestimmt die kinds

const CLIP_SYNONYMS: Record<string, string[]> = {
  idle: ['idle', 'stand', 'breath'],
  walk: ['walk'],
  run: ['run'],
  sit: ['sit'],
  lie: ['lie', 'lay', 'sleep'],
  dance: ['dance', 'samba'],
  wave: ['wave', 'greet'],
};

/** Ersatz-Clip, wenn der gewünschte fehlt (bevor auf idle zurückgefallen wird):
 *  ein Liegender soll wenigstens sitzen, ein Rennender schnell gehen. */
const CLIP_FALLBACK: Record<string, ClipKind> = {
  lie: 'sit',
  run: 'walk',
};


/** Freitext-Activity -> Animations-Kategorie (Client-Workaround für AV3D-6). */
export function activityToClipKind(activity: string): ClipKind {
  const a = activity.toLowerCase();
  if (/sleep|schlaf|liege|lying|nap|bett/.test(a)) return 'lie';
  if (/sit|sitz|eat|ess|meeting|read|les/.test(a)) return 'sit';
  if (/dance|tanz|party|feier/.test(a)) return 'dance';
  if (/wave|wink|greet|begrüß/.test(a)) return 'wave';
  return 'idle';
}

export class FigureLibrary {
  private models: LoadedModel[] = [];
  private assignments: Record<string, string> = {};
  /** Vom Server geladene Charakter-Modelle (null = Server hat keins). */
  private apiModels = new Map<string, LoadedModel | null>();
  /** Signatur des geladenen Modells je Charakter (Outfit-Wechsel erkennen) */
  private apiSignature = new Map<string, string>();
  private pending = new Set<string>();
  /** Server-Clips: kind -> (set|'' -> Clip) */
  private clipIndex = new Map<string, Map<string, THREE.AnimationClip>>();
  /** Set-Fallback-Kette pro Charakter (aus der Worldmap) */
  private charSets = new Map<string, string[]>();
  /** Körpergröße pro Charakter in Metern (aus height_cm der Worldmap) */
  private charHeight = new Map<string, number>();
  /** Figuren-Basishöhe in REALEN Metern (Vertrag § A3: 1,70; Welthöhe = x k) */
  private defaultHeight = BASE_FIGURE_HEIGHT_M;
  /** wird gerufen, sobald ein nachgeladenes Charakter-Modell bereit ist */
  onModelReady: ((charName: string) => void) | null = null;

  /** true, wenn mindestens ein Modell nutzbar ist; sonst Portrait-Fallback.
   *  opts.only: nur dieses Modell laden (Name oder Charaktername) —
   *  sonst alle Standard-Modelle + zugewiesene (assignOnly ohne Zuweisung
   *  wird übersprungen; Test-Modelle blähen sonst jeden Seitenaufruf auf). */
  async load(opts: { only?: string } = {}): Promise<boolean> {
    // Manifest ist optional (Dev-/Offline-Fallback) — fehlt es, arbeiten wir
    // rein mit den Server-Assets weiter.
    let manifest: Manifest = { models: [] };
    try {
      const res = await fetch('/models/manifest.json');
      if (res.ok) manifest = await res.json();
    } catch { /* kein Manifest -> nur Server-Assets */ }
    this.assignments = manifest.assignments ?? {};
    const loader = new GLTFLoader();
    const defaultHeight = manifest.defaultHeight ?? BASE_FIGURE_HEIGHT_M;

    const loadFile = async (url: string, forceFbx = false): Promise<{ scene: THREE.Group; animations: THREE.AnimationClip[] }> => {
      if (forceFbx || /\.fbx(\?|$)/i.test(url)) {
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
    // Clips: bevorzugt die globale Bibliothek des Servers (AV3D-5),
    // sonst die lokalen Manifest-Clips (Dev-/Offline-Betrieb).
    const serverClips = await getAnimationClips();
    const sources: Array<{ kind: string; set: string; url: string }> = serverClips.map((c) => ({
      kind: c.kind, set: c.set ?? '', url: c.url,
    }));
    if (!sources.length) {
      // Dev-/Offline-Fallback: lokale Manifest-Clips (ohne Sets)
      for (const [kind, url] of Object.entries(manifest.clipFiles ?? {})) sources.push({ kind, set: '', url });
    } else {
      const desc = sources.map((s) => s.set ? `${s.kind}/${s.set}` : s.kind).join(', ');
      console.info(`[figures] ${sources.length} Clips vom Server: ${desc}`);
    }
    for (const { kind, set, url } of sources) {
      try {
        const { animations } = await loadFile(url);
        if (!animations[0]) continue;
        const clip = animations[0].clone();
        clip.name = kind;
        if (!this.clipIndex.has(kind)) this.clipIndex.set(kind, new Map());
        const bySet = this.clipIndex.get(kind)!;
        if (!bySet.has(set)) bySet.set(set, clip);   // erster Treffer je kind+set
      } catch (e) {
        console.warn('[figures] Clip nicht ladbar:', url, e);
      }
    }
    this.defaultHeight = defaultHeight;
    this.loadFile = loadFile;

    const donor = this.models.find((m) => m.clips.length > 0);
    for (const m of this.models) {
      if (m.clips.length || m.noClips || !boneNames(m.template).size) continue;
      const fallbackClips = this.clipsFor(m.name);
      if (fallbackClips.length) {
        m.clips = adaptExternalClips(fallbackClips, m.template);
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
    return true;   // Server-Modelle kommen ggf. später (fetchCharacterModel)
  }

  private loadFile!: (url: string, forceFbx?: boolean) => Promise<{ scene: THREE.Group; animations: THREE.AnimationClip[] }>;

  /** Set-Fallback-Kette eines Charakters merken (aus /play/worldmap). */
  setCharacterSets(charName: string, sets: string[] | undefined) {
    if (sets?.length) this.charSets.set(charName, sets);
  }

  /** Modellwechsel prüfen (z.B. neues Outfit): Signatur vom Server holen und
   *  bei Abweichung das Modell verwerfen -> wird neu geladen. */
  async refreshIfChanged(charName: string): Promise<boolean> {
    const known = this.apiSignature.get(charName);
    if (!known || this.pending.has(charName)) return false;
    let info: ApiModel | null;
    try {
      info = await getCharacterModel(charName);
    } catch {
      return false;   // Server gerade nicht erreichbar -> nächster Poll
    }
    if (!info?.signature || info.signature === known) return false;
    console.info(`[figures] ${charName}: Modell geändert (${known} -> ${info.signature}) — lade neu`);
    this.apiModels.delete(charName);
    this.apiSignature.delete(charName);
    this.fetchCharacterModel(charName);
    return true;
  }

  /** Körpergröße eines Charakters merken (cm -> m); wirkt beim nächsten Bau. */
  setCharacterHeight(charName: string, heightCm: number | undefined) {
    if (heightCm && heightCm > 30 && heightCm < 400) this.charHeight.set(charName, heightCm / 100);
  }

  /** Clips für einen Charakter gemäß seiner Set-Kette auswählen:
   *  <kind>_<set1> → <kind>_<set2> → … → <kind> (ohne Set). */
  private clipsFor(charName: string): THREE.AnimationClip[] {
    const chain = [...(this.charSets.get(charName) ?? []), ''];
    const out: THREE.AnimationClip[] = [];
    for (const [kind, bySet] of this.clipIndex) {
      for (const set of chain) {
        const clip = bySet.get(set);
        if (clip) {
          const c = clip.clone();
          c.name = kind;
          out.push(c);
          break;
        }
      }
    }
    return out;
  }

  /** Modell eines Charakters vom Server nachladen (einmal pro Name).
   *  Ergebnis landet im Cache; onModelReady meldet die Fertigstellung. */
  private fetchCharacterModel(charName: string) {
    if (this.apiModels.has(charName) || this.pending.has(charName)) return;
    this.pending.add(charName);
    void (async () => {
      try {
        const info = await getCharacterModel(charName);
        if (!info) {
          this.apiModels.set(charName, null);   // Server hat keins -> Portrait
          return;
        }
        const model = await this.buildModel(charName, info);
        this.apiModels.set(charName, model);
        if (info.signature) this.apiSignature.set(charName, info.signature);
        console.info(`[figures] ${charName}: Modell vom Server (${info.format}/${info.rig}, ${model.clips.length} Clips, ${(model.height * 100).toFixed(0)} cm)`);
        this.onModelReady?.(charName);
      } catch (e) {
        // Transienter Fehler (Netzwerk, 5xx, Textur): nicht als "hat keins"
        // cachen, sondern später erneut versuchen.
        console.warn(`[figures] ${charName}: Modell nicht ladbar — neuer Versuch in 30 s`, e);
        window.setTimeout(() => this.fetchCharacterModel(charName), 30_000);
      } finally {
        this.pending.delete(charName);
      }
    })();
  }

  /** Modell laden, aufrichten, normalisieren; Clips nur bei Mixamo-Rig.
   *  FBX-Modelle (generic/Tiere) bekommen ihre Textur separat. */
  private async buildModel(name: string, info: ApiModel): Promise<LoadedModel> {
    const gltf = await this.loadFile(info.url, info.format === 'fbx');
    const template = gltf.scene;
    if (info.textureUrl) {
      const tex = await new THREE.TextureLoader().loadAsync(info.textureUrl);
      tex.colorSpace = THREE.SRGBColorSpace;
      tex.flipY = false;   // FBX-UVs entsprechen der glTF-Konvention
      template.traverse((o) => {
        if ((o as THREE.Mesh).isMesh) {
          (o as THREE.Mesh).material = new THREE.MeshStandardMaterial({ map: tex, roughness: 0.85, metalness: 0 });
        }
      });
    }
    const b = new THREE.Box3().setFromObject(template);
    const s = b.getSize(new THREE.Vector3());
    if (s.z > s.y * 1.5) {                       // Z-up-Export aufrichten
      template.rotation.x = -Math.PI / 2;
      template.updateMatrixWorld(true);
    }
    const bbox = new THREE.Box3().setFromObject(template);
    const rawHeight = Math.max(bbox.max.y - bbox.min.y, 0.01);
    const height = this.charHeight.get(name) ?? this.defaultHeight;
    const model: LoadedModel = {
      name, template,
      clips: gltf.animations.filter((c) => c.tracks.length > 0),
      scale: height / rawHeight, height, assignOnly: true, noClips: false,
    };
    // Clips gemäß der Set-Kette des Charakters (female/male/animal/custom).
    // "generic"-Rigs (eigene Skelette) bleiben clip-los -> prozedurales Idle.
    if (info.rig !== 'generic' && !model.clips.length && boneNames(template).size) {
      const candidates = this.clipsFor(name);
      if (candidates.length) model.clips = adaptExternalClips(candidates, template);
    }
    return model;
  }

  /** Modellwahl: Server-Modell > Manifest-Assignment > Pool (Demo-Welt). */
  instantiate(charName: string): Figure | null {
    const api = this.apiModels.get(charName);
    if (api) return new Figure(api);
    if (api === undefined) this.fetchCharacterModel(charName);   // nachladen anstoßen
    // api === null (Server hat keins) oder noch nicht geladen:
    // weiter zu Manifest-Assignment/Pool — sonst Portrait-Fallback.
    if (!this.models.length) return null;
    const assigned = this.assignments[charName] ?? charName;
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

/** Eine erkannte Beinkette eines clip-losen Rigs (prozeduraler Gang). */
interface LegChain {
  /** oberstes Gelenk der Kette (Hüfte/Schulter) */
  bone: THREE.Bone;
  /** Bind-Rotation des Gelenks (lokal) — Ruhelage */
  bindQuat: THREE.Quaternion;
  /** Schwungachse im Eltern-Raum des Gelenks */
  axis: THREE.Vector3;
  /** Gangphase beim Gehen: 4-Takt-Schritt, jedes Bein 90° versetzt */
  phaseWalk: number;
  /** Gangphase beim Rennen: Trab, diagonale Paare gemeinsam */
  phaseRun: number;
}

/**
 * Beinketten an einem beliebigen Skelett heuristisch erkennen (UniRig-Tiere):
 * Blatt-Knochen, die nahe dem Boden enden, und von dort aufwärts die
 * unverzweigte Kette bis unter die Wirbelsäule — das oberste Glied ist das
 * Hüft-/Schultergelenk, das beim Laufen schwingt.
 * Erwartet, dass die matrixWorld-Werte zum übergebenen Bounding-Box-Raum
 * passen (kein updateMatrixWorld dazwischen).
 */
function findLegChains(inst: THREE.Object3D, box: THREE.Box3): LegChain[] {
  const bones: THREE.Bone[] = [];
  inst.traverse((o) => { if ((o as THREE.Bone).isBone) bones.push(o as THREE.Bone); });
  if (!bones.length) return [];

  const size = box.getSize(new THREE.Vector3());
  const center = box.getCenter(new THREE.Vector3());
  const height = Math.max(size.y, 1e-3);
  const boneKids = (b: THREE.Object3D) => b.children.filter((c) => (c as THREE.Bone).isBone);

  const found: { bone: THREE.Bone; foot: THREE.Vector3 }[] = [];
  for (const leaf of bones) {
    if (boneKids(leaf).length) continue;                       // nur Ketten-Enden
    const foot = new THREE.Vector3().setFromMatrixPosition(leaf.matrixWorld);
    if (foot.y > box.min.y + height * 0.25) continue;          // endet nicht am Boden
    // aufwärts bis zur ersten Verzweigung (dort beginnt Wirbelsäule/Becken)
    let top: THREE.Bone = leaf;
    while ((top.parent as THREE.Bone)?.isBone && boneKids(top.parent!).length === 1) {
      top = top.parent as THREE.Bone;
    }
    if (top === leaf) continue;                                // Einzelknochen ist kein Bein
    const hip = new THREE.Vector3().setFromMatrixPosition(top.matrixWorld);
    if (hip.y - foot.y < height * 0.12) continue;              // Kette führt nicht aufwärts (z.B. Schwanz)
    if (!found.some((f) => f.bone === top)) found.push({ bone: top, foot });
  }
  // mehr als 4 Kandidaten: die bodennächsten sind die Beine
  found.sort((a, b) => a.foot.y - b.foot.y);
  const legs = found.slice(0, 4);

  // Körper-Längsachse = längere Grundflächen-Seite; Schwungachse quer dazu
  const long: 'x' | 'z' = size.x > size.z ? 'x' : 'z';
  const cross: 'x' | 'z' = long === 'x' ? 'z' : 'x';
  const axisWorld = long === 'x' ? new THREE.Vector3(0, 0, 1) : new THREE.Vector3(1, 0, 0);
  const q = new THREE.Quaternion();
  const chains = legs.map(({ bone, foot }) => {
    bone.parent!.getWorldQuaternion(q);
    return {
      bone, foot,
      bindQuat: bone.quaternion.clone(),
      axis: axisWorld.clone().applyQuaternion(q.invert()).normalize(),
      phaseWalk: 0,
      phaseRun: 0,
    };
  });

  // Gangphasen: Beinpaare über Sortierung zuordnen (vorn/hinten x links/rechts) —
  // Vorzeichen relativ zum Box-Zentrum sind unzuverlässig (Schwanz verschiebt es).
  if (chains.length === 4) {
    const byLong = [...chains].sort((a, b) => a.foot[long] - b.foot[long]);
    const [aL, aR] = byLong.slice(0, 2).sort((a, b) => a.foot[cross] - b.foot[cross]);
    const [bL, bR] = byLong.slice(2).sort((a, b) => a.foot[cross] - b.foot[cross]);
    // Gehen: 4-Takt-Schritt in seitlicher Folge (wie Katze/Hund:
    // hinten-links -> vorn-links -> hinten-rechts -> vorn-rechts)
    aL.phaseWalk = 0; bL.phaseWalk = Math.PI / 2;
    aR.phaseWalk = Math.PI; bR.phaseWalk = Math.PI * 1.5;
    // Rennen: Trab — diagonale Paare gemeinsam
    aL.phaseRun = 0; bR.phaseRun = 0;
    aR.phaseRun = Math.PI; bL.phaseRun = Math.PI;
  } else {
    // 1-3 Beine erkannt: links/rechts gegenphasig als bester Rest-Fall
    for (const c of chains) {
      const p = c.foot[cross] >= center[cross] ? 0 : Math.PI;
      c.phaseWalk = p; c.phaseRun = p;
    }
  }
  return chains;
}

export class Figure {
  root = new THREE.Group();
  height: number;
  private mixer: THREE.AnimationMixer;
  private actions = new Map<ClipKind, THREE.AnimationAction>();
  private current: THREE.AnimationAction | null = null;
  private currentKind: ClipKind | null = null;
  private targetYaw = Math.PI; // Default: Richtung Süden (Kamera-Grundstellung)

  private baseScale = 1;
  /** Y-Offset, der die Füße auf y=0 bringt (Mesh-Origin liegt nicht immer dort) */
  private groundY = 0;

  constructor(model: LoadedModel) {
    this.height = model.height;
    this.baseScale = model.scale;
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
    this.groundY = inst.position.y;
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
    // Clip-lose Rigs (UniRig-Tiere): Beinketten für den prozeduralen Gang
    if (this.actions.size === 0 && !box.isEmpty()) {
      this.legs = findLegChains(inst, box);
      if (this.legs.length) console.info(`[figures] prozeduraler Gang: ${this.legs.length} Beinketten erkannt`);
    }
    this.play('idle');
  }

  /** Clip mit Crossfade wechseln; fehlt der Clip: Ersatz-Clip, dann idle. */
  play(kind: ClipKind) {
    if (this.currentKind === kind) return;
    const fallback = CLIP_FALLBACK[kind];
    const resolved = this.actions.get(kind)
      ?? (fallback ? this.actions.get(fallback) : undefined)
      ?? this.actions.get('idle')
      ?? [...this.actions.values()][0];
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

  /** true, wenn keine Animationsclips vorhanden sind (z.B. Tier-Rig oder
   *  statisches Mesh) — dann übernimmt ein prozedurales Idle. */
  get isStatic(): boolean {
    return this.actions.size === 0;
  }

  private idlePhase = Math.random() * Math.PI * 2;
  private legs: LegChain[] = [];
  private walkPhase = Math.random() * Math.PI * 2;

  update(dt: number) {
    // Ohne Clips: prozedurale Animation — beim Laufen schwingen die erkannten
    // Beinketten (Trab), im Stand leichtes Atmen/Wippen, damit die Figur
    // nicht wie eine Statue wirkt (Tier-Rigs von UniRig haben keine Clips).
    if (this.isStatic) {
      const inst = this.root.children[0];
      const walking = this.currentKind === 'walk' || this.currentKind === 'run';
      if (walking && this.legs.length) {
        const running = this.currentKind === 'run';
        this.walkPhase += dt * (running ? 11 : 7);
        for (const leg of this.legs) {
          const swing = Math.sin(this.walkPhase + (running ? leg.phaseRun : leg.phaseWalk)) * 0.45;
          leg.bone.quaternion.setFromAxisAngle(leg.axis, swing).multiply(leg.bindQuat);
        }
        if (inst) {
          inst.position.y = this.groundY + Math.abs(Math.sin(this.walkPhase)) * this.height * 0.02;
          inst.scale.setScalar(this.baseScale);
        }
      } else {
        for (const leg of this.legs) leg.bone.quaternion.copy(leg.bindQuat);   // Ruhelage
        this.idlePhase += dt * 1.6;
        if (inst) {
          inst.position.y = this.groundY + Math.sin(this.idlePhase) * 0.012;
          inst.scale.setScalar(this.baseScale * (1 + Math.sin(this.idlePhase * 0.5) * 0.006));
        }
      }
    }
    // kürzesten Drehweg nehmen
    let d = this.targetYaw - this.root.rotation.y;
    while (d > Math.PI) d -= Math.PI * 2;
    while (d < -Math.PI) d += Math.PI * 2;
    this.root.rotation.y += d * Math.min(1, dt * 10);
    this.mixer.update(dt);
  }
}
