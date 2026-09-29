"""Commit a published clip WITHOUT the catalog's foreign local edits.

pose_catalog.json carries entries in the working tree that must never be
committed (licensed/local material). ``git commit -- <catalog>`` would take
them along. So the commit is built in a TEMPORARY index: HEAD's tree, the
catalog blob = HEAD's catalog + exactly the new entry (the same JSON layout
the server writes), the new files from the working tree. Neither the shared
index nor the working tree is touched; the shared index is re-synced to the
new HEAD for exactly these paths afterwards.

Plumbing only (``commit-tree`` + ``update-ref``), so no commit hooks run.
``update-ref HEAD <new> <old>`` is a compare-and-swap: when another session
committed in between, the whole commit is rebuilt on the new HEAD.
"""
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import List

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


def commit_with_entry(repo: Path, catalog_rel: str, key: str, entry: dict,
                      add_paths: List[str], message: str) -> str:
    """One commit on HEAD: HEAD's catalog + ``entries[key] = entry`` and the
    working-tree state of ``add_paths`` (repo-relative). Returns the hash."""
    for _attempt in range(3):
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
            commit = _git(repo, "commit-tree", tree, "-p", head, "-m", message).strip()
            res = _run(repo, ["update-ref", "-m", "animstudio publish", "HEAD", commit, head])
            if res.returncode == 0:
                _git(repo, "reset", "-q", "--", catalog_rel, *add_paths)
                return commit
        finally:
            if os.path.exists(idx):
                os.unlink(idx)
    raise StudioError("HEAD kept moving while committing - try again")
