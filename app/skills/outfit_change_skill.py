"""ChangeOutfit skill — switches between outfit pieces from the inventory.

This skill CREATES NO new outfits — it only puts on and takes off pieces
the character already has in its inventory. Creating new pieces / outfits
is CreateOutfit's job.

Input format (JSON or free text):
  - JSON: {"equip": ["item_id1", "Name2"], "unequip_slots": ["outer"],
            "unequip_items": ["item_id3"], "outfit_preset": "Streetwear"}
  - free text: "leather jacket, black sneakers" — matched against the inventory
"""
import json
import re
from typing import Any, Dict, List

from .base import BaseSkill, ToolSpec

from app.core.log import get_logger
from app.models.inventory import (
    get_character_inventory,
    get_item,
    resolve_item_id,
    equip_piece,
    unequip_piece,
    equip_item,
    unequip_item)

logger = get_logger("outfit_change")


class OutfitChangeSkill(BaseSkill):
    """Switches between pieces in the inventory — no inventions."""
    SINGLETON = True

    SKILL_ID = "outfit_change"
    ALWAYS_LOAD = True
    # [INTENT: change_outfit | hint=...] (F6) — dispatched here.
    INTENT_TYPES = ("change_outfit",)
    INTENT_PAYLOAD_KEYS = ("hint", "style")

    def handle_intent(self, intent_type, payload):
        """[INTENT: change_outfit]: hint/style becomes the input; the daily
        limit does not apply to committed intents."""
        import json as _json
        hint = payload.get("hint", "") or payload.get("style", "")
        raw_input = _json.dumps({
            "input": hint or "Change your outfit",
            "agent_name": payload.get("agent_name", ""),
            "user_id": "",
            "skip_daily_limit": True,
        })
        result = self.execute(raw_input)
        success = bool(result) and "Fehler" not in str(result)
        return {"success": success, "result": str(result)[:500]}

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        from app.core.prompt_templates import load_skill_meta
        meta = load_skill_meta("outfit_change")
        self.name = meta["name"]
        self.description = meta["description"]
        self.action_hint = meta.get("action_hint", "")
        self._defaults = {"enabled": True}
        logger.info("ChangeOutfit Skill initialized (swap-only)")

    def execute(self, raw_input: str) -> str:
        if not self.enabled:
            return "ChangeOutfit Skill ist deaktiviert."
        try:
            return self._execute_inner(raw_input)
        except Exception as e:
            logger.exception("ChangeOutfit Fehler: %s", e)
            return f"Fehler beim Outfit-Wechsel: {e}"

    def _execute_inner(self, raw_input: str) -> str:
        """Set the outfit intent (forced_pieces / forbidden_slots) and run
        the decency compliance for the character. Auto-fill and the
        OutfitCreation fallback were removed in step 4 (plan §4) —
        compliance alone is responsible for slot correctness.
        """
        from app.models.character import (
            get_outfit_intent, set_outfit_intent,
        )

        ctx = self._parse_base_input(raw_input)
        character_name = ctx.get("agent_name", "").strip()
        if not character_name:
            return "Fehler: user_id/character_name fehlt."

        spec = self._parse_input_spec(ctx)

        results: List[str] = []
        errors: List[str] = []

        # Load + modify the intent (a single save at the end).
        intent = get_outfit_intent(character_name)
        forced: Dict[str, str] = dict(intent.get("forced_pieces") or {})
        forbidden: set = set(intent.get("forbidden_slots") or [])

        # (The former outfit_type path is gone with the outfit_types tag
        # model, variant A. A complete change of style runs through
        # OutfitCreation / explicit equips; decency handles coverage.)

        # 2) Unequip slots — empty the slot + mark it forbidden.
        # Compliance/auto-fill respects forbidden_slots and does not fill.
        for slot in spec.get("unequip_slots", []):
            res = unequip_piece(character_name, slot=slot, source="skill")
            if res.get("status") == "ok":
                # Name the removed piece, not the slot ("feet" -> the shoes).
                _nm = self._item_label(res.get("item_id")) or f"slot '{slot}'"
                results.append(f"'{_nm}' abgelegt")
                # Multi-slot pieces: mark ALL cleared_slots forbidden
                for s in (res.get("cleared_slots") or [slot]):
                    forbidden.add(s)
                    forced.pop(s, None)
            else:
                errors.append(f"Slot '{slot}': {res.get('reason', 'unbekannt')}")

        # 3) Unequip single items — the same forbidden update for pieces;
        # hand items (equipped_items) need no intent.
        inv_items = self._inventory_item_index(character_name)
        for token in spec.get("unequip_items", []):
            # Names as the decision menu lists them, like equip — never a
            # guess: taking off the wrong piece is worse than nothing.
            iid = (self._match_inventory(token, inv_items, guess=False)
                   or resolve_item_id(token) or token)
            # try as a piece first, then as an item
            r = unequip_piece(character_name, item_id=iid, source="skill")
            piece_unequipped = r.get("status") == "ok"
            if not piece_unequipped:
                r = unequip_item(character_name, iid, source="skill")
            if r.get("status") == "ok":
                results.append(f"'{self._item_label(iid)}' abgelegt")
                if piece_unequipped:
                    for s in (r.get("cleared_slots") or []):
                        forbidden.add(s)
                        forced.pop(s, None)
            else:
                errors.append(f"'{token}': {r.get('reason', 'nicht equipped')}")

        # 4) Equip tokens — equip the piece + set forced_pieces.
        for token in spec.get("equip", []):
            iid = self._match_inventory(token, inv_items)
            if not iid:
                errors.append(
                    f"'{token}' nicht im Inventar. Verfuegbar: "
                    + (", ".join(self._inventory_summary(inv_items)) or "(leer)")
                )
                continue
            it = get_item(iid)
            if not it:
                errors.append(f"'{token}': Item-Definition fehlt")
                continue
            if it.get("category") == "outfit_piece":
                r = equip_piece(character_name, iid, source="skill")
                if r.get("status") == "ok":
                    slots_str = "+".join(r.get("slots") or [])
                    msg = f"'{it.get('name', iid)}' angelegt (Slot {slots_str})"
                    if r.get("displaced"):
                        labels = ", ".join(self._item_label(d) for d in r["displaced"])
                        msg += f", ersetzt '{labels}'"
                    results.append(msg)
                    for s in (r.get("slots") or []):
                        forced[s] = iid
                        forbidden.discard(s)
                else:
                    errors.append(f"'{token}': {r.get('reason', 'equip fehlgeschlagen')}")
            else:
                r = equip_item(character_name, iid, source="skill")
                if r.get("status") == "ok":
                    results.append(f"'{it.get('name', iid)}' an die Hand genommen")
                else:
                    errors.append(f"'{token}': {r.get('reason', 'equip fehlgeschlagen')}")

        # 5) Persist the intent
        intent["forced_pieces"] = forced
        intent["forbidden_slots"] = sorted(forbidden)
        set_outfit_intent(character_name, intent)

        # 6) Run compliance — decency check + notification. Auto-fill
        # closes decency gaps (when matching pieces are in the inventory),
        # otherwise a notification goes out. Compliance respects
        # forced_pieces and forbidden_slots — no more "the top puts itself
        # right back on" bug.
        try:
            from app.core.outfit_compliance import apply_outfit_compliance
            comp = apply_outfit_compliance(character_name)
            if comp.get("auto_filled"):
                names = ", ".join(
                    self._item_label(f["item_id"]) for f in comp["auto_filled"]
                )
                results.append(f"Compliance ergaenzte {names}")
        except Exception as _ce:
            logger.debug("Compliance-Aufruf in ChangeOutfit fehlgeschlagen: %s", _ce)

        # Summarise the result
        out_parts: List[str] = []
        if results:
            out_parts.append(" • ".join(results))
        if errors:
            out_parts.append("FEHLER: " + "; ".join(errors))
        if not out_parts:
            out_parts.append("Nichts geaendert — kein passendes Piece im Inventar.")

        return ". ".join(out_parts)

    # ------------------------------------------------------------------
    # Input-Parsing
    # ------------------------------------------------------------------

    def _parse_input_spec(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        """Normalise the skill input into a dict with equip/unequip fields."""
        spec: Dict[str, Any] = {
            "equip": [],
            "unequip_slots": [],
            "unequip_items": [],
        }
        for key in ("equip", "unequip_slots", "unequip_items"):
            val = ctx.get(key)
            if isinstance(val, list):
                spec[key] = [str(x).strip() for x in val if str(x).strip()]
            elif isinstance(val, str) and val.strip():
                spec[key] = [val.strip()]

        # Free-text fallback (the input field) — comma-separated tokens,
        # read as names of pieces to equip (no outfit_type any more).
        text = (ctx.get("input") or "").strip()
        if text and not (spec["equip"] or spec["unequip_slots"]
                          or spec["unequip_items"]):
            spec["equip"] = [t.strip() for t in re.split(r"[,;]+", text) if t.strip()]
        return spec

    # ------------------------------------------------------------------
    # Inventory matching
    # ------------------------------------------------------------------

    def _inventory_item_index(self, character_name: str) -> List[Dict[str, Any]]:
        """The character's inventory entries with item details."""
        inv = get_character_inventory(character_name, include_equipped=True)
        return inv.get("inventory", [])

    def _match_inventory(self, token: str, inv: List[Dict[str, Any]],
                         guess: bool = True) -> str:
        """Resolve a token (id or name) against the inventory entries.

        A trailing "(…)" is the decision menu's note and is dropped. With
        ``guess`` a name that matches nothing takes the one outfit piece
        that is the same kind of thing (:meth:`_closest_piece`)."""
        if not token:
            return ""
        token = re.sub(r"\s*\([^)]*\)\s*$", "", token.strip()) or token.strip()
        token_l = token.lower()
        # 1) exact id
        for entry in inv:
            if entry.get("item_id") == token:
                return token
        # 2) exact name (case-insensitive)
        for entry in inv:
            if (entry.get("item_name") or "").strip().lower() == token_l:
                return entry.get("item_id", "")
        # 3) substring match on the name (no false positives from too short a token)
        if len(token_l) >= 3:
            for entry in inv:
                name_l = (entry.get("item_name") or "").strip().lower()
                if token_l in name_l or name_l in token_l:
                    return entry.get("item_id", "")
        return self._closest_piece(token_l, inv) if guess else ""

    @staticmethod
    def _closest_piece(token_l: str, inv: List[Dict[str, Any]]) -> str:
        """The one outfit piece a free name most likely means, else "".

        A tool model takes names from the roleplay text ("eine lange Bluse
        und Shorts" -> "long blouse", "shorts") instead of the menu. First
        the last word, the kind of piece in an English name, against the
        piece's last word ("long blouse" -> "Sheer silk blouse"), then
        anywhere in its name ("shorts" -> "Short skirt"); a plural "s" is
        ignored, a colour alone never matches ("red cup" takes no red top).
        Two candidates at the first step that finds any: no guess."""
        def words(text):
            found = [w[:-1] if len(w) > 3 and w.endswith("s") else w
                     for w in re.findall(r"[^\W\d_]+", text.lower())]
            return [w for w in found if len(w) >= 3]

        wanted = words(token_l)
        if not wanted:
            return ""
        pieces = [(e, words(e.get("item_name") or "")) for e in inv
                  if e.get("item_category") == "outfit_piece"]
        for hit in (lambda ws: bool(ws) and ws[-1] == wanted[-1],
                    lambda ws: wanted[-1] in ws):
            found = [e for e, ws in pieces if hit(ws)]
            if found:
                if len(found) > 1:
                    return ""
                logger.info("ChangeOutfit: '%s' taken as '%s'", token_l, found[0].get("item_name"))
                return found[0].get("item_id", "")
        return ""

    def decision_menu(self, character_name: str) -> List[str]:
        """The character's clothes for the tool decision: the name this verb
        matches, the slots, and "worn" — what goes on, what it replaces,
        what can come off, sorted by name so the block stays the same from
        turn to turn. Ids and prompt text stay out; the tool LLM only
        copies a name."""
        lines = []
        for entry in self._inventory_item_index(character_name):
            if entry.get("item_category") != "outfit_piece":
                continue
            slots = "+".join((entry.get("outfit_piece") or {}).get("slots") or [])
            detail = ", ".join(part for part in (slots, "worn" if entry.get("equipped") else "") if part)
            lines.append(f"{entry.get('item_name')}" + (f" ({detail})" if detail else ""))
        return sorted(lines, key=str.lower)

    def _inventory_summary(self, inv: List[Dict[str, Any]]) -> List[str]:
        return [
            (e.get("item_name") or e.get("item_id") or "?")
            for e in inv
            if e.get("item_category") in ("outfit_piece", "tool", "decoration", "gift", "consumable")
        ][:20]

    @staticmethod
    def _item_label(item_id: str) -> str:
        it = get_item(item_id)
        return it.get("name") if it else item_id

    # ------------------------------------------------------------------
    # Tool-Spec
    # ------------------------------------------------------------------

    def as_tool(self, **kwargs) -> ToolSpec:
        return ToolSpec(
            name=self.name,
            description=self.description,
            func=self.execute)
