#!/usr/bin/env python3
"""Usage: ./.venv/bin/python scripts/smoke_instagram_render_error.py

A post whose image render FAILS reports the render's real reason instead of
"image was generated, but the file name could not be extracted"
(plugins/instagram/skill_post.py ``execute``).

Hand-derived expectations, every world access patched out:
a. The image service returns the error RESULT
   "Error: Qwen2.1 UC Turbo: request error (HTTP 400): ... no reference-image inputs"
   -> the tool answers "Error: the post image could not be generated: " + that
   text, the task track finishes with that text as its error, and no post is
   created.
b. The answer counts as a failure for the shared boundary
   (``streaming.is_error_result``), so the narrator's "tries, but it does not
   work out" still follows; the reason is now the real one.
"""
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FAILURE = ('Error: Qwen2.1 UC Turbo: request error (HTTP 400): '
           '{"detail":"\'Qwen2.1-UC-Turbo\' has no reference-image inputs"}')


class Service:
    def generate_from_input(self, raw):
        return FAILURE


class Queue:
    def __init__(self):
        self.finished = []

    def track_start(self, *args, **kwargs):
        return "track_1"

    def track_finish(self, track_id, error=None, **kwargs):
        self.finished.append((track_id, error))


def main():
    with tempfile.TemporaryDirectory(prefix="insta-render-error-") as tmp:
        from app.core import paths
        paths.init(tmp)
        from plugins.instagram import skill_post as M
        from app.core.streaming import is_error_result

        skill = object.__new__(M.InstagramSkill)
        queue = Queue()
        posts = []
        with patch.object(M.InstagramSkill, "_get_effective_config", lambda self, name: {"post_cooldown_hours": 0}), \
                patch.object(M.InstagramSkill, "_get_image_skill", lambda self: Service()), \
                patch.object(M.InstagramSkill, "_parse_input", lambda self, raw: {
                    "image_prompt": "a mirror selfie", "caption": "", "agent_name": "Mia", "user_id": ""}), \
                patch.object(M, "get_task_queue", return_value=queue), \
                patch.object(M, "get_character_current_location", return_value=""), \
                patch.object(M, "get_effective_activity", return_value=""), \
                patch.object(M, "get_character_appearance", return_value=""), \
                patch.object(M, "list_available_characters", return_value=["Mia"]), \
                patch.object(M, "create_post", side_effect=lambda *a, **k: posts.append(1)):
            answer = skill.execute("{}")
        assert answer == f"Error: the post image could not be generated: {FAILURE}", answer
        assert queue.finished == [("track_1", FAILURE)], queue.finished
        assert posts == []
        print("PASS a: the render's own reason is reported, no post is made")
        assert is_error_result(answer)
        print("PASS b: the answer is still a failure for the narrator")


if __name__ == "__main__":
    main()
