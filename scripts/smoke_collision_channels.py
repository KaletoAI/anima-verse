#!/usr/bin/env python3
"""Smoke: declared channels resolved into bind space (collision v7) — ``app/core/collision_channels.py``, the record in
``app/core/collision.py``, the override route ``POST /characters/{c}/model3d/collision/channels``, the model overview's
collision step and the Improvements ``collision_capsules`` type.

Usage:
    ./.venv/bin/python scripts/smoke_collision_channels.py

Plan docs/superpowers/plans/2026-11-14-cross-person-collision.md, Task 12; spec
docs/superpowers/specs/2026-11-13-cross-person-collision-design.md Part 4. Runs without the server, against a temp world +
instance with a temp ``plugins/`` dir holding one synthetic package ``pkgx`` (neutral ids); no live world, no Blender,
no network.

FIXTURE
- The synthetic body of ``scripts/smoke_collision_capsules.py`` (``make_body``; it already carries LeftToeBase
  (0.1, 0.02, 0.12) and RightToeBase): Hips (0, 1.0, 0), Spine1 (0, 1.2, 0), Spine2 (0, 1.35, 0), Neck (0, 1.5, 0),
  Head (0, 1.6, 0), LeftArm (0.2, 1.45, 0), RightArm (−0.2, 1.45, 0), LeftFoot (0.1, 0.08, 0), the legs at x ±0.1.
  Its 18 capsules (that smoke's [1]): thighs r 0.066 around (±0.1, 0.95…0.5, 0), hips r 0.1000 Hips → Spine1,
  spine r 0.1005 Spine1 → Spine2, outer_hips (0, 1.0…1.1, 0) / outer_waist (0, 1.1…1.2, 0) r 0.10 — both start at
  Hips —, outer_spine (0, 1.2…1.35, 0) r 0.10, head, arms, shoulders, chest far above.
- Package ``pkgx`` (apply_to "*"), slot ``slotx`` (covered_by [bottom], attribute kind [a, b], rig ``pkgx_chain`` op
  appendage_chain, two links PkgxA ← Hips, PkgxB ← PkgxA) with two regions:
  - ``chan``: bone Hips, offset [0, −0.10, 0.05], axis [0, 1, 0], depth 0.12, radius 0.02, cone_deg 30, funnel 0.03,
    accepts {ops: [appendage_chain]} (min_length / compress_min default 1.0, exposed_only default True);
  - ``rchan``: the same with from_rig pkgx_chain, applies_to {attributes.kind: [b]} (only in [3]).
- Character ``demo`` (template human-default, slotx {kind a}): base00000001.glb (sidecar {rig mixamo, base True}) and
  outfit aaaaaaaaaaaa.glb (the same bytes; sidecar {rig mixamo, source base_body, base_signature base00000001,
  base_model_sha256 = the base's sha, pieces {bottom: item_pants}}). Character ``demo2``: the base alone.
  ``model3d._current_base`` is pinned per character; ``motion_item_cache.item_snapshot`` is stubbed.

Expected, derived by hand:
[1] body_frame of the fixture joints: up = unit(Head − Hips) = unit(0, 0.6, 0) = (0, 1, 0); LeftArm − RightArm =
    (0.4, 0, 0), nothing along up → side (1, 0, 0); front = side × up = (1,0,0) × (0,1,0) = (0, 0, 1), and
    (LeftToeBase − LeftFoot) = (0, −0.06, 0.12) has dot 0.12 ≥ 0 → kept. With LeftToeBase at z −0.12 the dot is
    −0.12 → front (0, 0, −1). Without LeftArm → ValueError.
[2] Declared placement (resolve_channels on the fitted capsules, everything exposed): a_pos = Hips + offset along
    (side, up, front) = (0, 1.0, 0) + (0, −0.10, 0.05) = (0, 0.90, 0.05); axis (0, 1, 0) → b_pos = a_pos + 0.12·up =
    (0, 1.02, 0.05); r 0.02, cone 30, funnel 0.03, accepts [appendage_chain], min_length 1.0, compress_min 1.0, no
    interaction_kinds key; a = b = "mixamorig:Hips"; placement "declared"; applied None; frame as [1].
    suppress — the channel segment C is x = 0, z = 0.05, y ∈ [0.90, 1.02]; a capsule is listed when it starts at
    Hips (the owning-joint rule) or its bind segment comes within r_capsule + 0.02 of C:
      hips (a Hips; also 0.05 from C), outer_hips (a Hips), outer_waist (a Hips; also |(0,1.1,0) − (0,1.02,0.05)| =
        sqrt(0.08² + 0.05²) = 0.094340 ≤ 0.12) → listed;
      spine / outer_spine: nearest (0, 1.2, 0), sqrt(0.18² + 0.05²) = 0.186815 > 0.1005 + 0.02 = 0.1205 (0.12);
      thighs: overlap y ∈ [0.90, 0.95] at sqrt(0.1² + 0.05²) = 0.111803 > 0.066 + 0.02 = 0.086;
      shins (top (±0.1, 0.5, 0)) 0.415, arms (from (±0.2, 1.45, 0)) 0.477, shoulders 0.436, chest / head farther.
    → suppress [hips, outer_hips, outer_waist] in payload order. NOTE: the brief lists [hips, outer_hips]; outer_waist
    also starts at Hips (the table, Ruling of Task 2: Hips-rooted suppress lists include it), so the rule it states
    lists three.
[3] Rig placement (``rchan``, kind b): the sidecar ``extension_rig`` {status applied, groups [pkgx_chain], metrics
    {pkgx_chain: {opening {centre [0, 0.88, 0.02], axis [0, 2, 0]}}}} → a_pos (0, 0.88, 0.02), axis unit (0, 1, 0),
    b_pos (0, 1.00, 0.02), placement "rig"; suppress again [hips, outer_hips, outer_waist] (the thighs now at
    sqrt(0.1² + 0.02²) = 0.101980 > 0.086). Without the opening metric → no channel, skipped "Rig pkgx_chain reports no
    opening …"; with status "failed" → skipped "Rig pkgx_chain is not built on this model" (never the declared offset).
    The opening is part of channels_sig (another centre → another sig).
[4] Override {offset_mm [0, 10, −5], radius_scale 1.5, depth_scale 0.5, cone_deg 20} (through the profile's
    model3d_opts.collision_channels): a_pos = (0, 0.90 + 0.010, 0.05 − 0.005) = (0, 0.91, 0.045); depth 0.12·0.5 =
    0.06 → b_pos (0, 0.97, 0.045); r 0.02·1.5 = 0.03; cone 20; applied = the override. The override is in the sig.
[5] Review Focus 2: the base record (ensure_path on base00000001) carries channels [pkgx:chan]. The outfit sidecar
    carries that record (source own, sha = the base's): its capsules are current → relabelled {source base}, NOT
    refitted (fit counter unchanged); its piece item_pants (outfit_piece {}) occupies ``bottom`` = slotx's
    covered_by → channels [], channels_skipped [{pkgx:chan, "Covered by the worn outfit"}], channels_sig = the
    base's. The same outfit with item_pants {exposed_detail: True} keeps channels [pkgx:chan] (equal to the base's).
[6] Review Focus 5 (``demo2``): the base record is current. The route body {channels: {pkgx:chan: <[4]>}} stores the
    override → answer {channels: {pkgx:chan: <[4]>}, due: True}; the profile holds it. The poll
    (``collision.ensure``) returns the record UNCHANGED (the sidecar bytes too, no fit); record_state = {current True,
    channels_current False}; the overview's collision step is status "due" with the detail starting "Channel settings
    changed — recompute to apply"; the Improvements ``collision_capsules`` is_done is False. ``POST …/collision``
    (force + apply_channels) then carries the [4] channel (a_pos (0, 0.91, 0.045)) and the step is "done";
    channels_due False; is_done True; the panel info lists pkgx:chan with placement "declared", reason "".
[7] validate_overrides refuses offset 51 mm, radius_scale 0.4, cone_deg 0, a non-dict override, a non-dict map, a
    missing key; keeps an id no declaration names; None → {}. The route answers 400 for {channels: {pkgx:chan:
    {…cone_deg 0}}}, {} and {channels: {}, x: 1}, and stores nothing; an unknown character → 404.
[8] The payload version is 7 (collision.VERSION = collision.ts COLLISION_VERSION; ≥ 7 so a later bump keeps the
    check). A record of version 6 on the base is refitted on read (system staleness, fit counter +1), channels included.
[9] exposed_only_slots() lists ``bottom``: slotx carries no exposed_only rig (the rig default is False), only its
    exposed_only regions — the item editor offers the exposed_detail switch for the piece that covers a channel.
"""
import json
import math
import os
import re
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok ' if ok else 'FAIL'} {label}" + ("" if ok else f"\n       got:  {got!r}\n       want: {want!r}"))
    if not ok:
        FAILS.append(label)


def near_vec(label, got, want, tol=1e-6):
    ok = got is not None and len(got) == len(want) and all(abs(float(g) - w) <= tol for g, w in zip(got, want))
    print(f"  {'ok ' if ok else 'FAIL'} {label}: {got} ≈ {want}")
    if not ok:
        FAILS.append(label)


CHAN = {"id": "chan", "kind": "channel", "bone": "Hips", "offset": [0, -0.10, 0.05], "axis": [0, 1, 0],
        "depth": 0.12, "radius": 0.02, "cone_deg": 30, "funnel": 0.03, "accepts": {"ops": ["appendage_chain"]}}
RCHAN = {**CHAN, "id": "rchan", "from_rig": "pkgx_chain", "applies_to": {"attributes.kind": ["b"]}}
MANIFEST = {"name": "Pkgx", "apply_to": "*", "body_slots": [{
    "id": "slotx", "covered_by": ["bottom"],
    "attributes": {"kind": {"type": "select", "options": ["a", "b"]}},
    "rigs": [{"id": "pkgx_chain", "op": "appendage_chain", "chains": [[
        {"bone": "mixamorig:PkgxA", "parent": "Hips"}, {"bone": "mixamorig:PkgxB", "parent": "mixamorig:PkgxA"}]]}],
    "regions": [CHAN, RCHAN]}]}
OVERRIDE = {"offset_mm": [0, 10, -5], "radius_scale": 1.5, "depth_scale": 0.5, "cone_deg": 20}
SUPPRESS = ["hips", "outer_hips", "outer_waist"]


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="smoke_collision_channels_"))
    os.environ["STORAGE_DIR"] = str(tmp / "world")
    os.environ["INSTANCE_DIR"] = str(tmp / "instance")
    os.environ["ANIMATION_CLIPS_DIR"] = str(tmp / "clips")
    os.environ["ANIMATION_RIG_FILE"] = str(tmp / "reference.fbx")
    from app.core import paths
    paths.init(str(tmp / "world"))
    paths.init_instance(tmp / "instance")
    import importlib.util

    import yaml
    from fastapi import HTTPException

    from app.core import collision, collision_channels, config, db, model3d, model_overview, motion_item_cache
    from app.core.extension_rig import exposed_only_slots
    from app.core.improvements.base import Candidate
    from app.core.improvements.types.collision_capsules import CollisionCapsules
    from app.core.keyed_lock import keyed_lock
    from app.models.character import get_character_dir, get_character_profile, save_character_profile
    from app.plugins.loader import discover_packages
    from app.plugins import registry
    from app.routes import characters as routes

    db.init_schema()
    paths.get_config_path().write_text(json.dumps({"packages": {"enabled": "pkgx"}}))
    config.load(paths.get_config_path(), instance_path=tmp / "instance/config.json")
    package = tmp / "plugins" / "pkgx"
    package.mkdir(parents=True)
    (package / "plugin.yaml").write_text(yaml.safe_dump(MANIFEST))
    discover_packages(tmp / "plugins", force=True)
    check("pkgx loaded", "pkgx" in {p.id for p in registry.packages()}, True)

    spec = importlib.util.spec_from_file_location("smoke_collision_capsules",
                                                  ROOT / "scripts/smoke_collision_capsules.py")
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    body = fixture.make_body()
    fit = collision.fit_capsules(body)
    exposed_all = lambda entry: True  # noqa: E731

    def profile(kind="a", overrides=None):
        out = {"name": "demo", "template": "human-default", "body_slots": {"slotx": {"kind": kind}}}
        if overrides is not None:
            out["model3d_opts"] = {"collision_channels": overrides}
        return out

    def channel(channels, cid):
        return next((c for c in channels if c["id"] == cid), None)

    print("[1] body_frame")
    frame = collision_channels.body_frame({k: np.array(v, float) for k, v in fixture.JOINTS.items()})
    near_vec("up", frame["up"], [0, 1, 0])
    near_vec("side", frame["side"], [1, 0, 0])
    near_vec("front", frame["front"], [0, 0, 1])
    flipped = {**fixture.JOINTS, "LeftToeBase": (0.1, 0.02, -0.12)}
    near_vec("front follows the feet", collision_channels.body_frame(flipped)["front"], [0, 0, -1])
    try:
        collision_channels.body_frame({k: v for k, v in fixture.JOINTS.items() if k != "LeftArm"})
        check("missing joint → ValueError", "accepted", "ValueError")
    except ValueError as exc:
        check("missing joint → ValueError", "LeftArm" in str(exc), True)
    near_vec("mixamorig: keys match", collision_channels.body_frame(
        {f"mixamorig:{k}": v for k, v in fixture.JOINTS.items()})["front"], [0, 0, 1])

    print("[2] declared placement")
    wanted, sig = collision_channels.wanted_channels("demo", None, {}, profile=profile())
    check("one wanted channel (rchan needs kind b)", [w["id"] for w in wanted], ["pkgx:chan"])
    check("sig = sha256 of the list", bool(re.fullmatch(r"[0-9a-f]{64}", sig)), True)
    channels, skipped = collision_channels.resolve_channels(body, fit["capsules"], wanted, exposed=exposed_all)
    check("nothing skipped", skipped, [])
    rec = channel(channels, "pkgx:chan")
    near_vec("a_pos", rec["a_pos"], [0, 0.90, 0.05])
    near_vec("b_pos", rec["b_pos"], [0, 1.02, 0.05])
    check("record fields", {k: v for k, v in rec.items() if k not in ("a_pos", "b_pos", "frame")},
          {"id": "pkgx:chan", "kind": "channel", "a": "mixamorig:Hips", "b": "mixamorig:Hips", "r": 0.02,
           "cone_deg": 30.0, "funnel": 0.03, "accepts": ["appendage_chain"], "min_length": 1.0, "compress_min": 1.0,
           "suppress": SUPPRESS, "placement": "declared", "applied": None})
    check("frame", rec["frame"], {"side": [1.0, 0.0, 0.0], "up": [0.0, 1.0, 0.0], "front": [0.0, 0.0, 1.0]})

    print("[3] rig placement")
    applied = {"status": "applied", "groups": ["pkgx_chain"], "group_ops": {"pkgx_chain": "appendage_chain"},
               "metrics": {"pkgx_chain": {"opening": {"centre": [0, 0.88, 0.02], "axis": [0, 2, 0]}}}}
    wanted_r, sig_r = collision_channels.wanted_channels("demo", None, {"extension_rig": applied},
                                                         profile=profile("b"))
    check("both wanted with kind b", [w["id"] for w in wanted_r], ["pkgx:chan", "pkgx:rchan"])
    channels, skipped = collision_channels.resolve_channels(body, fit["capsules"], wanted_r, exposed=exposed_all)
    rec = channel(channels, "pkgx:rchan")
    near_vec("rig a_pos", rec["a_pos"] if rec else None, [0, 0.88, 0.02])
    near_vec("rig b_pos", rec["b_pos"] if rec else None, [0, 1.00, 0.02])
    check("rig placement / suppress", (rec or {}).get("placement"), "rig")
    check("rig suppress", (rec or {}).get("suppress"), SUPPRESS)
    moved = {**applied, "metrics": {"pkgx_chain": {"opening": {"centre": [0, 0.87, 0.02], "axis": [0, 1, 0]}}}}
    check("the opening is in the sig", collision_channels.wanted_channels(
        "demo", None, {"extension_rig": moved}, profile=profile("b"))[1] != sig_r, True)
    for label, state, reason in (
            ("no opening metric", {**applied, "metrics": {"pkgx_chain": {}}}, "Rig pkgx_chain reports no opening"),
            ("rig not built", {**applied, "status": "failed"}, "Rig pkgx_chain is not built on this model")):
        wanted_x, _ = collision_channels.wanted_channels("demo", None, {"extension_rig": state}, profile=profile("b"))
        channels, skipped = collision_channels.resolve_channels(body, fit["capsules"], wanted_x, exposed=exposed_all)
        check(f"{label}: no channel", [c["id"] for c in channels], ["pkgx:chan"])
        check(f"{label}: reason", [(s["id"], s["reason"].startswith(reason)) for s in skipped],
              [("pkgx:rchan", True)])

    print("[4] override")
    wanted_o, sig_o = collision_channels.wanted_channels("demo", None, {}, profile=profile(overrides={
        "pkgx:chan": OVERRIDE}))
    check("override in the sig", sig_o != sig, True)
    channels, _ = collision_channels.resolve_channels(body, fit["capsules"], wanted_o, exposed=exposed_all)
    rec = channel(channels, "pkgx:chan")
    near_vec("a_pos", rec["a_pos"], [0, 0.91, 0.045])
    near_vec("b_pos", rec["b_pos"], [0, 0.97, 0.045])
    check("r / cone / applied", (rec["r"], rec["cone_deg"], rec["applied"]),
          (0.03, 20.0, {"offset_mm": [0.0, 10.0, -5.0], "radius_scale": 1.5, "depth_scale": 0.5, "cone_deg": 20.0}))

    # Characters on disk.
    fits = []
    real_fit = collision.fit_capsules

    def counting_fit(data, *, scales=None, extension=None):
        fits.append(1)
        return real_fit(data, scales=scales, extension=extension)

    collision.fit_capsules = counting_fit
    bases = {}
    model3d._current_base = lambda name: bases.get(name)
    items = {"item_pants": {"outfit_piece": {}}}
    motion_item_cache.item_snapshot = lambda **_: items

    def make_character(name):
        get_character_dir(name).mkdir(parents=True, exist_ok=True)
        with keyed_lock("character_profile", name):
            assert save_character_profile(name, {**profile(), "name": name})
        d = model3d.get_model3d_dir(name)
        d.mkdir(parents=True, exist_ok=True)
        base = d / "base00000001.glb"
        base.write_bytes(body)
        base.with_suffix(".json").write_text(json.dumps({"rig": "mixamo", "base": True}))
        bases[name] = ("base00000001", collision._file_sha256(base))
        return d, base

    print("[5] exposure on an inherited record (Review Focus 2)")
    d, base = make_character("demo")
    base_rec = collision.ensure_path("demo", base)
    check("base record: channels", [c["id"] for c in base_rec["channels"]], ["pkgx:chan"])
    check("base record: version, sig", (base_rec["version"], len(base_rec["channels_sig"])), (collision.VERSION, 64))
    outfit = d / "aaaaaaaaaaaa.glb"
    outfit.write_bytes(body)
    outfit_meta = {"rig": "mixamo", "source": "base_body", "base_signature": "base00000001",
                   "base_model_sha256": bases["demo"][1], "pieces": {"bottom": "item_pants"}}
    for label, piece, want in (("covered", {}, []), ("exposed_detail", {"exposed_detail": True}, ["pkgx:chan"])):
        items["item_pants"] = {"outfit_piece": piece}
        outfit.with_suffix(".json").write_text(json.dumps({**outfit_meta, "collision": base_rec}))
        n = len(fits)
        rec = collision.ensure_path("demo", outfit)
        check(f"{label}: relabelled, not refitted", (rec["source"], len(fits) - n), ("base", 0))
        check(f"{label}: channels", [c["id"] for c in rec["channels"]], want)
        check(f"{label}: sig inherited", rec["channels_sig"], base_rec["channels_sig"])
        if not want:
            check("covered: skipped reason", rec["channels_skipped"],
                  [{"id": "pkgx:chan", "reason": collision_channels.COVERED}])
        else:
            check("exposed_detail: the base's channel", rec["channels"], base_rec["channels"])

    print("[6] Save never executes (Review Focus 5)")
    d2, base2 = make_character("demo2")
    collision.ensure_path("demo2", base2)
    sidecar_before = base2.with_suffix(".json").read_bytes()
    record_before = json.loads(sidecar_before)["collision"]
    answer = routes._set_character_collision_channels_sync("demo2", {"channels": {"pkgx:chan": OVERRIDE}})
    stored = {"pkgx:chan": {"offset_mm": [0.0, 10.0, -5.0], "radius_scale": 1.5, "depth_scale": 0.5,
                            "cone_deg": 20.0}}
    check("route answer", answer, {"channels": stored, "due": True})
    check("profile holds the override", get_character_profile("demo2")["model3d_opts"]["collision_channels"], stored)
    n = len(fits)
    polled = collision.ensure("demo2", "base00000001")
    check("poll: record unchanged", polled, record_before)
    check("poll: sidecar unchanged, no fit", (base2.with_suffix(".json").read_bytes() == sidecar_before,
                                              len(fits) - n), (True, 0))
    meta = json.loads(base2.with_suffix(".json").read_text())
    state = collision.record_state("demo2", base2, meta)
    check("record_state", state, {"current": True, "channels_current": False})

    def collision_row(meta, state):
        rows = model_overview.base_model_steps(meta, front_meta=None, collision_current=state["current"],
                                               channels_current=state["channels_current"])
        return next(r for r in rows if r["id"] == "collision")

    row = collision_row(meta, state)
    check("step: due + reason", (row["status"], row["detail"].startswith(
        "Channel settings changed — recompute to apply")), ("due", True))
    improvement, candidate = CollisionCapsules(), Candidate("character:demo2:base00000001", "demo2")
    check("Improvements: not done", improvement.is_done(candidate, {}), False)
    check("panel before applying: placement of the old record", [
        (e["id"], e["placement"]) for e in collision_channels.declarations_info("demo2", base2, meta)],
        [("pkgx:chan", "declared")])
    out = routes.recompute_character_model3d_collision("demo2", signature="base00000001", _={})
    rec = channel(out["collision"]["channels"], "pkgx:chan")
    near_vec("applied: a_pos", rec["a_pos"], [0, 0.91, 0.045])
    meta = json.loads(base2.with_suffix(".json").read_text())
    state = collision.record_state("demo2", base2, meta)
    check("applied: record_state", state, {"current": True, "channels_current": True})
    check("applied: step done", collision_row(meta, state)["status"], "done")
    check("applied: nothing due", collision.channels_due("demo2"), False)
    check("applied: Improvements done", improvement.is_done(candidate, {}), True)
    check("panel info", [(e["id"], e["placement"], e["reason"]) for e in
                         collision_channels.declarations_info("demo2", base2, meta)], [("pkgx:chan", "declared", "")])

    print("[7] validation")
    for label, raw in (("offset 51 mm", {"c": {**OVERRIDE, "offset_mm": [0, 51, 0]}}),
                       ("radius_scale 0.4", {"c": {**OVERRIDE, "radius_scale": 0.4}}),
                       ("cone_deg 0", {"c": {**OVERRIDE, "cone_deg": 0}}),
                       ("a non-dict override", {"c": 1.5}),
                       ("a non-dict map", [OVERRIDE]),
                       ("a missing key", {"c": {k: v for k, v in OVERRIDE.items() if k != "cone_deg"}})):
        try:
            collision_channels.validate_overrides(raw)
            check(f"{label} refused", "accepted", "ValueError")
        except ValueError:
            check(f"{label} refused", True, True)
    check("an unknown id is kept", list(collision_channels.validate_overrides({"gone:x": OVERRIDE})), ["gone:x"])
    check("None → {}", collision_channels.validate_overrides(None), {})
    for bad in ({"channels": {"pkgx:chan": {**OVERRIDE, "cone_deg": 0}}}, {}, {"channels": {}, "x": 1}):
        try:
            routes._set_character_collision_channels_sync("demo2", bad)
            check(f"{bad!r} → 400", "accepted", 400)
        except HTTPException as exc:
            check(f"{bad!r} → 400", exc.status_code, 400)
    check("nothing stored by a refused save",
          get_character_profile("demo2")["model3d_opts"]["collision_channels"], stored)
    try:
        routes._set_character_collision_channels_sync("nobody", {"channels": {}})
        check("unknown character → 404", "accepted", 404)
    except HTTPException as exc:
        check("unknown character → 404", exc.status_code, 404)

    print("[8] version 7")
    ts = (ROOT / "packages/scene-render/src/collision.ts").read_text()
    ts_version = int(re.search(r"export const COLLISION_VERSION = (\d+)", ts).group(1))
    check("collision.VERSION = COLLISION_VERSION, v7 or later (v7 brought the channels)",
          (collision.VERSION == ts_version, collision.VERSION >= 7), (True, True))
    meta = json.loads(base.with_suffix(".json").read_text())
    meta["collision"] = {**meta["collision"], "version": 6}
    meta["collision"].pop("channels", None)
    base.with_suffix(".json").write_text(json.dumps(meta))
    n = len(fits)
    rec = collision.ensure("demo", "base00000001")
    check("a v6 record is refitted on read", (len(fits) - n, rec["version"], [c["id"] for c in rec["channels"]]),
          (1, collision.VERSION, ["pkgx:chan"]))
    collision.fit_capsules = real_fit

    print("[9] the exposed_detail switch counts regions")
    check("exposed_only_slots", exposed_only_slots(), ["bottom"])

    print("FAIL" if FAILS else "OK", f"({len(FAILS)} failures)" if FAILS else "")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
