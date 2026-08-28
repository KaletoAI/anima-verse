import * as THREE from 'three';
import { CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';
import type { MapCharacter, MapInteraction } from '../types';
import { bubbleMs, bubbleText } from '../game/bubble';
import { MOVE_EPS_M, SWIM_FROM_DEFAULT_M, floatRootY, groundSink,
  ghostCutY, groundWaterLevel, idleClip, moveClip, sinkForState, terrainPace, wadeGate,
  type GroundScope, type GroundSink } from '../game/walk';
import { Figure, FigureLibrary } from './figures';
import { GROUND_Y } from './ground';
import type { PlaceEntry } from './placeSlot';
import { seededRandom } from './textures';
import { advanceProgress, catchUpStep, clampProgress, deadReckonRate, deadReckonStep, densifyPolyline, pointAtDistance, remainingPoints, shouldSnap, trimBucket, type MetrePoint } from './travelPath';

/** Walking pace in METRES PER SECOND — and since E4 that is all it is: the
 *  metre world has one scale, so this number means the same thing on the map
 *  and inside a room. Exported because the player-driven avatar (E3-T3) has to
 *  move at exactly the NPC pace; a second constant would drift. */
export const WALK_SPEED = 3.4;
const RUN_DISTANCE = 6; // farther than this -> run animation

/** What the ground says about a figure at one point: the clip its terrain type
 *  asks for while the figure MOVES (`anim`) and the one while it STANDS
 *  (`idle`) — `''` for either means "the ground says nothing" — plus how far
 *  the terrain rule reaches there (§ A1.5). All three are LOOKUPS the driver
 *  hands in: `main.ts` owns the terrain payload and the footprints, this file
 *  owns neither. */
export interface GroundMove {
  anim: string;
  idle: string;
  scope: GroundScope;
  /** The terrain type's raw `speed_factor` at the point (1 = plain ground).
   *  RAW: what it means for a walking figure is `walk.terrainPace`, which
   *  needs the `scope` beside it — a built place replaces the ground with its
   *  own floor whatever the catalog holds there. Only the figures that walk
   *  by their own reckoning read it (a fogged traveller, see `deadReckonStep`);
   *  the avatar's pace is read in `main.ts`, where the same lookup happens for
   *  the same reason. */
  speed: number;
  /** The ground's two depths in metres (`meta.move_sink_m` /
   *  `meta.idle_sink_m`, 0 = nothing sinks) — how deep the figure stands IN it
   *  while it moves and while it waits. Which one counts is `sinkForState`. */
  sink: GroundSink;
  /** The MIRROR height over the point in world metres, or `null` where the
   *  point is not water (E4, § G4; local since W2: the topmost area's
   *  `meta.water_profile`, evaluated AT this point — over a river the water
   *  line is a different height at every metre of its length).
   *  A figure hangs its sink under THIS, not under the carved bed —
   *  `walk.floatRootY` is the one place that says so, for travellers, NPCs and
   *  the player's avatar alike. */
  water: number | null;
  /** FROM WHICH WATER DEPTH the four fields above count at all
   *  (`meta.swim_from_m`, W4c) — shallower water is WADED, and then the ground
   *  says nothing: the figure keeps its own clips, sinks by nothing and stands
   *  on the bed. `walk.wadeGate` is the one place that applies it. */
  swimFrom: number;
}
/** Selection marker (E3-T1): the gold of the client's chrome (top bar, info panel). */
const SELECT_COLOR = 0xf2d98c;
/** Walk-target marker (E3-T4): the same gold, but a thin flat ring on the
 *  ground — it marks a place, not a figure. */
const WALK_TARGET_RADIUS = 0.55;

function ringColor(name: string): string {
  const rnd = seededRandom(name);
  return `hsl(${Math.floor(rnd() * 360)}, 65%, 55%)`;
}

/** Round portrait with a coloured ring as sprite texture; loads the avatar image lazily. */
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
  /** AV3D-6: the animation category the server delivered (authoritative) */
  animation?: string;
  root: THREE.Group;
  figure: Figure | null;
  ring: THREE.Mesh | null;
  sprite: THREE.Sprite | null;
  label: CSS2DObject;
  labelName: HTMLSpanElement;
  labelActivity: HTMLSpanElement;
  /** speech bubble above the name — empty and hidden unless someone speaks */
  labelBubble: HTMLDivElement;
  /** `performance.now()` at which the bubble is taken down again (0 = down) */
  bubbleUntil: number;
  target: THREE.Vector3;
  /** Pace of the NEXT step, as the ground under this figure sets it
   *  (`walk.terrainPace`, 1 = the plain `WALK_SPEED`). Only the player-driven
   *  figure ever carries something else: `setPlayerTarget` hands it in with
   *  the goal, because the goal is set from the CURRENT position every frame
   *  and a paced goal would fall under `MOVE_EPS_M` and freeze the figure
   *  (swim finding 2026-08-13). Server-driven journeys bring their own rate
   *  and never look at this. */
  pace: number;
  /** feste Blickrichtung im Stand (Marker) — sonst Nachbarn ansehen */
  face: THREE.Vector3 | null;
  /** Restliche Wegpunkte bis zum Ziel (Wegfindung um Gebäude) */
  waypoints: THREE.Vector3[];
  /** server journey being followed (§ A11) — replaces goal/waypoint logic.
   *  `key` identifies the POLYLINE: as long as it is unchanged the local
   *  `progressM` keeps running and only reconciles against a fresh poll; a new
   *  key is a new journey and is adopted whole. */
  route: (TravelRoute & { key: string }) | null;
  /** the payload says this figure is on a JOURNEY (`char.travel`) — true for a
   *  fogged traveller as well, which is the one that has no `route` (§ A12) */
  travelling: boolean;
  /** DEAD RECKONING of a traveller without a route (§ A12, decision
   *  `77dbdb61`): the last POLLED point, the real second it was seen at, the
   *  poll stamp it belonged to, and the rate measured against the point
   *  before it. `null` for everyone who is not such a figure. */
  reckon: { pos: MetrePoint; atS: number; stamp: number; rateMS: number | null } | null;
  /** running pair interaction (§ A8a) — placement AND clip come from it */
  interaction: PairPlay | null;
  activity: string;
  travelLine: THREE.Line | null;
  travelKey: string;
  bobPhase: number;
}

/** A journey as the renderer needs it (contract § A11): the metre polyline,
 *  the one number that walks it, and the rate it walks at. */
export interface TravelRoute {
  /** `travel.waypoints` — world points `[x, z]` in METRES, start to goal */
  points: MetrePoint[];
  /** arc length of `points`, measured by the client (`polylineLength`) */
  totalM: number;
  /** metres already walked along the polyline (`travel.progress_m`) */
  progressM: number;
  /** metres per REAL second: `pace_m_s_real ?? speed_m_s_real`. `null` means
   *  do not extrapolate at all — frozen world, arrived, degenerate segment. */
  rateMS: number | null;
  /** which worldmap poll the numbers came from; the progress reconciliation
   *  only runs against a genuinely NEW payload */
  stamp: number;
}

/** A pair interaction as the renderer runs it (§ A8a): the anchor the two
 *  halves are placed at, and ONE number — the clip time in GAME seconds —
 *  advanced locally at `rate` and reconciled against each new poll. */
export interface PairPlay {
  id: string;
  /** `<kind>__<role>` — the clip half this figure plays */
  clip: string;
  /** `placeId`: the place the server seated the pair on (§ A8a) — the
   *  figures stand at its slot height, not on the ground; null = halfway
   *  on the ground. */
  anchor: { x: number; z: number; yaw: number; placeId: string | null };
  /** interaction time in game seconds */
  elapsed: number;
  duration: number;
  /** the clip's own length — a looping clip replays every clipDuration */
  clipDuration: number;
  loop: boolean;
  /** game seconds per real second (0 = frozen) */
  rate: number;
  stamp: number;
}

/** Beyond this drift (clip seconds) a fresh poll snaps the local clip time. */
export const PAIR_SNAP_S = 0.3;

/** Identity of a polyline — same points, same journey. */
function routeKey(points: MetrePoint[]): string {
  return points.map((p) => `${p[0]},${p[1]}`).join(';');
}

export interface NpcState {
  char: MapCharacter;
  pos: THREE.Vector3;               // target position on the map
  /** fixed facing while standing (e.g. from the place marker) */
  face?: THREE.Vector3;
  /** Lean from the marker (degrees): head up/down or tilted sideways — a
   *  figure lying askew on the sand does not stand upright. */
  lean?: { tilt: number; roll: number };
  /** hide the figure (e.g. a storey other than the shown one) */
  hidden?: boolean;
  /** Zwischenstationen (z.B. Raum-Ausgänge bei Raumwechsel, AV3D-2) */
  via?: THREE.Vector3[];
  /** Put the figure at `pos` instead of walking it there. Set for placements
   *  that are not a MOVE at all: the detail view opening or closing (the
   *  character stood in that room before and after — finding B5) and the first
   *  placement of a figure. Ignored for the player-driven figure, whose
   *  position belongs to `main.ts` either way. */
  snap?: boolean;
  /** Running journey (§ A11) — the METRE polyline and the distance walked
   *  along it, built in `main.ts` from `travel.waypoints`/`progress_m`.
   *  Absent for anyone standing still AND for a traveller whose route is
   *  fogged (`waypoints: null`, § A12): then `pos` alone places the figure,
   *  no line is drawn and nothing is extrapolated. The travel line is drawn
   *  from THIS — there is no second field naming a destination. */
  route?: TravelRoute;
  /** Running pair interaction (§ A8a), straight from the worldmap row. */
  interaction?: MapInteraction | null;
  /** which worldmap poll this state came from (reconciliation of `elapsed`) */
  stamp?: number;
}

export class NpcManager {
  group = new THREE.Group();
  private npcs = new Map<string, Npc>();
  private avatarName = '';
  /** name of the picked figure (E3-T1) — the ring follows this, not the mesh */
  private selected: string | null = null;
  private selectRing: THREE.Mesh | null = null;
  /** figure the PLAYER steers (E3-T3); its placement comes from main.ts */
  private playerDriven: string | null = null;
  /** ground ring at the click target of a running walk (E3-T4) */
  private walkTargetRing: THREE.Mesh | null = null;
  /**
   * The WORLD ground under a point (§ A16) — handed in, never derived here.
   *
   * A traveller's position is re-derived from the polyline on every frame
   * (`tick`), so the height has to come with it: the poll's own point is up to
   * a second old and the figure would walk the hill of a metre it has left.
   * The default keeps the flat world of the payload, which is what a client
   * without a relief has always drawn.
   */
  private groundY: (x: number, z: number) => number = () => GROUND_Y;
  /** `Ground.heightRevision` — part of the drawn travel line's identity: the
   *  line is rebuilt only when its key changes, and the relief arrives long
   *  after the first line was drawn. Without it a journey already running
   *  would keep a line on the flat world until the walker's next five-metre
   *  bucket. */
  private groundRev: () => number = () => 0;
  /**
   * What the GROUND says about a figure at a point: the clips its type asks
   * for (`meta.move_anim` and `meta.idle_anim`, § A9) and HOW FAR that rule
   * reaches there (`walk.GroundScope`) — handed in like the height, never
   * derived here.
   *
   * It applies to every figure, the player's avatar included: they all go
   * through the one clip decision below (`moveClip` / `idleClip`), so a lake
   * is swum across by whoever crosses it and trodden by whoever stops in it —
   * and a tiled hall standing in that lake is walked and stood in. The default
   * is the world without painted ground: walk, run and idle as always.
   */
  private groundMoveAt: (x: number, z: number) => GroundMove =
    () => ({ anim: '', idle: '', scope: 'wilderness', speed: 1,
      sink: { move: 0, idle: 0 }, water: null,
      swimFrom: SWIM_FROM_DEFAULT_M });

  /**
   * The PLACE a pair anchor names (§ A8a: `anchor.place_id`), looked up in
   * the character's room by marker id — handed in like the ground height,
   * because the place inventory (`tile.roomMarkers`) lives in `main.ts`.
   * `x`/`z` are the anchor's world metres, which say WHICH tile to ask;
   * marker ids are per room, so the room comes from the character. The
   * default (no inventory) puts the pair on the ground as before.
   */
  private placeAt: (name: string, id: string, x: number, z: number) => PlaceEntry | undefined =
    () => undefined;

  constructor(private figures: FigureLibrary | null = null) {}

  /** Install the place lookup for pair anchors (see `placeAt`). */
  setPlaceAt(fn: (name: string, id: string, x: number, z: number) => PlaceEntry | undefined) {
    this.placeAt = fn;
  }

  /** Install the world height sampler (`Ground.heightAt`) and the revision of
   *  the field behind it. Called once at boot; the field updates itself. */
  setGroundHeight(fn: (x: number, z: number) => number, revision?: () => number) {
    this.groundY = fn;
    if (revision) this.groundRev = revision;
  }

  /** Install the ground-clip lookup (`main.ts` `groundMoveAt`: the terrain
   *  type's `move_anim` and `idle_anim` plus the scope at that point). Called
   *  once at boot; the payload updates itself. */
  setTerrainMove(fn: (x: number, z: number) => GroundMove) {
    this.groundMoveAt = fn;
  }

  setAvatar(name: string) {
    this.avatarName = name;
  }

  /** Name of the nearest figure under the ray, or null (E3-T1). Hits the whole
   *  `npc.root` hierarchy, so a sprite counts as well as a rigged figure.
   *  Hidden figures (other storey) are excluded — they are not clickable. */
  characterAt(raycaster: THREE.Raycaster): string | null {
    const roots = [...this.npcs.values()].filter((n) => n.root.visible).map((n) => n.root);
    for (const hit of raycaster.intersectObjects(roots, true)) {
      let o: THREE.Object3D | null = hit.object;
      while (o) {
        if (o.userData.charName) return o.userData.charName as string;
        o = o.parent;
      }
    }
    return null;
  }

  /** World position of a figure, or null when it is not on the map (E3-T1). */
  positionOf(name: string): THREE.Vector3 | null {
    return this.npcs.get(name)?.root.position.clone() ?? null;
  }

  /** Scale a figure is DRAWN at, or null when it is not on the map (E3-T5).
   *
   *  Constant 1 since E4: the metre world has ONE scale, so a figure inside a
   *  room is the same 1.70 m it is on the map (k = 1, `figures.setCharacterHeight`
   *  is the only thing that resizes one). It is still read, because the reach
   *  radii that used to shrink with the room (`proximity.ts`, `elevator.ts`)
   *  take the drawn size as their unit — and now simply get 1. */
  scaleOf(name: string): number | null {
    return this.npcs.get(name)?.root.scale.x ?? null;
  }

  /** Hand a figure over to the player (E3-T3), null gives it back to the
   *  server placement. While it is player-driven, `update()` ignores every
   *  PLACEMENT field for it (pos/via/route/scale/face/lean/hidden) — the frame
   *  hook in main.ts owns the position; label, activity and animation keep
   *  following the worldmap. Idempotent: only a real change clears the running
   *  route/waypoints, so the figure does not stutter on repeated calls. */
  setPlayerDriven(name: string | null) {
    if (this.playerDriven === name) return;
    this.playerDriven = name;
    if (!name) return;
    // No figure yet (the model is still loading, or a rebuild threw the group
    // away): nothing to do HERE — `update()` applies the same state the moment
    // it creates the figure, so the takeover is not lost.
    const npc = this.npcs.get(name);
    if (npc) this.takeOver(npc);
  }

  /** Bring a figure into the state a player-driven one has to be in (E3-T3/T6).
   *  Called from `setPlayerDriven` AND from `update()` right after a figure is
   *  created, because the two orders both happen: entering the mode with the
   *  figure on the map, and a model that only arrives afterwards. */
  private takeOver(npc: Npc) {
    npc.route = null;        // a server journey would keep overriding the input
    npc.waypoints = [];      // ditto for a planned A* path
    npc.target.copy(npc.root.position);
    npc.pace = 1;            // the walking hook reads the ground on its first frame
    // The placement fields update() stops writing keep their last value, and
    // two of them are wrong for a steered figure:
    // `face` was the traveller's destination — the avatar would walk while
    // staring at the town it no longer travels to; without it `tick()` falls
    // back to the walking direction and the neighbour gaze, like any NPC.
    npc.face = null;
    // `hidden` was the storey filter. Taking over an avatar on a storey that
    // is currently not displayed left it invisible AND unclickable, with no
    // way back — while the player steers, the figure they steer is visible.
    npc.root.visible = true;
  }

  // THE SECOND SCALE IS GONE (E4 task 3). `setPlayerScale` pulled the
  // player-driven figure to the room scale and `setPlayerSpeed` slowed it down
  // by the same factor, because a world metre inside a room used to be a
  // fraction of a human metre. With k = 1 a metre is a metre everywhere:
  // figures stand at scale 1 indoors and out, and `WALK_SPEED` means 3.4
  // metres a second wherever the avatar walks.

  /** Walk goal of the player-driven figure (E3-T3). Writes `npc.target`, so
   *  `tick()` walks there exactly as it does for any NPC — animation, facing
   *  and ground blending included, no second movement code path. */
  /** Goal of the player-driven figure, plus the PACE the ground under it
   *  allows (`walk.terrainPace`; 1 = the plain `WALK_SPEED`).
   *
   *  The pace belongs to the STEP, never to the goal: `main.ts` sets the goal
   *  a fixed lead ahead of the figure every frame, so scaling the lead
   *  instead would push it under `MOVE_EPS_M` on slow ground and the figure
   *  would stand still with an idle clip instead of swimming slowly (finding
   *  2026-08-13). */
  setPlayerTarget(name: string, pos: THREE.Vector3, pace = 1) {
    const npc = this.npcs.get(name);
    if (!npc) return;
    npc.target.copy(pos);
    npc.pace = Number.isFinite(pace) && pace > 0 ? pace : 1;
  }

  /** Hard placement of the player-driven figure (E3-T3): used when the SERVER
   *  moved the avatar behind the player's back (teleport, party pull, admin) —
   *  that is a jump, not a walk, so the position is set instead of targeted. */
  snapPlayerTo(name: string, pos: THREE.Vector3) {
    const npc = this.npcs.get(name);
    if (!npc) return;
    npc.root.position.copy(pos);
    npc.target.copy(pos);
    npc.waypoints = [];
    npc.route = null;
    // A jump lands on ground nobody has read yet — the pace of the ground the
    // figure stood on a moment ago says nothing about it. The next walking
    // frame supplies the real one.
    npc.pace = 1;
  }

  /** The standing pose of the player-driven figure (plan-posen-plaetze.md
   *  § 4): the facing and lean of the PLACE the server seated it on, or
   *  `null`/`null` when it stands up. `update()` stops writing these for a
   *  steered figure (they are placement decisions of the server view), so
   *  the seat is the one case that has to hand them in from outside — a
   *  seated avatar staring at its neighbours instead of along its chair
   *  would look wrong exactly where every NPC looks right. */
  setPlayerPose(name: string, face: THREE.Vector3 | null,
                lean: { tilt: number; roll: number } | null) {
    const npc = this.npcs.get(name);
    if (!npc) return;
    npc.face = face;
    npc.figure?.setLean(lean?.tilt ?? 0, lean?.roll ?? 0);
  }

  /** Show the goal of a click-to-walk order on the ground (E3-T4); null takes
   *  the marker away again (arrival, cancel, leaving the mode). The ring hangs
   *  in the manager's own group, NOT in a figure — it marks a place. */
  setWalkTarget(pos: THREE.Vector3 | null) {
    if (!pos) {
      if (!this.walkTargetRing) return;
      this.walkTargetRing.removeFromParent();
      this.walkTargetRing.geometry.dispose();
      (this.walkTargetRing.material as THREE.Material).dispose();
      this.walkTargetRing = null;
      return;
    }
    if (!this.walkTargetRing) {
      const ring = new THREE.Mesh(
        new THREE.RingGeometry(WALK_TARGET_RADIUS * 0.72, WALK_TARGET_RADIUS, 32),
        new THREE.MeshBasicMaterial({
          color: SELECT_COLOR, transparent: true, opacity: 0.8, depthWrite: false,
        })
      );
      ring.rotation.x = -Math.PI / 2;
      // Same lesson as the selection marker: a marker must never be its own
      // hit area, or the next click lands on it instead of on the ground.
      ring.raycast = () => {};
      this.group.add(ring);
      this.walkTargetRing = ring;
    }
    this.walkTargetRing.position.set(pos.x, pos.y + 0.06, pos.z);
  }

  /** Mark a figure as selected; null clears the marker (E3-T1). */
  setSelected(name: string | null) {
    this.selected = name;
    this.syncSelectRing();
  }

  /** Keep the marker on the selected figure across rebuilds/removals: the ring
   *  hangs in `npc.root`, and that group is thrown away whenever the model is
   *  reloaded or the character leaves the map. */
  private syncSelectRing() {
    const npc = this.selected ? this.npcs.get(this.selected) : undefined;
    if (this.selectRing && this.selectRing.parent === (npc?.root ?? null)) return;
    if (this.selectRing) {
      this.selectRing.removeFromParent();
      this.selectRing.geometry.dispose();
      (this.selectRing.material as THREE.Material).dispose();
      this.selectRing = null;
    }
    if (!npc) return;
    // Own mesh, deliberately NOT the identity ring: that one carries the
    // per-character colour and only exists for rigged figures.
    const ring = new THREE.Mesh(
      new THREE.RingGeometry(0.85, 1.05, 40),
      new THREE.MeshBasicMaterial({
        color: SELECT_COLOR, transparent: true, opacity: 0.95, depthWrite: false,
      })
    );
    ring.rotation.x = -Math.PI / 2;
    ring.position.y = 0.12;   // above the identity ring (0.09) and the sprite blob (0.08)
    // The marker must not be its own hit area: it hangs in `npc.root`, which
    // `characterAt` raycasts, so a click just BESIDE the figure would land on
    // the ring and re-select instead of clearing the selection.
    ring.raycast = () => {};
    npc.root.add(ring);
    this.selectRing = ring;
  }

  /** Pick the distance tier per figure (view state): full inside `near`,
   *  low beyond `far`; the band between keeps the last state (hysteresis
   *  like the building models in main.ts). The switch itself — a cache hit
   *  or a reload + rebuild — is the FigureLibrary's business; figures
   *  without a server model it ignores. */
  tickFigureTiers(cameraPos: THREE.Vector3, near: number, far: number) {
    if (!this.figures) return;
    for (const [name, npc] of this.npcs) {
      if (!npc.figure) continue;
      // The steered figure is the one thing the player looks at permanently,
      // and the follow camera hovers right around the band — distance
      // switching would rebuild it over and over. Always full.
      if (name === this.playerDriven) {
        this.figures.setFigureTier(name, 'full');
        continue;
      }
      const d = cameraPos.distanceTo(npc.root.position);
      if (d < near) this.figures.setFigureTier(name, 'full');
      else if (d > far) this.figures.setFigureTier(name, 'low');
    }
  }

  /** Drop a figure so the next `update()` builds it again — e.g. when its 3D
   *  model finished loading on the server.
   *
   *  THE ONE DELIBERATE EXCEPTION to the never-remove rule below: this hits
   *  the player-driven figure too, and it is meant to (a new model has to
   *  replace the old one). The figure comes back on the next `update()`, at
   *  the worldmap's point rather than the walked one and re-taken-over there
   *  (`createNpc` + `takeOver`), so a rebuild mid-walk can set the player back
   *  by up to one poll. Not what the guard is about — that one is a MISSING
   *  payload entry, which must never take the figure away at all. */
  rebuild(charName: string) {
    const npc = this.npcs.get(charName);
    if (!npc) return;
    this.group.remove(npc.root);
    this.dropTravelLine(npc);
    // …and the figure's own underwater ghost, whose materials are per figure
    // and whose registration is what isolation toggle 22 walks.
    npc.figure?.dispose();
    npc.label.element.remove();
    this.npcs.delete(charName);
  }

  /** Take a figure's travel line out of the scene AND off the GPU.
   *
   *  Removing it from the group is not enough: the BufferGeometry keeps its
   *  buffers until it is disposed, and both callers throw the whole Npc away
   *  right afterwards, so nothing will ever dispose it later. A rebuild fires
   *  on every model reload and a removal on every figure that leaves the map —
   *  and since E4 the line is the whole route (a polyline, not two points),
   *  so what leaks is bigger than it was. */
  private dropTravelLine(npc: Npc) {
    if (!npc.travelLine) return;
    this.group.remove(npc.travelLine);
    npc.travelLine.geometry.dispose();
    // The dashed material is built per line as well (it carries the dash
    // scale), so it is just as per-line as the geometry — same rule as the
    // selection and walk-target rings above.
    (npc.travelLine.material as THREE.Material).dispose();
    npc.travelLine = null;
    npc.travelKey = '';
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
        npc.root.position.copy(st.pos); // first sync: no walk across the whole map
        // The figure only arrived now, but the player has been steering since
        // before it existed — `setPlayerDriven` found nothing to write then.
        if (st.char.name === this.playerDriven) this.takeOver(npc);
      }
      // Player-driven figure (E3-T3): WHERE it stands belongs to the frame
      // hook in main.ts — pos/via/route/scale/face/lean/hidden are all
      // placement decisions of the server view and would fight the input at
      // 1 Hz. What the worldmap SAYS about the character still applies (name,
      // activity, animation). The travel line is cleared: a player walking on
      // foot has no server journey to draw, and drawing one from `st.pos`
      // would start it where the figure is not.
      this.adoptInteraction(npc, st);
      if (st.char.name === this.playerDriven) {
        npc.activity = st.char.activity || '';
        npc.animation = st.char.activity_animation || undefined;
        npc.labelActivity.textContent = npc.activity;
        npc.labelName.textContent = st.char.name;
        // …and for the same reason it carries no dead reckoning: a figure the
        // player steers walks on the player's input, not on a rate measured
        // between two polls of where the server thought it was.
        npc.travelling = false;
        npc.reckon = null;
        this.updateTravelLine(npc, null);
        continue;
      }
      // Adopt the server journey (§ A11). The RATE and the polyline are
      // authoritative and adopted on every update — a mid-journey freeze must
      // stop the extrapolation immediately, and a rate that changed with the
      // terrain must take effect at once. Only `progressM` is subject to
      // reconciliation, and only against a genuinely NEW worldmap payload
      // (stamp): update() runs at 1 Hz off the cached map, so comparing
      // against a stale payload would snap fast journeys backwards each
      // second. Hard snap when the two are more than TRAVEL_SNAP_M (2 m)
      // apart, otherwise let the local extrapolation keep running — that is
      // what keeps poll jitter out of the figure.
      /** this update ended a journey — the placement below must not re-walk it */
      let arrived = false;
      if (st.route && st.route.points.length >= 2) {
        const key = routeKey(st.route.points);
        if (!npc.route || npc.route.key !== key) {
          // Another polyline is another journey: take it whole, progress
          // included. Counting the points would not do — a new route can have
          // just as many, and the figure would then walk the new line from
          // the old distance.
          npc.route = {
            key,
            points: st.route.points.map((p) => [p[0], p[1]] as MetrePoint),
            totalM: st.route.totalM,
            progressM: st.route.progressM,
            rateMS: st.route.rateMS,
            stamp: st.route.stamp,
          };
        } else {
          npc.route.rateMS = st.route.rateMS;
          if (npc.route.stamp !== st.route.stamp) {
            if (shouldSnap(st.route.progressM, npc.route.progressM)) {
              npc.route.progressM = st.route.progressM;
            }
            npc.route.stamp = st.route.stamp;
          }
        }
        npc.waypoints = [];
      } else if (npc.route) {
        // The journey ENDED (§ A11: arrival is the travel block being gone) —
        // or its route went behind the fog. Either way the server has placed
        // the figure and there is nothing left to extrapolate, so this is a
        // SNAP: walking the last extrapolated metres off would be a visible
        // residual run across the arrival location, and the arrival point is
        // a door, not a direction.
        npc.route = null;
        npc.waypoints = [];
        npc.root.position.copy(st.pos);
        arrived = true;
      }
      // Zielwechsel -> Zwischenstationen übernehmen (Raum-Ausgänge). The A*
      // detour around buildings that stood here is GONE with the cell grid
      // (E4 task 5, `scene/pathfind.ts` deleted): it was built from the v1
      // grid keys the server stopped sending in E3, so it had been planning
      // routes over `undefined` cells for a release. Without waypoints the
      // figure walks the straight line, which is what it already did whenever
      // the grid answered nothing. Travellers are exempt in any case — on a
      // journey the server route alone drives the figure, and so is the
      // update that ENDS one: the arrival placed the figure where it belongs,
      // and the door routing of this very update (the traveller had no shown
      // room, the arrival gives it one) would walk it back out to the door
      // and in again — the residual walk in another costume.
      if (!npc.route && !arrived && !npc.target.equals(st.pos)) {
        npc.waypoints = st.via?.length ? st.via.map((v) => v.clone()) : [];
      }
      // A SNAP is not a move (finding B5): the placement changed because the
      // view did, so the figure belongs at the new point immediately — walking
      // it there would send it from the outdoor huddle spot in through the
      // front door of a room it never left. Handled like the arrival above:
      // waypoints dropped, position set.
      if (st.snap && !arrived) {
        npc.waypoints = [];
        npc.root.position.copy(st.pos);
      }
      npc.target.copy(st.pos);
      // …and at the SERVER's pace, which is the plain one. Only the walking
      // hook of main.ts hands a ground pace in, and only for the figure it
      // steers; a figure the player has just given back (leaving embodied
      // mode goes through ONE choke point, `setPlayerDriven(null)` on the
      // game-state bus — explicit exit and the zoom-out inside embody.ts
      // alike) would otherwise keep the pace of the ground it stood on and
      // crawl over every ground for the rest of the session. The reset sits
      // HERE, at the target write, because that is the first thing `update()`
      // does for a figure again once it is server-driven: while the player
      // steers, the branch above `continue`s long before this line.
      npc.pace = 1;
      npc.face = st.face ?? null;
      npc.figure?.setLean(st.lean?.tilt ?? 0, st.lean?.roll ?? 0);
      npc.root.visible = !st.hidden;
      npc.activity = st.char.activity || '';
      npc.animation = st.char.activity_animation || undefined;
      npc.labelActivity.textContent = npc.activity;
      // The walking mark comes from the TRAVEL BLOCK, not from the route: a
      // fogged traveller has no waypoints but is just as much on its way, and
      // its arrival time is in the payload all the same (§ A11).
      const travelling = !!st.char.travel;
      const eta = st.char.travel?.eta_hhmm ? ` ${st.char.travel.eta_hhmm}` : '';
      npc.labelName.textContent = (travelling ? `🚶${eta} ` : '') + st.char.name;
      npc.travelling = travelling;
      // DEAD RECKONING for a traveller the fog left without a route (§ A12,
      // decision `77dbdb61`): the payload thins a foreign traveller's row down
      // to its `pos` — neither the goal nor the speed of someone else's
      // journey is the avatar's to know — and that decision stands, so the
      // client does not ask for the missing rate. It MEASURES it instead, from
      // the gap between the last two polled points over the real time between
      // them (`deadReckonRate`).
      //
      // Gated on the STAMP, never on the call: `update()` runs at 1 Hz off the
      // CACHED map while the poll is 3 s, so the same payload arrives three
      // times and the last two of them would measure a gap of zero over the
      // seconds in between — a figure braked to a standstill by its own
      // bookkeeping.
      if (travelling && !npc.route) {
        const stamp = st.stamp ?? 0;
        const cur: MetrePoint = [st.pos.x, st.pos.z];
        const atS = performance.now() / 1000;
        if (!npc.reckon) {
          npc.reckon = { pos: cur, atS, stamp, rateMS: null };
        } else if (npc.reckon.stamp !== stamp) {
          // A refused measurement (`null`) KEEPS the rate the figure was
          // walking at — it is a missing observation, not a report of standing
          // still. A measured 0 is such a report and does replace it.
          const rate = deadReckonRate(npc.reckon.pos, npc.reckon.atS, cur, atS);
          npc.reckon = { pos: cur, atS, stamp, rateMS: rate ?? npc.reckon.rateMS };
        }
      } else {
        // Arrived, or the route came out of the fog: the measurement belongs
        // to a journey and must not survive it into the next one.
        npc.reckon = null;
      }
      this.updateTravelLine(npc, npc.route);
    }
    for (const [name, npc] of this.npcs) {
      // THE PLAYER'S OWN FIGURE IS NEVER REMOVED (finding B2). Its position
      // belongs to the frame hook in main.ts, not to the worldmap, so a poll
      // that does not mention it (a payload gap, a character list caught
      // mid-change) must not take it off the map — the player would be left
      // steering nothing, with no way to get the figure back short of leaving
      // the mode. Every other figure follows the payload as before.
      if (!seen.has(name) && name !== this.playerDriven) {
        this.group.remove(npc.root);
        this.dropTravelLine(npc);
        npc.figure?.dispose();
        npc.label.element.remove();
        this.npcs.delete(name);
      }
    }
    this.syncSelectRing();   // re-attach after rebuilds, drop when the figure left
  }

  private createNpc(st: NpcState): Npc {
    const isAvatar = st.char.name === this.avatarName;
    const root = new THREE.Group();
    root.userData.charName = st.char.name;   // figure picking (E3-T1)
    const figure = this.figures?.instantiate(st.char.name) ?? null;
    let sprite: THREE.Sprite | null = null;
    let ring: THREE.Mesh | null = null;
    let labelY: number;

    if (figure) {
      root.add(figure.root);
      // farbiger Bodenring als Wiedererkennung (gold = eigener Avatar)
      ring = new THREE.Mesh(
        new THREE.RingGeometry(0.55, 0.7, 28),
        new THREE.MeshBasicMaterial({
          color: isAvatar ? 0xe8b83a : new THREE.Color(ringColor(st.char.name)),
          transparent: true,
          opacity: 0.85,
        })
      );
      ring.rotation.x = -Math.PI / 2;
      ring.position.y = 0.09;
      root.add(ring);
      labelY = figure.height + 0.45;
    } else {
      const tex = makePortraitTexture(st.char.name, st.char.avatar_url, isAvatar);
      sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, depthTest: true }));
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
      labelY = -0.15;
    }

    const el = document.createElement('div');
    el.className = 'npc-label' + (isAvatar ? ' npc-avatar' : '') + (figure ? ' above' : '');
    const nameEl = document.createElement('span');
    nameEl.className = 'npc-name';
    nameEl.textContent = st.char.name;
    const actEl = document.createElement('span');
    actEl.className = 'npc-activity';
    // The bubble is the FIRST child, so it grows upwards out of the label
    // block and never pushes name or activity off the head.
    const bubbleEl = document.createElement('div');
    bubbleEl.className = 'npc-bubble';
    bubbleEl.hidden = true;
    el.append(bubbleEl, nameEl, actEl);
    const label = new CSS2DObject(el);
    label.position.set(0, labelY, 0);
    root.add(label);

    return {
      name: st.char.name, root, figure, ring, sprite, label,
      labelName: nameEl, labelActivity: actEl,
      labelBubble: bubbleEl, bubbleUntil: 0,
      target: st.pos.clone(), pace: 1, face: st.face ?? null, waypoints: [], route: null,
      travelling: false, reckon: null, interaction: null, activity: st.char.activity || '',
      animation: st.char.activity_animation || undefined,
      travelLine: null, travelKey: '',
      bobPhase: Math.random() * Math.PI * 2,
    };
  }

  /** Draw the journey as the dashed polyline it IS (§ A11), or take it away.
   *
   *  The whole route AHEAD, not a straight line to the goal: the server's
   *  waypoints walk around the buildings and over the passable ground, and a
   *  chord across them would promise a way that does not exist. A fogged
   *  traveller (`waypoints: null`) has no route here and therefore no line —
   *  that is the binding rule, the route would be a metre-exact marker for a
   *  place the avatar may not know.
   *
   *  TRIMMED at the walker's foot point (`remainingPoints`): the stretch
   *  already walked is behind the figure, and a line that still ran back to
   *  the starting point drew a way that had been used up. The trim advances in
   *  five-metre buckets, which is what the KEY carries — the geometry is
   *  rebuilt when the bucket rolls over and at no other time, so a traveller
   *  costs one buffer every metre and a half instead of one per frame. */
  private updateTravelLine(npc: Npc, route: (TravelRoute & { key: string }) | null) {
    // Clamped ONCE, for the bucket and the trim alike: a `progress_m` that has
    // run past the end of its own polyline draws the same last point however
    // far it overshoots, and an unclamped bucket would rebuild that identical
    // geometry every further five metres.
    const walked = route ? clampProgress(route.progressM, route.totalM) : 0;
    const key = route ? `${route.key}#${trimBucket(walked)}#${this.groundRev()}` : '';
    if (key === npc.travelKey) return;
    this.dropTravelLine(npc);   // clears travelKey, so the new one goes after
    npc.travelKey = key;
    const ahead = route ? remainingPoints(route.points, walked) : [];
    if (route && ahead.length >= 2) {
      // A POINT PER GROUND SAMPLE, not per waypoint (§ A16): the height is
      // taken at each corner and the stretch between two corners is straight,
      // so a line drawn on the server's waypoints alone would run through the
      // hills between them. `densifyPolyline` fills the long stretches (and
      // caps the count) — the corners of the route itself all survive.
      const pts = densifyPolyline(ahead).map(
        (p) => new THREE.Vector3(p[0], this.groundY(p[0], p[1]) + 0.3, p[1]));
      const geo = new THREE.BufferGeometry().setFromPoints(pts);
      const line = new THREE.Line(geo, new THREE.LineDashedMaterial({
        color: 0xf2cd6e, dashSize: 0.9, gapSize: 0.6, transparent: true, opacity: 0.9,
      }));
      line.computeLineDistances();
      this.group.add(line);
      npc.travelLine = line;
    }
  }

  /** Facing while standing: look at the centroid of the near neighbours
   *  (reads as a conversation circle); a lone figure faces the camera side. */
  private facingTargets(): Map<string, THREE.Vector3> {
    const NEAR = 4.5;                       // world metres = "in the same conversation"
    const out = new Map<string, THREE.Vector3>();
    const list = [...this.npcs.values()];
    for (const npc of list) {
      const near = list.filter(
        (o) => o !== npc && o.root.position.distanceTo(npc.root.position) < NEAR
      );
      if (!near.length) continue;
      const c = new THREE.Vector3();
      for (const o of near) c.add(o.root.position);
      c.divideScalar(near.length);
      out.set(npc.name, c);
    }
    return out;
  }

  /**
   * Show what a figure just said as a bubble over its head (stage 6).
   *
   * The HUD calls this out of the SAME batch of new transcript lines that
   * feeds the voice-over, so bubble and voice always agree about who said
   * what. A second line from the same figure REPLACES the first — a stack of
   * bubbles would cover the scene, and the chat panel is where the backlog
   * belongs. Unknown names are ignored: the speaker may be in another room,
   * or a figure the worldmap has not delivered yet.
   */
  say(name: string, text: string): void {
    const npc = this.npcs.get(name);
    if (!npc) return;
    const shown = bubbleText(text);
    if (!shown) return;
    npc.labelBubble.textContent = shown;
    npc.labelBubble.hidden = false;
    // Reading time, not a fixed timeout: a one-word answer should not hang in
    // the air as long as three sentences (game/bubble.ts).
    npc.bubbleUntil = performance.now() + bubbleMs(text);
  }

  /** Pro Frame: Richtung Ziel laufen, Animation nach Zustand wählen. */
  /** Is this figure bound in a pair interaction right now? main.ts asks
   *  before it reports the avatar's position: the clip moves the root, and a
   *  reported "move" would make the server end the very interaction. */
  inInteraction(name: string): boolean {
    return !!this.npcs.get(name)?.interaction;
  }

  /** Take the interaction block of a worldmap row (§ A8a). A new id is a new
   *  interaction and is adopted whole; the same id keeps the locally advanced
   *  clip time and only snaps it when a genuinely NEW poll disagrees by more
   *  than PAIR_SNAP_S. The rate is authoritative on every update — a freeze
   *  must stop the mixer at once. */
  private adoptInteraction(npc: Npc, st: NpcState) {
    const it = st.interaction;
    if (!it || !it.anchor) {
      npc.interaction = null;
      return;
    }
    const clip = `${it.kind}__${it.role}`;
    const stamp = st.stamp ?? 0;
    if (!npc.interaction || npc.interaction.id !== it.id || npc.interaction.clip !== clip) {
      npc.interaction = {
        id: it.id, clip,
        anchor: { x: it.anchor.x, z: it.anchor.z, yaw: it.anchor.yaw, placeId: it.anchor.place_id ?? null },
        elapsed: it.elapsed_s, duration: it.duration_s, rate: it.rate ?? 0, stamp,
        clipDuration: it.clip_duration_s || it.duration_s, loop: !!it.loop,
      };
      npc.route = null;
      npc.waypoints = [];
      this.updateTravelLine(npc, null);
      return;
    }
    const cur = npc.interaction;
    cur.rate = it.rate ?? 0;
    cur.anchor = { x: it.anchor.x, z: it.anchor.z, yaw: it.anchor.yaw, placeId: it.anchor.place_id ?? null };
    if (cur.stamp !== stamp) {
      if (Math.abs(cur.elapsed - it.elapsed_s) > PAIR_SNAP_S) cur.elapsed = it.elapsed_s;
      cur.stamp = stamp;
    }
  }

  /** One frame of a pair interaction: the figure stands at
   *  `anchor + R_y(yaw) · clipRoot(t)`, its root turned by `yaw`, and plays
   *  its clip half at game-clock time `t`. A pair the server seated on a
   *  PLACE (`anchor.placeId`) stands at that place's slot height — the
   *  couple on the sofa, not on the floor under it; the slots of one place
   *  share their height, so slot 0 stands for the place. Returns false when
   *  the half is not bound on this rig (or the figure has no rig) — then the
   *  ordinary placement runs, the clip falls back to the activity kind. */
  private tickInteraction(npc: Npc, dt: number, camDist: number, labelVisible: boolean): boolean {
    const it = npc.interaction!;
    if (!npc.figure || !this.figures) return false;
    it.elapsed = Math.min(it.duration || Infinity, it.elapsed + dt * it.rate);
    // clip time: a cycle replays, a one-shot holds its last frame
    const clipT = it.loop && it.clipDuration > 0 ? it.elapsed % it.clipDuration : it.elapsed;
    const root = this.figures.pairRootAt(it.clip, clipT);
    if (!root) return false;
    if (!npc.figure.playPair(it.clip, clipT, it.rate)) return false;
    const c = Math.cos(it.anchor.yaw);
    const s = Math.sin(it.anchor.yaw);
    const x = it.anchor.x + root.x * c + root.z * s;
    const z = it.anchor.z - root.x * s + root.z * c;
    const seat = it.anchor.placeId
      ? this.placeAt(npc.name, it.anchor.placeId, it.anchor.x, it.anchor.z) : undefined;
    npc.root.position.set(x, seat ? seat.slots[0].y : this.groundY(x, z), z);
    npc.figure.setYaw(it.anchor.yaw);
    npc.figure.update(dt);
    npc.ring?.scale.setScalar(THREE.MathUtils.clamp(camDist * 0.022, 1, 2.6));
    npc.label.visible = labelVisible;
    return true;
  }

  tick(dt: number, camDist: number) {
    const labelVisible = camDist < 55;
    const now = performance.now();
    for (const npc of this.npcs.values()) {
      if (npc.bubbleUntil && now >= npc.bubbleUntil) {
        npc.bubbleUntil = 0;
        npc.labelBubble.hidden = true;
        npc.labelBubble.textContent = '';
      }
    }
    const spriteScale = THREE.MathUtils.clamp(camDist * 0.055, 1.7, 3.4);
    const faceTo = this.facingTargets();
    for (const npc of this.npcs.values()) {
      if (npc.interaction && this.tickInteraction(npc, dt, camDist, labelVisible)) continue;
      // Server journey (§ A11): walk along the route instead of npc.target.
      // ONE number carries the whole journey — the metres walked along the
      // polyline — and the point is re-derived from it by arc length, so a
      // node is crossed without waiting for the next poll. The rate is metres
      // per REAL second (`pace_m_s_real ?? speed_m_s_real`); `null` (frozen
      // world, arrived, degenerate segment) extrapolates nothing, and the
      // advance is capped at the END of the polyline: the figure holds at its
      // last waypoint until the server books the arrival, it never walks past
      // it.
      if (npc.route && npc.route.points.length >= 2) {
        const r = npc.route;
        r.progressM = advanceProgress(r.progressM, r.rateMS, dt, r.totalM);
        // The trim follows the walker from HERE, not from the 1 Hz update:
        // the progress that decides the bucket is the extrapolated one, and a
        // line that only caught up with the next poll would lag a whole second
        // behind the figure. The call itself is a string compare on all but
        // every 5 m — see `updateTravelLine`. The player's own figure is
        // exempt for the same reason `update()` clears its line: it walks on
        // foot, there is no server journey to draw, and re-adding the line
        // here would fight that second-by-second.
        if (npc.name !== this.playerDriven) this.updateTravelLine(npc, r);
        const at = pointAtDistance(r.points, r.progressM)!;
        // The height belongs to the point the walk has REACHED, not to the
        // one the last poll reported: between two polls the figure covers
        // several metres of open country, and holding the poll's height would
        // have it walk into the hill and out of it again every three seconds.
        const goalPos = new THREE.Vector3(at[0], this.groundY(at[0], at[1]), at[1]);
        const delta = goalPos.clone().sub(npc.root.position);
        delta.y = 0;
        const d = delta.length();
        // WHAT THE GROUND SAYS AT THE POINT THE WALK HAS REACHED — read here,
        // because since E4 the ROOT depends on it too and not only the clip
        // (`walk.floatRootY`): over water the figure hangs its sink under the
        // MIRROR instead of under the carved bed. `d` is a horizontal distance
        // (`delta.y = 0` above), so deciding the pose before the height is not
        // a circle.
        const travelling = d > 0.02 || (r.rateMS ?? 0) > 0;
        const raw = this.groundMoveAt(at[0], at[1]);
        // TWO REACH RULES, in order: the SCOPE (a built place replaces the
        // ground with its floor) and, since W4c, the WATER DEPTH under the
        // figure — shallower than the kind's `swim_from_m` the ground says
        // nothing at all and the traveller wades through on its own walk clip,
        // feet on the bed. `goalPos.y` is still the raw terrain height of the
        // point the walk has reached, which is exactly the bed to measure
        // against; it becomes the float height two lines further down.
        const gm = wadeGate({ anim: raw.anim, idle: raw.idle, sink: raw.sink,
          water: groundWaterLevel(raw.water, raw.scope) },
        goalPos.y, raw.swimFrom);
        // THE UNDERWATER GHOST, for a traveller as for anybody else (finding
        // H3) — and on the UNGATED water level, because a wader is exactly the
        // figure the opaque surface cuts in half. `goalPos.y` is still the raw
        // BED here, three lines before it becomes the float height.
        npc.figure?.setSubmerged(
          ghostCutY(goalPos.y, groundWaterLevel(raw.water, raw.scope)));
        const groundIdle = idleClip(gm.idle, raw.scope);
        const sinkM = groundSink(sinkForState(travelling, groundIdle, gm.sink),
                                 raw.scope);
        goalPos.y = floatRootY(goalPos.y, gm.water, sinkM);
        if (d > 0.05) {
          // Catch-up speed: WALK_SPEED, or the JOURNEY's own pace when that is
          // faster. A fixed WALK_SPEED was a brake, not a smoother — the game
          // time factor multiplies `pace_m_s_real` (§ A11), so past a factor of
          // about 2.4 the interpolated point outruns 3.4 m/s and the figure
          // lags behind its own journey for the whole trip, then teleports on
          // arrival.
          const step = catchUpStep(d, r.rateMS, dt, WALK_SPEED);
          const dir = delta.clone().normalize();
          npc.root.position.addScaledVector(dir, step);
          npc.figure?.faceTowards(dir);
        }
        npc.root.position.y += (goalPos.y - npc.root.position.y) * Math.min(1, dt * 4);
        if (npc.figure) {
          // no 'run' on journeys: the pace comes from the server — walk while
          // the journey is moving, idle on freeze. WHAT walking looks like is
          // the ground's to say (`moveClip`, finding 3): a traveller crossing
          // painted water swims through it — and a FROZEN journey in that
          // water treads it (`idleClip`), instead of standing on the lake.
          //
          // The second argument is the GATE of the clip ground offset
          // (`figures.Figure.play`): whenever the GROUND names the clip, the
          // ground is the body's reference, so a clip authored on a water line
          // is dropped onto it. An ordinary standing clip keeps its height.
          // The third is how deep the ground swallows the body on top of that
          // — the MOVE depth while the journey runs, the IDLE one while it is
          // frozen in the water (`sinkForState`), and 0 outside the ground
          // rule's reach (`groundSink`). It is the VERY number the root was
          // placed with above, which is what makes the pair meet: root − sink
          // is the surface the body rests on.
          npc.figure.play(travelling ? moveClip(gm.anim, false, raw.scope)
            : (groundIdle || 'idle'), travelling || !!groundIdle, sinkM);
          npc.figure.update(dt);
          npc.ring?.scale.setScalar(THREE.MathUtils.clamp(camDist * 0.022, 1, 2.6));
        } else if (npc.sprite) {
          npc.bobPhase += dt * 14;
          npc.sprite.position.y = 0.15 + Math.abs(Math.sin(npc.bobPhase)) * 0.35;
          npc.sprite.scale.setScalar(spriteScale);
        }
        npc.label.visible = labelVisible;
        continue;   // travellers skip the normal goal/waypoint logic
      }
      // The next waypoint (when a way is planned), otherwise straight to the goal
      while (npc.waypoints.length && npc.root.position.distanceTo(npc.waypoints[0]) < 1.5) {
        npc.waypoints.shift();
      }
      const goal = npc.waypoints[0] ?? npc.target;
      const delta = goal.clone().sub(npc.root.position);
      delta.y = 0;
      const distToGoal = delta.length();
      const dist = npc.waypoints.length ? distToGoal + 10 : distToGoal;  // on the way = running
      const moving = distToGoal > MOVE_EPS_M;
      // A TRAVELLER WITHOUT A ROUTE WALKS BY ITS OWN RECKONING, and never in
      // the run boost. Under fog the worldmap thins a foreign traveller's row
      // down to `pos` (decision `77dbdb61`: neither the goal nor the speed of
      // someone else's journey is revealed) — so this figure lands in the
      // generic branch below with `route = null`, `target = pos` and `pace =
      // 1`, and that branch would sprint it at `3.4 * 1.8 = 6.12 m/s` in a
      // straight line: a wanderer's real pace is ~2 m/s, one 3 s poll gap is
      // 6 m, and 6 m is exactly `RUN_DISTANCE`. Sprint, pause, sprint.
      //
      // The client does not ask the server for what the decision withholds. It
      // MEASURES the rate between the last two polled points (`update()`,
      // `deadReckonRate`) and walks it — scaled by the ground under the figure
      // (`walk.terrainPace`, the very pace the avatar walks under) and capped
      // by the distance to the polled point, which is the one position the
      // server vouched for. Without a measurement yet (the first sighting) the
      // old walk stands, minus the boost.
      const reckoning = npc.travelling && npc.name !== this.playerDriven;
      const reckonRate = reckoning ? npc.reckon?.rateMS ?? null : null;
      if (moving) {
        // ONE pace for every figure, the player's included: `WALK_SPEED` is
        // metres a second and a metre is a metre (E4). `npc.pace` is what the
        // GROUND allows on top of that (1 for everybody but the avatar) —
        // the step is where the terrain pace belongs, because the goal is a
        // fixed lead ahead and a paced lead would fall under `MOVE_EPS_M`.
        let step: number;
        if (reckonRate !== null) {
          // The reckoned figure reads its own ground here, BEFORE the step:
          // the pace belongs to the metre the figure is standing on, and the
          // sample below (`standRaw`) is taken after the move, for the clip
          // and the height of where it arrives.
          const paceRaw = this.groundMoveAt(npc.root.position.x, npc.root.position.z);
          step = deadReckonStep(reckonRate, terrainPace(paceRaw.speed, paceRaw.scope),
                                dt, distToGoal);
        } else {
          step = Math.min(distToGoal,
            WALK_SPEED * dt * npc.pace * (!reckoning && dist > RUN_DISTANCE ? 1.8 : 1));
        }
        const dir = delta.clone().normalize();
        npc.root.position.addScaledVector(dir, step);
        npc.figure?.faceTowards(dir);
      }
      // WHAT THE GROUND SAYS UNDER THE FIGURE, once — the clips below and the
      // ROOT height need the same answer, and asking twice is how the two
      // start to disagree. Since E4 the height is part of it: over water the
      // root rides the MIRROR and not the carved bed (`walk.floatRootY`).
      const standRaw = this.groundMoveAt(npc.root.position.x, npc.root.position.z);
      // …and since W4c the DEPTH decides whether that word applies at all: the
      // bed is sampled UNDER THE FIGURE (never the waypoint's stored y, which
      // is a goal and may be a lake away), because "how deep does the water
      // stand around me" is a question about where the figure IS.
      const standBedY = this.groundY(npc.root.position.x, npc.root.position.z);
      const standGm = wadeGate({ anim: standRaw.anim, idle: standRaw.idle,
        sink: standRaw.sink,
        water: groundWaterLevel(standRaw.water, standRaw.scope) },
      standBedY, standRaw.swimFrom);
      // …and the UNDERWATER GHOST rides the same two numbers, but the UNGATED
      // water level (finding H3): `wadeGate` nulls the mirror below the kind's
      // swim depth because a wader keeps its own clips — and a wader is exactly
      // the figure the opaque water surface cuts in half. `ghostCutY` is the
      // whole decision — the SAME one a submerged prop is gated by — and it
      // answers the LEVEL, because the ghost cuts itself off at the waterline.
      npc.figure?.setSubmerged(ghostCutY(standBedY,
        groundWaterLevel(standRaw.water, standRaw.scope)));
      const standIdle = idleClip(standGm.idle, standRaw.scope);
      const standSink = groundSink(
        sinkForState(moving, standIdle, standGm.sink), standRaw.scope);
      // Match the height to the CURRENT waypoint — that is what makes the
      // vertical ride between two lift stops (AV3D-12).
      const goalY = floatRootY(npc.waypoints[0]?.y ?? npc.target.y,
        standGm.water, standSink);
      npc.root.position.y += (goalY - npc.root.position.y) * Math.min(1, dt * 4);
      if (!moving && npc.figure) {
        // Stehend: Marker-Richtung > Nachbarn ansehen > Kamera-Grundrichtung
        const target = faceTo.get(npc.name);
        const dir = npc.face
          ? npc.face.clone()
          : target
            ? target.clone().sub(npc.root.position).setY(0)
            : new THREE.Vector3(0, 0, 1);
        npc.figure.faceTowards(dir);
      }

      if (npc.figure) {
        // Moving, the GROUND decides (`moveClip`, finding 3): its `move_anim`
        // replaces walk and run alike, and without one the old pair stands.
        // STANDING, the ground gets the FIRST word too since the water round
        // of 2026-08-13 (`idleClip`): a figure standing in a lake treads water
        // rather than standing on it. Only where the ground names nothing does
        // the server's category hold (AV3D-6) — and where the server names
        // none either, the figure simply stands: the keyword guessing over
        // the activity text is gone (Task 13, plan-posen-plaetze.md), a pose
        // comes from the catalog or not at all. This is the ONE clip decision
        // of every figure, the player's avatar included: it is steered
        // through this same loop.
        const standingClip = npc.animation || 'idle';
        // The second argument is the gate of the clip ground offset (see the
        // traveller branch above): a clip the GROUND named — moving or
        // standing — has the ground as its reference, an activity clip does
        // not (`sleep` carries the bed it was animated on). The third is the
        // ground's own sink depth — one per pose since finding 13, picked by
        // the same state that picks the clip (`sinkForState`) and cut off
        // inside a built place like the clips are (`groundSink`). It is the
        // very number the root was raised with above, which is what makes the
        // pair meet: root − sink is the surface the body rests on.
        npc.figure.play(
          moving ? moveClip(standGm.anim, !reckoning && dist > RUN_DISTANCE, standRaw.scope)
            : (standIdle || standingClip), moving || !!standIdle, standSink);
        npc.figure.update(dt);
        // The ring grows with the camera distance so NPCs stay findable from afar
        npc.ring?.scale.setScalar(THREE.MathUtils.clamp(camDist * 0.022, 1, 2.6));
      } else if (npc.sprite) {
        if (moving) {
          npc.bobPhase += dt * 14;
          npc.sprite.position.y = 0.15 + Math.abs(Math.sin(npc.bobPhase)) * 0.35;
        } else {
          npc.sprite.position.y = 0.15;
        }
        npc.sprite.scale.setScalar(spriteScale);
      }
      npc.label.visible = labelVisible;
    }
    // Same rule as the identity ring: grow with the camera distance so the
    // selection stays findable in the far view (sprite figures included).
    this.selectRing?.scale.setScalar(THREE.MathUtils.clamp(camDist * 0.022, 1, 2.6));
  }
}
