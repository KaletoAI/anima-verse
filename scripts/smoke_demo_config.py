#!/usr/bin/env python3
"""Guard for the SHIPPED demo world config — no strays, no private endpoints.

Usage:
    ./.venv/bin/python scripts/smoke_demo_config.py

No server, no world DB, no network. It reads only TRACKED text files
(``git ls-files``) and never opens ``worlds/demo/world.db``.

WHY — ``worlds/demo/`` is tracked in git (CLAUDE.md) and is the first thing a
newcomer boots. Until 2026-09-21 it carried the maintainer's lab endpoint
(``http://192.168.8.197:8080/v1``), a GPU-named ``serialize_group`` and ~47
top-level keys that an old flatten-to-sections migration had left behind
(``backend``, ``batch_size``, ``chunk_size``, ``codeformer_weight``,
``service_url``, ``sharpen``, …). Nothing reads those at the root —
``config._flatten_to_env`` only ever walks SECTIONS — so they were pure noise
that survived every admin save round-trip.

THE FOUR RULES, each derived by hand from the source named with it:

R1  ROOT KEYS. ``app/core/config.py`` resolves every value through a section
    (``config.get("tts.backend")``, ``_flatten_to_env`` -> ``config.get(
    "<section>", {})``), so the only legal root keys are the section names of
    ``app/core/config_schema.SECTIONS`` plus the migration markers config.py
    writes at the root itself — today exactly one:
    ``config._LANE_MIGRATION_MARKER`` ("llm_lanes_migrated", set by
    ``_migrate_entry_lanes``). Anything else is a leftover.

R2  NO PRIVATE HOST. A shipped config must not name a machine on someone's
    LAN. Forbidden in every tracked text file under ``worlds/demo/`` and in
    ``shared/config/*.json``: the RFC1918 ranges 10/8, 172.16/12, 192.168/16,
    plus link-local 169.254/16 and the CGNAT range 100.64/10. ``localhost``
    and ``127.0.0.1`` are what docs/getting-started-new-world.md and README.md
    tell a newcomer to enter, so they stay allowed.

R3  NO SECRET VALUE. Secrets belong in ``worlds/<w>/secrets.json``, which is
    gitignored and split out by ``config._split_secrets``. So no key whose
    name ends in ``token`` / ``secret`` / ``password`` / ``api_key`` may carry
    a non-empty value anywhere in the tracked demo config — at any depth. The
    same check asserts secrets.json itself is not tracked.

R4  LIVE REFERENCES. Every task id under ``llm_routing[].tasks[].task`` must
    exist in ``app/core/llm_tasks.TASK_TYPES`` (the demo world still routed
    ``group_chat_stream``, a task deleted with the group-chat teardown), and
    every ``image_generation.backends[].api_type`` must be a key of
    ``app/imagegen/registry.BACKEND_REGISTRY``.

Exit code 0 = all four rules hold. Exit 1 prints every violation.
"""
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

# Throwaway storage root BEFORE any app import (scripts/smoke_scripts_storage_lint.py).
os.environ.setdefault("STORAGE_DIR", tempfile.mkdtemp(prefix="smoke_demo_config_"))

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import json  # noqa: E402

from app.core import config as config_mod  # noqa: E402
from app.core.config_schema import SECTIONS  # noqa: E402
from app.core.llm_tasks import TASK_TYPES  # noqa: E402
from app.imagegen.registry import BACKEND_REGISTRY  # noqa: E402

DEMO_CONFIG = REPO / "worlds" / "demo" / "config.json"

failures: list = []


def check_true(label: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"  OK  {label}")
    else:
        print(f"  FAIL {label}" + (f" — {detail}" if detail else ""))
        failures.append(label)


def tracked(pattern: str) -> list:
    """Paths tracked in git under `pattern` (relative to the repo root)."""
    out = subprocess.run(["git", "ls-files", "--", pattern], cwd=str(REPO),
                         capture_output=True, text=True, check=True).stdout
    return [REPO / line for line in out.splitlines() if line]


# ── R1 ──────────────────────────────────────────────────────────────────────
def part_root_keys() -> dict:
    print("1. root keys of worlds/demo/config.json (R1)")
    cfg = json.loads(DEMO_CONFIG.read_text(encoding="utf-8"))
    valid = set(SECTIONS) | {config_mod._LANE_MIGRATION_MARKER}
    stray = sorted(k for k in cfg if k not in valid)
    check_true(f"every root key is a SECTIONS name or a migration marker "
               f"({len(cfg)} key(s))", not stray, "stray: " + ", ".join(stray))
    # Counter-check: the rule is not vacuous — a section name must be accepted
    # and an invented key rejected.
    check_true("the rule accepts a real section name", "image_generation" in valid)
    check_true("the rule rejects an invented key", "codeformer_weight" not in valid)
    return cfg


# ── R2 ──────────────────────────────────────────────────────────────────────
# RFC1918 + link-local + CGNAT, as dotted-quad prefixes.
_PRIVATE_IP = re.compile(
    r"\b(?:"
    r"10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
    r"|192\.168\.\d{1,3}\.\d{1,3}"
    r"|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}"
    r"|169\.254\.\d{1,3}\.\d{1,3}"
    r"|100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}"
    r")\b"
)
_TEXT_SUFFIXES = {".json", ".md", ".txt", ".yaml", ".yml", ".csv"}


def part_private_hosts() -> None:
    print("2. no private-LAN host in tracked demo/shared config text (R2)")
    files = [p for p in tracked("worlds/demo") if p.suffix.lower() in _TEXT_SUFFIXES]
    files += [p for p in tracked("shared/config") if p.suffix.lower() == ".json"]
    check_true("there are tracked text files to scan", len(files) >= 2,
               f"found {len(files)}")
    hits = []
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            for m in _PRIVATE_IP.finditer(line):
                hits.append(f"{path.relative_to(REPO)}:{i}: {m.group(0)}")
    check_true(f"no RFC1918/link-local/CGNAT address in {len(files)} tracked file(s)",
               not hits, "; ".join(hits[:8]))
    # Counter-check of the pattern itself, hand-derived:
    for sample, expected in [("http://192.168.8.197:8080/v1", True),
                             ("http://10.0.0.5:8080", True),
                             ("http://172.16.3.1", True),
                             ("http://172.32.3.1", False),   # outside 172.16/12
                             ("http://localhost:8080/v1", False),
                             ("http://127.0.0.1:8000", False)]:
        check_true(f"pattern verdict for {sample!r} is {expected}",
                   bool(_PRIVATE_IP.search(sample)) is expected)


# ── R3 ──────────────────────────────────────────────────────────────────────
_SECRET_SUFFIXES = ("token", "secret", "password", "api_key")


def _walk(node, path=""):
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _walk(v, f"{path}.{k}" if path else k)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk(v, f"{path}[{i}]")
    else:
        yield path, node


def part_secrets(cfg: dict) -> None:
    print("3. no secret value in the tracked demo config (R3)")
    bad = []
    for dotted, value in _walk(cfg):
        key = dotted.rsplit(".", 1)[-1]
        if key.endswith(_SECRET_SUFFIXES) and isinstance(value, str) and value.strip():
            bad.append(f"{dotted} = {value[:12]}…")
    check_true("no key ending in token/secret/password/api_key carries a value",
               not bad, "; ".join(bad))
    check_true("worlds/demo/secrets.json is NOT tracked",
               not tracked("worlds/demo/secrets.json"))
    # Counter-check: the walker really reaches into lists and nested dicts.
    probe = {"a": {"b": [{"auth_token": "xyz"}]}}
    found = [d for d, v in _walk(probe) if d.endswith("auth_token")]
    check_true("the walker reaches list -> dict depth", found == ["a.b[0].auth_token"],
               str(found))


# ── R4 ──────────────────────────────────────────────────────────────────────
def part_references(cfg: dict) -> None:
    print("4. every routed task and backend type still exists (R4)")
    unknown_tasks = []
    task_count = 0
    for entry in cfg.get("llm_routing") or []:
        for t in entry.get("tasks") or []:
            task_count += 1
            if t.get("task") not in TASK_TYPES:
                unknown_tasks.append(f"{entry.get('model')}: {t.get('task')}")
    check_true(f"all {task_count} routed task id(s) exist in llm_tasks.TASK_TYPES",
               not unknown_tasks, "; ".join(unknown_tasks))
    check_true("the deleted task group_chat_stream is not in the catalog",
               "group_chat_stream" not in TASK_TYPES)

    backends = (cfg.get("image_generation") or {}).get("backends") or []
    unknown_types = [f"{b.get('name')}: {b.get('api_type')}" for b in backends
                     if b.get("api_type") not in BACKEND_REGISTRY]
    check_true(f"all {len(backends)} backend api_type(s) are in BACKEND_REGISTRY",
               not unknown_types, "; ".join(unknown_types))

    # Every LoRA the library offers must name a backend this world has.
    names = {b.get("name") for b in backends}
    orphan = []
    for tr in (cfg.get("image_generation") or {}).get("lora_triggers") or []:
        for be in tr.get("backends") or []:
            if be not in names:
                orphan.append(f"{tr.get('lora')} -> {be}")
    check_true("no LoRA library entry points at a missing backend",
               not orphan, "; ".join(orphan))


def main() -> int:
    check_true("worlds/demo/config.json exists", DEMO_CONFIG.is_file())
    if not DEMO_CONFIG.is_file():
        return 1
    cfg = part_root_keys()
    part_private_hosts()
    part_secrets(cfg)
    part_references(cfg)
    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s): {', '.join(failures)}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
