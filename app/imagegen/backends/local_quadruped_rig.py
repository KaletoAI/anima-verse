"""Local CC0 fox skeleton fitting and distance skinning, on the mesh channel.

FBX post-steps (normalization, retexture, extension rig, LOD and meshopt)
are no-ops. The Blender fit therefore fixes metres, orientation and ground
placement before export; the store must preserve the delivered FBX bytes.
"""
import json
import os
import tempfile
import threading
from pathlib import Path

from app.imagegen.base import ImageBackend, BackendNotApplicableError


class LocalQuadrupedRigBackend(ImageBackend):
    REQUIRES_URL = False
    MEDIA_TYPE = 'mesh'

    def __init__(self, name, api_url, cost, env_prefix):
        super().__init__(name, api_url, cost, 'local_quadruped_rig', env_prefix)
        self.category = 'mesh2rig'
        self.timeout = int(os.environ.get(f'{env_prefix}TIMEOUT', '') or 600)
        self.max_wait = int(os.environ.get(f'{env_prefix}MAX_WAIT', '') or 600)
        self.tail_mode_default = os.environ.get(f'{env_prefix}TAIL_MODE_DEFAULT', '') or 'calm'
        self._result = threading.local()
        self.last_result_files = []
        self.last_result_rig = 'generic'
        self.last_result_meta = {}

    @property
    def last_result_files(self):
        return getattr(self._result, 'files', [])

    @last_result_files.setter
    def last_result_files(self, value):
        self._result.files = value

    @property
    def last_result_meta(self):
        return getattr(self._result, 'meta', {})

    @last_result_meta.setter
    def last_result_meta(self, value):
        self._result.meta = value

    def check_availability(self):
        # Probe the channel, not Blender: an unavailable/unsupported executable
        # must enter the ordinary failure/cooldown path when the job runs.
        self._mark_available()
        return True

    def _generate(self, prompt, negative_prompt, params):
        from app.blender import runner
        from app.core.paths import get_quadruped_dir
        self.last_result_files = []
        self.last_result_meta = {}
        options = params.get('rig_options') or {}
        tail_motion = options.get('tail_motion', '')
        if tail_motion == '' or tail_motion is None:
            tail_motion = self.tail_mode_default
        if tail_motion not in ('full', 'calm', 'still'):
            raise ValueError('unknown tail_motion: ' + str(tail_motion))
        texture = Path(params.get('basecolor_path') or '')
        if not texture.is_file():
            raise BackendNotApplicableError(self, 'missing basecolor texture PNG')
        if not runner.is_available():
            raise RuntimeError(runner.status().get('error') or 'Blender 5.2–5.x is unavailable')
        assets = get_quadruped_dir()
        # Every catalog take is baked; backend config cannot select a subset.
        catalog = assets / 'clips.json'
        clips = json.loads(catalog.read_text()) if catalog.is_file() else []
        with tempfile.TemporaryDirectory(prefix='av-quadruped-') as tmp:
            result = runner.run('quadruped_rig', inputs={
                'mesh': Path(params['source_model_path']), 'texture': texture,
                'ref': assets / 'fox-animations.glb',
            }, params={'clips': clips,
                       'tail_motion': tail_motion},
                out_dir=Path(tmp), timeout_s=max(30, self.timeout - 10))
            if not result.get('ok'):
                data = result.get('data') or {}
                reason = data.get('reason') or result.get('error') or 'quadruped fitting failed'
                if data.get('not_applicable'):
                    raise BackendNotApplicableError(self, reason)
                raise RuntimeError(reason)
            outputs = result['outputs']
            self.last_result_meta = json.loads(Path(outputs['metrics']).read_text())
            self.last_result_files = [
                {'name': 'quadruped_rigged.fbx', 'mime': 'application/octet-stream', 'kind': 'model'},
                {'name': 'quadruped_basecolor.png', 'mime': 'image/png', 'kind': 'image'},
            ]
            return [Path(outputs[k]).read_bytes() for k in ('mesh', 'texture')]
