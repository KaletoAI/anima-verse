#!/usr/bin/env python3
"""Check request fidelity and persistent LLM-log comparisons.

Usage:
    ./.venv/bin/python scripts/smoke_llm_log_replay.py

No server or external provider. All storage and log writes use a temporary
folder, initialised before importing DB-aware application modules.

Hand-derived expectations from the replay contract:
* A streaming log contains history separately from its final user turn.
  Replay must send system, old user, old assistant, final user, in that order;
  a suffix already in the logged final turn must appear exactly once.
* Old queued '[user] ' formatting is not prompt content. A single-user call
  loses that prefix; multiple flattened roles cannot be replayed faithfully.
* Exact request messages take precedence over lossy display text, preserving
  image blocks and tool-call roles/IDs instead of flattening them.
* Replays are additional responses, not original requests. Two comparison
  records before/after a source in file order still belong to that one
  source. Adding another comparison never changes the source identifier.
  Filtering and pagination operate on original requests, not comparison rows.
* The queue logger must preserve the actual messages before constructing its
  human-readable summary; otherwise fresh calls would have the same ambiguity
  as historical multi-message logs.
"""
import copy
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main():
    with tempfile.TemporaryDirectory(prefix="llm-log-replay-") as temporary:
        root = Path(temporary)
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "instance")
        from app.core.llm_log_replay import (
            ReplayUnavailable, entry_id, group_entries, request_messages,
        )
        from app.routes import logs
        from app.utils import llm_logger
        from app.core.provider_queue import _log_task_result
        from app.core.llm_queue import LLMTask
        from app.core.llm_client import LLMResponse

        original = {
            "starttime": "2026-10-16T10:00:00+00:00", "task": "chat_stream",
            "provider": "original-provider", "model": "original-model",
            "trace_id": "original-trace", "response": "Original answer",
            "prompt": {
                "system": "System\nKeep whitespace. ",
                "messages": [
                    {"role": "user", "content": "Earlier question"},
                    {"role": "assistant", "content": "Earlier answer"},
                ],
                "user": "Current question\nAlready appended suffix",
            },
        }
        assert request_messages(original) == [
            {"role": "system", "content": "System\nKeep whitespace. "},
            {"role": "user", "content": "Earlier question"},
            {"role": "assistant", "content": "Earlier answer"},
            {"role": "user", "content": "Current question\nAlready appended suffix"},
        ]
        queued = {"prompt": {"system": "Rules", "user": "[user] Question\nNext line"}}
        assert request_messages(queued) == [
            {"role": "system", "content": "Rules"},
            {"role": "user", "content": "Question\nNext line"},
        ]
        for prompt in (
            {"system": "Rules", "user": "[user] One\n[assistant] Two\n[user] Three"},
            {},
        ):
            try:
                request_messages({"prompt": prompt})
            except ReplayUnavailable:
                pass
            else:
                raise AssertionError("Missing/ambiguous historical request was replayable")
        print("PASS: historical history ordering, suffix fidelity and ambiguity boundary")

        exact = [
            {"role": "system", "content": "Rules"},
            {"role": "user", "content": [
                {"type": "text", "text": "Inspect this"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}},
            ]},
            {"role": "assistant", "content": None, "tool_calls": [
                {"id": "call-demo", "type": "function", "function": {"name": "inspect", "arguments": "{}"}},
            ]},
            {"role": "tool", "tool_call_id": "call-demo", "content": "Found"},
            {"role": "user", "content": "Continue"},
        ]
        exact_entry = {"prompt": {"request_messages": exact, "user": "Lossy display text"}}
        assert request_messages(exact_entry) == exact
        print("PASS: authoritative multimodal/tool message structure overrides display text")

        source_id = entry_id(original)
        before = copy.deepcopy(original)
        first = {"replay_of": source_id, "response": "First comparison", "model": "model-a"}
        second = {"replay_of": source_id, "response": "Second comparison", "model": "model-b"}
        other = {"task": "intent", "model": "other", "prompt": {"user": "Other request"}}
        rows = group_entries([first, original, other, second])
        assert len(rows) == 2
        source = next(row for row in rows if row["entry_id"] == source_id)
        assert [row["response"] for row in source["comparisons"]] == ["First comparison", "Second comparison"]
        assert original == before
        assert entry_id(original) == source_id
        assert source["replay_available"] is True

        logs.LOG_FILE = root / "llm_calls.jsonl"
        logs.LOG_FILE.write_text("\n".join(json.dumps(row) for row in [first, original, other, second]) + "\n", encoding="utf-8")
        page = logs.llm_log_data(limit=1, offset=0, task="chat_stream", model="", character="", provider="", errors_only=False, search="")
        assert page["total"] == 1 and page["trace_totals"] == {"original-trace": 1}
        assert [row["model"] for row in page["entries"][0]["comparisons"]] == ["model-a", "model-b"]
        print("PASS: durable comparison grouping, original identity, filters and pagination")

        llm_logger.LOG_DIR = root
        llm_logger.LOG_FILE = root / "queue-log.jsonl"
        client = SimpleNamespace(temperature=0.0, model="new-model", max_tokens=None)
        task = LLMTask(task_id="demo", task_type="log_replay", priority=20,
                       agent_name="", created_at="", provider_name="demo",
                       _messages=exact, _llm=client)
        _log_task_result(task, "new-model", 0, LLMResponse(content="Answer"))
        logged = json.loads(llm_logger.LOG_FILE.read_text(encoding="utf-8"))
        assert logged["prompt"]["request_messages"] == exact
        assert logged["sampler"]["temperature"] == 0.0
        assert request_messages(logged) == exact
        print("PASS: new queue logs retain replayable multimodal and tool history")
    print("All LLM-log replay checks passed.")


if __name__ == "__main__":
    main()
