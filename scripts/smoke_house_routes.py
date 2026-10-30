"""House admin HTTP contract without Blender or live storage.

Usage: ./.venv/bin/python scripts/smoke_house_routes.py
A 6 x 9 m authored size supplies a 6 x 9 m footprint. Three storeys at
3.2 m and two units fit because each unit is 3 m wide (minimum 2.5 m).
Missing authored dimensions must return 400. The second build is busy. A saved 6 m width allows only floor(6/2.5) = 2
units; 99 storeys and 9 m height clamp to 12 and 4.5 m.
[F3] Resetting authored 6x9 to stored 8x12 yields 8x12; copying that
footprint to a sibling previously at 6x9 yields 8x12 on both. Missing
stored width/depth returns 400 repeatedly without repairing the missing
size on disk, and player reset returns 403.
[F7] Removing saved UIDs simulates legacy JSON: copy-layout must still
return 200 because its read and bulk_update must share persisted identities.
[F3-UI/F5-UI] The reset action is wired to its endpoint and translated;
server errors are rendered in an alert even on a newly opened panel.
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
            # Run independent final regressions before the older route checks.
            failures = []
            def check(number, fn):
                try:
                    fn(); print(number, 'PASS')
                except Exception as exc:
                    failures.append((number, repr(exc))); print(number, 'FAIL', repr(exc))
            def reset():
                props.set_variant_dims(pid, 0, dict(width_m=8, depth_m=12, height_m=10))
                response = client.post(base + '/reset-footprint')
                assert response.status_code == 200, response.text
                assert client.get(base).json()['footprint_m'] == [8, 12]
                missing_path = props._sidecar_path(missing)
                before = missing_path.read_bytes()
                assert client.post(f'/world/props/{missing}/variants/0/house/reset-footprint').status_code == 400
                assert missing_path.read_bytes() == before, 'failed reset repaired missing size'
                assert client.post(f'/world/props/{missing}/variants/0/house/reset-footprint').status_code == 400
                assert client.post(base + '/reset-footprint', headers={'x-role': 'user'}).status_code == 403
            check('F3-reset', reset)
            def copy_footprint(legacy=False):
                other_pid = props.create_prop(name='Copy regression', width_m=6, depth_m=9, height_m=8)['id']
                hp.set_house_spec(other_pid, 0, {})
                other_index = props.add_variant(other_pid)
                meta = props.read_sidecar(other_pid)
                meta[props.VARIANTS_KEY][other_index]['house'] = {'footprint_m': [4, 5], 'spec': saved}
                if legacy:
                    for entry in meta[props.VARIANTS_KEY]: entry.pop('uid', None)
                props._sidecar_path(other_pid).write_text(__import__('json').dumps(meta))
                response = client.post(f'/world/props/{other_pid}/house/copy-layout', json={'from': 0})
                assert response.status_code == 200, response.text
                assert client.get(f'/world/props/{other_pid}/variants/{other_index}/house').json()['footprint_m'] == [6, 9]
            check('F3-copy', copy_footprint)
            check('F7-legacy', lambda: copy_footprint(True))
            def ui():
                panel = (Path(__file__).resolve().parents[1] / 'frontend/src/tabs/props/HouseBuildPanel.tsx').read_text()
                assert '/house/reset-footprint' in panel
                assert "t('Reset footprint from size')" in panel
                assert 'status.error' in panel and 'role="alert"' in panel
                assert 'open={status.built || running || !!status.error || !!error}' in panel
            check('F3/F5-UI', ui)
            assert not failures, failures
            # Restore the older cases' initial footprint.
            meta = props.read_sidecar(pid)
            meta[props.VARIANTS_KEY][0]['house']['footprint_m'] = [6, 9]
            props._write_sidecar(pid, meta)
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
