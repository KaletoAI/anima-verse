#!/usr/bin/env python3
"""Exercise Influence CRUD, factors, import safety and privacy in temporary storage.

Usage: ./.venv/bin/python scripts/smoke_influence_rules.py

Hand-derived expectations from the Influence contract:
* JSON false, strings, NaN, 0 and 6 are not finite numeric factors in [.1,5].
  Both endpoints must reject them with 400 without changing the old row.
* Global 1.5 times exact actor/recipient 2 gives 3. Two matching factors 5
  give effective 5, not 25. Different stat/actor, self, unknown actor and
  zero delta give 1. A decreasing-only rule cannot affect a positive delta.
* Recipient signal 20<30 and actor signal 40>30 match. NOT a missing value
  remains unavailable, never true. Pair strength is exact: A/B=80, A/C=0.
* Missing world references survive storage and ZIP but are inactive. Invalid
  overwrite or DB failure leaves the old row and all other layer rows intact.
* Real persisted admin/player sessions see different rule lists: only the
  private Influence type is hidden; its detail/export are 404 for players.

Only the template catalog and shared-rule path are redirected to synthetic
fixtures. CRUD, SQLite, session resolution, strict conditions, ZIP reads/writes
and auth middleware run for real. A SQLite trigger injects persistence failure.
No server startup, real world, shared baseline, provider call or network is used.
"""
import copy
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import zipfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def influence(rule_id="demo-influence", *, actor="demo-actor", recipient="demo-recipient",
              stat="signal", factor=2, direction="increase", **extra):
    rule = {
        "id": rule_id, "name": "Synthetic influence", "type": "influence",
        "condition": "", "actor_condition": "", "pair_conditions": [],
        "influence": {"actor": actor, "recipient": recipient, "stat": stat,
                      "direction": direction, "factor": factor},
    }
    rule.update(extra)
    return rule


def archive(rule, *, manifest_id=None, scope="world"):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps({
            "version": 1, "type": "rule", "scope": scope,
            "rule_id": manifest_id or rule.get("id"),
        }))
        zf.writestr("db/rules.json", json.dumps([rule]))
    return buf.getvalue()


def main():
    with tempfile.TemporaryDirectory(prefix="influence-rules-") as tmp:
        root = Path(tmp)
        os.environ["STORAGE_DIR"] = tmp
        os.environ["INSTANCE_DIR"] = str(root / "instance")
        from app.core import paths
        paths.init(tmp)
        paths.init_instance(root / "instance")
        from app.core import config
        config.load(root / "config.json")
        from app.core.db import get_connection, init_schema, transaction
        init_schema()
        from app.models import character, character_template, relationship, rules
        from app.core import auth_dependency, sessions, users
        from app.routes.rules import router
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        template = {"id": "demo-template", "name": "Synthetic template",
                    "features": {"status_effects_enabled": True},
                    "sections": [{"fields": [
                        {"key": "signal", "label": "Signal", "store": "status_effects"},
                        {"key": "neighbor", "label": "Neighbor", "store": "status_effects"},
                    ]}]}
        shared_path = root / "shared-rules.json"
        shared_path.write_text('{"rules": []}', encoding="utf-8")
        with patch.object(rules, "_get_shared_rules_path", return_value=shared_path), \
             patch.object(character_template, "get_template", return_value=template), \
             patch.object(character_template, "list_templates", return_value=[
                 {"id": "demo-template", "name": "demo-template"}]):
            profiles = {}
            for name, signal in (("demo-actor", 40), ("demo-recipient", 20),
                                 ("demo-other", 50)):
                profile = {"template": "demo-template", "status_effects": {
                    "signal": signal, "neighbor": 50}}
                assert character.save_character_profile(name, profile, create_new=True)
                profiles[name] = character.get_character_profile(name)
            relationship.update_relationship_manual("demo-actor", "demo-recipient", strength=80)
            admin_id = users.create_user("demo", "temporary-password", role="admin")
            player_id = users.create_user("demo-player", "temporary-password", role="user")
            admin_token = sessions.create_session(admin_id)
            player_token = sessions.create_session(player_id)
            app = FastAPI()
            app.include_router(router)
            app.middleware("http")(auth_dependency.auth_gate_middleware)
            app.middleware("http")(auth_dependency.user_context_middleware)
            with TestClient(app, raise_server_exceptions=False) as admin, \
                 TestClient(app, raise_server_exceptions=False) as player:
                admin.cookies.set(sessions.SESSION_COOKIE_NAME, admin_token)
                player.cookies.set(sessions.SESSION_COOKIE_NAME, player_token)

                def post(rule, target="world", want=200):
                    response = admin.post("/rules", json={"rule": rule, "target": target})
                    assert response.status_code == want, (response.status_code, response.text)
                    return response

                def put(rule_id, updates, want=200):
                    response = admin.put(f"/rules/{rule_id}", json={"rule": updates})
                    assert response.status_code == want, (response.status_code, response.text)
                    return response

                def stored(rule_id):
                    response = admin.get(f"/rules/{rule_id}")
                    assert response.status_code == 200, response.text
                    return response.json()["rule"]

                base = influence()
                post(base)
                for bad in (False, "2", 0, 6):
                    candidate = influence(factor=bad)
                    # This is the first intended RED on the pre-feature backend:
                    # old CRUD accepts invalid Influence factors as successful.
                    post(candidate, want=400)
                    assert stored(base["id"])["influence"]["factor"] == 2
                    put(base["id"], {"influence": candidate["influence"]}, want=400)
                    assert stored(base["id"])["influence"]["factor"] == 2
                for value in ("NaN", "Infinity", "-Infinity"):
                    raw = json.dumps({"rule": influence()}).replace('"factor": 2', f'"factor": {value}')
                    response = admin.post("/rules", content=raw, headers={"content-type": "application/json"})
                    assert response.status_code == 400, response.text
                    assert stored(base["id"])["influence"]["factor"] == 2
                for edge in (.1, 5):
                    post(influence(f"demo-edge-{edge}", factor=edge))
                put(base["id"], {"influence": influence(direction="sideways")["influence"]}, want=400)
                for extra in ({"character": "demo-actor"}, {"target": {}},
                              {"modify": {"quantity": "x", "factor": 2}},
                              {"force_action": "wake"}, {"pair_conditions": [{"kind": "unknown"}]},
                              {"pair_conditions": [{"kind": "relationship", "op": ">=", "value": 50}]},
                              {"pair_conditions": [{"kind": "relationship", "op": ">", "value": False}]},
                              {"pair_conditions": [{"kind": "attraction", "observer": "other"}]},
                              {"condition": "true OR unknown_atom"}):
                    post(influence(**extra), want=400)
                put(base["id"], {"influence": influence(actor="demo-other")["influence"]})
                assert stored(base["id"])["influence"]["actor"] == "demo-other"
                put(base["id"], {"name": "Renamed"})
                assert stored(base["id"])["influence"]["actor"] == "demo-other"
                put(base["id"], {"type": "modify", "modify": {"quantity": "x", "factor": 2}})
                changed = stored(base["id"])
                assert changed["type"] == "modify" and "influence" not in changed
                assert "pair_conditions" not in changed and "actor_condition" not in changed
                put(base["id"], {k: v for k, v in base.items() if k != "id"})
                changed = stored(base["id"])
                assert "modify" not in changed and changed["influence"] == base["influence"]
                put(base["id"], {"influence": {"factor": 3}})
                changed = stored(base["id"])
                assert changed["influence"]["actor"] == "demo-actor"
                assert changed["influence"]["recipient"] == "demo-recipient"
                assert changed["influence"]["factor"] == 3
                put(base["id"], {"influence": {"factor": 2}})
                put(base["id"], {"type": "block", "influence": base["influence"]}, want=400)
                print("PASS strict factors, merged PUT, scope retention and subtype transitions")

                options = admin.get("/rules/influence-options")
                assert options.status_code == 200, options.text
                opts = options.json()
                assert {s["key"] for s in opts["stats"]} >= {"signal", "neighbor"}
                assert opts["directions"] == ["increase", "decrease", "both"]
                assert opts["factor_min"] == .1 and opts["factor_max"] == 5
                assert {p["kind"] for p in opts["pair_conditions"]} == {"relationship", "attraction"}
                missing = influence("demo-missing", actor="demo-absent", stat="missing_signal")
                post(missing)
                diag = admin.post("/rules/influence-validate", json={"rule": missing})
                assert diag.status_code == 200, diag.text
                assert diag.json()["errors"] == [] and diag.json()["warnings"]
                assert diag.json()["available"] is False
                assert stored("demo-missing")["influence"] == missing["influence"]
                bad_diag = admin.post("/rules/influence-validate", json={"rule": influence(factor=False)})
                assert bad_diag.status_code == 200 and bad_diag.json()["errors"]
                assert all(set(issue) >= {"path", "code", "message"}
                           for issue in bad_diag.json()["errors"])
                print("PASS authoring options and preserved inactive references")

                from app.core.stat_influence import influence_factor
                def factor(rule_list, *, actor="demo-actor", recipient="demo-recipient",
                           stat="signal", delta=3):
                    return influence_factor(actor, recipient, stat, delta,
                                            rules=rule_list, profiles=profiles)

                assert factor([base])["factor"] == 2
                assert factor([base], stat="neighbor")["factor"] == 1
                assert factor([base], actor="demo-other")["factor"] == 1
                assert factor([base], actor=None)["factor"] == 1
                assert factor([base], actor="demo-recipient")["factor"] == 1
                assert factor([base], delta=0)["factor"] == 1
                assert factor([base], delta=-3)["factor"] == 1
                assert factor([influence(direction="decrease")], delta=-3)["factor"] == 2
                assert factor([influence(direction="both")], delta=-3)["factor"] == 2
                global_rule = influence("demo-global", actor="", recipient="", factor=1.5)
                trace = factor([base, global_rule])
                assert trace["factor"] == 3
                assert [r["id"] for r in trace["rules"]] == ["demo-global", "demo-influence"]
                assert factor([base, base])["factor"] == 2, "duplicate IDs must not multiply twice"
                assert factor([influence("a", factor=5), influence("b", factor=5)])["factor"] == 5
                assert factor([influence("a", factor=.1), influence("b", factor=.1)])["factor"] == .1
                assert factor([missing])["factor"] == 1
                assert factor([influence(condition="signal<30", actor_condition="signal>30")])["factor"] == 2
                assert factor([influence(condition="signal>30")])["factor"] == 1
                assert factor([influence(condition="NOT missing_signal>10")])["factor"] == 1
                pair = influence(pair_conditions=[{"kind": "relationship", "op": ">", "value": 60}])
                assert factor([pair])["factor"] == 2
                assert factor([influence(actor="", recipient="", pair_conditions=pair["pair_conditions"])],
                              recipient="demo-other")["factor"] == 1
                assert factor([influence(pair_conditions=[{"kind": "relationship", "op": "=", "value": 80}])])["factor"] == 2
                assert factor([influence(pair_conditions=[{"kind": "relationship", "op": "<", "value": 80}])])["factor"] == 1
                from app.core import hooks
                owner = "demo-influence-smoke"
                hooks.register_provider("romantic_attraction", lambda observer, subject:
                                        observer == "demo-recipient" and subject == "demo-actor", owner=owner)
                try:
                    attraction = influence(pair_conditions=[{"kind": "attraction", "observer": "recipient"}])
                    assert factor([attraction])["factor"] == 2
                    assert factor([influence(pair_conditions=[{"kind": "attraction", "observer": "actor"}])])["factor"] == 1
                finally:
                    hooks.unregister_owned_providers(owner)
                assert factor([attraction])["factor"] == 1
                print("PASS exact pair/role conditions, dynamic stats, stacking and unavailable conditions")

                from app.core.content_io import export_rule_to_zip, import_rule_from_zip
                imported = influence("demo-roundtrip", condition="signal<30", actor_condition="signal>30",
                                     pair_conditions=[{"kind": "relationship", "op": ">", "value": 60}])
                post(imported)
                packed = export_rule_to_zip(imported["id"])
                assert admin.delete(f'/rules/{imported["id"]}?target=world').status_code == 200
                import_rule_from_zip(packed)
                assert {k: v for k, v in rules.get_rule(imported["id"]).items()
                        if not k.startswith("_")} == imported
                idless = influence("demo-manifest-id")
                del idless["id"]
                result = import_rule_from_zip(archive(idless, manifest_id="demo-manifest-id"))
                assert result["rule_id"] == "demo-manifest-id"
                assert rules.get_rule("demo-manifest-id")["influence"] == idless["influence"]
                missing_zip = export_rule_to_zip("demo-missing")
                assert admin.delete("/rules/demo-missing?target=world").status_code == 200
                import_rule_from_zip(missing_zip)
                assert rules.get_rule("demo-missing")["influence"] == missing["influence"]
                assert admin.post("/rules/influence-validate", json={"rule": rules.get_rule("demo-missing")}).json()["available"] is False
                before = copy.deepcopy(rules.get_rule(imported["id"]))
                invalid = copy.deepcopy(imported)
                invalid["influence"]["factor"] = False
                for payload in (archive(invalid), b"not a ZIP"):
                    response = admin.post("/rules/import?overwrite=true&target=world",
                                          files={"file": ("demo.zip", payload, "application/zip")})
                    assert response.status_code == 400, response.text
                    assert rules.get_rule(imported["id"]) == before
                replacement = {**imported, "name": "Imported replacement"}
                import_rule_from_zip(archive(replacement), overwrite=True)
                assert rules.get_rule(imported["id"])["name"] == "Imported replacement"
                rules.add_rule(influence("demo-shared"), target_dir="shared")
                shared_before = shared_path.read_bytes()
                response = admin.post("/rules/import?overwrite=true&target=world", files={
                    "file": ("demo.zip", archive(influence("demo-shared")), "application/zip")})
                assert response.status_code == 409, response.text
                assert "layer" in response.text.lower()
                assert shared_path.read_bytes() == shared_before
                assert rules.get_rule("demo-shared")["_origin"] == "shared"
                print("PASS ZIP roundtrip, manifest ID, safe overwrite and cross-layer refusal")

                old_layer = copy.deepcopy(rules._load_world_rules())
                try:
                    rules.save_rules([influence("demo-invalid-layer", factor=0)])
                except rules.RuleValidationError:
                    pass
                else:
                    raise AssertionError("full layer save accepted an invalid Influence rule")
                assert rules._load_world_rules() == old_layer
                for writer in (
                    lambda: rules.add_rule(influence("demo-bad-direct", factor=False)),
                    lambda: rules.update_rule(base["id"], {"influence": {"factor": 0}}),
                    lambda: rules.save_rules([influence("demo-bad-shared", factor=6)], target_dir="shared"),
                ):
                    try:
                        writer()
                    except rules.RuleValidationError as error:
                        assert error.errors and error.errors[0]["path"] == "influence.factor"
                    else:
                        raise AssertionError("a model writer bypassed full Influence validation")
                    assert rules._load_world_rules() == old_layer
                    assert shared_path.read_bytes() == shared_before
                # The trigger aborts real SQLite persistence, including any
                # pre-delete in the same transaction. The old rule must remain.
                with transaction() as conn:
                    conn.execute("""CREATE TRIGGER demo_rule_failure BEFORE UPDATE ON rules
                                    BEGIN SELECT RAISE(ABORT, 'injected rule write failure'); END""")
                try:
                    response = admin.put(f'/rules/{imported["id"]}', json={"rule": {"name": "Not saved"}})
                    assert response.status_code == 500, response.text
                    assert rules.get_rule(imported["id"])["name"] == "Imported replacement"
                    response = admin.post("/rules/import?overwrite=true&target=world", files={
                        "file": ("demo.zip", archive({**replacement, "name": "Not imported"}), "application/zip")})
                    assert response.status_code == 500, response.text
                    assert rules.get_rule(imported["id"])["name"] == "Imported replacement"
                finally:
                    with transaction() as conn:
                        conn.execute("DROP TRIGGER demo_rule_failure")
                print("PASS full-layer prevalidation and real persistence failure propagation")

                normal = {"id": "demo-public", "name": "Public block", "type": "block",
                          "condition": "", "character": "", "target": {"action": "enter"}}
                post(normal)
                public_ids = {r["id"] for r in player.get("/rules").json()["rules"]}
                assert "demo-public" in public_ids and base["id"] not in public_ids
                assert player.get("/rules/demo-public").status_code == 200
                assert player.get("/rules/demo-public/export").status_code == 200
                assert player.get(f'/rules/{base["id"]}').status_code == 404
                assert player.get(f'/rules/{base["id"]}/export').status_code == 404
                assert admin.get(f'/rules/{base["id"]}/export').status_code == 200
                assert player.get("/rules/influence-options").status_code == 403
                assert player.post("/rules/influence-validate", json={"rule": base}).status_code == 403
                assert player.post("/rules", json={"rule": base}).status_code == 403
                assert player.put(f'/rules/{base["id"]}', json={"rule": {"name": "Leak"}}).status_code == 403
                assert player.delete(f'/rules/{base["id"]}').status_code == 403
                from app.core import sync_topics
                with patch.object(sync_topics, "notify") as notify:
                    put(base["id"], {"name": "Private rename"})
                    assert not notify.call_args_list, "Influence definition emitted a player signal"
                print("PASS persisted admin/player session privacy and silent private definitions")

                # Review regressions run independently so RED records each
                # behavioral gap instead of stopping after the first failure.
                review_failures = []

                def review_case(label, check):
                    try:
                        check()
                    except AssertionError as error:
                        review_failures.append(f"{label}: {error}")
                        print(f"FAIL review regression: {label}: {error}")
                    else:
                        print(f"PASS review regression: {label}")

                def export_uses_authorized_snapshot():
                    from app.routes import rules as rule_routes
                    race_id = "demo-export-race"
                    public = {**normal, "id": race_id, "name": "Authorized public snapshot"}
                    rules.add_rule(public)
                    original_reader = rule_routes.get_rule

                    def switch_after_authorization_read(rule_id):
                        snapshot = original_reader(rule_id)
                        if rule_id == race_id:
                            # Commit the admin's replacement in the real DB
                            # between the route read and ZIP serialization.
                            private = influence(race_id)
                            private["name"] = "Private race definition"
                            rules.add_rule(private)
                        return snapshot

                    with patch.object(rule_routes, "get_rule", side_effect=switch_after_authorization_read):
                        response = player.get(f"/rules/{race_id}/export")
                    assert rules.get_rule(race_id)["type"] == "influence", "race replacement was not persisted"
                    assert response.status_code == 200, response.text
                    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
                        rows = json.loads(zf.read("db/rules.json"))
                    assert rows == [public], f"authorized public snapshot replaced by ZIP payload {rows!r}"

                def present_invalid_id_is_not_repaired():
                    original = influence("demo-invalid-id-target")
                    original["name"] = "Original retained rule"
                    rules.add_rule(original)
                    results = []
                    for invalid_id in (False, 0, None, ""):
                        candidate = influence()
                        candidate["id"] = invalid_id
                        candidate["name"] = "Invalid overwrite"
                        response = admin.post("/rules/import?overwrite=true&target=world", files={
                            "file": ("demo.zip", archive(candidate, manifest_id=original["id"]), "application/zip")})
                        current = rules.get_rule(original["id"])
                        results.append((invalid_id, response.status_code, current["name"]))
                        # Isolate each overwrite attempt without masking its result.
                        rules.add_rule(original)
                    assert all(status == 400 and name == "Original retained rule"
                               for _, status, name in results), f"invalid present IDs bypassed validation: {results!r}"

                def strict_rule_reads_cannot_reveal_shared_fallback():
                    import sqlite3
                    rule_id = "demo-read-overlay"
                    rules.add_rule(influence(rule_id, factor=5), target_dir="shared")
                    rules.add_rule(influence(rule_id, factor=1), target_dir="world")
                    loaded = [rule for rule in rules.load_rules() if rule["id"] == rule_id]
                    assert factor(loaded)["factor"] == 1, "world override fixture is not effective"
                    connection = get_connection()

                    class FailingRuleRead:
                        def execute(self, query, *args):
                            if "FROM rules" in query:
                                raise sqlite3.OperationalError("injected world rule read failure")
                            return connection.execute(query, *args)

                    with patch.object(rules, "get_connection", return_value=FailingRuleRead()):
                        # Legacy consumers deliberately retain their prior fallback.
                        legacy = [rule for rule in rules.load_rules() if rule["id"] == rule_id]
                        assert factor(legacy)["factor"] == 5
                        try:
                            rules.load_rules(strict=True)
                        except rules.RuleWriteError:
                            return
                        except TypeError as error:
                            raise AssertionError("load_rules has no error-transparent strict snapshot path") from error
                        raise AssertionError("strict read failure returned an incomplete factor-5 ruleset")

                def strict_shape_errors_are_not_empty_layers():
                    shared_bytes = shared_path.read_bytes()
                    try:
                        for bad_source in ([], {"rules": {}}, {"rules": [[]]}):
                            shared_path.write_text(json.dumps(bad_source), encoding="utf-8")
                            try:
                                rules.load_rules(strict=True)
                            except rules.RuleWriteError:
                                pass
                            else:
                                raise AssertionError(f"strict shared read accepted invalid shape: {bad_source!r}")
                    finally:
                        shared_path.write_bytes(shared_bytes)
                    saved_meta = get_connection().execute(
                        "SELECT meta FROM rules WHERE id=?", (base["id"],)).fetchone()[0]
                    try:
                        for bad_meta in ("not JSON", "[]", '{"id": false}'):
                            with transaction() as conn:
                                conn.execute("UPDATE rules SET meta=? WHERE id=?", (bad_meta, base["id"]))
                            try:
                                rules.load_rules(strict=True)
                            except rules.RuleWriteError:
                                pass
                            else:
                                raise AssertionError(f"strict world read accepted invalid metadata: {bad_meta!r}")
                    finally:
                        with transaction() as conn:
                            conn.execute("UPDATE rules SET meta=? WHERE id=?", (saved_meta, base["id"]))

                def diagnostic_profile_errors_are_unavailable():
                    import sqlite3
                    original_profile_reader = character.get_character_profile

                    def fail_recipient(name, **kwargs):
                        if name == "demo-recipient":
                            raise sqlite3.OperationalError("injected diagnostic profile read failure")
                        return original_profile_reader(name, **kwargs)

                    with patch.object(character, "get_character_profile", side_effect=fail_recipient):
                        response = admin.post("/rules/influence-validate", json={"rule": base})
                    assert response.status_code == 200, response.text
                    assert response.json()["available"] is False
                    assert any(issue["code"] == "read_error" for issue in response.json()["warnings"])

                def missing_persisted_relationship_strength_is_not_ten():
                    row = get_connection().execute(
                        "SELECT id, content, meta FROM relationships "
                        "WHERE (from_char=? AND to_char=?) OR (from_char=? AND to_char=?) "
                        "ORDER BY id DESC LIMIT 1",
                        ("demo-actor", "demo-recipient", "demo-recipient", "demo-actor")).fetchone()
                    assert row is not None, "exact-pair fixture is missing"
                    pair_rule = influence(pair_conditions=[{"kind": "relationship", "op": ">", "value": 5}])
                    assert factor([pair_rule])["factor"] == 2, "stored strength 80 must match >5"
                    content, meta = json.loads(row["content"]), json.loads(row["meta"])
                    content.pop("strength", None)
                    meta.pop("strength", None)
                    try:
                        with transaction() as conn:
                            conn.execute("UPDATE relationships SET content=?, meta=? WHERE id=?",
                                         (json.dumps(content), json.dumps(meta), row["id"]))
                        assert relationship.get_relationship("demo-actor", "demo-recipient")["strength"] == 10, \
                            "legacy reader must keep its historical default"
                        assert factor([pair_rule])["factor"] == 1, \
                            "missing persisted strength fabricated a >5 match from the legacy default 10"
                    finally:
                        with transaction() as conn:
                            conn.execute("UPDATE relationships SET content=?, meta=? WHERE id=?",
                                         (row["content"], row["meta"], row["id"]))
                    no_row = influence(recipient="demo-other", pair_conditions=[
                        {"kind": "relationship", "op": "<", "value": 1}])
                    assert factor([no_row], recipient="demo-other")["factor"] == 2, \
                        "a genuinely absent pair still has strength zero"

                def wildcard_diagnostic_handles_corrupt_profile():
                    saved = get_connection().execute(
                        "SELECT profile_json FROM characters WHERE name=?", ("demo-recipient",)).fetchone()[0]
                    draft = influence(recipient="", stat="missing_signal")
                    try:
                        with transaction() as conn:
                            conn.execute("UPDATE characters SET profile_json=? WHERE name=?",
                                         ("malformed profile JSON", "demo-recipient"))
                        response = admin.post("/rules/influence-validate", json={"rule": draft})
                        assert response.status_code == 200, \
                            f"wildcard missing-stat diagnostic escaped as HTTP {response.status_code}: {response.text}"
                        result = response.json()
                        assert not result["errors"] and result["available"] is False
                        assert any(issue["code"] == "read_error" for issue in result["warnings"]), result
                    finally:
                        with transaction() as conn:
                            conn.execute("UPDATE characters SET profile_json=? WHERE name=?",
                                         (saved, "demo-recipient"))

                def missing_persisted_romantic_value_is_unavailable():
                    from app.core.activity_engine import evaluate_condition_strict
                    row = get_connection().execute(
                        "SELECT id, content, meta FROM relationships "
                        "WHERE (from_char=? AND to_char=?) OR (from_char=? AND to_char=?) "
                        "ORDER BY id DESC LIMIT 1",
                        ("demo-actor", "demo-recipient", "demo-recipient", "demo-actor")).fetchone()
                    assert row is not None
                    content, meta = json.loads(row["content"]), json.loads(row["meta"])
                    content.pop("romantic_tension", None)
                    meta.pop("romantic_tension", None)
                    try:
                        with transaction() as conn:
                            conn.execute("UPDATE relationships SET content=?, meta=? WHERE id=?",
                                         (json.dumps(content), json.dumps(meta), row["id"]))
                        assert relationship.get_relationship("demo-actor", "demo-recipient")["romantic_tension"] == 0
                        result = evaluate_condition_strict("romantic:demo-recipient<1", "demo-actor",
                                                           profile=profiles["demo-actor"])
                        assert not result.available and not result.passed, \
                            f"missing romantic metric became a fabricated zero match: {result}"
                    finally:
                        with transaction() as conn:
                            conn.execute("UPDATE relationships SET content=?, meta=? WHERE id=?",
                                         (row["content"], row["meta"], row["id"]))

                review_case("export authorization and serialization share one snapshot", export_uses_authorized_snapshot)
                review_case("present invalid ZIP IDs cannot select a manifest overwrite target", present_invalid_id_is_not_repaired)
                review_case("strict rule snapshot rejects missing world overlay", strict_rule_reads_cannot_reveal_shared_fallback)
                review_case("strict snapshots reject actual layer JSON/shape corruption", strict_shape_errors_are_not_empty_layers)
                review_case("diagnostics do not hide failed strict profile reads", diagnostic_profile_errors_are_unavailable)
                review_case("missing persisted pair strength cannot fabricate a match", missing_persisted_relationship_strength_is_not_ten)
                review_case("wildcard diagnostics retain malformed-profile warnings", wildcard_diagnostic_handles_corrupt_profile)
                review_case("missing persisted romantic numeric value remains unavailable", missing_persisted_romantic_value_is_unavailable)
                assert not review_failures, "\n".join(review_failures)
            assert get_connection().execute("SELECT COUNT(*) FROM rules").fetchone()[0] > 0
    print("All Influence rules checks passed.")


if __name__ == "__main__":
    main()
