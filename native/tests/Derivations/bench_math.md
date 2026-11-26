# bench_math

- Origin: the browser scene's deleted `smoke_bench_math.mjs` @ 011cd048aa3cc2937186d7f35d2203af9491db8a
- Executed by: `native/tests/BenchMathVectorTests.cs`
- Vectors: `shared/test-vectors/bench_math.json`

## Derivation

```text
/**
 * Smoke check for the STATISTICS of the render bench (the browser scene's benchStats.ts
 * — the pure part; the camera drive and the DOM readout need a browser).
 *
 * Usage:  node smoke_bench_math.mjs   (historical; the runner was deleted with the browser scene in E3)
 *
 * Hand-derived expectations (§ B5a: numbers, no snapshots):
 * [1] percentile — linear interpolation between ranks (p50 of 1,2,3,4 = 2.5)
 * [2] summarize — 4 frames of 10/20/30/40 ms: 0.1 s total, 40 fps mean
 *     (frames / seconds, NOT the mean of per-frame rates), frame-ms median 25,
 *     P95 38.5, cpu/gpu/calls/tris medians as given, gpuMs null when never
 *     resolved. Worked: p95 rank = 0.95 * (4 - 1) = 2.85, so frame ms
 *     30 + 0.85 * 10 = 38.5 and cpu (2,4,6,8) 6 + 0.85 * 2 = 7.7, cpu median 5;
 *     calls sorted 100,110,120,130 -> median 115, tris -> 1150; with gpuMs
 *     null,4,5,6 only 4,5,6 count -> median 5
 * [3] empty input yields zeros and nulls, never NaN
 *
 * The cases (inputs + expectations) live in shared/test-vectors/bench_math.json, shared with
 * the native client's C# tests; each case label starts with the [n] of its derivation above.
 */
```
