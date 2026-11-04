{#- reveal_identity's state line for the tool decision. alias: the persona
    the bearer would reveal; knowers_present / non_knowers_present: who
    present is / is not in on it (sorted). -#}
Persona {{ alias }}. {% if knowers_present %}Already in on it: {{ knowers_present | join(", ") }}. {% endif %}{% if non_knowers_present %}Not in on it: {{ non_knowers_present | join(", ") }}.{% else %}Nobody present who is not in on it.{% endif %}
