"""Local runner for the GLBBodyRetexture worker.

The worker paints an outfit onto a character's base body: it takes the base
GLB plus one dressed render per view (each with its registration image) and
writes the dressed GLB, the atlas and a proof JSON. For now it runs LOCALLY as
a subprocess of this server — ``<worker_dir>/.venv/bin/python -m body_core``
with ``cwd=<worker_dir>``. A later move to the AI-Hub swaps only the transport
inside :func:`retexture`; the signature and the exceptions stay.

CPU work: never on a GPU channel, never through the image service. The caller
serialises runs per character. The instance settings (``body_retexture.*``)
are read live on every call, so a change in /admin/settings needs no restart.

A caller with a hard time limit for its whole run (the Outfit body tab's
painted-body runs, ``outfit_bodies._run_bounded``) sets it with
``run_deadline``: a worker started in that thread waits at most until the
deadline, then it is killed with everything it started (``RUN_DEADLINE``).
"""
import json
import os
import signal
import subprocess
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from app.core import config
from app.core.base_body import BASE_VIEWS
from app.core.log import get_logger

logger = get_logger("body_retexture")

DEFAULT_TIMEOUT_SECONDS = 1800
_STDERR_TAIL_LINES = 5


class RetextureUnavailable(RuntimeError):
    """The worker is not configured or not installed — nothing was run."""


class RetextureFailed(RuntimeError):
    """The worker ran and failed: exit code != 0, timeout, or no proof."""


RUN_DEADLINE = "Body retexture worker aborted: the painted-body run reached its time limit"
_scope = threading.local()


@contextmanager
def run_deadline(deadline: float) -> Iterator[None]:
    """Every worker started in this thread inside the block is killed at
    ``deadline`` (``time.monotonic()``) at the latest; one that would start
    after it fails at once (``RetextureFailed`` ``RUN_DEADLINE``)."""
    previous = getattr(_scope, "deadline", None)
    _scope.deadline = deadline
    try:
        yield
    finally:
        _scope.deadline = previous


def _run_left() -> Optional[float]:
    """Seconds left of this thread's ``run_deadline``, None without one."""
    deadline = getattr(_scope, "deadline", None)
    return None if deadline is None else deadline - time.monotonic()


def _worker_dir() -> Path:
    raw = str(config.get("body_retexture.worker_dir", "") or "").strip()
    if not raw:
        raise RetextureUnavailable("Body retexture worker not configured")
    return Path(os.path.expanduser(raw))


def _timeout_seconds() -> int:
    raw = config.get("body_retexture.timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT_SECONDS
    return value if value > 0 else DEFAULT_TIMEOUT_SECONDS


def _stderr_tail(stderr: str) -> str:
    lines = [line.strip() for line in (stderr or "").splitlines() if line.strip()]
    return "\n".join(lines[-_STDERR_TAIL_LINES:])


def _kill_group(proc: subprocess.Popen) -> None:
    """Kill the worker AND everything it started (its own process group)."""
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    try:
        proc.communicate(timeout=10)
    except Exception:  # noqa: BLE001 — reaping is best effort after SIGKILL
        pass


#: Views the worker treats as side views (arm exclusion zone).
SIDE_VIEWS = ("left", "right")


def build_argv(python: Path, glb_in: Path, views: dict, out_glb: Path,
               proof: Path, atlas: Path, *, side_arm_margin: Optional[float] = None,
               arm_rig_glb: Optional[Path] = None) -> list:
    """The worker command line: views in BASE_VIEWS order, absent ones skipped,
    every path absolute (the worker runs with its own repo as cwd). With a
    side view among ``views``: ``--side-arm-margin`` (when given) and
    ``--arm-rig-glb`` (when given) — the left/right views then skip the arm
    and that margin around it (fraction of the body height); without a
    side view neither flag is passed."""
    unknown = sorted(set(views) - set(BASE_VIEWS))
    if unknown:
        raise ValueError(f"Unknown retexture view(s): {', '.join(unknown)}")
    if "front" not in views:
        raise ValueError("The front view is required for a body retexture")
    argv = [str(python), "-m", "body_core", "--glb", os.path.abspath(glb_in)]
    for name in BASE_VIEWS:
        if name not in views:
            continue
        dressed, registration = views[name]
        argv += ["--view", f"{name}={os.path.abspath(dressed)},{os.path.abspath(registration)}"]
    argv += ["--out", os.path.abspath(out_glb),
             "--proof", os.path.abspath(proof),
             "--atlas", os.path.abspath(atlas)]
    if any(name in views for name in SIDE_VIEWS):
        if side_arm_margin is not None:
            argv += ["--side-arm-margin", repr(float(side_arm_margin))]
        if arm_rig_glb is not None:
            argv += ["--arm-rig-glb", os.path.abspath(arm_rig_glb)]
    return argv


def retexture(glb_in: Path, views: dict[str, tuple[Path, Path]], out_glb: Path,
              *, proof: Path, atlas: Path, side_arm_margin: Optional[float] = None,
              arm_rig_glb: Optional[Path] = None) -> dict:
    """Run the worker once and return its parsed proof JSON.

    ``views`` maps a view name (``front`` required; ``back``/``left``/``right``
    optional) to ``(dressed_png, registration_png)``. ``side_arm_margin`` /
    ``arm_rig_glb`` (a rigged copy of ``glb_in`` with the same UV layout)
    reach the worker only with a side view (``build_argv``).
    Raises RetextureUnavailable (not configured / not installed),
    RetextureFailed (exit != 0 with the last stderr lines as message, timeout,
    missing or unreadable proof) and ValueError (bad ``views``).
    """
    worker_dir = _worker_dir()
    python = worker_dir / ".venv" / "bin" / "python"
    if not python.is_file():
        raise RetextureUnavailable(f"Body retexture worker not installed: {python} not found")
    argv = build_argv(python, glb_in, views, out_glb, proof, atlas,
                      side_arm_margin=side_arm_margin, arm_rig_glb=arm_rig_glb)
    timeout = _timeout_seconds()
    left = _run_left()
    if left is not None and left <= 0:
        raise RetextureFailed(RUN_DEADLINE)
    wait = timeout if left is None else min(timeout, left)
    proof = Path(proof)
    # A proof left by an earlier run must never pass as this run's result.
    proof.unlink(missing_ok=True)

    logger.info("Body retexture start: %s (%s), timeout %d s",
                Path(glb_in).name, ",".join(n for n in BASE_VIEWS if n in views), timeout)
    try:
        proc = subprocess.Popen(argv, cwd=str(worker_dir), stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, start_new_session=True)
    except OSError as exc:
        raise RetextureUnavailable(f"Body retexture worker could not start: {exc}") from exc
    try:
        _stdout, stderr = proc.communicate(timeout=wait)
    except subprocess.TimeoutExpired:
        _kill_group(proc)
        if wait < timeout:
            logger.warning("Body retexture killed at the run's time limit after %d s: %s", round(wait),
                           Path(glb_in).name)
            raise RetextureFailed(RUN_DEADLINE) from None
        logger.warning("Body retexture timed out after %d s: %s", timeout, Path(glb_in).name)
        raise RetextureFailed(f"Body retexture worker timed out after {timeout} s") from None
    except BaseException:
        _kill_group(proc)
        raise

    if proc.returncode != 0:
        tail = _stderr_tail(stderr)
        logger.warning("Body retexture refused (exit %s): %s", proc.returncode, tail)
        raise RetextureFailed(tail or f"Body retexture worker exited with code {proc.returncode}")
    try:
        result = json.loads(proof.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise RetextureFailed("Body retexture worker wrote no proof file") from None
    except (OSError, ValueError) as exc:
        raise RetextureFailed(f"Body retexture proof unreadable: {exc}") from exc
    if not isinstance(result, dict):
        raise RetextureFailed("Body retexture proof is not a JSON object")
    logger.info("Body retexture done: %s", Path(out_glb).name)
    return result
