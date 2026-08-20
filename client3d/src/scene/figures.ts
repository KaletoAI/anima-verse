import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import * as SkeletonUtils from 'three/addons/utils/SkeletonUtils.js';
import { seededRandom } from './textures';
import { animatablePool, missingClipKinds, resolveClipName } from './clipCoverage';
import { clipGroundOffset, measureGroundOffsets } from './clipGround';
import type { ApiModel } from '../api';
import { getAnimationClips, getCharacterModel } from '../api';

/**
 * Animierte 3D-Figuren für NPCs (AV3D-5): Modelle kommen vom Server
 * (GET /characters/{name}/model3d), /models/manifest.json ist nur noch
 * Dev-/Offline-Fallback. Die Fallback-Kette (Figur -> Portrait-Sprite)
 * bleibt dieselbe.
 */

/** Base height of a figure without `height_cm`, in REAL metres — and since E4
 *  in world metres too: k = 1, so a figure is this tall on the map and in a
 *  room alike (contract schnittstellen-3d.md § A3; the payload's
 *  `figures.base_height_m_world` is the same 1.70). Only `setCharacterHeight`
 *  scales a figure at all. Do NOT put it back to 1.75: the admin preview and
 *  the prop/diorama scales are all worked out against 1.70. */
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

/** Auflösungs-Stufe eines Server-Modells (Vertragswerte von ?tier=). */
export type FigureTier = 'full' | 'low';

interface LoadedModel {
  name: string;
  template: THREE.Group;
  clips: THREE.AnimationClip[];
  scale: number;
  height: number; // Welthöhe nach Skalierung
  assignOnly: boolean;
  noClips: boolean;
  /** Stufe, mit der das Modell geladen wurde (Manifest-Modelle: full). */
  tier: FigureTier;
  /** true = the shared clip library reached this skeleton (at least one
   *  library clip survived `adaptExternalClips`). false also when no library
   *  was loaded at all — see `animatablePool`. */
  libraryFits: boolean;
}

/** What fitting the clip library to ONE rig produced. */
interface LibraryFit {
  /** adapted clips for kinds the model does not carry itself */
  extra: THREE.AnimationClip[];
  /** true = the library reached this skeleton at all */
  fits: boolean;
}

/** How many keyframe tracks a clip has to keep to be worth playing. Below
 *  that, so few bones of the target were addressed that the result is a twitch
 *  rather than a motion — the same bar in the adapt and the retarget path. */
const MIN_CLIP_TRACKS = 8;

/** A bone / track node name reduced to what is comparable across rigs: the
 *  `mixamorig` prefix and any namespace colons are noise, case is not
 *  significant. */
function normBoneName(name: string): string {
  return name.replace(/^mixamorig:?/i, '').replace(/:/g, '').toLowerCase();
}

/**
 * How far a rig's bind pose may sit from the library's bone-frame convention
 * before its clips are worthless on it — mean deviation over the addressed
 * bones, in degrees.
 *
 * `adaptExternalClips` copies LOCAL quaternion tracks 1:1, which is only ever
 * right while donor and target hold their bones in the same rest frame. The
 * Mixamo library was authored with every bone pointing at its child along the
 * bone's own +Y. A rig with identity rest rotations instead carries
 * world-parallel frames (legs down −Y, arms out +X), so the same track that
 * bends a Mixamo elbow folds that rig's limb over its torso — and nothing
 * downstream notices, because acceptance counts TRACK HITS by name only.
 *
 * Measured (acceptance round 2026-08-13, finding 7): Xbot.glb 95.6° mean /
 * 179.6° max, Soldier.glb 8.3° / 37.4°, eight server-generated character
 * models 1.3–1.7° / 7.0°. The threshold sits well above every rig that works
 * and well below the one that does not; the gap is a factor of ten, so the
 * exact value is not delicate.
 */
export const MAX_REST_FRAME_DEV_DEG = 30;
/** Drift (clip seconds) between the local mixer and the server's game-clock
 *  position of a pair clip beyond which the action is re-seeked. */
export const PAIR_RESYNC_S = 0.2;

/** The convention the shared clip library was authored in: a bone's child sits
 *  on that bone's own +Y axis. */
const DONOR_CHILD_AXIS = new THREE.Vector3(0, 1, 0);

/**
 * How far this skeleton's REST pose sits from the donor convention above:
 * for every bone the clips actually address, the angle between the direction
 * to its first bone child (expressed in the bone's OWN frame — that is exactly
 * `child.position`) and +Y.
 *
 * Bind pose only, one pass over the bones, no frame sampling: the numbers come
 * out of the rest transforms the loader already built, so this costs nothing
 * next to adapting the clips themselves.
 *
 * `bones` is how many bones carried the measurement; with none of them the
 * verdict is 0 (nothing measurable is not a defect — such a rig fails the
 * track count anyway).
 *
 * Exported for `client3d/scripts/smoke_clip_ground.mjs`: the red probe has to
 * walk the real chain rather than a copy of it.
 */
export function restFrameDeviation(
  clips: readonly THREE.AnimationClip[], target: THREE.Object3D
): { mean: number; max: number; bones: number } {
  const addressed = new Set<string>();
  for (const clip of clips) {
    for (const track of clip.tracks) {
      const dot = track.name.lastIndexOf('.');
      if (dot > 0) addressed.add(normBoneName(track.name.slice(0, dot)));
    }
  }
  const dir = new THREE.Vector3();
  let sum = 0;
  let max = 0;
  let bones = 0;
  target.traverse((o) => {
    if (!(o as THREE.Bone).isBone || !addressed.has(normBoneName(o.name))) return;
    const child = o.children.find((c) => (c as THREE.Bone).isBone);
    if (!child) return;   // end bone (fingertips, toes): no direction to read
    dir.copy(child.position);
    if (dir.lengthSq() < 1e-12) return;   // child sitting on its parent says nothing
    const deg = THREE.MathUtils.radToDeg(dir.normalize().angleTo(DONOR_CHILD_AXIS));
    sum += deg;
    if (deg > max) max = deg;
    bones += 1;
  });
  return { mean: bones ? sum / bones : 0, max, bones };
}

/** How many of the bones the clips address exist on this skeleton — the count
 *  that decides whether a clip survives `adaptExternalClips`, and the one
 *  number that makes "no clip fits" diagnosable from the console. */
function boneOverlap(clips: readonly THREE.AnimationClip[], target: THREE.Object3D): { matched: number; total: number } {
  const bones = new Set<string>();
  target.traverse((o) => {
    if ((o as THREE.Bone).isBone) bones.add(normBoneName(o.name));
  });
  const nodes = new Set<string>();
  for (const clip of clips) {
    for (const track of clip.tracks) {
      const dot = track.name.lastIndexOf('.');
      if (dot > 0) nodes.add(normBoneName(track.name.slice(0, dot)));
    }
  }
  let matched = 0;
  for (const node of nodes) if (bones.has(node)) matched += 1;
  return { matched, total: nodes.size };
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
    if (tracks.length >= MIN_CLIP_TRACKS) out.push(new THREE.AnimationClip(clip.name, clip.duration, tracks));
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
 *
 * Exported for `client3d/scripts/smoke_clip_ground.mjs` alone: the clip ground
 * offset is measured on the clips THIS produces, so the check has to walk the
 * real chain rather than a copy of it.
 */
export function adaptExternalClips(clips: THREE.AnimationClip[], target: THREE.Object3D): THREE.AnimationClip[] {
  const boneByKey = new Map<string, THREE.Bone>();
  target.traverse((o) => {
    if ((o as THREE.Bone).isBone) boneByKey.set(normBoneName(o.name), o as THREE.Bone);
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
  // Steh-Referenz der Quelle. Früher: MAXIMALE Hüfthöhe über ALLE Clips —
  // ein EINZELNER falsch skalierter Clip wurde damit zur Referenz und
  // drückte JEDE Figur in den Boden (Befund 2026-07-26: taking-fotos.fbx
  // mit Hüfte ~211 statt ~110 → alle NPCs ~0,47 m tief, überall).
  // Jetzt: pro Clip die MEDIAN-Hüfthöhe messen; Referenz = größter
  // Clip-Median, den mindestens ein zweiter Clip zu 70 % bestätigt
  // (Sitz-/Liege-Clips bleiben legitim darunter und senken die Hüfte wie
  // gewollt). Ein Clip ÜBER dem 1,5-fachen der Referenz ist ein
  // Export-Maßstabsfehler und wird selbst auf die Referenz zurückskaliert.
  const hipMedian = (clip: THREE.AnimationClip): number => {
    const ys: number[] = [];
    for (const track of clip.tracks) {
      if (track.name.endsWith('.position') && /hips\./i.test(track.name.replace(/^mixamorig:?/i, ''))) {
        for (let i = 1; i < track.values.length; i += 3) ys.push(Math.abs(track.values[i]));
      }
    }
    ys.sort((a, b) => a - b);
    return ys.length ? ys[Math.floor(ys.length / 2)] : 0;
  };
  const medians = new Map<THREE.AnimationClip, number>(
    clips.map((c) => [c, hipMedian(c)] as [THREE.AnimationClip, number]));
  const sorted = [...medians.values()].filter((m) => m > 1e-6).sort((a, b) => b - a);
  // Obergrenze (cap) = größter Wert, den ein zweiter Clip zu 70 % bestätigt;
  // Referenz = Median des STEH-Clusters [0,7 × cap .. cap] — so bestimmt
  // weder ein Maßstabs-Ausreißer (211) noch ein einzelner hoher Clip (sleep
  // 119,5) die Stehhöhe, sondern die dichte Idle/Walk-Gruppe (~110).
  let cap = sorted[0] || 0;
  for (let i = 0; i < sorted.length; i++) {
    if (sorted.length === 1 || (sorted[i + 1] !== undefined && sorted[i + 1] >= sorted[i] * 0.7)) {
      cap = sorted[i];
      break;
    }
  }
  const cluster = sorted.filter((m) => m >= cap * 0.7 && m <= cap).sort((a, b) => a - b);
  const sourceRest = cluster.length
    ? cluster[Math.floor(cluster.length / 2)]
    : (sorted[0] || 0);
  // Maßstabs-Heilung pro Clip: |y|-Werte eines Ausreißers vor der
  // Bounce-Rechnung auf die Referenz normieren.
  const scaleFixOf = (clip: THREE.AnimationClip): number => {
    const m = medians.get(clip) || 0;
    return sourceRest > 1e-6 && m > sourceRest * 1.5 ? sourceRest / m : 1;
  };
  const out: THREE.AnimationClip[] = [];
  for (const clip of clips) {
    const tracks: THREE.KeyframeTrack[] = [];
    for (const track of clip.tracks) {
      const dot = track.name.lastIndexOf('.');
      const node = track.name.slice(0, dot);
      const prop = track.name.slice(dot + 1);
      const bone = boneByKey.get(normBoneName(node));
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
        const scaleFix = scaleFixOf(clip);
        const rest = hips.position;
        const vals = new Float32Array(track.values.length);
        for (let i = 0; i < track.values.length; i += 3) {
          const bounce = (Math.abs(track.values[i + 1]) * scaleFix - sourceRest) * k; // Welt-Delta in m
          v.set(0, bounce, 0).applyMatrix4(hipsPosMatrix); // in Eltern-Raum (Richtung+Skala)
          v.sub(new THREE.Vector3().setFromMatrixPosition(hipsPosMatrix!)); // nur Richtungsanteil
          v.add(rest);
          v.toArray(vals, i);
        }
        tracks.push(new THREE.VectorKeyframeTrack(`${bone.name}.position`, [...track.times], [...vals]));
      }
    }
    if (tracks.length >= MIN_CLIP_TRACKS) out.push(new THREE.AnimationClip(clip.name, clip.duration, tracks));
  }
  return out;
}

/** `<kind>__a` / `<kind>__b` — the half of a pair clip (contract § A8a). */
export function isPairClipName(name: string): boolean {
  return /__[ab]$/.test(name);
}

/** The horizontal root path of a clip: hips XZ per keyframe in METRES of the
 *  clip's own frame (Mixamo clips are authored in centimetres). */
export interface RootPath {
  times: Float32Array;
  /** x0, z0, x1, z1, … */
  xz: Float32Array;
}

export function extractRootPath(clip: THREE.AnimationClip): RootPath {
  const track = clip.tracks.find((t) => t.name.endsWith('.position')
    && /hips\./i.test(t.name.replace(/^mixamorig:?/i, '')));
  if (!track) return { times: new Float32Array([0]), xz: new Float32Array([0, 0]) };
  const n = track.times.length;
  const xz = new Float32Array(n * 2);
  for (let i = 0; i < n; i++) {
    xz[i * 2] = track.values[i * 3] / 100;
    xz[i * 2 + 1] = track.values[i * 3 + 2] / 100;
  }
  return { times: Float32Array.from(track.times), xz };
}

/** Root XZ at clip time `t` (linear between keys, clamped at both ends). */
export function rootPathAt(path: RootPath, t: number): { x: number; z: number } {
  const { times, xz } = path;
  const n = times.length;
  if (n === 0) return { x: 0, z: 0 };
  if (t <= times[0]) return { x: xz[0], z: xz[1] };
  if (t >= times[n - 1]) return { x: xz[(n - 1) * 2], z: xz[(n - 1) * 2 + 1] };
  let lo = 0;
  let hi = n - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (times[mid] <= t) lo = mid; else hi = mid;
  }
  const span = times[hi] - times[lo] || 1;
  const f = (t - times[lo]) / span;
  return {
    x: xz[lo * 2] + (xz[hi * 2] - xz[lo * 2]) * f,
    z: xz[lo * 2 + 1] + (xz[hi * 2 + 1] - xz[lo * 2 + 1]) * f,
  };
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

/** Stand-in clip when the wanted one is missing (before falling back to idle):
 *  someone lying down should at least sit, a runner walk fast — and a swimmer
 *  walk, because the terrain clips (`move_anim`/`idle_anim`, § A9) name kinds
 *  out of an OPEN vocabulary that not every model carries. A model without
 *  `treading-water` simply stands in the lake, which is where it stood before
 *  the key existed — no break, just no water. */
const CLIP_FALLBACK: Record<string, ClipKind> = {
  lie: 'sit',
  run: 'walk',
  swim: 'walk',
  // A clip kind is the whole file name since 2026-08-13, so `swim-idle` is a
  // kind of its own — and the nearest thing to it on a rig without it is the
  // swimming stroke, not standing.
  'swim-idle': 'swim',
  'treading-water': 'idle',
};

/** Modelle, deren gebundene Kinds schon geloggt wurden (einmal je Modell,
 *  nicht je NPC-Instanz). */
const loggedActionKinds = new Set<string>();


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
  /** Gewünschte Auflösungs-Stufe je Charakter (view state, Default full). */
  private tierWanted = new Map<string, FigureTier>();
  /** Bereits geladene Stufen je Charakter — Rückwechsel ist damit sofort. */
  private tierCache = new Map<string, Map<FigureTier, LoadedModel>>();
  /** Server-Clips: kind -> (set|'' -> Clip) */
  private clipIndex = new Map<string, Map<string, THREE.AnimationClip>>();
  /** Root path of every pair-clip half (`<kind>__<role>`), clip-frame metres */
  private pairRoots = new Map<string, RootPath>();
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
        // Static meshes (no skeleton, no clips) are allowed too — an interim
        // state until a rigged model exists; such figures glide without a
        // walk animation.
        console.info(`[figures] ${m.name}: rawHeight=${rawHeight.toFixed(3)} -> scale=${(height / rawHeight).toFixed(3)}, clips=${usable.length}, bones=${boneNames(template).size}`);
        return { name: m.name, template, clips: usable, scale: height / rawHeight, height, assignOnly: !!m.assignOnly, noClips: !!m.noClips, tier: 'full' as FigureTier, libraryFits: false };
      })
    );
    for (const r of results) {
      if (r.status === 'fulfilled') this.models.push(r.value);
      else console.warn('[figures]', r.reason);
    }

    // Where the clips come from: the server's global library (AV3D-5) by
    // preference, the local manifest clips otherwise (dev/offline). What is
    // done with them is the loop below — every rig gets the kinds it does not
    // carry itself, and a rig the library does not fit borrows from another
    // model (bone names rewritten, mixamorig prefix mapping).
    const serverClips = await getAnimationClips();
    // A PAIR clip's half is indexed under `<kind>__<role>` (§ A8a) — the name
    // an interaction asks for; a solo clip keeps its plain kind.
    const sources: Array<{ kind: string; set: string; url: string }> = serverClips.map((c) => ({
      kind: c.role ? `${c.kind}__${c.role}` : c.kind, set: c.set ?? '', url: c.url,
    }));
    if (!sources.length) {
      // Dev/offline fallback: the local manifest clips (no sets)
      for (const [kind, url] of Object.entries(manifest.clipFiles ?? {})) sources.push({ kind, set: '', url });
    } else {
      const desc = sources.map((s) => s.set ? `${s.kind}/${s.set}` : s.kind).join(', ');
      console.info(`[figures] ${sources.length} clips from the server: ${desc}`);
    }
    for (const { kind, set, url } of sources) {
      try {
        const { animations } = await loadFile(url);
        if (!animations[0]) continue;
        const clip = animations[0].clone();
        clip.name = kind;
        // The half of a pair clip carries ROOT MOTION inside the anchor frame
        // (the handshake's approach, the dance's travel). `adaptExternalClips`
        // strips the horizontal hips motion like for every clip, so the root
        // path is kept aside here and drives the figure's ROOT instead — in
        // true world metres, independent of the figure's own scale.
        if (isPairClipName(kind)) this.pairRoots.set(kind, extractRootPath(clip));
        if (!this.clipIndex.has(kind)) this.clipIndex.set(kind, new Map());
        const bySet = this.clipIndex.get(kind)!;
        if (!bySet.has(set)) bySet.set(set, clip);   // first hit per kind+set
      } catch (e) {
        console.warn('[figures] clip not loadable:', url, e);
      }
    }
    this.defaultHeight = defaultHeight;
    this.loadFile = loadFile;

    const donor = this.models.find((m) => m.clips.length > 0);
    for (const m of this.models) {
      if (m.noClips || !boneNames(m.template).size) continue;
      // PER KIND, not all-or-nothing: a fallback rig that ships walk/idle/run
      // (Soldier, Xbot, Robot) keeps those and takes swim, yoga and the rest
      // of the library on top. Its own clips win for their own kinds.
      const fit = this.fitLibrary(m.name, m.template, m.clips);
      m.libraryFits = fit.fits;
      if (fit.extra.length) {
        const kinds = fit.extra.map((c) => c.name).sort().join(', ');
        console.info(`[figures] ${m.name}: ${fit.extra.length} clip kinds added`
          + ` from the library — ${kinds}`);
        m.clips = [...m.clips, ...fit.extra];
      }
      if (m.clips.length) continue;
      // Neither its own clips nor a library that fits this skeleton: borrow
      // from the first model that HAS clips and retarget bone by bone.
      if (!donor) continue;
      m.clips = retargetClips(m.template, donor.template, donor.clips);
      if (!m.clips.length) console.warn(`[figures] ${m.name}: clip retargeting failed`);
      else console.info(`[figures] ${m.name}: ${m.clips.length} clips retargeted from ${donor.name}`);
    }
    return true;   // server models may still arrive later (fetchCharacterModel)
  }

  private loadFile!: (url: string, forceFbx?: boolean) => Promise<{ scene: THREE.Group; animations: THREE.AnimationClip[] }>;

  /** Root XZ of a pair-clip half at clip time `t`, in clip-frame metres —
   *  null when no such clip is loaded. */
  pairRootAt(clipName: string, t: number): { x: number; z: number } | null {
    const path = this.pairRoots.get(clipName);
    return path ? rootPathAt(path, t) : null;
  }

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
    this.tierCache.delete(charName);   // beide Stufen gehören zum alten Mesh
    this.fetchCharacterModel(charName);
    return true;
  }

  /** Gewünschte Distanz-Stufe einer Figur setzen (view state — WANN full/low
   *  gilt, entscheidet der Aufrufer; die Hysterese steckt in dessen Bändern).
   *  Aktiviert sofort aus dem Stufen-Cache oder lädt die fehlende Stufe nach;
   *  bis dahin bleibt die stehende Figur unverändert sichtbar. */
  setFigureTier(charName: string, tier: FigureTier) {
    if ((this.tierWanted.get(charName) ?? 'full') === tier) return;
    this.tierWanted.set(charName, tier);
    this.syncTier(charName);
  }

  /** Aktives Modell auf die gewünschte Stufe bringen: Cache-Treffer sofort,
   *  sonst EIN Nachladelauf; danach erneut prüfen (der Wunsch kann sich
   *  während des Ladens geändert haben). Ein Ladefehler gibt auf — der
   *  nächste Stufen-Wechsel versucht es wieder. */
  private syncTier(charName: string) {
    const want = this.tierWanted.get(charName) ?? 'full';
    const active = this.apiModels.get(charName);
    if (!active || active.tier === want || this.pending.has(charName)) return;
    const cached = this.tierCache.get(charName)?.get(want);
    if (cached) {
      this.apiModels.set(charName, cached);
      this.onModelReady?.(charName);
      return;
    }
    this.pending.add(charName);
    void (async () => {
      let built = false;
      try {
        const info = await getCharacterModel(charName);
        if (info) {
          const model = await this.buildModel(charName, info, want);
          this.cacheTier(charName, model);
          built = true;
        }
      } catch (e) {
        console.warn(`[figures] ${charName}: ${want}-Stufe nicht ladbar`, e);
      } finally {
        this.pending.delete(charName);
      }
      if (built) this.syncTier(charName);
    })();
  }

  private cacheTier(charName: string, model: LoadedModel) {
    let byTier = this.tierCache.get(charName);
    if (!byTier) {
      byTier = new Map();
      this.tierCache.set(charName, byTier);
    }
    byTier.set(model.tier, model);
  }

  /** Körpergröße eines Charakters merken (cm -> m); wirkt beim nächsten Bau. */
  setCharacterHeight(charName: string, heightCm: number | undefined) {
    if (heightCm && heightCm > 30 && heightCm < 400) this.charHeight.set(charName, heightCm / 100);
  }

  /**
   * The server's clip library, fitted to ONE rig and reduced to the kinds
   * that rig does not already carry — the per-kind MERGE (swim finding
   * 2026-08-13).
   *
   * It used to be all or nothing on both sides: a model with ANY embedded
   * clip never saw the library, so the three manifest fallback rigs and every
   * server model that ships a single clip could play walk and idle and
   * nothing else. `move_anim: "swim"` then fell through `CLIP_FALLBACK` to
   * walk and the lake looked like a meadow. Per kind: an embedded clip WINS
   * for its own kind (it was authored for this mesh), the library fills the
   * rest.
   *
   * The whole library goes through `adaptExternalClips` and the filter runs
   * AFTER it, deliberately: that function derives its standing reference from
   * the hip heights ACROSS the clips it is given, so handing it a subset
   * would rescale the survivors against a different yardstick.
   *
   * The KIND of a clip is its lowercased name — the same key `Figure` binds
   * its actions under, and the library sets `clip.name = kind` itself.
   *
   * Every kind the library offered and this rig still cannot play is NAMED in
   * one console.warn, with the bone overlap behind it. Silence was the actual
   * bug in the acceptance round of 2026-08-13: the fallback rig
   * RobotExpressive has Blender bone names (Hips, Abdomen, UpperArm.L), the
   * library is Mixamo-named, three bones match — every library clip fell under
   * the track threshold and vanished without a word, so `swim` looked like a
   * rule failure and was a skeleton mismatch.
   *
   * Matching bone NAMES is not enough, though (finding 7 of the same round):
   * Xbot.glb answers to every Mixamo name and reports 23 of 23 clips fitted —
   * and swims with its limbs folded over its torso, because its bones rest in
   * world-parallel frames while the library's rotation tracks assume Mixamo
   * ones. So the bind pose is measured against that convention BEFORE the
   * clips are adapted: over the limit, the library does not fit this skeleton
   * and none of it is bound. Adapting first and dropping afterwards would be
   * the same verdict at a higher price.
   *
   * PARKED, not built: such a rig could have the library back for real by
   * going through `retargetClips` instead, which works over WORLD directions
   * and does not care about bone frames — today that path is only reachable
   * for models without any clips of their own.
   */
  private fitLibrary(charName: string, template: THREE.Object3D,
                     own: readonly THREE.AnimationClip[]
  ): LibraryFit {
    const candidates = this.clipsFor(charName);
    if (!candidates.length) return { extra: [], fits: false };
    const dev = restFrameDeviation(candidates, template);
    if (dev.mean > MAX_REST_FRAME_DEV_DEG) {
      console.warn(`[figures] ${charName}: the clip library does NOT fit this`
        + ` skeleton — its bind pose sits ${dev.mean.toFixed(1)}° off the`
        + ` library's bone convention (mean over ${dev.bones} addressed bones,`
        + ` max ${dev.max.toFixed(1)}°, limit ${MAX_REST_FRAME_DEV_DEG}°).`
        + ` Copied rotation tracks would fold the limbs over the torso, so no`
        + ` library clip is bound and this rig stays out of the random pool.`);
      return { extra: [], fits: false };
    }
    const adapted = adaptExternalClips(candidates, template);
    const have = new Set(own.map((c) => c.name.toLowerCase()));
    const missing = missingClipKinds(
      candidates.map((c) => c.name),
      [...have, ...adapted.map((c) => c.name)],
    );
    if (missing.length) {
      const { matched, total } = boneOverlap(candidates, template);
      console.warn(`[figures] ${charName}: ${missing.length} of ${candidates.length}`
        + ` library clip kinds NOT bound — ${missing.join(', ')}`
        + ` (${matched} of ${total} clip bones exist on this skeleton;`
        + ` a clip needs ${MIN_CLIP_TRACKS} usable tracks to survive)`);
    }
    const extra = adapted.filter((c) => !have.has(c.name.toLowerCase()));
    // WHERE each of these clips puts the body over the ground, measured once
    // per rig (`clipGround`, finding 3 of 2026-08-13). Pure data: what it is
    // good for is decided in `Figure.play`, and only while a terrain move clip
    // runs. Measured AFTER the filter — a clip this rig will never play costs
    // no skinning samples.
    measureGroundOffsets(extra, template);
    const floats = extra.filter((c) => clipGroundOffset(c) > 0.05)
      .map((c) => `${c.name} +${clipGroundOffset(c).toFixed(2)} m`);
    if (floats.length) {
      console.info(`[figures] ${charName}: clips authored off the floor —`
        + ` ${floats.join(', ')} (dropped while walking that ground)`);
    }
    return { extra, fits: adapted.length > 0 };
  }

  /** Pick the clips for a character along its set chain:
   *  <kind>_<set1> → <kind>_<set2> → … → <kind> (no set). */
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
        const tier = this.tierWanted.get(charName) ?? 'full';
        const model = await this.buildModel(charName, info, tier);
        this.cacheTier(charName, model);
        this.apiModels.set(charName, model);
        if (info.signature) this.apiSignature.set(charName, info.signature);
        console.info(`[figures] ${charName}: Modell vom Server (${info.format}/${info.rig}/${tier}, ${model.clips.length} Clips, ${(model.height * 100).toFixed(0)} cm)`);
        this.onModelReady?.(charName);
      } catch (e) {
        // Transienter Fehler (Netzwerk, 5xx, Textur): nicht als "hat keins"
        // cachen, sondern später erneut versuchen.
        console.warn(`[figures] ${charName}: Modell nicht ladbar — neuer Versuch in 30 s`, e);
        window.setTimeout(() => this.fetchCharacterModel(charName), 30_000);
      } finally {
        this.pending.delete(charName);
        this.syncTier(charName);   // Wunsch kann sich beim Laden geändert haben
      }
    })();
  }

  /** Load, upright and normalise a model; library clips only on a Mixamo rig.
   *  FBX models (generic/animals) get their texture separately.
   *  `tier=low` asks for the distance edition — where it does not (yet) exist
   *  the server serves the full mesh under the same tier. */
  private async buildModel(name: string, info: ApiModel, tier: FigureTier = 'full'): Promise<LoadedModel> {
    const url = tier === 'low' ? `${info.url}?tier=low` : info.url;
    const gltf = await this.loadFile(url, info.format === 'fbx');
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
    // Charaktere sind DIELEKTRIKA: Metalness hart auf 0 (AV3D-14).
    // Das Gateway bettet seit Rosi auch bei Humanoiden eine
    // Metal-Roughness-Textur ein, deren B-Kanal ~0,5 Metalness über den
    // ganzen Körper behauptet — auf Haut und Stoff physikalisch Unsinn; dazu
    // ist `metallicFactor` oft unbelegt, und der glTF-Default ist 1,0. Ohne
    // Korrektur rendert der Körper ohne Env-Map falsch (Rosi grünstichig).
    // Bewusst KEINE Env-Map-Lösung wie bei Gebäuden/Props: ein halb-
    // metallischer Körper ist auch mit Env-Map falsch. metalness = 0 macht
    // die metalnessMap multiplikativ tot; die ROUGHNESS aus dem G-Kanal
    // derselben Textur bleibt aktiv und ist erwünscht — deshalb wird
    // `roughness` NICHT angetastet.
    const matLog: string[] = [];
    template.traverse((o) => {
      const mesh = o as THREE.Mesh;
      if (!mesh.isMesh) return;
      for (const m of Array.isArray(mesh.material) ? mesh.material : [mesh.material]) {
        const std = m as THREE.MeshStandardMaterial;
        if (!std.isMeshStandardMaterial) continue;
        const before = std.metalness;
        const mr = std.metalnessMap ? 'MR-Map' : 'ohne MR-Map';
        if (before !== 0) {
          std.metalness = 0;
          std.needsUpdate = true;
        }
        matLog.push(`metalness ${before}->${std.metalness} (${mr}, roughness ${std.roughness}`
          + `${std.roughnessMap ? ' + Map' : ''})`);
      }
    });
    if (matLog.length) console.info(`[figures] ${name}: ${matLog.join(' | ')}`);

    const b = new THREE.Box3().setFromObject(template);
    const s = b.getSize(new THREE.Vector3());
    if (s.z > s.y * 1.5) {                       // Z-up-Export aufrichten
      template.rotation.x = -Math.PI / 2;
      template.updateMatrixWorld(true);
    }
    const bbox = new THREE.Box3().setFromObject(template);
    const rawHeight = Math.max(bbox.max.y - bbox.min.y, 0.01);
    // A server-normalised file already stands its real height on the ground;
    // rescaling it by the box would shrink a figure by its hair/hat again
    // (the crown-joint basis puts those ABOVE the target height on purpose).
    // Legacy models keep the runtime measure until they are re-generated.
    const height = this.charHeight.get(name) ?? this.defaultHeight;
    const scale = info.normalized ? 1 : height / rawHeight;
    const model: LoadedModel = {
      name, template,
      clips: gltf.animations.filter((c) => c.tracks.length > 0),
      scale, height: rawHeight * scale, assignOnly: true, noClips: false, tier,
      libraryFits: false,
    };
    // Clips along the character's set chain (female/male/animal/custom),
    // merged PER KIND: a clip embedded in the mesh wins for its own kind, the
    // library fills every kind the model does not carry (swim finding
    // 2026-08-13 — a single embedded clip used to lock the whole library out).
    // "generic" rigs (own skeletons) stay clip-less -> procedural idle.
    if (info.rig !== 'generic' && boneNames(template).size) {
      const fit = this.fitLibrary(name, template, model.clips);
      model.libraryFits = fit.fits;
      if (fit.extra.length) model.clips = [...model.clips, ...fit.extra];
    }
    return model;
  }

  /** Model choice: server model > manifest assignment > pool (demo world). */
  instantiate(charName: string): Figure | null {
    const api = this.apiModels.get(charName);
    if (api) return new Figure(api);
    if (api === undefined) this.fetchCharacterModel(charName);   // kick off the load
    // api === null (the server has none) or not loaded yet: on to the manifest
    // assignment/pool — the portrait fallback is the last resort.
    if (!this.models.length) return null;
    const assigned = this.assignments[charName] ?? charName;
    let model = this.models.find((m) => m.name === assigned);
    if (!model) {
      // Only rigs the clip library reaches are drawn at random (see
      // `animatablePool`): a Blender-named fallback rig can play its own
      // handful of embedded kinds and NOTHING else, so a character on water
      // would walk across the lake instead of swimming. An explicit
      // `assignments` entry still wins above — that is a deliberate choice.
      const pool = animatablePool(this.models.filter((m) => !m.assignOnly));
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
  /** Extra drop currently applied on top of `groundY`, in WORLD metres — the
   *  ground offset of the clip playing right now (`clipGround`, finding 3).
   *  0 for everything but a clip the GROUND named (move or idle). */
  private clipDrop = 0;
  /** Whether the clip playing right now was named by the GROUND
   *  (`walk.moveClip` / `walk.idleClip`) — part of the play state, because the
   *  same kind can be asked for both by the terrain and as a plain activity. */
  private terrainClip = false;
  /** How deep the GROUND under the figure swallows it while such a clip runs,
   *  in world metres — the depth the CALLER picked for the current state
   *  (`walk.sinkForState`, move or idle). Part of the play state for the same
   *  reason `terrainClip` is: walking from a ford into a lake changes nothing
   *  but this number, and the figure still has to sink — and so does stopping
   *  in the same lake, where the swimmer's depth gives way to the treader's. */
  private sink = 0;

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
    // Offenes Clip-Vokabular (Vertrag § A8): JEDES geladene Kind bekommt eine
    // Action unter seinem EIGENEN Namen. Vorher wurden nur die sieben
    // hartkodierten CLIP_SYNONYMS-Kinds gebunden — alle anderen Server-Kinds
    // (bartending, harvesting, situps, treading, plant, send, taking …) lagen
    // in model.clips, waren aber nie abspielbar und fielen still auf idle.
    // Die Clip-Namen SIND die Server-Kinds (FigureLibrary.load setzt
    // clip.name = kind, das Retargeting behält den Namen).
    const byName = new Map(model.clips.map((c) => [c.name.toLowerCase(), c]));
    for (const [kind, clip] of byName) {
      if (kind) this.actions.set(kind, this.mixer.clipAction(clip));
    }
    // The synonym table stays the ALIAS layer: a canonical kind no clip
    // carries literally is bound through its synonyms (the server delivers
    // "laying"/"sleep", "lie" is meant as well). Which clip stands in is
    // `resolveClipName` — EXACT before substring, so a needle never steals a
    // longer kind that only contains it (`swim` vs `swim-idle`, 2026-08-13).
    for (const [kind, needles] of Object.entries(CLIP_SYNONYMS) as [ClipKind, string[]][]) {
      if (this.actions.has(kind)) continue;
      const name = resolveClipName([...byName.keys()], needles);
      const clip = name ? byName.get(name) : undefined;
      if (clip) this.actions.set(kind, this.mixer.clipAction(clip));
    }
    // Einmal je Modell die gebundenen Kinds nennen — das ist der Nachweis,
    // dass das Vokabular offen ist (Abnahme A4).
    if (!loggedActionKinds.has(model.name)) {
      loggedActionKinds.add(model.name);
      console.info(`[figures] ${model.name}: ${this.actions.size} Kinds gebunden — `
        + `${[...this.actions.keys()].sort().join(', ')}`);
    }
    // Clip-lose Rigs (UniRig-Tiere): Beinketten für den prozeduralen Gang
    if (this.actions.size === 0 && !box.isEmpty()) {
      this.legs = findLegChains(inst, box);
      if (this.legs.length) console.info(`[figures] prozeduraler Gang: ${this.legs.length} Beinketten erkannt`);
    }
    this.play('idle');
  }

  /** Clip mit Crossfade wechseln; fehlt der Clip: Ersatz-Clip, dann idle.
   *  `kind` kommt server-authoritativ aus `activity_animation` — deshalb hier
   *  normalisieren, die Actions liegen unter kleingeschriebenen Kinds.
   *
   *  `terrainClip` says the kind comes from the GROUND the figure is on
   *  (`walk.moveClip` while it moves, `walk.idleClip` while it stands) — the
   *  state in which the ground is the body's reference, so a clip authored off
   *  the floor is dropped onto it (finding 3 of 2026-08-13: `swim` is animated
   *  on a water line and the swimmer floated a third of a metre over the lake;
   *  `treading-water` is authored the same way). An ordinary standing clip
   *  keeps its authored height on purpose — `sleep` carries the bed it was
   *  animated on.
   *
   *  `sink` is how deep that GROUND swallows the body (§ A9, in world metres)
   *  and rides the SAME gate: the normalisation above puts the lowest body
   *  point ON the surface, and for a swimmer that point is a bent knee — so
   *  the ground adds what belongs underneath it. It is NOT scaled with the
   *  figure: half a metre of water is half a metre for a child and for a
   *  giant. WHICH depth this is — the ground's move or its idle one — is the
   *  caller's decision (`walk.sinkForState`); the two are different numbers
   *  because a swimmer lies flat and a treader hangs upright. */
  play(rawKind: ClipKind, terrainClip = false, sink = 0) {
    const kind = (rawKind || 'idle').toLowerCase();
    // Junk is no depth, and never NaN: one NaN in the drop and the figure
    // hangs at no height for the rest of the session.
    const sinkM = terrainClip && Number.isFinite(sink) && sink > 0 ? sink : 0;
    if (this.currentKind === kind && this.terrainClip === terrainClip
        && this.sink === sinkM) return;
    this.terrainClip = terrainClip;
    this.sink = sinkM;
    const fallback = CLIP_FALLBACK[kind];
    const resolved = this.actions.get(kind)
      ?? (fallback ? this.actions.get(fallback) : undefined)
      ?? this.actions.get('idle')
      ?? [...this.actions.values()][0];
    // Beobachtbar machen, WELCHES Kind gewünscht war und ob es überhaupt
    // gebunden ist — ohne das ist von außen nicht unterscheidbar, ob ein Kind
    // gespielt oder still auf idle zurückgefallen ist (Abnahme A4).
    this.root.userData.clipKind = kind;
    this.root.userData.clipBound = this.actions.has(kind);
    // The drop belongs to the clip that ACTUALLY plays, not to the kind that
    // was asked for: a rig without `swim` falls back to `walk` and then walks
    // on the ground, which is where a walk clip already is (offset 0). The
    // ground's sink depth comes on top of that measurement, in world metres.
    this.setClipDrop(terrainClip && resolved
      ? clipGroundOffset(resolved.getClip()) * this.baseScale + sinkM : 0);
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

  /** Put the instance at `groundY − drop`. The anchor itself stays what the
   *  bind pose made it; only this ONE extra term moves, and it goes back to 0
   *  the moment the terrain move ends. Static rigs never get here — they have
   *  no actions, so `play` always resolves a drop of 0, and their procedural
   *  bob in `update` owns `inst.position.y` alone. */
  private setClipDrop(drop: number) {
    if (Math.abs(drop - this.clipDrop) < 1e-4) return;
    this.clipDrop = drop;
    const inst = this.root.children[0];
    if (inst) inst.position.y = this.groundY - drop;
  }

  faceTowards(dir: THREE.Vector3) {
    if (dir.lengthSq() < 1e-6) return;
    this.targetYaw = Math.atan2(dir.x, dir.z);
  }

  /** Turn the ROOT to an absolute yaw (radians, three.js Y rotation) — for a
   *  pair interaction the anchor decides, the clip carries the body's facing. */
  setYaw(yaw: number) {
    this.targetYaw = yaw;
  }

  /** Play the half of a PAIR clip in lockstep with the game clock (§ A8a):
   *  `t` is the clip time in GAME seconds, `rate` the game seconds per real
   *  second the mixer advances at between polls (0 = frozen). Re-seeks only
   *  when the local time drifted more than PAIR_RESYNC_S from `t`, so a poll
   *  never makes the figure stutter. Returns false when the half is not
   *  bound on this rig — the caller then falls back to a solo clip. */
  playPair(clipName: string, t: number, rate: number): boolean {
    const action = this.actions.get(clipName);
    if (!action) return false;
    this.setClipDrop(0);
    this.terrainClip = false;
    this.sink = 0;
    const duration = action.getClip().duration || 1;
    const want = Math.min(Math.max(t, 0), duration);
    if (this.current !== action) {
      action.reset().fadeIn(0.25).play();
      action.time = want;
      this.current?.fadeOut(0.25);
      this.current = action;
      this.currentKind = clipName;
      this.root.userData.clipKind = clipName;
      this.root.userData.clipBound = true;
    } else if (Math.abs(action.time - want) > PAIR_RESYNC_S) {
      action.time = want;
    }
    action.timeScale = rate;
    return true;
  }

  /** Neigung aus einem Animations-Marker (Grad): `tilt` = Kopf hoch/tief,
   *  `roll` = seitlich kippen. 'YXZ' hält den Gierwinkel vorne, damit die
   *  Neigung im FIGUREN-System wirkt und nicht in der Welt — sonst hinge sie
   *  von der Blickrichtung ab. 0/0 = aufrecht wie bisher. */
  setLean(tilt: number, roll: number) {
    this.root.rotation.order = 'YXZ';
    this.root.rotation.x = THREE.MathUtils.degToRad(tilt);
    this.root.rotation.z = THREE.MathUtils.degToRad(roll);
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
