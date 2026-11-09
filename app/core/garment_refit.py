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
  more seed when none passes; the sweep refuses instead).

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
    """Refit the character's outdated fits (``outdated_fits``) under its
    garment run lock. None when a chain runs (lock held / FIFO active) —
    nothing was touched; else the item ids refitted."""
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
                    out[name] = done
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
