"""One-time boot migration: every stored outfit piece gets its mode, the
per-item ``own_mesh`` flag and the per-character ``outfit_body_mode`` leave
the data (plan ``docs/superpowers/plans/2026-11-12-unified-worn-pieces.md``
Task 3, builder-check ruling 4).

The mode of a worn piece (``outfit_piece.mesh_mode``, ``garment_set``) used
to be split over two places: the ITEM's ``own_mesh`` flag and the WEARER's
``outfit_body_mode`` (``mesh`` / ``retexture``). ``migrate_modes_once`` judges
every stored outfit piece with ``judge_item`` — the world's (``world.db``) once
per world (world_kv flag ``FLAG``, which also covers the profiles), the shared
library's once per INSTALLATION (Ruling FR-C1: its own marker
``SHARED_MODES_KEY``, a top-level key of the shared items file written in the
same write as the judged items; the shared re-default's marker counts as done
too, ``shared_modes_done``). The two halves run on their own markers: a world
already migrated still runs the shared half while the shared marker is unset
(a failed shared write retries on the next boot), a new world never re-judges
the shared library: after the re-default has removed the modes nobody tests,
rule 4 would paint them all again. The judgement, in this order:

1. an item that already carries a valid ``mesh_mode`` is untouched (a shared
   item judged in another world, an item created after Task 2);
2. ``own_mesh`` true → ``own_mesh``;
3. worn (``equipped_pieces``) by at least one character, and EVERY wearer's
   STORED profile ``outfit_body_mode`` is ``"mesh"`` → ``in_body``;
4. else → ``painted``.

The wearers are every character row (dormant and pooled ones too); their
``outfit_body_mode`` is read from the stored profile key, never from the
derived ``base_body.outfit_body_mode``. Then the ``own_mesh`` key is removed
from every item, and per character, under ``keyed_lock("character_profile",
name)``, the ``outfit_body_mode`` key is popped from the profile.

The order is items first, profiles second: a run that dies in between keeps
the profile keys the next run's judgement needs (the flag is not set yet).
A failed write is logged as a WARNING and the migration goes on; the flag is
set anyway (as ``hair_migration`` does — a half-run retry at every start
would be worse), the log names what stayed. Only an item list, the character
list or a wearer's profile that cannot be read raises before anything is
written and leaves the flag unset (the boot logs it, the next start retries).

The shared library is ``shared/items/items.json`` in the repository: the
first boot of the first world rewrites that tracked file, once.

RE-DEFAULT (Rulings A10 / A12, fix round 1) — ``redefault_modes_once``,
after the mode migration and only once that has run. Since A10 the default
mode of a piece is ``in_body`` and a mode is stored only when someone picks
it; the mode migration above had written a mode into EVERY piece (most of
them ``painted`` by its rule 4). An outfit piece that belongs to no TEST
character — none wears it (``equipped_pieces``) and none owns it (its
inventory) — loses its stored ``outfit_piece.mesh_mode`` and follows the
default; a piece a test character wears or owns keeps its mode untouched.
A test character (``is_test_character``) is a humanoid whose STORED profile
carries ``model_pipeline: "base_body"``; every character row counts (dormant
and pooled ones too).

Two scopes, two markers:

- the WORLD's items: once per world (world_kv ``REDEFAULT_FLAG``);
- the SHARED library (``shared/items/items.json``, one per repository): once
  for ALL worlds — the marker ``SHARED_REDEFAULT_KEY`` is a top-level key of
  that file, written in the same write as the cleared items
  (``inventory._save_shared_items(meta=…)``, which keeps library meta across
  every later save), so it travels with the library. Only a world WITH test
  characters runs it, and it keeps every shared piece that world's test
  characters wear or own. A world without test characters (hotopia, say)
  that boots first leaves the shared library untouched and the marker unset
  — it cannot know which shared pieces another world's test characters
  wear, so clearing anything there could change their figures; the first
  boot of a world with test characters does it.

One INFO line per cleared item, one summary line. Failure handling as above:
a character list, a profile, an inventory or an item list that cannot be
read raises before anything is written and leaves both markers unset; a
failed world write is logged as a WARNING, the item keeps its mode, the
world flag is set anyway; a failed shared write is logged and leaves the
shared marker unset (the next boot retries — the write carries the marker,
so no half state). Items are written with the plain savers — no outfit
notification, no Build, no hub job: a test character's pieces keep their
modes (its wanted figure is unchanged), and off the pipeline the modes are
ignored (``garment_set.worn_garments`` is empty, ``figure.worn_sets`` puts
nothing in the body).

RE-KEYING (Task 5, ruling 4) — ``rekey_bodies_once``, once per world
(world_kv ``REKEY_FLAG``), right after the mode migration and only once that
has run: every stored outfit body (``ob…``) still keyed by its texture
(``{mode, texture_signature, version 1}``) is judged against the SHAPE key
its outfit has under the migrated modes (``figure.shape_key``). It is renamed
onto that key when its record matches exactly — base signature = the current
one, the outfit it was built for (record ``built_for``: the manifest of that
outfit's dressed front, else its model sidecar's ``pieces``) has a piece in
the body now, its base variant is the one a build would use now, and the
in-body dress text (``figure.shape_inputs``) is exactly the text the body was
meshed from (the texture store sidecars of its old ``texture_signature``,
``base_body._store_texture_views``). Otherwise — a painted or own-mesh piece
in its text, another base, no record, an open hub operation on it, a target
name already taken — it stays under its old id, decided ``"stale"``: the
artefact GC predicts no such key, so it goes unless a live outfit model
names it, and the next build meshes the shape anew. Every decision is
logged. The rename (``rekey_body``) never deletes: every file of the body's
chain (``artefact_graph.body_chain``: its refs and model group, the body
fits under ``garments/bodies/<id>/``) and any other derived file whose path
names the old id moves to the new name; every sidecar that names the old id
(the body's, its fits', the outfit models on it) is rewritten, the parent
record gets ``body_id`` = ``shape_key`` = the new key, ``version``
``figure.SHAPE_VERSION``, ``shape_inputs`` and ``rekeyed_from`` (old id,
old texture signature); ``mode`` / ``texture_signature`` leave it. All or
nothing: a failure part-way moves every file back and restores every
sidecar.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from app.core.log import get_logger

logger = get_logger("figure_migration")

#: world_kv key of the done flag.
FLAG = "migrated_worn_piece_modes"
#: world_kv key of the re-key's done flag.
REKEY_FLAG = "rekeyed_figure_bodies"
#: world_kv key of the re-default's done flag for the world's items (Ruling A12).
REDEFAULT_FLAG = "redefaulted_unworn_piece_modes"
#: Top-level key of the SHARED items file: the shared library's re-default ran
#: (once for every world; ``inventory.get_shared_items_meta``).
SHARED_REDEFAULT_KEY = "redefaulted_unworn_piece_modes"
#: Top-level key of the SHARED items file: the shared library's half of the
#: mode migration ran (once per installation, Ruling FR-C1). The world flag
#: ``FLAG`` covers only the world's items and its profiles.
SHARED_MODES_KEY = "migrated_worn_piece_modes"
#: A body's decision when it keeps its old id.
STALE = "stale"
#: The removed per-item flag (``outfit_piece`` key).
OWN_MESH_KEY = "own_mesh"
#: The removed per-character profile key and its value that meant "in the body".
PROFILE_KEY = "outfit_body_mode"
PROFILE_MESH = "mesh"


def _piece(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    piece = item.get("outfit_piece")
    return piece if isinstance(piece, dict) else None


def judge_item(item: Dict[str, Any], wearers_modes: List[Optional[str]]) -> str:
    """The mode of an outfit piece by ruling 4 (module docstring).
    ``wearers_modes``: the stored ``outfit_body_mode`` of every character
    wearing it (None for a profile without the key); empty = unworn."""
    from app.core import garment_set
    piece = _piece(item) or {}
    mode = piece.get("mesh_mode")
    if mode in garment_set.MESH_MODES:
        return mode
    if piece.get(OWN_MESH_KEY) is True:
        return garment_set.OWN_MESH
    if wearers_modes and all(m == PROFILE_MESH for m in wearers_modes):
        return garment_set.IN_BODY
    return garment_set.PAINTED


def _wearers(names: Sequence[str]) -> Tuple[Dict[str, List[str]], Dict[str, Optional[str]]]:
    """``({item id: [character, ...]}, {character: stored outfit_body_mode})``
    — who wears which outfit piece (``equipped_pieces``) and the STORED
    profile key of each character (None without one). A profile that cannot
    be read raises (``strict``): its wearers' judgement would be a guess."""
    from app.models.character import get_character_profile
    worn: Dict[str, List[str]] = {}
    modes: Dict[str, Optional[str]] = {}
    for name in names:
        profile = get_character_profile(name, strict=True) or {}
        modes[name] = profile.get(PROFILE_KEY)
        pieces = profile.get("equipped_pieces")
        for item_id in sorted({str(v).strip() for v in (pieces.values() if isinstance(pieces, dict) else ())
                               if v and str(v).strip()}):
            worn.setdefault(item_id, []).append(name)
    return worn, modes


def _migrate(items: List[Dict[str, Any]], worn: Dict[str, List[str]],
             modes: Dict[str, Optional[str]], where: str) -> Tuple[Dict[str, str], List[Dict[str, Any]]]:
    """Judge and clean ``items`` in place. ``(judged {id: mode}, changed
    items)``."""
    judged: Dict[str, str] = {}
    changed: List[Dict[str, Any]] = []
    for item in items:
        item_id = str(item.get("id") or "")
        piece = _piece(item)
        touched = False
        if item.get("category") == "outfit_piece":
            if piece is None:
                piece = {}
                item["outfit_piece"] = piece
            from app.core.garment_set import MESH_MODES
            if piece.get("mesh_mode") not in MESH_MODES:
                wearers = worn.get(item_id, [])
                mode = judge_item(item, [modes.get(w) for w in wearers])
                piece["mesh_mode"] = mode
                judged[item_id] = mode
                touched = True
                logger.info("Worn-piece mode migration: item %s (%s, %s) -> %s, wearers %s",
                            item_id, item.get("name") or "-", where, mode,
                            ", ".join(f"{w}={modes.get(w) or '-'}" for w in wearers) or "-")
        if piece is not None and OWN_MESH_KEY in piece:
            piece.pop(OWN_MESH_KEY)
            touched = True
        if touched:
            changed.append(item)
    return judged, changed


def _drop_profile_key(name: str) -> bool:
    """Pop ``outfit_body_mode`` under the profile lock. True when it was
    there and the profile was saved."""
    from app.core.keyed_lock import keyed_lock
    from app.models.character import get_character_profile, save_character_profile
    with keyed_lock("character_profile", name):
        profile = get_character_profile(name) or {}
        if PROFILE_KEY not in profile:
            return False
        profile.pop(PROFILE_KEY)
        if save_character_profile(name, profile):
            return True
    logger.warning("Worn-piece mode migration %s: profile not saved — %s stays", name, PROFILE_KEY)
    return False


def shared_modes_done() -> bool:
    """Whether the SHARED library's half of the mode migration ran — once per
    installation (Ruling FR-C1): its own marker ``SHARED_MODES_KEY`` in the
    shared items file, or the shared re-default's marker (the re-default runs
    only after the mode migration, and re-judging the pieces it cleared would
    paint them again). An unreadable file raises (``strict``)."""
    from app.models import inventory
    meta = inventory.get_shared_items_meta(strict=True)
    return bool(meta.get(SHARED_MODES_KEY) or meta.get(SHARED_REDEFAULT_KEY))


def migrate_modes_once() -> Optional[Dict[str, Any]]:
    """The migration (module docstring). None when both halves already ran
    (the world's ``FLAG`` and the shared library's ``shared_modes_done``),
    else ``{items: {item id: mode}, profiles: [names whose key was
    dropped]}`` — only the halves that ran this time."""
    from app.models import inventory
    from app.models.character import list_available_characters
    from app.models.world import get_world_setting, set_world_setting
    world_done = bool(get_world_setting(FLAG, strict=True))
    shared_done = shared_modes_done()
    if world_done and shared_done:
        return None
    # A list that cannot be read is no reason to call the world migrated.
    names = list_available_characters(include_pooled=True, include_dormant=True, strict=True)
    worn, modes = _wearers(names)
    world_items = [] if world_done else inventory._load_items(strict=True)
    shared_items = [] if shared_done else inventory._load_shared_items(strict=True)

    judged, changed = _migrate(world_items, worn, modes, "world")
    for item in changed:
        if not inventory._save_items([item]):
            logger.warning("Worn-piece mode migration: world item %s not saved", item.get("id"))
            judged.pop(str(item.get("id") or ""), None)
    if shared_done:
        logger.info("Worn-piece mode migration: the shared library was migrated before (installation "
                    "marker) — its modes stay as they are")
    else:
        from app.core.timeutils import utc_now_iso
        shared_judged, shared_changed = _migrate(shared_items, worn, modes, "shared")
        try:
            # The marker travels in the same write as the judged items: no half state.
            inventory._save_shared_items(shared_items, meta={SHARED_MODES_KEY: utc_now_iso()})
            judged.update(shared_judged)
        except Exception as e:  # noqa: BLE001 — the marker stays unset: the next boot retries
            logger.warning("Worn-piece mode migration: shared items not saved (%s): %s",
                           ", ".join(str(i.get("id")) for i in shared_changed) or "-", e)

    profiles: List[str] = []
    for name in ([] if world_done else names):
        try:
            if _drop_profile_key(name):
                profiles.append(name)
        except Exception as e:  # noqa: BLE001
            logger.warning("Worn-piece mode migration %s: profile step failed: %s", name, e)

    if not world_done:
        set_world_setting(FLAG, "1")
    logger.info("Worn-piece mode migration done: %d item(s) judged, %d profile(s) without %s",
                len(judged), len(profiles), PROFILE_KEY)
    return {"items": judged, "profiles": profiles}


# --- Re-default of the modes nobody tests (module docstring, Rulings A10 / A12) ----------


def is_test_character(name: str, profile: Dict[str, Any]) -> bool:
    """Whether ``name`` is one of the user's test characters for the
    re-default: humanoid AND its STORED profile says ``model_pipeline:
    "base_body"``. Read from the stored key on purpose, never through
    ``base_body.is_base_pipeline``: the removed "Use base body pipeline"
    checkbox's stored value is the user's record of which characters they
    test the figure with (Ruling A12), and that helper answers True for every
    humanoid since the checkbox is gone (Task 11h, Ruling A13). The key stays
    in the profiles until the re-default is done (``drop_pipeline_key_once``
    waits for it)."""
    if profile.get("model_pipeline") != "base_body":
        return False
    from app.core.model_refs import is_humanoid
    return bool(is_humanoid(name, profile=profile))


def _tested_pieces(names: Sequence[str]) -> Tuple[List[str], Dict[str, List[str]]]:
    """``(test characters, {item id: [test character, ...]})`` — the items a
    test character wears (``equipped_pieces``) or owns (inventory). A
    profile or inventory that cannot be read raises (``strict``): clearing a
    tester's piece would change its figure."""
    from app.models.character import get_character_profile
    from app.models.inventory import _load_inventory
    testers: List[str] = []
    tested: Dict[str, List[str]] = {}
    for name in names:
        profile = get_character_profile(name, strict=True) or {}
        if not is_test_character(name, profile):
            continue
        testers.append(name)
        pieces = profile.get("equipped_pieces")
        ids = {str(v).strip() for v in (pieces.values() if isinstance(pieces, dict) else ())}
        ids.update(str(e.get("item_id") or "").strip()
                   for e in _load_inventory(name, strict=True).get("inventory") or [])
        for item_id in sorted(i for i in ids if i):
            tested.setdefault(item_id, []).append(name)
    return testers, tested


def _redefault(items: List[Dict[str, Any]], tested: Dict[str, List[str]], where: str
               ) -> Tuple[Dict[str, str], Dict[str, str], List[Dict[str, Any]]]:
    """Clear the stored mode of every untested outfit piece of ``items`` in
    place. ``(cleared {id: old mode}, kept {id: mode}, changed items)``."""
    cleared: Dict[str, str] = {}
    kept: Dict[str, str] = {}
    changed: List[Dict[str, Any]] = []
    for item in items:
        piece = _piece(item)
        if item.get("category") != "outfit_piece" or piece is None or "mesh_mode" not in piece:
            continue
        item_id = str(item.get("id") or "")
        if item_id in tested:
            kept[item_id] = str(piece.get("mesh_mode"))
            continue
        cleared[item_id] = str(piece.pop("mesh_mode"))
        changed.append(item)
        logger.info("Mode re-default: item %s (%s, %s) %s -> default (no test character wears or owns it)",
                    item_id, item.get("name") or "-", where, cleared[item_id])
    return cleared, kept, changed


def redefault_modes_once() -> Optional[Dict[str, Any]]:
    """The re-default (module docstring). None when both scopes are done or
    the mode migration has not run yet (it would write rule-4 modes again),
    else ``{cleared: {item id: old mode}, kept: {item id: mode}, world:
    "done" | "already", shared: "done" | "already" | "waits" | "failed"}``
    — ``cleared`` only what was written, both scopes together."""
    from app.core.timeutils import utc_now_iso
    from app.models import inventory
    from app.models.character import list_available_characters
    from app.models.world import get_world_setting, set_world_setting
    world_done = bool(get_world_setting(REDEFAULT_FLAG, strict=True))
    shared_done = bool(inventory.get_shared_items_meta(strict=True).get(SHARED_REDEFAULT_KEY))
    if world_done and shared_done:
        return None
    if not get_world_setting(FLAG, strict=True):
        logger.warning("Mode re-default waits: the worn-piece mode migration has not run yet")
        return None
    names = list_available_characters(include_pooled=True, include_dormant=True, strict=True)
    testers, tested = _tested_pieces(names)
    world_items = [] if world_done else inventory._load_items(strict=True)
    shared_items = [] if shared_done or not testers else inventory._load_shared_items(strict=True)

    cleared: Dict[str, str] = {}
    kept: Dict[str, str] = {}
    out: Dict[str, Any] = {"cleared": cleared, "kept": kept,
                           "world": "already" if world_done else "done",
                           "shared": "already" if shared_done else "done"}
    if not world_done:
        world_cleared, world_kept, changed = _redefault(world_items, tested, "world")
        kept.update(world_kept)
        for item in changed:
            item_id = str(item.get("id") or "")
            if inventory._save_items([item]):
                cleared[item_id] = world_cleared[item_id]
            else:
                logger.warning("Mode re-default: world item %s not saved — keeps %s", item_id, world_cleared[item_id])
        set_world_setting(REDEFAULT_FLAG, "1")
    if not shared_done and not testers:
        out["shared"] = "waits"
        logger.info("Mode re-default: the shared library waits for a world with test characters "
                    "(this one has none — it cannot tell which shared pieces another world's test characters use)")
    elif not shared_done:
        shared_cleared, shared_kept, _changed = _redefault(shared_items, tested, "shared")
        kept.update(shared_kept)
        try:
            inventory._save_shared_items(shared_items, meta={SHARED_REDEFAULT_KEY: utc_now_iso()})
            cleared.update(shared_cleared)
        except Exception as e:  # noqa: BLE001 — the marker is in the same write: the next boot retries
            out["shared"] = "failed"
            logger.warning("Mode re-default: shared items not saved, they keep their modes (%s): %s",
                           ", ".join(sorted(shared_cleared)) or "-", e)
    logger.info("Mode re-default done (world %s, shared %s): %d item(s) back to the default, %d kept "
                "(test characters: %s)", out["world"], out["shared"], len(cleared), len(kept),
                ", ".join(testers) or "none")
    return out


# --- Re-keying the stored outfit bodies (module docstring) ------------------------------


class RekeyConflict(RuntimeError):
    """A body cannot move: a target name exists already, or nothing to move."""


def _move(src: Path, dst: Path) -> None:
    """One rename of the re-key (a module function: the smoke injects a failure here)."""
    os.rename(src, dst)


def _write(path: Path, data: bytes) -> None:
    """One atomic sidecar write of the re-key (the smoke injects a failure here)."""
    staged = path.with_name(f".rekey-{path.name}.tmp")
    try:
        staged.write_bytes(data)
        os.replace(staged, path)
    finally:
        staged.unlink(missing_ok=True)


def _swap(value: Any, old: str, new: str) -> Any:
    """``value`` with every occurrence of ``old`` in its strings (keys too) replaced by ``new``."""
    if isinstance(value, str):
        return value.replace(old, new)
    if isinstance(value, list):
        return [_swap(v, old, new) for v in value]
    if isinstance(value, dict):
        return {_swap(k, old, new): _swap(v, old, new) for k, v in value.items()}
    return value


def _renamed(root: Path, path: Path, old: str, new: str) -> Path:
    """``path`` (below ``root``) with ``old`` replaced by ``new`` in every component."""
    rel = path.relative_to(root)
    return root.joinpath(*[part.replace(old, new) for part in rel.parts])


def _rekey_plan(character_name: str, root: Path, old: str, new: str) -> Tuple[List[Tuple[Path, Path]], List[Path]]:
    """``(moves [(src, dst)], sidecars to rewrite at their FINAL path)`` of a re-key.
    Moves: every file of the body's chain whose path names ``old`` plus any
    other non-temp derived file that does (a file no scan claims stays nowhere
    under the old id); sidecars: every JSON below the three derived roots that
    names ``old`` (moved ones at their destination)."""
    from app.core import artefact_graph as ag
    nodes, _unknown = ag.scan(character_name)
    chain = ag.body_chain(nodes, root, old)
    files: Set[Path] = set()
    for node in nodes:
        if node.key in chain and node.kind in ("body", "body_fit"):
            files.update(node.files)
    all_files: List[Path] = []
    for name in ag.ROOT_DIRS:
        found, _temps = ag._walk(root / name)
        all_files += found
    files.update(p for p in all_files if old in p.relative_to(root).as_posix())
    moves = [(p, _renamed(root, p, old, new)) for p in sorted(files)]
    moved = {src: dst for src, dst in moves}
    sidecars: List[Path] = []
    for p in sorted(set(all_files) | files):
        if p.suffix.lower() != ".json":
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        if old in text:
            sidecars.append(moved.get(p, p))
    return moves, sidecars


def _prune_dirs(root: Path, marker: str) -> None:
    """Remove the EMPTY folders below ``root`` whose path names ``marker``
    (deepest first; ``rmdir`` never removes content)."""
    for name in ("model3d", "model_refs", "garments"):
        base = root / name
        if not base.is_dir():
            continue
        folders = [p for p in base.rglob("*") if p.is_dir() and marker in p.relative_to(root).as_posix()]
        for folder in sorted(folders, key=lambda p: len(p.parts), reverse=True):
            try:
                folder.rmdir()
            except OSError:
                pass


def rekey_body(character_name: str, old: str, new: str, *, record: Optional[Dict[str, Any]] = None) -> int:
    """Rename the stored outfit body ``old`` to ``new`` — its whole chain
    (module docstring), never deleting a file. ``record``: the keys to set on
    every ``outfit_body`` parent record (a value None removes the key).
    Returns the number of files renamed. Raises ``RekeyConflict`` (nothing
    touched) when a target exists or there is nothing to move, and re-raises
    any failure part-way AFTER every rename was undone and every sidecar
    restored."""
    from contextlib import ExitStack
    from app.core import base_body, model3d
    from app.core.artefact_graph import _char_dir
    from app.core.keyed_lock import keyed_lock
    if not (base_body.is_outfit_body_signature(old) and base_body.is_outfit_body_signature(new)) or old == new:
        raise ValueError(f"not two outfit body ids: {old!r} -> {new!r}")
    root = _char_dir(character_name)
    directory = root / "model3d"
    with ExitStack() as stack:
        for key in sorted((old, new)):
            stack.enter_context(keyed_lock("outfit_body", f"{character_name}:{key}"))
        for key in sorted((old, new)):
            stack.enter_context(keyed_lock("garment_body_fit", f"{character_name}:{key}"))
        for key in sorted((old, new)):
            stack.enter_context(keyed_lock("model3d", f"{character_name}:{key}"))
        stack.enter_context(keyed_lock("model3d_publication", str(directory)))
        moves, sidecars = _rekey_plan(character_name, root, old, new)
        if not moves:
            raise RekeyConflict(f"nothing of {old} stored")
        taken = [dst for _src, dst in moves if dst.exists() or dst.is_symlink()]
        if taken:
            raise RekeyConflict(f"{new} exists already ({taken[0].relative_to(root).as_posix()})")
        originals: Dict[Path, bytes] = {}
        moved_src = {dst: src for src, dst in moves}
        for path in sidecars:
            originals[path] = moved_src.get(path, path).read_bytes()
        done: List[Tuple[Path, Path]] = []
        written: List[Path] = []
        try:
            for src, dst in moves:
                dst.parent.mkdir(parents=True, exist_ok=True)
                _move(src, dst)
                done.append((src, dst))
            for path in sidecars:
                data = json.loads(originals[path].decode("utf-8"))
                data = _swap(data, old, new)
                parent = data.get("outfit_body") if isinstance(data, dict) else None
                if isinstance(parent, dict) and record:
                    for key, value in record.items():
                        if value is None:
                            parent.pop(key, None)
                        else:
                            parent[key] = value
                _write(path, json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))
                written.append(path)
        except BaseException:
            problems = []
            for path in reversed(written):
                try:
                    staged = path.with_name(f".rekey-undo-{path.name}.tmp")
                    staged.write_bytes(originals[path])
                    os.replace(staged, path)
                except OSError as e:  # pragma: no cover — logged loudly, the next lines still undo the moves
                    problems.append(f"{path}: {e}")
            for src, dst in reversed(done):
                try:
                    os.rename(dst, src)
                except OSError as e:  # pragma: no cover
                    problems.append(f"{dst} -> {src}: {e}")
            _prune_dirs(root, new)
            if problems:
                logger.error("Re-key %s %s -> %s: undo incomplete: %s", character_name, old, new, "; ".join(problems))
            else:
                logger.warning("Re-key %s %s -> %s failed part-way: every file is back under %s",
                               character_name, old, new, old)
            raise
        _prune_dirs(root, old)
        for key in (old, new):
            epoch = (str(directory), key)
            model3d._publication_epochs[epoch] = model3d._publication_epochs.get(epoch, 0) + 1
    logger.info("Re-key %s: outfit body %s -> %s (%d file(s) renamed, %d sidecar(s) rewritten)",
                character_name, old, new, len(moves), len(sidecars))
    return len(moves)


def _built_for_pieces(character_name: str, root: Path, signature: str) -> Optional[Tuple[Dict[str, str], list]]:
    """``(pieces, items)`` of the outfit a body was built for: the manifest of
    its dressed front (``model3d._ref_manifest``), else its model sidecar's
    ``pieces`` / ``items``; None when neither records any."""
    from app.core import model3d
    from app.core.model_refs import find_ref_image
    front = find_ref_image(character_name, "tpose", signature)
    if front is not None:
        manifest = model3d._ref_manifest(front)
        if isinstance(manifest.get("pieces"), dict) and manifest["pieces"]:
            return dict(manifest["pieces"]), list(manifest.get("items") or [])
    sidecar = root / "model3d" / f"{signature}.json"
    try:
        meta = json.loads(sidecar.read_text(encoding="utf-8")) if sidecar.is_file() else {}
    except (OSError, ValueError):
        meta = {}
    if isinstance(meta, dict) and isinstance(meta.get("pieces"), dict) and meta["pieces"]:
        return dict(meta["pieces"]), list(meta.get("items") or [])
    return None


def _meshed_texts(character_name: str, tsig: str) -> Optional[Dict[str, str]]:
    """``{view: dress text}`` the body of the texture ``tsig`` was meshed
    from — the texture store sidecars (``base_body._store_texture_views``) of
    every dressed view; None when one is missing or names no text."""
    from app.core import base_body
    if not base_body.is_texture_signature(tsig):
        return None
    texts: Dict[str, str] = {}
    for view in base_body.dressed_views():
        meta = base_body._ref_sidecar(base_body._texture_view(character_name, view, tsig))
        if not isinstance(meta.get("dress_text"), str) or meta.get("texture_signature") != tsig:
            return None
        texts[view] = meta["dress_text"]
    return texts


def _judge_body(character_name: str, root: Path, old: str, *, profile: Dict[str, Any], bsig: str,
                busy: Set[Tuple[str, str]]) -> Tuple[Optional[str], str, Dict[str, Any]]:
    """``(new key | None, why, record update)`` for the stored body ``old``;
    ``None`` = stale (``why`` says why), ``(old, "already keyed", {})`` for a
    body that carries a shape record already."""
    from app.core import figure
    from app.core.artefact_graph import _body_record
    record = _body_record(root, old)
    if not record:
        return None, "no parent record", {}
    if record.get("shape_key") == old and record.get("version") == figure.SHAPE_VERSION:
        return old, "already keyed", {}
    if (character_name, old) in busy:
        return None, "an open hub operation builds it", {}
    if not bsig or record.get("base_signature") != bsig:
        return None, f"built on base {record.get('base_signature') or '-'}, the current one is {bsig or '-'}", {}
    built_for = record.get("built_for")
    outfit = _built_for_pieces(character_name, root, built_for) if isinstance(built_for, str) and built_for else None
    if outfit is None:
        return None, f"no manifest of the outfit it was built for ({built_for or '-'})", {}
    pieces, items = outfit
    sets = figure.worn_sets(character_name, pieces=pieces, profile=profile)
    if not sets.in_body:
        return None, "no piece of its outfit is in the body now", {}
    variant = figure.predicted_variant(character_name, sets, items, profile=profile)
    if record.get("base_variant") != variant:
        return None, f"base variant {record.get('base_variant')!r}, a build uses {variant!r} now", {}
    inputs = figure.shape_inputs(character_name, sets, bsig=bsig, variant=variant, profile=profile)
    texts = _meshed_texts(character_name, str(record.get("texture_signature") or ""))
    if texts is None:
        return None, f"the texture store of {record.get('texture_signature') or '-'} names no dress text", {}
    if inputs["dress_text"] != texts:
        return None, "it was meshed from another dress text (a painted or own-mesh piece in the body)", {}
    new = figure.shape_key_of(inputs)
    update = {"body_id": new, "shape_key": new, "version": figure.SHAPE_VERSION, "shape_inputs": inputs,
              "rekeyed_from": {"body_id": old, "texture_signature": record.get("texture_signature"),
                               "version": record.get("version")},
              "mode": None, "texture_signature": None}
    return new, "", update


def _busy_bodies() -> Set[Tuple[str, str]]:
    """``{(character, body id)}`` with a running or deferred hub operation —
    a resume would publish under the old id. Raises when unreadable."""
    from app.core import base_body, hub_ops
    busy: Set[Tuple[str, str]] = set()
    for op in hub_ops.list_ops():
        if op.status not in (hub_ops.RUNNING, hub_ops.DEFERRED):
            continue
        parts = str(op.subject or "").split(":")
        if len(parts) == 3 and parts[0] == "model3d" and base_body.is_outfit_body_signature(parts[2]):
            busy.add((parts[1], parts[2]))
    return busy


def _rekey_character(character_name: str, busy: Set[Tuple[str, str]]) -> Dict[str, str]:
    """``{old id: new key | "stale"}`` for every stored body of the character
    that is not keyed by its shape yet."""
    from app.core import artefact_graph as ag, base_body
    from app.models.character import get_character_profile
    root = ag._char_dir(character_name)
    if not root.is_dir():
        return {}
    nodes, _unknown = ag.scan(character_name)
    bodies = sorted({n.key for n in nodes if n.kind == "body"})
    if not bodies:
        return {}
    profile = get_character_profile(character_name) or {}
    bsig = base_body.base_signature(character_name, profile=profile)
    out: Dict[str, str] = {}
    claimed: Set[str] = set()
    for old in bodies:
        try:
            new, why, update = _judge_body(character_name, root, old, profile=profile, bsig=bsig, busy=busy)
        except Exception as e:  # noqa: BLE001 — a body that cannot be judged is left as it is
            new, why, update = None, f"not judged: {e}", {}
        if new == old:
            logger.info("Re-key %s: outfit body %s carries its shape key already", character_name, old)
            continue
        if new is not None and new in claimed:
            new, why = None, f"another body is re-keyed onto {new}"
        if new is None:
            out[old] = STALE
            logger.info("Re-key %s: outfit body %s stays stale — %s", character_name, old, why)
            continue
        try:
            rekey_body(character_name, old, new, record=update)
        except Exception as e:  # noqa: BLE001 — rolled back: the body stays under its old id
            out[old] = STALE
            logger.warning("Re-key %s: outfit body %s not renamed to %s, stays stale — %s",
                           character_name, old, new, e)
            continue
        claimed.add(new)
        out[old] = new  # rekey_body logged it (one line per decision)
    return out


def rekey_bodies_once() -> Optional[Dict[str, Dict[str, str]]]:
    """The re-key (module docstring). None when it already ran or the mode
    migration has not run yet (the modes decide the keys), else
    ``{character: {old id: new key | "stale"}}`` (characters without a
    decision left out). A character list or hub operation list that cannot
    be read raises before anything is renamed and leaves the flag unset; a
    body that fails is logged, stays stale, and the flag is set anyway."""
    from app.models.character import list_available_characters
    from app.models.world import get_world_setting, set_world_setting
    if get_world_setting(REKEY_FLAG, strict=True):
        return None
    if not get_world_setting(FLAG, strict=True):
        logger.warning("Outfit body re-key waits: the worn-piece mode migration has not run yet")
        return None
    names = list_available_characters(include_pooled=True, include_dormant=True, strict=True)
    busy = _busy_bodies()
    result: Dict[str, Dict[str, str]] = {}
    for name in names:
        try:
            decisions = _rekey_character(name, busy)
        except Exception as e:  # noqa: BLE001 — its bodies are left as they are (stale)
            logger.warning("Re-key %s failed, its outfit bodies are left as they are: %s", name, e)
            continue
        if decisions:
            result[name] = decisions
    set_world_setting(REKEY_FLAG, "1")
    logger.info("Outfit body re-key done: %d re-keyed, %d stale",
                sum(1 for d in result.values() for v in d.values() if v != STALE),
                sum(1 for d in result.values() for v in d.values() if v == STALE))
    return result


# --- Figure stamp (Task 6, Ruling 6a) -------------------------------------------
#
# Since Task 6 an outfit model is current when its recorded ``figure`` is the
# figure delivered now (``base_body.figure_stale``). A model built before
# records none. ``stamp_figures_once`` judges every such model ONCE by the
# rule that was in force before (``legacy_current``: the current base, the
# variant its pieces call for, and the removed outfit-body-mode check — the
# mode it was built in against the mode the character's worn pieces call
# for, on an outfit body the body's current content and no own-mesh piece
# painted into it, and no own-mesh piece left painted on that has its fit
# now). A model that rule calls current gets the figure delivered now
# stamped into its sidecar, so it stays current and nothing is rebuilt; a
# stale one keeps no figure (stale, as before). Once per world (world_kv
# ``STAMP_FLAG``), after the re-key; it writes sidecars only.

#: world_kv key of the figure stamp's done flag.
STAMP_FLAG = "stamped_outfit_model_figures"
_OUTFIT_SIG_RE = re.compile(r"[0-9a-f]{12}")


def legacy_current(character_name: str, meta: Dict[str, Any], *, profile: Dict[str, Any],
                   base: Tuple[str, str]) -> bool:
    """Whether an outfit model without a recorded figure was current by the
    rule before Task 6 (block above). Read-only."""
    from app.core import base_body, garment_set
    from app.models.inventory import get_item
    if not base_body.built_on_current_base(meta, base):
        return False
    if not base_body.variant_current(character_name, meta, profile=profile):
        return False
    if meta.get("dressed") is not False:
        worn = profile.get("equipped_pieces") if isinstance(profile.get("equipped_pieces"), dict) else {}
        in_body = any(garment_set.mesh_mode_of(get_item(str(i))) == garment_set.IN_BODY
                      for i in sorted({str(v) for v in worn.values() if v}))
        built = str(meta.get("outfit_body_mode") or "retexture")
        if built != ("mesh" if in_body else "retexture"):
            return False
        if built == "mesh":
            body_id = str(meta.get("body_id") or "")
            if (not base_body.is_outfit_body_signature(body_id)
                    or base_body.file_sha256(base_body.outfit_body_path(character_name, body_id))
                    != meta.get("body_sha256")):
                return False
            if set(base_body.mesh_items_intended(meta)) - set(base_body.mesh_items_unpainted(meta)):
                return False
    return not base_body.mesh_items_ready(character_name, meta, base_sha=base[1])


def stamp_character(character_name: str) -> Dict[str, str]:
    """The stamp for one character: ``{signature: "stamped" | "stale"}`` of
    its outfit models without a recorded figure (off the pipeline: {})."""
    from app.core import base_body, figure, model3d
    from app.models.character import get_character_dir, get_character_profile
    profile = get_character_profile(character_name) or {}
    base = base_body.current_base(character_name, profile=profile)
    if base is None:
        return {}
    out: Dict[str, str] = {}
    directory = get_character_dir(character_name) / "model3d"
    for sidecar in sorted(directory.glob("*.json")) if directory.is_dir() else []:
        path = sidecar.with_suffix(".glb")
        if not _OUTFIT_SIG_RE.fullmatch(sidecar.stem) or not path.is_file():
            continue
        meta = model3d._read_sidecar(path)
        if meta.get("source") != "base_body" or not meta.get("base_signature") or "figure" in meta:
            continue
        if not legacy_current(character_name, meta, profile=profile, base=base):
            out[sidecar.stem] = STALE
            continue
        fig = figure.delivered_figure(character_name, profile=profile, pieces=dict(meta.get("pieces") or {}),
                                      items=list(meta.get("items") or []))
        model3d._publish_sidecar(path, {**meta, "figure": fig.as_dict()})
        out[sidecar.stem] = "stamped"
    return out


def stamp_figures_once() -> Optional[Dict[str, Dict[str, str]]]:
    """The figure stamp (block above). None when it already ran or the
    re-key has not run yet, else ``{character: {signature: "stamped" |
    "stale"}}``. A character list that cannot be read raises before anything
    is written and leaves the flag unset; a character that fails is logged
    (its models stay without a figure: stale) and the flag is set anyway."""
    from app.models.character import list_available_characters
    from app.models.world import get_world_setting, set_world_setting
    if get_world_setting(STAMP_FLAG, strict=True):
        return None
    if not get_world_setting(REKEY_FLAG, strict=True):
        logger.warning("Outfit model figure stamp waits: the outfit body re-key has not run yet")
        return None
    names = list_available_characters(include_pooled=True, include_dormant=True, strict=True)
    result: Dict[str, Dict[str, str]] = {}
    for name in names:
        try:
            decisions = stamp_character(name)
        except Exception as e:  # noqa: BLE001 — its models keep no figure (stale)
            logger.warning("Figure stamp %s failed, its outfit models stay unstamped: %s", name, e)
            continue
        if decisions:
            result[name] = decisions
            logger.info("Figure stamp %s: %s", name, decisions)
    set_world_setting(STAMP_FLAG, "1")
    logger.info("Outfit model figure stamp done: %d stamped, %d stale",
                sum(1 for d in result.values() for v in d.values() if v != STALE),
                sum(1 for d in result.values() for v in d.values() if v == STALE))
    return result


# --- The removed fit occasions' character globs (Task 11g fix round 1) ------
#
# The model FIT of a dressed back / side view is a CPU composite since Task
# 11g (``view_composite``): the occasions ``outfit_back`` / ``outfit_side``
# are gone (``config.REMOVED_FIT_OCCASIONS`` drops their routing chains) and
# with them the character editor's "Back fit" / "Side fit" globs. A value a
# character stored there (``profile.outfit_imagegen``) feeds nothing any
# more: ``drop_fit_globs_once`` removes it from every character row (dormant
# and pooled ones too) under ``keyed_lock("character_profile", name)``, once
# per world (world_kv ``FIT_GLOBS_FLAG``), with ONE summary INFO line naming
# the characters. A profile that does not save keeps the key (a WARNING);
# the flag is set anyway. A character list that cannot be read raises
# before anything is written and leaves the flag unset.

#: world_kv key of the done flag.
FIT_GLOBS_FLAG = "dropped_removed_fit_globs"
#: The ``outfit_imagegen`` keys that fed only the removed fit occasions.
REMOVED_FIT_GLOBS: Tuple[str, ...] = ("outfit_back_workflow", "outfit_side_workflow")


def _drop_fit_globs(name: str) -> List[str]:
    """Pop ``REMOVED_FIT_GLOBS`` from the character's ``outfit_imagegen``
    under the profile lock; the keys dropped (empty when none was there or
    the profile did not save)."""
    from app.core.keyed_lock import keyed_lock
    from app.models.character import get_character_profile, save_character_profile
    with keyed_lock("character_profile", name):
        profile = get_character_profile(name) or {}
        imagegen = profile.get("outfit_imagegen")
        if not isinstance(imagegen, dict):
            return []
        dropped = [key for key in REMOVED_FIT_GLOBS if key in imagegen]
        if not dropped:
            return []
        profile["outfit_imagegen"] = {k: v for k, v in imagegen.items() if k not in REMOVED_FIT_GLOBS}
        if save_character_profile(name, profile):
            return dropped
    logger.warning("Removed fit globs %s: profile not saved — %s stay", name, ", ".join(dropped))
    return []


def drop_fit_globs_once() -> Optional[Dict[str, List[str]]]:
    """The clean-up above. None when it already ran, else ``{character:
    [keys dropped]}``."""
    from app.models.character import list_available_characters
    from app.models.world import get_world_setting, set_world_setting
    if get_world_setting(FIT_GLOBS_FLAG, strict=True):
        return None
    names = list_available_characters(include_pooled=True, include_dormant=True, strict=True)
    result: Dict[str, List[str]] = {}
    for name in names:
        try:
            dropped = _drop_fit_globs(name)
        except Exception as e:  # noqa: BLE001 — the next character still goes
            logger.warning("Removed fit globs %s: failed: %s", name, e)
            continue
        if dropped:
            result[name] = dropped
    set_world_setting(FIT_GLOBS_FLAG, "1")
    logger.info("Removed fit occasions: outfit_imagegen.%s dropped from %d character(s)%s",
                " / ".join(REMOVED_FIT_GLOBS), len(result),
                f": {', '.join(f'{n} ({len(k)})' for n, k in sorted(result.items()))}" if result else "")
    return result


# --- The removed "Use base body pipeline" switch (Task 11h, Ruling A13) --------
#
# Every humanoid is on the base-body pipeline now (``base_body.is_base_pipeline``
# = humanoid and not a temporary NPC, Ruling A13a; an animal never is) and the
# per-character switch is gone with its
# route. Its stored profile value ``model_pipeline`` feeds nothing but ONE
# reader: the re-default above (``is_test_character``), which reads the
# STORED key on purpose to know the user's test characters. So the order is
# load-bearing: ``drop_pipeline_key_once`` runs only AFTER the re-default is
# finished for this world — the world's flag ``REDEFAULT_FLAG`` is set, and
# the shared library's marker ``SHARED_REDEFAULT_KEY`` is set or this world
# has no test character (it has nothing to give the shared re-default then).
# Until both hold it drops nothing, sets no flag and logs that it waits (the
# next start retries). Then it pops ``model_pipeline`` from every character
# row (dormant and pooled ones too) under ``keyed_lock("character_profile",
# name)``, once per world (world_kv ``PIPELINE_KEY_FLAG``), with ONE summary
# INFO line naming the characters and the values dropped. It rebuilds
# nothing: a humanoid without a base body keeps serving its existing model
# until a manual Build makes the base body (ruling 8a: an automatic Build
# never does). A profile that does not save keeps the key (a WARNING); the
# flag is set anyway. A character list or a profile that cannot be read
# raises before anything is written and leaves the flag unset.

#: world_kv key of the done flag.
PIPELINE_KEY_FLAG = "dropped_model_pipeline_key"
#: The removed per-character profile key of the "Use base body pipeline" switch.
PIPELINE_KEY = "model_pipeline"


def _pipeline_key_waits(names: Sequence[str]) -> str:
    """Why the drop must wait for the re-default (module section above), ""
    when it may run. Reads every profile ``strict``: a tester hidden behind an
    unreadable profile would lose its record before the shared re-default."""
    from app.models import inventory
    from app.models.character import get_character_profile
    from app.models.world import get_world_setting
    if not get_world_setting(REDEFAULT_FLAG, strict=True):
        return "the world's mode re-default has not run yet"
    if inventory.get_shared_items_meta(strict=True).get(SHARED_REDEFAULT_KEY):
        return ""
    testers = [n for n in names if is_test_character(n, get_character_profile(n, strict=True) or {})]
    return ("the shared library's mode re-default still needs this world's test characters ("
            + ", ".join(testers) + ")") if testers else ""


def _drop_pipeline_key(name: str) -> Optional[str]:
    """Pop ``model_pipeline`` under the profile lock; the value dropped (None
    when the key was not there or the profile did not save)."""
    from app.core.keyed_lock import keyed_lock
    from app.models.character import get_character_profile, save_character_profile
    with keyed_lock("character_profile", name):
        profile = get_character_profile(name, strict=True) or {}
        if PIPELINE_KEY not in profile:
            return None
        value = profile.pop(PIPELINE_KEY)
        if save_character_profile(name, profile):
            return str(value)
    logger.warning("Pipeline switch removal %s: profile not saved — %s stays", name, PIPELINE_KEY)
    return None


def drop_pipeline_key_once() -> Optional[Dict[str, str]]:
    """The clean-up above. None when it already ran or still waits for the
    re-default, else ``{character: value dropped}``."""
    from app.models.character import get_character_profile, list_available_characters
    from app.models.world import get_world_setting, set_world_setting
    if get_world_setting(PIPELINE_KEY_FLAG, strict=True):
        return None
    names = list_available_characters(include_pooled=True, include_dormant=True, strict=True)
    waits = _pipeline_key_waits(names)
    if waits:
        logger.info("Pipeline switch removal waits (retried at the next start): %s", waits)
        return None
    holders = [n for n in names if PIPELINE_KEY in (get_character_profile(n, strict=True) or {})]
    result: Dict[str, str] = {}
    for name in holders:
        try:
            value = _drop_pipeline_key(name)
        except Exception as e:  # noqa: BLE001 — the next character still goes
            logger.warning("Pipeline switch removal %s: failed: %s", name, e)
            continue
        if value is not None:
            result[name] = value
    set_world_setting(PIPELINE_KEY_FLAG, "1")
    logger.info("Pipeline switch removed: profile key %s dropped from %d character(s)%s — every humanoid is "
                "on the base-body pipeline, nothing rebuilt", PIPELINE_KEY, len(result),
                f": {', '.join(f'{n} ({v})' for n, v in sorted(result.items()))}" if result else "")
    return result


# --- Hairstyles as items (Task 13, D3) ------------------------------------------
#
# A character's hair was ONE thing: the hair text derived from its Appearance,
# the per-character ``hair_method`` (else the world's ``base_body.hair_method``)
# and the profile keys of its colour, placement, swing and stiffness — plus,
# under HairDeck, a hair item. Since Task 13 hair is a HAIRSTYLE: an item (a
# garment of kind hair the character owns) with its mode
# (``garment.mesh_mode``), its text (``garment.description``) and those
# settings; several owned, one worn (``equipped_mesh_pieces["hair"]``).
# ``migrate_hairstyles_once`` turns today's state into exactly that, once per
# world (world_kv ``HAIRSTYLE_FLAG``), for every character row (dormant and
# pooled ones too):
#
# - a humanoid with a hair slot and hair text (``garment_hair.
#   appearance_hair_text``) gets ONE hairstyle: mode = its STORED method
#   (``hair_migration.legacy_hair_method``: the profile's ``hair_method``,
#   else the world default), description = that hair text, settings = its
#   stored profile keys (``garment_hair.SETTING_KEYS``). A character that
#   already owns a hair item (HairDeck) gets THAT item extended — the worn
#   one, else the first owned — never a duplicate; its job folders and fits
#   stay, and its fingerprint inputs are the same values as before;
# - the hairstyle is worn and becomes the plain body's hairstyle
#   (``garment_hair.BASE_HAIRSTYLE_KEY``): the plain body's prompts read the
#   same text as before (``base_body.hair_text``), so ``base_signature``,
#   ``prompt_fingerprint`` and every stored file stay as they are — NOTHING
#   is rebuilt, no hub job, no generation;
# - the profile keys ``hair_method`` and ``SETTING_KEYS`` leave every
#   profile (a bald humanoid, a non-humanoid too).
#
# It runs only after ``hair_migration.delete_all_hair_once`` (its flag
# ``HAIR_FLAG``): that one reads the stored method too and removes the hair
# items of the removed methods first; until then it waits (the next start
# retries). The world's ``base_body.hair_method`` became
# ``base_body.hairstyle_default_mode`` at config load (``config.
# _migrate_hairstyle_default_mode``). Item first, profile second, under
# ``keyed_lock("garment_item", name)`` → ``keyed_lock("character_profile",
# name)`` (``garment_hair.create_hairstyle``'s order). A failure (an
# exception, a profile that was not saved) is a WARNING naming the character
# and the migration goes on; the flag is set only when every character went
# through (Ruling FR-minors) — else the next start runs it again, which finds
# a minted hairstyle instead of minting another. A character list or profile
# that cannot be read raises before anything is written and leaves the flag
# unset.

#: world_kv key of the done flag.
HAIRSTYLE_FLAG = "migrated_hairstyle_items"


def _legacy_settings(profile: Dict[str, Any]) -> Dict[str, Any]:
    from app.core.garment_hair import SETTING_KEYS
    return {k: profile[k] for k in SETTING_KEYS if profile.get(k) not in (None, "")}


def _hairstyle_of(name: str, profile: Dict[str, Any]) -> str:
    """Step 1 for one character (the caller holds the item lock): the id of
    the hairstyle it gets — an owned hair item extended, else a new one —
    "" for no hairstyle (bald, no humanoid, no hair slot)."""
    from app.core import garment_hair
    from app.core.hair_migration import legacy_hair_method
    from app.core.model_refs import is_humanoid
    from app.models import inventory
    if not is_humanoid(name, profile=profile):
        return ""
    slot = garment_hair._hair_slot(name, profile)
    text = garment_hair.appearance_hair_text(name, profile=profile)
    if slot is None or not text:
        return ""
    mode = legacy_hair_method(profile)
    settings = _legacy_settings(profile)
    owned = garment_hair.hairstyles(name)
    worn = garment_hair.worn_hair_id(name, profile)
    item = next((i for i in owned if i.get("id") == worn), owned[0] if owned else None)
    if item is None:
        return str(garment_hair._mint_hairstyle(name, slot.id, text, mode, settings)["id"])
    garment = dict(item.get("garment") or {})
    garment.update({"mesh_mode": mode, "description": text, **settings})
    garment.setdefault("body_slot", slot.id)
    if garment != (item.get("garment") or {}) and inventory.update_item(item["id"], {"garment": garment}) is None:
        raise RuntimeError(f"hair item {item['id']} not updated")
    return str(item["id"])


def _migrate_hairstyle(name: str) -> Tuple[str, List[str]]:
    """``(hairstyle id or "", profile keys dropped)`` of one character."""
    from app.core import garment_hair
    from app.core.hair_migration import LEGACY_METHOD_KEY
    from app.core.keyed_lock import keyed_lock
    from app.models.character import get_character_profile, save_character_profile
    with keyed_lock("garment_item", name):
        item_id = _hairstyle_of(name, get_character_profile(name, strict=True) or {})
        with keyed_lock("character_profile", name):
            profile = get_character_profile(name, strict=True) or {}
            dropped = [k for k in (LEGACY_METHOD_KEY, *garment_hair.SETTING_KEYS) if k in profile]
            for key in dropped:
                profile.pop(key)
            changed = bool(dropped)
            if item_id:
                worn = profile.get("equipped_mesh_pieces")
                worn = dict(worn) if isinstance(worn, dict) else {}
                if worn.get(garment_hair.HAIR_KIND) != item_id:
                    worn[garment_hair.HAIR_KIND] = item_id
                    profile["equipped_mesh_pieces"] = worn
                    changed = True
                if profile.get(garment_hair.BASE_HAIRSTYLE_KEY) != item_id:
                    profile[garment_hair.BASE_HAIRSTYLE_KEY] = item_id
                    changed = True
            if changed and not save_character_profile(name, profile):
                # Ruling FR-minors: a failure, so the migration is retried at the next start.
                raise RuntimeError(f"profile not saved — {item_id or 'no hairstyle'} stays unworn, keys "
                                   f"{', '.join(dropped) or 'none'} stay")
    return item_id, dropped


def migrate_hairstyles_once() -> Optional[Dict[str, str]]:
    """The migration above. None when it already ran or still waits for the
    hair migration, else ``{character: hairstyle id}`` (characters that got
    none are left out). Done (``HAIRSTYLE_FLAG``) only when every character
    went through (Ruling FR-minors): one that failed — an exception, a
    profile that was not saved — is logged and the whole migration runs
    again at the next start (it is idempotent: a worn hairstyle is found,
    never minted twice)."""
    from app.core.hair_migration import HAIR_FLAG
    from app.models.character import list_available_characters
    from app.models.world import get_world_setting, set_world_setting
    if get_world_setting(HAIRSTYLE_FLAG, strict=True):
        return None
    if not get_world_setting(HAIR_FLAG, strict=True):
        logger.info("Hairstyle migration waits for the hair migration (retried at the next start)")
        return None
    names = list_available_characters(include_pooled=True, include_dormant=True, strict=True)
    result: Dict[str, str] = {}
    keys = 0
    failed: List[str] = []
    for name in names:
        try:
            item_id, dropped = _migrate_hairstyle(name)
        except Exception as e:  # noqa: BLE001 — the next character still goes
            logger.warning("Hairstyle migration %s: failed: %s", name, e)
            failed.append(name)
            continue
        keys += len(dropped)
        if item_id:
            result[name] = item_id
    if failed:
        logger.warning("Hairstyle migration not done — %d character(s) failed (%s); retried at the next start",
                       len(failed), ", ".join(failed))
    else:
        set_world_setting(HAIRSTYLE_FLAG, "1")
    logger.info("Hairstyles: %d character(s) got their hairstyle worn, %d legacy hair key(s) dropped%s — "
                "nothing rebuilt", len(result), keys,
                f": {', '.join(f'{n} ({i})' for n, i in sorted(result.items()))}" if result else "")
    return result
