"""Standalone check: character-template defaults only use LIVING tokens.

Run: ./.venv/bin/python scripts/smoke_template_tokens.py
No server, no world DB — reads shared/templates/character/*.json only.

Invariant (user bug 2026-08-13)
------------------------------
``resolve_profile_tokens`` (app/models/character_template.py) resolves a
``{token}`` in a prompt field ONLY when some field of the same template
carries a ``replacement`` block whose ``target`` contains that field's key.
Anything else stays literal — by design. A field ``default`` that names a
token nobody declares therefore ships literal braces into every NEW
character: preview, image prompt and (via the default fallback in
``build_prompt_section``) the chat system prompt.

So: for every template and every field with a string ``default``,
    tokens(default) ⊆ tokens declared with target == field.key.

Hand-derivation (the RED counter-probe below)
---------------------------------------------
Declared replacement tokens per shipped template (read off the JSON):
  human-roleplay : gender, age, height -> target [character_appearance,
                   face_appearance]
  animal-default : species, breed, gender, age, height -> target
                   character_appearance
  human-default  : gender, age, height -> target character_appearance
  base-character : none

The defaults as they stood before the fix (dead = tokens minus declared):
  human-roleplay/character_appearance
    "{gender}, {skin_color} skin, {size} height, {body_type} body frame,
     {hair_length} {hair_color} hair, {eye_color} colored eyes"
    tokens  = body_type, eye_color, gender, hair_color, hair_length, size,
              skin_color
    dead    = body_type, eye_color, hair_color, hair_length, size, skin_color
  human-roleplay/face_appearance
    "{gender}, {skin_color} skin, {hair_length} {hair_color} hair,
     {eye_color} colored eyes"
    dead    = eye_color, hair_color, hair_length, skin_color
  animal-default/character_appearance
    "{animal_size} {species}, {breed}, {fur_type}, {primary_color}
     {pattern}, {eye_color}"
    dead    = animal_size, eye_color, fur_type, pattern, primary_color

Those six/four/five tokens are exactly what the body-slot migration bc98b6a
(2026-07-08) orphaned when it deleted the fields and their replacement
blocks but left the defaults untouched. This check would have caught it on
migration day; it runs the historical strings as a counter-probe so a green
run cannot be green by accident.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, ".")

TEMPLATE_DIR = Path("shared/templates/character")

# The pre-fix defaults, verbatim from bc98b6a..HEAD~ — red counter-probe.
HISTORICAL = {
    ("human-roleplay", "character_appearance"): (
        "{gender}, {skin_color} skin, {size} height, {body_type} body frame, "
        "{hair_length} {hair_color} hair, {eye_color} colored eyes",
        ["body_type", "eye_color", "hair_color", "hair_length", "size",
         "skin_color"],
    ),
    ("human-roleplay", "face_appearance"): (
        "{gender}, {skin_color} skin, {hair_length} {hair_color} hair, "
        "{eye_color} colored eyes",
        ["eye_color", "hair_color", "hair_length", "skin_color"],
    ),
    ("animal-default", "character_appearance"): (
        "{animal_size} {species}, {breed}, {fur_type}, {primary_color} "
        "{pattern}, {eye_color}",
        ["animal_size", "eye_color", "fur_type", "pattern", "primary_color"],
    ),
}


def check(name: str, cond: bool):
    print(("PASS  " if cond else "FAIL  ") + name)
    if not cond:
        sys.exit(1)


def declared_tokens(template: dict) -> dict:
    """{target field key: {token, ...}} from every replacement block."""
    out: dict = {}
    for section in template.get("sections", []):
        for field in section.get("fields", []):
            repl = field.get("replacement")
            if not repl:
                continue
            targets = repl.get("target", "")
            if isinstance(targets, str):
                targets = [targets]
            token = repl.get("token", field["key"])
            for target in targets:
                out.setdefault(target, set()).add(token)
    return out


def dead_tokens(text: str, declared: set) -> list:
    """Tokens in ``text`` that no replacement block declares for it."""
    return sorted(set(re.findall(r"\{(\w+)\}", text or "")) - set(declared))


def load_effective(name: str) -> dict:
    """Template as the resolver sees it: base merge + package fragments."""
    from app.models.character_template import get_template
    tmpl = get_template(name)
    if tmpl is None:
        raise SystemExit(f"template '{name}' failed to load")
    return tmpl


def main() -> None:
    import tempfile
    from app.core import paths
    paths.init(tempfile.mkdtemp(prefix="anima_template_tokens_check_"))
    # Species packages contribute template fragments (and could contribute
    # replacement blocks), so the check runs against the merged template the
    # resolver actually uses.
    try:
        from app.plugins.loader import discover_packages
        discover_packages()
    except Exception as e:  # a package-less checkout is still checkable
        print(f"NOTE  package discovery skipped: {e}")

    names = sorted(p.stem for p in TEMPLATE_DIR.glob("*.json"))
    check(f"templates found ({len(names)}): {', '.join(names)}", bool(names))

    findings = []
    for name in names:
        tmpl = load_effective(name)
        declared = declared_tokens(tmpl)
        for section in tmpl.get("sections", []):
            for field in section.get("fields", []):
                default = field.get("default")
                if not isinstance(default, str):
                    continue
                dead = dead_tokens(default, declared.get(field["key"], set()))
                if dead:
                    findings.append(f"{name}/{field['key']}: {', '.join(dead)}")
    check("no default references an undeclared token"
          + ("" if not findings else " -> " + " | ".join(findings)),
          not findings)

    # Red counter-probe: the historical defaults must still be rejected, with
    # exactly the token sets derived by hand in the docstring.
    for (name, key), (text, expected) in sorted(HISTORICAL.items()):
        declared = declared_tokens(load_effective(name)).get(key, set())
        found = dead_tokens(text, declared)
        check(f"counter-probe {name}/{key} rejects {expected}",
              found == expected)

    # The boot migration repairs the texts already saved from those defaults.
    # Hand-derived per segment (drop a segment whose remainder is only glue,
    # keep a segment that has content of its own):
    #   "{gender}" keeps, "{skin_color} skin" -> "skin" (glue) drops,
    #   "{size} height" / "{body_type} body frame" /
    #   "{hair_length} {hair_color} hair" / "{eye_color} colored eyes" drop.
    from app.core.appearance_token_migration import strip_dead_tokens
    cases = [
        (HISTORICAL[("human-roleplay", "character_appearance")][0],
         "{gender}"),
        (HISTORICAL[("human-roleplay", "face_appearance")][0], "{gender}"),
        (HISTORICAL[("animal-default", "character_appearance")][0],
         "{species}, {breed}"),
        # content sharing a segment with a dead token survives
        ("{gender}, {hair_length} {hair_color} hair in a tight braid",
         "{gender}, hair in a tight braid"),
        # nothing dead in there -> untouched, decimal comma intact
        ("a tall {gender} elf, 1,80 m, scarred cheek",
         "a tall {gender} elf, 1,80 m, scarred cheek"),
    ]
    for text, expected in cases:
        got, _ = strip_dead_tokens(text)
        check(f"migration cleans {text[:38]!r}... -> {expected!r}",
              got == expected)
        again, dropped = strip_dead_tokens(got)
        check("migration is idempotent", again == got and not dropped)

    print("OK")


if __name__ == "__main__":
    main()
