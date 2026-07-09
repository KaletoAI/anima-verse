"""Install/remove marketplace skill packages (pack type ``skill_package``).

Unlike content packs (character/item/rule/…) a skill package is a
package-format-v1 folder containing EXECUTABLE PYTHON — installing it means
its code runs on the next skill load. Guard rails therefore live at the
route (admin + explicit trust confirmation); this module does the safe
filesystem work:

- unpack into ``plugins/installed/<id>/`` (fully gitignored — repo files
  and installed content never collide; repo packages win on id collision),
- validate the ZIP is a single package with a ``plugin.yaml`` at its root,
- refuse path traversal / absolute members,
- list + remove installed packages (R7 deletion guarantee — removing the
  folder + reload leaves no trace).

The caller triggers ``discover_packages(force=True)`` / ``reload_skills``
after install to activate.
"""
import io
import shutil
import zipfile
from pathlib import Path
from typing import Any, Dict, List

import yaml

from app.core.log import get_logger

logger = get_logger("skill_package_io")


def _installed_root() -> Path:
    from app.plugins.loader import PLUGIN_DIR, INSTALLED_DIR_NAME
    return PLUGIN_DIR / INSTALLED_DIR_NAME


def _safe_members(zf: zipfile.ZipFile) -> List[str]:
    """Reject absolute paths and traversal; return the member name list."""
    names = zf.namelist()
    for n in names:
        p = Path(n)
        if p.is_absolute() or ".." in p.parts:
            raise ValueError(f"unsafe path in archive: {n!r}")
    return names


def _package_root(names: List[str]) -> str:
    """The single top-level folder every member shares, or '' when the
    ZIP already has plugin.yaml at its own root."""
    tops = {n.split("/", 1)[0] for n in names if n.strip("/")}
    if "plugin.yaml" in names:
        return ""
    if len(tops) != 1:
        raise ValueError(
            "skill package ZIP must contain exactly one package folder "
            f"(found top-level entries: {sorted(tops)})")
    return tops.pop()


def install_skill_package_from_zip(content: bytes,
                                   overwrite: bool = True) -> Dict[str, Any]:
    """Unpack a skill-package ZIP into plugins/installed/<id>/.

    The package id is the manifest ``name`` (fallback: the folder name).
    Returns {status, package_id, path, verbs}. Raises ValueError on an
    invalid archive, FileExistsError when the target exists and
    ``overwrite`` is False.
    """
    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as e:
        raise ValueError(f"not a valid ZIP: {e}")

    names = _safe_members(zf)
    root = _package_root(names)
    manifest_name = f"{root}/plugin.yaml" if root else "plugin.yaml"
    if manifest_name not in names:
        raise ValueError("skill package has no plugin.yaml at its root")

    try:
        manifest = yaml.safe_load(zf.read(manifest_name).decode("utf-8")) or {}
    except Exception as e:
        raise ValueError(f"plugin.yaml is not valid YAML: {e}")
    pkg_id = str(manifest.get("name") or root or "").strip()
    if not pkg_id or "/" in pkg_id or pkg_id in (".", ".."):
        raise ValueError(f"invalid package name in manifest: {pkg_id!r}")

    dest = _installed_root() / pkg_id
    if dest.exists():
        if not overwrite:
            raise FileExistsError(f"skill package '{pkg_id}' already installed")
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)

    prefix = f"{root}/" if root else ""
    for n in names:
        if n.endswith("/") or not n.startswith(prefix):
            continue
        rel = n[len(prefix):]
        if not rel:
            continue
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(zf.read(n))

    verbs = [str((s.get("skill_id") if isinstance(s, dict) else s) or "")
             for s in (manifest.get("skills") or [])]
    verbs = [v for v in verbs if v]
    logger.info("skill package installed: %s -> %s (%d verb(s))",
                pkg_id, dest, len(verbs))
    return {
        "status": "success",
        "package_id": pkg_id,
        "path": str(dest),
        "verbs": verbs,
        "description": str(manifest.get("description") or ""),
    }


def list_installed_skill_packages() -> List[Dict[str, Any]]:
    """Installed (marketplace) skill packages under plugins/installed/."""
    root = _installed_root()
    out: List[Dict[str, Any]] = []
    if not root.exists():
        return out
    for entry in sorted(root.iterdir()):
        manifest = entry / "plugin.yaml"
        if not entry.is_dir() or not manifest.exists():
            continue
        meta: Dict[str, Any] = {}
        try:
            meta = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
        except Exception:
            pass
        out.append({
            "id": entry.name,
            "name": str(meta.get("name") or entry.name),
            "version": str(meta.get("version") or ""),
            "description": str(meta.get("description") or ""),
        })
    return out


def remove_skill_package(package_id: str) -> Dict[str, Any]:
    """Delete an installed skill package (R7: folder removal is complete).
    Only touches plugins/installed/ — repo packages are never removable."""
    pkg_id = (package_id or "").strip()
    if not pkg_id or "/" in pkg_id or pkg_id in (".", ".."):
        raise ValueError(f"invalid package id: {pkg_id!r}")
    dest = _installed_root() / pkg_id
    if not dest.exists() or not dest.is_dir():
        raise FileNotFoundError(f"skill package '{pkg_id}' not installed")
    shutil.rmtree(dest)
    logger.info("skill package removed: %s", pkg_id)
    return {"status": "success", "package_id": pkg_id}
