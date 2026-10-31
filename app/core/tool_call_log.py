"""Best-effort structured outcomes for tool executions and discarded turns."""
import json
import re
import threading
from pathlib import Path
from typing import Any

from app.core.log import get_logger
from app.core.timeutils import utc_now_iso

LIVE_LOG_FILE = Path('./logs/tool_calls.jsonl')
LOG_FILE: Path | None = None
STATUSES = ('ok', 'error', 'blocked', 'unknown_tool', 'suppressed', 'exception', 'discarded')
logger = get_logger('tool_call_log')
_lock = threading.Lock()


def configure(path: Path | None) -> None:
    """Select the output at runtime; None disables recording."""
    global LOG_FILE
    with _lock:
        LOG_FILE = path


def classify(result: Any) -> str:
    """Classify without changing the execution boundary's error policy."""
    if isinstance(result, str):
        first_line = result[:300].split('\n', 1)[0]
        if re.search(r'\bnot found\b|^cannot\b|^you cannot\b|\bstill on\b.*\bcooldown\b|'
                     r'nicht im inventar|\bnot_equipped\b', first_line, re.IGNORECASE):
            return 'error'
    try:
        from app.core.streaming import is_error_result
        if is_error_result(result):
            return 'error'
        if isinstance(result, dict) and (
                result.get('success') is False or result.get('ok') is False
                or result.get('error') or result.get('status') in ('refused', 'failed', 'error')):
            return 'error'
    except Exception:
        pass
    return 'ok'


def _text(value: Any, limit: int) -> str:
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, default=str)
    return str(value)[:limit]


def record(*, character: str, tool: str, status: str, tool_input: Any = '',
           result: Any = '', source: str = '', duration_ms: float | None = None) -> None:
    """Append one row; malformed inputs or unavailable storage never escape."""
    if LOG_FILE is None:
        return
    try:
        from app.core.turn_trace import current_trace
        from app.core.timeutils import game_time
        trace = current_trace() or {}
        try:
            game_ts = game_time().canonical()
        except Exception:
            game_ts = ''
        row = dict(starttime=utc_now_iso(), game_ts=game_ts,
                   trace_id=trace.get('id', ''), trace_kind=trace.get('kind', ''),
                   character=character, tool=tool, status=status,
                   source=source or trace.get('kind', ''),
                   input=_text(tool_input, 2000), result=_text(result, 1000),
                   duration_ms=round(duration_ms) if duration_ms is not None else None)
        line = json.dumps(row, ensure_ascii=False)
        with _lock:
            if LOG_FILE is None:
                return
            LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            with LOG_FILE.open('a', encoding='utf-8') as stream:
                stream.write(line + '\n')
    except Exception:
        try:
            logger.debug('tool call log write failed', exc_info=True)
        except Exception:
            pass
