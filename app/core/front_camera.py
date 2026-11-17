"""A195 — the front orthographic camera of the dressed-figure render (template dialog).

STDLIB ONLY by contract: the Blender script ``figure_front.py`` imports this module inside Blender's own Python
(``_common.app_root_on_path``), the server imports it to read the picture back — so both sides use the ONE mapping.

Coordinates are the model's (glTF): x to the figure's left (= image right on a front view), y up, metres.
A front view looks along -z of the model (camera in front of a figure facing +z).

``camera_for(bbox, height_px, margin_m)``:
  * the framed box is the model box grown by ``margin_m`` on every side;
  * ``ppm`` (pixels per metre) = ``height_px`` / framed height;
  * ``w`` = ceil(framed width x ppm - 1e-4) (at least 1; the 1e-4 px absorbs float32 vertex noise), ``h`` = ``height_px``;
  * the camera centre: x = the framed box's x centre, y = its y centre;
  * Blender's ``ortho_scale`` spans the LARGER pixel side: max(w, h) / ppm (sensor fit AUTO).

``to_px(cam, x, y)`` = (w / 2 + (x - cx) x ppm, h / 2 - (y - cy) x ppm) — column, row of the pixel CORNER grid
(column 0 = the left edge of the picture); ``to_m`` is its inverse.
"""
import math

#: Default picture height (pixels) and margin (metres) of the dialog's render.
HEIGHT_PX = 1024
MARGIN_M = 0.04


def camera_for(bbox, height_px=HEIGHT_PX, margin_m=MARGIN_M):
    """``{w, h, ppm, cx, cy, ortho_scale}`` framing ``bbox`` = ``(xmin, xmax, ymin, ymax)`` (metres)."""
    xmin, xmax, ymin, ymax = (float(v) for v in bbox)
    if not (xmax > xmin and ymax > ymin):
        raise ValueError("empty model box")
    height_px = int(height_px)
    span_x = (xmax - xmin) + 2 * margin_m
    span_y = (ymax - ymin) + 2 * margin_m
    ppm = height_px / span_y
    w = max(1, int(math.ceil(span_x * ppm - 1e-4)))
    return {"w": w, "h": height_px, "ppm": ppm, "cx": (xmin + xmax) / 2.0, "cy": (ymin + ymax) / 2.0,
            "ortho_scale": max(w, height_px) / ppm}


def to_px(cam, x, y):
    """Picture (column, row) of the model point (x, y) — see the module docstring."""
    return (cam["w"] / 2.0 + (x - cam["cx"]) * cam["ppm"], cam["h"] / 2.0 - (y - cam["cy"]) * cam["ppm"])


def to_m(cam, col, row):
    """The model (x, y) of the picture point (col, row): the inverse of ``to_px``."""
    return (cam["cx"] + (col - cam["w"] / 2.0) / cam["ppm"], cam["cy"] - (row - cam["h"] / 2.0) / cam["ppm"])
