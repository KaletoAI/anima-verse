"""Real Blender integration; run by the controller, never by the implementer.

Usage: ./.venv/bin/python scripts/smoke_house_build_blender.py
A 6 x 9 m wall outline centred at zero has x extrema -3,+3 and z extrema
-4.5,+4.5. Three storeys at 3 m have floors at 0,3,6 m. The front awning
extends only toward +z, but symmetric keepers must make the exported box
centre (0,0) in xz within 0.02 m for both tiers, with and without the awning.
Shell parts are checked before material merging destroys their wall tags;
the exported GLBs are independently measured with node transforms applied.
All storage is temporary, initialized before importing any world modules.
"""
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    from app.core import paths
    with tempfile.TemporaryDirectory(prefix='smoke-house-blender-') as temp:
        root = Path(temp)
        paths.init(root)
        paths.init_instance(root / 'instance')
        from app.blender import runner
        from app.core import props, house_props as hp, hull_model
        assert runner.is_available(), 'Supported Blender is required'
        pid = props.create_prop(name='Blender house smoke', width_m=6, depth_m=9, height_m=9)['id']
        second = props.add_variant(pid)
        assert second == 1
        build_hull = hull_model.build_hull
        for variant, awning in ((0, True), (1, False)):
            props.set_variant_dims(pid, variant, {'width_m': 6, 'depth_m': 9, 'height_m': 9})
            hp.set_house_spec(pid, variant, {'style': 'steinhaus', 'storeys': 3,
                'storey_m': 3, 'overrides': {'shopfront': awning}})
            observed = set()
            def capture(*args, **kwargs):
                geometry = build_hull(*args, **kwargs)
                points = [v for part in geometry['parts'] if part['tag'] == 'wall'
                          for v in part['vertices']]
                assert points
                extents = [min(v[0] for v in points), max(v[0] for v in points),
                           min(v[2] for v in points), max(v[2] for v in points)]
                assert all(abs(a-b) <= .02 for a, b in zip(extents, [-3, 3, -4.5, 4.5])), extents
                if awning:
                    assert any(part['tag'] == 'awning' for part in geometry['parts'])
                observed.add(kwargs['tier'])
                return geometry
            with patch.object(hull_model, 'build_hull', side_effect=capture):
                result = hp.build_house_variant(pid, variant)
            assert result['ok'], result
            assert observed == {'full', 'low'}
            gallery = props.model_gallery(pid, variant)
            for tier in ('full', 'low'):
                file = gallery.find(tier, fallback=False)
                assert file and file.is_file(), (variant, tier)
                bounds = props.glb_bounds(file.read_bytes())
                assert bounds is not None
                lo, hi = bounds
                assert abs((lo[0]+hi[0])/2) <= .02, bounds
                assert abs((lo[2]+hi[2])/2) <= .02, bounds
        print('smoke_house_build_blender: PASS')


if __name__ == '__main__':
    main()
