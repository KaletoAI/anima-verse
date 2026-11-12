"""``base_refresh`` — base bodies rendered with older prompt texts, rebuilt at
idle time (spec docs/superpowers/specs/2026-11-11-hair-from-body-design.md
§ Design 5; framework docs/superpowers/specs/2026-11-11-improvements-figure-pipeline-design.md).

A subject is a character on the base-body pipeline with a ready base model
(``subjects.pipeline_characters``) whose stored base carries the
``OLDER_PROMPTS`` note — e.g. the bald base of a character whose hair now
comes from the body mesh. ``base_body.base_refresh_plan`` decides what runs:
every view and the model for the note; and, so a refresh that stopped on
load is finished instead of closed half-done, the views not yet refreshed
(then the model) or the model alone when it was not built from the stored
views. The optional ``character`` param narrows the roster.

The cost before start is ``base_body.base_rebuild_cost`` (first attempts,
summed over the step list the refresh runs). The apply makes the Base body
tab's two calls synchronously under the character's 3D generation guard:
``generate_base_images`` (force, the planned views) and
``generate_base_model`` (force), both with ``raise_load``. The base
signature stays (prompts are not identity): the files are replaced in place,
older bases go by identity as before, and the producers' own after-base
hooks run (``garments.after_base_model``, the artefact collect; outfit
models turn stale by the base model's bytes).

No automatic re-spend: a character whose last base attempt failed (a base
view's failure record, the base model's ``failed`` status) is not a
candidate, and a view or a model run that fails raises ``CandidateRefused``
— terminal, the Base body tab is where a person spends it again. A base
render or model run in progress elsewhere is not a candidate either; met at
apply time it is busy. Load — the generation guard held, an occasion that
resolves to nothing right now, a busy backend, the media switch,
``HubOpBusy`` — is busy, never an attempt.
"""
from typing import Any, Dict, List, Optional, Tuple

from app.core.improvements.base import (Candidate, CandidateBusy, CandidateRefused, ImprovementType,
                                        ParamField)
from app.core.improvements.types import subjects
from app.imagegen.base import BackendBusyError, MediaGenerationDisabled

#: The occasions of the views (front; back/left/right edit the front).
FRONT_OCCASION, VIEW_OCCASION = "base_front", "base_view"
#: The occasions of the base model: img2mesh + rig (a base is humanoid).
MODEL_OCCASIONS = ("mesh_humanoid", "rig_humanoid")


def _profile(name: str) -> Dict[str, Any]:
    from app.models.character import get_character_profile
    return get_character_profile(name) or {}


def _parse(key: str) -> str:
    """``base:<name>`` → ``name``."""
    return key.split(":", 1)[1]


def _blocker(name: str) -> Tuple[str, str]:
    """``("running" | "failed" | "", message)``: a base view render or the
    base model run in progress (``base_body`` status, the 3D generation
    guard), or the last base attempt's failure record (a view's — a hand-gate
    caveat is no failure — or the base model's)."""
    from app.core import base_body, model3d
    status = base_body.base_status(name)
    model = base_body.base_model_info(name) or {}
    if (any(s.get("running") for s in status.values()) or model.get("status") == "running"
            or model3d.generation_running(name)):
        return "running", f"{name}: a base render or 3D generation is running"
    failed = [(v, s.get("error") or "failed") for v, s in status.items() if s.get("failed")]
    if failed:
        return "failed", f"{name}: the last base attempt failed ({failed[0][0]}: {failed[0][1]})"
    if model.get("status") == "failed":
        return "failed", f"{name}: the last base model run failed ({model.get('error') or 'failed'})"
    return "", ""


def _judge(name: str, profile: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """``base_rebuild_cost`` (with its ``plan``) when the character is a
    candidate, else None: nothing running or failed, and a plan."""
    from app.core import base_body
    if _blocker(name)[0]:
        return None
    plan = base_body.base_refresh_plan(name, profile=profile)
    if not plan["views"] and not plan["model"]:
        return None
    return base_body.base_rebuild_cost(name, profile=profile, plan=plan)


def _label(name: str, plan: Dict[str, Any]) -> str:
    from app.core import base_body
    return f"{name} · base body · {base_body.REFRESH_REASON_TEXT.get(plan.get('reason') or '', 'stale')}"


def _require_routes(name: str, plan: Dict[str, Any]) -> None:
    """Every occasion the refresh renders on must resolve right now; nothing
    available is load — the step waits, nothing is spent."""
    occasions: List[str] = []
    views = list(plan.get("views") or ())
    if "front" in views:
        occasions.append(FRONT_OCCASION)
    if any(v != "front" for v in views):
        occasions.append(VIEW_OCCASION)
    if plan.get("model"):
        occasions += list(MODEL_OCCASIONS)
    for occasion in occasions:
        if not subjects.default_mesh_backend(occasion, name):
            raise CandidateBusy(f"no backend available for {occasion} right now")


def _render_views(name: str, views: List[str]) -> None:
    """The planned views, forced: all four in one run when the front is
    among them (the views edit the new front), else each view alone. A view
    that did not land is terminal (its failure record says why)."""
    from app.core import base_body
    try:
        if "front" in views:
            results = base_body.generate_base_images(name, force=True, raise_load=True)
        else:
            results = {}
            for view in views:
                results.update(base_body.generate_base_images(name, view=view, force=True, raise_load=True))
    except (BackendBusyError, MediaGenerationDisabled) as e:
        raise CandidateBusy(f"views — {e}") from e
    except ValueError as e:      # MissingInput / MissingFront / not humanoid
        raise CandidateRefused(f"views — {e}") from e
    missing = [v for v in views if not results.get(v)]
    if missing:
        status = base_body.base_status(name)
        error = next((status[v].get("error") for v in missing if status.get(v, {}).get("error")), None)
        raise CandidateRefused(f"views {', '.join(missing)} — {error or 'render failed'}")


def _build_model(name: str) -> None:
    """The base model, forced, under the character's model lock (as the
    Base body tab's run). Load is busy; any other end is terminal."""
    from app.core import base_body, model3d
    from app.core.hub_ops import HubOpBusy
    try:
        with model3d._char_lock(name):
            result = base_body.generate_base_model(name, force=True, raise_load=True)
    except (BackendBusyError, MediaGenerationDisabled, HubOpBusy) as e:
        raise CandidateBusy(f"model — {e}") from e
    except Exception as e:  # noqa: BLE001 — recorded as the base model's failure
        raise CandidateRefused(f"model — {e}") from e
    if not result.get("ok"):
        raise CandidateRefused(f"model — {result.get('error') or 'refused'}")


class BaseRefresh(ImprovementType):
    id = "base_refresh"
    label = "Rebuild base bodies made with older prompts"
    needs_media = True

    @property
    def params_schema(self) -> List[ParamField]:
        return [ParamField("character", "Character", "enum",
                           [{"value": "", "label": "All characters"}] +
                           [{"value": n, "label": n} for n in subjects.characters()], required=False)]

    def validate(self, params: Dict[str, Any]) -> Dict[str, Any]:
        out = super().validate(params)
        if out.get("character") and out["character"] not in subjects.characters():
            raise ValueError("Character not found")
        return out

    def _names(self, params: Dict[str, Any]) -> List[str]:
        names = subjects.pipeline_characters()
        if params.get("character"):
            names = [n for n in names if n == params["character"]]
        return names

    # --- candidates ------------------------------------------------------------

    def find_candidates(self, params: Dict[str, Any]) -> List[Candidate]:
        out: List[Candidate] = []
        for name in self._names(params):
            cost = _judge(name, _profile(name))
            if cost is None:
                continue
            out.append(Candidate(f"base:{name}", _label(name, cost["plan"]),
                                 hub_jobs=cost.get("hub_jobs"), note=str(cost.get("note") or "")))
        return sorted(out, key=lambda c: (c.label.lower(), c.key))

    def is_done(self, candidate: Candidate, params: Dict[str, Any]) -> bool:
        name = _parse(candidate.key)
        if name not in self._names(params):
            return True
        return _judge(name, _profile(name)) is None

    # --- apply -----------------------------------------------------------------

    def apply(self, candidate: Candidate, params: Dict[str, Any], task_id: str) -> Optional[str]:
        from app.core import base_body, model3d
        name = _parse(candidate.key)
        kind, message = _blocker(name)
        if kind == "running":
            raise CandidateBusy(message)
        if kind == "failed":
            raise CandidateRefused(message)
        if name not in self._names(params):
            return None                     # off the pipeline or gone meanwhile: nothing to spend
        plan = base_body.base_refresh_plan(name, profile=_profile(name))
        if not plan["views"] and not plan["model"]:
            return None                     # refreshed meanwhile (a click): the next scan closes it
        _require_routes(name, plan)
        with model3d._lock:
            if name in model3d._generating:
                raise CandidateBusy(f"{name}: model generation already running")
            model3d._generating.add(name)
        try:
            if plan["views"]:
                _render_views(name, list(plan["views"]))
            _build_model(name)
        finally:
            with model3d._lock:
                model3d._generating.discard(name)
        return None
