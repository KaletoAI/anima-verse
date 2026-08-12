#!/usr/bin/env python3
"""Check: LLM log pruning archives instead of deleting.

Usage:
    ./.venv/bin/python scripts/test_log_archive.py

Verifies app/utils/llm_logger.prune_jsonl_log(): entries falling out of the
retention window must be appended to logs/archive/<stem>_<YYYY-MM>.jsonl
(bucket = the month of the entry itself) before the live file is shortened,
and a failing archive write must leave the live file untouched.

Runs without server and without a world DB. Every case works inside its own
tempfile.mkdtemp() directory — the real logs/ of the repo are never touched; a
before/after guard at the end of the run proves that (see guard_repo_logs).
Expected values are derived by hand in each case (see the comments), not
snapshotted.

Exit code 0 = all cases green, != 0 = first failing case is printed.
"""
import json
import os
import shutil
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.timeutils import utc_now  # noqa: E402
from app.utils import llm_logger  # noqa: E402

FAILURES = []
CASES = 0


def check(label, cond, detail=""):
    global CASES
    CASES += 1
    if not cond:
        FAILURES.append("FAIL [%s] %s" % (label, detail))
        print("  FAIL %s — %s" % (label, detail))
    else:
        print("  ok   %s" % label)


def entry(days_ago, marker, hours=0):
    """One JSONL line whose starttime lies days_ago days in the past."""
    ts = utc_now() - timedelta(days=days_ago, hours=hours)
    return json.dumps({
        "starttime": ts.isoformat(timespec="seconds"),
        "task": "chat",
        "model": "demo-model",
        "marker": marker,
    }, ensure_ascii=False)


def entry_at(iso, marker):
    """One JSONL line with an explicitly given starttime."""
    return json.dumps({"starttime": iso, "task": "chat", "marker": marker},
                      ensure_ascii=False)


def write_lines(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for ln in lines:
            f.write(ln + "\n")


def read_lines(path):
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [ln.strip() for ln in f if ln.strip()]


def markers(lines):
    out = []
    for ln in lines:
        try:
            out.append(json.loads(ln).get("marker"))
        except Exception:
            out.append("<unparsable:%s>" % ln[:20])
    return out


def sandbox():
    d = Path(tempfile.mkdtemp(prefix="log_archive_check_"))
    return d, d / "llm_calls.jsonl", d / "archive"


def case_1_2_old_out_new_in():
    """Retention 5 days. 2 entries at 9/7 days -> archived, 2 at 3/1 days -> kept.
    Expected: removed == 2, live file has exactly markers new1/new2,
    bucket of the current-minus-9/-7-days month holds old1/old2 verbatim."""
    print("case 1+2: old entries archived, recent entries stay")
    d, live, arch = sandbox()
    try:
        old1, old2 = entry(9, "old1"), entry(7, "old2")
        new1, new2 = entry(3, "new1"), entry(1, "new2")
        write_lines(live, [old1, new1, old2, new2])

        removed = llm_logger.prune_jsonl_log(live, 5)
        check("removed count == 2", removed == 2, "got %r" % removed)
        check("live keeps 2 recent entries",
              markers(read_lines(live)) == ["new1", "new2"],
              "live = %r" % markers(read_lines(live)))

        buckets = sorted(p.name for p in arch.glob("*.jsonl"))
        archived = []
        for p in sorted(arch.glob("*.jsonl")):
            archived += read_lines(p)
        check("archive holds exactly the 2 removed lines, verbatim",
              sorted(archived) == sorted([old1, old2]),
              "buckets=%r lines=%r" % (buckets, markers(archived)))
        check("recent entries are NOT in the archive",
              not any(m in ("new1", "new2") for m in markers(archived)),
              "archive = %r" % markers(archived))
        check("bucket name follows <stem>_<YYYY-MM>.jsonl",
              all(b.startswith("llm_calls_") and len(b) == len("llm_calls_2026-07.jsonl")
                  for b in buckets),
              "buckets = %r" % buckets)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def case_3_idempotent():
    """Same file pruned twice. Second run finds nothing older than the window,
    so it must return 0 and leave the archive byte-identical."""
    print("case 3: second run duplicates nothing")
    d, live, arch = sandbox()
    try:
        write_lines(live, [entry(9, "old1"), entry(2, "new1")])
        first = llm_logger.prune_jsonl_log(live, 5)
        after_first = {p.name: read_lines(p) for p in sorted(arch.glob("*.jsonl"))}
        second = llm_logger.prune_jsonl_log(live, 5)
        after_second = {p.name: read_lines(p) for p in sorted(arch.glob("*.jsonl"))}

        check("first run removed 1", first == 1, "got %r" % first)
        check("second run removed 0", second == 0, "got %r" % second)
        check("archive unchanged after second run", after_first == after_second,
              "%r != %r" % ({k: len(v) for k, v in after_first.items()},
                            {k: len(v) for k, v in after_second.items()}))
        total = sum(len(v) for v in after_second.values())
        check("archive still holds exactly 1 line", total == 1, "got %d" % total)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def case_4_two_months():
    """3 fixed-date entries: 2 in 2026-05, 1 in 2026-06, all far in the past.
    Expected: two buckets llm_calls_2026-05.jsonl (2 lines) and
    llm_calls_2026-06.jsonl (1 line) — month from the entry, not from today."""
    print("case 4: two months -> two buckets")
    d, live, arch = sandbox()
    try:
        a = entry_at("2026-05-03T10:00:00+00:00", "may1")
        b = entry_at("2026-05-28T23:59:00+00:00", "may2")
        c = entry_at("2026-06-01T00:00:00+00:00", "jun1")
        write_lines(live, [a, c, b])

        removed = llm_logger.prune_jsonl_log(live, 5)
        check("removed count == 3", removed == 3, "got %r" % removed)
        check("live file is empty", read_lines(live) == [],
              "live = %r" % markers(read_lines(live)))
        may = read_lines(arch / "llm_calls_2026-05.jsonl")
        jun = read_lines(arch / "llm_calls_2026-06.jsonl")
        check("bucket 2026-05 holds 2 lines", markers(may) == ["may1", "may2"],
              "got %r" % markers(may))
        check("bucket 2026-06 holds 1 line", markers(jun) == ["jun1"],
              "got %r" % markers(jun))
        check("exactly 2 buckets exist", len(list(arch.glob("*.jsonl"))) == 2,
              "got %r" % sorted(p.name for p in arch.glob("*.jsonl")))
    finally:
        shutil.rmtree(d, ignore_errors=True)


def case_5_append_existing():
    """Bucket 2026-05 already holds 1 pre-existing line. Pruning 2 more entries
    of that month must yield 3 lines with the pre-existing line still first."""
    print("case 5: existing archive is appended, not overwritten")
    d, live, arch = sandbox()
    try:
        pre = entry_at("2026-05-01T08:00:00+00:00", "pre_existing")
        write_lines(arch / "llm_calls_2026-05.jsonl", [pre])
        write_lines(live, [entry_at("2026-05-10T08:00:00+00:00", "m1"),
                           entry_at("2026-05-11T08:00:00+00:00", "m2")])

        removed = llm_logger.prune_jsonl_log(live, 5)
        got = markers(read_lines(arch / "llm_calls_2026-05.jsonl"))
        check("removed count == 2", removed == 2, "got %r" % removed)
        check("bucket holds 3 lines, pre-existing one first",
              got == ["pre_existing", "m1", "m2"], "got %r" % got)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def case_6_no_starttime():
    """A line without starttime, an unparsable line and lines with a malformed
    starttime must all stay in the live file and never reach the archive.
    Only the one dated entry is archived.

    The malformed values are chosen so that they DISCRIMINATE, i.e. they are
    only kept because of the ``_MONTH_RE`` guard: "1999", "199905", "0" and
    "2026" all sort lexically BEFORE the cutoff ISO string, so without the guard
    they would be removed from the live file and land in a garbage bucket
    ("llm_calls_1999.jsonl", "llm_calls_0.jsonl", ...). "nonsense" sorts after
    the cutoff and would be kept either way — it is included as the plain
    "no timestamp semantics" case, not as evidence for the guard."""
    print("case 6: no/unusable starttime stays in the live file")
    d, live, arch = sandbox()
    try:
        no_ts = json.dumps({"task": "chat", "marker": "no_ts"})
        broken = "{not json at all"
        bad_ts = entry_at("nonsense", "bad_ts")
        # discriminating: lexically < cutoff, but no YYYY-MM prefix
        short1 = entry_at("1999", "short1")
        short2 = entry_at("199905", "short2")
        short3 = entry_at("0", "short3")
        short4 = entry_at("2026", "short4")
        old = entry_at("2026-05-05T08:00:00+00:00", "old1")
        undatable = [no_ts, broken, bad_ts, short1, short2, short3, short4]
        write_lines(live, undatable + [old])

        removed = llm_logger.prune_jsonl_log(live, 5)
        live_lines = read_lines(live)
        archived = []
        for p in sorted(arch.glob("*.jsonl")):
            archived += read_lines(p)
        check("removed count == 1", removed == 1, "got %r" % removed)
        check("live keeps all %d undatable lines" % len(undatable),
              live_lines == undatable,
              "live = %r" % markers(live_lines))
        check("archive holds only the dated entry", markers(archived) == ["old1"],
              "archive = %r" % markers(archived))
        check("exactly one bucket, named llm_calls_2026-05.jsonl",
              [p.name for p in sorted(arch.glob("*.jsonl"))] == ["llm_calls_2026-05.jsonl"],
              "got %r" % [p.name for p in sorted(arch.glob("*.jsonl"))])
    finally:
        shutil.rmtree(d, ignore_errors=True)


def case_7_archive_unwritable():
    """The decisive case. 'archive' exists as a FILE, so mkdir of the archive
    directory fails. Expected: return 0, live file byte-identical, the blocking
    file untouched."""
    print("case 7: archive not writable -> live file untouched")
    for variant in ("archive-is-a-file", "archive-dir-read-only"):
        d, live, arch = sandbox()
        try:
            lines = [entry_at("2026-05-05T08:00:00+00:00", "old1"),
                     entry(1, "new1")]
            write_lines(live, lines)
            before = live.read_bytes()

            if variant == "archive-is-a-file":
                arch.write_text("i am a file, not a directory\n", encoding="utf-8")
            else:
                arch.mkdir(parents=True, exist_ok=True)
                os.chmod(arch, 0o500)  # r-x: cannot create files inside

            removed = llm_logger.prune_jsonl_log(live, 5)
            check("[%s] return value is 0" % variant, removed == 0, "got %r" % removed)
            check("[%s] live file byte-identical" % variant,
                  live.read_bytes() == before,
                  "live = %r" % markers(read_lines(live)))
            if variant == "archive-is-a-file":
                check("[%s] blocking file untouched" % variant,
                      arch.read_text(encoding="utf-8") == "i am a file, not a directory\n",
                      "content = %r" % arch.read_text(encoding="utf-8"))
            else:
                os.chmod(arch, 0o700)
                check("[%s] no bucket was created" % variant,
                      list(arch.glob("*.jsonl")) == [],
                      "got %r" % [p.name for p in arch.glob("*.jsonl")])
        finally:
            if arch.is_dir():
                os.chmod(arch, 0o700)
            shutil.rmtree(d, ignore_errors=True)


def case_7b_partial_rollback():
    """Two buckets, the second one not writable (read-only file). The append of
    bucket 1 must be rolled back to its previous size, so a retry cannot
    duplicate: bucket 2026-05 must still hold exactly its 1 pre-existing line."""
    print("case 7b: failure in the second bucket rolls the first one back")
    d, live, arch = sandbox()
    blocked = arch / "llm_calls_2026-06.jsonl"
    try:
        pre = entry_at("2026-05-01T08:00:00+00:00", "pre_existing")
        write_lines(arch / "llm_calls_2026-05.jsonl", [pre])
        blocked.write_text("", encoding="utf-8")
        os.chmod(blocked, 0o400)  # read-only -> append raises

        live_lines = [entry_at("2026-05-10T08:00:00+00:00", "m1"),
                      entry_at("2026-06-10T08:00:00+00:00", "j1")]
        write_lines(live, live_lines)
        before = live.read_bytes()

        removed = llm_logger.prune_jsonl_log(live, 5)
        check("return value is 0", removed == 0, "got %r" % removed)
        check("live file byte-identical", live.read_bytes() == before,
              "live = %r" % markers(read_lines(live)))
        may = markers(read_lines(arch / "llm_calls_2026-05.jsonl"))
        check("first bucket rolled back to its 1 pre-existing line",
              may == ["pre_existing"], "got %r" % may)
    finally:
        if blocked.exists():
            os.chmod(blocked, 0o600)
        shutil.rmtree(d, ignore_errors=True)


def case_9_replace_fails_after_archive():
    """The only duplicate path: archiving succeeds, replacing the live file
    fails (the log directory is read-only, so the .tmp file cannot be created,
    while appending to the pre-existing bucket still works).
    Expected: return 0, live file unchanged, but the entry IS in the archive —
    a following run would archive it a second time. The warning must say so."""
    print("case 9: replace fails after successful archiving")
    d, live, arch = sandbox()
    bucket = arch / "llm_calls_2026-05.jsonl"
    try:
        write_lines(bucket, [])          # bucket exists and is writable
        old = entry_at("2026-05-05T08:00:00+00:00", "old1")
        write_lines(live, [old, entry(1, "new1")])
        before = live.read_bytes()
        os.chmod(d, 0o500)               # no new files next to the live log

        removed = llm_logger.prune_jsonl_log(live, 5)
        os.chmod(d, 0o700)
        check("return value is 0", removed == 0, "got %r" % removed)
        check("live file byte-identical", live.read_bytes() == before,
              "live = %r" % markers(read_lines(live)))
        check("entry did reach the archive", markers(read_lines(bucket)) == ["old1"],
              "bucket = %r" % markers(read_lines(bucket)))
        check("no .tmp leftover next to the live log",
              list(d.glob("*.tmp")) == [], "got %r" % [p.name for p in d.glob("*.tmp")])
    finally:
        os.chmod(d, 0o700)
        shutil.rmtree(d, ignore_errors=True)


def case_8_noop():
    """retention_days < 1 and a missing file change nothing at all —
    especially they must not create an archive directory."""
    print("case 8: retention < 1 and missing file are no-ops")
    d, live, arch = sandbox()
    try:
        lines = [entry_at("2026-05-05T08:00:00+00:00", "old1")]
        write_lines(live, lines)
        before = live.read_bytes()

        check("retention 0 returns 0", llm_logger.prune_jsonl_log(live, 0) == 0)
        check("retention -3 returns 0", llm_logger.prune_jsonl_log(live, -3) == 0)
        check("live file unchanged", live.read_bytes() == before)
        check("no archive dir created", not arch.exists())

        missing = d / "does_not_exist.jsonl"
        check("missing file returns 0", llm_logger.prune_jsonl_log(missing, 5) == 0)
        check("missing file was not created", not missing.exists())
        check("still no archive dir", not arch.exists())
    finally:
        shutil.rmtree(d, ignore_errors=True)


def dir_snapshot(d):
    """{file name: (size, mtime_ns)} for the files directly inside d, or None
    when d does not exist."""
    if not d.is_dir():
        return None
    return {p.name: (p.stat().st_size, p.stat().st_mtime_ns)
            for p in d.iterdir() if p.is_file()}


def snapshot_diff(before, after):
    """Human-readable difference of two dir_snapshot() results."""
    if before is None or after is None:
        return "%r -> %r" % (before, after)
    added = sorted(set(after) - set(before))
    gone = sorted(set(before) - set(after))
    changed = sorted(n for n in set(before) & set(after) if before[n] != after[n])
    return "added=%r removed=%r changed=%r" % (added, gone, changed)


def guard_repo_logs(repo_logs, before_logs, before_arch):
    """The repo's real logs/ must come out of the run untouched BY THIS CHECK.

    Absence proves nothing here: since the fix runs in production, logs/archive/
    legitimately holds llm_calls_<YYYY-MM>.jsonl buckets, and a running server
    appends to logs/*.log and the live JSONL files at any moment. So the guard
    compares before against after and asks what only this check could have
    caused:

    * no file appears in or disappears from logs/ — archiving the real live log
      would create a bucket, and every case here is supposed to stay inside its
      tempdir;
    * no file in logs/ gets SMALLER — the server only appends, whereas pruning
      rewrites a file shorter; growth during the run is legitimate;
    * no .tmp leftover — prune_jsonl_log writes <log>.tmp before renaming;
    * logs/archive/ is byte-identical (names, sizes, mtimes). Buckets are only
      written at server startup, which does not happen during a test run, so
      strict equality is stable here and catches an append into an existing
      bucket as well.
    """
    print("guard: repo logs/ untouched by this check")
    after_logs = dir_snapshot(repo_logs)
    after_arch = dir_snapshot(repo_logs / "archive")

    if before_logs is None:
        check("logs/ exists", after_logs is None, "appeared during the run")
        return
    check("no file added to / removed from logs/",
          set(after_logs) == set(before_logs), snapshot_diff(before_logs, after_logs))
    shrunk = sorted(n for n in set(before_logs) & set(after_logs)
                    if after_logs[n][0] < before_logs[n][0])
    check("no file in logs/ got smaller (append by the server is fine)",
          not shrunk,
          "shrunk: %r" % [(n, before_logs[n][0], after_logs[n][0]) for n in shrunk])
    check("no .tmp leftover in logs/",
          not [n for n in after_logs if n.endswith(".tmp")],
          "got %r" % [n for n in after_logs if n.endswith(".tmp")])
    check("logs/archive/ byte-identical (names, sizes, mtimes)",
          after_arch == before_arch, snapshot_diff(before_arch, after_arch))


def main():
    repo_logs = Path(__file__).resolve().parent.parent / "logs"
    before_logs = dir_snapshot(repo_logs)
    before_arch = dir_snapshot(repo_logs / "archive")

    case_1_2_old_out_new_in()
    case_3_idempotent()
    case_4_two_months()
    case_5_append_existing()
    case_6_no_starttime()
    case_7_archive_unwritable()
    case_7b_partial_rollback()
    case_9_replace_fails_after_archive()
    case_8_noop()

    guard_repo_logs(repo_logs, before_logs, before_arch)

    print("")
    if FAILURES:
        print("RED — %d of %d checks failed:" % (len(FAILURES), CASES))
        for f in FAILURES:
            print("  " + f)
        return 1
    print("GREEN — all %d checks passed" % CASES)
    return 0


if __name__ == "__main__":
    sys.exit(main())
