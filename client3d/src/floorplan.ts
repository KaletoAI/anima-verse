import { buildPlace, type PlaceRecord } from './scene/places';
// Floor-plan preview (AV3D-2) for the game admin:
//   /floorplan.html?location=<id-or-name>[&verify=1]
// Shows ONE isolated location with its interior revealed and polls it —
// floor-plan editor changes appear without reloading. Intended as an iframe
// beside the editor; requires an existing login in the 3D client.
//
// The preview renders EXCLUSIVELY from the scene recipe (contract § B1),
// producing the same view as the game-admin preview, which reads the same
// composer through /play/scene-preview (§ B3). Without a recipe (404), the
// server defines no room layout, floor plan or building model — only the
// bare tile and a notice remain.
// `&verify=1` enables verification per § B5a: compare each object's world BBox
// against the spec, ε = 0.01 m, with results in a console table.
import * as THREE from 'three';
import { Engine } from './scene/engine';
import { applyTileFade, buildTile, setSurfaceTextures, type Tile } from './scene/tiles';
import { setModelEnvironment } from './scene/glbMaterials';
import { getSurfaceTextures } from './api';
import { mountScene, SceneLibrary, unmountScene } from './scene/sceneRecipe';
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
(window as unknown as { __engine: Engine }).__engine = engine;   // Debug hook (as in main)
engine.setGameHour(11);
engine.target.set(0, 0, 0);
engine.dist = engine.targetDist = 22;
engine.pitchOffset = 28;

// Subtle meadow ground so the tile does not float in the sky
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

let previewPlace: PlaceRecord | null = null;

function rebuild(loc: WorldLocation) {
  if (previewPlace) engine.scene.remove(previewPlace.anchor);
  if (tile) {
    engine.scene.remove(tile.group);
    // …and give back what the old scene allocated. The editor polls every
    // 4 s and every signature change lands here, so without this a whole
    // tile's geometries, materials and texture clones leaked per rebuild
    // (review finding UI-3 neighbourhood; the ownership ledger of the scene
    // mount is what frees them).
    unmountScene(tile);
  }
  // Remove old CSS2D labels; the renderer does not clear their DOM nodes.
  document.querySelectorAll('.room-label, .loc-label').forEach((el) => el.remove());

  // The preview shows ONE location, at the world origin: `buildTile` places it
  // on its footprint centre (E4 task 3), and that centre is forced to 0/0 here
  // — so the payload coordinates below are already world coordinates and the
  // verify table can compare them 1:1 against the spec.
  const shown: WorldLocation = { ...loc, pos_x: 0, pos_z: 0, rooms: loc.rooms ?? [] };
  const place = previewPlace = buildPlace(shown);
  tile = buildTile(place);
  engine.scene.add(place.anchor);
  tile.fade = 1;
  tile.fadeTarget = 1;   // Keep the interior permanently open.
  engine.scene.add(tile.group);
  const scene = scenes.get(loc.id);
  if (!scene) {
    say('Kein Szenen-Rezept für diese Location (kein Raum-Layout, kein '
      + 'Grundriss, kein Gebäudemodell) — es gibt nichts aufzuklappen.');
    return;
  }
  // The place is at the origin, so payload coordinates are world coordinates;
  // the verification table compares them directly against the spec.
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

  // ONE signature covers map3d, ALL room layouts, model metadata and prop
  // sidecars (§ B1) — one poll, one comparison, no metadata collection.
  // Exactly ONE fetch per poll: retrieve initially, then check the signature.
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
