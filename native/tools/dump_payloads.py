#!/usr/bin/env python3
"""Dump the HTTP bodies the native client reads, from a COPY of a world, offline.

The native client (``native/``) is checked against the user's real world without
touching it: this tool opens a COPY of a world directory through the FastAPI app
itself (``TestClient(app)``, no lifespan — no agent loop, no scheduler, no LLM,
no task queue), logs in as a temporary player and writes exactly the answers the
client would get into an output directory laid out like ``native/fixtures/``, so
``FixtureSource`` can serve it: ``--offline=<dir>``.

Usage:
    ./.venv/bin/python native/tools/dump_payloads.py --world <COPY of a world dir> --out <dump dir> [--as-user NAME]

    --world   a COPY (a sqlite backup of world.db plus config.json, locations/,
              props/, door_models/, items/). The tool writes into it (a temporary
              user + its session, the app's boot migrations), so it refuses any
              directory inside the repository's worlds/.
    --as-user NAME  mirror that user of the copy: the temporary player gets its role,
              allowed characters and active character, so the fogged world map
              (§ A12) is the one that user's client sees. Without it the player
              has no avatar and the world map lists no locations.
    --out     the dump directory; refused inside the repository (the user's
              world content must never land in git). Created if missing.

What is written (names as ``native/fixtures/`` uses them, see
``native/Check/FixtureSource.cs``):

    heightfield.json            GET /play/heightfield
    tiles.json                  every indexed tile of /play/heightfield/tiles, merged
    worldmap.json               GET /play/worldmap (the fogged player view)
    locations.json              GET /world/locations?view=3d
    scene_<id>.json             GET /play/locations/<id>/scene (absent = 404)
    model_meta_<id>.json        GET /play/locations/<id>/model/meta (not read by the client)
    terrain.json                GET /play/terrain
    terrain_layers.json         GET /play/terrain-layers (the index)
    terrain_layers_tiles.json   every indexed tile of /play/terrain-layers?keys=…, merged
    surface_textures.json       GET /assets/surface-textures
    animation_clips.json        GET /assets/animation-clips
    model3d.json                GET /characters/<name>/model3d per world-map character (null = 404)
    urls.json + bin/            every binary URL those payloads name (models in every
                                tier and variant, surface images, the idle/walk clips)
    summary.json                counts of the dump

Binary bodies are HARD LINKS to the served file when it lies in the copy (the
same bytes at no disk cost), else written out. The server's background builders
are switched off for the run: no Meshopt delivery copies (the source GLB is served,
which the native loader reads as well), no on-demand distance meshes, no door/window
mesh builds (a missing door mesh stays missing, as on a server whose build is pending).
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import sys
import tempfile
from urllib.parse import quote

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

HEIGHT_BATCH = 64
LAYER_BATCH = 16
PLAYER = "native-dump"


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--world", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--as-user", default="")
    args = ap.parse_args()
    world, out = args.world.resolve(), args.out.resolve()
    if not (world / "world.db").is_file():
        sys.exit(f"--world {world}: no world.db there")
    if _inside(world, REPO / "worlds"):
        sys.exit(f"--world {world}: refusing a world inside the repository — pass a COPY")
    if _inside(out, REPO):
        sys.exit(f"--out {out}: refusing a dump inside the repository (world content stays out of git)")
    out.mkdir(parents=True, exist_ok=True)
    (out / "bin").mkdir(exist_ok=True)

    instance = Path(tempfile.mkdtemp(prefix="native-dump-instance-"))
    try:
        return dump(world, out, instance, args.as_user)
    finally:
        shutil.rmtree(instance, ignore_errors=True)


def dump(world: Path, out: Path, instance: Path, as_user: str) -> int:
    # CLAUDE.md: paths.init BEFORE any world-DB module; app.server needs both env vars.
    os.environ["STORAGE_DIR"] = str(world)
    os.environ["INSTANCE_DIR"] = str(instance)
    from app.core import paths
    paths.init(world)
    from app.server import app  # noqa: E402  (boot: config, schema, migrations on the COPY)
    from app.core import users, glb_delivery, door_models
    from app.blender import refine
    from fastapi.testclient import TestClient
    import starlette.responses as sr

    # Background builders off (see the docstring).
    glb_delivery.delivery_path = lambda p: p
    refine.auto_lod_enabled = lambda: False

    def _no_blender(*_a, **_k):
        raise RuntimeError("dump_payloads: no Blender builds")
    door_models.build_door_model = _no_blender
    if hasattr(door_models, "build_window_model"):
        door_models.build_window_model = _no_blender

    # Which file a response served: requests run one after another, so one slot is enough.
    served = {"path": None}
    orig_init = sr.FileResponse.__init__

    def _rec_init(self, path, *a, **k):
        served["path"] = Path(path)
        orig_init(self, path, *a, **k)
    sr.FileResponse.__init__ = _rec_init

    password = secrets.token_urlsafe(18)
    existing = users.get_user_by_username(PLAYER)
    if existing:
        users.delete_user(existing["id"])
    role, allowed, settings = "user", [], {}
    if as_user:
        model = users.get_user_by_username(as_user)
        if not model:
            sys.exit(f"--as-user {as_user}: no such user in the copy")
        role, allowed = model["role"], model.get("allowed_characters") or []
        settings = {k: v for k, v in (model.get("settings") or {}).items()
                    if k in ("active_character", "current_character", "default_character")}
    uid = users.create_user(PLAYER, password, role=role, allowed_characters=allowed)
    if settings:
        users.update_user(uid, settings=settings)
    try:
        client = TestClient(app)
        r = client.post("/auth/login", json={"username": PLAYER, "password": password})
        if r.status_code != 200:
            sys.exit(f"login failed: {r.status_code} {r.text[:200]}")
        return _dump_all(client, out, world, served)
    finally:
        users.delete_user(uid)


def _get(client, path):
    r = client.get(path)
    if r.status_code != 200:
        raise RuntimeError(f"GET {path} -> {r.status_code}: {r.text[:200]}")
    return r.json()


def _write(out: Path, name: str, data) -> int:
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    (out / name).write_bytes(raw)
    return len(raw)


def _model_urls(spec: dict) -> list:
    urls = []
    for v in (spec.get("variants") or {}).values():
        if isinstance(v, str) and v:
            urls.append(v)
    for mv in spec.get("model_variants") or []:
        if isinstance(mv, dict):
            urls.extend(v for v in mv.values() if isinstance(v, str) and v)
    return urls


def _dump_all(client, out: Path, world: Path, served: dict) -> int:
    summary = {}
    hf = _get(client, "/play/heightfield")
    summary["heightfield_bytes"] = _write(out, "heightfield.json", hf)

    keys = list(hf.get("tiles") or [])
    tiles = {}
    meta = {"sig": hf.get("sig", ""), "tile_m": hf.get("tile_m", 256), "step_m": hf.get("tile_step_m", 2)}
    for i in range(0, len(keys), HEIGHT_BATCH):
        q = ",".join(k.replace(",", ":") for k in keys[i:i + HEIGHT_BATCH])
        batch = _get(client, "/play/heightfield/tiles?keys=" + quote(q))
        meta.update({k: batch[k] for k in ("sig", "tile_m", "step_m") if k in batch})
        tiles.update(batch.get("tiles") or {})
    summary["height_tiles"] = len(tiles)
    summary["tiles_bytes"] = _write(out, "tiles.json", {**meta, "tiles": tiles})

    wm = _get(client, "/play/worldmap")
    _write(out, "worldmap.json", wm)
    summary["avatar"] = wm.get("avatar")
    summary["worldmap_locations"] = len(wm.get("locations") or [])
    summary["world_props"] = len(wm.get("world_props") or [])
    _write(out, "locations.json", _get(client, "/world/locations?view=3d"))

    urls = []
    scenes = 0
    for loc in wm.get("locations") or []:
        lid = loc.get("id")
        if not lid:
            continue
        r = client.get(f"/play/locations/{quote(lid)}/scene")
        if r.status_code == 200:
            scene = r.json()
            _write(out, f"scene_{lid}.json", scene)
            scenes += 1
            for spec in scene.get("models") or []:
                urls.extend(_model_urls(spec))
        elif r.status_code != 404:
            raise RuntimeError(f"scene {lid} -> {r.status_code}: {r.text[:200]}")
        r = client.get(f"/play/locations/{quote(lid)}/model/meta")
        if r.status_code == 200:
            _write(out, f"model_meta_{lid}.json", r.json())
    summary["scenes"] = scenes
    for wp in wm.get("world_props") or []:
        urls.extend(_model_urls(wp))

    terrain = _get(client, "/play/terrain")
    _write(out, "terrain.json", terrain)
    for area in terrain.get("areas") or []:
        for row in ((area.get("meta") or {}).get("scatter") or []):
            if isinstance(row, dict):
                urls.extend(_model_urls(row))

    index = _get(client, "/play/terrain-layers")
    _write(out, "terrain_layers.json", index)
    lkeys = list(index.get("tile_keys") or [])
    merged = None
    for i in range(0, len(lkeys), LAYER_BATCH):
        q = ",".join(k.replace(",", ":", 1) for k in lkeys[i:i + LAYER_BATCH])
        batch = _get(client, "/play/terrain-layers?keys=" + quote(q))
        if merged is None:
            merged = {k: v for k, v in batch.items() if k != "tiles"}
            merged["tiles"] = {}
        merged["tiles"].update(batch.get("tiles") or {})
    if merged is None:
        merged = {"tiles": {}}
    summary["layer_tiles"] = len(merged["tiles"])
    summary["layer_tiles_bytes"] = _write(out, "terrain_layers_tiles.json", merged)

    textures = _get(client, "/assets/surface-textures")
    _write(out, "surface_textures.json", textures)
    for t in textures if isinstance(textures, list) else []:
        if isinstance(t, dict) and isinstance(t.get("url"), str) and t["url"]:
            urls.append(t["url"])

    clips = _get(client, "/assets/animation-clips")
    _write(out, "animation_clips.json", clips)
    # The client loads the idle/walk clips through the locomotion mapping (Figures/ClipLibrary.cs) and
    # retargets them against the reference rig.
    loco = set((clips.get("locomotion") or {}).values()) | {"idle", "walk"}
    for c in clips.get("clips") or []:
        if isinstance(c, dict) and c.get("kind") in loco and c.get("url"):
            urls.append(c["url"])
    urls.append("/assets/animation-rig")

    model3d = {}
    for ch in wm.get("characters") or []:
        name = ch.get("name")
        if not name:
            continue
        r = client.get(f"/characters/{quote(name)}/model3d")
        model3d[name] = r.json() if r.status_code == 200 else None
        if r.status_code == 200 and isinstance(model3d[name], dict) and model3d[name].get("url"):
            urls.append(model3d[name]["url"])
    _write(out, "model3d.json", model3d)
    summary["characters"] = len(model3d)
    summary["character_models"] = sum(1 for v in model3d.values() if v)

    url_map, linked, written, missing, total = {}, 0, 0, [], 0
    for url in dict.fromkeys(urls):
        served["path"] = None
        r = client.get(url)
        if r.status_code != 200:
            missing.append(f"{url} -> {r.status_code}")
            continue
        body = r.content
        total += len(body)
        ext = Path(url.split("?")[0]).suffix or ".bin"
        name = "bin/" + hashlib.sha1(url.encode("utf-8")).hexdigest()[:20] + ext
        target = out / name
        if target.exists():
            target.unlink()
        src = served["path"]
        if src is not None and _inside(src, world) and src.is_file() and src.stat().st_size == len(body):
            os.link(src, target)
            linked += 1
        else:
            target.write_bytes(body)
            written += 1
        url_map[url] = name
    _write(out, "urls.json", url_map)
    summary.update(binary_urls=len(url_map), binary_linked=linked, binary_written=written,
                   binary_bytes=total, binary_missing=len(missing))
    _write(out, "summary.json", {**summary, "missing": missing})
    print("dump:", json.dumps(summary, ensure_ascii=False))
    for m in missing[:20]:
        print("  missing:", m)
    return 0


if __name__ == "__main__":
    sys.exit(main())
