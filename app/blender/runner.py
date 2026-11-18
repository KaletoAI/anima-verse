"""Runs one bpy script headlessly and hands its JSON result back.

Call shape::

    blender --background --factory-startup --python-exit-code 1 \\
            --python <script> -- <job>/args.json

Everything a script needs travels through a per-run JOB DIRECTORY, and nothing
else: inputs are COPIED in, outputs are written to ``out/``, the result is a
JSON file. A script therefore never sees a store path and cannot corrupt one —
the caller decides what to keep. The directory is removed when the run ends.

Two deliberate choices:

* **The result is a FILE, not stdout.** Blender writes unsolicited text to
  stdout (splash, addon chatter, exporter progress); a parser on that stream
  breaks the first time a version adds a line.
* **A script-side failure is a RETURN VALUE, not an exception.** Every caller
  here has the same fallback — keep the untouched original — so making them
  all write try/except would only invite one of them to forget. The result
  names HOW the run ended (``outcome``, ``app.blender.outcome``): a verdict
  about the input, a timeout, an interruption, Blender unavailable or a
  defect — callers decide by it, never by the ``error`` text.

Blender's own output is kept in ``logs/blender.log`` (``LOG_FILE``), one block
per run; a failed run's result carries its end as ``log_tail``.

``--factory-startup`` drops user preferences and third-party add-ons, so a
result does not depend on how the host's Blender happens to be set up. The
bundled glTF/FBX importers stay enabled (they are on in factory settings).

**How many run at once** is capped by ``server.blender_max_concurrent``
(instance scope, read at every acquire) across EVERY process of the
installation — server threads, refit pool workers, scripts: ``blender_slot``
holds one of N slot files (``<instance>/.blender-slots/slot-<i>.lock``) under
an exclusive ``flock`` while the subprocess runs. The kernel drops the lock
when the holder's descriptor closes, so a killed process frees its slot by
itself — and on Linux its Blender child is killed with it (``_die_with_parent``),
so a freed slot never hides a still-running orphan; a caller that finds every
slot taken polls until one is free. Only the Blender subprocess holds the
slot, not the input copies around it. A process outside the server (the
animation studio, the clip repair scripts) shares the server's slots, limit,
binary and switches only after ``use_instance_config`` bound it to the same
instance; without it, it runs on the shipped defaults and a private slot
folder.

**Orphaned job directories** (a host process killed mid-run never reaches
its ``rmtree``) are swept once per host process, in the background, when its
first job starts (``sweep_orphan_job_dirs``). Each job directory carries an
owner marker (``JOB_OWNER_FILE``: host pid, its start time, boot id, pid
namespace), written before Blender starts; a directory is removed only when
that owner is provably gone — several independent processes (server, refit
workers, the animation studio, clip scripts) share the temp folder.
"""
import contextlib
import contextvars
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

from app.core import process_slots
from app.core.log import get_logger

logger = get_logger(__name__)

SCRIPTS_DIR = Path(__file__).parent / "scripts"

# Blender 5.1 made transform_apply flip normals on negatively scaled objects
# (corrective_flip_normals, enabled by default); 5.0 does not. Require 5.2 so
# normalize.py produces consistent models across supported installations.
MIN_VERSION = (5, 2)
MAX_VERSION_EXCL = (6, 0)
_VERSION_RE = re.compile(r"(\d+)\.(\d+)(?:\.(\d+))?")

#: ``(path, st_mtime_ns, st_ino)`` -> version string of a completed probe.
_version_cache: Dict[Tuple[str, int, int], str] = {}
#: How long a failed or timed-out probe of one binary identity is remembered
#: before it is tried again (``status()`` runs before every job and in routes;
#: a hanging binary would otherwise cost the 30 s probe timeout every time).
NEG_TTL_S = 60.0
#: ``(path, st_mtime_ns, st_ino)`` -> ``time.monotonic()`` of the failed probe.
_version_failed: Dict[Tuple[str, int, int], float] = {}


def _config(path: str, default: Any) -> Any:
    """Config read that also works without a loaded world (scripts/tests)."""
    try:
        from app.core import config
        val = config.get(path, None)
        return default if val is None or val == "" else val
    except Exception:
        return default


def parse_version(text: str) -> Optional[Tuple[int, int, int]]:
    m = _VERSION_RE.search(text or "")
    return (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)) if m else None


def _usable(ver: Optional[Tuple[int, int, int]]) -> bool:
    return bool(ver) and MIN_VERSION <= ver[:2] < MAX_VERSION_EXCL


def _candidates() -> List[str]:
    found = []
    w = shutil.which("blender")
    if w:
        found.append(w)
    for pattern in ("/opt/blender*/blender", "/usr/local/blender*/blender",
                    str(Path.home() / "tools" / "blender*" / "blender")):
        root = Path(pattern).anchor or "/"
        for m in Path(root).glob(str(Path(pattern).relative_to(root))):
            if os.access(m, os.X_OK) and str(m) not in found:
                found.append(str(m))
    return found


def _discover() -> Tuple[str, List[Dict[str, str]]]:
    configured = str(_config("image_generation.blender_executable", "") or "").strip()
    rejected: List[Dict[str, str]] = []
    pool = [configured] if configured else _candidates()
    best, best_ver = "", None
    for exe in pool:
        ver = parse_version(version(exe))
        if not _usable(ver):
            rejected.append({"executable": exe, "version": version(exe) or "?",
                             "reason": f"needs >= {MIN_VERSION[0]}.{MIN_VERSION[1]} and < "
                                       f"{MAX_VERSION_EXCL[0]}.{MAX_VERSION_EXCL[1]}"})
            continue
        if best_ver is None or ver > best_ver:
            best, best_ver = exe, ver
    return best, rejected


def find_executable() -> str:
    """Pick the newest Blender in [5.2, 6.0) across discovery locations.

    A configured path wins but must be usable; never silently switch from it.
    """
    return _discover()[0]


def _binary_identity(exe: str) -> Optional[Tuple[str, int, int]]:
    """``(path, st_mtime_ns, st_ino)`` of the binary, None when it cannot be
    stat'ed. An upgrade in place (new file, or rewritten one) changes it."""
    try:
        st = os.stat(shutil.which(exe) or exe)
    except OSError:
        return None
    return exe, st.st_mtime_ns, st.st_ino


def version(executable: str = "") -> str:
    """Version string of the binary (e.g. "4.2.5 LTS"), "" if unusable.

    A probe that ran to completion (exit 0) is cached, keyed on the binary's
    identity, so an upgrade at the same path is probed afresh. A timeout, a
    failed start or a non-zero exit (a host under load at boot) is remembered
    for ``NEG_TTL_S`` only and then tried again, instead of rejecting Blender
    until a restart."""
    exe = executable or find_executable()
    if not exe:
        return ""
    key = _binary_identity(exe)
    if key is not None:
        if key in _version_cache:
            return _version_cache[key]
        failed_at = _version_failed.get(key)
        if failed_at is not None and time.monotonic() - failed_at < NEG_TTL_S:
            return ""
    try:
        proc = subprocess.run([exe, "--version"], capture_output=True, text=True,
                              errors="replace", timeout=30)
    except Exception as e:
        logger.debug("Blender version unreadable (%s): %s", exe, e)
        proc = None
    if proc is None or proc.returncode != 0:
        if proc is not None:
            logger.debug("Blender version probe failed (%s): exit %d", exe, proc.returncode)
        if key is not None:
            _version_failed[key] = time.monotonic()
        return ""
    first = (proc.stdout.strip().splitlines() or [""])[0]
    ver = first.replace("Blender", "").strip()
    if key is not None:
        _version_failed.pop(key, None)
        _version_cache[key] = ver
    return ver


def status() -> Dict[str, Any]:
    """What the admin UI shows: is refinement on, which binary, which version."""
    exe, rejected = _discover()
    ver = version(exe) if exe else ""
    error = "" if exe else (
        "; ".join(
            f"Blender {item['version']} at {item['executable']} is not supported "
            f"({item['reason']})" for item in rejected
        ) or "no blender executable found"
    )
    enabled = bool(_config("image_generation.blender_enabled", True))
    return {
        "enabled": enabled,
        "executable": exe,
        "version": ver,
        "configured": bool(str(_config("image_generation.blender_executable", "")).strip()),
        "usable": bool(enabled and exe and ver),
        "rejected": rejected,
        "error": error,
    }


def is_available() -> bool:
    return status()["usable"]


# --- the cross-process limit ---------------------------------------------------

#: Name of the slot folder under the instance directory.
SLOT_DIR_NAME = ".blender-slots"
#: The slots (``app.core.process_slots``): ``server.blender_max_concurrent`` across every process.
# the limit read goes through ``_config`` looked up at call time (a test may replace it)
_SLOTS = process_slots.SlotPool(SLOT_DIR_NAME, "server.blender_max_concurrent", 2,
                                read=lambda path, default: _config(path, default))

#: ``callback(waiting: bool)`` of the caller's context: True when this run has
#: to wait for a slot, False once it got one after waiting (``wait_notice``).
_wait_listener: contextvars.ContextVar[Optional[Callable[[bool], None]]] = \
    contextvars.ContextVar("blender_wait_listener", default=None)


def max_concurrent() -> int:
    """``server.blender_max_concurrent`` resolved live (at least 1); the value
    pinned at spawn in a process without a config, else the schema default."""
    return _SLOTS.limit()


def slot_dir() -> Path:
    """The folder of the slot files: pinned at spawn, else
    ``<instance>/.blender-slots``, else (a script without an instance) one
    per user in the system temp folder."""
    return _SLOTS.folder()


def use_instance_config(default_dir: Path) -> Optional[Path]:
    """Bind a process that runs Blender OUTSIDE the server (the animation
    studio, the clip repair/backfill scripts) to the installation's instance,
    so ``server.blender_max_concurrent`` with its slot folder
    (``<instance>/.blender-slots``), ``blender_executable`` and
    ``blender_enabled`` are the server's values — one limit across all
    processes, one binary, one switch.

    The directory: one already initialised in this process wins (nothing is
    reloaded); else ``INSTANCE_DIR`` (what ``start.sh --instance`` sets); else
    ``default_dir``, which the TOOL names (app code names no instance). A
    directory that does not exist is not created: the process then stays
    unbound (shipped defaults, private slot folder), logged.

    The config is loaded like the server loads it (``config.load``, both
    layers); the world layer is the initialised world's (the studio's
    throwaway one), else an empty one. No world DB is opened and no world is
    needed. Returns the instance directory, or None when unbound."""
    from app.core import config, paths
    if paths.instance_initialised():
        return paths.get_instance_dir()
    target = Path(os.environ.get("INSTANCE_DIR", "").strip() or default_dir).resolve()
    if not target.is_dir():
        logger.warning("Blender: instance %s not found — running on the shipped defaults "
                       "with a private slot folder, outside the server's limit", target)
        return None
    paths.init_instance(target)
    try:
        world_config = paths.get_config_path()
    except paths.StorageNotInitialised:
        world_config = None
    if world_config is not None:
        config.load(world_config, paths.get_instance_config_path())
    else:
        with tempfile.TemporaryDirectory(prefix="anima-no-world-") as empty:
            config.load(Path(empty) / "config.json", paths.get_instance_config_path())
    return target


def pin_slots(directory: Optional[str], limit: Optional[int]) -> None:
    """Fix folder and limit for this process (a spawned worker without config
    or instance gets the server's values at spawn; they stay until it ends)."""
    _SLOTS.pin(directory, limit)


def spawn_slots() -> Tuple[str, int]:
    """What ``pin_slots`` needs in a child process: ``(folder, limit)`` now."""
    return str(slot_dir()), max_concurrent()


@contextlib.contextmanager
def wait_notice(callback: Callable[[bool], None]) -> Iterator[None]:
    """Run the block with ``callback(True)`` / ``callback(False)`` called when
    a Blender run in it starts / stops waiting for a slot (this thread/context
    only). A failing callback is logged and ignored."""
    token = _wait_listener.set(callback)
    try:
        yield
    finally:
        _wait_listener.reset(token)


def _notify(waiting: bool) -> None:
    cb = _wait_listener.get()
    if cb is not None:
        cb(waiting)


@contextlib.contextmanager
def blender_slot(label: str = "") -> Iterator[None]:
    """Hold one of the ``max_concurrent()`` slots for the block — waiting,
    polled every ``process_slots.SLOT_POLL_S``, while all are taken. The limit
    is re-read on every try, so a changed setting applies to callers that
    already wait. A slot folder that cannot be created runs the block
    unlimited (logged)."""
    with process_slots.hold(slot_dir(), max_concurrent, what="Blender", label=label, on_wait=_notify):
        yield


def _text(data: Any) -> str:
    """A captured stream as text (str, bytes or None)."""
    if isinstance(data, bytes):
        data = data.decode("utf-8", errors="replace")
    return data or ""


# --- the Blender log ------------------------------------------------------------

#: ``logs/blender.log`` of the installation — the directory the server logs to, derived from this package's
#: location (like ``SCRIPTS_DIR``), so a process started elsewhere (the animation studio runs from
#: ``animation-studio/``) writes the same file. ``start.sh`` archives it at every server start.
LOG_FILE = Path(__file__).resolve().parents[2] / "logs" / "blender.log"
#: Blender output kept in the log for a run that did not end ok: the last 64 KB. A traceback with the operator
#: output before it is a few KB, so this is every script's whole output in practice, while a script that prints
#: per frame cannot grow the file by more than this per failed run.
LOG_FAILED_BYTES = 64 * 1024
#: ... for a run that ended ok: the last 2 KB (the closing lines) — ok runs are the bulk and their output is
#: rarely read.
LOG_OK_BYTES = 2 * 1024
#: ``run()``'s ``log_tail`` of a run that did not end ok: the last 40 lines, at most 4 KB.
TAIL_LINES = 40
TAIL_BYTES = 4 * 1024

_log_warned = False


def _last_bytes(text: str, limit: int) -> str:
    raw = text.encode("utf-8", errors="replace")
    if len(raw) <= limit:
        return text
    return "[… cut]\n" + raw[-limit:].decode("utf-8", errors="replace")


def _output(stdout: Any, stderr: Any) -> str:
    """Blender's stdout then its stderr (the traceback last, where a tail looks)."""
    out, err = _text(stdout), _text(stderr)
    if out and err and not out.endswith("\n"):
        out += "\n"
    return out + err


def log_tail(output: str) -> str:
    """The last ``TAIL_LINES`` lines of ``output``, at most ``TAIL_BYTES``."""
    lines = output.rstrip("\n").splitlines()[-TAIL_LINES:]
    raw = "\n".join(lines).encode("utf-8", errors="replace")[-TAIL_BYTES:]
    return raw.decode("utf-8", errors="ignore")


def _write_log(script: str, outcome_: str, seconds: float, job: Path, exit_code: Optional[int],
               output: str) -> None:
    """Append ONE block for this run to ``LOG_FILE``: a header line, then the output (``LOG_FAILED_BYTES`` /
    ``LOG_OK_BYTES`` of it). One ``os.write`` on an ``O_APPEND`` descriptor opened by path for this block: blocks
    of concurrent processes never interleave, and a rotation by rename loses none. A failure warns once and never
    fails the run."""
    global _log_warned
    from app.core.timeutils import utc_now_iso
    from app.blender import outcome as oc
    body = _last_bytes(output, LOG_OK_BYTES if outcome_ == oc.OK else LOG_FAILED_BYTES)
    head = (f"=== {utc_now_iso()} script={script} outcome={outcome_} seconds={seconds:.2f} pid={os.getpid()} "
            f"job={job.name} exit={'-' if exit_code is None else exit_code} ===\n")
    block = head + body + ("" if not body or body.endswith("\n") else "\n")
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(LOG_FILE), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, block.encode("utf-8", errors="replace"))
        finally:
            os.close(fd)
    except OSError as e:
        if not _log_warned:
            _log_warned = True
            logger.warning("Blender log %s not writable (%s) — runs go on without it", LOG_FILE, e)


#: First bytes ``_PDEATH_EXEC`` writes to stderr when it could not exec the
#: binary, followed by ``<errno>:<message>``; ``_spawn`` turns it back into the
#: ``OSError`` a direct start would have raised.
_EXEC_FAILED_MARK = "anima-blender-exec-failed:"

#: The exec wrapper Blender is started through on Linux. It runs in the child
#: (own interpreter, ``-I -S``: stdlib only, nothing from the environment),
#: asks the kernel for SIGKILL on the death of the thread that started it
#: (``prctl(PR_SET_PDEATHSIG)``), exits when that parent is already gone (the
#: race before the prctl), and then REPLACES itself with Blender (``execvp``:
#: same pid, same session, the death signal survives the exec). Fork-safe by
#: construction: nothing runs between fork and exec in the server process —
#: the reason ``preexec_fn`` (which can deadlock a threaded parent) is not used.
_PDEATH_EXEC = (
    "import os, sys\n"
    "parent, argv = int(sys.argv[1]), sys.argv[2:]\n"
    "try:\n"
    "    import ctypes\n"
    "    u = ctypes.c_ulong\n"
    "    ctypes.CDLL(None, use_errno=True).prctl(1, u(9), u(0), u(0), u(0))\n"
    "except Exception:\n"
    "    pass\n"
    "if os.getppid() != parent:\n"
    "    os._exit(1)\n"
    "try:\n"
    "    os.execvp(argv[0], argv)\n"
    "except OSError as e:\n"
    f"    sys.stderr.write('{_EXEC_FAILED_MARK}%d:%s\\n' % (e.errno or 0, e.strerror or e))\n"
    "    sys.stderr.flush()\n"
    "    os._exit(127)\n"
)


def _die_with_parent(cmd: List[str]) -> List[str]:
    """``cmd`` started through ``_PDEATH_EXEC`` so Blender is killed when this
    process dies (OOM kill, crash): without it Blender runs on in its own
    session until its timeout while the restarted server, whose flock died
    with it, starts new runs beside it. Unchanged off Linux (no prctl) or
    without a known interpreter."""
    if not sys.platform.startswith("linux") or not sys.executable:
        return cmd
    return [sys.executable, "-I", "-S", "-c", _PDEATH_EXEC, str(os.getpid()), *cmd]


def _spawn(cmd: List[str], timeout: int, env: Dict[str, str]) -> subprocess.CompletedProcess:
    """The one Blender subprocess (a seam the limit smoke stubs). Output that
    is not valid in the locale encoding (imported asset names) is replaced,
    never raised.

    The child dies with this process (``_die_with_parent``). The death signal
    follows the THREAD that forked: ``subprocess.run`` keeps that thread
    blocked until the child has ended (a timeout kills and reaps it there
    too), and the Popen never leaves this call, so it cannot fire early. It
    is not inherited by Blender's own children (none are started by the
    scripts here)."""
    proc = subprocess.run(_die_with_parent(cmd), capture_output=True, text=True, errors="replace",
                          timeout=timeout, env=env, start_new_session=True)
    if proc.returncode == 127 and (proc.stderr or "").startswith(_EXEC_FAILED_MARK):
        code, _, msg = proc.stderr[len(_EXEC_FAILED_MARK):].strip().partition(":")
        raise OSError(int(code) if code.isdigit() else 0, msg, cmd[0])
    return proc


# --- orphaned job directories ---------------------------------------------------

#: Prefix of every job directory (``tempfile.mkdtemp`` in the temp folder).
JOB_DIR_PREFIX = "av-blender-"
#: The owner marker in a job directory: ``{"pid", "start", "boot", "pidns"}``.
JOB_OWNER_FILE = "owner.json"
#: Age after which a job directory WITHOUT a marker counts as orphaned. Such a
#: directory comes from code before the marker (or from a marker write that
#: failed), so its owner cannot be checked and the age has to stand in for it.
#: The longest run any caller asks for is 1800 s (the schema maximum of
#: ``blender_timeout_s``, the studio's build), and before it the directory may
#: wait for a slot behind a batch of other runs (a clip import) — hours, not
#: days. A week is far beyond that, and waiting costs only disk: unmarked
#: directories are a finite legacy set that no current process adds to. The
#: age is taken from the newest mtime of the directory and its direct entries
#: (``progress.json`` is rewritten while a run lasts).
UNMARKED_MAX_AGE_S = 7 * 24 * 3600

_sweep_lock = threading.Lock()
_sweep_started = False


def _proc_read(path: str) -> str:
    with open(path, encoding="ascii", errors="replace") as f:
        return f.read()


def _proc_stat(pid: int) -> Tuple[str, int]:
    """``(state, starttime)`` of ``pid`` from ``/proc/<pid>/stat``; raises
    ``FileNotFoundError`` when no such process exists. The command name may
    hold spaces and parentheses, so the fields are counted after its LAST
    ``)``: state is field 3, starttime (clock ticks since boot) field 22."""
    raw = _proc_read(f"/proc/{pid}/stat")
    rest = raw[raw.rindex(")") + 2:].split()
    return rest[0], int(rest[19])


def _owner_identity() -> Optional[Dict[str, Any]]:
    """This process as an owner marker records it; None where that cannot be
    told (no ``/proc``, i.e. off Linux) — no marker is written then and the
    sweep does nothing."""
    try:
        pid = os.getpid()
        return {"pid": pid, "start": _proc_stat(pid)[1],
                "boot": _proc_read("/proc/sys/kernel/random/boot_id").strip(),
                "pidns": os.readlink("/proc/self/ns/pid")}
    except (OSError, ValueError, IndexError):
        return None


def _write_owner_marker(job: Path) -> None:
    """Mark ``job`` as this process's (written whole, then renamed in, so a
    sweeper never reads half a marker)."""
    ident = _owner_identity()
    if ident is None:
        return
    part = job / (JOB_OWNER_FILE + ".part")
    part.write_text(json.dumps(ident), encoding="utf-8")
    os.replace(part, job / JOB_OWNER_FILE)


def _read_owner_marker(job: Path) -> Optional[Dict[str, Any]]:
    """The marker of ``job``, None when it is absent, a symlink, not a regular
    file or not a well-formed marker (then the directory counts as unmarked)."""
    try:
        fd = os.open(str(job / JOB_OWNER_FILE), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return None
    try:
        with os.fdopen(fd, encoding="utf-8") as f:
            if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
                return None
            data = json.loads(f.read(4096))
    except (OSError, ValueError):
        return None
    if not (isinstance(data, dict) and type(data.get("pid")) is int and type(data.get("start")) is int
            and isinstance(data.get("boot"), str) and isinstance(data.get("pidns"), str)):
        return None
    return data


def _owner_gone(marker: Dict[str, Any], me: Dict[str, Any]) -> Optional[bool]:
    """True when the marker's owner is provably gone, False while it lives,
    None when it cannot be told (another pid namespace, ``/proc`` unreadable)
    — only True lets a directory be removed."""
    if marker["boot"] != me["boot"]:
        return True  # the machine rebooted since: every process of then is gone
    if marker["pidns"] != me["pidns"]:
        return None  # its pids mean something else here
    try:
        state, start = _proc_stat(marker["pid"])
    except FileNotFoundError:
        return True
    except (OSError, ValueError, IndexError):
        return None
    if start != marker["start"]:
        return True  # the pid now belongs to a later process
    return state in ("Z", "X")  # exited, only not reaped yet: runs no job


def _newest_mtime(job: Path) -> float:
    newest = os.lstat(job).st_mtime
    with os.scandir(job) as it:
        for entry in it:
            try:
                newest = max(newest, entry.stat(follow_symlinks=False).st_mtime)
            except OSError:
                pass
    return newest


def sweep_orphan_job_dirs(now: Optional[float] = None) -> List[str]:
    """Remove the job directories whose host process is gone; returns their
    paths. Looked at: entries ``JOB_DIR_PREFIX*`` DIRECTLY in this process's
    temp folder (where ``run`` creates them) that are real directories (a
    symlink is never followed) owned by this uid. A marked one goes only when
    ``_owner_gone`` proves its owner gone — never by age, a run may be long; an
    unmarked one only past ``UNMARKED_MAX_AGE_S``. Does nothing without
    ``/proc``. A directory that cannot be judged or removed is logged and
    skipped."""
    me = _owner_identity()
    if me is None:
        return []
    root = Path(os.path.realpath(tempfile.gettempdir()))
    uid = os.getuid()
    now = time.time() if now is None else now
    with os.scandir(root) as it:
        names = [e.name for e in it if e.name.startswith(JOB_DIR_PREFIX)]
    removed: List[str] = []
    for name in names:
        job = root / name
        try:
            st = os.lstat(job)
            if not stat.S_ISDIR(st.st_mode) or st.st_uid != uid:
                continue  # a symlink, a file, another user's
            if Path(os.path.realpath(job)).parent != root:
                continue
            marker = _read_owner_marker(job)
            if marker is not None:
                if _owner_gone(marker, me) is not True:
                    continue
            elif now - _newest_mtime(job) < UNMARKED_MAX_AGE_S:
                continue
            shutil.rmtree(job)  # fd-based on Linux: never follows a link inside
            removed.append(str(job))
        except FileNotFoundError:
            continue  # its owner, or another sweeper, removed it meanwhile
        except OSError as exc:
            logger.warning("Blender: orphaned job folder %s not removed: %s", job, exc)
    return removed


def _sweep_once_in_background() -> None:
    """Start ``sweep_orphan_job_dirs`` once per process, on a daemon thread so
    no job waits for it; a failure is logged, never raised."""
    global _sweep_started
    with _sweep_lock:
        if _sweep_started:
            return
        _sweep_started = True

    def work() -> None:
        try:
            gone = sweep_orphan_job_dirs()
            if gone:
                logger.info("Blender: removed %d orphaned job folder(s): %s", len(gone), ", ".join(gone))
        except Exception:  # noqa: BLE001 — housekeeping never fails a job
            logger.exception("Blender: sweeping orphaned job folders failed")

    try:
        threading.Thread(target=work, name="blender-job-sweep", daemon=True).start()
    except Exception:  # noqa: BLE001
        logger.exception("Blender: could not start the job folder sweep")


#: Signals that end Blender from OUTSIDE without a verdict (a stop, the OOM killer, the death signal of a dead
#: host): ``INTERRUPTED``. Any other signal (SIGSEGV, SIGABRT, SIGBUS, …) is Blender failing: ``CRASHED``.
_INTERRUPT_SIGNALS = frozenset({9, 15, 2, 1})  # SIGKILL, SIGTERM, SIGINT, SIGHUP


def _result(outcome_: str, error: str = "", *, data: Optional[Dict[str, Any]] = None,
            outputs: Optional[Dict[str, str]] = None, seconds: float = 0.0, tail: str = "",
            slot_wait_s: float = 0.0) -> Dict[str, Any]:
    from app.blender import outcome as oc
    return {"ok": outcome_ == oc.OK, "outcome": outcome_, "error": error, "data": data or {},
            "outputs": outputs or {}, "seconds": seconds, "slot_wait_s": slot_wait_s,
            "log_tail": "" if outcome_ == oc.OK else tail}


def run(script: str, *, inputs: Optional[Dict[str, Path]] = None,
        params: Optional[Dict[str, Any]] = None,
        out_dir: Optional[Path] = None,
        timeout_s: int = 0) -> Dict[str, Any]:
    """Executes ``scripts/<script>.py`` and returns its result.

    ``inputs`` maps a slot name to a local file; each is copied into the job
    directory under that slot name, and the script receives the copy's path.
    ``out_dir`` must be given when the script produces files: whatever it
    declares under ``outputs`` is MOVED there, and the returned paths point at
    the moved files. Without it a produced file would die with the job dir.

    Returns ``{"ok", "outcome", "error", "data", "outputs", "seconds",
    "slot_wait_s", "log_tail"}``. ``seconds`` is the whole call, the wait for a
    free Blender slot included; ``slot_wait_s`` is that wait alone (0 when a
    slot was free at once or the run ended before asking for one), so
    ``seconds - slot_wait_s`` is the run's own time. ``outcome`` is one of ``app.blender.outcome.ALL`` — what a
    caller decides by (``ok`` is ``outcome == OK``): ``UNAVAILABLE`` (disabled,
    not found, not startable), ``TIMEOUT``, ``INTERRUPTED`` (killed by a stop
    signal), ``REJECTED`` (the script reported failure itself) or ``CRASHED``
    (unknown script, input vanished, no or unreadable result, a declared output
    missing, a crash signal). ``log_tail`` is the end of Blender's output for
    every outcome but ``OK``. Every run that got a job folder is one block in
    ``LOG_FILE``; the three answers before it (disabled, not found, unknown
    script) start nothing and write none.
    """
    from app.blender import outcome as oc
    st = status()
    if not st["enabled"]:
        return _result(oc.UNAVAILABLE, "blender refinement is disabled")
    if not st["executable"]:
        return _result(oc.UNAVAILABLE, st["error"])

    script_path = SCRIPTS_DIR / f"{script}.py"
    if not script_path.is_file():
        return _result(oc.CRASHED, f"unknown blender script: {script}")

    timeout = int(timeout_s or _config("image_generation.blender_timeout_s", 120))
    _sweep_once_in_background()
    job = Path(tempfile.mkdtemp(prefix=JOB_DIR_PREFIX))
    started = time.time()
    ran: Dict[str, Any] = {"output": "", "exit": None, "slot_wait_s": 0.0}

    def done(outcome_: str, error: str = "", **fields: Any) -> Dict[str, Any]:
        """The run's result, its block in the Blender log and its one main.log line."""
        seconds = time.time() - started
        output = ran["output"]
        _write_log(script, outcome_, seconds, job, ran["exit"], output)
        if outcome_ == oc.OK:
            moved = fields.get("outputs") or {}
            logger.info("Blender %s: ok (%.2fs%s)", script, seconds, f", {len(moved)} file(s)" if moved else "")
        else:
            log = logger.error if outcome_ == oc.CRASHED else logger.warning
            log("Blender %s: %s — %s (output in %s)", script, outcome_, error, LOG_FILE)
        return _result(outcome_, error, seconds=seconds, tail=log_tail(output),
                       slot_wait_s=round(ran["slot_wait_s"], 2), **fields)

    try:
        try:
            _write_owner_marker(job)
        except OSError as e:
            # Unmarked, the folder is swept only past UNMARKED_MAX_AGE_S if left behind.
            logger.warning("Blender %s: job folder owner marker not written: %s", script, e)
        in_dir = job / "in"
        job_out = job / "out"
        tmp_dir = job / "tmp"
        for d in (in_dir, job_out, tmp_dir):
            d.mkdir()

        slots: Dict[str, str] = {}
        for slot, src in (inputs or {}).items():
            src = Path(src)
            if not src.is_file():
                return done(oc.CRASHED, f"input '{slot}' not found: {src}")
            dst = in_dir / f"{slot}{src.suffix.lower()}"
            try:
                shutil.copy2(src, dst)
                slots[slot] = str(dst)
                # An FBX carries its texture as a sibling file, not embedded —
                # copy a same-stem image along so the script can find it.
                for ext in (".png", ".jpg", ".jpeg"):
                    tex = src.with_suffix(ext)
                    if tex.is_file():
                        shutil.copy2(tex, dst.with_suffix(ext))
                        break
            except OSError as e:
                # The store file was replaced or purged after the check above.
                return done(oc.CRASHED, f"input '{slot}' unreadable: {e}")

        result_file = job / "result.json"
        args_file = job / "args.json"
        # A194: every run reports its stages into a progress file (``_common.progress``); a caller that already
        # chose one (the template drape's ``progress_file``) keeps it. Read by ``cpu_progress.snapshot``.
        progress_file = str((params or {}).get("progress_file") or (job / "progress.json"))
        args_file.write_text(json.dumps({
            "inputs": slots,
            "params": dict(params or {}),
            "out_dir": str(job_out),
            "result": str(result_file),
            "progress": progress_file,
        }, ensure_ascii=False), encoding="utf-8")

        cmd = [st["executable"], "--background", "--factory-startup",
               "--python-exit-code", "1", "--python", str(script_path),
               "--", str(args_file)]
        env = dict(os.environ)
        env["TMPDIR"] = str(tmp_dir)
        logger.debug("Blender: %s (timeout %ds)", script, timeout)
        try:
            # The timeout covers Blender itself, not the wait for a slot.
            from app.core import cpu_progress
            asked = time.monotonic()
            with blender_slot(script), cpu_progress.attach(f"blender:{script}", progress_file):
                ran["slot_wait_s"] = time.monotonic() - asked   # the slot is held from here on
                proc = _spawn(cmd, timeout, env)
        except subprocess.TimeoutExpired as exc:
            ran["output"] = _output(exc.stdout, exc.stderr)
            return done(oc.TIMEOUT, f"timeout after {timeout}s")
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            # The binary vanished or lost +x since discovery, or the start failed.
            return done(oc.UNAVAILABLE, f"blender could not be started: {exc}")
        ran["output"], ran["exit"] = _output(proc.stdout, proc.stderr), proc.returncode

        if not result_file.is_file():
            if proc.returncode < 0:
                signal_no = -proc.returncode
                return done(oc.INTERRUPTED if signal_no in _INTERRUPT_SIGNALS else oc.CRASHED,
                            f"blender was killed by signal {signal_no}")
            return done(oc.CRASHED, f"script wrote no result (exit {proc.returncode})")
        try:
            res = json.loads(result_file.read_text(encoding="utf-8"))
        except (ValueError, OSError) as e:
            return done(oc.CRASHED, f"result unreadable: {e}")

        if not res.get("ok"):
            return done(oc.REJECTED, str(res.get("error") or "script failed"), data=res.get("data") or {})

        moved: Dict[str, str] = {}
        declared = res.get("outputs") or {}
        if declared and not out_dir:
            return done(oc.CRASHED, "script produced files but no out_dir was given", data=res.get("data") or {})
        for slot, rel in declared.items():
            src = Path(rel)
            if not src.is_absolute():
                src = job_out / rel
            if not src.is_file():
                return done(oc.CRASHED, f"declared output '{slot}' is missing: {rel}", data=res.get("data") or {})
            dst = Path(out_dir) / src.name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            moved[slot] = str(dst)
        return done(oc.OK, data=res.get("data") or {}, outputs=moved)
    finally:
        shutil.rmtree(job, ignore_errors=True)
