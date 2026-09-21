#!/usr/bin/env python3
"""AST guard: no profile read-modify-write without ``keyed_lock``.

Usage:
    ./.venv/bin/python scripts/smoke_profile_rmw_lock.py

Pure static check — no world DB, no server, no storage directory at all.

WHAT IT CHECKS AND WHY (DATA-3 of the 2026-09-20 review)

``save_character_profile`` writes the WHOLE ``profile_json`` blob from the
dict it is handed. So this shape

    profile = get_character_profile(name)      # read
    profile["x"] = 1                           # modify
    save_character_profile(name, profile)      # write

silently drops every change another thread made to ANY other field of that
character between the read and the write — not only to ``x``. Since the
routes moved into the threadpool (2026-08-24) nothing serializes those two
threads any more; the replacement is ``keyed_lock("character_profile", name)``
around read AND write (``app/core/keyed_lock.py``).

The rule this file enforces, derived by hand from that contract:

    In one function body, a call ``get_character_profile(X)`` followed by a
    call ``save_character_profile(X, …)`` with the SAME first-argument source
    text is a read-modify-write. BOTH calls must sit inside a ``with``
    statement whose context manager is ``keyed_lock("character_profile", …)``.

Deliberate limits of the rule (so the result is honest rather than clever):

  * Same function body only. A read in one function and a write in another is
    not matched — the caller may well hold the lock (that is exactly how the
    equip routes work: the route locks, ``inventory.equip_piece`` writes).
  * Same first-argument SOURCE TEXT. ``get_character_profile(name)`` followed
    by ``save_character_profile(other, …)`` is two different characters and no
    pair.
  * A nested ``def`` is its own body and is checked separately.
  * The lock KEY is not compared — only the namespace ``"character_profile"``.
    A keyed lock on the wrong key would be a different (much rarer) bug and
    proving the key is the character would need type inference.

EXPECTED RESULT: zero unexpected violations. Every site that is deliberately
left unlocked stands in ALLOWLIST below WITH ITS REASON. The file is scanned
even when it is a symlink into the private pack repo — those packages call the
same API.
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN_DIRS = ("app", "plugins")

READ = "get_character_profile"
WRITE = "save_character_profile"
LOCK_NS = "character_profile"

#: ``<path>::<function>`` sites this check accepts WITHOUT the lock, each with
#: the reason it is safe (or who owns the fix). Anything not listed fails.
ALLOWLIST = {
    # --- the lock lives one level up, in the HTTP route -------------------
    "app/models/inventory.py::equip_piece":
        "routes/inventory.py + routes/play.py take keyed_lock('character_profile') "
        "around the call; locking again would deadlock (keyed_lock is a plain Lock)",
    "app/models/inventory.py::unequip_piece":
        "same: the equip/unequip routes hold the lock around this call",
    "app/models/inventory.py::apply_equipped_pieces":
        "same: /apply-equipped-pieces and /apply-outfit-set hold the lock",
    "app/models/inventory.py::equip_item":
        "same: POST /inventory/characters/{n}/equip holds the lock around it",
    "app/models/inventory.py::unequip_item":
        "same: POST /inventory/characters/{n}/unequip holds the lock around it",

    # --- creation paths: nobody else can hold this profile yet ------------
    "app/core/character_io.py::import_character_from_zip":
        "import CREATES the character row; there is no concurrent writer of a "
        "character that is not in the roster yet",

    # --- one-time boot migrations: single-threaded, before the routers ----
    "app/core/appearance_token_migration.py::migrate_dead_appearance_tokens_once":
        "boot migration (server.py lifespan, before the routers are reachable)",
    "app/core/game_calendar_migration.py::_migrate_profiles":
        "boot migration, same window",
    "app/core/height.py::migrate_height_to_profile_once":
        "boot migration, same window",
    "app/core/workflow_spec_migration.py::migrate_legacy_workflow_specs_once":
        "boot migration, same window",
    "app/models/character_template.py::normalize_character_template":
        "boot normalisation, same window (character_template.py is not part of "
        "the 2026-09-20 fix round either)",
    "app/models/character_template.py::migrate_prune_stale_stats_once":
        "boot migration, same window",

    # --- NEEDS COORDINATOR: real DATA-3 sites in files this fix round -----
    # --- does not own. Each one is a genuine unprotected read-modify-write,
    # --- reported to the coordinator rather than patched from here.
    "app/core/body_slots.py::set_slot_value":
        "NEEDS COORDINATOR — not this round's file set",
    "app/core/character_ops.py::apply_profile_update":
        "NEEDS COORDINATOR — not this round's file set",
    "app/core/character_ops.py::apply_outfit_imagegen":
        "NEEDS COORDINATOR — not this round's file set",
    "app/core/character_ops.py::build_status_effects":
        "NEEDS COORDINATOR — not this round's file set",
    "app/core/character_ops.py::apply_template_switch":
        "NEEDS COORDINATOR — not this round's file set",
    "app/core/model3d.py::set_model3d_options":
        "NEEDS COORDINATOR — not this round's file set",
    "app/core/model_refs.py::set_auto_kinds":
        "NEEDS COORDINATOR — not this round's file set",
    "app/core/model_refs.py::set_view_kinds":
        "NEEDS COORDINATOR — not this round's file set",
    "app/core/npc_assets.py::gate_placement":
        "NEEDS COORDINATOR — not this round's file set",
    "app/core/npc_assets.py::_place":
        "NEEDS COORDINATOR — not this round's file set",
    "app/core/npc_home.py::_put_at_point":
        "NEEDS COORDINATOR — not this round's file set",
    "app/core/npc_ops.py::apply_npc":
        "NEEDS COORDINATOR — not this round's file set",
    "app/core/npc_ops.py::sweep_expired_npcs":
        "NEEDS COORDINATOR — not this round's file set",
    "app/core/npc_pool.py::pool_npc":
        "NEEDS COORDINATOR — not this round's file set; the span also contains "
        "leave_party/cancel_journey/end_interaction, so it needs the same "
        "treatment as save_character_current_location",
    "app/core/npc_pool.py::revive_from_pool":
        "NEEDS COORDINATOR — not this round's file set",
    "app/core/npc_spawn.py::_fill_bound_slot":
        "NEEDS COORDINATOR — not this round's file set",
    "app/core/npc_spawn.py::_settle_wanderer":
        "NEEDS COORDINATOR — not this round's file set (see also SIM-9)",
    "app/models/inventory.py::apply_item_effects":
        "NEEDS COORDINATOR — inventory.py is another implementer's file",
    "plugins/undress/skill.py::execute":
        "NEEDS COORDINATOR — plugin package, not this round's file set",

    # --- character.py sites that CANNOT take the lock as it is today ------
    # keyed_lock hands out a plain threading.Lock, which is NOT re-entrant.
    # Each span below calls, directly or indirectly, something that now takes
    # this very lock — locking here would deadlock the request thread.
    "app/models/character.py::save_character_current_location":
        "NEEDS COORDINATOR — the span contains end_interaction(), which reaches "
        "clear_pose_intent -> places.release; both take this lock now. Needs an "
        "RLock in app/core/keyed_lock.py (not this round's file) or the "
        "interaction end pulled out of the span",
    "app/models/character.py::save_character_current_room":
        "NEEDS COORDINATOR — same shape as save_character_current_location",
    "app/models/character.py::set_pose_intent":
        "NEEDS COORDINATOR — calls places.assign / _seat_for_pose inside the "
        "span, and those take this lock",
    "app/models/character.py::set_is_sleeping":
        "NEEDS COORDINATOR — calls places.assign inside the span",
    "app/models/character.py::enter_offmap_sleep":
        "NEEDS COORDINATOR — calls the location setter inside the span",
    "app/models/character.py::wake_from_offmap":
        "NEEDS COORDINATOR — calls the location setter inside the span",
    "app/models/character.py::appear_in_world":
        "NEEDS COORDINATOR — calls wake_from_offmap (which writes the profile) "
        "inside the span",
    "app/core/interaction_engine.py::start_interaction":
        "NEEDS COORDINATOR — another implementer's file; it writes BOTH "
        "partners' profiles, which needs a name-ordered acquisition",
    "app/core/interaction_engine.py::end_interaction":
        "NEEDS COORDINATOR — same file, and it is called from inside "
        "save_character_current_location",
}


def _is_call(node, name):
    return (isinstance(node, ast.Call)
            and ((isinstance(node.func, ast.Name) and node.func.id == name)
                 or (isinstance(node.func, ast.Attribute) and node.func.attr == name)))


def _is_profile_lock(node):
    """True for ``keyed_lock("character_profile", …)`` as a context manager."""
    if not _is_call(node, "keyed_lock") or not node.args:
        return False
    first = node.args[0]
    return isinstance(first, ast.Constant) and first.value == LOCK_NS


def _src(node):
    try:
        return ast.unparse(node)
    except Exception:
        return "<?>"


def _walk_with_blocks(body, locked, out):
    """Statement walk that keeps the lock state across compound statements."""
    for stmt in body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if isinstance(stmt, (ast.With, ast.AsyncWith)):
            inner = locked or any(_is_profile_lock(it.context_expr)
                                  for it in stmt.items)
            _walk_with_blocks(stmt.body, inner, out)
            continue
        _collect_calls_shallow(stmt, locked, out)
        for field in ("body", "orelse", "finalbody"):
            sub = getattr(stmt, field, None)
            if sub:
                _walk_with_blocks(sub, locked, out)
        for handler in getattr(stmt, "handlers", []) or []:
            _walk_with_blocks(handler.body, locked, out)


def _collect_calls_shallow(stmt, locked, out):
    """READ/WRITE calls in ``stmt`` itself, not in its nested statement lists."""
    skip = set()
    for field in ("body", "orelse", "finalbody"):
        for sub in getattr(stmt, field, []) or []:
            for n in ast.walk(sub):
                skip.add(id(n))
    for handler in getattr(stmt, "handlers", []) or []:
        for n in ast.walk(handler):
            skip.add(id(n))
    for node in ast.walk(stmt):
        if id(node) in skip:
            continue
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if _is_call(node, READ) and node.args:
            out.append(("read", _src(node.args[0]), locked, node.lineno))
        elif _is_call(node, WRITE) and node.args:
            out.append(("write", _src(node.args[0]), locked, node.lineno))


def check_function(fn) -> list:
    """Unlocked read-modify-write pairs of one function body."""
    calls: list = []
    _walk_with_blocks(fn.body, False, calls)
    calls.sort(key=lambda c: c[3])
    bad = []
    for i, (kind_w, arg_w, locked_w, line_w) in enumerate(calls):
        if kind_w != "write":
            continue
        # The read that FEEDS this write is the last one of the same argument
        # before it. An earlier read of the same character does not make the
        # write unsafe — re-reading under the lock right before writing is the
        # correct fix, and the stale copy above it is only a decision read.
        read = None
        for cand in calls[:i]:
            if cand[0] == "read" and cand[1] == arg_w:
                read = cand
        if read is None:
            continue
        if not (read[2] and locked_w):
            bad.append((arg_w, read[3], line_w))
    return bad


def main() -> int:
    findings = []
    seen_allow = set()
    for d in SCAN_DIRS:
        base = ROOT / d
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.py")):
            rel = path.relative_to(ROOT).as_posix()
            if "/node_modules/" in rel or "/__pycache__/" in rel:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
            except Exception as e:
                print(f"  ! could not parse {rel}: {e}")
                continue
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                bad = check_function(node)
                if not bad:
                    continue
                key = f"{rel}::{node.name}"
                if key in ALLOWLIST:
                    seen_allow.add(key)
                    continue
                for arg, lr, lw in bad:
                    findings.append(f"{rel}:{lr}->{lw}  {node.name}({arg})")

    print("=" * 72)
    print("profile read-modify-write without keyed_lock('character_profile')")
    print("=" * 72)
    stale = sorted(set(ALLOWLIST) - seen_allow)
    for key in stale:
        print(f"  note: allowlist entry no longer matches a finding: {key}")
    if findings:
        print(f"\nFAIL — {len(findings)} unlocked read-modify-write pair(s):")
        for f in findings:
            print(f"  {f}")
        print("\nFix: wrap read AND write in "
              "`with keyed_lock(\"character_profile\", <name>):`, or add the "
              "site to ALLOWLIST in this file WITH the reason.")
        return 1
    print(f"\nPASS — no unlocked pairs "
          f"({len(seen_allow)} allowlisted site(s) skipped).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
