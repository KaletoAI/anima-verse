{#- One identity line of the scene state (prompt_lines.blocks_for).
    kind: "bearer" (the character wears the persona), "knower_present"
    (the character knows a present, transformed bearer) or "mapping".
    alias, name: the persona's alias and the bearer's real name.
    knowers: who is in on it (bearer only); non_knowers: who present is not.
    Lists come sorted; gender-neutral wording. -#}
{%- macro names(list) -%}
{%- if list | length == 1 -%}{{ list[0] }}{%- else -%}{{ list[:-1] | join(", ") }} and {{ list[-1] }}{%- endif -%}
{%- endmacro -%}
{%- if kind == "bearer" -%}
You are currently {{ alias }}. {% if knowers %}Only {{ names(knowers) }} {{ "knows" if knowers | length == 1 else "know" }} that you are {{ name }}.{% else %}Nobody else knows that you are {{ name }}.{% endif %}{% if non_knowers %} {{ names(non_knowers) }} {{ "does" if non_knowers | length == 1 else "do" }} not know — never reveal it in front of them.{% endif %}
{%- elif kind == "knower_present" -%}
{{ alias }} here is actually {{ name }}.{% if non_knowers %} {{ names(non_knowers) }} {{ "does" if non_knowers | length == 1 else "do" }} not know — do not call {{ alias }} "{{ name }}" in front of them.{% endif %}
{%- else -%}
{{ alias }} = {{ name }}
{%- endif -%}
