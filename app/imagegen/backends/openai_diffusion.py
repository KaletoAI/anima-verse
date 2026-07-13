"""Strict OpenAI-images-standard diffusion backend (LLM gateway)."""
import base64
import json
import os
import random
import re
import time
from typing import Any, Dict, List, Optional

import requests

from app.core.log import get_logger
from app.imagegen.backends.localai import LocalAIBackend

logger = get_logger("image_backends")


class OpenAIDiffusionBackend(LocalAIBackend):
    """Strict OpenAI images standard (POST {url}/v1/images/generations).

    For endpoints that adhere to the OpenAI standard — in particular the
    **LLM gateway** (OpenAI-compatible reverse proxy in front of ComfyUI).
    Differences from the LocalAI flavour (``LocalAIBackend``):
      - Parameter name ``steps`` (not ``step``).
      - Generic **extra-params block** (JSON): arbitrary extra keys
        (seed/steps/cfg/lora_01/...) are merged 1:1 into the request. Which names
        are valid is defined by the alias workflow on the gateway side — therefore
        NOT hardcoded but freely configurable.
      - ``response_format`` configurable (default ``b64_json``).
      - **Bearer header also on the result-URL fetch** (gateway result URLs are not
        public, they require the same job-owner token).
      - Error mapping per OpenAI/gateway semantics: 400=request error (no retry),
        401/403=config, 402=quota, 502=1x retry, 503=backoff retry, 429=backoff.

    ``model`` here is a **generation alias** of the gateway, not a ComfyUI checkpoint.
    ``ref_images`` (raw base64) stays inherited — the gateway accepts it as a bonus.
    """

    def __init__(self, name: str, api_url: str, cost: float, env_prefix: str,
                 api_key: str = "", model: str = ""):
        super().__init__(name, api_url, cost, env_prefix, api_key=api_key, model=model)
        self.api_type = "openai_diffusion"
        rf = os.environ.get(f"{env_prefix}RESPONSE_FORMAT", "").strip().lower()
        self.response_format = rf if rf in ("b64_json", "url") else "b64_json"
        # self.category (txt2img/img2img/inpaint) comes from the base class —
        # here it also routes the request: "inpaint" -> POST /v1/images/edits
        # (canvas + mask as two images), otherwise /v1/images/generations.
        # Default prompt (e.g. inpaint fill instruction) — fallback when the caller
        # provides no prompt.
        self.default_prompt = os.environ.get(f"{env_prefix}PROMPT", "").strip()
        # Inpaint mask parameters (only for category=inpaint). NO model-special logic —
        # everything freely configurable; the map-blend path (world.py) builds canvas + mask
        # purely from these values. The mask is ALWAYS sent along.
        #   full_mask    True = mask the whole area, False = only the center/cell
        #   terrain_hint True = append a dynamic terrain description to the prompt
        #   mask_grow    mask-edge factor (1.05 = +5%)
        #   inner_crop   core crop of the center (0.7 = inner 70%)
        def _flag(key: str, default: bool) -> bool:
            return os.environ.get(f"{env_prefix}{key}", str(default)).strip().lower() in ("true", "1", "yes")
        def _num(key: str, default: float) -> float:
            try:
                return float(os.environ.get(f"{env_prefix}{key}", "").strip() or default)
            except (TypeError, ValueError):
                return default
        self.full_mask = _flag("FULL_MASK", True)
        self.terrain_hint = _flag("TERRAIN_HINT", False)
        self.mask_grow = _num("MASK_GROW", 1.05)
        self.inner_crop = _num("INNER_CROP", 0.7)
        # Mask format for the edits upload (only category=inpaint):
        #   grayscale = L-PNG 1:1 as produced (white=edit) — for gateways that pass
        #               the mask directly to ComfyUI's ``inputs.mask`` (white=edit).
        #               The wire is then byte-identical to mapblend_debug/last_mask.png.
        #   openai    = OpenAI edits standard (RGBA, transparent=edit) for real
        #               OpenAI/DALL-E edits endpoints.
        _mf = os.environ.get(f"{env_prefix}MASK_FORMAT", "grayscale").strip().lower()
        self.mask_format = _mf if _mf in ("grayscale", "openai") else "grayscale"
        # Extra params: freely configurable JSON block (loras/seed/steps/cfg/...).
        # Merged as additional top-level keys into the request.
        raw = os.environ.get(f"{env_prefix}EXTRA_PARAMS", "").strip()
        self.extra_params: Dict[str, Any] = {}
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    self.extra_params = parsed
                else:
                    logger.warning(f"{name}: EXTRA_PARAMS ist kein JSON-Objekt, ignoriert")
            except (ValueError, TypeError) as e:
                logger.warning(f"{name}: EXTRA_PARAMS kein gueltiges JSON ({e}), ignoriert")

    def _post_gateway(self, endpoint: str, *, json: Optional[Dict[str, Any]] = None,
                      files: Optional[list] = None,
                      data: Optional[Dict[str, Any]] = None) -> requests.Response:
        """POST with OpenAI/gateway error mapping (spec §6). Blocks synchronously until
        the image is ready (the gateway parks under load itself — no own throttling).

        ``endpoint`` = "generations" (JSON) or "edits" (multipart: ``files`` + ``data``).
        For multipart do NOT set Content-Type — requests adds the boundary itself,
        so only the Bearer header (spec: auth on every request).
        """
        url = f"{self.api_url}/v1/images/{endpoint}"
        if json is not None:
            headers = self._headers()
        else:
            headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        _429 = _502 = _503 = 0
        max_429, max_502, max_503 = 4, 1, 4
        while True:
            resp = requests.post(url, json=json, files=files, data=data,
                                 headers=headers, timeout=self.timeout)
            code = resp.status_code
            if code == 200:
                return resp
            body = (resp.text or "")[:300]
            if code == 429:
                if _429 >= max_429:
                    raise RuntimeError(f"{self.name}: HTTP 429 (Rate-Limit) nach {max_429} Versuchen")
                _429 += 1
                wait = self._rate_limit_wait(resp, _429)
                logger.warning(f"{self.name}: 429, warte {wait:.1f}s ({_429}/{max_429})")
                time.sleep(wait)
                continue
            if code == 503:  # no healthy backend for the alias — retry with backoff
                if _503 >= max_503:
                    raise RuntimeError(f"{self.name}: HTTP 503 (kein Backend) nach {max_503} Versuchen: {body}")
                _503 += 1
                wait = min(2.0 * (2 ** (_503 - 1)), 30.0)
                logger.warning(f"{self.name}: 503 (kein gesundes Backend), warte {wait:.1f}s ({_503}/{max_503})")
                time.sleep(wait)
                continue
            if code == 502:  # generation failed / park timeout — retry once
                if _502 >= max_502:
                    raise RuntimeError(f"{self.name}: HTTP 502 (Generierung fehlgeschlagen): {body}")
                _502 += 1
                logger.warning(f"{self.name}: 502, einmaliger Retry ({_502}/{max_502})")
                continue
            if code == 402:
                logger.error(f"{self.name}: HTTP 402 — Credit-/Quota-Limit erreicht: {body}")
                raise RuntimeError(f"{self.name}: Quota/Credit-Limit erreicht (HTTP 402): {body[:160]}")
            if code in (401, 403):
                logger.error(f"{self.name}: HTTP {code} — API-Key/Alias nicht erlaubt: {body}")
                raise RuntimeError(f"{self.name}: Auth/Alias-Fehler (HTTP {code}): {body[:160]}")
            if code == 400:
                logger.error(f"{self.name}: HTTP 400 — Request-Fehler (prompt/image fehlt?): {body}")
                raise RuntimeError(f"{self.name}: Request-Fehler (HTTP 400): {body[:160]}")
            logger.error(f"{self.name}: HTTP {code}: {body}")
            raise RuntimeError(f"{self.name}: HTTP {code}: {body[:160]}")

    def _apply_lora_params(self, payload: Dict[str, Any], params: Dict[str, Any]) -> None:
        """Transfers selected LoRAs dynamically as ``lora_01``/``strength_01``,
        ``lora_02``/``strength_02`` … (ComfyUI/gateway convention, cf. spec §2/§4).

        The source is params['lora_inputs'] — resolved by the skill (dialog selection
        from the per-world LoRA library, endpoint-filtered). Unlike LocalAI NO
        ``<lora:>`` prompt syntax: the gateway/ComfyUI maps the keyed params onto the
        lora-loader node of the alias workflow. 'None'/empty slots are skipped.
        """
        idx = 0
        for l in (params.get("lora_inputs") or params.get("loras") or []):
            if not isinstance(l, dict):
                continue
            name = (l.get("name") or "").strip()
            if not name or name == "None":
                continue
            try:
                strength = float(l.get("strength", 1.0))
            except (TypeError, ValueError):
                strength = 1.0
            idx += 1
            payload[f"lora_{idx:02d}"] = name
            payload[f"strength_{idx:02d}"] = strength
        if idx:
            logger.info(f"{self.name}: {idx} LoRA(s) dynamisch als lora_NN-Params uebertragen")

    def _is_inpaint(self, params: Dict[str, Any]) -> bool:
        """Inpaint when the backend is categorized as such OR a mask is present."""
        refs = params.get("reference_images") or {}
        return self.category == "inpaint" or "input_mask" in refs

    def _collect_ref_bytes(self, params: Dict[str, Any]) -> List[tuple]:
        """Reference images as an ordered (title, bytes) list for the edits upload.

        Order = insertion order of params['reference_images']. The caller
        distinguishes by title: 'input_mask' -> mask field, everything else ->
        image field (canvas/references).
        """
        out: List[tuple] = []
        for title, path in (params.get("reference_images") or {}).items():
            if not path:
                continue
            sp = str(path)
            try:
                if sp.startswith(("http://", "https://")):
                    r = requests.get(sp, timeout=30)
                    if r.status_code == 200:
                        out.append((title, r.content))
                elif sp.startswith("data:"):
                    out.append((title, base64.b64decode(sp.split(",", 1)[1] if "," in sp else sp)))
                else:
                    with open(sp, "rb") as f:
                        out.append((title, f.read()))
            except Exception as e:
                logger.warning(f"{self.name}: Referenzbild '{sp}' nicht lesbar: {e}")
        return out

    def _parse_image_response(self, resp: requests.Response) -> List[bytes]:
        """Shared response parsing (b64_json | url) for generations + edits."""
        images: List[bytes] = []
        for item in resp.json().get("data", []):
            b64 = item.get("b64_json", "")
            if b64:
                images.append(base64.b64decode(b64))
                continue
            url = item.get("url", "")
            if url:
                # Result URLs are not public — send the Bearer header along.
                img_resp = requests.get(url, headers=self._headers(), timeout=60)
                if img_resp.status_code == 200:
                    images.append(img_resp.content)
                else:
                    logger.error(f"{self.name}: Result-URL HTTP {img_resp.status_code}")
        if not images:
            logger.error(f"{self.name}: Keine Bilder in Response")
        return images

    def _generate(self, prompt: str, negative_prompt: str, params: Dict[str, Any]) -> List[bytes]:
        prompt = prompt or self.default_prompt
        if self._is_inpaint(params):
            return self._generate_edits(prompt, negative_prompt, params)

        model = params.get("model") or self.model
        width = params.get("width") or self.width
        height = params.get("height") or self.height
        steps = params.get("num_inference_steps") or self.num_inference_steps
        width = round(width / 8) * 8 or 1024
        height = round(height / 8) * 8 or 1024

        payload: Dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "size": f"{width}x{height}",
            "response_format": self.response_format,
        }
        ref_images = self._collect_ref_images(params)
        if ref_images:
            payload["ref_images"] = ref_images
        # LoRAs dynamically (lora_01/strength_01..) — NO <lora:> prompt syntax.
        self._apply_lora_params(payload, params)
        if steps:
            payload["steps"] = steps  # OpenAI standard: steps (not LocalAI "step")
        if negative_prompt:
            payload["negative_prompt"] = negative_prompt
        seed = params.get("seed")
        if seed and seed > 0:
            payload["seed"] = seed
        # Merge freely configured extra params (alias-workflow-specific) last —
        # they are allowed to override the defaults above deliberately.
        if self.extra_params:
            payload.update(self.extra_params)

        logger.info(f"{self.name}: Starte Generierung (Alias {model}, {width}x{height}, "
                    f"{len(ref_images)} Ref-Bild(er), rf={self.response_format})")
        try:
            resp = self._post_gateway("generations", json=payload)
            return self._parse_image_response(resp)
        except requests.Timeout:
            logger.error(f"{self.name}: Timeout nach {self.timeout}s")
            return []
        except RuntimeError:
            return []
        except Exception as e:
            logger.error(f"{self.name}: Fehler: {e}")
            return []

    def _to_openai_mask(self, raw: bytes) -> bytes:
        """Grayscale inpaint mask (white = to fill, ComfyUI convention) ->
        OpenAI edits standard: RGBA PNG where edited is alpha=0 (transparent).
        On error the raw bytes unchanged (degrades instead of crashing)."""
        try:
            from PIL import Image, ImageOps
            import io as _io
            m = Image.open(_io.BytesIO(raw)).convert("L")
            rgba = Image.new("RGBA", m.size, (255, 255, 255, 255))
            rgba.putalpha(ImageOps.invert(m))  # white(255) -> alpha 0 (transparent = edit)
            buf = _io.BytesIO()
            rgba.save(buf, format="PNG")
            return buf.getvalue()
        except Exception as e:
            logger.warning(f"{self.name}: Masken-Konvertierung fehlgeschlagen ({e}), sende roh")
            return raw

    def _generate_edits(self, prompt: str, negative_prompt: str, params: Dict[str, Any]) -> List[bytes]:
        """Inpaint/img2img via POST /v1/images/edits (multipart).

        The gateway maps ``image`` -> ``inputs.init_image`` and ``mask`` -> ``inputs.mask``
        (gateway plan: "image+mask -> inputs.init_image/mask"). So the canvas goes
        into the ``image`` field and the inpaint mask into the **dedicated** ``mask`` field —
        NOT as a second ``image``, otherwise no latent-noise mask applies and the
        whole image is recomputed (only the masked area should change).
        The gateway returns the full (inpainted) canvas — the center crop is done
        by the caller (world.py) itself.
        """
        model = params.get("model") or self.model
        width = params.get("width") or self.width
        height = params.get("height") or self.height
        width = round(width / 8) * 8 or 1024
        height = round(height / 8) * 8 or 1024

        ref_bytes = self._collect_ref_bytes(params)
        if not ref_bytes:
            logger.error(f"{self.name}: Inpaint ohne Eingangsbild/Maske — abgebrochen")
            return []
        # Canvas/references -> image, input_mask -> mask. Mask at the end (the field
        # name decides the assignment, not the position). Polarity depending on
        # ``mask_format``: 'grayscale' sends the L mask (white=edit) 1:1 as produced
        # (== mapblend_debug), 'openai' inverts to the OpenAI edits standard
        # (RGBA, transparent = to edit).
        files: list = []
        mask_part = None
        for title, raw in ref_bytes:
            if "mask" in title.lower():
                _mbytes = self._to_openai_mask(raw) if self.mask_format == "openai" else raw
                mask_part = ("mask", (f"{title}.png", _mbytes, "image/png"))
            else:
                files.append(("image", (f"{title}.png", raw, "image/png")))
        if mask_part:
            files.append(mask_part)

        # Form fields: all values as string (multipart). Extra params + LoRAs last.
        data: Dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "size": f"{width}x{height}",
            "response_format": self.response_format,
        }
        steps = params.get("num_inference_steps") or self.num_inference_steps
        if steps:
            data["steps"] = steps
        if negative_prompt:
            data["negative_prompt"] = negative_prompt
        seed = params.get("seed")
        if seed and seed > 0:
            data["seed"] = seed
        self._apply_lora_params(data, params)
        if self.extra_params:
            data.update(self.extra_params)
        data = {k: str(v) for k, v in data.items()}

        _img_n = sum(1 for f, _ in files if f == "image")
        _mask_info = f"1 mask [{self.mask_format}]" if mask_part else "KEINE mask"
        logger.info(f"{self.name}: Starte Inpaint/edits (Alias {model}, {width}x{height}, "
                    f"{_img_n} image + {_mask_info})")
        try:
            resp = self._post_gateway("edits", files=files, data=data)
            return self._parse_image_response(resp)
        except requests.Timeout:
            logger.error(f"{self.name}: Timeout nach {self.timeout}s")
            return []
        except RuntimeError:
            return []
        except Exception as e:
            logger.error(f"{self.name}: Fehler: {e}")
            return []
