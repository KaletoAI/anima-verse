#!/usr/bin/env python3
"""Smoke: the profile a caller already holds reaches the humanoid check of the height phrase, and one figure read
loads the profile at most once (plan docs/superpowers/plans/2026-11-24-figure-poll-caches.md, Task 6).

Usage:
    ./.venv/bin/python scripts/smoke_figure_profile_passthrough.py

Runs without a server, LLM, HTTP, hub or Blender on a throwaway world: ``STORAGE_DIR`` / ``INSTANCE_DIR`` point at
temp dirs and ``paths.init(<tmp>)`` runs BEFORE any world-DB module is imported; a copy of the repo's ``human``
package is discovered so the template features resolve. Fixture: "demo" (template human-roleplay, female, 168 cm)
holds and wears one template piece "Plain Top" ({slots [top], mesh_mode template}).

``app.models.character.get_character_profile`` is patched: it counts every call and raises ``AssertionError`` while
the flag is set (otherwise it calls the real, read-scope-memoised function). Every reader below that imports it
lazily (``is_feature_enabled``, and ``get_character_config`` through its module global) sees the patch.

Expected values, by hand:

[P5] ``height.height_phrase(p, "demo")`` with the flag set. ``height_phrase`` holds ``p`` (height 168 -> not None, so
     it asks ``_is_humanoid(p, "demo")``); with the profile passed on, ``model_refs.is_humanoid(..., profile=p)`` ->
     ``is_feature_enabled(profile=p)`` -> ``get_character_config(profile=p)`` (no load) and the template default
     from ``p["template"]`` (no load) -> 0 calls of ``get_character_profile`` while forbidden, and no exception
     escapes. The phrase equals the one without the flag (a female 168 cm humanoid: the same bucket word both
     times) and is not empty (the height is set).
     Before Task 6 (``height.py:94`` called ``is_humanoid(character_name)`` without the profile) the check loaded the
     profile twice — once in ``get_character_config``, once for the template default. Both raise under the flag and
     both are swallowed (``is_feature_enabled`` fails open to humanoid), so the phrase still matches and only the
     call count shows the reload: 2 forbidden calls, want 0.
[P6] ``figure_build._figure_info("demo", profile=p, build=b)`` (b = a build state with nothing running), the flag
     off, the inner loads counted with ``read_scope.measure`` (tally "profile" sits in ``_load_character_profile``,
     the body behind the read-scope memo, so it counts real DB loads only). Before each run ``figure.invalidate()``,
     so no memo of an earlier run answers.
     - ``_figure_info`` opens a read scope itself: every sub-read asking ``get_character_profile("demo")`` again is
       served from the scope after the first load -> inner loads <= 1.
     - ``_figure_info`` inside an already open ``read_scope.scope()`` (a nested scope reuses the outer one) -> <= 1.
     - The comparison without any scope: the unscoped body ``_figure_info_body``, measured on f61a8d2a0 (the commit
       before this task) at 80 loads (UNSCOPED_LOADS_F61A8D2A0; the run that showed [P5] red). Checked: that pin >= the
       scoped count, today's unscoped count >= 1 (the body does reload the profile — otherwise the scope would have
       nothing to save here) and >= the scoped count. Today's unscoped number is printed, not pinned: any later
       passthrough may lower it (with this task's height passthrough it measured 40 — the height phrase sits on the
       figure path, its two reloads per call are gone).
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="smoke_figure_profile_passthrough_"))
os.environ["STORAGE_DIR"] = str(TMP / "world")
os.environ["INSTANCE_DIR"] = str(TMP / "instance")
os.environ["ANIMATION_CLIPS_DIR"] = str(TMP / "clips")
os.environ["ANIMATION_RIG_FILE"] = str(TMP / "reference.fbx")
for d in ("world", "instance", "clips"):
    (TMP / d).mkdir()

from app.core import paths  # noqa: E402

paths.init(str(TMP / "world"))
paths.init_instance(str(TMP / "instance"))

#: inner profile loads of the unscoped ``_figure_info_body`` on f61a8d2a0 (the [P6] comparison, reported)
UNSCOPED_LOADS_F61A8D2A0 = 80

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("OK   " if ok else "FAIL ") + f"{label}: {got!r}" + ("" if ok else f"  (want {want!r})"))
    if not ok:
        FAILS.append(label)


def main() -> int:
    paths.get_config_path().write_text(json.dumps({"packages": {"enabled": "human"}}), encoding="utf-8")
    (TMP / "instance" / "config.json").write_text("{}", encoding="utf-8")
    from app.core import config
    config.load(paths.get_config_path(), instance_path=TMP / "instance" / "config.json")
    from app.core import db
    db.init_schema()
    plugins = TMP / "plugins"
    shutil.copytree(ROOT / "plugins" / "human", plugins / "human")
    from app.plugins.loader import discover_packages
    discover_packages(plugins, force=True)

    import app.models.character as character
    from app.core import figure, figure_build, height, read_scope
    from app.models import inventory

    human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
             "character_appearance": "slender"}
    check("fixture: demo created", character.save_character_profile("demo", human, create_new=True), True)
    top = inventory.add_item(name="Plain Top", category="outfit_piece", prompt_fragment="plain top",
                             outfit_piece={"slots": ["top"], "outfit_types": ["casual"],
                                           "mesh_mode": "template"})["id"]
    check("fixture: top held", inventory.add_to_inventory("demo", top), True)
    check("fixture: top worn", inventory.equip_piece("demo", top, source="smoke")["status"], "ok")
    p = character.get_character_profile("demo")
    check("fixture: on the pipeline", figure_build.on_pipeline("demo", profile=p), True)

    real = character.get_character_profile
    S = {"forbid": False, "calls": 0, "forbidden": 0}

    def patched(name, *a, **k):
        S["calls"] += 1
        if S["forbid"]:
            S["forbidden"] += 1
            raise AssertionError(f"get_character_profile({name!r}) although the caller holds the profile")
        return real(name, *a, **k)

    character.get_character_profile = patched
    try:
        print("[P5] height phrase with the held profile")
        free = height.height_phrase(p, "demo")
        S.update(forbid=True, forbidden=0)
        try:
            got, err = height.height_phrase(p, "demo"), None
        except Exception as e:  # noqa: BLE001
            got, err = None, repr(e)
        finally:
            S["forbid"] = False
        check("P5 no exception", err, None)
        check("P5 forbidden profile loads", S["forbidden"], 0)
        check("P5 same phrase as without the flag", got, free)
        check("P5 phrase not empty (the height is set)", bool(free), True)

        print("[P6] profile loads of one figure read")
        b = {"running": False, "failed": {}}

        def loads(fn):
            figure.invalidate()
            S["calls"] = 0
            with read_scope.measure() as calls:
                fn()
            return calls.get("profile", 0), S["calls"]

        unscoped, unscoped_calls = loads(lambda: figure_build._figure_info_body("demo", profile=p, build=b))
        scoped, scoped_calls = loads(lambda: figure_build._figure_info("demo", profile=p, build=b))

        def nested():
            with read_scope.scope():
                figure_build._figure_info("demo", profile=p, build=b)
        outer, outer_calls = loads(nested)
        print(f"     unscoped _figure_info_body: {unscoped} loads, {unscoped_calls} calls "
              f"(f61a8d2a0: {UNSCOPED_LOADS_F61A8D2A0} loads); scoped: {scoped} loads, {scoped_calls} calls; "
              f"outer scope: {outer} loads, {outer_calls} calls")
        check("P6 _figure_info loads <= 1", scoped <= 1, True)
        check("P6 _figure_info in an outer scope loads <= 1", outer <= 1, True)
        check("P6 unscoped body reloads (>= 1)", unscoped >= 1, True)
        check("P6 scoped <= unscoped", scoped <= unscoped, True)
        check("P6 f61a8d2a0 pin (80) >= scoped", UNSCOPED_LOADS_F61A8D2A0 >= scoped, True)
    finally:
        character.get_character_profile = real

    print("ALL OK" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
