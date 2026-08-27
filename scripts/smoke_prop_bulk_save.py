#!/usr/bin/env python3
"""Smoke run for the prop detail's BATCH SAVE (``props.bulk_update``, 2026-08-25).

Usage:  ./.venv/bin/python scripts/smoke_prop_bulk_save.py

No world, no DB, no server: a throwaway props directory in /tmp gets a prop
written through the real store, and the batch is asked what it does to the
sidecar. Every expected value is derived BY HAND from the rules the field
routes already state, never from what the code currently prints.

---------------------------------------------------------------------------
[1] ONE REQUEST, ONE WRITE
---------------------------------------------------------------------------
That is the whole point of the batch. The panel used to write every field the
moment it lost focus, so authoring one variant — three metres, a subject, a
sink, a season, a marker — was SIX sidecar writes for one thought.

    the same six fields through the single-value setters   -> 6 writes
    the same six fields through `bulk_update`              -> 1 write

Counted by wrapping ``props._write_sidecar``. One is not "fewer", it is the
contract: a half-applied batch must not be a state the file can be in.

---------------------------------------------------------------------------
[2] THE SAME SANITATION, VERBATIM
---------------------------------------------------------------------------
A batch must never be a second, laxer way into the same record — the appliers
ARE the bodies of the single-value setters, so every law they state must hold
here. Hand-derived from those laws, all in ONE body:

    dims    {"width_m": 200}   -> 100.0    clamped to the (0, 100] window
    dims    {"depth_m": 0}     -> UNCHANGED (0.5)   nothing to inherit, so an
                                 unusable number costs the edit, not the size
    …and storing a size clears `dims_estimated` on that entry.

    ground_offset_m -9         -> -5.0     clamped, never refused
    ground_offset_m 0          -> NO KEY   "stands on the ground" IS absence
    description "   "          -> NO KEY   a blank line is not a statement
    markers  [junk, seat]      -> [seat]   invalid entries drop individually
    seasons  []                -> NO KEY   (which also puts variant 0 back in
                                 season, so it is the PRIMARY one again — [5]
                                 reads the record off it)

    general sway_factor 1.0    -> NO KEY   the default is stored as absence
    general tags "a, b, a"     -> ["a", "b"]   split + deduped case-insensitively
    general name "  "          -> UNCHANGED    a prop always has a name

---------------------------------------------------------------------------
[3] A REFUSAL WRITES NOTHING
---------------------------------------------------------------------------
Everything is checked BEFORE anything is stored (the ``plan_batch`` law), so a
body that is half junk cannot leave a half-saved prop behind — the admin would
have no way of telling which half arrived. Each of these raises ValueError (a
400 on the route) and leaves the sidecar BYTE-IDENTICAL, with zero writes:

    general  {"height_m": 2}      the moved-keys rule: the message names the
                                  variant route that owns the field now
    general  {"colour": "red"}    unknown prop field — refused, not ignored:
                                  a green "Saved" over a value that reached
                                  nothing is the worst of the three answers
    variants {"0": {"width_m": 2}}  a variant owns `dims`, not three loose
                                  metres — same rule one level down
    variants {"5": {...}}         this prop has two variants
    variants {"x": {...}}         a variant key is a STORE INDEX
    variants {"0": "nope"}        a patch is an object

    …and the good half of a body whose other half is junk is NOT written.

---------------------------------------------------------------------------
[4] AN EMPTY BODY IS A READ
---------------------------------------------------------------------------
Nothing to do writes nothing (0 writes) and still answers with the record, so
a Save with an empty draft can never move a file's mtime.

---------------------------------------------------------------------------
[5] THE ANSWER IS WHAT WAS STORED
---------------------------------------------------------------------------
The client adopts the answer instead of believing its own draft, so the answer
has to be the SAVED record: after [2] it says name "Long bench" and the primary
variant's clamped 100.0 m width. `sway_factor` reads back as the EFFECTIVE 1.0
even though the key is gone — that is the record's contract, and it is exactly
why the key itself is checked in the sidecar up in [2].
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

WORLD = Path(tempfile.mkdtemp(prefix="prop-bulk-smoke-"))
os.environ["STORAGE_DIR"] = str(WORLD)

from app.core import paths  # noqa: E402

paths.init(WORLD)

from app.core import props as store  # noqa: E402

FAILURES = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


class WriteCounter:
    """Counts the sidecar writes of whatever runs inside the ``with``."""

    def __init__(self) -> None:
        self.n = 0

    def __enter__(self) -> "WriteCounter":
        self._real = store._write_sidecar

        def counting(prop_id, meta):
            self.n += 1
            return self._real(prop_id, meta)

        store._write_sidecar = counting
        return self

    def __exit__(self, *exc) -> None:
        store._write_sidecar = self._real


def refused(label: str, **kwargs) -> None:
    """The body must raise AND leave the sidecar untouched."""
    before = (store._sidecar_path(BENCH) or Path()).read_text(encoding="utf-8")
    with WriteCounter() as w:
        try:
            store.bulk_update(BENCH, **kwargs)
            check(label, False, "no ValueError")
            return
        except ValueError as exc:
            reason = str(exc)
    after = (store._sidecar_path(BENCH) or Path()).read_text(encoding="utf-8")
    check(label, before == after and w.n == 0,
          f"{w.n} writes; {reason[:70]}")


def main() -> int:
    global BENCH
    print("[0] a prop with two variants")
    bench = store.create_prop(name="Bench", category="seating",
                              width_m=2.0, depth_m=0.5, height_m=0.9)["id"]
    BENCH = bench
    second = store.add_variant(bench)
    check("two variants", len(store.list_variants(bench)) == 2,
          str(len(store.list_variants(bench))))

    print("\n[1] one request, one write")
    seat = {"id": "seat1", "group": "seat", "at": [0.5, 0.5, 0.5]}
    with WriteCounter() as singles:
        store.update_prop(bench, {"name": "Bench"})
        store.set_variant_dims(bench, 0, {"width_m": 2.0})
        store.set_variant_description(bench, 0, "a bench")
        store.set_variant_ground_offset(bench, 0, -0.1)
        store.set_variant_seasons(bench, 0, ["Winter"])
        store.set_variant_markers(bench, 0, [seat])
    check("the single-value setters write once each", singles.n == 6,
          str(singles.n))
    with WriteCounter() as batch:
        store.bulk_update(
            bench,
            {"name": "Bench"},
            {"0": {"dims": {"width_m": 2.0}, "description": "a bench",
                   "ground_offset_m": -0.1, "seasons": ["Winter"],
                   "markers": [seat]}})
    check("the same six fields as a batch write ONCE", batch.n == 1,
          str(batch.n))

    print("\n[2] the same sanitation, verbatim")
    store.bulk_update(
        bench,
        {"name": "  ", "tags": "a, b, A", "sway_factor": 1.0,
         "category": "seating"},
        {"0": {"dims": {"width_m": 200, "depth_m": 0},
               "ground_offset_m": -9, "seasons": [],
               "markers": [{"group": "", "at": [0, 0, 0]}, seat]},
         "1": {"description": "   ", "ground_offset_m": 0, "seasons": []}})
    meta = store.read_sidecar(bench)
    v0, v1 = meta["model_variants"]
    check("200 m is clamped to the 100 m window", v0["width_m"] == 100.0,
          str(v0["width_m"]))
    check("a zero leaves the stored metre standing", v0["depth_m"] == 0.5,
          str(v0["depth_m"]))
    check("storing a size clears dims_estimated",
          v0["dims_estimated"] is False, str(v0.get("dims_estimated")))
    check("-9 m sinks to the -5 m limit", v0["ground_offset_m"] == -5.0,
          str(v0.get("ground_offset_m")))
    check("the invalid marker is dropped, the seat is kept",
          v0["markers"] == [{"id": "seat1", "group": "seat",
                             "at": [0.5, 0.5, 0.5]}],
          json.dumps(v0.get("markers")))
    check("a blank description writes NO key",
          "description" not in v1, json.dumps(v1))
    check("ground offset 0 writes NO key",
          "ground_offset_m" not in v1, json.dumps(v1))
    check("an empty season list writes NO key",
          "seasons" not in v1, json.dumps(v1))
    check("the default sway factor writes NO key",
          "sway_factor" not in meta, json.dumps(meta.get("sway_factor")))
    check("the tags are split and deduped", meta["tags"] == ["a", "b"],
          json.dumps(meta.get("tags")))
    check("a blank name leaves the prop's name standing",
          meta["name"] == "Bench", meta.get("name"))
    # Variant 1 kept everything the ADD copied over — the batch touched three
    # of its fields and nothing else.
    check("an untouched field of a patched variant survives",
          v1["width_m"] == 2.0, str(v1.get("width_m")))

    print("\n[3] a refusal writes nothing")
    refused("a moved field in the general half names the variant route",
            general={"height_m": 2})
    refused("an unknown prop field is refused, not ignored",
            general={"colour": "red"})
    refused("a loose metre on a variant is refused — a variant owns `dims`",
            variants={"0": {"width_m": 2}})
    refused("an index this prop has no variant for",
            variants={"5": {"description": "x"}})
    refused("a variant key that is not a store index",
            variants={"x": {"description": "x"}})
    refused("a patch that is not an object", variants={"0": "nope"})
    refused("the good half of a half-junk body is not written either",
            general={"name": "Never stored"},
            variants={"0": {"nonsense": 1}})

    print("\n[4] an empty body is a read")
    with WriteCounter() as empty:
        rec = store.bulk_update(bench)
    check("nothing to do writes nothing", empty.n == 0, str(empty.n))
    check("…and still answers with the record", (rec or {}).get("id") == bench)
    check("an unknown prop is None", store.bulk_update("nope-there") is None)

    print("\n[5] the answer is what was stored")
    answer = store.bulk_update(bench, {"name": "Long bench"})
    check("the name the batch just stored", answer["name"] == "Long bench",
          str(answer.get("name")))
    check("the primary variant's clamped width", answer["width_m"] == 100.0,
          str(answer.get("width_m")))
    check("and the sway factor reads back as the full amount",
          answer.get("sway_factor") == 1.0, str(answer.get("sway_factor")))

    print()
    if FAILURES:
        print(f"FAILED ({len(FAILURES)}): " + "; ".join(FAILURES))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        import shutil
        shutil.rmtree(WORLD, ignore_errors=True)
