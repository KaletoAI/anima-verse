"""Concurrent suitability, speed, live-play and real image payload checks.

Usage: ./.venv/bin/python scripts/smoke_suitability_speed.py

Hand-derived: six one-second calls at three workers take two seconds (<3).
A provider max_concurrent of 1 caps three requested workers to one; an
unreviewed log candidate is never sent. Thought/state/facts
medians 6+4+5 = 15 seconds: passes 20, fails 10. One passing vision case
out of three is below 70%. Running and unfrozen means live play. A JPEG
case sends one image; a missing file sends zero requests; WEBP keeps its MIME.
All storage is temporary and provider calls are fake.
"""
import copy
import json
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.core import paths


def main():
    with tempfile.TemporaryDirectory() as tmp:
        paths.init(tmp)
        from app.core import model_suitability as suit
        from app.core.suitability_scoring import curated_cases
        from scripts.smoke_suitability_semantics import ANSWERS
        base = copy.deepcopy(curated_cases()[0])
        base["repeats"] = 1
        answer = ANSWERS[base["id"]][0]
        client = SimpleNamespace(invoke=lambda messages: SimpleNamespace(
            content=answer, finish_reason="stop", usage={"completion_tokens": 12}))
        instance = SimpleNamespace(available=True, provider_name="fake", model="demo",
                                   create_llm=lambda **kw: client)

        def run(cases, lanes=3, concurrency=3, limit=20):
            with patch.object(suit, "load_cases", return_value={"cases": cases}), \
                 patch("app.core.config.get", side_effect=lambda key, default=None:
                       limit if key == "model_test.max_turn_seconds" else
                       [{"name": "fake", "max_concurrent": lanes}] if key == "providers" else default):
                return list(suit.iter_suitability_results("fake::demo", concurrency=concurrency,
                    routing_entry={"provider": "fake", "model": "demo", "max_concurrent": lanes}))[-1]["summary"]

        with patch("app.core.llm_router.create_llm_instance", return_value=instance), \
             patch.object(suit, "_persist", return_value=True), \
             patch("app.core.agent_loop.get_agent_loop", return_value=SimpleNamespace(status=lambda: {"running": True})), \
             patch("app.models.world.is_world_frozen", return_value=False):
            def slow(messages):
                time.sleep(1)
                return SimpleNamespace(content=answer, usage={"completion_tokens": 12})
            with patch.object(client, "invoke", side_effect=slow):
                start = time.monotonic()
                summary = run([{**base, "id": str(i)} for i in range(6)])
                assert time.monotonic() - start < 3
                assert summary["concurrency"] == 3
            print("[1] Six one-second calls run in under three seconds OK")
            assert run([base], lanes=1)["concurrency"] == 1
            print("[2] Provider max_concurrent caps effective concurrency OK")
            sent = []
            with patch.object(client, "invoke", side_effect=lambda m: sent.append(m) or SimpleNamespace(
                    content=answer, finish_reason="stop", usage={"completion_tokens": 12})):
                done = run([base, {**base, "id": "log_x", "reviewed": False}])
            assert len(sent) == 1 and [c["id"] for c in done["checks"]] == [base["id"]], done["checks"]
            print("[2b] Unreviewed log candidate is not sent OK")
            # Repetitions of a single case can occupy all three workers.
            barrier = threading.Barrier(3)
            def repeated(messages):
                barrier.wait(timeout=2)
                return SimpleNamespace(content=answer)
            with patch.object(client, "invoke", side_effect=repeated):
                assert run([{**base, "repeats": 3}])["score"] == "1/1"
            # A single invented tool invalidates the zero-invention requirement.
            answers = iter([answer, answer, '<tool name="Invented">{}</tool>'])
            with patch.object(client, "invoke", side_effect=lambda messages:
                              SimpleNamespace(content=next(answers))):
                invented = run([{**base, "repeats": 3}], lanes=1)
                assert invented["hallucinations"] == 1 and invented["verdict"] == "no — tools"
            # Pure summary input fixes latencies without faking the runner clock.
            def record(group, task, latency, ok=True):
                return {"group": group, "task": task, "category": "tool" if group == "tools" else "helper",
                        "ok": ok, "hallucinated": False, "duration_s": latency,
                        "runs": [{"duration_s": latency, "usage": {"completion_tokens": 30}}],
                        "run_checks": [{"decision_correct": True}]}
            records = [record("tools", "thought", 6), record("helpers", "extraction_chat_state", 4),
                       record("helpers", "extraction", 5), record("vision", "image_analysis", 2)]
            with patch("app.core.config.get", return_value=20):
                summary = copy.deepcopy(suit._summarize("fake::demo", records))
                assert summary["projected_turn_s"] == 15 and summary["verdict"] == "yes"
                assert summary["speed"]["helpers"]["median_latency_s"] == 4.5
                assert summary["speed"]["helpers"]["tok_s"] == 6.7
            with patch("app.core.config.get", return_value=10):
                assert suit._summarize("fake::demo", records)["verdict"] == "no — speed"
            print("[3] Projected 15-second turn passes 20 and fails 10 OK")
            summary.update(concurrency=3, live_play=True)
            records += [record("vision", "image_analysis", 2, False) for _ in range(2)]
            assert suit._summarize("fake::demo", records)["verdict"] == "no — vision"
            print("[4] Vision one out of three fails single-helper verdict OK")
            assert run([base])["live_play"] is True
            with patch("app.models.world.is_world_frozen", return_value=True):
                assert run([base])["live_play"] is False
            with patch("app.core.agent_loop.get_agent_loop", return_value=SimpleNamespace(status=lambda: {"running": False})):
                assert run([base])["live_play"] is False
            # Live play can start after the provider request has begun.
            loop = SimpleNamespace(status=lambda: {"running": True})
            with patch("app.core.agent_loop.get_agent_loop", return_value=loop),                  patch.object(loop, "status", side_effect=[{"running": False}, {"running": True}]):
                assert run([base])["live_play"] is True
            print("[5] Live play is recorded OK")
            image = Path(tmp) / "sample.JPG"
            image.write_bytes(b"image payload")
            vision = {"id": "vision", "task": "image_recognition", "group": "vision", "fmt": "text",
                      "system": "system", "user": "describe", "image": str(image), "repeats": 1}
            sent = []
            def capture(messages):
                sent.append(messages)
                return SimpleNamespace(content="A person is here.")
            with patch.object(client, "invoke", side_effect=capture):
                result = run([vision, {**vision, "id": "missing", "image": str(image) + ".missing"}])
            assert len(sent) == 1
            parts = sent[0][1]["content"]
            assert parts[0] == {"type": "text", "text": "describe"}
            assert len(parts) == 2 and parts[1]["type"] == "image_url"
            assert parts[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
            assert result["checks"][1]["invalid_input"] == "missing_input"
            print("[6] Vision sends one JPEG image; missing image sends nothing OK")
            from app.core.vision_message import image_user_content
            webp = Path(tmp) / "sample.webp"
            webp.write_bytes(b"webp payload")
            assert image_user_content("describe", webp)[1]["image_url"]["url"].startswith("data:image/webp;base64,")
            try:
                image_user_content("describe", webp.with_suffix(".missing"))
            except FileNotFoundError:
                pass
            else:
                raise AssertionError("Missing image did not raise")
            print("[7] Shared helper preserves WEBP MIME and missing-file error OK")
            print("Fake run summary: " + json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
