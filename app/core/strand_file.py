"""Reader for the files of a txt2hair (HAAR) strand job.

The hub alias delivers three files per job (spec
docs/superpowers/specs/2026-11-13-strand-hair-design.md § 6.3.3, Ruling H-R6):

- ``<input_name>_strands.npy`` — float32 little-endian, shape ``(N, P, 3)``:
  N strands of P points each, root first, metres, the generator's template
  head space (+y up, +z front). P is read from the array, never assumed — the
  live alias returns P = 100 although its upsample resolution is 128.
  A binary or ASCII ``.ply`` with the same content is accepted instead:
  ``element vertex N*P`` with float ``x``/``y``/``z`` (strand-major, root
  first) and ``element strand N``; P = vertex count / N.
- ``<input_name>_head.obj`` — the template head the strands are rooted on,
  same space.
- ``info.json`` — ``{seed, prompt, strands, points, space, units, version, …}``.
  Where it names ``strands`` / ``points`` they must match the array.

Pure numpy, no network, no world state.
"""
import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import numpy as np

STRANDS_SUFFIXES = ("_strands.npy", "_strands.ply")
HEAD_SUFFIX = "_head.obj"
INFO_NAME = "info.json"

_PLY_TYPES = {
    "char": "i1", "int8": "i1", "uchar": "u1", "uint8": "u1",
    "short": "i2", "int16": "i2", "ushort": "u2", "uint16": "u2",
    "int": "i4", "int32": "i4", "uint": "u4", "uint32": "u4",
    "float": "f4", "float32": "f4", "double": "f8", "float64": "f8",
}


class StrandFileError(ValueError):
    """A strand job file that cannot be read as the contract describes."""


def _check_strands(arr: np.ndarray, source: str) -> np.ndarray:
    if arr.ndim != 3 or arr.shape[2] != 3:
        raise StrandFileError(f"{source}: expected shape (N, P, 3), got {arr.shape}")
    if arr.shape[0] < 1 or arr.shape[1] < 2:
        raise StrandFileError(f"{source}: needs at least one strand of two points, got {arr.shape}")
    out = np.ascontiguousarray(arr, dtype=np.float32)
    if not np.isfinite(out).all():
        raise StrandFileError(f"{source}: non-finite coordinates")
    return out


def _read_npy(path: Path) -> np.ndarray:
    try:
        arr = np.load(path, allow_pickle=False)
    except (OSError, ValueError) as e:
        raise StrandFileError(f"{path.name}: not a readable .npy ({e})") from e
    if not isinstance(arr, np.ndarray) or arr.dtype.kind != "f":
        raise StrandFileError(f"{path.name}: expected a float array")
    return arr


def _ply_header(raw: bytes, name: str):
    end = raw.find(b"end_header")
    if not raw.startswith(b"ply") or end < 0:
        raise StrandFileError(f"{name}: not a PLY file")
    nl = raw.find(b"\n", end)
    body_start = nl + 1 if nl >= 0 else len(raw)
    lines = raw[:end].decode("ascii", "replace").splitlines()
    fmt = ""
    elements = []  # [name, count, [(prop, dtype)]]
    for line in lines[1:]:
        parts = line.split()
        if not parts or parts[0] in ("comment", "obj_info"):
            continue
        if parts[0] == "format" and len(parts) >= 2:
            fmt = parts[1]
        elif parts[0] == "element" and len(parts) == 3:
            elements.append([parts[1], int(parts[2]), []])
        elif parts[0] == "property" and elements:
            if parts[1] == "list":
                raise StrandFileError(f"{name}: list properties are not supported")
            dtype = _PLY_TYPES.get(parts[1])
            if dtype is None or len(parts) != 3:
                raise StrandFileError(f"{name}: unknown property line {line!r}")
            elements[-1][2].append((parts[2], dtype))
    if fmt not in ("binary_little_endian", "binary_big_endian", "ascii"):
        raise StrandFileError(f"{name}: unsupported PLY format {fmt!r}")
    return fmt, elements, body_start


def _read_ply(path: Path) -> np.ndarray:
    raw = path.read_bytes()
    fmt, elements, pos = _ply_header(raw, path.name)
    tables: Dict[str, np.ndarray] = {}
    if fmt == "ascii":
        tokens = raw[pos:].split()
        at = 0
        for ename, count, props in elements:
            n = count * len(props)
            vals = np.array(tokens[at:at + n], dtype=np.float64)
            if vals.size != n:
                raise StrandFileError(f"{path.name}: element {ename} is truncated")
            at += n
            if not props:
                tables[ename] = np.zeros(count)
                continue
            rec = np.zeros(count, dtype=[(p, d) for p, d in props])
            table = vals.reshape(count, len(props))
            for i, (p, _d) in enumerate(props):
                rec[p] = table[:, i]
            tables[ename] = rec
    else:
        order = "<" if fmt == "binary_little_endian" else ">"
        for ename, count, props in elements:
            dt = np.dtype([(p, order + d) for p, d in props]) if props else None
            size = (dt.itemsize if dt is not None else 0) * count
            if pos + size > len(raw):
                raise StrandFileError(f"{path.name}: element {ename} is truncated")
            tables[ename] = (np.frombuffer(raw, dtype=dt, count=count, offset=pos)
                             if dt is not None else np.zeros(count))
            pos += size
    counts = {ename: count for ename, count, _props in elements}
    vertex = tables.get("vertex")
    if vertex is None or vertex.dtype.names is None \
            or not {"x", "y", "z"} <= set(vertex.dtype.names):
        raise StrandFileError(f"{path.name}: no vertex element with x/y/z")
    n_strands = counts.get("strand", 0)
    if n_strands < 1 or counts["vertex"] % n_strands:
        raise StrandFileError(f"{path.name}: {counts['vertex']} vertices do not split into "
                              f"{n_strands} strands of equal length")
    xyz = np.stack([vertex["x"], vertex["y"], vertex["z"]], axis=1).astype(np.float32)
    return xyz.reshape(n_strands, counts["vertex"] // n_strands, 3)


def read_strands(path) -> np.ndarray:
    """The strands of a ``.npy`` or ``.ply`` file as float32 ``(N, P, 3)``,
    P taken from the file. Raises ``StrandFileError`` on anything else."""
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix == ".npy":
        arr = _read_npy(p)
    elif suffix == ".ply":
        arr = _read_ply(p)
    else:
        raise StrandFileError(f"{p.name}: strands must be .npy or .ply")
    return _check_strands(arr, p.name)


def read_head_obj(path) -> Tuple[np.ndarray, np.ndarray]:
    """``(V float32 (n, 3), F int32 (m, 3))`` of a Wavefront OBJ; polygons are
    fan-triangulated, ``v/vt/vn`` and negative indices are understood."""
    p = Path(path)
    verts, faces = [], []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("v "):
            parts = line.split()
            if len(parts) < 4:
                raise StrandFileError(f"{p.name}: short vertex line {line!r}")
            verts.append([float(parts[1]), float(parts[2]), float(parts[3])])
        elif line.startswith("f "):
            idx = []
            for tok in line.split()[1:]:
                i = int(tok.split("/")[0])
                idx.append(i - 1 if i > 0 else len(verts) + i)
            for k in range(1, len(idx) - 1):
                faces.append([idx[0], idx[k], idx[k + 1]])
    V = np.asarray(verts, dtype=np.float32).reshape(-1, 3)
    F = np.asarray(faces, dtype=np.int32).reshape(-1, 3)
    if not len(V):
        raise StrandFileError(f"{p.name}: no vertices")
    if len(F) and (F.min() < 0 or F.max() >= len(V)):
        raise StrandFileError(f"{p.name}: face index out of range")
    return V, F


def read_info(path) -> Dict[str, Any]:
    p = Path(path)
    try:
        info = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise StrandFileError(f"{p.name}: not readable JSON ({e})") from e
    if not isinstance(info, dict):
        raise StrandFileError(f"{p.name}: expected a JSON object")
    return info


def _find(directory: Path, suffixes) -> Optional[Path]:
    hits = sorted(f for f in directory.iterdir()
                  if f.is_file() and any(f.name.endswith(s) for s in suffixes))
    if len(hits) > 1:
        raise StrandFileError(f"{directory}: several files end in {'/'.join(suffixes)}: "
                              + ", ".join(f.name for f in hits))
    return hits[0] if hits else None


def read_strand_job(directory) -> Dict[str, Any]:
    """Everything one strand job delivered into ``directory`` (the
    ``output_dir`` of ``ImageService.generate_strands``):

    ``{"strands": (N, P, 3) float32, "head_V", "head_F" (None without a head
    file), "info": dict ({} without info.json), "strands_path", "head_path"}``.

    ``info.strands`` / ``info.points``, where present, must equal N / P."""
    d = Path(directory)
    strands_path = _find(d, STRANDS_SUFFIXES)
    if strands_path is None:
        raise StrandFileError(f"{d}: no *_strands.npy or *_strands.ply")
    strands = read_strands(strands_path)
    info_path = d / INFO_NAME
    info = read_info(info_path) if info_path.is_file() else {}
    n, p = int(strands.shape[0]), int(strands.shape[1])
    for key, have in (("strands", n), ("points", p)):
        want = info.get(key)
        if want is not None and int(want) != have:
            raise StrandFileError(f"{info_path.name}: {key} = {want}, the strand file has {have}")
    head_path = _find(d, (HEAD_SUFFIX,))
    head_V = head_F = None
    if head_path is not None:
        head_V, head_F = read_head_obj(head_path)
    return {"strands": strands, "head_V": head_V, "head_F": head_F, "info": info,
            "strands_path": str(strands_path), "head_path": str(head_path or "")}


def strand_summary(strands: np.ndarray) -> Dict[str, Any]:
    """Plain numbers of a strand set (N, P, bbox, root/tip height, length) —
    for logs and the job report, never a decision."""
    flat = strands.reshape(-1, 3)
    seg = np.linalg.norm(np.diff(strands, axis=1), axis=2).sum(axis=1)
    return {
        "strands": int(strands.shape[0]), "points": int(strands.shape[1]),
        "bbox_min": [round(float(v), 4) for v in flat.min(axis=0)],
        "bbox_max": [round(float(v), 4) for v in flat.max(axis=0)],
        "root_y_median": round(float(np.median(strands[:, 0, 1])), 4),
        "tip_y_median": round(float(np.median(strands[:, -1, 1])), 4),
        "length_median_m": round(float(np.median(seg)), 4),
    }


__all__ = ["StrandFileError", "read_strands", "read_head_obj", "read_info",
           "read_strand_job", "strand_summary", "STRANDS_SUFFIXES", "HEAD_SUFFIX",
           "INFO_NAME"]
