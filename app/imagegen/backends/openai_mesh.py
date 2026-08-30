"""LLM-gateway image-to-mesh backend (gateway generations/jobs API).

3D counterpart of ``OpenAIVideoBackend``: the gateway hosts an image-to-3D
workflow under a generation alias (e.g. ``Trellis2-Humanoid-Low``). Same async
API, but input IMAGES instead of a prompt, plus alias-specific params. Per the
client spec (``llm-gateway/docs/mesh-client-spec.md``, 2026-08-03) and the alias
schema (``GET /v1/generations/{alias}/schema``, which always wins):

    POST {api_url}/v1/generations            JSON:
        {"model": alias,
         "images": {"input_image": <base64|http-URL>},
         "params": {"input_name": …, "input_remove_background": true,
                    "input_face_num": 20000, "input_no_fingers": true},
         "mode": "async"}
        → 202 {"job_id": …}   (429/503 carry Retry-After)
    GET  {api_url}/v1/jobs/{job_id}           queued|running|done|failed
    POST {api_url}/v1/jobs/{job_id}/cancel

How MANY images go out is the alias' decision, read from its schema: a
multi-view workflow declares ``input_image_front``/``_back``/``_left``/
``_right`` and gets every view we rendered, a classic alias declares one
``input_image`` and gets the front view alone. Front is the only mandatory
view — a missing extra view is skipped, not an error.

The SAME class also drives the mesh→mesh aliases (``mesh-shrink``, spec § 3.4,
config ``category: "mesh2mesh"``): there the input is not an image but an
existing mesh, and it travels IN the request under ``files`` — never in
``params``, where the name would mean a file path on the gateway's backend:

    {"model": "mesh-shrink", "mode": "async",
     "params": {"input_name": "prop", "input_face_num": 5000},
     "files": {"input_mesh_path": "data:model/gltf-binary;base64,…"}}

``files`` is deliberately STRICT on the gateway side (unlike ``params``): an
unknown key or an unreadable value is a ``400``, a file over 64 MB a ``413``.
Both are terminal — a silently swallowed input would produce a technically
successful job on the wrong mesh. The size limit is therefore checked here
BEFORE anything is submitted. For the same reason the sha256 of whatever we
upload is kept and compared against the inputs the job view reports, so a
gateway-side mix-up shows up at the job instead of at the finished model.

Every public param name is ``input_*``; an UNKNOWN name is silently ignored by
the gateway (the alias default applies), so a stale name reaches nothing. Only
params the alias declares are sent — except when the schema is unreadable, then
the ``input_*`` names go out blind (worst case they are ignored).

``input_name`` decides the delivered FILE NAMES and is therefore always set;
leaving it empty makes the workflow inherit leftovers from a previous run. It
must also be UNIQUE per job (§ 3.2): a run's LOD stages live under that name on
the backend, so a later run with the same name hands the older stages out with
its own result. The caller builds the unique name (see
``service._unique_mesh_name``).
Meshing takes minutes → always ``mode:"async"`` + polling. ``MEDIA_TYPE ==
"mesh"`` keeps it out of image/video matching; the central ``generate()`` skips
image post-processing for it. Returns ALL delivered files as ``List[bytes]``;
their gateway metadata (name/mime/kind — the basis for sorting model, basecolor
and metallic apart) is exposed via ``last_result_files`` (thread-local).
"""
import base64
import hashlib
import os
import re
import threading
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import unquote, urlparse

import requests

from app.core.log import get_logger
from app.imagegen.backends._gateway_job import poll_job, submit_job
from app.imagegen.base import GatewayInputMismatchError, ImageBackend

logger = get_logger("image_backends")

# Purpose category of a mesh→mesh alias (mesh-shrink): it consumes a MESH, not
# an image, and must never be matched by a normal img2mesh generation.
MESH2MESH_CATEGORY = "mesh2mesh"

# Hard size limit of a file sent in ``files`` (mesh-client-spec § 1). The
# gateway answers 413 above it; refusing here keeps a doomed job out of the
# backend channel entirely.
MESH_UPLOAD_MAX_BYTES = 64 * 1024 * 1024

# data-URI mime per extension — the gateway derives the stored extension from
# it (unknown → .glb). Our stores only ever hold GLB/FBX.
_UPLOAD_MIME = {
    ".glb": "model/gltf-binary",
    ".gltf": "model/gltf+json",
    ".fbx": "model/fbx",
}

# Alias param for the reduced LOD stages of the same job (mesh-client-spec
# § 3.2): a comma-separated list of target triangle counts, sent as a STRING.
# Only the -Object family of the Hunyuan3D chain declares it today — which
# alias that is comes from the SCHEMA, never from a name match in code.
LOD_FACES_PARAM = "input_lod_faces"


def normalize_lod_faces(value: Any) -> List[int]:
    """Requested LOD stages as a clean list of positive ints — accepts one
    number, a list, or an already comma-separated string. Duplicates are
    dropped (the gateway would bake the same stage twice), order is kept."""
    if value is None or isinstance(value, bool):
        return []
    raw: List[Any]
    if isinstance(value, (list, tuple, set)):
        raw = list(value)
    else:
        raw = str(value).replace(";", ",").split(",")
    out: List[int] = []
    for item in raw:
        try:
            n = int(float(str(item).strip()))
        except (TypeError, ValueError):
            continue
        if n > 0 and n not in out:
            out.append(n)
    return out


class OpenAIMeshBackend(ImageBackend):
    """Gateway image-to-mesh via /v1/generations + /v1/jobs (async)."""

    MEDIA_TYPE = "mesh"
    DEFAULT_REF_SLOT_COUNT = 1

    def __init__(self, name: str, api_url: str, cost: float, env_prefix: str,
                 api_key: str = "", model: str = ""):
        super().__init__(name, api_url, cost, api_type="openai_mesh",
                         env_prefix=env_prefix)
        self.api_key = (api_key or os.environ.get(f"{env_prefix}API_KEY", "")).strip()
        self.model = (model or os.environ.get(f"{env_prefix}MODEL", "")).strip()
        self.timeout = int(os.environ.get(f"{env_prefix}TIMEOUT", "120") or 120)
        self.poll_interval = float(os.environ.get(f"{env_prefix}POLL_INTERVAL", "5.0") or 5.0)
        # max_wait budgets the RUNNING time; queue waiting is capped separately
        # (a queued job means the GPU is busy — being patient is the point of
        # having a queue on both sides).
        self.max_wait = int(os.environ.get(f"{env_prefix}MAX_WAIT", "900") or 900)
        self.max_queue_wait = int(
            os.environ.get(f"{env_prefix}MAX_QUEUE_WAIT", "0") or 0) or (self.max_wait * 4)
        self.mesh_endpoint = (os.environ.get(f"{env_prefix}MESH_ENDPOINT", "")
                              or "/v1/generations").strip().rstrip("/")
        # Which skeleton the alias produces — decides what may use it and which
        # of the delivered files must be STORED:
        #   mixamo  -> humanoid 52-bone rig, ONE glb (textures embedded)
        #   generic -> no standard skeleton, fbx + its basecolor image as an
        #              inseparable pair
        #   none    -> unrigged, ONE glb (textures embedded); static props /
        #              building models — never matched to a character
        self.mesh_rig = (os.environ.get(f"{env_prefix}MESH_RIG", "")
                         or "mixamo").strip().lower()
        # Alias params (schema: input_remove_background / input_face_num /
        # input_no_fingers)
        self.remove_background = str(
            os.environ.get(f"{env_prefix}REMOVE_BACKGROUND", "true")).strip().lower() \
            not in ("0", "false", "no", "off")
        self.no_fingers = str(
            os.environ.get(f"{env_prefix}NO_FINGERS", "true")).strip().lower() \
            not in ("0", "false", "no", "off")
        # 0 = not configured -> no detail param is sent and the ALIAS default
        # applies (Triposplat has no face param at all; its num_gaussians
        # default is 10000 and must stay reachable).
        self.face_num = int(os.environ.get(f"{env_prefix}FACE_NUM", "") or 0)
        # Hard ceiling for the detail count (0 = none). Config data, not a
        # family name in code: Hunyuan3D FREEZES above 40000 — the job never
        # errors, it hangs until the timeout.
        self.face_num_max = int(os.environ.get(f"{env_prefix}FACE_NUM_MAX", "") or 0)
        # Alias self-discovery (image slot names, file slot name, declared
        # param names); safe fallback without schema. A multi-view alias
        # declares SEVERAL image slots (input_image_front/_back/_left/_right);
        # the classic single-view alias declares one (input_image).
        self._image_slots: List[str] = []
        self._file_slot: str = ""
        self._alias_param_names: set = set()
        self._tls = threading.local()

    # -- result metadata ----------------------------------------------------
    @property
    def last_result_files(self) -> List[Dict[str, str]]:
        """Gateway metadata of the last downloaded results (thread-local), in
        the same order as the returned byte blobs: ``{"name", "mime", "kind"}``
        per file (e.g. ``{"name": "Spoty_articulationxl_00001_.fbx",
        "mime": "application/octet-stream", "kind": "model"}``).

        Name AND mime come from the job view together — they are the ONLY
        source for format/extension (the JPEG re-encode is per FILE, so a
        basecolor may stay PNG while the metallic map of the same job is JPEG).
        The artifact tokens in the name (``_basecolor`` / ``_metallic`` /
        ``_articulationxl``) are what sorts the files apart."""
        return [dict(f) for f in (getattr(self._tls, "result_files", []) or [])]

    # -- input identity -----------------------------------------------------
    # The gateway once ran two jobs on the same input file name and delivered
    # one client the other one's mesh. Its fix reports the stored inputs with
    # their sha256 in the job view (``input_images[]``, analogous to
    # ``results[]``); we hash what we upload anyway, so the swap becomes
    # detectable at the job instead of at the finished model. An OLD gateway
    # simply carries no such field — then there is nothing to compare and
    # nothing to warn about.
    INPUT_LIST_KEYS = ("input_images", "inputs", "input_files")

    def _remember_input(self, raw: bytes) -> str:
        """sha256 of the bytes we are about to upload, appended to the run's
        list (thread-local — a multi-view run uploads several images).
        Returns the digest for the job-start log."""
        digest = hashlib.sha256(raw).hexdigest()
        if not isinstance(getattr(self._tls, "input_sha256s", None), list):
            self._tls.input_sha256s = []
        self._tls.input_sha256s.append(digest)
        return digest

    def _check_input_identity(self, sd: Dict[str, Any], job_id: str) -> None:
        """Compare our uploaded inputs against the job view's input list.

        Raises ``GatewayInputMismatchError`` when the gateway reports inputs
        and any of OURS is missing from them. No list (old gateway), no digest
        (http URLs the gateway fetched itself) or a list without any sha256 →
        no check, no warning.
        """
        want = list(getattr(self._tls, "input_sha256s", None) or [])
        if not want:
            return
        entries: List[Any] = []
        for key in self.INPUT_LIST_KEYS:
            val = sd.get(key)
            if isinstance(val, list) and val:
                entries = val
                break
        got = [str(e.get("sha256") or "").strip().lower()
               for e in entries if isinstance(e, dict)]
        got = [h for h in got if h]
        if not got:
            return
        missing = [h for h in want if h not in got]
        if not missing:
            logger.debug("%s: Job %s Eingang bestaetigt (%d sha256, erster %s)",
                         self.name, job_id, len(want), want[0][:12])
            return
        raise GatewayInputMismatchError(
            f"{self.name}: job {job_id} ran on a DIFFERENT input than we "
            f"uploaded (ours sha256 "
            f"{', '.join(h[:12] for h in missing)} missing, the gateway stored "
            f"{', '.join(h[:12] for h in got)}) — result discarded")

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    def check_availability(self) -> bool:
        if not self.model:
            logger.warning("%s: kein Model/Alias konfiguriert", self.name)
            self._mark_unavailable()
            return False
        try:
            r = requests.get(f"{self.api_url}/v1/models",
                             headers=self._headers(), timeout=10)
            if r.status_code in (401, 403):
                logger.warning("%s: Auth abgelehnt (HTTP %d)", self.name, r.status_code)
                self._mark_unavailable()
                return False
            if r.status_code != 200:
                self._mark_unavailable()
                return False
        except Exception as e:
            logger.debug("%s: nicht erreichbar: %s", self.name, e)
            self._mark_unavailable()
            return False
        self._mark_available()
        self._fetch_alias_schema()
        return True

    def _fetch_alias_schema(self) -> None:
        """Reads the input slots + declared param names from the alias schema
        (e.g. ``input_image`` for img2mesh, ``input_mesh_path`` for shrink).

        ALL image slots are kept, in declaration order: a multi-view alias
        declares ``input_image_front``/``_back``/``_left``/``_right``, the
        classic one a single ``input_image``."""
        try:
            r = requests.get(f"{self.api_url}/v1/generations/{self.model}/schema",
                             headers=self._headers(), timeout=10)
            if r.status_code != 200:
                return
            sd = r.json() if r.content else {}
            images = sd.get("images") or []
            slots: List[str] = []
            if isinstance(images, list):
                for entry in images:
                    slot = (entry.get("name") if isinstance(entry, dict)
                            else str(entry)) or ""
                    if slot:
                        slots.append(str(slot))
            elif isinstance(images, dict):
                slots = [str(k) for k in images if str(k)]
            if slots:
                self._image_slots = slots
            # Non-image input slots (mesh→mesh: input_mesh_path). Same shape as
            # the image slots; absent on every img2mesh alias.
            files = sd.get("files") or []
            if isinstance(files, list) and files:
                first = files[0]
                slot = (first.get("name") if isinstance(first, dict) else str(first)) or ""
                if slot:
                    self._file_slot = slot
            elif isinstance(files, dict) and files:
                self._file_slot = next(iter(files))
            # Declared param names — optional params (e.g.
            # input_texture_resolution) are only sent when the alias really
            # declares them.
            raw_params = sd.get("params") or []
            names = set()
            if isinstance(raw_params, dict):
                names = {str(k).strip().lower() for k in raw_params}
            elif isinstance(raw_params, list):
                for entry in raw_params:
                    n = (entry.get("name") if isinstance(entry, dict) else entry) or ""
                    if n:
                        names.add(str(n).strip().lower())
            self._alias_param_names = names
            logger.info("%s: Alias-Schema gelesen (image_slots=%s, file_slot=%s, "
                        "params=%s)", self.name,
                        self._image_slots or ["input_image"],
                        self._file_slot or "-", sorted(names) or "?")
        except Exception as e:
            logger.debug("%s: Alias-Schema nicht lesbar: %s", self.name, e)

    @staticmethod
    def _slot_view(slot: str) -> str:
        """The VIEW a slot name asks for: ``back`` / ``left`` / ``right`` when
        the name carries that token, otherwise ``front``.

        So ``input_image_back`` is the back view and the classic single slot
        ``input_image`` is the front view — the same rule maps our reference
        keys and the alias' slot names onto one another."""
        low = str(slot or "").lower()
        for view in ("back", "left", "right"):
            if view in low:
                return view
        return "front"

    @classmethod
    def _input_images(cls, params: Dict[str, Any]) -> Dict[str, str]:
        """The input images of this run as ``{view: local path | URL}``.

        ``reference_images`` is keyed by view (``front``/``back``/…); the token
        rule of ``_slot_view`` also catches the legacy key ``input_image``,
        which lands on ``front``. The first entry per view wins. Only when the
        refs carry no front view does ``source_image_path`` fill it in."""
        views: Dict[str, str] = {}
        refs = params.get("reference_images") or {}
        if isinstance(refs, dict):
            for key, path in refs.items():
                if path:
                    views.setdefault(cls._slot_view(key), str(path))
        src = str(params.get("source_image_path") or "")
        if src:
            views.setdefault("front", src)
        return views

    @classmethod
    def select_slot_images(cls, slots: List[str],
                           view_paths: Dict[str, str]) -> Dict[str, str]:
        """Maps the alias' image slots onto the views we hold: ``{slot: path}``.

        A slot whose view we have no image for is LEFT OUT — a single-slot
        alias thus gets the front view only, a multi-view alias as many views
        as were rendered. The first slot per view wins (a schema declaring two
        slots of the same view would otherwise upload the image twice).

        Public/classmethod so the mapping can be checked without a backend
        instance or a gateway (scripts/smoke_mesh_multiview.py)."""
        out: Dict[str, str] = {}
        used: set = set()
        for slot in (slots or ["input_image"]):
            view = cls._slot_view(slot)
            if view in used:
                continue
            path = view_paths.get(view)
            if not path:
                continue
            out[str(slot)] = str(path)
            used.add(view)
        return out

    def build_input_files(self, params: Dict[str, Any]) -> Dict[str, str]:
        """The ``files`` block of a mesh→mesh request, or ``{}`` when this run
        has no source mesh (every img2mesh generation).

        Per spec § 3.4 the mesh travels IN the request: base64, a data-URI or
        an http(s) URL the gateway fetches itself. We send a data-URI so the
        gateway can derive the extension from the mime — a bare base64 blob
        would always land as ``.glb``, which is a lie for an FBX. A local path
        that is missing, or a file over 64 MB, raises HERE: the gateway would
        answer 400/413 and both are terminal, so submitting is pointless.

        Public so the payload can be checked without a gateway
        (scripts/smoke_mesh_gateway.py)."""
        src = str(params.get("source_model_path") or "").strip()
        if not src:
            return {}
        slot = self._file_slot or "input_mesh_path"
        if src.startswith(("http://", "https://")):
            return {slot: src}
        p = Path(src)
        if not p.is_file():
            raise FileNotFoundError(f"source mesh not found: {src}")
        size = p.stat().st_size
        if size > MESH_UPLOAD_MAX_BYTES:
            raise ValueError(
                f"source mesh is {size / 1024 / 1024:.1f} MB — over the "
                f"gateway limit of {MESH_UPLOAD_MAX_BYTES // 1024 // 1024} MB "
                f"(HTTP 413)")
        mime = _UPLOAD_MIME.get(p.suffix.lower(), "application/octet-stream")
        raw = p.read_bytes()
        self._remember_input(raw)
        b64 = base64.b64encode(raw).decode("utf-8")
        return {slot: f"data:{mime};base64,{b64}"}

    def _result_name_from(self, url: str, resp: requests.Response) -> str:
        cd = resp.headers.get("Content-Disposition", "") or ""
        m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', cd)
        if m:
            return unquote(m.group(1)).strip()
        return unquote(Path(urlparse(url).path).name or "")

    @property
    def supports_lod_stages(self) -> bool:
        """Whether this ALIAS can bake reduced LOD stages in the same job —
        read from the schema (``input_lod_faces``), never from the alias name.

        Deliberately STRICTER than ``_declares``: an unreadable schema counts
        as "no" here. Sending an unknown param blind is free (the gateway
        ignores it), but OFFERING the admin a control that reaches nothing is
        not."""
        return LOD_FACES_PARAM in self._alias_param_names

    def _declares(self, param: str) -> bool:
        """Whether the alias declares ``param``. An UNREADABLE schema (no names
        at all) counts as "declares everything": the gateway ignores unknown
        names silently, so sending blind costs nothing and keeps a backend
        usable while /schema is down."""
        return not self._alias_param_names or param in self._alias_param_names

    def _effective_faces(self, params: Dict[str, Any]) -> int:
        """Detail count for this run (0 = send none, alias default applies),
        clamped to ``face_num_max``."""
        faces = int(params.get("face_num") or self.face_num or 0)
        if self.face_num_max and faces > self.face_num_max:
            logger.warning("%s: face_num %d ueber dem Limit %d — gekappt "
                           "(hoehere Werte frieren dieses Backend ein)",
                           self.name, faces, self.face_num_max)
            faces = self.face_num_max
        return max(0, faces)

    def build_alias_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """The ``params`` block of the generation request — every key a public
        ``input_*`` name of the alias schema (mesh-client-spec § 1/3).

        Public so the param mapping can be checked without a gateway
        (scripts/smoke_mesh_gateway.py)."""
        # input_name is ALWAYS set: it decides the delivered file names, and an
        # empty one makes the workflow reuse leftovers of a previous run. The
        # alias is the fallback so the files stay attributable.
        alias_params: Dict[str, Any] = {
            "input_name": (str(params.get("mesh_name") or "").strip()
                           or str(self.model or self.name or "mesh").strip()),
        }
        # Background removal is an IMAGE step — the shrink alias does not
        # declare it (and would ignore it), so it goes out only where the
        # schema knows it.
        if self._declares("input_remove_background"):
            alias_params["input_remove_background"] = bool(params.get(
                "remove_background", self.remove_background))
        # Detail count: the mesh aliases call it input_face_num, the splat
        # pipeline (Triposplat) has no face param and takes input_num_gaussians
        # instead — SAME value under whichever the alias declares. 0 = send
        # none and let the alias default stand.
        faces = self._effective_faces(params)
        if faces:
            declared = [n for n in ("input_face_num", "input_num_gaussians")
                        if n in self._alias_param_names]
            for pname in (declared or ["input_face_num"]):
                alias_params[pname] = faces
        # input_no_fingers is accepted by ALL img2mesh families but only does
        # something in the Humanoid rig stage — send it whenever it is
        # declared (the shrink alias passes it through without effect).
        if self._declares("input_no_fingers"):
            alias_params["input_no_fingers"] = bool(
                params.get("no_fingers", self.no_fingers))
        # LOD stages (§ 3.2): reduced versions of the SAME bake, delivered by
        # the same job. Sent as a comma-separated STRING — the contract's type,
        # not a list — and only where the schema declares the param.
        lod = normalize_lod_faces(params.get("lod_faces"))
        if lod:
            if self._declares(LOD_FACES_PARAM):
                alias_params[LOD_FACES_PARAM] = ",".join(str(n) for n in lod)
            else:
                logger.info("%s: lod_faces=%s requested but the alias declares "
                            "no LOD param — dropped", self.name, lod)
        # Texture size: plumbed through the whole chain, sent only when the
        # alias declares it.
        tex = params.get("texture_size")
        if tex:
            if self._declares("input_texture_resolution"):
                alias_params["input_texture_resolution"] = int(tex)
            else:
                logger.info("%s: texture_size=%s requested but the alias "
                            "declares no texture param — dropped", self.name, tex)
        return alias_params

    def _generate(self, prompt: str, negative_prompt: str,
                  params: Dict[str, Any]) -> List[bytes]:
        self._tls.result_files = []
        self._tls.input_sha256s = []
        # mesh→mesh (shrink) or img2mesh — mutually exclusive: a run either
        # carries a source MESH in `files` or an input IMAGE in `images`.
        try:
            input_files = self.build_input_files(params)
        except (OSError, ValueError) as e:
            logger.error("%s: Eingangs-Mesh unbrauchbar: %s", self.name, e)
            return []
        payload: Dict[str, Any] = {
            "model": params.get("model") or self.model,
            "params": {},
            "mode": "async",
        }
        if input_files:
            payload["files"] = input_files
        else:
            # One slot per view the alias declares: a multi-view alias gets
            # front/back/left/right, the classic single-slot alias only front.
            views = self._input_images(params)
            slot_paths = self.select_slot_images(self._image_slots, views)
            images: Dict[str, str] = {}
            for slot, src in slot_paths.items():
                is_front = self._slot_view(slot) == "front"
                if src.startswith(("http://", "https://")):
                    images[slot] = src
                    continue
                p = Path(src)
                if not p.exists():
                    if is_front:
                        logger.error("%s: Eingangsbild fehlt: %s", self.name, src)
                        return []
                    # An extra view is a bonus, never a reason to fail the run.
                    logger.warning("%s: Zusatz-Ansicht %s fehlt (%s) — "
                                   "uebersprungen", self.name, slot, src)
                    continue
                raw = p.read_bytes()
                self._remember_input(raw)
                images[slot] = base64.b64encode(raw).decode("utf-8")
            if not any(self._slot_view(s) == "front" for s in images):
                logger.error("%s: kein Eingangsbild fuer die Mesh-Generierung",
                             self.name)
                return []
            payload["images"] = images

        alias_params = self.build_alias_params(params)
        payload["params"] = alias_params

        url = f"{self.api_url}{self.mesh_endpoint}"
        # Read the detail count back out of the params: an alias may declare
        # only input_num_gaussians (the splat-based one does) or no detail
        # param at all — a fixed key here used to raise a KeyError and kill
        # the job.
        faces = (alias_params.get("input_face_num")
                 or alias_params.get("input_num_gaussians")
                 or "alias default")
        # Count of what we send vs. the FIRST hash: an http URL counts as an
        # input but carries no hash of ours (the gateway fetches it itself).
        shas = list(getattr(self._tls, "input_sha256s", None) or [])
        n_inputs = len(input_files) if input_files else len(payload.get("images") or {})
        lod = alias_params.get(LOD_FACES_PARAM) or "-"
        logger.info("%s: starte Mesh-Job (Alias=%s, faces=%s, lod=%s, "
                    "name='%s', Eingang=%s images=%d sha256=%s)", self.name,
                    payload["model"], faces, lod, alias_params["input_name"],
                    "mesh" if input_files else "image", n_inputs,
                    shas[0][:12] if shas else "-")
        job_id = submit_job(self, url, payload, "Mesh")
        if not job_id:
            return []

        def _download(sd: Dict[str, Any], running_s: float) -> List[bytes]:
            # A job delivers the model plus its *_basecolor* / *_metallic*
            # maps, and with input_lod_faces one self-contained GLB per
            # requested stage. Download them all and hand their gateway
            # metadata (name/mime/kind) up — the caller decides by NAME which
            # ones it must store. The response order is alphabetical by file
            # name (§ 3.2), so position says nothing.
            for warn in (sd.get("warnings") or []):
                logger.warning("%s: Gateway-Warnung: %s", self.name, warn)
            # Did the job run on OUR input? (No-op on a gateway that does not
            # report its stored inputs.)
            self._check_input_identity(sd, job_id)
            _results = [r for r in (sd.get("results") or [])
                        if isinstance(r, dict)]
            if not _results:
                logger.error("%s: Job %s ohne results", self.name, job_id)
                return []
            blobs: List[bytes] = []
            files: List[Dict[str, str]] = []
            for idx, res in enumerate(_results):
                _r_url = res.get("url") or ""
                if _r_url and not _r_url.startswith(("http://", "https://")):
                    _r_url = f"{self.api_url}{_r_url}"
                if not _r_url:
                    _r_url = (f"{self.api_url}/v1/jobs/{job_id}/result/"
                              f"{res.get('n', idx)}")
                dl = requests.get(_r_url, headers=self._headers(), timeout=300)
                if dl.status_code != 200 or len(dl.content) < 100:
                    logger.error("%s: Result-Download %d HTTP %d (%d bytes)",
                                 self.name, idx, dl.status_code, len(dl.content))
                    return []
                want = str(res.get("sha256") or "").strip().lower()
                if want:
                    got = hashlib.sha256(dl.content).hexdigest()
                    if got != want:
                        logger.error("%s: Result %d (%s) sha256 stimmt nicht "
                                     "(%s != %s) — Job verworfen", self.name,
                                     idx, res.get("name", "?"), got[:12],
                                     want[:12])
                        return []
                blobs.append(dl.content)
                files.append({
                    "name": str(res.get("name") or "")
                            or self._result_name_from(_r_url, dl),
                    "mime": str(res.get("mime") or ""),
                    "kind": str(res.get("kind") or ""),
                })
            self._tls.result_files = files
            logger.info("%s: Mesh fertig (%.1fs, rig=%s, %d Datei(en): %s)",
                        self.name, running_s, sd.get("rig") or self.mesh_rig,
                        len(blobs),
                        ", ".join(f"{f['name']} [{f['kind'] or '?'}, {len(b)}B]"
                                  for f, b in zip(files, blobs)))
            return blobs

        return poll_job(self, job_id, max_wait=self.max_wait,
                        max_queue_wait=self.max_queue_wait,
                        poll_interval=self.poll_interval, on_done=_download)
