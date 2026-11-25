#!/usr/bin/env python3
"""Guard: every key an ``add_memory(extra_meta=...)`` caller writes is in META_KEYS.

Usage: ./.venv/bin/python scripts/smoke_memory_meta_keys.py

Why: ``add_memory`` merges ``extra_meta`` into the meta column past the
whitelist, so the insert is complete -- but every later write-back
(``save_memories`` -> ``_build_meta``, e.g. the access-count bump of
``retrieve_relevant_memories``) keeps only META_KEYS. A key missing there
survives exactly until the first write-back (2026-09-11 for the provenance
fields, again 2026-10-20 for the pair-interaction memory).

Part A, static (AST, no import of app code): every call named ``add_memory``
under app/ and plugins/ that passes ``extra_meta=`` is resolved to its key
set -- a dict literal, or a local name built from a dict literal plus
``name["k"] = ...`` assignments in the same function; ``x or None`` is
read as ``x``. A form the checker cannot resolve is a finding too (write
the keys out literally). META_KEYS is read from app/models/memory.py by AST.
Symlinked pack folders are not followed (Path.rglob does not); their
callers are outside this repository.

  Self-test sample (hand-counted): a literal {"a","b"} call, a name built
  from {"c"} plus n["d"] = 1, an ``n or None`` call and a call passing
  a function result -> resolved key sets {a,b}, {c,d}, {c,d} and one
  unresolvable finding.

  Repository, hand-derived from ``git grep extra_meta -- app plugins``
  (2026-11-25): at least 5 callers -- day_consolidation (date_key),
  interaction_engine (interaction_id, pose_key, location_id, room_id,
  started_at_game, ended_at_game, reason), item_reading (item_id, owner,
  secret_id, ref), memory_service (source, event_id, delay_minutes),
  scene_manager (location_id, room_id, participants, scene_id). Expected: 0
  missing keys, 0 unresolvable callers.

Part B, runtime (temp world): add_memory with the interaction keys, then one
write-back save_memories(name, load_memories(name)) -> all seven keys read
back with the values written (interaction_id "i1", reason "done", ...).
"""
import ast
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

failed = 0


def ok(label, cond, detail=""):
    global failed
    print(("  OK  " if cond else "  FAIL ") + label + (f" -- {detail}" if detail and not cond else ""))
    if not cond:
        failed += 1


def _dict_keys(node):
    if not isinstance(node, ast.Dict):
        return None
    keys = set()
    for k in node.keys:
        if not (isinstance(k, ast.Constant) and isinstance(k.value, str)):
            return None
        keys.add(k.value)
    return keys


def _name_keys(func, name):
    """Keys of local ``name`` in ``func``: dict-literal assignments plus
    subscript stores with a constant string key. None when any assignment
    to the name is something else."""
    keys, seen = set(), False
    for node in ast.walk(func):
        targets, value = [], None
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        for t in targets:
            if isinstance(t, ast.Name) and t.id == name:
                got = _dict_keys(value)
                if got is None:
                    return None
                keys |= got
                seen = True
            elif (isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name)
                  and t.value.id == name):
                sl = t.slice
                if not (isinstance(sl, ast.Constant) and isinstance(sl.value, str)):
                    return None
                keys.add(sl.value)
    return keys if seen else None


def _resolve(value, func):
    if isinstance(value, ast.BoolOp) and isinstance(value.op, ast.Or):
        return _resolve(value.values[0], func)
    if isinstance(value, ast.Dict):
        return _dict_keys(value)
    if isinstance(value, ast.Name) and func is not None:
        return _name_keys(func, value.id)
    return None


def scan_source(src, filename="<sample>"):
    """[(line, keys-or-None)] for every add_memory(..., extra_meta=...) call."""
    tree = ast.parse(src, filename)
    found = []

    def visit(node, func):
        for child in ast.iter_child_nodes(node):
            inner = child if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else func
            if isinstance(child, ast.Call):
                f = child.func
                fname = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
                if fname == "add_memory":
                    for kw in child.keywords:
                        if kw.arg == "extra_meta":
                            found.append((child.lineno, _resolve(kw.value, func)))
            visit(child, inner)

    visit(tree, None)
    return found


def meta_keys():
    tree = ast.parse((ROOT / "app/models/memory.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "META_KEYS" for t in node.targets):
            return {e.value for e in node.value.elts}
    raise SystemExit("META_KEYS not found in app/models/memory.py")


SAMPLE = '''
def one():
    add_memory("x", "y", extra_meta={"a": 1, "b": 2})
def two():
    n = {"c": 1}
    n["d"] = 1
    add_memory("x", "y", extra_meta=n)
    add_memory("x", "y", extra_meta=n or None)
def three():
    add_memory("x", "y", extra_meta=build())
'''

print("[self-test]")
got = scan_source(SAMPLE)
ok("sample resolves to {a,b}, {c,d}, {c,d}, unresolvable",
   [k for _, k in got] == [{"a", "b"}, {"c", "d"}, {"c", "d"}, None], repr(got))

print("[A] repository callers")
allowed = meta_keys()
callers, missing, unresolved = [], [], []
for base in ("app", "plugins"):
    for path in sorted((ROOT / base).rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        try:
            src = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if "extra_meta" not in src:
            continue
        for line, keys in scan_source(src, rel):
            callers.append(f"{rel}:{line}")
            if keys is None:
                unresolved.append(f"{rel}:{line}")
            else:
                missing += [f"{rel}:{line}:{k}" for k in sorted(keys - allowed)]
print("   callers:", ", ".join(callers))
ok(f"at least 5 extra_meta callers found ({len(callers)})", len(callers) >= 5)
ok("every caller's keys resolve", not unresolved, ", ".join(unresolved))
ok("every extra_meta key is in META_KEYS", not missing, ", ".join(missing))

print("[B] write-back keeps the keys")
from app.core import paths  # noqa: E402
with tempfile.TemporaryDirectory() as tmp:
    paths.init(Path(tmp))
    from app.core import db  # noqa: E402
    db.init_schema()
    from app.models import memory  # noqa: E402
    from app.models.character import save_character_profile  # noqa: E402
    save_character_profile("demo", {"name": "demo", "language": "en"}, create_new=True)
    written = {"interaction_id": "i1", "pose_key": "hug", "location_id": "loc1",
               "room_id": "r1", "started_at_game": "Y0001-D001T10:00:00",
               "ended_at_game": "Y0001-D001T10:05:00", "reason": "done"}
    memory.add_memory("demo", "A hug with someone.", memory_type="episodic",
                      extra_meta=dict(written))
    memory.save_memories("demo", memory.load_memories("demo"))
    back = memory.load_memories("demo")
    got = {k: back[0].get(k) for k in written} if back else {}
    ok("all seven keys survive one write-back", got == written, repr(got))

print("PASSED" if not failed else f"FAILED: {failed}")
sys.exit(1 if failed else 0)
