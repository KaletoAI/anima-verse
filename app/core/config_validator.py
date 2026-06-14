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
    issues.extend(_check_comfyui_workflows(config))
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
    providers = config.get("providers", [])

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

        # Cloud backends need API key
        if api_type in ("mammouth", "civitai", "together") and not api_key:
            issues.append(_err("image_generation", f"Backend '{name}': API Key fehlt (Cloud-Backend '{api_type}')"))

    # Hinweis: LLM-Provider-GPUs vom Typ 'comfyui' sind veraltet — die Queue
    # lebt jetzt pro ImageGen-Backend. Ein Warnhinweis hilft beim Aufraeumen.
    legacy_comfy_gpus = []
    for p in providers:
        for g in (p.get("gpus") or []):
            if "comfyui" in (g.get("types") or []):
                legacy_comfy_gpus.append(p.get("name", "?"))
                break
    if legacy_comfy_gpus:
        issues.append(_warn(
            "providers",
            f"Provider mit GPU-Typ 'comfyui' gefunden ({', '.join(legacy_comfy_gpus)}): "
            "wird nicht mehr fuer Routing genutzt. Typ aus den GPU-Eintraegen entfernen — "
            "jedes ComfyUI-Backend hat jetzt seinen eigenen Channel."))

    return issues


# ── ComfyUI Workflow Checks ──

def _check_comfyui_workflows(config: dict) -> list:
    issues = []
    ig = config.get("image_generation", {})
    workflows = ig.get("comfyui_workflows", {})
    backends = ig.get("backends", [])
    comfy_backend_names = {b.get("name", "") for b in backends if b.get("api_type") == "comfyui"}

    # Das Feld ist ein Match-Glob (z.B. "Flux2*"), zur Laufzeit via fnmatch in
    # match_workflow aufgeloest — also auch hier als Glob pruefen, nicht exakt.
    # Ein Name ohne Wildcard ist ein Glob der sich selbst matcht.
    default_wf = ig.get("comfy_default_workflow", "")
    if default_wf:
        import fnmatch
        wf_names = {wid: wf.get("name", wid) for wid, wf in workflows.items()}
        pat = default_wf.lower()
        match = default_wf in workflows or any(
            fnmatch.fnmatch(n.lower(), pat) for n in wf_names.values()
        )
        if not match:
            available = ", ".join(wf_names.values()) if wf_names else "keine"
            issues.append(_warn("image_generation", f"Default ComfyUI Workflow-Glob '{default_wf}' matcht keinen Workflow (verfuegbar: {available})"))

    for wid, wf in workflows.items():
        name = wf.get("name", wid)
        wf_file = wf.get("workflow_file", "")

        # Punkte im Key brechen den Admin-Editor (Felder werden per Dot-Notation
        # adressiert, ..comfyui_workflows.<KEY>.<feld>, und split('.') zerlegt).
        # Keys werden beim Load auto-migriert; Namen muss der Admin selbst aendern.
        if "." in wid:
            issues.append(_err("image_generation", f"Workflow-Key '{wid}' enthaelt einen Punkt — das bricht den Admin-Editor. Bitte ohne Punkt benennen."))
        if "." in name:
            issues.append(_err("image_generation", f"Workflow '{name}': Der Name enthaelt einen Punkt — bitte ohne Punkt benennen (z.B. 'Flux 1 Dev' statt 'Flux.1 Dev')."))

        # Workflow file exists?
        if wf_file and not Path(wf_file).exists():
            issues.append(_err("image_generation", f"Workflow '{name}': Datei '{wf_file}' nicht gefunden"))

        # Backend reference
        skill = wf.get("skill", "")
        if skill and skill not in comfy_backend_names:
            issues.append(_warn("image_generation", f"Workflow '{name}': Backend '{skill}' ist kein ComfyUI-Backend"))

        # Model set?
        if not wf.get("model", ""):
            issues.append(_warn("image_generation", f"Workflow '{name}': Kein Model konfiguriert"))

    # Check imagegen_default references
    for field_name, label in [
        ("outfit_imagegen_default", "Outfit"),
        ("expression_imagegen_default", "Expression"),
        ("location_imagegen_default", "Location"),
    ]:
        val = ig.get(field_name, "")
        if val:
            _check_imagegen_ref(val, workflows, backends, "image_generation", label, issues)

    return issues


def _check_imagegen_ref(val: str, workflows: dict, backends: list, section: str, label: str, issues: list):
    """Validate a 'workflow:<glob>' or 'backend:<glob>' reference.

    Match-Konzept: der Name-Teil ist ein Glob (z.B. "Qwen*"); gueltig, wenn er
    auf mindestens einen Workflow- bzw. Backend-Namen passt (fnmatch, case-
    insensitive). Ein exakter Name matcht sich selbst.
    """
    if ":" not in val:
        return
    import fnmatch
    ref_type, ref_name = val.split(":", 1)
    pat = ref_name.strip().lower()
    if not pat:
        return
    if ref_type == "workflow":
        names = {wf.get("name", k) for k, wf in workflows.items()} | set(workflows.keys())
        if not any(fnmatch.fnmatch(str(n).lower(), pat) for n in names):
            issues.append(_warn(section, f"{label} Default: kein Workflow passt auf '{ref_name}'"))
    elif ref_type == "backend":
        be_names = {b.get("name", "") for b in backends}
        if not any(fnmatch.fnmatch(str(n).lower(), pat) for n in be_names):
            issues.append(_warn(section, f"{label} Default: kein Backend passt auf '{ref_name}'"))


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
            _check_imagegen_ref(val, ig.get("comfyui_workflows", {}), ig.get("backends", []), "story_engine", "Story Engine", issues)

    # Instagram reference
    insta = config.get("skills", {}).get("instagram", {})
    if insta.get("enabled"):
        val = insta.get("imagegen_default", "")
        if val:
            ig = config.get("image_generation", {})
            _check_imagegen_ref(val, ig.get("comfyui_workflows", {}), ig.get("backends", []), "skills", "Instagram", issues)

    return issues
