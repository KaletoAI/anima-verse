"""Centralized JSON-based configuration module.

The configuration lives in TWO layers, each a ``config.json`` plus a sibling
``secrets.json`` (gitignored, holds api keys / passwords):

- the INSTANCE layer (``<instance>/config.json``, ``paths.init_instance``) —
  what belongs to the installation: endpoints, keys, LLM providers, image
  backends, ports;
- the WORLD layer (``worlds/<w>/config.json``, ``paths.init``) — what belongs
  to the simulation of one world: chat rules, NPC behaviour, calendar.

Which layer owns a value is its schema ``scope`` (``app/core/config_scope``).
In memory the two are ONE dict: ``get(dotpath)`` / ``get_section(dotpath)``
never ask for a layer. On disk each file stores only what differs from what
ships (``config_scope.prune``). A backward-compatibility bridge populates
os.environ so that existing code keeps working.
"""
import copy
import json
import os
import re
import tempfile
import threading
from pathlib import Path
from typing import Any, Optional

from app.core import config_scope, paths
from app.core.log import get_logger

logger = get_logger("config")

_CONFIG: dict = {}
# Keys this module generates for the numbered image/video/mesh backend blocks.
_IMAGEGEN_ENV_RE = re.compile(r"^SKILL_IMAGEGEN_\d+_")
_PROVIDER_ENV_RE = re.compile(r"^PROVIDER_\d+_")

# Upper bound of the SKILL_IMAGEGEN_{N}_* scan — the single source of truth for
# everyone who walks the numbered backend blocks (the image service that loads
# the backends AND the provider manager that gives each one a queue channel).
# It used to be scattered (19 / 20 / 30) and drifted: raising it in one place
# SILENTLY dropped backends past the lower bounds — a configured backend either
# vanished from the pool or ran without a serialized channel. Generous on
# purpose; anything past it is logged as an error at load.
MAX_IMAGE_BACKENDS = 200

# The world layer's config.json. Mutable — updated by load() when an explicit
# path is passed.
_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "storage" / "config.json"
# The instance layer's config.json — remembered by load() so reload() and
# save() address the same file. None = no instance layer (a script that
# opened a world without one); save() then refuses to drop instance values.
_INSTANCE_PATH: Optional[Path] = None
# Whether the last load() was strict (unreadable layer file -> raise); reload()
# keeps it, so the server's reloads stay as loud as its boot.
_LOAD_STRICT = False

# One lock for load / save / migrate_file: a save must never interleave with
# a reload reading the half-written pair of files.
_LOCK = threading.RLock()

# Snapshot of every `requires_restart: true` field's value at boot time.
# Filled once in load() and never overwritten — so the admin UI can tell
# after a save whether a restart-requiring field differs from what the
# running server process uses.
_BOOT_RESTART_SNAPSHOT: Optional[dict] = None

# Fields that contain sensitive data (API keys, passwords, secrets)
SENSITIVE_FIELDS = {
    "api_key", "password", "secret", "auth_token",
}


def _is_sensitive(key: str) -> bool:
    """Check if a config key name is sensitive."""
    return key in SENSITIVE_FIELDS


# ── Use-case-specific prompt styles ────────────────────────────────────────
# Style/negative/instruction belong to the CASE of a generation (map tile vs
# character photo vs item), not to the workflow. They hang on two dimensions:
#   use_case (map/character/item/…)  ×  style FAMILY (phrasing).
# There are two general families (NOT bound to model names, extensible per
# use case): 'natural' (flowing prose) and 'keywords' (comma tags). A
# workflow's "target prompt style" field (image_model) is translated into a
# family via _IMAGE_MODEL_FAMILY.
_PROMPT_STYLE_FAMILIES = ["natural", "keywords"]

# image_family / render target -> style family. Accepts the family names
# (natural/keywords) directly AND the render targets (z_image/qwen/flux) that
# get_target_model derives from file/backend names. Default: keywords.
_IMAGE_MODEL_FAMILY = {
    "": "keywords",
    "keywords": "keywords",
    "natural": "natural",
    "z_image": "keywords",
    "qwen": "natural",
    "flux": "natural",
}

# Shared photo negative prompt of the photoreal-oriented use cases.
_NEG_PHOTO = ("illustration, anime, cgi, 3d render, painting, airbrushed skin, "
              "plastic skin, smooth flawless skin, overexposed, glossy, fantasy, "
              "studio lighting, posed, cartoon, drawing, sketch, watermark, "
              "signature, text, logo, deformed, blurry, low quality")

# Negatives of the mesh-input renders — ONE text per use case, shared by both
# style families (deliberately NOT _NEG_PHOTO: "posed"/"studio lighting" would
# fight the T-pose / flat-light goal). Unlike _NEG_PHOTO they do NOT negate
# "cgi"/"3d render" either: the render IS the image-to-3D input and is asked
# for as a realistic 3D figure (user decision 2026-09-01) — the skin terms
# (airbrushed/plastic/flawless) stay so the textures remain lifelike.
# The finger terms bracket a SLIGHTLY spread hand (pose text: "fingers
# straight, slender and slightly spread apart", user decision 2026-09-24):
# "fingers pressed together" keeps them from closing, "splayed/fanned
# fingers" from a wide fan — a thin splayed surface the img2mesh bake
# inflates into an oversized paddle — and "curled fingers"/"clenched fists"
# from a fist. The hand-SIZE terms (oversized/large hands, thick/chunky/
# swollen/fused fingers, mitten hands) name the mesh failure reported
# 2026-09-26: the bake pads every hand by a structure cell and nothing after
# it scales a body part back, so the render must already show the hand size
# the mesh should end with (model_refs.TPOSE_PROMPT_DEFAULT has the why).
# "palms facing the camera / up" guard the palms-DOWN pose text (the Mixamo
# bind pose, user decision 2026-09-24) against the old palms-forward render.
# The leg terms carry what the pose text no longer over-asks for: it wants a
# clear separation instead of a straddle (user decision 2026-09-03), so the
# failure it must not fall back into — legs touching, ankles together — is
# named here. Deliberately NOT negated: a wide stance, which would fight the
# separation the positive text asks for.
# "cropped feet, feet cut off" (user report 2026-09-27, barefoot characters):
# a footwear piece gives the render a word to anchor the feet on ("boots",
# "sneakers"); barefoot there is none, and nothing else names the feet either
# — outfit_renderer's old "topless, bottomless" empty-slot fallback was
# retired in favour of body-slot exposed fragments, and no species package
# declares one for feet. The three "tpose*" use-case styles now also state
# the positive directly ("both feet fully/entirely inside the frame"),
# mirroring the existing hands clause — this negative is the same pairing.
_NEG_TPOSE = ("illustration, anime, painting, airbrushed skin, plastic skin, smooth flawless skin, overexposed, glossy, cartoon, drawing, sketch, watermark, signature, text, logo, deformed, blurry, low quality, harsh shadows, dramatic lighting, side lighting, rim light, backlighting, cropped, out of frame, cropped hands, hands cut off, cropped feet, feet cut off, A-pose, arms lowered, arms at sides, arms angled downward, relaxed arms, hands at hips, hands touching body, palms facing the camera, palms facing up, clenched fists, curled fingers, fingers pressed together, splayed fingers, fanned fingers, oversized hands, large hands, thick fingers, chunky fingers, swollen fingers, fused fingers, mitten hands, hands hidden, legs together, touching legs, touching ankles, crossed legs, narrow stance")
_NEG_TPOSE_ANIMAL = ("illustration, anime, painting, cartoon, drawing, sketch, watermark, signature, text, logo, deformed, blurry, low quality, harsh shadows, dramatic lighting, rim light, backlighting, cropped, out of frame, cropped legs, tail cut off, close-up, portrait, head only, human, person, hands, anthropomorphic, standing on two legs, clothing, costume, looking at the camera, head turned toward the camera, open mouth, sitting, lying down, curled up")

# Negatives of the OPTIONAL extra mesh views (back / left+right profile).
# Both build on _NEG_TPOSE and add what actually goes wrong there: the model
# turns the character back toward the camera, or lets it look over its
# shoulder, so the render ends up as yet another front-ish view. The profile
# text additionally pushes away the observed arm failures of a side view —
# the raised arms drawn FORWARD along the view axis or dropped toward the
# body ("arms going forward and down", the reported failure). Deliberately
# NOT negated: a single visible arm — in a strict profile the near arm
# correctly hides the far one.
_NEG_TPOSE_BACK = _NEG_TPOSE + ", front view, face visible, eyes, facial features, looking at the camera, looking over the shoulder, head turned, three-quarter view"
_NEG_TPOSE_SIDE = _NEG_TPOSE + ", front view, back view, facing the camera, looking at the camera, three-quarter view, both arms on one side, arms pointing forward, arms reaching forward, arms in front of the body, arms angled forward, arm resting along the body"

# Negative of the building-exterior render (source of the location 3D model —
# shared by both families). Like _NEG_TPOSE it is NOT _NEG_PHOTO (no skin
# terms); it keeps the WHOLE building in frame and free of people/interior.
# And like every other mesh-input negative it does NOT negate "cgi"/"3d
# render": the render IS the image-to-3D input (user decision 2026-09-01) —
# negating the asset look pushed the render toward photographic depth of
# field and environment cues, which bake badly into the mesh texture.
_NEG_BUILDING = ("illustration, anime, painting, cartoon, drawing, sketch, watermark, signature, text, logo, deformed, blurry, low quality, people, person, characters, crowd, interior, indoor, inside, room, furniture, close-up, cropped, out of frame, partial building, only part of the building, tilted horizon, dutch angle, fisheye, harsh shadows, cast shadows, ground shadow, dramatic lighting, side lighting, rim light, backlighting, golden hour, sunset, night, street, road, cars, trees, plants, garden, landscape, sky, clouds, surrounding buildings, neighborhood, scenery")

# Negative of the ROOM model-source renders: must NOT fight the subject —
# furniture (indoor) and plants (outdoor room) ARE the content, unlike
# _NEG_BUILDING which negates interior/furniture/trees for clean exteriors.
# Walls/ceiling/roof are negated hard so the diorama stays fully open.
_NEG_ROOM = ("illustration, anime, cartoon, drawing, sketch, painting, watermark, signature, text, logo, deformed, blurry, low quality, people, person, characters, crowd, walls, wall, ceiling, roof, enclosed room, closed room, building exterior, facade, close-up, cropped, out of frame, partial view, tilted horizon, dutch angle, fisheye, harsh shadows, cast shadows, ground shadow, dramatic lighting, side lighting, rim light, backlighting, golden hour, sunset, night, sky, clouds, street, road, cars, surrounding buildings, neighborhood, scenery")

# Negative of the OUTDOOR location scene diorama (building_outdoor): plants,
# trees and water are the subject there — only people, framing problems,
# shadows and off-base surroundings are pushed away.
_NEG_OUTDOOR_SCENE = ("illustration, anime, cartoon, drawing, sketch, painting, watermark, signature, text, logo, deformed, blurry, low quality, people, person, characters, crowd, interior, indoor, close-up, cropped, out of frame, partial view, tilted horizon, dutch angle, fisheye, harsh shadows, cast shadows, ground shadow, dramatic lighting, side lighting, rim light, backlighting, golden hour, sunset, night, sky, clouds, street, road, cars, surrounding buildings, neighborhood")

# View-specific additions for the back and side renders of the mesh-input
# use cases (props, buildings, rooms). A rear render must not turn the
# subject back toward the camera; a profile must not fall back into the
# familiar three-quarter view. Appended to the base negative of each family.
_NEG_VIEW_BACK = ", front view, front side, facade with the entrance facing the camera, three-quarter view, mirrored, turned toward the camera"
_NEG_VIEW_SIDE = ", front view, back view, three-quarter view, facing the camera, mirrored"
_NEG_PROP = "scene, environment, floor shadow, people, hands, text, watermark"

# Built-in defaults per use_case × family. These values are NOT seeded into
# config.json — they are the resolver default AND the grey placeholder in the
# admin UI (empty field = this default applies). Without a backend fallback
# EVERY use case needs a default for both families.
_DEFAULT_IMAGE_USE_CASES = {
    "scene": {
        # Composed player scene (room background + present characters).
        # Without a style the models drift into 3D/CGI looks — the default
        # pins photorealism; the anti-CGI negative is merged with the
        # scene renderer's built-in anti-duplicate negative.
        "keywords": {
            "prompt_style": "photo, photorealistic, realistic photography, natural lighting, realistic skin texture, high detail, 8k",
            "prompt_negative": "3d render, cgi, cartoon, anime, illustration, painting, video game screenshot, plastic skin",
        },
        "natural": {
            "prompt_style": "a photorealistic photograph, natural lighting, realistic skin texture, high detail",
            "prompt_negative": "3d render, cgi, cartoon, anime, illustration, painting, video game screenshot",
        },
    },
    "location": {
        "keywords": {
            "prompt_style": "{subject}, wide establishing shot, environment, atmospheric, detailed, no people",
            "prompt_negative": _NEG_PHOTO,
            "prompt_instruction": "Write comma-separated tags for an establishing shot of the place — environment, architecture, lighting, mood. No people.",
        },
        "natural": {
            "prompt_style": "a wide establishing shot of {subject}, atmospheric, detailed environment, no people",
            "prompt_negative": _NEG_PHOTO,
            "prompt_instruction": "Describe an establishing shot of the place — environment, architecture, lighting, mood. No people.",
        },
    },
    # Building exterior — source image for the location's 3D building model. A
    # three-quarter view of the WHOLE structure with a margin (the image-to-3D
    # pass needs the full silhouette), neutral background, no people, no interior.
    # Mesh input first (image-to-3D, AV3D-9): like "tpose" the render must be
    # ISOLATED (no street/trees/sky — environment bakes into the texture and
    # confuses the mesher's silhouette segmentation) under flat shadowless
    # light (shadows bake into the 3D texture). Deliberately NOT _NEG_PHOTO.
    "building": {
        "keywords": {
            "prompt_style": "{subject}, exterior view of a single building, three-quarter view, slightly elevated eye level, the entire structure from ground to rooftop in frame with a margin around it, completely isolated on an empty plain neutral background, flat even shadowless lighting, uniform illumination, sharp focus, highly detailed",
            "prompt_negative": _NEG_BUILDING,
            "prompt_instruction": "Write comma-separated tags for a three-quarter exterior view of the WHOLE building — architecture, materials, roof, storeys, style. The entire structure is in frame with a margin, neutral background, no people, no interior.",
        },
        "natural": {
            "prompt_style": "an exterior photo of {subject} as a single building seen from a three-quarter angle at a slightly elevated eye level, the entire structure from ground to rooftop inside the frame with a margin around it, completely isolated on an empty plain neutral background, flat even shadowless lighting, uniform illumination, sharp focus, highly detailed",
            "prompt_negative": _NEG_BUILDING,
            "prompt_instruction": "Describe a three-quarter exterior view of the WHOLE building — architecture, materials, roof, storeys, style. The entire structure is in frame with a margin, neutral background, no people, no interior.",
        },
    },
    # Outdoor location (park, plaza …): the "building model" of such a tile is
    # an open-air scene diorama, not a structure — same mesh-input rules.
    # Picked via the location's indoor/outdoor field (dialog + server).
    "building_outdoor": {
        "keywords": {
            "prompt_style": "{subject}, outdoor scene diorama on a square ground base, three-quarter view, elevated eye level, the entire scene from ground to treetops in frame with a margin around it, completely isolated on an empty plain neutral background, flat even shadowless lighting, uniform illumination, sharp focus, highly detailed",
            "prompt_negative": _NEG_OUTDOOR_SCENE,
            "prompt_instruction": "Write comma-separated tags for a three-quarter view of the WHOLE outdoor scene on its ground base — terrain, plants, water, paths, props. Entire scene in frame with a margin, neutral background, no people.",
        },
        "natural": {
            "prompt_style": "a photo of {subject} as a single outdoor scene diorama on a square ground base seen from a three-quarter angle at an elevated eye level, the entire scene from ground to treetops inside the frame with a margin around it, completely isolated on an empty plain neutral background, flat even shadowless lighting, uniform illumination, sharp focus, highly detailed",
            "prompt_negative": _NEG_OUTDOOR_SCENE,
            "prompt_instruction": "Describe a three-quarter view of the WHOLE outdoor scene on its ground base — terrain, plants, water, paths, props. The entire scene is in frame with a margin, neutral background, no people.",
        },
    },
    # Room model source (AV3D-2): the interior counterpart of "building" — the
    # render feeds the SAME image-to-3D pass, so the mesh-input rules hold
    # (isolated, neutral background, shadowless), but the subject is a fully
    # OPEN diorama: no walls at all and no ceiling — just the floor and its
    # furnishings, so top-down and cutaway room views work without shells.
    # Outdoor rooms (a park section) use "room_model_outdoor" instead —
    # picked via the room's indoor/outdoor field (room overrides location).
    # Wall avoidance (learned on Flux2, which IGNORES negative prompts —
    # distilled guidance, no CFG negative): everything must be positive, and
    # negation keywords ("no walls") plus the word "room" itself DRAW walls.
    # So the subject is reframed: a bare FLOOR SLAB with furniture standing
    # on it — an object that never had walls — floating like a game-asset
    # product render. The negative stays for CFG backends (SD/Z-Image).
    # The style carries the subject SLOT ({subject}, filled by
    # prompt_compose.compose): the subject belongs inside the style sentence,
    # not 60 tokens behind it. Two placeholders the frame must NOT set: the
    # inviting "with all of its furniture and decor" (it invites exactly what
    # a subject may want to exclude) and any shape word ("rectangular") —
    # form and size come from the dynamic ShapeHint alone (fix 237f5a1).
    "room_model": {
        "keywords": {
            "prompt_style": "{subject}, arranged on a bare floor slab, interior set piece with the architecture stripped away, open on every side and from above, nothing behind or around the furniture, floor slab floating on a plain neutral background, 3D game asset product render, high three-quarter camera angle, flat even shadowless lighting, uniform illumination, sharp focus, highly detailed",
            "prompt_negative": _NEG_ROOM,
            "prompt_instruction": "Write comma-separated tags for the furniture, decor, floor and style ONLY — the interior as a set piece on a bare floor slab. Never mention walls, ceilings or the building; describe just what stands on the floor. Neutral background, no people.",
        },
        "natural": {
            "prompt_style": "a product render of {subject}, staged on a bare floor slab — the architecture is completely stripped away, open on every side and from above, nothing stands behind or around the furnishings. The slab floats isolated on a plain neutral background like a 3D game asset, under flat, even, shadowless studio lighting, sharp focus, highly detailed",
            "prompt_negative": _NEG_ROOM,
            "prompt_instruction": "Describe the furniture, decor, floor and style ONLY — the interior as a set piece on a bare floor slab. Never mention walls, ceilings or the building; describe just what stands on the floor. Neutral background, no people.",
        },
    },
    # Open-air "room" (park section, courtyard): no walls or ceiling at all.
    "room_model_outdoor": {
        "keywords": {
            "prompt_style": "{subject}, open-air area diorama on a bare ground base, no walls, no ceiling, three-quarter view, elevated eye level, the entire area in frame with a margin around it, isolated on a plain neutral background, no surroundings, flat even shadowless lighting, uniform illumination, sharp focus, highly detailed",
            "prompt_negative": _NEG_ROOM,
            "prompt_instruction": "Write comma-separated tags for the WHOLE open-air area on its ground base — terrain, plants, water, paths, props. No walls, no ceiling, neutral background, no people.",
        },
        "natural": {
            "prompt_style": "a photo of {subject} as a single open-air area diorama on a bare ground base with no walls and no ceiling, seen from a three-quarter angle at an elevated eye level, the entire area inside the frame with a margin around it, isolated on a plain neutral background with no surroundings, flat even shadowless lighting, uniform illumination, sharp focus, highly detailed",
            "prompt_negative": _NEG_ROOM,
            "prompt_instruction": "Describe the WHOLE open-air area on its ground base — terrain, plants, water, paths, props. No walls, no ceiling, neutral background, no people.",
        },
    },
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
    # Terrain surface texture (AV3D-13): seamless tileable top-down ground
    # material for the 3D map (road, water, grass, …). Must tile without
    # visible seams and carry NO baked lighting — objects, shadows and
    # perspective all break the tiling illusion on the map floor.
    # The subject phrase comes from surface_textures.compose_prompt (per-kind
    # wording — "calm water surface with gentle ripples", not "water ground
    # material"): an abstract "<kind> ground material" subject plus a
    # "uniform material" style produced featureless gray swatches on every
    # backend. The style asks for color and structure positively; negation
    # keywords are gone (Flux lesson).
    "surface_texture": {
        "keywords": {
            "prompt_style": "seamless tileable texture photographed straight from above, macro surface detail, rich natural color, the surface fills the entire frame edge to edge, soft even diffuse daylight, crisp sharp focus, photorealistic, high detail",
            "prompt_negative": "objects, people, animals, shadows, highlights, perspective, horizon, sky, depth of field, border, frame, seams, text, watermark, logo, vignette, gray, monochrome, flat color, blurry, low quality",
            "prompt_instruction": "Write comma-separated tags for a seamless tileable top-down texture of the surface only — its color, structure and fine detail under soft even daylight. Nothing but the surface itself.",
        },
        "natural": {
            "prompt_style": "a seamless tileable texture photographed straight from above in macro detail: the surface fills the entire frame edge to edge with its rich natural color and fine structure, lit by soft even diffuse daylight, crisp sharp focus, photorealistic",
            "prompt_negative": "objects, people, animals, shadows, highlights, perspective, horizon, sky, depth of field, border, frame, seams, text, watermark, logo, vignette, gray, monochrome, flat color, blurry, low quality",
            "prompt_instruction": "Describe a seamless tileable top-down texture of the surface only — its color, structure and fine detail under soft even daylight. Nothing but the surface itself.",
        },
    },
    "item": {
        "keywords": {
            "prompt_style": "product photo, single object, isolated on a plain neutral background, soft studio lighting, sharp focus, highly detailed",
            "prompt_negative": "people, person, hands, characters, text, watermark, logo, clutter, busy background, blurry, low quality",
            "prompt_instruction": "Write comma-separated keywords for the single item only, isolated on a plain background. No people, no scene.",
        },
        "natural": {
            "prompt_style": "a clean product photo of a single object isolated on a plain neutral background, soft studio lighting, sharp focus",
            "prompt_negative": "people, person, hands, characters, text, watermark, logo, clutter, busy background, blurry, low quality",
            "prompt_instruction": "Write a short natural-language description of the single item only, isolated on a plain background. No people, no scene.",
        },
    },
    # Prop source image (plan-room-props.md): the product-shot render feeding
    # the img2mesh pass for a single furnishing object (chair, table, plant …).
    # Mesh-input rules like "item"/"tpose" — ISOLATED on a plain neutral ground
    # with a generous margin, flat even light (scene/shadows/perspective bake
    # into the mesh and confuse the object mesher). Flux lesson: everything
    # positive, no negation keywords in the style; the negative stays for CFG
    # backends (SD/Z-Image) which alone use it effectively.
    #
    # THE 3D-ASSET FRAMING LIVES HERE, AND ONLY HERE (2026-08-25, user
    # wording): the style opens with "A high-quality 3D model of {subject},
    # designed for 3D asset generation, 8k resolution" so the render is asked
    # for an ASSET, not a photograph that happens to show an object — image
    # models answer that framing with the clean, evenly lit, fully readable
    # geometry the mesher needs. It is DATA, not code: the admin can retune it
    # in /admin/settings, the composer weaves the subject into the {subject}
    # slot (`prompt_compose.weave_subject`) and both prop dialogs read the very
    # same string off the backend list — so the sentence exists once and can
    # never be duplicated into the final prompt.
    "prop": {
        "keywords": {
            "prompt_style": "A high-quality 3D model of {subject}, designed for 3D asset generation, 8k resolution, single object, isolated, centered, plain light gray background, product photography, soft studio lighting, full view, no scene",
            "prompt_negative": _NEG_PROP,
            "prompt_instruction": "Write comma-separated keywords for the single object only, isolated on a plain light gray background. No people, no scene.",
        },
        "natural": {
            "prompt_style": "A high-quality 3D model of {subject}, designed for 3D asset generation, 8k resolution, presented as a single isolated object on a plain seamless light gray studio background, centered product shot, soft even studio lighting from above, fully in frame with generous margin, matte surfaces clearly readable",
            "prompt_negative": _NEG_PROP,
            "prompt_instruction": "Describe the single object only, isolated on a plain light gray background. No people, no scene.",
        },
    },
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
    "character": {
        "keywords": {
            "prompt_style": "RAW photo, 35mm, natural light, skin texture, visible pores, detailed anatomy, 8k, high detail",
            "prompt_negative": _NEG_PHOTO,
            "prompt_instruction": "Write comma-separated tags for the scene — subject, pose, expression, setting, lighting, mood.",
        },
        "natural": {
            "prompt_style": "a candid photograph taken with a 35mm lens, natural light, skin with visible pores and texture, detailed anatomy, high detail",
            "prompt_negative": _NEG_PHOTO,
            "prompt_instruction": "Write a natural-language description of the scene — subject, pose, environment, lighting, mood.",
        },
    },
    "profile": {
        "keywords": {
            "prompt_style": "photorealistic, isolated floating head, only a short upper-neck stump, looking at camera, plain neutral background, sharp focus, high detail",
            "prompt_negative": _NEG_PHOTO,
            "prompt_instruction": "Write comma-separated tags for an isolated whole-head portrait — face, complete hairstyle including all hair tips, expression, short upper-neck stump. Preserve the subject's identity and full hair length; fit the entire hairstyle inside the frame without showing shoulders or torso.",
        },
        "natural": {
            "prompt_style": "a photorealistic portrait of an isolated floating head with only a short upper-neck stump, looking at the camera, plain neutral background, sharp focus",
            "prompt_negative": _NEG_PHOTO,
            "prompt_instruction": "Describe an isolated whole-head portrait — face, complete hairstyle including all hair tips, expression, short upper-neck stump. Preserve the subject's identity and full hair length; fit the entire hairstyle inside the frame without showing shoulders or torso.",
        },
    },
    # NOTE prompt layering: use-case styles carry camera/quality/framing/
    # lighting/background ONLY. Pose comes exclusively from the pose layer
    # (pose catalog / default_pose_prompt / tpose_prompt), expression from
    # the expression layer — never from a style. Keep styles pose-free.
    "outfit": {
        "keywords": {
            "prompt_style": "full body view, head to toe, plain neutral background, even lighting, sharp focus, high detail",
            "prompt_negative": _NEG_PHOTO,
            "prompt_instruction": "Write comma-separated tags describing the full outfit head-to-toe, plain background. Do not mention pose or facial expression.",
        },
        "natural": {
            "prompt_style": "a full-body photo of the character from head to toe against a plain neutral background, even lighting, sharp focus",
            "prompt_negative": _NEG_PHOTO,
            "prompt_instruction": "Describe the full outfit head-to-toe against a plain background. Do not mention pose or facial expression.",
        },
    },
    # Style for the T-pose reference render (image->3D / texture-baking
    # input): flat shadowless light — shadows would bake into the 3D
    # texture. Deliberately NOT _NEG_PHOTO ("posed", "studio lighting"
    # would fight the T-pose / flat-light goal). Pose-free like all styles.
    # The medium is a REALISTIC 3D FIGURE, not a photo (user decision
    # 2026-09-01): the render feeds a mesher, and a clean 3D-character look
    # with lifelike textures reconstructs better than photographic depth.
    "tpose": {
        "keywords": {
            "prompt_style": "render of a realistic 3D character model, lifelike skin{fabric} textures, full body view, head to toe, full arm span visible with both hands fully inside the frame, both feet fully inside the frame, wide framing with margin around the figure, plain neutral background, flat even shadowless lighting, uniform illumination, sharp focus, high detail",
            "prompt_negative": _NEG_TPOSE,
            "prompt_instruction": "Write comma-separated tags describing the character head-to-toe on a plain background with flat even lighting. Do not mention pose or facial expression.",
        },
        "natural": {
            "prompt_style": "a full-body render of the character as a realistic 3D figure with lifelike skin{fabric} textures, shown from head to toe against a plain neutral background, the full arm span visible with both hands entirely inside the frame, both feet entirely inside the frame, and margin around the figure, flat even shadowless lighting, uniform illumination, sharp focus",
            "prompt_negative": _NEG_TPOSE,
            "prompt_instruction": "Describe the character head-to-toe on a plain background with flat even lighting. Do not mention pose or facial expression.",
        },
    },
    # Mesh input for NON-humanoid characters (animals). Same lighting/background
    # goal as "tpose", but the framing is nose-to-tail instead of arm span, and
    # the negatives push away from anthropomorphism.
    "tpose_animal": {
        "keywords": {
            "prompt_style": "render of a realistic 3D animal model, lifelike fur and skin textures, full body view of the animal, nose to tail, all four legs and the tail fully inside the frame, three-quarter side view, margin around the animal, plain neutral background, flat even shadowless lighting, uniform illumination, sharp focus, high detail",
            "prompt_negative": _NEG_TPOSE_ANIMAL,
            "prompt_instruction": "Write comma-separated tags describing the animal's whole body from nose to tail on a plain background with flat even lighting. Do not mention pose or expression.",
        },
        "natural": {
            "prompt_style": "a full-body render of the animal as a realistic 3D creature figure with lifelike fur and skin textures, shown from nose to tail against a plain neutral background, seen from a three-quarter side angle with all four legs and the tail entirely inside the frame and margin around it, flat even shadowless lighting, uniform illumination, sharp focus",
            "prompt_negative": _NEG_TPOSE_ANIMAL,
            "prompt_instruction": "Describe the animal's whole body from nose to tail on a plain background with flat even lighting. Do not mention pose or expression.",
        },
    },
    # Optional EXTRA views of the humanoid mesh-input render (enabled per
    # character on the character editor's 3D tab, default off) — the input
    # for multi-view img2mesh backends. Framing/lighting stay identical to
    # "tpose" so the views compose into one consistent set; only the
    # negatives differ, because a back or profile render fails in its own way.
    # _seed_default_use_cases backfills both into existing worlds
    # automatically — no migration needed.
    "tpose_back": {
        "keywords": {
            "prompt_style": "render of a realistic 3D character model, lifelike skin{fabric} textures, full body view, head to toe, full arm span visible with both hands fully inside the frame, both feet fully inside the frame, wide framing with margin around the figure, plain neutral background, flat even shadowless lighting, uniform illumination, sharp focus, high detail",
            "prompt_negative": _NEG_TPOSE_BACK,
            "prompt_instruction": "Write comma-separated tags describing the character head-to-toe seen from behind on a plain background with flat even lighting. Do not mention pose or facial expression.",
        },
        "natural": {
            "prompt_style": "a full-body render of the character as a realistic 3D figure with lifelike skin{fabric} textures, shown from head to toe against a plain neutral background, the full arm span visible with both hands entirely inside the frame, both feet entirely inside the frame, and margin around the figure, flat even shadowless lighting, uniform illumination, sharp focus",
            "prompt_negative": _NEG_TPOSE_BACK,
            "prompt_instruction": "Describe the character head-to-toe seen from behind on a plain background with flat even lighting. Do not mention pose or facial expression.",
        },
    },
    # Shared by the left and the right profile. No arm-span clause here: in a
    # profile one arm points AT the camera and hides the other, so demanding a
    # visible span would only fight the view.
    "tpose_side": {
        "keywords": {
            "prompt_style": "render of a realistic 3D character model, lifelike skin{fabric} textures, full body view, head to toe, both feet fully inside the frame, wide framing with margin around the figure, plain neutral background, flat even shadowless lighting, uniform illumination, sharp focus, high detail",
            "prompt_negative": _NEG_TPOSE_SIDE,
            "prompt_instruction": "Write comma-separated tags describing the character head-to-toe in side profile on a plain background with flat even lighting. Do not mention pose or facial expression.",
        },
        "natural": {
            "prompt_style": "a full-body render of the character as a realistic 3D figure with lifelike skin{fabric} textures, shown from head to toe against a plain neutral background, both feet entirely inside the frame, margin around the figure, flat even shadowless lighting, uniform illumination, sharp focus",
            "prompt_negative": _NEG_TPOSE_SIDE,
            "prompt_instruction": "Describe the character head-to-toe in side profile on a plain background with flat even lighting. Do not mention pose or facial expression.",
        },
    },
    "expression": {
        "keywords": {
            "prompt_style": "RAW photo, natural light, skin texture, detailed face, expressive, high detail",
            "prompt_negative": _NEG_PHOTO,
            "prompt_instruction": "Write comma-separated tags emphasizing the character's facial expression and pose.",
        },
        "natural": {
            "prompt_style": "a candid photo emphasizing the character's facial expression and pose, natural light, high detail",
            "prompt_negative": _NEG_PHOTO,
            "prompt_instruction": "Describe the character emphasizing facial expression and pose.",
        },
    },
    "instagram": {
        "keywords": {
            "prompt_style": "candid smartphone photo, natural light, lifestyle, vibrant, high detail",
            "prompt_negative": _NEG_PHOTO,
            "prompt_instruction": "Write comma-separated tags for a casual lifestyle photo as if posted on Instagram.",
        },
        "natural": {
            "prompt_style": "a casual candid lifestyle photo as if posted on Instagram, natural light",
            "prompt_negative": _NEG_PHOTO,
            "prompt_instruction": "Describe a casual lifestyle photo as if posted on Instagram.",
        },
    },
    "event": {
        "keywords": {
            "prompt_style": "atmospheric scene, dynamic, cinematic lighting, detailed environment, high detail",
            "prompt_negative": _NEG_PHOTO,
            "prompt_instruction": "Write comma-separated tags for an atmospheric scene depicting the event. Focus on the environment.",
        },
        "natural": {
            "prompt_style": "an atmospheric cinematic scene depicting the event, detailed environment, dramatic lighting",
            "prompt_negative": _NEG_PHOTO,
            "prompt_instruction": "Describe an atmospheric scene depicting the event. Focus on the environment.",
        },
    },
    "story": {
        "keywords": {
            "prompt_style": "cinematic scene, dramatic composition, detailed environment, high detail",
            "prompt_negative": _NEG_PHOTO,
            "prompt_instruction": "Write comma-separated tags for a cinematic story scene — subject, action, setting, mood.",
        },
        "natural": {
            "prompt_style": "a cinematic story scene with dramatic composition and detailed environment",
            "prompt_negative": _NEG_PHOTO,
            "prompt_instruction": "Describe a cinematic story scene — subject, action, setting, mood.",
        },
    },
}


# ── Key-area prompt fragments (spec-picture-props.md § 3) ──────────────────
# A frame prop that is meant to take a picture (or a pane of glass) is asked
# for a CHROMA-KEY panel at generation time: the image model paints the
# picture surface a flat green, the glass a flat magenta, and the mesh that
# is baked from that render carries the colour in its atlas — the only marker
# the area detection (``app/core/picture_areas.py``) has. The text lives HERE,
# beside the ``prop`` use case whose prompt it is appended to
# (``props.compose_prompt``), keyed by the area KIND the detection looks for.
# The fragments are appended AFTER the composed prompt (they start with the
# separator), the negatives are merged into the negative prompt.
KEY_AREA_PROMPTS = {
    "picture": (", the picture surface inside the frame is a single flat "
                "uniform bright chroma-key green panel (#00FF00), no "
                "reflections, no artwork, no text"),
    "glass": (", the window pane is a single flat uniform bright magenta "
              "panel (#FF00FF), no reflections"),
}
KEY_AREA_NEGATIVES = {
    "picture": "painting, artwork, photo, poster, landscape in frame",
    "glass": "transparent glass, reflections",
}


def image_model_to_family(image_model: str) -> str:
    """Maps a 'target prompt style' (image_model) to a style family."""
    return _IMAGE_MODEL_FAMILY.get((image_model or "").strip(), "keywords")


#: What ``{fabric}`` becomes for a DRESSED character. A style names the
#: materials the render should show, and on a figure wearing nothing there is
#: no fabric to show — the words alone are enough to make a model drape cloth
#: over it. Undressed the slot collapses to nothing, so the sentence still
#: reads ("lifelike skin textures"). A style WITHOUT the placeholder is left
#: exactly as written — an admin who edits the text keeps what they typed.
FABRIC_CLAUSE = " and fabric"


def get_use_case_prompts(use_case: str, image_model: str = "",
                         clothed: bool = True) -> dict:
    """Resolves style / negative / instruction for a use case + target style.

    Priority per field: admin override (config) -> built-in default
    (_DEFAULT_IMAGE_USE_CASES[use_case][family]) -> "" (the caller then falls
    back to the workflow style). Always returns a dict with the three keys
    (values may be empty).

    ``clothed=False`` renders the ``{fabric}`` slot empty (see FABRIC_CLAUSE).
    THE one place every style passes through, so no caller can leak a raw
    placeholder into a prompt; the default keeps the clause for every path
    that does not know the character's state.

    Profile portraits are outfit-independent identity references: the whole
    head and complete hairstyle fit with margin; only a short neck is shown.
    Long hair remains fully visible against the background without adding
    shoulders or a bust. This also applies to custom styles; fabric stays empty.
    """
    uc = (use_case or "").strip() or "character"
    family = image_model_to_family(image_model)
    fields = ("prompt_style", "prompt_negative", "prompt_instruction")
    builtin = (_DEFAULT_IMAGE_USE_CASES.get(uc, {}) or {}).get(family, {}) or {}
    fabric = FABRIC_CLAUSE if clothed and uc != "profile" else ""
    out = {}
    for f in fields:
        override = get(f"image_generation.use_cases.{uc}.styles.{family}.{f}", "")
        text = (override or "").strip() or (builtin.get(f, "") or "")
        out[f] = text.replace("{fabric}", fabric)
    if uc == "profile":
        # Fit the complete hairstyle independently of the visible body boundary.
        framing = ("whole head and complete hairstyle fully inside the frame, "
                   "including the hair crown, ears, loose strands and all hair tips, "
                   "preserve the full authored hair length without cutting or "
                   "shortening the hairstyle, zoom out enough to leave generous "
                   "plain neutral background margin above, beside and below "
                   "the entire hair silhouette, only a short straight upper-neck "
                   "stump ending horizontally below the jaw and above the "
                   "shoulder line, narrow straight-sided neck base, long hair "
                   "may extend below the neck base against plain neutral "
                   "background with no body behind it, preserve hair colour, "
                   "texture and hairstyle, no shoulders, chest, torso or "
                   "visible clothing")
        out["prompt_style"] = f"{out['prompt_style']}, {framing}"
        out["prompt_negative"] = (
            f"{out['prompt_negative']}, cropped hair, cut off hair tips, truncated hairstyle, cropped crown, cut off top of head, head out of frame, extreme close-up, long neck, flared neck base, rounded bust base, shoulders, chest, torso, upper body, clothing, shirt, blouse, jacket, collar, straps"
        )
        out["prompt_instruction"] = (
            f"{out['prompt_instruction']} Keep the portrait outfit-independent: "
            f"{framing}. Do not add an outfit or show the full body."
        )
    return out


def get_lora_trigger_words(lora_names) -> list:
    """Activation words for the active LoRAs (from the per-world library
    ``image_generation.lora_triggers`` = [{lora, word, …}, …]). Matches by file
    name (basename too, in case path/extension differ slightly). Library order,
    duplicates removed.
    """
    if not lora_names:
        return []
    triggers = get("image_generation.lora_triggers", []) or []
    if not isinstance(triggers, list):
        return []
    want = set()
    for n in lora_names:
        n = (n or "").strip()
        if n:
            want.add(n)
            want.add(os.path.basename(n))
    out, seen = [], set()
    for e in triggers:
        if not isinstance(e, dict):
            continue
        lora = (e.get("lora") or "").strip()
        word = (e.get("word") or "").strip()
        if not (lora and word):
            continue
        if (lora in want or os.path.basename(lora) in want) and word not in seen:
            seen.add(word)
            out.append(word)
    return out


def get_lora_options(backend_name: str, lora_filter: str = "") -> list:
    """LoRA options for ONE backend from the consolidated LoRA library
    (``image_generation.lora_triggers`` = [{lora, word, source, backends,
    missing_on}, …]). Selection is backend-scoped (user decision 2026-07-16).

    Returns ``[{"name": str, "missing": bool}, …]``, sorted by name:

    - entries whose ``backends`` contain ``backend_name``; ``missing`` is True
      when the sync flagged the backend in ``missing_on`` (manual/touched
      entries only — they stay offered, marked "(missing)" in the dialogs).
    - manual entries with ``backends == []`` ("all backends").
    - ``lora_filter`` (e.g. "Qwen*"): case-insensitive glob applied to the
      name — mirrors the backend's ``lora_filter`` so "all backends" entries
      of foreign model families don't leak into the dropdowns.
    """
    import fnmatch
    triggers = get("image_generation.lora_triggers", []) or []
    if not isinstance(triggers, list):
        return []
    _pat = (lora_filter or "").strip().lower()
    out, seen = [], set()
    for e in triggers:
        if not isinstance(e, dict):
            continue
        lora = (e.get("lora") or "").strip()
        if not lora or lora in seen:
            continue
        backends = [str(x) for x in (e.get("backends") or []) if x]
        if backends and backend_name not in backends:
            continue
        if not backends and (e.get("source") or "manual") == "discovered":
            continue  # discovered entries always carry their backends
        if _pat and not fnmatch.fnmatch(lora.lower(), _pat):
            continue
        seen.add(lora)
        out.append({"name": lora,
                    "missing": backend_name in (e.get("missing_on") or [])})
    out.sort(key=lambda o: o["name"].lower())
    return out


def use_case_llm_compose(use_case: str) -> bool:
    """True when this use case composes its prompt through the LLM stage.

    Same read semantics as the styles: world override -> seeded default
    (False). Opt-in only — the mechanical composer stays the base, the LLM
    stage runs on ITS result (app/core/prompt_compose_llm.py).
    """
    uc = (use_case or "").strip()
    if not uc:
        return False
    return bool(get(f"image_generation.use_cases.{uc}.llm_compose", False))


def resolve_use_case_style(use_case: str, image_family: str = "",
                           backend_model: str = "",
                           backend_family: str = "",
                           clothed: bool = True) -> dict:
    """Convenience wrapper for all generate paths. Family priority:
    explicit ``image_family`` → backend ``image_family`` → heuristic from
    the backend model name (get_target_model). Returns
    {prompt_style, prompt_negative, prompt_instruction} for the use case.
    ``clothed`` is handed straight to get_use_case_prompts.
    """
    from app.core.prompt_adapters import get_target_model
    fam = (image_family or "").strip() or (backend_family or "").strip()
    target = get_target_model(fam, backend_model or "")
    return get_use_case_prompts(use_case, target, clothed=clothed)


# Example LLM providers a FRESH instance starts with (E11, user decision
# 2026-10-04): the two common local servers, so the providers page and the
# LLM routing have something to point at on first start. Only name / type /
# api_base — everything else is schema default. A provider the admin edits,
# adds or deletes makes the whole list the instance's own (a list is one
# value); an emptied list stays empty.
_DEFAULT_PROVIDERS = [
    {"name": "ollama-local", "type": "ollama", "api_base": "http://localhost:11434/v1"},
    {"name": "openai-compatible-local", "type": "openai", "api_base": "http://localhost:8080/v1"},
]


def _seed_default_providers(config: dict) -> bool:
    """Seeds the example providers when the instance names none.

    Idempotent: only fires when ``providers`` is absent — which is also what
    a pruned instance file stores for the shipped list. ``[]`` stays empty.
    In-memory only — see `migrate_file()` for the disk side.
    """
    if "providers" in config:
        return False
    import copy
    config["providers"] = copy.deepcopy(_DEFAULT_PROVIDERS)
    return True


_DEFAULT_MARKETPLACE_CATALOGS = [
    {
        "name": "Anima-Verse Public",
        "url": "https://github.com/KaletoAI/anima-verse-content",
        "auth_token": "",
        "enabled": True,
    },
]


def _seed_default_marketplace_catalogs(config: dict) -> bool:
    """Seeds the public catalog when the instance layer names none.

    Idempotent: only fires when `content_marketplace.catalogs` is absent —
    which is also what a pruned layer file stores for the shipped catalog.
    If the admin clears the list to [], it stays empty — explicit choice
    beats implicit re-seeding.

    In-memory only — see `migrate_file()` for the disk side.
    """
    cm = config.setdefault("content_marketplace", {})
    if "catalogs" in cm:
        return False
    import copy
    cm["catalogs"] = copy.deepcopy(_DEFAULT_MARKETPLACE_CATALOGS)
    return True


# Mesh (img2mesh) backends a BRAND-NEW world starts with — the gateway alias
# catalog of mesh-client-spec § 3.2/3.3, one entry per alias. face_num carries
# the family default (0/absent = let the alias decide, which is what the splat
# pipeline needs), face_num_max the ceiling of a family that HANGS instead of
# failing above it. Only mesh-relevant fields are seeded; everything else is
# schema default. Nothing here is retro-written into an existing world — a
# world's backend list belongs to its admin.
_MESH_GATEWAY_URL = "http://192.168.8.10:4000"
# Mesh→mesh alias: reduces an EXISTING mesh (category "mesh2mesh"), the
# "Create low variant" action of the model galleries. Deliberately only
# `mesh-shrink`: the quad remesher `mesh-shrink-quad` works but treats
# `input_face_num` as a rough guide only (5000 requested measured as ~38000
# triangles, mesh-client-spec § 3.4) — a low variant needs a PREDICTABLE
# target size, which `mesh-shrink` hits.
_DEFAULT_SHRINK_BACKEND = ("mesh-shrink", "mesh2mesh", 1, 5000, 0, 0)

_DEFAULT_MESH_BACKENDS = [
    # (alias, category, cost, face_num, face_num_max, max_concurrent)
    ("Trellis2-Low", "img2mesh", 1, 20000, 0, 0),
    ("Trellis2-High", "img2mesh", 2, 20000, 0, 0),
    ("Pixal3D", "img2mesh", 3, 50000, 0, 2),
    ("Triposplat", "img2mesh", 1, 0, 0, 0),
    ("Hunyuan3D", "img2mesh", 2, 40000, 40000, 0),
    ("mesh-mia", "mesh2rig", 0, 0, 0, 0),
    ("mesh-rig-unirig", "mesh2rig", 0, 0, 0, 0),
]


    ("GLB-Face-Retexture", "face_retexture", 1, 0, 0, 0),
def _default_mesh_backend_entries() -> list:
    """The seed list as config dicts (img2mesh, mesh2rig and mesh2mesh)."""
    out = []
    for name, category, cost, faces, faces_max, concurrent in (
            [*_DEFAULT_MESH_BACKENDS, _DEFAULT_SHRINK_BACKEND]):
        entry = {
            "name": name,
            "enabled": True,
            "api_type": "openai_mesh",
            "api_url": _MESH_GATEWAY_URL,
            "api_key": "",
            "model": name,
            "category": category,
            "cost": cost,
            "timeout": 3600,
            "poll_interval": 2,
            "max_concurrent": concurrent,
            "remove_background": True,
            "no_fingers": False,
        }
        if faces:
            entry["face_num"] = faces
        if faces_max:
            entry["face_num_max"] = faces_max
        out.append(entry)
    return out


def _seed_default_mesh_backends(config: dict) -> bool:
    """Seeds the mesh backend catalog (img2mesh + mesh2mesh) as the backend
    list when ``image_generation.backends`` is MISSING.

    The seed list is the shipped default of ``image_generation.backends``
    (``config_scope.shipped_default``): a layer file stores the list only when
    it differs from the seed, so a missing key means "the shipped list" and
    this brings it back. A list the admin edited — emptied to ``[]``
    included — is in the file and is never touched: appending aliases to it
    would resurrect entries they deleted on purpose.

    In-memory only — see `migrate_file()` for the disk side.
    """
    ig = config.setdefault("image_generation", {})
    if "backends" in ig:
        return False
    ig["backends"] = _default_mesh_backend_entries()
    logger.info("Default mesh backends seeded (%d)",
                len(_DEFAULT_MESH_BACKENDS) + 1)
    return True


def _migrate_backend_categories(config: dict) -> bool:
    """One-time rename of the backend category ``generate`` -> ``txt2img``.

    The category vocabulary became explicit about the direction of the alias
    (txt2img / img2img / inpaint / img2mesh). Nothing ever branched on the old
    ``generate`` value (only ``inpaint`` carries behaviour), so this is a pure
    label migration — image-to-image aliases can be re-tagged in the admin.

    In-memory only — see `migrate_file()` for the disk side.
    """
    backends = (config.get("image_generation") or {}).get("backends") or []
    changed = False
    for be in backends:
        if isinstance(be, dict) and be.get("category") == "generate":
            be["category"] = "txt2img"
            changed = True
    if changed:
        logger.info("Backend categories migrated: 'generate' -> 'txt2img'")
    return changed


def _migrate_lora_triggers(config: dict) -> bool:
    """One-time consolidation of the LoRA library to one entry per LoRA.

    Old shape: one entry per (lora, endpoint) pair — ``{lora, word, endpoint,
    source, missing}``. New shape (user decision 2026-07-16): one entry per
    unique LoRA name — ``{lora, word, source, backends, missing_on}``.

    Merge rules per name group (in list order): first non-empty ``word`` wins
    (dropped alternatives are logged once); ``source`` is manual when any
    member was manual or user-touched (non-empty word); ``backends`` is the
    union of the non-empty endpoints — unless a member had the empty endpoint
    ("all backends"), which wins as ``backends: []``; ``missing_on`` collects
    the endpoints of members flagged missing.

    In-memory only — see `migrate_file()` for the disk side.
    """
    ig = config.get("image_generation") or {}
    triggers = ig.get("lora_triggers")
    if not isinstance(triggers, list):
        return False
    if not any(isinstance(e, dict) and "endpoint" in e for e in triggers):
        return False  # already in the consolidated shape (or empty)

    merged: dict = {}
    order: list = []
    for e in triggers:
        if not isinstance(e, dict):
            continue
        name = (e.get("lora") or "").strip()
        if not name:
            continue
        word = (e.get("word") or "").strip()
        endpoint = (e.get("endpoint") or "").strip()
        manual = (e.get("source") or "manual").strip() != "discovered" or bool(word)
        entry = merged.get(name)
        if entry is None:
            entry = {"lora": name, "word": word,
                     "source": "manual" if manual else "discovered",
                     "backends": [], "missing_on": [], "_all": False}
            merged[name] = entry
            order.append(name)
        else:
            if word and not entry["word"]:
                entry["word"] = word
            elif word and entry["word"] and word != entry["word"]:
                logger.info("LoRA library migration: '%s' keeps word '%s', "
                            "drops '%s'", name, entry["word"], word)
            if manual:
                entry["source"] = "manual"
        if not endpoint:
            entry["_all"] = True
        else:
            if endpoint not in entry["backends"]:
                entry["backends"].append(endpoint)
            if e.get("missing") and endpoint not in entry["missing_on"]:
                entry["missing_on"].append(endpoint)
    for entry in merged.values():
        if entry.pop("_all"):
            entry["backends"] = []
            entry["missing_on"] = []

    ig["lora_triggers"] = [merged[n] for n in order]
    logger.info("LoRA library migrated: %d entries -> %d unique",
                len(triggers), len(order))
    return True


def _seed_default_use_cases(config: dict) -> bool:
    """Creates the use-case prompt structure (empty fields, 2 families per use case).

    The fields stay EMPTY — the built-in defaults (_DEFAULT_IMAGE_USE_CASES)
    apply as the resolver fallback and show as a grey placeholder in the admin
    UI. Only the structure is seeded, so the admin can see/edit/extend the
    entries. Idempotent + backfill of missing use cases. Returns True when
    something changed.

    In-memory only — see `migrate_file()` for the disk side.
    """
    import copy
    ig = config.setdefault("image_generation", {})
    uc_cfg = ig.setdefault("use_cases", {})
    empty_fields = {"prompt_style": "", "prompt_negative": "", "prompt_instruction": ""}
    changed = False
    for uc in _DEFAULT_IMAGE_USE_CASES:
        entry = uc_cfg.setdefault(uc, {})
        styles = entry.setdefault("styles", {})
        # Opt-in LLM composition per use case (sibling of styles, default off —
        # it costs a call and latency, so it is never implicit).
        if "llm_compose" not in entry:
            entry["llm_compose"] = False
            changed = True
        for fam in _PROMPT_STYLE_FAMILIES:
            if fam not in styles:
                styles[fam] = copy.deepcopy(empty_fields)
                changed = True
    if changed:
        logger.info("Use-case prompt structure seeded/extended")
    return changed


def _strip_legacy_imagegen_prompt_fields(config: dict) -> bool:
    """Removes the old style fields that now live in the use cases.

    - Backends:  prompt_prefix / negative_prompt
    They are functionally dead already (no env mirror, no reader left) — this
    only tidies up config.json. Idempotent.

    In-memory only — see `migrate_file()` for the disk side.
    """
    ig = config.get("image_generation", {})
    changed = False
    for be in (ig.get("backends", []) or []):
        if isinstance(be, dict):
            for k in ("prompt_prefix", "negative_prompt"):
                if k in be:
                    del be[k]; changed = True
            # ``supports_negative_prompt`` lived as a bool for one day
            # (2026-08-18) before it became the auto/yes/no select: a stored
            # True was the materialised default of that day, not a decision,
            # and is wrong for every natural-family model -> "auto"; a stored
            # False was an explicit untick -> "no". One-time normalisation.
            v = be.get("supports_negative_prompt")
            if v is True or v is None and "supports_negative_prompt" in be:
                be["supports_negative_prompt"] = "auto"; changed = True
            elif v is False:
                be["supports_negative_prompt"] = "no"; changed = True
    # Scattered prefix/suffix fields -> now part of the use cases.
    for k in ("profile_image_prompt_prefix", "outfit_image_prompt_prefix",
              "map_2d_image_prompt_suffix"):
        if k in ig:
            del ig[k]; changed = True
    if changed:
        logger.info("Legacy image-gen style fields removed (workflow/backend)")
    return changed


# Config fields whose feature was removed: no schema entry, no reader, no
# writer anywhere in app/ frontend/ client3d/ packages/ plugins/ — they only
# sat in the per-world config.json and misled whoever read it. Grouped by
# section; the strip below is the single place that knows them.
#   image_generation — ComfyUI era (comfy_default_workflow, comfyui_workflows,
#     unet_weight_dtype), the removed grid-map fit/edge pipeline (mapfit_*,
#     map_image_prompt_suffix, map_tile_vision_analysis, commit 245f1bf) and
#     the dropped collage scene mode (scene_prompt_collage — its living
#     siblings scene_prompt_multi_ref / scene_prompt_only_background stay),
#     leftovers that only sat in world files (context_render_*,
#     scene_asset_rembg, tpose_view_*) and the prompt-enhancer template
#     rebuild_llm_system_template (schema field + env bridge, read by nobody).
#   chat / random_events — single leftovers.
#   server — jwt_secret (see below) and storage_dir: the world is selected by
#     paths.init() / STORAGE_DIR BEFORE any config is read, so the bridged
#     value selected nothing.
DEAD_CONFIG_FIELDS: dict = {
    "image_generation": (
        "comfy_default_workflow",
        "comfyui_workflows",
        "mapfit_backend",
        "mapfit_workflow_file",
        "mapfit_imagegen_default",
        "map_image_prompt_suffix",
        "map_tile_vision_analysis",
        "unet_weight_dtype",
        "scene_prompt_collage",
        "context_render_grid",
        "context_render_figure",
        "scene_asset_rembg",
        "tpose_view_back",
        "tpose_view_left",
        "tpose_view_right",
        "rebuild_llm_system_template",
    ),
    "chat": ("auto_wake_stamina",),
    # Sessions are opaque random tokens (app/core/sessions.py), nothing signs
    # a JWT — the field was schema, validator warning and env bridge only.
    "server": ("jwt_secret", "storage_dir"),
    "random_events": ("event_image_denoise_strength",),
}

# Dead names that no section owns any more and that only survive at the TOP
# LEVEL of older world files (worlds/hotopia predates the sectioning). Item
# image size runs through ui.downscale_item_max_dim instead; "inventory" is no
# schema section, so a section variant is not swept here.
DEAD_TOPLEVEL_ONLY_FIELDS: tuple = ("item_image_width", "item_image_height")

# The section names again, this time at the TOP LEVEL of config.json, plus the
# top-level-only names above. None of the dead names is a living top-level key
# (they have no schema entry anywhere), so sweeping all of them at both depths
# is safe and keeps the lists from drifting apart.
DEAD_TOPLEVEL_FIELDS: tuple = tuple(sorted(
    {k for keys in DEAD_CONFIG_FIELDS.values() for k in keys}
    | set(DEAD_TOPLEVEL_ONLY_FIELDS)))


def _strip_dead_config_fields(config: dict) -> bool:
    """Removes the DEAD_CONFIG_FIELDS from the config dict.

    Sweeps both depths: inside the owning section AND at the top level, where
    worlds older than the sectioning still carry some of them.

    Same pattern as _strip_legacy_imagegen_prompt_fields: no fallback reader,
    no alias — the fields are gone from code, so they go from the world file
    too. Idempotent; returns True only when something was actually removed.

    In-memory only — see `migrate_file()` for the disk side.
    """
    changed = False
    for section, keys in DEAD_CONFIG_FIELDS.items():
        sec = config.get(section)
        if not isinstance(sec, dict):
            continue
        for key in keys:
            if key in sec:
                del sec[key]
                changed = True
    for key in DEAD_TOPLEVEL_FIELDS:
        if key in config:
            del config[key]
            changed = True
    if changed:
        logger.info("Dead config fields removed (feature gone)")
    return changed


# Use-case entries whose render occasion no longer exists. They sit one level
# deeper than DEAD_CONFIG_FIELDS (image_generation.use_cases.<name>), so the
# flat strip above walks past them.
#   map / mapfit — removed with the map-icon teardown
#     (plan-rueckbau-2d-karte.md). "map" was the 2D map icon's use case;
#     "mapfit" never had a default nor a reader and only ever reached a
#     config.json by hand.
DEAD_USE_CASES: tuple = ("map", "mapfit")


def _strip_dead_use_cases(config: dict) -> bool:
    """Removes the DEAD_USE_CASES from ``image_generation.use_cases``.

    Runs AFTER the seeding step, which only knows the living use cases and
    therefore never puts these back. Idempotent; returns True only when
    something was actually removed.

    In-memory only — see `migrate_file()` for the disk side.
    """
    ig = config.get("image_generation")
    if not isinstance(ig, dict):
        return False
    use_cases = ig.get("use_cases")
    if not isinstance(use_cases, dict):
        return False
    changed = False
    for name in DEAD_USE_CASES:
        if name in use_cases:
            del use_cases[name]
            changed = True
    if changed:
        logger.info("Dead image use cases removed (render occasion gone)")
    return changed


# ── Image routing (development_instructions/plan-image-routing.md § 2) ────
# The per-occasion default fields the image routing chains replace, in chain
# order per occasion. Read ONCE, while image_generation.routing does not exist
# yet; the same function then removes the old fields (_IMAGE_ROUTING_LEGACY_FIELDS).
_IMAGE_ROUTING_SEED: tuple = (
    ("profile", ("image_generation.profile_imagegen_default",)),
    ("expression", ("image_generation.expression_imagegen_default",
                    "image_generation.outfit_imagegen_default")),
    ("tpose", ("image_generation.expression_imagegen_default",
               "image_generation.outfit_imagegen_default")),
    ("location", ("image_generation.location_imagegen_default",)),
    ("timevariant", ("image_generation.timevariant_imagegen_default",)),
    ("prop", ("image_generation.prop_imagegen_default",)),
    ("scene_view", ("image_generation.scene_imagegen_default",
                    "image_generation.location_imagegen_default")),
    ("event", ("random_events.event_imagegen_default",
               "image_generation.scene_imagegen_default",
               "image_generation.location_imagegen_default")),
    ("photo", ("story_engine.imagegen_default",)),
    ("frame", ("messaging_frame.target",)),
    ("instagram", ("skills.instagram.imagegen_default",)),
)
_IMAGE_ROUTING_MESH_FIELD = "image_generation.mesh_imagegen_default"

# Every old field the chains replace — removed by the migration itself,
# independent of the marker (a world booted in phase R1 already holds the
# seeded routing AND the old fields).
_IMAGE_ROUTING_LEGACY_FIELDS: tuple = tuple(dict.fromkeys(
    [f for _occ, fields in _IMAGE_ROUTING_SEED for f in fields]
    + [_IMAGE_ROUTING_MESH_FIELD]))


def _pop_dotted(config: dict, dotted: str) -> bool:
    *parents, key = dotted.split(".")
    node: Any = config
    for part in parents:
        node = node.get(part) if isinstance(node, dict) else None
        if not isinstance(node, dict):
            return False
    if key not in node:
        return False
    del node[key]
    return True


def _dotted_value(config: dict, dotted: str) -> Any:
    node: Any = config
    for part in dotted.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node


def _legacy_route_spec(value: Any) -> str:
    """An old default value as a chain entry: the legacy ``workflow:`` prefix
    rewritten like ``workflow_spec_migration``, ``backend:`` dropped."""
    from app.core.workflow_spec_migration import strip_legacy_workflow_prefix
    if not isinstance(value, str):
        return ""
    s = str(strip_legacy_workflow_prefix(value) or "").strip()
    if s.lower().startswith("backend:"):
        s = s[len("backend:"):].strip()
    return s


def _mesh_routing_occasions(glob: str, backends: Any) -> list:
    """A matching img2mesh backend serves all four mesh occasions."""
    import fnmatch
    from app.imagegen.routing import describe_config_backend
    for b in backends or []:
        if not isinstance(b, dict):
            continue
        kind = describe_config_backend(b)
        if (kind["media"] == "mesh" and kind["category"] == "img2mesh"
                and fnmatch.fnmatch(kind["name"].lower(), glob.lower())):
            return ["mesh_humanoid", "mesh_creature", "mesh_object", "mesh_building"]
    return []


def _migrate_image_routing(config: dict) -> bool:
    """Seed ``image_generation.routing`` from the old per-occasion default
    fields ONCE (marker: the routing dict exists), then remove the old fields
    — every run, so a world seeded in phase R1 loses them too. Idempotent.
    Runs FIRST in ``_apply_file_migrations`` and normalises the legacy
    ``workflow:``/``backend:`` prefixes itself."""
    changed = False
    ig = config.get("image_generation")
    if not isinstance(ig, dict):
        ig = {}
    if not isinstance(ig.get("routing"), dict):
        routing: dict = {}
        for occasion, fields in _IMAGE_ROUTING_SEED:
            chain: list = []
            for dotted in fields:
                spec = _legacy_route_spec(_dotted_value(config, dotted))
                if spec and spec.lower() not in {c.lower() for c in chain}:
                    chain.append(spec)
            if chain:
                routing[occasion] = chain
        mesh = _legacy_route_spec(_dotted_value(config, _IMAGE_ROUTING_MESH_FIELD))
        if mesh:
            targets = _mesh_routing_occasions(mesh, ig.get("backends"))
            if not targets:
                logger.warning("Image routing: the old mesh default %r matches no "
                               "img2mesh backend — not migrated", mesh)
            for occasion in targets:
                routing[occasion] = [mesh]
        ig["routing"] = routing
        config["image_generation"] = ig
        logger.info("Image routing seeded from the old default fields: %s",
                    routing or "(no chains)")
        changed = True
    removed = [d for d in _IMAGE_ROUTING_LEGACY_FIELDS if _pop_dotted(config, d)]
    if removed:
        logger.info("Image routing: old default fields removed: %s", ", ".join(removed))
        changed = True
    return changed


def _migrate_mesh_rig_split(config: dict) -> bool:
    """Seed empty rig chains from old declarations, then drop the field once.

    Never enable or disable entries: previously disabled combined aliases stay
    disabled, and fresh img2mesh aliases are unrigged by definition.
    """
    ig = config.get("image_generation") or {}
    entries = ig.get("backends")
    if not isinstance(entries, list):
        return False
    changed = False
    routing = ig.get("routing")
    for occasion, rig in (("rig_humanoid", "mixamo"), ("rig_creature", "generic")):
        # Preserve malformed stored roots for the admin repair surface.
        if routing is not None and not isinstance(routing, dict):
            continue
        if (routing or {}).get(occasion):
            continue
        eligible = [b for b in entries if isinstance(b, dict)
                    and str(b.get("api_type") or "").strip().lower() == "openai_mesh"
                    and str(b.get("category") or "").strip().lower() == "mesh2rig"
                    and b.get("enabled", True) is not False
                    and str(b.get("mesh_rig") or "").strip().lower() == rig
                    and b.get("name")]
        if eligible:
            if routing is None:
                routing = ig["routing"] = {}
            routing[occasion] = [b["name"] for b in sorted(
                eligible, key=lambda b: float(b.get("cost") or 0))]
            changed = True
    for entry in entries:
        if isinstance(entry, dict) and "mesh_rig" in entry:
            del entry["mesh_rig"]
            changed = True
    return changed


def _apply_file_migrations(config: dict) -> bool:
    """Runs every load-time normalisation over ``config``, IN MEMORY.

    ``config`` is the UNION of both layers (instance + world): a migration
    may read a field of one layer and write the other (the image routing
    chains are instance data seeded from old fields, some of them world
    fields), so it runs once on the joined dict, never per layer.

    Strip (dead/legacy fields) + seed (use-case blocks, marketplace catalog,
    mesh backend catalog — each only where its key is MISSING, which is what
    a pruned layer file stores for a shipped default) + the two one-time
    renames. Every step is idempotent. Returns True when any step changed
    something — informational only: ``_migrate_image_routing`` re-seeds the
    pruned ``routing: {}`` on every load, so this flag is never a reason to
    write a file. Writers compare content (``_write_if_changed``).

    This is the shared body of `load()` (which never touches disk) and
    `migrate_file()` (which persists the very same result).
    """
    changed = False
    if _migrate_image_routing(config):
        changed = True
    if _seed_default_use_cases(config):
        changed = True
    if _seed_default_mesh_backends(config):
        changed = True
    if _strip_legacy_imagegen_prompt_fields(config):
        changed = True
    if _strip_dead_config_fields(config):
        changed = True
    if _strip_dead_use_cases(config):
        changed = True
    if _seed_default_marketplace_catalogs(config):
        changed = True
    if _seed_default_providers(config):
        changed = True
    if _migrate_backend_categories(config):
        changed = True
    if _migrate_mesh_rig_split(config):
        changed = True
    if _migrate_lora_triggers(config):
        changed = True
    return changed


# ── The two layers on disk ────────────────────────────────────────────────

class ConfigWriteRefused(RuntimeError):
    """A write was refused before writing: an unreadable layer file or a
    missing instance path would lose settings. Admin routes answer with 409."""


class InstanceConfigMissing(RuntimeError):
    """The instance config does not exist yet while the world config still
    carries instance settings — the server must not start (it would run
    without them, and the first admin save would drop them for good)."""


def _read_json_file(path: Path) -> dict:
    """The JSON object stored in ``path``; ``{}`` when the file is missing.

    Raises ``ValueError`` when the file exists but holds no readable JSON
    object — callers decide whether that is fatal.
    """
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        raise ValueError(f"cannot read {path}: {e}") from e
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not a JSON object")
    return data


def _resolve_instance_path(instance_path: Optional[Path]) -> Optional[Path]:
    """Argument > the initialised instance directory > None (no layer)."""
    if instance_path:
        return Path(instance_path)
    if paths.instance_initialised():
        return paths.get_instance_config_path()
    return None


def _layer_with_secrets(path: Path, strict: bool) -> dict:
    """One layer's config.json with ITS OWN secrets.json overlaid.

    Unreadable files are logged and read as empty — unless ``strict``, then
    the ``ValueError`` propagates (a writer must not replace a file it could
    not read).
    """
    data: dict = {}
    for i, f in enumerate((path, path.parent / "secrets.json")):
        try:
            part = _read_json_file(f)
        except ValueError as e:
            if strict:
                raise
            logger.error("Failed to load config: %s", e)
            continue
        if i == 0:
            data = part
            if not f.exists():
                logger.info("Config file not found: %s — this layer is empty", f)
        elif part:
            _deep_merge(data, part, secrets_from=f)
    return data


def _split_keys(part: dict, prefix: tuple = ()) -> list:
    """The dotted keys at which ``split_by_scope`` cut ``part`` — a mixed
    node is descended, every other value is one key."""
    out = []
    for key, value in part.items():
        parts = prefix + (str(key),)
        dotted = ".".join(parts)
        if isinstance(value, dict) and config_scope.child_scopes_differ(dotted):
            out.extend(_split_keys(value, parts))
        else:
            out.append(dotted)
    return out


def _key_list(part: dict, limit: int = 8) -> str:
    """``_split_keys`` for a message: the first ``limit`` keys, then a count."""
    keys = _split_keys(part)
    more = f" and {len(keys) - limit} more" if len(keys) > limit else ""
    return ", ".join(keys[:limit]) + more


def _read_layer(path: Path, layer: str, strict: bool = False) -> dict:
    """Read one layer and keep only what its scope owns.

    An unknown root key is ignored with one warning each. Keys of the other
    layer's scope are ignored with ONE warning per file (count, the first
    few names, what to do) — an unmigrated world carries dozens of them, and
    one line per key would bury the boot log; the single keys are logged at
    DEBUG. The file is not changed here; the next save or ``migrate_file``
    drops them from it.
    """
    data = _layer_with_secrets(path, strict)
    inst, world, unknown = config_scope.split_by_scope(data)
    own, foreign = (inst, world) if layer == config_scope.INSTANCE else (world, inst)
    for root in unknown:
        logger.warning("Config %s: unknown root key '%s' ignored", path, root)
    other = (config_scope.WORLD if layer == config_scope.INSTANCE
             else config_scope.INSTANCE)
    keys = _split_keys(foreign)
    if keys:
        hint = ("move them with scripts/migrate_instance_config.py"
                if layer == config_scope.WORLD
                else "the next save drops them from this file")
        logger.warning("Config %s: %d key(s) belong to the %s config and are "
                       "ignored (%s) — %s", path, len(keys), other,
                       _key_list(foreign, limit=5), hint)
        for key in keys:
            logger.debug("Config %s: '%s' belongs to the %s config — ignored",
                         path, key, other)
    return own


def _compose(world_path: Path, instance_path: Optional[Path],
             strict: bool = False) -> dict:
    """Both layers, read fresh, joined and migrated — the in-memory config
    before the calendar materialization.

    The migrations see only what survived the split: legacy instance fields
    in a WORLD file (``image_generation.*_imagegen_default``, providers, a
    world secrets.json) are foreign-scope and dropped before
    ``_migrate_image_routing`` could read them. Moving an old world over is
    therefore the migration script's job — it runs the migrations on the raw,
    unsplit union and carries the world's secrets into the instance."""
    union = (_read_layer(instance_path, config_scope.INSTANCE, strict)
             if instance_path is not None else {})
    # The two parts are disjoint (split by scope), so the merge only joins
    # the dicts of mixed nodes.
    _deep_merge(union, _read_layer(world_path, config_scope.WORLD, strict))
    _apply_file_migrations(union)
    return union


def _json_equal(a: Any, b: Any) -> bool:
    """Same JSON content — key order aside, ``1``/``1.0``/``true`` apart."""
    return (json.dumps(a, sort_keys=True, ensure_ascii=False)
            == json.dumps(b, sort_keys=True, ensure_ascii=False))


def _write_if_changed(path: Path, data: dict) -> bool:
    """Write ``data`` unless the file already holds exactly that content.

    The comparison is on the parsed JSON, never on the text and never on a
    "changed" flag. A missing file counts as different; an existing file that
    cannot be read raises (``_assert_readable``) — it was loaded as empty, so
    writing the in-memory state over it would drop everything it holds.
    """
    if path.exists() and _json_equal(_assert_readable(path), data):
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(path, data)
    logger.info("Config written: %s", path)
    return True


def _assert_readable(path: Path) -> dict:
    """The parsed content of an EXISTING layer file, or ``ConfigWriteRefused``.

    Every writer goes through this before it replaces or deletes a file: a
    file that could not be read was loaded as ``{}`` (non-strict load), and
    overwriting it with the degraded in-memory state would lose its content
    for good. A broken file is the admin's to repair, never ours to replace.
    """
    try:
        return _read_json_file(path)
    except ValueError as e:
        raise ConfigWriteRefused(f"refusing to overwrite unreadable config file — {e}") from e


def _write_layer(path: Path, pruned: dict) -> bool:
    """Persist one layer's pruned part: config.json + its secrets.json.

    An empty secrets part deletes the layer's secrets.json. Returns True
    when any file was written or deleted.
    """
    clean, secrets = _split_secrets(pruned)
    wrote = _write_if_changed(path, clean)
    secrets_path = path.parent / "secrets.json"
    if secrets:
        wrote = _write_if_changed(secrets_path, secrets) or wrote
    elif secrets_path.exists():
        _assert_readable(secrets_path)
        secrets_path.unlink()
        logger.info("Secrets file removed (nothing secret left): %s", secrets_path)
        wrote = True
    return wrote


def _persist(data: dict, world_path: Path,
             instance_path: Optional[Path]) -> tuple:
    """Split ``data`` by scope, prune each part and write what changed.

    Returns ``(wrote, pruned_world_part)``. Unknown root keys are dropped
    (logged). Without an instance path a NON-empty pruned instance part is
    refused with ``ConfigWriteRefused`` before anything is written — writing only
    the world would silently drop those settings.
    """
    inst, world, unknown = config_scope.split_by_scope(data)
    if unknown:
        logger.warning("Config save: unknown root key(s) dropped: %s",
                       ", ".join(unknown))
    inst_pruned = config_scope.prune(inst)
    world_pruned = config_scope.prune(world)
    if instance_path is None and inst_pruned:
        raise ConfigWriteRefused(
            "no instance path — refusing to drop instance settings: "
            + _key_list(inst_pruned))
    # Every target must be readable BEFORE the first write — a refusal in
    # the second layer must not leave the first one already rewritten.
    targets = [Path(world_path)] + ([Path(instance_path)] if instance_path is not None else [])
    for target in targets:
        for f in (target, target.parent / "secrets.json"):
            if f.exists():
                _assert_readable(f)
    wrote = False
    if instance_path is not None:
        wrote = _write_layer(Path(instance_path), inst_pruned)
    wrote = _write_layer(Path(world_path), world_pruned) or wrote
    return wrote, world_pruned


def check_instance_ready(world_path: Path, instance_path: Path) -> None:
    """Refuse to boot while the world still holds the instance settings.

    Raises ``InstanceConfigMissing`` when the world's config.json +
    secrets.json carry instance-scoped values that differ from what ships
    AND the instance holds none: its config.json does not exist, or it and
    its secrets.json prune to nothing (a half-run migration, a world copied
    back from a backup — the next save would silently drop those values).
    A missing world file never blocks (a new world), nor does a world whose
    instance part prunes to nothing (a fresh clone, a world that only ever
    had defaults there). An instance with settings of its own never blocks.

    Strict reads: an unreadable layer file raises ``ValueError`` here.
    """
    world_path = Path(world_path)
    instance_path = Path(instance_path)
    if not world_path.exists():
        return
    if instance_path.exists():
        own = _read_layer(instance_path, config_scope.INSTANCE, strict=True)
        if config_scope.prune(own):
            return
        state = "holds no settings"
    else:
        state = "does not exist"
    data = _layer_with_secrets(world_path, strict=True)
    inst, _world, _unknown = config_scope.split_by_scope(data)
    pending = config_scope.prune(inst)
    if not pending:
        return
    raise InstanceConfigMissing(
        f"The instance config {instance_path} {state}, but the world "
        f"config {world_path} still carries instance settings "
        f"({_key_list(pending)}). Move them into the instance "
        f"first:\n"
        f"  {_migration_command(world_path, instance_path)}")


# The tool's default --worlds-dir; the guard names it only when it differs.
_REPO_WORLDS_DIR = Path(__file__).resolve().parents[2] / "worlds"


def _migration_command(world_path: Path, instance_path: Path) -> str:
    """The migration call that fits THIS world and instance.

    ``--instance`` always (the tool's default is ``<repo>/instance``, the
    server's may be anything via ``--instance`` / ``INSTANCE_DIR``);
    ``--worlds-dir`` only when the world does not live in ``<repo>/worlds``
    (``start.sh --storage``)."""
    worlds_dir = Path(world_path).resolve().parent.parent
    cmd = (f'./.venv/bin/python scripts/migrate_instance_config.py '
           f'--from "{Path(world_path).parent.name}" '
           f'--instance "{Path(instance_path).resolve().parent}"')
    if worlds_dir != _REPO_WORLDS_DIR.resolve():
        cmd += f' --worlds-dir "{worlds_dir}"'
    return cmd


def migrate_file(config_path: Optional[Path] = None,
                 instance_path: Optional[Path] = None) -> bool:
    """Applies the load-time normalisations TO DISK. Returns True if written.

    `load()` is a pure READ path — it normalises only the in-memory config, so
    that merely opening a world (a smoke script, a CLI, an export run) leaves
    the files byte-identical. Persisting is this function's job, and the
    server boot calls it right after `load()`.

    Runs the pipeline of `load()` on FRESH reads of both layers (``_CONFIG``
    is never touched; it carries the materialized calendar) and then the
    write path of `save()`: split by scope, prune, split out the secrets,
    write each file only when its content differs. A missing layer file is
    created — as ``{}`` when its pruned part is empty — so a fresh clone and
    a new world reach a stable state: the next call writes nothing.

    Paths: the world file is the argument, else the remembered world path;
    the instance file is the argument, else the initialised instance
    directory's, else none (then a non-empty instance part raises like
    `save()`). An unreadable layer file skips the whole migration (logged) —
    a file that could not be read is never replaced. When the world file is
    the loaded one, ``game_seasons_are_defaults()`` follows the file
    afterwards, as after `save()` (``_note_seasons_on_disk``).
    """
    with _LOCK:
        world_path = Path(config_path) if config_path else _CONFIG_PATH
        inst_path = _resolve_instance_path(instance_path)
        try:
            union = _compose(world_path, inst_path, strict=True)
        except ValueError as e:
            logger.error("Config migration skipped — %s", e)
            return False
        wrote, world_pruned = _persist(union, world_path, inst_path)
        if Path(world_path).resolve() == Path(_CONFIG_PATH).resolve():
            # The loaded world's file now holds the pruned list — the flag
            # follows the disk exactly as after `save()`.
            _note_seasons_on_disk(world_pruned)
        if wrote:
            logger.info("Config files migrated (strip + seed + prune) -> %s, %s",
                        world_path, inst_path)
        return wrote


def load(config_path: Optional[Path] = None,
         instance_path: Optional[Path] = None, strict: bool = False) -> dict:
    """Load both config layers into ONE in-memory dict.

    Per layer: config.json, then the secrets.json of THE SAME layer on top,
    then only the part that layer's scope owns is kept (a foreign-scope key
    or an unknown root key is ignored with a warning). The two parts are
    joined, the load-time migrations run once on the union, and the result
    populates os.environ for backward compatibility.

    Paths: the world file is ``config_path``, else the last one used. The
    instance file is ``instance_path``, else the initialised instance
    directory's (``paths.init_instance``), else none — a script that opens a
    world without an instance sees no instance settings. Both are
    remembered; `reload()` reads the same pair.

    ``strict`` (the server boot): an existing layer file (config.json or
    secrets.json) that is no readable JSON object raises ``ValueError`` —
    the start ends loudly instead of running on an empty layer. Non-strict
    (scripts) logs the error and reads that file as empty; every writer then
    refuses to replace it (``_assert_readable``). `reload()` keeps the mode.

    READ-ONLY: nothing is written here. `migrate_file()` persists the
    normalisations.
    """
    global _CONFIG, _CONFIG_PATH, _INSTANCE_PATH, _BOOT_RESTART_SNAPSHOT, _LOAD_STRICT
    with _LOCK:
        world_path = Path(config_path) if config_path else _CONFIG_PATH
        inst_path = _resolve_instance_path(instance_path)
        if inst_path is None:
            logger.info("No instance config — loading the world layer only (%s)",
                        world_path)
        cfg = _compose(world_path, inst_path, strict=strict)
        _CONFIG_PATH, _INSTANCE_PATH, _LOAD_STRICT = world_path, inst_path, strict
        logger.info("Config loaded: world %s, instance %s", world_path, inst_path)

        # Populate os.environ for backward compatibility
        _flatten_to_env(cfg)

        # Freeze the boot snapshot of the restart-requiring fields (once only,
        # the first load wins — later reload() calls do not change it).
        if _BOOT_RESTART_SNAPSHOT is None:
            _BOOT_RESTART_SNAPSHOT = _collect_restart_values(cfg)

        # Complete the dict BEFORE it is published: a lock-free reader of
        # _CONFIG must never see it without its calendar.
        _materialize_game_calendar_defaults(cfg)
        _CONFIG = cfg

    _invalidate_config_derived_caches()
    return _CONFIG


# True while `game_seasons` in memory is the SHIPPED default list rather than
# something the world configured. The one-time atmosphere migration needs the
# distinction: on a materialized list no season has an "own" value yet.
_GAME_SEASONS_MATERIALIZED = False


def game_seasons_are_defaults() -> bool:
    """True when the loaded `game_seasons` came from `Calendar.default()`."""
    return _GAME_SEASONS_MATERIALIZED


def _note_seasons_on_disk(world_pruned: dict) -> None:
    """After a write of the world file: the season list is "the shipped
    default" exactly when pruning left it out of that file. One rule for
    `save()` and `migrate_file()` — a default-equal list is pruned, i.e.
    MISSING on disk, which the next `load()` reads as materialized too."""
    global _GAME_SEASONS_MATERIALIZED
    _GAME_SEASONS_MATERIALIZED = "game_seasons" not in world_pruned


def _materialize_game_calendar_defaults(cfg: dict) -> None:
    """Put the shipped calendar into the config IN MEMORY when it has none.

    `game_seasons` is an is_array section, and the admin's schema-default pass
    only fills fields of EXISTING items — an unconfigured world would show an
    empty season list while `get_calendar()` silently runs on
    `Calendar.default()`. Materializing here makes the effective calendar the
    visible one; nothing is written to disk (the next admin save persists it).
    """
    global _GAME_SEASONS_MATERIALIZED
    from app.core.game_time import default_calendar_config, default_seasons_config

    seasons = cfg.get("game_seasons")
    _GAME_SEASONS_MATERIALIZED = not (isinstance(seasons, list) and seasons)
    if _GAME_SEASONS_MATERIALIZED:
        cfg["game_seasons"] = default_seasons_config()

    calendar = cfg.get("game_calendar")
    if not isinstance(calendar, dict) or not calendar:
        cfg["game_calendar"] = default_calendar_config()


def _invalidate_config_derived_caches() -> None:
    """Drop module caches that were built FROM this config.

    The world calendar (`game_calendar`/`game_seasons`) is cached in
    `app.core.game_time` and the game-clock anchors in `app.core.timeutils`;
    both must follow an admin save immediately, or the header keeps showing
    seasons the config no longer has. Imported lazily — those modules import
    config themselves.
    """
    try:
        from app.core.game_time import invalidate_calendar_cache
        invalidate_calendar_cache()
        from app.core import timeutils
        timeutils.invalidate_game_clock_cache()
    except Exception as e:   # never let a cache reset break load/save
        logger.debug("cache invalidation after config change failed: %s", e)


def _collect_restart_values(cfg: dict) -> dict:
    """Reads the current values of every `requires_restart` path from cfg."""
    from app.core.config_schema import iter_restart_required_paths
    result = {}
    for path in iter_restart_required_paths():
        # Paths with '[*]' (array item fields) are resolved against every index
        if "[*]" in path:
            for resolved in _expand_wildcards(cfg, path):
                result[resolved] = _value_at(cfg, resolved)
        else:
            result[path] = _value_at(cfg, path)
    return result


def _value_at(cfg: dict, path: str) -> Any:
    """``get(path)`` against ``cfg`` instead of the loaded config."""
    try:
        return _resolve_path(cfg, path)
    except (KeyError, IndexError, TypeError):
        return None


def _expand_wildcards(cfg: dict, path: str) -> list:
    """Expands '[*]' wildcards against the current array lengths in cfg."""
    if "[*]" not in path:
        return [path]
    prefix, _, rest = path.partition("[*]")
    try:
        arr = _resolve_path(cfg, prefix)
    except (KeyError, IndexError, TypeError):
        return []
    if not isinstance(arr, list):
        return []
    out = []
    for i in range(len(arr)):
        sub = f"{prefix}[{i}]{rest}"
        out.extend(_expand_wildcards(cfg, sub))
    return out


def restart_pending_fields() -> list:
    """Compares the boot snapshot with the current config.

    Returns the list of paths whose values changed since the server start —
    i.e. the ones that do NOT take effect without a restart.
    """
    if _BOOT_RESTART_SNAPSHOT is None:
        return []
    pending = []
    current = _collect_restart_values(_CONFIG)
    # Changed values
    for path, boot_val in _BOOT_RESTART_SNAPSHOT.items():
        if current.get(path) != boot_val:
            pending.append(path)
    # Newly added paths (e.g. a new provider array entry with a
    # restart-requiring field) — a boot value that was empty and now has a
    # value counts as "pending" too.
    for path in current:
        if path not in _BOOT_RESTART_SNAPSHOT and current[path]:
            pending.append(path)
    return sorted(set(pending))


def named_entries(items: Any) -> Optional[dict]:
    """``{name: entry}`` when ``items`` is a NAMED LIST, else None.

    A named list is a list whose entries are ALL dicts with a non-empty,
    unique string ``name`` (providers, image backends, decision endpoints,
    marketplace catalogs). An empty list is a named list without entries.
    It is a pure function of the list content: the secrets file, the merge
    of that file and the admin save all decide with this one helper whether
    entries are matched by name or by position.
    """
    if not isinstance(items, list):
        return None
    out: dict = {}
    for entry in items:
        name = entry.get("name") if isinstance(entry, dict) else None
        if not isinstance(name, str) or not name or name in out:
            return None
        out[name] = entry
    return out


def pair_entries(new: list, current: list) -> list:
    """For every entry of ``new``, its counterpart in ``current`` (or None).

    Two named lists pair by name. A RENAME pairs by index: ``new[i]`` has a
    name ``current`` does not know AND ``current[i]`` has a name ``new`` does
    not know. Any other entry has no counterpart — an entry inserted
    mid-list never inherits from its neighbour. If either list is not a
    named list, entries pair by index.
    """
    new_named = named_entries(new)
    cur_named = named_entries(current)
    if new_named is None or cur_named is None:
        return [current[i] if i < len(current) else None for i in range(len(new))]
    out = []
    for i, entry in enumerate(new):
        name = entry["name"]
        if name in cur_named:
            out.append(cur_named[name])
        elif i < len(current) and current[i]["name"] not in new_named:
            out.append(current[i])
        else:
            out.append(None)
    return out


def _uniquely_named(items: list) -> dict:
    """``{name: entry}`` for the entries of ``items`` whose name is a
    non-empty string no other entry carries — all of them for a named list,
    the pairable part of any other list."""
    by_name: dict = {}
    dupes: set = set()
    for entry in items:
        name = entry.get("name") if isinstance(entry, dict) else None
        if not isinstance(name, str) or not name:
            continue
        if name in by_name:
            dupes.add(name)
        by_name[name] = entry
    for name in dupes:
        by_name.pop(name)
    return by_name


def _deep_merge(base: Any, overlay: Any,
                secrets_from: Optional[Path] = None) -> None:
    """In-place deep merge of overlay into base.

    A list overlay merges element-wise by index. A dict overlay onto a list
    is the by-name form of a named list (``_split_secrets``): each key is
    an entry name; an unknown name is ignored with a warning.

    ``secrets_from`` marks the overlay as that secrets.json, which has the
    parallel shape ``_split_secrets`` writes: a value with no counterpart in
    the config (a missing key, a list entry that is not there) is set only
    when it is a sensitive string; anything else is dropped with a warning
    naming the file — never grafted into the config in a shape the readers
    do not expect.
    """
    src = f" {secrets_from}" if secrets_from is not None else ""

    def _drop(what: str) -> None:
        logger.warning("Config secrets%s: %s has no counterpart in config.json — ignored",
                       src, what)

    if isinstance(base, dict) and isinstance(overlay, dict):
        for k, v in overlay.items():
            if k in base and isinstance(base[k], (dict, list)) and isinstance(v, (dict, list)):
                _deep_merge(base[k], v, secrets_from)
            elif secrets_from is None or (_is_sensitive(k) and isinstance(v, str)):
                base[k] = v
            else:
                _drop(f"'{k}'")
    elif isinstance(base, list) and isinstance(overlay, list):
        for i, v in enumerate(overlay):
            if i < len(base) and isinstance(base[i], (dict, list)) and isinstance(v, (dict, list)):
                _deep_merge(base[i], v, secrets_from)
            elif i < len(base) and secrets_from is None:
                base[i] = v
            elif secrets_from is not None and v not in ({}, []):
                _drop(f"list position {i}")
    elif isinstance(base, list) and isinstance(overlay, dict):
        by_name = _uniquely_named(base)
        if len(by_name) != len(base):
            logger.warning("Config secrets%s: %d of %d list entries have no unique name "
                           "— they take no secrets by name", src,
                           len(base) - len(by_name), len(base))
        for name, v in overlay.items():
            entry = by_name.get(name)
            if entry is None or not isinstance(v, dict):
                logger.warning("Config secrets%s: no list entry named '%s' — ignored", src, name)
                continue
            _deep_merge(entry, v, secrets_from)
    elif secrets_from is not None:
        _drop(f"a {type(overlay).__name__} value")


def _split_secrets(data: Any) -> tuple:
    """Walk data and split sensitive values out.

    Returns (clean, secrets). Sensitive string values are blanked in clean and
    placed into a parallel structure in secrets. A named list
    (``named_entries``) becomes a dict by entry name holding only the entries
    with secrets, so inserting or reordering entries never moves a key to
    another entry. Any other list keeps position; entries without secrets
    become empty dicts/lists in the secrets shape, and a list without any
    secret is dropped.
    """
    if isinstance(data, dict):
        clean: dict = {}
        secrets: dict = {}
        for k, v in data.items():
            if _is_sensitive(k) and isinstance(v, str):
                if v:
                    secrets[k] = v
                clean[k] = ""
            elif isinstance(v, (dict, list)):
                sub_clean, sub_secrets = _split_secrets(v)
                clean[k] = sub_clean
                if sub_secrets:
                    secrets[k] = sub_secrets
            else:
                clean[k] = v
        return clean, secrets

    if isinstance(data, list):
        named = named_entries(data) is not None
        clean_list: list = []
        secrets_list: list = []
        secrets_by_name: dict = {}
        for item in data:
            sub_clean, sub_secrets = _split_secrets(item)
            clean_list.append(sub_clean)
            secrets_list.append(sub_secrets if sub_secrets else {})
            if sub_secrets and named:
                secrets_by_name[item["name"]] = sub_secrets
        if named:
            return clean_list, secrets_by_name
        any_secrets = any(secrets_list)
        return clean_list, (secrets_list if any_secrets else [])

    return data, None


def reload() -> dict:
    """Reload both layers from disk — the world AND instance path of the
    last load (an instance given as an argument is kept, not re-resolved)."""
    with _LOCK:
        return load(_CONFIG_PATH, _INSTANCE_PATH, strict=_LOAD_STRICT)


def get(path: str, default: Any = None) -> Any:
    """Get a config value by dot-notation path.

    Examples:
        config.get("tts.backend")
        config.get("providers[0].name")
        config.get("llm_routing")
    """
    try:
        return _resolve_path(_CONFIG, path)
    except (KeyError, IndexError, TypeError):
        return default


def get_section(path: str) -> dict:
    """Get a config section as a dict."""
    result = get(path, {})
    if isinstance(result, dict):
        return dict(result)
    return {}


def get_all() -> dict:
    """Return the full config dict (for admin API)."""
    return dict(_CONFIG)


def save(data: dict, config_path: Optional[Path] = None) -> None:
    """Save the whole in-memory config into its two layers.

    ``data`` is split by scope (unknown root keys are dropped), each part is
    pruned to what differs from what ships, the sensitive fields go into the
    layer's own secrets.json (gitignored; an empty secrets part deletes the
    file) — and a file is written only when its JSON content differs from
    what is on disk. ``config_path`` is the WORLD file (default: the
    remembered one); the instance file is the one the last `load()` used.

    Without an instance file a non-empty pruned instance part raises
    ``ConfigWriteRefused("no instance path — refusing to drop instance settings")``
    and nothing is written; an empty one is simply not written.

    Admin layer saves strip materialized item defaults before passing the
    candidate here. Lists remain whole values during pruning.
    """
    global _CONFIG
    with _LOCK:
        world_path = Path(config_path) if config_path else _CONFIG_PATH
        _wrote, world_pruned = _persist(data, world_path, _INSTANCE_PATH)
        _CONFIG = data
        _note_seasons_on_disk(world_pruned)
    _invalidate_config_derived_caches()


def save_part(scope: str, part: dict) -> dict:
    """Replace one scope and save the current union under the module lock."""
    with _LOCK:
        inst, world, _unknown = config_scope.split_by_scope(_CONFIG)
        other_scope = config_scope.WORLD if scope == config_scope.INSTANCE else config_scope.INSTANCE
        other_part = copy.deepcopy(world if scope == config_scope.INSTANCE else inst)
        if scope == config_scope.INSTANCE:
            inst = copy.deepcopy(part)
        elif scope == config_scope.WORLD:
            world = copy.deepcopy(part)
        else:
            raise ValueError(f"unknown scope {scope!r}")
        union = inst
        _deep_merge(union, world)
        union_inst, union_world, _unknown = config_scope.split_by_scope(union)
        actual_other = union_world if other_scope == config_scope.WORLD else union_inst
        if json.dumps(actual_other, sort_keys=True) != json.dumps(other_part, sort_keys=True):
            raise ValueError(f"save_part would change the {other_scope} layer")
        save(union)
        # Keep the env publication under the lock so concurrent saves cannot
        # publish an older union after the newest one.
        _flatten_to_env(union)
        return union


def _atomic_write_json(path: Path, data: Any) -> None:
    """Write JSON atomically (temp file + rename)."""
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".json.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        Path(tmp_path).rename(path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _resolve_path(obj: Any, path: str) -> Any:
    """Resolve a dot-notation path with optional array indices."""
    parts = re.split(r'\.|\[(\d+)\]', path)
    parts = [p for p in parts if p is not None and p != ""]
    current = obj
    for part in parts:
        if isinstance(current, list):
            current = current[int(part)]
        elif isinstance(current, dict):
            # Try int key first if it looks like a number
            if part.isdigit() and part not in current:
                current = current[int(part)]
            else:
                current = current[part]
        else:
            raise KeyError(part)
    return current


# ── Backward Compatibility: Flatten JSON to os.environ ──

def _flatten_to_env(config: dict) -> None:
    """Flatten JSON config into os.environ for backward compatibility.

    This maps the structured JSON back into the flat PROVIDER_1_NAME etc.
    format that existing code expects via os.environ.get() / os.getenv().

    The fallback for an absent field is its schema default (``field_default``)
    — the ONE source, so a value stored at its default and an absent value
    bridge the same. Fields without a schema default keep their literal. The
    package-owned ``skills.searx.enabled`` keeps its literal too: package
    subsections exist in the schema only after plugin discovery, which runs
    after the first config load.
    """
    from app.core.config_schema import field_default

    env = {}

    # Server
    server = config.get("server", {})
    _set(env, "LOG_LEVEL", server.get("log_level", field_default("server", "log_level")))

    # Providers (1-indexed)
    for i, prov in enumerate(config.get("providers", []), start=1):
        p = f"PROVIDER_{i}_"
        _set(env, f"{p}NAME", prov.get("name", ""))
        _set(env, f"{p}TYPE", prov.get("type", field_default("providers", "type")))
        _set(env, f"{p}API_BASE", prov.get("api_base", ""))
        _set(env, f"{p}API_KEY", prov.get("api_key", field_default("providers", "api_key")))
        _set(env, f"{p}TIMEOUT", prov.get("timeout", field_default("providers", "timeout")))
        _set(env, f"{p}MAX_CONCURRENT", prov.get("max_concurrent", field_default("providers", "max_concurrent")))
        _set(env, f"{p}SERIALIZE_GROUP", prov.get("serialize_group", ""))

    # Memory thresholds (three-tier system)
    memory = config.get("memory", {})
    _set(env, "MEMORY_SHORT_TERM_DAYS", memory.get("short_term_days", field_default("memory", "short_term_days")))
    _set(env, "MEMORY_MID_TERM_DAYS", memory.get("mid_term_days", field_default("memory", "mid_term_days")))
    _set(env, "MEMORY_LONG_TERM_DAYS", memory.get("long_term_days", field_default("memory", "long_term_days")))
    _set(env, "CHAT_HISTORY_MAX_MESSAGES", memory.get("max_messages", field_default("memory", "max_messages")))
    _set(env, "CHAT_SESSION_GAP_HOURS", memory.get("session_gap_hours", field_default("memory", "session_gap_hours")))
    _set(env, "MEMORY_MAX_SEMANTIC", memory.get("max_semantic", field_default("memory", "max_semantic")))
    _set(env, "MEMORY_COMMITMENT_MAX_DAYS", memory.get("commitment_max_days", field_default("memory", "commitment_max_days")))
    _set(env, "MEMORY_COMMITMENT_COMPLETED_DAYS", memory.get("commitment_completed_days", field_default("memory", "commitment_completed_days")))

    # Image Generation
    ig = config.get("image_generation", {})
    _set(env, "OUTFIT_IMAGE_WIDTH", ig.get("outfit_image_width", field_default("image_generation", "outfit_image_width")))
    _set(env, "OUTFIT_IMAGE_HEIGHT", ig.get("outfit_image_height", field_default("image_generation", "outfit_image_height")))
    _set(env, "LOCATION_IMAGE_WIDTH", ig.get("location_image_width", field_default("image_generation", "location_image_width")))
    _set(env, "LOCATION_IMAGE_HEIGHT", ig.get("location_image_height", field_default("image_generation", "location_image_height")))
    _set(env, "U2NET_HOME", ig.get("u2net_home", field_default("image_generation", "u2net_home")))
    _set(env, "IMAGE_ANALYSIS_PROMPT", ig.get("image_analysis_prompt", field_default("image_generation", "image_analysis_prompt")))

    # ImageGen Backends (1-indexed)
    for i, be in enumerate(ig.get("backends", []), start=1):
        p = f"SKILL_IMAGEGEN_{i}_"
        for key in ["name", "enabled", "api_type", "api_url", "api_key", "model",
                     "cost", "width", "height",
                     "guidance_scale", "num_inference_steps",
                     "sampling_method", "schedule_type",
                     "checkpoint", "poll_interval", "max_wait", "max_queue_wait",
                     "disable_safety",
                     "scheduler", "clip_skip", "image_family",
                     "supports_negative_prompt", "timeout",
                     "max_concurrent", "serialize_group",
                     "response_format", "extra_params", "category", "prompt",
                     "ref_slot_count",
                     "full_mask", "mask_grow", "inner_crop",
                     "mask_format", "lora_url", "lora_filter",
                     # Video backends (localai_video / together_video / civitai_video)
                     "seconds", "video_endpoint", "video_engine",
                     # CivitAI (civitai / civitai_video)
                     "denoise_strength", "allow_mature_content",
                     # Mesh backend (openai_mesh, img2mesh)
                     "mesh_endpoint", "remove_background",
                     "face_num", "face_num_max", "no_fingers", "mesh_steps",
                     # Mesh animation (openai_mesh_animation, mesh2anim)
                     "motion_source", "source_slot", "caption_style", "segment_seconds",
                     "variant_param", "duration_param", "max_variants", "generator",
                     "license", "model_revision", "credit"]:
            val = be.get(key, "")
            # extra_params can be a dict (JSON editor) — bridge as JSON string.
            if key == "extra_params" and isinstance(val, (dict, list)):
                val = json.dumps(val)
            _set(env, f"{p}{key.upper()}", val)

    # Animation/video: folded into image_generation.backends (a video backend
    # type). The former standalone config.animation + TOGETHER_ANIMATE_* bridge
    # was retired — see app/imagegen/backends/*_video.py.

    # TTS
    tts = config.get("tts", {})
    _set(env, "TTS_ENABLED", tts.get("enabled", field_default("tts", "enabled")))
    _set(env, "TTS_AUTO", tts.get("auto", field_default("tts", "auto")))
    _set(env, "TTS_CHUNK_SIZE", tts.get("chunk_size", field_default("tts", "chunk_size")))
    _set(env, "TTS_BACKEND", tts.get("backend", field_default("tts", "backend")))
    _set(env, "TTS_FALLBACK_BACKEND", tts.get("fallback_backend", field_default("tts", "fallback_backend")))

    xtts = tts.get("xtts", {})
    _set(env, "TTS_XTTS_URL", xtts.get("url", field_default("tts", "xtts", "url")))
    _set(env, "TTS_XTTS_SPEAKER_WAV", xtts.get("speaker_wav", ""))
    _set(env, "TTS_XTTS_LANGUAGE", xtts.get("language", field_default("tts", "xtts", "language")))

    magpie = tts.get("magpie", {})
    _set(env, "TTS_MAGPIE_URL", magpie.get("url", field_default("tts", "magpie", "url")))
    _set(env, "TTS_MAGPIE_VOICE", magpie.get("voice", ""))
    _set(env, "TTS_MAGPIE_LANGUAGE", magpie.get("language", field_default("tts", "magpie", "language")))

    f5 = tts.get("f5", {})
    _set(env, "TTS_F5_URL", f5.get("url", field_default("tts", "f5", "url")))
    _set(env, "TTS_F5_REF_AUDIO", f5.get("ref_audio", ""))
    _set(env, "TTS_F5_REF_TEXT", f5.get("ref_text", ""))
    _set(env, "TTS_F5_SPEED", f5.get("speed", field_default("tts", "f5", "speed")))
    _set(env, "TTS_F5_REMOVE_SILENCE", f5.get("remove_silence", field_default("tts", "f5", "remove_silence")))
    _set(env, "TTS_F5_NFE_STEPS", f5.get("nfe_steps", field_default("tts", "f5", "nfe_steps")))
    _set(env, "TTS_F5_CUSTOM_CFG", f5.get("custom_cfg", ""))
    for lang, ldata in f5.get("languages", {}).items():
        ul = lang.upper()
        _set(env, f"TTS_F5_MODEL_{ul}", ldata.get("model", ""))
        _set(env, f"TTS_F5_VOCAB_{ul}", ldata.get("vocab", ""))
        _set(env, f"TTS_F5_CFG_{ul}", ldata.get("cfg", ""))

    # Skills
    skills = config.get("skills", {})

    # The searx package reads its own settings through the plugin context
    # (`skills.searx.*`, declared in plugins/searx/plugin.yaml). Only the
    # ENABLED gate still has an env fallback (app/plugins/loader.py).
    searx = skills.get("searx", {})
    _set(env, "SKILL_SEARX_ENABLED", searx.get("enabled", False))

    # `name`/`description` of a skill come from its skills/<id>.md template
    # since the plugin migration — the bridge used to set env vars nobody read.
    oc = skills.get("outfit_change", {})
    _set(env, "SKILL_OUTFIT_CHANGE_GENERATE_IMAGE", oc.get("generate_image", field_default("skills", "outfit_change", "generate_image")))
    _set(env, "SKILL_OUTFIT_CHANGE_LANGUAGE", oc.get("language", field_default("skills", "outfit_change", "language")))
    _set(env, "SKILL_OUTFIT_CHANGE_MAX_OUTFITS", oc.get("max_outfits", field_default("skills", "outfit_change", "max_outfits")))

    # Knowledge
    kn = config.get("knowledge", {})
    _set(env, "SKILL_KNOWLEDGE_BATCH_SIZE", kn.get("batch_size", field_default("knowledge", "batch_size")))
    _set(env, "SKILL_KNOWLEDGE_MAX_INPUT_TOKENS", kn.get("max_input_tokens", field_default("knowledge", "max_input_tokens")))
    _set(env, "SKILL_KNOWLEDGE_MAX_OUTPUT_TOKENS", kn.get("max_output_tokens", field_default("knowledge", "max_output_tokens")))
    _set(env, "SKILL_KNOWLEDGE_SEARCH_MAX_CANDIDATES", kn.get("search_max_candidates", field_default("knowledge", "search_max_candidates")))
    _set(env, "SKILL_KNOWLEDGE_SEARCH_MAX_RETURN", kn.get("search_max_return", field_default("knowledge", "search_max_return")))

    # Thoughts — AgentLoop pacing.
    # The AgentLoop reads these values directly via config.get(); nothing
    # reads these two env variables any more. The lines are kept only as
    # the bridge's pinned behaviour (scripts/smoke_dead_config_fields.py
    # test 11 checks the schema-default fallback through them).
    pro = config.get("thoughts", {})
    _set(env, "THOUGHT_MIN_TURN_GAP_SECONDS", pro.get("min_turn_gap_seconds", field_default("thoughts", "min_turn_gap_seconds")))
    _set(env, "THOUGHT_MIN_PER_CHAR_COOLDOWN_MINUTES", pro.get("min_per_char_cooldown_minutes", field_default("thoughts", "min_per_char_cooldown_minutes")))

    # Random Events
    re_cfg = config.get("random_events", {})
    _set(env, "EVENT_GENERATION_ENABLED", re_cfg.get("enabled", field_default("random_events", "enabled")))
    _set(env, "EVENT_BASE_PROBABILITY", (re_cfg.get("base_probability", field_default("random_events", "base_probability"))) / 100)
    _set(env, "EVENT_RESOLUTION_PROACTIVE", re_cfg.get("resolution_proactive", field_default("random_events", "resolution_proactive")))
    _set(env, "EVENT_RESOLUTION_COOLDOWN_MINUTES", re_cfg.get("resolution_cooldown_minutes", field_default("random_events", "resolution_cooldown_minutes")))
    _set(env, "EVENT_RESOLVED_IMAGE_LINGER_MINUTES", re_cfg.get("resolved_image_linger_minutes", field_default("random_events", "resolved_image_linger_minutes")))

    # Story Engine
    se = config.get("story_engine", {})
    _set(env, "STORY_ENGINE_ENABLED", se.get("enabled", field_default("story_engine", "enabled")))
    _set(env, "STORY_ENGINE_MAX_ACTIVE_ARCS", se.get("max_active_arcs", field_default("story_engine", "max_active_arcs")))
    _set(env, "STORY_ENGINE_COOLDOWN_HOURS", se.get("cooldown_hours", field_default("story_engine", "cooldown_hours")))
    _set(env, "STORY_ENGINE_MAX_BEATS", se.get("max_beats", field_default("story_engine", "max_beats")))
    _set(env, "STORY_ENGINE_BEAT_IMAGES", se.get("beat_images", field_default("story_engine", "beat_images")))

    # Purge stale provider and image/video/mesh backend blocks BEFORE writing: this bridge
    # only ever set keys, never removed them. A deleted backend therefore left
    # its SKILL_IMAGEGEN_{N}_* block behind and would come back as a phantom
    # instance on the next load — and a field cleared in the admin kept its old
    # value (_set skips empty values). Both are gone now: every generated key
    # that the current config does not produce is removed.
    for key in [k for k in os.environ if _IMAGEGEN_ENV_RE.match(k) or _PROVIDER_ENV_RE.match(k)]:
        if key not in env:
            del os.environ[key]

    # Write all to os.environ
    for key, value in env.items():
        os.environ[key] = str(value)


def _set(env: dict, key: str, value: Any) -> None:
    """Set an env value, converting Python types to env-compatible strings."""
    if value is None or value == "":
        return
    if isinstance(value, bool):
        env[key] = "true" if value else "false"
    elif isinstance(value, (dict, list)):
        env[key] = json.dumps(value, ensure_ascii=False)
    else:
        env[key] = str(value)
