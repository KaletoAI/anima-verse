import type {
  AtLocationChar, AuthUser, PosReport, TerrainPayload, WorldLocation, WorldMap,
} from './types';
// Imported locally as well: the re-export further down only exposes the types
// outwards, the parsing helpers here need them in their own scope.
import type {
  SceneBoundaryOpening, SceneDoorway, SceneExtra, SceneMarker,
  SceneFloor, SceneModelSpec, ScenePayload, ScenePlate, SceneProblem,
  SceneRoom, SceneWall, TerrainLayerBatch, TerrainLayerIndex,
  WorldHeightField,
} from '@anima/scene-render';
// The audio manifest is TYPED and validated in the pure soundtrack module, so
// the choosing side and the fetching side cannot drift apart (E4-T5).
import { emptyManifest, readManifest, type AudioManifest } from './game/soundtrack';

/**
 * The session is gone (401) — NOT a server that cannot be reached.
 *
 * The two used to be one generic `Error`, and every caller that catches
 * broadly (the worldmap poll) reported the expired session as "backend
 * unreachable": a red dot over a running server. `floorplan.ts` tells them
 * apart the same way, by status.
 */
export class AuthError extends Error {
  constructor() {
    super('not signed in');
    this.name = 'AuthError';
  }
}

/** True for the one failure that needs a login rather than a retry. */
export function isAuthError(e: unknown): e is AuthError {
  return e instanceof AuthError;
}

async function json<T>(res: Response): Promise<T> {
  // Announced to the whole app, once per failing call: `main.ts` listens and
  // brings the title screen's login form up. Same event name the shared
  // package fires (`@anima/player-ui` api.ts), so ONE listener covers the
  // HUD's own calls as well.
  if (res.status === 401) {
    window.dispatchEvent(new CustomEvent('auth:required'));
    throw new AuthError();
  }
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
  /** The point the server considers the LAST VALID one, when the refusal
   *  carries it (`POST /play/pos`). The caller snaps the figure back onto it —
   *  a refusal that left the two views disagreeing would be worse than the
   *  refusal itself. `null` whenever the server sent none. */
  pos: { x: number; z: number } | null;
  /** The location that point belongs to, '' for the open world. */
  locationId: string;
  constructor(status: number, message: string, reason = '',
              pos: { x: number; z: number } | null = null, locationId = '') {
    super(message);
    this.status = status;
    this.reason = reason;
    this.pos = pos;
    this.locationId = locationId;
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
  const raw = obj?.pos;
  const pos = raw && typeof raw === 'object'
    && typeof (raw as Record<string, unknown>).x === 'number'
    && typeof (raw as Record<string, unknown>).z === 'number'
    ? { x: (raw as { x: number }).x, z: (raw as { z: number }).z } : null;
  return new ApiError(res.status, message,
    typeof obj?.reason === 'string' ? obj.reason : '', pos,
    typeof obj?.location_id === 'string' ? obj.location_id : '');
}

/** The answer of `GET /account/characters`: which characters this account may
 *  take over. The server has already narrowed the list twice — to the ones
 *  whose template carries `playable_avatar`, and (for a non-admin) to the
 *  account's `allowed_characters` — so the client shows it as it comes. */
export interface PlayableCharacters {
  characters: string[];
  /** the one the account controls right now, `''` when none is set */
  active_character: string;
  /** the one a fresh login starts on — not shown, but part of the answer */
  default_character: string;
}

/** The characters the player may take over (`GET /account/characters`).
 *  Read when the game menu opens, not polled: the set changes with the
 *  world's cast, not with the frame. */
export async function listPlayableCharacters(): Promise<PlayableCharacters> {
  return json<PlayableCharacters>(await fetch('/account/characters'));
}

/** The answer of `POST /account/switch-character`. */
export interface SwitchedCharacter {
  status: string;
  /** who the account controlled before — that character turns autonomous again */
  previous_character: string;
  active_character: string;
}

/**
 * Take over another character (`POST /account/switch-character`).
 *
 * Throws an `ApiError` carrying the SERVER's reason for every refusal it
 * writes for this call — no access (403), not an avatar (400), unknown (404).
 * That text names the character and the rule, so the caller shows it as it is
 * instead of guessing from the status code.
 *
 * The caller reloads the page afterwards: avatar, role and the whole known-
 * places view of the running world belong to the character that was left.
 */
export async function switchCharacter(name: string): Promise<SwitchedCharacter> {
  const res = await fetch('/account/switch-character', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ character_name: name }),
  });
  if (res.status === 401) {
    window.dispatchEvent(new CustomEvent('auth:required'));
    throw new AuthError();
  }
  if (!res.ok) throw await refusal(res);
  return res.json() as Promise<SwitchedCharacter>;
}

// `avatarStep` lived here: one compass step of the avatar over
// `POST /world/avatar/step`. The route was deleted with the grid world (E3)
// and `postPos` below has replaced it (E4 task 5) — the client no longer asks
// for permission per boundary, it walks and reports.

/**
 * Report where the avatar is standing (`POST /play/pos`, E4 task 5).
 *
 * The whole movement channel of free walking: the client walks the figure
 * itself and sends the result ~3 times a second while it moves plus once when
 * it stops. The server judges the point (step plausibility, terrain, and the
 * FULL entry/exit gate when the point derives another location) and answers
 * with what it stored.
 *
 * Three answers are normal and none of them is an error: an accepted report
 * (`ok: true`), a throttled one (`ok: false, throttled: true`, the server
 * takes ~4 a second) and a stale one (`ok: false, stale: true`, below).
 * Everything else throws an `ApiError` whose `pos` is the last valid point —
 * the caller snaps the figure back onto it and shows `message`.
 *
 * `signal` puts a deadline on it: reports are frequent and a request that
 * never answers must not tie the next one up.
 *
 * `seq` and `tMs` are the ORDERING PAIR (2026-08-23, § A15): `seq` counts the
 * reports of this session, `tMs` is `performance.now()` at the moment the
 * report was taken. They exist because a request we ABORTED on the deadline
 * keeps running on a stalled server: without them that leftover is processed
 * late, becomes the server's "last valid point" and every fresh report is
 * judged against a point seconds behind the figure — the snap-back loop. With
 * them the server drops the leftover (`stale`) and measures the step against
 * the time that really passed while walking, not between two handler runs.
 */
export async function postPos(x: number, z: number, signal?: AbortSignal,
  seq?: number, tMs?: number
): Promise<PosReport> {
  const res = await fetch('/play/pos', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ x, z, seq, t_ms: tMs }),
    signal,
  });
  if (res.status === 401) {
    window.dispatchEvent(new CustomEvent('auth:required'));
    throw new AuthError();
  }
  if (!res.ok) throw await refusal(res);
  return res.json() as Promise<PosReport>;
}

/** The avatar's pose and PLACE (`POST /play/self/activity`,
 *  plan-posen-plaetze.md § 4). `{activity: ''}` clears pose and place — the
 *  figure stands up (sent on the first steering input while seated);
 *  `{place_id, pose}` seats the avatar on a place (409 when it is taken).
 *  Throws an `ApiError` carrying the server's reason on every refusal. */
export async function postActivity(body: { activity?: string; place_id?: string; pose?: string }
): Promise<{ ok: boolean; place: unknown }> {
  const res = await fetch('/play/self/activity', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (res.status === 401) {
    window.dispatchEvent(new CustomEvent('auth:required'));
    throw new AuthError();
  }
  if (!res.ok) throw await refusal(res);
  return res.json() as Promise<{ ok: boolean; place: unknown }>;
}

/** The painted terrain of the world (`GET /play/terrain`): the areas plus the
 *  effective type catalog they name. NEVER withheld — terrain is always
 *  visible, only locations hide, so this is fetched ONCE and refetched when
 *  the worldmap poll reports a different `terrain_sig`.
 *
 *  Throws like every other game call: the ground is not decoration, and a
 *  client that swallowed the failure would paint the whole world in the
 *  default kind and look right while being wrong. */
export async function fetchTerrain(): Promise<TerrainPayload> {
  return json<TerrainPayload>(await fetch('/play/terrain'));
}


/** The avatar's EXPLORATION MEMORY (`GET /play/explored`, § A12): the 64 m
 *  cells it has already stood in, as `"cx,cz"` keys, plus the signature the
 *  worldmap poll carries. */
export interface ExploredPayload {
  cells: string[];
  sig: string;
}

/** The ground the avatar has walked (`GET /play/explored`, § A12) — what the
 *  veil spares (`scene/fogVeil.ts`).
 *
 *  Fetched exactly like the terrain and the relief, on its own signature
 *  (`WorldMap.explored_sig`): the list is complete and flat, which is
 *  affordable a few times per session and would not be on a three-second poll.
 *
 *  Throws like every other game call — but the CALLER treats a failure as "no
 *  memory yet" rather than as a broken world: a veil that still covers walked
 *  ground is last week's picture, not a wrong one, and the FIGURES on that
 *  ground are filtered by the server anyway. */
export async function fetchExplored(): Promise<ExploredPayload> {
  return json<ExploredPayload>(await fetch('/play/explored'));
}

/** The world RELIEF (`GET /play/heightfield`, § A16): a grid of support points
 *  in world metres. Fetched and refetched exactly like the terrain, on its own
 *  signature (`WorldMap.height_sig`) — it is by far the largest thing the map
 *  has (up to ~1 MB) and has no business in a three-second poll.
 *
 *  Throws like the terrain call, and for the same reason: a client that
 *  swallowed the failure would drape the world flat and look right while
 *  standing figures in the air. */
export async function fetchHeightfield(): Promise<HeightfieldPayload> {
  return json<HeightfieldPayload>(await fetch('/play/heightfield'));
}

/**
 * The overview payload plus the TILE INDEX it carries since v2 (§ A16.3).
 *
 * The index is the loader's business and not the sampler's, which is why it
 * lives here and not in `WorldHeightField`: a tile that does not exist and one
 * that has not arrived yet read exactly the same to the sampler, so carrying
 * the index into the shared package would only add a second state that can go
 * stale.
 */
export interface HeightfieldPayload extends WorldHeightField {
  /** Edge length of a tile in metres — 256 today, and never a constant in the
   *  client: the tile size is a server decision. */
  tile_m: number;
  /** The step INSIDE a tile, always the fine one (4 m) however coarse the
   *  overview above may have become. */
  tile_step_m: number;
  /** Every tile the world has a ground in, as `"tx,tz"`. Anything outside this
   *  list is flat and is never asked for. */
  tiles: string[];
  /** The mip levels a tile reports an error for, in metres — `[4, 8, 16, 32,
   *  64]` today (E1 addendum § 4, § G2). They are multiples of `tile_step_m`
   *  AND divide the tile edge, so each coarse lattice is a SUBSET of the base
   *  one: a client may derive them by plain decimation and still be reading
   *  the server's own height function. */
  mip_levels_m?: number[];
  /** Per tile, `"tx,tz"` → what the terrain quadtree needs about it. Capped at
   *  the server's `TILE_STATS_MAX`; the rest arrives with the tiles. */
  tile_stats?: Record<string, HeightTileStats>;
  /** `false` when `tile_stats` was cut short by that cap. */
  tile_stats_complete?: boolean;
}

/** What one tile says about ITSELF (§ G2): its height span, and the exact
 *  largest VERTICAL error in metres a renderer makes by drawing it on
 *  `mip_levels_m[k]` instead of on the base lattice. Exact rather than
 *  sampled — the difference of two bilinear fields is bilinear and takes its
 *  extrema in the corners — which is what lets a screen-space error test be a
 *  guarantee. */
export interface HeightTileStats {
  min: number;
  max: number;
  err: number[];
}

/** One tile's grid as the batch endpoint sends it — WITHOUT a `step_m` of its
 *  own: every tile in a batch shares the one at the top level, and the caller
 *  merges it in (`ground.ts`). */
export interface HeightTileGrid {
  origin_x: number;
  origin_z: number;
  rows: number;
  cols: number;
  heights: number[][];
  /** The tile's own quadtree statistics (§ G2) — always present since E1, and
   *  the reason `GET /play/heightfield` may cap its `tile_stats`: whatever the
   *  overview could not carry rides in here. */
  stats?: HeightTileStats;
  /** The WATER field of the same window (Wasser v2 K-A E1, § A16.5). ABSENT
   *  for a tile without a drop of water in it, which is most tiles of most
   *  worlds — the key is never an empty raster. */
  water?: WaterTileGrid;
}

/**
 * The second field of a height tile: the world's water, on the tile's own
 * lattice (Wasser v2 K-A E1).
 *
 * `level[j][i]` is the local mirror in metres at the same support point
 * `heights[j][i]` describes — or `null` where the point carries no water. That
 * null is the ONLY mask this raster has, and it is not the outline: the server
 * writes the level two lattice steps PAST every outline (its dilation), so a
 * bilinear read anywhere INSIDE a water polygon meets four defined corners. A
 * `null` therefore means "far enough from any water that no reading needs this
 * texel", never "the shore is here".
 *
 * `flow_x`/`flow_z` are the downstream vector at that point: the axis tangent,
 * blended through the knots, times the area's speed factor. They are OMITTED
 * TOGETHER where the whole tile has no flow — every lake, every ice sheet —
 * because a still water's vector is exactly (0, 0) everywhere and two lattices
 * of zeros would double the tile's payload to say nothing. Absent reads as
 * "(0, 0) everywhere".
 */
export interface WaterTileGrid {
  level: (number | null)[][];
  /** The SIGNED distance to the authored outline of the water `level` comes
   *  from, in metres — positive inside it, negative in its dilation ring,
   *  `null` on exactly the texels `level` is null on (bake v9).
   *
   *  IT IS THE MASK `level` IS NOT. The level is written 4 m past every
   *  outline so a bilinear read inside a polygon always meets four defined
   *  corners; that dilation is what floods the bank if the level is read as
   *  "here is water". Only this field says where the author drew the water, and
   *  the renderer gates BOTH the vertex lift and the water shading on it. */
  sd?: (number | null)[][];
  flow_x?: number[][];
  flow_z?: number[][];
}

/** The answer of `GET /play/heightfield/tiles`. `tiles` holds only what the
 *  index knows — keys it does not are simply absent, which is the same
 *  statement as "flat there" and costs neither a raster nor a kilobyte. */
export interface HeightTileBatch {
  sig: string;
  tile_m: number;
  step_m: number;
  tiles: Record<string, HeightTileGrid>;
  /** The same level list the overview carries — repeated so a batch is
   *  readable on its own. */
  mip_levels_m?: number[];
}

/**
 * A batch of FINE height tiles (`GET /play/heightfield/tiles`, § A16.3) — the
 * ground every rule reads and the near view is draped with.
 *
 * At most `HEIGHT_TILE_BATCH_MAX` keys per call; the server drops the rest with
 * a one-shot warning, so `scene/heightTiles.tileBatches` splits before asking.
 * The keys are the client's own `"tx,tz"` (`tileKeyAt`), the wire wants
 * `tx:tz,tx:tz` — the comma is the separator BETWEEN keys there, so the pair
 * has to be spelled with a colon.
 *
 * Throws like the two calls above: a swallowed failure would drape the near
 * ground from the coarse overview and look perfectly fine while standing
 * figures beside the hill they are walking on.
 */
export async function fetchHeightTiles(keys: readonly string[]
): Promise<HeightTileBatch> {
  const query = keys.map((k) => k.replace(',', ':')).join(',');
  return json<HeightTileBatch>(
    await fetch(`/play/heightfield/tiles?keys=${encodeURIComponent(query)}`));
}

/** The answer of `GET /play/heightfield/stats` — statistics only, no grids.
 *  Keys the index does not know are simply absent, exactly as in the tile
 *  batch. */
export interface HeightTileStatsBatch {
  sig: string;
  tile_stats: Record<string, HeightTileStats>;
}

/**
 * The per-tile STATISTICS of a set of tiles (`GET /play/heightfield/stats`,
 * § G2) — without their grids, and therefore without their kilobytes.
 *
 * The overview caps `tile_stats` at the server's `TILE_STATS_MAX` = 64 and
 * says so through `tile_stats_complete`. The terrain quadtree takes its worst
 * vertical error PER LEVEL over every tile it holds a statistic for, so on a
 * world with more than 64 tiles that maximum is too small and the distant
 * ground is drawn coarser than the error budget allows. This call fetches the
 * remainder in the background (`scene/ground.ts`).
 *
 * At most `HEIGHT_TILE_BATCH_MAX` keys per call — and unlike the tile batch
 * the server REFUSES a longer one (400) rather than trimming it, because a
 * silently missing statistic reads as "complete" on this side. Same key
 * spelling as `fetchHeightTiles`: `"tx,tz"` here, `tx:tz` on the wire.
 *
 * Throws like the calls above; the caller keeps what it has and asks again.
 */
export async function fetchHeightTileStats(keys: readonly string[]
): Promise<HeightTileStatsBatch> {
  const query = keys.map((k) => k.replace(',', ':')).join(',');
  return json<HeightTileStatsBatch>(
    await fetch(`/play/heightfield/stats?keys=${encodeURIComponent(query)}`));
}

/**
 * The LAYER CUT of the ground (`GET /play/terrain-layers`, § G3) — the baked
 * masks the terrain material composites its material out of.
 *
 * TWO MODES, ONE CALL, because they are two halves of the same window:
 * WITHOUT keys the server answers the INDEX (the layer table, the coarse
 * world-wide id mask and every tile a painted shape reaches into); WITH keys it
 * answers the FINE masks of those tiles. The keys are the client's own
 * `"tx,tz"` — the very keys the height tiles use, so one want-set steers both
 * windows — and the wire wants `tx:tz` because the comma separates keys there.
 *
 * Throws like the three calls above. A swallowed failure would paint the whole
 * world in the default kind and look perfectly fine while being wrong about
 * every wood, path and shore in it.
 */
export async function fetchTerrainLayers(keys: readonly string[] = []
): Promise<TerrainLayerIndex | TerrainLayerBatch> {
  if (!keys.length) {
    return json<TerrainLayerIndex>(await fetch('/play/terrain-layers'));
  }
  const query = keys.map((k) => k.replace(',', ':')).join(',');
  return json<TerrainLayerBatch>(
    await fetch(`/play/terrain-layers?keys=${encodeURIComponent(query)}`));
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
  /** `a`/`b` for the half of a PAIR clip (`<kind>__a`), empty for a solo clip */
  role?: string;
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
 *  client3d/scripts/smoke_walk_math.mjs), so callers always get two music buckets and a
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
  /** true = the file already stands its real height on the ground (server-side
   *  normalisation). The client must NOT rescale it by the bounding box —
   *  hair above the crown would shrink the body again. */
  normalized?: boolean;
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
    normalized: !!m.normalized,
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
  ScenePayload, ScenePlate, SceneWall, SceneExtra, SceneModelSpec, SceneFloor,
  SceneMarker, SceneStyle, SceneRoom, ModelTier, SceneBoundaryOpening,
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
    // THE STOREY-0 ROOMS AS DATA (§ A19 no. 3) — what replaced the storey-0
    // plates. Same defensiveness as `plates`: a hull of fewer than three points
    // encloses nothing, so it names no floor.
    floor_plan: arr<SceneFloor>(data.floor_plan)
      .filter((f) => arr(f.polygon_world).length >= 3),
    walls: arr<SceneWall>(data.walls),
    extras: arr<SceneExtra>(data.extras),
    // Modelle wandern unveraendert durch: `variants` je Stufe (§ B1) statt
    // einer festen URL — welche Stufe geladen wird, entscheidet der Renderer
    // ueber pickVariant(), nicht diese Schicht.
    models: arr<SceneModelSpec>(data.models),
    figures: data.figures ?? { base_height_m_world: 1.7, stand_clearance: 0.12 },
    markers: arr<SceneMarker>(data.markers),
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
    // Detail-Modus der Location (v5.2 Nr. 10) — gilt auch ohne Modell.
    area_detail: data.area_detail === true ? true : undefined,
    // `terrain` and `natural_floor` ARE NOT READ ANY MORE (E5a, § A19 no. 1
    // and no. 6): the scene's own 17 x 17 relief is deleted, and "this
    // location stands on the terrain" is true of every location now.
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

// The world's time of day has NO fetch of its own any more: the worldmap
// payload carries the rendered world clock (`game_time`, § A11) on the poll
// that runs every 3 s regardless, and `main.ts` takes the sun's hour from
// there. One source, and no client ever parses a game stamp.
