#!/usr/bin/env python3
"""Create the native client's release signing key pair (ECDSA P-256) with the openssl CLI.

Usage: make_update_signing_key.py PRIVATE_KEY_PATH

Writes the PEM private key to PRIVATE_KEY_PATH (mode 0600; an existing file is never
overwritten; a path inside this repository is refused) and prints the public key as
base64 SubjectPublicKeyInfo (DER). Paste that into ``PublicKeySpki`` in
native/Core/Update/UpdateSignature.cs, rebuild the client, and publish with
``native/package.sh --publish --signing-key=PRIVATE_KEY_PATH``.
"""
import base64
import os
from pathlib import Path
import shutil
import subprocess
import sys

REPOSITORY = Path(__file__).resolve().parents[2]
CLIENT_KEY_FILE = "native/Core/Update/UpdateSignature.cs"


def make_key(path: Path) -> str:
    """Create the private key at ``path`` and return the public key as base64 SPKI."""
    openssl = shutil.which("openssl")
    if openssl is None:
        raise RuntimeError("the openssl command is required")
    target = path.expanduser().absolute()
    if target.resolve().is_relative_to(REPOSITORY):
        raise ValueError(f"the private key must live outside the repository ({REPOSITORY})")
    if os.path.lexists(target):
        raise FileExistsError(f"refusing to overwrite {target}")
    generated = subprocess.run([openssl, "genpkey", "-algorithm", "EC", "-pkeyopt", "ec_paramgen_curve:P-256"],
                               capture_output=True)
    if generated.returncode != 0 or b"PRIVATE KEY" not in generated.stdout:
        raise RuntimeError("openssl genpkey failed: " + generated.stderr.decode(errors="replace").strip())
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    # O_EXCL: never overwrite, also not a file that appeared since the check above.
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        output.write(generated.stdout)
        output.flush()
        os.fsync(output.fileno())
    public = subprocess.run([openssl, "pkey", "-in", str(target), "-pubout", "-outform", "DER"], capture_output=True)
    if public.returncode != 0 or not public.stdout:
        raise RuntimeError("openssl could not derive the public key: " + public.stderr.decode(errors="replace").strip())
    return base64.b64encode(public.stdout).decode("ascii")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: make_update_signing_key.py PRIVATE_KEY_PATH")
    try:
        spki = make_key(Path(sys.argv[1]))
    except (OSError, ValueError, RuntimeError) as error:
        sys.exit(f"make_update_signing_key.py: {error}")
    print(f"private key: {Path(sys.argv[1]).expanduser().absolute()} (mode 0600, keep it out of the repository)")
    print(f"public key (base64 SPKI): {spki}")
    print(f"paste it into {CLIENT_KEY_FILE}, then rebuild the client:")
    print(f'    public const string PublicKeySpki = "{spki}";')
