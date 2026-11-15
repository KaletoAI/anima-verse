#!/usr/bin/env python3
"""Ruling A92: the base front's skin detail step does not run for a front made from the FULL-BODY REFERENCE (that
picture already has real skin); fronts made from the profile image or from text keep the step and their fingerprint,
byte for byte — nothing turns due on deploy, and the world switch stays as it is.

Usage:
    ./.venv/bin/python scripts/smoke_skin_step_full_body.py

Runs against a THROWAWAY storage + instance directory with a copy of the repo's ``human`` package — no real world,
no hub, no server process. Every render goes to a recorder (``expression_regen.render_character_image``) that writes
an 8x8 PNG; the step itself (``base_skin.run_step``) is a recorder that returns an applied record, so no edit and no
matte model runs. ``socket.socket.connect`` and ``requests.Session.request`` are replaced by counters that refuse:
the run must end with 0 outbound attempts.

The old code is the commit before the ruling, ``OLD`` = c7a1b1bfe: its ``base_body.py`` and ``base_skin.py`` are
executed as modules of their own (``old_fp``), the old ``base_skin`` slotted in for the old ``base_body``'s import.

Fixture (world switch ``base_body.skin_detail_step`` ON — the shipped default): ``Demo`` (human-roleplay, a profile
image), ``DemoBare`` (the same without one: its front is made from text), ``DemoFull`` (a profile image AND a
full-body reference generated from it, ``full_body_reference.generate_base``).

Expected, derived by hand from the brief:

[1] Fingerprints before any render (no stored front, so the source is what the front is made from now):
      prompt_fingerprint(Demo) == old_fp(Demo) and prompt_fingerprint(DemoBare) == old_fp(DemoBare) — the profile
      and the text source add the skin part exactly as the old code did;
      prompt_fingerprint(DemoFull) == old_fp(DemoFull, switch OFF) — the payload without the ``skin_step`` key —
      and != old_fp(DemoFull) (the old code put the skin part in).
[2] The render (generate_base_images, all four views):
      Demo and DemoBare: run_step called once each (the front), the front sidecar's skin_step ``applied``; the
        recorded prompt_fingerprint == old_fp (byte-identical record) and prompts_current True;
      DemoFull: run_step NOT called; skin_step = {"applied": False, "outcome": "off", "reason":
        NOT_USED_FULL_BODY}; no neutral front stored; recorded fingerprint == old_fp(DemoFull, switch OFF);
        prompts_current True; every view current (base_view_states).
[3] The job counts (first attempts): base_rebuild_steps over the plan {views: all four, model: False} —
      Demo: view front 1 + skin front 1 + three views 1 each = 5; DemoFull: 4 (no "skin front"); the difference is
      exactly 1 (SKIN_STEP_JOBS). base_rebuild_cost hub_jobs 5 / 4. figure_build._plain_jobs: Demo front 2,
      front_full_body 1; DemoFull front 1, front_full_body 1 (the full-body tile's "then the front is due" count).
      With the switch OFF: every front count 1 (as before the ruling).
[4] A stored profile-made front once a full-body reference is set (Demo, set_base): the stored front judges, so
      prompt_fingerprint(Demo) is still old_fp(Demo); prompts_current True; the improvement plan
      (base_refresh_plan()) reason "" (not "older_prompts" — nothing runs by itself); Run all's plan
      (missing=True) reason "reference" (A87, by click) and its steps have NO "skin front" (the front is re-made
      from the full-body reference): hub jobs 4 + the model stages.
[5] A full-body front rendered WITH the step before the ruling (DemoFull's sidecars rewritten to old_fp(DemoFull)
      with the switch on, skin_step applied): it counts current — prompts_current True, every view current,
      base_refresh_plan() reason "" — the step only added fine detail the picture already has.
[6] "Run skin step": POST …/base-body/skin-step for DemoFull -> 409, detail NOT_USED_FULL_BODY, nothing started;
      for Demo (its stored front is profile-made, though a full-body reference is set) -> 202, started once.
      apply_skin_step(DemoFull) raises NotUsed. base_skin.info: DemoFull {enabled False, world_enabled True, note
      NOT_USED_FULL_BODY}; Demo {enabled True, world_enabled True, note ""}.
[7] The config description of skin_detail_step ends "Not used for fronts made from a full-body reference."
[8] Outbound attempts: 0.
"""
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OLD = "c7a1b1bfe"
FAILS = []
OUTBOUND = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:400] + ("" if ok else f" — expected {want!r}"[:400]))
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


def png(path: Path, pixel=(200, 100, 50, 255)) -> None:
    from PIL import Image
    im = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    im.putpixel((4, 4), pixel)
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path)


def png_bytes(grey: int) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (grey, grey, grey)).save(buf, format="PNG")
    return buf.getvalue()


RENDERED = png_bytes(200)


def recorder(character_name, *, output_stem, **kw):
    out = Path(output_stem).with_suffix(".png")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(RENDERED)
    extra = kw.get("sidecar_extra") or {}
    out.with_suffix(".json").write_text(json.dumps({"created_at": "2026-11-15T10:00:00+00:00", **extra}))
    return out


STEP_CALLS = []


def old_modules():
    """The old ``base_body`` / ``base_skin`` (commit ``OLD``) as modules of their own."""
    mods = {}
    for name in ("base_skin", "base_body"):
        src = subprocess.run(["git", "-C", str(ROOT), "show", f"{OLD}:app/core/{name}.py"],
                             capture_output=True, text=True, check=True).stdout
        mod = types.ModuleType(f"{name}_{OLD}")
        mod.__file__ = f"{name}_{OLD}.py"
        exec(compile(src, mod.__file__, "exec"), mod.__dict__)
        mods[name] = mod
    return mods


def main() -> int:
    block_network()
    with tempfile.TemporaryDirectory(prefix="skin-full-body-") as tmp:
        root = Path(tmp)
        os.environ["STORAGE_DIR"] = str(root / "world")
        os.environ["INSTANCE_DIR"] = str(root / "instance")
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "instance")
        paths.get_config_path().write_text(json.dumps({"packages": {"enabled": "human"},
                                                       "base_body": {"skin_detail_step": True}}))
        from app.core import config
        config.load(paths.get_config_path(), instance_path=root / "instance/config.json")
        from app.core import db
        db.init_schema()
        plugins = root / "plugins"
        shutil.copytree(ROOT / "plugins" / "human", plugins / "human")
        from app.plugins.loader import discover_packages
        discover_packages(plugins, force=True)

        import app.core as core_pkg
        from app.core import base_body, base_skin, expression_regen, figure_build, full_body_reference as fbr
        from app.core.config_schema import SECTIONS as CONFIG_SCHEMA
        from app.models.character import get_character_dir, get_character_images_dir, get_character_profile, \
            save_character_profile
        check("switch on (fixture)", base_skin.enabled(), True)
        human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
                 "character_appearance": "{gender}, {age} years old, freckles, long dark hair",
                 "body_slots": {"skin": {"tone": "olive"}, "eyes": {"color": "green"},
                                "build": {"type": "athletic"}}}
        for name, image in (("Demo", True), ("DemoBare", False), ("DemoFull", True)):
            check(f"create {name}", save_character_profile(name, json.loads(json.dumps(human)), create_new=True), True)
            if image:
                png(get_character_images_dir(name) / f"{name}_1.png")
                stored = get_character_profile(name)
                stored["profile_image"] = f"{name}_1.png"
                check(f"profile image {name}", save_character_profile(name, stored), True)
        expression_regen.render_character_image = recorder
        fbr.generate_base("DemoFull")
        check("DemoFull is made from the full-body reference",
              base_body.front_reference("DemoFull").get("source"), "full_body")

        def stub_step(character_name, front, neutral, *, profile):
            STEP_CALLS.append(character_name)
            return {"version": base_skin.SKIN_STEP_VERSION, "occasion": base_skin.SKIN_OCCASION,
                    "prompt": base_skin.skin_prompt(profile), "transfer": base_skin.transfer_params(),
                    "neutral": neutral.name, "applied": True, "outcome": base_skin.APPLIED}
        base_skin.run_step = stub_step

        old = old_modules()

        def old_fp(name, *, switch=True):
            with patch.dict(sys.modules, {"app.core.base_skin": old["base_skin"]}), \
                    patch.object(core_pkg, "base_skin", old["base_skin"], create=True), \
                    patch.object(old["base_skin"], "enabled", lambda: switch):
                return old["base_body"].prompt_fingerprint(name)

        print("[1] fingerprints before any render")
        # generate_base_images makes the first hairstyle (ensure_hairstyle) — the texts the fingerprint reads;
        # make it now so before and after compare the same texts.
        from app.core.garment_hair import ensure_hairstyle
        for name in ("Demo", "DemoBare", "DemoFull"):
            try:
                ensure_hairstyle(name)
            except ValueError:
                pass
        fp_old = {n: old_fp(n) for n in ("Demo", "DemoBare", "DemoFull")}
        fp_old_off = {n: old_fp(n, switch=False) for n in ("Demo", "DemoBare", "DemoFull")}
        check("the switch is in the old fingerprint", fp_old["Demo"] != fp_old_off["Demo"], True)
        check("profile source: byte-identical", base_body.prompt_fingerprint("Demo"), fp_old["Demo"])
        check("text source: byte-identical", base_body.prompt_fingerprint("DemoBare"), fp_old["DemoBare"])
        check("full-body source: no skin part", base_body.prompt_fingerprint("DemoFull"), fp_old_off["DemoFull"])
        check("full-body source: not the old value", base_body.prompt_fingerprint("DemoFull") != fp_old["DemoFull"],
              True)

        print("[2] the render")
        for name in ("Demo", "DemoBare", "DemoFull"):
            STEP_CALLS.clear()
            base_body.generate_base_images(name)
            bsig = base_body.base_signature(name)
            refs = get_character_dir(name) / "model_refs"
            meta = json.loads((refs / f"tpose_{bsig}.json").read_text())
            neutral = base_skin.neutral_path(name, bsig)
            if name == "DemoFull":
                check(f"{name}: the step does not run", STEP_CALLS, [])
                check(f"{name}: front record", meta.get("skin_step"),
                      {"applied": False, "outcome": "off", "reason": base_skin.NOT_USED_FULL_BODY})
                check(f"{name}: no neutral front", neutral, None)
                check(f"{name}: recorded fingerprint without the skin part", meta.get("prompt_fingerprint"),
                      fp_old_off[name])
            else:
                check(f"{name}: the step runs once", STEP_CALLS, [name])
                check(f"{name}: front record applied", (meta.get("skin_step") or {}).get("outcome"), "applied")
                check(f"{name}: a neutral front", neutral is not None, True)
                check(f"{name}: recorded fingerprint byte-identical to the old code", meta.get("prompt_fingerprint"),
                      fp_old[name])
            check(f"{name}: prompts current", base_body.prompts_current(name, bsig), True)
            check(f"{name}: every view current",
                  sorted({s["state"] for s in base_body.base_view_states(name).values()}), ["current"])

        print("[3] job counts")
        plan = {"views": list(base_body.BASE_VIEWS), "model": False}

        def steps(name):
            return base_body.base_rebuild_steps(name, {**plan, "signature": base_body.base_signature(name)})
        check("Demo steps", steps("Demo"), [("view front", 1), ("skin front", 1), ("view back", 1),
                                            ("view left", 1), ("view right", 1)])
        check("DemoFull steps", steps("DemoFull"), [("view front", 1), ("view back", 1), ("view left", 1),
                                                    ("view right", 1)])
        demo_cost = base_body.base_rebuild_cost("Demo", plan={**plan, "signature": base_body.base_signature("Demo")})
        full_cost = base_body.base_rebuild_cost("DemoFull",
                                                plan={**plan, "signature": base_body.base_signature("DemoFull")})
        check("rebuild cost 5 / 4", (demo_cost["hub_jobs"], full_cost["hub_jobs"]), (5, 4))
        check("difference exactly SKIN_STEP_JOBS", demo_cost["hub_jobs"] - full_cost["hub_jobs"],
              base_body.SKIN_STEP_JOBS)
        jd = figure_build._plain_jobs("Demo", base_body.base_signature("Demo"))
        jf = figure_build._plain_jobs("DemoFull", base_body.base_signature("DemoFull"))
        check("plain jobs Demo", (jd["front"], jd["front_full_body"]), (2, 1))
        check("plain jobs DemoFull", (jf["front"], jf["front_full_body"]), (1, 1))
        with patch.object(base_skin, "enabled", lambda: False):
            jo = figure_build._plain_jobs("Demo", base_body.base_signature("Demo"))
            check("switch off: front 1", (jo["front"], jo["front_full_body"]), (1, 1))
            check("switch off: no skin front", [s for s, _j in steps("Demo")].count("skin front"), 0)

        print("[4] a stored profile-made front once a full-body reference is set")
        fbr.generate_base("Demo")
        check("Demo now made from the full-body reference", base_body.front_reference("Demo").get("source"),
              "full_body")
        check("stored front judges: fingerprint unchanged", base_body.prompt_fingerprint("Demo"), fp_old["Demo"])
        check("prompts current", base_body.prompts_current("Demo", base_body.base_signature("Demo")), True)
        check("improvement plan: nothing", base_body.base_refresh_plan("Demo")["reason"], "")
        run_all = base_body.base_refresh_plan("Demo", missing=True)
        check("Run all plan: reference", run_all["reason"], "reference")
        run_steps = base_body.base_rebuild_steps("Demo", run_all)
        check("Run all: no skin front", [s for s, _j in run_steps].count("skin front"), 0)
        check("Run all: four view jobs", sum(j for s, j in run_steps if s.startswith("view ")), 4)
        check("Regenerate front now 1", figure_build._plain_jobs("Demo", base_body.base_signature("Demo"))["front"], 1)

        print("[5] a full-body front rendered with the step before the ruling")
        bsig = base_body.base_signature("DemoFull")
        refs = get_character_dir("DemoFull") / "model_refs"
        for view in base_body.BASE_VIEWS:
            side = refs / f"{base_body._kind(view)}_{bsig}.json"
            meta = json.loads(side.read_text())
            meta["prompt_fingerprint"] = fp_old["DemoFull"]
            if view == "front":
                meta["skin_step"] = {"version": 1, "applied": True, "outcome": "applied"}
            side.write_text(json.dumps(meta))
        check("current", base_body.prompts_current("DemoFull", bsig), True)
        check("every view current",
              sorted({s["state"] for s in base_body.base_view_states("DemoFull").values()}), ["current"])
        check("improvement plan: nothing", base_body.base_refresh_plan("DemoFull")["reason"], "")
        check("another fingerprint is still older",
              base_body.recorded_fingerprint("DemoFull", bsig, "front", {"prompt_fingerprint": "0" * 12},
                                             current=base_body.prompt_fingerprint("DemoFull")), "0" * 12)

        print("[6] Run skin step")
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.core.auth_dependency import require_admin
        from app.routes import characters as char_routes
        app = FastAPI()
        app.include_router(char_routes.router)
        app.dependency_overrides[require_admin] = lambda: {"role": "admin"}
        client = TestClient(app)
        started = []
        with patch.object(base_skin, "start_skin_step", lambda name: started.append(name)):
            r = client.post("/characters/DemoFull/base-body/skin-step")
            check("full-body front: 409 with the reason", (r.status_code, r.json().get("detail"), started),
                  (409, base_skin.NOT_USED_FULL_BODY, []))
            r = client.post("/characters/Demo/base-body/skin-step")
            check("profile-made front: started", (r.status_code, started), (202, ["Demo"]))
        try:
            base_skin.apply_skin_step("DemoFull")
            got = "nothing"
        except base_skin.NotUsed as e:
            got = str(e)
        check("apply_skin_step refuses", got, base_skin.NOT_USED_FULL_BODY)
        info_full = base_skin.info("DemoFull", base_body.base_signature("DemoFull"))
        info_demo = base_skin.info("Demo", base_body.base_signature("Demo"))
        check("info DemoFull", (info_full["enabled"], info_full["world_enabled"], info_full["note"]),
              (False, True, base_skin.NOT_USED_FULL_BODY))
        check("info Demo", (info_demo["enabled"], info_demo["world_enabled"], info_demo["note"]), (True, True, ""))
        check("plain body payload carries it",
              (base_body.base_info("DemoFull").get("skin") or {}).get("enabled"), False)

        print("[7] config description")
        desc = CONFIG_SCHEMA["base_body"]["fields"]["skin_detail_step"]["description"]
        check("description", desc.endswith("Not used for fronts made from a full-body reference."), True)

    print("[8] outbound attempts")
    check("outbound", OUTBOUND, [])
    if FAILS:
        print(f"\nFAILED: {len(FAILS)} — {FAILS}")
        return 1
    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
