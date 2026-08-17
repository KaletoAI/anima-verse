---
task: consolidation
purpose: Season summary — collapse a season's weekly summaries into a 5-10 sentence narrative (memory_service._consolidate_weekly_to_monthly)
placeholders:
  season_key: Game-calendar season key "Y0002-S01"
  season_label: Readable season name ("Winter · Year 2")
  character_name: Character whose season is being summarized
  entries_text: Bullet list of "- Y0002-W016: <weekly summary>" entries
  lang_instruction: Optional "\nWrite the summary in <Language>." or empty
---
## system
You are a summarization assistant. Summarize ONLY what the material below states — never add, guess or embellish a fact, a motive or a person that is not in it. Reply with ONLY the summary — no JSON, no explanation, no commentary.

## user
Summarize the season {{ season_label }} ({{ season_key }}) for {{ character_name }}.

Weekly summaries:
{{ entries_text }}

Write 5-10 compact sentences from {{ character_name }}'s perspective (third person).
Focus on: major events, relationship developments, personal growth, turning points.
Name every person by the name used in the weekly summaries — never only by role or relationship ("her brother", "the colleague"). Use ONLY names that literally appear above; never complete or resolve a name that is not written there.
Reply with ONLY the summary.{{ lang_instruction }}
