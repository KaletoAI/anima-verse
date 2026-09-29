"""Commit a published clip WITHOUT the catalog's foreign local edits.

pose_catalog.json carries entries in the working tree that must never be
committed (licensed/local material). ``git commit -- <catalog>`` would take
them along. So the commit is built in a TEMPORARY index: HEAD's tree, the
catalog blob = HEAD's catalog + exactly the new entry (the same JSON layout
the server writes), the new files from the working tree. Neither the shared
index nor the working tree is touched; the shared index is re-synced to the
new HEAD for exactly these paths afterwards. That re-sync failing (e.g. a
foreign ``index.lock``) never hides the landed commit: the sha comes back
with a warning that carries the ``git -C <repo> reset`` command to run by
hand (from any cwd). A tree
equal to HEAD's makes no commit at all (a ``publish --replace`` rerun after a
landed commit is harmless).

Plumbing only (``commit-tree`` + ``update-ref``), so no commit hooks run.
``update-ref HEAD <new> <old>`` is a compare-and-swap: when another session
committed in between, the whole commit is rebuilt on the new HEAD.
"""
import json
import os
import shlex
import subprocess
import tempfile
import time
from pathlib import Path
from typing import List, NamedTuple

from animstudio import StudioError


def _run(repo: Path, args, env=None, input_text=None) -> subprocess.CompletedProcess:
    # UTF-8 explicitly: the catalog carries non-ASCII synonyms, and text=True
    # alone would encode with the locale (ASCII under LANG=C).
    return subprocess.run(["git", *args], cwd=repo, env=env, input=input_text,
                          capture_output=True, text=True, encoding="utf-8")


def _git(repo: Path, *args: str, env=None, input_text=None) -> str:
    res = _run(repo, args, env=env, input_text=input_text)
    if res.returncode != 0:
        raise StudioError(f"git {' '.join(args)}: {res.stderr.strip()}")
    return res.stdout


class CommitResult(NamedTuple):
    """``sha`` is HEAD after the call; ``created`` is false when HEAD already
    had exactly this tree (no commit made); ``warning`` is non-empty when the
    commit is on HEAD but the shared index could not be synced — the caller
    must show it (it carries the ``git reset`` command to run)."""
    sha: str
    created: bool
    warning: str = ""


def _sync_index(repo: Path, sha: str, paths: List[str], created: bool) -> str:
    """Re-syncs the shared index to HEAD for ``paths``. A failure here must
    not hide the commit that already landed: it becomes a warning whose
    command works from ANY cwd (``git -C <repo>``: pathspecs resolve against
    the cwd, and ``-q`` would hide a mismatch from a subdirectory)."""
    try:
        res = _run(repo, ["reset", "-q", "--", *paths])
        err = "" if res.returncode == 0 else (res.stderr.strip().splitlines() or ["?"])[0]
    except OSError as e:
        err = str(e)
    if not err:
        return ""
    what = f"commit {sha} landed" if created else f"HEAD {sha} already has this"
    cmd = " ".join(shlex.quote(a) for a in
                   ["git", "-C", str(Path(repo).resolve()), "reset", "-q", "--", *paths])
    return f"{what}; shared index not synced ({err}) - run `{cmd}`"


def commit_with_entry(repo: Path, catalog_rel: str, key: str, entry: dict,
                      add_paths: List[str], message: str) -> CommitResult:
    """One commit on HEAD: HEAD's catalog + ``entries[key] = entry`` and the
    working-tree state of ``add_paths`` (repo-relative).

    When the resulting tree equals HEAD's, no commit is made (a rerun after a
    landed commit is harmless). Raises StudioError when no commit landed;
    once one is on HEAD it never raises — see ``CommitResult.warning``."""
    paths = [catalog_rel, *add_paths]
    last_err = ""
    for attempt in range(1, 4):
        if attempt > 1:
            time.sleep(0.2 * attempt)
        head = _git(repo, "rev-parse", "HEAD").strip()
        fd, idx = tempfile.mkstemp(prefix="animstudio-index-")
        os.close(fd)
        os.unlink(idx)                    # git wants to create the index itself
        env = {**os.environ, "GIT_INDEX_FILE": idx}
        try:
            _git(repo, "read-tree", head, env=env)
            doc = json.loads(_git(repo, "show", f"{head}:{catalog_rel}"))
            doc.setdefault("entries", {})[key] = entry
            blob = _git(repo, "hash-object", "-w", "--stdin",
                        input_text=json.dumps(doc, ensure_ascii=False, indent=2)).strip()
            _git(repo, "update-index", "--add", "--cacheinfo", f"100644,{blob},{catalog_rel}",
                 env=env)
            for p in add_paths:
                _git(repo, "update-index", "--add", "--", p, env=env)
            tree = _git(repo, "write-tree", env=env).strip()
        finally:
            if os.path.exists(idx):
                os.unlink(idx)
        if tree == _git(repo, "rev-parse", f"{head}^{{tree}}").strip():
            return CommitResult(head, False, _sync_index(repo, head, paths, False))
        commit = _git(repo, "commit-tree", tree, "-p", head, "-m", message).strip()
        res = _run(repo, ["update-ref", "-m", "animstudio publish", "HEAD", commit, head])
        if res.returncode == 0:
            return CommitResult(commit, True, _sync_index(repo, commit, paths, True))
        last_err = res.stderr.strip()
    raise StudioError(f"HEAD kept moving while committing - try again "
                      f"(git update-ref: {last_err or '?'})")
