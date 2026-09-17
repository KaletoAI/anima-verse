{# Per-turn scene state of the chat prompt — the companion of chat/chat_stream.md.
   Rendered by routes/chat.py:_build_chat_prompt and hung on the LAST user turn,
   after the conversation history (chat(): user_turn_suffix; run_chat_turn:
   appended to the triggering line). The system prompt explains the
   [SCENE STATE] marker to the model.

   Everything that can change between two turns lives here, so the system
   prompt and the history in front of it stay byte-identical for the backend's
   prompt cache. Inside the block the order follows the model, not the cache:
   the situation first, what this turn asks of the character last.

   BLOCKS (all optional, pre-formatted strings unless noted):
     situation_block — "Your current situation:" (time, weather, place, activity)
     self_state_lines: list[str] — the character's prompt_volatile template fields
     condition_reminder
     moment_notes: list[str] — one-off context of this turn (state modifiers,
       a spell taking effect, being woken up, a caller's hint)
     self_wearing, partner_wearing
     partner_state_lines: list[str] — character mode: the partner's mood, doing
       and volatile fields
     present_characters: str, present_details: str — room mode
     inventory_carrying_section, inventory_room_section
     focused_items — items the person you talk to drew attention to
     known_activities — the room's place offer (free places with poses, busy
       ones by name, the free-text hint as the tail)
     events_section, assignment_section, recent_activity_section
     memory_section, relationships_section
     reply_shape_section — "This moment" facts

   FLAGS / NAMES:
     character_name, partner_mode, partner_name
     addressed_to_me: bool, addressed_names: str — room mode, who the triggering
       line was meant for
     winding_down, respond_opportunity — the SKIP rules, always last
#}
[SCENE STATE — how things stand right now. Nobody said this.]
{% if situation_block %}

{{ situation_block }}
{% endif %}
{% if self_state_lines %}

Your current state:
{% for line in self_state_lines %}{{ line }}
{% endfor %}
{% endif %}
{% if condition_reminder %}

{{ condition_reminder }}
{% endif %}
{% for note in moment_notes %}

{{ note }}
{% endfor %}
{% if self_wearing %}

{{ self_wearing }}
{% endif %}
{% if partner_mode == "character" and partner_state_lines %}

{{ partner_name }} right now:
{% for line in partner_state_lines %}{{ line }}
{% endfor %}
{% endif %}
{% if partner_wearing %}

{{ partner_wearing }}
{% endif %}
{% if partner_mode == "room" %}

Others present: {{ present_characters }}.
{% if present_details %}
What you can see of them:
{{ present_details }}
{% endif %}
{% endif %}
{% if inventory_carrying_section %}

{{ inventory_carrying_section }}
{% endif %}
{% if inventory_room_section %}

{{ inventory_room_section }}
{% endif %}
{% if focused_items %}

FOCUSED ITEMS IN THE ROOM (the person you're talking to has drawn attention to these — you can naturally reference, point to, or interact with them):
{{ focused_items }}
{% endif %}
{% if known_activities %}

{{ known_activities }}
{% endif %}
{% if events_section %}

{{ events_section }}
{% endif %}
{% if assignment_section %}

{{ assignment_section }}
{% endif %}
{% if recent_activity_section %}

{{ recent_activity_section }}
{% endif %}
{% if memory_section %}

{{ memory_section }}
{% endif %}
{% if relationships_section %}

{{ relationships_section }}
{% endif %}
{% if partner_mode == "room" and partner_name %}

{% if addressed_to_me %}{{ partner_name }} spoke to YOU directly — that is what brought you into this turn. Answer {{ partner_name }}. Others may have spoken since: the transcript is what the room actually heard and its last lines are the freshest thing said, whoever said them. React to those as well if they concern you.
{% elif addressed_names %}{{ partner_name }} was speaking to {{ addressed_names }}, not to you. You overheard it. If you speak, speak as a bystander who joins in — do not answer as if the words were meant for you.
{% else %}{{ partner_name }} said that to the room, to nobody in particular — anyone present may pick it up, and this time it is you. Answer {{ partner_name }} as one of the people there.
{% endif %}
{% endif %}
{% if reply_shape_section %}

This moment:
{{ reply_shape_section }}
{% endif %}
{% if winding_down %}

=== The conversation is winding down ===
The exchange here is naturally coming to an end — the energy is fading. Give ONE short, in-character closing beat: a brief goodbye, an "I should get going", a final remark or small gesture that signals you are disengaging. One or two sentences. Do NOT open a new topic or ask a question that invites more back-and-forth.

If nothing fits, reply with exactly: SKIP
{% elif respond_opportunity %}

=== Overheard — you MAY chime in (no obligation) ===
You are present and overheard what was just said. It was NOT addressed to you. Join in ONLY if you genuinely have something to say that fits this moment and your character — a brief reaction, a question, a remark. There is no expectation that you speak.

If you have nothing natural to add right now, reply with exactly: SKIP
(Just the word SKIP — do not explain, do not narrate staying silent.)
{% endif %}

[END OF SCENE STATE]
