"""Hull regression checks with independent hand-derived geometry.

Round 1: upper timber outer=.07/2+.005+.30+.25=.59; front=.64.
The sill spans y=3.08..3.24 and x=-.59..6.59 on each flush side.
The shed begins at x=6+.04+.01=6.05, so the retained sill length
is 6.05-(-.59)=6.64 on both z=-.59..-.64 and z=8.59..8.64.
Stone inner offset=.07/2+.005=.04; covered slab starts at x=6+.04+.01=6.05.
Its plane still uses outer=.54: at x=6.05, height=top+(4+.54-.05)*tan(25).
Stepped castle has four lower and four upper convex corners; two coincide,
so six candidates survive (upper corners on the lower boundary are eligible).
With fixed rise 2, the two x=10 towers end at 3.08+2=5.08,
and the four upper candidates end at eaves=5.93 plus 2=7.93.
Two covered shed sides on a 10x8 rectangle stop at x=.05 and z=7.95.
A wood porch at 45 degrees and .1 overhang: underside at the eave
=2.9-.15/cos(45); cap top there=2.92-.1*.25=2.895,
so drop=2.895-(2.9-.15/cos(45))+.02.
The new low edge is 2.4-drop, above door head+.05=2.15. Raising
the door head to 2.3 needs the same roof clearance but exceeds that floor.
Chimney widths are .9 for wood and .6 for stone; schema maximum is 1.5.
All facade detail must clear its own roof by .02, and lower roofs by .02.
Budget tests use measured counts only to select a threshold between two
independently requested densities; expected fallback is exactly 1/2 or 0.
"""
import json
import math
import sys
import tempfile
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _hull_fixtures import stepped_house, rect_facts
from app.core import paths
# hull_styles reads world overrides from the world DB: redirect before import.
_STORAGE = tempfile.TemporaryDirectory(prefix="hull-clearance-")
paths.init(_STORAGE.name)
from app.core import hull_geometry, hull_roofs, hull_model, hull_styles
from app.core.hull_facts import hull_facts
from app.core.hull_ornaments import build_ornaments


def main():
    root = Path(__file__).resolve().parents[1]
    styles = {n: hull_styles.validate_style(json.loads((root/'shared/building_styles'/f'{n}.json').read_text()), n)
              for n in ('fachwerk', 'steinhaus', 'holzhuette', 'burg')}
    facts = hull_facts(stepped_house())
    desc = dict(style='steinhaus', seed=1, overrides=dict(ornament_density=1, pitch_deg=45, roof_form='gable'))
    for name in ('fachwerk', 'steinhaus', 'holzhuette'):
        desc['style'] = name
        result = hull_geometry.build_hull(facts, styles[name], desc, tier='full')
        for part in result['parts']:
            if 'detail_level' not in part:
                continue
            for wing in result['roof']['wings']:
                # Sharing the split boundary is not positive-area overlap.
                # These stepped-house wings are rectangles; compute their
                # local interval intersections independently of clip_detail.
                rect=wing['rect']; angle=math.radians(-rect['angle_deg'])
                local=[((x-rect['center'][0])*math.cos(angle)-(z-rect['center'][1])*math.sin(angle),
                        (x-rect['center'][0])*math.sin(angle)+(z-rect['center'][1])*math.cos(angle))
                       for x,_,z in part['vertices']]
                a,b,c,d=wing['limits']
                if min(max(p[0] for p in local),b)-max(min(p[0] for p in local),a)<1e-5:
                    continue
                if min(max(p[1] for p in local),d)-max(min(p[1] for p in local),c)<1e-5:
                    continue
                diffs = [y-height for x,y,z in part['vertices']
                         if (height := hull_roofs.roof_top_y(wing,x,z,styles[name])) is not None]
                if not diffs:
                    continue
                assert not (max(diffs) > .005 and min(diffs) < -.005), (name,part['tag'],diffs)
                if wing['level'] == part['detail_level']:
                    assert max(diffs) <= -.02+1e-4, (name,part['tag'],max(diffs))
                elif wing['level'] < part['detail_level']:
                    assert min(diffs) >= .02-1e-4, (name,part['tag'],min(diffs))
    # Seed 7: flush walls keep the sill from x=-.59 to x=6.05.
    sill_desc=dict(style='fachwerk',seed=7,overrides=dict(ornament_density=1))
    sill_hull=hull_geometry.build_hull(facts,styles['fachwerk'],sill_desc,tier='full')
    for front in (-.64,8.64):
        spans=[]
        for part in sill_hull['parts']:
            vertices=part['vertices']
            if part['tag']!='timber' or part.get('detail_level')!=1:
                continue
            if not (abs(min(v[1] for v in vertices)-3.08)<1e-4 and abs(max(v[1] for v in vertices)-3.24)<1e-4):
                continue
            if not any(abs(v[2]-front)<1e-4 for v in vertices):
                continue
            if max(v[2] for v in vertices)-min(v[2] for v in vertices)>.051:
                continue
            spans.append((min(v[0] for v in vertices),max(v[0] for v in vertices)))
        cursor=-.59
        for left,right in sorted(spans):
            if right<=cursor:
                continue
            assert left<=cursor+1e-4, (front,cursor,spans)
            cursor=max(cursor,right)
        assert cursor>=6.05-1e-4, (front,cursor,spans)
    roofs, info = hull_roofs.build_roofs(facts,styles['steinhaus'],desc,tier='full')
    shed = next(w for w in info['wings'] if w['level']==0)
    assert abs(min(p[0] for p in shed['ridge'])-6.05)<1e-4
    from app.core.scene_recipe import _point_in_polygon
    from app.core.world_geometry import polygon_distance
    for part in roofs:
        if part.get('roof_level') != 0 or part['tag'] not in ('roof','gable'):
            continue
        for x,_,z in part['vertices']:
            outline=facts['levels'][1]['outline']
            assert not (_point_in_polygon(x,z,outline) and polygon_distance(x,z,outline)>1e-4)
            assert x>=6.05-1e-4
    assert abs(shed['ridge_y']-(facts['levels'][0]['top_y']+4.49*math.tan(math.radians(25))))<1e-4
    flat_desc=deepcopy(desc); flat_desc['overrides']['roof_form']='flat'
    flat_parts,_=hull_roofs.build_roofs(facts,styles['steinhaus'],flat_desc,tier='full')
    assert all(v[0]>=6.05-1e-4 for p in flat_parts if p.get('roof_level')==0 and p['tag']=='roof' for v in p['vertices'])
    # The second covered side must constrain slab, gable and ridge too.
    pieces=[]
    wing=hull_roofs._pitched(dict(center=[5,4],length=10,depth=8,angle_deg=0),
                             ['z_max','x_min'],'shed',0,3,25,.4,styles['steinhaus'],{},pieces)
    assert all(v[0]>=.05-1e-4 and v[2]<=7.95+1e-4 for p in pieces for v in p['vertices'])
    assert abs(wing['ridge'][0][0]-.05)<1e-4
    # A porch clears the slab underside, or disappears when the door is too tall.
    from app.core.hull_ornaments import _porches
    rectangle=rect_facts()
    porch_style=deepcopy(styles['holzhuette']); porch_style['roof']['overhang_m']=[.1,.1]
    _,roof_info=hull_roofs.build_roofs(rectangle,porch_style,desc,tier='full')
    porch=[]
    _porches(rectangle['levels'][0],styles['holzhuette'],{},porch,roof_info)
    cap=next(p for p in porch if p['tag']=='roof')
    drop=2.895-(2.9-.15/math.cos(math.radians(45)))+.02
    assert abs(min(v[1] for v in cap['vertices'])-(2.4-drop))<1e-4
    rectangle['levels'][0]['edges'][0]['openings'][0]['y1']=2.3
    porch=[]
    _porches(rectangle['levels'][0],styles['holzhuette'],{},porch,roof_info)
    assert not porch
    castle = deepcopy(styles['burg']); castle['towers']['chance']=1
    castle['towers']['rise_m']=[2,2]; castle['towers']['roof']=['cone']
    towers = [p for p in build_ornaments(facts,castle,desc,{},tier='low') if p['tag']=='tower']
    assert len(towers)==6
    for tower in towers:
        xs=[v[0] for v in tower['vertices']]; zs=[v[2] for v in tower['vertices']]
        x,z=(min(xs)+max(xs))/2,(min(zs)+max(zs))/2
        assert not (0.05<x<9.95 and .05<z<7.95)
        expected_top=5.08 if x>9 else 7.93
        assert abs(max(v[1] for v in tower['vertices'])-expected_top)<1e-4
    for name,width in (('holzhuette',.9),('steinhaus',.6)):
        style=deepcopy(styles[name]); style['chimneys']=[1,1]
        parts,_=hull_roofs.build_roofs(rect_facts(),style,desc,tier='low')
        chimney=next(p for p in parts if p['tag']=='chimney')
        assert abs(max(v[0] for v in chimney['vertices'])-min(v[0] for v in chimney['vertices'])-width)<1e-4
    assert hull_styles.validate_style({'chimney_width_m':5},'x')['chimney_width_m']==1.5
    assert hull_styles.validate_style({},'x')['chimney_width_m']==.6
    assert hull_styles.validate_style({'chimney_width_m':0},'x')['chimney_width_m']==.3
    desc['style']='fachwerk'
    counts={}
    for density in (1,.5,0):
        candidate=deepcopy(desc); candidate['overrides']['ornament_density']=density
        counts[density]={tier:hull_geometry.build_hull(facts,styles['fachwerk'],candidate,tier=tier)['tris'] for tier in ('full','low')}
    assert counts[1]['full']>counts[.5]['full']
    budget={'full':counts[.5]['full'],'low':max(c['low'] for c in counts.values())}
    with patch.dict(hull_geometry.TRI_BUDGET,budget):
        fitted=hull_geometry.fit_budget(facts,styles['fachwerk'],desc)
        assert fitted['overrides']['ornament_density']==.5 and desc['overrides']['ornament_density']==1
    with patch.dict(hull_geometry.TRI_BUDGET,counts[0]):
        assert hull_geometry.fit_budget(facts,styles['fachwerk'],desc)['overrides']['ornament_density']==0
    assert hull_geometry.fit_budget(facts,styles['fachwerk'],desc) is desc
    with patch.object(hull_styles,'load_styles',return_value=styles), patch.dict(hull_geometry.TRI_BUDGET,budget):
        job=hull_model.build_job('hull-demo',desc,stepped_house())
        assert job['description']==desc and job['ornament_density_used']==.5
        assert job['placement']['full']==job['placement']['low']
    with patch.dict(hull_geometry.TRI_BUDGET,{'full':0,'low':0}):
        try: hull_geometry.fit_budget(facts,styles['fachwerk'],desc)
        except ValueError as error: assert str(error)=='hull too large'
        else: raise AssertionError('impossible hull accepted')
        with patch.object(hull_styles,'load_styles',return_value=styles):
            assert hull_model.build_job('hull-demo',desc,stepped_house())=={'ok':False,'error':'too_large'}
    print('PASS: hull clearance, covered shed, silhouette towers, chimney schema, budget fallback')

if __name__=='__main__':
    with tempfile.TemporaryDirectory() as temporary:
        paths.init(temporary)
        main()
