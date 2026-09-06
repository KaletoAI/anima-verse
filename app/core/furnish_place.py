"""Stage 3 of the furnishing job: the relational plan and its repair rounds
(plan-furnish-v2.md § 2 B1/B2/B4/B5/B6, § 3, task 4).

ONE ``furnish_place`` call plans all four groups at once — floor, wall,
ceiling, surface — in the anchor vocabulary of :mod:`app.core.furnish_solver`;
the solver turns that plan into geometry. This module is the orchestration
between the two: which pieces go into the prompt, how high a wall piece hangs
when the model does not say, and what happens to the pieces that did not fit.

PURE ORCHESTRATION — no DB, no world lookups. The library, the room geometry
and the LLM hop are handed in; what comes back is a solver result in the
SOLVER's frame (the caller owns the yard's origin shift, because only the
caller knows there is one).

THE PIECES ARE PLACED BEFORE THEY EXIST (decision E6). Since the job places
first and generates afterwards, most needs have no prop yet when the plan is
made. Such a need travels under a TEMPORARY id ``need:<key>`` carrying its
own dims — the solver never asks whether a prop id is real, and ``accept``
rewrites the id to the freshly created prop.

REPAIR RUNS PER PASS (B6). The first solve reports every failure with the pass
it happened in; each pass that has errors gets ONE re-plan call that sees only
its own errors and re-plans only its own group. The new group slice replaces
the old one and the WHOLE plan is solved again — not because the other groups
are re-planned, but because the solver is deterministic: replaying an
unchanged group reproduces its geometry exactly, including its placement ids,
while a frozen-and-merged result would leave surface children pointing at
supports that a repaired floor pass has just moved. (That the replay really is
identical is the solver's own promise, checked by hand in
``scripts/smoke_furnish_solver.py`` row 12.) A repair is kept only when that
pass places at least as much and fails at most as often as before.
"""

from typing import Any, Callable, Dict, List, Optional, Sequence

from app.core import furnish_needs
from app.core.log import get_logger

logger = get_logger(__name__)

#: Prop id of a need the library does not serve yet (E6). The colon makes it
#: unmintable as a real prop id (``props.safe_prop_id`` rejects it), so a
#: placeholder can never collide with a library piece — and never reach the
#: stored layout either: ``room_furnish.accept`` rewrites it.
NEED_ID_PREFIX = "need:"

#: The passes a REPAIR round runs in. Ceiling rides with the wall pass: both
#: hang above the floor pieces, both fail for the same reasons, and one wall
#: re-plan is cheaper than two calls that would contradict each other.
PASSES = ("floor", "wall", "surface")
#: The four mounts, which is what ``phase_counts`` reports — the dialog shows
#: the ceiling group separately even though it is repaired with the wall.
MOUNTS = ("floor", "wall", "ceiling", "surface")
MOUNT_PASS = {"floor": "floor", "wall": "wall", "ceiling": "wall",
              "surface": "surface"}

#: A wall piece with no ``base_m`` from the model hangs at eye height (E2).
WALL_BASE_CENTRE_M = 1.5
#: Keyword table for the fallback: ``(keywords, mode, metres)``. ``centre``
#: means the value is the piece's MIDDLE (base = centre − height/2), ``base``
#: means it is the lower edge itself. First match wins, so the more specific
#: word stands first — a "wall lamp" is a lamp, not a board.
_BASE_RULES = (
    (("mirror",), "centre", 1.6),
    (("picture", "painting", "poster", "portrait", "photo", "screen",
      "artwork", "tapestry"), "centre", 1.5),
    (("sconce", "lantern", "torch", "lamp", "light"), "base", 1.6),
    (("shelf", "cabinet", "cupboard", "rack", "board"), "base", 1.3),
)
#: How many failures one repair prompt lists — enough to name every piece of a
#: pass, short enough that the prompt stays a prompt.
MAX_ERROR_LINES = 20


# ── the pieces to place ─────────────────────────────────────────────────

def need_prop_id(need: Dict[str, Any]) -> str:
    """The id the PLAN calls this need by: its library piece when it has one,
    the temporary ``need:<key>`` when it has still to be built (E6)."""
    pid = str(need.get("prop_id") or "").strip()
    return pid or f"{NEED_ID_PREFIX}{need.get('key') or ''}"


def wall_base_default(*, kind: str = "", category: str = "", name: str = "",
                      height_m: float = 0.0) -> float:
    """Where a wall piece's LOWER edge sits when the model names no
    ``base_m`` — the fallback half of decision E2, computed before the call so
    the plan always carries a height. The solver clamps it into the storey.

    Hand-checkable: a 0.6 m picture centres at 1.5 m → base 1.2; a shelf hangs
    at 1.3 whatever its height; anything unclassified centres at 1.5 too, so a
    0.4 m piece lands at 1.3.
    """
    try:
        h = max(0.0, float(height_m or 0.0))
    except (TypeError, ValueError):
        h = 0.0
    hay = " ".join([str(kind or ""), str(category or ""), str(name or "")]).lower()
    for words, mode, value in _BASE_RULES:
        if any(word in hay for word in words):
            return round(value - h / 2 if mode == "centre" else value, 3)
    return round(WALL_BASE_CENTRE_M - h / 2, 3)


def build_items(needs: Sequence[Dict[str, Any]],
                library: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The confirmed furnishing as one entry per PROP the plan may name.

    Every need is placeable — the ones the library serves under their prop id
    with the library's facts, the ones still to be built under their temporary
    id with their own (E6). Two needs served by the SAME library piece become
    one entry with the counts added, because the plan speaks about props, not
    about needs; two unbuilt needs never merge, their keys differ.
    """
    from app.core.room_recipe import placement_stack_facts

    items: List[Dict[str, Any]] = []
    by_id: Dict[str, Dict[str, Any]] = {}
    for need in needs:
        if not isinstance(need, dict):
            continue
        pid = need_prop_id(need)
        prop = library.get(pid) or {}
        want = furnish_needs.count(need.get("count"))
        if pid in by_id:
            by_id[pid]["count"] = furnish_needs.count(by_id[pid]["count"] + want)
            continue
        kind = str(need.get("kind") or "")
        entry = {
            "id": pid,
            "name": str(prop.get("name") or kind or pid),
            "count": want,
            # A library piece's mount is the library's answer (the match stage
            # already refused a piece whose mount differs); an unbuilt need
            # answers for itself, and anything unclassified stands on the floor.
            "mount": (str(prop.get("mount") or "") if prop
                      else str(need.get("mount") or "")) or "floor",
            "width_m": prop.get("width_m") or need.get("width_m"),
            "depth_m": prop.get("depth_m") or need.get("depth_m"),
            "height_m": prop.get("height_m") or need.get("height_m"),
            # How many meshes this piece may alternate between (B17) and how
            # deep its mesh sinks into the ground — both facts of the VARIANT
            # a placement draws, read through the recipe's own resolver so the
            # solver stacks on the same height the payload renders.
            "variants": len(prop.get("variant_tiers") or []) or 1,
            "ground_offset_m": float(
                (placement_stack_facts(prop or None, None) or {})
                .get("ground_offset_m") or 0.0),
            "kind": kind,
            "category": str(need.get("category") or prop.get("category") or ""),
        }
        entry["base_m"] = (wall_base_default(
            kind=entry["kind"], category=entry["category"], name=entry["name"],
            height_m=float(entry["height_m"] or 0.0))
            if entry["mount"] == "wall" else None)
        by_id[pid] = entry
        items.append(entry)
    return items


def solver_props(items: Sequence[Dict[str, Any]],
                 library: Dict[str, Dict[str, Any]]
                 ) -> Dict[str, Dict[str, Any]]:
    """What the solver needs to know per prop id — for every id it may see:
    the items to place AND the props already standing in the room.

    Beside the three metres that is ``mount`` (which pass a piece belongs to),
    ``variants`` (how many meshes it may alternate between, B17) and
    ``ground_offset_m`` (how deep the mesh sinks — the solver's ``y0`` and its
    stacking height are measured from it).
    """
    from app.core.room_recipe import placement_stack_facts

    props: Dict[str, Dict[str, Any]] = {}
    for pid, prop in library.items():
        props[pid] = {
            "width_m": prop.get("width_m"), "depth_m": prop.get("depth_m"),
            "height_m": prop.get("height_m"),
            "mount": str(prop.get("mount") or "") or "floor",
            "variants": len(prop.get("variant_tiers") or []) or 1,
            "ground_offset_m": float(
                (placement_stack_facts(prop, None) or {})
                .get("ground_offset_m") or 0.0)}
    for item in items:
        props[item["id"]] = {
            "width_m": item["width_m"], "depth_m": item["depth_m"],
            "height_m": item["height_m"], "mount": item["mount"],
            "variants": item["variants"],
            "ground_offset_m": item["ground_offset_m"]}
    return props


def group_items(items: Sequence[Dict[str, Any]]
                ) -> Dict[str, List[Dict[str, Any]]]:
    """The prompt's four lists, one per mount — the plan is written group by
    group because the anchors are."""
    groups: Dict[str, List[Dict[str, Any]]] = {m: [] for m in MOUNTS}
    for item in items:
        mount = str(item.get("mount") or "floor")
        groups[mount if mount in groups else "floor"].append(
            {"id": item["id"], "name": item["name"], "count": item["count"],
             "width_m": item["width_m"], "depth_m": item["depth_m"],
             "height_m": item["height_m"]})
    return groups


# ── counting ────────────────────────────────────────────────────────────

def phase_counts(result: Dict[str, Any],
                 mount_by_id: Dict[str, str]) -> Dict[str, Dict[str, int]]:
    """``{mount: {placed, unplaced}}`` over all four mounts — what the review
    dialog shows per group and what the notification summarises."""
    out = {m: {"placed": 0, "unplaced": 0} for m in MOUNTS}
    for entry in result.get("placed") or []:
        mount = mount_by_id.get(str(entry.get("prop_id") or ""), "floor")
        out.get(mount, out["floor"])["placed"] += 1
    for entry in result.get("unplaced") or []:
        mount = str(entry.get("pass") or "floor")
        out.get(mount, out["floor"])["unplaced"] += 1
    return out


def pass_summary(counts: Dict[str, Dict[str, int]]) -> Dict[str, Dict[str, int]]:
    """The same numbers folded onto the three REPAIR passes (ceiling joins the
    wall), which is how the repair loop and the notification read them."""
    out = {p: {"placed": 0, "unplaced": 0} for p in PASSES}
    for mount, entry in counts.items():
        target = out[MOUNT_PASS.get(mount, "floor")]
        target["placed"] += int(entry.get("placed") or 0)
        target["unplaced"] += int(entry.get("unplaced") or 0)
    return out


# ── the plan ────────────────────────────────────────────────────────────

def _plan_of(answer: Any) -> List[Dict[str, Any]]:
    """The ``plan`` array of an answer — falling back to an unwrapped array,
    which is the one shape a model reaches for without being asked."""
    raw = answer.get("plan") if isinstance(answer, dict) else None
    if not isinstance(raw, list):
        raw = answer.get("_list") if isinstance(answer, dict) else None
    return [entry for entry in (raw or []) if isinstance(entry, dict)]


def _split(plan: Sequence[Dict[str, Any]], mount_by_id: Dict[str, str]
           ) -> Dict[str, List[Dict[str, Any]]]:
    """The plan cut into the three repair passes. An entry naming a prop the
    item list does not have lands in the floor pass — that is where the solver
    reports it as an unknown prop, so the floor re-plan is the one that can fix
    it."""
    out: Dict[str, List[Dict[str, Any]]] = {p: [] for p in PASSES}
    for entry in plan:
        mount = mount_by_id.get(str(entry.get("prop") or ""), "floor")
        out[MOUNT_PASS.get(mount, "floor")].append(entry)
    return out


def _fill_base(plan: Sequence[Dict[str, Any]],
               defaults: Dict[str, float]) -> List[Dict[str, Any]]:
    """Give every wall entry the ``base_m`` fallback the model left out (E2).
    The model's own value always wins; the solver clamps either way."""
    out: List[Dict[str, Any]] = []
    for entry in plan:
        pid = str(entry.get("prop") or "")
        if pid in defaults and entry.get("base_m") is None:
            entry = dict(entry, base_m=defaults[pid])
        out.append(entry)
    return out


def _error_lines(unplaced: Sequence[Dict[str, Any]],
                 names: Dict[str, str]) -> List[Dict[str, str]]:
    """The failures of one pass as the prompt's ``{pass, text}`` rows. The
    solver's reason already ends in one concrete alternative (constraint 5) —
    all that is added here is which piece it was about."""
    lines: List[Dict[str, str]] = []
    for entry in unplaced[:MAX_ERROR_LINES]:
        pid = str(entry.get("name") or "?")
        label = names.get(pid, pid)
        text = f"{label} ({pid})" if label != pid else pid
        lines.append({"pass": str(entry.get("pass") or "floor"),
                      "text": f"{text}: {entry.get('reason') or 'did not fit'}"})
    return lines


def _placed_rows(placed: Sequence[Dict[str, Any]],
                 names: Dict[str, str], mount_by_id: Dict[str, str],
                 positions: Dict[str, Sequence[float]]
                 ) -> List[Dict[str, Any]]:
    """The pieces a re-plan must NOT touch, told the way the prompt tells the
    room's own furniture. A child placement stores its ``at`` in its support's
    frame, so its row shows the SUPPORT's position — which is where the piece
    is, and the only number the model can relate anything to."""
    known: Dict[str, Sequence[float]] = dict(positions)
    for entry in placed:
        if not entry.get("on"):
            at = entry.get("at") or [0, 0]
            known[str(entry.get("id") or "")] = [float(at[0]), float(at[1])]
    rows: List[Dict[str, Any]] = []
    for entry in placed:
        pid = str(entry.get("prop_id") or "")
        place_id = str(entry.get("id") or "")
        support = str(entry.get("on") or "")
        at = known.get(support if support else place_id) or entry.get("at") or [0, 0]
        rows.append({
            "id": place_id, "name": names.get(pid, pid),
            "mount": mount_by_id.get(pid, "floor"),
            "x_m": round(float(at[0]), 2), "y_m": round(float(at[1]), 2),
            "yaw": round(float(entry.get("yaw") or 0.0), 1),
            "on": names.get(support, "") if support else ""})
    return rows


def run(*, room_name: str, room_description: str, geom: Dict[str, Any],
        storey_height_m: float, items: Sequence[Dict[str, Any]],
        props: Dict[str, Dict[str, Any]],
        existing: Sequence[Dict[str, Any]],
        template_existing: Sequence[Dict[str, Any]],
        template_openings: Sequence[Dict[str, Any]],
        ask: Callable[[str, str, str], Dict[str, Any]],
        alive: Optional[Callable[[], bool]] = None) -> Dict[str, Any]:
    """Plan the room, solve it, repair it per pass.

    ``ask(system_prompt, user_prompt, label_suffix)`` is the LLM hop — the
    caller owns the task label and the error type. ``alive()`` says whether
    the job still exists; a discarded job stops before the next call.

    Returns ``{"placed", "unplaced", "phase_counts"}`` in the SOLVER's frame.
    """
    from app.core import furnish_solver
    from app.core.prompt_templates import render_task

    names = {item["id"]: item["name"] for item in items}
    mount_by_id = {item["id"]: item["mount"] for item in items}
    defaults = {item["id"]: item["base_m"] for item in items
                if item["mount"] == "wall" and item.get("base_m") is not None}
    groups = group_items(items)
    positions = {str(e.get("id") or ""): [float(e.get("x_m") or 0.0),
                                          float(e.get("y_m") or 0.0)]
                 for e in template_existing}
    alive = alive or (lambda: True)

    def _ask(errors: List[Dict[str, str]], repass: Optional[str],
             extra_existing: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        sys_p, user_p = render_task(
            "furnish_place", room_name=room_name,
            room_description=room_description,
            room_w_m=geom["w_m"], room_d_m=geom["d_m"],
            is_rect=geom["is_rect"], storey_height_m=storey_height_m,
            openings=list(template_openings),
            existing=list(template_existing) + list(extra_existing),
            floor_items=groups["floor"], wall_items=groups["wall"],
            ceiling_items=groups["ceiling"], surface_items=groups["surface"],
            errors=errors, repass=repass)
        suffix = f" (re-plan {repass})" if repass else ""
        return _fill_base(_plan_of(ask(sys_p, user_p, suffix)), defaults)

    def _solve(plans: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
        plan = [entry for name in PASSES for entry in plans[name]]
        result = furnish_solver.solve(
            outline_m=geom["outline_m"], openings=geom["openings"],
            existing=list(existing), plan=plan, props=props,
            storey_height_m=storey_height_m)
        result["phase_counts"] = phase_counts(result, mount_by_id)
        return result

    plans = _split(_ask([], None, []), mount_by_id)
    result = _solve(plans)

    for name in PASSES:
        failures = [u for u in result.get("unplaced") or []
                    if MOUNT_PASS.get(str(u.get("pass") or "floor"),
                                      "floor") == name]
        if not failures or not alive():
            continue
        keep = [e for e in result.get("placed") or []
                if MOUNT_PASS.get(mount_by_id.get(str(e.get("prop_id") or ""),
                                                  "floor"), "floor") != name]
        try:
            replan = _ask(_error_lines(failures, names), name,
                          _placed_rows(keep, names, mount_by_id, positions))
        except Exception as e:  # noqa: BLE001 — a failed repair keeps the plan
            logger.info("furnish_place: re-plan of the %s pass failed (%s) — "
                        "keeping the previous result", name, e)
            continue
        candidate_plans = dict(plans)
        candidate_plans[name] = _split(replan, mount_by_id)[name]
        candidate = _solve(candidate_plans)
        before = pass_summary(result["phase_counts"])[name]
        after = pass_summary(candidate["phase_counts"])[name]
        if (after["placed"] >= before["placed"]
                and after["unplaced"] <= before["unplaced"]):
            plans, result = candidate_plans, candidate
        else:
            logger.info("furnish_place: the %s re-plan placed %d and failed "
                        "%d, against %d and %d before — discarded", name,
                        after["placed"], after["unplaced"], before["placed"],
                        before["unplaced"])
    return result
