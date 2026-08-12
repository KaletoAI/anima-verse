"""Migration: Extrahiert Bild-Metadaten (image_prompts, image_comments, image_metadata)
aus Character-Profilen in separate JSON-Dateien im images/image_meta/ Verzeichnis.

Entfernt danach die alten Keys aus dem Profil.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.models.character import (
    get_character_profile,
    save_character_profile,
    get_character_images_dir,
    _load_single_image_meta,
    _save_single_image_meta,
)


def migrate_character(user_id: str, character_name: str):
    """Migriert alle Bild-Daten eines Characters."""
    profile = get_character_profile(user_id, character_name)
    if not profile:
        return

    old_prompts = profile.get("image_prompts", {})
    old_comments = profile.get("image_comments", {})
    old_metadata = profile.get("image_metadata", {})

    # Alle betroffenen Bilder sammeln
    all_images = set(old_prompts.keys()) | set(old_comments.keys()) | set(old_metadata.keys())

    if not all_images:
        print(f"    Keine Bild-Daten zu migrieren")
        return

    migrated = 0
    skipped = 0

    for image_filename in all_images:
        # Pruefen ob bereits migriert
        existing = _load_single_image_meta(user_id, character_name, image_filename)
        if existing and existing.get("prompt") and existing.get("_migrated"):
            skipped += 1
            continue

        meta = existing.copy() if existing else {}
        meta["image_filename"] = image_filename

        # Prompt
        if image_filename in old_prompts:
            meta["prompt"] = old_prompts[image_filename]

        # Comment
        if image_filename in old_comments:
            meta["comment"] = old_comments[image_filename]

        # Metadata (backend, backend_type, workflow, faceswap, duration_s)
        if image_filename in old_metadata:
            meta.update(old_metadata[image_filename])

        # Defaults setzen
        meta.setdefault("prompt", "")
        meta.setdefault("comment", "")
        meta.setdefault("backend", "")
        meta.setdefault("backend_type", "")
        meta.setdefault("workflow", "")
        meta.setdefault("faceswap", False)
        meta.setdefault("duration_s", 0.0)
        meta.setdefault("image_analysis", "")
        meta["_migrated"] = True

        _save_single_image_meta(user_id, character_name, image_filename, meta)
        migrated += 1

    # Alte Keys aus Profil entfernen
    changed = False
    for key in ("image_prompts", "image_comments", "image_metadata"):
        if key in profile:
            del profile[key]
            changed = True

    if changed:
        save_character_profile(user_id, character_name, profile)
        print(f"    Alte Keys aus Profil entfernt")

    print(f"    Migriert: {migrated}, Uebersprungen: {skipped}")


def main():
    storage = Path("storage/users")
    if not storage.exists():
        print("storage/users nicht gefunden")
        return

    for user_dir in storage.iterdir():
        if not user_dir.is_dir():
            continue

        chars_dir = user_dir / "characters"
        if not chars_dir.exists():
            continue

        user_id = user_dir.name
        for char_dir in chars_dir.iterdir():
            if not char_dir.is_dir():
                continue
            character_name = char_dir.name
            print(f"Migriere: {user_id}/{character_name}")
            migrate_character(user_id, character_name)

    print("Migration abgeschlossen.")


if __name__ == "__main__":
    main()
