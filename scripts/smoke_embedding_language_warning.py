#!/usr/bin/env python3
"""Smoke: the admin validation warns when the ENGLISH built-in embedding model
has to rank a world that is not played in English.

Usage:
    ./.venv/bin/python scripts/smoke_embedding_language_warning.py

Runs without the server and without a real world DB: the rule is a pure
function of (config dict, account language), so the account lookup and the
"is an external embedding model routed?" probe are stubbed here. Storage is a
throwaway directory, so nothing is written into worlds/demo.

WHY THE RULE EXISTS (measured 2026-09-21)
-----------------------------------------
Embeddings have two consumers. The pose catalog matches short aliases that
are ENGLISH by design — a small English model is right for it. The
situational memory block (``memory.situational_enabled``, on by default)
embeds free world text: the incoming message against the character's facts
and promises, in the language the world is played in. With the default
``BAAI/bge-small-en-v1.5`` and German memories the ranking was noise — an
unrelated German sentence scored 0.752, the fitting one stayed just under the
0.75 threshold. So: warn, but only when that consumer is actually on.

THE TRUTH TABLE, derived by hand from those four conditions
-----------------------------------------------------------
The rule fires only when ALL of these hold at once, so each row below turns
exactly one of them off and the expected answer follows from the condition it
turns off — not from running the code:

  #  backend            internal_model        situational  language  expect
  1  internal           bge-small-en-v1.5     on           de        WARNING
  2  internal           bge-small-en-v1.5     on           en        none
  3  internal           mpnet multilingual    on           de        none
  4  internal           bge-small-en-v1.5     off          de        none
  5  external (routed)  bge-small-en-v1.5     on           de        none
  6  auto + routed      bge-small-en-v1.5     on           de        none
  7  auto, not routed   (unset -> default)    (unset)      de        WARNING
  8  internal           bge-small-en-v1.5     on           unreadable  none

Reasons, row by row:
  1  all four conditions hold — this is the configuration that was measured.
  2  an English world is exactly what an English model is for.
  3  the multilingual model can rank German; nothing to report.
  4  with the block off, nothing embeds world text any more — only the
     English pose aliases, which the English model handles.
  5  "external" never reaches the built-in model.
  6  "auto" resolves to external as soon as the pose_embedding task is
     routed and reachable — same reason as row 5. Resolved through
     ``embedding.effective_backend``, the one place that rule is written.
  7  the unset case: the schema defaults are the English model and the block
     switched ON, so an unconfigured German world is the measured one.
  8  an unreadable account row (a process without a world DB, a world before
     its first account row) must fail SILENT: no finding, no exception. A
     validation panel that throws is worse than a missing warning.

Further expectations, independent of the table:
  A  The level is ALWAYS "warning", never "error" — a bad language fit ranks
     badly, it does not break anything, and it must never block a save.
  B  The section is "embedding", because that is where the first fix is
     (the settings page turns the section into a jump link).
  C  The message names BOTH fixes: the multilingual mpnet model, and
     switching the situational block off under Memory. A warning that only
     states a problem makes the admin guess.
  D  The rule is reachable through ``validate_config`` — the function the
     route ``POST /admin/settings/validate`` calls — not just directly.
  E  The server log gets the SAME sentence, once per process: the flag is
     set on the first call whether or not there was a finding, so a busy
     world cannot spam the log or re-read the account row per embedding.

Exit code 0 = all checks passed, 1 = at least one failed.
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Storage and the clip library are redirected BEFORE the first app import:
# paths.init otherwise falls back to worlds/demo — the world tracked in git —
# and importing app.models.account would open its world.db.
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(
    prefix="embedding-lang-clips-")

from app.core import paths  # noqa: E402
paths.init(tempfile.mkdtemp(prefix="embedding-lang-storage-"))

from app.core import embedding as emb  # noqa: E402
from app.core.config_validator import validate_config  # noqa: E402

ENGLISH_MODEL = "BAAI/bge-small-en-v1.5"
MULTILINGUAL = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"

failures = []


def check(name, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {name}"
          f"{'' if ok else f'  — got {got!r}, want {want!r}'}")
    if not ok:
        failures.append(name)


# ── stubs ──────────────────────────────────────────────────────────────────

class _Account:
    """Stands in for app.models.account.get_language_settings."""

    def __init__(self):
        self.language = "de"
        self.broken = False

    def __call__(self):
        if self.broken:
            raise RuntimeError("no such table: account_profile")
        return {"system_language": self.language, "translation_mode": "off"}


account = _Account()

import app.models.account as account_mod  # noqa: E402
account_mod.get_language_settings = account

_external_routed = {"value": False}
emb._external_configured = lambda: _external_routed["value"]


def cfg(backend="internal", model=ENGLISH_MODEL, situational=True):
    """A config dict shaped like the one the admin form posts."""
    out = {"embedding": {}, "memory": {}}
    if backend is not None:
        out["embedding"]["backend"] = backend
    if model is not None:
        out["embedding"]["internal_model"] = model
    if situational is not None:
        out["memory"]["situational_enabled"] = situational
    return out


def embedding_issues(config):
    """The embedding findings of the FULL validator run (expectation D)."""
    return [i for i in validate_config(config) if i["section"] == "embedding"]


# ── the truth table ────────────────────────────────────────────────────────

print("Truth table (rows 1-8 of the docstring):")

rows = [
    # name, config, external_routed, language, broken, expected warnings
    ("1 internal + EN model + situational on + de",
     cfg(), False, "de", False, 1),
    ("2 same, world language en",
     cfg(), False, "en", False, 0),
    ("3 multilingual model",
     cfg(model=MULTILINGUAL), False, "de", False, 0),
    ("4 situational block off",
     cfg(situational=False), False, "de", False, 0),
    ("5 backend external, routed",
     cfg(backend="external"), True, "de", False, 0),
    ("6 backend auto, external routed",
     cfg(backend="auto"), True, "de", False, 0),
    ("7 backend auto, nothing routed, schema defaults",
     cfg(backend="auto", model=None, situational=None), False, "de", False, 1),
    ("8 account row unreadable",
     cfg(), False, "de", True, 0),
]

warning_row1 = None
for name, config, routed, lang, broken, want in rows:
    _external_routed["value"] = routed
    account.language = lang
    account.broken = broken
    try:
        issues = embedding_issues(config)
    except Exception as e:  # row 8 must not raise (expectation 8)
        check(name, f"raised {type(e).__name__}: {e}", f"{want} warning(s)")
        continue
    check(name, len(issues), want)
    if name.startswith("1 ") and issues:
        warning_row1 = issues[0]

account.broken = False
account.language = "de"
_external_routed["value"] = False

# ── A/B/C: shape and content of the finding ────────────────────────────────

print("Shape of the finding:")
check("A level is warning", (warning_row1 or {}).get("level"), "warning")
check("B section is embedding", (warning_row1 or {}).get("section"),
      "embedding")

msg = (warning_row1 or {}).get("message", "")
check("C names the offending model", ENGLISH_MODEL in msg, True)
check("C names the multilingual fix", MULTILINGUAL in msg, True)
check("C names the Memory switch as the second fix",
      "situational memory block off" in msg and "Memory" in msg, True)
check("C names the symptom",
      "unrelated memories" in msg and "miss the fitting ones" in msg, True)

# A, the general form: no configuration of the table may produce an error.
levels = set()
for _name, config, routed, lang, broken, _want in rows:
    _external_routed["value"] = routed
    account.language = lang
    account.broken = broken
    try:
        levels |= {i["level"] for i in embedding_issues(config)}
    except Exception:
        pass
account.broken = False
account.language = "de"
_external_routed["value"] = False
check("A the rule never produces level error", levels <= {"warning"}, True)

# ── E: one log line per process ────────────────────────────────────────────

print("Server log:")


class _Recorder:
    def __init__(self):
        self.warnings = []

    def warning(self, fmt, *args):
        self.warnings.append(fmt % args if args else fmt)

    def info(self, *a, **k):
        pass

    def debug(self, *a, **k):
        pass


rec = _Recorder()
real_logger = emb.logger
emb.logger = rec
emb._LANGUAGE_MISMATCH_CHECKED = False
# The live config is empty in this process — which IS row 7: backend auto with
# nothing routed, the schema defaults for model and block.
emb._maybe_log_language_mismatch()
emb._maybe_log_language_mismatch()
emb._maybe_log_language_mismatch()
emb.logger = real_logger

check("E exactly one log line for three uses", len(rec.warnings), 1)
check("E the log line is the validator's wording",
      rec.warnings[0] if rec.warnings else "",
      emb.language_mismatch_message(ENGLISH_MODEL, "de"))

# The flag is set even without a finding, so the account row is read at most
# once per process.
rec2 = _Recorder()
emb.logger = rec2
emb._LANGUAGE_MISMATCH_CHECKED = False
account.language = "en"
emb._maybe_log_language_mismatch()
account.language = "de"
emb._maybe_log_language_mismatch()
emb.logger = real_logger
check("E no log line for an English world, and no second check",
      len(rec2.warnings), 0)

# ── summary ────────────────────────────────────────────────────────────────

print()
if failures:
    print(f"FAILED: {len(failures)} check(s): " + ", ".join(failures))
    sys.exit(1)
print(f"OK — all checks passed ({len(rows)} table rows + shape + log).")
