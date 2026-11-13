"""Ruling C2 (plan 2026-11-12-unified-worn-pieces, Task 11g fix round 2):
the dressed back/side views and the garment chain's worn backs that the
MODEL fit made before Task 11g are stale — the old fits came back nude and
were accepted (live test, 2026-11-13: a Build painted a nude back and meshed a
shape from a dressed front and a nude back).

The readers refuse them from now on (``base_body.is_model_fit`` in
``dressed_image`` / ``shape_view_shas`` / ``_view_current``,
``garment_images.stale_model_fit`` / ``_follows_front``); this module
re-makes them ONCE per world, at boot, in a background thread, on the CPU:

* A dressed view (``model_refs/tpose_<back|left|right>_<sig>`` and the
  texture store's ``model_refs/texture/…``) whose sidecar
  ``is_model_fit``: its stored draft (``<dir>/drafts/<the sidecar's
  <view>_draft>``, the content its ``<view>_draft_sha256`` names) — while it
  was made from the view's front as that is now (the draft's
  ``front_sha256``) — is composited onto the base view the sidecar names
  (``base_body._composite_attempt``: the composite's checks + the view's
  gates) and published in place of the fit (``fit: "composite"``; the old
  sidecar's own keys — manifest, ``outfit_body`` — kept). A view copied
  without paint (``dressed`` False: an outfit on a shape with nothing
  painted) is no re-make of its own: it is removed and copied again by the
  next Build (0 jobs). Without a usable draft, with a composite that fails
  its checks, or with a base view gone, the stale file is REMOVED — the view
  is missing, never the old nude fit; the next Build drafts it anew (one hub
  job per view).
* A garment chain's accepted worn back that ``stale_model_fit``:
  ``garment_images.remake_model_fit_back`` — the stored draft of the current
  front composited again (no render) onto the base back the group was made
  on; refused or without a usable draft, the back and the later back steps
  are dropped and the chain renders them on its next run. A materialised
  copy (``copied_from`` its source group) is copied again from the source's
  re-made back, else dropped the same way.

Every character holds its Build lock meanwhile (``figure_build.build_lock``):
a Build never plans on views that change under it. One INFO line per
character with work, one summary line; the world flag ``FLAG`` is set when
every character went through (a crash re-runs it at the next start —
idempotent: a re-made view is no model fit any more). No hub job, ever.
"""
import json
import re
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.log import get_logger

logger = get_logger("model_fit_remake")

#: World flag: the one-time re-make ran to its end.
FLAG = "remade_model_fit_views"
#: The two-step views' file stems: ``tpose_<view>_<sig>``.
_VIEW_RE = re.compile(r"^tpose_(back|left|right)_([A-Za-z0-9]+)$")
#: Sidecar keys of the model fit's own render, not carried into the composite's sidecar.
_FIT_RENDER_KEYS = ("fit_gate", "prompt", "final_prompt", "negative_prompt", "reference_images", "seed",
                    "duration_s", "provider", "service", "model", "loras", "routing", "fallback_from",
                    "overflow_from", "characters", "mood", "expression_key", "activity", "pose_key",
                    "state_fingerprint", "hub_job", "job_id")


def _read(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _remove(image: Path) -> None:
    image.unlink(missing_ok=True)
    image.with_suffix(".json").unlink(missing_ok=True)


def remake_view(character_name: str, image: Path) -> str:
    """Re-make ONE stale dressed view (module docstring): ``"remade"``,
    ``"removed: <why>"`` or ``"current"`` (not a model fit — nothing done)."""
    import tempfile
    from app.core import base_body
    from app.core.model_refs import find_ref_image
    match = _VIEW_RE.match(image.stem)
    record = _read(image.with_suffix(".json"))
    if match is None or not base_body.is_model_fit(record):
        return "current"
    view, sig = match.group(1), match.group(2)
    kind = base_body._kind(view)
    if record.get("dressed") is False:
        _remove(image)
        return "removed: a copy without paint — the next Build copies it again"
    name = str(record.get(f"{view}_draft") or "")
    draft = image.parent / base_body.DRAFT_DIR / name if name else None
    if draft is None or not draft.is_file() or base_body.file_sha256(draft) != record.get(f"{view}_draft_sha256"):
        _remove(image)
        return "removed: its draft is not stored"
    front = base_body._image_at(image.parent / f"tpose_{sig}")
    front_sha = base_body._ref_sidecar(draft).get("front_sha256")
    if front is None or not front_sha or front_sha != base_body.file_sha256(front):
        _remove(image)
        return "removed: its draft follows another front"
    on = str(record.get("base_signature") or "")
    base_views = {v: find_ref_image(character_name, base_body._kind(v), on) for v in base_body.BASE_VIEWS} if on else {}
    if not on or base_views.get(view) is None:
        _remove(image)
        return "removed: its base view is gone"
    texture = {k: record[k] for k in ("texture_signature", "dress_text") if k in record}
    extra = base_body._composite_extra(view, on, base_views[view], draft, record.get("mesh_items") or None, texture)
    with tempfile.TemporaryDirectory(prefix=".composite_", dir=image.parent, ignore_cleanup_errors=True) as staging:
        stem = Path(staging) / image.stem
        staged, result = base_body._composite_attempt(character_name, view, stem=stem, draft=draft,
                                                      base_views=base_views, extra=extra, front=front)
        if not result["composite"].get("ok"):
            from app.core import view_composite
            _remove(image)
            return f"removed: the composite of its draft failed ({view_composite.summary(result['composite'])})"
        # The old sidecar's own keys (the outfit's manifest, the shape's ``outfit_body``) stay.
        meta = _read(staged.with_suffix(".json"))
        for key, value in record.items():
            if key not in _FIT_RENDER_KEYS:
                meta.setdefault(key, value)
        meta["remade_from_model_fit"] = True
        staged.with_suffix(".json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        warning = None if result["ok"] else base_body.fit_gate_warning(1, result, view)
        fit = {"ok": bool(result["ok"]), "chosen": 1, "attempts": [result], "warning": warning,
               "remade_from_model_fit": True}
        base_body._publish_staged(staged, image.parent / f"{kind}_{sig}", fit, key="fit_gate")
    return "remade"


def _view_files(character_name: str) -> List[Path]:
    """Every two-step view file of the character: ``model_refs`` and its texture store."""
    from app.core.model_refs import _IMAGE_EXTS, get_model_refs_dir
    root = get_model_refs_dir(character_name)
    out: List[Path] = []
    for directory in (root, root / "texture"):
        if directory.is_dir():
            out.extend(sorted(p for p in directory.iterdir()
                              if p.is_file() and p.suffix.lower() in _IMAGE_EXTS and _VIEW_RE.match(p.stem)))
    return out


def _views_on_plain_first(paths: List[Path]) -> List[Path]:
    """Views on a plain body first: a view whose base is a shape's view comes after that shape's view."""
    from app.core import base_body

    def on_plain(path: Path) -> int:
        return 0 if base_body.is_base_signature(str(_read(path.with_suffix(".json")).get("base_signature") or "")) else 1
    return sorted(paths, key=lambda p: (on_plain(p), str(p)))


def remake_character(character_name: str) -> Dict[str, Any]:
    """The re-make of one character (module docstring), under its Build lock:
    ``{"views": {file: outcome}, "backs": {file: outcome}}`` of the stale
    ones only."""
    from app.core import figure, figure_build, garment_images
    out: Dict[str, Any] = {"views": {}, "backs": {}}
    with figure_build.build_lock(character_name):
        for path in _views_on_plain_first(_view_files(character_name)):
            try:
                outcome = remake_view(character_name, path)
            except Exception as e:  # noqa: BLE001 — the stale file never stays served
                logger.warning("Model fit %s of %s: re-make failed: %s", path.name, character_name, e)
                _remove(path)
                outcome = f"removed: {e}"
            if outcome != "current":
                out["views"][path.name] = outcome
        out["backs"] = garment_images.remake_model_fit_backs(character_name)
    if out["views"] or out["backs"]:
        figure.invalidate()
        logger.info("Model fits of %s re-made by the composite: %s", character_name,
                    "; ".join(f"{name} {outcome}" for name, outcome in {**out["views"], **out["backs"]}.items()))
    return out


def remake_once() -> Optional[Dict[str, Dict[str, Any]]]:
    """The one-time re-make of every character (dormant and pooled ones
    included). None when it already ran, else ``{character: result}`` of
    the characters with stale views."""
    from app.models.character import list_available_characters
    from app.models.world import get_world_setting, set_world_setting
    if get_world_setting(FLAG, strict=True):
        return None
    names = list_available_characters(include_pooled=True, include_dormant=True, strict=True)
    result: Dict[str, Dict[str, Any]] = {}
    failed = False
    for name in names:
        try:
            done = remake_character(name)
        except Exception as e:  # noqa: BLE001 — the next character still goes; the flag waits
            failed = True
            logger.warning("Model fit re-make of %s failed (retried at the next start): %s", name, e)
            continue
        if done["views"] or done["backs"]:
            result[name] = done
    if not failed:
        set_world_setting(FLAG, "1")
    remade = sum(1 for r in result.values() for o in {**r["views"], **r["backs"]}.values() if o == "remade")
    removed = sum(1 for r in result.values() for o in {**r["views"], **r["backs"]}.values() if o != "remade")
    logger.info("Model fits re-made by the composite: %d re-made, %d removed (drafted anew by the next Build), "
                "%d character(s)%s", remade, removed, len(result),
                f": {', '.join(sorted(result))}" if result else "")
    return result


def start_once() -> None:
    """``remake_once`` in a background thread (boot must not wait: 3..5 s of
    CPU per view)."""
    def run() -> None:
        try:
            remake_once()
        except Exception:  # noqa: BLE001 — retried at the next start
            logger.exception("Model fit re-make failed (retried at the next start)")
    threading.Thread(target=run, daemon=True, name="model-fit-remake").start()
