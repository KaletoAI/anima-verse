"""Decision models — optional typed decisions over the Jev protocol
(development_instructions/plan-decision-models.md).

A decision model answers typed questions about a state — yes/no (``Noul``),
one of a fixed set (``Choice``), a point on a scale (``Score``) — with
probabilities and without generating text. Laya, openjev and TypeSafe Jev all
speak ``POST <url>/v1/systemone``; which one answers is an endpoint URL in the
world config (``decision.endpoints``), nothing else.

THE CONTRACT (same as ``embedding.embed``): ``decide`` never raises and
returns ``None`` whenever the caller should take its usual path — master
switch off, point unknown or ``off``, no usable endpoint, a failure, an answer
that does not fit the questions, or mode ``shadow``. Nothing may ever depend
on a decision model being there.

Modes per decision point (``decision.points.<id>.mode``):
* ``off``    — nothing happens.
* ``shadow`` — every listed endpoint is asked IN THE BACKGROUND and logged;
  ``decide`` returns ``None`` at once, so the caller's path gains no latency.
* ``on``     — the FIRST listed endpoint is asked synchronously; answers below
  the point's ``min_confidence`` are removed (a missing key = decide yourself).

Confidence is computed HERE from the returned probabilities, never taken from
the server: Laya reports ``1 - normalised entropy`` for choice/score, openjev
the largest probability, so one threshold would mean two different things.

Calls bypass the LLM queue (like embeddings): 30–500 ms, no prompt cache to
protect. Callers on the event loop wrap ``decide`` in ``asyncio.to_thread``.
"""
from __future__ import annotations

import json
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import httpx

from app.core import config, decision_log
from app.core.log import get_logger

logger = get_logger("decision")

MAX_OPTIONS = 255
MAX_STEPS = 3
BLOCK_AFTER_FAILURES = 3
BLOCK_SECONDS = 60.0
WARN_EVERY_S = 600.0
SHADOW_MAX_INFLIGHT = 8
PROBE_TIMEOUT_S = 30.0


# ── Types ─────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Noul:
    instructions: str


@dataclass(frozen=True)
class Choice:
    instructions: str
    options: Dict[str, str]


@dataclass(frozen=True)
class Score:
    instructions: str
    anchors: List[str]


Question = Union[Noul, Choice, Score]


@dataclass(frozen=True)
class Answer:
    value: Union[bool, str, float]
    p_yes: Optional[float]
    confidence: float
    distribution: Dict[str, float]


@dataclass(frozen=True)
class Decision:
    answers: Dict[str, Answer]


@dataclass(frozen=True)
class PointSpec:
    point_id: str
    label: str
    description: str
    default_min_confidence: float
    default_timeout_s: float
    origin: str


@dataclass(frozen=True)
class _Settings:
    mode: str
    endpoints: List[str]
    min_confidence: float
    timeout_s: float


@dataclass
class _Reply:
    endpoint: str
    answers: Optional[Dict[str, Answer]]
    error: str
    duration_ms: float
    server_confidence: Dict[str, Any]


# ── Registry ──────────────────────────────────────────────────────────────

_points: Dict[str, PointSpec] = {}
_points_lock = threading.Lock()


def register_point(point_id: str, *, label: str, description: str,
                   default_min_confidence: float = 0.7,
                   default_timeout_s: float = 2.0, origin: str = "core") -> None:
    """Announce a decision point. An unregistered point always decides nothing.
    Plugins call this from their ``on_load`` module and pass their package name
    as ``origin``."""
    spec = PointSpec(point_id, label, description, float(default_min_confidence),
                     float(default_timeout_s), origin)
    with _points_lock:
        _points[point_id] = spec


def registered_points() -> List[PointSpec]:
    with _points_lock:
        return [_points[k] for k in sorted(_points)]


# ── Config ────────────────────────────────────────────────────────────────

def _section() -> Dict[str, Any]:
    sec = config.get("decision")
    return sec if isinstance(sec, dict) else {}


def _num(raw: Any, default: float) -> float:
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return default
    return v if math.isfinite(v) and v > 0 else default


def _settings(spec: PointSpec, sec: Dict[str, Any]) -> _Settings:
    raw = (sec.get("points") or {}).get(spec.point_id) or {}
    if not isinstance(raw, dict):
        raw = {}
    eps = [str(e).strip() for e in (raw.get("endpoints") or []) if str(e).strip()]
    return _Settings(mode=str(raw.get("mode") or "off"), endpoints=eps,
                     min_confidence=_num(raw.get("min_confidence"), spec.default_min_confidence),
                     timeout_s=_num(raw.get("timeout_s"), spec.default_timeout_s))


def _endpoint(sec: Dict[str, Any], name: str, *, enabled_only: bool = True) -> Optional[Dict[str, Any]]:
    for e in sec.get("endpoints") or []:
        if not isinstance(e, dict) or e.get("name") != name:
            continue
        if not str(e.get("url") or "").strip():
            return None
        if enabled_only and not e.get("enabled", True):
            return None
        return e
    return None


def is_active(point_id: str) -> bool:
    """True when the master switch is on and the point runs in shadow or on —
    lets a caller skip building its questions when nothing would happen."""
    try:
        sec = _section()
        spec = _points.get(point_id)
        return bool(sec.get("enabled")) and spec is not None \
            and _settings(spec, sec).mode in ("shadow", "on")
    except Exception:
        return False


# ── Protocol ──────────────────────────────────────────────────────────────

def _question_json(q: Any) -> Optional[Dict[str, Any]]:
    if isinstance(q, Noul):
        return {"type": "noul", "instructions": q.instructions}
    if isinstance(q, Choice):
        if not 2 <= len(q.options) <= MAX_OPTIONS:
            return None
        return {"type": "choice", "instructions": q.instructions, "criteria": dict(q.options)}
    if isinstance(q, Score):
        if len(q.anchors) < 2:
            return None
        return {"type": "score", "instructions": q.instructions, "criteria": list(q.anchors)}
    return None


def _is_prob(v: Any) -> bool:
    return (not isinstance(v, bool) and isinstance(v, (int, float))
            and math.isfinite(v) and 0.0 <= v <= 1.0)


def _probs(raw: Dict[str, Any], keys: List[str]) -> Optional[Dict[str, float]]:
    p = raw.get("probabilities")
    if not isinstance(p, dict) or set(p) != set(keys):
        return None
    if not all(_is_prob(p[k]) for k in keys):
        return None
    out = {k: float(p[k]) for k in keys}
    return out if abs(sum(out.values()) - 1.0) <= 0.02 else None


def _parse_answer(q: Question, raw: Any) -> Optional[Answer]:
    """One raw answer → Answer with the OWN confidence rule (spec § 2.3)."""
    if not isinstance(raw, dict):
        return None
    if isinstance(q, Noul):
        p = raw.get("noul")
        if not _is_prob(p):
            return None
        p = float(p)
        return Answer(value=p >= 0.5, p_yes=p, confidence=max(p, 1.0 - p),
                      distribution={"yes": p, "no": 1.0 - p})
    if isinstance(q, Choice):
        probs = _probs(raw, list(q.options))
        choice = raw.get("choice")
        if probs is None or choice not in q.options:
            return None
        return Answer(value=choice, p_yes=None, confidence=probs[choice], distribution=probs)
    if isinstance(q, Score):
        probs = _probs(raw, [str(i) for i in range(len(q.anchors))])
        s = raw.get("score")
        if (probs is None or isinstance(s, bool) or not isinstance(s, (int, float))
                or not math.isfinite(s) or not 0 <= s <= len(q.anchors) - 1):
            return None
        return Answer(value=float(s), p_yes=None, confidence=max(probs.values()),
                      distribution=probs)
    return None


def _post(ep: Dict[str, Any], payload: Dict[str, Any], timeout: float) -> Tuple[Optional[Dict[str, Any]], str]:
    url = str(ep.get("url") or "").rstrip("/") + "/v1/systemone"
    headers = {"Content-Type": "application/json"}
    api_key = str(ep.get("api_key") or "").strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        r = httpx.post(url, json=payload, headers=headers, timeout=timeout)
    except httpx.TimeoutException:
        return None, "timeout"
    except httpx.HTTPError:
        return None, "connect"
    except (TypeError, ValueError):
        return None, "bad_request"
    if r.status_code != 200:
        return None, f"http_{r.status_code}"
    try:
        body = r.json()
    except ValueError:
        return None, "bad_json"
    return (body, "") if isinstance(body, dict) else (None, "bad_json")


# ── Endpoint health ───────────────────────────────────────────────────────

_health_lock = threading.Lock()
_fail_streak: Dict[str, int] = {}
_blocked_until: Dict[str, float] = {}
_last_warn: Dict[Tuple[str, str], float] = {}


def _is_blocked(name: str) -> bool:
    with _health_lock:
        return time.monotonic() < _blocked_until.get(name, 0.0)


def _note_result(name: str, error: str) -> None:
    warn = False
    with _health_lock:
        if not error:
            _fail_streak[name] = 0
            return
        n = _fail_streak.get(name, 0) + 1
        if n >= BLOCK_AFTER_FAILURES:
            _blocked_until[name] = time.monotonic() + BLOCK_SECONDS
            n = 0
        _fail_streak[name] = n
        now = time.monotonic()
        last = _last_warn.get((name, error))
        if last is None or now - last >= WARN_EVERY_S:
            _last_warn[(name, error)] = now
            warn = True
    (logger.warning if warn else logger.debug)("Decision endpoint %s failed: %s", name, error)


def endpoint_status() -> Dict[str, Dict[str, Any]]:
    now = time.monotonic()
    with _health_lock:
        names = set(_fail_streak) | set(_blocked_until)
        return {n: {"fail_streak": _fail_streak.get(n, 0),
                    "blocked_for_s": round(max(0.0, _blocked_until.get(n, 0.0) - now), 1)}
                for n in sorted(names)}


def _ask(ep: Dict[str, Any], state: Dict[str, Any], questions: Dict[str, Question],
         timeout: float, *, track: bool = True) -> _Reply:
    name = str(ep.get("name") or "")
    if track and _is_blocked(name):
        return _Reply(name, None, "blocked", 0.0, {})
    payload = {"model": str(ep.get("model") or ""), "state": state,
               "questions": {q: _question_json(x) for q, x in questions.items()}}
    t0 = time.monotonic()
    body, err = _post(ep, payload, timeout)
    ms = (time.monotonic() - t0) * 1000.0
    answers: Optional[Dict[str, Answer]] = None
    server_conf: Dict[str, Any] = {}
    if body is not None:
        raw = body.get("answers")
        if isinstance(raw, dict):
            answers = {}
            for q, spec in questions.items():
                a = _parse_answer(spec, raw.get(q))
                if a is None:
                    answers = None
                    break
                answers[q] = a
                server_conf[q] = (raw.get(q) or {}).get("confidence")
        if answers is None:
            err = "schema"
    if track:
        _note_result(name, err)
    return _Reply(name, answers, err, ms, server_conf)


# ── One endpoint, all steps ───────────────────────────────────────────────

def _run_endpoint(point: str, st: _Settings, ep: Dict[str, Any], state: Dict[str, Any],
                  questions: Dict[str, Question],
                  then: Optional[Callable[[Dict[str, Answer]], Optional[Dict[str, Question]]]],
                  key: Optional[str], mode: str,
                  trace: Optional[Dict[str, str]]) -> Optional[Dict[str, Answer]]:
    """Ask one endpoint, following ``then`` for up to MAX_STEPS steps. Returns
    the CONFIDENT answers of all steps, or None when a step failed."""
    confident: Dict[str, Answer] = {}
    state_chars = len(json.dumps(state, ensure_ascii=False, default=str))
    step_qs: Optional[Dict[str, Question]] = questions
    step = 1
    while step_qs:
        reply = _ask(ep, state, step_qs, st.timeout_s)
        preds = (None if reply.answers is None
                 else {q: (a.value, a.confidence) for q, a in reply.answers.items()})
        decision_log.record_call(
            point=point, mode=mode, endpoint=reply.endpoint, key=key or "", step=step,
            duration_ms=reply.duration_ms, error=reply.error, answers=preds,
            min_confidence=st.min_confidence,
            questions={q: type(x).__name__.lower() for q, x in step_qs.items()},
            server_confidence=reply.server_confidence, state_chars=state_chars, trace=trace)
        if reply.answers is None:
            if key:
                decision_log.deliver(point, key, reply.endpoint, None, done=True)
            return None
        step_conf = {q: a for q, a in reply.answers.items() if a.confidence >= st.min_confidence}
        confident.update(step_conf)
        nxt: Optional[Dict[str, Question]] = None
        if then is not None and step < MAX_STEPS:
            try:
                nxt = then(dict(step_conf)) or None
            except Exception as e:
                logger.debug("decision %s: then() failed: %s", point, e)
                nxt = None
            if nxt and any(_question_json(x) is None for x in nxt.values()):
                nxt = None
        if key:
            decision_log.deliver(point, key, reply.endpoint, preds, done=not nxt)
        step_qs = nxt
        step += 1
    return confident


# ── Shadow pool ───────────────────────────────────────────────────────────

_shadow_slots = threading.BoundedSemaphore(SHADOW_MAX_INFLIGHT)
_shadow_pool = ThreadPoolExecutor(max_workers=SHADOW_MAX_INFLIGHT,
                                  thread_name_prefix="decision-shadow")
_shadow_futures: set = set()
_shadow_lock = threading.Lock()


def _submit_shadow(point, st, ep, state, questions, then, key, trace) -> None:
    name = str(ep.get("name") or "")
    if not _shadow_slots.acquire(blocking=False):
        logger.debug("decision %s: shadow pool full, %s skipped", point, name)
        if key:
            decision_log.deliver(point, key, name, None, done=True)
        return

    def job():
        try:
            _run_endpoint(point, st, ep, state, questions, then, key, "shadow", trace)
        except Exception as e:
            logger.debug("decision %s: shadow call to %s failed: %s", point, name, e)
            if key:
                decision_log.deliver(point, key, name, None, done=True)
        finally:
            _shadow_slots.release()

    fut = _shadow_pool.submit(job)
    with _shadow_lock:
        _shadow_futures.add(fut)
    fut.add_done_callback(lambda f: _shadow_futures.discard(f))


def _wait_shadow(timeout: float) -> None:
    """Test hook: wait until the shadow calls in flight have finished."""
    with _shadow_lock:
        futs = list(_shadow_futures)
    if futs:
        wait(futs, timeout=timeout)


# ── Public API ────────────────────────────────────────────────────────────

def decide(point_id: str, state: Dict[str, Any], questions: Dict[str, Question], *,
           key: Optional[str] = None,
           then: Optional[Callable[[Dict[str, Answer]], Optional[Dict[str, Question]]]] = None,
           ) -> Optional[Decision]:
    """Ask the decision model of ``point_id``. ``None`` = take your usual path.

    ``key`` (chosen by the caller) ties this call to a later
    ``record_outcome``/``mark_taken``. ``then`` chains a follow-up: it gets the
    confident answers of a step and returns the next questions or None."""
    try:
        return _decide(point_id, state, questions, key, then)
    except Exception as e:
        logger.debug("decide(%s) failed: %s", point_id, e)
        return None


def _decide(point_id, state, questions, key, then) -> Optional[Decision]:
    sec = _section()
    if not sec.get("enabled"):
        return None
    spec = _points.get(point_id)
    if spec is None:
        return None
    st = _settings(spec, sec)
    if st.mode not in ("shadow", "on"):
        return None
    if not questions or any(_question_json(q) is None for q in questions.values()):
        logger.debug("decision %s: invalid questions, nothing asked", point_id)
        return None
    names = st.endpoints if st.mode == "shadow" else st.endpoints[:1]
    eps = [e for e in (_endpoint(sec, n) for n in names) if e is not None]
    if not eps:
        return None
    from app.core.turn_trace import current_trace
    trace = current_trace()
    trace = dict(trace) if trace else None
    if key:
        decision_log.open_pending(point_id, key, [str(e.get("name") or "") for e in eps],
                                  st.min_confidence)
    if st.mode == "shadow":
        for ep in eps:
            _submit_shadow(point_id, st, ep, state, questions, then, key, trace)
        return None
    answers = _run_endpoint(point_id, st, eps[0], state, questions, then, key, "on", trace)
    return None if answers is None else Decision(answers=answers)


def record_outcome(point_id: str, key: str, actual: Dict[str, Any]) -> None:
    """What the usual path really did — compared with the predictions under ``key``.
    A no-op for a key ``decide`` never opened."""
    try:
        decision_log.set_outcome(point_id, key, actual)
    except Exception as e:
        logger.debug("record_outcome(%s) failed: %s", point_id, e)


def mark_taken(point_id: str, key: str) -> None:
    """The caller acted on the decision (mode ``on``) — no usual path ran to compare."""
    try:
        decision_log.set_taken(point_id, key)
    except Exception as e:
        logger.debug("mark_taken(%s) failed: %s", point_id, e)


_PROBE_STATE = {"document": "Kira sits alone in the kitchen. Nobody has spoken to her "
                            "and nothing new has happened."}
_PROBE_QUESTIONS = {"turn": Choice("Does Kira have a reason to act or speak right now?",
                                   {"act": "yes, there is a reason", "idle": "no, nothing new"})}


def probe_endpoint(name: str) -> Dict[str, Any]:
    """Admin 'Test': one fixed question to a SAVED endpoint (enabled or not),
    with a long timeout so a cold llama-swap slot can load. Does not touch the
    endpoint's block state."""
    ep = _endpoint(_section(), name, enabled_only=False)
    if ep is None:
        return {"ok": False, "duration_ms": 0.0, "error": "unknown endpoint", "answer": None}
    reply = _ask(ep, _PROBE_STATE, _PROBE_QUESTIONS, PROBE_TIMEOUT_S, track=False)
    a = (reply.answers or {}).get("turn")
    return {"ok": a is not None, "duration_ms": round(reply.duration_ms, 1), "error": reply.error,
            "answer": None if a is None else {"value": a.value, "confidence": round(a.confidence, 4),
                                              "distribution": a.distribution}}
