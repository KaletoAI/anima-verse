#!/usr/bin/env python3
"""Weak validators: W/ changes representation strength, not opaque identity.

Hand-derived from P3 section 4.2: both weak/strong directions, lists,
wildcards and whitespace match; a different tag or missing header does not.
Usage: .venv/bin/python scripts/smoke_etag_matches.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.http_files import etag_matches

for value, tag, expected in [
    ('W/"a"', '"a"', True), ('"a"', 'W/"a"', True),
    ('"x", W/"a"', '"a"', True), ("*", '"a"', True),
    ('"b"', '"a"', False), (None, '"a"', False),
    ('  "x",  W/"a"  ', '"a"', True),
    ('W/"a,b"', '"a,b"', True),
    ('"x", W/"a,b"', '"a,b"', True),
    ('"a"', '"a,b"', False),
]:
    assert etag_matches(value, tag) is expected, (value, tag, expected)
print("PASS weak ETag comparisons")
