# clip_shift

- Origin: the `source` text of `shared/test-vectors/clip_shift.json` @ 011cd048aa3cc2937186d7f35d2203af9491db8a (the vector named a
  formula instead of a smoke; Task 99 of the clip-library work)
- Executed by: `native/tests/ClipShiftTests.cs` (core `native/Core/Figures/ClipShift.cs`)
- Vectors: `shared/test-vectors/clip_shift.json`

## Derivation

```text
Task 99: x=side/100*cos(yaw)+forward/100*sin(yaw), z=-side/100*sin(yaw)+forward/100*cos(yaw); absolute metres independent of figure height
```
