# figure_clips

- Origin: the browser scene's deleted `smoke_figure_clips.mjs` @ 011cd048aa3cc2937186d7f35d2203af9491db8a
- Executed by: `native/tests/FigureClipsVectorTests.cs`
- Vectors: `shared/test-vectors/figure_clips.json`

## Derivation

```text
/**
 * Figure clip decisions as pure functions — the rules both the browser and the
 * native client follow: pose → played clip, movement type → clip, which
 * transition clip bridges two clips, and how fast a bridge lets the figure go.
 * The server tables (`movement_poses`, `transition_clips` of the clip library)
 * are explicit arguments here; the module-state defaults of game/walk.ts are
 * checked to agree with them at the end.
 *
 * Usage:  node the browser scene's deleted smoke_figure_clips.mjs
 * Cases:  shared/test-vectors/figure_clips.json (format anima-test-vectors/1).
 *
 * Hand derivations (game/walk.ts, scene/clipCoverage.ts). Pose defaults:
 * standing idle, walking walk, running run, swimming breast-stroke,
 * treading_water treading-water, crawling crawl, crawling_rest crawl-rest.
 *
 * [1] resolveMovementPoses(null): no source entry, so every pose gets its
 *     default as both kind and publicKind.
 * [2] RAW_SERVER: walking " MOB1-Walk " trims and lower-cases to mob1-walk,
 *     public walk; standing as given; running kind " " is blank and
 *     public_kind 42 no string -> both default run; crawling null -> crawl;
 *     the four poses not named -> defaults. That table is POSES_SERVER.
 * [3] A string is no object: all defaults, standing idle.
 * [4] moveClip: swim -> swimming, crawl -> crawling, else running only when
 *     canRun (walk_run) AND running, otherwise walking. Default table:
 *     walk_run/false walk, walk_run/true run, walk/true walk (walk never
 *     runs), swim breast-stroke, crawl crawl. Server table: walking mob1-walk,
 *     running fell back to run in [2].
 * [5] idleClip: swim -> treading_water (treading-water), crawl ->
 *     crawling_rest (crawl-rest), every other movement ''.
 * [6] standingClipFor = groundIdle || animation || standing kind:
 *     (null,'') server mob1-stand-relaxed-idle-v2, default idle;
 *     ('sit','') sit; ('sit','treading-water') the ground wins.
 * [7] movementOf: the four words pass outside a built place, a built place
 *     is always walk_run, anything else walk_run. canRun only for walk_run.
 * [8] movementPoseOf: played kind first, then public kind, input trimmed and
 *     lower-cased. Server: mob1-walk -> walking, walk -> walking (public),
 *     " Idle " -> standing (public idle), dance -> ''. Default table: no pose
 *     plays or publishes mob1-walk -> ''.
 * [9] resolveClipTransitions(RAW_TABLE): " Sleeping " -> sleeping, accel 0;
 *     (sitting, *) without accel -> 0; (*, sitting) accel "x" -> 0; (standing, walking)
 *     accel 1; (standing, *) accel 12 capped to 8; empty from, missing kind,
 *     null and a string are dropped -> the five rows of TABLE. A non-list
 *     -> [].
 * [10] clipTransition over TABLE, order exact > exit (from, *) > enter (*, to):
 *     sleeping->standing exact get-up-bed; " Sitting "->walking exit
 *     get-up-chair; standing->sitting has exit (standing, *) AND enter (*, sitting),
 *     exit wins -> stretch; walking->sitting enter sit-down; standing->walking
 *     exact walk although (standing, *) exists; same clip, empty from and the
 *     dropped lying row -> null.
 * [11] bridgePace = 0 for accel <= 0, else min(1, max(.02, accel * e)) with a
 *     negative elapsed taken as 0: (0,5) 0; (-1,1) 0; (1,0) .02; (1,-3) .02;
 *     (1,.5) .5; (2,.005) max(.02,.01) .02; (.5,4) min(1,2) 1.
 * [12] clipKindChain steps: want, public kind of want's pose, CLIP_FALLBACK of
 *     want, of the public kind, of the family, standing kind, standing public,
 *     idle — blanks and repeats dropped. CLIP_FALLBACK: run/swim/crawl ->
 *     walk, lie -> sit, crawl-rest/treading-water -> idle, swim-idle -> swim.
 *     swim (default): no pose plays "swim" -> swim, walk, idle.
 *     mob1-walk (server): pose walking, public walk, family mob1 has no
 *     fallback -> mob1-walk, walk, mob1-stand-relaxed-idle-v2, idle.
 *     '' -> idle, which is standing's kind -> idle.
 *     treading-water -> itself, fallback idle.
 *     run-fast: family run -> walk -> run-fast, walk, idle.
 * [13] resolveClipKind: first chain step matchAnimKind finds (exact, else
 *     family base, else the first relative; entry returned as passed in).
 *     mob1-walk on [idle, walk-cmu]: mob1-walk nothing, walk -> relative
 *     walk-cmu. swim on [Idle, walk]: swim nothing, walk exact.
 *     run-fast on [run, run-fast-2]: no exact, run is the family base -> run.
 *     dance on [sit]: chain dance, idle; nothing -> ''.
 *     treading-water on [Idle]: idle matches "Idle" -> "Idle".
 * [14] proceduralGait: walking pose -> walk, running pose -> run, else the
 *     family run/walk, else null. mob1-walk: server walking -> walk, default
 *     family mob1 -> null; run -> run; run-fast family run; walk-cmu family
 *     walk; idle null; breast-stroke is swimming, family breast -> null.
 */
```
