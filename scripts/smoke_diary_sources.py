#!/usr/bin/env python3
"""Smoke plugin diary sources. Usage: ./.venv/bin/python scripts/smoke_diary_sources.py

Hand-derived expectations: Ana has one notes row (local id n1, NOTE-TEXT)
on Y0001-D001; Ben has none. Namespacing yields notes:n1, and a delete
callback makes it deletable. Default summary_input=False excludes NOTE-TEXT;
explicit opt-in includes it. Collection must not mutate the source row.
GET must expose the source label/icon. DELETE requires require_admin even for
an owner: unknown/missing rows give 404, a read-only source gives 405, and
successful deletion returns the namespaced id and leaves zero source rows.
No server startup, network or real storage is needed.
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

with tempfile.TemporaryDirectory(prefix="diary-sources-") as tmp:
    os.environ["STORAGE_DIR"] = tmp
    os.environ["INSTANCE_DIR"] = str(Path(tmp) / "instance")
    from app.core import paths
    paths.init(tmp)
    paths.init_instance(Path(tmp) / "instance")
    from app.core import config, db
    config.load(Path(tmp) / "config.json")
    db.init_schema()
    from app.models import diary
    from app.core.auth_dependency import require_admin
    from app.routes.diary import router, get_diary_entries, delete_diary_entry
    from fastapi import HTTPException, Request
    from unittest.mock import patch

    day = "Y0001-D001"
    store = [{"type": "notes", "id": "n1", "content": "NOTE-TEXT",
              "timestamp": "2026-01-01T10:00:00+00:00",
              "game_ts": day + "T10:00:00"}]

    def collect(character, key):
        return store if character == "Ana" and key == day else []

    def delete(character, local_id):
        if character == "Ana" and local_id == "n1" and store:
            store.clear()
            return True
        return False

    diary.register_diary_source("notes", collect, type_label="Notes", icon="N", delete=delete)
    entries = [e for e in diary.generate_for_day("Ana", day) if e["type"] == "notes"]
    assert len(entries) == 1 and entries[0]["id"] == "notes:n1"
    assert entries[0]["deletable"] is True and store[0]["id"] == "n1"
    assert not [e for e in diary.generate_for_day("Ben", day) if e["type"] == "notes"]
    assert "NOTE-TEXT" not in diary.build_daily_summary_input("Ana", day)
    data = get_diary_entries("Ana", date=day)
    assert data["types"]["notes"] == "Notes" and data["icons"]["notes"] == "N"
    assert data["entries"] == list(reversed(diary.generate_for_day("Ana", day)))
    assert get_diary_entries("Ana", date=day, type="notes")["entries"] == entries
    assert get_diary_entries("Ana", date=day, type="mood")["entries"] == []
    assert "notes" not in diary.ENTRY_TYPES and "notes" not in diary.ENTRY_ICONS
    diary.register_diary_source("notes", collect, type_label="Notes", icon="N", delete=delete,
                                summary_input=True)
    assert "NOTE-TEXT" in diary.build_daily_summary_input("Ana", day)
    diary.register_diary_source("notes", collect, type_label="Notes", icon="N", delete=delete)
    diary.register_diary_source("readonly", lambda c, d: [], type_label="Read only", icon="R")
    # A source that raises is skipped with a warning; the other entries survive.
    def broken(character, key):
        raise RuntimeError("boom")
    diary.register_diary_source("broken", broken, type_label="Broken", icon="B")
    assert [e["id"] for e in diary.generate_for_day("Ana", day) if e["type"] == "notes"] == ["notes:n1"]
    diary._DIARY_SOURCES.pop("broken")
    route = next(r for r in router.routes if "DELETE" in r.methods)
    assert route.path == "/diary/{user_id}/{character_name}/entries/{entry_id}"
    assert require_admin in [d.call for d in route.dependant.dependencies]
    def call_status(character, entry_id):
        try:
            return delete_diary_entry(character, entry_id)
        except HTTPException as exc:
            return exc.status_code

    # Exercise the actual authorization dependency without a server or portal thread.
    request = Request({"type": "http", "headers": []})
    for user, expected in [(None, 401), ({"role": "user"}, 403)]:
        with patch("app.core.auth_dependency._get_session_user", return_value=user):
            try:
                require_admin(request)
                raise AssertionError("Unauthorized deletion accepted")
            except HTTPException as exc:
                assert exc.status_code == expected
    with patch("app.core.auth_dependency._get_session_user", return_value={"role": "admin"}):
        assert require_admin(request)["role"] == "admin"
    assert call_status("Ana", "nosuch:x") == 404
    assert call_status("Ana", "invalid") == 404
    assert call_status("Ana", "readonly:x") == 405
    assert call_status("Ben", "notes:n1") == 404
    assert call_status("Ana", "notes:n1") == {"deleted": "notes:n1"}
    assert store == []
    assert call_status("Ana", "notes:n1") == 404
    print("PASS: diary source collection, summary isolation, GET metadata and admin DELETE")
