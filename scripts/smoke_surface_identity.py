#!/usr/bin/env python3
"""Smoke: the three fields of a surface kind — ID, Name, Description.

Usage:
    ./.venv/bin/python scripts/smoke_surface_identity.py

Runs WITHOUT the server against a throwaway storage dir AND a throwaway
shared dir (the library moved to ``shared/`` in E5 Task 4 — the real one is
the repo, so the smoke redirects ``paths.get_shared_dir``). Checks the three
things that made the old model wrong, with the expected values derived BY
HAND below — not recorded from the current output.

1. slug_for_name — the id a name gets. Worked through by the rule
   "lowercase, accents folded, everything outside [a-z0-9] to '_', trimmed,
   <= 40":

     "dark stone"        -> dark_stone      (one space -> one underscore)
     "Dark Stone"        -> dark_stone      (lowercased first)
     "  Rubber flooring" -> rubber_flooring (outer blanks trimmed)
     "Fluss-Kies!"       -> fluss_kies      ('-' and '!' are separators, the
                                             trailing run is stripped)
     "Flusskies"         -> flusskies       (ss stays ss)
     "Strasse 2b"        -> strasse_2b      (digits are allowed)
     "  ---  "           -> ''              (nothing usable left)
     "2 Meter Gras"      -> 2_meter_gras    (a leading digit is legal)
     "a"*60              -> "a"*40          (cut to the 40-char limit)

2. surface_description — what goes into the prompt. Chain per plan B3:
   description -> name -> the id read back as words. NEVER the raw id, so
   no underscore from an id may appear in any of the four cases.

3. migrate_kind_meta_once — subject becomes description, and a kind that
   relied on the curated map gets that wording WRITTEN OUT, because the map
   stops being a runtime fallback. Expected for the fixture below:
   3 kinds, 1 renamed subject, 2 seeded descriptions, 2 seeded names.
   Its idempotency is content-based (no world flag any more): the second
   run finds every entry complete and returns {}.

   The migration preserves what a kind produced BEFORE; it does not consult
   the name, because the old runtime chain did not either. Creating a NEW
   kind is the other case and does use the name — there is no previous
   result to keep.
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

FAILED: list[str] = []


def check(label: str, got, want) -> None:
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: {got!r}"
          + ("" if ok else f"  (expected {want!r})"))
    if not ok:
        FAILED.append(label)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="smoke-surface-"))
    os.environ.setdefault("ANIMATION_CLIPS_DIR", str(tmp / "clips"))
    from app.core import paths
    paths.init(tmp / "world")
    # The library lives in shared/ since E5 Task 4 — redirect it, the real
    # one is the repo and this smoke writes.
    paths.get_shared_dir = lambda: tmp / "shared"

    from app.core import surface_textures as st

    print("1. slug_for_name")
    for name, want in [
        ("dark stone", "dark_stone"),
        ("Dark Stone", "dark_stone"),
        ("  Rubber flooring", "rubber_flooring"),
        ("Fluss-Kies!", "fluss_kies"),
        ("Flusskies", "flusskies"),
        ("Strasse 2b", "strasse_2b"),
        ("  ---  ", ""),
        ("2 Meter Gras", "2_meter_gras"),
        ("a" * 60, "a" * 40),
    ]:
        check(f"slug({name!r})", st.slug_for_name(name), want)

    print("\n2. surface_description — the prompt chain")
    st.set_kind_meta("dark_stone", name="Dark stone",
                     description="rough dark basalt, fine grain")
    check("description wins", st.surface_description("dark_stone"),
          "rough dark basalt, fine grain")
    st.set_kind_meta("dark_stone", description="")
    check("name is next", st.surface_description("dark_stone"), "Dark stone")
    st.set_kind_meta("dark_stone", name="")
    check("id as words closes the gap", st.surface_description("dark_stone"),
          "the surface of dark stone seen straight from above")
    check("empty id", st.surface_description(""), "a natural ground surface")

    print("\n   no underscore from an id may reach a prompt")
    for kind in ("dark_stone", "rubber_flooring", "gravel"):
        st.set_kind_meta(kind, name="", description="")
        check(f"'_' not in description({kind})",
              "_" in st.surface_description(kind), False)

    print("\n3. ensure_kind_meta seeds instead of falling back")
    st.set_kind_meta("water", name="", description="")
    seeded = st.ensure_kind_meta("water")
    check("curated wording lands in the FIELD", seeded.get("description"),
          st.SURFACE_SUBJECTS["water"])
    check("name defaults to the id as words", seeded.get("name"), "water")
    st.ensure_kind_meta("water", name="Ocean", description="deep blue")
    check("an existing entry is never overwritten",
          st.surface_description("water"), st.SURFACE_SUBJECTS["water"])

    print("\n4. migrate_kind_meta_once")
    # Fixture: one kind with an old subject, one curated kind known only by
    # its file, one custom kind with nothing at all.
    d = st._dir(create=True)
    (d / "kinds.json").write_text(json.dumps({
        "old_kind": {"subject": "worn wooden planks"},
        "custom": {"name": "Custom stuff"},
    }, indent=2), encoding="utf-8")
    (d / "gravel_1780000000.jpg").write_bytes(b"\xff\xd8\xff\xe0stub")
    stats = st.migrate_kind_meta_once()
    check("kinds", stats.get("kinds"), 3)
    check("subject renamed", stats.get("subject_renamed"), 1)
    check("descriptions seeded", stats.get("description_seeded"), 2)
    check("names seeded", stats.get("name_seeded"), 2)

    meta = json.loads((d / "kinds.json").read_text(encoding="utf-8"))
    check("subject key is gone", "subject" in meta["old_kind"], False)
    check("old subject survives as description",
          meta["old_kind"].get("description"), "worn wooden planks")
    check("old kind got a name", meta["old_kind"].get("name"), "old kind")
    check("curated kind carries its wording now",
          meta["gravel"].get("description"), st.SURFACE_SUBJECTS["gravel"])
    # NOT "Custom stuff": the migration writes out what the kind produced
    # before, and the old chain never consulted the name. Preserving beats
    # improving here — the text is now visible and editable.
    check("a kind without curated wording keeps its old phrase",
          meta["custom"].get("description"),
          "the surface of custom seen straight from above")
    check("second run is a no-op", st.migrate_kind_meta_once(), {})

    print("\n5. list_textures carries the name")
    entry = next((e for e in st.list_textures() if e["kind"] == "gravel"), None)
    check("gravel is listed", entry is not None, True)
    check("with its name", (entry or {}).get("name"), "gravel")

    print("\n6. prompt_helper renders with AND without the field context")
    # Jinja runs with StrictUndefined: a new variable that some call site
    # forgets would raise at request time, not here. So render both ways.
    from app.core.prompt_templates import render_task
    _sys, user_with = render_task("prompt_helper", original_prompt="a lawn",
                                  improvement_request="",
                                  field_context="SEAMLESS TILEABLE texture")
    _sys, user_without = render_task("prompt_helper", original_prompt="a lawn",
                                     improvement_request="", field_context="")
    check("context reaches the user message",
          "SEAMLESS TILEABLE texture" in user_with, True)
    check("no context, no empty section",
          "What this prompt renders" in user_without, False)

    print("\n7. the material class (plan-water-rendering.md, Teil A)")
    check("matte needs no entry", st.sanitize_material({"class": "matte"}), None)
    check("an unknown class falls back to matte",
          st.sanitize_material({"class": "lava"}), None)
    water = st.sanitize_material({"class": "water"})
    check("water carries every dial", sorted(water or {}),
          ["class", "flow_speed", "map_strength", "roughness", "sky_mix",
           "speed", "wave_m"])
    # Two speeds, because one cannot serve both: a lake counter-scrolls its two
    # ripple layers (they cancel, the motion reads slow), a river sends both
    # downstream (the same number reads several times faster). `speed` is the
    # still-water metres per second, `flow_speed` the flowing one.
    check("still water keeps its 0.25 m/s", (water or {}).get("speed"), 0.25)
    # 0.5, not 0.15: the dial climbed 0.08 → 0.15 → 0.5. The first two steps
    # kept the flowing number BELOW the lake's 0.25, on the argument that a
    # river's two layers add up while a lake's cancel, so the same number reads
    # several times faster on a river. That premise no longer decides the dial:
    # by user decision (2026-08-25) the default flow is 0.5 m/s, so the ordering
    # is now inverted on purpose — flowing water is dialled FASTER than the lake
    # (0.5 > 0.25), and the layer-addition on top of it is wanted, not a reason
    # to compensate. 0.5 is a quarter of the 2.0 m/s ceiling, so an area still
    # has room to dial both up and down.
    check("...and flowing water is now dialled faster than the lake",
          (water or {}).get("flow_speed"), 0.5)
    clamped = st.sanitize_material({"class": "water", "wave_m": 999,
                                    "speed": -5, "flow_speed": 99, "sky_mix": 2,
                                    "roughness": -1, "map_strength": 7,
                                    "tint": "nonsense"})
    check("wave_m clamped to the max", (clamped or {}).get("wave_m"), 20.0)
    check("speed clamped to the min", (clamped or {}).get("speed"), 0.0)
    check("flow_speed clamped to the max", (clamped or {}).get("flow_speed"), 2.0)
    check("an invalid tint is dropped", "tint" in (clamped or {}), False)
    check("a valid tint is lowercased",
          (st.sanitize_material({"class": "water", "tint": "#1A2B3C"}) or {}).get("tint"),
          "#1a2b3c")
    print("   the other classes carry their OWN fields, nothing else")
    # Only water/ice need a shader, and only because of the motion. gloss and
    # glow are plain material numbers — so a class is the right set of dials
    # under a name, and a spec must never claim one its class ignores.
    ice = st.sanitize_material({"class": "ice"}) or {}
    check("ice stands still by default", ice.get("speed"), 0.0)
    check("...on a current too — ice does not flow", ice.get("flow_speed"), 0.0)
    check("...with a longer swell than water", ice.get("wave_m"), 4.0)
    gloss = st.sanitize_material({"class": "gloss", "wave_m": 9,
                                  "roughness": 0.4, "metalness": 0.9}) or {}
    check("gloss drops the ripple dials", "wave_m" in gloss, False)
    check("...and keeps its own", [gloss.get("roughness"), gloss.get("metalness")],
          [0.4, 0.9])
    glow = st.sanitize_material({"class": "glow", "glow": 99}) or {}
    check("glow is clamped at 5", glow.get("glow"), 5.0)
    check("glow has no roughness dial", "roughness" in glow, False)

    st.set_kind_meta("water", material={"class": "water", "wave_m": 2.5})
    check("stored on the kind",
          ((st.get_kind_meta().get("water") or {}).get("material") or {}).get("wave_m"),
          2.5)
    st.set_kind_meta("water", material={"class": "matte"})
    check("matte clears the declaration",
          "material" in (st.get_kind_meta().get("water") or {}), False)

    print("\n8. the /assets contract endpoint passes the new fields through")
    # The route re-serialises every entry onto an explicit whitelist. That is
    # deliberate for a contract surface — and exactly why `name` and
    # `material` were dropped there after being added to list_textures: the
    # lake rendered its texture and not a drop of water. A field needs BOTH
    # ends, so this checks the far one.
    from app.routes.assets import list_surface_textures
    st.set_kind_meta("gravel", name="Kies",
                     material={"class": "water", "wave_m": 3.0})
    rows = {e["kind"]: e for e in list_surface_textures()}
    check("name reaches the contract", rows.get("gravel", {}).get("name"), "Kies")
    check("material reaches the contract",
          (rows.get("gravel", {}).get("material") or {}).get("wave_m"), 3.0)
    st.set_kind_meta("gravel", material={"class": "matte"})
    rows = {e["kind"]: e for e in list_surface_textures()}
    check("a matte kind carries no material key",
          "material" in rows.get("gravel", {}), False)
    check("the url survives too", bool(rows.get("gravel", {}).get("url")), True)

    shutil.rmtree(tmp, ignore_errors=True)
    print()
    if FAILED:
        print(f"FAILED ({len(FAILED)}): {', '.join(FAILED)}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
