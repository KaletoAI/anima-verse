"""Invalidate extraction fingerprints when their memories are erased."""
from app.core.character_reset import register_reset_store, SCOPES
from app.models.character import get_character_dir


def reset_cache(conn, character_name):
    root = get_character_dir(character_name).resolve()
    path = root / "skills" / "knowledge_extract_cache.json"
    if not path.resolve().is_relative_to(root):
        raise ValueError("Knowledge cache escapes character directory")
    existed = path.exists()
    path.unlink(missing_ok=True)
    return int(existed)


register_reset_store("knowledge_extract_cache", reset_cache, SCOPES,
                     what="extracted-fact file fingerprints")
