/**
 * Riding between storeys in the embodied mode (plan-3d-game stage 3, floors
 * on foot).
 *
 * Stage 3 deliberately left storey changes out (decision 4: "no elevator
 * steering in v1"), and the 3D HUD has no room chips — which left the upper
 * floors of a building unreachable while embodied. Nothing new has to be
 * built for it: a building already carries one holding point per storey
 * (`tile.elevatorStops`, the storey routing of the NPCs rides them, AV3D-12)
 * plus `tile.roomLevels` and `tile.roomCenters`. What was missing is the
 * player's way in.
 *
 * Pure like `walk.ts`, `proximity.ts` and `roomwalk.ts`: plain numbers, no
 * Three, no DOM, no module state and no import BUT one to its own kind —
 * `stairs.ts` is as pure as this file, and the transpile of
 * `client3d/scripts/smoke_walk_math.mjs` follows a `./x` import between the
 * modules it loads, exactly as it does for `clickmove.ts` → `walk.ts`.
 */
import { nearestRoomAt } from './stairs';

/** How close to the holding point the avatar has to stand, in FIGURE metres —
 *  multiplied by the figure scale exactly like the talk range. Indoors a world
 *  metre is not a figure metre: at scale 0.3 the reach is 0.45 world metres,
 *  and unscaled the prompt would cover half the room. */
export const ELEVATOR_RANGE = 1.5;

/** Where the lift holds on one storey (XZ; the height is the caller's — the
 *  world point of the stop carries the storey's Y and is what drives the
 *  vertical ride). */
export interface ElevatorStop {
  level: number;
  pos: { x: number; z: number };
}

/** One room of the building, reduced to what the choice needs. */
export interface ElevatorRoom {
  id: string;
  level: number;
  center: { x: number; z: number };
}

/** What the HUD needs to draw the storey choice. */
export interface ElevatorState {
  /** storeys the lift actually serves, ascending (a basement sorts first) */
  levels: number[];
  /** storey the avatar is on — never offered as a destination */
  current: number;
}

/**
 * Storeys the lift really serves: a holding point AND at least one room. A
 * stop on a storey without a room leads nowhere, and the rooms are what
 * `/play/enter-room` moves the avatar between — a storey the server has no
 * room for cannot be entered at all.
 */
export function elevatorLevels(stops: ElevatorStop[], rooms: ElevatorRoom[]): number[] {
  const withRooms = new Set(rooms.map((r) => r.level));
  const levels = new Set<number>();
  for (const s of stops) {
    if (withRooms.has(s.level)) levels.add(s.level);
  }
  return [...levels].sort((a, b) => a - b);
}

/**
 * Is the avatar standing at its own storey's holding point of a building with
 * somewhere to ride to? Returns what the HUD shows, or null.
 *
 * @param pos    where the figure is drawn, world metres (XZ)
 * @param level  storey the avatar is on (from its room)
 * @param scale  scale the figure is drawn at (`npcs.scaleOf`)
 */
export function elevatorAt(
  pos: { x: number; z: number },
  level: number,
  stops: ElevatorStop[],
  rooms: ElevatorRoom[],
  scale: number,
): ElevatorState | null {
  const levels = elevatorLevels(stops, rooms);
  // Nothing to choose between: a single storey is not a ride, and a storey the
  // lift does not serve has no holding point to stand at.
  if (levels.length < 2 || !levels.includes(level)) return null;
  const stop = stops.find((s) => s.level === level);
  if (!stop) return null;
  const dist = Math.hypot(stop.pos.x - pos.x, stop.pos.z - pos.z);
  if (dist >= ELEVATOR_RANGE * scale) return null;
  return { levels, current: level };
}

/** Storeys to offer as buttons: everything but the one the avatar is on. */
export function elevatorOptions(state: ElevatorState): number[] {
  return state.levels.filter((lv) => lv !== state.current);
}

/**
 * The ONE storey there is to ride to, or null when there is a choice.
 *
 * A building with two served storeys leaves nothing to pick: the picker would
 * unfold a single button, and the press that opened it could have been the
 * ride. So the offer IS the ride there, exactly as it is on the stairs — from
 * the third storey on the choice comes back.
 */
export function elevatorSoleOption(state: ElevatorState): number | null {
  const options = elevatorOptions(state);
  return options.length === 1 ? options[0] : null;
}

/**
 * Room of `level` the ride ends in: the one whose centre lies NEAREST that
 * storey's holding point — stepping out of the lift puts you in the room it
 * opens into. Ties fall to the lower id, so the destination of a symmetric
 * floor cannot flicker between two rooms.
 *
 * Which is `nearestRoomAt` measured from the holding point, and that is where
 * the rule lives — the stairs ask the very same question from a landing, and
 * two copies of a tie-break are two chances to drift apart. All this function
 * still owns is finding the stop.
 */
export function elevatorTargetRoom(
  level: number,
  stops: ElevatorStop[],
  rooms: ElevatorRoom[],
): string | null {
  const stop = stops.find((s) => s.level === level);
  if (!stop) return null;
  return nearestRoomAt(level, stop.pos, rooms);
}
