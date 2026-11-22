"""The running SCENE of a pose: ONE layer for every pose interaction a
package ticks — a free pair or group (``interaction_engine``, scene id = the
interaction id, which a pose switch keeps) and a furniture run
(``prop_action_engine``, scene id = its ``execution_id``; pair, group or solo).
Neither engine keeps a copy of what lives here (plan pair scene, Task 3):

- the BEAT: hook ``scene.active(scene_id, kind, members, roles, pose_key,
  lead_role, delta_game_s, readouts)`` once per scheduler step for each scene
  that spent online GAME time running (``kind`` "interaction" | "prop_action";
  ``roles`` = ``{clip role: name}``, ``{}`` for a solo run; ``readouts`` =
  :func:`readouts`, what the clients reported). A frozen world beats not at all. Furniture
  beats come from ``prop_action_engine.advance`` through :func:`emit_active`
  (its run keeps its own game clock across restarts); free scenes beat from
  :func:`advance`, whose clock is this process's memory: the first step after
  a start credits only a scene that started after the process did.
- the FINALE: one participant's closing clip (catalog ``finale_animation``, or
  what a package derives, :func:`finale_kind`), started by a package with
  :func:`begin_finale` at a TEMPO in [0.2, 1] (1 = the clip's own speed). It
  plays ``loop_count`` cycles — the clip sidecar's count, whether the clip
  loops or not; 1 without one — so its REAL length is clip length x cycles /
  tempo. An animation, it runs on the SYSTEM clock (a frozen world still
  finishes it) and lives in this process only.
- "end after the finale" (:func:`end_after_finale`): the scene ends a given
  number of REAL seconds after that person's finale has fully played.
- the METERS row and HOLD (providers ``scene.meters`` / ``scene.meter_hold``)
  and the alt half a member plays (:func:`set_alt`).
- the TEMPO and the CLIP CLOCK: per scene one clock in CLIP seconds,
  ``clip_s += Δreal_unfrozen · tempo`` (the tempo before the step) on every
  beat and every payload read (:func:`clip_clock`). The tempo is refreshed on
  each beat from the provider ``scene.tempo(scene_id, members, roles,
  pose_key, lead_role) -> float | None``, clamped to [0.2, 1]; 1 without a
  provider or an answer. A pose switch (same scene, new pose) restarts the
  clock at 0 and keeps the tempo. Animation time is REAL time: the clock runs
  on the motion clock, so a frozen world stops it. It lives in this process:
  a scene first seen (its start, or the first touch after a server start)
  counts from 0.
- the CHANNEL READOUTS (:func:`report_readouts`, route
  ``POST /play/scene/readouts``): a 3D client that renders the scene reports
  a summary per (receiver, channel, entering) at most once a second; the
  latest per key, no older than READOUT_FRESH_S, rides on every beat, its
  ``reaches`` summed since the previous beat. Measurements only — what they
  mean is the package's. They live in this process.
"""
import math
import uuid
from datetime import timedelta
from threading import Lock

from app.core.game_time import GameTime
from app.core.log import get_logger
from app.core.timeutils import game_speed_factor, game_time, motion_time, utc_now

logger = get_logger("pose_scene")

#: Seconds a finale stays in the payload past its clip's own length. The
#: clips last about a second, the worldmap poll of a bystander 3 s: every
#: client must see the block once to play it (once per ``id``, § A8c), and a
#: new finale of the same person is refused until it is gone.
FINALE_SHOW_S = 4.0
#: The tempo range of a finale (and, later, of a scene): 1 = the clip's own speed.
TEMPO_MIN, TEMPO_MAX = 0.2, 1.0
#: REAL seconds between two beats of a scene that fills gauges: the travel
#: ticker's step, where the world tick alone would let a finale wait a minute.
METER_BEAT_REAL_S = 5.0
#: A ticker step a little early still beats (the ticker itself runs every 5 s).
_BEAT_SLACK = 0.8
#: SYSTEM seconds a client readout stays usable: an older one is no
#: measurement any more (the client closed, the figure left the view).
READOUT_FRESH_S = 5.0
#: SYSTEM seconds between two accepted reports of one key. The clients send
#: once a second; the network may bring two of them closer together, so the
#: floor is a little lower than 1 s (_BEAT_SLACK) — a report lost to jitter
#: would lose the reaches it carries.
READOUT_MIN_INTERVAL_S = 1.0 * _BEAT_SLACK
#: The most rows one report may carry (a scene has a few channels).
READOUT_MAX_ROWS = 32
#: The number fields of a report row, each finite and >= 0.
_READOUT_NUMBERS = ("insertion_of_depth", "part_radius_m", "rest_radius_m", "depth_m")

_mutex = Lock()
#: name -> the finale it plays: {id, scene_id, kind, role, alt, pose_key,
#: started, duration_s, loop_count, tempo}
_finales = {}
#: scene id -> {name, kind, due} — a pending "end after the finale"
_pending_ends = {}
#: free scene id -> {"game": GameTime of its last beat, "real": utc of it}
_beats = {}
#: scene id -> its clip clock {clip_s, tempo, motion: motion_time of the last
#: step, clip: what the payload last named it plays (None = not yet)}
_clocks = {}
#: scene id -> {(receiver, channel, entering): the latest accepted row +
#: "at" (utc of it) + "reaches" (summed since the last read)}
_readouts = {}
#: The game time of this process's first step (:func:`advance`): a free scene
#: started before it gets no credit for the time the server was down.
_boot = {"game": None}


# ---------------------------------------------------------------- scenes

def _engine():
    from app.core import prop_action_engine
    return prop_action_engine


def _furniture_run(scene_id):
    """The furniture run ``scene_id`` names (any status), None when it is none."""
    if not isinstance(scene_id, str) or not scene_id:
        return None
    from app.core import prop_action_store as store
    return store.get(scene_id)


def _free_interaction(name, profile=None):
    """``name``'s running FREE pair (not one a furniture run owns), or None."""
    from app.core.interaction_engine import get_interaction
    inter = get_interaction(name, profile)
    if not inter or inter.get("execution_kind") == "prop_action":
        return None
    return inter


def _free_scene(inter):
    from app.core.interaction_engine import members_of
    roles = members_of(inter)
    return dict(scene_id=inter["id"], kind="interaction", members=list(roles.values()),
                roles=roles, pose_key=str(inter.get("pose_key") or ""))


def _run_scene(run):
    engine = _engine()
    return dict(scene_id=run["execution_id"], kind="prop_action",
                members=[name for _, name in engine._members(run)],
                roles=dict(sorted((run["data"].get("clip_roles") or {}).items())) if run["members"] else {},
                pose_key=engine._held_pose(run))


def scene_of(name: str, profile=None) -> dict | None:
    """``{scene_id, kind, members, roles, pose_key}`` of the scene ``name`` plays
    in right now — an ACTIVE furniture run (sleep excluded), else a free pair —
    or None."""
    if not isinstance(name, str) or not name:
        return None
    from app.core import prop_action_store as store
    execution_id = store.held(store.person_key(name))
    run = store.get(execution_id) if execution_id else None
    if run and run["status"] == "active" and run["definition"]["ability"] != "sleep":
        return _run_scene(run)
    inter = _free_interaction(name, profile)
    return _free_scene(inter) if inter else None


def _notify_names(names):
    from app.core.keyed_lock import _after_locks
    from app.core.sync_topics import avatars
    names = tuple(names)
    _after_locks(lambda: avatars(names, ("self", "scene")))


def clamp_tempo(tempo) -> float:
    """``tempo`` inside [TEMPO_MIN, TEMPO_MAX]; 1 for anything that is no number."""
    try:
        value = float(tempo)
    except (TypeError, ValueError):
        return TEMPO_MAX
    if not math.isfinite(value):
        return TEMPO_MAX
    return min(TEMPO_MAX, max(TEMPO_MIN, value))


# ---------------------------------------------------------------- finale

def finale_kind(pose_key: str, name: str = "", *, profile=None) -> str:
    """The finale clip kind of ``pose_key``: its catalog ``finale_animation``,
    else what a package derives for it (``auto_finale``). "" when there is
    none or the clip is missing in the shape the pose needs: a multi-person
    pose needs a complete clip with one role per participant, a solo pose a
    solo clip — for ``name``'s own figure when given (its set chain, as
    ``animated_for``)."""
    from app.core.animation_clips import role_counts
    from app.core.pose_catalog import get_catalog
    entry = get_catalog("pose").get(pose_key or "") or {}
    kind = entry.get("finale_animation") or auto_finale(pose_key, entry)
    if not kind:
        return ""
    people = entry.get("participants", 1)
    roles = role_counts().get(kind, 1)
    if people != 1:
        return kind if roles == people else ""
    if roles != 1:
        return ""
    return kind if _solo_finale_clip(kind, name, profile) else ""


def auto_finale(pose_key: str, entry: dict | None = None) -> str:
    """The finale kind a package derives for a pose without an explicit one
    (provider ``pose.finale_animation(pose_key, animation, participants) -> kind``,
    e.g. a naming convention on the pose's own clip); "" without a provider
    or an answer. Unchecked — ``finale_kind`` checks the clip's shape."""
    from app.core.hooks import get_provider
    provider = get_provider("pose.finale_animation")
    if provider is None:
        return ""
    if entry is None:
        from app.core.pose_catalog import get_catalog
        entry = get_catalog("pose").get(pose_key or "") or {}
    try:
        kind = provider(pose_key=pose_key or "", animation=entry.get("animation") or "",
                        participants=int(entry.get("participants") or 1))
    except Exception as e:
        logger.debug("finale provider failed for %s: %s", pose_key, e)
        return ""
    return kind.strip().lower() if isinstance(kind, str) else ""


def _solo_finale_clip(kind, name, profile):
    """``{set, ...}`` of the solo clip ``name`` would play (any set without a
    name), None when there is none."""
    from app.core.animation_clips import clip_entries
    if not name:
        return next(({"set": e["set"]} for e in clip_entries() if e["kind"] == kind and not e["role"]), None)
    from app.core.animation_sets import resolve_sets
    from app.core.movement import clip_file_for
    return clip_file_for(kind, resolve_sets(name, profile), free_only=False)


def finale_cycles(meta) -> int:
    """How many cycles a clip plays AS A FINALE: the sidecar's ``loop_count``
    (1..99) whether the clip loops or not — a finale always ends, so an
    endless loop or a clip without a count plays once."""
    from app.core.animation_clips import stored_loop_count
    return stored_loop_count(meta) or 1


def _finale_clip_s(kind, role, name):
    """``(seconds, cycles)`` of the finale half this person plays at its own
    speed: the clip's length times :func:`finale_cycles`. ``(0.0, 1)``
    without a usable length."""
    from app.core.animation_clips import clip_entries, clip_meta
    if role:
        entry = next((e for e in clip_entries() if e["kind"] == kind and e["role"] == role), None)
        meta = clip_meta(kind, entry["set"]) if entry else None
    else:
        found = _solo_finale_clip(kind, name, None)
        meta = clip_meta(kind, found["set"]) if found else None
    try:
        duration = float((meta or {}).get("duration_s") or 0)
    except (TypeError, ValueError):
        return 0.0, 1
    if not (math.isfinite(duration) and duration > 0):
        return 0.0, 1
    cycles = finale_cycles(meta)
    return duration * cycles, cycles


def _finale_live(finale) -> bool:
    return bool(finale) and ((utc_now() - finale["started"]).total_seconds()
                             < finale["duration_s"] + FINALE_SHOW_S)


def _start_finale(scene_id, name, pose, role, tempo):
    """Books the finale (the caller checked the scene) — ``(result, kind)``."""
    kind = finale_kind(pose, name)
    if not kind:
        return dict(ok=False, reason="no_finale"), ""
    clip_s, cycles = _finale_clip_s(kind, role, name)
    if clip_s <= 0:
        return dict(ok=False, reason="no_finale"), ""
    # Playing an alt half: the finale closes in that alt when its clip has
    # one for the role, else in the role's own half.
    alt = ""
    if role:
        from app.core.animation_clips import clip_alts
        from app.core.interaction_engine import get_interaction
        current = str((get_interaction(name) or {}).get("alt") or "")
        if current and current in (clip_alts(kind).get(role) or []):
            alt = current
    with _mutex:
        if _finale_live(_finales.get(name)):
            return dict(ok=False, reason="finale_playing"), ""
        _finales[name] = dict(id=uuid.uuid4().hex[:12], scene_id=scene_id, kind=kind,
                              role=role or None, alt=alt, pose_key=pose, started=utc_now(),
                              duration_s=clip_s / tempo, loop_count=cycles, tempo=tempo)
    return dict(ok=True, reason=""), kind


def begin_finale(scene_id: str, name: str, *, tempo: float = 1.0) -> dict:
    """Starts ``name``'s finale in its running scene at ``tempo`` (clamped
    to [0.2, 1]) — ``{ok, reason}``.

    Refused: ``invalid`` arguments; a furniture run that is not active (or
    sleeps) ``not_active``, a name outside it ``not_participant``; a free
    scene that is not ``name``'s ``no_scene``; a pose without a usable
    finale clip ``no_finale``; a finale of that person still shown
    ``finale_playing``. Everyone in the scene is told to refresh;
    ``scene.finale_started(scene_id, name, kind, pose_key)`` fires after every
    lock is released. Takes the run's lock — never call it under a profile lock."""
    from app.core.keyed_lock import _after_locks
    from app.core.hooks import emit
    if not isinstance(scene_id, str) or not scene_id or not isinstance(name, str):
        return dict(ok=False, reason="invalid")
    tempo = clamp_tempo(tempo)
    if _furniture_run(scene_id) is not None:
        engine = _engine()
        from app.core import prop_action_store as store
        with engine._lock(scene_id):
            run = store.get(scene_id)
            if run is None or run["status"] != "active" or run["definition"]["ability"] == "sleep":
                return dict(ok=False, reason="not_active")
            if name not in [member for _, member in engine._members(run)]:
                return dict(ok=False, reason="not_participant")
            pose = engine._held_pose(run)
            role = (next((r for r, member in run["data"].get("clip_roles", {}).items() if member == name), "")
                    if run["members"] else "")
            result, kind = _start_finale(scene_id, name, pose, role, tempo)
            if result["ok"]:
                engine._notify(run)
    else:
        inter = _free_interaction(name)
        if not inter or inter["id"] != scene_id:
            return dict(ok=False, reason="no_scene")
        pose = str(inter.get("pose_key") or "")
        result, kind = _start_finale(scene_id, name, pose, inter["role"], tempo)
        if result["ok"]:
            from app.core.interaction_engine import members_of
            _notify_names(members_of(inter).values())
    if result["ok"]:
        _after_locks(lambda: emit("scene.finale_started", scene_id=scene_id, name=name,
                                  kind=kind, pose_key=pose))
    return result


def finale_for(name: str) -> dict | None:
    """The worldmap row's ``finale`` block of ``name`` (§ A8c):
    ``{id, kind, role, alt, elapsed_s, duration_s, loop_count, tempo}`` — the
    half (``role`` a..e, None for a solo clip; ``alt`` its alt half, ``""``
    none) a client plays ONCE per ``id`` for ``loop_count`` cycles at
    ``tempo`` (1 = the clip's own speed), then back to the scene's own clip;
    ``duration_s`` is the WHOLE finale in REAL seconds, every cycle at that
    tempo. Shown until ``FINALE_SHOW_S`` past its end, so a polling bystander
    sees it too; ``elapsed_s`` in SYSTEM seconds."""
    with _mutex:
        finale = _finales.get(name)
        if not _finale_live(finale):
            return None
        elapsed = (utc_now() - finale["started"]).total_seconds()
        return dict(id=finale["id"], kind=finale["kind"], role=finale["role"],
                    alt=finale.get("alt") or "",
                    elapsed_s=round(max(0.0, elapsed), 3), duration_s=round(finale["duration_s"], 3),
                    loop_count=int(finale.get("loop_count") or 1),
                    tempo=round(float(finale.get("tempo") or 1.0), 3))


def end_finales(scene_id=None, *, expired_only=False):
    """Drops the finales of one scene (its end — its clip clock goes too) or
    every expired one; the ``scene.finale_done(scene_id, name, kind,
    pose_key)`` events fire after the locks."""
    from app.core.keyed_lock import _after_locks
    from app.core.hooks import emit
    with _mutex:
        if scene_id is not None and not expired_only:
            _clocks.pop(scene_id, None)
            _readouts.pop(scene_id, None)
        done = [(name, f) for name, f in _finales.items()
                if (scene_id is None or f["scene_id"] == scene_id)
                and not (expired_only and _finale_live(f))]
        for name, _f in done:
            _finales.pop(name, None)
    for name, finale in done:
        _after_locks(lambda name=name, finale=finale: emit(
            "scene.finale_done", scene_id=finale["scene_id"], name=name,
            kind=finale["kind"], pose_key=finale["pose_key"]))


def end_after_finale(scene_id: str, name: str, delay_s: float) -> bool:
    """Ends the scene ``delay_s`` REAL seconds after ``name``'s finale in it
    has fully played (every cycle; at once + ``delay_s`` when none plays).
    False when ``scene_id`` is not ``name``'s running scene. The end is
    settled by :func:`advance` (the travel ticker's step); a scene that ended
    or changed id meanwhile is left alone. Due now, it ends right here."""
    if not isinstance(scene_id, str) or not isinstance(name, str):
        return False
    scene = scene_of(name)
    if not scene or scene["scene_id"] != scene_id:
        return False
    try:
        delay = max(0.0, float(delay_s))
    except (TypeError, ValueError):
        delay = 0.0
    if not math.isfinite(delay):
        delay = 0.0
    now = utc_now()
    with _mutex:
        finale = _finales.get(name)
        played = now
        if finale and finale["scene_id"] == scene_id:
            played = max(now, finale["started"] + timedelta(seconds=finale["duration_s"]))
        due = played + timedelta(seconds=delay)
        _pending_ends[scene_id] = dict(name=name, kind=scene["kind"], due=due)
    if due <= now:
        _settle_ends()
    else:
        # The travel ticker settles it: wake it, so it plans its next step
        # with this end in view (``travel_engine._next_beat_s``).
        from app.core.travel_engine import get_travel_ticker
        get_travel_ticker().wake()
    return True


def next_end_in_s() -> float | None:
    """REAL seconds until the next pending scene end (negative = due), None
    without one — so the travel ticker wakes for it."""
    with _mutex:
        if not _pending_ends:
            return None
        return (min(p["due"] for p in _pending_ends.values()) - utc_now()).total_seconds()


def _settle_ends() -> int:
    now = utc_now()
    with _mutex:
        due = [(scene_id, p) for scene_id, p in _pending_ends.items() if p["due"] <= now]
        for scene_id, _p in due:
            _pending_ends.pop(scene_id, None)
    ended = 0
    for scene_id, pending in due:
        try:
            if pending["kind"] == "prop_action":
                result = _engine().cancel(pending["name"], scene_id)
                ended += result.get("status") != "refused"
            else:
                from app.core.interaction_engine import end_interaction
                ended += bool(end_interaction(pending["name"], reason="ended", interaction_id=scene_id))
        except Exception:
            logger.exception("scene %s: the end after the finale failed", scene_id)
    return ended


# ---------------------------------------------------------------- hold / alt

def hold(scene_id: str, name: str, hold: bool) -> dict:
    """``name`` holds its own gauge back (or lets go) in its running scene —
    ``{ok, reason}``. What holding means is the package's (provider
    ``scene.meter_hold(scene_id, name, hold) -> bool``); refused for a
    furniture run that is not active (``not_active``), a non-participant,
    a free scene that is not ``name``'s (``no_scene``) and when no package
    takes it (``unsupported``)."""
    from app.core.hooks import get_provider
    if not isinstance(scene_id, str) or not scene_id or not isinstance(name, str) or not isinstance(hold, bool):
        return dict(ok=False, reason="invalid")
    run = _furniture_run(scene_id)
    if run is not None:
        engine = _engine()
        if run["status"] != "active":
            return dict(ok=False, reason="not_active")
        members = [member for _, member in engine._members(run)]
        if name not in members:
            return dict(ok=False, reason="not_participant")
    else:
        inter = _free_interaction(name)
        if not inter or inter["id"] != scene_id:
            return dict(ok=False, reason="no_scene")
        from app.core.interaction_engine import members_of
        members = list(members_of(inter).values())
    provider = get_provider("scene.meter_hold")
    try:
        taken = bool(provider and provider(scene_id=scene_id, name=name, hold=hold))
    except Exception as e:
        logger.debug("meter hold provider failed for %s: %s", name, e)
        taken = False
    if not taken:
        return dict(ok=False, reason="unsupported")
    _notify_names(members)
    return dict(ok=True, reason="")


def set_alt(scene_id: str, name: str, alt: str) -> dict:
    """``name`` plays the alt half ``alt`` of its clip role in its running
    scene (``""`` = the role's own half again) — ``{ok, reason}``; refused
    for a furniture run that is not active, a non-participant and a free
    scene that is not ``name``'s (``no_scene``); the rest is
    ``interaction_engine.set_alt``."""
    from app.core import interaction_engine
    if not isinstance(scene_id, str) or not scene_id or not isinstance(name, str) or not isinstance(alt, str):
        return dict(ok=False, reason="invalid")
    if _furniture_run(scene_id) is not None:
        engine = _engine()
        from app.core import prop_action_store as store
        with engine._lock(scene_id):
            run = store.get(scene_id)
            if run is None or run["status"] != "active":
                return dict(ok=False, reason="not_active")
            if name not in [member for _, member in engine._members(run)]:
                return dict(ok=False, reason="not_participant")
            result = interaction_engine.set_alt(name, alt)
            if result["ok"]:
                engine._notify(run)
        return result
    inter = _free_interaction(name)
    if not inter or inter["id"] != scene_id:
        return dict(ok=False, reason="no_scene")
    result = interaction_engine.set_alt(name, alt)
    if result["ok"]:
        _notify_names(interaction_engine.members_of(inter).values())
    return result


# ---------------------------------------------------------------- meters

def meter_rows(scene_id: str, members, pose_key: str, since_game_s: float = 0.0) -> list:
    """The gauges of a scene from the package that keeps them (provider
    ``scene.meters(scene_id, members, pose_key) -> [{name, value, label?,
    rate?, holdable?, held?}]``); [] without one or when it fails (a gauge
    never breaks the HUD row). Values are clamped to 0..100 and carried
    forward by ``rate`` (points per GAME second) over ``since_game_s``, the
    game time since the scene's last beat; the rate handed out is per REAL
    second (0 = frozen world)."""
    from app.core.hooks import get_provider
    provider = get_provider("scene.meters")
    if provider is None:
        return []
    try:
        rows = provider(scene_id=scene_id, members=list(members), pose_key=pose_key)
    except Exception as exc:
        logger.warning("scene.meters provider failed: %s", exc)
        return []
    factor = game_speed_factor()
    since = max(0.0, float(since_game_s or 0.0)) if factor > 0 else 0.0
    out = []
    for row in rows or []:
        try:
            value = float(row["value"])
        except (KeyError, TypeError, ValueError):
            continue
        if isinstance(row.get("name"), str) and math.isfinite(value):
            try:
                rate = max(0.0, float(row.get("rate") or 0.0))
            except (TypeError, ValueError):
                rate = 0.0
            if not math.isfinite(rate):
                rate = 0.0
            value = min(100.0, max(0.0, value + rate * since))
            out.append(dict(name=row["name"], value=round(value, 1),
                            rate=round(rate * factor, 4),
                            label=str(row.get("label") or ""),
                            # ``hold`` applies to this gauge / it is held now
                            holdable=row.get("holdable") is True, held=row.get("held") is True))
    return out


def meters(scene_id: str, name: str = "") -> list:
    """The meters row of a running scene: a furniture run by its id, a free
    scene through a member ``name`` (a free scene is found on its members'
    profiles). [] for anything else."""
    run = _furniture_run(scene_id)
    if run is not None:
        from app.core import prop_action_store as store
        if run["status"] in store.TERMINAL or run["status"] == "awaiting_consent":
            return []
        return _engine()._meters(run)
    inter = _free_interaction(name) if name else None
    if not inter or inter["id"] != scene_id:
        return []
    scene = _free_scene(inter)
    return meter_rows(scene_id, scene["members"], scene["pose_key"],
                      _free_since_s(scene_id, inter, game_time()))


# ---------------------------------------------------------------- tempo / clip clock

def _step_clock(scene_id, clip=None):
    """Integrates the clip clock of ``scene_id`` up to now and returns a
    copy. ``clip`` (the payload's name of what the clients play) restarts
    the clock at 0 when it differs from the one stored — a pose switch; a
    beat passes None and never judges it (the payload knows the clip)."""
    now = motion_time()
    with _mutex:
        clock = _clocks.get(scene_id)
        if clock is None:
            clock = _clocks[scene_id] = dict(clip_s=0.0, tempo=TEMPO_MAX, motion=now, clip=clip)
        elif clip is not None and clock["clip"] is not None and clock["clip"] != clip:
            clock.update(clip_s=0.0, motion=now, clip=clip)
        else:
            clock["clip_s"] += max(0.0, now - clock["motion"]) * clock["tempo"]
            clock["motion"] = now
            if clip is not None:
                clock["clip"] = clip
        return dict(clock)


def clip_clock(scene_id: str, clip: str) -> tuple:
    """``(clip_s, tempo)`` of a running scene as the worldmap's
    ``interaction`` block states it (§ A8a): the clip clock stepped up to now
    (CLIP seconds since the clip began, every second at the tempo it ran at)
    and the tempo it runs at now. ``clip`` names what the clients play
    (pose and clip kind); a different one than last time is a pose switch and
    starts at 0."""
    clock = _step_clock(scene_id, clip)
    return round(clock["clip_s"], 3), round(clock["tempo"], 3)


def scene_tempo(scene_id, members, roles, pose_key, lead_role) -> float:
    """The tempo a package gives the scene now (provider ``scene.tempo``),
    clamped to [0.2, 1]; 1 without a provider, without an answer or when it
    fails."""
    from app.core.hooks import get_provider
    provider = get_provider("scene.tempo")
    if provider is None:
        return TEMPO_MAX
    try:
        answer = provider(scene_id=scene_id, members=list(members), roles=dict(roles or {}),
                          pose_key=pose_key, lead_role=lead_role)
    except Exception as exc:
        logger.debug("scene.tempo provider failed for %s: %s", scene_id, exc)
        return TEMPO_MAX
    return clamp_tempo(answer) if answer is not None else TEMPO_MAX


def _beat_tempo(beat):
    """A beat steps the scene's clip clock at the old tempo, then takes the new one."""
    _step_clock(beat["scene_id"])
    tempo = scene_tempo(beat["scene_id"], beat["members"], beat["roles"], beat["pose_key"],
                        beat["lead_role"])
    with _mutex:
        clock = _clocks.get(beat["scene_id"])
        if clock is not None:
            clock["tempo"] = tempo


def _prune_clocks(free_ids):
    """Drops the clocks and readouts of scenes that no longer run (a free
    scene that is gone, a furniture run that ended or vanished)."""
    from app.core import prop_action_store as store
    with _mutex:
        ids = [scene_id for scene_id in {*_clocks, *_readouts} if scene_id not in free_ids]
    for scene_id in ids:
        run = _furniture_run(scene_id)
        if run is None or run["status"] in store.TERMINAL:
            with _mutex:
                _clocks.pop(scene_id, None)
                _readouts.pop(scene_id, None)


# ---------------------------------------------------------------- readouts

def _readout_row(raw):
    """A report row as stored (``reaches`` included), None when it is not
    one: names non-empty strings, the receiver not the entering figure, the
    numbers finite and >= 0, ``reaches`` a whole number >= 0."""
    if not isinstance(raw, dict):
        return None
    names = [raw.get(field) for field in ("receiver", "channel", "entering")]
    if not all(isinstance(name, str) and name for name in names) or names[0] == names[2]:
        return None
    row = dict(receiver=names[0], channel=names[1], entering=names[2])
    for field in _READOUT_NUMBERS:
        value = raw.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        value = float(value)
        if not (math.isfinite(value) and value >= 0):
            return None
        row[field] = value
    reaches = raw.get("reaches")
    if isinstance(reaches, bool) or not isinstance(reaches, int) or reaches < 0:
        return None
    row["reaches"] = reaches
    return row


def _may_watch(viewer, members) -> bool:
    """``viewer`` (a user's avatar) sees the scene: it plays in it, or one of
    its members is someone it can address (``perception.addressable_for``:
    the same room, or within earshot out in the open)."""
    if not viewer:
        return False
    if viewer in members:
        return True
    from app.core.perception import addressable_for
    return bool(set(addressable_for(viewer)) & set(members))


def report_readouts(scene_id: str, rows, *, viewer: str = "", admin: bool = False) -> int:
    """Stores a client's readout report of the running scene ``scene_id`` —
    the number of rows taken. A row is taken when it is well formed
    (:func:`_readout_row`), its receiver and entering figure are members of
    that scene while it runs (an active furniture run, or a free scene;
    :func:`scene_of` of the receiver), the reporting user is an admin or its
    avatar ``viewer`` watches the scene (:func:`_may_watch`), and its key
    (receiver, channel, entering) took no report in the last
    READOUT_MIN_INTERVAL_S. Everything else is dropped silently. A taken
    row replaces the key's values and adds its ``reaches``."""
    if not isinstance(scene_id, str) or not scene_id or not isinstance(rows, list):
        return 0
    taken = []
    members_of_receiver = {}
    for raw in rows[:READOUT_MAX_ROWS]:
        row = _readout_row(raw)
        if row is None:
            continue
        receiver = row["receiver"]
        if receiver not in members_of_receiver:
            scene = scene_of(receiver)
            members = scene["members"] if scene and scene["scene_id"] == scene_id else None
            members_of_receiver[receiver] = (members if members and (admin or _may_watch(viewer, members))
                                             else None)
        members = members_of_receiver[receiver]
        if not members or row["entering"] not in members:
            continue
        taken.append(row)
    if not taken:
        return 0
    now = utc_now()
    accepted = 0
    with _mutex:
        stored = _readouts.setdefault(scene_id, {})
        for row in taken:
            key = (row["receiver"], row["channel"], row["entering"])
            last = stored.get(key)
            if last and (now - last["at"]).total_seconds() < READOUT_MIN_INTERVAL_S:
                continue
            reaches = row.pop("reaches") + (last["reaches"] if last else 0)
            stored[key] = dict(row, at=now, reaches=reaches)
            accepted += 1
    return accepted


def readouts(scene_id: str) -> list:
    """The readouts of a scene for its beat: per key the latest report no
    older than READOUT_FRESH_S (``{receiver, channel, entering,
    insertion_of_depth, part_radius_m, rest_radius_m, depth_m, reaches,
    source: "client"}``, sorted by key), ``reaches`` summed since the
    previous call — which resets them. Older ones are forgotten. [] when
    nothing was reported."""
    now = utc_now()
    out = []
    with _mutex:
        stored = _readouts.get(scene_id)
        if not stored:
            return []
        for key in sorted(stored):
            row = stored[key]
            if (now - row["at"]).total_seconds() > READOUT_FRESH_S:
                del stored[key]
                continue
            out.append(dict(receiver=row["receiver"], channel=row["channel"], entering=row["entering"],
                            **{field: row[field] for field in _READOUT_NUMBERS},
                            reaches=row["reaches"], source="client"))
            row["reaches"] = 0
        if not stored:
            _readouts.pop(scene_id, None)
    return out


# ---------------------------------------------------------------- beats

def emit_active(*, scene_id, kind, members, roles, pose_key, delta_game_s):
    """Fires ``scene.active`` for one scene after every lock is released —
    first stepping its clip clock and refreshing its tempo (provider
    ``scene.tempo``, asked outside every lock), then taking its client
    readouts (:func:`readouts`)."""
    from app.core.hooks import emit
    from app.core.keyed_lock import _after_locks
    from app.core.pose_catalog import lead_role_of
    beat = dict(scene_id=scene_id, kind=kind, members=list(members), roles=dict(roles or {}),
                pose_key=pose_key, lead_role=lead_role_of(pose_key),
                delta_game_s=delta_game_s, readouts=[])
    def fire():
        _beat_tempo(beat)
        beat["readouts"] = readouts(scene_id)
        emit("scene.active", **beat)
    _after_locks(fire)


def _baseline(scene_id, inter):
    """The game time a free scene's next beat counts from: its last beat, else
    its start when it started after this process's first step, else now."""
    with _mutex:
        last = _beats.get(scene_id)
    if last:
        return last["game"]
    boot = _boot["game"]
    try:
        started = GameTime.parse(inter["started_at_game"])
    except (KeyError, TypeError, ValueError):
        started = None
    if boot is not None and started is not None and started >= boot:
        return started
    return None


def _free_since_s(scene_id, inter, now):
    base = _baseline(scene_id, inter)
    return max(0.0, float((now - base).total_seconds)) if base is not None else 0.0


def _free_scenes():
    """Every running free scene once: ``{scene_id: (scene, interaction)}``."""
    from app.models.character import get_character_profile, list_available_characters
    found = {}
    for name in list_available_characters():
        try:
            inter = _free_interaction(name, get_character_profile(name) or {})
        except Exception:
            continue
        if inter and inter["id"] not in found:
            found[inter["id"]] = (_free_scene(inter), inter)
    return found


def advance(now: GameTime, *, due_only: bool = False) -> int:
    """One scheduler step of the scene layer: settles pending ends
    (:func:`end_after_finale`), drops expired finales and beats every free
    scene that spent online game time (``scene.active``, kind
    "interaction"). ``due_only`` (the travel ticker's step): only scenes
    whose package keeps gauges, at most once per METER_BEAT_REAL_S real
    seconds — the world tick beats every scene. A frozen world beats none.
    Returns the beats fired."""
    from app.models.world import is_world_frozen
    if _boot["game"] is None:
        _boot["game"] = now
    _settle_ends()
    end_finales(expired_only=True)
    if due_only:
        from app.core.hooks import get_provider
        if get_provider("scene.meters") is None:
            return 0                          # nothing fills: the world tick's beat is enough
    scenes = _free_scenes()
    with _mutex:
        for gone in set(_beats) - set(scenes):
            _beats.pop(gone, None)
    _prune_clocks(set(scenes))
    if is_world_frozen():
        return 0
    real_now = utc_now()
    fired = 0
    for scene_id, (scene, inter) in scenes.items():
        base = _baseline(scene_id, inter)
        if base is None:
            with _mutex:
                _beats[scene_id] = dict(game=now, real=real_now)
            continue
        delta = float((now - base).total_seconds)
        if delta <= 0:
            continue
        if due_only:
            with _mutex:
                last = _beats.get(scene_id)
            if last and (real_now - last["real"]).total_seconds() < METER_BEAT_REAL_S * _BEAT_SLACK:
                continue
            if not meter_rows(scene_id, scene["members"], scene["pose_key"]):
                continue
        with _mutex:
            _beats[scene_id] = dict(game=now, real=real_now)
        emit_active(scene_id=scene_id, kind="interaction", members=scene["members"],
                    roles=scene["roles"], pose_key=scene["pose_key"], delta_game_s=delta)
        fired += 1
    return fired
