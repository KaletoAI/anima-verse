#!/usr/bin/env python3
"""Smoke: ``runner.run`` answers ``{"ok": False, …}`` on every host-side failure instead of raising (review
02#5), and names HOW the run ended in ``outcome`` (``app.blender.outcome``), with the end of Blender's output as
``log_tail`` and one block in the Blender log.

Usage:
    ./.venv/bin/python scripts/smoke_blender_run_failures.py

No Blender, no server, no world, no instance. The "Blender" is a Python script in a temp folder: it answers
``--version`` with ``Blender 5.2.0``; as a run it does what ``FAKE_MODE`` says (the runner copies the
environment into the child). It is configured through a stubbed ``runner._config``
(``image_generation.blender_executable``) and found by the real discovery; the slot folder is pinned
into the temp folder and ``runner.LOG_FILE`` points into it. Script name ``meshopt`` (only its path reaches
the fake).

Expected, derived by hand from the runner.run docstring ("``ok`` False covers everything"; the outcome table of
``app/blender/outcome.py``):
[1] The input vanishes between the ``is_file`` check and the copy (``shutil.copy2`` stubbed to raise
    FileNotFoundError) → ok False, error starts "input 'model' unreadable", outcome ``crashed``.
[2] The binary is gone after discovery (``status`` stubbed to name a missing path) → ok False, error starts
    "blender could not be started", outcome ``unavailable``.
[3] The binary lost +x (mode 0644) → same as [2] (PermissionError).
[4] Output not valid UTF-8 (bytes ff fe on stdout and stderr), no result, exit 1 → error
    "script wrote no result (exit 1)", outcome ``crashed``.
[5] Same garbage output, but the result file says ok → ok True, outcome ``ok``, log_tail "".
[6] Timeout: the fake writes "TAIL-MARKER-6" to stderr, then sleeps 30 s; timeout_s = 1 → error
    "timeout after 1s", outcome ``timeout``; "TAIL-MARKER-6" is in ``log_tail`` and in the run's block of the
    Blender log; the main.log record is ONE line: it names "timeout" and the log file and carries no output.
[7] The script reports failure itself (result ok False, error "ValueError: REJECT-MARKER", data {why: gate})
    → outcome ``rejected``, error and data passed through, the traceback in ``log_tail``.
[8] Blender killed by SIGTERM (the fake signals itself; no result) → exit −15 → outcome ``interrupted``,
    error "blender was killed by signal 15".
[9] Blender killed by SIGSEGV → exit −11, 11 is not a stop signal → outcome ``crashed``.
[10] Result file not JSON → ``crashed``, error starts "result unreadable".
[11] Result ok but its declared output ``nope.glb`` is missing (out_dir given) → ``crashed``, error
     "declared output 'model' is missing: nope.glb".
[12] ``image_generation.blender_enabled`` False → ``unavailable``, error "blender refinement is disabled", NO
     block written (nothing ran). An unknown script name → ``crashed``, no block.
[13] A chatty ok run: 3000 stdout lines of 51 bytes (= 153000 bytes) + "LAST-STDERR-LINE" → ok; its block's
     body is at most LOG_OK_BYTES (2048) plus the 8-byte cut marker "[… cut]\n" (10 bytes in UTF-8) and ends
     with "LAST-STDERR-LINE"; log_tail "".
[14] The same output, exit 3 without a result → ``crashed``; block body at most LOG_FAILED_BYTES (65536) + 10;
     log_tail = the last TAIL_LINES (40) lines, at most TAIL_BYTES (4096) bytes, its last line
     "LAST-STDERR-LINE".
[15] Every block header reads ``=== <UTC stamp> script=meshopt outcome=<o> seconds=<s> pid=<this pid>
     job=av-blender-<…> exit=<code or -> ===``, one per run that got a job folder (runs [1]..[11], [13], [14]
     plus the baseline: 14 blocks), outcomes ok, crashed, unavailable, unavailable,
     crashed, ok, timeout, rejected, interrupted, crashed, crashed, crashed, ok, crashed.

The retry budget of automatic callers (``app.blender.retry_budget``; DELAYS_S (300, 1200), HOLD_AFTER 3), on a
stubbed monotonic clock starting at t = 1000:
[16] An unknown key may run. ``timeout`` at t=1000 → deferred until 1000+300 = 1300: may_try False at 1299.9,
     True at 1300. ``interrupted`` at 1300 → until 1300+1200 = 2500: False at 2499.9, True at 2500.
     ``unavailable`` at 2500 (the 3rd in a row) → held: may_try False at 2500 + 10**9, held() True, exactly ONE
     WARNING naming the key and "kept timing out / being interrupted" and "held until restart". A 4th ``timeout``
     → still held, still one warning. ``ok`` → cleared: may_try True at once, held() False.
[17] ``rejected`` and ``crashed`` clear a deferred key; ``None`` and ``cancelled`` leave it deferred (until 1300
     for a ``timeout`` at 1000); one key's deferral does not touch another key.
[18] ``slot_wait_s`` (2026-11-18: the template drape takes the queue out of its work time): a run that finds a free
     slot reports a wait under one poll (SLOT_POLL_S 0.25 s); with both slots of the pinned limit 2 held by this
     process and released by a timer after 1.0 s, the run waits until the first poll after the release → 1.0 ≤
     slot_wait_s < 1.0 + 2 polls + 0.5 s of scheduling slack, and ``seconds`` (the whole call) ≥ slot_wait_s.
     Before the field existed ``slot_wait_s`` was absent (read as -1 here) and both checks fail.
[19] A drape left due as the Figure tab reads it (``figure_build``; the garment state, the profile read and the
     retry budget stubbed): ``_run_template`` of a Build click whose drape ran out of time returns a ``StepError``
     equal to LEFT_DUE["timeout"] that carries the drape's ``failure`` (outcome timeout), and notes ``timeout`` for
     the key "drape:K:i1"; ``_left_due`` is True for a timeout failure, False for a rejected one or none;
     ``_build_problem`` (no mesh mismatch) with only the left-due template entry → step "template" with that
     failure; with a real hair failure beside it → step "hair" (STEP_ORDER puts template before hair, so this is the
     left-due rule, not the order); ``_with_cached_failures`` of a step with ``failed`` + ``failure`` → the entry
     carries ``failure``; a ``Step`` equals and hashes as the same step without ``failure``. Before 2026-11-18
     there was no ``StepError`` / ``_left_due`` (AttributeError) and ``_build_problem`` had no ``failure``.
"""
import json
import logging
import os
import re
import shutil
import sys
import tempfile
import threading
import types
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.blender import outcome as oc  # noqa: E402
from app.blender import runner  # noqa: E402
from app.core import process_slots  # noqa: E402

#: A block header of ``runner._write_log``.
HEAD = re.compile(r"^=== (?P<stamp>\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\S*) script=(?P<script>\S+) "
                  r"outcome=(?P<outcome>\S+) seconds=\d+\.\d\d pid=(?P<pid>\d+) job=av-blender-\S+ "
                  r"exit=(?P<exit>-?\d+|-) ===$")


def blocks(path):
    """``[(header, body)]`` of the Blender log, in file order."""
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines(keepends=True):
        if line.startswith("=== ") and HEAD.match(line.rstrip("\n")):
            out.append([line.rstrip("\n"), ""])
        elif out:
            out[-1][1] += line
    return [tuple(x) for x in out]

FAILS = []

FAKE = """#!{python}
import json, os, sys
if sys.argv[1:2] == ["--version"]:
    print("Blender 5.2.0")
    sys.exit(0)
args = json.loads(open(sys.argv[-1], encoding="utf-8").read())
mode = os.environ.get("FAKE_MODE", "")
if mode in ("garbage", "garbage_ok"):
    sys.stdout.buffer.write(b"\\xff\\xfe imported \\xff\\n")
    sys.stderr.buffer.write(b"\\xfe\\xff error \\xff\\n")
    sys.stdout.flush(); sys.stderr.flush()
    if mode == "garbage_ok":
        open(args["result"], "w").write(json.dumps({{"ok": True, "data": {{}}, "outputs": {{}}}}))
    sys.exit(1)
if mode == "hang":
    sys.stderr.write("TAIL-MARKER-6\\n"); sys.stderr.flush()
    os.execvp("sleep", ["sleep", "30"])
if mode == "reject":
    sys.stderr.write("Traceback (most recent call last):\\nValueError: REJECT-MARKER\\n"); sys.stderr.flush()
    open(args["result"], "w").write(json.dumps({{"ok": False, "error": "ValueError: REJECT-MARKER",
                                                 "data": {{"why": "gate"}}, "outputs": {{}}}}))
    sys.exit(1)
if mode in ("sigterm", "segv"):
    import signal
    sys.stderr.write("SIGNAL-MARKER\\n"); sys.stderr.flush()
    os.kill(os.getpid(), signal.SIGTERM if mode == "sigterm" else signal.SIGSEGV)
    import time; time.sleep(5)
if mode == "badjson":
    open(args["result"], "w").write("{{not json")
    sys.exit(0)
if mode == "missing_output":
    open(args["result"], "w").write(json.dumps({{"ok": True, "data": {{}}, "outputs": {{"model": "nope.glb"}}}}))
    sys.exit(0)
if mode in ("chatty_ok", "chatty_fail"):
    for i in range(3000):
        print("line %05d " % i + "x" * 40)
    sys.stdout.flush()
    sys.stderr.write("LAST-STDERR-LINE\\n"); sys.stderr.flush()
    if mode == "chatty_fail":
        sys.exit(3)
open(args["result"], "w").write(json.dumps({{"ok": True, "data": {{}}, "outputs": {{}}}}))
"""


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


class Capture(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.records.append(record.getMessage() if self.text else record)

    text = True


def safe_run(**kw):
    """runner.run, with an escaping exception turned into a FAIL marker."""
    try:
        return runner.run("meshopt", **kw)
    except Exception as e:  # noqa: BLE001 — exactly what the smoke looks for
        return {"ok": None, "error": f"RAISED {type(e).__name__}: {e}"}


def budget_cases() -> None:
    """[16] [17] — the retry budget on a stubbed clock (docstring)."""
    from app.blender import retry_budget as rb
    clock = [1000.0]
    cap = Capture()
    cap.text = False  # the records themselves: their level is checked
    rb.logger.addHandler(cap)
    try:
        with patch.object(rb.time, "monotonic", lambda: clock[0]):
            rb.reset()
            key = "door:/x:arch"
            check(rb.may_try(key), "[16] an unknown key may run")
            rb.note(key, oc.TIMEOUT)
            clock[0] = 1299.9
            first_wait = rb.may_try(key)
            clock[0] = 1300.0
            check(not first_wait and rb.may_try(key), "[16] timeout at 1000: deferred until 1300")
            rb.note(key, oc.INTERRUPTED)
            clock[0] = 2499.9
            second_wait = rb.may_try(key)
            clock[0] = 2500.0
            check(not second_wait and rb.may_try(key), "[16] interrupted at 1300: deferred until 2500")
            rb.note(key, oc.UNAVAILABLE)
            clock[0] = 2500.0 + 10 ** 9
            warnings = [r for r in cap.records if r.levelno == logging.WARNING]
            check(not rb.may_try(key) and rb.held(key), "[16] the 3rd in a row holds it until restart")
            check(len(warnings) == 1 and key in warnings[0].getMessage()
                  and "kept timing out / being interrupted" in warnings[0].getMessage()
                  and "held until restart" in warnings[0].getMessage(),
                  f"[16] one warning naming the key ({[w.getMessage() for w in warnings]})")
            rb.note(key, oc.TIMEOUT)
            warnings = [r for r in cap.records if r.levelno == logging.WARNING]
            check(not rb.may_try(key) and len(warnings) == 1, "[16] a 4th: still held, still one warning")
            rb.note(key, oc.OK)
            check(rb.may_try(key) and not rb.held(key), "[16] ok clears it")
            for ended in (oc.REJECTED, oc.CRASHED):
                clock[0] = 1000.0
                rb.note(key, oc.TIMEOUT)
                rb.note(key, ended)
                check(rb.may_try(key), f"[17] {ended} clears a deferred key")
            for ended in (None, oc.CANCELLED):
                clock[0] = 1000.0
                rb.reset()
                rb.note(key, oc.TIMEOUT)
                rb.note(key, ended)
                clock[0] = 1299.9
                still = not rb.may_try(key)
                clock[0] = 1300.0
                check(still and rb.may_try(key), f"[17] {ended} leaves it deferred until 1300")
            clock[0] = 1000.0
            rb.note(key, oc.TIMEOUT)
            check(rb.may_try("door:/x:other") and not rb.may_try(key), "[17] keys are independent")
    finally:
        rb.logger.removeHandler(cap)
        rb.reset()


def figure_cases() -> None:
    """[19] — a drape left due as the Figure tab reads it (docstring); every world read stubbed."""
    from app.blender import retry_budget as rb
    from app.core import figure_build as fb, garment_template as gt
    due = gt.failure_info({"outcome": oc.TIMEOUT, "error": "Blender timed out", "log_tail": "TAIL"})
    # what ``_build_drape`` answers for a drape left due by a timeout
    left = {"state": "missing", "reason": gt.LEFT_DUE[oc.TIMEOUT], "outcome": oc.TIMEOUT, "failure": due}
    noted = []
    with patch.object(gt, "build", lambda *a, **k: left), patch.object(fb, "_read_profile", lambda c: {}), \
            patch.object(rb, "note", lambda key, o: noted.append((key, o))):
        err = fb._run_template("K", fb.Step("template", "Template drape · Skirt", 0, "i1"), explicit=True)
    check(isinstance(err, fb.StepError) and err == gt.LEFT_DUE[oc.TIMEOUT] and err.failure is due
          and noted == [("drape:K:i1", oc.TIMEOUT)], f"[19] _run_template: the reason with its failure ({err!r})")
    check(fb._left_due({"failure": due}) and not fb._left_due({"failure": {"outcome": oc.REJECTED}})
          and not fb._left_due({"error": "x"}), "[19] _left_due: timeout yes, rejected / no failure no")
    real = {"error": "stretch", "item_id": "i2", "failure": {"outcome": oc.REJECTED}}
    only_due = fb._build_problem("K", [], {"template": {"error": str(err), "item_id": "i1", "failure": due}},
                                 types.SimpleNamespace(shape=""))
    both = fb._build_problem("K", [], {"template": {"error": str(err), "item_id": "i1", "failure": due},
                                       "hair": real}, types.SimpleNamespace(shape=""))
    check((only_due or {}).get("step") == "template" and (only_due or {}).get("failure") is due,
          f"[19] _build_problem: the left-due step with its failure ({only_due})")
    check((both or {}).get("step") == "hair" and (both or {}).get("failure") == real["failure"],
          f"[19] _build_problem: a real failure (hair) before a left-due one (template) ({both})")
    stepped = fb.Step("template", "x", 0, "i1", failed="refused", failure=real["failure"])
    cached = fb._with_cached_failures({}, [stepped])
    check(cached == {"template": {"error": "refused", "item_id": "i1", "failure": real["failure"]}}
          and stepped == fb.Step("template", "x", 0, "i1", failed="refused")
          and hash(stepped) == hash(fb.Step("template", "x", 0, "i1", failed="refused"))
          and stepped.as_dict()["failure"] == real["failure"],
          f"[19] a cached failure keeps its failure; Step equality and hash ignore it ({cached})")


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="smoke-blender-run-"))
    saved_log = runner.LOG_FILE
    cap = Capture()
    runner.logger.addHandler(cap)
    try:
        exe = tmp / "blender"
        exe.write_text(FAKE.format(python=sys.executable), encoding="utf-8")
        exe.chmod(0o755)
        model = tmp / "model.glb"
        model.write_bytes(b"glTF-stub")
        runner.pin_slots(str(tmp / "slots"), 2)
        log_file = tmp / "logs" / "blender.log"
        runner.LOG_FILE = log_file
        runner._version_cache.clear()

        def config(key, default):
            return str(exe) if key == "image_generation.blender_executable" else default

        with patch.object(runner, "_config", config):
            st = runner.status()
            check(st["usable"] and st["executable"] == str(exe), f"fake is discovered ({st['error']!r})")
            res = safe_run(inputs={"model": model}, timeout_s=30)
            check(res["ok"] is True, f"baseline run ok ({res['error']!r})")

            # [1]
            def vanished(src, dst, *a, **kw):
                raise FileNotFoundError(2, "No such file or directory", str(src))
            fake_shutil = types.SimpleNamespace(copy2=vanished, rmtree=shutil.rmtree, move=shutil.move,
                                                which=shutil.which)
            with patch.object(runner, "shutil", fake_shutil):
                res = safe_run(inputs={"model": model}, timeout_s=30)
            check(res["ok"] is False and res["error"].startswith("input 'model' unreadable")
                  and res.get("outcome") == oc.CRASHED,
                  f"[1] vanished input -> ok False ({res['error']!r})")

            # [2]
            gone = dict(st, executable=str(tmp / "gone" / "blender"))
            with patch.object(runner, "status", lambda: gone):
                res = safe_run(inputs={"model": model}, timeout_s=30)
            check(res["ok"] is False and res["error"].startswith("blender could not be started")
                  and res.get("outcome") == oc.UNAVAILABLE,
                  f"[2] vanished binary -> unavailable ({res.get('outcome')}: {res['error']!r})")

            # [3]
            noexec = tmp / "noexec-blender"
            shutil.copy2(exe, noexec)
            noexec.chmod(0o644)
            with patch.object(runner, "status", lambda: dict(st, executable=str(noexec))):
                res = safe_run(inputs={"model": model}, timeout_s=30)
            check(res["ok"] is False and res["error"].startswith("blender could not be started")
                  and res.get("outcome") == oc.UNAVAILABLE,
                  f"[3] binary without +x -> unavailable ({res.get('outcome')}: {res['error']!r})")

            # [4]
            with patch.dict(os.environ, {"FAKE_MODE": "garbage"}):
                res = safe_run(inputs={"model": model}, timeout_s=30)
            check(res["ok"] is False and res["error"] == "script wrote no result (exit 1)"
                  and res.get("outcome") == oc.CRASHED,
                  f"[4] undecodable output, no result -> ok False ({res['error']!r})")

            # [5]
            with patch.dict(os.environ, {"FAKE_MODE": "garbage_ok"}):
                res = safe_run(inputs={"model": model}, timeout_s=30)
            check(res["ok"] is True and res.get("outcome") == oc.OK and res.get("log_tail") == "",
                  f"[5] undecodable output, result ok -> ok ({res.get('outcome')}: {res['error']!r})")

            # [6]
            cap.records.clear()
            with patch.dict(os.environ, {"FAKE_MODE": "hang"}):
                res = safe_run(inputs={"model": model}, timeout_s=1)
            check(res["ok"] is False and res["error"] == "timeout after 1s" and res.get("outcome") == oc.TIMEOUT,
                  f"[6] timeout -> timeout ({res.get('outcome')}: {res['error']!r})")
            check("TAIL-MARKER-6" in res.get("log_tail", ""), f"[6] log_tail carries the stderr ({res.get('log_tail')!r})")
            check("TAIL-MARKER-6" in blocks(log_file)[-1][1], "[6] the run's block carries the stderr")
            rec = next((r for r in cap.records if "timeout after 1s" in r), "")
            check("\n" not in rec and "timeout" in rec and str(log_file) in rec and "TAIL-MARKER-6" not in rec,
                  f"[6] main.log: one line naming the outcome and the log file ({rec!r})")

            # [7]
            with patch.dict(os.environ, {"FAKE_MODE": "reject"}):
                res = safe_run(inputs={"model": model}, timeout_s=30)
            check(res.get("outcome") == oc.REJECTED and res["error"] == "ValueError: REJECT-MARKER"
                  and res["data"] == {"why": "gate"} and "REJECT-MARKER" in res.get("log_tail", ""),
                  f"[7] script refusal -> rejected ({res.get('outcome')}: {res['error']!r})")

            # [8] [9]
            for n, mode, want, sig in ((8, "sigterm", oc.INTERRUPTED, 15), (9, "segv", oc.CRASHED, 11)):
                with patch.dict(os.environ, {"FAKE_MODE": mode}):
                    res = safe_run(inputs={"model": model}, timeout_s=30)
                check(res.get("outcome") == want and res["error"] == f"blender was killed by signal {sig}"
                      and "SIGNAL-MARKER" in res.get("log_tail", ""),
                      f"[{n}] {mode} -> {want} ({res.get('outcome')}: {res['error']!r})")

            # [10] [11]
            with patch.dict(os.environ, {"FAKE_MODE": "badjson"}):
                res = safe_run(inputs={"model": model}, timeout_s=30)
            check(res.get("outcome") == oc.CRASHED and res["error"].startswith("result unreadable"),
                  f"[10] unreadable result -> crashed ({res.get('outcome')}: {res['error']!r})")
            with patch.dict(os.environ, {"FAKE_MODE": "missing_output"}):
                res = safe_run(inputs={"model": model}, timeout_s=30, out_dir=tmp / "out11")
            check(res.get("outcome") == oc.CRASHED
                  and res["error"] == "declared output 'model' is missing: nope.glb",
                  f"[11] missing declared output -> crashed ({res.get('outcome')}: {res['error']!r})")

            # [12]
            before = len(blocks(log_file))

            def off(key, default):
                return False if key == "image_generation.blender_enabled" else config(key, default)
            with patch.object(runner, "_config", off):
                res = safe_run(inputs={"model": model}, timeout_s=30)
            check(res.get("outcome") == oc.UNAVAILABLE and res["error"] == "blender refinement is disabled",
                  f"[12] disabled -> unavailable ({res.get('outcome')}: {res['error']!r})")
            res = runner.run("no_such_script", inputs={"model": model})
            check(res.get("outcome") == oc.CRASHED and res["error"] == "unknown blender script: no_such_script",
                  f"[12] unknown script -> crashed ({res.get('outcome')}: {res['error']!r})")
            check(len(blocks(log_file)) == before, "[12] neither wrote a block (nothing ran)")

            # [13] [14]
            with patch.dict(os.environ, {"FAKE_MODE": "chatty_ok"}):
                res = safe_run(inputs={"model": model}, timeout_s=30)
            body = blocks(log_file)[-1][1]
            check(res.get("outcome") == oc.OK and res.get("log_tail") == ""
                  and len(body.encode()) <= runner.LOG_OK_BYTES + 10 and body.rstrip().endswith("LAST-STDERR-LINE"),
                  f"[13] chatty ok run: short block ({len(body.encode())} bytes), no log_tail")
            with patch.dict(os.environ, {"FAKE_MODE": "chatty_fail"}):
                res = safe_run(inputs={"model": model}, timeout_s=30)
            body = blocks(log_file)[-1][1]
            tail = res.get("log_tail", "")
            check(res.get("outcome") == oc.CRASHED and len(body.encode()) <= runner.LOG_FAILED_BYTES + 10
                  and len(body.encode()) > runner.LOG_OK_BYTES and body.rstrip().endswith("LAST-STDERR-LINE"),
                  f"[14] chatty failed run: capped block ({len(body.encode())} bytes)")
            check(len(tail.splitlines()) == runner.TAIL_LINES and len(tail.encode()) <= runner.TAIL_BYTES
                  and tail.splitlines()[-1] == "LAST-STDERR-LINE",
                  f"[14] log_tail: {len(tail.splitlines())} lines, {len(tail.encode())} bytes")

            # [15]
            got = blocks(log_file)
            want = [oc.OK, oc.CRASHED, oc.UNAVAILABLE, oc.UNAVAILABLE, oc.CRASHED, oc.OK, oc.TIMEOUT, oc.REJECTED,
                    oc.INTERRUPTED, oc.CRASHED, oc.CRASHED, oc.CRASHED, oc.OK, oc.CRASHED]
            heads = [h for h, _b in got]
            seen = [HEAD.match(h).group("outcome") if HEAD.match(h) else None for h in heads]
            check(seen == want, f"[15] {len(heads)} blocks, outcomes in run order ({seen})")
            check(bool(heads) and all(HEAD.match(h) and HEAD.match(h).group("pid") == str(os.getpid())
                                      and HEAD.match(h).group("script") == "meshopt" for h in heads),
                  f"[15] every header in the format ({heads[0] if heads else ''!r})")

            # [18]
            res = safe_run(inputs={"model": model}, timeout_s=30)
            check(res.get("ok") is True and 0.0 <= res.get("slot_wait_s", -1) < process_slots.SLOT_POLL_S,
                  f"[18] a free slot: slot_wait_s {res.get('slot_wait_s')!r} < {process_slots.SLOT_POLL_S}")
            held = [process_slots.try_slots(tmp / "slots", 2) for _ in range(2)]
            release = threading.Timer(1.0, lambda: [os.close(fd) for fd in held if fd is not None])
            release.start()
            res = safe_run(inputs={"model": model}, timeout_s=30)
            release.join()
            wait = res.get("slot_wait_s", -1)
            check(None not in held and res.get("ok") is True and 1.0 <= wait < 1.0 + 2 * process_slots.SLOT_POLL_S + 0.5
                  and res["seconds"] >= wait,
                  f"[18] both slots held 1 s: slot_wait_s {wait!r}, seconds {res.get('seconds')!r}")
        budget_cases()
        figure_cases()
    finally:
        runner.logger.removeHandler(cap)
        runner.LOG_FILE = saved_log
        runner.pin_slots(None, None)
        runner._version_cache.clear()
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{'FAILED: ' + str(len(FAILS)) if FAILS else 'all passed'}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
