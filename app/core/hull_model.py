"""Build declarative hull jobs, run Blender and report saved-plan staleness."""
from copy import deepcopy
import json
import secrets
from pathlib import Path
import tempfile
from typing import Any, Dict, Optional

from app.core import hull_styles, surface_textures
from app.core.hull_facts import hull_facts
from app.core.hull_geometry import build_hull, fit_budget
from app.core.hull_mesh import rng
from app.core.log import get_logger
from app.core.roof_model import _timeout_s, tone_to_linear
from app.core.scene_recipe import scene_mesh_placement

logger = get_logger(__name__)
FALLBACK_TONES: Dict[str, str] = {
    "wall": "#a99c86", "wall_ground": "#948774", "plinth": "#68635d",
    "roof": "#675b52", "trim": "#59432e", "door": "#654b32", "chimney": "#82776b",
}


def _materials(style: Dict, desc: Dict, tex_dir: Path) -> tuple:
    """Tint texture copies deterministically and retain their physical UV sizes."""
    from PIL import Image
    materials, textures, sizes = [], {}, {}
    tex_dir.mkdir(parents=True, exist_ok=True)
    for material in hull_styles.MATERIAL_KEYS:
        source = surface_textures.base_texture_file(style["materials"][material])
        key = None
        color = tone_to_linear(FALLBACK_TONES[material])
        if source and source.is_file():
            sizes[material] = surface_textures.texture_size_m(source)
            generator = rng(desc["seed"], f"tint:{material}")
            tint = desc["overrides"].get("tint", "#ffffff").lstrip("#")
            factors = [int(tint[i:i + 2], 16) / 255 *
                       (1 + generator.uniform(-style["tint_jitter"], style["tint_jitter"]))
                       for i in (0, 2, 4)]
            with Image.open(source) as image:
                channels = image.convert("RGB").split()
                tinted = Image.merge("RGB", tuple(channel.point(
                    [max(0, min(255, round(value * factor))) for value in range(256)])
                    for channel, factor in zip(channels, factors)))
                target = tex_dir / f"{material}.png"
                tinted.save(target, format="PNG")
            key = f"texture_{material}"
            textures[key] = str(target)
            color = [1.0, 1.0, 1.0]
        elif style["materials"][material]:
            # An empty kind (an optional slot like wall_ground) is not a defect.
            logger.warning("Hull material %s: missing texture kind %s; using fallback colour",
                           material, style["materials"][material])
        materials.append({"name": material, "texture": key, "color": color,
                          "roughness": 0.8, "alpha": 1.0})
    for material in ("glass", "interior"):
        materials.append({"name": material, "texture": None,
                          "color": tone_to_linear(style["palette"][material]),
                          "roughness": 0.1 if material == "glass" else 0.8,
                          "alpha": 0.6 if material == "glass" else 1.0})
    return materials, textures, sizes


def _meshes(parts: list, tier: str) -> list:
    """Merge parts by material without losing face-corner attributes."""
    merged = {}
    for part in parts:
        material = part["material"]
        mesh = merged.setdefault(material, {"name": f"hull_{tier}_{material}",
            "material": material, "vertices": [], "faces": [], "uvs": [], "colors": []})
        offset = len(mesh["vertices"])
        mesh["vertices"].extend([[x, -z, y] for x, y, z in part["vertices"]])
        mesh["faces"].extend([[index + offset for index in face] for face in part["faces"]])
        mesh["uvs"].extend(part["uvs"])
        mesh["colors"].extend(part["colors"])
    return [merged[key] for key in sorted(merged)]


def build_job(location_id: str, description: Any, location: Optional[Dict] = None,
              *, tex_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Return finished Blender meshes and tinted inputs for both hull tiers."""
    if location is None:
        from app.models.world import get_location_by_id
        location = get_location_by_id(location_id)
    if location is None:
        return {"ok": False, "error": "not_found"}
    facts = hull_facts(location, location_id)
    if not facts["ok"]:
        return facts
    styles = hull_styles.load_styles()
    raw_style = description.get("style") if isinstance(description, dict) else None
    if raw_style is not None and (not isinstance(raw_style, str) or raw_style not in styles):
        return {"ok": False, "error": "unknown_style"}
    desc = hull_styles.validate_description(description, styles)
    style = styles.get(desc["style"])
    if style is None:
        return {"ok": False, "error": "unknown_style"}
    directory = Path(tex_dir) if tex_dir is not None else Path(tempfile.mkdtemp(prefix="av-hull-textures-"))
    materials, textures, sizes = _materials(style, desc, directory)
    try:
        fitted = fit_budget(facts, style, desc, uv_sizes=sizes)
    except ValueError as error:
        if str(error) == "hull too large":
            return {"ok": False, "error": "too_large"}
        raise
    tiers, placement = {}, {}
    for tier in ("full", "low"):
        geometry = build_hull(facts, style, fitted, tier=tier, uv_sizes=sizes)
        tiers[tier] = {"meshes": _meshes(geometry["parts"], tier)}
        placement[tier] = scene_mesh_placement(location, geometry["bounds"]["min"],
                                               geometry["bounds"]["max"])
        if tier == "full":
            padding = geometry["padding_m"]
    return {"kind": "hull", "location_id": location_id, "description": desc,
            "ornament_density_used": fitted["overrides"]["ornament_density"],
            "style_id": desc["style"], "fingerprint": facts["fingerprint"],
            "tiers": tiers, "materials": materials, "textures": textures,
            "extras": {"interior_cutout_padding_m": padding},
            "export": {"full": "hull_full.glb", "low": "hull_low.glb"},
            "placement": placement}


def apply_wall_kinds(location_id: str, style: Dict) -> bool:
    """Write facade texture kinds through the location update operation."""
    from app.models.world import get_location_by_id
    from app.core.world_ops import update_location_with_extras
    location = get_location_by_id(location_id)
    if location is None:
        return False
    map3d = deepcopy(location.get("map3d") or {})
    map3d["wall_kind"] = style["materials"]["wall"]
    if style["materials"].get("wall_ground"):
        map3d["level_walls"] = {"0": style["materials"]["wall_ground"]}
    else:
        map3d.pop("level_walls", None)
    update_location_with_extras(location_id, {"map3d": map3d})
    return True


def generate_hull(location_id: str, description: Any) -> Dict[str, Any]:
    """Build and pin both gallery tiers synchronously, then update wall kinds."""
    from app.blender import runner
    from app.core.location_model3d import save_hull_model
    if not runner.is_available():
        return {"ok": False, "error": "blender_unavailable"}
    with tempfile.TemporaryDirectory(prefix="av-hull-") as temporary:
        directory = Path(temporary)
        job = build_job(location_id, description, tex_dir=directory / "textures")
        if not job.get("ok", True):
            return job
        job_file = directory / "job.json"
        job_file.write_text(json.dumps(job, sort_keys=True), encoding="utf-8")
        out_dir = directory / "out"
        out_dir.mkdir()
        result = runner.run("hull_build", inputs={"job": job_file, **job["textures"]},
                            out_dir=out_dir, timeout_s=_timeout_s())
        if not result.get("ok"):
            return {"ok": False, "error": str(result.get("error") or "build failed")}
        outputs = result.get("outputs") or {}
        files = {tier: Path(outputs.get(tier) or "") for tier in ("full", "low")}
        if not all(file.is_file() for file in files.values()):
            return {"ok": False, "error": "no glb produced"}
        meta = save_hull_model(location_id, files["full"].read_bytes(), files["low"].read_bytes(),
            placement_full=job["placement"]["full"], placement_low=job["placement"]["low"],
            description=job["description"], fingerprint=job["fingerprint"], style_id=job["style_id"])
        apply_wall_kinds(location_id, hull_styles.get_style(job["style_id"]))
    return {"ok": True, "error": "", "meta": meta}


def trigger_hull_generation(location_id: str, description: Any) -> bool:
    """Launch one tracked daemon build using the gallery job guard."""
    import threading
    from app.core.location_model3d import claim_job, release_job
    if not claim_job(location_id, kind="hull"):
        return False

    def _run() -> None:
        task_id, error = "", ""
        try:
            from app.core.task_queue import get_task_queue
            from app.models.world import get_location_by_id
            label = str((get_location_by_id(location_id) or {}).get("name") or location_id)
            try:
                task_id = get_task_queue().track_start(
                    "model3d_generation", f"Hull: {label}", start_running=True)
            except Exception:
                task_id = ""
            result = generate_hull(location_id, description)
            error = "" if result.get("ok") else str(result.get("error") or "failed")
        except Exception as exception:
            error = str(exception)
            logger.exception("Hull generation for %s failed", location_id)
        finally:
            if task_id:
                try:
                    get_task_queue().track_finish(task_id, error=error)
                except Exception:
                    logger.exception("Could not finish hull task %s", task_id)
            release_job(location_id, kind="hull")

    try:
        threading.Thread(target=_run, daemon=True).start()
    except Exception:
        release_job(location_id, kind="hull")
        raise
    return True


def hull_status(location_id: str) -> Dict[str, Any]:
    """Compare the active full hull's stored fingerprint with current geometry."""
    from app.core import location_model3d
    from app.core.model_store import DEFAULT_TIER, read_sidecar
    from app.models.world import get_location_by_id
    location = get_location_by_id(location_id)
    facts = hull_facts(location, location_id)
    owner = location_model3d._owner_id(location_id)
    gallery = location_model3d._gallery(owner) if owner else None
    selected = gallery.find(DEFAULT_TIER, fallback=False) if gallery else None
    meta = read_sidecar(selected) if selected else {}
    active = bool(meta.get("plan_hull"))
    hull = meta.get("hull") or {}
    built = hull.get("fingerprint", "")
    current = facts.get("fingerprint", "")
    return {"ok": facts["ok"], "error": facts.get("error", ""),
            "has_hull": bool(gallery and any(read_sidecar(file).get("plan_hull") for file in gallery.files())),
            "active": active, "stale": active and built != current,
            "built_fingerprint": built, "current_fingerprint": current,
            "description": hull.get("description"), "pending": location_model3d.is_pending(location_id)}


def propose_hull(location_id: str) -> Dict[str, Any]:
    """Suggest a validated building style with one LLM call, or fresh defaults."""
    from app.models.world import get_location_by_id
    from app.core.roof_model import _parse_json, oriented_bbox
    location = get_location_by_id(location_id)
    facts = hull_facts(location, location_id)
    if not facts["ok"]:
        return facts
    styles = hull_styles.load_styles()
    listing = [{"id": key, "name": style["name"], "description": style["description"]}
               for key, style in styles.items()]
    name = str(location.get("name") or location_id)
    description = {"style": "steinhaus", "seed": secrets.randbelow(2**31),
                   "overrides": {"ornament_density": 0.5}}
    used_llm = False
    try:
        from app.core.llm_router import llm_call
        from app.core.prompt_templates import render_task
        rectangle = oriented_bbox(facts["levels"][0]["outline"])
        system_prompt, user_prompt = render_task(
            "hull_design", name=name,
            description=str(location.get("description") or ""),
            style_hint=str(location.get("style_hint") or ""),
            storeys=len(facts["levels"]), length_m=rectangle["length"],
            depth_m=rectangle["depth"], styles=listing, forms=list(hull_styles.ROOF_FORMS))
        response = llm_call(task="hull_design", system_prompt=system_prompt,
                            user_prompt=user_prompt, agent_name="system",
                            label=f"Hull design: {name}")
        parsed = _parse_json(str(getattr(response, "content", "") or ""))
        if (not parsed or not isinstance(parsed.get("style"), str)
                or parsed["style"] not in styles or not isinstance(parsed.get("overrides"), dict)):
            raise ValueError("Invalid hull design answer")
        description = hull_styles.validate_description(
            {**parsed, "seed": description["seed"]}, styles)
        used_llm = True
    except Exception as error:
        logger.info("Hull design for %s: no LLM answer (%s) — defaults", location_id, error)
    return {"ok": True, "error": "", "location_id": location_id, "name": name,
            "styles": listing, "description_json": description, "llm": used_llm}
