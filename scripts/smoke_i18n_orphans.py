#!/usr/bin/env python3
"""Smoke: every key in shared/languages/de.json has a live English source.

Usage:  ./.venv/bin/python scripts/smoke_i18n_orphans.py

WHY THIS EXISTS
---------------
``shared/languages/de.json`` is a flat map ``{"English source": "deutsche
Uebersetzung"}``. The key IS the English string as it stands in the code, so a
key without a source string is dead weight: nobody ever looks it up, and it
quietly suggests that the surface it once belonged to is translatable. Two
ways keys go stale:

  * a React/Python string is reworded or its feature is deleted — the old key
    stays behind;
  * a string is written for one of the PYTHON-RENDERED ADMIN PAGES
    (/admin/settings, /admin/users, /admin/llm-stats, /admin/models,
    /admin/agent-loop, /admin/templates, /logs/*, /dashboard) or for the
    config schema. Those pages are ENGLISH-ONLY by project rule and have NO
    translation layer at all: ``static/admin/*.js`` renders its literals raw
    and the page builders in app/routes/{admin,admin_settings,dashboard,logs}.py
    emit theirs raw too. A de.json key for such a string is never read.

THE SOURCE SET — where a string literal legitimately justifies a de.json key
---------------------------------------------------------------------------
Derived by hand from the two consumers of the map:

  1. React ``t()`` from ``useI18n()`` (packages/player-ui/src/I18nProvider.tsx):
     looks the English source up in the map the SPA fetched from
     ``GET /i18n/translations/<lang>``. Its argument is often a variable fed
     from a label table in the same module (``t(VIEW_LABELS[v])``,
     ``t(field.label)``, ``t(mood)``), so ANY string literal in
     frontend/src, packages/*/src and client3d/src counts as a source.
  2. Python ``t(en, lang)`` from app/core/i18n.py: the same map, server side.
     Callers pass literals directly and also hand raw English strings to the
     React clients, which then translate them (``t(p.message)``,
     ``t(data.slot_labels[slot])``). So string literals in app/ and plugins/
     count — EXCEPT in the English-only files listed above.
  3. Data files whose string VALUES are rendered through ``t()``:
     shared/config/*.json (mood ids — see app/routes/shared_lists.py),
     shared/templates/**.json (character template field labels/descriptions,
     rendered by TemplateField), shared/prompt_filters/*.json, and the
     plugin manifests (plugins/*/plugin.yaml, including the symlinked private
     packs under ../anima-verse-packs/packs, which ship no de.json of their
     own — their strings can only be translated through this file).

NOT a source, on purpose: static/admin/*, static/game_admin/* (the built
bundle — a copy, never an origin), app/routes/admin.py, admin_settings.py,
dashboard.py, logs.py, app/core/config_schema.py, docs/, development_instructions/
and scripts/.

HOW A KEY IS MATCHED
--------------------
Python literals are taken from the AST (docstrings excluded — a docstring is
prose, not a UI string; that is what kept the dead key "Assignments" alive).
``a + b`` of two constants is folded, adjacent literals are joined by the
parser itself. TS/TSX literals are extracted by regex for '…', "…" and `…`
with their escapes resolved; because prettier wraps long strings, a TS file
additionally gets a fallback haystack in which literal seams (``' + '``,
``' '``) are removed and whitespace is collapsed. JSON/YAML contribute every
string they contain.

PLACEHOLDERS: React interpolates by hand —
``t('Floor {n}').replace('{n}', String(level))`` (client3d/src/hud/Hud.tsx) —
so the braces stand VERBATIM in the source literal and a plain string match is
exactly right. A template literal would carry ``${…}`` into the key and could
never be looked up; check B asserts no key contains ``${``.

WHAT IS CHECKED, with the expected values derived by hand
---------------------------------------------------------
A) SELF-TEST of the extractor, against six hand-written snippets whose
   expected literal sets are written out here, not recorded from a run:
     py  a function with a docstring whose body is ``return t("Hello")``
         -> {"Hello"}, and NOT the docstring — the discriminating case
     py  ``L = ["A" "B", "C" + "D"]``  -> {"AB", "CD"} (implicit join, fold)
     py  ``# "Comment"``               -> {} (a comment is no source)
     ts  ``const a = 'It\\'s'``        -> {"It's"} (escape resolved)
     ts  ``t("Floor {n}")``            -> {"Floor {n}"} (braces verbatim)
     ts  ``t('one ' +\n  'two')``      -> the seam fallback finds "one two"
B) no de.json key contains ``${`` (see PLACEHOLDERS above).
C) POSITIVE CONTROL: the key "The new password must be at least 8 characters
   long." is present in de.json and found in
   frontend/src/player/AvatarSettingsPanel.tsx, where it is a literal inside a
   ``t(...)`` call. A scan that cannot find it is broken, not clean.
   NEGATIVE CONTROL: a fake key is injected into the map in memory and MUST be
   reported as an orphan.
D) THE GUARD: no orphans. Exit code 1 lists them.
E) FAILS BEFORE / PASSES AFTER: the same scan is run against the de.json of the
   PINNED revision 8bc27a85 (the last commit before this guard landed). That map
   still carried the 66 keys this guard found, among them the config-schema
   switch "Analyse sentiment after conversations" — an /admin/settings string
   that never had a translation layer. Asserted as ">= 60" and by naming that
   one key, so the proof survives later edits instead of pinning a count that
   rots. (Never ``HEAD:`` — that becomes the fixed state the moment the cleanup
   is committed and the proof would compare the file with itself.)

Runs without a server and without a world DB — it imports nothing from app and
only reads files, so it opens no database at all.
"""
import ast
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PACKS = REPO.parent / "anima-verse-packs" / "packs"
DE_JSON = REPO / "shared" / "languages" / "de.json"

# ---------------------------------------------------------------- source set

# English-only surfaces: rendered raw, no t() anywhere near them.
NON_SOURCE_PY = {
    "app/routes/admin.py",            # /admin/models page builder
    "app/routes/admin_settings.py",   # /admin/settings, /admin/users, /admin/llm-stats,
                                      # /admin/agent-loop, /admin/templates page builders
    "app/routes/dashboard.py",        # /dashboard page builder
    "app/routes/logs.py",             # /logs/* page builders
    "app/core/config_schema.py",      # labels/descriptions rendered raw by static/admin/settings.js
}

SOURCE_TREES = [
    ("frontend/src", {".ts", ".tsx"}),
    ("packages", {".ts", ".tsx"}),
    ("client3d/src", {".ts", ".tsx"}),
    ("app", {".py"}),
    ("plugins", {".py", ".yaml", ".yml", ".json"}),
    ("shared/config", {".json"}),
    ("shared/templates", {".json"}),
    ("shared/prompt_filters", {".json"}),
    ("shared/rules", {".json"}),
    ("shared/items", {".json"}),
]
PACK_EXTS = {".py", ".yaml", ".yml", ".json", ".ts", ".tsx"}

# Keys whose only source the scan cannot see. Each entry names the real call
# site, is re-checked by hand when it is added, and stays SHORT — a long
# whitelist means the scan is wrong, not the keys.
WHITELIST: dict = {
    # (empty — every remaining key resolves to a source file)
}

# ------------------------------------------------------------- extraction

_TS_STRING = re.compile(
    r"'((?:[^'\\\n]|\\.)*)'"
    r"|\"((?:[^\"\\\n]|\\.)*)\""
    r"|`((?:[^`\\]|\\.)*)`",
    re.S,
)
_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", "'": "'", '"': '"', "`": "`", "/": "/"}
_SEAM = re.compile(r"['\"`]\s*\+?\s*['\"`]")
_WS = re.compile(r"\s+")


def _unescape(raw: str) -> str:
    out = []
    i = 0
    while i < len(raw):
        c = raw[i]
        if c == "\\" and i + 1 < len(raw):
            nxt = raw[i + 1]
            out.append(_ESCAPES.get(nxt, "\\" + nxt))
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def ts_literals(text: str) -> set:
    """Every string literal of a TS/TSX source, escapes resolved."""
    out = set()
    for m in _TS_STRING.finditer(text):
        raw = m.group(1) if m.group(1) is not None else (
            m.group(2) if m.group(2) is not None else m.group(3))
        if raw:
            out.add(_unescape(raw))
    return out


def ts_seam_haystack(text: str) -> str:
    """Whitespace-collapsed text with literal seams removed.

    Recovers a long string prettier wrapped across lines: ``'one ' + 'two'``
    and ``'one ' 'two'`` both collapse to ``one two``.
    """
    return _WS.sub(" ", _SEAM.sub("", text.replace('\\"', '"').replace("\\'", "'")))


def _fold(node):
    """Constant-fold a string expression: literal, or literal + literal."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _fold(node.left), _fold(node.right)
        if left is not None and right is not None:
            return left + right
    return None


def py_literals(text: str) -> set:
    """Every string literal of a Python source EXCEPT docstrings."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return set()
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", None)
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                docstrings.add(id(body[0].value))
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp):
            folded = _fold(node)
            if folded:
                out.add(folded)
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in docstrings:
                continue
            if node.value:
                out.add(node.value)
    return out


def _walk_data(obj, out: set) -> None:
    if isinstance(obj, str):
        if obj:
            out.add(obj)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str) and k:
                out.add(k)
            _walk_data(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _walk_data(v, out)


def json_literals(text: str) -> set:
    out: set = set()
    try:
        _walk_data(json.loads(text), out)
    except Exception:
        pass
    return out


def yaml_literals(text: str) -> set:
    out: set = set()
    try:
        import yaml
    except Exception:                                        # pragma: no cover
        return out
    try:
        for doc in yaml.safe_load_all(text):
            _walk_data(doc, out)
    except Exception:
        pass
    return out


# ------------------------------------------------------------------ scan

def source_files():
    files = []
    for base, exts in SOURCE_TREES:
        root = REPO / base
        if not root.exists():
            continue
        for p in sorted(root.rglob("*")):
            if not p.is_file() or p.suffix not in exts:
                continue
            if "node_modules" in p.parts or "__pycache__" in p.parts:
                continue
            rel = p.relative_to(REPO).as_posix()
            if rel in NON_SOURCE_PY:
                continue
            files.append((rel, p))
    if PACKS.exists():
        for p in sorted(PACKS.rglob("*")):
            if p.is_file() and p.suffix in PACK_EXTS and "__pycache__" not in p.parts:
                files.append(("packs/" + p.relative_to(PACKS).as_posix(), p))
    return files


def build_index():
    """{literal -> first file that holds it} plus the TS seam haystacks."""
    index = {}
    haystacks = []
    for rel, path in source_files():
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if path.suffix in (".ts", ".tsx"):
            lits = ts_literals(text)
            haystacks.append((rel, ts_seam_haystack(text)))
        elif path.suffix == ".py":
            lits = py_literals(text)
        elif path.suffix == ".json":
            lits = json_literals(text)
        else:
            lits = yaml_literals(text)
        for lit in lits:
            index.setdefault(lit, rel)
    return index, haystacks


def find_orphans(keys, index, haystacks):
    orphans = []
    for key in keys:
        if key in index or key in WHITELIST:
            continue
        collapsed = _WS.sub(" ", key)
        if any(collapsed in hay for _, hay in haystacks):
            continue
        orphans.append(key)
    return orphans


# ------------------------------------------------------------------ checks

_failures = []
_checks = 0


def check(label, ok, detail=""):
    global _checks
    _checks += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"   [{detail}]" if detail and not ok else ""))
    if not ok:
        _failures.append(label)


POSITIVE_KEY = "The new password must be at least 8 characters long."
POSITIVE_FILE = "frontend/src/player/AvatarSettingsPanel.tsx"
FAKE_KEY = "ZZ this string exists in no source file ZZ"

# The last commit before this guard landed; its de.json still holds the orphans.
PRE_CLEANUP_REV = "8bc27a85"
PRE_CLEANUP_MIN_ORPHANS = 60
PRE_CLEANUP_SAMPLE = "Analyse sentiment after conversations"


def main() -> int:
    print("A) extractor self-test (expected sets written by hand in the docstring)")
    py1 = py_literals('def f():\n    """doc"""\n    return t("Hello")\n')
    check('python: docstring excluded, t("Hello") found', py1 == {"Hello"}, str(py1))
    py2 = py_literals('L = ["A" "B", "C" + "D"]\n')
    check("python: implicit join + constant fold", {"AB", "CD"} <= py2, str(py2))
    py3 = py_literals('# "Comment"\nx = 1\n')
    check("python: comment is no literal", py3 == set(), str(py3))
    ts1 = ts_literals("const a = 'It\\'s'\n")
    check("ts: escaped apostrophe resolved", ts1 == {"It's"}, str(ts1))
    ts2 = ts_literals('t("Floor {n}").replace("{n}", String(l))\n')
    check("ts: placeholder braces kept verbatim", "Floor {n}" in ts2, str(ts2))
    seam = ts_seam_haystack("t('one ' +\n  'two')\n")
    check("ts: seam fallback rejoins a wrapped literal", "one two" in seam, seam)

    raw = json.loads(DE_JSON.read_text(encoding="utf-8"))
    translations = raw.get("translations", {})
    print(f"\nB) de.json: {len(translations)} keys")
    braced = [k for k in translations if "${" in k]
    check("no key carries a template-literal placeholder ${...}", not braced, str(braced[:3]))

    index, haystacks = build_index()
    print(f"   source set: {len(index)} distinct literals, {len(haystacks)} TS fallback haystacks")

    print("\nC) controls")
    check(f"the control key {POSITIVE_KEY!r} exists in de.json", POSITIVE_KEY in translations)
    hit = index.get(POSITIVE_KEY)
    check(f"…and its source is {POSITIVE_FILE}", hit == POSITIVE_FILE, str(hit))
    fake = find_orphans([FAKE_KEY], index, haystacks)
    check("an injected fake key is reported as an orphan", fake == [FAKE_KEY], str(fake))

    print("\nD) orphans")
    orphans = find_orphans(list(translations), index, haystacks)
    check("every de.json key has a source", not orphans, f"{len(orphans)} orphans")
    for key in orphans:
        print(f"      ORPHAN {key!r}")
    if WHITELIST:
        print("   whitelisted (source the scan cannot see):")
        for key, why in WHITELIST.items():
            print(f"      {key!r}: {why}")

    print(f"\nE) the same scan against de.json of {PRE_CLEANUP_REV} (must still find orphans)")
    try:
        old = subprocess.run(["git", "show", f"{PRE_CLEANUP_REV}:shared/languages/de.json"],
                             cwd=REPO, capture_output=True, text=True, check=True).stdout
        old_keys = list(json.loads(old).get("translations", {}))
    except Exception as e:                                   # pragma: no cover
        check(f"git show {PRE_CLEANUP_REV}:shared/languages/de.json", False, str(e))
    else:
        old_orphans = find_orphans(old_keys, index, haystacks)
        check(f"the pre-cleanup map had >= {PRE_CLEANUP_MIN_ORPHANS} orphans",
              len(old_orphans) >= PRE_CLEANUP_MIN_ORPHANS, str(len(old_orphans)))
        check(f"…including the config-schema key {PRE_CLEANUP_SAMPLE!r}",
              PRE_CLEANUP_SAMPLE in old_orphans)

    print()
    print(f"{_checks - len(_failures)}/{_checks} checks passed")
    if _failures:
        print("FAILED: " + "; ".join(_failures))
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
