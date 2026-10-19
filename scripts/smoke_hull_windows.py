"""Hand-derived §3.1/3.2/3.3 window and shopfront checks; run with ./.venv/bin/python."""
from copy import deepcopy
import math
import hashlib
import json
import tempfile
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from _hull_fixtures import rect_facts, no_degenerate_faces, waldkante_house, stepped_house, gap_house
from app.core import paths, hull_facades, hull_roofs
_STORAGE = tempfile.TemporaryDirectory(prefix="hull-windows-import-")
paths.init(_STORAGE.name)
from app.core.hull_facts import hull_facts
from app.core.hull_geometry import prepare_facts, fit_budget, build_hull, TRI_BUDGET
from app.core.hull_facades import mullions
from app.core.hull_styles import validate_style
from app.core.hull_walls import build_walls, wall_offsets

# Generated door-integrated wall parts (seed 17, density 1).
# 3a: Blender doors
BASELINE = {
    "modern:full": "27726a5f546af691b69b96f86c2e9743e3df875704682bda3f6d626f1e34f6ac",
    "modern:low": "1d1608011e9a5af1142275a1942b78635afb136032419e969b5810ac56e9bfcd",
    "fachwerk:low": "135abec5f5a07c1a29bb79dce0969aa474ed2037268b1c56bb40ac4e04771bd4",
    "steinhaus:low": "2d81b866101d0ef5e893717928bffc2be0fa704e463e2f1c4b43d74eab8a447d",
    "holzhuette:low": "7154a6f815485c9864debf6836727205bdf466238ecdde580e6078bb55bfc03f",
    "burg:low": "e574b5e65360b6fe49a8ae11fe551b7a8db5fd04d7ef35f9fcc021ba09f4ad10"
}


def check_blender_doors():
    """Hole 2..3.2 gives casing 1.93..3.27, y 0..2.17 (0.07 casing).

    Fachwerk wall .30: frame .34, centred at .19, depth .02...36.
    Low = four frame boxes + one leaf = 30 quads. Castle 1.8 gives
    two (1.8-.015)/2=.8925 leaves separated by .005.
    """
    for name in ('fachwerk','modern','steinhaus','burg'):
        for tier in ('full','low'):
            parts=build_walls(rect_facts(),style(name),dict(seed=17,overrides={}),tier=tier)
            doors=[p for p in parts if p['tag']=='door']
            assert {p.get('node') for p in doors} == {'frame','leaf'}
            assert not any(p['material']=='door' for p in parts)
            frame=next(p for p in doors if p['node']=='frame')
            inner,outer=wall_offsets(style(name),0)
            assert box(frame)==(1.93,3.27,0,2.17,round(inner-.02,4),round(outer+.02,4))
            if tier=='low':
                assert len(doors)==2 and sum(len(p['faces']) for p in doors)==30
            # Overlapping casing/surround box faces must not be coplanar.
            for surround in (p for p in parts if p['tag']=='frame'):
                for f in frame['faces']:
                    a=[frame['vertices'][i] for i in f]
                    for g in surround['faces']:
                        b=[surround['vertices'][i] for i in g]
                        for axis in range(3):
                            if max(v[axis] for v in a)-min(v[axis] for v in a)>1e-6:
                                continue
                            if not all(abs(v[axis]-a[0][axis])<1e-6 for v in b):
                                continue
                            assert not all(min(max(v[k] for v in a),max(v[k] for v in b)) >
                                           max(min(v[k] for v in a),min(v[k] for v in b))+1e-6
                                           for k in range(3) if k!=axis)
    shop=build_walls(rect_facts(),style('fachwerk'),dict(seed=17,overrides={'shopfront':True}),tier='full')
    assert any(p['tag']=='door' and p['material']=='glass' for p in shop)
    facts=rect_facts(); facts['levels'][0]['edges'][0]['openings'][0]['s1']=3.8
    doors=[p for p in build_walls(facts,style('burg'),dict(seed=17,overrides={}),tier='low') if p['tag']=='door']
    leaves=[box(p) for p in doors if p['node'] in ('leaf','leaf_b')]
    assert len(leaves)==2 and leaves[0][:2]==(2.005,2.8975) and leaves[1][:2]==(2.9025,3.795)
    # Opposite hinge: B's .04 x .06 ring is .06 from its centre-seam
    # latch edge, at 2.9025+.06=2.9625, lifted to y=1.025.
    full=build_walls(facts,style('burg'),dict(seed=17,overrides={}),tier='full')
    hardware=next(p for p in full if p.get('node')=='leaf_b' and p['material']=='hardware_castle')
    boxes=[hardware['vertices'][i:i+8] for i in range(0,len(hardware['vertices']),8)]
    rings=[v for v in boxes if abs(max(p[0] for p in v)-min(p[0] for p in v)-.04)<1e-4
           and abs(max(p[1] for p in v)-min(p[1] for p in v)-.06)<1e-4]
    assert len(rings)==2 and all(abs(sum(p[0] for p in v)/8-2.9625)<1e-4 for v in rings)
    from _hull_fixtures import face_normal
    for part in (p for p in full if p['tag']=='door'):
        for face in part['faces']:
            points=[part['vertices'][i] for i in face]
            start=min(face)//8*8
            solid=part['vertices'][start:start+8]
            normal=face_normal(points)
            assert sum(normal[k]*(sum(v[k] for v in points)/4-sum(v[k] for v in solid)/8)
                       for k in range(3)) > 0




def check_door_resolution_and_materials():
    """Styles change the facts hash, but leave every aperture coordinate fixed.

    Texture RGB 128 times #808080 leaf tint times #808080 paint rounds
    to 32 per channel. Frame has no leaf tint, so stays at 128.
    """
    from unittest.mock import patch
    from PIL import Image
    from app.core import door_models, door_styles, scene_recipe, hull_model
    loc=stepped_house()
    opening=next(op for room in loc['rooms'] for op in room['layout'].get('openings',[]) if op.get('type')=='door')
    with patch.object(door_models,'ensure_door_model',return_value=None):
        opening['door_style']='castle'
        first=hull_facts(loc)
        scene=scene_recipe.compose_scene(loc,plan_width_m=10)
        assert any(d.get('door_style')=='castle' for d in scene['doorways'])
        holes=[h for lv in first['levels'] for e in lv['edges'] for h in e['openings'] if h['kind']=='door']
        assert [h['door_style'] for h in holes]==['castle']
        opening['door_style']='interior'
        second=hull_facts(loc)
        assert first['fingerprint']!=second['fingerprint']
        strip=lambda f: [{k:v for k,v in h.items() if k!='door_style'} for lv in f['levels'] for e in lv['edges'] for h in e['openings']]
        assert strip(first)==strip(second)
        opening['prop_id']='image-door'
        prop=scene_recipe.compose_scene(loc,plan_width_m=10)
        assert all('door_style' not in d for d in prop['doorways'])
        propfacts=hull_facts(loc)
        assert any(h.get('door_style')=='' for lv in propfacts['levels'] for e in lv['edges'] for h in e['openings'] if h['kind']=='door')
        parts=build_walls(propfacts,style('burg'),dict(seed=1,overrides={}),tier='low')
        assert any(p['material']=='door_leaf_castle' for p in parts)
        opening.pop('prop_id'); opening.pop('door_style'); opening['door_prop']='none'
        assert all('door_style' not in d for d in scene_recipe.compose_scene(loc,plan_width_m=10)['doorways'])
        assert not any(h['kind']=='door' for lv in hull_facts(loc)['levels'] for e in lv['edges'] for h in e['openings'])
    facts=rect_facts()
    facts['levels'][0]['edges'][1]['openings']=[dict(s0=2,s1=3,y0=0,y1=2.1,kind='door',door_style='interior')]
    config=style('fachwerk')
    catalog=door_styles.load_door_styles()
    catalog['plank']['leaf_tint']='#808080'
    # A painted style remains painted when the hull substitutes a texture.
    catalog['interior']['leaf_tint']='#808080'
    desc=dict(seed=17,overrides=dict(door_color='#808080',materials={'door':'replacement'}))
    with tempfile.TemporaryDirectory() as tmp:
        source=Path(tmp)/'source.png'; Image.new('RGB',(1,1),(128,128,128)).save(source)
        with patch.object(door_styles,'load_door_styles',return_value=catalog), patch.object(hull_model.surface_textures,'base_texture_file',return_value=source):
            materials,images,sizes=hull_model._materials(config,desc,Path(tmp)/'textures',frozenset(),facts)
        by_name={m['name']:m for m in materials}
        assert 'door' not in by_name
        assert {'door_leaf_plank','door_leaf_interior','door_frame_plank','door_frame_interior','hardware_plank','hardware_interior','glass'} <= by_name.keys()
        with Image.open(images[by_name['door_leaf_interior']['texture']]) as image:
            assert image.getpixel((0,0))==(32,32,32)
        with Image.open(images[by_name['door_leaf_plank']['texture']]) as image:
            assert image.getpixel((0,0))==(64,64,64)  # timber does not take paint
        assert by_name['hardware_plank']['roughness']==.3
        assert by_name['glass']['alpha']==.6
        geometry=build_walls(facts,config,desc,tier='full',uv_sizes=sizes)
        assert {p['material'] for p in geometry} <= by_name.keys()
        # fachwerk names materials.door "door_planks"; only a BUILDING override may
        # replace a door style's leaf, so the painted interior door stays untextured.
        assert config['materials']['door']
        with patch.object(door_styles,'load_door_styles',return_value=catalog), patch.object(hull_model.surface_textures,'base_texture_file',return_value=source):
            plain,_,_=hull_model._materials(config,dict(seed=17,overrides={}),Path(tmp)/'plain',frozenset(),facts)
        assert next(m for m in plain if m['name']=='door_leaf_interior')['texture'] is None
    from _hull_fixtures import l_shaped_house
    large=hull_facts(l_shaped_house())
    for name in ('fachwerk','holzhuette','steinhaus','burg','modern'):
        config=style(name)
        fitted=fit_budget(large,config,dict(seed=7,overrides={'ornament_density':.5}))
        for tier in ('full','low'):
            result=build_hull(large,config,fitted,tier=tier)
            assert result['tris'] <= TRI_BUDGET[tier]
            assert sum(p['tag']=='door' and p.get('node')=='frame' for p in result['parts'])==2



def style(name):
    return validate_style(json.loads((root/'shared/building_styles'/f'{name}.json').read_text()),name)


def build(name='fachwerk', *, facts=None, density=1, tier='full'):
    config = style(name)
    config['shutters'] = 0
    return build_walls(rect_facts() if facts is None else facts,config,
                       dict(seed=17,overrides=dict(ornament_density=density)),tier=tier)


def box(part):
    # Edge 0 tangent +x, outward -z: compare (s,y,outward depth).
    points = [(x,y,-z) for x,y,z in part['vertices']]
    return tuple(round(f(p[k] for p in points),4) for k in range(3) for f in (min,max))


def expected_ring(d0,d1):
    return {(6,6.06,.9,2.1,d0,d1),(7.14,7.2,.9,2.1,d0,d1),
            (6.06,7.14,.9,.96,d0,d1),(6.06,7.14,2.04,2.1,d0,d1)}


def check_glass():
    outer = wall_offsets(style('fachwerk'),0)[1]
    assert {round(-v[2],4) for p in build() if p['tag']=='glass' for v in p['vertices']} == {round(outer-.12,4)}


def check_details():
    outer = wall_offsets(style('fachwerk'),0)[1]
    d0,d1 = round(outer-.14,4),round(outer-.08,4)
    parts = build()
    casements = [p for p in parts if p['tag']=='casement']
    assert len(casements)==6 and all(p['material']=='window_frame' for p in casements)
    assert {box(p) for p in casements} == expected_ring(d0,d1) | {
        (6.58,6.62,.96,2.04,d0,d1),(6.06,7.14,1.624,1.664,d0,d1)}
    sills = [p for p in parts if p['tag']=='sill']
    assert len(sills)==1 and sills[0]['material']=='trim'
    assert box(sills[0]) == (5.92,7.28,.83,.9,round(outer,4),round(outer+.1,4))
    assert no_degenerate_faces(parts)


def check_density():
    for filler in (False,True):
        facts = rect_facts()
        facts['levels'][0]['filler'] = filler
        if filler:
            facts['levels'][0]['edges'][0]['openings'][1]['blind'] = True
        parts = build(facts=facts,density=0)
        assert sum(p['tag']=='casement' for p in parts)==4
        assert sum(p['tag']=='sill' for p in parts)==1


def check_blind():
    facts = rect_facts()
    facts['levels'][0]['filler'] = True
    facts['levels'][0]['edges'][0]['openings'][1]['blind'] = True
    outer = wall_offsets(style('fachwerk'),0)[1]
    parts = build(facts=facts,density=0)
    assert {box(p) for p in parts if p['tag']=='casement'} == expected_ring(round(outer+.02,4),round(outer+.06,4))


def check_surrounds():
    for name in ('fachwerk','holzhuette','steinhaus','burg'):
        parts = build(name)
        frames = [box(p) for p in parts if p['tag']=='frame']
        assert not any(a < 7.2 and b > 6 and c < .9 and d <= .9 for a,b,c,d,_,_ in frames)
        assert sum(p['tag']=='sill' for p in parts)==1
        assert all(min(v[0] for v in p['vertices'])>5 for p in parts if p['tag'] in ('sill','casement'))
        assert any(a < 3.2 and b > 2 for a,b,_,_,_,_ in frames)


def check_wide_and_thresholds():
    for width,height,vertical,horizontal in ((2,1.2,1,1),(3.6,1.2,2,1),(.7,.9,1,1),(.69,.89,0,0)):
        facts = rect_facts()
        h = facts['levels'][0]['edges'][0]['openings'][1]
        h.update(s1=6+width,y1=.9+height)
        parts = [p for p in build(facts=facts) if p['tag']=='casement']
        assert len(parts)==4+vertical+horizontal
        centres = mullions(6,6+width) if width>1.8 else [6+width/2]
        for centre in centres if vertical else []:
            assert any(abs((box(p)[0]+box(p)[1])/2-centre)<1e-4 and abs(box(p)[1]-box(p)[0]-.04)<1e-4 for p in parts)


def check_identity():
    for name in ('modern','fachwerk','steinhaus','holzhuette','burg'):
        for tier in ('full','low') if name=='modern' else ('low',):
            parts = build_walls(rect_facts(),style(name),dict(seed=17,overrides=dict(ornament_density=1)),tier=tier)
            digest = hashlib.sha256(json.dumps(parts,sort_keys=True,allow_nan=False).encode()).hexdigest()
            assert digest == BASELINE[name+':'+tier], (name,tier,digest)



def prepared_windows(location=None, config=None, **overrides):
    facts = hull_facts(waldkante_house() if location is None else location)
    desc = dict(seed=17,overrides=dict(blind_windows=True,**overrides))
    return prepare_facts(facts,style('fachwerk') if config is None else config,desc,frozenset())


def check_real_storey_raster():
    """Seed 17 bay=2.4634947653. Upper outer=.59, spans [-.59,L+.59].
    L=10.4: 4 candidates, centres .8575,3.7525,6.6475,9.5425;
    L=9.1: 4 candidates, centres .695,3.265,5.835,8.405.
    Width=1.2: first/last end clearance .8475/.685, so no end drops.
    Edge 2 real centres 3.12,7.28: middle candidates overlap (drop 2),
    outside candidates have gap 1.0625/1.0625 (keep). Counts [4,4,2,4].
    Ground outer=.34: 4,3,4,3 raster candidates; door centre 5.2
    drops middle two on edge 2, giving [4,3,2,3].
    """
    facts = prepared_windows()
    upper = facts['levels'][1]
    counts = []
    for edge in upper['edges']:
        blinds = [h for h in edge['openings'] if h.get('blind')]
        counts.append(len(blinds))
        for h in blinds:
            assert math.isclose(h['s1']-h['s0'],1.2)
            assert math.isclose(h['y0']-upper['floor_y'],.92)
            assert math.isclose(h['y1']-h['y0'],1.2)
            assert h['s0'] >= -.59+.6-1e-8 and h['s1'] <= edge['length']+.59-.6+1e-8
            for real in edge['openings']:
                if not real.get('blind'):
                    assert max(real['s0']-h['s1'],h['s0']-real['s1']) >= .5-1e-8
    assert counts == [4,4,2,4], counts
    ground = facts['levels'][0]
    assert [sum(h.get('blind',False) for h in e['openings']) for e in ground['edges']] == [4,3,2,3]
    dims = hull_facades.blind_dims(style('fachwerk'),17)
    for edge in ground['edges']:
        for h in edge['openings']:
            if h.get('blind'):
                assert math.isclose(h['s1']-h['s0'],dims['width'])
                assert math.isclose(h['y1']-h['y0'],dims['height'])
                assert h['y0'] >= style('fachwerk')['plinth_height_m']+.1


def check_real_storey_flag_and_medians():
    facts = hull_facts(gap_house())
    original = deepcopy(facts)
    off = prepare_facts(facts,style('fachwerk'),dict(seed=17),frozenset())
    on = prepared_windows(gap_house())
    for a,b in zip(off['levels'],on['levels']):
        if a.get('filler'):
            assert a == b
        else:
            assert not any(h.get('blind') for e in a['edges'] for h in e['openings'])
    assert facts == original
    assert on == prepared_windows(gap_house())
    loc = waldkante_house()
    holes = loc['rooms'][1]['layout']['openings']
    holes[0].update(width_m=1.0,sill_m=.78,height_m=1.0)
    holes[1].update(width_m=1.4,sill_m=1.02,height_m=1.4)
    upper = prepared_windows(loc)['levels'][1]
    blinds = [h for e in upper['edges'] for h in e['openings'] if h.get('blind')]
    assert blinds
    for h in blinds:
        assert math.isclose(h['s1']-h['s0'],1.2)
        assert math.isclose(h['y0']-upper['floor_y'],.92)
        assert math.isclose(h['y1']-h['y0'],1.2)
    for edge in upper['edges']:
        for h in edge['openings']:
            if h.get('blind'):
                assert all(max(r['s0']-h['s1'],h['s0']-r['s1']) >= .5-1e-8
                           for r in edge['openings'] if not r.get('blind'))


def check_real_storey_roof_and_short_wall():
    facts = prepared_windows(stepped_house())
    _, info = hull_roofs.build_roofs(facts,style('fachwerk'),dict(seed=17),tier='full')
    upper = facts['levels'][1]
    # Lean-to touches edge 1; all three candidates are below its high side.
    assert not any(h.get('blind') for h in upper['edges'][1]['openings'])
    assert any(h.get('blind') for e in upper['edges'] for h in e['openings'])
    for edge in upper['edges']:
        for h in edge['openings']:
            if not h.get('blind'):
                continue
            centre = (h['s0']+h['s1'])/2
            x,z = [edge['a'][k]+(edge['b'][k]-edge['a'][k])*centre/edge['length'] for k in range(2)]
            for wing in info['wings']:
                if wing['level'] < upper['level']:
                    top = hull_roofs.roof_top_y(wing,x,z,style('fachwerk'))
                    assert top is None or h['y0'] >= top+.1-1e-8
    loc = waldkante_house()
    loc['map3d']['outline'] = [[0,0],[1.5,0],[1.5,9.1],[0,9.1]]
    facts = prepared_windows(loc,config=style('modern'))
    assert all(not h.get('blind') for l in facts['levels'] for e in (l['edges'][0],l['edges'][2]) for h in e['openings'])



def check_real_storey_filters():
    """A 6 m span/bay 2 has slots [.4,1.6],[2.4,3.6],[4.4,5.6].
    End slots drop at .6 clearance. A centre door with overlapping height
    drops the middle; a door ending at the sill does not. Roof equality
    at bottom-.1 is allowed; anything higher drops it. Ground plinth .81
    rejects sill .9, whereas .8 allows it. No medians from blind windows.
    """
    level = dict(level=0,floor_y=0,top_y=3,edges=[])
    edge = dict(openings=[])
    level['edges'] = [edge]
    dims = dict(width=1.2,sill=.9,height=1.2,plinth=.8)
    def slots():
        return hull_facades.wall_blind_windows(level,edge,dims,2,0,6,lambda s: [None,.8])
    assert [(h['s0'],h['s1']) for h in slots()] == [(2.4,3.6)]
    edge['openings'] = [dict(kind='door',s0=3.9,s1=4.5,y0=0,y1=2)]
    assert slots() == []  # .3 m horizontal gap
    edge['openings'][0]['y1'] = .9
    assert len(slots()) == 1
    assert hull_facades.wall_blind_windows(level,edge,dims,2,0,6,lambda s: [.8001]) == []
    dims['plinth'] = .81
    assert slots() == []
    edge['openings'] = [dict(kind='window',blind=True,s0=1,s1=2,y0=1,y1=2)]
    assert hull_facades.storey_window_dims(level) is None
    assert hull_facades.wall_blind_windows(level,edge,dims,2,0,1.5,lambda s: []) == []

def check_real_storey_budget():
    loc = gap_house()
    loc['map3d']['outline'] = [[0,0],[30,0],[30,20],[0,20]]
    loc['rooms'] = [loc['rooms'][0]]
    loc['rooms'][0]['layout'].update(w=30,d=20,openings=[])
    facts = hull_facts(loc)
    desc = dict(seed=7,overrides=dict(storeys_total=40,blind_windows=True,ornament_density=.5))
    original = deepcopy(desc)
    prepared = prepare_facts(facts,style('modern'),desc,frozenset())
    assert sum(h.get('blind',False) for e in prepared['levels'][0]['edges'] for h in e['openings']) == 30
    for resolved in (frozenset(),frozenset({'facade_module'})):
        fitted = fit_budget(facts,style('modern'),desc,resolved=resolved)
        for tier in ('full','low'):
            result = build_hull(facts,style('modern'),fitted,tier=tier,resolved=resolved)
            assert result['tris'] <= TRI_BUDGET[tier]
            print(f"PASS: blind budget {tier}={result['tris']} resolved={sorted(resolved)}")
    assert desc == original

def shop_parts(facts=None, tier='full', enabled=True, name='fachwerk'):
    from app.core.hull_ornaments import build_ornaments
    config = style(name)
    config['shutters'] = 0
    facts = rect_facts() if facts is None else facts
    desc = dict(seed=17,overrides=dict(shopfront=enabled))
    return (build_walls(facts,config,desc,tier=tier),
            build_ornaments(facts,config,desc,{},tier=tier))


def check_shop_street_edges():
    assert hasattr(hull_facades,'street_edges'), 'street_edges missing'
    facts = rect_facts()
    level = facts['levels'][0]
    assert hull_facades.street_edges(level) == {0}
    level['edges'][1]['openings'] = [dict(kind='passage')]
    assert hull_facades.street_edges(level) == {0,1}
    for edge in level['edges']:
        edge['openings'] = []
    assert hull_facades.street_edges(level) == {0}
    level['level'] = 1
    assert hull_facades.street_edges(level) == set()


def check_shop_panels_and_band():
    """outer=.34; span [-.34,10.34] inset gives [-.24,10.24]."""
    for tier in ('full','low'):
        walls, ornaments = shop_parts(tier=tier)
        panels = [p for p in walls if p['material']=='shop']
        assert panels, 'missing painted panels'
        assert all(p['tag']=='wall' and box(p)[2]>=.45 and box(p)[3]<=2.25
                   and box(p)[4:]==(.34,.34) for p in panels)
        street = [p for p in walls if p['tag']=='wall' and box(p)[4:]==(.34,.34)]
        assert all(p['material']=='shop' for p in street if .45<=box(p)[2]<2.25)
        signs = [p for p in ornaments if p['tag']=='sign']
        assert len(signs)==1
        assert box(signs[0]) == (-.24,10.24,2.25,2.75,.34,.4)
        assert signs[0]['material']=='shop' and signs[0]['protrudes']
        assert all(p['material']!='shop' for p in walls if p['tag']=='reveal')


def check_shop_awnings():
    for tier in ('full','low'):
        _, parts = shop_parts(tier=tier)
        awnings = [p for p in parts if p['tag']=='awning']
        assert len(awnings)==(8 if tier=='full' else 2), 'missing awning pieces'
        assert all(p['protrudes'] and p['material']=='awning' for p in awnings)
        for left,right in ((1.85,3.35),(5.85,7.35)):
            sheet = next(p for p in awnings if box(p)==(left,right,1.8296,2.23,.34,1.44))
            assert len(sheet['faces'])==1
            if tier=='full':
                assert any(box(p)==(left,right,1.6296,1.8296,1.42,1.44) for p in awnings)
                for a,b in ((left,round(left+.02,4)),(round(right-.02,4),right)):
                    cheek = next(p for p in awnings if box(p)==(a,b,1.8296,2.23,.34,1.44))
                    assert sorted(len(face) for face in cheek['faces'])==[3,3,4,4,4]
        assert no_degenerate_faces(parts)
        assert not any(p['tag'] in ('porch','canopy') for p in parts)
    for name in ('fachwerk','modern'):
        assert not any(p['tag'] in ('porch','canopy') for p in shop_parts(name=name)[1])


def check_shop_grouping_and_tall_door():
    for start,count in ((3.7,1),(3.9,2),(3.8,2)):
        facts = rect_facts()
        facts['levels'][0]['edges'][0]['openings'][1].update(s0=start,s1=start+1.2)
        awnings = [p for p in shop_parts(facts,tier='low')[1] if p['tag']=='awning']
        assert len(awnings)==count, (start,len(awnings))
        if count==1:
            assert box(awnings[0])==(1.85,5.05,1.8296,2.23,.34,1.44)
    facts = rect_facts()
    facts['levels'][0]['edges'][0]['openings'][0]['y1'] = 2.8
    parts = shop_parts(facts,tier='low')[1]
    assert not any(p['tag']=='sign' for p in parts)
    assert any(box(p)==(1.85,3.35,2.5296,2.93,.34,1.44) for p in parts if p['tag']=='awning')


def check_shop_flag_and_blinds():
    walls, ornaments = shop_parts(enabled=False)
    assert not any(p['material']=='shop' or p['tag'] in ('sign','awning') for p in walls+ornaments)
    facts = prepared_windows(shopfront=True)
    ground = facts['levels'][0]
    assert not any(h.get('blind') for h in ground['edges'][2]['openings']), 'street blind windows remain'
    assert any(h.get('blind') for e in ground['edges'] for h in e['openings'])
    assert any(h.get('blind') for e in facts['levels'][1]['edges'] for h in e['openings'])


def check_hull_design_render():
    """The real-window count and new optional overrides reach the rendered prompt."""
    from app.core.prompt_templates import render_task
    system, user = render_task(
        'hull_design', name='Cafe', description='Street cafe', style_hint='',
        storeys=2, windows=3, length_m=12, depth_m=8,
        styles=[dict(id='fachwerk', name='Timber', description='Traditional')],
        forms=['gable'])
    assert 'Real exterior windows: 3 (all storeys).' in user
    for key in ('blind_windows', 'shopfront', 'frame_color', 'shop_color', 'awning_color'):
        assert key in system, key
    assert 'cafés' in system and 'few windows for its size' in system


def check_hull_proposal_window_count():
    """Count windows on every storey, excluding doors and blind windows."""
    from types import SimpleNamespace
    from unittest.mock import patch
    from app.core.hull_model import propose_hull
    from app.core.prompt_templates import render_task
    facts = rect_facts()
    upper = deepcopy(facts['levels'][0])
    upper['edges'][0]['openings'].append(dict(kind='window', blind=True))
    facts['levels'].append(upper)
    with patch('app.models.world.get_location_by_id', return_value=dict(name='Cafe')), \
         patch('app.core.hull_model.hull_facts', return_value=facts), \
         patch('app.core.hull_styles.load_styles', return_value={'fachwerk': style('fachwerk')}), \
         patch('app.core.prompt_templates.render_task', wraps=render_task) as render, \
         patch('app.core.llm_router.llm_call', return_value=SimpleNamespace(
             content='{"style":"fachwerk","overrides":{"shopfront":true}}')):
        result = propose_hull('fixture')
    assert result['llm'], result
    assert render.call_args.kwargs['windows'] == 2
    assert result['description_json']['overrides']['shopfront'] is True


def main():
    failed = []
    for check in (check_blender_doors,check_door_resolution_and_materials,check_glass,check_details,check_density,check_blind,check_surrounds,check_wide_and_thresholds,check_identity,
                  check_real_storey_raster,check_real_storey_flag_and_medians,
                  check_real_storey_roof_and_short_wall,check_real_storey_filters,check_real_storey_budget,
                  check_shop_street_edges,check_shop_panels_and_band,check_shop_awnings,
                  check_shop_grouping_and_tall_door,check_shop_flag_and_blinds,check_hull_design_render,check_hull_proposal_window_count):
        try:
            check()
        except AssertionError as error:
            failed.append(check.__name__)
            print(f'FAIL: {check.__name__}: {error}')
        else:
            print(f'PASS: {check.__name__}')
    assert not failed, failed


if __name__ == '__main__':
    main()
