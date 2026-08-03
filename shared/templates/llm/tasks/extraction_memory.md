---
task: extraction
purpose: Extract semantic facts and commitments from a chat exchange between two characters (used by memory_service.extract_memories_from_exchange)
placeholders:
  speaker_a: Name of the partner character (the one talking TO the memory owner)
  speaker_b: Name of the memory owner (the character whose memories we extract)
  text_a: What speaker_a said
  text_b: What speaker_b said
  existing_summary: Bullet list of recent existing memories ("(none yet)" if none)
  commitments_block: Pre-formatted block of open commitments (empty string when none)
  lang_instruction: Optional "\nWrite the memory contents in <Language>." or empty
---
## system
You are a strict information extractor. Extract ONLY what the exchange literally states — never infer, complete or embellish a fact, a motive or a relationship, and never change who said or did something. Reply ONLY with valid JSON — no commentary, no explanation, no markdown code fences.

## user
Analyze this conversation exchange between two characters and extract important memories for {{ speaker_b }}.

{{ speaker_a }}: "{{ text_a }}"
{{ speaker_b }}: "{{ text_b }}"

Extract as a JSON array. For each memory:
- memory_type: "semantic" (fact/info) or "commitment" (promise/plan)
- content: short, compact sentence (max 1-2 sentences) — written from {{ speaker_b }}'s perspective in third person. Every person in it is named, never only by role or relationship ("her brother", "the colleague") — this line is read months later without this conversation. Use ONLY names that literally appear in the exchange above; never complete or resolve a name that is not written there.
- related_character: the OTHER character involved in this memory — usually "{{ speaker_a }}". Use the exact name, never a generic label.
- importance: 1-5 (5=critical, 4=important, 3=medium, 2=minor, 1=trivial)
- tags: list of keywords
- delay_minutes: ONLY for commitments — how many minutes from now the promise is due, as a NUMBER (30 = in half an hour, 120 = in two hours, 480 = this evening, 1440 = tomorrow, 10080 = next week). Use 0 when no time was given. Never write words here.

Already stored memories (DO NOT repeat):
{{ existing_summary }}

{% if commitments_block %}
{{ commitments_block }}
{% endif %}

IMPORTANT:
- Extract ONLY what is literally said in the exchange above. Never infer, complete or embellish a fact, a motive or a relationship that is not stated there. When in doubt, leave it out.
- Extract ONLY facts (semantic) and promises (commitment)
- Keep WHO did or said what exactly as the source line has it. Never swap speaker and addressee, never move a statement to the other person, and never turn an intention into an accomplished action ("planned to warn her" is not "warned her"). Report an act with the neutral word the source uses — do not upgrade "reported" to "betrayed".
- NO episodic memories (experiences) — those are auto-consolidated from chat history
- Extract memories from BOTH speakers when relevant for {{ speaker_b }}'s memory
- Use the actual names "{{ speaker_a }}" and "{{ speaker_b }}" — NEVER write "User", "Player", "Spieler", "the user", "I" or generic labels. A stand-in like "the narrator", "my conversation partner", "the other one" or "der Erzähler" is a generic label too.{{ lang_instruction }}
- "commitment" requires EITHER (a) a concrete time hint OR (b) an external addressee ({{ speaker_a }} or another named character). Inner plans without a time hint and without an addressee are NOT commitments — at most semantic.
- For commitments to {{ speaker_a }}: set "related_character": "{{ speaker_a }}".
- For commitments to a third party named in the text: set "related_character" to that name.
- For commitments with a time hint: set "delay_minutes" to the number of minutes from now (in two hours = 120, tomorrow = 1440). A promise without a time gets 0.
- MAXIMUM 2 commitments per extraction. If more plans appear in the text, pick the most important ones.
- If an open promise was fulfilled by this exchange, put the number shown in its [ID:…] bracket into "completed_ids" — the plain number, nothing else.
- Ignore meta-tags, trivia, smalltalk
- If nothing new: empty arrays []

Reply ONLY with valid JSON:
{"memories": [
    {"memory_type": "...", "content": "...", "related_character": "...", "importance": N, "tags": ["..."], "delay_minutes": N},
    ...
],
"completed_ids": [<id from the [ID:…] bracket>, ...]
}
