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


# Default-Workflows fuer neue Welten. Werte 1:1 aus den produktiv erprobten
# Hotopia-Workflows. Beim ersten Load einer Welt ohne `comfyui_workflows`
# werden diese drei Templates eingespielt — der User muss nur noch Backend
# (skill) und ggf. Modell-Dateien bestaetigen.
_DEFAULT_COMFYUI_WORKFLOWS = {
    "Qwen": {
        "name": "Qwen",
        "image_family": "natural",
        "filter": "Qwen*",
        "width": 1024,
        "height": 1024,
        "workflow_file": "./workflows/text2img_workflow_qwen_api.json",
        "loras": [{"file": "", "strength": 1} for _ in range(4)],
    },
    "Z-Image": {
        "name": "Z-Image",
        "image_family": "keywords",
        "filter": "Z-Image*",
        "width": 1024,
        "height": 1024,
        "workflow_file": "./workflows/text2img_workflow_z-image_api.json",
        "loras": [{"file": "", "strength": 1} for _ in range(4)],
    },
    "Flux": {
        "name": "Flux",
        "image_family": "natural",
        "filter": "Flux.2-9B*",
        "width": 1024,
        "height": 1024,
        "workflow_file": "./workflows/text2img_workflow_flux2_api.json",
        "loras": [{"file": "", "strength": 1} for _ in range(4)],
    },
    "Flux 1 Dev": {
        "name": "Flux 1 Dev",
        "image_family": "natural",
        "filter": "Flux*1*",
        "width": 1024,
        "height": 1024,
        "workflow_file": "./workflows/text2img_workflow_flux1_api.json",
        "model": "flux1-dev.safetensors",
        "clip": "clip_l.safetensors",
        "clip2": "t5xxl_fp8_e4m3fn_scaled.safetensors",
        "loras": [{"file": "", "strength": 1} for _ in range(4)],
    },
    "Flux Inpaint": {
        "name": "Flux Inpaint",
        "image_family": "natural",
        "filter": "Flux Inpaint*",
        "category": "inpaint",
        "width": 1024,
        "height": 1024,
        "workflow_file": "./workflows/img2img_workflow_flux1_inpaint_api.json",
        "model": "Flux1-DevFill-Onereward_fp8.safetensors",
        "clip": "clip_l.safetensors",
        "clip2": "t5xxl_fp8_e4m3fn_scaled.safetensors",
        # Flux1-DevFill = Fill-Modell: beschreibender Prompt fuer die Maske.
        "prompt": "seamless top-down map tile, photorealistic, continue the surrounding terrain, colors and style into the masked area with no visible seam, border or frame",
        "loras": [{"file": "", "strength": 1} for _ in range(4)],
    },
    "Qwen Inpaint": {
        "name": "Qwen Inpaint",
        "image_family": "natural",
        "filter": "Qwen Inpaint*",
        "category": "inpaint",
        "width": 1024,
        "height": 1024,
        "workflow_file": "./workflows/text2img_workflow_flux-qwen_inpaint_api.json",
        # Modell bewusst leer: der Workflow-Default ist ein NSFW-Modell — gehoert
        # nicht in die mitgelieferte Default-Config. Pro Welt im Admin setzen.
        "model": "",
        "clip": "Qwen2.5-VL-7B-Instruct-abliterated_merged.safetensors",
        # CLIP-Loader-Type muss zum Modell passen (qwen_image fuer Qwen-Image,
        # flux2 fuer Flux.2). Default hier auf den Qwen-Clip abgestimmt.
        "clip_type": "qwen_image",
        # Qwen-Edit = Instruktions-Modell: Anweisung statt Beschreibung.
        "prompt": "complement the gray masked areas and make a seamless map, matching the surrounding terrain, colors and photorealistic style with no visible seams, border or frame",
        "loras": [{"file": "", "strength": 1} for _ in range(4)],
    },
    "Flux2 Inpaint": {
        "name": "Flux2 Inpaint",
        "image_family": "natural",
        "filter": "Flux2 Inpaint*",
        "category": "inpaint",
        "width": 1024,
        "height": 1024,
        "workflow_file": "./workflows/text2img_workflow_flux-qwen_inpaint_api.json",
        "model": "flux-2-klein-9b-Q8_0.gguf",
        "clip": "Qwen3-8B-Q8_0.gguf",
        "clip_type": "flux2",
        "vae": "flux2-vae.safetensors",
        "prompt": "complement the gray masked areas and make a seamless map, matching the surrounding terrain, colors and hand-painted style with no visible seams, border or frame",
        # skill (Backend) bewusst LEER: pro Welt zuweisen (sonst deaktiviert).
        "loras": [{"file": "", "strength": 1} for _ in range(4)],
    },
    "SD15": {
        "name": "SD15",
        "image_family": "keywords",
        "filter": "SD15*",
        "width": 1024,
        "height": 1024,
        "workflow_file": "./workflows/text2img_workflow_sd15_api.json",
        "model": "SD15-Cyberrealistic-fp32.safetensors",
        "loras": [{"file": "", "strength": 1} for _ in range(4)],
    },
}


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

# Eingebaute Defaults pro use_case × Familie. Diese Werte werden NICHT in die
# config.json geseedet — sie sind Resolver-Default UND grauer Placeholder in der
# Admin-UI (leeres Feld = dieser Default greift). Ohne Backend-Fallback braucht
# JEDER Use-Case einen Default fuer beide Familien.
_DEFAULT_IMAGE_USE_CASES = {
    "map": {
        "keywords": {
            "prompt_style": "game map tile, photorealistic, oblique top-down angle with a slight tilt for depth, single close-up map tile, subject fills the entire frame edge to edge, cohesive palette, highly detailed, full-bleed, no border, no frame, borderless",
            "prompt_negative": "people, person, characters, faces, text, words, letters, watermark, signature, logo, frame, border, framed, vignette, grid lines, map pins, icons, flat, completely top-down, straight-down view, blueprint, schematic, side view, ground level, eye level, horizon, sky, distant, far away, zoomed out, wide region, blurry, lowres, jpeg artifacts, low quality",
            "prompt_instruction": "Write comma-separated keywords for a single close-up game map tile of the place, viewed from an oblique top-down angle (slightly tilted, not flat straight-down) for a sense of depth, photorealistic style. Stay faithful to the subject — depict only what it describes and do not invent extra landmarks or structures. The subject fills the entire frame edge to edge, closely framed, no border or frame. No people, no text, no camera or style talk.",
        },
        "natural": {
            "prompt_style": "a single close-up game map tile of the place, photorealistic, viewed from an oblique top-down angle (slightly tilted, not flat straight-down) for a sense of depth, the subject closely framed and filling the entire frame edge to edge with no border or frame around it, cohesive palette, highly detailed",
            "prompt_negative": "people, person, characters, faces, text, words, watermark, signature, logo, frame, border, framed, vignette, flat, completely top-down, straight-down view, blueprint, schematic, side view, ground level, eye level, horizon, sky, distant, far away, zoomed out, wide region, blurry, low quality",
            "prompt_instruction": "Describe a single close-up game map tile of the place, viewed from an oblique top-down angle (slightly tilted, not flat straight-down) for a sense of depth, photorealistic style. Stay faithful to the subject — depict only what it describes and do not invent extra landmarks or structures. The subject is closely framed and fills the entire frame edge to edge with no border or frame. No people, no text.",
        },
    },
    "mapfit": {
        # Map-Fit / Kanten-Angleich (Inpaint): die grauen/maskierten Flaechen des
        # Nachbar-Canvas nahtlos ergaenzen — KEIN „neues Tile"-Stil. Greift fuer
        # Fit-to-neighbors + Match-edges (category=="inpaint"-Workflows wie Qwen
        # Inpaint / Flux Inpaint), pro Familie editierbar im Use-Cases-Editor.
        "keywords": {
            "prompt_style": "top-down aerial map view of the area, filling the entire frame, in the same photorealistic style, colour palette and lighting as the rest of the map, highly detailed, slight tilt for depth, no border, no frame, no text",
            "prompt_negative": "people, person, characters, faces, text, words, watermark, signature, logo, frame, border, washed out, desaturated, flat, blurry, lowres, jpeg artifacts, low quality",
            "prompt_instruction": "Write a short comma-separated prompt for a top-down aerial map view of the area, filling the frame, in the same photorealistic style, colour palette and lighting as the rest of the map. Self-contained — do not continue or invent beyond the edges. No border, no frame, no text.",
        },
        "natural": {
            "prompt_style": "a top-down aerial map view of the area, filling the entire frame, in the same photorealistic style, colour palette and lighting as the rest of the map, highly detailed, slight tilt for depth, no border, no frame, no text",
            "prompt_negative": "people, person, characters, faces, text, words, watermark, signature, logo, frame, border, washed out, desaturated, flat, blurry, low quality",
            "prompt_instruction": "Write a short prompt for a top-down aerial map view of the area, filling the frame, in the same photorealistic style, colour palette and lighting as the rest of the map. Self-contained — do not continue or invent beyond the edges. No border, no frame, no text.",
        },
    },
    "location": {
        "keywords": {
            "prompt_style": "wide establishing shot, environment, atmospheric, detailed, no people",
            "prompt_negative": _NEG_PHOTO,
            "prompt_instruction": "Write comma-separated tags for an establishing shot of the place — environment, architecture, lighting, mood. No people.",
        },
        "natural": {
            "prompt_style": "a wide establishing shot of the place, atmospheric, detailed environment, no people",
            "prompt_negative": _NEG_PHOTO,
            "prompt_instruction": "Describe an establishing shot of the place — environment, architecture, lighting, mood. No people.",
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
    "outfit": {
        "keywords": {
            "prompt_style": "full body view, standing, plain neutral background, even lighting, sharp focus, high detail",
            "prompt_negative": _NEG_PHOTO,
            "prompt_instruction": "Write comma-separated tags describing the full outfit head-to-toe on a standing figure, plain background.",
        },
        "natural": {
            "prompt_style": "a full-body photo of the character standing against a plain neutral background, even lighting, sharp focus",
            "prompt_negative": _NEG_PHOTO,
            "prompt_instruction": "Describe the full outfit head-to-toe on a standing figure against a plain background.",
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
    """Aktivierungs-Woerter fuer die aktiven LoRAs (aus dem per-Welt-Repository
    ``image_generation.lora_triggers`` = [{lora, word}, …]). Matcht per Dateiname
    (auch Basename, falls Pfad/Endung leicht abweicht). Reihenfolge wie im Repo,
    Duplikate entfernt.
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


def get_lora_library_names(backend_name=None) -> list:
    """LoRA-Namen aus der per-Welt-LoRA-Library (``image_generation.lora_triggers``
    = [{lora, word, endpoint}, …]), gefiltert nach Endpoint:

    - Eintraege mit ``endpoint == backend_name`` ODER leerem ``endpoint`` (= gilt
      fuer alle Backends) werden aufgenommen.
    - ``backend_name=None`` -> alle Namen (kein Filter).

    Reihenfolge wie im Repo, Duplikate entfernt. Damit ziehen LoRA-Dropdowns die
    manuell gepflegten LoRAs (z.B. fuer Cloud-/OpenAI-Backends ohne LoRA-API) und
    bekommen nicht die LoRAs eines fremden Backends/Modells angeboten.
    """
    triggers = get("image_generation.lora_triggers", []) or []
    if not isinstance(triggers, list):
        return []
    out, seen = [], set()
    for e in triggers:
        if not isinstance(e, dict):
            continue
        lora = (e.get("lora") or "").strip()
        if not lora or lora in seen:
            continue
        ep = (e.get("endpoint") or "").strip()
        if backend_name is not None and ep and ep != backend_name:
            continue
        seen.add(lora)
        out.append(lora)
    return out


def resolve_use_case_style(use_case: str, image_family: str = "",
                           workflow_file: str = "", backend_model: str = "",
                           backend_family: str = "") -> dict:
    """Bequemer Wrapper fuer alle Generate-Pfade. Familie-Prioritaet:
    Workflow-``image_family`` → Backend-``image_family`` → Heuristik aus
    Workflow-Dateiname/Backend-Modellname (get_target_model). Liefert
    {prompt_style, prompt_negative, prompt_instruction} fuer den Use-Case.
    """
    from app.core.prompt_adapters import get_target_model
    fam = (image_family or "").strip() or (backend_family or "").strip()
    target = get_target_model(fam, workflow_file or "", backend_model or "")
    return get_use_case_prompts(use_case, target)


_DEFAULT_MARKETPLACE_CATALOGS = [
    {
        "name": "Anima-Verse Public",
        "url": "https://github.com/KaletoAI/anima-verse-content",
        "auth_token": "",
        "enabled": True,
    },
]


def _seed_default_marketplace_catalogs(config: dict, config_path: Path) -> bool:
    """Seeds the public catalog on a fresh world.

    Idempotent: only fires when `content_marketplace.catalogs` is absent.
    If the admin clears the list to [], it stays empty — explicit choice
    beats implicit re-seeding.
    """
    cm = config.setdefault("content_marketplace", {})
    if "catalogs" in cm:
        return False
    import copy
    cm["catalogs"] = copy.deepcopy(_DEFAULT_MARKETPLACE_CATALOGS)
    try:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        logger.info("Default marketplace catalog seeded -> %s", config_path)
        return True
    except OSError as e:
        logger.error("Failed to seed default marketplace catalog to %s: %s", config_path, e)
        return False


def _seed_default_use_cases(config: dict, config_path: Path) -> bool:
    """Legt die Use-Case-Prompt-Struktur an (leere Felder, 2 Familien je Use-Case).

    Die Felder bleiben LEER — die eingebauten Defaults (_DEFAULT_IMAGE_USE_CASES)
    greifen als Resolver-Fallback und werden in der Admin-UI als grauer
    Placeholder gezeigt. Geseedet wird nur die Struktur, damit der Admin die
    Eintraege sieht/editieren/erweitern kann. Idempotent + Backfill fehlender
    Use-Cases. Returns True wenn etwas geschrieben wurde.
    """
    import copy
    ig = config.setdefault("image_generation", {})
    uc_cfg = ig.setdefault("use_cases", {})
    empty_fields = {"prompt_style": "", "prompt_negative": "", "prompt_instruction": ""}
    changed = False
    for uc in _DEFAULT_IMAGE_USE_CASES:
        entry = uc_cfg.setdefault(uc, {})
        styles = entry.setdefault("styles", {})
        for fam in _PROMPT_STYLE_FAMILIES:
            if fam not in styles:
                styles[fam] = copy.deepcopy(empty_fields)
                changed = True
    if not changed:
        return False
    try:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        logger.info("Use-Case-Prompt-Struktur geseedet/ergaenzt -> %s", config_path)
        return True
    except OSError as e:
        logger.error("Failed to seed use_cases to %s: %s", config_path, e)
        return False


def _strip_legacy_imagegen_prompt_fields(config: dict, config_path: Path) -> bool:
    """Entfernt die alten Style-Felder, die jetzt in den Use-Cases leben.

    - Workflows: prompt_style / prompt_negative / prompt_instruction
    - Backends:  prompt_prefix / negative_prompt
    Funktional sind sie bereits tot (kein Env-Mirror/Leser mehr) — das hier
    raeumt nur die config.json auf. Idempotent.
    """
    ig = config.get("image_generation", {})
    changed = False
    _fam_map = {"z_image": "keywords", "qwen": "natural", "flux": "natural"}
    for wf in (ig.get("comfyui_workflows", {}) or {}).values():
        if isinstance(wf, dict):
            for k in ("prompt_style", "prompt_negative", "prompt_instruction"):
                if k in wf:
                    del wf[k]; changed = True
            # image_model ("Target Prompt Stil") -> image_family (natural/keywords)
            if "image_model" in wf:
                _old = (wf.pop("image_model") or "").strip()
                wf["image_family"] = _fam_map.get(_old, _old if _old in ("natural", "keywords") else "")
                changed = True
    for be in (ig.get("backends", []) or []):
        if isinstance(be, dict):
            for k in ("prompt_prefix", "negative_prompt"):
                if k in be:
                    del be[k]; changed = True
    # Verstreute Prefix/Suffix-Felder -> jetzt in den Use-Cases.
    for k in ("profile_image_prompt_prefix", "outfit_image_prompt_prefix",
              "map_2d_image_prompt_suffix"):
        if k in ig:
            del ig[k]; changed = True
    if not changed:
        return False
    try:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        logger.info("Legacy Image-Gen Style-Felder entfernt (Workflow/Backend) -> %s", config_path)
        return True
    except OSError as e:
        logger.error("Failed to strip legacy imagegen fields from %s: %s", config_path, e)
        return False


def _fix_dotted_workflow_keys(config: dict, config_path: Path) -> bool:
    """Repariert ComfyUI-Workflow-Keys, die einen Punkt enthalten.

    Der Admin-Settings-Editor adressiert Felder per Dot-Notation
    (image_generation.comfyui_workflows.<KEY>.<feld>) und zerlegt sie mit
    split('.'). Ein Punkt IM Key (z.B. "Flux.1 Dev") zersplittert den Pfad,
    wodurch der Workflow nicht mehr editier-/speicherbar ist. Der Anzeige-Name
    darf den Punkt behalten — nur der Dict-Key wird punktfrei gemacht.
    Idempotent. Returns True wenn etwas umbenannt wurde.
    """
    ig = config.get("image_generation", {})
    workflows = ig.get("comfyui_workflows", {})
    if not isinstance(workflows, dict):
        return False
    dotted = [k for k in workflows if "." in k or "[" in k or "]" in k]
    if not dotted:
        return False
    for old_key in dotted:
        wf = workflows[old_key]
        new_key = old_key.replace(".", " ").replace("[", "").replace("]", "")
        # Anzeige-Name behaelt den Original-Key (mit Punkt), falls nicht gesetzt.
        if isinstance(wf, dict) and not wf.get("name"):
            wf["name"] = old_key
        # Kollision vermeiden: Suffix anhaengen bis frei.
        base = new_key
        n = 2
        while new_key in workflows and new_key != old_key:
            new_key = f"{base} {n}"
            n += 1
        del workflows[old_key]
        workflows[new_key] = wf
        logger.info("ComfyUI-Workflow-Key '%s' -> '%s' (Punkt im Key zerbricht Admin-Editor)", old_key, new_key)
    try:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        return True
    except OSError as e:
        logger.error("Failed to write dotted-key fix to %s: %s", config_path, e)
        return False


def _seed_default_workflows(config: dict, config_path: Path) -> bool:
    """Seedet bei einer neuen Welt die drei Default-Workflows (Qwen/Z-Image/Flux).

    Idempotent: nur wenn `image_generation.comfyui_workflows` gar nicht existiert.
    Wenn der User die Workflows absichtlich auf {} geleert hat, bleibt es leer.
    Returns True wenn etwas geschrieben wurde.
    """
    import copy
    ig = config.setdefault("image_generation", {})
    if "comfyui_workflows" not in ig:
        ig["comfyui_workflows"] = copy.deepcopy(_DEFAULT_COMFYUI_WORKFLOWS)
        log_msg = "Default ComfyUI workflows (Qwen/Z-Image/Flux/Flux.1 Dev/Flux Inpaint/Qwen Inpaint) seeded"
    else:
        # Backfill: feature-kritische Default-Workflows, die nach ihrer Einfuehrung
        # dazukamen, in bestehende Welten nachziehen (nur wenn der Key fehlt).
        backfill = ["Flux Inpaint", "Flux 1 Dev", "Qwen Inpaint"]
        added = [k for k in backfill if k not in ig["comfyui_workflows"]]
        for k in added:
            ig["comfyui_workflows"][k] = copy.deepcopy(_DEFAULT_COMFYUI_WORKFLOWS[k])
        # Feld-Backfill: das per-Workflow `prompt`-Feld kam nach der Einfuehrung der
        # Inpaint-Workflows dazu. Bestehende Default-Workflows, die es noch NICHT
        # haben, bekommen den Default-Prompt nachgezogen (nur wenn fehlend) — sonst
        # fallen Qwen/Flux Inpaint beide auf denselben mapfit-Fallback und der
        # Dialog zeigt beim Wechsel denselben Prompt.
        field_added = []
        for k, dflt in _DEFAULT_COMFYUI_WORKFLOWS.items():
            entry = ig["comfyui_workflows"].get(k)
            if isinstance(entry, dict) and dflt.get("prompt") and "prompt" not in entry:
                entry["prompt"] = dflt["prompt"]
                field_added.append(f"{k}.prompt")
        if not added and not field_added:
            return False
        log_msg = "Backfilled ComfyUI workflow(s): " + (", ".join(added) or "-")
        if field_added:
            log_msg += " | fields: " + ", ".join(field_added)
    try:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        logger.info("%s -> %s", log_msg, config_path)
        return True
    except OSError as e:
        logger.error("Failed to seed default workflows to %s: %s", config_path, e)
        return False


def load(config_path: Optional[Path] = None) -> dict:
    """Load configuration from JSON file, then overlay secrets.json on top.

    secrets.json (sibling of config.json) holds sensitive fields and is gitignored.
    Falls back to empty config if config.json doesn't exist.
    Also populates os.environ for backward compatibility.
    """
    global _CONFIG, _CONFIG_PATH, _SECRETS_PATH
    if config_path:
        _CONFIG_PATH = Path(config_path)
    _SECRETS_PATH = _CONFIG_PATH.parent / "secrets.json"
    path = _CONFIG_PATH

    if not path.exists():
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

    # Punkt-Keys in comfyui_workflows reparieren (zerbrechen den Admin-Editor)
    # — VOR dem Seeding/Backfill, damit die Key-Praesenz korrekt geprueft wird.
    _fix_dotted_workflow_keys(_CONFIG, path)

    # Bei einer neuen/leeren Welt: Default-Workflows fuer Qwen/Z-Image/Flux
    # automatisch eintragen, damit der Admin nicht alles von Hand anlegen muss.
    _seed_default_workflows(_CONFIG, path)
    _seed_default_use_cases(_CONFIG, path)
    _strip_legacy_imagegen_prompt_fields(_CONFIG, path)
    _seed_default_marketplace_catalogs(_CONFIG, path)

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

    return _CONFIG


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
    global _CONFIG
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

    # Beszel
    beszel = config.get("beszel", {})
    _set(env, "BESZEL_URL", beszel.get("url", ""))
    _set(env, "BESZEL_TOKEN", beszel.get("token", ""))

    # Providers (1-indexed)
    for i, prov in enumerate(config.get("providers", []), start=1):
        p = f"PROVIDER_{i}_"
        _set(env, f"{p}NAME", prov.get("name", ""))
        _set(env, f"{p}TYPE", prov.get("type", "openai"))
        _set(env, f"{p}API_BASE", prov.get("api_base", ""))
        _set(env, f"{p}API_KEY", prov.get("api_key", ""))
        _set(env, f"{p}TIMEOUT", prov.get("timeout", 120))
        _set(env, f"{p}MAX_CONCURRENT", prov.get("max_concurrent", 1))
        _set(env, f"{p}BESZEL_SYSTEM_ID", prov.get("beszel_system_id", ""))
        for g, gpu in enumerate(prov.get("gpus", [])):
            gp = f"{p}GPU{g}_"
            _set(env, f"{gp}VRAM", gpu.get("vram_gb", 0))
            _set(env, f"{gp}DEVICE", gpu.get("device", str(g)))
            types = gpu.get("types", [])
            _set(env, f"{gp}TYPE", ",".join(types) if isinstance(types, list) else types)
            _set(env, f"{gp}LABEL", gpu.get("label", ""))
            _set(env, f"{gp}MATCH_NAME", gpu.get("match_name", ""))
            _set(env, f"{gp}MAX_CONCURRENT", gpu.get("max_concurrent", 1))

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
    _set(env, "COMFY_IMAGEGEN_DEFAULT", ig.get("comfy_default_workflow", ""))
    _set(env, "OUTFIT_IMAGE_WIDTH", ig.get("outfit_image_width", 832))
    _set(env, "OUTFIT_IMAGE_HEIGHT", ig.get("outfit_image_height", 1216))
    _set(env, "LOCATION_IMAGE_WIDTH", ig.get("location_image_width", 1280))
    _set(env, "LOCATION_IMAGE_HEIGHT", ig.get("location_image_height", 720))
    _set(env, "OUTFIT_IMAGEGEN_DEFAULT", ig.get("outfit_imagegen_default", ""))
    _set(env, "EXPRESSION_IMAGEGEN_DEFAULT", ig.get("expression_imagegen_default", ""))
    _set(env, "LOCATION_IMAGEGEN_DEFAULT", ig.get("location_imagegen_default", ""))
    # Map Fit/Edge: imagegen-Target (Match-Spec, z.B. "workflow:Flux Inpaint*")
    _set(env, "MAPFIT_IMAGEGEN_DEFAULT", ig.get(
        "mapfit_imagegen_default", "workflow:Flux Inpaint*"))
    _set(env, "MAP_TILE_VISION_ANALYSIS", ig.get("map_tile_vision_analysis", False))
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
                     "checkpoint", "poll_interval", "max_wait", "disable_safety",
                     "scheduler", "clip_skip", "image_family", "timeout",
                     "max_concurrent", "beszel_system_id",
                     "response_format", "extra_params", "category", "prompt",
                     "full_mask", "terrain_hint", "mask_grow", "inner_crop",
                     "lora_url"]:
            val = be.get(key, "")
            # extra_params kann ein Dict sein (JSON-Editor) — als JSON-String bruecken.
            if key == "extra_params" and isinstance(val, (dict, list)):
                val = json.dumps(val)
            _set(env, f"{p}{key.upper()}", val)
        for gi, g in enumerate(be.get("gpus", []) or []):
            gp = f"{p}GPU{gi}_"
            _set(env, f"{gp}VRAM", g.get("vram_gb", "") or "")
            _set(env, f"{gp}DEVICE", g.get("device", "") or "")
            _set(env, f"{gp}LABEL", g.get("label", "") or "")
            _set(env, f"{gp}MATCH_NAME", g.get("match_name", "") or "")

    # ComfyUI Workflows
    for wid, wf in ig.get("comfyui_workflows", {}).items():
        p = f"COMFY_IMAGEGEN_{wid}_"
        for key in ["name", "filter", "skill", "workflow_file",
                     "model", "image_family", "category", "prompt",
                     "width", "height",
                     "clip", "clip2", "vae", "clip_type"]:
            val = wf.get(key, "")
            _set(env, f"{p}{key.upper()}", val)
        # LoRAs
        for idx, lora in enumerate(wf.get("loras", []), start=1):
            _set(env, f"{p}LORA_{idx:02d}", lora.get("file", ""))
            _set(env, f"{p}LORA_{idx:02d}_STRENGTH", lora.get("strength", 1))

    # Animation
    anim = config.get("animation", {})
    comfy_a = anim.get("comfy", {})
    _set(env, "COMFY_ANIMATE_ENABLED", comfy_a.get("enabled", False))
    _set(env, "COMFY_ANIMATE_WORKFLOW_FILE", comfy_a.get("workflow_file", ""))
    _set(env, "COMFY_ANIMATE_BACKEND", comfy_a.get("backend", ""))
    _set(env, "COMFY_ANIMATE_UNET_HIGH", comfy_a.get("unet_high", ""))
    _set(env, "COMFY_ANIMATE_UNET_LOW", comfy_a.get("unet_low", ""))
    _set(env, "COMFY_ANIMATE_CLIP", comfy_a.get("clip", ""))
    _set(env, "COMFY_ANIMATE_WIDTH", comfy_a.get("width", 640))
    _set(env, "COMFY_ANIMATE_HEIGHT", comfy_a.get("height", 640))
    _set(env, "COMFY_ANIMATE_POLL_INTERVAL", comfy_a.get("poll_interval", 3.0))
    _set(env, "COMFY_ANIMATE_MAX_WAIT", comfy_a.get("max_wait", 600))
    for variant in ["high", "low"]:
        for idx, lora in enumerate(comfy_a.get(f"loras_{variant}", []), start=1):
            _set(env, f"COMFY_ANIMATE_LORA_{variant.upper()}_{idx:02d}", lora.get("file", ""))
            _set(env, f"COMFY_ANIMATE_LORA_{variant.upper()}_{idx:02d}_STRENGTH", lora.get("strength", 1))

    tog = anim.get("together", {})
    _set(env, "TOGETHER_ANIMATE_ENABLED", tog.get("enabled", False))
    _set(env, "TOGETHER_ANIMATE_LABEL", tog.get("label", ""))
    _set(env, "TOGETHER_ANIMATE_API_KEY", tog.get("api_key", ""))
    _set(env, "TOGETHER_ANIMATE_MODEL", tog.get("model", ""))
    _set(env, "TOGETHER_ANIMATE_WIDTH", tog.get("width", 720))
    _set(env, "TOGETHER_ANIMATE_HEIGHT", tog.get("height", 720))
    _set(env, "TOGETHER_ANIMATE_SECONDS", tog.get("seconds", 5))
    _set(env, "TOGETHER_ANIMATE_POLL_INTERVAL", tog.get("poll_interval", 5.0))
    _set(env, "TOGETHER_ANIMATE_MAX_WAIT", tog.get("max_wait", 600))

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

    comfy_tts = tts.get("comfyui", {})
    _set(env, "TTS_COMFYUI_SKILL", comfy_tts.get("skill", ""))
    _set(env, "TTS_COMFYUI_MODE", comfy_tts.get("mode", "auto"))
    _set(env, "TTS_COMFYUI_WORKFLOW_VOICECLONE", comfy_tts.get("workflow_voiceclone", ""))
    _set(env, "TTS_COMFYUI_WORKFLOW_VOICEDESC", comfy_tts.get("workflow_voicedesc", ""))
    _set(env, "TTS_COMFYUI_WORKFLOW_VOICENAME", comfy_tts.get("workflow_voicename", ""))
    _set(env, "TTS_COMFYUI_MAX_WAIT", comfy_tts.get("max_wait", 300))
    _set(env, "TTS_COMFYUI_POLL_INTERVAL", comfy_tts.get("poll_interval", 1.0))

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

    insta = skills.get("instagram", {})
    _set(env, "SKILL_INSTAGRAM_ENABLED", insta.get("enabled", False))
    _set(env, "SKILL_INSTAGRAM_NAME", insta.get("name", "Instagram"))
    _set(env, "SKILL_INSTAGRAM_DESCRIPTION", insta.get("description", ""))
    _set(env, "SKILL_INSTAGRAM_CAPTION_LANGUAGE", insta.get("caption_language", "en"))
    _set(env, "SKILL_INSTAGRAM_DEFAULT_POPULARITY", insta.get("default_popularity", 50))
    _set(env, "SKILL_INSTAGRAM_IMAGEGEN_DEFAULT", insta.get("imagegen_default", ""))

    for skill_key, env_prefix_map in [
        ("set_location", "SKILL_SETLOCATION"),
        ("set_activity", "SKILL_SETACTIVITY"),
        ("set_mood", "SKILL_SETMOOD"),
        ("talk_to", "SKILL_TALK_TO"),
        ("send_message", "SKILL_SEND_MESSAGE"),
        ("act", "SKILL_ACT"),
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
    _set(env, "OUTFIT_CHANGE_COOLDOWN_MINUTES", oc.get("cooldown_minutes", 120))

    mw = skills.get("markdown_writer", {})
    _set(env, "SKILL_MARKDOWN_WRITER_NAME", mw.get("name", "WriteMarkdown"))
    _set(env, "SKILL_MARKDOWN_WRITER_DESCRIPTION", mw.get("description", ""))
    _set(env, "SKILL_MARKDOWN_WRITER_FOLDERS", mw.get("folders", "diary,notes,guides"))
    _set(env, "SKILL_MARKDOWN_WRITER_DEFAULT_FOLDER", mw.get("default_folder", "diary"))
    _set(env, "SKILL_MARKDOWN_WRITER_MAX_SIZE_KB", mw.get("max_size_kb", 512))
    _set(env, "SKILL_MARKDOWN_WRITER_MAX_FILES", mw.get("max_files", 50))

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
    _set(env, "EVENT_IMAGE_DENOISE_STRENGTH", re_cfg.get("event_image_denoise_strength", 0.7))

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
