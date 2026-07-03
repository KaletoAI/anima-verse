"""Configuration validator — checks for common misconfigurations.

Each check returns a list of issues: {"level": "error"|"warning", "section": str, "message": str}
"""
from pathlib import Path
from typing import Any, Dict, List

from app.core.log import get_logger

logger = get_logger("config_validator")


def validate_config(config: dict) -> List[Dict[str, Any]]:
    """Run all validation checks on the config. Returns a list of issues."""
    issues = []
    issues.extend(_check_providers(config))
    issues.extend(_check_llm_routing(config))
    issues.extend(_check_image_backends(config))
    issues.extend(_check_animation(config))
    issues.extend(_check_tts(config))
    issues.extend(_check_skills(config))
    issues.extend(_check_server(config))
    return issues


def _err(section: str, msg: str) -> dict:
    return {"level": "error", "section": section, "message": msg}


def _warn(section: str, msg: str) -> dict:
    return {"level": "warning", "section": section, "message": msg}


# ── Provider Checks ──

def _check_providers(config: dict) -> list:
    issues = []
    providers = config.get("providers", [])
    if not providers:
        issues.append(_err("providers", "Keine Provider konfiguriert"))
        return issues

    names = set()
    for i, p in enumerate(providers):
        name = p.get("name", "")
        ptype = p.get("type", "")
        api_base = p.get("api_base", "")
        api_key = p.get("api_key", "")

        if not name:
            issues.append(_err("providers", f"Provider #{i+1}: Name fehlt"))
        elif name in names:
            issues.append(_err("providers", f"Provider '{name}': Doppelter Name"))
        names.add(name)

        if not api_base:
            issues.append(_err("providers", f"Provider '{name}': API Base URL fehlt"))

        # API Key check for cloud providers
        if ptype == "anthropic" and (not api_key or api_key in ("not-needed", "YOUR_ANTHROPIC_API_KEY")):
            issues.append(_err("providers", f"Provider '{name}': Anthropic benoetigt einen gueltigen API Key"))
        if api_base and "together.xyz" in api_base and (not api_key or api_key == "not-needed"):
            issues.append(_err("providers", f"Provider '{name}': Together.ai benoetigt einen API Key"))
        if api_base and "api.anthropic.com" in api_base and (not api_key or api_key in ("not-needed", "YOUR_ANTHROPIC_API_KEY")):
            issues.append(_err("providers", f"Provider '{name}': API Key fehlt oder ist Platzhalter"))

    return issues


# ── LLM Routing Checks ──

def _check_llm_routing(config: dict) -> list:
    from app.core.llm_tasks import TASK_TYPES, is_task_gated_off
    issues = []
    routing = config.get("llm_routing", [])
    if not isinstance(routing, list):
        issues.append(_err("llm_routing", "llm_routing muss eine Liste sein"))
        return issues

    providers = config.get("providers", [])
    provider_names = {p.get("name", "") for p in providers}

    # Coverage: task -> [(order, entry_idx)]
    coverage: dict = {}
    # (task, order) -> [entry_idx]
    order_keys: dict = {}

    for idx, entry in enumerate(routing):
        if not isinstance(entry, dict):
            issues.append(_err("llm_routing", f"Eintrag #{idx+1}: kein Objekt"))
            continue
        # Disabled-Eintraege werden zur Laufzeit ignoriert -> keine
        # Coverage/Order-/Provider-Validierung (sonst meldet die UI Fehler
        # fuer bewusst stillgelegte Modelle).
        if entry.get("enabled") is False:
            continue
        provider = (entry.get("provider") or "").strip()
        model = (entry.get("model") or "").strip()
        label = model or f"#{idx+1}"
        if not provider:
            issues.append(_err("llm_routing", f"{label}: Provider fehlt"))
        elif provider not in provider_names:
            issues.append(_err("llm_routing", f"{label}: Provider '{provider}' existiert nicht"))
        if not model:
            issues.append(_err("llm_routing", f"Eintrag #{idx+1}: Model fehlt"))

        tasks = entry.get("tasks") or []
        if not isinstance(tasks, list):
            continue
        for t in tasks:
            if not isinstance(t, dict):
                continue
            tid = t.get("task")
            order = t.get("order")
            if not tid:
                continue
            coverage.setdefault(tid, []).append((order, idx))
            if order is not None:
                order_keys.setdefault((tid, int(order)), []).append(idx)

    # Order-Uniqueness
    for (tid, order), idxs in order_keys.items():
        if len(idxs) > 1:
            issues.append(_err(
                "llm_routing",
                f"Task '{tid}' Order {order} mehrfach vergeben (Eintraege {', '.join('#'+str(i+1) for i in idxs)})"
            ))

    # Coverage: jeder Task im Katalog braucht mindestens einen Eintrag — ausser Gate off
    for tid in TASK_TYPES.keys():
        if coverage.get(tid):
            continue
        if is_task_gated_off(tid, config):
            continue
        # pose_embedding laeuft ueber config.embedding (eingebautes fastembed/ONNX
        # oder externer /v1/embeddings-Provider), NICHT ueber llm_routing. Nur bei
        # backend="external" wird ein gerouteter Provider erwartet.
        if tid == "pose_embedding" and (config.get("embedding", {}) or {}).get("backend", "auto") != "external":
            continue
        issues.append(_warn("llm_routing", f"Task '{tid}' hat keinen LLM-Eintrag"))

    # Unbekannte Tasks
    for tid in coverage.keys():
        if tid not in TASK_TYPES:
            issues.append(_warn("llm_routing", f"Unbekannter Task '{tid}' — nicht im Katalog"))

    return issues


# ── Image Backend Checks ──

def _check_image_backends(config: dict) -> list:
    issues = []
    ig = config.get("image_generation", {})
    backends = ig.get("backends", [])

    for be in backends:
        name = be.get("name", "?")
        enabled = be.get("enabled", True)
        if not enabled:
            continue

        api_type = be.get("api_type", "")
        api_url = be.get("api_url", "")
        api_key = be.get("api_key", "")

        if not api_url:
            issues.append(_err("image_generation", f"Backend '{name}': API URL fehlt"))

        # Echte Cloud-Backends brauchen einen API Key. openai_chat/localai/openai_diffusion
        # sind generisch (koennen auf LocalAI/vLLM/Gateway ohne Key zeigen) -> kein Zwang.
        if api_type in ("civitai", "together") and not api_key:
            issues.append(_err("image_generation", f"Backend '{name}': API Key fehlt (Cloud-Backend '{api_type}')"))

    # Use-case default render targets (backend globs)
    for field_name, label in [
        ("outfit_imagegen_default", "Outfit"),
        ("expression_imagegen_default", "Expression"),
        ("location_imagegen_default", "Location"),
    ]:
        val = ig.get(field_name, "")
        if val:
            _check_imagegen_ref(val, backends, "image_generation", label, issues)

    return issues


def _check_imagegen_ref(val: str, backends: list, section: str, label: str, issues: list):
    """Validate a render-target spec against the configured backend names.

    Match concept: the name part is a glob (e.g. "Qwen*"); valid when it
    matches at least one backend name (fnmatch, case-insensitive). An exact
    name matches itself. Accepted formats: ``backend:<glob>`` or a bare
    glob. Legacy ``workflow:<glob>`` specs are reported — ComfyUI was
    removed and such specs are ignored at runtime.
    """
    import fnmatch
    if ":" in val:
        ref_type, ref_name = val.split(":", 1)
        if ref_type == "workflow":
            issues.append(_warn(
                section,
                f"{label} Default '{val}': ComfyUI entfernt — auf 'backend:<glob>' umstellen"))
            return
        if ref_type != "backend":
            return
        pat = ref_name.strip()
    else:
        pat = val.strip()
    if not pat:
        return
    pl = pat.lower()
    be_names = {b.get("name", "") for b in backends}
    if not any(fnmatch.fnmatch(str(n).lower(), pl) for n in be_names):
        issues.append(_warn(section, f"{label} Default: kein Backend passt auf '{pat}'"))


# ── Animation Checks ──

def _check_animation(config: dict) -> list:
    issues = []
    anim = config.get("animation", {})

    comfy = anim.get("comfy", {})
    if comfy.get("enabled"):
        if not comfy.get("workflow_file"):
            issues.append(_err("animation", "ComfyUI Animation: Workflow Datei fehlt"))
        elif not Path(comfy["workflow_file"]).exists():
            issues.append(_err("animation", f"ComfyUI Animation: Datei '{comfy['workflow_file']}' nicht gefunden"))
        if not comfy.get("unet_high") and not comfy.get("unet_low"):
            issues.append(_warn("animation", "ComfyUI Animation: Kein UNet Model konfiguriert"))

    together = anim.get("together", {})
    if together.get("enabled"):
        if not together.get("model"):
            issues.append(_warn("animation", "Together Animation: Kein Model konfiguriert"))

    return issues


# ── TTS Checks ──

def _check_tts(config: dict) -> list:
    issues = []
    tts = config.get("tts", {})
    if not tts.get("enabled"):
        return issues

    backend = tts.get("backend", "")

    if backend == "xtts":
        xtts = tts.get("xtts", {})
        if not xtts.get("url"):
            issues.append(_err("tts", "XTTS: URL fehlt"))

    elif backend == "f5":
        f5 = tts.get("f5", {})
        if not f5.get("url"):
            issues.append(_err("tts", "F5-TTS: URL fehlt"))

    elif backend == "magpie":
        magpie = tts.get("magpie", {})
        if not magpie.get("url"):
            issues.append(_err("tts", "Magpie: URL fehlt"))
        if not magpie.get("voice"):
            issues.append(_warn("tts", "Magpie: Keine Stimme konfiguriert"))

    elif backend == "comfyui":
        comfy_tts = tts.get("comfyui", {})
        skill = comfy_tts.get("skill", "")
        if not skill:
            issues.append(_err("tts", "ComfyUI TTS: Kein Backend konfiguriert"))
        else:
            ig = config.get("image_generation", {})
            ig_backends = ig.get("backends", [])
            # skill can be comma-separated list of backend names
            skill_names = [s.strip() for s in skill.split(",") if s.strip()] if isinstance(skill, str) else skill if isinstance(skill, list) else []
            for sn in skill_names:
                be = next((b for b in ig_backends if b.get("name") == sn), None)
                if not be:
                    issues.append(_err("tts", f"ComfyUI TTS: Backend '{sn}' existiert nicht"))
                elif be.get("api_type") != "comfyui":
                    issues.append(_err("tts", f"ComfyUI TTS: Backend '{sn}' ist kein ComfyUI-Backend (Typ: {be.get('api_type', '?')})"))

    return issues


# ── Skills Checks ──

def _check_skills(config: dict) -> list:
    issues = []
    skills = config.get("skills", {})

    searx = skills.get("searx", {})
    if searx.get("enabled") and not searx.get("url"):
        issues.append(_err("skills", "SearX: Aktiviert aber keine URL konfiguriert"))

    return issues


# ── Server Checks ──

def _check_server(config: dict) -> list:
    issues = []
    server = config.get("server", {})

    jwt = server.get("jwt_secret", "")
    if not jwt or jwt == "your-secret-key-change-in-production":
        issues.append(_warn("server", "JWT Secret ist der Default-Wert — bitte fuer Production aendern"))

    # Story engine references
    se = config.get("story_engine", {})
    if se.get("enabled"):
        val = se.get("imagegen_default", "")
        if val:
            ig = config.get("image_generation", {})
            _check_imagegen_ref(val, ig.get("backends", []), "story_engine", "Story Engine", issues)

    # Instagram reference
    insta = config.get("skills", {}).get("instagram", {})
    if insta.get("enabled"):
        val = insta.get("imagegen_default", "")
        if val:
            ig = config.get("image_generation", {})
            _check_imagegen_ref(val, ig.get("backends", []), "skills", "Instagram", issues)

    return issues
