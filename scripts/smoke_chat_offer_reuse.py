#!/usr/bin/env python3
"""Respond tool prompts use package menus through the shared builder.

Usage: python scripts/smoke_chat_offer_reuse.py
Private paths are initialized before imports. No providers or server run.
"""
import ast
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import paths
TEMP = tempfile.TemporaryDirectory(prefix='chat-offer-')
paths.init(Path(TEMP.name) / 'world')
paths.init_instance(Path(TEMP.name) / 'instance')
from app.core import chat_engine as E


class OfferReuse(unittest.TestCase):
    def test_respond_uses_shared_builder_after_narration(self):
        tree = ast.parse(Path(E.__file__).read_text())
        turn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'run_chat_turn')
        calls = [n for n in ast.walk(turn) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name) and n.func.id == 'build_tool_step_prompt']
        self.assertEqual(len(calls), 1)
        args = {kw.arg: ast.unparse(kw.value) for kw in calls[0].keywords}
        self.assertEqual(args['mode'], "'respond'")
        self.assertEqual(args['rp_response'], 'clean')
        self.assertEqual(args['user_input'], 'incoming_message')
        self.assertNotIn('room_offer', args)
        self.assertNotIn('places.room_offer', ast.unparse(turn))


if __name__ == '__main__':
    unittest.main()
