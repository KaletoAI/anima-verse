#!/usr/bin/env python3
"""One-time: re-sign stored expression images whose body-slot EXPOSURE did not change.

Background (2026-11-12). Until 5e908226 the expression render contract
(``expression_regen._framing_basis``) carried each framed body slot's ``covered_by``
DECLARATION; it now carries the EFFECT (which framed body slots are exposed under the
rendered outfit and its open / closed pieces). In the same round a species package
widened a ``covered_by`` declaration and the core started to honour a covering piece's
``covers``. Both change every stored contract once, although only the images whose
exposure really changed are wrong. This script proves, image by image, that nothing but
the representation changed and re-signs those images under the new contract; it never
touches any other image.

An image is re-signed only when ALL hold:
  1. its stored contract equals the contract recomputed with the PREVIOUS basis
     (declaration list) and the previous declarations named by ``--old-covered-by``
     — so the LoRA, prompt, framing, style, size, matte and base did not drift;
  2. the framed body slots exposed under the PREVIOUS rule (a covering piece counts only
     on a clothing slot of the previous ``covered_by``; ``covers`` ignored; an open piece
     covers nothing) equal those exposed now (``body_slots.is_slot_exposed``);
  3. its canonical target file does not exist yet.
Re-signing copies the image to its canonical name for the new contract, writes the
sidecar with the new ``contract`` and ``identity`` and then removes the old pair (the
bytes and ``content_version`` stay). Everything else is reported and left alone; a
stale image re-renders on its next use as before.

Usage (server STOPPED — the script refuses while a process holds the world's world.db):
    ./.venv/bin/python scripts/migrate_expression_exposure.py --storage worlds/<world> \\
        --old-covered-by <body slot>=<clothing slot>,<clothing slot> [...] [--instance instance] [--apply]

Without ``--apply`` it only reports. Each ``--old-covered-by`` names one body slot's
declaration as it was before the change (a slot not named keeps its current declaration).
"""
import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


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


def _parse_old(values):
    old = {}
    for raw in values or []:
        slot, _, covers = raw.partition("=")
        if not slot.strip() or not covers.strip():
            raise SystemExit(f"--old-covered-by needs <body slot>=<clothing slots>: {raw!r}")
        old[slot.strip()] = [c.strip() for c in covers.split(",") if c.strip()]
    return old


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--storage", required=True, type=Path)
    ap.add_argument("--instance", type=Path, default=ROOT / "instance")
    ap.add_argument("--old-covered-by", action="append", default=[])
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    storage, instance = args.storage.resolve(), args.instance.resolve()
    old_decl = _parse_old(args.old_covered_by)
    if not old_decl:
        raise SystemExit("name at least one --old-covered-by")
    if not (storage / "world.db").is_file():
        raise SystemExit(f"no world.db in {storage}")
    holders = _world_db_holders(storage / "world.db")
    if holders:
        raise SystemExit(f"world.db is open by pid(s) {holders} — stop the server first")

    os.environ["STORAGE_DIR"], os.environ["INSTANCE_DIR"] = str(storage), str(instance)
    from app.core import paths
    paths.init(storage)
    paths.init_instance(instance)
    from app.core import config
    config.load(storage / "config.json")
    # The enabled packages' manifests only (no on_load code, no task side effects):
    # the body-slot declarations are all the contract reads.
    from app.plugins import registry
    from app.plugins.loader import PLUGIN_DIR, _collect_packages
    enabled = frozenset(p.strip() for p in (config.get("packages.enabled", "") or "").split(",") if p.strip())
    registry.clear_registry()
    for pkg in _collect_packages(PLUGIN_DIR, warn=False, enabled_ids=enabled):
        registry.register_package(pkg)

    from app.core import expression_regen as er
    from app.core.body_slots import is_slot_exposed, portrait_piece_slots
    from app.core.db import get_connection
    from app.core.expression_sets import catalog_snapshot, set_for_character, ExpressionSetError
    from app.core.http_files import content_version
    from app.core.outfit_renderer import covering_pieces, is_free_text_wardrobe, is_outfit_worn
    from app.models.character import get_character_profile

    def previous_basis(profile, framing):
        # The basis of the contract before 5e908226, with the previous declarations.
        profile = dict(profile or {})
        slots = er.framing_slots(profile, framing)
        return {"pieces": list(portrait_piece_slots(profile)) if framing == "upper_body" else [],
                "slots": sorted([s.id, old_decl.get(s.id, s.covered_by), s.prompt] for s in slots)}

    def previously_exposed(spec, profile):
        # is_slot_exposed before 5e908226, with the previous declarations.
        covered_by = old_decl.get(spec.id, spec.covered_by)
        if not covered_by:
            return True
        if is_free_text_wardrobe(profile):
            return not is_outfit_worn(profile)
        worn = covering_pieces(profile, dict(profile.get("equipped_pieces") or {}))
        return not any(worn.get(slot) for slot in covered_by)

    cat = catalog_snapshot()
    counts = {}
    names = [r[0] for r in get_connection().execute("SELECT name FROM characters ORDER BY name")]
    for name in names:
        try:
            folder = er._get_expressions_dir(name)
        except ValueError:
            continue
        if not folder.is_dir():
            continue
        profile = dict(get_character_profile(name) or {})
        try:
            spec = set_for_character(name, profile=profile, catalog=cat)
        except ExpressionSetError:
            spec = None
        for image in sorted(folder.iterdir()):
            if image.suffix.lower() not in er._IMAGE_EXTS or image.is_symlink():
                continue
            sidecar = image.with_suffix(".json")
            try:
                meta = json.loads(sidecar.read_text())
            except (OSError, ValueError):
                continue
            if not isinstance(meta, dict) or meta.get("schema") != 2:
                continue
            sid, key = meta.get("expression_set"), meta.get("expression_key")
            if spec is None or sid != spec.id or key not in spec.members or not meta.get("contract"):
                verdict = "not in the selected set (untouched)"
            else:
                rendered = er.render_profile_of(profile, meta)
                framing = er.expression_framing(rendered)
                current = er.member_contract(cat, spec, key, framing, rendered)
                if meta["contract"] == current:
                    verdict = "current"
                else:
                    with patch.object(er, "_framing_basis", previous_basis):
                        previous = er.member_contract(cat, spec, key, framing, rendered)
                    slots = er.framing_slots(rendered, framing)
                    before = {s.id for s in slots if previously_exposed(s, rendered)}
                    now = {s.id for s in slots if is_slot_exposed(s, rendered)}
                    identity = er._digest({"version": 2, "set_id": sid, "expression_key": key,
                                           "outfit_raw": meta.get("outfit_raw"), "contract": current})
                    target = folder / f"{er._safe_name(name)}_{identity[:24]}{image.suffix}"
                    if meta["contract"] != previous:
                        verdict = "stale: contract drifted otherwise (untouched)"
                    elif before != now:
                        verdict = "stale: exposure changed (untouched)"
                        print(f"  {name}/{image.name}: exposed {sorted(before)} -> {sorted(now)}")
                    elif target.exists() or target.with_suffix(".json").exists():
                        verdict = "target exists (untouched)"
                    elif meta.get("content_version") != content_version(image):
                        verdict = "bytes do not match metadata (untouched)"
                    else:
                        verdict = "re-signed" if args.apply else "would re-sign"
                        if args.apply:
                            staged = folder / f".resign-{target.name}"
                            shutil.copy2(image, staged)
                            os.replace(staged, target)
                            new_meta = dict(meta, contract=current, identity=target.stem)
                            staged_meta = folder / f".resign-{target.stem}.json"
                            staged_meta.write_text(json.dumps(new_meta, ensure_ascii=False, indent=2))
                            os.replace(staged_meta, target.with_suffix(".json"))
                            image.unlink()
                            sidecar.unlink(missing_ok=True)
            counts[verdict] = counts.get(verdict, 0) + 1
    for verdict, n in sorted(counts.items()):
        print(f"{n:5d}  {verdict}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
