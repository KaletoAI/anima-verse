#!/usr/bin/env python3
"""Smoke: publish lands clip + catalog entry, and commits ONLY the new entry.

Usage: ./.venv/bin/python scripts/smoke_animstudio_publish.py

No Blender: a fake build (FBX bytes + sidecar + build.json with the
source's sha) stands in for T3/T6. A throwaway GIT REPO with
shared/templates/pose/pose_catalog.json (a copy of the shipped one,
committed) is the target; the clip library is its shared/models/clips.
By hand:
[1] publish("demo-bow") with key "bowing": the FBX + sidecar sit in the
    temp library, the working-tree catalog has entries["bowing"] with
    animation "demo-bow", group "stand", solo true, synonyms lowercased.
[2] kind "demo-bow" again, a LICENSED "clash.fbx" present and kind "clash"
    -> StudioError before anything is written (library listing unchanged).
[3] key "sitting" (an existing key) or a synonym owned by another entry
    ("sitzen") -> StudioError, nothing written.
[4] a stale build (source edited after build -> sha differs) -> StudioError.
[6] a build whose entry breaks validate_catalog (group "nosuchgroup" is
    no place type) -> StudioError AFTER the files and the entry were
    written; the rollback leaves the catalog byte-identical and the library
    listing unchanged.
[7] another writer (the Poses tab) adds "foreign-race" to the catalog
    between our write and the validation, which then fails -> our key
    "race-key" is gone again, "foreign-race" stays (only our key is undone).
[8] --replace: a clip whose sidecar says author "animation-studio" (an own
    earlier publish, key "own-key") is refused again without replace and
    accepted with it; the catalog then still has exactly one "own-key".
    A foreign clip of that kind ([2]'s "demo-bow", no studio sidecar)
    stays refused even with replace.
[5] the catalog has a FOREIGN local edit (an extra entry "local-only" in the
    working tree, never committed): after publish of "demo-wave" (key
    "waving-demo") HEAD's catalog = previous HEAD + exactly "waving-demo"
    ("local-only" absent from HEAD), the working tree still has both, and
    `git diff HEAD -- <catalog>` shows only the "local-only" lines. The
    commit touches exactly: the catalog, the clip, its sidecar, the source.
    The shared index shows no staged change for those paths afterwards.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = Path(tempfile.mkdtemp(prefix="animstudio-repo-"))
# smoke_scripts_storage_lint accepts only a literal paths.init(...) or
# STORAGE_DIR before a world-DB import - bootstrap() is a wrapper it cannot see.
os.environ.setdefault("STORAGE_DIR", tempfile.mkdtemp(prefix="animstudio-world-"))
os.environ["ANIMATION_CLIPS_DIR"] = str(REPO / "shared/models/clips")
os.environ["ANIMATION_CLIPS_LICENSED_DIR"] = str(REPO / "shared/models/clips-licensed")
sys.path.insert(0, str(ROOT / "animation-studio"))

import animstudio                                                     # noqa: E402
animstudio.bootstrap()
animstudio.OUT = REPO / "animation-studio/out"
animstudio.ANIMS = REPO / "animation-studio/anims"

from app.core import pose_catalog as pc                               # noqa: E402
from animstudio import StudioError                                    # noqa: E402
from animstudio import publish as P                                   # noqa: E402

FAIL = []
CAT_REL = "shared/templates/pose/pose_catalog.json"


def git(*args, cwd=REPO):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                          text=True).stdout


def fake_build(kind, key, synonyms, group="stand"):
    src = animstudio.ANIMS / f"{kind}.py"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text(
        "from animstudio.dsl import Animation, Catalog\n"
        f"ANIM = Animation(kind={kind!r}, duration_s=1.0, loop=False,\n"
        f"    catalog=Catalog(key={key!r}, group={group!r}, prompt='Bowing politely',\n"
        f"                    synonyms={tuple(synonyms)!r}))\n")
    out = animstudio.OUT / kind
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{kind}.fbx").write_bytes(b"FBX-" + kind.encode())
    (out / f"{kind}.json").write_text(json.dumps({"kind": kind, "fps": 30}))
    from animstudio.build import spec_sha
    (out / "build.json").write_text(json.dumps({"kind": kind, "spec_sha": spec_sha(kind),
                                                "ok": True, "checks": []}))


try:
    (REPO / "shared/templates/pose").mkdir(parents=True)
    (REPO / "shared/models/clips").mkdir(parents=True)
    (REPO / "shared/models/clips-licensed").mkdir(parents=True)
    shutil.copy(ROOT / "shared/templates/pose/pose_catalog.json", REPO / CAT_REL)
    git("init", "-q")
    git("config", "user.email", "smoke@example.invalid")
    git("config", "user.name", "smoke")
    git("add", CAT_REL)
    git("commit", "-qm", "seed")
    pc.catalog_path = lambda a, _o=pc.catalog_path: (REPO / CAT_REL) if a == "pose" else _o(a)
    pc.reload_catalogs()

    # [1]
    fake_build("demo-bow", "bowing", ["Verbeugen", " sich verbeugen "])
    r = P.publish("demo-bow", repo=REPO, commit=False)
    lib = REPO / "shared/models/clips"
    if not (lib / "demo-bow.fbx").is_file() or not (lib / "demo-bow.json").is_file():
        FAIL.append("[1] clip files missing")
    e = json.loads((REPO / CAT_REL).read_text())["entries"].get("bowing") or {}
    if (e.get("animation"), e.get("group"), e.get("solo"), e.get("synonyms")) != \
            ("demo-bow", "stand", True, ["verbeugen", "sich verbeugen"]):
        FAIL.append(f"[1] entry {e}")
    # [2]
    (REPO / "shared/models/clips-licensed/clash.fbx").write_bytes(b"x")
    fake_build("clash", "clash-key", [])
    before = sorted(p.name for p in lib.iterdir())
    for kind in ("demo-bow", "clash"):
        try:
            P.publish(kind, repo=REPO, commit=False)
            FAIL.append(f"[2] {kind} accepted")
        except StudioError:
            pass
    if sorted(p.name for p in lib.iterdir()) != before:
        FAIL.append("[2] library changed")
    # [3]
    for key, syn in (("sitting", []), ("demo-x", ["sitzen"])):
        fake_build("demo-x", key, syn)
        cat_before = (REPO / CAT_REL).read_bytes()
        try:
            P.publish("demo-x", repo=REPO, commit=False)
            FAIL.append(f"[3] key {key} / {syn} accepted")
        except StudioError:
            pass
        if (REPO / CAT_REL).read_bytes() != cat_before or (lib / "demo-x.fbx").exists():
            FAIL.append(f"[3] {key}: something was written")
    # [4]
    fake_build("demo-stale", "stale-key", [])
    (animstudio.ANIMS / "demo-stale.py").write_text(
        (animstudio.ANIMS / "demo-stale.py").read_text() + "# edited\n")
    try:
        P.publish("demo-stale", repo=REPO, commit=False)
        FAIL.append("[4] stale build accepted")
    except StudioError:
        pass
    # [6]
    fake_build("demo-bad", "bad-key", [], group="nosuchgroup")
    cat_before, lib_before = (REPO / CAT_REL).read_bytes(), sorted(p.name for p in lib.iterdir())
    try:
        P.publish("demo-bad", repo=REPO, commit=False)
        FAIL.append("[6] invalid catalog accepted")
    except StudioError:
        pass
    if (REPO / CAT_REL).read_bytes() != cat_before:
        FAIL.append("[6] catalog not restored byte-identically")
    if sorted(p.name for p in lib.iterdir()) != lib_before:
        FAIL.append("[6] library changed")
    # [7]
    fake_build("demo-race", "race-key", [])
    real_validate = pc.validate_catalog

    def racing_validate(axis):
        d = json.loads((REPO / CAT_REL).read_text())
        d["entries"]["foreign-race"] = {"prompt": "p", "synonyms": [], "animation": "idle",
                                        "group": "stand", "solo": True}
        (REPO / CAT_REL).write_text(json.dumps(d, ensure_ascii=False, indent=2))
        return ["forced"]
    pc.validate_catalog = racing_validate
    try:
        P.publish("demo-race", repo=REPO, commit=False)
        FAIL.append("[7] forced problem accepted")
    except StudioError:
        pass
    finally:
        pc.validate_catalog = real_validate
    wt7 = json.loads((REPO / CAT_REL).read_text())["entries"]
    if "race-key" in wt7 or "foreign-race" not in wt7:
        FAIL.append(f"[7] race-key kept={'race-key' in wt7}, foreign kept={'foreign-race' in wt7}")
    if (lib / "demo-race.fbx").exists():
        FAIL.append("[7] clip file left behind")
    # [8]
    fake_build("demo-own", "own-key", [])
    (animstudio.OUT / "demo-own/demo-own.json").write_text(json.dumps(
        {"kind": "demo-own", "fps": 30, "source": {"format": "procedural",
                                                   "author": "animation-studio"}}))
    P.publish("demo-own", repo=REPO, commit=False)
    try:
        P.publish("demo-own", repo=REPO, commit=False)
        FAIL.append("[8] republish without replace accepted")
    except StudioError:
        pass
    try:
        P.publish("demo-own", repo=REPO, commit=False, replace=True)
    except StudioError as e:
        FAIL.append(f"[8] replace refused: {e}")
    if list(json.loads((REPO / CAT_REL).read_text())["entries"]).count("own-key") != 1:
        FAIL.append("[8] own-key not exactly once")
    try:
        P.publish("demo-bow", repo=REPO, commit=False, replace=True)
        FAIL.append("[8] replace of a foreign clip accepted")
    except StudioError:
        pass
    # [5] reset the working tree to HEAD, add a foreign local entry, publish with commit
    git("checkout", "--", CAT_REL)
    for f in ("demo-bow.fbx", "demo-bow.json"):
        (lib / f).unlink()
    pc.reload_catalogs()
    doc = json.loads((REPO / CAT_REL).read_text())
    doc["entries"]["local-only"] = {"prompt": "p", "synonyms": [], "animation": "idle",
                                    "group": "stand", "solo": True}
    (REPO / CAT_REL).write_text(json.dumps(doc, ensure_ascii=False, indent=2))
    pc.reload_catalogs()
    fake_build("demo-wave", "waving-demo", ["winken demo"])
    head_before = git("rev-parse", "HEAD").strip()
    r = P.publish("demo-wave", repo=REPO, commit=True, trailer="Co-Authored-By: smoke")
    head_doc = json.loads(git("show", f"HEAD:{CAT_REL}"))
    prev_doc = json.loads(git("show", f"{head_before}:{CAT_REL}"))
    if set(head_doc["entries"]) != set(prev_doc["entries"]) | {"waving-demo"}:
        FAIL.append("[5] HEAD catalog keys wrong")
    wt = json.loads((REPO / CAT_REL).read_text())["entries"]
    if "local-only" not in wt or "waving-demo" not in wt:
        FAIL.append("[5] working tree lost an entry")
    changed = sorted(git("show", "--name-only", "--format=", "HEAD").split())
    want = sorted([CAT_REL, "shared/models/clips/demo-wave.fbx",
                   "shared/models/clips/demo-wave.json", "animation-studio/anims/demo-wave.py"])
    if changed != want:
        FAIL.append(f"[5] commit touches {changed}")
    if git("diff", "--cached", "--name-only").strip():
        FAIL.append("[5] shared index has staged changes left")
    changed_lines = [ln for ln in git("diff", "HEAD", "--", CAT_REL).splitlines()
                     if ln.startswith(("+", "-")) and not ln.startswith(("+++", "---"))]
    if any('"waving-demo"' in ln for ln in changed_lines):
        FAIL.append("[5] diff HEAD still changes the published entry")
    if not any('"local-only"' in ln for ln in changed_lines):
        FAIL.append("[5] the foreign local entry vanished from the diff")
except Exception as e:                                                # noqa: BLE001
    import traceback
    traceback.print_exc()
    FAIL.append(f"crashed: {e!r}")
finally:
    shutil.rmtree(REPO, ignore_errors=True)

print("FAIL:\n" + "\n".join(FAIL) if FAIL else "OK smoke_animstudio_publish")
sys.exit(1 if FAIL else 0)
