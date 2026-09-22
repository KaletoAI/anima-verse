#!/usr/bin/env python3
"""Smoke run for the world's media master switch (`image_generation.enabled`).

Usage:
    ./.venv/bin/python scripts/smoke_media_generation_switch.py

Runs WITHOUT the server and against a THROWAWAY storage dir: ``paths.init`` is
called with a temp directory BEFORE the first app import, so no world DB and no
real ``task_queue.db`` can be touched. Nothing is generated — the backend under
test is a stub that only counts how often it was asked.

THE RULE
---------------------------------------------------------------------------
The admin switch "Media generation enabled" (Admin → Settings → Media
Generation, config path ``image_generation.enabled``) must switch off ALL media
generation of the world: images, video and 3D meshes. Until this change it was
only written into an env var nobody read (``SKILL_IMAGEGEN_ENABLED``) and used
as a routing gate for the LLM task catalog, so every render still ran.

The gate sits at the ONE handoff every generation crosses —
``ImageService.run_on_backend_channel`` (CLAUDE.md: "Every generation goes
through run_on_backend_channel — never backend.generate() directly"). It is
checked THERE and not in the backend, because the channel submission is what
queues the task and takes the GPU slot: a check inside the worker would let a
world with the switch off collect hundreds of tasks that each fail on arrival.

Hand-derived expectations, read off the source, never recorded from a run
---------------------------------------------------------------------------
  [1] ``media_generation_enabled()`` is the live read of
      ``config.get("image_generation.enabled", True)``:
        key absent -> True (a world that never saved the section generates),
        False       -> False,
        True        -> True.

  [2] With the switch OFF, ``run_on_backend_channel`` raises
      ``MediaGenerationDisabled`` with exactly the message
      "Media generation is disabled for this world", and
        * ``ProviderManager.submit_gpu_task`` is called ZERO times
          (nothing is queued, no GPU slot is taken), and
        * the stub backend's ``_generate`` is called ZERO times.
      With the switch ON the same call reaches the stub exactly once and
      returns its result — measured against a REAL single-slot
      ``ProviderQueue`` channel, so [2] cannot pass for want of a queue.

  [3] The exception is NOT a ``BackendBusyError``: busy means "retry
      elsewhere, no cooldown", this means "an admin has to turn it back on".
      ``issubclass(MediaGenerationDisabled, BackendBusyError)`` must be False,
      and the persistent ``TaskQueue`` must end such a task as **failed** with
      that message as its error (max_retries=0 -> exactly one attempt).

  [4] ``selection.run_on_backend`` must NOT put the backend on cooldown for
      it — the backend never saw the request, and a cooldown (300 s) would
      outlive switching the feature back on. Control in the same check: an op
      raising a plain ``RuntimeError`` DOES cool the backend down, so the
      assertion measures something.

  [5] The three public entry points refuse before any backend is asked:
        ``generate_video``  -> raises MediaGenerationDisabled
        ``generate_mesh``   -> raises MediaGenerationDisabled
        ``generate_from_input`` -> returns the string
            "Error: Media generation is disabled for this world"
            (its contract is a STRING — the LLM tool surface, the instagram
            post and npc_assets all read its prefix), and it returns it
            BEFORE parsing its input, i.e. even with a nonsense payload.

  [6] ``world_ops.build_imagegen_options()`` — the payload the render dialogs
      read from ``GET /world/imagegen-options`` — carries
      ``media_generation_enabled``: False while the switch is off, True while
      it is on. The dialog disables its Generate button on it.

  [7] The high-volume submitters skip instead of filling the queue:
        ``outfit_batch.start``            -> {"ok": False, "error": <message>}
        ``expression_regen.trigger_expression_generation`` -> False, and the
            generator behind it is never called (counted with a stub)
        ``npc_assets.gate_placement``     -> False (the NPC is placed as it
            is instead of being pooled forever) and no job is submitted
        ``improvements.engine.submit_allowed`` -> (False, "media_off")
      Each of them is checked in BOTH switch positions where that is possible
      without a world DB; ``submit_allowed``'s ON branch reads the
      improvements settings from the world DB, so only "not media_off" is
      asserted there.

  [8] ``skills/animate.animate_image`` returns False for every failed render,
      but a refusal is not a failure: with a service stub whose
      ``generate_video`` raises ``MediaGenerationDisabled`` the adapter must
      RE-RAISE it (message intact) so the route can answer 409 and a queue job
      records the real reason. Control in the same check: a stub raising a
      plain ``RuntimeError`` must still come back as ``False`` — the contract
      for every other error is unchanged.

  [9] The nesting guard. ``animate_image`` -> ``ImageService.generate_video``
      already submits onto the video backend's channel, so a caller that ALSO
      wraps it in ``submit_gpu_task`` runs that inner submission inside a GPU
      worker — a nested submit onto a single-slot channel deadlocks (CLAUDE.md;
      ``app/routes/instagram.py`` did exactly that). Expected answer, over the
      AST of every file under ``app/`` that names both: ZERO
      ``submit_gpu_task(...)`` calls whose arguments mention ``animate_image``.
      The one correct shape is the direct call from a thread that
      ``app/skills/video_generation_skill.py`` has always used, with the
      tracked task for queue-panel visibility.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

# Throwaway storage BEFORE any app module that could open a DB is imported.
_TMP = Path(tempfile.mkdtemp(prefix="smoke_media_switch_"))
os.environ["ANIMATION_CLIPS_DIR"] = str(_TMP / "clips")
from app.core import paths  # noqa: E402

paths.init(_TMP)
assert paths.get_storage_dir() == _TMP.resolve(), paths.get_storage_dir()

from app.core import config  # noqa: E402
from app.core import provider_manager as pm_mod  # noqa: E402
from app.core.provider import Provider  # noqa: E402
from app.core.provider_queue import ProviderQueue  # noqa: E402
from app.core.task_queue import TaskQueue  # noqa: E402
from app.imagegen.base import (BackendBusyError, ImageBackend,  # noqa: E402
                               MediaGenerationDisabled,
                               media_generation_enabled)
from app.imagegen.service import ImageService  # noqa: E402

MESSAGE = "Media generation is disabled for this world"

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}{(' — ' + detail) if detail else ''}")
        failures.append(label)


def switch(value) -> None:
    """Set / remove `image_generation.enabled` in the LIVE config.

    The running config is what ``media_generation_enabled()`` reads; there is
    no file to save here (and saving one would be a world write).
    """
    section = config._CONFIG.setdefault("image_generation", {})
    if value is None:
        section.pop("enabled", None)
    else:
        section["enabled"] = value


class _Stub(ImageBackend):
    """Counts every generation it is asked for. It never produces a file."""

    def __init__(self, name: str = "STUB"):
        super().__init__(name, "http://localhost", 0.0, "fake", "SMOKE_STUB_")
        self._available = True
        self.instance_enabled = True
        self.calls = 0

    def check_availability(self) -> bool:
        return True

    def _generate(self, prompt, negative_prompt, params):
        self.calls += 1
        return [b"img"]


class _RecordingManager:
    """Stands in for the ProviderManager: records every queue submission."""

    def __init__(self):
        self.submissions: list[dict] = []

    def submit_gpu_task(self, provider_name="", task_type="", priority=20,
                        callable_fn=None, agent_name="", label="",
                        gpu_type=""):
        self.submissions.append({"provider": provider_name, "task": task_type})
        return callable_fn() if callable_fn else None


def _real_manager(names):
    """A real ProviderManager with one single-slot channel per backend name."""
    pm = pm_mod.ProviderManager()
    for n in names:
        provider = Provider(name=n, type="image", api_base="", api_key="",
                            max_concurrent=1, timeout=60)
        provider.available = True
        pq = ProviderQueue(provider, queue_name=f"backend:{n}",
                           max_concurrent=1, chat_pause_enabled=False)
        pm.channels[f"backend:{n}"] = pq
        pm._backend_providers[n] = provider
        pm._known_backend_names.add(n)
    return pm


def raises(fn):
    """Runs fn() and returns the exception it raised (or None)."""
    try:
        fn()
    except BaseException as e:  # noqa: BLE001 — the type IS the result
        return e
    return None


# ---------------------------------------------------------------------------
def part_read():
    print("[1] media_generation_enabled() reads the switch live")
    switch(None)
    check("key absent -> True", media_generation_enabled() is True)
    switch(False)
    check("False -> False", media_generation_enabled() is False)
    switch(True)
    check("True -> True", media_generation_enabled() is True)


def part_choke_point():
    print("[2] the gate sits BEFORE the queue submission")
    orig = pm_mod.get_provider_manager

    stub = _Stub("B_OFF")
    rec = _RecordingManager()
    pm_mod.get_provider_manager = lambda: rec
    try:
        switch(False)
        exc = raises(lambda: ImageService.run_on_backend_channel(
            stub, lambda: stub.generate("p", "", {}), task_type="smoke"))
    finally:
        pm_mod.get_provider_manager = orig
    check("off: raises MediaGenerationDisabled",
          type(exc).__name__ == "MediaGenerationDisabled", repr(exc))
    check("off: the message is the one the UI shows", str(exc) == MESSAGE,
          str(exc))
    check("off: nothing was submitted to a queue", rec.submissions == [],
          repr(rec.submissions))
    check("off: the backend was never asked", stub.calls == 0)

    stub_on = _Stub("B_ON")
    pm = _real_manager(["B_ON"])
    pm_mod.get_provider_manager = lambda: pm
    try:
        switch(True)
        result = ImageService.run_on_backend_channel(
            stub_on, lambda: stub_on.generate("p", "", {}), task_type="smoke")
    finally:
        pm_mod.get_provider_manager = orig
    check("on: the real channel reaches the backend once", stub_on.calls == 1)
    check("on: the result travels back", result == [b"img"], repr(result))


def part_not_busy():
    print("[3] it is not a 'busy' and the queue fails such a task")
    check("MediaGenerationDisabled is not a BackendBusyError",
          not issubclass(MediaGenerationDisabled, BackendBusyError))

    tq = TaskQueue()
    conn = tq._connect()
    try:
        conn.execute("DELETE FROM tasks")
        conn.execute("DELETE FROM queue_paused")
        conn.commit()
    finally:
        conn.close()

    def _handler(_payload):
        raise MediaGenerationDisabled(MESSAGE)

    tq.register_handler("smoke_media_off", _handler)
    tq.start()
    task_id = tq.submit("smoke_media_off", {}, queue_name="smoke_media_q",
                        max_retries=0)
    row = None
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        conn = tq._connect()
        try:
            row = conn.execute(
                "SELECT status, error, retry_count FROM tasks WHERE task_id=?",
                (task_id,)).fetchone()
        finally:
            conn.close()
        if row and row["status"] in ("failed", "completed"):
            break
        time.sleep(0.05)
    tq._stopped = True
    tq._wake_event.set()
    check("the task ends as failed", bool(row) and row["status"] == "failed",
          repr(dict(row)) if row else "no row")
    check("the error is the message", bool(row) and row["error"] == MESSAGE,
          repr(row["error"]) if row else "")
    check("it was not retried", bool(row) and row["retry_count"] == 0,
          repr(row["retry_count"]) if row else "")


def part_no_cooldown():
    print("[4] a refused render does not cool the backend down")
    switch(False)
    svc = ImageService()

    cold = _Stub("B_COLD")

    def _op_disabled(_b):
        raise MediaGenerationDisabled(MESSAGE)

    exc = raises(lambda: svc.run_on_backend(cold, _op_disabled))
    check("off: raised typed", type(exc).__name__ == "MediaGenerationDisabled",
          repr(exc))
    check("off: no cooldown on the backend", cold._cooldown_until == 0.0,
          repr(cold._cooldown_until))

    control = _Stub("B_CTRL")

    def _op_broken(_b):
        raise RuntimeError("the gateway is on fire")

    raises(lambda: svc.run_on_backend(control, _op_broken))
    check("control: a real defect DOES cool the backend down",
          control._cooldown_until > 0.0, repr(control._cooldown_until))


def part_entry_points():
    print("[5] the public entry points refuse before any backend is asked")
    from app.imagegen.selection import BackendPool

    switch(False)
    svc = ImageService()
    # A video and a mesh stub IN the pool, so the selection in generate_video /
    # generate_mesh really succeeds and the refusal can only come from the
    # gate — without them both functions would bail out with "no backend
    # available" and this check would pass for the wrong reason.
    video = _Stub("V_STUB")
    video.MEDIA_TYPE = "video"
    mesh = _Stub("M_STUB")
    mesh.MEDIA_TYPE = "mesh"
    mesh.mesh_rig = "mixamo"
    mesh.category = "img2mesh"
    svc._pool = BackendPool([video, mesh], agent_instances_provider=lambda _n: {})

    orig_pm = pm_mod.get_provider_manager
    rec = _RecordingManager()
    pm_mod.get_provider_manager = lambda: rec
    try:
        exc = raises(lambda: svc.generate_video("/tmp/none.png", "walk",
                                                "/tmp/out.mp4"))
        exc2 = raises(lambda: svc.generate_mesh("/tmp/none.png",
                                                "/tmp/out.glb", rig="mixamo"))
    finally:
        pm_mod.get_provider_manager = orig_pm
    check("generate_video raises MediaGenerationDisabled",
          type(exc).__name__ == "MediaGenerationDisabled", repr(exc))
    check("generate_mesh raises MediaGenerationDisabled",
          type(exc2).__name__ == "MediaGenerationDisabled", repr(exc2))
    check("neither queued anything", rec.submissions == [],
          repr(rec.submissions))
    check("neither backend was asked", (video.calls, mesh.calls) == (0, 0),
          repr((video.calls, mesh.calls)))
    answer = svc.generate_from_input(json.dumps({"prompt": "a cat",
                                                 "agent_name": "Demo"}))
    check("generate_from_input answers with the Error string",
          answer == f"Error: {MESSAGE}", repr(answer))
    answer = svc.generate_from_input("not json at all")
    check("generate_from_input refuses before it parses its input",
          answer == f"Error: {MESSAGE}", repr(answer))


def part_options_payload():
    print("[6] the options payload the dialogs read carries the flag")
    from app.core import world_ops

    switch(False)
    payload = world_ops.build_imagegen_options()
    check("off: media_generation_enabled is False",
          payload.get("media_generation_enabled") is False, repr(payload)[:200])
    switch(True)
    payload = world_ops.build_imagegen_options()
    check("on: media_generation_enabled is True",
          payload.get("media_generation_enabled") is True, repr(payload)[:200])


def part_submitters():
    print("[7] the high-volume submitters skip while the switch is off")
    from app.core import expression_regen, npc_assets, outfit_batch
    from app.core.improvements import engine as imp_engine
    from app.models import character as character_mod

    switch(False)
    res = outfit_batch.start("Demo")
    check("outfit_batch.start: refused", res.get("ok") is False, repr(res))
    check("outfit_batch.start: says why", MESSAGE in str(res.get("error")),
          repr(res))

    # expression_regen: the generator behind the trigger is replaced by a
    # counter, so "did it start a render" is measured, not guessed.
    orig_trigger = expression_regen._do_trigger_expression_generation
    calls: list[str] = []
    expression_regen._do_trigger_expression_generation = (
        lambda *a, **kw: calls.append(a[0]) or True)
    try:
        got = expression_regen.trigger_expression_generation(
            "Demo", "", "standing", ignore_feature_gate=True, coalesce=False)
        check("expression trigger: off -> False", got is False, repr(got))
        check("expression trigger: off -> nothing generated", calls == [],
              repr(calls))
        switch(True)
        got = expression_regen.trigger_expression_generation(
            "Demo", "", "standing", ignore_feature_gate=True, coalesce=False)
        check("expression trigger: on -> the generator runs", len(calls) == 1,
              repr(calls))
    finally:
        expression_regen._do_trigger_expression_generation = orig_trigger

    # npc_assets: the gate must place the NPC instead of pooling it forever.
    switch(False)
    orig_is_temp = character_mod.is_temporary_npc
    orig_submit = npc_assets.submit_assets_job
    submitted: list[str] = []
    character_mod.is_temporary_npc = lambda _n: True
    npc_assets.submit_assets_job = (
        lambda *a, **kw: submitted.append(a[0] if a else "") or "task")
    try:
        held = npc_assets.gate_placement("Demo", "loc_demo")
        check("npc gate: off -> the NPC is not held back", held is False,
              repr(held))
        check("npc gate: off -> no finishing job queued", submitted == [],
              repr(submitted))
    finally:
        character_mod.is_temporary_npc = orig_is_temp
        npc_assets.submit_assets_job = orig_submit

    switch(False)
    allowed, reason = imp_engine.submit_allowed()
    check("improvements: off -> (False, 'media_off')",
          (allowed, reason) == (False, "media_off"), repr((allowed, reason)))
    switch(True)
    try:
        _allowed, reason_on = imp_engine.submit_allowed()
    except Exception as e:  # noqa: BLE001 — a DB-less store read may fail
        reason_on = f"<{type(e).__name__}>"
    check("improvements: on -> the media gate is passed",
          reason_on != "media_off", repr(reason_on))


def part_animate():
    print("[8] the animate adapter passes the refusal on")
    from app.skills import animate as animate_mod

    class _RefusingService:
        """Stands in for the ImageService: generate_video refuses like the gate."""

        def __init__(self):
            self.calls = 0

        def generate_video(self, **_kw):
            self.calls += 1
            raise MediaGenerationDisabled(MESSAGE)

    stub_service = _RefusingService()
    orig = animate_mod._image_service
    animate_mod._image_service = lambda: stub_service
    try:
        exc = raises(lambda: animate_mod.animate_image(
            "/tmp/none.png", "walk", "/tmp/out.mp4"))
    finally:
        animate_mod._image_service = orig
    check("animate_image re-raises MediaGenerationDisabled",
          type(exc).__name__ == "MediaGenerationDisabled", repr(exc))
    check("animate_image: the message survives", str(exc) == MESSAGE, str(exc))
    check("animate_image: it did reach generate_video", stub_service.calls == 1)

    # A plain defect must still collapse into False — the adapter's contract
    # for every OTHER error is unchanged.
    class _BrokenService:
        def generate_video(self, **_kw):
            raise RuntimeError("the gateway is on fire")

    animate_mod._image_service = lambda: _BrokenService()
    try:
        got = animate_mod.animate_image("/tmp/none.png", "walk", "/tmp/out.mp4")
    finally:
        animate_mod._image_service = orig
    check("control: a real defect is still False", got is False, repr(got))


def part_no_nested_submit():
    print("[9] no submit_gpu_task wraps animate_image (nested-submit guard)")
    import ast

    # ``animate_image`` -> ``ImageService.generate_video`` submits onto the
    # video backend's channel ITSELF. A caller that ALSO submits it as a GPU
    # task runs that inner submission inside a queue worker, and a nested
    # submit onto a single-slot channel deadlocks (CLAUDE.md). The one correct
    # shape is a direct call from a thread, as
    # app/skills/video_generation_skill.py does it.
    offenders: list[str] = []
    scanned = 0
    for path in sorted((REPO / "app").rglob("*.py")):
        text = path.read_text(encoding="utf-8", errors="replace")
        if "animate_image" not in text or "submit_gpu_task" not in text:
            continue
        scanned += 1
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = (node.func.attr if isinstance(node.func, ast.Attribute)
                    else getattr(node.func, "id", ""))
            if name != "submit_gpu_task":
                continue
            # Everything handed to this submission, callable_fn included.
            inner = ast.unparse(node)
            if "animate_image" in inner:
                offenders.append(
                    f"{path.relative_to(REPO)}:{node.lineno}")
    print(f"     ({scanned} file(s) name both animate_image and submit_gpu_task)")
    check("no GPU submission wraps animate_image", offenders == [],
          ", ".join(offenders))

    # Self-test on the shape that was there until this change — a scanner that
    # finds nothing must be shown to find something.
    old_shape = (
        "success = get_llm_queue().submit_gpu_task(\n"
        "    provider_name=service, task_type='image_animate',\n"
        "    callable_fn=lambda: animate_image(a, b, c), gpu_type=service)\n")
    found = []
    for node in ast.walk(ast.parse(old_shape)):
        if isinstance(node, ast.Call):
            name = (node.func.attr if isinstance(node.func, ast.Attribute)
                    else getattr(node.func, "id", ""))
            if name == "submit_gpu_task" and "animate_image" in ast.unparse(node):
                found.append(node.lineno)
    check("self-test: the old nested shape IS detected", found == [1],
          repr(found))


def main() -> int:
    print("smoke_media_generation_switch")
    print(f"  storage (throwaway): {_TMP}")
    try:
        part_read()
        part_choke_point()
        part_not_busy()
        part_no_cooldown()
        part_entry_points()
        part_options_payload()
        part_submitters()
        part_animate()
        part_no_nested_submit()
    finally:
        switch(None)
        shutil.rmtree(_TMP, ignore_errors=True)

    print()
    if failures:
        print(f"FAILED ({len(failures)}):")
        for f in failures:
            print(f"  {f}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
