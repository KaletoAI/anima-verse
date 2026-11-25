# order_chain

- Origin: none — native-first derivation (plan `2026-11-25-client-ausfuehrung-e3`, Task 2; spec
  `2026-11-25-client-ausfuehrung-design.md` § 5b/5c, plan decisions 6 and 19, reviews W3.1, N1, N2)
- Executed by: `native/tests/OrderVectorTests.cs` (every case [1]–[14]; the second variant of [10], no_path, only as
  a test), every case also as its own test in `native/tests/OrderPlayerTests.cs`
- Vectors: `shared/test-vectors/order_chain.json`

## Derivation

```text
THE FIXTURE
-----------
Geometry of native/tests/FakePathProvider.cs: a free floor (one rectangle x, z in [-10, 10], height 0);
Query(from, to) answers the straight line, Closest(p) is p itself on the floor. The order is one actor "Ona"
going from a chair to a bed (the wire form of plan decision 2):

  issued 100, eta 103.2, flip 105.6, deadline 113.2 (= eta + max(10, 0.5 * 3.2)), speed 1.4 m/s
  start  (0, 0, 0)        access (2.8, 0, 0) yaw 90       anchor (3.3, 0.45, 0) yaw 90
  sequence: exit(seat, sit_idle, 1.2 s) -> walk -> entry(lie, lie_down, 2.4 s) -> loop(lie, lie_idle)

No clip is loaded (IClipDurations answers null), so every phase lasts its nominal seconds. The path is
|access - start| = 2.8 m, at 1.4 m/s = 2.0 s. On the order's own clock the phases are

  exit  [0; 1.2)      walk  [1.2; 1.2 + 2.0 = 3.2)      entry [3.2; 3.2 + 2.4 = 5.6)      loop from 5.6

flip - issued = 105.6 - 100 = 5.6: the server's flip and the end of the chain coincide.

Frames: the client clock runs in steps of 1/60 s (frame k at k/60); an action "at t" happens before the
tick of the frame at t. A state's time is the first frame that shows it, compared with +-1/60 s
(eps 0.017 in the vector). The walk moves exactly speed * dt per frame along the path and lands on a corner
or the access exactly (no overshoot), so it reaches 2.8 m at walk time 2.0 s, frame 192 = 3.2 s.

THE CLOCK
---------
lag = motion_now - issued at Accept. IssuedLocal = clientNow - lag, set once, never adjusted; the order time
is t = clientNow - IssuedLocal - (frozen spans). Entry rule (spec 5c):
  lag <= 2 (LagFreshS)               the chain plays from the front, starting at the accept;
  2 < lag < flip - issued            mid-chain: the client plans its own path from the actor's start and
                                     seeks ONCE to (lag - exit_s) * speed along it, or into the entry clip;
  lag >= flip - issued or status active   the loop on the slot at once, no walk, no entry.

[1] fresh: lag 0.5 <= 2, accept at client 0 -> IssuedLocal = 0 - 0.5 = -0.5. The chain starts at the
    accept: Exit 0, Walk 1.2, Entry 3.2, Loop 5.6, each exactly once. Events: arrived_access and
    entry_started at 3.2, loop_started at 5.6.

[2] mid_walk: lag 2.5 (2 < 2.5 < 5.6). At the accept the chain is 2.5 s old: exit (1.2 s) is over, the
    walk has run 2.5 - 1.2 = 1.3 s -> path length 1.3 * 1.4 = 1.82 m, i.e. the figure stands at (1.82, 0, 0)
    in Walk. The remaining 2.8 - 1.82 = 0.98 m take 0.98 / 1.4 = 0.7 s -> Entry at local 3.2 - 2.5 = 0.7,
    Loop at 0.7 + 2.4 = 3.1.

[3] mid_entry: lag 4.0 (2 < 4.0 < 5.6). The walk would have ended at 3.2: Entry with phase time
    4.0 - 3.2 = 0.8 s at the accept, Loop at local 2.4 - 0.8 = 1.6.

[4] late_active: lag 7.0 >= 5.6 -> Loop at once, on the anchor (3.3, 0.45, 0); no Walk, no Entry.
    Separately status "active" with lag 0 -> the same.

REVISIONS AND NEW IDS
---------------------
[5] poll_noop: the same order_id and revision again at t 1.0 / 3.0 / 5.0 with other position fields (start x
    0.4, access x 2.2) -> Accept returns false, State and IssuedLocal stay; the chain is still [1] with lag 0
    (Exit 0, Walk 1.2, Entry 3.2 at x 2.8, Loop 5.6). Read after each poll: t 1.0 Exit, t 3.0 Walk at
    x = (3.0 - 1.2) * 1.4 = 2.52, t 5.0 Entry at x 2.8; IssuedLocal 0 every time.

[6] revision_shift: at t 2.0 (lag 0) revision 2 with every time + 30 s (issued 130, eta 133.2, flip 135.6,
    deadline 143.2). A higher revision never resets the clock: IssuedLocal stays 0, State stays Walk, the
    walked length stays (2.0 - 1.2) * 1.4 = 1.12 m; flip - issued = 135.6 - 130 = 5.6 is unchanged, and the
    chain ends as in [1] at 5.6.

[7] new ids (case 1 of spec 5b, decision 19 / N2), all with lag 0:
    new_id_from_walk: at t 2.5 a new id "cancel" -> the figure walks, it has no pose to leave: Abort at 2.5
      without an exit clip (event aborted), Idle from the next frame 2.5 + 1/60.
    new_id_from_loop: at t 6.0 (Loop since 5.6) a new prop_action whose sequence for Ona starts with exit
      (nominal 1.0 s) -> Exit at 6.0 with the pose kind of the RUNNING loop ("lie", key "lie_idle"), not that
      of the new sequence; then Walk 7.0 from the old access (2.8, 0, 0) to the new access (2.8, 0, 1.4):
      1.4 m / 1.4 = 1.0 s -> Entry 8.0, entry 1.5 s -> Loop 9.5.
      With a cancel carrying Ona (exit nominal 1.0, stand (1, 0, 1)): Exit at 6.0 ("lie"), Abort at 7.0 on
      (1, 0, 1), Idle from 7.0 + 1/60.
    new_id_from_loop_held: at t 6.0 a follow run whose sequence for Ona has no exit ([loop lie_side]) ->
      no Exit, the Loop goes on with the follow pose "lie_side". A cancel without Ona in actors -> Accept
      false, run-1 stays current, Loop goes on (until the row or a follow run ends it).

[8] refused at t 0.8 (in Exit) -> Abort at 0.8 (event aborted), Idle from 0.8 + 1/60, no further state.

[9] awaits: awaits "reaction", no flip. Exit 0, Walk 1.2, WaitAccess at the access from 3.2 (arrival). At
    t 4.0 revision 2 without awaits, flip 106.4 -> Entry exactly at 4.0 (the accept time, not the next
    frame), Loop at 4.0 + 2.4 = 6.4.

HEALING AND FREEZING
--------------------
[10] heal: a wall across the path, the hole x in (1.0, 1.5) over the whole floor depth. The figure walks
     from 1.2 s and is clamped onto the floor at x = 1.0:
       frame 114 (1.9 s):   x = (1.9 - 1.2) * 1.4 = 0.98
       frame 115 (1.9167):  intended 1.00333, clamped to the hole edge 1.0 -> moved 0.02 m, not slow
       from frame 116:      no movement (speed 0 < StuckSpeedMS 0.05)
     The stuck clock adds 1/60 per frame from frame 116; StuckS = 2.0 s is full after 120 frames, at frame
     235 (3.9167 s): first failure -> replan (same straight path, still blocked). After another 120 frames,
     frame 355 = 5.9167 s: second failure -> event "stuck". (The blockade replans every ReplanBlockedS = 1 s
     do not reset the stuck clock.) The local flip is IssuedLocal + (flip - issued) = 0 + 5.6; at
     5.6 + HealGraceS 5.0 = 10.6 the figure is still in Walk -> it is blended onto the access (2.8, 0, 0),
     event "healed", Entry at 10.6, Loop at 10.6 + 2.4 = 13.0. No arrived_access.
     Events: stuck 5.9167, healed 10.6, entry_started 10.6, loop_started 13.0.
     A path that ends 1.8 m short of the access (more than NavRoutePlanner.UnreachableM 0.5): no plan, event
     "no_path" at 1.2, the figure stands on (0, 0, 0) until the same heal at 10.6 (Entry 10.6, Loop 13.0).
     An access at y 3 over the floor mesh of height 0: the map's closest point (2.8, 0, 0) lies 3 m below it
     (>= the planner's storey tolerance 1.5 m), so it is no path either ("no_path" at 1.2, the figure stays on
     (0, 0, 0)) instead of a walk on the wrong storey and a final piece through the ceiling.

[11] frozen: at t 2.0 frozen for 3 s. The clock holds at the freeze moment: the walked length at 2.0 is
     (2.0 - 1.2) * 1.4 = 1.12 m and is still 1.12 m on resume at 5.0. States: Exit 0, Walk 1.2, Frozen 2.0,
     Walk 5.0, Entry 3.2 + 3 = 6.2, Loop 5.6 + 3 = 8.6 (the chain end moves by the frozen span). IssuedLocal
     stays 0.

LOCAL ORDERS AND ROWS
---------------------
[12] local_adopt (review W3.1): a local order "local:1" (sequence walk -> entry -> loop, no exit) from t 0
     with lag 0. At t 0.6 it is in Walk at 0.6 * 1.4 = 0.84 m. A server order "run-1" revision 1 with the
     same kind, location and anchor and an access 0.3 m beside it ((2.8, 0, 0.3); 0.3 > AccessDiffM 0.15)
     -> Accept true, Current.Id = "run-1", IssuedLocal 0, State Walk and the walked length unchanged, only the
     walk goal becomes (2.8, 0, 0.3). The accept comes before the tick of frame 0.6, i.e. the figure stands at
     frame 35: 35/60 * 1.4 = 0.81667; the tick of 0.6 walks on to 0.84. From (0.81667, 0, 0) the straight path to
     (2.8, 0, 0.3) is sqrt(1.98333^2 + 0.3^2) = 2.00589 m = 1.43278 s -> Entry at 35/60 + 1.43278 = 2.0161,
     Loop at 2.0161 + 2.4 = 4.4161 (frames 2.0167 / 4.4167, inside +-1/60).
     With an access 0.1 m beside it (0.1 <= 0.15) the walk goal stays (2.8, 0, 0): Entry 2.8 / 1.4 = 2.0,
     Loop 4.4. With another target (access and anchor 2 m away in z) it is case 1: a new clock
     IssuedLocal = 0.6 - 0 = 0.6; at the frame of the accept the new chain is 0 s old, so the walked length is 0
     and the figure stands where it was shown (x 0.8167), walk goal (2.8, 0, 2).

[13] row_without_order (decision 6, N1): a server order with seq 7 in Loop; a row without order and
     order_seq 7 >= 7 -> event "ended", Idle (the bridge blends into the row's rest placement); a second such
     row changes nothing. row_without_order_stale: seq 7 in Walk, a row with order_seq 6 < 7 -> no-op, State
     and walked length unchanged, the chain ends as in [1]. row_without_order_local: "local:1" in Walk,
     order_seq 99 -> no-op (the server never knows local:n): Walk 0, Entry 2.0, Loop 4.4.
     For [13] row_without_order the events are those of [1] with lag 0 plus "ended" at 6.0; for the stale row
     (at 2.0) the walked length read at 2.0 is (2.0 - 1.2) * 1.4 = 1.12.

[14] link_refused: ground floor y 0 for x < 3, upper floor y 3 from x 3; the map answers start -> access
     (4, 3, 0) with (0,0,0) -> link foot (1,0,0) -> link head (3,3,0) -> (4,3,0), the link owned by stair
     flight 0. Sequence without exit: the figure reaches the link foot after 1.0 / 1.4 = 0.714 s, frame 43
     (0.7167); the ride answers Refused -> event link_refused, State Abort at 43/60 on (1, 0, 0) (event
     aborted in the same frame), Idle at 44/60. Path length 1 + sqrt(2^2 + 3^2) + 1 = 5.605551275463989.
     In the vector the map is {height_step: [3, 3], answers: [...]} and the ride table {"stairs": "Refused"}.
```
