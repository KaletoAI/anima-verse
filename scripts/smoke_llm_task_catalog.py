#!/usr/bin/env python3
"""Guard for the LLM task catalog (plan-llm-routing-ui.md, Task 1).

Usage:
    ./.venv/bin/python scripts/smoke_llm_task_catalog.py

Runs standalone: no server, no world DB, no network. Imports app.core.llm_tasks,
app.core.llm_task_state and app.core.llm_router only.

Why: on 2026-09-13 the catalog carried four tasks that no code ever resolved
(send_message, talk_to, image_analysis, image_comment) — assigning a model to
them in the admin UI silently did nothing. This script makes that class of
defect fail loudly.

Checks (expected values derived by hand):
  1. None of the removed ids is in TASK_TYPES:
     send_message, talk_to, image_analysis, image_comment,
     furnish_needs, furnish_match, furnish_place.
  2. "furnish" IS in TASK_TYPES with category "tool" and requirements
     json True, min_context 8192, model_class "medium", creative True.
  3. Every TASK_TYPES id except "pose_embedding" has a non-empty
     requirements dict (npc_generate had none before this change).
  4. Every id named in llm_task_state.PRESETS exists in TASK_TYPES.
  5. fallback_parent table:
       furnish -> intent, prop_mount_classify -> intent,
       room_description_sync -> intent, npc_talk -> chat_stream,
       npc_generate -> chat_stream, extraction_chat_state -> extraction,
       intent_anything -> intent, chat_stream -> None, intent -> None,
       consolidation -> None.
  6. Dead-task guard: for every TASK_TYPES id, the literal string "<id>"
     (double-quoted) occurs in at least one .py file under app/ or plugins/
     OTHER THAN app/core/llm_tasks.py, app/core/llm_task_state.py and
     app/core/config_validator.py. (Every live task is passed as a string
     literal somewhere: llm_call(task="…"), resolve_llm("…"), a TASK
     constant, or a default argument.) "pose_embedding" counts via
     app/core/embedding.py; "storyteller" via app/models/storyteller.py.
"""
from __future__ import annotations
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.core.llm_tasks import TASK_TYPES
from app.core.llm_task_state import PRESETS
from app.core.llm_router import fallback_parent

FAILS: list[str] = []
def check(cond: bool, msg: str) -> None:
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)

REMOVED = ["send_message", "talk_to", "image_analysis", "image_comment",
           "furnish_needs", "furnish_match", "furnish_place"]
for tid in REMOVED:
    check(tid not in TASK_TYPES, f"1. removed id absent: {tid}")

f = TASK_TYPES.get("furnish") or {}
req = f.get("requirements") or {}
check(f.get("category") == "tool", "2. furnish category tool")
check(req.get("json") is True and req.get("min_context") == 8192
      and req.get("model_class") == "medium" and req.get("creative") is True,
      "2. furnish requirements union")

for tid, t in TASK_TYPES.items():
    if tid == "pose_embedding":
        continue
    check(bool(t.get("requirements")), f"3. profile present: {tid}")

for name, ids in PRESETS.items():
    for tid in ids:
        check(tid in TASK_TYPES, f"4. preset {name} names catalog id: {tid}")

EXPECT = {"furnish": "intent", "prop_mount_classify": "intent",
          "room_description_sync": "intent", "npc_talk": "chat_stream",
          "npc_generate": "chat_stream", "extraction_chat_state": "extraction",
          "intent_anything": "intent", "chat_stream": None, "intent": None,
          "consolidation": None}
for tid, want in EXPECT.items():
    check(fallback_parent(tid) == want, f"5. fallback_parent({tid}) == {want!r}")

SKIP = {os.path.join("app", "core", "llm_tasks.py"),
        os.path.join("app", "core", "llm_task_state.py"),
        os.path.join("app", "core", "config_validator.py")}
sources: list[tuple[str, str]] = []
for base in ("app", "plugins"):
    for dp, _dn, fns in os.walk(os.path.join(ROOT, base)):
        for fn in fns:
            if fn.endswith(".py"):
                rel = os.path.relpath(os.path.join(dp, fn), ROOT)
                if rel in SKIP:
                    continue
                with open(os.path.join(dp, fn), encoding="utf-8", errors="replace") as fh:
                    sources.append((rel, fh.read()))
for tid in TASK_TYPES:
    needle = f'"{tid}"'
    hits = [rel for rel, src in sources if needle in src]
    check(bool(hits), f"6. live caller for {tid}: {hits[:2]}")

print()
if FAILS:
    print(f"{len(FAILS)} check(s) failed")
    sys.exit(1)
print("all checks passed")
