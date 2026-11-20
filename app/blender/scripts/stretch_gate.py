"""The pure half of the template drape's stretch gate (``garment_template_build.py``): numpy only, no bpy — the
Blender script imports it, and ``scripts/smoke_stretch_gate.py`` checks it by hand without Blender.

The stretch of an edge is its draped length over its built length. Two ratios come out of one drape:

* ``all`` — every edge but the degenerate ones built shorter than ``MIN_EDGE_M`` (A144: 0.1 mm -> 0.19 mm read as
  1.87). Its 99th percentile is the drape's ``stretch_p99``, as before.
* ``gate`` — what ``stretch_max`` (the gated row, limit 1.3) is read from. Bug round 2026-11-20: an edge built
  shorter than ``GATE_MIN_REST_M``, or one that grew by less than ``GATE_MIN_GROW_M``, is no visible stretch of
  the cloth, so it counts as 1.0 here. Kira's blazer (V-neck 0.26 m) had a 1.33 mm edge at the V's bottom that the
  drape drew to 2.43 mm — ratio 1.82, a 1.1 mm change nobody can see — and it refused the whole piece. A real tear
  still fails: an edge of 4 mm drawn to 5.3 mm (1.325, +1.3 mm) is gated as before.

  The two floors together are the rule, on purpose: an edge counts when it was built at least 3 mm long AND grew
  by at least 1 mm. At the limit ratio 1.3 the 1 mm growth is reached only from 1 / 0.3 = 3.33 mm on, so an edge
  built 3.0-3.33 mm long may reach a ratio up to 1.33 unseen (3.0 -> 3.95 mm: 1.317, +0.95 mm). That band is
  accepted: what the gate is for is a change one can see on the cloth, and under 1 mm there is none; from
  3.33 mm on the ratio alone decides, as before.
"""
import numpy as np

#: Edges built shorter than this are no fabric (A144): left out of both ratios.
MIN_EDGE_M = 0.001
#: Bug round 2026-11-20: the gated ratio leaves out edges built shorter than this ...
GATE_MIN_REST_M = 0.003
#: ... and edges that grew by less than this in the drape (absolute, metres).
GATE_MIN_GROW_M = 0.001


def stretch(rest_len, draped_len):
    """``(gate, all)`` — the per-edge stretch ratios of a drape (``rest_len`` / ``draped_len`` = each edge's built
    and draped length in metres, same order). ``all`` is 1.0 for an edge under ``MIN_EDGE_M``; ``gate`` is 1.0
    besides for an edge under ``GATE_MIN_REST_M`` or one that grew by less than ``GATE_MIN_GROW_M``."""
    rest = np.asarray(rest_len, np.float64)
    draped = np.asarray(draped_len, np.float64)
    ratio = draped / np.maximum(rest, 1e-6)
    every = np.where(rest < MIN_EDGE_M, 1.0, ratio)
    tiny = (rest < GATE_MIN_REST_M) | (draped - rest < GATE_MIN_GROW_M)
    return np.where(tiny, 1.0, every), every
