#!/usr/bin/env python3
"""No-network credential policy checks for provider result downloads.

Hand-derived expectations: matching scheme/host/effective port gets Bearer;
foreign origins are anonymous only when opted in, otherwise refused. A 302
from gateway to CDN authenticates only the first call; CDN to gateway and
gateway to CDN to gateway never regain credentials. Userinfo and FTP are
invalid before any call. Five redirects permit six requests; a sixth redirect
is refused. Diffusion/video CDN results return bytes with no Authorization
and timeouts 60/180; mesh still refuses CDN results (default timeout 300).
A default netrc must never replace Bearer or authenticate anonymous hops;
environment proxies remain active and redirect cookies never carry over.
Unicode/punycode hostnames and explicit/default IPv6 ports share an origin.
Diffusion result timeouts are busy; video network errors retain poll retries.

Usage: ./.venv/bin/python scripts/smoke_result_download_auth.py
"""
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.imagegen.backends import _gateway_job as gateway
from app.imagegen.backends import openai_video as video
from app.imagegen.backends.openai_diffusion import OpenAIDiffusionBackend
from app.imagegen.backends.openai_mesh import OpenAIMeshBackend
from app.imagegen.base import BackendBusyError, GatewayRejectedError

AUTH = {"Authorization": "Bearer test-secret"}
HOME = "https://gateway.invalid/result"
CDN = "https://cdn.invalid/result"
BODY = b"result" * 200
backend = SimpleNamespace(api_url="https://gateway.invalid", _headers=lambda: AUTH)


def response(status=200, location=None):
    return SimpleNamespace(status_code=status, content=BODY,
                           headers={"Location": location} if location else {})


def exercise(action, replies, expected, timeout=300, rejects=False):
    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs.get("headers"), kwargs.get("allow_redirects")))
        assert kwargs["timeout"] == timeout
        return replies[len(calls) - 1]

    with patch.object(gateway.requests, "get", side_effect=get):
        try:
            result = action()
        except GatewayRejectedError:
            assert rejects, "Unexpected rejection"
        else:
            assert not rejects, "Expected rejection"
            assert result == [BODY] or result.content == BODY
    assert calls == expected, calls


def download(url, **kwargs):
    return lambda: gateway.download_result(backend, url, **kwargs)


exercise(download(HOME), [response()], [(HOME, AUTH, False)])
exercise(download("https://gateway.invalid:443/result"), [response()],
         [("https://gateway.invalid:443/result", AUTH, False)])
exercise(download(CDN, foreign="anonymous"), [response()], [(CDN, None, False)])
exercise(download(CDN), [], [], rejects=True)
for foreign in ("http://gateway.invalid/result", "https://gateway.invalid:444/result"):
    exercise(download(foreign), [], [], rejects=True)
exercise(download(HOME, foreign="anonymous"), [response(302, CDN), response()],
         [(HOME, AUTH, False), (CDN, None, False)])
exercise(download(HOME), [response(302, CDN)], [(HOME, AUTH, False)], rejects=True)
exercise(download(CDN, foreign="anonymous"), [response(302, HOME), response()],
         [(CDN, None, False), (HOME, None, False)])
exercise(download(HOME, foreign="anonymous"),
         [response(302, CDN), response(302, HOME), response()],
         [(HOME, AUTH, False), (CDN, None, False), (HOME, None, False)])
for invalid in ("https://user:pass@gateway.invalid/result", "https://@gateway.invalid/result",
                "ftp://gateway.invalid/result"):
    exercise(download(invalid, foreign="anonymous"), [], [], rejects=True)
    exercise(download(HOME, foreign="anonymous"), [response(302, invalid)],
             [(HOME, AUTH, False)], rejects=True)
exercise(download(HOME), [response(302, HOME)] * 5 + [response()],
         [(HOME, AUTH, False)] * 6)
exercise(download(HOME), [response(302, HOME)] * 6,
         [(HOME, AUTH, False)] * 6, rejects=True)

diffusion = OpenAIDiffusionBackend("test", backend.api_url, 0, "SMOKE_RESULT_", api_key="test-secret")
image_response = SimpleNamespace(json=lambda: {"data": [{"url": CDN}]})
exercise(lambda: diffusion._parse_image_response(image_response), [response()],
         [(CDN, None, False)], timeout=60)
video_backend = video.OpenAIVideoBackend("test", backend.api_url, 0, "SMOKE_RESULT_", api_key="test-secret", model="test")


def poll(_backend, _job_id, **kwargs):
    return kwargs["on_done"]({"results": [{"url": CDN}]}, 1)


with patch.object(video, "submit_job", return_value="job"), patch.object(video, "poll_job", side_effect=poll):
    exercise(lambda: video_backend._generate("test", "", {"source_image_path": HOME}),
             [response()], [(CDN, None, False)], timeout=180)
mesh = OpenAIMeshBackend("test", backend.api_url, 0, "SMOKE_RESULT_", api_key="test-secret", model="test")
exercise(lambda: mesh._download_same_origin(CDN), [], [], rejects=True)
# Failed/refused downloads keep the existing empty-result and error-log contract.
for result_url, reply in ((CDN, response(403)), ("ftp://cdn.invalid/result", None)):
    with patch.object(gateway.requests, "get", return_value=reply) as get, patch("app.imagegen.backends.openai_diffusion.logger") as log:
        assert diffusion._parse_image_response(SimpleNamespace(json=lambda: {"data": [{"url": result_url}]})) == []
        assert log.error.called
        assert get.call_count == (1 if reply else 0)
    def poll_failure(_backend, _job_id, **kwargs):
        return kwargs["on_done"]({"results": [{"url": result_url}]}, 1)
    with patch.object(video, "submit_job", return_value="job"), patch.object(video, "poll_job", side_effect=poll_failure), patch.object(gateway.requests, "get", return_value=reply) as get, patch.object(video, "logger") as log:
        assert video_backend._generate("test", "", {"source_image_path": HOME}) == []
        assert log.error.called
        assert get.call_count == (1 if reply else 0)
# Diffusion connection errors remain empty results (no special outer handler).
with patch.object(gateway.requests, "get", side_effect=gateway.requests.ConnectionError("offline")), patch("app.imagegen.backends.openai_diffusion.logger") as log:
    assert diffusion._parse_image_response(image_response) == []
    assert log.error.called


# Exercise Requests preparation itself: mocking get cannot detect netrc auth.
class Transport(gateway.requests.adapters.BaseAdapter):
    def __init__(self, replies):
        self.replies = iter(replies)
        self.headers = []
        self.proxies = []

    def send(self, request, **kwargs):
        self.headers.append(dict(request.headers))
        self.proxies.append(kwargs["proxies"])
        status, location = next(self.replies)
        reply = gateway.requests.Response()
        reply.status_code = status
        reply._content = BODY
        reply.request = request
        reply.url = request.url
        if location:
            reply.headers["Location"] = location
            reply.headers["Set-Cookie"] = "secret=must-not-carry; Path=/"
        return reply

    def close(self):
        pass


with tempfile.TemporaryDirectory() as tmp:
    netrc = Path(tmp) / "netrc"
    netrc.write_text("default login x password y\n")
    with patch.dict(os.environ, {"NETRC": str(netrc),
                                 "HTTPS_PROXY": "http://proxy.invalid:8080",
                                 "NO_PROXY": ""}):
        for start, replies, expected_auth in (
                (CDN, [(200, None)], [None]),
                (HOME, [(200, None)], [AUTH["Authorization"]]),
                (CDN, [(302, HOME), (200, None)], [None, None]),
                (HOME, [(302, HOME), (200, None)], [AUTH["Authorization"]] * 2)):
            transport = Transport(replies)
            with patch.object(gateway.requests.Session, "get_adapter", return_value=transport):
                gateway.download_result(backend, start, foreign="anonymous")
            assert [h.get("Authorization") for h in transport.headers] == expected_auth, transport.headers
            assert all("Cookie" not in h for h in transport.headers)
            assert all(p.get("https") == "http://proxy.invalid:8080" for p in transport.proxies)

for api_url, result_url in (
        ("https://bücher.invalid", "https://xn--bcher-kva.invalid/result"),
        ("https://xn--bcher-kva.invalid", "https://bücher.invalid/result"),
        ("https://[::1]", "https://[::1]:443/result")):
    equivalent = SimpleNamespace(api_url=api_url, _headers=lambda: AUTH)
    exercise(lambda: gateway.download_result(equivalent, result_url),
             [response()], [(result_url, AUTH, False)])

with patch.object(diffusion, "_post_gateway", return_value=image_response), patch.object(gateway.requests, "get", side_effect=gateway.requests.Timeout("result timeout")):
    try:
        diffusion._generate("test", "", {})
    except BackendBusyError:
        pass
    else:
        raise AssertionError("Diffusion result timeout must remain BackendBusyError")

# Video download network failures must reach poll_job's existing retry handler.
for error in (gateway.requests.Timeout, gateway.requests.ConnectionError):
    with patch.object(video, "submit_job", return_value="job"), patch.object(video, "poll_job", side_effect=poll), patch.object(gateway.requests, "get", side_effect=error("offline")):
        try:
            video_backend._generate("test", "", {"source_image_path": HOME})
        except error:
            pass
        else:
            raise AssertionError("Video network failure must reach the poll handler")
# A transient video result network failure retries the completed job download.
for error in (gateway.requests.Timeout, gateway.requests.ConnectionError):
    downloads = []

    def get_video(url, **kwargs):
        if url == f"{backend.api_url}/v1/jobs/job":
            return SimpleNamespace(status_code=200, content=b"status",
                                   json=lambda: {"status": "done", "results": [{"url": CDN}]})
        assert url == CDN
        downloads.append(url)
        if len(downloads) == 1:
            raise error("offline")
        return response()

    with patch.object(video, "submit_job", return_value="job"), patch.object(gateway.time, "sleep"), patch.object(gateway.requests, "get", side_effect=get_video), patch.object(gateway.requests, "post") as cancel, patch.object(gateway, "logger"), patch.object(video, "logger"):
        assert video_backend._generate("test", "", {"source_image_path": HOME}) == [BODY]
        assert len(downloads) == 2
        cancel.assert_not_called()
print("All result-download authentication checks passed")
