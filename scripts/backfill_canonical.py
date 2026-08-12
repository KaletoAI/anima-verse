"""One-off migration: rebuild the canonical fields in image.json for old images.

Value source: parsing the `prompt` field.
- Old Z-Image format: "expression and mood: X", "activity: X", "setting: X"
- New labeled sections: "Characters:\n- Name: ...", "Mood: X", "Setting: X", "Style: X"

Skip condition: `canonical` is already present and non-empty.
Idempotent: running it twice does no harm.

Usage:
    python scripts/backfill_canonical.py --world worlds/demo [--dry]
    python scripts/backfill_canonical.py --world worlds/demo --reclean
    python scripts/backfill_canonical.py --world worlds/demo --reparse
"""
import json
import re
import sys
from pathlib import Path

# The world directory comes from the CLI (--world), never from a hardcoded path.
WORLD = Path("worlds/demo")
CHARS_DIR = WORLD / "characters"
INSTAGRAM_DIR = WORLD / "instagram"


def _set_world(world_dir: Path) -> None:
    """Point the module at one world directory (worlds/<name>)."""
    global WORLD, CHARS_DIR, INSTAGRAM_DIR
    WORLD = world_dir
    CHARS_DIR = WORLD / "characters"
    INSTAGRAM_DIR = WORLD / "instagram"


def _load_world_locations() -> dict:
    """Return {location_id: location_name} from world.json."""
    wf = WORLD / "world.json"
    if not wf.exists():
        return {}
    try:
        data = json.loads(wf.read_text(encoding="utf-8"))
    except Exception:
        return {}
    locs = {}
    for loc in data.get("locations", []) or []:
        loc_id = loc.get("id", "")
        if loc_id:
            locs[loc_id] = loc.get("name", "")
    return locs


def _strip_label(text: str, label: str) -> str:
    """Strip a leading 'label: ' prefix when present."""
    pat = re.compile(r"^\s*" + re.escape(label) + r"\s*:?\s*", re.IGNORECASE)
    return pat.sub("", text).strip()


_OUTFIT_JUNK_PATTERNS = [
    r"empty string",
    r"nichts\s+(spezifisch|beschrieben|klar|definiert|festgelegt|angegeben)",
    r"keine?\s+(spezifische|beschreibung|angabe|kleidung|outfit)",
    r"nicht\s+(spezifiziert|beschrieben|festgelegt|definiert|angegeben)",
    r"^\s*(nichts|keine?|nothing|none|n/?a|unspecified|undefined)\s*$",
    r"no\s+(specific|outfit|clothing|description|details)",
    r"^\s*naked\s*$",  # "naked" alone carries nothing — an empty outfit means unclothed
]


def _clean_outfit(text: str) -> str:
    """Clean an outfit text: drop empty/unspecific values and over-long texts.

    An empty outfit already means unclothed in this system — no need to spell it out.
    """
    if not text:
        return ""
    t = text.strip().rstrip(",").strip()
    if not t:
        return ""
    # An outfit over 80 characters is usually LLM scene junk, not the real outfit
    if len(t) > 80:
        return ""
    # Known junk phrases
    for pat in _OUTFIT_JUNK_PATTERNS:
        if re.search(pat, t, flags=re.IGNORECASE):
            return ""
    return t


def parse_z_image_prompt(prompt: str, char_name_hint: str = "") -> dict:
    """Parse old Z-Image prompts with labels.

    Example:
        "Man1, 38 year old male, ... is wearing X, standing in office,
         expression and mood: Man1 looks happy, activity: Man1 is cooking,
         setting: Kitchen, A kitchen with ..."

    Fills as many fields as it can; anything not found stays empty.
    """
    out = {
        "persons": [],
        "person_prompts": {},
        "outfits": {},
        "pose": "",
        "expression": "",
        "scene": "",
        "mood": "",
        "activity": "",
        "location": "",
        "personality_hint": "",
        "profile_image_hint": "",
        "style": "",
        "negative": "",
    }

    if not prompt or not prompt.strip():
        return out

    text = prompt.strip()

    # Style: the first token when it is a known style adjective
    first = text.split(",", 1)[0].strip()
    if first.lower() in ("photorealistic", "anime", "cinematic", "illustration",
                         "3d render", "cyberpunk", "realistic"):
        out["style"] = first
        text = text[len(first):].lstrip(", ")

    # Check the labeled-section format first (Qwen/Flux)
    if re.search(r"^\s*Characters:\s*$", text, flags=re.MULTILINE):
        return _parse_labeled_sections(text, out)

    # Z-Image style: look for labels
    label_extractors = [
        ("mood", r"(?:expression and mood|mood)\s*:\s*([^,]+(?:,[^,]+)*?)(?=,\s*activity\s*:|,\s*setting\s*:|,\s*body language|$)"),
        ("activity", r"activity\s*:\s*([^,]+(?:,[^,]+)*?)(?=,\s*setting\s*:|,\s*mood\s*:|,\s*body language|$)"),
        ("location", r"setting\s*:\s*([^,]+(?:,[^,]+)*?)(?=,\s*body language|$)"),
        ("personality_hint", r"body language based on\s*:\s*(.+?)$"),
    ]
    for key, pat in label_extractors:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            val = m.group(1).strip().rstrip(",").strip()
            # Mood/activity are often "X looks Y" or "X is Y" — take them whole
            out[key] = val

    # Extract the persons heuristically from the beginning
    # Pattern: "Name1, ... is wearing ..., Name2, ... is wearing ..."
    persons_part = text
    for label in ("expression and mood", "mood", "activity", "setting", "body language based on"):
        pat = re.compile(r",\s*" + re.escape(label) + r"\s*:.*$", flags=re.IGNORECASE | re.DOTALL)
        persons_part = pat.sub("", persons_part)

    # Heuristic: find the first "Name is wearing X"
    persons_part = persons_part.strip().rstrip(",").strip()
    if persons_part:
        # Outfit: ONLY the first token after "is wearing" (never comma-greedy)
        wearing_match = re.search(r"\b(\w+)\s+is wearing\s+([^,]+)",
                                   persons_part, flags=re.IGNORECASE)
        if wearing_match:
            person_name = wearing_match.group(1)
            outfit_first_token = wearing_match.group(2).strip()
            # Person description = everything before "{name} is wearing"
            split_pos = persons_part.lower().find(f"{person_name.lower()} is wearing")
            if split_pos > 0:
                person_desc = persons_part[:split_pos].rstrip(", ").strip()
                if person_desc:
                    # Replace placeholders like "Man1"/"Woman1" with the real name when possible
                    if char_name_hint and re.match(r"^(Man|Woman|Person)\d+", person_desc):
                        person_desc = re.sub(r"^(Man|Woman|Person)\d+",
                                             char_name_hint, person_desc)
                    display_name = char_name_hint or person_name
                    out["person_prompts"]["1"] = person_desc
                    out["persons"].append({
                        "label": display_name, "name": display_name,
                        "appearance": person_desc, "gender": "",
                        "is_agent": False,
                    })
                cleaned_outfit = _clean_outfit(outfit_first_token)
                if cleaned_outfit:
                    out["outfits"]["1"] = f"{display_name} is wearing {cleaned_outfit}"
                # Scene text: everything between the end of the outfit and the next label
                # (e.g. "on stage, sitting, holding a drink, confident posture")
                wear_end = wearing_match.end()
                scene_text = persons_part[wear_end:].strip().lstrip(",").strip()
                if scene_text and len(scene_text) > 5:
                    # Filter out junk phrases (same set as the outfit filter)
                    if not any(re.search(p, scene_text, flags=re.IGNORECASE)
                               for p in _OUTFIT_JUNK_PATTERNS[:5]):  # only the "nothing/empty" patterns
                        out["scene"] = scene_text
        else:
            # No "is wearing" found — treat everything as one person without an outfit
            person_desc = persons_part
            if char_name_hint and re.match(r"^(Man|Woman|Person)\d+", person_desc):
                person_desc = re.sub(r"^(Man|Woman|Person)\d+",
                                     char_name_hint, person_desc)
            display_name = char_name_hint or ""
            out["person_prompts"]["1"] = person_desc
            out["persons"].append({
                "label": display_name, "name": display_name,
                "appearance": person_desc, "gender": "",
                "is_agent": False,
            })

    # Mood/activity: "Man1 looks X" / "Man1 is X" → substitute the real name
    if char_name_hint:
        for key in ("mood", "activity"):
            if out[key]:
                out[key] = re.sub(r"\b(Man|Woman|Person)\d+\b",
                                  char_name_hint, out[key])

    return out


def _parse_labeled_sections(text: str, out: dict) -> dict:
    """Parse the labeled-sections format (Qwen/Flux)."""
    sections = re.split(r"\n\n+", text)
    for sec in sections:
        sec = sec.strip()
        if sec.startswith("Characters:"):
            lines = [l.strip() for l in sec.split("\n")[1:] if l.strip().startswith("-")]
            for i, line in enumerate(lines, 1):
                line = line.lstrip("- ").rstrip(".")
                # Format: "Name: appearance, wearing outfit"
                m = re.match(r"^([^:,]+):\s*(.+?)(?:,\s*wearing\s+(.+))?$", line)
                if m:
                    name = m.group(1).strip()
                    appearance = m.group(2).strip()
                    outfit = (m.group(3) or "").strip()
                    out["person_prompts"][str(i)] = f"{name}: {appearance}" if name else appearance
                    out["persons"].append({
                        "label": name, "name": name, "appearance": appearance,
                        "gender": "", "is_agent": False,
                    })
                    if outfit:
                        out["outfits"][str(i)] = f"{name} is wearing {outfit}"
        elif sec.startswith("Action:"):
            out["scene"] = _strip_label(sec, "Action").rstrip(".")
        elif sec.startswith("Mood:"):
            out["mood"] = _strip_label(sec, "Mood").rstrip(".")
        elif sec.startswith("Setting:"):
            out["location"] = _strip_label(sec, "Setting").rstrip(".")
        elif sec.startswith("Style:"):
            out["style"] = _strip_label(sec, "Style").rstrip(".")
        # The first line (without a label) is the summary — ignored for canonical
    return out


def is_canonical_present(meta: dict) -> bool:
    c = meta.get("canonical")
    if not c or not isinstance(c, dict):
        return False
    # Counts as "present" when there is at least one person OR non-empty fields
    return bool(c.get("persons") or c.get("person_prompts") or c.get("location") or c.get("mood"))


def reclean_outfits(meta: dict) -> bool:
    """Apply the current outfit filter to an existing canonical. True when changed."""
    canonical = meta.get("canonical")
    if not canonical or not isinstance(canonical, dict):
        return False
    outfits = canonical.get("outfits") or {}
    if not outfits:
        return False
    new_outfits = {}
    changed = False
    for k, v in outfits.items():
        # v hat Format "Name is wearing X" — extract X
        if " is wearing " in v:
            prefix, raw = v.split(" is wearing ", 1)
            cleaned = _clean_outfit(raw)
            if cleaned:
                new_outfits[k] = f"{prefix} is wearing {cleaned}"
            else:
                changed = True  # the outfit is dropped (it was junk)
        else:
            cleaned = _clean_outfit(v)
            if cleaned:
                new_outfits[k] = cleaned
            else:
                changed = True
    if new_outfits != outfits:
        canonical["outfits"] = new_outfits
        return True
    return changed


def main(dry_run: bool = False, mode: str = "fill") -> None:
    """mode: 'fill' = only fill empty canonicals,
            'reclean' = re-filter existing outfits,
            'reparse' = re-parse canonical from the prompt (overwrites)."""
    location_map = _load_world_locations()
    print(f"World locations loaded: {len(location_map)}")
    print(f"Mode: {mode}")

    total = 0
    skipped = 0
    updated = 0
    failed = 0

    if not CHARS_DIR.exists():
        print(f"MISSING: {CHARS_DIR}")
        return

    for char_dir in sorted(CHARS_DIR.iterdir()):
        if not char_dir.is_dir():
            continue
        images_dir = char_dir / "images"
        if not images_dir.exists():
            continue

        char_total = 0
        char_updated = 0
        char_skipped = 0

        for json_file in sorted(images_dir.glob("*.json")):
            char_total += 1
            total += 1
            try:
                meta = json.loads(json_file.read_text(encoding="utf-8"))
            except Exception as e:
                print(f"  FEHLER beim Lesen {json_file.name}: {e}")
                failed += 1
                continue

            if mode == "reclean":
                # Only re-filter outfit junk in existing canonicals
                if reclean_outfits(meta):
                    if not dry_run:
                        json_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
                    updated += 1
                    char_updated += 1
                else:
                    skipped += 1
                    char_skipped += 1
                continue

            # Fill / reparse: reparse only overwrites when canonical_source ==
            # "parsed_from_prompt" (or is missing) — hand-maintained canonicals stay untouched
            if mode == "fill" and is_canonical_present(meta):
                skipped += 1
                char_skipped += 1
                continue
            if mode == "reparse":
                src = meta.get("canonical_source", "")
                if src and src != "parsed_from_prompt":
                    skipped += 1
                    char_skipped += 1
                    continue

            prompt = meta.get("prompt", "")
            if not prompt:
                canonical = {"persons": [], "person_prompts": {}, "outfits": {}}
            else:
                canonical = parse_z_image_prompt(prompt, char_name_hint=char_dir.name)
                if meta.get("negative_prompt"):
                    canonical["negative"] = meta["negative_prompt"]
                loc_id = meta.get("location", "")
                if loc_id:
                    resolved = location_map.get(loc_id, "")
                    if resolved:
                        canonical["location"] = resolved
                    elif not canonical.get("location"):
                        canonical["location"] = loc_id

            meta["canonical"] = canonical
            meta["canonical_source"] = "parsed_from_prompt"

            if not dry_run:
                json_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
            updated += 1
            char_updated += 1

        if char_total:
            print(f"  {char_dir.name}: total={char_total} updated={char_updated} skipped={char_skipped}")

    # --- Instagram directory (flat, no character subfolder) ---
    if INSTAGRAM_DIR.exists():
        insta_total = 0
        insta_updated = 0
        insta_skipped = 0
        for json_file in sorted(INSTAGRAM_DIR.glob("*.json")):
            try:
                meta = json.loads(json_file.read_text(encoding="utf-8"))
            except Exception as e:
                print(f"  Instagram FEHLER {json_file.name}: {e}")
                failed += 1
                continue
            # Skip list-based files (e.g. feed.json) — only image meta dicts are processed
            if not isinstance(meta, dict) or "image_filename" not in meta:
                continue
            insta_total += 1
            total += 1

            # Derive the character name from the file name: "Alia_1772193970_x_1.json" -> "Alia"
            char_hint = json_file.stem.split("_", 1)[0]

            if mode == "reclean":
                if reclean_outfits(meta):
                    if not dry_run:
                        json_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
                    updated += 1
                    insta_updated += 1
                else:
                    skipped += 1
                    insta_skipped += 1
                continue

            if mode == "fill" and is_canonical_present(meta):
                skipped += 1
                insta_skipped += 1
                continue
            if mode == "reparse":
                src = meta.get("canonical_source", "")
                if src and src != "parsed_from_prompt":
                    skipped += 1
                    insta_skipped += 1
                    continue

            prompt = meta.get("prompt", "")
            if not prompt:
                canonical = {"persons": [], "person_prompts": {}, "outfits": {}}
            else:
                canonical = parse_z_image_prompt(prompt, char_name_hint=char_hint)
                if meta.get("negative_prompt"):
                    canonical["negative"] = meta["negative_prompt"]
                # Instagram meta often has no location_id — only what the prompt says

            meta["canonical"] = canonical
            meta["canonical_source"] = "parsed_from_prompt"
            if not dry_run:
                json_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
            updated += 1
            insta_updated += 1

        if insta_total:
            print(f"  [Instagram]: total={insta_total} updated={insta_updated} skipped={insta_skipped}")

    print()
    print(f"TOTAL: {total} JSONs, {updated} updated, {skipped} already ok, {failed} errors")
    if dry_run:
        print("(DRY RUN — no files changed)")


if __name__ == "__main__":
    world_arg = ""
    for i, a in enumerate(sys.argv[1:], start=1):
        if a.startswith("--world="):
            world_arg = a.split("=", 1)[1]
        elif a == "--world" and i + 1 < len(sys.argv):
            world_arg = sys.argv[i + 1]
    if not world_arg:
        print("Usage: python scripts/backfill_canonical.py --world worlds/demo "
              "[--dry] [--reparse|--reclean]")
        sys.exit(2)
    _set_world(Path(world_arg))

    dry = "--dry" in sys.argv
    if "--reparse" in sys.argv:
        mode = "reparse"
    elif "--reclean" in sys.argv:
        mode = "reclean"
    else:
        mode = "fill"
    main(dry_run=dry, mode=mode)
