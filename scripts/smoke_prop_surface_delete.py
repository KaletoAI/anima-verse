#!/usr/bin/env python3
"""Smoke check for DELETING a baked walkable surface (plan-surface-delete.md).

Usage:  ./.venv/bin/python scripts/smoke_prop_surface_delete.py

Runs entirely in a temporary storage directory — no world file is touched, no
Blender is called: deleting a lattice is a file operation plus two guards, and
the fixture writes the sidecar the bake would have written.

--- PART 0: model_surface.delete_surface -------------------------------------
The lattice of a model lives in `<model file>.surface.json` (SURFACE_SUFFIX), so
deleting it is `surface_path(model).unlink()` — expressed as a state, not as an
event: True means "there was one and it is gone", False means "there was none".
The fixture writes a COMPLETE, VALID sidecar by hand — `_valid` demands the
current SURFACE_VERSION, the eight PAYLOAD_KEYS, the model file's own
(name, size, mtime) and the fix the lattice was baked under — so the state
before the delete is "baked" and the state after it can only be "missing":
  before:  read_surface != None, surface_status = baked 3x3 @ 0.25
  delete:  True, and the file is gone from disk
  after:   read_surface = None, surface_status = missing
  again:   False (nothing left to delete), state still missing
The parsed-sidecar cache is keyed by (path, size, mtime), so a deleted file can
never be answered from it — but the entry has to GO all the same, because
nothing else would ever evict it: a file that is read, deleted and re-baked
inside one mtime tick would otherwise be served from the version that was
deleted. Hence the check that the read cache holds no entry for the path.

--- PART 1: props.delete_surface_for ----------------------------------------
A prop variant names its mesh through `model_path(prop_id, variant=idx)` — the
same read the bake writes through — so the lattice a delete removes is exactly
the one the bake would overwrite. Fixture: prop `demo-prop` with two active
variants on the stems `model` (index 0) and `model-v2` (index 1), one .glb
each, a hand-written lattice beside each:
  delete variant 1  -> True; variant 1 missing, variant 0 STILL baked
  delete variant 1  -> False (idempotent, and it stays missing)
  delete variant 9  -> False (no such variant: no mesh, no lattice)
  delete on 'nope'  -> False (no such prop)
  delete variant None -> True (every ACTIVE variant; variant 0 was the last one)
                         and False on the repeat
A DELETE WHILE A BAKE RUNS IS REFUSED, not merely useless: the running job
writes the file again the moment its Blender run returns, so the panel would
show a lattice the admin just removed. The condition is the module's own
`_surface_building` set (one bake per prop, `bake_surfaces`), the answer is
`SurfaceBakeRunning` — the route turns it into 409 — and the file survives.
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FAILURES = []


def check(label, ok, detail=""):
    print(f"  {'✓' if ok else '✗'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


def write_lattice(model: Path, rotation=None):
    """The sidecar a bake would have written for ``model``: complete (all eight
    payload keys), current version, and stamped with the model file's identity
    plus the fix it was baked under — anything less reads as "no surface"."""
    from app.core import model_surface as ms
    surface = {
        "version": ms.SURFACE_VERSION,
        "source": ms._source_of(model),
        "rotation": {"x": 0.0, "y": 0.0, "z": 0.0} if rotation is None else rotation,
        "baked_at": "2026-08-29T00:00:00Z",
        "blender": "smoke",
        "step": 0.25, "origin": [-0.25, -0.25], "cols": 3, "rows": 3,
        "values": [0, 0, 0, 0, 10, 0, 0, 0, 0],
        "box_min": [-0.25, 0, -0.25], "box_max": [0.25, 0.1, 0.25],
        "extent_snapped": [0.5, 0.1, 0.5],
        "hits": 9, "target_m": 0.0, "measure": "xyz", "step_world": 0.25,
    }
    ms.surface_path(model).write_text(json.dumps(surface), encoding="utf-8")


def part0():
    """`delete_surface` on a bare model file: a state, not an event."""
    from app.core import model_surface as ms
    fix = {"x": 0, "y": 0, "z": 0}
    with tempfile.TemporaryDirectory() as tmp:
        model = Path(tmp) / "thing.glb"
        model.write_bytes(b"not really a glb")     # only its stat is read
        check("nothing to delete answers False", ms.delete_surface(model) is False)

        write_lattice(model)
        check("the fixture is a VALID lattice", ms.read_surface(model, fix) is not None)
        st = ms.surface_status(model, fix)
        check("status baked 3x3 @ 0.25",
              (st["state"], st["cols"], st["rows"], st["step"]) == ("baked", 3, 3, 0.25),
              str(st))

        check("delete answers True", ms.delete_surface(model) is True)
        check("the sidecar is gone", not ms.surface_path(model).exists())
        check("the model itself stands", model.exists())
        check("read_surface is None", ms.read_surface(model, fix) is None)
        check("status missing", ms.surface_status(model, fix)["state"] == "missing")
        check("the second delete answers False", ms.delete_surface(model) is False)
        check("status still missing", ms.surface_status(model, fix)["state"] == "missing")

        # The parse cache must not keep what was deleted (see the docstring).
        write_lattice(model)
        ms.read_surface(model, fix)
        sp = str(ms.surface_path(model))
        check("the read filled the parse cache",
              any(k[0] == sp for k in ms._load_cache))
        ms.delete_surface(model)
        check("the delete emptied it",
              not any(k[0] == sp for k in ms._load_cache))


def part1():
    """`delete_surface_for` on a prop variant, and the running bake's refusal."""
    with tempfile.TemporaryDirectory() as tmp:
        from app.core import paths
        paths.init(tmp)
        from app.core import props

        pid = "demo-prop"
        d = Path(tmp) / "props" / pid
        d.mkdir(parents=True)
        (d / "sidecar.json").write_text(json.dumps({
            "name": "Demo prop",
            "model_variants": [{"stem": "model", "active": True},
                               {"stem": "model-v2", "active": True}],
        }), encoding="utf-8")
        meshes = {}
        for idx, stem in enumerate(("model", "model-v2")):
            p = d / f"{stem}.glb"
            p.write_bytes(b"not really a glb")
            write_lattice(p)
            meshes[idx] = p
        check("variant 0 resolves to its mesh",
              props.model_path(pid, variant=0) == meshes[0])
        check("both variants read baked",
              [props.surface_status_for(pid, i)["state"] for i in (0, 1)]
              == ["baked", "baked"])

        check("delete variant 1 answers True", props.delete_surface_for(pid, 1) is True)
        check("variant 1 is missing", props.surface_status_for(pid, 1)["state"] == "missing")
        check("variant 0 is untouched", props.surface_status_for(pid, 0)["state"] == "baked")
        check("the repeat answers False", props.delete_surface_for(pid, 1) is False)
        check("variant 1 stays missing",
              props.surface_status_for(pid, 1)["state"] == "missing")
        check("an unknown variant answers False", props.delete_surface_for(pid, 9) is False)
        check("an unknown prop answers False", props.delete_surface_for("nope", 0) is False)

        # A running bake is refused, and the lattice survives the refusal.
        with props._lock:
            props._surface_building.add(pid)
        try:
            props.delete_surface_for(pid, 0)
            check("a running bake refuses the delete", False, "no exception")
        except props.SurfaceBakeRunning:
            check("a running bake refuses the delete", True)
        check("the lattice survived the refusal",
              props.surface_status_for(pid, 0)["state"] == "baked")
        with props._lock:
            props._surface_building.discard(pid)

        check("variant None takes every active variant",
              props.delete_surface_for(pid, None) is True)
        check("variant 0 is missing now",
              props.surface_status_for(pid, 0)["state"] == "missing")
        check("nothing left, so False",
              props.delete_surface_for(pid, None) is False)


def main():
    print("smoke_prop_surface_delete — part 0: model_surface.delete_surface")
    part0()
    print("smoke_prop_surface_delete — part 1: props.delete_surface_for")
    part1()
    if FAILURES:
        print(f"\n{len(FAILURES)} FAILED: {FAILURES}")
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
