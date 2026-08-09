// Grundriss-Vorschau (AV3D-2) für den Game-Admin:
//   /floorplan.html?location=<id-oder-name>[&verify=1]
// Zeigt EINE Location isoliert mit aufgedeckter Innenansicht und pollt sie —
// Änderungen im Grundriss-Editor erscheinen ohne Reload. Gedacht als iframe
// rechts neben dem Editor; Voraussetzung ist eine bestehende Anmeldung im
// 3D-Client.
//
// Die Vorschau rendert AUSSCHLIESSLICH aus dem Szenen-Rezept (Vertrag § B1)
// und zeigt damit zwangsläufig dasselbe Bild wie die Game-Admin-Vorschau, die
// denselben Composer über /play/scene-preview liest (§ B3). Ohne Rezept (404)
// gibt es per Server-Definition weder Raum-Layout noch Grundriss noch
// Gebäudemodell — dann bleibt die nackte Kachel mit Hinweis.
// `&verify=1` schaltet den Verify-Modus nach § B5a ein: Welt-BBox je Objekt
// gegen die Spec, ε = 0,01 m, Ausgabe als Konsolen-Tabelle.
import * as THREE from 'three';
import { Engine } from './scene/engine';
import { applyTileFade, buildTile, setSurfaceTextures, type Tile } from './scene/tiles';
import { setModelEnvironment } from './scene/glbMaterials';
import { getSurfaceTextures } from './api';
import { mountScene, SceneLibrary } from './scene/sceneRecipe';
void getSurfaceTextures().then(setSurfaceTextures);
import { grassTexture } from './scene/textures';
import type { WorldLocation } from './types';

const POLL_MS = 4000;
const wanted = new URLSearchParams(location.search).get('location') ?? '';

const msg = document.createElement('div');
msg.style.cssText = 'position:fixed;top:12px;left:50%;transform:translateX(-50%);'
  + 'background:rgba(20,24,32,.85);color:#eee;padding:8px 14px;border-radius:8px;'
  + 'font:14px system-ui;z-index:10;display:none';
document.body.appendChild(msg);
const say = (t: string) => {
  msg.textContent = t;
  msg.style.display = t ? 'block' : 'none';
};

const engine = new Engine(document.body);
setModelEnvironment(engine.modelEnv);
(window as unknown as { __engine: Engine }).__engine = engine;   // Debug-Hook (wie main)
engine.setGameHour(11);
engine.target.set(0, 0, 0);
engine.dist = engine.targetDist = 22;
engine.pitchOffset = 28;

// dezenter Wiesen-Untergrund, damit die Kachel nicht im Himmel schwebt
const groundTex = grassTexture();
groundTex.repeat.set(8, 8);
const ground = new THREE.Mesh(
  new THREE.PlaneGeometry(80, 80),
  new THREE.MeshStandardMaterial({ map: groundTex, roughness: 1 })
);
ground.rotation.x = -Math.PI / 2;
ground.receiveShadow = true;
engine.scene.add(ground);

const scenes = new SceneLibrary();
let tile: Tile | null = null;
let lastSig = '';

async function fetchLocation(): Promise<WorldLocation | null> {
  const res = await fetch('/world/locations');
  if (res.status === 401 || res.status === 403) {
    say('Nicht angemeldet — bitte zuerst im 3D-Client einloggen.');
    return null;
  }
  if (!res.ok) {
    say(`Location-Daten nicht ladbar (HTTP ${res.status})`);
    return null;
  }
  const data = await res.json();
  const locs: WorldLocation[] = Array.isArray(data) ? data : data.locations ?? [];
  const loc = locs.find((l) => l.id === wanted || l.name === wanted);
  if (!loc) say(wanted ? `Location "${wanted}" nicht gefunden` : 'Aufruf: floorplan.html?location=<id>');
  return loc ?? null;
}

function rebuild(loc: WorldLocation) {
  if (tile) engine.scene.remove(tile.group);
  // CSS2D-Label-Reste des alten Baus entfernen (der Renderer räumt sie nicht ab)
  document.querySelectorAll('.room-label, .loc-label').forEach((el) => el.remove());

  // The preview shows ONE location, at the world origin: `buildTile` still
  // places by grid cell (E4 task 3 puts it on the footprint), and cell 0/0 is
  // the origin either way — so the payload coordinates below are already world
  // coordinates and the verify table can compare them 1:1 against the spec.
  const shown: WorldLocation = { ...loc, pos_x: 0, pos_z: 0, rooms: loc.rooms ?? [] };
  tile = buildTile(shown);
  tile.fade = 1;
  tile.fadeTarget = 1;   // Innenansicht dauerhaft aufgedeckt
  engine.scene.add(tile.group);
  const scene = scenes.get(loc.id);
  if (!scene) {
    say('Kein Szenen-Rezept für diese Location (kein Raum-Layout, kein '
      + 'Grundriss, kein Gebäudemodell) — es gibt nichts aufzuklappen.');
    return;
  }
  // Kachel steht auf Grid 0/0 → Payload-Koordinaten sind hier direkt
  // Weltkoordinaten; die Verify-Tabelle vergleicht damit 1:1 gegen die Spec.
  void mountScene(tile, scene).then((report) => {
    if (report) {
      const models = `Modelle ${report.models.placed}/${report.models.total}`;
      say(report.rows.length
        ? `Verify: ${report.rows.length} Abweichung(en) von ${report.checked} Zahlen `
          + `(${models}) — siehe Konsole`
        : `Verify: ${report.checked} Zahlen geprüft, keine Abweichung (${models})`);
    }
  });
}

async function poll() {
  const loc = await fetchLocation();
  if (!loc) return;

  // EINE Signatur deckt map3d, ALLE Raum-Layouts, die Modell-Metas und die
  // Prop-Sidecars ab (§ B1) — ein Poll, ein Vergleich, kein Meta-Sammeln mehr.
  // Genau EIN Fetch je Poll: beim ersten Mal holen, danach die Signatur prüfen.
  if (scenes.get(loc.id) === undefined) await scenes.prime([loc.id]);
  else await scenes.sweep();
  const sig = scenes.get(loc.id)?.signature ?? '(keine Szene)';
  if (sig !== lastSig) {
    lastSig = sig;
    say('');
    rebuild(loc);
  }
}

void poll();
setInterval(poll, POLL_MS);
engine.addFrameHook((dt) => {
  if (tile) applyTileFade(tile, dt);
});
