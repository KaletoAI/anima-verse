#!/usr/bin/env python3
"""Automatic pre-filter for the A2 hallucination check.

Usage: python a2_overlap.py <db> [memories|summaries]

For every extraction product it reconstructs the source window it was made from
(chat_messages of the same character, same partner, shortly before the entry's
timestamp; for daily summaries: the whole day with that partner) and reports

  cov   = share of the entry's content words (>=5 chars, lowercased, no stopwords)
          that literally occur in the source window
  names = character names mentioned in the entry
  miss  = names mentioned that do NOT occur in the source window

Low cov / non-empty miss are CANDIDATES, not verdicts — every case has to be read.
"""
import sys
import re
import json
import sqlite3
import collections
from datetime import datetime, timedelta

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from a2_db_quality import (conn, load_memories, load_summaries, char_names,
                           source_window, day_window, WORD_RE, DE_STOP, EN_STOP)

STOP = DE_STOP | EN_STOP


def content_words(t):
    return {w.lower() for w in WORD_RE.findall(t)
            if len(w) >= 5 and w.lower() not in STOP}


def main(path, kind="memories"):
    c = conn(path)
    names = char_names(c)
    rows = []
    if kind == "memories":
        items = [m for m in load_memories(c) if m["origin"] == "extraction"]
        for m in items:
            win = source_window(c, m["who"], m["rel"], m["ts"])
            fallback = False
            if not win:
                win = source_window(c, m["who"], "", m["ts"])
                fallback = True
            src = " ".join(w["content"] or "" for w in win)
            srcw = content_words(src)
            cw = content_words(m["content"])
            cov = len(cw & srcw) / len(cw) if cw else -1
            ment = [n for n in names if n.lower() in m["content"].lower()]
            miss = [n for n in ment if n.lower() not in src.lower() and n != m["who"]]
            rows.append((m["id"], m["who"], m["tier"], m["ts"][:16], len(win),
                         round(cov, 2), ment, miss, fallback, m["content"][:80]))
    else:
        items = [s for s in load_summaries(c) if s["kind"] == "daily"]
        for s in items:
            win = day_window(c, s["who"], s["partner"], s["date_key"])
            src = " ".join(w["content"] or "" for w in win)
            srcw = content_words(src)
            cw = content_words(s["content"])
            cov = len(cw & srcw) / len(cw) if cw else -1
            ment = [n for n in names if n.lower() in s["content"].lower()]
            miss = [n for n in ment if n.lower() not in src.lower() and n != s["who"]]
            rows.append((s["id"], s["who"], s["kind"] + ":" + (s["partner"] or "-"),
                         s["date_key"], len(win), round(cov, 2), ment, miss, False,
                         s["content"][:80]))

    have = [r for r in rows if r[4] > 0]
    print("### %s %s   n=%d  mit_Quellfenster=%d (%.0f%%)"
          % (path, kind, len(rows), len(have), 100 * len(have) / max(1, len(rows))))
    if have:
        covs = sorted(r[5] for r in have)
        print("  cov: p10=%.2f median=%.2f p90=%.2f" %
              (covs[len(covs) // 10], covs[len(covs) // 2], covs[9 * len(covs) // 10]))
        nmiss = sum(1 for r in have if r[7])
        print("  Einträge mit Namen, die im Quellfenster fehlen: %d/%d (%.1f%%)"
              % (nmiss, len(have), 100 * nmiss / len(have)))
        buckets = collections.Counter()
        for r in have:
            buckets["cov<0.3" if r[5] < 0.3 else ("0.3-0.6" if r[5] < 0.6 else ">=0.6")] += 1
        print("  cov-Verteilung:", dict(buckets))
    for r in sorted(have, key=lambda r: r[5]):
        print("\t".join(str(x) for x in r))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "memories")
