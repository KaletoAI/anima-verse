#!/usr/bin/env python3
"""Soul cache: two reads cost one read_text; changes invalidate; writes replace inodes.

Usage: ./.venv/bin/python scripts/smoke_soul_md_cache.py
All storage is temporary and initialized before world modules are imported.
"""
import asyncio
import os
import stat
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import paths

current_umask = os.umask(0)
os.umask(current_umask)

with tempfile.TemporaryDirectory() as tmp, patch.object(
        os, "umask", side_effect=AssertionError("writer must not mutate umask")):
    paths.init(Path(tmp))
    from app.models import character_template as template
    from app.models.character import get_character_dir
    from app.core import soul_writer

    f = get_character_dir("demo") / "soul" / "test.md"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("# A\ntext\n")
    real_read = Path.read_text
    calls = []

    def read(path, *args, **kwargs):
        calls.append(path)
        return real_read(path, *args, **kwargs)

    with patch.object(Path, "read_text", read):
        assert template.load_source_file("demo", "soul/test.md") == template.strip_empty_sections("# A\ntext\n")
        assert template.load_source_file("demo", "soul/test.md") == template.strip_empty_sections("# A\ntext\n")
        assert len(calls) == 1, ("second read cached", len(calls))
        # Isolate cache I/O from the legacy directory-selection helper.
        with patch("app.models.character.get_character_dir", return_value=f.parent.parent), patch.object(
                template.os, "stat", wraps=template.os.stat) as stat_calls, patch.object(
                Path, "resolve", wraps=f.resolve) as resolve_calls:
            template.load_source_file("demo", "soul/test.md")
            assert stat_calls.call_count == 1, ("one stat per hit", stat_calls.call_count)
            assert resolve_calls.call_count == 0, "cache hits must not resolve paths"
        f.write_text("# A\nlonger text\n")
        assert template.load_source_file("demo", "soul/test.md") == template.strip_empty_sections("# A\nlonger text\n")
        assert len(calls) == 2, "size change re-reads"
        unchanged_identity = f.stat()
        f.write_text("# A\nLONGER text\n")
        with patch.object(template.os, "stat", return_value=unchanged_identity):
            template.invalidate_source_file(f)
            assert template.load_source_file("demo", "soul/test.md") == template.strip_empty_sections("# A\nLONGER text\n")
        assert len(calls) == 3, "explicit invalidate"
        f.unlink()
        assert template.load_source_file("demo", "soul/test.md") == ""

    # A real in-place writer must refresh content even with identical metadata.
    from app.core import character_ops
    f = get_character_dir("demo") / "soul" / "personality.md"
    f.write_text("# A\n## Body\nalpha\n")
    assert "alpha" in template.load_source_file("demo", "soul/personality.md")
    identity = f.stat()
    real_stat = template.os.stat
    resolved = f.resolve()

    def fixed_stat(path, *args, **kwargs):
        if Path(path) == resolved:
            return identity
        return real_stat(path, *args, **kwargs)

    request = SimpleNamespace(json=AsyncMock(return_value={"content": "# A\n## Body\nbravo\n"}))
    with patch.object(template.os, "stat", fixed_stat), patch.object(
            character_ops, "_is_soul_section_enabled", return_value=True):
        asyncio.run(character_ops.write_soul_file("demo", "personality", request))
        assert "bravo" in template.load_source_file("demo", "soul/personality.md")

    # A partially successful in-place write must invalidate and preserve its error.
    failure = OSError("partial write")
    real_write = Path.write_text

    def partial_write(path, *args, **kwargs):
        real_write(path, "# A\n## Body\npartial\n", encoding="utf-8")
        raise failure

    with patch.object(template.os, "stat", fixed_stat), patch.object(
            character_ops, "_is_soul_section_enabled", return_value=True), patch.object(
            Path, "write_text", partial_write):
        try:
            asyncio.run(character_ops.write_soul_file("demo", "personality", request))
        except OSError as exc:
            assert exc is failure, "original write exception propagates"
        else:
            raise AssertionError("write failure must propagate")
        assert "partial" in template.load_source_file("demo", "soul/personality.md")

    # New atomic files have the same mode as plain open under the current umask.
    plain = f.parent / "plain.md"
    with plain.open("w") as stream:
        stream.write("plain")
    fresh = f.parent / "fresh.md"
    soul_writer._atomic_write(fresh, "fresh")
    assert stat.S_IMODE(fresh.stat().st_mode) == 0o666 & ~current_umask
    assert stat.S_IMODE(fresh.stat().st_mode) == stat.S_IMODE(plain.stat().st_mode)

    soul_writer.append_entry("demo", "beliefs", "about_self", "First")
    target = soul_writer.get_soul_file_path("demo", "beliefs")
    target.chmod(0o640)
    before = target.stat().st_ino
    soul_writer.append_entry("demo", "beliefs", "about_self", "Second")
    assert target.stat().st_ino != before, "append atomically replaces inode"
    assert stat.S_IMODE(target.stat().st_mode) == 0o640, "atomic write preserves mode"
    before = target.stat().st_ino
    soul_writer.rewrite_file("demo", "beliefs", [{"category": "about_self", "text": "Third"}])
    assert target.stat().st_ino != before, "rewrite atomically replaces inode"
    assert stat.S_IMODE(target.stat().st_mode) == 0o640, "rewrite preserves mode"
    assert "Third" in template.load_source_file("demo", "soul/beliefs.md")
print("Soul cache checks passed")
