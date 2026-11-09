"""Model overview and image freshness — what the character tabs show beside
a 3D model or an image, decided here on the server.

1. STEPS — the side overview of a model (3D tab, Base body tab): one generic
   list per model, ``[{id, label, status, detail, numbers}]``, built from the
   model's sidecar and the records next to it, so both tabs render the same
   component. ``status``: ``done`` / ``skipped`` / ``warning`` / ``failed`` /
   ``missing`` (nothing recorded). ``label`` is a fixed English phrase the
   React tab translates; ``detail`` is server English with numbers in it;
   ``numbers`` are the raw values (``{name: number | str}``).

   - ``base_model_steps``: the base model ``model3d/<bsig>.glb`` — hand check
     of the front image, mesh, face retexture, black-eye check, rig, head
     twist, normalize, limb weights, extension rig, covered variant
     (``model3d/covered/<bsig>.glb``), texture re-encode, measurement.
   - ``outfit_model_steps``: an outfit model on the base-body pipeline
     (sidecar ``source: "base_body"``) — base model used, base variant and
     the piece that decided it, every dressed view with its fit gate and
     view guard, the back refit, the body retexture proof, the restored face
     texels, the extension rig (inherited from the base), the own-mesh
     pieces (own garment mesh / left painted on), the garments assembled
     onto it, measurement and distance mesh. A model of the old
     path gets no list: the 3D tab keeps its own overview for it.

2. FRESHNESS — ``{state, reason}`` beside every image and 3D preview of the
   character tabs: ``current`` / ``stale`` (made from inputs that changed
   since; ``reason`` names what, several joined by `` · ``) / ``missing``
   (no provenance recorded to compare against). The stale notions are the
   ones the pipeline already keeps: base signature and base view hashes, the
   dressed front a draft was made from, the base views a base model was
   built from, an own-mesh piece painted on that has its garment mesh now
   (``mesh_item_ready``), the garment fsig and the hair stale reasons, the pose render
   behind an old-path model, the profile picture behind the face view.

The ``annotate_*`` functions add both to the payloads of the info routes
(``GET /characters/{n}/base-body``, ``/model3d``, ``/model-refs``,
``/hair``); they only read (sidecars, file hashes cached by stat) and never
raise — a payload without the extras is still a valid payload.
"""
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.core.log import get_logger

logger = get_logger("model_overview")

CURRENT = "current"
STALE = "stale"
MISSING = "missing"

DONE = "done"
SKIPPED = "skipped"
WARNING = "warning"
FAILED = "failed"
NOT_RECORDED = "missing"

# Freshness reasons — fixed English phrases (the React badge translates
# each part of a `` · `` joined reason).
OLDER_BASE_BODY = "Made from an older base body"
OLDER_BASE_VIEW = "Made from an older base view"
OLDER_FRONT_VIEW = "Made from an older front view"
OLDER_DRESSED_FRONT = "Made from an older dressed front"
BASE_VIEWS_CHANGED = "Base views re-rendered since this model"
DRESSED_VIEWS_CHANGED = "Dressed views re-rendered since this model"
POSE_RENDER_CHANGED = "Pose render changed since this model"
STAND_IN = "Stand-in: model of another outfit"
PROFILE_CHANGED = "The profile picture changed"
OLDER_FIT = "An older fit is shown"
NO_PROVENANCE = "No provenance recorded"
# The same phrase as base_body.MESH_ITEM_READY: an own-mesh piece this image or
# model left painted on has an accepted garment fit now.
MESH_ITEM_READY = "An own-mesh piece painted on here has its garment mesh now"
# The same phrases as base_body.OLDER_BASE / BEFORE_PIPELINE / DETAIL_CHANGED / MESH_ITEM_READY.
MODEL_STALE_REASONS = {"older_base": "Built on an older base body",
                       "before_pipeline": "Built before the base body pipeline",
                       "detail_changed": "Built for another body detail under the clothing",
                       "mesh_item_ready": MESH_ITEM_READY}
# garments.garment_info ``stale_reasons`` -> phrase (the Hair tab's labels).
HAIR_STALE_REASONS = {"description_changed": "Hair description changed",
                      "base_changed": "Base body changed",
                      "base_model_changed": "Base model changed",
                      "hairdeck_changed": "Profile picture or HairDeck settings changed",
                      "colour_changed": "Hair colour changed",
                      "placement_changed": "Hair placement changed"}
FITTED_ON_OLDER_BASE = "Fitted on an older base model"


def freshness(state: str, reason: str = "") -> Dict[str, str]:
    return {"state": state, "reason": reason}


def _join(reasons: Iterable[str]) -> str:
    seen: List[str] = []
    for r in reasons:
        if r and r not in seen:
            seen.append(r)
    return " · ".join(seen)


def step(step_id: str, label: str, status: str, detail: str = "",
         numbers: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {"id": step_id, "label": label, "status": status, "detail": detail,
            "numbers": {k: v for k, v in (numbers or {}).items() if v is not None}}


def _num(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value:
        return None
    return float(value)


def _pct(value: Any) -> str:
    v = _num(value)
    return f"{v * 100:.1f} %" if v is not None else "–"


def _dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


# --- Steps shared by both model kinds ----------------------------------------

def _rig_step(meta: Dict[str, Any], *, inherited: bool = False) -> Dict[str, Any]:
    error = str(meta.get("rig_error") or "")
    rig = meta.get("rig") or ""
    backend = str(meta.get("rig_backend") or "")
    if error:
        return step("rig", "Rig", FAILED, error)
    if not rig or rig == "none":
        return step("rig", "Rig", NOT_RECORDED, "No rig")
    detail = f"{rig} · {backend}" if backend else rig
    if inherited:
        detail += " · from the base model"
    return step("rig", "Rig", DONE, detail)


def _head_twist_step(blender: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    twist = _dict(blender.get("head_twist"))
    if not twist:
        return None
    before = _dict(twist.get("before"))
    after = _dict(twist.get("after"))
    numbers = {"head_before_deg": _num(before.get("head")), "head_after_deg": _num(after.get("head"))}
    if twist.get("error"):
        return step("head_twist", "Head twist", FAILED, str(twist["error"]), numbers)
    if twist.get("corrected"):
        changes = [before[n] - after[n] for n in ("head", "neck")
                   if _num(before.get(n)) is not None and _num(after.get(n)) is not None]
        fixed = max(changes, key=abs) if changes else None
        detail = f"corrected {abs(fixed):.1f}°" if fixed is not None else "corrected"
        return step("head_twist", "Head twist", DONE, detail, numbers)
    head = _num(before.get("head"))
    return step("head_twist", "Head twist", DONE,
                f"straight ({abs(head):.1f}°)" if head is not None else "straight", numbers)


def _normalize_step(blender: Dict[str, Any]) -> Dict[str, Any]:
    if "normalize" not in (blender.get("steps") or []):
        return step("normalize", "Normalize", NOT_RECORDED, "Not run")
    before = _dict(blender.get("before"))
    after = _dict(blender.get("after"))
    h_before = (before.get("dims_m") or [None, None, None])[2] if isinstance(before.get("dims_m"), list) else None
    h_after = (after.get("dims_m") or [None, None, None])[2] if isinstance(after.get("dims_m"), list) else None
    scale = _num(blender.get("scale"))
    target = _num(blender.get("target_height_m"))
    detail = " · ".join(filter(None, [f"×{scale:.4f}" if scale is not None else "",
                                      f"{target:.2f} m" if target is not None else ""]))
    return step("normalize", "Normalize", DONE, detail,
                {"scale": scale, "height_before_m": _num(h_before), "height_after_m": _num(h_after)})


def _limb_weights_step(blender: Dict[str, Any], rig: str) -> Optional[Dict[str, Any]]:
    if rig != "mixamo":
        return None
    report = _dict(blender.get("limb_weights"))
    numbers = {k: _num(report.get(k)) for k in ("vertices", "fully_foreign", "unresolved")}
    if report.get("error"):
        return step("limb_weights", "Limb weights", FAILED, str(report["error"]), numbers)
    if report.get("skipped"):
        return step("limb_weights", "Limb weights", SKIPPED, str(report["skipped"]), numbers)
    if "limb_weights" not in (blender.get("steps") or []):
        return step("limb_weights", "Limb weights", NOT_RECORDED, "Not checked")
    repaired = int(report.get("vertices") or 0)
    unresolved = int(report.get("unresolved") or 0)
    detail = f"{repaired} vertices repaired" if repaired else "clean"
    if unresolved:
        return step("limb_weights", "Limb weights", WARNING, f"{detail} · {unresolved} unresolved", numbers)
    return step("limb_weights", "Limb weights", DONE, detail, numbers)


def _extension_step(state: Dict[str, Any], *, source: str = "") -> Dict[str, Any]:
    if not state:
        return step("extension_rig", "Extension rig", SKIPPED, "No extension groups")
    status = str(state.get("status") or "")
    groups = [g for g in (state.get("groups") or []) if isinstance(g, str)]
    reason = str(state.get("reason") or "")
    detail = ", ".join(groups)
    if source:
        detail = f"{detail} · {source}" if detail else source
    numbers = {"groups": len(groups)}
    if status == "applied":
        return step("extension_rig", "Extension rig", DONE, detail, numbers)
    if status == "failed":
        return step("extension_rig", "Extension rig", FAILED, reason or detail, numbers)
    if status == "not_found":
        return step("extension_rig", "Extension rig", WARNING, reason or "Geometry not found", numbers)
    if status == "none_applicable" or not groups:
        return step("extension_rig", "Extension rig", SKIPPED, reason or "No applicable groups", numbers)
    return step("extension_rig", "Extension rig", NOT_RECORDED, reason or "Not processed", numbers)


def _texture_step(meta: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    refined = _dict(meta.get("refined"))
    if not refined:
        return None
    if refined.get("retexture"):
        saved = _num(refined.get("bytes_saved"))
        return step("texture", "Texture re-encode", DONE,
                    f"{saved / (1024 * 1024):.1f} MB saved" if saved else "", {"bytes_saved": saved})
    return step("texture", "Texture re-encode", SKIPPED, str(refined.get("reason") or ""))


def _measure_step(meta: Dict[str, Any]) -> Dict[str, Any]:
    measured = _dict(meta.get("measured"))
    if not measured:
        return step("measure", "Measurement", NOT_RECORDED, "Not measured")
    dims = measured.get("dims_m") if isinstance(measured.get("dims_m"), list) else []
    height = _num(dims[2]) if len(dims) > 2 else None
    tris = _num(measured.get("tris"))
    bones = _num(measured.get("bones"))
    parts = [f"{int(tris):,} tris" if tris is not None else "",
             f"{int(bones)} bones" if bones is not None else "",
             f"h {height:.2f} m" if height is not None else ""]
    return step("measure", "Measurement", DONE, " · ".join(p for p in parts if p),
                {"tris": tris, "bones": bones, "height_m": height})


def _lod_step(meta: Dict[str, Any], tiers: List[str], low_tris: Any = None) -> Dict[str, Any]:
    if meta.get("lod_error"):
        return step("lod", "Distance mesh", FAILED, str(meta["lod_error"]))
    if "low" in tiers:
        tris = _num(low_tris)
        return step("lod", "Distance mesh", DONE, f"{int(tris):,} tris" if tris is not None else "",
                    {"tris": tris})
    return step("lod", "Distance mesh", NOT_RECORDED, "Not built yet")


# --- The base model ------------------------------------------------------------

def _hand_gate_step(front_meta: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if front_meta is None:
        return step("hand_gate", "Front view hand check", NOT_RECORDED, "No front view")
    gate = _dict(front_meta.get("hand_gate"))
    if not gate:
        return step("hand_gate", "Front view hand check", NOT_RECORDED, "Not recorded")
    attempts = [a for a in (gate.get("attempts") or []) if isinstance(a, dict)]
    chosen = int(gate.get("chosen") or 1)
    record = attempts[chosen - 1] if 0 < chosen <= len(attempts) else {}
    numbers = {"score": _num(record.get("score")), "limit": _num(gate.get("limit")),
               "attempts": len(attempts)}
    if gate.get("ok"):
        return step("hand_gate", "Front view hand check", DONE,
                    f"passed on attempt {chosen} of {len(attempts)}", numbers)
    return step("hand_gate", "Front view hand check", WARNING,
                f"palms may face the camera — kept attempt {chosen} of {len(attempts)} without a pass", numbers)


def _mesh_step(meta: Dict[str, Any]) -> Dict[str, Any]:
    backend = str(meta.get("mesh_backend") or meta.get("backend") or "")
    views = 1 + len(_dict(meta.get("view_images"))) if meta.get("source_image") else 0
    if not backend and not views:
        return step("mesh", "Mesh", NOT_RECORDED, "Not recorded")
    detail = " · ".join(filter(None, [backend, f"{views} views" if views else ""]))
    return step("mesh", "Mesh", DONE, detail, {"views": views or None})


def _face_steps(face: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The face retexture row and — once recorded — the black-eye check."""
    if not face:
        return [step("face_retexture", "Face retexture", NOT_RECORDED, "Not run")]
    status = str(face.get("status") or "")
    baked = _dict(face.get("baked"))
    numbers = {"texels_replaced": _num(baked.get("texels_replaced")),
               "body_texels_recolored": _num(baked.get("body_texels_recolored"))}
    detail = " · ".join(filter(None, [str(face.get("backend") or ""),
                                      "face view" if face.get("reference") == "face" else
                                      "front image" if face.get("reference") == "front" else ""]))
    if status == "failed":
        rows = [step("face_retexture", "Face retexture", FAILED, str(face.get("error") or face.get("reason") or ""),
                     numbers)]
    elif status == "skipped":
        rows = [step("face_retexture", "Face retexture", SKIPPED, str(face.get("reason") or ""), numbers)]
    elif status == "applied" and face.get("face_texture_lost"):
        rows = [step("face_retexture", "Face retexture", WARNING, "Face texture lost", numbers)]
    elif status == "applied":
        rows = [step("face_retexture", "Face retexture", DONE, detail, numbers)]
    else:
        rows = [step("face_retexture", "Face retexture", SKIPPED, f"reverted ({status})" if status else "")]
    if status != "applied":
        return rows
    gate = _dict(face.get("dark_gate"))
    if not gate:
        rows.append(step("dark_gate", "Black-eye check", NOT_RECORDED, "Not recorded (made before the check)"))
        return rows
    gnums = {"dark_share": _num(gate.get("dark_share")), "photo_dark_share": _num(gate.get("photo_dark_share")),
             "excess": _num(gate.get("excess")), "limit": _num(gate.get("limit")),
             "retry_yaw": _num(gate.get("retry_yaw"))}
    shares = f"{_pct(gate.get('dark_share'))} dark vs photo {_pct(gate.get('photo_dark_share'))}"
    if not gate.get("ok", True):
        rows.append(step("dark_gate", "Black-eye check", WARNING,
                         str(gate.get("warning") or "dark texels in the face") + f" · {shares}", gnums))
    elif gate.get("retried"):
        which = "retry kept" if gate.get("chosen") == "retry" else "first bake kept"
        rows.append(step("dark_gate", "Black-eye check", DONE, f"passed after a retry ({which}) · {shares}", gnums))
    else:
        rows.append(step("dark_gate", "Black-eye check", DONE, f"passed · {shares}", gnums))
    return rows


def _covered_step(record: Dict[str, Any], *, exists: bool, current: Optional[bool]) -> Dict[str, Any]:
    if not record:
        return step("covered_variant", "Covered variant", SKIPPED, "No exposed-only groups")
    removed = [g for g in (record.get("groups_removed") or []) if isinstance(g, str)]
    numbers = {"groups_removed": len(removed)}
    if record.get("status") == "failed":
        return step("covered_variant", "Covered variant", FAILED, str(record.get("reason") or ""), numbers)
    detail = "without " + ", ".join(removed) if removed else ""
    if not exists:
        return step("covered_variant", "Covered variant", WARNING, "File missing", numbers)
    if current is False:
        return step("covered_variant", "Covered variant", WARNING,
                    f"{detail} · built from another clean source" if detail else "built from another clean source",
                    numbers)
    return step("covered_variant", "Covered variant", DONE, detail, numbers)


def base_model_steps(meta: Dict[str, Any], *, front_meta: Optional[Dict[str, Any]],
                     covered_exists: bool = False, covered_current: Optional[bool] = None) -> List[Dict[str, Any]]:
    """The steps of a base model (pure). ``meta``: its sidecar;
    ``front_meta``: the sidecar of the current base front image (its
    ``hand_gate``), None without one; ``covered_exists`` / ``covered_current``:
    whether ``model3d/covered/<bsig>.glb`` exists and was built from the
    model's current clean prerig source (None = unknown)."""
    blender = _dict(meta.get("blender"))
    rows = [_hand_gate_step(front_meta), _mesh_step(meta), *_face_steps(_dict(meta.get("face_retexture"))),
            _rig_step(meta)]
    for row in (_head_twist_step(blender), _normalize_step(blender),
                _limb_weights_step(blender, str(meta.get("rig") or "")),
                _extension_step(_dict(meta.get("extension_rig"))),
                _covered_step(_dict(meta.get("covered_variant")), exists=covered_exists, current=covered_current),
                _texture_step(meta), _measure_step(meta)):
        if row is not None:
            rows.append(row)
    return rows


# --- The outfit model on the base-body pipeline --------------------------------

def _base_used_step(meta: Dict[str, Any], base: Optional[Tuple[str, str]]) -> Dict[str, Any]:
    bsig = str(meta.get("base_signature") or "")
    if not bsig:
        return step("base", "Base model", WARNING, MODEL_STALE_REASONS["before_pipeline"])
    if base is None:
        return step("base", "Base model", NOT_RECORDED, bsig)
    if bsig != base[0]:
        return step("base", "Base model", WARNING, f"{bsig} · older base body (now {base[0]})")
    if meta.get("base_model_sha256") != base[1]:
        return step("base", "Base model", WARNING, f"{bsig} · the base model was regenerated since")
    return step("base", "Base model", DONE, f"{bsig} · current")


def _variant_step(meta: Dict[str, Any], *, wanted: Optional[str], deciders: List[str],
                  shown: List[str], covered_missing_text: str) -> Dict[str, Any]:
    built = str(meta.get("base_variant") or "rigged")
    if meta.get("dressed") is False:
        return step("variant", "Base variant", DONE, "rigged · undressed combination")
    parts = [built]
    if deciders:
        parts.append("hidden by " + ", ".join(deciders))
    if shown:
        parts.append("shown through " + ", ".join(shown) + " (exposed detail)")
    detail = " · ".join(parts)
    if meta.get("covered_missing"):
        return step("variant", "Base variant", WARNING, f"{detail} · {covered_missing_text}")
    if wanted is not None and wanted != built:
        return step("variant", "Base variant", WARNING, f"{detail} · the pieces now call for {wanted}")
    return step("variant", "Base variant", DONE, detail)


def _dressed_view_step(view: str, *, used: bool, record: Optional[Dict[str, Any]],
                       guard: Dict[str, Any], delta_e: Optional[float]) -> Dict[str, Any]:
    label = {"front": "Dressed front", "back": "Dressed back", "left": "Dressed left",
             "right": "Dressed right"}.get(view, "Dressed view")
    fit = _dict((record or {}).get("fit_gate"))
    attempts = [a for a in (fit.get("attempts") or []) if isinstance(a, dict)]
    chosen = int(fit.get("chosen") or 0)
    pick = attempts[chosen - 1] if 0 < chosen <= len(attempts) else {}
    score = _num(_dict(guard.get("scores")).get(view))
    numbers = {"guard_score": score, "noise": _num(_dict(pick.get("noise")).get("score")),
               "noise_limit": _num(fit.get("noise_limit")), "fit_attempts": len(attempts) or None,
               "unchanged_delta_e": delta_e}
    parts = []
    if guard:
        parts.append(f"view check {guard.get('best') or '?'}" + (" · re-rendered" if guard.get("rerendered") else ""))
    if attempts:
        parts.append(f"fit attempt {chosen} of {len(attempts)}")
    if delta_e is not None:
        parts.append(f"ΔE {delta_e:.1f}")
    detail = " · ".join(parts)
    if not used:
        return step(f"dressed_{view}", label, WARNING, "turned around — left out of the model"
                    + (f" · {detail}" if detail else ""), numbers)
    if fit.get("warning"):
        return step(f"dressed_{view}", label, WARNING, str(fit["warning"]), numbers)
    if guard and not guard.get("ok", True):
        return step(f"dressed_{view}", label, WARNING, detail, numbers)
    return step(f"dressed_{view}", label, DONE, detail, numbers)


def _refit_step(meta: Dict[str, Any], back_delta: Optional[float], limit: float,
                has_back: bool) -> Optional[Dict[str, Any]]:
    refit = _dict(meta.get("back_refit"))
    if not refit:
        if not has_back:
            return None
        if back_delta is None:
            return step("back_refit", "Back refit", NOT_RECORDED, "No back ΔE recorded")
        if back_delta > limit:
            # A poor back without a refit record: built before the refit.
            return step("back_refit", "Back refit", NOT_RECORDED,
                        f"Not recorded (built before the refit) · ΔE {back_delta:.1f} > {limit:.1f}",
                        {"unchanged_delta_e": back_delta, "limit": limit})
        return step("back_refit", "Back refit", SKIPPED, f"not needed (ΔE {back_delta:.1f} ≤ {limit:.1f})",
                    {"unchanged_delta_e": back_delta, "limit": limit})
    attempts = [a for a in (refit.get("attempts") or []) if isinstance(a, dict)]
    first = _num(attempts[0].get("unchanged_delta_e")) if attempts else None
    second = _num(attempts[1].get("unchanged_delta_e")) if len(attempts) > 1 else None
    numbers = {"first_delta_e": first, "refit_delta_e": second, "limit": _num(refit.get("limit"))}
    if refit.get("skipped"):
        return step("back_refit", "Back refit", SKIPPED, str(refit["skipped"]), numbers)
    error = str(attempts[1].get("error") or "") if len(attempts) > 1 else ""
    if refit.get("chosen") == 2:
        return step("back_refit", "Back refit", DONE,
                    f"refit kept: ΔE {first:.1f} → {second:.1f}" if first is not None and second is not None
                    else "refit kept", numbers)
    if error:
        return step("back_refit", "Back refit", WARNING, f"first back kept · {error}", numbers)
    return step("back_refit", "Back refit", WARNING,
                f"first back kept: refit not better (ΔE {first:.1f} vs {second:.1f})"
                if first is not None and second is not None else "first back kept", numbers)


def _retexture_step(meta: Dict[str, Any], limit: float) -> Dict[str, Any]:
    proof = meta.get("retexture_proof")
    if not isinstance(proof, dict):
        if meta.get("dressed") is False:
            return step("retexture", "Body retexture", SKIPPED, "Undressed base copy")
        return step("retexture", "Body retexture", NOT_RECORDED, "No proof recorded")
    texels = _dict(proof.get("texels"))
    deltas: Dict[str, Optional[float]] = {}
    for view, record in _dict(proof.get("views")).items():
        deltas[view] = _num(_dict(_dict(record).get("dressed_alignment")).get("unchanged_delta_e"))
    numbers: Dict[str, Any] = {"coverage": _num(texels.get("garment_share_of_exposed")),
                               "unseen_share": _num(texels.get("unseen_filled_share_of_exposed_garment")),
                               "unobserved_share": _num(texels.get("unobserved_share_of_exposed"))}
    for view, value in deltas.items():
        numbers[f"delta_e_{view}"] = value
    parts = [f"coverage {_pct(texels.get('garment_share_of_exposed'))}",
             f"unseen {_pct(texels.get('unseen_filled_share_of_exposed_garment'))}"]
    parts += [f"ΔE {view} {value:.1f}" for view, value in deltas.items() if value is not None]
    high = [view for view, value in deltas.items() if value is not None and value > limit]
    if high:
        return step("retexture", "Body retexture", WARNING,
                    " · ".join(parts) + f" · poor registration: {', '.join(high)}", numbers)
    return step("retexture", "Body retexture", DONE, " · ".join(parts), numbers)


def _face_texels_step(meta: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    proof = meta.get("retexture_proof")
    if not isinstance(proof, dict):
        return None
    if "face_texels_restored" not in proof:
        return step("face_texels", "Face texels restored", NOT_RECORDED, "Not recorded (built before the step)")
    restored = _num(proof.get("face_texels_restored"))
    numbers = {"restored": restored, "mask": _num(proof.get("face_mask_texels"))}
    if proof.get("face_texels_skipped"):
        return step("face_texels", "Face texels restored", SKIPPED, str(proof["face_texels_skipped"]), numbers)
    return step("face_texels", "Face texels restored", DONE,
                f"{int(restored or 0):,} of {int(numbers['mask'] or 0):,} texels", numbers)


def _mesh_items_step(meta: Dict[str, Any], names: Dict[str, str]) -> Optional[Dict[str, Any]]:
    """The own-mesh pieces of an outfit model (sidecar ``mesh_items``): which
    are their own garment mesh, which stayed painted on (their reasons are in
    the garment warnings). None for an outfit without any."""
    mesh = _dict(meta.get("mesh_items"))
    intended = [i for i in mesh.get("intended") or [] if isinstance(i, str)]
    if not intended:
        return None
    effective = [i for i in intended if i in set(mesh.get("effective") or [])]
    painted = [i for i in intended if i not in effective]
    parts = []
    if effective:
        parts.append("own mesh: " + ", ".join(names.get(i, i) for i in effective))
    if painted:
        parts.append("painted on: " + ", ".join(names.get(i, i) for i in painted))
    return step("mesh_items", "Own-mesh pieces", WARNING if painted else DONE, " · ".join(parts),
                {"intended": len(intended), "effective": len(effective)})


def _garment_steps(garments: List[Dict[str, Any]], warnings: List[str]) -> List[Dict[str, Any]]:
    """``garments``: ``[{item_id, name, kind, method, fsig, current_fsig,
    served}]`` (``served``: the assembly on disk carries this fit)."""
    rows: List[Dict[str, Any]] = []
    for g in garments:
        label = "Hair" if g.get("kind") == "hair" else "Garment"
        parts = [str(g.get("name") or g.get("item_id") or ""), str(g.get("method") or ""),
                 f"fsig {g.get('fsig')}" if g.get("fsig") else ""]
        if g.get("fsig") and g.get("current_fsig") and g["fsig"] != g["current_fsig"]:
            status, extra = WARNING, "older fit"
        elif not g.get("served"):
            status, extra = WARNING, "not assembled yet"
        else:
            status, extra = DONE, "served"
        rows.append(step(f"garment_{g.get('item_id')}", label, status,
                         " · ".join(p for p in [*parts, extra] if p)))
    if not garments and not warnings:
        rows.append(step("garments", "Garments", SKIPPED, "No garment on this model"))
    if warnings:
        rows.append(step("garment_warnings", "Garment warnings", WARNING, " · ".join(warnings),
                         {"warnings": len(warnings)}))
    return rows


def outfit_model_steps(meta: Dict[str, Any], *, base: Optional[Tuple[str, str]],
                       base_meta: Optional[Dict[str, Any]], wanted_variant: Optional[str],
                       deciders: List[str], shown: List[str], dressed_records: Dict[str, Optional[Dict[str, Any]]],
                       garments: List[Dict[str, Any]], tiers: List[str], low_tris: Any = None,
                       refit_limit: float = 4.0, covered_missing_text: str = "",
                       item_names: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    """The steps of an outfit model on the base-body pipeline (pure).
    ``meta``: its sidecar; ``base``: the current ``(bsig, base model
    sha256)``; ``base_meta``: the sidecar of the base model it names (None
    when gone); ``wanted_variant``: the variant its pieces call for now;
    ``deciders`` / ``shown``: names of the worn pieces that hide the
    exposed-only groups / show them through (``exposed_detail``);
    ``dressed_records``: the sidecar of every dressed view the build looked
    at (front, back, sides), None when the file is gone; ``garments``: see
    ``_garment_steps``; ``tiers`` / ``low_tris``: the distance mesh;
    ``item_names``: item id -> name for the own-mesh pieces row."""
    proof = _dict(meta.get("retexture_proof"))
    guards = _dict(meta.get("view_guard"))
    used = {"front"} | set(_dict(meta.get("view_images")))
    views = [v for v in ("front", "back", "left", "right") if v in used or v in guards]
    rows = [_base_used_step(meta, base),
            _variant_step(meta, wanted=wanted_variant, deciders=deciders, shown=shown,
                          covered_missing_text=covered_missing_text)]
    deltas = {v: _num(_dict(_dict(_dict(proof.get("views")).get(v)).get("dressed_alignment")).get("unchanged_delta_e"))
              for v in views}
    if meta.get("dressed") is not False:
        for v in views:
            rows.append(_dressed_view_step(v, used=v in used, record=dressed_records.get(v),
                                           guard=_dict(guards.get(v)), delta_e=deltas.get(v)))
        refit = _refit_step(meta, deltas.get("back"), refit_limit, "back" in used)
        if refit is not None:
            rows.append(refit)
    rows.append(_retexture_step(meta, refit_limit))
    face = _face_texels_step(meta)
    if face is not None:
        rows.append(face)
    rows.append(_rig_step(meta, inherited=True))
    state = _dict(meta.get("extension_rig"))
    base_state = _dict((base_meta or {}).get("extension_rig"))
    if meta.get("base_variant") == "covered":
        source = "from the covered variant"
    elif state and base_state and state.get("fingerprint") == base_state.get("fingerprint") \
            and state.get("attempted_at") == base_state.get("attempted_at"):
        source = "inherited from the base model"
    elif state:
        source = "rebuilt for this outfit"
    else:
        source = ""
    rows.append(_extension_step(state, source=source))
    mesh_row = _mesh_items_step(meta, item_names or {})
    if mesh_row is not None:
        rows.append(mesh_row)
    rows += _garment_steps(garments, [w for w in (meta.get("garment_warnings") or []) if isinstance(w, str)])
    rows.append(_measure_step(meta))
    rows.append(_lod_step(meta, tiers, low_tris))
    return rows


# --- Freshness rules (pure) ------------------------------------------------------

def dressed_freshness(meta: Dict[str, Any], *, bsig: str, base_view_sha: str,
                      mesh_ready: bool = False) -> Dict[str, str]:
    """A dressed view on the pipeline: made from the current base view?
    ``mesh_ready``: an own-mesh piece it left painted on has its garment
    mesh now (``base_body.mesh_items_ready``)."""
    if not meta.get("base_signature"):
        return freshness(MISSING, NO_PROVENANCE)
    if meta["base_signature"] != bsig:
        return freshness(STALE, OLDER_BASE_BODY)
    if not meta.get("base_image_sha256"):
        return freshness(MISSING, NO_PROVENANCE)
    if meta["base_image_sha256"] != base_view_sha:
        return freshness(STALE, OLDER_BASE_VIEW)
    if mesh_ready:
        return freshness(STALE, MESH_ITEM_READY)
    return freshness(CURRENT)


def draft_freshness(meta: Dict[str, Any], *, bsig: str, front_sha: str) -> Dict[str, str]:
    """A draft: made from the current dressed front (of the current base)?"""
    reasons = []
    if meta.get("base_signature") and meta["base_signature"] != bsig:
        reasons.append(OLDER_BASE_BODY)
    if not meta.get("front_sha256"):
        return freshness(STALE, _join(reasons)) if reasons else freshness(MISSING, NO_PROVENANCE)
    if meta["front_sha256"] != front_sha:
        reasons.append(OLDER_DRESSED_FRONT)
    return freshness(STALE, _join(reasons)) if reasons else freshness(CURRENT)


def base_view_freshness(view: str, created: str, front_created: str) -> Dict[str, str]:
    """A base view other than the front is an edit of the front: one older
    than the stored front was made from a previous front. Stamps are the
    tile meta's ``created_at`` (aware ISO, comparable as strings in UTC)."""
    if view == "front":
        return freshness(CURRENT)
    if not created or not front_created:
        return freshness(MISSING, NO_PROVENANCE)
    return freshness(STALE, OLDER_FRONT_VIEW) if created < front_created else freshness(CURRENT)


def base_model_freshness(meta: Dict[str, Any], view_shas: Dict[str, str]) -> Dict[str, str]:
    """A base model: built from the base views stored now? ``view_shas``:
    view -> sha256 of the current base view file ("" when absent)."""
    recorded = {"front": meta.get("source_image_sha256") or ""}
    recorded.update({v: s for v, s in _dict(meta.get("view_images_sha256")).items()})
    if not recorded["front"]:
        return freshness(MISSING, NO_PROVENANCE)
    for view, sha in recorded.items():
        if sha and view_shas.get(view, sha) != sha:
            return freshness(STALE, BASE_VIEWS_CHANGED)
    return freshness(CURRENT)


def dressed_newer(model_created: str, records: Dict[str, Optional[Dict[str, Any]]]) -> bool:
    """Whether a dressed view the outfit model was built from was rendered
    again after the model (its sidecar ``created_at`` is later)."""
    if not model_created:
        return False
    return any(str(r.get("created_at") or "") > model_created for r in records.values() if isinstance(r, dict))


def model3d_freshness(model: Dict[str, Any], *, views_newer: bool = False) -> Dict[str, str]:
    """The 3D tab's model (``get_model3d_info``'s ``model``); ``views_newer``:
    ``dressed_newer`` of a pipeline outfit model."""
    reasons = []
    if model.get("match") == "nearest":
        reasons.append(STAND_IN)
    if model.get("stale_base"):
        reasons.append(MODEL_STALE_REASONS.get(model.get("stale_reason") or "", MODEL_STALE_REASONS["older_base"]))
    if views_newer:
        reasons.append(DRESSED_VIEWS_CHANGED)
    elif not model.get("base_signature") and model.get("tpose_status") == "changed":
        reasons.append(POSE_RENDER_CHANGED)
    if reasons:
        return freshness(STALE, _join(reasons))
    if not model.get("base_signature") and model.get("tpose_status") == "unknown" and model.get("match") == "exact":
        return freshness(MISSING, NO_PROVENANCE)
    return freshness(CURRENT)


def hair_preview_freshness(garment: Dict[str, Any]) -> Dict[str, str]:
    """The Hair tab's preview: the current-fsig fit, or an older one."""
    if not garment.get("preview_url"):
        return freshness(MISSING, NO_PROVENANCE)
    fit = _dict(_dict(garment.get("steps")).get("fit"))
    if garment.get("fsig") and fit.get("status") == "accepted":
        return freshness(CURRENT)
    reasons = [HAIR_STALE_REASONS.get(r, r) for r in garment.get("stale_reasons") or [] if isinstance(r, str)]
    return freshness(STALE, _join(reasons) or OLDER_FIT)


# --- IO: the info payloads ---------------------------------------------------------

def _sidecar(path: Optional[Path]) -> Dict[str, Any]:
    if path is None:
        return {}
    from app.core.model3d import _read_sidecar
    return _read_sidecar(path)


def _base_view_shas(character_name: str, bsig: str) -> Dict[str, str]:
    from app.core import base_body
    from app.core.model_refs import find_ref_image
    return {v: base_body.file_sha256(find_ref_image(character_name, base_body._kind(v), bsig))
            for v in base_body.BASE_VIEWS}


def _base_model_path(character_name: str, bsig: str) -> Path:
    from app.core.model3d import get_model3d_dir
    return get_model3d_dir(character_name) / f"{bsig}.glb"


def base_model_overview(character_name: str, bsig: str) -> Optional[Dict[str, Any]]:
    """``{steps, freshness}`` of the stored base model of ``bsig``, None
    without one."""
    import hashlib
    from app.core import base_body
    from app.core.model3d import COVERED_DIR
    from app.core.model_refs import find_ref_image
    path = _base_model_path(character_name, bsig)
    if not path.is_file():
        return None
    meta = _sidecar(path)
    front = find_ref_image(character_name, "tpose", bsig)
    covered = path.parent / COVERED_DIR / path.name
    covered_current: Optional[bool] = None
    if covered.is_file():
        prerig = path.parent / "prerig" / path.name
        recorded = _sidecar(covered).get("source_sha256")
        if prerig.is_file() and recorded:
            try:
                covered_current = hashlib.sha256(prerig.read_bytes()).hexdigest() == recorded
            except OSError:
                covered_current = None
    steps = base_model_steps(meta, front_meta=_sidecar(front) if front else None,
                             covered_exists=covered.is_file(), covered_current=covered_current)
    return {"steps": steps,
            "freshness": base_model_freshness(meta, _base_view_shas(character_name, bsig))}


def annotate_base_info(character_name: str, info: Dict[str, Any]) -> Dict[str, Any]:
    """``base_body.base_info`` + ``model.steps`` / ``model.freshness`` and a
    ``freshness`` in every ``image_meta`` entry. Never raises."""
    try:
        bsig = info.get("signature") or ""
        meta = info.get("image_meta") or {}
        front_created = str((meta.get("front") or {}).get("created_at") or "")
        for view, tile in meta.items():
            if isinstance(tile, dict):
                tile["freshness"] = base_view_freshness(view, str(tile.get("created_at") or ""), front_created)
        model = info.get("model")
        if bsig and isinstance(model, dict):
            overview = base_model_overview(character_name, bsig)
            if overview is not None:
                model.update(overview)
    except Exception:  # noqa: BLE001 — the overview never breaks the poll
        logger.exception("Base body overview of %s failed", character_name)
    return info


def _piece_decision(character_name: str, pieces: Dict[str, str]) -> Tuple[Optional[str], List[str], List[str]]:
    """``(variant the pieces call for, names of the pieces that hide the
    exposed-only groups, names of covering pieces that show them through)``."""
    from app.core import base_body
    from app.core.extension_rig import piece_covering_slots, rig_groups_for
    from app.core.motion_item_cache import item_snapshot
    wanted = base_body.outfit_variant(character_name, pieces)
    if not pieces:
        return wanted, [], []
    items = item_snapshot()
    groups = rig_groups_for(character_name, mesh_variant="")
    targets = {cover for g in groups if g.get("exposed_only") for cover in g.get("covered_by") or []}
    deciders, shown = [], []
    for item_id in sorted(set(pieces.values())):
        item = (items or {}).get(item_id) or {}
        piece = item.get("outfit_piece") or {}
        occupied = {slot for slot, worn in pieces.items() if worn == item_id}
        if not (piece_covering_slots(occupied, piece) & targets):
            continue
        name = str(item.get("name") or item_id)
        (shown if piece.get("exposed_detail") is True else deciders).append(name)
    return wanted, deciders, shown


def _assembled_garments(character_name: str, signature: str) -> List[Dict[str, Any]]:
    from app.core import garment_assembly, garment_store as gs
    from app.core.model3d import get_model3d_dir
    from app.core.motion_item_cache import item_snapshot
    directory = get_model3d_dir(character_name)
    wanted = garment_assembly._wanted_for(character_name, directory, signature)
    assembled = garment_assembly.assembled_path(directory, signature, garment_assembly.FULL)
    carried = _dict(_sidecar(assembled).get("garments")) if assembled.is_file() else {}
    items = item_snapshot() or {}
    out = []
    for g in wanted:
        try:
            current = gs.garment_fsig(character_name, g["item_id"])
        except ValueError:
            current = ""
        out.append({"item_id": g["item_id"], "kind": g["kind"], "fsig": g["fsig"], "current_fsig": current,
                    "name": (items.get(g["item_id"]) or {}).get("name") or g["item_id"],
                    "method": gs.fit_method(g.get("record") or {}),
                    "served": _dict(carried.get(g["item_id"])).get("fsig") == g["fsig"]})
    return out


def outfit_model_overview(character_name: str,
                          path: Path) -> Optional[Tuple[List[Dict[str, Any]], bool]]:
    """``(steps, dressed views newer than the model)`` of the stored outfit
    model ``path`` when it was built on the base-body pipeline (sidecar
    ``source: "base_body"`` or a ``base_signature``), else None (old path)."""
    from app.core import base_body
    from app.core.model3d import available_tiers, tier_variant
    from app.core.model_refs import get_model_refs_dir
    meta = _sidecar(path)
    if meta.get("source") != "base_body" and not meta.get("base_signature"):
        return None
    base = base_body.current_base(character_name)
    bsig = str(meta.get("base_signature") or "")
    base_meta = _sidecar(_base_model_path(character_name, bsig)) if bsig else None
    wanted, deciders, shown = _piece_decision(character_name, _dict(meta.get("pieces")))
    refs = get_model_refs_dir(character_name)
    names = {"front": meta.get("source_image"), **_dict(meta.get("view_images"))}
    for view in _dict(meta.get("view_guard")):
        names.setdefault(view, f"{base_body._kind(view)}_{path.stem}.png")
    records: Dict[str, Optional[Dict[str, Any]]] = {}
    for view, name in names.items():
        if isinstance(name, str) and name and Path(name).name == name:
            records[view] = _sidecar(refs / name) if (refs / name).is_file() else None
    low = tier_variant(path, "low")
    low_tris = _sidecar(low).get("tris") if low else None
    from app.core.motion_item_cache import item_snapshot
    items = item_snapshot() or {}
    steps = outfit_model_steps(meta, base=base, base_meta=base_meta, wanted_variant=wanted, deciders=deciders,
                               shown=shown, dressed_records=records,
                               garments=_assembled_garments(character_name, path.stem),
                               tiers=available_tiers(path), low_tris=low_tris,
                               refit_limit=base_body.BACK_REFIT_DELTA_E,
                               covered_missing_text=base_body.COVERED_MISSING,
                               item_names={i: str((items.get(i) or {}).get("name") or i)
                                           for i in base_body.mesh_items_intended(meta)})
    return steps, dressed_newer(str(meta.get("created_at") or ""), records)


def annotate_model3d_info(character_name: str, info: Dict[str, Any]) -> Dict[str, Any]:
    """``model3d.get_model3d_info`` + ``model.freshness`` and — for an
    outfit model on the base-body pipeline — ``model.steps``. Never raises."""
    model = info.get("model")
    if not isinstance(model, dict):
        return info
    try:
        from app.core.model3d import get_model3d_dir
        name = model.get("filename")
        overview = (outfit_model_overview(character_name, get_model3d_dir(character_name) / name)
                    if isinstance(name, str) and name and Path(name).name == name else None)
        if overview is not None:
            model["steps"] = overview[0]
        model["freshness"] = model3d_freshness(model, views_newer=bool(overview and overview[1]))
    except Exception:  # noqa: BLE001
        logger.exception("Model overview of %s failed", character_name)
    return info


def annotate_model_refs_info(character_name: str, info: Dict[str, Any]) -> Dict[str, Any]:
    """``model_refs.get_model_refs_info`` + a ``freshness`` in every image
    info: the dressed views and drafts on the pipeline against the current
    base, the face view against the profile picture; everything else is
    keyed by the current outfit and current when present. Never raises."""
    try:
        from app.core import base_body
        from app.core.model_refs import find_ref_image
        signature = info.get("signature") or ""
        pipeline = bool(info.get("pipeline"))
        bsig = base_body.base_signature(character_name) if pipeline else ""
        shas = _base_view_shas(character_name, bsig) if bsig else {}

        def mark(tile: Any, view: str) -> None:
            if not isinstance(tile, dict):
                return
            if view == "face":
                tile["freshness"] = (freshness(STALE, PROFILE_CHANGED) if (info.get("face_view") or {}).get("stale")
                                     else freshness(CURRENT))
                return
            if not pipeline:
                tile["freshness"] = freshness(CURRENT)
                return
            path = find_ref_image(character_name, base_body._kind(view), signature) if signature else None
            record = _sidecar(path)
            tile["freshness"] = dressed_freshness(
                record, bsig=bsig, base_view_sha=shas.get(view, ""),
                mesh_ready=bool(base_body.mesh_items_ready(character_name, record, bsig=bsig)))

        mark(info.get("tpose"), "front")
        if isinstance(info.get("pose"), dict):
            info["pose"]["freshness"] = freshness(CURRENT)
        for view, entry in (info.get("views") or {}).items():
            mark((entry or {}).get("info"), view)
        if isinstance(info.get("face_view"), dict):
            mark(info["face_view"], "face")
        front = find_ref_image(character_name, "tpose", signature) if pipeline and signature else None
        front_sha = base_body.file_sha256(front)
        for view, tile in (info.get("drafts") or {}).items():
            if isinstance(tile, dict):
                tile["freshness"] = draft_freshness(_sidecar(base_body.draft_path(character_name, view, signature)),
                                                    bsig=bsig, front_sha=front_sha)
    except Exception:  # noqa: BLE001
        logger.exception("Model refs freshness of %s failed", character_name)
    return info


def annotate_hair(payload: Dict[str, Any]) -> Dict[str, Any]:
    """The Hair tab payload + ``freshness`` on every image (all of them
    belong to the current fsig / hsig / profile picture: current when
    present), ``garment.preview_freshness`` and
    ``other.preview_freshness``. Never raises."""
    try:
        garment = payload.get("garment")
        if isinstance(garment, dict):
            for views in (garment.get("steps") or {}).values():
                if not isinstance(views, dict):
                    continue
                for tile in views.values():
                    if isinstance(tile, dict) and "attempts" in tile:
                        tile["freshness"] = freshness(CURRENT)
                        for attempt in tile.get("attempts") or []:
                            if isinstance(attempt, dict):
                                attempt["freshness"] = freshness(CURRENT)
            garment["preview_freshness"] = hair_preview_freshness(garment)
        hairdeck = payload.get("hairdeck")
        if isinstance(hairdeck, dict):
            for tile in (hairdeck.get("images") or {}).values():
                if isinstance(tile, dict):
                    tile["freshness"] = freshness(CURRENT)
        other = payload.get("other")
        if isinstance(other, dict):
            other["preview_freshness"] = (freshness(CURRENT) if other.get("on_current_base")
                                          else freshness(STALE, FITTED_ON_OLDER_BASE))
    except Exception:  # noqa: BLE001
        logger.exception("Hair freshness failed")
    return payload
