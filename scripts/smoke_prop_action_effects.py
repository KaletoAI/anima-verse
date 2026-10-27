#!/usr/bin/env python3
"""Private real Core effects/consent regressions; no live world or model work.

Controller: ./.venv/bin/python scripts/smoke_prop_action_effects.py
Retained actual execution: --scenario-dir /tmp/prop-effects-unused-directory
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Barrier, Event, Thread
import unittest
from unittest.mock import patch

PARSER = argparse.ArgumentParser(add_help=False)
PARSER.add_argument('--scenario-dir', type=Path)
PARSER.add_argument('--effects-stage', choices=('begin', 'rollback', 'finish', 'restart'))
ARGS, REST = PARSER.parse_known_args()
sys.argv = [sys.argv[0], *REST]
if ARGS.scenario_dir:
    root = ARGS.scenario_dir.resolve()
    root.mkdir(parents=True, exist_ok=False)
    (root / '.prop-action-scenario').write_text('Task5 private effectful Core execution\n')
    environment = dict(os.environ, PROP_ACTION_SMOKE_RESUME_ROOT=str(root))
    for stage in ('begin', 'rollback', 'finish', 'restart'):
        subprocess.run([sys.executable, __file__, '--effects-stage', stage], env=environment, check=True)
    print(f'Actual effectful execution and receipts: {root / "effects.json"}')
    raise SystemExit(0)

import smoke_prop_action_runs as S
F, A, R = S.F, S.A, S.R
from app.core.game_time import GameDuration
from app.core import effect_application as E, prompt_filters, stat_boosts, db
from app.core import agent_loop, llm_router
from types import SimpleNamespace
from plugins.interact import register as registration
from app.plugins.context import PluginContext

# Only external models/workers are replaced. Runtime/storage/consumers remain
# real, including the installed invitation hook and executable skill reply.
agent_loop.get_agent_loop = lambda: SimpleNamespace(bump_respond=lambda *a, **k: None)


def forbidden_model(*args, **kwargs):
    F.EXTERNAL_CALLS.append("unexpected model call")
    raise AssertionError("deterministic effects fixture attempted a model call")


llm_router.llm_call = forbidden_model
normal = S.character_template.get_template("run-person")
normal["sections"].append(dict(id="effects-other-stat", fields=[
    dict(key="other_energy", type="bar", store="status_effects", label="Unrelated energy")]))
S.character_template.save_template("run-person", normal)
normal.setdefault("features", {})["temporary_npc"] = False
S.character_template.save_template("effects-normal", normal)


def stat(amount, when='success', target='actor', ident=None):
    return dict(id=ident or 'energy-' + when, type='stat_delta', target=target, when=when,
                stat='run_energy', amount=amount)


def author(name, target, pid, effects):
    doc = F.props.read_sidecar(pid)
    doc['actions'][0]['effects'] = effects
    F.props._write_sidecar(pid, doc)
    target['definition_revision'] = F.props.get_prop(pid)['revision']
    profile = F.C.get_character_profile(name)
    profile.update(template='run-person', status_effects={'run_energy': 40})
    assert F.C.save_character_profile(name, profile)


def begin(ability='combined', effects=None):
    name, target, pid = S.setup_run(ability)
    author(name, target, pid, effects if effects is not None else [stat(15)])
    S.measured_entry()
    result = S.request(name, target)
    assert result['status'] == 'approaching', result
    S.tick(30)
    S.tick(2)
    return name, target, pid, result['execution_id']


def value(name):
    return F.C.get_character_profile(name)['status_effects']['run_energy']


def receipts(ref):
    return [dict(row) for row in db.get_connection().execute(
        'SELECT * FROM prop_action_effect_receipts WHERE execution_id=?', (ref,))]


def condition():
    with db.transaction() as conn:
        conn.execute("INSERT OR REPLACE INTO prompt_filters (id,label,condition,prompt_modifier,enabled,meta) VALUES (?,?,?,?,?,?)",
                     ('effects-boost', 'Real ten-point boost', '', '', 1,
                      json.dumps({'stat_boosts': {'run_energy': 10}})))
    prompt_filters.invalidate_filter_snapshot()
    return dict(id='boost', type='condition_add', target='actor', when='success',
                condition_id='effects-boost', duration_game_s=60, repeat='refresh')


class Effects(unittest.TestCase):
    def tearDown(self):
        F.W.set_world_frozen(False)
        for run in R.live_runs():
            A.cancel(run['actor'], run['execution_id'])
        F.assert_no_external_work()

    def test_rate_settlement_is_partition_independent_signed_and_restart_safe(self):
        for amount, pieces in ((2, [3] * 30), (-2, [3] * 30), (2, [90]), (-2, [90])):
            name, _, _, ref = begin('pose', [stat(amount, 'active')])
            for index, seconds in enumerate(pieces):
                S.tick(seconds)
                if index == 14:
                    with patch.object(A, '_PROCESS', 'fraction-restart'):
                        A.advance(F.game_time())
                    A.advance(F.game_time())  # reanchor original process, no time
            A.cancel(name, ref)  # zero-new-time cancellation cannot lose a unit
            self.assertEqual(value(name), 43 if amount > 0 else 37)
            result = json.loads(receipts(ref)[0]['result'])['targets'][name]
            self.assertEqual(result['delta'], 3 if amount > 0 else -3)
            self.assertEqual(result['carry'], 0)

    def test_huge_finite_rate_saturates_and_cancellation_releases_claims(self):
        for amount, expected, delta in ((1e308, 100, 60), (-1e308, 0, -40)):
            name, _, _, ref = begin('pose', [stat(amount, 'active')])
            F.set_game_time(F.game_time() + GameDuration.of(seconds=2))
            result = A.cancel(name, ref)
            self.assertEqual(result['status'], 'completed')
            self.assertEqual(value(name), expected)
            self.assertFalse(R.claims(ref))
            applied = json.loads(receipts(ref)[0]['result'])['targets'][name]
            self.assertEqual(applied['delta'], delta)
            self.assertEqual(applied['carry'], 0)

    def test_malformed_item_condition_does_not_lose_consumed_numeric_and_mood(self):
        name, _, _, ref = begin('pose', [])
        condition()
        from app.models import inventory
        item = inventory.add_item(name='Malformed duration fixture', consumable=True, effects={
            'run_energy_change': 15, 'mood_influence': 'calm', 'apply_condition': 'effects-boost',
            'condition_duration_hours': 'not-a-duration'})
        self.assertTrue(inventory.add_to_inventory(name, item['id']))
        result = inventory.consume_item(name, item['id'])
        self.assertTrue(result['success'])
        self.assertFalse(inventory.has_item(name, item['id']))
        self.assertEqual(value(name), 55)
        self.assertEqual(F.C.get_character_profile(name)['current_feeling'], 'calm')
        self.assertFalse(F.C.get_character_profile(name).get('active_conditions'))

    def test_late_activity_model_reply_retains_its_original_exclusion_snapshot(self):
        from app.core import stat_effects as stats
        name, _, _, ref = begin('pose', [stat(2, 'active')])
        template = S.character_template.get_template('run-person')
        template.setdefault('features', {})['status_effects_enabled'] = True
        S.character_template.save_template('run-person', template)
        profile = F.C.get_character_profile(name)
        profile['status_effects']['other_energy'] = 40
        F.C.save_character_profile(name, profile)
        def model_reply(**kwargs):
            A.cancel(name, ref)
            return SimpleNamespace(content='{"stats":{"run_energy":10,"other_energy":7}}')
        with patch.object(llm_router, 'llm_call', model_reply):
            rates = stats.evaluate_stat_rates(name, 'same activity')
        F.C.adjust_status_effects(name, rates, source='activity')
        self.assertEqual(value(name), 40)
        self.assertEqual(F.C.get_character_profile(name)['status_effects']['other_energy'], 47)

    def test_same_activity_cache_re_evaluates_after_declared_ownership_ends(self):
        from app.core import stat_effects as stats
        name, _, _, ref = begin('pose', [stat(2, 'active')])
        template = S.character_template.get_template('run-person')
        template.setdefault('features', {})['status_effects_enabled'] = True
        S.character_template.save_template('run-person', template)
        class InlineWorker:
            def __init__(self, target, args, **kwargs):
                self.target, self.args = target, args
            def start(self):
                self.target(*self.args)
        with patch.object(stats.threading, 'Thread', InlineWorker), \
             patch('app.models.character.get_effective_activity', return_value='same activity'), \
             patch.object(llm_router, 'llm_call', return_value=SimpleNamespace(
                 content='{"stats":{"run_energy":6,"other_energy":2}}')):
            stats.maybe_activity_tick(name)
            F.set_game_time(F.game_time() + GameDuration.of(minutes=30))
            stats.maybe_activity_tick(name)
            A.cancel(name, ref)
            F.C.adjust_status_effects(name, {'run_energy': -60})
            baseline = value(name)
            stats.maybe_activity_tick(name)  # ownership boundary is not billable
            F.set_game_time(F.game_time() + GameDuration.of(minutes=30))
            stats.maybe_activity_tick(name)
            self.assertEqual(value(name), baseline + 3)

    def test_general_temporary_together_keeps_real_immediate_legacy_start(self):
        from app.core import interaction_engine as interactions
        name, partner, target, _ = S.authored_pair()
        entries = S.pose_catalog.world_entries('pose')
        entries['effects-free-pair'] = dict(solo=False, animation='run-pair', group='stand',
                                           places=2, prompt='Free pair fixture')
        S.pose_catalog.replace_world_entries('pose', entries)
        S.pose_catalog.reload_catalogs()
        self.assertTrue(F.C.is_temporary_npc(partner))
        ref = interactions.create_invite(name, partner, 'effects-free-pair')
        self.assertEqual(interactions.get_invite(ref)['status'], 'accepted')
        actor, invitee = (F.C.get_character_profile(n)['interaction'] for n in (name, partner))
        self.assertEqual(actor['id'], invitee['id'])
        self.assertEqual(actor['invite_id'], ref)
        self.assertIsNone(actor['anchor']['place_id'])
        interactions.end_interaction(name, interaction_id=actor['id'])

    def test_success_is_final_drink_and_replay_reports_actual_delta(self):
        name, _, _, ref = begin()
        self.assertEqual(value(name), 40)
        S.tick(5)
        self.assertEqual(R.get(ref)['phase'], 'drink')
        self.assertEqual(value(name), 40)
        S.tick(5)
        self.assertEqual(value(name), 55)
        self.assertEqual(R.get(ref)['status'], 'completed')
        E.apply_execution_effects(ref, 'success', F.game_time())
        A.cancel(name, ref)
        self.assertEqual(value(name), 55)
        self.assertEqual(len(receipts(ref)), 1)
        self.assertEqual(json.loads(receipts(ref)[0]['result'])['targets'][name]['delta'], 15)

    def test_start_only_after_measured_entry_and_no_cancel_success(self):
        name, target, pid = S.setup_run('combined')
        author(name, target, pid, [stat(4, 'start'), stat(15)])
        S.measured_entry()
        ref = S.request(name, target)['execution_id']
        self.assertEqual(value(name), 40)
        S.tick(30)
        self.assertEqual(value(name), 40)
        S.tick(2)
        self.assertEqual(value(name), 44)
        A.cancel(name, ref)
        self.assertEqual(value(name), 44)
        self.assertEqual(len(receipts(ref)), 1)

    def test_condition_boost_refresh_ignore_expiry_without_changing_base(self):
        boost = condition()
        name, _, _, ref = begin(effects=[stat(15), boost])
        S.tick(10)
        profile = F.C.get_character_profile(name)
        self.assertEqual(profile['status_effects']['run_energy'], 55)
        self.assertEqual(stat_boosts.effective_stat(profile, 'run_energy'), 65)
        now = F.game_time()
        refreshed = E.apply_effects_to_profile(profile, [boost], now + GameDuration.of(seconds=30))['profile']
        self.assertEqual(refreshed['active_conditions'][0]['started_at'], (now + GameDuration.of(seconds=30)).canonical())
        ignored = E.apply_effects_to_profile(refreshed, [{**boost, 'repeat': 'ignore'}], now + GameDuration.of(seconds=40))['profile']
        self.assertEqual(ignored['active_conditions'], refreshed['active_conditions'])
        F.set_game_time(now + GameDuration.of(seconds=61))
        self.assertEqual(stat_boosts.effective_stat(F.C.get_character_profile(name), 'run_energy'), 55)
        from app.core.activity_engine import cleanup_expired_conditions
        self.assertEqual(cleanup_expired_conditions(name), 1)
        self.assertEqual(value(name), 55)

    def test_rate_fraction_is_durable_and_cancel_accrues_last_interval(self):
        name, _, _, ref = begin('pose', [stat(2, 'active')])
        S.tick(10)
        self.assertEqual(value(name), 40)
        self.assertTrue(receipts(ref))
        with patch.object(A, '_PROCESS', 'effects-restarted'):
            S.tick(3600)
            self.assertEqual(value(name), 40)
            S.tick(65)
            self.assertEqual(value(name), 42)
            F.set_game_time(F.game_time() + GameDuration.of(seconds=15))
            A.cancel(name, ref)
        self.assertEqual(value(name), 43)
        self.assertEqual(R.get(ref)['data']['active_game_s'], 90)

    def test_capped_overflow_is_not_later_credit_and_receipt_is_actual(self):
        name, _, _, ref = begin('pose', [stat(2, 'active')])
        profile = F.C.get_character_profile(name)
        profile['status_effects']['run_energy'] = 99
        F.C.save_character_profile(name, profile)
        S.tick(90)
        self.assertEqual(value(name), 100)
        result = json.loads(receipts(ref)[0]['result'])
        self.assertEqual(result['targets'][name]['delta'], 1)
        F.C.adjust_status_effects(name, {'run_energy': -10})
        S.tick(15)
        self.assertEqual(value(name), 90)
        S.tick(15)
        self.assertEqual(value(name), 91)

    def test_sql_failure_rolls_back_effect_receipt_and_phase_together(self):
        name, _, _, ref = begin()
        S.tick(5)
        with db.transaction() as conn:
            conn.execute("CREATE TRIGGER effects_rollback BEFORE INSERT ON prop_action_effect_receipts BEGIN SELECT RAISE(ABORT,'effects stop'); END")
        with self.assertRaises(Exception):
            S.tick(5)
        self.assertEqual(value(name), 40)
        self.assertEqual(R.get(ref)['phase'], 'drink')
        self.assertEqual(R.get(ref)['status'], 'active')
        self.assertFalse(receipts(ref))
        with db.transaction() as conn:
            conn.execute('DROP TRIGGER effects_rollback')
        A.advance(F.game_time())
        self.assertEqual(value(name), 55)
        self.assertEqual(R.get(ref)['status'], 'completed')

    def test_unknown_and_missing_actor_stats_refuse_before_claims(self):
        name, target, pid = S.setup_run('combined')
        author(name, target, pid, [stat(15)])
        profile = F.C.get_character_profile(name)
        profile['status_effects'] = {}
        F.C.save_character_profile(name, profile)
        self.assertEqual(S.request(name, target)['reason'], 'missing_character_stat')
        self.assertFalse(R.claims())
        transformed = E.apply_effects_to_profile({'status_effects': {'run_energy': 40}},
                                                [{**stat(15), 'stat': 'invented'}], F.game_time())
        self.assertEqual(transformed['profile']['status_effects'], {'run_energy': 40})

    def test_sleep_success_once_in_both_real_flag_recovery_windows(self):
        for after in (False, True):
            name, target, pid = S.setup_run('sleep')
            doc = F.props.read_sidecar(pid)
            doc['actions'][0]['pose_key'] = 'sleeping'
            doc['model_variants'][0]['markers'][0]['group'] = 'lie'
            F.props._write_sidecar(pid, doc)
            author(name, target, pid, [stat(15)])
            S.measured_entry('sleeping')
            ref = S.request(name, target)['execution_id']
            S.tick(30)
            real = F.C.set_is_sleeping
            def stopped(*args, **kwargs):
                if after:
                    real(*args, **kwargs)
                raise KeyboardInterrupt('process died at canonical flag boundary')
            with patch.object(F.C, 'set_is_sleeping', stopped):
                with self.assertRaises(KeyboardInterrupt):
                    S.tick(2)
            self.assertEqual(value(name), 40)
            with patch.object(A, '_PROCESS', 'sleep-effects-restart'):
                A.advance(F.game_time())
                A.advance(F.game_time())
            self.assertTrue(F.C.is_character_sleeping(name))
            self.assertEqual(R.get(ref)['status'], 'sleeping')
            self.assertEqual(value(name), 55)
            self.assertEqual(len(receipts(ref)), 1)
            A.cancel(name, ref)
            self.assertFalse(F.C.is_character_sleeping(name))

    def test_item_repeat_ignore_and_shared_mood_numeric_consumer(self):
        boost = condition()
        name, _, _, _ = begin('pose', [])
        from app.models import inventory
        item = inventory.add_item(name='Private effects drink', category='consumable', consumable=True,
            effects={'run_energy_change': 15, 'mood_influence': 'calm',
                     'apply_condition': boost['condition_id'], 'condition_duration_hours': 2})
        item_id = item['id'] if isinstance(item, dict) else item
        inventory.apply_item_effects(name, item_id)
        self.assertEqual(value(name), 55)
        profile = F.C.get_character_profile(name)
        self.assertEqual(profile['current_feeling'], 'calm')
        self.assertEqual(stat_boosts.effective_stat(profile, 'run_energy'), 65)
        started = profile['active_conditions'][0]['started_at']
        F.set_game_time(F.game_time() + GameDuration.of(seconds=30))
        inventory.apply_item_effects(name, item_id)
        self.assertEqual(F.C.get_character_profile(name)['active_conditions'][0]['started_at'], started)

    def test_real_reply_path_is_exact_and_temporary_never_autoyes(self):
        from plugins.interact import register as registration
        from plugins.interact.skill import InteractSkill
        from app.core import agent_loop
        from types import SimpleNamespace
        name, partner, target, pid = S.authored_pair()
        author(name, target, pid, [stat(7, 'start', 'actor'), stat(3, 'start', 'partner', 'partner-energy')])
        profile = F.C.get_character_profile(partner)
        profile.update(template='run-person', status_effects={'run_energy': 40})
        F.C.save_character_profile(partner, profile)
        with patch.object(registration.decision, 'is_active', return_value=False), \
             patch.object(agent_loop, 'get_agent_loop', return_value=SimpleNamespace(bump_respond=lambda *a, **k: None)):
            ref = S.request(name, target, partner=partner)['execution_id']
        self.assertEqual(R.get(ref)['status'], 'awaiting_consent')
        self.assertFalse(R.claims())
        skill = InteractSkill({}, PluginContext("interact"))
        reply = skill.execute(json.dumps({'agent_name': partner, 'execution_id': ref,
                                         'partner': name, 'answer': 'yes'}))
        self.assertEqual(R.get(ref)['status'], 'approaching', reply)
        S.tick(30)
        S.tick(2)
        self.assertEqual(value(name), 47)
        self.assertEqual(value(partner), 43)
        A.cancel(partner, ref)
        self.assertFalse(F.C.get_character_profile(name).get('interaction'))
        self.assertFalse(F.C.get_character_profile(partner).get('interaction'))

    def test_effect_targets_stay_semantic_when_clip_roles_are_reversed(self):
        name, partner, target, pid = S.authored_pair()
        author(name, target, pid, [stat(7, 'start'), stat(3, 'start', 'partner', 'partner-energy')])
        for actor, gender in ((name, 'female'), (partner, 'male')):
            profile = F.C.get_character_profile(actor)
            profile.update(gender=gender, template='run-person', status_effects={'run_energy': 40}, height=170)
            F.C.save_character_profile(actor, profile)
        path = F.ROOT / 'clips/run-pair.json'
        metadata = json.loads(path.read_text())
        metadata['role_gender'] = dict(a='male', b='female')
        path.write_text(json.dumps(metadata))
        S.clips._clear_entries_cache()
        ref = S.request(name, target, partner=partner)['execution_id']
        self.assertEqual(R.get(ref)['data']['clip_roles'], dict(a=partner, b=name))
        A.respond(partner, ref, True)
        S.tick(30)
        S.tick(2)
        self.assertEqual(F.C.get_character_profile(name)['interaction']['role'], 'b')
        self.assertEqual(value(name), 47)
        self.assertEqual(value(partner), 43)

    def test_two_real_objects_same_pose_share_no_consent(self):
        name, partner, target, pid = S.authored_pair()
        location = F.W.get_location_by_id(target['location_id'])
        room = next(room for room in location['rooms'] if room['id'] == target['room_id'])
        room['layout']['props'].append(dict(id='other-device', prop_id=pid, at=[4, 5], yaw=0))
        F.W.upsert_location(location, sync_world=True)
        F.places.invalidate()
        first = S.request(name, target, partner=partner)['execution_id']
        other = dict(target, placement_id='other-device')
        second = S.request(name, other, partner=partner)['execution_id']
        self.assertTrue(first and second and first != second)
        self.assertEqual(A.respond(partner, second, True)['status'], 'approaching')
        self.assertEqual(R.get(first)['status'], 'awaiting_consent')
        self.assertFalse(R.claims(first))
        self.assertTrue(R.claims(second))
        self.assertEqual(A.respond(partner, first, True)['reason'], 'participant_claimed')
        self.assertTrue(R.claims(second))
        S.tick(30)
        S.tick(2)
        self.assertEqual(R.get(second)['status'], 'active')
        self.assertEqual(F.C.get_character_profile(name)['place']['id'], 'other-device/body')
        self.assertEqual(F.C.get_character_profile(partner)['place']['execution_id'], second)

    def test_explicit_decision_runs_outside_locks_and_uses_real_response(self):
        from app.core.decision import Answer, Decision
        from app.core.keyed_lock import keyed_lock
        for answer in ('accept', 'decline'):
            name, partner, target, _ = S.authored_pair()
            def external_decision(*args, **kwargs):
                ref = kwargs['key']
                self.assertFalse(A._lock(ref)._is_owned())
                self.assertFalse(keyed_lock('character_profile', name)._is_owned())
                self.assertFalse(keyed_lock('character_profile', partner)._is_owned())
                self.assertFalse(keyed_lock('places', target['location_id'])._is_owned())
                # Real SQLite write authority must be available to another
                # connection: no model/backend call can span a write txn.
                with R.transaction():
                    pass
                return Decision({'answer': Answer(value=answer, p_yes=None, confidence=1,
                                                  distribution={answer: 1.0})})
            with patch.object(registration.decision, 'is_active', return_value=True), \
                 patch.object(registration.decision, 'decide', external_decision):
                result = S.request(name, target, partner=partner)
            self.assertEqual(result['status'], 'approaching' if answer == 'accept' else 'cancelled')
            self.assertEqual(bool(R.claims(result['execution_id'])), answer == 'accept')

    def test_concurrent_effect_replays_never_duplicate_start_or_rate(self):
        name, _, _, ref = begin('pose', [stat(5, 'start'), stat(2, 'active', ident='rate')])
        self.assertEqual(value(name), 45)
        S.tick(90)
        with ThreadPoolExecutor(max_workers=4) as workers:
            list(workers.map(lambda _: E.apply_execution_effects(ref, 'active', F.game_time()), range(8)))
            list(workers.map(lambda _: E.apply_execution_effects(ref, 'start', F.game_time()), range(8)))
        self.assertEqual(value(name), 48)
        self.assertEqual(len(receipts(ref)), 2)

    def test_same_pose_other_object_is_not_consent_and_revision_change_invalidates(self):
        name, partner, target, pid = S.authored_pair()
        ref = S.request(name, target, partner=partner)['execution_id']
        doc = F.props.read_sidecar(pid)
        doc['actions'][0]['description'] = 'A different revision of the same pose'
        F.props._write_sidecar(pid, doc)
        self.assertEqual(A.respond(partner, ref, True)['reason'], 'stale_definition')
        self.assertFalse(R.claims())
        self.assertFalse(F.C.get_character_profile(name).get('interaction'))
        target['definition_revision'] = F.props.get_prop(pid)['revision']
        other = dict(target, placement_id='not-the-accepted-object')
        self.assertEqual(S.request(name, other, partner=partner)['reason'], 'placement_not_found')
        self.assertFalse(R.claims())

    def test_normal_and_temporary_explicit_no_and_unanswered_question(self):
        from plugins.interact.skill import InteractSkill
        for template in ('run-person', 'effects-normal'):
            name, partner, target, pid = S.authored_pair()
            profile = F.C.get_character_profile(partner)
            profile['template'] = template
            F.C.save_character_profile(partner, profile)
            ref = S.request(name, target, partner=partner)['execution_id']
            self.assertEqual(R.get(ref)['status'], 'awaiting_consent')
            self.assertFalse(R.claims())
            skill = InteractSkill({}, PluginContext('interact'))
            skill.execute(json.dumps(dict(agent_name=partner, execution_id=ref)))
            self.assertEqual(R.get(ref)['status'], 'awaiting_consent')
            skill.execute(json.dumps(dict(agent_name=name, execution_id=ref, answer='yes')))
            self.assertEqual(R.get(ref)['status'], 'awaiting_consent')
            skill.execute(json.dumps(dict(agent_name=partner, execution_id=ref, answer='no')))
            self.assertEqual(R.get(ref)['reason'], 'consent_declined')
            self.assertFalse(R.claims())

    def test_declared_rates_suppress_only_their_stats_at_actual_activity_write(self):
        name, _, _, ref = begin('pose', [stat(2, 'active')])
        profile = F.C.get_character_profile(name)
        profile['status_effects']['other_energy'] = 40
        F.C.save_character_profile(name, profile)
        from app.core import stat_effects
        # Represents a real result returned after an already-inflight model
        # request. The actual consumer must recheck ownership at write time.
        F.C.adjust_status_effects(name, {'run_energy': 10, 'other_energy': 7}, source='activity')
        self.assertEqual(value(name), 40)
        self.assertEqual(F.C.get_character_profile(name)['status_effects']['other_energy'], 47)
        S.tick(90)
        self.assertEqual(value(name), 43)
        A.cancel(name, ref)
        F.C.adjust_status_effects(name, {'run_energy': 10}, source='activity')
        self.assertEqual(value(name), 53)

    def test_effect_writer_waits_profile_before_database_and_old_callbacks_preserve_replacement(self):
        from app.core.keyed_lock import keyed_lock
        name, target, _, ref = begin('pose', [stat(2, 'active')])
        F.set_game_time(F.game_time() + GameDuration.of(seconds=90))
        waiting, done = Event(), Event()
        errors = []
        real_lock = A.keyed_lock
        @contextmanager
        def observed_lock(namespace, key):
            if namespace == 'character_profile' and key == name:
                waiting.set()
            with real_lock(namespace, key):
                yield
        def cancel():
            try:
                A.cancel(name, ref)
            except BaseException as exc:
                errors.append(exc)
            finally:
                done.set()
        with keyed_lock('character_profile', name):
            with patch.object(A, 'keyed_lock', observed_lock):
                worker = Thread(target=cancel)
                worker.start()
                self.assertTrue(waiting.wait(5))
                profile = F.C.get_character_profile(name)
                profile['concurrent_note'] = 'profile-before-DB writer survived'
                self.assertTrue(F.C.save_character_profile(name, profile))
        self.assertTrue(done.wait(5), errors)
        worker.join(5)
        self.assertFalse(errors)
        self.assertEqual(value(name), 43)
        self.assertEqual(F.C.get_character_profile(name)['concurrent_note'], 'profile-before-DB writer survived')
        replacement = S.request(name, target)['execution_id']
        journey = F.E.get_journey(name)
        A.cancel(name, ref)
        A._cancelled(name, {'execution_ref': ref, 'journey_id': 'old', 'execution_kind': 'prop_action'}, 'cancelled')
        self.assertEqual(F.E.get_journey(name), journey)
        self.assertEqual(R.get(replacement)['status'], 'approaching')
        self.assertTrue(R.claims(replacement))
        self.assertEqual(value(name), 43)

    def test_freeze_and_oversize_final_tick_have_no_unearned_rate_bonus(self):
        name, _, _, ref = begin('combined', [stat(6, 'active'), stat(15)])
        F.W.set_world_frozen(True)
        S.tick(7200)
        self.assertEqual(value(name), 40)
        F.W.set_world_frozen(False)
        S.tick(7200)
        # Exactly ten active phase seconds: 6/minute -> 1, plus success 15.
        self.assertEqual(value(name), 56)
        self.assertEqual(R.get(ref)['data']['active_game_s'], 10)


    def test_real_condition_repeat_refresh_ignore_and_removal(self):
        boost = condition()
        name, target, pid, ref = begin(effects=[stat(15), boost])
        S.tick(10)
        first_stamp = F.C.get_character_profile(name)['active_conditions'][0]['started_at']
        second = S.request(name, target)['execution_id']
        S.tick(30)
        S.tick(2)
        S.tick(10)
        refreshed = F.C.get_character_profile(name)['active_conditions'][0]['started_at']
        self.assertNotEqual(refreshed, first_stamp)
        self.assertEqual(value(name), 70)
        doc = F.props.read_sidecar(pid)
        doc['actions'][0]['effects'] = [{**boost, 'repeat': 'ignore'}]
        F.props._write_sidecar(pid, doc)
        target['definition_revision'] = F.props.get_prop(pid)['revision']
        third = S.request(name, target)['execution_id']
        S.tick(30)
        S.tick(2)
        S.tick(10)
        self.assertEqual(R.get(third)['status'], 'completed')
        self.assertEqual(F.C.get_character_profile(name)['active_conditions'][0]['started_at'], refreshed)
        removed = E.apply_character_effects(name, [dict(id='remove', type='condition_remove',
            condition_id='effects-boost')], F.game_time(), source='effects-smoke')
        self.assertTrue(removed['results']['remove']['applied'])
        self.assertFalse(F.C.get_character_profile(name)['active_conditions'])
        self.assertEqual(value(name), 70)
        self.assertEqual(stat_boosts.effective_stat(F.C.get_character_profile(name), 'run_energy'), 70)

    def test_effect_notifications_observe_only_committed_real_values(self):
        from app.core import sync_topics
        name, _, _, ref = begin()
        observed = []
        real = sync_topics.changed_at
        def observe(actor, *args, **kwargs):
            if actor == name and kwargs.get('topics') == ('presence', 'self'):
                observed.append((value(name), R.get(ref)['status'], len(receipts(ref))))
            return real(actor, *args, **kwargs)
        with patch.object(sync_topics, 'changed_at', observe):
            S.tick(10)
        self.assertIn((55, 'completed', 1), observed)


    def test_competing_claims_award_only_the_real_entry_winner(self):
        name, target, pid = S.setup_run()
        author(name, target, pid, [stat(15, 'start')])
        other = F.actor(target['location_id'], at=(2, 5))
        profile = F.C.get_character_profile(other)
        profile.update(template='run-person', status_effects={'run_energy': 40}, height=170)
        F.C.save_character_profile(other, profile)
        S.measured_entry()
        barrier = Barrier(2)
        def compete(actor):
            barrier.wait()
            return S.request(actor, target)
        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(compete, (name, other)))
        self.assertEqual(sum(result['status'] == 'approaching' for result in results), 1)
        winner = next(actor for actor, result in zip((name, other), results) if result['status'] == 'approaching')
        loser = other if winner == name else name
        S.tick(30)
        S.tick(2)
        self.assertEqual(value(winner), 55)
        self.assertEqual(value(loser), 40)
        self.assertEqual(len(receipts(next(result['execution_id'] for result in results if result['execution_id']))), 1)

    def test_start_receipt_failure_rolls_back_real_entry_pose_position_and_value(self):
        name, target, pid = S.setup_run()
        author(name, target, pid, [stat(15, 'start')])
        S.measured_entry()
        ref = S.request(name, target)['execution_id']
        S.tick(30)
        access = F.C.get_character_pos(name)
        with db.transaction() as conn:
            conn.execute("CREATE TRIGGER entry_stop BEFORE INSERT ON prop_action_effect_receipts BEGIN SELECT RAISE(ABORT,'entry rollback'); END")
        try:
            with self.assertRaises(Exception):
                S.tick(2)
            self.assertEqual(R.get(ref)['status'], 'approaching')
            self.assertEqual(R.get(ref)['phase'], 'entry')
            self.assertEqual(F.C.get_character_pos(name), access)
            self.assertFalse(F.C.get_character_profile(name).get('place'))
            self.assertEqual(value(name), 40)
            self.assertFalse(receipts(ref))
        finally:
            with db.transaction() as conn:
                conn.execute('DROP TRIGGER entry_stop')
        A.advance(F.game_time())
        self.assertEqual(R.get(ref)['status'], 'active')
        self.assertEqual(value(name), 55)


def execution_scenario(stage):
    path = F.ROOT / 'effects.json'
    if stage == 'begin':
        name, target, pid, ref = begin(effects=[stat(15), condition()])
        S.tick(5)
        path.write_text(json.dumps(dict(actor=name, execution_id=ref, target=target,
                                       before=value(name), run=R.get(ref)), indent=2))
        F.assert_no_external_work()
        os._exit(0)
    data = json.loads(path.read_text())
    name, ref = data['actor'], data['execution_id']
    A.advance(F.game_time())  # actual process restart reanchors before active time
    if stage == 'rollback':
        with db.transaction() as conn:
            conn.execute("CREATE TRIGGER scenario_stop BEFORE INSERT ON prop_action_effect_receipts BEGIN SELECT RAISE(ABORT,'real rollback'); END")
        try:
            S.tick(5)
        except Exception:
            pass
        else:
            raise AssertionError('receipt write did not fail')
        assert value(name) == 40 and R.get(ref)['status'] == 'active' and not receipts(ref)
        with db.transaction() as conn:
            conn.execute('DROP TRIGGER scenario_stop')
        data['rollback_profile'] = F.C.get_character_profile(name)
        path.write_text(json.dumps(data, indent=2))
        F.assert_no_external_work()
        os._exit(0)
    if stage == 'finish':
        def stop_after_real_commit(run):
            assert value(name) == 55 and R.get(ref)['status'] == 'completed'
            assert stat_boosts.effective_stat(F.C.get_character_profile(name), 'run_energy') == 65
            data.update(after=value(name), profile=F.C.get_character_profile(name),
                        receipts=receipts(ref), run=R.get(ref))
            assert data['run']['data']['cleanup_pending']
            path.write_text(json.dumps(data, indent=2))
            F.assert_no_external_work()
            os._exit(0)
        A._cleanup = stop_after_real_commit
        S.tick(5)
        raise AssertionError('real effect commit boundary was not reached')
    else:
        E.apply_execution_effects(ref, 'success', F.game_time())
        A.cancel(name, ref)
        assert value(name) == 55 and len(receipts(ref)) == 2
        data.update(restarted_value=value(name), restarted_run=R.get(ref))
    path.write_text(json.dumps(data, indent=2))
    F.assert_no_external_work()


if __name__ == '__main__':
    if ARGS.effects_stage:
        execution_scenario(ARGS.effects_stage)
    else:
        unittest.main(argv=[sys.argv[0], *REST])
