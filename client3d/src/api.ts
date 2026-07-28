import type { AtLocationChar, AuthUser, WorldLocation, WorldMap } from './types';
// Zusaetzlich lokal importiert: der Re-Export weiter unten stellt die Typen
// nur nach aussen, die Parse-Helfer hier brauchen sie im eigenen Scope.
import type {
  SceneExit, SceneExtra, SceneMarker, SceneModelSpec, ScenePayload,
  ScenePlate, SceneRoom, SceneWall,
} from '@anima/scene-render';

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json() as Promise<T>;
}

export async function authStatus(): Promise<{ authenticated: boolean; user?: AuthUser }> {
  return json(await fetch('/auth/status'));
}

export async function login(username: string, password: string): Promise<AuthUser> {
  const res = await fetch('/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) throw new Error('Login fehlgeschlagen');
  const data = await res.json();
  return data.user as AuthUser;
}

export async function logout(): Promise<void> {
  await fetch('/auth/logout', { method: 'POST' });
}

export async function getLocations(): Promise<WorldLocation[]> {
  const data = await json<{ locations: WorldLocation[] }>(await fetch('/world/locations'));
  return data.locations;
}

export async function getWorldMap(): Promise<WorldMap> {
  return json(await fetch('/play/worldmap'));
}

export async function getCharactersAtLocation(locationId: string): Promise<AtLocationChar[]> {
  const data = await json<{ characters: AtLocationChar[] }>(
    await fetch(`/characters/at-location?location=${encodeURIComponent(locationId)}`)
  );
  return data.characters ?? [];
}

// --- 3D-Assets (AV3D-5) ------------------------------------------------------

export interface ApiClip {
  kind: string;
  /** Figur, für die der Clip autoriert wurde (female/male/animal/…); leer = Default */
  set?: string;
  name: string;
  filename: string;
  url: string;
}

/** Globale Animations-Bibliothek des Servers; leer, wenn nicht verfügbar. */
export async function getAnimationClips(): Promise<ApiClip[]> {
  try {
    const res = await fetch('/assets/animation-clips');
    if (!res.ok) return [];
    const data = await res.json();
    return (data.clips ?? []) as ApiClip[];
  } catch {
    return [];
  }
}

export interface ApiModel {
  url: string;
  /** Kennung des konkreten Modells (ändert sich z.B. beim Outfit-Wechsel) */
  signature?: string;
  format: 'glb' | 'fbx';
  /** "mixamo" = Clip-Bibliothek anwendbar; "generic" = eigenes Skelett (Tiere) */
  rig: 'mixamo' | 'generic' | string;
  /** nur im FBX-Fall: separat gespeicherte Textur */
  textureUrl?: string;
}

/** Maßstabs-Anker (backend-note-scale-anchors.md, v3): 0 = nicht deklariert. */
export interface ApiModelAnchors {
  /** Orientierungs-Korrektur in Grad (Admin-Regler) */
  rotation?: { x?: number; y?: number; z?: number };
  /** Höhen-Feinjustierung in Metern */
  offset_y?: number;
  /** Kachel-Verschiebung in Welt-Metern (±25, nur Gebäude): letzter Schritt
   *  der Kette, Welt-Achsen (+x = Ost, +z = Süd), Yaw dreht NICHT mit */
  offset_x?: number;
  offset_z?: number;
  /** Gebäude: geschätzte Gesamthöhe in realen Metern */
  height_m?: number;
  /** Gebäude: sichtbare Geschosse des Meshs */
  floors?: number;
  /** Raum: geschätzte reale Breite (größte Seite) in Metern */
  width_m?: number;
  /** Änderungs-Kennung des Modells (Cache-Invalidierung) */
  signature?: string;
}

/** Modell-Info eines Charakters; null wenn der Server keins hat (404).
 *  Andere Fehler (Netzwerk, 5xx) werfen — der Aufrufer darf sie nicht als
 *  "hat keins" cachen, sondern soll später erneut versuchen. */
export async function getCharacterModel(name: string): Promise<ApiModel | null> {
  const res = await fetch(`/characters/${encodeURIComponent(name)}/model3d`);
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`model3d ${name}: HTTP ${res.status}`);
  const data = await res.json();
  const m = data?.model;
  if (!m?.url) return null;
  return {
    url: m.url,
    signature: data.signature ?? m.filename ?? undefined,
    format: (m.format ?? 'glb') as 'glb' | 'fbx',
    rig: m.rig ?? data.rig ?? 'mixamo',
    textureUrl: m.texture_url ?? undefined,
  };
}


// --- Szenen-Rezept (schnittstellen-3d.md Teil B) ------------------------------
// Der Server komponiert die GANZE Szene einer Location; der Client stellt sie
// nur dar. Jede Zahl ist bereits ein WELT-Meter um das Kachelzentrum — keine
// Fraktionen, keine Maßstabsfaktoren, keine Geometrie-Entscheidung hier.
// Gegenstück auf der Serverseite: app/core/scene_recipe.py.
//
// Die Typen selbst leben in @anima/scene-render: EINE Definition für diesen
// Client und die Admin-Vorschau. Sie standen vorher doppelt (hier und in
// frontend/src/tabs/world/worldTypes.ts) und waren bereits auseinander-
// gelaufen. Re-Export, damit kein Importeur angefasst werden muss.
export type {
  ScenePayload, ScenePlate, SceneWall, SceneExtra, SceneModelSpec,
  SceneMarker, SceneExit, SceneStyle, SceneRoom,
  /** hiess hier frueher ApiOpening */
  SceneOpening,
} from '@anima/scene-render';

/** Komplette Szene einer Location (§ B1). 404 = nichts zu komponieren (kein
 *  Grundriss, kein Raum mit Layout, kein Gebäudemodell) → Legacy-Pfad wie
 *  bisher. Andere Fehler werfen; der Aufrufer versucht es später erneut. */
export async function getLocationScene(locationId: string): Promise<ScenePayload | null> {
  const res = await fetch(`/play/locations/${encodeURIComponent(locationId)}/scene`);
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`scene ${locationId}: HTTP ${res.status}`);
  const data = await res.json();
  if (!data?.signature) return null;
  // Defensiv nur da, wo eine kaputte Liste den Aufbau abbrechen ließe; die
  // Zahlenfelder kommen aus dem Composer und werden NICHT nachgerechnet.
  const arr = <T>(v: unknown): T[] => (Array.isArray(v) ? (v as T[]) : []);
  return {
    signature: String(data.signature),
    rooms: arr<SceneRoom>(data.rooms),
    extent_m: data.extent_m || 10,
    k: data.k || 1,
    storey_m: data.storey_m || 3,
    levels: arr(data.levels),
    style: data.style ?? {},
    plates: arr<ScenePlate>(data.plates).filter((p) => arr(p.outline).length >= 3),
    walls: arr<SceneWall>(data.walls),
    extras: arr<SceneExtra>(data.extras),
    models: arr<SceneModelSpec>(data.models),
    figures: data.figures ?? { base_height_m_world: 1.7, stand_clearance: 0.12 },
    markers: arr<SceneMarker>(data.markers),
    exits: arr<SceneExit>(data.exits),
    outdoor_rooms: arr<string>(data.outdoor_rooms),
  };
}

/** Zusammenstellung (Surface-Tab): Zonen-Verlauf Richtung einer Nachbar-Art. */
export interface ApiSurfaceBlend {
  /** Nachbar-Art, zu der der Verlauf zeigt (z.B. "water") */
  toward: string;
  /** Zonen von der toward-Kante aus; until = Anteil 0..1 des Übergangswegs,
   *  letzte Zone ohne until = Rest; kind "neighbor" = Art des Land-Nachbarn */
  zones: { kind: string; until?: number }[];
  /** Ausfransung der Zonengrenzen (0..~0.15, Default 0.06) */
  noise?: number;
}

export interface ApiSurfaceTexture {
  kind: string;      // road | grass | water | coast | ... (offen, wie terrain)
  /** einfache Fläche: kachelbares Bild */
  url?: string;
  /** physische Kantenlänge der Textur in Metern (Kachel-Maßstab; Default 3) */
  size_m?: number;
  /** ODER Zusammenstellung aus anderen Arten (Küste usw.) */
  blend?: ApiSurfaceBlend;
}

/** Globale Oberflächen-Texturen für Terrain-Kacheln; leer/404 = Client
 *  nutzt seine eingebauten prozeduralen Texturen. */
export async function getSurfaceTextures(): Promise<ApiSurfaceTexture[]> {
  try {
    const res = await fetch('/assets/surface-textures');
    if (!res.ok) return [];
    const data = await res.json();
    const list = Array.isArray(data) ? data : data.textures ?? [];
    return list.filter((t: ApiSurfaceTexture) => t?.kind && (t.url || t.blend));
  } catch {
    return [];
  }
}

/** Spielzeit der Welt (Stunde 0..24, fraktional); null wenn nicht verfügbar. */
export async function getGameHour(): Promise<number | null> {
  try {
    const res = await fetch('/world/game-time');
    if (!res.ok) return null;
    const data = await res.json();
    const t = new Date(data.game_now);
    if (isNaN(t.getTime())) return null;
    return t.getUTCHours() + t.getUTCMinutes() / 60;
  } catch {
    return null;
  }
}
