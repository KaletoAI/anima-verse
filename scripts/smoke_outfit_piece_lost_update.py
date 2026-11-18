#!/usr/bin/env python3
"""Smoke: review 05#12 — two writers of ONE shared ``outfit_piece`` never lose an update.

Usage:
    ./.venv/bin/python scripts/smoke_outfit_piece_lost_update.py

No server, no Blender, no LLM, no network: a throwaway world (``paths.init`` into a temp dir BEFORE any world
import), one world outfit piece made with ``inventory.add_item``.

The race, derived by hand from ``app/models/inventory.py::update_item`` (a key the update NAMES replaces the stored
one) and the writers ``garment_from_worn.set_choice`` / ``garment_template.set_params`` (each: ``get_item`` → copy
the whole ``outfit_piece`` → change ONE key → ``update_item`` with the whole copy):

  start      template.params.length_m 0.6, no piece_views
  T1         set_choice("demo", item, "front", "worn") reads the piece (length 0.6) and is held 0.5 s
             after its read (``inventory.get_item`` wrapped for T1 only)
  T2         set_params(item, length_m 0.8) — started once T1 has read
  expected   length_m 0.8 AND piece_views {"front": "worn"}: T2's write must not be undone by T1's stale copy,
             which names ``template`` with the OLD record.

[1] final length_m == 0.8          [2] final piece_views == {"front": "worn"}
[3] T2 finished after T1 (T2 waited for the item lock; with no lock T2 finishes inside T1's 0.5 s hold)

Second race, same shape, with a whole-item writer: T1 = ``inventory.set_item_image_meta(item, {"backend": "x"})``
held 0.5 s after its ``_load_items`` read (the pre-fix writer saved that WHOLE snapshot back), T2 =
``set_params(item, length_m 0.9)``.
[4] final length_m == 0.9          [5] final image_meta == {"backend": "x"}          [6] T2 finished after T1

Fails on the pre-fix commit 104171a41 (no item lock: [1] reads 0.6 and [3] is False — T1 locked per character,
set_params not at all; [4] reads the stale value and [6] is False — set_item_image_meta took no lock).
"""
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_SCRATCH = Path(tempfile.mkdtemp(prefix="smoke-op-lost-"))
from app.core import paths  # noqa: E402
paths.init(_SCRATCH / "world")
paths.init_instance(_SCRATCH / "instance")

from app.core import db  # noqa: E402
db.init_schema()
from app.core import garment_from_worn as gfw  # noqa: E402
from app.core import garment_template as gt  # noqa: E402
from app.models import inventory  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"   [{detail}]" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


shirt = inventory.add_item("T-Shirt", category="outfit_piece", prompt_fragment="blue t-shirt",
                           outfit_piece={"slots": ["top"], "covers": []})
iid = shirt["id"]
gt.set_params(iid, {"kind": "top", "length_m": 0.6, "sleeves": "short"})

_real_get = inventory.get_item
t1_read = threading.Event()
done = {}


def _slow_get(item_id, *a, **kw):
    item = _real_get(item_id, *a, **kw)
    if threading.current_thread().name == "T1" and not t1_read.is_set():
        t1_read.set()
        time.sleep(0.5)
    return item


inventory.get_item = _slow_get


def t1():
    gfw.set_choice("demo", iid, "front", gfw.WORN)
    done["T1"] = time.monotonic()


def t2():
    gt.set_params(iid, {"kind": "top", "length_m": 0.8, "sleeves": "short"})
    done["T2"] = time.monotonic()


a = threading.Thread(target=t1, name="T1")
a.start()
t1_read.wait(5)
b = threading.Thread(target=t2, name="T2")
b.start()
a.join(10)
b.join(10)
inventory.get_item = _real_get

final = inventory.get_item(iid)["outfit_piece"]
params = gt.params_of(inventory.get_item(iid)) or {}
check("[1] template length kept at 0.8", params.get("length_m") == 0.8, str(params.get("length_m")))
check("[2] piece_views stored", final.get("piece_views") == {"front": "worn"}, str(final.get("piece_views")))
check("[3] T2 waited for T1", done.get("T2", 0) > done.get("T1", 1), str(done))

# --- second race: set_item_image_meta vs set_params
_real_load = inventory._load_items
t1b_read = threading.Event()
done.clear()


def _slow_load(*a, **kw):
    items = _real_load(*a, **kw)
    if threading.current_thread().name == "T1b" and not t1b_read.is_set():
        t1b_read.set()
        time.sleep(0.5)
    return items


inventory._load_items = _slow_load


def t1b():
    inventory.set_item_image_meta(iid, {"backend": "x"})
    done["T1"] = time.monotonic()


def t2b():
    gt.set_params(iid, {"kind": "top", "length_m": 0.9, "sleeves": "short"})
    done["T2"] = time.monotonic()


a = threading.Thread(target=t1b, name="T1b")
a.start()
t1b_read.wait(5)
b = threading.Thread(target=t2b, name="T2b")
b.start()
a.join(10)
b.join(10)
inventory._load_items = _real_load
item = inventory.get_item(iid)
params = gt.params_of(item) or {}
check("[4] template length kept at 0.9", params.get("length_m") == 0.9, str(params.get("length_m")))
check("[5] image_meta stored", item.get("image_meta") == {"backend": "x"}, str(item.get("image_meta")))
check("[6] T2 waited for T1", done.get("T2", 0) > done.get("T1", 1), str(done))

print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL OK")
sys.exit(1 if FAILS else 0)
