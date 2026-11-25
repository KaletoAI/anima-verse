"""Part items (plan-anhaenger, design G): a buckle, a pendant or a side charm as an item of its own.

A PART is an ``outfit_piece`` in mode ``accessory`` without a slot whose ``jewellery.kind`` is ``charm``
(``accessory_spec``): its own name, description, image and ONE img2mesh mesh (``accessory_pendant.run(<part id>)``,
store ``<world>/jewellery/<part>/<psig>/``). A HOST (a necklace or a belt) refers to its parts by link
(``accessory_spec.links``); the link decides where the part sits, the host's build takes the part's mesh.

A part is worn only through its host: it never lies in an inventory, a room or a shop (``inventory`` refuses the
write and hides a stored entry), it is never put on a slot (``is_part`` guards the outfit paths), and the outfit text
names it once, through its host (``compose_text``).

Locks: an item's read-modify-write holds ``outfit_piece_lock(item)``; a link check and a part's deletion also hold
``keyed_lock("accessory_part", part)``. Order: host before part.
"""
import re
from typing import Any, Dict, Iterable, List, Optional

from app.core.log import get_logger

logger = get_logger("accessory_parts")

#: The words a part's image prompt is built from (``part_image_prompt``): the subject per role (``{m}`` = the material
#: word taken over from the host text, with its space, or nothing), the tail, and the material / colour words one of
#: which may be taken over. Only POSITIVE words: a negation ("no chain") is moved to the negative prompt
#: (``prompt_compose.split_negations``), which an engine without a negative input drops — the 2026-11-25 acceptance
#: got pendants hanging on a chain and buckles on a strap piece, and the mesher modelled the chain with them.
PART_IMAGE_SUBJECT: Dict[str, str] = {
    "buckle": "a single {m}belt buckle, the bare metal buckle frame with its prong",
    "pendant": "a single {m}pendant, the pendant alone with its small top loop",
    "charm": "a single small {m}charm, the charm alone with its small top loop"}
PART_IMAGE_TAIL = "front view, isolated product photo, plain white background"
PART_MATERIAL_WORDS = ("gold", "golden", "silver", "copper", "brass", "bronze", "iron", "steel", "pewter", "bone",
                       "wooden", "jade", "amber", "pearl")
#: A new part's own defaults per role (``make_part``): its size (longest side, mm) and how it is fastened.
ROLE_SIZE_MM: Dict[str, float] = {"buckle": 50.0, "pendant": 18.0, "charm": 25.0}
ROLE_MOUNT: Dict[str, str] = {"buckle": "flat", "pendant": "hang", "charm": "hang"}
#: Which host kind takes which role.
HOST_ROLES: Dict[str, tuple] = {"belt": ("buckle", "charm"), "necklace": ("pendant",)}

REFUSED_WEAR = "A part item is worn through its chain or belt"


def _spec(item: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    from app.core import accessory_spec
    return accessory_spec.of_item(item)


def is_part(item: Optional[Dict[str, Any]]) -> bool:
    """Whether ``item`` is a part item: an outfit piece whose ``jewellery.kind`` is ``charm``."""
    if not isinstance(item, dict) or item.get("category") != "outfit_piece":
        return False
    raw = ((item.get("outfit_piece") or {}).get("jewellery") or {})
    return isinstance(raw, dict) and raw.get("kind") == "charm"


def is_part_id(item_id: str) -> bool:
    """``is_part`` of the stored item ``item_id`` (False when there is none)."""
    if not item_id:
        return False
    from app.models.inventory import get_item
    return is_part(get_item(item_id))


def part_spec(item: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The normalized ``charm`` block of a part item, None for any other item."""
    if not is_part(item):
        return None
    spec = _spec(item)
    return dict(spec["charm"]) if spec else None


def effective_size_mm(link: Dict[str, Any], part: Optional[Dict[str, Any]]) -> float:
    """The size of a linked part: the link's own, else the part's (``charm.size_mm``)."""
    if link.get("size_mm") is not None:
        return float(link["size_mm"])
    from app.core.accessory_spec import CHARM_DEFAULTS
    return float((part_spec(part) or CHARM_DEFAULTS)["size_mm"])


def effective_mount(link: Dict[str, Any], part: Optional[Dict[str, Any]]) -> str:
    """How a linked part is fastened: a pendant always hangs from its chain's lowest point, a buckle lies flat; a
    charm takes the link's mount, else the part's own."""
    if link.get("role") == "pendant":
        return "hang"
    if link.get("role") == "buckle":
        return "flat"
    if link.get("mount"):
        return str(link["mount"])
    from app.core.accessory_spec import CHARM_DEFAULTS
    return str((part_spec(part) or CHARM_DEFAULTS)["mount"])


def validate_links(host_id: str, spec: Optional[Dict[str, Any]]) -> None:
    """``ValueError`` when a link of the host ``host_id`` (``spec`` normalized) names a missing item, an item that
    is no part, or the host itself. Each part is read under ``keyed_lock("accessory_part", id)`` (a deletion of the
    part holds it too)."""
    from app.core import accessory_spec
    from app.core.keyed_lock import keyed_lock
    from app.models.inventory import get_item
    for link in accessory_spec.links(spec):
        pid = link["item"]
        if pid == host_id:
            raise ValueError(f"{pid} cannot be a part of itself")
        with keyed_lock("accessory_part", pid):
            part = get_item(pid)
            if not part:
                raise ValueError(f"linked item {pid} does not exist")
            if not is_part(part):
                raise ValueError(f"{pid} is not a part item")


def all_items() -> List[Dict[str, Any]]:
    from app.models.inventory import list_items, list_shared_items
    seen, out = set(), []
    for item in list(list_items()) + [{**i, "_shared": True} for i in list_shared_items()]:
        iid = item.get("id")
        if iid and iid not in seen:
            seen.add(iid)
            out.append(item)
    return out


def used_by(part_id: str) -> List[Dict[str, Any]]:
    """``[{item_id, name, role}]`` of every world and library item whose links name ``part_id``, by item id. No
    cache (admin and save paths only)."""
    from app.core import accessory_spec
    out = []
    for item in all_items():
        spec = _spec(item)
        if not spec or spec.get("kind") == "charm":
            continue
        for link in accessory_spec.links(spec):
            if link["item"] == part_id:
                out.append({"item_id": item["id"], "name": item.get("name") or item["id"], "role": link["role"],
                            "shared": bool(item.get("_shared"))})
                break
    return sorted(out, key=lambda e: e["item_id"])


def part_ids_of(item: Optional[Dict[str, Any]]) -> List[str]:
    """The linked part ids of a host item, in link order without repeats."""
    from app.core import accessory_spec
    out: List[str] = []
    for link in accessory_spec.links(_spec(item)):
        if link["item"] not in out:
            out.append(link["item"])
    return out


# --- the state of the links (read-only) -----------------------------------------------------------------------------

REASON_PART_MISSING = "Linked {role} not built yet — Build mesh spends 1 hub job"
REASON_PART_GONE = "Linked {role} item {id} no longer exists — the {host} is shown without it"
REASON_PART_NO_IMAGE = "Linked {role} has no image — generate it in Items (1 image job)"


def part_states(spec: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Per link of the host ``spec`` (normalized): ``{**link, state, reason, psig, part_name, size_mm, mount, flip}``
    with the EFFECTIVE size and mount (the link's, else the part's). ``state`` is the part mesh's
    (``accessory_pendant.pendant_state``: ready / running / missing / refused / failed / no_image) or ``gone`` — the
    item is missing or no part. Read-only, no job."""
    from app.core import accessory_pendant, accessory_spec
    from app.models.inventory import get_item
    out: List[Dict[str, Any]] = []
    host = str((spec or {}).get("kind") or "piece")
    for link in accessory_spec.links(spec):
        role = accessory_spec.ROLE_NAMES.get(link["role"], "Part").lower()
        part = get_item(link["item"])
        row = {**link, "psig": "", "part_name": (part or {}).get("name") or link["item"]}
        if not is_part(part):
            out.append({**row, "state": "gone", "size_mm": float(link.get("size_mm") or 0.0) or None,
                        "mount": effective_mount(link, None), "flip": False,
                        "reason": REASON_PART_GONE.format(role=role, id=link["item"], host=host)})
            continue
        ps = part_spec(part) or {}
        row.update({"size_mm": effective_size_mm(link, part), "mount": effective_mount(link, part),
                    "flip": bool(ps.get("flip"))})
        try:
            st = accessory_pendant.pendant_state(link["item"])
        except ValueError:
            st = {"state": "gone", "reason": REASON_PART_GONE.format(role=role, id=link["item"], host=host),
                  "psig": ""}
        reason = st["reason"]
        if st["state"] == "missing" and reason == accessory_pendant.REASON_MISSING:
            reason = REASON_PART_MISSING.format(role=role)
        elif st["state"] == "no_image":
            reason = REASON_PART_NO_IMAGE.format(role=role)
        out.append({**row, "state": st["state"], "reason": reason, "psig": st.get("psig") or ""})
    return out


def ready_inputs(states: List[Dict[str, Any]]) -> List[list]:
    """The geometry entries of the READY parts (``accessory_build.geometry_inputs``): ``[role, index, item, psig,
    size_mm, at_deg, mount, drop_cm, flip]``."""
    return [[s["role"], int(s["index"]), s["item"], s["psig"], float(s["size_mm"]), float(s["at_deg"]),
             str(s["mount"]), float(s["drop_cm"]), bool(s["flip"])] for s in states if s["state"] == "ready"]


# --- the outfit text ------------------------------------------------------------------------------------------------

_WITH = re.compile(r"\bwith\b", re.I)


def compose_text(host_frag: str, part_frags: List[str]) -> str:
    """The host's outfit text with its parts' texts (each named once): a part text already in the host text
    (case-insensitive) or empty is left out; ``"{host} with {a}"`` / ``"{host} with {a}, {b} and {c}"`` — or
    ``", "`` instead of a second ``with`` when the host text already has the word."""
    host = (host_frag or "").strip()
    low = host.lower()
    parts: List[str] = []
    for frag in part_frags:
        f = (frag or "").strip()
        if not f or f.lower() in low or f.lower() in (p.lower() for p in parts):
            continue
        parts.append(f)
    if not parts:
        return host
    tail = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]
    if not host:
        return tail
    return f"{host}, {tail}" if _WITH.search(host) else f"{host} with {tail}"


_ARTICLES = {"a", "an", "the", "of", "and", "with", "on", "in"}


def _words(text: str) -> List[str]:
    return [w for w in re.split(r"[^a-z]+", (text or "").lower()) if w]


def host_mentions_part(host_frag: str, part_frag: str) -> bool:
    """Whether the host's text already describes the part: a content word of the part text (no article, no
    ``PART_MATERIAL_WORDS``) also stands in the host text."""
    host = set(_words(host_frag))
    for w in _words(part_frag):
        if w in _ARTICLES or w in PART_MATERIAL_WORDS:
            continue
        if w in host:
            return True
    return False


def host_text(item: Dict[str, Any], base: str) -> str:
    """``base`` (the host's own fragment) composed with its linked parts' texts (``compose_text``); parts that are
    gone or no part are left out."""
    ids = part_ids_of(item)
    if not ids:
        return base
    from app.models.inventory import get_item
    frags = []
    for pid in ids:
        part = get_item(pid)
        if is_part(part):
            frags.append(str(part.get("prompt_fragment") or ""))
    return compose_text(base, frags)


# --- the image prompt and a new part ----------------------------------------------------------------------------------

def part_image_prompt(role: str, host_text: str) -> str:
    """The image prompt of a new part: its subject with at most ONE material word taken over from the host text (the
    first token in ``PART_MATERIAL_WORDS``) and the tail. The host text itself never goes in — "copper belt" would
    draw the whole belt."""
    subject = PART_IMAGE_SUBJECT.get(role, PART_IMAGE_SUBJECT["charm"])
    word = next((w for w in _words(host_text) if w in PART_MATERIAL_WORDS), "")
    return f"{subject.format(m=word + ' ' if word else '')}, {PART_IMAGE_TAIL}"


def make_part(host_id: str, role: str, at: str = "front") -> str:
    """A new part item for the host ``host_id`` in ``role`` (buckle / pendant / charm), linked on the host: a buckle or
    a pendant replaces the host's link, a charm is appended (``ValueError`` at ``MAX_CHARMS``). Never put in an
    inventory or a room. The image is the caller's (one image job). Returns the part's id."""
    from app.core import accessory_spec
    from app.models.inventory import add_item, get_item, outfit_piece_lock, update_item
    with outfit_piece_lock(host_id):
        host = get_item(host_id)
        spec = _spec(host)
        if not host or not spec:
            raise ValueError(f"{host_id} is no accessory")
        if role not in HOST_ROLES.get(spec["kind"], ()):
            raise ValueError(f"a {spec['kind']} has no {role}")
        if role == "charm" and len(spec.get("charms") or []) >= accessory_spec.MAX_CHARMS:
            raise ValueError(f"a belt carries at most {accessory_spec.MAX_CHARMS} charms")
        name = f"{host.get('name') or host_id} {accessory_spec.ROLE_NAMES[role]}"
        part = add_item(name=name, category="outfit_piece",
                        image_prompt=part_image_prompt(role, str(host.get("prompt_fragment") or "")),
                        prompt_fragment="",
                        outfit_piece={"slots": [], "mesh_mode": "accessory",
                                      "jewellery": {"kind": "charm",
                                                    "charm": {"size_mm": ROLE_SIZE_MM[role],
                                                              "mount": ROLE_MOUNT[role]}}})
        pid = part["id"]
        raw = dict((host.get("outfit_piece") or {}).get("jewellery") or {})
        if role == "charm":
            raw["charms"] = list(spec.get("charms") or []) + [{"item": pid, "at": at}]
        else:
            raw[role] = {"item": pid}
        update_item(host_id, {"outfit_piece": {**(host.get("outfit_piece") or {}), "jewellery": raw}})
    logger.info("Part %s (%s) made for %s", pid, role, host_id)
    return pid


# --- export ----------------------------------------------------------------------------------------------------------

def expand_with_parts(ids: Iterable[str]) -> List[str]:
    """``ids`` plus every part their items link, sorted, without repeats."""
    from app.models.inventory import get_item
    out = set()
    for iid in ids:
        if not iid:
            continue
        out.add(iid)
        out.update(part_ids_of(get_item(iid)))
    return sorted(out)


def remap_links(raw: Dict[str, Any], mapping: Dict[str, str]) -> Dict[str, Any]:
    """A stored ``jewellery`` dict with its link item ids renamed through ``mapping`` (ids not in it stay)."""
    out = dict(raw or {})
    for key in ("pendant", "buckle"):
        if isinstance(out.get(key), dict) and out[key].get("item") in mapping:
            out[key] = {**out[key], "item": mapping[out[key]["item"]]}
    if isinstance(out.get("charms"), list):
        out["charms"] = [{**c, "item": mapping.get(c.get("item"), c.get("item"))} if isinstance(c, dict) else c
                         for c in out["charms"]]
    return out
