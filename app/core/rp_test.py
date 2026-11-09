"""Roleplay suitability test — the RP counterpart of ``model_suitability``.

Design: docs/superpowers/specs/2026-11-09-rp-model-test-design.md.

The cases (``shared/config/rp_test_cases.json``, built by
``scripts/rp_test_build_cases.py``) are the REAL chat prompt of a 1:1 in-person
turn with an SFW demo cast. Each case pins one failure mode seen in play:
repetition loops, an absent person walking in, a cat that talks, a character
that melts at flattery, the player's actions decided for him, ...

Two halves, deliberately apart:
- Code (``rp_metrics``) measures what code can measure: repetition with the
  game's own rule, tool syntax / thinking leaks / speaker labels in the prose,
  the mood marker the prompt asks for, language, truncation, refusals, length.
- A judge model (chosen in the setup, never the model under test) answers
  yes/no questions per case from ``facts`` — not from the whole system prompt.
  It first has to pass hand-written calibration anchors; a judge that misses
  them is not trusted, and its dimensions stay ``not judged`` while the code
  half is still saved. Judging can be repeated later from the stored answers
  (job kind ``rp_judge``).

Results live in ``model_capabilities.json`` → ``rp_results`` (keyed like the
tool test by "provider::model"), raw answers in the gitignored sidecar.
A run with a provider outage (infrastructure error) is not saved.
"""
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from statistics import median
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

from app.core import rp_metrics as metrics
from app.core.log import get_logger
from app.core.timeutils import utc_now

logger = get_logger("rp_test")

SCORER_VERSION = "rp-1"
DIMENSIONS = ("repetition", "prose", "character", "logic", "discipline")
THRESHOLD_OVERALL = 70
THRESHOLD_DIMENSION = 55
BORDERLINE_BAND = 5
JUDGE_COVERAGE = 0.8
CALIBRATION_MIN = 0.9
JUDGE_MAX_TOKENS = 1500
JUDGE_RETRY_S = 5
ROOT = Path(__file__).resolve().parents[2]
CASES_PATH = ROOT / "shared/config/rp_test_cases.json"
# Hard caps: one occurrence anywhere makes the verdict "no".
CAPS = ("refusal", "salad", "empty", "language", "rejected")
CAP_LABELS = {"refusal": "refusal", "salad": "broken output", "empty": "empty reply", "language": "language",
              "rejected": "rejected request"}
# Judge requests in flight per judge provider, across all RP jobs (an "rp" job
# judges on a provider whose own queue it does not hold).
_JUDGE_GATES: Dict[str, threading.BoundedSemaphore] = {}
_JUDGE_GATES_LOCK = threading.Lock()


class JudgeError(RuntimeError):
    """The judge gave no usable answer."""


def fixture_version(data: Dict[str, Any]) -> str:
    import hashlib
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


_CASES_CACHE: Dict[str, Any] = {}


def load_rp_cases() -> Dict[str, Any]:
    """The fixture plus its version hash; parsed once per file change (the
    report polls it), handed out as a copy."""
    from copy import deepcopy
    stat = CASES_PATH.stat()
    key = (str(CASES_PATH), stat.st_mtime_ns, stat.st_size)
    if _CASES_CACHE.get("key") != key:
        data = json.loads(CASES_PATH.read_text(encoding="utf-8"))
        data["fixture_version"] = fixture_version({k: data.get(k) for k in ("cases", "anchors", "cliches")})
        _CASES_CACHE.update(key=key, data=data)
    return deepcopy(_CASES_CACHE["data"])


def cases_info() -> Dict[str, Any]:
    data = load_rp_cases()
    cases = [{"id": c["id"], "label": c["label"], "focus": c["focus"], "repeats": c["repeats"],
              "turns": 1 + len(c.get("turns", []))} for c in data["cases"]]
    return {"total": len(cases), "cases": cases,
            "replies": sum(c["repeats"] * c["turns"] for c in cases),
            "anchors": len(data.get("anchors", []))}


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

def _number(value, low, high) -> bool:
    import math
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and low <= value <= high and math.isfinite(value))


def _validate_judge(judge: Any) -> Dict[str, str]:
    if (not isinstance(judge, dict) or set(judge) != {"provider", "model"}
            or not all(isinstance(judge[k], str) and judge[k].strip() for k in ("provider", "model"))):
        raise ValueError("judge must be an object with provider and model")
    return {"provider": judge["provider"].strip(), "model": judge["model"].strip()}


def validate_rp_settings(settings: Any) -> Dict[str, Any]:
    """Validate and copy explicit RP test parameters; never consult routing."""
    from copy import deepcopy
    from app.core.llm_router import parse_extra_params
    defaults = {"temperature": 0.8, "top_p": None, "repetition_penalty": None, "max_tokens": 0,
                "chat_template": "", "thinking_budget": 0, "extra_params": {}, "judge": None}
    if not isinstance(settings, dict) or settings.keys() - defaults.keys():
        raise ValueError("settings must be an object with known keys only")
    result = {**defaults, **deepcopy(settings)}
    if not _number(result["temperature"], 0, 2):
        raise ValueError("temperature must be a number from 0 to 2")
    if result["top_p"] is not None and not _number(result["top_p"], 0.01, 1):
        raise ValueError("top_p must be null or a number from 0.01 to 1")
    if result["repetition_penalty"] is not None and not _number(result["repetition_penalty"], 0, 1.5):
        raise ValueError("repetition_penalty must be null or a number from 0 to 1.5")
    # 0 = no cap sent (the provider default) — how the in-game chat entries
    # run; a test-only cap would score its own cut-offs as "truncated".
    tokens = result["max_tokens"]
    if not isinstance(tokens, int) or isinstance(tokens, bool) or not 0 <= tokens <= 200000:
        raise ValueError("max_tokens must be an integer from 0 to 200000")
    if not isinstance(result["chat_template"], str):
        raise ValueError("chat_template must be text")
    budget = result["thinking_budget"]
    if type(budget) is not int or not 0 <= budget <= 3000:
        raise ValueError("thinking_budget must be an integer from 0 (off) to 3000")
    if not isinstance(result["extra_params"], dict):
        raise ValueError("extra_params must be a JSON object")
    result["extra_params"] = parse_extra_params(result["extra_params"])
    result["judge"] = _validate_judge(result["judge"])
    return result


def validate_rp_judge_settings(settings: Any) -> Dict[str, Any]:
    if not isinstance(settings, dict) or set(settings) != {"judge"}:
        raise ValueError("settings must be {judge: {provider, model}}")
    return {"judge": _validate_judge(settings["judge"])}


def judge_key(settings: Dict[str, Any]) -> str:
    judge = settings["judge"]
    return f"{judge['provider']}::{judge['model']}"


# ---------------------------------------------------------------------------
# Calls
# ---------------------------------------------------------------------------

def _limits(inst, model: str, requested: int) -> Tuple[int, Any]:
    """Parallel requests a provider allows for this test, and its quota —
    the same caps the tool test applies (max_concurrent, whole-key parallel
    limit, the model's server slots)."""
    from app.core import config
    from app.core.model_suitability import model_slots
    provider_obj = getattr(inst, "_provider", None)
    cap = next((p.get("max_concurrent") for p in config.get("providers", []) or []
                if p.get("name") == getattr(inst, "provider_name", "")), None)
    try:
        cap = int(cap) if cap else requested
    except (TypeError, ValueError):
        cap = requested
    limit = max(1, min(requested, cap))
    parallel = getattr(provider_obj, "max_parallel_llm", 0) or 0
    if type(parallel) is int and parallel > 0:
        limit = min(limit, parallel)
    slots = model_slots(provider_obj, model)
    if slots:
        limit = min(limit, slots)
    return limit, getattr(provider_obj, "quota", None)


def _invoke(client, messages, quota, cancel_event) -> Dict[str, Any]:
    """One request with the tool test's quota handling; returns response metadata."""
    from app.core.model_suitability import _MAX_REMOTE_RATE_LIMITS, _wait_for_quota
    from app.core.provider_quota import QuotaUnavailable, rate_limit_error
    remote_limits = 0
    while True:
        _wait_for_quota(quota, cancel_event)
        started = time.monotonic()
        try:
            resp = client.invoke(messages)
            break
        except Exception as exc:
            cause = rate_limit_error(exc) if quota is not None else None
            if cause is None:
                raise
            if not isinstance(cause, QuotaUnavailable):
                remote_limits += 1
                if remote_limits > _MAX_REMOTE_RATE_LIMITS:
                    raise
    usage = dict(getattr(resp, "usage", None) or {})
    return {"content": getattr(resp, "content", "") or "",
            "reasoning_tokens": usage.get("reasoning_tokens"),
            "completion_tokens": int(usage.get("completion_tokens") or 0),
            "finish_reason": getattr(resp, "finish_reason", None),
            "duration_s": round(time.monotonic() - started, 2)}


def _skill_names() -> List[str]:
    """Names of the loaded skills — a skill name used like a call in the prose
    is tool syntax. Read from the live manager, never hard-coded (R1)."""
    try:
        from app.core.dependencies import get_skill_manager
        return sorted({getattr(s, "name", "") for s in get_skill_manager().skills if getattr(s, "name", "")})
    except Exception as exc:  # noqa: BLE001 — the check then falls back to tool tags only
        logger.debug("rp_test: no skill names: %s", exc)
        return []


def _clean(text: str) -> str:
    from app.core.chat_engine import clean_response
    return clean_response(text or "")


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------

def _reply(raw: Dict[str, Any], player_line: str) -> Dict[str, Any]:
    return {**raw, "clean": _clean(raw.get("content", "")), "player_line": player_line}


def _cancelled(cancel_event) -> bool:
    return cancel_event is not None and cancel_event.is_set()


def generate_run(case: Dict[str, Any], call: Callable[[List[Dict[str, Any]]], Dict[str, Any]],
                 cancel_event: Optional[threading.Event] = None) -> Dict[str, Any]:
    """One run of one case. A conversation feeds the model's own CLEANED replies
    back (as the game stores them) and hangs the scene state on the latest
    player line only; it stops at a refusal, an empty reply or a cancel."""
    if _cancelled(cancel_event):
        return {"replies": [], "aborted": True}
    messages = [dict(m) for m in case["messages"]]
    replies = [_reply(call(messages), case["incoming"])]
    aborted = False
    moment = case.get("moment", "")
    plain = [dict(m) for m in messages]
    # The history the next turn sees: the first player line without the scene state.
    plain[-1]["content"] = case["incoming"]
    for line in case.get("turns", []):
        last = replies[-1]
        if (last.get("error") or not last["clean"].strip() or metrics.refusal(last["clean"])
                or _cancelled(cancel_event)):
            aborted = True
            break
        plain.append({"role": "assistant", "content": last["clean"]})
        plain.append({"role": "user", "content": line})
        from app.core.chat_engine import attach_moment
        replies.append(_reply(call(attach_moment(plain, moment)), line))
    return {"replies": replies, "aborted": aborted}


REPLY_FLAG_NAMES = ("empty", "truncated", "tool_syntax", "thinking_leak", "name_prefix", "image_markdown",
                    "mood_marker", "language", "salad", "refusal", "cat_speech")


def evaluate_run(case: Dict[str, Any], run: Dict[str, Any], skill_names: List[str],
                 cliches: List[str]) -> None:
    """Code checks per reply, plus the repetition series for the two cases
    that measure it (prior = the character's replies already in the history)."""
    for reply in run["replies"]:
        if reply.get("infra"):
            # A provider outage says nothing about the model (and the run is not saved).
            reply["flags"] = None
        elif reply.get("error"):
            # The model's endpoint REJECTED the request (4xx: context too long,
            # unsupported parameter...) — that is the model's answer: a hard cap.
            reply["flags"] = {**{name: None for name in REPLY_FLAG_NAMES}, "rejected": True,
                              "ends_question": False, "words": None}
        else:
            reply["flags"] = dict(metrics.reply_flags(reply.get("content", ""), reply["clean"], case=case,
                                                      finish_reason=reply.get("finish_reason"),
                                                      skill_names=skill_names), rejected=False)
        reply["cliches"] = metrics.cliche_hits(reply["clean"], cliches)
    if "repetition" in case.get("focus", []):
        prior = [_clean(m["content"]) for m in case["messages"][1:-1] if m["role"] == "assistant"]
        valid = [r for r in run["replies"] if not r.get("error")]
        run["repetition"] = metrics.repetition_series([r["clean"] for r in valid], prior=prior,
                                                      player_lines=[r["player_line"] for r in valid])


# ---------------------------------------------------------------------------
# Judge
# ---------------------------------------------------------------------------

def _transcript(case: Dict[str, Any]) -> List[Dict[str, str]]:
    lines = []
    for message in case["messages"][1:-1]:
        speaker = case["player"] if message["role"] == "user" else case["character"]
        text = _clean(message["content"]) if message["role"] == "assistant" else message["content"]
        lines.append({"speaker": speaker, "text": text})
    if not case.get("turns"):
        lines.append({"speaker": case["player"], "text": case["incoming"]})
    return lines


def judge_prompt(case: Dict[str, Any], run: Dict[str, Any]) -> Tuple[str, str]:
    from app.core.prompt_templates import render_task
    replies = [r for r in run["replies"] if not r.get("error")]
    multi = bool(case.get("turns"))
    if multi:
        answer = "\n".join(f"{case['player']}: {r['player_line']}\n{case['character']} [{i + 1}]: {r['clean']}"
                           for i, r in enumerate(replies))
    else:
        answer = replies[0]["clean"] if replies else ""
    return render_task("rp_judge", character=case["character"], player=case["player"],
                       facts=case.get("facts", []), transcript=_transcript(case), answer=answer,
                       multi=multi, questions=[{"id": c["id"], "question": c["question"]} for c in case["checks"]])


def parse_judge(text: str, ids: List[str]) -> Dict[str, Dict[str, str]]:
    """{"answers": {id: {answer, why}}} → only well-formed yes/no answers of
    the asked ids. Raises JudgeError when nothing usable came back."""
    span = re.search(r"\{[\s\S]*\}", text or "")
    try:
        data = json.loads(span.group(0)) if span else None
    except ValueError:
        data = None
    answers = (data or {}).get("answers") if isinstance(data, dict) else None
    if not isinstance(answers, dict):
        raise JudgeError("judge answer is not the expected JSON")
    out = {}
    for qid in ids:
        item = answers.get(qid)
        if isinstance(item, dict) and str(item.get("answer", "")).strip().lower() in ("yes", "no"):
            out[qid] = {"answer": item["answer"].strip().lower(), "why": str(item.get("why", ""))[:300]}
    if not out:
        raise JudgeError("judge answered none of the questions")
    return out


def ask_judge(call, system: str, user: str, ids: List[str]) -> Dict[str, Dict[str, str]]:
    """One judge request, one retry on an unusable answer or a failed request
    (a 429 from a provider without a configured quota lands here)."""
    last = None
    for attempt in range(2):
        try:
            raw = call([{"role": "system", "content": system}, {"role": "user", "content": user}])
            return parse_judge(raw.get("content", ""), ids)
        except Exception as exc:  # noqa: BLE001 — retried once, then raised
            if exc.__class__.__name__ == "_QuotaWaitCancelled":
                raise
            last = exc
            if not isinstance(exc, JudgeError) and attempt == 0:
                time.sleep(JUDGE_RETRY_S)
    raise last


def calibrate(call, data: Dict[str, Any]) -> Dict[str, Any]:
    """Run the hand-written anchors; the judge must hit >= 90 % of their answers.
    Misses keep only ids and the error CLASS — the result lands in a tracked file."""
    common = {c["id"]: c for c in data.get("common_checks", [])}
    case_checks = {c["id"]: c for case in data["cases"] for c in case["checks"]}
    hits = total = 0
    details = []
    for anchor in data.get("anchors", []):
        character, player = anchor.get("character", ""), anchor.get("player", "")
        questions = []
        for qid in anchor["answers"]:
            check = common.get(qid) or case_checks.get(qid)
            if check is None:
                details.append({"id": anchor["id"], "question": qid, "error": "unknown question"})
                continue
            questions.append({"id": qid, "question": check["question"].replace("{player}", player)
                              .replace("{character}", character)})
        fake = {"character": character, "player": player, "facts": anchor["facts"],
                "messages": [{"role": "system", "content": ""}, {"role": "user", "content": ""}],
                "incoming": anchor["player_line"], "checks": questions}
        system, user = judge_prompt(fake, {"replies": [{"clean": anchor["reply"], "player_line": anchor["player_line"]}]})
        try:
            answers = ask_judge(call, system, user, [q["id"] for q in questions]) if questions else {}
        except Exception as exc:  # noqa: BLE001 — a failed anchor is a miss
            if exc.__class__.__name__ == "_QuotaWaitCancelled":
                raise
            answers = {}
            details.append({"id": anchor["id"], "error": exc.__class__.__name__})
        for qid, expected in anchor["answers"].items():
            total += 1
            got = (answers.get(qid) or {}).get("answer")
            hits += got == expected
            if got != expected:
                details.append({"id": anchor["id"], "question": qid, "expected": expected, "got": got})
    return {"passed": hits, "total": total, "ok": bool(total) and hits / total >= CALIBRATION_MIN,
            "misses": details}


def judge_run(call, case: Dict[str, Any], run: Dict[str, Any],
              cancel_event: Optional[threading.Event] = None) -> None:
    if _cancelled(cancel_event):
        return
    replies = [r for r in run["replies"] if not r.get("error")]
    if not replies:
        run["judge"] = {"answers": {}, "error": "no reply to judge"}
        return
    system, user = judge_prompt(case, run)
    try:
        run["judge"] = {"answers": ask_judge(call, system, user, [c["id"] for c in case["checks"]]), "error": None}
    except Exception as exc:  # noqa: BLE001 — recorded as not judged (sidecar only)
        if exc.__class__.__name__ == "_QuotaWaitCancelled":
            return
        run["judge"] = {"answers": {}, "error": str(exc)[:300]}


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _pct(value: Optional[float]) -> Optional[float]:
    return None if value is None else round(100 * value, 1)


def summarize(model_full: str, data: Dict[str, Any], results: Dict[str, List[Dict[str, Any]]], *,
              settings: Dict[str, Any], calibration: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Scores, findings and per-case evidence from evaluated (and judged) runs."""
    cases = {c["id"]: c for c in data["cases"]}
    judge_ok = bool(calibration and calibration.get("ok"))
    # Judge items: (dimension, passed or None=not judged).
    items: Dict[str, List[Optional[bool]]] = {d: [] for d in DIMENSIONS}
    replies_all = []
    case_out = []
    brief_words, long_words, conv_words = [], [], []
    rep_series, rep_case = [], {}
    findings: List[Dict[str, Any]] = []
    check_fail: Dict[Tuple[str, str], List[int]] = {}
    for cid, runs in results.items():
        case = cases[cid]
        checks = {c["id"]: c for c in case["checks"]}
        tally = {qid: {"pass": 0, "fail": 0, "unjudged": 0} for qid in checks}
        for run in runs:
            answers = (run.get("judge") or {}).get("answers", {}) if judge_ok else {}
            for qid, check in checks.items():
                got = (answers.get(qid) or {}).get("answer")
                passed = None if got is None else got == check["expect"]
                items[check["dimension"]].append(passed)
                tally[qid]["unjudged" if passed is None else "pass" if passed else "fail"] += 1
            for index, reply in enumerate(run["replies"]):
                flags = reply.get("flags")
                if not flags:
                    continue
                replies_all.append(reply)
                if flags.get("cat_speech") is not None:
                    items["character"].append(not flags["cat_speech"])
                if flags.get("words") is None:
                    continue
                # Reply 0 answers `incoming`, reply i answers turns[i - 1];
                # brief_turns index `turns`.
                if case.get("length") == "brief" or (index >= 1 and index - 1 in case.get("brief_turns", [])):
                    brief_words.append(flags["words"])
                if case.get("length") == "long":
                    long_words.append(flags["words"])
                if case.get("turns"):
                    conv_words.append(flags["words"])
            if run.get("repetition"):
                rep_series.extend(run["repetition"])
                rep_case.setdefault(cid, []).extend(run["repetition"])
        for qid, counts in tally.items():
            if counts["fail"]:
                check_fail[(cid, qid)] = [counts["fail"], counts["pass"] + counts["fail"]]
        case_out.append({"id": cid, "label": case["label"], "focus": case["focus"], "runs": len(runs),
                         "checks": {qid: dict(tally[qid], dimension=checks[qid]["dimension"],
                                              expect=checks[qid]["expect"], finding=checks[qid].get("finding", ""))
                                    for qid in checks},
                         "repetition": metrics.repetition_score(rep_case[cid]) if cid in rep_case else None,
                         "aborted_runs": sum(bool(r.get("aborted")) for r in runs),
                         "errors": sum(bool(rep.get("error")) for r in runs for rep in r["replies"])})

    def judged(dimension):
        values = items[dimension]
        answered = [v for v in values if v is not None]
        coverage = len(answered) / len(values) if values else 0.0
        if not values or coverage < JUDGE_COVERAGE:
            return None, f"{sum(answered)}/{len(answered)}", coverage
        return 100 * sum(answered) / len(answered), f"{sum(answered)}/{len(answered)}", coverage

    def flag_rate(name):
        return metrics.rate(r["flags"].get(name) for r in replies_all)

    rates = {name: flag_rate(name) for name in ("tool_syntax", "thinking_leak", "empty", "language", "name_prefix",
                                                 "image_markdown", "truncated", "mood_marker")}
    agency_score, agency_n, agency_cov = judged("discipline")
    rates["player_agency"] = None if agency_score is None else 1 - agency_score / 100
    ratio = metrics.length_ratio(brief_words, long_words)
    dims: Dict[str, Dict[str, Any]] = {}
    # A rate over every scored reply of the repetition cases (design §4a):
    # the long conversations weigh by their replies, not one run each.
    code_rep = metrics.repetition_score(rep_series)
    judge_rep, rep_n, _ = judged("repetition")
    if code_rep is None:
        rep_total = None
    elif judge_rep is None:
        rep_total = code_rep
    else:
        rep_total = 2 / 3 * code_rep + 1 / 3 * judge_rep
    dims["repetition"] = {"score": None if rep_total is None else round(rep_total, 1),
                          "code": None if code_rep is None else round(code_rep, 1),
                          "judge": None if judge_rep is None else round(judge_rep, 1), "n": rep_n}
    for dimension in ("prose", "character", "logic"):
        score, n, coverage = judged(dimension)
        dims[dimension] = {"score": None if score is None else round(score, 1), "n": n,
                           "coverage": round(coverage, 2)}
    dims["discipline"] = {"score": metrics.discipline_score(rates, ratio),
                          "judge_part": agency_score is not None, "n": agency_n,
                          "rates": {k: None if v is None else round(v, 3) for k, v in rates.items()}}
    caps = {name: sum(bool(r["flags"].get(name)) for r in replies_all) for name in CAPS}
    available = [d["score"] for d in dims.values() if d["score"] is not None]
    overall = round(sum(available) / len(available), 1) if available else None
    missing = [name for name, d in dims.items() if d["score"] is None]
    verdict = _verdict(overall, dims, caps, missing)

    # --- findings (English: the admin page has no translation layer) ---
    def add(severity, text):
        findings.append({"severity": severity, "text": text})
    if calibration is not None and not judge_ok:
        add("bad", f"Judge failed calibration ({calibration.get('passed')}/{calibration.get('total')} anchor "
                   "answers) — prose, character and logic were not judged.")
    for name, count in caps.items():
        if count:
            label = {"refusal": "Refused or answered as an assistant", "salad": "Broke into multi-script token salad",
                     "empty": "Gave an empty reply", "language": "Answered in the wrong language",
                     "rejected": "The endpoint rejected the request (e.g. prompt too long)"}[name]
            add("bad", f"{label} in {count} of {len(replies_all)} replies.")
    series = [s for runs in results.values() for run in runs for s in (run.get("repetition") or [])]
    if series:
        rep_count = sum(s["repeat"] for s in series)
        copies = sum(s["full_copy"] for s in series)
        shapes = sum(s["same_shape"] for s in series)
        add("bad" if rep_count / len(series) >= 0.3 else "warn" if rep_count else "good",
            f"Repeats itself in {rep_count} of {len(series)} replies (the game's repetition rule)."
            if rep_count else f"No repetition in {len(series)} replies (the game's repetition rule).")
        if copies:
            add("bad", f"Copied an earlier reply almost verbatim {copies}×.")
        if shapes:
            add("warn", f"Same reply shape as the previous reply in {shapes} of {len(series)} replies.")
    conv = [r for cid, runs in results.items() if cases[cid].get("turns") for run in runs
            for r in run["replies"] if r.get("flags")]
    questions = sum(r["flags"]["ends_question"] for r in conv)
    if conv and questions / len(conv) >= 0.8:
        add("warn", f"Ends {questions} of {len(conv)} conversation replies with a question.")
    if ratio is not None:
        if ratio > metrics.LENGTH_RATIO_LIMIT:
            add("warn", f"Length does not follow the moment: short moments get {ratio:.0%} of the length of "
                        "long ones.")
        else:
            add("good", f"Answers short moments short ({ratio:.0%} of the long replies).")
    flag_text = {"tool_syntax": "Tool syntax in the prose", "thinking_leak": "Reasoning leaked into the reply",
                 "name_prefix": "Speaker label in front of the reply", "image_markdown": "Markdown image syntax",
                 "truncated": "Cut off at the token limit", "mood_marker": "Mood marker missing or malformed"}
    for name, label in flag_text.items():
        count = sum(bool(r["flags"].get(name)) for r in replies_all)
        if count:
            add("bad" if name in ("tool_syntax", "thinking_leak") else "warn",
                f"{label} in {count} of {len(replies_all)} replies.")
    if judge_ok:
        for (cid, qid), (fails, total) in sorted(check_fail.items()):
            check = next(c for c in cases[cid]["checks"] if c["id"] == qid)
            add("bad" if fails * 2 >= total else "warn",
                f"{check.get('finding') or qid} — {cases[cid]['label']}: {fails} of {total} runs.")
    cliche = sorted({c for r in replies_all for c in r.get("cliches", [])})
    if cliche:
        add("warn", "Stock phrases: " + ", ".join(cliche) + ".")

    durations = [r["duration_s"] for r in replies_all if r.get("duration_s")]
    tokens = sum(r.get("completion_tokens") or 0 for r in replies_all)
    words = [r["flags"]["words"] for r in replies_all if r["flags"].get("words") is not None]
    mean_conv = sum(conv_words) / len(conv_words) if conv_words else 0
    spread = (round((sum((w - mean_conv) ** 2 for w in conv_words) / len(conv_words)) ** 0.5 / mean_conv, 2)
              if conv_words and mean_conv else None)
    return {
        "model": model_full, "scorer_version": SCORER_VERSION, "fixture_version": data["fixture_version"],
        "date": utc_now().date().isoformat(), "settings": settings,
        "judge": {**settings["judge"], "calibration": calibration},
        "overall": overall, "verdict": verdict, "dimensions": dims, "caps": caps,
        "length": {"brief_median": median(brief_words) if brief_words else None,
                   "long_median": median(long_words) if long_words else None,
                   "ratio": ratio, "conversation_spread": spread},
        "speed": {"median_latency_s": round(median(durations), 2) if durations else None,
                  "tok_s": round(tokens / sum(durations), 1) if durations and tokens else None,
                  "median_words": median(words) if words else None},
        "findings": findings, "cases": case_out, "replies": len(replies_all),
        "thresholds": {"overall": THRESHOLD_OVERALL, "dimension": THRESHOLD_DIMENSION, "band": BORDERLINE_BAND},
    }


def _verdict(overall, dims, caps, missing) -> str:
    """yes / borderline / no — <reason> / incomplete — <dimension> not judged."""
    capped = [name for name in CAPS if caps.get(name)]
    if capped:
        return "no — " + CAP_LABELS[capped[0]]
    if missing:
        return "incomplete — " + ", ".join(missing) + " not judged"
    weakest = min(dims, key=lambda name: dims[name]["score"])
    low = [name for name, d in dims.items() if d["score"] < THRESHOLD_DIMENSION]
    if not low and overall >= THRESHOLD_OVERALL:
        return "yes"
    near = (all(d["score"] >= THRESHOLD_DIMENSION - BORDERLINE_BAND for d in dims.values())
            and overall >= THRESHOLD_OVERALL - BORDERLINE_BAND)
    return "borderline" if near else "no — " + weakest


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _stored_results(results: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    return {cid: [{"aborted": run.get("aborted", False), "judge": run.get("judge"),
                   "repetition": run.get("repetition"),
                   "replies": [{k: r.get(k) for k in ("content", "clean", "player_line", "finish_reason",
                                                       "duration_s", "completion_tokens", "reasoning_tokens",
                                                       "error", "infra", "flags", "cliches")} for r in run["replies"]]}
                  for run in runs] for cid, runs in results.items()}


def persist(model_full: str, summary: Dict[str, Any], results: Dict[str, List[Dict[str, Any]]],
            *, infra: bool) -> bool:
    """Raw answers to the local sidecar always; the result only without an
    infrastructure error (an outage says nothing about the model)."""
    from app.core.model_capabilities import get_rp_outputs, save_rp_outputs, save_rp_result
    try:
        save_rp_outputs(model_full, {"scorer_version": SCORER_VERSION, "fixture_version": summary["fixture_version"],
                                     "results": _stored_results(results)})
        summary["diagnostic_run_id"] = get_rp_outputs(model_full).get("run_id")
    except Exception as exc:
        logger.error("Failed to persist RP diagnostics for %s: %s", model_full, exc)
        return False
    if infra:
        return False
    try:
        save_rp_result(model_full, summary)
        logger.info("RP test saved for %s: %s (%s)", model_full, summary["overall"], summary["verdict"])
        return True
    except Exception as exc:
        logger.error("Failed to persist RP result for %s: %s", model_full, exc)
        return False


# ---------------------------------------------------------------------------
# Runners (job kinds "rp" and "rp_judge" of the shared test queue)
# ---------------------------------------------------------------------------

def _caller(inst, client, model: str, requested: int, cancel_event):
    limit, quota = _limits(inst, model, requested)
    return limit, (lambda messages: _invoke(client, messages, quota, cancel_event))


def _judge_gate(provider: str, limit: int) -> threading.BoundedSemaphore:
    """One gate per judge provider, shared by every RP job that judges there."""
    with _JUDGE_GATES_LOCK:
        if provider not in _JUDGE_GATES:
            _JUDGE_GATES[provider] = threading.BoundedSemaphore(limit)
        return _JUDGE_GATES[provider]


def _judge_caller(settings, cancel_event, requested):
    """(limit, call) for the judge — temperature 0, no thinking, its provider's
    caps and quota, and the shared per-provider gate."""
    from app.core.llm_router import create_llm_instance
    inst = create_llm_instance("rp_judge", judge_key(settings), use_routing=False)
    if inst is None or not inst.available:
        raise JudgeError(f"judge {judge_key(settings)} is not available")
    client = inst.create_llm(temperature=0, thinking=False, max_tokens=JUDGE_MAX_TOKENS)
    limit, call = _caller(inst, client, settings["judge"]["model"], requested, cancel_event)
    gate = _judge_gate(settings["judge"]["provider"], limit)

    def gated(messages):
        with gate:
            return call(messages)
    return limit, gated


def _prepare_judge(settings, cancel_event, requested) -> Iterator[Dict[str, Any]]:
    """Build the judge and run its calibration. Ends with {"type": "judge",
    "call", "limit", "calibration"} or {"type": "error"} when the judge is
    unreachable (nothing to judge with — say so before any work is done)."""
    try:
        limit, call = _judge_caller(settings, cancel_event, requested)
    except Exception as exc:  # noqa: BLE001
        yield {"type": "error", "message": f"Judge not usable: {exc}"}
        return
    yield {"type": "progress", "phase": "calibrating the judge"}
    try:
        calibration = calibrate(call, load_rp_cases())
    except Exception as exc:  # noqa: BLE001 — includes a cancel during the quota wait
        if _cancelled(cancel_event):
            return
        calibration = {"passed": 0, "total": 0, "ok": False, "misses": [{"error": exc.__class__.__name__}]}
    yield {"type": "judge", "call": call, "limit": limit, "calibration": calibration}


def _judge_runs(call, limit, data, results, cancel_event) -> Iterator[Dict[str, Any]]:
    """Judge every run; yields progress, stops early on cancel."""
    cases = {c["id"]: c for c in data["cases"]}
    jobs = [(cid, run) for cid, runs in results.items() for run in runs]
    with ThreadPoolExecutor(max_workers=limit) as pool:
        futures = [pool.submit(judge_run, call, cases[cid], run, cancel_event) for cid, run in jobs]
        for index, future in enumerate(futures):
            future.result()
            if _cancelled(cancel_event):
                pool.shutdown(wait=False, cancel_futures=True)
                return
            yield {"type": "progress", "phase": f"judging {index + 1}/{len(futures)}"}


def _take_judge(events, sink: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
    """Pass progress/error events through; keep the final judge event."""
    for event in events:
        if event["type"] == "judge":
            sink.update(event)
        else:
            yield event


def iter_rp_results(model_full: str, *, settings: dict, cancel_event: Optional[threading.Event] = None,
                    concurrency: int = 3) -> Iterator[Dict[str, Any]]:
    """Calibrate the judge, generate, measure, judge, save. Events as in
    model_suitability: start / progress / check / done / error."""
    from app.core.llm_router import create_llm_instance
    from app.core.model_suitability import _QuotaWaitCancelled, _rejected_by_model
    settings = validate_rp_settings(settings)
    if judge_key(settings).lower() == model_full.lower():
        yield {"type": "error", "message": "The judge must be a different model than the one under test"}
        return
    data = load_rp_cases()
    inst = create_llm_instance("rp_test", model_full, use_routing=False)
    if inst is None:
        yield {"type": "error", "message": f"No provider found for model '{model_full}'"}
        return
    if not inst.available:
        yield {"type": "error", "message": f"Provider '{inst.provider_name}' is not available"}
        return
    cases = data["cases"]
    yield {"type": "start", "model": model_full, "total": len(cases)}
    judge: Dict[str, Any] = {}
    for event in _take_judge(_prepare_judge(settings, cancel_event, concurrency), judge):
        yield event
        if event["type"] == "error":
            return
    if not judge or _cancelled(cancel_event):
        return
    budget = settings["thinking_budget"]
    client = inst.create_llm(
        temperature=settings["temperature"], top_p=settings["top_p"], max_tokens=settings["max_tokens"] or None,
        repetition_penalty=settings["repetition_penalty"], chat_template=settings["chat_template"],
        extra_params=settings["extra_params"], thinking=bool(budget), thinking_budget=budget or None)
    limit, call = _caller(inst, client, model_full.partition("::")[2], concurrency, cancel_event)
    infra = threading.Event()

    def safe_call(messages):
        try:
            return call(messages)
        except _QuotaWaitCancelled:
            raise
        except Exception as exc:  # noqa: BLE001 — sorted below
            outage = not _rejected_by_model(exc)
            if outage:
                infra.set()
            return {"content": "", "error": str(exc)[:300], "infra": outage, "duration_s": 0,
                    "finish_reason": None}

    skill_names = _skill_names()
    results: Dict[str, List[Dict[str, Any]]] = {}
    with ThreadPoolExecutor(max_workers=limit) as pool:
        pending = [(case, [pool.submit(generate_run, case, safe_call, cancel_event) for _ in range(case["repeats"])])
                   for case in cases]
        for index, (case, futures) in enumerate(pending):
            runs = []
            for future in futures:
                try:
                    runs.append(future.result())
                except _QuotaWaitCancelled:
                    pool.shutdown(wait=False, cancel_futures=True)
                    return
            if _cancelled(cancel_event):
                pool.shutdown(wait=False, cancel_futures=True)
                return
            for run in runs:
                evaluate_run(case, run, skill_names, data.get("cliches", []))
            results[case["id"]] = runs
            yield {"type": "progress", "done": index + 1, "phase": f"generated {case['label']}"}
            yield {"type": "check", "id": case["id"], "label": case["label"], "focus": case["focus"],
                   "runs": _stored_results({case["id"]: runs})[case["id"]]}
    calibration = judge["calibration"]
    if calibration["ok"]:
        yield from _judge_runs(judge["call"], judge["limit"], data, results, cancel_event)
    if _cancelled(cancel_event):
        return
    from app.core.model_suitability import _JOBS_LOCK
    with _JOBS_LOCK:
        if _cancelled(cancel_event):
            return
        summary = summarize(model_full, data, results, settings=settings, calibration=calibration)
        summary["infra"] = infra.is_set()
        summary["saved"] = persist(model_full, summary, results, infra=infra.is_set())
        yield {"type": "done", "summary": summary}


def iter_rp_judge(model_full: str, *, settings: dict, cancel_event: Optional[threading.Event] = None,
                  concurrency: int = 3) -> Iterator[Dict[str, Any]]:
    """Judge the stored answers of the last RP run again (new judge, or the
    judge was down) — no new answers are generated. A judge that is down or
    fails its calibration changes nothing: the stored result stays."""
    from app.core.model_capabilities import get_all_rp_results, get_rp_outputs
    settings = validate_rp_judge_settings(settings)
    record = get_all_rp_results().get(model_full.lower())
    raw = get_rp_outputs(model_full, (record or {}).get("diagnostic_run_id") or "")
    data = load_rp_cases()
    if not record or not raw.get("results"):
        yield {"type": "error", "message": "No stored RP answers for this model — run the test first"}
        return
    if raw.get("fixture_version") != data["fixture_version"]:
        yield {"type": "error", "message": "The RP test cases changed since this run — run the test again"}
        return
    if judge_key(settings).lower() == model_full.lower():
        yield {"type": "error", "message": "The judge must be a different model than the one under test"}
        return
    results = raw["results"]
    for runs in results.values():
        for run in runs:
            run.pop("judge", None)
    yield {"type": "start", "model": model_full, "total": len(results)}
    judge: Dict[str, Any] = {}
    for event in _take_judge(_prepare_judge(settings, cancel_event, concurrency), judge):
        yield event
        if event["type"] == "error":
            return
    if not judge or _cancelled(cancel_event):
        return
    calibration = judge["calibration"]
    if not calibration["ok"]:
        yield {"type": "error", "message": f"The judge failed its calibration ({calibration['passed']}/"
                                           f"{calibration['total']} anchor answers) — the stored result is kept"}
        return
    yield from _judge_runs(judge["call"], judge["limit"], data, results, cancel_event)
    if _cancelled(cancel_event):
        return
    from app.core.model_suitability import _JOBS_LOCK
    with _JOBS_LOCK:
        if _cancelled(cancel_event):
            return
        run_settings = {**record["settings"], "judge": settings["judge"]}
        summary = summarize(model_full, data, results, settings=run_settings, calibration=calibration)
        summary["date"] = record.get("date", summary["date"])
        summary["rejudged"] = utc_now().date().isoformat()
        summary["infra"] = False
        summary["saved"] = persist(model_full, summary, results, infra=False)
        yield {"type": "done", "summary": summary}
