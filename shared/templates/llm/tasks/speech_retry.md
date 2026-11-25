---
task: speech_retry
purpose: B-lite speech net — map spoken lines a thought turn's tool decision dropped onto the character's speech verbs. Its OWN short prompt, not an appendix to the tool-decision prompt (plan-log-befunde-2026-09-11 § 3.8).
placeholders:
  character: Name of the speaking character
  quotes: List of the spoken lines (strings, verbatim from the RP prose)
  present: List of names of the other characters in the room right now
  tools: List of {name, description} — the DELIVERS_SPEECH verbs this character has, description straight from the skill
  example: One complete, real tool call in this model's tool format — the first line, said to the first person present, in the verb's own input shape ("" when no verb can phrase one; then the descriptions state the fields)
---
## system
You turn spoken lines of {{ character }} into speech tool calls. That is the whole task.

SPEECH VERBS AVAILABLE:
{% for t in tools %}
- {{ t.name }}: {{ t.description }}
{% endfor %}

FORMAT — one call per line that qualifies, in this model's tool format.
{% if example %}
Example, the first line said to {{ present[0] }}:
{{ example }}
For every other line write the same kind of call with that line's own words and the person it is spoken to.
{% endif %}

RULES:
- Take the spoken words VERBATIM, in the language they are written in. Do not rewrite, translate or summarise them.
- Address the person the line is spoken to. Only the people listed as present can hear a line in the room.
- Skip a line that is not {{ character }} speaking to someone present: a remembered line, an inner voice, something read aloud, a line another person said, a text that was written rather than spoken.
- If no line qualifies, answer with NONE and nothing else.
- Output ONLY tool calls. No prose, no explanation, no markers, no other verbs.

## user
{{ character }} spoke in this turn:
{% for q in quotes %}
- «{{ q }}»
{% endfor %}

In the room right now: {{ present | join(', ') }}

Output ONLY the tool calls that deliver these lines.
