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

#: Spec § 6.5: publish sees only the shared catalog (its world layer is a
#: throwaway one), so a world's own override of the key stays possible.
WORLD_NOTE = ("a world can override pose {key!r} through its world layer - "
              "publish checks only the shared catalog")


def _is_pair(anim) -> bool:
    from animstudio.dsl import PairAnimation
    return isinstance(anim, PairAnimation)


def catalog_entry(anim) -> Dict:
    c = anim.catalog
    entry = {"prompt": str(c.prompt).strip(),
             "synonyms": [s.strip().lower() for s in c.synonyms if str(s).strip()],
             "animation": anim.kind, "group": c.group, "solo": not _is_pair(anim)}
    if str(c.label_de).strip():
        entry["label_de"] = str(c.label_de).strip()
    if _is_pair(anim):
        # The pair takes one place of two slots; clip +X lies along the
        # facing of a marker (docs/schnittstellen-3d.md § A8a).
        entry.update(places=2, yaw_offset=0)
    return entry


def repointed_entry(anim, existing: Dict) -> Dict:
    """``Catalog(repoint=True)``: the existing entry of the key with this
    clip's prompt/animation/group (and pair fields), every field it carried
    otherwise kept, its synonyms first and the new ones appended."""
    new = catalog_entry(anim)
    merged = json.loads(json.dumps(existing))
    if new["solo"]:
        merged.pop("places", None)
        merged.pop("yaw_offset", None)
    syn = list(merged.get("synonyms") or [])
    merged.update({k: v for k, v in new.items() if k != "synonyms"})
    merged["synonyms"] = syn + [s for s in new["synonyms"] if s not in syn]
    return merged


def clip_users(entries: Dict, kind: str) -> List[str]:
    """The pose keys whose entry plays clip ``kind``."""
    return sorted(k for k, e in entries.items() if (e or {}).get("animation") == kind)


def clip_files(anim) -> List[str]:
    """The library files of one clip: the FBX (both halves of a pair) and
    the sidecar."""
    k = anim.kind
    return ([f"{k}__a.fbx", f"{k}__b.fbx", f"{k}.json"] if _is_pair(anim)
            else [f"{k}.fbx", f"{k}.json"])


def taken_over(anim) -> List[str]:
    return [s.strip().lower() for s in anim.catalog.take_over if str(s).strip()]


def _own_existing(kind: str) -> bool:
    """A clip of this kind that the studio itself published earlier."""
    from app.core.animation_clips import clip_entries
    for e in clip_entries():
        if e["kind"] != kind:
            continue
        if e["source"] != "free":
            return False
        side = Path(e["path"]).parent / f"{kind}.json"   # a pair's halves share it
        try:
            src = json.loads(side.read_text(encoding="utf-8")).get("source") or {}
        except (OSError, ValueError):
            return False
        return (src.get("author") == "animation-studio"
                or src.get("studio") == "animation-studio")
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


def _check_catalog(anim, replace: bool) -> Dict[str, List[str]]:
    """The key and every synonym are free in the pose catalog (both stores)
    — except a synonym named in ``catalog.take_over``, which moves here from
    its owner on publish. Returns owner key -> the synonyms it gives up."""
    from app.core import pose_catalog as pc
    key = anim.catalog.key.strip().lower()
    if not key or "/" in key:
        raise StudioError("catalog key must be non-empty and contain no '/'")
    entry = catalog_entry(anim)
    take = taken_over(anim)
    stray = [t for t in take if t not in entry["synonyms"]]
    if stray:
        raise StudioError(f"take_over {stray} must also be synonyms of {key!r}")
    catalog = pc.get_catalog("pose")
    if anim.catalog.repoint:
        if key not in catalog:
            raise StudioError(f"repoint: there is no pose {key!r} to re-point")
    elif key in catalog and not (replace and catalog[key].get("animation") == anim.kind):
        raise StudioError(f"catalog key {key!r} exists already "
                          "(Catalog(repoint=True) re-points an existing pose to this clip)")
    moves: Dict[str, List[str]] = {}
    for alias in [key] + entry["synonyms"]:
        for other, e in catalog.items():
            if other == key:
                continue
            if alias in take and alias != other and alias in e.get("synonyms", []):
                moves.setdefault(other, []).append(alias)
                continue
            if alias == other or alias in e.get("synonyms", []):
                raise StudioError(f"{alias!r} already belongs to {other!r}")
    return moves


def _undo_catalog(pc, cat_path: Path, before: bytes, written: bytes,
                  old_entries: Dict[str, Optional[dict]]) -> None:
    """Takes back our catalog write. Call WITHOUT the file lock held.

    Untouched since our write -> the original bytes come back exactly. Some
    other writer (the Poses tab) came in between -> only our keys (the new
    one and the owners a take_over touched) are undone in the current
    document, their write stays."""
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
        for key, old_entry in old_entries.items():
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
    checks = built.get("checks") or []
    if not checks:
        # all([]) is True: a build.json from before the checks existed.
        raise StudioError(f"the last build of {kind} recorded no checks - build again")
    if not built.get("ok") or not all(c.get("ok") for c in checks):
        raise StudioError("the last build did not pass its checks")
    if built.get("spec_sha") != spec_sha(kind):
        raise StudioError("the source changed after the last build - build again")
    from animstudio.dsl import validate, PairAnimation, Reversed
    bridge = not isinstance(anim, PairAnimation) and anim.bridge
    if isinstance(anim, Reversed):
        from animstudio.reverse import source_clip
        source_clip(anim)
    elif not isinstance(anim, PairAnimation):
        validate(anim)
    if not bridge:
        pc.reload_catalogs()
    reload_clip_caches()
    _check_kind(anim, replace)    # early, before anything is written
    if not bridge:
        _check_catalog(anim, replace)
    lib = paths.get_animation_clips_dir()
    cat_path = None if bridge else pc.catalog_path("pose")
    commit_paths: List[str] = []
    if commit:
        # Before anything is written: every path the commit names must lie
        # inside the repository.
        def rel(p) -> str:
            try:
                return str(Path(p).resolve().relative_to(repo.resolve()))
            except ValueError:
                raise StudioError(f"{p} lies outside the repository {repo} - "
                                  "cannot commit it (publish with --no-commit?)")
        commit_paths = (([rel(cat_path)] if cat_path else []) + [rel(lib / f) for f in clip_files(anim)]
                        + [rel(animstudio.ANIMS / f"{kind}.py")])
    lib.mkdir(parents=True, exist_ok=True)
    written: List[Path] = []
    backups: Dict[Path, bytes] = {}
    key = "" if bridge else anim.catalog.key.strip().lower()
    entry = {} if bridge else catalog_entry(anim)
    old_clip = ""
    cat_undo = None               # (before, written, old entries) once we wrote
    moves: Dict[str, List[str]] = {}
    try:
        for name in clip_files(anim):
            dst = lib / name
            if dst.exists():
                backups[dst] = dst.read_bytes()
            from app.core.http_files import atomic_replace, sibling_stage
            with sibling_stage(dst) as tmp:
                shutil.copyfile(out / name, tmp)
                atomic_replace(tmp, dst)
            written.append(dst)
        reload_clip_caches()
        if not bridge:
            with pc.catalog_file_lock("pose"):
                # The critical section is read -> alias check -> write: the
                # names are checked AGAIN under the lock (the Poses tab may have
                # written in between; get_catalog sees it through the file stamp).
                # Only the catalog half: the clip files are already ours here,
                # the kind check would now find them.
                moves = _check_catalog(anim, replace)
                before = cat_path.read_bytes()
                doc = json.loads(before.decode("utf-8"))
                entries = doc.setdefault("entries", {})
                olds = {k: (json.loads(json.dumps(entries[k])) if k in entries else None)
                        for k in [key, *moves]}
                if anim.catalog.repoint:
                    if key not in entries:
                        raise StudioError(f"repoint: pose {key!r} is not in the shared catalog")
                    old_clip = str(entries[key].get("animation") or "")
                    entry = repointed_entry(anim, entries[key])
                entries[key] = entry
                for owner, gone in moves.items():
                    if owner in entries:
                        entries[owner]["synonyms"] = [x for x in entries[owner].get("synonyms", [])
                                                      if x not in gone]
                pc.write_shared_document("pose", doc)
                cat_undo = (before, cat_path.read_bytes(), olds)
            pc.reload_catalogs()
            problems = pc.validate_catalog("pose")
            if problems:
                raise StudioError("catalog invalid after publish: " + "; ".join(problems))
    except Exception:
        for p in written:
            if p in backups:
                with sibling_stage(p) as tmp:
                    tmp.write_bytes(backups[p])
                    atomic_replace(tmp, p)
            else:
                p.unlink(missing_ok=True)
        reload_clip_caches()
        if cat_undo is not None:
            # The write's ``with`` has been left: taking the lock again here
            # is not a nested acquisition.
            _undo_catalog(pc, cat_path, cat_undo[0], cat_undo[1], cat_undo[2])
        pc.reload_catalogs()
        raise
    files = [str(p) for p in written]
    result = {"kind": kind, "key": key, "files": files, "commit": "", "commit_created": False,
              "warning": "", "note": ("bridge published; caller supplies clip_transitions.json rules" if bridge
                                      else WORLD_NOTE.format(key=key)), "moved": moves,
              "repointed_from": old_clip if old_clip != kind else "",
              # the replaced clip's remaining users (empty: no pose plays it now)
              "old_clip_users": (clip_users(pc.get_catalog("pose"), old_clip)
                                 if old_clip and old_clip != kind else [])}
    if commit:
        from animstudio.gitops import commit_with_entry
        msg = (f"feat(clips): {kind} — procedural clip + pose '{key}' (animation-studio)"
               if not result["repointed_from"] else
               f"feat(clips): {kind} — procedural clip, pose '{key}' re-pointed from "
               f"'{result['repointed_from']}' (animation-studio)")
        if bridge:
            msg = f"feat(clips): {kind} — procedural bridge (animation-studio)"
        if isinstance(anim, Reversed):
            msg = f"feat(clips): {kind} — {anim.source} reversed as a bridge (animation-studio)"
        if trailer:
            msg += "\n\n" + trailer
        res = commit_with_entry(repo, "" if bridge else commit_paths[0], key, entry,
                                commit_paths if bridge else commit_paths[1:], msg,
                                strip=moves)
        result.update(commit=res.sha, commit_created=res.created, warning=res.warning)
    return result
