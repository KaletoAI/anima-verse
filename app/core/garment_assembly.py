"""Garment assembly — the served 3D model = bare outfit model + grafted
garment meshes (plan 2026-11-09-base-body-phase4-hair R11, R12).

The stored ``model3d/<sig>.glb`` stays BARE: every management path
(``find_model3d``, ``find_model3d_serving``, Blender steps, base-colour and
face checks, extension-rig rebuilds, LOD, weight repair) keeps seeing the file
without hair. The delivery is a derived file next to it::

    model3d/assembled/<sig>.glb      + .json   full tier
    model3d/assembled/low/<sig>.glb  + .json   distance tier

built by numpy (``glb_mesh.graft``) from the bare file of that tier plus the
garment node of every wanted fit. Its sidecar is the bare sidecar plus
``garments: {item_id: {kind, fsig, sha256}}`` (``sha256`` = the garment
source used for THAT tier) and ``bare_revision`` (stat records of the bare
file and its sidecar when the build captured them).

Only the byte/URL paths substitute the assembly (``served``), and only when
it is current: same ``bare_revision`` as the bare file on disk now, same
garments as wanted now. Anything else serves the bare file and asks for a
background build (``schedule``) — serving never waits. A build publishes
under ``model3d_publication`` only if the bare file is still the one it read
(generation-key rule), so a republished bare file can never be covered by an
assembly of its predecessor.

Which garment: the hair of the profile's ``equipped_mesh_pieces`` (outfit
independent) plus the own-mesh outfit pieces of THE SIGNATURE — the
``mesh_items.effective`` list its bare sidecar recorded (plan
2026-11-09-base-body-phase5-mesh-items, Task 4: the pieces the build left
out of the texture), never the current profile's pieces, so a stand-in or a
model of another outfit carries exactly the garments its texture lacks.
Per garment the fit ``garment_store.accepted_fit`` names on the CURRENT base
model (current fsig, else the newest accepted fit) — and only when the bare
model of the signature was built on that same base model
(``built_on_fit_base``: the bare full sidecar's ``base_model_sha256``, else
its ``base_signature``, equals the fit record's). An outfit model from an
older base (served as stale until rebuilt) has another body under the
garments: it is served bare, and no assembly is built for it. Off the
base-body pipeline, or with nothing wanted, the bare file is served
unchanged.

Own-mesh pieces of the signature worn over each other (plan
2026-11-10-texture-body-reuse-and-layering, Task 2): an outer piece is
grafted from its LAYERED fit over the inner pieces of the set
(``garment_layers``; its sidecar entry adds ``over: <lsig>``). ``served``
only reads: a layered fit not built yet serves the body fit, the entry says
``pending`` and the build (``assemble``) makes the layered fit first — CPU
work, no hub job. A changed inner fit changes the ``lsig``, so the assembly
is no longer current and the outer piece is layered again.
"""
import json
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.core.log import get_logger

logger = get_logger("garment_assembly")

FULL = "full"
LOW = "low"
TIERS = (FULL, LOW)

_lock = threading.Lock()
# One build per (character, signature) at a time; a request while one runs
# makes it run once more afterwards (the wanted state may have moved on).
_building: set = set()
_again: set = set()
# (character, signature) -> the input key of a build that failed: the same
# inputs are not retried on every request (a new bare file, fit or equip is).
_failed: Dict[Tuple[str, str], str] = {}


# --- Paths and revisions ------------------------------------------------------

def _model3d():
    from app.core import model3d
    return model3d


def bare_path(directory: Path, signature: str, tier: str) -> Path:
    """The bare GLB of ``signature`` at ``tier`` in a model directory."""
    return directory / f"{signature}.glb" if tier == FULL else directory / tier / f"{signature}.glb"


def assembled_path(directory: Path, signature: str, tier: str) -> Path:
    """The assembled GLB of ``signature`` at ``tier`` in a model directory."""
    root = directory / _model3d().ASSEMBLED_DIR
    return root / f"{signature}.glb" if tier == FULL else root / tier / f"{signature}.glb"


def _stat_record(path: Path) -> Optional[List[int]]:
    try:
        st = path.stat()
    except OSError:
        return None
    return [st.st_size, st.st_mtime_ns, st.st_ino]


def bare_revision(path: Path) -> List[Optional[List[int]]]:
    """Stat records (size, mtime_ns, inode) of a bare model file and its
    sidecar — what an assembly was built from. No content is read."""
    path = Path(path)
    return [_stat_record(path), _stat_record(path.with_suffix(".json"))]


def carry_sidecar_key(bare: Path, before: List[Optional[List[int]]], key: str, value: Any) -> bool:
    """A bare sidecar write that is no assembly input — ONE key the caller
    just published into it (``collision``: the capsule set, measured on the
    bare body) — carried into the assembly of that tier: an assembly that was
    current against ``before`` (``bare_revision`` captured right before the
    write) gets the key and the new revision, so it stays served instead of
    being rebuilt for a key it merely copies. The caller holds
    ``model3d_publication`` of the model directory. True when re-stamped."""
    bare = Path(bare)
    if bare.parent.name == LOW:
        directory, tier = bare.parent.parent, LOW
    else:
        directory, tier = bare.parent, FULL
    assembled = assembled_path(directory, bare.stem, tier)
    if not assembled.is_file():
        return False
    meta = _read_json(assembled.with_suffix(".json"))
    if not meta or meta.get("bare_revision") != before:
        return False
    meta[key] = value
    meta["bare_revision"] = bare_revision(bare)
    _model3d()._publish_sidecar(assembled, meta)
    return True


def read_sidecar(path: Path) -> Dict[str, Any]:
    """The sidecar of an assembled (or bare) model file, {} when unreadable."""
    return _read_json(Path(path).with_suffix(".json"))


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _file_sha256(path: Optional[Path]) -> str:
    from app.core.base_body import file_sha256
    return file_sha256(path)


# --- What is wanted -----------------------------------------------------------

def built_on_fit_base(bare_meta: Dict[str, Any], record: Dict[str, Any]) -> bool:
    """Whether a bare outfit model (its sidecar ``bare_meta``) was built on
    the base model a fit (its ``record``) was fitted to: the sidecar's
    ``base_model_sha256`` equals the record's, or — a sidecar without the
    sha — its ``base_signature`` does. A sidecar with neither (a model from
    before the pipeline) matches nothing."""
    sha = str(bare_meta.get("base_model_sha256") or "")
    if sha:
        return sha == str(record.get("base_model_sha256") or "")
    bsig = str(bare_meta.get("base_signature") or "")
    return bool(bsig) and bsig == str(record.get("base_signature") or "")


def effective_mesh_items(bare_meta: Optional[Dict[str, Any]]) -> List[str]:
    """The own-mesh outfit pieces a bare outfit model was built WITHOUT in its
    texture (sidecar ``mesh_items.effective``), sorted; [] when it records
    none."""
    mesh = (bare_meta or {}).get("mesh_items")
    if not isinstance(mesh, dict):
        return []
    return sorted({str(i) for i in (mesh.get("effective") or []) if isinstance(i, str) and i})


def _wanted(character_name: str, profile: Optional[Dict[str, Any]] = None, *,
            bare_meta: Optional[Dict[str, Any]] = None, build_layers: bool = False) -> List[Dict[str, Any]]:
    """The garments to graft, sorted by item id: ``{item_id, kind, fsig, fit,
    low, record}`` per garment with an accepted fit on the current base
    model — the hair of the profile's ``equipped_mesh_pieces``, and with
    ``bare_meta`` (the bare model's sidecar) the signature's effective mesh
    set (``effective_mesh_items``), restricted to fits on the base model that
    bare model was built on (``built_on_fit_base``). [] off the pipeline or
    with nothing wanted.

    Own-mesh pieces worn over each other (plan 2026-11-10 Task 2,
    ``garment_layers``): an outer piece's ``fit`` / ``low`` are its layered
    fit over the inner pieces of the set, and it carries ``over: {lsig,
    items, pending, without}``; a layered fit not built yet serves the body
    fit with ``pending`` True. ``build_layers`` (the assembly build, never
    serving) builds the missing ones first."""
    if profile is None:
        from app.models.character import get_character_profile
        profile = get_character_profile(character_name) or {}
    worn = profile.get("equipped_mesh_pieces")
    hair = {str(v) for v in worn.values() if v} if isinstance(worn, dict) else set()
    clothing = set(effective_mesh_items(bare_meta)) - hair
    if not hair and not clothing:
        return []
    from app.core import base_body, garment_store
    from app.core.garment_set import CLOTHING
    from app.models.inventory import get_item
    base = base_body.current_base(character_name, profile=profile)
    if not base or not base[1]:
        return []
    out: List[Dict[str, Any]] = []
    for item_id in sorted(hair | clothing):
        item = get_item(item_id) or {}
        if item_id in clothing:
            # The bare model was built without it in the texture: graft it
            # even when the flag was switched off since (that state has a
            # signature of its own; this model needs its garment).
            if item.get("category") != "outfit_piece":
                continue
            kind = CLOTHING
        else:
            kind = str((item.get("garment") or {}).get("kind") or "")
            if item.get("category") != "garment" or kind not in garment_store.GARMENT_VERSION:
                continue
        # The fit of the CURRENT method (garment_store.accepted_fit): a switched
        # hair method serves that method's fit, or no hair before it has one.
        fit = garment_store.accepted_fit(character_name, item_id, base_model_sha=base[1], profile=profile)
        parsed = garment_store.parse_name(fit[0]) if fit else None
        if not parsed:
            continue
        if bare_meta is not None and not built_on_fit_base(bare_meta, fit[1]):
            continue
        fsig = parsed[1]
        low = garment_store.garment_path(character_name, item_id, fsig, "low")
        out.append({"item_id": item_id, "kind": kind, "fsig": fsig, "fit": fit[0],
                    "low": low if low.is_file() else None, "record": fit[1]})
    layered = [g for g in out if g["kind"] == CLOTHING]
    if bare_meta is not None and len(layered) > 1:
        from app.core import garment_layers
        from app.core.base_body import mesh_items_intended
        args = dict(base_sha=base[1], profile=profile, intended=mesh_items_intended(bare_meta),
                    fits={g["item_id"]: (g["fit"], g["record"]) for g in layered})
        items = [g["item_id"] for g in layered]
        layers = (garment_layers.ensure if build_layers else garment_layers.plan)(character_name, items, **args)
        for g in layered:
            entry = layers.get(g["item_id"])
            if entry and entry["lsig"]:
                g.update(fit=entry["source"], low=entry["low"],
                         over={"lsig": entry["lsig"], "items": sorted(entry["inner"]),
                               "pending": entry["pending"], "without": entry["without"]})
    return out


def _wanted_for(character_name: str, directory: Path, signature: str, *,
                build_layers: bool = False) -> List[Dict[str, Any]]:
    """``_wanted`` for the bare model of ``signature`` in ``directory``: its
    FULL sidecar names the base it was built on (the low tier is derived
    from the full file)."""
    return _wanted(character_name, bare_meta=_read_json(bare_path(directory, signature, FULL).with_suffix(".json")),
                   build_layers=build_layers)


def wanted_garments(character_name: str, *,
                    profile: Optional[Dict[str, Any]] = None) -> Dict[str, Tuple[Path, Optional[Path], dict]]:
    """item_id -> (fit GLB, low GLB or None, fit record) of every garment the
    served model should carry (R11); {} off the pipeline / with no equipped
    mesh piece / without an accepted fit on the current base model."""
    return {g["item_id"]: (g["fit"], g["low"], g["record"]) for g in _wanted(character_name, profile)}


def _source(garment: Dict[str, Any], tier: str) -> Path:
    """The GLB a tier takes the garment node from: the low tier's own garment
    when it was built, else the full fit (never a bald distance figure)."""
    return garment["low"] if tier == LOW and garment["low"] is not None else garment["fit"]


def _state(wanted: List[Dict[str, Any]], tier: str) -> Dict[str, Dict[str, Any]]:
    """The sidecar ``garments`` map an assembly of ``tier`` must carry — a
    layered piece adds ``over`` (its ``lsig``) and, while its layered fit is
    missing, ``pending`` (so the assembly is rebuilt once it exists)."""
    out: Dict[str, Dict[str, Any]] = {}
    for g in wanted:
        entry: Dict[str, Any] = {"kind": g["kind"], "fsig": g["fsig"], "sha256": _file_sha256(_source(g, tier))}
        over = g.get("over")
        if over:
            entry["over"] = over["lsig"]
            if over["pending"]:
                entry["pending"] = True
        out[g["item_id"]] = entry
    return out


def _current(assembled: Path, bare: Path, state: Dict[str, Any]) -> bool:
    if not assembled.is_file():
        return False
    meta = _read_json(assembled.with_suffix(".json"))
    return meta.get("bare_revision") == bare_revision(bare) and meta.get("garments") == state


# --- Serving ------------------------------------------------------------------

def served(character_name: str, path: Optional[Path], tier: str) -> Optional[Path]:
    """The file to deliver for the bare model ``path`` at ``tier``: its
    assembly when that is current (``bare_revision`` and ``garments`` equal
    the wanted state), else ``path`` itself — then a background build is
    asked for. ``path`` unchanged when nothing is wanted. Never raises."""
    if path is None:
        return path
    try:
        path = Path(path)
        tier = tier or FULL
        if path.suffix.lower() != ".glb" or tier not in TIERS:
            return path
        if tier == FULL:
            directory = path.parent
        elif path.parent.name == tier:
            directory = path.parent.parent
        else:
            return path
        signature = path.stem
        from app.core.base_body import is_base_signature
        if is_base_signature(signature):
            return path  # the base body itself is never dressed
        assembled = assembled_path(directory, signature, tier)
        wanted = _wanted_for(character_name, directory, signature)
        if not wanted:
            if assembled.exists():
                schedule(character_name, signature)  # takes the leftover away
            return path
        if _current(assembled, path, _state(wanted, tier)):
            return assembled
        schedule(character_name, signature)
        return path
    except Exception:  # noqa: BLE001 — serving falls back to the bare file
        logger.exception("Garment assembly %s: serving check failed", character_name)
        return path


# --- Building -----------------------------------------------------------------

def _remove(directory: Path, signature: str, tier: str) -> bool:
    """Unlink one tier's assembly under the publication lock; True if any."""
    from app.core.keyed_lock import keyed_lock
    target = assembled_path(directory, signature, tier)
    removed = False
    with keyed_lock("model3d_publication", str(directory)):
        for p in (target, target.with_suffix(".json")):
            if p.exists():
                p.unlink(missing_ok=True)
                removed = True
    return removed


def _build(character_name: str, directory: Path, bare: Path,
           wanted: List[Dict[str, Any]], tier: str) -> Tuple[bytes, Dict[str, Any], list]:
    """Read the bare file + its sidecar under the publication lock (so bytes
    and revision belong together), graft every garment, validate. Returns
    (bytes, sidecar, captured revision)."""
    from app.core import glb_mesh
    from app.core.keyed_lock import keyed_lock
    from app.core.model_validate import rig_frames_preserved
    from app.core.timeutils import utc_now_iso
    model3d = _model3d()
    with keyed_lock("model3d_publication", str(directory)):
        revision = bare_revision(bare)
        data = bare.read_bytes()
        meta = _read_json(bare.with_suffix(".json"))
    if meta.get("base") or meta.get("rig") != "mixamo":
        raise ValueError(f"bare model {bare.name} is no rigged outfit model (rig {meta.get('rig')!r})")
    blob = data
    for garment in wanted:
        source = _source(garment, tier)
        mesh = glb_mesh.garment_arrays(source.read_bytes())
        extras = {"kind": garment["kind"], "item_id": garment["item_id"], "fsig": garment["fsig"]}
        if garment.get("over") and not garment["over"]["pending"]:
            extras["over"] = garment["over"]["items"]
        blob = glb_mesh.graft(blob, mesh, name=f"garment_{garment['kind']}_{garment['item_id']}", extras=extras)
    verdict = model3d._validator_for("mixamo", character_name)(blob)
    if not verdict.get("ok"):
        raise ValueError("assembled model failed validation: " + "; ".join(verdict.get("errors") or []))
    frames = rig_frames_preserved(data, blob)
    if not frames.get("ok"):
        raise ValueError("assembled model rewrote the rig frames: " + "; ".join(frames.get("errors") or []))
    side = {**meta, "garments": _state(wanted, tier), "bare_revision": revision,
            "assembled_at": utc_now_iso()}
    return blob, side, revision


def assemble(character_name: str, signature: str, *,
             tiers: Tuple[str, ...] = (FULL, LOW)) -> Dict[str, Any]:
    """Build (or remove) the assembled delivery files of ``signature``.

    Per tier: the bare revision and the wanted garments are captured FIRST;
    the result is published under ``model3d_publication`` only while the
    bare file is still the captured one. Nothing wanted (or no bare file of
    that tier) removes an existing assembly. An assembly that is already
    current is left alone. Works inside a staged model operation too (the
    model directory is then the stage; its publication carries the result).

    Returns ``{ok, tiers: {tier: status}, error?}`` with status
    ``assembled`` / ``current`` / ``removed`` / ``none`` / ``stale`` /
    ``failed``."""
    from app.core import sync_topics
    from app.core.keyed_lock import keyed_lock
    model3d = _model3d()
    if not isinstance(signature, str) or not signature or any(c in signature for c in ("/", "\\", "\0")) \
            or signature in (".", ".."):
        raise ValueError("Invalid model signature")
    directory = model3d.get_model3d_dir(character_name)
    # The layered fits of pieces worn over each other are built here (CPU, no hub job), never while serving.
    wanted = _wanted_for(character_name, directory, signature, build_layers=True)
    statuses: Dict[str, str] = {}
    errors: List[str] = []
    changed = False
    for tier in tiers:
        if tier not in TIERS:
            raise ValueError(f"unknown model tier {tier!r}")
        bare = bare_path(directory, signature, tier)
        target = assembled_path(directory, signature, tier)
        if not wanted or not bare.is_file():
            removed = _remove(directory, signature, tier) if target.exists() or target.with_suffix(".json").exists() \
                else False
            changed |= removed
            statuses[tier] = "removed" if removed else "none"
            continue
        if _current(target, bare, _state(wanted, tier)):
            statuses[tier] = "current"
            continue
        try:
            blob, side, revision = _build(character_name, directory, bare, wanted, tier)
        except Exception as e:  # noqa: BLE001 — one tier's failure is reported, the bare file keeps serving
            logger.warning("Garment assembly %s/%s (%s) failed: %s", character_name, signature, tier, e)
            statuses[tier] = "failed"
            errors.append(f"{tier}: {e}")
            continue
        with keyed_lock("model3d_publication", str(directory)):
            if bare_revision(bare) != revision:
                statuses[tier] = "stale"  # the bare file moved on meanwhile
                continue
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                model3d._publish_model_bytes(target, blob)
                model3d._publish_sidecar(target, side)
            except FileNotFoundError:
                statuses[tier] = "none"  # model directory deleted meanwhile
                continue
        changed = True
        statuses[tier] = "assembled"
        logger.info("Garment assembly %s: %s (%s, %d garment(s), %d bytes)", character_name,
                    target.name, tier, len(wanted), len(blob))
    if changed and character_name not in getattr(model3d._staging, "directories", {}):
        sync_topics.changed_at(character_name)
    out: Dict[str, Any] = {"ok": not errors, "tiers": statuses}
    if errors:
        out["error"] = "; ".join(errors)
    return out


def _input_key(character_name: str, signature: str) -> str:
    """What a build of ``signature`` would read now (both tiers' bare
    revisions + wanted garments) — the failure memo's key."""
    directory = _model3d().get_model3d_dir(character_name)
    wanted = _wanted_for(character_name, directory, signature)
    return json.dumps([[bare_revision(bare_path(directory, signature, t)), _state(wanted, t)] for t in TIERS],
                      sort_keys=True)


def schedule(character_name: str, signature: Optional[str] = None) -> bool:
    """Ask for a background (re)build of the assembled model of ``signature``
    (None = the model the current outfit serves, else the current outfit
    signature). One build per (character, signature) at a time — a request
    while one runs makes it run once more. Inside a staged model operation
    the request waits for that operation's publication. A build that failed
    is not retried with unchanged inputs. True if started (or deferred)."""
    try:
        model3d = _model3d()
        if signature is None:
            path = model3d.find_model3d_serving(character_name)[0]
            if path is None:
                from app.core.model_refs import current_outfit_state
                signature = current_outfit_state(character_name)[2]
            else:
                signature = path.stem
        if not isinstance(signature, str) or not signature or any(c in signature for c in ("/", "\\", "\0")) \
                or signature in (".", ".."):
            return False
        if character_name in getattr(model3d._staging, "directories", {}):
            requests = getattr(model3d._staging, "assembly_requests", {}).get(character_name)
            if requests is None:
                return False
            requests.add(signature)
            return True
        key = (character_name, signature)
        directory = model3d.get_model3d_dir(character_name)
        if not _wanted_for(character_name, directory, signature) and not any(
                p.exists() for t in TIERS
                for p in (assembled_path(directory, signature, t),
                          assembled_path(directory, signature, t).with_suffix(".json"))):
            return False  # nothing to build and nothing to take away: no thread
        if key in _failed and _failed.get(key) == _input_key(character_name, signature):
            return False
        with _lock:
            if key in _building:
                _again.add(key)
                return False
            _building.add(key)
        threading.Thread(target=_run, args=(key,), daemon=True,
                         name=f"garment-assembly-{character_name}").start()
        return True
    except Exception:  # noqa: BLE001 — a schedule request never breaks its caller
        logger.exception("Garment assembly %s: schedule failed", character_name)
        return False


def _run(key: Tuple[str, str]) -> None:
    character_name, signature = key
    try:
        while True:
            with _lock:
                _again.discard(key)
            try:
                inputs = _input_key(character_name, signature)
                result = assemble(character_name, signature)
            except Exception as e:  # noqa: BLE001
                logger.warning("Garment assembly %s/%s failed: %s", character_name, signature, e)
                result, inputs = {"ok": False, "error": str(e)}, ""
            if result.get("ok"):
                _failed.pop(key, None)
            elif inputs:
                _failed[key] = inputs
            with _lock:
                # Leave the in-flight set in the same critical section that
                # saw no new request, so no request falls between the two.
                if key not in _again:
                    _building.discard(key)
                    return
    except BaseException:
        with _lock:
            _building.discard(key)
            _again.discard(key)
        raise


def wait_idle(timeout: float = 30.0) -> bool:
    """Block until no background build runs (smokes, shutdown). True when idle."""
    import time
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with _lock:
            if not _building:
                return True
        time.sleep(0.02)
    return False
