"""Migration: Verschiebt Metadaten-JSONs aus image_meta/ Unterverzeichnissen
direkt neben die Bilder (gleicher Name, .json Endung).

Betrifft:
- storage/users/{user}/characters/{char}/images/image_meta/*.json → images/*.json
- storage/users/{user}/instagram/image_meta/*.json → instagram/*.json

Loescht leere image_meta/ Verzeichnisse nach der Migration.
"""
import shutil
import sys
from pathlib import Path


def migrate_dir(image_meta_dir: Path, target_dir: Path, label: str):
    """Verschiebt alle JSON-Dateien aus image_meta_dir nach target_dir."""
    if not image_meta_dir.exists():
        return

    moved = 0
    skipped = 0
    for json_file in image_meta_dir.glob("*.json"):
        dst = target_dir / json_file.name
        if dst.exists():
            # Bereits vorhanden — Quelle loeschen
            json_file.unlink()
            skipped += 1
        else:
            shutil.move(str(json_file), str(dst))
            moved += 1

    # Leeres Verzeichnis loeschen
    try:
        if image_meta_dir.exists() and not any(image_meta_dir.iterdir()):
            image_meta_dir.rmdir()
            print(f"  {label}: image_meta/ Verzeichnis geloescht")
    except Exception:
        pass

    if moved or skipped:
        print(f"  {label}: Verschoben: {moved}, Uebersprungen: {skipped}")


def main():
    storage = Path("storage/users")
    if not storage.exists():
        print("storage/users nicht gefunden")
        return

    for user_dir in sorted(storage.iterdir()):
        if not user_dir.is_dir():
            continue
        user_id = user_dir.name

        # Character Gallery images
        chars_dir = user_dir / "characters"
        if chars_dir.exists():
            for char_dir in sorted(chars_dir.iterdir()):
                if not char_dir.is_dir():
                    continue
                images_dir = char_dir / "images"
                meta_dir = images_dir / "image_meta"
                if meta_dir.exists():
                    migrate_dir(meta_dir, images_dir, f"{user_id}/{char_dir.name}")

        # Instagram
        instagram_dir = user_dir / "instagram"
        meta_dir = instagram_dir / "image_meta"
        if meta_dir.exists():
            migrate_dir(meta_dir, instagram_dir, f"{user_id}/instagram")

    print("Migration abgeschlossen.")


if __name__ == "__main__":
    main()
