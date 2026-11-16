"""The Build — ONE action per character that brings the delivered figure to
the wanted one (plan ``docs/superpowers/plans/2026-11-12-unified-worn-
pieces.md`` Task 7; spec ``docs/superpowers/specs/2026-11-12-unified-worn-
pieces-design.md`` "The flow when Build runs", rulings 1–2).

``plan`` lists exactly the missing steps for what is worn, in the fixed
order ``STEP_ORDER`` (a step with nothing to do is not in it):

1. ``plain_body`` — the plain body is missing or was rendered with older
   prompts (``base_body.base_refresh_plan(missing=True)``): its views, then
   its mesh run (``generate_base_images`` / ``generate_base_model``).
1b. ``base_repair`` — the stored base model's mesh repair is older than its settings or the repair version
   (``model3d.mesh_repair_state`` ``due``; Ruling A34): its local rebuild from the clean prerig source
   (``model3d.rebuild_extension_rig(repair=True)``) — CPU, no hub job, in automatic Builds too. A plain body
   rebuilt in the same Build is repaired by its own run; the step then finds nothing due.
1c. ``tip_smoothing`` — the stored base model's tip smoothing record is missing or of an older version
   (``extension_tip.model_tip_smoothing_due``; Ruling A43): its local extension rebuild
   (``model3d.rebuild_extension_rig``) — CPU, no hub job, in automatic Builds too. A base repaired or rebuilt
   before it in the same Build was smoothed by that run; the step then finds nothing due.
2. (Ruling A119: there is no interim step — a piece that is not ready is left off the figure shown meanwhile.)
3. ``shape`` — the wanted meshed shape is not stored
   (``base_body.prepare_shape``): first every view the shape needs
   (``dressed_views()``) is refreshed — a stale one (a model fit of before
   Task 11g, Ruling C2) counts as missing and is re-made, its stored draft
   composited again when it follows the front (``base_body.
   shape_view_jobs``) — then it is meshed; never from a partial, stale or
   refused set.
4. ``pieces`` — one step per own-mesh piece whose chain has something to
   run (``garments.run_estimate``), run through the character's garment
   FIFO (``garments.run_queued``).
5. ``hair`` — the worn HairDeck hairstyle whose chain has something to run
   (``run_queued``). A humanoid that owns no hairstyle gets its first one
   (``garment_hair.ensure_hairstyle``) when the Build starts.
6. ``texture`` — the wanted painted set: its views, when they are missing
   (the paint itself is Blender on the CPU, done by the assembly). Also
   ("Views: …") when no texture step is planned but a view of
   the figure delivered NOW is not current for it (``dressed_image`` — the
   predicate of the Figure tab's Dressed views; ruling F16).
7. ``fits`` — the CPU refits (``garment_refit.refit_character``, tracked).
8. ``assemble`` — the outfit model of the figure delivered THEN, built from
   whatever is built (Ruling A119: pieces not ready are left off), then the garment assembly
   (``garment_assembly.schedule``).
9. ``collision`` — a stored model's collision record carries channels that no longer match the declarations,
   the per-character overrides or the opening (``collision.channels_due``: the Channels panel's Save stores only,
   ruling R4 of the cross-person collision plan): ``collision.recompute_character(apply_channels=True)`` — CPU,
   no hub job, in automatic Builds too. Listed last, so the models this Build made are applied as well (a fresh
   fit resolves its channels itself; the step then finds nothing due).

A rebuilt plain body re-renders the views every other image is edited from:
with ``plain_body`` in a MANUAL plan every view counts as missing and a stored
shape as not stored.

Ruling 8a: an AUTOMATIC Build never spends base-body hub jobs. The
``plain_body`` step is listed in every plan that needs it, marked ``manual``
("Base body outdated — Build to refresh" / "No base body yet — Build to
create", ``figure.BASE_OUTDATED`` / ``figure.BASE_MISSING``) with its cost, and only a
manual Build (or the ``base_refresh`` improvement) runs it. An automatic plan
builds the rest on the stored plain body (no view counts as missing because
of it); without any plain body it has nothing to build on and plans nothing
else.

Cost (``cost``) reuses the producers' own arithmetic, never a second table:
the plain body = ``base_rebuild_steps``; texture =
``base_body.dressed_view_estimate`` (per missing view, a copy from the
texture store 0 — fix round T12-F1, ruling F13 c) and the whole set
``base_body.dressed_view_jobs()`` on a rebuilt body or shape;
shape = views (when missing) + ``model3d.mesh_hub_stages``; pieces / hair =
``run_estimate``; fits / assemble / collision = 0. ``hub_jobs`` None as soon as one step
is unknown (the note says which). It is an ESTIMATE of first attempts: a
gate's retry (a view-guard re-render, a re-draft after a refused composite) is extra — the
note says so ("N hub jobs (estimate, retries extra)").

The run (``start``): one FIFO per character (a deque + one worker thread). A
``start`` while a run goes keeps ONE follow-up (repeated calls keep one);
every run re-plans at its start, so a follow-up with nothing left ends at
once. Each run, from its plan to its last step, holds the character's
``build_lock``: the Figure tab's Delete of a stored body or texture
(``figure.delete_stored``) takes it too and re-judges deletability under it,
so a Build never plans on a body that is deleted under it (Ruling 10a). Model work (plain body, shape,
texture, assemble) holds ``model3d.generation_slot``. A failed step is
recorded (``failed[step]``; for ``pieces`` the first failing piece, every
failing piece under ``items``) and skips only the steps whose ``DEPENDS``
name it; the others run — except a failed VIEW step (``STOP_STEPS``: plain
body, shape, texture — a refused view, Ruling C4): it STOPS the
Build there, every later step is skipped, and its reason is the Build's
status (``state()['failed']``) in the Figure tab. The run shows as one tracked task "Build · <name>
(<i>/<n> <label>)".

A run pins the figure it planned for (Ruling A18, Task 11g-fix6): the wanted figure of its plan (taken again
after the ``REPIN_STEPS``, which change it themselves). Before every step but ``UNPINNED_STEPS`` the wanted figure of NOW is compared with
it; the shape step pins its shape, a view render the figure it
renders for; and a shape being meshed is asked between its hub stages whether it is still wanted
(``model3d.shape_guard``: no face or rig job for a shape the hair change made obsolete). A step whose figure
moved ends the run as "superseded" (``StepSuperseded``, ``state()['superseded']``) — not a failure, no error
state — and ONE follow-up builds the figure wanted now; before, such a step failed ("Views missing", "the body
shape is not built") and the follow-up started from scratch anyway.

Automatic (Task 8; rulings 7a, 7b): ``request(character, trigger)`` is how the
triggers of today reach the Build — the outfit change (``model_refs``'s
debounce timer), the body change (``garments.after_base_model``), a piece
ready (``base_body.after_mesh_item_ready``), a detail change
(``base_body.after_piece_detail_change``), the auto hook
(``model3d.maybe_auto_generate_for_outfit``). It starts an AUTOMATIC Build
only on the pipeline with "Build automatically" on (``auto_build_on``:
profile ``figure_auto_build``, absent = on, and the world switch
``model_refs._enabled()``); otherwise the change only stays marked
(``figure.pending_changes``). A trigger during a run coalesces into the ONE
follow-up (``start``), never interleaving steps. A mode change of an item
(``inventory.update_item``) calls nothing — its wearers are listed by
``wearers`` and built on request (the Items' "Build for them").

Paused (Ruling A42, ``generation_pause``): while the character's automatic
generation is paused ``request`` starts nothing — the trigger is held
(``generation_pause.hold_build``) and Resume asks again; an automatic run
going when the pause comes finishes the step in flight and stops before the
next one (``state()['paused']``, ``generation_pause.BUILD_PAUSED``), held the
same way; a chain it waits for that becomes held in the garment FIFO stops it
too (``BuildPaused``). A manual Build never consults the pause, and its start
drops a held automatic Build (it builds the same figure).

A garment chain that failed for its current fsig (``garments.cached_failure``)
is listed as "failed — Retry" with 0 counted jobs (``Step.failed``). An
automatic Build never runs it (the failure is reported, nothing spent); a
manual one (``start(…, automatic=False)``: the Build button / Retry, "Build
for them", "Build current outfit") clears that failure and runs the chain
from the failed step (``garments.run_queued(explicit=True)``; the chain
re-judges stored attempts under the current gate versions first).
"""
import logging
import re
import threading
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

STEP_ORDER = ("plain_body", "base_repair", "tip_smoothing", "shape", "pieces", "template", "hair", "texture", "fits",
              "assemble",
              "collision")
#: What a step needs: a failed (or skipped) step skips every step naming it here.
DEPENDS = {"base_repair": {"plain_body"}, "tip_smoothing": {"plain_body"}, "shape": {"plain_body"}, "pieces": {"plain_body"},
           "template": {"plain_body"}, "hair": {"plain_body"}, "texture": {"plain_body", "shape"}, "fits": {"plain_body"},
           "assemble": {"plain_body", "fits"}}
#: Steps that hold the character's 3D generation slot (model work).
SLOT_STEPS = frozenset({"plain_body", "base_repair", "tip_smoothing", "shape", "texture", "assemble",
                        "collision"})
#: Steps whose failure (a refused view, a shape not meshed) STOPS the Build: nothing after them runs (Ruling C4).
STOP_STEPS = frozenset({"plain_body", "shape", "texture"})
#: Steps that do not check the run's pinned figure first (Ruling A18): the plain body (it builds what every
#: figure stands on; the pin is taken again after it), the CPU refits (they fit what is built) and the collision
#: channels (they apply to every stored model, whichever figure is wanted).
UNPINNED_STEPS = frozenset({"plain_body", "base_repair", "tip_smoothing", "fits", "collision"})
#: Steps after which the run pins the wanted figure again: they change it themselves — the plain body (the
#: figure stands on the new body) and the hair (its chain delivers the worn hairstyle's mesh; the hairstyle itself is
#: made before the first pin — ``garment_hair.ensure_hairstyle`` at the start of ``_run``).
REPIN_STEPS = frozenset({"plain_body", "hair"})

#: A step whose figure moved while it ran (Ruling A18): not a failure, no error state — ``state()['superseded']``.
SUPERSEDED = "Superseded: {why} — the follow-up builds {new}"
#: ``SUPERSEDED``'s ``why`` of the run's pinned wanted figure.
WANTED_MOVED = "the wanted figure changed meanwhile ({fields})"
#: ... of the shape step's body shape (the hair or an outfit change wants another shape).
SHAPE_MOVED = "the body shape {shape} is no longer wanted (now {now})"
#: ... of the views of a step (the figure delivered moved while they rendered).
VIEWS_MOVED = "the figure changed while its views rendered ({fields})"
#: The reason of the follow-up a superseded run keeps.
SUPERSEDED_REASON = "superseded"



class BuildPaused(Exception):
    """An automatic Build met the character's pause of automatic generation (Ruling A42): its chain waits held in
    the garment FIFO. The run ends there — neither a failure nor superseded — and is held for the Resume."""


class StepSuperseded(Exception):
    """A step's pinned figure is no longer the one wanted / delivered (Ruling A18): the run ends there — neither
    a failure nor an error state — and ONE follow-up (``_keep_followup_locked``) re-plans and builds the figure
    wanted now."""

#: ``start`` / the route's 409 off the pipeline (a non-humanoid or a temporary NPC — Rulings A13 / A13a).
OFF_PIPELINE = "No figure — the figure is for humanoid characters that are not temporary NPCs"
#: Task-queue row type of a Build.
TRACK_TYPE = "figure_build"


#: The plan label's tail of a chain that failed for its current fsig (ruling 7a).
FAILED_SUFFIX = " — failed — Retry"
#: What replaces it while a manual Build retries that chain (T8 concern 7).
RETRY_SUFFIX = " — retrying"


@dataclass(frozen=True)
class Step:
    name: str            # one of STEP_ORDER
    label: str           # "Plain body: views 4 + mesh + rig", "Own mesh · Tailored Black"
    jobs: Optional[int]  # first-attempt hub jobs, None = unknown
    item_id: str = ""
    #: A garment chain that failed for its current fsig (ruling 7a): the cached
    #: error; an automatic Build skips the step, a manual one retries it.
    failed: str = ""
    #: Base-body work (ruling 8a): why it is listed; only a manual Build runs it.
    manual: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "label": self.label, "jobs": self.jobs, "item_id": self.item_id,
                "failed": self.failed, "manual": self.manual}

    def running_label(self, explicit: bool) -> str:
        """The label while the step runs: a cached chain failure that a manual
        Build retries reads "… — retrying", not "… — failed — Retry"."""
        if explicit and self.failed and self.label.endswith(FAILED_SUFFIX):
            return self.label[:-len(FAILED_SUFFIX)] + RETRY_SUFFIX
        return self.label


# --- Plan ---------------------------------------------------------------------------

def _profile_of(character_name: str, profile: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if profile is not None:
        return profile
    from app.models.character import get_character_profile
    return get_character_profile(character_name) or {}


def _item_name(item_id: str) -> str:
    from app.models import inventory
    return str((inventory.get_item(item_id) or {}).get("name") or item_id)


#: ``state()['failed']`` key of a Build that could not read the character's profile (ruling F13 e).
PROFILE_FAILED = "profile"
#: Its error text.
PROFILE_UNREADABLE = "The character's profile could not be read — nothing was judged or built: {error}"


def _read_profile(character_name: str) -> Dict[str, Any]:
    """The profile a Build judges, read STRICTLY (``get_character_profile(strict=True)``): a DB or decoding
    error raises instead of becoming the empty profile — which reads as "off the pipeline" and ended a Build
    as "nothing to build" (T12 incident; ruling F13 e)."""
    from app.models.character import get_character_profile
    return get_character_profile(character_name, strict=True)


def _record_unread(character_name: str, reason: str, error: BaseException) -> Dict[str, Any]:
    """A Build (or its start) that could not read the profile: a warning and the failure state
    (``state()['failed'][PROFILE_FAILED]``) — never "nothing to build". Returns the ``start`` answer."""
    from app.core.timeutils import utc_now_iso
    message = PROFILE_UNREADABLE.format(error=str(error) or type(error).__name__)
    logger.warning("Build %s (%s) failed: %s", character_name, reason, message)
    with _lock:
        _last[character_name] = {"failed": {PROFILE_FAILED: {"error": message, "item_id": ""}}, "skipped": [],
                                 "reason": reason, "finished_at": utc_now_iso()}
    return {"status": "failed", "reason": message}


def on_pipeline(character_name: str, *, profile: Optional[Dict[str, Any]] = None) -> bool:
    """Whether the character builds a figure at all (``base_body.is_base_pipeline``)."""
    from app.core import base_body
    return base_body.is_base_pipeline(character_name, profile=_profile_of(character_name, profile))


def _model_figure(character_name: str, signature: str):
    """The figure the stored outfit model of ``signature`` was built as
    (``figure.built_figure``), None without a current model or a record."""
    from app.core import figure, model3d
    path = model3d.find_model3d(character_name, signature)
    return figure.built_figure(model3d._read_sidecar(path)) if path is not None else None


def _views_missing(character_name: str, fig, signature: str) -> bool:
    """Whether a ``dressed_views()`` view of ``fig`` is not stored for ``signature``."""
    from app.core import base_body
    return any(base_body.dressed_image(character_name, v, signature, fig.bsig, fig=fig) is None
               for v in base_body.dressed_views())


def _views_label(what: str, views: int, copied: bool = False) -> str:
    if views:
        return f"{what}: views {views}"
    return f"{what}: views copied from the texture store" if copied else f"{what}: paint on the CPU"


#: The plan label's tail when the outfit's full-body reference is generated first (Ruling A104).
AUTO_REFERENCE_LABEL = " + full-body reference 1 (generated automatically before the front)"


def _with_reference(character_name: str, step: Step, fig, signature: str, profile: Dict[str, Any],
                    front: Optional[bool]) -> Step:
    """``step`` (one that renders the dressed views of ``fig``) with the outfit's full-body reference that
    ``base_body.generate_dressed_images`` generates before the front (Ruling A104, ``full_body_reference.auto_jobs``)
    counted in — only while the step renders the front (``front``: the whole set, or the front not stored)."""
    from app.core import base_body, full_body_reference
    if not step.jobs:
        return step
    if front is None:
        front = base_body.dressed_image(character_name, "front", signature, fig.bsig, fig=fig) is None
    extra = full_body_reference.auto_jobs(character_name, fig, profile=profile) if front else 0
    if not extra:
        return step
    return Step(step.name, step.label + AUTO_REFERENCE_LABEL, step.jobs + extra, step.item_id, failed=step.failed,
                manual=step.manual)


#: The ``fits`` step of a manual Build that re-fits the pieces whose fit on the body shape was refused (Ruling A23 b).
REFIT_LABEL = "Re-fit on the body shape (refused before): {names}"
#: ``_run_fits``' error when a re-fit is refused again (Ruling A23 b): the piece stays left off (Ruling A119).
REFIT_REFUSED = "Fit refused — {items}; left off the figure"
#: The plain body step's label when its rebuild is what the hair wanted in the body costs (ruling F13 a).
HAIR_REBUILD_LABEL = "Hair · in the body → plain body rebuild ({parts})"
#: ``cost`` note: the total is an estimate of first attempts (ruling F13 c).
COST_NOTE = "{total} hub jobs (estimate, retries extra)"


def _chain_step(character_name: str, name: str, item_id: str, label: str,
                profile: Dict[str, Any]) -> Optional[Step]:
    """A garment chain step (``pieces`` / ``hair``) when its chain has something to run or
    its cost is unknown (``run_estimate``); a chain that failed for its current fsig
    (``garments.cached_failure``) as "failed — Retry" (ruling 7a) with what its retry
    spends — a manual Build runs it (Ruling A25; an automatic one skips it)."""
    from app.core import garments
    failure = garments.cached_failure(character_name, item_id, profile=profile)
    if failure is not None and (failure.get(garments.REFIT_OFFER) or {}).get("kept"):
        # Ruling A162: the user kept the old fit after a refused refit — nothing to run for the piece.
        return None
    estimate = garments.run_estimate(character_name, item_id, profile=profile)
    if failure is not None:
        error = str(failure.get("error") or "chain failed")
        if failure.get("step"):
            error = f"{failure['step']} — {error}"
        jobs = estimate.get("hub_jobs")
        return Step(name, f"{label}{FAILED_SUFFIX}", int(jobs) if jobs is not None else None, item_id,
                    failed=error)
    if estimate.get("hub_jobs") is None:
        return Step(name, f"{label} ({estimate.get('note') or 'cost unknown'})", None, item_id)
    if not estimate.get("steps"):
        return None
    return Step(name, label, int(estimate["hub_jobs"]), item_id)


def _hair_step(character_name: str, profile: Dict[str, Any]) -> Optional[Step]:
    """The hair chain (HairDeck or HAAR) of the worn hairstyle (``garment_hair.worn_hairstyle``); None without
    one."""
    from app.core import garment_hair
    item = garment_hair.worn_hairstyle(character_name, profile)
    if not item or not item.get("id"):
        return None
    method = "HAAR" if garment_hair.hairstyle_mode(item) == garment_hair.HAAR_MODE else "HairDeck"
    label = f"Hair · {item.get('name') or 'Hairstyle'} ({method})"
    return _chain_step(character_name, "hair", str(item["id"]), label, profile)


#: The label of a template drape step (Ruling A138) and its CPU estimate (measured A142: 40–50 s wall on Kira with the pose shapes).
TEMPLATE_LABEL = "Template drape · {name} (CPU ~45 s, 0 hub jobs)"


def _template_step(character_name: str, item_id: str, delivered, profile: Dict[str, Any]) -> Optional[Step]:
    """The drape of a worn template piece (``garment_template.drape_state``): None when it is ready or cannot be
    draped (no parameters, a kind not built — the Figure tab says why, nothing to build); "failed — Retry" for a
    failed drape of the current key (a manual Build retries it, ruling 7a)."""
    from app.core import base_body, garment_template
    from app.core.figure import worn_sets
    base = base_body.current_base(character_name, profile=profile)
    sets = worn_sets(character_name, pieces=dict(delivered.pieces), profile=profile)
    state = garment_template.drape_state(character_name, item_id, base_sha=base[1] if base else "",
                                         lower=garment_template.lower_layers(sets.own, item_id))
    label = TEMPLATE_LABEL.format(name=_item_name(item_id))
    if state["state"] == "missing":
        return Step("template", label, 0, item_id)
    if state["state"] == "failed":
        return Step("template", label + FAILED_SUFFIX, 0, item_id,
                    failed=str(state["record"].get("error") or state["reason"]))
    return None


def _runnable(steps: List[Step], explicit: bool) -> List[Step]:
    """The steps that do work: a cached chain failure (ruling 7a) and the
    plain body (ruling 8a) only in a manual Build."""
    return [s for s in steps if explicit or not (s.failed or s.manual)]


#: The steps that render views (Ruling FR-I3: a refused view makes them a cached failure).
VIEW_STEPS = frozenset({"shape", "texture"})
#: ``Step.failed`` of a view step whose view was refused for its inputs (Ruling FR-I3).
VIEW_REFUSED = "View refused — {views}"


def _refused(step: Step, refusals: Dict[str, str]) -> Step:
    """``step`` as a cached failure (Ruling FR-I3) when a view it renders was refused for its inputs: listed
    "failed — Retry" with what its retry spends (the estimates count a refused view as one draft); an automatic
    Build skips it, a manual one clears the records and retries once."""
    if not refusals:
        return step
    reason = VIEW_REFUSED.format(views="; ".join(f"{v}: {r}" for v, r in sorted(refusals.items())))
    return Step(step.name, f"{step.label}{FAILED_SUFFIX}", step.jobs, step.item_id, failed=reason,
                manual=step.manual)


def _retry_refused_views(character_name: str, step: Optional[Step], explicit: bool, *signatures: str) -> None:
    """A manual Build retries a view step that was a cached refusal once (Ruling FR-I3): its records go."""
    if not explicit or step is None or not step.failed:
        return
    from app.core import base_body
    for signature in signatures:
        if signature:
            base_body.clear_view_refusals(character_name, signature)
    logger.info("Build %s: retrying the refused views of %s", character_name, ", ".join(s for s in signatures if s))


def plan(character_name: str, *, profile: Optional[Dict[str, Any]] = None,
         explicit: bool = True, resolved: Optional[Tuple[Any, Any]] = None) -> List[Step]:
    """The steps a Build runs now, in ``STEP_ORDER`` (module docstring).
    ``[]`` off the pipeline or when the delivered figure is the wanted one and
    built. ``explicit`` (default — what the Build button runs, the plan the UI
    shows): a manual Build; False: an automatic one. A chain that failed for
    its fsig is listed with ``failed`` and 0 jobs; it makes the fits and the
    assembly follow only when ``explicit`` (a manual Build retries it). The
    plain body is listed with ``manual`` in both; only an explicit plan builds
    on its refresh (ruling 8a). ``resolved``: the ``figure._delivered``
    pair of ``profile`` when the caller holds it. Read-only."""
    from app.core import base_body, figure, garment_refit, model3d
    profile = _profile_of(character_name, profile)
    if not base_body.is_base_pipeline(character_name, profile=profile):
        return []
    wanted, delivered = resolved or figure._delivered(character_name, profile=profile)
    signature, bsig = wanted.signature, wanted.bsig
    steps: List[Step] = []

    refresh = base_body.base_refresh_plan(character_name, profile=profile, missing=True)
    stale = bool(refresh.get("views") or refresh.get("model"))
    if stale:
        rebuild = base_body.base_rebuild_steps(character_name, refresh)
        views = sum(jobs for step, jobs in rebuild if step.startswith("view "))
        parts = ([f"views {views}"] if views else []) + [step for step, _jobs in rebuild
                                                         if not step.startswith("view ")]
        no_base = refresh.get("reason") == "missing"   # no stored front or no base model
        label = ("Plain body: " + " + ".join(parts) if no_base or not figure.hair_needs_rebuild(
            character_name, wanted, profile=profile) else HAIR_REBUILD_LABEL.format(parts=" + ".join(parts)))
        if refresh.get("reason") == "mesh_mismatch":   # Ruling A61
            label = MESH_MISMATCH_LABEL.format(body="Plain body", parts=" + ".join(parts))
        steps.append(Step("plain_body", label,
                          sum(jobs for _step, jobs in rebuild),
                          manual=figure.BASE_MISSING if no_base else figure.BASE_OUTDATED))
        if no_base and not explicit:
            return steps  # ruling 8a: nothing to build on until a manual Build makes it
    # Ruling 8a: only a manual Build refreshes the plain body; an automatic one builds on the stored one.
    rebased = stale and explicit
    if not rebased and _mesh_repair_due(character_name, bsig):
        steps.append(Step("base_repair", MESH_REPAIR_LABEL, 0))
    if not rebased and _tip_smoothing_due(character_name, bsig):
        steps.append(Step("tip_smoothing", TIP_SMOOTHING_LABEL, 0))

    built = _model_figure(character_name, signature)
    set_jobs = base_body.dressed_view_jobs()
    take_out = ""
    meshed = not figure.is_plain(wanted.shape)
    shape_stored = meshed and not rebased and figure._shape_stored(character_name, wanted.shape, bsig)
    if shape_stored and base_body.mesh_view_mismatch(character_name, wanted.shape) is not None:
        # Ruling A61: the stored shape's mesh does not match its own views — a manual Build meshes it again
        # (``_run_shape``: ``prepare_shape(rebuild=True)``), an automatic one never spends on it.
        stages = model3d.mesh_hub_stages(character_name, wanted.shape)
        steps.append(Step("shape", MESH_MISMATCH_LABEL.format(body="Body shape", parts=" + ".join(stages)),
                          len(stages), manual=MESH_MISMATCH_MANUAL))
    if meshed and (rebased or not shape_stored):
        # Ruling C4: every view the shape needs is refreshed before it is meshed (a stale one re-made).
        views = set_jobs if rebased else base_body.shape_view_jobs(character_name, wanted.shape, bsig)
        stages = model3d.mesh_hub_stages(character_name, wanted.shape)
        step = Step("shape", "Body shape: " + " + ".join(([f"views {views}"] if views else []) + stages),
                    views + len(stages), manual=take_out)
        steps.append(step if rebased else _refused(step, base_body.shape_view_refusals(character_name,
                                                                                         wanted.shape, bsig)))

    for item_id in wanted.template:
        # Ruling A138: a template piece is draped on the CPU (0 hub jobs) when its drape of the current key is missing.
        step = _template_step(character_name, item_id, delivered, profile)
        if step is not None:
            steps.append(step)
    for item_id in wanted.own:
        if item_id in wanted.template:
            continue
        # The worn state's chain only (plan Task 11b: the other state is built by its own button, never both
        # automatically); a piece worn open says so — its open mesh is another chain.
        label = f"Own mesh · {_item_name(item_id)}" + (" (open)" if item_id in wanted.open else "")
        step = _chain_step(character_name, "pieces", item_id, label, profile)
        if step is not None:
            steps.append(step)

    if wanted.hair == figure.HAIR_HAIRDECK:
        step = _hair_step(character_name, profile)
        if step is not None:
            steps.append(step)

    # Ruling A61: the assembly of the figure delivered now was refused for exactly these inputs — an automatic Build
    # does not run it again (nor the CPU work that only feeds it); a manual one retries it once.
    held = None if rebased else _assemble_held(character_name, signature, delivered)
    if wanted.texture:
        # A shape meshed again from its stored views (Ruling A61) keeps them: its dressed views stay current.
        shape_built = not any(s.name == "shape" and s.manual != MESH_MISMATCH_MANUAL for s in steps)
        views_missing = rebased or not shape_built or _views_missing(character_name, wanted, signature)
        if held is not None and not explicit and not views_missing:
            pass   # nothing to render; the paint itself is the held assembly
        elif views_missing or built is None or built.texture != wanted.texture or built.shape != wanted.shape:
            views = (set_jobs if rebased or not shape_built
                     else base_body.dressed_view_estimate(character_name, wanted, signature, profile=profile)
                     if views_missing else 0)
            step = _with_reference(character_name, Step("texture", _views_label("Texture", views,
                                                                                 copied=views_missing),
                                                         views, manual=take_out),
                                   wanted, signature, profile, True if rebased or not shape_built else None)
            steps.append(step if rebased or not shape_built
                         else _refused(step, base_body.dressed_view_refusals(character_name, wanted, signature)))
    # Ruling A23 b: a refused fit on the shape is a cached failure — the piece is left off (Ruling A119); a manual
    # Build re-fits it once.
    refused = dict(delivered.fit_refused)
    # Ruling FR-I3: a view refused for its inputs is a cached failure too — an automatic Build plans nothing
    # that needs it (no other views, fits or assembly); a manual one retries it once.
    view_hold = not explicit and any(s.failed and s.name in VIEW_STEPS for s in steps)
    hold = (view_hold or held is not None) and not explicit
    if (not view_hold
            and not any(s.name == "texture" for s in _runnable(steps, explicit))
            and _views_missing(character_name, delivered, signature)):
        # Ruling F16: the views of the figure delivered NOW, judged like the Dressed views (``dressed_image``) — a
        # view made for another figure is never "nothing to build" while the sub-tab calls it stale.
        views = base_body.dressed_view_estimate(character_name, delivered, signature, profile=profile)
        label = (_views_label("Views", views, copied=True) if views or delivered.texture
                 else "Views: copied from the body's views")
        step = _refused(_with_reference(character_name, Step("texture", label, views), delivered, signature,
                                        profile, None),
                        base_body.dressed_view_refusals(character_name, delivered, signature))
        steps.append(step)
        hold = hold or (not explicit and bool(step.failed))

    grafted = bool(wanted.own) or wanted.hair == figure.HAIR_HAIRDECK
    work = _runnable(steps, explicit)
    if refused and explicit:
        steps.append(Step("fits", REFIT_LABEL.format(names=", ".join(_item_name(i) for i in sorted(refused))), 0))
    elif grafted and not hold and (any(s.name in ("plain_body", "base_repair", "tip_smoothing", "shape", "pieces", "hair")
                                       for s in work)
                                   or garment_refit.work_count(character_name, profile=profile) > 0):
        steps.append(Step("fits", "Fits on the CPU", 0))

    if held is not None and not view_hold:
        # Listed "failed — Retry" (Ruling A61): ``_runnable`` drops it from an automatic Build.
        steps.append(Step("assemble", ASSEMBLE_LABEL + FAILED_SUFFIX, 0, failed=held["error"]))
    elif not hold and (_runnable(steps, explicit) or built is None or built.as_dict() != delivered.as_dict()):
        steps.append(Step("assemble", ASSEMBLE_LABEL, 0))
    # Last, and after the assembly's own test: a channel step alone never makes the figure assemble.
    if _collision_due(character_name):
        steps.append(Step("collision", COLLISION_LABEL, 0))
    return steps


#: The assembly step's label: the outfit model of the figure delivered now (the paint), then the garment assembly.
ASSEMBLE_LABEL = "Assemble the figure"
#: A body (the plain body or a meshed shape) whose mesh the paint step refused against its own views (Ruling A61).
MESH_MISMATCH_LABEL = "{body}: new mesh — the stored one does not match its views ({parts})"
#: ``Step.manual`` of a body shape meshed again for that reason (Ruling A61; ruling 8a: never automatically).
MESH_MISMATCH_MANUAL = "The body shape's mesh does not match its views — Build to mesh it again"


def _assemble_held(character_name: str, signature: str, delivered) -> Optional[Dict[str, str]]:
    """The recorded refusal of the assembly of ``signature`` as ``delivered`` while its inputs are the same
    (``base_body.assemble_refusal``, Ruling A61), else None. Never raises (a plan never fails on it)."""
    from app.core import base_body
    try:
        return base_body.assemble_refusal(character_name, signature, delivered)
    except Exception:  # noqa: BLE001
        logger.debug("Build %s: assembly refusal not read", character_name, exc_info=True)
        return None


def cost(character_name: str, steps: Optional[List[Step]] = None) -> Dict[str, Any]:
    """``{hub_jobs, steps: [Step.as_dict()], note}`` of ``steps`` (default:
    ``plan``) on their first attempts; ``hub_jobs`` None when a step's cost
    is unknown — the note names those steps. Never raises."""
    try:
        steps = plan(character_name) if steps is None else steps
    except Exception as e:  # noqa: BLE001 — an estimate, never a failure
        logger.warning("Build cost of %s not computable: %s", character_name, e)
        return {"hub_jobs": None, "steps": [], "note": f"cost unknown — {e}"}
    unknown = [s.label for s in steps if s.jobs is None]
    total = None if unknown else sum(int(s.jobs or 0) for s in steps)
    if unknown:
        note = "cost unknown — " + "; ".join(unknown)
    elif steps:
        note = COST_NOTE.format(total=total)
    else:
        note = "nothing to build"
    return {"hub_jobs": total, "steps": [s.as_dict() for s in steps], "note": note}


# --- Run ----------------------------------------------------------------------------

_lock = threading.Lock()
_queues: Dict[str, Deque[Tuple[str, bool]]] = {}  # character -> follow-up (reason, automatic), at most one
_refit_items: Dict[str, str] = {}         # character -> the piece of its queued Re-fit run (Ruling FR-I2)
_active: set = set()                      # characters whose worker thread is alive
_current: Dict[str, Dict[str, Any]] = {}  # character -> the run in flight
_last: Dict[str, Dict[str, Any]] = {}     # character -> the last run that had steps
_build_locks: Dict[str, threading.Lock] = {}  # character -> held by a run from its plan to its last step
_pins: Dict[str, Any] = {}                # character -> the wanted figure the run in flight was planned for (A18)
_own_chains: Dict[str, set] = {}          # character -> items whose chain the Build runs now (Ruling A25)


def runs_chain(character_name: str, item_id: str) -> bool:
    """Whether the character's Build runs ``item_id``'s chain itself now (Ruling A25): its finished fit queues
    no "piece_ready" follow-up — the Build's own fits and assembly come next."""
    with _lock:
        return item_id in _own_chains.get(character_name, ())


#: The Build steps that run ONE piece's own chain (its fit included).
PIECE_CHAIN_STEPS = ("pieces", "hair", "template")


def fits_piece(character_name: str, item_id: str) -> bool:
    """A166: whether the character's running Build still fits ``item_id`` — its chain runs now (``runs_chain``) or
    a step of the piece's chain comes later in the run's plan. A Build planned before the piece became due does not
    (Glut's briefs, 2026-11-17: the dialog waited for a Build that never fitted them). False when no Build runs."""
    with _lock:
        if character_name not in _active:
            return False
        if item_id in _own_chains.get(character_name, ()):
            return True
        current = _current.get(character_name) or {}
        steps = list(current.get("steps") or [])
        index = int((current.get("step") or {}).get("index") or 1)
    return any(s.get("item_id") == item_id and s.get("name") in PIECE_CHAIN_STEPS for s in steps[index - 1:])


#: 409 of a manual render of the dressed views while a Build of the character runs (ruling F16, fix round
#: T12-F1 — like Delete's ``figure.BUILD_RUNNING``, ruling 10a): the Build renders the views its figure needs;
#: a manual run beside it would render the same views twice (since ruling A14 no dressed render waits for the
#: garment chains any more).
VIEWS_BUILD_RUNNING = ("Not rendered: a Build runs for this character now and renders the views its figure "
                       "needs — regenerate after the Build if needed.")


#: 409 of the base body's own actions (a view's render, "Run skin step", the base model) while a Build of the
#: character runs (Ruling A20): the Build plans and builds on the base body as it found it — a base edit beside
#: it made its views and meshes stale while they were built (live test, 2026-11-13: a new front 34 s after the Build
#: started).
BASE_BUILD_RUNNING = ("Not started: a Build runs for this character now and builds on the base body as it is — "
                      "change the base body after the Build")


def running(character_name: str) -> bool:
    """Whether a Build of the character runs now (its worker is alive: a run or its kept follow-up)."""
    with _lock:
        return character_name in _active


#: Ruling A26 a (symmetrical to A20's ``BASE_BUILD_RUNNING``): a Build does not start while a base-body step of
#: the character is queued or running — it would build on a base that is being replaced (live test, 2026-11-13: the
#: skin step rewrote the base front 60 s into a Build, the dressed front was edited from the old one). ``step``
#: is ``base_step_in_flight``'s name of it.
BASE_STEP_RUNNING = "{step} is running — Build once it is done"
#: Ruling A26 b: the base views changed under a running Build (a step that slipped in beside it) — it stops at
#: the next step instead of failing with "views missing". ``step`` is the step it stopped at.
BASE_CHANGED = "Base body changed during the Build ({step}) — Build again"
#: How often a deferred automatic Build looks whether the base step ended, and how long it waits at most
#: (Ruling A26 a / A22: a deferral, never a failure).
DEFERRED_POLL_S = 5.0
DEFERRED_WAIT_S = 3600.0
_deferred: Dict[str, str] = {}   # character -> the reason of the automatic Build waiting for a base step


def base_step_in_flight(character_name: str) -> str:
    """The base-body step of the character queued or running now, by name, "" when none (Ruling A26 a) — read
    from the registries the steps keep anyway, never a second one: the Base body tab's Run all
    (``_run_all_active``), the base views' reservations and the base model run
    (``base_body.base_steps_running``: a view's render, the skin step, Run all's views, the base model — each
    from its click on), the character's 3D generation guard when a base step holds it
    (``model3d.generation_holder``: re-rig, face retexture / cleanup, a fetched or resumed mesh job, the base
    refresh / face Improvements) and an extension tip rebuild."""
    with _lock:
        if character_name in _run_all_active:
            return "Base body Run all"
    from app.core import base_body, extension_tip, model3d
    steps = base_body.base_steps_running(character_name)
    if steps:
        return steps[0]
    holder = model3d.generation_holder(character_name)
    if holder:
        return holder
    if extension_tip.rebuild_running(character_name):
        return "Extension tip rebuild"
    return ""


#: The Build's steps that work on the plain (base) body itself (Ruling A55): only these count as base work in the
#: Base body tab. Every other step builds the outfit on top of the base body and leaves it as it is.
BASE_BUILD_STEPS = frozenset({"plain_body", "base_repair", "tip_smoothing"})
#: The Base body tab's neutral line while only work on top of the base body runs (Ruling A55).
OUTFIT_BUILDING = "An outfit model is building — the base body is not affected"


def base_activity(character_name: str) -> Dict[str, str]:
    """What of the character's 3D work runs now, split by whether it touches the base body (Ruling A55 — the Base
    body tab's status follows only its own steps): ``base`` names the base-body work in flight — a Build at one of
    ``BASE_BUILD_STEPS`` (that step's label) or ``base_step_in_flight`` (Run all, a view, the base model, a named
    holder of the generation guard, a tip rebuild) — "" when none; ``other`` is ``OUTFIT_BUILDING`` while, with no
    base work, an outfit model or garment is built (a Build at any other step, the outfit model's own run, an
    unnamed holder of the generation guard), else "". A Build that has not reached its first step yet is neither.
    Read-only, never raises."""
    out = {"base": "", "other": ""}
    try:
        with _lock:
            step = dict((_current.get(character_name) or {}).get("step") or {}) if character_name in _active else {}
        name = str(step.get("name") or "")
        if name in BASE_BUILD_STEPS:
            out["base"] = str(step.get("label") or name)
            return out
        out["base"] = base_step_in_flight(character_name)
        if out["base"]:
            return out
        from app.core import base_body, model3d
        if name or base_body.outfit_running(character_name) or model3d.generation_running(character_name):
            out["other"] = OUTFIT_BUILDING
    except Exception:  # noqa: BLE001 — a label, never a failure of the poll
        logger.debug("Base activity of %s not read", character_name, exc_info=True)
    return out


def _defer(character_name: str, reason: str, step: str) -> Dict[str, Any]:
    """An automatic start while a base step is in flight (Ruling A26 a): a deferral, not a failure (A22) — ONE
    waiter per character starts the automatic Build once no base step is in flight any more (it re-plans then;
    nothing to build ends at once). ``{"status": "deferred", "reason"}``."""
    message = BASE_STEP_RUNNING.format(step=step)
    with _lock:
        waiting = character_name in _deferred
        _deferred[character_name] = reason
    logger.info("Build %s (%s, automatic) deferred: %s", character_name, reason, message)
    if not waiting:
        try:
            threading.Thread(target=_deferred_waiter, args=(character_name,), daemon=True,
                             name=f"figure-build-deferred-{character_name}").start()
        except Exception:  # noqa: BLE001 — without a waiter the change stays pending (figure.pending_changes)
            with _lock:
                _deferred.pop(character_name, None)
            logger.warning("Build %s: deferral waiter not started", character_name, exc_info=True)
    return {"status": "deferred", "reason": message}


def _deferred_waiter(character_name: str, *, poll_s: Optional[float] = None,
                     timeout_s: Optional[float] = None) -> None:
    import time
    poll_s = DEFERRED_POLL_S if poll_s is None else poll_s
    deadline = time.monotonic() + (DEFERRED_WAIT_S if timeout_s is None else timeout_s)
    try:
        while base_step_in_flight(character_name):
            if time.monotonic() >= deadline:
                logger.info("Build %s: a base step still runs after %.0f s — the deferred automatic Build is "
                            "dropped (the change stays pending)", character_name, DEFERRED_WAIT_S)
                return
            time.sleep(poll_s)
    finally:
        with _lock:
            reason = _deferred.pop(character_name, None)
    if reason is not None and time.monotonic() < deadline:
        logger.info("Build %s: the base step is done — the deferred automatic Build (%s) starts", character_name,
                    reason)
        request(character_name, reason)


def build_lock(character_name: str) -> threading.Lock:
    """The character's Build lock: a run holds it from its plan to its last
    step (``_worker``); ``figure.delete_stored`` takes it without waiting and
    refuses while a Build holds it (Ruling 10a)."""
    with _lock:
        return _build_locks.setdefault(character_name, threading.Lock())


def _keep_followup_locked(character_name: str, reason: str, automatic: bool) -> None:
    """Keep ONE follow-up (caller holds ``_lock``): a manual request replaces an
    automatic one (it may retry cached failures), never the other way round."""
    queue = _queues.setdefault(character_name, deque())
    if not queue:
        queue.append((reason, automatic))
    elif queue[0][1] and not automatic:
        queue[0] = (reason, automatic)


def start(character_name: str, *, reason: str, automatic: bool = False) -> Dict[str, Any]:
    """Start a Build of the character: ``{"status": "started"}`` (the worker
    took it), ``"queued"`` (a run goes — ONE follow-up is kept, repeated calls
    keep one; it re-plans when it starts), ``"current"`` (nothing to build —
    for an ``automatic`` Build also when only cached chain failures are left,
    which only a manual Build retries), ``"off"`` (off the pipeline, with
    ``reason``), ``"failed"`` (the profile could not be read: ``reason``,
    recorded as the Build's failure — ruling F13 e), ``"base_busy"`` (a click
    while a base-body step of the character is queued or running — Ruling
    A26 a; ``reason`` names it, the routes answer 409) / ``"deferred"`` (the
    same for an automatic start: it starts once the step is done — a
    deferral, never a failure). ``automatic``: started
    by a trigger (``request``), not by a click (ruling 7a)."""
    try:
        profile = _read_profile(character_name)
    except Exception as e:  # noqa: BLE001 — a DB / decoding error is the Build's failure, never "current"
        return _record_unread(character_name, reason, e)
    if not on_pipeline(character_name, profile=profile):
        return {"status": "off", "reason": OFF_PIPELINE}
    with _lock:
        if character_name in _active:
            _keep_followup_locked(character_name, reason, automatic)
            return {"status": "queued"}
    busy = base_step_in_flight(character_name)
    if busy:
        # Ruling A26 a: never beside a base step — a click is refused naming it, a trigger waits for it.
        if automatic:
            return _defer(character_name, reason, busy)
        return {"status": "base_busy", "reason": BASE_STEP_RUNNING.format(step=busy)}
    if not _runnable(plan(character_name, profile=profile, explicit=not automatic), not automatic):
        return {"status": "current"}
    with _lock:
        if character_name in _active:  # another start won the race
            _keep_followup_locked(character_name, reason, automatic)
            return {"status": "queued"}
        _queues[character_name] = deque([(reason, automatic)])
        _active.add(character_name)
        _current[character_name] = {"reason": reason, "step": None, "steps": []}
    threading.Thread(target=_worker, args=(character_name,), daemon=True,
                     name=f"figure-build-{character_name}").start()
    logger.info("Build %s started (%s%s)", character_name, reason, ", automatic" if automatic else "")
    if not automatic:
        _drop_held_build(character_name)
    return {"status": "started"}


def _drop_held_build(character_name: str) -> None:
    """A manual Build covers a held automatic one (Ruling A42): it plans the figure wanted now."""
    try:
        from app.core import generation_pause
        if generation_pause.is_paused(character_name):
            from app.core.task_queue import get_task_queue
            get_task_queue().drop_trigger(character_name, "build")
    except Exception:  # noqa: BLE001 — the held entry only stays listed
        logger.debug("Held Build of %s not dropped", character_name, exc_info=True)


# --- Automatic ------------------------------------------------------------------------

#: Profile key of the Figure tab's "Build automatically" (absent = on).
AUTO_BUILD_KEY = "figure_auto_build"


def auto_build_on(character_name: str, *, profile: Optional[Dict[str, Any]] = None) -> bool:
    """Whether triggers start the character's Build: the profile's
    ``figure_auto_build`` (absent = on) and the world switch of the automatic
    outfit renders (``model_refs._enabled()``, as for the T-pose pass before)."""
    from app.core import model_refs
    if not model_refs._enabled():
        return False
    return _profile_of(character_name, profile).get(AUTO_BUILD_KEY) is not False


def set_auto_build(character_name: str, enabled: bool) -> bool:
    """Store "Build automatically" (profile read-modify-write under the
    character's profile lock). Switching it off never stops a run going.
    The save's bool."""
    from app.core.keyed_lock import keyed_lock
    from app.models.character import get_character_profile, save_character_profile
    with keyed_lock("character_profile", character_name):
        profile = get_character_profile(character_name) or {}
        profile[AUTO_BUILD_KEY] = bool(enabled)
        return bool(save_character_profile(character_name, profile))


def request(character_name: str, trigger: str) -> bool:
    """A trigger's way to the Build (module docstring): on the pipeline with
    ``auto_build_on`` → an automatic ``start(reason=trigger)``; True when it
    started or was kept as the follow-up. Else False — the change stays in
    ``figure.pending_changes``; a profile that cannot be read is recorded as
    the Build's failure (ruling F13 e). A request while a base-body step runs is
    deferred until it is done (Ruling A26 a) — True as well. While the
    character's automatic generation is paused the request is held instead
    (Ruling A42, ``generation_pause.hold_build``) — False. Never raises."""
    try:
        try:
            profile = _read_profile(character_name)
        except Exception as e:  # noqa: BLE001 — recorded, never "not requested" in silence
            _record_unread(character_name, trigger, e)
            return False
        if not on_pipeline(character_name, profile=profile) or not auto_build_on(character_name, profile=profile):
            logger.debug("Build %s not requested (%s): off the pipeline or not automatic", character_name, trigger)
            return False
        from app.core import generation_pause
        if generation_pause.hold_build(character_name, trigger):
            # Ruling A42: paused — nothing starts; Resume asks again (the change stays marked meanwhile).
            return False
        return start(character_name, reason=trigger, automatic=True).get("status") in ("started", "queued",
                                                                                       "deferred")
    except Exception:  # noqa: BLE001 — a trigger never breaks its caller
        logger.exception("Build request of %s (%s) failed", character_name, trigger)
        return False


def wearers(item_id: str) -> List[str]:
    """The characters on the pipeline whose ``equipped_pieces`` hold
    ``item_id`` — every stored character, dormant and pooled ones included
    (they keep their figure). Sorted by name."""
    from app.models.character import get_character_profile, list_available_characters
    out: List[str] = []
    for name in list_available_characters(include_pooled=True):
        try:
            profile = get_character_profile(name) or {}
        except Exception:  # noqa: BLE001 — one unreadable profile never hides the rest
            logger.warning("Profile of %s unreadable for the wearers of %s", name, item_id, exc_info=True)
            continue
        if item_id not in (profile.get("equipped_pieces") or {}).values():
            continue
        if on_pipeline(name, profile=profile):
            out.append(name)
    return sorted(out, key=str.lower)


def state(character_name: str) -> Dict[str, Any]:
    """``{running, step, queued, deferred, failed, skipped, superseded, reason, finished_at}``:
    ``step`` the step in flight (``{name, label, jobs, item_id, index,
    count}``), ``queued`` the follow-ups kept (0 or 1); ``failed`` /
    ``skipped`` / ``finished_at`` of the last run that had steps;
    ``superseded`` its ``{step, label, note}`` when it ended superseded
    (Ruling A18), else None; ``paused`` its ``{step, label, note}`` when the
    character's pause stopped it (Ruling A42), else None; ``deferred`` the reason of an automatic Build that
    waits for a base step (Ruling A26 a), else None."""
    with _lock:
        deferred = _deferred.get(character_name)
        running = character_name in _active
        current = dict(_current.get(character_name) or {})
        queued = len(_queues.get(character_name) or ())
        last = dict(_last.get(character_name) or {})
    return {"running": running, "step": current.get("step") if running else None, "queued": queued,
            "deferred": deferred, "paused": dict(last["paused"]) if last.get("paused") else None,
            "failed": dict(last.get("failed") or {}), "skipped": list(last.get("skipped") or []),
            "superseded": dict(last["superseded"]) if last.get("superseded") else None,
            "reason": current.get("reason") if running else last.get("reason"),
            "finished_at": last.get("finished_at")}


def dismiss_failure(character_name: str, step: str) -> bool:
    """A166: forget the last run's failure of ``step`` (and, for ``assemble``, the recorded refusal of the figure
    delivered now) — the status no longer says "a step failed" for it; the next Build tries it again. A chain that
    failed for its current input stays listed (its own row offers its fix). True when something was dropped."""
    from app.core import base_body
    dropped = False
    with _lock:
        last = _last.get(character_name)
        failed = (last or {}).get("failed") or {}
        if step in failed:
            failed.pop(step)
            dropped = True
    if step == "assemble":
        try:
            _profile, wanted, _delivered, _items = _now(character_name)
            if base_body.assemble_refusal(character_name, wanted.signature, _delivered) is not None:
                dropped = True
            base_body.clear_assemble_refusal(character_name, wanted.signature)
        except Exception:  # noqa: BLE001 — the last run's record is dropped either way
            logger.debug("Build %s: assembly refusal not cleared", character_name, exc_info=True)
    if dropped:
        base_body._invalidate_figure()
        _notify_build_changed()
    return dropped


#: The Build steps whose failure names ONE piece (``Step.item_id``): its garment chain (``_chain``: the error
#: "<garment step> — <reason>") and the Re-fit run's fit (``_run_refit``: ``fits``, the refused fit itself).
PIECE_FAILURE_STEPS = ("pieces", "hair", "fits")
_CHAIN_ERROR_STEP = re.compile(r"^([a-z_]+) — ")


def _answered_by(name: str, error: str, steps: frozenset) -> bool:
    """Whether a recorded failure of Build step ``name`` (``error``) is one of the garment ``steps`` a user's
    acceptance answers: a chain failure at one of them, the Re-fit run's refused fit for ``fit``."""
    if name == "fits":
        return "fit" in steps
    found = _CHAIN_ERROR_STEP.match(error)
    return bool(found and found.group(1) in steps)


def answer_piece_failure(character_name: str, item_id: str, steps) -> bool:
    """Ruling A69: the user took a result of the piece ``item_id`` that its checks refused — a refused fit accepted
    (``fit_attempts.accept``), a stored image or a kept mesh used (``garments.use_attempt`` / ``use_mesh``). The last
    Build's failure of THAT piece at one of the garment ``steps`` is answered by it and goes from the Build's state:
    the Figure tab's row, its head and the Build problem of the Figure and 3D tabs then follow the accepted result
    instead of saying "Failed" until the next Build (Kai's jeans, 2026-11-14: the Build of 22:03 failed at the fit,
    the user accepted that fit at 22:04, the figure was assembled with it — and the row said "Failed"). Every other
    failure of the run stays; a Build that runs later records its own (a newer refusal shows again). Returns whether
    anything went."""
    wanted = frozenset(steps)
    changed = False
    with _lock:
        last = _last.get(character_name)
        failed = (last or {}).get("failed") or {}
        for name in [n for n in PIECE_FAILURE_STEPS if n in failed]:
            entry = failed[name]
            items = dict(entry.get("items") or {entry.get("item_id"): entry.get("error")})
            error = str(items.get(item_id) or "")
            if item_id not in items or not _answered_by(name, error, wanted):
                continue
            items.pop(item_id)
            changed = True
            if not items:
                failed.pop(name)
                continue
            first, first_error = next(iter(items.items()))
            failed[name] = {**{k: v for k, v in entry.items() if k != "items"}, "item_id": first,
                            "error": first_error, **({"items": items} if len(items) > 1 else {})}
    if changed:
        logger.info("Build %s: the failure of %s answered by the user's acceptance (%s)", character_name, item_id,
                    ", ".join(sorted(wanted)))
    return changed


def _worker(character_name: str) -> None:
    while True:
        with _lock:
            queue = _queues.get(character_name)
            if not queue:
                _active.discard(character_name)
                _current.pop(character_name, None)
                return
            reason, automatic = queue.popleft()
            refit_item = _refit_items.pop(character_name, "") if reason == REFIT_REASON else ""
            _current[character_name] = {"reason": reason, "step": None, "steps": []}
        if automatic and not refit_item and reason != PAINT_REASON:
            from app.core import generation_pause
            if generation_pause.hold_build(character_name, reason):
                continue   # Ruling A42: a kept automatic follow-up waits for the Resume
        _notify_build_changed()
        try:
            with build_lock(character_name):
                if refit_item:
                    _run_refit(character_name, refit_item)
                elif reason == PAINT_REASON:
                    _run_paint(character_name)
                else:
                    _run(character_name, reason, automatic=automatic)
        except Exception:  # noqa: BLE001 — a worker reports, never raises
            logger.exception("Build %s (%s) failed", character_name, reason)
        finally:
            _notify_build_changed()


def _notify_build_changed() -> None:
    """Ruling A136: a Build (or re-fit) of a character started or ended — push the admin-only topic
    ``generation`` to the admins' connections (a topic, never data; Build state is admin-only, so never to the
    character's avatar), so an open piece dialog and the Figure tab reload instead of keeping stale text."""
    from app.core import sync_topics
    sync_topics.notify("generation", to=sync_topics.Admins())


def _tracked(character_name: str, label: str):
    """A task-queue display row (``track_start``); (queue, id) or (None, "")."""
    try:
        from app.core.task_queue import get_task_queue
        queue = get_task_queue()
        return queue, queue.track_start(TRACK_TYPE, label, agent_name=character_name, start_running=True)
    except Exception:  # noqa: BLE001 — the display row is optional
        logger.debug("Build of %s not tracked", character_name, exc_info=True)
        return None, ""


def _run(character_name: str, reason: str, *, automatic: bool = False) -> None:
    """One Build: re-plan, then every step in order (module docstring). An
    ``automatic`` run reports a cached chain failure without running it; a
    manual one retries it."""
    from app.core import garment_hair
    try:
        # Hairstyles (plan Task 13): a humanoid without one gets its first, worn, before anything is planned.
        garment_hair.ensure_hairstyle(character_name)
    except ValueError as e:
        logger.info("Build %s: no hairstyle (%s)", character_name, e)
    except Exception as e:  # noqa: BLE001 — a hairstyle that cannot be made never blocks the Build
        logger.warning("Build %s: the first hairstyle was not made: %s", character_name, e)
    try:
        profile = _read_profile(character_name)
    except Exception as e:  # noqa: BLE001 — ruling F13 e: failed, never "nothing to build"
        _record_unread(character_name, reason, e)
        return
    _run_planned(character_name, reason, profile, automatic=automatic)


def _figure_text(fig) -> str:
    """How a superseded step names the figure the follow-up builds."""
    return f"figure {fig.signature} (shape {fig.shape})"


def _moved_fields(old: Dict[str, Any], new: Dict[str, Any]) -> str:
    """The ``Figure.as_dict`` keys that differ, in their order — what moved."""
    return ", ".join(k for k in dict.fromkeys([*old, *new]) if old.get(k) != new.get(k)) or "figure"


def _pin(character_name: str, wanted) -> None:
    with _lock:
        _pins[character_name] = wanted


def _check_pin(character_name: str) -> None:
    """``StepSuperseded`` when the wanted figure of now is not the one the run pinned (Ruling A18). A profile
    that cannot be read is no verdict here (the step reports it)."""
    with _lock:
        pinned = _pins.get(character_name)
    if pinned is None:
        return
    try:
        _profile, wanted, _delivered, _items = _now(character_name)
    except Exception:  # noqa: BLE001 — the step itself fails on it
        return
    if wanted.as_dict() != pinned.as_dict():
        raise StepSuperseded(SUPERSEDED.format(why=WANTED_MOVED.format(
            fields=_moved_fields(pinned.as_dict(), wanted.as_dict())), new=_figure_text(wanted)))


#: Steps that write the base views themselves: the run takes its base snapshot again after them (Ruling A26 b).
BASE_WRITING_STEPS = frozenset({"plain_body"})


def _base_snapshot(character_name: str) -> Optional[Tuple[str, Dict[str, str]]]:
    """``(base signature, {view: sha256})`` of the character's base views now ("" for a missing one) — what a
    running Build compares before each step (Ruling A26 b). None when it cannot be read (no verdict then)."""
    try:
        from app.core import base_body
        from app.core.model_refs import find_ref_image
        bsig = base_body.base_signature(character_name)
        return bsig, {v: base_body.file_sha256(find_ref_image(character_name, base_body._kind(v), bsig))
                      for v in base_body.BASE_VIEWS}
    except Exception:  # noqa: BLE001 — no snapshot, no verdict; the steps report their own errors
        logger.debug("Build %s: base snapshot not read", character_name, exc_info=True)
        return None


def _base_changed(character_name: str, snapshot: Optional[Tuple[str, Dict[str, str]]]) -> List[str]:
    """The base views whose content is not the run's snapshot any more ([] without a snapshot). Another base
    SIGNATURE is no verdict here: the wanted figure moved with it, the pin says so (Ruling A18 — superseded,
    with its follow-up)."""
    if snapshot is None:
        return []
    now = _base_snapshot(character_name)
    if now is None or now[0] != snapshot[0]:
        return []
    return [v for v in snapshot[1] if now[1].get(v, "") != snapshot[1][v]]


def _step_text(step: Step) -> str:
    return step.name.replace("_", " ")


def _run_planned(character_name: str, reason: str, profile: Dict[str, Any], *, automatic: bool) -> None:
    """``_run`` after the profile was read: plan, then every step in order. The run pins the wanted figure of
    its plan (Ruling A18, module docstring); a step that raises ``StepSuperseded`` ends the run without a
    failure and keeps ONE follow-up."""
    from app.core import figure
    from app.core.timeutils import utc_now_iso
    explicit = not automatic
    resolved = figure._delivered(character_name, profile=profile)
    steps = plan(character_name, profile=profile, explicit=explicit, resolved=resolved)
    if automatic:
        # Rulings 8a / A11: the plain body and the take-out stay listed (the UI's pending change), an automatic
        # run never builds them.
        steps = [s for s in steps if not s.manual]
    if not _runnable(steps, explicit):
        logger.info("Build %s (%s): nothing to build", character_name, reason)
        return
    busy = base_step_in_flight(character_name)
    if busy:
        # Ruling A26 a, for a run that slipped past ``start`` (a kept follow-up, a race with a click): nothing
        # is built beside a base step — an automatic run waits for it, a manual one says why it did not start.
        if automatic:
            _defer(character_name, reason, busy)
        else:
            with _lock:
                _last[character_name] = {"failed": {"build": {"error": BASE_STEP_RUNNING.format(step=busy),
                                                              "item_id": ""}},
                                         "skipped": [s.name for s in steps], "reason": reason,
                                         "finished_at": utc_now_iso(), "superseded": None}
            logger.info("Build %s (%s) not run: %s", character_name, reason, BASE_STEP_RUNNING.format(step=busy))
        return
    with _lock:
        _current[character_name] = {"reason": reason, "step": None, "steps": [s.as_dict() for s in steps]}
    _pin(character_name, resolved[0])
    # Ruling A26 b: the base views as the run found them — a change under it stops it at the next step.
    snapshot = _base_snapshot(character_name)
    queue, task_id = _tracked(character_name, f"Build · {character_name} (0/{len(steps)})")
    failed: Dict[str, Dict[str, Any]] = {}
    skipped: List[str] = []
    superseded: Optional[Dict[str, str]] = None
    paused: Optional[Dict[str, str]] = None
    from app.core import generation_pause
    try:
        for index, step in enumerate(steps, 1):
            if automatic and generation_pause.is_paused(character_name):
                # Ruling A42: the step before has finished; nothing after it starts — held for the Resume.
                paused = _paused_here(character_name, reason, step, queue, task_id)
                break
            shown = step.running_label(explicit)
            label = f"Build · {character_name} ({index}/{len(steps)} {shown})"
            with _lock:
                _current[character_name]["step"] = {**step.as_dict(), "label": shown, "index": index,
                                                    "count": len(steps)}
            if queue is not None and task_id:
                try:
                    queue.track_update_label(task_id, label)
                except Exception:  # noqa: BLE001
                    logger.debug("Build track %s not relabelled", task_id, exc_info=True)
            if DEPENDS.get(step.name, set()) & (set(failed) | set(skipped)):
                if step.name not in skipped:
                    skipped.append(step.name)
                logger.info("Build %s: %s skipped — it needs %s", character_name, step.label,
                            sorted(DEPENDS[step.name] & (set(failed) | set(skipped))))
                continue
            changed = _base_changed(character_name, snapshot)
            if changed:
                error = BASE_CHANGED.format(step=_step_text(step))
                logger.warning("Build %s: base views %s changed during the Build — stopped before %s",
                               character_name, ", ".join(changed), step.label)
            elif step.failed and automatic:
                # Ruling 7a: an automatic Build never spends a chain that failed for this input.
                error = step.failed
            else:
                try:
                    if step.name not in UNPINNED_STEPS:
                        _check_pin(character_name)
                    if step.name == "plain_body":
                        _wait_base_views(character_name)
                    error = _run_step(character_name, step, explicit)
                except BuildPaused:
                    # Ruling A42: the chain of this step waits held in the garment FIFO.
                    paused = _paused_here(character_name, reason, step, queue, task_id)
                    break
                except StepSuperseded as e:
                    # Ruling A18: the figure moved — not a failure; ONE follow-up builds the figure wanted now.
                    superseded = {"step": step.name, "label": step.label, "note": str(e)}
                    logger.info("Build %s: %s superseded — %s", character_name, step.label, e)
                    with _lock:
                        _keep_followup_locked(character_name, SUPERSEDED_REASON, automatic)
                    if queue is not None and task_id:
                        try:
                            queue.track_update_label(task_id, f"Build · {character_name} — superseded, the "
                                                              "follow-up builds the figure wanted now")
                        except Exception:  # noqa: BLE001
                            logger.debug("Build track %s not relabelled", task_id, exc_info=True)
                    break
                if not error and step.name in REPIN_STEPS:
                    try:
                        _pin(character_name, _now(character_name)[1])   # the Build's own change of the figure
                    except Exception:  # noqa: BLE001 — the next step reports an unreadable profile
                        logger.debug("Build %s: pin not renewed", character_name, exc_info=True)
                if step.name in BASE_WRITING_STEPS:
                    snapshot = _base_snapshot(character_name)   # the Build's own change of the base views
                elif _base_changed(character_name, snapshot):
                    # Ruling A26 b: the base changed while the step ran — what it made stands on the replaced
                    # base, and a failure is BECAUSE of that (a live test: "views missing" for a dressed front edited
                    # from the replaced base front). Stop here, never with the step's own error.
                    logger.warning("Build %s: the base views changed while %s ran (%s)", character_name,
                                   step.label, error or "done")
                    error = BASE_CHANGED.format(step=_step_text(step))
                    changed = ["changed"]
            if error:
                logger.warning("Build %s: %s failed: %s", character_name, step.label, error)
                entry = failed.get(step.name)
                if entry is None:
                    failed[step.name] = {"error": error, "item_id": step.item_id}
                else:
                    entry.setdefault("items", {entry["item_id"]: entry["error"]})[step.item_id] = error
                if step.name in STOP_STEPS or changed:
                    # Ruling C4: a refused view stops the Build here — nothing is meshed, painted or assembled
                    # from what it left; the figure delivered before stays served. Ruling A26 b: so does a base
                    # that changed under the Build.
                    rest = [s.name for s in steps[index:] if s.name not in skipped]
                    skipped.extend(dict.fromkeys(rest))
                    logger.info("Build %s stopped at %s — skipped: %s", character_name, step.label,
                                ", ".join(dict.fromkeys(rest)) or "nothing")
                    break
            else:
                logger.info("Build %s: %s done", character_name, step.label)
    finally:
        with _lock:
            _pins.pop(character_name, None)
            _last[character_name] = {"failed": failed, "skipped": skipped, "reason": reason,
                                     "finished_at": utc_now_iso(), "superseded": superseded, "paused": paused}
        if queue is not None and task_id:
            try:
                queue.track_finish(task_id, error="; ".join(f"{k}: {v['error']}" for k, v in failed.items()))
            except Exception:  # noqa: BLE001
                logger.debug("Build track %s not finished", task_id, exc_info=True)


def _paused_here(character_name: str, reason: str, step: Step, queue, task_id: str) -> Dict[str, str]:
    """An automatic run stopped by the pause before ``step`` (Ruling A42): held for the Resume; the run's
    ``paused`` record."""
    from app.core import generation_pause
    generation_pause.hold_build(character_name, reason)
    note = generation_pause.BUILD_PAUSED.format(step=step.label)
    logger.info("Build %s: automatic generation paused — stopped before %s", character_name, step.label)
    if queue is not None and task_id:
        try:
            queue.track_update_label(task_id, f"Build · {character_name} — paused before {step.label}")
        except Exception:  # noqa: BLE001
            logger.debug("Build track %s not relabelled", task_id, exc_info=True)
    return {"step": step.name, "label": step.label, "note": note}


# --- Steps (each returns "" or the error) --------------------------------------------

def _run_step(character_name: str, step: Step, explicit: bool) -> str:
    """Run one step: "" or its error (an exception is the error)."""
    from app.core import model3d
    try:
        if step.name in SLOT_STEPS:
            with model3d.generation_slot(character_name):
                return _RUNNERS[step.name](character_name, step, explicit)
        return _RUNNERS[step.name](character_name, step, explicit)
    except (StepSuperseded, BuildPaused):
        raise  # Ruling A18: not the step's failure — ``_run_planned`` ends the run and keeps the follow-up
    except Exception as e:  # noqa: BLE001 — the step failed, the run goes on
        logger.exception("Build %s: %s failed", character_name, step.label)
        return str(e) or type(e).__name__


def _now(character_name: str):
    """``(profile, wanted, delivered, items)`` judged now — the profile read strictly (a read error fails the
    step, ruling F13 e)."""
    from app.core import figure
    profile = _read_profile(character_name)
    wanted, delivered = figure._delivered(character_name, profile=profile)
    return profile, wanted, delivered, figure._items_of(profile, None)


#: How long the Build's plain body step waits for base views rendered beside it (Ruling A20), and how often it
#: looks.
BASE_VIEWS_WAIT_S = 1800.0
BASE_VIEWS_POLL_S = 2.0


def _wait_base_views(character_name: str, *, timeout_s: Optional[float] = None,
                     poll_s: Optional[float] = None) -> List[str]:
    """Ruling A20: before the Build's plain body step judges what is missing, the base views reserved by a
    render beside it (a view's Regenerate or the skin step started before the Build — the routes refuse new
    ones while it runs) are waited for, so the plain body is judged and meshed from the views that run
    leaves, never from the front it replaces. Returns the views still reserved after ``timeout_s`` (then the
    step goes on: ``generate_base_images`` serialises on the character's render lock)."""
    import time
    from app.core import base_body
    timeout_s = BASE_VIEWS_WAIT_S if timeout_s is None else timeout_s
    poll_s = BASE_VIEWS_POLL_S if poll_s is None else poll_s
    deadline = time.monotonic() + timeout_s
    logged = False
    while True:
        busy = [v for v, st in base_body.base_status(character_name).items() if st.get("running")]
        if not busy or time.monotonic() >= deadline:
            if busy:
                logger.warning("Build %s: base views %s still render after %.0f s — the plain body step goes on",
                               character_name, ", ".join(busy), timeout_s)
            elif logged:
                logger.info("Build %s: the base views rendered beside it are done", character_name)
            return busy
        if not logged:
            logger.info("Build %s: waiting for the base views being rendered (%s) before the plain body step",
                        character_name, ", ".join(busy))
            logged = True
        time.sleep(poll_s)


def _run_plain_body(character_name: str, step: Step, explicit: bool = False) -> str:
    """The plain body's views (all four in one run when the front is among them — the
    others edit the new front — else each view alone), then its model; forced."""
    from app.core import base_body, view_facing
    refresh = base_body.base_refresh_plan(character_name, missing=True)
    views = list(refresh.get("views") or ())
    if views:
        if "front" in views:
            results = base_body.generate_base_images(character_name, force=True)
        else:
            results = {}
            for view in views:
                results.update(base_body.generate_base_images(character_name, view=view, force=True))
        missing = [v for v in views if not results.get(v)]
        if missing:
            status = base_body.base_status(character_name)
            error = next((status[v].get("error") for v in missing if (status.get(v) or {}).get("error")), None)
            return f"views {', '.join(missing)} — {error or 'render failed'}"
    if refresh.get("model") or views:
        holds = _side_view_holds(character_name)
        if holds:
            # Ruling A96: no hub jobs on side views the user must look at first — the tab names what to do; the
            # base model's own button builds it anyway (the user's decision).
            return view_facing.HOLD_PREFIX + "; ".join(holds)
        result = base_body.generate_base_model(character_name, force=True)
        if not result.get("ok"):
            return str(result.get("error") or "Base model generation failed")
    return ""


def _side_view_holds(character_name: str) -> List[str]:
    """``view_facing.side_view_holds`` of the stored base side views (Ruling A96); [] when they cannot be found."""
    from app.core import base_body, view_facing
    from app.core.model_refs import find_ref_image
    bsig = base_body.base_signature(character_name)
    if not bsig:
        return []
    sides = {v: find_ref_image(character_name, base_body._kind(v), bsig) for v in view_facing.SIDE_VIEWS}
    return view_facing.side_view_holds(sides["left"], sides["right"])


#: The Build's label of the base mesh repair step.
MESH_REPAIR_LABEL = "Base mesh repair (local)"


def _mesh_repair_due(character_name: str, bsig: str) -> bool:
    """Whether the stored base model ``bsig`` needs its mesh repair (``model3d.mesh_repair_state`` ``due``);
    False without a stored base model or when the state cannot be read."""
    from app.core import model3d
    try:
        state = model3d.mesh_repair_state(character_name, bsig) if bsig else None
    except Exception:  # noqa: BLE001 — a plan never fails on it
        logger.debug("Build %s: mesh repair state not read", character_name, exc_info=True)
        return False
    return bool(state and state.get("due"))


def _run_base_repair(character_name: str, step: Step, explicit: bool = False) -> str:
    """The base mesh repair of the stored base model when it is (still) due — a plain body rebuilt before it
    in this Build was repaired by its own run. Local; the base's changed bytes refit what is fitted on it."""
    from app.core import base_body, model3d
    bsig = base_body.base_signature(character_name)
    if not _mesh_repair_due(character_name, bsig):
        return ""
    result = model3d.rebuild_extension_rig(character_name, bsig, force=True, repair=True)
    if not result.get("ok"):
        return str(result.get("error") or (result.get("extension_rig") or {}).get("reason")
                   or "Base mesh repair failed")
    return ""


#: The Build's label of the tip smoothing step (Ruling A43).
TIP_SMOOTHING_LABEL = "Tip smoothing (local)"


def _tip_smoothing_due(character_name: str, bsig: str) -> bool:
    """Whether the stored base model ``bsig`` needs its tip smoothing (``extension_tip.model_tip_smoothing_due``);
    False without a stored base model, without a switched-on ``pair_tip`` group or when it cannot be read."""
    from app.core import extension_tip, model3d
    try:
        path = model3d.find_model3d(character_name, bsig) if bsig else None
        if path is None:
            return False
        meta = model3d._read_sidecar(path)
        meta.setdefault("rig", model3d.required_rig(character_name))
        return extension_tip.model_tip_smoothing_due(character_name, path, meta)
    except Exception:  # noqa: BLE001 — a plan never fails on it
        logger.debug("Build %s: tip smoothing state not read", character_name, exc_info=True)
        return False


def _has_tip_smoothing(character_name: str, bsig: str) -> bool:
    """Whether the stored base model ``bsig`` shows a tip smoothing row (``extension_tip.tip_smoothing_state``)."""
    from app.core import extension_tip
    return bool(bsig) and extension_tip.tip_smoothing_state(character_name, bsig) is not None


def _run_tip_smoothing(character_name: str, step: Step, explicit: bool = False) -> str:
    """The extension rebuild of the stored base model when its tip smoothing is (still) due — a base repaired or
    rebuilt before it in this Build was smoothed by that run. Local; changed base bytes refit what is fitted on it."""
    from app.core import base_body, model3d
    bsig = base_body.base_signature(character_name)
    if not _tip_smoothing_due(character_name, bsig):
        return ""
    result = model3d.rebuild_extension_rig(character_name, bsig, force=True)
    if not result.get("ok"):
        return str(result.get("error") or (result.get("extension_rig") or {}).get("reason")
                   or "Tip smoothing failed")
    return ""


#: The Build's label of the collision channel step (``collision.channels_due``; module docstring step 9).
COLLISION_LABEL = "Collision capsules: apply the saved channel settings (local)"


def _collision_due(character_name: str) -> bool:
    """Whether a stored model of the character carries channels the saved settings no longer match
    (``collision.channels_due``); False when it cannot be read (a plan never fails on it)."""
    from app.core import collision
    try:
        return collision.channels_due(character_name)
    except Exception:  # noqa: BLE001 — a plan never fails on it
        logger.debug("Build %s: collision channels state not read", character_name, exc_info=True)
        return False


def _run_collision(character_name: str, step: Step, explicit: bool = False) -> str:
    """Apply the saved channel settings to every stored model of the character
    (``collision.recompute_character(apply_channels=True)``) — CPU, no hub job. "" or the models that failed."""
    from app.core import collision
    if not _collision_due(character_name):
        return ""
    result = collision.recompute_character(character_name, apply_channels=True)
    failed = [f"{signature}: {entry.get('error') or 'failed'}" for signature, entry in (result.get("models") or {}).items()
              if not entry.get("ok")]
    return "Collision capsules not recomputed — " + "; ".join(failed) if failed else ""


def _outfit_model(character_name: str, signature: str) -> str:
    """The outfit model of the figure delivered now, without the shape
    preparation (the Build's own steps make shapes). Not forced: a model of
    exactly this figure is kept, and a texture painted before is reused
    (``base_body.stored_texture_body``) — an automatic Build runs on every
    trigger, it must not repaint what is stored (Task 8)."""
    from app.core import model3d
    result = model3d.generate_for_current_outfit(character_name, signature=signature, prepare=False)
    return "" if result.get("ok") else str(result.get("error") or "Outfit model build failed")


#: ``_dressed``'s error: a dressed view stayed missing (Ruling C4).
DRESSED_VIEWS_MISSING = "Views missing: {views} — nothing is painted or assembled without them"


def _view_identity(fig) -> Dict[str, Any]:
    """What the dressed views of a figure are made for (Ruling A18): its shape, texture, hair and which pieces
    are in the body / grafted."""
    return {"shape": fig.shape, "texture": fig.texture, "hair": fig.hair, "in_body": list(fig.in_body),
            "own": list(fig.own)}


def _dressed(character_name: str, wanted) -> str:
    """The views of the figure delivered NOW for the worn outfit (missing ones only); "" when every
    ``dressed_views()`` view is current afterwards, else the error — the recorded refusal (a composite that
    failed, Ruling C4) or which views are missing. Nothing is built on top of a view that stayed missing.
    Ruling A18: the views are judged for the figure they were rendered for — when the delivered figure moved
    while they rendered (a garment fit accepted, the hair changed), ``StepSuperseded``, never "Views
    missing"."""
    from app.core import base_body
    _profile, _w, before, items = _now(character_name)
    try:
        base_body.generate_dressed_images(character_name, pieces=dict(wanted.pieces), items=items,
                                          signature=wanted.signature)
    except Exception as e:  # noqa: BLE001 — reported as the step's error below
        logger.warning("Build %s: dressed views of %s failed: %s", character_name, wanted.signature, e)
    _profile, wanted_now, delivered, _items = _now(character_name)
    if _view_identity(delivered) != _view_identity(before):
        raise StepSuperseded(SUPERSEDED.format(why=VIEWS_MOVED.format(
            fields=_moved_fields(_view_identity(before), _view_identity(delivered))), new=_figure_text(wanted_now)))
    missing = [v for v in base_body.dressed_views()
               if base_body.dressed_image(character_name, v, wanted.signature, delivered.bsig, fig=delivered) is None]
    if not missing:
        return ""
    reason = base_body.outfit_failure(character_name, wanted.signature)
    stale = base_body.stale_views(character_name, wanted.signature, missing)
    if stale:
        # Ruling A26 c: a stored view edited from a base view replaced since is stale, not missing.
        if reason == base_body.DRESSED_FRONT_STALE and "front" in stale:
            reason = ""
        gone = [v for v in missing if v not in stale]
        text = base_body.VIEWS_STALE.format(views=base_body._join_views(stale),
                                            verb="is" if len(stale) == 1 else "are")
        if gone:
            text += "; " + DRESSED_VIEWS_MISSING.format(views=", ".join(gone))
        return text + (f" ({reason})" if reason else "")
    return DRESSED_VIEWS_MISSING.format(views=", ".join(missing)) + (f" ({reason})" if reason else "")


def _run_shape(character_name: str, step: Step, explicit: bool = False) -> str:
    """The wanted meshed shape (``base_body.prepare_shape``). Ruling A18: the step pins that shape — a hair or
    outfit change that wants another one stops the mesh before its next hub stage (``model3d.shape_guard``)
    and ends the step superseded (``StepSuperseded``)."""
    from app.core import base_body, figure, model3d
    _profile, wanted, _delivered, items = _now(character_name)
    shape = wanted.shape
    if figure.is_plain(shape):
        return ""
    _retry_refused_views(character_name, step, explicit, shape)
    # Ruling A61: a stored shape whose mesh the paint step refused against its views is meshed again (manual only).
    rebuild = explicit and base_body.mesh_view_mismatch(character_name, shape) is not None
    with model3d.shape_guard(character_name, shape, lambda: _now(character_name)[1].shape == shape):
        result = base_body.prepare_shape(character_name, wanted, items=items, signature=wanted.signature,
                                         rebuild=rebuild)
    if result is not None and not result.get("ok") and not result.get("superseded"):
        return str(result.get("error") or "Body shape build failed")
    _profile, wanted_now, _d, _items = _now(character_name)
    if wanted_now.shape != shape:
        raise StepSuperseded(SUPERSEDED.format(why=SHAPE_MOVED.format(shape=shape, now=wanted_now.shape),
                                               new=_figure_text(wanted_now)))
    if result is not None and result.get("superseded"):
        # The guard said no, but the shape is wanted again now: the follow-up builds it.
        raise StepSuperseded(SUPERSEDED.format(why=str(result.get("error") or "the body shape moved"),
                                               new=_figure_text(wanted_now)))
    return ""


def _chain(character_name: str, item_id: str, explicit: bool) -> str:
    """The item's chain through the character's garment FIFO; ``explicit`` (a
    manual Build) clears a cached failure first and retries it (ruling 7a)."""
    from app.core import garments
    with _lock:
        _own_chains.setdefault(character_name, set()).add(item_id)
    try:
        runs = garments.run_queued(character_name, [item_id], explicit=True) if explicit else \
            garments.run_queued(character_name, [item_id])
    finally:
        with _lock:
            _own_chains.get(character_name, set()).discard(item_id)
    result = runs.get(item_id) or {}
    if result.get("ok"):
        return ""
    if result.get("paused"):
        raise BuildPaused(str(result.get("error") or ""))
    error = str(result.get("error") or "chain failed")
    return f"{result['step']} — {error}" if result.get("step") else error


def _run_pieces(character_name: str, step: Step, explicit: bool = False) -> str:
    return _chain(character_name, step.item_id, explicit)


def _run_template(character_name: str, step: Step, explicit: bool = False) -> str:
    """Drape one template piece (``garment_template.build``; a manual Build first forgets its failed drape)."""
    from app.core import garment_template
    if explicit and step.failed:
        garment_template.clear_failure(character_name, step.item_id)
    profile = _read_profile(character_name)
    state = garment_template.build(character_name, step.item_id, profile=profile)
    return "" if state["state"] == "ready" else str(state["reason"])


def _run_hair(character_name: str, step: Step, explicit: bool = False) -> str:
    """The worn HairDeck hairstyle's chain (``step.item_id``, else the worn one now)."""
    from app.core import garment_hair
    item_id = step.item_id or garment_hair.worn_hair_id(character_name)
    if not item_id:
        return "No hairstyle is worn"
    return _chain(character_name, item_id, explicit)


def _run_texture(character_name: str, step: Step, explicit: bool = False) -> str:
    """The views of the painted set on the wanted shape (the paint is the assembly's)."""
    _profile, wanted, _delivered, _items = _now(character_name)
    _retry_refused_views(character_name, step, explicit, wanted.signature)
    return _dressed(character_name, wanted)


def _run_fits(character_name: str, step: Step, explicit: bool = False) -> str:
    """The CPU refits; a manual Build first re-fits the pieces whose fit on the wanted body shape was refused
    (Ruling A23 b, ``refit_refused``) — refused again: the step's error, the piece stays left off."""
    from app.core import garment_refit
    if explicit:
        still = refit_refused(character_name)
        if still:
            return REFIT_REFUSED.format(items="; ".join(f"{_item_name(i)}: {r}" for i, r in sorted(still.items())))
    done = garment_refit.tracked(character_name, lambda: garment_refit.refit_character(character_name))
    if done is None:
        logger.info("Build %s: refits skipped — a garment chain of the character runs", character_name)
    return ""


def _refused_fit_of(character_name: str, item_id: str, wanted, profile: Dict[str, Any]):
    """``(base fit, fsig)`` of a wanted own-mesh piece — the fit its fit on the wanted shape is derived from —
    or None without one."""
    from app.core import base_body, garment_store
    from app.core.outfit_options import CLOSED, OPEN
    base_sha = base_body.base_model_sha256(character_name, wanted.bsig)
    state = OPEN if item_id in wanted.open else CLOSED
    base_fit = garment_store.accepted_fit(character_name, item_id, base_model_sha=base_sha, profile=profile,
                                          state=state) if base_sha else None
    if base_fit is None:
        return None
    parsed = garment_store.parse_name(Path(base_fit[0]))
    return (base_fit, parsed[1]) if parsed else None


def refit_refused(character_name: str, item_ids: Optional[List[str]] = None) -> Dict[str, str]:
    """Ruling A23 b: fit the pieces whose fit on the wanted body shape is refused (``figure.Figure.fit_refused``
    of the figure delivered now; ``item_ids`` narrows them) once more — the cached refusal is dropped first, the
    fit runs on the CPU (``garments.body_fit``, which records a refusal again). Item -> reason of those refused
    again ({} when every one fits now)."""
    from app.core import garment_store, garments
    profile, wanted, delivered, _items = _now(character_name)
    still: Dict[str, str] = {}
    for item_id in sorted(delivered.fit_refused):
        if item_ids is not None and item_id not in item_ids:
            continue
        found = _refused_fit_of(character_name, item_id, wanted, profile)
        if found is None:
            continue
        base_fit, fsig = found
        garment_store.clear_failure_on_body(character_name, item_id, fsig, wanted.shape)
        result = garments.body_fit(character_name, item_id, body_id=wanted.shape,
                                   body_sha=garments.body_sha256(character_name, wanted.shape), base_fit=base_fit,
                                   profile=profile, build=True)
        if result.get("fit") is None:
            still[item_id] = str(result.get("error") or "not fitted on this body")
            logger.info("Build %s: the re-fit of %s on %s was refused again: %s", character_name, item_id,
                        wanted.shape, still[item_id])
        else:
            logger.info("Build %s: the re-fit of %s on %s was accepted", character_name, item_id, wanted.shape)
    from app.core import figure
    figure.invalidate()
    return still


#: The run reason of a "Re-fit" (``refit``): the worker runs ``_run_refit`` for it, never a Build.
REFIT_REASON = "refit"
#: The steps a "Re-fit" runs (Ruling FR-I2): the CPU refit of the piece and the CPU assembly — never a hub step.
REFIT_STEPS = frozenset({"fits", "assemble"})
#: ``refit``'s refusal while a Build of the character runs (it would re-fit and assemble itself).
REFIT_BUILD_RUNNING = "A Build runs for this character now — Re-fit after it"
#: A Re-fit whose fit was accepted while hub steps are due (Ruling FR-I2): they stay due for Build, nothing is
#: assembled (the figure built before stays served).
REFIT_DUE = "Fit accepted — not assembled: {steps} still due — Build to finish"
#: A Re-fit whose fit was accepted while views of the figure are missing: their render is hub work (FR-I2).
REFIT_VIEWS_DUE = "views of the figure"


def refit(character_name: str, item_id: str) -> Dict[str, Any]:
    """The Figure tab's "Re-fit" of a piece whose fit on the body shape was refused (Rulings A23 b, FR-I2):
    a run of its own in the character's Build worker (``_run_refit``) that, under the ``build_lock`` (FR-minors),
    drops the cached refusal, fits the piece on the CPU and — accepted, and no hub step due — assembles the
    figure on the CPU. It never starts a hub step: what is due stays due for Build. ``{"status": "started"}``;
    ``"building"`` while a Build of the character runs (``REFIT_BUILD_RUNNING``), ``"base_busy"`` while a base
    step is in flight (Ruling A26 a), ``"off"`` / ``"failed"`` as ``start``; ValueError when the piece's fit is
    not refused."""
    busy = base_step_in_flight(character_name)
    if busy:
        # Ruling A26 a: a click — refused naming the base step (nothing cleared).
        return {"status": "base_busy", "reason": BASE_STEP_RUNNING.format(step=busy)}
    try:
        profile = _read_profile(character_name)
    except Exception as e:  # noqa: BLE001 — recorded like a Build's start
        return _record_unread(character_name, REFIT_REASON, e)
    if not on_pipeline(character_name, profile=profile):
        return {"status": "off", "reason": OFF_PIPELINE}
    from app.core import figure
    _wanted, delivered = figure._delivered(character_name, profile=profile)
    if item_id not in delivered.fit_refused:
        raise ValueError(f"{_item_name(item_id)}: its fit on the body shape is not refused")
    with _lock:
        if character_name in _active:
            return {"status": "building", "reason": REFIT_BUILD_RUNNING}
        _queues[character_name] = deque([(REFIT_REASON, True)])
        _refit_items[character_name] = item_id
        _active.add(character_name)
        _current[character_name] = {"reason": REFIT_REASON, "step": None, "steps": []}
    threading.Thread(target=_worker, args=(character_name,), daemon=True,
                     name=f"figure-refit-{character_name}").start()
    logger.info("Re-fit %s of %s started", item_id, character_name)
    return {"status": "started"}


def _refit_due(character_name: str, steps: List[Step], delivered, signature: str) -> List[str]:
    """What keeps a Re-fit from assembling (Ruling FR-I2): the labels of the runnable automatic steps that are
    not ``REFIT_STEPS`` (hub work, they stay due for Build) and the figure's views when one is missing (the
    assembly would render it — ``base_body.ensure_figure_views``)."""
    from app.core import base_body
    due = [s.label for s in steps if s.name not in REFIT_STEPS]
    if any(s.name == "assemble" for s in steps) and not due and (
            _views_missing(character_name, delivered, signature)
            or not all(base_body.dressed_image(character_name, v, signature, delivered.bsig)
                       for v in base_body.dressed_views())):
        due.append(REFIT_VIEWS_DUE)
    return due


def _run_refit(character_name: str, item_id: str) -> None:
    """The Re-fit run (``refit``; the worker holds the ``build_lock``): the piece's re-fit
    (``refit_refused`` — the cached refusal is dropped HERE, under the lock), then the automatic plan's ``fits``
    and ``assemble`` steps only, both CPU, and only when no other step is due; else nothing is assembled and
    ``state()['failed']['assemble']`` says what Build still has to do (``REFIT_DUE``)."""
    from app.core import figure
    from app.core.timeutils import utc_now_iso
    label = f"Re-fit · {character_name} ({_item_name(item_id)})"
    queue, task_id = _tracked(character_name, label)
    failed: Dict[str, Dict[str, Any]] = {}
    skipped: List[str] = []
    try:
        try:
            still = refit_refused(character_name, [item_id])
        except Exception as e:  # noqa: BLE001 — the run reports, never raises
            logger.exception("Re-fit %s of %s failed", item_id, character_name)
            still = {item_id: str(e) or type(e).__name__}
        if still:
            failed["fits"] = {"error": REFIT_REFUSED.format(
                items="; ".join(f"{_item_name(i)}: {r}" for i, r in sorted(still.items()))), "item_id": item_id}
            skipped.append("assemble")
            return
        profile = _read_profile(character_name)
        wanted, delivered = figure._delivered(character_name, profile=profile)
        steps = _runnable([s for s in plan(character_name, profile=profile, explicit=False,
                                           resolved=(wanted, delivered)) if not s.manual], False)
        due = _refit_due(character_name, steps, delivered, wanted.signature)
        if due:
            failed["assemble"] = {"error": REFIT_DUE.format(steps="; ".join(due)), "item_id": item_id}
            skipped.extend(s.name for s in steps if s.name in REFIT_STEPS and s.name != "assemble")
            logger.info("Re-fit %s of %s: fit accepted, not assembled — due for Build: %s", item_id,
                        character_name, "; ".join(due))
            return
        for step in steps:
            with _lock:
                if character_name in _current:
                    _current[character_name]["step"] = {**step.as_dict(), "index": 1, "count": len(steps)}
            error = _run_step(character_name, step, False)
            if error:
                failed[step.name] = {"error": error, "item_id": step.item_id}
                break
    except Exception as e:  # noqa: BLE001 — a worker reports, never raises
        logger.exception("Re-fit %s of %s failed", item_id, character_name)
        failed.setdefault("fits", {"error": str(e) or type(e).__name__, "item_id": item_id})
    finally:
        with _lock:
            _last[character_name] = {"failed": failed, "skipped": skipped, "reason": REFIT_REASON,
                                     "finished_at": utc_now_iso(), "superseded": None}
        if queue is not None and task_id:
            try:
                queue.track_finish(task_id, error="; ".join(f"{k}: {v['error']}" for k, v in failed.items()))
            except Exception:  # noqa: BLE001
                logger.debug("Re-fit track %s not finished", task_id, exc_info=True)


#: The run reason of a "Paint now" (Ruling A148, ``paint``): the worker runs ``_run_paint``, never a Build.
PAINT_REASON = "paint"
#: ``paint``'s refusal while a Build runs (it paints itself).
PAINT_BUILD_RUNNING = "A Build runs for this character now — it paints too"
#: ``paint``'s refusal when the plan needs hub work first (the steps named).
PAINT_HUB_DUE = "Needs hub work first: {steps} — Build runs it"
#: ``paint``'s refusal when nothing is due.
PAINT_NOTHING = "The painted texture is current"


def paint_steps(character_name: str, *, profile: Optional[Dict[str, Any]] = None,
                resolved: Optional[Tuple[Any, Any]] = None) -> Tuple[List[Step], List[Step]]:
    """``(cpu, hub)`` of the automatic plan (Ruling A148): the CPU steps a "Paint now" runs — a texture step with 0
    hub jobs (its views are stored), the fits, the assembly — and every other runnable step (hub work, or a step
    with an unknown cost), which keeps "Paint now" disabled. Read-only."""
    planned = plan(character_name, profile=profile, explicit=False, resolved=resolved)
    steps = _runnable([s for s in planned if not s.manual], False)
    cpu = [s for s in steps if s.name in REFIT_STEPS or (s.name == "texture" and s.jobs == 0)]
    # A manual step (the plain body, a mesh made again) blocks too: only a Build you start runs it.
    return cpu, [s for s in planned if s.manual] + [s for s in steps if s not in cpu]


def paint(character_name: str) -> Dict[str, Any]:
    """The painted piece dialog's "Paint now" (Ruling A148): a run of its own in the character's Build worker that
    runs only the CPU steps of ``paint_steps`` (the repaint with the stored painted body and the colours, then the
    assembly) — never a hub step. ``{"status": "started"}``; ``"building"`` / ``"base_busy"`` / ``"hub_due"`` /
    ``"current"`` / ``"off"`` with ``reason``."""
    busy = base_step_in_flight(character_name)
    if busy:
        return {"status": "base_busy", "reason": BASE_STEP_RUNNING.format(step=busy)}
    try:
        profile = _read_profile(character_name)
    except Exception as e:  # noqa: BLE001 — recorded like a Build's start
        return _record_unread(character_name, PAINT_REASON, e)
    if not on_pipeline(character_name, profile=profile):
        return {"status": "off", "reason": OFF_PIPELINE}
    cpu, hub = paint_steps(character_name, profile=profile)
    if hub:
        return {"status": "hub_due", "reason": PAINT_HUB_DUE.format(steps="; ".join(s.label for s in hub))}
    if not cpu:
        return {"status": "current", "reason": PAINT_NOTHING}
    with _lock:
        if character_name in _active:
            return {"status": "building", "reason": PAINT_BUILD_RUNNING}
        _queues[character_name] = deque([(PAINT_REASON, True)])
        _active.add(character_name)
        _current[character_name] = {"reason": PAINT_REASON, "step": None, "steps": []}
    threading.Thread(target=_worker, args=(character_name,), daemon=True,
                     name=f"figure-paint-{character_name}").start()
    logger.info("Paint now of %s started", character_name)
    return {"status": "started"}


def _run_paint(character_name: str) -> None:
    """The "Paint now" run (``paint``; the worker holds the ``build_lock``): re-plans and runs the CPU steps only,
    when still no hub step is due; else nothing runs and ``state()['failed']['assemble']`` says why."""
    from app.core.timeutils import utc_now_iso
    queue, task_id = _tracked(character_name, f"Paint · {character_name}")
    failed: Dict[str, Dict[str, Any]] = {}
    try:
        cpu, hub = paint_steps(character_name, profile=_read_profile(character_name))
        if hub:
            failed["assemble"] = {"error": PAINT_HUB_DUE.format(steps="; ".join(s.label for s in hub)), "item_id": ""}
            return
        for index, step in enumerate(cpu, 1):
            with _lock:
                if character_name in _current:
                    _current[character_name]["step"] = {**step.as_dict(), "index": index, "count": len(cpu)}
            error = _run_step(character_name, step, False)
            if error:
                failed[step.name] = {"error": error, "item_id": step.item_id}
                break
    except Exception as e:  # noqa: BLE001 — a worker reports, never raises
        logger.exception("Paint of %s failed", character_name)
        failed.setdefault("assemble", {"error": str(e) or type(e).__name__, "item_id": ""})
    finally:
        with _lock:
            _last[character_name] = {"failed": failed, "skipped": [], "reason": PAINT_REASON,
                                     "finished_at": utc_now_iso(), "superseded": None}
        if queue is not None and task_id:
            try:
                queue.track_finish(task_id, error="; ".join(f"{k}: {v['error']}" for k, v in failed.items()))
            except Exception:  # noqa: BLE001
                logger.debug("Paint track %s not finished", task_id, exc_info=True)


def _run_assemble(character_name: str, step: Step, explicit: bool = False) -> str:
    """The outfit model of the figure delivered now (Ruling A119: the newest body, the ready pieces on it, the
    rest left off), then the garment assembly — CPU only."""
    from app.core import base_body, garment_assembly
    from app.core import model3d
    _profile, wanted, _delivered, _items = _now(character_name)
    # A166: the painted region and the side views need the covered variant (it shares the unrigged source's UVs);
    # a variant that failed or went missing is built again here, before the outfit model is painted.
    model3d.ensure_covered_variant(character_name)
    views = base_body.ensure_figure_views(character_name, wanted.signature)
    if views is not None and not views.get("ok"):
        return str(views.get("error") or "views failed")
    error = _outfit_model(character_name, wanted.signature)
    if not error:
        base_body.clear_assemble_refusal(character_name, wanted.signature)
        garment_assembly.schedule(character_name, wanted.signature)
    elif base_body.outfit_refusal(character_name, wanted.signature) == error:
        # Ruling A61: the same inputs would be refused again — recorded for the figure delivered NOW, the one the
        # next plan judges; an automatic Build waits for a person or a change of the inputs.
        base_body.record_assemble_refusal(character_name, wanted.signature, _now(character_name)[2], error)
    return error


_RUNNERS: Dict[str, Callable[[str, Step, bool], str]] = {
    "plain_body": _run_plain_body, "base_repair": _run_base_repair, "tip_smoothing": _run_tip_smoothing,
    "shape": _run_shape, "pieces": _run_pieces, "template": _run_template,
    "hair": _run_hair, "texture": _run_texture, "fits": _run_fits, "assemble": _run_assemble,
    "collision": _run_collision}


# --- The Figure tab's payload ----------------------------------------------------------

#: The note of a worn piece the served figure does not carry (Ruling A75).
NOT_ON_FIGURE = "Not on the figure shown now"


def _not_on_figure(served_state: Optional[Dict[str, Any]], changes: List[Dict[str, Any]],
                   worn: List[Dict[str, Any]]) -> None:
    """The rows of a piece the served figure lacks (``_served_state`` ``missing``, not only pending) without a
    reason of their own say so (``NOT_ON_FIGURE``, Ruling A75)."""
    gone = {m["item_id"] for m in (served_state or {}).get("missing") or [] if not m.get("pending")}
    if not gone:
        return
    for change in changes:
        if change.get("key") in gone and not change.get("note"):
            change["note"] = NOT_ON_FIGURE
    for row in worn:
        if row.get("item_id") in gone and not row.get("note"):
            row["note"] = NOT_ON_FIGURE


#: The hair row's notes while the hair wanted in the body waits for the plain body's rebuild (ruling F13 a):
#: the worn HairDeck hair stands in, or (no HairDeck fit) the plain body is bald.
HAIR_WAITS_HAIRDECK = "Shown with its HairDeck hair until the plain body is rebuilt with the hair"
HAIR_WAITS_BALD = "Shown bald until the plain body is rebuilt with the hair"
#: The hair row's note while another body hairstyle waits for its body shape (D4).
HAIR_WAITS_SHAPE = "Shown with the plain body's hair until this hairstyle's body shape is built"


def _hair_row(character_name: str, profile: Dict[str, Any], wanted, delivered,
              failed: Dict[str, Dict[str, Any]], running: bool) -> Dict[str, Any]:
    """The Figure tab's hair row: ``{name, item_id, mode, state, note,
    rebuild}`` of the worn hairstyle (plan Task 13: ``name`` / ``item_id``
    the hairstyle, ``""`` when none is worn; ``mode`` its mode) —
    ``rebuild`` True when the hair is wanted in the body and only the plain
    body's rebuild puts it there (ruling F13 a; the row's ``jobs`` are then
    that step's)."""
    from app.core import figure, garment_hair
    item = garment_hair.worn_hairstyle(character_name, profile) or {}
    head = {"name": str(item.get("name") or ""), "item_id": str(item.get("id") or ""),
            "mode": garment_hair.hair_mode(character_name, profile=profile)}
    rebuild = wanted.hair == figure.HAIR_BODY and figure.hair_needs_rebuild(character_name, wanted, profile=profile)
    if (failed.get("hair") or {}).get("error"):
        return {**head, "state": "failed", "note": str(failed["hair"]["error"]), "rebuild": rebuild}
    if wanted.hair == delivered.hair and wanted.hair_style == delivered.hair_style and not rebuild:
        return {**head, "state": "ready", "note": "", "rebuild": False}
    state = "building" if running else "pending"
    if wanted.hair == figure.HAIR_BODY and rebuild:
        note = HAIR_WAITS_HAIRDECK if delivered.hair == figure.HAIR_HAIRDECK else HAIR_WAITS_BALD
        return {**head, "state": state, "note": note, "rebuild": True}
    if wanted.hair == figure.HAIR_BODY:
        return {**head, "state": state, "note": HAIR_WAITS_SHAPE, "rebuild": False}
    shown = "in the body" if delivered.hair == figure.HAIR_BODY else "bald"
    method = "HAAR" if head["mode"] == garment_hair.HAAR_MODE else "HairDeck"
    return {**head, "state": state, "note": f"Shown {shown} until its {method} mesh is built",
            "rebuild": False}


def _other_state_jobs(character_name: str, item_id: str, worn_state: str,
                      profile: Dict[str, Any]) -> Optional[int]:
    """The hub jobs of building the OTHER open / closed state's own mesh of a worn piece (the piece details'
    single action, ``garments.run_estimate(state=…)``); None when unknown."""
    from app.core import garments
    from app.core.outfit_options import CLOSED, OPEN
    try:
        estimate = garments.run_estimate(character_name, item_id, profile=profile,
                                         state=CLOSED if worn_state == OPEN else OPEN)
    except Exception:  # noqa: BLE001 — an estimate, never a failure of the payload
        logger.debug("Other-state estimate of %s/%s failed", character_name, item_id, exc_info=True)
        return None
    jobs = estimate.get("hub_jobs")
    return int(jobs) if jobs is not None else None


#: The step the Figure tab's "Regenerate mesh" of a refused piece forces (with its chain, Ruling A23 b).
REGENERATE_STEP = "mesh"


def _regenerate_jobs(character_name: str, item_id: str, profile: Dict[str, Any]) -> Optional[int]:
    """The hub jobs of "Regenerate mesh" (``garments.run_estimate(from_step=REGENERATE_STEP)``: the mesh made
    anew and everything after it — Ruling FR-minors, the button states it); None when unknown."""
    from app.core import garments
    try:
        jobs = garments.run_estimate(character_name, item_id, profile=profile,
                                     from_step=REGENERATE_STEP).get("hub_jobs")
    except Exception:  # noqa: BLE001 — an estimate, never a failure of the payload
        logger.debug("Regenerate estimate of %s/%s failed", character_name, item_id, exc_info=True)
        return None
    return int(jobs) if jobs is not None else None


def _worn_rows(character_name: str, wanted, delivered, failed: Dict[str, Dict[str, Any]],
               running: bool, profile: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """The Figure tab's worn rows. Open / closed (plan Task 11b): ``piece_state`` — ``"open"`` / ``"closed"`` for
    a closable piece, None otherwise (not the row's ``state``, which is its readiness) — and, for an own-mesh
    closable piece, ``other_state_jobs``: what building the other state's mesh costs (None: unknown or not
    applicable). ``left_out`` (Ruling A119): why a piece that is not ready is left off the figure shown. A piece whose fit on the body shape was
    refused (Ruling A31 wording): ``fit_refused`` the reason in plain words, ``fit_refused_detail`` the measured
    reasons (the tooltip), ``refused_on`` what is in that body shape ("" unknown), ``piece_broken`` whether the
    reason points at the piece itself — only then ``regenerate_jobs`` is what its "Regenerate mesh" spends
    (``_regenerate_jobs``), else None. ``accepted_by_user`` (Ruling A31, A69 — ``_accepted_by_user``): ``{step,
    on, reason, …}`` when the fit the figure uses (``on``: "Plain body" / "Body shape (…)"), its mesh or one of its
    images was refused by its checks and accepted by the user, else None."""
    from app.core import figure, fit_attempts, garment_set
    from app.core.outfit_options import CLOSED, OPEN
    from app.models import inventory
    profile = _profile_of(character_name, profile)
    piece_failures: Dict[str, str] = {}
    entry = failed.get("pieces") or {}
    if entry:
        piece_failures = dict(entry.get("items") or {entry.get("item_id"): entry.get("error")})
    rows: List[Dict[str, Any]] = []
    seen = set()
    names = (fit_attempts.shape_names(character_name, profile=profile)
             if delivered.fit_refused or not figure.is_plain(delivered.shape) else {})
    for slot, item_id in sorted(wanted.pieces.items()):
        if item_id in seen:
            continue
        seen.add(item_id)
        item = inventory.get_item(item_id) or {}
        want, have = wanted.state_of(item_id), delivered.state_of(item_id)
        failure = str(piece_failures.get(item_id) or "")
        refused = str(delivered.fit_refused.get(item_id) or "")
        words = (fit_attempts.refusal_words(character_name, item_id, delivered.fit_refused_on, refused)
                 if refused else {"text": "", "detail": "", "piece": False})
        if failure:
            state = "failed"
        elif refused:
            state = "fit_refused"   # Ruling A23 b: "Fit refused — <reason>" with Re-fit / Regenerate mesh
        elif item_id in delivered.shown_closed:
            state = "building" if running else "pending"   # ruling F13 b: the closed mesh stands in
        elif want == have:
            state = "ready"
        elif running:
            state = "building"
        elif item_id in delivered.left_out:
            state = "left_out"
        else:
            state = "pending"
        mode = garment_set.mesh_mode_of(item) or garment_set.PAINTED
        closable = garment_set.closable_of(item)
        piece_state = (OPEN if item_id in wanted.open else CLOSED) if closable else None
        rows.append({"slot": slot, "item_id": item_id, "name": str(item.get("name") or item_id),
                     "mode": mode, "state": state,
                     "note": delivered.left_out.get(item_id) or delivered.notes.get(item_id) or "",
                     "left_out": delivered.left_out.get(item_id) or "",
                     "failure": failure, "fit_refused": words["text"], "fit_refused_detail": words["detail"],
                     "refused_on": names.get(delivered.fit_refused_on, "") if refused else "",
                     "piece_broken": bool(words["piece"]), "piece_state": piece_state,
                     "accepted_by_user": (_accepted_by_user(character_name, item_id, delivered.shape, profile, names)
                                          if mode in garment_set.OWN_MESH_MODES and not refused else None),
                     "other_state_jobs": (_other_state_jobs(character_name, item_id, piece_state, profile)
                                          if closable and mode in garment_set.OWN_MESH_MODES else None),
                     "regenerate_jobs": (_regenerate_jobs(character_name, item_id, profile)
                                         if state == "fit_refused" and words["piece"] else None),
                     "template": (_template_row(character_name, item_id, item, wanted, profile)
                                  if mode == garment_set.TEMPLATE else None)})
    return rows


def _template_row(character_name: str, item_id: str, item: Dict[str, Any], wanted,
                  profile: Dict[str, Any]) -> Dict[str, Any]:
    """A template row's ``template`` (Ruling A138): ``{params (None: none stored), source ("llm" / "user"),
    updated_at, built (the kinds draped today), state ("ready" / "missing" / "failed" / "blocked"), reason,
    built_at, metrics {wall_s, cpu_s, stretch_max, coverage, texture, pose_shapes (Rulings A141 / A142: the poses with
    a corrective shape, side suffixes folded), layered_over (Ruling A142: how many lower drapes it was draped over)},
    cost {llm_calls, hub_jobs, cpu_s}}``."""
    from app.core import base_body, garment_template
    stored = garment_template.template_of(item)
    base = base_body.current_base(character_name, profile=profile)
    drape = garment_template.drape_state(character_name, item_id, base_sha=base[1] if base else "",
                                         lower=garment_template.lower_layers(wanted.own, item_id), item=item)
    record = drape["record"] or {}
    metrics = record.get("metrics") or {}
    out = {"params": garment_template.params_of(item), "source": stored.get("source") or "",
           "updated_at": stored.get("updated_at") or "", "built": list(garment_template.BUILT_KINDS),
           "state": drape["state"], "reason": drape["reason"], "built_at": record.get("created_at") or "",
           "metrics": {"wall_s": metrics.get("wall_total_s"), "cpu_s": (metrics.get("drape") or {}).get("cpu_s"),
                       "stretch_max": (metrics.get("drape") or {}).get("stretch_max"),
                       "coverage": (metrics.get("bake") or {}).get("coverage"),
                       "texture": (record.get("texture") or {}).get("source") or "",
                       "pose_shapes": garment_template.shape_targets(record.get("pose_shapes")),
                       "layered_over": len(record.get("colliders") or [])}
           if metrics else None,
           "cost": {"llm_calls": 1, "hub_jobs": 0, "cpu_s": garment_template.CPU_ESTIMATE_S}}
    return out


def _accepted_by_user(character_name: str, item_id: str, shape: str, profile: Dict[str, Any],
                      names: Dict[str, str]) -> Optional[Dict[str, Any]]:
    """A worn row's ``accepted_by_user``: ``{step, on, reason, detail, at, view}`` when a result the figure uses for
    the piece was refused by its checks and accepted by the user — its fit (Ruling A31, ``step`` "fit", ``on`` the
    body), else its mesh or an image of its chain (Ruling A69, ``garments.user_taken``: ``step`` "mesh" / the image
    step, ``view`` the image's view, ``on`` ""); None otherwise."""
    from app.core import fit_attempts, garments
    fit = fit_attempts.accepted_by_user(character_name, item_id, shape, profile=profile, names=names)
    if fit is not None:
        return {**fit, "step": "fit", "view": ""}
    taken = garments.user_taken(character_name, item_id, profile=profile)
    if taken is None:
        return None
    return {"step": taken["step"], "view": taken["view"], "on": "", "reason": "; ".join(taken["reasons"]),
            "detail": "\n".join(taken["reasons"]), "at": taken["at"]}


def _with_cached_failures(failed: Dict[str, Dict[str, Any]], steps: List[Step]) -> Dict[str, Dict[str, Any]]:
    """The last run's ``failed`` plus the planned chains that failed for their
    current fsig (``Step.failed``), in the same shape — a cached failure shows
    as "failed — Retry" before any Build ran."""
    out = {name: {**entry, **({"items": dict(entry["items"])} if entry.get("items") else {})}
           for name, entry in failed.items()}
    for step in steps:
        if not step.failed:
            continue
        entry = out.get(step.name)
        if entry is None:
            out[step.name] = {"error": step.failed, "item_id": step.item_id}
        elif step.item_id != entry.get("item_id"):
            entry.setdefault("items", {entry.get("item_id"): entry.get("error")}).setdefault(step.item_id,
                                                                                           step.failed)
    return out


def _served_url(character_name: str) -> Optional[str]:
    from urllib.parse import quote
    from app.core import model3d
    try:
        return model3d.versioned_model_urls(
            character_name, f"/characters/{quote(character_name, safe='')}/model3d/file").get("url")
    except Exception:  # noqa: BLE001 — the preview is optional
        logger.debug("Served model URL of %s unreadable", character_name, exc_info=True)
        return None


def _served_built_at(character_name: str) -> Optional[str]:
    """When the model ``_served_url`` serves was built (Ruling UI3 a: the 3D preview's caption) — the
    delivered bytes (the garment assembly when it is current), ``model_overview.built_at``; None without one."""
    from app.core import garment_assembly, model3d, model_overview
    try:
        full, _, _ = model3d.find_model3d_serving_tier(character_name, "")
        if full is None:
            return None
        return model_overview.built_at(garment_assembly.served(character_name, full, model3d.FULL_TIER))
    except Exception:  # noqa: BLE001 — the caption is optional
        logger.debug("Served model stamp of %s unreadable", character_name, exc_info=True)
        return None


# What the Figure tab's viewer says about the figure it shows (Ruling A75; the character-tab checklist point 8: a
# light and the reason in plain words). English, translated by the client (de.json keys).
SERVED_COMPLETE = "Shows the outfit worn now"
SERVED_WITHOUT = "Not the whole outfit"
SERVED_WITHOUT_REASON = "Shown without {pieces}: this is not the outfit worn now until the missing pieces are on it."
SERVED_ASSEMBLING = "Putting the pieces on"
SERVED_ASSEMBLING_REASON = "Shown without {pieces} for a moment: the CPU puts them on now (no hub job)."
#: Ruling A119: the outfit model of the figure delivered now is not built yet — the newest plain body is shown with
#: the ready own-mesh pieces put on; every painted piece is left off until its texture is built.
SERVED_PLAIN = "Plain body"
SERVED_PLAIN_REASON = "The model of the outfit worn now is not built yet: the plain body is shown with the pieces that are ready."
#: A missing piece's reason (``missing[].reason``); a refusal's measured text goes into ``missing[].detail``.
PIECE_REFUSED = "Its fit on this body was refused"
PIECE_NO_FIT = "It has no accepted fit on this body"
PIECE_REFUSED_PLAIN = "Its fit on the base body was refused"
PIECE_PENDING = "Its fit on this body is made now"
PIECE_NO_TEXTURE = "Its texture is not built yet"


def _plain_fit_refusal(character_name: str, item_id: str, profile: Optional[Dict[str, Any]]) -> str:
    """The recorded refusal (its error text) of the piece's fit on the plain body (``fit_attempts.fit_status``) — a
    piece without that fit has none on a body shape either —, "" without one."""
    from app.core import fit_attempts
    try:
        failure = fit_attempts.fit_status(character_name, item_id, "", profile=profile).get("failure")
    except Exception:  # noqa: BLE001 — the reason falls back to the general one
        logger.debug("Plain fit status of %s/%s unreadable", character_name, item_id, exc_info=True)
        return ""
    error = str((failure or {}).get("error") or "") if isinstance(failure, dict) else ""
    return error


def _served_state(character_name: str, *, profile: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """What the figure the viewer shows (``_served_url``: ``model3d.find_model3d_serving`` and the file
    ``garment_assembly.served`` delivers for it) is, compared with the outfit worn now — so a figure that lacks a
    piece is never shown as if it were the outfit (Ruling A75):
    ``{light, state, reason, pieces, notes, missing: [{item_id, name, reason, detail, pending}]}`` — ``reason`` may hold
    ``{pieces}`` (the missing pieces' names, joined), filled in by the client after translating; ``notes`` further
    sentences —, None without a served model.

    - ``match`` "base" (Ruling A119: the outfit model of the figure delivered now is not built yet, the plain body
      is served with the ready own-mesh pieces put on, ``garment_assembly.bare_meta_of``) → yellow
      ``SERVED_PLAIN``; ``missing`` lists every painted piece (``PIECE_NO_TEXTURE``) and the own-mesh pieces the
      served bytes do not carry, as below;
    - an own-mesh piece the served model's texture leaves to its garment (``effective_mesh_items`` of its bare
      sidecar) that the served bytes do not carry (the assembled sidecar's ``garments``; none when the bare file is
      served) → ``missing``, each with its reason (``detail``: a refusal's measured text): a fit refused on the model's body (``garment_assembly._wanted``
      ``left_off``, read only — ``PIECE_REFUSED``), a fit refused on the plain body already (``PIECE_REFUSED_PLAIN``,
      ``_plain_fit_refusal``), a fit still to be made (``pending``, ``PIECE_PENDING``) or no accepted fit there
      (``PIECE_NO_FIT``). Any not
      pending → red ``SERVED_WITHOUT`` (the stored model stays served: the serving path re-assembles it without the
      piece); only pending → blue ``SERVED_ASSEMBLING``;
    - else green ``SERVED_COMPLETE``.
    Never raises (None on failure)."""
    from app.core import garment_assembly, model3d
    from app.models.inventory import get_item
    try:
        path, match = model3d.find_model3d_serving(character_name)
        if path is None:
            return None
        notes: List[str] = []
        bare_meta = garment_assembly.bare_meta_of(character_name, path.parent, path.stem)
        worn = (profile or {}).get("equipped_mesh_pieces")
        hair = {str(v) for v in worn.values() if v} if isinstance(worn, dict) else set()
        clothing = sorted(set(garment_assembly.effective_mesh_items(bare_meta)) - hair)
        missing: List[Dict[str, Any]] = []
        if clothing:
            served = garment_assembly.served(character_name, path, model3d.FULL_TIER)
            carried = (set(garment_assembly.read_sidecar(Path(served)).get("garments") or {})
                       if served is not None and Path(served) != Path(path) else set())
            left_off: Dict[str, str] = {}
            wanted = {g["item_id"]: g for g in garment_assembly._wanted(character_name, profile,
                                                                        bare_meta=bare_meta, left_off=left_off)}
            for item_id in clothing:
                if item_id in carried:
                    continue
                pending, detail = item_id in wanted, ""
                if item_id in left_off:
                    reason, detail = PIECE_REFUSED, left_off[item_id]
                elif pending:
                    reason = PIECE_PENDING
                elif detail := _plain_fit_refusal(character_name, item_id, profile):
                    reason = PIECE_REFUSED_PLAIN
                else:
                    reason = PIECE_NO_FIT
                missing.append({"item_id": item_id, "name": str((get_item(item_id) or {}).get("name") or item_id),
                                "reason": reason, "detail": detail, "pending": pending})
        if match == "base":
            from app.core import figure
            fig = figure.delivered_figure_cached(character_name, profile=profile)
            missing[:0] = [{"item_id": item_id, "name": str((get_item(item_id) or {}).get("name") or item_id),
                            "reason": PIECE_NO_TEXTURE, "detail": "", "pending": False} for item_id in fig.painted]
            return {"light": "yellow", "state": SERVED_PLAIN, "reason": SERVED_PLAIN_REASON,
                    "pieces": ", ".join(m["name"] for m in missing), "notes": [], "missing": missing}
        pieces = ", ".join(m["name"] for m in missing)
        if missing and not all(m["pending"] for m in missing):
            return {"light": "red", "state": SERVED_WITHOUT, "reason": SERVED_WITHOUT_REASON, "pieces": pieces,
                    "notes": notes, "missing": missing}
        if missing:
            return {"light": "blue", "state": SERVED_ASSEMBLING, "reason": SERVED_ASSEMBLING_REASON,
                    "pieces": pieces, "notes": notes, "missing": missing}
        return {"light": "green", "state": SERVED_COMPLETE, "reason": "", "pieces": "", "notes": [], "missing": []}
    except Exception:  # noqa: BLE001 — a caption of the viewer, never a failure of the poll
        logger.exception("Served figure state of %s unreadable", character_name)
        return None


def _served_foot_pose(character_name: str) -> Optional[Dict[str, Any]]:
    """The ``foot_pose`` of the model ``_served_url`` serves (Ruling A52): the assembly sidecar's record when the
    assembly with a fitted shoe is served (``garment_assembly.served_foot_pose``), else None. The Figure tab hands
    it to its viewer, as ``GET …/model3d`` hands ``model.foot_pose`` to the 3D model tab: a served shoe is
    bound with its foot turned BACK by the fit's extension (``footwear_fit`` step 7), so a viewer that shows it
    without the record shows the shoe bent up at the front and its heel through the floor. The viewer applies it
    only to a model carrying exactly that shoe (``footPoseMatches``), so a stale pose beside a newer file is a
    no-op, never a wrong turn."""
    from app.core import garment_assembly, model3d
    try:
        full, _, _ = model3d.find_model3d_serving_tier(character_name, "")
        if full is None:
            return None
        return garment_assembly.served_foot_pose(character_name, full, model3d.FULL_TIER)
    except Exception:  # noqa: BLE001 — the pose is optional, the viewer then shows the bind pose
        logger.debug("Served foot pose of %s unreadable", character_name, exc_info=True)
        return None


def _item_jobs(steps: List[Step], name: str, item_id: str) -> Optional[int]:
    """The planned hub jobs of a piece's (``pieces``, by item) or the hair's
    chain step: 0 when nothing of it is planned, None when unknown."""
    for step in steps:
        if step.name == name and (not item_id or step.item_id == item_id):
            return step.jobs
    return 0


def _with_jobs(changes: List[Dict[str, Any]], steps: List[Step]) -> List[Dict[str, Any]]:
    """``changes`` (``figure.pending_changes``) each with the ``jobs`` of the
    plan step that builds it (fix round T12-F1, F13 a/b — the change row
    names its cost): a piece or its open / closed state = its ``pieces``
    chain, the hair = its ``hair`` chain or, wanted in the body on a bald
    plain body, the plain body's rebuild; the plain body = its step. None:
    unknown; 0: nothing of it planned."""
    from app.core import figure
    out = []
    for change in changes:
        key = str(change.get("key") or "")
        if key == figure.BODY_KEY:
            jobs = _item_jobs(steps, "plain_body", "")
        elif key == figure.HAIR_KEY:
            jobs = _item_jobs(steps, "plain_body" if change.get("note") == figure.HAIR_REBUILD else "hair", "")
        else:
            item_id = key[:-len(figure.STATE_KEY_SUFFIX)] if key.endswith(figure.STATE_KEY_SUFFIX) else key
            jobs = _item_jobs(steps, "pieces", item_id)
        out.append({**change, "jobs": jobs})
    return out


def _plain_jobs(character_name: str, bsig: str) -> Dict[str, Any]:
    """What the single actions on the plain body cost (the Figure tab's Body
    details write it under each button): ``view`` (a side or back view),
    ``front`` (the front's Regenerate: with the skin detail step while it
    applies to the front made now — ``base_skin.applies``, never for one made
    from the full-body reference, Ruling A92), ``front_full_body`` (the same
    for a front made from the full-body reference — what a new full-body
    reference makes due), ``model`` (its mesh
    run, ``model3d.mesh_hub_stages``), ``after_front`` (what the next
    Build then rebuilds after a new front: the three other views, which edit
    the front, and the model) and ``model_followup`` (Ruling UI3c: what a
    step that changes a base view IN PLACE — the skin step keeps the front's
    ``created_at``, so the other views stay current — or a single side view
    makes stale: the stored base model, rebuilt by the next Build — ``{jobs,
    stages}`` from the same ``base_rebuild_steps``; None while no base model
    is stored, nothing goes stale then). None when not computable."""
    from app.core import base_body, base_skin, model3d
    try:
        others = [v for v in base_body.BASE_VIEWS if v != "front"]
        model_steps = base_body.base_rebuild_steps(character_name, {"signature": bsig, "views": [], "model": True})
        stored = model3d.find_model3d(character_name, bsig) is not None
        return {"view": base_body.BASE_VIEW_JOBS,
                "front": base_body.BASE_VIEW_JOBS + (base_body.SKIN_STEP_JOBS
                                                     if base_skin.applies(character_name) else 0),
                "front_full_body": base_body.BASE_VIEW_JOBS + (
                    base_body.SKIN_STEP_JOBS if base_skin.applies(character_name, source=base_body.SOURCE_FULL_BODY)
                    else 0),
                "model": len(model3d.mesh_hub_stages(character_name, bsig)),
                "after_front": sum(jobs for _step, jobs in base_body.base_rebuild_steps(
                    character_name, {"signature": bsig, "views": others, "model": True})),
                "model_followup": ({"jobs": sum(jobs for _step, jobs in model_steps),
                                    "stages": [step for step, _jobs in model_steps]} if stored else None)}
    except Exception:  # noqa: BLE001 — an estimate, never a failure
        logger.debug("Plain body job counts of %s not computable", character_name, exc_info=True)
        return {"view": None, "front": None, "front_full_body": None, "model": None, "after_front": None,
                "model_followup": None}


# --- The Base body tab's "Run all" (Task UI1, rule R1) ----------------------------------------------------------
#
# ONE button that brings the plain (base) body up to date and skips every step that is current — the same
# judgement the Build and the ``base_refresh`` improvement use, never a second one:
#
# 1. ``plain_body`` — ``base_body.base_refresh_plan(missing=True)`` has views or the model: exactly the Build's
#    ``plain_body`` step (``_run_plain_body`` through ``_run_step``: the stale / missing views, the skin step with
#    the front, then the model — whose run applies the face cleanup and the face retexture as switched on);
#    cost ``base_body.base_rebuild_cost``.
# 2. else ``face_cleanup`` — the stored base mesh is not cleaned at the current version while the switch is on
#    (``model3d.face_cleanup_state`` ``can_reapply``): ``model3d.trigger_face_cleanup``, which rebuilds what follows.
# 3. else ``face_retexture`` — "Improve face before rigging" is on and the stored base model has no face retexture
#    (none recorded, or the last one failed), or the face values saved since differ from the ones it ran with
#    (Task UI2: the record's ``settings`` fingerprint): ``model3d.trigger_face_retexture`` with the remembered
#    settings.
# 4. else ``mesh_repair`` — the stored base model's mesh repair is older than its saved settings or the repair
#    version (``model3d.mesh_repair_state`` ``due``, Ruling A34): ``base_mesh_repair.start_repair`` — local, no hub
#    job; it rebuilds the extension rig on the repaired mesh, so it includes kinds 5 and 6.
# 5. else ``tip_smoothing`` — the stored base model carries a switched-on ``pair_tip`` group but no tip smoothing
#    record of the current version (``extension_tip.model_tip_smoothing_due``, Ruling A43): the extension rebuild
#    (``extension_tip.start_tip_rebuild``) — local, no hub job; it includes kind 6.
# 6. else ``extension_rig`` — a tip setting saved since (Task UI2) makes the stored base model's extension rig older
#    than its settings (``model3d.extension_settings_changed``): ``extension_tip.start_tip_rebuild`` — local, no hub
#    job.
# 7. else ``collision`` — a channel setting saved since (the Channels panel stores only) leaves a stored model's
#    collision channels not current (``collision.channels_due``): ``collision.recompute_character(apply_channels=
#    True)`` in a worker thread — local, no hub job. The kinds above refit the base model's set, which resolves its
#    channels; the outfit models it leaves due stay listed here on the next poll.
# 8. else nothing: "Everything is current".
#
# Each earlier kind includes the later ones (a new model, a cleanup and a face retexture all re-rig, and the rig
# builds the extension bones with the saved settings), so one kind per click is enough.
# The single steps (a view's / the model's Regenerate, "Run skin step", the face dialogs, a tip panel's Rebuild)
# stay the forced re-runs (rule R2); the settings (the face switches and values, the tip settings) are saved on
# their own (rule R3).

#: ``base_run_all`` kinds.
RUN_ALL_PLAIN, RUN_ALL_CLEANUP, RUN_ALL_FACE = "plain_body", "face_cleanup", "face_retexture"
RUN_ALL_EXTENSION = "extension_rig"
RUN_ALL_REPAIR = "mesh_repair"
RUN_ALL_TIP = "tip_smoothing"
RUN_ALL_COLLISION = "collision"
#: The collision channels are applied locally (CPU); its label in the step list.
COLLISION_STEP = "collision"
#: The tip smoothing runs inside the extension rebuild (local); its label in the step list (Ruling A43).
TIP_STEP = "tip_smoothing"
#: The base mesh repair is local (CPU); its label in the step list.
REPAIR_STEP = "repair"
#: The extension rebuild is local (CPU); its label in the step list.
EXTENSION_STEP = "extension"
#: ``start_base_run_all``'s refusals.
RUN_ALL_BUILD_RUNNING = ("A Build runs for this character now — it refreshes the base body itself when that is "
                         "outdated; Run all again after it")
RUN_ALL_BUSY = "A base view render or a 3D run of this character is going — Run all again after it"
#: The face cleanup itself is local (CPU); its label in the step list.
CLEANUP_STEP = "cleanup"

_run_all_active: set = set()
_run_all_last: Dict[str, Dict[str, Any]] = {}


#: ``_face_retexture_pending``'s answers: nothing due, no (or a failed) face retexture, the saved face values
#: differ from the ones the stored face retexture ran with (Task UI2: rule R3 → R1).
FACE_CURRENT, FACE_MISSING, FACE_CHANGED = "", "missing", "changed"


def _face_retexture_pending(character_name: str, bsig: str) -> str:
    """Why the stored base model's face retexture is due: "Improve face before rigging" is on, the model is a
    humanoid one with its retained unrigged source, and its sidecar records no face retexture or a failed one
    (``FACE_MISSING``; ``reverted`` and ``skipped`` are decisions, not missing work), or an applied one whose
    ``settings`` fingerprint differs from the face values saved now (``FACE_CHANGED``,
    ``model3d.face_settings_fingerprint``). A record WITHOUT a fingerprint (made before Task UI2) counts as current —
    never every existing model due at once. ``FACE_CURRENT`` ("") otherwise."""
    from app.core import model3d
    if not model3d.get_model3d_options(character_name).get("face_before_rig"):
        return FACE_CURRENT
    if model3d.required_rig(character_name) != "mixamo":
        return FACE_CURRENT
    path = model3d.find_model3d(character_name, bsig)
    if path is None or not (path.parent / "unrigged" / f"{bsig}.glb").is_file():
        return FACE_CURRENT
    record = model3d._read_sidecar(path).get("face_retexture")
    if not isinstance(record, dict) or record.get("status") == "failed":
        return FACE_MISSING
    stored = str(record.get("settings") or "")
    if record.get("status") == "applied" and stored:
        now = model3d.face_settings_fingerprint(character_name)
        if now and now != stored:
            return FACE_CHANGED
    return FACE_CURRENT


def _face_stages(character_name: str, bsig: str, follow_up: str) -> List[str]:
    """The hub stages of a face redo on the stored base mesh: a re-rig alone, or the face stages of a fresh
    mesh run (``model3d.mesh_hub_stages`` without ``mesh``: [upscale,] face, rig)."""
    from app.core import model3d
    if follow_up == "rerig":
        return ["rig"]
    stages = [stage for stage in model3d.mesh_hub_stages(character_name, bsig) if stage != "mesh"]
    # A163: a face view the run renders first counts as its own (image) job.
    from app.core.face_retexture import face_view_due
    return stages if "face" in stages else [*(["face view"] if face_view_due(character_name) else []), "face", "rig"]


def base_run_all(character_name: str, *, profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """What the Base body tab's "Run all" runs now (block comment above): ``{kind, steps: [{name, jobs}],
    hub_jobs, note, running, last}`` — ``kind`` "" when every step is current (``hub_jobs`` 0) or the plan
    could not be read (``hub_jobs`` None, ``note`` says why); ``steps`` in run order with their first-attempt
    hub jobs (``view front``, ``skin front``, ``mesh``, ``upscale``, ``face``, ``rig``, ``cleanup``, ``repair``,
    ``tip_smoothing``, ``extension`` and ``collision`` — the last five local; ``tip_smoothing`` only on a base with a
    switched-on ``pair_tip`` group); ``face_due`` why a face retexture is planned ("missing" / "changed",
    else ""); ``running`` while a Run all of the character goes, ``last`` its last outcome
    (``{error, finished_at}``, None before the first). Read-only."""
    from app.core import base_body, model3d
    with _lock:
        state_now = {"running": character_name in _run_all_active,
                     "last": dict(_run_all_last[character_name]) if character_name in _run_all_last else None}
    out: Dict[str, Any] = {"kind": "", "steps": [], "hub_jobs": 0, "note": "", "face_due": "", **state_now}
    try:
        profile = _profile_of(character_name, profile)
        if not on_pipeline(character_name, profile=profile):
            return out
        refresh = base_body.base_refresh_plan(character_name, profile=profile, missing=True)
        if refresh.get("views") or refresh.get("model"):
            cost = base_body.base_rebuild_cost(character_name, profile=profile, plan=refresh)
            return {**out, "kind": RUN_ALL_PLAIN, "hub_jobs": cost.get("hub_jobs"), "note": str(cost.get("note") or ""),
                    "steps": [{"name": step, "jobs": jobs} for step, jobs in cost.get("steps") or []]}
        bsig = str(refresh.get("signature") or "")
        cleanup = model3d.face_cleanup_state(character_name, bsig) if bsig else {}
        if cleanup.get("can_reapply"):
            stages = _face_stages(character_name, bsig, str(cleanup.get("follow_up") or "rerig"))
            return {**out, "kind": RUN_ALL_CLEANUP, "hub_jobs": len(stages),
                    "note": "face cleanup not on the stored mesh: cleanup (local) + " + " + ".join(stages),
                    "steps": [{"name": CLEANUP_STEP, "jobs": 0}] + [{"name": stage, "jobs": 1} for stage in stages]}
        face_due = _face_retexture_pending(character_name, bsig) if bsig else FACE_CURRENT
        if face_due:
            stages = _face_stages(character_name, bsig, "face_retexture")
            what = ("face values changed — not applied yet: " if face_due == FACE_CHANGED
                    else "the base model has no face retexture: ")
            return {**out, "kind": RUN_ALL_FACE, "hub_jobs": len(stages), "face_due": face_due,
                    "note": what + " + ".join(stages),
                    "steps": [{"name": stage, "jobs": 1} for stage in stages]}
        # The extension rebuild of a base with a switched-on tip group smooths its tips again (Ruling A43).
        tip = [{"name": TIP_STEP, "jobs": 0}] if _has_tip_smoothing(character_name, bsig) else []
        if _mesh_repair_due(character_name, bsig):
            return {**out, "kind": RUN_ALL_REPAIR, "hub_jobs": 0,
                    "note": "base mesh not repaired with the saved settings: repair + extension rebuild (local)",
                    "steps": [{"name": REPAIR_STEP, "jobs": 0}, *tip, {"name": EXTENSION_STEP, "jobs": 0}]}
        if _tip_smoothing_due(character_name, bsig):
            return {**out, "kind": RUN_ALL_TIP, "hub_jobs": 0,
                    "note": "tip smoothing not applied to this model yet: extension rebuild (local)",
                    "steps": [*tip, {"name": EXTENSION_STEP, "jobs": 0}]}
        path = model3d.find_model3d(character_name, bsig) if bsig else None
        due_reason = model3d.extension_due_reason(character_name, path) if path is not None else ""
        if due_reason:
            return {**out, "kind": RUN_ALL_EXTENSION, "hub_jobs": 0,
                    "note": ("extension groups changed since the last build: extension rebuild (local)"
                             if due_reason == "groups" else "tip settings saved, not built yet: extension rebuild (local)"),
                    "steps": [*tip, {"name": EXTENSION_STEP, "jobs": 0}]}
        if _collision_due(character_name):
            return {**out, "kind": RUN_ALL_COLLISION, "hub_jobs": 0,
                    "note": "channel settings changed — not applied yet: collision capsules recompute (local)",
                    "steps": [{"name": COLLISION_STEP, "jobs": 0}]}
        return out
    except Exception as e:  # noqa: BLE001 — a label, never a failure of the poll
        logger.warning("Base Run all plan of %s not computable: %s", character_name, e)
        return {**out, "hub_jobs": None, "note": f"cost unknown — {e}"}


def start_base_run_all(character_name: str) -> Dict[str, Any]:
    """Start the Base body tab's "Run all": ``{"status": "started", "kind"}`` · ``"current"`` (nothing to do)
    · ``"off"`` (off the pipeline) · ``"building"`` (a Build of the character runs or holds its lock —
    ``RUN_ALL_BUILD_RUNNING``) · ``"busy"`` (a base render or a 3D run goes — ``RUN_ALL_BUSY``) · ``"failed"``
    (the profile could not be read). A face redo that its own guard refuses raises ``ValueError`` /
    ``LookupError`` (the route's 409). The plain-body step runs in a worker thread under the character's
    ``build_lock`` (a Build started meanwhile waits for it) and the 3D generation slot (``_run_step``)."""
    from app.core import base_body, model3d
    try:
        profile = _read_profile(character_name)
    except Exception as e:  # noqa: BLE001 — never "current" on an unreadable profile
        return {"status": "failed", "reason": PROFILE_UNREADABLE.format(error=str(e) or type(e).__name__)}
    if not on_pipeline(character_name, profile=profile):
        return {"status": "off", "reason": OFF_PIPELINE}
    if running(character_name):
        return {"status": "building", "reason": RUN_ALL_BUILD_RUNNING}
    with _lock:
        if character_name in _run_all_active:
            return {"status": "busy", "reason": RUN_ALL_BUSY}
    plan_now = base_run_all(character_name, profile=profile)
    kind = plan_now["kind"]
    if not kind:
        return {"status": "current"}
    bsig = base_body.base_signature(character_name, profile=profile)
    if kind == RUN_ALL_CLEANUP:
        result = model3d.trigger_face_cleanup(character_name, bsig)
        if result.get("status") == "already_running":
            return {"status": "busy", "reason": RUN_ALL_BUSY}
        return {"status": "started", "kind": kind}
    if kind == RUN_ALL_FACE:
        result = model3d.trigger_face_retexture(character_name, bsig)
        if result.get("status") == "already_running":
            return {"status": "busy", "reason": RUN_ALL_BUSY}
        return {"status": "started", "kind": kind}
    if kind == RUN_ALL_REPAIR:
        from app.core import base_mesh_repair
        if model3d.generation_running(character_name) or not base_mesh_repair.start_repair(character_name, bsig):
            return {"status": "busy", "reason": RUN_ALL_BUSY}
        return {"status": "started", "kind": kind}
    if kind in (RUN_ALL_EXTENSION, RUN_ALL_TIP):
        from app.core import extension_tip
        if model3d.generation_running(character_name) or not extension_tip.start_tip_rebuild(character_name, bsig):
            return {"status": "busy", "reason": RUN_ALL_BUSY}
        return {"status": "started", "kind": kind}
    if kind == RUN_ALL_COLLISION:
        return _start_collision_run_all(character_name)
    lock = build_lock(character_name)
    if not lock.acquire(blocking=False):
        return {"status": "building", "reason": RUN_ALL_BUILD_RUNNING}
    views = [v for v in base_body.BASE_VIEWS if v in {s["name"][5:] for s in plan_now["steps"]
                                                       if s["name"].startswith("view ")}]
    if model3d.generation_running(character_name) or any(
            s.get("running") for s in base_body.base_status(character_name).values()):
        lock.release()
        return {"status": "busy", "reason": RUN_ALL_BUSY}
    with _lock:
        _run_all_active.add(character_name)
    # The planned views count as running from THIS moment (the tab polls ``base_info``), as a view's Regenerate.
    base_body.reserve_views(character_name, views, step=base_body.RUN_ALL_STEP)
    step = Step("plain_body", "Plain body: " + str(plan_now["note"]), plan_now["hub_jobs"])

    def run() -> None:
        from app.core.timeutils import utc_now_iso
        queue, task_id = _tracked(character_name, f"Base body · {character_name} (Run all)")
        error = "Run all failed"
        try:
            error = _run_step(character_name, step, True)
        finally:
            base_body.release_views(character_name, views)
            lock.release()
            with _lock:
                _run_all_active.discard(character_name)
                _run_all_last[character_name] = {"error": error, "finished_at": utc_now_iso()}
            if queue is not None and task_id:
                try:
                    queue.track_finish(task_id, error=error)
                except Exception:  # noqa: BLE001
                    logger.debug("Run all track %s not finished", task_id, exc_info=True)
            logger.info("Base Run all %s ended%s", character_name, f": {error}" if error else "")

    try:
        threading.Thread(target=run, daemon=True, name=f"base-run-all-{character_name}").start()
    except Exception:
        # No thread, so nobody else frees what was taken above.
        base_body.release_views(character_name, views)
        lock.release()
        with _lock:
            _run_all_active.discard(character_name)
        raise
    logger.info("Base Run all %s started (%s)", character_name, plan_now["note"])
    return {"status": "started", "kind": kind}


def _start_collision_run_all(character_name: str) -> Dict[str, Any]:
    """Run all's ``collision`` kind: the saved channel settings applied to every stored model in a worker thread under
    the character's ``build_lock`` and 3D generation slot (``_run_step``) — local, no hub job. Counts as Run all
    running (``_run_all_active``) until it ends."""
    from app.core import model3d
    lock = build_lock(character_name)
    if not lock.acquire(blocking=False):
        return {"status": "building", "reason": RUN_ALL_BUILD_RUNNING}
    if model3d.generation_running(character_name):
        lock.release()
        return {"status": "busy", "reason": RUN_ALL_BUSY}
    with _lock:
        _run_all_active.add(character_name)
    step = Step("collision", COLLISION_LABEL, 0)

    def run() -> None:
        from app.core.timeutils import utc_now_iso
        error = "Run all failed"
        try:
            error = _run_step(character_name, step, True)
        finally:
            lock.release()
            with _lock:
                _run_all_active.discard(character_name)
                _run_all_last[character_name] = {"error": error, "finished_at": utc_now_iso()}
            logger.info("Base Run all %s (collision) ended%s", character_name, f": {error}" if error else "")

    try:
        threading.Thread(target=run, daemon=True, name=f"base-run-all-collision-{character_name}").start()
    except Exception:
        lock.release()
        with _lock:
            _run_all_active.discard(character_name)
        raise
    return {"status": "started", "kind": RUN_ALL_COLLISION}


def _outfit_name(character_name: str, pieces: Dict[str, str]) -> str:
    """The saved outfit whose pieces are exactly the worn ones, else ""."""
    ids = sorted({str(v) for v in (pieces or {}).values() if v})
    if not ids:
        return ""
    try:
        from app.models.character import get_character_outfits
        for outfit in get_character_outfits(character_name) or []:
            if sorted({str(i) for i in outfit.get("pieces") or [] if i}) == ids:
                return str(outfit.get("name") or "")
    except Exception:  # noqa: BLE001 — a label, never a failure
        logger.debug("Saved outfits of %s unreadable", character_name, exc_info=True)
    return ""


#: ``figure_info`` memo: character -> (key, monotonic, answer) (fix round T12-F1, ruling F13 f).
_info_memo: Dict[str, Tuple[Tuple[Any, ...], float, Dict[str, Any]]] = {}
_info_lock = threading.Lock()


def _stat(path) -> Tuple[int, int]:
    try:
        st = path.stat()
        return st.st_mtime_ns, st.st_size
    except OSError:
        return 0, 0


def _info_key(character_name: str, profile: Dict[str, Any], build: Dict[str, Any]) -> Tuple[Any, ...]:
    """What a memoised ``figure_info`` answer stands for — taken BEFORE the
    inputs are read: the figure generation (``figure.invalidate``: every
    ref, model, garment record and config write), the profile and the worn
    items (their modes and texts) — the worn hairstyle and the base
    hairstyle among them (Ruling FR-minors: a hairstyle's mode, colour or
    placement is an item edit, as in ``figure.delivered_figure_cached``),
    the Build's state, and the stat of the character's ``model_refs`` /
    ``model3d`` / ``garments`` directories (an atomic publication renames
    into them; a deletion too)."""
    import hashlib
    from app.core import figure
    from app.core.garment_hair import BASE_HAIRSTYLE_KEY
    from app.models.character import get_character_dir
    from app.models.inventory import get_item
    worn = profile.get("equipped_pieces") or {}
    mesh = profile.get("equipped_mesh_pieces")
    ids = sorted({str(v) for v in worn.values() if v} | {str(i) for i in profile.get("equipped_items") or []
                                                         if isinstance(i, str)}
                 | {str(v) for v in (mesh.values() if isinstance(mesh, dict) else ()) if v}
                 | ({str(profile[BASE_HAIRSTYLE_KEY])} if profile.get(BASE_HAIRSTYLE_KEY) else set()))
    root = get_character_dir(character_name)
    return (figure._generation[0], hashlib.sha1(figure._canonical(profile)).hexdigest(),
            hashlib.sha1(figure._canonical({i: get_item(i) for i in ids})).hexdigest(),
            figure._canonical(build),
            tuple(_stat(root / name) for name in ("model_refs", "model3d", "garments")))


def figure_info(character_name: str) -> Dict[str, Any]:
    """``_figure_info`` memoised (fix round T12-F1, ruling F13 f: the Figure
    tab's GET took 2–5 s): an answer is served again while its ``_info_key``
    holds, for at most ``figure.MEMO_TTL_S``, and stored only when no write
    moved the figure generation while it was computed. A copy is returned."""
    import copy
    import time
    from app.core import figure
    profile = _profile_of(character_name, None)
    build = state(character_name)
    key = _info_key(character_name, profile, build)
    now = time.monotonic()
    with _info_lock:
        hit = _info_memo.get(character_name)
        if hit is not None and hit[0] == key and now - hit[1] < figure.MEMO_TTL_S:
            return copy.deepcopy(hit[2])
    info = _figure_info(character_name, profile=profile, build=build)
    with _info_lock:
        if key[0] == figure._generation[0]:
            if len(_info_memo) >= 256:
                _info_memo.clear()
            _info_memo[character_name] = (key, now, copy.deepcopy(info))
    return info


#: The plan steps the character list counts as the BASE (plain) body (Ruling A112); every other step is the
#: outfit's (the worn figure: shape, pieces, hair, texture/views, fits, assembly, collision).
BASE_STEPS = frozenset({"plain_body", "base_repair", "tip_smoothing"})
#: ``open_steps`` memo: character -> (key, monotonic, answer) — the same key and TTL as ``figure_info``.
_open_memo: Dict[str, Tuple[Tuple[Any, ...], float, Dict[str, Any]]] = {}


def _open_group(steps: List[Step]) -> Dict[str, Any]:
    rows = [{"label": s.label, "jobs": s.jobs, "hold": bool(s.failed or s.manual),
             "why": s.failed or s.manual} for s in steps]
    return {"count": len(rows),
            "hub_jobs": None if any(s.jobs is None for s in steps) else sum(int(s.jobs or 0) for s in steps),
            "hold": any(r["hold"] for r in rows), "steps": rows}


def open_steps(character_name: str) -> Dict[str, Any]:
    """The character list's badges (Ruling A112): the Build's own plan (``plan``, the manual one the Figure tab
    shows) split into ``base`` (``BASE_STEPS``) and ``outfit`` — each ``{count, hub_jobs (None = unknown), hold,
    steps: [{label, jobs, hold, why}]}``; ``hold`` a step only a manual Build runs (``Step.manual``) or one that
    failed for its inputs (``Step.failed``). Plus ``building`` (a run goes). Off the pipeline both are empty.
    Read-only, no hub / LLM / Blender work; memoised like ``figure_info`` (``_info_key``, ``figure.MEMO_TTL_S``).
    Never raises: an unreadable plan answers ``error`` with empty groups."""
    import copy
    import time
    from app.core import figure
    try:
        profile = _profile_of(character_name, None)
        build = state(character_name)
        key = _info_key(character_name, profile, build)
    except Exception as e:  # noqa: BLE001 — a badge, never a failure of the list
        logger.debug("open steps of %s: key not read", character_name, exc_info=True)
        return {"building": False, "base": _open_group([]), "outfit": _open_group([]), "error": str(e)}
    now = time.monotonic()
    with _info_lock:
        hit = _open_memo.get(character_name)
        if hit is not None and hit[0] == key:
            if now - hit[1] >= figure.MEMO_TTL_S and character_name not in _open_refreshing:
                # Past the TTL with the same key: served once more while ONE background re-plan refreshes it
                # (the list polls every character; a cold plan of ~30 characters takes about a second).
                _open_refreshing.add(character_name)
                threading.Thread(target=_refresh_open, args=(character_name,), daemon=True,
                                 name=f"open-steps-{character_name}").start()
            return copy.deepcopy(hit[2])
    return _compute_open(character_name, profile, build, key, now)


_open_refreshing: set = set()


def _refresh_open(character_name: str) -> None:
    import time
    try:
        profile = _profile_of(character_name, None)
        build = state(character_name)
        _compute_open(character_name, profile, build, _info_key(character_name, profile, build), time.monotonic())
    except Exception:  # noqa: BLE001 — the stale answer stays until the next read
        logger.debug("open steps of %s: refresh failed", character_name, exc_info=True)
    finally:
        with _info_lock:
            _open_refreshing.discard(character_name)


def _compute_open(character_name: str, profile: Dict[str, Any], build: Dict[str, Any],
                  key: Tuple[Any, ...], now: float) -> Dict[str, Any]:
    import copy
    from app.core import figure
    try:
        steps = plan(character_name, profile=profile)
        error = ""
    except Exception as e:  # noqa: BLE001
        logger.warning("open steps of %s not computable: %s", character_name, e)
        steps, error = [], str(e)
    out: Dict[str, Any] = {"building": bool(build.get("running")),
                           "base": _open_group([s for s in steps if s.name in BASE_STEPS]),
                           "outfit": _open_group([s for s in steps if s.name not in BASE_STEPS])}
    if error:
        out["error"] = error
        return out
    with _info_lock:
        if key[0] == figure._generation[0]:
            if len(_open_memo) >= 256:
                _open_memo.clear()
            _open_memo[character_name] = (key, now, copy.deepcopy(out))
    return out


def _figure_info(character_name: str, *, profile: Dict[str, Any], build: Dict[str, Any]) -> Dict[str, Any]:
    """``GET /characters/{c}/figure``: ``{pipeline, humanoid, auto_build,
    status, changes, cost, build, wanted, delivered, served_url, served_built_at
    (when the served model was built — Ruling UI3 a), served_state (what that model is against the outfit worn
    now — Ruling A75, ``_served_state``), served_foot_pose (the
    served model's fitted-shoe pose or None — Ruling A52), outfit (the
    saved outfit worn now, "" when none matches), worn (each row with the
    ``jobs`` its chain step plans), hair (with ``jobs``), body (``plain.jobs``:
    ``_plain_jobs``)}``. ``status``: ``building`` while a run goes, else ``failed`` /
    ``changes`` when the plan has steps (failed: the last run recorded a
    failure, or a planned chain failed for its input — ``Step.failed``),
    else ``up_to_date``. ``auto_build`` = ``auto_build_on``."""
    from app.core import base_body, figure, garment_set, model_refs
    pipeline = on_pipeline(character_name, profile=profile)
    out: Dict[str, Any] = {
        "pipeline": pipeline, "humanoid": model_refs.is_humanoid(character_name, profile=profile),
        "auto_build": auto_build_on(character_name, profile=profile),
        "build": build, "served_url": _served_url(character_name),
        "served_built_at": _served_built_at(character_name),
        "served_foot_pose": _served_foot_pose(character_name)}
    if not pipeline:
        return {**out, "status": "up_to_date", "changes": [], "cost": cost(character_name, []),
                "wanted": None, "delivered": None, "outfit": "", "worn": [], "hair": None, "body": None}
    wanted, delivered = figure._delivered(character_name, profile=profile)
    steps = plan(character_name, profile=profile, resolved=(wanted, delivered))
    failures = _with_cached_failures(build["failed"], steps)
    if build["running"]:
        status = "building"
    elif steps:
        status = "failed" if failures else "changes"
    else:
        status = "up_to_date"
    changes = _with_jobs(figure._pending(character_name, wanted, delivered, profile), steps)
    body_change = next((c for c in changes if c.get("key") == figure.BODY_KEY), None)
    built = _model_figure(character_name, wanted.signature)
    meshed = not figure.is_plain(wanted.shape)
    hair_rebuild = any(c.get("key") == figure.HAIR_KEY and c.get("note") == figure.HAIR_REBUILD for c in changes)
    if body_change is not None:
        plain_state = "missing" if body_change.get("delivered") == "missing" else "older_prompts"
        plain_note = "" if plain_state == "missing" else str(body_change.get("delivered") or "")
    elif hair_rebuild:   # the hair's row stands for the plain body's rebuild (ruling F13 a)
        from app.core.base_body import OLDER_PROMPTS
        plain_state, plain_note = "older_prompts", OLDER_PROMPTS
    elif (plain_mismatch := base_body.mesh_view_mismatch(character_name, wanted.bsig)) is not None:
        # Ruling A61: the stored base mesh does not match its own views — outdated until a manual Build meshes it.
        from app.core.model_overview import MESH_VIEW_MISMATCH
        plain_state, plain_note = "older_prompts", MESH_VIEW_MISMATCH.get(plain_mismatch.get("view", ""), "")
    else:
        plain_state, plain_note = "ready", ""
    body = {"plain": {"key": wanted.bsig, "state": plain_state, "note": plain_note},
            "shape": {"key": wanted.shape if meshed else "",
                      "state": ("ready" if delivered.shape == wanted.shape else "missing") if meshed else "plain"},
            "texture": {"key": wanted.texture,
                        "state": ("ready" if built is not None and built.texture == wanted.texture
                                  and built.shape == wanted.shape else "missing") if wanted.texture else "none"}}
    body["plain"]["jobs"] = _plain_jobs(character_name, wanted.bsig)
    worn = _worn_rows(character_name, wanted, delivered, failures, build["running"], profile)
    # Ruling A131: a new body is being built (a base or body-shape step runs) or the newest body has no fits of
    # pieces that were fitted on the earlier one — the tab says so once; those pieces wait for it.
    step_name = str((build.get("step") or {}).get("name") or "") if build["running"] else ""
    new_body = step_name in BASE_STEPS or step_name == "shape" or any(
        row["left_out"] == figure.LEFT_OFF_NEW_BODY for row in worn)
    if new_body:
        for row in worn:
            # a running Build's own-mesh row has no left-off reason of its own yet; a left-off row keeps its own
            if row["mode"] in garment_set.OWN_MESH_MODES and row["state"] == "building" and not row["left_out"]:
                row["left_out"] = row["note"] = figure.LEFT_OFF_NEW_BODY
    served_state = _served_state(character_name, profile=profile)
    _not_on_figure(served_state, changes, worn)
    hair = _hair_row(character_name, profile, wanted, delivered, failures, build["running"])
    for row in worn:
        row["jobs"] = _item_jobs(steps, "pieces", row["item_id"])
    hair["jobs"] = _item_jobs(steps, "plain_body" if hair.get("rebuild") else "hair", "")
    return {**out, "status": status, "changes": changes, "cost": cost(character_name, steps),
            "wanted": wanted.as_dict(), "delivered": delivered.as_dict(),
            "outfit": _outfit_name(character_name, wanted.pieces),
            "worn": worn, "hair": hair, "body": body, "served_state": served_state, "new_body": new_body,
            # Ruling A87: whether the full-body references are set — information beside the plan, never a step.
            "full_body_reference": _full_body_note(character_name, profile),
            "problem": None if build["running"] else _build_problem(character_name, steps, failures, delivered)}


def _full_body_note(character_name: str, profile: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """``full_body_reference.build_note`` (Ruling A87); None when it cannot be read."""
    try:
        from app.core import full_body_reference
        return full_body_reference.build_note(character_name, profile=profile)
    except Exception:  # noqa: BLE001 — an information line never breaks the tab
        logger.exception("Full-body reference note of %s failed", character_name)
        return None


#: ``problem.kind`` (Ruling A61): the body's mesh does not match its own views / any other failed step.
PROBLEM_MESH, PROBLEM_FAILED = "mesh_mismatch", "failed"
#: A failed step's label when the plan does not list it any more.
STEP_LABELS = {"plain_body": "Plain body", "base_repair": MESH_REPAIR_LABEL, "tip_smoothing": TIP_SMOOTHING_LABEL,
               "shape": "Body shape", "pieces": "Own mesh", "template": "Template drape", "hair": "Hair",
               "texture": "Texture", "fits": "Fits on the CPU", "assemble": ASSEMBLE_LABEL,
               "collision": COLLISION_LABEL}
_VIEW_IN_ERROR = re.compile(r"\b(front|back|left|right)(?: view\b|:)")


def _build_problem(character_name: str, steps: List[Step], failures: Dict[str, Dict[str, Any]],
                   delivered) -> Optional[Dict[str, Any]]:
    """What the tabs that run the Build say about a failed step (Ruling A61; the character-tab checklist point 8:
    which step, the reason in plain words, the view, the action that fixes it and its cost), None when nothing
    failed. ``{kind, step, step_label, view, body, detail, action, jobs, held}``:

    * ``mesh_mismatch`` — the body the figure is painted on (``body``: ``plain`` / ``shape``) has a mesh the body
      retexture worker refused against its own ``view`` (``base_body.mesh_view_mismatch``): ``action``
      ``rebuild_mesh`` = a manual Build, which makes the mesh again first; ``jobs`` that step's hub jobs.
    * ``failed`` — the first failed step in ``STEP_ORDER`` (the last run's or a cached one): ``detail`` its error,
      ``view`` a view the error names, ``action`` ``retry`` = a manual Build; ``jobs`` the plan's hub jobs (None when
      unknown).

    ``held``: automatic Builds do not run the step again until its inputs change (a cached failure). Never raises."""
    from app.core import base_body, figure
    try:
        by_name = {s.name: s for s in steps}
        mismatch = base_body.mesh_view_mismatch(character_name, delivered.shape)
        if mismatch is not None:
            plain = figure.is_plain(delivered.shape)
            fix = by_name.get("plain_body" if plain else "shape")
            return {"kind": PROBLEM_MESH, "step": "assemble", "step_label": ASSEMBLE_LABEL, "view": mismatch["view"],
                    "body": "plain" if plain else "shape", "detail": mismatch["error"], "action": "rebuild_mesh",
                    "jobs": fix.jobs if fix is not None else None, "held": True}
        name = next((n for n in STEP_ORDER if n in failures), None)
        if name is None:
            name = next((n for n in failures), None)
        if name is None:
            return None
        entry = failures[name]
        detail = str(entry.get("error") or "")
        planned = by_name.get(name)
        label = (planned.running_label(True).removesuffix(RETRY_SUFFIX) if planned is not None
                 else STEP_LABELS.get(name, name.replace("_", " ").capitalize()))
        found = _VIEW_IN_ERROR.search(detail)
        unknown = any(s.jobs is None for s in _runnable(steps, True))
        return {"kind": PROBLEM_FAILED, "step": name, "step_label": label,
                "view": base_body.registration_refusal_view(detail) or (found.group(1) if found else ""),
                "body": "", "detail": detail, "action": "retry",
                "jobs": None if unknown else sum(int(s.jobs or 0) for s in _runnable(steps, True)),
                "held": bool(planned is not None and planned.failed)}
    except Exception:  # noqa: BLE001 — a line of the tab, never a failure of the poll
        logger.debug("Build problem of %s not read", character_name, exc_info=True)
        return None
