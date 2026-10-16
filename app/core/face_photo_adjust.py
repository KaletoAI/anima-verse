"""Local, deterministic face-photo exposure controls in linear light."""
import math
import numpy as np
from PIL import Image

PROBLEM = 'Light balance needs the face view (a cut-out head)'
MAX_PIXELS = 4096 * 4096


def check_size(size):
    if size[0] * size[1] > MAX_PIXELS:
        raise ValueError('Reference photo exceeds the decoded pixel limit (4096 × 4096 pixels)')


def _mirror_columns(axis, width):
    return np.floor(2*axis - np.arange(width) + .5).astype(int)


FIX = 'Use the face view as source or switch light balance off'


#: Defaults when a character has no remembered values (user decision
#: 2026-10-16: full light balance). NEUTRAL is the byte-exact identity.
DEFAULTS = {'balance': 1.0, 'tone_match': 1.0, 'brightness': 1.0}
NEUTRAL = {'balance': 0.0, 'tone_match': 0.0, 'brightness': 1.0}
TONE_MATCH_UNSUPPORTED = ('the face retexture backend does not support tone match '
                          '(needs node GLBFaceRetexture >= 1.1)')


def validated_params(params=None) -> dict:
    defaults = dict(DEFAULTS)
    if params is not None and (not isinstance(params, dict) or set(params) - defaults.keys()):
        raise ValueError('Unsupported face photo parameters')
    result = {**defaults, **(params or {})}
    for key, value in result.items():
        low, high = (0, 1) if key in ('balance', 'tone_match') else (.5, 1.5)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f'Invalid face photo parameter: {key}')
        result[key] = float(value)
    return result


def _blur(a, radius):
    for _ in range(3):
        for axis in (0, 1):
            pad = [(0, 0), (0, 0)]
            pad[axis] = (radius + 1, radius)
            c = np.cumsum(np.pad(a, pad, mode='edge'), axis=axis)
            a = (np.take(c, range(2*radius+1, c.shape[axis]), axis=axis)
                 - np.take(c, range(c.shape[axis]-2*radius-1), axis=axis)) / (2*radius+1)
    return a


def adjust(rgba: np.ndarray | Image.Image, *, balance: float, brightness: float) -> np.ndarray:
    """Return uint8 RGBA, preserving alpha and transparent background bytes."""
    params = validated_params({'balance': balance, 'brightness': brightness})
    balance, brightness = params['balance'], params['brightness']
    check_size(rgba.size if isinstance(rgba, Image.Image) else rgba.shape[1::-1])
    a = np.asarray(rgba.convert('RGBA') if isinstance(rgba, Image.Image) else rgba)
    if a.ndim != 3 or a.shape[2] != 4 or a.dtype != np.uint8:
        raise ValueError('Expected uint8 RGBA photo')
    result = a.copy()
    if balance == 0 and brightness == 1:
        return result
    # A byte lookup avoids full-size decode temporaries and keeps work float32.
    levels = np.arange(256, dtype=np.float32) / 255
    decoded = np.where(levels <= .04045, levels/12.92, ((levels+.055)/1.055)**2.4)
    lin = decoded[a[..., :3]]
    mask = a[..., 3] > 127
    gain = 1.
    if balance:
        rows, cols = np.where(mask)
        if mask.all() or len(cols) < 64 or len(np.unique(rows)) < 8 or np.ptp(cols) < 8:
            raise ValueError(PROBLEM)
        centres = [np.flatnonzero(row).mean() for row in mask if row.any()]
        cx = float(np.median(centres))
        h, w = mask.shape
        scale = min(1., 128 / max(h, w))
        sw, sh = max(8, round(w*scale)), max(8, round(h*scale))
        def resize(v, size, method):
            return np.asarray(Image.fromarray(v.astype(np.float32)).resize(size, method))
        m = resize(mask, (sw, sh), Image.Resampling.BOX)
        luminance = lin @ np.array([.2126, .7152, .0722], dtype=np.float32)
        ym = resize(luminance*mask, (sw, sh), Image.Resampling.BOX)
        # A narrower face-relative radius retains cheek exposure gradients in
        # the low pass; three box passes still suppress small facial features.
        radius = max(1, round((np.ptp(cols)+1)*sw/w/20))
        low = _blur(ym, radius) / np.maximum(_blur(m, radius), 1e-4)
        mirror = _mirror_columns(((2*cx+1)*sw/w - 1)/2, sw)
        valid = (mirror >= 0) & (mirror < sw)
        mirror = np.clip(mirror, 0, sw-1)
        both = (m > .5) & (m[:, mirror] > .5) & valid
        g = np.where(both, np.sqrt(np.maximum(low[:, mirror],1e-4)/np.maximum(low,1e-4)), 1.)
        g = _blur(np.clip(g,.5,2), max(1,radius//3))
        g = np.where(both, g, 1.)
        full_mirror = _mirror_columns(cx, w)
        valid_columns = (full_mirror >= 0) & (full_mirror < w)
        paired = mask & mask[:, np.clip(full_mirror, 0, w-1)] & valid_columns
        full_gain = resize(g, (w,h), Image.Resampling.BILINEAR)
        gain = np.where(paired, full_gain, 1.)[...,None] ** balance
    lin *= gain
    lin *= brightness
    np.clip(lin, 0, 1, out=lin)
    visible = a[...,3] > 0
    # Encode one channel at a time, retaining transparent RGB verbatim.
    for channel in range(3):
        values = lin[..., channel]
        dark = values <= .0031308
        encoded = np.power(values, np.float32(1/2.4))
        encoded *= 1.055
        encoded -= .055
        encoded[dark] = values[dark] * 12.92
        encoded *= 255
        np.rint(encoded, out=encoded)
        result[..., channel][visible] = encoded[visible].astype(np.uint8)
    return result
