# places_client

- Origin: the browser scene's deleted `smoke_places_client.mjs` @ 011cd048aa3cc2937186d7f35d2203af9491db8a
- Executed by: `native/tests/FigurePlacementVectorTests.cs`
- Vectors: `shared/test-vectors/place_poll.json`

## Derivation

```text
/**
 * Smoke check for the client's half of PLACES (plan-posen-plaetze.md § 4,
 * numbers, no screenshots — § B5a): the one pure rule the 3D client applies
 * to a seat the SERVER handed it, `packages/scene-render/src/placeSlot.ts`.
 *
 * Usage:  node smoke_places_client.mjs   (historical; the runner was deleted with the browser scene in E3)
 *         (self-bundles through esbuild like its siblings)
 *
 * WHAT THE CLIENT DOES NOT DECIDE. A character's worldmap row carries
 * `place: {id, slot, …}`; the scene payload carries the marker's `slots[]`
 * (one world point per unit of capacity, the server's slot formula). The
 * client looks the marker up by id and takes the slot the server named —
 * it chooses nothing, and the only rules it has are the two clamps below.
 *
 * Hand-derived expectations
 * -------------------------
 * One entry with capacity 3 at anchor (−2, 0, −3), spacing 0.6 m along the
 * facing's cross axis (here z), so the server's slots are
 *
 *   slot 0: (−2, 0, −3.6)     slot 1: (−2, 0, −3)     slot 2: (−2, 0, −2.4)
 *
 * (index i sits at at + (i − (n−1)/2)·spacing: (0−1)·0.6 = −0.6,
 * (1−1)·0.6 = 0, (2−1)·0.6 = +0.6 — the middle slot IS the anchor).
 *
 *   [1] `slotFor(e, 1)`      → slot 1, the anchor point (−2, 0, −3).
 *   [2] `slotFor(e, 'pair')` → the place's CENTRE, the mean of its slots
 *                              (−2, 0, −3): a PAIR is anchored on the place
 *                              (the server's `centre_of`, the worldmap row's
 *                              own x/z for a pair) and the clip's own frame
 *                              moves both partners out from there. A fresh
 *                              vector, not one of the slots.
 *   [3] `slotFor(e, 7)`      → slot 0: an index outside the entry's slots
 *                              (the capacity shrank under a sitter) falls
 *                              back to the first slot, never throws.
 *   [4] `slotFor(e, 2)`      → slot 2, the last one (−2, 0, −2.4) — the
 *                              range check is `< length`, not `< length − 1`.
 *   [5] the answer is the entry's OWN vector (identity), so a caller that
 *       moves the figure must `clone()` — and a re-lift of the entry
 *       (`reliftScene`, `deriveRoomSpots`) reaches the seat without a copy.
 *   [6] an entry WITHOUT slots (a payload marker that named none) answers
 *       `undefined` for a numbered slot and for a pair alike — total, never
 *       a throw and never a made-up point; the callers guard.
 *
 * WHICH TARGET A PLACE GETS (`scene/placeGlyphs.ts`, ruling 2026-08-28)
 * --------------------------------------------------------------------
 * Since the prop mesh itself takes the seat's click, the ring and the mesh
 * split the offered places between them — every place must end up with
 * exactly one target, and none with two.
 *
 *   [7] `buildGlyphs` draws a ring for
 *         - a ROOM marker (`fixed: false`)                        -> yes
 *         - a PROP marker with an `anchor` (its mesh is the target) -> no
 *         - a PROP marker WITHOUT one (a payload from before the field:
 *           `pickableProps` cannot find its mesh, so a ring is the only
 *           target it can have)                                   -> yes
 *       …and `skipPlaceId` still removes the place the avatar itself holds.
 *       …and a DIORAMA place (`diorama: true`, plan-diorama-hover.md) loses
 *       its ring exactly when its room's diorama is MOUNTED — the fourth
 *       argument is that set of rooms. Without a mounted diorama (the
 *       interior has not loaded, or it belongs to another room) the ring
 *       stays: a place one cannot click is worse than a ring.
 *       Four offers, two rings, and their `userData.placeId` are the room
 *       marker's and the anchor-less prop marker's.
 *   [8] `pickableProps` keys on ROOM + ANCHOR, not on the anchor alone: an
 *       anchor is a metre point in the room's own frame, so a bench in the
 *       same corner of two rooms carries the same pair. Two entries at
 *       anchor (1, 2), one in room "a" and one in room "b", against ONE
 *       placement in room "a" -> one pickable prop with ONE place, "a/seat".
 *       An entry without an anchor is never matched (it is a room marker),
 *       and a placement whose mesh has not loaded (`object: null`) is
 *       nothing to click.
 *   [8b] A target of `role: 'room'` is the room's DIORAMA and takes every
 *       `diorama` place of the same room — no anchor is compared, because a
 *       place on a diorama has no placement to name one. The two roles
 *       partition the places: the invariant of [7] + [8] is that every
 *       offered place ends up with EXACTLY ONE target (a ring, a prop or a
 *       diorama), never two.
 *
 * A POLL OLDER THAN OUR OWN SEAT CHANGE (plan-aufstehen.md, Task 1)
 * ----------------------------------------------------------------
 * Standing up releases the seat on the server and walks straight away. The
 * worldmap poll that was in flight while that happened still shows the seat,
 * and all three of its consumers (`reconcileAvatarPlace`, `reconcileAvatarPos`
 * and the player branch of `npcs.update`) ask ONE rule whether to believe it:
 * `pollIsStale(polledAt, ownSeatChangeAt)` — the poll is stale when it was
 * ASKED before the server ANSWERED our own last seat change. Both stamps are
 * `performance.now()` milliseconds, so the comparison is a plain `<`.
 *
 *   [9] `pollIsStale(1000, Infinity)` -> true: `Infinity` is the release in
 *       flight (no answer yet), and nothing asked before it can know about it.
 *       `pollIsStale(120, 200)`      -> true: asked 80 ms before the answer.
 *       `pollIsStale(300, 200)`      -> false: asked after it, believe it.
 *       `pollIsStale(200, 200)`      -> false: the same instant is not older.
 *       `pollIsStale(0, 0)`          -> false: no seat change of our own has
 *       ever been answered (the start value, and the value a FAILED release
 *       falls back to) — every poll counts, the server's word stands.
 *       The correction clock: `pollIsStale(100, 150)` -> true (100 < 150),
 *       `pollIsStale(200, 150)` -> false (200 > 150).
 *       These cases run from `shared/test-vectors/place_poll.json` (plan
 *       Task 29), which the native client's C# tests read too; `Infinity` is
 *       written `null` there (JSON has no Infinity) and mapped back by the
 *       dispatch below.
 *
 *  [10] WHICH CLIP A STANDING FIGURE PLAYS, `standingClipFor(animation,
 *       groundIdle)` — the expression the frame loop of `npcs.tick()` runs for
 *       every figure, the avatar included: the GROUND has the first word, then
 *       the server's activity clip, and a figure that has neither simply
 *       stands.
 *         ('sit', '')      -> 'sit'   the server's activity clip
 *         (undefined, '')  -> 'idle'  nothing named: the figure stands
 *         ('sit', 'tread') -> 'tread' the ground wins (standing in a lake)
 *       This is why the stand-up clears `npc.animation` locally
 *       (`setPlayerAnimation(name, null)`): with 'sit' still on the figure the
 *       rule keeps answering 'sit' until a fresh poll arrives.
 */
```
