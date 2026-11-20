"""Contact sheets of the template dialog's drawing (``garment_preview.shapes``): every option of every parameter of
every template kind side by side on one body — for checking by eye that each option is drawn the way the build makes
it and that the options of one parameter can be told apart (``scripts/smoke_garment_preview_options.py`` checks the
same numerically, ``scripts/garment_preview_sheets.py`` writes the sheets).

* ``model_front(glb)`` — the plain body's own front (an orthographic projection of its triangles, shaded by the
  normal) with the ``front_camera`` mapping, so the drawing registers EXACTLY (no silhouette guess);
* ``option_sets()`` — per kind the parameters and the values tried (every choice; three values of a number), each
  in the context that makes it apply (``garment_template.validate_params`` resets a field a context does not read);
* ``cloth_mask(drawn, w, h)`` — the cloth as the dialog draws it (every fill but the collar / lapel, less the cuts,
  plus the collar / lapel over them);
* ``render(base, drawn, colour)`` / ``sheet(tiles, title)`` — the dialog's look (``TemplateOverlay.tsx``) in PIL.

Nothing here touches a world: the caller hands the GLB bytes in.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

#: Fills drawn over the openings (``TemplateOverlay.tsx`` OVER_ROLES).
OVER_ROLES = ("collar", "lapel")


def model_front(glb: bytes, height_px: int = 1500) -> Tuple[Any, Dict[str, Any]]:
    """``(RGBA picture, frame)`` of the plain body seen from the front (glTF +z towards the camera): the triangles
    painted back to front, shaded by the normal's z; ``frame`` = ``garment_preview.frame_of_mask`` + ``camera``."""
    import numpy as np
    from PIL import Image, ImageDraw
    from app.core import front_camera, glb_mesh
    from app.core import garment_preview as gp
    arr = glb_mesh.body_arrays(glb)
    P = np.asarray(arr.positions, float)
    F = np.asarray(arr.faces, int).reshape(-1, 3)
    cam = front_camera.camera_for((P[:, 0].min(), P[:, 0].max(), P[:, 1].min(), P[:, 1].max()), height_px)
    col = cam["w"] / 2.0 + (P[:, 0] - cam["cx"]) * cam["ppm"]
    row = cam["h"] / 2.0 - (P[:, 1] - cam["cy"]) * cam["ppm"]
    tri = P[F]
    nrm = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    nrm /= np.maximum(np.linalg.norm(nrm, axis=1), 1e-12)[:, None]
    order = np.argsort(tri[:, :, 2].mean(axis=1))
    im = Image.new("RGBA", (cam["w"], cam["h"]), (0, 0, 0, 0))
    dr = ImageDraw.Draw(im)
    for i in order:
        g = int(120 + 110 * abs(float(nrm[i, 2])))
        a, b, c = F[i]
        dr.polygon([(col[a], row[a]), (col[b], row[b]), (col[c], row[c])], fill=(g, g - 8, g - 16, 255))
    mask = np.asarray(im)[:, :, 3] >= gp.ALPHA_MIN
    frame = dict(gp.frame_of_mask(mask), camera=cam)
    return im, frame


def _base(kind: str) -> Dict[str, Any]:
    return {"kind": kind}


def option_sets() -> List[Dict[str, Any]]:
    """``[{kind, param, values, context, label}]``: every parameter the dialog shows per kind (``KIND_FIELDS`` less
    ``kind`` and ``opacity`` — a material-only field, ``MATERIAL_ONLY``), every choice / three numbers, in a context
    where it applies."""
    from app.core import garment_template as gt
    ctx: Dict[Tuple[str, str], Dict[str, Any]] = {
        ("top", "neckline"): {"shoulders": "covered"},
        ("dress", "neckline"): {"shoulders": "covered", "length_m": 0.6},
        ("top", "neck_depth_m"): {"shoulders": "covered", "neckline": "v"},
        ("dress", "neck_depth_m"): {"shoulders": "covered", "neckline": "v"},
        ("jacket", "neck_depth_m"): {"neckline": "v"},
        ("top", "sleeves"): {"shoulders": "covered"},
        ("dress", "sleeves"): {"shoulders": "covered"},
        ("jacket", "sleeves"): {},
        ("top", "sleeve_fit"): {"shoulders": "covered", "sleeves": "long"},
        ("dress", "sleeve_fit"): {"shoulders": "covered", "sleeves": "long"},
        ("jacket", "sleeve_fit"): {"sleeves": "long"},
        ("top", "shoulders"): {"sleeves": "short"},
        ("dress", "shoulders"): {"sleeves": "short"},
        ("jacket", "collar"): {"sleeves": "long"},
        ("jacket", "front"): {"sleeves": "long"},
        ("skirt", "slit"): {"slit_m": 0.25},
        ("dress", "slit"): {"slit_m": 0.25},
        ("skirt", "slit_m"): {"slit": "left"},
        ("dress", "slit_m"): {"slit": "left"},
        ("briefs", "string_width_m"): {"sides": "string"},
        ("briefs", "fit"): {"leg_length_m": 0.15},
        ("tights", "garters"): {"tights_style": "thigh_high"},
        ("dress", "fit"): {"shoulders": "covered", "length_m": 0.6},
        ("tights", "waistband"): {"tights_style": "tights"},
        ("trousers", "hem"): {"leg_shape": "skinny", "trouser_length": "full", "seat": "fitted"},
    }
    for k in ("top", "dress"):
        for f in gt.OFF_SHOULDER_FIELDS:
            ctx[(k, f)] = {"shoulders": "off_shoulder", "sleeves": "short", "lacing": "front"}
    numbers = {"length_m": (0.3, 0.55, 0.8), "flare": (0.0, 0.5, 1.0), "slit_m": (0.1, 0.25, 0.45),
               "band_m": (0.01, 0.03, 0.05), "band_drop_m": (0.02, 0.05, 0.08), "lace_depth_m": (0.05, 0.15, 0.3),
               "sleeve_fit": (0.0, 0.5, 1.0), "fit": (0.0, 0.5, 1.0), "neck_depth_m": (0.05, 0.12, 0.22),
               "leg_cut": (0.0, 0.5, 1.0), "back_coverage": (0.0, 0.3, 1.0), "side_width_m": (0.01, 0.05, 0.1),
               "leg_length_m": (0.0, 0.1, 0.25), "string_width_m": (0.004, 0.01, 0.02),
               "cup_coverage": (0.3, 0.7, 1.0), "push_up": (0.0, 0.5, 1.0), "underband_m": (0.0, 0.03, 0.08)}
    out = []
    for kind in gt.BUILT_KINDS:
        for param in gt.KIND_FIELDS.get(kind, ()):
            if param in ("kind", "opacity"):
                continue
            kind_, rule, _d = gt.PARAM_SPEC[param]
            values = list(rule) if kind_ == "choice" else list(numbers.get(param, (rule[0], (rule[0] + rule[1]) / 2,
                                                                                    rule[1])))
            context = dict(ctx.get((kind, param), {}))
            if param == "neckline":
                # the corset top edges apply to a top / dress with straps only (``validate_params``)
                cov = [v for v in values if v not in gt.STRAPLESS_NECKLINES]
                out.append({"kind": kind, "param": param, "values": cov, "context": context, "label": param})
                if kind in ("top", "dress"):
                    out.append({"kind": kind, "param": param, "values": list(gt.STRAPLESS_NECKLINES),
                                "context": {"shoulders": "straps"}, "label": "neckline (straps)"})
                continue
            out.append({"kind": kind, "param": param, "values": values, "context": context, "label": param})
    return out


def params_for(kind: str, param: str, value: Any, context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The validated params of one option, None when ``validate_params`` resets it (the option does not apply)."""
    from app.core import garment_template as gt
    raw = dict(_base(kind), **context)
    raw[param] = value
    p, _errors = gt.validate_params(raw)
    if p[param] != (round(value, 3) if isinstance(value, float) else value):
        return None
    return p


def cloth_mask(drawn: Dict[str, Any], w: int, h: int):
    """The cloth as the dialog shows it (bool h x w): the union of the fills under the openings less every cut, plus
    the fills drawn over them."""
    import numpy as np
    from PIL import Image, ImageDraw
    under = Image.new("L", (w, h), 0)
    du = ImageDraw.Draw(under)
    over = Image.new("L", (w, h), 0)
    do = ImageDraw.Draw(over)
    for s in drawn["shapes"]:
        pts = [tuple(q) for q in s["points"]]
        if len(pts) < 3:
            continue
        if s["kind"] == "fill":
            (do if s["role"] in OVER_ROLES else du).polygon(pts, fill=255)
    for s in drawn["shapes"]:
        if s["kind"] == "cut" and len(s["points"]) >= 3:
            du.polygon([tuple(q) for q in s["points"]], fill=0)
    return (np.asarray(under) > 0) | (np.asarray(over) > 0)


def line_mask(drawn: Dict[str, Any], w: int, h: int, width: int = 3):
    """The guides (lines / dashes) drawn as strokes (bool h x w)."""
    import numpy as np
    from PIL import Image, ImageDraw
    im = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(im)
    for s in drawn["shapes"]:
        if s["kind"] in ("line", "dash") and s["role"] != "dim" and len(s["points"]) >= 2:
            d.line([tuple(q) for q in s["points"]], fill=255, width=width)
    return np.asarray(im) > 0


def render(base, drawn: Dict[str, Any], colour: Tuple[int, int, int] = (79, 140, 255)):
    """The picture with the piece on it, as ``TemplateOverlay.tsx`` draws it (cloth at 0.6 over the picture with its
    outline, collar / lapel over the openings, guides in red, dashes dashed, the marks as text)."""
    import numpy as np
    from PIL import Image, ImageDraw, ImageFilter
    w, h = base.size
    img = Image.new("RGBA", (w, h), (255, 255, 255, 255))
    img.alpha_composite(base)
    m = cloth_mask(drawn, w, h)
    edge = Image.fromarray((m * 255).astype("uint8")).filter(ImageFilter.MaxFilter(5))
    ring = (np.asarray(edge) > 0) & ~m
    layer = np.zeros((h, w, 4), "uint8")
    layer[m] = (*colour, int(255 * 0.6))
    layer[ring] = (31, 79, 209, 255)
    img.alpha_composite(Image.fromarray(layer, "RGBA"))
    d = ImageDraw.Draw(img)
    for s in drawn["shapes"]:
        pts = [tuple(q) for q in s["points"]]
        if s["kind"] in ("line", "dash") and len(pts) >= 2:
            colr = (192, 57, 43) if s["role"] == "dim" else (209, 36, 47)
            wid = 3 if s["role"].endswith("edge") else 2
            if s["kind"] == "line":
                d.line(pts, fill=colr, width=wid)
            else:
                _dashed(d, pts, colr, wid)
    for mk in drawn.get("marks") or []:
        x, y = mk["x"], mk["y"]
        tw = d.textlength(mk["text"], font=_font())
        x = x - tw if mk["anchor"] == "end" else x - tw / 2 if mk["anchor"] == "middle" else x
        d.text((x, y - 8), mk["text"], fill=(17, 17, 17), stroke_width=2, stroke_fill=(255, 255, 255), font=_font())
    return img


def _font(size: int = 15):
    from PIL import ImageFont
    for name in ("DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _dashed(d, pts, colour, width, on: float = 8.0, off: float = 6.0) -> None:
    import math
    carry, draw = 0.0, True
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        seg = math.hypot(x1 - x0, y1 - y0)
        pos = 0.0
        while pos < seg:
            step = min((on if draw else off) - carry, seg - pos)
            if draw:
                a, b = pos / seg, (pos + step) / seg
                d.line([(x0 + (x1 - x0) * a, y0 + (y1 - y0) * a), (x0 + (x1 - x0) * b, y0 + (y1 - y0) * b)],
                       fill=colour, width=width)
            pos += step
            carry += step
            if carry >= (on if draw else off) - 1e-9:
                carry, draw = 0.0, not draw


def crop_box(drawns: List[Dict[str, Any]], w: int, h: int, margin: int = 40) -> Tuple[int, int, int, int]:
    """One box round every option's shapes and marks (the same crop for every tile of a sheet)."""
    xs, ys = [], []
    for dr in drawns:
        for s in dr["shapes"]:
            for x, y in s["points"]:
                xs.append(x)
                ys.append(y)
        for mk in dr.get("marks") or []:
            xs.append(mk["x"])
            ys.append(mk["y"])
    if not xs:
        return 0, 0, w, h
    return (max(0, int(min(xs)) - margin), max(0, int(min(ys)) - margin), min(w, int(max(xs)) + margin + 260),
            min(h, int(max(ys)) + margin))


def sheet(tiles: List[Tuple[str, Any]], title: str):
    """The tiles side by side (each ``(label, image)``), the label over each, the title on top."""
    from PIL import Image, ImageDraw
    tw = max(im.size[0] for _l, im in tiles)
    th = max(im.size[1] for _l, im in tiles)
    pad, head = 10, 44
    out = Image.new("RGB", (pad + len(tiles) * (tw + pad), head + 24 + th + pad), (255, 255, 255))
    d = ImageDraw.Draw(out)
    d.text((pad, 8), title, fill=(0, 0, 0), font=_font(20))
    for i, (label, im) in enumerate(tiles):
        x = pad + i * (tw + pad)
        d.text((x, head - 4), label, fill=(20, 20, 120), font=_font(18))
        out.paste(im.convert("RGB"), (x, head + 20))
    return out
