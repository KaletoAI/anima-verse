"""Global surface-texture library (AV3D-13).

Seamless tileable top-down ground textures for terrain tiles (road, water,
grass, …), delivered world-globally via ``GET /assets/surface-textures`` —
analogous to the animation-clip library. ``kind`` is an OPEN vocabulary
matching the location ``terrain`` field; the client gets ONE texture per
kind — the ACTIVE one. Like the image galleries and the building models,
SEVERAL versions per kind may be stored: every generation/upload adds a
timestamped file, one of them is selected. ``size_m`` = physical edge
length (default 3 m); an empty list is the normal state — the client
falls back to its built-in procedural materials.

Three fields, three jobs — never one field for two of them:

    ID   (``kind``)  the machine key: file names, the ``terrain`` field,
                     the client contract, level_floors / room floor kinds /
                     blend ``toward``. Lowercase, no spaces, IMMUTABLE once
                     created, and it NEVER reaches a prompt.
    Name             free text with spaces, the only thing pickers show.
    Description      the one text that goes into the image prompt.

The ID is derived from the Name (``slug_for_name``) unless one is given —
that rule lives HERE, so the admin UI cannot grow a second one.

Storage: ``worlds/<world>/surface_textures/``:

    <kind>_<ts>.jpg          — one file per version (uploads may be PNG/WebP)
    <kind>_<ts>.json         — sidecar: created_at, source, backend, prompt,
                               negative, size_m
    <kind>.jpg / <kind>.json — the legacy single-version store, stays valid
    selection.json           — {"<kind>": "<active filename>"}

Without a selection entry the NEWEST version is active. Generation runs
through the normal image pipeline — use case ``surface_texture``,
serialized on the backend GPU channel like every other render — and the
result is converted to JPEG ≤ 1024²; the sidecar records HOW the texture
was made (backend + final prompt).
"""

import json
import random
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.log import get_logger
from app.core.timeutils import utc_now_iso

logger = get_logger(__name__)

DEFAULT_SIZE_M = 3.0
TEXTURE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
_KIND_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
# Version-timestamp suffix: unix seconds (≥ 9 digits) — kinds themselves may
# contain digits/underscores, the length keeps the split unambiguous.
_TS_RE = re.compile(r"^(.+)_(\d{9,})$")
_SEL_FILE = "selection.json"
_BLENDS_FILE = "blends.json"
# Per-kind metadata: {kind: {name?, description?}} — see the module doc.
_KINDS_FILE = "kinds.json"
# Flag for the one-time subject → description migration.
_META_V2_FLAG = "world.migration.surface_kind_meta_v2"

_lock = threading.Lock()
# Running job keys "<kind>|<backend glob>" — generations of the SAME kind on
# DIFFERENT backends may run/queue concurrently (each serializes on its own
# GPU channel); only a double-click of the same kind+backend is rejected.
_generating: set = set()


def _dir(*, create: bool = False) -> Path:
    from app.core.paths import get_storage_dir
    d = get_storage_dir() / "surface_textures"
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


def safe_kind(kind: str) -> str:
    """Normalized kind ('' = invalid) — lowercase, url/file-safe."""
    kind = (kind or "").strip().lower()
    return kind if _KIND_RE.match(kind) else ""


def slug_for_name(name: str) -> str:
    """The ID a name gets: lowercase, spaces → ``_``, everything the ID
    grammar does not allow dropped, ≤ 40 characters ('' = nothing usable
    left). THE one slugify of this feature — the admin UI sends the name and
    reads the resulting id back rather than deriving its own."""
    s = (name or "").strip().lower()
    # Accents first so "Fluß-Kies" keeps its letters instead of losing them.
    import unicodedata
    s = s.replace("ß", "ss")
    s = "".join(c for c in unicodedata.normalize("NFKD", s)
                if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")[:40].rstrip("_")
    # The grammar wants a letter or digit up front.
    s = re.sub(r"^[^a-z0-9]+", "", s)
    return s if _KIND_RE.match(s) else ""


def unslug(kind: str) -> str:
    """An ID read back as words — ``dark_stone`` → ``dark stone``. Used
    wherever an ID would otherwise leak into human-facing text: a default
    name, and the last link of the prompt chain (a prompt must never carry
    an underscore from the ID)."""
    return re.sub(r"[_-]+", " ", (kind or "").strip()).strip()


def _stem_kind(stem: str) -> str:
    """Kind of a file stem: ``<kind>_<ts>`` (versioned) or ``<kind>``
    (legacy). '' when the stem is no valid kind."""
    m = _TS_RE.match(stem)
    return safe_kind(m.group(1) if m else stem)


def _sidecar_path(p: Path) -> Path:
    return p.with_suffix(".json")


def _read_meta(p: Path) -> Dict[str, Any]:
    sp = _sidecar_path(p)
    if sp.exists():
        try:
            meta = json.loads(sp.read_text(encoding="utf-8"))
            if isinstance(meta, dict):
                return meta
        except (OSError, ValueError):
            pass
    return {}


def _write_meta(p: Path, meta: Dict[str, Any]) -> None:
    _sidecar_path(p).write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")


def _created_key(p: Path) -> float:
    meta = _read_meta(p)
    ts = meta.get("created_at") or ""
    if ts:
        from app.core.timeutils import parse_iso
        try:
            return parse_iso(ts).timestamp()
        except (TypeError, ValueError):
            pass
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0


def _files_by_kind() -> Dict[str, List[Path]]:
    """All stored texture files grouped by kind, newest first per kind."""
    d = _dir()
    if not d.is_dir():
        return {}
    out: Dict[str, List[Path]] = {}
    for p in d.iterdir():
        if not p.is_file() or p.suffix.lower() not in TEXTURE_EXTS:
            continue
        kind = _stem_kind(p.stem)
        if kind:
            out.setdefault(kind, []).append(p)
    for kind in out:
        out[kind].sort(key=_created_key, reverse=True)
    return out


def _read_selection() -> Dict[str, str]:
    sp = _dir() / _SEL_FILE
    if sp.exists():
        try:
            sel = json.loads(sp.read_text(encoding="utf-8"))
            if isinstance(sel, dict):
                return sel
        except (OSError, ValueError):
            pass
    return {}


def _write_selection(sel: Dict[str, str]) -> None:
    (_dir(create=True) / _SEL_FILE).write_text(
        json.dumps(sel, indent=2, ensure_ascii=False), encoding="utf-8")


def texture_file(kind: str) -> Optional[Path]:
    """The ACTIVE version of a kind: the selection entry when it points at an
    existing file, else the newest stored version (legacy files need no
    migration this way)."""
    kind = safe_kind(kind)
    if not kind:
        return None
    sel = _read_selection().get(kind, "")
    if sel and "/" not in sel and "\\" not in sel and ".." not in sel:
        p = _dir() / sel
        if p.exists() and _stem_kind(p.stem) == kind:
            return p
    files = _files_by_kind().get(kind) or []
    return files[0] if files else None


def file_by_name(filename: str) -> Optional[Path]:
    """Resolve a served filename (path-escape safe, known extensions only)."""
    if "/" in filename or "\\" in filename or ".." in filename:
        return None
    p = _dir() / filename
    if not p.exists() or p.suffix.lower() not in TEXTURE_EXTS:
        return None
    return p if _stem_kind(p.stem) else None


def _size_m_of(p: Path) -> float:
    try:
        v = float(_read_meta(p).get("size_m"))
        return v if v > 0 else DEFAULT_SIZE_M
    except (TypeError, ValueError):
        return DEFAULT_SIZE_M


def set_size_m(kind: str, size_m: float, filename: str = "") -> bool:
    """Persist the physical edge length on ONE version's sidecar (default:
    the active one) — a property of the image (what area it depicts)."""
    kind = safe_kind(kind)
    if not kind:
        return False
    p = (file_by_name(filename) if filename else texture_file(kind))
    if not p or _stem_kind(p.stem) != kind:
        return False
    try:
        size_m = float(size_m)
    except (TypeError, ValueError):
        return False
    if size_m <= 0 or size_m > 100:
        return False
    meta = _read_meta(p)
    if abs(size_m - DEFAULT_SIZE_M) < 1e-9:
        meta.pop("size_m", None)
    else:
        meta["size_m"] = round(size_m, 2)
    if meta:
        _write_meta(p, meta)
    else:
        _sidecar_path(p).unlink(missing_ok=True)
    return True


def select_texture(kind: str, filename: str) -> bool:
    """Make ``filename`` the active version of its kind."""
    kind = safe_kind(kind)
    p = file_by_name(filename) if kind else None
    if not p or _stem_kind(p.stem) != kind:
        return False
    sel = _read_selection()
    sel[kind] = p.name
    _write_selection(sel)
    return True


# ── Blend compositions (AV3D-13 v2) ─────────────────────────────────────
# A library entry may be a COMPOSITION instead of a texture: a zone
# gradient toward a neighbor kind ("coast" = water → sand → whatever the
# other neighbors are). The client mixes generically — a new ground look
# is a new entry, never a client change. One JSON file holds all blends;
# a blend WINS over texture files of the same kind in the client list.

def _read_blends() -> Dict[str, Dict[str, Any]]:
    bp = _dir() / _BLENDS_FILE
    if bp.exists():
        try:
            data = json.loads(bp.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {k: v for k, v in data.items()
                        if safe_kind(k) and isinstance(v, dict)}
        except (OSError, ValueError):
            pass
    return {}


def _write_blends(blends: Dict[str, Dict[str, Any]]) -> None:
    (_dir(create=True) / _BLENDS_FILE).write_text(
        json.dumps(blends, indent=2, ensure_ascii=False), encoding="utf-8")


def sanitize_blend(raw: Any) -> Optional[Dict[str, Any]]:
    """Whitelist + coerce a blend definition (contract → schnittstellen-3d
    „Oberflächen-Bibliothek"): ``toward`` = the neighbor kind the gradient
    runs to, ``zones`` from the toward edge (each {kind, until 0..1};
    ascending; the last zone may omit ``until`` = rest; kind "neighbor" =
    the dominant non-toward neighbor), ``noise`` = border fraying."""
    if not isinstance(raw, dict):
        return None
    toward = safe_kind(str(raw.get("toward") or ""))
    if not toward:
        return None
    zones_in = raw.get("zones")
    if not isinstance(zones_in, list) or not zones_in or len(zones_in) > 8:
        return None
    zones: List[Dict[str, Any]] = []
    last_until = 0.0
    for i, z in enumerate(zones_in):
        if not isinstance(z, dict):
            return None
        zk = str(z.get("kind") or "").strip().lower()
        if zk != "neighbor":
            zk = safe_kind(zk)
        if not zk:
            return None
        entry: Dict[str, Any] = {"kind": zk}
        if "until" in z and z.get("until") is not None:
            try:
                u = round(float(z["until"]), 3)
            except (TypeError, ValueError):
                return None
            if not (last_until < u <= 1.0):
                return None
            last_until = u
            entry["until"] = u
        elif i != len(zones_in) - 1:
            return None  # only the LAST zone may omit until
        zones.append(entry)
    out: Dict[str, Any] = {"toward": toward, "zones": zones}
    noise = raw.get("noise")
    if noise is not None:
        try:
            n = round(float(noise), 3)
        except (TypeError, ValueError):
            return None
        if 0 <= n <= 0.5:
            out["noise"] = n
    return out


def get_blends() -> Dict[str, Dict[str, Any]]:
    return _read_blends()


def set_blend(kind: str, blend: Any) -> Optional[Dict[str, Any]]:
    """Create/replace a composition entry. None on invalid input."""
    kind = safe_kind(kind)
    clean = sanitize_blend(blend)
    if not kind or clean is None:
        return None
    blends = _read_blends()
    blends[kind] = clean
    _write_blends(blends)
    return clean


def delete_blend(kind: str) -> bool:
    kind = safe_kind(kind)
    blends = _read_blends()
    if kind not in blends:
        return False
    blends.pop(kind)
    _write_blends(blends)
    return True


def list_textures() -> List[Dict[str, Any]]:
    """CLIENT list — one entry per kind, the ACTIVE version:
    {kind, name, filename, url, size_m, size}.

    ``name`` travels with it so every picker in the admin and both renderers
    can show words instead of an id; what they STORE is still the id."""
    blends = _read_blends()
    meta = _read_kind_meta()
    out: List[Dict[str, Any]] = []

    def _name(kind: str) -> str:
        return ((meta.get(kind) or {}).get("name") or "").strip() or unslug(kind)

    def _material(kind: str) -> Optional[Dict[str, Any]]:
        return (meta.get(kind) or {}).get("material") or None

    for kind in sorted(set(_files_by_kind()) | set(blends)):
        entry: Dict[str, Any]
        if kind in blends:
            # A composition wins over texture files of the same kind.
            entry = {"kind": kind, "name": _name(kind), "blend": blends[kind]}
        else:
            p = texture_file(kind)
            if not p:
                continue
            entry = {
                "kind": kind,
                "name": _name(kind),
                "filename": p.name,
                "url": f"/assets/surface-textures/{p.name}",
                "size_m": _size_m_of(p),
                "size": p.stat().st_size,
            }
        mat = _material(kind)
        if mat:
            entry["material"] = mat
        out.append(entry)
    return out


def admin_list() -> List[Dict[str, Any]]:
    """Admin listing — ALL versions per kind (newest first) incl. HOW each
    was made: [{kind, name, description, versions: [{filename, url, size_m,
    created_at, source, backend, prompt, negative, active}]}]."""
    out = []
    by_kind = _files_by_kind()
    kmeta = _read_kind_meta()
    for kind in sorted(by_kind):
        active = texture_file(kind)
        versions = []
        for p in by_kind[kind]:
            meta = _read_meta(p)
            versions.append({
                "filename": p.name,
                "url": f"/assets/surface-textures/{p.name}",
                "size_m": _size_m_of(p),
                "created_at": meta.get("created_at", ""),
                "source": meta.get("source", ""),
                "backend": meta.get("backend", ""),
                "prompt": meta.get("prompt", ""),
                "negative": meta.get("negative", ""),
                "active": bool(active and p.name == active.name),
            })
        entry = kmeta.get(kind) or {}
        out.append({"kind": kind, "name": entry.get("name", ""),
                    "description": entry.get("description", ""),
                    "material": entry.get("material") or None,
                    "versions": versions})
    return out


def delete_texture(kind: str, filename: str = "") -> bool:
    """Remove ONE version (+ sidecar) by filename, or ALL versions of the
    kind when ``filename`` is empty. Deleting the active version moves the
    selection to the newest remaining one."""
    kind = safe_kind(kind)
    if not kind:
        return False
    if filename:
        p = file_by_name(filename)
        if not p or _stem_kind(p.stem) != kind:
            return False
        p.unlink()
        _sidecar_path(p).unlink(missing_ok=True)
    else:
        files = _files_by_kind().get(kind) or []
        if not files:
            return False
        for p in files:
            p.unlink()
            _sidecar_path(p).unlink(missing_ok=True)
    sel = _read_selection()
    if kind in sel and not (_dir() / sel[kind]).exists():
        sel.pop(kind)
        _write_selection(sel)
    return True


def _new_path(kind: str, ext: str) -> Path:
    """Fresh timestamped target file; bumps the timestamp on a collision."""
    d = _dir(create=True)
    ts = int(time.time())
    while True:
        p = d / f"{kind}_{ts}{ext}"
        if not p.exists():
            return p
        ts += 1


def save_uploaded(kind: str = "", contents: bytes = b"", *,
                  name: str = "") -> Dict[str, Any]:
    """Store an uploaded texture as a NEW version (magic-byte sniffed) and
    select it — existing versions stay. Like a generation, an upload may
    create the kind: without an id one is derived from the name, and name +
    description are seeded."""
    kind = safe_kind(kind) or slug_for_name(name)
    if not kind:
        return {"ok": False, "error": "bad_kind"}
    if len(contents) > 10 * 1024 * 1024:
        return {"ok": False, "error": "too_large"}
    if contents[:3] == b"\xff\xd8\xff":
        ext = ".jpg"
    elif contents[:8] == b"\x89PNG\r\n\x1a\n":
        ext = ".png"
    elif contents[:4] == b"RIFF" and contents[8:12] == b"WEBP":
        ext = ".webp"
    else:
        return {"ok": False, "error": "not_an_image"}
    ensure_kind_meta(kind, name=name)
    p = _new_path(kind, ext)
    p.write_bytes(contents)
    _write_meta(p, {"created_at": utc_now_iso(), "source": "uploaded"})
    select_texture(kind, p.name)
    return {"ok": True, "kind": kind, "filename": p.name}


# Subject phrases per kind — the visual character of the material, which the
# generic "<kind> ground material" wording completely failed to convey (gray
# swatches on every backend). The vocabulary stays OPEN: unknown kinds get
# the generic fallback and the phrase is editable in the tab anyway.
SURFACE_SUBJECTS: Dict[str, str] = {
    "water": "calm water surface with gentle ripples and small waves, natural blue-green tones",
    "road": "worn gray asphalt with fine grain, subtle cracks and faint tire marks",
    "grass": "dense short lawn grass, natural fresh green blades",
    "sand": "fine beach sand with slight wind ripples, warm beige tones",
    "rock": "rough natural stone with fissures and mineral speckles",
    "gravel": "small mixed gravel pebbles densely packed, varied gray-brown tones",
    "dirt": "dry brown earth with small stones, cracks and fine soil texture",
    "snow": "fresh untouched snow with fine sparkling crystals",
    "forest": "forest floor of brown leaf litter, moss patches and small twigs",
    # Indoor level-plate floor (the 3D client tiles storey plates with the
    # active "floor" texture; floor_source was withdrawn 2026-07-19).
    "floor": "smooth wooden plank flooring with natural grain and subtle wear",
    # Interior wall surface for the room shell (plan-room-props.md): the
    # client skins walls derived from the room geometry with this kind.
    "wall": "smooth plastered interior wall with fine even texture, neutral warm off-white tone",
}


def _read_kind_meta() -> Dict[str, Dict[str, str]]:
    p = _dir() / _KINDS_FILE
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {k: v for k, v in data.items() if isinstance(v, dict)}
        except (OSError, ValueError):
            pass
    return {}


def get_kind_meta() -> Dict[str, Dict[str, str]]:
    """Per-kind display metadata (see _KINDS_FILE)."""
    return _read_kind_meta()


# ── Material class (plan-water-rendering.md, Teil A) ────────────────────
# A kind may say HOW it is lit, not just what it looks like. Water is not
# recognised by its colour but by what it reflects and how it moves, and a
# colour map on a matte material delivers neither. The class rides with the
# kind (kinds.json) and goes to BOTH renderers via /assets/surface-textures.
#
# Only WATER needed a shader, and only because it MOVES. Everything else the
# standard material can already do — a class is then just the right numbers
# under a name somebody can pick:
#
#   water   moving ripples, low roughness, sky reflection   (shader)
#   ice     the same surface standing still                 (shader, speed 0)
#   gloss   polished floor, wet cobbles, tiles, metal        (plain material)
#   glow    neon, lava, crystals — the texture EMITS         (plain material)
#
# No separate "metal" class: gloss carries `metalness`, and a metal floor is a
# gloss with that dial up. One class fewer to maintain, the same reach.
SURFACE_CLASSES = ("matte", "water", "ice", "gloss", "glow")
# name -> (min, max, default). The default is the generic one; a class may
# override it below.
_MATERIAL_RANGES: Dict[str, Any] = {
    "map_strength": (0.0, 1.0, 0.75),
    "wave_m": (0.2, 20.0, 1.6),
    "speed": (0.0, 2.0, 0.05),
    "sky_mix": (0.0, 1.0, 0.55),
    "roughness": (0.0, 1.0, 0.08),
    "metalness": (0.0, 1.0, 0.05),
    "glow": (0.0, 5.0, 1.0),
}
# Which numbers a class actually carries — everything else is dropped, so a
# spec never claims a dial its class ignores.
_CLASS_FIELDS: Dict[str, tuple] = {
    "water": ("map_strength", "wave_m", "speed", "sky_mix", "roughness"),
    "ice": ("map_strength", "wave_m", "speed", "sky_mix", "roughness"),
    "gloss": ("map_strength", "roughness", "metalness"),
    "glow": ("map_strength", "glow"),
}
# Where a class wants something other than the generic default. Ice is water
# standing still: no flow, a longer swell, more sky and a fainter texture.
_CLASS_DEFAULTS: Dict[str, Dict[str, float]] = {
    "ice": {"speed": 0.0, "wave_m": 4.0, "sky_mix": 0.7,
            "roughness": 0.05, "map_strength": 0.6},
    "gloss": {"roughness": 0.25, "metalness": 0.05, "map_strength": 1.0},
    "glow": {"map_strength": 1.0, "glow": 1.0},
}
_HEX_RE = re.compile(r"^#[0-9a-f]{6}$")


def sanitize_material(raw: Any) -> Optional[Dict[str, Any]]:
    """Whitelist + clamp a material declaration. None = no declaration (the
    kind renders matte, exactly as before). An unknown class falls back to
    matte rather than failing — a client must never meet a class it cannot
    draw."""
    if not isinstance(raw, dict):
        return None
    cls = str(raw.get("class") or "").strip().lower()
    if cls not in SURFACE_CLASSES:
        cls = "matte"
    if cls == "matte":
        return None      # the default needs no entry
    out: Dict[str, Any] = {"class": cls}
    tint = str(raw.get("tint") or "").strip().lower()
    if _HEX_RE.match(tint):
        out["tint"] = tint
    overrides = _CLASS_DEFAULTS.get(cls) or {}
    for key in _CLASS_FIELDS.get(cls) or ():
        lo, hi, generic = _MATERIAL_RANGES[key]
        default = overrides.get(key, generic)
        try:
            v = float(raw.get(key, default))
        except (TypeError, ValueError):
            v = default
        out[key] = round(min(max(v, lo), hi), 4)
    return out


def _write_kind_meta(data: Dict[str, Dict[str, str]]) -> None:
    (_dir(create=True) / _KINDS_FILE).write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def set_kind_meta(kind: str, *, name: Any = None, description: Any = None,
                  material: Any = None) -> Optional[Dict[str, Any]]:
    """Set a kind's name (free text, spaces welcome), its description and/or
    its material class. None leaves a field untouched, '' clears it. None
    result = invalid kind.

    The ID is not settable here — it is in file names and in world data, so
    renaming it would be a data migration, not an edit."""
    k = safe_kind(kind)
    if not k:
        return None
    data = _read_kind_meta()
    entry = dict(data.get(k) or {})
    if material is not None:
        clean = sanitize_material(material)
        if clean:
            entry["material"] = clean
        else:
            entry.pop("material", None)   # matte = no entry
    for key, val in (("name", name), ("description", description)):
        if val is None:
            continue
        v = str(val).strip()
        if v:
            entry[key] = v[:400]
        else:
            entry.pop(key, None)
    if entry:
        data[k] = entry
    else:
        data.pop(k, None)
    _write_kind_meta(data)
    return {"kind": k, **entry}


def ensure_kind_meta(kind: str, *, name: str = "",
                     description: str = "") -> Dict[str, str]:
    """Seed name and description when a kind is created, and return them.

    This is where the curated wording lands: in the FIELD, not in a runtime
    fallback that silently outranks what the admin typed. What stands in the
    description is what gets sent — that is the whole point of the split.
    Existing entries are never overwritten."""
    k = safe_kind(kind)
    if not k:
        return {}
    data = _read_kind_meta()
    entry = dict(data.get(k) or {})
    if not entry.get("name"):
        entry["name"] = (name or "").strip()[:400] or unslug(k)
    if not entry.get("description"):
        seed = (description or "").strip() or SURFACE_SUBJECTS.get(k, "")
        entry["description"] = (seed or entry["name"])[:400]
    if entry != (data.get(k) or {}):
        data[k] = entry
        _write_kind_meta(data)
    return entry


def migrate_kind_meta_once() -> Dict[str, int]:
    """Carry ``kinds.json`` over to name + description (2026-07-28).

    ``subject`` becomes ``description``, and every kind that had none gets
    one written out — curated wording, else the name, else the id as words.
    That is the point of the migration: the curated map stops being a
    RUNTIME fallback (which silently outranked the field), so a kind that
    relied on it must carry the text itself or its generation result would
    change. Names are filled the same way, so the pickers read as words at
    once.

    Idempotent via a world_kv flag. Returns a small stats dict for the log.
    """
    from app.models.world import get_world_setting, set_world_setting
    if get_world_setting(_META_V2_FLAG):
        return {}
    data = _read_kind_meta()
    # Kinds with files or blends but no meta entry at all also need seeding —
    # they used to live entirely off the curated map.
    known = set(data) | set(_files_by_kind()) | set(_read_blends())
    renamed = seeded_desc = seeded_name = 0
    for kind in sorted(known):
        if not safe_kind(kind):
            continue
        entry = dict(data.get(kind) or {})
        subject = str(entry.pop("subject", "") or "").strip()
        if subject and not entry.get("description"):
            entry["description"] = subject
            renamed += 1
        if not entry.get("name"):
            entry["name"] = unslug(kind)
            seeded_name += 1
        if not entry.get("description"):
            # Deliberately NOT the name — this writes out what the kind
            # produced BEFORE, and the old runtime chain never looked at the
            # name. A kind whose text was poor keeps its poor text, now
            # visible in an editable field instead of hidden in a fallback.
            # (`ensure_kind_meta` does use the name: a NEW kind has no
            # previous result to preserve.)
            entry["description"] = (SURFACE_SUBJECTS.get(kind)
                                    or f"the surface of {unslug(kind)} seen straight from above")
            seeded_desc += 1
        data[kind] = entry
    if data:
        _write_kind_meta(data)
    set_world_setting(_META_V2_FLAG, "1")
    return {"kinds": len(data), "subject_renamed": renamed,
            "description_seeded": seeded_desc, "name_seeded": seeded_name}


def kind_name(kind: str) -> str:
    """What a picker shows for an ID — the name, else the ID as words."""
    k = (kind or "").strip().lower()
    return ((_read_kind_meta().get(k) or {}).get("name") or "").strip() or unslug(k)


def surface_description(kind: str) -> str:
    """The text that goes into the image prompt: description → name → the ID
    read back as words. The ID itself never reaches a prompt — an underscore
    in a subject phrase is a defect, not a wording choice."""
    k = (kind or "").strip().lower()
    if not k:
        return "a natural ground surface"
    entry = _read_kind_meta().get(k) or {}
    return ((entry.get("description") or "").strip()
            or (entry.get("name") or "").strip()
            or f"the surface of {unslug(k)} seen straight from above")


def compose_prompt(kind: str, backend) -> Dict[str, str]:
    """Final prompt + negative for a kind on a backend — use-case style
    (``surface_texture``, per image family) plus the per-kind subject
    phrase. The dialog shows exactly this and may edit it (final-prompt
    rule); ``style`` is returned separately so the UI can recompose per
    kind."""
    from app.core import config as _cfg
    from app.core.prompt_compose import compose as _compose
    ucp = _cfg.resolve_use_case_style(
        "surface_texture",
        backend_model=getattr(backend, "model", "") or "",
        backend_family=getattr(backend, "image_family", ""))
    subject = surface_description(kind)
    # Composition (slot/append, negation guard, negative merge) belongs to
    # prompt_compose; the return SHAPE stays, the dialog recomposes per kind
    # from `style` + its own subject field.
    composed = _compose(use_case="surface_texture", subject=subject,
                        backend=backend)
    return {
        "style": (ucp.get("prompt_style") or "").strip(),
        "prompt": composed.prompt,
        "negative": composed.negative,
    }


def _gen_key(kind: str, backend_glob: str) -> str:
    return f"{kind}|{(backend_glob or '').strip().lower()}"


def is_pending(kind: str = "") -> List[str]:
    """KINDS with at least one running generation (any backend)."""
    with _lock:
        kinds = sorted({k.split("|", 1)[0] for k in _generating})
    return kinds if not kind else ([kind] if kind in kinds else [])


def _generate(kind: str, backend_glob: str, prompt: str, negative: str) -> Dict[str, Any]:
    """Blocking generation on a worker thread — the GPU job itself runs on
    the backend queue channel like every image render. Adds a NEW version
    and selects it; the sidecar records backend + final prompt."""
    from app.imagegen.service import get_image_service
    svc = get_image_service()
    backend = None
    if backend_glob.strip():
        backend = svc.resolve_imagegen_target(backend_glob)
    if not backend:
        backend = svc._select_backend()
    if not backend:
        logger.warning("Surface texture %s: no image backend available", kind)
        return {"ok": False, "error": "no backend available"}

    if not prompt.strip():
        composed = compose_prompt(kind, backend)
        prompt = composed["prompt"]
        if not negative.strip():
            negative = composed["negative"]

    from app.core.task_queue import get_task_queue
    task_id = ""
    try:
        task_id = get_task_queue().track_start(
            "surface_texture", f"Surface texture: {kind}", start_running=True)
    except Exception:
        task_id = ""

    error = ""
    try:
        params: Dict[str, Any] = {
            "width": 1024, "height": 1024,
            "seed": random.randint(1, 2**31 - 1),
        }
        # The prompt arrives already composed (compose_prompt, or edited in
        # the dialog) — the metablock records the use case, not a fresh compose.
        _log_meta = {"agent_name": f"Surface {kind}", "original_prompt": prompt,
                     "auto_enhance": False,
                     "compose": {"use_case": "surface_texture",
                                 "settings_applied": True}}
        from app.core.llm_queue import get_llm_queue, Priority
        images = get_llm_queue().submit_gpu_task(
            provider_name=backend.name,
            task_type="surface_texture",
            priority=Priority.IMAGE_GEN,
            callable_fn=lambda: backend.generate(prompt, negative, params,
                                                 log_meta=_log_meta),
            agent_name="system",
            label=f"Surface texture: {kind}",
            gpu_type=backend.api_type)
        if not images:
            error = "empty backend result"
            return {"ok": False, "error": error}

        # Contract: JPEG preferred, ≤ 1024² — convert whatever came back.
        import io
        from PIL import Image
        img = Image.open(io.BytesIO(images[0])).convert("RGB")
        if max(img.size) > 1024:
            img.thumbnail((1024, 1024))
        out = _new_path(kind, ".jpg")
        img.save(out, "JPEG", quality=90)
        _write_meta(out, {
            "created_at": utc_now_iso(),
            "source": "generated",
            "backend": backend.name,
            "prompt": prompt,
            "negative": negative,
        })
        select_texture(kind, out.name)
        logger.info("Surface texture %s: %s (%d bytes, backend %s)",
                    kind, out.name, out.stat().st_size, backend.name)
        return {"ok": True, "filename": out.name}
    except Exception as e:
        error = str(e)
        logger.error("Surface texture %s failed: %s", kind, e)
        return {"ok": False, "error": error}
    finally:
        if task_id:
            try:
                get_task_queue().track_finish(task_id, error=error)
            except Exception:
                pass


def trigger_generation(kind: str = "", *, name: str = "",
                       description: str = "", backend_glob: str = "",
                       prompt: str = "", negative: str = "") -> str:
    """Start a texture generation in the background and return the ID it runs
    for ('' = nothing usable, 'busy' = already running).

    The ID comes from ``kind`` when one is given, else from the name — the
    caller may send just a name and read the id back. Name and description
    are seeded on first use, so a fresh kind carries its own prompt text
    instead of leaning on a runtime fallback.

    Different backends for the same kind run concurrently (each queues on its
    own GPU channel); only THIS kind+backend combination is refused while it
    is still running (double-click guard)."""
    kind = safe_kind(kind) or slug_for_name(name)
    if not kind:
        return ""
    ensure_kind_meta(kind, name=name, description=description)
    key = _gen_key(kind, backend_glob)
    with _lock:
        if key in _generating:
            return "busy"
        _generating.add(key)

    def _run() -> None:
        try:
            _generate(kind, backend_glob, prompt, negative)
        finally:
            with _lock:
                _generating.discard(key)

    threading.Thread(target=_run, daemon=True).start()
    return kind
