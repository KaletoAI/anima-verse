"""Configuration validator — checks for common misconfigurations.

Each check returns a list of issues: {"level": "error"|"warning", "section": str, "message": str}
"""
from typing import Any, Dict, List

from app.core.log import get_logger

logger = get_logger("config_validator")


def validate_config(config: dict) -> List[Dict[str, Any]]:
    """Run all validation checks on the config. Returns a list of issues."""
    issues = []
    issues.extend(_check_providers(config))
    issues.extend(_check_llm_routing(config))
    issues.extend(_check_image_backends(config))
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
        issues.append(_err("providers", "No providers configured"))
        return issues

    names = set()
    for i, p in enumerate(providers):
        name = p.get("name", "")
        ptype = p.get("type", "")
        api_base = p.get("api_base", "")
        api_key = p.get("api_key", "")

        if not name:
            issues.append(_err("providers", f"Provider #{i+1}: name missing"))
        elif name in names:
            issues.append(_err("providers", f"Provider '{name}': duplicate name"))
        names.add(name)

        if not api_base:
            issues.append(_err("providers", f"Provider '{name}': API base URL missing"))

        # API key check for cloud providers
        if ptype == "anthropic" and (not api_key or api_key in ("not-needed", "YOUR_ANTHROPIC_API_KEY")):
            issues.append(_err("providers", f"Provider '{name}': Anthropic requires a valid API key"))
        if api_base and "together.xyz" in api_base and (not api_key or api_key == "not-needed"):
            issues.append(_err("providers", f"Provider '{name}': Together.ai requires an API key"))
        if api_base and "api.anthropic.com" in api_base and (not api_key or api_key in ("not-needed", "YOUR_ANTHROPIC_API_KEY")):
            issues.append(_err("providers", f"Provider '{name}': API key missing or placeholder"))

    return issues


# ── LLM Routing Checks ──

def _check_llm_routing(config: dict) -> list:
    from app.core.llm_tasks import TASK_TYPES, is_task_gated_off
    issues = []
    routing = config.get("llm_routing", [])
    if not isinstance(routing, list):
        issues.append(_err("llm_routing", "llm_routing must be a list"))
        return issues

    providers = config.get("providers", [])
    provider_names = {p.get("name", "") for p in providers}

    # Coverage: task -> [(order, entry_idx)]
    coverage: dict = {}
    # (task, order) -> [entry_idx]
    order_keys: dict = {}

    for idx, entry in enumerate(routing):
        if not isinstance(entry, dict):
            issues.append(_err("llm_routing", f"Entry #{idx+1}: not an object"))
            continue
        # Disabled entries are ignored at runtime -> no coverage/order/
        # provider validation (otherwise the UI reports errors for models
        # that were deliberately shut off).
        if entry.get("enabled") is False:
            continue
        provider = (entry.get("provider") or "").strip()
        model = (entry.get("model") or "").strip()
        label = model or f"#{idx+1}"
        if not provider:
            issues.append(_err("llm_routing", f"{label}: provider missing"))
        elif provider not in provider_names:
            issues.append(_err("llm_routing", f"{label}: provider '{provider}' does not exist"))
        if not model:
            issues.append(_err("llm_routing", f"Entry #{idx+1}: model missing"))

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

    # Order uniqueness
    for (tid, order), idxs in order_keys.items():
        if len(idxs) > 1:
            issues.append(_err(
                "llm_routing",
                f"Task '{tid}' order {order} assigned multiple times (entries {', '.join('#'+str(i+1) for i in idxs)})"
            ))

    # Coverage: every task in the catalog needs at least one entry — unless gated off
    for tid in TASK_TYPES.keys():
        if coverage.get(tid):
            continue
        if is_task_gated_off(tid, config):
            continue
        # pose_embedding runs via config.embedding (built-in fastembed/ONNX or
        # an external /v1/embeddings provider), NOT via llm_routing. A routed
        # provider is only expected for backend="external".
        if tid == "pose_embedding" and (config.get("embedding", {}) or {}).get("backend", "auto") != "external":
            continue
        issues.append(_warn("llm_routing", f"Task '{tid}' has no LLM entry"))

    # Unknown tasks
    for tid in coverage.keys():
        if tid not in TASK_TYPES:
            issues.append(_warn("llm_routing", f"Unknown task '{tid}' — not in the catalog"))

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
            issues.append(_err("image_generation", f"Backend '{name}': API URL missing"))

        # Real cloud backends need an API key. openai_chat/localai/openai_diffusion
        # + localai_video are generic (may point at LocalAI/vLLM/gateway without a
        # key) -> no requirement.
        if api_type in ("civitai", "together", "together_video") and not api_key:
            issues.append(_err("image_generation", f"Backend '{name}': API key missing (cloud backend '{api_type}')"))

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
                f"{label} default '{val}': ComfyUI was removed — switch to 'backend:<glob>'"))
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
        issues.append(_warn(section, f"{label} default: no backend matches '{pat}'"))


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
            issues.append(_err("tts", "XTTS: URL missing"))

    elif backend == "f5":
        f5 = tts.get("f5", {})
        if not f5.get("url"):
            issues.append(_err("tts", "F5-TTS: URL missing"))

    elif backend == "magpie":
        magpie = tts.get("magpie", {})
        if not magpie.get("url"):
            issues.append(_err("tts", "Magpie: URL missing"))
        if not magpie.get("voice"):
            issues.append(_warn("tts", "Magpie: no voice configured"))

    return issues


# ── Skills Checks ──

def _check_skills(config: dict) -> list:
    issues = []
    skills = config.get("skills", {})

    searx = skills.get("searx", {})
    if searx.get("enabled") and not searx.get("url"):
        issues.append(_err("skills", "SearX: enabled but no URL configured"))

    return issues


# ── Server Checks ──

def _check_server(config: dict) -> list:
    issues = []
    server = config.get("server", {})

    jwt = server.get("jwt_secret", "")
    if not jwt or jwt == "your-secret-key-change-in-production":
        issues.append(_warn("server", "JWT secret is the default value — change it for production"))

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
