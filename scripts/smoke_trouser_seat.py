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

[P] parameters: ``seat`` is a trouser field (in ``TROUSER_FIELDS`` and ``KIND_FIELDS["trousers"]``). Not given, it
    follows the leg (``default_seat``): straight -> ``regular``, skinny -> ``fitted`` (a skinny piece stored before the
    field keeps its second skin); given, it is kept (skinny + regular stays regular); a stirrup is pinned whole as a
    second skin, so skinny + stirrup + regular -> fitted. A skirt's key is the same with or without a ``seat`` value
    (it never enters another kind's key); a trouser's key changes from regular to fitted. ``LEGGINGS`` = skinny /
    fitted / fit 0 / full, and validates to itself (no field reset).
[S] ``seat_spec``: fitted ease 0, no bridge; regular ease 0.01, bridge; relaxed 0.025, bridge; no crotch drop any
    more (the review of 2026-11-20: two leg walls meeting at the centre plane read as a slit). ``trouser_spec``
    carries it as ``seat``.
[B] ``trouser_seat`` on a synthetic tube (``ring_tube``): 72 vertices per ring at 5 deg steps, radius 0.15 about
    (0, 0), rings every 5 mm from z 0.7025 to the top 1.00, the crotch at 0.80, waistband 0.04 (its lower edge 0.96).
    Above the crotch the vertex at 90 deg is the cleft, 0.02 in (radius 0.13); under it (the leg) every vertex is at
    0.15. Normals horizontal, except the 0 deg vertex of the ring at z 0.9275 (normal straight up: no ring vertex).
    - fitted: V returned unchanged.
    - the hull of a slice: the 71 vertices at 0.15 (the cleft is inside); its centroid c = -(the cleft's circle point)
      / 71 = (0, -0.15 / 71) = (0, -0.00211268) (the 72 circle points sum to 0).
    - the slice's median radius about c: of the 72 distances sorted, the cleft (0.13 + 0.00211) is the smallest; the
      others are sqrt(0.0225 + 0.3 d sin a + d^2) (d = 0.00211268), ascending in sin a; the 36th and 37th of all 72 are
      the 35th and 36th of the 71 = sin a -cos 85 deg and 0: 0.14983065 and 0.15001488, median R = 0.14992276. Ease
      0.01 -> scale 1 + k with k = 0.01 / R = 0.06670101.
    - regular at z 0.8525 (ease full: 0.96 - 0.06 = 0.90 and down; both slices round it alike): the cleft's ray from c
      runs along +y and meets the hull's edge from 85 to 95 deg at y = 0.15 cos 5 deg = 0.14942920, scaled about c:
      -d + (0.14942920 + d)(1 + k) = 0.15953720. The 270 deg vertex (a hull vertex on the same ray, the other way):
      d + (0.15 - d)(1 + k) = 0.15986423. Both rays are mirror lines of their neighbourhood, so the evening keeps them.
    - in the waistband (z 0.9825, no ease): the cleft at 0.14942920 (bridged), the 270 deg vertex at 0.15.
    (Tolerance 1e-6: ``_hull2`` rounds the hull's points to 1e-6.)
    - the fill: the 0 deg vertex at z 0.9275 is no ring vertex; all its neighbours are, so its horizontal move is the
      mean of their four moves exactly. The leg (z <= 0.80): no vertex moves at or under 0.80 - 0.08 = 0.72, a leg
      vertex never moves in, the 0 deg column's move shrinks going down, and the skin between the legs (|x| < 0.03:
      the 80..100 and 260..280 deg columns) takes half its filled move (``CROTCH_STRIP_SHARE`` 0.5): run once more
      with the share at 1, its moves are exactly twice these, every other vertex's the same. Heights are never
      changed.
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
    zs = np.round(np.arange(0.7025, 1.0001, 0.005), 4)
    V, N = [], []
    for z in zs:
        for a in angles:
            r = 0.13 if abs(math.degrees(a) - 90) < 1e-6 and z > 0.80 else 0.15
            V.append([r * math.cos(a), r * math.sin(a), z])
            N.append([0.0, 0.0, 1.0] if abs(z - 0.9275) < 1e-6 and abs(a) < 1e-6 else [math.cos(a), math.sin(a), 0.0])
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
    check("default seat, straight", gt.validate_params({"kind": "trousers"})[0]["seat"], "regular")
    check("default seat, skinny", gt.validate_params({"kind": "trousers", "leg_shape": "skinny"})[0]["seat"], "fitted")
    check("skinny + regular kept", gt.validate_params({"kind": "trousers", "leg_shape": "skinny",
                                                       "seat": "regular"})[0]["seat"], "regular")
    check("stirrup -> fitted", gt.validate_params({"kind": "trousers", "leg_shape": "skinny", "hem": "stirrup",
                                                   "seat": "regular"})[0]["seat"], "fitted")
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
    for name, ease, bridge in (("fitted", 0.0, False), ("regular", 0.01, True), ("relaxed", 0.025, True)):
        sp = gt.seat_spec(name)
        check(f"{name}", (sp["ease_m"], sp["bridge"], "drop_m" in sp), (ease, bridge, False))
    meas = {"waist_y": 1.05, "hip_y": 0.90}
    check("trouser_spec carries seat", gt.trouser_spec(reg, meas)["seat"], gt.seat_spec("regular"))

    print("[B] trouser_seat")
    gf = fitted_module()
    V, N, E, zs, n = ring_tube()
    f = {"seat": gt.seat_spec("fitted")}
    out, _info = gf.trouser_seat(V, N, E, f, 0.0, 0.80, 1.0, 0.96)
    check("fitted: untouched", bool(np.array_equal(out, V)), True)
    f = {"seat": gt.seat_spec("regular")}
    out, info = gf.trouser_seat(V, N, E, f, 0.0, 0.80, 1.0, 0.96)
    ring = lambda z: int(np.argmin(np.abs(zs - z)))
    for z, cleft_r, back_r in ((0.8525, 0.15953720, 0.15986423), (0.9825, 0.14942920, 0.15)):
        i = ring(z)
        check(f"z {zs[i]}: cleft radius", float(np.linalg.norm(out[i * n + 18, :2])), cleft_r, tol=1e-6)
        check(f"z {zs[i]}: 270 deg radius", float(np.linalg.norm(out[i * n + 54, :2])), back_r, tol=1e-6)
    check("heights kept", bool(np.array_equal(out[:, 2], V[:, 2])), True)
    D = out[:, :2] - V[:, :2]
    k = ring(0.9275) * n
    nb = [k + 1, k + n - 1, k + n, k - n]
    check("fill: the up-facing vertex moves as its neighbours' mean", float(np.abs(D[k] - D[nb].mean(0)).max()), 0.0,
          tol=1e-9)
    check("fill: the up-facing vertex moved", bool(np.linalg.norm(D[k]) > 1e-3), True)
    leg = V[:, 2] <= 0.80
    rad = np.linalg.norm(out[:, :2], axis=1) - np.linalg.norm(V[:, :2], axis=1)
    check("leg: nothing moves at or under 0.72", float(np.abs(D[V[:, 2] <= 0.72 + 1e-9]).max()), 0.0, tol=0.0)
    check("leg: never moves in", float(rad[leg].min()) >= -1e-9, True)
    col = [float(np.linalg.norm(D[ring(z) * n])) for z in zs if z <= 0.80]
    check("leg: the 0 deg column's move shrinks going down", bool(np.all(np.diff(col) >= -1e-12)), True)
    check("leg: the 0 deg column moves under the crotch", col[-1] > 1e-3, True)
    strip = leg & (np.abs(V[:, 0]) < 0.03)
    check("strip share", gf.CROTCH_STRIP_SHARE, 0.5)
    gf.CROTCH_STRIP_SHARE = 1.0
    full, _info = gf.trouser_seat(V, N, E, f, 0.0, 0.80, 1.0, 0.96)
    gf.CROTCH_STRIP_SHARE = 0.5
    Df = full[:, :2] - V[:, :2]
    check("strip: half its filled move", float(np.abs(2.0 * D[strip] - Df[strip]).max()), 0.0, tol=1e-12)
    check("strip: it does move", bool(np.abs(Df[strip]).max() > 1e-4), True)
    check("strip: nothing else changes", float(np.abs(D[~strip] - Df[~strip]).max()), 0.0, tol=0.0)

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
