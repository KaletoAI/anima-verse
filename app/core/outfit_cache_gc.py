"""The outfit rule and the scanners of the artefact GC, plus the report the
outfit-batch dialog shows.

The JUDGE of every derived file is ``app/core/artefact_graph.py`` (parents,
roots, reachability, the one collector every delete path calls). This module
keeps what it is built from: the outfit rule (manifest re-sign, reachable
set), the file scanners per cache, the garment roots — and
``verify_cache`` / ``purge_stale``, which read and act on the graph for the
outfit-batch cache dialog.

Two caches key on the SAME signature (``model_refs.current_outfit_state``):

* ``characters/<name>/model_refs/`` — ``<kind>_<sig>.png`` plus a ``.json``
  sidecar, kinds ``tpose`` / ``pose`` plus the optional extra mesh views
  ``tpose_back`` / ``tpose_left`` / ``tpose_right`` (legacy:
  ``tpose_animal``);
* ``characters/<name>/model3d/`` — ``<sig>.glb|fbx`` plus ``<sig>.json`` and,
  for FBX, ``<sig>.png``; the reduced tiers (``low/<sig>.*``) and the
  untouched originals (``raw/<sig>.*``) belong to the same entry. A group
  whose top-level model is gone can never be served — it is stale whatever
  its manifest says, and its leftovers go with a purge.

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
The reachable set is only enumerated when an entry WITHOUT a manifest exists
— with every entry carrying one, the cartesian product is never built.

**Base bodies** (``app/core/base_body.py``) share both directories under a
base signature (``"base"`` + 8 hex — never an outfit signature, which is
pure hex): ``tpose[_<view>]_<bsig>`` refs and the ``<bsig>`` model group.
Exactly the character's CURRENT base signature is valid; every other base
entry is stale (a new profile image or body description made it obsolete).
No manifest is read for them.

**Garments** (``app/core/garment_store.py``) live in ``characters/<name>/garments/``
and are grouped by ``(item, fsig)``; the report names such a group
``garment:<item>_<fsig>``. Valid are the CURRENT-fsig files of every equipped
garment item and of every own-mesh outfit piece the character holds
(``garment_set.held_clothing``; a run in flight writes exactly those) and the group of the fit
that is served instead while the current one is not accepted yet — the newest
accepted fit on the current base model (``garment_store.accepted_fit``, R11).
Every other recognised garment group is stale; a file whose name the store
does not recognise is never judged. When the keep set cannot be computed, no
garment group is judged at all.

**Painted bodies** (``base_body`` texture store, plan
2026-11-10-texture-body-reuse Task 1) live in ``model3d/texture/`` and
``model_refs/texture/[drafts/]`` under a texture signature (``"tex"`` + 12
hex); the report names such a group ``texture:<tsig>``. **Outfit bodies**
(``ob`` + 8 hex, plan 2026-11-10-outfit-body-mesh-mode) share the model and
reference directories like a base body, their fits live in
``garments/bodies/<id>/``. How both are judged: ``artefact_graph``.
"""

import re
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple

from app.core.log import get_logger

logger = get_logger(__name__)

#: Enumerating the reachable set is lazy but not free. Above this many
#: combinations we refuse instead of hanging for minutes.
MAX_REACHABLE_COMBOS = 5_000_000
#: Longest first — otherwise "tpose_animal_<sig>" or "tpose_back_<sig>"
#: parses as kind "tpose" with a mangled signature.
REF_PREFIXES = ("tpose_animal_", "tpose_front_", "tpose_right_", "tpose_back_", "tpose_left_",
                "tpose_", "pose_")
#: The shape of a mesh cache key: ``model_refs.outfit_signature`` (md5[:12]),
#: a retired -s fork (accepted only for deletion), a base-body signature or
#: an outfit body id — the names of the rollback snapshots this module lists.
_MESH_SIG_RE = re.compile(r"[0-9a-f]{12}(-s[0-9a-f]{8})?|base[0-9a-f]{8}|ob[0-9a-f]{8}")
#: The shape of a base-body signature (``base_body.base_signature``).
_BASE_SIG_RE = re.compile(r"base[0-9a-f]{8}")
#: The shape of an outfit body id (``base_body.outfit_body_id``).
_OUTFIT_BODY_RE = re.compile(r"ob[0-9a-f]{8}")


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
                    "items": [str(i) for i in (items or []) if i],
                    "mesh_variant": meta.get("mesh_variant", ""),
                    "mesh_token": meta.get("mesh_token", "")}
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
                 owned: Set[str], reachable: Callable[[], Set[str]],
                 character_name: str = "") -> bool:
    """The rule of this module, for one cache entry. ``reachable`` is called
    only for an entry without a manifest (it may enumerate millions).

    Retired -s forks are always unreachable. Ordinary pose-state references
    (-p) are judged by their outfit base, independently of mesh inputs."""
    from app.core.model_refs import is_state_fork, neutral_signature
    if is_state_fork(signature):
        return False
    base = neutral_signature(signature)
    if manifest is not None:
        used = set(manifest["pieces"].values()) | set(manifest["items"])
        if not used.issubset(owned):
            return False
        from app.core.model_refs import mesh_signature
        return mesh_signature(manifest["pieces"], manifest["items"], character_name,
                              manifest.get("mesh_variant", ""), manifest.get("mesh_token", "")) == base
    return base in reachable()


def _ref_files(character_name: str) -> Dict[str, List[Path]]:
    """signature → its reference files (image + sidecar), by file name —
    the base-body back drafts (``model_refs/drafts/``) go with the
    signature of their outfit."""
    from app.core.base_body import DRAFT_DIR
    from app.core.model_refs import _IMAGE_EXTS
    from app.models.character import get_character_dir
    out: Dict[str, List[Path]] = {}
    d = get_character_dir(character_name) / "model_refs"
    if not d.exists():
        return out
    drafts = d / DRAFT_DIR
    for p in sorted(d.iterdir()) + (sorted(drafts.iterdir()) if drafts.is_dir() else []):
        if not p.is_file() or p.suffix.lower() not in _IMAGE_EXTS + (".json",):
            continue
        for prefix in REF_PREFIXES:
            if p.stem.startswith(prefix):
                out.setdefault(p.stem[len(prefix):], []).append(p)
                break
    return out


def _mesh_files(character_name: str) -> Dict[str, List[Path]]:
    """signature → its mesh files (model + sidecar + texture), including the
    reduced tiers (``low/``), the raw backups (``raw/``), a base body's
    covered variant (``covered/``) and the garment
    assemblies (``assembled/``, ``assembled/low/``) of the same signature —
    exactly what ``model3d._purge_combination`` removes."""
    from app.blender.refine import RAW_DIR_NAME
    from app.core.model3d import ASSEMBLED_DIR, COVERED_DIR, FULL_TIER, MODEL_EXTS, MODEL_TIERS
    from app.models.character import get_character_dir
    out: Dict[str, List[Path]] = {}
    d = get_character_dir(character_name) / "model3d"
    if not d.exists():
        return out
    keep = MODEL_EXTS + (".json", ".png", ".jpg", ".jpeg")
    subdirs = [d / t for t in MODEL_TIERS if t != FULL_TIER] + [d / "unrigged", d / "facefix", d / "facefix-ref", d / RAW_DIR_NAME, d / "prerig", d / "low" / "prerig", d / "low" / RAW_DIR_NAME,
                                                               d / COVERED_DIR, d / ASSEMBLED_DIR, d / ASSEMBLED_DIR / "low"]
    for folder in [d] + subdirs:
        if not folder.is_dir():
            continue
        any_suffix = folder.name in (RAW_DIR_NAME, "prerig", "unrigged", "facefix", "facefix-ref")    # the purger takes raw/<sig>.*
        for p in sorted(folder.iterdir()):
            if p.is_file() and (any_suffix or p.suffix.lower() in keep):
                out.setdefault(p.stem, []).append(p)
    rollback = d / "rollback"
    if rollback.is_dir():
        for snapshot in sorted(rollback.iterdir()):
            if snapshot.is_dir() and _MESH_SIG_RE.fullmatch(snapshot.name):
                out.setdefault(snapshot.name, []).extend(p for p in snapshot.rglob("*") if p.is_file())
    return out


def _has_top_model(signature: str, files: Iterable[Path]) -> bool:
    """True when the group has a top-level model file — the only one
    ``model3d.find_model3d`` serves."""
    from app.core.model3d import MODEL_EXTS
    for p in files:
        if (p.stem == signature and p.suffix.lower() in MODEL_EXTS
                and p.parent.name == "model3d"):
            return True
    return False


def _worn_signature(character_name: str) -> str:
    """The currently worn combination — protected from every rule below."""
    try:
        from app.core.model_refs import current_outfit_state
        return current_outfit_state(character_name)[2]
    except Exception:
        return ""


def _current_base_signature(character_name: str) -> Optional[str]:
    """The base signature that is valid right now: ``""`` for a character
    that has none (non-humanoid — every base entry of it is stale), None when
    it cannot be computed (then no base entry is judged at all — never delete
    on a guess)."""
    try:
        from app.core.base_body import base_signature
        from app.core.model_refs import is_humanoid
        if not is_humanoid(character_name):
            return ""
        return base_signature(character_name)
    except Exception:
        logger.exception("Cache GC %s: base signature unavailable", character_name)
        return None


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


GARMENT_KEY_PREFIX = "garment:"


def _garment_key(item_id: str, fsig: str) -> str:
    return f"{GARMENT_KEY_PREFIX}{item_id}_{fsig}"


def _garment_files(character_name: str) -> Dict[str, List[Path]]:
    """``garment:<item>_<fsig>`` → its files under ``garments/``."""
    from app.core import garment_store
    return {_garment_key(item, fsig): files
            for (item, fsig), files in garment_store.stored_groups(character_name).items()}


TEXTURE_KEY_PREFIX = "texture:"


def _texture_dirs(character_name: str) -> List[Path]:
    from app.core.base_body import DRAFT_DIR, TEXTURE_DIR
    from app.models.character import get_character_dir
    root = get_character_dir(character_name)
    refs = root / "model_refs" / TEXTURE_DIR
    return [root / "model3d" / TEXTURE_DIR, refs, refs / DRAFT_DIR]


def _texture_files(character_name: str) -> Dict[str, List[Path]]:
    """``texture:<tsig>`` → its files in the texture store (painted body +
    sidecar, dressed views, drafts); a name that is no texture signature is
    never judged."""
    from app.core.base_body import TEXTURE_SIG_RE
    out: Dict[str, List[Path]] = {}
    for folder in _texture_dirs(character_name):
        if not folder.is_dir():
            continue
        for p in sorted(folder.iterdir()):
            if not p.is_file():
                continue
            stem = p.stem
            for prefix in REF_PREFIXES:
                if stem.startswith(prefix):
                    stem = stem[len(prefix):]
                    break
            if TEXTURE_SIG_RE.fullmatch(stem):
                out.setdefault(TEXTURE_KEY_PREFIX + stem, []).append(p)
    return out


def _garment_roots(character_name: str) -> Optional[Tuple[Set[str], Set[str], Set[str]]]:
    """``(keep, items, hair items)`` — the garment roots of the artefact
    graph. ``keep``: the garment groups that stay — per garment item, every
    equipped mesh piece (hair) and every own-mesh outfit piece the character
    HOLDS or wears (``garment_set.held_clothing``: a dress in the wardrobe
    keeps its fit, plan 2026-11-09-base-body-phase5-mesh-items Task 4) — the
    current fsig, the fit served on the current base model, and per method
    (hair: edit chain / HairDeck) the newest accepted fit on the current base
    model and the newest accepted fit at all — so switching the hair method
    back never costs a generation (plan 2026-11-09-hairdeck-hair, Review
    Focus 3). An older accepted fit of the same method is stale. ``items``:
    the kept items (a deleted item keeps nothing); ``hair items``: the kept
    hair garments (their HairDeck jobs are judged by ``artefact_graph``).
    None when the roots cannot be computed (then nothing is judged — never
    delete on a guess)."""
    try:
        from app.core import base_body, garment_set, garment_store
        from app.models.inventory import get_equipped_mesh_pieces, get_item
        keep: Set[str] = set()
        kept_items: Set[str] = set()
        hair: Set[str] = set()
        base = base_body.current_base(character_name)
        items = sorted({*get_equipped_mesh_pieces(character_name).values(),
                        *garment_set.held_clothing(character_name)})
        for item_id in items:
            item = get_item(item_id)
            if item is None:
                continue  # a deleted item keeps nothing
            kept_items.add(item_id)
            try:
                keep.add(_garment_key(item_id, garment_store.garment_fsig(character_name, item_id)))
            except ValueError:
                pass  # no current fingerprint (e.g. the flag is off): the accepted fits below stay
            if garment_set.garment_kind_of(item) == garment_set.HAIR:
                hair.add(item_id)
            if base and base[1]:
                fit = garment_store.accepted_fit(character_name, item_id, base_model_sha=base[1])
                parsed = garment_store.parse_name(fit[0]) if fit else None
                if parsed:
                    keep.add(_garment_key(*parsed))
            newest = list(garment_store.newest_accepted_fits(character_name, item_id).values())
            if base and base[1]:
                newest += garment_store.newest_accepted_fits(
                    character_name, item_id, base_model_sha=base[1]).values()
            for path, _record in newest:
                parsed = garment_store.parse_name(path)
                if parsed:
                    keep.add(_garment_key(*parsed))
        return keep, kept_items, hair
    except Exception:
        logger.exception("Cache GC %s: garment keep set unavailable", character_name)
        return None


def _garment_keep(character_name: str) -> Optional[Set[str]]:
    """The garment groups that stay (``_garment_roots``), None when unknown."""
    roots = _garment_roots(character_name)
    return roots[0] if roots is not None else None


def verify_cache(character_name: str) -> Dict[str, Any]:
    """Report on the character's derived files — the artefact graph
    (``app/core/artefact_graph.py``) read as the outfit-batch dialog shows it:

    ``{refs: {total, valid, stale, stale_bytes}, meshes: {…}, garments: {…}, textures: {…},
    body_fits: {…}, hairdeck: {…}, temp: {…}, stale_signatures: [...], protected: [sig]}``

    Group counts, not file counts — one signature owns an image and its
    sidecar. A group whose work is running counts as valid. Raises
    ValueError when the reachable set is refused (see
    ``reachable_signatures``).
    """
    from app.core import artefact_graph
    analysis = artefact_graph.analyse(character_name, explicit=True)
    worn = analysis.roots.worn
    stale: List[str] = []
    out: Dict[str, Any] = {"stale_signatures": stale, "protected": [worn] if worn else []}
    for category in artefact_graph.CATEGORIES:
        group = [n for n in analysis.nodes if n.category == category]
        stale_nodes = [n for n in group if not n.reachable and not n.protected]
        out[category] = {"total": len(group), "valid": len(group) - len(stale_nodes),
                         "stale": len(stale_nodes), "stale_bytes": sum(n.size() for n in stale_nodes)}
        for node in stale_nodes:
            if node.key not in stale:
                stale.append(node.key)
    logger.info("Cache GC %s: refs %s, meshes %s, garments %s, textures %s, body fits %s, %d stale key(s)",
                character_name, out["refs"], out["meshes"], out["garments"], out["textures"],
                out["body_fits"], len(stale))
    return out


def purge_stale(character_name: str,
                signatures: Iterable[str]) -> Dict[str, Any]:
    """Delete the given keys — but only those the CURRENT graph still calls
    unreachable (``artefact_graph.collect(keys=…)``, explicit).

    The re-check is the point: the report the caller acted on may be minutes
    old, and a batch run may have produced a perfectly valid entry in the
    meantime. Anything not (or no longer) stale is skipped and counted.
    """
    wanted = {str(s) for s in (signatures or []) if s}
    if not wanted:
        return {"deleted_files": 0, "freed_bytes": 0, "skipped": 0}
    from app.core import artefact_graph
    report = artefact_graph.collect(character_name, explicit=True, keys=wanted, reason="cache purge")
    held = {s["key"] for s in report["skipped"]}
    done = {e["key"] for e in report["orphans"]} - held
    return {"deleted_files": report["deleted_files"], "freed_bytes": report["freed_bytes"],
            "skipped": len(wanted - done)}
