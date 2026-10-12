"""Pinned Real-ESRGAN ONNX inference, tiled on CPU with bounded memory."""
import hashlib
import io
import math
import os
import tempfile
import threading
import time
from pathlib import Path

import numpy as np
import requests
from PIL import Image

from app.imagegen.base import ImageBackend
from app.imagegen.upscale import dimensions

MODEL_REVISION = '899dc1e4b22bbf1955c2f1739c085edc080cb366'
MODEL_SHA256 = '924ebad6532777303582d4ce7811849b88869231a3ae7093e0f21200249df8d5'
MODEL_SIZE = 4866396
MODEL_URL = f'https://huggingface.co/jonathanst29/tinier-upscale-models/resolve/{MODEL_REVISION}/realesr-general-x4v3.onnx'
MODEL_PATH = Path(__file__).resolve().parents[3] / 'models/upscale/realesr-general-x4v3.onnx'
_INIT_LOCK = threading.Lock()
_RUN_LOCK = threading.Lock()
_session = None
_retry_at = 0.0


def verify_model(path):
    """Reject and remove any file that is not the pinned artifact."""
    if not path.is_file():
        return False
    valid = path.stat().st_size == MODEL_SIZE and hashlib.sha256(path.read_bytes()).hexdigest() == MODEL_SHA256
    if not valid:
        path.unlink(missing_ok=True)
    return valid


def get_session():
    """Download atomically once, then share the verified ORT session."""
    global _session, _retry_at
    with _INIT_LOCK:
        if _session is not None:
            return _session
        if time.monotonic() < _retry_at:
            raise RuntimeError('Local upscale model is temporarily unavailable')
        temporary = None
        try:
            if not verify_model(MODEL_PATH):
                MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(dir=MODEL_PATH.parent, suffix='.tmp', delete=False) as handle:
                    temporary = Path(handle.name)
                    with requests.get(MODEL_URL, stream=True, timeout=60) as response:
                        response.raise_for_status()
                        count = 0
                        for chunk in response.iter_content(65536):
                            count += len(chunk)
                            if count > MODEL_SIZE:
                                raise ValueError('Local upscale download exceeds the pinned size')
                            handle.write(chunk)
                if not verify_model(temporary):
                    raise ValueError('Local upscale model checksum mismatch')
                os.replace(temporary, MODEL_PATH)
            import onnxruntime as ort
            _session = ort.InferenceSession(str(MODEL_PATH), providers=['CPUExecutionProvider'])
            return _session
        except Exception:
            _retry_at = time.monotonic() + 600
            raise
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def tiled_upscale(image, session, tile_size=256, overlap=16):
    """Infer expanded tiles, discard the halo, and immediately store uint8 RGB."""
    source = np.asarray(image.convert('RGB'))
    height, width = source.shape[:2]
    result = np.empty((height * 4, width * 4, 3), dtype=np.uint8)
    name = session.get_inputs()[0].name
    for y in range(0, height, tile_size):
        for x in range(0, width, tile_size):
            right, bottom = min(x + tile_size, width), min(y + tile_size, height)
            x0, y0 = max(0, x - overlap), max(0, y - overlap)
            x1, y1 = min(width, right + overlap), min(height, bottom + overlap)
            tensor = np.ascontiguousarray(source[y0:y1, x0:x1].transpose(2, 0, 1)[None], dtype=np.float32) / 255
            output = session.run(None, {name: tensor})[0]
            if output.shape != (1, 3, (y1-y0)*4, (x1-x0)*4) or not np.isfinite(output).all():
                raise ValueError('Invalid local upscale tensor')
            crop = output[0, :, (y-y0)*4:(bottom-y0)*4, (x-x0)*4:(right-x0)*4]
            result[y*4:bottom*4, x*4:right*4] = np.clip(np.rint(crop.transpose(1, 2, 0) * 255), 0, 255).astype(np.uint8)
    return Image.fromarray(result)


class LocalUpscaleBackend(ImageBackend):
    """Fixed model on a serialized CPU channel; construction never performs I/O."""
    REQUIRES_URL = False

    def __init__(self, name, api_url, cost, env_prefix, *, upscale_scale=2, color_fix=True, max_side=4096):
        super().__init__(name, api_url, cost, 'local_upscale', env_prefix)
        self._available = time.monotonic() >= _retry_at
        self.category = 'upscale'
        self.upscale_scale = min(4, max(1, float(upscale_scale)))
        self.color_fix = bool(color_fix)
        self.max_side = min(8192, max(512, int(max_side)))
        self.model = f'realesr-general-x4v3@{MODEL_REVISION}'

    def check_availability(self):
        if time.monotonic() < _retry_at:
            self._mark_unavailable()
            return False
        self._mark_available()
        return True

    def _generate(self, prompt, negative_prompt, params):
        with Image.open(io.BytesIO(params['image_bytes'])) as decoded:
            decoded.load()
            image = decoded.convert('RGB')
        longest = max(image.size)
        target = min(longest * self.upscale_scale, self.max_side)
        target_size = dimensions(image, target)
        if target > longest:
            # The intermediate RGB buffer stays within 8192² pixels even
            # when the administrator chooses an 8192-pixel final cap.
            intermediate_side = min(8192, 2 * self.max_side)
            if 4 * longest > intermediate_side:
                image = image.resize(dimensions(image, math.ceil(intermediate_side / 4)), Image.Resampling.LANCZOS)
            with _RUN_LOCK:
                image = tiled_upscale(image, get_session())
            image = image.resize(target_size, Image.Resampling.LANCZOS)
        out = io.BytesIO()
        image.save(out, format='PNG')
        return [out.getvalue()]
