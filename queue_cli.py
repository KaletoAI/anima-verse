#!/usr/bin/env python3
"""Queue CLI — Inspect and manage the persistent TaskQueue via SQLite.

Works WITHOUT the server running — reads the same SQLite DB directly.

Usage:
    python queue_cli.py list                          # pending tasks (all queues)
    python queue_cli.py list -q GamingPC              # filter by queue
    python queue_cli.py list -s failed                # filter by status
    python queue_cli.py list -s all                   # all statuses
    python queue_cli.py info <task_id>                # full task details
    python queue_cli.py cancel <task_id>              # cancel pending task
    python queue_cli.py retry <task_id>               # retry failed/cancelled task
    python queue_cli.py move <task_id> <queue>        # move to different queue
    python queue_cli.py priority <task_id> <int>      # change priority (lower = higher)
    python queue_cli.py pause <queue>                 # pause a queue
    python queue_cli.py resume <queue>                # resume a queue
    python queue_cli.py clear                         # delete old completed/failed (>24h)
    python queue_cli.py clear --hours 1               # delete older than 1h
    python queue_cli.py clear --status failed         # delete only failed
    python queue_cli.py stats                         # queue statistics

Which database?  There is no default world (app/core/paths.py raises rather
than opening the tracked demo world), so point this CLI at one:
    TASK_QUEUE_DB=<file>          in the legacy root .env, or
    STORAGE_DIR=./worlds/<name>   in the environment  ->  <that>/task_queue.db
Without either it exits with that message instead of guessing.
"""
import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path


# ---------------------------------------------------------------------------
# Resolve the queue DB (minimal — no dependencies, no app import)
# ---------------------------------------------------------------------------
NO_DB = ("no task queue database selected — set TASK_QUEUE_DB in the root .env "
         "or point STORAGE_DIR at a world (e.g. STORAGE_DIR=./worlds/demo)")


def _resolve_db_path():
    """TASK_QUEUE_DB from the legacy root .env, else ``$STORAGE_DIR/task_queue.db``.

    No fallback: a guessed path used to mean the tracked demo world, so an
    unselected world is an error message, not a silent default.
    """
    env_path = Path(__file__).resolve().parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("TASK_QUEUE_DB="):
                val = line.split("=", 1)[1].strip().strip('"').strip("'")
                if val:
                    return Path(val)
    storage = os.environ.get("STORAGE_DIR", "").strip()
    if storage:
        return Path(storage) / "task_queue.db"
    return None


DB_PATH = _resolve_db_path()


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------
def _connect() -> sqlite3.Connection:
    if DB_PATH is None:
        print(f"ERROR: {NO_DB}", file=sys.stderr)
        sys.exit(1)
    if not DB_PATH.exists():
        print(f"ERROR: database not found: {DB_PATH}", file=sys.stderr)
        print("Start the server first, or check TASK_QUEUE_DB / STORAGE_DIR", file=sys.stderr)
        sys.exit(1)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _fmt_dt(iso: str | None) -> str:
    if not iso:
        return "-"
    try:
        return iso.replace("T", " ")[:16]
    except Exception:
        return str(iso)


_STATUS_COLORS = {
    "pending":   "\033[33m",   # yellow
    "running":   "\033[36m",   # cyan
    "completed": "\033[32m",   # green
    "failed":    "\033[31m",   # red
    "cancelled": "\033[90m",   # grey
}
_RESET = "\033[0m"


def _c(text: str, status: str) -> str:
    return f"{_STATUS_COLORS.get(status, '')}{text}{_RESET}"


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
def cmd_list(args: argparse.Namespace) -> None:
    conn = _connect()
    status_filter = args.status if args.status != "all" else None
    statuses = (status_filter,) if status_filter else ("pending", "running")

    where = "status IN ({})".format(",".join("?" * len(statuses)))
    params: list = list(statuses)
    if args.queue:
        where += " AND queue_name=?"
        params.append(args.queue)

    rows = conn.execute(
        f"""SELECT task_id, queue_name, task_type, priority, status,
                   created_at, started_at, completed_at, duration_s,
                   character_name, error
            FROM tasks WHERE {where}
            ORDER BY
              CASE status WHEN 'running' THEN 0 WHEN 'pending' THEN 1 ELSE 2 END,
              priority ASC, created_at ASC
            LIMIT {args.limit}""",
        params,
    ).fetchall()
    conn.close()

    if not rows:
        print("No tasks found.")
        return

    print(f"{'TASK_ID':<20} {'QUEUE':<12} {'TYPE':<28} {'PRIO':>4} {'STATUS':<11} {'CREATED':<16} {'CHARACTER':<14} {'ERR'}")
    print("-" * 115)
    for r in rows:
        err = (r["error"] or "")[:30]
        ts = _fmt_dt(r["completed_at"] or r["started_at"] or r["created_at"])
        status_padded = r['status'].ljust(11)
        print(
            f"{r['task_id']:<20} {r['queue_name']:<12} {r['task_type']:<28} "
            f"{r['priority']:>4} {_c(status_padded, r['status'])} "
            f"{ts:<16} {(r['character_name'] or ''):<14} {err}"
        )
    print(f"\n{len(rows)} task(s) shown.")


def cmd_info(args: argparse.Namespace) -> None:
    conn = _connect()
    row = conn.execute(
        "SELECT * FROM tasks WHERE task_id=?", (args.task_id,)
    ).fetchone()
    conn.close()
    if not row:
        print(f"Task not found: {args.task_id}")
        return
    d = dict(row)
    print(f"\n{'='*60}")
    print(f"Task: {d['task_id']}")
    print(f"{'='*60}")
    for k, v in d.items():
        if k == "payload":
            try:
                v = json.dumps(json.loads(v), ensure_ascii=False, indent=2)
            except Exception:
                pass
        elif k == "result" and v:
            try:
                v = json.dumps(json.loads(v), ensure_ascii=False, indent=2)[:500]
            except Exception:
                pass
        print(f"  {k:<16}: {v}")
    print()


def cmd_cancel(args: argparse.Namespace) -> None:
    conn = _connect()
    now = datetime.now().isoformat(timespec="seconds")
    cur = conn.execute(
        "UPDATE tasks SET status='cancelled', completed_at=?, error='Cancelled (CLI)'"
        " WHERE task_id=? AND status='pending'",
        (now, args.task_id),
    )
    conn.commit()
    conn.close()
    if cur.rowcount:
        print(f"\u2713 Task cancelled: {args.task_id}")
    else:
        print(f"Task not found, or not 'pending': {args.task_id}")


def cmd_retry(args: argparse.Namespace) -> None:
    conn = _connect()
    cur = conn.execute(
        """UPDATE tasks
           SET status='pending', error='', result=NULL,
               started_at=NULL, completed_at=NULL, duration_s=0
           WHERE task_id=? AND status IN ('failed','cancelled')""",
        (args.task_id,),
    )
    conn.commit()
    conn.close()
    if cur.rowcount:
        print(f"\u2713 Task reset to 'pending': {args.task_id}")
        print("  -> the server worker picks it up on its next cycle.")
    else:
        print(f"Task not found, or not failed/cancelled: {args.task_id}")


def cmd_move(args: argparse.Namespace) -> None:
    conn = _connect()
    cur = conn.execute(
        "UPDATE tasks SET queue_name=? WHERE task_id=? AND status='pending'",
        (args.queue, args.task_id),
    )
    conn.commit()
    conn.close()
    if cur.rowcount:
        print(f"\u2713 Task moved: {args.task_id} -> {args.queue}")
    else:
        print(f"Task not found, or not 'pending': {args.task_id}")


def cmd_priority(args: argparse.Namespace) -> None:
    conn = _connect()
    cur = conn.execute(
        "UPDATE tasks SET priority=? WHERE task_id=? AND status='pending'",
        (args.priority, args.task_id),
    )
    conn.commit()
    conn.close()
    if cur.rowcount:
        print(f"\u2713 Priority set: {args.task_id} -> {args.priority}")
    else:
        print(f"Task not found, or not 'pending': {args.task_id}")


def cmd_pause(args: argparse.Namespace) -> None:
    conn = _connect()
    now = datetime.now().isoformat(timespec="seconds")
    conn.execute(
        """INSERT INTO queue_paused (queue_name, paused, updated_at)
           VALUES (?, 1, ?)
           ON CONFLICT(queue_name) DO UPDATE SET paused=1, updated_at=?""",
        (args.queue, now, now),
    )
    conn.commit()
    conn.close()
    print(f"\u2713 Queue paused: {args.queue}")
    print("  -> running tasks finish; new ones wait.")


def cmd_resume(args: argparse.Namespace) -> None:
    conn = _connect()
    now = datetime.now().isoformat(timespec="seconds")
    conn.execute(
        """INSERT INTO queue_paused (queue_name, paused, updated_at)
           VALUES (?, 0, ?)
           ON CONFLICT(queue_name) DO UPDATE SET paused=0, updated_at=?""",
        (args.queue, now, now),
    )
    conn.commit()
    conn.close()
    print(f"\u2713 Queue resumed: {args.queue}")
    print("  -> the server worker resumes on its next cycle.")


def cmd_clear(args: argparse.Namespace) -> None:
    conn = _connect()
    cutoff = (datetime.now() - timedelta(hours=args.hours)).isoformat(timespec="seconds")
    statuses = [args.status] if args.status else ["completed", "failed", "cancelled"]
    placeholders = ",".join("?" * len(statuses))
    cur = conn.execute(
        f"DELETE FROM tasks WHERE status IN ({placeholders}) AND completed_at < ?",
        (*statuses, cutoff),
    )
    conn.commit()
    conn.close()
    print(f"\u2713 {cur.rowcount} task(s) deleted (older than {args.hours}h, status: {statuses})")


def cmd_stats(args: argparse.Namespace) -> None:
    conn = _connect()
    print(f"\nDatabase: {DB_PATH if DB_PATH else NO_DB}\n")

    # Per-queue stats
    queues = conn.execute(
        "SELECT DISTINCT queue_name FROM tasks ORDER BY queue_name"
    ).fetchall()
    paused_map = {
        r["queue_name"]: r["paused"]
        for r in conn.execute("SELECT queue_name, paused FROM queue_paused").fetchall()
    }

    print(f"{'QUEUE':<16} {'PAUSED':<8} {'PENDING':>7} {'RUNNING':>7} {'DONE':>7} {'FAILED':>7} {'CANCEL':>7}")
    print("-" * 65)
    for q in queues:
        qn = q["queue_name"]
        paused = "YES" if paused_map.get(qn) else "no"
        counts = {
            r["status"]: r["cnt"]
            for r in conn.execute(
                "SELECT status, COUNT(*) as cnt FROM tasks WHERE queue_name=? GROUP BY status",
                (qn,),
            ).fetchall()
        }
        print(
            f"{qn:<16} {paused:<8} {counts.get('pending',0):>7} {counts.get('running',0):>7} "
            f"{counts.get('completed',0):>7} {counts.get('failed',0):>7} {counts.get('cancelled',0):>7}"
        )

    # Overall
    total = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    oldest = conn.execute(
        "SELECT created_at FROM tasks ORDER BY created_at ASC LIMIT 1"
    ).fetchone()
    print(f"\nTotal: {total} tasks")
    if oldest:
        print(f"Oldest entry: {_fmt_dt(oldest[0])}")

    # Failed tasks with errors
    failed = conn.execute(
        "SELECT task_id, queue_name, task_type, error, completed_at FROM tasks"
        " WHERE status='failed' ORDER BY completed_at DESC LIMIT 5"
    ).fetchall()
    if failed:
        print("\nLatest errors:")
        for f in failed:
            print(f"  {f['task_id']} [{f['queue_name']}] {f['task_type']}: {(f['error'] or '')[:80]}")

    conn.close()


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="TaskQueue CLI \u2014 manage the queue without the server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # list
    p_list = sub.add_parser("list", help="List tasks")
    p_list.add_argument("-q", "--queue", default="", help="Filter by queue name")
    p_list.add_argument("-s", "--status", default="pending",
                        help="Status: pending|running|failed|cancelled|completed|all")
    p_list.add_argument("-n", "--limit", type=int, default=50, help="Max rows")
    p_list.set_defaults(func=cmd_list)

    # info
    p_info = sub.add_parser("info", help="Show task details")
    p_info.add_argument("task_id")
    p_info.set_defaults(func=cmd_info)

    # cancel
    p_cancel = sub.add_parser("cancel", help="Cancel a pending task")
    p_cancel.add_argument("task_id")
    p_cancel.set_defaults(func=cmd_cancel)

    # retry
    p_retry = sub.add_parser("retry", help="Retry a failed task")
    p_retry.add_argument("task_id")
    p_retry.set_defaults(func=cmd_retry)

    # move
    p_move = sub.add_parser("move", help="Move a task to another queue")
    p_move.add_argument("task_id")
    p_move.add_argument("queue", help="Target queue name")
    p_move.set_defaults(func=cmd_move)

    # priority
    p_prio = sub.add_parser("priority", help="Change a task's priority (lower = sooner)")
    p_prio.add_argument("task_id")
    p_prio.add_argument("priority", type=int, help="New priority (e.g. 10=high, 30=low)")
    p_prio.set_defaults(func=cmd_priority)

    # pause
    p_pause = sub.add_parser("pause", help="Pause a queue")
    p_pause.add_argument("queue", help="Queue name")
    p_pause.set_defaults(func=cmd_pause)

    # resume
    p_resume = sub.add_parser("resume", help="Resume a queue")
    p_resume.add_argument("queue", help="Queue name")
    p_resume.set_defaults(func=cmd_resume)

    # clear
    p_clear = sub.add_parser("clear", help="Delete old finished tasks")
    p_clear.add_argument("--hours", type=float, default=24.0,
                         help="Delete entries older than N hours (default: 24)")
    p_clear.add_argument("--status", default="",
                         help="Delete only this status (completed/failed/cancelled)")
    p_clear.set_defaults(func=cmd_clear)

    # stats
    p_stats = sub.add_parser("stats", help="Queue statistics")
    p_stats.set_defaults(func=cmd_stats)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
