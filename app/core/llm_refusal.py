"""Live-configured refusal detection and instance-wide refusal counters."""
import json
import re
import threading
from datetime import timedelta
from typing import Optional

from app.core import config, paths
from app.core.log import get_logger
from app.core.timeutils import utc_now, parse_iso

logger = get_logger("llm_refusal")
_lock = threading.Lock()


class RefusalError(RuntimeError):
    """The call exhausted its eligible uncensored fallback models."""

    def __init__(self, provider: str, model: str, task: str, excerpt: str):
        self.provider, self.model, self.task = provider, model, task
        self.excerpt = excerpt[:200]
        super().__init__(f"LLM refusal: {provider}/{model} task={task} — {self.excerpt}")


def _setting(name: str) -> str:
    """The live value, else the schema default: the instance config stores
    only deviations from the shipped default, so an untouched field is absent.
    A field the user cleared is stored as '' and disables detection."""
    value = config.get('llm_refusal.' + name)
    if value is None:
        from app.core.config_schema import field_default
        value = field_default('llm_refusal', name)
    return value if isinstance(value, str) else ''


def detect_refusal(text: str) -> Optional[str]:
    text = text.strip()
    if text.startswith(('{', '[', '```')):
        return None
    text = re.sub(r'^[A-Z][A-Za-z ]{0,15}:\s*', '', text, count=1)
    first = re.split(r'[.!?\n]', text[:300], maxsplit=1)[0].casefold()
    start = text[:400].casefold()
    phrases = _setting('phrases')
    reasons = _setting('reasons')
    if (any(p.strip().casefold() in first for p in phrases.splitlines() if p.strip())
            and any(r.strip().casefold() in start for r in reasons.splitlines() if r.strip())):
        return text[:200]
    return None


def checks_refusals(task: str) -> bool:
    from app.core.llm_tasks import TASK_TYPES
    return TASK_TYPES.get(task, {}).get('category') != 'chat'


def record_refusal(*, provider: str, model: str, task: str, routing_task: str,
                   excerpt: str, agent: str = '') -> None:
    row = dict(ts=utc_now().isoformat(), provider=provider, model=model, task=task,
               routing_task=routing_task, agent=agent, excerpt=excerpt[:200])
    logger.warning('LLM refusal: %s/%s task=%s — %s', provider, model, task, excerpt[:120])
    try:
        with _lock:
            path = paths.get_llm_refusals_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('a', encoding='utf-8') as handle:
                handle.write(json.dumps(row, ensure_ascii=False) + '\n')
    except OSError as exc:
        logger.warning('Cannot write refusal log: %s', exc)


def refusal_counts(hours: int = 48) -> dict:
    from app.core.llm_tasks import TASK_TYPES
    task_ids = set(TASK_TYPES)
    result = {'models': {}, 'tasks': {}}
    cutoff = utc_now() - timedelta(hours=hours)
    try:
        with _lock, paths.get_llm_refusals_path().open(encoding='utf-8') as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                    fields = ('ts', 'task', 'routing_task', 'provider', 'model', 'excerpt')
                    if not isinstance(row, dict) or any(not isinstance(row.get(k), str) for k in fields):
                        continue
                    stamp = parse_iso(row['ts'])
                    if stamp is None or stamp < cutoff:
                        continue
                    recent = {key: row[key] for key in ('ts', 'task', 'provider', 'model', 'excerpt')}
                    # A catalog task counts on its own row (image_pose_check, not
                    # the image_prompt chain it borrows); an unlisted call type
                    # (image_analysis, tool) counts on the task whose chain it used.
                    task_key = row['task'] if row['task'] in task_ids else row['routing_task']
                    keys = [('models', row['model'].lower()), ('tasks', task_key)]
                    for group, key in keys:
                        entry = result[group].setdefault(key, {'count': 0, 'recent': []})
                        entry['count'] += 1
                        entry['recent'].append(recent)
                        entry['recent'].sort(key=lambda r: parse_iso(r['ts']), reverse=True)
                        del entry['recent'][3:]
                except (ValueError, KeyError, TypeError, AttributeError):
                    continue
    except OSError:
        pass
    return result
