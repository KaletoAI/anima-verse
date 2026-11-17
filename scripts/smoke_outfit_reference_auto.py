#!/usr/bin/env python3
"""Ruling A104: the worn outfit's full-body reference is generated automatically BEFORE its dressed front.

Usage:
    ./.venv/bin/python scripts/smoke_outfit_reference_auto.py

Runs against a THROWAWAY storage + instance directory with a copy of the repo's ``human`` package — no real world,
no hub, no server process. Every render goes to a recorder (``expression_regen.render_character_image``) that
writes an 8x8 PNG; ``full_body_reference.generate_outfit`` is replaced by a stand-in that takes the real run lock
(``_reserve`` / ``_release``) and records the gallery picture Demo_2.png through the real ``set_outfit`` (or
raises, per case). ``socket.socket.connect`` and ``requests.Session.request`` refuse and count: 0 outbound.

Fixture (as smoke_reference_front [5]): ``Demo`` (human-roleplay, bald, base-body pipeline) with profile image
Demo_1.png, nothing worn; the figure stubbed: plain shape BSIG, texture "texabc", every dress text "a red dress"
(something is painted). Worn outfit key = "or" + sha256('{"open":[],"pieces":[]}')[:10]. The base views are made
first (generate_base_images, 4 recorder calls, cleared before the cases).

Expected, derived by hand from the ruling ("Die Ganzkörper-Referenz des Outfit-Körpers muss automatisch vor der
Frontansicht erzeugt werden"):

(a) no record + a source (the profile image): auto_due True, auto_jobs(fig) = GENERATE_JOBS = 1, build_note
    outfit_auto True; generate_dressed_images(front, force) -> the stand-in runs ONCE, then ONE render: occasion
    "outfit_front", use case "outfit_edit" — Ruling A125: an edit of the base front tpose_<bsig>.png (input 1) with
    a frozen copy named Demo_2.png as the SECOND picture, sidecar outfit_reference_sha256 = sha256(Demo_2.png)
    (``view_composite.compose`` stubbed: copies the edit). Afterwards build_note outfit True, outfit_auto False.
(b) the record exists: the same call -> the stand-in is NOT called (still 1), one render with Demo_2.png second.
(c) record cleared, the stand-in raises RuntimeError("boom"): one attempt, then ONE render on the old path
    (occasion "outfit_front", use case DRESS_USE_CASE, reference = the base front on grey, no second picture, no
    outfit_reference_sha256 in the sidecar); auto_note = AUTO_FAILED with error "boom" = "Full-body reference
    failed: boom — front made from the base front"; build_note outfit_failed the same; outfit_failure(Demo, osig)
    "" (the pass is no failure — the build continues).
(d) no source (profile_image dropped, no plain-body reference, no other gallery picture counts as the profile
    image): auto_due False, auto_jobs 0, the stand-in not called, one old-path render.
(e) plan count: figure_build._with_reference(Step("texture", "Texture: views 2", 2), front=True) -> jobs 3, label
    + AUTO_REFERENCE_LABEL only while auto_jobs is 1 (state (a)); with a record or without a source jobs stay 2;
    front=False keeps 2 in every state.
(g) after (c)'s real failure with the profile image Demo_1.png as source: auto_due False, auto_jobs 0, the plan +0;
    the next pass makes NO call (attempts stay 2) and renders the old path; the note stays.
(h) the source changes (Demo_1.png rewritten with another pixel -> another sha256): auto_due True again; the next
    pass (stand-in still failing) tries once more (attempts 3). clear_auto_failure (Generate / pick) also re-allows.
(f) the run lock: another run of Demo holds the lock (``_reserve(Demo, "base")``); ensure_outfit waits, the other
    run records Demo_2.png and releases after ~0.3 s -> ensure_outfit returns that record with note "", the
    stand-in raised ALREADY_RUNNING once and made nothing itself (made 0).
(i) a busy backend is load, not a failure (review 09#6): the record cleared and the failure marks dropped
    (clear_auto_failure), the stand-in raises ``BackendBusyError("backend busy")``; generate_dressed_images
    (no raise_load) -> one attempt (attempts 2), ONE old-path render (DRESS_USE_CASE), auto_note = AUTO_FAILED
    with error "backend busy", and auto_due STAYS True (the next pass tries again; fails on 3f2ce338e: False). The
    same with RuntimeError("boom") -> attempts 3, auto_due False (a real failure still blocks).
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS = []
OUTBOUND = []
CALLS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


def block_network():
    import socket
    import requests

    def refuse_connect(self, *a, **kw):
        OUTBOUND.append(("socket", a))
        raise OSError("network blocked in smoke")

    def refuse_request(self, method, url, *a, **kw):
        OUTBOUND.append(("requests", method, url))
        raise OSError("network blocked in smoke")
    socket.socket.connect = refuse_connect
    requests.Session.request = refuse_request


def png_rgba(path: Path, pixel=(200, 100, 50, 255)) -> None:
    from PIL import Image
    im = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    im.putpixel((4, 4), pixel)
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path)


def png_grey(grey: int) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (grey, grey, grey)).save(buf, format="PNG")
    return buf.getvalue()


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def recorder(character_name, *, output_stem, **kw):
    ref = kw.get("reference_image")
    CALLS.append({"name": character_name, "ref_name": Path(ref).name if ref else None, **kw})
    out = Path(output_stem).with_suffix(".png")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(png_grey(200))
    extra = kw.get("sidecar_extra") or {}
    out.with_suffix(".json").write_text(json.dumps({"created_at": "2026-11-15T10:00:00+00:00", **extra}))
    return out


def main() -> int:
    block_network()
    with tempfile.TemporaryDirectory(prefix="outfit-ref-auto-") as tmp:
        root = Path(tmp)
        os.environ["STORAGE_DIR"] = str(root / "world")
        os.environ["INSTANCE_DIR"] = str(root / "instance")
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "instance")
        paths.get_config_path().write_text(json.dumps({"packages": {"enabled": "human"},
                                                       "base_body": {"skin_detail_step": False}}))
        from app.core import config
        config.load(paths.get_config_path(), instance_path=root / "instance/config.json")
        from app.core import db
        db.init_schema()
        plugins = root / "plugins"
        shutil.copytree(ROOT / "plugins" / "human", plugins / "human")
        from app.plugins.loader import discover_packages
        discover_packages(plugins, force=True)

        from app.core import base_body, expression_regen, figure, figure_build, model_refs
        from app.core import full_body_reference as fbr
        from app.core import outfit_references
        from app.models.character import (get_character_dir, get_character_images_dir, get_character_profile,
                                          save_character_profile)
        human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
                 "body_slots": {"skin": {"tone": "olive"}, "eyes": {"color": "green"},
                                "build": {"type": "athletic"}}}
        check("create Demo", save_character_profile("Demo", json.loads(json.dumps(human)), create_new=True), True)
        images = get_character_images_dir("Demo")
        png_rgba(images / "Demo_1.png")
        stored = get_character_profile("Demo")
        stored["profile_image"] = "Demo_1.png"
        check("profile image", save_character_profile("Demo", stored), True)
        png_rgba(images / "Demo_2.png", pixel=(20, 20, 30, 255))

        expression_regen.render_character_image = recorder
        refs = get_character_dir("Demo") / "model_refs"
        bsig = base_body.base_signature("Demo")
        base_body.generate_base_images("Demo")
        check("base views", len(CALLS), 4)

        key = "or" + hashlib.sha256(b'{"open":[],"pieces":[]}').hexdigest()[:10]
        osig = "smokeosig"

        def fig(*_a, profile=None, **_kw):
            return figure.Figure(signature=osig, bsig=bsig, shape=bsig, texture="texabc", in_body=(),
                                 painted=("dress",), own=())
        figure.delivered_figure = fig
        figure.delivered_figure_cached = fig
        base_body.figure_texts = lambda c, f, items, profile=None: {v: "a red dress" for v in base_body.dressed_views()}
        model_refs.current_outfit_state = lambda c: ({}, [], osig)
        figure_build.start = lambda *a, **kw: {"status": "started"}
        figure_build.request = lambda *a, **kw: True

        stand = {"mode": "ok", "attempts": 0, "made": 0}

        def stand_in(character_name, *, key=None, reserved=False, painted=None):
            stand["attempts"] += 1
            if not reserved:
                fbr._reserve(character_name, key)
            error = None
            try:
                if stand["mode"] == "boom":
                    raise RuntimeError("boom")
                if stand["mode"] == "busy":
                    from app.imagegen.base import BackendBusyError
                    raise BackendBusyError("backend busy")
                stand["made"] += 1
                from app.core.outfit_references import references_dir   # a generated picture lives there
                references_dir(character_name).mkdir(parents=True, exist_ok=True)
                shutil.copyfile(images / "Demo_2.png", references_dir(character_name) / "Demo_2.png")
                return fbr.set_outfit(character_name, "Demo_2.png", key=key, pieces={},
                                      origin=fbr.ORIGIN_GENERATED, prompt="p")
            except Exception as e:
                error = str(e)
                raise
            finally:
                fbr._release(character_name, key, error)
        fbr.generate_outfit = stand_in
        step2 = figure_build.Step("texture", "Texture: views 2", 2)

        from app.core import view_composite as _vc

        def fake_compose(base_view, draft_file, target, *, rule="outfit", **_kw):
            Path(target).write_bytes(Path(draft_file).read_bytes())
            return {"version": _vc.VERSION, "rule": rule, "ok": True, "iou": 1.0,
                    "coverage": {"score": 0.9, "region": 0.2}, "mask_share": 0.2, "reasons": []}
        _vc.compose = fake_compose

        def second(call):
            return [Path(p).name for p in call.get("extra_reference_images") or []]

        def dress_front():
            CALLS.clear()
            base_body.generate_dressed_images("Demo", pieces={}, items=[], signature=osig, force=True, view="front")
            return list(CALLS)

        print("(a) no record + a source")
        check("auto_due", fbr.auto_due("Demo", {}, (), painted=()), True)
        check("auto_jobs", fbr.auto_jobs("Demo", fig()), 1)
        note = fbr.build_note("Demo")
        check("note before", (note["outfit"], note["outfit_auto"], note["outfit_failed"]), (False, True, ""))
        e_on = figure_build._with_reference("Demo", step2, fig(), osig, get_character_profile("Demo"), True)
        check("(e) plan +1", (e_on.jobs, e_on.label), (3, "Texture: views 2" + figure_build.AUTO_REFERENCE_LABEL))
        e_off = figure_build._with_reference("Demo", step2, fig(), osig, get_character_profile("Demo"), False)
        check("(e) front not rendered: +0", e_off.jobs, 2)
        calls = dress_front()
        check("generated once", (stand["attempts"], stand["made"]), (1, 1))
        one = calls[0] if len(calls) == 1 else {}
        check("one render from the new record",
              (len(calls), one.get("occasion"), one.get("image_use_case"), one.get("ref_name"), second(one),
               (one.get("sidecar_extra") or {}).get("outfit_reference_sha256")),
              (1, "outfit_front", "outfit_edit", f"tpose_{bsig}.png", ["Demo_2.png"], sha(images / "Demo_2.png")))
        stored_meta = json.loads((refs / f"tpose_{osig}.json").read_text())
        check("stored sidecar", stored_meta.get("outfit_reference_sha256"), sha(images / "Demo_2.png"))
        note = fbr.build_note("Demo")
        check("note after", (note["outfit"], note["outfit_auto"]), (True, False))

        print("(b) the record exists")
        check("(e) with a record: +0",
              figure_build._with_reference("Demo", step2, fig(), osig, get_character_profile("Demo"), True).jobs, 2)
        calls = dress_front()
        check("not called", stand["attempts"], 1)
        check("render from the record", [(c.get("image_use_case"), second(c)) for c in calls],
              [("outfit_edit", ["Demo_2.png"])])

        print("(c) the generation fails")
        outfit_references.clear_reference("Demo", key)
        stand["mode"] = "boom"
        calls = dress_front()
        check("one attempt", stand["attempts"], 2)
        one = calls[0] if len(calls) == 1 else {}
        check("old path", (len(calls), one.get("occasion"), one.get("image_use_case"), bool(second(one)),
                           "outfit_reference_sha256" in (one.get("sidecar_extra") or {})),
              (1, "outfit_front", base_body.DRESS_USE_CASE, False, False))
        failed = "Full-body reference failed: boom — front made from the base front"
        check("AUTO_FAILED wording", fbr.AUTO_FAILED.format(error="boom"), failed)
        check("auto_note", fbr.auto_note("Demo", key), failed)
        check("build_note outfit_failed", fbr.build_note("Demo")["outfit_failed"], failed)
        check("no pass failure", base_body.outfit_failure("Demo", osig), "")

        print("(g) the same source: no automatic retry")
        check("auto_due", fbr.auto_due("Demo", {}, (), painted=()), False)
        check("auto_jobs", fbr.auto_jobs("Demo", fig()), 0)
        check("plan +0",
              figure_build._with_reference("Demo", step2, fig(), osig, get_character_profile("Demo"), True).jobs, 2)
        calls = dress_front()
        check("no call", stand["attempts"], 2)
        check("old path", [c.get("image_use_case") for c in calls], [base_body.DRESS_USE_CASE])
        check("note stays", fbr.build_note("Demo")["outfit_failed"], failed)

        print("(h) the source changed: tried again")
        png_rgba(images / "Demo_1.png", pixel=(1, 2, 3, 255))
        check("auto_due", fbr.auto_due("Demo", {}, (), painted=()), True)
        dress_front()
        check("tried again", stand["attempts"], 3)
        check("blocked again", fbr.auto_due("Demo", {}, (), painted=()), False)
        fbr.clear_auto_failure("Demo", key)
        check("Generate/pick re-allows", fbr.auto_due("Demo", {}, (), painted=()), True)

        print("(d) no source")
        stored = get_character_profile("Demo")
        stored.pop("profile_image", None)
        check("profile image dropped", save_character_profile("Demo", stored), True)
        check("auto_due", fbr.auto_due("Demo", {}, (), painted=()), False)
        check("(e) no source: auto_jobs 0", fbr.auto_jobs("Demo", fig()), 0)
        check("(e) no source: +0",
              figure_build._with_reference("Demo", step2, fig(), osig, get_character_profile("Demo"), True).jobs, 2)
        calls = dress_front()
        check("not called", stand["attempts"], 3)
        check("old path", [(c.get("image_use_case")) for c in calls], [base_body.DRESS_USE_CASE])

        print("(f) a run of the character already holds the lock")
        stored = get_character_profile("Demo")
        stored["profile_image"] = "Demo_1.png"
        save_character_profile("Demo", stored)
        stand["mode"], stand["attempts"], stand["made"] = "ok", 0, 0
        fbr._reserve("Demo", fbr.BASE_SLOT)

        def other_run():
            time.sleep(0.3)
            fbr.set_outfit("Demo", "Demo_2.png", key=key, pieces={}, origin=fbr.ORIGIN_GENERATED)
            fbr._release("Demo", fbr.BASE_SLOT, None)
        fbr.AUTO_POLL_S = 0.05
        threading.Thread(target=other_run, daemon=True).start()
        record, note = fbr.ensure_outfit("Demo", {}, (), painted=())
        check("waited and used its record", (bool(record) and record.get("image"), note, stand["attempts"],
                                             stand["made"]), ("Demo_2.png", "", 1, 0))

        print("(i) a busy backend is load")
        outfit_references.clear_reference("Demo", key)
        fbr.clear_auto_failure("Demo")
        check("due again", fbr.auto_due("Demo", {}, (), painted=()), True)
        stand["mode"] = "busy"
        calls = dress_front()
        check("one attempt", stand["attempts"], 2)
        check("old path", [c.get("image_use_case") for c in calls], [base_body.DRESS_USE_CASE])
        check("auto_note", fbr.auto_note("Demo", key), fbr.AUTO_FAILED.format(error="backend busy"))
        check("still due: the next pass tries again", fbr.auto_due("Demo", {}, (), painted=()), True)
        stand["mode"] = "boom"
        dress_front()
        check("a real failure: attempts", stand["attempts"], 3)
        check("a real failure blocks", fbr.auto_due("Demo", {}, (), painted=()), False)

    print("outbound attempts")
    check("outbound", OUTBOUND, [])
    if FAILS:
        print(f"\nFAILED: {len(FAILS)} — {FAILS}")
        return 1
    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
