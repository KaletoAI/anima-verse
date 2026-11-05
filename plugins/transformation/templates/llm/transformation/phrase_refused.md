{#- Storyteller hint to the avatar alone when a spoken phrase changes
    nothing. reason: already_transformed | cooldown | not_transformed |
    not_holding_item | refused | ...; body: the linked character of the
    phrase; error: the refusal text of a refused swap. -#}
{%- if reason == "already_transformed" -%}
You are already transformed — nothing happens.
{%- elif reason == "cooldown" -%}
The power to become {{ body }} has not recovered yet — nothing happens.
{%- elif reason == "not_transformed" -%}
You are not transformed into {{ body }} — nothing happens.
{%- elif reason == "not_holding_item" -%}
You do not carry the power item — nothing happens.
{%- elif reason == "refused" and error -%}
Not now: {{ error }} Nothing happens.
{%- else -%}
Nothing happens.
{%- endif -%}
