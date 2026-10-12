"""Shared PNG output and cache identity contract for reference upscalers."""
import hashlib
import io
import json

from PIL import Image

IMPLEMENTATION_VERSION = 1
MAX_BYTES = 64 * 1024 * 1024


def dimensions(image, side):
    """Preserve aspect ratio, rounding to the nearest nonzero pixel."""
    ratio = side / max(image.size)
    return tuple(max(1, round(n * ratio)) for n in image.size)


def normalize_output(raw: bytes, max_side: int):
    """Decode, bound and encode RGB PNG; reduce the cap until the upload fits."""
    with Image.open(io.BytesIO(raw)) as decoded:
        if decoded.format != 'PNG':
            raise ValueError('Upscale output is not a PNG')
        decoded.load()
        image = decoded.convert('RGB')
    cap = min(int(max_side), max(image.size))
    while cap > 0:
        bounded = image if max(image.size) <= cap else image.resize(dimensions(image, cap), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        bounded.save(out, format='PNG')
        if out.tell() <= MAX_BYTES:
            return out.getvalue(), list(bounded.size)
        cap -= 512
    raise ValueError('Upscale PNG exceeds the 64 MB upload limit')


def cache_identity(image_bytes: bytes, backend):
    """Include every input that can affect the output, without credentials."""
    identity = {'photo_sha256': hashlib.sha256(image_bytes).hexdigest(),
                'backend': backend.name, 'api_type': backend.api_type,
                'model': getattr(backend, 'model', ''),
                'scale': backend.upscale_scale, 'color_fix': backend.color_fix,
                'max_side': backend.max_side, 'version': IMPLEMENTATION_VERSION}
    identity['key'] = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    return identity
