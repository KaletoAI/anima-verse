#!/usr/bin/env python3
"""Ruling A74a: the base prompts carry no safe-content tag, no plain-surface
clause, no anatomy word and none of the pack's "no …" clauses or anatomy
negatives — and the stored bases rendered before it stay current
(app/core/base_body.py, the private pack's ``nsfw_anatomy/plugin.yaml``).

Usage:
    ./.venv/bin/python scripts/smoke_base_prompt_a74a.py

Runs against a THROWAWAY storage directory with a copy of the repo's ``human``
package and — when the private packs repo is checked out next to this one
(``plugins/nsfw_anatomy`` resolves) — the manifest of its ``nsfw_anatomy``
package with ``on_load`` / ``templates`` left out (only its body slots
matter here). No world, no server, no image service, no outbound request:
nothing renders, the stored base set of [3] is written by hand. Without the
packs repo the pack sections print SKIP and the core checks still run.

The words this smoke must not find are never written in it: the core's are
"sfw", "mannequin" and "anatomy" (no body part among them); the pack's are
READ from the pack's manifest as it was before the ruling (``PACK_BEFORE``,
``git -C <packs repo> show``): every comma clause of a ``base_body_negative``
and every clause of a ``base_body_prompt`` that starts with "no ".

Fixture ``Demo`` (template human-roleplay — the template both packages apply
to): female, 30, height 168, skin olive, eyes green, build athletic, profile
image Demo_1.png, and every pack slot with a ``base_body_prompt`` that
applies to a female character valued with the first option of each
attribute its template names (read from today's manifest — this smoke names
no slot of the pack).

[1] Today's texts. APPEARANCE = "female, 30 years old, green eyes, olive
    skin, average height, athletic build" (smoke_base_body_prompt [1]: the
    human build slot carries the height), then the pack's ``base_body_prompt``
    fragments FRAGS in manifest slot order (human sorts before nsfw_anatomy;
    a male-only slot or one without the key adds nothing), each template with
    its placeholders replaced by those values. Block = BALD + ", " + BODY +
    ", " + APPEARANCE + ", " + ", ".join(FRAGS) with BALD = "completely bald
    with a smooth bare scalp", BODY = "an unclothed body with realistic
    natural skin, visible pores, subtle skin tone variation, matte skin".
    Negative of every view = BASE = HAIR_NEG + ", clothing, underwear,
    jewellery, " + POSE_NEG — the pack declares no ``base_body_negative`` any
    more, so nothing follows; the back draft's = HAIR_NEG + ", " + POSE_NEG.
    The FINAL front prompt (base_front style, both families, the block in its
    slot, the pose after it) and every negative: no "sfw", no "mannequin",
    no "anatomy", none of the pack's old terms (case-insensitive substring);
    the block — where a ``base_body_prompt`` lands — has no comma clause
    starting with "no " (a haired front's pose text keeps its own hair clause,
    model_refs.TPOSE_FRONT_HAIR_CLAUSE; Demo is bald); and every one of
    FRAGS stands in the block (the size words are kept).
[2] Fails on the old code: base_body.py of ``BEFORE`` (executed as its own
    module) on the same registry opens the block with "sfw" and has
    "mannequin" in it and "anatomy" in its negative; today's base_body with
    the pack manifest of ``PACK_BEFORE`` registered has a "no " clause in the
    block and every old pack term in the negative. Each of [1]'s checks would
    fail there.
[3] Carry-over (due / cost). With the pack of ``PACK_BEFORE`` registered,
    the old module gives the identity OLD_ID, the fingerprint OLD_FP and the
    texts of the four views; a stored base set is written under the
    signature OLD_ID as ``generate_base_images`` wrote it before the ruling
    (front 10:00, views 10:05; sidecars with ``base_identity`` OLD_ID,
    ``prompt_fingerprint`` OLD_FP, ``prompt``, ``final_prompt``,
    ``negative_prompt`` = use-case negative + ", " + the view's negative,
    ``reference_images`` Demo_1.png, the front's ``skin_step`` record as the
    step writes it; no ``prompt_rules``). Then today's pack again:
      * base_identity != OLD_ID and prompt_fingerprint != OLD_FP — without the
        carry-over this base would be MISSING (a new identity) and its
        fingerprint OLDER_PROMPTS: a full re-render;
      * base_signature == OLD_ID (``_carried_front``), prompts_current True,
        base_prompts_freshness "current", base_view_states all four
        "current", base_refresh_plan reason "" (nothing to refresh).
    A real change still counts:
      * eyes "blue" — a new appearance clause: base_signature != OLD_ID;
      * BODY_TEXT + ", light freckles" — a new clause: prompts_current False;
      * the front sidecar marked ``prompt_rules`` (rendered since): its old
        fingerprint is compared as it is — prompts_current False;
      * the front's skin record without the step (switch off at the time)
        while the switch is on: prompts_current False;
      * a back view whose fingerprint is not the front's: that view stale
        (OLDER_PROMPTS), the others current.
    ``generate_base_images`` records ``"prompt_rules": PROMPT_RULES`` in
    every view's sidecar (source check: the render path needs a backend).
"""
import copy
import inspect
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import types
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

#: The commit of the core before Ruling A74a — never HEAD.
BEFORE = "d1ca15228"
#: The commit of the packs repo before Ruling A74a.
PACK_BEFORE = "bf1128f"

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}" + ("" if ok else f" — expected {want!r}"))
    if not ok:
        FAILS.append(label)


BALD = "completely bald with a smooth bare scalp"
BODY = "an unclothed body with the same skin and body surface as the person in the picture, realistic detailed texture, natural matte look"
APPEARANCE = "female, 30 years old, green eyes, olive skin, average height, athletic build"
HAIR_NEG = ("hair, long hair, short hair, ponytail, braid, bun, fringe, bangs, wig, headscarf, hat, hood, "
            "stubble on the scalp, hair on the shoulders, hair on the back")
POSE_NEG = ("hands touching body, fists, curled fingers, fused fingers, mitten hands, cropped feet, feet cut off, "
            "cropped legs, close-up, portrait crop")
BASE = HAIR_NEG + ", clothing, underwear, jewellery, " + POSE_NEG
DRAFT = HAIR_NEG + ", " + POSE_NEG
CORE_WORDS = ("sfw", "mannequin", "anatomy")
VIEWS = ("front", "back", "left", "right")


def clauses(text):
    return [c.strip() for c in str(text or "").split(",") if c.strip()]


def packs_repo():
    link = ROOT / "plugins" / "nsfw_anatomy"
    if not (link / "plugin.yaml").is_file():
        return None
    real = link.resolve()
    top = subprocess.run(["git", "-C", str(real), "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    return (Path(top.stdout.strip()), real) if top.returncode == 0 else None


def manifest(text):
    import yaml
    data = yaml.safe_load(text)
    data.pop("on_load", None)
    data.pop("templates", None)
    return data


def pack_fragments(data, gender="female"):
    """``({slot id: {attr: value}}, [fragment])`` of the manifest's slots whose
    ``base_body_prompt`` applies to ``gender``: each attribute the template
    names takes its first option."""
    values, fragments = {}, []
    for slot in data.get("body_slots") or []:
        template = str(slot.get("base_body_prompt") or "")
        genders = (slot.get("applies_to") or {}).get("gender")
        if not template or (genders and gender not in genders):
            continue
        chosen = {attr: str((spec.get("options") or [""])[0]) for attr, spec in (slot.get("attributes") or {}).items()
                  if "{" + attr + "}" in template}
        for attr, value in chosen.items():
            template = template.replace("{" + attr + "}", value)
        values[slot["id"]], fragments = chosen, fragments + [template]
    return values, fragments


def old_pack_terms(old):
    """(negative terms, "no …" clauses) of the manifest before the ruling."""
    negatives, nos = [], []
    for slot in old.get("body_slots") or []:
        negatives += clauses(slot.get("base_body_negative"))
        nos += [c for c in clauses(slot.get("base_body_prompt")) if c.lower().startswith("no ")]
    return negatives, nos


def final_prompt(config, family, block, prompt):
    style = config.get_use_case_prompts("base_front", family, clothed=False, character=block)["prompt_style"]
    return config.join_style_prompt(style, prompt, block)


def has_word(text, word):
    return re.search(rf"\b{re.escape(word)}\b", text, re.IGNORECASE) is not None


def main() -> int:
    repo = packs_repo()
    with tempfile.TemporaryDirectory(prefix="a74a-") as tmp:
        root = Path(tmp)
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        enabled = "human,nsfw_anatomy" if repo else "human"
        paths.get_config_path().write_text(json.dumps({"packages": {"enabled": enabled},
                                                       "base_body": {"hairstyle_default_mode": "hairdeck"}}))
        from app.core import config
        config.load(paths.get_config_path(), instance_path=root / "instance/config.json")
        from app.core import db
        db.init_schema()
        from app.plugins.loader import discover_packages

        new_plugins, old_plugins = root / "plugins_new", root / "plugins_old"
        for plugins in (new_plugins, old_plugins):
            shutil.copytree(ROOT / "plugins" / "human", plugins / "human")
        old_terms, old_nos, pack_values, frags = [], [], {}, []
        if repo:
            top, real = repo
            today = manifest((real / "plugin.yaml").read_text(encoding="utf-8"))
            rel = real.relative_to(top) / "plugin.yaml"
            old = manifest(subprocess.run(["git", "-C", str(top), "show", f"{PACK_BEFORE}:{rel.as_posix()}"],
                                          capture_output=True, text=True, check=True).stdout)
            for plugins, data in ((new_plugins, today), (old_plugins, old)):
                (plugins / "nsfw_anatomy").mkdir()
                (plugins / "nsfw_anatomy" / "plugin.yaml").write_text(json.dumps(data))
            old_terms, old_nos = old_pack_terms(old)
            pack_values, frags = pack_fragments(today)
        else:
            print("  SKIP the private packs repo is not checked out — the pack checks are skipped")
        discover_packages(new_plugins, force=True)

        from app.core import base_body, base_skin, model_overview
        from app.core.model_refs import get_model_refs_dir
        from app.models.character import get_character_images_dir, get_character_profile, save_character_profile

        name = "Demo"
        slots = {"skin": {"tone": "olive"}, "eyes": {"color": "green"}, "build": {"type": "athletic"}}
        slots.update(pack_values)
        check("create", save_character_profile(name, {"template": "human-roleplay", "gender": "female", "age": 30,
                                                      "height": 168, "body_slots": slots}, create_new=True), True)
        images = get_character_images_dir(name)
        images.mkdir(parents=True, exist_ok=True)
        (images / "Demo_1.png").write_bytes(b"\x89PNG" + b"a" * 100)
        stored = get_character_profile(name)
        stored["profile_image"] = "Demo_1.png"
        check("save image", save_character_profile(name, stored), True)
        prof = get_character_profile(name)

        print("[1] today's texts")
        appearance = ", ".join([APPEARANCE, *frags])
        block = base_body.base_character(name, "front", profile=prof)
        check("block", block, f"{BALD}, {BODY}, {appearance}")
        if repo:
            check("the pack's fragments read", len(frags) > 0, True)
            check("the size words stay", all(f in block for f in frags), True)
        texts = [block]
        for view in VIEWS:
            prompt, negative = base_body.base_prompt(name, view, profile=prof)
            check(f"{view} negative", negative, BASE)
            texts += [prompt, negative]
        draft_negative = base_body.draft_prompt(name, "back", profile=prof)[1]
        check("draft negative", draft_negative, DRAFT)
        texts.append(draft_negative)
        front_prompt = base_body.base_prompt(name, "front", profile=prof)[0]
        for family in ("natural", "keywords"):
            texts.append(final_prompt(config, family, block, front_prompt))
        joined = " | ".join(texts)
        for word in CORE_WORDS:
            check(f"no {word!r}", has_word(joined, word), False)
        check("no clause starting with 'no ' in the block",
              [c for c in clauses(block) if c.lower().startswith("no ")], [])
        if repo:
            check("the pack's old terms read", (len(old_terms) > 0, len(old_nos) > 0), (True, True))
            check("none of the pack's old terms",
                  [t for t in (*old_terms, *old_nos) if t.lower() in joined.lower()], [])

        print(f"[2] fails on the old code ({BEFORE}, pack {PACK_BEFORE})")
        old_src = subprocess.run(["git", "show", f"{BEFORE}:app/core/base_body.py"], cwd=ROOT,
                                 capture_output=True, text=True, check=True).stdout
        old_bb = types.ModuleType("base_body_" + BEFORE)
        old_bb.__file__ = f"base_body_{BEFORE}.py"
        exec(compile(old_src, old_bb.__file__, "exec"), old_bb.__dict__)
        old_block = old_bb.base_character(name, "front", profile=prof)
        old_negative = old_bb.base_prompt(name, "front", profile=prof)[1]
        check("old block opens with the tag, names the dummy",
              (clauses(old_block)[0] == "sfw", has_word(old_block, "mannequin")), (True, True))
        check("old negative has the anatomy word", has_word(old_negative, "anatomy"), True)
        if repo:
            discover_packages(old_plugins, force=True)
            block_p = base_body.base_character(name, "front", profile=prof)
            negative_p = base_body.base_prompt(name, "front", profile=prof)[1]
            check("old pack: a 'no ' clause in the block",
                  any(c.lower().startswith("no ") for c in clauses(block_p)), True)
            check("old pack: every old term in the negative",
                  all(t in clauses(negative_p) for t in old_terms), True)

        print("[3] carry-over of a base rendered before the ruling")
        # Still on the pack of PACK_BEFORE (when there is one): the old module's view of the base.
        old_id = old_bb.base_identity(name, profile=prof)
        old_fp = old_bb.prompt_fingerprint(name, profile=prof)
        refs = get_model_refs_dir(name)
        refs.mkdir(parents=True, exist_ok=True)
        skin_part = base_skin.fingerprint_part(prof)
        skin_record = ({**skin_part, "applied": True, "outcome": "applied"} if skin_part
                       else {"applied": False, "outcome": "off"})
        from PIL import Image
        for view in VIEWS:
            prompt, negative = old_bb.base_prompt(name, view, profile=prof)
            use_case = base_body.BASE_USE_CASES[view]
            uc = config.get_use_case_prompts(use_case, "natural", clothed=False)
            final = final_prompt(config, "natural", old_bb.base_character(name, view, profile=prof), prompt) \
                if view == "front" else prompt
            meta = {"created_at": "2026-11-14T10:00:00+00:00" if view == "front" else "2026-11-14T10:05:00+00:00",
                    "base_signature": old_id, "base_identity": old_id, "prompt_fingerprint": old_fp,
                    "prompt": prompt, "final_prompt": final,
                    "negative_prompt": ", ".join(p for p in (uc["prompt_negative"], negative) if p),
                    "reference_images": {"input_reference_image_1": "Demo_1.png"}}
            if view == "front":
                meta["skin_step"] = skin_record
            stem = refs / (f"tpose_{old_id}" if view == "front" else f"tpose_{view}_{old_id}")
            Image.new("RGBA", (8, 8), (128, 128, 128, 255)).save(stem.with_suffix(".png"))
            stem.with_suffix(".json").write_text(json.dumps(meta))
        discover_packages(new_plugins, force=True)
        prof = get_character_profile(name)
        if repo:
            check("identity changed (would be MISSING)", base_body.base_identity(name, profile=prof) != old_id, True)
        check("fingerprint changed (would be OLDER_PROMPTS)",
              base_body.prompt_fingerprint(name, profile=prof) != old_fp, True)
        check("base_signature carried", base_body.base_signature(name, profile=prof), old_id)
        check("prompts_current", base_body.prompts_current(name, old_id, profile=prof), True)
        check("freshness", base_body.base_prompts_freshness(name, profile=prof)["state"], model_overview.CURRENT)
        check("view states", {v: s["state"] for v, s in base_body.base_view_states(name, profile=prof).items()},
              {v: model_overview.CURRENT for v in VIEWS})
        check("refresh plan", base_body.base_refresh_plan(name, profile=prof)["reason"], "")

        blue = copy.deepcopy(prof)
        blue["body_slots"]["eyes"]["color"] = "blue"
        check("eyes blue: a new body", base_body.base_signature(name, profile=blue) != old_id, True)
        with patch.object(base_body, "BODY_TEXT", base_body.BODY_TEXT + ", light freckles"):
            check("a clause added: stale", base_body.prompts_current(name, old_id, profile=prof), False)
        front_json = refs / f"tpose_{old_id}.json"
        original = front_json.read_text()
        front_json.write_text(json.dumps({**json.loads(original), "prompt_rules": base_body.PROMPT_RULES}))
        check("marked: fingerprint only", base_body.prompts_current(name, old_id, profile=prof), False)
        if skin_part:
            front_json.write_text(json.dumps({**json.loads(original),
                                              "skin_step": {"applied": False, "outcome": "off"}}))
            check("skin step since switched on: stale", base_body.prompts_current(name, old_id, profile=prof),
                  False)
        front_json.write_text(original)
        back_json = refs / f"tpose_back_{old_id}.json"
        back_json.write_text(json.dumps({**json.loads(back_json.read_text()), "prompt_fingerprint": "0" * 12}))
        states = base_body.base_view_states(name, profile=prof)
        check("a back of another render: stale, the rest current",
              ({v: s["state"] for v, s in states.items()}, states["back"].get("reason")),
              ({"front": model_overview.CURRENT, "back": model_overview.STALE, "left": model_overview.CURRENT,
                "right": model_overview.CURRENT}, base_body.OLDER_PROMPTS))
        check("new renders record the rules",
              '"prompt_rules": PROMPT_RULES' in inspect.getsource(base_body.generate_base_images), True)

    if FAILS:
        print(f"FAILED: {', '.join(FAILS)}")
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
