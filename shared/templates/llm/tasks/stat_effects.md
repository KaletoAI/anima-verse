{# Stat-effect evaluation outside chat beats (plan-activity-stat-effects.md):
   - per_hour=false: a SIGNIFICANT event (e.g. intimacy just ended) — big
     swings allowed, semantics come from each value's template hint.
   - per_hour=true: an ONGOING activity — deltas PER HOUR; the caller
     scales them to the actually elapsed time.

   Variables: target_name, stat_list, per_hour (bool), situation_text
#}

## system

You judge how a situation affects {{ target_name }}'s status values. Reply ONLY with valid JSON, no commentary.

The available values are:
{{ stat_list }}

{% if per_hour %}
This is an ONGOING activity. Return integer deltas PER HOUR of doing this activity. Judge intensity from the description: light activity around ±3..8 per hour, demanding physical activity around -10..-25 per hour on energy-like values, resting raises them. Let each value's own description above guide direction and size.
{% else %}
This is a SIGNIFICANT event / turning point. Large swings are allowed and often correct (up to about -90..+90) when a value's description implies it — e.g. an arousal-like value dropping sharply right after a climax, or an energy-like value collapsing at total exhaustion. Aspects that are only mildly touched still get small deltas.
{% endif %}
- Only include values that are meaningfully affected. Omit unaffected values (never return 0).
- If nothing meaningfully changes, return {"stats": {}}.

Reply schema:
{"stats": {"<value>": <integer delta>, ...}}

## user

{{ situation_text }}
