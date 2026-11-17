"""Live progress of CPU jobs (A194) — ONE mechanism for every local run of the figure pipeline.

A172 gave the template drape a live step (a registry plus a progress file the Blender run writes). This module
generalises it, so every CPU job reports the same way and every place that shows the step shows the same line:
``"Stage · i/n · 42 s"`` (plus ``"~N s left"`` when an i/n allows an estimate).

Three levels, all optional:

- **scope** (``scope(key)``) — a display slot the UI reads (``figure:<character>`` for a Build step,
  ``piece:<character>:<item>`` for a piece dialog, ``base:<character>`` for the base body's Run all). Opened by the
  thread that runs the job; the scopes travel in a ``ContextVar``, so nested scopes all receive the reports.
- **stage** (``stage(name)``) — what the server-side job does now ("Measuring the body").
- **head + sub** — a subprocess or worker run under the stage: ``attach(name, file)`` names it ("Rigging
  (Blender)") and points at its progress FILE; the run writes its own sub-stage there (``write_file``, or the
  Blender twin ``progress`` in ``app/blender/scripts/_common.py``). In-process compute calls ``sub(stage, i, n)``;
  inside a refit-pool worker the same call writes the file the parent attached (``child_file``).

Progress is never worth a failed job: every function here swallows its own errors. Read-only for the UI:
``snapshot(key)``. The task queue's display row follows along when a scope has a ``relabel`` callback (throttled,
refreshed by a small ticker so a Blender file's frames reach the row without a UI poll).
"""
from __future__ import annotations

import contextlib
import contextvars
import json
import logging
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

logger = logging.getLogger(__name__)

#: The English labels of stage keys (translatable on the React side: every value is a de.json key). Modules add
#: their own with ``register_labels``; an unknown key is shown as itself with ``_`` as spaces.
LABELS: Dict[str, str] = {
    # Blender scripts (``runner.run`` attaches ``blender:<script>``)
    "blender:rig_export": "Rigging (Blender)",
    "blender:rig_rest": "Reading the rig (Blender)",
    "blender:extension_bones": "Extension bones (Blender)",
    "blender:attached_part": "Attached part (Blender)",
    "blender:inset_part": "Inset part (Blender)",
    "blender:normalize": "Normalising the model (Blender)",
    "blender:limb_weights": "Limb weights (Blender)",
    "blender:lod": "Level of detail (Blender)",
    "blender:meshopt": "Compressing the model (Blender)",
    "blender:measure": "Measuring the model (Blender)",
    "blender:diagnose": "Checking the model (Blender)",
    "blender:bake_vc": "Baking colours (Blender)",
    "blender:quadruped_rig": "Quadruped rig (Blender)",
    "blender:retexture": "Retexturing (Blender)",
    "blender:garment_template_build": "Template drape (Blender)",
    "blender:hull_build": "Building the hull (Blender)",
    "blender:heightgrid": "Height grid (Blender)",
    "blender:picture_areas": "Picture areas (Blender)",
    "blender:glb_to_ref_fbx": "Converting the clip (Blender)",
    "blender:clip_measure": "Measuring the clip (Blender)",
    "blender:fbx_clip": "Importing the clip (Blender)",
    "blender:cmu_clip": "Importing the clip (Blender)",
    "blender:clip_orient": "Orienting the clip (Blender)",
    "blender:clip_to_bvh": "Exporting the clip (Blender)",
    "blender:waterdetect": "Finding water (Blender)",
    "blender:door_build": "Building the door (Blender)",
    # refit-pool compute (``refit_pool.run`` attaches ``cpu:<function>``)
    "cpu:fit_clothing": "Garment fit",
    "cpu:build_shell": "Shell build",
    "cpu:fit_hairdeck": "Hair deck fit",
    "cpu:fit_haar": "Hair strand fit",
    "cpu:fit_compute": "Footwear insole fit",
    "cpu:derive_compute": "Footwear insole fit",
    "cpu:graft_file": "Assembling the figure",
    "cpu:_build": "Layered build",
    # external workers
    "worker:body_retexture": "Retexturing the body",
    # in-process stages
    "face_cleanup": "Face cleanup",
    "assemble": "Assembling the figure",
    "postprocess": "Post-processing the view",
    "matte": "Cutting out the piece",
    "iterate": "Iterating",
    # Blender sub-stages (``_common.progress``)
    "loading": "Loading the model",
    "exporting": "Writing the model",
    "building_part": "Building the part",
    "filling": "Filling the hole",
    "takes": "Baking the takes",
    "skinning": "Skinning",
    "posture": "Posture pass",
    # Python compute sub-stages (``cpu_progress.sub``)
    "drape_substeps": "Cloth substeps",
    "shell_views": "Shell views",
    "insole_feet": "Feet",
    "frame": "Frame",
    "bones": "Bones",
    "parts": "Parts",
    "levels": "Levels",
    "views": "Views",
    "pieces": "Pieces",
    "poses": "Poses",
    "working": "Working",
}

#: ``scope`` key -> entry ``{started, stage, stage_at, head, head_at, file, sub, relabel, shown, depth}``.
_entries: Dict[str, Dict[str, Any]] = {}
_lock = threading.Lock()
_scopes: contextvars.ContextVar[Tuple[str, ...]] = contextvars.ContextVar("cpu_progress_scopes", default=())
#: Set in a child (refit-pool worker): ``sub`` writes this file instead of the registry (``child_file``).
_child: Dict[str, Optional[str]] = {"file": None, "t0": None, "stage": None}
#: How often a scope's task-queue row is relabelled at most, and how often the ticker looks.
RELABEL_EVERY_S = 1.0
TICK_S = 2.0
_ticker: Dict[str, Any] = {"thread": None}


def register_labels(labels: Dict[str, str]) -> None:
    """Add stage labels (a module's own keys). Never raises."""
    try:
        LABELS.update({str(k): str(v) for k, v in labels.items()})
    except Exception:  # noqa: BLE001
        pass


def label_of(key: Optional[str]) -> str:
    if not key:
        return ""
    return LABELS.get(key) or str(key).split(":", 1)[-1].replace("_", " ").strip().capitalize()


def _now() -> float:
    return time.monotonic()


# --- the writing side --------------------------------------------------------------

@contextlib.contextmanager
def scope(key: str, *, relabel: Optional[Callable[[str], None]] = None) -> Iterator[None]:
    """Report into ``key`` for the block (this thread / context and what it calls). Re-entering a key that is
    open keeps its clock. ``relabel(line)`` is called (throttled) with the current line — a task-queue row."""
    token = None
    try:
        with _lock:
            entry = _entries.get(key)
            if entry is None:
                entry = _entries[key] = {"started": _now(), "stage": None, "stage_at": _now(), "head": None,
                                         "head_at": None, "file": None, "sub": None, "relabel": None,
                                         "shown": 0.0, "depth": 0}
            entry["depth"] += 1
            if relabel is not None:
                entry["relabel"] = relabel
        token = _scopes.set(tuple(k for k in _scopes.get() if k != key) + (key,))
        if relabel is not None:
            _ensure_ticker()
    except Exception:  # noqa: BLE001 — progress never stops a job
        logger.debug("cpu_progress scope %s not opened", key, exc_info=True)
    try:
        yield
    finally:
        try:
            if token is not None:
                _scopes.reset(token)
            with _lock:
                entry = _entries.get(key)
                if entry is not None:
                    entry["depth"] -= 1
                    if entry["depth"] <= 0:
                        _entries.pop(key, None)
        except Exception:  # noqa: BLE001
            pass


def scoped(key: str, fn: Callable[..., Any]) -> Callable[..., Any]:
    """``fn`` wrapped to run in ``scope(key)`` — for a thread target (``Thread(target=scoped(k, run))``)."""
    def _wrapped(*args: Any, **kwargs: Any) -> Any:
        with scope(key):
            return fn(*args, **kwargs)
    return _wrapped


def active() -> bool:
    """True when a report here reaches a scope (or a parent's file, in a worker)."""
    return bool(_scopes.get()) or bool(_child.get("file"))


def _each(fn: Callable[[Dict[str, Any]], None]) -> None:
    keys = _scopes.get()
    if not keys:
        return
    with _lock:
        for key in keys:
            entry = _entries.get(key)
            if entry is not None:
                fn(entry)
    for key in keys:
        _maybe_relabel(key)


def stage(name: str) -> None:
    """The server-side stage of every open scope (resets head and sub). Never raises."""
    try:
        def _set(entry: Dict[str, Any]) -> None:
            entry.update(stage=name, stage_at=_now(), head=None, head_at=None, file=None, sub=None)
        _each(_set)
    except Exception:  # noqa: BLE001
        pass


def sub(stage_key: str, i: Optional[int] = None, n: Optional[int] = None, *, label: Optional[str] = None) -> None:
    """Inner-loop progress (``i`` of ``n``) — into the open scopes, or, in a worker, into the parent's file.
    Never raises; cheap enough to call per iteration (a file write is throttled to 4 per second)."""
    try:
        path = _child.get("file")
        if path:
            now = time.time()
            if _child.get("stage") != stage_key:
                _child["stage"], _child["t0"] = stage_key, now
            elif i is not None and n is not None and 0 < i < n and now - float(_child.get("last") or 0) < 0.25:
                return
            _child["last"] = now
            write_file(path, stage_key, i, n, label=label, t0=_child["t0"])
            return

        def _set(entry: Dict[str, Any]) -> None:
            old = entry.get("sub") or {}
            t0 = old.get("t0") if old.get("stage") == stage_key else time.time()
            entry["sub"] = {"stage": stage_key, "label": label, "i": i, "n": n, "t0": t0, "t": time.time()}
        _each(_set)
    except Exception:  # noqa: BLE001
        pass


def progress_path(prefix: str = "progress") -> str:
    """A fresh private file path for a run's progress record (its folder exists; the file does not)."""
    folder = Path(tempfile.gettempdir()) / f"anima-progress-{os.getuid() if hasattr(os, 'getuid') else 0}"
    folder.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f"{prefix}-", suffix=".json", dir=str(folder))
    os.close(fd)
    os.unlink(name)
    return name


@contextlib.contextmanager
def attach(head: str, file: Optional[str] = None) -> Iterator[None]:
    """A subprocess / worker run named ``head`` (a ``LABELS`` key) under the current stage, reporting into
    ``file`` while the block runs. Restores the previous head afterwards (runs nest: a Blender run inside a
    worker-free fit)."""
    saved: Dict[str, Tuple[Any, Any, Any, Any]] = {}
    try:
        keys = _scopes.get()
        with _lock:
            for key in keys:
                entry = _entries.get(key)
                if entry is not None:
                    saved[key] = (entry.get("head"), entry.get("head_at"), entry.get("file"), entry.get("sub"))
                    entry.update(head=head, head_at=_now(), file=file, sub=None)
        for key in keys:
            _maybe_relabel(key, force=True)
    except Exception:  # noqa: BLE001
        pass
    try:
        yield
    finally:
        try:
            with _lock:
                for key, (h, at, f, s) in saved.items():
                    entry = _entries.get(key)
                    if entry is not None:
                        entry.update(head=h, head_at=at, file=f, sub=s)
            if file:
                Path(file).unlink(missing_ok=True)
                Path(file + ".tmp").unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass


def write_file(path: str, stage_key: str, i: Optional[int] = None, n: Optional[int] = None, *,
               label: Optional[str] = None, t0: Optional[float] = None) -> None:
    """Write one progress record (atomically replaced): ``{stage, label, i, n, t0, t}``. Never raises."""
    try:
        now = time.time()
        rec = {"stage": stage_key, "label": label, "i": i, "n": n, "t0": t0 if t0 is not None else now, "t": now}
        tmp = Path(str(path) + ".tmp")
        tmp.write_text(json.dumps(rec), encoding="utf-8")
        tmp.replace(path)
    except Exception:  # noqa: BLE001
        pass


@contextlib.contextmanager
def child_file(path: Optional[str]) -> Iterator[None]:
    """In a worker process: ``sub`` writes ``path`` for the block."""
    old = dict(_child)
    _child.update(file=path, t0=None, stage=None, last=0.0)
    try:
        yield
    finally:
        _child.clear()
        _child.update(old)


def run_reporting(path: Optional[str], fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Module-level trampoline a process pool can pickle: ``fn(*args, **kwargs)`` with ``child_file(path)``."""
    with child_file(path):
        return fn(*args, **kwargs)


# --- the reading side --------------------------------------------------------------

def _read_file(path: str) -> Optional[Dict[str, Any]]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _int(v: Any) -> Optional[int]:
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _normalise_sub(data: Dict[str, Any]) -> Dict[str, Any]:
    """A file record in either shape: the generic ``{stage, label, i, n, t0, t}`` or A172's drape record
    ``{stage, index, count, pose, frame, frames}`` (pose shape i/n, else frame i/n)."""
    i, n = _int(data.get("i")), _int(data.get("n"))
    extra = ""
    if i is None and n is None:
        if data.get("count"):
            i, n = _int(data.get("index")), _int(data.get("count"))
            if data.get("frame") and data.get("frames"):
                extra = f"frame {_int(data.get('frame'))}/{_int(data.get('frames'))}"
        elif data.get("frames"):
            i, n = _int(data.get("frame")), _int(data.get("frames"))
    label = data.get("label") or label_of(data.get("stage"))
    if data.get("pose"):
        label = f"{label} ({str(data['pose']).replace('_', ' ')})"
    return {"stage": data.get("stage"), "label": label, "i": i, "n": n, "extra": extra,
            "t0": data.get("t0"), "t": data.get("t")}


def eta_seconds(i: Optional[int], n: Optional[int], spent_s: float) -> Optional[float]:
    """Linear estimate of the rest: ``spent / i * (n - i)``; None without a usable i/n or before 2 s of data."""
    if not i or not n or i <= 0 or n <= i or spent_s < 2.0:
        return None
    return spent_s / i * (n - i)


def format_line(parts: List[Dict[str, Any]], elapsed_s: float, eta_s: Optional[float]) -> str:
    """``"Stage · Sub i/n · 42 s · ~30 s left"`` — the one line (English; the React side builds the same with t())."""
    out = []
    for p in parts:
        text = str(p.get("label") or "")
        if p.get("i") is not None and p.get("n"):
            text = f"{text} {p['i']}/{p['n']}".strip()
        if text:
            out.append(text)
        if p.get("extra"):
            out.append(str(p["extra"]))
    out.append(f"{int(round(elapsed_s))} s")
    if eta_s is not None:
        out.append(f"~{int(round(eta_s))} s left")
    return " · ".join(out)


def snapshot(key: str) -> Optional[Dict[str, Any]]:
    """What ``key`` does now — ``{parts: [{label, i, n, extra}], elapsed_s, eta_s, line, stage, head}`` — or None
    when it is not open. ``elapsed_s`` counts from the innermost of head / stage / scope start. Never raises."""
    try:
        with _lock:
            entry = dict(_entries.get(key) or {})
        if not entry:
            return None
        now = _now()
        parts: List[Dict[str, Any]] = []
        if entry.get("stage"):
            parts.append({"label": label_of(entry["stage"]), "i": None, "n": None, "extra": ""})
        if entry.get("head"):
            parts.append({"label": label_of(entry["head"]), "i": None, "n": None, "extra": ""})
        sub_rec = entry.get("sub")
        if entry.get("file"):
            data = _read_file(entry["file"])
            if data:
                sub_rec = _normalise_sub(data)
        elif sub_rec:
            sub_rec = {**sub_rec, "label": sub_rec.get("label") or label_of(sub_rec.get("stage")), "extra": ""}
        eta = None
        if sub_rec:
            parts.append({"label": sub_rec.get("label") or "", "i": sub_rec.get("i"), "n": sub_rec.get("n"),
                          "extra": sub_rec.get("extra") or ""})
            try:
                spent = float(sub_rec.get("t") or 0) - float(sub_rec.get("t0") or 0)
            except (TypeError, ValueError):
                spent = 0.0
            eta = eta_seconds(sub_rec.get("i"), sub_rec.get("n"), spent)
        if not parts:
            parts.append({"label": label_of("working"), "i": None, "n": None, "extra": ""})
        since = entry.get("head_at") or entry.get("stage_at") or entry.get("started") or now
        elapsed = max(0.0, now - float(since))
        return {"parts": parts, "elapsed_s": round(elapsed, 1), "eta_s": round(eta, 1) if eta is not None else None,
                "total_s": round(max(0.0, now - float(entry.get("started") or now)), 1),
                "stage": entry.get("stage"), "head": entry.get("head"),
                "line": format_line(parts, elapsed, eta)}
    except Exception:  # noqa: BLE001
        logger.debug("cpu_progress snapshot %s failed", key, exc_info=True)
        return None


def _maybe_relabel(key: str, *, force: bool = False) -> None:
    try:
        with _lock:
            entry = _entries.get(key)
            if entry is None or entry.get("relabel") is None:
                return
            if not force and _now() - float(entry.get("shown") or 0) < RELABEL_EVERY_S:
                return
            entry["shown"] = _now()
            relabel = entry["relabel"]
        snap = snapshot(key)
        if snap:
            relabel(snap["line"])
    except Exception:  # noqa: BLE001
        logger.debug("cpu_progress relabel %s failed", key, exc_info=True)


def _tick() -> None:
    while True:
        time.sleep(TICK_S)
        with _lock:
            keys = [k for k, e in _entries.items() if e.get("relabel") is not None]
        for key in keys:
            _maybe_relabel(key)


def _ensure_ticker() -> None:
    with _lock:
        if _ticker["thread"] is not None:
            return
        t = threading.Thread(target=_tick, daemon=True, name="cpu-progress-ticker")
        _ticker["thread"] = t
    t.start()


def track_relabel(queue: Any, task_id: str, base: str) -> Optional[Callable[[str], None]]:
    """A ``relabel`` that writes ``"<base> — <line>"`` onto a task-queue display row (None without a row)."""
    if queue is None or not task_id:
        return None

    def _relabel(line: str) -> None:
        try:
            queue.track_update_label(task_id, f"{base} — {line}")
        except Exception:  # noqa: BLE001
            pass
    return _relabel
