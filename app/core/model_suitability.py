"""Versioned model suitability evidence from frozen logs and synthetic cases.

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
"""
import json
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

from app.core.log import get_logger
from app.core.paths import get_storage_dir
from app.core.timeutils import utc_now
from app.core.suitability_scoring import (SCORER_VERSION, DIMENSIONS, prepare_case,
                                          score_case, semantic_cases, fixture_version)

logger = get_logger("model_suitability")

Verdict = Tuple[Optional[bool], bool, str]  # (ok, hallucinated, detail)

_LOG_PATH = Path("./logs/llm_calls.jsonl")
_TAG_RE = re.compile(r'<tool\s+name="(\w+)">([\s\S]*?)</tool>')
# Tool tasks (tool-LLM decisions) vs. helper tasks.
_TOOL_TASKS = {"thought", "intent"}
# Case counts per task, and whether the case runs repeatedly for consistency.
_SELECT = [
    ("thought", 8),
    ("intent", 4),
    ("tool", 2),
    ("extraction", 4),
    ("relationship_summary", 3),
    ("image_prompt", 3),
    ("consolidation", 3),
    ("image_analysis", 2),
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


def build_cases_from_log(log_path: Optional[Path] = None) -> Dict[str, Any]:
    """Extract frozen fixtures from the LLM log and save them under storage;
    return a summary of the resulting cases."""
    path = log_path or _LOG_PATH
    rows: List[dict] = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue

    # Pass 1: gather more than n candidates per task to skip invalid goldens.
    pool: Dict[str, List[tuple]] = {}
    for task, n in _SELECT:
        seen = set()
        cand: List[tuple] = []
        for e in rows:
            if len(cand) >= n * 5:
                break
            if e.get("task") != task or e.get("error"):
                continue
            system, user = _prompt_of(e)
            golden = (e.get("response") or "").strip()
            if not (system and golden):
                continue
            key = hash(system[:200] + user[:100])
            if key in seen:
                continue
            fmt = _detect_fmt(golden)
            seen.add(key)
            cand.append((system, user, golden, fmt))
        pool[task] = cand

    # Hardened JSON keys: intersection across ALL JSON goldens of a task;
    # drops idiosyncratic keys such as 'action' found in only one golden.
    task_keys: Dict[str, List[str]] = {}
    for task, cand in pool.items():
        keysets = []
        for (_s, _u, g, fmt) in cand:
            if fmt == "json":
                obj = _first_json(g, array=False)
                if isinstance(obj, dict):
                    keysets.append(set(obj.keys()))
        if keysets:
            inter = set.intersection(*keysets) if len(keysets) > 1 else keysets[0]
            task_keys[task] = sorted(inter)

    # Tool goldens are examples, never semantic truth. Helpers retain format
    # filtering only; per-case catalogs always come from frozen prompts.
    cases: List[Dict[str, Any]] = []
    skipped = 0
    for task, n in _SELECT:
        category = "tool" if task in _TOOL_TASKS else "helper"
        picked = 0
        for (system, user, golden, fmt) in pool.get(task, []):
            if picked >= n:
                break
            expect = _build_expect(fmt, golden)
            if fmt == "json" and task in task_keys:
                expect["keys"] = task_keys[task]
            g_ok = True if category == "tool" else (_v_json(golden, expect, [])[0] if fmt == "json" else bool(golden.strip()))
            if not g_ok:
                skipped += 1
                continue
            picked += 1
            cases.append(prepare_case({
                "id": f"{task}_{picked}",
                "task": task,
                "label": f"{task} #{picked} ({fmt})",
                "category": category,
                "fmt": fmt,
                "system": system,
                "user": user,
                "golden": golden,
                "expect": expect,
                "repeats": _TOOL_REPEATS if category == "tool" else 1,
            }))

    data = {
        "built_at": utc_now().isoformat(timespec="seconds"),
        "fixture_version": fixture_version(cases),
        "cases": cases,
    }
    p = _cases_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    by_task: Dict[str, int] = {}
    for c in cases:
        by_task[c["task"]] = by_task.get(c["task"], 0) + 1
    logger.info("Built %d suitability cases from log (%s); %d invalid goldens skipped",
                len(cases), by_task, skipped)
    return {"total": len(cases), "by_task": by_task, "skipped": skipped,
            "built_at": data["built_at"]}


def load_cases(auto_build: bool = True) -> Dict[str, Any]:
    p = _cases_path()
    if not p.exists():
        if auto_build:
            build_cases_from_log()
        else:
            return {"allowed_tools": [], "cases": []}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        data.pop("allowed_tools", None)
        prepared = [prepare_case(c) for c in data.get("cases", [])]
        ids = {c["id"] for c in prepared}
        data["cases"] = prepared + [c for c in semantic_cases() if c["id"] not in ids]
        data["fixture_version"] = fixture_version(data["cases"])
        return data
    except Exception as e:
        logger.error("Failed to load suitability cases: %s", e)
        return {"allowed_tools": [], "cases": []}


def cases_info() -> Dict[str, Any]:
    data = load_cases(auto_build=False)
    cases = data.get("cases", [])
    by_task: Dict[str, int] = {}
    for c in cases:
        by_task[c.get("task", "?")] = by_task.get(c.get("task", "?"), 0) + 1
    return {"total": len(cases), "by_task": by_task,
            "built_at": data.get("built_at", ""),
            "allowed_tools": data.get("allowed_tools", [])}


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

def iter_suitability_results(
    model_full: str, extra_params: Optional[Dict[str, Any]] = None,
    routing_entry: Optional[dict] = None,
) -> Iterator[Dict[str, Any]]:
    """Run frozen fixture cases against a model and yield NDJSON events."""
    from app.core.llm_router import create_llm_instance
    data = load_cases(auto_build=True)
    cases = data.get("cases", [])
    if not cases:
        yield {"type": "error", "message": "No test cases — is logs/llm_calls.jsonl present?"}
        return

    inst = create_llm_instance("suitability_test", model_full,
                               routing_entry=routing_entry)
    if inst is None:
        yield {"type": "error", "message": f"No provider found for model '{model_full}'"}
        return
    if not inst.available:
        yield {"type": "error", "message": f"Provider '{inst.provider_name}' is not available"}
        return
    try:
        client = inst.create_llm(temperature=0.3, max_tokens=900,
                                 extra_params=extra_params or {})
    except Exception as e:
        yield {"type": "error", "message": f"client init failed: {e}"}
        return

    def ask(system: str, user: str):
        """Return full local response metadata, duration and token count."""
        t0 = time.monotonic()
        resp = client.invoke([
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ])
        dt = time.monotonic() - t0
        usage = getattr(resp, "usage", None) or {}
        ctok = int(usage.get("completion_tokens") or 0)
        raw = {"content": getattr(resp, "content", "") or "",
               "reasoning": getattr(resp, "reasoning", None),
               "finish_reason": getattr(resp, "finish_reason", None),
               "usage": usage, "duration_s": dt}
        return raw, dt, ctok

    yield {"type": "start", "model": model_full, "total": len(cases)}

    results: List[Dict[str, Any]] = []
    for idx, case in enumerate(cases):
        repeats = int(case.get("repeats", 1)) or 1
        runs: List[Verdict] = []
        durs: List[float] = []
        toks: List[int] = []
        outputs: List[dict] = []
        dimensions = []
        for _ in range(repeats):
            attempt_start = time.monotonic()
            try:
                if case.get("task") == "image_analysis" or case.get("fixture_error"):
                    raw, dt, ctok = {"content": "", "reasoning": None, "finish_reason": None, "usage": {}, "duration_s": 0}, 0, 0
                else:
                    raw, dt, ctok = ask(case["system"], case["user"])
                evidence = score_case(case, raw["content"], finish_reason=raw.get("finish_reason"))
                dimensions.append(evidence)
                runs.append((evidence["ok"], evidence["hallucinated"], evidence["detail"]))
                durs.append(dt)
                toks.append(ctok)
                outputs.append(raw)
            except Exception as e:
                evidence = score_case(case, "", infra_error=True)
                dimensions.append(evidence)
                runs.append((None, False, "infra_error"))
                failed_duration = time.monotonic() - attempt_start
                durs.append(failed_duration)
                toks.append(0)
                outputs.append({"content": "", "reasoning": None, "finish_reason": None,
                                "usage": {}, "duration_s": failed_duration, "error": str(e)})
        # Pass and hallucination need a majority across repeats.
        npass = sum(1 for r in runs if r[0])
        nhall = sum(1 for r in runs if r[1])
        need = (repeats // 2) + 1
        ok = npass >= need if all(r[0] is not None for r in runs) else None
        hall = nhall >= need
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
        rec = {"id": case["id"], "label": case["label"], "category": case["category"],
               "ok": ok, "hallucinated": bool(hall), "detail": detail,
               "infra": bool(infra), "duration_s": avg_dt, "tok_s": tps,
               "tok": tot_tok, "dur_total": round(sum(valid_durs), 2),
               "runs": outputs,
               "dimensions": {k: (dimensions[0][k] if all(d[k] == dimensions[0][k] for d in dimensions) else "mixed") for k in DIMENSIONS},
               "run_checks": dimensions}
        rec["invalid_input"] = rec["dimensions"]["invalid_input"]
        results.append(rec)
        yield {"type": "check", "index": idx, **{k: rec[k] for k in
               ("id", "label", "category", "ok", "hallucinated", "detail",
                "infra", "duration_s", "tok_s", "dimensions", "run_checks")}}

    summary = _summarize(model_full, results)
    summary.update(scorer_version=SCORER_VERSION,
                   fixture_version=data.get("fixture_version") or fixture_version(cases))
    summary["saved"] = _persist(model_full, summary, results)
    yield {"type": "done", "summary": summary}


def _summarize(model_full: str, results: List[Dict[str, Any]]) -> Dict[str, Any]:
    eligible = [r for r in results if r.get("ok") is not None]
    tool = [r for r in eligible if r["category"] == "tool"]
    helper = [r for r in eligible if r["category"] == "helper"]
    tp = sum(1 for r in tool if r["ok"])
    hp = sum(1 for r in helper if r["ok"])
    passed = sum(1 for r in results if r["ok"])
    halluc = sum(1 for r in results if r["hallucinated"])
    tool_rate = (tp / len(tool)) if tool else 0.0
    helper_rate = (hp / len(helper)) if helper else 0.0
    tool_hall = sum(1 for r in tool if r["hallucinated"])
    semantic_tool = [r for r in tool if any(isinstance(d.get("decision_correct"), bool) for d in r.get("run_checks", [r.get("dimensions", {})]))]
    tool_ok = bool(tool_rate >= 0.85 and tool_hall == 0) if semantic_tool else "not_tested"
    helper_ok = bool(helper_rate >= 0.70) if helper else "not_tested"
    # Aggregate speed.
    total_tok = sum(int(r.get("tok") or 0) for r in results)
    total_dur = sum(float(r.get("dur_total") or 0.0) for r in results)
    lat = [r["duration_s"] for r in results if r.get("duration_s")]
    speed = {
        "avg_latency_s": round(sum(lat) / len(lat), 2) if lat else 0.0,
        "tok_per_s": round(total_tok / total_dur, 1) if total_dur and total_tok else 0.0,
        "total_s": round(total_dur, 1),
        "tokens": total_tok,
    }
    infra = any(r.get("infra") for r in results)
    return {
        "model": model_full,
        "date": utc_now().date().isoformat(),
        "score": f"{passed}/{len(eligible)}",
        "tool": f"{tp}/{len(tool)}",
        "helper": f"{hp}/{len(helper)}",
        "hallucinations": halluc,
        "verdict": {"tool": tool_ok, "helper": helper_ok},
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
                      ("id", "label", "category", "ok", "hallucinated", "detail",
                       "duration_s", "tok_s", "dimensions", "run_checks")} for r in results]
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
            "checks": stored_checks,
        },
    }
    try:
        save_suitability(model_full, record)
        logger.info("Suitability saved for %s: %s (tool_ok=%s, %.1f tok/s)",
                    model_full, summary["score"], summary["verdict"]["tool"],
                    (summary.get("speed") or {}).get("tok_per_s", 0))
        return True
    except Exception as e:
        logger.error("Failed to persist suitability for %s: %s", model_full, e)
        return False


# ---------------------------------------------------------------------------
# Asynchronous job runner (background thread, pollable status)
# ---------------------------------------------------------------------------
_JOBS: Dict[str, Dict[str, Any]] = {}
_JOBS_LOCK = threading.Lock()

class SuitabilityTestConflict(RuntimeError):
    """A different request is already testing this provider/model."""


def _run_job(model_full: str, extra_params: Optional[Dict[str, Any]] = None,
             routing_entry: Optional[dict] = None) -> None:
    try:
        for ev in iter_suitability_results(
                model_full, extra_params=extra_params, routing_entry=routing_entry):
            t = ev.get("type")
            with _JOBS_LOCK:
                job = _JOBS.get(model_full)
                if job is None:
                    return
                if t == "start":
                    job["total"] = ev.get("total", 0)
                    job["status"] = "running"
                elif t == "check":
                    job["checks"].append({k: ev.get(k) for k in
                                          ("id", "label", "category", "ok",
                                           "hallucinated", "detail", "infra",
                                           "duration_s", "tok_s", "dimensions", "run_checks")})
                    job["done"] = len(job["checks"])
                elif t == "done":
                    job["summary"] = ev.get("summary")
                    job["status"] = "done"
                elif t == "error":
                    job["error"] = ev.get("message")
                    job["status"] = "error"
    except Exception as e:  # noqa: BLE001
        logger.error("suitability job %s crashed: %s", model_full, e)
        with _JOBS_LOCK:
            job = _JOBS.get(model_full)
            if job is not None:
                job["error"] = str(e)
                job["status"] = "error"


def _snapshot(job: Dict[str, Any]) -> Dict[str, Any]:
    j = dict(job)
    j.pop("_request", None)
    j["checks"] = list(job.get("checks") or [])
    return j


def start_test(model_full: str, extra_params: Optional[Dict[str, Any]] = None,
               routing_entry: Optional[dict] = None,
               entry_index: Optional[int] = None) -> Dict[str, Any]:
    """Run a model test, reusing only an identical active request."""
    request = (entry_index, routing_entry, extra_params)
    with _JOBS_LOCK:
        cur = _JOBS.get(model_full)
        if cur and cur.get("status") == "running":
            if cur.get("_request") != request:
                raise SuitabilityTestConflict(
                    "A different suitability test is already running for this model")
            return _snapshot(cur)
        entry_name = (str(routing_entry.get("name") or
                          (f"Entry #{entry_index + 1}" if entry_index is not None
                           else "Saved LLM entry")) if routing_entry else "")
        job = {"model": model_full, "status": "running", "total": 0, "done": 0,
               "checks": [], "summary": None, "error": None,
               "entry_index": entry_index, "entry_name": entry_name,
               "_request": request}
        _JOBS[model_full] = job
    threading.Thread(target=_run_job, args=(model_full, extra_params, routing_entry),
                     daemon=True, name="suit-test").start()
    with _JOBS_LOCK:
        return _snapshot(_JOBS[model_full])


def get_job(model_full: str) -> Optional[Dict[str, Any]]:
    """Current status of a running or completed job, if any."""
    with _JOBS_LOCK:
        job = _JOBS.get(model_full)
        return _snapshot(job) if job else None


def list_jobs() -> List[Dict[str, Any]]:
    """All known jobs, for restoring the running-jobs view after reload."""
    with _JOBS_LOCK:
        return [_snapshot(j) for j in _JOBS.values()]
