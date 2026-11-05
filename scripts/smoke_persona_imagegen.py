#!/usr/bin/env python3
"""Smoke: a worn persona's image settings, look and cache key.

Usage:  ./.venv/bin/python scripts/smoke_persona_imagegen.py

Throwaway storage + instance (``STORAGE_DIR``/``INSTANCE_DIR`` point at temp
dirs, ``paths.init`` runs BEFORE any world-DB module is imported; the
animation clip/rig paths point into the temp dir too). No server, no image
backend (a fake image service records the payload), no real world, no
transformation package: a fake ``identity.active_persona`` provider with
owner "smoke" answers from the dict ``PERSONA``.

THE RULE (restated from the plan, Task 4)
    * effective_outfit_imagegen(C, stored): not transformed -> a copy of
      stored. Transformed -> a copy where workflow / tpose_workflow are the
      persona's when non-empty, loras := persona loras (maybe []),
      tpose_loras := persona tpose_loras (maybe []), model removed; every
      other key unchanged. stored itself is never modified.
    * The routing's character match (position 0) reads the effective dict.
    * outfit_signature_raw(..., look) appends "|look=<look>" when look is
      non-empty; the worn state (current_outfit_state) passes the current
      look token "persona:<persona_id>" ("" = not transformed -> the
      historical string, byte-identical).
    * Image appearance (observer ""): the persona description when
      non-empty, else the real appearance; real_look=True (profile portrait)
      keeps the real one.
    * render_character_image: character model/LoRAs from the effective dict;
      tpose occasion takes tpose_loras unless empty (then loras).
    * An expression job keeps the persona state it was queued in
      (expression_snapshot freezes it, the render runs pinned to it).
    * A manifest records the look; the cache GC re-signs with it.

FIXTURE
    Item "Demo coat" (outfit piece, slot top) -> COAT id. Character Cara,
    template human-default, appearance "REAL-LOOK freckled redhead",
    outfit_imagegen S = {workflow "char-*", profile_workflow "prof-*",
    tpose_workflow "char-tpose-*", tpose_view_workflow "tview-*",
    mesh_workflow "mesh-*", model "real.safetensors",
    loras [{face-lora 0.8}], tpose_loras [{turn-lora 1.0}]}. Worn: A =
    {"top": COAT} (inventory reads patched). No species packages -> empty
    body-slot suffix and mesh variant "".
    P1 = persona_id "p1", alias "Moonveil", description "P-LOOK a figure in
    moonlit silver", imagegen {workflow "pers-*", tpose_workflow "",
    loras [{mask-lora 0.6}], tpose_loras []}.

EXPECTED, derived BY HAND from the rule above
---------------------------------------------
[A] effective: no persona -> == S, a new object, mutating it leaves S.
    P1 -> {workflow "pers-*", profile_workflow "prof-*", tpose_workflow
    "char-tpose-*", tpose_view_workflow "tview-*", mesh_workflow "mesh-*",
    loras [mask-lora 0.6], tpose_loras []} (no model).
    imagegen {} -> workflow "char-*", tpose_workflow "char-tpose-*",
    loras [], tpose_loras [], no model.
    imagegen {tpose_workflow "pers-tpose-*", tpose_loras [p-turn 0.9]} ->
    tpose_workflow "pers-tpose-*", workflow "char-*", loras [],
    tpose_loras [p-turn 0.9]. S afterwards still equals its original.
    identity_view: persona_imagegen(Cara) P1 -> P1's imagegen dict, a copy;
    no persona -> None. look_token P1 -> "persona:p1", no persona -> "",
    persona_id "" -> "persona:Moonveil".
[B] routing character_spec: no persona -> expression "char-*", photo
    "char-*", tpose "char-tpose-*". P1 -> expression "pers-*", photo
    "pers-*", instagram "pers-*", tpose "char-tpose-*" (empty persona
    T-pose backend keeps hers), profile "prof-*", tpose_view "tview-*";
    chain_for("expression")[0] == ("pers-*", "character", 0). Persona with
    tpose_workflow "pers-tpose-*" only -> tpose "pers-tpose-*", expression
    "char-*".
[C] signature: outfit_signature_raw(A, [], "Cara") == "top=<COAT>";
    with look "persona:p1" -> "top=<COAT>|look=persona:p1";
    mesh_signature(A, [], "Cara", "", "persona:p1") ==
    md5("top=<COAT>|look=persona:p1")[:12]. current_outfit_state(Cara)[2]:
    no persona -> md5("top=<COAT>")[:12]; P1 -> md5("top=<COAT>|look=
    persona:p1")[:12]. Pinned to P1, then the provider flips to "not
    transformed": still the P1 value; after the pin -> the real value.
[D] person_description(Cara): no persona -> "REAL-LOOK freckled redhead";
    P1 -> "P-LOOK a figure in moonlit silver"; P1 with description "" ->
    the real look. PromptBuilder(Cara, real_look=True) -> the real look,
    PromptBuilder(Cara) -> P-LOOK.
[E] render_character_image payload (fake service): no persona, expression
    -> loras [face-lora 0.8], model_override "real.safetensors",
    appearance REAL-LOOK; no persona, tpose -> loras [turn-lora 1.0].
    P1, expression -> loras [mask-lora 0.6], no model_override, appearance
    P-LOOK; P1, tpose -> loras [mask-lora 0.6] (tpose_loras [] = the normal
    LoRAs, which are the persona's).
[F] Expression job queued under P1, run after the revert: outfit_raw
    "top=<COAT>|look=persona:p1", frozen profile loras [mask-lora 0.6]; at
    render time look token "persona:p1", effective loras [mask-lora 0.6],
    character_spec("expression") "pers-*", appearance P-LOOK; afterwards
    live spec "char-*". The reverse (queued real, run under P1): outfit_raw
    "top=<COAT>", at render time token "", loras [face-lora 0.8], spec
    "char-*", appearance REAL-LOOK; afterwards live spec "pers-*". The two
    stems differ.
[G] Manifest: sidecar {equipped_pieces A, equipped_items [], look
    "persona:p1"} -> read_manifest look "persona:p1", model3d._ref_manifest
    carries look "persona:p1"; a sidecar without look -> read_manifest look
    "", _ref_manifest has no "look" key. Cache GC, not transformed now:
    the entry md5("top=<COAT>|look=persona:p1")[:12] with the look manifest
    is valid; the same entry with a look-less manifest is not.
[I] Identity reference (fix round 1, ruling 1). Cara gets a profile
    portrait images/profile.png (profile_image set) and a published
    expression of her REAL look (rendered not transformed, outfit A).
    reference_allowed: not transformed -> True for the portrait and the
    real expression; P1 -> False for both. _resolve_person_ref_image(Cara):
    not transformed -> the real expression (today's chain); P1 -> "" (no
    persona-look image yet; NOT the portrait, NOT the real expression);
    P1 profile_only -> ""; not transformed profile_only -> the portrait.
    Pinned to the real look while P1 is live -> the real expression again.
    After an expression published under P1 (its sidecar outfit_raw ends in
    "|look=persona:p1"): reference_allowed True for it, and
    _resolve_person_ref_image(Cara) under P1 -> that persona image.
[J] Face retexture (ruling 2). A face view model_refs/face_view.png whose
    sidecar certifies it (image_sha256 = its bytes, reference_sha256 = the
    portrait's bytes). reference_info(Cara, sig, meta): meta of a real-look
    T-pose (model3d._face_choice_meta of a sidecar without look) -> reference
    "face"; of a persona T-pose (sidecar look "persona:p1") -> reference
    "front", face_available False, no problems; explicit "face" with the
    persona meta -> one problem, code "persona_look".
[H] Deletion test (provider unregistered): effective == S, spec "char-*",
    current_outfit_state the real value, appearance REAL-LOOK.
"""
import copy
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(tempfile.mkdtemp(prefix="persona-imagegen-smoke-"))
STORAGE = ROOT / "world"
STORAGE.mkdir()
os.environ["STORAGE_DIR"] = str(STORAGE)
os.environ["INSTANCE_DIR"] = str(ROOT / "instance")
os.environ["ANIMATION_CLIPS_DIR"] = str(ROOT / "clips")
os.environ["ANIMATION_RIG_FILE"] = str(ROOT / "rig.fbx")
(STORAGE / "config.json").write_text(json.dumps({}), encoding="utf-8")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
paths.init_instance(ROOT / "instance")
from app.core import config, db  # noqa: E402
config.load(STORAGE / "config.json")
db.init_schema()

from app.core import pose_catalog as pc  # noqa: E402
_catalogs = {}
for _axis in ("pose", "expression"):
    _target = STORAGE / f"{_axis}.json"
    shutil.copyfile(pc.catalog_path(_axis), _target)
    _catalogs[_axis] = _target
pc.catalog_path = lambda axis: _catalogs[axis]
pc.reload_catalogs()
from app.core.expression_sets_migration import migrate_catalog_metadata  # noqa: E402
migrate_catalog_metadata()

from app.core import expression_regen as er  # noqa: E402
from app.core import hooks, identity_view  # noqa: E402
from app.core import model_refs as mr  # noqa: E402
from app.core import outfit_cache_gc as gc  # noqa: E402
from app.core import prompt_builder as pb  # noqa: E402
from app.core.keyed_lock import keyed_lock  # noqa: E402
from app.core.outfit_imagegen import current_look, effective_outfit_imagegen, pinned_look  # noqa: E402
from app.imagegen import routing  # noqa: E402
from app.models import inventory  # noqa: E402
from app.models.character import get_character_profile, save_character_profile  # noqa: E402
from app.models.inventory import add_item  # noqa: E402

FAILURES = []
CHECKED = 0


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'OK ' if ok else 'FAIL'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


def md5_12(text):
    return hashlib.md5(text.encode()).hexdigest()[:12]


REAL = "REAL-LOOK freckled redhead"
P_LOOK = "P-LOOK a figure in moonlit silver"
FACE = {"name": "face-lora", "strength": 0.8}
TURN = {"name": "turn-lora", "strength": 1.0}
MASK = {"name": "mask-lora", "strength": 0.6}
S = {"workflow": "char-*", "profile_workflow": "prof-*", "tpose_workflow": "char-tpose-*",
     "tpose_view_workflow": "tview-*", "mesh_workflow": "mesh-*", "model": "real.safetensors",
     "loras": [dict(FACE)], "tpose_loras": [dict(TURN)]}
S_ORIGINAL = copy.deepcopy(S)
P1 = {"persona_id": "p1", "alias": "Moonveil", "description": P_LOOK, "portrait_url": "",
      "imagegen": {"workflow": "pers-*", "tpose_workflow": "",
                   "loras": [dict(MASK)], "tpose_loras": []}}

COAT = add_item("Demo coat", category="outfit_piece", prompt_fragment="a linen coat",
                outfit_piece={"slots": ["top"]})["id"]
A = {"top": COAT}
RAW = f"top={COAT}"

assert save_character_profile("Cara", {"character_name": "Cara", "template": "human-default"},
                              create_new=True)
with keyed_lock("character_profile", "Cara"):
    _p = get_character_profile("Cara")
    _p["character_appearance"] = REAL
    _p["outfit_imagegen"] = copy.deepcopy(S)
    assert save_character_profile("Cara", _p)

PERSONA = {}


def _active(subject):
    got = PERSONA.get(subject)
    return copy.deepcopy(got) if got else None


def provider_on():
    hooks.register_provider(identity_view.PROVIDER_ACTIVE, _active, owner="smoke")


provider_on()
_equip = (patch.object(inventory, "get_equipped_pieces", side_effect=lambda _n: dict(A)),
          patch.object(inventory, "get_equipped_items", side_effect=lambda _n: []))
for _ctx in _equip:
    _ctx.start()

print("[A] effective_outfit_imagegen")
got = effective_outfit_imagegen("Cara", S)
check("not transformed -> equal to stored", got, S_ORIGINAL)
check("not transformed -> a new object", got is S, False)
got["loras"].append({"name": "x"})
check("mutating the copy leaves stored", S, S_ORIGINAL)
PERSONA["Cara"] = P1
check("P1 -> merged", effective_outfit_imagegen("Cara", S),
      {"workflow": "pers-*", "profile_workflow": "prof-*", "tpose_workflow": "char-tpose-*",
       "tpose_view_workflow": "tview-*", "mesh_workflow": "mesh-*",
       "loras": [MASK], "tpose_loras": []})
PERSONA["Cara"] = dict(P1, imagegen={})
got = effective_outfit_imagegen("Cara", S)
check("imagegen {} -> backends kept", (got["workflow"], got["tpose_workflow"]),
      ("char-*", "char-tpose-*"))
check("imagegen {} -> no character LoRA", (got["loras"], got["tpose_loras"], "model" in got),
      ([], [], False))
PERSONA["Cara"] = dict(P1, imagegen={"tpose_workflow": "pers-tpose-*",
                                     "tpose_loras": [{"name": "p-turn", "strength": 0.9}]})
got = effective_outfit_imagegen("Cara", S)
check("T-pose-only persona", (got["tpose_workflow"], got["workflow"], got["loras"], got["tpose_loras"]),
      ("pers-tpose-*", "char-*", [], [{"name": "p-turn", "strength": 0.9}]))
check("stored never modified", S, S_ORIGINAL)
PERSONA["Cara"] = P1
pi = identity_view.persona_imagegen("Cara")
check("persona_imagegen P1", pi, P1["imagegen"])
pi["loras"].append("x")
check("persona_imagegen is a copy", identity_view.persona_imagegen("Cara")["loras"], [MASK])
check("look_token P1", identity_view.look_token("Cara"), "persona:p1")
PERSONA["Cara"] = dict(P1, persona_id="")
check("look_token without id", identity_view.look_token("Cara"), "persona:Moonveil")
PERSONA.clear()
check("persona_imagegen none", identity_view.persona_imagegen("Cara"), None)
check("look_token none", identity_view.look_token("Cara"), "")

print("[B] routing character match")
check("no persona expression", routing.character_spec("expression", "Cara"), "char-*")
check("no persona photo", routing.character_spec("photo", "Cara"), "char-*")
check("no persona tpose", routing.character_spec("tpose", "Cara"), "char-tpose-*")
PERSONA["Cara"] = P1
for occ, want in (("expression", "pers-*"), ("photo", "pers-*"), ("instagram", "pers-*"),
                  ("tpose", "char-tpose-*"), ("profile", "prof-*"), ("tpose_view", "tview-*")):
    check(f"P1 {occ}", routing.character_spec(occ, "Cara"), want)
check("P1 chain_for position 0", routing.chain_for("expression", "Cara")[0], ("pers-*", "character", 0))
PERSONA["Cara"] = dict(P1, imagegen={"tpose_workflow": "pers-tpose-*"})
check("T-pose persona tpose", routing.character_spec("tpose", "Cara"), "pers-tpose-*")
check("T-pose persona expression", routing.character_spec("expression", "Cara"), "char-*")
PERSONA.clear()

print("[C] signature")
check("raw without look", mr.outfit_signature_raw(A, [], "Cara"), RAW)
check("raw with look", mr.outfit_signature_raw(A, [], "Cara", look="persona:p1"), RAW + "|look=persona:p1")
check("mesh_signature with look", mr.mesh_signature(A, [], "Cara", "", "persona:p1"),
      md5_12(RAW + "|look=persona:p1"))
check("worn, not transformed", mr.current_outfit_state("Cara")[2], md5_12(RAW))
PERSONA["Cara"] = P1
check("worn, P1", mr.current_outfit_state("Cara")[2], md5_12(RAW + "|look=persona:p1"))
with pinned_look("Cara"):
    PERSONA.clear()
    check("pinned P1 after the revert", mr.current_outfit_state("Cara")[2],
          md5_12(RAW + "|look=persona:p1"))
check("after the pin", mr.current_outfit_state("Cara")[2], md5_12(RAW))

print("[D] image appearance")
check("not transformed", pb.person_description("Cara"), REAL)
PERSONA["Cara"] = P1
check("P1", pb.person_description("Cara"), P_LOOK)
check("PromptBuilder real_look", pb.PromptBuilder("Cara", real_look=True)._resolve_character_appearance("Cara"), REAL)
check("PromptBuilder default", pb.PromptBuilder("Cara")._resolve_character_appearance("Cara"), P_LOOK)
PERSONA["Cara"] = dict(P1, description="")
check("P1 without description", pb.person_description("Cara"), REAL)
PERSONA.clear()

print("[E] render_character_image payload")


class FakeService:
    enabled = True

    def __init__(self):
        self.payloads = []

    def generate_from_input(self, text):
        self.payloads.append(json.loads(text))
        return "Error: fake service"


def render_payload(occasion):
    fake = FakeService()
    with patch("app.imagegen.service.get_image_service", return_value=fake):
        er.render_character_image("Cara", output_stem=ROOT / "out" / "x", equipped_pieces=dict(A),
                                  equipped_items=[], pose_prompt="standing", expression_prompt="calm",
                                  image_use_case="tpose" if occasion == "tpose" else "expression",
                                  occasion=occasion)
    return fake.payloads[0]


pay = render_payload("expression")
check("real expression loras", pay.get("loras"), [FACE])
check("real expression model", pay.get("model_override"), "real.safetensors")
check("real expression appearance", pay["appearances"][0]["appearance"], REAL)
check("real tpose loras", render_payload("tpose").get("loras"), [TURN])
PERSONA["Cara"] = P1
pay = render_payload("expression")
check("P1 expression loras", pay.get("loras"), [MASK])
check("P1 expression model", "model_override" in pay, False)
check("P1 expression appearance", pay["appearances"][0]["appearance"], P_LOOK)
check("P1 tpose loras", render_payload("tpose").get("loras"), [MASK])
PERSONA.clear()

print("[F] expression job keeps its queued state")
SEEN = []


def recorder(character, *, output_stem, **kw):
    prof = kw["appearance_profile"]
    SEEN.append({"token": current_look(character).token,
                 "loras": effective_outfit_imagegen(character, prof.get("outfit_imagegen"))["loras"],
                 "spec": routing.character_spec("expression", character),
                 "appearance": pb.person_description(character, body_profile=prof,
                                                     apply_state_modifiers=False, neutral_state=True)})
    return None


PERSONA["Cara"] = P1
req = er.expression_snapshot("Cara", "neutral", equipped_pieces=dict(A), equipped_items=[])
check("queued outfit_raw", req.outfit_raw, RAW + "|look=persona:p1")
check("frozen profile loras", er._thaw(req.profile)["outfit_imagegen"]["loras"], [MASK])
PERSONA.clear()
# The recorder renders nothing: the job then fails on purpose (its log quiet).
with patch.object(er, "render_character_image", recorder), patch.object(er, "logger"):
    er.generate_expression_image(req)
check("render time, queued P1", SEEN[-1] if SEEN else None,
      {"token": "persona:p1", "loras": [MASK], "spec": "pers-*", "appearance": P_LOOK})
check("live after the job", routing.character_spec("expression", "Cara"), "char-*")
req2 = er.expression_snapshot("Cara", "neutral", equipped_pieces=dict(A), equipped_items=[])
check("queued real outfit_raw", req2.outfit_raw, RAW)
PERSONA["Cara"] = P1
with patch.object(er, "render_character_image", recorder), patch.object(er, "logger"):
    er.generate_expression_image(req2)
check("render time, queued real", SEEN[-1] if len(SEEN) > 1 else None,
      {"token": "", "loras": [FACE], "spec": "char-*", "appearance": REAL})
check("live P1 after the job", routing.character_spec("expression", "Cara"), "pers-*")
check("stems differ", req.stem != req2.stem, True)
PERSONA.clear()

print("[G] manifests and cache GC")
from app.core import model3d  # noqa: E402
side = ROOT / "refs"
side.mkdir()
(side / "tpose_a.json").write_text(json.dumps({"equipped_pieces": A, "equipped_items": [],
                                               "look": "persona:p1"}))
(side / "tpose_b.json").write_text(json.dumps({"equipped_pieces": A, "equipped_items": []}))
with_look = gc.read_manifest(side / "tpose_a.json")
without = gc.read_manifest(side / "tpose_b.json")
check("read_manifest look", with_look["look"], "persona:p1")
check("read_manifest no look", without["look"], "")
check("_ref_manifest look", model3d._ref_manifest(side / "tpose_a.png").get("look"), "persona:p1")
check("_ref_manifest no look key", "look" in model3d._ref_manifest(side / "tpose_b.png"), False)
sig_p = md5_12(RAW + "|look=persona:p1")
check("GC: persona entry valid after revert",
      gc._entry_valid(sig_p, with_look, {COAT}, lambda: set(), "Cara"), True)
check("GC: look-less manifest does not re-sign",
      gc._entry_valid(sig_p, without, {COAT}, lambda: set(), "Cara"), False)

print("[I] identity reference")
from PIL import Image  # noqa: E402
from app.core.outfit_imagegen import REAL_LOOK, reference_allowed  # noqa: E402
from app.models.character import get_character_current_feeling, get_character_images_dir  # noqa: E402
PERSONA.clear()
with keyed_lock("character_profile", "Cara"):
    _p = get_character_profile("Cara")
    _p["profile_image"] = "profile.png"
    assert save_character_profile("Cara", _p)
PORTRAIT = get_character_images_dir("Cara") / "profile.png"
PORTRAIT.parent.mkdir(parents=True, exist_ok=True)
Image.new("RGB", (8, 8), (100, 0, 0)).save(PORTRAIT)


def fake_expression(character, *, output_stem, **kw):
    image = output_stem.with_suffix(".png")
    Image.new("RGB", (8, 8), (20, 40, 60)).save(image)
    image.with_suffix(".json").write_text(json.dumps({"prompt": kw["expression_prompt"],
                                                      "equipped_pieces": kw["equipped_pieces"],
                                                      "equipped_items": kw["equipped_items"]}))
    return image


MOOD = get_character_current_feeling("Cara") or ""
with patch.object(er, "render_character_image", fake_expression):
    REAL_EXPR = er.generate_expression_image(er.expression_snapshot("Cara", MOOD))
check("real expression published", REAL_EXPR is not None, True)
PERSON = pb.Person(name="Cara", appearance="", gender="")
check("allowed, not transformed: portrait", reference_allowed("Cara", PORTRAIT), True)
check("allowed, not transformed: real expression", reference_allowed("Cara", REAL_EXPR), True)
check("not transformed: real expression", pb.PromptBuilder("Cara")._resolve_person_ref_image(PERSON), str(REAL_EXPR))
check("not transformed profile_only: portrait",
      pb.PromptBuilder("Cara")._resolve_person_ref_image(PERSON, profile_only=True), str(PORTRAIT))
PERSONA["Cara"] = P1
check("allowed, P1: portrait", reference_allowed("Cara", PORTRAIT), False)
check("allowed, P1: real expression", reference_allowed("Cara", REAL_EXPR), False)
check("P1: no reference", pb.PromptBuilder("Cara")._resolve_person_ref_image(PERSON), "")
check("P1 profile_only: no reference",
      pb.PromptBuilder("Cara")._resolve_person_ref_image(PERSON, profile_only=True), "")
with pinned_look("Cara", REAL_LOOK):
    check("pinned real look: real expression",
          pb.PromptBuilder("Cara")._resolve_person_ref_image(PERSON), str(REAL_EXPR))
with patch.object(er, "render_character_image", fake_expression):
    P_EXPR = er.generate_expression_image(er.expression_snapshot("Cara", MOOD))
check("persona expression published", P_EXPR is not None and P_EXPR != REAL_EXPR, True)
check("allowed, P1: persona expression", reference_allowed("Cara", P_EXPR), True)
check("P1: the persona expression", pb.PromptBuilder("Cara")._resolve_person_ref_image(PERSON), str(P_EXPR))
PERSONA.clear()

print("[J] face retexture reference")
from app.core import face_retexture  # noqa: E402
REFS = mr.get_model_refs_dir("Cara")
REFS.mkdir(parents=True, exist_ok=True)
FACE = REFS / "face_view.png"
Image.new("RGB", (8, 8), (200, 150, 120)).save(FACE)
FACE.with_suffix(".json").write_text(json.dumps({
    "image_sha256": hashlib.sha256(FACE.read_bytes()).hexdigest(),
    "reference_sha256": hashlib.sha256(PORTRAIT.read_bytes()).hexdigest()}))
SIG = md5_12(RAW)
for _name, _look in (("tpose_real", ""), ("tpose_persona", "persona:p1")):
    _img = REFS / f"{_name}.png"
    Image.new("RGB", (8, 8), (1, 2, 3)).save(_img)
    _img.with_suffix(".json").write_text(json.dumps({"equipped_pieces": A, "equipped_items": [],
                                                     **({"look": _look} if _look else {})}))
real_meta = model3d._face_choice_meta(REFS / "tpose_real.png", b"x")
persona_meta = model3d._face_choice_meta(REFS / "tpose_persona.png", b"x")
check("real-look mesh: face view", face_retexture.reference_info("Cara", SIG, real_meta)["reference"], "face")
got = face_retexture.reference_info("Cara", SIG, persona_meta)
check("persona mesh: front, no face view, no problem",
      (got["reference"], got["face_available"], got["problems"]), ("front", False, []))
got = face_retexture.reference_info("Cara", SIG, persona_meta, "face")
check("persona mesh, explicit face: refused", [p["code"] for p in got["problems"]], ["persona_look"])

print("[H] deletion test")
PERSONA["Cara"] = P1
hooks.unregister_owned_providers("smoke")
check("effective", effective_outfit_imagegen("Cara", S), S_ORIGINAL)
check("spec", routing.character_spec("expression", "Cara"), "char-*")
check("worn signature", mr.current_outfit_state("Cara")[2], md5_12(RAW))
check("appearance", pb.person_description("Cara"), REAL)

for _ctx in _equip:
    _ctx.stop()
shutil.rmtree(ROOT, ignore_errors=True)
print(f"\n{CHECKED - len(FAILURES)}/{CHECKED} checks passed")
if FAILURES:
    print("FAILED:", ", ".join(FAILURES))
    sys.exit(1)
print("PASS smoke_persona_imagegen")
