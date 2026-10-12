"""Text-to-motion through the gateway generations/jobs API.

What differs between motion models is configuration on the backend entry,
never a model name in code (spec plan-pose-animation-unimate.md §13 E8):
which file goes up (the puppet GLB or the reference-rig FBX) and under which
alias slot, which caption style the LLM writes, which alias parameter carries
the variant count and the segment duration, and the provenance stamped on a
published clip. One run may return several variants; every result is
verified on its own and reported in ``last_result_meta``.
"""
import base64
import hashlib
import json
import os
import re
import struct
import threading
from pathlib import Path
from typing import Dict, List

import requests

from app.core.log import get_logger
from app.imagegen.backends._gateway_job import poll_job, submit_job
from app.imagegen.base import ImageBackend

logger = get_logger("image_backends")
UPLOAD_MAX_BYTES = 64 * 1024 * 1024
GLB_MIME = "model/gltf-binary"
FBX_MAGIC = b"Kaydara FBX Binary"
RESULT_MIMES = (GLB_MIME, "model/fbx", "application/octet-stream")
MOTION_SOURCES = ("puppet", "reference_rig")
CAPTION_STYLES = ("object", "person")
VARIANT_CAP = 4
# Defaults = the UniMate entry this backend type was built for.
DEFAULT_LICENSE = "CC-BY-NC-4.0"
DEFAULT_GENERATOR = "unimate"
DEFAULT_MODEL_REVISION = "174fc755ec248d0c98f27759b7a95648e7f05905"
DEFAULT_CREDIT = ("UniMate: Linzhan Mou, Jiahui Lei, Zhiyang Dou, Chenyue Cai, Chaoyue Song, "
                  "Adam Finkelstein, Szymon Rusinkiewicz. Checkpoints © 2026 Linzhan Mou.")


def _choice(value: str, allowed, default: str, name: str, field: str) -> str:
    if value in allowed:
        return value
    if value:
        logger.warning("%s: %s %r unknown, using %r", name, field, value, default)
    return default


def _number(raw: str, cast, default, name: str, field: str):
    try:
        return cast(raw) if raw not in ("", None) else default
    except ValueError:
        logger.warning("%s: %s %r is not a number, using %r", name, field, raw, default)
        return default


class OpenAIMeshAnimationBackend(ImageBackend):
    """Text-to-motion on an existing rigged GLB (gateway alias mesh-unimate)."""

    MEDIA_TYPE = "animation"

    def __init__(self, name: str, api_url: str, cost: float, env_prefix: str):
        super().__init__(name, api_url, cost, api_type="openai_mesh_animation",
                         env_prefix=env_prefix)
        self.api_key = os.environ.get(f"{env_prefix}API_KEY", "").strip()
        self.model = os.environ.get(f"{env_prefix}MODEL", "").strip()
        self.timeout = int(os.environ.get(f"{env_prefix}TIMEOUT", "120") or 120)
        self.poll_interval = float(os.environ.get(f"{env_prefix}POLL_INTERVAL", "5.0") or 5.0)
        self.max_wait = int(os.environ.get(f"{env_prefix}MAX_WAIT", "900") or 900)
        self.max_queue_wait = int(
            os.environ.get(f"{env_prefix}MAX_QUEUE_WAIT", "0") or 0) or self.max_wait * 4
        self.mesh_endpoint = (os.environ.get(f"{env_prefix}MESH_ENDPOINT", "")
                              or "/v1/generations").strip().rstrip("/")
        extra = json.loads(os.environ.get(f"{env_prefix}EXTRA_PARAMS", "") or "{}")
        self.extra_params = {k: v for k, v in extra.items()
                             if k in ("input_cfg_scale", "input_chain_overlap")}
        if not self.category:
            self.category = "mesh2anim"
        env = lambda key: os.environ.get(f"{env_prefix}{key}", "").strip()
        self.motion_source = _choice(env("MOTION_SOURCE"), MOTION_SOURCES, "puppet",
                                     name, "motion_source")
        self.source_slot = env("SOURCE_SLOT") or "input_mesh_path"
        self.caption_style = _choice(env("CAPTION_STYLE"), CAPTION_STYLES, "object",
                                     name, "caption_style")
        self.variant_param = env("VARIANT_PARAM") or "input_num_repetitions"
        self.duration_param = env("DURATION_PARAM")
        self.segment_seconds = _number(env("SEGMENT_SECONDS"), float, 2.0, name, "segment_seconds")
        self.max_variants = min(VARIANT_CAP, max(1, _number(env("MAX_VARIANTS"), int, VARIANT_CAP,
                                                            name, "max_variants")))
        self.generator = env("GENERATOR") or DEFAULT_GENERATOR
        self.license = env("LICENSE") or DEFAULT_LICENSE
        self.credit = env("CREDIT") or DEFAULT_CREDIT
        self.model_revision = env("MODEL_REVISION") or DEFAULT_MODEL_REVISION
        self._tls = threading.local()

    @property
    def motion_meta(self) -> Dict:
        """Everything the pose-animation job needs to know about this model."""
        return {"motion_source": self.motion_source, "source_slot": self.source_slot,
                "caption_style": self.caption_style, "variant_param": self.variant_param,
                "duration_param": self.duration_param, "segment_seconds": self.segment_seconds,
                "max_variants": self.max_variants, "generator": self.generator,
                "license": self.license, "credit": self.credit,
                "model_revision": self.model_revision}

    @property
    def last_result_meta(self) -> List[Dict]:
        """Per-result verdicts of the latest job on the current worker thread."""
        return list(getattr(self._tls, "result_meta", []))

    @property
    def last_job_id(self) -> str:
        """The latest submitted job ID on the current worker thread."""
        return getattr(self._tls, "job_id", "")

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    def check_availability(self) -> bool:
        if not self.model:
            logger.warning("%s: no model/alias configured", self.name)
            self._mark_unavailable()
            return False
        try:
            r = requests.get(f"{self.api_url}/v1/models",
                             headers=self._headers(), timeout=10)
            if r.status_code in (401, 403):
                logger.warning("%s: authentication rejected (HTTP %d)",
                               self.name, r.status_code)
                self._mark_unavailable()
                return False
            if r.status_code != 200:
                self._mark_unavailable()
                return False
        except Exception as e:
            logger.debug("%s: not reachable: %s", self.name, e)
            self._mark_unavailable()
            return False
        self._mark_available()
        return True

    def _read_source(self, path: str) -> bytes:
        p = Path(path or "")
        if not path or not p.is_file():
            raise ValueError("source model missing")
        size = p.stat().st_size
        if size > UPLOAD_MAX_BYTES:
            raise ValueError(f"source model exceeds 64 MiB ({size} bytes)")
        raw = p.read_bytes()
        if self.motion_source == "puppet" and raw[:4] != b"glTF":
            raise ValueError("source model is not a binary glTF")
        if self.motion_source == "reference_rig" and not raw.startswith(FBX_MAGIC):
            raise ValueError("source rig is not a binary FBX")
        return raw

    def _generate(self, prompt, negative_prompt, params):
        self._tls.job_id = ""
        self._tls.result_meta = []
        raw = self._read_source(params.get("source_model_path"))
        captions = [str(c) for c in (params.get("captions") or [])]
        if not 1 <= len(captions) <= 3:
            raise ValueError("1..3 captions required")
        variants = params.get("variants", 1)
        if isinstance(variants, bool) or not isinstance(variants, int) \
                or not 1 <= variants <= self.max_variants:
            raise ValueError(f"variants must be 1..{self.max_variants}")
        alias_params = {k: v for k, v in self.extra_params.items()
                        if k not in (self.variant_param, self.duration_param)}
        alias_params.update({"seed": int(params["seed"]), self.variant_param: variants})
        if self.duration_param:
            alias_params[self.duration_param] = float(self.segment_seconds)
        mime = GLB_MIME if self.motion_source == "puppet" else "application/octet-stream"
        payload = {"model": params.get("model") or self.model, "mode": "async",
                   "prompt": "\n".join(captions), "params": alias_params,
                   "files": {self.source_slot: "data:" + mime + ";base64,"
                             + base64.b64encode(raw).decode()}}
        job_id = submit_job(self, f"{self.api_url}{self.mesh_endpoint}", payload, "Animation")
        if not job_id:
            return []
        self._tls.job_id = job_id
        cb = params.get("on_job_id")
        if callable(cb):
            cb(job_id)
        return poll_job(self, job_id, max_wait=self.max_wait,
                        max_queue_wait=self.max_queue_wait,
                        poll_interval=self.poll_interval,
                        should_cancel=params.get("should_cancel"),
                        on_done=lambda sd, _s: self._download(sd, job_id, variants))

    def _download(self, sd, job_id: str, variants: int = 1) -> List[bytes]:
        """Every verified result in ``n`` order; one verdict per model result."""
        results = sorted((r for r in (sd.get("results") or [])
                          if isinstance(r, dict) and r.get("mime") in RESULT_MIMES),
                         key=lambda r: r.get("n", 0) if isinstance(r.get("n", 0), int) else 0)
        blobs: List[bytes] = []
        meta: List[Dict] = []
        for pos, res in enumerate(results):
            entry = {"n": res.get("n", 0), "name": str(res.get("name") or ""),
                     "mime": res.get("mime"), "sha256": res.get("sha256"), "ok": False,
                     "reason": ""}
            meta.append(entry)
            if pos >= variants:
                entry["reason"] = "unrequested result"
                continue
            blob, reason = self._fetch_result(job_id, res)
            entry["ok"], entry["reason"] = blob is not None, reason
            if blob is None:
                logger.error("%s: job %s result %s discarded: %s",
                             self.name, job_id, entry["n"], reason)
            else:
                blobs.append(blob)
        self._tls.result_meta = meta
        return blobs

    def _fetch_result(self, job_id: str, res: Dict):
        """Download and verify one result: ``(bytes, "")`` or ``(None, reason)``."""
        want = res.get("sha256")
        if want is None or want == "":
            return None, "missing sha256"
        if not isinstance(want, str) or re.fullmatch(r"[0-9a-fA-F]{64}", want) is None:
            return None, "malformed sha256"
        dl = requests.get(f"{self.api_url}/v1/jobs/{job_id}/result/{res.get('n', 0)}",
                          headers=self._headers(), timeout=300, allow_redirects=False)
        if dl.status_code != 200:
            return None, f"download HTTP {dl.status_code}"
        blob = dl.content
        if hashlib.sha256(blob).hexdigest() != want.lower():
            return None, "sha256 mismatch"
        if blob.startswith(FBX_MAGIC):
            return blob, ""
        if blob[:4] != b"glTF":
            return None, "result is neither glTF nor FBX"
        try:
            _check_glb(blob)
        except (ValueError, TypeError, AttributeError, struct.error) as exc:
            return None, f"invalid animation GLB: {exc}"
        return blob, ""


def _check_glb(blob: bytes) -> None:
    """A complete GLB 2 container with a skin and exactly one animation."""
    magic, version, total = struct.unpack_from("<4sII", blob)
    if magic != b"glTF" or version != 2 or total != len(blob):
        raise ValueError("invalid GLB header")
    offset, document = 12, None
    while offset < total:
        length, kind = struct.unpack_from("<II", blob, offset)
        offset += 8
        if length % 4 or offset + length > total:
            raise ValueError("invalid GLB chunk length")
        if document is None:
            if kind != 0x4E4F534A:
                raise ValueError("first GLB chunk must be JSON")
            document = json.loads(blob[offset:offset + length])
            if not isinstance(document, dict):
                raise ValueError("GLB JSON must be an object")
        elif kind == 0x4E4F534A:
            raise ValueError("duplicate GLB JSON chunk")
        offset += length
    if document is None:
        raise ValueError("GLB has no JSON chunk")
    skins, animations = document.get("skins"), document.get("animations")
    if not isinstance(skins, list) or not skins or not all(isinstance(skin, dict) for skin in skins):
        raise ValueError("GLB has no skin")
    if not isinstance(animations, list) or len(animations) != 1 or not isinstance(animations[0], dict):
        raise ValueError("GLB must contain exactly one animation")
