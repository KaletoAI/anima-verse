import type { AtLocationChar, AuthUser, WorldLocation, WorldMap } from './types';

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

export function mapIconUrl(locationId: string): string {
  return `/world/locations/${encodeURIComponent(locationId)}/map-icon-2d`;
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

export interface ApiLocationModel extends ApiModelAnchors {
  url: string;
  format: string;
}

/** Gebäude-Modell einer Location (AV3D-9); null wenn der Server keins hat
 *  (404 ist der Normalfall — prozedurales Gebäude bleibt). Andere Fehler
 *  werfen, der Aufrufer versucht es später erneut. */
export async function getLocationModel(locationId: string): Promise<ApiLocationModel | null> {
  const res = await fetch(`/play/locations/${encodeURIComponent(locationId)}/model/meta`);
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`location model ${locationId}: HTTP ${res.status}`);
  const data = await res.json();
  if (!data?.url) return null;
  return {
    url: data.url, format: data.format ?? 'glb',
    rotation: data.rotation, offset_y: data.offset_y,
    height_m: data.height_m, floors: data.floors, signature: data.signature,
  };
}

export interface ApiRoomModel extends ApiModelAnchors {
  url: string;
  format: string;
}

/** 3D-Modell eines Raums (AV3D-2); null wenn keins da ist (404 = Normalfall). */
export async function getRoomModel(roomId: string): Promise<ApiRoomModel | null> {
  const res = await fetch(`/play/rooms/${encodeURIComponent(roomId)}/model/meta`);
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`room model ${roomId}: HTTP ${res.status}`);
  const data = await res.json();
  if (!data?.url) return null;
  return {
    url: data.url, format: data.format ?? 'glb',
    rotation: data.rotation, offset_y: data.offset_y,
    width_m: data.width_m, signature: data.signature,
  };
}

export interface ApiSurfaceTexture {
  kind: string;      // road | grass | water | gravel | ... (offen, wie terrain)
  url: string;
  /** physische Kantenlänge der Textur in Metern (Kachel-Maßstab; Default 3) */
  size_m?: number;
}

/** Globale Oberflächen-Texturen für Terrain-Kacheln; leer/404 = Client
 *  nutzt seine eingebauten prozeduralen Texturen. */
export async function getSurfaceTextures(): Promise<ApiSurfaceTexture[]> {
  try {
    const res = await fetch('/assets/surface-textures');
    if (!res.ok) return [];
    const data = await res.json();
    const list = Array.isArray(data) ? data : data.textures ?? [];
    return list.filter((t: ApiSurfaceTexture) => t?.kind && t?.url);
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
