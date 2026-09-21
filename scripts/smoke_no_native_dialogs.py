#!/usr/bin/env python3
"""Lint: the web UIs must not call `window.alert/confirm/prompt`.

Usage:  ./.venv/bin/python scripts/smoke_no_native_dialogs.py

Needs no server, no world DB and no node_modules — it reads source text.

THE RULE (CLAUDE.md, section "Frontend")

    "No `window.prompt/alert/confirm` — build real in-app UI for inputs and
     confirmations."

WHY IT IS A RULE, not a preference.  A native dialog is a modal of the
BROWSER, not of the app: it cannot be styled, it cannot be translated through
`t()`, and it blocks the JavaScript main thread while it is up.  In the /play
grid and in the 3D client's HUD that thread is the render loop, and while the
pointer is locked (the 3D client's normal state) the browser suppresses the
dialog outright — the click then appears to do nothing at all.  The
replacements exist: `frontend/src/components/ConfirmDialog.tsx` for a yes/no
question, `frontend/src/components/PromptDialog.tsx` for one value, and the
inline confirmation strip of `packages/player-ui/src/GalleryPanel.tsx` inside
the player panels.

WHAT COUNTS AS A CALL

Comments and string literals are NOT calls — a docstring may name the thing it
forbids, and `t('Really delete?')` is a translated message, not a dialog.  So
the detector strips `//`, `/* */` comments and '…' / "…" / `…` literals first
and only then looks for a call:

    (?<![\\w.$])(?:window\\.)?(?:alert|confirm|prompt)\\s*\\(

The lookbehind is what keeps the false positives out: a member access like
`props.confirm(` or `hub.prompt(` is somebody else's API, only the bare global
and the explicit `window.` form are the browser's.  `onConfirm(`,
`setConfirmDel(` and `confirmDelete(` differ in case or in the character right
after the word, so none of them matches.

EXPECTED RESULT, derived by hand

Part 1 runs the detector over eleven hand-written snippets whose verdict is
derived from THE RULE above, never recorded from a run — a detector that has
quietly stopped detecting must fail here, not pass everything in part 2.

Part 2 scans the sources.  The expected count is ZERO, in every scanned tree.
That number is not an observation either: the rule admits no exception, so any
find is a defect.  The review of 2026-09-20 (finding UI-7) counted 16 call
sites — 14 `window.confirm` and 2 `window.prompt` — which is why this check
exists; run part 2 against those revisions of the files and it reports 16.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# The TypeScript/JavaScript UI trees the rule covers.
SCAN_DIRS = [
    "frontend/src",
    "packages/player-ui/src",
    "packages/scene-render/src",
    "client3d/src",
]
SUFFIXES = {".ts", ".tsx", ".js", ".jsx", ".mjs"}

CALL_RE = re.compile(r"(?<![\w.$])(?:window\.)?(?:alert|confirm|prompt)\s*\(")


def strip_comments_and_strings(src: str) -> str:
    """Blank out comments and string/template literals, keeping line numbers.

    Every removed character is replaced by a space (newlines survive), so the
    offsets of everything else — and therefore the reported line numbers —
    stay exactly as they are in the file.
    """
    out = list(src)
    i = 0
    n = len(src)
    while i < n:
        c = src[i]
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            while i < n and src[i] != "\n":
                out[i] = " "
                i += 1
        elif c == "/" and i + 1 < n and src[i + 1] == "*":
            while i < n and not (src[i] == "*" and i + 1 < n and src[i + 1] == "/"):
                if src[i] != "\n":
                    out[i] = " "
                i += 1
            for _ in range(2):
                if i < n:
                    out[i] = " "
                    i += 1
        elif c in "'\"`":
            quote = c
            out[i] = " "
            i += 1
            while i < n:
                if src[i] == "\\":
                    out[i] = " "
                    if i + 1 < n and src[i + 1] != "\n":
                        out[i + 1] = " "
                    i += 2
                    continue
                if src[i] == quote:
                    out[i] = " "
                    i += 1
                    break
                if src[i] == "\n" and quote != "`":
                    break  # unterminated single-line literal — stop, stay safe
                if src[i] != "\n":
                    out[i] = " "
                i += 1
        else:
            i += 1
    return "".join(out)


def find_violations(src: str) -> list[tuple[int, str]]:
    """Return (line number, matched text) for every native dialog call."""
    cleaned = strip_comments_and_strings(src)
    hits: list[tuple[int, str]] = []
    for m in CALL_RE.finditer(cleaned):
        line = cleaned.count("\n", 0, m.start()) + 1
        hits.append((line, m.group(0)))
    return hits


# ── Part 1: the detector, against hand-derived verdicts ────────────────────
# "expected" = how many calls THE RULE sees in the snippet, reasoned out here.
SELF_TEST: list[tuple[str, str, int]] = [
    ("bare window.confirm", "if (!window.confirm(t('x'))) return", 1),
    ("bare window.prompt", "const n = window.prompt(t('Name'))", 1),
    ("bare window.alert", "window.alert('boom')", 1),
    # No `window.` prefix — still the browser global.
    ("global confirm", "if (confirm('really?')) go()", 1),
    # Somebody else's method of the same name: a member access, not the global.
    ("member access", "if (!props.confirm(x)) return; hub.prompt(y)", 0),
    # Different word / different next character — not the global either.
    ("camelCase callback", "onConfirm(() => drop()); setConfirmDel(true)", 0),
    ("longer identifier", "void confirmDelete(); void promptForName()", 0),
    # A line comment may name the forbidden thing.
    ("line comment", "// no window.confirm() in this UI\nrun()", 0),
    ("block comment", "/* replaces confirm( and prompt( */\nrun()", 0),
    # Prose inside a translated string is a message, not a dialog.
    ("string literal", "toast(t('Use confirm( never')); note(`prompt( here`)", 0),
    # Two calls on one line are two findings.
    ("two on one line", "confirm('a'); window.alert('b')", 2),
]


def run_self_test() -> int:
    bad = 0
    print("Part 1 — detector self-test")
    for name, snippet, expected in SELF_TEST:
        got = len(find_violations(snippet))
        ok = got == expected
        if not ok:
            bad += 1
        print(f"  [{'ok' if ok else 'FAIL'}] {name}: expected {expected}, got {got}")
    return bad


# ── Part 2: the sources ────────────────────────────────────────────────────
def scan_sources() -> list[str]:
    findings: list[str] = []
    scanned = 0
    for rel in SCAN_DIRS:
        root = REPO / rel
        if not root.is_dir():
            print(f"  (skipped, not present: {rel})")
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix not in SUFFIXES:
                continue
            scanned += 1
            try:
                src = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for line, text in find_violations(src):
                findings.append(f"{path.relative_to(REPO)}:{line}: {text}")
    print(f"  scanned {scanned} source files in {len(SCAN_DIRS)} trees")
    return findings


def main() -> int:
    failures = run_self_test()
    print("\nPart 2 — native dialog calls in the UI sources (expected: 0)")
    findings = scan_sources()
    for f in findings:
        print(f"  [FAIL] {f}")
    if findings:
        failures += len(findings)
    else:
        print("  [ok] no window.alert / confirm / prompt call")

    print("\n" + ("FAILED" if failures else "PASSED")
          + f" — {failures} problem(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
