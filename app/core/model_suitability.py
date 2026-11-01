"""Versioned model suitability evidence from curated cases (plus reviewed log cases).

Tool format, catalog availability, arguments and curated semantics are scored
separately. Log goldens are examples only. Helper scores measure format, never
semantic quality. Invalid/missing/truncated inputs are excluded. Raw responses
and every repetition remain in the local gitignored sidecar.

Verdict policy: each repetition passes only if every checked format, availability,
argument and semantic dimension passes and no refusal is detected. Uncurated
semantics remain not_tested. Case verdicts require a strict majority; invalid input
(missing image, invalid fixture, infrastructure error) excludes the case from score
denominators. A truncated answer (finish_reason=length) FAILS without being called a
refusal or hallucination. A prompt conflict (a JSON-contract tool whose example in the
same prompt is not JSON) is flagged and suspends only that tool's argument check. The
aggregate tool threshold remains 85% with no invented tools, and requires at
least one curated semantic case with evidence; otherwise it is not_tested.
Helper threshold remains 70% and is explicitly format-only. Individual dimensions
and every repetition remain visible even when an aggregate says mixed. Historical
records are archived unchanged before a future result replaces the latest view.

Queue: unfinished requests persist in the instance-wide suitability_queue.json,
shared by all worlds. Restarted jobs load as interrupted and require explicit
resume (repeating a running test from the start) or discard; finished jobs live
only in the capability table. List order preserves FIFO within each provider.
"""
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from statistics import median
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

from app.core.log import get_logger
from app.core.paths import get_storage_dir, get_instance_dir
from app.core.timeutils import utc_now
from app.core.suitability_scoring import (SCORER_VERSION, DIMENSIONS, prepare_case,
                                          score_case, curated_cases, fixture_version)

logger = get_logger("model_suitability")

Verdict = Tuple[Optional[bool], bool, str]  # (ok, hallucinated, detail)

_LOG_PATH = Path("./logs/llm_calls.jsonl")
_TAG_RE = re.compile(r'<tool\s+name="(\w+)">([\s\S]*?)</tool>')
# Tool tasks (tool-LLM decisions) vs. helper tasks.
_TOOL_TASKS = {"thought", "intent"}
# Case counts per task, and whether the case runs repeatedly for consistency.
_SELECT = [
    ("thought", 8), ("intent", 4), ("tool", 2),
    ("extraction_chat_state", 4), ("extraction", 4), ("npc_action", 3),
    ("relationship_summary", 3), ("image_prompt", 3), ("consolidation", 3),
    ("furnish", 1), ("building_layout", 1), ("outfit_generation", 1),
    ("story_arc_generation", 1), ("story_arc_advancement", 1), ("random_event", 1), ("secret_generation", 1),
    ("image_analysis", 2), ("image_recognition", 2),
]
_TOOL_REPEATS = 3


def _cases_path() -> Path:
    return get_storage_dir() / "suitability_cases.json"


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------

def _strip_fences(text: str) -> str:
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z0-9]*\s*", "", t)
        t = re.sub(r"\s*```$", "", t)
    return t.strip()


def _first_json(text: str, array: bool = False):
    """Extract and parse the first {…} or […] from text, as production does."""
    s = _strip_fences(text)
    pat = r"\[[\s\S]*\]" if array else r"\{[\s\S]*\}"
    m = re.search(pat, s)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Fixture builder (from the log)
# ---------------------------------------------------------------------------

def _prompt_of(entry: dict) -> Tuple[str, str]:
    p = entry.get("prompt")
    if isinstance(p, dict):
        return (p.get("system") or "", p.get("user") or "")
    return "", ""


def _detect_fmt(golden: str) -> str:
    if _TAG_RE.search(golden):
        return "tool"
    g = golden.strip()
    if g.upper().rstrip().endswith("NONE") or g.upper() == "NONE":
        return "abstain"
    if _first_json(g, array=False) is not None or _first_json(g, array=True) is not None:
        return "json"
    return "text"


def _build_expect(fmt: str, golden: str) -> Dict[str, Any]:
    if fmt == "json":
        arr = _first_json(golden, array=True)
        if isinstance(arr, list) and not isinstance(_first_json(golden, array=False), dict):
            return {"array": True, "keys": []}
        obj = _first_json(golden, array=False)
        if isinstance(obj, dict):
            return {"array": False, "keys": sorted(obj.keys())}
        return {"array": False, "keys": []}
    if fmt == "text":
        return {"max": max(240, len(golden.strip()))}
    return {}


def build_cases_from_log(log_path=None, *, since: str | None = None) -> Dict[str, Any]:
    """Capture world-local candidates; only explicitly reviewed rules are scored."""
    from app.core.timeutils import parse_iso
    try:
        cutoff = parse_iso(since) if since is not None else None
    except (ValueError, TypeError) as error:
        raise ValueError("Invalid --since ISO timestamp") from error
    path = Path(log_path) if log_path is not None else _LOG_PATH
    rows = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except (ValueError, TypeError):
                continue
            if not isinstance(row, dict):
                continue
            if cutoff is not None:
                try:
                    stamp = parse_iso(row.get("starttime") or row.get("ts") or row.get("timestamp") or "")
                except (ValueError, TypeError):
                    continue
                if stamp < cutoff:
                    continue
            rows.append(row)
    cases = []
    skipped = 0
    for task, count in _SELECT:
        seen = set()
        picked = 0
        for row in rows:
            if picked >= count:
                break
            if row.get("task") != task or row.get("error"):
                continue
            system, user = _prompt_of(row)
            golden = row.get("response") or ""
            if not isinstance(golden, str) or not system or not golden.strip():
                skipped += 1
                continue
            identity = (system, user)
            if identity in seen:
                continue
            seen.add(identity)
            group = ("tools" if task in _TOOL_TASKS else
                     "vision" if task in ("image_analysis", "image_recognition") else "helpers")
            reviewed = row.get("reviewed") is True
            picked += 1
            case = prepare_case({
                "id": f"log_{task}_{picked}", "task": task, "group": group,
                "system": system, "user": user, "golden": golden,
                "fmt": _detect_fmt(golden), "repeats": 3,
                "reviewed": reviewed,
                "sets": row.get("sets", {}),
                "expect": row.get("expect", {}) if reviewed else {},
                **({"image": row["image"]} if isinstance(row.get("image"), str) else {}),
            })
            cases.append(case)
    data = {"built_at": utc_now().isoformat(timespec="seconds"),
            "fixture_version": fixture_version(cases), "cases": cases}
    target = _cases_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    by_task = {}
    for case in cases:
        by_task[case["task"]] = by_task.get(case["task"], 0) + 1
    return {"total": len(cases), "by_task": by_task, "skipped": skipped,
            "built_at": data["built_at"]}


def load_cases(auto_build: bool = True) -> Dict[str, Any]:
    """Combine world-local candidates with tracked curated cases in every world."""
    path = _cases_path()
    if not path.exists() and auto_build:
        build_cases_from_log()
    data = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError) as error:
            logger.error("Failed to load suitability cases: %s", error)
    curated = curated_cases()
    curated_ids = {case["id"] for case in curated}
    prepared = []
    for case in data.get("cases", []):
        if case.get("id") in curated_ids:
            continue
        candidate = {**case, "reviewed": case.get("reviewed") is True}
        prepared.append(prepare_case(candidate))
    data.pop("allowed_tools", None)
    data["cases"] = prepared + curated
    data["curated_only"] = not prepared
    data["fixture_version"] = fixture_version(data["cases"])
    return data


def runnable_cases() -> List[Dict[str, Any]]:
    """The cases a test sends: the curated set plus log candidates a person
    reviewed (scripts/suitability_capture_cases.py --review)."""
    return [case for case in load_cases(auto_build=False).get("cases", [])
            if case.get("reviewed", True) is True]


def cases_info() -> Dict[str, Any]:
    """Counts of the cases a test runs, by group (tools / helpers / vision)."""
    by_group: Dict[str, int] = {}
    for case in runnable_cases():
        by_group[case.get("group", "?")] = by_group.get(case.get("group", "?"), 0) + 1
    return {"total": sum(by_group.values()), "by_group": by_group}


# ---------------------------------------------------------------------------
# Validators by format
# ---------------------------------------------------------------------------

def _v_json(out: str, expect: dict, allowed: List[str]) -> Verdict:
    arr = expect.get("array")
    obj = _first_json(out, array=bool(arr))
    if obj is None:
        return False, False, f"no parseable JSON {'array' if arr else 'object'}"
    if arr:
        if not isinstance(obj, list) or not obj:
            return False, False, "empty/invalid array"
        return True, False, f"valid JSON array ({len(obj)} items)"
    if not isinstance(obj, dict):
        return False, False, "not a JSON object"
    keys = expect.get("keys") or []
    missing = [k for k in keys if k not in obj]
    if missing:
        return False, False, f"missing keys {missing}"
    return True, False, "valid JSON with expected keys"


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def _rejected_by_model(exc: BaseException) -> bool:
    """A 4xx refusal of the request itself (not 408/409/429, which are load)."""
    status = getattr(exc, "status_code", None)
    if status is None:
        match = re.search(r"Error code: (\d{3})", str(exc))
        status = int(match.group(1)) if match else None
    return isinstance(status, int) and 400 <= status < 500 and status not in (408, 409, 429)


def validate_settings(settings: dict) -> dict:
    """Validate and copy explicit test parameters; never consult routing."""
    import math
    from copy import deepcopy
    from app.core.llm_router import parse_extra_params
    defaults = {"temperature": {"tools": 0.1, "helpers": 0.5, "vision": 0.3},
                "repetition_penalty": None, "max_tokens": 900, "chat_template": "",
                "thinking": dict.fromkeys(("tools", "helpers", "vision"), False),
                "thinking_budget": dict.fromkeys(("tools", "helpers", "vision")), "extra_params": {}}
    if not isinstance(settings, dict) or settings.keys() - defaults.keys():
        raise ValueError("settings must be an object with known keys only")
    result = {**defaults, **deepcopy(settings)}
    def number(value, low, high):
        return (isinstance(value, (int, float)) and not isinstance(value, bool)
                and low <= value <= high and math.isfinite(value))
    temps = result["temperature"]
    if (not isinstance(temps, dict) or set(temps) != set(defaults["temperature"])
            or not all(number(v, 0, 2) for v in temps.values())):
        raise ValueError("temperature must contain tools, helpers and vision numbers from 0 to 2")
    penalty = result["repetition_penalty"]
    if penalty is not None and not number(penalty, 0, 1.5):
        raise ValueError("repetition_penalty must be null or a number from 0 to 1.5")
    tokens = result["max_tokens"]
    if not isinstance(tokens, int) or isinstance(tokens, bool) or not 0 <= tokens <= 200000:
        raise ValueError("max_tokens must be an integer from 0 to 200000")
    if not isinstance(result["chat_template"], str):
        raise ValueError("chat_template must be text")
    groups = {"tools", "helpers", "vision"}
    thinking = result["thinking"]
    if not isinstance(thinking, dict) or set(thinking) != groups or not all(isinstance(v, bool) for v in thinking.values()):
        raise ValueError("thinking must contain tools, helpers and vision booleans")
    budgets = result["thinking_budget"]
    if (not isinstance(budgets, dict) or set(budgets) != groups
            or not all(v is None or (type(v) is int and 1 <= v <= 32000) for v in budgets.values())):
        raise ValueError("thinking_budget must contain tools, helpers and vision integers from 1 to 32000 or null")
    if not isinstance(result["extra_params"], dict):
        raise ValueError("extra_params must be a JSON object")
    result["extra_params"] = parse_extra_params(result["extra_params"])
    return result


def iter_suitability_results(
    model_full: str, *, settings: dict,
    cancel_event: Optional[threading.Event] = None,
    concurrency: int = 3,
) -> Iterator[Dict[str, Any]]:
    """Run frozen fixture cases against a model and yield NDJSON events."""
    from app.core.llm_router import create_llm_instance
    settings = validate_settings(settings)
    data = load_cases(auto_build=False)
    # Unreviewed log candidates (possibly from an older prompt layout) wait
    # for review in scripts/suitability_capture_cases.py.
    cases = runnable_cases()
    curated_ids = {case["id"] for case in curated_cases()}
    data = {**data, "cases": cases, "fixture_version": fixture_version(cases),
            "curated_only": all(case.get("id") in curated_ids for case in cases)}
    if not cases:
        yield {"type": "error", "message": "No test cases"}
        return

    inst = create_llm_instance("suitability_test", model_full, use_routing=False)
    if inst is None:
        yield {"type": "error", "message": f"No provider found for model '{model_full}'"}
        return
    if not inst.available:
        yield {"type": "error", "message": f"Provider '{inst.provider_name}' is not available"}
        return
    try:
        clients = {group: inst.create_llm(
            temperature=temperature, thinking=settings["thinking"][group],
            thinking_budget=settings["thinking_budget"][group],
            **{k: v for k, v in settings.items() if k not in ("temperature", "thinking", "thinking_budget")})
            for group, temperature in settings["temperature"].items()}
    except Exception as e:
        yield {"type": "error", "message": f"client init failed: {e}"}
        return

    from app.core import config
    from app.core.agent_loop import get_agent_loop
    from app.models.world import is_world_frozen
    from app.core.vision_message import image_user_content
    from app.core.suitability_scoring import ROOT

    provider, _, model = model_full.partition("::")
    # Tests go straight to the provider, past the queue and its lanes; the
    # provider's own parallel-request limit is the bound.
    provider_cap = next((p.get("max_concurrent") for p in config.get("providers", []) or []
                         if p.get("name") == (getattr(inst, "provider_name", "") or provider)), None)
    try:
        provider_cap = int(provider_cap) if provider_cap else concurrency
    except (TypeError, ValueError):
        provider_cap = concurrency
    concurrency = max(1, min(concurrency, provider_cap))
    live_play = bool(get_agent_loop().status()["running"] and not is_world_frozen())
    cases = [prepare_case(case) for case in cases]

    def ask(case):
        """Return full local response metadata, duration and token count."""
        t0 = time.monotonic()
        user = case["user"]
        if case["group"] == "vision":
            user = image_user_content(user, ROOT / case["image"])
        resp = clients[case["group"]].invoke([
            {"role": "system", "content": case["system"]},
            {"role": "user", "content": user},
        ])
        dt = time.monotonic() - t0
        usage = getattr(resp, "usage", None) or {}
        ctok = int(usage.get("completion_tokens") or 0)
        raw = {"content": getattr(resp, "content", "") or "",
               "reasoning": getattr(resp, "reasoning", None),
               "budget_hit": bool(getattr(resp, "budget_hit", False)),
               "finish_reason": getattr(resp, "finish_reason", None),
               "usage": usage, "duration_s": dt}
        return raw, dt, ctok

    yield {"type": "start", "model": model_full, "total": len(cases)}

    def attempt(case):
        if cancel_event is not None and cancel_event.is_set():
            return None
        attempt_start = time.monotonic()
        try:
            missing = (case["group"] == "vision" and
                       (not case.get("image") or not (ROOT / case["image"]).is_file()))
            if missing or case.get("fixture_error"):
                raw, dt, ctok = {"content": "", "reasoning": None, "finish_reason": None,
                                 "budget_hit": False, "usage": {}, "duration_s": 0}, 0, 0
            else:
                raw, dt, ctok = ask(case)
            evidence = score_case(case, raw["content"], finish_reason=raw.get("finish_reason"))
        except Exception as exc:
            missing = (case["group"] == "vision" and isinstance(exc, FileNotFoundError)
                       and not (ROOT / case["image"]).is_file())
            # A request the server refuses for this model (400 "at most 0
            # images" from a text-only model) is the model's answer: the case
            # fails. Only an outage (connection, timeout, 5xx, 429) is infra.
            rejected = _rejected_by_model(exc)
            evidence = (score_case(case, "") if rejected
                        else score_case(case, "", infra_error=not missing))
            dt, ctok = time.monotonic() - attempt_start, 0
            raw = {"content": "", "reasoning": None, "finish_reason": None,
                   "budget_hit": False, "usage": {}, "duration_s": dt, "error": str(exc)}
        return evidence, raw, dt, ctok

    results: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        pending = [[pool.submit(attempt, case) for _ in range(int(case.get("repeats", 1)) or 1)]
                   for case in cases]
        for idx, case in enumerate(cases):
            if cancel_event is not None and cancel_event.is_set():
                return
            attempts = [future.result() for future in pending[idx]]
            if cancel_event is not None and cancel_event.is_set():
                return
            live_play = live_play or bool(get_agent_loop().status()["running"] and not is_world_frozen())
            dimensions = [a[0] for a in attempts]
            outputs = [a[1] for a in attempts]
            durs = [a[2] for a in attempts]
            toks = [a[3] for a in attempts]
            runs = [(d["ok"], d["hallucinated"], d["detail"]) for d in dimensions]
            repeats = len(attempts)
            # Quality needs a strict majority; every invented tool counts.
            npass = sum(1 for r in runs if r[0])
            need = (repeats // 2) + 1
            ok = npass >= need if all(r[0] is not None for r in runs) else None
            hall = any(r[1] for r in runs)
            infra = any(r.get("infra") for r in dimensions)
            # Take detail and output from the first failure, otherwise the first run.
            rep_idx = next((i for i, r in enumerate(runs) if not r[0]), 0)
            detail = runs[rep_idx][2]
            if repeats > 1:
                detail = f"{npass}/{repeats} runs ok — {detail}"
            # Speed: mean duration of valid runs plus tokens per second.
            valid_durs = [d for d in durs if d > 0]
            avg_dt = round(sum(valid_durs) / len(valid_durs), 2) if valid_durs else 0.0
            tot_tok = sum(toks)
            tps = round(tot_tok / sum(valid_durs), 1) if valid_durs and tot_tok else 0.0
            rec = {"id": case["id"], "group": case["group"], "task": case.get("task"), "label": case["label"], "category": case["category"],
                   "ok": ok, "hallucinated": bool(hall), "detail": detail,
                   "infra": bool(infra), "duration_s": avg_dt, "tok_s": tps,
                   "tok": tot_tok, "dur_total": round(sum(valid_durs), 2),
                   "runs": outputs,
                   "budget_hits": sum(bool(r.get("budget_hit")) for r in outputs),
                   "truncated_runs": sum(r.get("finish_reason") == "length" for r in outputs),
                   "reasoning_tokens": [(r.get("usage") or {}).get("reasoning_tokens") for r in outputs],
                   "dimensions": {k: (dimensions[0][k] if all(d[k] == dimensions[0][k] for d in dimensions) else "mixed") for k in DIMENSIONS},
                   "run_checks": dimensions}
            rec["invalid_input"] = rec["dimensions"]["invalid_input"]
            results.append(rec)
            yield {"type": "check", "index": idx, **{k: rec[k] for k in
                   ("id", "label", "category", "group", "task", "ok", "hallucinated", "detail",
                    "infra", "duration_s", "tok_s", "dimensions", "run_checks", "truncated_runs", "reasoning_tokens", "budget_hits")},
                   "prompt": {"system": case.get("system", ""), "user": case.get("user", "")},
                   "runs": outputs}

    # Cancellation and final persistence must be atomic with job completion.
    with _JOBS_LOCK:
        if cancel_event is not None and cancel_event.is_set():
            return
        summary = _summarize(model_full, results, settings=settings)
        summary.update(concurrency=concurrency, live_play=live_play,
                       curated_only=bool(data.get("curated_only")))
        summary.update(settings=settings, scorer_version=SCORER_VERSION,
                       fixture_version=data.get("fixture_version") or fixture_version(cases))
        summary["saved"] = _persist(model_full, summary, results)
        yield {"type": "done", "summary": summary}


def _summarize(model_full: str, results: List[Dict[str, Any]], *, settings: Optional[dict] = None) -> Dict[str, Any]:
    eligible = [r for r in results if r.get("ok") is not None]
    tool = [r for r in eligible if r["category"] == "tool"]
    tp = sum(1 for r in tool if r["ok"])
    passed = sum(1 for r in results if r["ok"])
    halluc = sum(1 for r in results if r["hallucinated"])
    tool_rate = (tp / len(tool)) if tool else 0.0
    tool_hall = sum(1 for r in tool if r["hallucinated"])
    semantic_tool = [r for r in tool if any(isinstance(d.get("decision_correct"), bool) for d in r.get("run_checks", [r.get("dimensions", {})]))]
    tool_ok = bool(tool_rate >= 0.85 and tool_hall == 0) if semantic_tool else "not_tested"
    from app.core import config
    def group_of(record):
        return record.get("group") or ("tools" if record["category"] == "tool" else
                "vision" if record.get("task") in ("image_analysis", "image_recognition") else "helpers")

    helper = [r for r in eligible if group_of(r) == "helpers"]
    hp = sum(bool(r["ok"]) for r in helper)
    helper_rate = hp / len(helper) if helper else 0.0
    helper_ok = helper_rate >= 0.70 if helper else "not_tested"
    vision = [r for r in eligible if group_of(r) == "vision"]
    vision_rate = sum(bool(r["ok"]) for r in vision) / len(vision) if vision else 0.0
    vision_ok = vision_rate >= 0.70 if vision else "not_tested"

    def timings(records):
        return [run for r in records for run in r.get("runs", [])
                if float(run.get("duration_s") or 0) > 0 and not run.get("error")]

    speed = {}
    for group in ("tools", "helpers", "vision"):
        runs = timings([r for r in eligible if group_of(r) == group])
        durations = [r["duration_s"] for r in runs]
        tokens = sum(int((r.get("usage") or {}).get("completion_tokens") or 0) for r in runs)
        reasoning_counts = [(run.get("usage") or {}).get("reasoning_tokens")
                            for record in results if group_of(record) == group for run in record.get("runs", [])]
        reasoning_counts = [n for n in reasoning_counts if n is not None]
        speed[group] = {"reasoning_tokens_median": median(reasoning_counts) if reasoning_counts else None,
                        "median_latency_s": round(median(durations), 2) if durations else None,
                        "tok_s": round(tokens / sum(durations), 1) if durations else None}
    task_medians = []
    for task in ("thought", "extraction_chat_state", "extraction"):
        runs = timings([r for r in eligible if r.get("task") == task])
        task_medians.append(median([r["duration_s"] for r in runs]) if runs else None)
    projected = sum(task_medians) if all(v is not None for v in task_medians) else None
    max_turn = config.get("model_test.max_turn_seconds", 20)
    speed_ok = projected is not None and projected <= max_turn
    verdict = next(("no — " + name for name, ok in
                    (("tools", tool_ok), ("helpers", helper_ok), ("vision", vision_ok), ("speed", speed_ok))
                    if ok is not True), "yes")
    infra = any(r.get("infra") for r in results)
    all_runs = [run for r in results for run in r.get("runs", [])]
    positive_tokens = [(run.get("usage") or {}).get("reasoning_tokens", 0) or 0 for run in all_runs]
    positive_tokens = [n for n in positive_tokens if n > 0]
    failed_by_truncation = []
    for record in results:
        failing = [run for run in record.get("run_checks", []) if run.get("ok") is False]
        if record.get("ok") is False and failing and all(run.get("truncated") for run in failing):
            failed_by_truncation.append(record["id"])
    return {
        "budget_hits": sum(bool(run.get("budget_hit")) for run in all_runs),
        "thinking_leak_runs": sum(
            (((run.get("usage") or {}).get("reasoning_tokens") or 0) > 0 or bool((run.get("reasoning") or "").strip()))
            for record in results if not ((settings or {}).get("thinking") or {}).get(group_of(record), False)
            for run in record.get("runs", [])),
        "total_runs": len(all_runs),
        "truncated_runs": sum(run.get("finish_reason") == "length" for run in all_runs),
        "truncated_cases": [r["id"] for r in results if any(run.get("finish_reason") == "length" for run in r.get("runs", []))],
        "failed_by_truncation": failed_by_truncation,
        "thinking_runs": sum(((run.get("usage") or {}).get("reasoning_tokens") or 0) > 0 or bool((run.get("reasoning") or "").strip()) for run in all_runs),
        "reasoning_tokens_median": median(positive_tokens) if positive_tokens else None,
        "model": model_full,
        "date": utc_now().date().isoformat(),
        "score": f"{passed}/{len(eligible)}",
        "tool": f"{tp}/{len(tool)}",
        "helper": f"{hp}/{len(helper)}",
        "hallucinations": halluc,
        "verdict": verdict,
        "vision": {"rate": vision_rate, "verdict": vision_ok},
        "projected_turn_s": projected,
        # The verdict names only the first failed dimension; speed is kept on
        # its own so the model table can mark a slow model that also failed tools.
        "speed_ok": speed_ok,
        "max_turn_seconds": max_turn,
        "helper_evidence": "format only; semantic not_tested",
        "tool_evidence": "conjunction of checked dimensions; uncurated decisions not_tested",
        "speed": speed,
        "infra": infra,
        "checks": results,
    }


def _persist(model_full: str, summary: Dict[str, Any], results: List[Dict[str, Any]]) -> bool:
    """Persist results only when no infrastructure errors occurred:
    provider outages and timeouts do not say anything about model quality."""
    from app.core.model_capabilities import save_raw_outputs, save_suitability
    # Stored checks: verdict, detail and timing only. The raw answer goes into
    # the local sidecar file — the test replays REAL logged prompts, so it
    # quotes the world's characters and plot and must not reach the shared,
    # committed results file.
    stored_checks = [{k: r.get(k) for k in
                      ("id", "label", "category", "group", "task", "ok", "hallucinated", "detail",
                       "duration_s", "tok_s", "dimensions", "run_checks", "truncated_runs", "reasoning_tokens", "budget_hits")} for r in results]
    raw_outputs = {"scorer_version": summary.get("scorer_version"),
                   "fixture_version": summary.get("fixture_version"),
                   "cases": {r["id"]: r.get("runs", []) for r in results}}
    # Preserve diagnostics even when infrastructure prevents a quality record.
    try:
        save_raw_outputs(model_full, raw_outputs)
    except Exception as exc:
        logger.error("Failed to persist local suitability diagnostics: %s", exc)
        return False
    if summary.get("infra") or any(r.get("infra") for r in results):
        return False
    # Keyed by full Provider::Model; identical models on different hardware
    # do not overwrite one another.
    record = {
        "tested_date": summary["date"],
        "tested_score": summary["score"],
        "tested_tool_score": summary["tool"],
        "tested_helper_score": summary["helper"],
        "tested_hallucinations": summary["hallucinations"],
        "tested_verdict": summary["verdict"],
        "tested_speed": summary.get("speed"),
        "tested_suitability": {
            "model": model_full,
            "scorer_version": summary.get("scorer_version"),
            "fixture_version": summary.get("fixture_version"),
            "helper_evidence": "format only; semantic not_tested",
            "tool": summary["tool"],
            "helper": summary["helper"],
            "verdict": summary["verdict"],
            "speed": summary.get("speed"),
            **{key: summary.get(key) for key in ("settings", "concurrency", "live_play", "projected_turn_s", "speed_ok",
                                                      "max_turn_seconds", "vision", "curated_only", "total_runs", "truncated_runs",
                                                      "truncated_cases", "failed_by_truncation", "thinking_runs", "thinking_leak_runs", "budget_hits", "reasoning_tokens_median")},
            "checks": stored_checks,
        },
    }
    try:
        save_suitability(model_full, record)
        logger.info("Suitability saved for %s: %s (%s)",
                    model_full, summary["score"], summary["verdict"])
        return True
    except Exception as e:
        logger.error("Failed to persist suitability for %s: %s", model_full, e)
        return False


# ---------------------------------------------------------------------------
# Asynchronous job runner (background thread, pollable status)
# ---------------------------------------------------------------------------
_JOBS: Dict[str, Dict[str, Any]] = {}
_JOBS_LOCK = threading.RLock()
_ACTIVE_PROVIDERS: set[str] = set()
_QUEUE_LOADED = False
_PERSISTED_STATUSES = ("queued", "running", "interrupted")
_QUEUE_FIELDS = ("job_id", "model", "provider", "settings", "concurrency", "status", "enqueued_at")


def _persist_queue() -> None:
    """Called under _JOBS_LOCK; config's atomic writer has no import-time I/O."""
    from app.core.config import _atomic_write_json
    path = get_instance_dir() / "suitability_queue.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(path, {"jobs": [
        {key: job[key] for key in _QUEUE_FIELDS} for job in _JOBS.values()
        if job["status"] in _PERSISTED_STATUSES and not job["_cancel"].is_set()]})


def _load_queue() -> None:
    """Load once under _JOBS_LOCK without writing or starting workers."""
    global _QUEUE_LOADED
    if _QUEUE_LOADED:
        return
    _QUEUE_LOADED = True
    path = get_instance_dir() / "suitability_queue.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
            raise ValueError("expected an object with a jobs list")
    except FileNotFoundError:
        return
    except (OSError, ValueError) as exc:
        logger.warning("Cannot load suitability queue %s: %s", path, exc)
        return
    for entry in data["jobs"]:
        try:
            if not isinstance(entry, dict):
                raise ValueError("job must be an object")
            job = {key: entry[key] for key in _QUEUE_FIELDS}
            if (any(not isinstance(job[k], str) or not job[k] for k in
                    ("job_id", "model", "provider", "enqueued_at"))
                    or job["provider"] != job["model"].partition("::")[0]
                    or job["status"] not in _PERSISTED_STATUSES
                    or type(job["concurrency"]) is not int or job["concurrency"] < 1
                    or job["job_id"] in _JOBS):
                raise ValueError("invalid job metadata")
            from app.core.timeutils import parse_iso
            if parse_iso(job["enqueued_at"]) is None:
                raise ValueError("invalid enqueued_at")
            job["settings"] = validate_settings(job["settings"])
            job.update(status="interrupted", total=0, done=0, checks=[], summary=None,
                       error=None, _request=(job["settings"], job["concurrency"]),
                       _cancel=threading.Event())
            _JOBS[job["job_id"]] = job
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("Skipping invalid suitability queue entry: %s", exc)


def _start_provider(provider: str) -> None:
    """Ensure one FIFO worker per provider, called under _JOBS_LOCK."""
    if provider not in _ACTIVE_PROVIDERS:
        _ACTIVE_PROVIDERS.add(provider)
        threading.Thread(target=_worker, args=(provider,), daemon=True,
                         name="suit-test-" + provider).start()


def interrupted_jobs() -> List[Dict[str, Any]]:
    with _JOBS_LOCK:
        _load_queue()
        return [_snapshot(j) for j in _JOBS.values() if j["status"] == "interrupted"]


def resume_interrupted() -> int:
    with _JOBS_LOCK:
        _load_queue()
        jobs = [j for j in _JOBS.values() if j["status"] == "interrupted"]
        for job in jobs:
            job.update(status="queued", total=0, done=0, checks=[], summary=None, error=None)
        _persist_queue()
        for provider in dict.fromkeys(j["provider"] for j in jobs):
            _start_provider(provider)
        return len(jobs)


def discard_interrupted() -> int:
    with _JOBS_LOCK:
        _load_queue()
        ids = [j["job_id"] for j in _JOBS.values() if j["status"] == "interrupted"]
        for job_id in ids:
            del _JOBS[job_id]
        _persist_queue()
        return len(ids)


def _reset_for_tests() -> None:
    """Simulate a fresh process; callers must first stop all test workers."""
    global _QUEUE_LOADED
    with _JOBS_LOCK:
        if _ACTIVE_PROVIDERS:
            raise RuntimeError("Cannot reset while workers are active")
        _JOBS.clear()
        _QUEUE_LOADED = False


def _snapshot(job: Dict[str, Any]) -> Dict[str, Any]:
    from copy import deepcopy
    result = deepcopy({k: v for k, v in job.items() if not k.startswith("_")})
    waiting = [j["job_id"] for j in _JOBS.values() if j["status"] == "queued"
               and j["provider"] == job["provider"]]
    result["position"] = waiting.index(job["job_id"]) + 1 if job["status"] == "queued" else 0
    finished = job.get("_finished")
    result["finished_ago_s"] = round(time.monotonic() - finished, 1) if finished else None
    return result


def _run_job(job: Dict[str, Any]) -> None:
    try:
        for ev in iter_suitability_results(job["model"], settings=job["settings"],
                                          cancel_event=job["_cancel"],
                                          concurrency=job["concurrency"]):
            with _JOBS_LOCK:
                if job["_cancel"].is_set():
                    continue
                kind = ev.get("type")
                if kind == "start":
                    job["total"] = ev.get("total", 0)
                elif kind == "check":
                    job["checks"].append({k: v for k, v in ev.items() if k not in ("type", "index")})
                    job["done"] = len(job["checks"])
                elif kind == "done":
                    job["summary"] = ev.get("summary")
                    job["status"] = "done"
                    _persist_queue()
                elif kind == "error":
                    job["error"] = ev.get("message")
                    job["status"] = "error"
                    _persist_queue()
    except Exception as exc:
        logger.error("suitability job %s crashed: %s", job["model"], exc)
        with _JOBS_LOCK:
            job["error"] = str(exc)
            job["status"] = "error"
    finally:
        with _JOBS_LOCK:
            if job["_cancel"].is_set():
                job["status"] = "cancelled"
            elif job["status"] == "running":
                job["status"] = "error"
                job["error"] = "Runner ended without a result"
            job["_finished"] = time.monotonic()
            _persist_queue()


def _worker(provider: str) -> None:
    try:
        while True:
            with _JOBS_LOCK:
                job = next((j for j in _JOBS.values() if j["status"] == "queued"
                            and j["provider"] == provider), None)
                if job is None:
                    _ACTIVE_PROVIDERS.discard(provider)
                    return
                job["status"] = "running"
                _persist_queue()
            _run_job(job)
    except OSError as exc:
        # A failed write must not leave a dead worker registered forever.
        with _JOBS_LOCK:
            job["status"] = "cancelled" if job["_cancel"].is_set() else "interrupted"
            _ACTIVE_PROVIDERS.discard(provider)
            logger.error("Suitability queue write failed for %s; worker stopped: %s", provider, exc)
            try:
                _persist_queue()
            except OSError:
                pass  # The previous atomic file remains recoverable on restart.


def enqueue_test(model_full: str, *, settings: dict,
                 concurrency: int = 3) -> Dict[str, Any]:
    """Queue a frozen explicit request, FIFO within each provider."""
    from copy import deepcopy
    from uuid import uuid4
    settings = validate_settings(settings)
    provider = model_full.partition("::")[0]
    request = deepcopy((settings, concurrency))
    with _JOBS_LOCK:
        _load_queue()
        for job in _JOBS.values():
            if (job["model"] == model_full and job["status"] in _PERSISTED_STATUSES
                    and job["_request"] == request):
                return _snapshot(job)
        job = {"job_id": uuid4().hex, "model": model_full, "provider": provider,
               "status": "queued", "total": 0, "done": 0, "checks": [],
               "summary": None, "error": None, "settings": settings,
               "concurrency": concurrency, "enqueued_at": utc_now().isoformat(),
               "_request": request, "_cancel": threading.Event()}
        _JOBS[job["job_id"]] = job
        _persist_queue()
        _start_provider(provider)
        return _snapshot(job)


def cancel_test(job_id: str) -> bool:
    with _JOBS_LOCK:
        _load_queue()
        job = _JOBS.get(job_id)
        if job is None or job["status"] not in _PERSISTED_STATUSES:
            return False
        if job["status"] == "interrupted":
            del _JOBS[job_id]
            _persist_queue()
            return True
        job["_cancel"].set()
        if job["status"] == "queued":
            job["status"] = "cancelled"
            job["_finished"] = time.monotonic()
        _persist_queue()
        return True


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    with _JOBS_LOCK:
        _load_queue()
        job = _JOBS.get(job_id)
        return _snapshot(job) if job else None


def list_jobs() -> List[Dict[str, Any]]:
    """Active FIFO first, then terminal jobs in submission order."""
    with _JOBS_LOCK:
        _load_queue()
        jobs = list(_JOBS.values())
        ordered = ([j for j in jobs if j["status"] == "running"]
                   + [j for j in jobs if j["status"] == "queued"]
                   + [j for j in jobs if j["status"] == "interrupted"]
                   + [j for j in jobs if j["status"] not in _PERSISTED_STATUSES])
        return [_snapshot(j) for j in ordered]
