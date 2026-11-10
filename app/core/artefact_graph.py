"""The artefact graph of one character — every derived 3D file, its parents,
the roots, and the ONE collector that deletes what no root reaches (plan
``docs/superpowers/plans/2026-11-10-outfit-body-mesh-mode.md``, Task 3).

WHY. A character's derived files form chains: base → painted texture / outfit
body → fits per body → assemblies. Every delete path used to remove its own
link and leave the rest of the chain behind (an item delete purged the outfit
models but none of its fits, a base change left every outfit body of the old
base on disk, a crashed run left its whole stage). Here the chain is computed
once, from the files themselves, and every delete path runs the same walk.

SCOPE. The three derived roots of a character directory: ``model3d/``,
``model_refs/`` and ``garments/``. Images, outfit pictures, expressions and
soul files are not derived 3D artefacts and are never touched.

NODES (the report key in brackets; a file belongs to exactly one node):

* outfit ``<sig>`` — an outfit combination (md5[:12], pose-state refs
  ``<sig>-p…``, retired forks ``-s…``): refs ``model_refs/{tpose*,pose}_<sig>``
  (+ ``drafts/``), the model group ``model3d/[<tier>/]<sig>.*`` incl.
  ``assembled/`` (the garment assembly) and ``rollback/<sig>/``. Category
  ``refs`` / ``meshes`` (two nodes, one key).
* base ``base<8hex>`` — a base body, same layout (+ ``covered/``).
* body ``ob<8hex>`` — an outfit body of the mesh mode, same layout; parent
  record ``outfit_body {body_id, texture_signature, base_signature, …}`` in
  its sidecars.
* texture ``texture:<tsig>`` — the texture store: dressed views
  ``model_refs/texture/[drafts/]`` + the painted body ``model3d/texture/``;
  parent ``base_signature`` in its sidecars.
* garment ``garment:<item>_<fsig>`` — the shared garment files of one
  fingerprint (images, raw, prepared) and its fit on the BASE body (fit,
  ``low/``, ``layers/``, ``failed/``); parents item + fsig (fsig contains the
  base signature).
* body fit ``bodyfit:<body>:<item>_<fsig>`` — the same parts on an outfit
  body: ``garments/bodies/<body>/…``; parents the body and ``garment:<item>_<fsig>``.
* HairDeck job ``hairdeck:<item>_<hsig>`` — the folder ``garments/raw/<item>_<hsig>/``.
* temp ``temp:<path>`` — a dot-named entry anywhere below the three roots:
  a ``.process-*`` stage, a ``.fitgate_*`` / ``.fitref_*`` / ``.viewref_*``
  work folder, a ``.tmp`` write. A process that dies leaves them behind.
* ``face_view`` — ``model_refs/face_view.*`` (from the profile picture): a root.

Anything else below the three roots is ``unknown``: listed, never deleted.

ROOTS: the worn outfit; the outfit combinations the character can still
produce (``outfit_cache_gc``'s outfit rule — manifest re-sign against the
inventory, else the reachable set over it; what the outfit batch pre-builds,
saved outfit sets included); the CURRENT base signature (none for a
non-humanoid; unknown = nothing base-derived is judged); the equipped / held
own-mesh garments with their current fsig (``outfit_cache_gc._garment_roots``,
R11 served fit included); the character's outfit body mode.

REACHABILITY (one function each, ``_judge``):

* outfit: the outfit rule; the worn one always.
* base: exactly the current base signature.
* texture: named (``texture_signature``) by a sidecar of a LIVE outfit and
  no sidecar of it names another base than the current one. Both modes: the
  dressed views are the mesher input of the outfit body too, and the painted
  body is small and CPU-made — mode back never re-renders (Task 5).
* body: its record names the CURRENT base AND either the mode is ``mesh``
  and its texture is live, or a live outfit model still names it as
  ``body_id`` (a model built in mesh mode stays served after a switch to
  retexture until it is rebuilt; its assembly still needs the body fits).
* garment: ``_garment_roots`` (current fsig, served fit, newest accepted per
  method). Body fit: its body AND its garment group are reachable.
* HairDeck job: its item is kept and the hsig is the item's current one or
  is named by a kept fit (``inputs.hsig``: a refit needs the seed files).
* temp: younger than ``TEMP_GRACE_S`` or a live stage of this process
  (``model3d.active_stages``).

RULINGS.

* BASE REGENERATED: a new base signature makes everything derived from the
  old one unreachable at once — base group, its textures, its outfit bodies
  and their body fits. Never served stale: an outfit body is never served
  itself (an outfit model is a copy of it) and a new base signature means a
  new tsig, so a new body id — the old body could never be reused. A base
  MODEL regenerated under the same signature keeps the bodies (own mesh +
  rig, Task 1 ruling); fits are refitted in place (same names). Base fits of
  an older fingerprint follow R11 (served until the new fit is accepted).
* MODE: see body/texture above.

SAFETY. Never deleted: what is running — a live model stage of the
signature, an open hub operation on it (``hub_ops`` subject
``model3d:<char>:<sig>``), the base model / outfit body run in progress
(``base_body`` status), an outfit body whose build lock
(``keyed_lock("outfit_body", …)``) another thread holds, a garment item with
a run or a queued run, the fits of a body being fitted
(``keyed_lock("garment_body_fit", …)``) —, the worn combination (the model
served for it; a "nearest" stand-in served for an outfit without a model is
judged like any outfit — gone, the serving chain picks the next nearest), and
(sweep only) any node with a file younger than ``GRACE_S``. Every judgement that cannot
be computed (an exception in the inventory, the base, the garment roots, a
reachable set over ``REACHABLE_BUDGET_S``) keeps everything it would have
judged. An outfit entry WITHOUT a manifest is the only one that needs the
reachable set; a key not shaped like a signature never does. An automatic
collect (hooks, sweep) runs under ``HOOK_BUDGET_S`` and deletes nothing when
it overruns. Deletion takes the model locks of the signature (``model3d`` →
``model3d_publication``, the order of a publication). One summary log line
per collect, with its duration.
"""
from __future__ import annotations

import json
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple

from app.core.log import get_logger

logger = get_logger("artefact_graph")

#: A node with a file younger than this is skipped by the automatic sweep
#: (an explicit delete ignores it): a run may be writing the next file of it.
GRACE_S = 10 * 60
#: A dot-named work folder younger than this is never removed. A live stage
#: of THIS process is protected by registration; the grace covers a stage of
#: another process (a script) and the short-lived work folders.
TEMP_GRACE_S = 24 * 3600
#: Wall-clock budget of the reachable-set enumeration (only an outfit entry
#: WITHOUT a manifest needs it). One signature costs ~1.5 ms, a wardrobe of a
#: million combinations ~25 minutes; past the budget the entries it would
#: have judged are kept ("undetermined").
REACHABLE_BUDGET_S = 5.0
#: Budget of one automatic collect (a delete-path hook, the daily sweep):
#: past it the judgement is abandoned and NOTHING is deleted.
HOOK_BUDGET_S = 30.0

ROOT_DIRS = ("model3d", "model_refs", "garments")
CATEGORIES = ("refs", "meshes", "garments", "textures", "body_fits", "hairdeck", "temp")

_OUTFIT_BODY_RE = re.compile(r"ob[0-9a-f]{8}")
_BASE_SIG_RE = re.compile(r"base[0-9a-f]{8}")
_HAIRDECK_DIR_RE = re.compile(r"(?P<item>[A-Za-z0-9][A-Za-z0-9_-]*)_(?P<hsig>[0-9a-f]{12})")


@dataclass
class Node:
    key: str
    kind: str        # outfit | base | body | texture | garment | body_fit | hairdeck | temp | face_view
    category: str    # report bucket (CATEGORIES), "" for face_view
    files: List[Path] = field(default_factory=list)
    dirs: List[Path] = field(default_factory=list)   # owned folders, removed whole when empty after
    parents: Dict[str, Any] = field(default_factory=dict)
    reachable: bool = True
    reason: str = ""
    protected: str = ""

    def size(self) -> int:
        total = 0
        for p in self.files:
            try:
                total += p.stat().st_size
            except OSError:
                pass
        return total

    def newest_mtime(self) -> float:
        """Newest mtime of the node's files (a temp node: its folder too —
        an empty stage of a run that just started is young)."""
        newest = 0.0
        for p in list(self.files) + (list(self.dirs) if self.kind == "temp" else []):
            try:
                newest = max(newest, p.stat().st_mtime)
            except OSError:
                pass
        return newest


@dataclass
class Roots:
    worn: str = ""
    #: the current base signature; "" = none (non-humanoid), None = unknown
    base: Optional[str] = None
    #: "mesh" | "retexture" | "off" | "" (unknown: bodies are not judged)
    mode: str = ""
    #: item ids in the inventory; None = unreadable (no outfit is judged then)
    owned: Optional[Set[str]] = field(default_factory=set)
    #: garment keys kept (``garment:<item>_<fsig>``), None = not computable
    garment_keep: Optional[Set[str]] = None
    garment_items: Set[str] = field(default_factory=set)
    #: the kept hair items; their current hsig is computed only when a
    #: HairDeck job folder exists (``_hair_hsig``)
    hair_items: Set[str] = field(default_factory=set)
    running_sigs: Set[str] = field(default_factory=set)
    running_items: Set[str] = field(default_factory=set)
    reachable: Optional[Callable[[], Set[str]]] = None
    #: why the reachable set could not be computed ("" = it could / was not needed)
    undetermined: str = ""


class GcOverBudget(RuntimeError):
    """A collect ran past its deadline — abandoned, nothing deleted."""


@dataclass
class Analysis:
    character: str
    roots: Roots
    nodes: List[Node]
    unknown: List[Path]


# --- Scan -----------------------------------------------------------------------

def _char_dir(character_name: str) -> Path:
    from app.models.character import get_character_dir
    return get_character_dir(character_name)


def _walk(root: Path) -> Tuple[List[Path], List[Path]]:
    """``(files, temp entries)`` below ``root``: a dot-named entry is a temp
    entry and is not descended into."""
    files: List[Path] = []
    temps: List[Path] = []
    if not root.is_dir():
        return files, temps
    stack = [root]
    while stack:
        folder = stack.pop()
        try:
            entries = sorted(folder.iterdir())
        except OSError:
            continue
        for p in entries:
            if p.name.startswith("."):
                temps.append(p)
            elif p.is_dir() and not p.is_symlink():
                stack.append(p)
            elif p.is_file() or p.is_symlink():
                files.append(p)
    return files, temps


def _tree_files(path: Path) -> List[Path]:
    if path.is_file() or path.is_symlink():
        return [path]
    return [p for p in sorted(path.rglob("*")) if p.is_file() or p.is_symlink()]


def _sig_kind(signature: str) -> str:
    """``body`` / ``base`` / ``outfit`` — or "" for a name no producer of
    this code writes (a hand-placed test model ``s1ap.glb``): its files stay
    ``unknown``, listed and never deleted."""
    if _OUTFIT_BODY_RE.fullmatch(signature):
        return "body"
    if _BASE_SIG_RE.fullmatch(signature):
        return "base"
    from app.core.model_refs import neutral_signature
    from app.core.outfit_cache_gc import _OUTFIT_SIG_RE
    return "outfit" if _OUTFIT_SIG_RE.fullmatch(neutral_signature(signature)) else ""


def scan(character_name: str) -> Tuple[List[Node], List[Path]]:
    """Every node of the character's three derived roots + the unknown files."""
    from app.core import garment_store, outfit_cache_gc as ocg
    root = _char_dir(character_name)
    nodes: List[Node] = []
    for category, files_of in (("refs", ocg._ref_files), ("meshes", ocg._mesh_files)):
        for signature, files in files_of(character_name).items():
            # A dot-named file (an atomic write in flight) is a temp entry, never a signature's.
            files = [p for p in files if not p.name.startswith(".")]
            kind = _sig_kind(signature) if signature and not signature.startswith(".") else ""
            if files and kind:
                nodes.append(Node(signature, kind, category, files))
    rollback = root / "model3d" / "rollback"
    for node in nodes:
        if node.category == "meshes" and (rollback / node.key).is_dir():
            node.dirs.append(rollback / node.key)
    for tkey, files in ocg._texture_files(character_name).items():
        nodes.append(Node(tkey, "texture", "textures", list(files),
                          parents={"texture_signature": tkey[len(ocg.TEXTURE_KEY_PREFIX):]}))
    bodies_root = garment_store._root(character_name) / garment_store.BODIES_DIR
    for (item_id, fsig), files in garment_store.stored_groups(character_name).items():
        by_body: Dict[str, List[Path]] = {}
        for p in files:
            by_body.setdefault(garment_store.body_of(p), []).append(p)
        for body, body_files in sorted(by_body.items()):
            gkey = ocg._garment_key(item_id, fsig)
            if not body:
                nodes.append(Node(gkey, "garment", "garments", body_files,
                                  parents={"item_id": item_id, "fsig": fsig}))
            else:
                nodes.append(Node(f"bodyfit:{body}:{item_id}_{fsig}", "body_fit", "body_fits", body_files,
                                  dirs=[bodies_root / body],
                                  parents={"item_id": item_id, "fsig": fsig, "body_id": body,
                                           "garment": gkey}))
    raw = garment_store._root(character_name) / garment_store.PART_DIRS["raw"]
    if raw.is_dir():
        for folder in sorted(raw.iterdir()):
            match = _HAIRDECK_DIR_RE.fullmatch(folder.name)
            if not match or not folder.is_dir() or folder.is_symlink():
                continue
            files = [p for p in _tree_files(folder)
                     if not any(part.startswith(".") for part in p.relative_to(folder).parts)]
            nodes.append(Node(f"hairdeck:{folder.name}", "hairdeck", "hairdeck", files, dirs=[folder],
                              parents={"item_id": match.group("item"), "hsig": match.group("hsig")}))
    face = [p for p in sorted((root / "model_refs").glob("face_view.*")) if p.is_file()]
    if face:
        nodes.append(Node("face_view", "face_view", "", face))
    all_files: List[Path] = []
    for name in ROOT_DIRS:
        files, temps = _walk(root / name)
        all_files += files
        for temp in temps:
            nodes.append(Node(f"temp:{temp.relative_to(root).as_posix()}", "temp", "temp",
                              _tree_files(temp), dirs=[temp] if temp.is_dir() else []))
    claimed = {p for n in nodes if n.kind != "temp" for p in n.files}
    unknown = [p for p in all_files if p not in claimed]
    return nodes, unknown


# --- Roots ----------------------------------------------------------------------

def running_keys(character_name: str) -> Tuple[Set[str], Set[str]]:
    """``(signatures, garment items)`` with work in progress for the character."""
    sigs: Set[str] = set()
    items: Set[str] = set()
    try:
        from app.core import model3d
        for _path, (name, sig) in model3d.active_stages().items():
            if name == character_name and sig:
                sigs.add(str(sig))
    except Exception:
        logger.exception("Artefact GC %s: stage registry unreadable", character_name)
    try:
        from app.core import base_body
        with base_body._status_lock:
            model_sig = base_body._model_running.get(character_name)
            outfit_sigs = [sig for (name, _stage), sig in base_body._outfit_running.items()
                           if name == character_name]
        sigs.update(s for s in [model_sig, *outfit_sigs] if s)
    except Exception:
        logger.exception("Artefact GC %s: base body status unreadable", character_name)
    try:
        from app.core import hub_ops
        prefix = f"model3d:{character_name}:"
        for op in hub_ops.list_ops():
            if op.status in (hub_ops.RUNNING, hub_ops.DEFERRED) and str(op.subject or "").startswith(prefix):
                sigs.add(str(op.subject)[len(prefix):])
    except Exception:
        logger.exception("Artefact GC %s: hub operations unreadable", character_name)
    try:
        from app.core import garment_store, garments
        with garment_store._status_lock:
            items.update(item for (name, item) in garment_store._running if name == character_name)
        with garments._lock:
            items.update(job.item_id for job in garments._queues.get(character_name, ()) or ())
    except Exception:
        logger.exception("Artefact GC %s: garment runs unreadable", character_name)
    return sigs, items


def compute_roots(character_name: str) -> Roots:
    """The roots of the character (module docstring)."""
    from app.core import outfit_cache_gc as ocg
    roots = Roots()
    roots.worn = ocg._worn_signature(character_name)
    roots.base = ocg._current_base_signature(character_name)
    try:
        from app.core import base_body
        from app.models.character import get_character_profile
        profile = get_character_profile(character_name) or {}
        if not base_body.is_base_pipeline(character_name, profile=profile):
            roots.mode = "off"
        else:
            roots.mode = base_body.outfit_body_mode(character_name, profile=profile)
    except Exception:
        logger.exception("Artefact GC %s: outfit body mode unavailable", character_name)
        roots.mode = ""
    try:
        from app.models.inventory import get_character_inventory
        entries = (get_character_inventory(character_name) or {}).get("inventory") or []
        roots.owned = {str(e.get("item_id") or "") for e in entries if e.get("item_id")}
    except Exception:
        logger.exception("Artefact GC %s: inventory unreadable — no outfit is judged", character_name)
        roots.owned = None
    garment = ocg._garment_roots(character_name)
    if garment is not None:
        roots.garment_keep, roots.garment_items, roots.hair_items = garment
    roots.running_sigs, roots.running_items = running_keys(character_name)
    memo: List[Set[str]] = []

    def reachable() -> Set[str]:
        # Computed at most once per analysis; a refusal is remembered so the
        # next manifest-less entry does not pay the budget again.
        if roots.undetermined:
            raise ValueError(roots.undetermined)
        if not memo:
            started = time.monotonic()
            try:
                memo.append(ocg.reachable_signatures(character_name,
                                                     deadline=started + REACHABLE_BUDGET_S))
            except ValueError as exc:
                roots.undetermined = str(exc)
                logger.warning("Artefact GC %s: reachable set not computed (%s) — "
                               "outfit entries without a manifest are kept", character_name, exc)
                raise
            logger.info("Artefact GC %s: reachable set of %d signature(s) in %.1f s",
                        character_name, len(memo[0]), time.monotonic() - started)
        return memo[0]
    roots.reachable = reachable
    return roots


# --- Judgement ------------------------------------------------------------------

def _json(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _outfit_valid(character_name: str, node: Node, roots: Roots) -> bool:
    """``outfit_cache_gc``'s outfit rule for one outfit node."""
    from app.core import outfit_cache_gc as ocg
    if node.category == "meshes":
        if not ocg._has_top_model(node.key, node.files):
            return False
        from app.core.model3d import _stored_manifest
        manifest = _stored_manifest(character_name, node.key)
    else:
        manifest = ocg.read_manifest(ocg._sidecar_of(node.files) or Path("/nonexistent"))
    return ocg._entry_valid(node.key, manifest, roots.owned, roots.reachable, character_name)


def _outfit_sidecars(root: Path, signature: str) -> List[Path]:
    """The sidecars that speak for an outfit combination: its model and its
    T-pose refs (top level)."""
    out = [root / "model3d" / f"{signature}.json"]
    out += sorted((root / "model_refs").glob(f"tpose*_{signature}.json"))
    return [p for p in out if p.is_file()]


def _body_record(root: Path, body_id: str) -> Dict[str, Any]:
    for path in (root / "model3d" / f"{body_id}.json", root / "model3d" / "unrigged" / f"{body_id}.json",
                 root / "model3d" / "prerig" / f"{body_id}.json", root / "model_refs" / f"tpose_{body_id}.json"):
        record = _json(path).get("outfit_body")
        if isinstance(record, dict):
            return record
    for path in sorted((root / "model_refs").glob(f"tpose_*_{body_id}.json")):
        record = _json(path).get("outfit_body")
        if isinstance(record, dict):
            return record
    return {}


def _hair_hsig(character_name: str, item_id: str) -> str:
    """The item's current HairDeck fingerprint, "" when it cannot be computed
    (its jobs are kept then)."""
    try:
        from app.core import garment_store
        return garment_store.garment_hsig(character_name, item_id)
    except Exception:  # noqa: BLE001 — unknown hsig: never delete on a guess
        logger.exception("Artefact GC %s: HairDeck fingerprint of %s unavailable", character_name, item_id)
        return ""


def _check_deadline(deadline: Optional[float], character_name: str) -> None:
    if deadline is not None and time.monotonic() > deadline:
        raise GcOverBudget(f"artefact GC of {character_name} over its time budget")


def _judge(character_name: str, nodes: List[Node], roots: Roots,
           deadline: Optional[float] = None) -> None:
    """Set ``reachable`` + ``reason`` on every node (module docstring).
    Raises ``GcOverBudget`` once ``deadline`` (``time.monotonic()``) passes."""
    root = _char_dir(character_name)
    # 1. Outfit combinations — the roots every other chain hangs from.
    live: Set[str] = set()
    for node in nodes:
        if node.kind != "outfit":
            continue
        _check_deadline(deadline, character_name)
        if roots.worn and node.key == roots.worn:
            node.reachable, node.reason = True, "worn"
        elif roots.owned is None:
            node.reachable, node.reason = True, "inventory unknown"
        else:
            try:
                valid = _outfit_valid(character_name, node, roots)
            except ValueError as exc:
                node.reachable, node.reason = True, f"producibility undetermined: {exc}"
            else:
                node.reachable, node.reason = ((True, "producible outfit") if valid
                                               else (False, "no producible outfit"))
        if node.reachable:
            live.add(node.key)
    if roots.worn:
        live.add(roots.worn)
    live_tsigs: Set[str] = set()
    named_bodies: Set[str] = set()
    for sig in sorted(live):
        for sidecar in _outfit_sidecars(root, sig):
            meta = _json(sidecar)
            tsig = meta.get("texture_signature")
            if isinstance(tsig, str) and tsig:
                live_tsigs.add(tsig)
            body = meta.get("body_id")
            if sidecar.parent.name == "model3d" and isinstance(body, str) and body:
                named_bodies.add(body)
    # 2. Base bodies.
    for node in nodes:
        if node.kind != "base":
            continue
        if roots.base is None:
            node.reachable, node.reason = True, "base unknown"
        elif node.key == roots.base:
            node.reachable, node.reason = True, "current base"
        else:
            node.reachable, node.reason = False, "older base"
    # 3. Outfit bodies (refs + model group judged once per id).
    body_verdicts: Dict[str, Tuple[bool, str, Dict[str, Any]]] = {}
    for node in nodes:
        if node.kind != "body":
            continue
        if node.key not in body_verdicts:
            record = _body_record(root, node.key)
            parents = {k: record.get(k) for k in ("body_id", "texture_signature", "base_signature")}
            if roots.base is None or not roots.mode:
                verdict = (True, "base or mode unknown")
            elif not roots.base or record.get("base_signature") != roots.base:
                verdict = (False, "older base")
            elif roots.mode == "mesh" and record.get("texture_signature") in live_tsigs:
                verdict = (True, "texture of a live outfit (mesh mode)")
            elif node.key in named_bodies:
                verdict = (True, "named by a live outfit model")
            else:
                verdict = (False, "no live outfit on it" if roots.mode == "mesh"
                           else f"not used in {roots.mode} mode")
            body_verdicts[node.key] = (*verdict, parents)
        node.reachable, node.reason, parents = body_verdicts[node.key]
        node.parents = dict(parents)
    body_ok = {key: verdict[0] for key, verdict in body_verdicts.items()}
    # 4. Texture store.
    for node in nodes:
        if node.kind != "texture":
            continue
        tsig = node.parents.get("texture_signature")
        if tsig not in live_tsigs:
            node.reachable, node.reason = False, "no live outfit names it"
            continue
        bases = {(_json(p).get("base_signature")) for p in node.files if p.suffix.lower() == ".json"}
        bases.discard(None)
        bases.discard("")
        if roots.base is not None and any(b != roots.base for b in bases):
            node.reachable, node.reason = False, "older base"
        else:
            node.reachable, node.reason = True, "texture of a live outfit"
    # 5. Garments, their fits per body, HairDeck jobs.
    garment_ok: Dict[str, bool] = {}
    for node in nodes:
        if node.kind != "garment":
            continue
        if roots.garment_keep is None:
            node.reachable, node.reason = True, "garment roots unknown"
        elif node.key in roots.garment_keep:
            node.reachable, node.reason = True, "kept fit"
        else:
            node.reachable, node.reason = False, "no held garment uses this fingerprint"
        garment_ok[node.key] = node.reachable
    for node in nodes:
        if node.kind != "body_fit":
            continue
        body = node.parents["body_id"]
        gkey = node.parents["garment"]
        g_ok = True if roots.garment_keep is None else (garment_ok.get(gkey, False) or gkey in roots.garment_keep)
        b_ok = body_ok.get(body, False)
        node.reachable = g_ok and b_ok
        node.reason = ("fit of a kept garment on a live body" if node.reachable
                       else "body gone" if not b_ok else "garment fingerprint gone")
    kept_hsigs: Dict[str, Set[str]] = {}
    for node in nodes:
        if node.kind != "garment" or not node.reachable:
            continue
        for p in node.files:
            if p.suffix == ".json" and p.parent.name == "garments":
                inputs = _json(p).get("inputs")
                if isinstance(inputs, dict) and inputs.get("hsig"):
                    kept_hsigs.setdefault(node.parents["item_id"], set()).add(str(inputs["hsig"]))
    current_hsig: Dict[str, str] = {}
    for node in nodes:
        if node.kind != "hairdeck":
            continue
        item, hsig = node.parents["item_id"], node.parents["hsig"]
        if item in roots.hair_items and item not in current_hsig:
            current_hsig[item] = _hair_hsig(character_name, item)
        if roots.garment_keep is None:
            node.reachable, node.reason = True, "garment roots unknown"
        elif item not in roots.garment_items:
            node.reachable, node.reason = False, "item not held"
        elif current_hsig.get(item, "") in ("", hsig):
            node.reachable, node.reason = True, "current HairDeck job"
        elif hsig in kept_hsigs.get(item, set()):
            node.reachable, node.reason = True, "job of a kept fit"
        else:
            node.reachable, node.reason = False, "older HairDeck job"
    # 6. Temp work folders.
    from app.core.timeutils import utc_now
    try:
        from app.core import model3d
        active = set(model3d.active_stages())
    except Exception:
        active = set()
    now = utc_now().timestamp()
    for node in nodes:
        if node.kind != "temp":
            continue
        target = node.dirs[0] if node.dirs else (node.files[0] if node.files else None)
        if target is not None and str(target.resolve()) in active:
            node.reachable, node.reason = True, "live stage"
        elif now - node.newest_mtime() < TEMP_GRACE_S:
            node.reachable, node.reason = True, "recent work folder"
        else:
            node.reachable, node.reason = False, "left behind by an ended run"
    for node in nodes:
        if node.kind == "face_view":
            node.reachable, node.reason = True, "profile picture"


def _protect(nodes: List[Node], roots: Roots, *, explicit: bool) -> None:
    """Mark unreachable nodes that must not go now (``protected``)."""
    from app.core.timeutils import utc_now
    now = utc_now().timestamp()
    for node in nodes:
        if node.reachable:
            continue
        item = node.parents.get("item_id")
        if node.kind in ("outfit", "base", "body") and (node.key in roots.running_sigs
                                                        or (roots.worn and node.key == roots.worn)):
            node.protected = "running"
        elif node.kind == "body_fit" and node.parents.get("body_id") in roots.running_sigs:
            node.protected = "running"
        elif item and item in roots.running_items:
            node.protected = "running"
        elif not explicit and node.kind != "temp" and now - node.newest_mtime() < GRACE_S:
            node.protected = "grace"


def analyse(character_name: str, *, roots: Optional[Roots] = None, explicit: bool = True,
            deadline: Optional[float] = None) -> Analysis:
    """The judged graph of a character (read-only). ``deadline``
    (``time.monotonic()``): raises ``GcOverBudget`` once it passes."""
    nodes, unknown = scan(character_name)
    _check_deadline(deadline, character_name)
    roots = roots if roots is not None else compute_roots(character_name)
    _check_deadline(deadline, character_name)
    _judge(character_name, nodes, roots, deadline)
    _protect(nodes, roots, explicit=explicit)
    return Analysis(character_name, roots, nodes, unknown)


# --- Deletion -------------------------------------------------------------------

def _try_lock(namespace: str, key: str):
    """The keyed lock when no OTHER thread holds it (acquired), else None."""
    from app.core.keyed_lock import keyed_lock
    lock = keyed_lock(namespace, key)
    return lock if lock.acquire(blocking=False) else None


def _remove(paths: Iterable[Path], allowed_root: Path) -> Tuple[int, int]:
    """Unlink files inside ``allowed_root``; ``(files, bytes)`` removed."""
    count = freed = 0
    base = allowed_root.resolve()
    for p in paths:
        try:
            if not p.resolve().is_relative_to(base) or p.resolve() == base:
                logger.warning("Artefact GC: %s outside %s, not removed", p, allowed_root)
                continue
            size = p.lstat().st_size
            p.unlink()
            count += 1
            freed += size
        except FileNotFoundError:
            continue
        except OSError as e:
            logger.warning("Artefact GC: %s not removed: %s", p, e)
    return count, freed


def _prune_empty(folder: Path, stop: Path) -> None:
    """Remove ``folder`` and its empty sub-folders, then empty parents up to
    (not including) ``stop``."""
    if not folder.is_dir() or folder.is_symlink():
        return
    for sub in sorted((p for p in folder.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
        try:
            sub.rmdir()
        except OSError:
            pass
    current = folder
    while current != stop and current.is_relative_to(stop):
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent


def _delete_node(character_name: str, node: Node, root: Path) -> Tuple[int, int, str]:
    """Delete one node under the locks its kind needs; ``(files, bytes,
    skip reason)``."""
    from app.core.keyed_lock import keyed_lock
    if node.kind in ("outfit", "base", "body"):
        held = []
        if node.kind == "body":
            lock = _try_lock("outfit_body", f"{character_name}:{node.key}")
            if lock is None:
                return 0, 0, "running"
            held.append(lock)
        try:
            from app.core import model3d
            directory = root / "model3d"
            with keyed_lock("model3d", f"{character_name}:{node.key}"), \
                    keyed_lock("model3d_publication", str(directory)):
                if any(sig == node.key and name == character_name
                       for name, sig in model3d.active_stages().values()):
                    return 0, 0, "running"
                count, freed = _remove(node.files, root)
                for folder in node.dirs:
                    _prune_empty(folder, directory / "rollback")
                key = (str(directory), node.key)
                model3d._publication_epochs[key] = model3d._publication_epochs.get(key, 0) + 1
            return count, freed, ""
        finally:
            for lock in held:
                lock.release()
    if node.kind in ("garment", "body_fit", "hairdeck"):
        from app.core import garment_store
        garments_root = garment_store._root(character_name)
        held = []
        if node.kind == "body_fit":
            lock = _try_lock("garment_body_fit", f"{character_name}:{node.parents['body_id']}")
            if lock is None:
                return 0, 0, "running"
            held.append(lock)
        try:
            count, freed = _remove(node.files, garments_root)
            # A folder (a body's fits, a HairDeck job) goes only once it is empty.
            for folder in node.dirs:
                _prune_empty(folder, folder.parent)
            if node.kind == "body_fit":
                _prune_empty(garments_root / garment_store.BODIES_DIR, garments_root)
            return count, freed, ""
        finally:
            for lock in held:
                lock.release()
    if node.kind == "texture":
        return (*_remove(node.files, root), "")
    if node.kind == "temp":
        target = node.dirs[0] if node.dirs else (node.files[0] if node.files else None)
        if target is None:
            return 0, 0, ""
        size = node.size()
        count = len(node.files)
        try:
            if not target.resolve().is_relative_to(root.resolve()):
                return 0, 0, "outside"
            if target.is_dir() and not target.is_symlink():
                shutil.rmtree(target)
            else:
                target.unlink()
        except FileNotFoundError:
            return 0, 0, ""
        except OSError as e:
            logger.warning("Artefact GC %s: %s not removed: %s", character_name, target, e)
            return 0, 0, "error"
        return count, size, ""
    return 0, 0, "not deletable"


def _descendants(nodes: List[Node], keys: Set[str]) -> Set[str]:
    """``keys`` plus the body fits hanging from a wanted garment or body key."""
    out = set(keys)
    for node in nodes:
        if node.kind == "body_fit" and (node.parents.get("garment") in keys or node.parents.get("body_id") in keys):
            out.add(node.key)
    return out


def _entry(node: Node) -> Dict[str, Any]:
    return {"key": node.key, "kind": node.kind, "category": node.category, "files": len(node.files),
            "bytes": node.size(), "reason": node.reason, "protected": node.protected,
            "parents": {k: v for k, v in node.parents.items() if v}}


def collect(character_name: str, *, dry_run: bool = False, explicit: bool = False,
            keys: Optional[Iterable[str]] = None, reason: str = "",
            roots: Optional[Roots] = None, budget_s: Optional[float] = None) -> Dict[str, Any]:
    """Delete every unreachable node of the character (``keys``: only those
    and the body fits hanging from them) — or, with ``dry_run``, only list
    them. ``explicit`` (a delete path, a click) skips the grace window; what
    is running is never deleted. Returns ``{character, reason, dry_run,
    explicit, orphans: [...], deleted_files, freed_bytes, skipped: [...],
    unknown: [...], totals: {category: {total, reachable, orphans, bytes}},
    seconds, aborted}``. ``budget_s``: a judgement that runs past it is
    abandoned and NOTHING is deleted (``aborted`` names why) — an automatic
    caller must never hang on a pathological wardrobe. Never mints a
    directory for a vanished character."""
    report: Dict[str, Any] = {"character": character_name, "reason": reason, "dry_run": dry_run,
                              "explicit": explicit, "orphans": [], "deleted_files": 0, "freed_bytes": 0,
                              "skipped": [], "unknown": [], "totals": {}, "seconds": 0.0, "aborted": ""}
    root = _char_dir(character_name)
    if not root.is_dir():
        return report
    started = time.monotonic()
    try:
        analysis = analyse(character_name, roots=roots, explicit=explicit,
                           deadline=started + budget_s if budget_s is not None else None)
    except GcOverBudget as exc:
        report["aborted"] = str(exc)
        report["seconds"] = round(time.monotonic() - started, 2)
        logger.warning("Artefact GC %s (%s): abandoned after %.1f s (budget %.0f s) — nothing deleted",
                       character_name, reason or "manual", report["seconds"], budget_s)
        return report
    wanted = _descendants(analysis.nodes, set(keys)) if keys is not None else None
    for category in CATEGORIES:
        group = [n for n in analysis.nodes if n.category == category]
        orphans = [n for n in group if not n.reachable]
        report["totals"][category] = {"total": len(group), "reachable": len(group) - len(orphans),
                                      "orphans": len(orphans), "bytes": sum(n.size() for n in orphans)}
    report["unknown"] = [p.relative_to(root).as_posix() for p in analysis.unknown]
    deleted = freed = 0
    for node in analysis.nodes:
        if node.reachable or (wanted is not None and node.key not in wanted):
            continue
        entry = _entry(node)
        report["orphans"].append(entry)
        if node.protected:
            report["skipped"].append({"key": node.key, "why": node.protected})
            continue
        if dry_run:
            continue
        count, size, skip = _delete_node(character_name, node, root)
        deleted += count
        freed += size
        if skip:
            report["skipped"].append({"key": node.key, "why": skip})
    report["deleted_files"], report["freed_bytes"] = deleted, freed
    report["seconds"] = round(time.monotonic() - started, 2)
    logger.info("Artefact GC %s (%s%s%s): %d orphan node(s), %d file(s) %s, %.1f MB, %d skipped, "
                "%d unknown, %.1f s",
                character_name, reason or "manual", ", explicit" if explicit else "", ", dry run" if dry_run else "",
                len(report["orphans"]), deleted if not dry_run else sum(e["files"] for e in report["orphans"]),
                "deleted" if not dry_run else "would go",
                (freed if not dry_run else sum(e["bytes"] for e in report["orphans"])) / 1e6,
                len(report["skipped"]), len(report["unknown"]), report["seconds"])
    return report


def collect_quietly(character_name: str, reason: str, *, explicit: bool = True) -> Optional[Dict[str, Any]]:
    """``collect`` for a delete path and the daily sweep: never raises (a
    failed sweep must not fail the delete that asked for it) and gives up
    after ``HOOK_BUDGET_S`` without deleting anything."""
    try:
        return collect(character_name, explicit=explicit, reason=reason, budget_s=HOOK_BUDGET_S)
    except Exception:
        logger.exception("Artefact GC %s after %s failed", character_name, reason)
        return None


def item_holders(item_id: str) -> List[str]:
    """Characters with an inventory entry of ``item_id`` or garment files of
    it — asked BEFORE an item is deleted (its inventory rows go with it)."""
    from app.core import garment_store
    from app.models.character import list_available_characters
    from app.models.inventory import get_character_inventory
    out: List[str] = []
    for name in list_available_characters():
        try:
            entries = (get_character_inventory(name) or {}).get("inventory") or []
        except Exception:
            entries = []
        if any(e.get("item_id") == item_id for e in entries) or any(
                key[0] == item_id for key in garment_store.stored_groups(name)):
            out.append(name)
    return out


def sweep_all() -> Dict[str, int]:
    """The daily sweep: ``collect`` (grace on) for every character with
    derived files. ``{characters, deleted_files, freed_bytes}``."""
    from app.models.character import list_available_characters
    totals = {"characters": 0, "deleted_files": 0, "freed_bytes": 0}
    for name in list_available_characters():
        try:
            root = _char_dir(name)
        except ValueError:
            continue
        if not any((root / d).is_dir() for d in ROOT_DIRS):
            continue
        result = collect_quietly(name, "daily sweep", explicit=False)
        if result:
            totals["characters"] += 1
            totals["deleted_files"] += result["deleted_files"]
            totals["freed_bytes"] += result["freed_bytes"]
    if totals["deleted_files"]:
        logger.info("Artefact GC daily sweep: %d file(s), %.1f MB over %d character(s)",
                    totals["deleted_files"], totals["freed_bytes"] / 1e6, totals["characters"])
    return totals
