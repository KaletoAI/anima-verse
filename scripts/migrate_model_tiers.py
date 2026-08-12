#!/usr/bin/env python3
"""ONE-SHOT migration to the tier-aware model gallery (plan-3d-lod-und-betreten.md).

Filesystem only — no world.db is opened (the server may be running).

Two conversions per world storage dir:

1. ``props/<id>/model.glb`` (fixed name) → ``model_<ts>.glb`` + a per-model
   sidecar (tier ``full``) + a ``selection.json`` entry. The per-run fields
   (``backend``/``face_num``/``texture_size``) MOVE from the prop master
   record (``sidecar.json``) onto the model sidecar, where they belong now.
2. ``locations/<id>/model3d/selection.json``: the old ``{stem: "<file>"}``
   format becomes ``{stem: {"full": "<file>"}}``. Location/room model files
   that no selection names get an explicit ``full`` entry, so the store never
   has to guess. A ``__none__`` value stays ``{"full": "__none__"}``.

Usage:  ./.venv/bin/python scripts/migrate_model_tiers.py [--apply] [PATH ...]
        (default PATHs: worlds/* and storage/, dry-run without --apply)
"""
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEL_FILE = "selection.json"
SEL_NONE = "__none__"
FULL = "full"
MODEL_EXTS = (".fbx", ".glb", ".gltf", ".obj", ".ply", ".vrm")


def _load(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _dump(p: Path, data, apply: bool) -> None:
    if apply:
        p.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                     encoding="utf-8")


def migrate_props(storage: Path, apply: bool, stats: dict) -> None:
    d = storage / "props"
    if not d.is_dir():
        return
    for prop in sorted(p for p in d.iterdir() if p.is_dir()):
        master_path = prop / "sidecar.json"
        old_model = prop / "model.glb"
        master = _load(master_path)
        if not isinstance(master, dict):
            continue
        if not old_model.exists():
            stats["props_no_model"] += 1
            continue
        ts = int(old_model.stat().st_mtime)
        target = prop / f"model_{ts}.glb"
        while target.exists():
            ts += 1
            target = prop / f"model_{ts}.glb"
        meta = {
            # The MESH's own timestamp (the master record's created_at is the
            # prop record's, which usually predates the mesh) — it is what the
            # gallery sorts by.
            "created_at": datetime.fromtimestamp(
                old_model.stat().st_mtime, timezone.utc).isoformat(),
            "source": master.get("source") or "generated",
            "format": "glb",
            "rig": "none",
            "tier": FULL,
        }
        for key in ("backend", "face_num", "texture_size"):
            if master.get(key) not in (None, "", 0):
                meta[key] = master.pop(key)
            else:
                master.pop(key, None)
        print(f"    prop {prop.name}: model.glb -> {target.name} "
              f"(backend={meta.get('backend', '')!r})")
        if apply:
            old_model.rename(target)
            (prop / f"model_{ts}.json").write_text(
                json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
            _dump(prop / SEL_FILE, {"model": {FULL: target.name}}, apply)
            _dump(master_path, master, apply)
        stats["props"] += 1


def migrate_locations(storage: Path, apply: bool, stats: dict) -> None:
    d = storage / "locations"
    if not d.is_dir():
        return
    for loc in sorted(p for p in d.iterdir() if p.is_dir()):
        mdir = loc / "model3d"
        if not mdir.is_dir():
            continue
        sel_path = mdir / SEL_FILE
        sel = _load(sel_path) if sel_path.exists() else {}
        out = {}
        for stem, value in (sel or {}).items():
            out[stem] = {FULL: value} if isinstance(value, str) else (
                value if isinstance(value, dict) else {})
        before = json.dumps(sel or {}, sort_keys=True)
        # Files nobody selected: name them explicitly as the full tier (the
        # newest per stem wins, exactly what the store used to pick).
        by_stem = {}
        for f in mdir.iterdir():
            if not f.is_file() or f.suffix.lower() not in MODEL_EXTS:
                continue
            stem = f.name.rsplit(".", 1)[0]
            if "_" in stem and stem.rsplit("_", 1)[1].isdigit():
                stem = stem.rsplit("_", 1)[0]
            by_stem.setdefault(stem, []).append(f)
        for stem, files in by_stem.items():
            if out.get(stem, {}).get(FULL):
                continue
            newest = max(files, key=lambda f: f.stat().st_mtime)
            out.setdefault(stem, {})[FULL] = newest.name
            stats["stems_pinned"] += 1
        if json.dumps(out, sort_keys=True) == before:
            continue
        print(f"    {sel_path.relative_to(ROOT)}: {json.dumps(out)}")
        _dump(sel_path, out, apply)
        stats["selections"] += 1
        # A model sidecar without a tier is a full one — make it explicit so
        # the admin gallery can group by tier without guessing.
        for files in by_stem.values():
            for f in files:
                side = f.with_suffix(".json")
                meta = _load(side)
                if isinstance(meta, dict) and not meta.get("tier"):
                    meta["tier"] = FULL
                    _dump(side, meta, apply)
                    stats["sidecars"] += 1


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    apply = "--apply" in sys.argv
    targets = [Path(a).resolve() for a in args]
    if not targets:
        targets = sorted(p for p in (ROOT / "worlds").iterdir() if p.is_dir())
        if (ROOT / "storage").is_dir():
            targets.append(ROOT / "storage")
    print(f"{'APPLY' if apply else 'DRY RUN'} — {len(targets)} storage dir(s)")
    total = {"props": 0, "props_no_model": 0, "selections": 0,
             "stems_pinned": 0, "sidecars": 0}
    for storage in targets:
        print(f"  {storage}")
        stats = {k: 0 for k in total}
        migrate_props(storage, apply, stats)
        migrate_locations(storage, apply, stats)
        for k, v in stats.items():
            total[k] += v
        print(f"    -> {stats}")
    print(f"TOTAL {total}  ({time.strftime('%Y-%m-%d %H:%M:%S')})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
