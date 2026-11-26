#!/usr/bin/env python3
"""Smoke: World Dev free mode — the FreeModePanel's media section agrees with
the media routes (plan docs/superpowers/plans/2026-11-25-world-dev-free-media.md,
Task 11).

Usage:
    ./.venv/bin/python scripts/smoke_world_dev_media_panel.py

A pure source check: no storage, no server, no world DB, no render. It reads
frontend/src/tabs/world-dev/FreeModePanel.tsx, app/routes/world_dev.py,
app/core/world_dev_media.py, app/core/world_dev_runs.py (AST) and
shared/languages/de.json. tsc proves the panel is well-typed; this proves the
panel and the server speak the SAME contract, which tsc cannot see.

WHAT IS CHECKED, and where every expected value comes from
----------------------------------------------------------
Plan Task 10 (the routes) and Task 11 (the panel), by hand:

  (a) start: the panel keeps "Generate media" in the persistent state
      "worlddev.free.media" with default true and sends it as
      "generate_media" — the field POST /world-dev/free/start reads
      (data.get("generate_media") in app/routes/world_dev.py).
  (b) the three media endpoints the panel calls — GET .../media,
      POST .../media-switch with {enabled}, POST .../media/retry — each exist
      as a route "/free/{run_id}/<suffix>" under the router's "/world-dev"
      prefix, with the matching method; the switch route reads
      data["enabled"].
  (c) the panel's element type names every key media_status returns:
      kind, id, name, row_id, status, note, steps, produced; its step type
      names id, label, status, note — and world_dev_media._STEP_STATUS_KEYS
      is exactly ("id", "label", "status", "note").
  (d) every row status of world_dev_runs.MEDIA_STATUSES (queued, running,
      done, failed, skipped, cancelled, removed — seven) has a label in the
      panel's MEDIA_STATUS_LABELS, and every label is a de.json key.
  (e) live updates: the panel subscribes to the "generation" sync topic
      (syncHub().onTopics(['generation'], ...)) and runs no polling loop
      (no setInterval in the file).
  (f) every t('<literal>') of the panel is a de.json key (smoke_i18n_orphans
      checks only the other direction: no key without a source).

Plan docs/superpowers/plans/2026-11-25-world-dev-free-fixes.md, Task 1 (F1 —
an interrupted run renders nothing before Accept):

  (g) the panel's MediaStatus interface names "waiting", its MediaWaiting
      type names kind, id, name, steps, and world_dev_media.media_status
      returns a dict literal with the key "waiting" (AST of the return).
  (h) both new t() literals — "Waiting for Accept" and the interrupted-run
      hint — appear in the panel and are de.json keys.
"""
from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PANEL = ROOT / "frontend/src/tabs/world-dev/FreeModePanel.tsx"
ROUTES = ROOT / "app/routes/world_dev.py"
MEDIA = ROOT / "app/core/world_dev_media.py"
RUNS = ROOT / "app/core/world_dev_runs.py"
DE = ROOT / "shared/languages/de.json"

failures: list = []


def check(cond: bool, msg: str) -> None:
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


def module_const(path: Path, name: str):
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} not found in {path}")


def interface_fields(src: str, name: str) -> set:
    m = re.search(r"interface\s+" + name + r"\s*\{(.*?)\n\}", src, re.S)
    if not m:
        return set()
    return set(re.findall(r"^\s*(\w+)\??\s*:", m.group(1), re.M))


panel = PANEL.read_text(encoding="utf-8")
routes = ROUTES.read_text(encoding="utf-8")
de = json.loads(DE.read_text(encoding="utf-8"))["translations"]

# (a)
check(re.search(r"usePersistentState(?:<boolean>)?\(\s*'worlddev\.free\.media'\s*,\s*true\s*\)", panel)
      is not None, "(a) persistent state worlddev.free.media, default true")
check(re.search(r"generate_media\s*:", panel) is not None, "(a) start body sends generate_media")
check('data.get("generate_media")' in routes, "(a) the start route reads generate_media")

# (b)
check('prefix="/world-dev"' in routes, "(b) router prefix /world-dev")
for method, suffix in (("get", "media"), ("post", "media-switch"), ("post", "media/retry")):
    check(f'@router.{method}("/free/{{run_id}}/{suffix}")' in routes,
          f"(b) route {method.upper()} /world-dev/free/{{run_id}}/{suffix} exists")
    call = "apiGet" if method == "get" else "apiPost"
    pat = call + r"(?:<[^(]*?>)?\(\s*\x60/world-dev/free/\$\{encodeURIComponent\([^)]*\)\}/" \
        + re.escape(suffix) + r"\x60"
    check(re.search(pat, panel) is not None, f"(b) panel calls {call} .../{suffix}")
check('data["enabled"]' in routes, "(b) the switch route reads enabled")
check(re.search(r"/media-switch\x60\s*,\s*\{\s*enabled\s*[:,}]", panel) is not None,
      "(b) panel sends {enabled} to media-switch")

# (c)
el = interface_fields(panel, "MediaElement")
want_el = {"kind", "id", "name", "row_id", "status", "note", "steps", "produced"}
check(want_el <= el, f"(c) MediaElement names {sorted(want_el)} (has {sorted(el)})")
st = interface_fields(panel, "MediaStep")
want_st = {"id", "label", "status", "note"}
check(want_st <= st, f"(c) MediaStep names {sorted(want_st)} (has {sorted(st)})")
check(module_const(MEDIA, "_STEP_STATUS_KEYS") == ("id", "label", "status", "note"),
      "(c) world_dev_media._STEP_STATUS_KEYS is (id, label, status, note)")
for key in ("enabled", "state", "elements"):
    check(re.search(r"interface\s+MediaStatus\s*\{[^}]*\b" + key + r"\??\s*:", panel, re.S)
          is not None, f"(c) MediaStatus names {key}")

# (d)
statuses = module_const(RUNS, "MEDIA_STATUSES")
check(len(statuses) == 7, f"(d) MEDIA_STATUSES has 7 statuses ({statuses})")
m = re.search(r"MEDIA_STATUS_LABELS[^=]*=\s*\{(.*?)\}", panel, re.S)
labels = dict(re.findall(r"(\w+)\s*:\s*'([^']*)'", m.group(1))) if m else {}
for s in statuses:
    check(s in labels, f"(d) status {s} has a label")
    if s in labels:
        check(labels[s] in de, f"(d) label {labels[s]!r} is a de.json key")

# (e)
check(re.search(r"syncHub\(\)\.onTopics\(\s*\[\s*'generation'\s*\]", panel) is not None,
      "(e) the panel listens to the generation topic")
check("setInterval(" not in panel, "(e) no polling loop")

# (f)
missing = sorted({s for s in re.findall(r"\bt\(\s*'((?:[^'\\]|\\.)*)'\s*\)", panel)
                  if s.replace("\\'", "'") not in de})
check(not missing, f"(f) every t() literal has a de.json key (missing: {missing})")

# (g)
check(re.search(r"interface\s+MediaStatus\s*\{[^}]*\bwaiting\??\s*:", panel, re.S) is not None,
      "(g) MediaStatus names waiting")
wt_fields = interface_fields(panel, "MediaWaiting")
check({"kind", "id", "name", "steps"} <= wt_fields,
      f"(g) MediaWaiting names kind, id, name, steps (has {sorted(wt_fields)})")
status_keys: set = set()
for node in ast.walk(ast.parse(MEDIA.read_text(encoding="utf-8"))):
    if isinstance(node, ast.FunctionDef) and node.name == "media_status":
        for sub in ast.walk(node):
            if isinstance(sub, ast.Return) and isinstance(sub.value, ast.Dict):
                status_keys |= {k.value for k in sub.value.keys if isinstance(k, ast.Constant)}
check("waiting" in status_keys, f"(g) media_status returns the key waiting (keys {sorted(status_keys)})")

# (h)
for lit in ("Waiting for Accept",
            "This run was interrupted: its media are rendered after Accept; "
            "Discard drops them."):
    check(f"t('{lit}')" in panel, f"(h) the panel shows t({lit!r})")
    check(lit in de, f"(h) {lit!r} is a de.json key")

if failures:
    print(f"\n{len(failures)} FAILED")
    sys.exit(1)
print("\nall ok")
