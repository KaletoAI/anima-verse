import * as THREE from 'three';
import { CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';
import type { MapCharacter } from '../types';
import { activityToClipKind, Figure, FigureLibrary } from './figures';
import { PathGrid } from './pathfind';
import { seededRandom } from './textures';

const WALK_SPEED = 3.4; // Welteinheiten pro Sekunde (~Gehtempo bei 10er-Zellen)
const RUN_DISTANCE = 6; // weiter als das entfernt -> Lauf-Animation

function ringColor(name: string): string {
  const rnd = seededRandom(name);
  return `hsl(${Math.floor(rnd() * 360)}, 65%, 55%)`;
}

/** Rundes Portrait mit farbigem Ring als Sprite-Textur; lädt das Avatarbild nach. */
function makePortraitTexture(name: string, avatarUrl: string | undefined, isAvatar: boolean): THREE.CanvasTexture {
  const S = 144;
  const c = document.createElement('canvas');
  c.width = c.height = S;
  const ctx = c.getContext('2d')!;
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;

  const draw = (img: HTMLImageElement | null) => {
    ctx.clearRect(0, 0, S, S);
    const r = S / 2 - 6;
    ctx.fillStyle = isAvatar ? '#e8b83a' : ringColor(name);
    ctx.beginPath();
    ctx.moveTo(S / 2 - 10, S - 26);
    ctx.lineTo(S / 2 + 10, S - 26);
    ctx.lineTo(S / 2, S);
    ctx.closePath();
    ctx.fill();

    ctx.beginPath();
    ctx.arc(S / 2, S / 2 - 8, r - 8, 0, Math.PI * 2);
    ctx.fillStyle = '#2b3440';
    ctx.fill();
    ctx.save();
    ctx.clip();
    if (img) {
      const s = Math.max((2 * (r - 8)) / img.width, (2 * (r - 8)) / img.height);
      ctx.drawImage(img, S / 2 - (img.width * s) / 2, S / 2 - 8 - (img.height * s) / 2, img.width * s, img.height * s);
    } else {
      ctx.fillStyle = '#e8e2d5';
      ctx.font = `bold ${S / 3}px system-ui, sans-serif`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      const initials = name.split(/\s+/).map((p) => p[0] ?? '').join('').slice(0, 2).toUpperCase();
      ctx.fillText(initials, S / 2, S / 2 - 6);
    }
    ctx.restore();
    ctx.lineWidth = 7;
    ctx.strokeStyle = isAvatar ? '#e8b83a' : ringColor(name);
    ctx.beginPath();
    ctx.arc(S / 2, S / 2 - 8, r - 5, 0, Math.PI * 2);
    ctx.stroke();
    tex.needsUpdate = true;
  };

  draw(null);
  if (avatarUrl) {
    const img = new Image();
    img.onload = () => draw(img);
    img.src = avatarUrl;
  }
  return tex;
}

interface Npc {
  name: string;
  /** AV3D-6: vom Server gelieferte Animations-Kategorie (schlägt das Raten) */
  animation?: string;
  root: THREE.Group;
  figure: Figure | null;
  ring: THREE.Mesh | null;
  sprite: THREE.Sprite | null;
  label: CSS2DObject;
  labelName: HTMLSpanElement;
  labelActivity: HTMLSpanElement;
  target: THREE.Vector3;
  /** Ziel-Skalierung (1 = Kartengröße; kleiner in Innenräumen) */
  targetScale: number;
  /** feste Blickrichtung im Stand (Marker) — sonst Nachbarn ansehen */
  face: THREE.Vector3 | null;
  /** Restliche Wegpunkte bis zum Ziel (Wegfindung um Gebäude) */
  waypoints: THREE.Vector3[];
  /** server journey being followed (§ A11) — replaces goal/waypoint logic */
  route: NpcState['route'] | null;
  activity: string;
  travelLine: THREE.Line | null;
  travelKey: string;
  bobPhase: number;
}

export interface NpcState {
  char: MapCharacter;
  pos: THREE.Vector3;               // Zielposition auf der Karte
  /** Skalierung der Figur (1 = Kartengröße; kleiner in Innenräumen) */
  scale?: number;
  /** feste Blickrichtung im Stand (z.B. vom Animations-Marker) */
  face?: THREE.Vector3;
  /** Figur ausblenden (z.B. andere Etage als die gewählte) */
  hidden?: boolean;
  /** Zwischenstationen (z.B. Raum-Ausgänge bei Raumwechsel, AV3D-2) */
  via?: THREE.Vector3[];
  /** server journey (§ A11): world points of the path cells (length ==
   *  travel.path.length) + last polled seg/frac; cellSecondsReal steers the
   *  client-side extrapolation between polls (null = frozen world).
   *  stamp identifies the worldmap poll the values came from — seg/frac
   *  reconciliation only runs against a genuinely fresh payload. */
  route?: { points: THREE.Vector3[]; seg: number; frac: number;
            cellSecondsReal: number | null; stamp: number };
  travelTo: THREE.Vector3 | null;   // Reiseziel (Linien-Endpunkt) oder null
}

export class NpcManager {
  group = new THREE.Group();
  private npcs = new Map<string, Npc>();
  private avatarName = '';
  private grid: PathGrid | null = null;

  constructor(private figures: FigureLibrary | null = null) {}

  /** Karten-Grid für die Wegfindung setzen (Gebäude blockieren). */
  setPathGrid(grid: PathGrid) {
    this.grid = grid;
  }

  setAvatar(name: string) {
    this.avatarName = name;
  }

  /** NPC verwerfen, damit er beim nächsten update() neu gebaut wird —
   *  z.B. wenn sein 3D-Modell vom Server nachgeladen wurde. */
  rebuild(charName: string) {
    const npc = this.npcs.get(charName);
    if (!npc) return;
    this.group.remove(npc.root);
    if (npc.travelLine) this.group.remove(npc.travelLine);
    npc.label.element.remove();
    this.npcs.delete(charName);
  }

  /** Soll-Zustand aus dem Worldmap-Poll übernehmen. */
  update(states: NpcState[]) {
    const seen = new Set<string>();
    for (const st of states) {
      seen.add(st.char.name);
      let npc = this.npcs.get(st.char.name);
      if (!npc) {
        npc = this.createNpc(st);
        this.npcs.set(st.char.name, npc);
        this.group.add(npc.root);
        npc.root.position.copy(st.pos); // erster Sync: nicht quer über die Karte laufen
      }
      // Adopt the server journey (§ A11). The RATE (cellSecondsReal) and the
      // path geometry are authoritative and adopted on every update — a
      // mid-journey freeze must stop the extrapolation immediately, not only
      // once the 0.5-cell snap fires. Only seg/frac are subject to
      // reconciliation, and only against a genuinely NEW worldmap payload
      // (stamp): update() runs at 1 Hz off the cached map, so comparing
      // against a stale payload would snap fast journeys backwards each
      // second. Hard snap when |server - local| > 0.5 cells, otherwise let
      // the local extrapolation keep running (avoids poll jitter).
      if (st.route) {
        if (!npc.route || npc.route.points.length !== st.route.points.length) {
          npc.route = { ...st.route, points: st.route.points.map((p) => p.clone()) };
        } else {
          npc.route.cellSecondsReal = st.route.cellSecondsReal;
          for (let k = 0; k < st.route.points.length; k++) {
            npc.route.points[k].copy(st.route.points[k]);
          }
          if (npc.route.stamp !== st.route.stamp) {
            const server = st.route.seg + st.route.frac;
            const local = npc.route.seg + npc.route.frac;
            if (Math.abs(server - local) > 0.5) {
              npc.route.seg = st.route.seg;
              npc.route.frac = st.route.frac;
            }
            npc.route.stamp = st.route.stamp;
          }
        }
        npc.waypoints = [];
      } else {
        npc.route = null;
      }
      // Zielwechsel -> Weg planen: vorgegebene Zwischenstationen (Raum-
      // Ausgänge) haben Vorrang, sonst um Gebäude herum (A*). Travellers are
      // exempt — on a journey the server route alone drives the figure.
      if (!st.route && !npc.target.equals(st.pos)) {
        npc.waypoints = st.via?.length
          ? st.via.map((v) => v.clone())
          : this.planPath(npc.root.position, st.pos);
      }
      npc.target.copy(st.pos);
      npc.targetScale = st.scale ?? 1;
      npc.face = st.face ?? null;
      npc.root.visible = !st.hidden;
      npc.activity = st.char.activity || '';
      npc.animation = st.char.activity_animation || undefined;
      npc.labelActivity.textContent = npc.activity;
      const travelling = !!st.travelTo;
      const eta = st.char.travel?.eta_game ? ` ${st.char.travel.eta_game.slice(11, 16)}` : '';
      npc.labelName.textContent = (travelling ? `🚶${eta} ` : '') + st.char.name;
      this.updateTravelLine(npc, st);
    }
    for (const [name, npc] of this.npcs) {
      if (!seen.has(name)) {
        this.group.remove(npc.root);
        if (npc.travelLine) this.group.remove(npc.travelLine);
        npc.label.element.remove();
        this.npcs.delete(name);
      }
    }
  }

  private createNpc(st: NpcState): Npc {
    const isAvatar = st.char.name === this.avatarName;
    const root = new THREE.Group();
    const figure = this.figures?.instantiate(st.char.name) ?? null;
    let sprite: THREE.Sprite | null = null;
    let ring: THREE.Mesh | null = null;
    let labelY: number;

    if (figure) {
      root.add(figure.root);
      // farbiger Bodenring als Wiedererkennung (gold = eigener Avatar)
      ring = new THREE.Mesh(
        new THREE.RingGeometry(0.55, 0.7, 28),
        new THREE.MeshBasicMaterial({
          color: isAvatar ? 0xe8b83a : new THREE.Color(ringColor(st.char.name)),
          transparent: true,
          opacity: 0.85,
        })
      );
      ring.rotation.x = -Math.PI / 2;
      ring.position.y = 0.09;
      root.add(ring);
      labelY = figure.height + 0.45;
    } else {
      const tex = makePortraitTexture(st.char.name, st.char.avatar_url, isAvatar);
      sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, depthTest: true }));
      sprite.center.set(0.5, 0.02);
      sprite.scale.setScalar(2.6);
      sprite.position.y = 0.15;
      root.add(sprite);
      const blob = new THREE.Mesh(
        new THREE.CircleGeometry(0.7, 18),
        new THREE.MeshBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.28 })
      );
      blob.rotation.x = -Math.PI / 2;
      blob.position.y = 0.08;
      root.add(blob);
      labelY = -0.15;
    }

    const el = document.createElement('div');
    el.className = 'npc-label' + (isAvatar ? ' npc-avatar' : '') + (figure ? ' above' : '');
    const nameEl = document.createElement('span');
    nameEl.className = 'npc-name';
    nameEl.textContent = st.char.name;
    const actEl = document.createElement('span');
    actEl.className = 'npc-activity';
    el.append(nameEl, actEl);
    const label = new CSS2DObject(el);
    label.position.set(0, labelY, 0);
    root.add(label);

    return {
      name: st.char.name, root, figure, ring, sprite, label,
      labelName: nameEl, labelActivity: actEl,
      target: st.pos.clone(), targetScale: st.scale ?? 1, face: st.face ?? null, waypoints: [], route: null, activity: st.char.activity || '',
      animation: st.char.activity_animation || undefined,
      travelLine: null, travelKey: '',
      bobPhase: Math.random() * Math.PI * 2,
    };
  }

  private updateTravelLine(npc: Npc, st: NpcState) {
    const key = st.travelTo ? `${st.travelTo.x},${st.travelTo.z}` : '';
    if (key === npc.travelKey) return;
    npc.travelKey = key;
    if (npc.travelLine) {
      this.group.remove(npc.travelLine);
      npc.travelLine.geometry.dispose();
      npc.travelLine = null;
    }
    if (st.travelTo) {
      const from = st.pos.clone().setY(0.3);
      const to = st.travelTo.clone().setY(0.3);
      const geo = new THREE.BufferGeometry().setFromPoints([from, to]);
      const line = new THREE.Line(geo, new THREE.LineDashedMaterial({
        color: 0xf2cd6e, dashSize: 0.9, gapSize: 0.6, transparent: true, opacity: 0.9,
      }));
      line.computeLineDistances();
      this.group.add(line);
      npc.travelLine = line;
    }
  }

  /** Weg von A nach B über begehbare Zellen; leer = direkte Linie genügt. */
  private planPath(from: THREE.Vector3, to: THREE.Vector3): THREE.Vector3[] {
    if (!this.grid) return [];
    if (from.distanceTo(to) < 12) return [];        // im selben Ort: direkt
    const a = PathGrid.cellOf(from);
    const b = PathGrid.cellOf(to);
    const pts = this.grid.findPath(a.x, a.y, b.x, b.y);
    if (pts.length > 1) console.info(`[path] ${pts.length - 1} Wegpunkte (${a.x},${a.y}) -> (${b.x},${b.y})`);
    return pts.slice(0, -1);                        // letzter Punkt = Zielzelle, dort gilt st.pos
  }

  /** Blickrichtung im Stand: zum Schwerpunkt der nahen Nachbarn schauen
   *  (wirkt wie ein Gesprächskreis); allein stehende schauen zur Kamera-Seite. */
  private facingTargets(): Map<string, THREE.Vector3> {
    const NEAR = 4.5;                       // Welteinheiten = "im selben Gespräch"
    const out = new Map<string, THREE.Vector3>();
    const list = [...this.npcs.values()];
    for (const npc of list) {
      const near = list.filter(
        (o) => o !== npc && o.root.position.distanceTo(npc.root.position) < NEAR
      );
      if (!near.length) continue;
      const c = new THREE.Vector3();
      for (const o of near) c.add(o.root.position);
      c.divideScalar(near.length);
      out.set(npc.name, c);
    }
    return out;
  }

  /** Pro Frame: Richtung Ziel laufen, Animation nach Zustand wählen. */
  tick(dt: number, camDist: number) {
    const labelVisible = camDist < 55;
    const spriteScale = THREE.MathUtils.clamp(camDist * 0.055, 1.7, 3.4);
    const faceTo = this.facingTargets();
    for (const npc of this.npcs.values()) {
      // Server journey (§ A11): walk along the route instead of npc.target.
      // The TOTAL progress (seg+frac as one number) is extrapolated and
      // seg/frac re-derived from it — advancing only the per-segment frac
      // would stall at every node until the next poll arrives.
      // cellSecondsReal == null (frozen world) => do not extrapolate.
      if (npc.route && npc.route.points.length >= 2) {
        const r = npc.route;
        if (r.cellSecondsReal && r.cellSecondsReal > 0) {
          let progress = r.seg + r.frac + dt / r.cellSecondsReal;
          const maxProgress = r.points.length - 1;
          // last node: hold at frac 1 and wait for the server's arrival
          // (travel vanishes up to half a cell BEFORE that — § A11)
          if (progress > maxProgress) progress = maxProgress;
          r.seg = THREE.MathUtils.clamp(Math.floor(progress), 0, r.points.length - 2);
          r.frac = progress - r.seg;
        }
        const a = r.points[r.seg];
        const b = r.points[Math.min(r.seg + 1, r.points.length - 1)];
        const goalPos = a.clone().lerp(b, r.frac);
        const delta = goalPos.clone().sub(npc.root.position);
        delta.y = 0;
        const d = delta.length();
        if (d > 0.05) {
          // catch-up speed: at most WALK_SPEED, so corrections stay a walk
          const step = Math.min(d, WALK_SPEED * dt);
          const dir = delta.clone().normalize();
          npc.root.position.addScaledVector(dir, step);
          npc.figure?.faceTowards(dir);
        }
        npc.root.position.y += (goalPos.y - npc.root.position.y) * Math.min(1, dt * 4);
        // blend back to map scale — a journey may start out of an interior
        const rs = npc.root.scale.x;
        if (Math.abs(rs - npc.targetScale) > 1e-3) {
          npc.root.scale.setScalar(rs + (npc.targetScale - rs) * Math.min(1, dt * 5));
        }
        if (npc.figure) {
          // no 'run' on journeys: the pace comes from the server —
          // walk while the game clock moves, idle on freeze
          npc.figure.play(d > 0.02 || (r.cellSecondsReal ?? 0) > 0 ? 'walk' : 'idle');
          npc.figure.update(dt);
          npc.ring?.scale.setScalar(THREE.MathUtils.clamp(camDist * 0.022, 1, 2.6));
        } else if (npc.sprite) {
          npc.bobPhase += dt * 14;
          npc.sprite.position.y = 0.15 + Math.abs(Math.sin(npc.bobPhase)) * 0.35;
          npc.sprite.scale.setScalar(spriteScale);
        }
        npc.label.visible = labelVisible;
        continue;   // travellers skip the normal goal/waypoint logic
      }
      // Nächster Wegpunkt (falls ein Weg geplant ist), sonst direkt zum Ziel
      while (npc.waypoints.length && npc.root.position.distanceTo(npc.waypoints[0]) < 1.5) {
        npc.waypoints.shift();
      }
      const goal = npc.waypoints[0] ?? npc.target;
      const delta = goal.clone().sub(npc.root.position);
      delta.y = 0;
      const distToGoal = delta.length();
      const dist = npc.waypoints.length ? distToGoal + 10 : distToGoal;  // unterwegs = laufen
      const moving = distToGoal > 0.05;
      if (moving) {
        const step = Math.min(distToGoal, WALK_SPEED * dt * (dist > RUN_DISTANCE ? 1.8 : 1));
        const dir = delta.clone().normalize();
        npc.root.position.addScaledVector(dir, step);
        npc.figure?.faceTowards(dir);
      }
      // Höhe dem AKTUELLEN Wegpunkt angleichen — so entsteht am Fahrstuhl
      // die vertikale Fahrt zwischen den Haltepunkten (AV3D-12)
      const goalY = npc.waypoints[0]?.y ?? npc.target.y;
      npc.root.position.y += (goalY - npc.root.position.y) * Math.min(1, dt * 4);
      // Skalierung weich überblenden (Innenraum-Maßstab vs. Kartengröße)
      const s = npc.root.scale.x;
      if (Math.abs(s - npc.targetScale) > 1e-3) {
        npc.root.scale.setScalar(s + (npc.targetScale - s) * Math.min(1, dt * 5));
      }
      if (!moving && npc.figure) {
        // Stehend: Marker-Richtung > Nachbarn ansehen > Kamera-Grundrichtung
        const target = faceTo.get(npc.name);
        const dir = npc.face
          ? npc.face.clone()
          : target
            ? target.clone().sub(npc.root.position).setY(0)
            : new THREE.Vector3(0, 0, 1);
        npc.figure.faceTowards(dir);
      }

      if (npc.figure) {
        // Server-Kategorie schlägt das Keyword-Raten (AV3D-6)
        const standingClip = npc.animation || activityToClipKind(npc.activity);
        npc.figure.play(moving ? (dist > RUN_DISTANCE ? 'run' : 'walk') : standingClip);
        npc.figure.update(dt);
        // Ring wächst mit der Kameradistanz, damit NPCs in der Fernsicht auffindbar bleiben
        npc.ring?.scale.setScalar(THREE.MathUtils.clamp(camDist * 0.022, 1, 2.6));
      } else if (npc.sprite) {
        if (moving) {
          npc.bobPhase += dt * 14;
          npc.sprite.position.y = 0.15 + Math.abs(Math.sin(npc.bobPhase)) * 0.35;
        } else {
          npc.sprite.position.y = 0.15;
        }
        npc.sprite.scale.setScalar(spriteScale);
      }
      npc.label.visible = labelVisible;
    }
  }
}
