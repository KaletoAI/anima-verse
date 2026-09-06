"""One-time cleanup: soul values that are still sitting in ``profile_json``.

Fields with a ``source_file`` in the character template (personality, presence,
tasks, soul, beliefs, lessons, goals) live in ``characters/<X>/soul/*.md``. The
MD file is the source of truth — but until this migration landed, every save
wrote the value into the profile blob as well and only stripped it from the
in-memory dict afterwards. That left a second copy in the DB that:

* no UI ever shows (the profile form skips ``source_file`` fields, the soul
  editor reads the file),
* no reset reaches (``_reset_retrospect_soul_files`` clears the FILE),
* but that consumers did read — the profile loader used to prefer the blob
  over the file, and the prompt builder fell back to it when the file was
  empty. A character whose Retrospect was reset therefore kept talking out of
  a soul file that had been cleared months ago, in wording from an older
  world.

This module removes that second copy. Nothing is thrown away silently:

* MD file has content -> the blob value is redundant, dropped.
* MD file empty, field is authored (personality/presence/tasks/soul) -> the
  blob value is written INTO the file first. That prose has no other home.
* MD file empty, field is Retrospect output (beliefs/lessons/goals) -> the
  value is dropped, because an empty file is exactly what a reset leaves
  behind and Retrospect rewrites those files from lived experience anyway.
  The dropped text is written to ``migration_backup/`` first, so a wrong call
  here stays recoverable.

Idempotent by construction: once the keys are gone from the blob there is
nothing left to move, so it runs on every boot without a marker.
"""
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

#: Section ids whose files Retrospect writes and a reset clears. Their content
#: is generated from lived experience — an empty file means "reset or never
#: run", never "the text got lost", so a leftover blob value is stale.
_GENERATED_SECTIONS = frozenset({"beliefs", "lessons", "goals"})


def _section_id(source_file: str) -> str:
    """``soul/lessons.md`` -> ``lessons`` (the id the soul editor uses)."""
    return Path(source_file).stem


def _replace_body(md_text: str, body: str, title: str) -> str:
    """Return the MD file with its body replaced, keeping the ``# Title``.

    Used to move a rescued blob value into an empty file. Unlike
    ``_inject_into_first_empty_section`` this also accepts structured content
    (a value that carries its own ``## Sections``) — which is exactly what the
    older blob values look like.
    """
    header = ""
    for line in (md_text or "").splitlines():
        if line.strip().startswith("# ") and not line.strip().startswith("## "):
            header = line.rstrip()
            break
    if not header:
        header = f"# {title}"
    return f"{header}\n\n{body.strip()}\n"


def _has_prose(value: str) -> bool:
    """Does this blob value say anything besides its headings?

    Deliberately NOT ``strip_empty_sections``: that one is the yardstick for
    FILES, where the convention is that all content sits under a ``##``
    section, so it discards a prelude. A blob value is just as often plain
    prose with no section at all — measuring it that way would declare a
    character's whole personality empty and drop it.
    """
    return bool("\n".join(ln for ln in (value or "").splitlines()
                          if not ln.lstrip().startswith("#")).strip())


def _scaffold_for(filename: str) -> str:
    """The empty scaffold shipped in shared/templates/soul/, or ""."""
    try:
        from app.models.character import _soul_template_dir
        src = _soul_template_dir() / filename
        return src.read_text(encoding="utf-8") if src.exists() else ""
    except Exception:
        return ""


def _compose_rescue(existing: str, value: str, section: str) -> str:
    """Put ``value`` into ``existing`` so that the readers find it again."""
    from app.models.character import _inject_into_first_empty_section

    structured = any(ln.strip().startswith("## ") for ln in value.splitlines())
    if not structured and existing:
        injected = _inject_into_first_empty_section(existing, value)
        if injected != existing:
            return injected
    if not structured:
        value = f"## {section.replace('_', ' ').title()}\n\n{value}"
    return _replace_body(existing, value, section.title())


def migrate_soul_blobs_once(only: Optional[str] = None) -> Dict[str, Any]:
    """Strip ``source_file`` keys from every character's profile blob.

    ``only``: restrict the sweep to one character. Used by the paths that can
    put a blob value BACK — a reset (which clears the file the value would
    otherwise outlive) and an import of an older export (whose dump carries
    the raw row). They get the rescue and the backup for free instead of a
    second, subtly different strip.

    Returns ``{characters, rescued, dropped, backup}`` for the boot log, or
    ``{}`` when there was nothing to do.
    """
    from app.core.db import get_connection, transaction
    from app.models.character import (_inject_into_first_empty_section,
                                      get_character_dir)
    from app.models.character_template import (get_template, load_source_file,
                                               source_file_keys)

    sql = "SELECT name, template, profile_json FROM characters"
    params: tuple = ()
    if only:
        sql += " WHERE name=?"
        params = (only,)
    try:
        rows = get_connection().execute(sql, params).fetchall()
    except Exception as exc:
        logger.warning("soul-blob migration: reading characters failed: %s", exc)
        return {}

    updates: List[tuple] = []
    dropped_backup: Dict[str, Dict[str, str]] = {}
    rescued = dropped = 0

    for name, template_col, profile_json in rows:
        try:
            profile = json.loads(profile_json or "{}")
        except Exception:
            continue
        if not isinstance(profile, dict):
            continue
        template_id = (profile.get("template") or template_col or "").strip()
        tmpl = get_template(template_id) if template_id else None
        if not tmpl:
            continue
        keys = source_file_keys(tmpl)
        # Blob values that carry no prose at all are scaffolds the old
        # file->blob round-trip left behind ("## Main task\n\n## Concrete
        # activities"), not content — they go with the rest of the keys.
        present = {k: profile[k].strip() for k in keys
                   if isinstance(profile.get(k), str) and _has_prose(profile[k])}
        if not any(k in profile for k in keys):
            continue

        char_dir = get_character_dir(name)
        keep: set = set()
        for key, blob_value in present.items():
            relpath = keys[key]
            md_path = char_dir / relpath
            # Same yardstick the prompt uses: a file holding nothing but empty
            # `## Section` headings is a scaffold, i.e. EMPTY. Measuring this
            # any other way would count a scaffold as content and silently
            # throw away prose that lives nowhere else.
            file_body = load_source_file(name, relpath).strip()
            if file_body:
                continue  # the file speaks — the blob copy is redundant
            section = _section_id(relpath)
            if section in _GENERATED_SECTIONS:
                dropped_backup.setdefault(name, {})[key] = blob_value
                dropped += 1
                logger.info("soul-blob migration [%s]: %s dropped (%d chars, "
                            "generated section with an empty file)",
                            name, key, len(blob_value))
                continue
            # Authored prose with no other home — move it into the file.
            # It has to land UNDER a `## Section`: that is where the readers
            # look, so prose written next to the title would be invisible and
            # the rescue would silently lose it.
            try:
                existing = (md_path.read_text(encoding="utf-8")
                            if md_path.exists() else "")
                if "## " not in existing:
                    existing = _scaffold_for(md_path.name) or existing
                md_path.parent.mkdir(parents=True, exist_ok=True)
                md_path.write_text(
                    _compose_rescue(existing, blob_value, section),
                    encoding="utf-8")
            except Exception as exc:
                logger.warning("soul-blob migration [%s]: writing %s failed: "
                               "%s — key kept in the profile", name, relpath, exc)
                keep.add(key)
                continue
            # Verify at the consumer, not at the writer: if the rescued text
            # does not read back, keep the key rather than drop the only copy.
            if not load_source_file(name, relpath).strip():
                logger.warning("soul-blob migration [%s]: %s did not read back "
                               "from %s — key kept in the profile",
                               name, key, relpath)
                keep.add(key)
                continue
            rescued += 1
            logger.info("soul-blob migration [%s]: %s moved into %s "
                        "(%d chars)", name, key, relpath, len(blob_value))

        for key in keys:
            if key not in keep:
                profile.pop(key, None)
        updates.append((json.dumps(profile, ensure_ascii=False), name))

    if not updates:
        return {}

    backup_path: Optional[Path] = None
    if dropped_backup:
        backup_path = _write_backup(dropped_backup)

    try:
        with transaction() as conn:
            conn.executemany(
                "UPDATE characters SET profile_json=? WHERE name=?", updates)
    except Exception as exc:
        logger.warning("soul-blob migration: writing profiles failed: %s", exc)
        return {}

    result: Dict[str, Any] = {"characters": len(updates),
                              "rescued": rescued, "dropped": dropped}
    if backup_path:
        result["backup"] = str(backup_path)
    return result


def _write_backup(payload: Dict[str, Dict[str, str]]) -> Optional[Path]:
    """Persist dropped values under ``migration_backup/`` in the world dir."""
    from app.core.paths import get_storage_dir
    from app.core.timeutils import utc_now

    try:
        target_dir = get_storage_dir() / "migration_backup"
        target_dir.mkdir(parents=True, exist_ok=True)
        stamp = utc_now().strftime("%Y%m%d-%H%M%S")
        path = target_dir / f"soul_blob_{stamp}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        return path
    except Exception as exc:
        logger.warning("soul-blob migration: backup could not be written: %s", exc)
        return None
