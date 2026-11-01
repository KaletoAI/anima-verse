#!/usr/bin/env python3
"""An [INTENT:] whose title is an intent id re-states that plan; it creates nothing.

Usage: ./.venv/bin/python scripts/smoke_intent_id_title.py

On 2026-11-01 a tool model answered
``[INTENT: 998d3b40 | Go to the inn | when=now | prio=3 | by=self]`` for the
listed open plan 998d3b40 and a second plan titled "998d3b40" was created
(24 such rows in one world's log). Hand-derived from
``intents.parse_and_apply_intent_markers``:

  [1] "sample" owns the active plan "Go to the inn" (id I). The marker
      ``[INTENT: I | Go to the inn | when=now …]`` creates nothing: returns [],
      "sample" still has exactly one intent. (Fails on 2d33fa51: one created.)
  [2] The id of a COMPLETED intent as title creates nothing either.
  [3] An ordinary title next to it in the same text is still created:
      ``[INTENT: Bake bread | …]`` -> one intent titled "Bake bread".

All storage is temporary; paths.init precedes every world-DB import.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import paths  # noqa: E402

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}" + ("" if ok else f" — expected {want!r}"))
    if not ok:
        FAILS.append(label)


with tempfile.TemporaryDirectory(prefix="intent-id-title-") as storage:
    paths.init(Path(storage))
    from app.core import config, db
    config.load(Path(storage) / "config.json")
    db.init_schema()
    from app.models import intents

    plan = intents.create_own_intent("sample", "Go to the inn")
    pid = plan["id"]
    print("[1] the open plan's id as title")
    created = intents.parse_and_apply_intent_markers(
        "sample", f"[INTENT: {pid} | Go to the inn | when=now | prio=3 | by=self]")
    check("created", created, [])
    check("titles", sorted(i["title"] for i in intents.list_intents(owner="sample")), ["Go to the inn"])

    print("[2] a completed intent's id as title")
    done = intents.create_own_intent("sample", "Feed the cat")
    intents.complete_intent_as("sample", done["id"])
    created = intents.parse_and_apply_intent_markers(
        "sample", f"[INTENT: {done['id']} | Feed the cat | when=standing]")
    check("created", created, [])

    print("[3] an ordinary title beside it")
    created = intents.parse_and_apply_intent_markers(
        "sample", f"[INTENT: {pid} | Go to the inn | when=now]\n"
                  "[INTENT: Bake bread | for the guests | when=standing | prio=3 | by=self]")
    check("created titles", [i["title"] for i in created], ["Bake bread"])

print("FAIL: " + ", ".join(FAILS) if FAILS else "ALL OK")
sys.exit(1 if FAILS else 0)
