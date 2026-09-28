"""Decision models — the call log, the shadow statistics and the register
that matches a prediction with what really happened
(development_instructions/plan-decision-models.md § 3.3, § 9).

Three stores:

* ``logs/decisions.jsonl`` — one line per endpoint answer (kind ``call``),
  per reported outcome (``outcome``) and per shortcut taken (``taken``).
  Lines carry ``starttime`` so ``llm_logger.prune_jsonl_log`` archives them.
* ``decision_stats`` (world.db) — counters per SYSTEM day × point ×
  endpoint × question (see world_db_schema.py for the column meaning).
* the OPEN-prediction register, in memory: ``(point, key)`` → the
  predictions of every asked endpoint plus the real outcome once reported.
  Shadow calls run in the background, so either side may arrive first; the
  pair is counted when both are there. An entry nobody resolves expires
  after ``PENDING_TTL_S`` and counts as ``no_outcome``.

Never raises into a caller: a failed write is logged at debug level.
"""
import json
import math
import threading
import time
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.core.log import get_logger
from app.core.timeutils import utc_now, utc_now_iso

logger = get_logger("decision")

LOG_FILE = Path("./logs/decisions.jsonl")
PENDING_TTL_S = 600.0
PENDING_MAX = 2000
# Latency histogram: a sample falls into the first edge it does not exceed.
LAT_EDGES_MS = (25, 50, 100, 200, 400, 800, 1600, 3200, 6400)
# A shadow call row keeps what the model was shown, cut per field to this many
# characters — the END is kept, the newest context sits there.
STATE_EXCERPT_MAX = 3000
# recent_disagreements reads at most this many bytes from the end of LOG_FILE.
DISAGREE_SCAN_BYTES = 8_000_000

_COUNTERS = ("calls", "answers", "low_conf", "agree", "disagree", "no_outcome", "taken")

_log_lock = threading.Lock()
_stats_lock = threading.Lock()
_pending_lock = threading.Lock()
_pending: Dict[Tuple[str, str], Dict[str, Any]] = {}


# ── JSONL ─────────────────────────────────────────────────────────────────

def _append(row: Dict[str, Any]) -> None:
    out = {"starttime": utc_now_iso()}
    try:
        from app.core.timeutils import game_time
        out["game_ts"] = game_time().canonical()
    except Exception:
        out["game_ts"] = ""
    out.update(row)
    try:
        line = json.dumps(out, ensure_ascii=False, default=str)
        with _log_lock:
            LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception as e:
        logger.debug("decision log write failed: %s", e)


# ── Stats ─────────────────────────────────────────────────────────────────

def _bucket(ms: float) -> str:
    for edge in LAT_EDGES_MS:
        if ms <= edge:
            return str(edge)
    return "inf"


def _bump(point: str, endpoint: str, question: str, counts: Dict[str, int],
          error: str = "", latency_ms: Optional[float] = None) -> None:
    """Add ``counts`` (and one error / latency sample) to one stats row."""
    from app.core.db import transaction
    day = utc_now_iso()[:10]
    vals = [int(counts.get(c, 0)) for c in _COUNTERS]
    with _stats_lock:
        try:
            with transaction() as conn:
                cur = conn.execute(
                    "SELECT errors_json, lat_hist_json FROM decision_stats "
                    "WHERE day=? AND point=? AND endpoint=? AND question=?",
                    (day, point, endpoint, question)).fetchone()
                errors = json.loads(cur[0]) if cur else {}
                hist = json.loads(cur[1]) if cur else {}
                if error:
                    errors[error] = errors.get(error, 0) + 1
                if latency_ms is not None:
                    b = _bucket(latency_ms)
                    hist[b] = hist.get(b, 0) + 1
                cols = ", ".join(_COUNTERS)
                marks = ", ".join("?" * len(_COUNTERS))
                upd = ", ".join(f"{c} = {c} + excluded.{c}" for c in _COUNTERS)
                conn.execute(
                    f"INSERT INTO decision_stats (day, point, endpoint, question, {cols}, "
                    f"errors_json, lat_hist_json) VALUES (?, ?, ?, ?, {marks}, ?, ?) "
                    f"ON CONFLICT(day, point, endpoint, question) DO UPDATE SET {upd}, "
                    f"errors_json = excluded.errors_json, lat_hist_json = excluded.lat_hist_json",
                    (day, point, endpoint, question, *vals,
                     json.dumps(errors), json.dumps(hist)))
        except Exception as e:
            logger.debug("decision stats write failed: %s", e)


def _excerpt(value: Any) -> str:
    """One state field as text, at most STATE_EXCERPT_MAX chars, END kept."""
    text = str(value)
    if len(text) <= STATE_EXCERPT_MAX:
        return text
    return "…" + text[len(text) - (STATE_EXCERPT_MAX - 1):]


def record_call(*, point: str, mode: str, endpoint: str, key: str, step: int,
                duration_ms: float, error: str,
                answers: Optional[Dict[str, Tuple[Any, float]]],
                min_confidence: float, questions: Dict[str, str],
                server_confidence: Dict[str, Any], state_chars: int,
                trace: Optional[Dict[str, str]],
                state: Optional[Dict[str, Any]] = None,
                options: Optional[Dict[str, List[str]]] = None) -> None:
    """One endpoint answer (or failure): JSONL line + counters.

    ``state`` (what the model was shown) is written in mode ``shadow`` only,
    each field cut by ``_excerpt``; ``options`` are the option keys per
    question."""
    row: Dict[str, Any] = {
        "kind": "call", "point": point, "mode": mode, "endpoint": endpoint,
        "key": key, "step": step, "duration_ms": round(duration_ms, 1),
        "state_chars": state_chars, "questions": questions,
        "min_confidence": round(float(min_confidence), 3),
        "trace_id": (trace or {}).get("id", ""),
        "trace_kind": (trace or {}).get("kind", ""),
        "who": (trace or {}).get("who", ""),
    }
    if options:
        row["options"] = {q: [str(k) for k in keys] for q, keys in options.items()}
    if state and mode == "shadow":
        row["state"] = {str(k): _excerpt(v) for k, v in state.items()}
    if error:
        row["error"] = error
    if answers is not None:
        row["answers"] = {q: {"value": v, "confidence": round(c, 4)}
                          for q, (v, c) in answers.items()}
        row["server_confidence"] = server_confidence
    _append(row)
    _bump(point, endpoint, "", {"calls": 1}, error=error,
          latency_ms=None if error == "blocked" else duration_ms)
    for q, (_v, conf) in (answers or {}).items():
        _bump(point, endpoint, q, {"answers": 1, "low_conf": 1 if conf < min_confidence else 0})


# ── Open-prediction register ──────────────────────────────────────────────

def _same(pred: Any, actual: Any) -> bool:
    if isinstance(pred, bool) or isinstance(actual, bool):
        return bool(pred) == bool(actual)
    if isinstance(pred, (int, float)) and isinstance(actual, (int, float)):
        return round(pred) == round(actual)
    return str(pred) == str(actual)


def _ready(entry: Dict[str, Any]) -> bool:
    return not entry["waiting"] and (entry["taken"] or entry["actual"] is not None)


def _count(point: str, entry: Dict[str, Any]) -> None:
    """Count one resolved (or expired) entry. Called WITHOUT _pending_lock."""
    if entry["taken"]:
        for ep in entry["preds"]:
            _bump(point, ep, "", {"taken": 1})
        return
    actual = entry["actual"]
    if actual is None:
        for ep in entry["preds"]:
            _bump(point, ep, "", {"no_outcome": 1})
        return
    for ep, preds in entry["preds"].items():
        for q, (value, conf) in preds.items():
            if q not in actual or conf < entry["min"]:
                continue
            _bump(point, ep, q, {"agree": 1} if _same(value, actual[q]) else {"disagree": 1})


def _expire_locked(now: float) -> List[Tuple[str, Dict[str, Any]]]:
    out = []
    for pk in [pk for pk, e in _pending.items() if now - e["t"] >= PENDING_TTL_S]:
        out.append((pk[0], _pending.pop(pk)))
    while len(_pending) >= PENDING_MAX:
        pk = min(_pending, key=lambda k: _pending[k]["t"])
        out.append((pk[0], _pending.pop(pk)))
    return out


def sweep() -> None:
    with _pending_lock:
        done = _expire_locked(time.monotonic())
    for point, entry in done:
        _count(point, entry)


def open_pending(point: str, key: str, endpoints: List[str], min_confidence: float) -> None:
    with _pending_lock:
        done = _expire_locked(time.monotonic())
        _pending[(point, key)] = {"t": time.monotonic(), "min": float(min_confidence),
                                  "waiting": set(endpoints), "preds": {},
                                  "actual": None, "taken": False}
    for p, entry in done:
        _count(p, entry)


def _resolve_if_ready(point: str, key: str) -> None:
    with _pending_lock:
        entry = _pending.get((point, key))
        if entry is None or not _ready(entry):
            return
        _pending.pop((point, key), None)
    _count(point, entry)


def deliver(point: str, key: str, endpoint: str,
            preds: Optional[Dict[str, Tuple[Any, float]]], done: bool) -> None:
    """One step of one endpoint arrived. ``preds`` None = the endpoint failed."""
    with _pending_lock:
        entry = _pending.get((point, key))
        if entry is None:
            return
        if preds:
            entry["preds"].setdefault(endpoint, {}).update(preds)
        if done:
            entry["waiting"].discard(endpoint)
    _resolve_if_ready(point, key)


def set_outcome(point: str, key: str, actual: Dict[str, Any]) -> None:
    with _pending_lock:
        entry = _pending.get((point, key))
        if entry is None:
            return
        entry["actual"] = dict(actual)
    _append({"kind": "outcome", "point": point, "key": key, "actual": dict(actual)})
    _resolve_if_ready(point, key)


def set_taken(point: str, key: str) -> None:
    with _pending_lock:
        entry = _pending.get((point, key))
        if entry is None:
            return
        entry["taken"] = True
    _append({"kind": "taken", "point": point, "key": key})
    _resolve_if_ready(point, key)


# ── Read side (admin) ─────────────────────────────────────────────────────

def percentile_label(hist: Dict[str, int], p: float) -> str:
    total = sum(int(v) for v in hist.values())
    if total <= 0:
        return ""
    need = math.ceil(p * total)
    cum = 0
    for edge in LAT_EDGES_MS:
        cum += int(hist.get(str(edge), 0))
        if cum >= need:
            return f"<={edge} ms"
    return f">{LAT_EDGES_MS[-1]} ms"


def query_stats(days: int = 7) -> List[Dict[str, Any]]:
    """Counters of the last ``days`` SYSTEM days, summed per point × endpoint × question."""
    from app.core.db import get_connection
    since = (utc_now() - timedelta(days=max(1, int(days)) - 1)).isoformat()[:10]
    try:
        rows = get_connection().execute(
            "SELECT point, endpoint, question, " + ", ".join(_COUNTERS)
            + ", errors_json, lat_hist_json FROM decision_stats WHERE day >= ?",
            (since,)).fetchall()
    except Exception as e:
        logger.debug("decision stats read failed: %s", e)
        return []
    agg: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    for r in rows:
        k = (r[0], r[1], r[2])
        a = agg.setdefault(k, {"point": r[0], "endpoint": r[1], "question": r[2],
                               **{c: 0 for c in _COUNTERS}, "errors": {}, "_hist": {}})
        for i, c in enumerate(_COUNTERS):
            a[c] += int(r[3 + i] or 0)
        for name, n in json.loads(r[3 + len(_COUNTERS)] or "{}").items():
            a["errors"][name] = a["errors"].get(name, 0) + int(n)
        for b, n in json.loads(r[4 + len(_COUNTERS)] or "{}").items():
            a["_hist"][b] = a["_hist"].get(b, 0) + int(n)
    out = []
    for k in sorted(agg):
        a = agg[k]
        hist = a.pop("_hist")
        a["p50"] = percentile_label(hist, 0.5)
        a["p95"] = percentile_label(hist, 0.95)
        out.append(a)
    return out


def _tail_rows() -> List[Dict[str, Any]]:
    """The JSON rows of the last DISAGREE_SCAN_BYTES of LOG_FILE, in file
    order. A partial first line and malformed lines are dropped."""
    out: List[Dict[str, Any]] = []
    try:
        with open(LOG_FILE, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            start = max(0, size - int(DISAGREE_SCAN_BYTES))
            f.seek(start)
            if start > 0:
                f.readline()  # the cut line
            data = f.read()
    except Exception:
        return out
    for line in data.decode("utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
        except Exception:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def recent_disagreements(point: str = "", limit: int = 50,
                         include_unsure: bool = False) -> List[Dict[str, Any]]:
    """Predictions that differ from what the usual path did, newest first,
    read back from the tail of the JSONL log. A key that has a ``taken`` row
    is skipped (the decider acted). Unsure ones (below the row's
    ``min_confidence``) only with ``include_unsure``. Never raises."""
    try:
        rows = _tail_rows()
        taken = set()
        actual: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for r in rows:
            pk = (str(r.get("point", "")), str(r.get("key", "")))
            if r.get("kind") == "taken":
                taken.add(pk)
            elif r.get("kind") == "outcome" and isinstance(r.get("actual"), dict):
                actual[pk] = r["actual"]
        found: List[Tuple[str, int, Dict[str, Any]]] = []
        for idx, r in enumerate(rows):
            if r.get("kind") != "call" or not isinstance(r.get("answers"), dict):
                continue
            pk = (str(r.get("point", "")), str(r.get("key", "")))
            if point and pk[0] != point:
                continue
            if pk in taken or pk not in actual:
                continue
            real = actual[pk]
            min_conf = r.get("min_confidence")
            state = r.get("state") if isinstance(r.get("state"), dict) else {}
            opts = r.get("options") if isinstance(r.get("options"), dict) else {}
            for q, ans in r["answers"].items():
                if q not in real or not isinstance(ans, dict):
                    continue
                pred = ans.get("value")
                if _same(pred, real[q]):
                    continue
                try:
                    conf = float(ans.get("confidence", 0.0))
                except (TypeError, ValueError):
                    conf = 0.0
                try:
                    confident = min_conf is None or conf >= float(min_conf)
                except (TypeError, ValueError):
                    confident = True
                if not confident and not include_unsure:
                    continue
                q_opts = opts.get(q)
                found.append((str(r.get("starttime", "")), idx, {
                    "starttime": r.get("starttime", ""), "point": pk[0],
                    "endpoint": r.get("endpoint", ""), "key": pk[1], "question": q,
                    "predicted": pred, "confidence": conf, "confident": confident,
                    "actual": real[q], "state": state,
                    "options": list(q_opts) if isinstance(q_opts, list) else [],
                }))
        # Newest first; a tie within one second keeps the file order reversed.
        found.sort(key=lambda t: (t[0], t[1]), reverse=True)
        return [item for _st, _i, item in found[:max(0, int(limit))]]
    except Exception as e:
        logger.debug("decision disagreements read failed: %s", e)
        return []
