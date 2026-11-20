"""Usage: ./.venv/bin/python scripts/smoke_llm_continuation_template.py

The prefill of a capped thought must survive the server's chat template
(2026-11-20, vLLM 400 "continue_final_message is set but the final message
does not appear in the chat after applying the chat template").

Template: shared/test-vectors/chat_templates/sensenova_loop_9b.jinja — the
chat template of SenseNova-Loop-9B-Preview as shipped in its GGUF metadata
(Qwen3 layout), rendered the way transformers does (sandboxed Jinja,
trim_blocks + lstrip_blocks). The server's rule, as in
transformers.apply_chat_template(continue_final_message=True):
final_message.strip() must occur in the rendered prompt.

By hand from the template: an assistant message after the last user turn is
rendered as '<|im_start|>assistant\n<think>\n' + thought|trim +
'\n</think>\n\n' + answer.lstrip('\n'), the whole content trimmed first.
So with thought "R":
  answer ""      -> prompt ends '<think>\nR\n</think>\n\n<|im_end|>\n'
  answer "x"     -> prompt ends '<think>\nR\n</think>\n\nx<|im_end|>\n'
  answer "\n\nx" -> the same as "x": the two line breaks are gone.
The cause: the old prefill '<think>\nR\n</think>\n\n' + '\n\nx' (four line
breaks) is NOT in that prompt. A thought "a</think>b" or "a<think>b" is split
by the template and not found either.

The client therefore sends '<think>\nR\n</think>\n\n' + answer.lstrip() for
answers "", "x", "\n\nx", for a thought with white space around it and for a
raw thought in the content ('<think>\n\n  R ') — each found in the prompt,
and "x" + continuation "done" = "xdone". A thought or begun answer with a
marker is not sent: the play client answers that one call without thinking
(2 calls, nothing remembered), the isolated test client fails it
(1 call, continuation_failed, no error text since no server refused).
"""
import copy
import sys
from pathlib import Path
from types import SimpleNamespace as NS
from jinja2.sandbox import ImmutableSandboxedEnvironment
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.core import llm_client as llm

TEMPLATE = (ROOT / 'shared/test-vectors/chat_templates/sensenova_loop_9b.jinja').read_text()


def raise_exception(message):
    raise ValueError(message)


def render(prefill):
    env = ImmutableSandboxedEnvironment(trim_blocks=True, lstrip_blocks=True)
    env.globals['raise_exception'] = raise_exception
    return env.from_string(TEMPLATE).render(messages=[
        dict(role='system', content='S'), dict(role='user', content='ping'),
        dict(role='assistant', content=prefill)], add_generation_prompt=False)


def continues(prefill):
    return prefill.strip() in render(prefill)


def response(content='', reasoning=None, finish='stop'):
    return NS(usage=None, choices=[NS(finish_reason=finish,
              message=NS(content=content, reasoning_content=reasoning))])


def client_for(responses):
    client = llm.LLMClient('sensenova-loop-9b-awq', 'k', 'http://fake/v1', max_tokens=900,
                           thinking=True, thinking_budget=300)
    calls = []
    def create(**kwargs):
        calls.append(copy.deepcopy(kwargs))
        return responses.pop(0)
    client._sync = NS(chat=NS(completions=NS(create=create)))
    return client, calls


def main():
    head = '<|im_start|>system\nS<|im_end|>\n<|im_start|>user\nping<|im_end|>\n<|im_start|>assistant\n'
    base = '<think>\nR\n</think>\n\n'
    # The template itself, by hand.
    assert render(base) == head + base + '<|im_end|>\n', render(base)
    assert render(base + 'x') == head + base + 'x<|im_end|>\n'
    assert render(base + '\n\nx') == head + base + 'x<|im_end|>\n'
    # The cause: what the client used to send is not in the prompt.
    assert not continues(base + '\n\nx')
    assert not continues('<think>\na</think>b\n</think>\n\n')
    assert not continues('<think>\na<think>b\n</think>\n\n')
    # What the client sends now.
    for content, reasoning, expected, answer in [
            ('', 'R', base, 'done'), ('x', 'R', base + 'x', 'xdone'),
            ('\n\nx', 'R', base + 'x', 'xdone'), ('\n\nx', '\n R \n', base + 'x', 'xdone'),
            ('<think>\n\n  R ', None, base, 'done')]:
        llm._NO_CONTINUE.clear()
        client, calls = client_for([response(content, reasoning, 'length'), response('done')])
        result = client.invoke('ping')
        prefill = calls[1]['messages'][-1]['content']
        assert prefill == expected, (content, reasoning, prefill)
        assert continues(prefill), prefill
        assert result.content == answer and result.reasoning.strip() == 'R' and result.budget_hit, result
        assert calls[1]['extra_body']['continue_final_message'] is True
    # A marker inside the thought or the begun answer: never sent.
    for content, reasoning in [('', 'a</think>b'), ('', 'a<think>b'), ('x</think>y', 'R')]:
        llm._NO_CONTINUE.clear()
        llm._NO_CONTINUE_STRIKES.clear()
        client, calls = client_for([response(content, reasoning, 'length'), response('plain')])
        result = client.invoke('ping')
        assert result.content == 'plain' and result.budget_unenforceable and len(calls) == 2
        assert calls[1]['extra_body']['chat_template_kwargs']['enable_thinking'] is False
        assert 'continue_final_message' not in calls[1]['extra_body']
        assert not llm._NO_CONTINUE and not llm._NO_CONTINUE_STRIKES
        client, calls = client_for([response(content, reasoning, 'length')])
        client.isolate_server_state(set())
        failed = client.invoke('ping')
        assert failed.continuation_failed and failed.continuation_error is None and len(calls) == 1
        assert failed.continuation_reason == 'the capped thought contains a thought marker, not sent'
        assert not llm._NO_CONTINUE
    print('Continuation prefill survives the SenseNova/Qwen3 template; marker thoughts are not sent OK')


if __name__ == '__main__':
    main()
