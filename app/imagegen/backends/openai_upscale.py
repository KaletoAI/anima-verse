"""Authenticated AI-Hub upscale alias over native async generations/jobs."""
import base64
import hashlib
import os
from urllib.parse import quote, urljoin

import requests

from app.imagegen.base import ImageBackend, GatewayRejectedError, GatewayInputMismatchError, GatewayOutputError
from app.imagegen.backends._gateway_job import submit_job, poll_job, download_result


class OpenAIUpscaleBackend(ImageBackend):
    """Single PNG in/out; the alias schema is a mandatory availability gate."""
    DEFAULT_REF_SLOT_COUNT = 1

    def __init__(self, name, api_url, cost, env_prefix, *, upscale_scale=2, color_fix=True, max_side=4096):
        super().__init__(name, api_url, cost, 'openai_upscale', env_prefix)
        self.category = 'upscale'
        self.model = os.environ.get(f'{env_prefix}MODEL', '').strip()
        self.api_key = os.environ.get(f'{env_prefix}API_KEY', '').strip()
        self.upscale_scale = min(4, max(1, float(upscale_scale)))
        self.color_fix = bool(color_fix)
        self.max_side = min(8192, max(512, int(max_side)))
        self.timeout = int(os.environ.get(f'{env_prefix}TIMEOUT', '') or 120)
        self.max_wait = int(os.environ.get(f'{env_prefix}MAX_WAIT', '') or 900)
        self.max_queue_wait = int(os.environ.get(f'{env_prefix}MAX_QUEUE_WAIT', '') or self.max_wait * 4)
        self.poll_interval = float(os.environ.get(f'{env_prefix}POLL_INTERVAL', '') or 5)
        self._schema = (False, '', frozenset())

    def _headers(self):
        return {'Authorization': f'Bearer {self.api_key}'} if self.api_key else {}

    def check_availability(self):
        try:
            response = requests.get(f'{self.api_url}/v1/generations/{quote(self.model, safe="")}/schema', headers=self._headers(), timeout=10)
            response.raise_for_status()
            schema = response.json()
            images = schema.get('images') or []
            slots = list(images) if isinstance(images, dict) else [v.get('name', '') if isinstance(v, dict) else v for v in images]
            if len(slots) != 1 or not isinstance(slots[0], str) or not slots[0]:
                raise ValueError('Upscale alias must declare one required image slot')
            declaration = images.get(slots[0], {}) if isinstance(images, dict) else images[0]
            if isinstance(declaration, dict) and declaration.get('required') is False:
                raise ValueError('Upscale image slot must be required')
            params = schema.get('params') or []
            names = frozenset(params) if isinstance(params, dict) else frozenset(v.get('name', '') if isinstance(v, dict) else v for v in params)
            schema_state = (True, slots[0], names)
        except Exception:
            self._schema = (False, '', frozenset())
            self._mark_unavailable()
            return False
        self._schema = schema_state
        self._mark_available()
        return True

    def _generate(self, prompt, negative_prompt, params):
        verified, image_slot, param_names = self._schema
        if not verified:
            raise GatewayRejectedError('Upscale alias schema is unavailable')
        raw = params['image_bytes']
        digest = hashlib.sha256(raw).hexdigest()
        values = {'scale': self.upscale_scale, 'color_fix': self.color_fix}
        payload = {'model': self.model, 'mode': 'async',
                   'images': {image_slot: 'data:image/png;base64,' + base64.b64encode(raw).decode('ascii')},
                   'params': {k: v for k, v in values.items() if k in param_names}}
        job = submit_job(self, f'{self.api_url}/v1/generations', payload, 'Upscale')
        if not job:
            return []

        def done(status, seconds):
            hashes = [str(entry.get('sha256') or '').lower() for key in ('input_images', 'inputs', 'input_files')
                      for entry in (status.get(key) or []) if isinstance(entry, dict)]
            if any(hashes) and digest not in hashes:
                raise GatewayInputMismatchError('Upscale input identity mismatch')
            results = status.get('results') or []
            if len(results) != 1 or results[0].get('mime') != 'image/png':
                raise GatewayOutputError('Upscale must deliver exactly one image/png')
            item = results[0]
            url = item.get('url') or f'/v1/jobs/{job}/result/{item.get("n", 0)}'
            response = download_result(self, urljoin(self.api_url + '/', url))
            response.raise_for_status()
            if item.get('sha256') and hashlib.sha256(response.content).hexdigest() != item['sha256'].lower():
                raise GatewayOutputError('Upscale result checksum mismatch')
            return [response.content]

        return poll_job(self, job, max_wait=self.max_wait, max_queue_wait=self.max_queue_wait,
                        poll_interval=self.poll_interval, on_done=done)
