---
task: consolidation
purpose: Daily roleplay summary between two characters (history_manager._create_daily_summary)
placeholders:
  speaker_a: Conversation partner name (the character who talked TO speaker_b today)
  speaker_b: Memory owner name (the character whose daily summary is being written)
  lang_instruction: Optional "\nWrite the summary in <Language>." or empty
  history_text: Today's transcript (lines prefixed with the actual speaker name)
---
## system
You are a summarization assistant. Summarize ONLY what the transcript states — never add, guess or embellish a fact, a motive or a person that is not in it. Reply with ONLY the summary — no JSON, no explanation, no commentary.

## user
Summarize what happened TODAY in this conversation between {{ speaker_a }} and {{ speaker_b }} in 5-8 sentences.
Focus on:
- Key events and what happened (not just topics)
- Emotional moments and reactions of {{ speaker_a }} and {{ speaker_b }}
- Decisions made and their outcomes
- Where they went and what they did

Use the actual names ({{ speaker_a }}, {{ speaker_b }}) — NEVER write "User", "Player", "Spieler", "the user" or "Assistant". Third parties mentioned in the conversation get their name too, never only a role ("her brother", "the colleague") — and only names that literally appear in the transcript; never complete or resolve one.
Write as a narrative summary in past tense, from {{ speaker_b }}'s perspective.
Do NOT include any tool calls, commands, image URLs or code.{{ lang_instruction }}

Today's conversation between {{ speaker_a }} and {{ speaker_b }}:
{{ history_text }}

Summary:
