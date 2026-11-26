#!/usr/bin/env python3
"""Smoke: World Dev free mode — the media lane's cost gate (plan
docs/superpowers/plans/2026-11-25-world-dev-free-media.md, Task 5):
``route_check``, ``step_gate``, ``BUILD_STEP_OCCASIONS`` and the per-plan Build gate.

A temp world and instance (paths.init BEFORE any world-DB import), an EMPTY
ANIMATION_CLIPS_DIR; no server, no LLM, no render. The temp instance has NO
image backends and no ``image_generation.routing``. ``get_image_service`` is
replaced by a counting function that raises, so a path that reached the
service (and so a render) fails loudly — (e) asserts it was never called.
The pool the routing evaluates against is the routing module's own test seam
``routing._pool`` (looked up at call time), replaced by an empty pool: the
"no backends" instance without constructing the service. In production
that pool comes from ``get_image_service().pool`` — a read of the backend
configuration, not a render; (e) proves no render path is reached.

Usage:
    ./.venv/bin/python scripts/smoke_world_dev_media_routes.py

WHAT IS CHECKED, and where every expected value comes from
----------------------------------------------------------

Hand derivation from app/imagegen/occasions.py: of the three occasions the
location/portrait steps route, NONE carries a ``default_chain`` — ``location``
(_image(... _WORLD)), ``profile`` (_image(... profile_workflow scope)) and
``mesh_building`` (_mesh(...)) are declared without one; the only occasion
with a default chain is ``upscale`` (["Iris-3B-Upscale", "Real-ESRGAN-CPU"]).
routing.chain_for = the character's own glob (none here) + _rules(occasion) =
config routing[occasion] if present else default_chain else [].

  (a) no routing config, no character glob -> chain_for is [] for all three ->
      route_check gives exactly
      "no routing chain for <occ> — configure it in /admin/settings → Media
      Generation → Routing" for location, profile and mesh_building.
      upscale: chain = its default chain (2 entries), no backend in the pool
      matches either glob -> _config_filter "no_match" for both ->
      intended_entry None -> intended_spec_for "" ->
      "no usable entry in the upscale chain".
  (b) routing {"location": ["fake-*"]} (in memory) -> chain [fake-*], no backend
      matches -> "no usable entry in the location chain"; profile still has no
      chain (the rule is per occasion).
  (c) step_gate order, on the character "Demo Gate" (saved directly) and a
      run in review, step = its portrait StepSpec (occasions ("profile",)):
      media switch off + image_generation.enabled False + paused ->
      "media generation is off for this run" (the run switch wins);
      switch on, enabled False (still paused) ->
      "media generation is disabled (image_generation.enabled)";
      enabled True, paused (task queue set_character_paused) ->
      "automatic generation of Demo Gate is paused — Retry media after Resume";
      not paused -> the route note of "profile" ((a)'s text).
      A build StepSpec with the profile's figure_auto_build False, in the
      AUTOMATIC Build mode (wdm.BUILD_EXPLICIT patched False) ->
      "Build automatically is off for Demo Gate" (before any route check); in
      the lane's mode (BUILD_EXPLICIT True, plan 2026-11-25-world-dev-free-
      complete-characters-budget decision 13) the switch does not apply: the
      real plan of a character without a base body runs the plain body
      (explicit plan), whose first occasion base_front has no chain ->
      the no-chain note of base_front.
      A location step (building-front, occasions ("location",)) ignores the
      character checks: switch on, enabled -> the "location" route note.
  (d) drift guard: the occasion literals the plan's grep finds
      (every catalog occasion literal on a line matching occasion= / occasion:
      "<id>" or run_routed("<id>") in figure_build,
      base_body, garments, garment_hair, model3d, model_refs) PLUS the
      ``*OCCASION* = "<id>"`` constants and DRAFT_OCCASIONS values of the modules
      the Build steps reach (base_body, base_skin, garment_cut_texture,
      footwear_source, accessory_pendant, garment_template_views, garment_images,
      garment_beard, garment_mesh's mesh_occasion) PLUS the occasion of every
      ImageService method a scanned module calls (generate_hair, generate_strands,
      upscale_image — each method's own run_routed literal, read from
      app/imagegen/service.py: hair_mesh, hair_strands, upscale) are all in
      union(BUILD_STEP_OCCASIONS.values()) | OFF_BUILD_OCCASIONS; the set it
      leaves to OFF_BUILD_OCCASIONS is exactly {"tpose", "expression"} (the
      off-pipeline T-pose pass of model_refs, never called from a Build step);
      set(BUILD_STEP_OCCASIONS) == set(figure_build.STEP_ORDER); every
      member is a catalog occasion (occasions.occasion_ids()); every
      (step, occasion) of CONDITIONAL_OCCASIONS is in that step's tuple; the
      module source compiles without a SyntaxWarning (raw docstring).
  (f) per-plan gate: figure_build.plan patched, route_check patched to note
      only ONE occasion X (None otherwise).
      rig_creature: the base-body pipeline is humanoid only
      (base_body.is_base_pipeline), so NO Build step maps to rig_creature —
      asserted (it is in no BUILD_STEP_OCCASIONS value); the per-plan
      property is shown on garment_cut_texture instead (only the cut_texture
      step maps to it, a non-manual step): plan [template, assemble] ->
      step_gate(build) None; plan [template, cut_texture] -> the
      garment_cut_texture note. A real pendant step is manual (PART_MANUAL,
      figure_build._pendant_step) and an automatic Build drops it
      (figure_build.planned_work): X = jewellery_mesh, plan [pendant(manual),
      assemble] -> None (only assemble runs); plan [pendant(manual)] alone ->
      "Demo Gate: " + PART_MANUAL + " (Characters → Figure)". A failed step
      (ruling 7a: an automatic Build skips it): X = mesh_footwear, plan
      [pieces(boots, failed), assemble] -> None; plan [pieces(boots, failed)]
      alone -> the only-failed note naming its label. (The manual-pendant and
      failed-step cases run in the AUTOMATIC mode, BUILD_EXPLICIT patched
      False; in the lane's explicit mode the manual pendant and the failed
      piece run — figure_build._runnable keeps them — so plan [pendant(manual)]
      alone -> "note jewellery_mesh" and plan [pieces(boots, failed)] alone ->
      "note mesh_footwear".) An empty plan ->
      "the figure is already built". An unknown piece kind (item "nope") ->
      "the Build plan of Demo Gate could not be read (...)", never the union. face_retexture (in plain_body only while
      model3d.face_before_rig_planned is True — CONDITIONAL_OCCASIONS): plan
      [plain_body] with the predicate patched False -> None; True -> the
      face_retexture note. A pieces step of a clothing item narrows to
      garment_fill.OCCASIONS["clothing"] = (garment_view, mesh_garment): with
      X = mesh_footwear -> None, X = mesh_garment -> its note. A clothing
      piece in mode shell (made from the body on the CPU) -> only garment_view:
      X = mesh_garment -> None, X = garment_view -> its note.
      Hair (hair_occasions, by the worn hairstyle's mode; get_item patched for
      the hair items, garment_beard.has_facial_hair patched): HairDeck without
      facial hair -> X = garment_view None, X = hair_mesh its note; HairDeck
      with facial hair -> X = garment_view its note; HAAR -> X = hair_strands
      its note, X = hair_mesh None; body -> None for each of hair_mesh,
      garment_view, hair_strands.
      upscale (SOFT_OCCASIONS, empty-chain only): real route_check with
      routing {"upscale": []} -> route_check("upscale", chain_only=True) is
      the no-chain note; without that entry the default chain (2 entries)
      passes chain_only (None) although no entry is usable (a) — so an
      unusable upscale entry never skips a Build. X = upscale: plan
      [pieces(coat)] -> its note; plan [plain_body] (not manual here) face off
      -> None, face on -> its note.
      REAL plan (figure_build.plan and route_check unpatched, routing empty):
      Demo Gate is a fresh humanoid on the base-body pipeline without a base
      body -> ruling 8a: in the AUTOMATIC mode (BUILD_EXPLICIT False)
      plan(explicit=False) is [plain_body] with manual BASE_MISSING, which an
      automatic Build does not run -> step_gate(build)
      == "Demo Gate: No base body yet — Build to create (Characters → Figure)"
      (literal, hand-derived; also == figure.BASE_MISSING's text), NOT
      "the figure is already built". In the lane's explicit mode the plain
      body runs; its first occasion base_front has no chain (no routing
      config) -> the no-chain note of base_front.
      Never raises: generation_pause.is_paused raising -> "the pause of
      automatic generation of Demo Gate could not be read (boom)";
      auto_build_on raising (AUTOMATIC mode) -> "the "Build automatically"
      switch of Demo Gate could not be read (boom)"; in the explicit mode it is
      not read -> the no-chain note of base_front.
      Off-pipeline mesh (character_mesh_occasions): a humanoid (rig mixamo,
      no extra views — humanoids default off — face off) ->
      ["tpose", "mesh_humanoid", "rig_humanoid"]; rig patched "generic" ->
      ["tpose", "mesh_creature", "rig_creature"] (its own rig only, never the
      other rig occasion).
  (e) get_image_service never called in (a)–(f).
"""
from __future__ import annotations

import atexit
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP = Path(tempfile.mkdtemp(prefix="smoke_wd_media_routes_"))
atexit.register(shutil.rmtree, TMP, ignore_errors=True)
os.environ["ANIMATION_CLIPS_DIR"] = str(TMP / "clips")
os.environ["STORAGE_DIR"] = str(TMP / "world")
os.environ["INSTANCE_DIR"] = str(TMP / "instance")

from app.core import paths  # noqa: E402

paths.init(TMP / "world")

from app.core import db  # noqa: E402

db.init_schema()

import app.imagegen.service as image_service  # noqa: E402

_service_calls = []


def _no_render(*_a, **_k):
    _service_calls.append(1)
    raise AssertionError("render reached")


image_service.get_image_service = _no_render

from app.core import config  # noqa: E402
from app.core import figure_build, model3d  # noqa: E402
from app.core import world_dev_media as wdm  # noqa: E402
from app.core import world_dev_runs as wr  # noqa: E402
from app.core.task_queue import get_task_queue  # noqa: E402
from app.imagegen import occasions, routing  # noqa: E402
from app.models.character import save_character_profile  # noqa: E402

routing._pool = lambda pool=None: pool if pool is not None else SimpleNamespace(backends=[])

failures = []


def check(label, cond, detail=None):
    print(("  ok   " if cond else "  FAIL ") + label
          + ("" if cond or detail is None else f"   -> {detail!r}"))
    if not cond:
        failures.append(label)


def no_chain(occ):
    return (f"no routing chain for {occ} — configure it in /admin/settings → Media Generation → "
            f"Routing")


def no_entry(occ):
    return f"no usable entry in the {occ} chain"


ig = config._CONFIG.setdefault("image_generation", {})
ig.pop("routing", None)
ig["enabled"] = True

# (a)
print("(a) no routing configured")
for occ in ("location", "profile", "mesh_building"):
    check(f"(a) {occ}: no chain", wdm.route_check(occ) == no_chain(occ), wdm.route_check(occ))
check("(a) upscale: default chain, nothing matches", wdm.route_check("upscale") == no_entry("upscale"),
      wdm.route_check("upscale"))

# (b)
print("(b) a chain without a usable entry")
ig["routing"] = {"location": ["fake-*"]}
check("(b) location: no usable entry", wdm.route_check("location") == no_entry("location"),
      wdm.route_check("location"))
check("(b) profile still has no chain", wdm.route_check("profile") == no_chain("profile"),
      wdm.route_check("profile"))
ig.pop("routing", None)

# (c)
print("(c) step_gate order")
NAME = "Demo Gate"
save_character_profile(NAME, {"name": NAME, "template": "human-roleplay", "gender": "female",
                              "age": 30}, create_new=True)
run = wr.create_run("build", "m", "p", "u", 80, 300000)
wr.set_status(run, "awaiting_review")
portrait = wdm.StepSpec("portrait", "portrait", ("profile",), "fp", "portrait")
build = wdm.StepSpec("build", "Figure Build", (), "fp", "build")
front = wdm.StepSpec("building-front", "building front", ("location",), "fp", "gallery")
get_task_queue().set_character_paused(NAME, True)
wr.set_media_enabled(run, False)
ig["enabled"] = False
g = wdm.step_gate(wr.get_run(run), "character", NAME, portrait)
check("(c) run switch off wins", g == "media generation is off for this run", g)
wr.set_media_enabled(run, True)
g = wdm.step_gate(run, "character", NAME, portrait)
check("(c) master switch off next", g == "media generation is disabled (image_generation.enabled)", g)
ig["enabled"] = True
g = wdm.step_gate(run, "character", NAME, portrait)
check("(c) paused next", g == f"automatic generation of {NAME} is paused — Retry media after Resume", g)
get_task_queue().set_character_paused(NAME, False)
g = wdm.step_gate(run, "character", NAME, portrait)
check("(c) then the route note", g == no_chain("profile"), g)
save_character_profile(NAME, {"name": NAME, "template": "human-roleplay", "gender": "female",
                              "age": 30, figure_build.AUTO_BUILD_KEY: False})
wdm.BUILD_EXPLICIT = False
g = wdm.step_gate(run, "character", NAME, build)
check("(c) automatic mode: Build automatically off", g == f"Build automatically is off for {NAME}", g)
wdm.BUILD_EXPLICIT = True
g = wdm.step_gate(run, "character", NAME, build)
check("(c) explicit mode: the switch does not apply -> the plain body's route note",
      g == no_chain("base_front"), g)
g = wdm.step_gate(run, "location", "loc_x", front)
check("(c) a location step: its route note", g == no_chain("location"), g)

# (d)
print("(d) drift guard")
PLAN_GREP = re.compile(r'occasion[=:] *"[a-z_0-9]+"|run_routed\("[a-z_0-9]+"')
CONST = re.compile(r'^[A-Z_]*OCCASION[A-Z_]* *= *"([a-z_0-9]+)"', re.M)
LITERAL = re.compile(r'"([a-z_0-9]+)"')
CATALOG = set(occasions.occasion_ids())


def scan(text):
    """Every catalog occasion literal on a line the plan's grep matches (so the
    conditional form occasion="a" if … else "b" yields both)."""
    out = set()
    for line in text.splitlines():
        if PLAN_GREP.search(line) and not line.lstrip().startswith("#"):
            out.update(x for x in LITERAL.findall(line) if x in CATALOG)
    return out


found = set()
for mod in ("figure_build", "base_body", "garments", "garment_hair", "model3d", "model_refs"):
    found |= scan((ROOT / "app" / "core" / f"{mod}.py").read_text(encoding="utf-8"))
for mod in ("base_body", "base_skin", "garment_cut_texture", "footwear_source", "accessory_pendant",
            "garment_template_views", "garment_images", "garment_beard"):
    text = (ROOT / "app" / "core" / f"{mod}.py").read_text(encoding="utf-8")
    found.update(CONST.findall(text))
    found |= scan(text)
SERVICE_SRC = (ROOT / "app" / "imagegen" / "service.py").read_text(encoding="utf-8")


def method_occasion(method):
    """The run_routed literal inside ImageService.<method>'s own body."""
    body = SERVICE_SRC.split(f"    def {method}(", 1)[1].split("\n    def ", 1)[0]
    return re.search(r"run_routed\(['\"]([a-z_0-9]+)['\"]", body).group(1)


SERVICE_METHODS = {m: method_occasion(m) for m in ("generate_hair", "generate_strands", "upscale_image")}
check("(d) service methods route hair_mesh / hair_strands / upscale",
      SERVICE_METHODS == {"generate_hair": "hair_mesh", "generate_strands": "hair_strands",
                          "upscale_image": "upscale"}, SERVICE_METHODS)
for mod in ("figure_build", "base_body", "garments", "garment_hair", "model3d", "model_refs", "base_skin",
            "garment_cut_texture", "footwear_source", "accessory_pendant", "garment_template_views",
            "garment_images", "garment_beard"):
    text = (ROOT / "app" / "core" / f"{mod}.py").read_text(encoding="utf-8")
    found.update(occ for m, occ in SERVICE_METHODS.items() if f".{m}(" in text)
from app.core import base_body, garment_mesh  # noqa: E402
found.update(base_body.DRAFT_OCCASIONS.values())
found.add(garment_mesh.mesh_occasion("clothing"))
union = set().union(*wdm.BUILD_STEP_OCCASIONS.values())
check("(d) scan found the known literals", {"base_front", "base_view", "outfit_front", "outfit_back_turn",
                                            "outfit_back_draft", "garment_cut_texture", "jewellery_mesh",
                                            "mesh_footwear", "hair_mesh", "hair_strands",
                                            "upscale"} <= found, sorted(found))
check("(d) every literal covered", found <= union | set(wdm.OFF_BUILD_OCCASIONS),
      sorted(found - union - set(wdm.OFF_BUILD_OCCASIONS)))
check("(d) off-Build exactly tpose + expression", found - union == {"tpose", "expression"}
      and set(wdm.OFF_BUILD_OCCASIONS) == {"tpose", "expression"}, sorted(found - union))
check("(d) keys == STEP_ORDER", set(wdm.BUILD_STEP_OCCASIONS) == set(figure_build.STEP_ORDER),
      sorted(set(wdm.BUILD_STEP_OCCASIONS) ^ set(figure_build.STEP_ORDER)))
check("(d) members are catalog occasions", union <= set(occasions.occasion_ids()),
      sorted(union - set(occasions.occasion_ids())))
check("(d) conditional (step, occasion) pairs are members",
      all(occ in wdm.BUILD_STEP_OCCASIONS.get(step, ()) for step, occ in wdm.CONDITIONAL_OCCASIONS),
      sorted(wdm.CONDITIONAL_OCCASIONS))
import warnings  # noqa: E402
with warnings.catch_warnings():
    warnings.simplefilter("error", SyntaxWarning)
    try:
        compile((ROOT / "app" / "core" / "world_dev_media.py").read_text(encoding="utf-8"),
                "world_dev_media.py", "exec")
        _syntax = None
    except SyntaxWarning as e:
        _syntax = str(e)
check("(d) world_dev_media compiles without a SyntaxWarning", _syntax is None, _syntax)

# (f)
print("(f) per-plan gate")
real_route_check, real_plan = wdm.route_check, figure_build.plan
real_face = model3d.face_before_rig_planned
save_character_profile(NAME, {"name": NAME, "template": "human-roleplay", "gender": "female",
                              "age": 30, figure_build.AUTO_BUILD_KEY: True})


def only(occ):
    wdm.route_check = lambda o, character="", **_k: (f"note {o}" if o == occ else None)


def plan_of(*steps):
    figure_build.plan = lambda *_a, **_k: list(steps)


def gate():
    return wdm.step_gate(run, "character", NAME, build)


S = figure_build.Step
check("(f) no Build step maps to rig_creature",
      all("rig_creature" not in v for v in wdm.BUILD_STEP_OCCASIONS.values()), wdm.BUILD_STEP_OCCASIONS)
only("garment_cut_texture")
plan_of(S("template", "t", 0, item_id="i1"), S("assemble", "a", 0))
g = gate()
check("(f) plan without cut_texture -> None", g is None, g)
plan_of(S("template", "t", 0, item_id="i1"), S("cut_texture", "c", 2, item_id="i2"))
g = gate()
check("(f) plan with cut_texture -> its note", g == "note garment_cut_texture", g)
only("jewellery_mesh")
wdm.BUILD_EXPLICIT = False  # the automatic mode: manual and failed steps do not run
plan_of(S("pendant", "p", 1, item_id="i2", manual=figure_build.PART_MANUAL), S("assemble", "a", 0))
g = gate()
check("(f) manual pendant + assemble -> None (only assemble runs)", g is None, g)
plan_of(S("pendant", "p", 1, item_id="i2", manual=figure_build.PART_MANUAL))
g = gate()
check("(f) manual pendant alone -> its manual reason",
      g == f"{NAME}: {figure_build.PART_MANUAL} (Characters → Figure)", g)
plan_of()
g = gate()
check("(f) empty plan -> already built", g == "the figure is already built", g)

from app.models.inventory import add_item, get_item  # noqa: E402
from app.core import garment_set  # noqa: E402


def item_id_of(created):
    return str(created.get("id") if isinstance(created, dict) else created)


coat_id = item_id_of(add_item("Demo Coat", category="outfit_piece",
                              outfit_piece={"slots": ["top"], "mesh_mode": "own_mesh"}))
boots_id = item_id_of(add_item("Demo Boots", category="outfit_piece",
                               outfit_piece={"slots": ["feet"], "mesh_mode": "own_mesh"}))
slip_id = item_id_of(add_item("Demo Slip", category="outfit_piece",
                              outfit_piece={"slots": ["underwear_top"], "mesh_mode": "shell"}))
check("(f) fixture kinds: clothing, footwear, clothing",
      [garment_set.garment_kind_of(get_item(i)) for i in (coat_id, boots_id, slip_id)]
      == ["clothing", "footwear", "clothing"],
      [get_item(i) for i in (coat_id, boots_id, slip_id)])

only("mesh_footwear")
plan_of(S("pieces", "Own mesh · Demo Boots — failed — Retry", 0, item_id=boots_id, failed="mesh refused"),
        S("assemble", "a", 0))
g = gate()
check("(f) failed pieces + assemble -> None (only assemble runs)", g is None, g)
plan_of(S("pieces", "Own mesh · Demo Boots — failed — Retry", 0, item_id=boots_id, failed="mesh refused"))
g = gate()
check("(f) failed pieces alone -> only-failed note",
      g == (f"{NAME}: only failed steps are left (Own mesh · Demo Boots — failed — Retry) — a manual "
            f"Build retries them (Characters → Figure)"), g)
wdm.BUILD_EXPLICIT = True  # the lane's mode: both run
g = gate()
check("(f) explicit: failed pieces alone run -> their note", g == "note mesh_footwear", g)
only("jewellery_mesh")
plan_of(S("pendant", "p", 1, item_id="i2", manual=figure_build.PART_MANUAL))
g = gate()
check("(f) explicit: manual pendant alone runs -> its note", g == "note jewellery_mesh", g)
plan_of(S("pieces", "Own mesh · ?", 3, item_id="nope"))
g = gate()
check("(f) unknown piece kind -> plan-unreadable note",
      isinstance(g, str) and g.startswith(f"the Build plan of {NAME} could not be read ("), g)

only("face_retexture")
plan_of(S("plain_body", "p", 6))
model3d.face_before_rig_planned = lambda *_a, **_k: False
g = gate()
check("(f) face off -> face_retexture not gated", g is None, g)
model3d.face_before_rig_planned = lambda *_a, **_k: True
g = gate()
check("(f) face on -> face_retexture gated", g == "note face_retexture", g)
only("upscale")
g = gate()
check("(f) face on -> the face reference's upscale gated", g == "note upscale", g)
model3d.face_before_rig_planned = lambda *_a, **_k: False
g = gate()
check("(f) face off -> upscale of plain_body not gated", g is None, g)

plan_of(S("pieces", "Own mesh · Demo Coat", 3, item_id=coat_id))
g = gate()
check("(f) clothing piece: upscale gated", g == "note upscale", g)
only("mesh_footwear")
g = gate()
check("(f) clothing piece: footwear chain not gated", g is None, g)
only("mesh_garment")
g = gate()
check("(f) clothing piece: garment mesh gated", g == "note mesh_garment", g)
plan_of(S("pieces", "Own mesh · Demo Slip", 1, item_id=slip_id))
g = gate()
check("(f) shell piece: mesh_garment not gated", g is None, g)
only("garment_view")
g = gate()
check("(f) shell piece: garment_view gated", g == "note garment_view", g)

# Hair, by the worn hairstyle's mode.
import app.models.inventory as inventory_mod  # noqa: E402
from app.core import garment_beard  # noqa: E402
real_get_item, real_beard = inventory_mod.get_item, garment_beard.has_facial_hair
HAIR = {f"hair_{m}": {"id": f"hair_{m}", "category": "garment", "name": m,
                      "garment": {"kind": "hair", "slot": "hair", "mesh_mode": m}}
        for m in ("hairdeck", "haar", "body")}
inventory_mod.get_item = lambda i, *a, **k: HAIR.get(i) or real_get_item(i, *a, **k)


def hair_gate(mode, occ, beard=False):
    garment_beard.has_facial_hair = lambda *_a, **_k: beard
    only(occ)
    plan_of(S("hair", f"Hair · {mode}", 1, item_id=f"hair_{mode}"))
    return gate()


g = hair_gate("hairdeck", "garment_view")
check("(f) HairDeck, no facial hair: garment_view not gated", g is None, g)
g = hair_gate("hairdeck", "hair_mesh")
check("(f) HairDeck: hair_mesh gated", g == "note hair_mesh", g)
g = hair_gate("hairdeck", "garment_view", beard=True)
check("(f) HairDeck with facial hair: garment_view gated", g == "note garment_view", g)
g = hair_gate("haar", "hair_strands")
check("(f) HAAR: hair_strands gated", g == "note hair_strands", g)
g = hair_gate("haar", "hair_mesh")
check("(f) HAAR: hair_mesh not gated", g is None, g)
for occ in ("hair_mesh", "garment_view", "hair_strands"):
    g = hair_gate("body", occ, beard=True)
    check(f"(f) hair in the body: {occ} not gated", g is None, g)
inventory_mod.get_item, garment_beard.has_facial_hair = real_get_item, real_beard
figure_build.plan = real_plan
wdm.route_check = real_route_check

# upscale: empty-chain only.
ig["routing"] = {"upscale": []}
g = wdm.route_check("upscale", chain_only=True)
check("(f) explicit empty upscale chain -> no-chain note", g == no_chain("upscale"), g)
ig.pop("routing", None)
g = wdm.route_check("upscale", chain_only=True)
check("(f) default upscale chain passes chain_only", g is None, g)

# The REAL plan of a fresh character (ruling 8a).
model3d.face_before_rig_planned = real_face
wdm.BUILD_EXPLICIT = False
g = gate()
check("(f) automatic mode, real plan, no base body -> the plain body's manual note",
      g == "Demo Gate: No base body yet — Build to create (Characters → Figure)", g)
wdm.BUILD_EXPLICIT = True
g = gate()
check("(f) explicit mode, real plan, no base body -> the plain body runs: base_front's route note",
      g == no_chain("base_front"), g)
from app.core import figure  # noqa: E402
check("(f) ... which is figure.BASE_MISSING", figure.BASE_MISSING == "No base body yet — Build to create",
      figure.BASE_MISSING)

# Never raises.
from app.core import generation_pause  # noqa: E402
real_paused, real_auto = generation_pause.is_paused, figure_build.auto_build_on


def boom(*_a, **_k):
    raise RuntimeError("boom")


generation_pause.is_paused = boom
g = gate()
check("(f) is_paused raising -> a note", g == f"the pause of automatic generation of {NAME} could not be read (boom)", g)
generation_pause.is_paused = real_paused
figure_build.auto_build_on = boom
wdm.BUILD_EXPLICIT = False
g = gate()
check("(f) automatic mode: auto_build_on raising -> its own note",
      g == f'the "Build automatically" switch of {NAME} could not be read (boom)', g)
wdm.BUILD_EXPLICIT = True
g = gate()
check("(f) explicit mode: auto_build_on not read", g == no_chain("base_front"), g)
figure_build.auto_build_on = real_auto

real_rig = model3d.required_rig
occ = wdm.character_mesh_occasions(NAME)
check("(f) off-pipeline mesh, humanoid", occ == ["tpose", "mesh_humanoid", "rig_humanoid"], occ)
model3d.required_rig = lambda *_a, **_k: "generic"
occ = wdm.character_mesh_occasions(NAME)
check("(f) off-pipeline mesh, own rig only", occ[:1] == ["tpose"] and "mesh_creature" in occ
      and "rig_creature" in occ and "rig_humanoid" not in occ and "mesh_humanoid" not in occ, occ)
model3d.required_rig = real_rig
model3d.face_before_rig_planned = real_face

# (e)
check("(e) get_image_service never reached", not _service_calls, len(_service_calls))

print()
if failures:
    print(f"FAILED: {len(failures)}")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("all ok")
