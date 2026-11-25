# clip_order

- Origin: `client3d/scripts/smoke_clip_order.mjs` @ 011cd048aa3cc2937186d7f35d2203af9491db8a
- Executed by: `native/tests/ClipLibraryVectorTests.cs`
- Vectors: `shared/test-vectors/clip_commit.json`

## Derivation

```text
/** [1] Hand calculation: w1, w2, i1, h1 arrive i1, h1, w2, w1.
 * List order chooses w1 for walk/A, with loop=true. Losing w1 chooses w2
 * with loop=false. Pair roots and root-motion survive. The pair roots are
 * taken from the committed index (`pairRootsOf`), keyed by kind AND set: a
 * second handshake__a file in the same (neutral) set loses its slot AND its
 * root (h1 stays, not h2); the b-half stays independent. Missing results
 * leave gaps.
 * [2] Sets (2026-11-20 fix, client3d/scripts/smoke_pair_root_sets.mjs [A]):
 * hug__a in set "female" (f1), in "male" (m1), in "male" again (m2, loses:
 * first wins), hug__b in "" (n1), walk in "" (w1). Roots: hug__a/female =
 * root:f1, hug__a/male = root:m1. `pairRootFor` along a set chain (the
 * character's sets, then ""): [male, ""] → root:m1, [female, ""] → root:f1,
 * [elf, ""] → none (null: no neutral hug__a), hug__b with [male, ""] →
 * root:n1 (the neutral file).
 * [3] A solo kind (walk) has no pair-root entry.
 */
```
