#!/usr/bin/env python3
"""Packaging contracts; run with python3 native/tests/package_test.py."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

NATIVE = Path(__file__).resolve().parents[1]
ROOT = NATIVE.parent


class PackagingTests(unittest.TestCase):
    def test_version_uses_commit_time_and_marks_uncommitted_sources(self):
        stamp, sha = subprocess.check_output(
            ["git", "-C", str(ROOT), "show", "-s", "--format=%ct %h", "HEAD"], text=True).split()
        expected = datetime.datetime.fromtimestamp(int(stamp), datetime.timezone.utc).strftime("%Y%m%d%H%M%S") + "-" + sha
        dirty = subprocess.check_output(["git", "-C", str(ROOT), "status", "--porcelain", "--untracked-files=normal"], text=True)
        if dirty:
            expected += "-dirty"
        actual = subprocess.check_output(["bash", str(NATIVE / "version.sh")], text=True).strip()
        self.assertEqual(expected, actual)

    def test_apprun_version_args_logs_and_failure_exit(self):
        with tempfile.TemporaryDirectory(prefix="anima package ") as temp:
            root = Path(temp)
            app = root / "Anima.AppDir"
            binary = app / "usr/bin"
            binary.mkdir(parents=True)
            shutil.copyfile(NATIVE / "AppRun", app / "AppRun")
            (binary / "version.txt").write_text("20261029090000-1234abcd\n")
            engine = binary / "anima-native.x86_64"
            engine.write_text("#!/usr/bin/env python3\nimport sys,json,os\nopen(os.environ['ARGS'], 'w').write(json.dumps(sys.argv[1:]))\nprint('engine started')\nsys.exit(7)\n")
            engine.chmod(0o755)
            env = dict(os.environ, HOME=str(root), XDG_DATA_HOME=str(root / "user data"), ARGS=str(root / "args.json"))
            version = subprocess.run(["bash", str(app / "AppRun"), "--version"], env=env, text=True, capture_output=True)
            self.assertEqual(0, version.returncode, version.stderr)
            self.assertEqual("20261029090000-1234abcd", version.stdout.strip())
            self.assertFalse((root / "args.json").exists())
            run = subprocess.run(["bash", str(app / "AppRun"), "--headless", "--", "--check", "--user=A B"], env=env, text=True, capture_output=True)
            self.assertEqual(7, run.returncode, run.stderr)
            args = json.loads((root / "args.json").read_text())
            self.assertIn("--headless", args)
            self.assertEqual(["--check", "--user=A B"], args[args.index("--") + 1:])
            logfile = Path(args[args.index("--log-file") + 1])
            self.assertTrue(logfile.is_relative_to(root / "user data"))
            logs = list((root / "user data").rglob("native-*.log"))
            self.assertEqual(1, len(logs))
            self.assertEqual("Anima Native 20261029090000-1234abcd", logs[0].read_text().splitlines()[0])
            self.assertIn("engine started", logs[0].read_text())
            self.assertFalse((app / "logs").exists())
            fallback_env = dict(env)
            fallback_env.pop("XDG_DATA_HOME")
            run = subprocess.run(["bash", str(app / "AppRun"), "--headless", "--user=C D"], env=fallback_env, text=True, capture_output=True)
            self.assertEqual(7, run.returncode, run.stderr)
            args = json.loads((root / "args.json").read_text())
            self.assertEqual(["--user=C D"], args[args.index("--") + 1:])
            self.assertIn("--headless", args)
            logfile = Path(args[args.index("--log-file") + 1])
            self.assertTrue(logfile.is_relative_to(root / ".local/share/godot/app_userdata/Anima Native/logs"))

    def test_publish_hash_size_replacement_and_failure_preserves_release(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            dest = root / "static/native"
            dest.mkdir(parents=True)
            old = dest / "AnimaNative-old-x86_64.AppImage"
            old.write_bytes(b"old")
            image = root / "AnimaNative-20261029090000-1234abcd-x86_64.AppImage"
            image.write_bytes(b"appimage payload")
            command = ["python3", str(NATIVE / "tools/publish_appimage.py"), str(image), "20261029090000-1234abcd", str(dest)]
            run = subprocess.run(command, text=True, capture_output=True)
            self.assertEqual(0, run.returncode, run.stderr)
            info = json.loads((dest / "version.json").read_text())
            self.assertEqual({"version", "file", "size", "sha256", "built_utc"}, set(info))
            self.assertEqual(image.name, info["file"])
            self.assertEqual("20261029090000-1234abcd", info["version"])
            self.assertEqual(16, info["size"])
            self.assertEqual(hashlib.sha256(b"appimage payload").hexdigest(), info["sha256"])
            self.assertTrue(os.access(dest / image.name, os.X_OK))
            self.assertEqual(0o644, (dest / "version.json").stat().st_mode & 0o777)
            self.assertFalse(old.exists())
            datetime.datetime.strptime(info["built_utc"], "%Y-%m-%dT%H:%M:%SZ")
            before = (dest / "version.json").read_bytes()
            dirty = subprocess.run(command[:3] + ["20261029090000-1234abcd-dirty", str(dest)], capture_output=True)
            self.assertNotEqual(0, dirty.returncode)
            self.assertEqual(before, (dest / "version.json").read_bytes())
            image.unlink()
            failed = subprocess.run(command, capture_output=True)
            self.assertNotEqual(0, failed.returncode)
            self.assertEqual(before, (dest / "version.json").read_bytes())
            self.assertEqual(b"appimage payload", (dest / info["file"]).read_bytes())
            self.assertEqual([], list(dest.glob("*.tmp")))

    def test_package_assembles_complete_export_and_rejects_missing_cef(self):
        # Only the two expensive host tools are substituted. Assembly, permission
        # repair, filename/version matching and publication gates run for real.
        export = NATIVE / "export"
        export.mkdir(exist_ok=True)
        # Keep this test deterministic on clean HEAD too. This temporary source
        # is outside the ignored export tree and is removed by the context manager.
        with tempfile.TemporaryDirectory(dir=export) as temp, tempfile.NamedTemporaryFile(
                dir=NATIVE / "tests", prefix=".package-source-", suffix=".txt") as dirty_source:
            root = Path(temp)
            native = root / "native"
            native.mkdir()
            for name in ["package.sh", "version.sh", "AppRun", "icon.svg"]:
                shutil.copyfile(NATIVE / name, native / name)
            (native / "fixtures").mkdir()
            (native / "fixtures/fixture.json").write_text("{}")
            build = native / "build.sh"
            build.write_text("""#!/usr/bin/env bash
set -eu
out="$1"
mkdir -p "$out/locales"
for file in anima-native.x86_64 libgdcef.so libcef.so gdCefRenderProcess libmeshoptimizer.so icudtl.dat extra.pak; do
  echo payload > "$out/$file"
done
bash "$(dirname "$0")/version.sh" > "$out/version.txt"
[ -z "${DROP_CEF:-}" ] || rm "$out/libcef.so"
""")
            tool = root / "appimagetool"
            tool.write_text("""#!/usr/bin/env python3
import os, pathlib, sys
app, output = map(pathlib.Path, sys.argv[-2:])
for name in ['AppRun', 'usr/bin/anima-native.x86_64', 'usr/bin/gdCefRenderProcess']:
    assert os.access(app / name, os.X_OK), name
for name in ['anima-native.desktop', 'anima-native.svg', '.DirIcon', 'usr/bin/libmeshoptimizer.so', 'usr/bin/extra.pak', 'usr/bin/fixtures/fixture.json']:
    assert (app / name).is_file(), name
assert os.environ['ARCH'] == 'x86_64'
output.write_bytes(b'packed AppDir')
""")
            tool.chmod(0o755)
            env = dict(os.environ, APPIMAGETOOL=str(tool))
            out = root / "out"
            command = ["bash", str(native / "package.sh"), str(out)]
            run = subprocess.run(command, env=env, capture_output=True, text=True)
            self.assertEqual(0, run.returncode, run.stderr)
            images = list(out.glob("AnimaNative-*-dirty-x86_64.AppImage"))
            self.assertEqual(1, len(images))
            self.assertEqual(b"packed AppDir", images[0].read_bytes())
            self.assertEqual([], list(out.glob(".package-*")))
            run = subprocess.run(command, env=dict(env, DROP_CEF="1"), capture_output=True, text=True)
            self.assertNotEqual(0, run.returncode)
            self.assertIn("missing libcef.so", run.stderr)
            self.assertEqual([], list(out.glob(".package-*")))
            self.assertEqual(b"packed AppDir", images[0].read_bytes())
            run = subprocess.run(command + ["--publish"], env=env, capture_output=True, text=True)
            self.assertNotEqual(0, run.returncode)
            self.assertIn("clean worktree", run.stderr)


if __name__ == "__main__":
    unittest.main()
