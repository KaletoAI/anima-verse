#!/usr/bin/env python3
"""Task 9/D7 smoke. Usage: .venv/bin/python scripts/smoke_clip_revision.py

Hand oracle: unchanged files yield the same 40-character SHA1. Adding one
sidecar adds a stat tuple; rewriting it and reloading changes that tuple.
A transition save changes the seed mtime, and a world edit — including deleting an older rule — changes the hashed rows.
Each reload/save sends exactly one clips/Everyone signal; invalid saves send zero.
A settled library reuses its file digest. Both libraries count, even hidden twins.
All libraries, storage and transition seeds are temporary.
"""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        os.environ['ANIMATION_CLIPS_DIR'] = str(root / 'free')
        os.environ['ANIMATION_CLIPS_LICENSED_DIR'] = str(root / 'licensed')
        from app.core import paths
        paths.init(root / 'world')
        from app.core import db, animation_clips as clips, sync_topics
        db.init_schema()
        for name in ('free', 'licensed'):
            (root / name).mkdir()
            (root / name / 'walk.fbx').write_bytes(b'fixture')
        with patch.object(clips, 'clip_transitions_path', return_value=root / 'transitions.json'), patch.object(sync_topics, 'notify') as notify:
            first = clips.library_revision()
            assert len(first) == 40 and first == clips.library_revision()
            sidecar = root / 'free' / 'walk.json'
            sidecar.write_text('{}')
            second = clips.library_revision()
            assert second != first
            sidecar.write_text('{"loop": false}')
            clips.reload_clip_caches()
            assert clips.library_revision() != second
            notify.assert_called_once_with('clips', to=sync_topics.Everyone())
            notify.reset_mock()
            before = clips.library_revision()
            clips.save_transitions([])
            assert clips.library_revision() != before
            notify.assert_called_once_with('clips', to=sync_topics.Everyone())
            notify.reset_mock()
            before = clips.library_revision()
            with db.transaction() as conn:
                conn.execute("INSERT INTO clip_transitions_world (from_pose,to_pose,kind,accel,updated_at) VALUES ('standing','walking','walk',0,'fixture')")
            assert clips.library_revision() != before
            # Deleting an OLDER world rule leaves MAX(updated_at) alone; the
            # revision must still move (it hashes the rows).
            with db.transaction() as conn:
                conn.execute("INSERT INTO clip_transitions_world (from_pose,to_pose,kind,accel,updated_at) VALUES ('sitting','standing','get-up-chair',0,'a-older')")
            before = clips.library_revision()
            with db.transaction() as conn:
                conn.execute("DELETE FROM clip_transitions_world WHERE updated_at='a-older'")
            assert clips.library_revision() != before
            try:
                clips.save_transitions(None)
            except clips.ClipLibraryError:
                pass
            else:
                raise AssertionError('invalid save accepted')
            notify.assert_not_called()
            # Both the shadowed free FBX and a licensed set sidecar count.
            for path in (root / 'free' / 'walk.fbx', root / 'licensed' / 'female' / 'walk.json'):
                before = clips.library_revision()
                path.parent.mkdir(exist_ok=True)
                path.write_bytes(b'changed fixture')
                clips.reload_clip_caches()
                assert clips.library_revision() != before
            from app.routes.assets import list_animation_clips
            assert list_animation_clips()['revision'] == clips.library_revision()
            # Reload finishes before the notification, including under the writer lock.
            with patch('app.core.expression_pose_maps.reload_presets') as reload:
                def check_notify(*args, **kwargs):
                    reload.assert_called_once_with()
                with patch.object(sync_topics, 'notify', side_effect=check_notify):
                    with clips.library_write_lock(root / 'free'):
                        clips.reload_clip_caches()
            for name in ('free', 'licensed'):
                os.utime(root / name, ns=(1_000_000_000, 1_000_000_000))
            os.utime(root / 'licensed' / 'female', ns=(1_000_000_000, 1_000_000_000))
            settled = clips.library_revision()
            with patch.object(clips, '_revision_files', side_effect=AssertionError('hot-path scan')):
                assert clips.library_revision() == settled
        print('clip revision: all checks passed')


if __name__ == '__main__':
    main()
