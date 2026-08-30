"""Verify and clean the per-outfit render caches of one character.

Two caches key on the SAME signature (``model_refs.current_outfit_state``):

* ``characters/<name>/model_refs/`` — ``<kind>_<sig>.png`` plus a ``.json``
  sidecar, kinds ``tpose`` / ``pose`` plus the optional extra mesh views
  ``tpose_back`` / ``tpose_left`` / ``tpose_right`` (legacy:
  ``tpose_animal``);
* ``characters/<name>/model3d/`` — ``<sig>.glb|fbx`` plus ``<sig>.json`` and,
  for FBX, ``<sig>.png``.

Entries go stale when an outfit piece is deleted, or when the signature rule
changes (37f6328 collapsed covered pieces onto one signature). The hard part
is that a signature is an md5[:12]: NOTHING can be read back out of it.

So there are two ways to judge a cache entry, in this order:

1. **Manifest.** A sidecar that records the pieces it was rendered from is
   checked EXACTLY: every referenced item must still be in the inventory, and
   re-signing those pieces (which applies today's visibility normalisation)
   must reproduce the file name. This also covers entries with carried items,
   which the reachable set below can never contain. A sidecar that records
   NOTHING equipped belongs to a character dressed by free text
   (``outfit_description``, a temporary NPC) and re-signs against that text —
   an edited outfit line therefore leaves a detectable entry behind instead of
   a permanently "valid" one.
2. **Reachability.** Without a manifest, the only usable question is whether
   the signature is one that could still be produced at all — i.e. whether it
   lies in the set of signatures over the character's inventory
   (the outfit-batch enumeration). A legacy entry WITH carried items is
   therefore reported stale; that is deliberate and the dialog shows the
   number before anything is deleted — it regenerates on the next wear.

The worn combination is never reported stale, whatever the rules say.
"""

from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

from app.core.log import get_logger

logger = get_logger(__name__)

#: Enumerating the reachable set is lazy but not free. Above this many
#: combinations we refuse instead of hanging for minutes.
MAX_REACHABLE_COMBOS = 5_000_000
#: Longest first — otherwise "tpose_animal_<sig>" or "tpose_back_<sig>"
#: parses as kind "tpose" with a mangled signature.
REF_PREFIXES = ("tpose_animal_", "tpose_back_", "tpose_left_", "tpose_right_",
                "tpose_", "pose_")


def reachable_signatures(character_name: str) -> Set[str]:
    """Every pieces-only signature this character could still produce today.

    The cartesian product over their inventory, enumerated lazily through the
    outfit-batch machinery and collected as a SET — several piece sets can
    collapse onto one signature (covered pieces, 37f6328).

    Raises ValueError above ``MAX_REACHABLE_COMBOS`` rather than working for
    minutes; the caller turns that into a readable message.
    """
    from app.core.outfit_batch import (_iter_combos, _resolve_filter,
                                       _signature, combo_options, count_combos)
    options = combo_options(character_name)
    if not options:
        return set()
    choices, error = _resolve_filter(options, None)
    if error:
        raise ValueError(error)
    total = count_combos(choices)
    if total > MAX_REACHABLE_COMBOS:
        raise ValueError(
            f"{total:,} combinations — too many to verify the cache against "
            f"(limit {MAX_REACHABLE_COMBOS:,}). Reduce the inventory or clean "
            f"up by hand.")
    return {_signature(pieces, character_name) for pieces in _iter_combos(choices)}


def _sign(pieces: Dict[str, str], items: Optional[List[str]],
          character_name: str = "") -> str:
    """Re-sign a manifest with TODAY's rule (visibility normalisation
    included — that is what makes normalisation orphans detectable).

    ``character_name`` matters for a manifest that records NOTHING equipped:
    such an entry belongs to a character dressed by the free-text
    ``outfit_description`` (a temporary NPC), and the rule hashes that text
    (``model_refs.outfit_signature``). Without the name every empty manifest
    would re-sign to md5("") and the entries left behind by an edited outfit
    text would count as valid forever."""
    from app.core.model_refs import outfit_signature
    return outfit_signature(pieces, items or [], character_name)


def read_manifest(sidecar: Path) -> Optional[Dict[str, Any]]:
    """``{pieces, items}`` of a sidecar, or None when it records none.

    Two key spellings are accepted on purpose: the reference renders have
    always written ``equipped_pieces``/``equipped_items`` (the expression
    renderer's meta), the mesh sidecar writes ``pieces``/``items``. Same
    content, and neither is worth a migration.
    """
    import json
    if not sidecar.exists():
        return None
    try:
        meta = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(meta, dict):
        return None
    for pkey, ikey in (("pieces", "items"),
                       ("equipped_pieces", "equipped_items")):
        pieces = meta.get(pkey)
        if isinstance(pieces, dict):
            items = meta.get(ikey)
            return {"pieces": {str(k): str(v) for k, v in pieces.items() if v},
                    "items": [str(i) for i in (items or []) if i]}
    return None


def _inventory_ids(character_name: str) -> Set[str]:
    """Item ids the character still owns — a manifest referencing anything
    else describes a combination that cannot exist any more."""
    from app.models.inventory import get_character_inventory
    try:
        entries = (get_character_inventory(character_name) or {}).get("inventory") or []
    except Exception:
        logger.exception("Cache GC %s: inventory unreadable", character_name)
        return set()
    return {str(e.get("item_id") or "") for e in entries if e.get("item_id")}


def _entry_valid(signature: str, manifest: Optional[Dict[str, Any]],
                 owned: Set[str], reachable: Set[str],
                 character_name: str = "") -> bool:
    """The rule of this module, for one cache entry.

    State variants (``<base>-s<fp>``, model_refs.STATE_SIG_SEP) are judged
    by their outfit base: the state fingerprint is not reconstructible from
    the manifest, and a variant is worth keeping exactly as long as its
    outfit combination is."""
    from app.core.model_refs import neutral_signature
    base = neutral_signature(signature)
    if manifest is not None:
        used = set(manifest["pieces"].values()) | set(manifest["items"])
        if not used.issubset(owned):
            return False
        return _sign(manifest["pieces"], manifest["items"],
                     character_name) == base
    return base in reachable


def _ref_files(character_name: str) -> Dict[str, List[Path]]:
    """signature → its reference files (image + sidecar), by file name."""
    from app.core.model_refs import _IMAGE_EXTS
    from app.models.character import get_character_dir
    out: Dict[str, List[Path]] = {}
    d = get_character_dir(character_name) / "model_refs"
    if not d.exists():
        return out
    for p in sorted(d.iterdir()):
        if not p.is_file() or p.suffix.lower() not in _IMAGE_EXTS + (".json",):
            continue
        for prefix in REF_PREFIXES:
            if p.stem.startswith(prefix):
                out.setdefault(p.stem[len(prefix):], []).append(p)
                break
    return out


def _mesh_files(character_name: str) -> Dict[str, List[Path]]:
    """signature → its mesh files (model + sidecar + texture)."""
    from app.core.model3d import MODEL_EXTS
    from app.models.character import get_character_dir
    out: Dict[str, List[Path]] = {}
    d = get_character_dir(character_name) / "model3d"
    if not d.exists():
        return out
    for p in sorted(d.iterdir()):
        if p.is_file() and p.suffix.lower() in MODEL_EXTS + (".json", ".png"):
            out.setdefault(p.stem, []).append(p)
    return out


def _worn_signature(character_name: str) -> str:
    """The currently worn combination — protected from every rule below."""
    try:
        from app.core.model_refs import current_outfit_state
        return current_outfit_state(character_name)[2]
    except Exception:
        return ""


def _sidecar_of(files: Iterable[Path]) -> Optional[Path]:
    for p in files:
        if p.suffix.lower() == ".json":
            return p
    return None


def _bytes_of(files: Iterable[Path]) -> int:
    total = 0
    for p in files:
        try:
            total += p.stat().st_size
        except OSError:
            pass
    return total


def verify_cache(character_name: str) -> Dict[str, Any]:
    """Report on both caches:

    ``{refs: {total, valid, stale, stale_bytes}, meshes: {…},
    stale_signatures: [...], protected: [sig]}``

    Signature counts, not file counts — one signature owns an image and its
    sidecar. Raises ValueError when the reachable set is refused (see
    ``reachable_signatures``).
    """
    reachable = reachable_signatures(character_name)
    owned = _inventory_ids(character_name)
    worn = _worn_signature(character_name)

    stale: List[str] = []
    out: Dict[str, Any] = {"stale_signatures": stale,
                           "protected": [worn] if worn else []}
    for key, files_of in (("refs", _ref_files), ("meshes", _mesh_files)):
        groups = files_of(character_name)
        valid = 0
        stale_bytes = 0
        for signature, files in groups.items():
            if signature and signature == worn:
                valid += 1
                continue
            manifest = read_manifest(_sidecar_of(files) or Path("/nonexistent"))
            if _entry_valid(signature, manifest, owned, reachable,
                            character_name):
                valid += 1
                continue
            stale_bytes += _bytes_of(files)
            if signature not in stale:
                stale.append(signature)
        out[key] = {"total": len(groups), "valid": valid,
                    "stale": len(groups) - valid, "stale_bytes": stale_bytes}
    logger.info("Cache GC %s: refs %s, meshes %s, %d stale signature(s)",
                character_name, out["refs"], out["meshes"], len(stale))
    return out


def purge_stale(character_name: str,
                signatures: Iterable[str]) -> Dict[str, Any]:
    """Delete the files of the given signatures — but only those the CURRENT
    report still calls stale.

    The re-check is the point: the report the caller acted on may be minutes
    old, and a batch run may have produced a perfectly valid entry in the
    meantime. Anything not (or no longer) stale is skipped and counted.
    """
    wanted = {str(s) for s in (signatures or []) if s}
    if not wanted:
        return {"deleted_files": 0, "freed_bytes": 0, "skipped": 0}
    report = verify_cache(character_name)
    allowed = set(report["stale_signatures"])
    skipped = len(wanted - allowed)
    deleted = 0
    freed = 0
    for files_of in (_ref_files, _mesh_files):
        for signature, files in files_of(character_name).items():
            if signature not in wanted or signature not in allowed:
                continue
            for p in files:
                try:
                    size = p.stat().st_size
                    p.unlink()
                    deleted += 1
                    freed += size
                except OSError as e:
                    logger.warning("Cache GC %s: %s not removed: %s",
                                   character_name, p.name, e)
    logger.info("Cache GC %s: %d file(s) deleted, %.1f MB freed, %d signature(s) "
                "skipped (no longer stale)", character_name, deleted,
                freed / 1e6, skipped)
    return {"deleted_files": deleted, "freed_bytes": freed, "skipped": skipped}
