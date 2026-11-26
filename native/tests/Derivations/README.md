# Derivation documents

A file here is the `source` of one or more shared test vectors
(`shared/test-vectors/<name>.json`) whose logic, after E3 deletes the browser scene, exists only
natively. It holds the hand derivation of every number in those vectors; the C# vector tests
execute the cases. The rule and the guard are in `shared/test-vectors/README.md` (Rules) and
`scripts/smoke_vector_sources.py`.

One document per former source smoke (`<basis>.md` for the browser scene's deleted `smoke_<basis>.mjs`),
even when that smoke fed several vector files.

## Format

1. **Head** — three facts, one line each:
   - `Origin:` the old source and the commit it was taken from, `<old source> @ <PIN>`
     (PIN = `011cd048aa3cc2937186d7f35d2203af9491db8a`);
   - `Executed by:` the C# file(s) under `native/tests/` that run the cases;
   - `Vectors:` the vector files, each written out as `shared/test-vectors/<name>.json` (the guard
     requires the literal file name).
2. **Derivation** — the old source's opening docstring, word for word, in one `text` code block
   (`./.venv/bin/python scripts/smoke_vector_sources.py --extract <old source>` prints it).
3. **Inline derivations** (optional) — further comment blocks of the smoke that contain an `[n]`
   mark a case label of the vector cites, each in its own `text` code block, in file order.

The derivation is never edited to match an implementation. It changes only when the spec changes,
and then the vector and the C# tests change with it.
