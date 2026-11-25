"""A stored channel record follows a changed exposure without a refit (plan anatomy, task 3).

Usage: ./.venv/bin/python scripts/smoke_channel_exposure_refresh.py

Exposure is identity and not part of ``channels_sig`` (``collision_channels`` module docstring). A record whose
covered set (``channels_skipped`` with reason ``COVERED``) differs from the exposure now — after a pack declares
``hide_under``, or a partial cover now counts as covered — is brought in line on its next ``collision.refresh``,
WITHOUT ``apply_channels``:

  E1 record carries channel X in ``channels``, X exposed now   -> exposure_current True, refresh False,
     ``_with_channels`` 0 calls (nothing to do).
  E2 the same record, X covered (hidden) now                   -> refresh True, X in ``channels_skipped`` with
     COVERED, ``_with_channels`` 0 calls (re-filtering needs no file).
  E3 record with X in ``channels_skipped``/COVERED, X exposed now -> refresh True, ``_with_channels`` exactly 1 call
     (a newly exposed channel is resolved on the GLB), ``apply_channels`` was False.
  E4 ``channels_sig`` of the record unchanged in E1-E3 (the sig ignores exposure and ``hide_under``).
  E5 ``record_state`` of the E3 record before the refresh: ``exposure_current`` False; ``model_overview.
     _collision_step`` with that state is ``due`` with ``EXPOSURE_CHANGED``.
  E6 a channel skipped for ANOTHER reason (no capsule set) and covered now: exposure_current True — an id that has
     no channel either way never keeps a record due (no refresh loop).
Everything is synthetic: fake record, fake ``wanted``, a patched ``exposed``; no Blender, no world data.
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FAILS = []


def check(ok, label):
    print(("PASS " if ok else "FAIL ") + label)
    if not ok:
        FAILS.append(label)


def main():
    with tempfile.TemporaryDirectory(prefix="channel-exposure-") as tmp:
        root = Path(tmp)
        from app.core import paths
        paths.init(root / "w")
        paths.init_instance(root / "instance")
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "rig.fbx")
        from app.core import collision, collision_channels, model_overview
        glb = root / "m.glb"
        glb.write_bytes(b"glTF-fake")
        SIG = "sig-1"
        wanted = [{"id": "pkg:x", "exposed_only": True, "covered_by": ["bottom"], "hide_under": ["bottom"]}]
        state = {"exposed": True}
        calls = []
        collision_channels.wanted_channels = lambda c, p, m, profile=None: (wanted, SIG)
        collision_channels.exposure = lambda meta, items=None: (lambda entry: state["exposed"])
        collision.identity = lambda path, meta: ("own", "sha-1")
        collision.character_scales = lambda c, profile=None: {"s": 1.0}
        collision.extension_chains = lambda meta: []

        def fake_with_channels(record, data, w, sig, exposed):
            calls.append(data)
            return {**record, "channels": [{"id": "pkg:x", "suppress": []}] if exposed(w[0]) else [],
                    "channels_skipped": [] if exposed(w[0]) else [{"id": "pkg:x", "reason": collision_channels.COVERED}],
                    "channels_sig": sig}
        collision._with_channels = fake_with_channels

        def record(channels, skipped):
            return {"version": collision.VERSION, "sha256": "sha-1", "scales": {"s": 1.0}, "source": "own",
                    "extension_groups": [], "capsules": [{"id": "Hips"}], "channels": channels,
                    "channels_skipped": skipped, "channels_sig": SIG}
        open_rec = record([{"id": "pkg:x", "suppress": ["Hips"]}], [])
        covered_rec = record([], [{"id": "pkg:x", "reason": collision_channels.COVERED}])
        exposed = lambda entry: state["exposed"]  # noqa: E731
        profile = {"template": ""}

        # E1
        state["exposed"] = True
        meta = {"rig": "mixamo", "collision": dict(open_rec)}
        check(collision.exposure_current(open_rec, wanted, exposed) is True, "E1 exposure_current True")
        check(collision.refresh("C", glb, meta, profile=profile) is False and not calls, "E1 refresh False, 0 resolves")
        check(meta["collision"]["channels_sig"] == SIG, "E4 sig unchanged (E1)")
        # E2
        state["exposed"] = False
        meta = {"rig": "mixamo", "collision": dict(open_rec)}
        changed = collision.refresh("C", glb, meta, profile=profile)
        rec = meta["collision"]
        check(changed is True and not calls, "E2 refresh True without a resolve")
        check(rec["channels"] == [] and {"id": "pkg:x", "reason": collision_channels.COVERED} in rec["channels_skipped"],
              "E2 X moved to channels_skipped / COVERED")
        check(rec["channels_sig"] == SIG, "E4 sig unchanged (E2)")
        # E5 (before E3's refresh)
        state["exposed"] = True
        meta = {"rig": "mixamo", "collision": dict(covered_rec)}
        st = collision.record_state("C", glb, meta, profile=profile)
        check(st.get("exposure_current") is False and st.get("current") is True and st.get("channels_current") is True,
              "E5 record_state: exposure_current False, capsules and channels_sig current")
        row = model_overview._collision_step(meta, current=st["current"], channels_current=st["channels_current"],
                                             exposure_current=st["exposure_current"])
        check(row.get("status") == model_overview.DUE and model_overview.EXPOSURE_CHANGED in row.get("detail", ""),
              f"E5 collision step due with EXPOSURE_CHANGED ({row.get("status")}: {row.get("detail")})")
        # E3
        changed = collision.refresh("C", glb, meta, profile=profile)
        rec = meta["collision"]
        check(changed is True and len(calls) == 1, f"E3 refresh True with exactly one resolve ({len(calls)})")
        check([c["id"] for c in rec["channels"]] == ["pkg:x"] and rec["channels_sig"] == SIG,
              "E3 X back in channels; E4 sig unchanged")
        check(collision.record_state("C", glb, meta, profile=profile)["exposure_current"] is True,
              "E3 record now exposure_current")
        # E6
        state["exposed"] = False
        broken = record([], [{"id": "pkg:x", "reason": "No capsule set"}])
        check(collision.exposure_current(broken, wanted, exposed) is True,
              "E6 a channel skipped for another reason keeps the record current")
    if FAILS:
        print(f"FAILED: {len(FAILS)}")
        sys.exit(1)
    print("ALL OK")


if __name__ == "__main__":
    main()
