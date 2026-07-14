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
  format: 'glb' | 'fbx';
  /** "mixamo" = Clip-Bibliothek anwendbar; "generic" = eigenes Skelett (Tiere) */
  rig: 'mixamo' | 'generic' | string;
  /** nur im FBX-Fall: separat gespeicherte Textur */
  textureUrl?: string;
}

/** Modell-Info eines Charakters; null wenn der Server keins hat (404). */
export async function getCharacterModel(name: string): Promise<ApiModel | null> {
  try {
    const res = await fetch(`/characters/${encodeURIComponent(name)}/model3d`);
    if (!res.ok) return null;
    const data = await res.json();
    const m = data?.model;
    if (!m?.url) return null;
    return {
      url: m.url,
      format: (m.format ?? 'glb') as 'glb' | 'fbx',
      rig: m.rig ?? data.rig ?? 'mixamo',
      textureUrl: m.texture_url ?? undefined,
    };
  } catch {
    return null;
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
