#!/usr/bin/env python3
"""Ruling A48a: the Mesh row's 3D view of an own-mesh clothing piece — the mesh routes, the inside-the-body
share, its cache and the kept refused mesh attempts (app/core/garment_mesh_view.py, garment_mesh.keep_attempt,
the routes ``/characters/{c}/garments/{item}/mesh/{which}[/body[/{overlay}]]`` in app/routes/characters.py).

Usage:
    ./.venv/bin/python scripts/smoke_garment_mesh_view.py

Runs against a THROWAWAY storage + instance directory with a copy of the repo's ``human`` package — no real
world, no hub, no GPU, no server process; the characters router is mounted on a bare FastAPI app with real
sessions (pattern of smoke_garment_wardrobe_routes.py). Stubs: ``base_body.current_base`` (the base pair below),
``base_body._snapshot_base_model`` (reads the planted body files), ``garment_source.fit_masks`` (the synthetic
masks below — no BiRefNet), ``model_refs.find_ref_image`` (the planted front view), ``garment_assembly.schedule``.

Meshes (``box(lo, hi, n)``: the six faces of an axis-aligned box, each an n × n grid of quads, two triangles
each — all triangles of one face have the same area, so area share = face share wherever a face is split on
grid lines).

[1] ``inside_faces`` — the body is the box [-0.1, 0.1]³ (n 60, edges 3.3 mm), voxel 2 mm:
    a. cube [0.06, 0.14] × [-0.04, 0.04]² (n 4, columns 2 cm wide along x at 0.06 / 0.08 / 0.10 / 0.12 / 0.14):
       half of it lies inside the body's +x face x = 0.1. Inside: the whole −x face (x 0.06) and on each of the
       four side faces the two columns below x 0.1 = 1 + 4 · ½ = 3 of 6 face areas -> share 0.5; the nearest
       centroid lies 2 cm / 3 = 6.7 mm (3.3 voxels) from the surface, so ± 0.02 holds every voxel rounding.
    b. cube [-0.04, 0.04]³ -> 1.0; c. cube [0.2, 0.28] × [-0.04, 0.04]² -> 0.0.
[2] ``placement`` — body box x ±0.15, y 0 .. 1.7, z ±0.1 (n 120: edges ≤ 1.4 cm, dense enough for the body
    field's surface samples in [5]); its mask rows 100 .. 269 (170 px), columns
    120 .. 179: sb = 1.7 / 170 = 0.01 m/px, centre (150, 185) px, bbox centre (0, 0.85, 0). Garment cube [-1, 1]³
    (n 8), its mask rows 150 .. 189 (40 px), columns 130 .. 169: sd = 2 / 40 = 0.05 /px, centre (150, 170) px.
    ``place_by_framing``: x -> (150 + x/0.05 − 150) · 0.01 = 0.2 x; y -> 0.85 − (170 − y/0.05 − 185) · 0.01 =
    1.0 + 0.2 y; z -> 0.2 z. The torso band (0.03 .. 0.15 of 1.7 below the top 1.2) is centred on z 0 on both:
    dz 0. So s = 0.2, t = (0, 1.0, 0) (± 1e-6).
[3] The kept refused attempts (``garment_mesh.keep_attempt`` / ``clear_attempts`` / ``attempt_files``): attempt
    1 of the current fsig F is kept as ``attempts/mesh/dress_F.try1.glb`` + ``.try1.raw.glb`` with the bytes of
    the candidate and the raw; ``garment_store.parse_name`` puts both in the group (dress, F), so
    ``stored_groups`` lists them; ``clear_attempts`` removes both.
[4] Routes (admin session) on the piece ``dress`` (own mesh, worn by Demo) with F's prepared mesh = the garment
    cube of [2] (accepted record, tris_prepared 768 = 6 · 8² · 2), a raw file (other bytes) and refused attempt 1:
    ``mesh/prepared`` -> 200 model/gltf-binary, the prepared bytes, ETag "<content_version>", 304 on it,
    immutable with ``?v=``; ``mesh/raw`` -> the raw bytes; ``mesh/prepared?attempt=1`` -> the attempt's bytes;
    ``?attempt=2`` -> 404; which "nope" -> 400; attempt 7 -> 400; item "..%2Fsecret" and "dress%20x" -> 404.
    The panel (``GET …/garments/dress``): ``steps.mesh.view`` names prepared / raw with their versioned URLs and
    attempt 1 (reasons ["torn"]) with its prepared + raw files. Triangles are COUNTED IN THE FILE, not taken from
    the record: the raw file holds the 768-triangle cube (record tris_raw 900) -> 768; attempt 1's prepared file
    is the n 2 box, 6 · 2² · 2 = 48 (record 50) -> 48.
[5] The body view (``mesh/prepared/body``), body = the box of [2] (unrigged = rigged, k 1, voxel 3.4 mm), the
    masks of [2]: the placed cube spans x ±0.2, y 0.8 .. 1.2, z ±0.2 — its four sides lie outside the body; on
    its top and bottom face (cells 5 cm) the cells with |x| < 0.15 and |z| < 0.1 lie inside: 6 × 4 of 8 × 8 cells
    each -> inside area 2 · 0.375 of 6 faces = 0.125 (face share the same; nearest centroid 5 cm / 3 from the
    body's surface). ``inside_faces`` = 0.125 · 768 = 96. The JSON names ghost_url and inside_url; both answer
    200 model/gltf-binary (the ghost has the body's triangle count, 6 · 120² · 2; the inside overlay 96
    triangles). A second GET (and ``body_view`` again) computes nothing: ``_INFO`` computes 1
    -> 1, hits +2; If-None-Match with the ETag -> 304.
[6] Auth: the player session -> 403 on the mesh, body and overlay routes; with the server's gate
    (``auth_gate_middleware``) an anonymous GET of ``mesh/prepared`` -> 401 and nothing computed.
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


def near(label, got, want, tol):
    ok = got is not None and abs(got - want) <= tol
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r} (want {want} ± {tol})")
    if not ok:
        FAILS.append(label)


def box(lo, hi, n):
    """The six faces of the box [lo, hi], each an n × n quad grid (two triangles per quad), unwelded."""
    import numpy as np
    lo, hi = np.asarray(lo, float), np.asarray(hi, float)
    P, F = [], []
    for axis in range(3):
        u, v = [a for a in range(3) if a != axis]
        for side in (lo[axis], hi[axis]):
            base = sum(len(p) for p in P)
            g = np.linspace(0, 1, n + 1)
            pts = np.zeros(((n + 1) ** 2, 3))
            uu, vv = np.meshgrid(g, g, indexing="ij")
            pts[:, axis] = side
            pts[:, u] = lo[u] + uu.ravel() * (hi[u] - lo[u])
            pts[:, v] = lo[v] + vv.ravel() * (hi[v] - lo[v])
            idx = np.arange((n + 1) ** 2).reshape(n + 1, n + 1) + base
            a, b, c, d = idx[:-1, :-1], idx[1:, :-1], idx[1:, 1:], idx[:-1, 1:]
            F.append(np.stack([a, b, c], -1).reshape(-1, 3))
            F.append(np.stack([a, c, d], -1).reshape(-1, 3))
            P.append(pts)
    return np.concatenate(P), np.concatenate(F)


def masks():
    import numpy as np
    body = np.zeros((400, 300), bool)
    body[100:270, 120:180] = True
    garment = np.zeros((400, 300), bool)
    garment[150:190, 130:170] = True
    return body, garment


def main() -> int:
    import numpy as np
    with tempfile.TemporaryDirectory(prefix="garment-mesh-view-") as tmp:
        root = Path(tmp)
        os.environ["STORAGE_DIR"] = str(root / "world")
        os.environ["INSTANCE_DIR"] = str(root / "instance")
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "instance")
        paths.get_config_path().write_text(json.dumps({"packages": {"enabled": "human"}}))
        from app.core import config
        config.load(paths.get_config_path(), instance_path=root / "instance/config.json")
        from app.core import db
        db.init_schema()
        plugins = root / "plugins"
        shutil.copytree(ROOT / "plugins" / "human", plugins / "human")
        from app.plugins.loader import discover_packages
        discover_packages(plugins, force=True)

        from app.core import (auth_dependency, base_body, garment_assembly, garment_mesh, garment_mesh_view,
                              garment_source, model_refs, sessions, users)
        from app.core import garment_store as gs
        from app.core.glb_mesh import static_arrays, static_glb
        from app.core.http_files import content_version
        from app.models import inventory
        from app.models.character import get_character_dir, save_character_profile

        print("[1] inside_faces: a cube half inside a box body")
        BP, BF = box([-0.1] * 3, [0.1] * 3, 60)
        for label, lo, hi, want in (("half inside", [0.06, -0.04, -0.04], [0.14, 0.04, 0.04], 0.5),
                                    ("all inside", [-0.04] * 3, [0.04] * 3, 1.0),
                                    ("all outside", [0.2, -0.04, -0.04], [0.28, 0.04, 0.04], 0.0)):
            P, F = box(lo, hi, 4)
            mask, share, face_share = garment_mesh_view.inside_faces(P, F, BP, BF, vox=0.002)
            near(f"{label}: area share", share, want, 0.02)
            near(f"{label}: face share", face_share, want, 0.02)
            check(f"{label}: one flag per face", mask.shape, (len(F),))

        print("[2] placement: the fit's framing as a scale and an offset")
        body_P, body_F = box([-0.15, 0.0, -0.1], [0.15, 1.7, 0.1], 120)
        garment_P, garment_F = box([-1.0] * 3, [1.0] * 3, 8)
        body_mask, garment_mask = masks()
        s, t = garment_mesh_view.placement(garment_P, garment_F, body_P, {"body": body_mask, "garment": garment_mask})
        near("s", s, 0.2, 1e-6)
        near("t.x", float(t[0]), 0.0, 1e-6)
        near("t.y", float(t[1]), 1.0, 1e-6)
        near("t.z", float(t[2]), 0.0, 1e-6)

        # --- fixture -----------------------------------------------------------------------------------------
        garment_assembly.schedule = lambda name, signature=None: True
        model_refs.schedule_outfit_render = lambda *a, **k: None
        human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
                 "character_appearance": "slender",
                 "body_slots": {"skin": {"tone": "light"}, "eyes": {"color": "blue"},
                                "build": {"type": "athletic"}, "hair": {"length": "medium", "color": "blonde"}}}
        check("create Demo", save_character_profile("Demo", json.loads(json.dumps(human)), create_new=True), True)
        op = {"slots": ["top", "bottom"], "outfit_types": ["casual"], "mesh_mode": "own_mesh", "covers": []}
        dress = inventory.add_item(name="Dress", category="outfit_piece", item_id="dress",
                                   prompt_fragment="a plain dress", outfit_piece=op)["id"]
        check("give dress", inventory.add_to_inventory("Demo", dress), True)
        check("equip dress", inventory.equip_piece("Demo", dress, source="smoke")["status"], "ok")
        bsig = base_body.base_signature("Demo")
        model_dir = get_character_dir("Demo") / "model3d"
        (model_dir / "unrigged").mkdir(parents=True, exist_ok=True)
        body_glb = static_glb(body_P, body_F, np.zeros((len(body_P), 2)))
        (model_dir / f"{bsig}.glb").write_bytes(body_glb)
        (model_dir / "unrigged" / f"{bsig}.glb").write_bytes(body_glb)
        refs = get_character_dir("Demo") / "model_refs"
        refs.mkdir(parents=True, exist_ok=True)
        front = refs / f"tpose_{bsig}.png"
        front.write_bytes(b"\x89PNG-front")
        base_body.current_base = lambda name, profile=None: (bsig, "body-sha")
        base_body._snapshot_base_model = lambda name, sig: {
            "unrigged": (model_dir / "unrigged" / f"{sig}.glb").read_bytes(),
            "rigged": (model_dir / f"{sig}.glb").read_bytes()}
        MASKS = []

        def fake_masks(name, item_id, fsig, *, body_front, base_front):
            MASKS.append((name, item_id, Path(body_front).name))
            b, g = masks()
            return b, g, {"registered": False}
        garment_source.fit_masks = fake_masks
        real_find = model_refs.find_ref_image
        model_refs.find_ref_image = lambda name, kind, signature=None: (
            front if (kind, signature) == ("tpose", bsig) else real_find(name, kind, signature))

        fsig = gs.garment_fsig("Demo", dress)
        prepared = gs.garment_path("Demo", dress, fsig, "prepared")
        raw = gs.garment_path("Demo", dress, fsig, "raw")
        prepared.parent.mkdir(parents=True, exist_ok=True)
        raw.parent.mkdir(parents=True, exist_ok=True)
        prepared_bytes = static_glb(garment_P, garment_F, np.zeros((len(garment_P), 2)))
        prepared.write_bytes(prepared_bytes)
        raw.write_bytes(prepared_bytes + b"RAW-TAIL")
        check("prepared triangles", len(static_arrays(prepared_bytes)[1]), 768)
        attempt_glb = static_glb(*box([-1.0] * 3, [1.0] * 3, 2), np.zeros((6 * 9, 2)))
        candidate = root / "candidate.glb"
        candidate.write_bytes(attempt_glb)
        raw_try = root / "raw_try.glb"
        raw_try.write_bytes(attempt_glb + b"RAW-TRY")
        ghost = gs.garment_path("Demo", dress, fsig, "image", step="ghost", view="front")
        ghost.parent.mkdir(parents=True, exist_ok=True)
        ghost.write_bytes(b"\x89PNG-ghost")
        record = {"accepted": True, "kind": "clothing", "item_id": dress, "fsig": fsig, "tris_raw": 900,
                  "tris_prepared": 768, "largest_component_share": 1.0, "created_at": "2026-11-14T12:00:00+00:00",
                  "attempts": [{"attempt": 1, "ok": False, "reasons": ["torn"], "tris_raw": 120,
                                "tris_prepared": 50, "largest_component_share": 0.5},
                               {"attempt": 2, "ok": True, "reasons": [], "tris_raw": 900, "tris_prepared": 768,
                                "largest_component_share": 1.0}]}
        gs.write_record(prepared.with_suffix(".json"), record)

        print("[3] kept refused attempts")
        garment_mesh.keep_attempt("Demo", dress, fsig, 1, candidate, raw_try)
        kept = garment_mesh.attempt_files("Demo", dress, fsig, 1)
        check("attempt files", (kept["prepared"].name if kept["prepared"] else None,
                                kept["raw"].name if kept["raw"] else None),
              (f"dress_{fsig}.try1.glb", f"dress_{fsig}.try1.raw.glb"))
        check("attempt bytes", (kept["prepared"].read_bytes() == attempt_glb,
                                kept["raw"].read_bytes() == attempt_glb + b"RAW-TRY"), (True, True))
        group = gs.stored_groups("Demo").get((dress, fsig)) or []
        check("in the group", sorted(p.name for p in group if p.parent.name == "mesh"),
              [f"dress_{fsig}.try1.glb", f"dress_{fsig}.try1.raw.glb"])
        garment_mesh.clear_attempts("Demo", dress, fsig)
        check("cleared", garment_mesh.attempt_files("Demo", dress, fsig, 1), {"prepared": None, "raw": None})
        garment_mesh.keep_attempt("Demo", dress, fsig, 1, candidate, raw_try)

        tokens = {}
        for role in (users.ROLE_ADMIN, users.ROLE_USER):
            uid = users.create_user("demo-" + role, "temporary-smoke-password", role, allowed_characters=["Demo"])
            tokens[role] = sessions.create_session(uid)
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.routes.characters import router
        app = FastAPI()
        app.include_router(router)
        base_url = "/characters/Demo/garments/dress/mesh"
        with TestClient(app, raise_server_exceptions=False) as client:
            print("[4] mesh routes (admin)")
            client.cookies.set(sessions.SESSION_COOKIE_NAME, tokens[users.ROLE_ADMIN])
            r = client.get(f"{base_url}/prepared")
            version = content_version(prepared)
            check("prepared 200", (r.status_code, r.headers.get("content-type"), r.content == prepared_bytes,
                                   r.headers.get("etag")),
                  (200, "model/gltf-binary", True, f'"{version}"'))
            check("prepared 304", client.get(f"{base_url}/prepared",
                                             headers={"If-None-Match": f'"{version}"'}).status_code, 304)
            check("immutable with v", client.get(f"{base_url}/prepared?v={version}").headers.get("cache-control"),
                  "public, max-age=31536000, immutable")
            r = client.get(f"{base_url}/raw")
            check("raw 200", (r.status_code, r.content == prepared_bytes + b"RAW-TAIL"), (200, True))
            r = client.get(f"{base_url}/prepared?attempt=1")
            check("attempt 1", (r.status_code, r.content == attempt_glb), (200, True))
            r = client.get(f"{base_url}/raw?attempt=1")
            check("attempt 1 raw", (r.status_code, r.content == attempt_glb + b"RAW-TRY"), (200, True))
            check("attempt 2 absent", client.get(f"{base_url}/prepared?attempt=2").status_code, 404)
            check("which nope", client.get(f"{base_url}/nope").status_code, 400)
            check("attempt 7", client.get(f"{base_url}/prepared?attempt=7").status_code, 400)
            for bad in ("..%2Fsecret", "dress%20x"):
                check(f"item {bad}", client.get(f"/characters/Demo/garments/{bad}/mesh/prepared").status_code, 404)
            panel = client.get("/characters/Demo/garments/dress").json()
            view = (((panel.get("garment") or {}).get("steps") or {}).get("mesh") or {}).get("view") or {}
            check("panel prepared url", (view.get("prepared") or {}).get("url"),
                  f"/characters/Demo/garments/dress/mesh/prepared?v={version}")
            check("panel raw", ((view.get("raw") or {}).get("tris"), (view.get("raw") or {}).get("url", "")
                                .startswith("/characters/Demo/garments/dress/mesh/raw?v=")), (768, True))
            att = (view.get("attempts") or [{}])[0]
            check("panel attempt", (len(view.get("attempts") or []), att.get("attempt"), att.get("reasons"),
                                    (att.get("prepared") or {}).get("tris"),
                                    (att.get("prepared") or {}).get("url", "").endswith("&attempt=1"),
                                    (att.get("raw") or {}).get("body_url")),
                  (1, 1, ["torn"], 48, True, "/characters/Demo/garments/dress/mesh/raw/body?attempt=1"))

            print("[5] body view: share, overlays, cache")
            before = garment_mesh_view.info()
            r = client.get(f"{base_url}/prepared/body")
            body = r.json() if r.status_code == 200 else {}
            check("body 200", r.status_code, 200)
            near("share inside", body.get("share"), 0.125, 0.01)
            near("face share inside", body.get("face_share"), 0.125, 0.01)
            check("faces", (body.get("faces"), body.get("inside_faces")), (768, 96))
            near("placement scale", (body.get("placement") or {}).get("scale"), 0.2, 1e-6)
            check("masks asked once, on the base front", MASKS, [("Demo", "dress", front.name)])
            g = client.get(body.get("ghost_url") or "/none")
            check("ghost overlay", (g.status_code, g.headers.get("content-type"),
                                    len(static_arrays(g.content)[1]) if g.status_code == 200 else None),
                  (200, "model/gltf-binary", len(body_F)))
            ins = client.get(body.get("inside_url") or "/none")
            check("inside overlay", (ins.status_code, len(static_arrays(ins.content)[1])
                                     if ins.status_code == 200 else None), (200, 96))
            r2 = client.get(f"{base_url}/prepared/body")
            again = garment_mesh_view.body_view("Demo", dress, "prepared")
            after = garment_mesh_view.info()
            check("computed once", (after["computes"] - before["computes"], after["hits"] - before["hits"] >= 3),
                  (1, True))
            check("same answer", (r2.json().get("key"), again.get("key")), (body.get("key"), body.get("key")))
            check("masks not asked again", len(MASKS), 1)
            check("body 304", client.get(f"{base_url}/prepared/body",
                                         headers={"If-None-Match": r.headers.get("etag", "")}).status_code, 304)
            check("overlay nope", client.get(f"{base_url}/prepared/body/nope").status_code, 400)

            print("[6] auth")
            client.cookies.set(sessions.SESSION_COOKIE_NAME, tokens[users.ROLE_USER])
            for url in (f"{base_url}/prepared", f"{base_url}/prepared/body", f"{base_url}/prepared/body/ghost"):
                check(f"player {url}", client.get(url).status_code, 403)
        gated = FastAPI()
        gated.middleware("http")(auth_dependency.auth_gate_middleware)
        gated.middleware("http")(auth_dependency.user_context_middleware)
        gated.include_router(router)
        computes = garment_mesh_view.info()["computes"]
        with TestClient(gated, raise_server_exceptions=False) as anon:
            check("anonymous mesh", anon.get(f"{base_url}/prepared", headers={"accept": "*/*"}).status_code, 401)
            check("anonymous body", anon.get(f"{base_url}/raw/body", headers={"accept": "*/*"}).status_code, 401)
        check("anonymous computed nothing", garment_mesh_view.info()["computes"], computes)

    print("\nFAILED: " + ", ".join(FAILS) if FAILS else "\nall checks passed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
