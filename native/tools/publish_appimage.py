#!/usr/bin/env python3
"""Publish a complete AppImage before atomically replacing its manifest."""
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile


def publish(image: Path, version: str, destination: Path) -> None:
    if not re.fullmatch(r"\d{14}-[0-9a-f]{7,40}", version):
        raise ValueError("publishing requires a clean commit version")
    name = f"AnimaNative-{version}-x86_64.AppImage"
    if image.name != name:
        raise ValueError("AppImage filename does not match its baked version")
    destination.mkdir(parents=True, exist_ok=True)
    # Serialize publishers, including cleanup of older releases.
    with (destination / ".publish.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        staged = []
        try:
            with tempfile.NamedTemporaryFile(dir=destination, suffix=".tmp", delete=False) as output:
                staged.append(Path(output.name))
                with image.open("rb") as source:
                    shutil.copyfileobj(source, output)
                output.flush()
                os.fsync(output.fileno())
            payload = staged[-1]
            sha256 = hashlib.sha256()
            with payload.open("rb") as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    sha256.update(chunk)
            manifest = {
                "version": version,
                "file": name,
                "size": payload.stat().st_size,
                "sha256": sha256.hexdigest(),
                "built_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
            payload.chmod(0o755)
            with tempfile.NamedTemporaryFile(mode="w", dir=destination, suffix=".tmp", delete=False) as output:
                staged.append(Path(output.name))
                json.dump(manifest, output, indent=2)
                output.write("\n")
                output.flush()
                os.fchmod(output.fileno(), 0o644)
                os.fsync(output.fileno())
            os.replace(payload, destination / name)
            os.replace(staged[-1], destination / "version.json")
            for old in destination.glob("AnimaNative-*-x86_64.AppImage"):
                if old.name != name:
                    old.unlink()
        finally:
            for path in staged:
                path.unlink(missing_ok=True)


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit("usage: publish_appimage.py IMAGE VERSION DESTINATION")
    publish(Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3]))
