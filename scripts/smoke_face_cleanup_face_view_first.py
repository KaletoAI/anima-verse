"""A174 item 1: "Run all" / "Re-apply face cleanup" never refuses a stale face view (A163).

Usage: ./.venv/bin/python scripts/smoke_face_cleanup_face_view_first.py

Hand-derived expectations:
- eligibility {reference 'face', problems [face_stale, no_source]} -> blocking = [no_source] (1 of 2 left)
- the same with reference 'front' -> both stay (face_stale on a front run is no face-view step: 2 left)
- trigger_face_cleanup with a stale face view and an otherwise runnable state starts (status 'generating')
  instead of the LookupError "The profile picture changed after the face view was rendered."
"""
import os, sys, tempfile, threading
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
tmp = tempfile.mkdtemp()
from app.core import paths
paths.init(tmp)
from app.core import face_retexture, model3d

stale = {'code': 'face_stale', 'message': 'The profile picture changed after the face view was rendered.'}
other = {'code': 'no_source', 'message': 'No retained unrigged mesh source.'}
fails = 0
def check(label, got, want):
    global fails
    ok = got == want
    fails += not ok
    print(('OK  ' if ok else 'FAIL'), label, got, '' if ok else f'(want {want})')

check('face source drops face_stale', face_retexture.blocking_problems({'reference': 'face', 'problems': [stale, other]}), [other])
check('front source keeps both', len(face_retexture.blocking_problems({'reference': 'front', 'problems': [stale, other]})), 2)

# trigger_face_cleanup end to end with stubs (no backend, no thread work).
model3d.face_cleanup_state = lambda c, s: {'running': False, 'can_reapply': True, 'follow_up': 'face_retexture', 'jobs': 3}
face_retexture.check = lambda c, s, *a, **k: {'reference': 'face', 'problems': [stale]}
face_retexture.runnable = lambda c, b='': {'ok': True, 'problems': []}
class Q:
    def track_start(self, *a, **k): return 't1'
    def track_finish(self, *a, **k): pass
import app.core.task_queue as tq
tq.get_task_queue = lambda: Q()
model3d.run_face_cleanup = lambda *a, **k: {'ok': True}
try:
    res = model3d.trigger_face_cleanup('Demo', 'a' * 16)
    check('stale face view starts the run', res.get('status'), 'generating')
except LookupError as e:
    check('stale face view starts the run', f'LookupError: {e}', 'generating')
for t in threading.enumerate():
    if t is not threading.current_thread() and t.daemon:
        t.join(2)
print('FAILED' if fails else 'ALL OK')
sys.exit(1 if fails else 0)
