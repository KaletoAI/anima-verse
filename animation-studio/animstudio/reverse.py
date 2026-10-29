"""Build a bridge from a finished, license-free solo clip."""
import json
import math
from dataclasses import asdict
from pathlib import Path

import animstudio
from animstudio import StudioError
from animstudio.checks import Check, FLOOR_CM, MIN_TRACKS, _require


def source_clip(anim):
    from app.core import paths
    from app.core.animation_clips import validate_kind, ClipLibraryError
    try:
        validate_kind(anim.kind)
        validate_kind(anim.source)
    except ClipLibraryError as e:
        raise StudioError(str(e)) from e
    lib = paths.get_animation_clips_dir().resolve()
    fbx = lib / f'{anim.source}.fbx'
    side = lib / f'{anim.source}.json'
    try:
        meta = json.loads(side.read_text(encoding='utf-8'))
    except (OSError, ValueError) as e:
        raise StudioError('Reversed requires a source in the license-free library') from e
    if meta.get('pair') or '__' in anim.source:
        raise StudioError('Reversed refuses pair clips')
    if meta.get('loop'):
        raise StudioError('Reversed refuses looped clips')
    if not fbx.is_file() or not fbx.resolve().is_relative_to(lib) or not side.resolve().is_relative_to(lib):
        raise StudioError('Reversed requires a license-free source FBX and sidecar')
    return fbx, side, meta


def build_reversed(anim, sha):
    from app.blender import runner
    from app.core import paths
    fbx, side, original = source_clip(anim)
    out = animstudio.OUT / anim.kind
    out.mkdir(parents=True, exist_ok=True)
    res = runner.run('reverse_clip', inputs={'src': fbx, 'sidecar': side,
                     'rig': paths.get_rig_file()}, params={'kind': anim.kind,
                     'source': anim.source, 'spec_sha': sha}, out_dir=out, timeout_s=900)
    if not res['ok']:
        raise StudioError(f"reverse_clip failed: {res['error']}")
    meta = json.loads(Path(res['outputs']['sidecar']).read_text())
    measure = json.loads(Path(res['outputs']['measure']).read_text())
    frames = measure['frames']
    _require(frames)
    bad = [k for k in ('fps', 'frames', 'duration_s') if meta.get(k) != original.get(k)]
    fps, n = meta.get('fps'), meta.get('frames')
    if n != len(frames) or not isinstance(fps, (int, float)) or fps <= 0:
        bad.append('measured frames/fps')
    elif abs(meta['duration_s'] - round(n / fps, 3)) > 1e-9:
        bad.append('duration_s != frames / fps')
    if meta.get('loop') is not False or meta.get('pair') is not False or meta.get('kind') != anim.kind:
        bad.append('kind/loop/pair')
    low = min(p[1] for f in frames for p in f.values())
    motion = meta['geometry']['root_motion']
    source_motion = original.get('geometry', {}).get('root_motion', {})
    expected = ([0, 0] if source_motion.get('mode', 'strip') == 'strip' else
                [-v for v in source_motion['travel_m']])
    error = math.dist(motion['travel_m'], expected)
    checks = [Check('sidecar', not bad, len(bad), '0 mismatches', '; '.join(bad)),
              Check('floor', low >= FLOOR_CM, round(low, 2), f'>= {FLOOR_CM} cm'),
              Check('tracks', measure['tracks'] >= MIN_TRACKS, measure['tracks'], f'>= {MIN_TRACKS}'),
              Check('bridge_travel', motion['mode'] == 'keep' and error <= .01,
                    error, '<= 0.01 m', f'expected {expected}')]
    report = {'kind': anim.kind, 'spec_sha': sha, 'ok': all(c.ok for c in checks),
              'checks': [asdict(c) for c in checks], 'fbx': res['outputs'][anim.kind],
              'sidecar': res['outputs']['sidecar']}
    (out / 'build.json').write_text(json.dumps(report, indent=1), encoding='utf-8')
    return report
