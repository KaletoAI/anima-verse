#!/usr/bin/env python3
"""Fact quality of the A2 extraction products (memories/summaries/relationships).

Usage:
    python a2_db_quality.py <section> <db> [<db> ...]
    python a2_db_quality.py sample <db> <memories|summaries> <limit> <seed> [<tier>]

Sections:
    inventory   row counts, timespans, origin classification per table
    junk        empty/duplicate/fence/preamble/language/truncation counters
    persons     person-reference metrics (name vs pronoun/role, first-name-only)
    sample      dump entry + reconstructed source window for manual reading

The DBs must be READ-ONLY SNAPSHOTS of worlds/<w>/world.db — never the live file
(the server holds locks).  The script only measures; interpretation is manual.
"""
import sys
import re
import json
import sqlite3
import difflib
import collections
from datetime import datetime, timedelta

DE_STOP = set("der die das und ist ein eine sich nicht mit dem den ich er sie es "
              "auf für von als aus bei nach über um vor war hatte wurde ihre seine "
              "ihm ihr dass wie noch nur schon aber dann weil dabei während".split())
EN_STOP = set("the and is a an of to in that with for on at as was were had has "
              "her his their they she he it this these those while after before "
              "from which but not only".split())

WORD_RE = re.compile(r"[A-Za-zÄÖÜäöüßÀ-ÿ]+")


def conn(path):
    c = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    c.row_factory = sqlite3.Row
    return c


def lang_of(text):
    words = [w.lower() for w in WORD_RE.findall(text)]
    if len(words) < 8:
        return "short"
    de = sum(1 for w in words if w in DE_STOP)
    en = sum(1 for w in words if w in EN_STOP)
    if de > en * 1.3:
        return "de"
    if en > de * 1.3:
        return "en"
    return "mixed"


def parse_ts(s):
    if not s:
        return None
    s = s.replace("Z", "+00:00")
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        return None
    return d.replace(tzinfo=None)


def char_names(c):
    return [r[0] for r in c.execute("select name from characters")]


def origin_of(tier, tags, meta):
    tags = set(tags)
    ctx = meta.get("context", "")
    if any(t.startswith("action_performed") for t in tags):
        return "act_engine_performed"
    if any(t.startswith("action_witnessed") for t in tags):
        return "act_engine_witnessed"
    if ctx == "scene" or "scene" in tags:
        return "scene_consolidation"
    if ctx == "day" or "day" in tags:
        return "day_consolidation"
    return "extraction"


def load_memories(c):
    out = []
    for r in c.execute("select * from memories order by ts"):
        tags = json.loads(r["tags"] or "[]")
        meta = json.loads(r["meta"] or "{}")
        out.append(dict(id=r["id"], who=r["character_name"], tier=r["tier"],
                        ts=r["ts"], content=r["content"] or "", tags=tags,
                        meta=meta, origin=origin_of(r["tier"], tags, meta),
                        rel=meta.get("related_character", "")))
    return out


def load_summaries(c):
    out = []
    for r in c.execute("select * from summaries order by date_key"):
        out.append(dict(id=r["id"], who=r["character_name"], kind=r["kind"],
                        date_key=r["date_key"], partner=r["partner"] or "",
                        content=r["content"] or ""))
    return out


def sec_inventory(path):
    c = conn(path)
    print("### %s" % path)
    for t in ("memories", "summaries", "relationships", "knowledge",
              "chat_messages", "diary_entries", "utterances", "scenes",
              "social_dialog_history", "character_action_log", "thoughts"):
        try:
            n = c.execute('select count(*) from "%s"' % t).fetchone()[0]
        except sqlite3.Error:
            continue
        cols = [r[1] for r in c.execute('PRAGMA table_info("%s")' % t)]
        tcol = "ts" if "ts" in cols else ("created_at" if "created_at" in cols
                                          else ("date_key" if "date_key" in cols else None))
        span = ""
        if tcol and n:
            lo, hi = c.execute('select min("%s"),max("%s") from "%s"' % (tcol, tcol, t)).fetchone()
            span = " %s .. %s" % (lo, hi)
        print("  %-24s %6d%s" % (t, n, span))
    mems = load_memories(c)
    print("  memories by (tier,origin):")
    for k, v in sorted(collections.Counter((m["tier"], m["origin"]) for m in mems).items(),
                       key=lambda x: -x[1]):
        print("     %-40s %5d" % ("%s/%s" % k, v))
    sums = load_summaries(c)
    print("  summaries by kind:", dict(collections.Counter(s["kind"] for s in sums)))
    print()


PREAMBLE_RE = re.compile(
    r"^\s*(hier ist|here is|here's|zusammenfassung\s*:|summary\s*:|sure[,!]|"
    r"okay[,.]|als (assistent|zusammenfass)|the summary|natürlich[,!]|"
    r"i (will|can) summar)", re.I)
SALAD_RE = re.compile(r"[Ѐ-ӿ一-鿿぀-ヿ؀-ۿ]")
REPEAT_RE = re.compile(r"(.)\1{6,}")
END_OK_RE = re.compile(r"[.!?…»\"')\]]\s*$")
THINK_RE = re.compile(r"<think|</think|◁think", re.I)


def junk_row(text):
    flags = []
    t = (text or "").strip()
    if not t:
        return ["empty"]
    if "```" in t:
        flags.append("fence")
    if t.startswith("{") or t.startswith("["):
        flags.append("json_residue")
    if PREAMBLE_RE.search(t):
        flags.append("preamble")
    if SALAD_RE.search(t):
        flags.append("foreign_script")
    if REPEAT_RE.search(t):
        flags.append("char_repeat")
    if THINK_RE.search(t):
        flags.append("think_tag")
    if not END_OK_RE.search(t):
        flags.append("no_sentence_end")
    if re.search(r"<tool|\[IMAGE|!\[|https?://", t):
        flags.append("markup")
    if len(t) < 15:
        flags.append("very_short")
    return flags


def sec_junk(path):
    c = conn(path)
    print("### %s" % path)
    for label, rows in (("memories", [(m["id"], m["who"], m["content"], m["origin"])
                                      for m in load_memories(c)]),
                        ("summaries", [(s["id"], s["who"], s["content"], s["kind"])
                                       for s in load_summaries(c)])):
        n = len(rows)
        if not n:
            continue
        fc = collections.Counter()
        lang = collections.Counter()
        per_group_lang = collections.defaultdict(collections.Counter)
        flag_examples = collections.defaultdict(list)
        for _id, who, txt, grp in rows:
            for f in junk_row(txt):
                fc[f] += 1
                if len(flag_examples[f]) < 4:
                    flag_examples[f].append((_id, who, (txt or "")[:130]))
            l = lang_of(txt or "")
            lang[l] += 1
            per_group_lang[grp][l] += 1
        exact = 0
        fuzzy = 0
        by_char = collections.defaultdict(list)
        for _id, who, txt, grp in rows:
            by_char[who].append((_id, (txt or "").strip()))
        fuzzy_examples = []
        for who, items in by_char.items():
            seen = {}
            for _id, txt in items:
                if txt in seen:
                    exact += 1
                else:
                    seen[txt] = _id
            keys = list(seen.keys())
            for i in range(len(keys)):
                for j in range(i + 1, len(keys)):
                    a, b = keys[i], keys[j]
                    if abs(len(a) - len(b)) > max(len(a), len(b), 1) * 0.4:
                        continue
                    r = difflib.SequenceMatcher(None, a, b).ratio()
                    if r >= 0.85:
                        fuzzy += 1
                        if len(fuzzy_examples) < 8:
                            fuzzy_examples.append((who, round(r, 2), a[:110], b[:110]))
        print("  %s n=%d" % (label, n))
        print("     flags:", dict(fc))
        print("     lang:", dict(lang))
        for grp, lc in sorted(per_group_lang.items()):
            print("       %-22s %s" % (grp, dict(lc)))
        print("     exact_dupes=%d  fuzzy_pairs(>=0.85)=%d" % (exact, fuzzy))
        for f in ("fence", "json_residue", "preamble", "foreign_script",
                  "char_repeat", "think_tag", "empty", "markup"):
            for e in flag_examples.get(f, []):
                print("       %-14s #%s %s | %s" % ((f,) + e))
        for ex in fuzzy_examples:
            print("       fz %s %.2f | %s || %s" % ex)
    print()


# Whole-word role nouns (German + English), incl. inflected/possessive forms.
ROLE_RE = re.compile(
    r"\b("
    r"bruder|bruders|brüder|schwester|schwestern|mutter|vater|sohn|sohnes|"
    r"tochter|onkel|tante|cousin|cousine|oma|opa|eltern|geschwister|"
    r"brother|sister|mother|father|son|daughter|sibling|"
    r"freund|freundin|freunde|chef|chefin|nachbar|nachbarin|kollege|kollegin|"
    r"kollegen|ehemann|ehefrau|geliebte|geliebter|partnerin"
    r")\b", re.I)
# Generic person placeholders — the entry deliberately hides WHO it was about.
GENERIC_RE = re.compile(
    r"\b("
    r"eine[rn]? (anderen? )?person|die person|jemand(en|em)?|der andere|"
    r"den anderen|dem anderen|die andere|gesprächspartner(in)?|"
    r"der erzähler|dem erzähler|den erzähler|erzählers|"
    r"der unbekannte|dem unbekannten|einen unbekannten|ein unbekannter|"
    r"the narrator|the other person|someone|somebody|a stranger|the stranger|"
    r"der (user|nutzer|spieler)|the (user|player)|"
    r"mein gegenüber|sein gegenüber|ihr gegenüber"
    r")\b", re.I)
PRONOUNS = ("er", "sie", "ihn", "ihm", "ihr", "ihre", "ihrem", "ihren", "seine",
            "seinem", "seinen", "he", "she", "him", "her", "his", "they", "them")


def sec_persons(path):
    c = conn(path)
    names = char_names(c)
    firsts = collections.Counter(n.split()[0] for n in names)
    multiword = [n for n in names if " " in n]
    print("### %s" % path)
    print("  characters=%d multiword=%s ambiguous_firsts=%s"
          % (len(names), multiword, [f for f, k in firsts.items() if k > 1]))

    def analyse(rows, label):
        n = len(rows)
        if not n:
            return
        no_name = role_no_name = pron_only = first_only = generic = 0
        role_examples, noname_examples, firstonly_examples = [], [], []
        generic_examples = []
        for _id, who, txt in rows:
            t = txt or ""
            low = t.lower()
            words = [w.lower() for w in WORD_RE.findall(t)]
            found_any = [nm for nm in names
                         if nm.lower() in low or nm.split()[0].lower() in words]
            others = [nm for nm in found_any if nm != who]
            if not found_any:
                no_name += 1
                if len(noname_examples) < 8:
                    noname_examples.append((_id, who, t[:110]))
            roles = ROLE_RE.findall(t)
            if roles and not others:
                role_no_name += 1
                if len(role_examples) < 8:
                    role_examples.append((_id, who, [r[0] for r in roles][:2], t[:110]))
            g = GENERIC_RE.search(t)
            if g:
                generic += 1
                if len(generic_examples) < 8:
                    generic_examples.append((_id, who, g.group(0), t[:110]))
            if not others and any(w in PRONOUNS for w in words):
                pron_only += 1
            for nm in multiword:
                first = nm.split()[0]
                if first.lower() in words and nm.lower() not in low:
                    first_only += 1
                    if len(firstonly_examples) < 6:
                        firstonly_examples.append((_id, who, first, t[:110]))
                    break
        print("  %s n=%d" % (label, n))
        print("     kein Charaktername im Eintrag:      %4d (%.1f%%)" % (no_name, 100 * no_name / n))
        print("     Rollenwort ohne fremden Namen:      %4d (%.1f%%)" % (role_no_name, 100 * role_no_name / n))
        print("     nur Pronomen, kein fremder Name:    %4d (%.1f%%)" % (pron_only, 100 * pron_only / n))
        print("     Vorname ohne Nachnamen (Mehrwort):  %4d (%.1f%%)" % (first_only, 100 * first_only / n))
        print("     generischer Personen-Platzhalter:   %4d (%.1f%%)" % (generic, 100 * generic / n))
        for e in generic_examples:
            print("       gen   #%s %s (%s) | %s" % e)
        for e in role_examples:
            print("       role  #%s %s %s | %s" % e)
        for e in noname_examples[:4]:
            print("       none  #%s %s | %s" % e)
        for e in firstonly_examples[:4]:
            print("       first #%s %s (%s) | %s" % e)

    mems = load_memories(c)
    analyse([(m["id"], m["who"], m["content"]) for m in mems], "memories(all)")
    analyse([(m["id"], m["who"], m["content"]) for m in mems if m["origin"] == "extraction"],
            "memories(extraction only)")
    for org in ("day_consolidation", "scene_consolidation"):
        analyse([(m["id"], m["who"], m["content"]) for m in mems if m["origin"] == org],
                "memories(%s)" % org)
    sums = load_summaries(c)
    analyse([(s["id"], s["who"], s["content"]) for s in sums], "summaries(all)")
    print()


def source_window(c, who, partner, ts, before_min=45, after_min=5):
    t = parse_ts(ts)
    if not t:
        return []
    lo = (t - timedelta(minutes=before_min)).isoformat()
    hi = (t + timedelta(minutes=after_min)).isoformat()
    if partner:
        q = ("select ts,role,partner,content from chat_messages where character_name=? "
             "and partner=? and ts>=? and ts<=? order by ts")
        args = [who, partner, lo, hi]
    else:
        q = ("select ts,role,partner,content from chat_messages where character_name=? "
             "and ts>=? and ts<=? order by ts")
        args = [who, lo, hi]
    return [dict(r) for r in c.execute(q, args)]


def day_window(c, who, partner, date_key):
    if partner:
        q = ("select ts,role,partner,content from chat_messages where character_name=? "
             "and partner=? and substr(ts,1,10)=? order by ts")
        args = [who, partner, date_key]
    else:
        q = ("select ts,role,partner,content from chat_messages where character_name=? "
             "and substr(ts,1,10)=? order by ts")
        args = [who, date_key]
    return [dict(r) for r in c.execute(q, args)]


def sec_sample(path, kind="memories", limit=40, seed=7, tier=None):
    import random
    random.seed(seed)
    c = conn(path)
    names = char_names(c)
    print("### %s  kind=%s tier=%s seed=%s" % (path, kind, tier, seed))
    if kind == "memories":
        rows = [m for m in load_memories(c) if m["origin"] == "extraction"]
        if tier:
            rows = [m for m in rows if m["tier"] == tier]
        random.shuffle(rows)
        picked = rows[:limit]
        picked.sort(key=lambda m: m["ts"])
        for m in picked:
            win = source_window(c, m["who"], m["rel"], m["ts"])
            if not win:
                win = source_window(c, m["who"], "", m["ts"])
            mentioned = [n for n in names if n.lower() in m["content"].lower()]
            src_txt = " ".join(w["content"] or "" for w in win).lower()
            missing = [n for n in mentioned if n.lower() not in src_txt and n != m["who"]]
            print("--- MEM #%s %s [%s] %s rel=%r" % (m["id"], m["who"], m["tier"], m["ts"], m["rel"]))
            print("    C: %s" % m["content"][:400])
            print("    names_in_entry=%s missing_in_source=%s window_lines=%d"
                  % (mentioned, missing, len(win)))
            for w in win[-12:]:
                who = "PARTNER" if w["role"] == "user" else "SELF"
                print("      %s %-7s %s" % (w["ts"][11:19], who, (w["content"] or "").replace("\n", " ")[:240]))
            print()
    else:
        rows = load_summaries(c)
        if tier:
            rows = [s for s in rows if s["kind"] == tier]
        random.shuffle(rows)
        picked = rows[:limit]
        for s in picked:
            win = day_window(c, s["who"], s["partner"], s["date_key"]) if s["kind"] == "daily" else []
            mentioned = [n for n in names if n.lower() in s["content"].lower()]
            src_txt = " ".join(w["content"] or "" for w in win).lower()
            missing = [n for n in mentioned if n.lower() not in src_txt and n != s["who"]]
            print("--- SUM #%s %s [%s %s] partner=%r" % (s["id"], s["who"], s["kind"], s["date_key"], s["partner"]))
            print("    C: %s" % s["content"][:700])
            print("    names_in_entry=%s missing_in_source=%s window_lines=%d"
                  % (mentioned, missing, len(win)))
            for w in win[:26]:
                who = "PARTNER" if w["role"] == "user" else "SELF"
                print("      %s %-7s %s" % (w["ts"][11:19], who, (w["content"] or "").replace("\n", " ")[:200]))
            print()


if __name__ == "__main__":
    sec = sys.argv[1]
    fn = dict(inventory=sec_inventory, junk=sec_junk, persons=sec_persons)
    if sec == "sample":
        sec_sample(sys.argv[2],
                   sys.argv[3] if len(sys.argv) > 3 else "memories",
                   int(sys.argv[4]) if len(sys.argv) > 4 else 40,
                   int(sys.argv[5]) if len(sys.argv) > 5 else 7,
                   sys.argv[6] if len(sys.argv) > 6 else None)
    else:
        for p in sys.argv[2:]:
            fn[sec](p)
