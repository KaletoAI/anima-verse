#!/usr/bin/env python3
"""Smoke: re-rendering fallback images (improvement type fallback_rerender).

Usage:  ./.venv/bin/python scripts/smoke_fallback_rerender.py

Spec: development_instructions/plan-image-routing.md § 5 + review notes
("Verbesserungstyp"): candidates come from the image meta on every scan
(images with `fallback_from`), nothing is listed; while the intended spec does
not resolve, `apply` raises CandidateBusy (step stays pending); `apply`
renders EXPLICITLY on the backend the intended spec resolves to (no further
fallback, no new marker); done = a replacement with `source_file` = the
candidate and WITHOUT `fallback_from` (portrait: the current profile image
carries no `fallback_from`). Throwaway storage + world DB, fake producers.

PART A — the subject helpers
A1 character "Mara": images a.png (fallback_from {occasion photo,
   intended_spec "Big*", position 0}, prompt "a harbour photo"), b.png (no
   marker, prompt "b"), p.png (the profile image, with a marker) ->
   character_gallery_images("Mara") lists a.png and b.png (not the profile),
   a.png with its fallback_from, b.png with fallback_from None.
A2 character_profile("Mara")["fallback_from"] == p.png's marker.
A1b b.png's meta says character_names [] ("nobody") -> the helper keeps
   [] (not None, which would mean "detect the persons again"); a.png has no
   entry -> None.
A3 regenerate_character_gallery_image("Mara", "a.png", "Big A") calls the
   regenerate producer with backend_name "Big A", create_new True, the stored
   prompt and source_file "a.png"; the new file's meta — written by the REAL
   producer merge (image_regenerate._merge_regen_meta over route_meta(None),
   what an explicit render yields) in ONE write — has source_file "a.png" and
   NO fallback_from although a.png's own meta (its create_new base) has one.
A4 gallery_images(<loc>) carries each image's fallback_from.
A5 regenerate_character_gallery_image with an empty backend raises and never
   reaches the producer (a routed render could land on a fallback again).

PART B — the type
B1 subject character_gallery -> ["gallery:Mara:c.png"]: c.png is a fresh
   marked image; a.png is NOT listed because part A already produced its
   replacement a_v1.png (source_file a.png, no marker) — that is "done";
   b.png carries no marker.
B2 subject character_images -> ["character:Mara"] (p.png is the profile and
   carries a marker).
B3 subject location_gallery -> ["location:<loc>:x.png"].
B4 occasion filter: {"subject": "location_gallery", "occasion": "location"}
   -> [] (x.png's marker says "photo"); occasion "photo" -> the candidate.
B5 apply while "Big*" resolves to nothing (Big A cooling) -> CandidateBusy,
   no producer call.
B6 Big A healthy -> apply("gallery:Mara:c.png") renders EXPLICITLY on
   "Big A" with source_file "c.png"; the next scan no longer lists c.png
   (replacement with source_file c.png and no marker).
B7 apply("character:Mara") runs the REAL regenerate_profile over the fake
   producer: backend "Big A", source p.png, create_new, source_file "p.png";
   the profile is now p_v1.png without a marker -> not listed any more.
B7b the old portrait p.png (still marked) is now a gallery image — it is NOT
   a character_gallery candidate: its replacement is the current profile.
B8 apply("location:<loc>:x.png") -> regenerate_gallery_image(loc, "x.png",
   "Big A").
B9 the type is registered; smoke_improvement_types lists six types.
B10 a marker without an intended spec is a defect, not load: apply raises a
   plain RuntimeError (a failed attempt), never CandidateBusy.
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
STORAGE = Path(tempfile.mkdtemp(prefix="fallback-rerender-"))
os.environ["STORAGE_DIR"] = str(STORAGE)
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="fallback-rerender-clips-")
from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import config, db  # noqa: E402
config.load(STORAGE / "config.json")
db.init_schema()

from app.core.improvements.types import subjects  # noqa: E402
from app.models import world  # noqa: E402
from app.models.character import (add_character_image_metadata,  # noqa: E402
                                  add_character_image_prompt, get_character_images_dir,
                                  get_single_image_meta, save_character_profile,
                                  set_character_profile_image)
from app.skills import image_regenerate  # noqa: E402

FAILS = []


def check(label, got, expected):
    ok = got == expected
    print(f"  {'OK  ' if ok else 'FAIL'} {label}: {got!r}"
          + ("" if ok else f" (expected {expected!r})"))
    if not ok:
        FAILS.append(label)


MARK = {"occasion": "photo", "intended_spec": "Big*", "position": 0}
REGEN_CALLS = []


def fake_regenerate_image(character_name, output_path, original_prompt, **kw):
    """Stands in for the render only. The meta it writes comes from the REAL
    producer merge over the original's meta and route_meta(None) — what the
    producer does after an explicit render — in one write, as the producer
    does. It does not decide the marker itself."""
    from app.imagegen.routing import route_meta
    REGEN_CALLS.append({"name": character_name, "path": Path(output_path).name,
                        "prompt": original_prompt, "backend_name": kw.get("backend_name"),
                        "create_new": kw.get("create_new"),
                        "source_file": kw.get("source_file", "")})
    if not kw.get("backend_name"):
        raise AssertionError("the smoke only fakes EXPLICIT renders")
    new = Path(output_path).with_name(Path(output_path).stem + "_v1.png")
    new.write_bytes(b"\x89PNG fake")
    meta = image_regenerate._merge_regen_meta(
        get_single_image_meta(character_name, Path(output_path).name),
        {"backend": kw.get("backend_name"), "prompt": original_prompt},
        route_meta(None), create_new=bool(kw.get("create_new")),
        orig_filename=Path(output_path).name, now_iso="2026-09-30T00:00:00",
        source_file=kw.get("source_file", ""))
    add_character_image_metadata(character_name, new.name, meta)
    add_character_image_prompt(character_name, new.name, original_prompt)
    return True, original_prompt, str(new)


image_regenerate.regenerate_image = fake_regenerate_image


def make_images():
    save_character_profile("Mara", {"name": "Mara", "appearance": "a tall woman"},
                           create_new=True)
    d = get_character_images_dir("Mara")
    d.mkdir(parents=True, exist_ok=True)
    for fn, prompt, marker in (("a.png", "a harbour photo", MARK), ("b.png", "b", None),
                               ("p.png", "a portrait", MARK)):
        (d / fn).write_bytes(b"\x89PNG fake")
        add_character_image_prompt("Mara", fn, prompt)
        add_character_image_metadata("Mara", fn, {"backend": "Cheap", "fallback_from": marker})
    add_character_image_metadata("Mara", "b.png", {"character_names": []})
    set_character_profile_image("Mara", "p.png")


def part_a():
    print("A) subject helpers")
    make_images()
    rows = {r["filename"]: r for r in subjects.character_gallery_images("Mara")}
    check("A1 listed", sorted(rows), ["a.png", "b.png"])
    check("A1 markers", (rows["a.png"]["fallback_from"], rows["b.png"]["fallback_from"]),
          (MARK, None))
    check("A1b character_names", (rows["a.png"]["character_names"],
                                  rows["b.png"]["character_names"]), (None, []))
    check("A2 profile marker", (subjects.character_profile("Mara") or {}).get("fallback_from"), MARK)
    subjects.regenerate_character_gallery_image("Mara", "a.png", "Big A")
    call = REGEN_CALLS[-1]
    check("A3 producer call", (call["path"], call["backend_name"], call["create_new"],
                               call["prompt"], call["source_file"]),
          ("a.png", "Big A", True, "a harbour photo", "a.png"))
    new_meta = get_single_image_meta("Mara", "a_v1.png")
    check("A3 source_file", new_meta.get("source_file"), "a.png")
    check("A3 no marker inherited from a.png", new_meta.get("fallback_from"), None)
    loc = world.add_location("Harbour", "A small harbour.")["id"]
    g = world.get_gallery_dir(loc)
    g.mkdir(parents=True, exist_ok=True)
    (g / "x.png").write_bytes(b"\x89PNG fake")
    world.save_gallery_prompt(loc, "x.png", "a harbour")
    world.set_gallery_image_meta(loc, "x.png", {"backend": "Cheap", "fallback_from": MARK})
    check("A4 gallery marker", [i["fallback_from"] for i in subjects.gallery_images(loc)], [MARK])
    n = len(REGEN_CALLS)
    try:
        subjects.regenerate_character_gallery_image("Mara", "b.png", "")
        check("A5 empty backend refused", "no exception", "RuntimeError")
    except RuntimeError:
        check("A5 empty backend refused", True, True)
    check("A5 no producer call", len(REGEN_CALLS), n)


def part_b():
    print("B) the type")
    from app.core.improvements import registry
    from app.core.improvements.base import Candidate, CandidateBusy
    import app.core.improvements.types  # noqa: F401 — registers the types
    from app.imagegen import routing
    from app.imagegen import service as service_mod
    from app.imagegen.base import ImageBackend
    from app.imagegen.selection import BackendPool

    class Fake(ImageBackend):
        def __init__(self, name, cost):
            super().__init__(name, "http://localhost", float(cost), "fake", "FAKE_FR_")
            self.category = "img2img"
            self.instance_enabled = True
            self._available = True

        def check_availability(self):
            # The endpoint answers — a running cooldown still wins (`available`).
            self._available = True
            return self.available

        def _generate(self, prompt, negative_prompt, params):
            return [b"x"]

    big, cheap = Fake("Big A", 3), Fake("Cheap", 0)
    svc = service_mod.ImageService()
    svc.enabled = True
    svc._pool = BackendPool([big, cheap], agent_instances_provider=lambda n: {})
    service_mod._service = svc
    routing._character_switches = lambda character: {}

    d = get_character_images_dir("Mara")
    (d / "c.png").write_bytes(b"\x89PNG fake")
    add_character_image_prompt("Mara", "c.png", "c")
    add_character_image_metadata("Mara", "c.png", {"backend": "Cheap", "fallback_from": MARK})

    t = registry.get("fallback_rerender")
    check("B9 registered", t is not None, True)

    def cands(params):
        return [c.key for c in t.find_candidates(t.validate(params))]

    check("B1 gallery", cands({"subject": "character_gallery"}), ["gallery:Mara:c.png"])
    check("B2 portrait", cands({"subject": "character_images"}), ["character:Mara"])
    loc = next(l["id"] for l in subjects.locations() if l.get("name") == "Harbour")
    check("B3 location", cands({"subject": "location_gallery"}), [f"location:{loc}:x.png"])
    check("B4 filter out", cands({"subject": "location_gallery", "occasion": "location"}), [])
    check("B4 filter in", cands({"subject": "location_gallery", "occasion": "photo"}),
          [f"location:{loc}:x.png"])

    big.mark_unhealthy("smoke", 300)
    n = len(REGEN_CALLS)
    try:
        t.apply(Candidate("gallery:Mara:c.png", "c"), t.validate({"subject": "character_gallery"}), "t1")
        check("B5 busy", "no exception", "CandidateBusy")
    except CandidateBusy:
        check("B5 busy", True, True)
    check("B5 no producer call", len(REGEN_CALLS), n)

    big.clear_cooldown()
    t.apply(Candidate("gallery:Mara:c.png", "c"), t.validate({"subject": "character_gallery"}), "t2")
    check("B6 explicit backend", (REGEN_CALLS[-1]["backend_name"], REGEN_CALLS[-1]["source_file"]),
          ("Big A", "c.png"))
    check("B6 done", cands({"subject": "character_gallery"}), [])

    t.apply(Candidate("character:Mara", "Mara"), t.validate({"subject": "character_images"}), "t3")
    call = REGEN_CALLS[-1]
    check("B7 portrait", (call["path"], call["backend_name"], call["create_new"], call["source_file"]),
          ("p.png", "Big A", True, "p.png"))
    check("B7 new profile", (subjects.character_profile("Mara") or {}).get("filename"), "p_v1.png")
    check("B7 done", cands({"subject": "character_images"}), [])
    check("B7b old portrait is no gallery candidate", cands({"subject": "character_gallery"}), [])

    GALLERY_CALLS = []
    subjects.regenerate_gallery_image = lambda loc_id, fn, backend: GALLERY_CALLS.append(
        (loc_id, fn, backend))
    t.apply(Candidate(f"location:{loc}:x.png", "x"), t.validate({"subject": "location_gallery"}), "t4")
    check("B8 location", GALLERY_CALLS, [(loc, "x.png", "Big A")])

    (d / "e.png").write_bytes(b"\x89PNG fake")
    add_character_image_prompt("Mara", "e.png", "e")
    add_character_image_metadata("Mara", "e.png", {"backend": "Cheap", "fallback_from": {
        "occasion": "photo", "intended_spec": "", "position": 0}})
    n = len(REGEN_CALLS)
    try:
        t.apply(Candidate("gallery:Mara:e.png", "e"), t.validate({"subject": "character_gallery"}), "t5")
        got = "no exception"
    except CandidateBusy:
        got = "CandidateBusy"
    except RuntimeError:
        got = "RuntimeError"
    check("B10 marker without spec", (got, len(REGEN_CALLS)), ("RuntimeError", n))


if __name__ == "__main__":
    part_a()
    part_b()
    print()
    if FAILS:
        print(f"{len(FAILS)} check(s) failed: {FAILS}")
        sys.exit(1)
    print("all checks passed")
