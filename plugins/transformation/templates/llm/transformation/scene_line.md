{#- One secrecy line of the scene state (prompt_lines.blocks_for).
    kind: "body" (the character is the body standing in the world for its
    leader), "leader" (the character is the leader standing in the world, the
    body is its secret other self), "knower_present" (the character knows a
    present, transformed body) or "knower_leader_present" (the character
    knows that a present leader is secretly that body). body, leader: the two
    character names. knowers: who is in on it (body and leader only, the
    family left out); non_knowers: who present is not.
    Lists come sorted; gender-neutral wording. -#}
{%- macro names(list) -%}
{%- if list | length == 1 -%}{{ list[0] }}{%- else -%}{{ list[:-1] | join(", ") }} and {{ list[-1] }}{%- endif -%}
{%- endmacro -%}
{%- if kind == "body" -%}
You are {{ body }}, and secretly {{ leader }}. Nobody may learn that you are {{ leader }}{% if knowers %}, except {{ names(knowers) }}{% endif %}.{% if non_knowers %} {{ names(non_knowers) }} {{ "does" if non_knowers | length == 1 else "do" }} not know — never reveal it in front of them.{% endif %}
{%- elif kind == "leader" -%}
You are {{ leader }}, and secretly also {{ body }}. Nobody may learn that you are {{ body }}{% if knowers %}, except {{ names(knowers) }}{% endif %}.{% if non_knowers %} {{ names(non_knowers) }} {{ "does" if non_knowers | length == 1 else "do" }} not know — never reveal it in front of them.{% endif %}
{%- elif kind == "knower_leader_present" -%}
{{ leader }} here is secretly {{ body }}.{% if non_knowers %} {{ names(non_knowers) }} {{ "does" if non_knowers | length == 1 else "do" }} not know — do not call {{ leader }} "{{ body }}" in front of them.{% endif %}
{%- else -%}
{{ body }} here is secretly {{ leader }}.{% if non_knowers %} {{ names(non_knowers) }} {{ "does" if non_knowers | length == 1 else "do" }} not know — do not call {{ body }} "{{ leader }}" in front of them.{% endif %}
{%- endif -%}
