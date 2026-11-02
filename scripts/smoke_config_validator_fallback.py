#!/usr/bin/env python3
"""The routing coverage warning follows the fallback chain resolve_llm follows
(``llm_router.fallback_parent``). Standalone: no server, no world DB.

Usage: ./.venv/bin/python scripts/smoke_config_validator_fallback.py

Synthetic config: provider P, one enabled entry P/m with chat_stream@1.
A package task ``t_pack_narration`` is registered with fallback chat_stream,
``t_pack_orphan`` with fallback consolidation (itself unrouted).

Hand-derived — "Task '<id>' has no LLM entry" is warned for:
  * npc_talk          → no: npc_* → chat_stream, which has an entry;
  * t_pack_narration  → no: declared fallback chat_stream has an entry (the
    2026-11-02 report: intimacy_finale_narration);
  * consolidation     → yes: no entry and no fallback;
  * t_pack_orphan     → yes: its parent consolidation has no entry either;
  * chat_stream       → no: it has its own entry.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import llm_tasks  # noqa: E402
from app.core.config_validator import _check_llm_routing  # noqa: E402

FAILS = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: {got!r}" + ("" if ok else f" (want {want!r})"))
    if not ok:
        FAILS.append(label)


llm_tasks.register_plugin_task("t_pack_narration", {"label": "x", "category": "chat",
                                                    "fallback": "chat_stream"}, "smoke")
llm_tasks.register_plugin_task("t_pack_orphan", {"label": "y", "category": "chat",
                                                 "fallback": "consolidation"}, "smoke")
config = {"providers": [{"name": "P", "type": "openai", "api_base": "http://x"}],
          "llm_routing": [{"provider": "P", "model": "m", "enabled": True,
                           "tasks": [{"task": "chat_stream", "order": 1}]}]}
warned = {i["message"] for i in _check_llm_routing(config)}


def has(tid):
    return f"Task '{tid}' has no LLM entry" in warned


for tid, want in (("npc_talk", False), ("t_pack_narration", False), ("consolidation", True),
                  ("t_pack_orphan", True), ("chat_stream", False)):
    check(tid, has(tid), want)

print('\nFAILED: ' + ', '.join(FAILS) if FAILS else '\nall checks passed')
sys.exit(1 if FAILS else 0)
