#!/usr/bin/env python3
"""Face cleanup version 5 — a FOLDED flap is settled onto the lid, not stacked onto anchors
(``face_cleanup._settle_flaps``) — on a synthetic head, expectations derived by hand.

Usage: ./.venv/bin/python scripts/smoke_face_cleanup_visor.py

No world, no server, no hub, no Blender. The fixture is the head of ``smoke_face_cleanup.py`` (sphere R = 95.9 mm,
160 rings x 320 segments, ~1.9 mm between neighbours on the face, lash paint 22 x 7 mm around each eye centre, lips
painted) with, at each eye:

- an EYE OPENING with an eyeball in it: the front vertices within 5 mm of the eye centre pushed 2.2 mm in along the
  radius (Lirien's eyeball sits 2.2 mm under the lid);
- a VISOR: the upper-lid band 6 .. 10 mm above the eye centre, 12 mm either side, folded over the eye. Across the
  band (s = 0 at its lower row, 1 at its upper row) a vertex moves 6 sin(pi s) mm out along the radius and
  8 sin(pi s) mm DOWN (no taper: the band's ends are torn walls, stretched triangles to the unmoved skin beside
  them). The upper half of the band (the visor's top side, root at the upper row) runs from 10 mm down to the tip
  at 8 - 8 = 0 mm, in front of the eye centre; the lower half (its underside) runs from the tip back UP to its root
  at 6 mm — upside down: its triangles face into the head in the front view. The band stays 1 mm clear of the
  opening (6 > 5): the opening's ring is the eye, not the visor's root.

Hand-derived expectations:
- FIXTURE: the rings lie pi R / 160 = 1.88 mm apart, so the 4 mm band holds a row within 0.94 mm of its middle
  (|s - 0.5| <= 0.235): that row stands 6 sin(0.265 pi) = 4.4 mm proud along the radius (the 8 mm drop runs across
  the radius at the eye's height and only adds) — "more than 4.0 mm proud" is the gate; 56 band vertices move.
- BEFORE: the band is more than EYE_FREE_MM (2.5) proud of the lid wherever 6 sin(pi s) > 2.5 + the lid's rise —
  the flap set; the fold of version 2 put each flap vertex INSET_MM under ONE anchor, so a triangle whose corners
  took anchors on the two root rows spanned the 4 mm between them upside down (the visor's underside) — that is the
  fails-on-the-old-code proof below.
- AFTER (version 5): the flap set grows by its foot — every connected band vertex more than FLAP_FOOT_MM = 1.0 mm
  proud (6 sin(pi s) > 1 for all but the rows within s < 0.054 of a root, i.e. within 0.2 mm: none of the lattice's)
  and the corners of the underside's upside-down triangles — so every visor vertex moves (gate: more than 90 %).
  The flap's nodes take the mean lid-plane position of their neighbours with the root rows and the skin beside the
  band's ends held (a Tutte map of a disc onto the band between its roots: no triangle of it turns over), at the
  height of the membrane the anchors span: the sphere around the band reads 0, so the membrane lies at 0 and at
  most down to the opening's 2.2 mm where the lid follows it, INSET_MM = 0.6 mm under it. So every moved vertex ends
  at most 0.1 mm above the sphere (the flap is gone, no visor in front of the eye) and at most 2.2 + 0.6 = 2.8 mm
  under it; NO non-degenerate triangle with a moved corner faces into the head (normal against the radius); the eye
  region holds no more spikes (nodes over SPIKE_DEG = 120 degrees) than the same head WITHOUT the visor — the
  coordinator's gate "at most the raw mesher's count", here the head before the flap was folded on; the eyeball
  (the opening's vertices, deeper than ANCHOR_DEPTH_MM under the smooth base: pinned) keeps its exact bytes; vertex
  count, index order and UVs are unchanged; everything outside the eye regions and the mouth region keeps its
  bytes; the result passes ``validate_source``; a second run gives the same bytes.
- OLD CODE: ``face_cleanup.py`` at 803ec60c (version 4, the fold of version 2) leaves upside-down triangles there.
"""
import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import numpy as np  # noqa: E402

import smoke_face_cleanup as base  # noqa: E402  (fixture helpers; its main() runs only as a script)

FAILS = []
OLD_COMMIT = "803ec60c"
R, HEAD_Y, EYE_Y, EYE_X, MM = base.R, base.HEAD_Y, base.EYE_Y, base.EYE_X, base.MM


def check(cond, label):
    print(("OK   " if cond else "FAIL ") + label)
    if not cond:
        FAILS.append(label)


def build(visor=True):
    """``(glb, P, F, U, masks)`` of the head with an eye opening at each eye and, with ``visor``, the folded visor."""
    rings, segments = 160, 320
    P, U = [], []
    for i in range(rings + 1):
        theta = np.pi * i / rings
        for j in range(segments):
            phi = 2 * np.pi * j / segments
            x, y, z = R * np.sin(theta) * np.sin(phi), HEAD_Y + R * np.cos(theta), R * np.sin(theta) * np.cos(phi)
            P.append((x, y, z))
            U.append(base.planar_uv(x, y, z >= 0))
    P, U = np.array(P, np.float64), np.array(U, np.float64)
    F = []
    for i in range(rings):
        for j in range(segments):
            a, b = i * segments + j, i * segments + (j + 1) % segments
            c, d = (i + 1) * segments + j, (i + 1) * segments + (j + 1) % segments
            F += [(a, c, b), (b, c, d)]
    F = np.array(F, np.int64)
    front = P[:, 2] > 0
    radial = (P - np.array([0, HEAD_Y, 0])) / R
    opening = np.zeros(len(P), bool)
    band = np.zeros(len(P), bool)
    out = np.zeros(len(P))
    down = np.zeros(len(P))
    for cx in (EYE_X, -EYE_X):
        dx, dy = P[:, 0] - cx, P[:, 1] - EYE_Y
        opening |= front & (np.hypot(dx, dy) < 5 * MM)
        here = front & (np.abs(dx) < 12 * MM) & (dy >= 6 * MM) & (dy <= 10 * MM)
        band |= here
        s = np.clip((dy - 6 * MM) / (4 * MM), 0.0, 1.0)
        lift = np.sin(np.pi * s)
        out = np.where(here, 6 * MM * lift, out)
        down = np.where(here, 8 * MM * lift, down)
    P = P - radial * (2.2 * MM) * opening[:, None]
    if visor:
        P = P + radial * out[:, None]
        P[:, 1] -= down
    visor_moved = band & (out > 0) if visor else np.zeros(len(P), bool)
    box = np.array([(sx * 0.12, y, sz * 0.06) for y in (base.BOTTOM, 0.33) for sx in (-1, 1) for sz in (-1, 1)])
    box_f = np.array([(0, 1, 2), (1, 3, 2), (4, 6, 5), (5, 6, 7), (0, 4, 1), (1, 4, 5),
                      (2, 3, 6), (3, 7, 6), (0, 2, 4), (2, 6, 4), (1, 5, 3), (3, 5, 7)], np.int64) + len(P)
    P = np.vstack([P, box])
    U = np.vstack([U, np.full((8, 2), (0.5, 0.95))])
    F = np.vstack([F, box_f])
    N = P - np.array([0, HEAD_Y, 0])
    N /= np.linalg.norm(N, axis=1)[:, None]
    pad = np.zeros(8, bool)
    masks = {"opening": np.concatenate([opening, pad]), "visor": np.concatenate([visor_moved, pad])}
    return base.pack(P, N, U, F, base.texture_png(True)), P, F, U, masks


def eye_masks(P):
    """The eye regions (an ellipse 34 x 27 mm around each eye centre, front half)."""
    out = []
    for cx in (EYE_X, -EYE_X):
        out.append((P[:, 2] > 0) & (((P[:, 0] - cx) / (34 * MM)) ** 2 + ((P[:, 1] - EYE_Y) / (27 * MM)) ** 2 < 1))
    return out


def spikes(P, F, region):
    """Nodes of ``region`` whose largest dihedral angle (non-degenerate triangles) exceeds face_cleanup.SPIKE_DEG."""
    from app.core import face_cleanup as fc
    node, _welded = fc._weld(P, F, MM)
    n = int(node.max()) + 1
    Q = np.zeros((n, 3))
    Q[node] = P
    G = node[F]
    G = G[(G[:, 0] != G[:, 1]) & (G[:, 1] != G[:, 2]) & (G[:, 0] != G[:, 2])]
    normal = np.cross(Q[G[:, 1]] - Q[G[:, 0]], Q[G[:, 2]] - Q[G[:, 0]])
    area = np.linalg.norm(normal, axis=1)
    keep = area > (fc.DEGENERATE_MM * MM) ** 2
    G, normal = G[keep], normal[keep] / area[keep][:, None]
    edges = np.sort(np.concatenate([G[:, [0, 1]], G[:, [1, 2]], G[:, [2, 0]]]), 1)
    face = np.tile(np.arange(len(G)), 3)
    key = edges[:, 0] * n + edges[:, 1]
    order = np.argsort(key, kind="stable")
    key, face, edges = key[order], face[order], edges[order]
    pair = np.flatnonzero(key[1:] == key[:-1])
    angle = np.degrees(np.arccos(np.clip((normal[face[pair]] * normal[face[pair + 1]]).sum(1), -1, 1)))
    worst = np.zeros(n)
    np.maximum.at(worst, edges[pair, 0], angle)
    np.maximum.at(worst, edges[pair, 1], angle)
    return int((worst[np.unique(node[region])] > fc.SPIKE_DEG).sum())


def upside_down(P0, P1, F):
    """Non-degenerate triangles with a moved corner whose normal points into the head (against the radius)."""
    from app.core import face_cleanup as fc
    moved = np.any(P1 != P0, axis=1)
    faces = F[moved[F].any(1)]
    normal = np.cross(P1[faces[:, 1]] - P1[faces[:, 0]], P1[faces[:, 2]] - P1[faces[:, 0]])
    area = np.linalg.norm(normal, axis=1)
    centre = P1[faces].mean(1) - np.array([0, HEAD_Y, 0])
    return int((((normal * centre).sum(1) < 0) & (area > (fc.DEGENERATE_MM * MM) ** 2)).sum())


def old_module():
    source = subprocess.run(["git", "-C", str(ROOT), "show", f"{OLD_COMMIT}:app/core/face_cleanup.py"],
                            check=True, capture_output=True, text=True).stdout
    path = Path(tempfile.mkdtemp()) / "face_cleanup_old.py"
    path.write_text(source, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("face_cleanup_old", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    from app.core import face_cleanup as fc
    from app.core.glb_mesh import static_arrays
    from app.core.mesh_source import validate_source

    glb, _P, _F, _U, masks = build()
    plain, *_ = build(visor=False)
    P0, F0, U0, *_ = static_arrays(glb)
    Pp, Fp, *_ = static_arrays(plain)
    opening, visor = masks["opening"], masks["visor"]
    regions = eye_masks(P0)
    proud = (np.linalg.norm(P0[visor] - np.array([0, HEAD_Y, 0]), axis=1) - R) / MM
    check(proud.max() > 4.0 and visor.sum() == 56, f"fixture: the visor stands {proud.max():.2f} mm proud ({int(visor.sum())} vertices)")
    raw_spikes = [spikes(Pp, Fp, r) for r in regions]
    print(f"     spikes per eye without the visor: {raw_spikes}")
    out, record = fc.clean_face(glb)
    check(record["version"] == 5, f"version {record['version']}")
    eyes = record["eyes"].get("eyes") or []
    check(record["eyes"]["status"] == "applied" and all(e.get("status") == "applied" for e in eyes),
          f"the fold applied at both eyes ({[e.get('status') for e in eyes]})")
    P1, F1, U1, *_ = static_arrays(out)
    moved = np.any(P1 != P0, axis=1)
    height = (np.linalg.norm(P1[moved] - np.array([0, HEAD_Y, 0]), axis=1) - R) / MM
    check(visor.sum() > 0 and moved[visor].mean() > 0.9,
          f"the visor's vertices moved: {int(moved[visor].sum())} of {int(visor.sum())}")
    check(height.max() <= 0.1 and height.min() >= -2.8,
          f"every moved vertex ends {height.min():.2f} .. {height.max():.2f} mm on the sphere (-2.8 .. 0.1): no visor left")
    flipped = upside_down(P0, P1, F0)
    check(flipped == 0, f"no triangle with a moved corner faces into the head ({flipped})")
    after = [spikes(P1, F1, r) for r in regions]
    check(all(a <= b for a, b in zip(after, raw_spikes)), f"spikes per eye {after} <= without the visor {raw_spikes}")
    check(np.array_equal(P1[opening], P0[opening]), f"the eyeball keeps its exact bytes ({int(opening.sum())} vertices)")
    outside = ~(regions[0] | regions[1])
    outside &= ~((np.abs(P0[:, 0]) < 31 * MM) & (np.abs(P0[:, 1] - base.MOUTH_Y) < 17 * MM))
    check(np.array_equal(P1[outside], P0[outside]), f"outside the regions: positions byte-identical ({int(outside.sum())})")
    check(len(P1) == len(P0) and np.array_equal(F1, F0) and np.array_equal(U1, U0), "vertex count, index order and UVs unchanged")
    check(validate_source(out)["ok"], "the result passes validate_source")
    again, _ = fc.clean_face(glb)
    check(again == out, "deterministic: a second run gives the same bytes")

    old = old_module()
    out_old, _ = old.clean_face(glb)
    Po, *_ = static_arrays(out_old)
    flipped_old = upside_down(P0, Po, F0)
    spikes_old = [spikes(Po, F0, r) for r in regions]
    check(flipped_old > 0 or any(a > b for a, b in zip(spikes_old, raw_spikes)),
          f"face_cleanup at {OLD_COMMIT}: {flipped_old} triangles face into the head, spikes per eye {spikes_old}")

    print()
    print("FAILED" if FAILS else "ALL OK", f"({len(FAILS)} failures)")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
