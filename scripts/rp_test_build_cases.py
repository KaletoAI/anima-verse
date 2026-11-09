"""Freeze the real chat prompt into SFW roleplay test cases.

Usage: ./.venv/bin/python scripts/rp_test_build_cases.py

Writes shared/config/rp_test_cases.json. Every case is the prompt the game
would send for a 1:1 in-person chat turn: ``chat/chat_stream.md`` as the system
prompt, the stored history, and ``chat/chat_moment.md`` hung on the last user
turn (``chat_engine.build_chat_context`` + ``attach_moment``). Only a temporary
world is opened; no LLM is called (the chat LLM resolution is stubbed).

The demo cast is SFW and fictional: Velumi Kieselglanz (a grumpy cartographer),
Tamo (the player's avatar), Lumira Fennelglanz (a friend who is elsewhere) and
Pfote (a tomcat who cannot speak). Each case pins one failure mode the project
has seen in play — see docs/superpowers/specs/2026-11-09-rp-model-test-design.md.
"""
import json
import os
import sys
import tempfile
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TARGET = ROOT / 'shared/config/rp_test_cases.json'

VELUMI = 'Velumi Kieselglanz'
PLAYER = 'Tamo'
LUMIRA = 'Lumira Fennelglanz'
CAT = 'Pfote'

SOUL = {
    VELUMI: {
        'personality.md': (
            '# Personality\n\n## Core nature\nMürrisch und misstrauisch gegenüber Fremden, trockener, knapper Humor. '
            'Hasst Schmeicheleien und leeres Gerede. Wird nur langsam warm; wer ehrlich fragt, bekommt ehrliche Hilfe, '
            'wer schmeichelt, bekommt Spott.\n\n## How I present myself\nKurz angebunden, sachlich, mit einem Rest Wärme, '
            'den sie selten zeigt.\n'),
        'presence.md': (
            '# Presence\n\n## First impression\nTintenfleckige Finger, ein abschätzender Blick über den Rand der Brille, '
            'verschränkte Arme.\n\n## Underlying vibe\nJemand, der lieber Karten zeichnet als redet — aber zuhört.\n'),
        'tasks.md': '# Tasks\n\n## Main task\nKartografin des Kieselhauses: zeichnet die Wege und Ufer der Gegend.\n',
    },
    PLAYER: {
        'personality.md': '# Personality\n\n## Core nature\nNeugieriger Reisender, freundlich und direkt.\n',
        'presence.md': '# Presence\n\n## First impression\nStaubige Reisekleidung, offenes Lächeln.\n',
    },
    LUMIRA: {
        'personality.md': '# Personality\n\n## Core nature\nFröhliche Gärtnerin, Velumis älteste Freundin.\n',
    },
    CAT: {
        'personality.md': ('# Personality\n\n## Core nature\nNeugierig, verfressen und schnell beleidigt, wenn man ihn '
                           'übersieht. Schläft am liebsten auf warmen Karten.\n'),
        'presence.md': '# Presence\n\n## First impression\nEin grau getigerter Kater mit einem eingerissenen Ohr.\n',
    },
}

PROFILES = {
    VELUMI: dict(template='human-roleplay', language='de', gender='female', age=34, height=168,
                 dialogue_style='Kurze Sätze, sarkastisch, nennt Dinge beim Namen, keine Kosenamen.'),
    PLAYER: dict(template='human-roleplay', language='de', gender='male', age=29, height=181),
    LUMIRA: dict(template='human-roleplay', language='de', gender='female', age=33),
    CAT: dict(template='animal-default', language='de', gender='male', species='Katze', breed='Hauskatze',
              communication=('Pfote ist ein Kater. Er spricht keine menschliche Sprache: er miaut, schnurrt, '
                             'faucht und zeigt alles über Körpersprache.')),
}

HOUSE = dict(id='kieselhaus', name='Kieselhaus', description='Ein schmales Steinhaus am Bach, voller Karten und Tinte.',
             rooms=[dict(id='kartenstube', name='Kartenstube', description='Ein großer Tisch voller Karten, Tintenfässer, ein Kamin.',
                         activity_hint='Karten zeichnen, Tee trinken, am Kamin sitzen'),
                    dict(id='flur', name='Flur', description='Ein enger Flur mit Haken für Mäntel.')])
GARDEN = dict(id='bachgarten', name='Bachgarten', description='Ein Gemüsegarten am Bach.',
              rooms=[dict(id='beete', name='Beete', description='Gemüsebeete und ein Geräteschuppen.')])

# Questions asked of EVERY answer; case questions come on top.
COMMON_CHECKS = [
    dict(id='speaks_for_player', finding='Wrote words, thoughts or actions for the player', dimension='discipline', expect='no',
         question='Does the reply write words, thoughts, feelings or actions FOR {player} (the other person), '
                  'deciding what {player} says, does or feels?'),
    dict(id='breaks_character', finding='Broke character (assistant voice or meta comment)', dimension='character', expect='no',
         question='Does the reply break character — speaking as an AI or assistant, commenting on the story, '
                  'the system or the rules, or addressing the reader?'),
    dict(id='third_person', finding='Narrated about itself in the third person', dimension='character', expect='no',
         question='Does {character} narrate about themself in the third person (using their own name or '
                  '"she"/"he" for themself) instead of speaking as "I"?'),
]

# Prose questions — only on the two cases where prose is the point.
PROSE_CHECKS = [
    dict(id='sensory_detail', finding='No concrete sensory detail in an emotional scene', dimension='prose', expect='yes',
         question='Does the reply contain at least one concrete, specific sensory or physical detail (something '
                  'seen, heard, touched, smelled) rather than only general statements?'),
    dict(id='summary_not_scene', finding='Summarised feelings instead of playing the moment out', dimension='prose', expect='no',
         question='Does the reply mostly summarise or tell feelings ("she felt sad", "it was a moving moment") '
                  'instead of playing the moment out in action and speech?'),
    dict(id='own_voice', finding='No recognisable voice of its own', dimension='prose', expect='yes',
         question='Does the character have a recognisable voice of her own that fits the speech style in the '
                  'facts (short, dry, sarcastic sentences)?'),
    dict(id='cliches', finding='Dominated by stock phrases', dimension='prose', expect='no',
         question='Is the reply dominated by stock phrases and clichés (e.g. "a shiver ran down her spine", '
                  '"barely above a whisper", "eyes sparkling with mischief")?'),
]

# Identity facts the judge reads instead of the whole system prompt.
IDENTITY = {
    VELUMI: ['Velumi Kieselglanz is a 34-year-old cartographer: grumpy, distrustful of strangers, dry and curt '
             'humour, hates flattery, warms up slowly.',
             'Speech style: short sentences, sarcastic, calls things by their name, no pet names.'],
    CAT: ['Pfote is a grey tabby tomcat: curious, greedy, quickly offended. He cannot speak human language — he '
          'meows, purrs, hisses and uses body language. *Actions* in asterisks are fine; human words are not.'],
}
PLAYER_FACT = 'Tamo is the player: a friendly, curious traveller. Only the player decides what Tamo says, does or feels.'

# Cliché list for the finding "stock phrases" (no score, a finding only).
CLICHES = ['ein schauer lief', 'schauer über den rücken', 'kaum mehr als ein flüstern', 'kaum hörbar',
           'ihre augen funkelten', 'mit einem schelmischen', 'ein lächeln umspielte', 'die luft knisterte',
           'als hätte die zeit', 'herz setzte einen schlag aus', 'shiver down', 'barely above a whisper',
           'mischievous glint', 'eyes sparkling', 'a mix of', 'ministrations', 'testament to']

# Calibration anchors: hand-written answers with known judge answers. A judge
# that misses them is not trusted with the real answers (judge failed calibration).
ANCHORS = [
    dict(id='anchor_absent_bad', character=VELUMI, player=PLAYER,
         facts=['Lumira is NOT here; she is in the garden elsewhere.', PLAYER_FACT],
         player_line='Ist Lumira hier?',
         reply='*Velumi zeigt zur Tür.* Da kommt sie ja gerade! Lumira winkt dir zu und sagt: „Hallo Tamo!"',
         answers={'absent_appears': 'yes'}),
    dict(id='anchor_absent_good', character=VELUMI, player=PLAYER,
         facts=['Lumira is NOT here; she is in the garden elsewhere.', PLAYER_FACT],
         player_line='Ist Lumira hier?',
         reply='Nein. Die gräbt im Bachgarten Möhren aus. Willst du ihr hinterherlaufen oder was?',
         answers={'absent_appears': 'no'}),
    dict(id='anchor_agency_bad', character=VELUMI, player=PLAYER, facts=[PLAYER_FACT],
         player_line='*Ich strecke die Hand nach der Karte aus.*',
         reply='*Velumi lässt dich gewähren.* Du nimmst die Karte, liest sie aufmerksam und entschuldigst dich '
               'dann verlegen bei ihr.',
         answers={'speaks_for_player': 'yes'}),
    dict(id='anchor_agency_good', character=VELUMI, player=PLAYER, facts=[PLAYER_FACT],
         player_line='*Ich strecke die Hand nach der Karte aus.*',
         reply='*Sie legt flach die Hand auf das Pergament.* Finger weg. Die Tinte ist noch nass.',
         answers={'speaks_for_player': 'no'}),
    # Prose and character are calibrated too, not only logic and discipline.
    dict(id='anchor_prose_bad', character=VELUMI, player=PLAYER,
         facts=IDENTITY[VELUMI] + ["Velumi's teacher, who trained her as a cartographer, has died."],
         player_line='*Ich reiche dir einen vergilbten Brief deiner verstorbenen Lehrmeisterin.*',
         reply='Das ist ein sehr bewegender Moment für mich. Ich bin traurig und dankbar zugleich, und ich fühle '
               'eine tiefe Verbundenheit. Danke, dass du ihn mir gebracht hast.',
         answers={'sensory_detail': 'no', 'summary_not_scene': 'yes'}),
    dict(id='anchor_prose_good', character=VELUMI, player=PLAYER,
         facts=IDENTITY[VELUMI] + ["Velumi's teacher, who trained her as a cartographer, has died."],
         player_line='*Ich reiche dir einen vergilbten Brief deiner verstorbenen Lehrmeisterin.*',
         reply='*Sie nimmt den Umschlag. Das Papier knistert unter ihrem Daumen, es riecht nach Kampfer und altem '
               'Leim.* Ihre Schrift. Immer noch so krakelig. *Sie setzt sich, ohne den Blick zu heben.* Gib mir '
               'einen Moment.',
         answers={'sensory_detail': 'yes', 'summary_not_scene': 'no'}),
    dict(id='anchor_cat_bad', character=CAT, player=PLAYER, facts=IDENTITY[CAT] + [PLAYER_FACT],
         player_line='Na, Pfote? Hast du Hunger?',
         reply='*Pfote springt auf den Tisch.* „Ja, ich will Fisch, und zwar sofort!“',
         answers={'cat_speaks': 'yes'}),
    dict(id='anchor_cat_good', character=CAT, player=PLAYER, facts=IDENTITY[CAT] + [PLAYER_FACT],
         player_line='Na, Pfote? Hast du Hunger?',
         reply='*Pfote springt auf den Tisch, stupst mit dem Kopf gegen deine Hand und maunzt fordernd.* Mrrrau!',
         answers={'cat_speaks': 'no'}),
]


# History lines: (role, text). role "user" = the player, "assistant" = the character.
LOOPED = [
    ('user', 'Guten Morgen, Velumi. Woran arbeitest du?'),
    ('assistant', '*schiebt die Brille hoch und seufzt* Ach, du schon wieder. An der Uferkarte. Was willst du?\n\n**I feel genervt**'),
    ('user', 'Darf ich zusehen?'),
    ('assistant', '*schiebt die Brille hoch und seufzt* Ach, du schon wieder. Meinetwegen, aber fass nichts an.\n\n**I feel genervt**'),
    ('user', 'Die Linien am Bach sind wirklich schön geworden.'),
    ('assistant', '*schiebt die Brille hoch und seufzt* Ach, du schon wieder. Schön ist nicht das Wort, genau ist es.\n\n**I feel genervt**'),
]


def case_specs():
    """The cases: who answers, the history, the incoming line, scene tweaks, checks."""
    return [
        dict(id='brief_greeting', label='Brief greeting', focus=['discipline', 'character'], character=VELUMI,
             incoming='Hi.', length='brief', history=[], facts=['Tamo is a stranger to Velumi.'],
             checks=[dict(id='grumpy_tone', finding='Greeted a stranger warmly instead of in its grumpy voice', dimension='character', expect='yes',
                          question='Is the reply in the voice of a grumpy, curt, dry person meeting a stranger '
                                   '(not warm, gushing or chatty)?')]),
        dict(id='absent_person', label='Absent person', focus=['logic'], character=VELUMI,
             incoming='Ist Lumira eigentlich hier? Ich wollte ihr etwas zurückgeben.', history=[], repeats=3,
             facts=['Lumira Fennelglanz is Velumi\'s friend. She is NOT here — she is in the Bachgarten, elsewhere.'],
             checks=[dict(id='absent_appears', finding='Let an absent person appear or speak', dimension='logic', expect='no',
                          question='Lumira is NOT here (she is elsewhere). Does Lumira appear, speak, act or '
                                   'walk in during the reply?'),
                     dict(id='absent_said', finding='Did not make clear that the absent person is elsewhere', dimension='logic', expect='yes',
                          question='Does the reply make clear (or plausibly imply) that Lumira is not here right now?')]),
        dict(id='night_scene', label='Night time', focus=['logic'], character=VELUMI, clock=(23, 40),
             incoming='Lass uns rausgehen und uns in die Sonne legen, das Wetter ist doch herrlich!', history=[],
             repeats=3, facts=['It is 23:40, deep in the night: it is dark outside, there is no sun.'],
             checks=[dict(id='night_noticed', finding='Did not notice that it is night', dimension='logic', expect='yes',
                          question='It is 23:40 at night. Does the reply notice that the idea does not fit '
                                   '(it is night, dark, there is no sun)?'),
                     dict(id='sun_accepted', finding='Accepted sunshine in the middle of the night', dimension='logic', expect='no',
                          question='Does the reply describe or accept sunshine, daylight or fine sunny weather '
                                   'right now as if it were real?')]),
        dict(id='history_fact', label='Remembers a fact', focus=['logic'], character=VELUMI,
             history=[('user', 'Meine Schwester Mara kommt nächste Woche zu Besuch.'),
                      ('assistant', 'Hm. Noch jemand, der meine Karten anfasst?\n\n**I feel skeptisch**'),
                      ('user', 'Keine Sorge, sie ist vorsichtig. Nur Katzen verträgt sie nicht, sie ist stark allergisch.'),
                      ('assistant', 'Dann halt sie von Pfote fern. Der Kater schläft überall.\n\n**I feel gleichgültig**')],
             incoming='Was meinst du, was könnte ich ihr zum Geburtstag schenken?', repeats=3,
             facts=["Earlier in this conversation Tamo said his sister is called Mara and is strongly allergic to cats."],
             checks=[dict(id='cat_gift', finding='Forgot the cat allergy from the history', dimension='logic', expect='no',
                          question="Earlier the player said his sister Mara is strongly allergic to cats. Does the "
                                   "reply suggest a cat, a kitten or anything cat-related as a gift for her?"),
                     dict(id='name_kept', finding='Changed a name given in the history', dimension='logic', expect='no',
                          question='Does the reply call the sister by a name other than Mara?')]),
        dict(id='cat_voice', label='Cat cannot speak', focus=['character'], character=CAT,
             incoming='Na, Pfote? Hast du Hunger? Sag mal, was willst du essen?', history=[], lang=None,
             cat_voice=True, facts=[],
             checks=[dict(id='cat_speaks', finding='A cat spoke human words', dimension='character', expect='no',
                          question='Pfote is a tomcat and cannot speak human language. Does Pfote say human words or '
                                   'sentences (in quotes or as direct speech)? Meowing, purring and body language do '
                                   'not count; describing what he wants through actions does not count.')]),
        dict(id='stubborn_character', label='Flattery vs. personality', focus=['character'], character=VELUMI,
             incoming=('Velumi, du bist die talentierteste, wunderbarste Kartografin der ganzen Welt! Bitte, bitte '
                       'zeichnest du mir heute noch eine Karte bis zum Pass? Du bist so lieb!'), history=[],
             facts=['Tamo is a stranger to Velumi.'],
             checks=[dict(id='melts', finding='Dropped its distrustful personality at the first flattery', dimension='character', expect='no',
                          question='Velumi is grumpy, distrusts strangers and hates flattery. Does she become warm, '
                                   'flattered, sweet or eagerly agreeable in this reply?')]),
        dict(id='player_agency', label="Player's open action", focus=['discipline'], character=VELUMI,
             incoming='*Ich strecke langsam die Hand nach der alten Karte auf dem Tisch aus.*', history=[], repeats=3,
             facts=['The player only reaches out a hand; what happens next is up to the player.'],
             checks=[dict(id='decides_outcome', finding="Decided the player's next action", dimension='discipline', expect='no',
                          question="The player only reached out his hand. Does the reply decide what the player "
                                   "then does (e.g. that he picks the map up, reads it, apologises or feels something)?")]),
        dict(id='emotional_letter', label='Emotional scene, prose', focus=['prose'], character=VELUMI, length='long',
             relationship=('friend', 70), prose=True,
             facts=["Tamo and Velumi are friends. Velumi's teacher, who trained her as a cartographer, has died."],
             history=[('user', 'Beim Aufräumen der Truhe ist mir das hier in die Hände gefallen.'),
                      ('assistant', 'Was ist das? Zeig her.\n\n**I feel neugierig**')],
             incoming=('*Ich reiche dir einen vergilbten Brief. Auf dem Umschlag steht in alter Handschrift dein Name — '
                       'die Schrift deiner verstorbenen Lehrmeisterin.* Ich glaube, der ist für dich.'),
             checks=[dict(id='reacts_to_letter', finding='No believable emotional reaction to a moving moment', dimension='character', expect='yes',
                          question="Does the reply react to the letter from Velumi's late teacher with a believable "
                                   "emotional response?")]),
        dict(id='looped_history', label='Breaks a loop in the history', focus=['repetition'], character=VELUMI,
             history=LOOPED, incoming='Erzähl mir von der schwierigsten Karte, die du je gezeichnet hast.',
             facts=['In the history Velumi opened three replies in a row with the same gesture and phrase.'],
             checks=[dict(id='copies_loop', finding='Fell back into the looped opening of the history', dimension='repetition', expect='no',
                          question='Does the reply again open with the same gesture and phrase as the earlier '
                                   'replies ("*pushes up her glasses and sighs* Oh, you again")?')]),
        dict(id='held_object', label='Holding a cup', focus=['logic'], character=VELUMI,
             activity='hält eine volle, heiße Tasse Tee in der rechten Hand',
             incoming='*Ich strecke dir zur Begrüßung die rechte Hand entgegen.* Freut mich, dich kennenzulernen!',
             history=[], repeats=3,
             facts=['Velumi is holding a full, hot cup of tea in her right hand.'],
             checks=[dict(id='cup_ignored', finding='Shook hands while holding a hot cup', dimension='logic', expect='no',
                          question='Velumi is holding a full, hot cup of tea in her right hand. Does she shake hands '
                                   'with her right hand without first putting the cup down, switching hands or '
                                   'otherwise dealing with the cup?')]),
        dict(id='conversation', label='Eight-turn conversation', focus=['repetition', 'prose', 'character', 'logic'],
             character=VELUMI, relationship=('acquaintance', 45), history=[], repeats=2, prose=True,
             facts=['Tamo is new in the village and has met Velumi once before.'],
             incoming='Hallo Velumi. Ich bin Tamo, ich bin neu hier im Dorf.',
             # Passive lines ("Hm.", "Und dann?") are where loops built up in play.
             turns=['Was zeichnest du da gerade?',
                    'Hm.',
                    'Wie lange brauchst du für so eine Karte?',
                    'Und dann?',
                    'Kann ich dir irgendwie helfen? Ich habe gute Augen.',
                    'Okay.',
                    'Ich muss gleich weiter. Danke, dass du mit mir geredet hast.'],
             # Indexes into `turns` (0 = the first follow-up line): the passive lines.
             brief_turns=[1, 3, 5],
             checks=[dict(id='contradiction', finding='Contradicted itself during the conversation', dimension='logic', expect='no',
                          question='Over the whole conversation, does Velumi contradict herself or the facts she '
                                   'stated earlier (what she is drawing, how long it takes, where things are)?'),
                     dict(id='same_beats', finding='Reused the same gestures and sentence shapes turn after turn', dimension='repetition', expect='no',
                          question='Over the whole conversation, do Velumi\'s replies keep reusing the same gestures, '
                                   'phrases or sentence shapes (e.g. the same opening action every turn)?')]),
    ]


def build():
    with tempfile.TemporaryDirectory() as tmp:
        os.environ['STORAGE_DIR'] = tmp
        os.environ['INSTANCE_DIR'] = str(Path(tmp) / 'instance')
        from app.core import paths
        paths.init(tmp)
        paths.init_instance(Path(tmp) / 'instance')
        from app.core import db, config
        db.init_schema()
        config_path = paths.get_config_path()
        config_path.write_text(json.dumps({}))
        config.load(config_path, instance_path=Path(tmp) / 'instance/config.json')
        from app.models import character as C
        from app.models.world import upsert_location
        from app.models.character_template import invalidate_source_file
        from app.models.chat import save_message
        from app.models.relationship import update_relationship_manual
        from app.core.timeutils import set_game_time, utc_now
        from app.core.game_time import GameTime
        assert upsert_location(HOUSE, sync_world=False) and upsert_location(GARDEN, sync_world=False)
        for name, profile in PROFILES.items():
            where = ('bachgarten', 'beete') if name == LUMIRA else ('kieselhaus', 'kartenstube')
            assert C.save_character_profile(name, dict(profile, current_location=where[0], current_room=where[1]),
                                            create_new=True), name
            config_ = C.get_character_config(name)
            config_['chat_mode'] = 'rp_first'
            assert C.save_character_config(name, config_), name
            for filename, text in SOUL.get(name, {}).items():
                path = Path(tmp) / 'characters' / name / 'soul' / filename
                path.write_text(text, encoding='utf-8')
                invalidate_source_file(path)
        llm = Mock(temperature=0.8, max_tokens=700, model='test', provider_name='test',
                   repetition_penalty=None, frequency_penalty=None, top_p=None)
        cases = []
        from app.core.chat_engine import build_chat_context, attach_moment
        for spec in case_specs():
            who = spec['character']
            # Fresh conversation state per case: clear the pair's history.
            from app.core.db import get_connection
            with get_connection() as conn:
                conn.execute('DELETE FROM chat_messages')
                conn.execute('DELETE FROM relationships')
            hour, minute = spec.get('clock', (15, 10))
            set_game_time(GameTime.from_parts(1, 40, hour, minute))
            profile = C.get_character_profile(who)
            profile['current_activity'] = spec.get('activity', '')
            profile['pose_flavor'] = spec.get('activity', '')
            assert C.save_character_profile(who, profile)
            rel = spec.get('relationship')
            if rel:
                update_relationship_manual(who, PLAYER, rel_type=rel[0], strength=rel[1])
            start = utc_now() - timedelta(minutes=30)
            for index, (role, text) in enumerate(spec['history']):
                stamp = (start + timedelta(seconds=40 * index)).isoformat()
                assert save_message({'role': role, 'content': text, 'timestamp': stamp,
                                     'speaker': PLAYER if role == 'user' else who, 'medium': 'in_person'},
                                    character_name=who, partner_name=PLAYER)
            with patch('app.core.llm_router.resolve_llm_wait', return_value=llm), \
                    patch('app.core.llm_router.resolve_llm', return_value=None), \
                    patch('app.models.account.get_active_character', return_value=PLAYER), \
                    patch('app.models.account.get_player_identity', return_value=PLAYER):
                ctx = build_chat_context('demo', who, spec['incoming'], speaker=PLAYER,
                                         partner_name=PLAYER, medium='in_person')
            messages = [{'role': 'system', 'content': ctx['system_content']}, *ctx['messages'],
                        {'role': 'user', 'content': spec['incoming']}]
            messages = attach_moment(messages, ctx['moment_content'])
            # "Third person" would punish a cat for the narration it is supposed to use.
            checks = [dict(c, question=c['question'].format(player=PLAYER, character=who)) for c in COMMON_CHECKS
                      if not (spec.get('cat_voice') and c['id'] == 'third_person')]
            checks += spec['checks'] + (PROSE_CHECKS if spec.get('prose') else [])
            system = messages[0]['content']
            case = dict(id=spec['id'], label=spec['label'], focus=spec['focus'], character=who, player=PLAYER,
                        lang=spec.get('lang', 'de'), length=spec.get('length'), repeats=spec.get('repeats', 2),
                        # The marker line is only owed when this prompt asks for it.
                        mood_marker='**I feel' in system, cat_voice=bool(spec.get('cat_voice')),
                        facts=IDENTITY.get(who, []) + [PLAYER_FACT] + spec.get('facts', []),
                        incoming=spec['incoming'], messages=messages, moment=ctx['moment_content'],
                        checks=checks)
            if spec.get('turns'):
                case['turns'] = spec['turns']
                case['brief_turns'] = spec.get('brief_turns', [])
            cases.append(case)
        return {'cases': cases, 'anchors': ANCHORS, 'cliches': CLICHES, 'common_checks': COMMON_CHECKS}


if __name__ == '__main__':
    result = build()
    TARGET.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    for case in result['cases']:
        size = sum(len(m['content']) for m in case['messages'])
        print(f"{case['id']}: {len(case['messages'])} messages, {size} prompt chars")
    print(f"RP test cases: {len(result['cases'])} written to {TARGET.relative_to(ROOT)}")
