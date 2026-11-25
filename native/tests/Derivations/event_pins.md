# event_pins

- Origin: `client3d/scripts/smoke_event_pins.mjs` @ 011cd048aa3cc2937186d7f35d2203af9491db8a
- Executed by: `native/tests/OverviewLabelsVectorTests.cs`
- Vectors: `shared/test-vectors/event_pins.json`

## Derivation

```text
/**
 * Smoke check for the event pins of the world map — client3d/src/game/eventPins.ts.
 *
 * Usage:  node client3d/scripts/smoke_event_pins.mjs
 *
 * Hand derivations (cases in shared/test-vectors/event_pins.json, shared with
 * the native client's C# tests):
 * [G] pinGlyph: no list or an empty list -> null (no pin); any event whose
 *     category is 'danger' -> 🔥; any other event (also one without a
 *     category) -> ❗.
 * [Y] pinY(groundY, placeHeight) = groundY + placeHeight + PIN_LIFT_M 3.5:
 *     0 + 4 + 3.5 = 7.5; 42.25 + 4 + 3.5 = 49.75; -3 + 0.3 + 3.5 = 0.8;
 *     12 + 0 + 3.5 = 15.5. The ground term is the point of the fix: the pin
 *     used to float at placeHeight + 3.5 ABOVE SEA LEVEL, buried in a hill.
 */
```
