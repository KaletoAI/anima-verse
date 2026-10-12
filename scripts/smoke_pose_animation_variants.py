#!/usr/bin/env python3
"""Smoke the variant flow of a pose animation job (plan v3 Task 5), with
disposable storage and stubbed generation, conversion and measurement.

Usage: ./.venv/bin/python scripts/smoke_pose_animation_variants.py

Fixture: catalog entry "waving" (stand), backend "kimodo" with
motion_source reference_rig, caption_style person, segment 4 s, generator
kimodo, license NVIDIA-Open-Model-License. The hub returns 3 verdicts for 3
requested variants: n0 ok (FBX bytes "v0"), n1 failed "missing sha256",
n2 ok (FBX bytes "v2"). Measurement of the clip made from "v2" reports hips
1.25 m — outside the stand window 0.95–1.20 — so it fails the check.
Expected by hand:
 1. The captions are prepared with caption_style "person", segment 4.0, and the
    hub is asked for variants=3 with the REFERENCE RIG as source (FBX path).
 2. The job ends completed with state awaiting_choice and three candidates:
    index 0 ok; index 1 not ok, reasons ["missing sha256"], no preview;
    index 2 not ok with the hip-height reason. Progress phase "choose".
    Both converted variants went through format "fbx" with the ref input.
 3. recent_jobs shows state, backend "kimodo", generator "kimodo" and the
    candidates without any filesystem path.
 4. choose(tid, 2) -> ChoiceError 422; choose(tid, 7) -> 404;
    choose("task_unknown", 0) -> 404.
 5. choose(tid, 0) publishes: free/waving.fbx holds the bytes of candidate 0,
    the sidecar has source.generator "kimodo", generated_for_pose "waving",
    variant_index 0, no puppet_sha256, license/credit from the backend; the
    catalog entry points at "waving"; the task staging is gone; state
    "published", chosen 0.
 6. A second choose(tid, 0) -> 409; discard(tid) -> 409.
 7. A second job, discard(tid) -> staging removed, state "discarded";
    choose afterwards -> 409.
 8. Restart in awaiting_choice: a third job; a NEW TaskQueue instance on the
    same database; choose(tid, 0) still publishes.
 9. sweep_candidates: a fourth job left waiting with candidates.json stamped
    8 days ago and a fifth stamped 6 days ago -> the 8-day staging is removed
    and its state becomes "expired" (choose -> 410); the 6-day one stays.
10. No candidate passes (every hub verdict fails) -> the job fails with
    "no variant passed the check".
11. An explicit backend that the service refuses -> submit raises ValueError
    and nothing is queued; variants 5 -> ValueError.
12. periodic_jobs runs the sweep daily (86400 s) under "pose_animation_candidates".
Review fixes:
 2b. A restart that re-enters a job whose progress already says awaiting_choice
     returns that finished result instead of failing it; no hub cancel.
 4b. candidates.json present but the chosen FBX gone -> 410.
 8b. All three hub verdicts ok, only "v2" fails its check: choose(1) publishes
     the bytes of variant 1, not of the first one.
 9b. A candidate stamped 8 days ago is refused (410) by choose itself even
     before any sweep ran, and its job becomes "expired".
 13. submit without a variant count queues 3 variants.
"""
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from smoke_pose_animation_queue import structure

FBX = b"Kaydara FBX Binary  \x00"
META = {"motion_source": "reference_rig", "source_slot": "input_rig_path",
        "caption_style": "person", "variant_param": "input_num_samples",
        "duration_param": "input_duration", "segment_seconds": 4.0, "max_variants": 4,
        "generator": "kimodo", "license": "NVIDIA-Open-Model-License",
        "credit": "Kimodo, NVIDIA", "model_revision": "kimodo-soma-rp-v1"}


def main():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        from app.core import paths
        paths.init(tmp)
        os.environ.update({name: str(root / suffix) for name, suffix in {
            "ANIMATION_CLIPS_DIR": "free", "ANIMATION_CLIPS_INBOX_DIR": "inbox",
            "ANIMATION_RIG_FILE": "rig.fbx", "ANIMATION_PUPPET_FILE": "puppet.glb",
            "ANIMATION_CLIPS_LICENSED_DIR": "licensed"}.items()})
        from app.core import pose_animation as pa, pose_catalog as pc
        from app.core import task_queue as tq_mod
        from app.core.db import init_schema
        init_schema()
        catalog = root / "catalog.json"
        catalog.write_text(json.dumps({"groups": {"stand": {"default": "waving", "needs_place": False}},
            "entries": {"waving": {"prompt": "waving", "solo": True, "group": "stand", "animation": "old"}}}))
        original_path = pc.catalog_path
        pc.catalog_path = lambda axis: catalog if axis == "pose" else original_path(axis)
        pc.reload_catalogs()
        paths.get_animation_clips_dir().mkdir()
        paths.get_rig_file().write_bytes(FBX + b"rig")
        paths.get_puppet_file().write_bytes(b"glTFpuppet")
        tq = pa.get_task_queue()
        pa.register()
        backend = SimpleNamespace(name="kimodo", motion_meta=dict(META), max_variants=4)
        route = SimpleNamespace(backend=backend)
        calls = {"prepare": [], "generate": [], "convert": []}
        state = {"verdicts": None, "refuse": False}

        def resolve(name=""):
            if state["refuse"] or name not in ("", "kimodo"):
                raise ValueError(f"'{name}' is not an animation backend of the pose_animation chain")
            return route

        def prepare(mode, **kwargs):
            calls["prepare"].append(kwargs)
            return pa.PreparedMotion(["A person waves."], False, None)

        def generate(source, captions, seed, **kwargs):
            calls["generate"].append((source, kwargs["variants"], kwargs["route"]))
            kwargs["on_job_id"]("j1", "kimodo")
            verdicts = state["verdicts"] or [
                {"n": 0, "ok": True, "reason": ""}, {"n": 1, "ok": False, "reason": "missing sha256"},
                {"n": 2, "ok": True, "reason": ""}]
            blobs = [FBX + f"v{v['n']}".encode() for v in verdicts if v["ok"]]
            if not blobs:
                return {"ok": False, "error": "animation backend returned no usable variant",
                        "results": verdicts}
            return {"ok": True, "blobs": blobs, "results": verdicts, "backend": "kimodo", "job_id": "j1"}

        def run(script, *, inputs, out_dir, **kwargs):
            if script == "clip_measure":
                bad = Path(inputs["clip"]).read_bytes().endswith(b"v2")
                return {"ok": True, "data": {**structure(), "frames": 120,
                        "hips_y": [1.25 if bad else 1.05], "min_foot_y": 0.0}}
            assert script == "glb_to_ref_fbx"
            calls["convert"].append((kwargs["params"], sorted(inputs)))
            out_dir.mkdir(parents=True, exist_ok=True)
            for name in ("motion", "rest"):
                (out_dir / (name + ".fbx")).write_bytes(Path(inputs["src"]).read_bytes())
            return {"ok": True, "outputs": {name: out_dir / (name + ".fbx") for name in ("motion", "rest")}}

        def importing(kind, src, rest, *, out_dir, source_extra, **kwargs):
            out_dir.mkdir(parents=True)
            fbx, sidecar = out_dir / (kind + ".fbx"), out_dir / (kind + ".json")
            fbx.write_bytes(Path(src).read_bytes())
            meta = {"source": source_extra, "frames": 120, "duration_s": 4.0}
            sidecar.write_text(json.dumps(meta))
            return {"fbx": fbx, "sidecar": sidecar, "meta": meta}

        def job(**submit_kwargs):
            tid = pa.submit("entry", key="waving", seed=0, **submit_kwargs)
            try:
                result = pa._handle({"mode": "entry", "key": "waving", "seed": 0, "_task_id": tid,
                                     "backend": submit_kwargs.get("backend", ""),
                                     "variants": submit_kwargs.get("variants", 1)})
                tq._finish_task(tid, "completed", result=result)
                return tid, None
            except RuntimeError as exc:
                tq._finish_task(tid, "failed", error=str(exc))
                return tid, str(exc)

        def expect(status, fn, *args):
            try:
                fn(*args)
            except pa.ChoiceError as exc:
                assert exc.status == status, (exc.status, str(exc))
                return str(exc)
            raise AssertionError(f"expected ChoiceError {status}")

        staging = lambda tid: paths.get_clips_inbox_dir() / ".pose_animation" / tid
        service = SimpleNamespace(resolve_animation_backend=resolve, generate_mesh_animation=generate)
        try:
            with patch.object(tq, "start"), patch.object(pa, "prepare_motion", side_effect=prepare), \
                 patch.object(pa, "get_image_service", return_value=service), \
                 patch.object(pa.runner, "run", side_effect=run), \
                 patch.object(pa, "import_source", side_effect=importing):
                tid, error = job(backend="kimodo", variants=3)
                assert error is None, error
                assert calls["prepare"][0]["caption_style"] == "person"
                assert calls["prepare"][0]["segment_seconds"] == 4.0
                assert calls["generate"][0] == (str(paths.get_rig_file()), 3, route)
                print("PASS 1: captions in the backend style, rig source, 3 variants requested")
                progress = tq.get_task_progress(tid)
                assert progress["phase"] == "choose" and progress["state"] == "awaiting_choice"
                cands = progress["candidates"]
                assert [c["index"] for c in cands] == [0, 1, 2]
                assert [c["ok"] for c in cands] == [True, False, False], cands
                assert cands[1]["reasons"] == ["missing sha256"] and cands[1]["preview"] is False
                assert "hip height" in cands[2]["reasons"][0] and cands[0]["preview"] is True
                assert all(p == {"format": "fbx"} and i == ["ref", "src"] for p, i in calls["convert"])
                assert len(calls["convert"]) == 2
                print("PASS 2: awaiting_choice with one usable, one hub-failed, one check-failed variant")
                with patch.object(pa, "_cancel_lost_job") as lost:
                    again = pa._handle({"mode": "entry", "key": "waving", "_task_id": tid})
                assert again["state"] == "awaiting_choice" and again["candidates"] == cands
                lost.assert_not_called()
                print("PASS 2b: a restart after the variants were ready keeps the finished result")
                listed = {j["task_id"]: j for j in pa.recent_jobs()}[tid]
                assert (listed["state"], listed["backend"], listed["generator"]) == \
                    ("awaiting_choice", "kimodo", "kimodo"), listed
                assert str(root) not in json.dumps(listed), listed
                print("PASS 3: recent_jobs carries state and candidates without paths")
                assert "did not pass" in expect(422, pa.choose, tid, 2)
                expect(404, pa.choose, tid, 7)
                expect(404, pa.choose, "task_unknown", 0)
                print("PASS 4: failed, out-of-range and unknown choices refused")
                cand_fbx = Path(json.loads((staging(tid) / "candidates.json").read_text())["candidates"][0]["fbx"])
                kept = cand_fbx.read_bytes()
                cand_fbx.unlink()
                expect(410, pa.choose, tid, 0)
                cand_fbx.write_bytes(kept)
                print("PASS 4b: a vanished candidate file is 410, not a crash")
                out = pa.choose(tid, 0)
                free = paths.get_animation_clips_dir()
                assert (free / "waving.fbx").read_bytes() == FBX + b"v0"
                side = json.loads((free / "waving.json").read_text())
                src = side["source"]
                assert (src["generator"], src["generated_for_pose"], src["variant_index"]) == \
                    ("kimodo", "waving", 0), src
                assert "puppet_sha256" not in src and src["model_revision"] == "kimodo-soma-rp-v1"
                assert (side["license"], side["credit"]) == ("NVIDIA-Open-Model-License", "Kimodo, NVIDIA")
                assert json.loads(catalog.read_text())["entries"]["waving"]["animation"] == "waving"
                assert not staging(tid).exists()
                progress = tq.get_task_progress(tid)
                assert (progress["state"], progress["chosen"]) == ("published", 0) and out["kind"] == "waving"
                print("PASS 5: choice publishes exactly the chosen variant with generic provenance")
                expect(409, pa.choose, tid, 0)
                expect(409, pa.discard, tid)
                print("PASS 6: a decided job refuses a second choice and a discard")
                tid2, _ = job(backend="kimodo", variants=3)
                assert staging(tid2).exists()
                pa.discard(tid2)
                assert not staging(tid2).exists() and tq.get_task_progress(tid2)["state"] == "discarded"
                expect(409, pa.choose, tid2, 0)
                print("PASS 7: discard removes the candidates; a later choice is refused")
                state["verdicts"] = [{"n": i, "ok": True, "reason": ""} for i in range(3)]
                tid3, _ = job(variants=3)
                state["verdicts"] = None
                assert [c["ok"] for c in tq.get_task_progress(tid3)["candidates"]] == [True, True, False]
                fresh = tq_mod.TaskQueue()
                with patch.object(pa, "get_task_queue", return_value=fresh):
                    pa.choose(tid3, 1)
                assert tq.get_task_progress(tid3)["state"] == "published"
                assert (free / "waving.fbx").read_bytes() == FBX + b"v1"
                print("PASS 8: a choice survives a restart and publishes exactly the chosen variant")
                old, young, stale = (job(variants=2)[0] for _ in range(3))
                from app.core.timeutils import utc_now
                from datetime import timedelta
                for t, days in ((old, 8), (young, 6), (stale, 8)):
                    f = staging(t) / "candidates.json"
                    data = json.loads(f.read_text())
                    data["created_at"] = (utc_now() - timedelta(days=days)).isoformat()
                    f.write_text(json.dumps(data))
                expect(410, pa.choose, stale, 0)
                assert tq.get_task_progress(stale)["state"] == "expired" and not staging(stale).exists()
                print("PASS 9b: choose itself refuses a candidate older than 7 days")
                assert pa.sweep_candidates() == 1
                assert not staging(old).exists() and staging(young).exists()
                assert tq.get_task_progress(old)["state"] == "expired"
                expect(410, pa.choose, old, 0)
                print("PASS 9: the 7-day sweep removes only expired candidates")
                state["verdicts"] = [{"n": 0, "ok": False, "reason": "missing sha256"}]
                _tid, error = job(variants=1)
                assert error and "no variant passed the check" in error, error
                state["verdicts"] = None
                print("PASS 10: no usable variant fails the job")
                before = len(tq.list_recent_tasks(pa.TASK_TYPE, limit=100))
                for kwargs in ({"backend": "flux"}, {"variants": 5}, {"variants": 0}):
                    try:
                        pa.submit("entry", key="waving", **kwargs)
                    except ValueError:
                        pass
                    else:
                        raise AssertionError(f"submit accepted {kwargs}")
                assert len(tq.list_recent_tasks(pa.TASK_TYPE, limit=100)) == before
                print("PASS 11: refused backend or variant count queues nothing")
                queued = pa.submit("free", text="wave")
                payload = next(t for t in tq.list_recent_tasks(pa.TASK_TYPE, limit=100)
                               if t["task_id"] == queued)["payload"]
                assert payload["variants"] == 3, payload
                print("PASS 13: the default variant count is 3")
        finally:
            pc.catalog_path = original_path
            pc.reload_catalogs()
    from app.core import periodic_jobs
    rows = [(r[1], r[2]) for r in periodic_jobs._SUB_TASKS if r[0] is periodic_jobs._sub_pose_animation_candidates]
    assert rows == [(86400, "pose_animation_candidates")], rows
    with patch("app.core.pose_animation.sweep_candidates") as sweep:
        periodic_jobs._sub_pose_animation_candidates()
        sweep.assert_called_once_with()
    print("PASS 12: the sweep runs daily")
    print("All pose animation variant smokes passed")


if __name__ == "__main__":
    main()
