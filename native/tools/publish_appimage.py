#!/usr/bin/env python3
"""Publish a complete, signed AppImage before atomically replacing its manifest.

Usage: publish_appimage.py --signing-key KEY IMAGE VERSION DESTINATION

KEY is the PEM ECDSA P-256 private key made by make_update_signing_key.py; it never
lives in the repository. Without a usable key nothing is published.

The client (native/Core/Update/UpdateSignature.cs) verifies ``version.json.sig``: a
DER (RFC 3279) ECDSA P-256 / SHA-256 signature over ``canonical_manifest()`` of the
manifest's version, file, size and sha256. ``built_utc`` is informational and unsigned.
"""
import argparse
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

CANONICAL_HEADER = "anima-native-update-v1"


def canonical_manifest(version: str, file: str, size: int, sha256: str) -> bytes:
    """The ONE canonical serialisation of the signed fields (UTF-8, LF line ends, final LF).

    Must stay byte-identical to UpdateSignature.Canonical in the client.
    """
    return (f"{CANONICAL_HEADER}\nversion={version}\nfile={file}\nsize={int(size)}\n"
            f"sha256={sha256.lower()}\n").encode("utf-8")


def _openssl() -> str:
    tool = shutil.which("openssl")
    if tool is None:
        raise RuntimeError("signing requires the openssl command")
    return tool


def check_signing_key(key: Path) -> None:
    """Refuse anything but a readable ECDSA P-256 private key."""
    if not key.is_file():
        raise ValueError(f"signing key not found: {key}")
    run = subprocess.run([_openssl(), "pkey", "-in", str(key), "-noout", "-text"],
                         capture_output=True, text=True)
    if run.returncode != 0 or "prime256v1" not in run.stdout or "priv:" not in run.stdout:
        raise ValueError(f"signing key is not an ECDSA P-256 private key: {key}")


def sign_manifest(canonical: bytes, key: Path) -> bytes:
    """DER signature over ``canonical``, verified against the key's own public half before use."""
    openssl = _openssl()
    signed = subprocess.run([openssl, "dgst", "-sha256", "-sign", str(key)], input=canonical, capture_output=True)
    if signed.returncode != 0 or not signed.stdout:
        raise RuntimeError("openssl could not sign the manifest: " + signed.stderr.decode(errors="replace").strip())
    with tempfile.TemporaryDirectory(prefix="anima-update-verify-") as temp:
        public, signature = Path(temp) / "public.pem", Path(temp) / "version.json.sig"
        derived = subprocess.run([openssl, "pkey", "-in", str(key), "-pubout", "-out", str(public)], capture_output=True)
        signature.write_bytes(signed.stdout)
        verified = subprocess.run([openssl, "dgst", "-sha256", "-verify", str(public), "-signature", str(signature)],
                                  input=canonical, capture_output=True)
        if derived.returncode != 0 or verified.returncode != 0:
            raise RuntimeError("the fresh manifest signature does not verify")
    return signed.stdout


def publish(image: Path, version: str, destination: Path, signing_key: Path) -> None:
    if not signing_key:
        raise ValueError("publishing requires a signing key")
    if not re.fullmatch(r"\d{14}-[0-9a-f]{7,40}", version):
        raise ValueError("publishing requires a clean commit version")
    name = f"AnimaNative-{version}-x86_64.AppImage"
    if image.name != name:
        raise ValueError("AppImage filename does not match its baked version")
    check_signing_key(Path(signing_key))
    destination.mkdir(parents=True, exist_ok=True)
    # Serialize publishers, including cleanup of older releases.
    with (destination / ".publish.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        staged = []
        try:
            with tempfile.NamedTemporaryFile(dir=destination, suffix=".tmp", delete=False) as output:
                staged.append(Path(output.name))
                with image.open("rb") as source:
                    shutil.copyfileobj(source, output)
                output.flush()
                os.fsync(output.fileno())
            payload = staged[-1]
            sha256 = hashlib.sha256()
            with payload.open("rb") as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    sha256.update(chunk)
            manifest = {
                "version": version,
                "file": name,
                "size": payload.stat().st_size,
                "sha256": sha256.hexdigest(),
                "built_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
            signature = sign_manifest(
                canonical_manifest(manifest["version"], manifest["file"], manifest["size"], manifest["sha256"]),
                Path(signing_key))
            payload.chmod(0o755)
            with tempfile.NamedTemporaryFile(dir=destination, suffix=".tmp", delete=False) as output:
                staged.append(Path(output.name))
                output.write(signature)
                output.flush()
                os.fchmod(output.fileno(), 0o644)
                os.fsync(output.fileno())
            staged_signature = staged[-1]
            with tempfile.NamedTemporaryFile(mode="w", dir=destination, suffix=".tmp", delete=False) as output:
                staged.append(Path(output.name))
                json.dump(manifest, output, indent=2)
                output.write("\n")
                output.flush()
                os.fchmod(output.fileno(), 0o644)
                os.fsync(output.fileno())
            # Image, then signature, then manifest: once the manifest names the release, both are in place.
            # A client reading between the last two renames sees a mismatching pair and is offered nothing.
            os.replace(payload, destination / name)
            os.replace(staged_signature, destination / "version.json.sig")
            os.replace(staged[-1], destination / "version.json")
            for old in destination.glob("AnimaNative-*-x86_64.AppImage"):
                if old.name != name:
                    old.unlink()
        finally:
            for path in staged:
                path.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Publish a signed AppImage release into static/native/.")
    parser.add_argument("--signing-key", required=True, type=Path,
                        help="PEM ECDSA P-256 private key (make_update_signing_key.py); kept outside the repository")
    parser.add_argument("image", type=Path)
    parser.add_argument("version")
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    try:
        publish(args.image, args.version, args.destination, args.signing_key)
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(1, f"publish_appimage.py: {error}\n")
