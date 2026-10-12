"""Preflight for explicit reference upscale picks (no fallback)."""
from app.imagegen.routing import normalize_spec, resolve_spec
from app.imagegen.service import get_image_service


def require_upscale_backend(pick: str, character_name: str = ''):
    """Probe a special-purpose backend without the ordinary generator matcher."""
    import fnmatch
    service = get_image_service()
    pattern = normalize_spec(pick).lower()
    for backend in service.backends:
        if (fnmatch.fnmatch(backend.name.lower(), pattern) and backend.instance_enabled
                and backend.category == 'upscale' and not backend.in_cooldown()):
            backend.check_availability()
    _, selected = resolve_spec('upscale', pick, character=character_name, pool=service.pool)
    if selected is None:
        raise ValueError('Selected upscale backend is unavailable — no automatic fallback')
    return selected
