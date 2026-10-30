---
task: extraction
purpose: Extract semantic facts and commitments from a character's own thought turn — the monologue counterpart of extraction_memory (used by memory_service.extract_memories_from_exchange without a partner)
placeholders:
  speaker_b: Name of the memory owner (the character whose thought this is)
  text_b: The thought itself
  presence_known: Whether actual room presence is known
  present_names: Comma-joined names actually present (empty means nobody)
  absent_names: Comma-joined mentioned names absent from this place
  existing_summary: Bullet list of recent existing memories ("(none yet)" if none)
  open_plans_block: Pre-formatted block of open plans (empty string when none)
  lang_instruction: Optional "\nWrite the memory contents in <Language>." or empty
---
## system
You are a strict information extractor. Extract ONLY what the text literally states — never infer, complete or embellish a fact, a motive or a relationship, and never change who said or did something. Reply ONLY with valid JSON — no commentary, no explanation, no markdown code fences.

## user
This is what {{ speaker_b }} thought to themselves. Nobody else was part of it. Extract the memories worth keeping.

{{ speaker_b }}: "{{ text_b }}"

{% if presence_known %}
Who was really in the room with {{ speaker_b }}: {{ present_names if present_names else "nobody" }}.
{% if absent_names %}
NOT there: {{ absent_names }}. Whatever the thought tells about being with them, talking to or touching them
is imagined — it did not happen.
{% endif %}
{% endif %}

Extract as a JSON array. For each memory:
- memory_type: "semantic" (fact/info) or "commitment" (promise/plan)
- title: ONLY for commitments — a short plan label, 2–6 words, in the language of the content, without the owner's name (e.g. "bake bread", "return the borrowed book").
- content: short, compact sentence (max 1-2 sentences) — written about {{ speaker_b }} in third person. Every person in it is named, never only by role or relationship ("her brother", "the colleague") — this line is read months later without this thought. Use ONLY names that literally appear in the text above; never complete or resolve a name that is not written there.
- related_character: the other person this memory is ABOUT, if the text names one. Leave it out entirely when the thought is only about {{ speaker_b }} — never invent an addressee.
- importance: 1-5 (5=critical, 4=important, 3=medium, 2=minor, 1=trivial)
- tags: list of keywords
- when: ONLY for commitments — first decide WHEN the plan happens, judged by the thought itself: "now" ({{ speaker_b }} is doing, starting or about to do it in this thought — going there, telling, knocking, taking the order), "ongoing" (a state or attitude: staying with, watching over, keeping company, being there for someone), "done" (the thought shows it finished), "wish" (only wanted, hoped, considered or wondered about, or an effect on someone to achieve — impress, win over, make jealous, get closer — with no concrete act), "waiting" ({{ speaker_b }} waits for someone else's reply, reaction or action), or "later" (a concrete act {{ speaker_b }} will do at a later moment, not started in this thought, whose completion can be seen: something given, told, brought, written, visited or made — "give her the letter", not "impress him"). If the thought or the content sentence you would write describes what {{ speaker_b }} IS doing — present tense, an act under way, heading somewhere, following, watching or searching — it is "now", never "later". "later" needs an intended moment or a clear trigger (a time, "when he comes by", "after ...", "tomorrow"), or a single act that has not begun; getting to know someone, becoming better at something or living a feeling is "wish". Only "later" is a commitment; for the others leave the item out.
- delay_minutes: ONLY for commitments — how many minutes from now the plan is due, as a NUMBER (30 = in half an hour, 120 = in two hours, 480 = this evening, 1440 = tomorrow, 10080 = next week). Use 0 when no time was given. Never write words here.

Already stored memories (DO NOT repeat):
{{ existing_summary }}

{% if open_plans_block %}
{{ open_plans_block }}
{% endif %}

IMPORTANT:
- Something done WITH a person who was not there did not happen: no semantic memory of it, and a plan that needed that person is NOT fulfilled — never put its id into completed_ids.
- Extract ONLY what is literally in the thought above. Never infer, complete or embellish a fact, a motive or a relationship that is not stated there. When in doubt, leave it out.
- Extract ONLY facts (semantic) and plans (commitment)
- Semantic memories only for what the thought shows as DONE or LEARNED and still matters later: an action with a lasting result (something made, cleaned, posted, sent, given or taken, a place visited) or a fact found out about the world or a person. Never for gestures, poses or passing body movements (stretching, breathing, looking around), and never for intentions, plans, wishes, preparations, rehearsals, moods, worries, wondering or imagined events ("plans to", "wants to", "will", "is preparing", "is nervous about", "wonders whether"). This restricts semantic memories only; commitment rules below still apply.
- Keep WHO did or said what exactly as the text has it, and never turn an intention into an accomplished action ("planned to warn her" is not "warned her").
- NO episodic memories (experiences) — those are auto-consolidated from chat history
- NEVER write "User", "Player", "Spieler", "the user", "I" or generic labels. A stand-in like "the narrator", "my conversation partner" or "the other one" is a generic label too.{{ lang_instruction }}
- A commitment is something {{ speaker_b }} means to do LATER and has not started in this thought: a concrete act with an observable completion ("give her the letter").
  NOT a commitment: doing or starting something now; a lasting state or attitude (staying with, watching over, keeping company, being there for someone); something shown as done (if it finishes an open plan, put its id into completed_ids); something only considered or wished ("wonders whether", "would like to", "maybe"); waiting for someone's answer or reaction; a goal of effect on a person (impress, win over, test) without a concrete act.
  A named person alone does not make a plan a commitment; a plan without a person is fine when clearly for later ("tomorrow", "next week", "after the shift", "first ..., then ...").
- MAXIMUM 2 commitments per extraction. If more plans appear, pick the most important ones.
- If an open plan was fulfilled, put its id into "completed_ids" exactly as shown (8 hex characters), never a number.
- Ignore mood descriptions, scenery and smalltalk with oneself
- If nothing new: empty arrays []

Reply ONLY with valid JSON:
{"memories": [
    {"memory_type": "...", "title": "... (commitments only)", "content": "...", "related_character": "...", "importance": N, "tags": ["..."], "when": "later", "delay_minutes": N},
    ...
],
"completed_ids": ["a1b2c3d4", ...]
}
