"""``outfit_rebuild`` — stale outfit models of characters on the base-body
pipeline, rebuilt on the current base at idle time (spec
docs/superpowers/specs/2026-11-11-improvements-figure-pipeline-design.md § 6.4).

A subject is an outfit model ``model3d/<sig>.glb`` the serving chain calls
stale (``base_body.outfit_info`` status ``stale``: an older base, before the
pipeline, another body detail, another figure than the one delivered now —
a mode changed, a shape or an own mesh built since — or a rebuilt outfit
body). Scope
``worn`` (default) looks at the worn combination of every character,
``saved`` adds the character's saved outfit sets (``subjects.
saved_outfit_signatures``) — only a set that HAS a stored model: this type
rebuilds, it never fills (``fill_missing`` / ``mesh_from_tpose`` do), and it
never walks the combination product.

The cost before start is ``base_body.rebuild_cost`` (first attempts). The
base body itself is never rebuilt here, and a base built with older prompt
wording is not stale for this type (``outfit_info`` judges identity only).

No automatic re-spend: an outfit whose last build failed (``outfit_info``
``failed``, in memory until a restart or a click on "Rebuild from base") is
not a candidate; a build that ends refused raises ``CandidateRefused`` —
terminal. Where the dressed views must be rendered and the character's
``model_ref_auto.tpose`` toggle is off, the outfit is not a candidate (the
outfit change would not render them either). Load — the model guard held, a
build running, an occasion that resolves to nothing right now, a busy
backend, the media switch, ``HubOpBusy`` — is busy, never an attempt.
"""
from typing import Any, Dict, List, Optional, Tuple

from app.core.improvements.base import (Candidate, CandidateBusy, CandidateRefused, ImprovementType,
                                        ParamField)
from app.core.improvements.types import subjects
from app.imagegen.base import BackendBusyError, MediaGenerationDisabled

SCOPE_WORN, SCOPE_SAVED = "worn", "saved"
#: The occasion of the dressed front; the other views add their draft's
#: ``base_body.DRAFT_OCCASIONS`` (the composite onto the base view is CPU work).
FRONT_OCCASION = "outfit_front"
#: The occasions of an outfit body (a meshed shape): img2mesh + rig.
BODY_OCCASIONS = ("mesh_humanoid", "rig_humanoid")


def _profile(name: str) -> Dict[str, Any]:
    from app.models.character import get_character_profile
    return get_character_profile(name) or {}


def _parse(key: str) -> Tuple[str, str]:
    """``outfit:<name>:<sig>`` → ``(name, sig)`` (a signature never holds ":")."""
    name, sig = key.split(":", 1)[1].rsplit(":", 1)
    return name, sig


def _outfits(name: str, scope: str) -> List[Tuple[str, str]]:
    """``(signature, saved label or "")`` of the outfits in ``scope``: the
    worn combination, plus the saved sets under ``saved``."""
    from app.core.model_refs import current_outfit_state
    worn = current_outfit_state(name)[2]
    out = [(worn, "")] if worn else []
    if scope == SCOPE_SAVED:
        out += [(sig, label) for sig, label in subjects.saved_outfit_signatures(name) if sig != worn]
    return out


def _auto_tpose(name: str) -> bool:
    from app.core.model_refs import get_auto_kinds
    return bool(get_auto_kinds(name).get("tpose", True))


def _judge(name: str, sig: str, profile: Dict[str, Any],
           info: Optional[Dict[str, Any]] = None) -> Optional[Tuple[Dict[str, Any], Dict[str, Any]]]:
    """``(outfit_info, rebuild_cost)`` when the outfit is a candidate, else
    None: its model is stale (not failed, running, missing, ready) and —
    when its dressed views must be rendered (or that is unknown) — the
    character's T-pose auto toggle is on."""
    from app.core import base_body
    info = info or base_body.outfit_info(name, signature=sig)
    if info.get("status") != "stale":
        return None
    cost = base_body.rebuild_cost(name, sig, profile=profile, stale_reason=info.get("stale_reason"))
    if cost.get("views_needed") is not False and not _auto_tpose(name):
        return None
    return info, cost


def _label(name: str, sig: str, saved: str, reason: Optional[str]) -> str:
    from app.core import base_body
    from app.core.outfit_bodies import outfit_label
    outfit = saved or outfit_label(name, sig) or sig[:8]
    why = base_body.STALE_REASON_TEXT.get(str(reason or ""), "stale")
    return f"{name} · {outfit} · {why}"


def _require_routes(name: str, cost: Dict[str, Any]) -> None:
    """Every occasion the rebuild renders on must resolve right now; nothing
    available is load — the step waits."""
    from app.core import base_body
    occasions: List[str] = []
    if cost.get("views_needed") or cost.get("body_needed"):
        # The outfit's views, and a shape's own views before it is meshed.
        occasions.append(FRONT_OCCASION)
        for view in base_body.dressed_views():
            draft = base_body.DRAFT_OCCASIONS.get(view)
            if draft and draft not in occasions:
                occasions.append(draft)
    if cost.get("body_needed"):
        occasions += list(BODY_OCCASIONS)
    for occasion in occasions:
        if not subjects.default_mesh_backend(occasion, name):
            raise CandidateBusy(f"no backend available for {occasion} right now")


def _render_views(name: str, sig: str) -> None:
    """The outfit's dressed views, cached views reused (``force=False``): the
    worn combination through its T-pose lane (``trigger_now`` blocking),
    another one the outfit batch's way (``generate_model_ref_images`` with
    the stored model's manifest — ``trigger_now`` renders the worn outfit
    only). Both opt in to ``raise_load``: a busy backend or the media switch
    comes back as the typed exception (``apply`` makes it busy), never as a
    view failure."""
    from app.core import model3d, model_refs
    pieces, items, worn = model_refs.current_outfit_state(name)
    if worn == sig:
        model_refs.trigger_now(name, ("tpose",), force=False, blocking=True, pieces=pieces, items=items,
                               signature=sig, raise_load=True)
        return
    manifest = model3d._stored_manifest(name, sig) or {}
    model_refs.generate_model_ref_images(name, kinds=("tpose",), force=False,
                                         pieces=dict(manifest.get("pieces") or {}),
                                         items=list(manifest.get("items") or []), signature=sig,
                                         raise_load=True)


class OutfitRebuild(ImprovementType):
    id = "outfit_rebuild"
    label = "Rebuild stale outfit models"
    needs_media = True

    @property
    def params_schema(self) -> List[ParamField]:
        return [
            ParamField("scope", "Scope", "enum",
                       [{"value": SCOPE_WORN, "label": "Worn outfits"},
                        {"value": SCOPE_SAVED, "label": "Worn outfits and saved outfit sets"}],
                       required=False, default=SCOPE_WORN),
            ParamField("character", "Character", "enum",
                       [{"value": "", "label": "All characters"}] +
                       [{"value": n, "label": n} for n in subjects.characters()], required=False),
        ]

    def validate(self, params: Dict[str, Any]) -> Dict[str, Any]:
        out = super().validate(params)
        if out.get("character") and out["character"] not in subjects.characters():
            raise ValueError("Character not found")
        out["scope"] = out.get("scope") or SCOPE_WORN
        return out

    def _names(self, params: Dict[str, Any]) -> List[str]:
        names = subjects.pipeline_characters()
        if params.get("character"):
            names = [n for n in names if n == params["character"]]
        return names

    # --- candidates ------------------------------------------------------------

    def find_candidates(self, params: Dict[str, Any]) -> List[Candidate]:
        scope = params.get("scope") or SCOPE_WORN
        out: List[Candidate] = []
        for name in self._names(params):
            profile = _profile(name)
            for sig, saved in _outfits(name, scope):
                judged = _judge(name, sig, profile)
                if judged is None:
                    continue
                info, cost = judged
                out.append(Candidate(f"outfit:{name}:{sig}", _label(name, sig, saved, info.get("stale_reason")),
                                     hub_jobs=cost.get("hub_jobs"), note=str(cost.get("note") or "")))
        return sorted(out, key=lambda c: (c.label.lower(), c.key))

    def is_done(self, candidate: Candidate, params: Dict[str, Any]) -> bool:
        name, sig = _parse(candidate.key)
        if name not in self._names(params):
            return True
        return _judge(name, sig, _profile(name)) is None

    # --- apply -----------------------------------------------------------------

    def apply(self, candidate: Candidate, params: Dict[str, Any], task_id: str) -> None:
        from app.core import base_body, model3d
        name, sig = _parse(candidate.key)
        info = base_body.outfit_info(name, signature=sig)
        if info.get("status") == "running":
            raise CandidateBusy(f"{name}: the outfit model is being built")
        with model3d._lock:
            if name in model3d._generating:
                raise CandidateBusy(f"{name}: model generation already running")
        # Failed, rebuilt or gone meanwhile (a click, the outfit trigger):
        # nothing to spend — the next scan closes the step.
        judged = _judge(name, sig, _profile(name), info)
        if judged is None:
            return
        cost = judged[1]
        _require_routes(name, cost)
        with model3d._lock:
            if name in model3d._generating:
                raise CandidateBusy(f"{name}: model generation already running")
            model3d._generating.add(name)
        try:
            if cost.get("views_needed"):
                try:
                    _render_views(name, sig)
                except (BackendBusyError, MediaGenerationDisabled) as e:
                    raise CandidateBusy(f"views — {e}") from e
                bsig = base_body.base_signature(name)
                missing = [v for v in base_body.dressed_views()
                           if base_body.dressed_image(name, v, sig, bsig) is None]
                if missing:
                    # The views did not land: never mesh or repaint from a
                    # partial set (and never let the build render them again).
                    error = base_body.outfit_info(name, signature=sig).get("error") or "render failed"
                    raise CandidateRefused(f"views {', '.join(missing)} — {error}")
            result = model3d.generate_for_current_outfit(name, force=True, signature=sig)
        except base_body.OutfitError as e:
            raise CandidateRefused(f"build — {e}") from e
        finally:
            with model3d._lock:
                model3d._generating.discard(name)
        if not result.get("ok"):
            raise CandidateRefused(f"build — {result.get('error') or 'refused'}")
