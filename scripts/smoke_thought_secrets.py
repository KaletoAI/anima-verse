#!/usr/bin/env python3
"""Thought knowledge in temporary storage, without an LLM.

Usage: ./.venv/bin/python scripts/smoke_thought_secrets.py

Hand-derived expectations (design D): X knows O's two secrets, learned in
order, so newest first: second (self-discovered), first (told), severity 2.
[a] Regular thought renders that exact block directly after skill text;
    X's own secret never enters it. No knowledge yields an empty key.
[b] Disabled template feature yields an empty key and no knowledge text.
[c] In-chat thought follows the same rendering and feature rules.
"""
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    with tempfile.TemporaryDirectory(prefix="thought-secrets-") as tmp:
        os.environ.update(STORAGE_DIR=tmp, INSTANCE_DIR=tmp)
        from app.core import paths
        paths.init(tmp)
        paths.init_instance(tmp)
        from app.core import db, thought_context as tc
        from app.core.prompt_templates import render
        from app.models import secrets as sec
        from app.models.character import save_character_profile
        db.init_schema()
        for name in ('X', 'O', 'Empty'):
            assert save_character_profile(name, dict(character_language='en'), create_new=True)
        first = sec.add_secret('O', 'First notebook fact')
        second = sec.add_secret('O', 'Second notebook fact')
        sec.add_secret('X', 'Private own fact')
        from app.core.game_time import GameTime
        for secret, day, discovered in [(first, 1, False), (second, 2, True)]:
            with patch.object(sec, 'game_time', return_value=GameTime.parse(f'Y0001-D00{day}T12:00:00')):
                sec.add_known_by('O', secret['id'], 'X', discovered=discovered)
        expected = (
            "\nSecrets you know about others:\n"
            "- About O: Second notebook fact (you discovered this yourself, severity 2/5)\n"
            "- About O: First notebook fact (someone told you, severity 2/5)"
            "\n\nWhen someone asks directly about one of these people, consider sharing what you know — "
            "BUT only if: (a) you trust them more than the secret's owner, OR (b) the severity is low, "
            "OR (c) you have reason to betray the owner (bad relationship, recent conflict). "
            "Otherwise deflect, lie, or partially reveal. Never volunteer high-severity secrets unprompted."
        )
        from app.models.character_template import is_feature_enabled
        def feature(name, key):
            return True if key == 'secrets_enabled' else is_feature_enabled(name, key)
        with patch('app.models.character_template.is_feature_enabled', side_effect=feature), patch.object(
                tc, '_build_skill_context_blocks', return_value=[('demo', 'SKILL SENTINEL')]):
            ctx = tc.build_thought_context('X')
            empty = tc.build_thought_context('Empty')
        assert ctx['known_secrets_block'] == expected
        assert empty['known_secrets_block'] == ''
        assert sec.known_about_others_block('X') == expected
        for label, template in [('a', 'chat/agent_thought.md'), ('c', 'chat/agent_thought_in_chat.md')]:
            out = render(template, **ctx)
            assert expected in out and 'Private own fact' not in out
            start = out.index('SKILL SENTINEL') + len('SKILL SENTINEL')
            assert not out[start:out.index(expected)].strip()
            render(template, **empty)
            print(f'PASS [{label}] {template} knowledge directly after skills; empty context renders')
        def disabled(name, key):
            return False if key == 'secrets_enabled' else is_feature_enabled(name, key)
        with patch('app.models.character_template.is_feature_enabled', side_effect=disabled):
            off = tc.build_thought_context('X')
        assert off['known_secrets_block'] == ''
        for template in ('chat/agent_thought.md', 'chat/agent_thought_in_chat.md'):
            assert 'Secrets you know about others:' not in render(template, **off)
        print('PASS [b] feature off leaves empty key and no block in both templates')
    print('PASS smoke_thought_secrets')


if __name__ == '__main__':
    main()
