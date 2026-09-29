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
  * a started job fails with "park timeout" / "backend busy" ->
    ``BackendBusyError`` (load, no cooldown)
  * gateway loses the job (repeated 404) or keeps failing the poll (5xx /
    network) -> ``[]`` (the job is gone/broken -> cooldown is correct)

The lost-job caps are the point of this module: a gateway restart makes
``/v1/jobs/{id}`` answer 404 forever, and without a cap the worker polls until
``max_queue_wait`` (an hour by default), pinning the serialized backend channel
(video) or leaving a character stuck in ``_generating`` (mesh).
"""
import re
import time
from typing import Any, Callable, Dict, List

import requests

from app.core.log import get_logger
from app.imagegen.base import (GATEWAY_503_FLAP_WAITS_S, BackendBusyError,
                               GatewayInputMismatchError, GatewayRejectedError,
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
               kind: str) -> str:
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
    """
    resp = None
    busy_attempts = 0
    flaps = 0
    while True:
        try:
            resp = requests.post(url, json=payload, headers=backend._headers(),
                                 timeout=backend.timeout)
        except Exception as e:
            logger.error("%s: connection error: %s", backend.name, e)
            return ""
        code = resp.status_code
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
        return ""
    return job_id


def poll_job(backend: ImageBackend, job_id: str, *,
             max_wait: int, max_queue_wait: int, poll_interval: float,
             on_done: Callable[[Dict[str, Any], float], List[bytes]]
             ) -> List[bytes]:
    """Poll ``/v1/jobs/{job_id}`` until the job resolves or a budget runs out.

    ``max_wait`` budgets the RUNNING time only; time spent queued at the gateway
    is capped separately by ``max_queue_wait`` (a queued job means the GPU is
    busy elsewhere — cancelling it early turns a busy phase into a cascade of
    cooldowns). ``on_done(status_dict, running_seconds)`` downloads and returns
    the result blobs for a completed job (``[]`` on a download error).

    Returns the result blobs (or ``[]``). Raises ``BackendBusyError`` when the
    job runs or waits past its budget (load, no cooldown). A lost job — 3
    consecutive 404s, or more than 10 other failed polls — returns ``[]``
    (gone/broken -> cooldown is correct).
    """
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
        try:
            poll = requests.get(f"{backend.api_url}/v1/jobs/{job_id}",
                                headers=backend._headers(), timeout=30)
            if poll.status_code != 200:
                if poll.status_code == 404:
                    misses_404 += 1
                    if misses_404 >= _MAX_CONSEC_404:
                        logger.error("%s: Job %s %d× in Folge 404 — Gateway kennt "
                                     "den Job nicht mehr, Abbruch", backend.name,
                                     job_id, misses_404)
                        return []
                else:
                    misses_other += 1
                    if misses_other > _MAX_CONSEC_OTHER:
                        logger.error("%s: Job %s %d fehlgeschlagene Polls in Folge "
                                     "(zuletzt HTTP %d) — Abbruch", backend.name,
                                     job_id, misses_other, poll.status_code)
                        return []
                logger.debug("%s: Job-Poll HTTP %d", backend.name, poll.status_code)
                continue
            # A usable status resets the lost-job counters.
            misses_404 = 0
            misses_other = 0
            sd = poll.json() if poll.content else {}
            status = (sd.get("status") or "").lower() if isinstance(sd, dict) else ""
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
        except (GatewayRejectedError, GatewayInputMismatchError, BackendBusyError):
            # A verdict about the INPUT (or a job that parked out on load) —
            # raised above or by ``on_done`` — not a failed poll. Counting it
            # as one would keep polling a job that is already decided.
            raise
        except Exception as e:
            misses_other += 1
            if misses_other > _MAX_CONSEC_OTHER:
                logger.error("%s: Job %s %d fehlgeschlagene Polls in Folge "
                             "(zuletzt %s) — Abbruch", backend.name, job_id,
                             misses_other, e)
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
