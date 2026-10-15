"""Shared async-job driver for the LLM-gateway generation backends.

Both ``openai_video`` and ``openai_mesh`` drive the identical gateway async
protocol: POST to ``/v1/generations`` (honouring Retry-After on 429/503) to get
a ``job_id``, then poll ``/v1/jobs/{id}`` until the job is done, failed, or a
time budget runs out. Only the request payload and the result download differ
per media type — those stay in the backend (payload built by the caller, the
download passed in as ``on_done``); the machinery lives here so the two backends
cannot drift apart. (They already had: the poll loop was copied, and only one
copy would ever get a fix.)

Failure semantics mirror the busy/cooldown contract in ``base.py``:
  * gateway stays busy (429 / 503 WITH Retry-After) after the POST retries
    -> ``BackendBusyError`` (load, no cooldown)
  * 503 WITHOUT Retry-After (alias has no healthy backend) -> retried across
    the health flap, then ``RuntimeError`` (defect -> cooldown)
  * job runs longer than ``max_wait`` / sits queued longer than
    ``max_queue_wait`` -> ``BackendBusyError`` (load, no cooldown)
  * gateway rejects the payload (400/413) or a started job dies on an INPUT
    error -> ``GatewayRejectedError`` (terminal, no cooldown — the reason is
    the client's, not the backend's)
  * a gateway-side cancelled job -> ``GenerationCancelled`` (terminal,
    no retry, fallback or cooldown)
  * a started job fails with "park timeout" / "backend busy" ->
    ``BackendBusyError`` (load, no cooldown)
  * gateway loses the job (repeated 404) or keeps failing the poll (5xx /
    network) -> ``[]`` (the job is gone/broken -> cooldown is correct); the
    job is cancelled first (best effort), because a routed re-run starts the
    same work on the next backend and must not leave this one running

The lost-job caps are the point of this module: a gateway restart makes
``/v1/jobs/{id}`` answer 404 forever, and without a cap the worker polls until
``max_queue_wait`` (an hour by default), pinning the serialized backend channel
(video) or leaving a character stuck in ``_generating`` (mesh).
"""
import re
import time
from typing import Any, Callable, Dict, List, Optional

import requests

from app.core.log import get_logger
from app.imagegen.base import (GATEWAY_503_FLAP_WAITS_S, BackendBusyError,
                               GatewayInputMismatchError, GatewayRejectedError, GatewayOutputError,
                               GenerationCancelled, HubJobLost,
                               ImageBackend, is_gateway_busy_502,
                               retry_after_seconds)

logger = get_logger("image_backends")

# Consecutive failed polls (reset by any successful poll) before the job counts
# as lost. A 404 means the gateway forgot the job -> bail fast; other failures
# (5xx / network) may be transient -> stay patient.
_MAX_CONSEC_404 = 3
_MAX_CONSEC_OTHER = 10

# Statuses that mean "this request will never work": the gateway rejected the
# payload itself (400 = unknown files key / unreadable value, 413 = file over
# 64 MB, mesh-client-spec § 1). Retrying is pointless and the reason must
# reach the caller instead of dying in the log — a swallowed rejection looks
# exactly like a mesh backend that produced nothing.
_TERMINAL_STATUSES = (400, 413)

# A STARTED job can fail on the input just as terminally: the re-bake node of
# the mesh→mesh chain reads the input mesh's texture, and a mesh that carries
# none (vertex colours only, no UVs) makes it receive nothing. The gateway
# reports that as a per-node error — matched on the meaningful part, since the
# node number and the node's class name are not ours to depend on. It says
# "wrong input", never "broken backend": no cooldown, and a retry is pointless
# (mesh-client-spec § 3.3/3.4).
_TERMINAL_JOB_ERROR = re.compile(r"expected\s+np\.ndarray.*?NoneType",
                                 re.IGNORECASE | re.DOTALL)
_TERMINAL_JOB_HINT = ("the input mesh has no UVs/texture, so the re-bake step "
                      "got nothing to read — permanent, a retry cannot help")


def submit_job(backend: ImageBackend, url: str, payload: Dict[str, Any],
               kind: str, *, stage: Any = None,
               attach_params: Optional[Dict[str, Any]] = None) -> str:
    """POST the async job and return its ``job_id`` ("" on a logged failure).

    Retries the POST up to 3× on 429 and on a 503 WITH ``Retry-After`` (queue
    full; header honoured, capped at 120 s); if the gateway is still busy
    afterwards raises ``BackendBusyError`` (load, not a defect). A 503 WITHOUT
    ``Retry-After`` means the alias has no healthy backend: retried across the
    gateway's health flap (``GATEWAY_503_FLAP_WAITS_S``), then ``RuntimeError`` (defect -> cooldown in the backend
    runner). A 502 "park timeout"/"backend busy" is load as well. A 400/413 is
    the opposite — the payload itself was rejected — and raises
    ``GatewayRejectedError`` so the reason surfaces.
    ``kind`` is a short label for the error log (e.g. "Video" / "Mesh").

    ``stage`` is the operation's hub-stage handle (``app.core.hub_ops``,
    ``params["hub_stage"]``) or None. It is told ``posting`` right before
    every POST, ``not_posted`` when the gateway answered without taking the
    job, and ``submitted`` with the job id the moment we have it — together
    with ``attach_params``, what ``backend.attach`` needs to collect the job
    after a restart (input hashes, variant count). A POST whose answer never
    arrived (connection error) stays ``posting``: whether the gateway took it
    is unknown, and that window is the documented submission gap.
    """
    resp = None
    busy_attempts = 0
    flaps = 0
    while True:
        if stage is not None:
            stage.posting(backend)
        try:
            resp = requests.post(url, json=payload, headers=backend._headers(),
                                 timeout=backend.timeout)
        except Exception as e:
            logger.error("%s: connection error: %s", backend.name, e)
            return ""
        code = resp.status_code
        if stage is not None and code not in (200, 201, 202):
            # An HTTP answer that is not an acceptance: the gateway holds no
            # job for this POST.
            stage.not_posted()
        retry_after = retry_after_seconds(resp)
        if code == 503 and retry_after is None:
            # No healthy backend for the alias — retried across the gateway's
            # health flap, a defect (not load) once it outlasts it.
            if flaps < len(GATEWAY_503_FLAP_WAITS_S):
                wait_s = GATEWAY_503_FLAP_WAITS_S[flaps]
                flaps += 1
                logger.warning("%s: HTTP 503 without Retry-After (no healthy "
                               "backend) — retry in %.0fs (%d/%d)", backend.name,
                               wait_s, flaps, len(GATEWAY_503_FLAP_WAITS_S))
                time.sleep(wait_s)
                continue
            raise RuntimeError(
                f"{backend.name}: HTTP 503 — alias has no healthy backend: "
                f"{(resp.text or '').strip()[:300]}")
        if code in (429, 503):
            busy_attempts += 1
            if busy_attempts >= 3:
                # Retries exhausted while the gateway kept answering busy —
                # that is load, not a defect (no cooldown).
                raise BackendBusyError(
                    f"{backend.name}: HTTP {code} (gateway busy) after 3 attempts")
            wait_s = min(120.0, retry_after if retry_after is not None else 10.0)
            logger.info("%s: Gateway busy (HTTP %d) — retry in %.0fs",
                        backend.name, code, wait_s)
            time.sleep(wait_s)
            continue
        if code == 502 and is_gateway_busy_502(resp.text or ""):
            raise BackendBusyError(
                f"{backend.name}: HTTP 502 (gateway park timeout): "
                f"{(resp.text or '').strip()[:300]}")
        break
    if resp is not None and resp.status_code in _TERMINAL_STATUSES:
        detail = (resp.text or "").strip()[:300]
        logger.error("%s: %s request rejected (HTTP %d) - %s", backend.name,
                     kind, resp.status_code, detail)
        raise GatewayRejectedError(
            f"{backend.name}: HTTP {resp.status_code} — {detail or 'request rejected'}")
    if resp is None or resp.status_code not in (200, 201, 202):
        logger.error("%s: %s request HTTP %s - %s", backend.name, kind,
                     getattr(resp, "status_code", "?"),
                     (resp.text[:300] if resp is not None else ""))
        return ""
    body = resp.json() if resp.content else {}
    job_id = str(body.get("job_id") or body.get("id") or "") \
        if isinstance(body, dict) else ""
    if not job_id:
        logger.error("%s: no job_id in response: %s", backend.name,
                     str(body)[:200])
        if stage is not None:
            stage.not_posted()
        return ""
    if stage is not None:
        stage.submitted(backend, job_id, dict(attach_params or {}))
    return job_id


def stage_kwargs(params: Dict[str, Any],
                 attach_params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The ``submit_job`` keywords of a run: the hub-stage handle from
    ``params["hub_stage"]`` plus the attach params — and NOTHING when the run
    has no stage, so a plain generation calls ``submit_job`` exactly as
    before (E4)."""
    stage = (params or {}).get("hub_stage")
    if stage is None:
        return {}
    return {"stage": stage, "attach_params": dict(attach_params or {})}


def stage_cancel(params: Dict[str, Any]) -> Optional[Callable[[], bool]]:
    """The cancel check of the run's hub operation — set only on a RESUMED
    operation (its display row's cancel button, spec D6); None otherwise, so
    a normal run polls exactly as before."""
    stage = (params or {}).get("hub_stage")
    op = getattr(stage, "op", None)
    return getattr(op, "should_cancel", None)


def _cancel_lost_job(backend: ImageBackend, job_id: str) -> None:
    """Best-effort ``POST /v1/jobs/{id}/cancel`` for a job we give up on.

    A lost job may still be running on the gateway (a flapping poll, not a
    forgotten job): with image routing the caller re-runs the same mesh or
    video on the next chain entry, and the abandoned job would keep a GPU busy
    for nothing. Never raises — the verdict ("lost") stands either way."""
    try:
        requests.post(f"{backend.api_url}/v1/jobs/{job_id}/cancel",
                      headers=backend._headers(), timeout=10)
    except Exception as e:                                  # noqa: BLE001
        logger.debug("%s: cancel of lost job %s failed: %s", backend.name,
                     job_id, e)


def poll_job(backend: ImageBackend, job_id: str, *,
             max_wait: int, max_queue_wait: int, poll_interval: float,
             on_done: Callable[[Dict[str, Any], float], List[bytes]],
             should_cancel: Optional[Callable[[], bool]] = None,
             attach_since: Optional[float] = None
             ) -> List[bytes]:
    """Poll ``/v1/jobs/{job_id}`` until the job resolves or a budget runs out.

    ``max_wait`` budgets the RUNNING time only; time spent queued at the gateway
    is capped separately by ``max_queue_wait`` (a queued job means the GPU is
    busy elsewhere — cancelling it early turns a busy phase into a cascade of
    cooldowns). ``on_done(status_dict, running_seconds)`` downloads and returns
    the result blobs for a completed job (``[]`` on a download error).
    ``should_cancel`` is checked after each poll sleep; a true result cancels
    the job best effort and raises ``GenerationCancelled(job_id)``.

    Returns the result blobs (or ``[]``). Raises ``BackendBusyError`` when the
    job runs or waits past its budget (load, no cooldown). A lost job — 3
    consecutive 404s, or more than 10 other failed polls — is cancelled
    (best effort, ``_cancel_lost_job``) and returns ``[]`` (gone/broken ->
    cooldown is correct).

    ``attach_since`` (SYSTEM epoch seconds of the original submission)
    switches to ATTACH semantics — collecting a job recorded before a restart
    (``_poll_attached``). Without it the behaviour above is unchanged.
    """
    if attach_since is not None:
        return _poll_attached(backend, job_id, since=float(attach_since),
                              budget_s=float(max_queue_wait) + float(max_wait),
                              poll_interval=poll_interval, on_done=on_done,
                              should_cancel=should_cancel)
    start = time.time()
    queued_since = start
    started = False
    misses_404 = 0
    misses_other = 0
    while True:
        if started:
            if time.time() - start > max_wait:
                break
        elif time.time() - queued_since > max_queue_wait:
            logger.warning("%s: Job %s wartet seit %.0fs in der Gateway-Queue "
                           "— Abbruch", backend.name, job_id,
                           time.time() - queued_since)
            break
        time.sleep(poll_interval)
        if should_cancel is not None and should_cancel():
            logger.info("%s: job %s cancelled by the caller", backend.name, job_id)
            _cancel_lost_job(backend, job_id)
            raise GenerationCancelled(job_id)
        try:
            poll = requests.get(f"{backend.api_url}/v1/jobs/{job_id}",
                                headers=backend._headers(), timeout=30)
            if poll.status_code != 200:
                if poll.status_code == 410:
                    raise GatewayRejectedError(f"{backend.name}: job {job_id} is no longer retrievable (HTTP 410)")
                if poll.status_code == 404:
                    misses_404 += 1
                    if misses_404 >= _MAX_CONSEC_404:
                        logger.error("%s: job %s answered 404 %d times in a "
                                     "row — the gateway no longer knows it, "
                                     "giving up", backend.name, job_id,
                                     misses_404)
                        raise GatewayRejectedError(f"{backend.name}: job {job_id} is no longer retrievable (HTTP 404)")
                else:
                    misses_other += 1
                    if misses_other > _MAX_CONSEC_OTHER:
                        logger.error("%s: job %s: %d failed polls in a row "
                                     "(last HTTP %d) — giving up", backend.name,
                                     job_id, misses_other, poll.status_code)
                        _cancel_lost_job(backend, job_id)
                        return []
                logger.debug("%s: Job-Poll HTTP %d", backend.name, poll.status_code)
                continue
            # A usable status resets the lost-job counters.
            misses_404 = 0
            misses_other = 0
            sd = poll.json() if poll.content else {}
            status = (sd.get("status") or "").lower() if isinstance(sd, dict) else ""
            if status == "cancelled":
                raise GenerationCancelled(job_id)
            if status in ("failed", "error"):
                detail = str(sd.get("error") or sd)
                if _TERMINAL_JOB_ERROR.search(detail):
                    logger.error("%s: Job %s scheiterte am EINGANG, nicht am "
                                 "Backend — %s (%s)", backend.name, job_id,
                                 _TERMINAL_JOB_HINT, detail[:200])
                    raise GatewayRejectedError(
                        f"{backend.name}: {_TERMINAL_JOB_HINT} — {detail[:200]}")
                if is_gateway_busy_502(detail):
                    # The gateway gave up waiting for a GPU (park timeout /
                    # backend busy): load, not a defect — no cooldown.
                    logger.warning("%s: Job %s failed on load: %s",
                                   backend.name, job_id, detail[:300])
                    raise BackendBusyError(
                        f"{backend.name}: job {job_id} parked out: {detail[:200]}")
                logger.error("%s: Job %s failed: %s", backend.name, job_id,
                             detail[:300])
                return []
            if status == "running" and not started:
                # The GPU took the job — only now does max_wait start.
                started = True
                start = time.time()
                logger.info("%s: Job %s gestartet (%.0fs in der Queue)",
                            backend.name, job_id, start - queued_since)
            if status == "running" and sd.get("progress") is not None:
                # progress + elapsed_s are what the job view offers for
                # logging (mesh-client-spec § 1) — mesh jobs run for minutes.
                logger.info("%s: Job %s laeuft — %.0f%% (%ss)", backend.name,
                            job_id, float(sd.get("progress") or 0) * 100,
                            sd.get("elapsed_s", "?"))
            if status in ("done", "completed"):
                return on_done(sd, time.time() - start)
            # queued / running → keep waiting
        except (GatewayRejectedError, GatewayInputMismatchError, BackendBusyError, GenerationCancelled, GatewayOutputError, HubJobLost):
            # A verdict about the INPUT (or a job that parked out on load) —
            # raised above or by ``on_done`` — not a failed poll. Counting it
            # as one would keep polling a job that is already decided.
            raise
        except Exception as e:
            misses_other += 1
            if misses_other > _MAX_CONSEC_OTHER:
                logger.error("%s: job %s: %d failed polls in a row "
                             "(last %s) — giving up", backend.name, job_id,
                             misses_other, e)
                _cancel_lost_job(backend, job_id)
                return []
            logger.warning("%s: Poll-Fehler: %s", backend.name, e)
            continue
    logger.error("%s: Job %s abgebrochen (%s)", backend.name, job_id,
                 f"laeuft laenger als {max_wait}s" if started
                 else "kam nicht aus der Gateway-Queue")
    try:
        requests.post(f"{backend.api_url}/v1/jobs/{job_id}/cancel",
                      headers=backend._headers(), timeout=10)
    except Exception:
        pass
    # Load, not a defect -> no cooldown (the fallback engine reads this).
    raise BackendBusyError("timeout" if started else "gateway queue")


# Attach mode (a job recorded before a restart). The gateway keeps a job for
# its default TTL of 24 h; after that it answers 404, so an older record is
# lost without asking.
ATTACH_MAX_AGE_S = 24 * 3600
# An unreachable gateway is not a lost job: polls back off up to this pause.
_ATTACH_MAX_PAUSE_S = 30.0
# A finished job whose results do not download this many times in a row is lost.
_ATTACH_MAX_EMPTY = 10


def _poll_attached(backend: ImageBackend, job_id: str, *, since: float,
                   budget_s: float, poll_interval: float,
                   on_done: Callable[[Dict[str, Any], float], List[bytes]],
                   should_cancel: Optional[Callable[[], bool]] = None
                   ) -> List[bytes]:
    """Collect an EXISTING job after a restart (hub-job resume spec § 3.4).

    LOST (``HubJobLost``, terminal — never a resubmission): 410, three 404 in
    a row, 401/403 (the job is not readable with this key), the job failed or
    was cancelled on the gateway, the record is older than 24 h, a job still
    QUEUED or RUNNING past its time budget (``since + max_queue_wait +
    max_wait``), or a finished job's results did not download
    ``_ATTACH_MAX_EMPTY`` times. UNREACHABLE (connection error, 5xx, an
    unreadable body) is not lost: the poll backs off up to 30 s and keeps
    asking until the 24 h are over — the budget never applies to it, and
    never to a job that is already done.

    The first poll goes out at once and always goes out — a job that finished
    while we were down is collected without waiting, however long Anima was
    away (within the 24 h). No GPU slot and no master switch: nothing is
    generated, the job already ran."""
    deadline = since + min(max(0.0, budget_s), ATTACH_MAX_AGE_S)
    pause = max(0.5, float(poll_interval))
    misses_404 = 0
    empty = 0
    first = True
    while True:
        if not first:
            if time.time() - since > ATTACH_MAX_AGE_S:
                raise HubJobLost(f"{backend.name}: job {job_id} is older than 24 h "
                                 f"(gateway retention)")
            time.sleep(pause)
        first = False
        if should_cancel is not None and should_cancel():
            logger.info("%s: job %s cancelled by the caller", backend.name, job_id)
            _cancel_lost_job(backend, job_id)
            raise GenerationCancelled(job_id)
        try:
            poll = requests.get(f"{backend.api_url}/v1/jobs/{job_id}",
                                headers=backend._headers(), timeout=30)
        except requests.RequestException as e:
            pause = min(_ATTACH_MAX_PAUSE_S, pause * 2)
            logger.warning("%s: job %s unreachable (%s) — next poll in %.0fs",
                           backend.name, job_id, e, pause)
            continue
        code = poll.status_code
        if code == 410:
            raise HubJobLost(f"{backend.name}: job {job_id} is no longer "
                             f"retrievable (HTTP 410)")
        if code == 404:
            misses_404 += 1
            if misses_404 >= _MAX_CONSEC_404:
                raise HubJobLost(f"{backend.name}: the gateway no longer knows "
                                 f"job {job_id} (HTTP 404)")
            continue
        if code in (401, 403):
            raise HubJobLost(f"{backend.name}: job {job_id} is not readable "
                             f"with this backend's key (HTTP {code})")
        if code != 200:
            pause = min(_ATTACH_MAX_PAUSE_S, pause * 2)
            logger.warning("%s: job %s poll HTTP %d — next poll in %.0fs",
                           backend.name, job_id, code, pause)
            continue
        misses_404 = 0
        try:
            sd = poll.json() if poll.content else {}
        except ValueError:
            sd = {}
        if not isinstance(sd, dict):
            sd = {}
        status = str(sd.get("status") or "").lower()
        if status == "cancelled":
            raise HubJobLost(f"{backend.name}: job {job_id} was cancelled on "
                             f"the gateway")
        if status in ("failed", "error"):
            detail = str(sd.get("error") or "no reason given")[:200]
            raise HubJobLost(f"{backend.name}: job {job_id} failed on the "
                             f"gateway: {detail}")
        if status not in ("done", "completed"):
            if status in ("queued", "running") and time.time() > deadline:
                _cancel_lost_job(backend, job_id)
                raise HubJobLost(f"{backend.name}: job {job_id} did not finish "
                                 f"within its time budget")
            pause = max(0.5, float(poll_interval))
            if status == "running" and sd.get("progress") is not None:
                logger.info("%s: job %s running (collect after restart) — "
                            "%.0f%%", backend.name, job_id,
                            float(sd.get("progress") or 0) * 100)
            continue
        try:
            blobs = on_done(sd, float(sd.get("elapsed_s") or 0))
        except requests.RequestException as e:
            blobs = []
            logger.warning("%s: job %s result download unreachable: %s",
                           backend.name, job_id, e)
        if blobs:
            return blobs
        empty += 1
        if empty >= _ATTACH_MAX_EMPTY:
            raise HubJobLost(f"{backend.name}: the results of job {job_id} "
                             f"could not be downloaded")
        pause = min(_ATTACH_MAX_PAUSE_S, pause * 2)


class _NoNetrcAuth(requests.auth.AuthBase):
    """Preserve explicit headers while suppressing ambient netrc credentials."""

    def __call__(self, request):
        return request


def download_result(backend: ImageBackend, url: str, *, timeout=300, foreign="refuse"):
    """Validate every hop; never restore credentials after a foreign origin."""
    if foreign not in ("refuse", "anonymous"):
        raise ValueError("Unknown foreign-origin download policy")
    from urllib.parse import urljoin, urlparse
    def origin(value):
        parsed = urlparse(value)
        if (parsed.username is not None or parsed.password is not None
                or not parsed.hostname or parsed.scheme not in ("http", "https")):
            raise GatewayRejectedError("Invalid gateway result URL")
        port = parsed.port if parsed.port is not None else (443 if parsed.scheme == "https" else 80)
        hostname = parsed.hostname
        try:
            hostname = hostname.encode("idna").decode("ascii")
        except UnicodeError:
            # Invalid IDNs remain distinct; Requests will reject them on send.
            pass
        return parsed.scheme.lower(), hostname.lower(), port
    expected = origin(backend.api_url)
    authenticated = True
    for _ in range(6):
        if origin(url) != expected:
            if foreign == "refuse":
                raise GatewayRejectedError("Gateway result URL has a foreign origin; download refused")
            authenticated = False
        # Verified in installed Requests Session.prepare_request: netrc lookup
        # checks auth/trust_env, NOT Authorization headers. Explicit no-op auth
        # protects the backend Bearer too, while retaining environment proxies.
        # requests.get creates a fresh Session per hop, so cookies cannot carry.
        response = requests.get(url, headers=backend._headers() if authenticated else None,
                                timeout=timeout, allow_redirects=False, auth=_NoNetrcAuth())
        if response.status_code not in (301, 302, 303, 307, 308):
            return response
        url = urljoin(url, response.headers.get("Location", ""))
    raise GatewayRejectedError("Too many gateway result redirects")
