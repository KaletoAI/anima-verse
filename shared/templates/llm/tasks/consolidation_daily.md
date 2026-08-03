---
task: consolidation
purpose: Daily summary — collapse one day's episodic memories into a 3-5 sentence narrative (memory_service._consolidate_episodics_to_daily)
placeholders:
  day_str: Date string "YYYY-MM-DD"
  character_name: Character whose day is being summarized
  existing: Existing daily summary text (empty if none)
  lang_instruction: Optional language instruction (empty for English)
  contents: Bullet list of that day's episodic memories
  thoughts_of_day: That day's private thoughts as a line list (empty if none)
---
## system
You are a summarization assistant. Summarize ONLY what the material below states — never add, guess or embellish a fact, a motive or a person that is not in it. Reply with ONLY the summary — no JSON, no explanation, no commentary.

## user
Summarize the day {{ day_str }} for {{ character_name }}.

{% if existing %}
Existing daily summary:
{{ existing }}
{% endif %}
Individual memories from this day:
{{ contents }}
{% if thoughts_of_day %}

Inner life of the day — what {{ character_name }} thought while it happened
(private; nobody else witnessed this):
{{ thoughts_of_day }}
{% endif %}

Write 3-5 compact sentences from {{ character_name }}'s perspective (third person).
Focus on: key moments, people involved, emotions, decisions.
Name every person by the name used in the material — never only by role or relationship ("her brother", "the colleague"), and never by a stand-in like "the narrator", "the conversation partner" or "the other one". Use ONLY names that literally appear above; never complete or resolve a name that is not written there.
Keep WHO did or said what exactly as the material has it, and do not turn an intention into an accomplished action.
{% if thoughts_of_day %}Let the inner life colour WHY things happened — but write about the day, not about the thinking.
{% endif %}Reply with ONLY the summary.{{ lang_instruction }}
