#!/usr/bin/env python3
"""Smoke run for the marketplace BULK publish (plan-marketplace-props.md
Teil E, ``app/core/marketplace_publish.py``). Throwaway storage; the store's
``publish`` is replaced by a recorder, so no host is involved. By hand:

Seed: 23 props "P00".."P22", job list = the 23 ids with the unknown id
"nope" inserted at position 5 → 24 items. A chunk is sent once it holds
CHUNK = 10 BUILT packs (or CHUNK_BYTES): positions 0..10 (nope at 5 fails to
build) = 10 packs, 11..20 = 10 packs, 21..23 = 3 packs.

[1] all goes well → three store calls with 10, 10, 3 packs; flush_every
    equals the chunk size each time (one index write per call); job "done",
    done == total == 24; "nope" is "error", the 23 props "success"; each pack
    is named after its prop ("P00", …) and carries the given tags.
[2] the SECOND store call raises (a lost index race) → job "error"; positions
    0..10 stay as they were (10 success + "nope" error), the 13 items of
    positions 11..23 are "skipped" — reported, not retried — and done == 24
    (every item has its final status).
[3] a second start for the same catalog while a job runs → BulkJobRunning
    naming the running job; the running one ends "done".
[4] one entity fails with an UNEXPECTED exception (KeyError, a malformed
    record) → that item "error" with the exception's name, the job "done",
    the other two published.
[5] CHUNK_BYTES set to 1 byte → every pack goes out in its own store call:
    3 props → calls of 1, 1, 1.

Usage:  ./.venv/bin/python scripts/smoke_marketplace_bulk.py
"""
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="marketplace-bulk-smoke-"))
os.environ["STORAGE_DIR"] = str(STORAGE)
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="marketplace-bulk-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import db  # noqa: E402
db.init_schema()

from app.core import marketplace_publish as mp  # noqa: E402
from app.core import props  # noqa: E402
from app.core.marketplace_store import CatalogRepo, MarketplaceError  # noqa: E402

FAILURES = []


def check(label, actual, expected):
    ok = actual == expected
    print(f"  {'✓' if ok else '✗'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


ids = [props.create_prop(name=f"P{i:02d}", category="misc")["id"] for i in range(23)]
job_ids = ids[:5] + ["nope"] + ids[5:]
repo = CatalogRepo.from_url("https://github.com/o/r", "tok")
calls = []


def wait(job_id):
    for _ in range(600):
        job = mp.get_job(job_id)
        if job["status"] != "running":
            return job
        time.sleep(0.05)
    return mp.get_job(job_id)


def recorder(fail_on=None, gate=None):
    def fake(repo_, pack_type, uploads, *, sweep_age_s, flush_every, **kw):
        if gate:
            gate.wait(10)
        calls.append((len(uploads), flush_every,
                      [u.entry["name"] for u in uploads], [u.entry["tags"] for u in uploads]))
        if fail_on and len(calls) == fail_on:
            raise MarketplaceError("another publish wrote the catalog index at the same time")
        return [{"pack_id": u.entry["id"], "status": "success"} for u in uploads]
    return fake


print("\n[1] a clean run")
mp.publish = recorder()
job = wait(mp.start_bulk(repo, "main", "prop", job_ids, ["town"],
                         max_pack_mb=500, sweep_age_s=3600)["id"])
check("chunk sizes", [c[0] for c in calls], [10, 10, 3])
check("one index write per call", [c[1] for c in calls], [10, 10, 3])
check("status", job["status"], "done")
check("done / total", (job["done"], job["total"]), (24, 24))
check("nope", next(i["status"] for i in job["items"] if i["entity_id"] == "nope"), "error")
check("successes", sum(i["status"] == "success" for i in job["items"]), 23)
check("named after the props", calls[0][2][:3], ["P00", "P01", "P02"])
check("tags", calls[0][3][0], ["town"])

print("\n[2] the second store call fails")
calls.clear()
mp.publish = recorder(fail_on=2)
job = wait(mp.start_bulk(repo, "main", "prop", job_ids, [],
                         max_pack_mb=500, sweep_age_s=3600)["id"])
statuses = [i["status"] for i in job["items"]]
check("status", job["status"], "error")
check("positions 0..10 published", statuses[:11].count("success"), 10)
check("nope still an error", statuses[5], "error")
check("the rest skipped", statuses[11:], ["skipped"] * 13)
check("done after abort", job["done"], 24)
check("error reported", "at the same time" in job["error"], True)

print("\n[3] one running job per catalog")
calls.clear()
gate = threading.Event()
mp.publish = recorder(gate=gate)
first = mp.start_bulk(repo, "main", "prop", ids[:2], [], max_pack_mb=500, sweep_age_s=3600)
try:
    mp.start_bulk(repo, "main", "prop", ids[2:4], [], max_pack_mb=500, sweep_age_s=3600)
    check("second start refused", "started", "BulkJobRunning")
except mp.BulkJobRunning as e:
    check("second start refused, naming the running job", e.job_id, first["id"])
gate.set()
check("first job ends done", wait(first["id"])["status"], "done")

print("\n[4] an unexpected exception for one entity")
calls.clear()
mp.publish = recorder()
real_text = mp.default_text


def broken_text(pack_type, entity_id):
    if entity_id == ids[1]:
        raise KeyError("name")
    return real_text(pack_type, entity_id)


mp.default_text = broken_text
job = wait(mp.start_bulk(repo, "main", "prop", ids[:3], [], max_pack_mb=500,
                         sweep_age_s=3600)["id"])
mp.default_text = real_text
check("job done", job["status"], "done")
check("statuses", [i["status"] for i in job["items"]], ["success", "error", "success"])
check("error names the exception", job["items"][1]["error"], "'name'")

print("\n[5] the byte budget closes a chunk early")
calls.clear()
mp.CHUNK_BYTES = 1
job = wait(mp.start_bulk(repo, "main", "prop", ids[:3], [], max_pack_mb=500,
                         sweep_age_s=3600)["id"])
check("one pack per call", [c[0] for c in calls], [1, 1, 1])

print("\nall checks passed" if not FAILURES
      else f"\n{len(FAILURES)} check(s) FAILED: {FAILURES}")
sys.exit(1 if FAILURES else 0)
