Character’s text:
{{ rp_response }}
{% if user_input %}
Other person’s words (context only):
{{ user_input }}
{% endif %}
{% if present %}
Present in your room: {{ present | join(", ") }}
{% else %}
Nobody else is here.
{% endif %}
{{ speech_note }}
Tools offered this turn:
{% for tool in tools %}
- {{ tool.name }}: {{ tool.brief }}
{% endfor %}
{{ menu_note }}{{ questions_note }}{{ guardrails }}
{% if marker_travel_allowed %}
When the text shows the character setting off for another place, write one line **I am at <place>** with the exact name of one known place (never a room, never an invented name):
{% for place in known_places %}
- {{ place }}
{% endfor %}
{% endif %}
{% if plans %}
Open plans (id | title):
{{ plans }}
{% endif %}
