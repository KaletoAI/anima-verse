# Multi-view mesh input for props, buildings and rooms — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Props and location/room models can be meshed from front + optional back/left/right renders, each view rendered as its own step (optionally with the front image as reference), with one central "Generate 3D model" button for locations.

**Architecture:** A tiny shared vocabulary module (`app/core/view_prompts.py`) maps a view onto a per-view use case (`<base>_back` / `<base>_side`) and a subject prefix; props store view images next to their variant's front image, locations tag gallery images with `building-<view>` types (one-time migration of `building` → `building-front`). The existing `service.generate_mesh(view_images=…)` and the alias slot mapping in `openai_mesh.py` are reused unchanged. The frontend gets a generic **Views** section in `MeshBackendDialog`, a view selector + front-reference toggle in the two image dialogs, and moves the location mesh button from the gallery tile into `BuildingModelPanel`.

**Tech Stack:** Python 3 / FastAPI backend (`app/`), React + TypeScript + Vite admin (`frontend/`), standalone smoke scripts under `scripts/` (no pytest), `npm run lint` / `npm run build` from the repo root.

**Spec:** `docs/superpowers/specs/2026-09-02-multiview-props-locations-design.md`

## Global Constraints

- No `.env`, no environment-variable config; world data stays in `worlds/<world>/` (CLAUDE.md).
- Admin-UI strings are **English** and wrapped in `t()` (React) — new strings get a German entry in `shared/languages/de.json` (Task 12).
- Code comments and docstrings are English; when a touched file still has German comments in the edited region, translate them.
- **No backward-compat shims**: the `building` image type is renamed via the boot migration (Task 3); no code path reads `building` afterwards.
- Never run two image generations in parallel on the same backend — every render goes through `get_llm_queue().submit_gpu_task` / the existing chains; this plan adds no new queue path.
- No `window.prompt/alert/confirm`; modals via `createPortal` to `document.body`.
- Smoke checks derive their expected values **by hand in the docstring**, never from current output.
- Commits: `git add <exact paths>` then `git commit -- <paths>` (shared worktree rule); message ends with
  `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` and
  `Claude-Session: https://claude.ai/code/session_01CpArTbGnVGBNzzobZCiL7R`.
- Run Python via `./.venv/bin/python` from the repo root. Do NOT touch `worlds/demo/world.db` (a running server may hold it).
- Frontend verification is `npm run lint` and `npm run build` (repo root); the built bundle in `static/game_admin/` is committed only in Task 12.

---

### Task 1: Shared view vocabulary + smoke script

**Files:**
- Create: `app/core/view_prompts.py`
- Create: `scripts/smoke_view_types.py`

**Interfaces:**
- Produces (used by Tasks 3–7):
  - `VIEWS: tuple = ("front", "back", "left", "right")`, `EXTRA_VIEWS = ("back", "left", "right")`
  - `is_view(name: Any) -> bool`
  - `view_use_case(base: str, view: str) -> str` — `front → base`, `back → f"{base}_back"`, `left`/`right → f"{base}_side"`; raises `ValueError` on an unknown view.
  - `view_prefix(view: str) -> str` — `""` for front, a phrase otherwise.
  - `view_subject(view: str, subject: str) -> str` — `f"{prefix}, {subject}"` when a prefix exists, else `subject`.
  - `BUILDING_TYPES: tuple = ("building-front", "building-back", "building-left", "building-right")`
  - `building_type(view: str) -> str` (`"building-front"` …), `building_view(image_type: Any) -> str` (`"front"`… or `""` when not a building type).

- [ ] **Step 1: Write the smoke script with the expectations derived by hand**

```python
#!/usr/bin/env python3
"""Smoke run for the view vocabulary shared by props and locations
(app/core/view_prompts.py) and the building-type migration.

No world, no DB, no server. Expectations are worked out by hand from the
design (docs/superpowers/specs/2026-09-02-multiview-props-locations-design.md):

  1. Four views exist: front, back, left, right. Anything else is not a view.
  2. A view picks the use case of a mesh-input render: the FRONT keeps the
     base use case, the BACK gets "<base>_back", LEFT and RIGHT share
     "<base>_side" (the T-pose precedent tpose/tpose_back/tpose_side). This
     holds for every base — prop, building, building_outdoor, room_model,
     room_model_outdoor — with no special case per base.
  3. The front has NO subject prefix; back/left/right each have one, and the
     left and right phrases differ (they share a use case, so the prefix is
     the only thing that tells the mesher's left from its right).
  4. Gallery image types of a location model source are "building-<view>";
     "building" alone is NOT one of them any more (it is migrated away).
  5. The migration rewrite turns every image_types value "building" into
     "building-front", leaves every other value alone, reports whether it
     changed anything, and a second run changes nothing.
  6. A prop's extra views live next to its variant's front image:
     stem "model" -> "source_back.png", stem "model-v2" -> "source-v2_left.png";
     the front keeps its historic name ("source.png" / "source-v2.png").

Expected results:

  (a) view_use_case("prop", "front") == "prop"
      view_use_case("prop", "back") == "prop_back"
      view_use_case("room_model_outdoor", "left") == "room_model_outdoor_side"
      view_use_case("building", "right") == "building_side"
      view_use_case("building", "top") -> ValueError
  (b) view_prefix("front") == "" ; view_prefix(v) != "" for the other three;
      view_prefix("left") != view_prefix("right")
      view_subject("front", "a chair") == "a chair"
      view_subject("back", "a chair") == view_prefix("back") + ", a chair"
  (c) building_type("back") == "building-back"; building_view("building-left") == "left";
      building_view("building") == ""; building_view("day") == ""; is_view("front") is True;
      is_view("building-front") is False
  (d) rewrite_building_types({"image_types": {"a.png": "building", "b.png": "day",
      "c.png": "building-back"}}) -> True and the dict becomes
      {"a.png": "building-front", "b.png": "day", "c.png": "building-back"};
      a second call returns False; a meta without image_types returns False.
  (e) view_source_name("model", "back") == "source_back.png"
      view_source_name("model-v2", "left") == "source-v2_left.png"
      view_source_name("model", "front") == "source.png"
      view_source_name("model-v2", "front") == "source-v2.png"
      view_source_name("bogus", "back") == ""

Usage:  ./.venv/bin/python scripts/smoke_view_types.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FAILURES = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}"
          f"{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


from app.core.view_prompts import (BUILDING_TYPES, EXTRA_VIEWS, VIEWS,  # noqa: E402
                                   building_type, building_view, is_view,
                                   view_prefix, view_subject, view_use_case)

print("\n(a) view -> use case")
check("front keeps the base", view_use_case("prop", "front") == "prop")
check("back gets _back", view_use_case("prop", "back") == "prop_back")
check("left of an outdoor room is _side",
      view_use_case("room_model_outdoor", "left") == "room_model_outdoor_side")
check("right of a building is _side",
      view_use_case("building", "right") == "building_side")
try:
    view_use_case("building", "top")
    check("unknown view raises ValueError", False)
except ValueError:
    check("unknown view raises ValueError", True)
check("VIEWS is front/back/left/right",
      VIEWS == ("front", "back", "left", "right"), str(VIEWS))
check("EXTRA_VIEWS is back/left/right",
      EXTRA_VIEWS == ("back", "left", "right"), str(EXTRA_VIEWS))

print("\n(b) subject prefix")
check("front has no prefix", view_prefix("front") == "")
check("back/left/right have one",
      all(view_prefix(v) for v in EXTRA_VIEWS))
check("left and right differ", view_prefix("left") != view_prefix("right"))
check("front subject untouched", view_subject("front", "a chair") == "a chair")
check("back subject is prefixed",
      view_subject("back", "a chair") == f"{view_prefix('back')}, a chair")

print("\n(c) building image types")
check("building_type(back)", building_type("back") == "building-back")
check("building_view(building-left)", building_view("building-left") == "left")
check("plain 'building' is no view type", building_view("building") == "")
check("day is no view type", building_view("day") == "")
check("BUILDING_TYPES lists the four",
      BUILDING_TYPES == ("building-front", "building-back",
                         "building-left", "building-right"), str(BUILDING_TYPES))
check("is_view(front)", is_view("front") is True)
check("is_view(building-front) is False", is_view("building-front") is False)

print("\n(d) migration rewrite")
try:
    from app.models.world import rewrite_building_types
    meta = {"image_types": {"a.png": "building", "b.png": "day",
                            "c.png": "building-back"}}
    changed = rewrite_building_types(meta)
    check("first run reports a change", changed is True)
    check("building -> building-front, others untouched",
          meta["image_types"] == {"a.png": "building-front", "b.png": "day",
                                  "c.png": "building-back"},
          str(meta["image_types"]))
    check("second run changes nothing", rewrite_building_types(meta) is False)
    check("meta without image_types is a no-op",
          rewrite_building_types({"rooms": {}}) is False)
except ImportError as e:
    check("rewrite_building_types importable", False, str(e))

print("\n(e) prop view file names")
try:
    from app.core.props import view_source_name
    check("model/back", view_source_name("model", "back") == "source_back.png")
    check("model-v2/left", view_source_name("model-v2", "left") == "source-v2_left.png")
    check("model/front is the historic name",
          view_source_name("model", "front") == "source.png")
    check("model-v2/front is the historic name",
          view_source_name("model-v2", "front") == "source-v2.png")
    check("bogus stem -> ''", view_source_name("bogus", "back") == "")
except ImportError as e:
    check("view_source_name importable", False, str(e))

print()
if FAILURES:
    print(f"FAILED ({len(FAILURES)}): " + "; ".join(FAILURES))
    sys.exit(1)
print("all view-type checks passed")
```

- [ ] **Step 2: Run it to see it fail**

Run: `./.venv/bin/python scripts/smoke_view_types.py`
Expected: `ModuleNotFoundError: No module named 'app.core.view_prompts'`

- [ ] **Step 3: Write `app/core/view_prompts.py`**

```python
"""The VIEW vocabulary of mesh-input renders — shared by props and locations.

A multi-view img2mesh alias takes up to four images of one subject: front,
back, left, right (``openai_mesh.select_slot_images`` maps them onto the
alias' slots). Characters render their extra views through
``model_refs.py`` (``tpose_back`` / ``tpose_side``); props and location
models go through here. Same shape as the T-pose precedent:

* the FRONT keeps the base use case (``prop``, ``building``, ``room_model`` …),
* the BACK gets ``<base>_back`` — its own style and its own negative, because
  a rear render fails in its own way,
* LEFT and RIGHT share ``<base>_side``; the side itself is said in a phrase
  prepended to the subject (early tokens steer diffusion).

Gallery image types of a location model source are ``building-<view>``.
The character path is deliberately NOT moved onto this module (2026-09-02).
"""
from typing import Any

VIEWS = ("front", "back", "left", "right")
EXTRA_VIEWS = ("back", "left", "right")

_VIEW_PREFIX = {
    "front": "",
    "back": "seen directly from behind, the rear side facing the camera",
    "left": "seen from the left side, the left flank facing the camera",
    "right": "seen from the right side, the right flank facing the camera",
}

BUILDING_TYPES = tuple(f"building-{v}" for v in VIEWS)


def is_view(name: Any) -> bool:
    """True for one of the four view names (exact, lower-case)."""
    return isinstance(name, str) and name in VIEWS


def view_use_case(base: str, view: str) -> str:
    """The use case a render of ``view`` composes from, given the FRONT's
    base use case. Raises ``ValueError`` for an unknown view — a typo must
    not silently render a front."""
    if not is_view(view):
        raise ValueError(f"unknown view: {view!r}")
    if view == "front":
        return base
    return f"{base}_back" if view == "back" else f"{base}_side"


def view_prefix(view: str) -> str:
    """The phrase prepended to the subject for this view ('' for front)."""
    if not is_view(view):
        raise ValueError(f"unknown view: {view!r}")
    return _VIEW_PREFIX[view]


def view_subject(view: str, subject: str) -> str:
    """``subject`` with the view phrase in front of it — the front unchanged."""
    prefix = view_prefix(view)
    subject = (subject or "").strip()
    if not prefix:
        return subject
    return f"{prefix}, {subject}" if subject else prefix


def building_type(view: str) -> str:
    """Gallery image type of a location model source seen from ``view``."""
    if not is_view(view):
        raise ValueError(f"unknown view: {view!r}")
    return f"building-{view}"


def building_view(image_type: Any) -> str:
    """The view a gallery image type names ('' when it is not a building
    view type — ``day``, ``map_2d`` and the retired bare ``building`` alike)."""
    if isinstance(image_type, str) and image_type in BUILDING_TYPES:
        return image_type[len("building-"):]
    return ""
```

- [ ] **Step 4: Run the smoke again**

Run: `./.venv/bin/python scripts/smoke_view_types.py`
Expected: sections (a)–(c) PASS; (d) and (e) FAIL with `importable` (those functions come in Tasks 3 and 6). Exit code 1 for now — that is the expected state at the end of this task.

- [ ] **Step 5: Commit**

```bash
git add app/core/view_prompts.py scripts/smoke_view_types.py
git commit -m "feat(3d): a view vocabulary shared by prop and location mesh inputs

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01CpArTbGnVGBNzzobZCiL7R" -- app/core/view_prompts.py scripts/smoke_view_types.py
```

---

### Task 2: Per-view use-case styles (data) + style lists for the dialogs

**Files:**
- Modify: `app/core/config.py` — `_DEFAULT_IMAGE_USE_CASES` (after the `"prop"` entry ~line 297 and after `"room_model_outdoor"` ~line 220), new negatives next to `_NEG_BUILDING` (~line 111)
- Modify: `app/core/world_ops.py:2176` (`build_imagegen_options` style list)
- Modify: `app/routes/world.py:1880-1912` (`props_admin` — `prompt_styles`, `ref_slot_count`)

**Interfaces:**
- Produces: use cases `prop_back`, `prop_side`, `building_back`, `building_side`, `building_outdoor_back`, `building_outdoor_side`, `room_model_back`, `room_model_side`, `room_model_outdoor_back`, `room_model_outdoor_side` resolvable via `config.resolve_use_case_style(name, family)`.
- Produces: `GET /world/props` → `image_backends[i].prompt_styles: {prop, prop_back, prop_side}` (raw styles, `{subject}` slot included) and `image_backends[i].ref_slot_count: int`. The existing `prompt_style` key stays (= `prompt_styles["prop"]`).
- Produces: `GET /world/imagegen-options` → `options[i].prompt_styles` additionally carries the eight building/room view use cases.

- [ ] **Step 1: Add the view negatives in `app/core/config.py` right after `_NEG_OUTDOOR_SCENE`**

```python
# View-specific additions for the back and side renders of the mesh-input
# use cases (props, buildings, rooms). A rear render must not turn the
# subject back toward the camera; a profile must not fall back into the
# familiar three-quarter view. Appended to the base negative of each family.
_NEG_VIEW_BACK = ", front view, front side, facade with the entrance facing the camera, three-quarter view, mirrored, turned toward the camera"
_NEG_VIEW_SIDE = ", front view, back view, three-quarter view, facing the camera, mirrored"
_NEG_PROP = "scene, environment, floor shadow, people, hands, text, watermark"
```

Then replace the two literal `"prompt_negative": "scene, environment, floor shadow, people, hands, text, watermark",` lines inside the `"prop"` entry with `"prompt_negative": _NEG_PROP,` (both families).

- [ ] **Step 2: Add the ten use cases to `_DEFAULT_IMAGE_USE_CASES`**

Insert directly after the closing `},` of the `"prop"` entry:

```python
    # Extra VIEWS of the prop product shot (back / left+right) — the inputs of
    # a multi-view img2mesh alias. Same isolation, background and light as
    # "prop" so the views compose into one set; only the camera clause and
    # the negative differ. Left/right share "_side": the side itself comes
    # from view_prompts.view_prefix, prepended to the subject.
    "prop_back": {
        "keywords": {
            "prompt_style": "A high-quality 3D model of {subject}, designed for 3D asset generation, 8k resolution, rear view, the back of the object facing the camera, single object, isolated, centered, plain light gray background, product photography, soft studio lighting, full view, no scene",
            "prompt_negative": _NEG_PROP + _NEG_VIEW_BACK,
            "prompt_instruction": "Write comma-separated keywords for the single object seen from BEHIND, isolated on a plain light gray background. No people, no scene.",
        },
        "natural": {
            "prompt_style": "A high-quality 3D model of {subject}, designed for 3D asset generation, 8k resolution, photographed from directly behind so the back of the object faces the camera, presented as a single isolated object on a plain seamless light gray studio background, centered product shot, soft even studio lighting from above, fully in frame with generous margin, matte surfaces clearly readable",
            "prompt_negative": _NEG_PROP + _NEG_VIEW_BACK,
            "prompt_instruction": "Describe the single object seen from behind, isolated on a plain light gray background. No people, no scene.",
        },
    },
    "prop_side": {
        "keywords": {
            "prompt_style": "A high-quality 3D model of {subject}, designed for 3D asset generation, 8k resolution, side view, strict profile, single object, isolated, centered, plain light gray background, product photography, soft studio lighting, full view, no scene",
            "prompt_negative": _NEG_PROP + _NEG_VIEW_SIDE,
            "prompt_instruction": "Write comma-separated keywords for the single object in strict side profile, isolated on a plain light gray background. No people, no scene.",
        },
        "natural": {
            "prompt_style": "A high-quality 3D model of {subject}, designed for 3D asset generation, 8k resolution, photographed in strict side profile, presented as a single isolated object on a plain seamless light gray studio background, centered product shot, soft even studio lighting from above, fully in frame with generous margin, matte surfaces clearly readable",
            "prompt_negative": _NEG_PROP + _NEG_VIEW_SIDE,
            "prompt_instruction": "Describe the single object in strict side profile, isolated on a plain light gray background. No people, no scene.",
        },
    },
```

Insert directly after the closing `},` of the `"room_model_outdoor"` entry:

```python
    # Extra VIEWS of the location model sources (building exterior, outdoor
    # scene diorama, room diorama, open-air room) — multi-view img2mesh
    # inputs. Framing/isolation/light identical to the base use case; only
    # the camera clause and the negative differ. Left/right share "_side".
    "building_back": {
        "keywords": {
            "prompt_style": "{subject}, exterior view of a single building seen from directly behind, the rear facade facing the camera, slightly elevated eye level, the entire structure from ground to rooftop in frame with a margin around it, completely isolated on an empty plain neutral background, flat even shadowless lighting, uniform illumination, sharp focus, highly detailed",
            "prompt_negative": _NEG_BUILDING + _NEG_VIEW_BACK,
            "prompt_instruction": "Write comma-separated tags for the REAR view of the WHOLE building — back facade, roof, storeys, materials. Entire structure in frame with a margin, neutral background, no people, no interior.",
        },
        "natural": {
            "prompt_style": "an exterior photo of {subject} as a single building seen from directly behind with its rear facade facing the camera, at a slightly elevated eye level, the entire structure from ground to rooftop inside the frame with a margin around it, completely isolated on an empty plain neutral background, flat even shadowless lighting, uniform illumination, sharp focus, highly detailed",
            "prompt_negative": _NEG_BUILDING + _NEG_VIEW_BACK,
            "prompt_instruction": "Describe the rear view of the WHOLE building — back facade, roof, storeys, materials. The entire structure is in frame with a margin, neutral background, no people, no interior.",
        },
    },
    "building_side": {
        "keywords": {
            "prompt_style": "{subject}, exterior view of a single building in strict side elevation, one side wall facing the camera, slightly elevated eye level, the entire structure from ground to rooftop in frame with a margin around it, completely isolated on an empty plain neutral background, flat even shadowless lighting, uniform illumination, sharp focus, highly detailed",
            "prompt_negative": _NEG_BUILDING + _NEG_VIEW_SIDE,
            "prompt_instruction": "Write comma-separated tags for a strict SIDE elevation of the WHOLE building — side wall, roof, storeys, materials. Entire structure in frame with a margin, neutral background, no people, no interior.",
        },
        "natural": {
            "prompt_style": "an exterior photo of {subject} as a single building in strict side elevation with one side wall facing the camera, at a slightly elevated eye level, the entire structure from ground to rooftop inside the frame with a margin around it, completely isolated on an empty plain neutral background, flat even shadowless lighting, uniform illumination, sharp focus, highly detailed",
            "prompt_negative": _NEG_BUILDING + _NEG_VIEW_SIDE,
            "prompt_instruction": "Describe a strict side elevation of the WHOLE building — side wall, roof, storeys, materials. The entire structure is in frame with a margin, neutral background, no people, no interior.",
        },
    },
    "building_outdoor_back": {
        "keywords": {
            "prompt_style": "{subject}, outdoor scene diorama on a square ground base seen from directly behind, elevated eye level, the entire scene from ground to treetops in frame with a margin around it, completely isolated on an empty plain neutral background, flat even shadowless lighting, uniform illumination, sharp focus, highly detailed",
            "prompt_negative": _NEG_OUTDOOR_SCENE + _NEG_VIEW_BACK,
            "prompt_instruction": "Write comma-separated tags for the REAR view of the WHOLE outdoor scene on its ground base — terrain, plants, water, paths, props. Entire scene in frame with a margin, neutral background, no people.",
        },
        "natural": {
            "prompt_style": "a photo of {subject} as a single outdoor scene diorama on a square ground base seen from directly behind at an elevated eye level, the entire scene from ground to treetops inside the frame with a margin around it, completely isolated on an empty plain neutral background, flat even shadowless lighting, uniform illumination, sharp focus, highly detailed",
            "prompt_negative": _NEG_OUTDOOR_SCENE + _NEG_VIEW_BACK,
            "prompt_instruction": "Describe the rear view of the WHOLE outdoor scene on its ground base — terrain, plants, water, paths, props. The entire scene is in frame with a margin, neutral background, no people.",
        },
    },
    "building_outdoor_side": {
        "keywords": {
            "prompt_style": "{subject}, outdoor scene diorama on a square ground base in strict side view, elevated eye level, the entire scene from ground to treetops in frame with a margin around it, completely isolated on an empty plain neutral background, flat even shadowless lighting, uniform illumination, sharp focus, highly detailed",
            "prompt_negative": _NEG_OUTDOOR_SCENE + _NEG_VIEW_SIDE,
            "prompt_instruction": "Write comma-separated tags for a strict SIDE view of the WHOLE outdoor scene on its ground base — terrain, plants, water, paths, props. Entire scene in frame with a margin, neutral background, no people.",
        },
        "natural": {
            "prompt_style": "a photo of {subject} as a single outdoor scene diorama on a square ground base in strict side view at an elevated eye level, the entire scene from ground to treetops inside the frame with a margin around it, completely isolated on an empty plain neutral background, flat even shadowless lighting, uniform illumination, sharp focus, highly detailed",
            "prompt_negative": _NEG_OUTDOOR_SCENE + _NEG_VIEW_SIDE,
            "prompt_instruction": "Describe a strict side view of the WHOLE outdoor scene on its ground base — terrain, plants, water, paths, props. The entire scene is in frame with a margin, neutral background, no people.",
        },
    },
    "room_model_back": {
        "keywords": {
            "prompt_style": "{subject}, arranged on a bare floor slab, interior set piece with the architecture stripped away, open on every side and from above, nothing behind or around the furniture, floor slab floating on a plain neutral background, 3D game asset product render, high camera angle from directly behind the set piece, flat even shadowless lighting, uniform illumination, sharp focus, highly detailed",
            "prompt_negative": _NEG_ROOM + _NEG_VIEW_BACK,
            "prompt_instruction": "Write comma-separated tags for the furniture, decor, floor and style ONLY, seen from BEHIND the set piece on its bare floor slab. Never mention walls, ceilings or the building. Neutral background, no people.",
        },
        "natural": {
            "prompt_style": "a product render of {subject}, staged on a bare floor slab and photographed from directly behind the set piece — the architecture is completely stripped away, open on every side and from above, nothing stands behind or around the furnishings. The slab floats isolated on a plain neutral background like a 3D game asset, under flat, even, shadowless studio lighting, sharp focus, highly detailed",
            "prompt_negative": _NEG_ROOM + _NEG_VIEW_BACK,
            "prompt_instruction": "Describe the furniture, decor, floor and style ONLY, seen from behind the set piece on its bare floor slab. Never mention walls, ceilings or the building. Neutral background, no people.",
        },
    },
    "room_model_side": {
        "keywords": {
            "prompt_style": "{subject}, arranged on a bare floor slab, interior set piece with the architecture stripped away, open on every side and from above, nothing behind or around the furniture, floor slab floating on a plain neutral background, 3D game asset product render, high camera angle in strict side view, flat even shadowless lighting, uniform illumination, sharp focus, highly detailed",
            "prompt_negative": _NEG_ROOM + _NEG_VIEW_SIDE,
            "prompt_instruction": "Write comma-separated tags for the furniture, decor, floor and style ONLY, in strict SIDE view of the set piece on its bare floor slab. Never mention walls, ceilings or the building. Neutral background, no people.",
        },
        "natural": {
            "prompt_style": "a product render of {subject}, staged on a bare floor slab and photographed in strict side view — the architecture is completely stripped away, open on every side and from above, nothing stands behind or around the furnishings. The slab floats isolated on a plain neutral background like a 3D game asset, under flat, even, shadowless studio lighting, sharp focus, highly detailed",
            "prompt_negative": _NEG_ROOM + _NEG_VIEW_SIDE,
            "prompt_instruction": "Describe the furniture, decor, floor and style ONLY, in strict side view of the set piece on its bare floor slab. Never mention walls, ceilings or the building. Neutral background, no people.",
        },
    },
    "room_model_outdoor_back": {
        "keywords": {
            "prompt_style": "{subject}, open-air area diorama on a bare ground base, no walls, no ceiling, seen from directly behind, elevated eye level, the entire area in frame with a margin around it, isolated on a plain neutral background, no surroundings, flat even shadowless lighting, uniform illumination, sharp focus, highly detailed",
            "prompt_negative": _NEG_ROOM + _NEG_VIEW_BACK,
            "prompt_instruction": "Write comma-separated tags for the REAR view of the WHOLE open-air area on its ground base — terrain, plants, water, paths, props. No walls, no ceiling, neutral background, no people.",
        },
        "natural": {
            "prompt_style": "a photo of {subject} as a single open-air area diorama on a bare ground base with no walls and no ceiling, seen from directly behind at an elevated eye level, the entire area inside the frame with a margin around it, isolated on a plain neutral background with no surroundings, flat even shadowless lighting, uniform illumination, sharp focus, highly detailed",
            "prompt_negative": _NEG_ROOM + _NEG_VIEW_BACK,
            "prompt_instruction": "Describe the rear view of the WHOLE open-air area on its ground base — terrain, plants, water, paths, props. No walls, no ceiling, neutral background, no people.",
        },
    },
    "room_model_outdoor_side": {
        "keywords": {
            "prompt_style": "{subject}, open-air area diorama on a bare ground base, no walls, no ceiling, strict side view, elevated eye level, the entire area in frame with a margin around it, isolated on a plain neutral background, no surroundings, flat even shadowless lighting, uniform illumination, sharp focus, highly detailed",
            "prompt_negative": _NEG_ROOM + _NEG_VIEW_SIDE,
            "prompt_instruction": "Write comma-separated tags for a strict SIDE view of the WHOLE open-air area on its ground base — terrain, plants, water, paths, props. No walls, no ceiling, neutral background, no people.",
        },
        "natural": {
            "prompt_style": "a photo of {subject} as a single open-air area diorama on a bare ground base with no walls and no ceiling, in strict side view at an elevated eye level, the entire area inside the frame with a margin around it, isolated on a plain neutral background with no surroundings, flat even shadowless lighting, uniform illumination, sharp focus, highly detailed",
            "prompt_negative": _NEG_ROOM + _NEG_VIEW_SIDE,
            "prompt_instruction": "Describe a strict side view of the WHOLE open-air area on its ground base — terrain, plants, water, paths, props. No walls, no ceiling, neutral background, no people.",
        },
    },
```

- [ ] **Step 3: Verify the resolver sees all ten**

Run:
```bash
./.venv/bin/python -c "
from app.core.config import _DEFAULT_IMAGE_USE_CASES as U
need = ['prop_back','prop_side','building_back','building_side','building_outdoor_back','building_outdoor_side','room_model_back','room_model_side','room_model_outdoor_back','room_model_outdoor_side']
missing = [n for n in need if n not in U]
bad = [n for n in need if n in U and set(U[n]) != {'keywords','natural'}]
print('missing', missing, 'bad families', bad)
assert not missing and not bad
print('ok')"
```
Expected: `missing [] bad families []` then `ok`.

- [ ] **Step 4: Extend the dialog style lists**

`app/core/world_ops.py` ~line 2176 — replace the tuple:

```python
        for _uc in ("location", "map", "building", "building_outdoor",
                    "room_model", "room_model_outdoor",
                    "building_back", "building_side",
                    "building_outdoor_back", "building_outdoor_side",
                    "room_model_back", "room_model_side",
                    "room_model_outdoor_back", "room_model_outdoor_side"):
```

`app/routes/world.py` `props_admin` — replace the loop body so each backend carries all three prop styles and its reference-slot count:

```python
    image_backends = []
    try:
        for b in svc.list_available_backends(media="image"):
            style = compose_prompt("", b)
            # The three prop use cases the image dialog may render into (front
            # keeps "prop", the extra views their own siblings) — RAW styles
            # with the {subject} slot, the dialog weaves per view.
            styles = {uc: compose_prompt("", b, use_case=uc)["style"]
                      for uc in ("prop", "prop_back", "prop_side")}
            # False = no negative input (auto/yes/no resolved in
            # negation_fold): the form hides the field, and the handoff folds
            # whatever negative is submitted into the prompt as negations.
            image_backends.append({"name": b.name,
                                   "prompt_style": style["style"],
                                   "prompt_styles": styles,
                                   "prompt_negative": style["negative"],
                                   # Reference slots: the view dialog offers
                                   # "front as reference" only where one exists.
                                   "ref_slot_count": int(
                                       getattr(b, "ref_slot_count", 0) or 0),
                                   "supports_negative_prompt": bool(
                                       getattr(b, "supports_negative_prompt",
                                               True))})
    except Exception:
        pass
```

`compose_prompt(..., use_case=...)` does not exist yet — add it now in `app/core/props.py` (signature `def compose_prompt(subject: str, backend, key_areas: Any = None, use_case: str = "prop") -> Dict[str, str]`): replace the two literal `"prop"` uses inside the function body (`resolve_use_case_style("prop", …)` and `_compose(use_case="prop", …)`) with `use_case`, and add to the docstring: `` ``use_case`` picks the style of an extra VIEW (``prop_back`` / ``prop_side``); the front is ``prop``. ``

- [ ] **Step 5: Syntax check**

Run: `./.venv/bin/python -c "import app.core.config, app.core.props, app.routes.world; print('ok')"`
Expected: `ok`

- [ ] **Step 6: Commit**

```bash
git add app/core/config.py app/core/world_ops.py app/routes/world.py app/core/props.py
git commit -m "data(3d): back and side use cases for prop and location mesh inputs

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01CpArTbGnVGBNzzobZCiL7R" -- app/core/config.py app/core/world_ops.py app/routes/world.py app/core/props.py
```

---

### Task 3: Boot migration `building` → `building-front`

**Files:**
- Modify: `app/models/world.py` (after `remove_gallery_image_type`, ~line 2568)
- Modify: `app/server.py` (after the scale-frame migration block, ~line 155)
- Test: `scripts/smoke_view_types.py` section (d)

**Interfaces:**
- Produces: `rewrite_building_types(meta: dict) -> bool` (pure, in-place), `migrate_building_image_type_once() -> Dict[str, int]` (`{"galleries": n, "images": m}`; `{}` when nothing changed).

- [ ] **Step 1: Run the smoke to see (d) fail**

Run: `./.venv/bin/python scripts/smoke_view_types.py`
Expected: `FAIL  rewrite_building_types importable`

- [ ] **Step 2: Add the two functions to `app/models/world.py` after `remove_gallery_image_type`**

```python
def rewrite_building_types(meta: dict) -> bool:
    """Rename the retired bare ``building`` image type to ``building-front``
    IN PLACE (2026-09-02: the location model source got four view types).
    Returns whether anything changed. Pure — the migration below and the
    smoke check call it on a dict."""
    types = meta.get("image_types")
    if not isinstance(types, dict):
        return False
    changed = False
    for name, value in list(types.items()):
        if value == "building":
            types[name] = "building-front"
            changed = True
    return changed


def migrate_building_image_type_once() -> Dict[str, int]:
    """Walk every gallery's ``gallery_meta.json`` and rename the bare
    ``building`` image type to ``building-front``. Idempotent by construction
    (a migrated file holds no ``building`` value any more), so it needs no
    marker; touches only files that change. Returns ``{galleries, images}``
    counts for the boot log, ``{}`` when nothing changed."""
    root = get_storage_dir() / "world_gallery"
    if not root.is_dir():
        return {}
    galleries = images = 0
    for meta_file in root.glob("*/gallery_meta.json"):
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        before = dict(meta.get("image_types") or {})
        if not rewrite_building_types(meta):
            continue
        meta_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                             encoding="utf-8")
        galleries += 1
        images += sum(1 for v in before.values() if v == "building")
    return {"galleries": galleries, "images": images} if galleries else {}
```

(`json`, `Dict` and `get_storage_dir` are already imported in that module — verify with `grep -n "^import json\|^from typing\|get_storage_dir" app/models/world.py | head`.)

- [ ] **Step 3: Hook it into `app/server.py` after the scale-frame migration block**

```python
    # Location model sources carry a VIEW since 2026-09-02: the bare
    # "building" gallery image type becomes "building-front" once.
    try:
        from app.models.world import migrate_building_image_type_once
        _bt = migrate_building_image_type_once()
        if _bt:
            logger.info("Building image types migrated: %s", _bt)
    except Exception as _bte:
        logger.warning("building image-type migration failed: %s", _bte)
```

- [ ] **Step 4: Run the smoke**

Run: `./.venv/bin/python scripts/smoke_view_types.py`
Expected: section (d) all PASS; only section (e) still FAILs (`view_source_name importable`).

- [ ] **Step 5: Commit**

```bash
git add app/models/world.py app/server.py
git commit -m "feat(world): the building image type migrates to building-front once

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01CpArTbGnVGBNzzobZCiL7R" -- app/models/world.py app/server.py
```

---

### Task 4: Location backend — building view types and view renders

**Files:**
- Modify: `app/core/world_ops.py` — `assign_gallery_image_type` (~2268), `resolve_gallery_subject` (~2629), `gallery_use_case` (~2664), `compose_preview_core` (~2707), `generate_gallery_image_core` (~2796, 2962, 3010, 3101, 3131)
- Modify: `app/core/exterior_render.py:534`

**Interfaces:**
- Consumes: `app.core.view_prompts` (`building_view`, `view_use_case`, `view_subject`, `BUILDING_TYPES`, `EXTRA_VIEWS`).
- Produces: `POST /world/locations/{id}/gallery` accepts `prompt_type` ∈ `building-front|building-back|building-left|building-right` and optional `front_reference: "<gallery file>"`; `POST /world/compose-preview` accepts the same `prompt_type` values. `assign_gallery_image_type` accepts the four types.

- [ ] **Step 1: Type validation** — replace in `assign_gallery_image_type`:

```python
    from app.core.view_prompts import BUILDING_TYPES
    if image_type and image_type not in ("day", "night", "map_2d", *BUILDING_TYPES):
        raise HTTPException(
            status_code=400,
            detail="Type must be 'day', 'night', 'map_2d', one of "
                   + ", ".join(f"'{t}'" for t in BUILDING_TYPES) + " or empty")
```

- [ ] **Step 2: Subject and use case** — in `resolve_gallery_subject` the two `prompt_type == "building"` checks become `building_view(prompt_type)` (truthy for the four view types), with `from app.core.view_prompts import building_view` at the top of the function. Rewrite `gallery_use_case`:

```python
def gallery_use_case(location: Dict[str, Any], room_id: str,
                     prompt_type: str) -> str:
    """The use case a gallery render belongs to.

    A building-view render FOR A ROOM is the room-model source — its own use
    case (open cutaway); the building exterior style would demand a "single
    building" even for a park room. Both split further on the indoor/outdoor
    flag (room overrides location): an outdoor location's building is a
    scene diorama, an outdoor room an open-air area. The VIEW the type names
    (``building-back`` …) then picks the base's back/side sibling
    (``view_prompts.view_use_case``); the front keeps the base.
    """
    from app.core.view_prompts import building_view, view_use_case
    view = building_view(prompt_type)
    if view:
        base = (("room_model_outdoor" if is_outdoor_room(location, room_id)
                 else "room_model") if room_id
                else ("building_outdoor" if is_outdoor_room(location, "")
                      else "building"))
        return view_use_case(base, view)
    return "map" if prompt_type == "map_2d" else "location"
```

- [ ] **Step 3: View prefix in `compose_preview_core`** — after `subject = …` add:

```python
    # A back/side view says so at the head of the subject (the use case only
    # knows "back" or "side"; left vs right is this phrase).
    from app.core.view_prompts import building_view, view_subject
    _view = building_view(prompt_type)
    if _view:
        subject = view_subject(_view, subject)
```

Also change the default `prompt_type = (data.get("prompt_type") or "building").strip()` to `or "building-front"`.

- [ ] **Step 4: `generate_gallery_image_core`**

(a) After `prompt = custom_prompt or resolve_gallery_subject(...)` add:

```python
        from app.core.view_prompts import building_view, view_subject
        _view = building_view(prompt_type)
        # Composed subjects get the view phrase; a dialog prompt arrives final
        # (settings_applied) and already carries it from the preview.
        if _view and not custom_prompt:
            prompt = view_subject(_view, prompt)
```

(b) The `elif prompt_type == "building":` params block (~2962) becomes `elif _view:` with the comment "Square so the whole subject fits with a margin — every building view feeds the image-to-3D pass" and `params["image_use_case"] = _uc_name` (the resolved use case, already computed above the params block — check that `_uc_name` is assigned before this point; it is, at the `gallery_use_case` call).

(c) Front reference — insert directly after the existing self-reference block (`logger.info("Map-Selbst-Referenz in Slot 1: %s", _ref_name)`):

```python
        # A back/side view may take the FRONT render as its appearance
        # reference (design 2026-09-02) — style stays, unlike the regenerate
        # self-reference above. Only where the backend has a slot and the
        # file exists; otherwise the view renders from text alone.
        _front_ref = (data.get("front_reference") or "").strip()
        if _view and _view != "front" and _front_ref:
            if "/" in _front_ref or ".." in _front_ref:
                logger.warning("front_reference rejected (path): %s", _front_ref)
            elif int(getattr(backend, "ref_slot_count", 0) or 0) < 1:
                logger.info("front_reference ignored: backend %s has no "
                            "reference slot", backend.name)
            else:
                _front_path = get_gallery_dir(location_name) / _front_ref
                if _front_path.exists():
                    params["reference_images"] = {
                        "input_reference_image_1": str(_front_path)}
                    logger.info("Front reference in slot 1 for %s view: %s",
                                _view, _front_ref)
                else:
                    logger.warning("front_reference missing: %s", _front_ref)
```

(d) `if not _is_replace and prompt_type not in ("map_2d", "building"):` → `if not _is_replace and prompt_type != "map_2d" and not _view:`

(e) `if prompt_type in ("day", "night", "map_2d", "building"):` → `if prompt_type in ("day", "night", "map_2d") or _view:`

- [ ] **Step 5: `exterior_render.py:534`** — `set_gallery_image_type(loc_id, image_name, "building-front")`; update the module docstring line `(image_type building)` → `(image_type building-front)`.

- [ ] **Step 6: No stale literal left**

Run: `grep -n "\"building\"" app/core/world_ops.py app/core/exterior_render.py`
Expected: only the two hits inside `gallery_use_case` (`else "building"` base) and the `for _uc in (...)` style list from Task 2 — no `prompt_type == "building"` / `in (..., "building")` comparisons remain.

Run: `./.venv/bin/python -c "import app.core.world_ops, app.core.exterior_render; print('ok')"` → `ok`.

- [ ] **Step 7: Commit**

```bash
git add app/core/world_ops.py app/core/exterior_render.py
git commit -m "feat(world): building images carry a view; back/side renders may reference the front

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01CpArTbGnVGBNzzobZCiL7R" -- app/core/world_ops.py app/core/exterior_render.py
```

---

### Task 5: Location mesh takes view images

**Files:**
- Modify: `app/core/location_model3d.py` — `_generate` (~1208), `_run` (~1315), `trigger_generation` (~1333), `list_models` row (~198)
- Modify: `app/routes/world.py` — `_location_model3d_generate_sync` (~971)
- Modify: `frontend/src/components/ModelGallery.tsx:52` (type) and `runHint` (~255)

**Interfaces:**
- Consumes: `service.generate_mesh(view_images: Dict[str, str])` (exists).
- Produces: `trigger_generation(location_id, *, source_image, backend_glob="", room_id="", face_num=None, texture_size=None, tier=DEFAULT_TIER, lod_faces=None, view_images: Optional[Dict[str, str]] = None) -> bool`; route body key `view_images: {back?, left?, right?}` (gallery file names); model rows carry `view_images: Dict[str, str]`.

- [ ] **Step 1: `_generate`** — add parameter `view_images: Optional[Dict[str, str]] = None` (last), and after the `src` existence check:

```python
    # Optional extra views (design 2026-09-02): gallery files of the same
    # scope, keyed by view. Resolved like the front; a missing one is skipped
    # with a log line — the mesh runs off what exists.
    from app.core.view_prompts import EXTRA_VIEWS
    view_paths: Dict[str, str] = {}
    for view in EXTRA_VIEWS:
        name = str((view_images or {}).get(view) or "").strip()
        if not name:
            continue
        if "/" in name or ".." in name:
            logger.warning("Location model %s: view %s rejected (path): %s",
                           owner, view, name)
            continue
        p = get_gallery_dir(location_id) / name
        if p.exists():
            view_paths[view] = str(p)
        else:
            logger.warning("Location model %s: view %s missing (%s)", owner,
                           view, name)
```

Pass `view_images=view_paths or None` into `generate_mesh(...)`, and after `meta = {...}` add:

```python
        if view_paths:
            # Which extra views went into this mesh — file names, like
            # "source_image".
            meta["view_images"] = {v: Path(p).name for v, p in view_paths.items()}
```

- [ ] **Step 2: `_run` and `trigger_generation`** — thread `view_images` through: `_run(..., lod_faces=None, view_images=None)` calls `_generate(..., lod_faces=lod_faces, view_images=view_images)`; `trigger_generation` gets `view_images: Optional[Dict[str, str]] = None` and appends it to the `Thread(args=[...])` list. Docstring addition: `` ``view_images`` adds back/left/right gallery files for a multi-view alias (single-slot aliases get the front only). ``

- [ ] **Step 3: Row payload** — in `list_models` add `"view_images": dict(meta.get("view_images") or {}),` after `"source_image"`.

- [ ] **Step 4: Routes** — ONE helper right above `_location_model3d_generate_sync`:

```python
def _view_images_body(location_id: str, data: Dict[str, Any]) -> Dict[str, str]:
    """``view_images`` of a mesh request: ``{back|left|right: <gallery file>}``,
    each checked for path escapes and existence (400 otherwise). ``{}``
    when the body names none."""
    raw_views = data.get("view_images") or {}
    if not isinstance(raw_views, dict):
        raise HTTPException(status_code=400, detail="view_images must be an object")
    from app.core.view_prompts import EXTRA_VIEWS
    view_images: Dict[str, str] = {}
    for view in EXTRA_VIEWS:
        name = str(raw_views.get(view) or "").strip()
        if not name:
            continue
        if "/" in name or ".." in name:
            raise HTTPException(status_code=400, detail=f"bad view image name for {view}")
        if not (get_gallery_dir(location_id) / name).exists():
            raise HTTPException(status_code=400,
                                detail=f"view image for {view} not found: {name}")
        view_images[view] = name
    return view_images
```

Call it from BOTH sync bodies — `_location_model3d_generate_sync` (~971) and `_room_model3d_generate_sync` (~1418, behind `POST /locations/{id}/rooms/{room_id}/model3d/generate`): add `view_images=_view_images_body(location_id, data) or None` to each `trigger_generation(...)` call, and extend both route docstrings' body lists with `view_images?: {back?, left?, right?}`. `get_gallery_dir` is already imported at the top of `routes/world.py` (line 22).

- [ ] **Step 5: Frontend tooltip** — `ModelGallery.tsx`: add `view_images?: Record<string, string>` to `GalleryModel` (next to `source_image`), and in `runHint` after the `source_image` line:

```ts
  const views = Object.keys(m.view_images || {})
  if (views.length) parts.push(`+ ${views.join('/')}`)
```

- [ ] **Step 6: Verify**

Run: `./.venv/bin/python -c "import app.core.location_model3d, app.routes.world; print('ok')"` → `ok`
Run: `./.venv/bin/python scripts/smoke_mesh_multiview.py` → `all mesh-multiview checks passed`
Run: `npm run lint` → no errors.

- [ ] **Step 7: Commit**

```bash
git add app/core/location_model3d.py app/routes/world.py frontend/src/components/ModelGallery.tsx
git commit -m "feat(3d): a building or room model meshes from front plus optional back/left/right views

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01CpArTbGnVGBNzzobZCiL7R" -- app/core/location_model3d.py app/routes/world.py frontend/src/components/ModelGallery.tsx
```

---

### Task 6: Prop backend — view image storage and routes

**Files:**
- Modify: `app/core/props.py` — constants (~224), `source_name` (~4526), `_source_file`/`source_path` (~4536), `_image_meta`/`_set_image_meta` (~4555), `save_source_image` (~4585), `delete_variant` (~4072), `list_variants` (~3231)
- Modify: `app/routes/world.py` — `_prop_source_upload` (~2337), `prop_source_upload` (~2356)
- Modify: `app/routes/prop_variants.py` — `prop_variant_source_upload` (~568), new DELETE route
- Modify: `app/routes/assets.py` — `get_prop_source` (~689)
- Test: `scripts/smoke_view_types.py` section (e)

**Interfaces:**
- Produces:
  - `view_source_name(stem: str, view: str) -> str`
  - `_source_file(prop_id, variant=None, *, view="front", create=False)`, `source_path(prop_id, variant=None, view="front")`
  - `save_source_image(prop_id, contents, variant=None, *, view="front", backend="", prompt="", negative="") -> bool`
  - `delete_source_image(prop_id, variant, view) -> bool` (extra views only)
  - `_image_meta(meta, stem, view="front")`, `_set_image_meta(meta, stem, *, view="front", backend="", prompt="", negative="")`
  - `variant_images(prop_id, variant) -> Dict[str, Dict[str, str]]` — `{view: provenance}` for every view whose file exists
  - `list_variants` rows gain `images: {front?, back?, left?, right?}`
  - HTTP: `POST /world/props/{id}/variants/{i}/source?view=back`, `DELETE /world/props/{id}/variants/{i}/source?view=back`, `GET /assets/props/{id}/source?variant=&view=back`

- [ ] **Step 1: Run the smoke to see (e) fail**

Run: `./.venv/bin/python scripts/smoke_view_types.py` → `FAIL  view_source_name importable`

- [ ] **Step 2: File naming** — after `source_name` add:

```python
def view_source_name(stem: str, view: str) -> str:
    """File name of ONE view of a variant's source image: the front keeps
    :func:`source_name`, every extra view hangs ``_<view>`` off that stem
    (``source_back.png``, ``source-v2_left.png``). ``''`` for a stem this
    store would not hand out or an unknown view."""
    from app.core.view_prompts import is_view
    base = source_name(stem)
    if not base or not is_view(view):
        return ""
    if view == "front":
        return base
    return f"{base[:-len('.png')]}_{view}.png"
```

Rewrite `_source_file` / `source_path`:

```python
def _source_file(prop_id: str, variant: Any = None, *, view: str = "front",
                 create: bool = False) -> Optional[Path]:
    """Where ONE view of a variant's source image LIVES, whether or not it
    exists yet. ``None`` for an unknown prop, an index this prop has no
    variant for, or an unknown view."""
    d = _prop_dir(prop_id, create=create)
    if not d:
        return None
    name = view_source_name(_stem_of(prop_id, variant), view)
    return (d / name) if name else None


def source_path(prop_id: str, variant: Any = None,
                view: str = "front") -> Optional[Path]:
    """The EXISTING source image of one variant and view — ``None`` (or a
    negative index) means the PRIMARY variant, i.e. the same file every
    unqualified read has always served. ``None`` when this variant has no
    such image yet."""
    p = _source_file(prop_id, variant, view=view)
    return p if p and p.exists() else None
```

- [ ] **Step 3: Provenance per view** — add the constant next to `IMAGE_META_KEYS`:

```python
#: Variant-entry / master-record key holding the provenance of the EXTRA
#: views (``{"back": {...}, "left": {...}, "right": {...}}``); the front
#: stays in ``image`` / the master fields.
IMAGE_VIEWS_KEY = "image_views"
```

and rewrite the two helpers:

```python
def _image_meta(meta: Dict[str, Any], stem: str,
                view: str = "front") -> Dict[str, str]:
    """What is recorded about ONE view of a variant's source image: backend,
    prompt, negative, generated_at (empty strings when nothing is recorded)."""
    keys = IMAGE_META_KEYS
    if view != "front":
        if stem == MODEL_STEM:
            rec = (meta.get(IMAGE_VIEWS_KEY) or {}).get(view) or {}
        else:
            rec = {}
            for entry in _variant_list(meta):
                if entry["stem"] == stem:
                    rec = (entry.get(IMAGE_VIEWS_KEY) or {}).get(view) or {}
        return {k: str(rec.get(k) or "") for k in keys}
    if stem == MODEL_STEM:
        return {k: str(meta.get(_IMAGE_META_MASTER[k]) or "") for k in keys}
    for entry in _variant_list(meta):
        if entry["stem"] == stem:
            img = entry.get("image") or {}
            return {k: str(img.get(k) or "") for k in keys}
    return {k: "" for k in keys}


def _set_image_meta(meta: Dict[str, Any], stem: str, *, view: str = "front",
                    backend: str = "", prompt: str = "",
                    negative: str = "") -> None:
    """Record what a freshly written source image (of one view) was made
    with, IN PLACE. The caller writes the sidecar."""
    rec = {"backend": backend, "prompt": prompt, "negative": negative,
           "generated_at": utc_now_iso()}
    if view != "front":
        if stem == MODEL_STEM:
            meta.setdefault(IMAGE_VIEWS_KEY, {})[view] = rec
            return
        entries = _variant_list(meta)
        for entry in entries:
            if entry["stem"] == stem:
                entry.setdefault(IMAGE_VIEWS_KEY, {})[view] = rec
        meta[VARIANTS_KEY] = entries
        return
    if stem == MODEL_STEM:
        for k, m in _IMAGE_META_MASTER.items():
            meta[m] = rec[k]
        return
    entries = _variant_list(meta)
    for entry in entries:
        if entry["stem"] == stem:
            entry["image"] = rec
    meta[VARIANTS_KEY] = entries


def _drop_image_meta(meta: Dict[str, Any], stem: str, view: str) -> None:
    """Forget the provenance of a deleted EXTRA view, in place."""
    if stem == MODEL_STEM:
        (meta.get(IMAGE_VIEWS_KEY) or {}).pop(view, None)
        return
    entries = _variant_list(meta)
    for entry in entries:
        if entry["stem"] == stem:
            (entry.get(IMAGE_VIEWS_KEY) or {}).pop(view, None)
    meta[VARIANTS_KEY] = entries
```

`_variant_list` REBUILDS every entry from a whitelist (~line 690, `rec = {"stem": …}` and `rec["image"] = …`), so an unlisted key would be dropped on the next read-modify-write. Directly after the `rec["image"]` block add:

```python
            # Provenance of the EXTRA views (design 2026-09-02) — same shape
            # as `image`, one record per view that has one.
            views = entry.get(IMAGE_VIEWS_KEY)
            if isinstance(views, dict):
                kept = {v: {k: str((r or {}).get(k) or "") for k in IMAGE_META_KEYS}
                        for v, r in views.items()
                        if v in ("back", "left", "right") and isinstance(r, dict)}
                if kept:
                    rec[IMAGE_VIEWS_KEY] = kept
```

- [ ] **Step 4: `save_source_image` + `delete_source_image` + variant cleanup**

`save_source_image(prop_id, contents, variant=None, *, view="front", backend="", prompt="", negative="")`: `target = _source_file(prop_id, variant, view=view, create=True)`; `_set_image_meta(meta, _stem_of(prop_id, variant), view=view, backend=…, …)`; log line names the view. Add after it:

```python
def delete_source_image(prop_id: str, variant: Any, view: str) -> bool:
    """Remove ONE extra view image of a variant (never the front — that is
    the variant's identity picture). False when nothing was there."""
    from app.core.view_prompts import EXTRA_VIEWS
    if view not in EXTRA_VIEWS:
        return False
    p = source_path(prop_id, variant, view=view)
    if not p:
        return False
    p.unlink()
    meta = read_sidecar(prop_id)
    _drop_image_meta(meta, _stem_of(prop_id, variant), view)
    _write_sidecar(prop_id, meta)
    return True


def variant_images(prop_id: str, variant: Any = None) -> Dict[str, Dict[str, str]]:
    """``{view: provenance}`` for every view whose file exists on this
    variant — what the detail's source panel renders its four tiles from."""
    from app.core.view_prompts import VIEWS
    meta = read_sidecar(prop_id)
    stem = _stem_of(prop_id, variant)
    return {v: _image_meta(meta, stem, v) for v in VIEWS
            if source_path(prop_id, variant, view=v)}
```

In `delete_variant`, replace the single unlink with a loop over all views:

```python
    from app.core.view_prompts import VIEWS
    for view in VIEWS:
        img = _source_file(pid, i, view=view)
        if img and img.exists():
            img.unlink()
```

In `list_variants`, add `"images": variant_images(prop_id, i),` right after `"image": …`, and extend the docstring's field list with `images` (`{view: provenance} for every view file that exists`).

- [ ] **Step 5: Routes**

`app/routes/world.py` `_prop_source_upload(prop_id, file, variant=None, view="front")` → `save_source_image(prop_id, contents, variant, view=view)`; validate the view first:

```python
    from app.core.view_prompts import is_view
    if not is_view(view):
        raise HTTPException(status_code=400, detail="view must be front, back, left or right")
```

`app/routes/prop_variants.py`:

```python
@router.post("/props/{prop_id}/variants/{index}/source")
async def prop_variant_source_upload(prop_id: str, index: int,
                                     file: UploadFile = File(...),
                                     view: str = "front") -> Dict[str, Any]:
    """Upload THIS variant's product-shot image (``?view=`` picks one of the
    four views; default front) — the picture its re-mesh works from. The
    image belongs to the variant like its meshes do, so an upload here can
    never overwrite another version's picture."""
    from app.routes.world import _prop_source_upload
    return await _prop_source_upload(prop_id, file, _variant(prop_id, index),
                                     view=view)


@router.delete("/props/{prop_id}/variants/{index}/source")
def prop_variant_source_delete(prop_id: str, index: int,
                               view: str = "") -> Dict[str, Any]:
    """Remove ONE extra view image (``?view=back|left|right``) of this
    variant. The front is not deletable — it is the variant's picture."""
    from app.core.props import delete_source_image
    from app.core.view_prompts import EXTRA_VIEWS
    _variant(prop_id, index)
    if view not in EXTRA_VIEWS:
        raise HTTPException(status_code=400,
                            detail="view must be back, left or right")
    if not delete_source_image(prop_id, index, view):
        raise HTTPException(status_code=404, detail="No such view image")
    return {"status": "ok"}
```

`app/routes/assets.py` `get_prop_source(prop_id, request, variant="", view="front")`: validate with `is_view(view)` (404 otherwise) and call `source_path(prop_id, variant=idx, view=view)`. Docstring: `` ``view`` serves one of the extra views (``back``/``left``/``right``); default front. ``

- [ ] **Step 6: Verify**

Run: `./.venv/bin/python scripts/smoke_view_types.py` → `all view-type checks passed`
Run: `./.venv/bin/python -c "import app.core.props, app.routes.world, app.routes.prop_variants, app.routes.assets; print('ok')"` → `ok`
Run: `grep -n "_source_file(\|source_path(" app/core/props.py app/routes/*.py` and confirm every remaining call is either front (no `view=`) or passes a `view=` keyword — no positional third argument anywhere.

- [ ] **Step 7: Commit**

```bash
git add app/core/props.py app/routes/world.py app/routes/prop_variants.py app/routes/assets.py
git commit -m "feat(props): a variant stores back/left/right view images beside its front

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01CpArTbGnVGBNzzobZCiL7R" -- app/core/props.py app/routes/world.py app/routes/prop_variants.py app/routes/assets.py
```

---

### Task 7: Prop backend — view render with front reference, mesh with views

**Files:**
- Modify: `app/core/props.py` — `_gen_key` (~5519), `_render_source` (~5661), `_generate` (~5783), `trigger_generation` (~6080)
- Modify: `app/routes/world.py` — `prop_regenerate` (~2160)
- Modify: `app/routes/prop_variants.py` — `prop_variant_generate` (~579)

**Interfaces:**
- Consumes: Task 6 storage API, `view_prompts`, `service.generate_mesh(view_images=…)`.
- Produces: `trigger_generation(..., view: str = "front", front_reference: bool = False, views: Optional[List[str]] = None)`; bodies: `image_only` runs take `view` + `front_reference`; `mesh_only` / full runs take `views: ["back", "left", "right"]`.

- [ ] **Step 1: `_gen_key`** — signature `_gen_key(prop_id, variant, backend_glob, view: str = "")`, return `f"{prop_id}|{idx}|{(backend_glob or '').strip().lower()}|{view}"`; docstring addition: `` A view render carries its VIEW so a back and a left render of one variant run side by side while the same view stays one job. `` Check `_split_gen_key` still parses (it partitions on the first two `|` — unchanged).

- [ ] **Step 2: `_render_source`**

Signature: `_render_source(prop_id, backend_glob, prompt, negative, variant=None, *, view="front", front_reference=False)`. Changes inside:

```python
    from app.core.view_prompts import view_subject, view_use_case
    use_case = view_use_case("prop", view)
    meta0 = read_sidecar(prop_id)
    key_areas = meta0.get(KEY_AREAS_KEY) or []
    if not prompt.strip():
        composed = compose_prompt(
            view_subject(view, variant_description(meta0, variant)
                         or meta0.get("name", "")),
            backend, key_areas=key_areas, use_case=use_case)
        prompt = composed["prompt"]
        if not negative.strip():
            negative = composed["negative"]
    elif key_areas:
        prompt, negative = apply_key_areas(prompt, negative, key_areas)

    params: Dict[str, Any] = {
        "width": 1024, "height": 1024,
        "seed": random.randint(1, 2**31 - 1),
    }
    # A back/side view may take the variant's FRONT image as its appearance
    # reference (design 2026-09-02) — only where a front exists and the
    # backend has a slot; otherwise the view renders from text alone.
    if view != "front" and front_reference:
        front = source_path(prop_id, variant)
        if not front:
            logger.info("Prop %s: no front image, %s view renders without "
                        "reference", prop_id, view)
        elif int(getattr(backend, "ref_slot_count", 0) or 0) < 1:
            logger.info("Prop %s: backend %s has no reference slot, %s view "
                        "renders without reference", prop_id, backend.name, view)
        else:
            params["reference_images"] = {"input_reference_image_1": str(front)}
    _log_meta = {"agent_name": f"Prop {prop_id}", "original_prompt": prompt,
                 "auto_enhance": False,
                 "compose": {"use_case": use_case, "settings_applied": True}}
```

`task_type` becomes `f"prop_source_{view}"` when `view != "front"` (else unchanged), label `f"Prop source ({view}): {prop_id}"`. The final save: `save_source_image(prop_id, images[0], variant, view=view, backend=…, prompt=…, negative=…)`.

- [ ] **Step 3: `_generate` and `trigger_generation`**

`_generate(..., variant=None, view="front", front_reference=False, views=None)`:
- the render call becomes `_render_source(prop_id, image_backend_glob, prompt, negative, variant, view=view, front_reference=front_reference)`;
- before `generate_mesh`:

```python
        # Extra views for a multi-view alias — the files this variant holds
        # among the requested ones; a requested view without a file is
        # skipped, never fatal.
        from app.core.view_prompts import EXTRA_VIEWS
        view_paths: Dict[str, str] = {}
        for v in (views or []):
            if v not in EXTRA_VIEWS:
                continue
            vp = source_path(prop_id, variant, view=v)
            if vp:
                view_paths[v] = str(vp)
            else:
                logger.info("Prop %s: requested %s view has no image, skipped",
                            prop_id, v)
```

- pass `view_images=view_paths or None` to `generate_mesh`;
- in `write_model_sidecar(path, {...})` add `**({"view_images": {v: Path(p).name for v, p in view_paths.items()}} if view_paths else {}),`.

`trigger_generation(..., variant=None, view="front", front_reference=False, views=None)`: key `_gen_key(pid, variant, mesh_backend_glob if not image_only else image_backend_glob, view if image_only else "")` — read the existing key construction in the function body and keep its backend-glob choice, only append the view; pass the three new keywords into `_generate`. Docstring: `` ``view``/``front_reference`` belong to an ``image_only`` run (which view is rendered, and whether the front is slotted as reference); ``views`` names the extra views a MESH run should send along. ``

- [ ] **Step 4: Routes** — both generate routes (`prop_regenerate` in `world.py`, `prop_variant_generate` in `prop_variants.py`) parse:

```python
    from app.core.view_prompts import EXTRA_VIEWS, is_view
    view = str(data.get("view") or "front").strip()
    if not is_view(view):
        raise HTTPException(status_code=400,
                            detail="view must be front, back, left or right")
    raw_views = data.get("views") or []
    if not isinstance(raw_views, list) or any(v not in EXTRA_VIEWS for v in raw_views):
        raise HTTPException(status_code=400,
                            detail="views must be a list of back/left/right")
```

and pass `view=view, front_reference=bool(data.get("front_reference")), views=list(raw_views)` to `trigger_generation`. Docstrings: add `view?`, `front_reference?`, `views?` to the body lists with one sentence each (`view`/`front_reference` for `image_only`; `views` for the mesh).

- [ ] **Step 5: Verify**

Run: `./.venv/bin/python -c "import app.core.props, app.routes.world, app.routes.prop_variants; print('ok')"` → `ok`
Run: `./.venv/bin/python scripts/smoke_view_types.py` → `all view-type checks passed`
Run: `./.venv/bin/python scripts/smoke_mesh_multiview.py` → `all mesh-multiview checks passed`

- [ ] **Step 6: Commit**

```bash
git add app/core/props.py app/routes/world.py app/routes/prop_variants.py
git commit -m "feat(props): a view renders with the front as reference; the mesh takes the views along

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01CpArTbGnVGBNzzobZCiL7R" -- app/core/props.py app/routes/world.py app/routes/prop_variants.py
```

---

### Task 8: `MeshBackendDialog` — generic Views section

**Files:**
- Modify: `frontend/src/components/MeshBackendDialog.tsx`

**Interfaces:**
- Produces:
```ts
export type MeshView = 'front' | 'back' | 'left' | 'right'
export interface MeshViewChoice {
  view: MeshView
  options: { value: string; label: string }[]
  required?: boolean
}
// prop:   views?: MeshViewChoice[]
// opts:   views?: Partial<Record<MeshView, string>>   (only chosen views, '' never sent)
```

- [ ] **Step 1: Types** — after `MeshBackend` add the two exports above; add `views?: Partial<Record<MeshView, string>>` to `MeshGenerateOpts` with the comment `/** Chosen image per view (file name), only views that were picked. */`; add `views?: MeshViewChoice[]` to the component props with doc:

```ts
  /** The VIEWS a multi-view alias may take (design 2026-09-02): per view the
   *  candidate images. 0 options → not rendered (a required one blocks
   *  Generate), 1 option → a checkbox (on by default), more → a select with
   *  "— none —" for optional views and the first entry preselected. */
  views?: MeshViewChoice[]
```

- [ ] **Step 2: State + reset** — next to `lodDraft`:

```ts
  const [viewPick, setViewPick] = useState<Partial<Record<MeshView, string>>>({})
```

and inside the `useEffect(() => { if (!open) return … })` reset block add:

```ts
    const initial: Partial<Record<MeshView, string>> = {}
    for (const v of views || []) {
      if (v.options.length) initial[v.view] = v.options[0].value
    }
    setViewPick(initial)
```

with `views` added to the effect's dependency comment (the eslint-disable line already covers the array).

- [ ] **Step 3: Blocking rule + payload** — after `const canLod = …`:

```ts
  const missingRequired = (views || []).filter((v) => v.required && !v.options.length)
  const viewBlocked = missingRequired.length > 0
```

In `start()` before `onGenerate(picked, opts)`:

```ts
    if (views && views.length) {
      const chosen: Partial<Record<MeshView, string>> = {}
      for (const v of views) {
        const val = viewPick[v.view]
        if (val) chosen[v.view] = val
      }
      opts.views = chosen
    }
```

Generate button: `disabled={none || viewBlocked}`.

- [ ] **Step 4: Render the section** — after the `{hint ? … : null}` line inside the form:

```tsx
              {views && views.length ? (
                <>
                  <label className="ga-hint">{t('Views')}</label>
                  {views.map((v) => {
                    if (!v.options.length) return null
                    const label = t(VIEW_LABELS[v.view])
                    if (v.options.length === 1) {
                      const only = v.options[0]
                      return (
                        <label key={v.view} className="ga-check-row">
                          <input type="checkbox"
                            checked={!!viewPick[v.view]}
                            disabled={!!v.required}
                            onChange={(e) => setViewPick((p) => ({
                              ...p, [v.view]: e.target.checked ? only.value : '' }))} />
                          <span>{label} · {only.label}</span>
                        </label>
                      )
                    }
                    return (
                      <label key={v.view} style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                        <span className="ga-hint">{label}{v.required ? '' : ` (${t('optional')})`}</span>
                        <select className="ga-input" value={viewPick[v.view] || ''}
                          onChange={(e) => setViewPick((p) => ({ ...p, [v.view]: e.target.value }))}>
                          {!v.required ? <option value="">{t('— none —')}</option> : null}
                          {v.options.map((o) => (
                            <option key={o.value} value={o.value}>{o.label}</option>
                          ))}
                        </select>
                      </label>
                    )
                  })}
                  {viewBlocked ? (
                    <div className="ga-hint" style={{ color: 'var(--danger, #f85149)' }}>
                      {t('No image for the required view: {views}').replace('{views}',
                        missingRequired.map((v) => t(VIEW_LABELS[v.view])).join(', '))}
                    </div>
                  ) : (
                    <div className="ga-hint">
                      {t('A single-slot alias uses the front only; a multi-view alias takes every view picked here.')}
                    </div>
                  )}
                </>
              ) : null}
```

with, at module level:

```ts
const VIEW_LABELS: Record<MeshView, string> = {
  front: 'Front', back: 'Back', left: 'Left', right: 'Right',
}
```

- [ ] **Step 5: Verify**

Run: `npm run lint` → clean. Run: `npm run build` → succeeds (do not commit `static/` yet).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/MeshBackendDialog.tsx
git commit -m "feat(admin): the mesh dialog offers the views a multi-view alias may take

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01CpArTbGnVGBNzzobZCiL7R" -- frontend/src/components/MeshBackendDialog.tsx
```

---

### Task 9: Props frontend — view tiles, view dialog, mesh views

**Files:**
- Modify: `frontend/src/tabs/props/propTypes.ts` (~236-270, `ImageBackendInfo`)
- Modify: `frontend/src/tabs/props/PropImageDialog.tsx`
- Modify: `frontend/src/tabs/props/PropDetail.tsx` (~110-150 props, ~598-620 upload, ~1365-1440 source panel)
- Modify: `frontend/src/tabs/props/PropsTab.tsx` (~50-70 state, ~290-400 dialogs)

**Interfaces:**
- Consumes: `GET /world/props` (`images`, `prompt_styles`, `ref_slot_count`), routes of Tasks 6–7, `MeshBackendDialog.views`.
- Produces: `PropView` type; `PropVariant.images`; `onRegenerateImage(variant, view, image?, subject?)`; `PropImageDialog` props `view`, `hasFront`; `onGenerate(imageBackend, prompt, negative, frontReference)`.

- [ ] **Step 1: Types (`propTypes.ts`)**

```ts
export type PropView = 'front' | 'back' | 'left' | 'right'
export const PROP_EXTRA_VIEWS: PropView[] = ['back', 'left', 'right']
```

In `PropVariant` after `image`: `/** Provenance per view whose file exists — the source panel's tiles. */ images: Partial<Record<PropView, PropSourceImage>>`. In `ImageBackendInfo` (find it with `grep -n "interface ImageBackendInfo" -A 8`): add `prompt_styles?: Record<string, string>` and `ref_slot_count?: number`.

- [ ] **Step 2: `PropImageDialog`** — new props `view: PropView` and `hasFront: boolean`; `onGenerate: (imageBackend: string, prompt: string, negative: string, frontReference: boolean) => void`. State `const [useFront, setUseFront] = useState(true)` reset on open. Compose from the view's style:

```ts
const styleFor = (backend: ImageBackendInfo | undefined, view: PropView): string => {
  const key = view === 'front' ? 'prop' : view === 'back' ? 'prop_back' : 'prop_side'
  return backend?.prompt_styles?.[key] ?? backend?.prompt_style ?? ''
}
const VIEW_PHRASE: Record<PropView, string> = {
  front: '',
  back: 'seen directly from behind, the rear side facing the camera',
  left: 'seen from the left side, the left flank facing the camera',
  right: 'seen from the right side, the right flank facing the camera',
}
const composePrompt = (prop: PropFull, backend: ImageBackendInfo | undefined,
                       view: PropView, variantSubject?: string): string => {
  const subject = variantSubject || prop.description || prop.name || ''
  const phrase = VIEW_PHRASE[view]
  return composePropPrompt(styleFor(backend, view),
                           phrase ? `${phrase}, ${subject}` : subject)
}
```

(The phrases mirror `app/core/view_prompts.py` — the dialog shows the final prompt, so it must weave the same words; keep the two tables identical.) Every `composePrompt(prop, b, subject)` call becomes `composePrompt(prop, b, view, subject)`. Title: `{t('Render source image')} — {prop.name} · {t('Variant')} {variant + 1} · {t(VIEW_LABEL[view])}` with `const VIEW_LABEL: Record<PropView, string> = { front: 'Front', back: 'Back', left: 'Left', right: 'Right' }`. Above the hint text, for `view !== 'front'`:

```tsx
              {view !== 'front' ? (
                (() => {
                  const slots = backends.find((b) => b.name === picked)?.ref_slot_count || 0
                  return (
                    <label className="ga-check-row"
                      title={t('The variant’s front image goes into the backend’s first reference slot so the view keeps the same appearance. Text still decides the view.')}>
                      <input type="checkbox" checked={useFront && hasFront && slots > 0}
                        disabled={!hasFront || slots === 0}
                        onChange={(e) => setUseFront(e.target.checked)} />
                      <span>
                        {t('Use the front image as reference')}
                        {!hasFront ? ` — ${t('no front image yet')}`
                          : slots === 0 ? ` — ${t('this backend has no reference slot')}` : ''}
                      </span>
                    </label>
                  )
                })()
              ) : null}
```

Render button: `onGenerate(picked, prompt, negative, view !== 'front' && useFront && hasFront)`.

- [ ] **Step 3: `PropDetail` source panel**

Prop types (the detail OWNS the variant list — `PropFull` has none — so the facts the container's dialogs need travel with the callbacks):

```ts
  onRegenerateImage: (variant: number, view: PropView, image?: PropSourceImage,
    subject?: string, hasFront?: boolean) => void
  /** Re-mesh … — `existingViews` are the extra views this variant holds a file for. */
  onRegenerateMesh: (variant: number, existingViews: PropView[]) => void
```

The existing 🖼 button passes `'front'` and `!!shownVariant?.has_source`; the existing re-mesh (⚙) call passes `PROP_EXTRA_VIEWS.filter((v) => !!shownVariant?.images?.[v])`. `uploadSource(file, view: PropView = 'front')` posts to `` `/world/props/${enc}/variants/${variant}/source${view === 'front' ? '' : `?view=${view}`}` ``. Add:

```ts
  const deleteView = useCallback(async (view: PropView) => {
    try {
      await apiDelete(`/world/props/${enc}/variants/${variant}/source?view=${view}`)
      await meshesChanged()
      toast(t('Deleted'))
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [enc, variant, meshesChanged, t, toast])
  const [armedView, setArmedView] = useState<PropView | null>(null)
  const viewUploadRef = useRef<HTMLInputElement>(null)
  const [uploadView, setUploadView] = useState<PropView>('back')
```

(`apiDelete` from `'../../lib/api'`.) After the front's button row insert the tile row:

```tsx
            <div className="ga-form-section-label" style={{ margin: '6px 0 0' }}>
              {t('Extra views (multi-view mesh)')}
            </div>
            <div style={{ display: 'flex', gap: 6 }}>
              {PROP_EXTRA_VIEWS.map((view) => {
                const rec = shownVariant?.images?.[view]
                return (
                  <div key={view} style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 3 }}>
                    <span className="ga-hint">{t(VIEW_LABEL[view])}</span>
                    {rec ? (
                      <img
                        src={`/assets/props/${enc}/source?variant=${variant}&view=${view}&v=${reloadKey}`}
                        alt={t(VIEW_LABEL[view])}
                        title={rec.backend ? `🖼 ${rec.backend}${rec.generated_at ? ` · ${rec.generated_at.slice(0, 10)}` : ''}` : t('Uploaded')}
                        style={{ width: '100%', aspectRatio: '1', objectFit: 'contain', borderRadius: 6,
                          border: '1px solid var(--border, #30363d)', background: 'rgba(255,255,255,0.04)' }} />
                    ) : (
                      <div style={{ width: '100%', aspectRatio: '1', borderRadius: 6,
                        border: '1px dashed var(--border, #30363d)', display: 'flex',
                        alignItems: 'center', justifyContent: 'center' }}>
                        <span className="ga-hint">{t('none')}</span>
                      </div>
                    )}
                    <div style={{ display: 'flex', gap: 3 }}>
                      <button type="button" className="ga-btn ga-btn-sm" style={{ flex: 1 }}
                        disabled={variantBusy}
                        onClick={() => onRegenerateImage(variant, view, rec,
                          shownVariant?.description || prop.name,
                          !!shownVariant?.has_source)}
                        title={t('Render this view (optionally with the front image as reference).')}>
                        🖼
                      </button>
                      <button type="button" className="ga-btn ga-btn-sm"
                        onClick={() => { setUploadView(view); viewUploadRef.current?.click() }}
                        title={t('Upload a picture as this view.')}>
                        ⬆
                      </button>
                      {rec ? (
                        <button type="button" className="ga-btn ga-btn-sm ga-btn-danger"
                          onClick={() => {
                            if (armedView === view) { setArmedView(null); void deleteView(view) }
                            else setArmedView(view)
                          }}
                          title={armedView === view ? t('Click again to delete this view') : t('Delete this view image')}>
                          {armedView === view ? t('Sure?') : '×'}
                        </button>
                      ) : null}
                    </div>
                  </div>
                )
              })}
              <input ref={viewUploadRef} type="file" accept="image/*" style={{ display: 'none' }}
                onChange={(e) => {
                  const f = e.target.files?.[0]
                  if (f) void uploadSource(f, uploadView)
                  e.target.value = ''
                }} />
            </div>
```

with `const VIEW_LABEL: Record<PropView, string> = { front: 'Front', back: 'Back', left: 'Left', right: 'Right' }` at module level and `PROP_EXTRA_VIEWS`, `PropView` imported from `./propTypes`.

- [ ] **Step 4: `PropsTab`** — `imgRegen` state gains `view: PropView` and `hasFront: boolean`; `regen` state gains `views?: PropView[]`:

```ts
  onRegenerateMesh={(variant, views) =>
    setRegen({ id: selectedProp.id, meshOnly: true, variant, views })}
  onRegenerateImage={(variant, view, image, subject, hasFront) =>
    setImgRegen({ prop: selectedProp, variant, view, hasFront: !!hasFront, image, subject })}
```

`PropImageDialog` gets `view={imgRegen?.view || 'front'}` and `hasFront={!!imgRegen?.hasFront}`; its `onGenerate` posts `{ image_only: true, image_backend: imageBackend, prompt, negative, view: target.view, front_reference: frontReference }`.

The re-mesh `MeshBackendDialog` gets:

```tsx
          views={regen?.meshOnly && regen.views?.length
            ? regen.views.map((view) => ({ view, options: [{ value: view, label: t('stored') }] }))
            : undefined}
```

and its `onGenerate` body adds `...(opts.views ? { views: Object.keys(opts.views) } : {})` to the POST body.

- [ ] **Step 5: Verify**

Run: `npm run lint` → clean; `npm run build` → succeeds.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/tabs/props/propTypes.ts frontend/src/tabs/props/PropImageDialog.tsx frontend/src/tabs/props/PropDetail.tsx frontend/src/tabs/props/PropsTab.tsx
git commit -m "feat(admin): a prop variant renders, uploads and meshes its back/left/right views

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01CpArTbGnVGBNzzobZCiL7R" -- frontend/src/tabs/props/propTypes.ts frontend/src/tabs/props/PropImageDialog.tsx frontend/src/tabs/props/PropDetail.tsx frontend/src/tabs/props/PropsTab.tsx
```

---

### Task 10: Location gallery — four building types, view selector, front reference

**Files:**
- Modify: `frontend/src/tabs/world/worldTypes.ts:475`
- Modify: `frontend/src/components/ImageGenDialog.tsx` (types ~60-100, props ~120-200, submit ~440-480, render ~740-800)
- Modify: `frontend/src/tabs/world/LocationGallery.tsx` (tile ~100-160, filters ~270-285, state ~201, submit ~344-380, panel ~500-565, dialog ~640-690)

**Interfaces:**
- Produces: `IMAGE_TYPES = ['', 'day', 'night', 'map_2d', 'building-front', 'building-back', 'building-left', 'building-right']`, `BUILDING_TYPES`, `isBuildingType(t)`; `ImageGenSubmit.front_reference?: string`; `ImageGenDialog` props `viewChoice?: { value: ImageView; onChange: (v: ImageView) => void }`, `frontReferences?: string[]`.

- [ ] **Step 1: `worldTypes.ts`**

```ts
export const BUILDING_TYPES = ['building-front', 'building-back', 'building-left', 'building-right'] as const
export type BuildingType = typeof BUILDING_TYPES[number]
export const IMAGE_TYPES = ['', 'day', 'night', 'map_2d', ...BUILDING_TYPES] as const
export const isBuildingType = (t: string | undefined): boolean =>
  (BUILDING_TYPES as readonly string[]).includes(t || '')
```

- [ ] **Step 2: `ImageGenDialog`** — types:

```ts
export type ImageView = 'front' | 'back' | 'left' | 'right'
```

`ImageGenSubmit` gains `front_reference?: string` (comment: `// Gallery file used as the appearance reference of a back/side view (view renders only).`). Props gain:

```ts
  /** View selector for the building/room model source (design 2026-09-02):
   *  the caller owns the value (it sets prompt_type) and re-runs the compose
   *  preview on change. */
  viewChoice?: { value: ImageView; onChange: (v: ImageView) => void }
  /** Front images the chosen view may reference (newest first); shown only
   *  for back/left/right and when non-empty. The pick is emitted as
   *  `front_reference`. */
  frontReferences?: string[]
```

State: `const [frontRef, setFrontRef] = useState('')`, `const [useFrontRef, setUseFrontRef] = useState(true)`; reset on open: `setFrontRef(frontReferences?.[0] || ''); setUseFrontRef(true)` inside the existing `useEffect(() => { if (open) { setUseRoom(true); … } })` (add `frontReferences?.[0]` to its deps). In `handleSubmit` before `setSubmitting(true)`:

```ts
    if (viewChoice && viewChoice.value !== 'front' && useFrontRef && frontRef
        && (currentOption.ref_slot_count || 0) > 0) {
      payload.front_reference = frontRef
    }
```

(add `viewChoice`, `useFrontRef`, `frontRef` to the callback deps). Render, at the top of the form body (find the first field, the backend select, and insert before it):

```tsx
              {viewChoice ? (
                <>
                  <label className="ga-imagegen-label">{t('View')}</label>
                  <select className="ga-input" value={viewChoice.value}
                    disabled={submitting}
                    onChange={(e) => viewChoice.onChange(e.target.value as ImageView)}>
                    {(['front', 'back', 'left', 'right'] as ImageView[]).map((v) => (
                      <option key={v} value={v}>{t(VIEW_LABEL[v])}</option>
                    ))}
                  </select>
                  {viewChoice.value !== 'front' && (frontReferences || []).length ? (
                    <>
                      <label className="ga-check-row"
                        title={t('The front image goes into the backend’s first reference slot so the view keeps the same appearance. Text still decides the view.')}>
                        <input type="checkbox"
                          checked={useFrontRef && slotBudget > 0}
                          disabled={submitting || slotBudget === 0}
                          onChange={(e) => setUseFrontRef(e.target.checked)} />
                        <span>
                          {t('Use front image as reference')}
                          {slotBudget === 0 ? ` — ${t('this backend has no reference slot')}` : ''}
                        </span>
                      </label>
                      {useFrontRef && slotBudget > 0 ? (
                        <select className="ga-input" value={frontRef}
                          disabled={submitting}
                          onChange={(e) => setFrontRef(e.target.value)}>
                          {(frontReferences || []).map((f) => (
                            <option key={f} value={f}>{f}</option>
                          ))}
                        </select>
                      ) : null}
                    </>
                  ) : null}
                </>
              ) : null}
```

`slotBudget` is defined below the callbacks today — move the `const slotBudget = currentOption?.ref_slot_count || 0` line above the JSX if it is not already in scope there (it is computed before `if (!open) return null`, so it is). Add at module level `const VIEW_LABEL: Record<ImageView, string> = { front: 'Front', back: 'Back', left: 'Left', right: 'Right' }`. The reference toggle adds one slot to `usedSlots`: `+ (viewChoice && viewChoice.value !== 'front' && useFrontRef && frontRef ? 1 : 0)`.

- [ ] **Step 3: `LocationGallery`**

- import `BUILDING_TYPES, isBuildingType` and `type ImageView` (from `'../../components/ImageGenDialog'`).
- Tile: `{type !== 'building' ? (🌙)}` → `{!isBuildingType(type) ? (…)}`; delete the whole `{type === 'building' && onGenerateModel ? (🧊) : null}` block. Remove `onGenerateModel` from the tile props, from the `LocationGallery` props (both the interface and the destructuring) and from the tile call site.
- Filters: `(tps[f] || '') === 'building'` → `isBuildingType(tps[f])`; `!== 'building'` → `!isBuildingType(tps[f])`.
- State: keep `dialogType` as the DIALOG KIND (`'building'` = one of the two 🏛 buttons was pressed) and add the view beside it:

```ts
  const [dialogType, setDialogType] = useState<'day' | 'night' | 'map_2d' | 'building' | null>(null)
  const [buildingView, setBuildingView] = useState<ImageView>('front')
```

`'building'` stays the DIALOG KIND (which button was pressed); the wire value is derived:

```ts
  const promptType = dialogType === 'building' ? `building-${buildingView}` : dialogType
```

Use `promptType` in `submitGenerate` (`prompt_type: promptType`) and in `composeRequest` (`prompt_type: promptType`, with `buildingView` in its deps). Reset `setBuildingView('front')` whenever `setDialogType('building')` is called (both buttons). In `submitGenerate` add `if (payload.front_reference) body.front_reference = payload.front_reference`.

- Front references for the dialog (scope-aware, newest first — the gallery lists newest first already; keep that order):

```ts
  const frontImages = useMemo(() => {
    const tps = data?.image_types || {}
    const rooms = data?.image_rooms || {}
    return (data?.images || []).filter((f) => tps[f] === 'building-front'
      && (roomFilter ? rooms[f] === roomFilter : !rooms[f]))
  }, [data, roomFilter])
```

- Dialog: add `viewChoice={dialogType === 'building' ? { value: buildingView, onChange: setBuildingView } : undefined}` and `frontReferences={dialogType === 'building' ? frontImages : undefined}`. Title for the building kind: `` t('Generate building image — {name}') `` stays; `showResolution` / `defaultResolution` conditions keep `dialogType === 'building'`.
- Button titles: the 3D-mode `🏛 Generate building` title → `t('Open the image generation dialog for the building exterior (front, back, left or right view — the sources of the 3D building model).')`; the room `🏛 Generate model image` title → `t('Generate the room’s model source image (open-top interior, front or an extra view — feeds the 3D room model).')`.
- Regenerate dialog: `regenTarget.type` may now be a building view type; `submitRegenRef` sends it unchanged (the server accepts it).

- [ ] **Step 4: Verify**

Run: `grep -n "'building'" frontend/src/tabs/world/LocationGallery.tsx` → only the dialog-kind uses (`setDialogType('building')`, `dialogType === 'building'`), no image-type comparisons.
Run: `npm run lint` → clean (expect errors in `LocationEditor`/`WorldTab` about the removed `onGenerateModel` prop — those are fixed in Task 11; if lint refuses to pass, do Task 11 Step 1 first and commit both together).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/tabs/world/worldTypes.ts frontend/src/components/ImageGenDialog.tsx frontend/src/tabs/world/LocationGallery.tsx
git commit -m "feat(admin): building images come in four views; a view render may reference the front

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01CpArTbGnVGBNzzobZCiL7R" -- frontend/src/tabs/world/worldTypes.ts frontend/src/components/ImageGenDialog.tsx frontend/src/tabs/world/LocationGallery.tsx
```

---

### Task 11: Central "Generate 3D model" button in `BuildingModelPanel`

**Files:**
- Modify: `frontend/src/tabs/world/BuildingModelPanel.tsx` (props ~94-126, `generate` ~198-222, `picker` ~487-499, head render where `uploadButton`/`blenderTools` are placed)
- Modify: `frontend/src/tabs/world/LocationEditor.tsx` (~47, ~562-580)
- Modify: `frontend/src/tabs/world/RoomEditor.tsx` (~19-41, ~108-112)
- Modify: `frontend/src/tabs/world/WorldTab.tsx` (~41, ~233, ~255)

**Interfaces:**
- Consumes: `GET /world/locations/{id}/gallery` (`GalleryResponse`), `MeshBackendDialog.views`, route body `view_images`.
- Produces: `BuildingModelPanel` props lose `generateSource` / `onGenerateSourceConsumed`; `RoomEditor` loses `modelGenSource` / `onModelGenConsumed`; `LocationEditor` / `WorldTab` drop their `modelGenSrc` / `roomModelSrc` state.

- [ ] **Step 1: Remove the tile plumbing** — `LocationEditor.tsx`: delete `const [modelGenSrc, setModelGenSrc] = useState<string | null>(null)`, the `onGenerateModel={setModelGenSrc}` prop and the two `generateSource` / `onGenerateSourceConsumed` props. `WorldTab.tsx`: delete `roomModelSrc` state, `onGenerateModel={setRoomModelSrc}`, and `modelGenSource={roomModelSrc}` (+ its `onModelGenConsumed` sibling — find with `grep -n "onModelGenConsumed" frontend/src/tabs/world/WorldTab.tsx`). `RoomEditor.tsx`: remove `modelGenSource` / `onModelGenConsumed` from the props interface and destructuring, delete the `useEffect` that switched to the 3D tab on `modelGenSource`, and drop the two props from the `BuildingModelPanel` call.

- [ ] **Step 2: `BuildingModelPanel` state + gallery fetch**

Replace the `generateSource` / `onGenerateSourceConsumed` props with nothing; add state:

```ts
  // The central "Generate 3D model" dialog (design 2026-09-02): opened from
  // the panel head, fed with the gallery's building-view images of THIS
  // scope (location = images without a room, room = its own), newest first.
  const [genViews, setGenViews] = useState<MeshViewChoice[] | null>(null)
  const openGenerate = useCallback(async () => {
    try {
      // `encLoc`, not `enc`: the gallery is the LOCATION's (enc carries the
      // room path for a room panel); the room filter is applied below.
      const g = await apiGet<GalleryResponse>(`/world/locations/${encLoc}/gallery`)
      const types = g.image_types || {}
      const rooms = g.image_rooms || {}
      const inScope = (f: string) => (roomId ? rooms[f] === roomId : !rooms[f])
      const forView = (view: MeshView) => (g.images || [])
        .filter((f) => types[f] === `building-${view}` && inScope(f))
        .map((f) => ({ value: f, label: f }))
      setGenViews([
        { view: 'front', options: forView('front'), required: true },
        { view: 'back', options: forView('back') },
        { view: 'left', options: forView('left') },
        { view: 'right', options: forView('right') },
      ])
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [encLoc, roomId, t, toast])
```

Imports: `type MeshView, type MeshViewChoice` from `'../../components/MeshBackendDialog'`, `type GalleryResponse` from `'./worldTypes'`.

- [ ] **Step 3: `generate` + `picker`**

```ts
  const generate = useCallback(
    (backend: string, opts?: MeshGenerateOpts) => {
      const views = opts?.views || {}
      const src = views.front
      setGenViews(null)
      if (!src) return
      const { front: _front, ...extra } = views
      void apiPost<{ status?: string }>(`/world/locations/${enc}/model3d/generate`,
        { source_image: src, backend,
          ...(Object.keys(extra).length ? { view_images: extra } : {}),
          ...(opts?.face_num ? { face_num: opts.face_num } : {}),
          ...(opts?.texture_size ? { texture_size: opts.texture_size } : {}),
          ...(opts?.tier ? { tier: opts.tier } : {}),
          ...(opts?.lod_faces !== undefined ? { lod_faces: opts.lod_faces } : {}) })
        .then((d) => { /* keep the existing already_running / started toasts */ startPoll() })
        .catch((e) => toast(t('Error') + ': ' + (e as Error).message, 'error'))
    },
    [enc, startPoll, t, toast],
  )
```

(Keep the body's existing toast strings and any extra fields the current `generate` sends — read it first and preserve them; only the source/view derivation changes.) `picker`: `open={genViews !== null}`, `views={genViews || undefined}`, `onClose={() => setGenViews(null)}`.

- [ ] **Step 4: The button** — next to `uploadButton` (same head row) add:

```tsx
  const generateButton = (
    <button
      className="ga-btn ga-btn-sm"
      disabled={!!model3d?.pending}
      onClick={() => { void openGenerate() }}
      title={roomId
        ? t('Mesh the room’s model source images (front, plus back/left/right when present) into a 3D room model.')
        : t('Mesh the building images (front, plus back/left/right when present) into the 3D building model.')}
    >
      🧊 {t('Generate 3D model')}
    </button>
  )
```

and render `{generateButton}` immediately before `{uploadButton}` wherever the head row composes them (find with `grep -n "{uploadButton}" frontend/src/tabs/world/BuildingModelPanel.tsx`).

- [ ] **Step 5: Verify**

Run: `grep -rn "generateSource\|onGenerateSourceConsumed\|onGenerateModel\|modelGenSource\|roomModelSrc\|modelGenSrc" frontend/src` → no hits.
Run: `npm run lint` → clean; `npm run build` → succeeds.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/tabs/world/BuildingModelPanel.tsx frontend/src/tabs/world/LocationEditor.tsx frontend/src/tabs/world/RoomEditor.tsx frontend/src/tabs/world/WorldTab.tsx
git commit -m "feat(admin): one central Generate-3D-model button picks the building views

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01CpArTbGnVGBNzzobZCiL7R" -- frontend/src/tabs/world/BuildingModelPanel.tsx frontend/src/tabs/world/LocationEditor.tsx frontend/src/tabs/world/RoomEditor.tsx frontend/src/tabs/world/WorldTab.tsx
```

---

### Task 12: Translations, docs, bundle

**Files:**
- Modify: `shared/languages/de.json`
- Modify: `CLAUDE.md` (3D-models paragraph)
- Modify: `development_instructions/backend-status-3d.md` (ledger — gitignored, edit only, do not `git add`)
- Build output: `static/game_admin/` (committed)

- [ ] **Step 1: German entries** — collect every NEW `t('…')` string from Tasks 8–11 (`git diff 66afa89a -- frontend/src | grep -o "t('[^']*')" | sort -u`) and add them to `translations` in `shared/languages/de.json` (keys exactly as in code, unique). Minimum set:

| English | Deutsch |
|---|---|
| `Views` | `Ansichten` |
| `Front` | `Vorne` |
| `Back` | `Hinten` |
| `Left` | `Links` |
| `Right` | `Rechts` |
| `optional` | `optional` |
| `— none —` | `— keine —` |
| `stored` | `gespeichert` |
| `none` | `keine` |
| `View` | `Ansicht` |
| `No image for the required view: {views}` | `Kein Bild für die Pflicht-Ansicht: {views}` |
| `A single-slot alias uses the front only; a multi-view alias takes every view picked here.` | `Ein Alias mit einem Slot nutzt nur die Front; ein Multi-View-Alias nimmt jede hier gewählte Ansicht.` |
| `Use the front image as reference` | `Frontbild als Referenz verwenden` |
| `Use front image as reference` | `Frontbild als Referenz` |
| `no front image yet` | `noch kein Frontbild` |
| `this backend has no reference slot` | `dieses Backend hat keinen Referenz-Slot` |
| `Render source image` | `Quellbild rendern` |
| `Extra views (multi-view mesh)` | `Zusatzansichten (Multi-View-Mesh)` |
| `Render this view (optionally with the front image as reference).` | `Diese Ansicht rendern (optional mit dem Frontbild als Referenz).` |
| `Upload a picture as this view.` | `Ein Bild als diese Ansicht hochladen.` |
| `Click again to delete this view` | `Nochmal klicken, um diese Ansicht zu löschen` |
| `Delete this view image` | `Dieses Ansichtsbild löschen` |
| `Uploaded` | `Hochgeladen` |
| `Deleted` | `Gelöscht` |
| `Generate 3D model` | `3D-Modell erzeugen` |
| `Mesh the building images (front, plus back/left/right when present) into the 3D building model.` | `Die Gebäudebilder (Front, plus Hinten/Links/Rechts falls vorhanden) zum 3D-Gebäudemodell vermeshen.` |
| `Mesh the room’s model source images (front, plus back/left/right when present) into a 3D room model.` | `Die Modell-Quellbilder des Raums (Front, plus Hinten/Links/Rechts falls vorhanden) zum 3D-Raummodell vermeshen.` |
| `The front image goes into the backend’s first reference slot so the view keeps the same appearance. Text still decides the view.` | `Das Frontbild geht in den ersten Referenz-Slot des Backends, damit die Ansicht dasselbe Aussehen behält. Die Ansicht selbst bestimmt der Text.` |
| `The variant’s front image goes into the backend’s first reference slot so the view keeps the same appearance. Text still decides the view.` | `Das Frontbild der Variante geht in den ersten Referenz-Slot des Backends, damit die Ansicht dasselbe Aussehen behält. Die Ansicht selbst bestimmt der Text.` |
| `Open the image generation dialog for the building exterior (front, back, left or right view — the sources of the 3D building model).` | `Bildgenerierungs-Dialog für die Gebäudeaußenansicht öffnen (Vorne, Hinten, Links oder Rechts — die Quellen des 3D-Gebäudemodells).` |
| `Generate the room’s model source image (open-top interior, front or an extra view — feeds the 3D room model).` | `Das Modell-Quellbild des Raums erzeugen (offenes Interieur, Front oder Zusatzansicht — speist das 3D-Raummodell).` |

Validate: `./.venv/bin/python -c "import json; d=json.load(open('shared/languages/de.json')); print(len(d['translations']))"` → prints a number (valid JSON). Any key already present in the file must not be duplicated — check each with `grep -c '"<key>"' shared/languages/de.json` before adding.

- [ ] **Step 2: `CLAUDE.md`** — in the 3D-models paragraph, after the sentence ending `…with a persisted 90°-step \`rotation\` fix in the JSON sidecar.` insert:

```
**Mesh inputs carry VIEWS** (2026-09-02, `app/core/view_prompts.py`): a location model source is a gallery
image of type `building-front` / `building-back` / `building-left` / `building-right` (the bare `building`
type was migrated away at boot), a prop variant keeps `source[-vN]_<view>.png` beside its front image; back/side
renders use the `<base>_back` / `<base>_side` use cases and may slot the front image as reference. The mesh
button for locations/rooms is the central "Generate 3D model" in `BuildingModelPanel` (picker per view), and
`service.generate_mesh(view_images=…)` hands every view to the alias — single-slot aliases get the front only.
```

- [ ] **Step 3: Ledger** — append to `development_instructions/backend-status-3d.md` one entry: date `2026-09-02`, "Multi-view mesh input for props, buildings, rooms — spec `docs/superpowers/specs/2026-09-02-multiview-props-locations-design.md`; gateway needs rig-`none` aliases with `input_image_front/back/left/right` slots to profit" (edit only; the file is gitignored).

- [ ] **Step 4: Full verification**

```bash
./.venv/bin/python scripts/smoke_view_types.py
./.venv/bin/python scripts/smoke_mesh_multiview.py
./.venv/bin/python scripts/smoke_game_time_lint.py
./.venv/bin/python scripts/smoke_scene_recipe.py
./.venv/bin/python -c "import app.server" 2>&1 | tail -3   # boots the import graph; a world-less import may log warnings, must not raise
npm run lint
npm run build
```

Expected: every smoke ends with its `all … checks passed` line, lint clean, build writes `static/game_admin/assets/*` and `client3d/dist/*`.

- [ ] **Step 5: Commit (bundle included)**

```bash
git add shared/languages/de.json CLAUDE.md static/game_admin
git commit -m "build(admin): multi-view mesh inputs for props, buildings and rooms — bundle, translations, docs

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01CpArTbGnVGBNzzobZCiL7R" -- shared/languages/de.json CLAUDE.md static/game_admin
```

(`client3d/dist/` is gitignored — do not add it.)

---

## Self-review notes

- **Spec coverage:** § 3 → Task 1; § 4 → Task 2; § 5.1 → Task 6; § 5.2 → Tasks 6–7; § 5.3 → Task 7; § 5.4 → Tasks 8–9; § 6.1 → Tasks 4, 10; § 6.2 → Task 3; § 6.3 → Task 4; § 6.4 → Task 10; § 6.5 → Task 11; § 6.6 → Task 5; § 7 → Task 8; § 9 → Tasks 1, 3, 6, 12; § 10 → Task 12.
- **Names used across tasks:** `view_use_case`, `view_subject`, `building_view`, `BUILDING_TYPES`, `EXTRA_VIEWS`, `is_view` (Task 1) — consumed verbatim in Tasks 3–7; `view_source_name`, `source_path(..., view=)`, `save_source_image(..., view=)`, `delete_source_image`, `variant_images` (Task 6) — consumed in Task 7 and by the routes; `MeshView`, `MeshViewChoice`, `MeshGenerateOpts.views` (Task 8) — consumed in Tasks 9 and 11; `ImageView`, `viewChoice`, `frontReferences`, `front_reference` (Task 10) — matched by the server key `front_reference` (Task 4); route bodies `view`, `front_reference`, `views` (Task 7) ↔ Task 9; `view_images` (Task 5) ↔ Task 11.
