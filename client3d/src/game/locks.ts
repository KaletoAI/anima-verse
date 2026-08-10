/**
 * What the avatar may not walk into, and why
 * (plan-betreten-und-tueren.md § 3 decision 2: "a ban is visible").
 *
 * Pure maths like `walk.ts` and `doors.ts`: no Three.js, no DOM, no module
 * state and no import at all, so `client3d/scripts/smoke_walk_math.mjs` can import the
 * file as plain ESM and check the rules with hand-derived cases.
 *
 * THE SERVER SAYS WHAT, THE CLIENT SAYS HOW. The verdict comes from the two
 * per-avatar polls and from nowhere else: `/play/scene → rooms[]` carries
 * `enterable` + `reason` per room, its `neighbors` the same per direction
 * (task C1). Nothing here derives a lock, and no lock is ever written into a
 * tile's cached scene payload — the signature-cached recipe is the same
 * geometry for everybody, while a lock belongs to ONE avatar at ONE moment.
 * Callers bind it at render/interaction time, by id.
 *
 * `reason` is the server's own sentence, already localized for the player. It
 * travels through the client untranslated.
 */

/** Locked things by id, each with the server's reason. A key EXISTS exactly
 *  for what is locked — an empty string is a lock the server gave no words to,
 *  not an open door. */
export type LockMap = Readonly<Record<string, string>>;

/** Nothing is locked. A constant and not a literal per caller, so the "no
 *  payload yet" case is one shared, frozen object. */
export const NO_LOCKS: LockMap = Object.freeze({});

/** Whether the server refuses this id (room or location). */
export function isLocked(locks: LockMap | null | undefined, id: string): boolean {
  if (!locks || !id) return false;
  return Object.prototype.hasOwnProperty.call(locks, id);
}

/** The server's sentence for a locked id, or '' when it is not locked (and
 *  when it is locked without words — the caller has nothing to show either
 *  way). */
export function lockReason(locks: LockMap | null | undefined, id: string): string {
  if (!isLocked(locks, id)) return '';
  const text = (locks as Record<string, string>)[id];
  return typeof text === 'string' ? text : '';
}

/**
 * The lock a DOORWAY inherits from the rooms it joins: the reason, or `null`
 * when nothing behind it is barred.
 *
 * `null` and not `''`, because the two are different answers: a lock the
 * server gave no words to still has to be DRAWN as a lock, and a caller
 * testing the string alone would draw it open.
 *
 * A doorway is a threshold between rooms, so it is locked when a room on the
 * far side is: that is the ban the player has to see BEFORE walking there.
 * `currentRoom` is left out of the judgement on purpose — the avatar is
 * standing in it, and a rule that refuses ENTERING a room says nothing about
 * leaving it. Without that exception every door of a locked room the avatar
 * is inside would read as a cage.
 *
 * The first locked room in payload order supplies the words; `roomIds[0]` owns
 * the wall the gap was cut from, so a two-room doorway names the near side
 * first.
 */
export function doorwayLock(roomIds: readonly string[] | null | undefined,
  locks: LockMap, currentRoom = ''): string | null {
  for (const id of roomIds ?? []) {
    if (id === currentRoom) continue;
    if (isLocked(locks, id)) return lockReason(locks, id);
  }
  return null;
}

/**
 * The rooms the room-change heuristic is allowed to propose.
 *
 * A locked room is no candidate: walking across its threshold must not post
 * the avatar into a room `/play/enter-room` would refuse — the offer and the
 * server would disagree in front of the player.
 *
 * The room the avatar is ALREADY in survives the filter even when it is
 * locked. Dropping it would make the nearest OTHER room the best candidate
 * while the figure stands still, and the hysteresis would then walk the avatar
 * out of a room it legitimately occupies.
 */
export function unlockedRooms<T extends { id: string }>(
  rooms: readonly T[], locks: LockMap, currentRoom = ''): T[] {
  return rooms.filter((r) => r.id === currentRoom || !isLocked(locks, r.id));
}
