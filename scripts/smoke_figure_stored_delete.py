#!/usr/bin/env python3
"""The Figure tab's Delete of a stored body shape (Ruling A64): a shape kept only by its history is deletable, the
shape the figure stands on is refused with its reason, the confirmation lists what goes, nothing outside the
character folder is touched, and only an admin may do it.

Usage:
    ./.venv/bin/python scripts/smoke_figure_stored_delete.py

Throwaway STORAGE_DIR / INSTANCE_DIR (no real world, no server, no hub). The routes run through the real router
behind the real auth gate; the session lookup reads the role from a header (as in smoke_auth_gate.py).

Fixture — character Kai with three stored body shapes, the files real, the artefact graph's VERDICTS fixed
(``artefact_graph.analyse`` wraps the real ``scan`` and sets reachable/reason per key) and the worn figure fixed
(``figure._delivered``: wanted = delivered shape OBC):
- OBH ``ob0000000a``: verdict reachable, "named by a live outfit model" — the outfit model ``aaaaaaaaaaaa``
  (model3d/aaaaaaaaaaaa.glb + .json naming body_id OBH, low/aaaaaaaaaaaa.glb) was once built on it; no outfit would
  be built on it now. Its files: model3d/OBH.glb, OBH.json, prerig/OBH.glb, model_refs/tpose_OBH.png + .json and
  the body fit garments/bodies/OBH/shirt_kai_f00000000003.glb + .json — 7 files of the body + 3 of the model.
- OBC ``ob0000000b``: verdict "shape of a live outfit", and the figure stands on it (current).
- OBN ``ob0000000c``: verdict "shape of a live outfit", not current.
Every fixture file holds 4096 bytes.

Expected, derived by hand (``figure.stored`` / ``delete_preview`` / ``delete_stored``, Ruling A64):
[1] stored: OBH deletable, refusal "", history True; OBC refusal "current" (not deletable); OBN refusal "needed".
    The worn figure unresolvable (``_delivered`` raises) → OBH NOT deletable (refusal "needed"): only the
    graph's verdict decides then, and it is reachable.
[2] GET …/figure/stored/OBH/preview (admin) → 200: deletable, history, outfit_models = [label of aaaaaaaaaaaa],
    files = the 10 paths above relative to the character folder (sorted), bytes = 10 × 4096 = 40960.
    Every listed path resolves inside the character folder.
[3] GET …/OBC/preview → deletable False, refusal "current"; DELETE …/OBC → 409 with ``figure.SHAPE_CURRENT``;
    DELETE …/OBN → 409 with ``figure.SHAPE_NEEDED``; nothing changed on disk.
[4] Traversal: DELETE and GET preview of ``..``-shaped keys (``ob..%2F..``, ``..%2Fmodel3d``, ``%2e%2e``,
    ``ob0000000a%2F..``) → 400 or 404, a key not shaped like a body ("model3d") → 400; the character tree is
    byte-identical afterwards, and a file one level above the character folder is untouched.
[5] Auth: a player session (role user, Kai allowed) → 403 on the preview GET and on DELETE; anonymous → 401;
    nothing changed.
[6] DELETE …/OBH (admin) → 200: the 10 files are gone, OBC's and OBN's files are all still there.
"""
import json
import os
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("ok   " if ok else "FAIL ") + f"{label}: {got!r}" + ("" if ok else f" (want {want!r})"))
    if not ok:
        FAILS.append(label)


def write(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * 4096)
    return path


def tree(root: Path):
    return sorted((p.relative_to(root).as_posix(), p.stat().st_size) for p in root.rglob("*") if p.is_file())


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="a64-stored-") as tmp:
        base = Path(tmp)
        os.environ["STORAGE_DIR"] = str(base / "world")
        os.environ["INSTANCE_DIR"] = str(base / "instance")
        os.environ["ANIMATION_CLIPS_DIR"] = str(base / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(base / "reference.fbx")
        from app.core import paths
        paths.init(base / "world")
        paths.init_instance(base / "instance")
        paths.get_config_path().write_text(json.dumps({}))
        from app.core import config
        config.load(paths.get_config_path(), instance_path=base / "instance" / "config.json")
        from app.core import db
        db.init_schema()
        from app.core import artefact_graph, figure, figure_build
        from app.models.character import get_character_dir, save_character_profile
        figure_build.request = lambda *a, **k: False
        check("create Kai", save_character_profile("Kai", {"template": "human-roleplay", "gender": "male", "age": 30},
                                                   create_new=True), True)
        char = get_character_dir("Kai")
        M, R, G = char / "model3d", char / "model_refs", char / "garments"
        OBH, OBC, OBN, SIG = "ob0000000a", "ob0000000b", "ob0000000c", "aaaaaaaaaaaa"
        files = {}
        for body, built_for in ((OBH, SIG), (OBC, "bbbbbbbbbbbb"), (OBN, "cccccccccccc")):
            rec = json.dumps({"outfit_body": {"body_id": body, "shape_key": body, "built_for": built_for}})
            files[body] = [write(M / f"{body}.glb"), write(M / "prerig" / f"{body}.glb"), write(R / f"tpose_{body}.png"),
                           write(G / "bodies" / body / "shirt_kai_f00000000003.glb"),
                           write(G / "bodies" / body / "shirt_kai_f00000000003.json")]
            for p in (M / f"{body}.json", R / f"tpose_{body}.json"):
                p.write_text(rec + " " * (4096 - len(rec)))
                files[body].append(p)
        model = [write(M / f"{SIG}.glb"), write(M / "low" / f"{SIG}.glb"), M / f"{SIG}.json"]
        meta = json.dumps({"body_id": OBH, "pieces": {}, "items": []})
        model[2].write_text(meta + " " * (4096 - len(meta)))
        outside = write(char.parent / "outside.txt")

        verdicts = {OBH: (True, "named by a live outfit model"), OBC: (True, "shape of a live outfit"),
                    OBN: (True, "shape of a live outfit")}
        real_scan = artefact_graph.scan

        def analyse(character_name, **_kw):
            nodes, _unknown = real_scan(character_name)
            for node in nodes:
                if node.kind == "body" and node.key in verdicts:
                    node.reachable, node.reason = verdicts[node.key]
                    record = artefact_graph._body_record(char, node.key)
                    node.parents = {k: record.get(k) for k in ("body_id", "shape_key", "built_for")}
                elif node.kind == "outfit":
                    node.reachable, node.reason = True, "producible outfit"
                elif node.kind == "body_fit":
                    node.reachable, node.reason = True, "fit of a kept garment on a live body"
            return types.SimpleNamespace(nodes=nodes)
        artefact_graph.analyse = analyse
        current = types.SimpleNamespace(shape=OBC, texture="")
        figure._delivered = lambda name, **kw: (current, current)

        # [1]
        listed = {e["key"]: e for e in figure.stored("Kai") if e["kind"] == "shape"}
        check("[1] OBH deletable/refusal/history", (listed[OBH]["deletable"], listed[OBH]["refusal"],
                                                   listed[OBH]["history"]), (True, "", True))
        check("[1] OBC refusal", (listed[OBC]["deletable"], listed[OBC]["refusal"]), (False, "current"))
        check("[1] OBN refusal", (listed[OBN]["deletable"], listed[OBN]["refusal"]), (False, "needed"))

        def broken(name, **kw):
            raise RuntimeError("profile unreadable")
        figure._delivered = broken
        listed_b = {e["key"]: e for e in figure.stored("Kai") if e["kind"] == "shape"}
        check("[1] worn figure unknown → OBH kept", (listed_b[OBH]["deletable"], listed_b[OBH]["refusal"]),
              (False, "needed"))
        figure._delivered = lambda name, **kw: (current, current)

        from fastapi import FastAPI, Request
        from fastapi.testclient import TestClient
        from app.core import auth_dependency
        from app.routes import figure as figure_route
        users = {"user": {"id": "u_user", "username": "demo", "role": "user", "allowed_characters": ["Kai"]},
                 "admin": {"id": "u_admin", "username": "demo", "role": "admin", "allowed_characters": []}}

        def session_user(request: Request):
            return users.get(request.headers.get("x-test-user", ""))
        auth_dependency._get_session_user = session_user
        app = FastAPI()
        app.middleware("http")(auth_dependency.auth_gate_middleware)
        app.middleware("http")(auth_dependency.user_context_middleware)
        app.include_router(figure_route.router)
        client = TestClient(app)
        admin = {"x-test-user": "admin"}

        # [2]
        r = client.get(f"/characters/Kai/figure/stored/{OBH}/preview", headers=admin)
        check("[2] preview status", r.status_code, 200)
        p = r.json() if r.status_code == 200 else {}
        want_files = sorted(f.relative_to(char).as_posix() for f in files[OBH] + model)
        check("[2] preview files", p.get("files"), want_files)
        check("[2] preview bytes", p.get("bytes"), 10 * 4096)
        check("[2] preview deletable/history", (p.get("deletable"), p.get("history")), (True, True))
        check("[2] outfit models deleted with it", len(p.get("outfit_models") or []), 1)
        check("[2] every path inside the character folder",
              all((char / f).resolve().is_relative_to(char.resolve()) for f in p.get("files") or []), True)

        before = tree(base)
        # [3]
        r = client.get(f"/characters/Kai/figure/stored/{OBC}/preview", headers=admin)
        check("[3] OBC preview", (r.status_code, r.json().get("deletable"), r.json().get("refusal")),
              (200, False, "current"))
        r = client.delete(f"/characters/Kai/figure/stored/{OBC}", headers=admin)
        check("[3] DELETE OBC", (r.status_code, r.json().get("detail")), (409, figure.SHAPE_CURRENT))
        r = client.delete(f"/characters/Kai/figure/stored/{OBN}", headers=admin)
        check("[3] DELETE OBN", (r.status_code, r.json().get("detail")), (409, figure.SHAPE_NEEDED))
        check("[3] nothing changed", tree(base) == before, True)

        # [4]
        for key in ("ob..%2F..", "..%2Fmodel3d", "%2e%2e", f"{OBH}%2F..", "model3d"):
            for method, path in (("DELETE", f"/characters/Kai/figure/stored/{key}"),
                                 ("GET", f"/characters/Kai/figure/stored/{key}/preview")):
                code = client.request(method, path, headers=admin).status_code
                check(f"[4] {method} {key}", code in (400, 404), True)
        check("[4] model3d-shaped key → 400",
              client.delete("/characters/Kai/figure/stored/model3d", headers=admin).status_code, 400)
        check("[4] nothing changed, outside file intact", (tree(base) == before, outside.read_bytes() == b"x" * 4096),
              (True, True))

        # [5]
        for method, path in (("GET", f"/characters/Kai/figure/stored/{OBH}/preview"),
                             ("DELETE", f"/characters/Kai/figure/stored/{OBH}")):
            check(f"[5] player {method}", client.request(method, path, headers={"x-test-user": "user"}).status_code,
                  403)
            check(f"[5] anonymous {method}", client.request(method, path).status_code, 401)
        check("[5] nothing changed", tree(base) == before, True)

        # [6]
        r = client.delete(f"/characters/Kai/figure/stored/{OBH}", headers=admin)
        check("[6] DELETE OBH", r.status_code, 200)
        check("[6] OBH and its outfit model gone", [f.relative_to(char).as_posix() for f in files[OBH] + model
                                                   if f.exists()], [])
        check("[6] OBC and OBN kept", all(f.exists() for f in files[OBC] + files[OBN]), True)
        check("[6] outside file intact", outside.read_bytes() == b"x" * 4096, True)
    print("ALL OK" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
