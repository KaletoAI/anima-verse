"""Central LLM call logging — writes every LLM call as JSONL to logs/llm_calls.jsonl.

Each entry holds: start/end timestamp, task, model, character, user, prompt, response,
duration, token usage (real or estimated), max context length. Calls made inside an
active turn trace additionally carry ``trace_id``/``trace_kind`` so the log viewer can
group all calls of one action.
"""
import json
import threading
from datetime import datetime, timedelta

from app.core.timeutils import utc_now
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.log import get_logger

logger = get_logger("llm_log")

LOG_DIR = Path("./logs")
LOG_FILE = LOG_DIR / "llm_calls.jsonl"
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
        task: kind of call (chat_stream, image_prompt, social_reaction, etc.)
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


def prune_jsonl_log(path: Path, retention_days: int) -> int:
    """Removes JSONL entries whose ``starttime`` is older than
    ``retention_days`` days. Rewrites the file atomically (tmp + rename).

    Both logs (llm_calls.jsonl, image_prompts.jsonl) carry ``starttime``
    as an ISO string — same schema assumption. Entries without a starttime
    are kept conservatively (no timestamp = cannot age out).

    Returns: number of removed entries (0 when there is nothing to do).
    """
    if retention_days < 1:
        return 0
    if not path.exists():
        return 0
    cutoff = utc_now() - timedelta(days=retention_days)
    cutoff_iso = cutoff.isoformat()

    kept: List[str] = []
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
                    if ts and ts < cutoff_iso:
                        removed += 1
                        continue
                    kept.append(line_strip)
            if removed:
                tmp = path.with_suffix(path.suffix + ".tmp")
                with open(tmp, "w", encoding="utf-8") as f:
                    for ln in kept:
                        f.write(ln + "\n")
                tmp.replace(path)
                logger.info("Log-Cleanup %s: %d alte Eintraege entfernt (>%d Tage)",
                            path.name, removed, retention_days)
        except Exception as e:
            logger.warning("Log-Cleanup fuer %s fehlgeschlagen: %s", path, e)
            return 0
    return removed


def prune_logs_on_startup() -> Dict[str, int]:
    """Called by the server lifespan at startup. Reads the retention period
    from the config (server.log_retention_days, default 5) and trims
    llm_calls.jsonl + image_prompts.jsonl to that window.
    """
    try:
        from app.core import config as _cfg
        days = int(_cfg.get("server.log_retention_days") or 5)
    except Exception:
        days = 5
    out = {
        "llm_calls": prune_jsonl_log(LOG_FILE, days),
        "image_prompts": prune_jsonl_log(LOG_DIR / "image_prompts.jsonl", days),
        "retention_days": days,
    }
    return out
