#!/usr/bin/env python3
"""Manual live check of ONE decision endpoint — not a smoke, needs the network.

Usage:  ./.venv/bin/python scripts/check_decision_endpoint.py <base-url> [model]
        e.g. http://<host>:8080/upstream/laya

Sends the probe questions of plan-decision-models.md § 1 (the idle-thought
question and four pose texts in two steps) and prints, per answer, the value,
the client's own confidence, the server's confidence and the latency. Uses the
client's protocol helpers directly; no world, no config, no storage.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.core.decision import Choice, _ask  # noqa: E402

if len(sys.argv) < 2:
    print(__doc__)
    sys.exit(2)
EP = {"name": "probe", "url": sys.argv[1], "model": sys.argv[2] if len(sys.argv) > 2 else ""}


def show(label, state, questions):
    t0 = time.monotonic()
    r = _ask(EP, state, questions, 60.0, track=False)
    ms = (time.monotonic() - t0) * 1000
    if r.answers is None:
        print(f"{label:48s} FAILED {r.error} ({ms:.0f} ms)")
        return None
    for q, a in r.answers.items():
        print(f"{label:48s} {q}={a.value!s:18s} conf={a.confidence:.3f} "
              f"server={r.server_confidence.get(q)} ({ms:.0f} ms)")
    return r.answers


show("idle: Kira alone, nothing new", {"document": "Kira sitzt allein in der Küche. Niemand hat sie "
     "angesprochen, nichts Neues ist passiert."},
     {"turn": Choice("Does Kira have a reason to act or speak right now?",
                     {"act": "yes, there is a reason", "idle": "no, nothing new"})})

GROUPS = Choice("Which body position does the text describe?",
                {"stand": "Standing spot", "seat": "Seat", "ground": "Ground", "lie": "Lying place"})
for text in ("lehnt sich mit verschränkten Armen an die Wand", "sitzt am Tisch und liest",
             "liegt im Bett und schläft", "kniet vor dem Altar"):
    show(f"pose group: {text}", {"text": text}, {"group": GROUPS})
