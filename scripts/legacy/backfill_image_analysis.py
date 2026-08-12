"""Backfill: Fuehrt Bildanalyse (Vision-LLM) fuer alle existierenden Bilder durch
und speichert das Ergebnis in den jeweiligen Metadaten-JSON-Dateien (gleicher Name wie Bild, .json).

Betrifft:
- Gallery-Bilder: storage/users/{user}/characters/{char}/images/
- Instagram-Bilder: storage/users/{user}/instagram/

Ueberspringt Bilder, die bereits eine image_analysis haben.

Usage:
    python3 backfill_image_analysis.py [--dry-run] [--user USER] [--character CHAR]
"""
import argparse
import base64
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv()

from app.core.provider_manager import initialize_provider_manager
from app.core.llm_router import resolve_llm
from app.core.llm_client import LLMClient
from app.core.llm_queue import get_llm_queue, Priority
from app.models.character import (
    get_character_images_dir,
    _load_single_image_meta,
    _save_single_image_meta,
)
from app.models.instagram import (
    get_instagram_dir,
    load_image_meta,
    save_image_meta,
)

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}

DEFAULT_ANALYSIS_PROMPT = (
    "Describe this image in detail. Include:\n"
    "- People: appearance, clothing, pose, expression\n"
    "- Setting: location, environment, lighting\n"
    "- Objects and activities visible\n"
    "- Overall mood and atmosphere\n\n"
    "Be factual and objective. Respond ONLY with the description, "
    "no formatting, no markdown, no quotes. 2-4 sentences."
)


def get_analysis_prompt() -> str:
    """Laedt den Analyse-Prompt aus LLM_DEFAULT_IMAGE_RECOGNITION_ANALYSIS_PROMPT oder Default."""
    return os.environ.get("LLM_DEFAULT_IMAGE_RECOGNITION_ANALYSIS_PROMPT", "").strip() or DEFAULT_ANALYSIS_PROMPT


def get_vision_llm_config():
    """Laedt die Vision-LLM Konfiguration via llm_router."""
    instance = resolve_llm("image_recognition")
    if instance:
        return {
            "model": instance.model,
            "api_base": instance.api_base,
            "api_key": instance.api_key,
            "temperature": 0.3,
            "max_tokens": 300,
        }
    return None


def analyze_image(image_path: str, vcfg: dict, prompt: str) -> str:
    """Analysiert ein Bild via Vision-LLM. Gibt die Beschreibung zurueck oder leeren String."""
    if not os.path.exists(image_path):
        return ""

    try:
        with open(image_path, "rb") as f:
            image_bytes = f.read()
        base64_image = base64.b64encode(image_bytes).decode("utf-8")
    except Exception as e:
        print(f"    FEHLER beim Laden: {e}")
        return ""

    llm = LLMClient(
        model=vcfg["model"],
        api_key=vcfg["api_key"],
        api_base=vcfg["api_base"],
        temperature=vcfg["temperature"],
        max_tokens=vcfg["max_tokens"],
        request_timeout=int(os.environ.get("LLM_REQUEST_TIMEOUT", "120")),
    )

    image_url = f"data:image/png;base64,{base64_image}"
    message = {
        "role": "user",
        "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": image_url}},
        ],
    }

    try:
        response = get_llm_queue().submit(
            task_type="image_analysis",
            priority=Priority.LOW,
            llm=llm,
            messages_or_prompt=[message],
            character_name="backfill",
            user_id="system",
        )
        analysis = response.content.strip()
        if analysis.startswith('"') and analysis.endswith('"'):
            analysis = analysis[1:-1]
        if analysis.startswith("'") and analysis.endswith("'"):
            analysis = analysis[1:-1]
        return analysis
    except Exception as e:
        print(f"    FEHLER bei LLM-Analyse: {e}")
        return ""


def backfill_gallery(user_id: str, character_name: str, vcfg: dict, dry_run: bool, prompt: str = "") -> tuple:
    """Backfill fuer Gallery-Bilder eines Characters. Returns (analysed, skipped)."""
    images_dir = get_character_images_dir(user_id, character_name)
    analysed = 0
    skipped = 0

    for f in sorted(images_dir.iterdir()):
        if not f.is_file() or f.suffix.lower() not in IMAGE_EXTENSIONS:
            continue

        meta = _load_single_image_meta(user_id, character_name, f.name)
        if meta and meta.get("image_analysis"):
            skipped += 1
            continue

        if dry_run:
            print(f"    [DRY-RUN] Wuerde analysieren: {f.name}")
            analysed += 1
            continue

        print(f"    Analysiere: {f.name} ...", end=" ", flush=True)
        analysis = analyze_image(str(f), vcfg, prompt)
        if analysis:
            if meta is None:
                meta = {}
            meta.setdefault("image_filename", f.name)
            meta["image_analysis"] = analysis
            _save_single_image_meta(user_id, character_name, f.name, meta)
            print(f"OK ({len(analysis)} Zeichen)")
            analysed += 1
        else:
            print("FEHLGESCHLAGEN")

    return analysed, skipped


def backfill_instagram(user_id: str, vcfg: dict, dry_run: bool, prompt: str = "") -> tuple:
    """Backfill fuer Instagram-Bilder eines Users. Returns (analysed, skipped)."""
    instagram_dir = get_instagram_dir(user_id)
    analysed = 0
    skipped = 0

    for f in sorted(instagram_dir.iterdir()):
        if not f.is_file() or f.suffix.lower() not in IMAGE_EXTENSIONS:
            continue

        meta = load_image_meta(user_id, f.name)
        if meta and meta.get("image_analysis"):
            skipped += 1
            continue

        if dry_run:
            print(f"    [DRY-RUN] Wuerde analysieren: {f.name}")
            analysed += 1
            continue

        print(f"    Analysiere: {f.name} ...", end=" ", flush=True)
        analysis = analyze_image(str(f), vcfg, prompt)
        if analysis:
            if meta is None:
                meta = {"image_filename": f.name}
            meta["image_analysis"] = analysis
            save_image_meta(user_id, f.name, meta)
            print(f"OK ({len(analysis)} Zeichen)")
            analysed += 1
        else:
            print("FEHLGESCHLAGEN")

    return analysed, skipped


def main():
    parser = argparse.ArgumentParser(description="Backfill image analysis for all images")
    parser.add_argument("--dry-run", action="store_true", help="Nur anzeigen, nichts schreiben")
    parser.add_argument("--user", type=str, default=None, help="Nur diesen User verarbeiten")
    parser.add_argument("--character", type=str, default=None, help="Nur diesen Character (braucht --user)")
    args = parser.parse_args()

    analysis_prompt = get_analysis_prompt()

    if args.dry_run:
        print("=== DRY-RUN Modus ===\n")

    # Provider-Queues initialisieren (sonst: "No provider queue available")
    initialize_provider_manager()

    vcfg = get_vision_llm_config()
    if not vcfg:
        print("FEHLER: Kein Vision-LLM (image_recognition) konfiguriert.")
        print("Setze LLM_*_TASK=image_recognition in .env")
        sys.exit(1)

    print(f"Vision-LLM: {vcfg['model']}")
    print(f"API Base: {vcfg['api_base']}")
    print(f"Prompt: {analysis_prompt[:80]}...\n")

    storage = Path("storage/users")
    if not storage.exists():
        print("storage/users nicht gefunden")
        return

    total_analysed = 0
    total_skipped = 0

    for user_dir in sorted(storage.iterdir()):
        if not user_dir.is_dir():
            continue
        user_id = user_dir.name
        if args.user and user_id != args.user:
            continue

        # --- Gallery-Bilder ---
        chars_dir = user_dir / "characters"
        if chars_dir.exists():
            for char_dir in sorted(chars_dir.iterdir()):
                if not char_dir.is_dir():
                    continue
                character_name = char_dir.name
                if args.character and character_name != args.character:
                    continue

                images_dir = char_dir / "images"
                if not images_dir.exists():
                    continue

                print(f"Gallery: {user_id}/{character_name}")
                a, s = backfill_gallery(user_id, character_name, vcfg, args.dry_run, analysis_prompt)
                total_analysed += a
                total_skipped += s
                if a or s:
                    print(f"    → Analysiert: {a}, Uebersprungen: {s}")

        # --- Instagram-Bilder ---
        if not args.character:
            instagram_dir = user_dir / "instagram"
            if instagram_dir.exists():
                print(f"Instagram: {user_id}")
                a, s = backfill_instagram(user_id, vcfg, args.dry_run, analysis_prompt)
                total_analysed += a
                total_skipped += s
                if a or s:
                    print(f"    → Analysiert: {a}, Uebersprungen: {s}")

    print(f"\n=== Fertig ===")
    print(f"Gesamt analysiert: {total_analysed}")
    print(f"Gesamt uebersprungen: {total_skipped}")


if __name__ == "__main__":
    main()
