"""``garment_fill`` — the garment mesh chain for own-mesh outfit pieces that
have none (spec docs/superpowers/specs/2026-11-11-improvements-figure-pipeline-design.md
§ 6.1).

Two kinds of subject (``garment_set.garment_kind_of``): ``clothing`` runs the
edit chain per WEARER (``garments.run_garment``, the fsig carries the base),
``footwear`` runs the shoe chain ONCE per ITEM under the item lock and then
fits every wearer (``garments.run_queued`` per wearer, sorted — the first
runs the item steps, the later ones find them done and fit on the CPU).
Hair is ``hair_fill``'s.

A candidate is never a refused source: a persisted chain failure of the
current fsig (``garments.cached_failure``, which covers
``footwear_source.refused_step``) excludes the piece, and a run that ends
refused raises ``CandidateRefused`` — terminal, the step is never re-spent
by the engine. Load (a chain result ``retry_later``, an occasion that
resolves to nothing right now, a run already queued or in flight) is
``CandidateBusy``.
"""
from typing import Any, Dict, List, Optional, Tuple

from app.core.improvements.base import (Candidate, CandidateBusy, CandidateRefused, ImprovementType,
                                        ParamField)
from app.core.improvements.types import subjects

KIND_ALL, KIND_CLOTHING, KIND_FOOTWEAR = "all", "clothing", "footwear"
SCOPE_WORN, SCOPE_HELD = "worn", "held"
#: The occasions a chain needs to resolve before a step may start (spec § 5.3).
OCCASIONS: Dict[str, Tuple[str, ...]] = {KIND_CLOTHING: ("garment_view", "mesh_garment"),
                                         KIND_FOOTWEAR: ("footwear_empty", "mesh_footwear")}


def _require_routes(kind: str, character: str) -> None:
    """Every occasion the kind's chain renders on must resolve right now;
    nothing available is load, not a defect — the step waits."""
    for occasion in OCCASIONS[kind]:
        if not subjects.default_mesh_backend(occasion, character):
            raise CandidateBusy(f"no backend available for {occasion} right now")


def _profile(name: str) -> Dict[str, Any]:
    from app.models.character import get_character_profile
    return get_character_profile(name) or {}


def _pieces(name: str, profile: Dict[str, Any], scope: str) -> Dict[str, str]:
    """``{item id: kind}`` of the character's own-mesh outfit pieces in
    ``scope``: worn (``garment_set.worn_garments``) or held — the wardrobe
    too (``held_clothing``)."""
    from app.core import garment_set
    from app.models.inventory import get_item
    ids = set(garment_set.worn_garments(name, profile=profile))
    if scope == SCOPE_HELD:
        ids.update(garment_set.held_clothing(name, profile=profile))
    out: Dict[str, str] = {}
    for item_id in sorted(ids):
        kind = garment_set.garment_kind_of(get_item(item_id))
        if kind in (KIND_CLOTHING, KIND_FOOTWEAR):
            out[item_id] = kind
    return out


def _in_flight(name: str, item_id: str) -> bool:
    """A run of the item is queued or running for this character."""
    from app.core import garments
    from app.core import garment_store as gs
    queue = garments.queue_state(name, item_id)
    return bool(queue["queue_running"] == item_id or queue.get("queue_position")
                or gs.status(name, item_id)["running_step"])


def _fit_missing(name: str, profile: Dict[str, Any], item_id: str, kind: str) -> bool:
    """No accepted fit of the current fsig on the current base model."""
    from app.core import base_body, garments
    from app.core import garment_store as gs
    base = base_body.current_base(name, profile=profile)
    if base is None:
        return False
    try:
        fsig = gs.garment_fsig(name, item_id, profile=profile)
    except ValueError:
        return False
    method = gs.kind_method(kind, name, profile, item_id=item_id)
    return garments._fit_state(name, item_id, fsig, base[1], method) != "accepted"


def _wants(name: str, profile: Dict[str, Any], item_id: str, kind: str) -> bool:
    """The candidate rule of one (wearer, piece): the fit is missing, nothing
    is persisted against the piece, no run is queued or in flight."""
    from app.core import garments
    return (_fit_missing(name, profile, item_id, kind)
            and garments.cached_failure(name, item_id, profile=profile) is None
            and not _in_flight(name, item_id))


def _subjects(params: Dict[str, Any]) -> Tuple[List[str], str, str]:
    # The roster is the pipeline characters with a READY base model, a named character too: since Task 11h
    # (Ruling A13) every humanoid is on the pipeline, also one without a base body, whose chain cannot run.
    roster = subjects.pipeline_characters()
    names = [n for n in roster if n == params["character"]] if params.get("character") else roster
    return names, params.get("kind") or KIND_ALL, params.get("scope") or SCOPE_WORN


def _footwear_wearers(item_id: str, names: List[str], scope: str,
                      profiles: Dict[str, Dict[str, Any]]) -> List[str]:
    """The wearers in scope whose fit of the item is missing and who hold no
    failure against it; empty when the item's source is refused."""
    from app.core import footwear_source
    if footwear_source.refused_step(item_id) is not None:
        return []
    out: List[str] = []
    for name in names:
        profile = profiles.setdefault(name, _profile(name))
        if _pieces(name, profile, scope).get(item_id) == KIND_FOOTWEAR and _wants(name, profile, item_id,
                                                                                 KIND_FOOTWEAR):
            out.append(name)
    return sorted(out)


def _judge(result: Dict[str, Any]) -> None:
    """A chain result: load is busy, a refusal terminal, success returns."""
    from app.core.garment_footwear import NO_BASE
    if result.get("ok"):
        if result.get("fit") == NO_BASE:
            raise CandidateRefused("fit — no base model to fit onto")
        return
    if result.get("retry_later"):
        raise CandidateBusy(str(result.get("error") or "the garment backend is busy"))
    raise CandidateRefused(f"{result.get('step') or 'run'} — {result.get('error') or 'refused'}")


class GarmentFill(ImprovementType):
    id = "garment_fill"
    label = "Generate missing garment meshes"
    needs_media = True

    @property
    def params_schema(self) -> List[ParamField]:
        return [
            ParamField("kind", "Kind", "enum",
                       [{"value": KIND_ALL, "label": "Clothing and footwear"},
                        {"value": KIND_CLOTHING, "label": "Clothing"},
                        {"value": KIND_FOOTWEAR, "label": "Footwear"}], required=False, default=KIND_ALL),
            ParamField("scope", "Scope", "enum",
                       [{"value": SCOPE_WORN, "label": "Worn pieces"},
                        {"value": SCOPE_HELD, "label": "Worn and held pieces (the wardrobe)"}],
                       required=False, default=SCOPE_WORN),
            ParamField("character", "Character", "enum",
                       [{"value": "", "label": "All characters"}] +
                       [{"value": n, "label": n} for n in subjects.characters()], required=False),
        ]

    def validate(self, params: Dict[str, Any]) -> Dict[str, Any]:
        out = super().validate(params)
        if out.get("character") and out["character"] not in subjects.characters():
            raise ValueError("Character not found")
        out["kind"] = out.get("kind") or KIND_ALL
        out["scope"] = out.get("scope") or SCOPE_WORN
        return out

    # --- candidates ------------------------------------------------------------

    def _clothing_candidates(self, names: List[str], scope: str,
                             profiles: Dict[str, Dict[str, Any]]) -> List[Candidate]:
        from app.core import garments
        out: List[Candidate] = []
        for name in names:
            profile = profiles.setdefault(name, _profile(name))
            for item_id, kind in _pieces(name, profile, scope).items():
                if kind != KIND_CLOTHING or not _wants(name, profile, item_id, kind):
                    continue
                est = garments.run_estimate(name, item_id, profile=profile)
                out.append(Candidate(f"clothing:{name}:{item_id}", f"{name} · {subjects.item_name(item_id)}",
                                     hub_jobs=est["hub_jobs"], note=est["note"]))
        return out

    def _footwear_candidates(self, names: List[str], scope: str,
                             profiles: Dict[str, Dict[str, Any]]) -> List[Candidate]:
        from app.core import garments
        items: List[str] = []
        for name in names:
            profile = profiles.setdefault(name, _profile(name))
            items += [i for i, k in _pieces(name, profile, scope).items() if k == KIND_FOOTWEAR]
        out: List[Candidate] = []
        for item_id in sorted(set(items)):
            wearers = _footwear_wearers(item_id, names, scope, profiles)
            if not wearers:
                continue
            # One chain per item: the first wearer's run spends the hub jobs,
            # every later wearer finds the item steps done and only fits.
            est = garments.run_estimate(wearers[0], item_id, profile=profiles[wearers[0]])
            n = len(wearers)
            out.append(Candidate(f"footwear:{item_id}",
                                 f"{subjects.item_name(item_id)} · {n} wearer{'' if n == 1 else 's'}",
                                 hub_jobs=est["hub_jobs"], note=f"{', '.join(wearers)} · {est['note']}"))
        return out

    def find_candidates(self, params: Dict[str, Any]) -> List[Candidate]:
        names, kind, scope = _subjects(params)
        profiles: Dict[str, Dict[str, Any]] = {}
        out: List[Candidate] = []
        if kind in (KIND_ALL, KIND_CLOTHING):
            out += self._clothing_candidates(names, scope, profiles)
        if kind in (KIND_ALL, KIND_FOOTWEAR):
            out += self._footwear_candidates(names, scope, profiles)
        return sorted(out, key=lambda c: (c.label.lower(), c.key))

    def is_done(self, candidate: Candidate, params: Dict[str, Any]) -> bool:
        names, _kind, scope = _subjects(params)
        kind, rest = candidate.key.split(":", 1)
        if kind == KIND_CLOTHING:
            name, item_id = rest.split(":", 1)
            return not _wants(name, _profile(name), item_id, KIND_CLOTHING)
        return not _footwear_wearers(rest, names, scope, {})

    # --- apply -----------------------------------------------------------------

    def apply(self, candidate: Candidate, params: Dict[str, Any], task_id: str) -> None:
        from app.core import garments
        kind, rest = candidate.key.split(":", 1)
        if kind == KIND_CLOTHING:
            name, item_id = rest.split(":", 1)
            if _in_flight(name, item_id):
                raise CandidateBusy(f"{name}: a garment run of {subjects.item_name(item_id)} is in flight")
            _require_routes(KIND_CLOTHING, name)
            _judge(garments.run_garment(name, item_id))
            return
        item_id = rest
        names, _k, scope = _subjects(params)
        # Refused meanwhile (a click, another wearer's run): nothing to spend —
        # the next scan closes the step.
        wearers = _footwear_wearers(item_id, names, scope, {})
        if not wearers:
            return
        for name in wearers:
            if _in_flight(name, item_id):
                raise CandidateBusy(f"{name}: a garment run of {subjects.item_name(item_id)} is in flight")
        _require_routes(KIND_FOOTWEAR, wearers[0])
        for name in wearers:
            # ``run_queued`` re-checks ``cached_failure`` at enqueue: a refusal
            # by the first wearer's run stops the rest without a hub call.
            _judge(garments.run_queued(name, [item_id]).get(item_id) or {"ok": False, "error": "no result"})
