#!/usr/bin/env python3
"""Smoke run for the generic ``choice`` config field of the Skills tab.

Usage:  ./.venv/bin/python scripts/smoke_skill_choice_fields.py

Runs against a THROWAWAY storage directory — never touches a real world.
``STORAGE_DIR`` and ``ANIMATION_CLIPS_DIR`` are redirected BEFORE any app
module is imported, so ``app.server``'s own ``paths.init()`` lands in the same
temp dir. No server, no network, no image backend is contacted: the pool is a
handful of fake ``ImageBackend`` instances, built the way
``scripts/smoke_backend_enabled.py`` builds them, and
``app.imagegen.service.get_image_service`` is pointed at them.

WHAT THIS IS ABOUT (user decision 2026-09-21, "Punkt 4, Weg A")

``video_generation`` carries per-character settings the React Skills tab could
not show, because its renderer only knew ``bool``/``int``/``float``/``str``/
``locations`` and the skill declared no fields at all (``get_config_fields``
returned ``{}``). The old vanilla-UI window that served them is gone; its three
routes had no caller left. Instead of a second special editor the field
vocabulary grew ONE generic type:

    {"type": "choice", "options_source": "<name>", "default": "", …}

The options do not travel in the declaration — the server resolves the source
name once per request (``character_ops.skill_option_source``) and ships the
lists beside the skills as ``option_sources``.

Hand-derived expectations
===========================================================================
The fake pool (name / media / enabled / available / cost):

    ImgCheap    image  on   up    1.0
    ImgPricey   image  on   up    5.0
    ImgOffline  image  on   DOWN  2.0
    ImgOff      image  OFF  up    0.5
    VidA        video  on   up    3.0
    VidB        video  on   up    0.5
    MeshM       mesh   on   up    1.0

[1] OPTION SOURCES — ``skill_option_source`` filters by media kind AND by
    "enabled and available", and sorts cheapest first (the rule written in
    ``_media_backend_options``):
      1a  ``image_backends`` -> ["ImgCheap", "ImgPricey"]  (1.0 before 5.0;
          ImgOffline is down, ImgOff is switched off, MeshM is no image)
      1b  ``video_backends`` -> ["VidB", "VidA"]           (0.5 before 3.0)
      1c  an unknown source name -> [] (the field still renders: empty entry
          plus a stored value)
      1d  no image service -> [] for both (nothing to offer, no exception)

[2] THE SKILL'S DECLARATION — read off ``VideoGenerationSkill``:
      2a  ``get_config_fields()`` has exactly the keys
          {imagegen_backend, imagegen_model, animate_service},
      2b  imagegen_backend is ``choice`` on ``image_backends``,
          animate_service is ``choice`` on ``video_backends``,
          imagegen_model is ``str`` (a free-text ``model_override``: the
          backend abstraction has no model list),
      2c  every field's default is "" — the empty option is "world default",
      2d  the two removed keys are gone from ``_defaults`` AND from the
          declared fields: ``imagegen_workflow`` (ComfyUI relic — no backend
          reads a workflow input; the service treats the field as a soft
          backend glob, which merely duplicates ``imagegen_backend``) and
          ``imagegen_loras`` (LoRAs come from the character's image
          settings),
      2e  the skill's ``execute`` no longer builds those two keys into the
          image payload — checked on the source, since running it would
          render an image.

[3] THE PAYLOAD of ``build_available_skills`` for a character:
      3a  the video skill appears with its three fields,
      3b  ``option_sources`` carries BOTH sources with the lists of [1] —
          one entry per source, not per field,
      3c  a field with no stored value comes back with value "" and
          ``value_unavailable`` False,
      3d  a source is computed at most ONCE per call even though two fields
          use two different sources and the same source could be declared
          twice (counted through a wrapper around ``skill_option_source``).

[4] ROUND TRIP through the ordinary field-wise save path
    (``_update_character_skill_config_route_sync``, the body of
    ``POST /characters/{c}/skills/{skill}``):
      4a  saving ``imagegen_backend = "ImgPricey"`` comes back as the field's
          ``value`` with ``value_unavailable`` False,
      4b  the skill's own effective config says "ImgPricey" too — the value
          the render would use,
      4c  saving a SECOND field merges instead of replacing (the route reads
          the stored config first): both values survive.

[5] A STORED VALUE THE SOURCE NO LONGER OFFERS (backend deleted or offline):
      5a  ``animate_service = "GoneVid"`` is still the field's ``value``
          (never silently dropped) and is flagged ``value_unavailable``
          True — the UI keeps it selectable, marked "(unavailable)", the
          same spirit as the LoRA library's "(missing)",
      5b  ``imagegen_backend = "ImgOffline"`` (exists, but down right now) is
          flagged the same way — the list only holds what can render now,
      5c  the empty value is NEVER flagged (it is the world default, not a
          dangling pick).

[6] ROUTE INVENTORY of ``app.server.app`` — the three routes that served the
    old window are gone and the generic ones are there:
      6a  GET  /characters/{character_name}/skills/image_generation/workflows  absent
      6b  GET  /characters/{character_name}/skills/video_generation/options    absent
      6c  POST /characters/{character_name}/skills/video_generation/config     absent
      6d  GET  /characters/{character_name}/skills/available                   present
      6e  GET/POST /characters/{character_name}/skills/{skill_name} + the
          enabled PUT                                                          present
      6f  ``character_ops`` no longer defines ``build_imagegen_workflows``,
          ``build_videogen_options``, ``apply_videogen_config``.

FAILS BEFORE THE CHANGE
    Verified against commit 2b445fbbd238082035d4dff8b85afc224a134abf: this
    file was run over a source tree whose ``app/`` carries the OLD
    ``skills/video_generation_skill.py``, ``core/character_ops.py`` and
    ``routes/characters.py`` (``git show <hash>:<file>``, everything else
    symlinked). It aborts in [1a] with
    ``AttributeError: module 'app.core.character_ops' has no attribute
    'skill_option_source'``. The same tree, questioned directly, answers:
    ``get_config_fields() == {}`` (so [2] and [3a] could not hold),
    ``_defaults`` still carries ``imagegen_workflow`` + ``imagegen_loras``
    ([2d]), ``build_imagegen_workflows`` / ``build_videogen_options`` /
    ``apply_videogen_config`` all exist ([6f]) and all three routes are in
    the route tree ([6a-c]).
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="skillchoice-smoke-"))
os.environ["STORAGE_DIR"] = str(STORAGE)
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="skillchoice-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import db  # noqa: E402
db.init_schema()

from app.core import character_ops  # noqa: E402
from app.imagegen import service as imgservice  # noqa: E402
from app.imagegen.base import ImageBackend  # noqa: E402
from app.models.character import save_character_profile  # noqa: E402
from app.skills.video_generation_skill import VideoGenerationSkill  # noqa: E402

FAILURES = []


def check(label, ok, detail=""):
    print(f"  [{'ok' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAILURES.append(label)


def eq(label, got, expected):
    check(label, got == expected, f"got {got!r}, expected {expected!r}")


class _Fake(ImageBackend):
    """Same shape as the fake in scripts/smoke_backend_enabled.py."""

    def __init__(self, name, *, media="image", enabled=True, available=True,
                 cost=1.0):
        super().__init__(name, "http://localhost", cost, "fake", "FAKE_")
        self.MEDIA_TYPE = media
        self.instance_enabled = enabled
        self.available = available

    def check_availability(self) -> bool:
        return self.available

    def _generate(self, prompt, negative_prompt, params):
        return []


class _FakeService:
    def __init__(self, backends, enabled=True):
        self.backends = backends
        self.enabled = enabled


POOL = [
    _Fake("ImgCheap", cost=1.0),
    _Fake("ImgPricey", cost=5.0),
    _Fake("ImgOffline", cost=2.0, available=False),
    _Fake("ImgOff", cost=0.5, enabled=False),
    _Fake("VidA", media="video", cost=3.0),
    _Fake("VidB", media="video", cost=0.5),
    _Fake("MeshM", media="mesh", cost=1.0),
]

imgservice.get_image_service = lambda: _FakeService(POOL)  # type: ignore[assignment]


class _StubManager:
    """Only the attribute build_available_skills reads."""

    def __init__(self, skills):
        self.skills = skills


VIDEO_SKILL = VideoGenerationSkill({})
import app.core.dependencies as _deps  # noqa: E402
_deps.get_skill_manager = lambda: _StubManager([VIDEO_SKILL])  # type: ignore[assignment]

CHAR = "Demo"
save_character_profile(CHAR, {"name": CHAR, "description": "smoke character"},
                       create_new=True)


def names(options):
    return [o["value"] for o in options]


# ---------------------------------------------------------------------------
print("[1] option sources")
eq("1a image_backends", names(character_ops.skill_option_source("image_backends")),
   ["ImgCheap", "ImgPricey"])
eq("1b video_backends", names(character_ops.skill_option_source("video_backends")),
   ["VidB", "VidA"])
eq("1c unknown source", character_ops.skill_option_source("nope"), [])
imgservice.get_image_service = lambda: _FakeService(POOL, enabled=False)
eq("1d service off -> image", character_ops.skill_option_source("image_backends"), [])
eq("1d service off -> video", character_ops.skill_option_source("video_backends"), [])
imgservice.get_image_service = lambda: _FakeService(POOL)
check("1  labels mirror the names",
      all(o["value"] == o["label"]
          for o in character_ops.skill_option_source("image_backends")))

# ---------------------------------------------------------------------------
print("[2] what the skill declares")
fields = VIDEO_SKILL.get_config_fields()
eq("2a field keys", sorted(fields), ["animate_service", "imagegen_backend", "imagegen_model"])
eq("2b backend field", (fields["imagegen_backend"]["type"],
                        fields["imagegen_backend"]["options_source"]),
   ("choice", "image_backends"))
eq("2b video field", (fields["animate_service"]["type"],
                      fields["animate_service"]["options_source"]),
   ("choice", "video_backends"))
eq("2b model field is free text", fields["imagegen_model"]["type"], "str")
check("2b model field names no source", "options_source" not in fields["imagegen_model"])
check("2c every default is empty",
      all(f["default"] == "" for f in fields.values()))
check("2c every field has a label and a description",
      all(f.get("label") and f.get("description") for f in fields.values()))
for gone in ("imagegen_workflow", "imagegen_loras"):
    check(f"2d {gone} not in _defaults", gone not in VIDEO_SKILL._defaults)
    check(f"2d {gone} not offered as a field", gone not in fields)
_src = Path(__file__).resolve().parents[1] / "app" / "skills" / "video_generation_skill.py"
_text = _src.read_text(encoding="utf-8")
check("2e execute() no longer reads imagegen_workflow",
      'cfg.get("imagegen_workflow"' not in _text)
check("2e execute() no longer reads imagegen_loras",
      'cfg.get("imagegen_loras"' not in _text)
check("2e no workflow key in the image payload",
      'imagegen_input["workflow"]' not in _text)
check("2e no loras key in the image payload",
      'imagegen_input["loras"]' not in _text)

# ---------------------------------------------------------------------------
print("[3] the skills/available payload")
_calls = []
_real_source = character_ops.skill_option_source


def _counting_source(name):
    _calls.append(name)
    return _real_source(name)


character_ops.skill_option_source = _counting_source
payload = character_ops.build_available_skills(CHAR)
character_ops.skill_option_source = _real_source

entry = next((s for s in payload["skills"] if s["skill_id"] == "video_generation"), None)
check("3a the video skill is listed", entry is not None)
eq("3a with its three fields", sorted(entry["config_fields"]),
   ["animate_service", "imagegen_backend", "imagegen_model"])
eq("3b option_sources keys", sorted(payload["option_sources"]),
   ["image_backends", "video_backends"])
eq("3b image list", names(payload["option_sources"]["image_backends"]),
   ["ImgCheap", "ImgPricey"])
eq("3b video list", names(payload["option_sources"]["video_backends"]),
   ["VidB", "VidA"])
eq("3c unset value", entry["config_fields"]["imagegen_backend"]["value"], "")
eq("3c unset value not flagged",
   entry["config_fields"]["imagegen_backend"]["value_unavailable"], False)
check("3c the str field carries no flag",
      "value_unavailable" not in entry["config_fields"]["imagegen_model"])
eq("3d each source resolved once", sorted(_calls), ["image_backends", "video_backends"])

# ---------------------------------------------------------------------------
print("[4] round trip through the field-wise save route")
from app.routes.characters import (  # noqa: E402
    _update_character_skill_config_route_sync as save_field)

save_field(CHAR, "video_generation", {"config": {"imagegen_backend": "ImgPricey"}})
payload = character_ops.build_available_skills(CHAR)
entry = next(s for s in payload["skills"] if s["skill_id"] == "video_generation")
eq("4a stored value returned",
   entry["config_fields"]["imagegen_backend"]["value"], "ImgPricey")
eq("4a offered -> not flagged",
   entry["config_fields"]["imagegen_backend"]["value_unavailable"], False)
eq("4b the skill's effective config",
   VIDEO_SKILL._get_effective_config(CHAR).get("imagegen_backend"), "ImgPricey")

save_field(CHAR, "video_generation", {"config": {"imagegen_model": "qwen-image"}})
cfg = VIDEO_SKILL._get_effective_config(CHAR)
eq("4c the first field survived the second save", cfg.get("imagegen_backend"), "ImgPricey")
eq("4c the second field is stored", cfg.get("imagegen_model"), "qwen-image")

# ---------------------------------------------------------------------------
print("[5] a stored value the source no longer offers")
save_field(CHAR, "video_generation", {"config": {"animate_service": "GoneVid",
                                                 "imagegen_backend": "ImgOffline"}})
payload = character_ops.build_available_skills(CHAR)
entry = next(s for s in payload["skills"] if s["skill_id"] == "video_generation")
eq("5a the vanished pick is still returned",
   entry["config_fields"]["animate_service"]["value"], "GoneVid")
eq("5a and flagged",
   entry["config_fields"]["animate_service"]["value_unavailable"], True)
check("5a it is really not in the offered list",
      "GoneVid" not in names(payload["option_sources"]["video_backends"]))
eq("5b an offline backend is flagged too",
   entry["config_fields"]["imagegen_backend"]["value_unavailable"], True)
eq("5b but kept as the value",
   entry["config_fields"]["imagegen_backend"]["value"], "ImgOffline")

save_field(CHAR, "video_generation", {"config": {"animate_service": "",
                                                 "imagegen_backend": ""}})
payload = character_ops.build_available_skills(CHAR)
entry = next(s for s in payload["skills"] if s["skill_id"] == "video_generation")
eq("5c empty is never flagged (video)",
   entry["config_fields"]["animate_service"]["value_unavailable"], False)
eq("5c empty is never flagged (image)",
   entry["config_fields"]["imagegen_backend"]["value_unavailable"], False)

# ---------------------------------------------------------------------------
print("[6] route inventory + dead cores")
import app.server as server  # noqa: E402
from fastapi.routing import _IncludedRouter  # noqa: E402


def walk_routes(routes, prefix=""):
    """Flatten the app's route tree (same walk as
    scripts/smoke_admin_controls.py): an ``include_router`` call is ONE
    wrapper node in ``app.routes``, so the ~680 endpoints sit one level
    deeper."""
    for r in routes:
        if isinstance(r, _IncludedRouter):
            ctx = getattr(r, "include_context", None)
            yield from walk_routes(r.original_router.routes,
                                   prefix + (getattr(ctx, "prefix", "") or ""))
        elif getattr(r, "path", None):
            yield prefix + r.path, r


ROUTES = {(m, path) for path, r in walk_routes(server.app.routes)
          for m in (getattr(r, "methods", None) or ())}
check("6  route tree flattened (sanity: > 500 endpoints)", len(ROUTES) > 500,
      f"{len(ROUTES)} method/path pairs")
BASE = "/characters/{character_name}/skills"
for label, method, path in [
    ("6a imagegen workflows", "GET", f"{BASE}/image_generation/workflows"),
    ("6b videogen options", "GET", f"{BASE}/video_generation/options"),
    ("6c videogen config", "POST", f"{BASE}/video_generation/config"),
]:
    check(f"{label} is gone", (method, path) not in ROUTES, path)
for label, method, path in [
    ("6d available", "GET", f"{BASE}/available"),
    ("6e read config", "GET", BASE + "/{skill_name}"),
    ("6e write config", "POST", BASE + "/{skill_name}"),
    ("6e enabled", "PUT", BASE + "/{skill_name}/enabled"),
]:
    check(f"{label} is there", (method, path) in ROUTES, path)
for gone in ("build_imagegen_workflows", "build_videogen_options",
             "apply_videogen_config"):
    check(f"6f character_ops.{gone} is gone", not hasattr(character_ops, gone))

# ---------------------------------------------------------------------------
print()
if FAILURES:
    print(f"FAILED ({len(FAILURES)}): " + ", ".join(FAILURES))
    sys.exit(1)
print("all checks passed")
