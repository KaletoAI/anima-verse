#!/usr/bin/env python3
"""Smoke: the generic package character panel (core + admin routes + skill listing).

Usage:  ./.venv/bin/python scripts/smoke_character_panels.py

No server, no LLM, no real world: ``STORAGE_DIR``/``INSTANCE_DIR`` point at
temp dirs and ``paths.init`` runs before any world-DB module is imported. The
fake provider is registered in THIS process only, under the fake package id
``smoke-panel-pkg``, and is unregistered at the end (``unregister_owned_providers``).

WHAT IS CHECKED, and where every expected value comes from
----------------------------------------------------------
The fake provider (below) keeps its cards in a dict and records every call.
Expectations are derived by hand from the contract in
``app/core/character_panels.py`` / ``docs/plugins.md`` → "Character panels":

A) ROUTES REQUIRE ADMIN — each of the four route functions in
   ``app/routes/character_panels.py`` carries ``Depends(require_admin)``.

B) 404 — GET for the package ``no-such-pkg`` (no provider) → HTTPException 404;
   GET for the registered package but character ``Nobody`` → 404.

C) DESCRIBE — GET for ``Ada`` with lang ``de``: the provider receives
   ``("Ada", "de")``; the answer is normalized: card ``c1`` keeps its values,
   gets ``hint == ""``/``min is None`` defaults on fields that did not set them,
   ``actions[0] == {"id": "go", "label": "Go", "confirm": "", "primary": True}``.
   An odd lang (``"../x"``) reaches the provider as ``"en"``.

D) SAVE — create with ``{"name": "  Bo ", "count": "7", "pick": ["x", "x", "", "y"],
   "junk": 1}``: provider receives card_id None and exactly
   ``{"name": "Bo", "count": 7, "pick": ["x", "y"]}`` (undeclared ``junk`` dropped,
   strip, int, list dedup). Result ``{"ok": True, "error": "", "card_id": "c2"}``.
   Create with ``name`` empty → ``ok False``, error "Name is required." (English;
   with lang ``de`` "Name fehlt." from de.json),
   provider NOT called. Update ``c1`` with ``count`` 99 (field max 50) →
   error "Count: at most 50.". Update ``c1`` with ``count`` "abc" → error
   "Count: enter a whole number.". Update an unknown card → "This entry no longer
   exists.". Update ``c1`` with ``on`` False → provider receives ``{"on": False}``.
   A provider refusal ``{"ok": False, "error": "taken"}`` comes back verbatim.

E) DELETE / ACTION round trips — delete ``c2`` → provider gets ``("Ada","c2","en")``,
   a following GET has only ``c1``. Action ``go`` on ``c1`` → ``{"ok": True,
   "error": "", "message": "went"}``.

F) PROVIDER EXCEPTION → HTTPException 500 (traceback logged). A describe answer
   with an unknown field type → 500 too.

G) SKILL LISTING — ``character_ops.build_available_skills`` with a stub skill
   manager of three skills: ``s1``/``s2`` belong to the fake package (has a
   panel), ``s3`` to package ``other-pkg`` (no panel), ``s4`` to no package.
   Expected ``panel_package``: s1 = s2 = ``smoke-panel-pkg``, s3 = s4 = ``""``.
   After ``unregister_owned_providers`` the same listing has ``""`` for all.
"""
import inspect
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(tempfile.mkdtemp(prefix="character-panels-smoke-"))
STORAGE = ROOT / "world"
STORAGE.mkdir()
os.environ["STORAGE_DIR"] = str(STORAGE)
os.environ["INSTANCE_DIR"] = str(ROOT / "instance")
os.environ["ANIMATION_CLIPS_DIR"] = str(ROOT / "clips")
os.environ["ANIMATION_RIG_FILE"] = str(ROOT / "rig.fbx")
(STORAGE / "config.json").write_text("{}", encoding="utf-8")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
paths.init_instance(ROOT / "instance")
from app.core import config, db  # noqa: E402
config.load(STORAGE / "config.json")
db.init_schema()

from fastapi import HTTPException  # noqa: E402

from app.core import character_ops, hooks  # noqa: E402
from app.core.auth_dependency import require_admin  # noqa: E402
from app.core.character_panels import panel_capability  # noqa: E402
from app.models.character import save_character_profile  # noqa: E402
from app.routes import character_panels as routes  # noqa: E402

PKG = "smoke-panel-pkg"
FAILURES = []
CHECKED = 0


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'OK ' if ok else 'FAIL'} {label}: {actual!r}" + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


def status_of(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except HTTPException as e:
        return e.status_code
    return 200


class FakeProvider:
    def __init__(self):
        self.calls = []
        self.cards = {"c1": {"name": "Al", "count": 3, "on": True, "pick": []}}
        self.refuse = ""
        self.boom = False
        self.bad_type = False

    def describe(self, character, lang):
        self.calls.append(("describe", character, lang))
        if self.boom:
            raise RuntimeError("provider exploded")
        fields = [
            {"key": "name", "type": "text", "label": "Name", "required": True},
            {"key": "count", "type": "int", "label": "Count", "min": 0, "max": 50, "unit": "min"},
            {"key": "on", "type": "bool", "label": "On"},
            {"key": "pick", "type": "bad" if self.bad_type else "items", "label": "Pick",
             "filter": "outfit"},
        ]
        return {
            "title": "Fake", "intro": "One line.",
            "cards": [{"id": cid, "title": v["name"], "fields": fields, "values": dict(v),
                       "actions": [{"id": "go", "label": "Go", "primary": True}],
                       "deletable": True} for cid, v in self.cards.items()],
            "create": {"label": "New", "fields": fields[:3] + [fields[3]]},
        }

    def save(self, character, card_id, values, lang):
        self.calls.append(("save", character, card_id, values, lang))
        if self.refuse:
            return {"ok": False, "error": self.refuse}
        if card_id is None:
            card_id = f"c{len(self.cards) + 1}"
            self.cards[card_id] = {"name": "", "count": 0, "on": False, "pick": []}
        self.cards[card_id].update(values)
        return {"ok": True, "card_id": card_id}

    def delete(self, character, card_id, lang):
        self.calls.append(("delete", character, card_id, lang))
        self.cards.pop(card_id, None)
        return {"ok": True}

    def action(self, character, card_id, action_id, lang):
        self.calls.append(("action", character, card_id, action_id, lang))
        return {"ok": True, "message": "went"}


def last_call(p, kind):
    return next((c for c in reversed(p.calls) if c[0] == kind), None)


assert save_character_profile("Ada", {"character_name": "Ada", "template": "human-roleplay"},
                              create_new=True)

provider = FakeProvider()
hooks.register_provider(panel_capability(PKG), provider, owner=PKG)
try:
    # ── A) admin dependency ────────────────────────────────────────────────
    print("A) routes require admin")
    for fn in (routes.get_character_panel, routes.save_character_panel,
               routes.delete_character_panel, routes.run_character_panel_action):
        deps = [p.default.dependency for p in inspect.signature(fn).parameters.values()
                if hasattr(p.default, "dependency")]
        check(f"{fn.__name__} depends on require_admin", require_admin in deps, True)

    # ── B) 404 ─────────────────────────────────────────────────────────────
    print("B) 404")
    check("no provider → 404", status_of(routes.get_character_panel, "Ada", "no-such-pkg",
                                         lang="en", _={}), 404)
    check("unknown character → 404", status_of(routes.get_character_panel, "Nobody", PKG,
                                               lang="en", _={}), 404)
    check("save without provider → 404", status_of(
        routes.save_character_panel, "Ada", "no-such-pkg",
        body={"card_id": None, "values": {}}, lang="en", _={}), 404)

    # ── C) describe ────────────────────────────────────────────────────────
    print("C) describe")
    panel = routes.get_character_panel("Ada", PKG, lang="de", _={})
    check("provider got (Ada, de)", last_call(provider, "describe"), ("describe", "Ada", "de"))
    check("card ids", [c["id"] for c in panel["cards"]], ["c1"])
    check("values kept", panel["cards"][0]["values"]["name"], "Al")
    f_name = panel["cards"][0]["fields"][0]
    check("hint default", f_name["hint"], "")
    check("min default", f_name["min"], None)
    check("action normalized", panel["cards"][0]["actions"][0],
          {"id": "go", "label": "Go", "confirm": "", "primary": True})
    check("create label", panel["create"]["label"], "New")
    routes.get_character_panel("Ada", PKG, lang="../x", _={})
    check("odd lang → en", last_call(provider, "describe")[2], "en")

    # ── D) save ────────────────────────────────────────────────────────────
    print("D) save")
    res = routes.save_character_panel(
        "Ada", PKG, body={"card_id": None, "values": {
            "name": "  Bo ", "count": "7", "pick": ["x", "x", "", "y"], "junk": 1}},
        lang="en", _={})
    check("create result", res, {"ok": True, "error": "", "card_id": "c2"})
    check("provider got clean values", last_call(provider, "save"),
          ("save", "Ada", None, {"name": "Bo", "count": 7, "pick": ["x", "y"]}, "en"))

    n_saves = len([c for c in provider.calls if c[0] == "save"])
    res = routes.save_character_panel("Ada", PKG, body={"card_id": None, "values": {"name": " "}},
                                      lang="en", _={})
    check("required empty", res, {"ok": False, "error": "Name is required."})
    res = routes.save_character_panel("Ada", PKG, body={"card_id": None, "values": {"name": ""}},
                                      lang="de", _={})
    check("required empty, German (de.json)", res, {"ok": False, "error": "Name fehlt."})
    res = routes.save_character_panel("Ada", PKG, body={"card_id": "c1", "values": {"count": 99}},
                                      lang="en", _={})
    check("max", res, {"ok": False, "error": "Count: at most 50."})
    res = routes.save_character_panel("Ada", PKG, body={"card_id": "c1", "values": {"count": "abc"}},
                                      lang="en", _={})
    check("not a number", res, {"ok": False, "error": "Count: enter a whole number."})
    res = routes.save_character_panel("Ada", PKG, body={"card_id": "zz", "values": {}},
                                      lang="en", _={})
    check("unknown card", res, {"ok": False, "error": "This entry no longer exists."})
    check("provider not called on refused input",
          len([c for c in provider.calls if c[0] == "save"]), n_saves)
    res = routes.save_character_panel("Ada", PKG, body={"card_id": "c1", "values": {"on": False}},
                                      lang="en", _={})
    check("bool update", last_call(provider, "save")[3], {"on": False})
    provider.refuse = "taken"
    res = routes.save_character_panel("Ada", PKG, body={"card_id": "c1", "values": {"name": "X"}},
                                      lang="en", _={})
    check("provider refusal verbatim", res, {"ok": False, "error": "taken"})
    provider.refuse = ""

    # ── E) delete / action ─────────────────────────────────────────────────
    print("E) delete / action")
    res = routes.delete_character_panel("Ada", PKG, body={"card_id": "c2"}, lang="en", _={})
    check("delete result", res, {"ok": True, "error": ""})
    check("provider got delete", last_call(provider, "delete"), ("delete", "Ada", "c2", "en"))
    panel = routes.get_character_panel("Ada", PKG, lang="en", _={})
    check("cards after delete", [c["id"] for c in panel["cards"]], ["c1"])
    res = routes.run_character_panel_action("Ada", PKG, body={"card_id": "c1", "action_id": "go"},
                                            lang="en", _={})
    check("action result", res, {"ok": True, "error": "", "message": "went"})
    check("provider got action", last_call(provider, "action"), ("action", "Ada", "c1", "go", "en"))

    # ── F) provider errors ─────────────────────────────────────────────────
    print("F) provider errors → 500")
    provider.boom = True
    check("raising provider → 500", status_of(routes.get_character_panel, "Ada", PKG,
                                              lang="en", _={}), 500)
    provider.boom = False
    provider.bad_type = True
    check("unknown field type → 500", status_of(routes.get_character_panel, "Ada", PKG,
                                                lang="en", _={}), 500)
    provider.bad_type = False

    # ── G) skill listing ───────────────────────────────────────────────────
    print("G) skill listing carries panel_package")

    class _Skill:
        ALWAYS_LOAD = False

        def __init__(self, sid):
            self.SKILL_ID = sid
            self.name = sid
            self.description = ""

        def get_config_fields(self):
            return {}

    class _Pkg:
        def __init__(self, pid):
            self.id = pid
            self.capability_label = "Cap " + pid
            self.capability_description = ""

    class _Manager:
        skills = [_Skill("s1"), _Skill("s2"), _Skill("s3"), _Skill("s4")]

    owners = {"s1": _Pkg(PKG), "s2": _Pkg(PKG), "s3": _Pkg("other-pkg")}
    import app.core.dependencies as deps_mod
    import app.plugins.registry as reg_mod
    saved = (deps_mod._skill_manager, reg_mod.package_of_skill, character_ops.skill_dependency_block)
    deps_mod._skill_manager = _Manager()
    reg_mod.package_of_skill = lambda sid: owners.get(sid)
    character_ops.skill_dependency_block = lambda c, s: ""
    try:
        listing = character_ops.build_available_skills("Ada")
        got = {s["skill_id"]: s["panel_package"] for s in listing["skills"]}
        check("panel_package per skill", got, {"s1": PKG, "s2": PKG, "s3": "", "s4": ""})
        hooks.unregister_owned_providers(PKG)
        listing = character_ops.build_available_skills("Ada")
        got = {s["skill_id"]: s["panel_package"] for s in listing["skills"]}
        check("no provider → no panel_package", got, {"s1": "", "s2": "", "s3": "", "s4": ""})
        check("route 404 after unregister", status_of(routes.get_character_panel, "Ada", PKG,
                                                      lang="en", _={}), 404)
    finally:
        deps_mod._skill_manager, reg_mod.package_of_skill, character_ops.skill_dependency_block = saved
finally:
    hooks.unregister_owned_providers(PKG)

print(f"\n{CHECKED - len(FAILURES)}/{CHECKED} checks passed")
if FAILURES:
    print("FAILED:", ", ".join(FAILURES))
    sys.exit(1)
