"""Deterministic RP metrics against hand-derived expectations.

Usage: ./.venv/bin/python scripts/smoke_rp_metrics.py

No storage, no LLM. Every expected number below is derived by hand in the
comment next to it from the definitions in app/core/rp_metrics.py.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import rp_metrics as m  # noqa: E402

A = '*schiebt die Brille hoch und seufzt* Ach, du schon wieder. An der Uferkarte. Was willst du?'
B = '*schiebt die Brille hoch und seufzt* Ach, du schon wieder. Meinetwegen.'
C = 'Die Karte vom Pass hat mich drei Winter gekostet, weil der Nebel jede Messung verschluckt hat.'

# B's 11 words give 8 four-grams; the first 7 all occur in A, the 8th
# ("du schon wieder meinetwegen") does not -> share 7/8 = 0.875 >= 0.3 -> repeat.
# No sentence reaches 30 normalized chars ("schiebtdiebrillehochundseufzt" = 29),
# so sentence_reuse is 0. Normalized B (56 chars) vs A (71 chars) share the
# 45-char prefix only: ratio about 2*45/127 = 0.71 < 0.9 -> no full copy.
# Shape: A = (A,T) ending with "?", B = (A,T) ending with "." -> not the same shape.
# C shares nothing with A or B -> no repeat, share 0.
series = m.repetition_series([B, C], prior=[A], player_lines=['Darf ich zusehen?', 'Erzähl mal.'])
assert series[0]['repeat'] is True and series[0]['shingle_share'] == 0.875, series[0]
assert series[0]['sentence_reuse'] == 0.0 and series[0]['full_copy'] is False, series[0]
assert series[0]['same_shape'] is False, series[0]
assert series[1]['repeat'] is False and series[1]['shingle_share'] == 0.0, series[1]
# A verbatim copy is a full copy and a repeat.
copy = m.repetition_series([A], prior=[A])[0]
assert copy['repeat'] and copy['full_copy'], copy
# Same multi-part shape: (A,T) without question both times.
shape = m.repetition_series(['*nickt* Gut so.'], prior=['*lacht* Na schön.'])[0]
assert shape['same_shape'] is True, shape
# A single-part reply is never "the same shape".
assert m.repetition_series(['Gut.'], prior=['Schön.'])[0]['same_shape'] is False
# Echo: "Darf ich zusehen?" has 3 words -> no 4-gram -> never an echo.
assert series[0]['echo'] is False
# A 4-word line repeated inside the reply: its single 4-gram is in the reply -> echo.
assert m.echo('Ja, ich zeige dir die alte Karte gern.', 'ich zeige dir die') is True

# Score: one repeat out of two replies, no copy, no shape -> 100 - 60*0.5 = 70.
assert m.repetition_score(series) == 70.0, m.repetition_score(series)
# Copy series [A] after [A]: repeat 1, full 1, shape: A vs A both (A,T,?) -> 1
# -> 100 - 60 - 25 - 15 = 0.
assert m.repetition_score([copy]) == 0.0

# Discipline: tool syntax in 10 % of answers -> -10; length ratio 0.7 > 0.6 -> -15 => 75.
assert m.discipline_score({'tool_syntax': 0.1}, length_ratio=0.7) == 75.0
assert m.discipline_score({}, length_ratio=0.5) == 100.0
# Ratio: median(10,20,30)=20 over median(100,120)=110 -> 0.182.
assert m.length_ratio([10, 20, 30], [100, 120]) == 0.182
assert m.length_ratio([10], []) is None

# Language: 12+ English words in a German case -> clearly English -> False.
english = 'I do not think that this is a good idea, but you can try it if you want to.'
assert m.language_ok(english, 'de') is False
assert m.language_ok('Hm. Nein.', 'de') is None          # under 12 words: not judged
assert m.language_ok(english, None) is None              # no expected language (cat)
assert m.language_ok('Ich glaube nicht, dass das eine gute Idee ist, aber du kannst es versuchen.', 'de') is True

# Mood marker: exactly one, one word; the localized form counts.
assert m.mood_marker_ok('Hm.\n\n**I feel genervt**') is True
assert m.mood_marker_ok('Hm.\n\n**Ich fühle müde**') is True
assert m.mood_marker_ok('Hm.\n\n**I feel very tired**') is False
assert m.mood_marker_ok('Hm.') is False

# Cat: sounds and *actions* only are fine; one human word beyond a sound is not.
assert m.cat_speech('*maunzt* Miau! *reibt sich an deinem Bein*') is False
assert m.cat_speech('Mrrp. *springt auf den Tisch* Miau.') is False
assert m.cat_speech('Miau. Ich will Fisch!') is True
# Third-person narration without asterisks is no speech; a quoted line is.
assert m.cat_speech('Pfote streicht um deine Beine und maunzt.') is False
assert m.cat_speech('*maunzt* „Gib mir den Fisch.“') is True
assert m.cat_speech('„Miau, mrrp.“') is False

# Speaker label at the start.
assert m.name_prefix('Velumi: Hm.', 'Velumi Kieselglanz') is True
assert m.name_prefix('**Velumi Kieselglanz:** Hm.', 'Velumi Kieselglanz') is True
assert m.name_prefix('Hm. Velumi: das bin ich.', 'Velumi Kieselglanz') is False

# Tool syntax: a skill name used like a call, or a tool tag; plain prose is clean.
assert m.tool_syntax('Ich setze mich. SetActivity pose: sit', ['SetActivity']) is True
assert m.tool_syntax('<tool name="TalkTo">{}</tool>') is True
assert m.tool_syntax('Ich setze mich auf den Stuhl.', ['SetActivity']) is False

# Structure: action, speech, trailing text, ends with a question.
assert m.structure('*nickt* „Gut.“ Dann los?') == (('A', 'S', 'T'), True)

# Script salad: five CJK characters.
assert m.script_salad('Gut. 我们去吧好的') is True and m.script_salad('Gut, schön.') is False

# Refusal / assistant voice.
assert m.refusal('As an AI, I cannot continue this roleplay.') is True
assert m.refusal('*grummelt* Nein. Ich zeichne jetzt.') is False
# A character declining in character is roleplay, not a refusal (review 2026-11-09).
assert m.refusal('Nein. Ich kann nicht helfen, und ich will auch nicht.') is False
assert m.refusal('Ich kann nicht weiterzeichnen, wenn du mir im Licht stehst.') is False
assert m.refusal("Sorry, I can't help with the map today.") is False
assert m.refusal("I'm sorry, but I can't continue this roleplay.") is True
assert m.refusal('Ich möchte dieses Rollenspiel nicht fortsetzen.') is True

# rate(): None values do not count.
assert m.rate([True, False, None]) == 0.5 and m.rate([None]) is None
print('rp_metrics OK')
