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

Since the image routing the video skill declares NO field: its still frame is
the "photo" occasion (Task 10 removed ``imagegen_backend`` / ``imagegen_model``)
and its animation the "video" occasion (Task 16a removed ``animate_service`` —
a named feature loss; a value still stored in a character's skill file is
ignored, not migrated). ``animate_service`` was the last real ``choice``
field; the generic machinery stays (coordinator ruling) and is exercised in
full through a PROBE skill that exists only in this smoke (SKILL_ID
``smoke_choice_probe``, not a real feature):

    still_backend  choice on image_backends   (the image source)
    alt_video      choice on video_backends   (the video source)
    second_video   choice on video_backends   (the SAME source again ->
                                              computed once)
    note           str                        (a plain field: never flagged)

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
      2a  ``get_config_fields()`` is {} (no per-character setting left),
      2b  (the probe's declaration) every probe default is "" — the empty
          option is "world default" — and every field has a label and a
          description,
      2d  the removed keys are gone from ``_defaults`` AND from the declared
          fields: ``imagegen_workflow`` (ComfyUI relic, a soft backend glob),
          ``imagegen_loras`` (LoRAs come from the character's image
          settings), and since the image routing ``imagegen_backend`` and
          ``imagegen_model`` (the still is routed as occasion "photo"; the
          model override is a named feature loss of the routing spec) and
          ``animate_service`` (the animation is routed as occasion "video"),
      2e  the skill's ``execute`` no longer reads any of the five and builds
          none of ``workflow``/``loras``/``backend``/``model_override`` into
          the image payload, but names ``"occasion": "photo"``; it hands
          ``animate_image`` no ``service=`` (the "video" chain decides) —
          checked on the source, since running it would render an image
          (the run itself: scripts/smoke_image_routing_callers.py F-V5).

[3] THE PAYLOAD of ``build_available_skills`` for a character (skills: the
    video skill + the probe):
      3a  the video skill appears with NO fields (``config_fields`` None),
          the probe with its four,
      3b  ``option_sources`` carries BOTH sources with the lists of [1] —
          one entry per source, not per field,
      3c  a field with no stored value comes back with value "" and
          ``value_unavailable`` False; the str field carries no flag,
      3d  a source is computed at most ONCE per call: three choice fields
          over two sources, ``video_backends`` declared twice (alt_video +
          second_video) -> exactly one call per source (counted through a
          wrapper around ``skill_option_source``).

[4] ROUND TRIP through the ordinary field-wise save path
    (``_update_character_skill_config_route_sync``, the body of
    ``POST /characters/{c}/skills/{skill}``):
      4a  saving the probe's ``alt_video = "VidA"`` comes back as the field's
          ``value`` with ``value_unavailable`` False,
      4b  the probe's own effective config says "VidA" too,
      4c  saving a SECOND field merges instead of replacing (the route reads
          the stored config first): the probe's ``still_backend =
          "ImgPricey"`` then ``note = "qwen-image"`` — both values survive.

[5] A STORED VALUE THE SOURCE NO LONGER OFFERS (backend deleted or offline):
      5a  the probe's ``alt_video = "GoneVid"`` is still the field's ``value``
          (never silently dropped) and is flagged ``value_unavailable``
          True — the UI keeps it selectable, marked "(unavailable)", the
          same spirit as the LoRA library's "(missing)",
      5b  the probe's ``still_backend = "ImgOffline"`` (exists, but down
          right now) is flagged the same way — the list only holds what can
          render now,
      5c  the empty value is NEVER flagged (it is the world default, not a
          dangling pick),
      5d  a stale ``animate_service = "VidA"`` stored in the video skill's
          file (written before Task 16a) is neither offered (the skill still
          lists no fields) nor read (its effective config has no such key).

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
    (The image-routing rewrite of [2] fails on commit 08424378, whose video
    skill still declares imagegen_backend/imagegen_model: 2a and 2d. The
    Task 16a rewrite fails on commit 462007bc, whose video skill still
    declares animate_service: 2a, 2d, 2e, 3a, 5d.)
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


from app.skills.base import BaseSkill  # noqa: E402


class _ProbeSkill(BaseSkill):
    """Exists only in this smoke: declares the field shapes no shipped skill
    has any more (an image choice, two video choices on one source, a str)."""

    SKILL_ID = "smoke_choice_probe"

    def __init__(self):
        super().__init__({})
        self._defaults = {"still_backend": "", "alt_video": "", "second_video": "",
                          "note": ""}

    def get_config_fields(self):
        return {
            "still_backend": {"type": "choice", "options_source": "image_backends",
                              "default": "", "label": "Still", "description": "d"},
            "alt_video": {"type": "choice", "options_source": "video_backends",
                          "default": "", "label": "Alt video", "description": "d"},
            "second_video": {"type": "choice", "options_source": "video_backends",
                             "default": "", "label": "Second video", "description": "d"},
            "note": {"type": "str", "default": "", "label": "Note", "description": "d"},
        }

    def execute(self, *args, **kwargs) -> str:
        return ""


VIDEO_SKILL = VideoGenerationSkill({})
PROBE = _ProbeSkill()
import app.core.dependencies as _deps  # noqa: E402
_deps.get_skill_manager = lambda: _StubManager([VIDEO_SKILL, PROBE])  # type: ignore[assignment]

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
eq("2a no fields", fields, {})
_pfields = PROBE.get_config_fields()
check("2b every probe default is empty",
      all(f["default"] == "" for f in _pfields.values()))
check("2b every probe field has a label and a description",
      all(f.get("label") and f.get("description") for f in _pfields.values()))
for gone in ("imagegen_workflow", "imagegen_loras", "imagegen_backend",
             "imagegen_model", "animate_service"):
    check(f"2d {gone} not in _defaults", gone not in VIDEO_SKILL._defaults)
    check(f"2d {gone} not offered as a field", gone not in fields)
_src = Path(__file__).resolve().parents[1] / "app" / "skills" / "video_generation_skill.py"
_text = _src.read_text(encoding="utf-8")
for gone in ("imagegen_workflow", "imagegen_loras", "imagegen_backend",
             "imagegen_model", "animate_service"):
    check(f"2e execute() no longer reads {gone}", f'cfg.get("{gone}"' not in _text)
for key in ("workflow", "loras", "backend", "model_override"):
    check(f"2e no {key} key in the image payload",
          f'imagegen_input["{key}"]' not in _text)
check("2e the still names its occasion", '"occasion": "photo"' in _text)
check("2e animate_image gets no service (routed)", "service=" not in _text)

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
probe = next((s for s in payload["skills"] if s["skill_id"] == PROBE.SKILL_ID), None)
check("3a the video skill is listed", entry is not None)
eq("3a with no fields", entry["config_fields"], None)
check("3a the probe is listed", probe is not None)
eq("3a with its four fields", sorted(probe["config_fields"]),
   ["alt_video", "note", "second_video", "still_backend"])
eq("3b option_sources keys", sorted(payload["option_sources"]),
   ["image_backends", "video_backends"])
eq("3b image list", names(payload["option_sources"]["image_backends"]),
   ["ImgCheap", "ImgPricey"])
eq("3b video list", names(payload["option_sources"]["video_backends"]),
   ["VidB", "VidA"])
eq("3c unset value", probe["config_fields"]["still_backend"]["value"], "")
eq("3c unset value not flagged",
   probe["config_fields"]["still_backend"]["value_unavailable"], False)
eq("3c unset video value not flagged",
   probe["config_fields"]["alt_video"]["value_unavailable"], False)
check("3c the str field carries no flag",
      "value_unavailable" not in probe["config_fields"]["note"])
eq("3d each source resolved once", sorted(_calls), ["image_backends", "video_backends"])

# ---------------------------------------------------------------------------
print("[4] round trip through the field-wise save route")
from app.routes.characters import (  # noqa: E402
    _update_character_skill_config_route_sync as save_field)

save_field(CHAR, PROBE.SKILL_ID, {"config": {"alt_video": "VidA"}})
payload = character_ops.build_available_skills(CHAR)
probe = next(s for s in payload["skills"] if s["skill_id"] == PROBE.SKILL_ID)
eq("4a stored value returned",
   probe["config_fields"]["alt_video"]["value"], "VidA")
eq("4a offered -> not flagged",
   probe["config_fields"]["alt_video"]["value_unavailable"], False)
eq("4b the skill's effective config",
   PROBE._get_effective_config(CHAR).get("alt_video"), "VidA")

save_field(CHAR, PROBE.SKILL_ID, {"config": {"still_backend": "ImgPricey"}})
save_field(CHAR, PROBE.SKILL_ID, {"config": {"note": "qwen-image"}})
cfg = PROBE._get_effective_config(CHAR)
eq("4c the first field survived the second save", cfg.get("still_backend"), "ImgPricey")
eq("4c the second field is stored", cfg.get("note"), "qwen-image")

# ---------------------------------------------------------------------------
print("[5] a stored value the source no longer offers")
save_field(CHAR, PROBE.SKILL_ID, {"config": {"alt_video": "GoneVid"}})
save_field(CHAR, PROBE.SKILL_ID, {"config": {"still_backend": "ImgOffline"}})
payload = character_ops.build_available_skills(CHAR)
probe = next(s for s in payload["skills"] if s["skill_id"] == PROBE.SKILL_ID)
eq("5a the vanished pick is still returned",
   probe["config_fields"]["alt_video"]["value"], "GoneVid")
eq("5a and flagged",
   probe["config_fields"]["alt_video"]["value_unavailable"], True)
check("5a it is really not in the offered list",
      "GoneVid" not in names(payload["option_sources"]["video_backends"]))
eq("5b an offline backend is flagged too",
   probe["config_fields"]["still_backend"]["value_unavailable"], True)
eq("5b but kept as the value",
   probe["config_fields"]["still_backend"]["value"], "ImgOffline")

save_field(CHAR, PROBE.SKILL_ID, {"config": {"alt_video": ""}})
save_field(CHAR, PROBE.SKILL_ID, {"config": {"still_backend": ""}})
payload = character_ops.build_available_skills(CHAR)
probe = next(s for s in payload["skills"] if s["skill_id"] == PROBE.SKILL_ID)
eq("5c empty is never flagged (video)",
   probe["config_fields"]["alt_video"]["value_unavailable"], False)
eq("5c empty is never flagged (image)",
   probe["config_fields"]["still_backend"]["value_unavailable"], False)

from app.models.character import save_character_skill_config  # noqa: E402
save_character_skill_config(CHAR, "video_generation", {"animate_service": "VidA"})
payload = character_ops.build_available_skills(CHAR)
entry = next(s for s in payload["skills"] if s["skill_id"] == "video_generation")
eq("5d a stale animate_service is not offered", entry["config_fields"], None)
check("5d and not read",
      "animate_service" not in VIDEO_SKILL._get_effective_config(CHAR))

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
