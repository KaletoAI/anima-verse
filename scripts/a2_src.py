#!/usr/bin/env python3
"""Union source window for an extraction product + reading dump.

Usage:
  python a2_src.py stats <db>                 # coverage over ALL extraction memories
  python a2_src.py dump  <db> <n> <seed> [tier]   # random sample for manual reading
  python a2_src.py ids   <db> <id> [<id> ...]     # specific entries with their source

The window unions every table the character could have produced/perceived text in
during [ts-45min, ts+5min]: chat_messages, utterances (room speech), perceptions,
thoughts, character_action_log.storyteller_response.
"""
import sys
import re
import sqlite3
import random
from datetime import timedelta

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from a2_db_quality import (conn, load_memories, load_summaries, char_names,
                           parse_ts, WORD_RE, DE_STOP, EN_STOP)

STOP = DE_STOP | EN_STOP


def cwords(t):
    return {w.lower() for w in WORD_RE.findall(t or "")
            if len(w) >= 5 and w.lower() not in STOP}


def has(c, table):
    try:
        c.execute("select 1 from %s limit 1" % table)
        return True
    except sqlite3.Error:
        return False


def window(c, who, ts, before=45, after=5):
    t = parse_ts(ts)
    if not t:
        return []
    lo = (t - timedelta(minutes=before)).isoformat()
    hi = (t + timedelta(minutes=after)).isoformat()
    out = []
    q = [("chat_messages",
          "select ts, case when role='user' then 'PARTNER:'||partner else 'SELF' end, content "
          "from chat_messages where character_name=? and ts>=? and ts<=?"),
         ("utterances",
          "select ts, 'ROOM:'||speaker, content from utterances "
          "where ts>=? and ts<=? and (speaker=? or addressees like '%'||?||'%')"),
         ("perceptions",
          "select ts, 'PERC:'||kind, content from perceptions "
          "where perceiver=? and ts>=? and ts<=?"),
         ("thoughts",
          "select ts, 'THOUGHT', content from thoughts where character_name=? and ts>=? and ts<=?"),
         ("character_action_log",
          "select created_at, 'ACT', storyteller_response from character_action_log "
          "where character_name=? and created_at>=? and created_at<=?")]
    for table, sql in q:
        if not has(c, table):
            continue
        try:
            if table == "utterances":
                rows = c.execute(sql, (lo, hi, who, who)).fetchall()
            else:
                rows = c.execute(sql, (who, lo, hi)).fetchall()
        except sqlite3.Error:
            continue
        for r in rows:
            out.append((r[0], r[1], r[2] or ""))
    out.sort(key=lambda x: x[0] or "")
    return out


def day_source(c, who, date_key, partner):
    """Source of a daily summary: chat of that day (+ scene summaries of that day)."""
    out = []
    if partner:
        rows = c.execute(
            "select ts, case when role='user' then 'PARTNER' else 'SELF' end, content "
            "from chat_messages where character_name=? and partner=? and substr(ts,1,10)=?",
            (who, partner, date_key)).fetchall()
    else:
        rows = c.execute(
            "select ts, case when role='user' then 'PARTNER:'||partner else 'SELF' end, content "
            "from chat_messages where character_name=? and substr(ts,1,10)=?",
            (who, date_key)).fetchall()
    out += [(r[0], r[1], r[2] or "") for r in rows]
    if has(c, "scenes"):
        rows = c.execute(
            "select last_activity_ts, 'SCENE', summary, participants from scenes "
            "where substr(last_activity_ts,1,10)=? and participants like '%'||?||'%'",
            (date_key, who)).fetchall()
        out += [(r[0], "SCENE", (r[2] or "")) for r in rows if (r[2] or "").strip()]
    if has(c, "memories"):
        rows = c.execute(
            "select ts,'EPISODIC',content from memories where character_name=? "
            "and substr(ts,1,10)=? and tier in ('episodic','semantic')", (who, date_key)).fetchall()
        out += [(r[0], r[1], r[2] or "") for r in rows]
    out.sort(key=lambda x: x[0] or "")
    return out


BOILER = ("Hat ", "Had a group conversation", "Announced to", "Heard ",
          "Planned action", "Reminder:", "Told ", "Saw ", "Acted ",
          "Commented on", "Ich habe einen Instagram-Post", "**I feel", "[")
BOILER_IN = (" liked my Instagram", " commented on my Instagram")


def is_freetext(t):
    t = (t or "").strip()
    if any(t.startswith(p) for p in BOILER):
        return False
    if any(p in t[:60] for p in BOILER_IN):
        return False
    return True


def stats(path):
    c = conn(path)
    names = char_names(c)
    mems = [m for m in load_memories(c) if m["origin"] == "extraction"]
    have = 0
    covs = []
    miss_n = 0
    for m in mems:
        win = window(c, m["who"], m["ts"])
        if not win:
            continue
        have += 1
        src = " ".join(w[2] for w in win)
        cw = cwords(m["content"])
        cov = len(cw & cwords(src)) / len(cw) if cw else 1.0
        covs.append(cov)
        ment = [n for n in names if n.lower() in m["content"].lower()]
        if [n for n in ment if n.lower() not in src.lower() and n != m["who"]]:
            miss_n += 1
    covs.sort()
    print("%s: extraction-Memories n=%d, mit Union-Quellfenster %d (%.0f%%)"
          % (path, len(mems), have, 100 * have / max(1, len(mems))))
    if covs:
        print("  Wortdeckung cov: p10=%.2f median=%.2f p90=%.2f | cov<0.3: %d (%.0f%%)"
              % (covs[len(covs) // 10], covs[len(covs) // 2], covs[9 * len(covs) // 10],
                 sum(1 for x in covs if x < 0.3),
                 100 * sum(1 for x in covs if x < 0.3) / len(covs)))
        print("  mit Namen, die im Quellfenster fehlen: %d (%.1f%%)" % (miss_n, 100 * miss_n / have))


def show(c, names, m, win, maxlines=16, srclen=230):
    src = " ".join(w[2] for w in win)
    cw = cwords(m["content"])
    cov = len(cw & cwords(src)) / len(cw) if cw else 1.0
    ment = [n for n in names if n.lower() in m["content"].lower()]
    miss = [n for n in ment if n.lower() not in src.lower() and n != m["who"]]
    print("=== #%s %s [%s] %s rel=%r cov=%.2f miss=%s lines=%d"
          % (m["id"], m["who"], m.get("tier") or m.get("kind"), m["ts"], m.get("rel", ""),
             cov, miss, len(win)))
    print("  ENTRY: %s" % m["content"][:420].replace("\n", " | "))
    for w in win[-maxlines:]:
        print("   %s %-16s %s" % ((w[0] or "")[5:16], w[1][:16], (w[2] or "").replace("\n", " ")[:srclen]))
    print()


def dump(path, n, seed, tier=None):
    c = conn(path)
    names = char_names(c)
    random.seed(seed)
    mems = [m for m in load_memories(c) if m["origin"] == "extraction"]
    if tier:
        mems = [m for m in mems if m["tier"] == tier]
    mems = [m for m in mems if window(c, m["who"], m["ts"])]
    random.shuffle(mems)
    for m in mems[:n]:
        show(c, names, m, window(c, m["who"], m["ts"]))


def dump_sum(path, n, seed, partner_mode="any"):
    c = conn(path)
    names = char_names(c)
    random.seed(seed)
    sums = [s for s in load_summaries(c) if s["kind"] == "daily"]
    if partner_mode == "with":
        sums = [s for s in sums if s["partner"]]
    elif partner_mode == "without":
        sums = [s for s in sums if not s["partner"]]
    random.shuffle(sums)
    for s in sums[:n]:
        win = day_source(c, s["who"], s["date_key"], s["partner"])
        s2 = dict(s, ts=s["date_key"], rel=s["partner"])
        show(c, names, s2, win, maxlines=22, srclen=190)


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "stats":
        stats(sys.argv[2])
    elif cmd == "dump":
        dump(sys.argv[2], int(sys.argv[3]), int(sys.argv[4]),
             sys.argv[5] if len(sys.argv) > 5 else None)
    elif cmd == "dumpsum":
        dump_sum(sys.argv[2], int(sys.argv[3]), int(sys.argv[4]),
                 sys.argv[5] if len(sys.argv) > 5 else "any")
    elif cmd == "ids":
        c = conn(sys.argv[2])
        names = char_names(c)
        want = set(int(x) for x in sys.argv[3:])
        for m in load_memories(c):
            if m["id"] in want:
                show(c, names, m, window(c, m["who"], m["ts"]))
