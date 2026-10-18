#!/usr/bin/env python3
"""LoRA store contract A–P, using temporary storage only.

Hand-derived expectations: A's manual L-all applies to A and B, L-disc only
A, L-other only B: options are [L-all,L-disc] and [L-all,L-other], all present.
Migration preserves three ordered entries and backs up the original config;
B reload changes neither file. C an existing two-entry file wins over three
legacy entries, with one 'dropped 3' warning. D editing L-disc preserves it
as manual/missing when A reports only another name. E two concurrent writers
produce twenty edited words AND twenty new names. F a changed stat exposes a
hand edit. G no instance means empty reads, refused writes and harmless sync.
H stale settings are refused without changing either file. I each real edit
backs up once, no-op edits never do; permissions are 0700/0600 and config
history stays unchanged. J an unreadable file reads as [] with one logged
error, a writer raises ValueError and the file bytes stay as they were. K GET returns three migrated entries. L POST adds a manual entry visible in GET.
M editing a discovered word makes it manual. N rename conflict returns 409
with byte-identical storage. O unknown delete returns false with no snapshot;
known delete returns true with one new snapshot. P slash names work in POST,
PATCH and delete. Extra checks cover conflicts, backend removal,
secrets preservation, refusal of unbound legacy targets, and the existing CLI:
dry-run writes nothing; the selected source migrates three entries after backup.

Old-code proof: at c822d24a, case A leaves lora_triggers in config.json and
creates no lora_library.json; this assertion fails before any new API is used.
At 60da557c, K fails because the per-entry library GET route does not exist.
"""
import json
import logging
import os
from pathlib import Path
import stat
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

with tempfile.TemporaryDirectory(prefix="lora-library-store-") as tmp:
    root = Path(tmp)
    world = root / "world"
    instance = root / "instance"
    world.mkdir()
    instance.mkdir()
    from app.core import paths
    paths.init(world)
    paths.init_instance(instance)
    from app.core import config, config_admin, config_scope, lora_library as lib
    from app.imagegen import service

    wp = world / "config.json"
    cp = instance / "config.json"
    lp = instance / "lora_library.json"
    wp.write_text("{}")
    initial = [
        {"lora": "L-all", "word": "all", "source": "manual", "backends": [], "missing_on": []},
        {"lora": "L-disc", "word": "", "source": "discovered", "backends": ["A"], "missing_on": []},
        {"lora": "L-other", "word": "", "source": "discovered", "backends": ["B"], "missing_on": []},
    ]
    legacy = {"image_generation": {"lora_triggers": initial}, "server": {"log_level": "DEBUG"}}
    cp.write_text(json.dumps(legacy))
    secrets_path = instance / "secrets.json"
    secrets_path.write_text(json.dumps({"server": {"password": "test-only-secret"}}))
    old_config = cp.read_bytes()
    config.load(wp, cp)
    assert secrets_path.exists(), "A: migration must preserve instance secrets"
    assert json.loads(secrets_path.read_text()) == {"server": {"password": "test-only-secret"}}
    assert lp.exists(), "A: c822d24a has no library file after load"
    assert json.loads(lp.read_text()) == {"version": 1, "entries": initial}
    assert "lora_triggers" not in json.loads(cp.read_text()).get("image_generation", {})
    assert any((p / "config.json").read_bytes() == old_config for p in config.list_snapshots(instance))
    assert config.get_lora_options("A") == [{"name": "L-all", "missing": False}, {"name": "L-disc", "missing": False}]
    assert config.get_lora_options("B") == [{"name": "L-all", "missing": False}, {"name": "L-other", "missing": False}]
    assert config.get_lora_trigger_words(["L-all"]) == ["all"]
    # Exercise the pinned old implementation, with both paths still temporary.
    import subprocess
    old_source = subprocess.run(
        ["timeout", "300", "git", "show", "c822d24a:app/core/config.py"],
        check=True, capture_output=True, text=True).stdout
    old_namespace = {"__name__": "lora_store_old_config", "__file__": config.__file__}
    exec(compile(old_source, "c822d24a:app/core/config.py", "exec"), old_namespace)
    old_instance = root / "old-instance"
    old_instance.mkdir()
    old_cp = old_instance / "config.json"
    old_cp.write_text(json.dumps(legacy))
    paths.init_instance(old_instance)
    try:
        old_namespace["load"](wp, old_cp)
        assert "lora_triggers" in json.loads(old_cp.read_text())["image_generation"]
        assert not (old_instance / "lora_library.json").exists()
    finally:
        paths.init_instance(instance)
    print("PASS A migration, backup and backend options (old code: c822d24a)")
    before = (cp.read_bytes(), lp.read_bytes())
    config.load(wp, cp)
    assert before == (cp.read_bytes(), lp.read_bytes())
    print("PASS B idempotent reload")

    cp.write_text(json.dumps(legacy))
    lp.write_text(json.dumps({"version": 1, "entries": initial[:2]}))
    records = []
    class Capture(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())
    handler = Capture()
    config.logger.addHandler(handler)
    try:
        config.load(wp, cp)
    finally:
        config.logger.removeHandler(handler)
    assert lib.entries() == initial[:2]
    assert sum("dropped 3" in r for r in records) == 1, records
    assert "lora_triggers" not in json.loads(cp.read_text()).get("image_generation", {})
    print("PASS C crash recovery: existing library wins, one warning")

    class Backend:
        name = "A"
        instance_enabled = True
        lora_url = "fake://loras"
        def fetch_loras(self):
            # Network work must permit an editor write on another thread.
            with ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(lib.update_entry, "L-all", word="network edit").result(timeout=5)
            return ["replacement"]
    class Service:
        enabled = True
        backends = [Backend()]
    lib.update_entry("L-disc", word="w")
    with patch.object(service, "get_image_service", return_value=Service()):
        lib.sync_lora_library()
    touched = next(e for e in lib.entries() if e["lora"] == "L-disc")
    assert touched["word"] == "w" and touched["source"] == "manual" and touched["missing_on"] == ["A"]
    assert next(e for e in lib.entries() if e["lora"] == "L-all")["word"] == "network edit"
    print("PASS D touched discovery survives; network holds no store lock")

    for i in range(20):
        lib.add_manual_entry(f"edit-{i}")
    barrier = Barrier(2)
    def editor():
        for i in range(20):
            barrier.wait(timeout=5)
            lib.update_entry(f"edit-{i}", word=f"word-{i}")
    def sync_writer():
        for i in range(20):
            barrier.wait(timeout=5)
            def add(items):
                items.append({"lora": f"new-{i}", "word": "", "source": "discovered", "backends": ["A"], "missing_on": []})
                return True
            lib._mutate(add)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(editor), pool.submit(sync_writer)]
        for future in futures:
            future.result(timeout=30)
    stored = {e["lora"]: e for e in json.loads(lp.read_text())["entries"]}
    for i in range(20):
        assert stored[f"edit-{i}"]["word"] == f"word-{i}"
        assert f"new-{i}" in stored
    print("PASS E twenty concurrent edits and discoveries preserved")

    data = json.loads(lp.read_text())
    data["entries"].append({"lora": "external", "source": "manual", "word": "", "backends": [], "missing_on": []})
    previous_stat = lp.stat()
    lp.write_text(json.dumps(data))
    os.utime(lp, ns=(previous_stat.st_atime_ns, previous_stat.st_mtime_ns + 1_000_000_000))
    assert lib.entries()[-1]["lora"] == "external"
    print("PASS F external edit invalidates stat cache")
    with patch.object(paths, "instance_initialised", return_value=False):
        assert lib.entries() == []
        try:
            lib.add_manual_entry("unavailable")
        except lib.LoraLibraryUnavailable:
            pass
        else:
            raise AssertionError("G: writer accepted missing instance")
        with patch.object(service, "get_image_service", return_value=Service()):
            assert lib.sync_lora_library()["changed"] is False
    print("PASS G no-instance readers, writers and sync")

    before = (cp.read_bytes(), lp.read_bytes())
    try:
        config_admin.save_layer("instance", {"image_generation": {"lora_triggers": initial}})
    except config_admin.LayerSaveError as exc:
        assert str(exc) == "image_generation.lora_triggers moved to the LoRA library — reload the page"
    else:
        raise AssertionError("H: stale settings accepted")
    assert before == (cp.read_bytes(), lp.read_bytes())
    assert config_scope.scope_of("image_generation.lora_triggers") is None
    assert "lora_triggers" not in config_scope.prune(legacy).get("image_generation", {})
    assert "lora_triggers" not in config_scope.shipped_tree("instance").get("image_generation", {})
    assert config_scope.schema_for("instance")["image_generation"]["sub_arrays"]["lora_triggers"]["virtual"]
    print("PASS H stale save rejected; virtual marker excluded from config")

    # Use a fresh history directory so retention cannot hide extra snapshots.
    history = instance / lib.LORA_HISTORY_DIRNAME
    import shutil
    shutil.rmtree(history)
    config_history = {str(p.relative_to(instance)): p.read_bytes() for p in (instance / ".config-history").rglob("*") if p.is_file()}
    def count():
        return len(list(history.iterdir())) if history.exists() else 0
    lib.update_entry("L-disc", word="w")
    assert count() == 0
    lib.update_entry("L-disc", backends=["B"])
    assert count() == 1
    assert next(e for e in lib.entries() if e["lora"] == "L-disc")["missing_on"] == []
    lib.add_manual_entry("new/manual")
    assert count() == 2
    try:
        lib.update_entry("new/manual", rename_to="L-disc")
    except lib.LoraLibraryConflict:
        pass
    else:
        raise AssertionError("rename conflict accepted")
    try:
        lib.add_manual_entry("L-disc")
    except lib.LoraLibraryConflict:
        pass
    else:
        raise AssertionError("duplicate accepted")
    assert count() == 2
    assert not lib.delete_entry("unknown")
    assert count() == 2
    assert lib.delete_entry("new/manual")
    assert count() == 3
    assert lib.clear_discovered() == 21
    assert count() == 4
    assert lib.clear_discovered() == 0
    assert count() == 4
    assert stat.S_IMODE(history.stat().st_mode) == 0o700
    assert stat.S_IMODE(lp.stat().st_mode) == 0o600
    for p in history.rglob("*"):
        assert stat.S_IMODE(p.stat().st_mode) == (0o700 if p.is_dir() else 0o600)
    assert config_history == {str(p.relative_to(instance)): p.read_bytes() for p in (instance / ".config-history").rglob("*") if p.is_file()}
    for i in range(55):
        lib.update_entry("L-all", word=f"rotate-{i}")
    assert count() == 50
    print("PASS I one backup per mutation, no-op/conflict unchanged, permissions and retention")
    # J: an unreadable library reads as empty (renders go on, one error log)
    # while every writer refuses it, so the broken file is never replaced.
    broken = b'{"entries": "not a list"}'
    lp.write_bytes(broken)
    records = []
    handler = Capture()
    lib.logger.addHandler(handler)
    try:
        assert lib.entries() == [] and lib.entries() == []
        assert config.get_lora_options("A") == []
        try:
            lib.add_manual_entry("blocked")
        except ValueError:
            pass
        else:
            raise AssertionError("J: writer replaced an unreadable library")
    finally:
        lib.logger.removeHandler(handler)
    assert lp.read_bytes() == broken
    assert sum("Invalid LoRA library" in r for r in records) == 1, records
    print("PASS J unreadable library: empty reads, refused writes, one error")
    import asyncio
    from fastapi import HTTPException
    from app.routes import admin_settings as adm
    class Request:
        def __init__(self, body):
            self.body = body
        async def json(self):
            return self.body
    def call(route, body):
        return asyncio.run(route(Request(body), user=None))
    def refused(route, body, status):
        try:
            call(route, body)
        except HTTPException as exc:
            assert exc.status_code == status
            return exc.detail
        raise AssertionError(f"Expected HTTP {status}: {body}")
    # Re-run migration for the route fixture after J deliberately broke the file.
    lp.unlink()
    cp.write_text(json.dumps(legacy))
    config.load(wp, cp)
    assert hasattr(adm, "lora_library_get"), "K: missing library GET route"
    assert adm.lora_library_get(user=None) == {"entries": initial}
    print("PASS K GET migrated entries")
    added = {"lora": "route-new", "word": "trigger", "source": "manual", "backends": ["A"], "missing_on": []}
    assert call(adm.lora_library_add, {"lora": "route-new", "word": "trigger", "backends": ["A"]}) == {"entry": added}
    assert adm.lora_library_get(user=None)["entries"] == initial + [added]
    detail = refused(adm.lora_library_add, {"lora": "route-new"}, 409)
    assert detail["code"] == "duplicate" and "route-new" in detail["message"]
    refused(adm.lora_library_add, {"lora": " "}, 400)
    print("PASS L POST manual entry and errors")
    assert call(adm.lora_library_update, {"lora": "L-disc", "word": "edited"}) == {"entry": dict(initial[1], word="edited", source="manual")}
    refused(adm.lora_library_update, {"lora": "unknown", "word": "x"}, 404)
    print("PASS M PATCH discovered becomes manual")
    before = lp.read_bytes()
    snapshots = count()
    detail = refused(adm.lora_library_update, {"lora": "L-disc", "rename_to": "L-all"}, 409)
    assert detail["code"] == "duplicate" and "L-all" in detail["message"]
    assert lp.read_bytes() == before and count() == snapshots
    print("PASS N rename conflict: 409 and byte-identical file")
    assert call(adm.lora_library_delete, {"lora": "unknown"}) == {"deleted": False}
    assert count() == snapshots
    shutil.rmtree(history)
    assert call(adm.lora_library_delete, {"lora": "route-new"}) == {"deleted": True}
    assert count() == 1
    assert (next(history.iterdir()) / "lora_library.json").read_bytes() == before
    print("PASS O delete results and one snapshot")
    slash = "flux/a.safetensors"
    assert call(adm.lora_library_add, {"lora": slash})["entry"]["lora"] == slash
    assert call(adm.lora_library_update, {"lora": slash, "word": "flux"})["entry"]["word"] == "flux"
    assert call(adm.lora_library_delete, {"lora": slash}) == {"deleted": True}
    assert all(e["lora"] != slash for e in adm.lora_library_get(user=None)["entries"])
    print("PASS P slash names in POST, PATCH and delete")
    alternate = root / "alternate-instance"
    alternate.mkdir()
    alternate_cp = alternate / "config.json"
    alternate_cp.write_text(json.dumps(legacy))
    alternate_before = alternate_cp.read_bytes()
    try:
        config.migrate_file(wp, alternate_cp)
    except config.ConfigWriteRefused:
        pass
    else:
        raise AssertionError("migration must refuse an unbound legacy instance")
    assert alternate_cp.read_bytes() == alternate_before

    cli_worlds = root / "cli-worlds"
    cli_source = cli_worlds / "source"
    cli_source.mkdir(parents=True)
    cli_cp = cli_source / "config.json"
    cli_cp.write_text(json.dumps(legacy))
    cli_instance = root / "cli-instance"
    cli_backups = root / "cli-backups"
    command = ["timeout", "300", sys.executable, "scripts/migrate_instance_config.py",
               "--from", "source", "--worlds-dir", str(cli_worlds),
               "--instance", str(cli_instance), "--backup-dir", str(cli_backups)]
    dry = subprocess.run(command + ["--dry-run"], capture_output=True, text=True)
    assert dry.returncode == 0, dry.stdout + dry.stderr
    assert not cli_instance.exists() and not cli_backups.exists()
    assert json.loads(cli_cp.read_text()) == legacy
    actual = subprocess.run(command, capture_output=True, text=True)
    assert actual.returncode == 0, actual.stdout + actual.stderr
    assert json.loads((cli_instance / "lora_library.json").read_text())["entries"] == initial
    assert "lora_triggers" not in json.loads(cli_cp.read_text()).get("image_generation", {})
    print("PASS migration safeguards: explicit target refused; CLI dry-run and legacy data preserved")
    print("PASS A–P LoRA library store")
