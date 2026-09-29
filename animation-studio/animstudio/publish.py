"""Publish a built clip: into the free library, into the tracked pose
catalog (shared store), and one commit with exactly these changes.

Order: every check first (build fresh + green, names free), then the clip
files, then the catalog entry under the cross-process file lock, then
validate_catalog — on any problem everything written is rolled back.

``catalog_file_lock`` is not re-entrant: it is taken once for the write and,
on a rollback, once more only after that first ``with`` has been left.
"""
import json
import os
import shutil
from pathlib import Path
from typing import Dict, List, Optional

import animstudio
from animstudio import StudioError
from animstudio.build import load_anim, spec_sha


def catalog_entry(anim) -> Dict:
    c = anim.catalog
    return {"prompt": str(c.prompt).strip(),
            "synonyms": [s.strip().lower() for s in c.synonyms if str(s).strip()],
            "animation": anim.kind, "group": c.group, "solo": True}


def _own_existing(kind: str) -> bool:
    """A clip of this kind that the studio itself published earlier."""
    from app.core.animation_clips import clip_entries
    for e in clip_entries():
        if e["kind"] != kind:
            continue
        if e["source"] != "free":
            return False
        side = Path(e["path"]).with_suffix(".json")
        try:
            src = json.loads(side.read_text(encoding="utf-8")).get("source") or {}
        except (OSError, ValueError):
            return False
        return src.get("author") == "animation-studio"
    return False


def _check_kind(anim, replace: bool) -> None:
    """The kind is a legal clip name and free in BOTH libraries (or, with
    ``replace``, an own earlier studio clip)."""
    from app.core.animation_clips import ClipLibraryError, clip_entries, validate_kind
    try:
        validate_kind(anim.kind)
    except ClipLibraryError as e:
        raise StudioError(str(e))
    if any(e["kind"] == anim.kind for e in clip_entries()):
        if not (replace and _own_existing(anim.kind)):
            raise StudioError(f"a clip of kind {anim.kind!r} exists already"
                              + ("" if replace else " (use --replace for an own studio clip)"))


def _check_catalog(anim, replace: bool) -> None:
    """The key and every synonym are free in the pose catalog (both stores)."""
    from app.core import pose_catalog as pc
    key = anim.catalog.key.strip().lower()
    if not key or "/" in key:
        raise StudioError("catalog key must be non-empty and contain no '/'")
    entry = catalog_entry(anim)
    catalog = pc.get_catalog("pose")
    if key in catalog and not (replace and catalog[key].get("animation") == anim.kind):
        raise StudioError(f"catalog key {key!r} exists already")
    for alias in [key] + entry["synonyms"]:
        for other, e in catalog.items():
            if other == key:
                continue
            if alias == other or alias in e.get("synonyms", []):
                raise StudioError(f"{alias!r} already belongs to {other!r}")


def _undo_catalog(pc, cat_path: Path, before: bytes, written: bytes, key: str,
                  old_entry: Optional[dict]) -> None:
    """Takes back our catalog write. Call WITHOUT the file lock held.

    Untouched since our write -> the original bytes come back exactly. Some
    other writer (the Poses tab) came in between -> only our key is undone in
    the current document, their write stays."""
    with pc.catalog_file_lock("pose"):
        try:
            current = cat_path.read_bytes()
        except OSError:
            current = written
        if current == written:
            tmp = cat_path.with_name(cat_path.name + ".undo.tmp")
            tmp.write_bytes(before)
            os.chmod(tmp, cat_path.stat().st_mode & 0o777)
            os.replace(tmp, cat_path)
            return
        doc = json.loads(current.decode("utf-8"))
        entries = doc.setdefault("entries", {})
        if old_entry is None:
            entries.pop(key, None)
        else:
            entries[key] = old_entry
        pc.write_shared_document("pose", doc)


def publish(kind: str, *, replace: bool = False, commit: bool = True, trailer: str = "",
            repo: Path = animstudio.REPO) -> Dict:
    from app.core import paths
    from app.core import pose_catalog as pc
    from app.core.animation_clips import reload_clip_caches
    anim = load_anim(kind)
    out = animstudio.OUT / kind
    try:
        built = json.loads((out / "build.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise StudioError(f"no build of {kind} - run build first")
    if not built.get("ok"):
        raise StudioError("the last build did not pass its checks")
    if built.get("spec_sha") != spec_sha(kind):
        raise StudioError("the source changed after the last build - build again")
    pc.reload_catalogs()
    reload_clip_caches()
    _check_kind(anim, replace)    # early, before anything is written
    _check_catalog(anim, replace)
    lib = paths.get_animation_clips_dir()
    lib.mkdir(parents=True, exist_ok=True)
    written: List[Path] = []
    backups: Dict[Path, bytes] = {}
    key = anim.catalog.key.strip().lower()
    entry = catalog_entry(anim)
    cat_path = pc.catalog_path("pose")
    cat_undo = None               # (before, written, old entry) once we wrote
    try:
        for suffix in (".fbx", ".json"):
            dst = lib / f"{kind}{suffix}"
            if dst.exists():
                backups[dst] = dst.read_bytes()
            tmp = dst.with_name(dst.name + ".tmp")
            shutil.copyfile(out / f"{kind}{suffix}", tmp)
            os.replace(tmp, dst)
            written.append(dst)
        reload_clip_caches()
        with pc.catalog_file_lock("pose"):
            # The critical section is read -> alias check -> write: the
            # names are checked AGAIN under the lock (the Poses tab may have
            # written in between; get_catalog sees it through the file stamp).
            # Only the catalog half: the clip files are already ours here,
            # the kind check would now find them.
            _check_catalog(anim, replace)
            before = cat_path.read_bytes()
            doc = json.loads(before.decode("utf-8"))
            entries = doc.setdefault("entries", {})
            old_entry = entries.get(key)
            entries[key] = entry
            pc.write_shared_document("pose", doc)
            cat_undo = (before, cat_path.read_bytes(), old_entry)
        pc.reload_catalogs()
        problems = pc.validate_catalog("pose")
        if problems:
            raise StudioError("catalog invalid after publish: " + "; ".join(problems))
    except Exception:
        for p in written:
            if p in backups:
                p.write_bytes(backups[p])
            else:
                p.unlink(missing_ok=True)
        reload_clip_caches()
        if cat_undo is not None:
            # The write's ``with`` has been left: taking the lock again here
            # is not a nested acquisition.
            _undo_catalog(pc, cat_path, cat_undo[0], cat_undo[1], key, cat_undo[2])
        pc.reload_catalogs()
        raise
    files = [str(p) for p in written]
    sha = ""
    if commit:
        from animstudio.gitops import commit_with_entry

        def rel(p) -> str:
            return str(Path(p).resolve().relative_to(repo.resolve()))
        msg = f"feat(clips): {kind} — procedural clip + pose '{key}' (animation-studio)"
        if trailer:
            msg += "\n\n" + trailer
        sha = commit_with_entry(repo, rel(cat_path), key, entry,
                                [rel(p) for p in written] + [rel(animstudio.ANIMS / f"{kind}.py")],
                                msg)
    return {"kind": kind, "key": key, "files": files, "commit": sha}
