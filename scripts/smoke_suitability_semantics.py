"""Offline regression checks, derived by hand from suitability-spec.md.

An offered GoToCharacter is available; an unoffered Invented is not. Markdown
walkthroughs fail format, never hallucinate merely for prose. Markers plus tags
are valid, NONE plus tags is contradictory. JSON parseability proves no semantic
quality. Image text without an image is untested regardless of response language.
Curated synthetic cases require the declared action and reject their named trap;
uncurated cases must leave decision correctness untested. A length stop fails
the case (counted, never excluded) without a refusal/hallucination label. A
conflicting example only suspends that tool's argument check; the case still
counts. Format-template placeholders like `[input]` are not conflicting examples
(the frozen 2026-10 prompts list every tool as `<tool name="X">[input]</tool>`,
which once excluded every real tool case). No provider calls, world data or production parser imports.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.suitability_scoring import prepare_case, score_case, semantic_cases


def main():
    base = {'id': 'demo', 'category': 'tool', 'task': 'intent', 'fmt': 'text',
            'system': '=== AVAILABLE TOOLS ===\n- GoToCharacter: Input: plain text\n- InteractWith: Input: plain text\n- Act: Input JSON: {"text":"action"}\n=== HOW TO USE TOOLS ===\n<tool name="ToolName">example</tool>', 'expect': {}}
    c = prepare_case(base)
    assert set(c['allowed_tools']) == {'GoToCharacter', 'InteractWith', 'Act'}
    r = score_case(c, '<tool name="GoToCharacter">Alex</tool>')
    assert r['tool_available'] is True and r['decision_correct'] == 'not_tested'
    assert score_case(c, '<tool name="Invented">x</tool>')['tool_available'] is False
    assert score_case(c, '<tool name="InteractWith">Alex</tool>')['tool_available'] is True
    r = score_case(c, '**Step 1 – Tool actions** → Tool: `GoToCharacter`')
    assert r['format_valid'] is False and r['hallucinated'] is False
    assert score_case(c, '**I feel calm**\n**I do stand: still**\n[INTENT: wait]\n<tool name="InteractWith">Alex</tool>')['format_valid'] is True
    assert score_case(c, '<tool name="InteractWith">Alex</tool>\nNONE')['format_valid'] is False
    assert score_case(c, '<tool name="Act">plain text</tool>')['args_valid'] is False
    assert score_case(c, '<tool name="Act">{"text":null}</tool>')['args_valid'] is False
    assert score_case(c, '<tool name="Act">{"text":"waves"}</tool>')['args_valid'] is True
    assert score_case(c, '[INTENT_DONE: demo]\n[INTENT_PROGRESS: demo | step]\nNONE')['format_valid'] is True
    conflict = prepare_case({**base, 'system': base['system'] + '\n<tool name="Act">plain input</tool>'})
    r = score_case(conflict, '<tool name="Act">plain input</tool>')
    assert r['fixture_conflict'] is True and r['args_valid'] == 'not_tested'
    assert r['ok'] is True and r['invalid_input'] is False  # still scored on format/availability
    assert score_case(conflict, '**Step 1** → Tool: `Act`')['ok'] is False
    placeholder = prepare_case({**base, 'system': base['system'] + '\n- <tool name="Act">[input]</tool>'})
    assert placeholder['fixture_conflict'] is False and placeholder['fixture_conflicts'] == []
    assert score_case(placeholder, '<tool name="Act">plain text</tool>')['args_valid'] is False
    assert score_case(c, '<tool name="Act">{"text":"As an AI researcher, I wave"}</tool>')['refusal'] is False
    assert score_case(c, 'Ich kann das nicht tun.')['refusal'] is True
    assert score_case(c, 'NONE', infra_error=True)['infra_error'] is True

    r = score_case(c, '**Step 1 – Tool actions** ...', finish_reason='length')
    assert r['ok'] is False and r['truncated'] is True and r['invalid_input'] is False
    assert r['hallucinated'] is False and r['refusal'] == 'not_tested'
    assert score_case(prepare_case({**base, 'system': '<tool name="ToolName">example</tool>'}), 'NONE')['invalid_input'] == 'invalid_fixture'
    for language in ('Leider ist keine Bilddatei vorhanden.', "I'm sorry, but I need to see the image"):
        r = score_case({'task': 'image_analysis', 'category': 'helper'}, language)
        assert r['invalid_input'] == 'missing_input' and r['ok'] is None and r['refusal'] == 'not_tested'
    r = score_case({'category': 'helper', 'fmt': 'json', 'expect': {'keys': ['x']}}, '{"x":1}')
    assert r['format_valid'] is True and r['semantic'] == 'not_tested'
    for c in semantic_cases():
        assert score_case(c, c['test_good'])['decision_correct'] is True, c['id']
        assert score_case(c, c['test_good'])['ok'] is True, c['id']
        assert score_case(c, c['test_bad'])['decision_correct'] is False, c['id']
    auto = next(c for c in semantic_cases() if c['id'] == 'semantic_autonomous')
    assert score_case(auto, auto['test_good'].replace('Alex', 'Other'))['required_action_missing'] is True
    assert score_case(auto, 'NONE')['required_action_missing'] is True
    print('Suitability semantics: all expectations hold.')

if __name__ == '__main__':
    main()
