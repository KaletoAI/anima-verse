# overview_labels

- Origin: `client3d/scripts/smoke_overview_labels.mjs` @ 011cd048aa3cc2937186d7f35d2203af9491db8a
- Executed by: `native/tests/OverviewLabelsVectorTests.cs`
- Vectors: `shared/test-vectors/overview_labels.json`

## Derivation

```text
/**
 * Smoke check for the labels over the world map and the overview auto-close of
 * the open view — client3d/src/scene/nameTags.ts and client3d/src/game/openView.ts.
 *
 * Usage:  node client3d/scripts/smoke_overview_labels.mjs
 *
 * Hand derivations (cases in shared/test-vectors/overview_labels.json, shared
 * with the native client's C# tests):
 * [V] tagVisible(camDist, hidden, ownFirstPerson) = !hidden && !own && camDist < 55:
 *     40 and 54.999 -> true; 55 is not < 55 -> false; 60 -> false; a hidden figure
 *     at 10 m -> false; the camera's own first-person body at 1 m -> false.
 * [T] tagTravelling(travel) = !!travel && !travel.starts_in_s: null -> false;
 *     starts_in_s 0 and null are falsy -> true; 12 is truthy (the start lies ahead)
 *     -> false; an empty object is truthy and has no starts_in_s -> true.
 * [N] tagName(name, travel): not under way -> the name as it is; under way ->
 *     "🚶" + (eta_hhmm truthy ? " " + eta_hhmm : "") + " " + name:
 *     {0, "14:30"} -> "🚶 14:30 Ada"; {eta "07:05"} -> "🚶 07:05 Ada";
 *     {12, "14:30"} -> "Ada"; eta null or "" (falsy) -> "🚶 Cleo Marsh".
 * [A] tagAnchorY(h) = h + 0.45 over a model, -0.15 for a portrait (null):
 *     1.6 -> 2.05; 1.8 -> 2.25; null -> -0.15.
 * [L] locationLabelLift(h) = h + 2.2 (the label above the place's ground datum):
 *     4 -> 6.2; 0.6 -> 2.8; 3 -> 5.2.
 * [D] closeTargetDist(w) = max(12, 3·w): 2 -> 6 < 12 -> 12; 4 -> 12; 10 -> 30;
 *     0 -> 12.
 * [C] openViewShouldClose(camDist, tx, tz, cx, cz, w) = camDist > 60 ||
 *     hypot(tx - cx, tz - cz) > closeTargetDist(w), both strict:
 *     centre (10, -5), width 10 -> limit 30. Camera exactly 60 -> stays;
 *     60.0001 -> closes. Target (28, 19): offset (18, 24) -> hypot 30 exactly
 *     (3-4-5 x 6) -> not > 30 -> stays. Target (28, 19.5): offset (18, 24.5) ->
 *     sqrt(324 + 600.25) = sqrt(924.25) = 30.4015... -> closes. Target (-15, -5):
 *     offset 25 <= 30 with camera 59 <= 60 -> stays. A 1 m shrine at the origin:
 *     3·1 = 3 < 12 -> limit 12; offset (12, 0) -> stays, (12.01, 0) -> closes.
 *     Width 8 at (-40, 100) -> limit max(12, 24) = 24; target (-40, 76) is 24 off
 *     -> stays; (-40, 75.5) is 24.5 off -> closes.
 * [B] tagBadges(badges) — browser-only (no shared vector): text = the icons
 *     joined without a gap, title = the non-empty titles joined by "\n",
 *     key = text + "\u0001" + title. null and [] -> text "", title "", key
 *     "\u0001". [{🔒, "Private"}] -> "🔒" / "Private". [{🔒, "A"}, {⭐, ""}]
 *     -> "🔒⭐" / "A" (the empty title leaves no blank line). Same icons, other
 *     title -> other key (the span must be rewritten when only the state changed).
 */
```
