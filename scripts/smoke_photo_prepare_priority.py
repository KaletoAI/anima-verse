#!/usr/bin/env python3
"""Prepare must enqueue image_prompt at HIGH, preserving the queue timing label.

Usage: ./.venv/bin/python scripts/smoke_photo_prepare_priority.py
Hand oracle: the waiting player gets Priority.HIGH (10), not the ordinary
image_prompt default NORMAL (20). The prompt and subject still reach the UI.
Temporary storage is initialised before any world imports; the LLM is stubbed.
"""
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
with tempfile.TemporaryDirectory(prefix="photo-priority-") as temp:
    os.environ["STORAGE_DIR"] = temp
    os.environ["INSTANCE_DIR"] = temp
    from app.core import paths
    paths.init(temp)
    paths.init_instance(temp)
    from app.core.scene_photo import prepare_scene_photo
    from app.core.llm_queue import Priority
    with patch('app.core.scene_photo._pairs_among', return_value=[]), \
         patch('app.core.scene_photo._person_descriptions', return_value=''), \
         patch('app.core.prompt_templates.render_task', return_value=('System', 'User')), \
         patch('app.imagegen.routing.explain_occasion', return_value={}), \
         patch('app.core.llm_router.llm_call', return_value=SimpleNamespace(
             content='A candid photograph of Bob standing beside a sunlit window.')) as llm:
        result = prepare_scene_photo('Ann', snapshot={
            'location': 'loc', 'room': 'room', 'subjects': ['Bob'],
            'present': ['Bob'], 'transcript': 'Bob: Look at this lovely view.'})
    assert result['ok'] and result['subjects'] == ['Bob']
    assert result['prompt'].startswith('A candid photograph')
    assert llm.call_args.kwargs['task'] == 'image_prompt'
    assert llm.call_args.kwargs.get('priority') == Priority.HIGH, llm.call_args
    assert llm.call_args.kwargs.get('label') == 'scene-photo prepare'
print('photo prepare priority: PASS (HIGH + timing label, stubbed LLM, temporary storage)')
