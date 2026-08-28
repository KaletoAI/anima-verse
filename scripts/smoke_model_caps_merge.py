#!/usr/bin/env python3
"""Smoke check for the model-capabilities consolidation (shared/config).

Usage:
    ./.venv/bin/python scripts/smoke_model_caps_merge.py

Runs without the server and without a world DB. Every expectation below is
derived BY HAND from the merge rules in
``app/core/model_capabilities_migration``:

  R1  suitability: the greater ``tested_date`` wins, regardless of file age.
  R2  suitability: an entry WITH a date beats one without.
  R3  suitability: equal dates -> the file with the greater mtime wins.
  R4  models: an entry carrying no information ({} or all-null/empty) is
      dropped, never migrated.
  R5  models: an informative entry beats an empty one for the same pattern,
      whichever file it came from.
  R6  models: two informative entries -> the greater mtime wins.
  R7  the shared file's own content competes under the same rules, so a
      newer result already present in git survives an older world file.
  R8  meta keys ("_default") are kept and follow mtime.
  R9  split_raw_outputs pulls every checks[].output out of the payload — the
      test replays real logged prompts, so those answers quote the world and
      must not reach the shared, committed file. Scores, verdicts, timings and
      the detail line stay.

Hand-derived numbers for the CASE below, before running anything:

  Sources (mtime): shared=100, worldA=200, worldB=300

  suitability
    prov::alpha   shared 2026-01-01 | A 2026-05-05 | B 2026-03-03
                  -> A wins (R1: 05-05 is the greatest date, even though B's
                     file is newer)
    prov::beta    A (no date) | B 2026-02-02          -> B wins (R2)
    prov::gamma   A 2026-04-04 | B 2026-04-04         -> B wins (R3, mtime 300)
    prov::delta   shared 2026-07-07 | B 2026-06-06    -> shared wins (R7)
                  => 4 suitability entries

  models
    empty-one     A {} | B {tool_calling:null,vision:null,notes_de:""}
                  -> dropped (R4)          => dropped_empty counts it once
    half-empty    A {} | B {vision:true}   -> B's entry survives (R5)
    both-full     A {notes_de:"a"} | B {notes_de:"b"} -> B wins (R6, mtime 300)
    from-shared   shared {tool_calling:true}          -> survives (R7)
    _default      shared {} | B {vision:false}        -> B wins (R8)
                  => 3 real patterns + 1 meta key, dropped_empty == 1

Exit code 0 = all expectations hold.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.model_capabilities_migration import (  # noqa: E402
    has_capability_info,
    merge_capability_sources,
    split_raw_outputs,
)

SHARED = ({
    "models": {
        "from-shared": {"tool_calling": True},
        "_default": {},
    },
    "suitability": {
        "prov::alpha": {"tested_date": "2026-01-01", "who": "shared"},
        "prov::delta": {"tested_date": "2026-07-07", "who": "shared"},
    },
}, 100.0)

WORLD_A = ({
    "models": {
        "empty-one": {},
        "half-empty": {},
        "both-full": {"notes_de": "a"},
    },
    "suitability": {
        "prov::alpha": {"tested_date": "2026-05-05", "who": "A"},
        "prov::beta": {"who": "A"},
        "prov::gamma": {"tested_date": "2026-04-04", "who": "A"},
    },
}, 200.0)

WORLD_B = ({
    "models": {
        "empty-one": {"tool_calling": None, "vision": None, "notes_de": ""},
        "half-empty": {"vision": True},
        "both-full": {"notes_de": "b"},
        "_default": {"vision": False},
    },
    "suitability": {
        "prov::alpha": {"tested_date": "2026-03-03", "who": "B"},
        "prov::beta": {"tested_date": "2026-02-02", "who": "B"},
        "prov::gamma": {"tested_date": "2026-04-04", "who": "B"},
        "prov::delta": {"tested_date": "2026-06-06", "who": "B"},
    },
}, 300.0)

failures = []


def check(label, actual, expected):
    if actual != expected:
        failures.append(f"{label}: expected {expected!r}, got {actual!r}")
        print(f"  FAIL  {label}: expected {expected!r}, got {actual!r}")
    else:
        print(f"  ok    {label} = {actual!r}")


print("has_capability_info (R4)")
check("empty dict", has_capability_info({}), False)
check("all null/empty", has_capability_info(
    {"tool_calling": None, "vision": None, "notes_de": ""}), False)
check("None", has_capability_info(None), False)
check("tool_calling false counts", has_capability_info({"tool_calling": False}), True)
check("vision true counts", has_capability_info({"vision": True}), True)
check("note counts", has_capability_info({"notes_de": "slow"}), True)
check("blank note does not", has_capability_info({"notes_de": "   "}), False)
check("tool_instruction counts",
      has_capability_info({"tool_instruction": "use tags"}), True)
check("tested_* counts", has_capability_info({"tested_score": "8/12"}), True)

print("\nmerge_capability_sources")
merged, stats = merge_capability_sources([SHARED, WORLD_A, WORLD_B])
suit = merged["suitability"]
models = merged["models"]

check("R1 greatest date wins", suit["prov::alpha"]["who"], "A")
check("R2 dated beats undated", suit["prov::beta"]["who"], "B")
check("R3 tie -> newer file", suit["prov::gamma"]["who"], "B")
check("R7 newer shared survives", suit["prov::delta"]["who"], "shared")
check("suitability count", len(suit), 4)

check("R4 empty pattern dropped", "empty-one" in models, False)
check("R5 informative beats empty", models["half-empty"], {"vision": True})
check("R6 newer file wins", models["both-full"]["notes_de"], "b")
check("R7 shared pattern survives", models["from-shared"], {"tool_calling": True})
check("R8 meta key follows mtime", models["_default"], {"vision": False})
check("pattern count (meta excluded)", stats["models"], 3)
check("dropped_empty", stats["dropped_empty"], 1)
check("stats suitability", stats["suitability"], 4)

print("\nidempotence: merging the result again changes nothing")
again, _ = merge_capability_sources([(merged, 400.0)])
check("models stable", again["models"], merged["models"])
check("suitability stable", again["suitability"], merged["suitability"])

print("\norder independence: sources in reverse yield the same payload")
rev, _ = merge_capability_sources([WORLD_B, WORLD_A, SHARED])
check("models order-independent", rev["models"], models)
check("suitability order-independent", rev["suitability"], suit)

print("\nsplit_raw_outputs (R9)")
WORLD_TEXT = "<a character walked to the shore and named a private plot point>"
payload = {
    "models": {"p": {"vision": True}},
    "suitability": {
        "prov::alpha": {
            "tested_date": "2026-05-05",
            "tested_score": "8/12",
            "tested_suitability": {
                "model": "prov::alpha",
                "checks": [
                    {"id": "thought_1", "label": "thought #1", "ok": True,
                     "detail": "3/3 runs ok", "output": WORLD_TEXT},
                    {"id": "thought_2", "label": "thought #2", "ok": False,
                     "detail": "0/3 runs ok", "output": ""},
                ],
            },
        },
        "prov::beta": {"tested_date": "2026-01-01"},
    },
}
before = json.dumps(payload)
clean, outs = split_raw_outputs(payload)

check("world text gone from payload", WORLD_TEXT in json.dumps(clean), False)
check("no output key left", '"output"' in json.dumps(clean), False)
check("extracted per model", outs, {"prov::alpha": {"thought_1": WORLD_TEXT}})
check("empty output not extracted", "thought_2" in outs["prov::alpha"], False)
checks = clean["suitability"]["prov::alpha"]["tested_suitability"]["checks"]
check("detail survives", checks[0]["detail"], "3/3 runs ok")
check("label survives", checks[0]["label"], "thought #1")
check("verdict survives", checks[1]["ok"], False)
check("score survives", clean["suitability"]["prov::alpha"]["tested_score"], "8/12")
check("entry without checks untouched",
      clean["suitability"]["prov::beta"], {"tested_date": "2026-01-01"})
check("models untouched", clean["models"], {"p": {"vision": True}})
check("input not mutated", json.dumps(payload), before)
check("second split is a no-op", split_raw_outputs(clean)[1], {})

if failures:
    print(f"\n{len(failures)} FAILURE(S)")
    sys.exit(1)
print("\nAll expectations hold.")
