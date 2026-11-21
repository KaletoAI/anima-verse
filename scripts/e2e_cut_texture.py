#!/usr/bin/env python3
"""END-TO-END proof of the texture from cut inside the character's Build (user test 2026-11-21: "Shirt is fully draped
and the textures are not generated").

Usage:
    ./.venv/bin/python scripts/e2e_cut_texture.py --world <world dir> --character <name> \
        [--item <item id>] [--instance <instance dir>] [--shared-items <shared/items dir>] [--dry-run] \
        [--no-redrape] [--fresh-back-view] [--chain MiniMax-H3-Image,P-H3-Image] [--reject-attempt 1] \
        [--workdir <dir>] [--out <dir>] [--keep]

    # the stage before the live run: real Blender, the hub stubbed (no image job leaves the process)
    ./.venv/bin/python scripts/e2e_cut_texture.py --world worlds/demo --character demo --dry-run

What it does, in ONE process, never touching the world it is given:

1. COPIES what one character's Build reads into a temp STORAGE_DIR (``--workdir``, default the system temp dir):
   ``world.db`` (+ its ``-wal``; a ``cp``, never a symlink, never opened in place), the world's ``config.json``, the
   character's directory (its ``images/`` too: the base body's views live there), and ``items/``, ``footwear/``,
   ``jewellery/``.
   ``--shared-items`` (the checkout the world RUNS with — its items may differ from this one's) is copied into a
   private shared directory (everything else of ``shared/`` is read through symlinks). The copy is deleted at the end unless ``--keep``.
2. Loads the REAL instance (``--instance``, default ``<repo>/instance``) read-only through ``config.load`` — every
   config writer is replaced by a recorder first, so nothing is written there (a recorded write is reported and
   fails the run). Nothing of the instance is printed or copied.
3. Prepares the scenario ON THE COPY: the piece (``--item``, else the worn template top whose ``texture`` is "cut";
   a worn top with "projection" is switched to "cut" in the copy's DB) loses every texture-from-cut record and its
   cut-only run (``templates/cut/<item>_*``), and — unless ``--no-redrape`` — its drapes, so the Build has to cut,
   texture AND drape it (the two run side by side); ``--fresh-back-view`` also drops its back piece-only view (+1
   image job).
4. Plans (``figure_build.plan``) and refuses to go on when any step other than the piece's drape, its cut texture,
   the views / fits / assembly / collision would spend a hub job (the run must spend image jobs on the cut texture
   only). The announced count is the cut_texture step's ``jobs``.
5. Clicks Build ONCE (``figure_build.start``, a manual Build) and waits until the character is quiet.
6. Asserts:
   - no other click: ``garment_cut_texture.start`` / ``start_recompose`` and ``garment_template_views.start`` were
     never called, ``figure_build.start`` exactly once (follow-ups the Build keeps itself are allowed);
   - the image jobs submitted equal the announced count (live: every ``submit_gpu_task`` onto the backends allowed
     — ``P-H3-Image`` and the local upscalers; any other backend is REFUSED before it is queued; dry: every stubbed
     render / upscale / view call);
   - the Build's state is not running and has no failed step; its plan afterwards is empty (the local collision
     channel aside) — no second Build;
   - the atlas exists (``garment_cut_texture.atlas_path`` of the current csig) and the dialog reads it as done
     (``dialog_state``: ``current`` and ``applied`` True), the Figure row's ``cut_build`` is "done";
   - the SERVED GLB is the assembly (``garment_assembly.served`` of the bare model) and carries the atlas: one of its images decodes to the atlas's pixels (mean absolute
     difference < 2 at the GLB image's size);
   - zero LLM calls; network: only the hub's host (its availability probes; a dry run sends no job);
   - when the drape ran too: the cut texture's first image job started before the drape step ended (side by side).
7. Copies the record, the answers and the atlas to ``--out`` (default ``~/claude-out/cut-e2e/<stamp>``) for a look.

``--chain a,b`` overrides the ``garment_cut_texture`` routing chain IN THE PROCESS (``routing._rules``; nothing is
written — the recorder still fails the run on a config write); every entry must be in ``ALLOWED_BACKENDS``.
``--reject-attempt N`` forces the gates of attempt N to "rejected" (the answer itself is real), so attempt N + 1 runs
on the chain's next entry (docs/edit-prompts.md §7). With it, the image jobs counted are the announced count plus one
per job that ran a second attempt, at most the plan's ``max``; each job's ``attempts`` and its routing meta are printed
and checked (attempt 2 aimed at position 2, no ``fallback_from``).

Exit 0 = every check passed. ``--dry-run`` answers each image job with its own template (the islands pre-filled with
the fabric colour) and the upscale with a refusal (Lanczos fallback, counted); it renders no piece-only view (so no
``--fresh-back-view``).
"""
import argparse
import hashlib
import io
import json
import os
import shutil
import socket
import struct
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

#: The image backends a live run may submit to: the local P-H3 / MiniMax aliases and the local upscalers (free, own
#: GPUs/CPU).
ALLOWED_BACKENDS = {"P-H3-Image", "MiniMax-H3-Image", "Iris-3B-Upscale", "Real-ESRGAN-CPU"}
#: The hub's host (``openai_diffusion`` gateway of the local GPUs).
HUB_HOSTS = {"192.168.8.10"}

FAILS: List[str] = []
JOBS: List[Dict[str, Any]] = []         # every image job submitted (live) / answered (dry)
REFUSED: List[str] = []                 # backends refused by the guard
OUTBOUND: List[str] = []                # network connects refused
LLM: List[str] = []                     # LLM calls refused
CLICKS: Dict[str, int] = {"figure_build.start": 0, "garment_cut_texture.start": 0,
                          "garment_cut_texture.start_recompose": 0, "garment_template_views.start": 0}
CONFIG_WRITES: List[str] = []
STEPS: List[Dict[str, Any]] = []


def check(label: str, got: Any, want: Any) -> None:
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:400] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


# --- guards ------------------------------------------------------------------------------------------------------

#: Stack frames of a backend / provider availability probe: blocked like every other connect, but not counted as the
#: run's traffic (the instance's cloud backends are probed when the image pool or the providers start).
PROBE_FRAMES = ("check_availability", "_check_provider", "check_providers", "check_all", "health")
PROBES: List[str] = []


def install_network_guard(allowed_hosts: set) -> None:
    import traceback
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_create = socket.create_connection

    def host_of(address) -> str:
        return str(address[0]) if isinstance(address, tuple) and address else str(address)

    def refuse(what: str, address) -> None:
        names = [f.name for f in traceback.extract_stack()]
        if any(p in n for n in names for p in PROBE_FRAMES):
            PROBES.append(f"{what} {address!r}")
        else:
            OUTBOUND.append(f"{what} {address!r} via {' > '.join(names[-6:-2])}")
        raise OSError(f"e2e harness: outbound connect blocked ({address!r})")

    def connect(self, address):
        if self.family == getattr(socket, "AF_UNIX", None) or host_of(address) in allowed_hosts:
            return real_connect(self, address)
        refuse("connect", address)

    def connect_ex(self, address):
        if self.family == getattr(socket, "AF_UNIX", None) or host_of(address) in allowed_hosts:
            return real_connect_ex(self, address)
        refuse("connect_ex", address)

    def create_connection(address, *a, **k):
        if host_of(address) in allowed_hosts:
            return real_create(address, *a, **k)
        refuse("create_connection", address)
    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex
    socket.create_connection = create_connection


def install_config_write_guard() -> None:
    """Every writer of a config layer records instead of writing (the real instance is read-only here)."""
    from app.core import config
    for name in ("_write_if_changed", "_write_layer", "save", "save_part"):
        if hasattr(config, name):
            def blocked(*a, _name=name, **k):
                CONFIG_WRITES.append(_name)
                return False if _name.startswith("_write") else None
            setattr(config, name, blocked)


def install_job_guard(dry: bool) -> None:
    """Live: every GPU task is counted; a backend outside ``ALLOWED_BACKENDS`` is refused BEFORE it is queued. No
    LLM call at all (the Build of a top with parameters needs none)."""
    from app.core import llm_queue, llm_router
    real_gpu = llm_queue.LLMQueue.submit_gpu_task

    def submit_gpu_task(self, *a, **k):
        name = str(k.get("provider_name") or (a[0] if a else ""))
        if name not in ALLOWED_BACKENDS:
            REFUSED.append(name)
            raise RuntimeError(f"e2e harness: backend {name!r} is not allowed (only {sorted(ALLOWED_BACKENDS)})")
        if dry:
            REFUSED.append(f"dry:{name}")
            raise RuntimeError("e2e harness: no hub job in a dry run")
        JOBS.append({"backend": name, "task": k.get("task_type"), "label": k.get("label"), "t": time.time()})
        return real_gpu(self, *a, **k)
    llm_queue.LLMQueue.submit_gpu_task = submit_gpu_task

    def no_llm(*a, **k):
        LLM.append(str(k.get("task") or (a[0] if a else "")))
        raise RuntimeError("e2e harness: no LLM call in this run")
    llm_router.llm_call = no_llm
    llm_queue.LLMQueue.submit = lambda self, *a, **k: no_llm(*a, **k)


def install_dry_hub() -> None:
    """``--dry-run``: each image job answers with its own template (the islands pre-filled with the fabric colour), the
    upscale is refused (the flow falls back to Lanczos), a back view is the item picture."""
    from app.core import garment_cut_texture as gct
    from app.core import garment_template_views as tv
    from app.imagegen import service

    class DryBackend:
        name = "P-H3-Image (dry)"
        model = "P-H3-Image"
        extra_params = {"use_prompt_upsampler": False}

    def routed(item_id, side, prompt_for, template_png, ref_png, seed):
        prompt = prompt_for("ordinal")
        JOBS.append({"backend": "dry", "task": f"cut:{side}", "label": prompt[:60], "t": time.time()})
        return Path(template_png).read_bytes(), DryBackend(), None, "ordinal", prompt
    gct._routed_render = routed

    def upscale(self, *a, **k):
        JOBS.append({"backend": "dry", "task": "upscale", "label": "", "t": time.time()})
        raise RuntimeError("dry run: no upscale")
    service.ImageService.upscale_image = upscale

    def view(character_name, item_id, view_name, *a, **k):
        JOBS.append({"backend": "dry", "task": f"view:{view_name}", "label": "", "t": time.time()})
        raise RuntimeError("dry run: no piece-only view is rendered")
    tv.generate = view


def install_click_counters() -> None:
    from app.core import figure_build, garment_cut_texture as gct, garment_template_views as tv
    for mod, name, key in ((figure_build, "start", "figure_build.start"), (gct, "start", "garment_cut_texture.start"),
                           (gct, "start_recompose", "garment_cut_texture.start_recompose"),
                           (tv, "start", "garment_template_views.start")):
        real = getattr(mod, name)

        def wrapped(*a, _real=real, _key=key, **k):
            CLICKS[_key] += 1
            return _real(*a, **k)
        setattr(mod, name, wrapped)
    real_step = figure_build._run_step

    def run_step(character_name, step, explicit):
        entry = {"step": step.name, "item_id": step.item_id, "label": step.label, "jobs": step.jobs, "t0": time.time()}
        STEPS.append(entry)
        try:
            entry["error"] = str(real_step(character_name, step, explicit) or "")
            return entry["error"]
        finally:
            entry["t1"] = time.time()
    figure_build._run_step = run_step


# --- the copy ----------------------------------------------------------------------------------------------------

def copy_world(src: Path, dst: Path, character: str) -> None:
    if not (src / "world.db").is_file():
        raise SystemExit(f"{src} has no world.db")
    if not (src / "characters" / character).is_dir():
        raise SystemExit(f"{src} has no character {character!r}")
    dst.mkdir(parents=True)
    for name in ("world.db", "world.db-wal"):
        if (src / name).is_file():
            shutil.copyfile(src / name, dst / name)        # a plain copy; never opened in place, never symlinked
    if (src / "config.json").is_file():
        shutil.copyfile(src / "config.json", dst / "config.json")
    shutil.copytree(src / "characters" / character, dst / "characters" / character, symlinks=False)
    for name in ("items", "footwear", "jewellery"):
        if (src / name).is_dir():
            shutil.copytree(src / name, dst / name, symlinks=False)


def setup(world: Path, instance: Path, tmp: Path, dry: bool, shared_items: Path = ROOT / "shared" / "items",
          u2net_home: Path = ROOT / "models" / "u2net") -> None:
    os.environ["STORAGE_DIR"] = str(world)
    os.environ["INSTANCE_DIR"] = str(instance)
    (tmp / "clips").mkdir(exist_ok=True)
    os.environ["ANIMATION_CLIPS_DIR"] = str(tmp / "clips")
    from app.core import paths
    paths.init(world)
    paths.init_instance(instance)
    shared = tmp / "shared"
    shared.mkdir()
    for entry in (ROOT / "shared").iterdir():
        if entry.name != "items":
            (shared / entry.name).symlink_to(entry)
    if shared_items.is_dir():
        shutil.copytree(shared_items, shared / "items")
    paths.get_shared_dir = lambda: shared
    from app.models import inventory
    inventory._get_shared_dir = lambda: shared
    install_config_write_guard()
    from app.core import config
    config.load(paths.get_config_path(), instance_path=instance / "config.json")
    # the matte models (BiRefNet) of the installation — never a download
    os.environ["U2NET_HOME"] = str(u2net_home)
    from app.core import db
    db.init_schema()
    from app.plugins.loader import discover_packages
    discover_packages(ROOT / "plugins", force=True)
    install_job_guard(dry)
    if dry:
        install_dry_hub()
    from app.core.provider_manager import initialize_provider_manager
    initialize_provider_manager()
    install_click_counters()


def pick_item(character: str, wanted: str) -> str:
    from app.core import figure, garment_template as gt
    from app.models.character import get_character_profile
    from app.models.inventory import get_item
    profile = get_character_profile(character) or {}
    w, _d = figure._delivered(character, profile=profile)
    tops = [i for i in w.template if (gt.params_of(get_item(i)) or {}).get("kind") in gt.PATTERN_KINDS]
    if wanted:
        if wanted not in w.template:
            raise SystemExit(f"{wanted} is not a worn template piece of {character} ({list(w.template)})")
        return wanted
    cut = [i for i in tops if (gt.params_of(get_item(i)) or {}).get("texture") == "cut"]
    if cut or tops:
        return (cut or tops)[0]
    raise SystemExit(f"{character} wears no template top ({list(w.template)})")


def prepare(character: str, item_id: str, *, redrape: bool, fresh_back: bool) -> Dict[str, Any]:
    """The scenario on the copy (module docstring, step 3)."""
    from app.core import garment_template as gt
    from app.core import garment_template_views as tv
    from app.models.inventory import get_item
    item = get_item(item_id)
    params = gt.params_of(item) or {}
    switched = params.get("texture") != "cut"
    if switched:
        gt.set_params(item_id, {**params, "texture": "cut"},
                      source=((item or {}).get("outfit_piece") or {}).get("template", {}).get("source") or "user")
    tdir = gt.templates_dir(character)
    removed = {"cut": 0, "drape": 0, "back_view": 0}
    for path in (tdir / "cut").glob(f"{item_id}_*"):
        path.unlink()
        removed["cut"] += 1
    if redrape:
        for path in tdir.glob(f"{item_id}_*"):
            if path.is_file():
                path.unlink()
                removed["drape"] += 1
    if fresh_back:
        back = tv.accepted(character, item_id, "back")
        if back is not None:
            for path in back.parent.glob(f"{back.stem}*"):
                path.unlink()
                removed["back_view"] += 1
    from app.core import figure
    figure.invalidate()
    return {"switched_to_cut": switched, "removed": removed}


# --- checks ------------------------------------------------------------------------------------------------------

def glb_images(path: Path) -> List[bytes]:
    """The embedded images of a GLB (bufferView-backed; data URIs too)."""
    import base64
    data = path.read_bytes()
    magic, _version, _length = struct.unpack_from("<4sII", data, 0)
    if magic != b"glTF":
        raise ValueError(f"{path} is not a GLB")
    off, doc, binary = 12, None, b""
    while off < len(data):
        clen, ctype = struct.unpack_from("<II", data, off)
        chunk = data[off + 8: off + 8 + clen]
        if ctype == 0x4E4F534A:
            doc = json.loads(chunk.decode("utf-8"))
        elif ctype == 0x004E4942:
            binary = chunk
        off += 8 + clen
    out = []
    for img in (doc or {}).get("images") or []:
        if "bufferView" in img:
            bv = doc["bufferViews"][img["bufferView"]]
            start = int(bv.get("byteOffset") or 0)
            out.append(binary[start:start + int(bv["byteLength"])])
        elif str(img.get("uri") or "").startswith("data:"):
            out.append(base64.b64decode(img["uri"].split(",", 1)[1]))
    return out


def atlas_in_glb(glb: Path, atlas: Path) -> Dict[str, Any]:
    import numpy as np
    from PIL import Image
    want_sha = hashlib.sha256(atlas.read_bytes()).hexdigest()
    with Image.open(atlas) as a:
        ref = a.convert("RGB")
    best = None
    for blob in glb_images(glb):
        if hashlib.sha256(blob).hexdigest() == want_sha:
            return {"match": True, "how": "bytes", "mad": 0.0}
        try:
            with Image.open(io.BytesIO(blob)) as im:
                got = np.asarray(im.convert("RGB"), np.float64)
        except Exception:  # noqa: BLE001 — not a picture we can read
            continue
        want = np.asarray(ref.resize((got.shape[1], got.shape[0]), Image.LANCZOS), np.float64)
        mad = float(np.abs(got - want).mean())
        best = mad if best is None else min(best, mad)
    return {"match": best is not None and best < 2.0, "how": "pixels", "mad": best}


def wait_quiet(character: str, timeout: float = 4 * 3600.0, settle: float = 4.0) -> None:
    from app.core import figure_build, garment_assembly, model3d
    deadline = time.time() + timeout
    quiet_since = None
    while True:
        busy = figure_build.running(character) or model3d.generation_running(character)
        if not busy:
            garment_assembly.wait_idle(timeout=900.0)
            quiet_since = quiet_since or time.time()
            if time.time() - quiet_since >= settle:
                return
        else:
            quiet_since = None
        if time.time() > deadline:
            raise RuntimeError(f"{character} still busy after {timeout} s")
        time.sleep(1.0)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--world", required=True, type=Path, help="the world directory (only READ: it is copied)")
    ap.add_argument("--character", required=True)
    ap.add_argument("--item", default="")
    ap.add_argument("--instance", type=Path, default=ROOT / "instance")
    ap.add_argument("--shared-items", type=Path, default=ROOT / "shared" / "items",
                    help="the shared items the world runs with (copied; default this checkout's)")
    ap.add_argument("--u2net-home", type=Path, default=ROOT / "models" / "u2net",
                    help="the rembg / BiRefNet models of the installation (read, never downloaded)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-redrape", action="store_true")
    ap.add_argument("--fresh-back-view", action="store_true")
    ap.add_argument("--chain", default="", help="comma list: the garment_cut_texture chain, in-process only")
    ap.add_argument("--reject-attempt", type=int, default=0, help="force the gates of this attempt to 'rejected'")
    ap.add_argument("--workdir", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()
    if args.dry_run and args.fresh_back_view:
        raise SystemExit("--fresh-back-view needs a live run (a dry run renders no view)")
    if not (args.instance / "config.json").is_file():
        raise SystemExit(f"{args.instance} holds no config.json — pass the installation's --instance")
    install_network_guard(HUB_HOSTS)   # the backends' availability probes go there too; no JOB is sent in a dry run
    stamp = time.strftime("%Y%m%d-%H%M%S")
    tmp = Path(tempfile.mkdtemp(prefix="e2e-cut-", dir=str(args.workdir) if args.workdir else None))
    out_dir = args.out or Path.home() / "claude-out" / "cut-e2e" / stamp
    world = tmp / "world"
    try:
        print(f"copying {args.character} into {world}")
        copy_world(args.world.resolve(), world, args.character)
        setup(world, args.instance.resolve(), tmp, args.dry_run, args.shared_items.resolve(),
              args.u2net_home.resolve())
        from app.core import figure_build, garment_cut_texture as gct, paths
        check("storage is the copy", Path(paths.get_storage_dir()).resolve(), world.resolve())
        chain = [c.strip() for c in args.chain.split(",") if c.strip()]
        if chain:
            bad = [c for c in chain if c not in ALLOWED_BACKENDS]
            if bad:
                raise SystemExit(f"--chain: {bad} not allowed (only {sorted(ALLOWED_BACKENDS)})")
            from app.imagegen import routing as _routing
            real_rules = _routing._rules
            _routing._rules = lambda occasion: list(chain) if occasion == gct.CUT_USE_CASE else real_rules(occasion)
            print(f"chain {gct.CUT_USE_CASE}: {chain} (in-process)")
        if args.reject_attempt:
            from app.imagegen import routing as _routing
            real_post = gct.post_job

            def post_job(*a, **k):
                res = real_post(*a, **k)
                if _routing.current_attempt() == args.reject_attempt and not k.get("force") \
                        and res.get("state") == "ready":
                    res = {**res, "state": "rejected", "reason": f"e2e: attempt {args.reject_attempt} rejected"}
                return res
            gct.post_job = post_job
        if OUTBOUND:
            print(f"setup: {len(OUTBOUND)} connect(s) blocked while starting — not counted: {OUTBOUND[:3]}")
            OUTBOUND.clear()
        item_id = pick_item(args.character, args.item)
        prep = prepare(args.character, item_id, redrape=not args.no_redrape, fresh_back=args.fresh_back_view)
        print(f"piece {item_id}: {prep}")

        steps = figure_build.plan(args.character)
        cost = figure_build.cost(args.character, steps)
        print("plan:")
        for s in steps:
            print(f"  {s.name:12s} {s.item_id or '':28s} jobs={s.jobs} {s.label}")
        print(f"cost: {cost['note']}")
        cut_steps = [s for s in steps if s.name == "cut_texture" and s.item_id == item_id]
        check("the plan has the piece's cut_texture step", len(cut_steps), 1)
        others = [s for s in steps if s.jobs and not (s.name == "cut_texture" and s.item_id == item_id)]
        if others or not cut_steps:
            print("refused: other steps would spend hub jobs: " + "; ".join(s.label for s in others))
            return 2
        announced = int(cut_steps[0].jobs or 0)

        started = figure_build.start(args.character, reason="e2e-cut-texture")
        print(f"Build: {started}")
        wait_quiet(args.character)

        state = figure_build.state(args.character)
        check("Build not running", state["running"], False)
        check("Build failed steps", state["failed"], {})
        after = figure_build.plan(args.character)
        check("plan afterwards has no cut_texture step", [s.label for s in after if s.name == "cut_texture"], [])
        # live run 2026-11-21 (Kai): the Build ended with the drape due again ("cut anew") and the assembly due — a
        # second Build would have been needed. Nothing but the local collision channel may be left.
        check("plan afterwards is empty (no second Build)", [s.label for s in after if s.name != "collision"], [])
        rec0 = (gct.dialog_state(args.character, item_id).get("record") or {})
        second = sum(1 for e in (rec0.get("jobs") or {}).values() if len(e.get("attempts") or []) > 1)
        for j, e in (rec0.get("jobs") or {}).items():
            for a in e.get("attempts") or []:
                print(f"  {j} attempt {a.get('attempt')}: {a.get('backend')} {a.get('dialect')} {a.get('state')} "
                      f"{a.get('reason') or ''} routing={a.get('routing')}")
        if args.reject_attempt:
            tries = [a for e in (rec0.get("jobs") or {}).values() for a in (e.get("attempts") or [])
                     if a.get("attempt") == args.reject_attempt + 1]
            check("every job ran the next attempt", bool(tries) and second == len(
                [e for e in (rec0.get("jobs") or {}).values() if e.get("attempts")]), True)
            if not args.dry_run:      # the dry render is stubbed: it carries no routing meta
                check("the next attempt aimed at the next chain entry",
                      [((a.get("routing") or {}).get("attempt_entry") or {}).get("aimed_position") for a in tries],
                      [args.reject_attempt + 1] * len(tries))
            check("no fallback_from", [a for a in tries if "fallback_from" in (a.get("routing") or {})], [])
        check("image jobs as announced (+ one per second attempt)", len(JOBS), announced + second)
        check("clicks", CLICKS, {"figure_build.start": 1, "garment_cut_texture.start": 0,
                                 "garment_cut_texture.start_recompose": 0, "garment_template_views.start": 0})
        check("backends refused", REFUSED, [])
        check("LLM calls", LLM, [])
        check("network outside the hub", OUTBOUND, [])
        check("config writes", CONFIG_WRITES, [])
        dialog = gct.dialog_state(args.character, item_id)
        rec = dialog.get("record") or {}
        print(f"record: state={rec.get('state')} reason={rec.get('reason')!r} "
              f"jobs={ {j: (e.get('state'), e.get('reason')) for j, e in (rec.get('jobs') or {}).items()} }")
        check("dialog: current", dialog.get("current"), True)
        check("dialog: applied", dialog.get("applied"), True)
        from app.models.inventory import get_item
        row = figure_build._cut_build_row(args.character, item_id, get_item(item_id))
        check("figure row: cut_build done", (row or {}).get("state"), "done")
        sig = dialog.get("csig")
        atlas = gct.atlas_path(args.character, item_id, sig) if sig else None
        check("atlas exists", bool(atlas and atlas.is_file()), True)
        from app.core import garment_assembly, model3d
        bare, _match = model3d.find_model3d_serving(args.character)[:2]
        served = garment_assembly.served(args.character, bare, garment_assembly.FULL)
        print(f"served model: {served} (bare {bare})")
        check("the served model is the assembly", bool(served and bare and Path(served) != Path(bare)), True)
        if atlas and atlas.is_file() and served:
            found = atlas_in_glb(Path(served), atlas)
            print(f"atlas in the served GLB: {found}")
            check("the served GLB carries the atlas", found["match"], True)
        else:
            check("a served model", bool(served), True)
        drape = next((s for s in STEPS if s["step"] == "template" and s["item_id"] == item_id), None)
        if drape is not None and JOBS:
            check("the first image job started before the drape ended", JOBS[0]["t"] < drape["t1"], True)
        out_dir.mkdir(parents=True, exist_ok=True)
        if sig:
            for path in gct.cut_dir(args.character).glob(f"{item_id}_{sig}*"):
                shutil.copyfile(path, out_dir / path.name)
        (out_dir / "e2e.json").write_text(json.dumps({"plan": [s.as_dict() for s in steps], "cost": cost,
                                                     "jobs": JOBS, "steps": STEPS, "state": state,
                                                     "prepare": prep, "fails": FAILS}, indent=1, default=str))
        print(f"availability probes blocked (not counted): {len(PROBES)}")
        print(f"files: {out_dir}")
    finally:
        if not args.keep:
            shutil.rmtree(tmp, ignore_errors=True)
        else:
            print(f"kept: {tmp}")
    print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
