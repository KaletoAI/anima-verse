#!/usr/bin/env python3
"""Smoke run for the prop PICTURE AREAS — sidecar fields, prompt fragments,
slot kind rule (spec-picture-props.md § 1–3, plan task 3, part 1: no Blender).

Usage:  ./.venv/bin/python scripts/smoke_props_areas.py

No world, no DB, no server: a throwaway props directory in /tmp gets a prop
written through the real store. Every expected value below is derived BY HAND
from the spec, never recorded from a run.

---------------------------------------------------------------------------
[1] SIDECAR ROUND-TRIP: key_areas / areas / area_defaults
---------------------------------------------------------------------------
`create_prop(..., key_areas=["glass", "picture", "picture"])` stores the
requested key colours de-duplicated in the fixed kind order of
`picture_areas.KINDS` = (picture, glass):

    key_areas -> ["picture", "glass"]

A prop without a detection run carries `areas == []` and `area_defaults == {}`
on its record — both fields are ALWAYS present, so no consumer has to know the
difference between "none" and "not detected yet".

`areas` written through `sanitize_areas` reads back identically:

    [{"id": "picture_1", "kind": "picture", "size_m": [0.5, 0.4],
      "normal": [0, 0, 1], "source": "auto", "faces": 48},
     {"id": "glass_1", "kind": "glass", "size_m": [0.3, 0.3],
      "normal": [1, 0, 0], "source": "manual", "faces": 12}]

An unknown kind in `key_areas` is a ValueError (a silently dropped kind would
report "Saved" over a request that reached nothing).

`key_areas` is a prop patch field too (ruling R7), same sanitizer:

    {"key_areas": ["glass"]}   -> stored ["glass"]
    {"key_areas": []}          -> the key is removed (record reads [])
    {"key_areas": ["neon"]}    -> ValueError, sidecar byte-identical

---------------------------------------------------------------------------
[2] area_defaults ARE CHECKED AGAINST THE AREAS
---------------------------------------------------------------------------
`area_defaults` travels the ordinary prop patch (`PROP_PATCH_KEYS`). With the
two areas of [1] stored:

    {"glass_1": {"preset": "glass"}}    -> stored as is
    {"nope": {"preset": "glass"}}       -> ValueError (unknown area)
    {"glass_1": {"preset": "mirror"}}   -> ValueError (preset not in SLOT_PRESETS)
    {"glass_1": {}}                     -> ValueError (a default needs a preset)
    "glass"                             -> ValueError (not an object)

A refused patch leaves the sidecar BYTE-IDENTICAL.

---------------------------------------------------------------------------
[3] detect_slots: THE PREFIX RULE FOR glass
---------------------------------------------------------------------------
A split writes materials `slot_picture_<k>` / `slot_glass_<k>`. The kind rule
of `detect_slots` gains the prefix `glass` -> material:

    ["slot_glass_1", "slot_picture_2"]
        -> [{"name": "glass_1", "kind": "material"},
            {"name": "picture_2", "kind": "image"}]

    "slot_glassy" is NOT a material slot (the prefix has to be the whole
    first token: glass, glass_<k>), "slot_glass" stays one (unchanged rule).

---------------------------------------------------------------------------
[4] compose_prompt APPENDS THE KEY-AREA FRAGMENTS
---------------------------------------------------------------------------
With `key_areas=["picture"]` the composed prompt ends with the picture
fragment of `config.KEY_AREA_PROMPTS` and the negative carries
`config.KEY_AREA_NEGATIVES["picture"]` = "painting, artwork, photo, poster,
landscape in frame". Without `key_areas` neither text appears. `glass`
likewise with the magenta fragment and "transparent glass, reflections".
With both kinds both fragments appear, picture first.
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

WORLD = Path(tempfile.mkdtemp(prefix="prop-areas-smoke-"))
os.environ["STORAGE_DIR"] = str(WORLD)

from app.core import paths  # noqa: E402

paths.init(WORLD)

from app.core import config  # noqa: E402
from app.core import props as store  # noqa: E402

FAILURES = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


class FakeBackend:
    """Just what `compose_prompt` reads off a backend."""
    name = "fake"
    model = ""
    image_family = "keywords"


AREAS = [
    {"id": "picture_1", "kind": "picture", "size_m": [0.5, 0.4],
     "normal": [0, 0, 1], "source": "auto", "faces": 48},
    {"id": "glass_1", "kind": "glass", "size_m": [0.3, 0.3],
     "normal": [1, 0, 0], "source": "manual", "faces": 12},
]


def main() -> int:
    print("[1] sidecar round-trip: key_areas / areas / area_defaults")
    pid = store.create_prop(name="Picture frame", category="decor",
                            key_areas=["glass", "picture", "picture"])["id"]
    meta = store.read_sidecar(pid)
    check("key_areas stored de-duplicated in kind order",
          meta.get("key_areas") == ["picture", "glass"],
          str(meta.get("key_areas")))
    rec = store.get_prop(pid)
    check("the record carries key_areas",
          rec.get("key_areas") == ["picture", "glass"], str(rec.get("key_areas")))
    check("no run yet: areas == []", rec.get("areas") == [], str(rec.get("areas")))
    check("no run yet: area_defaults == {}", rec.get("area_defaults") == {},
          str(rec.get("area_defaults")))
    try:
        store.create_prop(name="Bad", key_areas=["neon"])
        check("an unknown key kind is refused", False, "no ValueError")
    except ValueError as exc:
        check("an unknown key kind is refused", True, str(exc)[:60])
    out = store.update_prop(pid, {"key_areas": ["glass"]})
    check("R7: key_areas is patchable", out.get("key_areas") == ["glass"],
          str(out.get("key_areas")))
    out = store.update_prop(pid, {"key_areas": []})
    check("R7: an empty list removes the key",
          "key_areas" not in out and store.get_prop(pid)["key_areas"] == [],
          str(out.get("key_areas")))
    before = (store._sidecar_path(pid) or Path()).read_text(encoding="utf-8")
    try:
        store.update_prop(pid, {"key_areas": ["neon"]})
        check("R7: an unknown kind is refused", False, "no ValueError")
    except ValueError as exc:
        after = (store._sidecar_path(pid) or Path()).read_text(encoding="utf-8")
        check("R7: an unknown kind is refused, nothing written", after == before,
              str(exc)[:50])
    store.update_prop(pid, {"key_areas": ["picture", "glass"]})
    meta = store.read_sidecar(pid)
    meta[store.AREAS_KEY] = store.sanitize_areas(AREAS)
    store._write_sidecar(pid, meta)
    got = store.get_prop(pid)["areas"]
    check("areas read back as written", got == AREAS, str(got))

    print("\n[2] area_defaults are checked against the areas")
    out = store.update_prop(pid, {"area_defaults": {"glass_1": {"preset": "glass"}}})
    check("a default on an existing area is stored",
          out.get("area_defaults") == {"glass_1": {"preset": "glass"}},
          str(out.get("area_defaults")))
    check("…and on the record",
          store.get_prop(pid)["area_defaults"] == {"glass_1": {"preset": "glass"}})
    before = (store._sidecar_path(pid) or Path()).read_text(encoding="utf-8")
    for label, value in (("an unknown area", {"nope": {"preset": "glass"}}),
                         ("a preset outside SLOT_PRESETS",
                          {"glass_1": {"preset": "mirror"}}),
                         ("a default without preset", {"glass_1": {}}),
                         ("a string instead of an object", "glass")):
        try:
            store.update_prop(pid, {"area_defaults": value})
            check(f"refused: {label}", False, "no ValueError")
        except ValueError as exc:
            after = (store._sidecar_path(pid) or Path()).read_text(encoding="utf-8")
            check(f"refused: {label}", after == before, str(exc)[:60])

    print("\n[3] detect_slots: the prefix rule for glass")
    got = store.detect_slots(["slot_glass_1", "slot_picture_2"])
    check("slot_glass_1 -> material, slot_picture_2 -> image",
          got == [{"name": "glass_1", "kind": "material"},
                  {"name": "picture_2", "kind": "image"}], str(got))
    check("slot_glass stays a material slot",
          store.detect_slots(["slot_glass"]) == [{"name": "glass", "kind": "material"}])
    check("slot_glassy is an image slot (the prefix is a whole token)",
          store.detect_slots(["slot_glassy"]) == [{"name": "glassy", "kind": "image"}],
          str(store.detect_slots(["slot_glassy"])))

    print("\n[4] compose_prompt appends the key-area fragments")
    pic = config.KEY_AREA_PROMPTS["picture"].strip(" ,")
    gl = config.KEY_AREA_PROMPTS["glass"].strip(" ,")
    pic_neg = config.KEY_AREA_NEGATIVES["picture"]
    gl_neg = config.KEY_AREA_NEGATIVES["glass"]
    check("the picture negative is the spec text",
          pic_neg == "painting, artwork, photo, poster, landscape in frame", pic_neg)
    check("the glass negative is the spec text",
          gl_neg == "transparent glass, reflections", gl_neg)
    plain = store.compose_prompt("a wooden frame", FakeBackend())
    check("without key_areas: no picture fragment",
          pic not in plain["prompt"] and pic_neg not in plain["negative"])
    check("without key_areas: no glass fragment",
          gl not in plain["prompt"] and gl_neg not in plain["negative"])
    with_pic = store.compose_prompt("a wooden frame", FakeBackend(),
                                    key_areas=["picture"])
    check("picture: fragment in the prompt", pic in with_pic["prompt"],
          with_pic["prompt"][-90:])
    check("picture: negative addition", pic_neg in with_pic["negative"],
          with_pic["negative"])
    check("picture: no glass text",
          gl not in with_pic["prompt"] and gl_neg not in with_pic["negative"])
    check("picture: the subject is still woven in",
          "wooden frame" in with_pic["prompt"])
    with_gl = store.compose_prompt("a door", FakeBackend(), key_areas=["glass"])
    check("glass: fragment in the prompt", gl in with_gl["prompt"])
    check("glass: negative addition", gl_neg in with_gl["negative"])
    check("glass: no picture text",
          pic not in with_gl["prompt"] and pic_neg not in with_gl["negative"])
    both = store.compose_prompt("a door", FakeBackend(),
                                key_areas=["glass", "picture"])
    check("both: picture fragment before glass",
          0 <= both["prompt"].find(pic) < both["prompt"].find(gl),
          both["prompt"][-200:])
    check("both: both negatives",
          pic_neg in both["negative"] and gl_neg in both["negative"])
    check("style is returned RAW (no fragment)",
          pic not in both["style"] and gl not in both["style"])

    print()
    if FAILURES:
        print(f"FAILED ({len(FAILURES)}): " + "; ".join(FAILURES))
        return 1
    print("ALL GREEN")
    return 0


if __name__ == "__main__":
    sys.exit(main())
