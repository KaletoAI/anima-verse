#!/usr/bin/env python3
"""Smoke: every core API docs/skill-core-api.md promises really exists.

Usage:  ./.venv/bin/python scripts/smoke_docs_skill_core_api.py

docs/skill-core-api.md is a CONTRACT for package authors: "these names, with
these parameters, are what a skill package may call". Nothing enforced it, so
the document drifted — it still named `agent_loop.agent_loop().bump(name,
reason=...)` (the accessor is `get_agent_loop`, the keyword is `hint`),
`relationship.extract_romantic_interests` (moved into a package) and
`soul_writer` entries that had been renamed. This is the check.

WHAT IS CHECKED, and where every expected value comes from
-----------------------------------------------------------

The expectations are NOT a hand-copied list: they are read out of the document
itself at run time and compared against `inspect.signature` of the real object.
A row that is wrong therefore fails here, and a row that is right needs no
maintenance.

A) EXISTENCE. Every call spelled in the document — a backticked
   ``name(args)`` inside a table row or a paragraph — resolves to a real
   attribute. A section heading carries the module it documents
   (``## Pose — `app.models.character` ✅``), so a bare ``set_pose_intent(...)``
   under that heading is looked up there; a fully qualified
   ``app.core.hooks.register(...)`` is looked up as written.

B) PARAMETER NAMES. The names the document writes between the parentheses are
   compared with the real signature: each documented name must exist as a real
   parameter, and the documented ones must appear in the real order. ``*`` is
   read as "keyword-only from here" and checked as such. A trailing ``…``
   means the list is deliberately partial — then only the names given are
   checked. Without ``…`` the document must name every parameter the callable
   has (minus ``self``), so a NEW parameter also shows up as a failure.

C) MODULES. Every ``app.*`` module named in a heading imports.

Storage: the run creates a throwaway storage dir and calls ``paths.init`` on it
BEFORE anything from ``app`` is imported, and points ANIMATION_CLIPS_DIR /
ANIMATION_RIG_FILE at it too, so nothing touches a real world or the real clip
library. No server, no world DB of the project, no network.

Deliberately NOT checked: the prose. Whether "never hold a profile lock across
an LLM call" is still true cannot be read off a signature; that is what
scripts/smoke_profile_rmw_lock.py is for.

FAILS BEFORE / PASSES AFTER
---------------------------
Run against the pre-fix revision of the document the check reports four dead
names (`agent_loop.agent_loop`, `relationship.extract_romantic_interests`,
`intent_engine.tool_intent_payload`, `travel_engine.list_active_journeys`) and
the wrong `bump` keyword. The comparison is not automated here because the old
document used a different heading layout, so the section->module mapping this
check relies on did not exist yet.
"""
import inspect
import os
import re
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DOC = REPO / "docs" / "skill-core-api.md"

_failures = []
_checks = 0


def check(label, ok, detail=""):
    global _checks
    _checks += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"   [{detail}]" if detail and not ok else ""))
    if not ok:
        _failures.append(label)


def _boot():
    """Throwaway storage, set before app.* is imported."""
    td = tempfile.mkdtemp(prefix="smoke_docs_core_api_")
    os.environ["STORAGE_DIR"] = td
    os.environ["ANIMATION_CLIPS_DIR"] = str(Path(td) / "clips")
    os.environ["ANIMATION_RIG_FILE"] = str(Path(td) / "reference.fbx")
    sys.path.insert(0, str(REPO))
    from app.core import paths
    paths.init(td)


# `name(args)` inside a code span; the name may be dotted and may carry a
# leading "A / B / " chain of alternatives that share the parameter list.
_CALL_RE = re.compile(r"`([A-Za-z_][\w. /]*)\(([^`()]*)\)(?:\s*->[^`]*)?`")
#: an `app.<module>` in a section heading sets the default lookup module
_HEAD_MOD_RE = re.compile(r"`(app\.[\w.]+)`")

#: Spans that look like calls but are not core API: examples, literals and
#: names this document deliberately spells in prose.
SKIP_NAMES = {
    "keyed_lock",                 # shown as an example with literal arguments
    "get_character_profile", "save_character_profile",  # the lock example block
    "subjects.mesh_backend_options",  # lives in a built-in type package
    "super().validate", "registry.register",
    "ValueError", "datetime.now",     # prose, not core API
    "execute",                        # "Durchreichung an execute()" — prose
    "int", "str", "bool", "dict", "list",
}

#: Sections whose heading module is not where the bare names live.
MODULE_ALIAS = {
    "app.core.improvements": "app.core.improvements.base",
}

#: Names the document spells the way a caller writes them (on an instance or a
#: class) — mapped to where the definition actually is.
NAME_ALIAS = {
    "BaseSkill.tool_intent_payload": "app.skills.base.BaseSkill.tool_intent_payload",
    "handle_intent": "app.skills.base.BaseSkill.handle_intent",
    "visible_for": "app.skills.base.BaseSkill.visible_for",
    "defer_for_attachment": "app.skills.base.BaseSkill.defer_for_attachment",
    "thought_context_block": "app.skills.base.BaseSkill.thought_context_block",
    "tool_intent_payload": "app.skills.base.BaseSkill.tool_intent_payload",
    "get_usage_instructions": "app.skills.base.BaseSkill.get_usage_instructions",
    "ctx.get_config": "app.plugins.context.PluginContext.get_config",
    "skill_manager.tool_names_with_flag":
        "app.skills.skill_manager.SkillManager.tool_names_with_flag",
    "skill_manager.progress_type_for_tool":
        "app.skills.skill_manager.SkillManager.progress_type_for_tool",
    "generate_from_input": "app.imagegen.service.ImageService.generate_from_input",
    "ParamField": "app.core.improvements.base.ParamField",
    "Candidate": "app.core.improvements.base.Candidate",
    "validate": "app.core.improvements.base.ImprovementType.validate",
    "apply": "app.core.improvements.base.ImprovementType.apply",
    "find_candidates": "app.core.improvements.base.ImprovementType.find_candidates",
    "is_done": "app.core.improvements.base.ImprovementType.is_done",
}


def _resolve(dotted):
    """Import-and-getattr a dotted name; returns (obj, error)."""
    import importlib
    parts = dotted.split(".")
    for i in range(len(parts), 0, -1):
        try:
            mod = importlib.import_module(".".join(parts[:i]))
        except Exception:
            continue
        obj = mod
        for attr in parts[i:]:
            obj = getattr(obj, attr, None)
            if obj is None:
                return None, f"no attribute {attr!r} on {'.'.join(parts[:i])}"
        return obj, ""
    return None, "no importable module prefix"


def _documented_params(argtext):
    """Parameter names the document spells, plus the two markers."""
    names, kwonly_from, partial = [], None, False
    for raw in argtext.split(","):
        tok = raw.strip()
        if not tok:
            continue
        if tok in ("…", "...") or tok.startswith("*") and tok != "*":
            partial = True
            continue
        if tok == "*":
            kwonly_from = len(names)
            continue
        name = tok.split("=")[0].split(":")[0].strip()
        if name:
            names.append(name)
    return names, kwonly_from, partial


def _real_params(obj):
    try:
        sig = inspect.signature(obj)
    except Exception as e:
        return None, None, str(e)
    names, kwonly = [], set()
    for p in sig.parameters.values():
        if p.name == "self":
            continue
        if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            continue
        names.append(p.name)
        if p.kind == p.KEYWORD_ONLY:
            kwonly.add(p.name)
    return names, kwonly, ""


def main():
    _boot()
    doc = DOC.read_text(encoding="utf-8")

    # --- C) modules named in headings -------------------------------------
    heading_mods = []
    current = []
    calls = []          # (dotted_or_bare, argtext, default_modules)
    for line in doc.splitlines():
        if line.startswith("## "):
            current = [MODULE_ALIAS.get(m, m) for m in _HEAD_MOD_RE.findall(line)]
            heading_mods.extend(current)
            continue
        for m in _CALL_RE.finditer(line):
            head, args = m.group(1), m.group(2)
            for alt in head.split(" / "):
                alt = alt.strip()
                if not alt or " " in alt or alt in SKIP_NAMES:
                    continue
                calls.append((NAME_ALIAS.get(alt, alt), args, tuple(current)))

    print(f"C) every app.* module named in a heading imports ({len(set(heading_mods))})")
    import importlib
    bad_mods = []
    for mod in sorted(set(heading_mods)):
        try:
            importlib.import_module(mod)
        except Exception as e:
            bad_mods.append(f"{mod}: {e}")
    check("no heading names a module that cannot be imported", not bad_mods, "; ".join(bad_mods))

    # --- A) existence ------------------------------------------------------
    resolved = []       # (label, obj, args)
    missing = []
    for name, args, mods in calls:
        candidates = [name] if name.startswith("app.") else \
            [f"{m}.{name}" for m in mods] + ([name] if "." in name else [])
        if not candidates:
            continue
        obj, err = None, "no section module"
        for cand in candidates:
            obj, err = _resolve(cand)
            if obj is not None:
                resolved.append((cand, obj, args))
                break
        if obj is None:
            missing.append(f"{name}({args[:40]}) -> {err}")

    print(f"A) every documented call resolves ({len(calls)} spans, "
          f"{len(resolved)} resolved)")
    check("no documented core API is missing from the code", not missing,
          " | ".join(sorted(set(missing))))

    # --- B) parameter names ------------------------------------------------
    print(f"B) documented parameter names match inspect.signature "
          f"({len(resolved)} callables)")
    mismatches = []
    for label, obj, argtext in resolved:
        if not callable(obj):
            continue
        real, real_kwonly, err = _real_params(obj)
        if real is None:
            continue                                   # builtin / C object
        doc_names, kwonly_from, partial = _documented_params(argtext)
        unknown = [n for n in doc_names if n not in real]
        if unknown:
            mismatches.append(f"{label}: unknown param(s) {unknown}; real={real}")
            continue
        # relative order
        idx = [real.index(n) for n in doc_names]
        if idx != sorted(idx):
            mismatches.append(f"{label}: documented order {doc_names} != real {real}")
            continue
        if not partial and doc_names != real:
            mismatches.append(f"{label}: documents {doc_names}, real is {real}")
            continue
        if kwonly_from is not None:
            after = set(doc_names[kwonly_from:])
            wrong = sorted(after - real_kwonly)
            if wrong:
                mismatches.append(f"{label}: documented as keyword-only but is not: {wrong}")
    check("no signature drifted away from the document", not mismatches,
          " | ".join(sorted(mismatches)))

    print()
    print(f"{_checks - len(_failures)}/{_checks} checks passed")
    if _failures:
        for f in _failures:
            print(f"  failed: {f}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
