"""Give regenerated images back the reference images they were first rendered with.

Usage:
    ./.venv/bin/python scripts/restore_regen_references.py --storage "worlds/<world>" [--apply]
        [--log logs/image_prompts.jsonl]

Before 2026-11-01 a regenerate resolved every person's reference image LIVE
(the character's current outfit) and wrote those new references over the
image's ``reference_images`` — so the next regenerate could no longer find
the outfit/nudity of the original moment. Since then a regenerate keeps the
source image's references (app/imagegen/source_refs.py), but only from what
the meta still names.

This script restores the names from the image log: for every gallery or
Instagram meta with ``regenerated_at`` it looks for the log entry of the
FIRST render — same creator (``service`` = gallery owner or
``from_character``), ``endtime`` within 2 seconds of the meta's
``created_at``, no error, references present. Exactly one such entry is
required; anything ambiguous is reported and left alone. A restored meta
gets the logged ``reference_images`` and loses ``reference_paths`` (those
named the overwritten files); a regenerate then finds the files by name.

Only the JSON sidecars are read and written — no world DB, no server module.
Default is a dry run; ``--apply`` writes. The log only reaches back as far as
it was kept, so older images stay as they are.
"""
import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_SLACK = timedelta(seconds=2)


def _parse(stamp):
    try:
        dt = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        return None  # a naive local stamp cannot be matched against the UTC log
    return dt


def _load_log(path: Path):
    by_service = {}
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if entry.get("error") or not entry.get("reference_images"):
                continue
            end = _parse(entry.get("endtime") or "")
            if end is None:
                continue
            by_service.setdefault(entry.get("service") or "", []).append((end, entry))
    return by_service


def _metas(storage: Path):
    for f in sorted(storage.glob("characters/*/images/*.json")):
        yield f, f.parent.parent.name
    for f in sorted(storage.glob("instagram/*.json")):
        yield f, ""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--storage", required=True, help="the world directory")
    ap.add_argument("--log", default=str(ROOT / "logs" / "image_prompts.jsonl"))
    ap.add_argument("--apply", action="store_true", help="write the restored metas")
    args = ap.parse_args()
    storage = Path(args.storage).resolve()
    if not (storage / "characters").is_dir():
        print(f"no characters/ under {storage}")
        return 2
    log = _load_log(Path(args.log))

    restored = unchanged = ambiguous = missing = 0
    for meta_path, owner in _metas(storage):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(meta, dict) or not meta.get("regenerated_at"):
            continue
        created = _parse(meta.get("created_at") or "")
        if created is None:
            missing += 1
            continue
        services = {s for s in (owner, meta.get("from_character") or "",
                                meta.get("character") or "") if s}
        if not owner:  # Instagram: the poster is not in the path
            services |= set(meta.get("character_names") or [])
        hits = [e for s in services for end, e in log.get(s, [])
                if abs(end - created) <= _SLACK]
        if not hits:
            missing += 1
            continue
        if len(hits) > 1:
            ambiguous += 1
            print(f"  ambiguous ({len(hits)} log entries): {meta_path.relative_to(storage)}")
            continue
        refs = hits[0]["reference_images"]
        if refs == meta.get("reference_images") and "reference_paths" not in meta:
            unchanged += 1
            continue
        restored += 1
        print(f"  {meta_path.relative_to(storage)}")
        print(f"      now:      {sorted((meta.get('reference_images') or {}).values())}")
        print(f"      restored: {sorted(refs.values())}")
        if args.apply:
            meta["reference_images"] = refs
            meta.pop("reference_paths", None)
            meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n{'restored' if args.apply else 'would restore'}: {restored}, already right: {unchanged}, "
          f"ambiguous: {ambiguous}, no log entry: {missing}")
    if not args.apply and restored:
        print("dry run — pass --apply to write")
    return 0


if __name__ == "__main__":
    sys.exit(main())
