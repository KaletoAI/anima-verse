#!/usr/bin/env python3
"""explain_routing() against a synthetic config (plan-llm-routing-ui.md, Task 2).

Usage:
    ./.venv/bin/python scripts/smoke_llm_routing_explain.py

Standalone: no server, no world DB. Provider availability and cooldowns are
injected callables, so the resolver rule is tested, not the network.

Synthetic config:
  providers: A (available), B (UNavailable)
  entries:
    #0 A/m0 enabled  tasks chat_stream@1, intent@2
    #1 B/m1 enabled  tasks intent@1, consolidation@1
    #2 A/m2 DISABLED tasks chat_stream@2, translation@1
    #3 A/m3 enabled  tasks image_recognition@1   (m3 in cooldown 42 s)
  disabled (persistent): {"secret_generation"}; runtime_disabled: {"roof_design"}
  story_engine.enabled = False (gates story_stream off)
  embedding.backend = "internal", internal_model = "BAAI/bge-small-en-v1.5"

Expected (by hand from the resolver rule):
  1. chat_stream: via direct, resolved #0 order 1, chain has ONE row (entry #2
     is disabled → not a candidate; chain lists only enabled candidates).
  2. intent: via direct, resolved #0 order 2, reason mentions "order 1 skipped:
     provider unavailable"; chain[0].skipped == "provider unavailable",
     chain[1].skipped is None.
  3. consolidation: via none — only candidate is on B (unavailable);
     resolved None; reason "no LLM in chain".
  4. translation: via none, resolved None, chain [] (only holder disabled);
     fallback None.
  5. furnish: via fallback, resolved #0 (from intent, order 2),
     resolved.via_task == "intent", fallback == "intent".
  6. npc_talk: via fallback, resolved #0 via_task "chat_stream".
  7. image_recognition: via none — sole candidate in model cooldown;
     chain[0].skipped == "model cooldown".
  8. story_stream: via gated_off, resolved None, gated_off True.
  9. secret_generation: via disabled, disabled True.
 10. roof_design: via disabled, runtime_disabled True.
 11. pose_embedding: via direct, resolved None, reason startswith "built-in".
 12. entries[3].model_cooldown_s == 42 (rounded), entries[2].enabled False,
     entries[1].provider_available False; providers has 2 rows.
 13. Every task in TASK_TYPES appears exactly once in result["tasks"].

Lane pools (one `max_concurrent` per provider+model — second config):
  entries: P/gem on lanes 3 · P/gem on (no value) · P/gem OFF lanes 8 ·
           P/big on lanes 2 · Q/gem on lanes "x" (unreadable)
 14. lane_count_in = highest value among the ENABLED entries of the pair:
     P/gem → max(3, 1) = 3 (the disabled 8 does not count), P/big → 2,
     Q/gem → 1 (unreadable = one lane), P/none → 1 (no entry).
 15. explain_routing reports the POOL's number on every entry, not the
     entry's own field: lanes == [3, 3, 3, 2, 1] — the entry without a value
     and the disabled one both show the 3 their model runs with.
"""
from __future__ import annotations
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from types import SimpleNamespace
from app.core.llm_tasks import TASK_TYPES
from app.core.llm_router import explain_routing

FAILS: list[str] = []
def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond: FAILS.append(msg)

CFG = {
    "providers": [{"name": "A", "type": "openai", "enabled": True},
                  {"name": "B", "type": "openai", "enabled": True}],
    "llm_routing": [
        {"provider": "A", "model": "m0", "enabled": True,
         "tasks": [{"task": "chat_stream", "order": 1}, {"task": "intent", "order": 2}]},
        {"provider": "B", "model": "m1", "enabled": True,
         "tasks": [{"task": "intent", "order": 1}, {"task": "consolidation", "order": 1}]},
        {"provider": "A", "model": "m2", "enabled": False,
         "tasks": [{"task": "chat_stream", "order": 2}, {"task": "translation", "order": 1}]},
        {"provider": "A", "model": "m3", "enabled": True,
         "tasks": [{"task": "image_recognition", "order": 1}]},
    ],
    "story_engine": {"enabled": False},
    "embedding": {"backend": "internal", "internal_model": "BAAI/bge-small-en-v1.5"},
}
PROV = {"A": SimpleNamespace(available=True, type="openai"),
        "B": SimpleNamespace(available=False, type="openai")}
res = explain_routing(CFG, provider_lookup=PROV.get,
                      cooled_down=lambda p, m: 42.0 if (p, m) == ("A", "m3") else None,
                      disabled={"secret_generation"}, runtime_disabled={"roof_design"})
T = {t["task"]: t for t in res["tasks"]}

t = T["chat_stream"]; check(t["via"] == "direct" and t["resolved"]["index"] == 0 and len(t["chain"]) == 1, "1. chat_stream")
t = T["intent"]; check(t["via"] == "direct" and t["resolved"]["index"] == 0 and t["resolved"]["order"] == 2
                       and t["chain"][0]["skipped"] == "provider unavailable" and t["chain"][1]["skipped"] is None
                       and "order 1 skipped: provider unavailable" in t["reason"], "2. intent")
t = T["consolidation"]; check(t["via"] == "none" and t["resolved"] is None and t["reason"] == "no LLM in chain", "3. consolidation")
t = T["translation"]; check(t["via"] == "none" and t["chain"] == [] and t["fallback"] is None, "4. translation")
t = T["furnish"]; check(t["via"] == "fallback" and t["resolved"]["index"] == 0 and t["resolved"]["via_task"] == "intent" and t["fallback"] == "intent", "5. furnish")
t = T["npc_talk"]; check(t["via"] == "fallback" and t["resolved"]["via_task"] == "chat_stream", "6. npc_talk")
t = T["image_recognition"]; check(t["via"] == "none" and t["chain"][0]["skipped"] == "model cooldown", "7. image_recognition")
t = T["story_stream"]; check(t["via"] == "gated_off" and t["resolved"] is None and t["gated_off"] is True, "8. story_stream")
t = T["secret_generation"]; check(t["via"] == "disabled" and t["disabled"] is True, "9. secret_generation")
t = T["roof_design"]; check(t["via"] == "disabled" and t["runtime_disabled"] is True, "10. roof_design")
t = T["pose_embedding"]; check(t["via"] == "direct" and t["resolved"] is None and t["reason"].startswith("built-in"), "11. pose_embedding")
E = res["entries"]
check(round(E[3]["model_cooldown_s"]) == 42 and E[2]["enabled"] is False and E[1]["provider_available"] is False and len(res["providers"]) == 2, "12. entries/providers")
check(sorted(T) == sorted(TASK_TYPES) and len(res["tasks"]) == len(TASK_TYPES), "13. one row per catalog task")

from app.core.llm_lanes import lane_count_in
POOLS = {"providers": [{"name": "P", "type": "openai"}, {"name": "Q", "type": "openai"}],
         "llm_routing": [
    {"provider": "P", "model": "gem", "max_concurrent": 3, "tasks": []},
    {"provider": "P", "model": "gem", "tasks": []},
    {"provider": "P", "model": "gem", "enabled": False, "max_concurrent": 8, "tasks": []},
    {"provider": "P", "model": "big", "max_concurrent": 2, "tasks": []},
    {"provider": "Q", "model": "gem", "max_concurrent": "x", "tasks": []}]}
R = POOLS["llm_routing"]
check([lane_count_in(R, "P", "gem"), lane_count_in(R, "P", "big"), lane_count_in(R, "Q", "gem"),
       lane_count_in(R, "P", "none")] == [3, 2, 1, 1], "14. lane_count_in folds per provider+model")
res2 = explain_routing(POOLS, provider_lookup=lambda n: None, cooled_down=lambda p, m: None,
                       disabled=set(), runtime_disabled=set())
check([e["lanes"] for e in res2["entries"]] == [3, 3, 3, 2, 1], "15. entries carry their pool's lanes")

print()
if FAILS: print(f"{len(FAILS)} check(s) failed"); sys.exit(1)
print("all checks passed")
