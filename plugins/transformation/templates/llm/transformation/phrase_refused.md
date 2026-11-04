{#- Storyteller hint to the avatar alone when a spoken phrase changes
    nothing. reason: already_transformed | cooldown | not_transformed |
    not_holding_item | unknown_persona; alias: the persona's alias. -#}
{%- if reason == "already_transformed" -%}
You are already transformed — nothing happens.
{%- elif reason == "cooldown" -%}
The power of {{ alias }} has not recovered yet — nothing happens.
{%- elif reason == "not_transformed" -%}
You are not transformed into {{ alias }} — nothing happens.
{%- else -%}
Nothing happens.
{%- endif -%}
