#!/usr/bin/env python3
"""One-time (Ruling A196): the full-body reference post-process becomes per-character checkboxes.

What changes for the stored data:
  1. The world default ``base_body.reference_postprocess`` (config.json of the world) is gone. A character that
     only followed it (no own value) gets those operations CHECKED explicitly — its current state, so nothing
     becomes outdated and no job is due; the script lists those characters and, with ``--apply``, removes the key
     from the world's config.json.
  2. A character's own ``False`` is dropped from its profile (unchecked = no entry); its own ``True`` stays.
  No other option is checked: an own ``True`` stays exactly that operation.

The descriptors come from the world's ENABLED packages (their manifests and ``on_load`` registration code only;
no task, no server, no network).

Usage (server STOPPED — refuses while another process holds the world's world.db):
    ./.venv/bin/python scripts/migrate_reference_postprocess_a196.py --storage worlds/<world> [--apply]

Without ``--apply`` it only reports.
"""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

WORLD_KEY = ("base_body", "reference_postprocess")


def _world_db_holders(db_path: Path):
    """PIDs (other than this one) with ``db_path`` open (Linux /proc)."""
    target = str(db_path.resolve())
    holders = []
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit() or int(proc.name) == os.getpid():
            continue
        try:
            for fd in (proc / "fd").iterdir():
                if os.readlink(fd) == target:
                    holders.append(int(proc.name))
                    break
        except OSError:
            continue
    return holders


def _world_default(cfg: dict) -> list:
    raw = (cfg.get(WORLD_KEY[0]) or {}).get(WORLD_KEY[1]) if isinstance(cfg.get(WORLD_KEY[0]), dict) else None
    if isinstance(raw, (list, tuple)):
        return [str(x).strip() for x in raw if str(x).strip()]
    return [x.strip() for x in str(raw or "").split(",") if x.strip()]


def plan_profile(profile: dict, available: dict, world: list) -> dict:
    """``{"choices": new {op: True} or None (unchanged), "followed_world": [ids checked from the default]}`` for one
    profile — pure, so the smoke checks it by hand."""
    from app.core import view_postprocess as vp
    raw = profile.get(vp.PROFILE_KEY)
    own = {str(k): bool(v) for k, v in raw.items()} if isinstance(raw, dict) else {}
    followed = [op for op in world if op not in own and op in available and vp.applies(available[op], profile)]
    new = {op: True for op, v in own.items() if v}
    new.update({op: True for op in followed})
    changed = new != (raw if isinstance(raw, dict) else {})
    return {"choices": new if changed else None, "followed_world": followed}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--storage", required=True, type=Path)
    ap.add_argument("--instance", type=Path, default=ROOT / "instance")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    storage, instance = args.storage.resolve(), args.instance.resolve()
    if not (storage / "world.db").is_file():
        raise SystemExit(f"no world.db in {storage}")
    holders = _world_db_holders(storage / "world.db")
    if holders:
        raise SystemExit(f"world.db is open by pid(s) {holders} — stop the server first")

    os.environ["STORAGE_DIR"], os.environ["INSTANCE_DIR"] = str(storage), str(instance)
    from app.core import paths
    paths.init(storage)
    cfg_path = storage / "config.json"
    world_cfg = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.is_file() else {}
    world = _world_default(world_cfg)
    # Missing = the shipped default "" = no package (config_schema packages.enabled).
    raw_enabled = (world_cfg.get("packages") or {}).get("enabled") or ""
    enabled = frozenset(p.strip() for p in str(raw_enabled).split(",") if p.strip())
    from app.plugins.loader import PLUGIN_DIR, _collect_packages, _run_on_load
    for pkg in _collect_packages(PLUGIN_DIR, warn=False, enabled_ids=enabled):
        rel = str(pkg.manifest.get("on_load", "") or "").strip()
        if rel:
            _run_on_load(pkg, rel)
    from app.core import view_postprocess as vp
    from app.core.db import get_connection
    from app.core.keyed_lock import keyed_lock
    from app.models.character import get_character_profile, save_character_profile
    available = vp.operations()
    print(f"world default {'.'.join(WORLD_KEY)}: {world or '(none)'}; options: {sorted(available)}")

    names = [r[0] for r in get_connection().execute("SELECT name FROM characters ORDER BY name")]
    for name in names:
        profile = get_character_profile(name) or {}
        plan = plan_profile(profile, available, world)
        if plan["followed_world"]:
            print(f"  {name} ({profile.get('gender') or '?'}): followed the world default "
                  f"{plan['followed_world']} — now checked explicitly")
        if plan["choices"] is None:
            continue
        print(f"  {name}: {profile.get(vp.PROFILE_KEY)} -> {plan['choices']}")
        if args.apply:
            with keyed_lock("character_profile", name):
                fresh = get_character_profile(name) or {}
                again = plan_profile(fresh, available, world)["choices"]
                if again is not None:
                    if again:
                        fresh[vp.PROFILE_KEY] = again
                    else:
                        fresh.pop(vp.PROFILE_KEY, None)
                    if not save_character_profile(name, fresh):
                        print(f"  {name}: SAVE FAILED")
    if args.apply and isinstance(world_cfg.get(WORLD_KEY[0]), dict) and WORLD_KEY[1] in world_cfg[WORLD_KEY[0]]:
        world_cfg[WORLD_KEY[0]].pop(WORLD_KEY[1])
        if not world_cfg[WORLD_KEY[0]]:
            world_cfg.pop(WORLD_KEY[0])
        cfg_path.write_text(json.dumps(world_cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"removed {'.'.join(WORLD_KEY)} from {cfg_path}")
    print("applied" if args.apply else "report only (no --apply)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
