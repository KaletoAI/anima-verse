#!/usr/bin/env python3
"""The Figure tab's poll (``base_body.base_info``, ``GET /characters/{c}/figure?plain=1`` every 3 s) does not
re-read or re-hash the full-body reference and its post-processed copy (review 08b#1).

Usage:
    ./.venv/bin/python scripts/smoke_base_info_poll_cost.py

Runs against a THROWAWAY storage + instance directory with a copy of the repo's ``human`` package — no world, no
hub, no server. ``pathlib.Path.read_bytes`` and ``hashlib.sha256`` are wrapped by counters that count a read of /
a hash over the bytes of exactly two files: the full-body reference ORIGINAL and its post-processed COPY.

Fixture: ``Demo`` (human, profile image ``Demo_1.png``) with a full-body reference ``full.png`` (64 x 64 RGBA, a
figure disc on a transparent background — it carries its own matte, so no BiRefNet) recorded with origin "upload",
and ONE stand-in reference operation (``invert``: inverts the colour inside the matte, so it always finds
something) checked for Demo. The four stored base views of the current base are 8 x 8 PNGs whose front sidecar
records ``front_reference`` as a render would (so the front is current).

Expected, derived by hand from the code paths:

* Steady state (a second poll, nothing changed): every hash of the original and of the copy goes through the
  stat-keyed ``base_body.file_sha256`` (size, mtime_ns, inode unchanged -> the cached digest), and the copy's
  record exists (``reference_record`` answers, ``processed_reference`` never reads the bytes) ->
  original 0 reads / 0 hashes, copy 0 reads / 0 hashes.
  Before the fix ``view_postprocess`` hashed with a bare ``sha256(read_bytes())`` on each of its calls: per
  ``front_source_image`` one read+hash of the original in ``processed_reference`` and one read+hash of the original
  plus one of the copy in its ``reference_record``; per ``reference_record`` of ``_reference_state`` /
  ``postprocess_followup`` the same two pairs — this smoke run on 18b50231a printed 8 reads + 8 hashes of the
  original and 5 + 5 of the copy per steady poll (13 full reads and sha256 runs of a multi-MB picture in practice)
  and failed every count below.
* Cold poll right after the reference's bytes changed (new size and mtime -> the cache misses once, a new copy key):
  original: ``file_sha256`` 1 read + 1 hash; the record of the new key is missing, so ``processed_reference``
  reads the bytes it processes (read 2) and hashes them (hash 2) -> 2 reads / 2 hashes.
  copy: written by the operation, ``processed_reference`` hashes the bytes it writes (hash 1, no read), the next
  ``reference_record`` hashes the new file once through ``file_sha256`` (read 1, hash 2) -> 1 read / 2 hashes.
  Every later call of that poll is a cache hit.
* The payload is unchanged by the cache: ``postprocess.reference.processed`` True and ``front_reference.current``
  True in the steady state; after the change the front is outdated with ``FRONT_OTHER_FULL_BODY``.
"""
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}" + ("" if ok else f" — expected {want!r}"))
    if not ok:
        FAILS.append(label)


def figure_png(colour) -> bytes:
    import numpy as np
    from PIL import Image
    yy, xx = np.mgrid[0:64, 0:64]
    a = np.zeros((64, 64, 4), np.uint8)
    disc = (xx - 32) ** 2 + (yy - 32) ** 2 <= 24 * 24
    a[disc, :3] = colour
    a[disc, 3] = 255
    buf = io.BytesIO()
    Image.fromarray(a, "RGBA").save(buf, "PNG")
    return buf.getvalue()


def tiny_png(path: Path) -> None:
    from PIL import Image
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (8, 8), (200, 100, 50, 255)).save(path)


def invert(image, *, view, params):
    import numpy as np
    from PIL import Image
    a = np.asarray(image).copy()
    inside = a[..., 3] > 127
    a[inside, :3] = 255 - a[inside, :3]
    return {"image": Image.fromarray(a, "RGBA"), "found": int(inside.sum()), "regions": [], "seconds": 0.0}


class Counter:
    """Counts reads of / sha256 over the bytes of the watched files."""

    def __init__(self):
        self.files = {}          # label -> Path
        self.reads = {}
        self.hashes = {}
        self._real_read = Path.read_bytes
        self._real_sha = hashlib.sha256

    def reset(self):
        self.reads = {k: 0 for k in self.files}
        self.hashes = {k: 0 for k in self.files}

    def install(self):
        counter = self

        def read_bytes(path):
            data = counter._real_read(path)
            for label, watched in counter.files.items():
                if watched is not None and os.path.abspath(path) == os.path.abspath(watched):
                    counter.reads[label] += 1
            return data

        def sha256(data=b"", *args, **kwargs):
            for label, watched in counter.files.items():
                if watched is not None and data and len(data) > 64 and os.path.isfile(watched) \
                        and bytes(data) == counter._real_read(watched):
                    counter.hashes[label] += 1
            return counter._real_sha(data, *args, **kwargs)

        Path.read_bytes = read_bytes
        hashlib.sha256 = sha256

    def remove(self):
        Path.read_bytes = self._real_read
        hashlib.sha256 = self._real_sha


def main() -> int:
    counter = Counter()
    with tempfile.TemporaryDirectory(prefix="base-info-poll-") as tmp:
        root = Path(tmp)
        os.environ["STORAGE_DIR"] = str(root / "world")
        os.environ["INSTANCE_DIR"] = str(root / "instance")
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "instance")
        paths.get_config_path().write_text(json.dumps({"packages": {"enabled": "human"}}))
        from app.core import config
        config.load(paths.get_config_path(), instance_path=root / "instance/config.json")
        from app.core import db
        db.init_schema()
        plugins = root / "plugins"
        shutil.copytree(ROOT / "plugins" / "human", plugins / "human")
        from app.plugins.loader import discover_packages
        discover_packages(plugins, force=True)

        from app.core import base_body, hooks, view_postprocess
        from app.core.model_refs import get_model_refs_dir
        from app.models.character import get_character_images_dir, get_character_profile, save_character_profile
        hooks.register_provider(view_postprocess.CAPABILITY,
                                lambda: {"id": "invert", "label": "Invert", "views": ["front"], "params": {},
                                         "apply": invert}, owner="smoke_poll", multiple=True)
        human = {"template": "human-default", "gender": "female", "age": 30, "height": 168,
                 "body_slots": {"skin": {"tone": "olive"}, "eyes": {"color": "green"},
                                "build": {"type": "athletic"}}}
        check("create Demo", save_character_profile("Demo", dict(human), create_new=True), True)
        tiny_png(get_character_images_dir("Demo") / "Demo_1.png")
        refs = get_model_refs_dir("Demo")
        original = refs / "references" / "full.png"
        original.parent.mkdir(parents=True, exist_ok=True)
        original.write_bytes(figure_png((180, 140, 120)))
        stored = get_character_profile("Demo")
        stored["profile_image"] = "Demo_1.png"
        stored["full_body_reference"] = {"image": "full.png", "sha256": hashlib.sha256(original.read_bytes())
                                         .hexdigest(), "origin": "upload"}
        stored[view_postprocess.PROFILE_KEY] = {"invert": True}
        check("profile saved", save_character_profile("Demo", stored), True)

        bsig = base_body.base_signature("Demo")
        wanted = base_body.front_reference("Demo")      # makes the processed copy
        check("front made from the processed copy", (wanted.get("source"), wanted.get("postprocess")),
              ("full_body", ["invert"]))
        copy = next(view_postprocess.processed_dir("Demo").glob("full_pp*.png"))
        for view in base_body.BASE_VIEWS:
            path = refs / f"{base_body._kind(view)}_{bsig}.png"
            tiny_png(path)
            meta = {"base_signature": bsig, "base_identity": base_body.base_identity("Demo"),
                    "prompt_fingerprint": base_body.prompt_fingerprint("Demo"), "prompt_rules": "a74a"}
            if view == "front":
                meta["front_reference"] = wanted
            path.with_suffix(".json").write_text(json.dumps(meta))

        counter.files = {"original": original, "copy": copy}
        counter.install()
        try:
            counter.reset()
            first = base_body.base_info("Demo")
            print(f"       first poll: reads {counter.reads}, hashes {counter.hashes}")
            counter.reset()
            info = base_body.base_info("Demo")
            print(f"       steady poll: reads {counter.reads}, hashes {counter.hashes}")
            print("[1] steady state")
            check("original reads", counter.reads["original"], 0)
            check("original hashes", counter.hashes["original"], 0)
            check("copy reads", counter.reads["copy"], 0)
            check("copy hashes", counter.hashes["copy"], 0)
            check("payload: processed", (info.get("postprocess") or {}).get("reference", {}).get("processed"), True)
            check("payload: front current", (info.get("front_reference") or {}).get("current"), True)
            check("payload equal to the first poll", (first["front_reference"], first["postprocess"]),
                  (info["front_reference"], info["postprocess"]))

            print("[2] cold poll after the reference changed")
            original.write_bytes(figure_png((90, 60, 40)) + b"")
            counter.reset()
            info = base_body.base_info("Demo")
            new_copy = next(view_postprocess.processed_dir("Demo").glob("full_pp*.png"))
            check("a new copy replaced the old one", (new_copy != copy, copy.exists()), (True, False))
            # The copy's bytes are new: count the new file under the same label from here on.
            print(f"       cold poll: reads {counter.reads}, hashes {counter.hashes}")
            check("original reads", counter.reads["original"], 2)
            check("original hashes", counter.hashes["original"], 2)
            counter.files["copy"] = new_copy
            counter.reset()
            info = base_body.base_info("Demo")
            check("next poll: no read or hash at all", (counter.reads, counter.hashes),
                  ({"original": 0, "copy": 0}, {"original": 0, "copy": 0}))
            check("payload: front outdated by the other reference",
                  (info["front_reference"]["current"], info["front_reference"]["reason"]),
                  (False, base_body.FRONT_OTHER_FULL_BODY))
        finally:
            counter.remove()

        print("[3] the copy's two hashes in the cold poll")
        # Counted apart: during the cold poll the copy did not exist under a known name yet. Re-run it on a third
        # content and watch the copy path that results (it is named by the content's key, computed here).
        original.write_bytes(figure_png((20, 200, 20)))
        from app.core.view_postprocess import _copy_paths, _key
        available = view_postprocess.operations()
        key = _key(hashlib.sha256(original.read_bytes()).hexdigest(), ["invert"], available)
        third, _sidecar = _copy_paths("Demo", original, key)
        counter.files = {"original": original, "copy": third}
        counter.install()
        try:
            counter.reset()
            base_body.base_info("Demo")
            print(f"       cold poll: reads {counter.reads}, hashes {counter.hashes}")
            check("original: 2 reads / 2 hashes", (counter.reads["original"], counter.hashes["original"]), (2, 2))
            check("copy: 1 read / 2 hashes", (counter.reads["copy"], counter.hashes["copy"]), (1, 2))
        finally:
            counter.remove()

    print()
    if FAILS:
        print(f"{len(FAILS)} failure(s): {', '.join(FAILS)}")
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
