#!/usr/bin/env python3
"""Ruling A74b: the A-pose front is made FROM A REFERENCE IMAGE — the base front from the profile image, an outfit's
dressed front from that outfit's own picture — and nothing runs because a reference changed.

Usage:
    ./.venv/bin/python scripts/smoke_reference_front.py

Runs against a THROWAWAY storage + instance directory with a copy of the repo's ``human`` package — no real world,
no hub, no server process. Every render goes to a recorder (``expression_regen.render_character_image``) that
writes an 8x8 PNG; the service checks call ``ImageService.generate_on_backend`` with a stand-in backend whose
``run_on_backend`` raises before any request. ``socket.socket.connect`` and ``requests.Session.request`` are
replaced by counters that refuse: the run must end with 0 outbound attempts.

Fixture: ``Demo`` (human-roleplay, bald: no hair slot, base-body pipeline) with profile image Demo_1.png (an 8x8
RGBA picture, transparent but for one opaque pixel); ``DemoBare`` the same without a profile image. BSIG =
base_signature(Demo).

Expected, derived by hand from the user's decisions (brief of Ruling A74b) and the validated hub job c265fd78
(prompt: "change the view and position of the character in the picture to " + the bald head + the body text +
the base front's framing/light tail + the pose text; no gender, age, height or build words):

[1] The service gate. A payload with ``require_reference`` and a reference override:
      backend with 0 reference slots          -> BackendNotApplicableError "...this render is an edit of one"
      backend with 1 slot, slot resolves {}   -> the same (the reference does not condition the attempt)
      backend with 1 slot, the reference slotted -> reaches the backend (run_on_backend called)
      the same payload WITHOUT require_reference on 0 slots -> reaches the backend (unchanged behaviour)
    Routing (``routing.run_routed('base_front', …)``): chain [no-ref, with-ref] -> "with-ref", attempts
    [no-ref, with-ref], no-ref NOT in cooldown (not applicable = no cooldown); chain [no-ref] alone -> an
    exception, the result is never a text render and no other backend is tried (attempts [no-ref]).
[2] Base front with a profile image (generate_base_images(Demo), skin step off): 4 renders; the front's
    use case "base_front_edit", occasion "base_front", reference = a copy NAMED Demo_1.png inside
    model_refs/.editref_* (not the gallery file; its transparent corner on grey (128, 128, 128)),
    require_reference True; style_character = edit_character(Demo) = BALD_HEAD + ", " + SAME_FACE + ", " + BODY_TEXT
    (SAME_FACE = "the same face as the person in the picture", Ruling A94 — Demo has no facial hair; the human
    package adds no base-body text) — so no "female", no "30 years old", no "average height", no
    "athletic build" in it. The composed natural-family prompt (config.join_style_prompt over the use case's
    style with that block, then the pose text) starts with
    "change the view and position of the character in the picture to " + BALD_HEAD + ", " + SAME_FACE + ", " +
    BODY_TEXT +
    ", the whole figure from head to feet inside the frame with both hands inside it and empty margin above
    the head and below the feet, plain neutral background, flat even shadowless lighting on the whole figure
    and the face, sharp focus" and ends with base_prompt(front)[0]. The front's sidecar_extra records
    front_reference {method "reference", image "Demo_1.png", sha256 = sha256(Demo_1.png bytes), prompt =
    _edit_fingerprint}. The views (back/left/right) are edits of the front as before (no require_reference).
    front_reference_state(Demo): current True, reason "".
[3] No profile image (DemoBare): no refusal (decision 2 — the text path): 4 renders, the front's use case
    "base_front", reference None, require_reference False, style_character = base_character(front),
    front_reference {"method": "text"}; base_info(DemoBare)["front_reference"]["note"] = NO_PROFILE_IMAGE_NOTE.
[4] A reference change makes the front due — by a click only:
      the front's sidecar without front_reference (rendered before A74b, = from text) ->
        front_reference_state reason FRONT_MADE_FROM_TEXT; base_refresh_plan(missing=True) reason "reference",
        views all four; base_refresh_plan(missing=False) reason != "reference" (the base_refresh improvement
        never spends on it) and base_refresh._judge(Demo) None; prompts_current still True; the front tile of
        annotate_base_info(base_info) stale with that reason;
      sidecar front_reference with another sha256 -> reason FRONT_OTHER_REFERENCE;
      no render happened in [4] (recorder count unchanged).
[5] Outfit reference (figure stubbed as in smoke_dressed_view_regenerate: the plain shape BSIG, texture
    "texabc", front dress text "a red dress", worn pieces {} -> outfit key "or" + sha256('{"open":[],
    "pieces":[]}')[:10]). outfit_references.outfit_key({"top": "b", "legs": "a"}, ["b", "zz"]) =
    "or" + sha256('{"open":["b"],"pieces":["a","b"]}')[:10] (sorted ids; an open id not worn is dropped).
      set_reference(Demo, "Demo_2.png") (a second gallery picture): saves only — 0 renders, figure_build.start /
      request not called; references_of(Demo) holds the key with sha256(Demo_2.png).
      generate_dressed_images(front, force): ONE render (Ruling A125, superseding A74b's outfit part), occasion
      "outfit_front", use case "outfit_edit", input 1 = a copy of the BASE front tpose_<BSIG>.png in
      model_refs/.viewref_*, require_reference True, input 2 (extra_reference_images) = one copy named Demo_2.png
      in model_refs/.editref_*, with EDIT_SECOND_PICTURE (front: no "seen" words); sidecar
      outfit_reference_sha256 = sha256(Demo_2.png), base_signature BSIG, base_image_sha256 = sha256 of the base
      front. ``view_composite.compose`` is stubbed here (copies the edit, record ok; asserted base_alpha=True);
      the real composite is smoke_dressed_edit_a125.py.
      dressed_image(front) is that file; after clear_reference it is None (due: "made from a reference image
      that was cleared"); after set_reference(Demo_3.png) None again (another picture).
      Without a reference the dressed front is the old edit of the body's front (use case "outfit_edit").
      texture_key: equal to the key without references while the outfit has none; a reference of ANOTHER
      outfit changes nothing; this outfit's reference changes it.
      reference_only_change: a model built as the figure without references, the figure now differing only by
      the reference -> True (the outfit_rebuild improvement passes it over); built as another texture -> False.
[6] Fails on the old code (commit d1ca15228, before A74b): its generate_base_images drew the front with
    ``draw("front", stem, None)`` (no reference image), its config had no "base_front_edit" use case and its
    check_renderable refused a character without a profile image (MissingInput).
[7] Outbound attempts: 0.
"""
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OLD = "d1ca15228"
PREFIX = "change the view and position of the character in the picture to "
FAILS = []
OUTBOUND = []


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


CALLS = []


def recorder(character_name, *, output_stem, **kw):
    ref = kw.get("reference_image")
    corner = None
    if ref is not None:
        from PIL import Image
        with Image.open(ref) as im:
            corner = im.convert("RGB").getpixel((0, 0))
    CALLS.append({"name": character_name, "stem": Path(output_stem), "ref": ref,
                  "ref_name": Path(ref).name if ref else None,
                  "ref_dir": Path(ref).parent.name if ref else None, "corner": corner, **kw})
    out = Path(output_stem).with_suffix(".png")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(png_grey(200))
    extra = kw.get("sidecar_extra") or {}
    out.with_suffix(".json").write_text(json.dumps({"created_at": "2026-11-15T10:00:00+00:00", **extra}))
    return out


def service_gate(profile_file: Path):
    print("[1] the service gate and the routing")
    from app.imagegen import routing, service as svc
    from app.imagegen.base import BackendNotApplicableError, ImageBackend
    from app.imagegen.selection import BackendPool
    from app.core.prompt_builder import PromptBuilder

    class Backend(ImageBackend):
        def __init__(self, name):
            super().__init__(name, "http://unused", 0, "fake", "REF_SMOKE_")
            self.ref_slot_count = 1
            self._available = True

        def check_availability(self):
            return True

        def _generate(self, *args):
            raise AssertionError("No external generation")

    with patch.object(svc.ImageService, "_load_instances", return_value=[]):
        service = svc.ImageService()
    payload = {"prompt": "a pose", "agent_name": "Demo", "auto_enhance": False, "skip_gallery": True,
               "profile_only": True, "image_use_case": "base_front_edit",
               "appearances": [{"name": "Demo", "appearance": ""}],
               "reference_image_override": str(profile_file), "require_reference": True}
    parsed = service._parse_input(json.dumps(payload))
    check("require_reference kept at the service boundary", parsed.get("require_reference"), True)

    class Reached(Exception):
        pass

    def reached(*a, **kw):
        raise Reached()

    backend = Backend("gate")
    outcomes = []
    with (patch.object(service, "_get_instance_config", return_value={}),
          patch.object(service, "run_on_backend", side_effect=reached)):
        for slots, resolved, flag in ((0, None, True), (1, {}, True),
                                      (1, {"input_reference_image_1": str(profile_file)}, True),
                                      (0, None, False)):
            backend.ref_slot_count = slots
            with ExitStack() as stack:
                if resolved is not None:
                    stack.enter_context(patch.object(PromptBuilder, "resolve_reference_slots", return_value={
                        "reference_images": resolved, "has_reference_slots": bool(resolved)}))
                try:
                    service.generate_on_backend(backend, {**parsed, "require_reference": flag}, explicit=False)
                    outcomes.append("returned")
                except BackendNotApplicableError as e:
                    outcomes.append("not applicable: edit" if "edit of one" in str(e) else f"not applicable: {e}")
                except Reached:
                    outcomes.append("reached")
        check("gate outcomes", outcomes, ["not applicable: edit", "not applicable: edit", "reached", "reached"])

        bad, good = Backend("no-ref"), Backend("with-ref")
        bad.ref_slot_count = 0
        good_slots = {"reference_images": {"input_reference_image_1": str(profile_file)}, "has_reference_slots": True}
        pool = BackendPool([bad, good])
        attempts = []

        def render(b):
            attempts.append(b.name)
            with ExitStack() as stack:
                if b is good:
                    stack.enter_context(patch.object(PromptBuilder, "resolve_reference_slots", return_value=good_slots))
                try:
                    service.generate_on_backend(b, dict(parsed), explicit=False)
                except Reached:
                    return b.name
        with (patch.object(routing, "_character_spec", return_value=""),
              patch.object(routing, "_rules", return_value=["no-ref", "with-ref"])):
            result, _route = routing.run_routed("base_front", render, character="Demo", has_ref=True, pool=pool)
        check("chain [no-ref, with-ref]", (result, attempts, bad.in_cooldown()), ("with-ref", ["no-ref", "with-ref"],
                                                                              False))
        attempts.clear()
        with (patch.object(routing, "_character_spec", return_value=""),
              patch.object(routing, "_rules", return_value=["no-ref"])):
            try:
                result = routing.run_routed("base_front", render, character="Demo", has_ref=True, pool=pool)
                got = ("returned", result)
            except Exception as e:  # noqa: BLE001 — the kind is what is checked
                got = ("raised", type(e).__name__)
        check("chain [no-ref] alone: raises, nothing else tried", (got[0], attempts), ("raised", ["no-ref"]))


def main() -> int:
    block_network()
    with tempfile.TemporaryDirectory(prefix="reference-front-") as tmp:
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

        from app.core import base_body, expression_regen, figure, figure_build, model_overview, model_refs
        from app.core import outfit_references
        from app.models.character import (get_character_dir, get_character_images_dir, get_character_profile,
                                          save_character_profile)
        human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
                 "body_slots": {"skin": {"tone": "olive"}, "eyes": {"color": "green"},
                                "build": {"type": "athletic"}}}
        for name, image in (("Demo", True), ("DemoBare", False)):
            check(f"create {name}", save_character_profile(name, json.loads(json.dumps(human)), create_new=True), True)
            if image:
                png_rgba(get_character_images_dir(name) / f"{name}_1.png")
                stored = get_character_profile(name)
                stored["profile_image"] = f"{name}_1.png"
                check(f"profile image {name}", save_character_profile(name, stored), True)
        profile_file = get_character_images_dir("Demo") / "Demo_1.png"

        service_gate(profile_file)

        expression_regen.render_character_image = recorder
        refs = get_character_dir("Demo") / "model_refs"
        bsig = base_body.base_signature("Demo")

        print("[2] the base front is an edit of the profile image")
        base_body.generate_base_images("Demo")
        check("4 renders", len(CALLS), 4)
        front = CALLS[0]
        check("front use case / occasion", (front["image_use_case"], front["occasion"]),
              ("base_front_edit", "base_front"))
        check("front reference: a frozen copy", (front["ref_name"], front["ref"].parent.parent,
                                                 front["ref_dir"].startswith(".editref_"),
                                                 front["ref"] == profile_file, front["corner"]),
              ("Demo_1.png", refs, True, False, (128, 128, 128)))
        check("require_reference only on the front", [bool(c.get("require_reference")) for c in CALLS],
              [True, False, False, False])
        block = base_body.BALD_HEAD + ", the same face as the person in the picture, " + base_body.BODY_TEXT
        check("edit block", (front["style_character"], base_body.edit_character("Demo")), (block, block))
        check("no build words in the block", [w for w in ("female", "30 years old", "average height", "athletic")
                                              if w in front["style_character"]], [])
        style = config.get_use_case_prompts("base_front_edit", "natural", clothed=False,
                                            character=front["style_character"])["prompt_style"]
        composed = config.join_style_prompt(style, front["bare_prompt"], front["style_character"])
        want_head = (PREFIX + block + ", the whole figure from head to feet inside the frame with both hands inside it"
                     " and empty margin above the head and below the feet, plain neutral background, flat even"
                     " shadowless lighting on the whole figure and the face, sharp focus")
        check("composed prompt: the edit instruction, the block, the framing", composed[:len(want_head)], want_head)
        check("composed prompt: ends with the pose text", composed.endswith(base_body.base_prompt("Demo", "front")[0]),
              True)
        check("front_reference recorded", front["sidecar_extra"].get("front_reference"),
              {"method": "reference", "image": "Demo_1.png", "sha256": sha(profile_file),
               "prompt": base_body._edit_fingerprint("Demo", get_character_profile("Demo"))})
        check("editref dir gone", [p.name for p in refs.iterdir() if p.is_dir()], [])
        state = base_body.front_reference_state("Demo")
        check("front current", (state["current"], state["reason"]), (True, ""))

        print("[3] no profile image: the text path")
        CALLS.clear()
        base_body.generate_base_images("DemoBare")
        bare = CALLS[0] if CALLS else {}
        check("4 renders", len(CALLS), 4)
        check("front: text render", (bare.get("image_use_case"), bare.get("ref"), bool(bare.get("require_reference")),
                                     bare.get("style_character") == base_body.base_character("DemoBare", "front"),
                                     (bare.get("sidecar_extra") or {}).get("front_reference")),
              ("base_front", None, False, True, {"method": "text"}))
        check("tab note", (base_body.base_info("DemoBare").get("front_reference") or {}).get("note"),
              base_body.NO_PROFILE_IMAGE_NOTE)

        print("[4] a reference change makes the front due — by a click only")
        CALLS.clear()
        front_json = refs / f"tpose_{bsig}.json"
        meta = json.loads(front_json.read_text())
        meta.pop("front_reference")
        front_json.write_text(json.dumps(meta))
        state = base_body.front_reference_state("Demo")
        check("pre-A74b front: made from text", state["reason"], base_body.FRONT_MADE_FROM_TEXT)
        plan = base_body.base_refresh_plan("Demo", missing=True)
        check("Build / Run all plan", (plan.get("reason"), list(plan.get("views") or [])),
              ("reference", list(base_body.BASE_VIEWS)))
        check("improvement plan never 'reference'", base_body.base_refresh_plan("Demo").get("reason") != "reference",
              True)
        from app.core.improvements.types import base_refresh
        check("base_refresh improvement: no candidate", base_refresh._judge("Demo", get_character_profile("Demo")),
              None)
        check("prompts still current", base_body.prompts_current("Demo", bsig), True)
        tile = model_overview.annotate_base_info("Demo", base_body.base_info("Demo"))["image_meta"]["front"]
        check("front tile", tile.get("freshness"), {"state": "stale", "reason": base_body.FRONT_MADE_FROM_TEXT})
        meta["front_reference"] = {"method": "reference", "image": "Demo_1.png", "sha256": "0" * 64,
                                   "prompt": base_body._edit_fingerprint("Demo", get_character_profile("Demo"))}
        front_json.write_text(json.dumps(meta))
        check("another picture", base_body.front_reference_state("Demo")["reason"], base_body.FRONT_OTHER_REFERENCE)
        check("no render in [4]", len(CALLS), 0)

        print("[5] the outfit reference")
        check("outfit_key by hand", outfit_references.outfit_key({"top": "b", "legs": "a"}, ["b", "zz"]),
              "or" + hashlib.sha256(b'{"open":["b"],"pieces":["a","b"]}').hexdigest()[:10])
        key = "or" + hashlib.sha256(b'{"open":[],"pieces":[]}').hexdigest()[:10]
        osig = "smokeosig"
        refs.mkdir(parents=True, exist_ok=True)
        stub = {"text": "a red dress", "tex": "texabc"}

        def fig(*_a, profile=None, **_kw):
            return figure.Figure(signature=osig, bsig=bsig, shape=bsig, texture=stub["tex"], in_body=(),
                                 painted=("dress",), own=())
        figure.delivered_figure = fig
        figure.delivered_figure_cached = fig
        base_body.figure_texts = lambda c, f, items, profile=None: {v: stub["text"] for v in base_body.dressed_views()}
        model_refs.current_outfit_state = lambda c: ({}, [], osig)
        started = []
        figure_build.start = lambda *a, **kw: started.append(("start", a)) or {"status": "started"}
        figure_build.request = lambda *a, **kw: started.append(("request", a)) or True

        texture_before = figure.texture_key("Demo", figure.worn_sets("Demo", pieces={}), shape=bsig, bsig=bsig,
                                            variant="", items=[])
        for n in (2, 3):
            png_rgba(get_character_images_dir("Demo") / f"Demo_{n}.png", pixel=(10 * n, 20, 30, 255))
        other = get_character_profile("Demo")
        other["outfit_references"] = {"orffffffffff": {"image": "Demo_3.png", "sha256": "1" * 64}}
        check("another outfit's reference changes no key",
              figure.texture_key("Demo", figure.worn_sets("Demo", pieces={}), shape=bsig, bsig=bsig, variant="",
                                 items=[], profile=other), texture_before)
        CALLS.clear()
        got = outfit_references.set_reference("Demo", "Demo_2.png")
        check("set: key, sha", (got["key"], got["record"]["sha256"]),
              (key, sha(get_character_images_dir("Demo") / "Demo_2.png")))
        check("set: saves only", (len(CALLS), started), (0, []))
        check("nothing painted: the reference changes no key",
              figure.texture_key("Demo", figure.worn_sets("Demo", pieces={}), shape=bsig, bsig=bsig, variant="",
                                 items=[]), texture_before)
        painted_inputs = lambda *a, **kw: {"version": 1, "dress_text": {"front": "a red dress"}}  # noqa: E731
        with patch.object(base_body, "texture_inputs", side_effect=painted_inputs):
            with_ref = figure.texture_key("Demo", figure.worn_sets("Demo", pieces={}), shape=bsig, bsig=bsig,
                                          variant="", items=[])
            bare_profile = {k: v for k, v in get_character_profile("Demo").items() if k != "outfit_references"}
            without = figure.texture_key("Demo", figure.worn_sets("Demo", pieces={}), shape=bsig, bsig=bsig,
                                         variant="", items=[], profile=bare_profile)
        check("painted: this outfit's reference changes the key", (with_ref != without, without ==
              base_body.texture_signature({"version": 1, "dress_text": {"front": "a red dress"}})), (True, True))
        from app.core import view_composite as _vc
        composed = []

        def fake_compose(base_view, draft_file, target, *, rule="outfit", base_alpha=False, **_kw):
            composed.append((Path(base_view).name, base_alpha))
            Path(target).write_bytes(Path(draft_file).read_bytes())
            return {"version": _vc.VERSION, "rule": rule, "ok": True, "iou": 1.0, "alpha": "base",
                    "coverage": {"score": 0.9, "region": 0.2}, "mask_share": 0.2, "reasons": []}
        _real_compose, _vc.compose = _vc.compose, fake_compose
        base_body.generate_dressed_images("Demo", pieces={}, items=[], signature=osig, force=True, view="front")
        one = CALLS[0] if len(CALLS) == 1 else {}
        check("composited onto the base front, alpha the base's", composed, [(f"tpose_{bsig}.png", True)])
        extras = [Path(p) for p in one.get("extra_reference_images") or []]
        check("one render", len(CALLS), 1)
        check("outfit front: an edit of the base front, its picture second",
              (one.get("occasion"), one.get("image_use_case"), one.get("ref_name"),
               str(one.get("ref_dir") or "").startswith(".viewref_"), bool(one.get("require_reference")),
               [p.name for p in extras], all(p.parent.name.startswith(".editref_") for p in extras),
               one.get("extra_reference_prompt")),
              ("outfit_front", "outfit_edit", f"tpose_{bsig}.png", True, True, ["Demo_2.png"], True,
               base_body.EDIT_SECOND_PICTURE.format(seen="")))
        extra = one.get("sidecar_extra") or {}
        check("outfit front sidecar",
              (extra.get("outfit_reference_sha256"), extra.get("base_signature"), extra.get("base_image_sha256")),
              (sha(get_character_images_dir("Demo") / "Demo_2.png"), bsig, sha(refs / f"tpose_{bsig}.png")))
        path = refs / f"tpose_{osig}.png"
        check("dressed front current", base_body.dressed_image("Demo", "front", osig, bsig, fig=fig()), path)
        outfit_references.clear_reference("Demo", key)
        check("cleared: due", base_body.dressed_image("Demo", "front", osig, bsig, fig=fig()), None)
        outfit_references.set_reference("Demo", "Demo_3.png")
        check("another picture: due", base_body.dressed_image("Demo", "front", osig, bsig, fig=fig()), None)
        check("reference changes rendered nothing", (len(CALLS), started), (1, []))
        outfit_references.clear_reference("Demo", key)
        CALLS.clear()
        # Ruling A104 would generate the reference first (smoke_outfit_reference_auto.py); the old edit is pinned here.
        from app.core import full_body_reference as _fbr
        _auto_due, _fbr.auto_due = _fbr.auto_due, (lambda *_a, **_k: False)
        try:
            base_body.generate_dressed_images("Demo", pieces={}, items=[], signature=osig, force=True, view="front")
        finally:
            _fbr.auto_due = _auto_due
        check("without a reference: the same edit, no second picture",
              [(c.get("occasion"), c.get("image_use_case"), list(c.get("extra_reference_images") or []))
               for c in CALLS], [("outfit_front", base_body.DRESS_USE_CASE, [])])
        _vc.compose = _real_compose

        built = figure.Figure(signature=osig, bsig=bsig, shape=bsig, texture="texplain", in_body=(), painted=(),
                              own=())
        now = {"tex": "texplain"}

        def fig_by_profile(*_a, profile=None, **_kw):
            ref = bool((profile or {}).get("outfit_references"))
            return figure.Figure(signature=osig, bsig=bsig, shape=bsig, texture=now["tex"] + ("ref" if ref else ""),
                                 in_body=(), painted=(), own=())
        figure.delivered_figure_cached = fig_by_profile
        meta_model = {"figure": built.as_dict(), "pieces": {}, "items": [], "base_signature": bsig}
        with_ref = {**get_character_profile("Demo"), "outfit_references": {key: {"image": "Demo_2.png",
                                                                                 "sha256": "2" * 64}}}
        check("reference-only change", outfit_references.reference_only_change("Demo", meta_model, profile=with_ref),
              True)
        now["tex"] = "texother"
        check("another change too", outfit_references.reference_only_change("Demo", meta_model, profile=with_ref),
              False)

    print(f"[6] fails on the old code ({OLD})")

    def old(path):
        return subprocess.run(["git", "-C", str(ROOT), "show", f"{OLD}:{path}"], capture_output=True, text=True,
                              check=True).stdout
    old_body = old("app/core/base_body.py")
    check("old front: no reference image", 'path = draw("front", stem, None)' in old_body, True)
    check("old config: no base_front_edit", '"base_front_edit"' in old("app/core/config.py"), False)
    check("old check_renderable refused no profile image",
          'raise MissingInput("No profile picture. Set a profile picture, then render the base body")' in old_body,
          True)

    print("[7] outbound attempts")
    check("outbound", OUTBOUND, [])

    if FAILS:
        print(f"\nFAILED: {len(FAILS)} — {FAILS}")
        return 1
    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
