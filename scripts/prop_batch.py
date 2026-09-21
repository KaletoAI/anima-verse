#!/usr/bin/env python3
"""Generate a batch of props with several model variants each, one mesh at a
time, against a RUNNING server.

Usage:
    ./.venv/bin/python scripts/prop_batch.py --job JOB.json --password-file PW \
        [--base http://127.0.0.1:8000] [--user admin] [--image-backend GLOB] \
        [--mesh-backend GLOB] [--poll 30] [--timeout 2700]

The job file is a JSON list; every entry describes one prop and the subjects
of its variants (the first subject is variant 0, the rest are appended):

    [{"name": "Compact hatchback", "category": "vehicle", "mount": "floor",
      "width_m": 4.3, "depth_m": 1.8, "height_m": 1.5,
      "reference": true,
      "variants": ["a silver compact hatchback car, ...",
                   "the same car in dark red", ...]}]

``reference`` slots variant 0's front image as the appearance reference of
every further variant (the body shape stays, the paint changes); leave it out
for objects whose variants should differ in shape.

The script is the "controlled" half of an overnight run: it triggers ONE
generation at a time and waits for its mesh to land before it starts the next
(the server's own double-click guard forbids two runs on the same variant,
and every mesh queues on the same GPU channel anyway). A failed variant is
retried once and then skipped. It is resumable — a prop that already exists
by name is picked up, variants that carry a mesh are skipped — and it stops
between two steps when a file named ``<job>.stop`` appears next to the job.
Progress is written to ``<job>.state.json`` and to stdout.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib import request as _rq
from urllib.error import HTTPError


class Api:
    """Minimal cookie-session client for the admin API."""

    def __init__(self, base: str, user: str, password: str):
        self.base = base.rstrip("/")
        self.user = user
        self.password = password
        self.cookie = ""

    def login(self) -> None:
        req = _rq.Request(f"{self.base}/auth/login",
                          data=json.dumps({"username": self.user,
                                           "password": self.password}).encode(),
                          headers={"Content-Type": "application/json"},
                          method="POST")
        with _rq.urlopen(req, timeout=60) as resp:
            raw = resp.headers.get("Set-Cookie") or ""
            self.cookie = raw.split(";", 1)[0]
            if not self.cookie:
                raise RuntimeError("login returned no session cookie")

    def call(self, method: str, path: str, body: Any = None,
             _retry: bool = True) -> Any:
        data = None
        headers = {"Cookie": self.cookie}
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        req = _rq.Request(f"{self.base}{path}", data=data, headers=headers,
                          method=method)
        try:
            with _rq.urlopen(req, timeout=120) as resp:
                text = resp.read().decode()
                return json.loads(text) if text else {}
        except HTTPError as e:
            if e.code == 401 and _retry:
                self.login()
                return self.call(method, path, body, _retry=False)
            detail = e.read().decode(errors="replace")[:300]
            raise RuntimeError(f"{method} {path} -> {e.code}: {detail}") from None


def log(msg: str) -> None:
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def find_prop_by_name(api: Api, name: str) -> Optional[Dict[str, Any]]:
    listing = api.call("GET", "/world/props")
    for p in listing.get("props", []):
        if (p.get("name") or "").strip().lower() == name.strip().lower():
            return p
    return None


def variants(api: Api, prop_id: str) -> List[Dict[str, Any]]:
    res = api.call("GET", f"/world/props/{prop_id}/variants")
    return list(res.get("variants") or [])


def is_pending(api: Api, prop_id: str) -> bool:
    """Is a generation of any variant of this prop in flight?"""
    res = api.call("GET", f"/world/props/{prop_id}/variants")
    return bool(res.get("generating_variants"))


def wait_for_mesh(api: Api, prop_id: str, index: int, poll: float,
                  timeout: float) -> bool:
    """Block until variant ``index`` carries a mesh, or the run ended without
    one, or ``timeout`` seconds passed. True only for a landed mesh."""
    started = time.time()
    seen_pending = False
    while time.time() - started < timeout:
        time.sleep(poll)
        try:
            vs = variants(api, prop_id)
            entry = next((v for v in vs if int(v.get("index", -1)) == index), None)
            if entry and entry.get("has_model"):
                return True
            pending = is_pending(api, prop_id)
        except Exception as e:  # network hiccup — keep waiting
            log(f"  poll error: {e}")
            continue
        if pending:
            seen_pending = True
            continue
        # Not pending any more and still no mesh: the run ended in failure.
        # Give the server one more poll before believing that — the header
        # task is closed a moment before the sidecar is written.
        if seen_pending or time.time() - started > 3 * poll:
            time.sleep(poll)
            vs = variants(api, prop_id)
            entry = next((v for v in vs if int(v.get("index", -1)) == index), None)
            return bool(entry and entry.get("has_model"))
    log(f"  timeout after {int(timeout)} s")
    return False


def stop_requested(job: Path) -> bool:
    return job.with_suffix(job.suffix + ".stop").exists()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--job", required=True)
    ap.add_argument("--password-file", required=True)
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--user", default="admin")
    ap.add_argument("--image-backend", default="")
    ap.add_argument("--mesh-backend", default="")
    ap.add_argument("--poll", type=float, default=30.0)
    ap.add_argument("--timeout", type=float, default=2700.0,
                    help="seconds to wait for one mesh before giving up")
    args = ap.parse_args()

    job = Path(args.job)
    entries = json.loads(job.read_text(encoding="utf-8"))
    state_path = job.with_suffix(job.suffix + ".state.json")
    state: Dict[str, Any] = {}
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))

    def save_state() -> None:
        state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False),
                              encoding="utf-8")

    api = Api(args.base, args.user,
              Path(args.password_file).read_text(encoding="utf-8").strip())
    api.login()
    log(f"logged in as {args.user}; {len(entries)} props in {job.name}")

    gen_body_base: Dict[str, Any] = {}
    if args.image_backend:
        gen_body_base["image_backend"] = args.image_backend
    if args.mesh_backend:
        gen_body_base["mesh_backend"] = args.mesh_backend

    for entry in entries:
        name = entry["name"]
        subjects: List[str] = list(entry.get("variants") or [])
        if not subjects:
            log(f"skip {name!r}: no variants")
            continue
        if stop_requested(job):
            log("stop file found — leaving before the next prop")
            return 0
        st = state.setdefault(name, {"prop_id": "", "done": [], "failed": []})
        prop = None
        if st["prop_id"]:
            try:
                prop = api.call("GET", f"/world/props/{st['prop_id']}")
            except RuntimeError:
                prop = None
        if not prop:
            prop = find_prop_by_name(api, name)
        if prop:
            prop_id = prop["id"]
            log(f"== {name}: exists as {prop_id}")
        else:
            body = {"name": name,
                    "category": entry.get("category", ""),
                    "width_m": entry.get("width_m"),
                    "depth_m": entry.get("depth_m"),
                    "height_m": entry.get("height_m"),
                    "description": subjects[0],
                    **gen_body_base}
            res = api.call("POST", "/world/props/generate", body)
            prop_id = res["prop"]["id"]
            log(f"== {name}: created {prop_id}, variant 0 generating")
            if entry.get("mount"):
                try:
                    api.call("POST", f"/world/props/{prop_id}",
                             {"mount": entry["mount"]})
                except RuntimeError as e:
                    log(f"  mount not set: {e}")
            st["prop_id"] = prop_id
            save_state()
            if wait_for_mesh(api, prop_id, 0, args.poll, args.timeout):
                st["done"].append(0)
                log("  variant 0 landed")
            else:
                log("  variant 0 failed — retrying once")
                api.call("POST", f"/world/props/{prop_id}/generate", gen_body_base)
                if wait_for_mesh(api, prop_id, 0, args.poll, args.timeout):
                    st["done"].append(0)
                    log("  variant 0 landed on retry")
                else:
                    st["failed"].append(0)
                    log("  variant 0 failed twice — moving on")
            save_state()

        # Further variants: append a slot, set its subject, generate into it.
        existing = variants(api, prop_id)
        for i, subject in enumerate(subjects):
            if stop_requested(job):
                log("stop file found — leaving before the next variant")
                return 0
            cur = next((v for v in existing if int(v.get("index", -1)) == i), None)
            if cur and cur.get("has_model"):
                if i not in st["done"]:
                    st["done"].append(i)
                continue
            if i in st["failed"]:
                continue
            if cur is None:
                if i == 0:
                    continue  # variant 0 handled above
                res = api.call("POST", f"/world/props/{prop_id}/variants",
                               {"from": 0})
                idx = int(res["index"])
                if idx != i:
                    log(f"  variant slot landed at {idx}, expected {i} — using {idx}")
                    i = idx
            # The batch save is the ONE way into a variant's fields since the
            # per-field routes were deleted (2026-09-21): the body maps the
            # STORE INDEX (a JSON object key, hence the str) to the patch, and
            # nothing is written unless the whole body checks out.
            api.call("POST", f"/world/props/{prop_id}/bulk",
                     {"variants": {str(i): {"description": subject}}})
            body = dict(gen_body_base)
            if entry.get("reference"):
                body.update({"front_reference": True, "reference_variant": 0})
            ok = False
            for attempt in (1, 2):
                res = api.call("POST", f"/world/props/{prop_id}/generate", body)
                if res.get("status") == "already_running":
                    log(f"  variant {i}: something still running, waiting")
                    time.sleep(args.poll)
                log(f"  variant {i}: generating (attempt {attempt})")
                if wait_for_mesh(api, prop_id, i, args.poll, args.timeout):
                    ok = True
                    break
            if ok:
                st["done"].append(i)
                log(f"  variant {i} landed")
            else:
                st["failed"].append(i)
                log(f"  variant {i} failed twice — moving on")
            save_state()
            existing = variants(api, prop_id)

    log("batch finished")
    for name, st in state.items():
        log(f"  {name}: done {sorted(st['done'])} failed {sorted(st['failed'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
