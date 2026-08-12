#!/usr/bin/env python3
"""LLM-basierte Review von Expression/Pose-Presets.

Laesst ein LLM alle Presets (Keys + Prompt + Synonyme) einer Datei bewerten
und schreibt einen angereicherten Ziel-JSON mit Review-Block pro Eintrag.

Usage:
  python scripts/review_presets.py --list
  python scripts/review_presets.py --llm Evo-X2::Qwen3.5-9B-heretic \
      --source shared/templates/expression/expression_presets.json \
      --target /tmp/expression_review.json

  python scripts/review_presets.py --llm Evo-X2::Qwen3.5-9B-heretic \
      --source shared/templates/pose/pose_presets_generated.json \
      --target /tmp/pose_generated_review.json \
      --limit 20

Ausgabeformat (Ziel-JSON, gleiche Struktur wie Quelle + "_review" pro Preset):
  {
    "presets": {
      "happy": {
        "prompt": "warm genuine smile, ...",
        "synonyms": [...],
        "_review": {
          "rating": 4,
          "issues": ["missing eyebrow detail"],
          "suggested_prompt": "...",
          "keep": true
        }
      }
    }
  }
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# Projekt-Root ins sys.path damit wir app.* importieren koennen
_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))

# CLI vor-Parsing nur fuer --world (muss vor paths.init() passieren).
# Die volle Argument-Parser-Logik kommt spaeter in main().
import os as _os  # noqa: E402
_world_override = None
for i, _arg in enumerate(sys.argv):
    if _arg == "--world" and i + 1 < len(sys.argv):
        _world_override = sys.argv[i + 1]
        break
    if _arg.startswith("--world="):
        _world_override = _arg.split("=", 1)[1]
        break

# Bootstrap genauso wie in app/server.py:
#   1. paths.init()  — Storage-Dir (via --world / STORAGE_DIR / default) setzen
#   2. config.load() — JSON-Config laden, os.environ befuellen
#   3. provider_manager initialisieren — liest Provider aus Env
#   4. llm_router nutzen — LLMInstance fuer explizite Model-Overrides
from app.core import paths as _paths_mod  # noqa: E402
if _world_override:
    _paths_mod.init(Path("worlds") / _world_override)
else:
    _paths_mod.init()

from app.core.config import load as _load_config  # noqa: E402
_load_config(_paths_mod.get_config_path())

from app.core.provider_manager import (  # noqa: E402
    get_provider_manager, initialize_provider_manager,
)
from app.core.llm_router import create_llm_instance  # noqa: E402

# Provider initialisieren (wie im Server-Lifespan); llm_router resolved lazy.
initialize_provider_manager()


# ============================================================================
# LLM-Prompts fuer Review
# ============================================================================

_REVIEW_SYSTEM_EXPRESSION = (
    "You review facial-expression presets used to guide image generation. "
    "Each entry maps a mood keyword to a short English sentence describing "
    "face details (eyes, eyebrows, mouth, jaw). "
    "Rate each entry on quality and usefulness."
)

_REVIEW_SYSTEM_POSE = (
    "You review body-pose presets used to guide image generation. "
    "Each entry maps an activity keyword to a short English sentence describing "
    "body position (arms, legs, posture, weight distribution). "
    "Rate each entry on quality and usefulness."
)

_REVIEW_USER_TEMPLATE = (
    "Review this preset entry:\n"
    "\n"
    "  key:      {key}\n"
    "  prompt:   {prompt}\n"
    "  synonyms: {synonyms}\n"
    "\n"
    "Evaluate:\n"
    "- rating: 1 (bad) to 5 (excellent) — does the prompt accurately describe the keyword?\n"
    "- issues: list of concrete problems (too generic, wrong focus, character/location leaked, not a real expression/pose, etc.). Empty list if fine.\n"
    "- suggested_prompt: a better version if rating < 4, otherwise null.\n"
    "- keep: false if the entry should be DELETED (character-specific, junk, activity instead of pose/expression, etc.), true otherwise.\n"
    "\n"
    "Reply with ONLY a valid JSON object like this (no other text):\n"
    '{{"rating": 4, "issues": [], "suggested_prompt": null, "keep": true}}'
)


def _guess_kind(source_path: Path) -> str:
    """Erraet ob expression oder pose basierend auf Pfad."""
    s = str(source_path).lower()
    if "expression" in s:
        return "expression"
    if "pose" in s:
        return "pose"
    return "expression"


# ============================================================================
# LLM-Resolution
# ============================================================================

def list_available_llms() -> List[Dict[str, str]]:
    """Listet alle verfuegbaren provider::model Kombinationen."""
    pm = get_provider_manager()
    result = []
    all_models = pm.list_all_models()
    for provider_name, info in all_models.items():
        for m in info.get("models", []):
            name = m.get("name") if isinstance(m, dict) else str(m)
            if not name:
                continue
            result.append({
                "provider": provider_name,
                "model": name,
                "id": f"{provider_name}::{name}",
                "type": info.get("type", ""),
            })
    return result


def print_available_llms():
    """Gibt verfuegbare LLMs gruppiert nach Provider aus."""
    llms = list_available_llms()
    if not llms:
        print("Keine LLMs gefunden. Pruefe PROVIDER_* in .env und Config.")
        return
    current = ""
    for entry in sorted(llms, key=lambda x: (x["provider"], x["model"])):
        if entry["provider"] != current:
            current = entry["provider"]
            print(f"\n{current} ({entry['type']}):")
        print(f"  {entry['id']}")
    print()


def resolve_llm(identifier: str):
    """Loest 'provider::model' in einen LLMClient (app.core.llm_client) auf."""
    if "::" not in identifier:
        print(f"FEHLER: LLM muss im Format provider::model angegeben werden (z.B. 'Evo-X2::Qwen3.5-9B-heretic').")
        print("       Verfuegbare LLMs mit --list anzeigen.")
        sys.exit(1)

    provider_name, model_name = identifier.split("::", 1)
    instance = create_llm_instance(
        task="tools",
        model=model_name,
        provider_name=provider_name,
        temperature=0.1,
        max_tokens=400,
    )
    if not instance:
        print(f"FEHLER: Kann LLM nicht erstellen: {identifier}")
        print("       Verfuegbare LLMs mit --list anzeigen.")
        sys.exit(1)
    return instance.create_llm()


# ============================================================================
# Review-Loop
# ============================================================================

def _parse_llm_json(content: str) -> Optional[Dict[str, Any]]:
    """Extrahiert JSON-Block aus LLM-Antwort (robust gegen Markdown-Wrapper)."""
    text = (content or "").strip()
    # Thinking-Tokens rauswerfen
    text = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"```(?:json)?\s*|\s*```", "", text, flags=re.IGNORECASE).strip()
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def review_preset(
    llm,
    key: str,
    entry: Dict[str, Any],
    system_prompt: str,
    timeout_s: float = 60.0,
) -> Dict[str, Any]:
    """Laesst das LLM einen einzelnen Preset-Eintrag bewerten."""
    prompt = _REVIEW_USER_TEMPLATE.format(
        key=key,
        prompt=entry.get("prompt", ""),
        synonyms=", ".join(entry.get("synonyms", [])) or "(none)",
    )
    # Plain OpenAI-style message dicts — LLMClient.invoke() versteht sie direkt
    # ueber to_openai_messages() (kein LangChain noetig).
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]
    start = time.time()
    try:
        resp = llm.invoke(messages)
        content = resp.content if hasattr(resp, "content") else str(resp)
    except Exception as e:
        return {
            "rating": None,
            "issues": [f"LLM error: {e}"],
            "suggested_prompt": None,
            "keep": True,
            "_error": str(e),
        }
    dt = time.time() - start

    parsed = _parse_llm_json(content)
    if not parsed:
        return {
            "rating": None,
            "issues": ["Could not parse LLM JSON response"],
            "suggested_prompt": None,
            "keep": True,
            "_raw": content[:300],
            "_elapsed_s": round(dt, 2),
        }

    # Validierung + Normalisierung
    result: Dict[str, Any] = {
        "rating": parsed.get("rating"),
        "issues": parsed.get("issues") or [],
        "suggested_prompt": parsed.get("suggested_prompt"),
        "keep": bool(parsed.get("keep", True)),
        "_elapsed_s": round(dt, 2),
    }
    if isinstance(result["rating"], (int, float)):
        result["rating"] = max(1, min(5, int(result["rating"])))
    return result


def run_review(
    llm,
    source: Path,
    target: Path,
    kind: str,
    limit: Optional[int] = None,
    resume: bool = True,
) -> None:
    """Laeuft das Review fuer alle Presets und schreibt inkrementell ins Target."""
    system = _REVIEW_SYSTEM_POSE if kind == "pose" else _REVIEW_SYSTEM_EXPRESSION

    with open(source, "r", encoding="utf-8") as f:
        src = json.load(f)
    presets = src.get("presets", {})
    if not presets:
        print(f"FEHLER: Keine 'presets' in {source}")
        sys.exit(1)

    # Ziel laden (fuer Resume) oder leer initialisieren
    dst: Dict[str, Any] = {k: v for k, v in src.items() if k != "presets"}
    dst["presets"] = {}
    if resume and target.exists():
        try:
            with open(target, "r", encoding="utf-8") as f:
                existing = json.load(f)
            for k, v in (existing.get("presets", {}) or {}).items():
                if v.get("_review"):
                    dst["presets"][k] = v
        except Exception as e:
            print(f"WARN: Resume-Datei ungueltig ({e}), starte neu")

    total = len(presets)
    done = 0
    skipped_existing = 0
    print(f"Review: {total} Eintraege aus {source.name} via {kind}-Prompt")

    for i, (key, entry) in enumerate(presets.items(), start=1):
        if limit and done >= limit:
            print(f"Limit {limit} erreicht, stoppe.")
            break

        # Schon bewertet? Skip
        if key in dst["presets"] and dst["presets"][key].get("_review"):
            skipped_existing += 1
            print(f"  [{i}/{total}] {key}: SKIP (bereits reviewt)")
            continue

        review = review_preset(llm, key, entry, system)
        merged = dict(entry)
        merged["_review"] = review
        dst["presets"][key] = merged
        done += 1

        # Kompakte Status-Zeile
        r = review.get("rating")
        keep = "KEEP" if review.get("keep") else "DROP"
        issues = review.get("issues") or []
        issue_txt = f" — {issues[0]}" if issues else ""
        print(f"  [{i}/{total}] {key}: rating={r} {keep}{issue_txt}")

        # Inkrementell speichern (Crash-sicher)
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            json.dump(dst, f, ensure_ascii=False, indent=2)

    print(f"\nFertig: {done} bewertet, {skipped_existing} uebersprungen")
    print(f"Ziel: {target}")


# ============================================================================
# CLI
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="LLM-Review fuer Expression/Pose-Presets",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--list", action="store_true",
                        help="Liste verfuegbarer LLMs ausgeben")
    parser.add_argument("--world", type=str,
                        help="World-Name (Unterordner in worlds/). Bestimmt welcher storage/config "
                             "geladen wird. Default: worlds/demo")
    parser.add_argument("--llm", type=str,
                        help="LLM als 'provider::model' (z.B. Evo-X2::Qwen3.5-9B-heretic)")
    parser.add_argument("--source", type=str,
                        help="Quell-JSON (z.B. shared/templates/expression/expression_presets.json)")
    parser.add_argument("--target", type=str,
                        help="Ziel-JSON (wird ueberschrieben bzw. fortgesetzt)")
    parser.add_argument("--kind", choices=["expression", "pose"],
                        help="Review-Typ (auto-detected aus source falls nicht gesetzt)")
    parser.add_argument("--limit", type=int, default=None,
                        help="Nur N Eintraege bewerten (fuer schnelle Tests)")
    parser.add_argument("--no-resume", action="store_true",
                        help="Ziel komplett neu schreiben, statt existierende Reviews zu behalten")
    args = parser.parse_args()

    if args.list:
        print_available_llms()
        return

    if not args.llm or not args.source or not args.target:
        parser.error("--llm, --source und --target sind erforderlich (oder --list nutzen)")

    source = Path(args.source)
    target = Path(args.target)
    if not source.exists():
        print(f"FEHLER: Quelle existiert nicht: {source}")
        sys.exit(1)

    kind = args.kind or _guess_kind(source)
    llm = resolve_llm(args.llm)
    run_review(llm, source, target, kind,
               limit=args.limit, resume=not args.no_resume)


if __name__ == "__main__":
    main()
