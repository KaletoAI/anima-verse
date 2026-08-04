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
  all write try/except would only invite one of them to forget.

``--factory-startup`` drops user preferences and third-party add-ons, so a
result does not depend on how the host's Blender happens to be set up. The
bundled glTF/FBX importers stay enabled (they are on in factory settings).
"""
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Optional

from app.core.log import get_logger

logger = get_logger(__name__)

SCRIPTS_DIR = Path(__file__).parent / "scripts"

# Tail of the Blender log kept on failure — enough for a traceback, not enough
# to bloat a log line.
LOG_TAIL_CHARS = 4000

_version_cache: Dict[str, str] = {}


def _config(path: str, default: Any) -> Any:
    """Config read that also works without a loaded world (scripts/tests)."""
    try:
        from app.core import config
        val = config.get(path, None)
        return default if val is None or val == "" else val
    except Exception:
        return default


def find_executable() -> str:
    """Path to the Blender binary: configured value first, then discovery.

    Discovery covers the usual unpacked-tarball locations; a configured path
    always wins so a host with several installs stays predictable.
    """
    configured = str(_config("image_generation.blender_executable", "") or "").strip()
    if configured:
        return configured
    found = shutil.which("blender")
    if found:
        return found
    globs = ("/opt/blender*/blender", "/usr/local/blender*/blender",
             str(Path.home() / "tools" / "blender*" / "blender"))
    for pattern in globs:
        root = Path(pattern).anchor or "/"
        rel = str(Path(pattern).relative_to(root))
        matches = sorted(Path(root).glob(rel), reverse=True)   # newest first
        for m in matches:
            if os.access(m, os.X_OK):
                return str(m)
    return ""


def version(executable: str = "") -> str:
    """Version string of the binary (e.g. "4.2.5 LTS"), "" if unusable."""
    exe = executable or find_executable()
    if not exe:
        return ""
    if exe in _version_cache:
        return _version_cache[exe]
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True,
                             timeout=30).stdout
        first = (out.strip().splitlines() or [""])[0]
        ver = first.replace("Blender", "").strip()
    except Exception as e:
        logger.debug("Blender version unreadable (%s): %s", exe, e)
        ver = ""
    _version_cache[exe] = ver
    return ver


def status() -> Dict[str, Any]:
    """What the admin UI shows: is refinement on, which binary, which version."""
    exe = find_executable()
    ver = version(exe) if exe else ""
    enabled = bool(_config("image_generation.blender_enabled", True))
    return {
        "enabled": enabled,
        "executable": exe,
        "version": ver,
        "configured": bool(str(_config("image_generation.blender_executable", "")).strip()),
        "usable": bool(enabled and exe and ver),
    }


def is_available() -> bool:
    return status()["usable"]


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

    Returns ``{"ok", "error", "data", "outputs", "seconds"}``. ``ok`` False
    covers everything: Blender missing, disabled by config, crash, timeout,
    unreadable result, or a script reporting failure itself.
    """
    st = status()
    if not st["enabled"]:
        return {"ok": False, "error": "blender refinement is disabled",
                "data": {}, "outputs": {}, "seconds": 0.0}
    if not st["executable"]:
        return {"ok": False, "error": "no blender executable found",
                "data": {}, "outputs": {}, "seconds": 0.0}

    script_path = SCRIPTS_DIR / f"{script}.py"
    if not script_path.is_file():
        return {"ok": False, "error": f"unknown blender script: {script}",
                "data": {}, "outputs": {}, "seconds": 0.0}

    timeout = int(timeout_s or _config("image_generation.blender_timeout_s", 120))
    job = Path(tempfile.mkdtemp(prefix="av-blender-"))
    started = time.time()
    try:
        in_dir = job / "in"
        job_out = job / "out"
        tmp_dir = job / "tmp"
        for d in (in_dir, job_out, tmp_dir):
            d.mkdir()

        slots: Dict[str, str] = {}
        for slot, src in (inputs or {}).items():
            src = Path(src)
            if not src.is_file():
                return {"ok": False, "error": f"input '{slot}' not found: {src}",
                        "data": {}, "outputs": {}, "seconds": 0.0}
            dst = in_dir / f"{slot}{src.suffix.lower()}"
            shutil.copy2(src, dst)
            slots[slot] = str(dst)
            # An FBX carries its texture as a sibling file, not embedded — copy
            # a same-stem image along so the script can find it.
            for ext in (".png", ".jpg", ".jpeg"):
                tex = src.with_suffix(ext)
                if tex.is_file():
                    shutil.copy2(tex, dst.with_suffix(ext))
                    break

        result_file = job / "result.json"
        args_file = job / "args.json"
        args_file.write_text(json.dumps({
            "inputs": slots,
            "params": dict(params or {}),
            "out_dir": str(job_out),
            "result": str(result_file),
        }, ensure_ascii=False), encoding="utf-8")

        cmd = [st["executable"], "--background", "--factory-startup",
               "--python-exit-code", "1", "--python", str(script_path),
               "--", str(args_file)]
        env = dict(os.environ)
        env["TMPDIR"] = str(tmp_dir)
        logger.debug("Blender: %s (timeout %ds)", script, timeout)
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=timeout, env=env,
                                  start_new_session=True)
        except subprocess.TimeoutExpired:
            logger.error("Blender %s: timeout after %ds", script, timeout)
            return {"ok": False, "error": f"timeout after {timeout}s",
                    "data": {}, "outputs": {}, "seconds": time.time() - started}

        seconds = time.time() - started
        if not result_file.is_file():
            tail = (proc.stderr or proc.stdout or "")[-LOG_TAIL_CHARS:]
            logger.error("Blender %s: no result (exit %d)\n%s",
                         script, proc.returncode, tail)
            return {"ok": False,
                    "error": f"script wrote no result (exit {proc.returncode})",
                    "data": {}, "outputs": {}, "seconds": seconds}
        try:
            res = json.loads(result_file.read_text(encoding="utf-8"))
        except (ValueError, OSError) as e:
            return {"ok": False, "error": f"result unreadable: {e}",
                    "data": {}, "outputs": {}, "seconds": seconds}

        if not res.get("ok"):
            logger.warning("Blender %s reported failure: %s", script,
                           res.get("error") or "?")
            return {"ok": False, "error": str(res.get("error") or "script failed"),
                    "data": res.get("data") or {}, "outputs": {},
                    "seconds": seconds}

        moved: Dict[str, str] = {}
        declared = res.get("outputs") or {}
        if declared and not out_dir:
            return {"ok": False,
                    "error": "script produced files but no out_dir was given",
                    "data": res.get("data") or {}, "outputs": {},
                    "seconds": seconds}
        for slot, rel in declared.items():
            src = Path(rel)
            if not src.is_absolute():
                src = job_out / rel
            if not src.is_file():
                return {"ok": False,
                        "error": f"declared output '{slot}' is missing: {rel}",
                        "data": res.get("data") or {}, "outputs": {},
                        "seconds": seconds}
            dst = Path(out_dir) / src.name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            moved[slot] = str(dst)

        logger.info("Blender %s: ok (%.2fs%s)", script, seconds,
                    f", {len(moved)} file(s)" if moved else "")
        return {"ok": True, "error": "", "data": res.get("data") or {},
                "outputs": moved, "seconds": seconds}
    finally:
        shutil.rmtree(job, ignore_errors=True)
