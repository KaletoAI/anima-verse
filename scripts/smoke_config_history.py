#!/usr/bin/env python3
"""Smoke: back up each changed config layer before writing it (Task 1, A4).

Usage: ./.venv/bin/python scripts/smoke_config_history.py

All fixtures live under a TemporaryDirectory. Both paths are initialized
before importing config or any world-DB module. Case J passes a path STRING
to git check-ignore; it never creates anything in the repository worlds.

Hand-derived expectations from plan-config-save-guard.md, Task 1:
A  Instance starts with Europe/Berlin and provider p, whose separate secret
   is sk-1. Changing timezone to UTC means one backup containing both exact
   pre-save byte strings, even though only config.json changes.
B  Repeating that save changes neither JSON value: still one backup.
C  Changing only p.api_key to sk-2 makes a second backup, with sk-1 in it.
D  Removing p.api_key removes secrets.json; backup number three retains sk-2.
E  Two direct snapshots at 2026-01-02 03:04:05.000006 UTC must be named
   20260102T030405000006Z and 20260102T030405000006Z-1, both with both files.
F  52 snapshots at one-second intervals with keep=50 discard seconds 0 and
   1, leaving exactly seconds 2 through 51, in ascending name order.
G  History and snapshot directories are 0700; every copied file is 0600,
   even when the source files were 0644.
H  Saving world chat.top_p=0.9 backs up its old {} under the world only;
   the instance history count and file bytes do not change.
I  An OSError during backup refuses the save with ConfigWriteRefused before
   either current file changes, preserving the instance bytes exactly.
J  git check-ignore -q worlds/demo/.config-history/x exits 0, because the
   history ignore rule also covers the tracked demo world.

Task 2 expectations (baseline 62959789 lacks scripts/config_history.py):
K  Removing provider b reports removed entries ['b']; adding c reports added
   entries ['c']; removing a section also reports its nested named entries.
   Secret changes expose paths only, never either key value.
L  A PID file containing this process refuses restore with code 2 and the
   stop-server instruction, leaving files and history unchanged.
M  A stale PID permits restore: exact saved bytes return, a new snapshot
   contains both overwritten files, and restored files have mode 0600.
N  Restoring a config-only snapshot removes current secrets.json.

Baseline without this feature: 8b5f1124b338f336c679a98ea7abc156f72d0f38
fails in A because list_snapshots is absent.
"""
import contextlib
import io
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


def main():
    with tempfile.TemporaryDirectory(prefix="config-history-") as tmp:
        root = Path(tmp)
        world, instance = root / "world", root / "instance"
        os.environ.update(STORAGE_DIR=str(world), INSTANCE_DIR=str(instance))
        from app.core import paths
        paths.init(world)
        paths.init_instance(instance)
        from app.core import config

        cfg = instance / "config.json"
        sec = instance / "secrets.json"
        world_cfg = world / "config.json"
        cfg.write_text(json.dumps({"server": {"timezone": "Europe/Berlin"},
                                   "providers": [{"name": "p"}]}), encoding="utf-8")
        sec.write_text(json.dumps({"providers": {"p": {"api_key": "sk-1"}}}), encoding="utf-8")
        world_cfg.write_text("{}", encoding="utf-8")
        config.load(world_cfg, cfg)
        before = cfg.read_bytes(), sec.read_bytes()
        part = {"server": {"timezone": "UTC"},
                "providers": [{"name": "p", "api_key": "sk-1"}]}
        config.save_part("instance", part)
        snaps = config.list_snapshots(instance)
        assert len(snaps) == 1, "A: one backup per changed layer"
        assert snaps[0].parent == instance / ".config-history"
        assert ((snaps[0] / "config.json").read_bytes(),
                (snaps[0] / "secrets.json").read_bytes()) == before
        print("PASS A: instance backup preserves both pre-save files")

        config.save_part("instance", part)
        assert len(config.list_snapshots(instance)) == 1
        print("PASS B: unchanged save creates no backup")

        config_before = cfg.read_bytes()
        part["providers"][0]["api_key"] = "sk-2"
        config.save_part("instance", part)
        snaps = config.list_snapshots(instance)
        assert len(snaps) == 2 and cfg.read_bytes() == config_before
        assert json.loads((snaps[-1] / "secrets.json").read_text())["providers"]["p"]["api_key"] == "sk-1"
        print("PASS C: secrets-only change backs up the old key")

        del part["providers"][0]["api_key"]
        config.save_part("instance", part)
        snaps = config.list_snapshots(instance)
        assert not sec.exists() and len(snaps) == 3
        assert json.loads((snaps[-1] / "secrets.json").read_text())["providers"]["p"]["api_key"] == "sk-2"
        print("PASS D: removing secrets preserves their backup")

        frozen = datetime(2026, 1, 2, 3, 4, 5, 6, tzinfo=timezone.utc)

        def fixture(name):
            folder = root / name
            folder.mkdir()
            (folder / "config.json").write_bytes(before[0])
            (folder / "secrets.json").write_bytes(before[1])
            for file in folder.iterdir():
                file.chmod(0o644)
            return folder

        collision = fixture("collision")
        with patch.object(config, "utc_now", return_value=frozen):
            first = config.snapshot_layer(collision)
            second = config.snapshot_layer(collision)
        assert [first.name, second.name] == ["20260102T030405000006Z", "20260102T030405000006Z-1"]
        for snap in (first, second):
            assert ((snap / "config.json").read_bytes(),
                    (snap / "secrets.json").read_bytes()) == before
        print("PASS E: identical timestamps create distinct complete backups")

        rotation = fixture("rotation")
        created = []
        for index in range(52):
            with patch.object(config, "utc_now", return_value=frozen + timedelta(seconds=index)):
                created.append(config.snapshot_layer(rotation))
        remaining = config.list_snapshots(rotation)
        assert len(remaining) == 50 and remaining == created[2:]
        assert not created[0].exists() and not created[1].exists()
        print("PASS F: rotation keeps exactly the newest 50 of 52 backups")

        for layer in (instance, collision, rotation):
            assert stat.S_IMODE((layer / ".config-history").stat().st_mode) == 0o700
            for snap in config.list_snapshots(layer):
                assert stat.S_IMODE(snap.stat().st_mode) == 0o700
                for file in snap.iterdir():
                    assert stat.S_IMODE(file.stat().st_mode) == 0o600
        print("PASS G: backup directories are 0700 and files are 0600")

        instance_before = cfg.read_bytes()
        instance_snaps = config.list_snapshots(instance)
        config.save_part("world", {"chat": {"top_p": 0.9}})
        world_snaps = config.list_snapshots(world)
        assert len(world_snaps) == 1
        assert world_snaps[0].parent == world / ".config-history"
        assert (world_snaps[0] / "config.json").read_bytes() == b"{}"
        assert config.list_snapshots(instance) == instance_snaps
        assert cfg.read_bytes() == instance_before
        print("PASS H: world save backs up only the world layer")

        part["server"]["timezone"] = "Europe/London"
        with patch.object(config, "snapshot_layer", side_effect=OSError("backup unavailable")):
            try:
                config.save_part("instance", part)
            except config.ConfigWriteRefused as exc:
                assert "refusing to write config without a backup" in str(exc)
                assert isinstance(exc.__cause__, OSError)
            else:
                raise AssertionError("I: save must refuse a failed backup")
        assert cfg.read_bytes() == instance_before and not sec.exists()
        print("PASS I: failed backup refuses the save without changing files")

        result = subprocess.run(["timeout", "60", "git", "check-ignore", "-q",
                                 "worlds/demo/.config-history/x"], cwd=REPO, check=False)
        assert result.returncode == 0, "J: demo history must be gitignored"
        print("PASS J: demo history path is gitignored without creating it")
        from scripts import config_history
        lines = config_history.diff_layers(
            {"providers": [{"name": "a"}, {"name": "b"}]},
            {"providers": {"b": {"api_key": "old-secret-value"}}},
            {"providers": [{"name": "a"}, {"name": "c"}]},
            {"providers": {"b": {"api_key": "new-secret-value"}}})
        assert "providers: removed entries ['b']" in lines
        assert "providers: added entries ['c']" in lines
        assert "secret changed: providers.b.api_key" in lines
        assert all("old-secret-value" not in line and "new-secret-value" not in line
                   for line in lines)
        assert "image_generation.backends: removed entries ['b']" in config_history.diff_layers(
            {"image_generation": {"backends": [{"name": "b"}]}}, {}, {}, {})
        print("PASS K: named entries and secret paths are diffed without values")

        recovery = fixture("recovery")
        saved = config.snapshot_layer(recovery)
        current = (b'{"server":{"timezone":"UTC"}}', b'{"key":"current"}')
        (recovery / "config.json").write_bytes(current[0])
        (recovery / "secrets.json").write_bytes(current[1])
        pid_file = root / "main.pid"
        pid_file.write_text(str(os.getpid()))
        snapshots_before = config.list_snapshots(recovery)
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            assert config_history.restore(recovery, saved.name, pid_file) == 2
        assert "stop the server first (./start.sh --stop)" in output.getvalue()
        assert config.list_snapshots(recovery) == snapshots_before
        assert ((recovery / "config.json").read_bytes(),
                (recovery / "secrets.json").read_bytes()) == current
        print("PASS L: live PID refuses restore without changing files or history")

        child = subprocess.Popen(["timeout", "60", sys.executable, "-c", "pass"])
        child.wait(timeout=60)
        pid_file.write_text(str(child.pid))
        assert config_history.restore(recovery, saved.name, pid_file) == 0
        snapshots_after = config.list_snapshots(recovery)
        overwritten = next(s for s in snapshots_after if s not in snapshots_before)
        assert ((overwritten / "config.json").read_bytes(),
                (overwritten / "secrets.json").read_bytes()) == current
        for name, expected in zip(("config.json", "secrets.json"), before):
            assert (recovery / name).read_bytes() == expected
            assert stat.S_IMODE((recovery / name).stat().st_mode) == 0o600
        print("PASS M: stale PID allows exact restore after backing up current files")

        (recovery / "secrets.json").unlink()
        config_only = config.snapshot_layer(recovery)
        (recovery / "secrets.json").write_bytes(current[1])
        assert config_history.restore(recovery, config_only.name, pid_file) == 0
        assert not (recovery / "secrets.json").exists()
        assert (recovery / "config.json").read_bytes() == before[0]
        print("PASS N: config-only restore removes current secrets")
    print("OK — config history: A-N passed")


if __name__ == "__main__":
    main()
