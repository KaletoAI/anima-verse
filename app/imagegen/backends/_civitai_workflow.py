"""Shared driver for the CivitAI Orchestration v2 workflow API.

Both CivitAI backends (``civitai`` = images, ``civitai_video`` = image-to-video)
speak the same protocol: POST ``/v2/consumer/workflows`` with a list of steps,
poll ``GET /v2/consumer/workflows/{id}`` until the workflow resolves, then
download the output blobs through their signed URLs. Only the step payload
differs per backend, so the machinery lives here once (the counterpart of
``_gateway_job.py`` for the LLM gateway).

Spec: ``https://orchestration.civitai.com/openapi/v2-consumers.json``. Its
``WorkflowTemplate.required`` lists ``currencies`` — stale: the live API accepts
a workflow without it (checked 2026-09-30), so the body deliberately omits it.
The blue -> green -> yellow charging order and the upgrade failing on a too
low yellow balance come from the guide ("Submitting Work"), not the schema.

Failure semantics follow the busy/cooldown contract in ``base.py``:
  * mature content: ``allow_mature`` forces yellow Buzz (``allowMatureContent``);
    otherwise ``upgradeMode: automatic`` pays blue/green first and upgrades to
    yellow only for a result that turns out mature
  * submit answers 400/422 -> ``GatewayRejectedError`` (the INPUT was refused:
    no cooldown, no re-route; CivitAI's message reaches the caller)
  * submit answers 429/503 -> ``BackendBusyError`` (load)
  * submit answers 401/403 or anything else -> ``RuntimeError`` (defect ->
    cooldown + ``BackendFailedError`` -> the routing tries the next entry)
  * a blob carries ``blockedReason`` (moderation) -> ``GatewayRejectedError``,
    whatever the workflow status says — retrying the same input is pointless
  * workflow ends ``failed`` / ``expired`` / ``canceled`` -> ``RuntimeError``
  * the queue budget (``max_queue_wait``, while unassigned/preparing/scheduled)
    or the running budget (``max_wait``, from ``processing`` on) runs out ->
    the workflow is cancelled first (DELETE while queued, which refunds;
    PUT status=canceled once processing), then ``BackendBusyError``. A retry
    must not leave a paid job running in parallel.
  * the workflow is lost (3 consecutive 404 polls, or more than 10 other
    failed polls) -> cancelled best effort, ``None`` -> the backend returns
    ``[]`` (empty result = defect -> cooldown), exactly like ``poll_job``.

``selection.run_on_backend`` classifies ANY exception whose text matches
``_re_4xx`` (400/401/403/404/405/413/422, "Bad Request", "Unprocessable") as a
rejected payload — no cooldown, no re-route. So every DEFECT message raised
here is worded without an HTTP status number; the code is only logged.
"""
import base64
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from app.core.log import get_logger
from app.imagegen.base import BackendBusyError, GatewayRejectedError, ImageBackend

logger = get_logger("image_backends")

WORKFLOWS_PATH = "/v2/consumer/workflows"

# Workflow statuses (spec: WorkflowStatus).
QUEUED_STATUSES = ("unassigned", "preparing", "scheduled")
_RUNNING = "processing"
_SUCCEEDED = "succeeded"
_TERMINAL_FAILURES = ("failed", "expired", "canceled")

# Consecutive failed polls before the workflow counts as lost (same caps as
# _gateway_job.poll_job): a 404 means CivitAI no longer knows it -> bail fast;
# other failures (5xx / network) may be transient -> stay patient.
_MAX_CONSEC_404 = 3
_MAX_CONSEC_OTHER = 10

_MIME_BY_SUFFIX = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
                   "webp": "image/webp"}


def headers(api_key: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def image_input(backend: ImageBackend, src: str) -> str:
    """An image field value the API accepts ("Either A URL, A DataURL or a
    Base64 string"): http(s) and data: URIs pass through, a local file becomes
    a data URI. A missing file is a broken INPUT, not a broken backend ->
    ``GatewayRejectedError`` (no cooldown)."""
    src = str(src or "").strip()
    if src.startswith(("http://", "https://", "data:")):
        return src
    p = Path(src)
    if not src or not p.is_file():
        raise GatewayRejectedError(f"{backend.name}: source image missing: {src or '(none)'}")
    mime = _MIME_BY_SUFFIX.get(p.suffix.lower().lstrip("."), "image/png")
    return f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode("ascii")


def first_reference_image(params: Dict[str, Any]) -> str:
    """The first slotted reference image (``params['reference_images']`` maps
    slot title -> path/URL/data URI), skipping an inpaint mask; else
    ``source_image_path`` (the video handoff sets both). ``""`` = none."""
    refs = params.get("reference_images") or {}
    if isinstance(refs, dict):
        for title, path in refs.items():
            if path and title != "input_mask":
                return str(path)
    return str(params.get("source_image_path") or "")


def _error_text(resp: requests.Response) -> str:
    """CivitAI's validation message (``errors`` of the problem document), else
    the raw body — capped for the log and the exception."""
    try:
        body = resp.json()
    except ValueError:
        return (resp.text or "(empty)")[:300]
    if isinstance(body, dict):
        return json.dumps(body.get("errors") or body.get("detail") or body.get("title") or body)[:300]
    return str(body)[:300]


def submit(backend: ImageBackend, steps: List[Dict[str, Any]], *,
           allow_mature: bool) -> Dict[str, Any]:
    """POST the workflow; returns the workflow object (it carries ``id`` and a
    first ``status``). Raises per the module docstring."""
    body: Dict[str, Any] = {"steps": steps}
    if allow_mature:
        # Forces yellow Buzz for every workflow, mature or not.
        body["allowMatureContent"] = True
    else:
        # Pay with the cheapest currency (blue -> green -> yellow) and, only
        # when the result turns out mature, let CivitAI swap the charge to
        # yellow and deliver. The alternative ("manual") withholds a mature
        # result paid in blue/green — an output this app could never use, and
        # one that may read as a failed render (cooldown + re-route).
        body["upgradeMode"] = "automatic"
    try:
        resp = requests.post(f"{backend.api_url}{WORKFLOWS_PATH}", json=body,
                             headers=headers(backend.api_key), timeout=60)
    except requests.RequestException as e:
        raise RuntimeError(f"{backend.name}: workflow submit failed: {type(e).__name__}") from e
    code = resp.status_code
    if code in (200, 201, 202):
        try:
            wf = resp.json() if resp.content else {}
        except ValueError:
            raise RuntimeError(f"{backend.name}: workflow submit returned no JSON") from None
        if not isinstance(wf, dict) or not wf.get("id"):
            # A success without a workflow id is a broken answer (defect).
            raise RuntimeError(f"{backend.name}: workflow submit returned no workflow id")
        cost = (wf.get("cost") or {}).get("total")
        logger.info("%s: workflow %s submitted (status %s, cost %s Buzz)",
                    backend.name, wf["id"], wf.get("status"), cost)
        return wf
    if code in (400, 422):
        sent = [{k: v for k, v in (s.get("input") or {}).items() if not isinstance(v, str) or len(v) < 300}
                for s in steps]
        logger.error("%s: workflow rejected (HTTP %d): %s — sent (large values omitted): %s",
                     backend.name, code, _error_text(resp), json.dumps(sent)[:800])
        raise GatewayRejectedError(f"{backend.name}: request rejected by CivitAI: {_error_text(resp)}")
    if code in (429, 503):
        logger.warning("%s: CivitAI busy (HTTP %d)", backend.name, code)
        raise BackendBusyError(f"{backend.name}: CivitAI busy (rate limit / capacity)")
    logger.error("%s: workflow submit failed (HTTP %d): %s", backend.name, code, _error_text(resp))
    # No status number in the text — _re_4xx would turn a 401 into "payload error".
    if code in (401, 403):
        raise RuntimeError(f"{backend.name}: API key rejected (unauthorized)")
    kind = "client error" if 400 <= code < 500 else "server error"
    raise RuntimeError(f"{backend.name}: workflow submit failed ({kind})")


def _cancel(backend: ImageBackend, wf_id: str, status: str) -> None:
    """Best-effort cancel of a workflow we give up on. While it is still
    queued a DELETE refunds ("may trigger a refund if the work … has not yet
    started"); once processing only PUT status=canceled stops it."""
    url = f"{backend.api_url}{WORKFLOWS_PATH}/{wf_id}"
    try:
        if status in QUEUED_STATUSES:
            requests.delete(url, headers=headers(backend.api_key), timeout=15)
        else:
            requests.put(url, json={"status": "canceled"},
                         headers=headers(backend.api_key), timeout=15)
        logger.info("%s: workflow %s cancelled (was %s)", backend.name, wf_id, status or "?")
    except Exception as e:   # noqa: BLE001 — best effort
        logger.debug("%s: cancel of workflow %s failed: %s", backend.name, wf_id, e)


def output_blobs(wf: Dict[str, Any]) -> List[Dict[str, Any]]:
    """All output blobs of all steps: ``output.images[]`` (imageGen /
    textToImage) and ``output.video`` (videoGen)."""
    blobs: List[Dict[str, Any]] = []
    for step in wf.get("steps") or []:
        out = (step or {}).get("output") or {}
        for img in out.get("images") or []:
            if isinstance(img, dict):
                blobs.append(img)
        video = out.get("video")
        if isinstance(video, dict):
            blobs.append(video)
    return blobs


def _raise_if_blocked(backend: ImageBackend, wf: Dict[str, Any]) -> None:
    """Moderation lives on the blob (``Blob.blockedReason``). A blocked output
    is a verdict about the INPUT: never retry it, never re-route it."""
    for blob in output_blobs(wf):
        reason = blob.get("blockedReason")
        if reason:
            logger.error("%s: workflow %s output blocked by moderation: %s",
                         backend.name, wf.get("id"), reason)
            raise GatewayRejectedError(f"{backend.name}: output blocked by moderation ({reason})")


def run_workflow(backend: ImageBackend, steps: List[Dict[str, Any]], *,
                 allow_mature: bool, max_wait: float, max_queue_wait: float,
                 poll_interval: float) -> Optional[Dict[str, Any]]:
    """Submit ``steps`` and poll until the workflow resolves.

    Returns the succeeded workflow object, or ``None`` when the workflow got
    lost (the caller returns ``[]``). Raises per the module docstring.
    ``max_queue_wait`` budgets the queued phase, ``max_wait`` the running
    phase only — its clock starts at ``processing``. SYSTEM time throughout.
    """
    wf = submit(backend, steps, allow_mature=allow_mature)
    wf_id = str(wf["id"])
    queued_since = time.monotonic()
    running_since: Optional[float] = None
    misses_404 = 0
    misses_other = 0
    while True:
        status = str(wf.get("status") or "").lower()
        try:
            _raise_if_blocked(backend, wf)
        except GatewayRejectedError:
            if status not in (_SUCCEEDED, *_TERMINAL_FAILURES):
                # Blocked while still running: stop paying for the rest.
                _cancel(backend, wf_id, status)
            raise
        if status == _SUCCEEDED:
            took = time.monotonic() - (running_since or queued_since)
            logger.info("%s: workflow %s succeeded (%.0fs)", backend.name, wf_id, took)
            return wf
        if status in _TERMINAL_FAILURES:
            logger.error("%s: workflow %s ended '%s': %s", backend.name, wf_id, status,
                         json.dumps(wf.get("steps"))[:400])
            raise RuntimeError(f"{backend.name}: workflow ended '{status}'")
        now = time.monotonic()
        if status == _RUNNING and running_since is None:
            running_since = now
            logger.info("%s: workflow %s processing (%.0fs queued)", backend.name,
                        wf_id, now - queued_since)
        if running_since is not None and now - running_since >= max_wait:
            logger.warning("%s: workflow %s still processing after %.0fs — cancelling",
                           backend.name, wf_id, now - running_since)
            _cancel(backend, wf_id, status)
            raise BackendBusyError(f"{backend.name}: polling timeout after {max_wait:.0f}s")
        if running_since is None and now - queued_since >= max_queue_wait:
            logger.warning("%s: workflow %s queued for %.0fs — cancelling",
                           backend.name, wf_id, now - queued_since)
            _cancel(backend, wf_id, status)
            raise BackendBusyError(f"{backend.name}: queued longer than {max_queue_wait:.0f}s")

        time.sleep(poll_interval)
        try:
            resp = requests.get(f"{backend.api_url}{WORKFLOWS_PATH}/{wf_id}",
                                headers=headers(backend.api_key), timeout=30)
        except requests.RequestException as e:
            resp = None
            logger.debug("%s: poll of workflow %s failed: %s", backend.name, wf_id, e)
        code = resp.status_code if resp is not None else 0
        if code in (200, 202):   # the spec lists both for GET /workflows/{id}
            try:
                polled = resp.json()
            except ValueError:
                polled = None
            if isinstance(polled, dict):
                wf = polled
                misses_404 = misses_other = 0
                continue
        if code == 404:
            misses_404 += 1
        else:
            misses_other += 1
        if misses_404 >= _MAX_CONSEC_404 or misses_other > _MAX_CONSEC_OTHER:
            logger.error("%s: workflow %s lost (%d not-found, %d failed polls, last HTTP %s) "
                         "— giving up", backend.name, wf_id, misses_404, misses_other, code)
            _cancel(backend, wf_id, status)
            return None


def download_blobs(backend: ImageBackend, wf: Dict[str, Any]) -> List[bytes]:
    """Download every output blob of a succeeded workflow. The signed URLs
    expire, so this runs right after the poll. ``[]`` (defect) when a blob has
    no URL, is not available or the download fails; a blocked blob raises."""
    _raise_if_blocked(backend, wf)
    blobs = output_blobs(wf)
    if not blobs:
        logger.error("%s: workflow %s succeeded without output", backend.name, wf.get("id"))
        return []
    out: List[bytes] = []
    for blob in blobs:
        url = blob.get("url")
        if not url or blob.get("available") is False:
            logger.error("%s: output blob %s not available (url=%s)", backend.name,
                         blob.get("id"), bool(url))
            return []
        try:
            resp = requests.get(url, timeout=120)
        except requests.RequestException as e:
            logger.error("%s: download of blob %s failed: %s", backend.name, blob.get("id"), e)
            return []
        if resp.status_code != 200 or not resp.content:
            logger.error("%s: download of blob %s failed (HTTP %d)", backend.name,
                         blob.get("id"), resp.status_code)
            return []
        out.append(resp.content)
    logger.info("%s: %d output blob(s) downloaded (%d bytes)", backend.name, len(out),
                sum(len(b) for b in out))
    return out
