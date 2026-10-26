"""Read-only expression inventory and explicitly previewed maintenance."""
from contextlib import ExitStack
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

from app.core.keyed_lock import keyed_lock
from app.core.expression_sets import catalog_snapshot, set_for_character, ExpressionSetError


class CleanupError(ValueError):
    def __init__(self, message, status=400, completed=None):
        super().__init__(message)
        self.status = status
        self.completed = completed or {}


def _profile(name):
    from app.core.db import get_connection
    row = get_connection().execute("SELECT template,profile_json FROM characters WHERE name=?", (name,)).fetchone()
    if row is None:
        raise CleanupError("Character not found", 404)
    profile = json.loads(row[1] or "{}")
    profile["template"] = row[0]
    return profile


def _safe(folder, filename):
    if not filename or Path(filename).name != filename:
        raise CleanupError("Invalid expression filename")
    path = folder / filename
    if folder.is_symlink() or path.is_symlink() or path.resolve().parent != folder.resolve():
        raise CleanupError("Expression symlink or containment failure")
    return path


def _file_identity(path):
    stat = path.lstat()
    identity = [path.name, stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns]
    if path.is_symlink():
        identity.append(os.readlink(path))
    elif path.is_file():
        identity.append(hashlib.sha256(path.read_bytes()).hexdigest())
    return identity


def _scan(name):
    from app.core import expression_regen as er
    from app.core.http_files import content_version
    cat = catalog_snapshot()
    profile = _profile(name)
    selection_error = ""
    try:
        spec = set_for_character(name, profile=profile, catalog=cat)
    except ExpressionSetError as exc:
        spec = None
        selection_error = str(exc)
    try:
        folder = er._get_expressions_dir(name)
        paths = sorted(folder.iterdir()) if folder.is_dir() else []
        identities = [_file_identity(p) for p in paths]
    except ValueError as exc:
        raise CleanupError(str(exc)) from exc
    except OSError as exc:
        raise CleanupError("Expression inventory changed; refresh preview", 409) from exc
    revision = er._digest({"character": name, "catalog": cat.revision, "set": spec.id if spec else "",
        "selection": profile.get("expression_set", ""), "files": identities,
        "exists": folder.exists(), "epoch": er.mutation_epoch(name)})
    rows = []
    # Unknown explicit selections preserve historical inspection but cannot delete.
    consumed = set()
    for path in paths:
        if path.suffix.lower() not in er._IMAGE_EXTS:
            continue
        consumed.add(path.name)
        sidecar = path.with_suffix(".json")
        consumed.add(sidecar.name)
        row = {"file": path.name, "action": "review", "reason": "Unverified metadata", "meta": {}}
        rows.append(row)
        if path.is_symlink() or sidecar.is_symlink():
            row["reason"] = "Symlink: manual review required"
            continue
        try:
            meta = json.loads(sidecar.read_text())
            if not isinstance(meta, dict):
                continue
            row["meta"] = meta
        except (OSError, ValueError):
            continue
        if (not isinstance(meta.get("equipped_pieces", {}), dict)
                or not isinstance(meta.get("equipped_items", []), list)
                or not isinstance(meta.get("expression_key", ""), str)
                or not isinstance(meta.get("expression_set", ""), str)):
            row["meta"] = {}
            row["reason"] = "Malformed expression metadata"
            continue
        if spec is None:
            row["reason"] = selection_error
            continue
        key = meta.get("expression_key")
        sid = meta.get("expression_set")
        if meta.get("schema") == 2:
            contract_proof = meta.get("contract")
            if (not isinstance(meta.get("outfit_raw"), str)
                    or not sid or not key
                    or not isinstance(meta.get("neutral_state"), bool)
                    or not isinstance(contract_proof, str) or len(contract_proof) != 64
                    or any(c not in "0123456789abcdef" for c in contract_proof)
                    or not meta.get("content_version")):
                row["reason"] = "Incomplete expression identity or render contract"
                continue
            if meta["content_version"] != content_version(path):
                row["reason"] = "Image bytes do not match metadata"
                continue
            row.update(expression_set=sid, expression_key=key, outfit_raw=meta["outfit_raw"])
            if sid != spec.id or key not in spec.members:
                row.update(action="remove", reason="Not in the selected expression set")
                continue
            contract = er._digest({"version": 2, "pose_prompt": spec.pose_prompt,
                                   "expression_prompt": cat.entries[key]["prompt"]})
            if contract_proof != contract or meta["neutral_state"] is not True:
                row.update(action="remove", reason="Obsolete expression render contract")
                continue
            identity = er._digest({"version": 2, "set_id": sid, "expression_key": key,
                                  "outfit_raw": meta["outfit_raw"], "contract": contract})
            target = f"{er._safe_name(name)}_{identity[:24]}{path.suffix}"
            row.update(target=target, action="keep" if target == path.name and meta.get("identity") == path.stem else "adopt",
                       reason="Current image" if target == path.name else "Proven-compatible image with noncanonical filename")
        elif key and key in cat.entries:
            owner = next((s.id for s in cat.sets.values() if key in s.members), "")
            if owner != spec.id:
                row.update(action="remove", reason="Legacy expression belongs to another anatomy set")
            elif meta.get("state_fingerprint") or meta.get("pose_key"):
                row.update(action="remove", reason="Legacy activity/state-dependent expression contract")
    # A target is adopted once. Existing canonical valid bytes always win.
    by_target = {}
    for row in rows:
        if row["action"] in ("keep", "adopt"):
            by_target.setdefault(Path(row["target"]).stem, []).append(row)
    for group in by_target.values():
        winner = max(group, key=lambda r: (r["action"] == "keep", (folder / r["file"]).stat().st_mtime_ns, r["file"]))
        for row in group:
            if row is not winner:
                row.update(action="remove", reason="Redundant compatible image; deterministic winner retained")
    for path in paths:
        if path.name not in consumed:
            rows.append({"file": path.name, "action": "review", "reason": "Unmanaged or orphaned file", "meta": {}})
    counts = {action: sum(row["action"] == action for row in rows) for action in ("keep", "adopt", "remove", "review")}
    return {"revision": revision, "counts": counts, "files": rows}


def preview_cleanup(character):
    from app.core.expression_regen import publication_lock
    with keyed_lock("character_profile", character), keyed_lock("pose_catalog", "expression"), publication_lock(character):
        result = _scan(character)
    return {**result, "files": [{k: v for k, v in row.items() if k != "meta"} for row in result["files"]]}


def apply_cleanup(character, revision):
    from app.core import expression_regen as er
    from app.core.pose_catalog_edit import catalog_txn
    completed = {"adopted": 0, "removed": 0, "kept": 0, "review": 0}
    with er.render_lock(character), keyed_lock("character_profile", character), catalog_txn("expression"), er.publication_lock(character):
        plan = _scan(character)
        if not revision or plan["revision"] != revision:
            raise CleanupError("Expression cleanup preview is stale; refresh it", 409)
        folder = er._get_expressions_dir(character)
        # Validate every affected path and target before the first mutation.
        for row in plan["files"]:
            if row["action"] in ("adopt", "remove"):
                _safe(folder, row["file"])
                _safe(folder, str(Path(row["file"]).with_suffix(".json")))
            if row["action"] == "adopt":
                target = _safe(folder, row["target"])
                if target.exists() or target.with_suffix(".json").exists():
                    raise CleanupError("Adoption target changed; refresh preview", 409)
        if not any(r["action"] in ("adopt", "remove") for r in plan["files"]):
            return {**completed, "kept": plan["counts"]["keep"], "review": plan["counts"]["review"]}
        er.invalidate_publication(character)
        operation = "prepare adoption"
        try:
            with tempfile.TemporaryDirectory(prefix=".cleanup-", dir=folder) as staging:
                staging = Path(staging)
                prepared = []
                for row in plan["files"]:
                    if row["action"] != "adopt":
                        continue
                    source = _safe(folder, row["file"])
                    target = _safe(folder, row["target"])
                    image_stage = staging / target.name
                    shutil.copy2(source, image_stage)
                    meta = dict(row["meta"])
                    meta["identity"] = target.stem
                    meta_stage = image_stage.with_suffix(".json")
                    meta_stage.write_text(json.dumps(meta, ensure_ascii=False, indent=2))
                    prepared.append((row, image_stage, meta_stage, target))
                for row, image_stage, meta_stage, target in prepared:
                    operation = f"adopt {row['file']}"
                    os.replace(image_stage, target)
                    try:
                        os.replace(meta_stage, target.with_suffix(".json"))
                    except BaseException:
                        target.unlink(missing_ok=True)
                        raise
                    completed["adopted"] += 1
                for row in plan["files"]:
                    if row["action"] not in ("adopt", "remove"):
                        continue
                    operation = f"remove {row['file']}"
                    source = _safe(folder, row["file"])
                    source.unlink()
                    source.with_suffix(".json").unlink(missing_ok=True)
                    if row["action"] == "remove":
                        completed["removed"] += 1
                completed.update(kept=plan["counts"]["keep"], review=plan["counts"]["review"])
        except OSError as exc:
            raise CleanupError(f"Cleanup failed during {operation}: {exc}", 500, completed) from exc
    return completed


def inventory(character):
    from app.core import expression_regen as er
    from app.core.http_files import content_version
    from app.models.inventory import get_item
    try:
        with keyed_lock("character_profile", character), keyed_lock("pose_catalog", "expression"), er.publication_lock(character):
            plan = _scan(character)
            cat = catalog_snapshot()
    except (CleanupError, ExpressionSetError):
        return []
    folder = er._get_expressions_dir(character)
    rows = []
    names = {}
    def item_name(iid):
        if iid not in names:
            names[iid] = (get_item(iid) or {}).get("name") or iid
        return names[iid]
    for row in plan["files"]:
        file = folder / row["file"]
        if file.suffix.lower() not in er._IMAGE_EXTS or file.is_symlink() or not file.is_file():
            continue
        meta = row["meta"]
        rows.append({**meta, "file": row["file"],
            "expression_set": meta.get("expression_set", ""), "expression_key": meta.get("expression_key", ""),
            "expression_label": cat.entries.get(meta.get("expression_key"), {}).get("label", meta.get("expression_key", "")),
            "outfit_raw": meta.get("outfit_raw", ""), "contract": meta.get("contract", ""),
            "status": "current" if row["action"] == "keep" else "unverified" if row["action"] == "review" else "historical",
            "reason": row["reason"], "version": content_version(file),
            "equipped_pieces": {slot: item_name(iid) for slot, iid in (meta.get("equipped_pieces") or {}).items()},
            "equipped_items": [item_name(iid) for iid in meta.get("equipped_items") or []]})
    return sorted(rows, key=lambda row: str(row.get("created_at") or ""), reverse=True)
