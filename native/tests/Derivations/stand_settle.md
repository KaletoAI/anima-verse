# stand_settle

- Origin: the browser scene's deleted `smoke_stand_settle.mjs` @ 011cd048aa3cc2937186d7f35d2203af9491db8a
- Executed by: `native/tests/BridgeVectorTests.cs`
- Vectors: `shared/test-vectors/stand_settle.json`

## Derivation

```text
/**
 * Smoke check: an NPC keeps the spot its bridge clip left it on (plan
 * bruecken-feinschliff, Task C4) — `settleOffset` in
 * the browser scene's `standSettle.ts` and its two call sites in
 * the browser scene's `npcs.ts` (the bridge hand-over in `tick`, the goal write
 * in `update`).
 *
 * Usage:  node the browser scene's deleted smoke_stand_settle.mjs
 *
 * Every expected number below is derived BY HAND from the rule written out
 * here, never recorded from the current output.
 *
 * ===========================================================================
 * THE RULE
 * ===========================================================================
 * A bridge clip with root motion (getting up out of a chair or a bed) carries
 * the body off the seat; when it ends the NPC's root takes that travel over
 * (`Figure.takeTravel`). The server already put the character's position on
 * the point the same clip sets it down (`room_stand.bridge_stand_point` = seat
 * + the clip's travel, then `pick_stand`), so the goal the NPC walks to IS that
 * stand point — the hand-over moves the ROOT only. Before this task it moved
 * the goal by the travel as well: the figure walked on to a point one travel
 * past the stand point, and back once the next poll re-wrote the goal (C0
 * § 5.2: goal 49 → 85 cm from the seat).
 *
 * Client and server measure the travel differently (the client per rig, with
 * the bridge's turn in the root; the server from the sidecar's `travel_m`), so
 * the body lands a few centimetres off the server's point. Within
 * STAND_ADOPT_M = 0.25 m — the raster step of `room_stand.pick_stand`
 * (`STAND_GRID_M = 0.25`, app/core/room_stand.py:51), i.e. closer than the
 * server could have placed the figure anyway — the NPC keeps where it stands:
 *
 *     settle = figure − server              (X/Z; |settle| <= 0.25)
 *     goal   = server + settle              (= the figure: nothing to walk)
 *
 * as long as the server sends the SAME position (within SAME_STAND_M = 1 mm;
 * the server writes centimetre-rounded points, so a real move is >= 1 cm).
 * A different position voids it — the figure walks from where it stands. The
 * height is the server's either way (only X/Z are settled).
 *
 * ===========================================================================
 * [P] THE PURE DECISION — settleOffset(figure, server, lastServer, tol)
 * ===========================================================================
 * [P1] figure (2.12, 3.00), server = last = (2.00, 3.00):
 *      off = (0.12, 0), |off| = 0.12 <= 0.25            → (0.12, 0)
 * [P2] figure (2.40, 3.00):  |off| = 0.40 > 0.25          → null
 * [P3] diagonal, figure (2.09, 2.88): off = (0.09, −0.12),
 *      |off| = sqrt(0.0081 + 0.0144) = sqrt(0.0225) = 0.15 → (0.09, −0.12)
 * [P4] exactly on the raster step: figure (2.00, 3.25), |off| = 0.25 → kept
 *      ((0, 0.25), the bound is inclusive); figure (2.00, 3.2501) → null
 * [P5] the server moved: server (2.01, 3.00), last (2.00, 3.00) — 1 cm, a
 *      real move → null; server (2.0004, 3.00) — 0.4 mm, float noise → the
 *      offset from the NEW server point, (2.12 − 2.0004, 0) = (0.1196, 0)
 * [P6] STAND_ADOPT_M is 0.25 (the raster step quoted above).
 *
 * ===========================================================================
 * [S] THE MANAGER — the real `NpcManager.update` + `tick`
 * ===========================================================================
 * One injected NPC (the shape `createNpc` builds; `update` never creates it,
 * so no DOM is needed), with a STUB figure whose bridge has just ended and
 * holds a travel (`holdsTravel`, `takeTravel` hands it over once) — the
 * bridge itself is `smoke_bridge_root.mjs` [Y3]'s business, here only what
 * the manager does with the travel. Seat at (1.60, 0, 3.00), server stand
 * point P = (2.00, 0, 3.00) delivered by `update`, dt = 1/30 s. Walking pace:
 * step = min(dist, WALK_SPEED 3.4 · dt) = min(dist, 0.113333) (dist < 6 m
 * RUN_DISTANCE: no boost), and nothing moves under MOVE_EPS_M = 0.05.
 *
 * [S1] travel (0.52, 0): after the hand-over tick the root is at (2.12, 3.00)
 *      — 0.12 m off P → settle (0.12, 0), goal = (2.12, 0, 3.00) = the figure.
 *      The root does not move in that tick nor in 30 more (<= 1e-6), and after
 *      the next `update` (same P) the distance root → goal is < 1e-6.
 *      OLD CODE: the goal moved by the travel to (2.52, 3.00), 0.40 m ahead,
 *      and the hand-over tick already stepped 0.113333 towards it.
 * [S4] `update` with the SAME P again (a poll): settle kept, goal (2.12, 3.00).
 * [S3] `update` with a NEW P' = (3.00, 3.00) — 1 m away: settle cleared, goal
 *      = P' exactly; one tick later the root has walked 0.113333 towards it
 *      (dist 0.88 > 0.113333), x = 2.12 + 0.113333 = 2.233333.
 * [S2] travel (0.80, 0) on a fresh NPC: root (2.40, 3.00), 0.40 m off P → no
 *      settle, goal = P; the hand-over tick walks back 0.113333 towards it:
 *      x = 2.40 − 0.113333 = 2.286667.
 *      OLD CODE: goal (2.80, 3.00), the tick walks away: x = 2.513333.
 * [S5] THE AVATAR IS NOT AFFECTED: the player-driven figure takes its travel
 *      through `takePlayerTravel`, which still moves root AND goal (main.ts
 *      reports the new point itself): root (1.60, 3.00) + (0.52, 0) → both at
 *      (2.12, 3.00), and it keeps no settle.
 * [S6] a SNAP (`st.snap`, a view change) with the same P puts the root on the
 *      settled spot (2.12, 3.00), not back on P.
 */
```
