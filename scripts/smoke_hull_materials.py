"""Pure material contract; hand-derived rows (W/G/A/B are distinct kinds).

A + {1:B}: walls A/B/A, slots wall/wall_l1/wall.
No A + {1:B}: walls G/B/W, slots wall_ground/wall_l1/wall.
Neither: G/W/W, no extra slots, baseline geometry digest unchanged.
Roof R replaces only roof. #808080 gives 128/255 on walls;
#ff0000 roof_tint gives (1,0,0) on roof, with zero jitter.
Validation retains slate and #336699, drops empty trim/junk and blue.
"""
import sys
import tempfile
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import paths

_storage = tempfile.TemporaryDirectory(prefix="hull-materials-storage-")
paths.init(Path(_storage.name))

from smoke_hull_geometry import check_identity, digest, description
from _hull_fixtures import l_shaped_house
from app.core import hull_model, hull_styles
from app.core.hull_facts import hull_facts
from app.core.hull_geometry import build_hull


def main():
    styles = hull_styles.load_styles()
    desc = hull_styles.validate_description({'overrides': {
        'materials': {'roof': 'slate', 'trim': '', 'junk': 'x'},
        'roof_tint': '#336699', 'tint': '#ffffff'}}, styles)
    assert desc['overrides']['materials'] == {'roof': 'slate'}
    assert desc['overrides']['roof_tint'] == '#336699'
    assert 'roof_tint' not in hull_styles.validate_description(
        {'overrides': {'roof_tint': 'blue'}}, styles)['overrides']
    # Plain colours bypass global tint, jitter and weathering; overrides win per slot.
    from app.core.hull_util import tone_to_linear
    with tempfile.TemporaryDirectory() as tmp:
        for name, style in styles.items():
            for colours in ({}, {'frame_color': '#abcdef', 'shop_color': '#123456',
                                 'awning_color': '#fedcba'}):
                plain_desc = hull_styles.validate_description({'overrides': {
                    **colours, 'tint': '#000000', 'roof_tint': '#000000'}}, styles)
                materials, textures, sizes = hull_model._materials(
                    {**style, 'materials': {}}, plain_desc, Path(tmp) / name, frozenset())
                by_name = {m['name']: m for m in materials}
                for material, key in (('window_frame', 'frame'), ('shop', 'shop'), ('awning', 'awning')):
                    assert material in by_name, (name, material)
                    colour = colours.get(key + '_color', style['palette'].get(key, '#ffffff'))
                    assert by_name[material] == dict(name=material, texture=None,
                        color=tone_to_linear(colour), roughness=.6, alpha=1.0)
                    assert 'texture_' + material not in textures and material not in sizes
    style = deepcopy(styles['steinhaus'])
    style['materials'].update(wall='w', wall_ground='g')
    desc = description('steinhaus', 7)
    loc = l_shaped_house()
    for fields, walls, slots in (
        ({'wall_kind': 'a', 'level_walls': {'1': 'b'}}, ['a','b','a'], ['wall','wall_l1','wall']),
        ({'level_walls': {'1': 'b'}}, ['g','b','w'], ['wall_ground','wall_l1','wall']),
        ({}, ['g','w','w'], ['wall_ground','wall','wall'])):
        loc = l_shaped_house()
        loc['map3d'].update(fields)
        result = hull_model.material_kinds(style, desc, {'map3d': fields}, [0,1,2])
        assert result['walls'] == dict(zip(['0','1','2'], walls))
        assert result['storey_slot'] == dict(enumerate(slots))
        assert result['slots']['wall'] == fields.get('wall_kind', 'w')
        if not fields:
            assert not any(k.startswith('wall_l') for k in result['slots'])
        effective = {**style, 'storey_slot': result['storey_slot']}
        facts = hull_facts(loc)
        geometry = build_hull(facts, effective, desc, tier='full')
        for n, slot in enumerate(slots):
            shell = [p for p in geometry['parts'] if p['tag'] == 'wall'
                     and all(n*3-1e-4 <= v[1] <= (n+1)*3+1e-4 for v in p['vertices'])]
            assert shell and all(p['material'] == slot for p in shell)
        if not fields:
            assert digest(geometry) == digest(build_hull(facts, style, desc, tier='full'))
    top = hull_model.material_kinds(style, desc, {'map3d': {'level_walls': {'2':'b'}}}, [0,1,2])
    for form in ('gable', 'shed'):
        geometry = build_hull(hull_facts(loc), {**style, 'storey_slot': top['storey_slot']},
                              {**desc, 'overrides': {'roof_form':form}}, tier='full')
        ends = [p for p in geometry['parts'] if p['tag']=='gable' and p['material']=='wall_l2']
        assert ends
        assert any(c < 1 for p in ends for face in p['colors'] for c in face)
    override = deepcopy(desc)
    override['overrides'].update(materials={'roof':'r'}, tint='#808080', roof_tint='#ff0000')
    kinds = hull_model.material_kinds(style, override, {}, [0,1,2])
    assert kinds['slots'] == {**style['materials'], 'roof':'r'}
    from PIL import Image
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp)/'white.png'
        Image.new('RGB', (2,2), 'white').save(source)
        effective = {**style, 'materials': kinds['slots'], 'tint_jitter': 0}
        with patch('app.core.surface_textures.base_texture_file', return_value=source), patch(
                'app.core.surface_textures.texture_size_m', return_value=3):
            _, textures, sizes = hull_model._materials(effective, override, Path(tmp)/'out', frozenset(kinds['slots']))
        for slot, pixel in [('roof',(255,0,0)), ('wall',(128,128,128))]:
            with Image.open(textures['texture_'+slot]) as image:
                assert image.getpixel((0,0)) == pixel
            assert sizes[slot] == 3
    # Integration through build_job, including added storeys and distinct UV sizes.
    from app.core.hull_mesh import rng
    with tempfile.TemporaryDirectory() as tmp:
        sources = {}
        for kind, size in [('w', 2), ('g', 3), ('b', 5), ('r', 7)]:
            source = Path(tmp) / f'{kind}.png'
            Image.new('RGB', (2, 2), 'white').save(source)
            sources[kind] = source
        loc = l_shaped_house()
        loc['map3d']['level_walls'] = {'1': 'b', '3': 'b'}
        original = deepcopy(loc)
        extended = deepcopy(override)
        extended['overrides']['storeys_total'] = 4
        with patch.object(hull_styles, 'load_styles', return_value={'steinhaus': style}), patch(
                'app.core.surface_textures.base_texture_file', side_effect=lambda k: sources.get(k)), patch(
                'app.core.surface_textures.texture_size_m', side_effect=lambda p: {'w':2,'g':3,'b':5,'r':7}[p.stem]):
            job = hull_model.build_job(loc['id'], extended, loc, tex_dir=Path(tmp)/'job')
            effective = hull_model.material_kinds(style, extended, loc, [0,1,2,3])
            _, textures, sizes = hull_model._materials({**style, 'materials':effective['slots']},
                extended, Path(tmp)/'slots', frozenset(effective['slots']))
        assert loc == original
        assert job['walls'] == {'0':'g', '1':'b', '2':'w', '3':'b'}
        assert {'wall_l1', 'wall_l3'} <= {m['name'] for m in job['materials']}
        assert sizes['wall_l1'] == sizes['wall_l3'] == 5 and sizes['roof'] == 7
        assert Path(textures['texture_wall_l1']).read_bytes() == Path(textures['texture_wall']).read_bytes()
        factors = [128/255 * (1+rng(7, 'tint:wall').uniform(-style['tint_jitter'], style['tint_jitter']))]
        with Image.open(textures['texture_wall_l1']) as image:
            assert image.getpixel((0,0))[0] == round(255*factors[0])
    check_identity()
    print('PASS hull materials')


if __name__ == '__main__':
    main()
