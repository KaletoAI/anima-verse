#!/usr/bin/env python3
"""Exact intimacy names must precede every observable side effect.

Hand-derived expectations: an absent actor, a partial partner or an invented
partner produces an error, zero consent rows, zero response wakeups and no
state/session writes. Whole-name case differences resolve to the stored name.
Temporary NPC and player partners still auto-accept; ordinary NPCs still need
a reciprocal offer. No external LLM or production storage is used.

Usage: ./.venv/bin/python scripts/smoke_intimacy_exact_names.py
Requires the installed private intimacy package (plugins/intimacy).
"""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if not (Path(__file__).resolve().parents[1] / "plugins/intimacy/skill.py").is_file():
    print("SKIP: optional private intimacy package is not installed")
    sys.exit(0)
TMP = tempfile.TemporaryDirectory(prefix="intimacy-exact-names-")
ROOT = Path(TMP.name)
os.environ["ANIMATION_CLIPS_DIR"] = str(ROOT / "clips")
os.environ["ANIMATION_RIG_FILE"] = str(ROOT / "rig.fbx")
from app.core import paths
paths.init(ROOT / "world")
paths.init_instance(ROOT / "instance")
from app.core import config, db
(ROOT / "world").mkdir(parents=True, exist_ok=True)
(ROOT / "world" / "config.json").write_text(json.dumps({"packages": {"enabled": "intimacy"}}))
config.load(ROOT / "world" / "config.json")
db.init_schema()
from app.models import character as C
from app.plugins.context import PluginContext
from plugins.intimacy import requests as R
from plugins.intimacy.skill import IntimateSkill
from plugins.intimacy import sessions as S

R.ensure_schema()
S.ensure_schema()
ACTOR, PARTNER, TEMP = "demo_actor", "demo_partner full", "demo_temporary"
for name, template in ((ACTOR, "default"), (PARTNER, "default"), (TEMP, "npc-temporary")):
    assert C.save_character_profile(name, {"character_name": name, "template": template}, create_new=True)


def rows():
    with db.transaction() as conn:
        return [tuple(row) for row in conn.execute(
            "SELECT requester, partner FROM intimate_requests ORDER BY requester, partner")]



with patch("app.core.agent_loop.get_agent_loop") as loop, \
     patch("app.models.character.set_is_intimate") as state, \
     patch("plugins.intimacy.sessions.open_or_join") as session, \
     patch("plugins.intimacy.sessions.leave") as leave, \
     patch("app.core.outfit_compliance.apply_outfit_compliance") as compliance:
    for active in (True, False):
        skill = IntimateSkill({}, PluginContext("intimacy"), active)
        for actor, partner in (("demo_unknown", PARTNER), (ACTOR, "demo_partner"),
                               (ACTOR, "demo_partner invented"), (ACTOR, "demo_unknown")):
            result = skill.execute(json.dumps({"agent_name": actor, "partner": partner}))
            assert result.startswith("Error"), result
            assert rows() == []
        for actor, partner in (("demo_unknown", TEMP), (ACTOR, "demo_partner")):
            try:
                R.request_or_accept(actor, partner)
            except ValueError:
                pass
            else:
                raise AssertionError("Direct consent entry accepted an absent name")
        assert rows() == []
    loop.assert_not_called()
    state.assert_not_called()
    session.assert_not_called()
    leave.assert_not_called()
    compliance.assert_not_called()

# Real temporary-NPC policy remains an immediate acceptance with no offer.
assert C.is_temporary_npc(TEMP)
assert R.request_or_accept(ACTOR.upper(), TEMP.upper()) is True
assert rows() == []
# Player-control detection is a boundary here; it must still bypass NPC offers.
with patch("app.models.account.is_player_controlled", return_value=True):
    assert R.request_or_accept(ACTOR, PARTNER) is True
assert rows() == []
with patch("app.core.agent_loop.get_agent_loop") as loop:
    assert R.request_or_accept(ACTOR.upper(), PARTNER.upper()) is False
    assert rows() == [(ACTOR, PARTNER)]
    assert loop.return_value.bump_respond.call_args.args == (PARTNER,)
    assert R.request_or_accept(PARTNER.upper(), ACTOR.upper()) is True
    assert rows() == []
    assert loop.return_value.bump_respond.call_count == 1

# The public verb persists canonical names in state and the shared session.
with patch("app.models.account.is_player_controlled", return_value=True), \
     patch("app.core.outfit_compliance.apply_outfit_compliance"):
    result = IntimateSkill({}, PluginContext("intimacy"), True).execute(json.dumps(
        {"agent_name": ACTOR.upper(), "partner": PARTNER.upper()}))
    assert not result.startswith("Error"), result
    assert C.get_state_flags(ACTOR).get("is_intimate")
    assert C.get_state_flags(PARTNER).get("is_intimate")
    with db.transaction() as conn:
        shares = conn.execute(
            "SELECT session_id, character_name FROM intimate_session_participants "
            "WHERE left_game_ts IS NULL ORDER BY character_name").fetchall()
    assert [row["character_name"] for row in shares] == sorted((ACTOR, PARTNER))
    assert len({row["session_id"] for row in shares}) == 1

print("PASS: exact intimacy names reject before effects; consent policy preserved")
TMP.cleanup()
