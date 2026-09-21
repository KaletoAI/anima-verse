#!/usr/bin/env python3
"""Smoke: docs/config-defaults.md documents nothing that no longer exists.

Usage:  ./.venv/bin/python scripts/smoke_docs_config_defaults.py

Covers review finding DS-11. The table listed 19 setting names that appeared
nowhere in the code any more (all `TOGETHER_ANIMATE_*`, `PROACTIVE_*`,
`KNOWLEDGE_MAX_*`, `STORY_ENGINE_BEAT_FACESWAP`, `PORT`, …) and pointed at
four source files that had been deleted. Both halves are mechanical, so both
are checked here instead of being re-verified by hand every few months.

Pure text work: `git grep` over the tracked tree plus a plain read of the
document. No server, no world DB, nothing from `app` is imported.

WHAT IS CHECKED, and where every expected value comes from
-----------------------------------------------------------

A) Every setting name in the tables (`| \\`NAME\\` | … |`, uppercase) occurs
   at least once, as a whole word, in the code: `app/`, `plugins/`,
   `shared/`, `static/`, `docker/`, `queue_cli.py`, `frontend/src`,
   `client3d/src`. The expected answer is "one or more hits" for every name
   — a documented knob nobody reads is a dead end for whoever looks it up.
   `scripts/` is deliberately NOT part of the corpus: a check script may
   mention a name precisely because it is forbidden (`smoke_send_message_intent`
   names `PORT` as an example of an env read), and that must not keep a dead
   entry alive.

B) Every `app/…`, `plugins/…` or `docker/…` path named in the Datei column
   exists on disk. Expected: all of them. This is the `test -f` half of the
   finding — four paths had been deleted with their modules.

C) The two settings the document gained (`server.max_upload_mb`,
   `server.cors_origins`) are still fields of
   `app/core/config_schema.py`. They are config.json settings, not names of
   the A-kind, so A would not see them.

FAILS BEFORE / PASSES AFTER
---------------------------
Confirmed by running A and B against the previous revision of the document
(`git show 74693e4f: (the pinned pre-fix revision — HEAD would compare the file with itself once this is committed) docs/config-defaults.md`) — see the last block of the output:
19 names without a hit and four missing files there, none here.
"""
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DOC = REPO / "docs" / "config-defaults.md"

# Where a setting name may show up. scripts/ is left out on purpose (see A).
CORPUS = ["app", "plugins", "shared", "static", "docker", "queue_cli.py",
          "frontend/src", "client3d/src"]

_failures = []
_checks = 0


def check(label, ok, detail=""):
    global _checks
    _checks += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"   [{detail}]" if detail and not ok else ""))
    if not ok:
        _failures.append(label)


def documented_names(text):
    return re.findall(r"^\| `([A-Z][A-Z0-9_]+)` \|", text, re.M)


def documented_paths(text):
    """Paths in the Datei column of a table row — prose that NAMES a deleted
    module (the header note does, to say it is gone) is not a claim that the
    file exists."""
    rows = [ln for ln in text.splitlines() if ln.startswith("| `")]
    return sorted(set(re.findall(
        r"\b((?:app|plugins|docker)/[A-Za-z0-9_./-]+\.(?:py|sh|yaml|yml))\b",
        "\n".join(rows))))


def names_without_hit(names):
    """The names `git grep -w` finds nowhere in the corpus."""
    if not names:
        return []
    pattern = "|".join(re.escape(n) for n in names)
    out = subprocess.run(["git", "grep", "-howE", pattern, "--"] + CORPUS,
                         cwd=REPO, capture_output=True, text=True).stdout
    found = set(out.split())
    return [n for n in names if n not in found]


def main():
    doc = DOC.read_text(encoding="utf-8")
    names = documented_names(doc)
    paths = documented_paths(doc)

    print(f"A) every documented name occurs in the code ({len(names)} names)")
    dead = names_without_hit(names)
    check("no documented setting is unknown to the code", not dead, str(dead))

    print(f"B) every source file the document names exists ({len(paths)} paths)")
    gone = [p for p in paths if not (REPO / p).exists()]
    check("no Datei column points at a deleted module", not gone, str(gone))

    print("C) the two config.json settings are still in the schema")
    schema = (REPO / "app" / "core" / "config_schema.py").read_text(encoding="utf-8")
    for field in ("max_upload_mb", "cors_origins"):
        check(f"config_schema.py defines {field}", f'"{field}": {{' in schema)
        check(f"docs/config-defaults.md mentions {field}", field in doc)

    print("D) A and B against the PREVIOUS revision (must find what DS-11 "
          "reported)")
    try:
        old = subprocess.run(["git", "show", "74693e4f:docs/config-defaults.md"],
                             cwd=REPO, capture_output=True, text=True,
                             check=True).stdout
    except Exception as e:                                   # pragma: no cover
        check("git show 74693e4f: (the pinned pre-fix revision — HEAD would compare the file with itself once this is committed) docs/config-defaults.md", False, str(e))
    else:
        old_dead = names_without_hit(documented_names(old))
        check("the pre-fix revision documented at least 19 unknown names",
              len(old_dead) >= 19, f"{len(old_dead)}: {old_dead}")
        old_gone = [p for p in documented_paths(old) if not (REPO / p).exists()]
        # At least the 4 modules DS-11 found deleted. Later feature removals
        # delete more modules the old document still names, so this is a
        # floor, not a pin.
        check("the previous revision named at least 4 deleted modules",
              len(old_gone) >= 4, f"{len(old_gone)}: {old_gone}")

    print()
    print(f"{_checks - len(_failures)}/{_checks} checks passed")
    if _failures:
        for f in _failures:
            print(f"  failed: {f}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
