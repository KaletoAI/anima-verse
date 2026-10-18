"""Smoke content revisions and three-way layer saves using temporary storage.

Usage: ./.venv/bin/python scripts/smoke_config_revision.py

Hand-derived expectations from plan-config-revision.md, Task 1:
A Identical pruned content hashes to the same 16 hex digits; changing the
  timezone changes the content and therefore the revision.
B A view's default enabled=True is unchanged relative to its base, so the
  foreign False survives alongside our new p2. Old-code proof: c131288a
  has no issue_revision, so this case cannot preserve a revision-based edit.
C Both sides choosing UTC agree and must save without conflict.
D UTC versus Asia/Tokyo changes the same unit differently: exactly
  server.timezone conflicts, and refusal must leave UTC bytes untouched.
E A masked key means the base key, not a new edit; foreign k2 survives while
  our independent timezone edit saves UTC.
F Reloading unchanged files preserves the content revision: an empty cache
  cannot prevent a save on the equal-revision fast path.
G Reloading changed content with no cached base refuses unknown_base with
  no conflict paths and no file writes.
H Disjoint timezone/provider edits from two threads both survive; two
  different timezone edits yield exactly one success and one conflict.
I game_seasons is one top-level list unit, independent of chat.top_p;
  editing both from the same base retains both foreign and own changes.
J routing is one image_generation.routing unit; removing an occasion
  replaces that subtree, so the removed occasion cannot reappear.
K A stale page resetting server.timezone after a foreign save stored UTC
  there conflicts on exactly server.timezone and leaves UTC; the same stale
  page resetting it when the foreign save touched only providers succeeds
  and drops the stored timezone (no shipped default stays in the file).
"""
import ast
import copy
import json
import os
from pathlib import Path
import re
import sys
import subprocess
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

with tempfile.TemporaryDirectory(prefix="config-revision-") as root:
    world = Path(root) / "world"
    instance = Path(root) / "instance"
    world.mkdir()
    instance.mkdir()
    os.environ["STORAGE_DIR"] = str(world)
    os.environ["INSTANCE_DIR"] = str(instance)
    from app.core import paths
    paths.init(world)
    paths.init_instance(instance)
    from app.core import config, config_admin as adm, config_scope

    # Service reloads may contact providers; this smoke tests persistence only.
    def reloads(keys, scope):
        assert not config._LOCK._is_owned(), "service reload under config lock"
        return []

    adm.apply_section_reloads = reloads
    seed = {"providers": [{"name": "p1", "api_key": "k1"}],
            "image_generation": {"backends": [{"name": "b1", "api_type": "openai_diffusion"}],
                                 "routing": {"profile": ["b1"]}},
            "server": {"timezone": "Europe/Berlin"}}

    def clear_cache():
        adm._REVISION_CACHE.clear()

    def load():
        for directory in (world, instance):
            (directory / "secrets.json").unlink(missing_ok=True)
        (instance / "config.json").write_text(json.dumps(seed))
        (world / "config.json").write_text(json.dumps({"game_seasons": [{"name": "warm", "days": 20}]}))
        config.load(world / "config.json", instance / "config.json")

    def issued(scope="instance"):
        with config._LOCK:
            return adm.issue_revision(scope), adm.layer_view(scope)

    def stored(scope="instance"):
        return json.loads(((instance if scope == "instance" else world) / "config.json").read_text())

    def foreign_timezone(value):
        view = adm.layer_view("instance")
        view["server"]["timezone"] = value
        adm.save_layer("instance", view)

    def snapshot():
        return {str(p): p.read_bytes() for directory in (instance, world)
                for p in directory.glob("*.json")}

    def stale(fn, expected, reason="conflict"):
        before = snapshot()
        try:
            fn()
        except adm.LayerStale as exc:
            assert exc.paths == expected, exc.paths
            assert exc.reason == reason, exc.reason
        else:
            raise AssertionError("expected LayerStale")
        assert snapshot() == before

    load()
    r0, view0 = issued()
    assert issued()[0] == r0 and re.fullmatch(r"[0-9a-f]{16}", r0)
    foreign_timezone("UTC")
    assert issued()[0] != r0
    print("PASS A")

    # Pin the old-code proof to the pre-revision implementation, never HEAD.
    old_source = subprocess.run(
        ["timeout", "300", "git", "show", "c131288a:app/core/config_admin.py"],
        check=True, capture_output=True, text=True).stdout
    assert not any(isinstance(node, ast.FunctionDef) and node.name == "issue_revision"
                   for node in ast.parse(old_source).body), "B: old code already issues revisions"
    load()
    r0, view0 = issued()
    assert view0["image_generation"]["enabled"] is True
    adm.set_media_switch(False)
    view0["providers"].append({"name": "p2"})
    result = adm.save_layer("instance", view0, base_revision=r0)
    assert [p["name"] for p in stored()["providers"]] == ["p1", "p2"]
    assert stored()["image_generation"]["enabled"] is False
    assert result["revision"] == adm.layer_revision("instance")
    print("PASS B")

    for case, timezone in (("C", "UTC"), ("D", "Asia/Tokyo")):
        load()
        r0, view0 = issued()
        foreign_timezone("UTC")
        view0["server"]["timezone"] = timezone
        if case == "C":
            adm.save_layer("instance", view0, base_revision=r0)
        else:
            stale(lambda: adm.save_layer("instance", view0, base_revision=r0), ["server.timezone"])
        assert stored()["server"]["timezone"] == "UTC"
        print("PASS", case)

    load()
    r0, view0 = issued()
    foreign = adm.layer_view("instance")
    foreign["providers"][0]["api_key"] = "k2"
    adm.save_layer("instance", foreign)
    view0["providers"][0]["api_key"] = "***"
    view0["server"]["timezone"] = "UTC"
    adm.save_layer("instance", view0, base_revision=r0)
    secrets = json.loads((instance / "secrets.json").read_text())
    assert secrets["providers"]["p1"]["api_key"] == "k2", secrets
    assert stored()["server"]["timezone"] == "UTC"
    print("PASS E")

    load()
    r0, view0 = issued()
    config.load(world / "config.json", instance / "config.json")
    clear_cache()
    assert adm.layer_revision("instance") == r0
    view0["server"]["timezone"] = "UTC"
    adm.save_layer("instance", view0, base_revision=r0)
    assert stored()["server"]["timezone"] == "UTC"
    print("PASS F")

    load()
    r0, view0 = issued()
    foreign_timezone("UTC")
    config.load(world / "config.json", instance / "config.json")
    clear_cache()
    stale(lambda: adm.save_layer("instance", view0, base_revision=r0), [], "unknown_base")
    print("PASS G")

    def concurrent(views, revision):
        barrier = threading.Barrier(2)
        def save(view):
            barrier.wait(timeout=10)
            try:
                return adm.save_layer("instance", view, base_revision=revision)
            except adm.LayerStale as exc:
                return exc
        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(save, views))

    load()
    r0, first = issued()
    second = copy.deepcopy(first)
    first["server"]["timezone"] = "UTC"
    second["providers"].append({"name": "p3"})
    assert all(isinstance(r, dict) for r in concurrent([first, second], r0))
    assert stored()["server"]["timezone"] == "UTC"
    assert [p["name"] for p in stored()["providers"]] == ["p1", "p3"]
    r0, first = issued()
    second = copy.deepcopy(first)
    first["server"]["timezone"] = "Asia/Tokyo"
    second["server"]["timezone"] = "America/New_York"
    results = concurrent([first, second], r0)
    assert sum(isinstance(r, dict) for r in results) == 1
    failure = next(r for r in results if isinstance(r, adm.LayerStale))
    assert failure.paths == ["server.timezone"] and failure.reason == "conflict"
    winner = "Asia/Tokyo" if isinstance(results[0], dict) else "America/New_York"
    assert stored()["server"]["timezone"] == winner
    print("PASS H")

    load()
    r0, view0 = issued("world")
    foreign = adm.layer_view("world")
    foreign.setdefault("chat", {})["top_p"] = 0.37
    adm.save_layer("world", foreign)
    view0["game_seasons"] = [{"name": "cold", "days": 30}]
    adm.save_layer("world", view0, base_revision=r0)
    assert stored("world")["chat"]["top_p"] == 0.37
    assert stored("world")["game_seasons"] == [{"name": "cold", "days": 30}]
    print("PASS I")

    base = {"image_generation": {"routing": {"profile": ["b1"], "scene": ["b1"]}}}
    own = copy.deepcopy(base)
    del own["image_generation"]["routing"]["profile"]
    result = adm.rebase_layer("instance", own, base, copy.deepcopy(base))
    assert result == {"image_generation": {"routing": {"scene": ["b1"]}}}
    assert adm.change_units(base) == {"image_generation.routing": base["image_generation"]["routing"]}
    assert config_scope.prune({"image_generation": {"lora_triggers": [{"name": "virtual"}]}}) == {}
    print("PASS J")

    load()
    r0, view0 = issued()
    foreign_timezone("UTC")
    try:
        adm.save_layer("instance", view0, resets=["server.timezone"], base_revision=r0)
    except adm.LayerStale as exc:
        assert exc.paths == ["server.timezone"] and exc.reason == "conflict"
    else:
        raise AssertionError("K: stale reset overwrote a foreign edit")
    assert stored()["server"]["timezone"] == "UTC"
    load()
    r0, view0 = issued()
    foreign = adm.layer_view("instance")
    foreign["providers"].append({"name": "p9"})
    adm.save_layer("instance", foreign)
    adm.save_layer("instance", view0, resets=["server.timezone"], base_revision=r0)
    assert "timezone" not in stored().get("server", {})
    assert [p["name"] for p in stored()["providers"]] == ["p1", "p9"]
    print("PASS K")
    print("ALL OK")
