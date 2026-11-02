"""Verified BVH/report pairs through the gateway generations/jobs API."""
import base64
import hashlib
import json
import os
import re

import requests

from app.imagegen.backends.openai_mesh_animation import OpenAIMeshAnimationBackend
from app.imagegen.backends._gateway_job import submit_job, stage_kwargs, stage_cancel


class OpenAIMotionTransitionBackend(OpenAIMeshAnimationBackend):
    MEDIA_TYPE = 'animation'

    def __init__(self, name, api_url, cost, env_prefix):
        super().__init__(name, api_url, cost, env_prefix)
        self.api_type = 'openai_motion_transition'
        self.category = 'motion2transition'
        env = lambda key, default: os.environ.get(env_prefix + key, '').strip() or default
        self.generator = 'motionbricks'
        self.license = env('LICENSE', 'NVIDIA-Open-Model-License')
        self.credit = env('CREDIT', 'MotionBricks, NVIDIA')
        self.model_revision = env('MODEL_REVISION', '')

    @property
    def motion_meta(self):
        return {'generator': 'motionbricks', 'license': self.license, 'credit': self.credit,
                'model_revision': self.model_revision, 'max_variants': self.max_variants}

    def generate_transition(self, files, params_json, *, should_cancel=None, on_job_id=None):
        blobs = self._generate('', '', {'files': files, 'params_json': params_json,
                                      'should_cancel': should_cancel, 'on_job_id': on_job_id})
        values = [json.loads(b) for b in blobs]
        for value in values:
            if 'bvh' in value:
                value['bvh'] = value['bvh'].encode('utf-8')
        return values

    def _generate(self, prompt, negative_prompt, params):
        self._tls.job_id = ''
        self._tls.result_meta = []
        spec = json.loads(params['params_json'])
        variants = len(spec['variants'])
        if not 1 <= variants <= self.max_variants:
            raise ValueError('variants must be 1..4')
        files = params['files']
        required = {'input_start_bvh', 'input_target_bvh'}
        if not required <= files.keys() or set(files) - required - {'input_guide_bvh'}:
            raise ValueError('invalid transition file slots')
        if bool(spec.get('guide')) != ('input_guide_bvh' in files):
            raise ValueError('guide file and params must agree')
        if any(not b.startswith(b'HIERARCHY') or len(b) > 64 * 1024 * 1024 for b in files.values()):
            raise ValueError('invalid BVH input')
        payload = {'model': self.model, 'mode': 'async', 'prompt': 'transition',
                   'params': {'input_params': params['params_json']},
                   'files': {k: 'data:text/plain;base64,' + base64.b64encode(v).decode()
                             for k, v in files.items()}}
        job_id = submit_job(self, f'{self.api_url}{self.mesh_endpoint}', payload, 'Transition',
                            **stage_kwargs(params, {'variants': variants}))
        if not job_id:
            return []
        self._tls.job_id = job_id
        if callable(params.get('on_job_id')):
            params['on_job_id'](job_id)
        return self._collect(job_id, variants,
                             should_cancel=params.get('should_cancel') or stage_cancel(params))

    def _fetch(self, job_id, result):
        want = result.get('sha256')
        if not isinstance(want, str) or not re.fullmatch('[0-9a-fA-F]{64}', want):
            raise ValueError('missing or malformed sha256')
        response = requests.get(f"{self.api_url}/v1/jobs/{job_id}/result/{result['n']}",
                                headers=self._headers(), timeout=300, allow_redirects=False)
        if response.status_code != 200:
            raise ValueError(f'download HTTP {response.status_code}')
        blob = response.content
        if hashlib.sha256(blob).hexdigest() != want.lower():
            raise ValueError('sha256 mismatch')
        return blob

    def _download(self, sd, job_id, variants=1):
        results = sorted(sd.get('results') or [], key=lambda r: r.get('n', -1))
        blobs, verdicts = [], []
        for i in range(variants):
            entry = {'n': i, 'ok': False, 'reason': ''}
            try:
                if len(results) != 2 * variants:
                    raise ValueError('expected exactly two results per variant')
                pair = results[2*i:2*i+2]
                if len(pair) != 2 or [r.get('n') for r in pair] != [2*i, 2*i+1]:
                    raise ValueError('missing BVH/report pair')
                if not str(pair[0].get('name', '')).lower().endswith('.bvh') or not str(pair[1].get('name', '')).lower().endswith('.json'):
                    raise ValueError('invalid BVH/report result names or order')
                bvh, report_blob = [self._fetch(job_id, r) for r in pair]
                if not bvh.startswith(b'HIERARCHY'):
                    raise ValueError('invalid BVH header')
                report = json.loads(report_blob)
                if not isinstance(report, dict):
                    raise ValueError('report must be a JSON object')
                # hub_ops persists bytes; JSON envelopes retain the pairing on resume.
                value = {'bvh': bvh.decode('utf-8'), 'report': report}
                entry['ok'] = True
            except (ValueError, KeyError, UnicodeError, requests.RequestException) as exc:
                entry['reason'] = str(exc)
                value = {'error': str(exc)}
            blobs.append(json.dumps(value).encode())
            verdicts.append(entry)
        self._tls.result_meta = verdicts
        return blobs
