#!/usr/bin/env python3
"""Smoke pose labels. Usage: ./.venv/bin/python scripts/smoke_pose_labels.py

Hand-derived expectations: world pair waltzing has only German Walzertanzen,
so English falls back to its key. Pair twirling has base twirling around,
so both languages use that until German is set to Herumwirbeln. Clearing
German removes the stored field and restores the base fallback. Solo bowing
and an unknown key return their keys; only an unlabeled pair is flagged.
Whitespace is stripped, lookup ignores key case, and other language labels
survive normalization. Labels of 80 characters are valid; 81 are rejected
with 400 on create and update, without changing storage. Options use the
avatar language. Finally every shipped pair must have a German label (the
controller supplies those labels separately). All writes use temporary storage.
"""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

with tempfile.TemporaryDirectory(prefix="pose-labels-") as tmp:
    os.environ["STORAGE_DIR"] = tmp
    os.environ["INSTANCE_DIR"] = str(Path(tmp) / "instance")
    from app.core import paths
    paths.init(tmp)
    paths.init_instance(Path(tmp) / "instance")
    from app.core import config, db
    config.load(Path(tmp) / "config.json")
    db.init_schema()
    from app.core.pose_catalog import pose_label
    from app.core import pose_catalog
    from app.routes.poses import _create_entry_sync, _update_entry_sync, list_entries
    from app.core.pose_catalog_edit import read_store, write_store, catalog_txn
    from fastapi import HTTPException

    def create(key, **fields):
        return _create_entry_sync({}, dict(key=key, prompt=key, animation="standing",
                                          solo=False, places=2, yaw_offset=0, group="stand", store="world", **fields))

    create("waltzing", label_de="  Walzertanzen  ")
    _create_entry_sync({}, dict(key="bowing", prompt="bowing", animation="standing",
                               solo=True, group="stand", store="world"))
    create("twirling", label=" twirling around ")
    assert pose_label("waltzing", "de") == "Walzertanzen"
    assert pose_label("waltzing", "en") == "waltzing"
    assert pose_label("twirling", "en") == "twirling around"
    assert pose_label("twirling", "de") == "twirling around"
    assert pose_label("bowing", "de") == "bowing"
    assert pose_label("no such pose", "de") == "no such pose"
    assert pose_label("  Waltzing ", "de") == "Walzertanzen"
    assert pose_label("  Unknown Pose  ", "de") == "Unknown Pose"
    rows = {r["key"]: r for r in list_entries(axis="pose")["entries"]}
    assert rows["waltzing"]["label_de_missing"] is False
    assert rows["waltzing"]["label_de"] == "Walzertanzen"
    assert rows["twirling"]["label"] == "twirling around"
    assert rows["twirling"]["label_de_missing"] is True
    assert rows["bowing"]["label_de_missing"] is False
    _update_entry_sync("twirling", "pose", {}, {"label_de": " Herumwirbeln "})
    assert pose_label("twirling", "de") == "Herumwirbeln"
    _update_entry_sync("twirling", "pose", {}, {"label_de": ""})
    assert "label_de" not in read_store("pose", "world")["entries"]["twirling"]
    assert pose_label("twirling", "de") == "twirling around"
    with catalog_txn("pose"):
        data = read_store("pose", "world")
        data["entries"]["waltzing"]["label_fr"] = " valse "
        write_store("pose", data, "world")
    assert pose_label("waltzing", "fr") == "valse"
    assert pose_catalog.get_catalog("pose")["waltzing"]["label_fr"] == "valse"
    for field in ("label", "label_de"):
        for invalid in ("x" * 81, 123, None):
            for operation in (lambda: create("swaying", **{field: invalid}),
                              lambda: _update_entry_sync("twirling", "pose", {}, {field: invalid})):
                before = read_store("pose", "world")
                try:
                    operation()
                except HTTPException as exc:
                    assert exc.status_code == 400
                else:
                    raise AssertionError("Invalid label accepted")
                assert read_store("pose", "world") == before
        _update_entry_sync("twirling", "pose", {}, {field: "x" * 80})
    create("swaying", label="x" * 80, label_de="x" * 80)
    _update_entry_sync("twirling", "pose", {}, {"label": "", "label_de": ""})
    assert "label" not in read_store("pose", "world")["entries"]["twirling"]
    assert pose_label("twirling", "de") == "twirling"
    with patch.object(pose_catalog, "get_catalog", side_effect=RuntimeError("unavailable")):
        assert pose_label(" waltzing ", "de") == "waltzing"
    from app.routes.play import play_interact_options
    with patch("app.core.hooks.get_provider", return_value=lambda: "InteractWith"), patch(
        "app.core.interaction_engine.partner_poses", return_value=[("waltzing", "standing")]
    ), patch("app.models.account.get_active_character", return_value="demo"), patch(
        "app.models.character.get_character_language", return_value="de"
    ):
        assert play_interact_options(user={}) == {
            "poses": [{"key": "waltzing", "kind": "standing", "label": "Walzertanzen"}]}
    print("PASS: pose label lookup, editor storage, validation, list flags and localized options", flush=True)
    import json
    shipped = json.loads(pose_catalog.catalog_path("pose").read_text())["entries"]
    assert all(e.get("label_de", "").strip() for e in shipped.values() if not e.get("solo", True)), \
        "Every shipped pair pose must have label_de (controller supplies shipped labels)"
    print("PASS: every shipped pair pose has label_de")
