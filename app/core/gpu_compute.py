"""Local compute jobs on the GPU, with a CPU fallback — the ONE place every Taichi job of the server goes through.

Rule of the code base (2026-11-18): a local compute job (a drape, a solver, a field kernel) is written once as Taichi
kernels and runs through this module — on the GPU when this process can use one, on Taichi's CPU backend otherwise.
The first user is the XPBD drape (``app/core/drape.py``).

What it owns
------------
- **Device resolution** (``device()``): ``server.gpu_compute_device`` = ``auto`` (default) takes a real GPU through
  Vulkan when one is usable, else the CPU; ``cpu`` forces the CPU. "Real" is enforced, never assumed: before Taichi
  starts, the Vulkan loader is restricted to the HARDWARE drivers installed (``hardware_icds``: every ICD manifest
  of the loader's search path except the software ones — lavapipe/llvmpipe, SwiftShader, gfxstream — through
  ``VK_DRIVER_FILES`` / ``VK_ICD_FILENAMES``). Without that, a process that may not open the GPU (no ``render``
  group) gets llvmpipe — software Vulkan on the CPU — and Taichi still reports ``Arch.vulkan`` (measured
  2026-11-18). With it, Vulkan finds no device, Taichi falls back to its CPU arch, and this module logs ONE line
  with the reason (``render_access``: e.g. "no access to /dev/dri/renderD128 — the server process lacks the
  'render' group"). The device name is read from Taichi's own init log and checked again against the software
  names. Verified on this machine only with the Radeon 8060S (RADV); an NVIDIA or Intel driver is picked up the
  same way because nothing here names a vendor.
- **Taichi start** (``session``): the one ``ti.init`` — f32, ``fast_math`` off, the offline kernel cache in
  ``<instance>/.taichi-cache`` (else the user's cache folder, never the shared temp folder) with one sub-folder per
  arch (a CPU and a Vulkan cache never collide), the version check off (no network), ``cpu_max_num_threads`` = the job's CPU budget (``fit_kernels.threads()`` unless given). Taichi's arch
  is per process; a refit worker (its own spawn process) resolves at its first job. The runtime is restarted
  (``ti.reset`` + ``ti.init``, ~0.1 s plus the warm kernel compile, 0.2-0.4 s) only when a job needs another arch
  (``cpu=True`` below) or, on the CPU arch, another thread count.
- **How many jobs use the GPU at once** across every process of the installation (the server and its refit
  workers): ``server.gpu_compute_parallel`` slots (``process_slots``, folder ``<instance>/.gpu-compute-slots``,
  pinned into spawn workers by ``refit_pool``). A job that finds no free slot WAITS for one — it never falls back
  to the CPU on its own: a result differs between the devices in its last bits and the GPU is 2-10x faster, so a
  wait of one running drape (2-4 s) beats a CPU run (7-25 s). The wait shows in the live progress line
  ("Waiting for the GPU", ``cpu_progress``) and in the log. Jobs on the CPU arch take no slot.

How a job adopts it (the reuse shape)
-------------------------------------
::

    from app.core import gpu_compute

    def _build(ti):                       # build (and warm up) the kernels for the runtime given; cached per runtime
        @ti.kernel
        def step(x: ti.types.ndarray(dtype=ti.math.vec3, ndim=1)): ...
        return {"step": step}

    with gpu_compute.session("myjob", _build, label="my job") as s:   # resolve, start Taichi, take a GPU slot
        k = s.kernels
        ... ndarrays on s.ti, launches, s.ti.sync() before reading results ...
    record["device"] = s.device                                         # {"arch", "name"} into the result record

A job whose launch pattern defeats the GPU passes ``cpu=True`` (see the rules); everything else is identical.

Rules for a job author
----------------------
1. **f32 only.** The kernels must run unchanged on Vulkan: ``default_fp`` is f32, no f64 fields, no CPU-only
   features (Python-scope recursion, ``ti.static`` over huge ranges).
2. **Results carry the device.** Vulkan is run-to-run deterministic but not bit-equal to the CPU arch (the drape:
   p99 0.03-2.8 mm, single vertices up to 31 mm at chaotic contacts). Store ``s.device`` in the result record, and
   keep the device OUT of every version / staleness rule: a stored result is not stale because the current device
   differs from the recorded one (no refit flapping while the GPU is briefly unavailable). Bump the job's own
   result version once when it moves onto this module.
3. **Few launches per step.** Every kernel launch costs ~40-55 us on Vulkan (a barrier between dependent launches)
   against 25-45 us on the CPU arch, independent of its size. A job made of many tiny dependent launches loses on
   the GPU: the drape of an unwelded jacket with 3191 graph colours (3197 launches per substep) took 526-604 s on
   Vulkan against 428-467 s on the CPU arch, while the welded one (48 colours) took 6.6 s against 16-21 s. A job
   that can tell (the drape counts its colours: ``drape.GPU_MAX_COLOURS``) passes ``cpu=True`` for such an input:
   the decision depends on the input only, so the same input runs on the same arch on every machine.
4. **Sync before you time or read.** Launches are asynchronous on the GPU: ``s.ti.sync()`` before a timer stops,
   and keep per-step read-backs rare (each costs a sync, 77-280 us on Vulkan).
5. **One Taichi user per process at a time**: ``session`` holds a process-wide lock for its block (a restart of
   the runtime must never pull the arrays from under another thread).
"""
from __future__ import annotations

import contextlib
import grp
import json
import os
import pwd
import re
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

from app.core import process_slots
from app.core.log import get_logger

logger = get_logger(__name__)

SETTING_DEVICE = "server.gpu_compute_device"
SETTING_PARALLEL = "server.gpu_compute_parallel"
#: ``server.gpu_compute_device`` values.
AUTO, CPU = "auto", "cpu"
#: The GPU slots across every process (``process_slots``): folder under the instance, the setting, its fallback
#: (= the schema default). Why 4 (measured 2026-11-18, Radeon 8060S iGPU, 1-8 processes, docs/gpu-compute.md): the
#: largest count at which no single drape is slower than the same drape alone on the CPU arch, for BOTH kinds measured.
#: - HairDeck (Rosi, launch-bound, 24 % GPU busy alone): the throughput rises up to 6 at once (8 -> 47 drapes/min, one
#:   drape 6.8 s) and is flat at 8 (one drape 8.9 s > 8.3 s on the CPU). The GPU never reached 100 % (88 %): each
#:   process drives its launches from one CPU core.
#: - HAAR (Glut, compute-bound, 76 % alone): the throughput is flat from 2 on (26 -> 30-33/min) as the GPU nears
#:   100 %, and one drape grows with the count: 7.2 s at 4, 10.6 s at 6 (> 7.7 s on the CPU).
#: 4 keeps both below their CPU time; 6 would be the HairDeck-only answer (+50 % HairDeck throughput).
SLOTS = process_slots.SlotPool(".gpu-compute-slots", SETTING_PARALLEL, 4)
#: ICD manifests whose library is a software rasteriser (never a GPU): matched against the library file name.
SOFTWARE_ICD = re.compile(r"lvp|lavapipe|llvmpipe|swiftshader|gfxstream", re.I)
#: A Vulkan device name that is a software rasteriser (checked again after Taichi started).
SOFTWARE_DEVICE = re.compile(r"llvmpipe|lavapipe|swiftshader|software", re.I)
#: Taichi's own log line naming the Vulkan device it opened (TRACE level).
_DEVICE_LINE = re.compile(r'Vulkan Device "([^"]+)" supports')
#: A line of Taichi's C++ logger ("[T 11/18/26 23:36:43.809 2214014] ...") or of its Vulkan backend.
_TAICHI_LINE = re.compile(r"^\[[TDIWEC] \d\d/\d\d/\d\d |^RHI Error|^\[Taichi\]")
#: Stage key of the live progress line while a job waits for a GPU slot.
WAIT_STAGE = "gpu_wait"

_LOCK = threading.RLock()
#: The Taichi runtime of this process: ``ti`` module, ``arch`` ("vulkan" / "cpu"), ``threads`` (CPU arch),
#: ``generation`` (bumped by every start), ``device`` (what ``device()`` returns), ``gpu`` (the resolved GPU
#: device or None), ``gpu_reason`` (why there is none), ``kernels`` {name: (generation, kernels, t_jit_s)}.
_STATE: Dict[str, Any] = {"ti": None, "arch": None, "threads": None, "generation": 0, "device": None,
                          "gpu": None, "gpu_reason": None, "resolved": False, "kernels": {}}
#: ``server.gpu_compute_device`` pinned at spawn in a process without a config (``pin``).
_PINNED: Dict[str, Any] = {}


# --- settings ------------------------------------------------------------------------------------------------------

def device_setting() -> str:
    """``server.gpu_compute_device`` resolved: the pinned value in a spawn worker, else the config, else ``auto``."""
    if _PINNED.get("device"):
        return str(_PINNED["device"])
    try:
        from app.core import config
        value = str(config.get(SETTING_DEVICE, AUTO) or AUTO).strip().lower()
    except Exception:  # noqa: BLE001 — no config loaded (a script)
        value = AUTO
    return CPU if value == CPU else AUTO


def parallel() -> int:
    """``server.gpu_compute_parallel`` resolved live (at least 1)."""
    return SLOTS.limit()


def spawn_spec() -> Tuple[str, int, str]:
    """What ``pin`` needs in a spawned child (a refit worker has no config): ``(slot folder, limit, device)``."""
    folder, limit = SLOTS.spawn_spec()
    return folder, limit, device_setting()


def pin(spec: Optional[Tuple[str, int, str]]) -> None:
    """Fix the slot folder, the limit and the device setting for this process (``spawn_spec`` of the parent)."""
    _PINNED.clear()
    if not spec:
        SLOTS.pin(None, None)
        return
    folder, limit, device = spec
    SLOTS.pin(folder, limit)
    _PINNED["device"] = device


# --- the hardware --------------------------------------------------------------------------------------------------

def icd_dirs() -> List[Path]:
    """The Vulkan loader's ICD manifest folders, in its search order (XDG config, /etc, XDG data, /usr/share)."""
    home = Path.home()
    cfg = [os.environ.get("XDG_CONFIG_HOME") or str(home / ".config")] + \
          (os.environ.get("XDG_CONFIG_DIRS") or "/etc/xdg").split(":")
    data = [os.environ.get("XDG_DATA_HOME") or str(home / ".local/share")] + \
           (os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":")
    out: List[Path] = []
    for base in cfg + ["/etc"] + data:
        p = Path(base) / "vulkan" / "icd.d"
        if base and p not in out:
            out.append(p)
    return out


def _icd_library(path: Path) -> str:
    try:
        return str(json.loads(path.read_text(encoding="utf-8")).get("ICD", {}).get("library_path", ""))
    except (OSError, ValueError, AttributeError):
        return ""


def hardware_icds() -> Tuple[List[str], List[str]]:
    """``(hardware, software)`` ICD manifests the loader would see: a ``VK_DRIVER_FILES`` / ``VK_ICD_FILENAMES``
    already in the environment is the list, else every ``*.json`` of ``icd_dirs``. Software = the manifest's
    library (or file name) matches ``SOFTWARE_ICD``."""
    preset = os.environ.get("VK_DRIVER_FILES") or os.environ.get("VK_ICD_FILENAMES")
    if preset and not _STATE.get("pinned_icds"):
        files = [Path(p) for p in preset.split(":") if p]
    else:
        files = []
        for d in icd_dirs():
            try:
                files += sorted(d.glob("*.json"))
            except OSError:
                pass
    hw, sw = [], []
    for f in files:
        (sw if SOFTWARE_ICD.search(_icd_library(f) or f.name) or SOFTWARE_ICD.search(f.name) else hw).append(str(f))
    return hw, sw


def render_access() -> Dict[str, Any]:
    """The DRM render nodes and whether THIS process may open them -> ``{"nodes", "usable", "reason"}``; ``reason``
    ("" when one is usable) names the group the process lacks and whether the user is in it per the group database
    (a login that predates the membership: start the server through ``sg <group>``)."""
    nodes = sorted(str(p) for p in Path("/dev/dri").glob("renderD*")) if Path("/dev/dri").is_dir() else []
    usable = [n for n in nodes if os.access(n, os.R_OK | os.W_OK)]
    if usable:
        return {"nodes": nodes, "usable": usable, "reason": ""}
    if not nodes:
        return {"nodes": [], "usable": [], "reason": "no GPU render node (/dev/dri/renderD*) visible to this process "
                                                    "(a container needs the device passed in)"}
    node = nodes[0]
    try:
        group = grp.getgrgid(os.stat(node).st_gid)
        user = pwd.getpwuid(os.getuid())
        member = user.pw_name in group.gr_mem or user.pw_gid == group.gr_gid
    except (KeyError, OSError):
        return {"nodes": nodes, "usable": [], "reason": f"no access to {node}"}
    if member:
        why = (f"no access to {node} — the server process lacks the '{group.gr_name}' group (user "
               f"'{user.pw_name}' is a member since a later login: start the server through `sg {group.gr_name}`, "
               f"or log in again)")
    else:
        why = (f"no access to {node} — user '{user.pw_name}' is not in the '{group.gr_name}' group "
               f"(`usermod -aG {group.gr_name} {user.pw_name}`, then log in again)")
    return {"nodes": nodes, "usable": [], "reason": why}


def probe() -> Dict[str, Any]:
    """The status the admin page shows, without starting Taichi: the setting, the slot limit, the hardware ICDs,
    the render-node access and — when this process started Taichi — what it resolved."""
    hw, sw = hardware_icds()
    access = render_access()
    if device_setting() == CPU:
        expect = f"cpu — {SETTING_DEVICE} = cpu"
    elif not hw:
        expect = "cpu — no hardware Vulkan driver installed" + (f" (only {', '.join(Path(s).name for s in sw)})"
                                                                if sw else "")
    elif access["reason"]:
        expect = f"cpu — {access['reason']}"
    else:
        expect = "gpu (Vulkan)"
    return {"setting": device_setting(), "parallel": parallel(), "slot_dir": str(SLOTS.folder()),
            "hardware_icds": [Path(h).name for h in hw], "software_icds": [Path(s).name for s in sw],
            "render_nodes": access["nodes"], "render_usable": access["usable"], "expected": expect,
            "resolved_here": dict(_STATE["device"]) if _STATE["device"] else None}


def status_line() -> str:
    """One line for the settings page: what a job started now would run on, and why."""
    p = probe()
    here = p["resolved_here"]
    line = f"expected device: {p['expected']}; {p['parallel']} GPU job(s) at once"
    if here:
        line += f"; this server process resolved {here['arch']} ({here.get('name') or here.get('reason')})"
    return line


# --- the Taichi runtime --------------------------------------------------------------------------------------------

def _cache_dir(arch: str) -> str:
    """The offline kernel cache of ``arch``: ``<instance>/.taichi-cache/<arch>`` once an instance is chosen, else
    the user's cache folder (``$XDG_CACHE_HOME`` or ``~/.cache``) ``/anima-verse/taichi-cache/<arch>``. Never a fixed
    folder in the shared temp directory: another user (or installation) could own or plant kernels there."""
    from app.core import paths
    if paths.instance_initialised():
        root = paths.get_instance_dir() / ".taichi-cache"
    else:
        base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
        root = os.path.join(base, "anima-verse", "taichi-cache")
    d = os.path.join(str(root), arch)
    os.makedirs(d, mode=0o700, exist_ok=True)
    return d


def _init(ti: Any, arch: str, threads: int) -> str:
    """``ti.init`` for ``arch`` ("vulkan" / "cpu") with this module's options; Taichi's TRACE log of the start is
    captured from fd 2 and returned (the device line is only there). Other output that reached fd 2 meanwhile (a
    log line of another thread) is written back."""
    import sys
    kw = dict(default_fp=ti.f32, cpu_max_num_threads=max(1, int(threads)), offline_cache=True,
              offline_cache_file_path=_cache_dir(arch), fast_math=False)
    cap = tempfile.TemporaryFile()
    try:
        sys.stderr.flush()
    except Exception:  # noqa: BLE001
        pass
    saved = os.dup(2)
    os.dup2(cap.fileno(), 2)
    try:
        ti.init(arch=ti.vulkan if arch == "vulkan" else ti.cpu, log_level=ti.TRACE, **kw)
    finally:
        os.dup2(saved, 2)
        os.close(saved)
        ti.set_logging_level(ti.WARN)
    cap.seek(0)
    text = cap.read().decode("utf-8", errors="replace")
    cap.close()
    other = "".join(ln for ln in text.splitlines(keepends=True) if not _TAICHI_LINE.search(ln) and
                    not ln.startswith(" "))
    if other:
        try:
            os.write(2, other.encode("utf-8", errors="replace"))
        except OSError:
            pass
    return text


def _current_arch(ti: Any) -> str:
    arch = ti.lang.impl.current_cfg().arch
    return "vulkan" if arch == ti.vulkan else "cpu"


def _pin_hardware_icds(hw: List[str]) -> None:
    """Restrict the Vulkan loader to ``hw`` (set before the first ``ti.init``; the loader reads it then)."""
    joined = ":".join(hw)
    os.environ["VK_DRIVER_FILES"] = joined
    os.environ["VK_ICD_FILENAMES"] = joined
    os.environ.pop("VK_ADD_DRIVER_FILES", None)
    _STATE["pinned_icds"] = True


def _start(ti: Any, arch: str, threads: int) -> str:
    """(Re)start Taichi on ``arch`` -> the arch it really runs on (a Vulkan start without a device falls back to
    the CPU arch inside Taichi)."""
    if _STATE["ti"] is not None:
        ti.reset()
    t0 = time.monotonic()
    text = _init(ti, arch, threads)
    got = _current_arch(ti)
    _STATE.update(ti=ti, arch=got, threads=int(threads), generation=_STATE["generation"] + 1, kernels={})
    _STATE["last_init_text"] = text
    logger.debug("Taichi started on %s (%.2fs, %d CPU threads)", got, time.monotonic() - t0, threads)
    return got


def _resolve(ti: Any, threads: int) -> None:
    """The first start of this process: the GPU when ``auto`` finds a real one, else the CPU — ONE log line."""
    reason = ""
    gpu = None
    if device_setting() == CPU:
        reason = f"{SETTING_DEVICE} = cpu"
    else:
        hw, sw = hardware_icds()
        if not hw:
            reason = "no hardware Vulkan driver installed" + (f" (only software: "
                                                              f"{', '.join(Path(s).name for s in sw)})" if sw else "")
        else:
            _pin_hardware_icds(hw)
            got = _start(ti, "vulkan", threads)
            text = _STATE.pop("last_init_text", "")
            if got == "vulkan":
                names = _DEVICE_LINE.findall(text)
                name = names[-1] if names else "unknown Vulkan device"
                if SOFTWARE_DEVICE.search(name):
                    reason = f"Vulkan opened the software device {name!r} — refused"
                else:
                    gpu = {"arch": "vulkan", "name": name}
            else:
                err = next((ln.strip() for ln in text.splitlines() if "RHI Error" in ln), "")
                reason = render_access()["reason"] or ("Vulkan found no usable device" + (f" ({err})" if err else ""))
    _STATE.update(gpu=gpu, gpu_reason=reason or None, resolved=True)
    if gpu:
        _STATE["device"] = dict(gpu)
        logger.info("GPU compute: %s (Vulkan) in process %d", gpu["name"], os.getpid())
        return
    _STATE["device"] = {"arch": "cpu", "name": "cpu", "reason": reason}
    if _STATE["ti"] is None or _STATE["arch"] != "cpu":
        _start(ti, "cpu", threads)
        _STATE.pop("last_init_text", None)
    log = logger.info if device_setting() == CPU else logger.warning
    log("GPU compute: CPU in process %d — %s", os.getpid(), reason)


def _taichi() -> Any:
    os.environ.setdefault("ENABLE_TAICHI_HEADER_PRINT", "0")
    os.environ["TI_SKIP_VERSION_CHECK"] = "ON"            # ti.init would otherwise phone home
    import taichi as ti
    return ti


def _default_threads() -> int:
    from app.core import fit_kernels
    return fit_kernels.threads()


def device() -> Dict[str, Any]:
    """What this process computes on: ``{"arch": "vulkan", "name"}`` or ``{"arch": "cpu", "name": "cpu",
    "reason"}`` — starts Taichi (resolving the device) when it has not started yet."""
    with _LOCK:
        if not _STATE["resolved"]:
            _resolve(_taichi(), _default_threads())
        return dict(_STATE["device"])


def _ensure(cpu: bool, threads: int) -> None:
    """The runtime this job needs: the resolved device (or the CPU arch when ``cpu``); on the CPU arch with
    ``threads`` CPU threads."""
    ti = _taichi()
    if not _STATE["resolved"]:
        _resolve(ti, threads)
    want = "vulkan" if (_STATE["gpu"] and not cpu) else "cpu"
    if _STATE["arch"] != want or (want == "cpu" and _STATE["threads"] != threads):
        got = _start(ti, want, threads)
        _STATE.pop("last_init_text", None)
        if got != want:            # the GPU went away since the first start: the CPU from now on
            _STATE.update(gpu=None, gpu_reason="Vulkan start failed after an earlier success",
                          device={"arch": "cpu", "name": "cpu",
                                  "reason": "Vulkan start failed after an earlier success"})
            logger.warning("GPU compute: CPU in process %d — the Vulkan restart failed", os.getpid())


def kernels(name: str, build: Callable[[Any], Any]) -> Tuple[Any, float]:
    """``build(ti)`` for the current runtime, cached until the runtime restarts -> ``(kernels, t_build_s)``
    (``t_build_s`` > 0 only for the call that built them). Call inside ``session``."""
    with _LOCK:
        hit = _STATE["kernels"].get(name)
        if hit is not None and hit[0] == _STATE["generation"]:
            return hit[1], 0.0
        t0 = time.monotonic()
        built = build(_STATE["ti"])
        took = time.monotonic() - t0
        _STATE["kernels"][name] = (_STATE["generation"], built, took)
        return built, took


@dataclass
class Session:
    """One job's hold on the compute device (``session``)."""
    ti: Any
    kernels: Any
    device: Dict[str, Any]
    t_jit_s: float = 0.0
    slot_wait_s: float = 0.0


def _wait_notice(label: str) -> Callable[[bool], None]:
    def notice(waiting: bool) -> None:
        from app.core import cpu_progress
        if waiting:
            cpu_progress.sub(WAIT_STAGE, label="Waiting for the GPU")
    return notice


@contextlib.contextmanager
def session(name: str, build: Callable[[Any], Any], *, cpu: bool = False, label: str = "",
            threads: Optional[int] = None) -> Iterator[Session]:
    """Run a job's block on the compute device: resolve it (first use), (re)start Taichi as needed, build the
    job's kernels (``kernels(name, build)``), and — on the GPU — hold one of the ``parallel()`` GPU slots for the
    block, waiting visibly while all are taken. ``cpu`` runs this job on the CPU arch (rule 3 of the module
    docstring). ``threads``: the CPU arch's thread count (default ``fit_kernels.threads()``). A failure while
    building the kernels on the GPU (the first kernel compile) moves this process to the CPU for good (logged)
    and builds them there. One session per process at a time."""
    threads = int(threads or _default_threads())
    with _LOCK:
        _ensure(cpu, threads)
        try:
            built, took = kernels(name, build)
        except Exception as e:  # noqa: BLE001 — a GPU that fails its first kernel is no GPU for this process
            if _STATE["arch"] != "vulkan":
                raise
            reason = f"the first {name} kernels failed on Vulkan ({type(e).__name__}: {e})"
            logger.warning("GPU compute: CPU in process %d — %s", os.getpid(), reason)
            _STATE.update(gpu=None, gpu_reason=reason, device={"arch": "cpu", "name": "cpu", "reason": reason})
            _ensure(True, threads)
            built, took = kernels(name, build)
        dev = {"arch": _STATE["arch"], "name": (_STATE["gpu"] or {}).get("name") if _STATE["arch"] == "vulkan"
               else "cpu"}
        if _STATE["arch"] == "cpu":
            dev["threads"] = _STATE["threads"]
            reason = "the job asked for the CPU" if (cpu and _STATE["gpu"]) else _STATE["gpu_reason"]
            if reason:
                dev["reason"] = reason
        s = Session(ti=_STATE["ti"], kernels=built, device=dev, t_jit_s=took)
        if _STATE["arch"] != "vulkan":
            yield s
            return
        with process_slots.hold(SLOTS.folder(), parallel, what="GPU compute", label=label or name,
                                on_wait=_wait_notice(label or name)) as held:
            s.slot_wait_s = held["wait_s"]
            yield s
