#!/usr/bin/env python3
"""Scrapes the CMU mocap database index into shared/models/cmu_catalog.json.

Three page kinds carry everything the bulk import needs:

* ``motcat.php``                     — the six main categories
* ``motcat.php?maincat=<n>``         — that category's subcategories
* ``search.php?maincat=<n>&subcat=<m>`` — which takes sit in a subcategory
* ``subjects.php`` / ``search.php?subjectnumber=<s>`` — every subject with all
  of its trials, their descriptions, the source frame rate and the exact
  ``.asf``/``.amc`` file names on the server (which zero-pad subjects < 10).

The take list comes from the SUBJECT pages — they are complete; the category
pages only decide where a take is filed. A take that no subcategory lists keeps
an empty ``categories``.

Pairs (two people recorded together) are recognised from the subject
description marker "(2 subjects - subject A|B)": subjects whose description is
otherwise identical form a pair, and equal trial numbers on both sides are the
same recording seen from the two skeletons. Some pairs carry no marker at all
(the salsa subjects 60/61), so two ADJACENT subjects with the same description
and the very same trial list count as a pair too. That last rule over-reaches —
two people who each walked once on their own read the same as two who walked
together — so ``scripts/cmu_convert_all.py`` confirms every pair against the
AMC frame counts before converting it as one.

The run is idempotent — roughly 140 requests, one at a time with a short pause.

Usage:
    ./.venv/bin/python scripts/cmu_catalog.py [--out <file>] [--pause <s>]

Options:
    --out <file>    where to write the catalog
                    (default: shared/models/cmu_catalog.json)
    --pause <s>     seconds between requests (default 0.4)
"""
import argparse
import html
import json
import re
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import paths  # noqa: E402

CMU_BASE = "https://mocap.cs.cmu.edu"

# "(2 subjects - subject A)" — the only reliable pair marker in the database.
ROLE_RE = re.compile(r"\(\s*2\s+subjects?\s*-\s*subject\s*([AB])\s*\)", re.I)
SUBJECT_HEAD_RE = re.compile(r"Subject #(\d+)\s*\((.*?)\)\s*<A HREF", re.I | re.S)
ASF_RE = re.compile(r'HREF="(/subjects/[^"]+\.asf)"', re.I)
# One trial row of a subject page: a first cell that is empty on most subjects
# but carries a thumbnail link on the newer ones, then trial number,
# description and the file links; the second-to-last cell is the frame rate.
TRIAL_RE = re.compile(
    r"<TR BGCOLOR=#[0-9A-Fa-f]{6}><TD>(?:(?!</?TR).)*?</TD><TD>(\d+)</TD><TD>(.*?)</TD>(.*?)</TR>",
    re.I | re.S)
AMC_RE = re.compile(r'HREF="(/subjects/[^"]+\.amc)"', re.I)
RATE_RE = re.compile(r"<TD>\s*(\d+)\s*</TD>\s*<TD><A HREF=\"badtrial", re.I)
CAT_LINK_RE = re.compile(r'HREF="motcat\.php\?maincat=(\d+)">(.*?)</A>', re.I | re.S)
SUBCAT_LINK_RE = re.compile(
    r'HREF="search\.php\?maincat=(\d+)&subcat=(\d+)">(.*?)</A>', re.I | re.S)
CAT_TAKE_RE = re.compile(
    r'HREF="search\.php\?subjectnumber=(\d+)&trinum=(\d+)">\d+</A></TD><TD>(.*?)</TD>',
    re.I | re.S)
SUBJECT_LINK_RE = re.compile(r"search\.php\?subjectnumber=(\d+)[\"&]", re.I)

_UNVERIFIED = ssl.create_default_context()
_UNVERIFIED.check_hostname = False
_UNVERIFIED.verify_mode = ssl.CERT_NONE


def get(url: str, pause: float = 0.4) -> str:
    """Fetches one page; the CMU server ships an incomplete certificate chain,
    so a failed verification falls back to an unverified fetch."""
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            body = r.read()
    except (urllib.error.URLError, ssl.SSLError):
        with urllib.request.urlopen(url, timeout=60, context=_UNVERIFIED) as r:
            body = r.read()
    time.sleep(pause)
    return body.decode("utf-8", "replace")


def text(raw: str) -> str:
    """Table cell markup to plain text."""
    return html.unescape(re.sub(r"<[^>]+>", "", raw)).strip()


def role_of(desc: str) -> str:
    m = ROLE_RE.search(desc or "")
    return m.group(1).lower() if m else ""


def base_desc(desc: str) -> str:
    """The description without the pair marker — the pair's shared identity."""
    return re.sub(r"\s+", " ", ROLE_RE.sub("", desc or "")).strip(" ,-").lower()


def scrape_categories(pause: float) -> tuple:
    """Main categories, subcategories and the take → category assignment."""
    page = get(f"{CMU_BASE}/motcat.php", pause)
    mains = {mid: text(name) for mid, name in CAT_LINK_RE.findall(page)}
    subs, assign = {}, {}
    for mid in sorted(mains, key=int):
        sub_page = get(f"{CMU_BASE}/motcat.php?maincat={mid}", pause)
        found = [(a, b, text(n)) for a, b, n in SUBCAT_LINK_RE.findall(sub_page)]
        for main, sub, name in found:
            key = f"{main}/{sub}"
            subs[key] = name
            take_page = get(f"{CMU_BASE}/search.php?maincat={main}&subcat={sub}", pause)
            for subject, trial, _desc in CAT_TAKE_RE.findall(take_page):
                assign.setdefault((int(subject), int(trial)), []).append(key)
        print(f"  main {mid} {mains[mid]!r}: {len(found)} subcategories")
    return mains, subs, assign


def scrape_subject(number: int, pause: float) -> dict:
    """One subject page: description plus every trial with its file names."""
    page = get(f"{CMU_BASE}/search.php?subjectnumber={number}", pause)
    head = SUBJECT_HEAD_RE.search(page)
    desc = text(head.group(2)) if head else ""
    asf = ASF_RE.search(page)
    trials = []
    for trial, raw_desc, rest in TRIAL_RE.findall(page):
        amc = AMC_RE.search(rest)
        rate = RATE_RE.search(rest)
        if not amc:
            continue
        trials.append({
            "trial": int(trial),
            "description": text(raw_desc),
            "amc": amc.group(1),
            "framerate": int(rate.group(1)) if rate else 0,
        })
    return {"number": number, "description": desc,
            "asf": asf.group(1) if asf else "", "trials": trials}


def pair_partners(subjects: list) -> dict:
    """Maps a subject number to its partner's number, and to its role.

    Two ways a pair shows itself, both needed:

    * the explicit marker — subjects whose descriptions match apart from
      "(2 subjects - subject A|B)" belong together; within such a group each A
      takes the closest unused B, which keeps the neighbouring numbering
      (18/19, 20/21, …) intact even where a group holds more than one pair.
    * unmarked twins — the salsa subjects 60/61 carry no marker at all. Two
      ADJACENT subject numbers with the same description and the very same
      trial list (count, descriptions and frame rates) are the two skeletons of
      one recording; the lower number is A.
    """
    by_number = {s["number"]: s for s in subjects}
    groups = {}
    for s in subjects:
        role = role_of(s["description"])
        if role:
            groups.setdefault(base_desc(s["description"]),
                              {"a": [], "b": []})[role].append(s["number"])
    partners, roles = {}, {}
    for group in groups.values():
        free_b = sorted(group["b"])
        for a in sorted(group["a"]):
            if not free_b:
                break
            b = min(free_b, key=lambda n: (abs(n - a), n < a))
            free_b.remove(b)
            partners[a], partners[b] = b, a
            roles[a], roles[b] = "a", "b"

    def fingerprint(s: dict) -> tuple:
        return (base_desc(s["description"]),
                tuple((t["trial"], base_desc(t["description"]), t["framerate"])
                      for t in s["trials"]))

    for a in sorted(by_number):
        b = a + 1
        if a in partners or b in partners or b not in by_number:
            continue
        if not by_number[a]["trials"]:
            continue
        if fingerprint(by_number[a]) == fingerprint(by_number[b]):
            partners[a], partners[b] = b, a
            roles[a], roles[b] = "a", "b"
    return partners, roles


def build(pause: float) -> dict:
    print("scraping categories …")
    mains, subs, assign = scrape_categories(pause)
    print(f"  {len(mains)} main categories, {len(subs)} subcategories, "
          f"{len(assign)} categorised takes")

    index = get(f"{CMU_BASE}/subjects.php", pause)
    numbers = sorted({int(n) for n in SUBJECT_LINK_RE.findall(index)})
    print(f"scraping {len(numbers)} subjects …")
    subjects = []
    for n in numbers:
        s = scrape_subject(n, pause)
        subjects.append(s)
        print(f"  subject {n}: {len(s['trials'])} trials — {s['description'][:60]}")

    partners, roles = pair_partners(subjects)
    print("pairs: " + ", ".join(f"{a}/{b}" for a, b in sorted(partners.items()) if a < b))
    by_number = {s["number"]: s for s in subjects}
    takes = []
    for s in subjects:
        role = roles.get(s["number"], "")
        partner = partners.get(s["number"], 0)
        stem = Path(s["asf"]).stem            # "01" / "18" — the server's own name
        for t in s["trials"]:
            take_id = Path(t["amc"]).stem     # "01_01" / "18_01"
            partner_id = ""
            if partner:
                other = by_number.get(partner)
                match = next((x for x in (other["trials"] if other else [])
                              if x["trial"] == t["trial"]), None)
                if match:
                    partner_id = Path(match["amc"]).stem
            takes.append({
                "subject": s["number"],
                "trial": t["trial"],
                "id": take_id,
                "subject_dir": stem,
                "asf": s["asf"],
                "amc": t["amc"],
                "framerate": t["framerate"],
                "description": t["description"],
                "subject_description": s["description"],
                "categories": sorted(assign.get((s["number"], t["trial"]), [])),
                "pair_role": role if partner_id else "",
                "pair_partner": partner_id,
            })
    return {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": f"{CMU_BASE}/",
        "credit": ("The data used in this project was obtained from "
                   "mocap.cs.cmu.edu. The database was created with funding "
                   "from NSF EIA-0196217."),
        "main_categories": mains,
        "sub_categories": subs,
        "takes": takes,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default="")
    ap.add_argument("--pause", type=float, default=0.4)
    a = ap.parse_args()

    out = Path(a.out) if a.out else paths.get_shared_dir() / "models" / "cmu_catalog.json"
    cat = build(a.pause)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(cat, indent=1, ensure_ascii=False), encoding="utf-8")

    takes = cat["takes"]
    paired = sum(1 for t in takes if t["pair_partner"])
    uncat = sum(1 for t in takes if not t["categories"])
    print(f"\nwrote {out}")
    print(f"  {len(takes)} takes, {paired} of them in pairs "
          f"({paired // 2} recordings), {uncat} without a category")
    return 0


if __name__ == "__main__":
    sys.exit(main())
