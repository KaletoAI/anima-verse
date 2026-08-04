"""Application-facing side of the Blender stage: what callers actually call.

``runner`` speaks in scripts and job directories; this is the layer that knows
what the app wants done and what belongs in a sidecar. Every model store
(characters, props) uses the SAME entry point, so a new store gets the whole
stage by calling one function rather than by copying a recipe.

Best-effort throughout: a host without Blender, a disabled refinement or a
failing script must never cost an asset that was just generated. Nothing here
modifies a mesh — measuring only reads.
"""
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from app.core.log import get_logger
from app.core.timeutils import utc_now_iso

logger = get_logger(__name__)


def measure_file(path: Path) -> Optional[Dict[str, Any]]:
    """Real geometry of a model file, or None when it could not be measured.

    Adds ``at`` and ``blender`` to what the script reports, so a stored
    measurement says when it was taken and by which version — a number whose
    origin is unknown cannot be trusted later.
    """
    from app.blender import runner
    res = runner.run("measure", inputs={"model": Path(path)})
    if not res.get("ok"):
        logger.debug("nicht vermessen (%s): %s", Path(path).name,
                     res.get("error"))
        return None
    data = dict(res["data"])
    data["at"] = utc_now_iso()
    data["blender"] = runner.version()
    return data


def attach_measurement(meta: Dict[str, Any], path: Path,
                       key: str = "measured") -> bool:
    """Measures ``path`` and puts the result in ``meta[key]``. True when it
    landed. The caller writes the sidecar — one write, not two."""
    data = measure_file(path)
    if data is None:
        return False
    meta[key] = data
    return True


# Where an untouched original goes before a refinement overwrites it. A
# SUBDIRECTORY, not a "<name>.raw.glb" sibling: the stores glob for
# "<signature>.*" to find and purge a model, and a sibling would answer that
# glob — the backup would start being served as if it were the model.
RAW_DIR_NAME = "raw"


def raw_backup_path(path: Path) -> Path:
    return Path(path).parent / RAW_DIR_NAME / Path(path).name


def apply_script(path: Path, script: str, params: Dict[str, Any], *,
                 validator: Optional[Callable[[bytes], Dict[str, Any]]] = None,
                 require_smaller: bool = True,
                 keep_original: bool = True) -> Dict[str, Any]:
    """Runs a mesh-modifying script and swaps its result in ONLY if it earns it.

    Four gates, in order. The result must exist (a script that finds nothing to
    do declares no output), it must be smaller when ``require_smaller``, it must
    pass ``validator`` — the SAME check a freshly delivered model faces — and
    only then does it replace the file. Anything else leaves the original
    exactly as it was.

    The gates are the point. A GLB export can rewrite skins and joint order,
    and the 52-joint rule is unforgiving; a model that cost minutes of GPU must
    not die of an exporter detail. With ``keep_original`` the untouched file is
    kept under ``raw/`` first — an img2mesh bake is not reproducible, so
    without it a bad refinement would be final.

    Returns ``{"ok", "applied", "data", "error"}``. ``ok`` says the script ran,
    ``applied`` says the file on disk changed.
    """
    import shutil
    import tempfile
    from app.blender import runner

    path = Path(path)
    out: Dict[str, Any] = {"ok": False, "applied": False, "data": {}, "error": ""}
    with tempfile.TemporaryDirectory(prefix="av-refine-") as tmp:
        res = runner.run(script, inputs={"model": path}, params=params,
                         out_dir=Path(tmp))
        out["data"] = res.get("data") or {}
        if not res.get("ok"):
            out["error"] = res.get("error") or "script failed"
            return out
        out["ok"] = True
        produced = res.get("outputs", {}).get("model")
        if not produced:
            out["error"] = "nothing to do"
            return out

        result = Path(produced)
        blob = result.read_bytes()
        if require_smaller and len(blob) >= path.stat().st_size:
            out["error"] = "result is not smaller"
            return out
        if validator is not None:
            verdict = validator(blob)
            if not verdict.get("ok"):
                out["error"] = ("refined model failed validation: "
                                + "; ".join(verdict.get("errors") or []))
                logger.warning("%s: %s — Original behalten", path.name,
                               out["error"])
                return out

        if keep_original:
            backup = raw_backup_path(path)
            # Only the FIRST time: a second run must not overwrite the true
            # original with an already-refined file.
            if not backup.exists():
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, backup)
        path.write_bytes(blob)
        out["applied"] = True
        logger.info("%s: %s angewandt (%d -> %d bytes)", path.name, script,
                    out["data"].get("before", {}).get("file_bytes", 0), len(blob))
    return out


def retexture(path: Path,
              validator: Optional[Callable[[bytes], Dict[str, Any]]] = None
              ) -> Dict[str, Any]:
    """Re-encodes a GLB's textures to JPEG at the configured quality.

    The single biggest win available: 70–93 % of a generated GLB is texture,
    stored as uncompressed PNG. Geometry, UVs and rig are untouched, and
    images that need an alpha channel stay PNG.
    """
    from app.core import config
    if Path(path).suffix.lower() not in (".glb", ".gltf"):
        return {"ok": False, "applied": False, "data": {},
                "error": f"retexture handles GLB, not {Path(path).suffix}"}
    params = {
        "jpeg_quality": config.get("image_generation.blender_jpeg_quality", 85),
        "max_texture_size": config.get(
            "image_generation.blender_max_texture_size", 0),
    }
    return apply_script(path, "retexture", params, validator=validator,
                        require_smaller=True,
                        keep_original=bool(config.get(
                            "image_generation.blender_keep_original", True)))


# What a distance mesh is built from, and how hard it may be reduced. The
# kinds are separate settings because they fail differently: a prop is a
# compact shape with evenly spread triangles, a room is flat walls beside a
# few small details, and a character is watched closely and in motion.
LOD_KINDS = ("character", "prop", "room", "building")


def lod_ratio(kind: str) -> float:
    """Configured target fraction for this kind of subject.

    A world that predates these settings has no value stored, and the fallback
    then comes from the SCHEMA — not from a second number written here, which
    would silently disagree with what the admin page shows as the default.
    """
    from app.core import config
    from app.core.config_schema import get_schema
    key = kind if kind in LOD_KINDS else "prop"
    field = f"blender_lod_ratio_{key}"
    fallback = 0.25
    try:
        fallback = float(
            get_schema()["image_generation"]["fields"][field]["default"])
    except (KeyError, TypeError, ValueError):
        pass
    try:
        return float(config.get(f"image_generation.{field}", fallback) or fallback)
    except (TypeError, ValueError):
        return fallback


def auto_retexture_enabled() -> bool:
    """Whether a freshly stored model is re-encoded without being asked."""
    from app.core import config
    return bool(config.get("image_generation.blender_auto_retexture", True))


def unavailable_reason() -> str:
    """Why measuring is not possible right now, "" when it is.

    Callers turn this into an HTTP error; keeping the wording here means the
    admin reads the same sentence wherever the stage is offered.
    """
    from app.blender import runner
    st = runner.status()
    if not st["enabled"]:
        return "blender refinement is disabled"
    if not st["executable"]:
        return "no blender executable found"
    return ""
