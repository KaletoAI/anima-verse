#!/usr/bin/env python3
"""Smoke: docs/config-defaults.md documents nothing that no longer exists.

Usage:  ./.venv/bin/python scripts/smoke_docs_config_defaults.py

Covers review finding DS-11. The table listed 19 setting names that appeared
nowhere in the code any more (all `TOGETHER_ANIMATE_*`, `PROACTIVE_*`,
`KNOWLEDGE_MAX_*`, `STORY_ENGINE_BEAT_FACESWAP`, `PORT`, …) and pointed at
four source files that had been deleted. Both halves are mechanical, so both
are checked here instead of being re-verified by hand every few months.

Mostly text work: `git grep` over the tracked tree plus a plain read of the
document. The one import is `app/core/config_schema.py` (part D) — a pure data
module, read against a throwaway storage dir. No server, no world DB.

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

C) The config.json settings the document names in its own right
   (`server.max_upload_mb`, `server.max_inflight_jobs_per_user`,
   `server.cors_origins`) are still fields of `app/core/config_schema.py`.
   They are config.json settings, not names of the A-kind, so A would not
   see them.

D) Every `<section>.<field>` path the Quelle column gives as the source of a
   bridged name has that field in `app/core/config_schema.py` — unless the
   row says "(nur config.json)", which is this document's marker for a value
   that IS bridged but has no schema field and therefore no admin form. That
   marker is a claim too, so it is checked the other way round: such a leaf
   must NOT be a schema field.

FAILS BEFORE / PASSES AFTER
---------------------------
Confirmed by running A and B against the previous revision of the document
(`git show 74693e4f:docs/config-defaults.md` — a PINNED commit, never `HEAD:`, which
would compare the file with itself once this revision is committed) — see the last block of the output:
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


def _schema_field(dotted):
    """The config_schema field a dotted config.json path points at, or None."""
    import os
    import tempfile
    os.environ.setdefault("STORAGE_DIR", tempfile.mkdtemp(prefix="smoke_docs_cfg_"))
    sys.path.insert(0, str(REPO))
    from app.core.config_schema import SECTIONS
    parts = dotted.split(".")
    if parts[0] == "skills" and len(parts) == 3:
        # A package contributes its own subsection (plugin.yaml config_schema),
        # merged under "skills" at load time — the core schema does not have it.
        import yaml
        man = REPO / "plugins" / parts[1] / "plugin.yaml"
        if not man.exists():
            return None
        meta = yaml.safe_load(man.read_text(encoding="utf-8")) or {}
        sub = (meta.get("config_schema") or {}).get(parts[1]) or {}
        f = (sub.get("fields") or {}).get(parts[2])
        return f if isinstance(f, dict) else None
    node = SECTIONS.get(parts[0])
    for key in parts[1:]:
        if not isinstance(node, dict):
            return None
        node = node.get("fields", node).get(key)
    return node if isinstance(node, dict) and "fields" not in node else None


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

    print("C) the config.json settings are still in the schema")
    schema = (REPO / "app" / "core" / "config_schema.py").read_text(encoding="utf-8")
    for field in ("max_upload_mb", "max_inflight_jobs_per_user", "cors_origins"):
        check(f"config_schema.py defines {field}", f'"{field}": {{' in schema)
        check(f"docs/config-defaults.md mentions {field}", field in doc)

    print("D) every Quelle path resolves the way the row claims")
    schema_only, json_only = [], []
    for row in [ln for ln in doc.splitlines() if ln.startswith("| `")]:
        m = re.search(r"\| `((?:[a-z_]+\.)+[a-z_0-9]+)`([^|]*)\|", row)
        if not m:
            continue
        declared = _schema_field(m.group(1)) is not None
        if "nur config.json" in m.group(2):
            if declared:
                json_only.append(m.group(1))
        elif not declared:
            schema_only.append(m.group(1))
    check("every admin-settable source is a config_schema field",
          not schema_only, str(schema_only))
    check("every \"nur config.json\" source really has no schema field",
          not json_only, str(json_only))

    print("E) A and B against the PREVIOUS revision (must find what DS-11 "
          "reported)")
    try:
        old = subprocess.run(["git", "show", "74693e4f:docs/config-defaults.md"],
                             cwd=REPO, capture_output=True, text=True,
                             check=True).stdout
    except Exception as e:                                   # pragma: no cover
        check("git show 74693e4f:docs/config-defaults.md (pinned pre-fix revision)",
              False, str(e))
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
