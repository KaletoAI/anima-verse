#!/usr/bin/env python3
"""Smoke: the dead periodic relationship-summary job stays gone, the live task stays.

Usage:
    ./.venv/bin/python scripts/smoke_relationship_summary_job_gone.py

Pure text + AST scan of the tracked tree. No app import, no server, no world DB,
no storage — so nothing here can write into worlds/demo.

BACKGROUND (2026-09-21)
-----------------------
``app/core/relationship_summary.py`` held a background-queue handler that
condensed relationship memories into a narrative summary. It was registered in
the server lifespan, but NOTHING ever submitted the task type
``relationship_summary`` to the background queue, and the handler bailed out on
a missing ``user_id`` anyway. Everything hanging off it was dead with it: the
prompt template ``tasks/relationship_summary_pair.md``, the preview driver
``_drive_relationship_summary_pair``, the admin field
``relationships.summary_interval_minutes`` with its env bridge
(``RELATIONSHIP_SUMMARY_*``), the character-template flag
``relationship_summary_enabled`` and the memory meta keys
``summary``/``summary_stale``.

What did NOT go is the LLM task of the same name: after every chat exchange
``app/core/chat_engine.py`` rates the sentiment of both sides with
``tasks/relationship_summary.md``, gated by ``relationships.summary_enabled``.
Deleting "the relationship summary" as one thing would take that with it, which
is why this guard has a positive half.

WHAT IS CHECKED, and where every expected value comes from
----------------------------------------------------------

A) ``app/core/relationship_summary.py`` does not exist. Expected: absent — the
   module was deleted whole, it had no caller left.

B) None of the four dead names occurs anywhere in ``app/``,
   ``shared/templates/``, ``docs/``, ``README.md``, ``frontend/src/`` or
   ``static/admin/``:
       relationship_summary_pair      (template + preview driver)
       summary_interval_minutes       (admin field of the job)
       relationship_summary_enabled   (character-template feature flag)
       RELATIONSHIP_SUMMARY_          (the env bridge, all three names)
   Expected: zero hits for each. ``scripts/`` is deliberately NOT in the corpus
   — this file names all four on purpose, and
   ``scripts/analyze_a2_logs.py`` classifies HISTORIC log lines that still
   carry the old prompt.

C) ``shared/templates/llm/tasks/relationship_summary_pair.md`` is gone, while
   ``shared/templates/llm/tasks/relationship_summary.md`` still exists — the
   live task renders that one on every exchange, ``prompt_templates`` would
   raise without it.

D) ``relationship_summary`` is still a key of ``TASK_TYPES`` in
   ``app/core/llm_tasks.py`` (read from the AST, the module is not imported).
   Expected: present — without a catalog entry the task has no routing, no
   priority and no admin row.

E) ``app/core/config_schema.py`` still declares the field ``summary_enabled``
   under the section ``relationships`` and no longer declares
   ``summary_interval_minutes`` there. Expected: exactly that pair — the
   switch is kept (it gates the live sentiment call in chat_engine), the
   interval belonged to the removed job.

Exit code 0 = all checks passed, 1 = at least one failed.
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FAILED = []


def check(label: str, actual, expected) -> None:
    ok = actual == expected
    print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    if not ok:
        print(f"        expected: {expected!r}")
        print(f"        actual:   {actual!r}")
        FAILED.append(label)


# --------------------------------------------------------------------------
# Corpus
# --------------------------------------------------------------------------
CORPUS_DIRS = ["app", "shared/templates", "docs", "frontend/src", "static/admin"]
CORPUS_FILES = ["README.md"]
SKIP_DIRS = {"node_modules", "__pycache__", ".git", "dist"}
TEXT_SUFFIXES = {".py", ".md", ".json", ".ts", ".tsx", ".js", ".jsx", ".css",
                 ".html", ".yaml", ".yml", ".txt"}


def corpus_files():
    for rel in CORPUS_FILES:
        p = ROOT / rel
        if p.is_file():
            yield p
    for rel in CORPUS_DIRS:
        base = ROOT / rel
        if not base.is_dir():
            continue
        for p in base.rglob("*"):
            if not p.is_file() or p.suffix not in TEXT_SUFFIXES:
                continue
            if any(part in SKIP_DIRS for part in p.parts):
                continue
            yield p


FILES = sorted(set(corpus_files()))


def hits(needle: str):
    out = []
    for p in FILES:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if needle in text:
            for i, line in enumerate(text.splitlines(), 1):
                if needle in line:
                    out.append(f"{p.relative_to(ROOT)}:{i}")
    return out


print("A) the dead module file is gone")
check("app/core/relationship_summary.py absent",
      (ROOT / "app" / "core" / "relationship_summary.py").exists(), False)

print("B) no dead name left in app/ shared/templates/ docs/ README.md "
      "frontend/src/ static/admin/")
print(f"   (corpus: {len(FILES)} files)")
for name in ("relationship_summary_pair", "summary_interval_minutes",
             "relationship_summary_enabled", "RELATIONSHIP_SUMMARY_"):
    check(f"no occurrence of {name}", hits(name), [])

print("C) the templates: the pair prompt is gone, the live prompt stays")
tasks = ROOT / "shared" / "templates" / "llm" / "tasks"
check("relationship_summary_pair.md absent",
      (tasks / "relationship_summary_pair.md").exists(), False)
check("relationship_summary.md present",
      (tasks / "relationship_summary.md").exists(), True)

print("D) the live task is still in the llm_tasks catalog")


def _dict_keys(node):
    return [k.value for k in node.keys
            if isinstance(k, ast.Constant) and isinstance(k.value, str)]


def _module_dict(path: Path, name: str):
    """The dict literal assigned to `name` at module level — AST only, the
    module is never imported (plain `x = {...}` and annotated `x: T = {...}`)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        for tgt in targets:
            if isinstance(tgt, ast.Name) and tgt.id == name \
                    and isinstance(node.value, ast.Dict):
                return node.value
    return None


def _task_types_keys():
    node = _module_dict(ROOT / "app" / "core" / "llm_tasks.py", "TASK_TYPES")
    return _dict_keys(node) if node is not None else []


catalog = _task_types_keys()
check("TASK_TYPES was found at all", len(catalog) > 10, True)
check("relationship_summary is a catalog task",
      "relationship_summary" in catalog, True)

print("E) config_schema keeps the switch and dropped the interval")


def _value_for(dict_node, key):
    for k, v in zip(dict_node.keys, dict_node.values):
        if isinstance(k, ast.Constant) and k.value == key:
            return v
    return None


def _relationship_fields():
    sections = _module_dict(ROOT / "app" / "core" / "config_schema.py", "SECTIONS")
    if sections is None:
        return None
    sec = _value_for(sections, "relationships")
    if not isinstance(sec, ast.Dict):
        return None
    fields = _value_for(sec, "fields")
    if not isinstance(fields, ast.Dict):
        return None
    return _dict_keys(fields)


fields = _relationship_fields()
check("the relationships section was found", fields is not None, True)
check("summary_enabled is still a field", "summary_enabled" in (fields or []), True)
check("summary_interval_minutes is not a field any more",
      "summary_interval_minutes" in (fields or []), False)

print()
if FAILED:
    print(f"{len(FAILED)} check(s) FAILED: " + ", ".join(FAILED))
    sys.exit(1)
print("all checks passed")
