#!/usr/bin/env python3
"""Downloads the CMU mocap originals listed in shared/models/cmu_catalog.json.

Every subject's skeleton (``.asf``) and every trial's motion (``.amc``) land
under ``shared/models/mocap-src/cmu/<subject>/`` with the file names the server
uses — that directory is the untouched source archive the converter reads from
and is not tracked by git.

Resumable: a file that already exists with a plausible size is left alone, so
an interrupted run simply continues.

Usage:
    ./.venv/bin/python scripts/cmu_fetch_all.py [options]

    # only two subjects, e.g. to re-pull a pair
    ./.venv/bin/python scripts/cmu_fetch_all.py --only 18,19

Options:
    --catalog <file>  catalog to read (default: shared/models/cmu_catalog.json)
    --dest <dir>      target directory (default: shared/models/mocap-src/cmu)
    --only <list>     comma-separated subject numbers
    --jobs <n>        parallel downloads, capped at 3 — the CMU server is a
                      university host, not a CDN (default 1)
    --pause <s>       seconds between downloads (default 0.25)
    --retries <n>     attempts per file (default 3)
"""
import argparse
import json
import ssl
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import paths  # noqa: E402

CMU_BASE = "https://mocap.cs.cmu.edu"
MIN_BYTES = 100

_UNVERIFIED = ssl.create_default_context()
_UNVERIFIED.check_hostname = False
_UNVERIFIED.verify_mode = ssl.CERT_NONE

# The CMU server ships an incomplete certificate chain, so verification fails
# for every file alike. Once it has failed once, stop paying for the doomed
# handshake — the data is public and its integrity is checked by the parser.
_verify = True


def default_catalog() -> Path:
    return paths.get_shared_dir() / "models" / "cmu_catalog.json"


def default_dest() -> Path:
    return paths.get_shared_dir() / "models" / "mocap-src" / "cmu"


def have(dest: Path) -> bool:
    return dest.is_file() and dest.stat().st_size >= MIN_BYTES


def read_url(url: str) -> bytes:
    global _verify
    if _verify:
        try:
            with urllib.request.urlopen(url, timeout=120) as r:
                return r.read()
        except (urllib.error.URLError, ssl.SSLError):
            _verify = False
    with urllib.request.urlopen(url, timeout=120, context=_UNVERIFIED) as r:
        return r.read()


def download(url: str, dest: Path, retries: int, pause: float) -> bool:
    """One file, retried."""
    if have(dest):
        return True
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + f".part{threading.get_ident():x}")
    for attempt in range(1, retries + 1):
        try:
            tmp.write_bytes(read_url(url))
            if tmp.stat().st_size < MIN_BYTES:
                raise OSError(f"suspiciously small ({tmp.stat().st_size} bytes)")
            tmp.replace(dest)
            time.sleep(pause)
            return True
        except Exception as e:
            print(f"    attempt {attempt}/{retries} failed for {url}: {e}", flush=True)
            time.sleep(min(30.0, 2.0 * attempt))
    tmp.unlink(missing_ok=True)
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--catalog", default="")
    ap.add_argument("--dest", default="")
    ap.add_argument("--only", default="")
    ap.add_argument("--jobs", type=int, default=1)
    ap.add_argument("--pause", type=float, default=0.25)
    ap.add_argument("--retries", type=int, default=3)
    a = ap.parse_args()

    catalog = Path(a.catalog) if a.catalog else default_catalog()
    if not catalog.is_file():
        raise SystemExit(f"catalog not found: {catalog} — run scripts/cmu_catalog.py first")
    dest_root = Path(a.dest) if a.dest else default_dest()
    takes = json.loads(catalog.read_text(encoding="utf-8"))["takes"]

    only = {int(x) for x in a.only.replace(" ", "").split(",") if x} if a.only else set()
    if only:
        takes = [t for t in takes if t["subject"] in only]

    # One ASF per subject, one AMC per take.
    wanted = {}
    for t in takes:
        wanted[(t["subject_dir"], Path(t["asf"]).name)] = t["asf"]
        wanted[(t["subject_dir"], Path(t["amc"]).name)] = t["amc"]

    total = len(wanted)
    todo = [(dest_root / subject_dir / name, CMU_BASE + url_path)
            for (subject_dir, name), url_path in sorted(wanted.items())
            if not have(dest_root / subject_dir / name)]
    skipped = total - len(todo)
    counter = {"done": 0, "failed": 0}
    lock = threading.Lock()
    started = time.time()
    print(f"{total} files → {dest_root} ({skipped} already present, {len(todo)} to fetch)",
          flush=True)

    def work(item) -> None:
        target, url = item
        ok = download(url, target, a.retries, a.pause)
        with lock:
            counter["done" if ok else "failed"] += 1
            n = counter["done"] + counter["failed"]
            if n % 25 == 0 or not ok or n == len(todo):
                rate = n / max(1e-6, time.time() - started)
                print(f"  [{n}/{len(todo)}] fetched {counter['done']}, "
                      f"failed {counter['failed']}, {rate * 60:.0f}/min", flush=True)

    jobs = max(1, min(3, a.jobs))          # never hammer a university server
    if jobs > 1:
        with ThreadPoolExecutor(max_workers=jobs) as pool:
            list(pool.map(work, todo))
    else:
        for item in todo:
            work(item)
    print(f"done: fetched {counter['done']}, already present {skipped}, "
          f"failed {counter['failed']}", flush=True)
    return 1 if counter["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
