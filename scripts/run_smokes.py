#!/usr/bin/env python3
"""Run the standalone smoke checks and report only what deviates from the known-red baseline.

Every ``scripts/smoke_*.py`` runs in its own process with the repo's ``.venv/bin/python`` (cwd = repo root,
no server).  The result is compared against ``scripts/smoke_baseline.txt`` — one line per KNOWN-red smoke,
``name<TAB>reason`` — so a smoke that turns red is visible again instead of drowning among the known ones.

Usage:
    ./.venv/bin/python scripts/run_smokes.py                       # every smoke, 4 at a time
    ./.venv/bin/python scripts/run_smokes.py --jobs 8              # more parallel processes
    ./.venv/bin/python scripts/run_smokes.py garment 'smoke_fit_*' # only matching smokes
    ./.venv/bin/python scripts/run_smokes.py --timeout 600         # per-smoke timeout in seconds (default 300)
    ./.venv/bin/python scripts/run_smokes.py -v                    # print the output tail of every newly red smoke
    ./.venv/bin/python scripts/run_smokes.py --log-dir /tmp/smk    # write the full output of every red smoke there
    ./.venv/bin/python scripts/run_smokes.py --update-baseline     # rewrite the baseline from this run
    ./.venv/bin/python scripts/run_smokes.py --list-red            # print the baseline grouped by reason

Filters: a positional argument containing ``*``, ``?`` or ``[`` is a glob on the smoke name, anything else a
substring; the ``smoke_`` prefix and ``.py`` suffix are optional.  With filters, only the matching smokes are
compared (and, with ``--update-baseline``, only their lines are rewritten).

Output: NEWLY RED (not in the baseline -> exit code 1), NOW GREEN (in the baseline but passing -> "remove from
baseline", exit code stays 0), baseline entries whose file is gone, and one total line.

Result rules:
  * exit code 0 = green.  A smoke that cannot run its subject here (no Blender, no node, no CMU mirror, ...)
    already prints ``SKIP``/``skipped`` and exits 0 — it counts as green; the total line counts such runs.
  * any other exit code, or the timeout, = red.

Isolation: each smoke gets ``STORAGE_DIR`` and ``INSTANCE_DIR`` pointing at its own fresh temp directories
(removed afterwards), so a smoke that forgets ``paths.init(<tmp>)`` can never reach a real world or the real
instance; a smoke that sets its own values overrides them.  (A full run with and without them gave the same
red set — they change no result, they only remove the risk.)  ``ANIMATION_CLIPS_DIR`` / ``ANIMATION_RIG_FILE`` are
passed through unchanged.  ``PYTHONPATH`` starts with the repo root, so a smoke that does not insert it imports
this checkout's ``app`` and not the one the venv's editable install points at.  The ``.mjs`` checks are not run.

Baseline file: ``#`` lines are comments, every other line is ``name<TAB>reason``, sorted by name.  Reasons begin
with a class tag — ``REAL:`` (may show a product bug), ``STALE:`` (pins an old expectation nobody could re-derive
with certainty), ``ENV:`` (needs something this machine lacks or depends on time/load) — and ``?`` marks a
smoke nobody has looked at yet.  ``--update-baseline`` keeps existing reasons and writes ``?`` for new ones.
"""
from __future__ import annotations

import argparse
import fnmatch
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"
BASELINE = SCRIPTS / "smoke_baseline.txt"

BASELINE_HEADER = """\
# Known-red smoke checks — read by scripts/run_smokes.py, one line per smoke: name<TAB>reason.
# A smoke listed here is red today for the stated reason; any OTHER red smoke is a regression.
# Reason tags: REAL = may show a product bug · STALE = pins an old expectation · ENV = machine/time/load · ? = unread.
# Remove a line as soon as the smoke passes ("NOW GREEN" in the runner output). Sorted by name.
"""

# A line a smoke prints when it skips (part of) its subject because this machine lacks something.
_SKIP_LINE = re.compile(r"^\W*(skip|skipped)\b", re.IGNORECASE | re.MULTILINE)
_TAIL_LINES = 25


def _interpreter(explicit: str | None) -> str:
    if explicit:
        return explicit
    venv = REPO / ".venv" / "bin" / "python"
    return str(venv) if venv.exists() else sys.executable


def _normalise(arg: str) -> str:
    name = arg[:-3] if arg.endswith(".py") else arg
    return name


def _select(all_names: list[str], filters: list[str]) -> list[str]:
    if not filters:
        return all_names
    picked = []
    for name in all_names:
        for raw in filters:
            f = _normalise(raw)
            if any(ch in f for ch in "*?["):
                if fnmatch.fnmatch(name, f) or fnmatch.fnmatch(name, "smoke_" + f):
                    picked.append(name)
                    break
            elif f in name:
                picked.append(name)
                break
    return picked


def read_baseline(path: Path = BASELINE) -> dict[str, str]:
    entries: dict[str, str] = {}
    if not path.exists():
        return entries
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        name, _, reason = line.partition("\t")
        entries[name.strip()] = reason.strip() or "?"
    return entries


def write_baseline(entries: dict[str, str], path: Path = BASELINE) -> None:
    body = "".join(f"{name}\t{entries[name]}\n" for name in sorted(entries))
    path.write_text(BASELINE_HEADER + body, encoding="utf-8")


def _tag(reason: str) -> str:
    head, sep, _ = reason.partition(":")
    return head.strip() if sep and head.strip().isupper() and " " not in head.strip() else reason


def list_red(entries: dict[str, str]) -> None:
    groups: dict[str, list[str]] = {}
    for name in sorted(entries):
        groups.setdefault(_tag(entries[name]), []).append(name)
    for tag in sorted(groups, key=lambda t: (-len(groups[t]), t)):
        print(f"{tag} ({len(groups[tag])})")
        for name in groups[tag]:
            print(f"  {name}\t{entries[name]}")
    print(f"{len(entries)} known-red smokes")


def run_one(name: str, python: str, timeout: float) -> dict:
    """Run one smoke in its own process group; return status, exit code, duration and the output."""
    tmp_root = Path(tempfile.mkdtemp(prefix=f"run_smokes_{name}_"))
    storage, instance = tmp_root / "storage", tmp_root / "instance"
    storage.mkdir()
    instance.mkdir()
    env = dict(os.environ)
    env["STORAGE_DIR"] = str(storage)
    env["INSTANCE_DIR"] = str(instance)
    # The repo first on the import path: about 50 smokes do not insert it themselves and would otherwise import
    # ``app`` through the venv's editable install, i.e. from whichever checkout that points at (wrong in a worktree).
    env["PYTHONPATH"] = os.pathsep.join([str(REPO)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
    env.setdefault("PYTHONUNBUFFERED", "1")
    started = time.monotonic()
    proc = subprocess.Popen(
        [python, str(SCRIPTS / f"{name}.py")], cwd=str(REPO), env=env,
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    try:
        out, _ = proc.communicate(timeout=timeout)
        status = "green" if proc.returncode == 0 else "red"
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        out, _ = proc.communicate()
        status = "timeout"
    finally:
        # A smoke may leave grandchildren (Blender, node) behind; they share its session.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        shutil.rmtree(tmp_root, ignore_errors=True)
    text = out.decode("utf-8", "replace") if out else ""
    return {
        "name": name, "status": status, "rc": proc.returncode,
        "seconds": time.monotonic() - started, "output": text,
        "skipped": status == "green" and bool(_SKIP_LINE.search(text)),
    }


def _tail(text: str, n: int = _TAIL_LINES) -> str:
    lines = text.rstrip().splitlines()
    return "\n".join("      " + ln for ln in lines[-n:])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("filters", nargs="*", help="smoke names: substring, or glob with * ? [")
    ap.add_argument("--jobs", "-j", type=int, default=4)
    ap.add_argument("--timeout", type=float, default=300.0, help="per-smoke timeout in seconds")
    ap.add_argument("--python", help="interpreter (default: <repo>/.venv/bin/python, else this one)")
    ap.add_argument("--update-baseline", action="store_true", help="rewrite the baseline from this run")
    ap.add_argument("--list-red", action="store_true", help="print the baseline grouped by reason and exit")
    ap.add_argument("--verbose", "-v", action="store_true", help="print the output tail of newly red smokes")
    ap.add_argument("--log-dir", type=Path, help="write the full output of every red smoke into this directory")
    args = ap.parse_args(argv)

    baseline = read_baseline()
    if args.list_red:
        list_red(baseline)
        return 0

    all_names = sorted(p.stem for p in SCRIPTS.glob("smoke_*.py"))
    names = _select(all_names, args.filters)
    if not names:
        print("no smoke matches", " ".join(args.filters))
        return 2
    python = _interpreter(args.python)
    if args.log_dir:
        args.log_dir.mkdir(parents=True, exist_ok=True)

    results: dict[str, dict] = {}
    started = time.monotonic()
    progress = sys.stderr.isatty()
    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        futures = [pool.submit(run_one, n, python, args.timeout) for n in names]
        for i, fut in enumerate(as_completed(futures), 1):
            r = fut.result()
            results[r["name"]] = r
            if r["status"] != "green" and args.log_dir:
                (args.log_dir / f"{r['name']}.log").write_text(
                    f"# status={r['status']} rc={r['rc']} seconds={r['seconds']:.1f}\n{r['output']}",
                    encoding="utf-8")
            if progress:
                print(f"\r[{i}/{len(names)}] {r['name'][:60]:<60}", end="", file=sys.stderr, flush=True)
    if progress:
        print(file=sys.stderr)

    red = {n for n, r in results.items() if r["status"] != "green"}
    newly_red = sorted(red - baseline.keys())
    now_green = sorted(n for n in names if n in baseline and n not in red)
    gone = sorted(n for n in baseline if n not in all_names) if not args.filters else []

    for n in newly_red:
        r = results[n]
        how = "timeout" if r["status"] == "timeout" else f"exit {r['rc']}"
        print(f"NEWLY RED  {n}  ({how}, {r['seconds']:.0f} s)")
        if args.verbose:
            print(_tail(r["output"]))
    for n in now_green:
        print(f"NOW GREEN  {n}  -> remove from baseline")
    for n in gone:
        print(f"GONE       {n}  -> baseline entry for a smoke file that no longer exists")

    if args.update_baseline:
        updated = dict(baseline)
        for n in names:
            if n in red:
                updated.setdefault(n, "?")
            else:
                updated.pop(n, None)
        for n in gone:
            updated.pop(n, None)
        write_baseline(updated)
        print(f"baseline rewritten: {len(updated)} entries ({BASELINE.relative_to(REPO)})")

    skipped = sum(1 for r in results.values() if r["skipped"])
    timeouts = sum(1 for r in results.values() if r["status"] == "timeout")
    print(f"{len(names)} smokes in {time.monotonic() - started:.0f} s: "
          f"{len(names) - len(red)} green ({skipped} with skips), {len(red)} red "
          f"({len(red) - len(newly_red)} known, {len(newly_red)} new, {timeouts} timeouts), "
          f"{len(now_green)} now green")
    return 1 if newly_red else 0


if __name__ == "__main__":
    sys.exit(main())
