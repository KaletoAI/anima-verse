{#- reveal_identity's state line for the tool decision. body, leader: the
    secret the character would reveal ("<body> is secretly <leader>");
    knowers_present / non_knowers_present: who present is / is not in on it
    (sorted). -#}
{{ body }} is secretly {{ leader }}. {% if knowers_present %}Already in on it: {{ knowers_present | join(", ") }}. {% endif %}{% if non_knowers_present %}Not in on it: {{ non_knowers_present | join(", ") }}.{% else %}Nobody present who is not in on it.{% endif %}
