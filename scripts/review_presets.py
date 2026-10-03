#!/usr/bin/env python3
"""LLM-based review of expression/pose presets.

Lets an LLM rate every preset (keys + prompt + synonyms) of a file and writes
an enriched target JSON with a review block per entry.

Needs a world (it reads that world's config): pass --world <name>
(-> worlds/<name>) or set STORAGE_DIR. There is no default world. The LLM
providers and the routing are INSTANCE config: set INSTANCE_DIR to the
instance directory (start.sh uses ./instance). There is no default instance.

Usage:
  python scripts/review_presets.py --world demo --list
  python scripts/review_presets.py --llm local-llm::qwen3-8b \
      --source shared/templates/expression/expression_presets.json \
      --target /tmp/expression_review.json

  python scripts/review_presets.py --llm local-llm::qwen3-8b \
      --source shared/templates/pose/pose_presets_generated.json \
      --target /tmp/pose_generated_review.json \
      --limit 20

Output format (target JSON, same structure as the source + "_review" per preset):
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

# Project root on sys.path so app.* can be imported
_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))

# CLI pre-parsing for --world only (it has to happen before paths.init()).
# The full argument parser follows later in main().
import os as _os  # noqa: E402
_world_override = None
for i, _arg in enumerate(sys.argv):
    if _arg == "--world" and i + 1 < len(sys.argv):
        _world_override = sys.argv[i + 1]
        break
    if _arg.startswith("--world="):
        _world_override = _arg.split("=", 1)[1]
        break

# Bootstrap exactly like app/server.py:
#   1. paths.init()  — set the storage dir (via --world or STORAGE_DIR; there
#      is NO default world any more, so without either this exits)
#   2. paths.init_instance() — the instance dir (INSTANCE_DIR, no default)
#   3. config.load() — load both config layers, fill os.environ
#   4. initialise provider_manager — reads the providers from the env
#   5. use llm_router — LLMInstance for explicit model overrides
from app.core import paths as _paths_mod  # noqa: E402
try:
    if _world_override:
        _paths_mod.init(Path("worlds") / _world_override)
    else:
        _paths_mod.init()
except _paths_mod.StorageNotInitialised as _e:
    print(f"ERROR: {_e}\n"
          "       This tool reads a real world: pass --world <name> "
          "(-> worlds/<name>) or set STORAGE_DIR.", file=sys.stderr)
    sys.exit(2)

try:
    _paths_mod.init_instance()
except _paths_mod.InstanceNotInitialised as _e:
    print(f"ERROR: {_e}\n"
          "       This tool calls the configured LLMs: set INSTANCE_DIR to the "
          "instance directory (e.g. ./instance).", file=sys.stderr)
    sys.exit(2)

from app.core.config import load as _load_config  # noqa: E402
_load_config(_paths_mod.get_config_path(), _paths_mod.get_instance_config_path())

from app.core.provider_manager import (  # noqa: E402
    get_provider_manager, initialize_provider_manager,
)
from app.core.llm_router import create_llm_instance  # noqa: E402

# Initialise the providers (as in the server lifespan); llm_router resolves lazily.
initialize_provider_manager()


# ============================================================================
# LLM prompts for the review
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
    """Guesses expression or pose from the path."""
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
    """Lists every available provider::model combination."""
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
    """Prints the available LLMs grouped by provider."""
    llms = list_available_llms()
    if not llms:
        print("No LLMs found. Check the providers in the instance config.")
        return
    current = ""
    for entry in sorted(llms, key=lambda x: (x["provider"], x["model"])):
        if entry["provider"] != current:
            current = entry["provider"]
            print(f"\n{current} ({entry['type']}):")
        print(f"  {entry['id']}")
    print()


def resolve_llm(identifier: str):
    """Resolves 'provider::model' into an LLMClient (app.core.llm_client)."""
    if "::" not in identifier:
        print(f"ERROR: give the LLM as provider::model (e.g. 'local-llm::qwen3-8b').")
        print("       Show the available LLMs with --list.")
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
        print(f"ERROR: cannot create LLM: {identifier}")
        print("       Show the available LLMs with --list.")
        sys.exit(1)
    return instance.create_llm()


# ============================================================================
# Review-Loop
# ============================================================================

def _parse_llm_json(content: str) -> Optional[Dict[str, Any]]:
    """Extracts the JSON block from an LLM answer (robust against Markdown wrappers)."""
    text = (content or "").strip()
    # Drop thinking tokens
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
    """Lets the LLM rate a single preset entry."""
    prompt = _REVIEW_USER_TEMPLATE.format(
        key=key,
        prompt=entry.get("prompt", ""),
        synonyms=", ".join(entry.get("synonyms", [])) or "(none)",
    )
    # Plain OpenAI-style message dicts — LLMClient.invoke() understands them
    # directly via to_openai_messages() (no LangChain needed).
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

    # Validation + normalisation
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
    """Runs the review over all presets and writes the target incrementally."""
    system = _REVIEW_SYSTEM_POSE if kind == "pose" else _REVIEW_SYSTEM_EXPRESSION

    with open(source, "r", encoding="utf-8") as f:
        src = json.load(f)
    presets = src.get("presets", {})
    if not presets:
        print(f"ERROR: no 'presets' in {source}")
        sys.exit(1)

    # Load the target (for resume) or start empty
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
            print(f"WARN: resume file invalid ({e}), starting over")

    total = len(presets)
    done = 0
    skipped_existing = 0
    print(f"Review: {total} entries from {source.name} via the {kind} prompt")

    for i, (key, entry) in enumerate(presets.items(), start=1):
        if limit and done >= limit:
            print(f"Limit {limit} reached, stopping.")
            break

        # Already rated? Skip
        if key in dst["presets"] and dst["presets"][key].get("_review"):
            skipped_existing += 1
            print(f"  [{i}/{total}] {key}: SKIP (already reviewed)")
            continue

        review = review_preset(llm, key, entry, system)
        merged = dict(entry)
        merged["_review"] = review
        dst["presets"][key] = merged
        done += 1

        # Compact status line
        r = review.get("rating")
        keep = "KEEP" if review.get("keep") else "DROP"
        issues = review.get("issues") or []
        issue_txt = f" — {issues[0]}" if issues else ""
        print(f"  [{i}/{total}] {key}: rating={r} {keep}{issue_txt}")

        # Save incrementally (crash-safe)
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            json.dump(dst, f, ensure_ascii=False, indent=2)

    print(f"\nDone: {done} rated, {skipped_existing} skipped")
    print(f"Target: {target}")


# ============================================================================
# CLI
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="LLM review of expression/pose presets",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--list", action="store_true",
                        help="Print the available LLMs")
    parser.add_argument("--world", type=str,
                        help="World name (subdirectory of worlds/). Selects which storage/config "
                             "is loaded. Required when STORAGE_DIR is not set — "
                             "there is no default world.")
    parser.add_argument("--llm", type=str,
                        help="LLM as 'provider::model' (e.g. local-llm::qwen3-8b)")
    parser.add_argument("--source", type=str,
                        help="Source JSON (e.g. shared/templates/expression/expression_presets.json)")
    parser.add_argument("--target", type=str,
                        help="Target JSON (overwritten or resumed)")
    parser.add_argument("--kind", choices=["expression", "pose"],
                        help="Review kind (auto-detected from the source if not set)")
    parser.add_argument("--limit", type=int, default=None,
                        help="Rate only N entries (for quick tests)")
    parser.add_argument("--no-resume", action="store_true",
                        help="Rewrite the target from scratch instead of keeping existing reviews")
    args = parser.parse_args()

    if args.list:
        print_available_llms()
        return

    if not args.llm or not args.source or not args.target:
        parser.error("--llm, --source and --target are required (or use --list)")

    source = Path(args.source)
    target = Path(args.target)
    if not source.exists():
        print(f"ERROR: source does not exist: {source}")
        sys.exit(1)

    kind = args.kind or _guess_kind(source)
    llm = resolve_llm(args.llm)
    run_review(llm, source, target, kind,
               limit=args.limit, resume=not args.no_resume)


if __name__ == "__main__":
    main()
