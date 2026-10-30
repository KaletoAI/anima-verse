"""House admin HTTP contract without Blender or live storage.

Usage: ./.venv/bin/python scripts/smoke_house_routes.py
A 6 x 9 m authored size supplies a 6 x 9 m footprint. Three storeys at
3.2 m and two units fit because each unit is 3 m wide (minimum 2.5 m).
Missing authored dimensions must return 400. The second build is busy. A saved 6 m width allows only floor(6/2.5) = 2
units; 99 storeys and 9 m height clamp to 12 and 4.5 m.
Copying layout changes only units, storeys and storey_m; player writes are 403.
"""
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    with tempfile.TemporaryDirectory(prefix='house-routes-') as temp:
        root = Path(temp)
        os.environ['STORAGE_DIR'] = str(root)
        os.environ['INSTANCE_DIR'] = str(root / 'instance')
        from app.core import paths
        paths.init(root)
        paths.init_instance(root / 'instance')
        from app.core import props, house_props as hp, auth_dependency
        from app.routes.prop_variants import router
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        app = FastAPI()
        app.include_router(router)
        app.middleware('http')(auth_dependency.auth_gate_middleware)
        app.middleware('http')(auth_dependency.user_context_middleware)
        users = {role: {'id': role, 'username': role, 'role': role,
                        'allowed_characters': []} for role in ('admin', 'user')}
        with patch.object(auth_dependency, '_get_session_user',
                          side_effect=lambda request: users.get(request.headers.get('x-role'))):
            client = TestClient(app, headers={'x-role': 'admin'})
            pid = props.create_prop(name='House routes', width_m=6, depth_m=9, height_m=8)['id']
            missing = props.create_prop(name='Missing size')['id']
            meta = props.read_sidecar(missing)
            for key in ('width_m', 'depth_m'):
                meta[props.VARIANTS_KEY][0].pop(key, None)
            with patch.object(props, '_variant_list', return_value=meta[props.VARIANTS_KEY]):
                props._write_sidecar(missing, meta)
            base = f'/world/props/{pid}/variants/0/house'
            assert client.get(f'/world/props/{missing}/variants/0/house').json()['footprint_m'] is None
            response = client.put(f'/world/props/{missing}/variants/0/house', json={})
            assert (response.status_code, response.json()['detail']) == (400, "set the prop's size first"), response.text
            initial = client.get(base).json()
            assert initial['spec'] == hp.HOUSE_DEFAULTS and not initial['built'] and not initial['running']
            assert initial['footprint_m'] == [6, 9]
            assert initial['styles'] and 'door_styles' in initial and 'wall_kinds' in initial
            spec = {'storeys': 3, 'storey_m': 3.2, 'units': 2, 'overrides': {'tint': '#aabbcc'}}
            response = client.put(base, json=spec)
            assert response.status_code == 200, response.text
            saved = response.json()
            assert saved['storeys'] == 3 and saved['units'] == 2 and saved['storey_m'] == 3.2
            assert client.get(base).json()['spec'] == saved
            assert client.get(base).json()['footprint_m'] == [6, 9]
            with patch.object(hp, 'trigger_house_build', side_effect=[True, False]):
                assert client.post(base + '/build').json() == {'status': 'building'}
                assert client.post(base + '/build').json() == {'status': 'already_running'}
            gallery = props.model_gallery(pid, 0)
            model = gallery.dir / (gallery.stem + '_123.glb')
            model.write_bytes(b'glTF')
            from app.core.model_store import write_sidecar
            write_sidecar(model, {'source': 'house_build'})
            assert client.get(base).json()['built'] is True
            hp._running.add(pid)
            try:
                assert client.get(base).json()['running'] is True
            finally:
                hp._running.discard(pid)
            other = props.add_variant(pid)
            props.set_variant_dims(pid, other, {'width_m': 6, 'depth_m': 9, 'height_m': 8})
            hp.set_house_spec(pid, other, {'style': 'modern', 'overrides': {'tint': '#112233'}})
            copy = f'/world/props/{pid}/house/copy-layout'
            assert client.post(copy, json={'from': 0}).status_code == 200
            copied = client.get(f'/world/props/{pid}/variants/{other}/house').json()['spec']
            assert all(copied[k] == saved[k] for k in ('units', 'storeys', 'storey_m'))
            assert copied['style'] == 'modern' and copied['overrides']['tint'] == '#112233'
            assert client.post(copy, json={'from': -1}).status_code == 404
            for bad in ({}, {'from': True}, {'from': '0'}):
                assert client.post(copy, json=bad).status_code == 400
            assert client.post(copy, content='{', headers={'content-type': 'application/json'}).status_code == 400
            props.set_variant_dims(pid, 0, {'width_m': 8, 'depth_m': 12, 'height_m': 10})
            assert client.get(base).json()['footprint_m'] == [6, 9]
            clamped = client.put(base, json={'storeys': 99, 'storey_m': 9, 'units': 8}).json()
            assert (clamped['storeys'], clamped['storey_m'], clamped['units']) == (12, 4.5, 2)
            assert client.get(f'/world/props/{pid}/variants/99/house').status_code == 404
            for method, url, body in [('put', base, spec), ('post', base + '/build', {}), ('post', copy, {'from': 0})]:
                assert getattr(client, method)(url, json=body, headers={'x-role': 'user'}).status_code == 403
            assert client.get(base, headers={'x-role': 'user'}).status_code == 200
        print('house routes: all checks passed')


if __name__ == '__main__':
    main()
