#!/usr/bin/env python3
"""Usage: ./.venv/bin/python scripts/smoke_locomotion_clips.py

[transitions] Hand-derived specificity: exact sit->walk beats sit->*,
which beats *->walk. Unruled and identical poses have no bridge. A group
target is a literal key here, so walking->@seat never matches sitting;
only the prop entry caller performs the separate catalog-group lookup.
"""
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
with tempfile.TemporaryDirectory(prefix='locomotion-clips-') as temporary:
    os.environ.update(STORAGE_DIR=temporary, INSTANCE_DIR=temporary,
                      ANIMATION_CLIPS_DIR=str(Path(temporary) / 'clips'))
    from app.core import paths
    paths.init(temporary)
    paths.init_instance(temporary)
    from app.core.animation_clips import resolve_transition
    rules = [{'from': '*', 'to': 'walk', 'kind': 'stroll'},
             {'from': 'sit', 'to': '*', 'kind': 'idle'},
             {'from': 'sit', 'to': 'walk', 'kind': 'run'},
             {'from': 'walking', 'to': '@seat', 'kind': 'entry'}]
    for src, dst, expected in [('sit', 'walk', 'run'), ('sit', 'jog', 'idle'),
                               ('idle', 'walk', 'stroll'), ('idle', 'jog', None),
                               ('walk', 'walk', None), ('  SIT ', 'WALK', 'run'),
                               ('', 'walk', None), ('walking', 'sitting', None),
                               ('walking', '@seat', 'entry')]:
        result = resolve_transition(src, dst, rules)
        assert (result['kind'] if result else None) == expected, (src, dst, result)
    print('[transitions] 9 hand-derived cases passed')
