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
   The resolver walks `fields` AND `subsections` (2026-09-21). It used to walk
   `fields` only, so every subsection leaf looked undeclared — which is how the
   document came to claim the TTS backend URLs had no admin form although
   `/admin/settings → Text-to-Speech → XTTS v2` has offered them all along
   (`static/admin/settings.js` renders `subsections`).

G) Every row whose Quelle column names a `config.json` path claims the value
   reaches the code through the env bridge under the NAME in the first column.
   Checked against the same AST reading of `_flatten_to_env` that part F uses:
   every such name must be one the bridge sets. Expected: all of them. A
   removed bridge line slips past A, because the anchor tends to live on in a
   comment somewhere — `DAILY_SUMMARY_DAYS` did in `app/core/scene_manager.py`
   after `app/utils/history_manager.py` moved to
   `config.get("knowledge.daily_summary_days")` on 2026-09-22.

F) THE INVERSE OF D, straight from the code and without the document: every
   config leaf that `config._flatten_to_env` bridges into an env var must have
   a schema field. A bridged value is a setting the app reads at runtime; one
   without a field can only be changed by editing `config.json` by hand, and a
   running server overwrites such an edit on the next admin save. The paths are
   read out of the AST of `_flatten_to_env` — `x = config.get("sec", {})` /
   `y = x.get("sub", {})` build the prefix, every `_set(env, "NAME", <var>.get(
   "<field>", …))` is one leaf. Expected answer, derived by hand from the
   function: ZERO leaves without a field. The dynamic blocks (the numbered
   provider / backend loops and the F5 language loop) carry no string literal
   for their field and are simply not seen — they are array items, whose
   fields live under `sub_arrays` / `is_array`, not flat leaves.

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
        # merged under "skills" at load time. If it does not, the leaf may
        # still be a core subsection (skills.outfit_change.* has no package),
        # so this is a first LOOK, not the whole answer.
        import yaml
        man = REPO / "plugins" / parts[1] / "plugin.yaml"
        if man.exists():
            meta = yaml.safe_load(man.read_text(encoding="utf-8")) or {}
            sub = (meta.get("config_schema") or {}).get(parts[1]) or {}
            f = (sub.get("fields") or {}).get(parts[2])
            if isinstance(f, dict):
                return f
    node = SECTIONS.get(parts[0])
    for key in parts[1:]:
        if not isinstance(node, dict):
            return None
        # A leaf may sit in this node's `fields` OR in one of its
        # `subsections` (tts.xtts.url, skills.outfit_change.language …).
        step = None
        for holder in ("fields", "subsections"):
            box = node.get(holder)
            if isinstance(box, dict) and key in box:
                step = box[key]
                break
        node = step
    return node if isinstance(node, dict) and "fields" not in node else None


def bridged_leaves():
    """Every `<section>.<field>` path `config._flatten_to_env` bridges.

    Read out of the AST, not by importing and running the function: the
    bridge WRITES os.environ, and a check script must not.
    """
    import ast
    src = (REPO / "app" / "core" / "config.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "_flatten_to_env")

    def dotted_get(call, prefix):
        """`<known var>.get("<literal>", …)` -> its dotted path, else None."""
        if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                and call.func.attr == "get"
                and isinstance(call.func.value, ast.Name)
                and call.func.value.id in prefix and call.args
                and isinstance(call.args[0], ast.Constant)
                and isinstance(call.args[0].value, str)):
            return None
        return (prefix[call.func.value.id] + "." + call.args[0].value).lstrip(".")

    prefix = {"config": ""}
    for node in ast.walk(fn):
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)):
            path = dotted_get(node.value, prefix)
            if path is not None:
                prefix[node.targets[0].id] = path

    leaves = {}
    for node in ast.walk(fn):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "_set" and len(node.args) >= 3):
            continue
        name = (node.args[1].value
                if isinstance(node.args[1], ast.Constant) else "?")
        for sub in ast.walk(node.args[2]):
            path = dotted_get(sub, prefix)
            if path is not None:
                leaves.setdefault(path, name)
    return leaves


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

    print("F) every bridged config leaf has a schema field")
    leaves = bridged_leaves()
    check(f"the AST reader found the bridge's leaves ({len(leaves)})",
          len(leaves) >= 60, str(len(leaves)))
    undeclared = sorted(f"{path} ({env})" for path, env in leaves.items()
                        if _schema_field(path) is None)
    check("no bridged setting is missing its config_schema field",
          not undeclared, str(undeclared))
    # Counter-check: the resolver is not answering "declared" to everything.
    check("the resolver says None for an invented leaf",
          _schema_field("tts.xtts.no_such_field") is None)
    check("the resolver finds a SUBSECTION leaf",
          _schema_field("tts.xtts.url") is not None)
    check("the resolver finds a plain section leaf",
          _schema_field("server.log_level") is not None)

    print("G) every row that claims to be bridged really is")
    # A row with a `config.json` path in the Quelle column says: "change it in
    # the admin UI, and `_flatten_to_env` puts it under this NAME". When the
    # bridge line for that leaf goes away (a reader moved to `config.get(...)`
    # — `knowledge.daily_summary_days` did on 2026-09-22), the row becomes a
    # lie that check A does not see: the NAME usually survives somewhere in a
    # comment, which is a hit for A. Expected, derived from the two columns
    # themselves: every such NAME is one the AST found in `_flatten_to_env`.
    bridge_names = set(bridged_leaves().values())
    unbridged = []
    for row in [ln for ln in doc.splitlines() if ln.startswith("| `")]:
        m = re.match(r"\| `([A-Z][A-Z0-9_]+)` \| `((?:[a-z_]+\.)+[a-z_0-9]+)`",
                     row)
        if m and m.group(1) not in bridge_names:
            unbridged.append(f"{m.group(1)} ({m.group(2)})")
    check("no row names an anchor the bridge no longer sets",
          not unbridged, str(unbridged))

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
