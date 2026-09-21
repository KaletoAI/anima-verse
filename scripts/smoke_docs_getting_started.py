#!/usr/bin/env python3
"""Smoke: docs/getting-started-new-world.md still describes the real UI.

Usage:  ./.venv/bin/python scripts/smoke_docs_getting_started.py

The walk-through tells a newcomer which button to press. Every label in it is
therefore a claim about a string that exists somewhere in the code, and a
renamed field turns the document into a maze with no way to notice. This check
compares the document against the sources the UI is built from.

Pure text work: the document, `app/core/config_schema.py`, `app/core/llm_router.py`,
`app/core/users.py`, the character templates and the two frontend/package source
trees are read and compared. No server, no world DB, nothing from ``app`` is
imported.

WHAT IS CHECKED, and where every expected value comes from
-----------------------------------------------------------

A) UI labels. Every **bold** span of the document that looks like a label (one
   to five words, starts uppercase, no sentence punctuation) must occur as a
   quoted string in the UI sources: the `t('…')` strings and tab labels under
   `frontend/src` and `packages/*/src`, the `"label"` values of
   `app/core/config_schema.py`, and the character templates. Step headings (a
   bold span opening a numbered list item) are prose, not labels, and are
   skipped — as is `Game-Admin`, which is the name of a surface and is checked
   as the route `/game-admin` instead.

B) Admin sections. The sections the document sends the reader to must be
   `label` values of the top-level sections in `config_schema.py`.

C) The LLM-routing pages. The document says routing has three pages; expected
   value = the `pages` list of the `llm_routing` section.

D) Character templates. The document names the templates a new character can be
   created from; expected value = the `label` of every `shared/templates/character/*.json`,
   and which of them carry `features.playable_avatar`.

E) The unrouted-task rule. `fallback_parent()` in `app/core/llm_router.py` is the
   one place that rule lives; every parent and every specially-mapped task it
   names must appear in the document.

F) The bootstrap-admin line the reader greps for must still be the line the
   server logs (`app/core/users.py`).

G) The two outdated routing screenshots must still be on disk, since the
   document explains what they show.
"""
import glob
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DOC = REPO / "docs" / "getting-started-new-world.md"
SCHEMA = REPO / "app" / "core" / "config_schema.py"
ROUTER = REPO / "app" / "core" / "llm_router.py"
USERS = REPO / "app" / "core" / "users.py"
TEMPLATES = REPO / "shared" / "templates" / "character"

# Names of SURFACES, not of widgets — they have no string in the sources and
# are verified through their route instead.
SURFACE_NAMES = {"Game-Admin", "Player UI", "Server Admin"}

_failures = []
_checks = 0


def check(label, ok, detail=""):
    global _checks
    _checks += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"   [{detail}]" if detail and not ok else ""))
    if not ok:
        _failures.append(label)


def ui_corpus():
    parts = []
    for pattern in ("frontend/src/**/*.ts", "frontend/src/**/*.tsx",
                    "packages/*/src/**/*.ts", "packages/*/src/**/*.tsx",
                    "shared/templates/character/*.json"):
        for f in glob.glob(str(REPO / pattern), recursive=True):
            parts.append(Path(f).read_text(encoding="utf-8", errors="replace"))
    parts.append(SCHEMA.read_text(encoding="utf-8"))
    return "\n".join(parts)


def schema_sections():
    src = SCHEMA.read_text(encoding="utf-8")
    # A section may open with comment lines (llm_simple does), so allow them
    # between the key and its label.
    return dict(re.findall(
        r'\n    "([a-z0-9_]+)": \{\n(?:\s*#[^\n]*\n)*\s*"label": "([^"]*)"', src))


def routing_pages():
    src = SCHEMA.read_text(encoding="utf-8")
    i = src.find('\n    "llm_routing": {')
    j = src.find('\n    "lanes": {')
    seg = src[i:j if j > i else len(src)]
    return re.findall(r'"id": "([a-z_]+)",\s*\n\s*"label": "([^"]+)"', seg)


def bold_labels(doc):
    """Bold spans that are UI labels, not prose."""
    step_headings = set(re.findall(r"^\s*\d+\.\s+\*\*([^*\n]+)\*\*", doc, re.M))
    out = set()
    for span in re.findall(r"\*\*([^*\n]{1,45})\*\*", doc):
        if span in step_headings:
            continue
        for part in re.split(r"\s*→\s*", span):
            part = part.strip()
            if not re.fullmatch(r"[A-Z][A-Za-z0-9 ()/&.\-]*", part):
                continue
            if part.endswith(".") or len(part.split()) > 5:
                continue
            if part in SURFACE_NAMES:
                continue
            out.add(part)
    return out


def main():
    doc = DOC.read_text(encoding="utf-8")

    print("A) every bold UI label exists as a string in the sources")
    corpus = ui_corpus()
    labels = bold_labels(doc)
    check(f"the document names UI labels ({len(labels)})", len(labels) >= 30)
    missing = sorted(l for l in labels
                     if f"'{l}'" not in corpus and f'"{l}"' not in corpus)
    check("every bold UI label is a real string", not missing, str(missing))

    print("B) the admin sections it sends the reader to exist")
    sections = set(schema_sections().values())
    named = {"Server", "LLM Providers", "LLM Models (Simple)",
             "LLM Routing (Advanced)", "Media Generation", "Text-to-Speech",
             "Game calendar"}
    check("the document still names these sections",
          all(n in doc for n in named), str(sorted(n for n in named if n not in doc)))
    unknown = sorted(n for n in named if n not in sections)
    check("every named section is a config_schema section", not unknown,
          f"{unknown} not in {sorted(sections)}")

    print("C) LLM Routing has the three pages the document describes")
    pages = routing_pages()
    check(f"llm_routing declares 3 pages ({len(pages)})", len(pages) == 3, str(pages))
    for _id, label in pages:
        check(f"the document names the '{label}' page",
              re.search(r"\*\*%s\*\*" % re.escape(label), doc) is not None)

    print("D) the character templates and which of them are playable")
    tmpl = {}
    for f in sorted(TEMPLATES.glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        flag = d.get("features", {}).get("playable_avatar")
        tmpl[f.stem] = (d.get("label", ""), flag if isinstance(flag, bool) else None)
    check(f"the repo ships character templates ({len(tmpl)})", len(tmpl) >= 4, str(sorted(tmpl)))
    for stem, (label, _playable) in tmpl.items():
        check(f"the document names the template '{label}'", label in doc, stem)
    playable = sorted(s for s, (_l, p) in tmpl.items() if p is True)
    # Only the templates that DECLARE the flag false are NPC-only; a template
    # without a `features` block (the shared base) is not offered at all.
    not_playable = sorted(s for s, (_l, p) in tmpl.items() if p is False)
    check("the document names every playable template id",
          all(f"`{s}`" in doc for s in playable), str(playable))
    check("the document names every NPC-only template id",
          all(f"`{s}`" in doc for s in not_playable), str(not_playable))

    print("E) the unrouted-task rule matches fallback_parent()")
    src = ROUTER.read_text(encoding="utf-8")
    body = src[src.find("def fallback_parent("):]
    body = body[:body.find("\ndef ", 1)]
    parents = re.findall(r'for parent in \(([^)]*)\)', body)
    parents = re.findall(r'"([a-z_]+)"', parents[0]) if parents else []
    mapped = re.findall(r'if task in \(([^)]*)\)', body)
    mapped = re.findall(r'"([a-z_]+)"', mapped[0]) if mapped else []
    check(f"fallback_parent names parent prefixes ({parents})", len(parents) == 3)
    for p in parents:
        check(f"the document names the '{p}' fallback", f"`{p}_*`" in doc or f"`{p}`" in doc)
    check(f"the document names the intent-mapped tasks ({mapped})",
          all(f"`{t}`" in doc for t in mapped),
          str([t for t in mapped if f"`{t}`" not in doc]))
    check("the document names the npc_* -> chat_stream rule",
          "`npc_*`" in doc and "`chat_stream`" in doc)

    print("F) the bootstrap-admin line is still what the server logs")
    log_line = USERS.read_text(encoding="utf-8")
    check("users.py still logs '=== BOOTSTRAP ADMIN CREATED ==='",
          "=== BOOTSTRAP ADMIN CREATED ===" in log_line)
    check("the document greps for BOOTSTRAP ADMIN",
          'grep "BOOTSTRAP ADMIN"' in doc)

    print("G) the two outdated routing screenshots are still there")
    shots = sorted((REPO / "docs" / "images" / "getting-started").glob("llm-routing-*.png"))
    check(f"two llm-routing screenshots on disk ({len(shots)})", len(shots) == 2,
          str([s.name for s in shots]))
    check("the document says they show the older layout",
          "llm-routing-*.png" in doc and "OLDER" in doc)

    print()
    print(f"{_checks - len(_failures)}/{_checks} checks passed")
    if _failures:
        for f in _failures:
            print(f"  failed: {f}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
