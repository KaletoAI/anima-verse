#!/usr/bin/env python3
"""Measure operational + format quality of the A2 "fact supplier" LLM tasks.

Usage:
    ./.venv/bin/python scripts/analyze_a2_logs.py [--json]

Reads logs/llm_calls.jsonl (live window) and logs/archive/llm_calls_2026-07.jsonl
(month archive) WITHOUT touching any world.db. For every log line of the A2 tasks
(extraction, extraction_chat_state, consolidation, relationship_summary,
intro_memory) the actual template BRANCH is derived from the prompt text — the
log field `template` is worthless (always == task, see findings Q2).

Format discipline is measured against the REAL extraction of each caller
(app/routes/chat.py:2033, app/core/stat_effects.py:92, app/core/chat_engine.py:975,
app/core/story_engine.py:322, plugins/retrospect/skill.py:182), not against
json.loads.
"""
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILES = [
    ("live", ROOT / "logs" / "llm_calls.jsonl"),
    ("archive-2026-07", ROOT / "logs" / "archive" / "llm_calls_2026-07.jsonl"),
]
A2_TASKS = {"extraction", "extraction_chat_state", "consolidation",
            "relationship_summary", "intro_memory", "memory_consolidation"}


# --------------------------------------------------------------------------
# Branch matching — rules derive from shared/templates/llm/tasks/*.md
# --------------------------------------------------------------------------
_ROLE_PREFIX = re.compile(r"^\s*\[(system|user|assistant|human)\]\s*", re.I)


def branch_of(task: str, sysp: str, userp: str) -> str:
    # The queue worker joins the message list into one string with "[role] "
    # prefixes before it reaches the logger — strip them before matching.
    s = _ROLE_PREFIX.sub("", (sysp or "")).lstrip()
    u = _ROLE_PREFIX.sub("", (userp or "")).lstrip()
    if task == "extraction_chat_state":
        if s.startswith("You are a strict information extractor"):
            return "extraction_chat_state.md"
        if "You judge how a situation affects" in s:
            return "stat_effects.md"
        return "?unmatched"
    if task == "relationship_summary":
        if s.startswith("Analyze this exchange between two characters"):
            return "relationship_summary.md (JSON)"
        if s.startswith("You are a relationship analyst for fictional characters"):
            return "relationship_summary_pair.md (prose)"
        return "?unmatched"
    if task == "consolidation":
        if s.startswith("You summarize a scene that happened in a shared world"):
            return "consolidation_scene.md"
        if s.startswith("You compress a character's day into ONE short recap"):
            return "day_consolidation inline (no template)"
        if s.startswith("You help a fictional character reflect"):
            return "retrospect.md"
        if s.startswith("You are a creative story director"):
            return "story_arc_generation.md"
        if s.startswith("Story Arc:"):
            return "story_arc_advancement.md"
        if s.startswith("Closing story arc:"):
            return "story_arc_resolve.md"
        if "Write a short diary entry" in s:
            return "consolidation_daily_diary.md"
        if u.startswith("Summarize the day "):
            return "consolidation_daily.md"
        if u.startswith("Summarize the week "):
            return "consolidation_weekly.md"
        if u.startswith("Summarize the month "):
            return "consolidation_monthly.md"
        if u.startswith("Summarize what happened TODAY in this conversation"):
            return "consolidation_today.md"
        if u.startswith("Summarize the following conversation between"):
            return "consolidation_history_summary.md"
        return "?unmatched"
    if task == "extraction":
        return "extraction_memory.md"
    if task == "intro_memory":
        return "intro_memory.md"
    return task


# --------------------------------------------------------------------------
# Real caller extractions
# --------------------------------------------------------------------------
_SPECIALS = re.compile(r'<SPECIAL_\d+>|<\|[A-Z_]+\|>')


def extract_chat_state(content):
    """app/routes/chat.py:2032-2041 (identical shape in stat_effects.py:92)."""
    raw = (content or "").strip()
    m = re.search(r'\{.*\}', raw, re.DOTALL)
    if not m:
        return None, "no-json-found"
    try:
        return json.loads(m.group()), "regex"
    except json.JSONDecodeError:
        return None, "parse-error"


def extract_rel_json(content):
    """app/core/chat_engine.py:974-978 — note the NON-nesting regex."""
    raw = _SPECIALS.sub('', content or "").strip()
    m = re.search(r'\{[^}]+\}', raw, re.DOTALL)
    if not m:
        return None, "no-json-found"
    try:
        return json.loads(m.group(0)), "regex"
    except json.JSONDecodeError:
        return None, "parse-error"


def extract_story_arc(content):
    """app/core/story_engine.py:322-343."""
    cleaned = (content or "").strip()
    if cleaned.startswith("```"):
        cleaned = "\n".join(l for l in cleaned.split("\n")
                            if not l.strip().startswith("```"))
    try:
        return json.loads(cleaned), "direct"
    except json.JSONDecodeError:
        pass
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(cleaned[start:end + 1]), "regex"
        except json.JSONDecodeError:
            return None, "parse-error"
    return None, "no-json-found"


def extract_retrospect(content):
    """plugins/retrospect/skill.py:182-191."""
    cleaned = (content or "").strip()
    if cleaned.startswith("```"):
        cleaned = "\n".join(l for l in cleaned.split("\n")
                            if not l.strip().startswith("```"))
    m = re.search(r"\{[\s\S]+\}", cleaned)
    try:
        return json.loads(m.group(0) if m else cleaned), ("regex" if m else "direct")
    except Exception:
        return None, "parse-error"


def extract_memory_json(content):
    """app/core/memory_service.py:102-107."""
    c = (content or "").strip()
    if not c:
        return None, "empty"
    m = re.search(r"\{[\s\S]*\}", c)
    try:
        return (json.loads(m.group(0)), "regex") if m else (json.loads(c), "direct")
    except Exception:
        return None, "parse-error"


JSON_BRANCHES = {
    "extraction_chat_state.md": extract_chat_state,
    "stat_effects.md": extract_chat_state,
    "relationship_summary.md (JSON)": extract_rel_json,
    "story_arc_generation.md": extract_story_arc,
    "story_arc_advancement.md": extract_story_arc,
    "story_arc_resolve.md": extract_story_arc,
    "retrospect.md": extract_retrospect,
    "extraction_memory.md": extract_memory_json,
}

FENCE = re.compile(r"```")
THINK = re.compile(r"<think>|</think>|<thinking>|\[THINK\]|◁think▷", re.I)
# Reasoning leakage heuristic for models that put their reasoning INTO content
LEAK = re.compile(r"^\s*(okay|alright|let me|first,? I|the user (wants|is asking)|"
                  r"I need to|we need to|looking at)\b", re.I)


def pct(a, b):
    return f"{100.0 * a / b:.1f}%" if b else "n/a"


def quant(vals, q):
    if not vals:
        return None
    v = sorted(vals)
    i = min(len(v) - 1, int(round(q * (len(v) - 1))))
    return v[i]


def main():
    rows = []
    windows = {}
    for wname, path in FILES:
        if not path.exists():
            continue
        lo = hi = None
        n = 0
        for line in path.open(errors="replace"):
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            n += 1
            t = d.get("starttime") or ""
            if t:
                lo = t if lo is None or t < lo else lo
                hi = t if hi is None or t > hi else hi
            if d.get("task") in A2_TASKS:
                d["_window"] = wname
                rows.append(d)
        windows[wname] = (n, lo, hi)

    print("== Fenster ==")
    for w, (n, lo, hi) in windows.items():
        print(f"  {w}: {n} Zeilen, {lo} -> {hi}")
    print(f"  A2-Zeilen gesamt: {len(rows)}")

    by_branch = defaultdict(list)
    for d in rows:
        p = d.get("prompt") or {}
        b = branch_of(d.get("task"), p.get("system", ""), p.get("user", ""))
        d["_branch"] = b
        by_branch[(d.get("task"), b)].append(d)

    print("\n== Zweige ==")
    for (task, br), items in sorted(by_branch.items(), key=lambda kv: -len(kv[1])):
        wc = Counter(i["_window"] for i in items)
        print(f"  {task:24s} {br:38s} n={len(items):5d}  "
              f"live={wc['live']} arch={wc['archive-2026-07']}")

    print("\n== Kosten / Latenz / Format je Zweig ==")
    out = {}
    for (task, br), items in sorted(by_branch.items(), key=lambda kv: -len(kv[1])):
        tin = [i.get("tokens", {}).get("input", 0) for i in items]
        tout = [i.get("tokens", {}).get("output", 0) for i in items]
        dur = [i.get("duration_s", 0) for i in items]
        models = Counter(f"{i.get('provider','')}/{i.get('model','')}" for i in items)
        errs = [i for i in items if i.get("error")]
        empties = [i for i in items if not (i.get("response") or "").strip()]
        fr = Counter(i["finish_reason"] for i in items if "finish_reason" in i)
        n_fr = sum(fr.values())
        fences = sum(1 for i in items if FENCE.search(i.get("response") or ""))
        thinks = sum(1 for i in items if THINK.search(i.get("response") or ""))
        leaks = sum(1 for i in items if LEAK.match((i.get("response") or "")))

        rec = {
            "task": task, "branch": br, "n": len(items),
            "in_p50": quant(tin, .5), "in_p90": quant(tin, .9),
            "out_p50": quant(tout, .5), "out_p90": quant(tout, .9),
            "dur_p50": quant(dur, .5), "dur_p90": quant(dur, .9),
            "dur_max": max(dur) if dur else None,
            "models": models.most_common(4),
            "errors": len(errs), "empty": len(empties),
            "fences": fences, "think_tags": thinks, "prose_lead": leaks,
            "finish_reason": dict(fr), "finish_reason_n": n_fr,
            "fr_length": fr.get("length", 0),
        }

        fn = JSON_BRANCHES.get(br)
        if fn:
            direct = regex_only = fail = 0
            for i in items:
                c = i.get("response") or ""
                ok_direct = False
                try:
                    json.loads(c.strip())
                    ok_direct = True
                except Exception:
                    pass
                data, how = fn(c)
                if data is not None and ok_direct:
                    direct += 1
                elif data is not None:
                    regex_only += 1
                else:
                    fail += 1
            rec.update({"json_direct": direct, "json_regex": regex_only,
                        "json_fail": fail})
        out[(task, br)] = rec

        print(f"\n--- {task} / {br}  (n={rec['n']})")
        print(f"    in  P50/P90: {rec['in_p50']}/{rec['in_p90']}   "
              f"out P50/P90: {rec['out_p50']}/{rec['out_p90']}")
        print(f"    dur P50/P90/max: {rec['dur_p50']}/{rec['dur_p90']}/{rec['dur_max']} s")
        print(f"    models: {rec['models']}")
        print(f"    error={rec['errors']} empty={rec['empty']} fence={rec['fences']} "
              f"think={rec['think_tags']} prose_lead={rec['prose_lead']}")
        print(f"    finish_reason (n={n_fr}): {rec['finish_reason']}")
        if fn:
            n = rec["n"]
            print(f"    JSON: direkt={rec['json_direct']} ({pct(rec['json_direct'], n)})  "
                  f"nur-Regex={rec['json_regex']} ({pct(rec['json_regex'], n)})  "
                  f"kaputt={rec['json_fail']} ({pct(rec['json_fail'], n)})")

    if "--json" in sys.argv:
        Path("/tmp/a2_branches.json").write_text(
            json.dumps([{k: v for k, v in r.items()} for r in out.values()],
                       default=str, indent=1))
        print("\n(geschrieben: /tmp/a2_branches.json)")


if __name__ == "__main__":
    main()
