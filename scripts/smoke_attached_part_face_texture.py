#!/usr/bin/env python3
"""Hand-derived face preservation with an unrelated part atlas.

A blue body plus a red marked part must pass against the blue baked body.
Changing the body's RGB by 40 must fail even when the part stays blue. Mesh
order is intentionally reversed, proving that node extras, not index or name,
identify the excluded part. A second unmarked body primitive must still pass
and a changed second body primitive must fail. A joined patch sharing the
body mesh excludes only its material-marked primitive, leaving one body
primitive; deleting that marker exposes the differing red atlas and fails.
"""
import copy
from pathlib import Path
import sys
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def main():
    from app.core import paths
    with tempfile.TemporaryDirectory(prefix='part-face-') as tmp:
        paths.init(tmp)
        from app.core.face_retexture import face_texture_preserved,_body_primitives
        from app.core.model_validate import parse_glb
        from scripts.smoke_face_retexture_bake import fixture,glb
        baked=glb(*fixture())
        doc,binary=fixture(True)
        # The fixture's body is blue, material 0; its face material is red.
        body=copy.deepcopy(doc['meshes'][0]['primitives'][1])
        part=copy.deepcopy(doc['meshes'][0]['primitives'][0])
        doc['meshes']=[{'primitives':[part]},{'primitives':[body,copy.deepcopy(body)]}]
        doc['nodes']=[{'mesh':0,'extras':{'attached_part':'part'}},{'mesh':1}]
        rigged=glb(doc,binary)
        assert len(_body_primitives(parse_glb(rigged)))==2
        assert face_texture_preserved(baked,rigged)
        import importlib.util
        module_path=Path(__file__).resolve().parents[1]/'app/blender/scripts/_common.py'
        spec=importlib.util.spec_from_file_location('part_common',module_path)
        common=importlib.util.module_from_spec(spec);spec.loader.exec_module(common)
        path=Path(tmp)/'reordered.glb';path.write_bytes(rigged)
        common.body_meshes_first(path)
        reordered=parse_glb(path.read_bytes())
        assert reordered['bin']==parse_glb(rigged)['bin']
        assert reordered['gltf']['nodes'][0]['mesh']==1
        assert reordered['gltf']['nodes'][1]['mesh']==0
        assert face_texture_preserved(baked,path.read_bytes())

        doc['meshes'][1]['primitives'][1]['material']=1
        assert not face_texture_preserved(baked,glb(doc,binary))
        doc['meshes'][1]['primitives'][1]['material']=0
        doc['nodes'][0].pop('extras')
        assert not face_texture_preserved(baked,glb(doc,binary)), 'An unmarked differing primitive must be checked'
        # A joined inset patch uses material extras, retaining its body primitive.
        doc['materials'][1]['extras'] = {'attached_part': 'inset'}
        doc['meshes'] = [{'primitives': [body, part]}]
        doc['nodes'] = [{'mesh': 0}]
        joined = glb(doc, binary)
        assert len(_body_primitives(parse_glb(joined))) == 1
        assert face_texture_preserved(baked, joined)
        path.write_bytes(joined)
        common.body_meshes_first(path)
        assert path.read_bytes() == joined, 'Mixed body must retain its mesh order'
        doc['materials'][1].pop('extras')
        assert not face_texture_preserved(baked, glb(doc, binary))
        print('PASS face retexture ignores only marked parts, including reversed meshes and multiple body primitives')


if __name__=='__main__': main()
