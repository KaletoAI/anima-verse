#!/usr/bin/env python3
"""Smoke: native-client releases are signed, and only the signed bytes verify (review 14#1).

Usage:  ./.venv/bin/python scripts/smoke_update_signing.py

Runs without the server and without a world: a throwaway key and a throwaway
``static/native/`` live in temp dirs; ``openssl`` (the CLI, as the publisher uses
it) does every signature check.

THE CANONICAL BYTES — the one serialisation both sides sign/verify
------------------------------------------------------------------

``native/tools/publish_appimage.py::canonical_manifest`` and
``native/Core/Update/UpdateSignature.cs::Canonical`` build, as UTF-8 with LF line
ends and a final LF::

    anima-native-update-v1
    version=<version>
    file=<file>
    size=<size as plain decimal>
    sha256=<sha256 in lowercase hex>

``built_utc`` is NOT signed (informational only). Worked example, counted by hand:

    version = "20261029090000-1234abcd"                       (14 + 1 + 8 = 23 chars)
    file    = "AnimaNative-20261029090000-1234abcd-x86_64.AppImage"
                                                              (12 + 23 + 16 = 51 chars)
    size    = 16
    sha256  = "3A2F0E5C6D1B4A7988C0D2E4F6A8B0C1D3E5F7091B2D4F6081A3C5E7092B4D6F"  (uppercase in, 64)

    line 1  "anima-native-update-v1" + LF      22 + 1 = 23
    line 2  "version=" + version + LF           8 + 23 + 1 = 32
    line 3  "file=" + file + LF                 5 + 51 + 1 = 57
    line 4  "size=16" + LF                      7 + 1 = 8
    line 5  "sha256=" + lowercase sha + LF      7 + 64 + 1 = 72
    total                                       192 bytes

so the bytes are exactly (the sha lowercased)::

    b"anima-native-update-v1\\nversion=20261029090000-1234abcd\\n"
    b"file=AnimaNative-20261029090000-1234abcd-x86_64.AppImage\\nsize=16\\n"
    b"sha256=3a2f0e5c6d1b4a7988c0d2e4f6a8b0c1d3e5f7091b2d4f6081a3c5e7092b4d6f\\n"

The C# side cannot be compiled here; part B reads its string literals in order and
expects exactly ``"anima-native-update-v1\\n", "version=", "\\n", "file=", "\\n",
"size=", "\\n", "sha256=", "\\n"`` (the xUnit test ``CanonicalBytesMatchThePublisher``
pins the same example when the tests are run with dotnet).

WHAT IS CHECKED, and the expected values
-----------------------------------------

A) ``canonical_manifest`` == the 192 bytes above.
B) UpdateSignature.cs: the literal order above; ``PublicKeySpki`` is either ""
   (no key baked: the client fails closed) or a base64 P-256 SPKI — 91 bytes =
   the 26-byte header ``3059301306072a8648ce3d020106082a8648ce3d030107034200``
   (SEQUENCE, id-ecPublicKey, prime256v1, BIT STRING) + 0x04 + 64 bytes of point.
C) ``make_update_signing_key.make_key``: the key file has mode 0600, the returned
   SPKI has that same 91-byte shape, a second call on the same path and a path
   inside the repository are refused.
D) Publishing a 16-byte image ("appimage payload": 8 + 1 + 7) WITH the key writes
   ``version.json`` and ``version.json.sig`` (both 0644); the signature is DER
   (first byte 0x30, at most 72 bytes for P-256) and ``openssl dgst -sha256
   -verify`` accepts it over ``canonical_manifest`` of the published fields
   (size 16, sha256 = hashlib's of the 16 bytes).
E) Changing ANY single byte of those canonical bytes (every position, +1 mod 256)
   makes ``openssl dgst -verify`` fail; so does a manifest whose ``sha256`` differs
   in its first hex digit. Changing only ``built_utc`` keeps it valid (not signed).
F) Without a key nothing is published: the CLI without ``--signing-key`` exits 2
   and ``publish(..., signing_key=None)`` raises; a P-384 key and a PUBLIC key file
   are refused as signing keys. In every case the destination holds no
   ``version.json``/``version.json.sig``.
G) The server hands the signature out exactly like the manifest: the real
   ``auth_gate_middleware`` in front of a ``StaticFiles`` mount at ``/static`` (as
   ``app/server.py`` mounts it) answers an ANONYMOUS ``GET
   /static/native/version.json.sig`` with 200 and the published bytes; a gated
   route still answers 401 (the gate is really in front).

Fails on the old code: ``publish(image, version, destination)`` took no key and
wrote no ``version.json.sig`` (D finds no file, F finds an unsigned release
published), and ``canonical_manifest``/``make_update_signing_key`` did not exist.
"""
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TOOLS = ROOT / "native" / "tools"
FAILS = []


def check(label, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + label + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        FAILS.append(label)


def load(name):
    spec = importlib.util.spec_from_file_location(name, TOOLS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


publisher = load("publish_appimage")
keymaker = load("make_update_signing_key")

# ---- A) canonical bytes ------------------------------------------------------
EXAMPLE = (b"anima-native-update-v1\nversion=20261029090000-1234abcd\n"
           b"file=AnimaNative-20261029090000-1234abcd-x86_64.AppImage\nsize=16\n"
           b"sha256=3a2f0e5c6d1b4a7988c0d2e4f6a8b0c1d3e5f7091b2d4f6081a3c5e7092b4d6f\n")
canonical = publisher.canonical_manifest(
    "20261029090000-1234abcd", "AnimaNative-20261029090000-1234abcd-x86_64.AppImage", 16,
    "3A2F0E5C6D1B4A7988C0D2E4F6A8B0C1D3E5F7091B2D4F6081A3C5E7092B4D6F")
check("A canonical bytes == worked example", canonical == EXAMPLE, repr(canonical))
check("A worked example is 192 bytes", len(canonical) == 192, str(len(canonical)))

# ---- B) the C# side, read ---------------------------------------------------
SPKI_HEADER = bytes.fromhex("3059301306072a8648ce3d020106082a8648ce3d030107034200")


def p256_spki(text):
    try:
        raw = base64.b64decode(text, validate=True)
    except ValueError:
        return False
    return len(raw) == 91 and raw[:26] == SPKI_HEADER and raw[26] == 0x04


source = (ROOT / "native/Core/Update/UpdateSignature.cs").read_text()
body = source[source.index("public static byte[] Canonical("):]
body = body[:body.index(";")]
literals = [s.encode().decode("unicode_escape") for s in re.findall(r'"((?:[^"\\]|\\.)*)"', body)]
check("B C# Canonical literals in order", literals == [
    "anima-native-update-v1\n", "version=", "\n", "file=", "\n", "size=", "\n", "sha256=", "\n"], repr(literals))
check("B C# formats size invariant and lowercases sha",
      "size.ToString(CultureInfo.InvariantCulture)" in body and "sha256.ToLowerInvariant()" in body)
baked = re.search(r'public const string PublicKeySpki = "([^"]*)";', source)
check("B PublicKeySpki constant present", baked is not None)
if baked:
    check("B PublicKeySpki is empty (fail closed) or a P-256 SPKI",
          baked.group(1) == "" or p256_spki(baked.group(1)), baked.group(1))
    print(f"     (baked key: {'none — this build never updates' if not baked.group(1) else 'present'})")

with tempfile.TemporaryDirectory(prefix="update-signing-smoke-") as temp:
    temp = Path(temp)

    # ---- C) key creation ------------------------------------------------------
    key = temp / "keys" / "release.pem"
    spki = keymaker.make_key(key)
    check("C key file mode 0600", (key.stat().st_mode & 0o777) == 0o600, oct(key.stat().st_mode & 0o777))
    check("C printed SPKI is a 91-byte P-256 SPKI", p256_spki(spki), spki)
    before_key = key.read_bytes()
    try:
        keymaker.make_key(key)
        check("C second make_key on the same path refused", False)
    except FileExistsError:
        check("C second make_key on the same path refused", key.read_bytes() == before_key)
    try:
        keymaker.make_key(ROOT / "native" / "release-key-smoke.pem")
        check("C key inside the repository refused", False)
    except ValueError:
        check("C key inside the repository refused", not (ROOT / "native" / "release-key-smoke.pem").exists())
    public_pem = temp / "public.pem"
    subprocess.run(["openssl", "pkey", "-in", str(key), "-pubout", "-out", str(public_pem)], check=True)

    def verifies(data: bytes, signature: Path) -> bool:
        run = subprocess.run(["openssl", "dgst", "-sha256", "-verify", str(public_pem), "-signature", str(signature)],
                             input=data, capture_output=True)
        return run.returncode == 0 and b"Verified OK" in run.stdout

    # ---- D) signed publish ------------------------------------------------------
    version = "20261029090000-1234abcd"
    image = temp / f"AnimaNative-{version}-x86_64.AppImage"
    image.write_bytes(b"appimage payload")
    dest = temp / "static" / "native"
    publisher.publish(image, version, dest, key)
    manifest_path, sig_path = dest / "version.json", dest / "version.json.sig"
    check("D version.json + version.json.sig published", manifest_path.is_file() and sig_path.is_file())
    check("D both 0644", all((p.stat().st_mode & 0o777) == 0o644 for p in (manifest_path, sig_path)))
    manifest = json.loads(manifest_path.read_text())
    sig = sig_path.read_bytes()
    check("D signature is DER, <= 72 bytes", sig[:1] == b"\x30" and len(sig) <= 72, sig.hex())
    check("D manifest size 16, sha256 of the image",
          manifest["size"] == 16 and manifest["sha256"] == hashlib.sha256(b"appimage payload").hexdigest(), str(manifest))
    signed = publisher.canonical_manifest(manifest["version"], manifest["file"], manifest["size"], manifest["sha256"])
    check("D openssl verifies the published signature", verifies(signed, sig_path))

    # ---- E) one changed byte fails -------------------------------------------
    survivors = []
    for i in range(len(signed)):
        tampered = bytearray(signed)
        tampered[i] = (tampered[i] + 1) % 256
        if verifies(bytes(tampered), sig_path):
            survivors.append(i)
    check(f"E every one-byte change of the {len(signed)} canonical bytes fails", survivors == [], str(survivors))
    forged = dict(manifest, sha256=("0" if manifest["sha256"][0] != "0" else "1") + manifest["sha256"][1:])
    check("E manifest with another sha256 fails",
          not verifies(publisher.canonical_manifest(forged["version"], forged["file"], forged["size"], forged["sha256"]), sig_path))
    rebuilt = dict(manifest, built_utc="2030-01-01T00:00:00Z")
    check("E built_utc alone is not signed",
          verifies(publisher.canonical_manifest(rebuilt["version"], rebuilt["file"], rebuilt["size"], rebuilt["sha256"]), sig_path))

    # ---- F) no key, no publish ------------------------------------------------
    def nothing_published(where: Path) -> bool:
        return not (where / "version.json").exists() and not (where / "version.json.sig").exists()

    unsigned_dest = temp / "unsigned" / "static" / "native"
    run = subprocess.run([sys.executable, str(TOOLS / "publish_appimage.py"), str(image), version, str(unsigned_dest)],
                         capture_output=True, text=True)
    check("F CLI without --signing-key exits 2", run.returncode == 2 and "--signing-key" in run.stderr, run.stderr)
    check("F CLI without key published nothing", nothing_published(unsigned_dest))
    try:
        publisher.publish(image, version, unsigned_dest, None)
        check("F publish(signing_key=None) raises", False)
    except ValueError:
        check("F publish(signing_key=None) raises", nothing_published(unsigned_dest))
    p384 = temp / "p384.pem"
    subprocess.run(["openssl", "genpkey", "-algorithm", "EC", "-pkeyopt", "ec_paramgen_curve:P-384", "-out", str(p384)],
                   check=True, capture_output=True)
    for label, wrong in (("P-384 key", p384), ("public key file", public_pem), ("missing key", temp / "absent.pem")):
        run = subprocess.run([sys.executable, str(TOOLS / "publish_appimage.py"), "--signing-key", str(wrong),
                              str(image), version, str(unsigned_dest)], capture_output=True, text=True)
        check(f"F {label} refused, nothing published", run.returncode != 0 and nothing_published(unsigned_dest),
              f"rc={run.returncode} {run.stderr}")

    # ---- G) served like the manifest -------------------------------------------
    storage = temp / "world"
    instance = temp / "instance"
    os.environ["STORAGE_DIR"] = str(storage)
    os.environ["INSTANCE_DIR"] = str(instance)
    from app.core import paths  # noqa: E402
    paths.init(storage)
    paths.init_instance(instance)
    from fastapi import FastAPI  # noqa: E402
    from fastapi.staticfiles import StaticFiles  # noqa: E402
    from fastapi.testclient import TestClient  # noqa: E402
    from app.core import auth_dependency  # noqa: E402

    app = FastAPI()
    app.middleware("http")(auth_dependency.auth_gate_middleware)

    @app.get("/characters/list")
    def _gated():
        return {"ok": True}

    app.mount("/static", StaticFiles(directory=str(temp / "static")), name="static")
    client = TestClient(app)
    for name in ("version.json", "version.json.sig"):
        response = client.get(f"/static/native/{name}")
        check(f"G anonymous GET /static/native/{name} -> 200 with the published bytes",
              response.status_code == 200 and response.content == (dest / name).read_bytes(), str(response.status_code))
    check("G gate is in front (anonymous /characters/list -> 401)", client.get("/characters/list").status_code == 401)

print()
if FAILS:
    print(f"FAILED: {len(FAILS)} check(s): {FAILS}")
    sys.exit(1)
print("ALL PASS")
