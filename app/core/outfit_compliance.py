"""Outfit-Compliance: zentrale Funktion die equipped_pieces gegen
Decency-Regeln + Intent abgleicht.

Plan: development_instructions/plan-outfit-system-rethink.md §2

Ersetzt das alte apply_outfit_type_compliance + outfit_types-Modell.
Decency ist die einzige harte Regel — Stil/Wetter sind reine LLM-Hinweise.

Decency-Werte:
- public:   top + bottom MUESSEN bedeckt sein
- private:  bei alone_in_room ODER is_intimate → alles OK; sonst wie public
- nude_ok:  immer alles OK

Modifikator swim_allowed: bei is_wet=True duerfen top/bottom durch
Swimwear-Pieces ersetzt werden oder leer bleiben.

Schritt 2 (May 2026): Decency-Logik live, aber is_intimate/is_wet/is_sleeping
sind State-Flags die in Schritt 6 dazukommen. Solange behandeln wir alle
Flags als False — die Compliance-Funktion akzeptiert sie aber schon als
optionale Parameter, sodass Schritt 6 nur Aufrufstellen erweitern muss.
"""
from typing import Any, Dict, List, Optional, Set

from app.core.log import get_logger
from app.models.inventory import (
    VALID_PIECE_SLOTS, _piece_slots, get_item, _load_inventory,
)

logger = get_logger("outfit_compliance")


# Slots die unter "decency=public" zwingend bedeckt sein muessen.
# (top + bottom — Unterwaesche zaehlt sozial nicht als "bedeckt".)
PUBLIC_REQUIRED_SLOTS: Set[str] = {"top", "bottom"}

# Swimwear-Slots: erfuellen public-Pflicht wenn swim_allowed + is_wet.
SWIM_SLOTS: Set[str] = {"swimwear_top", "swimwear_bottom"}


def _get_room_and_location(character_name: str) -> tuple[Optional[Dict], Optional[Dict]]:
    """Liefert (room, location) fuer den aktuellen Standort des Chars."""
    from app.models.character import (
        get_character_current_location, get_character_current_room,
    )
    from app.models.world import get_location_by_id
    loc_id = get_character_current_location(character_name) or ""
    if not loc_id:
        return None, None
    loc = get_location_by_id(loc_id) or {}
    if not loc:
        return None, None
    room_id = get_character_current_room(character_name) or ""
    room = None
    if room_id:
        for r in (loc.get("rooms") or []):
            if r.get("id") == room_id or r.get("name") == room_id:
                room = r
                break
    return room, loc


def _present_other_characters(character_name: str, room_id: str,
                              location_id: str) -> List[str]:
    """Namen aller anderen Chars im selben Raum.

    Liest character_state direkt — ungefiltert (player-controlled zaehlt
    als anwesend, da fuer Decency relevant).
    """
    if not (character_name and room_id and location_id):
        return []
    try:
        from app.core.db import get_connection
        conn = get_connection()
        rows = conn.execute(
            "SELECT character_name FROM character_state "
            "WHERE current_location=? AND current_room=? "
            "AND character_name != ?",
            (location_id, room_id, character_name),
        ).fetchall()
        return [r[0] for r in rows if r and r[0]]
    except Exception as e:
        logger.debug("_present_other_characters Fehler: %s", e)
        return []  # konservativ: wenn unklar → niemand → privacy gewaehren


def _is_humanoid(character_name: str) -> bool:
    """True wenn dieser Char menschartig ist (generisches Template-Feature
    ``humanoid``). Steuert u.a. die Decency-Eskalation: nur menschartige
    Anwesende zaehlen als "Zuschauer".

    Tiere o.ae. (animal-Templates: humanoid=False) eskalieren private nicht
    auf public. Default True (fail-open) fuer Templates ohne das Feature.
    """
    try:
        from app.models.character_template import is_feature_enabled
        return is_feature_enabled(character_name, "humanoid")
    except Exception as e:
        logger.debug("_is_humanoid Fehler: %s", e)
        return True  # konservativ: im Zweifel als Person zaehlen (bedeckt)


def _all_present_are_intimate(character_name: str,
                              others: List[str]) -> bool:
    """True wenn JEDE anwesende Person ein romantischer Partner ist (Paar).

    Nutzt den generischen Relationship-``type`` (Core-System: friend/romantic/
    rival/... — kein Template-Feld). Ein Paar darf vor einander privat bleiben;
    sobald eine nicht-romantische Person dazukommt, greift wieder public.
    Leere Liste = vacuously True (allein).
    """
    if not others:
        return True
    try:
        from app.models.relationship import get_relationship
        for other in others:
            rel = get_relationship(character_name, other) or {}
            if (rel.get("type") or "").strip().lower() != "romantic":
                return False
        return True
    except Exception as e:
        logger.debug("_all_present_are_intimate Fehler: %s", e)
        return False  # konservativ: im Zweifel public (bedeckt)


def resolve_decency(
    character_name: str,
    *,
    is_intimate: bool = False,
) -> tuple[str, Dict[str, Any]]:
    """Ermittelt den effektiven Decency-Wert + Context-Info.

    Reihenfolge:
        1. is_intimate=True ODER decency_exempt-Flag → "nude_ok" (Override)
        2. room.decency
        3. location.decency
        4. Default: "public"

    private wird zu "public" eskaliert wenn eine nicht-romantische, fuer
    menschartige (humanoid) Person im Raum ist.

    Returns: (decency, context-dict mit Debug-Info)
    """
    if is_intimate:
        return "nude_ok", {"reason": "is_intimate"}

    # decency_exempt: manuell/per Rule/Skill gesetzter Dauer-Override (== nude_ok)
    try:
        from app.models.character import get_state_flags
        if get_state_flags(character_name).get("decency_exempt"):
            return "nude_ok", {"reason": "decency_exempt"}
    except Exception:
        pass

    room, loc = _get_room_and_location(character_name)
    raw_decency = ""
    source = ""
    if room and room.get("decency"):
        raw_decency = (room.get("decency") or "").strip().lower()
        source = "room"
    elif loc and loc.get("decency"):
        raw_decency = (loc.get("decency") or "").strip().lower()
        source = "location"
    else:
        raw_decency = "public"
        source = "default"

    ctx: Dict[str, Any] = {
        "source": source,
        "raw": raw_decency,
        "room_id": (room or {}).get("id"),
        "location_id": (loc or {}).get("id"),
        "swim_allowed": bool(
            (room or {}).get("swim_allowed") or (loc or {}).get("swim_allowed")
        ),
        "style_hint": (
            (room or {}).get("style_hint") or (loc or {}).get("style_hint") or ""
        ),
    }

    if raw_decency == "private":
        others = _present_other_characters(
            character_name, ctx["room_id"] or "", ctx["location_id"] or "")
        # Nur menschartige Personen sind "Zuschauer". Tiere o.ae. eskalieren
        # private nicht.
        relevant = [o for o in others if _is_humanoid(o)]
        if not relevant:
            ctx["alone"] = True
            return "private", ctx
        # Paar-Ausnahme: sind alle (zaehlenden) Anwesenden romantische Partner,
        # bleibt der Raum privat (man zieht sich vor dem Partner nicht an).
        if _all_present_are_intimate(character_name, relevant):
            ctx["private_with_partner"] = True
            return "private", ctx
        ctx["escalated_to_public"] = True
        return "public", ctx

    return raw_decency, ctx


def _check_decency_violations(
    eq_pieces: Dict[str, str],
    decency: str,
    *,
    swim_allowed: bool = False,
    is_wet: bool = False,
) -> Set[str]:
    """Liefert die Menge der Slots die laut Decency belegt sein muessten
    aber leer/uneinheitlich sind. Leere Menge = keine Verletzung.
    """
    if decency in ("nude_ok", "private"):
        return set()
    if decency != "public":
        # Unbekannte Decency: defensiv keine Verletzung melden
        return set()
    # public: top + bottom muessen bedeckt sein
    missing = {s for s in PUBLIC_REQUIRED_SLOTS if not eq_pieces.get(s)}
    if swim_allowed and is_wet:
        # Swim-Exemption: swimwear-Slots zaehlen als bedeckt
        if eq_pieces.get("swimwear_top"):
            missing.discard("top")
        if eq_pieces.get("swimwear_bottom"):
            missing.discard("bottom")
    return missing


def _find_inventory_piece_for_slot(
    character_name: str,
    target_slot: str,
    *,
    style_hint: str = "",
    exclude_ids: Optional[Set[str]] = None,
) -> Optional[str]:
    """Sucht im Inventar ein Outfit-Piece das den Slot belegt.

    Nimmt das erste passende Single-Slot-Piece. (Die fruehere outfit_types/
    style_hint-Praeferenz entfaellt — outfit_types-Modell ist raus; style_hint
    ist nur noch ein Creation-Hinweis, keine mechanische Auswahlregel.)
    Multi-Slot-Pieces werden uebersprungen — die kommen ueber ChangeOutfit /
    Garderobe, sonst wuerden sie bestehende Slots verdraengen.
    """
    exclude_ids = exclude_ids or set()
    inv = _load_inventory(character_name).get("inventory", [])
    for entry in inv:
        iid = entry.get("item_id")
        if not iid or iid in exclude_ids:
            continue
        item = get_item(iid)
        if not item or item.get("category") != "outfit_piece":
            continue
        slots = _piece_slots(item)
        if target_slot not in slots or len(slots) > 1:
            continue
        return iid
    return None


def apply_outfit_compliance(
    character_name: str,
    *,
    is_intimate: Optional[bool] = None,
    is_wet: Optional[bool] = None,
    is_sleeping: Optional[bool] = None,
) -> Dict[str, Any]:
    """Zentrale Compliance-Funktion (Plan §2).

    State-Flags (is_intimate, is_wet, is_sleeping) werden — wenn nicht
    explizit uebergeben — aus character_state gelesen. Schritt 6 (May 2026):
    Activity-Skills setzen die Flags, Compliance liest sie automatisch.

    Algorithmus:
        1. is_sleeping=True → no-op (off-map)
        2. intent.locked → no-op
        3. intent.forced_pieces respektieren (Slot belegt = bleibt)
        4. intent.forbidden_slots → diese Slots werden geleert
        5. Decency-Check gegen das resultierende equipped_pieces
        6. Verletzte Slots: Auto-Fill aus Inventar (style_hint priorisiert)
        7. Auch nach Auto-Fill verletzt: Notification

    Returns:
        {
          "status": "ok" | "locked" | "skipped",
          "decency": str,
          "intent_locked": bool,
          "forced_kept": [slot, ...],
          "forbidden_cleared": [slot, ...],
          "auto_filled": [{slot, item_id}, ...],
          "violations": [{slot, reason}, ...],
        }
    """
    from app.models.character import (
        get_character_profile, save_character_profile, get_outfit_intent,
        get_state_flags,
    )

    # State-Flags aus dem Profil ziehen wenn nicht ueberschrieben
    if is_intimate is None or is_wet is None or is_sleeping is None:
        flags = get_state_flags(character_name)
        if is_intimate is None:
            is_intimate = flags["is_intimate"]
        if is_wet is None:
            is_wet = flags["is_wet"]
        if is_sleeping is None:
            is_sleeping = flags["is_sleeping"]

    result: Dict[str, Any] = {
        "status": "ok",
        "decency": "",
        "intent_locked": False,
        "forced_kept": [],
        "forbidden_cleared": [],
        "auto_filled": [],
        "violations": [],
    }

    if is_sleeping:
        # Schlafende Chars sind off-map — keine Compliance.
        result["status"] = "skipped"
        result["reason"] = "is_sleeping"
        return result

    intent = get_outfit_intent(character_name)
    if intent.get("locked"):
        result["status"] = "locked"
        result["intent_locked"] = True
        return result

    decency, ctx = resolve_decency(character_name, is_intimate=is_intimate)
    result["decency"] = decency
    result["decency_context"] = ctx

    profile = get_character_profile(character_name) or {}
    eq_pieces: Dict[str, str] = dict(profile.get("equipped_pieces") or {})
    changed = False

    # 1. forced_pieces: stelle sicher, dass die geforderten Items angelegt sind.
    forced = intent.get("forced_pieces") or {}
    for slot, iid in forced.items():
        if eq_pieces.get(slot) != iid:
            # Wir SETZEN das nicht aktiv — das ist Aufgabe von ChangeOutfit /
            # equip_piece (die kuemmern sich um Multi-Slot-Mirroring,
            # Verdraengung etc.). Compliance respektiert nur den Status quo
            # und meldet wenn das forced piece nicht angelegt ist.
            result["violations"].append(
                {"slot": slot, "reason": "forced_piece_not_equipped",
                 "expected": iid, "actual": eq_pieces.get(slot)}
            )
        else:
            result["forced_kept"].append(slot)

    # 2. forbidden_slots: leeren falls noch belegt (und nicht forced).
    forbidden = set(intent.get("forbidden_slots") or [])
    if forbidden:
        from app.models.inventory import unequip_piece
        for slot in sorted(forbidden):
            if slot in forced:
                continue  # forced gewinnt gegen forbidden (Konflikt-Sonderfall)
            if eq_pieces.get(slot):
                # unequip_piece kuemmert sich um Multi-Slot-Mirror
                try:
                    unequip_piece(character_name, slot=slot)
                    eq_pieces.pop(slot, None)
                    result["forbidden_cleared"].append(slot)
                    changed = True
                except Exception as e:
                    logger.debug("forbidden_slots clear [%s/%s]: %s",
                                 character_name, slot, e)

    # 3. Decency-Check
    swim_allowed = bool(ctx.get("swim_allowed"))
    missing = _check_decency_violations(
        eq_pieces, decency,
        swim_allowed=swim_allowed, is_wet=is_wet,
    )

    # 4. Auto-Fill: violations beheben, AUSSER der Slot ist forbidden
    style_hint = ctx.get("style_hint") or intent.get("target_outfit_type") or ""
    auto_fill_attempted = []
    for slot in sorted(missing):
        if slot in forbidden:
            # User/LLM hat den Slot explizit als leer markiert — nicht auffuellen
            result["violations"].append(
                {"slot": slot, "reason": "forbidden_but_decency_violated"}
            )
            continue
        # Inventar-Suche
        exclude = set(eq_pieces.values())
        cand_id = _find_inventory_piece_for_slot(
            character_name, slot,
            style_hint=style_hint, exclude_ids=exclude,
        )
        auto_fill_attempted.append(slot)
        if not cand_id:
            result["violations"].append(
                {"slot": slot, "reason": "no_inventory_piece"}
            )
            continue
        # Equippen ueber equip_piece (kuemmert sich um Mirror, Persistenz)
        from app.models.inventory import equip_piece
        try:
            equip_piece(character_name, cand_id)
            eq_pieces[slot] = cand_id
            result["auto_filled"].append({"slot": slot, "item_id": cand_id})
            changed = True
        except Exception as e:
            logger.warning("auto_fill [%s/%s] fehlgeschlagen: %s",
                           character_name, slot, e)
            result["violations"].append(
                {"slot": slot, "reason": f"equip_failed: {e}"}
            )

    # 5. Persist + Event
    if changed:
        # equipped_pieces wurden bereits ueber equip/unequip_piece persistiert.
        # outfit_events wurden dabei auch schon publiziert.
        logger.info(
            "outfit_compliance [%s] decency=%s: filled=%d, cleared=%d, violations=%d",
            character_name, decency,
            len(result["auto_filled"]),
            len(result["forbidden_cleared"]),
            len(result["violations"]),
        )

    # 6. Notification bei harten Decency-Verletzungen (nicht forbidden)
    hard_violations = [
        v for v in result["violations"]
        if v.get("reason") in ("no_inventory_piece", "forced_piece_not_equipped")
    ]
    if hard_violations:
        try:
            from app.models.notifications import add_notification
            slots = ", ".join(v["slot"] for v in hard_violations)
            add_notification(
                character_name,
                (f"⚠️ Outfit passt nicht zu {decency}-Raum — fehlt: {slots}. "
                 "Keine passende Kleidung im Inventar."),
                notification_type="outfit_mismatch",
            )
        except Exception:
            pass

    return result
