import type { AtLocationChar, AuthUser, RoomMarker, WorldLocation, WorldMap } from './types';

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
    offset_x: data.offset_x, offset_z: data.offset_z,
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

// --- Raum-Rezept & Prop-Bibliothek (Raum-Props) ------------------------------

export interface ApiProp {
  id: string;
  name: string;
  category?: string;
  /** REALE Maße in Metern, NACH dem Orientierungs-Fix (x=width, y=height, z=depth) */
  width_m: number;
  depth_m: number;
  height_m: number;
  /** Orientierungs-Fix in Grad (Euler 'XYZ', wie bei den Raum-Modellen) */
  rotation?: { x?: number; y?: number; z?: number };
  tags?: string[];
  marker_count?: number;
  has_model: boolean;
}

/** Prop-Bibliothek; BARE ARRAY vom Server, leer = Normalzustand.
 *  Fehler/nicht verfügbar → []. */
export async function getProps(): Promise<ApiProp[]> {
  try {
    const res = await fetch('/assets/props');
    if (!res.ok) return [];
    const data = await res.json();
    const list = Array.isArray(data) ? data : data.props ?? [];
    return list.filter((p: ApiProp) => p?.id);
  } catch {
    return [];
  }
}

export function propModelUrl(id: string): string {
  return `/assets/props/${encodeURIComponent(id)}/model`;
}

export interface ApiOpening {
  edge: number;            // Kanten-INDEX in outline (Kante i = Punkt i -> i+1)
  at: number;              // 0..1 ENTLANG der gerichteten Kante (Öffnungs-Mitte)
  width_m: number;
  height_m: number;
  sill_m: number;          // reale Meter
  type: string;            // "window" | "door" | "passage" (offen)
  to?: string;
  prop_id?: string;
  /** vom Nachbarraum gespiegelte Öffnung (rein informativ; Kante/at sind
   *  bereits auf diesen Raum umgerechnet -> exakt wie eigene behandeln) */
  mirrored?: boolean;
}

export interface ApiPlacement {
  prop_id: string;
  at: [number, number];    // Fraktionen des 8x8-Referenzquadrats
  yaw: number;             // Grad, im Uhrzeigersinn (Draufsicht)
  offset_y: number;        // reale Meter
  dims: { width_m: number; depth_m: number; height_m: number };
  has_model: boolean;
  model_url?: string;
  missing?: boolean;
}

export interface ApiPropMarker {
  placement: number;       // Index in placements
  animation: string;
  offset_m: [number, number]; // Meter relativ zum Platzierungspunkt (dx, dz)
  height_m: number;        // Meter ÜBER dem Etagenboden
  facing?: number;         // Grad, Welt-Kompass (0=S/90=E/180=N/270=W)
}

export interface ApiRoomRecipe {
  room_id: string;
  level: number;
  rotation?: number;       // Modell-Yaw wie gehabt
  outline: [number, number][];   // absolute Fraktionen 8x8, im Uhrzeigersinn
  surfaces?: { floor?: string; wall?: string };   // Surface-Texture-Kinds
  openings?: ApiOpening[];
  exit?: [number, number];
  /** exit wurde aus einer Tür/Passage abgeleitet (layout.exit fehlt) */
  exit_derived?: boolean;
  markers?: RoomMarker[];        // bestehendes Vokabular aus types.ts
  placements?: ApiPlacement[];
  prop_markers?: ApiPropMarker[];
  signature: string;             // md5, ändert sich bei Layout- UND Prop-Änderungen
}

/** Raum-Rezept; 404 = Raum ohne Layout (null), andere Fehler werfen.
 *  Optionale Felder werden durchgereicht; nur outline auf gültige
 *  [x, y]-Paare gefiltert (defensiv wie bei map3d.outline im Bestand). */
export async function getRoomRecipe(roomId: string): Promise<ApiRoomRecipe | null> {
  const res = await fetch(`/play/rooms/${encodeURIComponent(roomId)}/recipe`);
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`room recipe ${roomId}: HTTP ${res.status}`);
  const data = await res.json();
  if (!data) return null;
  const outline = (Array.isArray(data.outline) ? data.outline : []).filter(
    (p: unknown): p is [number, number] =>
      Array.isArray(p) && p.length === 2 && typeof p[0] === 'number' && typeof p[1] === 'number'
  );
  return {
    room_id: data.room_id,
    level: data.level ?? 0,
    rotation: data.rotation,
    outline,
    surfaces: data.surfaces,
    openings: data.openings,
    exit: data.exit,
    markers: data.markers,
    placements: data.placements,
    prop_markers: data.prop_markers,
    signature: data.signature ?? '',
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
