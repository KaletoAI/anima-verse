"""Model Suitability Test — prueft ein konkretes Modell auf Tool-/Helper-Eignung.

LOG-ABGELEITET: die Testfaelle stammen aus echten Aufrufen in
``logs/llm_calls.jsonl`` (Feld ``prompt`` = {system, user}, plus die reale
Antwort als "golden"). Damit testet der Test exakt das, was die App in der
Praxis verlangt — statt synthetischer Spielzeug-Prompts.

Ablauf:
1. Einmalig wird aus dem Log ein EINGEFRORENER Fixture-Satz extrahiert
   (``storage/suitability_cases.json``): pro Task echte {system,user}-Prompts,
   deren geloggte Antwort gueltig war, inkl. Positiv- (golden feuert ein Tool)
   und Negativ-/Abstain-Faellen (golden = NONE). Eingefroren = gleiche Faelle
   fuer jedes Modell -> Scores vergleichbar.
2. Replay der echten Prompts gegen das Kandidaten-Modell; validiert mit
   produktionsnahen Parsern je Format (echtes ``<tool name="X">…</tool>``-Format,
   JSON-Schema, Abstain, Text). Tool-Faelle werden mehrfach gelaufen (Konsistenz).

Schluesselsignal (kalibriert an echtem RP-Modell "Fallen Command"): RP-Modelle
geben Tool-Calls im FALSCHEN Format aus (``**SetActivity: …**`` statt
``<tool name="SetActivity">…</tool>``) und ertraenken sie in Prosa -> der
Projekt-Parser fuehrt NICHTS aus -> faellt hier durch.

Ergebnis -> storage/model_capabilities.json (``tested_*`` + ``tested_suitability``
+ ``tested_verdict``), Anzeige auf "Model Capabilities".
"""
import json
import re
import threading
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

from app.core.log import get_logger
from app.core.paths import get_storage_dir
from app.core.timeutils import utc_now

logger = get_logger("model_suitability")

Verdict = Tuple[bool, bool, str]  # (ok, hallucinated, detail)

_LOG_PATH = Path("./logs/llm_calls.jsonl")
_TAG_RE = re.compile(r'<tool\s+name="(\w+)">([\s\S]*?)</tool>')
# Pseudo-Tool-Marker, die RP-Modelle statt des echten Formats verwenden
_PSEUDO_RE = re.compile(r'(?im)(?:^|\n)\s*(?:\*\*|\[|#+\s*)?\s*'
                        r'(SetActivity|SetPose|SetLocation|Act|ChangeOutfit|TalkTo|'
                        r'SendMessage|ImageGenerator|Instagram|Retrospect)\s*[:=]')

# Tool-Tasks (Tool-LLM-Entscheidung) vs. Helper-Tasks
_TOOL_TASKS = {"thought", "intent"}
# Anzahl Faelle je Task + ob mehrfach (Konsistenz) gelaufen wird
_SELECT = [
    ("thought", 8),
    ("intent", 4),
    ("tool", 2),
    ("extraction", 4),
    ("relationship_summary", 3),
    ("image_prompt", 3),
    ("consolidation", 3),
    ("expression_map", 3),
    ("image_analysis", 2),
]
_TOOL_REPEATS = 3


def _cases_path() -> Path:
    return get_storage_dir() / "suitability_cases.json"


# ---------------------------------------------------------------------------
# JSON-Helfer
# ---------------------------------------------------------------------------

def _strip_fences(text: str) -> str:
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z0-9]*\s*", "", t)
        t = re.sub(r"\s*```$", "", t)
    return t.strip()


def _first_json(text: str, array: bool = False):
    """Produktionsnah: erstes {…} bzw. […] aus dem Text ziehen und parsen."""
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
# Fixture-Builder (aus dem Log)
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
    """Extrahiert einen eingefrorenen Fixture-Satz aus dem LLM-Log und speichert
    ihn nach ``storage/suitability_cases.json``. Gibt eine Zusammenfassung zurueck."""
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

    cases: List[Dict[str, Any]] = []
    for task, n in _SELECT:
        seen = set()
        picked = 0
        for e in rows:
            if picked >= n:
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
            # thought-Faelle nur als Positiv (golden feuert Tool) aufnehmen
            if task == "thought" and fmt != "tool":
                continue
            category = "tool" if task in _TOOL_TASKS else "helper"
            seen.add(key)
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
                "expect": _build_expect(fmt, golden),
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
    logger.info("Built %d suitability cases from log (%s)", len(cases), by_task)
    return {"total": len(cases), "by_task": by_task,
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
# Validatoren je Format
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


def list_checks() -> List[Dict[str, str]]:
    data = load_cases(auto_build=False)
    return [{"id": c["id"], "label": c["label"], "category": c["category"]}
            for c in data.get("cases", [])]


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def iter_suitability_results(model_full: str) -> Iterator[Dict[str, Any]]:
    """Spielt die Fixture-Faelle gegen ein Modell und yieldet NDJSON-Events."""
    from app.core.llm_router import create_llm_instance

    data = load_cases(auto_build=True)
    cases = data.get("cases", [])
    allowed = data.get("allowed_tools", [])
    if not cases:
        yield {"type": "error", "message": "No test cases — is logs/llm_calls.jsonl present?"}
        return

    inst = create_llm_instance("suitability_test", model_full)
    if inst is None:
        yield {"type": "error", "message": f"No provider found for model '{model_full}'"}
        return
    if not inst.available:
        yield {"type": "error", "message": f"Provider '{inst.provider_name}' is not available"}
        return
    try:
        client = inst.create_llm(temperature=0.3, max_tokens=900)
    except Exception as e:
        yield {"type": "error", "message": f"client init failed: {e}"}
        return

    def ask(system: str, user: str) -> str:
        resp = client.invoke([
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ])
        return (getattr(resp, "content", "") or "").strip()

    yield {"type": "start", "model": model_full, "total": len(cases)}

    results: List[Dict[str, Any]] = []
    for idx, case in enumerate(cases):
        validator = _VALIDATORS.get(case["fmt"], _v_text)
        repeats = int(case.get("repeats", 1)) or 1
        runs: List[Verdict] = []
        for _ in range(repeats):
            try:
                out = ask(case["system"], case["user"])
                runs.append(validator(out, case.get("expect", {}), allowed))
            except Exception as e:
                runs.append((False, False, f"call error: {str(e)[:100]}"))
        # Konsistenz: bestehen nur bei Mehrheit; Halluzination bei Mehrheit
        npass = sum(1 for r in runs if r[0])
        nhall = sum(1 for r in runs if r[1])
        need = (repeats // 2) + 1
        ok = npass >= need
        hall = nhall >= need
        # Detail vom repraesentativsten Run (erster Fail, sonst erster)
        rep = next((r for r in runs if not r[0]), runs[0])
        detail = rep[2]
        if repeats > 1:
            detail = f"{npass}/{repeats} runs ok — {detail}"
        rec = {"id": case["id"], "label": case["label"], "category": case["category"],
               "ok": bool(ok), "hallucinated": bool(hall), "detail": detail}
        results.append(rec)
        yield {"type": "check", "index": idx, **rec}

    summary = _summarize(model_full, results)
    _persist(model_full, summary, results)
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
    return {
        "model": model_full,
        "date": utc_now().date().isoformat(),
        "score": f"{passed}/{len(results)}",
        "tool": f"{tp}/{len(tool)}",
        "helper": f"{hp}/{len(helper)}",
        "hallucinations": halluc,
        "verdict": {"tool": tool_ok, "helper": helper_ok},
        "checks": results,
    }


def _persist(model_full: str, summary: Dict[str, Any], results: List[Dict[str, Any]]) -> None:
    from app.core.model_capabilities import (get_all_capabilities,
                                             save_model_capability)
    name = model_full.split("::", 1)[1] if "::" in model_full else model_full
    key = name.lower()
    caps_all = get_all_capabilities()
    save_key = key
    existing: Dict[str, Any] = {}
    for pat, c in caps_all.items():
        if pat.lower() == key:
            existing = dict(c)
            save_key = pat
            break
    existing["tested_date"] = summary["date"]
    existing["tested_score"] = summary["score"]
    existing["tested_tool_score"] = summary["tool"]
    existing["tested_helper_score"] = summary["helper"]
    existing["tested_hallucinations"] = summary["hallucinations"]
    existing["tested_verdict"] = summary["verdict"]
    existing["tested_suitability"] = {
        "model": model_full,
        "tool": summary["tool"],
        "helper": summary["helper"],
        "verdict": summary["verdict"],
        "checks": results,
    }
    try:
        save_model_capability(save_key, existing)
        logger.info("Suitability saved for %s: %s (tool_ok=%s)",
                    model_full, summary["score"], summary["verdict"]["tool"])
    except Exception as e:
        logger.error("Failed to persist suitability for %s: %s", model_full, e)


# ---------------------------------------------------------------------------
# Asynchroner Job-Runner (Start im Hintergrund-Thread, Status pollbar)
# ---------------------------------------------------------------------------
_JOBS: Dict[str, Dict[str, Any]] = {}
_JOBS_LOCK = threading.Lock()


def _run_job(model_full: str) -> None:
    try:
        for ev in iter_suitability_results(model_full):
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
                                           "hallucinated", "detail")})
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
    j["checks"] = list(job.get("checks") or [])
    return j


def start_test(model_full: str) -> Dict[str, Any]:
    """Startet den Eignungstest fuer ein Modell im Hintergrund. Laeuft bereits
    ein Job fuer dasselbe Modell, wird dessen aktueller Status zurueckgegeben."""
    with _JOBS_LOCK:
        cur = _JOBS.get(model_full)
        if cur and cur.get("status") == "running":
            return _snapshot(cur)
        job = {"model": model_full, "status": "running", "total": 0, "done": 0,
               "checks": [], "summary": None, "error": None}
        _JOBS[model_full] = job
    threading.Thread(target=_run_job, args=(model_full,), daemon=True,
                     name="suit-test").start()
    with _JOBS_LOCK:
        return _snapshot(_JOBS[model_full])


def get_job(model_full: str) -> Optional[Dict[str, Any]]:
    """Aktueller Status eines (laufenden oder fertigen) Jobs, oder None."""
    with _JOBS_LOCK:
        job = _JOBS.get(model_full)
        return _snapshot(job) if job else None


def list_jobs() -> List[Dict[str, Any]]:
    """Alle bekannten Jobs (fuer 'laeuft noch'-Anzeige nach Reload)."""
    with _JOBS_LOCK:
        return [_snapshot(j) for j in _JOBS.values()]
