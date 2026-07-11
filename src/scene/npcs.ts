import * as THREE from 'three';
import { CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';
import type { MapCharacter } from '../types';
import { seededRandom } from './textures';

const WALK_SPEED = 6; // Welteinheiten pro Sekunde

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
    // Zeiger-Spitze nach unten
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
  root: THREE.Group;
  sprite: THREE.Sprite;
  label: CSS2DObject;
  labelName: HTMLSpanElement;
  labelActivity: HTMLSpanElement;
  target: THREE.Vector3;
  travelLine: THREE.Line | null;
  travelKey: string;
  moving: boolean;
  bobPhase: number;
}

export interface NpcState {
  char: MapCharacter;
  pos: THREE.Vector3;               // Zielposition auf der Karte
  travelTo: THREE.Vector3 | null;   // Reiseziel (Linien-Endpunkt) oder null
}

export class NpcManager {
  group = new THREE.Group();
  private npcs = new Map<string, Npc>();
  private avatarName = '';

  setAvatar(name: string) {
    this.avatarName = name;
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
      npc.target.copy(st.pos);
      npc.labelActivity.textContent = st.char.activity || '';
      const travelling = !!st.travelTo;
      npc.labelName.textContent = (travelling ? '🚶 ' : '') + st.char.name;
      this.updateTravelLine(npc, st);
    }
    for (const [name, npc] of this.npcs) {
      if (!seen.has(name)) {
        this.group.remove(npc.root);
        npc.label.element.remove();
        this.npcs.delete(name);
      }
    }
  }

  private createNpc(st: NpcState): Npc {
    const isAvatar = st.char.name === this.avatarName;
    const root = new THREE.Group();

    const tex = makePortraitTexture(st.char.name, st.char.avatar_url, isAvatar);
    const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, depthTest: true }));
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

    const el = document.createElement('div');
    el.className = 'npc-label' + (isAvatar ? ' npc-avatar' : '');
    const nameEl = document.createElement('span');
    nameEl.className = 'npc-name';
    nameEl.textContent = st.char.name;
    const actEl = document.createElement('span');
    actEl.className = 'npc-activity';
    el.append(nameEl, actEl);
    const label = new CSS2DObject(el);
    label.position.set(0, -0.15, 0);
    root.add(label);

    return {
      name: st.char.name, root, sprite, label,
      labelName: nameEl, labelActivity: actEl,
      target: st.pos.clone(), travelLine: null, travelKey: '', moving: false,
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

  /** Pro Frame: Richtung Ziel laufen, leichtes Bobbing während der Bewegung. */
  tick(dt: number, camDist: number) {
    const labelVisible = camDist < 55;
    const spriteScale = THREE.MathUtils.clamp(camDist * 0.055, 1.7, 3.4);
    for (const npc of this.npcs.values()) {
      const delta = npc.target.clone().sub(npc.root.position);
      delta.y = 0;
      const dist = delta.length();
      npc.moving = dist > 0.05;
      if (npc.moving) {
        const step = Math.min(dist, WALK_SPEED * dt);
        npc.root.position.addScaledVector(delta.normalize(), step);
        npc.bobPhase += dt * 14;
        npc.sprite.position.y = 0.15 + Math.abs(Math.sin(npc.bobPhase)) * 0.35;
      } else {
        npc.sprite.position.y = 0.15;
      }
      npc.sprite.scale.setScalar(spriteScale);
      npc.label.visible = labelVisible;
    }
  }
}
