{#- One secrecy line of the scene state (prompt_lines.blocks_for).
    kind: "body" (the character is the body standing in the world for its
    leader) or "knower_present" (the character knows a present, transformed
    body). body, leader: the two character names. knowers: who is in on it
    (body only, the family left out); non_knowers: who present is not.
    Lists come sorted; gender-neutral wording. -#}
{%- macro names(list) -%}
{%- if list | length == 1 -%}{{ list[0] }}{%- else -%}{{ list[:-1] | join(", ") }} and {{ list[-1] }}{%- endif -%}
{%- endmacro -%}
{%- if kind == "body" -%}
You are {{ body }}, and secretly {{ leader }}. Nobody may learn that you are {{ leader }}{% if knowers %}, except {{ names(knowers) }}{% endif %}.{% if non_knowers %} {{ names(non_knowers) }} {{ "does" if non_knowers | length == 1 else "do" }} not know — never reveal it in front of them.{% endif %}
{%- else -%}
{{ body }} here is secretly {{ leader }}.{% if non_knowers %} {{ names(non_knowers) }} {{ "does" if non_knowers | length == 1 else "do" }} not know — do not call {{ body }} "{{ leader }}" in front of them.{% endif %}
{%- endif -%}
