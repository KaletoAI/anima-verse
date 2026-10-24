#!/usr/bin/env python3
"""Room ambience smoke. Usage: .venv/bin/python scripts/smoke_room_ambience.py.

By hand: daylight 1.4 clamps to 1, hex becomes lowercase; 1/no tint is
neutral and omitted; .3/invalid tint retains .3 with no tint. An edit to
room data must change the fingerprint and reach the matching rooms[] block.
All DB access uses temporary storage, initialized before world imports.
"""
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import paths


def main():
    with tempfile.TemporaryDirectory(prefix='room-ambience-') as tmp:
        paths.init(Path(tmp))
        from app.core import world_ops, scene_recipe, db
        clean = world_ops.sanitize_ambience
        assert clean({'daylight':1.4,'tint':'#BCD8FF'}) == {'daylight':1.,'tint':'#bcd8ff'}
        assert clean({'daylight':1,'tint':None}) is None
        assert clean({'daylight':'x'}) is None
        assert clean({'daylight':.3,'tint':'blue'}) == {'daylight':.3,'tint':None}
        assert clean({'daylight':-.5}) == {'daylight':0.,'tint':None}
        for raw in (None, [], 'x', {'daylight':float('nan')}, {'daylight':float('inf')}):
            assert clean(raw) is None
        db.init_schema()
        loc = {'id':'ambience-room','map3d':{'plan_width_m':10,
            'outline':[[-5,-5],[5,-5],[5,5],[-5,5]]},'rooms':[
            {'id':'r','ambience':{'daylight':.3,'tint':'#ffcf9a'},
             'layout':{'x':-2,'y':-2,'w':4,'d':4}},
            {'id':'neutral','ambience':{'daylight':1,'tint':None}}]}
        from app.models import world
        loc['name'] = 'Ambience room'
        assert world.upsert_location(loc, sync_world=False)
        world_ops.update_location_with_extras(loc['id'], {'rooms':loc['rooms']})
        loc = world.get_location_by_id(loc['id'])
        assert 'ambience' not in loc['rooms'][1]
        before = scene_recipe.scene_fingerprint(loc,loc['id'])
        assert before == scene_recipe.scene_fingerprint(loc,loc['id'])
        scene = scene_recipe.compose_scene(loc, plan_width_m=10)
        assert next(r for r in scene['rooms'] if r['room_id']=='r')['ambience'] == loc['rooms'][0]['ambience']
        loc['rooms'][0]['ambience']['daylight'] = .5
        assert scene_recipe.scene_fingerprint(loc,loc['id']) != before
        loc['rooms'][0]['ambience'] = {'daylight':'x'}
        world_ops.update_location_with_extras(loc['id'], {'rooms':loc['rooms']})
        assert 'ambience' not in world.get_location_by_id(loc['id'])['rooms'][0]
        print('PASS: ambience clamps/invalid/neutral, room sanitization, payload and fingerprint')


if __name__ == '__main__':
    main()
