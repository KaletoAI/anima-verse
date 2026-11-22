#!/usr/bin/env python3
"""Change plan point 2 + 3: a re-render plans its own slots and names them; scene view and pose check keep the tokens.

Usage: ./.venv/bin/python scripts/smoke_regen_ref_marks.py

Runs without the server, on a temp storage (paths.init before any world-DB import), with a fake backend that captures
what it is sent (the prompt BEFORE the normaliser — the canonical ``<ref N>``) and a stubbed llm_call.
Design: docs/edit-prompts.md §4. Expected values, derived by hand from the rules:

[A] ``edit_prompt.strip_refs`` removes every token spelling, not only ``<ref N>``:
    A1 "- Ann (the person in <image3>), brown hair." -> "- Ann, brown hair." (the parenthesis holds only the token part)
    A2 "Setting: the place shown in <image2>." -> the line goes (no word left after the label)
    A3 "Edit <Picture 1>. Keep the face of <Picture 2>, warm light." -> the P-H3 prefix goes whole, then the clause
       holding a token goes: "warm light."
    A4 "Kai (tall; as in @image2), smiling" -> "Kai (tall), smiling";  "<Subject 1> waves" -> the line goes.
    A5 ordinal prose is no token: "the first image" stays byte-identical.
[B] ``edit_prompt.mark_refs(prompt, roles)`` (roles = the slot manifest):
    B1 "Kai and Kaira at the bar.\\n- Kai, tall." with Kai in slot 2 -> the LIST line "- Kai" is marked first,
       not the earlier prose mention: "Kai and Kaira at the bar.\\n- Kai (the person in <ref 2>), tall."
    B2 only Kaira mentioned ("Kaira laughs.") and Kai in slot 2 -> "Kaira" is no mention of Kai (whole word) ->
       the line "Kai (the person in <ref 2>) is in the picture too." is added at the end.
    B3 "People in the frame: Kai (tall; blue shirt)" -> the mark becomes the parenthesis' first part:
       "People in the frame: Kai (the person in <ref 1>; tall; blue shirt)".
    B4 "Kai's cup and Kai." -> the possessive is skipped, the second mention is marked: "Kai's cup and Kai (the person
       in <ref 1>)."
    B5 room in slot 3, text "A walk, setting: the park." -> "A walk, setting: the place shown in <ref 3>, the park."
       without a setting label -> line "Setting: the place shown in <ref 3>." at the end.
    B6 item "lamp" in slot 4 -> line "Objects: the lamp from <ref 4>."
    B7 a slot already named (``<ref 2>`` in the text) is left alone; roles {} or None -> byte-identical.
    B8 lines are added as their own paragraph before a closing "Style:" paragraph: "X.\\n\\nStyle: photo." + room 2
       -> "X.\\n\\nSetting: the place shown in <ref 2>.\\n\\nStyle: photo." (inserted at the "Style:" line, so the blank
       line before it stays and one more follows the added lines).
[C] ``regenerate_image`` with a fake 3-slot backend, people Ann (agent) + Bob, stored prompt STORED (it carries the
    Qwen tokens of an earlier render, ``<image3>`` for Ann, ``<image1>`` for Bob, ``<image2>`` for the room — a
    prompt copied from a log's final_prompt):
    strip -> BASE = "A photo of Ann and Bob at the window.\\n\\nCharacters:\\n- Ann, brown hair.\\n- Bob, short
    hair.\\n\\nStyle: photo." (the setting line has no word left and goes; three blank lines collapse to one).
    C1 use_room=False: plan = Ann (agent) slot 1, Bob slot 2 -> sent prompt = BASE with "- Ann (the person in
       <ref 1>), brown hair." and "- Bob (the person in <ref 2>), short hair."; reference_roles = {1: identity Ann,
       2: identity Bob}; the returned (stored) prompt == BASE (no token).
    C2 use_room=True (the room from the location): Ann 1, room 2, Bob 3 -> Bob "<ref 3>" and the paragraph "Setting:
       the place shown in <ref 2>." before "Style: photo." (as B8); roles[2] = room.
    C3 a 1-slot backend: only Ann is slotted -> only "- Ann (the person in <ref 1>)"; Bob unmarked; no setting line.
    C4 a 0-slot backend: the sent prompt == BASE, no reference_roles.
    C5 the dialog adds Cid (not in the text), 4 slots, no room: Cid slot 3 -> "Cid (the person in <ref 3>) is in the
       picture too." before "Style: photo.".
    C6 screenshot photo (occasion "photo", the source as reference), stored prompt with the OLD sentence "The
       reference image gives only composition, …": slot 1 = screenshot (role composition), Ann 2, Bob 3; the sent
       prompt ends with exactly one "<ref 1> gives only composition, camera angle and poses; its 3D/CGI look must not
       be copied."; the returned prompt has no sentence and no token. On a 0-slot backend the sentence is NOT sent
       (it would name a picture that is not there).
[D] normaliser, no slot sent: a ``<ref N>`` never reaches the engine — "The exact room from <ref 1>, keeping its
    layout. Two people sit." -> its sentence is dropped: "Two people sit."; prose without the token ("the first
    image") stays byte-identical (docs §3 step 1).
[E] scene view defaults: ``PROMPT_MULTI_REF_DEFAULT`` filled with people "Kai (shown in <ref 2>; tall man); Mia
    (shown in <ref 3>; slim woman)" and normalised for Qwen2.1 with 3 slots starts "The exact room from <image1>, "
    and contains "Kai (shown in <image2>; " and "Mia (shown in <image3>; "; no "reference image" in either default;
    the previous defaults (code and schema placeholder) are in ``SCENE_PROMPT_LEGACY_DEFAULTS``; each schema
    placeholder == its code default.
[F] pose check keeps the tokens: original O names <ref 1>, <ref 2>, <ref 3>.
    F1 an answer (long enough) that lost "<ref 3>" -> check_pose returns O.
    F2 an answer that keeps all three -> the answer.
    F3 a token-free prompt -> the answer (unchanged behaviour).
    F4 the template names the rule ("Keep every reference token").
"""
import io
import os
import sys
import tempfile
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
TEMP = tempfile.TemporaryDirectory(prefix="smoke-regen-ref-marks-")
os.environ["STORAGE_DIR"] = TEMP.name
os.environ["INSTANCE_DIR"] = TEMP.name
from app.core import paths  # noqa: E402

paths.init(TEMP.name)
paths.init_instance(TEMP.name)
from app.core import db  # noqa: E402

db.init_schema()
from PIL import Image  # noqa: E402

from app.core import prompt_builder as pb  # noqa: E402
from app.imagegen import edit_prompt as ep  # noqa: E402
from app.models import character  # noqa: E402
from app.skills import image_regenerate as ir  # noqa: E402

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}" + ("" if ok else f"\n         expected {want!r}"))
    if not ok:
        FAILS.append(label)


# ------------------------------------------------------------------------------------------------ [A] strip_refs
print("[A] strip_refs")
check("A1", ep.strip_refs("- Ann (the person in <image3>), brown hair."), "- Ann, brown hair.")
check("A2", ep.strip_refs("X.\nSetting: the place shown in <image2>."), "X.")
check("A3", ep.strip_refs("Edit <Picture 1>. Keep the face of <Picture 2>, warm light."), "warm light.")
check("A4 paren", ep.strip_refs("Kai (tall; as in @image2), smiling"), "Kai (tall), smiling")
check("A4 subject", ep.strip_refs("A walk.\n<Subject 1> waves"), "A walk.")
check("A5 prose", ep.strip_refs("Use the first image."), "Use the first image.")

# ------------------------------------------------------------------------------------------------ [B] mark_refs


def ident(name):
    return {"role": "identity", "label": name}


def k(n):
    return f"input_reference_image_{n}"


print("[B] mark_refs")
check("B1", ep.mark_refs("Kai and Kaira at the bar.\n- Kai, tall.", {k(2): ident("Kai")}),
      "Kai and Kaira at the bar.\n- Kai (the person in <ref 2>), tall.")
check("B2", ep.mark_refs("Kaira laughs.", {k(2): ident("Kai")}),
      "Kaira laughs.\nKai (the person in <ref 2>) is in the picture too.")
check("B3", ep.mark_refs("People in the frame: Kai (tall; blue shirt)", {k(1): ident("Kai")}),
      "People in the frame: Kai (the person in <ref 1>; tall; blue shirt)")
check("B4", ep.mark_refs("Kai's cup and Kai.", {k(1): ident("Kai")}), "Kai's cup and Kai (the person in <ref 1>).")
room3 = {k(3): {"role": "room", "label": "the room"}}
check("B5 label", ep.mark_refs("A walk, setting: the park.", room3),
      "A walk, setting: the place shown in <ref 3>, the park.")
check("B5 none", ep.mark_refs("A walk.", room3), "A walk.\nSetting: the place shown in <ref 3>.")
check("B6", ep.mark_refs("A table.", {k(4): {"role": "item", "label": "lamp"}}),
      "A table.\nObjects: the lamp from <ref 4>.")
check("B7 named", ep.mark_refs("Kai from <ref 2>.", {k(2): ident("Kai")}), "Kai from <ref 2>.")
check("B7 empty", ep.mark_refs("Kai.", {}), "Kai.")
check("B7 none", ep.mark_refs("Kai.", None), "Kai.")
check("B8", ep.mark_refs("X.\n\nStyle: photo.", {k(2): {"role": "room", "label": "the room"}}),
      "X.\n\nSetting: the place shown in <ref 2>.\n\nStyle: photo.")

# ------------------------------------------------------------------------------------------------ [C] regenerate
print("[C] regenerate_image")
buf = io.BytesIO()
Image.new("RGB", (4, 4), "red").save(buf, "PNG")
PNG = buf.getvalue()


class Backend:
    name, api_type, model, image_family = "Fake", "fake", "", "natural"
    supports_negative_prompt = True

    def __init__(self, slots):
        self.ref_slot_count = slots
        self.captured = None

    def generate(self, prompt, negative, params, **kwargs):
        self.captured = prompt, dict(params.get("reference_images") or {}), dict(params.get("reference_roles") or {})
        return [PNG]


class Service:
    enabled = True

    def __init__(self, backend):
        self.backend = backend

    def _wait_for_explicit_backend(self, name): return self.backend
    def _get_instance_config(self, *args): return {}
    def run_on_backend_channel(self, backend, fn, **kwargs): return fn()
    def run_on_backend(self, backend, op, **kwargs): return op(backend), backend
    def _generate_image_analysis(self, *args): return ""


REFS = {}
ROOM = Path(TEMP.name) / "world_gallery" / "loc1" / "room.png"
ROOM.parent.mkdir(parents=True)
ROOM.write_bytes(PNG)
for name in ("Ann", "Bob", "Cid"):
    character.save_character_profile(name, {"name": name, "language": "en"}, create_new=True)
    ref = character.get_character_outfits_dir(name) / f"{name}_original.png"
    ref.write_bytes(PNG)
    REFS[name] = str(ref)


class Builder(pb.PromptBuilder):
    def __init__(self, name): self.character_name = name

    def detect_persons(self, prompt, character_names=None):
        names = character_names if character_names is not None else ["Ann", "Bob"]
        return [pb.Person(n, "", "", is_agent=n == "Ann") for n in names]

    def _resolve_person_ref_image(self, person): return REFS[person.name]
    def _collect_location(self, variables): variables.ref_image_room = str(ROOM)


GALLERY = character.get_character_images_dir("Ann")
GALLERY.mkdir(parents=True, exist_ok=True)
SOURCE = GALLERY / "src.png"
SOURCE.write_bytes(PNG)
STORED = ("A photo of Ann and Bob at the window.\n\nCharacters:\n- Ann (the person in <image3>), brown hair.\n"
          "- Bob (the person in <image1>), short hair.\n\nSetting: the place shown in <image2>.\n\nStyle: photo.")
BASE = "A photo of Ann and Bob at the window.\n\nCharacters:\n- Ann, brown hair.\n- Bob, short hair.\n\nStyle: photo."
SENTENCE = "<ref 1> gives only composition, camera angle and poses; its 3D/CGI look must not be copied."


def regen(slots, prompt=STORED, names=("Ann", "Bob"), **kw):
    backend = Backend(slots)
    with ExitStack() as stack:
        for target, kwargs in [
            ("app.imagegen.service.get_image_service", {"return_value": Service(backend)}),
            ("app.core.prompt_builder.PromptBuilder", {"new": Builder}),
            ("app.core.config.resolve_use_case_style", {"return_value": {}}),
        ]:
            stack.enter_context(patch(target, **kwargs))
        out = GALLERY / "out.png"
        ok, final, _ = ir.regenerate_image("Ann", str(out), prompt, backend_name="Fake",
                                           character_names=list(names), pose_check=False, **kw)
    assert ok
    return final, backend.captured


def roles_of(r):
    return {int(key.rsplit("_", 1)[1]): (v["role"], v["label"]) for key, v in r.items()}


check("strip of STORED", ep.strip_refs(STORED), BASE)
final, (sent, refs, roles) = regen(3, use_room=False)
check("C1 sent", sent, BASE.replace("- Ann,", "- Ann (the person in <ref 1>),")
      .replace("- Bob,", "- Bob (the person in <ref 2>),"))
check("C1 roles", roles_of(roles), {1: ("identity", "Ann"), 2: ("identity", "Bob")})
check("C1 refs", [Path(refs[k(n)]).name for n in (1, 2)], ["Ann_original.png", "Bob_original.png"])
check("C1 stored", final, BASE)

final, (sent, refs, roles) = regen(3, use_room=True)
check("C2 sent", sent, BASE.replace("- Ann,", "- Ann (the person in <ref 1>),")
      .replace("- Bob,", "- Bob (the person in <ref 3>),")
      .replace("short hair.\n\nStyle", "short hair.\n\nSetting: the place shown in <ref 2>.\n\nStyle"))
check("C2 roles", roles_of(roles), {1: ("identity", "Ann"), 2: ("room", "the room"), 3: ("identity", "Bob")})

final, (sent, refs, roles) = regen(1, use_room=True)
check("C3 sent", sent, BASE.replace("- Ann,", "- Ann (the person in <ref 1>),"))

final, (sent, refs, roles) = regen(0, use_room=True)
check("C4 sent", (sent, roles), (BASE, {}))

final, (sent, refs, roles) = regen(4, names=("Ann", "Bob", "Cid"), use_room=False)
check("C5 sent", sent, BASE.replace("- Ann,", "- Ann (the person in <ref 1>),")
      .replace("- Bob,", "- Bob (the person in <ref 2>),")
      .replace("short hair.\n\nStyle", "short hair.\n\nCid (the person in <ref 3>) is in the picture too.\n\nStyle"))

OLD = STORED + "\nThe reference image gives only composition, camera angle and poses; its 3D/CGI look must not be copied."
final, (sent, refs, roles) = regen(3, prompt=OLD, occasion="photo", use_source_as_reference=True,
                                   source_image_path=str(SOURCE), use_room=False)
check("C6 sent", sent, BASE.replace("- Ann,", "- Ann (the person in <ref 2>),")
      .replace("- Bob,", "- Bob (the person in <ref 3>),") + "\n" + SENTENCE)
check("C6 once", sent.count("gives only composition"), 1)
check("C6 roles", roles_of(roles), {1: ("composition", "the screenshot"), 2: ("identity", "Ann"),
                                    3: ("identity", "Bob")})
check("C6 stored", final, BASE)
final, (sent, refs, roles) = regen(0, prompt=OLD, occasion="photo", use_source_as_reference=True,
                                   source_image_path=str(SOURCE), use_room=False)
check("C6 0-slot", sent, BASE)

# ------------------------------------------------------------------------------------------------ [D] normaliser
print("[D] normaliser without a slot")
QW = SimpleNamespace(model="Qwen2.1", prompt_dialect_setting="auto", name="Qwen2.1")
out, meta = ep.normalise("The exact room from <ref 1>, keeping its layout. Two people sit.", {}, QW)
check("D token", (out, meta["notes"]), ("Two people sit.", ["unresolved"]))
prose = "Put the hat from the second image on the first image."
check("D prose", ep.normalise(prose, {}, QW)[0], prose)

# ------------------------------------------------------------------------------------------------ [E] scene defaults
print("[E] scene view defaults")
from app.core import scene_render as sr  # noqa: E402
from app.core.config_schema import SCENE_PROMPT_LEGACY_DEFAULTS, SECTIONS  # noqa: E402

people = "Kai (shown in <ref 2>; tall man); Mia (shown in <ref 3>; slim woman)"
filled = sr.PROMPT_MULTI_REF_DEFAULT.format(setting="room", count="exactly two people", people=people)
slots3 = {"reference_images": {k(n): f"/tmp/r{n}.png" for n in (1, 2, 3)}}
out, _ = ep.normalise(filled, slots3, QW)
check("E start", out.startswith("The exact room from <image1>, "), True)
check("E people", ("Kai (shown in <image2>; " in out, "Mia (shown in <image3>; " in out), (True, True))
check("E no old words", any("reference image" in d for d in (sr.PROMPT_MULTI_REF_DEFAULT, sr.PROMPT_ONLY_BG_DEFAULT)),
      False)
OLD_CODE = ("The exact {setting} from the first reference image, keeping its layout, lighting and perspective. Compose "
            "{count} into the scene and NO ONE else — each of them appears exactly once, no additional people or "
            "animals, no duplicates. A subject's reference image pins their FACE/IDENTITY ONLY — their appearance, "
            "outfit and pose follow the text; IGNORE the pose, outfit and background the reference shows. "
            "Subjects: {people}")
check("E legacy", OLD_CODE in SCENE_PROMPT_LEGACY_DEFAULTS, True)


def _field(schema, key):
    if isinstance(schema, dict):
        if key in schema and isinstance(schema[key], dict) and "placeholder" in schema[key]:
            return schema[key]
        for v in schema.values():
            got = _field(v, key)
            if got:
                return got
    elif isinstance(schema, list):
        for v in schema:
            got = _field(v, key)
            if got:
                return got
    return None


check("E placeholder multi", _field(SECTIONS, "scene_prompt_multi_ref")["placeholder"],
      sr.PROMPT_MULTI_REF_DEFAULT)
check("E placeholder bg", _field(SECTIONS, "scene_prompt_only_background")["placeholder"],
      sr.PROMPT_ONLY_BG_DEFAULT)

# ------------------------------------------------------------------------------------------------ [F] pose check
print("[F] pose check")
from app.imagegen import pose_check  # noqa: E402

O = ("The exact room from <ref 1>, keeping its layout. Subjects: Kai (shown in <ref 2>; tall man): sitting at the "
     "table; Mia (shown in <ref 3>; slim woman): standing by the counter.")
LOST = ("The exact room from <ref 1>, keeping its layout. Subjects: Kai (shown in <ref 2>; tall man): sitting at the "
        "table, both hands on the cup; Mia (slim woman): standing by the counter, her left hand on it.")
KEPT = LOST.replace("Mia (slim", "Mia (shown in <ref 3>; slim")


def answer(text):
    return lambda **kw: SimpleNamespace(content=f"CHECK: fine\nPROMPT: {text}")


with patch("app.core.llm_router.llm_call", answer(LOST)):
    check("F1 lost", pose_check.check_pose(O), O)
with patch("app.core.llm_router.llm_call", answer(KEPT)):
    check("F2 kept", pose_check.check_pose(O), KEPT)
PLAIN = ep.strip_refs(O)
with patch("app.core.llm_router.llm_call", answer(ep.strip_refs(LOST))):
    check("F3 plain", pose_check.check_pose(PLAIN), ep.strip_refs(LOST))
TPL = (Path(__file__).resolve().parents[1] / "shared/templates/llm/tasks/image_pose_check.md").read_text()
check("F4 template", "Keep every reference token" in TPL, True)

print("ALL OK" if not FAILS else f"FAILED: {FAILS}")
sys.exit(1 if FAILS else 0)
