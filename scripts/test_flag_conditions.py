"""Standalone check: state flags are valid conditions, as the help panel says.

Run: ./.venv/bin/python scripts/test_flag_conditions.py
No server — throwaway world, profile access stubbed.

The condition help panel offers every registered state flag (is_sleeping,
is_wet, is_intimate, decency_exempt + plugin flags) as a bare condition.
Before 2026-07-29 the evaluator had no handler for them: they fell through
to "unknown condition" and passed permissively — a filter like
"stamina<20 AND is_sleeping" triggered regardless of the flag.
"""
import sys
import tempfile

sys.path.insert(0, ".")


def check(name: str, cond: bool):
    print(("PASS  " if cond else "FAIL  ") + name)
    if not cond:
        sys.exit(1)


def main() -> None:
    tmp = tempfile.mkdtemp(prefix="anima_flag_cond_check_")
    from app.core import paths, db
    paths.init(tmp)
    db.init_schema()

    import app.models.character as character
    from app.core.activity_engine import evaluate_condition

    profile = {"gender": "male", "is_intimate": True, "is_wet": False}
    orig = character.get_character_profile
    character.get_character_profile = lambda n, **kw: dict(profile)
    try:
        check("active flag passes", evaluate_condition("is_intimate", "Demo")[0])
        check("inactive flag fails", not evaluate_condition("is_wet", "Demo")[0])
        check("absent flag fails", not evaluate_condition("decency_exempt", "Demo")[0])
        check("NOT inverts a flag", not evaluate_condition("NOT is_intimate", "Demo")[0])
        check("flag composes with AND",
              evaluate_condition("is_intimate AND is_male", "Demo")[0])
        check("AND fails on the inactive flag",
              not evaluate_condition("is_wet AND is_male", "Demo")[0])
        check("inactive flag reports a reason",
              bool(evaluate_condition("is_wet", "Demo")[1]))
        # Documented permissiveness for truly unknown conditions stays.
        check("unknown condition still passes",
              evaluate_condition("definitely_not_a_condition", "Demo")[0])
    finally:
        character.get_character_profile = orig

    print("OK")


if __name__ == "__main__":
    main()
