#!/usr/bin/env python3
"""Smoke: the observer-relative identity view (``app/core/identity_view.py``).

Usage:  ./.venv/bin/python scripts/smoke_identity_view.py

Throwaway storage (tempfile + ``paths.init`` BEFORE any world-DB module is
imported), no server, no real world DB, no LLM. The only world data is three
roster rows (Cara, Kim, Obs) — ``resolve_name`` maps a real name through the
roster, nothing else here touches the DB.

THE RULE (restated from the plan so every value below is derivable)
    * persona of C = what the ``identity.active_persona`` provider answers for C
      (``None``, a non-dict, an answer without alias, or a raising provider
      = no persona).
    * knows(O, C) = O and C equal after casefold, or C has no persona, or the
      ``identity.knows`` provider says True. Persona present but no knows
      provider = False. A RAISING knows provider = True ("as if the package
      were absent").
    * shown_name(O, C) = C if no persona or O is C; "<alias> (<C>)" if O knows;
      the alias otherwise; a raising knows provider = C.
    * identity_key(C) = public_label(C) = alias while C has a persona, else C.
    * masked_description(O, C) = persona description when O is a non-knower of
      C's active persona, else None.
    * resolve_name(O, token): a roster name (exact, then casefold) -> that roster
      name; the casefolded alias of an ACTIVE persona -> its subject;
      anything else -> None.
    * is_persona_name(n) = n (stripped, casefolded) is among the names the
      ``identity.persona_names`` provider lists — transformed or not.
    * identity_snapshot(names) = {C: alias} for the transformed ones.
    * rewrite_names(O, text, subjects): every whole-word, case-sensitive
      occurrence of a transformed subject's real name -> shown_name(O, C).
    * validate_character_name refuses a persona name with code "reserved".

FIXTURE: providers registered with owner "smoke" — Cara wears persona p1
"Moonveil" ("a masked figure in a dark suit"), only Kim knows; the names
provider lists "Moonveil" and (in [3]) the inactive "Starfall".

EXPECTED, derived BY HAND from the rule above
---------------------------------------------
[0] no provider registered
    shown_name(Obs, Cara) = "Cara"; identity_key(Cara) = "Cara";
    public_label(Cara) = "Cara"; resolve_name(Obs, "Moonveil") = None (not on
    the roster, no persona); resolve_name(Obs, "cara") = "Cara" (casefold
    roster hit); knows(Obs, Cara) = True (no persona); masked_description = None;
    rewrite leaves the text alone; is_persona_name("Moonveil") = False;
    snapshot = {}; character_name_problem("Moonveil") = None.
[1] fake providers
    non-knower Obs sees "Moonveil"; knower Kim "Moonveil (Cara)"; Cara herself
    "Cara"; observer "cara" is Cara (casefold) -> "Cara".
    shown_names(Obs, [Cara, Kim]) = ["Moonveil", "Kim"] (Kim has no persona).
    identity_key = public_label = "Moonveil".
    knows: Obs False, Kim True, Cara True.
    masked_description: Obs -> the description; Kim -> None; Cara -> None;
    Obs about Kim -> None (no persona).
    resolve_name(Obs, "moonveil") = "Cara"; resolve_name(Obs, "Kim") = "Kim";
    resolve_name(Obs, "Nobody") = None.
    rewrite (Obs) "Cara leaves the hall." -> "Moonveil leaves the hall.";
    rewrite (Obs) "Caravan rolls in." unchanged (no word boundary after Cara);
    rewrite (Obs) "cara waves." unchanged (case-sensitive);
    rewrite (Kim) "Cara leaves the hall." -> "Moonveil (Cara) leaves the hall."
    (single pass: the inserted label is not rewritten again);
    rewrite (Cara) unchanged (self).
    identity_snapshot([Cara, Kim]) = {"Cara": "Moonveil"}.
    active_persona(Cara) = Persona("Cara", "p1", "Moonveil", <desc>, "").
[2] raising providers
    active raises -> shown "Cara", key "Cara", persona None.
    knows raises (active fine) -> shown "Cara", masked None, knows True,
    key still "Moonveil" (the persona itself is fine).
    names raises -> is_persona_name False.
    junk active answer (a string, or a dict without alias) -> no persona.
[3] reserved-name hook (names provider ["Moonveil", "Starfall"])
    character_name_problem("moonveil").code = "reserved";
    "  Starfall " -> "reserved" (configured, never active — still reserved);
    resolve_name(Obs, "Starfall") = None (not active);
    character_name_problem("Moonbeam") = None.
[4] deletion test: unregister owner "smoke" -> shown_name(Obs, Cara) = "Cara",
    identity_key = "Cara", character_name_problem("Moonveil") = None.
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FAILS = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: {got!r}" + ("" if ok else f" (want {want!r})"))
    if not ok:
        FAILS.append(label)


def main():
    with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as clips:
        os.environ["STORAGE_DIR"] = tmp
        os.environ["INSTANCE_DIR"] = tmp
        os.environ["ANIMATION_CLIPS_DIR"] = clips
        from app.core import paths
        paths.init(tmp)
        paths.init_instance(tmp)
        from app.core.db import init_schema, transaction
        init_schema()
        with transaction() as conn:
            for name in ("Cara", "Kim", "Obs"):
                conn.execute(
                    "INSERT INTO characters (name, template, profile_json, config_json, created_at, updated_at)"
                    " VALUES (?, 'demo', '{}', '{}', '', '')", (name,))

        from app.core import hooks
        from app.core.character_name import character_name_problem
        from app.core.identity_view import (
            PROVIDER_ACTIVE, PROVIDER_KNOWS, PROVIDER_NAMES, Persona, active_persona,
            identity_key, identity_snapshot, is_persona_name, knows, masked_description,
            public_label, resolve_name, rewrite_names, shown_name, shown_names)

        desc = "a masked figure in a dark suit"

        def active(s):
            if s == "Cara":
                return {"persona_id": "p1", "alias": "Moonveil", "description": desc,
                        "portrait_url": ""}
            return None

        def boom(*_a):
            raise RuntimeError("broken package")

        def register_fakes():
            hooks.register_provider(PROVIDER_ACTIVE, active, owner="smoke")
            hooks.register_provider(PROVIDER_KNOWS, lambda o, s: o == "Kim", owner="smoke")
            hooks.register_provider(PROVIDER_NAMES, lambda: ["Moonveil"], owner="smoke")

        print("[0] no provider registered")
        hooks.unregister_owned_providers("smoke")
        for cap in (PROVIDER_ACTIVE, PROVIDER_KNOWS, PROVIDER_NAMES):
            check(f"no provider for {cap}", hooks.get_provider(cap), None)
        check("no provider: shown", shown_name("Obs", "Cara"), "Cara")
        check("no provider: key", identity_key("Cara"), "Cara")
        check("no provider: public label", public_label("Cara"), "Cara")
        check("no provider: resolve alias", resolve_name("Obs", "Moonveil"), None)
        check("no provider: resolve real casefold", resolve_name("Obs", "cara"), "Cara")
        check("no provider: knows", knows("Obs", "Cara"), True)
        check("no provider: masked", masked_description("Obs", "Cara"), None)
        check("no provider: rewrite", rewrite_names("Obs", "Cara leaves.", ["Cara"]), "Cara leaves.")
        check("no provider: persona name", is_persona_name("Moonveil"), False)
        check("no provider: snapshot", identity_snapshot(["Cara", "Kim"]), {})
        check("no provider: not reserved", character_name_problem("Moonveil"), None)

        print("[1] fake providers")
        register_fakes()
        check("non-knower", shown_name("Obs", "Cara"), "Moonveil")
        check("knower", shown_name("Kim", "Cara"), "Moonveil (Cara)")
        check("self", shown_name("Cara", "Cara"), "Cara")
        check("self casefold", shown_name("cara", "Cara"), "Cara")
        check("shown_names", shown_names("Obs", ["Cara", "Kim"]), ["Moonveil", "Kim"])
        check("key", identity_key("Cara"), "Moonveil")
        check("public label", public_label("Cara"), "Moonveil")
        check("key untransformed", identity_key("Kim"), "Kim")
        check("knows non-knower", knows("Obs", "Cara"), False)
        check("knows knower", knows("Kim", "Cara"), True)
        check("knows self", knows("Cara", "Cara"), True)
        check("masked desc non-knower", masked_description("Obs", "Cara"), desc)
        check("masked desc knower", masked_description("Kim", "Cara"), None)
        check("masked desc self", masked_description("Cara", "Cara"), None)
        check("masked desc no persona", masked_description("Obs", "Kim"), None)
        check("resolve alias casefold", resolve_name("Obs", "moonveil"), "Cara")
        check("resolve real", resolve_name("Obs", "Kim"), "Kim")
        check("resolve unknown", resolve_name("Obs", "Nobody"), None)
        check("rewrite", rewrite_names("Obs", "Cara leaves the hall.", ["Cara"]),
              "Moonveil leaves the hall.")
        check("rewrite word boundary", rewrite_names("Obs", "Caravan rolls in.", ["Cara"]),
              "Caravan rolls in.")
        check("rewrite case-sensitive", rewrite_names("Obs", "cara waves.", ["Cara"]), "cara waves.")
        check("rewrite knower", rewrite_names("Kim", "Cara leaves the hall.", ["Cara"]),
              "Moonveil (Cara) leaves the hall.")
        check("rewrite self", rewrite_names("Cara", "Cara leaves the hall.", ["Cara"]),
              "Cara leaves the hall.")
        check("snapshot", identity_snapshot(["Cara", "Kim"]), {"Cara": "Moonveil"})
        check("persona", active_persona("Cara"), Persona("Cara", "p1", "Moonveil", desc, ""))
        check("no persona", active_persona("Kim"), None)

        print("[2] raising providers")
        hooks.register_provider(PROVIDER_ACTIVE, boom, owner="smoke")
        check("provider raises → real name", shown_name("Obs", "Cara"), "Cara")
        check("active raises: key", identity_key("Cara"), "Cara")
        check("active raises: persona", active_persona("Cara"), None)
        hooks.register_provider(PROVIDER_ACTIVE, active, owner="smoke")
        hooks.register_provider(PROVIDER_KNOWS, boom, owner="smoke")
        check("knows raises: shown", shown_name("Obs", "Cara"), "Cara")
        check("knows raises: masked", masked_description("Obs", "Cara"), None)
        check("knows raises: knows", knows("Obs", "Cara"), True)
        check("knows raises: key", identity_key("Cara"), "Moonveil")
        hooks.register_provider(PROVIDER_NAMES, boom, owner="smoke")
        check("names raises", is_persona_name("Moonveil"), False)
        hooks.register_provider(PROVIDER_ACTIVE, lambda s: "Moonveil", owner="smoke")
        check("junk answer (str)", active_persona("Cara"), None)
        hooks.register_provider(PROVIDER_ACTIVE, lambda s: {"persona_id": "p1"}, owner="smoke")
        check("junk answer (no alias)", shown_name("Obs", "Cara"), "Cara")

        print("[3] reserved-name hook")
        register_fakes()
        hooks.register_provider(PROVIDER_NAMES, lambda: ["Moonveil", "Starfall"], owner="smoke")
        err = character_name_problem("moonveil")
        check("alias reserved", err is not None, True)
        check("alias reserved code", getattr(err, "code", None), "reserved")
        check("inactive alias reserved", getattr(character_name_problem("  Starfall "), "code", None),
              "reserved")
        check("inactive alias not resolved", resolve_name("Obs", "Starfall"), None)
        check("other name free", character_name_problem("Moonbeam"), None)

        print("[4] deletion test")
        hooks.unregister_owned_providers("smoke")
        check("removed: shown", shown_name("Obs", "Cara"), "Cara")
        check("removed: key", identity_key("Cara"), "Cara")
        check("removed: not reserved", character_name_problem("Moonveil"), None)

    if FAILS:
        print(f"FAIL: {len(FAILS)} check(s): {', '.join(FAILS)}")
        return 1
    print("PASS smoke_identity_view")
    return 0


if __name__ == "__main__":
    sys.exit(main())
