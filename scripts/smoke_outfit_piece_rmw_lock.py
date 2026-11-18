#!/usr/bin/env python3
"""AST guard: no ``outfit_piece`` read-modify-write without ``inventory.outfit_piece_lock``.

Usage:
    ./.venv/bin/python scripts/smoke_outfit_piece_rmw_lock.py

Pure static check — no world DB, no server, no storage directory.

WHY (review 05#12): an item's ``outfit_piece`` is shared by every wearer, and ``update_item`` replaces every key
the update names. A writer that does ``item = get_item(X)`` → copies the whole piece → changes one key →
``update_item(X, {"outfit_piece": piece})`` puts back the OLD value of every other key another thread wrote in
between. The serializer is ``inventory.outfit_piece_lock(item_id)`` (keyed by the ITEM, not the character).

The rule, derived by hand from that contract: in one function body (a nested ``def`` is its own body), a call
``get_item(A)`` and a LATER call ``update_item(B, {...})`` whose second argument is a dict literal naming the key
``"outfit_piece"`` — where A and B have the same source text — form a read-modify-write; BOTH calls must sit
inside a ``with`` whose items include a call to ``outfit_piece_lock(...)`` (bare or as an attribute). The lock
key is not compared. Scanned: ``app/**`` and ``plugins/**`` (symlinked pack folders followed).

Second rule (whole-item writers, review 05#12 follow-up): in one function body, a call ``_load_items()`` /
``_load_shared_items()`` followed by ``_save_items(X)`` / ``_save_shared_items(X)`` is a snapshot write-back. The
save must sit inside a ``with`` naming ``item_write_lock`` / ``_item_locks`` / ``outfit_piece_lock`` — unless it
is ``_save_items([one_item])`` (a single-row upsert, list literal of one element: it cannot undo another item).
A function named ``*_locked`` (its caller holds the locks) is skipped. Boot/one-shot migrations that run before the server serves stand in ALLOWLIST with their reason.

The second half proves the guard bites: a synthetic unlocked writer must be reported, a locked one must not.

EXPECTED RESULT: zero violations; the synthetic check reports exactly ``bad`` and ``bad_snapshot``.
"""
import ast
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST = {
    # "path::function": reason
}
SNAPSHOT_ALLOW = {
    "app/core/figure_migration.py::migrate_modes_once": "boot one-shot migration, runs before the server serves",
    "app/core/figure_migration.py::redefault_modes_once": "boot one-shot migration, runs before the server serves",
    "app/core/shell_mode_migration.py::migrate_shell_mode_once": "boot one-shot migration, runs before the server serves",
}
LOCKS = {"item_write_lock", "_item_locks", "outfit_piece_lock"}


def _name(func):
    return func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ""


def _is_lock(withnode, names=("outfit_piece_lock",)):
    return any(isinstance(i.context_expr, ast.Call) and _name(i.context_expr.func) in names
               for i in withnode.items)


def _scan_snapshot(fn):
    loads, saves = [], []

    def walk(node, locked):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue
            inner = locked or (isinstance(child, (ast.With, ast.AsyncWith)) and _is_lock(child, LOCKS))
            if isinstance(child, ast.Call):
                n = _name(child.func)
                if n in ("_load_items", "_load_shared_items"):
                    loads.append(child.lineno)
                elif n in ("_save_items", "_save_shared_items") and not locked:
                    single = (n == "_save_items" and child.args and isinstance(child.args[0], ast.List)
                              and len(child.args[0].elts) == 1)
                    if not single:
                        saves.append(child.lineno)
            walk(child, inner)

    walk(fn, False)
    return [(min(loads), w) for w in saves if loads and min(loads) <= w]


def _names_piece(call):
    return (len(call.args) >= 2 and isinstance(call.args[1], ast.Dict)
            and any(isinstance(k, ast.Constant) and k.value == "outfit_piece" for k in call.args[1].keys))


def _scan_body(fn):
    reads, writes = [], []

    def walk(node, locked):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue
            inner = locked or (isinstance(child, (ast.With, ast.AsyncWith)) and _is_lock(child))
            if isinstance(child, ast.Call) and child.args:
                key = ast.unparse(child.args[0])
                if _name(child.func) == "get_item":
                    reads.append((key, locked, child.lineno))
                elif _name(child.func) == "update_item" and _names_piece(child):
                    writes.append((key, locked, child.lineno))
            walk(child, inner)

    walk(fn, False)
    out = []
    for wkey, wlocked, wline in writes:
        for rkey, rlocked, rline in reads:
            if rkey == wkey and rline <= wline and not (wlocked and rlocked):
                out.append((rline, wline))
    return out


def scan_source(src, label):
    violations = []
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for rline, wline in _scan_body(node):
                tag = f"{label}::{node.name}"
                if tag not in ALLOWLIST:
                    violations.append(f"{tag} read l.{rline} / write l.{wline}")
            # A ``*_locked`` helper documents that its caller holds ``_item_locks``.
            for rline, wline in ([] if node.name.endswith("_locked") else _scan_snapshot(node)):
                tag = f"{label}::{node.name}"
                if tag not in SNAPSHOT_ALLOW:
                    violations.append(f"{tag} snapshot load l.{rline} / unlocked save l.{wline}")
    return violations


def files():
    for top in ("app", "plugins"):
        for dirpath, _dirs, names in os.walk(ROOT / top, followlinks=True):
            for n in names:
                if n.endswith(".py"):
                    yield Path(dirpath) / n


def main():
    violations = []
    for f in files():
        try:
            violations += scan_source(f.read_text(encoding="utf-8"), str(f.relative_to(ROOT)))
        except SyntaxError:
            continue
    synthetic = '''
def bad(i):
    item = inventory.get_item(i)
    inventory.update_item(i, {"outfit_piece": dict(item["outfit_piece"])})
def good(i):
    with inventory.outfit_piece_lock(i):
        item = inventory.get_item(i)
        inventory.update_item(i, {"outfit_piece": dict(item["outfit_piece"])})
def bad_snapshot(i):
    items = _load_items()
    _save_items(items)
def good_snapshot(i):
    with _item_locks(i):
        items = _load_items()
        _save_items(items)
def single_row(i):
    items = _load_items()
    _save_items([items[0]])
'''
    syn = scan_source(synthetic, "synthetic")
    ok = True
    for v in violations:
        print("FAIL unlocked outfit_piece RMW:", v)
        ok = False
    if sorted(v.split(" ")[0] for v in syn) != ["synthetic::bad", "synthetic::bad_snapshot"]:
        print("FAIL guard self-check:", syn)
        ok = False
    print("ALL OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
