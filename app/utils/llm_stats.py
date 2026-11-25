"""LLM call statistics for duration estimates.

Keeps a rolling window of calls per `(model, task)` in the world-DB table
`llm_call_stats` and estimates the expected duration of new calls from
their input tokens.

Estimate:
    est_dur = median(duration) * (current_in / median(in))
With a hierarchical fallback (model,task) -> (model,*) -> None.
"""
from datetime import datetime

from app.core.timeutils import utc_now_iso
from statistics import median
from typing import Dict, Optional

from app.core.db import get_connection, transaction
from app.core.log import get_logger

logger = get_logger("llm_stats")

# Maximum number of calls kept per (model, task, provider) bucket. High enough
# for admin evaluations over longer periods. RETENTION only — it is the limit
# of the DELETE in record_call and must not be used as a read limit.
_BUCKET_LIMIT = 5000
# How many of the most recent calls the estimator reads per bucket. The median
# and the p90 of a remaining-time display need the recent behaviour of the
# model, not weeks-old hardware states — and reading the full retention window
# meant up to 3 x 5000 rows plus three Python sorts BEFORE every single LLM
# call (the estimate runs per task start and per chat registration).
_READ_WINDOW = 200
# Minimum samples for the primary bucket to be used (otherwise fallback).
_MIN_TASK_SAMPLES = 5
# How long a stats insert waits for the world.db write lock (the connection's
# busy_timeout is 5000 ms). A statistics row is not worth holding the finished
# LLM call's thread: past this wait the row is dropped with a warning.
_STATS_BUSY_TIMEOUT_MS = 250


def record_call(model: str, task: str, provider: str,
                in_tokens: int, out_tokens: int, duration_s: float,
                agent_name: str = "", max_tokens: int = 0) -> None:
    """Write one finished LLM call into the statistics table.

    Broken / incomplete records are skipped. After the insert the bucket is
    capped at `_BUCKET_LIMIT` entries per `(model, task, provider)` — the
    same model name on other hardware runs at another speed and therefore
    gets its own bucket. Waits at most `_STATS_BUSY_TIMEOUT_MS` for the write
    lock (set on this thread's own connection for this one write, restored
    afterwards); a busy database drops the row, never fails the caller.
    """
    if not model or not task:
        return
    if in_tokens <= 0 or out_tokens <= 0 or duration_s <= 0:
        return

    prov = provider or ""
    agent = agent_name or ""
    mt = int(max_tokens) if max_tokens else 0
    own = get_connection()
    previous = int(own.execute("PRAGMA busy_timeout").fetchone()[0])
    own.execute(f"PRAGMA busy_timeout={int(_STATS_BUSY_TIMEOUT_MS)}")
    try:
        with transaction() as conn:
            conn.execute(
                "INSERT INTO llm_call_stats "
                "(ts, model, task, provider, agent_name, "
                " in_tokens, out_tokens, max_tokens, duration_s) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (utc_now_iso(),
                 model, task, prov, agent,
                 int(in_tokens), int(out_tokens), mt, float(duration_s)))
            conn.execute(
                "DELETE FROM llm_call_stats WHERE id IN ("
                "  SELECT id FROM llm_call_stats "
                "   WHERE model = ? AND task = ? AND provider = ? "
                "   ORDER BY ts DESC LIMIT -1 OFFSET ?"
                ")",
                (model, task, prov, _BUCKET_LIMIT))
    except Exception as e:
        logger.warning("LLM stats insert failed: %s", e)
    finally:
        own.execute(f"PRAGMA busy_timeout={previous}")


def estimate_duration(model: str, task: str, provider: str = "",
                      in_tokens: int = 0) -> Optional[Dict]:
    """Estimate the duration of an LLM call from historical data.

    Args:
        model: model name
        task: task_type (e.g. "thought", "extraction")
        provider: provider/channel name. Matters because the same model runs
            at a different speed on other hardware. Empty = any provider
            (used only as the last fallback).
        in_tokens: current input tokens. 0 = unknown, then the plain median.

    Returns:
        dict with `est_duration_s`, `p90_duration_s`, `est_out_tokens`,
        `samples`, `source` ("task" | "model"), or None when nothing
        comparable is recorded.
    """
    if not model:
        return None

    # Hierarchical fallback:
    # 1. (model, task, provider) — exact
    # 2. (model, *,    provider) — another task on the same hardware
    # 3. (model, task, *)        — the same task on other hardware
    prov_filter = provider if provider else None
    rows = _fetch_bucket(model, task, prov_filter)
    source = "task"
    if len(rows) < _MIN_TASK_SAMPLES and prov_filter is not None:
        rows = _fetch_bucket(model, None, prov_filter)
        source = "model"
    if len(rows) < _MIN_TASK_SAMPLES:
        rows = _fetch_bucket(model, task, None)
        source = "task_any_provider"
    if not rows:
        return None

    durs = [r[2] for r in rows]
    ins  = [r[0] for r in rows if r[0] > 0]
    outs = [r[1] for r in rows]

    med_dur = median(durs)
    med_in  = median(ins) if ins else 0
    med_out = int(median(outs)) if outs else 0

    if med_in > 0 and in_tokens > 0:
        # Linear scaling with the input — capped for extreme outliers
        ratio = max(0.3, min(3.0, in_tokens / med_in))
        est_dur = med_dur * ratio
    else:
        est_dur = med_dur

    sorted_durs = sorted(durs)
    p90_idx = max(0, int(len(sorted_durs) * 0.9) - 1)
    p90 = sorted_durs[min(p90_idx, len(sorted_durs) - 1)]

    return {
        "est_duration_s": round(est_dur, 2),
        "p90_duration_s": round(p90, 2),
        "est_out_tokens": med_out,
        "samples": len(rows),
        "source": source,
    }


def _fetch_bucket(model: str, task: Optional[str], provider: Optional[str]):
    """The latest entries of one bucket.

    `task=None` or `provider=None` means "any" (no WHERE filter). At most
    `_READ_WINDOW` rows are read (newest first). Returns a list of
    (in_tokens, out_tokens, duration_s).
    """
    conn = get_connection()
    where = ["model = ?"]
    params: list = [model]
    if task is not None:
        where.append("task = ?")
        params.append(task)
    if provider is not None:
        where.append("provider = ?")
        params.append(provider)
    params.append(_READ_WINDOW)
    sql = (
        "SELECT in_tokens, out_tokens, duration_s "
        "FROM llm_call_stats "
        f"WHERE {' AND '.join(where)} "
        "ORDER BY ts DESC LIMIT ?"
    )
    cur = conn.execute(sql, params)
    return [(r[0], r[1], r[2]) for r in cur.fetchall()]
