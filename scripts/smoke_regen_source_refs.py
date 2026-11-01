"""Smoke: a regenerate renders with the reference images of its SOURCE image
(app/imagegen/source_refs.py + app/skills/image_regenerate.py).

Usage:
    ./.venv/bin/python scripts/smoke_regen_source_refs.py

Runs without the server: temp storage, no world DB, a stubbed image service
and prompt builder — no backend and no LLM is contacted.

Expected values, derived by hand from the user report (2026-11-01: a nude
scene of Kira, rendered with her nude outfit reference, came back in the
white dress she wears TODAY, because the regenerate resolved her current
reference instead of the one the image was rendered with):

Fixture (temp storage):
    characters/Kira/outfits/Kira_nude.png    — the source image's reference
    characters/Kira/outfits/Kira_dress.png   — her CURRENT reference
    characters/Kai/outfits/Kai_a.png         — the source's second person
    characters/Luisa/outfits/Luisa_now.png   — a person the dialog ADDS
    world_gallery/loc1/room_a.png            — the source's room reference
    world_gallery/loc1/room_now.png          — the room's CURRENT reference

A) meta_paths — an absolute file inside storage becomes its storage-relative
   path ("characters/Kira/outfits/Kira_nude.png"); a file outside is dropped.
B) source_references with reference_paths: persons {Kira: Kira_nude, Kai:
   Kai_a}, room room_a.
C) An old meta with file NAMES only resolves the same three files by search.
D) A missing file is left out; "../x" names and paths leaving the storage dir
   resolve to nothing.
E) regenerate_image(keep_source_references=True): Kira gets Kira_nude (not
   the live Kira_dress), the room room_a (not the live room_now); Luisa, whom
   the source does not have, gets her live Luisa_now. The written meta
   carries reference_paths of exactly those files.
F) Same call with keep_source_references=False (a NEW render): the live
   references Kira_dress and room_now (the room's current gallery default,
   get_background_path(loc1, r1) — stubbed to room_now).
G) The dialog picks ANOTHER room (room_id "r2" != the source's "r1"): the
   room resolves live (room_now) while the people keep their source refs.
   Picking the SAME room ("r1") keeps room_a.
H) Callers: the gallery worker, the Instagram regenerate and the Improvements
   gallery re-render pass keep_source_references=True; the scene photo
   (a NEW photo) does not.
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_tmp = Path(tempfile.mkdtemp(prefix="smoke_regen_refs_"))
os.environ["STORAGE_DIR"] = str(_tmp)
os.environ["INSTANCE_DIR"] = str(_tmp)

from app.core import paths  # noqa: E402
paths.init(str(_tmp))

failures = []


def check(name, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + name + (f"   [{detail}]" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def touch(rel):
    p = _tmp / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"\x89PNG fixture")
    return p


NUDE = touch("characters/Kira/outfits/Kira_nude.png")
DRESS = touch("characters/Kira/outfits/Kira_dress.png")
KAI = touch("characters/Kai/outfits/Kai_a.png")
LUISA = touch("characters/Luisa/outfits/Luisa_now.png")
ROOM = touch("world_gallery/loc1/room_a.png")
ROOM_NOW = touch("world_gallery/loc1/room_now.png")
(_tmp / "characters/Kai/images").mkdir(parents=True, exist_ok=True)
SOURCE = touch("characters/Kai/images/Kai_photo_v1.png")
outside = Path(tempfile.mkdtemp(prefix="smoke_regen_outside_")) / "x.png"
outside.write_bytes(b"x")

from app.imagegen import source_refs  # noqa: E402

print("A) meta_paths")
mp = source_refs.meta_paths({"input_reference_image_1": str(NUDE),
                             "input_reference_image_2": str(outside),
                             "input_reference_image_3": ""})
check("inside storage -> relative path",
      mp.get("input_reference_image_1") == "characters/Kira/outfits/Kira_nude.png", f"{mp}")
check("outside storage and empty slots dropped", set(mp) == {"input_reference_image_1"}, f"{mp}")

print("B) reference_paths")
META_NEW = {"reference_paths": {"input_reference_image_1": "characters/Kai/outfits/Kai_a.png",
                                "input_reference_image_2": "world_gallery/loc1/room_a.png",
                                "input_reference_image_3": "characters/Kira/outfits/Kira_nude.png"},
            "reference_images": {"input_reference_image_1": "Kai_a.png",
                                 "input_reference_image_2": "room_a.png",
                                 "input_reference_image_3": "Kira_nude.png"},
            "character_names": ["Kira", "Kai"], "location": "loc1", "room_id": "r1"}
sr = source_refs.source_references(META_NEW)
check("persons from paths", sr["persons"] == {"Kai": str(KAI.resolve()), "Kira": str(NUDE.resolve())},
      f"{sr}")
check("room from paths", sr["room"] == str(ROOM.resolve()), f"{sr}")

print("C) file names only")
META_OLD = {k: v for k, v in META_NEW.items() if k != "reference_paths"}
so = source_refs.source_references(META_OLD)
check("old meta resolves the same files", so == sr, f"{so}")

print("D) missing and hostile entries")
sd = source_refs.source_references({
    "reference_paths": {"input_reference_image_1": "../" + outside.parent.name + "/x.png",
                        "input_reference_image_2": str(outside)},
    "reference_images": {"input_reference_image_1": "../x.png", "input_reference_image_2": "gone.png",
                         "input_reference_image_3": "Kira_gone.png"},
    "character_names": ["Kira"], "location": "loc1"})
check("nothing resolves", sd == {"persons": {}, "room": ""}, f"{sd}")

# --- regenerate_image with stubs ---------------------------------------------
import app.core.prompt_builder as pb  # noqa: E402
import app.imagegen.service as svc  # noqa: E402
from app.skills import image_regenerate as ir  # noqa: E402


class _P:
    def __init__(self, name):
        self.name, self.appearance, self.is_agent, self.is_user, self.gender = name, "", name == "Kai", False, ""


LIVE = {"Kira": str(DRESS), "Kai": str(KAI), "Luisa": str(LUISA)}


class _FakeBuilder:
    def __init__(self, character_name):
        self.character_name = character_name

    def detect_persons(self, prompt, character_names=None):
        return [_P(n) for n in (character_names or [])]

    def _resolve_person_ref_image(self, p):
        return LIVE.get(p.name, "")

    def _collect_location(self, pv):
        pv.ref_image_room = str(ROOM_NOW)

    def resolve_reference_slots(self, pv, max_slots=0):
        refs = {f"input_reference_image_{i}": path for i, path in sorted(pv.ref_images.items())}
        if pv.ref_image_room:
            refs[f"input_reference_image_{len(refs) + 1}"] = pv.ref_image_room
        return {"reference_images": refs, "has_reference_slots": True}


captured = {}


class _Backend:
    name, api_type, ref_slot_count, model, image_family = "Fake", "fake", 4, "", ""

    def generate(self, prompt, negative, params, log_meta=None):
        captured["refs"] = dict(params.get("reference_images") or {})
        return [b"\x89PNG rendered"]


class _Service:
    enabled = True

    def _wait_for_explicit_backend(self, name):
        return _Backend()

    def _get_instance_config(self, character, b):
        return {}

    def run_on_backend_channel(self, b, fn, **_kw):
        return fn()

    def run_on_backend(self, b, op, character_name=""):
        return op(b), b

    def _generate_image_analysis(self, path, character):
        return ""


pb.PromptBuilder = _FakeBuilder
svc.get_image_service = lambda: _Service()

from app.models.character import _save_single_image_meta, _load_single_image_meta  # noqa: E402
_save_single_image_meta("Kai", SOURCE.name, dict(META_OLD, image_filename=SOURCE.name))


def regen(**kw):
    captured.clear()
    ok, _p, out = ir.regenerate_image(
        "Kai", str(SOURCE), "Kira and Kai in the office", backend_name="Fake",
        character_names=kw.pop("names", ["Kira", "Kai"]), location_id="loc1",
        source_room_id="r1", create_new=True, pose_check=False, **kw)
    return ok, set(captured.get("refs", {}).values()), out


print("E) keep_source_references=True")
ok, refs, out = regen(keep_source_references=True, names=["Kira", "Kai", "Luisa"])
check("render succeeded", ok)
want = {str(NUDE.resolve()), str(KAI.resolve()), str(LUISA), str(ROOM.resolve())}
check("Kira nude, Kai, room_a from the source; Luisa live", refs == want,
      f"{sorted(Path(r).name for r in refs)}")
written = _load_single_image_meta("Kai", Path(out).name)
check("meta reference_paths names those files",
      set(written.get("reference_paths", {}).values()) == {
          "characters/Kira/outfits/Kira_nude.png", "characters/Kai/outfits/Kai_a.png",
          "characters/Luisa/outfits/Luisa_now.png", "world_gallery/loc1/room_a.png"},
      f"{written.get('reference_paths')}")

import app.models.world as world  # noqa: E402
world.get_background_path = lambda loc, room="", strict_room=False: ROOM_NOW

print("F) keep_source_references=False")
ok, refs, _ = regen(keep_source_references=False)
check("live references (dress, room_now)", refs == {str(DRESS), str(KAI), str(ROOM_NOW)},
      f"{sorted(Path(r).name for r in refs)}")

print("G) room picked in the dialog")
ok, refs, _ = regen(keep_source_references=True, room_id="r2")
check("another room resolves live, people keep theirs",
      refs == {str(NUDE.resolve()), str(KAI.resolve()), str(ROOM_NOW)},
      f"{sorted(Path(r).name for r in refs)}")
ok, refs, _ = regen(keep_source_references=True, room_id="r1")
check("the same room keeps room_a", str(ROOM.resolve()) in refs,
      f"{sorted(Path(r).name for r in refs)}")

print("H) callers")
src = {p: (ROOT / p).read_text(encoding="utf-8") for p in (
    "app/core/character_ops.py", "app/routes/instagram.py",
    "app/core/improvements/types/subjects.py", "app/core/scene_photo.py")}
for p in ("app/core/character_ops.py", "app/routes/instagram.py",
          "app/core/improvements/types/subjects.py"):
    check(f"{p} keeps the source references", "keep_source_references=True" in src[p])
check("scene photo renders live", "keep_source_references" not in src["app/core/scene_photo.py"])

print()
if failures:
    print(f"{len(failures)} check(s) FAILED: {failures}")
    sys.exit(1)
print("ALL CHECKS PASSED")
