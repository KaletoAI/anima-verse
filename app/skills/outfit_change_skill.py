"""ChangeOutfit Skill — Wechselt zwischen Outfit-Pieces aus dem Inventar.

Dieser Skill ERZEUGT KEINE neuen Outfits — er ruestet nur Pieces an
und ab, die der Character bereits in seinem Inventar hat. Fuer das
Erzeugen neuer Pieces / Outfits ist OutfitCreation zustaendig.

Input-Format (JSON oder Freitext):
  - JSON: {"equip": ["item_id1", "Name2"], "unequip_slots": ["outer"],
            "unequip_items": ["item_id3"], "outfit_preset": "Streetwear"}
  - Freitext: "Lederjacke, schwarze Sneaker" — wird gegen Inventar gematcht
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
    """Wechselt zwischen Pieces im Inventar — keine Erfindungen."""

    SKILL_ID = "outfit_change"
    ALWAYS_LOAD = True

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        from app.core.prompt_templates import load_skill_meta
        meta = load_skill_meta("outfit_change")
        self.name = meta["name"]
        self.description = meta["description"]
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
        """Setzt Outfit-Intent (forced_pieces / forbidden_slots) + ruft
        Decency-Compliance fuer den Char auf. Auto-Fill und
        OutfitCreation-Fallback wurden in Schritt 4 entfernt (Plan §4) —
        Compliance ist allein zustaendig fuer Slot-Korrektheit.
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

        # Intent laden + modifizieren (Single-Save am Ende).
        intent = get_outfit_intent(character_name)
        forced: Dict[str, str] = dict(intent.get("forced_pieces") or {})
        forbidden: set = set(intent.get("forbidden_slots") or [])

        # (Frueherer outfit_type-Pfad entfernt — das outfit_types-Tag-Modell ist
        # raus, Variante A. Ein kompletter Stil-Wechsel laeuft jetzt ueber
        # OutfitCreation/explizites Equip; Bedeckung regelt Decency.)

        # 2) Unequip Slots — Slot leeren + forbidden markieren.
        # Compliance/AutoFill respektiert forbidden_slots und fuellt nicht.
        for slot in spec.get("unequip_slots", []):
            res = unequip_piece(character_name, slot=slot)
            if res.get("status") == "ok":
                results.append(f"Slot '{slot}' geleert")
                # Multi-Slot-Pieces: ALLE cleared_slots forbidden machen
                for s in (res.get("cleared_slots") or [slot]):
                    forbidden.add(s)
                    forced.pop(s, None)
            else:
                errors.append(f"Slot '{slot}': {res.get('reason', 'unbekannt')}")

        # 3) Unequip einzelne Items — fuer Pieces gleiches Forbidden-Update,
        # fuer Hand-Items (equipped_items) kein Intent-Begriff noetig.
        for token in spec.get("unequip_items", []):
            iid = resolve_item_id(token) or token
            # erst als Piece versuchen, dann als Item
            r = unequip_piece(character_name, item_id=iid)
            piece_unequipped = r.get("status") == "ok"
            if not piece_unequipped:
                r = unequip_item(character_name, iid)
            if r.get("status") == "ok":
                results.append(f"'{self._item_label(iid)}' abgelegt")
                if piece_unequipped:
                    for s in (r.get("cleared_slots") or []):
                        forbidden.add(s)
                        forced.pop(s, None)
            else:
                errors.append(f"'{token}': {r.get('reason', 'nicht equipped')}")

        # 4) Equip Tokens — Piece-Equip + forced_pieces setzen.
        inv_items = self._inventory_item_index(character_name)
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
                r = equip_piece(character_name, iid)
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
                r = equip_item(character_name, iid)
                if r.get("status") == "ok":
                    results.append(f"'{it.get('name', iid)}' an die Hand genommen")
                else:
                    errors.append(f"'{token}': {r.get('reason', 'equip fehlgeschlagen')}")

        # 5) Intent persistieren
        intent["forced_pieces"] = forced
        intent["forbidden_slots"] = sorted(forbidden)
        set_outfit_intent(character_name, intent)

        # 6) Compliance laufen lassen — Decency-Check + Notification.
        # Auto-Fill schliesst Decency-Verletzungen (falls passende Pieces
        # im Inventar), sonst geht eine Notification raus. Compliance
        # respektiert forced_pieces und forbidden_slots — kein "Top
        # zieht sich sofort wieder an"-Bug mehr.
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

        # Ergebnis zusammenfassen
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
        """Normalisiert den Skill-Input in ein Dict mit equip/unequip/type Feldern."""
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

        # Freitext-Fallback (input-Feld) — Liste von Tokens, kommagetrennt,
        # als zu equippende Piece-Namen interpretiert (kein outfit_type mehr).
        text = (ctx.get("input") or "").strip()
        if text and not (spec["equip"] or spec["unequip_slots"]
                          or spec["unequip_items"]):
            spec["equip"] = [t.strip() for t in re.split(r"[,;]+", text) if t.strip()]
        return spec

    # ------------------------------------------------------------------
    # Inventar-Matching
    # ------------------------------------------------------------------

    def _inventory_item_index(self, character_name: str) -> List[Dict[str, Any]]:
        """Liefert die Inventar-Items des Characters mit Item-Details."""
        inv = get_character_inventory(character_name, include_equipped=True)
        return inv.get("inventory", [])

    def _match_inventory(self, token: str, inv: List[Dict[str, Any]]) -> str:
        """Resolved einen Token (ID oder Name) gegen die Inventar-Items."""
        if not token:
            return ""
        token_l = token.strip().lower()
        # 1) ID exakt
        for entry in inv:
            if entry.get("item_id") == token:
                return token
        # 2) Name exakt (case-insensitive)
        for entry in inv:
            if (entry.get("item_name") or "").strip().lower() == token_l:
                return entry.get("item_id", "")
        # 3) Substring-Match auf Name (vermeide false positives bei zu kurzem Token)
        if len(token_l) >= 3:
            for entry in inv:
                name_l = (entry.get("item_name") or "").strip().lower()
                if token_l in name_l or name_l in token_l:
                    return entry.get("item_id", "")
        return ""

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
