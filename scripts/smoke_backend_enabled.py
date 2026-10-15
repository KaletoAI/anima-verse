#!/usr/bin/env python3
"""Smoke run for two selection rules of the image service:

  IMG-5 (a)  globally disabled backends are never selectable, including
             character-scoped selection and availability checks.
  IMG-4      ``generate_mesh`` never falls back from an explicit pick: an
             explicitly named alias that is unavailable (or delivers the
             wrong rig) is an ERROR, not an invitation to render on the
             cheapest other one.

No server, no network, no world DB: fake backends drive ``BackendPool``
directly, and the mesh case runs against an ``ImageService`` whose only
live part is that pool.

Usage:  ./.venv/bin/python scripts/smoke_backend_enabled.py

Hand-derived expectations
---------------------------------------------------------------------------
One image backend ``Backend1``, built once per row with its global flag
and availability. Selection requires BOTH to be on:

  global | available | selectable
  -------+-----------+-----------
   on    | yes       | yes      [1a]
   off   | yes       | no       [1b]
   on    | no        | no       [1c]
   off   | no        | no       [1d]

``list_available_backends(character)`` and ``_wait_for_backend(character)``
must answer the same way [2, 4], since the admin lists and the engine must
not disagree about what exists. Disabled backends must not be probed.

Mesh [3]: MeshA (cost 2, available), MeshB (cost 1, offline), MeshGen
(cost 1, available) are all img2mesh. An explicit unavailable MeshB fails
without rendering; an explicit MeshGen runs and its empty delivery fails
storage. No explicit pick falls back. Empty mesh routing chooses MeshGen
by cost. Rig identity is checked only on mesh2rig delivery in the rig split
smoke, never used to filter the mesh backend inventory.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.imagegen.base import ImageBackend  # noqa: E402
from app.imagegen.selection import BackendPool  # noqa: E402
from app.imagegen.service import ImageService  # noqa: E402

FAILED = []


def check(label, got, expected):
    ok = got == expected
    print(f"  {'OK ' if ok else 'FAIL'} {label}: {got!r} (expected {expected!r})")
    if not ok:
        FAILED.append(label)


class _Fake(ImageBackend):
    def __init__(self, name, *, enabled=True, available=True,
                 media="image", cost=1.0):
        super().__init__(name, "http://localhost", cost, "fake", "FAKE_")
        self.MEDIA_TYPE = media
        self.instance_enabled = enabled
        self._available = available
        self.available = available
        if media == "mesh":
            self.category = "img2mesh"

    def check_availability(self) -> bool:
        self.availability_checks = getattr(self, "availability_checks", 0) + 1
        return self.available

    def _generate(self, prompt, negative_prompt, params):
        return []


# --------------------------------------------------------------------------
print("[1] global enablement and availability (_select_backend_for_agent)")
TABLE = [
    ("1a global on, available", True, True, "Backend1"),
    ("1b global off, available", False, True, None),
    ("1c global on, unavailable", True, False, None),
    ("1d global off, unavailable", False, False, None),
]
for label, global_on, available, expected in TABLE:
    b = _Fake("Backend1", enabled=global_on, available=available)
    pool = BackendPool([b])
    picked = pool._select_backend_for_agent("demo")
    check(label, getattr(picked, "name", None), expected)
    picked = pool._select_backend()
    check(label + " (global selection)", getattr(picked, "name", None), expected)

print("[2] list_available_backends answers the same table")
for label, global_on, available, expected in TABLE:
    b = _Fake("Backend1", enabled=global_on, available=available)
    pool = BackendPool([b])
    names = [x.name for x in pool.list_available_backends("demo")]
    check(label.replace("1", "2", 1), names,
          [expected] if expected else [])

print("[4] wait selection respects global enablement without probing disabled entries")
for label, global_on, available, expected in TABLE:
    b = _Fake("Backend1", enabled=global_on, available=available)
    pool = BackendPool([b])
    picked = pool._wait_for_backend("demo")
    check(label.replace("1", "4", 1), getattr(picked, "name", None), expected)
    check(label + " availability probes",
          getattr(b, "availability_checks", 0), int(global_on))

# --------------------------------------------------------------------------
print("[3] generate_mesh never falls back from an explicit pick")
mesh_a = _Fake("MeshA", media="mesh", cost=2.0)
mesh_b = _Fake("MeshB", media="mesh", available=False, cost=1.0)
mesh_gen = _Fake("MeshGen", media="mesh", cost=1.0)

svc = ImageService.__new__(ImageService)
svc._pool = BackendPool([mesh_a, mesh_b, mesh_gen])
used = []


def _fake_runner(primary, op, character_name=""):
    """Stands in for the pool's runner: records the chosen backend and
    answers an empty delivery, so no channel or gateway is touched."""
    used.append(primary.name)
    return {"blobs": [], "files": []}, primary


svc.run_on_backend = _fake_runner

used.clear()
res = svc.generate_mesh("/tmp/none.png", "/tmp/out.glb",
                        backend_glob="MeshB")
check("3a explicit unavailable: ok", res.get("ok"), False)
check("3a explicit unavailable: error names it",
      "MeshB" in str(res.get("error")), True)
check("3a explicit unavailable: nothing rendered", used, [])

used.clear()
res = svc.generate_mesh("/tmp/none.png", "/tmp/out.glb",
                        backend_glob="MeshGen")
check("3b explicit img2mesh: ok", res.get("ok"), False)
check("3b img2mesh delivery checked", res.get("error"), "no model file delivered")
check("3b any img2mesh can be explicitly selected", used, ["MeshGen"])

used.clear()
svc.generate_mesh("/tmp/none.png", "/tmp/out.glb", backend_glob="")
check("3c no glob picks by cost", used, ["MeshGen"])

print()
if FAILED:
    print(f"FAILED ({len(FAILED)}): " + ", ".join(FAILED))
    sys.exit(1)
print("all checks passed")
sys.exit(0)
