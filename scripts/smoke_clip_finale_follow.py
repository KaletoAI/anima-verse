#!/usr/bin/env python3
"""A clip's finale clips follow its orientation and surface heights.

Usage: ./.venv/bin/python scripts/smoke_clip_finale_follow.py

On 2026-11-03 three pair poses had been turned (-90°, -90°, 180°, one also
lowered ~20 cm) with the orientation dial while their finale clips kept the
import orientation: the finale started 90° or 180° off and up to 26 cm
away. Since then ``orient_clip`` and ``set_clip_height_offsets`` hand the
same edit to the finales of every pose that plays the clip.

Temporary world and clip libraries. Pose catalog (world layer): "p-base"
plays pair kind "base" with ``finale_animation`` "base-fin"; "p-auto" plays
pair kind "auto" and names no finale — a provider ``pose.finale_animation``
derives "<animation>-end" (like a package does); "p-lone" plays "lone"
without any finale; "p-mixed" plays pair "mixed" whose finale "mixed-fin" is
a SOLO clip. Hand-derived:

  [1] shift_cm [10, -5] on base__b -> the answer lists base__a, base__b,
      base-fin__a, base-fin__b; both sidecars carry shift_cm [10, -5].
  [2] again [10, -5] -> both [20, -10] (cumulative, applied once each).
  [3] with_finales=False [-20, 10] on base -> base back to no shift,
      base-fin still [20, -10].
  [4] height_offsets_cm {seat: 5} on base -> base and base-fin carry
      {seat: 5}; {seat: 0} removes it from both.
  [5] the provider path: shift on auto -> auto-end follows.
  [6] lone (no finale) -> only lone's two files; mixed -> its solo finale
      mixed-fin is not touched (another shape), mixed itself is.
  [7] finale_kinds_of("base") == ["base-fin"], of "base-fin" == [].
  [8] With Blender: real pair FBX copies, yaw 90 on base -> both sidecars
      yaw_deg 90 and the finale's a->b anchor axis equals the base's
      (same clip, so the same numbers to the millimetre). Skipped without
      Blender.
"""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
REPO = Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory(prefix="clip-finale-follow-") as tmp:
        root = Path(tmp)
        for name in ("free", "licensed", "world", "instance"):
            (root / name).mkdir()
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "free")
        os.environ["ANIMATION_CLIPS_LICENSED_DIR"] = str(root / "licensed")
        os.environ["ANIMATION_RIG_FILE"] = str(REPO / "shared/models/rig/reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "instance")
        from app.core import db
        db.init_schema()
        from app.core import animation_clips as ac, hooks, pose_catalog
        from app.blender import runner

        def pair(kind, data=b"never rewrite this FBX"):
            for role in ("a", "b"):
                (root / "free" / f"{kind}__{role}.fbx").write_bytes(data)
            (root / "free" / f"{kind}.json").write_text(json.dumps({"pair": True, "geometry": {}}))

        def geometry(kind):
            return json.loads((root / "free" / f"{kind}.json").read_text()).get("geometry", {})

        def sidecar(kind):
            return json.loads((root / "free" / f"{kind}.json").read_text())

        for kind in ("base", "base-fin", "auto", "auto-end", "lone", "mixed"):
            pair(kind)
        (root / "free" / "mixed-fin.fbx").write_bytes(b"solo")
        (root / "free" / "mixed-fin.json").write_text(json.dumps({"geometry": {}}))
        entries = pose_catalog.world_entries("pose")
        for key, animation, finale in (("p-base", "base", "base-fin"), ("p-auto", "auto", ""),
                                       ("p-lone", "lone", ""), ("p-mixed", "mixed", "mixed-fin")):
            entries[key] = dict(participants=2, animation=animation, group="stand", places=1,
                                prompt="two people", **({"finale_animation": finale} if finale else {}))
        pose_catalog.replace_world_entries("pose", entries)
        pose_catalog.reload_catalogs()
        hooks.register_provider(
            "pose.finale_animation",
            lambda pose_key, animation, participants: f"{animation}-end" if animation == "auto" else "",
            owner="smoke")

        def kinds(rows):
            return sorted({(r["kind"], r.get("role") or "") for r in rows})

        rows = ac.orient_clip("free", "base__b.fbx", shift_cm=[10, -5])
        assert kinds(rows) == [("base", "a"), ("base", "b"), ("base-fin", "a"), ("base-fin", "b")], kinds(rows)
        assert geometry("base")["shift_cm"] == geometry("base-fin")["shift_cm"] == [10, -5]
        print("[1] PASS: the finale takes the same shift")
        ac.orient_clip("free", "base__a.fbx", shift_cm=[10, -5])
        assert geometry("base")["shift_cm"] == geometry("base-fin")["shift_cm"] == [20, -10]
        print("[2] PASS: cumulative, once per clip")
        ac.orient_clip("free", "base__a.fbx", shift_cm=[-20, 10], with_finales=False)
        assert "shift_cm" not in geometry("base") and geometry("base-fin")["shift_cm"] == [20, -10]
        print("[3] PASS: with_finales=False edits the clip alone")

        rows = ac.set_clip_height_offsets("free", "base__a.fbx", {"seat": 5})
        assert {r["kind"] for r in rows} == {"base", "base-fin"}
        assert sidecar("base")["height_offsets_cm"] == sidecar("base-fin")["height_offsets_cm"] == {"seat": 5}
        ac.set_clip_height_offsets("free", "base__a.fbx", {"seat": 0})
        assert "height_offsets_cm" not in sidecar("base") and "height_offsets_cm" not in sidecar("base-fin")
        print("[4] PASS: surface heights follow, and their removal too")

        ac.orient_clip("free", "auto__a.fbx", shift_cm=[3, 4])
        assert geometry("auto-end")["shift_cm"] == [3, 4]
        print("[5] PASS: a package-derived finale follows")

        rows = ac.orient_clip("free", "lone__a.fbx", shift_cm=[1, 1])
        assert kinds(rows) == [("lone", "a"), ("lone", "b")], kinds(rows)
        rows = ac.orient_clip("free", "mixed__a.fbx", shift_cm=[2, 2])
        assert kinds(rows) == [("mixed", "a"), ("mixed", "b")], kinds(rows)
        assert "shift_cm" not in geometry("mixed-fin") and geometry("mixed")["shift_cm"] == [2, 2]
        print("[6] PASS: no finale, or one of another shape, is left alone")

        assert ac.finale_kinds_of("base") == ["base-fin"] and ac.finale_kinds_of("base-fin") == []
        print("[7] PASS: finale lookup from the pose catalog")

        if not runner.is_available():
            print("[8] SKIP: Blender not available")
            return
        source = REPO / "shared/models/clips"
        for kind in ("turn", "turn-fin"):
            for role in ("a", "b"):
                shutil.copy(source / f"kissing__{role}.fbx", root / "free" / f"{kind}__{role}.fbx")
            shutil.copy(source / "kissing.json", root / "free" / f"{kind}.json")
        entries = pose_catalog.world_entries("pose")
        entries["p-turn"] = dict(participants=2, animation="turn", group="stand", places=1,
                                 prompt="two people", finale_animation="turn-fin")
        pose_catalog.replace_world_entries("pose", entries)
        pose_catalog.reload_catalogs()
        ac.orient_clip("free", "turn__a.fbx", yaw_deg=90)
        base, fin = geometry("turn"), geometry("turn-fin")
        assert base["yaw_deg"] == fin["yaw_deg"] == 90, (base.get("yaw_deg"), fin.get("yaw_deg"))
        assert all(base["roles"][r]["anchor_xz_m"] == fin["roles"][r]["anchor_xz_m"] for r in ("a", "b")), \
            (base["roles"], fin["roles"])
        print("[8] PASS: a real turn reaches the finale file, same anchors")


if __name__ == "__main__":
    main()
