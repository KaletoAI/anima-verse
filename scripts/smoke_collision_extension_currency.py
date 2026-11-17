#!/usr/bin/env python3
"""Smoke: a collision record is current only for the extension groups it was built for (app/core/collision.py
``is_current`` / ``refresh`` / ``record_state``, review 06 part C #1).

Usage:  ./.venv/bin/python scripts/smoke_collision_extension_currency.py

No world DB, no server: ``paths.init`` on a temp dir, an 8-byte dummy model file there, and three stubs — the
capsule fit (``fit_capsules``: the table capsule ``hips`` plus one capsule ``<group>:bone1`` per extension group it
is handed, and a counter), the extension groups (``extension_chains``: op ``attached_part`` for every group in
``CARRIED``) and the wanted channels (none, signature ``sig0``). ``profile={}`` everywhere, so the scales are
``default_scales()``.

The model is an OUTFIT on the base-body pipeline (sidecar ``source "base_body"``, ``base_model_sha256`` "BASESHA",
``base_signature`` "bsig") -> identity ``("base", "BASESHA")``. Its sidecar starts with the BASE's record copied with
the base meta: ``source "own"``, sha BASESHA, capsules [hips, part:bone1], ``extension_groups`` ["part"].

Expected, by hand:
[1] first post-rig pass, the outfit's extension rig FAILED (CARRIED = []): the copied set is relabelled, not refitted
    (base groups ["part"] ∩ carried [] = [] = the model's groups): changed True, 0 fits, source "base", capsules
    [hips] (the part's capsule filtered out — Ruling A49), extension_groups [].
[2] ``record_state`` right after the outfit's extension rig was rebuilt and APPLIED (CARRIED = ["part"]), before any
    refresh: current False (the record was built for [], the model carries ["part"]). The old currency (version, sha,
    scales) said True, so neither the overview nor the Improvements queue ever repaired it.
[3] the post-rig pass after that rebuild: the set is refitted on THIS file under the same identity: changed True,
    1 fit, handed the groups ["part"]; capsules [hips, part:bone1], extension_groups ["part"], source "base", sha
    BASESHA. The old code returned changed False and kept [hips] — the bug: an extension part with no capsule.
[4] the next pass: changed False, still 1 fit (current); ``record_state`` current True.
[5] the same with ``apply_channels=True`` (the Improvements queue / recompute path): changed False, 1 fit.
[6] a copied base record that LACKS a group the outfit carries (base groups [], outfit ["part"]): no relabel (the
    inherited set has no capsule for it) -> refitted: changed True, 1 fit, capsules [hips, part:bone1].
[7] a failed fit is stored with the groups it was asked for: fit raises -> error record, extension_groups ["part"];
    the next pass changes nothing and does not fit again (no poll loop).
[8] ``is_current`` without ``extension_groups`` is the old three-key check (True for the [3] record); with ["part"]
    True, with [] False; a record without the key (written before this check) is not current for any groups list.
"""
from __future__ import annotations

import copy
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS: list = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok ' if ok else 'FAIL'} {label}" + ("" if ok else f"\n       got:  {got!r}\n       want: {want!r}"))
    if not ok:
        FAILS.append(label)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="smoke_collision_currency_"))
    from app.core import paths
    paths.init(str(tmp))
    from app.core import collision, collision_channels

    state = {"carried": [], "fits": 0, "handed": None, "raise": False}

    def fake_fit(data, *, scales=None, extension=None):
        state["fits"] += 1
        state["handed"] = [g["group"] for g in extension or []]
        if state["raise"]:
            raise ValueError("no skin")
        capsules = [{"id": "hips", "a": "Hips", "b": "Spine1", "r": 0.05, "region": "torso"}]
        capsules += [{"id": f"{g['group']}:bone1", "a": "bone1", "b": "bone1", "r": 0.02, "region": "attached_part"}
                     for g in extension or []]
        return {"version": collision.VERSION, "capsules": capsules, "skipped": [], "scales": scales}

    collision.fit_capsules = fake_fit
    collision.extension_chains = lambda meta: [{"group": g, "op": "attached_part", "chains": [["bone1"]]}
                                               for g in sorted(state["carried"])]
    collision_channels.wanted_channels = lambda *a, **k: ([], "sig0")

    path = tmp / "outfit.glb"
    path.write_bytes(b"glTFfake")
    scales = collision.default_scales()

    def base_record(groups):
        caps = [{"id": "hips", "a": "Hips", "b": "Spine1", "r": 0.05, "region": "torso"}]
        caps += [{"id": f"{g}:bone1", "a": "bone1", "b": "bone1", "r": 0.02, "region": "attached_part"} for g in groups]
        return {"version": collision.VERSION, "sha256": "BASESHA", "scales": scales, "source": "own",
                "capsules": caps, "skipped": [], "channels": [], "channels_skipped": [], "channels_sig": "sig0",
                "extension_groups": list(groups)}

    def outfit_meta(record):
        return {"source": "base_body", "base_model_sha256": "BASESHA", "base_signature": "bsig", "rig": "mixamo",
                "collision": copy.deepcopy(record), "extension_rig": {"status": "failed"}}

    ids = lambda meta: [c["id"] for c in meta["collision"]["capsules"]]  # noqa: E731
    refresh = lambda meta, **kw: collision.refresh("demo", path, meta, profile={}, **kw)  # noqa: E731

    print("[1] first pass, extension rig failed: relabel")
    meta = outfit_meta(base_record(["part"]))
    check("changed", refresh(meta), True)
    check("fits", state["fits"], 0)
    check("source / capsules / groups", (meta["collision"]["source"], ids(meta), meta["collision"]["extension_groups"]),
          ("base", ["hips"], []))

    print("[2] record_state after the extension rig applied")
    state["carried"] = ["part"]
    meta["extension_rig"] = {"status": "applied"}
    check("current", collision.record_state("demo", path, meta, profile={})["current"], False)

    print("[3] the post-rig pass after the rebuild: refit under the base identity")
    check("changed", refresh(meta), True)
    check("fits / handed", (state["fits"], state["handed"]), (1, ["part"]))
    rec = meta["collision"]
    check("capsules / groups / source / sha", (ids(meta), rec["extension_groups"], rec["source"], rec["sha256"]),
          (["hips", "part:bone1"], ["part"], "base", "BASESHA"))

    print("[4] the next pass")
    check("changed", refresh(meta), False)
    check("fits", state["fits"], 1)
    check("record_state current", collision.record_state("demo", path, meta, profile={})["current"], True)

    print("[5] apply_channels")
    check("changed", refresh(meta, apply_channels=True), False)
    check("fits", state["fits"], 1)

    print("[6] the copied base record lacks a group the outfit carries")
    state["fits"] = 0
    meta6 = outfit_meta(base_record([]))
    meta6["extension_rig"] = {"status": "applied"}
    check("changed", refresh(meta6), True)
    check("fits / capsules", (state["fits"], ids(meta6)), (1, ["hips", "part:bone1"]))

    print("[7] a failed fit keeps its groups")
    state["fits"], state["raise"] = 0, True
    meta7 = outfit_meta(base_record([]))
    meta7["extension_rig"] = {"status": "applied"}
    check("changed", refresh(meta7), True)
    check("error / groups", (bool(meta7["collision"].get("error")), meta7["collision"]["extension_groups"]),
          (True, ["part"]))
    check("next pass changed", refresh(meta7), False)
    check("fits", state["fits"], 1)

    print("[8] is_current")
    check("three keys", collision.is_current(rec, "BASESHA", scales), True)
    check("groups ['part']", collision.is_current(rec, "BASESHA", scales, ["part"]), True)
    check("groups []", collision.is_current(rec, "BASESHA", scales, []), False)
    legacy = {k: v for k, v in rec.items() if k != "extension_groups"}
    check("record without the key, groups []", collision.is_current(legacy, "BASESHA", scales, []), False)

    print("ALL OK" if not FAILS else f"FAILED ({len(FAILS)}): {', '.join(FAILS)}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
