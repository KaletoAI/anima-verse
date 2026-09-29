#!/usr/bin/env python3
"""Smoke: the pose catalog cache follows an EXTERNAL edit of its file.

Usage: ./.venv/bin/python scripts/smoke_catalog_file_reload.py

Temp world; the catalog is a private COPY injected through
pose_catalog.catalog_path (the one funnel loader and router share). The real
shared/templates/pose/pose_catalog.json is never written (checked byte for
byte at the end). By hand:
[1] get_catalog("pose") holds the shipped keys; `smoke-extern` is absent;
    get_groups() is read (so the groups cache is FILLED before [3]).
[2] the file is rewritten from OUTSIDE (plain write, no reload call) with an
    added entry `smoke-extern` -> the very next get_catalog has it, and the
    alias embedding cache holds no entry of the pose axis any more (its keys
    are (axis, model id) tuples; a seeded ("pose", "smoke-model") entry must
    be gone, a seeded ("expression", "smoke-model") entry must survive — the
    expression file did not change) so new synonyms reach the matcher.
[3] a group label edited on disk ("seat" -> "Seat X") -> get_groups() shows it.
[4] catalog_file_lock is exclusive: a second flock(LOCK_EX|LOCK_NB) on the
    same lock file from another open file description raises
    BlockingIOError while the first is held, and succeeds after release.
[5] write_shared_document writes json.dumps(doc, ensure_ascii=False, indent=2)
    byte for byte (no trailing newline) and keeps the file mode (0o644 here).
[6] an alias-embedding warm-up that started on the OLD catalog does not park
    its vectors after the file changed under it: the embed function edits the
    file on its first call and reads the catalog (-> drop). The returned map
    lacks `smoke-late`, and nothing is cached for ("pose", <fn key>); the next
    call embeds again and its map carries `smoke-late`.
"""
import fcntl
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_tmp = tempfile.mkdtemp(prefix="smoke_catalog_reload_")
os.environ.setdefault("STORAGE_DIR", _tmp)
from app.core import paths                                            # noqa: E402
paths.init(_tmp)
from app.core import pose_catalog as pc                               # noqa: E402
from app.core.db import init_schema                                   # noqa: E402

FAIL = []
REAL = pc.catalog_path("pose")
REAL_BYTES = REAL.read_bytes()
orig = pc.catalog_path
try:
    init_schema()
    cat = Path(_tmp) / "pose_catalog.json"
    cat.write_bytes(REAL_BYTES)
    os.chmod(cat, 0o644)
    pc.catalog_path = lambda a: cat if a == "pose" else orig(a)
    pc.reload_catalogs()
    if "smoke-extern" in pc.get_catalog("pose"):
        FAIL.append("[1] smoke-extern present before the edit")
    if pc.get_groups()["seat"]["label"] == "Seat X":
        FAIL.append("[1] group label already edited")
    pc.get_catalog("expression")
    pc._embed_cache[("pose", "smoke-model")] = {"x": [1.0]}
    pc._embed_cache[("expression", "smoke-model")] = {"y": [1.0]}
    doc = json.loads(cat.read_text(encoding="utf-8"))
    doc["entries"]["smoke-extern"] = {"prompt": "p", "synonyms": [], "animation": "idle",
                                      "group": "stand", "solo": True}
    cat.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    if "smoke-extern" not in pc.get_catalog("pose"):
        FAIL.append("[2] external edit not seen")
    if any(k[0] == "pose" for k in pc._embed_cache):
        FAIL.append(f"[2] pose embed cache not dropped: {list(pc._embed_cache)}")
    pc.get_catalog("expression")
    if ("expression", "smoke-model") not in pc._embed_cache:
        FAIL.append("[2] expression embed cache dropped although its file is unchanged")
    doc["groups"]["seat"]["label"] = "Seat X"
    cat.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    if pc.get_groups()["seat"]["label"] != "Seat X":
        FAIL.append("[3] group edit not seen")
    with pc.catalog_file_lock("pose"):
        fd = os.open(str(cat) + ".lock", os.O_RDWR | os.O_CREAT)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            FAIL.append("[4] second lock acquired while held")
        except BlockingIOError:
            pass
        finally:
            os.close(fd)
    fd = os.open(str(cat) + ".lock", os.O_RDWR)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    os.close(fd)
    pc.write_shared_document("pose", doc)
    if cat.read_text(encoding="utf-8") != json.dumps(doc, ensure_ascii=False, indent=2):
        FAIL.append("[5] format differs")
    if (cat.stat().st_mode & 0o777) != 0o644:
        FAIL.append("[5] mode changed")

    edited = {"done": False}

    def racing_embed(alias):
        if not edited["done"]:
            edited["done"] = True
            doc["entries"]["smoke-late"] = {"prompt": "p", "synonyms": [],
                                            "animation": "idle", "group": "stand",
                                            "solo": True}
            cat.write_text(json.dumps(doc, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            pc.get_catalog("pose")          # a reader notices the edit -> drop
        return [1.0, 0.0]

    fn_key = ("pose", pc._embed_model_key(racing_embed))
    first = pc._alias_embeddings("pose", racing_embed)
    if "smoke-late" in first:
        FAIL.append("[6] first map already carries smoke-late")
    if fn_key in pc._embed_cache:
        FAIL.append("[6] vectors of the old catalog were cached after the drop")
    second = pc._alias_embeddings("pose", racing_embed)
    if "smoke-late" not in second:
        FAIL.append("[6] second map misses smoke-late")
    if pc._embed_cache.get(fn_key) is not second:
        FAIL.append("[6] second map not cached")
except Exception as e:                                                # noqa: BLE001
    import traceback
    traceback.print_exc()
    FAIL.append(f"crashed: {e!r}")
finally:
    pc.catalog_path = orig
    if REAL.read_bytes() != REAL_BYTES:
        FAIL.append("REAL catalog modified")
    shutil.rmtree(_tmp, ignore_errors=True)
print("FAIL:\n" + "\n".join(FAIL) if FAIL else "OK smoke_catalog_file_reload")
sys.exit(1 if FAIL else 0)
