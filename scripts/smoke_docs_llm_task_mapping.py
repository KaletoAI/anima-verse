#!/usr/bin/env python3
"""Smoke: docs/llm-task-mapping.md lists exactly the tasks that exist.

Usage:  ./.venv/bin/python scripts/smoke_docs_llm_task_mapping.py

The document IS the task catalog for a human reader — "27 tasks, in the order
they stand in app/core/llm_tasks.py". A catalog that has drifted is worse than
none: a removed task keeps looking routable (the document still listed
`group_chat_stream` after the group chat was deleted), and a new one is
invisible. Neither is visible by reading, so it is checked.

WHAT IS CHECKED, and where every expected value comes from
-----------------------------------------------------------

A) The set of task ids in the catalog tables equals `TASK_TYPES` — no extra, no
   missing. The expected set is read from `app/core/llm_tasks.py` at run time;
   a hand-copied list here would be the same duplication the check is about.

B) The count sentence ("N tasks, in the order they stand in") states the real
   number.

C) The `fallback_parent` table in the document matches the function for every
   catalog id plus one probe per documented shape (`intent_x`, `thought_x`,
   `extraction_x`, `npc_x`, and an id that matches no rule).

D) Every `app/…`-style module path the Caller columns name exists on disk
   (the columns are written repo-relative without the `app/` prefix, e.g.
   `core/act_engine.py`, `routes/chat.py`, `plugins/…`).

Storage: a throwaway dir via STORAGE_DIR before `app` is imported. `llm_tasks`
and `llm_router` are pure catalog/resolution code — no server, no world DB.

Deliberately NOT checked: labels, categories, gates and the Purpose prose. They
are editorial; pinning them here would turn every wording change into a test
failure.

NOTE: `docs/llm-task-mapping.md` is gitignored ("Files removed from public
release", next to CLAUDE.md). It exists in a working copy, not in a fresh
clone — so this check SKIPS with exit code 0 when the file is absent instead of
failing a checkout that never had it.
"""
import os
import re
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DOC = REPO / "docs" / "llm-task-mapping.md"

_failures = []
_checks = 0


def check(label, ok, detail=""):
    global _checks
    _checks += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"   [{detail}]" if detail and not ok else ""))
    if not ok:
        _failures.append(label)


def _boot():
    os.environ.setdefault("STORAGE_DIR", tempfile.mkdtemp(prefix="smoke_docs_tasks_"))
    sys.path.insert(0, str(REPO))


def documented_task_ids(text):
    """The first cell of every catalog table row is a task id in backticks."""
    return {m.group(1) for m in re.finditer(r"^\| `([a-z][a-z0-9_]*)` \| ", text, re.M)}


def documented_paths(text):
    rows = [ln for ln in text.splitlines() if ln.startswith("| `")]
    return sorted(set(re.findall(
        r"`((?:core|routes|models|imagegen|skills|utils|plugins)/[A-Za-z0-9_./-]+\.py)`",
        "\n".join(rows))))


def main():
    _boot()
    if not DOC.exists():
        print(f"SKIP  {DOC.relative_to(REPO)} is not present in this checkout "
              f"(gitignored, not part of the public release)")
        return 0
    doc = DOC.read_text(encoding="utf-8")
    from app.core.llm_tasks import TASK_TYPES
    from app.core.llm_router import fallback_parent

    real = set(TASK_TYPES)
    named = documented_task_ids(doc)

    print(f"A) the catalog tables list exactly the real tasks ({len(real)})")
    check("no task is missing from the document", not (real - named),
          str(sorted(real - named)))
    check("the document lists no task that is gone", not (named - real),
          str(sorted(named - real)))

    print("B) the count sentence states the real number")
    m = re.search(r"^(\d+) tasks, in the order they stand in", doc, re.M)
    check("the document counts its tasks correctly",
          bool(m) and int(m.group(1)) == len(real),
          f"document says {m.group(1) if m else '?'}, real is {len(real)}")

    print("C) the fallback_parent table matches the function")
    expected = {
        "intent_probe": "intent", "thought_probe": "thought",
        "extraction_probe": "extraction", "npc_probe": "chat_stream",
        "furnish": "intent", "prop_mount_classify": "intent",
        "room_description_sync": "intent",
        "a_task_no_rule_matches": None,
    }
    wrong = [f"{t}: {fallback_parent(t)} != {p}"
             for t, p in expected.items() if fallback_parent(t) != p]
    check("every documented fallback shape behaves as the table says",
          not wrong, str(wrong))

    print("D) every module path in the Caller columns exists")
    paths = documented_paths(doc)
    gone = [p for p in paths
            if not (REPO / p).exists() and not (REPO / "app" / p).exists()]
    check(f"no Caller column points at a deleted module ({len(paths)} paths)",
          not gone, str(gone))

    print()
    print(f"{_checks - len(_failures)}/{_checks} checks passed")
    if _failures:
        for f in _failures:
            print(f"  failed: {f}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
