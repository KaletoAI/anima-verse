"""Ruling A147: a closable piece worn closed says so in its worn front edit.

Usage: ./.venv/bin/python scripts/smoke_worn_closed_a147.py

Hand-derived expectations (no storage, no server):
- cardigan, slots [outer] -> closable (garment_set.default_closable: outer) -> state closed,
  fragment "shapeless grey knitted cardigan with ink-stained cuffs" names no state ->
  "<fragment>, " + WORN_CLOSED.
- "open cardigan worn open" -> fragment_names_state True ("open") -> fragment alone.
- same cardigan in state open -> fragment alone (the open phrase comes from fragment(state=open)).
- skirt, slots [bottom] -> not closable -> fragment alone.
- fsig: fragment(item) for the closed cardigan stays the bare text (nothing re-renders).
"""
from app.core.garment_clothing import WORN, WORN_CLOSED, fragment, worn_text

def piece(frag, slots):
    return {"id": "x", "name": "n", "category": "outfit_piece", "prompt_fragment": frag,
            "outfit_piece": {"slots": slots}}

card = piece("shapeless grey knitted cardigan with ink-stained cuffs.", ["outer"])
t = fragment(card)
assert t == "shapeless grey knitted cardigan with ink-stained cuffs", t
got = WORN.format(fragment=worn_text(card, t, "closed"))
assert got == ("Keep the image exactly as it is. Only change their clothing: they now wear only shapeless grey "
               "knitted cardigan with ink-stained cuffs, worn closed, its fronts fastened together at the centre "
               "(buttoned / zipped / wrapped shut), any designed neckline or lapel opening kept as it is."), got
assert worn_text(card, t, "open") == t
op = piece("open cardigan worn open", ["outer"])
assert worn_text(op, fragment(op), "closed") == "open cardigan worn open"
sk = piece("pleated navy skirt", ["bottom"])
assert worn_text(sk, fragment(sk), "closed") == "pleated navy skirt"
assert "fastened" in WORN_CLOSED and "lapel" in WORN_CLOSED
print("ok: A147 worn closed wording")
