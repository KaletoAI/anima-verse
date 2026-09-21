#!/usr/bin/env python3
"""Smoke run: no upload route reads a request body without a cap (SEC-7).

Usage:
    ./.venv/bin/python scripts/smoke_upload_call_sites.py

A pure SOURCE check (AST) — it imports nothing of the app, opens no DB, needs
no server. That is the point: the finding is not a behaviour of one handler
but a habit spread over many, and the only way to keep it fixed is to check
every call site at once.

The finding under test (review 2026-09-20, security.md SEC-7, part 1)
---------------------------------------------------------------------------
``contents = await file.read()`` reads the WHOLE uploaded body into memory and
writes it to disk. A single request could therefore fill the world's storage,
and several routes only ever checked the size AFTER the bytes were already in
RAM — which is not a cap, it is a report. The fix is
``app.core.upload_limits.read_upload_capped``, which stops at the cap while
reading, plus ``guard_content_length`` before the multipart parser runs.

What is checked, derived by hand from the source
---------------------------------------------------------------------------
[1] Nowhere under app/ is there an ``await <something>.read()`` with NO size
    argument, except:
      * ``upload_limits.read_upload_capped`` itself, which reads in chunks
        (``await file.read(_CHUNK)`` — it has an argument, so it never
        matches anyway); the module is skipped for clarity.
      * the files in KNOWN_UNCAPPED below — empty today. An entry is printed
        as a warning, never as a pass, so a documented offender still shows
        up on every run.
    A new uncapped read anywhere else fails this check.

[2] The upload route files use the shared helper: each of
    app/routes/{world,characters,inventory,admin_settings,prop_variants}.py
    must call ``read_upload_capped`` at least once, and no longer contain a
    bare ``await ....read()``.

[3] One ceiling for model uploads: no file under app/routes/ defines its own
    ``100 * 1024 * 1024`` constant any more — the number lives in
    ``upload_limits.MODEL_UPLOAD_MAX_BYTES``. Same KNOWN list applies.

Running this against the pre-fix tree (``git archive HEAD app``) reports 15
uncapped reads — 9 in world.py, 4 in characters.py (the model upload reads a
texture too), 1 in inventory.py, 1 in admin_settings.py, 1 in
prop_variants.py — plus the two local 100-MB constants in world.py and one
each in characters.py and prop_variants.py.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

#: Empty on purpose: every upload site under app/ goes through the helper.
#: An entry here would mean a site that still buffers the whole body — it is
#: printed as a warning, never as a pass, so the list documents debt instead
#: of hiding it.
KNOWN_UNCAPPED: set[str] = set()

#: Same for a file that still carries its own 100-MB model ceiling instead of
#: upload_limits.MODEL_UPLOAD_MAX_BYTES.
KNOWN_OWN_MODEL_CAP: set[str] = set()

FAILED: list[str] = []
WARNED: list[str] = []


def check(name, got, want):
    ok = got == want
    print(f"  [{'OK  ' if ok else 'FAIL'}] {name}"
          f"{'' if ok else f' — got {got!r}, want {want!r}'}")
    if not ok:
        FAILED.append(name)


def uncapped_reads(path: Path) -> list[int]:
    """Line numbers of ``await <expr>.read()`` calls without an argument."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    hits: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Await):
            continue
        call = node.value
        if not isinstance(call, ast.Call):
            continue
        func = call.func
        if (isinstance(func, ast.Attribute) and func.attr == "read"
                and not call.args and not call.keywords):
            hits.append(node.lineno)
    return hits


def own_model_cap(path: Path) -> list[int]:
    """Line numbers of a literal ``100 * 1024 * 1024`` assignment."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    hits: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        src = ast.unparse(node.value)
        if src.replace(" ", "") == "100*1024*1024":
            hits.append(node.lineno)
    return hits


SOURCES = sorted(p for p in (REPO / "app").rglob("*.py")
                 if "__pycache__" not in p.parts)

print("\n[1] no uncapped `await ....read()` under app/")
offenders: dict[str, list[int]] = {}
for path in SOURCES:
    rel = str(path.relative_to(REPO))
    if rel == "app/core/upload_limits.py":
        continue
    hits = uncapped_reads(path)
    if hits:
        offenders[rel] = hits

new_offenders = {k: v for k, v in offenders.items() if k not in KNOWN_UNCAPPED}
for rel, lines in sorted(offenders.items()):
    if rel in KNOWN_UNCAPPED:
        WARNED.append(f"{rel}:{lines} (known, outside this file set)")
check("no NEW uncapped read", new_offenders, {})

print("\n[2] the upload route files use the shared helper")
for name in ("world", "characters", "inventory", "admin_settings",
             "prop_variants"):
    rel = f"app/routes/{name}.py"
    text = (REPO / rel).read_text(encoding="utf-8")
    check(f"{rel} calls read_upload_capped",
          "read_upload_capped(" in text, True)
    check(f"{rel} has no bare await .read()",
          uncapped_reads(REPO / rel), [])

print("\n[3] one ceiling for model uploads")
own: dict[str, list[int]] = {}
for path in sorted((REPO / "app" / "routes").rglob("*.py")):
    rel = str(path.relative_to(REPO))
    hits = own_model_cap(path)
    if hits:
        own[rel] = hits
new_own = {k: v for k, v in own.items() if k not in KNOWN_OWN_MODEL_CAP}
for rel, lines in sorted(own.items()):
    if rel in KNOWN_OWN_MODEL_CAP:
        WARNED.append(f"{rel}:{lines} (known own 100 MB constant)")
check("no route file carries its own 100 MB model cap", new_own, {})
check("upload_limits defines the shared one",
      "MODEL_UPLOAD_MAX_BYTES = 100 * 1024 * 1024"
      in (REPO / "app/core/upload_limits.py").read_text(encoding="utf-8"), True)

print()
for line in WARNED:
    print(f"  warn {line}")
if FAILED:
    print(f"\nFAILED ({len(FAILED)}): " + ", ".join(FAILED))
    sys.exit(1)
print("\nall checks passed")
