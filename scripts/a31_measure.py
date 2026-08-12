#!/usr/bin/env python3
"""A3.1 — read-only measurement of the tool/intent tasks from the LLM logs.

Usage:
    ./.venv/bin/python scripts/a31_measure.py [section]

Sections: m1 (intent tool-format discipline), m1b (Tool-LLM rows logged as
`thought`), m2 (spell_detect + furnish_*), m3 (perceive_action thoughts),
all (default).

Reads ONLY log files (logs/llm_calls.jsonl + logs/archive/llm_calls_*.jsonl).
Never touches world.db. Uses the production parser
(`app.core.tool_formats.find_tool_calls`) so the classification matches what
the runtime actually executed.
"""
import json
import re
import sys
import statistics
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.tool_formats import find_tool_calls  # noqa: E402

FILES = [
    ("2026-07", Path("logs/archive/llm_calls_2026-07.jsonl")),
    ("2026-08a", Path("logs/archive/llm_calls_2026-08.jsonl")),
    ("live", Path("logs/llm_calls.jsonl")),
]

# Tool list block that build_tool_instruction() writes into the system prompt.
_TOOLS_BLOCK = re.compile(r"=== AVAILABLE TOOLS ===\n(.*?)\n\s*\n?=== HOW TO USE",
                          re.DOTALL)
_TOOL_LINE = re.compile(r"^- ([A-Za-z_][\w]*):", re.MULTILINE)

# "no tool needed" marker demanded by the decision prompt.
_NONE_RE = re.compile(r"(?:^|\n)\s*(?:NONE|None)\s*(?:[.!]|$)", re.MULTILINE)

# Meta / reasoning prose the STRICT OUTPUT block explicitly forbids.
_META_RE = re.compile(
    r"\b(Based on|We need to|Let me|Let's|I need to|Looking at|First,|"
    r"The character (?:has|did|does|is)|The user (?:said|asked)|"
    r"Okay,|Alright,|So,? the|Analysis|Analyzing|Reasoning|Step 1|"
    r"Therefore|Thus,|In summary|Note that)\b")

# Tool-ish output the parser does NOT accept (the "near miss" bucket).
_NEARMISS_PATTERNS = [
    ("square_bracket_call", re.compile(r"\[\s*(?:INTENT|TOOL|TOOLS?)\s*[:=]", re.I)),
    ("tools_header", re.compile(r"^\s*(?:TOOLS?|TOOL CALLS?)\s*:", re.M | re.I)),
    ("markdown_toolname", re.compile(r"\*\*\s*(?:use\s+)?[A-Z]\w+\s*\*\*\s*(?:\(|:)")),
    ("json_call", re.compile(r'"(?:tool|tool_name|name)"\s*:\s*"')),
    ("bare_tag_no_name", re.compile(r"<tool>\s*", re.I)),
    ("xml_selfnamed", re.compile(r"<([A-Z]\w+)>[\s\S]*?</\1>")),
    ("func_call_syntax", re.compile(r"\b[A-Z]\w+\((?:[^)]{0,120})\)")),
]

_MARKER_RE = re.compile(r"\*\*\s*I (?:feel|do|am at)\b[^*]*\*\*", re.I)


def load(task_filter=None, role_filter=None):
    rows = []
    for bucket, path in FILES:
        if not path.exists():
            continue
        for lineno, line in enumerate(path.open(encoding="utf-8", errors="replace"), 1):
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            if task_filter and d.get("task") not in task_filter:
                continue
            if role_filter and d.get("llm_role") not in role_filter:
                continue
            d["_bucket"] = bucket
            d["_file"] = str(path)
            d["_line"] = lineno
            rows.append(d)
    return rows


def sysprompt(d):
    p = d.get("prompt") or {}
    if isinstance(p, dict):
        s = p.get("system") or ""
        if s:
            return s
        for m in (p.get("messages") or []):
            if m.get("role") == "system":
                return m.get("content") or ""
    return ""


def userprompt(d):
    p = d.get("prompt") or {}
    if isinstance(p, dict):
        u = p.get("user")
        if u:
            return u
        for m in reversed(p.get("messages") or []):
            if m.get("role") == "user":
                return m.get("content") or ""
    return ""


def known_tools(d):
    m = _TOOLS_BLOCK.search(sysprompt(d))
    if not m:
        return {}
    return {n: 1 for n in _TOOL_LINE.findall(m.group(1))}


def classify(d):
    resp = (d.get("response") or "")
    err = (d.get("error") or "").strip()
    kt = known_tools(d)
    matches = find_tool_calls("tag", resp, kt or None) if resp.strip() else []
    stripped = resp.strip()
    meta = bool(_META_RE.search(stripped))
    if err:
        return "c_error", matches, meta, kt
    if not stripped:
        return "c_empty", matches, meta, kt
    if matches:
        return "a_toolcall", matches, meta, kt
    # remove marker lines, then look for NONE
    body = _MARKER_RE.sub("", stripped).strip()
    if _NONE_RE.search(body) or body.upper() in ("NONE", "NONE."):
        return "b_none", matches, meta, kt
    if meta:
        return "e_reasoning", matches, meta, kt
    return "d_prose", matches, meta, kt


def pct(n, tot):
    return f"{100.0*n/tot:.1f}%" if tot else "-"


def quantiles(vals):
    if not vals:
        return (0, 0)
    vals = sorted(vals)
    def q(p):
        i = min(len(vals) - 1, int(round(p * (len(vals) - 1))))
        return vals[i]
    return (q(0.5), q(0.9))


def report_population(name, rows):
    print(f"\n{'='*70}\n{name}  (n={len(rows)})\n{'='*70}")
    cats = Counter()
    by_model = defaultdict(Counter)
    by_month = defaultdict(Counter)
    lat = []
    tin = []
    fr = Counter()
    fr_missing = 0
    nearmiss = Counter()
    nearmiss_rows = defaultdict(list)
    toolnames = Counter()
    multi = Counter()
    examples = defaultdict(list)
    for d in rows:
        cat, matches, meta, kt = classify(d)
        cats[cat] += 1
        model = d.get("model") or "?"
        month = (d.get("starttime") or "")[:7]
        by_model[model][cat] += 1
        by_month[month][cat] += 1
        if d.get("duration_s"):
            lat.append(float(d["duration_s"]))
        t = d.get("tokens") or {}
        if t.get("input"):
            tin.append(int(t["input"]))
        if "finish_reason" in d:
            fr[d.get("finish_reason") or "(empty-string)"] += 1
        else:
            fr_missing += 1
        for n, _i in matches:
            toolnames[n] += 1
        if matches:
            multi[len(matches)] += 1
        if cat in ("d_prose", "e_reasoning"):
            hit = False
            for label, rx in _NEARMISS_PATTERNS:
                if rx.search(d.get("response") or ""):
                    nearmiss[label] += 1
                    nearmiss_rows[label].append((d["_file"], d["_line"]))
                    hit = True
            if not hit:
                nearmiss["none_of_the_above"] += 1
                nearmiss_rows["none_of_the_above"].append((d["_file"], d["_line"]))
        if len(examples[cat]) < 6:
            examples[cat].append((d["_file"], d["_line"], model,
                                  (d.get("response") or "")[:220].replace("\n", "\\n")))
    tot = len(rows)
    print("\n-- Classification --")
    for k in ("a_toolcall", "b_none", "c_empty", "c_error", "d_prose", "e_reasoning"):
        print(f"  {k:14s} {cats.get(k,0):5d}  {pct(cats.get(k,0), tot)}")
    print("\n-- by model --")
    for m, c in sorted(by_model.items(), key=lambda x: -sum(x[1].values())):
        n = sum(c.values())
        print(f"  {m:38s} n={n:5d}  " + " ".join(
            f"{k[0]}={c.get(k,0)}" for k in
            ("a_toolcall", "b_none", "c_empty", "c_error", "d_prose", "e_reasoning")))
    print("\n-- by month --")
    for m, c in sorted(by_month.items()):
        n = sum(c.values())
        print(f"  {m}  n={n:5d}  a={c.get('a_toolcall',0)} b={c.get('b_none',0)} "
              f"empty={c.get('c_empty',0)} err={c.get('c_error',0)} "
              f"prose={c.get('d_prose',0)} reason={c.get('e_reasoning',0)}")
    p50, p90 = quantiles(lat)
    print(f"\n-- latency  P50={p50:.2f}s  P90={p90:.2f}s  n={len(lat)}  max={max(lat) if lat else 0:.2f}s")
    p50, p90 = quantiles(tin)
    print(f"-- input tokens  P50={p50}  P90={p90}  n={len(tin)}")
    print(f"-- finish_reason (rows WITH field: {sum(fr.values())}, without: {fr_missing})")
    for k, v in fr.most_common():
        print(f"     {k:20s} {v:5d}  {pct(v, sum(fr.values()))}")
    print(f"-- tools called: {dict(toolnames.most_common(20))}")
    print(f"-- calls per response: {dict(sorted(multi.items()))}")
    print("\n-- near-miss shapes in prose/reasoning rows --")
    for k, v in nearmiss.most_common():
        print(f"     {k:22s} {v:4d}   e.g. {nearmiss_rows[k][:3]}")
    print("\n-- examples --")
    for k in ("c_empty", "c_error", "d_prose", "e_reasoning", "b_none", "a_toolcall"):
        for f, ln, m, txt in examples.get(k, []):
            print(f"  [{k}] {f}:{ln} {m}\n       {txt}")
    return cats


def m1():
    rows = load(task_filter={"intent"})
    report_population("M1 — task == 'intent' (rp_first tool phase of run_chat_turn)", rows)


def m1b():
    rows = load(task_filter={"thought"}, role_filter={"Tool-LLM"})
    report_population("M1b — llm_role == 'Tool-LLM' logged under task 'thought' "
                      "(same routing task `intent`)", rows)


def m2():
    rows = load(task_filter={"spell_detect", "furnish_select", "furnish_new",
                             "furnish_place"})
    print(f"\n{'='*70}\nM2 — spell_detect + furnish_*  (n={len(rows)})\n{'='*70}")
    for d in rows:
        resp = d.get("response") or ""
        print(f"\n--- {d['_file']}:{d['_line']}  task={d['task']} model={d.get('model')} "
              f"provider={d.get('provider')} dur={d.get('duration_s')}s "
              f"tokens={d.get('tokens')} finish={d.get('finish_reason', '(missing)')} "
              f"err={d.get('error','')!r}")
        print(f"    SYSTEM[:300]: {sysprompt(d)[:300]!r}")
        print(f"    USER[:400]:   {userprompt(d)[:400]!r}")
        print(f"    RESPONSE:     {resp[:900]!r}")
        # JSON check like the consumers do
        s = resp.strip()
        s2 = re.sub(r"^```(?:json)?|```$", "", s, flags=re.M).strip()
        m = re.search(r"[\{\[][\s\S]*[\}\]]", s2)
        try:
            obj = json.loads(m.group(0) if m else s2)
            print(f"    JSON: OK  keys={list(obj)[:12] if isinstance(obj, dict) else type(obj).__name__}")
        except Exception as e:
            print(f"    JSON: FAIL {e}")


def m3():
    tpl = Path("shared/templates/llm/tasks/perceive_action.md")
    text = tpl.read_text(encoding="utf-8") if tpl.exists() else ""
    print(f"\n{'='*70}\nM3 — perceive_action via task 'thought'\n{'='*70}")
    print(f"template exists: {tpl.exists()}  len={len(text)}")
    # pick literal markers = lines without Jinja
    lits = [l.strip() for l in text.splitlines()
            if l.strip() and "{" not in l and len(l.strip()) > 30]
    print("literal candidate markers:")
    for l in lits[:20]:
        print("   ", repr(l[:120]))
    rows = load(task_filter={"thought"})
    marker = None
    for cand in lits:
        hits = sum(1 for d in rows if cand in userprompt(d) or cand in sysprompt(d))
        if hits:
            print(f"  MARKER HIT {hits:4d}  {cand[:90]!r}")
            if marker is None:
                marker = cand
    if marker is None:
        print("  no literal marker matched any thought row")
        return
    sel = [d for d in rows if marker in userprompt(d) or marker in sysprompt(d)]
    print(f"\nselected n={len(sel)}")
    lat = [float(d["duration_s"]) for d in sel if d.get("duration_s")]
    p50, p90 = quantiles(lat)
    print(f"latency P50={p50:.2f}s P90={p90:.2f}s")
    roles = Counter(d.get("llm_role") for d in sel)
    print("roles:", dict(roles))
    print("models:", dict(Counter(d.get("model") for d in sel)))


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    if which in ("m1", "all"):
        m1()
    if which in ("m1b", "all"):
        m1b()
    if which in ("m2", "all"):
        m2()
    if which in ("m3", "all"):
        m3()
