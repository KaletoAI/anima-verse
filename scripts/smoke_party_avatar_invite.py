#!/usr/bin/env python3
"""The player's "Invite to party" (``POST /play/party/invite``).

Usage: ./.venv/bin/python scripts/smoke_party_avatar_invite.py

Background (2026-11-08): the player's avatar had no way to invite anyone into
a party (the HUD only answered invitations and left), and a temporary NPC
refused every standing invitation because ``request_consent`` asked it in a
THOUGHT turn, which temporary NPCs never get.

World, built in a temp dir (no live world, no LLM, the agent loop and task
queue are stubs): Home (one room, kitchen) holds the avatar "Demo Avatar"
(player-controlled, language en), the ordinary NPC "Demo Guide", the
temporary NPCs "Demo Host" and "Demo Visitor", and "Demo Leader" leading
"Demo Follower". "Demo Far" stands in Away. No world config -> decision
point off, no skill costs, no block rules.

Hand-derived expectations:
  (a) Package wiring: the invite verb stands behind the player action
      ``party_invite`` -> the scene's ``capability_actions["party_invite"]``
      is "invite_to_party"; the provider ``play.party_invite`` is registered.
  (b) Avatar -> Demo Guide (ordinary NPC): ``{"ok": True, "status":
      "pending", "invite_id": <pinv_…>}``; the row is pending, inviter the
      avatar; the guide is asked in a THOUGHT turn: exactly one
      ``bump("Demo Guide", hint=…)`` whose hint carries the invite id and the
      no-destination sentence of consent.md, no ``bump_respond``.
  (c) Avatar -> Demo Host (temporary NPC): pending as well, but asked in an
      ANSWER turn: exactly one ``bump_respond("Demo Host", speaker="Demo
      Avatar", on_demand=True, request_id=<that invite id>)``, no ``bump``.
  (d) The host's tool step can answer: JoinParty is offered without a
      per-character setting (``default_enabled_for`` True with the open
      standing invitation), the open-question line names the invite id, and
      its logged-shape answer ``JoinParty for: {"leader": "Demo Avatar",
      "answer": "yes", "invite_id": …}`` parses to ONE JoinParty call which,
      executed as the host, forms the party: avatar leader, members
      ["Demo Host"].
  (e) Refusals, each a 409 whose detail is the English sentence with the
      name filled in, and no new invitation row:
      Demo Host again -> "Demo Host is already in your party.";
      Demo Far -> "Demo Far is not here with you.";
      Demo Follower -> "Demo Follower is already in a party.";
      a blocked skill (patched ``blocked_reason`` = "Not now.") -> "Not now.";
      after Demo Leader invited the avatar -> "Demo Leader has already
      invited you — answer that invitation first.";
      the avatar as Demo Leader's follower -> "You are travelling in someone
      else's party and cannot invite anyone.".
  (f) An NPC's standing invitation to a temporary NPC is still refused
      (Demo Guide -> Demo Visitor: "A temporary NPC needs a destination-bound
      trip …"), and no agent turn is requested for it.
  (g) Without the provider the route answers 404 "Party invitations are not
      available." — never a 500.
"""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FAILURES = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'} {label}" + ("" if ok else f" — {detail}"))
    if not ok:
        FAILURES.append(label)


def main():
    with tempfile.TemporaryDirectory(prefix='party-avatar-invite-') as tmp:
        root = Path(tmp)
        os.environ['STORAGE_DIR'] = str(root / 'world')
        os.environ['INSTANCE_DIR'] = str(root / 'instance')
        os.environ['ANIMATION_CLIPS_DIR'] = str(root / 'clips')
        os.environ['ANIMATION_RIG_FILE'] = str(root / 'rig.fbx')
        from app.core import paths
        paths.init(root / 'world')
        paths.init_instance(root / 'instance')
        (root / 'instance' / 'config.json').write_text(json.dumps({
            'providers': [], 'embedding': {'backend': 'external'}}))
        from app.core import config, db
        config.load(root / 'world' / 'config.json')
        db.init_schema()
        cfg = config.get_all()
        cfg['packages'] = {'enabled': 'party'}
        cfg.setdefault('image_generation', {})['enabled'] = False
        config.save(cfg)
        from fastapi import HTTPException
        from app.core import hooks
        from app.core import party_engine as party
        from app.core.dependencies import get_skill_manager
        from app.core.tool_formats import find_tool_calls
        from app.core.users import create_user, update_user
        from app.models import character as chars, world
        from app.plugins.context import PluginContext
        from app.routes.play import _play_party_invite_sync, _player_skill_payload
        from plugins.party.skill import PartySkill, player_invite
        from plugins.party.trip_intents import open_questions
        get_skill_manager()
        home = world.add_location('Home', 'One room', rooms=[{'id': 'kitchen', 'name': 'Kitchen'}])['id']
        away = world.add_location('Away', 'Elsewhere', rooms=[{'id': 'hall', 'name': 'Hall'}])['id']
        avatar = 'Demo Avatar'
        cast = [(avatar, 'human-roleplay', home, 'kitchen'),
                ('Demo Guide', 'human-roleplay', home, 'kitchen'),
                ('Demo Host', 'npc-temporary', home, 'kitchen'),
                ('Demo Visitor', 'npc-temporary', home, 'kitchen'),
                ('Demo Leader', 'human-roleplay', home, 'kitchen'),
                ('Demo Follower', 'human-roleplay', home, 'kitchen'),
                ('Demo Far', 'human-roleplay', away, 'hall')]
        for name, template, loc, room in cast:
            assert chars.save_character_profile(name, {
                'character_name': name, 'template': template, 'language': 'en',
                'current_location': loc, 'current_room': room}, create_new=True)
            chars.set_known_locations(name, [home, away])
        chars.save_character_skill_config(avatar, 'invite_to_party', {'enabled': True})
        user = create_user('demo', 'smoke-password', allowed_characters=[avatar])
        assert update_user(user, settings={'active_character': avatar})
        assert party.add_to_party('Demo Leader', 'Demo Follower')

        loop = Mock()
        loop.bump.return_value = True
        loop.bump_respond.return_value = True
        queue = Mock()
        queue.is_paused.return_value = False

        def rows():
            return db.get_connection().execute(
                "SELECT COUNT(*) FROM party_invites").fetchone()[0]

        def refused(target, expected_detail):
            before = rows()
            try:
                _play_party_invite_sync({'target': target})
            except HTTPException as e:
                check(f"409 for {target}: {expected_detail!r}",
                      e.status_code == 409 and e.detail == expected_detail,
                      f"{e.status_code} {e.detail!r}")
            else:
                check(f"409 for {target}", False, "no refusal")
            check(f"no invitation row for {target}", rows() == before, f"{before} -> {rows()}")

        with patch('app.models.account.get_active_character', return_value=avatar), \
             patch('app.core.agent_loop.get_agent_loop', return_value=loop), \
             patch('app.core.task_queue.get_task_queue', return_value=queue):
            print("(a) package wiring")
            payload = _player_skill_payload(avatar)
            check("capability_actions.party_invite",
                  payload['capability_actions'].get('party_invite') == 'invite_to_party',
                  payload['capability_actions'])
            check("provider registered", hooks.get_provider('play.party_invite') is player_invite)

            print("(b) avatar -> ordinary NPC: thought turn")
            res = _play_party_invite_sync({'target': 'Demo Guide'})
            guide_id = res.get('invite_id', '')
            check("answer", res == {'ok': True, 'status': 'pending', 'invite_id': guide_id}
                  and guide_id.startswith('pinv_'), res)
            row = party.get_invite(guide_id) or {}
            check("pending row", row.get('status') == 'pending' and row.get('inviter') == avatar
                  and row.get('invitee') == 'Demo Guide', row)
            hint = (loop.bump.call_args.kwargs.get('hint', '') if loop.bump.call_args else '')
            check("one bump for the guide", loop.bump.call_count == 1
                  and loop.bump.call_args.args == ('Demo Guide',), loop.bump.call_args_list)
            check("consent names the invite and no destination",
                  guide_id in hint and 'There is no fixed destination' in hint, hint)
            check("no answer turn", loop.bump_respond.call_count == 0, loop.bump_respond.call_args_list)

            print("(c) avatar -> temporary NPC: answer turn")
            loop.reset_mock()
            res = _play_party_invite_sync({'target': 'Demo Host'})
            host_id = res.get('invite_id', '')
            check("answer", res.get('ok') is True and res.get('status') == 'pending'
                  and host_id.startswith('pinv_'), res)
            call = loop.bump_respond.call_args
            check("one bump_respond", loop.bump_respond.call_count == 1, loop.bump_respond.call_args_list)
            check("answer turn addressed and correlated", call is not None
                  and call.args == ('Demo Host',) and call.kwargs.get('speaker') == avatar
                  and call.kwargs.get('on_demand') is True
                  and call.kwargs.get('request_id') == host_id, call)
            check("no thought bump", loop.bump.call_count == 0, loop.bump.call_args_list)

            print("(d) the host answers yes in its tool step")
            join = PartySkill({}, PluginContext('party'), 'join')
            check("JoinParty offered by default", join.default_enabled_for('Demo Host') is True)
            lines = open_questions('Demo Host', ['JoinParty'])
            check("open question names the invite", len(lines) == 1 and host_id in lines[0], lines)
            answer = json.dumps({'leader': avatar, 'answer': 'yes', 'invite_id': host_id})
            calls = find_tool_calls('natural_en', 'JoinParty for: ' + answer
                                    + '\n\n[INTENT: Go along | Follow the guest | when=now | prio=3 | by=self]',
                                    {'JoinParty': None, 'TalkTo': None})
            check("one parsed call", calls == [('JoinParty', answer)], calls)
            out = join.execute(json.dumps({**json.loads(calls[0][1]), 'agent_name': 'Demo Host'}))
            p = party.get_party_of(avatar) or {}
            check("party formed", p.get('role') == 'leader' and p.get('members') == ['Demo Host'],
                  f"{out} / {p}")

            print("(e) refusals")
            refused('Demo Host', 'Demo Host is already in your party.')
            refused('Demo Far', 'Demo Far is not here with you.')
            refused('Demo Follower', 'Demo Follower is already in a party.')
            with patch('app.core.skill_gate.blocked_reason', return_value='Not now.'):
                refused('Demo Visitor', 'Not now.')
            party.leave_party(avatar)
            assert party.create_pending_invite('Demo Leader', avatar)
            party.leave_party('Demo Follower')
            refused('Demo Leader', 'Demo Leader has already invited you — answer that invitation first.')
            party.clear_invites_for(avatar)
            assert party.add_to_party('Demo Leader', avatar)
            refused('Demo Guide', "You are travelling in someone else's party and cannot invite anyone.")
            party.leave_party(avatar)

            print("(f) NPC -> temporary NPC standing invitation stays refused")
            loop.reset_mock()
            invite = PartySkill({}, PluginContext('party'), 'invite')
            out = invite.execute(json.dumps({'agent_name': 'Demo Guide', 'target': 'Demo Visitor'}))
            check("refused", out.startswith('A temporary NPC needs a destination-bound trip'), out)
            check("nobody asked", loop.bump.call_count == 0 and loop.bump_respond.call_count == 0)
            check("no row", party.find_pending_invite('Demo Guide', 'Demo Visitor') is None)

            print("(g) without the provider")
            hooks.unregister_owned_providers('party')
            try:
                _play_party_invite_sync({'target': 'Demo Guide'})
            except HTTPException as e:
                check("404 with reason", e.status_code == 404
                      and e.detail == 'Party invitations are not available.', f"{e.status_code} {e.detail!r}")
            else:
                check("404 with reason", False, "no refusal")
            hooks.register_provider('play.party_invite', player_invite, owner='party')

    print(f"\n{len(FAILURES)} failed" + (": " + ", ".join(FAILURES) if FAILURES else ""))
    sys.exit(1 if FAILURES else 0)


if __name__ == '__main__':
    main()
