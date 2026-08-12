#!/usr/bin/env python3
"""Reading aid for the A2 hallucination check.

Usage:
  python a2_judge.py mem <db> <n> <seed>
  python a2_judge.py sum <db> <n> <seed> [with|without]
  python a2_judge.py one <db> <id>            # one memory, FULL source text

Per entry it prints
  cov       word coverage of the entry against the FULL (untruncated) source window
  fehlend   distinctive terms of the entry that do NOT occur in the source at all
            (character names are checked separately, first name counts)
  namen?    names in the entry whose first name does not occur in the source
and then the source lines (truncated for reading, the metrics use the full text).
"""
import sys
import random

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from a2_src import window, day_source, cwords, is_freetext
from a2_db_quality import conn, load_memories, load_summaries, char_names

SKIP = set("""oder aber dann dass sich seine ihrem ihren nicht mehr sehr auch schon
noch immer wieder etwas wollte werden wurde haben hatte konnte sollte müssen
during about which their there where would could should because""".split())


def judge(entry, who, src, names):
    low = src.lower()
    cw = {w for w in cwords(entry) if w not in SKIP}
    srcw = cwords(src)
    cov = len(cw & srcw) / len(cw) if cw else 1.0
    missing = sorted(cw - srcw)
    ment = [n for n in names if n.lower() in entry.lower()]
    nmiss = [n for n in ment
             if n != who and n.split()[0].lower() not in low and n.lower() not in low]
    return cov, missing, ment, nmiss


def show(eid, who, tier, ts, rel, content, win, names, maxlines=10, srclen=420):
    src = " ".join(w[2] for w in win)
    cov, missing, ment, nmiss = judge(content, who, src, names)
    print("=== #%s %s [%s] %s rel=%r  cov=%.2f  namen=%s  namen_fehlen=%s  quellzeilen=%d"
          % (eid, who, tier, ts, rel, cov, ment, nmiss, len(win)))
    print("  EINTRAG: %s" % content[:450].replace("\n", " | "))
    print("  FEHLENDE_BEGRIFFE: %s" % (", ".join(missing[:18]) or "-"))
    for w in win[-maxlines:]:
        print("   %s %-14s %s" % ((w[0] or "")[5:16], w[1][:14], (w[2] or "").replace("\n", " ")[:srclen]))
    print()


def mem(path, n, seed):
    c = conn(path)
    names = char_names(c)
    random.seed(seed)
    ms = [m for m in load_memories(c) if m["origin"] == "extraction" and is_freetext(m["content"])]
    rows = []
    for m in ms:
        w = window(c, m["who"], m["ts"])
        if w:
            rows.append((m, w))
    random.shuffle(rows)
    print("POPULATION: %d freitext-Extraktions-Memories mit Quellfenster (von %d gesamt); Stichprobe %d"
          % (len(rows), len(ms), min(n, len(rows))))
    for m, w in rows[:n]:
        show(m["id"], m["who"], m["tier"], m["ts"][:16], m["rel"], m["content"], w, names)


def summ(path, n, seed, mode="any"):
    c = conn(path)
    names = char_names(c)
    random.seed(seed)
    ss = [s for s in load_summaries(c) if s["kind"] == "daily"]
    if mode == "with":
        ss = [s for s in ss if s["partner"]]
    elif mode == "without":
        ss = [s for s in ss if not s["partner"]]
    rows = []
    for s in ss:
        w = day_source(c, s["who"], s["date_key"], s["partner"])
        if w:
            rows.append((s, w))
    random.shuffle(rows)
    print("POPULATION: %d Tages-Summaries (%s) mit Quelltag; Stichprobe %d"
          % (len(rows), mode, min(n, len(rows))))
    for s, w in rows[:n]:
        show(s["id"], s["who"], "daily", s["date_key"], s["partner"], s["content"], w,
             names, maxlines=14, srclen=300)


def one(path, eid):
    c = conn(path)
    names = char_names(c)
    for m in load_memories(c):
        if m["id"] == int(eid):
            w = window(c, m["who"], m["ts"])
            show(m["id"], m["who"], m["tier"], m["ts"], m["rel"], m["content"], w,
                 names, maxlines=30, srclen=4000)


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "mem":
        mem(sys.argv[2], int(sys.argv[3]), int(sys.argv[4]))
    elif cmd == "sum":
        summ(sys.argv[2], int(sys.argv[3]), int(sys.argv[4]),
             sys.argv[5] if len(sys.argv) > 5 else "any")
    else:
        one(sys.argv[2], sys.argv[3])
