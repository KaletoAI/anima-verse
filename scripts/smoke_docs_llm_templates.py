#!/usr/bin/env python3
"""Smoke: docs/llm-templates.md names every LLM template that exists.

Usage:  ./.venv/bin/python scripts/smoke_docs_llm_templates.py

Covers review finding DS-19. The document opened with "catalogs every active
template" and left out 17 of the 50 files under `shared/templates/llm/tasks/`
— a claim of completeness that nothing checked. This is the check.

Pure text work: it reads the template directory and the Markdown file. No
server, no world DB, nothing from `app` is imported.

WHAT IS CHECKED, and where every expected value comes from
-----------------------------------------------------------

A) Every `*.md` under `shared/templates/llm/tasks/` appears in the document,
   named as a file (`<name>.md` inside backticks). The expected set is the
   directory listing — the files ARE the specification; a hand-copied list
   here would be the very duplication the finding is about.

B) The same for `shared/templates/llm/chat/`.

C) The other way round: every `<name>.md` the document names as a template
   exists — in `shared/templates/llm/{tasks,chat,skills}/` or in a package's
   own `plugins/*/templates/llm/{tasks,chat,skills}/`, because
   `prompt_templates.template_search_dirs` searches the package first. This
   half is a forward guard with no before-state: it has to follow the
   symlinked packages, or it would declare `instagram_caption.md` and
   `relationship_summary_romantic_interests.md` dead although both live in a
   package (that is how the second one was almost deleted from the document).

D) `shared/templates/llm/` holds no directory besides `tasks`, `chat` and
   `skills` — the Layout block in the document names exactly those three, so
   a fourth one would make it wrong without any row being wrong.

Deliberately NOT checked: the Task and Caller columns. A caller moves with
every refactor; pinning it here would make this check a maintenance burden
rather than a guard. What it guards is the one thing the document claims
about itself — that nothing is missing.

FAILS BEFORE / PASSES AFTER
---------------------------
Confirmed by running part A against the previous revision of the document
(`git show 74693e4f:docs/llm-templates.md` — a PINNED commit, never `HEAD:`, which
would compare the file with itself once this revision is committed) — see the last block of the output:
17 templates are missing there.
"""
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LLM_DIR = REPO / "shared" / "templates" / "llm"
DOC = REPO / "docs" / "llm-templates.md"

_failures = []
_checks = 0


def check(label, ok, detail=""):
    global _checks
    _checks += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"   [{detail}]" if detail and not ok else ""))
    if not ok:
        _failures.append(label)


def template_files(sub):
    d = LLM_DIR / sub
    return sorted(p.name for p in d.glob("*.md")) if d.is_dir() else []


def named_in(text):
    """Every `<something>.md` the document mentions inside backticks."""
    return set(re.findall(r"`([A-Za-z0-9_./-]+\.md)`", text))


def known_template_names():
    """Every template file name the loader could find, shared + packages."""
    names = set()
    for sub in ("tasks", "chat", "skills"):
        names |= {p.name for p in (LLM_DIR / sub).glob("*.md")} if (LLM_DIR / sub).is_dir() else set()
    for pkg in (REPO / "plugins").glob("*/templates/llm/*"):
        if pkg.is_dir():
            names |= {p.name for p in pkg.glob("*.md")}
    return names


def missing_from(text, sub):
    doc_names = {n.rsplit("/", 1)[-1] for n in named_in(text)}
    return [f for f in template_files(sub) if f not in doc_names]


def main():
    doc = DOC.read_text(encoding="utf-8")

    print(f"A) every tasks/ template is named ({len(template_files('tasks'))} files)")
    miss = missing_from(doc, "tasks")
    check("no tasks/ template missing from docs/llm-templates.md", not miss, str(miss))

    print(f"B) every chat/ template is named ({len(template_files('chat'))} files)")
    miss = missing_from(doc, "chat")
    check("no chat/ template missing from docs/llm-templates.md", not miss, str(miss))

    print("C) every template the document names exists")
    known = known_template_names()
    # Only bare file names are template references; a path like
    # "docs/llm-task-mapping.md" is a cross-reference, not a template.
    ghosts = sorted(n for n in named_in(doc) if "/" not in n and n not in known)
    check("no row points at a deleted template", not ghosts, str(ghosts))

    print("D) the Layout block still describes the directory")
    subdirs = sorted(p.name for p in LLM_DIR.iterdir() if p.is_dir())
    check("shared/templates/llm/ holds exactly chat, skills, tasks",
          subdirs == ["chat", "skills", "tasks"], str(subdirs))

    print("E) part A against the PREVIOUS revision of the document "
          "(must find the gap the finding reported)")
    try:
        old = subprocess.run(["git", "show", "74693e4f:docs/llm-templates.md"],
                             cwd=REPO, capture_output=True, text=True,
                             check=True).stdout
    except Exception as e:                                   # pragma: no cover
        check("git show 74693e4f:docs/llm-templates.md (pinned pre-fix revision)",
              False, str(e))
    else:
        old_missing = missing_from(old, "tasks")
        check("the previous revision was missing 17 tasks/ templates",
              len(old_missing) == 17, f"{len(old_missing)}: {old_missing}")

    print()
    print(f"{_checks - len(_failures)}/{_checks} checks passed")
    if _failures:
        for f in _failures:
            print(f"  failed: {f}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
