"""Centralized JSON-based configuration module.

Replaces .env / python-dotenv with a single storage/config.json file.
Provides get(dotpath), get_section(dotpath), and a backward-compatibility
bridge that populates os.environ so that existing code keeps working
during the migration phase.
"""
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Optional

from app.core.log import get_logger

logger = get_logger("config")

_CONFIG: dict = {}
# Mutable — updated by load() when an explicit path is passed
# Keys this module generates for the numbered image/video/mesh backend blocks.
_IMAGEGEN_ENV_RE = re.compile(r"^SKILL_IMAGEGEN_\d+_")

# Upper bound of the SKILL_IMAGEGEN_{N}_* scan — the single source of truth for
# everyone who walks the numbered backend blocks (the image service that loads
# the backends AND the provider manager that gives each one a queue channel).
# It used to be scattered (19 / 20 / 30) and drifted: raising it in one place
# SILENTLY dropped backends past the lower bounds — a configured backend either
# vanished from the pool or ran without a serialized channel. Generous on
# purpose; anything past it is logged as an error at load.
MAX_IMAGE_BACKENDS = 200

_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "storage" / "config.json"
_SECRETS_PATH: Optional[Path] = None  # set in load() — sibling of _CONFIG_PATH

# Snapshot der Werte aller `requires_restart: true`-Felder zum Boot-Zeitpunkt.
# Wird in load() einmalig befuellt und nicht mehr ueberschrieben — so kann
# die Admin-UI nach einem Save erkennen, ob ein restart-pflichtiges Feld
# gegenueber dem laufenden Server-Prozess abweicht.
_BOOT_RESTART_SNAPSHOT: Optional[dict] = None

# Fields that contain sensitive data (API keys, passwords, secrets)
SENSITIVE_FIELDS = {
    "api_key", "password", "jwt_secret", "bot_token", "secret",
    "auth_token",
}


def _is_sensitive(key: str) -> bool:
    """Check if a config key name is sensitive."""
    return key in SENSITIVE_FIELDS


# ── Use-Case-spezifische Prompt-Styles ──────────────────────────────────────
# Style/Negative/Instruction gehoeren zum FALL der Generierung (Map-Tile vs
# Character-Foto vs Item), nicht zum Workflow. Sie haengen an zwei Dimensionen:
#   use_case (map/character/item/…)  ×  Style-FAMILIE (Formulierung).
# Es gibt zwei generelle Familien (NICHT an Modellnamen gebunden, pro Use-Case
# erweiterbar): 'natural' (Fliesstext) und 'keywords' (Komma-Tags). Das
# "Target Prompt Stil"-Feld (image_model) eines Workflows wird ueber
# _IMAGE_MODEL_FAMILY in eine Familie uebersetzt.
_PROMPT_STYLE_FAMILIES = ["natural", "keywords"]

# image_family / Render-Target -> Style-Familie. Akzeptiert die neuen Familien
# (natural/keywords) direkt UND die Render-Targets (z_image/qwen/flux), die
# get_target_model aus Datei-/Backend-Namen ableitet. Default: keywords.
_IMAGE_MODEL_FAMILY = {
    "": "keywords",
    "keywords": "keywords",
    "natural": "natural",
    "z_image": "keywords",
    "qwen": "natural",
    "flux": "natural",
}

# Gemeinsamer Foto-Negativ-Prompt fuer die photoreal-orientierten Use-Cases.
_NEG_PHOTO = ("illustration, anime, cgi, 3d render, painting, airbrushed skin, "
              "plastic skin, smooth flawless skin, overexposed, glossy, fantasy, "
              "studio lighting, posed, cartoon, drawing, sketch, watermark, "
              "signature, text, logo, deformed, blurry, low quality")

# Negatives of the mesh-input renders — ONE text per use case, shared by both
# style families (deliberately NOT _NEG_PHOTO: "posed"/"studio lighting" would
# fight the T-pose / flat-light goal).
_NEG_TPOSE = ("illustration, anime, cgi, 3d render, painting, airbrushed skin, plastic skin, smooth flawless skin, overexposed, glossy, cartoon, drawing, sketch, watermark, signature, text, logo, deformed, blurry, low quality, harsh shadows, dramatic lighting, side lighting, rim light, backlighting, cropped, out of frame, cropped hands, hands cut off, A-pose, arms lowered, arms at sides, arms angled downward, relaxed arms, hands at hips, hands touching body, clenched fists, curled fingers, fingers overlapping, hands hidden")
_NEG_TPOSE_ANIMAL = ("illustration, anime, cgi, 3d render, painting, cartoon, drawing, sketch, watermark, signature, text, logo, deformed, blurry, low quality, harsh shadows, dramatic lighting, rim light, backlighting, cropped, out of frame, cropped legs, tail cut off, close-up, portrait, head only, human, person, hands, anthropomorphic, standing on two legs, clothing, costume, looking at the camera, head turned toward the camera, open mouth, sitting, lying down, curled up")

# Negative of the building-exterior render (source of the location 3D model —
# shared by both families). Like _NEG_TPOSE it is NOT _NEG_PHOTO (no skin
# terms); it keeps the WHOLE building in frame and free of people/interior.
_NEG_BUILDING = ("illustration, anime, cgi, 3d render, painting, cartoon, drawing, sketch, watermark, signature, text, logo, deformed, blurry, low quality, people, person, characters, crowd, interior, indoor, inside, room, furniture, close-up, cropped, out of frame, partial building, only part of the building, tilted horizon, dutch angle, fisheye, harsh shadows, cast shadows, ground shadow, dramatic lighting, side lighting, rim light, backlighting, golden hour, sunset, night, street, road, cars, trees, plants, garden, landscape, sky, clouds, surrounding buildings, neighborhood, scenery")

# Negative of the ROOM model-source renders: must NOT fight the subject —
# furniture (indoor) and plants (outdoor room) ARE the content, unlike
# _NEG_BUILDING which negates interior/furniture/trees for clean exteriors.
# Walls/ceiling/roof are negated hard so the diorama stays fully open.
_NEG_ROOM = ("illustration, anime, cartoon, drawing, sketch, painting, watermark, signature, text, logo, deformed, blurry, low quality, people, person, characters, crowd, walls, wall, ceiling, roof, enclosed room, closed room, building exterior, facade, close-up, cropped, out of frame, partial view, tilted horizon, dutch angle, fisheye, harsh shadows, cast shadows, ground shadow, dramatic lighting, side lighting, rim light, backlighting, golden hour, sunset, night, sky, clouds, street, road, cars, surrounding buildings, neighborhood, scenery")

# Negative of the OUTDOOR location scene diorama (building_outdoor): plants,
# trees and water are the subject there — only people, framing problems,
# shadows and off-base surroundings are pushed away.
_NEG_OUTDOOR_SCENE = ("illustration, anime, cartoon, drawing, sketch, painting, watermark, signature, text, logo, deformed, blurry, low quality, people, person, characters, crowd, interior, indoor, close-up, cropped, out of frame, partial view, tilted horizon, dutch angle, fisheye, harsh shadows, cast shadows, ground shadow, dramatic lighting, side lighting, rim light, backlighting, golden hour, sunset, night, sky, clouds, street, road, cars, surrounding buildings, neighborhood")

# Eingebaute Defaults pro use_case × Familie. Diese Werte werden NICHT in die
# config.json geseedet — sie sind Resolver-Default UND grauer Placeholder in der
# Admin-UI (leeres Feld = dieser Default greift). Ohne Backend-Fallback braucht
# JEDER Use-Case einen Default fuer beide Familien.
_DEFAULT_IMAGE_USE_CASES = {
    "map": {
        "keywords": {
            "prompt_style": "{subject}, game map tile, photorealistic, oblique top-down angle with a slight tilt for depth, single close-up map tile, subject fills the entire frame edge to edge, cohesive palette, highly detailed, full-bleed, no border, no frame, borderless",
            "prompt_negative": "people, person, characters, faces, text, words, letters, watermark, signature, logo, frame, border, framed, vignette, grid lines, map pins, icons, flat, completely top-down, straight-down view, blueprint, schematic, side view, ground level, eye level, horizon, sky, distant, far away, zoomed out, wide region, blurry, lowres, jpeg artifacts, low quality",
            "prompt_instruction": "Write comma-separated keywords for a single close-up game map tile of the place, viewed from an oblique top-down angle (slightly tilted, not flat straight-down) for a sense of depth, photorealistic style. Stay faithful to the subject — depict only what it describes and do not invent extra landmarks or structures. The subject fills the entire frame edge to edge, closely framed, no border or frame. No people, no text, no camera or style talk.",
        },
        "natural": {
            "prompt_style": "a single close-up game map tile of {subject}, photorealistic, viewed from an oblique top-down angle (slightly tilted, not flat straight-down) for a sense of depth, the subject closely framed and filling the entire frame edge to edge with no border or frame around it, cohesive palette, highly detailed",
            "prompt_negative": "people, person, characters, faces, text, words, watermark, signature, logo, frame, border, framed, vignette, flat, completely top-down, straight-down view, blueprint, schematic, side view, ground level, eye level, horizon, sky, distant, far away, zoomed out, wide region, blurry, low quality",
            "prompt_instruction": "Describe a single close-up game map tile of the place, viewed from an oblique top-down angle (slightly tilted, not flat straight-down) for a sense of depth, photorealistic style. Stay faithful to the subject — depict only what it describes and do not invent extra landmarks or structures. The subject is closely framed and fills the entire frame edge to edge with no border or frame. No people, no text.",
        },
    },
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
    "prop": {
        "keywords": {
            "prompt_style": "single object, isolated, centered, plain light gray background, product photography, soft studio lighting, full view, no scene",
            "prompt_negative": "scene, environment, floor shadow, people, hands, text, watermark",
            "prompt_instruction": "Write comma-separated keywords for the single object only, isolated on a plain light gray background. No people, no scene.",
        },
        "natural": {
            "prompt_style": "a single isolated object on a plain seamless light gray studio background, centered product shot, soft even studio lighting from above, fully in frame with generous margin, matte surfaces clearly readable",
            "prompt_negative": "scene, environment, floor shadow, people, hands, text, watermark",
            "prompt_instruction": "Describe the single object only, isolated on a plain light gray background. No people, no scene.",
        },
    },
    # The object drawn INTO a context plate (docs/scene-asset-pipeline.md).
    # The picture already exists: light, camera, ground and scale come from the
    # plate, and the only thing this prompt may add is ONE object at the marked
    # spot. Everything that would tempt a model to redraw the scene (a setting,
    # a background, a mood) is deliberately absent, and the negative names the
    # two defects the cutout stage cannot repair — a floating object and a
    # second copy of it. The one-metre grid in the plate is mentioned on
    # purpose: it is the only scale reference the model gets.
    "scene_asset": {
        "keywords": {
            "prompt_style": "add {subject} at the marked spot, standing firmly on the ground with its base touching it, same light and shadow direction as the rest of the photo, same perspective and camera angle, size true to the one-metre ground grid, sharp focus, photorealistic, surroundings unchanged",
            "prompt_negative": "floating, hovering above the ground, cropped, cut off, two objects, duplicate, copy, people, person, text, watermark, changed background, new scenery, different lighting, relit scene",
            "prompt_instruction": "Write comma-separated keywords for the ONE object to be added at the marked spot — what it is, its material, its colour, its size. Only the object; the surroundings, the light and the camera already exist.",
        },
        "natural": {
            "prompt_style": "a photograph of {subject} standing at the marked spot, its base resting on the ground, lit by exactly the same light as everything around it and casting its shadow the same way, seen from the same camera angle, as large as the one-metre grid on the ground demands, with the rest of the picture completely unchanged",
            "prompt_negative": "floating, hovering above the ground, cropped, cut off, two objects, duplicate, people, text, watermark, changed background, new scenery, different lighting",
            "prompt_instruction": "Describe the ONE object to be added at the marked spot — what it is, its material, its colour, its size. Only the object; the surroundings, the light and the camera already exist.",
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
            "prompt_style": "photorealistic, portrait, head and shoulders, only head, looking at camera, neutral background, sharp focus, high detail",
            "prompt_negative": _NEG_PHOTO,
            "prompt_instruction": "Write comma-separated tags for a head-and-shoulders portrait — face, hair, expression. Neutral background, no full body.",
        },
        "natural": {
            "prompt_style": "a photorealistic head-and-shoulders portrait looking at the camera, neutral background, sharp focus",
            "prompt_negative": _NEG_PHOTO,
            "prompt_instruction": "Describe a head-and-shoulders portrait — face, hair, expression. Neutral background, no full body.",
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
    "tpose": {
        "keywords": {
            "prompt_style": "full body view, head to toe, full arm span visible with both hands fully inside the frame, wide framing with margin around the figure, plain neutral background, flat even shadowless lighting, uniform illumination, sharp focus, high detail",
            "prompt_negative": _NEG_TPOSE,
            "prompt_instruction": "Write comma-separated tags describing the character head-to-toe on a plain background with flat even lighting. Do not mention pose or facial expression.",
        },
        "natural": {
            "prompt_style": "a full-body photo of the character from head to toe against a plain neutral background, the full arm span visible with both hands entirely inside the frame and margin around the figure, flat even shadowless lighting, uniform illumination, sharp focus",
            "prompt_negative": _NEG_TPOSE,
            "prompt_instruction": "Describe the character head-to-toe on a plain background with flat even lighting. Do not mention pose or facial expression.",
        },
    },
    # Mesh input for NON-humanoid characters (animals). Same lighting/background
    # goal as "tpose", but the framing is nose-to-tail instead of arm span, and
    # the negatives push away from anthropomorphism.
    "tpose_animal": {
        "keywords": {
            "prompt_style": "full body view of the animal, nose to tail, all four legs and the tail fully inside the frame, three-quarter side view, margin around the animal, plain neutral background, flat even shadowless lighting, uniform illumination, sharp focus, high detail",
            "prompt_negative": _NEG_TPOSE_ANIMAL,
            "prompt_instruction": "Write comma-separated tags describing the animal's whole body from nose to tail on a plain background with flat even lighting. Do not mention pose or expression.",
        },
        "natural": {
            "prompt_style": "a full-body photo of the animal from nose to tail against a plain neutral background, seen from a three-quarter side angle with all four legs and the tail entirely inside the frame and margin around it, flat even shadowless lighting, uniform illumination, sharp focus",
            "prompt_negative": _NEG_TPOSE_ANIMAL,
            "prompt_instruction": "Describe the animal's whole body from nose to tail on a plain background with flat even lighting. Do not mention pose or expression.",
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


def image_model_to_family(image_model: str) -> str:
    """Uebersetzt ein 'Target Prompt Stil' (image_model) in eine Style-Familie."""
    return _IMAGE_MODEL_FAMILY.get((image_model or "").strip(), "keywords")


def get_use_case_prompts(use_case: str, image_model: str = "") -> dict:
    """Loest Style/Negative/Instruction fuer einen Use-Case + Target-Style auf.

    Prioritaet pro Feld: Admin-Override (config) -> eingebauter Default
    (_DEFAULT_IMAGE_USE_CASES[use_case][familie]) -> "" (Aufrufer faellt dann
    auf den Workflow-Style zurueck). Gibt immer ein Dict mit den drei Keys
    zurueck (Werte koennen leer sein).
    """
    uc = (use_case or "").strip() or "character"
    family = image_model_to_family(image_model)
    fields = ("prompt_style", "prompt_negative", "prompt_instruction")
    builtin = (_DEFAULT_IMAGE_USE_CASES.get(uc, {}) or {}).get(family, {}) or {}
    out = {}
    for f in fields:
        override = get(f"image_generation.use_cases.{uc}.styles.{family}.{f}", "")
        out[f] = (override or "").strip() or (builtin.get(f, "") or "")
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
                           backend_family: str = "") -> dict:
    """Convenience wrapper for all generate paths. Family priority:
    explicit ``image_family`` → backend ``image_family`` → heuristic from
    the backend model name (get_target_model). Returns
    {prompt_style, prompt_negative, prompt_instruction} for the use case.
    """
    from app.core.prompt_adapters import get_target_model
    fam = (image_family or "").strip() or (backend_family or "").strip()
    target = get_target_model(fam, backend_model or "")
    return get_use_case_prompts(use_case, target)


_DEFAULT_MARKETPLACE_CATALOGS = [
    {
        "name": "Anima-Verse Public",
        "url": "https://github.com/KaletoAI/anima-verse-content",
        "auth_token": "",
        "enabled": True,
    },
]


def _seed_default_marketplace_catalogs(config: dict) -> bool:
    """Seeds the public catalog on a fresh world.

    Idempotent: only fires when `content_marketplace.catalogs` is absent.
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
_DEFAULT_SHRINK_BACKEND = ("mesh-shrink", "none", 1, 5000, 0, 0)

_DEFAULT_MESH_BACKENDS = [
    # (name, rig, cost, face_num, face_num_max, max_concurrent)
    ("Trellis2-Humanoid-Low", "mixamo", 1, 20000, 0, 0),
    ("Trellis2-Humanoid-High", "mixamo", 2, 20000, 0, 0),
    ("Trellis2-Generic-Low", "generic", 1, 20000, 0, 0),
    ("Trellis2-Generic-High", "generic", 2, 20000, 0, 0),
    ("Trellis2-Object-Low", "none", 1, 20000, 0, 0),
    ("Pixal3D-Humanoid", "mixamo", 3, 50000, 0, 2),
    ("Pixal3D-Generic", "generic", 3, 50000, 0, 0),
    ("Pixal3D-Object", "none", 5, 50000, 0, 0),
    # Splat pipeline: no face param at all (input_num_gaussians, default
    # 10000) — face_num stays 0 so nothing is sent.
    ("Triposplat-Object", "none", 1, 0, 0, 0),
    ("Hunyuan3D-Humanoid", "mixamo", 2, 40000, 40000, 0),
    ("Hunyuan3D-Generic", "generic", 2, 40000, 40000, 0),
    ("Hunyuan3D-Object", "none", 2, 40000, 40000, 0),
]


def _default_mesh_backend_entries() -> list:
    """The seed list as config dicts (img2mesh aliases + the mesh→mesh one)."""
    out = []
    for name, rig, cost, faces, faces_max, concurrent in (
            [*_DEFAULT_MESH_BACKENDS, _DEFAULT_SHRINK_BACKEND]):
        entry = {
            "name": name,
            "enabled": True,
            "api_type": "openai_mesh",
            "api_url": _MESH_GATEWAY_URL,
            "api_key": "",
            "model": name,
            "category": ("mesh2mesh" if name == _DEFAULT_SHRINK_BACKEND[0]
                         else "img2mesh"),
            "cost": cost,
            "timeout": 3600,
            "poll_interval": 2,
            "max_concurrent": concurrent,
            "mesh_rig": rig,
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
    """Seeds the mesh backend catalog (img2mesh + mesh2mesh) into a BRAND-NEW
    world's config.

    Only ever called for a world whose config.json did not exist yet: an
    existing world's backend list is the admin's, and silently appending
    aliases to it would resurrect entries they deleted on purpose.

    In-memory only — see `migrate_file()` for the disk side.
    """
    ig = config.setdefault("image_generation", {})
    backends = ig.setdefault("backends", [])
    if any(isinstance(b, dict) and b.get("api_type") == "openai_mesh"
           for b in backends):
        return False
    backends.extend(_default_mesh_backend_entries())
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
    """Legt die Use-Case-Prompt-Struktur an (leere Felder, 2 Familien je Use-Case).

    Die Felder bleiben LEER — die eingebauten Defaults (_DEFAULT_IMAGE_USE_CASES)
    greifen als Resolver-Fallback und werden in der Admin-UI als grauer
    Placeholder gezeigt. Geseedet wird nur die Struktur, damit der Admin die
    Eintraege sieht/editieren/erweitern kann. Idempotent + Backfill fehlender
    Use-Cases. Returns True wenn sich etwas geaendert hat.

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
#     siblings scene_prompt_multi_ref / scene_prompt_only_background stay).
#   chat / inventory / random_events — single leftovers; item image size runs
#     through ui.downscale_item_max_dim instead.
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
    ),
    "chat": ("auto_wake_stamina",),
    "inventory": ("item_image_width", "item_image_height"),
    "random_events": ("event_image_denoise_strength",),
}

# The same names again, this time at the TOP LEVEL of config.json. Older worlds
# predate the sectioning: worlds/demo and worlds/hotopia carry
# item_image_width/height as top-level keys and have no "inventory" section at
# all, so a section-only strip would walk straight past them. None of the dead
# names is a living top-level key (they have no schema entry anywhere), so
# sweeping all of them at both depths is safe and keeps the two lists from
# drifting apart.
DEAD_TOPLEVEL_FIELDS: tuple = tuple(sorted(
    {k for keys in DEAD_CONFIG_FIELDS.values() for k in keys}))


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


# Config fields that hold a RENDER TARGET — a backend-name glob ("Flux2*", or
# an exact name), optionally with the tolerated legacy prefix "backend:". The
# ComfyUI era also wrote "workflow:<glob>" here; that form resolves to None in
# BackendPool.resolve_spec, so the configured backend was silently ignored and
# the caller fell back to auto-selection. The rewrite below drops the prefix.
# The DB counterpart (per-character overrides) is
# app/core/workflow_spec_migration.py.
LEGACY_SPEC_FIELDS: tuple = (
    "image_generation.outfit_imagegen_default",
    "image_generation.expression_imagegen_default",
    "image_generation.location_imagegen_default",
    "image_generation.prop_imagegen_default",
    "image_generation.scene_imagegen_default",
    "image_generation.mesh_imagegen_default",
    "image_generation.timevariant_imagegen_default",
    "random_events.event_imagegen_default",
    "story_engine.imagegen_default",
    "skills.instagram.imagegen_default",
    "messaging_frame.target",
)


def _rewrite_legacy_workflow_specs(config: dict) -> bool:
    """Rewrites "workflow:<glob>" render targets to the bare glob.

    Same pattern as _strip_dead_config_fields above: no fallback reader, no
    alias — the world file gets the canonical spelling once. Idempotent;
    returns True only when something actually changed.

    In-memory only — see `migrate_file()` for the disk side.
    """
    from app.core.workflow_spec_migration import strip_legacy_workflow_prefix
    changed = False
    for dotted in LEGACY_SPEC_FIELDS:
        *parents, key = dotted.split(".")
        node = config
        for part in parents:
            node = node.get(part) if isinstance(node, dict) else None
            if not isinstance(node, dict):
                break
        if not isinstance(node, dict) or key not in node:
            continue
        old = node.get(key)
        new = strip_legacy_workflow_prefix(old)
        if new == old:
            continue
        node[key] = new
        changed = True
        logger.info("Legacy render spec rewritten: %s %r -> %r", dotted, old, new)
    return changed


def _apply_file_migrations(config: dict, fresh_world: bool) -> bool:
    """Runs every load-time normalisation over ``config``, IN MEMORY.

    Strip (dead/legacy fields) + seed (use-case blocks, marketplace catalog,
    and — for a brand-new world only — the mesh backend catalog) + the two
    one-time renames. Every step is idempotent, so a second run over the same
    dict returns False. Returns True when any step changed something.

    This is the shared body of `load()` (which never touches disk) and
    `migrate_file()` (which persists the very same result).
    """
    changed = False
    if _seed_default_use_cases(config):
        changed = True
    if fresh_world and _seed_default_mesh_backends(config):
        changed = True
    if _strip_legacy_imagegen_prompt_fields(config):
        changed = True
    if _strip_dead_config_fields(config):
        changed = True
    if _rewrite_legacy_workflow_specs(config):
        changed = True
    if _seed_default_marketplace_catalogs(config):
        changed = True
    if _migrate_backend_categories(config):
        changed = True
    if _migrate_lora_triggers(config):
        changed = True
    return changed


def migrate_file(config_path: Optional[Path] = None) -> bool:
    """Applies the load-time normalisations TO DISK. Returns True if written.

    `load()` is a pure READ path — it normalises only the in-memory config, so
    that merely opening a world (a smoke script, a CLI, an export run) leaves
    the world's files byte-identical. Persisting is this function's job, and it
    is called from exactly one place: the server boot, right after `load()` —
    the RUNNING world's config.json is meant to stay current. The admin save
    path needs no call: it serialises the whole in-memory config back out
    (`/admin/settings/raw` -> page state -> `config.save`), so the seeded and
    stripped state lands there by itself.

    Deliberately works on a FRESH READ of the file rather than on `_CONFIG`:
    by the time boot calls this, `_CONFIG` carries the secrets.json overlay,
    and dumping that would leak API keys into the tracked config.json. The
    re-read dict is exactly what the old in-load writers used to persist.
    """
    path = Path(config_path) if config_path else _CONFIG_PATH
    fresh_world = not path.exists()
    on_disk: dict = {}
    if not fresh_world:
        try:
            with open(path, "r", encoding="utf-8") as f:
                on_disk = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.error("Config migration skipped — cannot read %s: %s", path, e)
            return False
        if not isinstance(on_disk, dict):
            logger.error("Config migration skipped — %s is not an object", path)
            return False

    if not _apply_file_migrations(on_disk, fresh_world):
        return False

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_json(path, on_disk)
        logger.info("Config file migrated (strip + seed) -> %s", path)
        return True
    except OSError as e:
        logger.error("Failed to write migrated config to %s: %s", path, e)
        return False


def load(config_path: Optional[Path] = None) -> dict:
    """Load configuration from JSON file, then overlay secrets.json on top.

    secrets.json (sibling of config.json) holds sensitive fields and is gitignored.
    Falls back to empty config if config.json doesn't exist.
    Also populates os.environ for backward compatibility.

    READ-ONLY: the strip/seed normalisations below run in memory only, so
    loading a world never modifies its files. `migrate_file()` persists them.
    """
    global _CONFIG, _CONFIG_PATH, _SECRETS_PATH
    if config_path:
        _CONFIG_PATH = Path(config_path)
    _SECRETS_PATH = _CONFIG_PATH.parent / "secrets.json"
    path = _CONFIG_PATH

    # A world whose config.json does not exist yet gets the one-time defaults
    # a NEW world starts with (mesh backends); an existing world never does.
    fresh_world = not path.exists()

    if fresh_world:
        logger.warning("Config file not found: %s — using empty config", path)
        _CONFIG = {}
    else:
        try:
            with open(path, "r", encoding="utf-8") as f:
                _CONFIG = json.load(f)
            logger.info("Config loaded from %s", path)
        except (json.JSONDecodeError, IOError) as e:
            logger.error("Failed to load config from %s: %s", path, e)
            _CONFIG = {}

    # Normalise IN MEMORY — nothing lands on disk here (see migrate_file()).
    _apply_file_migrations(_CONFIG, fresh_world)

    # Overlay secrets.json (gitignored — holds api keys / passwords)
    if _SECRETS_PATH.exists():
        try:
            with open(_SECRETS_PATH, "r", encoding="utf-8") as f:
                secrets = json.load(f)
            _deep_merge(_CONFIG, secrets)
            logger.info("Secrets overlaid from %s", _SECRETS_PATH)
        except (json.JSONDecodeError, IOError) as e:
            logger.error("Failed to load secrets from %s: %s", _SECRETS_PATH, e)

    # Populate os.environ for backward compatibility
    _flatten_to_env(_CONFIG)

    # Boot-Snapshot der restart-pflichtigen Felder einfrieren (nur einmal,
    # der erste Load gewinnt — spaetere reload()-Aufrufe veraendern das nicht).
    global _BOOT_RESTART_SNAPSHOT
    if _BOOT_RESTART_SNAPSHOT is None:
        _BOOT_RESTART_SNAPSHOT = _collect_restart_values(_CONFIG)

    _materialize_game_calendar_defaults(_CONFIG)

    _invalidate_config_derived_caches()
    return _CONFIG


# True while `game_seasons` in memory is the SHIPPED default list rather than
# something the world configured. The one-time atmosphere migration needs the
# distinction: on a materialized list no season has an "own" value yet.
_GAME_SEASONS_MATERIALIZED = False


def game_seasons_are_defaults() -> bool:
    """True when the loaded `game_seasons` came from `Calendar.default()`."""
    return _GAME_SEASONS_MATERIALIZED


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
    """Liest aktuelle Werte aller `requires_restart`-Pfade aus cfg."""
    try:
        from app.core.config_schema import iter_restart_required_paths
    except Exception:
        return {}
    result = {}
    for path in iter_restart_required_paths():
        # Pfade mit '[*]' (Array-Item-Felder) auflösen wir gegen alle Indizes
        if "[*]" in path:
            for resolved in _expand_wildcards(cfg, path):
                result[resolved] = get(resolved)
        else:
            result[path] = get(path)
    return result


def _expand_wildcards(cfg: dict, path: str) -> list:
    """Expandiert '[*]'-Wildcards gegen die aktuellen Array-Längen in cfg."""
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
    """Vergleicht Boot-Snapshot mit aktueller Config.

    Liefert eine Liste der Pfade, deren Werte sich seit dem Server-Start
    geaendert haben — d.h. die ohne Restart NICHT wirksam werden.
    """
    if _BOOT_RESTART_SNAPSHOT is None:
        return []
    pending = []
    current = _collect_restart_values(_CONFIG)
    # Geänderte Werte
    for path, boot_val in _BOOT_RESTART_SNAPSHOT.items():
        if current.get(path) != boot_val:
            pending.append(path)
    # Neu hinzugekommene Pfade (z.B. neuer Provider-Array-Eintrag mit
    # restart-pflichtigem Feld) — wenn der Boot-Wert leer war und jetzt
    # ein Wert da ist, faellt das auch unter "pending".
    for path in current:
        if path not in _BOOT_RESTART_SNAPSHOT and current[path]:
            pending.append(path)
    return sorted(set(pending))


def _deep_merge(base: Any, overlay: Any) -> None:
    """In-place deep merge of overlay into base. Lists are merged element-wise by index."""
    if isinstance(base, dict) and isinstance(overlay, dict):
        for k, v in overlay.items():
            if k in base and isinstance(base[k], (dict, list)) and isinstance(v, (dict, list)):
                _deep_merge(base[k], v)
            else:
                base[k] = v
    elif isinstance(base, list) and isinstance(overlay, list):
        for i, v in enumerate(overlay):
            if i < len(base):
                if isinstance(base[i], (dict, list)) and isinstance(v, (dict, list)):
                    _deep_merge(base[i], v)
                else:
                    base[i] = v


def _split_secrets(data: Any) -> tuple:
    """Walk data and split sensitive values out.

    Returns (clean, secrets). Sensitive string values are blanked in clean and
    placed into a parallel structure in secrets. Lists keep position; entries
    without secrets become empty dicts/lists in the secrets shape and are
    pruned at the top level if entirely empty.
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
        clean_list: list = []
        secrets_list: list = []
        any_secrets = False
        for item in data:
            sub_clean, sub_secrets = _split_secrets(item)
            clean_list.append(sub_clean)
            secrets_list.append(sub_secrets if sub_secrets else {})
            if sub_secrets:
                any_secrets = True
        return clean_list, (secrets_list if any_secrets else [])

    return data, None


def reload() -> dict:
    """Reload configuration from disk (uses same path as last load)."""
    return load()


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
    """Save configuration. Sensitive fields are split out into secrets.json (gitignored)."""
    global _CONFIG, _GAME_SEASONS_MATERIALIZED
    path = config_path or _CONFIG_PATH
    secrets_path = path.parent / "secrets.json"

    path.parent.mkdir(parents=True, exist_ok=True)

    clean, secrets = _split_secrets(data)

    _atomic_write_json(path, clean)
    logger.info("Config saved to %s", path)

    if secrets:
        _atomic_write_json(secrets_path, secrets)
        logger.info("Secrets saved to %s", secrets_path)
    elif secrets_path.exists():
        try:
            secrets_path.unlink()
        except OSError:
            pass

    _CONFIG = data
    if isinstance(data.get("game_seasons"), list) and data["game_seasons"]:
        _GAME_SEASONS_MATERIALIZED = False
    _invalidate_config_derived_caches()


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


def mask_sensitive(data: Any, _key: str = "") -> Any:
    """Return a copy of data with sensitive values masked for display."""
    if isinstance(data, dict):
        result = {}
        for k, v in data.items():
            result[k] = mask_sensitive(v, k)
        return result
    if isinstance(data, list):
        return [mask_sensitive(item, _key) for item in data]
    if _is_sensitive(_key) and isinstance(data, str) and len(data) > 4:
        return "***" + data[-4:]
    return data


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
    """
    env = {}

    # Server
    server = config.get("server", {})
    _set(env, "LOG_LEVEL", server.get("log_level", "INFO"))
    _set(env, "JWT_SECRET", server.get("jwt_secret", ""))
    _set(env, "STORAGE_DIR", server.get("storage_dir", "./storage"))

    # Providers (1-indexed)
    for i, prov in enumerate(config.get("providers", []), start=1):
        p = f"PROVIDER_{i}_"
        _set(env, f"{p}NAME", prov.get("name", ""))
        _set(env, f"{p}TYPE", prov.get("type", "openai"))
        _set(env, f"{p}API_BASE", prov.get("api_base", ""))
        _set(env, f"{p}API_KEY", prov.get("api_key", ""))
        _set(env, f"{p}TIMEOUT", prov.get("timeout", 120))
        _set(env, f"{p}MAX_CONCURRENT", prov.get("max_concurrent", 1))
        _set(env, f"{p}SERIALIZE_GROUP", prov.get("serialize_group", ""))
        _set(env, f"{p}RESERVE_CHAT_SLOT", bool(prov.get("reserve_chat_slot", False)))

    # Memory Thresholds (3-Stufen-System)
    memory = config.get("memory", {})
    _set(env, "MEMORY_SHORT_TERM_DAYS", memory.get("short_term_days", 3))
    _set(env, "MEMORY_MID_TERM_DAYS", memory.get("mid_term_days", 30))
    _set(env, "MEMORY_LONG_TERM_DAYS", memory.get("long_term_days", 90))
    _set(env, "CHAT_HISTORY_MAX_MESSAGES", memory.get("max_messages", 100))
    _set(env, "CHAT_SESSION_GAP_HOURS", memory.get("session_gap_hours", 4))
    _set(env, "MEMORY_MAX_SEMANTIC", memory.get("max_semantic", 50))
    _set(env, "MEMORY_COMMITMENT_MAX_DAYS", memory.get("commitment_max_days", 5))
    _set(env, "MEMORY_COMMITMENT_COMPLETED_DAYS", memory.get("commitment_completed_days", 3))

    # Image Generation
    ig = config.get("image_generation", {})
    _set(env, "SKILL_IMAGEGEN_ENABLED", ig.get("enabled", True))
    _set(env, "SKILL_IMAGEGEN_NAME", ig.get("name", "ImageGenerator"))
    _set(env, "SKILL_IMAGEGEN_DESCRIPTION", ig.get("description", ""))
    _set(env, "OUTFIT_IMAGE_WIDTH", ig.get("outfit_image_width", 832))
    _set(env, "OUTFIT_IMAGE_HEIGHT", ig.get("outfit_image_height", 1216))
    _set(env, "LOCATION_IMAGE_WIDTH", ig.get("location_image_width", 1280))
    _set(env, "LOCATION_IMAGE_HEIGHT", ig.get("location_image_height", 720))
    _set(env, "OUTFIT_IMAGEGEN_DEFAULT", ig.get("outfit_imagegen_default", ""))
    _set(env, "EXPRESSION_IMAGEGEN_DEFAULT", ig.get("expression_imagegen_default", ""))
    _set(env, "LOCATION_IMAGEGEN_DEFAULT", ig.get("location_imagegen_default", ""))
    _set(env, "TIMEVARIANT_IMAGEGEN_DEFAULT", ig.get("timevariant_imagegen_default", ""))
    _set(env, "PROP_IMAGEGEN_DEFAULT", ig.get("prop_imagegen_default", ""))
    _set(env, "U2NET_HOME", ig.get("u2net_home", "./models/u2net"))
    _set(env, "REBUILD_LLM_SYSTEM_TEMPLATE", ig.get("rebuild_llm_system_template", ""))
    _set(env, "IMAGE_ANALYSIS_PROMPT", ig.get("image_analysis_prompt", ""))

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
                     # Video backends (localai_video / together_video)
                     "seconds", "video_endpoint",
                     # Mesh backend (openai_mesh, img2mesh)
                     "mesh_endpoint", "mesh_rig", "remove_background",
                     "face_num", "face_num_max", "no_fingers"]:
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
    _set(env, "TTS_ENABLED", tts.get("enabled", False))
    _set(env, "TTS_AUTO", tts.get("auto", False))
    _set(env, "TTS_CHUNK_SIZE", tts.get("chunk_size", 300))
    _set(env, "TTS_BACKEND", tts.get("backend", "xtts"))
    _set(env, "TTS_FALLBACK_BACKEND", tts.get("fallback_backend", ""))

    xtts = tts.get("xtts", {})
    _set(env, "TTS_XTTS_URL", xtts.get("url", ""))
    _set(env, "TTS_XTTS_SPEAKER_WAV", xtts.get("speaker_wav", ""))
    _set(env, "TTS_XTTS_LANGUAGE", xtts.get("language", "de"))

    magpie = tts.get("magpie", {})
    _set(env, "TTS_MAGPIE_URL", magpie.get("url", ""))
    _set(env, "TTS_MAGPIE_VOICE", magpie.get("voice", ""))
    _set(env, "TTS_MAGPIE_LANGUAGE", magpie.get("language", "de-DE"))

    f5 = tts.get("f5", {})
    _set(env, "TTS_F5_URL", f5.get("url", ""))
    _set(env, "TTS_F5_REF_AUDIO", f5.get("ref_audio", ""))
    _set(env, "TTS_F5_REF_TEXT", f5.get("ref_text", ""))
    _set(env, "TTS_F5_SPEED", f5.get("speed", 1.0))
    _set(env, "TTS_F5_REMOVE_SILENCE", f5.get("remove_silence", False))
    _set(env, "TTS_F5_NFE_STEPS", f5.get("nfe_steps", 32))
    _set(env, "TTS_F5_CUSTOM_CFG", f5.get("custom_cfg", ""))
    for lang, ldata in f5.get("languages", {}).items():
        ul = lang.upper()
        _set(env, f"TTS_F5_MODEL_{ul}", ldata.get("model", ""))
        _set(env, f"TTS_F5_VOCAB_{ul}", ldata.get("vocab", ""))
        _set(env, f"TTS_F5_CFG_{ul}", ldata.get("cfg", ""))

    # Skills
    skills = config.get("skills", {})

    searx = skills.get("searx", {})
    _set(env, "SKILL_SEARX_ENABLED", searx.get("enabled", False))
    _set(env, "SKILL_SEARX_URL", searx.get("url", ""))
    _set(env, "SKILL_SEARX_NAME", searx.get("name", "WebSearch"))
    _set(env, "SKILL_SEARX_DESCRIPTION", searx.get("description", ""))
    _set(env, "SKILL_SEARX_ENGINES", searx.get("engines", ""))
    _set(env, "SKILL_SEARX_CATEGORIES", searx.get("categories", ""))
    _set(env, "SKILL_SEARX_NUM_RESULTS", searx.get("num_results", 5))

    for skill_key, env_prefix_map in [
    ]:
        s = skills.get(skill_key, {})
        _set(env, f"{env_prefix_map}_ENABLED", s.get("enabled", True))
        _set(env, f"{env_prefix_map}_NAME", s.get("name", ""))
        _set(env, f"{env_prefix_map}_DESCRIPTION", s.get("description", ""))

    oc = skills.get("outfit_change", {})
    _set(env, "SKILL_OUTFIT_CHANGE_NAME", oc.get("name", "ChangeOutfit"))
    _set(env, "SKILL_OUTFIT_CHANGE_DESCRIPTION", oc.get("description", ""))
    _set(env, "SKILL_OUTFIT_CHANGE_GENERATE_IMAGE", oc.get("generate_image", True))
    _set(env, "SKILL_OUTFIT_CHANGE_LANGUAGE", oc.get("language", "en"))
    _set(env, "SKILL_OUTFIT_CHANGE_MAX_OUTFITS", oc.get("max_outfits", 10))

    # Knowledge
    kn = config.get("knowledge", {})
    _set(env, "KNOWLEDGE_MAX_PROMPT_ENTRIES", kn.get("max_prompt_entries", 20))
    _set(env, "KNOWLEDGE_MAX_ENTRIES", kn.get("max_entries", 200))
    _set(env, "DAILY_SUMMARY_DAYS", kn.get("daily_summary_days", 7))
    _set(env, "SKILL_KNOWLEDGE_BATCH_SIZE", kn.get("batch_size", 5))
    _set(env, "SKILL_KNOWLEDGE_MAX_INPUT_TOKENS", kn.get("max_input_tokens", 12000))
    _set(env, "SKILL_KNOWLEDGE_MAX_OUTPUT_TOKENS", kn.get("max_output_tokens", 1500))
    _set(env, "SKILL_KNOWLEDGE_SEARCH_MAX_CANDIDATES", kn.get("search_max_candidates", 50))
    _set(env, "SKILL_KNOWLEDGE_SEARCH_MAX_RETURN", kn.get("search_max_return", 8))

    # Relationships
    rel = config.get("relationships", {})
    _set(env, "RELATIONSHIP_SUMMARY_ENABLED", rel.get("summary_enabled", True))
    _set(env, "RELATIONSHIP_SUMMARY_INTERVAL_MINUTES", rel.get("summary_interval_minutes", 120))

    # Social
    sr = config.get("social_reactions", {})
    _set(env, "SOCIAL_REACTIONS_ENABLED", sr.get("enabled", True))

    # Thoughts — AgentLoop pacing.
    # AgentLoop liest die Werte direkt via config.get() (kein env-Bridge
    # mehr noetig); Mapping bleibt nur fuer Backward-Compat falls Code
    # die env-Variable noch erwartet.
    pro = config.get("thoughts", config.get("proactive", {}))
    _set(env, "THOUGHT_MIN_TURN_GAP_SECONDS", pro.get("min_turn_gap_seconds", 30))
    _set(env, "THOUGHT_MIN_PER_CHAR_COOLDOWN_MINUTES", pro.get("min_per_char_cooldown_minutes", 5))

    # Random Events
    re_cfg = config.get("random_events", {})
    _set(env, "EVENT_GENERATION_ENABLED", re_cfg.get("enabled", True))
    _set(env, "EVENT_BASE_PROBABILITY", (re_cfg.get("base_probability", 5)) / 100)
    _set(env, "EVENT_RESOLUTION_PROACTIVE", re_cfg.get("resolution_proactive", True))
    _set(env, "EVENT_RESOLUTION_COOLDOWN_MINUTES", re_cfg.get("resolution_cooldown_minutes", 15))
    _set(env, "EVENT_IMAGEGEN_DEFAULT", re_cfg.get("event_imagegen_default", ""))
    _set(env, "EVENT_RESOLVED_IMAGE_LINGER_MINUTES", re_cfg.get("resolved_image_linger_minutes", 30))

    # Story Engine
    se = config.get("story_engine", {})
    _set(env, "STORY_ENGINE_ENABLED", se.get("enabled", False))
    _set(env, "STORY_ENGINE_MAX_ACTIVE_ARCS", se.get("max_active_arcs", 2))
    _set(env, "STORY_ENGINE_COOLDOWN_HOURS", se.get("cooldown_hours", 6))
    _set(env, "STORY_ENGINE_MAX_BEATS", se.get("max_beats", 5))
    _set(env, "STORY_ENGINE_BEAT_IMAGES", se.get("beat_images", True))
    _set(env, "STORY_ENGINE_IMAGEGEN_DEFAULT", se.get("imagegen_default", ""))

    # Telegram
    tg = config.get("telegram", {})
    _set(env, "TELEGRAM_BOT_TOKEN", tg.get("bot_token", ""))
    _set(env, "TELEGRAM_API_URL", tg.get("api_url", "https://api.telegram.org/bot"))

    # UI
    ui = config.get("ui", {})
    _set(env, "DEFAULT_THEME", ui.get("default_theme", "default"))
    _set(env, "AVAILABLE_THEMES", ui.get("available_themes", "default,minimal,dark"))

    # Purge stale image/video/mesh backend blocks BEFORE writing: this bridge
    # only ever set keys, never removed them. A deleted backend therefore left
    # its SKILL_IMAGEGEN_{N}_* block behind and would come back as a phantom
    # instance on the next load — and a field cleared in the admin kept its old
    # value (_set skips empty values). Both are gone now: every generated key
    # that the current config does not produce is removed.
    for key in [k for k in os.environ if _IMAGEGEN_ENV_RE.match(k)]:
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
