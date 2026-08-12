"""Migration: Extrahiert Bild-Metadaten aus feed.json und Character-Profilen
in separate JSON-Dateien im image_meta/ Verzeichnis.

Entfernt danach image_prompt aus feed.json Eintraegen.
"""
import json
import sys
from pathlib import Path

# Projekt-Root zum Path hinzufuegen
sys.path.insert(0, str(Path(__file__).parent))

from app.models.instagram import (
    get_instagram_dir,
    load_feed,
    save_feed,
    save_image_meta,
    load_image_meta,
)
from app.models.character import get_character_image_metadata


def migrate_user(user_id: str):
    """Migriert alle Bilder eines Users."""
    instagram_dir = get_instagram_dir(user_id)
    feed = load_feed(user_id)

    if not feed:
        print(f"  Kein Feed gefunden fuer {user_id}")
        return

    # Character-Metadaten laden (alle Agents)
    agent_meta_cache = {}
    for post in feed:
        an = post.get("agent_name", "")
        if an and an not in agent_meta_cache:
            try:
                agent_meta_cache[an] = get_character_image_metadata(user_id, an)
            except Exception:
                agent_meta_cache[an] = {}

    migrated = 0
    skipped = 0

    for post in feed:
        image_filename = post.get("image_filename", "")
        if not image_filename:
            continue

        # Bereits migriert?
        existing = load_image_meta(user_id, image_filename)
        if existing:
            skipped += 1
            continue

        character_name = post.get("agent_name", "")
        image_prompt = post.get("image_prompt", "")

        # Metadaten aus Character-Profil holen
        char_meta = agent_meta_cache.get(character_name, {}).get(image_filename, {})

        meta = {
            "image_filename": image_filename,
            "prompt": image_prompt,
            "backend": char_meta.get("backend", ""),
            "backend_type": char_meta.get("backend_type", ""),
            "workflow": char_meta.get("workflow", ""),
            "faceswap": char_meta.get("faceswap", False),
            "duration_s": char_meta.get("duration_s", 0.0),
            "image_analysis": "",
        }

        save_image_meta(user_id, image_filename, meta)
        migrated += 1

    # image_prompt aus Feed-Eintraegen entfernen
    changed = False
    for post in feed:
        if "image_prompt" in post:
            del post["image_prompt"]
            changed = True

    if changed:
        save_feed(user_id, feed)
        print(f"  image_prompt aus feed.json entfernt")

    print(f"  Migriert: {migrated}, Uebersprungen: {skipped}")


def main():
    # Alle User-Verzeichnisse mit instagram/ Ordner finden
    storage = Path("storage/users")
    if not storage.exists():
        print("storage/users nicht gefunden")
        return

    for user_dir in storage.iterdir():
        if not user_dir.is_dir():
            continue
        instagram_dir = user_dir / "instagram"
        if not instagram_dir.exists():
            continue

        user_id = user_dir.name
        print(f"Migriere User: {user_id}")
        migrate_user(user_id)

    print("Migration abgeschlossen.")


if __name__ == "__main__":
    main()
