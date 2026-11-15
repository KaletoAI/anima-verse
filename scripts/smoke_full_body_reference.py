#!/usr/bin/env python3
"""Ruling A87: the A-pose front is an edit of a dedicated FULL-BODY REFERENCE — generated from the profile image
(or picked / uploaded), one for the plain body and one per outfit — and nothing turns due because this exists.

Usage:
    ./.venv/bin/python scripts/smoke_full_body_reference.py

Runs against a THROWAWAY storage + instance directory with a copy of the repo's ``human`` package — no real world,
no hub, no server process. Every render goes to a recorder (``expression_regen.render_character_image``) that writes
an 8x8 PNG; the routing checks call ``ImageService.generate_on_backend`` with stand-in backends whose
``run_on_backend`` raises before any request. ``socket.socket.connect`` and ``requests.Session.request`` are
replaced by counters that refuse: the run must end with 0 outbound attempts.

Fixture: ``Demo`` (human-roleplay; appearance text "{gender}, {age} years old, freckles, long dark hair"; skin
olive, eyes green, build athletic, 168 cm; no hairstyle — a bald plain body) with profile image Demo_1.png;
``DemoBare`` the same without a profile image. The human package renders the slots as "green eyes", "olive skin",
"average height, athletic build" (the build slot carries the height — ``base_body.base_appearance``'s rule).

Expected, derived by hand from the brief and the user's validated chain (hub job 5086b496: profile image → full-body
reference, prompt since Ruling A95 "Full body shot from head to feet inside the frame, <attributes>, neutral studio lighting, …", negative = nothing worn;
hub job c265fd78: that output → the A-pose front, A74b's edit prompt):

[1] Routing. OCCASIONS base_reference / outfit_reference: needs_ref_slot True, requires_chain True, both in
    MESH_INPUT_OCCASIONS (so no negative fold, the tpose LoRAs). run_routed('base_reference', …):
      chain [no-ref (0 slots), with-ref] -> "with-ref"; the no-ref backend is a configuration skip (never tried);
      chain [no-ref] alone -> NoRouteError, nothing tried;
      empty chain -> NoRouteError (requires a chain — never the cheapest backend).
    The service gate (require_reference) refuses a 1-slot backend the reference does not condition
    (BackendNotApplicableError "…edit of one") — A74b's gate, the payload of [2] carries the flag.
    Config migration: routing {base_front: [A], outfit_front: [B]} -> base_reference [A], outfit_reference [B];
    a stored base_reference [C] stays [C].
[2] Generate the plain body's reference (generate_base(Demo)): ONE render — occasion "base_reference", use case
    "base_reference", reference a frozen copy named Demo_1.png in model_refs/.editref_*, require_reference True,
    postprocess False, no equipped pieces;
      style_character = "female, 30 years old, freckles, long dark hair, green eyes, olive skin, average height,
        athletic build"  (the appearance text resolved, hair included, then the slots — the attribute block
        alone, no body-state words: those belong to the A-pose edit, Ruling A87b);
      composed prompt (Ruling A95, the user's validated shape of 2026-11-15) = "Full body shot from head to feet
        inside the frame, " + that + ", neutral studio lighting, plain clean background, photorealistic, high
        detail" (no edit prefix, no pose words);
      extra_negative = "clothing, underwear, jewellery" + ", region detail" (the fixture region of [10] applies to
        Demo, uncovered; its reference text needs {size} and drops, its negative stays).
    Record: origin "generated", the picture in the gallery as Demo_<stamp>_fullbody.png with the recorder's bytes,
    made_from {image "Demo_1.png", sha256 of Demo_1.png, kind "profile"}, prompt = the composed prompt.
[3] The front's reference chain:
      with the full-body reference: front_reference(Demo) = {method "reference", image <its name>, sha256 <its
        bytes>, prompt _edit_fingerprint, source "full_body"}; generate_base_images(Demo) edits a frozen copy of
        THAT picture with A74b's edit block (edit_character) — the step-2 prompt unchanged;
      cleared: {method "reference", image "Demo_1.png", sha256, prompt} — exactly A74b's four keys;
      DemoBare (no profile image, no reference): {"method": "text"}.
[4] Freshness (stored front made from the profile image, A74b's record):
      set the full-body reference -> FRONT_PROFILE_NOT_FULL_BODY; base_refresh_plan(missing=True) reason
        "reference"; base_refresh_plan() never "reference" (no automatic spend);
      a front made from it -> current; another full-body picture -> FRONT_OTHER_FULL_BODY;
      cleared again -> FRONT_NO_FULL_BODY_NOW; the tile's info line: NO_FULL_BODY_NOTE.
[5] Bit-identity: a front rendered with A74b's record and no full-body reference set is current, and
    front_reference(Demo) has no "source" key — nothing turns due on deploy. On the old code (a620816cd, the commit
    before A87) front_reference built the same four keys: the line
    'return {"method": FRONT_FROM_REFERENCE, "image": image.name, "sha256": sha,' is in it.
[6] Generate an outfit's reference: with the plain body's reference set its source is that picture (kind
    "full_body"), cleared it is the profile image; occasion / use case "outfit_reference", require_reference,
    style_character = outfit_block (the figure as dressed now: "female, 30 years old, freckles, long dark hair,
    green eyes, olive skin, average height, athletic build" — nothing worn in the fixture, so no "wearing");
    recorded under the outfit key of the worn combination with origin "generated".
[7] Uploads (the routes on a test app, the cap patched to 1000 bytes): 2000 declared bytes -> 413 for both upload
    routes; bytes that are no image -> 415; an 8x8 PNG -> 200, record origin "upload".
[8] Run all and the Build never generate one: no module but full_body_reference.py and routes/figure.py names
    generate_base / generate_outfit / start_base / start_outfit; build_note(Demo) = {base, outfit} booleans.
[11] Ruling A103 — per-backend reference texts. The fixture region's reference_prompt adds
    backends [{match "*fake*", values {alpha: "a textured {size} area"}}], its reference_negative is
    {default "region detail", backends [{match "*FAKE*", default "blurred region"}]} (globs case-insensitive,
    over the backend's name AND model). For DemoPart (alpha, large; surface wide):
      under the override: base_block = Demo's block + ", exposed wide surface, a textured large area"; type beta
        -> "a flat large surface" (a value the override does not name falls back to the base's); no type ->
        nothing (neither declares a default); negatives: plain body BASE_NEG + ", blurred region", outfit
        "blurred region"; without a choice everything as in [10];
      generate_base's payload backend_variants: keys [region/prompt ["*fake*"], region/negative ["*FAKE*"]],
        4 variants in product order (-1,-1), (-1,0), (0,-1), (0,0); variant (-1,-1) = the base block/negative,
        (0,0) = the override block / BASE_NEG + ", blurred region";
      service.apply_backend_variant at the backend point: backend "Fake-1" (model "m1") -> choice [0, 0], the
        override block + negative; "Other" (model "m2") -> [-1, -1], the base; "Plain" with model "fake-xl" ->
        [0, 0] (the model id matches); the caller's payload is never changed (a re-run picks again);
      generate_on_backend on "Other", then "Fake-1", then "Other" with the same payload: the use-case style
        receives base / override / base block and the effective negative ends with "region detail" / "blurred
        region" / "region detail" (the use case's negative before it).
    Loader: a backends entry without match, a non-list backends, values on a negative, an entry with neither
      values nor default -> ValueError.
[9] Outbound attempts: 0.
[10] Rulings A93 / A93b — the full-body reference is an appearance picture, NOT a mesh input, and it names nothing
    of a slot that declares a mesh part (a clean mesh cannot be made from it). Fixture package ``fixture_region``
    (written into the throwaway plugins dir, requires human): slot ``region`` covered by bottom / underwear_bottom,
    attributes type / size / part, exposed text "exposed {size} {type} region", a mesh part switched by ``part``
    with NO tpose_prompt and lora_patterns ["*Region*"]; slot ``surface`` (no mesh part) covered by top /
    underwear_top, exposed text "exposed {size} surface". ``DemoPart`` = Demo's profile + region {type alpha, size
    large, part on} + surface {size wide}, nothing worn, profile image, outfit_imagegen.tpose_loras [PoseFixture,
    RegionFixture]; ``DemoPartOff`` the same with part off.
      occasions.mesh_input_text: base_reference / outfit_reference False; tpose / base_front / base_view True;
      base_block(DemoPart) = base_block(DemoPartOff) = Demo's block + ", exposed wide surface, a smooth plain
        large area" (the general fragments, then the exposed ones; the region slot's own texts stay out, switch
        on or off — A93b; its reference_prompt for type alpha "a smooth plain {size} area" comes last — A95; for
        type beta "a flat large surface", with no type and no default nothing — A101); reference
        negatives: plain body "clothing, underwear, jewellery, region detail", outfit "region detail"; with the
        region covered neither its reference text nor its negative;
      outfit_block of both = the same text (nothing worn: no "wearing");
      A93's ordinary description of DemoPartOff (person_description(mesh_input=False)) = Demo's block +
        ", exposed large alpha region, exposed wide surface" (manifest slot order) — what A93b takes out;
      the REAL render_character_image behind generate_base (stub service, generate_from_input records the payload
        and delivers nothing -> RuntimeError "The render delivered no picture"): occasion base_reference,
        require_reference True, style_character = the block above, loras [PoseFixture] for BOTH (RegionFixture
        dropped whether the switch is on or off — A93b);
      the same renderer on occasion base_front (a mesh input, A74a unchanged): DemoPart [PoseFixture] (switch on:
        dropped), DemoPartOff [PoseFixture, RegionFixture] (switch off: A74a drops nothing).
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

OLD = "a620816cd"
#: The commit before Ruling A93 (its full-body reference took the mesh-input description).
BEFORE_A93 = "c7a1b1bfe"
FIXTURE_REGION = """name: fixture_region
version: "1.0.0"
requires: [human]
apply_to: ["human-default", "human-roleplay"]
body_slots:
  - id: region
    covered_by: [bottom, underwear_bottom]
    attributes:
      type: {type: select, options: [alpha, beta]}
      size: {type: select, options: [small, large]}
      part: {type: select, options: ["off", "on"]}
    prompt:
      exposed: "exposed {size} {type} region"
    rigs:
    - {id: region_inset, op: inset_part, chains: []}
    mesh_part:
      switch: part
      lora_patterns: ["*Region*"]
      reference_prompt:
        by: type
        values: {alpha: "a smooth plain {size} area", beta: "a flat {size} surface"}
        backends:
          - match: "*fake*"
            values: {alpha: "a textured {size} area"}
      reference_negative:
        default: "region detail"
        backends:
          - {match: "*FAKE*", default: "blurred region"}
      rigs:
        region_inset: {params: {}}
  - id: surface
    covered_by: [top, underwear_top]
    attributes:
      size: {type: select, options: [narrow, wide]}
    prompt:
      exposed: "exposed {size} surface"
"""
FRAMING = "Full body shot from head to feet inside the frame"
FINISH = "neutral studio lighting, plain clean background, photorealistic, high detail"
#: The plain body's extra negative without a mesh-part slot (Ruling A95: nothing worn).
BASE_NEG = "clothing, underwear, jewellery"


def framed(block):
    """The composed reference prompt (Ruling A95): framing first, then the block, then light and finish."""
    return f"{FRAMING}, {block}, {FINISH}"
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


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


CALLS = []
RENDERED = png_bytes(200)


def recorder(character_name, *, output_stem, **kw):
    ref = kw.get("reference_image")
    CALLS.append({"name": character_name, "stem": Path(output_stem), "ref": ref,
                  "ref_name": Path(ref).name if ref else None,
                  "ref_dir": Path(ref).parent.name if ref else None, **kw})
    out = Path(output_stem).with_suffix(".png")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(RENDERED)
    extra = kw.get("sidecar_extra") or {}
    out.with_suffix(".json").write_text(json.dumps({"created_at": "2026-11-15T10:00:00+00:00", **extra}))
    return out


def composed(use_case, call):
    from app.core import config
    style = config.get_use_case_prompts(use_case, "natural", clothed=False,
                                        character=call["style_character"])["prompt_style"]
    return config.join_style_prompt(style, call["bare_prompt"], call["style_character"])


def routing_checks(profile_file: Path):
    print("[1] routing")
    from app.imagegen import occasions, routing, service as svc
    from app.imagegen.base import BackendNotApplicableError, ImageBackend
    from app.imagegen.selection import BackendPool
    from app.core.prompt_builder import PromptBuilder
    for occ in ("base_reference", "outfit_reference"):
        o = occasions.OCCASIONS[occ]
        check(f"{occ}: ref slot, chain required, mesh input",
              (o["needs_ref_slot"], o.get("requires_chain"), occ in occasions.MESH_INPUT_OCCASIONS,
               occasions.folds_negative(occ)), (True, True, True, False))

    class Backend(ImageBackend):
        def __init__(self, name, slots):
            super().__init__(name, "http://unused", 0, "fake", "FBR_SMOKE_")
            self.ref_slot_count = slots
            self._available = True

        def check_availability(self):
            return True

        def _generate(self, *args):
            raise AssertionError("No external generation")

    class Reached(Exception):
        pass

    with patch.object(svc.ImageService, "_load_instances", return_value=[]):
        service = svc.ImageService()
    payload = {"prompt": "", "style_character": "x", "agent_name": "Demo", "auto_enhance": False,
               "skip_gallery": True, "profile_only": True, "image_use_case": "base_reference",
               "appearances": [{"name": "Demo", "appearance": ""}],
               "reference_image_override": str(profile_file), "require_reference": True}
    parsed = service._parse_input(json.dumps(payload))
    bad, good, unslotted = Backend("no-ref", 0), Backend("with-ref", 1), Backend("one-slot", 1)
    pool = BackendPool([bad, good, unslotted])
    attempts = []

    def render(b):
        attempts.append(b.name)
        slots = ({"reference_images": {"input_reference_image_1": str(profile_file)}, "has_reference_slots": True}
                 if b is good else {"reference_images": {}, "has_reference_slots": False})
        with (patch.object(service, "_get_instance_config", return_value={}),
              patch.object(service, "run_on_backend", side_effect=Reached()),
              patch.object(PromptBuilder, "resolve_reference_slots", return_value=slots)):
            try:
                service.generate_on_backend(b, dict(parsed), explicit=False)
            except Reached:
                return b.name

    def run(chain):
        attempts.clear()
        with (patch.object(routing, "_character_spec", return_value=""),
              patch.object(routing, "_rules", return_value=chain)):
            try:
                result, _route = routing.run_routed("base_reference", render, character="Demo", has_ref=True,
                                                    pool=pool)
                return ("returned", result, list(attempts))
            except routing.NoRouteError:
                return ("no route", None, list(attempts))
            except BackendNotApplicableError:
                return ("not applicable", None, list(attempts))
    check("chain [no-ref, with-ref]", run(["no-ref", "with-ref"]), ("returned", "with-ref", ["with-ref"]))
    check("chain [no-ref] alone", run(["no-ref"]), ("no route", None, []))
    check("empty chain: no route", run([]), ("no route", None, []))
    got = run(["one-slot"])
    check("a slot the reference does not condition: never a text render", (got[0] != "returned", got[2]),
          (True, ["one-slot"]))

    from app.core import config as cfg
    seeded = {"image_generation": {"routing": {"base_front": ["A"], "outfit_front": ["B"]}}}
    cfg._migrate_reference_routing(seeded)
    check("seeded from the fronts", (seeded["image_generation"]["routing"]["base_reference"],
                                     seeded["image_generation"]["routing"]["outfit_reference"]), (["A"], ["B"]))
    owned = {"image_generation": {"routing": {"base_front": ["A"], "base_reference": ["C"]}}}
    cfg._migrate_reference_routing(owned)
    check("a stored chain owns its value", (owned["image_generation"]["routing"]["base_reference"],
                                            "outfit_reference" in owned["image_generation"]["routing"]), (["C"], False))


def upload_checks(full_body_reference):
    print("[7] uploads")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.core import upload_limits
    from app.core.auth_dependency import require_admin
    from app.routes import figure as figure_routes
    app = FastAPI()
    app.include_router(figure_routes.router)
    app.dependency_overrides[require_admin] = lambda: {"role": "admin"}
    client = TestClient(app)
    with patch.object(upload_limits, "max_upload_bytes", return_value=1000):
        for path in ("/characters/Demo/base-body/full-body-reference/upload",
                     "/characters/Demo/figure/outfit-reference/upload"):
            big = client.post(path, files={"file": ("big.png", b"\x89PNG" + b"0" * 2000, "image/png")})
            check(f"{path.split('/')[3]}: over the cap", big.status_code, 413)
            text = client.post(path, files={"file": ("note.png", b"just text, no picture", "image/png")})
            check(f"{path.split('/')[3]}: no image", text.status_code, 415)
        ok = client.post("/characters/Demo/base-body/full-body-reference/upload",
                         files={"file": ("mine.png", png_bytes(90), "image/png")})
        check("plain body upload stored", (ok.status_code, (ok.json().get("record") or {}).get("origin")),
              (200, "upload"))
        check("record names the gallery file",
              full_body_reference.base_record("Demo")["sha256"], hashlib.sha256(png_bytes(90)).hexdigest())


def mesh_part_checks(human, *, want_block):
    print("[10] a mesh-part slot: the full-body reference names nothing of it and drops its LoRAs (A93 / A93b)")
    from app.core import expression_regen, full_body_reference as fbr
    from app.core.prompt_builder import person_description
    from app.imagegen import occasions
    from app.models.character import get_character_images_dir, get_character_profile, save_character_profile
    check("mesh-input text per occasion",
          {o: occasions.mesh_input_text(o) for o in ("base_reference", "outfit_reference", "tpose", "base_front",
                                                     "base_view")},
          {"base_reference": False, "outfit_reference": False, "tpose": True, "base_front": True, "base_view": True})
    # A95: the region's own texts stay out (A93b), its reference_prompt says what it shows instead (uncovered).
    want = want_block + ", exposed wide surface, a smooth plain large area"
    payloads = []
    payloads_by_name = {}

    class Service:
        enabled = True

        def generate_from_input(self, raw, **kw):
            payloads.append(json.loads(raw))
            return ""     # no picture: the renderer returns None

    for name, switch, front_loras in (("DemoPart", "on", ["PoseFixture"]),
                                      ("DemoPartOff", "off", ["PoseFixture", "RegionFixture"])):
        profile = json.loads(json.dumps(human))
        profile["body_slots"]["region"] = {"type": "alpha", "size": "large", "part": switch}
        profile["body_slots"]["surface"] = {"size": "wide"}
        profile["outfit_imagegen"] = {"tpose_loras": [{"name": "PoseFixture", "strength": 1.0},
                                                      {"name": "RegionFixture", "strength": 0.8}]}
        check(f"create {name}", save_character_profile(name, profile, create_new=True), True)
        png(get_character_images_dir(name) / f"{name}_1.png")
        stored = get_character_profile(name)
        stored["profile_image"] = f"{name}_1.png"
        check(f"profile image {name}", save_character_profile(name, stored), True)
        stored = get_character_profile(name)
        a93 = person_description(name, apply_state_modifiers=False, mesh_input=False,
                                 body_profile=fbr._undressed(stored), neutral_state=True)
        print(f"  {name} A93  (ordinary description): {framed(a93)!r}")
        print(f"  {name} A93b (the reference):        {fbr.compose('base_reference', fbr.base_block(name))!r}")
        check(f"{name}: plain body block names nothing of the region, the other exposed text stays",
              fbr.base_block(name), want)
        check(f"{name}: outfit block (nothing worn)", fbr.outfit_block(name), want)
        check(f"{name}: plain body negative adds the region's reference negative",
              fbr.reference_negative(name, fbr._undressed(stored), base=True), BASE_NEG + ", region detail")
        check(f"{name}: outfit negative (uncovered): the region's only",
              fbr.reference_negative(name, stored, base=False), "region detail")
        from app.core import body_slots
        beta = json.loads(json.dumps(stored))
        beta["body_slots"]["region"]["type"] = "beta"
        check(f"{name}: the reference text follows the type (A101)",
              body_slots.prompt_fragments(name, profile=beta, appearance_reference=True, neutral_state=True)["exposed"],
              ["exposed wide surface", "a flat large surface"])
        real_exposed = body_slots.is_slot_exposed
        with patch.object(body_slots, "is_slot_exposed",
                          lambda spec, prof: spec.id != "region" and real_exposed(spec, prof)):
            check(f"{name}: covered region: no reference text, no reference negative",
                  (body_slots.prompt_fragments(name, profile=stored, appearance_reference=True,
                                               neutral_state=True)["exposed"],
                   body_slots.appearance_reference_negative(name, profile=stored)), (["exposed wide surface"], ""))
        if switch == "off":
            check(f"{name}: A93's ordinary description still named it", a93,
                  want_block + ", exposed large alpha region, exposed wide surface")   # manifest slot order
        payloads.clear()
        with patch("app.imagegen.service.get_image_service", return_value=Service()):
            check(f"{name}: real renderer behind generate_base", _raises(lambda: fbr.generate_base(name)),
                  "RuntimeError")
            sent = payloads[0] if len(payloads) == 1 else {}
            payloads_by_name[name] = sent
            check(f"{name}: full-body reference payload",
                  (sent.get("occasion"), sent.get("require_reference"), sent.get("style_character"),
                   [lora.get("name") for lora in sent.get("loras") or []]),
                  ("base_reference", True, want, ["PoseFixture"]))
            payloads.clear()
            expression_regen.render_character_image(
                name, output_stem=Path(tempfile.mkdtemp()) / "front", equipped_pieces={}, equipped_items=[],
                pose_prompt="", expression_prompt="", bare_prompt="", image_use_case="base_front",
                style_character="x", occasion="base_front", apply_state_modifiers=False,
                mesh_input_profile=fbr._undressed(stored), character_loras=True, postprocess=False)
            sent = payloads[0] if len(payloads) == 1 else {}
            check(f"{name}: a mesh input (base_front), A74a unchanged",
                  (sent.get("occasion"), [lora.get("name") for lora in sent.get("loras") or []]),
                  ("base_front", front_loras))
    backend_variant_checks(want_block, payloads_by_name)
    old_src = subprocess.run(["git", "-C", str(ROOT), "show", f"{BEFORE_A93}:app/core/full_body_reference.py"],
                             capture_output=True, text=True, check=True).stdout
    check("the code before A93 took the mesh-input description",
          "person_description(character_name, apply_state_modifiers=False, mesh_input=True," in old_src, True)



def backend_variant_checks(want_block, payloads_by_name):
    print("[11] per-backend reference texts (A103)")
    from app.core import body_slots, config, full_body_reference as fbr
    from app.imagegen import service as svc
    from app.imagegen.base import ImageBackend
    from app.models.character import get_character_profile
    from app.plugins.registry import _parse_reference_text
    name = "DemoPart"
    stored = get_character_profile(name)
    base = want_block + ", exposed wide surface, a smooth plain large area"
    fake = want_block + ", exposed wide surface, a textured large area"
    choice = {("region", "prompt"): 0, ("region", "negative"): 0}
    with body_slots.reference_backend_choice(choice):
        check("override block", fbr.base_block(name), fake)
        beta = json.loads(json.dumps(stored))
        beta["body_slots"]["region"]["type"] = "beta"
        check("override: a value it does not name falls back to the base's",
              body_slots.prompt_fragments(name, profile=beta, appearance_reference=True, neutral_state=True)["exposed"],
              ["exposed wide surface", "a flat large surface"])
        beta["body_slots"]["region"]["type"] = ""
        check("override: no type, no default anywhere -> nothing",
              body_slots.prompt_fragments(name, profile=beta, appearance_reference=True, neutral_state=True)["exposed"],
              ["exposed wide surface"])
        check("override negatives", (fbr.reference_negative(name, fbr._undressed(stored), base=True),
                                     fbr.reference_negative(name, stored, base=False)),
              (BASE_NEG + ", blurred region", "blurred region"))
    check("without a choice: the base", (fbr.base_block(name), fbr.reference_negative(name, stored, base=False)),
          (base, "region detail"))
    sent = payloads_by_name.get(name) or {}
    variants = sent.get("backend_variants") or {}
    check("payload keys", variants.get("keys"),
          [{"slot": "region", "field": "prompt", "match": ["*fake*"]},
           {"slot": "region", "field": "negative", "match": ["*FAKE*"]}])
    check("payload variants",
          [(v["choice"], v["style_character"], v["negative_prompt_extra"]) for v in variants.get("variants") or []],
          [([-1, -1], base, BASE_NEG + ", region detail"), ([-1, 0], base, BASE_NEG + ", blurred region"),
           ([0, -1], fake, BASE_NEG + ", region detail"), ([0, 0], fake, BASE_NEG + ", blurred region")])

    class Backend(ImageBackend):
        def __init__(self, bname, model):
            super().__init__(bname, "http://unused", 0, "stub", "FBR_SMOKE_")
            self.model = model
            self.ref_slot_count = 1
            self._available = True

        def check_availability(self):
            return True

        def _generate(self, *args):
            raise AssertionError("No external generation")
    fake_b, other_b, plain_b = Backend("Fake-1", "m1"), Backend("Other", "m2"), Backend("Plain", "fake-xl")
    frozen = json.dumps(sent, sort_keys=True)
    for b, want in ((fake_b, (fake, BASE_NEG + ", blurred region")), (other_b, (base, BASE_NEG + ", region detail")),
                    (plain_b, (fake, BASE_NEG + ", blurred region"))):
        got = svc.apply_backend_variant(sent, b)
        check(f"pick for {b.name}/{b.model}", (svc.backend_choice(variants["keys"], b),
                                              got.get("style_character"), got.get("negative_prompt_extra")),
              ([0, 0] if b is not other_b else [-1, -1], *want))
    check("the caller's payload is unchanged", json.dumps(sent, sort_keys=True), frozen)

    class Reached(Exception):
        pass
    with patch.object(svc.ImageService, "_load_instances", return_value=[]):
        service = svc.ImageService()
    parsed = service._parse_input(json.dumps({**sent, "reference_image_override": "", "require_reference": False}))
    seen = []
    real_ucp, real_neg = config.get_use_case_prompts, svc.resolve_negative_prompt

    def spy_ucp(*a, **kw):
        seen.append(("block", kw.get("character")))
        return real_ucp(*a, **kw)

    def spy_neg(data, uc_negative):
        out = real_neg(data, uc_negative)
        seen.append(("negative", out.rsplit(", ", 1)[-1]))
        return out
    with (patch.object(service, "_get_instance_config", return_value={}),
          patch.object(service, "run_on_backend", side_effect=Reached()),
          patch.object(config, "get_use_case_prompts", spy_ucp),
          patch.object(svc, "resolve_negative_prompt", spy_neg)):
        for b in (other_b, fake_b, other_b):
            try:
                service.generate_on_backend(b, parsed, explicit=False)
            except Reached:
                pass
            except Exception as e:   # noqa: BLE001 — reported by the check below
                seen.append(("error", type(e).__name__ + ": " + str(e)[:120]))
    check("generate_on_backend picks per backend",
          [entry for entry in seen if entry[0] != "block" or entry[1] is not None],
          [("block", base), ("negative", "region detail"), ("block", fake), ("negative", "blurred region"),
           ("block", base), ("negative", "region detail")])
    attrs = {"type": {"type": "select", "options": ["a"]}}
    for label, raw, field in (
            ("entry without match", {"by": "type", "values": {"a": "x"}, "backends": [{"values": {"a": "y"}}]},
             "reference_prompt"),
            ("backends not a list", {"default": "x", "backends": {"match": "*"}}, "reference_negative"),
            ("values on a negative", {"default": "x", "backends": [{"match": "*", "values": {"a": "y"}}]},
             "reference_negative"),
            ("entry with no text", {"by": "type", "values": {"a": "x"}, "backends": [{"match": "*"}]},
             "reference_prompt")):
        check(f"loader refuses: {label}",
              _raises(lambda: _parse_reference_text(raw, attrs, field, allow_by=field == "reference_prompt")),
              "ValueError")

def main() -> int:
    block_network()
    with tempfile.TemporaryDirectory(prefix="full-body-ref-") as tmp:
        root = Path(tmp)
        os.environ["STORAGE_DIR"] = str(root / "world")
        os.environ["INSTANCE_DIR"] = str(root / "instance")
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "instance")
        paths.get_config_path().write_text(json.dumps({"packages": {"enabled": "human,fixture_region"},
                                                       "base_body": {"skin_detail_step": False}}))
        from app.core import config
        config.load(paths.get_config_path(), instance_path=root / "instance/config.json")
        from app.core import db
        db.init_schema()
        plugins = root / "plugins"
        shutil.copytree(ROOT / "plugins" / "human", plugins / "human")
        (plugins / "fixture_region").mkdir()
        (plugins / "fixture_region" / "plugin.yaml").write_text(FIXTURE_REGION)
        from app.plugins.loader import discover_packages
        discover_packages(plugins, force=True)

        from app.core import base_body, expression_regen, full_body_reference as fbr, outfit_references
        from app.models.character import (get_character_dir, get_character_images_dir, get_character_profile,
                                          save_character_profile)
        human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
                 "character_appearance": "{gender}, {age} years old, freckles, long dark hair",
                 "body_slots": {"skin": {"tone": "olive"}, "eyes": {"color": "green"},
                                "build": {"type": "athletic"}}}
        for name, image in (("Demo", True), ("DemoBare", False)):
            check(f"create {name}", save_character_profile(name, json.loads(json.dumps(human)), create_new=True), True)
            if image:
                png(get_character_images_dir(name) / f"{name}_1.png")
                stored = get_character_profile(name)
                stored["profile_image"] = f"{name}_1.png"
                check(f"profile image {name}", save_character_profile(name, stored), True)
        profile_file = get_character_images_dir("Demo") / "Demo_1.png"
        refs = get_character_dir("Demo") / "model_refs"

        routing_checks(profile_file)

        mesh_part_checks(human, want_block="female, 30 years old, freckles, long dark hair, green eyes, olive skin, "
                                           "average height, athletic build")

        expression_regen.render_character_image = recorder

        print("[2] generate the plain body's full-body reference")
        want_block = "female, 30 years old, freckles, long dark hair, green eyes, olive skin, average height, athletic build"
        check("tile prompt before the click", fbr.base_tile("Demo")["generate"]["prompt"], framed(want_block))
        record = fbr.generate_base("Demo")
        one = CALLS[0] if len(CALLS) == 1 else {}
        check("one render", len(CALLS), 1)
        check("occasion / use case / reference",
              (one.get("occasion"), one.get("image_use_case"), one.get("ref_name"),
               str(one.get("ref_dir") or "").startswith(".editref_"), one.get("ref") == profile_file,
               bool(one.get("require_reference")), one.get("postprocess"), one.get("equipped_pieces")),
              ("base_reference", "base_reference", "Demo_1.png", True, False, True, False, {}))
        check("attribute block", one.get("style_character"), want_block)
        check("composed prompt: framing, block, finish", composed("base_reference", one), framed(want_block))
        # Demo is human-roleplay, so the fixture region applies (uncovered, no attributes: its reference text
        # needs {size} and drops, its negative names no attribute and stays).
        check("negative: nothing worn + the region's (A95)", one.get("extra_negative"), BASE_NEG + ", region detail")
        gallery = get_character_images_dir("Demo") / record["image"]
        check("record", (record["origin"], record["image"].startswith("Demo_") and
                         record["image"].endswith("_fullbody.png"), gallery.read_bytes() == RENDERED,
                         record["made_from"], record["prompt"]),
              ("generated", True, True, {"image": "Demo_1.png", "sha256": sha(profile_file), "kind": "profile"},
               framed(want_block)))
        check("no staging left in model_refs", sorted(p.name for p in refs.iterdir()) if refs.is_dir() else [], [])

        print("[3] the front's reference chain")
        fp = base_body._edit_fingerprint("Demo", get_character_profile("Demo"))
        check("front from the full-body reference", base_body.front_reference("Demo"),
              {"method": "reference", "image": record["image"], "sha256": sha(gallery), "prompt": fp,
               "source": "full_body"})
        CALLS.clear()
        base_body.generate_base_images("Demo")
        front = CALLS[0] if CALLS else {}
        check("the front edits the full-body reference with A74b's block",
              (front.get("occasion"), front.get("image_use_case"), front.get("ref_name"),
               front.get("style_character") == base_body.edit_character("Demo"), bool(front.get("require_reference")),
               (front.get("sidecar_extra") or {}).get("front_reference", {}).get("source")),
              ("base_front", "base_front_edit", record["image"], True, True, "full_body"))
        check("front current", base_body.front_reference_state("Demo")["current"], True)
        fbr.clear_base("Demo")
        # generate_base_images made the first hairstyle from the appearance (ensure_hairstyle): the edit text's
        # fingerprint is read anew.
        fp = base_body._edit_fingerprint("Demo", get_character_profile("Demo"))
        check("cleared: the profile image, A74b's four keys", base_body.front_reference("Demo"),
              {"method": "reference", "image": "Demo_1.png", "sha256": sha(profile_file), "prompt": fp})
        check("no picture at all: text", base_body.front_reference("DemoBare"), {"method": "text"})
        check("generate refused without a profile image",
              _raises(lambda: fbr.start_base("DemoBare")), "MissingInput")

        print("[4] freshness")
        bsig = base_body.base_signature("Demo")
        front_json = refs / f"tpose_{bsig}.json"
        meta = json.loads(front_json.read_text())
        meta["front_reference"] = base_body.front_reference("Demo")    # A74b's record: from the profile image
        front_json.write_text(json.dumps(meta))
        check("profile-made front current without a reference", base_body.front_reference_state("Demo")["current"],
              True)
        fbr.set_base("Demo", record["image"])
        check("set -> due with its reason", base_body.front_reference_state("Demo")["reason"],
              base_body.FRONT_PROFILE_NOT_FULL_BODY)
        check("Run all / Build plan", base_body.base_refresh_plan("Demo", missing=True).get("reason"), "reference")
        check("improvement plan never 'reference'", base_body.base_refresh_plan("Demo").get("reason") != "reference",
              True)
        meta["front_reference"] = base_body.front_reference("Demo")
        front_json.write_text(json.dumps(meta))
        check("made from it -> current", base_body.front_reference_state("Demo")["current"], True)
        png(get_character_images_dir("Demo") / "Demo_9.png", pixel=(9, 9, 9, 255))
        fbr.set_base("Demo", "Demo_9.png")
        check("another full-body picture", base_body.front_reference_state("Demo")["reason"],
              base_body.FRONT_OTHER_FULL_BODY)
        meta["front_reference"] = base_body.front_reference("Demo")
        front_json.write_text(json.dumps(meta))
        fbr.clear_base("Demo")
        check("cleared", base_body.front_reference_state("Demo")["reason"], base_body.FRONT_NO_FULL_BODY_NOW)
        check("tab line without a reference", (base_body.base_info("Demo").get("front_reference") or {}).get("note"),
              base_body.NO_FULL_BODY_NOTE)

        print("[5] bit-identity without a full-body reference")
        meta["front_reference"] = {"method": "reference", "image": "Demo_1.png", "sha256": sha(profile_file),
                                   "prompt": fp}
        front_json.write_text(json.dumps(meta))
        check("A74b record current", base_body.front_reference_state("Demo")["current"], True)
        check("no source key", "source" in base_body.front_reference("Demo"), False)
        old_body = subprocess.run(["git", "-C", str(ROOT), "show", f"{OLD}:app/core/base_body.py"],
                                  capture_output=True, text=True, check=True).stdout
        check("old code built the same four keys",
              'return {"method": FRONT_FROM_REFERENCE, "image": image.name, "sha256": sha,' in old_body, True)

        print("[6] generate an outfit's full-body reference")
        fbr.set_base("Demo", record["image"])
        check("source: the plain body's reference", fbr.outfit_source("Demo"), (gallery, "full_body"))
        CALLS.clear()
        got = fbr.generate_outfit("Demo")
        out = CALLS[0] if len(CALLS) == 1 else {}
        key = outfit_references.outfit_key({}, [])
        want_outfit = "female, 30 years old, freckles, long dark hair, green eyes, olive skin, average height, " \
                      "athletic build"
        check("outfit render",
              (out.get("occasion"), out.get("image_use_case"), out.get("ref_name"), bool(out.get("require_reference")),
               out.get("style_character"), composed("outfit_reference", out)),
              ("outfit_reference", "outfit_reference", record["image"], True, want_outfit,
               framed(want_outfit)))
        check("recorded under the worn outfit", (got["key"], got["record"]["origin"],
                                                 got["record"]["made_from"]["kind"],
                                                 key in outfit_references.references_of("Demo")),
              (key, "generated", "full_body", True))
        fbr.clear_base("Demo")
        check("source without it: the profile image", fbr.outfit_source("Demo"), (profile_file, "profile"))
        tile = fbr.outfit_tile("Demo", outfit_references.info("Demo"))
        check("outfit tile: generate part", (tile["generate"]["jobs"], tile["generate"]["ready"],
                                             tile["generate"]["source"]), (1, True, "profile"))

        upload_checks(fbr)

        print("[8] Run all and the Build never generate one")
        names = ("generate_base(", "generate_outfit(", "start_base(", "start_outfit(")
        users = sorted({str(p.relative_to(ROOT)) for p in (ROOT / "app").rglob("*.py")
                        if any(n in p.read_text(encoding="utf-8") for n in names)})
        check("only the module and its routes", users, ["app/core/full_body_reference.py", "app/routes/figure.py"])
        note = fbr.build_note("Demo")
        check("build note", sorted(note), ["base", "outfit"])

    print("[9] outbound attempts")
    check("outbound", OUTBOUND, [])
    if FAILS:
        print(f"\nFAILED: {len(FAILS)} — {FAILS}")
        return 1
    print("\nAll checks passed.")
    return 0


def _raises(fn):
    try:
        fn()
        return "nothing"
    except Exception as e:  # noqa: BLE001 — the kind is what is checked
        return type(e).__name__


if __name__ == "__main__":
    sys.exit(main())
