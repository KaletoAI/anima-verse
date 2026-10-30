#!/usr/bin/env python3
"""Usage: ./.venv/bin/python scripts/smoke_prop_action_figure_filter.py

A prop action whose pose the actor's figure cannot play is not meant for it:
not offered, and refused (``pose_not_for_actor``) instead of playing as the
group's fallback clip (``prop_action_engine.animated_for``).

Hand-derived expectations, private clip directory and catalog:
clips ``female/kneel-a`` (female set only), ``sit`` (neutral), no ``rest-b``
anywhere; poses kneeling -> kneel-a, sitting -> sit, resting -> rest-b,
blank -> "" (no clip kind configured). Sets follow gender (both humanoid):
Mia female -> chain [female], Ben male -> chain [male].

a. sitting: neutral clip, playable by both -> True / True.
b. kneeling: female/kneel-a — Mia True; Ben's chain [male] + neutral holds no
   kneel-a -> False.
c. resting: rest-b exists nowhere -> False for both (the group fallback is
   no clip of this pose either).
d. blank: no kind claims nothing -> True.
e. combined phases [sitting, kneeling]: every phase must play -> Mia True,
   Ben False.
f. Wiring on the run fixture (smoke_prop_action_runs): with animated_for
   answering False, the offer list drops the action entirely and check()
   answers pose_not_for_actor; with True the action is offered again.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

CATALOG = {"kneeling": {"animation": "kneel-a", "solo": True}, "sitting": {"animation": "sit", "solo": True},
           "resting": {"animation": "rest-b", "solo": True}, "blank": {"animation": "", "solo": True}}


def pure():
    with tempfile.TemporaryDirectory(prefix="figure-filter-") as tmp:
        root = Path(tmp)
        free, licensed = root / "free", root / "licensed"
        (free / "female").mkdir(parents=True)
        licensed.mkdir()
        old = {k: os.environ.get(k) for k in ("ANIMATION_CLIPS_DIR", "ANIMATION_CLIPS_LICENSED_DIR")}
        os.environ.update(ANIMATION_CLIPS_DIR=str(free), ANIMATION_CLIPS_LICENSED_DIR=str(licensed))
        try:
            for path, kind in ((free / "female", "kneel-a"), (free, "sit")):
                (path / f"{kind}.fbx").write_bytes(b"isolated pose fixture")
                (path / f"{kind}.json").write_text(json.dumps({"kind": kind, "duration_s": 2, "loop": True}))
            from app.core import paths
            paths.init(root / "world")
            from app.core import animation_clips, pose_catalog
            from app.core import prop_action_engine as E
            animation_clips._clear_entries_cache()
            mia, ben = {"gender": "female"}, {"gender": "male"}

            def solo(pose):
                return {"ability": "pose", "pose_key": pose}

            with patch.object(pose_catalog, "get_catalog", return_value=CATALOG), \
                    patch("app.core.model_refs.is_humanoid", return_value=True):
                ok = lambda who, profile, definition: E.animated_for(who, definition, profile=profile)
                assert ok("Mia", mia, solo("sitting")) and ok("Ben", ben, solo("sitting"))
                print("PASS a: a neutral clip plays for everyone")
                assert ok("Mia", mia, solo("kneeling")) and not ok("Ben", ben, solo("kneeling"))
                print("PASS b: a female-only clip is not for a male figure")
                assert not ok("Mia", mia, solo("resting")) and not ok("Ben", ben, solo("resting"))
                print("PASS c: a pose whose clip exists nowhere is for nobody")
                assert ok("Ben", ben, solo("blank"))
                print("PASS d: a pose without a clip kind passes")
                combined = {"ability": "combined", "phases": [{"pose_key": "sitting"}, {"pose_key": "kneeling"}]}
                assert ok("Mia", mia, combined) and not ok("Ben", ben, combined)
                print("PASS e: every phase of a combined action must play")
            animation_clips._clear_entries_cache()
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


def wiring():
    import smoke_prop_action_runs as S
    F, A = S.F, S.A
    F.paths.init(F.ROOT / "world")
    from app.core import prop_actions as P
    name, target, _ = S.setup_run()
    identity = {k: target[k] for k in ("location_id", "room_id", "placement_id", "variant_uid")}
    with patch.object(A, "animated_for", return_value=False):
        P._offers_cache.clear()
        assert [o for o in P.offers(name) if o["action_id"] == target["action_id"]] == []
        assert A.check(name, identity, target["action_id"], target["definition_revision"]) == dict(
            enabled=False, reason="pose_not_for_actor")
    P._offers_cache.clear()
    assert [o["action_id"] for o in P.offers(name)] == [target["action_id"]]
    print("PASS f: not offered and refused when the figure cannot play it")


if __name__ == "__main__":
    pure()
    wiring()
