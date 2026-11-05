#!/usr/bin/env python3
"""Smoke: the player payloads show the AVATAR's view of a transformed
character — the alias (and the persona portrait) for a non-knower avatar,
"<alias> (<name>)" for a knower — while every technical key and URL stays the
real name (spec: display-only secrecy).

Usage:  ./.venv/bin/python scripts/smoke_identity_play_payload.py

Throwaway storage + instance (``STORAGE_DIR``/``INSTANCE_DIR`` point at temp
dirs, ``paths.init`` runs BEFORE any world-DB module is imported). No server,
no LLM, no real world. The transformation package is loaded the way the
server loads it (``packages.enabled`` = transformation;
``discover_packages()``) and is the provider of ``identity.*``. The route
functions are called directly; the active avatar is switched with
``account.set_active_character`` (no request context → the account profile).

FIXTURE
    Location "Inn", room "taproom" (entry). Cara (bearer of "amulet"), Kim
    (knower of Cara), Obs (knows nothing), all in the taproom. Persona p1:
    item amulet, alias "Moonveil", max 0, cooldown 0. Cara is transformed
    through ``engine.transform``. The amulet has NO image at first, so the
    persona's portrait_url is "" (``register.active_persona``: an item
    without ``image`` → "").
    Lines recorded AFTER the transformation (``perception.record_utterance``):
      1. Cara: "Good evening." (no addressee)
      2. Kim → [Cara]: "Welcome back."
      3. Storyteller: "Cara sets a cup down."
    A consolidated scene in the taproom with participants [Cara, Kim, Obs]
    and the summary "Moonveil and Kim talked." (Task 10 writes public
    labels into summaries).

THE RULES and what follows BY HAND
    player_view(O, C) = {"display_name": shown_name(O, C)} plus
    "portrait_url" = persona.portrait_url exactly when masked_description(O,
    C) is not None (O a non-knower of C's active persona). shown_name(Obs,
    Cara) = "Moonveil"; shown_name(Kim, Cara) = "Moonveil (Cara)";
    shown_name(X, Y) = Y for every non-transformed Y.
[A] avatar Obs, ``play_scene``:
    present_detail Cara: display_name "Moonveil", portrait_url present and
    "" (no amulet image); name "Cara" (key) and avatar_url unchanged (URL).
    Kim: display_name "Kim", NO portrait_url.
    display_names = {"Cara": "Moonveil", "Kim": "Kim"} at least for the
    present; portrait_urls = {"Cara": ""} (only the masked one).
    Line 1: meta.speaker "Cara" (key), meta.speaker_shown "Moonveil".
    Line 2: meta.addressees ["Cara"], meta.addressees_shown ["Moonveil"],
    speaker_shown absent (Kim is not transformed → Task 6 sets nothing).
    Line 3 (storyteller, Task 6 rewrite for the perceiver): content
    "Moonveil sets a cup down."; meta.narrator True and meta.speaker_shown
    == meta.speaker (the localised label set by the rewrite loop).
    LEAK WALK: no string value anywhere in the payload contains "Cara",
    except under the technical keys name, character, inviter, invitee,
    partner, leader, members, participants, present, speaker, addressees
    and URL fields (avatar_url, portrait_url, *_url). Dict KEYS are not
    values (display_names, speaker_expr_versions, present_badges are keyed
    by the real name on purpose).
[B] avatar Obs, the amulet gets image "amulet.png": present_detail Cara
    portrait_url "/inventory/items/amulet/image"; portrait_urls["Cara"]
    the same.
[C] avatar Kim, ``play_scene``: Cara display_name "Moonveil (Cara)", NO
    portrait_url; display_names["Cara"] "Moonveil (Cara)"; portrait_urls
    has no "Cara".
[D] avatar Obs, ``play_others``: the Cara block display_name "Moonveil",
    portrait_url "/inventory/items/amulet/image", name "Cara"; Kim block
    display_name "Kim" without portrait_url; the leak walk as in [A].
[E] ``build_worldmap_payload`` (show_all — the temp location is unplaced,
    the fog question is not this smoke's): lens Obs → the Cara row
    display_name "Moonveil" + portrait_url, the Kim row "Kim" without;
    lens Kim → Cara "Moonveil (Cara)" without portrait_url; no lens →
    Cara "Cara" without portrait_url (no viewpoint, the admin's real view).
    The leak walk of [A] over the Obs payload finds nothing.
[F] avatar Obs, ``play_scenes``: the scene's participants ["Cara", "Kim"]
    (real keys, the avatar removed) and participants_shown ["Moonveil",
    "Kim"]; summary unchanged "Moonveil and Kim talked.".
[G] Providers unregistered (deletion test): avatar Obs, ``play_scene`` →
    Cara display_name "Cara", no portrait_url, portrait_urls {};
    ``play_others`` the same; worldmap lens Obs → Cara "Cara".
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(tempfile.mkdtemp(prefix="identity-play-payload-smoke-"))
STORAGE = ROOT / "world"
STORAGE.mkdir()
os.environ["STORAGE_DIR"] = str(STORAGE)
os.environ["INSTANCE_DIR"] = str(ROOT / "instance")
os.environ["ANIMATION_CLIPS_DIR"] = str(ROOT / "clips")
os.environ["ANIMATION_RIG_FILE"] = str(ROOT / "rig.fbx")

PERSONAS = [
    {"id": "p1", "item_id": "amulet", "alias": "Moonveil",
     "description": "A figure in moonlit silver.",
     "max_duration_minutes": 0, "cooldown_minutes": 0},
]
(STORAGE / "config.json").write_text(json.dumps({
    "packages": {"enabled": "transformation"},
}), encoding="utf-8")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
paths.init_instance(ROOT / "instance")
from app.core import config, db  # noqa: E402
config.load(STORAGE / "config.json")
db.init_schema()

# The personas live in the package's own table (Characters → Skills panel).
from plugins.transformation import store as tstore  # noqa: E402
tstore.ensure_schema()
for _p in PERSONAS:
    tstore.create_definition({k: v for k, v in _p.items() if k != "id"}, persona_id=_p["id"])

from app.core import embedding  # noqa: E402
embedding.embed = lambda text: None   # no model

from app.core.game_time import GameTime  # noqa: E402
from app.core.keyed_lock import keyed_lock  # noqa: E402
from app.core.timeutils import set_game_factor, set_game_time, utc_now_iso  # noqa: E402
from app.models import inventory  # noqa: E402
from app.models.character import get_character_profile, save_character_profile  # noqa: E402
from app.models.world import _load_world_data, _save_world_data, add_location  # noqa: E402

FAILURES = []
CHECKED = 0


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'OK ' if ok else 'FAIL'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


TECH_KEYS = {"name", "character", "inviter", "invitee", "partner", "leader",
             "members", "participants", "present", "speaker", "addressees"}


def leaks(node, needle, path="$", under_tech=False):
    """Paths of string values containing ``needle`` outside technical keys
    and URL fields. Dict keys are not inspected (they are keys)."""
    out = []
    if isinstance(node, dict):
        for k, v in node.items():
            tech = under_tech or k in TECH_KEYS or k.endswith("_url")
            out += leaks(v, needle, f"{path}.{k}", tech)
    elif isinstance(node, (list, tuple)):
        for i, v in enumerate(node):
            out += leaks(v, needle, f"{path}[{i}]", under_tech)
    elif isinstance(node, str) and needle in node and not under_tech:
        out.append(path)
    return out


def entry(rows, name):
    return next((r for r in rows if r.get("name") == name), None)


set_game_factor(0.0)
set_game_time(GameTime.parse("Y0002-D100T12:00:00"))

INN = add_location("Inn", "A stone house.")["id"]
ROOM = "taproom"
_data = _load_world_data()
for _loc in _data.get("locations", []):
    if _loc.get("id") == INN:
        _loc["rooms"] = [{"id": ROOM, "name": "Taproom", "description": "Benches."}]
        _loc["entry_room"] = ROOM
_save_world_data(_data)

for _name in ("Cara", "Kim", "Obs"):
    assert save_character_profile(_name, {"character_name": _name, "template": "human-roleplay"},
                                  create_new=True), _name
    with keyed_lock("character_profile", _name):
        _p = get_character_profile(_name)
        _p["current_location"] = INN
        _p["current_room"] = ROOM
        assert save_character_profile(_name, _p), _name

inventory.add_item("Amulet", item_id="amulet")
assert inventory.add_to_inventory("Cara", "amulet")

from app.plugins import loader, registry  # noqa: E402
loader.discover_packages()
check("package loaded", "transformation" in {p.id for p in registry.packages()}, True)

from app.core import hooks  # noqa: E402
from plugins.transformation import engine, knowers  # noqa: E402

engine.tick()
check("Kim made a knower", knowers.add("Kim", "Cara", "p1"), True)
check("transform ok", engine.transform("Cara", "p1", source="smoke"),
      {"ok": True, "reason": "", "alias": "Moonveil"})

from app.core import perception  # noqa: E402
from app.core.perception import STORYTELLER_SPEAKER  # noqa: E402
perception.record_utterance(speaker="Cara", content="Good evening.",
                            location_id=INN, room_id=ROOM)
perception.record_utterance(speaker="Kim", content="Welcome back.", addressees=["Cara"],
                            location_id=INN, room_id=ROOM)
perception.record_utterance(speaker=STORYTELLER_SPEAKER, content="Cara sets a cup down.",
                            location_id=INN, room_id=ROOM)

from app.models import scene_store  # noqa: E402
_now = utc_now_iso()
_sid = 0
for _who in ("Cara", "Kim", "Obs"):
    _sid = scene_store.touch_scene(INN, ROOM, _who, _now)
scene_store.mark_consolidated(_sid, "Moonveil and Kim talked.")

from app.models.account import set_active_character  # noqa: E402
from app.routes import play  # noqa: E402
from app.core.world_ops import build_worldmap_payload  # noqa: E402


def scene_lines(payload):
    return payload.get("scene") or []


def line_by(payload, pred):
    return next((ln for ln in scene_lines(payload) if pred(ln)), None)


# ── [A] avatar Obs, play_scene ─────────────────────────────────────────────
print("[A] Obs — /play/scene")
set_active_character("Obs")
p = play.play_scene(user=None)
check("A avatar", p.get("avatar"), "Obs")
cara = entry(p.get("present_detail") or [], "Cara") or {}
kim = entry(p.get("present_detail") or [], "Kim") or {}
check("A Cara display_name", cara.get("display_name"), "Moonveil")
check("A Cara portrait_url present", "portrait_url" in cara, True)
check("A Cara portrait_url empty (no item image)", cara.get("portrait_url"), "")
check("A Cara name stays the key", cara.get("name"), "Cara")
check("A Kim display_name", kim.get("display_name"), "Kim")
check("A Kim has no portrait_url", "portrait_url" in kim, False)
dn = p.get("display_names") or {}
check("A display_names Cara", dn.get("Cara"), "Moonveil")
check("A display_names Kim", dn.get("Kim"), "Kim")
check("A portrait_urls", p.get("portrait_urls"), {"Cara": ""})
l1 = line_by(p, lambda ln: (ln.get("meta") or {}).get("speaker") == "Cara") or {}
check("A line 1 speaker key", (l1.get("meta") or {}).get("speaker"), "Cara")
check("A line 1 speaker_shown", (l1.get("meta") or {}).get("speaker_shown"), "Moonveil")
l2 = line_by(p, lambda ln: (ln.get("meta") or {}).get("speaker") == "Kim") or {}
check("A line 2 addressees key", (l2.get("meta") or {}).get("addressees"), ["Cara"])
check("A line 2 addressees_shown", (l2.get("meta") or {}).get("addressees_shown"), ["Moonveil"])
check("A line 2 no speaker_shown", "speaker_shown" in (l2.get("meta") or {}), False)
l3 = line_by(p, lambda ln: (ln.get("meta") or {}).get("narrator") is True) or {}
check("A line 3 storyteller content", l3.get("content"), "Moonveil sets a cup down.")
check("A line 3 speaker_shown = localised label",
      bool((l3.get("meta") or {}).get("speaker_shown"))
      and (l3.get("meta") or {}).get("speaker_shown") == (l3.get("meta") or {}).get("speaker"),
      True)
check("A leak walk", leaks(p, "Cara"), [])

# ── [B] the amulet gets an image ───────────────────────────────────────────
print("[B] Obs — persona portrait from the item image")
inventory.update_item("amulet", {"image": "amulet.png"})
p = play.play_scene(user=None)
cara = entry(p.get("present_detail") or [], "Cara") or {}
check("B Cara portrait_url", cara.get("portrait_url"), "/inventory/items/amulet/image")
check("B portrait_urls", (p.get("portrait_urls") or {}).get("Cara"), "/inventory/items/amulet/image")

# ── [C] avatar Kim (knower) ────────────────────────────────────────────────
print("[C] Kim — /play/scene")
set_active_character("Kim")
p = play.play_scene(user=None)
cara = entry(p.get("present_detail") or [], "Cara") or {}
check("C Cara display_name", cara.get("display_name"), "Moonveil (Cara)")
check("C Cara has no portrait_url", "portrait_url" in cara, False)
check("C display_names Cara", (p.get("display_names") or {}).get("Cara"), "Moonveil (Cara)")
check("C portrait_urls without Cara", "Cara" in (p.get("portrait_urls") or {}), False)

# ── [D] avatar Obs, play_others ────────────────────────────────────────────
print("[D] Obs — /play/others")
set_active_character("Obs")
o = play.play_others(user=None)
cara = entry(o.get("characters") or [], "Cara") or {}
kim = entry(o.get("characters") or [], "Kim") or {}
check("D Cara display_name", cara.get("display_name"), "Moonveil")
check("D Cara portrait_url", cara.get("portrait_url"), "/inventory/items/amulet/image")
check("D Cara name stays the key", cara.get("name"), "Cara")
check("D Kim display_name", kim.get("display_name"), "Kim")
check("D Kim has no portrait_url", "portrait_url" in kim, False)
check("D leak walk", leaks(o, "Cara"), [])

# ── [E] worldmap ───────────────────────────────────────────────────────────
print("[E] worldmap")
w = build_worldmap_payload("Obs", show_all=True)
cara = entry(w.get("characters") or [], "Cara") or {}
kim = entry(w.get("characters") or [], "Kim") or {}
check("E Obs: Cara display_name", cara.get("display_name"), "Moonveil")
check("E Obs: Cara portrait_url", cara.get("portrait_url"), "/inventory/items/amulet/image")
check("E Obs: Kim display_name", kim.get("display_name"), "Kim")
check("E Obs: Kim has no portrait_url", "portrait_url" in kim, False)
check("E Obs: leak walk", leaks(w, "Cara"), [])
w = build_worldmap_payload("Kim", show_all=True)
cara = entry(w.get("characters") or [], "Cara") or {}
check("E Kim: Cara display_name", cara.get("display_name"), "Moonveil (Cara)")
check("E Kim: Cara has no portrait_url", "portrait_url" in cara, False)
w = build_worldmap_payload("", show_all=True)
cara = entry(w.get("characters") or [], "Cara") or {}
check("E no lens: Cara display_name", cara.get("display_name"), "Cara")
check("E no lens: Cara has no portrait_url", "portrait_url" in cara, False)

# ── [F] play_scenes ────────────────────────────────────────────────────────
print("[F] Obs — /play/scenes")
s = play.play_scenes(user=None)
sc = (s.get("scenes") or [{}])[0]
check("F participants (keys)", sc.get("participants"), ["Cara", "Kim"])
check("F participants_shown", sc.get("participants_shown"), ["Moonveil", "Kim"])
check("F summary", sc.get("summary"), "Moonveil and Kim talked.")

# ── [G] package absent ─────────────────────────────────────────────────────
print("[G] providers unregistered")
hooks.unregister_owned_providers("transformation")
p = play.play_scene(user=None)
cara = entry(p.get("present_detail") or [], "Cara") or {}
check("G scene: Cara display_name", cara.get("display_name"), "Cara")
check("G scene: Cara has no portrait_url", "portrait_url" in cara, False)
check("G scene: portrait_urls", p.get("portrait_urls"), {})
o = play.play_others(user=None)
cara = entry(o.get("characters") or [], "Cara") or {}
check("G others: Cara display_name", cara.get("display_name"), "Cara")
check("G others: Cara has no portrait_url", "portrait_url" in cara, False)
w = build_worldmap_payload("Obs", show_all=True)
cara = entry(w.get("characters") or [], "Cara") or {}
check("G worldmap: Cara display_name", cara.get("display_name"), "Cara")

print()
if FAILURES:
    print(f"FAIL — {len(FAILURES)} of {CHECKED} checks failed: {FAILURES}")
    sys.exit(1)
print(f"PASS — {CHECKED} checks")
