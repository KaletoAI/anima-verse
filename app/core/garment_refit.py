"""Boot sweep: refit garment fits made by an older fit algorithm.

A fit record carries ``fit_version`` (``garment_fit.FIT_VERSION[kind]``; HAAR hair its own,
``garment_fit.fit_version_for``);
``garments._fit_state`` reports an older or missing one as ``stale`` and the
next chain run of the item re-fits it. Hair is only run on a base model
change or a click, so without this sweep an old fit would stay served until
then. After a server start (``start_sweep``, from the lifespan) one daemon
thread walks the characters one at a time and refits, for every garment
whose CURRENT fsig holds an accepted fit on the CURRENT base model with an
outdated ``fit_version``, the fit step only:

- edit chain (clothing): ``garments._fit`` from the cached prepared mesh + images;
- HairDeck: the stored seeds (``garments._fit_seed``), the served seed first
  — HairDeck itself never runs again here (a run's fit step would ask for one
  more seed when none passes; the sweep refuses instead);
- HAAR: the stored seeds of the current ``ssig`` (``garments._haar_fit_step``, ``_refit_haar``) — HAAR itself
  never runs here; a HAAR record's version is ``garment_haar.HAAR_FIT_VERSION``
  (``garment_fit.expected_fit_version``);
- footwear: ``garment_footwear.fit`` from the item's cached shoe source.

Per body (plan 2026-11-10-outfit-body-mesh-mode, Task 2): then every fit on
an OUTFIT BODY (``garments/bodies/<body id>/``) with an outdated
``fit_version`` whose body is still stored unchanged (``body_sha256``) and
whose fsig is the one the base model serves now is refitted on that body
from the base fit (``garments.fit_on_body``) — after the base fits, so it
derives from the refitted one. A refusal is recorded on that body
(``garment_store.record_body_failure``); the old fit stays served.

Before that, per character in the outfit-body mesh mode, every stored outfit
body whose posture record is stale gets its base body's posture
(``outfit_bodies.match_stale_postures``, ``app/core/outfit_body_posture.py``):
the turned body's garments are refitted onto it and the worn outfit's model
on it is rebuilt as the CPU copy.

Refused clothing fits (scale retry, 2026-11-10): a clothing fit refused as
too small (``garment_fit.too_small`` — only deep push / max push gates)
whose failure record predates the scale retry (no ``scale_retry`` stamp,
``garment_fit.SCALE_RETRY_VERSION``) is fitted ONCE more by the widening
fit — on the base model (``refused_fits``, edit chain, the current fsig on
the current base model) and on every outfit body (``refused_body_fits``,
the body stored unchanged, the fsig of the served base fit). A new refusal
is recorded stamped, so it is not retried again.

The Swing default (Ruling H-R9): ``hair_motion.HAIR_SWING_DEFAULT`` flipped
on (H-R1), and Swing is in a HairDeck fit's fingerprint — a hairstyle that
never chose its Swing got a NEW fsig without a fit, the Swing-off fit of the
old fsig stayed served, and the version check above never sees another fsig.
``swing_default_fits`` lists exactly those (their stored setting is the
default, the Swing-off fsig holds an accepted Swing-off fit on the current
base model, the current fsig none); the sweep refits their stored seeds under
the current fsig (``_refit_hairdeck``, the served seed of the old fit first).
An explicit Swing (``"off"`` / ``"on"``) is never listed.

Refit before re-render (``garment_source``): every refit here fits through
``garments._fit`` / ``fit_on_body``, so a group refitted from a source made
on an older base is registered from its own base copy like the chain does.
First, per character, the base views of every image group an accepted fit
was made from are kept with that group while they are still on disk
unchanged (``garment_source.backfill``) — a group from before keeps its
frame when the base images are rendered again under the same signature.

Refused refits are not retried at every start (Ruling R7c, plan 2026-11-12
fit-sdf-speed-drape): the sweep stamps its refusal record with the fit version
and the identity of the refit's inputs (``refusal_stamp``: fsig, base model,
prepared mesh / HairDeck job + seeds / shoe source); the listers skip a piece
whose refusal holds by both (``held_refusal``). A new version, changed inputs
or an explicit run (Regenerate) tries again. On an outfit body the refusal
record already holds by body bytes, base fit and version (``body_failure``).

CPU only: no image, mesh or hub call. ``garments._publish_fit`` schedules the
re-assembly of the current outfit model. A character whose garment chain runs
(its run lock held, or its FIFO active) is retried later, never refitted
alongside. A refused refit is recorded like a refused run's fit
(``garments._note_outcome``) — the old fit stays served, automatic triggers
skip it until an explicit run. One log line per refit. Asset maintenance like
the outfit GC: a world freeze does not stop it.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

#: Seconds after the server start before the sweep begins (boot traffic first).
SWEEP_DELAY_S = 120.0
#: Pause between two characters.
SWEEP_PAUSE_S = 2.0
#: A busy character (garment chain running) is retried this often, this far apart.
BUSY_RETRIES = 20
BUSY_RETRY_S = 30.0


def inputs_id(character_name: str, item_id: str, fsig: str, method: str, base_sha: str, *,
              profile: Optional[Dict[str, Any]] = None) -> str:
    """The identity of a refit's inputs (Ruling R7c): sha256[:16] of ``{fsig, base_model_sha256, method}`` plus
    per method what the fit reads beyond them — HairDeck the ``hsig`` and its stored seeds, footwear the current
    shoe source mesh and its insole analysis (``footwear_source``), the edit chain the prepared mesh's sha256.
    A changed input = another identity = the sweep tries again."""
    import hashlib
    import json
    from app.core import garment_store as gs
    from app.core.base_body import file_sha256
    parts: Dict[str, Any] = {"fsig": fsig, "base_model_sha256": base_sha, "method": method}
    try:
        if method == gs.HAIRDECK:
            from app.core import garments
            hsig = gs.garment_hsig(character_name, item_id, profile=profile)
            parts.update(hsig=hsig, seeds=list(garments._stored_seeds(character_name, item_id, hsig)))
        elif method == gs.HAAR:
            ssig = gs.garment_ssig(character_name, item_id, profile=profile)
            parts.update(ssig=ssig, seeds=gs.haar_seeds(character_name, item_id, ssig))
        elif method == gs.SHOE:
            from app.core import footwear_source
            ssig = footwear_source.current_ssig(item_id)
            folder = footwear_source.source_dir(item_id, ssig)
            parts.update(ssig=ssig, source_sha256=file_sha256(folder / "prepared.glb"),
                         insole_sha256=file_sha256(folder / "insole.json"))
        else:
            parts["prepared_sha256"] = file_sha256(gs.garment_path(character_name, item_id, fsig, "prepared"))
    except ValueError:
        parts["unreadable"] = True
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def refusal_stamp(character_name: str, item_id: str, kind: str, fsig: str, method: str, base_sha: str, *,
                  profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """``{fit_version, inputs_id}`` a refused refit's failure record carries (``garment_store.record_failure``)."""
    from app.core import garment_fit
    return {"fit_version": garment_fit.fit_version_for(kind, method),
            "inputs_id": inputs_id(character_name, item_id, fsig, method, base_sha, profile=profile)}


def held_refusal(character_name: str, item_id: str, kind: str, fsig: str, method: str, base_sha: str, *,
                 profile: Optional[Dict[str, Any]] = None) -> bool:
    """Whether the refit of ``(item_id, fsig)`` on the base model ``base_sha`` was refused already by the current
    fit version from the same inputs (Ruling R7c): its failure record (``chain_failure``, a ``fit`` step) names
    ``fit_version`` == ``FIT_VERSION[kind]`` and the current ``inputs_id``. An unstamped record (a chain run's)
    does not hold here."""
    from app.core import garment_fit, garment_store as gs
    failure = gs.chain_failure(character_name, item_id, fsig, base_model_sha=base_sha)
    if not failure or failure.get("step") != "fit" or "inputs_id" not in failure:
        return False
    return (failure.get("fit_version") == garment_fit.fit_version_for(kind, method)
            and failure.get("inputs_id") == inputs_id(character_name, item_id, fsig, method, base_sha,
                                                      profile=profile))


def outdated_fits(character_name: str, *, profile: Optional[Dict[str, Any]] = None
                  ) -> List[Tuple[str, str, str, str]]:
    """``[(item_id, kind, fsig, method)]`` of the character's fits that the
    sweep refits: the item's current fsig and method, accepted on the
    current base model, ``fit_version`` older or missing, its refit not
    refused already from the same inputs (``held_refusal``). A fit on another
    base model is ``garments.after_base_model``'s, another fsig the next
    chain run's."""
    from app.core import base_body, garment_fit, garment_store as gs
    if profile is None:
        from app.models.character import get_character_profile
        profile = get_character_profile(character_name) or {}
    base = base_body.current_base(character_name, profile=profile)
    if base is None or not base[1]:
        return []
    root = gs._root(character_name)
    out: List[Tuple[str, str, str, str]] = []
    for (item_id, fsig), files in sorted(gs.stored_groups(character_name).items()):
        fit = next((p for p in files if p.suffix == ".glb" and p.parent == root), None)
        if fit is None:
            continue
        record = gs.read_record(fit.with_suffix(".json"))
        kind = str(record.get("kind") or "")
        if record.get("accepted") is not True or record.get("base_model_sha256") != base[1] \
                or kind not in garment_fit.FIT_VERSION \
                or record.get("fit_version") == garment_fit.expected_fit_version(record):
            continue
        try:
            current = gs.garment_fsig(character_name, item_id, profile=profile)
            method = gs.garment_method(character_name, item_id, profile=profile)
        except ValueError:
            continue
        if current != fsig or gs.fit_method(record) != method:
            continue
        if held_refusal(character_name, item_id, kind, fsig, method, base[1], profile=profile):
            continue
        out.append((item_id, kind, fsig, method))
    return out


def swing_default_fits(character_name: str, *, profile: Optional[Dict[str, Any]] = None
                       ) -> List[Tuple[str, str, str]]:
    """``[(item_id, old fsig, current fsig)]`` of the character's HairDeck hairstyles on the Swing DEFAULT (no
    stored ``hair_swing``; Ruling H-R9, module docstring) whose current fsig has no accepted fit on the current base
    model while the fsig they would have with Swing off (``garment_store.garment_fsig(swing=False)``) holds an
    accepted HairDeck fit made with Swing off (``inputs.swing`` false) on it — the fits ``HAIR_SWING_DEFAULT``
    flipping on left behind. By item id; never one whose refit of the current fsig the current fit version refused
    already from the same inputs (``held_refusal``). Empty while the default is off."""
    from app.core import base_body, garment_hair, garment_set, hair_motion, garment_store as gs
    from app.models.inventory import get_item
    if not hair_motion.HAIR_SWING_DEFAULT:
        return []
    if profile is None:
        from app.models.character import get_character_profile
        profile = get_character_profile(character_name) or {}
    base = base_body.current_base(character_name, profile=profile)
    if base is None or not base[1]:
        return []

    def accepted(item_id: str, fsig: str) -> Dict[str, Any]:
        record = gs.read_record(gs.garment_path(character_name, item_id, fsig, "fit").with_suffix(".json"))
        return record if record.get("accepted") is True and record.get("base_model_sha256") == base[1] else {}

    out: List[Tuple[str, str, str]] = []
    for item_id in sorted({iid for iid, _fsig in gs.stored_groups(character_name)}):
        try:
            if gs.garment_method(character_name, item_id, profile=profile) != gs.HAIRDECK:
                continue
            settings = garment_hair.hairstyle_settings(get_item(item_id))
            if settings.get(hair_motion.SETTING_SWING) in (hair_motion.SWING_ON, hair_motion.SWING_OFF):
                continue
            current = gs.garment_fsig(character_name, item_id, profile=profile)
            old = gs.garment_fsig(character_name, item_id, profile=profile, swing=False)
        except ValueError:
            continue
        if old == current or accepted(item_id, current):
            continue
        record = accepted(item_id, old)
        if gs.fit_method(record) != gs.HAIRDECK or (record.get("inputs") or {}).get("swing"):
            continue
        if held_refusal(character_name, item_id, garment_set.HAIR, current, gs.HAIRDECK, base[1], profile=profile):
            continue
        out.append((item_id, old, current))
    return out


def retry_refusal(record: Dict[str, Any]) -> bool:
    """A failure record of a fit refused as too small (``garment_fit.too_small``
    on the reasons after the error's "— ") that was recorded before the scale
    retry (``scale_retry`` missing or older than
    ``garment_fit.SCALE_RETRY_VERSION``): the refit sweep fits it once more."""
    from app.core import garment_fit
    if record.get("step") != "fit":
        return False
    try:
        if int(record.get("scale_retry") or 0) >= garment_fit.SCALE_RETRY_VERSION:
            return False
    except (TypeError, ValueError):
        pass
    _head, sep, reasons = str(record.get("error") or "").partition(" — ")
    return bool(sep) and garment_fit.too_small(reasons.split("; "))


def _clothing_kind(character_name: str, item_id: str, profile: Dict[str, Any]) -> Optional[str]:
    """The item's garment kind when it is clothing, else None (unknown items too)."""
    from app.core import garment_set, garments
    try:
        kind = garments._item_order(character_name, item_id, profile)[1]
    except ValueError:
        return None
    return kind if kind == garment_set.CLOTHING else None


def refused_fits(character_name: str, *, profile: Optional[Dict[str, Any]] = None
                 ) -> List[Tuple[str, str, str, str]]:
    """``[(item_id, kind, fsig, method)]`` of the character's clothing whose
    fit of the CURRENT fsig was refused on the CURRENT base model as too
    small before the scale retry (``retry_refusal``); edit chain only (the
    method clothing is made with)."""
    from app.core import base_body, garment_store as gs
    if profile is None:
        from app.models.character import get_character_profile
        profile = get_character_profile(character_name) or {}
    base = base_body.current_base(character_name, profile=profile)
    if base is None or not base[1]:
        return []
    out: List[Tuple[str, str, str, str]] = []
    for (item_id, fsig), files in sorted(gs.stored_groups(character_name).items()):
        failed = gs.garment_path(character_name, item_id, fsig, "failed")
        if failed not in files:
            continue
        record = gs.read_record(failed)
        if record.get("base_model_sha256") != base[1] or not retry_refusal(record):
            continue
        kind = _clothing_kind(character_name, item_id, profile)
        if kind is None:
            continue
        try:
            current = gs.garment_fsig(character_name, item_id, profile=profile)
            method = gs.garment_method(character_name, item_id, profile=profile)
        except ValueError:
            continue
        if current != fsig or method != gs.EDIT_CHAIN:
            continue
        out.append((item_id, kind, fsig, method))
    return out


def refused_body_fits(character_name: str, *, profile: Optional[Dict[str, Any]] = None
                      ) -> List[Tuple[str, str, str, str]]:
    """``[(item_id, kind, fsig, body_id)]`` of the character's clothing fits
    on outfit bodies refused as too small before the scale retry
    (``retry_refusal``): the body stored unchanged since (``body_sha256``),
    the fsig that of the fit the base model serves now; by (item, fsig), then
    body."""
    from app.core import base_body, garments, garment_store as gs
    if profile is None:
        from app.models.character import get_character_profile
        profile = get_character_profile(character_name) or {}
    base = base_body.current_base(character_name, profile=profile)
    if base is None or not base[1]:
        return []
    out: List[Tuple[str, str, str, str]] = []
    served: Dict[str, Optional[str]] = {}
    for (item_id, fsig), files in sorted(gs.stored_groups(character_name).items()):
        for failed in files:
            body_id = gs.body_of(failed)
            if not body_id or failed != gs.garment_path(character_name, item_id, fsig, "failed", body=body_id):
                continue
            record = gs.read_record(failed)
            if not retry_refusal(record) or not record.get("body_sha256") \
                    or record.get("body_sha256") != garments.body_sha256(character_name, body_id):
                continue
            if item_id not in served:
                hit = gs.accepted_fit(character_name, item_id, base_model_sha=base[1], profile=profile)
                parsed = gs.parse_name(hit[0]) if hit else None
                served[item_id] = parsed[1] if parsed else None
            kind = _clothing_kind(character_name, item_id, profile)
            if served[item_id] != fsig or kind is None:
                continue
            out.append((item_id, kind, fsig, body_id))
    return out


def outdated_body_fits(character_name: str, *, profile: Optional[Dict[str, Any]] = None
                       ) -> List[Tuple[str, str, str, str]]:
    """``[(item_id, kind, fsig, body_id)]`` of the character's fits on outfit
    bodies that the sweep refits: accepted on the body as it is stored now,
    ``fit_version`` older or missing, made under the fsig of the fit the base
    model serves now (``garment_store.accepted_fit``; footwear: its current
    fsig — a shoe on a body is derived from its base fit, ``garment_footwear.body_fit``),
    its refit not refused already on these body bytes from the same base fit by
    the current version (``garment_store.body_failure``, Ruling R7c); by
    (item, fsig), then body."""
    from app.core import base_body, garment_fit, garments, garment_store as gs
    if profile is None:
        from app.models.character import get_character_profile
        profile = get_character_profile(character_name) or {}
    base = base_body.current_base(character_name, profile=profile)
    if base is None or not base[1]:
        return []
    out: List[Tuple[str, str, str, str]] = []
    served: Dict[str, Optional[str]] = {}
    base_fits: Dict[str, Any] = {}   # item -> the base fit served now (``accepted_fit``), clothing / hair
    for (item_id, fsig), files in sorted(gs.stored_groups(character_name).items()):
        for fit in files:
            body_id = gs.body_of(fit)
            if not body_id or fit.suffix != ".glb" or fit != gs.garment_path(character_name, item_id, fsig, "fit",
                                                                             body=body_id):
                continue
            record = gs.read_record(fit.with_suffix(".json"))
            kind = str(record.get("kind") or "")
            if record.get("accepted") is not True or kind not in garment_fit.FIT_VERSION \
                    or record.get("fit_version") == garment_fit.expected_fit_version(record) \
                    or not record.get("body_sha256") \
                    or record.get("body_sha256") != garments.body_sha256(character_name, body_id):
                continue
            if item_id not in served:
                if kind == "footwear":
                    try:
                        served[item_id] = gs.garment_fsig(character_name, item_id, profile=profile)
                    except ValueError:
                        served[item_id] = None
                else:
                    base_fits[item_id] = gs.accepted_fit(character_name, item_id, base_model_sha=base[1],
                                                         profile=profile)
                    parsed = gs.parse_name(base_fits[item_id][0]) if base_fits[item_id] else None
                    served[item_id] = parsed[1] if parsed else None
            if served[item_id] != fsig:
                continue
            hit = base_fits.get(item_id)
            if hit is not None and gs.body_failure(
                    character_name, item_id, fsig, body_id, body_sha=str(record.get("body_sha256")),
                    base_fit_sha=garments._sha(hit[0]),
                    fit_version=garment_fit.expected_fit_version(hit[1])) is not None:
                continue
            out.append((item_id, kind, fsig, body_id))
    return out


def _refit_bodies(character_name: str, profile: Dict[str, Any], base_sha: str) -> List[str]:
    """Refit ``outdated_body_fits``, then ``refused_body_fits`` (caller holds
    the run lock). Returns ``"<item>@<body id>"`` per refitted fit."""
    from app.core import garment_fit, garments, garment_store as gs
    from app.core.keyed_lock import keyed_lock
    done: List[str] = []
    outdated = outdated_body_fits(character_name, profile=profile)
    refused = [fit for fit in refused_body_fits(character_name, profile=profile) if fit not in outdated]
    for item_id, kind, fsig, body_id in outdated + refused:
        base_fit = gs.accepted_fit(character_name, item_id, base_model_sha=base_sha, profile=profile)
        if base_fit is None:
            continue
        old = gs.read_record(gs.garment_path(character_name, item_id, fsig, "fit", body=body_id).with_suffix(".json"))
        try:
            # Serialised with the assembly builds' fits on the same body (``garments.body_fit``).
            with keyed_lock("garment_body_fit", f"{character_name}:{body_id}"):
                if kind == "footwear":
                    # The shoe on the outfit body is derived from its base fit (``garment_footwear.body_fit``,
                    # ``build``: a stale / older-version fit is made now, CPU only — Ruling A35).
                    from app.core import garment_footwear
                    garment_footwear.body_fit(character_name, item_id, body_id=body_id,
                                              body_sha=garments.body_sha256(character_name, body_id),
                                              profile=profile, build=True)
                else:
                    garments.fit_on_body(character_name, item_id, body_id=body_id, base_fit=base_fit,
                                         profile=profile)
        except Exception as e:  # noqa: BLE001 — recorded on that body, the old fit stays served
            error = e.error if isinstance(e, garments._Refused) else (str(e) or type(e).__name__)
            gs.record_body_failure(character_name, item_id, fsig, body_id, error=error,
                                   body_sha=str(old.get("body_sha256") or ""),
                                   base_fit_sha=garments._sha(base_fit[0]),
                                   fit_version=garment_fit.expected_fit_version(base_fit[1]))
            outcome = f"refused — {error}"
        else:
            done.append(f"{item_id}@{body_id}")
            outcome = "ok"
        why = ("too-small refusal retried widened" if (item_id, kind, fsig, body_id) in refused
               else f"fit_version {old.get('fit_version')} -> {garment_fit.expected_fit_version(old)}")
        logger.info("Garment refit %s/%s (%s, %s) on outfit body %s: %s: %s", character_name,
                    item_id, kind, fsig, body_id, why, outcome)
    return done


def _retry_refused(character_name: str, profile: Dict[str, Any], bsig: str,
                   skip: List[str]) -> List[str]:
    """Fit ``refused_fits`` once more (caller holds the run lock), items in
    ``skip`` (refitted just now) left out; the outcome is recorded like a
    run's fit (``garments._note_outcome``: a new refusal stamped). Returns
    the item ids fitted."""
    from app.core import base_body, garments, garment_store as gs
    done: List[str] = []
    for item_id, kind, fsig, _method in refused_fits(character_name, profile=profile):
        if item_id in skip:
            continue
        gs.start(character_name, item_id, "fit")
        try:
            garments._fit(character_name, item_id, kind, fsig, bsig, profile)
        except base_body.MissingInput as e:
            gs.end(character_name, item_id, "fit")
            logger.info("Garment refit %s/%s (%s): skipped — %s", character_name, item_id, fsig, e)
            continue
        except garments._Refused as e:
            result = garments._refusal(character_name, item_id, fsig, "fit", e.error, e.gates, [])
        except Exception as e:  # noqa: BLE001 — reported as the fit's failure, the sweep goes on
            result = garments._refusal(character_name, item_id, fsig, "fit", str(e) or type(e).__name__, None, [])
        else:
            gs.end(character_name, item_id, "fit")
            result = {"ok": True, "fsig": fsig, "ran": ["fit"]}
            done.append(item_id)
        garments._note_outcome(character_name, item_id, result)
        logger.info("Garment refit %s/%s (%s, %s): too-small refusal retried widened: %s", character_name, item_id,
                    kind, fsig, "ok" if result.get("ok") else f"refused — {result.get('error')}")
    return done


def outdated_footwear_fits(character_name: str, *, profile: Optional[Dict[str, Any]] = None
                           ) -> List[Tuple[str, str, str]]:
    """``[(item_id, old fsig, current fsig)]`` of the character's WORN footwear whose current fsig has no
    accepted fit on the current base model while an accepted fit of an OLDER ``fit_version`` exists under
    another fsig of the SAME shoe source and width cap (the footwear fsig carries the fit version itself —
    plan 2026-11-10-footwear-rigid-shoes Task 25: a version bump refits once at boot, CPU only, instead of
    waiting for the next outfit build) — unless the refit of the current fsig was refused already by the current
    version from the same shoe source (``held_refusal``, Ruling R7c)."""
    from app.core import base_body, garment_fit, garment_footwear, garment_set, garment_store as gs
    if profile is None:
        from app.models.character import get_character_profile
        profile = get_character_profile(character_name) or {}
    base = base_body.current_base(character_name, profile=profile)
    if base is None or not base[1]:
        return []
    out: List[Tuple[str, str, str]] = []
    groups = gs.stored_groups(character_name)
    root = gs._root(character_name)
    for item_id in garment_set.worn_garments(character_name, profile=profile):
        try:
            if gs._garment_kind(item_id) != garment_set.FOOTWEAR:
                continue
            current = gs.garment_fsig(character_name, item_id, profile=profile)
        except ValueError:
            continue
        if garment_footwear.fit_state(character_name, item_id, current, base[1]) == "accepted":
            continue
        if held_refusal(character_name, item_id, garment_set.FOOTWEAR, current, gs.SHOE, base[1], profile=profile):
            continue
        from app.models.inventory import get_item
        inputs = garment_footwear.fsig_inputs(character_name, get_item(item_id) or {"id": item_id}, profile=profile)
        for (iid, fsig), files in sorted(groups.items()):
            if iid != item_id or fsig == current:
                continue
            fit = next((p for p in files if p.suffix == ".glb" and p.parent == root), None)
            if fit is None:
                continue
            record = gs.read_record(fit.with_suffix(".json"))
            if record.get("accepted") is not True or record.get("kind") != garment_set.FOOTWEAR \
                    or record.get("fit_version") == garment_fit.FIT_VERSION[garment_set.FOOTWEAR] \
                    or record.get("ssig") != inputs["ssig"] \
                    or (record.get("scale") or {}).get("width_cap") != inputs["width_cap"]:
                continue
            out.append((item_id, fsig, current))
            break
    return out


def outdated_footwear_sources(character_name: str, *, profile: Optional[Dict[str, Any]] = None) -> List[str]:
    """Item ids of the character's WORN footwear whose shoe source is through the mesh step under the current
    ssig while its insole analysis is missing or of another ``footwear_insole.INSOLE_VERSION`` — the re-analysis
    is CPU work (``footwear_source.run_source(steps=["insole"], force=True)``) that today only happened on the
    next outfit build; the sweep and the ``fit_refit`` improvement run it (spec 2026-11-11-improvements-figure-
    pipeline § 6.2). A source without its mesh is ``garment_fill``'s, never listed here."""
    from app.core import footwear_insole, footwear_source, garment_set, garment_store as gs
    if profile is None:
        from app.models.character import get_character_profile
        profile = get_character_profile(character_name) or {}
    out: List[str] = []
    for item_id in garment_set.worn_garments(character_name, profile=profile):
        try:
            if gs._garment_kind(item_id) != garment_set.FOOTWEAR:
                continue
            ssig = footwear_source.current_ssig(item_id)
            if not footwear_source.step_done(item_id, ssig, "mesh"):
                continue
            version = footwear_source.step_record(item_id, ssig, "insole").get("version")
        except ValueError:
            continue
        if version != footwear_insole.INSOLE_VERSION:
            out.append(item_id)
    return out


def _fit_footwear(character_name: str, item_id: str, fsig: str, profile: Dict[str, Any],
                  stamp: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """One footwear fit on the base model under the run lock, reported and noted like every refit; the result.
    ``stamp`` (``refusal_stamp``): carried by a refusal's failure record."""
    from app.core import garment_footwear, garments, garment_store as gs
    gs.start(character_name, item_id, "fit")
    try:
        garment_footwear.fit(character_name, item_id, fsig, profile=profile, schedule=False)
    except garments._Refused as e:
        result = garments._refusal(character_name, item_id, fsig, "fit", e.error, e.gates, [])
    except Exception as e:  # noqa: BLE001 — reported as the fit's failure, the sweep goes on
        result = garments._refusal(character_name, item_id, fsig, "fit", str(e) or type(e).__name__, None, [])
    else:
        gs.end(character_name, item_id, "fit")
        result = {"ok": True, "fsig": fsig, "ran": ["fit"]}
    if not result.get("ok") and stamp:
        result["refusal_stamp"] = stamp
    garments._note_outcome(character_name, item_id, result)
    return result


def _refit_footwear_bodies(character_name: str, item_id: str, old_fsig: str, profile: Dict[str, Any]) -> List[str]:
    """Refit the item on every stored outfit body whose fit of ``old_fsig`` was accepted
    (``garment_footwear.body_fit`` with ``build``); ``"<item>@<body id>"`` per body fitted."""
    from app.core import garment_footwear, garments, garment_store as gs
    from app.core.keyed_lock import keyed_lock
    done: List[str] = []
    for body_id in garment_footwear.stored_outfit_bodies(character_name):
        old_body = gs.read_record(gs.garment_path(character_name, item_id, old_fsig, "fit", body=body_id)
                                  .with_suffix(".json"))
        if old_body.get("accepted") is not True:
            continue
        body_sha = garments.body_sha256(character_name, body_id)
        try:
            with keyed_lock("garment_body_fit", f"{character_name}:{body_id}"):
                garment_footwear.body_fit(character_name, item_id, body_id=body_id, body_sha=body_sha,
                                          profile=profile, build=True)
        except Exception as e:  # noqa: BLE001 — recorded on that body by body_fit, the sweep goes on
            logger.info("Garment refit %s/%s (footwear) on outfit body %s: %s", character_name, item_id,
                        body_id, str(e) or type(e).__name__)
            continue
        done.append(f"{item_id}@{body_id}")
    return done


def _refit_footwear(character_name: str, profile: Dict[str, Any], base: Tuple[str, str]) -> List[str]:
    """The footwear part of the sweep, caller holds the run lock: first ``outdated_footwear_sources`` — the insole
    re-analysed (CPU), then the fit on the base model and on every stored outfit body that had one, exactly what
    ``garment_footwear.run_chain`` does for an outdated insole — then ``outdated_footwear_fits`` under the current
    fsig the same way. Returns the item ids (``"<item>@<body id>"`` per body fit)."""
    from app.core import footwear_source, garment_fit, garment_set, garments, garment_store as gs
    done: List[str] = []
    for item_id in outdated_footwear_sources(character_name, profile=profile):
        fsig = gs.garment_fsig(character_name, item_id, profile=profile)
        gs.start(character_name, item_id, "insole")
        res = footwear_source.run_source(item_id, steps=["insole"], force=True)
        if not res.get("ok"):
            result = garments._refusal(character_name, item_id, fsig, str(res.get("step") or "insole"),
                                       str(res.get("error") or ""), res.get("gates"), [])
            if res.get("failure") == footwear_source.LOAD:
                result["retry_later"] = True
            garments._note_outcome(character_name, item_id, result)
            logger.info("Garment refit %s/%s (footwear): insole re-analysis refused — %s", character_name, item_id,
                        result.get("error"))
            continue
        gs.end(character_name, item_id, "insole")
        result = _fit_footwear(character_name, item_id, fsig, profile,
                               stamp=refusal_stamp(character_name, item_id, garment_set.FOOTWEAR, fsig, gs.SHOE,
                                                   base[1], profile=profile))
        logger.info("Garment refit %s/%s (footwear, %s): insole re-analysed, fit: %s", character_name, item_id,
                    fsig, "ok" if result.get("ok") else f"refused — {result.get('error')}")
        if result.get("ok"):
            done.append(item_id)
            done += _refit_footwear_bodies(character_name, item_id, fsig, profile)
    for item_id, old_fsig, fsig in outdated_footwear_fits(character_name, profile=profile):
        old = gs.read_record(gs.garment_path(character_name, item_id, old_fsig, "fit").with_suffix(".json"))
        result = _fit_footwear(character_name, item_id, fsig, profile,
                               stamp=refusal_stamp(character_name, item_id, garment_set.FOOTWEAR, fsig, gs.SHOE,
                                                   base[1], profile=profile))
        logger.info("Garment refit %s/%s (footwear, %s -> %s): fit_version %s -> %s: %s", character_name, item_id,
                    old_fsig, fsig, old.get("fit_version"), garment_fit.FIT_VERSION[garment_set.FOOTWEAR],
                    "ok" if result.get("ok") else f"refused — {result.get('error')}")
        if result.get("ok"):
            done.append(item_id)
            done += _refit_footwear_bodies(character_name, item_id, old_fsig, profile)
    return done


def _busy(character_name: str) -> bool:
    """A garment chain of the character runs or waits in its FIFO, or a CPU refit runs beside it (Ruling A30)."""
    from app.core import garments
    return garments.busy(character_name)


def _refit_hairdeck(character_name: str, item_id: str, kind: str, fsig: str, bsig: str,
                    profile: Dict[str, Any], *, served_fsig: Optional[str] = None) -> None:
    """Refit HairDeck hair from its stored seeds under ``fsig`` — the served seed (of the fit under
    ``served_fsig``, default ``fsig``) first and kept when it passes, else the best passing one
    (``_choose_seed``). Never runs HairDeck: ``_Refused`` when no stored seed passes."""
    from app.core import base_body, garments, garment_store as gs
    hsig = gs.garment_hsig(character_name, item_id, profile=profile)
    seeds = garments._stored_seeds(character_name, item_id, hsig)
    if garments._hairdeck_files(character_name, item_id, hsig)[0] is None or not seeds:
        raise base_body.MissingInput("The HairDeck hair is missing — run the hairdeck step first")
    record = gs.read_record(gs.garment_path(character_name, item_id, served_fsig or fsig, "fit")
                            .with_suffix(".json"))
    served = (record.get("inputs") or {}).get("seed")
    order = ([served] if served in seeds else []) + [s for s in seeds if s != served]
    snapshot = base_body._snapshot_base_model(character_name, bsig)
    fits: Dict[int, Dict[str, Any]] = {}
    for seed in order:
        fits[seed] = garments._fit_seed(character_name, item_id, hsig, seed, seeds.index(seed) + 1,
                                        snapshot["rigged"], profile)
        if seed == served and fits[seed]["gates"]["ok"]:
            break
    chosen = served if served in fits and fits[served]["gates"]["ok"] else garments._choose_seed(fits)
    if chosen is None:
        raise garments._Refused("fit", "refit refused for every stored HairDeck seed",
                                {"attempts": garments._refused_gates(fits)})
    garments._publish_hairdeck(character_name, item_id, kind, fsig, bsig, hsig, profile, snapshot,
                               fits[chosen], fits)


def _refit_haar(character_name: str, item_id: str, kind: str, fsig: str, bsig: str,
                profile: Dict[str, Any]) -> None:
    """Refit HAAR hair from its stored seeds on the current base model (``garments._haar_fit_step`` with
    ``refit``: every stored seed of the current ``ssig`` is fitted again, the served one published). Never runs
    HAAR: ``MissingInput`` without a stored seed, ``_Refused`` when the served seed's fit cannot be made. The fit
    is published under the fsig it names after the refit (the best seed may change with the new results)."""
    from app.core import garments
    garments._haar_fit_step(character_name, item_id, kind, bsig, profile)


def _refit_swing_default(character_name: str, profile: Dict[str, Any], base: Tuple[str, str]) -> List[str]:
    """Refit ``swing_default_fits`` under their current fsig from the stored seeds (caller holds the run lock;
    Ruling H-R9), reported and noted like every refit, a refusal stamped (``refusal_stamp``). Returns the item
    ids fitted."""
    from app.core import base_body, garment_set, garments, garment_store as gs
    done: List[str] = []
    for item_id, old_fsig, fsig in swing_default_fits(character_name, profile=profile):
        stamp = refusal_stamp(character_name, item_id, garment_set.HAIR, fsig, gs.HAIRDECK, base[1], profile=profile)
        gs.start(character_name, item_id, "fit")
        try:
            _refit_hairdeck(character_name, item_id, garment_set.HAIR, fsig, base[0], profile, served_fsig=old_fsig)
        except base_body.MissingInput as e:
            gs.end(character_name, item_id, "fit")
            logger.info("Garment refit %s/%s (%s): skipped — %s", character_name, item_id, fsig, e)
            continue
        except garments._Refused as e:
            result = garments._refusal(character_name, item_id, fsig, "fit", e.error, e.gates, [])
        except Exception as e:  # noqa: BLE001 — reported as the fit's failure, the sweep goes on
            result = garments._refusal(character_name, item_id, fsig, "fit", str(e) or type(e).__name__, None, [])
        else:
            gs.end(character_name, item_id, "fit")
            result = {"ok": True, "fsig": fsig, "ran": ["fit"]}
            done.append(item_id)
        if not result.get("ok"):
            result["refusal_stamp"] = stamp
        garments._note_outcome(character_name, item_id, result)
        logger.info("Garment refit %s/%s (hair, %s -> %s): Swing default on: %s", character_name, item_id, old_fsig,
                    fsig, "ok" if result.get("ok") else f"refused — {result.get('error')}")
    return done


def refit_character(character_name: str) -> Optional[List[str]]:
    """Refit the character's outdated fits (``outdated_fits``, the Swing
    default's ``swing_default_fits``, the too-small refusals ``refused_fits``,
    then ``outdated_body_fits`` / ``refused_body_fits``) under its garment run lock (``garments.hold_all``:
    no CPU refit starts beside the FIFO meanwhile, Ruling A30). None when a
    chain runs (lock held / FIFO active / a refit beside it) — nothing was
    touched; else the item ids refitted (``"<item>@<body id>"`` for a fit on
    an outfit body)."""
    from app.core import base_body, garment_fit, garments, garment_store as gs
    from app.models.character import get_character_profile
    if not garments.hold_all(character_name):
        return None
    done: List[str] = []
    try:
        profile = get_character_profile(character_name) or {}
        base = base_body.current_base(character_name, profile=profile)
        try:
            from app.core import garment_source
            kept = garment_source.backfill(character_name)
            if kept:
                logger.info("Garment refit %s: base views kept with %d image group(s)", character_name, kept)
        except Exception:  # noqa: BLE001 — the refits below do not depend on it
            logger.exception("Garment refit %s: keeping the base views failed", character_name)
        for item_id, kind, fsig, method in outdated_fits(character_name, profile=profile):
            old = gs.read_record(gs.garment_path(character_name, item_id, fsig, "fit").with_suffix(".json"))
            # The inputs as they are BEFORE the refit (a refit never changes them).
            stamp = refusal_stamp(character_name, item_id, kind, fsig, method, base[1], profile=profile)
            gs.start(character_name, item_id, "fit")
            try:
                if method == gs.HAIRDECK:
                    _refit_hairdeck(character_name, item_id, kind, fsig, base[0], profile)
                elif method == gs.HAAR:
                    _refit_haar(character_name, item_id, kind, fsig, base[0], profile)
                elif method == gs.SHOE:
                    # Footwear (plan 2026-11-10-footwear-rigid-shoes Task 25): the shoe source is cached
                    # under the item's ssig — the refit is the fit alone, CPU only, never a hub job; the
                    # record notes ``refitted.from_body_sha256`` when the body bytes changed as well.
                    from app.core import garment_footwear
                    garment_footwear.fit(character_name, item_id, fsig, profile=profile, schedule=False)
                else:
                    garments._fit(character_name, item_id, kind, fsig, base[0], profile)
            except base_body.MissingInput as e:
                # Inputs gone (prepared mesh / HairDeck hair / HAAR seeds): the next chain run rebuilds them.
                gs.end(character_name, item_id, "fit")
                logger.info("Garment refit %s/%s (%s): skipped — %s", character_name, item_id, fsig, e)
                continue
            except garments._Refused as e:
                result = garments._refusal(character_name, item_id, fsig, "fit", e.error, e.gates, [])
            except Exception as e:  # noqa: BLE001 — reported as the fit's failure, the sweep goes on
                result = garments._refusal(character_name, item_id, fsig, "fit", str(e) or type(e).__name__,
                                           None, [])
            else:
                gs.end(character_name, item_id, "fit")
                result = {"ok": True, "fsig": fsig, "ran": ["fit"]}
                done.append(item_id)
            if not result.get("ok"):
                result["refusal_stamp"] = stamp
            garments._note_outcome(character_name, item_id, result)
            logger.info("Garment refit %s/%s (%s, %s): fit_version %s -> %s: %s", character_name, item_id,
                        kind, fsig, old.get("fit_version"), garment_fit.expected_fit_version(old),
                        "ok" if result.get("ok") else f"refused — {result.get('error')}")
        if base is not None and base[1]:
            done += _refit_swing_default(character_name, profile, base)
            done += _retry_refused(character_name, profile, base[0], done)
            done += _refit_bodies(character_name, profile, base[1])
            done += _refit_footwear(character_name, profile, base)
    finally:
        garments.release_all(character_name)
    return done


def work_count(character_name: str, *, profile: Optional[Dict[str, Any]] = None) -> int:
    """How many units a run of the character would refit (the tracked task's label): every lister of
    ``refit_character`` plus the stale outfit-body postures. Read-only; 0 when nothing is to do."""
    from app.core import outfit_bodies
    if profile is None:
        from app.models.character import get_character_profile
        profile = get_character_profile(character_name) or {}
    base = set(outdated_fits(character_name, profile=profile)) | set(refused_fits(character_name, profile=profile))
    bodies = set(outdated_body_fits(character_name, profile=profile)) \
        | set(refused_body_fits(character_name, profile=profile))
    shoes = {i for i, _old, _new in outdated_footwear_fits(character_name, profile=profile)} \
        | set(outdated_footwear_sources(character_name, profile=profile))
    swing = {i for i, _old, _new in swing_default_fits(character_name, profile=profile)}
    postures = outfit_bodies.stale_posture_bodies(character_name, profile=profile)
    return len(base) + len(bodies) + len(shoes) + len(swing) + len(postures)


def _count(character_name: str) -> Optional[int]:
    """``work_count``, None when it cannot be read (the run goes ahead, untracked count)."""
    try:
        return work_count(character_name)
    except Exception:  # noqa: BLE001 — the label only
        logger.exception("Garment refit %s: work count unreadable", character_name)
        return None


#: ``_attempt``'s status for a character whose garment chain runs.
BUSY = "busy"


def _posture(name: str) -> List[str]:
    """``outfit_bodies.match_stale_postures`` as the sweep words it; never raises."""
    try:
        # Outfit bodies from before the posture match get their base's posture first
        # (outfit_body_posture.py; CPU, refits the fits on a turned body itself).
        from app.core.outfit_bodies import match_stale_postures
        return [f"posture@{body_id}" for body_id in match_stale_postures(name)]
    except Exception:  # noqa: BLE001 — one character never stops the sweep
        logger.exception("Garment refit sweep: posture match of %s failed", name)
        return []


def tracked(character_name: str, run: Any) -> Optional[List[str]]:
    """``run()`` (a refit of the character: returns what it refitted, None when a garment chain runs) as a
    tracked CPU task (``refit_pool.track``, label ``Refit · <name> (n fits)``) — the manual refits (the
    ``fit_refit`` improvement) are registered like the sweep's, in-process or not. None: the track is discarded
    (nothing was done); an exception finishes it failed and propagates."""
    from app.core import refit_pool
    label = refit_pool.fits_label(character_name, _count(character_name))
    tid = refit_pool.track(character_name, label, pending=False)
    try:
        with refit_pool.blender_wait_label(tid, label):
            done = run()
    except Exception as e:  # noqa: BLE001 — finished failed, then raised to the caller
        refit_pool.finish(tid, error=str(e) or type(e).__name__)
        raise
    if done is None:
        refit_pool.discard(tid)
    else:
        refit_pool.finish(tid)
    return done


def _sweep_one(name: str, *, task_id: str, pause: float, retries: int, retry_s: float) -> List[str]:
    """The serial sweep's unit (today's order): posture once, then ``refit_character`` retried while busy."""
    from app.core import refit_pool
    if refit_pool.cancelled(task_id):
        logger.info("Garment refit sweep: %s cancelled while it waited", name)
        refit_pool.release(task_id)
        return []
    label = refit_pool.fits_label(name, _count(name)) if task_id else ""
    if task_id:
        refit_pool.activate(task_id, label)
    with refit_pool.blender_wait_label(task_id, label):
        out = _posture(name)
    try:
        for attempt in range(retries + 1):
            with refit_pool.blender_wait_label(task_id, label):
                done = refit_character(name)
            if done is not None:
                break
            if attempt < retries:
                time.sleep(retry_s)
        else:
            logger.info("Garment refit sweep: %s stayed busy — left for the next start", name)
            refit_pool.finish(task_id, error="garment run in progress — left for the next start")
            return out
        refit_pool.finish(task_id)
        return out + done
    except Exception as e:  # noqa: BLE001 — one character never stops the sweep
        logger.exception("Garment refit sweep: %s failed", name)
        refit_pool.finish(task_id, error=str(e) or type(e).__name__)
        return out
    finally:
        if pause:
            time.sleep(pause)


def _attempt(name: str, task_id: str, first: bool, pause: float) -> Tuple[str, List[str]]:
    """The parallel sweep's unit, on an orchestrator thread: posture on the ``first`` attempt, then one
    ``refit_character``. ``(BUSY, posture part)`` when the garment chain runs (the track stays pending, the
    scheduler retries later), else ``("done", what was refitted)``; a failure finishes the track failed and
    returns the posture part as done."""
    from app.core import refit_pool
    if first and refit_pool.cancelled(task_id):
        logger.info("Garment refit sweep: %s cancelled while it waited", name)
        refit_pool.release(task_id)
        return "done", []
    if _busy(name):
        return BUSY, []
    label = refit_pool.fits_label(name, _count(name)) if task_id else ""
    if task_id:
        refit_pool.activate(task_id, label)
    with refit_pool.blender_wait_label(task_id, label):
        out = _posture(name) if first else []
    try:
        with refit_pool.blender_wait_label(task_id, label):
            done = refit_character(name)
    except Exception as e:  # noqa: BLE001 — fails this character only
        logger.exception("Garment refit sweep: %s failed", name)
        refit_pool.finish(task_id, error=str(e) or type(e).__name__)
        return "done", out
    finally:
        if pause:
            time.sleep(pause)
    if done is None:
        return BUSY, out
    refit_pool.finish(task_id)
    return "done", out + done


def _nice_thread() -> None:
    try:
        # Low priority: a per-thread nice value (Linux; elsewhere it stays normal).
        os.setpriority(os.PRIO_PROCESS, threading.get_native_id(), 10)
    except (AttributeError, OSError):
        pass


def _sweep_parallel(names: List[str], tracks: Dict[str, str], workers: int, *, pause: float, retries: int,
                    retry_s: float) -> Dict[str, List[str]]:
    """Up to ``workers`` characters at once, each on its own orchestrator thread (its fits in order, under its
    run lock); the compute goes to the refit pool. A busy character goes back to the end and is tried again
    ``retry_s`` later (at most ``retries`` times) without holding a slot."""
    from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
    from app.core import refit_pool
    out: Dict[str, List[str]] = {}
    later: List[Tuple[float, str, int]] = []  # (due, name, attempt)
    partial: Dict[str, List[str]] = {}
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="garment-refit",
                            initializer=_nice_thread) as ex:
        running = {ex.submit(_attempt, name, tracks.get(name, ""), True, pause): (name, 0) for name in names}
        while running or later:
            now = time.monotonic()
            for item in [x for x in later if x[0] <= now]:
                later.remove(item)
                _due, name, attempt = item
                running[ex.submit(_attempt, name, tracks.get(name, ""), False, pause)] = (name, attempt)
            if not running:
                time.sleep(max(0.0, min(x[0] for x in later) - time.monotonic()))
                continue
            timeout = max(0.0, min(x[0] for x in later) - time.monotonic()) if later else None
            finished, _ = wait(list(running), timeout=timeout, return_when=FIRST_COMPLETED)
            for fut in finished:
                name, attempt = running.pop(fut)
                try:
                    status, items = fut.result()
                except Exception:  # noqa: BLE001 — _attempt never raises; defensive
                    logger.exception("Garment refit sweep: %s failed", name)
                    refit_pool.finish(tracks.get(name, ""), error="refit failed")
                    continue
                if status == BUSY:
                    partial[name] = partial.get(name, []) + items
                    if attempt < retries:
                        later.append((time.monotonic() + retry_s, name, attempt + 1))
                    else:
                        logger.info("Garment refit sweep: %s stayed busy — left for the next start", name)
                        refit_pool.finish(tracks.get(name, ""),
                                          error="garment run in progress — left for the next start")
                        if partial.get(name):
                            out[name] = partial[name]
                    continue
                done = partial.get(name, []) + items
                if done:
                    out[name] = done
    return out


def sweep(characters: Optional[Iterable[str]] = None, *, pause: float = SWEEP_PAUSE_S,
          retries: int = BUSY_RETRIES, retry_s: float = BUSY_RETRY_S,
          workers: Optional[int] = None) -> Dict[str, List[str]]:
    """Refit every character's outdated fits (default: every character, dormant and pooled ones included).
    ``workers`` characters at once (default ``refit_pool.workers()``: the ``server.refit_workers`` setting in the
    server, 1 elsewhere); 1 = one character after the other, in-process — the order and pauses of before. Every
    character with work is a tracked CPU task from the start (``pending`` until its turn, ``running`` while it
    refits — Game-Admin's header). A busy character is retried ``retries`` times ``retry_s`` apart, then left
    for the next start. Character -> item ids refitted (characters with none left out). Never raises."""
    from app.core import refit_pool
    out: Dict[str, List[str]] = {}
    try:
        if characters is None:
            from app.models.character import list_available_characters
            characters = list_available_characters(include_pooled=True, include_dormant=True)
        names = list(characters)
        n = refit_pool.workers() if workers is None else max(1, int(workers))
        tracks: Dict[str, str] = {}
        for name in names:
            count = _count(name)
            if count is None or count > 0:
                tracks[name] = refit_pool.track(name, refit_pool.fits_label(name, count), pending=True)
        if n > 1 and len(names) > 1:
            return _sweep_parallel(names, tracks, min(n, len(names)), pause=pause, retries=retries, retry_s=retry_s)
        for name in names:
            done = _sweep_one(name, task_id=tracks.get(name, ""), pause=pause, retries=retries, retry_s=retry_s)
            if done:
                out[name] = done
    except Exception:  # noqa: BLE001
        logger.exception("Garment refit sweep failed")
    return out


def _run_sweep(delay: float) -> None:
    _nice_thread()
    time.sleep(delay)
    done = sweep()
    if done:
        logger.info("Garment refit sweep: %s fit(s) refitted for %s", sum(map(len, done.values())),
                    ", ".join(sorted(done)))


def start_sweep(delay: float = SWEEP_DELAY_S) -> threading.Thread:
    """Start the boot sweep on a daemon thread (server lifespan)."""
    thread = threading.Thread(target=_run_sweep, args=(delay,), name="garment-refit-sweep", daemon=True)
    thread.start()
    return thread
