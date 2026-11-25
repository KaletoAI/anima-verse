"""AI-Hub TTS discovery and generation client.

Consumes Text-to-Speech aliases exposed by the AI-Hub gateway via:
  - ``GET  /v1/models``                    (alias list)
  - ``GET  /v1/generations/{alias}/schema`` (parameters, voices, clone slots)
  - ``POST /v1/generations``               (sync or async audio synthesis)
  - ``GET  /v1/jobs/{job_id}``             (async polling fallback)

Schema contract:
  If the AI-Hub schema includes the standardized top-level ``tts`` block, its
  declarations win directly. Until then (or for third-party cloud aliases),
  the exact same :class:`TTSAliasSpec` is inferred from ``params[]`` and
  ``files[]`` so local aliases such as ``ZONOS3-Mini`` and ``ming-3.0-tts-0.5b``
  work immediately and gain full voice lists as soon as AI-Hub publishes them.
"""
from __future__ import annotations

import base64
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
from urllib.parse import quote, urljoin

import requests

from app.core.log import get_logger

logger = get_logger("tts_ai_hub")

HUB_MODEL_PREFIX = "hub:"

# ISO-639-1 -> English language name (for aliases like ming-3.0-tts-0.5b or Qwen3-TTS)
_ISO_TO_ENGLISH: Dict[str, str] = {
    "de": "German",
    "en": "English",
    "fr": "French",
    "es": "Spanish",
    "it": "Italian",
    "pt": "Portuguese",
    "ru": "Russian",
    "ja": "Japanese",
    "ko": "Korean",
    "zh": "Chinese",
    "nl": "Dutch",
    "pl": "Polish",
    "tr": "Turkish",
    "ar": "Arabic",
    "hi": "Hindi",
    "sv": "Swedish",
    "da": "Danish",
    "fi": "Finnish",
    "no": "Norwegian",
    "cs": "Czech",
    "el": "Greek",
    "he": "Hebrew",
    "uk": "Ukrainian",
}

_AUDIO_EXT_BY_MIME: Dict[str, str] = {
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/wave": ".wav",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/flac": ".flac",
    "audio/x-flac": ".flac",
    "audio/ogg": ".ogg",
    "audio/opus": ".opus",
    "audio/aac": ".aac",
    "audio/mp4": ".m4a",
}

_MIME_BY_EXT: Dict[str, str] = {
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".flac": "audio/flac",
    ".ogg": "audio/ogg",
    ".opus": "audio/opus",
    ".m4a": "audio/mp4",
}

# Non-TTS param signatures (e.g. ACE-Step music models listed under ai-hub (tts))
_NON_TTS_PARAMS = frozenset({"lyrics", "bpm", "timesignature", "keyscale"})


@dataclass
class TTSAliasSpec:
    """Normalized capabilities of a single AI-Hub TTS alias."""

    alias: str
    local: bool = True
    backends: List[str] = field(default_factory=list)
    modes: List[str] = field(default_factory=lambda: ["sync", "async"])
    preferred_mode: str = "sync"
    text_param: str = "text"
    language_param: Optional[str] = None
    language_format: str = "iso639_1"
    language_choices: List[str] = field(default_factory=list)
    voice_param: Optional[str] = None
    voices: List[Dict[str, Any]] = field(default_factory=list)
    default_voice: str = ""
    clone_supported: bool = False
    clone_required: bool = False
    clone_file_slot: str = ""
    clone_accept: List[str] = field(default_factory=lambda: ["wav", "mp3", "flac", "ogg"])
    clone_reference_text_param: Optional[str] = None
    clone_overrides_voice: bool = True
    style_param: Optional[str] = None
    speed_param: Optional[str] = None
    speed_default: Optional[float] = None
    speed_min: Optional[float] = None
    speed_max: Optional[float] = None
    speed_neutral: Optional[float] = None
    output_format: str = "wav"
    has_explicit_tts_block: bool = False

    @property
    def model_id(self) -> str:
        return f"{HUB_MODEL_PREFIX}{self.alias}"

    @property
    def label(self) -> str:
        suffix = "AI-Hub lokal" if self.local else "AI-Hub"
        return f"{self.alias} ({suffix})"

    def extra_param_meta(self) -> Optional[Dict[str, Any]]:
        """The ONE generic character-level extra parameter for this alias."""
        if self.style_param:
            return {
                "kind": "style",
                "param": self.style_param,
                "label": "Voice style",
                "label_de": "Stimm-Stil",
                "placeholder": "e.g. calm, warm, slightly raspy",
                "placeholder_de": "z. B. ruhig, warm, leicht rauchig",
                "hint": f"Style / emotion hint sent to '{self.style_param}' (optional)",
                "hint_de": f"Stil-/Emotionshinweis für '{self.style_param}' (optional)",
            }
        if self.speed_param:
            neutral = self.speed_neutral if self.speed_neutral is not None else (
                0.0 if self.speed_param == "speaking_rate" else 1.0
            )
            is_rate_auto_zero = (
                neutral == 0.0
                and self.speed_min is not None
                and self.speed_min >= 0.0
                and self.speed_max is not None
                and self.speed_max > 2.0
            )
            is_offset = (neutral == 0.0 and not is_rate_auto_zero)
            return {
                "kind": "speed",
                "param": self.speed_param,
                "label": "Speaking rate",
                "label_de": "Sprechtempo",
                "default": self.speed_default,
                "neutral": neutral,
                "min": self.speed_min,
                "max": self.speed_max,
                "placeholder": str(neutral),
                "placeholder_de": str(neutral),
                "hint": (
                    f"Speaking rate (0 = auto, {self.speed_min:g}–{self.speed_max:g}; higher = faster)"
                    if is_rate_auto_zero else
                    "Speaking rate offset (0 = normal, negative = slower, positive = faster)"
                    if is_offset else
                    "Speed multiplier (1.0 = normal, e.g. 0.85 slower, 1.15 faster)"
                ),
                "hint_de": (
                    f"Sprechtempo (0 = automatisch, {self.speed_min:g}–{self.speed_max:g}; höher = schneller)"
                    if is_rate_auto_zero else
                    "Sprechtempo-Abweichung (0 = normal, negativ = langsamer, positiv = schneller)"
                    if is_offset else
                    "Sprechtempo-Faktor (1.0 = normal, z. B. 0.85 langsamer, 1.15 schneller)"
                ),
            }
        return None

    def to_capability_dict(self) -> Dict[str, Any]:
        return {
            "id": self.model_id,
            "alias": self.alias,
            "label": self.label,
            "source": "ai_hub_local" if self.local else "ai_hub_cloud",
            "available": True,
            "voices": [
                {"value": str(v.get("value") or v.get("id") or ""), "label": str(v.get("label") or v.get("value") or v.get("id") or "")}
                for v in self.voices
                if (v.get("value") or v.get("id"))
            ],
            "default_voice": self.default_voice,
            "supports_clone": self.clone_supported,
            "clone_required": self.clone_required,
            "extra_param": self.extra_param_meta(),
        }


def _params_by_name(schema: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    raw = schema.get("params") or []
    out: Dict[str, Dict[str, Any]] = {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            name = str(k).strip()
            if name:
                out[name] = v if isinstance(v, dict) else {"name": name}
    elif isinstance(raw, list):
        for entry in raw:
            if isinstance(entry, dict):
                name = str(entry.get("name") or "").strip()
                if name:
                    out[name] = entry
            elif isinstance(entry, str) and entry.strip():
                out[entry.strip()] = {"name": entry.strip()}
    return out


def _files_by_name(schema: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    raw = schema.get("files") or []
    out: Dict[str, Dict[str, Any]] = {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            name = str(k).strip()
            if name:
                out[name] = v if isinstance(v, dict) else {"name": name}
    elif isinstance(raw, list):
        for entry in raw:
            if isinstance(entry, dict):
                name = str(entry.get("name") or "").strip()
                if name:
                    out[name] = entry
            elif isinstance(entry, str) and entry.strip():
                out[entry.strip()] = {"name": entry.strip()}
    return out


def _infer_language_format(param_def: Dict[str, Any]) -> str:
    choices = [str(c) for c in (param_def.get("choices") or []) if c is not None]
    default = str(param_def.get("default") or "").strip()
    samples = ([default] if default else []) + choices[:20]
    for s in samples:
        if not s or s.lower() in ("auto", "none"):
            continue
        if len(s) == 5 and s[2] == "-":
            return "bcp47"
        if s in ("German", "English", "French", "Spanish", "Chinese"):
            return "english_name"
        if s in ("german", "english", "french", "spanish", "chinese"):
            return "english_name_lower"
        if len(s) == 2 and s.islower():
            return "iso639_1"
    return "iso639_1"


def _normalize_voices(raw_voices: Any) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen = set()
    if not isinstance(raw_voices, list):
        return out
    for item in raw_voices:
        if isinstance(item, dict):
            vid = str(item.get("id") or item.get("value") or item.get("name") or "").strip()
            if not vid or vid in seen:
                continue
            seen.add(vid)
            label = str(item.get("label") or vid).strip()
            gender = str(item.get("gender") or "").strip()
            langs = item.get("languages")
            if gender and gender.lower() not in label.lower():
                label = f"{label} ({gender})"
            entry: Dict[str, Any] = {"value": vid, "label": label}
            if gender:
                entry["gender"] = gender
            if isinstance(langs, list) and langs:
                entry["languages"] = [str(x) for x in langs]
            out.append(entry)
        elif item is not None:
            vid = str(item).strip()
            if vid and vid not in seen:
                seen.add(vid)
                out.append({"value": vid, "label": vid})
    return out


def _opt_float(val: Any) -> Optional[float]:
    if val is None or val == "":
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def parse_tts_alias_schema(
    alias: str,
    schema: Dict[str, Any],
    *,
    local: bool = True,
) -> Optional[TTSAliasSpec]:
    """Parses ``GET /v1/generations/{alias}/schema`` into a :class:`TTSAliasSpec`.

    Returns ``None`` if the alias is not a TTS model (e.g. music/STT).
    """
    if not isinstance(schema, dict):
        return None

    params = _params_by_name(schema)
    files = _files_by_name(schema)
    tts_block = schema.get("tts") if isinstance(schema.get("tts"), dict) else None

    if tts_block:
        task = str(tts_block.get("task") or "tts").strip().lower()
        if task and task != "tts":
            return None
    else:
        if _NON_TTS_PARAMS & set(params.keys()):
            return None

    # 1. Text parameter
    text_param = str((tts_block or {}).get("text_param") or "").strip()
    if not text_param:
        for cand in ("text", "input", "prompt"):
            if cand in params:
                text_param = cand
                break
    if not text_param:
        return None

    # 2. Voice parameter + choices
    voice_param: Optional[str] = None
    if tts_block and "voice_param" in tts_block:
        vp = tts_block.get("voice_param")
        voice_param = str(vp).strip() if vp else None
    else:
        for cand in ("voice", "speaker", "speaker_name", "speakers"):
            if cand in params:
                voice_param = cand
                break

    voices: List[Dict[str, Any]] = []
    default_voice = ""
    if tts_block and isinstance(tts_block.get("voices"), list):
        voices = _normalize_voices(tts_block.get("voices"))
    if voice_param and voice_param in params:
        vp_def = params[voice_param]
        default_voice = str(vp_def.get("default") or "").strip()
        if not voices and isinstance(vp_def.get("choices"), list):
            voices = _normalize_voices(vp_def.get("choices"))
        if not voices and default_voice:
            voices = [{"value": default_voice, "label": default_voice}]
    if not default_voice and voices:
        default_voice = str(voices[0]["value"])

    # 3. Voice cloning slot
    clone_supported = False
    clone_required = False
    clone_file_slot = ""
    clone_accept = ["wav", "mp3", "flac", "ogg"]
    clone_reference_text_param: Optional[str] = None
    clone_overrides_voice = True

    clone_block = (tts_block or {}).get("clone") if isinstance((tts_block or {}).get("clone"), dict) else None
    if clone_block is not None:
        clone_supported = bool(clone_block.get("supported", False))
        clone_required = bool(clone_block.get("required", False))
        clone_file_slot = str(clone_block.get("file_slot") or "").strip()
        if isinstance(clone_block.get("accept"), list) and clone_block["accept"]:
            clone_accept = [str(x).lstrip(".").lower() for x in clone_block["accept"]]
        rt = clone_block.get("reference_text_param")
        clone_reference_text_param = str(rt).strip() if rt else None
        if "overrides_voice" in clone_block:
            clone_overrides_voice = bool(clone_block["overrides_voice"])
    else:
        for slot_cand in ("reference_audio", "input_audio", "speaker_audio", "voice_sample"):
            if slot_cand in files:
                fdef = files[slot_cand]
                clone_supported = True
                clone_file_slot = slot_cand
                clone_required = bool(fdef.get("required")) or (voice_param is None)
                if isinstance(fdef.get("accept"), list) and fdef["accept"]:
                    clone_accept = [str(x).lstrip(".").lower() for x in fdef["accept"]]
                break
        if clone_supported and "reference_text" in params:
            clone_reference_text_param = "reference_text"

    # Must support at least preset voices or voice cloning (otherwise e.g. SFX)
    if not voice_param and not clone_supported:
        return None

    # 4. Language parameter
    language_param: Optional[str] = None
    language_format = "iso639_1"
    language_choices: List[str] = []
    if tts_block and "language_param" in tts_block:
        lp = tts_block.get("language_param")
        language_param = str(lp).strip() if lp else None
        language_format = str(tts_block.get("language_format") or "iso639_1").strip()
        if isinstance(tts_block.get("language_choices"), list):
            language_choices = [str(x) for x in tts_block["language_choices"]]
    else:
        for cand in ("language", "language_code", "lang_code"):
            if cand in params:
                language_param = cand
                language_format = _infer_language_format(params[cand])
                if isinstance(params[cand].get("choices"), list):
                    language_choices = [str(x) for x in params[cand]["choices"]]
                break
    if language_param and not language_choices and language_param in params:
        if isinstance(params[language_param].get("choices"), list):
            language_choices = [str(x) for x in params[language_param]["choices"]]

    # 5. Character controls: style & speed
    style_param: Optional[str] = None
    speed_param: Optional[str] = None
    speed_default: Optional[float] = None
    speed_min: Optional[float] = None
    speed_max: Optional[float] = None
    speed_neutral: Optional[float] = None

    controls = (tts_block or {}).get("controls") if isinstance((tts_block or {}).get("controls"), dict) else None
    if controls is not None:
        st = controls.get("style")
        if isinstance(st, dict) and st.get("param"):
            style_param = str(st["param"]).strip()
        elif isinstance(st, str) and st.strip():
            style_param = st.strip()
        sp = controls.get("speed")
        if isinstance(sp, dict) and sp.get("param"):
            speed_param = str(sp["param"]).strip()
            speed_default = _opt_float(sp.get("default"))
            speed_min = _opt_float(sp.get("min"))
            speed_max = _opt_float(sp.get("max"))
            speed_neutral = _opt_float(sp.get("neutral"))
        elif isinstance(sp, str) and sp.strip():
            speed_param = sp.strip()
    else:
        for cand in ("instruction", "instructions", "voice_description"):
            if cand in params:
                style_param = cand
                break
        if not style_param and text_param == "input" and "prompt" in params:
            # e.g. venice.ai/tts-qwen3-*: input = text, prompt = voice style instruction
            style_param = "prompt"
        for cand in ("speaking_rate", "speed"):
            if cand in params:
                speed_param = cand
                pdef = params[cand]
                speed_default = _opt_float(pdef.get("default"))
                speed_min = _opt_float(pdef.get("min"))
                speed_max = _opt_float(pdef.get("max"))
                speed_neutral = 0.0 if cand == "speaking_rate" else 1.0
                break

    modes = [str(m) for m in (schema.get("modes") or ["sync", "async"]) if m]
    preferred_mode = str((tts_block or {}).get("preferred_mode") or "").strip().lower()
    if preferred_mode not in ("sync", "async"):
        preferred_mode = "sync" if "sync" in modes else (modes[0] if modes else "sync")

    output_format = str((tts_block or {}).get("output_format") or "wav").strip().lower().lstrip(".")
    if not output_format and "response_format" in params:
        output_format = str(params["response_format"].get("default") or "mp3").strip().lower()

    return TTSAliasSpec(
        alias=alias,
        local=local,
        backends=[str(b) for b in (schema.get("backends") or []) if b],
        modes=modes,
        preferred_mode=preferred_mode,
        text_param=text_param,
        language_param=language_param,
        language_format=language_format,
        language_choices=language_choices,
        voice_param=voice_param,
        voices=voices,
        default_voice=default_voice,
        clone_supported=clone_supported,
        clone_required=clone_required,
        clone_file_slot=clone_file_slot,
        clone_accept=clone_accept,
        clone_reference_text_param=clone_reference_text_param,
        clone_overrides_voice=clone_overrides_voice,
        style_param=style_param,
        speed_param=speed_param,
        speed_default=speed_default,
        speed_min=speed_min,
        speed_max=speed_max,
        speed_neutral=speed_neutral,
        output_format=output_format or "wav",
        has_explicit_tts_block=tts_block is not None,
    )


def format_language_for_alias(language: str, spec: TTSAliasSpec) -> Optional[str]:
    """Converts a character ISO language code (e.g. ``'de'``) to what the alias expects."""
    raw = (language or "").strip()
    if not raw or not spec.language_param:
        return None
    iso2 = raw.split("-")[0].split("_")[0].lower()
    eng = _ISO_TO_ENGLISH.get(iso2, raw)

    fmt = (spec.language_format or "iso639_1").lower()
    if fmt == "english_name":
        candidate = eng
    elif fmt == "english_name_lower":
        candidate = eng.lower()
    elif fmt == "bcp47":
        candidate = raw if "-" in raw else f"{iso2}-{iso2.upper()}"
    elif fmt == "raw":
        candidate = raw
    else:
        candidate = iso2

    if spec.language_choices:
        lower_map = {c.lower(): c for c in spec.language_choices}
        for probe in (candidate, raw, iso2, eng, eng.lower()):
            if probe.lower() in lower_map:
                return lower_map[probe.lower()]
        if "auto" in lower_map:
            return lower_map["auto"]
        return None

    return candidate


def _is_cloud_tts_candidate(model_id: str, owned_by: str) -> bool:
    low = model_id.lower()
    ob = owned_by.lower()
    if ob not in ("venice.ai", "wiro", "lulabs"):
        return False
    if any(skip in low for skip in ("whisper", "music", "sfx", "sound-effects", "dubbing", "isolation", "alignment", "scribe", "speech-to-text", "voice-changer", "lipsync", "video", "image")):
        return False
    return any(tok in low for tok in ("/tts-", "tts", "voice-clone", "chatterbox", "vibevoice", "kokoro", "omnivoice", "fishaudio/s2"))


def discover_ai_hub_tts(
    hub_url: str,
    api_key: str = "",
    *,
    default_alias: str = "",
    extra_aliases: Sequence[str] = (),
    include_cloud: bool = False,
    timeout: int = 10,
) -> Tuple[bool, Dict[str, TTSAliasSpec]]:
    """Queries AI-Hub ``/v1/models`` and ``/v1/generations/{alias}/schema``.

    Returns ``(reachable, {alias: TTSAliasSpec})``.
    """
    base = (hub_url or "").strip().rstrip("/")
    if not base:
        return False, {}
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    try:
        resp = requests.get(f"{base}/v1/models", headers=headers, timeout=timeout)
        if resp.status_code != 200:
            logger.warning("AI-Hub TTS discovery: /v1/models HTTP %d", resp.status_code)
            return False, {}
        body = resp.json()
        models = body.get("data", body) if isinstance(body, dict) else body
        if not isinstance(models, list):
            return False, {}
    except Exception as e:
        logger.warning("AI-Hub TTS discovery failed: %s", e)
        return False, {}

    # Build ordered list of (alias, is_local)
    candidates: List[Tuple[str, bool]] = []
    seen = set()
    by_id: Dict[str, Dict[str, Any]] = {}
    for entry in models:
        if isinstance(entry, dict) and entry.get("id"):
            by_id[str(entry["id"])] = entry

    for entry in models:
        if not isinstance(entry, dict):
            continue
        mid = str(entry.get("id") or "").strip()
        if not mid or mid in seen:
            continue
        owned_by = str(entry.get("owned_by") or "").strip()
        task = str(entry.get("task") or "").strip().lower()
        explicit_local = entry.get("local")
        is_local = (
            bool(explicit_local)
            if isinstance(explicit_local, bool)
            else owned_by.lower() == "ai-hub (tts)"
        )

        if task:
            if task != "tts":
                continue
            if not is_local and not include_cloud:
                continue
            candidates.append((mid, is_local))
            seen.add(mid)
        elif owned_by.lower() == "ai-hub (tts)":
            candidates.append((mid, True))
            seen.add(mid)
        elif include_cloud and _is_cloud_tts_candidate(mid, owned_by):
            candidates.append((mid, False))
            seen.add(mid)

    # Always include explicitly configured default_alias and extra_aliases
    explicit_list = ([default_alias.strip()] if default_alias.strip() else []) + [
        a.strip() for a in extra_aliases if a and a.strip()
    ]
    for alias in explicit_list:
        if alias in seen:
            continue
        entry = by_id.get(alias) or {}
        owned_by = str(entry.get("owned_by") or "")
        is_local = (
            bool(entry["local"])
            if isinstance(entry.get("local"), bool)
            else (owned_by.lower() == "ai-hub (tts)" or "/" not in alias)
        )
        candidates.append((alias, is_local))
        seen.add(alias)

    specs: Dict[str, TTSAliasSpec] = {}
    for alias, is_local in candidates:
        # Preserve slashes for namespaced cloud aliases like venice.ai/tts-kokoro
        encoded = quote(alias, safe="/")
        try:
            sr = requests.get(
                f"{base}/v1/generations/{encoded}/schema",
                headers=headers,
                timeout=timeout,
            )
            if sr.status_code != 200:
                logger.debug("AI-Hub TTS schema %s: HTTP %d", alias, sr.status_code)
                continue
            sd = sr.json() if sr.content else {}
            spec = parse_tts_alias_schema(alias, sd, local=is_local)
            if spec is None:
                logger.debug("AI-Hub alias '%s' skipped (not a TTS schema)", alias)
                continue
            specs[alias] = spec
            logger.info(
                "AI-Hub TTS alias '%s' ready (local=%s, voices=%d, clone=%s, extra=%s)",
                alias,
                spec.local,
                len(spec.voices),
                spec.clone_file_slot if spec.clone_supported else "no",
                (spec.extra_param_meta() or {}).get("kind", "-"),
            )
        except Exception as e:
            logger.debug("AI-Hub TTS schema error for '%s': %s", alias, e)

    return True, specs


def _read_sidecar_transcript(audio_path: Path) -> str:
    """Reads an optional sidecar ``.txt`` transcript next to a reference audio."""
    candidates = [audio_path.with_suffix(".txt")]
    if audio_path.stem.endswith("_norm"):
        orig_stem = audio_path.stem[:-5]
        candidates.append(audio_path.parent / f"{orig_stem}.txt")
    for cand in candidates:
        if cand.exists():
            try:
                txt = cand.read_text(encoding="utf-8").strip()
                if txt:
                    return txt
            except OSError:
                pass
    return ""


def _guess_audio_ext(content_type: str, data: bytes, fallback: str = "wav") -> str:
    ct = (content_type or "").split(";")[0].strip().lower()
    if ct in _AUDIO_EXT_BY_MIME:
        return _AUDIO_EXT_BY_MIME[ct]
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return ".wav"
    if data[:4] == b"fLaC":
        return ".flac"
    if data[:4] == b"OggS":
        return ".ogg"
    if data[:3] == b"ID3" or (len(data) >= 2 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0):
        return ".mp3"
    ext = (fallback or "wav").lstrip(".").lower()
    return f".{ext}"


def _is_native_client_audio(ext: str, data: bytes) -> bool:
    """True when the container is directly decodable by the Native (Godot) client
    AND browsers: WAV (PCM), MP3, or Ogg Vorbis (not FLAC / Ogg-Opus / AAC)."""
    if ext == ".wav" and data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return True
    if ext == ".mp3" and (
        data[:3] == b"ID3"
        or (len(data) >= 2 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0)
    ):
        return True
    if ext == ".ogg" and data[:4] == b"OggS" and b"OpusHead" not in data[:128]:
        return True
    return False


def _write_compatible_audio(raw: bytes, ext: str, out_dir: Path) -> Path:
    """Writes synthesized audio, transcoding unsupported containers (e.g. FLAC
    from ComfyUI) to 16-bit PCM WAV so the Native Godot client can play them."""
    stem = uuid.uuid4().hex
    if _is_native_client_audio(ext, raw):
        out_path = out_dir / f"{stem}{ext}"
        out_path.write_bytes(raw)
        return out_path

    src_path = out_dir / f"{stem}_src{ext}"
    wav_path = out_dir / f"{stem}.wav"
    src_path.write_bytes(raw)
    try:
        res = subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src_path), "-c:a", "pcm_s16le", str(wav_path)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if res.returncode == 0 and wav_path.exists() and wav_path.stat().st_size > 44:
            src_path.unlink(missing_ok=True)
            return wav_path
        logger.warning(
            "AI-Hub TTS audio transcode (%s -> .wav) failed (rc=%d): %s",
            ext, res.returncode, (res.stderr or "")[:200],
        )
    except FileNotFoundError:
        logger.warning("ffmpeg not available — serving raw %s audio (Native client requires WAV/MP3/OGG)", ext)
    except Exception as e:
        logger.warning("AI-Hub TTS audio transcode (%s -> .wav) error: %s", ext, e)

    wav_path.unlink(missing_ok=True)
    fallback_path = out_dir / f"{stem}{ext}"
    src_path.rename(fallback_path)
    return fallback_path


def _extract_audio_from_json(
    body: Dict[str, Any],
    *,
    base_url: str,
    headers: Dict[str, str],
    timeout: int,
    fallback_ext: str,
) -> Optional[Tuple[bytes, str]]:
    """Extracts audio bytes + file extension from a sync or completed job JSON."""
    items = body.get("results") or body.get("data") or []
    if isinstance(items, list) and items:
        item = items[0] if isinstance(items[0], dict) else {}
        if item.get("b64_json"):
            raw = base64.b64decode(item["b64_json"])
            ext = _guess_audio_ext(str(item.get("mime") or ""), raw, fallback_ext)
            return raw, ext
        if item.get("url"):
            dl_url = urljoin(base_url + "/", str(item["url"]))
            dl = requests.get(dl_url, headers=headers, timeout=timeout)
            if dl.status_code == 200 and dl.content:
                ext = _guess_audio_ext(
                    dl.headers.get("content-type", "") or str(item.get("mime") or ""),
                    dl.content,
                    fallback_ext,
                )
                return dl.content, ext
    if body.get("audio_base64"):
        raw = base64.b64decode(body["audio_base64"])
        return raw, _guess_audio_ext("", raw, fallback_ext)
    if body.get("url"):
        dl_url = urljoin(base_url + "/", str(body["url"]))
        dl = requests.get(dl_url, headers=headers, timeout=timeout)
        if dl.status_code == 200 and dl.content:
            return dl.content, _guess_audio_ext(dl.headers.get("content-type", ""), dl.content, fallback_ext)
    return None


def generate_ai_hub_tts(
    hub_url: str,
    api_key: str,
    spec: TTSAliasSpec,
    *,
    text: str,
    voice: str = "",
    speaker_wav: str = "",
    language: str = "de",
    param: str = "",
    mode: str = "sync",
    timeout: int = 120,
    out_dir: Path,
    normalize_fn: Optional[Callable[[str], str]] = None,
    transcribe_fn: Optional[Callable[[str, str], str]] = None,
) -> Optional[Path]:
    """Synthesizes speech via AI-Hub ``POST /v1/generations``."""
    base = (hub_url or "").strip().rstrip("/")
    if not base:
        logger.error("AI-Hub TTS error: URL not configured")
        return None

    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    params: Dict[str, Any] = {spec.text_param: text}
    files: Dict[str, str] = {}

    # Language
    formatted_lang = format_language_for_alias(language, spec)
    if formatted_lang and spec.language_param:
        params[spec.language_param] = formatted_lang

    # Cloning vs Preset voice
    use_clone = bool(speaker_wav and spec.clone_supported and spec.clone_file_slot)
    if use_clone:
        ref_path_str = normalize_fn(speaker_wav) if normalize_fn else speaker_wav
        ref_path = Path(ref_path_str)
        if not ref_path.exists():
            logger.error("AI-Hub TTS '%s': reference audio not found: %s", spec.alias, ref_path_str)
            return None
        mime = _MIME_BY_EXT.get(ref_path.suffix.lower(), "audio/wav")
        b64 = base64.b64encode(ref_path.read_bytes()).decode("ascii")
        files[spec.clone_file_slot] = f"data:{mime};base64,{b64}"
        if spec.clone_reference_text_param:
            ref_txt = _read_sidecar_transcript(ref_path)
            if not ref_txt and transcribe_fn:
                ref_txt = transcribe_fn(str(ref_path), language or "de")
            if ref_txt:
                params[spec.clone_reference_text_param] = ref_txt
        if spec.voice_param and not spec.clone_overrides_voice and (voice or spec.default_voice):
            params[spec.voice_param] = voice or spec.default_voice
    elif spec.voice_param:
        eff_voice = (voice or spec.default_voice).strip()
        if eff_voice:
            params[spec.voice_param] = eff_voice

    # Generic extra character parameter (style or speed)
    extra_val = (param or "").strip()
    if extra_val:
        if spec.style_param:
            params[spec.style_param] = extra_val
        elif spec.speed_param:
            num = _opt_float(extra_val)
            if num is not None:
                if spec.speed_min is not None:
                    num = max(spec.speed_min, num)
                if spec.speed_max is not None:
                    num = min(spec.speed_max, num)
                params[spec.speed_param] = num

    effective_mode = mode if mode in spec.modes else spec.preferred_mode
    payload: Dict[str, Any] = {
        "model": spec.alias,
        "mode": effective_mode,
        "params": params,
    }
    if files:
        payload["files"] = files

    try:
        resp = requests.post(
            f"{base}/v1/generations",
            json=payload,
            headers=headers,
            timeout=timeout,
        )
        if resp.status_code not in (200, 201, 202):
            logger.error("AI-Hub TTS '%s' HTTP %d: %s", spec.alias, resp.status_code, resp.text[:300])
            return None

        ctype = resp.headers.get("content-type", "")
        if ctype.startswith("audio/") or (
            "json" not in ctype.lower() and len(resp.content) > 44
        ):
            ext = _guess_audio_ext(ctype, resp.content, spec.output_format)
            return _write_compatible_audio(resp.content, ext, out_dir)

        body = resp.json() if resp.content else {}
        if not isinstance(body, dict):
            logger.error("AI-Hub TTS '%s': unexpected response body", spec.alias)
            return None

        # Sync JSON with inline/URL result
        extracted = _extract_audio_from_json(
            body, base_url=base, headers=headers, timeout=timeout, fallback_ext=spec.output_format
        )
        if extracted:
            raw, ext = extracted
            return _write_compatible_audio(raw, ext, out_dir)

        # Async job polling
        job_id = str(body.get("job_id") or body.get("id") or "").strip()
        if not job_id:
            logger.error("AI-Hub TTS '%s': no audio and no job_id in response: %s", spec.alias, str(body)[:200])
            return None

        deadline = time.monotonic() + max(15, timeout)
        while time.monotonic() < deadline:
            time.sleep(0.4)
            poll = requests.get(f"{base}/v1/jobs/{quote(job_id, safe='')}", headers=headers, timeout=15)
            if poll.status_code != 200:
                continue
            st = poll.json() if poll.content else {}
            status = str(st.get("status") or "").lower()
            if status in ("done", "completed", "succeeded"):
                extracted = _extract_audio_from_json(
                    st, base_url=base, headers=headers, timeout=timeout, fallback_ext=spec.output_format
                )
                if not extracted:
                    # Fallback to standard result endpoint
                    dl = requests.get(
                        f"{base}/v1/jobs/{quote(job_id, safe='')}/result/0",
                        headers=headers,
                        timeout=timeout,
                    )
                    if dl.status_code == 200 and dl.content:
                        extracted = (
                            dl.content,
                            _guess_audio_ext(dl.headers.get("content-type", ""), dl.content, spec.output_format),
                        )
                if extracted:
                    raw, ext = extracted
                    return _write_compatible_audio(raw, ext, out_dir)
                logger.error("AI-Hub TTS '%s' job %s completed without downloadable audio", spec.alias, job_id)
                return None
            if status in ("failed", "error", "cancelled", "canceled"):
                logger.error("AI-Hub TTS '%s' job %s %s: %s", spec.alias, job_id, status, st.get("error"))
                return None

        logger.error("AI-Hub TTS '%s' job %s timed out after %ds", spec.alias, job_id, timeout)
        return None
    except Exception as e:
        logger.error("AI-Hub TTS '%s' error: %s", spec.alias, e)
        return None
