"""Model Suitability Test — measures a specific model's tool/helper fitness.

LOG-DERIVED: cases come from real calls in ``logs/llm_calls.jsonl`` (the
``prompt`` {system, user} and actual response as the golden). The test thus
measures what the application actually needs instead of toy prompts.

Workflow:
1. Extract a FROZEN fixture set once into ``storage/suitability_cases.json``:
   real {system, user} prompts per task with valid logged responses, both
   positive (golden invokes a tool) and negative/abstain (golden = NONE).
   Frozen cases make scores comparable across models.
2. Replay those prompts against a candidate model and validate them with
   production-like parsers for each format (actual ``<tool name="X">…</tool>``
   tags, JSON schema, abstention and text). Tool cases run repeatedly to
   measure consistency.

Key signal (calibrated against a real RP model): RP models emit tool calls
in the WRONG format (``**SetActivity: …**`` rather than
``<tool name="SetActivity">…</tool>``), buried in prose. The application
parser then executes NOTHING, so such calls fail here.

Results go to ``shared/config/model_capabilities.json`` (``tested_*`` +
``tested_suitability`` + ``tested_verdict``), shown on the Model Capabilities
page. Shared across all worlds and tracked in git; the models' RAW answers go to
the gitignored ``model_capabilities_outputs.json`` next to it, because the test
replays real logged prompts and the answers quote the world.
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

logger = get_logger("model_suitability")

Verdict = Tuple[bool, bool, str]  # (ok, hallucinated, detail)

_LOG_PATH = Path("./logs/llm_calls.jsonl")
_TAG_RE = re.compile(r'<tool\s+name="(\w+)">([\s\S]*?)</tool>')
# Pseudo-tool markers used by RP models instead of the actual tool format.
_PSEUDO_RE = re.compile(r'(?im)(?:^|\n)\s*(?:\*\*|\[|#+\s*)?\s*'
                        r'(SetActivity|SetPose|SetLocation|Act|ChangeOutfit|TalkTo|'
                        r'SendMessage|ImageGenerator|Instagram|Retrospect)\s*[:=]')

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

    allowed = sorted({m.group(1) for e in rows if e.get("task") == "thought"
                      for m in _TAG_RE.finditer(e.get("response") or "")})

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
            if task == "thought" and fmt != "tool":
                continue
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

    # Pass 2: keep only goldens accepted by their OWN validator,
    # filtering prose, garbage and ambiguous golden responses.
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
            validator = _VALIDATORS.get(fmt, _v_text)
            g_ok, _gh, _gd = validator(golden, expect, allowed)
            if not g_ok:
                skipped += 1
                continue
            picked += 1
            cases.append({
                "id": f"{task}_{picked}",
                "task": task,
                "label": f"{task} #{picked} ({fmt})",
                "category": category,
                "fmt": fmt,
                "system": system,
                "user": user,
                "golden": golden[:400],
                "expect": expect,
                "repeats": _TOOL_REPEATS if category == "tool" else 1,
            })

    data = {
        "built_at": utc_now().isoformat(timespec="seconds"),
        "allowed_tools": allowed,
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
            "allowed_tools": allowed, "built_at": data["built_at"]}


def load_cases(auto_build: bool = True) -> Dict[str, Any]:
    p = _cases_path()
    if not p.exists():
        if auto_build:
            build_cases_from_log()
        else:
            return {"allowed_tools": [], "cases": []}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
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

def _strip_tool_noise(text: str) -> str:
    s = _TAG_RE.sub("", text)
    s = re.sub(r"\*\*[^*\n]+\*\*", "", s)  # **I feel ...**-Marker entfernen
    return s.strip()


def _v_tool(out: str, expect: dict, allowed: List[str]) -> Verdict:
    tags = _TAG_RE.findall(out or "")
    if not tags:
        if _PSEUDO_RE.search(out or ""):
            return False, True, ("tool call in WRONG format (** **/markdown) — the "
                                 "project parser would execute NOTHING")
        return False, False, "no tool call emitted"
    names = [n for n, _ in tags]
    unknown = [n for n in names if allowed and n not in allowed]
    if unknown:
        return False, True, f"unknown/invented tool(s): {sorted(set(unknown))}"
    for n, inp in tags:
        if n == "Act":
            if _first_json(inp, array=False) is None:
                return False, False, "Act tool input is not valid JSON"
    prose = _strip_tool_noise(out)
    if len(prose) > 400:
        return False, True, f"tool call buried in {len(prose)} chars of narrative prose"
    return True, False, f"clean tool call(s): {names}"


def _v_abstain(out: str, expect: dict, allowed: List[str]) -> Verdict:
    tags = _TAG_RE.findall(out or "")
    if tags:
        return False, True, f"emitted tool(s) {[n for n, _ in tags]} though NONE was correct"
    if _PSEUDO_RE.search(out or ""):
        return False, True, "attempted a (malformed) tool though NONE was correct"
    return True, False, "correctly abstained (no tool)"


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


def _v_text(out: str, expect: dict, allowed: List[str]) -> Verdict:
    s = (out or "").strip()
    if not s:
        return False, False, "empty"
    if _TAG_RE.search(s):
        return False, False, "contains tool tags (misread the task)"
    low = s.lower()
    if any(p in low for p in ("as an ai", "i cannot", "i can't", "language model",
                              "i'm sorry, but")):
        return False, True, "refusal/meta text"
    mx = int(expect.get("max", 1200))
    if len(s) > mx * 3:
        return False, False, f"far too long ({len(s)} chars, golden ~{mx})"
    return True, False, f"plain text, {len(s)} chars"


_VALIDATORS = {"tool": _v_tool, "abstain": _v_abstain, "json": _v_json, "text": _v_text}

# Infrastructure/availability errors are NOT evidence about the model;
# do not save results for those runs.
_INFRA_MARKERS = ("call error", "unable to access", "connection", "timeout",
                  "service unavailable", "bad gateway", "error code: 5",
                  "error code: 4", "non-serverless", "remote end closed")


def _is_infra_error(detail: str) -> bool:
    d = (detail or "").lower()
    return any(mk in d for mk in _INFRA_MARKERS)


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
    allowed = data.get("allowed_tools", [])
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
        """Return (text, duration_s, completion_tokens)."""
        t0 = time.monotonic()
        resp = client.invoke([
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ])
        dt = time.monotonic() - t0
        usage = getattr(resp, "usage", None) or {}
        ctok = int(usage.get("completion_tokens") or 0)
        return (getattr(resp, "content", "") or "").strip(), dt, ctok

    yield {"type": "start", "model": model_full, "total": len(cases)}

    results: List[Dict[str, Any]] = []
    for idx, case in enumerate(cases):
        validator = _VALIDATORS.get(case["fmt"], _v_text)
        repeats = int(case.get("repeats", 1)) or 1
        runs: List[Verdict] = []
        durs: List[float] = []
        toks: List[int] = []
        outputs: List[str] = []
        for _ in range(repeats):
            try:
                out, dt, ctok = ask(case["system"], case["user"])
                runs.append(validator(out, case.get("expect", {}), allowed))
                durs.append(dt)
                toks.append(ctok)
                outputs.append(out)
            except Exception as e:
                runs.append((False, False, f"call error: {str(e)[:120]}"))
                durs.append(0.0)
                toks.append(0)
                outputs.append("")
        # Pass and hallucination need a majority across repeats.
        npass = sum(1 for r in runs if r[0])
        nhall = sum(1 for r in runs if r[1])
        need = (repeats // 2) + 1
        ok = npass >= need
        hall = nhall >= need
        infra = any(_is_infra_error(r[2]) for r in runs)
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
               "ok": bool(ok), "hallucinated": bool(hall), "detail": detail,
               "infra": bool(infra), "duration_s": avg_dt, "tok_s": tps,
               "tok": tot_tok, "dur_total": round(sum(valid_durs), 2),
               # Truncated raw output for prompt-template diagnosis.
               "output": (outputs[rep_idx] or "")[:600]}
        results.append(rec)
        yield {"type": "check", "index": idx, **{k: rec[k] for k in
               ("id", "label", "category", "ok", "hallucinated", "detail",
                "infra", "duration_s", "tok_s")}}

    summary = _summarize(model_full, results)
    summary["saved"] = _persist(model_full, summary, results)
    yield {"type": "done", "summary": summary}


def _summarize(model_full: str, results: List[Dict[str, Any]]) -> Dict[str, Any]:
    tool = [r for r in results if r["category"] == "tool"]
    helper = [r for r in results if r["category"] == "helper"]
    tp = sum(1 for r in tool if r["ok"])
    hp = sum(1 for r in helper if r["ok"])
    passed = sum(1 for r in results if r["ok"])
    halluc = sum(1 for r in results if r["hallucinated"])
    tool_rate = (tp / len(tool)) if tool else 0.0
    helper_rate = (hp / len(helper)) if helper else 0.0
    tool_hall = sum(1 for r in tool if r["hallucinated"])
    tool_ok = bool(tool_rate >= 0.85 and tool_hall == 0)
    helper_ok = bool(helper_rate >= 0.70)
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
        "score": f"{passed}/{len(results)}",
        "tool": f"{tp}/{len(tool)}",
        "helper": f"{hp}/{len(helper)}",
        "hallucinations": halluc,
        "verdict": {"tool": tool_ok, "helper": helper_ok},
        "speed": speed,
        "infra": infra,
        "checks": results,
    }


def _persist(model_full: str, summary: Dict[str, Any], results: List[Dict[str, Any]]) -> bool:
    """Persist results only when no infrastructure errors occurred:
    provider outages and timeouts do not say anything about model quality."""
    if summary.get("infra") or any(r.get("infra") for r in results):
        logger.info("Suitability NOT saved for %s — infrastructure error (provider "
                    "unreachable/non-serverless)", model_full)
        return False
    from app.core.model_capabilities import save_raw_outputs, save_suitability
    # Stored checks: verdict, detail and timing only. The raw answer goes into
    # the local sidecar file — the test replays REAL logged prompts, so it
    # quotes the world's characters and plot and must not reach the shared,
    # committed results file.
    stored_checks = [{k: r.get(k) for k in
                      ("id", "label", "category", "ok", "hallucinated", "detail",
                       "duration_s", "tok_s")} for r in results]
    raw_outputs = {r["id"]: r.get("output") or "" for r in results if r.get("output")}
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
            "tool": summary["tool"],
            "helper": summary["helper"],
            "verdict": summary["verdict"],
            "speed": summary.get("speed"),
            "checks": stored_checks,
        },
    }
    try:
        save_suitability(model_full, record)
        save_raw_outputs(model_full, raw_outputs)
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
                                           "duration_s", "tok_s")})
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
