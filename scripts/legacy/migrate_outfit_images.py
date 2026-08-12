"""Migration: Verschiebt Outfit-Bilder von images/ nach outfits/
und entfernt die images-Liste aus Character-Profilen.
"""
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.models.character import (
    get_character_profile,
    save_character_profile,
    get_character_images_dir,
    get_character_outfits_dir,
    get_character_outfits,
)


def migrate_character(user_id: str, character_name: str):
    """Migriert Outfit-Bilder und entfernt images-Liste."""
    profile = get_character_profile(user_id, character_name)
    if not profile:
        return

    outfits = get_character_outfits(user_id, character_name)
    images_dir = get_character_images_dir(user_id, character_name)
    outfits_dir = get_character_outfits_dir(user_id, character_name)

    # Outfit-Bilder verschieben
    moved = 0
    for outfit in outfits:
        img = outfit.get("image", "")
        if not img:
            continue
        src = images_dir / img
        dst = outfits_dir / img
        if src.exists() and not dst.exists():
            shutil.move(str(src), str(dst))
            moved += 1
            print(f"    Verschoben: {img}")
        elif dst.exists():
            # Bereits im outfits/ Verzeichnis — Quelle loeschen falls doppelt
            if src.exists():
                src.unlink()

    # images-Liste aus Profil entfernen
    changed = False
    if "images" in profile:
        del profile["images"]
        changed = True

    if changed:
        save_character_profile(user_id, character_name, profile)
        print(f"    images-Liste aus Profil entfernt")

    print(f"    Outfit-Bilder verschoben: {moved}")


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
