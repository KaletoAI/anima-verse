#!/usr/bin/env python3
"""Smoke: bug round 2026-11-20 — the trouser seat (``seat`` fitted / regular / relaxed), the leggings preset and the
one-time migration of pre-A233 trouser parameters.

Usage:
    ./.venv/bin/python scripts/smoke_trouser_seat.py

No server, no hub, no network, no Blender: ``garment_template`` directly; the builder module
``app/blender/scripts/garment_template_fitted.py`` is imported with stub ``bpy`` / ``bmesh`` / ``mathutils`` modules
and only its pure numpy ``trouser_seat`` is run; the migration runs in a temp world (``paths.init(<tmp>)`` before any
world-DB import) with a temp shared items file.

Expected by hand:

[P] parameters: ``seat`` is a trouser field (in ``TROUSER_FIELDS`` and ``KIND_FIELDS["trousers"]``), default
    ``regular``; a skirt's key is the same with or without a ``seat`` value (it never enters another kind's key); a
    trouser's key changes from regular to fitted. ``LEGGINGS`` = skinny / fitted / fit 0 / full, and validates to
    itself (no field reset).
[S] ``seat_spec``: fitted ease 0, drop 0, no bridge; regular ease 0.01, drop 0.02, bridge; relaxed 0.025 / 0.04.
    ``trouser_spec`` carries it as ``seat``.
[B] ``trouser_seat`` on a synthetic tube (``ring`` below): 72 vertices per ring at 5 deg steps, radius 0.15 about
    (0, 0), rings every 5 mm from z 0.8025 (just above the crotch 0.80) to the top 1.00, waistband 0.04 (its lower
    edge 0.96); the vertex at 90 deg is the cleft, 0.02 in (radius 0.13). Normals horizontal (every vertex is in a
    ring), no legs.
    - fitted: V returned unchanged.
    - regular at a ring well under the ease ramp (z 0.85: ease full from 0.96 - 0.06 = 0.90 down): the convex hull
      runs straight from the 85 deg to the 95 deg vertex, so at 90 deg it lies at 0.15 x cos 5 deg = 0.149429; the
      slice's median radius is 0.15, so the scale is 1 + 0.01 / 0.15 = 1.066667: the cleft vertex ends at
      0.149429 x 1.066667 = 0.159391 and the 0 deg vertex (a hull vertex) at 0.15 x 1.066667 = 0.16 — the cleft is
      bridged to within 0.16 - 0.159391 = 0.6 mm (it was 20 mm).
    - in the waistband (z 0.98, no ease): the cleft vertex at 0.149429 (bridged), the 0 deg vertex stays at 0.15.
[M] the migration on a temp world: W1 = trousers with length_m 0.9 / waist_height low / no leg_shape -> rise low,
    trouser_length full (0.9 >= 0.85), leg_shape straight, length_m and waist_height gone; W2 = trousers already with
    leg_shape skinny -> untouched; W3 = a skirt -> untouched; shared S1 = trousers length_m 0.5 / natural -> rise
    mid, trouser_length knee (0.40 <= 0.5 < 0.62); the world flag and the shared marker set; a second call returns
    None. ``trouser_length``: 0.3 shorts, 0.7 capri, 0.8 ankle, "x" full.
"""
import json
import math
import os
import sys
import tempfile
import types
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FAILS = []


def check(label, got, want, tol=None):
    ok = (abs(float(got) - float(want)) <= tol) if tol is not None else got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}" + ("" if ok else f" — expected {want!r}"))
    if not ok:
        FAILS.append(label)


def fitted_module():
    """The builder module with stub Blender modules (only its numpy functions are called)."""
    for name in ("bpy", "bmesh", "garment_template_drape"):
        sys.modules.setdefault(name, types.ModuleType(name))
    mu = types.ModuleType("mathutils")
    mu.Vector = tuple
    sys.modules.setdefault("mathutils", mu)
    sys.path.insert(0, str(ROOT / "app" / "blender" / "scripts"))
    import garment_template_fitted as gf
    return gf


def ring_tube():
    angles = np.radians(np.arange(0, 360, 5))
    zs = np.round(np.arange(0.8025, 1.0001, 0.005), 4)
    V, N = [], []
    for z in zs:
        for a in angles:
            r = 0.13 if abs(math.degrees(a) - 90) < 1e-6 else 0.15
            V.append([r * math.cos(a), r * math.sin(a), z])
            N.append([math.cos(a), math.sin(a), 0.0])
    n = len(angles)
    E = []
    for i in range(len(zs)):
        for j in range(n):
            E.append((i * n + j, i * n + (j + 1) % n))
            if i + 1 < len(zs):
                E.append((i * n + j, (i + 1) * n + j))
    return np.array(V), np.array(N), np.array(E, int), zs, n


def main() -> int:
    from app.core import garment_template as gt

    print("[P] parameters")
    check("seat is a trouser field", "seat" in gt.TROUSER_FIELDS and "seat" in gt.KIND_FIELDS["trousers"], True)
    check("default seat", gt.validate_params({"kind": "trousers"})[0]["seat"], "regular")
    skirt = gt.validate_params({"kind": "skirt"})[0]
    key = dict(base_sha="b" * 64, texture_sha="t" * 12, lower=[])
    check("a skirt's key ignores seat", gt.tsig({**skirt, "seat": "relaxed"}, **key), gt.tsig(skirt, **key))
    reg = gt.validate_params({"kind": "trousers", "seat": "regular"})[0]
    fit = gt.validate_params({"kind": "trousers", "seat": "fitted"})[0]
    check("a trouser's key follows seat", gt.tsig(reg, **key) != gt.tsig(fit, **key), True)
    leg, errors = gt.validate_params(gt.LEGGINGS)
    check("leggings preset", {k: leg[k] for k in gt.LEGGINGS}, dict(gt.LEGGINGS))
    check("leggings preset valid", errors, [])

    print("[S] seat_spec")
    for name, ease, drop, bridge in (("fitted", 0.0, 0.0, False), ("regular", 0.01, 0.02, True),
                                     ("relaxed", 0.025, 0.04, True)):
        sp = gt.seat_spec(name)
        check(f"{name}", (sp["ease_m"], sp["drop_m"], sp["bridge"]), (ease, drop, bridge))
    meas = {"waist_y": 1.05, "hip_y": 0.90}
    check("trouser_spec carries seat", gt.trouser_spec(reg, meas)["seat"], gt.seat_spec("regular"))

    print("[B] trouser_seat")
    gf = fitted_module()
    V, N, E, zs, n = ring_tube()
    f = {"seat": gt.seat_spec("fitted"), "centre_gap_m": gt.TROUSER_CENTRE_GAP_M}
    out, _info = gf.trouser_seat(V, N, E, f, {}, 0.0, 0.80, 1.0, 0.96)
    check("fitted: untouched", bool(np.array_equal(out, V)), True)
    f = {"seat": gt.seat_spec("regular"), "centre_gap_m": gt.TROUSER_CENTRE_GAP_M}
    out, info = gf.trouser_seat(V, N, E, f, {}, 0.0, 0.80, 1.0, 0.96)
    for z, cleft_r, side_r in ((0.8525, 0.159391, 0.16), (0.9825, 0.149429, 0.15)):
        i = int(np.argmin(np.abs(zs - z)))
        check(f"z {zs[i]}: cleft radius", float(np.linalg.norm(out[i * n + 18, :2])), cleft_r, tol=2e-4)
        check(f"z {zs[i]}: side radius", float(np.linalg.norm(out[i * n, :2])), side_r, tol=2e-4)
    check("heights kept", bool(np.array_equal(out[:, 2], V[:, 2])), True)

    print("[M] migration")
    from app.core import trouser_params_migration as tm
    for length, want in ((0.3, "shorts"), (0.5, "knee"), (0.7, "capri"), (0.8, "ankle"), (0.9, "full"), ("x", "full")):
        check(f"length {length}", tm.trouser_length(length), want)
    with tempfile.TemporaryDirectory(prefix="trouser-params-") as tmp:
        root = Path(tmp)
        for k, v in {"STORAGE_DIR": root / "world", "INSTANCE_DIR": root / "instance",
                     "ANIMATION_CLIPS_DIR": root / "clips", "ANIMATION_RIG_FILE": root / "reference.fbx"}.items():
            os.environ[k] = str(v)
        (root / "instance").mkdir()
        from app.core import paths
        paths.init(root / "world")
        paths.get_config_path().write_text(json.dumps({"packages": {"enabled": "human"}}))
        from app.core import config, db
        config.load(paths.get_config_path(), instance_path=root / "instance" / "config.json")
        db.init_schema()
        from app.models import inventory

        def piece(item_id, params):
            return {"id": item_id, "name": item_id, "category": "outfit_piece",
                    "outfit_piece": {"slots": ["bottom"], "mesh_mode": "template",
                                     "template": {"params": params, "source": "user"}}}
        shared = root / "shared" / "items.json"
        shared.parent.mkdir()
        inventory._get_shared_items_file = lambda: shared
        shared.write_text(json.dumps({"items": [
            piece("shared_s1", {"kind": "trousers", "length_m": 0.5, "waist_height": "natural"})]}))
        check("world items saved", bool(inventory._save_items([
            piece("world_w1", {"kind": "trousers", "length_m": 0.9, "waist_height": "low", "rise": "mid",
                               "fit": 0.3}),
            piece("world_w2", {"kind": "trousers", "leg_shape": "skinny", "length_m": 0.9}),
            piece("world_w3", {"kind": "skirt", "length_m": 0.4, "waist_height": "low"})])), True)
        result = tm.migrate_trouser_params_once() or {}
        check("changes", sorted(c["item"] for c in result.get("items", [])), ["shared_s1", "world_w1"])
        items = {i["id"]: i["outfit_piece"]["template"]["params"] for i in inventory._load_items(strict=True)}
        check("W1", items["world_w1"], {"kind": "trousers", "rise": "low", "fit": 0.3, "trouser_length": "full",
                                        "leg_shape": "straight"})
        check("W2 untouched", items["world_w2"], {"kind": "trousers", "leg_shape": "skinny", "length_m": 0.9})
        check("W3 untouched", items["world_w3"], {"kind": "skirt", "length_m": 0.4, "waist_height": "low"})
        data = json.loads(shared.read_text())
        check("S1", data["items"][0]["outfit_piece"]["template"]["params"],
              {"kind": "trousers", "rise": "mid", "trouser_length": "knee", "leg_shape": "straight"})
        check("shared marker", bool(data.get(tm.SHARED_KEY)), True)
        from app.models.world import get_world_setting
        check("world flag", bool(get_world_setting(tm.FLAG, strict=True)), True)
        check("second call", tm.migrate_trouser_params_once(), None)
    print("\nall checks passed" if not FAILS else f"\n{len(FAILS)} FAILED: {FAILS}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
