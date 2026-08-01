"""Central LLM call logging — writes every LLM call as JSONL to logs/llm_calls.jsonl.

Each entry holds: start/end timestamp, task, model, character, user, prompt, response,
duration, token usage (real or estimated), max context length. Calls made inside an
active turn trace additionally carry ``trace_id``/``trace_kind`` so the log viewer can
group all calls of one action.
"""
import json
import os
import re
import threading
from datetime import timedelta

from app.core.timeutils import utc_now
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.core.log import get_logger

logger = get_logger("llm_log")

LOG_DIR = Path("./logs")
LOG_FILE = LOG_DIR / "llm_calls.jsonl"
# Pruned entries are appended here, bucketed by their own month:
# logs/archive/<stem>_<YYYY-MM>.jsonl. Same directory start.sh uses for the
# rotated main_*.log / client3d_*.log — different naming scheme, no overlap.
ARCHIVE_DIR = LOG_DIR / "archive"
_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
_lock = threading.Lock()


def _template_basename(template_path: str, fallback_task: str) -> str:
    """Strips path and ``.md`` suffix from the template path.

    Example: ``shared/templates/llm/tasks/classify_activity.md`` →
    ``classify_activity``. Also accepts plain basenames or the sub-path
    form (``tasks/classify_activity.md``). Falls back to the task name
    when no template was passed.
    """
    if not template_path:
        return fallback_task or ""
    name = template_path.replace("\\", "/").rsplit("/", 1)[-1]
    if name.endswith(".md"):
        name = name[:-3]
    return name or fallback_task or ""


def log_llm_call(
    task: str,
    model: str,
    agent_name: str = "", provider: str = "",
    system_prompt: str = "",
    user_input: str = "",
    response: str = "",
    duration_s: float = 0.0,
    tokens_input: int = 0,
    tokens_output: int = 0,
    max_tokens: int = 0,
    messages: Optional[List[Dict[str, str]]] = None,
    error: str = "",
    llm_role: str = "",
    template: str = "",
    label: str = "",
    trace_id: str = "",
    trace_kind: str = ""):
    """Logs an LLM call as a JSONL line and prints a short line to stdout.

    Args:
        task: kind of call (chat_stream, image_prompt, extraction, etc.)
        model: model name (e.g. mistral:latest)
        agent_name: character name
        provider: provider name (e.g. OllamaLocal, OpenAI-API)
        system_prompt: system prompt text
        user_input: user/human message
        response: LLM answer
        duration_s: duration in seconds
        tokens_input: input tokens (real or estimated)
        tokens_output: output tokens (real or estimated)
        max_tokens: max tokens / context length
        messages: optional full message list for multi-message calls
        llm_role: role of the LLM call (Tool-LLM, Chat-LLM, LLM)
        template: full path or file name of the rendered Jinja template
            (e.g. ``shared/templates/llm/tasks/classify_activity.md``).
            Reduced to the basename without ``.md`` and shown as the third
            badge in the log viewer — it makes debugging easier because one
            sees immediately which template file was rendered. On an empty
            value the logger falls back to ``task``.
        label: caller detail of the call (e.g. ``compose:room_model``) — the
            caller passes it to ``llm_call``, here it lands in the JSONL so a
            call in the log can be attributed to its source.
        trace_id: correlation id of the action this call belongs to. Empty
            means "look it up yourself": the logger then reads the ambient
            turn trace (``turn_trace.current_trace()``), so call sites inside
            an action need no change at all. Only call sites that cross a
            context boundary (the queue worker thread) pass it explicitly.
        trace_kind: kind of the action (``respond``, ``thought``, ``chat``,
            ...), same fallback as ``trace_id``. The fallback fills each field
            on its own, so an explicit value always wins per field.
    """
    if not trace_id or not trace_kind:
        try:
            from app.core.turn_trace import current_trace
            _t = current_trace()
            if _t:
                trace_id = trace_id or _t.get("id", "")
                trace_kind = trace_kind or _t.get("kind", "")
        except Exception:
            pass
    template_basename = _template_basename(template, task)
    end_time = utc_now()
    start_time = end_time - timedelta(seconds=duration_s)
    entry: Dict[str, Any] = {
        "starttime": start_time.isoformat(timespec="seconds"),
        "endtime": end_time.isoformat(timespec="seconds"),
        "task": task,
        "template": template_basename,
        "llm_role": llm_role or task,
        "provider": provider,
        "model": model,
        "service": agent_name,
        "user_id": "",
        "duration_s": round(duration_s, 2),
        "tokens": {
            "input": tokens_input,
            "output": tokens_output,
            "max": max_tokens,
        },
        "prompt": {},
        "response": response,
    }

    if label:
        entry["label"] = label
    if trace_id:
        entry["trace_id"] = trace_id
    if trace_kind:
        entry["trace_kind"] = trace_kind
    if error:
        entry["error"] = error

    # Build prompt
    if system_prompt:
        entry["prompt"]["system"] = system_prompt
    if user_input:
        entry["prompt"]["user"] = user_input
    if messages:
        entry["prompt"]["messages"] = messages

    # Write JSONL
    with _lock:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # Short line for structured logging
    tok_str = ""
    if tokens_input or tokens_output:
        tok_str = " | %d\u2192%d tok" % (tokens_input, tokens_output)
    prov_str = "%s/" % provider if provider else ""
    role_str = "[%s] " % llm_role if llm_role else ""
    if error:
        logger.error(
            "%s%s | %s | %s%s | %.2fs%s | %s",
            role_str, task, agent_name or "-", prov_str, model, duration_s, tok_str, error[:200])
    else:
        logger.info(
            "%s%s | %s | %s%s | %.2fs%s",
            role_str, task, agent_name or "-", prov_str, model, duration_s, tok_str)

    if not error and tokens_input > 0 and tokens_output > 0 and duration_s > 0:
        try:
            from app.utils.llm_stats import record_call
            record_call(model, task, provider, tokens_input, tokens_output, duration_s,
                        agent_name=agent_name, max_tokens=max_tokens)
        except Exception as e:
            logger.warning("llm_stats.record_call fehlgeschlagen: %s", e)


def extract_token_info(response) -> Dict[str, int]:
    """Extracts token info from an LLM response.

    Supports LLMResponse.usage (dict with prompt_tokens/completion_tokens).
    """
    info = {"input_tokens": 0, "output_tokens": 0}

    usage = getattr(response, "usage", None)
    if usage and isinstance(usage, dict):
        info["input_tokens"] = usage.get("prompt_tokens", 0) or usage.get("input_tokens", 0)
        info["output_tokens"] = usage.get("completion_tokens", 0) or usage.get("output_tokens", 0)

    return info


def estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 characters per token."""
    return len(text) // 4


def get_model_name(llm) -> str:
    """Extracts the model name from an LLMClient."""
    return (
        getattr(llm, "model_name", "")
        or getattr(llm, "model", "")
        or "unknown"
    )


def get_max_tokens(llm) -> int:
    """Extracts max_tokens from an LLMClient."""
    val = getattr(llm, "max_tokens", None)
    return int(val) if val else 0


def _archive_pruned_lines(path: Path, buckets: Dict[str, List[str]]) -> None:
    """Appends the pruned lines to their monthly archive buckets.

    ``buckets`` maps ``YYYY-MM`` → the raw JSONL lines of that month. Each
    bucket is appended verbatim to ``<archive>/<stem>_<YYYY-MM>.jsonl``, where
    ``<archive>`` is the ``archive`` sub-directory next to the pruned log
    (``logs/archive`` for the production logs) and ``<stem>`` the log's file
    name without suffix (``llm_calls``, ``image_prompts``).

    Appending across several buckets is not atomic, so a failure rolls every
    file touched in this call back to the size it had before — a retry on the
    next startup must not duplicate entries.

    Raises on any I/O failure; the caller then leaves the live log untouched.
    """
    archive_dir = path.parent / ARCHIVE_DIR.name
    archive_dir.mkdir(parents=True, exist_ok=True)
    # (file, size before this call) for the rollback — only files that were
    # actually opened for appending land here.
    touched: List[Tuple[Path, int]] = []
    try:
        for month in sorted(buckets):
            target = archive_dir / ("%s_%s.jsonl" % (path.stem, month))
            size_before = target.stat().st_size if target.exists() else 0
            with open(target, "a", encoding="utf-8") as f:
                touched.append((target, size_before))
                for ln in buckets[month]:
                    f.write(ln + "\n")
                f.flush()
                os.fsync(f.fileno())
    except Exception:
        for target, size in touched:
            try:
                with open(target, "r+b") as f:
                    f.truncate(size)
            except Exception as rollback_err:
                logger.warning("Archive rollback for %s failed: %s", target, rollback_err)
        raise


def prune_jsonl_log(path: Path, retention_days: int) -> int:
    """Moves JSONL entries whose ``starttime`` is older than ``retention_days``
    days out of the live log and into a monthly archive. The shortened live
    file is rewritten atomically (tmp + rename).

    Both logs (llm_calls.jsonl, image_prompts.jsonl) carry ``starttime``
    as an ISO string — same schema assumption. Entries without a starttime,
    with an unparsable line or with a ``starttime`` that does not start with
    ``YYYY-MM`` are kept conservatively (no usable timestamp = cannot age out)
    and therefore never end up in the archive.

    Archive layout: one file per log and calendar month,
    ``logs/archive/<stem>_<YYYY-MM>.jsonl`` (e.g.
    ``logs/archive/llm_calls_2026-07.jsonl``). The month comes from the entry
    itself, not from the current time, so entries land in the right bucket even
    when the server has not run for a long while. Buckets are only ever
    appended to.

    Order matters: the archive is written BEFORE the live file is replaced. If
    archiving fails, the live file stays untouched and the function returns 0 —
    an over-long log is preferable to lost data.

    Returns: number of entries removed from the live file — normally identical
    to the number of entries appended to the archive. 0 when there is nothing to
    do and 0 as well on every failure. Note the one case where the two numbers
    differ: if archiving succeeded but rewriting the live file failed, the
    entries are already in the archive while the live file still holds them, so
    the return value is 0 although entries were archived. That is deliberate —
    the return value states what left the live file — and it is logged as its
    own warning, because the next startup will archive those entries a second
    time.
    """
    if retention_days < 1:
        return 0
    if not path.exists():
        return 0
    cutoff = utc_now() - timedelta(days=retention_days)
    cutoff_iso = cutoff.isoformat()

    kept: List[str] = []
    buckets: Dict[str, List[str]] = {}
    removed = 0
    with _lock:
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line_strip = line.strip()
                    if not line_strip:
                        continue
                    try:
                        obj = json.loads(line_strip)
                    except Exception:
                        # keep an unparsable line rather than dropping it
                        kept.append(line_strip)
                        continue
                    ts = (obj.get("starttime") or "").strip()
                    month = ts[:7]
                    if ts and ts < cutoff_iso and _MONTH_RE.match(month):
                        buckets.setdefault(month, []).append(line_strip)
                        removed += 1
                        continue
                    kept.append(line_strip)
        except Exception as e:
            logger.warning("Log cleanup for %s failed while reading: %s", path, e)
            return 0

        if not removed:
            return 0

        try:
            _archive_pruned_lines(path, buckets)
        except Exception as e:
            logger.warning(
                "Log archiving for %s failed (%s) — live file kept unchanged, "
                "%d entries not removed", path, e, removed)
            return 0

        try:
            tmp = path.with_suffix(path.suffix + ".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                for ln in kept:
                    f.write(ln + "\n")
            tmp.replace(path)
        except Exception as e:
            # Nothing is lost — the entries are already in the archive — but the
            # live file still holds them, so the next startup will archive the
            # same entries again. Say so explicitly: this is the only path that
            # produces duplicates, and the operator has to be able to tell it
            # apart from the read failure above.
            logger.warning(
                "Log cleanup for %s failed while replacing the live file (%s) — "
                "%d entries are ALREADY archived in %s but still in the live "
                "file; the next startup will archive them a second time",
                path, e, removed, ", ".join(sorted(buckets)))
            return 0

        logger.info("Log cleanup %s: %d old entries archived (>%d days) in %s",
                    path.name, removed, retention_days,
                    ", ".join(sorted(buckets)))
    return removed


def prune_logs_on_startup() -> Dict[str, int]:
    """Called by the server lifespan at startup. Reads the retention period
    from the config (server.log_retention_days, default 5) and trims
    llm_calls.jsonl + image_prompts.jsonl to that window.

    Entries falling out of the window are not dropped but appended to their
    monthly bucket under ``logs/archive/`` (see ``prune_jsonl_log``). The
    returned dict names the counts per log plus ``archived`` as their sum, so
    the lifespan log line can state how many entries were moved. ``archived``
    counts entries that left the live file; a failure after a successful
    archive write reports 0 for that log even though its entries reached the
    archive — that case has its own warning in ``prune_jsonl_log``.
    """
    try:
        from app.core import config as _cfg
        days = int(_cfg.get("server.log_retention_days") or 5)
    except Exception:
        days = 5
    llm_calls = prune_jsonl_log(LOG_FILE, days)
    image_prompts = prune_jsonl_log(LOG_DIR / "image_prompts.jsonl", days)
    out = {
        "llm_calls": llm_calls,
        "image_prompts": image_prompts,
        "archived": llm_calls + image_prompts,
        "retention_days": days,
    }
    return out
