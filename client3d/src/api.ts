import type { AtLocationChar, AuthUser, WorldLocation, WorldMap } from './types';
// Imported locally as well: the re-export further down only exposes the types
// outwards, the parsing helpers here need them in their own scope.
import type {
  SceneBoundaryOpening, SceneDoorway, SceneExit, SceneExtra, SceneMarker,
  SceneModelSpec, ScenePayload, ScenePlate, SceneProblem, SceneRoom,
  SceneTerrain, SceneWall,
} from '@anima/scene-render';
// The audio manifest is TYPED and validated in the pure soundtrack module, so
// the choosing side and the fetching side cannot drift apart (E4-T5).
import { emptyManifest, readManifest, type AudioManifest } from './game/soundtrack';

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
  // Console/diagnostics only — the title screen shows its own translated line
  // (the raw text of a proxy error page would be neither).
  if (!res.ok) throw new Error(`login failed (HTTP ${res.status})`);
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

/** The player's map. `all` asks for the UNFILTERED view (contract § A12) — it
 *  is the admin switch of the game menu and answers 403 for anybody else, so
 *  callers must only pass it for role `admin`. */
export async function getWorldMap(all = false): Promise<WorldMap> {
  return json(await fetch(all ? '/play/worldmap?all=1' : '/play/worldmap'));
}

/** Error of a game call that carries the server's own reason. `message` is the
 *  server's `detail.message` where there is one — that text is written FOR the
 *  player and belongs in a toast unchanged. */
export class ApiError extends Error {
  status: number;
  /** machine-readable reason of the server (`party_follower`, `block_enter`, …) */
  reason: string;
  constructor(status: number, message: string, reason = '') {
    super(message);
    this.status = status;
    this.reason = reason;
  }
}

/** The refusal of a game call, read the way the server writes it: a `detail`
 *  object with `reason` + `message` is text FOR the player, a plain string
 *  detail is technical ("room not in current location") and only ever reaches
 *  the console. Callers tell the two apart by `reason` — an empty one means
 *  there is nothing worth showing. */
async function refusal(res: Response): Promise<ApiError> {
  let detail: unknown = null;
  try {
    const body = await res.json();
    detail = (body && typeof body === 'object' && 'detail' in body) ? body.detail : body;
  } catch { /* error without a body — status alone has to do */ }
  const obj = detail && typeof detail === 'object' ? detail as Record<string, unknown> : null;
  const message = typeof detail === 'string' ? detail
    : typeof obj?.message === 'string' ? obj.message
      : `HTTP ${res.status}`;
  return new ApiError(res.status, message, typeof obj?.reason === 'string' ? obj.reason : '');
}

export type StepDirection = 'north' | 'south' | 'east' | 'west';

/** One grid step of the avatar. Throws an `ApiError`: 403 = party follower,
 *  entry-room gate or block rule (message written for the player), 404 = no
 *  location in that direction. `signal` lets the caller put a deadline on the
 *  request — the client allows only ONE step in flight, so a request that
 *  never answers would bar every cell boundary until the page is reloaded. */
export async function avatarStep(direction: StepDirection, signal?: AbortSignal
): Promise<{ location_id: string; room_id?: string }> {
  const res = await fetch('/world/avatar/step', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ direction }),
    signal,
  });
  if (!res.ok) throw await refusal(res);
  return res.json();
}

/** Move the avatar into another room of its current location — the same call
 *  the HUD's room chips make. Throws an `ApiError` on any refusal (a rule, a
 *  room the server does not have at this location). Whether that is shown is
 *  the caller's call: the room walk stays silent (the next poll shows what
 *  holds), the elevator ride announces a refusal that carries a `reason` —
 *  today `/play/enter-room` writes one for `party_follower` only, every other
 *  refusal is technical text and stays out of the player's face. `signal` lets
 *  the caller put a deadline on it: only ONE room change may be in flight, so
 *  a request that never answers would bar every further one until reload. */
export async function enterRoom(roomId: string, signal?: AbortSignal): Promise<void> {
  const res = await fetch('/play/enter-room', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ room_id: roomId }),
    signal,
  });
  if (!res.ok) throw await refusal(res);
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

/** Music and ambience the server has on disk (`app/routes/game_audio.py`).
 *  Empty when the route is missing or the request fails — audio is decoration,
 *  and a client that throws its start away because a folder is empty would be
 *  the worse bug. The shape is validated by `readManifest` (pure, checked in
 *  scripts/smoke_walk_math.mjs), so callers always get two music buckets and a
 *  plain terrain map. */
export async function getAudioManifest(): Promise<AudioManifest> {
  try {
    const res = await fetch('/assets/audio');
    if (!res.ok) return emptyManifest();
    return readManifest(await res.json());
  } catch {
    return emptyManifest();
  }
}

// --- Spoken lines (E4-T6) ----------------------------------------------------

/** Does this world speak at all (`GET /tts/status` → `enabled`, i.e.
 *  `config.tts.enabled`)? Asked ONCE when the HUD mounts. `false` on any
 *  failure: a client that cannot reach the status must stay silent rather than
 *  fire a render request per line into nothing. */
export async function ttsStatus(): Promise<boolean> {
  try {
    const res = await fetch('/tts/status');
    if (!res.ok) return false;
    const data = await res.json();
    return !!data?.enabled;
  } catch {
    return false;
  }
}

/**
 * Render one spoken line and return the URL of the audio, or `''` when there is
 * nothing to play. Never throws — a world without a voice is a world one can
 * still play in, so every failure (TTS off, backend down, no speakable text
 * after the server's cleanup) is the same empty string.
 *
 * `characterName` picks the VOICE: the server looks the character's TTS config
 * up itself (`app/routes/tts.py`) — but only when `user_id` is non-empty as
 * well (`if user_id and character_name` there), so leaving it out would give
 * every character the world's default voice. It is the logged-in user, the same
 * identity `mountHud` already carries.
 */
export async function ttsSpeak(text: string, characterName: string,
                               userId: string): Promise<string> {
  try {
    const res = await fetch('/tts/speak', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, user_id: userId, character_name: characterName }),
    });
    if (!res.ok) return '';
    const data = await res.json();
    return typeof data?.audio_url === 'string' ? data.audio_url : '';
  } catch {
    return '';
  }
}

export interface ApiModel {
  url: string;
  /** identity of this particular model (changes e.g. with the outfit) */
  signature?: string;
  format: 'glb' | 'fbx';
  /** "mixamo" = the clip library applies; "generic" = own skeleton (animals) */
  rig: 'mixamo' | 'generic' | string;
  /** FBX case only: the texture, stored separately */
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
    // Identität der AUSGELIEFERTEN Datei (Server kann bei unbekannter
    // Kombination das nächstliegende Modell servieren): wechselt auch dann,
    // wenn das exakte Mesh später fertig wird und den Nearest-Treffer ablöst.
    signature: m.signature ?? m.filename ?? data.signature,
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
  ScenePayload, ScenePlate, SceneWall, SceneExtra, SceneModelSpec, SceneTerrain,
  SceneMarker, SceneExit, SceneStyle, SceneRoom, ModelTier, SceneBoundaryOpening,
  SceneDoorway, SceneProblem,
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
    // Modelle wandern unveraendert durch: `variants` je Stufe (§ B1) statt
    // einer festen URL — welche Stufe geladen wird, entscheidet der Renderer
    // ueber pickVariant(), nicht diese Schicht.
    models: arr<SceneModelSpec>(data.models),
    figures: data.figures ?? { base_height_m_world: 1.7, stand_clearance: 0.12 },
    markers: arr<SceneMarker>(data.markers),
    exits: arr<SceneExit>(data.exits),
    // Thresholds as finished primitives (plan-betreten-und-tueren.md § 4.1):
    // they pass through untouched — nothing here clamps, scales or measures a
    // door, that is the whole point of the block.
    doorways: arr<SceneDoorway>(data.doorways),
    // Findings of the composer (plan-betreten-und-tueren.md § 4.3) — the
    // client SHOWS them, it never re-derives or repairs one.
    problems: arr<SceneProblem>(data.problems),
    outdoor_rooms: arr<string>(data.outdoor_rooms),
    // Boundary pass-throughs (§ B1 Nr. 13) — the entry proximity of the
    // "Betreten" offer reads them; absent stays absent (no empty-array alias).
    boundary_openings: Array.isArray(data.boundary_openings)
      && data.boundary_openings.length
      ? (data.boundary_openings as SceneBoundaryOpening[]) : undefined,
    // Höhenfeld (§ B1 Nr. 14) — nur bei Relief-Locations im Payload. Ein
    // Gitter ohne Zeilen ist kein Relief, sondern eine kaputte Antwort.
    terrain: Array.isArray(data.terrain?.grid) && data.terrain.grid.length > 1
      ? (data.terrain as SceneTerrain) : undefined,
    // Detail-Modus der Location (v5.2 Nr. 10) — gilt auch ohne Modell.
    area_detail: data.area_detail === true ? true : undefined,
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
  /** Die ID — road | grass | water | coast | ... (offen, wie terrain). Klein,
   *  ohne Leerzeichen, unveraenderlich; das ist der Wert, den terrain und die
   *  Bodenarten referenzieren. */
  kind: string;
  /** Anzeigetext der Art (Vertrag § A9). Der Client zeigt ihn, wo er Arten
   *  benennt; fehlt er, ist die ID als Woerter zu lesen. */
  name?: string;
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
