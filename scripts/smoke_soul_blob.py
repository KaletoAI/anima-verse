#!/usr/bin/env python3
"""Smoke run for the soul-value single source of truth.

Usage:  ./.venv/bin/python scripts/smoke_soul_blob.py

Soul fields (`source_file` in the character template) live in
``characters/<X>/soul/*.md``. They used to exist TWICE: the MD file and a copy
in ``profile_json``. The two readers disagreed about which one wins — the
profile loader preferred the blob, the prompt builder preferred the file and
fell back to the blob — so a character whose soul file had been cleared kept
speaking from a months-old blob value that no UI could show.

This check builds its OWN throwaway world (a temp dir, a fresh world.db) and
walks the three cases the migration has to tell apart. The expectations are
derived BY HAND from the rule, not from a recorded run:

  Alpha  — authored field (personality), file is a SCAFFOLD (headings, no
           body — what a freshly created character has), blob "Warm und
           direkt.". The prose has no other home -> it is MOVED INTO the file,
           under the first empty heading, because that is where the readers
           look. A scaffold counts as EMPTY, exactly as the prompt sees it.
           expect: rescued=1, the text reads back, blob key gone
  Beta   — generated field (lessons), file EMPTY, blob "Alte Lektion."
           An empty file is what a reset leaves behind; Retrospect rewrites
           the file from lived experience -> the value is DROPPED (backed up).
           expect: dropped=1, file still empty, profile reads "" (no ghost)
  Gamma  — authored field (soul), file has a filled "## Kern" section, blob
           "Alter Text". The file speaks -> the blob copy is redundant and is
           dropped silently.
           expect: neither rescued nor dropped, file untouched, profile reads
           the FILE text ("Alter Text" must never surface again). The reader
           normalises heading + body to "## Kern\nNeuer Text" — one blank
           line less than on disk, which is why the expectation says so.

Plus the two invariants that made the ghost possible in the first place:
  * a second migration run reports nothing (idempotent by construction)
  * build_prompt_section renders NO line for a field whose file is empty,
    even while a blob value sits next to it (no fallback)
  * save_character_profile does not write a handed-in soul value into the
    blob — it lands in the file instead
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

FAILURES = []


def check(label, actual, expected):
    ok = actual == expected
    print(f"  {'OK  ' if ok else 'FAIL'} {label}: {actual!r}"
          + ("" if ok else f"  (expected {expected!r})"))
    if not ok:
        FAILURES.append(label)


def main():
    tmp = Path(tempfile.mkdtemp(prefix="soul_blob_smoke_"))
    try:
        from app.core import paths
        paths.init(str(tmp))          # absolute path — never touch a real world
        from app.core import db
        db.init_schema()

        from app.core.db import get_connection, transaction
        from app.core.soul_blob_migration import migrate_soul_blobs_once
        from app.models.character import (get_character_dir,
                                          get_character_profile,
                                          save_character_profile)

        template = "human-roleplay"
        fixtures = [
            # name,   profile key,             relative file, file body, blob value
            ("Alpha", "character_personality", "soul/personality.md", "",
             "Warm und direkt."),
            ("Beta",  "character_lessons",     "soul/lessons.md",     "",
             "Alte Lektion."),
            ("Gamma", "character_soul",        "soul/soul.md",
             "## Kern\n\nNeuer Text", "Alter Text"),
        ]

        for name, key, rel, body, blob in fixtures:
            char_dir = get_character_dir(name, create=True)
            md = char_dir / rel
            md.parent.mkdir(parents=True, exist_ok=True)
            scaffold = (f"# {Path(rel).stem.title()}\n\n"
                        "## Erster Abschnitt\n\n## Zweiter Abschnitt\n")
            md.write_text(scaffold if not body
                          else f"# {Path(rel).stem.title()}\n\n{body}\n",
                          encoding="utf-8")
            profile = {"character_name": name, "template": template, key: blob}
            with transaction() as conn:
                conn.execute(
                    "INSERT INTO characters (name, template, profile_json, "
                    "config_json, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                    (name, template, json.dumps(profile, ensure_ascii=False),
                     "{}", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"))

        print("[1] migration: rescue vs. drop vs. redundant")
        result = migrate_soul_blobs_once()
        check("characters touched", result.get("characters"), 3)
        check("rescued (authored prose, empty file)", result.get("rescued"), 1)
        check("dropped (generated field, empty file)", result.get("dropped"), 1)

        def blob_of(name):
            row = get_connection().execute(
                "SELECT profile_json FROM characters WHERE name=?", (name,)).fetchone()
            return json.loads(row[0])

        check("Alpha blob has no personality key",
              "character_personality" in blob_of("Alpha"), False)
        check("Beta blob has no lessons key",
              "character_lessons" in blob_of("Beta"), False)
        check("Gamma blob has no soul key",
              "character_soul" in blob_of("Gamma"), False)

        print("[2] the files after the sweep")
        alpha_md = (get_character_dir("Alpha") / "soul/personality.md").read_text()
        check("Alpha file carries the rescued prose",
              "Warm und direkt." in alpha_md, True)
        beta_md = (get_character_dir("Beta") / "soul/lessons.md").read_text()
        check("Beta file stays empty", "Alte Lektion." in beta_md, False)
        gamma_md = (get_character_dir("Gamma") / "soul/soul.md").read_text()
        check("Gamma file untouched", gamma_md.strip().endswith("Neuer Text"), True)
        check("Alpha keeps its scaffold headings",
              "## Erster Abschnitt" in alpha_md, True)

        backup = Path(result.get("backup", ""))
        check("dropped text is backed up",
              backup.is_file() and "Alte Lektion." in backup.read_text(), True)

        print("[3] what the consumers read now (file wins, no ghost)")
        check("Alpha personality", get_character_profile("Alpha")
              .get("character_personality"),
              "## Erster Abschnitt\nWarm und direkt.")
        check("Beta lessons (ghost gone)", get_character_profile("Beta")
              .get("character_lessons"), "")
        check("Gamma soul comes from the file", get_character_profile("Gamma")
              .get("character_soul"), "## Kern\nNeuer Text")

        print("[4] prompt: no fallback to the blob")
        from app.models.character_template import get_template, build_prompt_section
        tmpl = get_template(template)
        # A blob value handed in directly must not reach the prompt either.
        data = dict(get_character_profile("Beta"))
        data["character_lessons"] = "Alte Lektion."
        lines = build_prompt_section(tmpl, data, character_name="Beta")
        check("no 'lessons' line for an empty file",
              any("gelernt" in ln.lower() or "lessons" in ln.lower() for ln in lines),
              False)

        print("[5] migration is idempotent")
        check("second run reports nothing", migrate_soul_blobs_once(), {})

        print("[6] save_character_profile keeps soul values out of the blob")
        prof = get_character_profile("Gamma")
        prof["character_soul"] = "Von Hand gesetzt"
        save_character_profile("Gamma", prof)
        check("blob still has no soul key",
              "character_soul" in blob_of("Gamma"), False)
        check("value went nowhere near the blob — file still wins",
              get_character_profile("Gamma").get("character_soul"),
              "## Kern\nNeuer Text")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} check(s): {', '.join(FAILURES)}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
