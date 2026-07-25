import * as THREE from 'three';
import type { ApiRoomRecipe } from '../api';

// Hüllen-Renderer für Polygon-Räume (Raum-Rezept, Abschnitt 2a): Bodenplatte
// + Wandsegmente aus dem outline-Polygon. Vorbild: der Gebäude-Grundriss-Block
// in tiles.ts (AV3D-12) — gleiche Punkt-Abbildung, gleiche wallSeg-Technik,
// gleiche Umlaufrichtungs-Erkennung. Kein CSG.

const LW = 8;               // Kantenlänge des 8x8-Referenzquadrats
const WALL_T = 0.07;        // Wanddicke (wie Vorbild)
const GLASS_T = 0.03;       // dünne Glasfläche in Fenster-Öffnungen
const EPS = 0.02;           // kürzere Stücke nicht bauen

export interface ShellCtx {
  k: number;        // Welt-Meter pro Real-Meter (8 / plan_width_m)
  storey: number;   // Etagenhöhe in Welt-Metern
  floorY: number;   // Etagen-Basis (level * storey) — Konvention wie Vorbild:
                    // Platten-OBERKANTE bei floorY + 0.08, Wände ab dort
  /** Aktive Surface-Textur eines Kinds; null = prozeduraler Fallback
   *  (dann schlichte Farben wie im Vorbild: Boden 0xd8d0c2, Wand 0xcfc4b2).
   *  Wird von der Integration geliefert — hier nur aufrufen. */
  surface: (
    kind: string | undefined,
    use: 'floor' | 'wall'
  ) => { texture: THREE.Texture; sizeM: number } | null;
  /** false = Outdoor-Raum (§2e): weder Wände noch Platten-Geometrie — nur
   *  die Boden-TEXTUR flach auf dem Untergrund (ohne surfaces.floor gar
   *  nichts, der Level-/Terrain-Boden scheint durch); Öffnungen wirken
   *  allein über die Spiegelung in den Nachbarwänden */
  walls?: boolean;
}

export interface RoomShell {
  group: THREE.Group;   // Kachel-LOKAL: Ursprung = Kachelzentrum, XZ-Ebene
  /** fürs Wall-Culling der Integration; mid/normal kachel-lokal (XZ) */
  walls: { mesh: THREE.Mesh; mid: THREE.Vector2; normal: THREE.Vector2 }[];
}

// Kleine lokale Pendants zu std()/box() aus tiles.ts (dort privat).
function std(opts: THREE.MeshStandardMaterialParameters): THREE.MeshStandardMaterial {
  return new THREE.MeshStandardMaterial({ roughness: 0.85, metalness: 0.02, transparent: true, ...opts });
}

function box(w: number, h: number, d: number, mat: THREE.Material): THREE.Mesh {
  const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat);
  m.castShadow = true;
  m.receiveShadow = true;
  return m;
}

export function buildRoomShell(recipe: ApiRoomRecipe, ctx: ShellCtx): RoomShell {
  const group = new THREE.Group();
  const walls: RoomShell['walls'] = [];
  const { k, floorY } = ctx;

  const pts = recipe.outline.map(([fx, fz]) => new THREE.Vector2(fx * LW - LW / 2, fz * LW - LW / 2));
  if (pts.length < 3) return { group, walls };

  const WALL_H = Math.max(0.6, ctx.storey - 0.15);
  // +0.10 statt +0.08: die Etagen-Platten des Gebäude-Grundrisses
  // (map3d.outline) liegen bei +0.08 — koplanar würde die Raum-Platte
  // dagegen z-fighten; +0.10 bleibt unter der Inhalts-Basis +0.12
  const baseY = floorY + 0.10;

  // Umlaufrichtung per Flächenvorzeichen (robust, auch wenn der Vertrag im
  // Uhrzeigersinn liefert) -> Außennormale der Wandstücke fürs Culling
  let area = 0;
  for (let i = 0; i < pts.length; i++) {
    const a = pts[i], b = pts[(i + 1) % pts.length];
    area += a.x * b.y - b.x * a.y;
  }
  const ccw = area > 0;

  // --- Outdoor (§2e): nur die Boden-Textur, flach auf dem Untergrund ----------
  if (ctx.walls === false) {
    const surf = recipe.surfaces?.floor ? ctx.surface(recipe.surfaces.floor, 'floor') : null;
    if (surf) {
      const tex = surf.texture.clone();
      tex.needsUpdate = true;
      tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
      const rep = 1 / (surf.sizeM * k);
      tex.repeat.set(rep, rep);
      // knapp über Terrain-/Sockelplatte (0.04/0.045) bzw. Etagen-Platte (0.08)
      const flat = new THREE.Mesh(
        new THREE.ShapeGeometry(new THREE.Shape(pts)),
        std({ color: 0xffffff, map: tex, side: THREE.DoubleSide })
      );
      flat.rotation.x = Math.PI / 2;   // Shape-XY -> Boden-XZ (wie die Platte)
      flat.position.y = floorY + (floorY > 0 ? 0.085 : 0.055);
      flat.receiveShadow = true;
      group.add(flat);
    }
    return { group, walls };
  }

  // --- Bodenplatte: outline-Fläche, Oberkante bei floorY + 0.08 ---------------
  const floorShape = new THREE.Shape(pts);
  const floorSurf = ctx.surface(recipe.surfaces?.floor, 'floor');
  const slabMat = floorSurf ? std({ color: 0xffffff }) : std({ color: 0xd8d0c2 });
  if (floorSurf) {
    // ExtrudeGeometry-UVs sind Shape-Koordinaten (Welt-Einheiten) -> Kachelmaß
    // sizeM x k, also repeat = 1 / (sizeM x k) in beiden Achsen
    const tex = floorSurf.texture.clone();
    tex.needsUpdate = true;
    tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
    const rep = 1 / (floorSurf.sizeM * k);
    tex.repeat.set(rep, rep);
    slabMat.map = tex;
  }
  const slab = new THREE.Mesh(
    new THREE.ExtrudeGeometry(floorShape, { depth: 0.14, bevelEnabled: false }),
    slabMat
  );
  slab.rotation.x = Math.PI / 2;   // Shape-XY -> Boden-XZ (nach unten extrudiert)
  slab.position.y = baseY;         // Oberkante knapp über der Etagen-Basis
  slab.receiveShadow = true;
  group.add(slab);

  // --- Wände: pro Kante Segmente, um Öffnungen geteilt ------------------------
  const wallSurf = ctx.surface(recipe.surfaces?.wall, 'wall');

  // Wand-Material für ein Stück gegebener Länge/Höhe; Box-UVs sind 0..1 pro
  // Fläche, daher pro Stück eine geklonte Textur mit eigener repeat.
  const wallMat = (segLen: number, segH: number): THREE.MeshStandardMaterial => {
    if (!wallSurf) return std({ color: 0xcfc4b2 });
    const tex = wallSurf.texture.clone();
    tex.needsUpdate = true;
    tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
    const tile = wallSurf.sizeM * k;
    tex.repeat.set(segLen / tile, segH / tile);
    return std({ color: 0xffffff, map: tex });
  };

  // Ein Wand-Stück entlang einer Kante platzieren (t = Meter entlang der Kante,
  // y = Welt-Meter). cull = true -> Voll-Segment fürs Culling eintragen.
  const placeSpan = (
    a: THREE.Vector2,
    dir: THREE.Vector2,
    normal: THREE.Vector2,
    t0: number,
    t1: number,
    yBottom: number,
    yTop: number,
    thickness: number,
    mat: THREE.Material,
    cull: boolean,
    castShadow: boolean
  ) => {
    const segLen = t1 - t0;
    const segH = yTop - yBottom;
    if (segLen < EPS || segH < EPS) return;
    const mid = a.clone().addScaledVector(dir, (t0 + t1) / 2);
    const seg = box(segLen, segH, thickness, mat);
    seg.position.set(mid.x, yBottom + segH / 2, mid.y);
    seg.rotation.y = -Math.atan2(dir.y, dir.x);
    seg.castShadow = castShadow;
    seg.receiveShadow = false;
    group.add(seg);
    if (cull) walls.push({ mesh: seg, mid: mid.clone(), normal: normal.clone() });
  };

  const glassMat = std({ color: 0xbcd4e0, opacity: 0.3, roughness: 0.3 });

  const openings = recipe.openings ?? [];
  for (let i = 0; i < pts.length; i++) {
    const a = pts[i], b = pts[(i + 1) % pts.length];
    const len = a.distanceTo(b);
    if (len < EPS) continue;
    const dir = b.clone().sub(a).divideScalar(len);
    const normal = ccw ? new THREE.Vector2(dir.y, -dir.x) : new THREE.Vector2(-dir.y, dir.x);

    // Öffnungen dieser Kante nach at sortieren. Annahme: `at` ist die
    // Öffnungs-MITTE (0..1 entlang der gerichteten Kante).
    const ops = openings
      .filter((o) => o.edge === i)
      .map((o) => {
        const c = THREE.MathUtils.clamp(o.at, 0, 1) * len;
        const half = (o.width_m * k) / 2;
        return { o, start: Math.max(0, c - half), end: Math.min(len, c + half) };
      })
      .sort((p, q) => p.start - q.start);

    const solid = (t0: number, t1: number) =>
      placeSpan(a, dir, normal, t0, t1, baseY, baseY + WALL_H, WALL_T, wallMat(t1 - t0, WALL_H), true, false);

    let cursor = 0;
    for (const { o, start, end } of ops) {
      // Voll-Wand bis zur Öffnung (Culling-Eintrag)
      if (start - cursor > EPS) solid(cursor, start);
      const span = end - start;
      // reale Meter -> immer x k (Backend-Vorschau hatte hier einen Vergesser)
      const sillTop = Math.min(baseY + o.sill_m * k, baseY + WALL_H);
      const openTop = Math.min(baseY + (o.sill_m + o.height_m) * k, baseY + WALL_H);
      // Brüstungsband (0 .. sill), NICHT ins Culling
      placeSpan(a, dir, normal, start, end, baseY, sillTop, WALL_T, wallMat(span, sillTop - baseY), false, false);
      // Öffnungsbereich: Fenster = Glasfläche, Tür/Passage = Lücke
      if (o.type === 'window') {
        placeSpan(a, dir, normal, start, end, sillTop, openTop, GLASS_T, glassMat, false, false);
      }
      // Sturzband (openTop .. Wandhöhe), NICHT ins Culling
      placeSpan(a, dir, normal, start, end, openTop, baseY + WALL_H, WALL_T, wallMat(span, baseY + WALL_H - openTop), false, false);
      cursor = Math.max(cursor, end);
    }
    // Rest-Wand bis Kantenende
    if (len - cursor > EPS) solid(cursor, len);
  }

  return { group, walls };
}
