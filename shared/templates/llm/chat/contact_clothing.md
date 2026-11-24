{#- The reason a contact clip cannot start yet (app/core/contact_clothing.py, owner decision 2026-11-25): who still
    wears which piece. Vars: people = [{name, pieces: [item name], ids: [item id]}]. -#}
Not yet: {% for p in people %}{{ p.name }} still wears {{ p.pieces | join(", ") }} ({{ p.ids | join(", ") }}){% if not loop.last %}; {% endif %}{% endfor %}. That has to come off first — whoever wears it takes it off with ChangeOutfit {"unequip_items": ["<item id>"]} — then try again.
