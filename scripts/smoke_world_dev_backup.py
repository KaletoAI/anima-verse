#!/usr/bin/env python3
"""Smoke check for the World Dev free-mode safety backup and its offline restore.

Usage:  ./.venv/bin/python scripts/smoke_world_dev_backup.py

Throwaway storage only (``paths.init(<tmpdir>)`` before any world-DB import);
the restore script's pid guard is pointed at a throwaway pid directory, never at
the repo's ``.pids/``.

Expectations, derived by hand from the plan (Task 4) and the spec (§ Safety
backup), not recorded from a run:

  [1] take_backup("run_a") returns <storage>/.cache/world_dev_backups/run_a and
      that directory holds world.db (a SQLite online backup) and the text files
      of characters/demo: soul/personality.md and character.json. The PNG beside
      them is NOT copied ("text files, not images").
  [2] After the backup the location loc_a is renamed Alpha -> Beta (that change is
      left in a STRAY world.db-wal + world.db-shm on disk), the soul file is
      rewritten to "changed", and a new character directory characters/newcomer
      appears. restore_backup("run_a", storage):
        - loc_a is named Alpha again (read with a FRESH connection; a WAL that
          survived the restore would replay Beta onto the restored file),
        - no world.db-wal / world.db-shm remains from before (a fresh open may
          create new ones, so the check is that the Beta frames are gone),
        - personality.md reads "original" again,
        - characters/newcomer is gone from the world and lives in
          <backup>/removed_after_restore/newcomer (moved, never deleted),
        - the returned dict names the db, 2 restored text files and
          ["newcomer"] as moved.
  [3] Retention MAX_BACKUPS = 10: run_a plus ten more backups r01..r10 are 11;
      the oldest (run_a) is pruned, exactly 10 directories remain, r10 among them.
  [4] The script refuses while a server may run: a pid file naming THIS process
      (alive by definition) -> exit code 2, and neither world.db nor the soul
      file changed (byte-identical before and after).
  [5] An unsafe run id ("../x") is refused by both take_backup and
      restore_backup with ValueError.
"""
import hashlib
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from app.core import paths  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="smoke_wd_backup_"))
STORAGE = TMP / "world"
STORAGE.mkdir()
paths.init(STORAGE)

from app.core import db  # noqa: E402
from app.models.world import upsert_location  # noqa: E402

FAILS = []


def check(cond, label):
    print(("PASS " if cond else "FAIL ") + label)
    if not cond:
        FAILS.append(label)


def loc_name(path: Path) -> str:
    conn = sqlite3.connect(str(path))
    try:
        row = conn.execute("SELECT name FROM locations WHERE id = 'loc_a'").fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def close_db_connections():
    for conn in list(db._connections.values()):
        try:
            conn.close()
        except Exception:
            pass
    db._connections.clear()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    try:
        from app.core import world_dev_backup as wdb
    except ImportError as e:
        print(f"FAIL import app.core.world_dev_backup: {e}")
        return 1

    db.init_schema()
    check(upsert_location({"id": "loc_a", "name": "Alpha"}, sync_world=False),
          "seed location written")
    char = STORAGE / "characters" / "demo"
    (char / "soul").mkdir(parents=True)
    (char / "images").mkdir()
    soul = char / "soul" / "personality.md"
    soul.write_text("original", encoding="utf-8")
    (char / "character.json").write_text('{"name": "demo"}', encoding="utf-8")
    (char / "images" / "portrait.png").write_bytes(b"\x89PNG\r\n\x1a\n fake")

    # [1]
    bpath = Path(wdb.take_backup("run_a"))
    expected = STORAGE / ".cache" / "world_dev_backups" / "run_a"
    check(bpath.resolve() == expected.resolve(), f"[1] backup path {bpath}")
    check((bpath / "world.db").is_file(), "[1] world.db in backup")
    check(loc_name(bpath / "world.db") == "Alpha", "[1] backup holds Alpha")
    bchar = bpath / "characters" / "demo"
    check((bchar / "soul" / "personality.md").read_text() == "original",
          "[1] soul md copied")
    check((bchar / "character.json").is_file(), "[1] character.json copied")
    check(not (bchar / "images" / "portrait.png").exists(), "[1] png not copied")

    # [2] change the world; keep the rename in a stray WAL
    check(upsert_location({"id": "loc_a", "name": "Beta"}, sync_world=False),
          "[2] rename written")
    wal = STORAGE / "world.db-wal"
    shm = STORAGE / "world.db-shm"
    check(wal.is_file() and wal.stat().st_size > 0, "[2] live WAL exists")
    wal_copy = TMP / "wal.copy"
    shm_copy = TMP / "shm.copy"
    shutil.copy2(wal, wal_copy)
    if shm.exists():
        shutil.copy2(shm, shm_copy)
    close_db_connections()          # the restore runs with the server stopped
    shutil.copy2(wal_copy, wal)     # leave the stray WAL behind
    if shm_copy.exists():
        shutil.copy2(shm_copy, shm)
    soul.write_text("changed", encoding="utf-8")
    (STORAGE / "characters" / "newcomer" / "soul").mkdir(parents=True)
    (STORAGE / "characters" / "newcomer" / "soul" / "x.md").write_text("x")

    report = wdb.restore_backup("run_a", STORAGE)
    print("     restore report:", report)
    check(loc_name(STORAGE / "world.db") == "Alpha", "[2] loc_a is Alpha again")
    check(soul.read_text(encoding="utf-8") == "original", "[2] soul md restored")
    check(not (STORAGE / "characters" / "newcomer").exists(),
          "[2] newcomer gone from the world")
    check((bpath / "removed_after_restore" / "newcomer" / "soul" / "x.md").is_file(),
          "[2] newcomer moved into removed_after_restore")
    check(report.get("moved_dirs") == ["newcomer"], "[2] report names newcomer")
    check(report.get("text_files") == 2, "[2] report: 2 text files restored")
    check(bool(report.get("db")), "[2] report names the db")

    # [3] retention
    for i in range(1, 11):
        wdb.take_backup(f"r{i:02d}")
    root = STORAGE / ".cache" / "world_dev_backups"
    names = sorted(p.name for p in root.iterdir() if p.is_dir())
    check(len(names) == 10, f"[3] 10 backups remain ({len(names)})")
    check("run_a" not in names, "[3] oldest (run_a) pruned")
    check("r10" in names and "r01" in names, "[3] r01..r10 kept")

    # [4] the script refuses while a pid file names a live process
    pid_dir = TMP / "pids"
    pid_dir.mkdir()
    (pid_dir / "main.pid").write_text(str(os.getpid()))
    soul.write_text("marker", encoding="utf-8")
    db_before = digest(STORAGE / "world.db")
    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "world_dev_restore.py"), "r05",
         "--storage", str(STORAGE), "--pid-dir", str(pid_dir)],
        capture_output=True, text=True, cwd=str(REPO))
    print("     script stdout/stderr:", (proc.stdout + proc.stderr).strip()[:300])
    check(proc.returncode == 2, f"[4] exit code 2 (got {proc.returncode})")
    check(digest(STORAGE / "world.db") == db_before, "[4] world.db untouched")
    check(soul.read_text(encoding="utf-8") == "marker", "[4] soul untouched")

    # [5]
    for fn, args in (("take_backup", ("../x",)),
                     ("restore_backup", ("../x", STORAGE))):
        try:
            getattr(wdb, fn)(*args)
            check(False, f"[5] {fn} refuses ../x")
        except ValueError:
            check(True, f"[5] {fn} refuses ../x")

    print(f"\n{'FAILED' if FAILS else 'OK'}: {len(FAILS)} failure(s)")
    return 1 if FAILS else 0


if __name__ == "__main__":
    rc = 1
    try:
        rc = main()
    finally:
        close_db_connections()
        shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(rc)
