// Grundriss-Vorschau (AV3D-2) für den Game-Admin:
//   /floorplan.html?location=<id-oder-name>[&verify=1]
// Zeigt EINE Location isoliert mit aufgedeckter Innenansicht und pollt sie —
// Änderungen im Grundriss-Editor erscheinen ohne Reload. Gedacht als iframe
// rechts neben dem Editor; Voraussetzung ist eine bestehende Anmeldung im
// 3D-Client.
//
// Hat die Location ein Szenen-Rezept (Vertrag § B1), rendert die Vorschau
// AUSSCHLIESSLICH daraus — damit zeigt sie zwangsläufig dasselbe Bild wie die
// Game-Admin-Vorschau, die denselben Composer über /play/scene-preview liest
// (§ B3). Ohne Rezept (404) bleibt der Legacy-Pfad. `&verify=1` schaltet den
// Verify-Modus nach § B5a ein: Welt-BBox je Objekt gegen die Spec, ε = 0,01 m,
// Ausgabe als Konsolen-Tabelle.
import * as THREE from 'three';
import { Engine } from './scene/engine';
import { applyRoomModel, applyTileFade, buildTile, type Tile } from './scene/tiles';
import { roomModelLibrary, setModelEnvironment } from './scene/buildings';
import { getLocationModel, getProps, getRoomModel, getRoomRecipe, getSurfaceTextures, type ApiRoomRecipe } from './api';
import { setLocationAnchor, setSurfaceTextures, storeyHeight } from './scene/tiles';
import { setPropLibrary } from './scene/propAssets';
import { mountRoomRecipe } from './scene/roomRecipe';
import { mountScene, SceneLibrary } from './scene/sceneRecipe';
void getSurfaceTextures().then(setSurfaceTextures);
void getProps().then(setPropLibrary);
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

const roomModels = roomModelLibrary();
// Raum-Rezepte (Legacy-Pfad, nur ohne Szenen-Rezept)
const recipeByRoom = new Map<string, ApiRoomRecipe | null>();
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

  const scene = scenes.get(loc.id);
  const shown: WorldLocation = { ...loc, grid_x: 0, grid_y: 0, rooms: loc.rooms ?? [] };
  // Editor-Kontext: Exit-Punkte zeigen (nur Legacy — im Szenen-Pfad kommen
  // Ausgänge fertig als Weltpunkte und brauchen keine gemalten Hilfspunkte)
  tile = buildTile(shown, { markers: !scene, sceneMode: !!scene });
  tile.fade = 1;
  tile.fadeTarget = 1;   // Innenansicht dauerhaft aufgedeckt
  engine.scene.add(tile.group);
  if (scene) {
    // Kachel steht auf Grid 0/0 → Payload-Koordinaten sind hier direkt
    // Weltkoordinaten; die Verify-Tabelle vergleicht damit 1:1 gegen die Spec.
    void mountScene(tile, scene).then((report) => {
      if (report) {
        say(report.rows.length
          ? `Verify: ${report.rows.length} Abweichung(en) von ${report.checked} Zahlen — siehe Konsole`
          : `Verify: ${report.checked} Zahlen geprüft, keine Abweichung`);
      }
    });
    return;
  }
  for (const room of shown.rooms) {
    if (!room.layout) continue;
    // Hülle immer aus dem Rezept; das Diorama koexistiert (model_at)
    const recipe = recipeByRoom.get(room.id);
    if (recipe && recipe.outline.length >= 3) void mountRoomRecipe(tile, room.id, recipe);
    const model = roomModels.get(room.id);
    if (model) applyRoomModel(tile, room.id, model);
    else roomModels.request(room.id);
  }
}

roomModels.onModelReady = (roomId) => {
  if (!tile || scenes.has(tile.loc.id)) return;
  const model = roomModels.get(roomId);
  if (model) applyRoomModel(tile, roomId, model);
};

async function poll() {
  const loc = await fetchLocation();
  if (!loc) return;

  // Szenen-Rezept zuerst: seine Signatur deckt map3d, ALLE Raum-Layouts, die
  // Modell-Metas und die Prop-Sidecars ab (§ B1) — ein Poll, ein Vergleich.
  // genau EIN Fetch je Poll: beim ersten Mal holen, danach die Signatur prüfen
  if (scenes.get(loc.id) === undefined) await scenes.prime([loc.id]);
  else await scenes.sweep();
  const scene = scenes.get(loc.id);
  if (scene) {
    if (scene.signature !== lastSig) {
      lastSig = scene.signature;
      rebuild(loc);
      say('');
    }
    return;
  }

  // Auch Meta-Justierungen (rotation/offset_y/Anker/signature) live
  // übernehmen: Metas abfragen und geänderte Modelle aus dem Cache werfen.
  const metas: unknown[] = [];
  for (const r of loc.rooms ?? []) {
    if (!r.layout) continue;
    try {
      const meta = await getRoomModel(r.id);
      metas.push([r.id, meta?.rotation, meta?.offset_y, meta?.width_m, meta?.signature]);
    } catch { /* Server kurz weg -> nächster Poll */ }
    // Rezept mitpollen — signature bewegt sich bei Layout- UND Prop-Änderungen
    try {
      const recipe = await getRoomRecipe(r.id);
      recipeByRoom.set(r.id, recipe);
      metas.push([r.id, 'recipe', recipe?.signature]);
    } catch { /* Server kurz weg -> nächster Poll */ }
  }
  // v3-Anker (explizit): plan_width_m + Gebäude-Meta -> Etagen/Figuren-Maßstab
  try {
    const bmeta = await getLocationModel(loc.id);
    metas.push(['building', bmeta?.height_m, bmeta?.floors, bmeta?.signature,
      bmeta?.rotation, bmeta?.offset_y, bmeta?.offset_x, bmeta?.offset_z]);
    const planW = loc.map3d?.plan_width_m || 0;
    if (planW > 0) {
      const k = 8 / planW;
      const storeyWorld = bmeta?.height_m && bmeta?.floors
        ? (bmeta.height_m / bmeta.floors) * k
        : storeyHeight(loc);
      setLocationAnchor(loc.id, { k, storeyWorld });
    }
  } catch { /* Server kurz weg */ }
  const sig = JSON.stringify([
    loc.entry_room,
    (loc.rooms ?? []).map((r) => [r.id, r.name, r.layout]),
    metas,
  ]);
  if (sig !== lastSig) {
    if (lastSig) for (const r of loc.rooms ?? []) roomModels.invalidate(r.id);
    lastSig = sig;
    rebuild(loc);
    say('');
  }
}

void poll();
setInterval(poll, POLL_MS);
engine.addFrameHook((dt) => {
  if (tile) applyTileFade(tile, dt);
});
