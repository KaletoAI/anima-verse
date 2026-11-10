"""Boot sweep: refit garment fits made by an older fit algorithm.

A fit record carries ``fit_version`` (``garment_fit.FIT_VERSION[kind]``);
``garments._fit_state`` reports an older or missing one as ``stale`` and the
next chain run of the item re-fits it. Hair is only run on a base model
change or a click, so without this sweep an old fit would stay served until
then. After a server start (``start_sweep``, from the lifespan) one daemon
thread walks the characters one at a time and refits, for every garment
whose CURRENT fsig holds an accepted fit on the CURRENT base model with an
outdated ``fit_version``, the fit step only:

- edit chain: ``garments._fit`` from the cached prepared mesh + images;
- HairDeck: the stored seeds (``garments._fit_seed``), the served seed first
  — HairDeck itself never runs again here (a run's fit step would ask for one
  more seed when none passes; the sweep refuses instead);
- subtract: ``garment_subtract.run_fit`` from the cached cut.

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


def outdated_fits(character_name: str, *, profile: Optional[Dict[str, Any]] = None
                  ) -> List[Tuple[str, str, str, str]]:
    """``[(item_id, kind, fsig, method)]`` of the character's fits that the
    sweep refits: the item's current fsig and method, accepted on the
    current base model, ``fit_version`` older or missing. A fit on another
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
                or record.get("fit_version") == garment_fit.FIT_VERSION[kind]:
            continue
        try:
            current = gs.garment_fsig(character_name, item_id, profile=profile)
            method = gs.garment_method(character_name, item_id, profile=profile)
        except ValueError:
            continue
        if current != fsig or gs.fit_method(record) != method:
            continue
        out.append((item_id, kind, fsig, method))
    return out


def outdated_body_fits(character_name: str, *, profile: Optional[Dict[str, Any]] = None
                       ) -> List[Tuple[str, str, str, str]]:
    """``[(item_id, kind, fsig, body_id)]`` of the character's fits on outfit
    bodies that the sweep refits: accepted on the body as it is stored now,
    ``fit_version`` older or missing, made under the fsig of the fit the base
    model serves now (``garment_store.accepted_fit``); by (item, fsig), then body."""
    from app.core import base_body, garment_fit, garments, garment_store as gs
    if profile is None:
        from app.models.character import get_character_profile
        profile = get_character_profile(character_name) or {}
    base = base_body.current_base(character_name, profile=profile)
    if base is None or not base[1]:
        return []
    out: List[Tuple[str, str, str, str]] = []
    served: Dict[str, Optional[str]] = {}
    for (item_id, fsig), files in sorted(gs.stored_groups(character_name).items()):
        for fit in files:
            body_id = gs.body_of(fit)
            if not body_id or fit.suffix != ".glb" or fit != gs.garment_path(character_name, item_id, fsig, "fit",
                                                                             body=body_id):
                continue
            record = gs.read_record(fit.with_suffix(".json"))
            kind = str(record.get("kind") or "")
            if record.get("accepted") is not True or kind not in garment_fit.FIT_VERSION \
                    or record.get("fit_version") == garment_fit.FIT_VERSION[kind] \
                    or not record.get("body_sha256") \
                    or record.get("body_sha256") != garments.body_sha256(character_name, body_id):
                continue
            if item_id not in served:
                hit = gs.accepted_fit(character_name, item_id, base_model_sha=base[1], profile=profile)
                parsed = gs.parse_name(hit[0]) if hit else None
                served[item_id] = parsed[1] if parsed else None
            if served[item_id] != fsig:
                continue
            out.append((item_id, kind, fsig, body_id))
    return out


def _refit_bodies(character_name: str, profile: Dict[str, Any], base_sha: str) -> List[str]:
    """Refit ``outdated_body_fits`` (caller holds the run lock). Returns
    ``"<item>@<body id>"`` per refitted fit."""
    from app.core import garment_fit, garments, garment_store as gs
    from app.core.keyed_lock import keyed_lock
    done: List[str] = []
    for item_id, kind, fsig, body_id in outdated_body_fits(character_name, profile=profile):
        base_fit = gs.accepted_fit(character_name, item_id, base_model_sha=base_sha, profile=profile)
        if base_fit is None:
            continue
        old = gs.read_record(gs.garment_path(character_name, item_id, fsig, "fit", body=body_id).with_suffix(".json"))
        try:
            # Serialised with the assembly builds' fits on the same body (``garments.body_fit``).
            with keyed_lock("garment_body_fit", f"{character_name}:{body_id}"):
                garments.fit_on_body(character_name, item_id, body_id=body_id, base_fit=base_fit, profile=profile)
        except Exception as e:  # noqa: BLE001 — recorded on that body, the old fit stays served
            error = e.error if isinstance(e, garments._Refused) else (str(e) or type(e).__name__)
            gs.record_body_failure(character_name, item_id, fsig, body_id, error=error,
                                   body_sha=str(old.get("body_sha256") or ""),
                                   base_fit_sha=garments._sha(base_fit[0]),
                                   fit_version=garment_fit.FIT_VERSION[kind])
            outcome = f"refused — {error}"
        else:
            done.append(f"{item_id}@{body_id}")
            outcome = "ok"
        logger.info("Garment refit %s/%s (%s, %s) on outfit body %s: fit_version %s -> %s: %s", character_name,
                    item_id, kind, fsig, body_id, old.get("fit_version"), garment_fit.FIT_VERSION[kind], outcome)
    return done


def _busy(character_name: str) -> bool:
    """A garment chain of the character runs or waits in its FIFO."""
    from app.core import garments
    with garments._lock:
        return character_name in garments._active


def _refit_hairdeck(character_name: str, item_id: str, kind: str, fsig: str, bsig: str,
                    profile: Dict[str, Any]) -> None:
    """Refit HairDeck hair from its stored seeds — the served seed first and
    kept when it passes, else the best passing one (``_choose_seed``). Never
    runs HairDeck: ``_Refused`` when no stored seed passes."""
    from app.core import base_body, garments, garment_store as gs
    hsig = gs.garment_hsig(character_name, item_id, profile=profile)
    seeds = garments._stored_seeds(character_name, item_id, hsig)
    if garments._hairdeck_files(character_name, item_id, hsig)[0] is None or not seeds:
        raise base_body.MissingInput("The HairDeck hair is missing — run the hairdeck step first")
    record = gs.read_record(gs.garment_path(character_name, item_id, fsig, "fit").with_suffix(".json"))
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


def refit_character(character_name: str) -> Optional[List[str]]:
    """Refit the character's outdated fits (``outdated_fits``, then
    ``outdated_body_fits``) under its garment run lock. None when a chain
    runs (lock held / FIFO active) — nothing was touched; else the item ids
    refitted (``"<item>@<body id>"`` for a fit on an outfit body)."""
    from app.core import base_body, garment_fit, garments, garment_store as gs
    from app.models.character import get_character_profile
    lock = gs.char_lock(character_name)
    if _busy(character_name) or not lock.acquire(blocking=False):
        return None
    done: List[str] = []
    try:
        profile = get_character_profile(character_name) or {}
        base = base_body.current_base(character_name, profile=profile)
        for item_id, kind, fsig, method in outdated_fits(character_name, profile=profile):
            old = gs.read_record(gs.garment_path(character_name, item_id, fsig, "fit").with_suffix(".json"))
            gs.start(character_name, item_id, "fit")
            try:
                if method == gs.HAIRDECK:
                    _refit_hairdeck(character_name, item_id, kind, fsig, base[0], profile)
                elif method == gs.SUBTRACT:
                    from app.core import garment_subtract
                    garment_subtract.run_fit(character_name, item_id, kind, fsig, base[0], profile)
                else:
                    garments._fit(character_name, item_id, kind, fsig, base[0], profile)
            except base_body.MissingInput as e:
                # Inputs gone (prepared mesh / HairDeck hair): the next chain run rebuilds them.
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
            garments._note_outcome(character_name, item_id, result)
            logger.info("Garment refit %s/%s (%s, %s): fit_version %s -> %s: %s", character_name, item_id,
                        kind, fsig, old.get("fit_version"), garment_fit.FIT_VERSION[kind],
                        "ok" if result.get("ok") else f"refused — {result.get('error')}")
        if base is not None and base[1]:
            done += _refit_bodies(character_name, profile, base[1])
    finally:
        lock.release()
    return done


def sweep(characters: Optional[Iterable[str]] = None, *, pause: float = SWEEP_PAUSE_S,
          retries: int = BUSY_RETRIES, retry_s: float = BUSY_RETRY_S) -> Dict[str, List[str]]:
    """Refit every character's outdated fits, one character at a time
    (default: every character, dormant and pooled ones included). A busy
    character is retried ``retries`` times ``retry_s`` apart, then left for
    the next start. Character -> item ids refitted (characters with none
    left out). Never raises."""
    out: Dict[str, List[str]] = {}
    try:
        if characters is None:
            from app.models.character import list_available_characters
            characters = list_available_characters(include_pooled=True, include_dormant=True)
        for name in characters:
            try:
                # Outfit bodies from before the posture match get their base's posture first
                # (outfit_body_posture.py; CPU, refits the fits on a turned body itself).
                from app.core.outfit_bodies import match_stale_postures
                matched = match_stale_postures(name)
                if matched:
                    out[name] = [f"posture@{body_id}" for body_id in matched]
            except Exception:  # noqa: BLE001 — one character never stops the sweep
                logger.exception("Garment refit sweep: posture match of %s failed", name)
            try:
                for attempt in range(retries + 1):
                    done = refit_character(name)
                    if done is not None:
                        break
                    if attempt < retries:
                        time.sleep(retry_s)
                else:
                    logger.info("Garment refit sweep: %s stayed busy — left for the next start", name)
                    continue
                if done:
                    out[name] = out.get(name, []) + done
            except Exception:  # noqa: BLE001 — one character never stops the sweep
                logger.exception("Garment refit sweep: %s failed", name)
            if pause:
                time.sleep(pause)
    except Exception:  # noqa: BLE001
        logger.exception("Garment refit sweep failed")
    return out


def _run_sweep(delay: float) -> None:
    try:
        # Low priority: a per-thread nice value (Linux; elsewhere it stays normal).
        os.setpriority(os.PRIO_PROCESS, threading.get_native_id(), 10)
    except (AttributeError, OSError):
        pass
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
