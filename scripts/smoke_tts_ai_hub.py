"""Smoke test for AI-Hub TTS discovery, schema mapping, and generic character config."""
from __future__ import annotations

import base64
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.core.tts_ai_hub import (
    _write_compatible_audio,
    discover_ai_hub_tts,
    format_language_for_alias,
    generate_ai_hub_tts,
    parse_tts_alias_schema,
)
from app.core.tts_service import (
    CLONE_VOICE_PREFIX,
    TTSService,
    list_local_cloned_voices,
    split_generic_voice,
)


def test_schema_parsing_fallback_and_contract():
    # 1. ZONOS3-Mini fallback (current hub schema without explicit tts block or voice choices)
    zonos_raw = {
        "alias": "ZONOS3-Mini",
        "backends": ["dx10-02", "rtx-3090"],
        "params": [
            {"name": "text", "type": "string", "default": "Hallo"},
            {"name": "voice", "type": "string", "default": "Wolfgang"},
            {"name": "language", "type": "string", "default": "de"},
            {"name": "reference_audio", "type": "string", "default": ""},
            {"name": "speaking_rate", "type": "float", "default": 0.0},
        ],
        "files": [{"name": "reference_audio", "required": False}],
        "modes": ["sync", "async"],
    }
    z = parse_tts_alias_schema("ZONOS3-Mini", zonos_raw, local=True)
    assert z is not None
    assert z.text_param == "text"
    assert z.voice_param == "voice"
    assert [v["value"] for v in z.voices] == ["Wolfgang"]
    assert z.clone_supported and not z.clone_required
    assert z.clone_file_slot == "reference_audio"
    assert z.language_format == "iso639_1"
    assert format_language_for_alias("de", z) == "de"
    assert z.extra_param_meta()["kind"] == "speed"
    assert z.extra_param_meta()["param"] == "speaking_rate"

    # 2. ming-3.0-tts-0.5b fallback (clone-only + English language name + reference_text)
    ming_raw = {
        "alias": "ming-3.0-tts-0.5b",
        "backends": ["rtx-3090"],
        "params": [
            {"name": "text", "type": "string", "default": "Hallo"},
            {"name": "reference_audio", "type": "string", "default": "ming_us_james_reference.flac"},
            {"name": "reference_text", "type": "string", "default": "Hello, this is James."},
            {"name": "language", "type": "string", "default": "German"},
        ],
        "files": [{"name": "reference_audio", "required": False}],
        "modes": ["sync", "async"],
    }
    m = parse_tts_alias_schema("ming-3.0-tts-0.5b", ming_raw, local=True)
    assert m is not None
    assert m.voice_param is None
    assert m.voices == []
    assert m.clone_supported and m.clone_required
    assert m.clone_reference_text_param == "reference_text"
    assert m.language_format == "english_name"
    assert format_language_for_alias("de", m) == "German"
    assert format_language_for_alias("en", m) == "English"
    assert m.extra_param_meta() is None

    # 3. Music model under ai-hub (tts) must be rejected
    music_raw = {
        "alias": "ACE-Step-1.5-XL",
        "params": [
            {"name": "prompt", "type": "string", "default": ""},
            {"name": "lyrics", "type": "string", "default": "[Instrumental]"},
            {"name": "bpm", "type": "int", "default": 120},
        ],
        "files": [],
    }
    assert parse_tts_alias_schema("ACE-Step-1.5-XL", music_raw, local=True) is None

    # 4. Explicit AI-Hub `tts` contract block takes full precedence
    zonos_v2 = dict(zonos_raw)
    zonos_v2["tts"] = {
        "task": "tts",
        "text_param": "text",
        "language_param": "language",
        "language_format": "iso639_1",
        "language_choices": ["de", "en"],
        "voice_param": "voice",
        "voices": [
            {"id": "Wolfgang", "label": "Wolfgang", "gender": "male"},
            {"id": "Klara", "label": "Klara", "gender": "female"},
        ],
        "clone": {
            "supported": True,
            "required": False,
            "file_slot": "reference_audio",
            "accept": ["wav", "flac"],
            "reference_text_param": None,
            "overrides_voice": True,
        },
        "controls": {
            "speed": {"param": "speaking_rate", "default": 0.0, "min": -1.0, "max": 1.0, "neutral": 0.0},
            "style": None,
        },
        "preferred_mode": "sync",
        "output_format": "wav",
    }
    z2 = parse_tts_alias_schema("ZONOS3-Mini", zonos_v2, local=True)
    assert z2 is not None and z2.has_explicit_tts_block
    assert [v["value"] for v in z2.voices] == ["Wolfgang", "Klara"]
    assert z2.voices[0]["label"] == "Wolfgang (male)"
    assert z2.extra_param_meta()["min"] == -1.0

    # 5. Style control priority over speed (e.g. Venice Qwen3 TTS)
    qwen_raw = {
        "alias": "venice.ai/tts-qwen3-1-7b",
        "params": [
            {"name": "input", "type": "string", "required": True},
            {"name": "prompt", "type": "string"},
            {"name": "speed", "type": "float"},
            {"name": "voice", "type": "string", "choices": ["Aiden", "Vivian"]},
        ],
        "files": [],
    }
    q = parse_tts_alias_schema("venice.ai/tts-qwen3-1-7b", qwen_raw, local=False)
    assert q is not None
    assert q.text_param == "input"
    assert q.style_param == "prompt"
    assert q.extra_param_meta()["kind"] == "style"


def test_generic_voice_and_character_config():
    assert split_generic_voice("Wolfgang", "") == ("Wolfgang", "")
    assert split_generic_voice(f"{CLONE_VOICE_PREFIX}./voices/ANNE_ref.wav", "") == ("", "./voices/ANNE_ref.wav")
    assert split_generic_voice("", "./voices/DAVID_ref.wav") == ("", "./voices/DAVID_ref.wav")
    assert split_generic_voice("Wolfgang", "./voices/DAVID_ref.wav") == ("Wolfgang", "")

    svc = TTSService()
    cfg = svc.get_character_config({
        "tts_enabled": True,
        "tts_auto": False,
        "tts_model": "hub:ZONOS3-Mini",
        "tts_voice": "clone:./voices/ANNE_ref.wav",
        "tts_param": "0.15",
        "tts_language": "de",
    })
    assert cfg["model"] == "hub:ZONOS3-Mini"
    assert cfg["voice"] == ""
    assert cfg["speaker_wav"] == "./voices/ANNE_ref.wav"
    assert cfg["param"] == "0.15"

    # Legacy character with only tts_speaker_wav still works
    legacy_cfg = svc.get_character_config({
        "tts_speaker_wav": "./voices/DAVID_ref.wav",
        "tts_language": "de",
    })
    assert legacy_cfg["speaker_wav"] == "./voices/DAVID_ref.wav"
    assert legacy_cfg["voice"] == ""


def test_generate_payload_and_sidecar():
    ming_spec = parse_tts_alias_schema("ming-3.0-tts-0.5b", {
        "params": [
            {"name": "text", "type": "string"},
            {"name": "reference_text", "type": "string"},
            {"name": "language", "type": "string", "default": "German"},
        ],
        "files": [{"name": "reference_audio", "required": False}],
        "modes": ["sync"],
    }, local=True)
    assert ming_spec is not None

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        wav_path = td_path / "sample.wav"
        wav_path.write_bytes(b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 40)
        (td_path / "sample.txt").write_text("Das ist mein Referenztext.", encoding="utf-8")

        fake_wav = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 60
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"content-type": "audio/wav"}
        mock_resp.content = fake_wav

        captured = {}
        def fake_post(url, json=None, headers=None, timeout=None):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return mock_resp

        with patch("app.core.tts_ai_hub.requests.post", side_effect=fake_post):
            out = generate_ai_hub_tts(
                "http://127.0.0.1:4000",
                "secret-key",
                ming_spec,
                text="Hallo Welt",
                speaker_wav=str(wav_path),
                language="de",
                out_dir=td_path,
            )

        assert out is not None and out.exists() and out.suffix == ".wav"
        assert captured["url"] == "http://127.0.0.1:4000/v1/generations"
        assert captured["json"]["model"] == "ming-3.0-tts-0.5b"
        assert captured["json"]["params"]["text"] == "Hallo Welt"
        assert captured["json"]["params"]["language"] == "German"
        assert captured["json"]["params"]["reference_text"] == "Das ist mein Referenztext."
        assert captured["json"]["files"]["reference_audio"].startswith("data:audio/wav;base64,")
        decoded = base64.b64decode(captured["json"]["files"]["reference_audio"].split(",", 1)[1])
        assert decoded == wav_path.read_bytes()


def test_template_and_live_discovery():
    # Validate base-character.json has special: tts_config
    tmpl = json.loads(Path("shared/templates/character/base-character.json").read_text(encoding="utf-8"))
    tts_sec = [s for s in tmpl["sections"] if s.get("id") == "tts_config"]
    assert len(tts_sec) == 1 and tts_sec[0].get("special") == "tts_config"
    keys = [f["key"] for f in tts_sec[0]["fields"]]
    assert keys == ["tts_enabled", "tts_auto", "tts_model", "tts_voice", "tts_param"], keys

    # Validate local cloned voices listing skips duplicate _norm when original exists
    cloned = list_local_cloned_voices()
    assert all(c["value"].startswith("clone:./voices/") for c in cloned)

    # Live read-only discovery check against configured AI-Hub if reachable
    from app.core.config import load as load_cfg
    inst_cfg = Path("instance/config.json")
    load_cfg(instance_path=inst_cfg if inst_cfg.exists() else None)
    hub_url = os.environ.get("TTS_AI_HUB_URL", "")
    hub_key = os.environ.get("TTS_AI_HUB_API_KEY", "")
    if hub_url:
        ok, specs = discover_ai_hub_tts(hub_url, hub_key)
        print(f"Live AI-Hub discovery ({hub_url}): reachable={ok}, aliases={sorted(specs.keys())}")
        if ok:
            assert "ZONOS3-Mini" in specs
            assert "ming-3.0-tts-0.5b" in specs
            assert "ACE-Step-1.5-XL" not in specs
            for alias, sp in specs.items():
                print("  CAP:", json.dumps(sp.to_capability_dict(), ensure_ascii=False))

    # End-to-end TTSService.capabilities() check
    svc = TTSService()
    caps = svc.capabilities()
    model_ids = [m["id"] for m in caps["models"]]
    assert "xtts" in model_ids and "magpie" in model_ids and "f5" in model_ids
    if hub_url and "hub:ZONOS3-Mini" in model_ids:
        print("TTSService.capabilities() models:", model_ids)


def test_flac_transcodes_to_wav():
    sample_flacs = sorted(Path("worlds/Anima Divide/tmp/tts_audio").glob("*.flac"))
    if not sample_flacs:
        return
    flac_bytes = sample_flacs[0].read_bytes()
    assert flac_bytes[:4] == b"fLaC"
    with tempfile.TemporaryDirectory() as td:
        out = _write_compatible_audio(flac_bytes, ".flac", Path(td))
        assert out.suffix == ".wav", out.name
        wav_bytes = out.read_bytes()
        assert wav_bytes[:4] == b"RIFF" and wav_bytes[8:12] == b"WAVE"
        assert len(wav_bytes) > 1000
        # No leftover _src.flac file
        assert list(Path(td).glob("*_src*")) == []


if __name__ == "__main__":
    test_schema_parsing_fallback_and_contract()
    test_generic_voice_and_character_config()
    test_generate_payload_and_sidecar()
    test_flac_transcodes_to_wav()
    test_template_and_live_discovery()
    print("ALL TTS AI-HUB SMOKE CHECKS PASSED!")
