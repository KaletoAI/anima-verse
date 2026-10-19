"""Task 2, no Blender: hand-derived apply and schema rows.

Rooms A=(0,0)..(6,4), B=(6.2,0)..(10,8) align the 0.2 gap to x=6,
so the union is (0,0)(10,0)(10,8)(6,8)(6,4)(0,4). North windows
centre at x=3 and x=8, both on facade edge 0; their 1.2 m spans are
[2.4,3.6] and [7.4,8.6]. Seed boundary expands the box by 2 m.
Upper A alone yields the 6x4 level-1 contour; an omitted stored B keeps
its place and still completes the union. An omitted stored room at
x 10.2..14 next to a placed 0..10 room is written aligned to x 10..14
(0.2 < 0.3, one room each, tie -> 10), so its wall lies on the contour
(0,0)(14,0)(14,4)(0,4). Split x=6.4 blocks writes.
"""
import copy
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import paths
paths.init(Path(tempfile.mkdtemp(prefix='building-assistant-smoke-')))
from app.core import db
db.init_schema()
from app.core.layout_apply import (sanitize_layout, apply_layout, layout_snapshot,
                                   restore_layout_snapshot, layout_counts)
from app.core.world_ops import update_location_with_extras
from app.core.hull_styles import load_styles, validate_description
from app.core.hull_facts import hull_facts
from app.models import world

OUTLINE = [[0,0],[10,0],[10,8],[6,8],[6,4],[0,4]]
BOUNDARY = [[-2,-2],[12,-2],[12,10],[-2,10]]
window = dict(edge=0, at=.5, width_m=1.2, height_m=1.4, sill_m=.9, type='window')
draft = dict(rooms=[dict(name='A', x=0,y=0,w=6,d=4,room_type='living', openings=[window]),
                         dict(name='B', x=6.2,y=0,w=3.8,d=8,room_type='bogus', openings=[window])],
             storey_height_m=9, hull={'style':'no-such-style'})
loc = world.add_location('House', 'Test', rooms=[])
n, warnings = sanitize_layout(draft, location=loc)
assert n['rooms'][0].get('room_type') == 'living'
assert 'room_type' not in n['rooms'][1]
assert 'room_type_dropped' in [w['code'] for w in warnings]
assert n['storey_height_m'] == 4.5
assert n['hull_valid'] is False
assert 'hull_style_unknown' in [w['code'] for w in warnings]
for value in ('3.2', True, None, float('nan'), float('inf')):
    bad, _ = sanitize_layout({**draft, 'storey_height_m':value}, location=loc)
    assert 'storey_height_m' not in bad
low, _ = sanitize_layout({**draft, 'storey_height_m':1}, location=loc)
assert low['storey_height_m'] == 2.6
style = next(iter(load_styles()))
raw_hull = dict(style=style, overrides={'shopfront':True, 'pitch_deg':100})
valid, _ = sanitize_layout({**draft,'hull':raw_hull}, location=loc)
assert valid['hull_valid'] and valid['hull'] == validate_description(raw_hull,load_styles())
chat, _ = sanitize_layout({'rooms':[dict(name='Chat',x=0,y=0,w=4,d=4)]},location=loc)
assert set(chat) == {'summary','location_id','location_name','boundary','storey_height_m',
                     'entry_room','rooms','boundary_openings','stairs'}
assert 'room_type' not in chat['rooms'][0]
assert chat['storey_height_m'] == 3.0  # existing preview key, no new chat keys
update_location_with_extras(loc['id'], {'entry_room':''})
loc = world.get_location_by_id(loc['id'])
snap = layout_snapshot(loc['id'])
n, warnings = sanitize_layout(draft,location=loc,derive_contour=True)
assert n['outline'] == OUTLINE and n['boundary'] == BOUNDARY and not n['errors']
assert n['rooms'][1]['layout']['x'] == 6 and n['rooms'][1]['layout']['w'] == 4
assert layout_counts(n) == dict(rooms=2,new_rooms=2,openings=2,boundary_openings=0,stairs=0)
apply_layout(n)
after = world.get_location_by_id(loc['id'])
assert after['map3d']['outline'] == OUTLINE
assert after['map3d']['boundary'] == BOUNDARY and after['map3d']['storey_height_m'] == 4.5
assert not after['map3d'].get('level_outlines')
a = next(r for r in after['rooms'] if r['id']==n['rooms'][0]['room_id'])
b = next(r for r in after['rooms'] if r['id']==n['rooms'][1]['room_id'])
assert a['room_type'] == 'living' and a['layout'] == n['rooms'][0]['layout']
facts = hull_facts(after)
windows = [(e['index'], o) for l in facts['levels'] for e in l['edges']
           for o in e['openings'] if o['kind']=='window']
assert len(windows) == 2 and all(i==0 for i,o in windows), windows
# Omitted B retains its layout and completes the union.
partial = {'rooms':[dict(id=a['id'],x=0,y=0,w=6,d=4)]}
kept, ws = sanitize_layout(partial,location=after,derive_contour=True)
assert kept['outline']==OUTLINE and any(w['code']=='room_not_placed' and w['ref']==b['id'] for w in ws)
apply_layout(kept)
assert world.get_location_by_id(loc['id'])['map3d']['boundary'] == BOUNDARY
assert next(r for r in world.get_location_by_id(loc['id'])['rooms'] if r['id']==b['id']) == b
# Chat apply preserves stored contour, type and height, even with geometry edits.
chat_existing, _ = sanitize_layout({'rooms':[dict(id=a['id'],x=0,y=0,w=6,d=4)]},location=after)
apply_layout(chat_existing)
chat_after = world.get_location_by_id(loc['id'])
assert chat_after['map3d'] == after['map3d']
assert next(r for r in chat_after['rooms'] if r['id']==a['id'])['room_type']=='living'
# All contour and existing optional map keys share a single save.
combined = {**kept, 'stairs':[dict(at=[1,1],from_level=0,dir_deg=0)],
            'boundary_openings':[dict(edge=0,at=.5,width_m=1)]}
apply_layout(combined)
combined_map = world.get_location_by_id(loc['id'])['map3d']
assert combined_map['outline']==OUTLINE and combined_map['stairs']==combined['stairs']
assert len(combined_map['boundary_openings'])==1
upper = copy.deepcopy(draft)
upper['rooms'].append(dict(name='Upper',x=0,y=0,w=6,d=4,level=1))
u, _ = sanitize_layout(upper,location=loc,derive_contour=True)
assert u['level_outlines']=={'1':[[0,0],[6,0],[6,4],[0,4]]}
apply_layout(u)
assert world.get_location_by_id(loc['id'])['map3d']['level_outlines']==u['level_outlines']
# Applying the original plan replaces the entire cascade.
apply_layout(n)
assert not world.get_location_by_id(loc['id'])['map3d'].get('level_outlines')
split = copy.deepcopy(draft)
split['rooms'][1].update(x=6.4,w=3.6)
bad, ws = sanitize_layout(split,location=loc,derive_contour=True)
assert any(e['code']=='contour_split' for e in bad['errors'])
assert all(e in ws for e in bad['errors'])
before = world.get_location_by_id(loc['id'])
try:
    apply_layout(bad)
except ValueError as exc:
    assert str(exc).startswith('contour:')
else:
    raise AssertionError('contour errors accepted')
assert world.get_location_by_id(loc['id']) == before
restore_layout_snapshot(snap)
back = world.get_location_by_id(loc['id'])
for key in ('rooms','map3d','entry_room'):
    assert back.get(key) == loc.get(key), key
# An omitted, unaligned stored room is written aligned, not left beside the contour.
side = world.add_location('Side', 'Test', rooms=[])
seed = {'rooms':[dict(name='Main',x=0,y=0,w=10,d=4), dict(name='Shed',x=10.2,y=0,w=3.8,d=4)]}
first, _ = sanitize_layout(seed, location=side)
apply_layout(first)
side = world.get_location_by_id(side['id'])
main = next(r for r in side['rooms'] if r.get('name')=='Main')
shed = next(r for r in side['rooms'] if r.get('name')=='Shed')
assert shed['layout']['x'] == 10.2
only_main, ws = sanitize_layout({'rooms':[dict(id=main['id'],x=0,y=0,w=10,d=4)]},
                                location=side, derive_contour=True)
assert any(w['code']=='room_not_placed' and w['ref']==shed['id'] for w in ws)
assert only_main['outline'] == [[0,0],[14,0],[14,4],[0,4]] and not only_main['errors']
apply_layout(only_main)
stored = next(r for r in world.get_location_by_id(side['id'])['rooms'] if r['id']==shed['id'])
assert stored['layout']['x'] == 10 and stored['layout']['w'] == 4, stored['layout']
print('building assistant schema/apply rows: PASS')
