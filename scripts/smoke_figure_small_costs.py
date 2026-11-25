"""Usage: ./.venv/bin/python scripts/smoke_figure_small_costs.py

Task 7 of the figure-poll-caches plan: three small per-poll costs.

[K1] garment_template._file_sha goes through base_body.file_sha256, keyed by
     (size, mtime_ns, inode). One tmp file hashed twice -> Path.read_bytes runs
     exactly 1x (the second call is a stat hit), value == hashlib.sha256(content).
     The file is then replaced via os.replace by a file of the SAME length but
     different content: the replacement was created while the old file still
     existed, so it has a new inode -> the key differs -> a new hash, equal to
     sha256(new content). A missing file gives "".
     Old code: read_bytes on every call -> 2 reads for 2 calls -> FAIL.

[K2] outfit_renderer.is_free_text_wardrobe, values confirmed against the old
     code (it read get_template(name)["features"]["outfit_system_enabled"]):
       {"template": "npc-temporary"} -> True  (npc-temporary.json declares
                                               features.outfit_system_enabled false)
       {"template": "default"}      -> False (no default.json in
                                               shared/templates/character -> None -> {})
       {"template": "no-such-tmpl"} -> False (unknown -> None)
       {}                           -> False (no name -> early False)
     Warm cache (the npc-temporary call above warmed template_features): a
     second call for npc-temporary calls get_template 0x.
     Old code: get_template on every call -> 1 call -> FAIL.

[K3] body_slots: filter_mesh_input_loras called 5x with the same LoRA that
     an active, exposed mesh part's glob drops -> exactly 1 INFO line
     "Mesh input part dropped LoRA" (once per LoRA name). exposed_slot_loras(
     mesh_input=True) with the active mesh part and a stored slot LoRA -> 0 INFO
     lines (that drop logs at DEBUG now).
     Old code: 5 INFO lines from the filter, 1 from exposed_slot_loras -> FAIL.

No world, no server, no LLM, no HTTP: STORAGE_DIR/INSTANCE_DIR and
paths.init point at tmp dirs before any world-DB module is imported.
"""
import hashlib
import logging
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_tmp = tempfile.TemporaryDirectory()
_storage = Path(_tmp.name) / "world"
_instance = Path(_tmp.name) / "instance"
_storage.mkdir()
_instance.mkdir()
os.environ["STORAGE_DIR"] = str(_storage)
os.environ["INSTANCE_DIR"] = str(_instance)

from app.core import paths  # noqa: E402

paths.init(str(_storage))

failures = []


def check(label, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + label + (f" -- {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(label)


# ---------------------------------------------------------------- [K1]
from app.core import garment_template as gt  # noqa: E402

f = Path(_tmp.name) / "tex.png"
content_a = b"A" * 64
content_b = b"B" * 64
f.write_bytes(content_a)
reads = []
_orig_read_bytes = Path.read_bytes


def _counting_read_bytes(self):
    if str(self) == str(f):
        reads.append(1)
    return _orig_read_bytes(self)


with patch.object(Path, "read_bytes", _counting_read_bytes):
    h1 = gt._file_sha(str(f))
    h2 = gt._file_sha(str(f))
    check("[K1] two calls read the file once", len(reads) == 1, f"reads={len(reads)}")
    check("[K1] value is sha256(content)",
          h1 == h2 == hashlib.sha256(content_a).hexdigest(), f"{h1} {h2}")
    repl = Path(_tmp.name) / "tex.new"
    repl.write_bytes(content_b)
    os.replace(repl, f)
    h3 = gt._file_sha(str(f))
    check("[K1] same-length replacement (new inode) rehashes",
          h3 == hashlib.sha256(content_b).hexdigest(), h3)
check("[K1] missing file -> ''", gt._file_sha(str(Path(_tmp.name) / "missing.png")) == "")

# ---------------------------------------------------------------- [K2]
from app.core import outfit_renderer as orr  # noqa: E402
from app.models import character_template as ct  # noqa: E402

check("[K2] npc-temporary -> True", orr.is_free_text_wardrobe({"template": "npc-temporary"}) is True)
check("[K2] default -> False", orr.is_free_text_wardrobe({"template": "default"}) is False)
check("[K2] unknown -> False", orr.is_free_text_wardrobe({"template": "no-such-tmpl"}) is False)
check("[K2] {} -> False", orr.is_free_text_wardrobe({}) is False)
calls = []
_orig_get_template = ct.get_template


def _counting_get_template(*a, **k):
    calls.append(a)
    return _orig_get_template(*a, **k)


with patch.object(ct, "get_template", _counting_get_template):
    warm = orr.is_free_text_wardrobe({"template": "npc-temporary"})
check("[K2] warm second call -> True", warm is True)
check("[K2] warm second call: get_template 0x", len(calls) == 0, f"calls={len(calls)}")

# ---------------------------------------------------------------- [K3]
from app.core import body_slots as bs  # noqa: E402
from app.plugins.registry import BodySlotSpec, MeshPartSpec  # noqa: E402


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.records.append(record)


cap = _Capture()
bs.logger.addHandler(cap)
bs.logger.setLevel(logging.DEBUG)

slot = BodySlotSpec("slot", "fixture", covered_by=["cover"],
                    attributes={"lora": {"type": "lora_select"}},
                    mesh_part=MeshPartSpec("switch", "flat slot", ["*InsetShape*"], {}))
profile = {"body_slots": {"slot": {"switch": "on", "lora": "slot-insetshape"}}, "equipped_pieces": {}}
loras = [{"name": "INSETSHAPE-v1", "strength": 1}, {"name": "pose", "strength": 1}]


def info_lines(text):
    return [r for r in cap.records if r.levelno == logging.INFO and text in r.getMessage()]


with patch.object(bs, "slots_for_character", return_value=[slot]):
    kept = None
    for _ in range(5):
        kept = bs.filter_mesh_input_loras(loras, profile)
    check("[K3] filter keeps the non-matching LoRA", kept == [loras[1]], repr(kept))
    n = len(info_lines("Mesh input part dropped LoRA"))
    check("[K3] 5 filter calls -> exactly 1 INFO line", n == 1, f"lines={n}")
    cap.records.clear()
    out = bs.exposed_slot_loras("", profile=profile, mesh_input=True)
    check("[K3] exposed_slot_loras(mesh_input) drops the slot LoRA", out == [], repr(out))
    n = len([r for r in cap.records if r.levelno >= logging.INFO])
    check("[K3] exposed_slot_loras(mesh_input) -> 0 INFO lines", n == 0, f"lines={n}")
bs.logger.removeHandler(cap)

if failures:
    print(f"FAILED {len(failures)}: " + ", ".join(failures))
    sys.exit(1)
print("ALL PASS smoke_figure_small_costs")
