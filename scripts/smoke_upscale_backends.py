#!/usr/bin/env python3
"""P2 upscale contracts, without network or persistent storage.

Usage: ./.venv/bin/python scripts/smoke_upscale_backends.py
Hand-derived expectations: a 273x261 RGB fixture crosses the 256-pixel tile
boundary in both axes. A nearest-neighbour 4x session repeats every input
pixel into exactly 4x4 pixels, giving 1092x1044, including colours and edges.
A 1200x600 result capped at 512 must become 512x256. A 300x200 input at
scale 2 has target 600x400; max_side 512 instead gives 512x341 (rounded).
Explicit picks cannot fall back; special operations never generate images.
The options fixture has one generator and three special image entries: all
ordinary options contain only that generator. The default seed has eleven
entries (eight original mesh aliases + one P1 face alias + two P2 upscalers).
Missing upscale routing uses the two-name default; explicit [] remains [].
Changing any cache identity field or corrupting either file forces one call.
Busy/cancel invoke no next entry and set no cooldown; invalid Hub output does.
At max_side 8192, the intermediate has a further 8192-side memory cap:
a 2300x1 input is inferred at 2048x1; its requested 2x output is 4600x2.
All model-file checks use temporary files; the optional pinned ONNX is read only.
"""
import io
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from PIL import Image


def png(image):
    out = io.BytesIO()
    image.save(out, format='PNG')
    return out.getvalue()


class RepeatSession:
    def get_inputs(self):
        return [type('Input', (), {'name': 'input'})()]

    def run(self, outputs, inputs):
        tensor = inputs['input']
        assert tensor.dtype == np.float32 and tensor.shape[0:2] == (1, 3)
        assert 0 <= tensor.min() <= tensor.max() <= 1
        return [tensor.repeat(4, axis=2).repeat(4, axis=3)]


def main():
    with tempfile.TemporaryDirectory() as tmp:
        from app.core import paths
        paths.init(tmp)
        paths.init_instance(Path(tmp) / 'instance')
        from app.imagegen.backends.local_upscale import tiled_upscale
        from app.imagegen.upscale import normalize_output
        fixture = np.zeros((261, 273, 3), dtype=np.uint8)
        fixture[:, :, 0] = np.arange(273, dtype=np.uint16) % 256
        fixture[:, :, 1] = (np.arange(261, dtype=np.uint16) % 256)[:, None]
        fixture[0, :, 2] = 255
        fixture[-1, :, 2] = 127
        fixture[:, -1, 2] = 63
        result = tiled_upscale(Image.fromarray(fixture), RepeatSession())
        assert result.size == (1092, 1044)
        assert np.array_equal(np.asarray(result), fixture.repeat(4, 0).repeat(4, 1))
        raw, size = normalize_output(png(Image.new('RGB', (1200, 600))), 512)
        assert size == [512, 256] and Image.open(io.BytesIO(raw)).mode == 'RGB'
        from unittest.mock import patch
        from app.core import config, db, provider_manager
        from app.core.config_validator import _check_image_backends
        from app.imagegen.backends import local_upscale
        from app.imagegen.backends.local_upscale import LocalUpscaleBackend
        from app.imagegen.backends.openai_upscale import OpenAIUpscaleBackend
        from app.imagegen.service import ImageService
        from app.imagegen.selection import BackendPool, is_generator_backend
        from app.imagegen.base import ImageBackend, BackendBusyError, BackendFailedError, GenerationCancelled, MediaGenerationDisabled, GatewayRejectedError, GatewayOutputError
        from app.imagegen import routing
        from app.imagegen.occasions import OCCASIONS, backend_fits
        from app.imagegen.backends._gateway_job import download_result
        import hashlib
        import json
        import os
        import threading
        db.init_schema()

        class Response:
            status_code = 200
            headers = {}
            content = b'content'
            def __init__(self, data=None, content=None, code=200, headers=None):
                self.data = data
                if content is not None: self.content = content
                self.status_code = code
                self.headers = headers or {}
            def json(self): return self.data
            def raise_for_status(self):
                if self.status_code != 200: raise ValueError('transport failure')

        schema = {'images': [{'name': 'reference', 'required': True}],
                  'params': [{'name': 'scale'}, {'name': 'color_fix'}]}
        hub = OpenAIUpscaleBackend('hub', 'https://gateway.invalid', 1, 'UPSCALE_SMOKE_', upscale_scale=3, color_fix=False, max_side=512)
        hub.model = 'Iris-3B-Upscale'
        hub.api_key = 'fixture-token'
        hub.poll_interval = 0
        image = png(Image.new('RGB', (300, 200), (17, 83, 219)))
        delivered = png(Image.new('RGB', (900, 600), (17, 83, 219)))
        payloads = []
        def submit(backend, url, payload, kind):
            payloads.append(payload)
            return 'fixture-job'
        def poll(backend, job, **kwargs):
            return kwargs['on_done']({'results': [{'mime': 'image/png', 'url': '/result',
                'sha256': hashlib.sha256(delivered).hexdigest()}],
                'input_images': [{'sha256': hashlib.sha256(image).hexdigest()}]}, 1)
        with patch('app.imagegen.backends.openai_upscale.requests.get', return_value=Response(schema)):
            assert hub.check_availability()
        with patch('app.imagegen.backends.openai_upscale.submit_job', side_effect=submit), patch('app.imagegen.backends.openai_upscale.poll_job', side_effect=poll), patch('app.imagegen.backends.openai_upscale.download_result', return_value=Response(content=delivered)):
            assert hub._generate('', '', {'image_bytes': image, 'strength': 1}) == [delivered]
            payload = payloads[-1]
            assert payload['mode'] == 'async' and list(payload['images']) == ['reference']
            import base64
            uri = payload['images']['reference']
            assert uri.startswith('data:image/png;base64,') and base64.b64decode(uri.split(',')[1]) == image
            assert payload['params'] == {'scale': 3.0, 'color_fix': False}
            hub._schema = (True, 'reference', frozenset({'scale'}))
            hub._generate('', '', {'image_bytes': image})
            assert payloads[-1]['params'] == {'scale': 3.0}
        # Hand-derived: a pending health check preserves the verified payload.
        import threading
        started, release = threading.Event(), threading.Event()
        def pending_schema(url, **kwargs):
            if url.endswith('/schema'):
                started.set()
                assert release.wait(5)
                return Response(schema)
            return response()
        with patch('app.imagegen.backends.openai_upscale.requests.get', side_effect=pending_schema), patch('app.imagegen.backends.openai_upscale.submit_job', side_effect=submit), patch('app.imagegen.backends.openai_upscale.poll_job', side_effect=poll), patch('app.imagegen.backends.openai_upscale.download_result', return_value=Response(content=delivered)):
            worker = threading.Thread(target=hub.check_availability)
            worker.start()
            try:
                assert started.wait(5)
                hub._generate('', '', {'image_bytes': image})
                assert list(payloads[-1]['images']) == ['reference'] and payloads[-1]['params'] == {'scale': 3.0}
            finally:
                release.set()
                worker.join(5)
            assert not worker.is_alive()
        # A completed schema failure during encoding cannot split this payload.
        encode = base64.b64encode
        def refresh_during_encode(raw):
            with patch('app.imagegen.backends.openai_upscale.requests.get', return_value=Response(code=403)):
                assert not hub.check_availability()
            return encode(raw)
        with patch('app.imagegen.backends.openai_upscale.base64.b64encode', side_effect=refresh_during_encode), patch('app.imagegen.backends.openai_upscale.submit_job', side_effect=submit), patch('app.imagegen.backends.openai_upscale.poll_job', side_effect=poll), patch('app.imagegen.backends.openai_upscale.download_result', return_value=Response(content=delivered)):
            hub._generate('', '', {'image_bytes': image})
            assert list(payloads[-1]['images']) == ['reference']
            assert payloads[-1]['params'] == {'scale': 3.0, 'color_fix': False}
        with patch('app.imagegen.backends.openai_upscale.requests.get', return_value=Response(schema)):
            assert hub.check_availability()
        # Exercise the real poller; a cancelled job must abort, not degrade.
        from app.imagegen.backends import _gateway_job
        with patch('app.imagegen.backends.openai_upscale.submit_job', return_value='fixture-job'), patch.object(_gateway_job.requests, 'get', return_value=Response({'status': 'cancelled'})):
            try:
                hub._generate('', '', {'image_bytes': image})
            except GenerationCancelled:
                pass
            else:
                raise AssertionError('Polled upscale cancellation must propagate')
        with patch('app.imagegen.backends.openai_upscale.requests.get', return_value=Response(code=403)):
            assert not hub.check_availability() and not hub.available
        try: hub._generate('', '', {'image_bytes': image})
        except GatewayRejectedError: pass
        else: raise AssertionError('Missing schema must refuse generation')
        for results in ([], [{'mime': 'image/jpeg'}], [{'mime': 'image/png'}, {'mime': 'image/png'}]):
            hub._schema = (True, 'reference', frozenset({'scale', 'color_fix'}))
            with patch('app.imagegen.backends.openai_upscale.submit_job', return_value='fixture-job'), patch('app.imagegen.backends.openai_upscale.poll_job', side_effect=lambda backend, job, **kw: kw['on_done']({'results': results}, 1)):
                try: hub._generate('', '', {'image_bytes': image})
                except GatewayOutputError: pass
                else: raise AssertionError('Invalid output must fail')
        with patch('app.imagegen.backends._gateway_job.requests.get') as download:
            try: download_result(hub, 'https://foreign.invalid/result')
            except GatewayRejectedError: pass
            else: raise AssertionError('Foreign result origin must fail')
            download.assert_not_called()
        with patch('app.imagegen.backends._gateway_job.requests.get', return_value=Response(code=302, headers={'Location': 'https://foreign.invalid/result'})) as download:
            try: download_result(hub, 'https://gateway.invalid/result')
            except GatewayRejectedError: pass
            else: raise AssertionError('Foreign redirect must fail')
            assert download.call_count == 1 and download.call_args.kwargs['allow_redirects'] is False

        wrong = Path(tmp) / 'wrong.onnx'
        wrong.write_bytes(b'wrong pinned model')
        assert not local_upscale.verify_model(wrong) and not wrong.exists()
        local = LocalUpscaleBackend('cpu', '', 0, 'UPSCALE_SMOKE_')
        with patch.object(local_upscale, 'MODEL_PATH', Path(tmp) / 'model.onnx'), patch.object(local_upscale.requests, 'get', side_effect=OSError('offline fixture')), patch.object(local_upscale, '_session', None), patch.object(local_upscale, '_retry_at', 0):
            assert local.check_availability()
            try: local_upscale.get_session()
            except OSError: pass
            else: raise AssertionError('Download must fail')
            assert not local.check_availability()
            with patch.object(local_upscale.time, 'monotonic', return_value=local_upscale._retry_at + 1):
                assert local.check_availability()
        with patch.object(local_upscale, 'get_session', return_value=RepeatSession()):
            assert Image.open(io.BytesIO(local._generate('', '', {'image_bytes': image})[0])).size == (600, 400)
            # 4*1200 > 2*512 -> inference input capped at ceil(512/2)=256.
            big = png(Image.new('RGB', (1200, 600)))
            local.max_side = 512
            with patch.object(local_upscale, 'get_session', side_effect=AssertionError('No inference for already-large input')):
                assert local._generate('', '', {'image_bytes': big})[0] == big
            local.max_side = 512
            medium = png(Image.new('RGB', (300, 200)))
            shapes = []
            class RecordingSession(RepeatSession):
                def run(self, outputs, inputs):
                    shapes.append(inputs['input'].shape)
                    return super().run(outputs, inputs)
            with patch.object(local_upscale, 'get_session', return_value=RecordingSession()):
                assert Image.open(io.BytesIO(local._generate('', '', {'image_bytes': medium})[0])).size == (512, 341)
                assert max(max(shape[2:]) for shape in shapes) <= 256

        local.max_side = 8192
        def bounded_inference(source, session):
            assert source.size == (2048, 1)
            return Image.new('RGB', (8, 1))
        with patch.object(local_upscale, 'get_session', return_value=RepeatSession()), patch.object(local_upscale, 'tiled_upscale', side_effect=bounded_inference):
            assert Image.open(io.BytesIO(local._generate('', '', {'image_bytes': png(Image.new('RGB', (2300, 1)))})[0])).size == (4600, 2)
        entries = [{'name': 'configured-cpu', 'api_type': 'local_upscale', 'category': 'upscale', 'enabled': True,
                    'upscale_scale': 3, 'max_side': 512, 'color_fix': False},
                   {'name': 'configured-hub', 'api_type': 'openai_upscale', 'category': 'upscale', 'enabled': True,
                    'api_url': 'https://gateway.invalid', 'model': 'Iris-3B-Upscale', 'upscale_scale': 4, 'max_side': 1024, 'color_fix': False}]
        with patch.dict(os.environ, {}, clear=False), patch.object(config, 'get', return_value=entries):
            config._flatten_to_env({'image_generation': {'backends': entries}})
            svc = object.__new__(ImageService)
            loaded = svc._load_instances()
            by_name = {b.name: b for b in loaded}
            assert by_name['configured-cpu'].upscale_scale == 3 and by_name['configured-cpu'].max_side == 512
            assert by_name['configured-hub'].upscale_scale == 4 and not by_name['configured-hub'].color_fix
            assert by_name['configured-hub'].model == 'Iris-3B-Upscale'
            assert not _check_image_backends({'image_generation': {'backends': entries}})
            assert not LocalUpscaleBackend.REQUIRES_URL and ImageBackend.REQUIRES_URL
            manager = object.__new__(provider_manager.ProviderManager)
            with patch.object(manager, '_channel') as create_channel:
                providers, known = manager._load_backend_channels({})
                assert 'configured-cpu' in providers
                assert 'configured-cpu' in known
                assert any(call.args[0] == 'backend:configured-cpu' for call in create_channel.call_args_list)
            config._flatten_to_env({'image_generation': {'backends': [{**entries[0], 'enabled': False}]}})
            with patch.object(manager, '_channel') as create_channel:
                providers, known = manager._load_backend_channels({})
                assert 'configured-cpu' not in providers
                create_channel.assert_not_called()

        # Missing route uses the default chain; explicit [] remains cheapest.
        with patch.object(config, 'get', return_value={}):
            assert routing._rules('upscale') == ['Iris-3B-Upscale', 'Real-ESRGAN-CPU']
        with patch.object(config, 'get', return_value={'upscale': []}):
            assert routing._rules('upscale') == []

        # Real persistence on temporary instance/world config files.
        world_config = Path(tmp) / 'config.json'
        instance_config = Path(tmp) / 'instance' / 'config.json'
        config.load(world_config, instance_path=instance_config)
        from app.core import config_scope
        from app.routes.admin_settings import _validate_image_routing
        for rules in ({}, {'upscale': []}, {'upscale': ['configured-hub', 'configured-cpu']}):
            part = {'image_generation': {'backends': entries, 'routing': rules}}
            config.save_part(config_scope.INSTANCE, part)
            config.load(world_config, instance_path=instance_config)
            assert config.get('image_generation.routing') == rules
            expected = ['Iris-3B-Upscale', 'Real-ESRGAN-CPU'] if 'upscale' not in rules else rules['upscale']
            assert routing._rules('upscale') == expected
        assert not _validate_image_routing({'backends': entries, 'routing': {'upscale': ['configured-cpu']}})[0]
        assert 'wrong kind' in _validate_image_routing({'backends': entries, 'routing': {'photo': ['configured-cpu']}})[0]
        class Fake(ImageBackend):
            def __init__(self, name, category='upscale', cost=0):
                super().__init__(name, 'https://fixture.invalid', cost, 'fake', 'UPSCALE_SMOKE_')
                self.category = category
                self._available = True
                self.instance_enabled = True
                self.upscale_scale = 2
                self.max_side = 512
                self.color_fix = True
                self.model = 'fixture-v1'
                self.calls = 0
                self.failure = None
            def check_availability(self): return self.available
            def _generate(self, prompt, negative, params):
                self.calls += 1
                if self.failure: raise self.failure
                return [delivered]
        first, second, generator, inpaint = Fake('first'), Fake('second'), Fake('generator', 'txt2img'), Fake('inpaint', 'inpaint')
        svc = object.__new__(ImageService)
        svc._pool = BackendPool([first, second, generator, inpaint])
        svc.enabled = True
        svc.run_on_backend_channel = lambda b, fn, **kwargs: fn()
        for occasion, definition in OCCASIONS.items():
            if definition['category'] == 'render':
                assert not backend_fits(occasion, {'media': 'image', 'category': 'upscale'})
        assert backend_fits('upscale', {'media': 'image', 'category': 'upscale'})
        assert not backend_fits('upscale', {'media': 'image', 'category': 'txt2img'})
        assert svc.match_backend('first') is None and svc.match_backend('fir*') is None
        assert svc.resolve_imagegen_target('*', preferred_backend='first') is None
        assert svc.match_backend('*') is generator
        assert svc.list_available_backends() == [generator]
        assert svc._wait_for_backend('') is generator
        from app.core.explicit_backend import require_explicit_backend
        from fastapi import HTTPException
        with patch('app.imagegen.service.get_image_service', return_value=svc):
            try: require_explicit_backend('first')
            except HTTPException as exc: assert exc.status_code == 503
            else: raise AssertionError('Ordinary explicit route accepted upscale')
            # Actual option producers, including the HTTP payloads.
            from app.core.world_ops import build_imagegen_options
            from app.core.character_ops import skill_option_source
            from app.core.improvements.types.subjects import image_backend_options
            from app.routes.world import surface_textures_admin, props_admin
            assert [o['name'] for o in build_imagegen_options()['options']] == ['generator']
            assert [o['value'] for o in skill_option_source('image_backends')] == ['generator']
            assert [o['value'] for o in image_backend_options()] == ['generator']
            for response, key in ((surface_textures_admin(), 'backends'), (props_admin(), 'image_backends')):
                assert [o['name'] for o in response[key]] == ['generator']
                assert all(is_generator_backend(o) for o in response[key])
        with patch.object(routing, '_rules', return_value=['first', 'second']):
            cached_path = Path(tmp) / 'facefix-ref' / '0123456789ab.png'
            result = svc.upscale_image(image, cache_path=cached_path)
            assert result['out'] == [512, 341] and not result['cached'] and first.calls == 1
            assert svc.upscale_image(image, cache_path=cached_path)['cached'] and first.calls == 1
            for attribute, value in (('upscale_scale', 3), ('color_fix', False), ('max_side', 1024), ('model', 'fixture-v2'), ('api_type', 'fake-v2')):
                setattr(first, attribute, value)
                assert not svc.upscale_image(image, cache_path=cached_path)['cached']
            assert not svc.upscale_image(png(Image.new('RGB', (300, 200), 'red')), cache_path=cached_path)['cached']
            cached_path.write_bytes(b'corrupt')
            assert not svc.upscale_image(image, cache_path=cached_path)['cached']
            cached_path.with_suffix('.json').write_text('broken')
            assert not svc.upscale_image(image, cache_path=cached_path)['cached']
            first.failure = BackendBusyError('busy fixture')
            calls = second.calls
            try: svc.upscale_image(image)
            except BackendBusyError: pass
            else: raise AssertionError('Busy must propagate')
            assert not first.in_cooldown() and second.calls == calls
            first.failure = GenerationCancelled('fixture-job')
            try: svc.upscale_image(image)
            except GenerationCancelled: pass
            else: raise AssertionError('Cancel must propagate')
            assert not first.in_cooldown() and second.calls == calls
            first.failure = RuntimeError('offline fixture')
            try: svc.upscale_image(image, backend_glob='first')
            except BackendFailedError: pass
            else: raise AssertionError('Explicit failure must propagate')
            assert second.calls == calls
            first._cooldown_until = 0
            first._available = True
            assert svc.upscale_image(image)['backend'] == 'second' and second.calls == calls+1
            assert first.in_cooldown()
            with patch('app.imagegen.service.media_generation_enabled', return_value=False):
                try: svc.upscale_image(image, cache_path=cached_path)
                except MediaGenerationDisabled: pass
                else: raise AssertionError('Master switch must propagate')
        hub._available = True
        hub._cooldown_until = 0
        hub._schema = (True, 'reference', frozenset({'scale', 'color_fix'}))
        svc._pool.backends.insert(0, hub)
        second._available = True
        with patch.object(hub, 'check_availability', return_value=True), patch.object(routing, '_rules', return_value=['hub', 'second']), patch('app.imagegen.backends.openai_upscale.submit_job', return_value='fixture-job'), patch('app.imagegen.backends.openai_upscale.poll_job', side_effect=lambda backend, job, **kw: kw['on_done']({'results': []}, 1)):
            assert svc.upscale_image(image)['backend'] == 'second', 'Invalid Hub output must fall back to CPU'
        svc._pool.backends.remove(hub)
        if local_upscale.MODEL_PATH.is_file() and local_upscale.MODEL_PATH.stat().st_size == local_upscale.MODEL_SIZE and hashlib.sha256(local_upscale.MODEL_PATH.read_bytes()).hexdigest() == local_upscale.MODEL_SHA256:
            import onnxruntime as ort
            session = ort.InferenceSession(str(local_upscale.MODEL_PATH), providers=['CPUExecutionProvider'])
            small = Image.fromarray(fixture[:23, :29])
            tensor = np.asarray(small).transpose(2, 0, 1)[None].astype(np.float32)/255
            expected = session.run(None, {session.get_inputs()[0].name: tensor})[0][0].transpose(1, 2, 0)
            expected = np.clip(np.rint(expected*255), 0, 255).astype(np.uint8)
            assert np.max(np.abs(np.asarray(tiled_upscale(small, session, tile_size=12)).astype(int)-expected.astype(int))) <= 2
            print('OK: optional pinned ONNX tiled/untiled check')
        else:
            print('SKIP: optional pinned ONNX file absent or not verified; no download')
    print('PASS: upscale backends — payload, schema, origin, config bridge, generator options, routing, pin, tiling, bounds, cache, explicit, fallback, busy and cancellation')


if __name__ == '__main__':
    main()
