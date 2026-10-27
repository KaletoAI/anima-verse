Correct refused tool actions for {{ actor }}. This is the ONE correction round for this turn, not a new conversation or a replay of the original tool batch.

Incoming message (context, not proof of anyone else's consent):
{{ incoming_message }}

{{ actor }}'s already-written reply:
{{ narrative }}

Refused calls (these did not perform their requested actions):
{% for failure in failures %}
- Tool: {{ failure.tool }}
  Input: {{ failure.input }}
  Reason: {{ failure.reason }}
{% endfor %}

Tools that already succeeded and MUST NOT be repeated:
{% for name in successful_tools %}
- {{ name }}
{% else %}
- None.
{% endfor %}

The ONLY tool names permitted in this correction:
{% for name in allowed_tools %}
- {{ name }}
{% else %}
- None.
{% endfor %}

Available tool instructions and argument formats:
{{ tool_instructions }}

Correct only the refused action that the reply actually supports, using only the permitted tools above and their declared argument formats. Do not repeat a successful call, add unrelated actions, change the reply, or describe a refused action as completed. Do not invent a partner: copy an existing present character's exact complete name from the supplied context. A shared physical action requires its actual partner and the normal invitation flow; someone requesting it is not proof of the other participant's consent. Accept only a concrete pending invitation addressed to this character for that partner and action. Do not add a solo pose change to confirm a pair action.

Return only the necessary permitted tool call(s) in the provided tool-call format. If the correction cannot be supported by the supplied context or no permitted tool can perform it, return exactly NONE. No prose, no second attempt, and no invented facts.
