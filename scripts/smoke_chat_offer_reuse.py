#!/usr/bin/env python3
"""RP tool prompts reuse the same offer, including an empty offer.

Usage: python scripts/smoke_chat_offer_reuse.py
Private paths are initialized before imports. No providers or server run.
"""
import ast
from contextlib import ExitStack
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import paths
TEMP = tempfile.TemporaryDirectory(prefix='chat-offer-')
paths.init(Path(TEMP.name) / 'world')
paths.init_instance(Path(TEMP.name) / 'instance')
from app.core import chat_engine as E


class OfferReuse(unittest.TestCase):
    def test_supplied_offer_is_used_without_recomputation(self):
        with ExitStack() as stack:
            replacements = {
                'app.core.dependencies.get_skill_manager': Mock(return_value=Mock(get_agent_usage_instructions=Mock(return_value=''))),
                'app.core.tool_formats.build_tool_instruction': Mock(return_value='tools'),
                'app.core.outfit_renderer.undressed_line': Mock(return_value='undressed'),
                'app.models.character.get_character_appearance': Mock(return_value=''),
                'app.models.character.get_character_current_location': Mock(return_value='loc'),
                'app.models.character.get_character_language_instruction': Mock(return_value=''),
                'app.models.character_template.is_roleplay_character': Mock(return_value=True),
                'app.models.world.list_locations_for_character': Mock(return_value=[]),
                'app.models.account.get_active_character': Mock(return_value=''),
                'app.core.places.room_offer': Mock(side_effect=AssertionError('offer recomputed')),
            }
            for name, value in replacements.items():
                stack.enter_context(patch(name, value))
            for offer in ('SHARED OFFER', ''):
                result = E._build_rp_tool_system('A', [], 'tag', '', '', room_offer=offer)
                self.assertEqual('SHARED OFFER' in result, bool(offer))

    def test_chat_context_forwards_offer_from_main_prompt(self):
        tree = ast.parse(Path(E.__file__).read_text())
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Name) and node.func.id == '_build_rp_tool_system']
        self.assertEqual(len(calls), 1)
        forwarded = next((kw.value for kw in calls[0].keywords if kw.arg == 'room_offer'), None)
        self.assertIsInstance(forwarded, ast.Attribute)
        self.assertEqual(ast.unparse(forwarded), '_prompt.room_offer')


if __name__ == '__main__':
    unittest.main()
