"""TTS Service - XTTS v2, F5-TTS, and Magpie backends.

Provides text-to-speech generation with three configurable backends:
- XTTS v2: Voice cloning capable, higher quality, slower
- F5-TTS: High-quality voice cloning via Gradio API
- Magpie: Multilingual TTS via REST API (multipart form)
"""
import asyncio
import json
import os
import re
import shutil
import struct
import subprocess
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from app.core.log import get_logger
logger = get_logger("tts")

from app.core.paths import get_storage_dir as _get_storage_dir
_REF_AUDIO_CACHE: Dict[str, str] = {}


# Reference audio specs matching XTTS/F5-TTS expectations
_REF_TARGET_RATE = 24000
_REF_MAX_DURATION = 10  # seconds


def _normalize_reference_audio(audio_path: str) -> str:
    """Normalizes reference audio to 24kHz mono WAV, max 10s.

    Non-WAV files (MP3, FLAC, OGG) or WAV files with wrong sample rate
    are converted on first use. Result is cached in voices/ directory.
    Returns the path to use (original if already OK, normalized otherwise).
    """
    if audio_path in _REF_AUDIO_CACHE:
        return _REF_AUDIO_CACHE[audio_path]

    p = Path(audio_path)
    if not p.exists():
        return audio_path

    needs_convert = False
    reason = ""

    if p.suffix.lower() != ".wav":
        needs_convert = True
        reason = f"non-WAV format ({p.suffix})"
    else:
        # Check WAV properties
        try:
            with open(p, "rb") as wf:
                wf.read(4)  # RIFF
                wf.read(4)  # size
                wf.read(4)  # WAVE
                wf.read(4)  # fmt
                wf.read(4)  # chunk size
                fmt = struct.unpack("<HHIIHH", wf.read(16))
                channels, sample_rate = fmt[1], fmt[2]
                bps = fmt[5]
                file_size = p.stat().st_size
                duration = (file_size - 44) / (sample_rate * channels * bps // 8)
                if sample_rate != _REF_TARGET_RATE:
                    needs_convert = True
                    reason = f"sample rate {sample_rate}Hz"
                elif channels != 1:
                    needs_convert = True
                    reason = f"{channels} channels"
                elif duration > _REF_MAX_DURATION + 2:
                    needs_convert = True
                    reason = f"too long ({duration:.1f}s)"
        except Exception:
            pass

    if not needs_convert:
        _REF_AUDIO_CACHE[audio_path] = audio_path
        return audio_path

    # Build normalized path: same dir, same stem, _norm.wav
    norm_path = p.parent / f"{p.stem}_norm.wav"

    if norm_path.exists():
        logger.debug("Using cached normalized ref: %s", norm_path)
        _REF_AUDIO_CACHE[audio_path] = str(norm_path)
        return str(norm_path)

    # Convert with ffmpeg (preferred) or soundfile (fallback)
    converted = False
    try:
        cmd = [
            "ffmpeg", "-y", "-i", str(p),
            "-ar", str(_REF_TARGET_RATE),
            "-ac", "1",
            "-sample_fmt", "s16",
            "-t", str(_REF_MAX_DURATION),
            str(norm_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0 and norm_path.exists():
            converted = True
        else:
            logger.warning("ffmpeg normalization failed: %s", result.stderr[:200])
    except FileNotFoundError:
        # ffmpeg not installed — try soundfile as fallback
        try:
            import soundfile as sf
            import numpy as np
            data, sr = sf.read(str(p))
            # Stereo to mono
            if len(data.shape) > 1:
                data = np.mean(data, axis=1)
            # Resample to target rate
            if sr != _REF_TARGET_RATE:
                ratio = sr / _REF_TARGET_RATE
                if abs(ratio - round(ratio)) < 0.01 and round(ratio) >= 2:
                    data = data[::int(round(ratio))]
                else:
                    old_len = len(data)
                    new_len = int(old_len * _REF_TARGET_RATE / sr)
                    new_indices = np.linspace(0, old_len - 1, new_len)
                    data = np.interp(new_indices, np.arange(old_len), data)
            # Trim to max duration
            max_samples = _REF_MAX_DURATION * _REF_TARGET_RATE
            if len(data) > max_samples:
                data = data[:max_samples]
            data = data.astype(np.float32)
            peak = np.max(np.abs(data))
            if peak > 1.0:
                data = data / peak
            sf.write(str(norm_path), data, _REF_TARGET_RATE, subtype='PCM_16')
            converted = True
        except ImportError:
            logger.warning("Neither ffmpeg nor soundfile available, using original ref audio (%s): %s",
                          reason, audio_path)
        except Exception as sf_err:
            logger.warning("soundfile normalization failed: %s", sf_err)
    except Exception as e:
        logger.error("Ref audio normalization error: %s", e)

    if converted and norm_path.exists():
        logger.info("Normalized ref audio (%s): %s -> %s", reason, p.name, norm_path.name)
        _REF_AUDIO_CACHE[audio_path] = str(norm_path)
        return str(norm_path)

    _REF_AUDIO_CACHE[audio_path] = audio_path
    return audio_path


def clear_tts_tmp():
    """Deletes all temporary TTS audio files. Called at server startup."""
    if (_get_storage_dir() / "tmp" / "tts_audio").exists():
        shutil.rmtree((_get_storage_dir() / "tmp" / "tts_audio"))
        logger.info("Temp directory cleared: %s", (_get_storage_dir() / "tmp" / "tts_audio"))
    (_get_storage_dir() / "tmp" / "tts_audio").mkdir(parents=True, exist_ok=True)


def clean_text_for_tts(text: str) -> str:
    """Cleans LLM response text for TTS output."""
    # Remove options block
    text = re.sub(r'\*\*Option\s+[A-Z]:\*\*\s*\[?[^\]\n]+\]?', '', text)
    # Remove mood marker
    text = re.sub(r'\*\*I\s+feel\s+.+?\*\*', '', text, flags=re.IGNORECASE)
    # Remove markdown bold/italic
    text = re.sub(r'\*{1,3}(.+?)\*{1,3}', r'\1', text)
    # Remove markdown headers
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    # Markdown links: [text](url) -> text
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    # Remove inline images
    text = re.sub(r'!\[.*?\]\([^)]+\)', '', text)
    # Remove URLs
    text = re.sub(r'https?://\S+', '', text)
    # Remove emojis (common unicode ranges)
    text = re.sub(
        r'[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF'
        r'\U0001F1E0-\U0001F1FF\U00002702-\U000027B0\U0000FE0F]+',
        '', text
    )
    # Collapse multiple blank lines
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def _find_split_pos(buffer: str, i: int) -> int:
    """Finds the split position after a sentence end at index i.

    Includes trailing quotation marks, parentheses and asterisks so they
    do not end up as fragments in the next chunk.
    """
    pos = i + 1
    while pos < len(buffer) and buffer[pos] in '"\'""»›*)':
        pos += 1
    return pos


def split_tts_chunk(buffer: str, min_chars: int) -> tuple:
    """Splits the buffer at the first sentence end after min_chars.

    Detects real sentence ends: period/exclamation/question mark followed by
    a space or newline. Ignores abbreviations (e.g., Dr., Nr.).
    Includes trailing quotation marks/asterisks.

    Args:
        buffer: Accumulated text for TTS.
        min_chars: Minimum number of characters before a sentence end is searched.

    Returns:
        (chunk, rest) — chunk is None if the buffer is too short or has no sentence end.
    """
    if len(buffer) < min_chars:
        return (None, buffer)

    # Search for the first real sentence end FROM min_chars onward
    for i in range(min_chars, len(buffer)):
        ch = buffer[i]

        if ch in '!?':
            pos = _find_split_pos(buffer, i)
            chunk = buffer[:pos].strip()
            remaining = buffer[pos:]
            if chunk:
                return (chunk, remaining)

        elif ch == '.':
            next_idx = i + 1
            # Skip trailing quotation marks
            closing = next_idx
            while closing < len(buffer) and buffer[closing] in '"\'""»›*)':
                closing += 1

            if closing >= len(buffer):
                # Period (+ quotes) at end of text
                chunk = buffer[:closing].strip()
                if chunk:
                    return (chunk, "")
            elif closing < len(buffer) and buffer[closing] in ' \n\t':
                # Period + whitespace — exclude abbreviations
                word_start = i - 1
                while word_start >= 0 and buffer[word_start].isalpha():
                    word_start -= 1
                word_len = i - word_start - 1
                if word_len > 2 or buffer[closing] == '\n':
                    chunk = buffer[:closing].strip()
                    remaining = buffer[closing:]
                    if chunk:
                        return (chunk, remaining)

        elif ch == '\n' and i > 0 and buffer[i - 1] == '\n':
            # Double newline = paragraph end
            chunk = buffer[:i].strip()
            remaining = buffer[i:]
            if chunk:
                return (chunk, remaining)

    # No sentence end after min_chars — search for the LAST sentence end BEFORE it
    for i in range(min(min_chars, len(buffer)) - 1, -1, -1):
        ch = buffer[i]
        if ch in '!?':
            pos = _find_split_pos(buffer, i)
            chunk = buffer[:pos].strip()
            if chunk:
                return (chunk, buffer[pos:])
        elif ch == '.':
            pos = _find_split_pos(buffer, i)
            if pos < len(buffer) and buffer[pos] in ' \n\t':
                word_start = i - 1
                while word_start >= 0 and buffer[word_start].isalpha():
                    word_start -= 1
                word_len = i - word_start - 1
                if word_len > 2 or buffer[pos] == '\n':
                    chunk = buffer[:pos].strip()
                    if chunk:
                        return (chunk, buffer[pos:])

    return (None, buffer)


class TTSService:
    """Manages TTS backends (XTTS v2, F5-TTS, Magpie) with global + per-character config."""

    def __init__(self):
        self.enabled = False
        self.auto = False
        self.backend = "xtts"
        self.xtts_url = ""
        self.xtts_speaker_wav = ""
        self.xtts_language = "de"
        self.magpie_url = ""
        self.magpie_voice = ""
        self.magpie_language = "de-DE"
        self.f5_url = ""
        self.f5_ref_audio = ""
        self.f5_ref_text = ""
        self.f5_custom_ckpt = ""
        self.f5_custom_vocab = ""
        self.f5_custom_cfg = ""
        self.f5_remove_silence = False
        self.f5_speed = 1.0
        self.f5_nfe_steps = 32
        self._f5_client = None
        self._f5_ref_text_cache: Dict[str, str] = {}
        # F5-TTS per-language model registry
        self._f5_language_models: Dict[str, Dict[str, str]] = {}
        self._f5_current_language: Optional[str] = None
        self._f5_model_lock = threading.Lock()
        self._available = None
        self.fallback_backend = ""
        self._load_config()

    def _load_config(self):
        """Loads config from environment variables."""
        self.enabled = os.environ.get("TTS_ENABLED", "false").lower() in ("true", "1", "yes")
        self.auto = os.environ.get("TTS_AUTO", "false").lower() in ("true", "1", "yes")
        self.chunk_size = int(os.environ.get("TTS_CHUNK_SIZE", "0"))
        self.backend = os.environ.get("TTS_BACKEND", "xtts").lower()
        self.fallback_backend = os.environ.get("TTS_FALLBACK_BACKEND", "").lower()

        # XTTS
        self.xtts_url = os.environ.get("TTS_XTTS_URL", "http://localhost:8020").rstrip("/")
        self.xtts_speaker_wav = os.environ.get("TTS_XTTS_SPEAKER_WAV", "")
        self.xtts_language = os.environ.get("TTS_XTTS_LANGUAGE", "de")

        # Magpie
        self.magpie_url = os.environ.get("TTS_MAGPIE_URL", "http://localhost:9000").rstrip("/")
        self.magpie_voice = os.environ.get("TTS_MAGPIE_VOICE", "")
        self.magpie_language = os.environ.get("TTS_MAGPIE_LANGUAGE", "de-DE")

        # F5-TTS
        self.f5_url = os.environ.get("TTS_F5_URL", "http://localhost:7860").rstrip("/")
        self.f5_ref_audio = os.environ.get("TTS_F5_REF_AUDIO", "")
        self.f5_ref_text = os.environ.get("TTS_F5_REF_TEXT", "")
        self.f5_custom_ckpt = os.environ.get("TTS_F5_CUSTOM_CKPT", "")
        self.f5_custom_vocab = os.environ.get("TTS_F5_CUSTOM_VOCAB", "")
        self.f5_custom_cfg = os.environ.get("TTS_F5_CUSTOM_CFG", "")
        self.f5_remove_silence = os.environ.get("TTS_F5_REMOVE_SILENCE", "false").lower() in ("true", "1", "yes")
        self.f5_speed = float(os.environ.get("TTS_F5_SPEED", "1.0"))
        self.f5_nfe_steps = int(os.environ.get("TTS_F5_NFE_STEPS", "32"))
        self._f5_client = None

        # F5-TTS per-language model registry: scan TTS_F5_MODEL_{LANG} env vars
        self._f5_language_models = {}
        prefix = "TTS_F5_MODEL_"
        for key, value in os.environ.items():
            if key.startswith(prefix) and len(key) == len(prefix) + 2:
                lang = key[len(prefix):].lower()
                ckpt = value.strip()
                vocab = os.environ.get(f"TTS_F5_VOCAB_{lang.upper()}", "").strip()
                cfg = os.environ.get(f"TTS_F5_CFG_{lang.upper()}", "").strip()
                self._f5_language_models[lang] = {
                    "ckpt": ckpt,
                    "vocab": vocab,
                    "cfg": cfg or self.f5_custom_cfg,
                }
                logger.info("F5-TTS: language '%s' registered: %s",
                            lang, 'standard' if not ckpt else ckpt.split('/')[-1][:50])

        # Backward compatibility: old TTS_F5_CUSTOM_CKPT as legacy fallback
        if not self._f5_language_models and self.f5_custom_ckpt:
            self._f5_language_models["_legacy"] = {
                "ckpt": self.f5_custom_ckpt,
                "vocab": self.f5_custom_vocab,
                "cfg": self.f5_custom_cfg,
            }
            logger.info("F5-TTS: legacy single-model config (no TTS_F5_MODEL_* variables)")

    def _check_backend_reachable(self, backend: str) -> bool:
        """Checks whether a given backend is reachable (without loading models)."""
        try:
            if backend == "xtts":
                resp = requests.get(f"{self.xtts_url}/docs", timeout=5)
                return resp.status_code == 200
            elif backend == "magpie":
                resp = requests.get(self.magpie_url, timeout=5)
                return resp.status_code < 500
            elif backend == "f5":
                resp = requests.get(self.f5_url, timeout=5)
                return resp.status_code == 200
            return False
        except Exception:
            return False

    def is_available(self) -> bool:
        """Checks whether the configured TTS backend is reachable."""
        if not self.enabled:
            self._available = False
            return False

        try:
            if self.backend == "xtts":
                resp = requests.get(f"{self.xtts_url}/docs", timeout=5)
                self._available = resp.status_code == 200
            elif self.backend == "magpie":
                resp = requests.get(self.magpie_url, timeout=5)
                self._available = resp.status_code < 500
            elif self.backend == "f5":
                resp = requests.get(self.f5_url, timeout=5)
                self._available = resp.status_code == 200
                if self._available and self._f5_language_models:
                    # Load the first registered language model at startup
                    first_lang = next(iter(self._f5_language_models))
                    if first_lang != "_legacy":
                        self._ensure_f5_model(first_lang)
                    elif self.f5_custom_ckpt:
                        self._ensure_f5_model("")
            else:
                self._available = False
        except requests.exceptions.ConnectionError:
            self._available = False
        except Exception:
            self._available = False

        if not self._available and self.fallback_backend and self.fallback_backend != self.backend:
            logger.warning("Primary backend '%s' not reachable, checking fallback '%s'...",
                          self.backend, self.fallback_backend)
            if self._check_backend_reachable(self.fallback_backend):
                logger.info("Fallback '%s' is available", self.fallback_backend)
                self._available = True
            else:
                logger.warning("Fallback '%s' also not reachable", self.fallback_backend)

        return self._available

    def get_character_config(self, agent_config: Dict[str, Any]) -> Dict[str, Any]:
        """Merges global + per-character TTS settings.

        Per-character values override global defaults.
        """
        # speaker_wav default depends on the backend
        if self.backend == "f5":
            default_speaker = self.f5_ref_audio
        else:
            default_speaker = self.xtts_speaker_wav
        # voice default: Magpie has its own named voices
        if self.backend == "magpie":
            default_voice = self.magpie_voice
            default_language = self.magpie_language
        else:
            default_voice = ""
            default_language = self.xtts_language
        return {
            "enabled": agent_config.get("tts_enabled", self.enabled),
            "auto": agent_config.get("tts_auto", self.auto),
            "voice": agent_config.get("tts_voice", "") or default_voice,
            "speaker_wav": agent_config.get("tts_speaker_wav", "") or default_speaker,
            "language": agent_config.get("tts_language", "") or default_language,
        }

    def _generate_with_backend(
        self,
        backend: str,
        text: str,
        voice: str = "",
        speaker_wav: str = "",
        language: str = "") -> Optional[Path]:
        """Generates audio with a specific backend."""
        if backend == "xtts":
            return self._generate_xtts(
                text,
                speaker_wav or self.xtts_speaker_wav,
                language or self.xtts_language)
        elif backend == "magpie":
            return self._generate_magpie(
                text,
                voice or self.magpie_voice,
                language or self.magpie_language)
        elif backend == "f5":
            effective_language = language or self.xtts_language
            # Thread lock: model switch + generation are atomic
            with self._f5_model_lock:
                if not self._ensure_f5_model(effective_language):
                    logger.warning("F5-TTS: model switch for '%s' failed, "
                                  "trying generation with the current model", effective_language)
                return self._generate_f5(
                    text,
                    speaker_wav or self.f5_ref_audio,
                    self.f5_ref_text,
                    effective_language)
        else:
            logger.error("Unknown backend: %s", backend)
            return None

    def generate(
        self,
        text: str,
        voice: str = "",
        speaker_wav: str = "",
        language: str = "") -> Optional[Path]:
        """Generates an audio file via the configured backend.

        Tries the primary backend first. On failure, the fallback backend
        (TTS_FALLBACK_BACKEND) is used if configured.

        Args:
            text: Cleaned text for TTS.
            voice: Voice name for Magpie (override).
            speaker_wav: XTTS/F5-TTS reference audio (override).
            language: Language (for XTTS and F5-TTS model selection).

        Returns:
            Path to the generated audio file, or None on failure.
        """
        if not text.strip():
            return None

        (_get_storage_dir() / "tmp" / "tts_audio").mkdir(parents=True, exist_ok=True)

        logger.debug("Text to TTS (%s): %s%s", self.backend, text[:500], '...' if len(text) > 500 else '')

        result = self._generate_with_backend(self.backend, text, voice, speaker_wav, language)

        if result is None and self.fallback_backend and self.fallback_backend != self.backend:
            logger.warning("Primary backend '%s' failed, trying fallback '%s'...",
                          self.backend, self.fallback_backend)
            result = self._generate_with_backend(self.fallback_backend, text, voice, speaker_wav, language)
            if result:
                logger.info("Fallback '%s' succeeded", self.fallback_backend)

        return result

    def _generate_xtts(
        self, text: str, speaker_wav: str, language: str
    ) -> Optional[Path]:
        """XTTS v2: Sends text + speaker reference to xtts-api-server."""
        if not speaker_wav:
            logger.error("XTTS error: speaker_wav is required but not configured. Set TTS_XTTS_SPEAKER_WAV.")
            return None
        speaker_wav = _normalize_reference_audio(speaker_wav)
        try:
            payload = {
                "text": text,
                "language": language,
                "speaker_wav": speaker_wav,
            }

            resp = requests.post(
                f"{self.xtts_url}/tts_to_audio/",
                json=payload,
                timeout=300)
            if resp.status_code == 200:
                filename = f"{uuid.uuid4().hex}.wav"
                out_path = (_get_storage_dir() / "tmp" / "tts_audio") / filename
                out_path.write_bytes(resp.content)
                logger.debug("XTTS: %d bytes -> %s", len(resp.content), out_path)
                return out_path
            else:
                logger.error("XTTS error: HTTP %d - %s", resp.status_code, resp.text[:200])
                return None
        except Exception as e:
            logger.error("XTTS error: %s", e)
            return None

    # Explicit allowlist for Magpie TTS - only these characters pass through.
    # Magpie's character_mapping has no digits or special chars like % @ # etc.
    _MAGPIE_ALLOWED = frozenset(
        "abcdefghijklmnopqrstuvwxyz"
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        "äöüÄÖÜß"
        " \t\n"
        ".,!?;:-'\"/()'"
    )

    @staticmethod
    def _clean_text_for_magpie(text: str) -> str:
        """Extra text cleanup for Magpie TTS to avoid pronunciation mapping errors.

        Magpie's phonemizer fails on characters outside its supported set
        (digits, %, @, # etc.). Only characters in _MAGPIE_ALLOWED pass through.
        """
        # Replace common typographic/Unicode characters with allowed equivalents
        replacements = {
            "\u2014": " - ",   # em dash
            "\u2013": " - ",   # en dash
            "\u2026": "...",   # ellipsis
            "\u201e": '"',     # „
            "\u201c": '"',     # "
            "\u201d": '"',     # "
            "\u2018": "'",     # '
            "\u2019": "'",     # '
            "\u00ab": '"',     # «
            "\u00bb": '"',     # »
            "\u2022": ",",     # bullet
            "\u00a0": " ",     # non-breaking space
            "\u200b": "",      # zero-width space
            "\u200d": "",      # zero-width joiner
            "\ufeff": "",      # BOM
            # French/Latin accented characters → ASCII base
            "à": "a", "â": "a", "á": "a", "ã": "a", "å": "a",
            "è": "e", "é": "e", "ê": "e", "ë": "e",
            "ì": "i", "í": "i", "î": "i", "ï": "i",
            "ò": "o", "ó": "o", "ô": "o", "õ": "o",
            "ù": "u", "ú": "u", "û": "u",
            "ý": "y", "ÿ": "y",
            "ç": "c", "ñ": "n",
            "À": "A", "Â": "A", "Á": "A",
            "È": "E", "É": "E", "Ê": "E", "Ë": "E",
            "Î": "I", "Ï": "I",
            "Ô": "O", "Ó": "O",
            "Û": "U", "Ú": "U",
            "Ç": "C", "Ñ": "N",
            # Ampersand → "und"
            "&": " und ",
        }
        for old, new in replacements.items():
            text = text.replace(old, new)

        # Allowlist filter: replace all disallowed characters with spaces
        text = ''.join(c if c in TTSService._MAGPIE_ALLOWED else ' ' for c in text)

        # Collapse multiple spaces/newlines
        text = re.sub(r'[ \t]+', ' ', text)
        text = re.sub(r'\n{2,}', '\n', text)
        return text.strip()

    @staticmethod
    def _transliterate_for_magpie(text: str) -> str:
        """Fallback: replace German umlauts/special chars with ASCII equivalents.

        Magpie's phonemizer sometimes fails on certain umlaut combinations.
        This gives it a second chance with pure ASCII text.
        """
        replacements = {
            "ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss",
            "Ä": "Ae", "Ö": "Oe", "Ü": "Ue",
        }
        for old, new in replacements.items():
            text = text.replace(old, new)
        return text

    def _magpie_sentence_fallback(
        self, text: str, language: str, voice: str) -> Optional[Path]:
        """Synthesize sentence by sentence, concatenating WAV results.

        Splits on sentence-ending punctuation AND newlines (for titles/paragraphs).
        Skips sentences that fail and concatenates the rest.
        Returns None if all sentences fail.
        """
        import wave
        import io

        # Split on sentence-ending punctuation OR newlines
        sentences = re.split(r'(?<=[.!?])\s+|\n+', text)
        sentences = [s.strip() for s in sentences if s.strip()]
        if len(sentences) <= 1:
            return None

        logger.debug("Magpie sentence fallback: %d chunks to process", len(sentences))

        wav_chunks = []
        params_set = False
        wav_params = None

        for i, sentence in enumerate(sentences):
            if not sentence:
                continue
            # Build fresh form_data for each sentence
            sentence_form = {
                "text": (None, sentence),
                "language": (None, language),
                "voice": (None, voice),
            }
            try:
                resp = requests.post(
                    f"{self.magpie_url}/v1/audio/synthesize",
                    files=sentence_form, timeout=60)
                if resp.status_code == 200 and len(resp.content) > 44:
                    bio = io.BytesIO(resp.content)
                    with wave.open(bio, 'rb') as wf:
                        if not params_set:
                            wav_params = wf.getparams()
                            params_set = True
                        wav_chunks.append(wf.readframes(wf.getnframes()))
                else:
                    err_detail = resp.text[:120] if resp.text else "(empty)"
                    logger.warning("Magpie skip [%d/%d] HTTP %d: %s | text: %s...",
                                  i+1, len(sentences), resp.status_code, err_detail, sentence[:50])
            except Exception as e:
                logger.error("Magpie sentence error [%d/%d]: %s", i+1, len(sentences), e)

        if not wav_chunks or not wav_params:
            logger.error("Magpie: all sentences failed")
            return None

        # Concatenate WAV chunks
        filename = f"{uuid.uuid4().hex}.wav"
        out_path = (_get_storage_dir() / "tmp" / "tts_audio") / filename
        with wave.open(str(out_path), 'wb') as out_wf:
            out_wf.setparams(wav_params)
            for chunk in wav_chunks:
                out_wf.writeframes(chunk)

        ok_count = len(wav_chunks)
        total = len(sentences)
        logger.debug("Magpie sentence fallback: %d/%d sentences OK -> %s", ok_count, total, out_path)
        return out_path

    def _generate_magpie(
        self, text: str, voice: str, language: str
    ) -> Optional[Path]:
        """Magpie TTS: Sends text via multipart form to the Magpie REST API."""
        if not voice:
            logger.error("Magpie error: voice is required. Set TTS_MAGPIE_VOICE.")
            return None
        try:
            # Sanitize text for Magpie's phonemizer
            text = self._clean_text_for_magpie(text)
            if not text:
                logger.warning("Magpie: empty text after cleanup, skipping")
                return None

            # Magpie needs locale format "de-DE" (lowercase-UPPERCASE).
            # Extract language from the voice name (Magpie-Multilingual.DE-DE.Name)
            # or map a short form to a locale.
            effective_lang = language
            parts = voice.split(".")
            if len(parts) >= 2:
                raw_lang = parts[1]  # e.g. "DE-DE" from "Magpie-Multilingual.DE-DE.Sofia"
                lang_parts = raw_lang.split("-")
                if len(lang_parts) == 2:
                    effective_lang = f"{lang_parts[0].lower()}-{lang_parts[1].upper()}"
                else:
                    effective_lang = raw_lang.lower()
            elif len(language) == 2:
                effective_lang = f"{language}-{language.upper()}"  # "de" -> "de-DE"
            form_data = {
                "text": (None, text),
                "language": (None, effective_lang),
                "voice": (None, voice),
            }
            resp = requests.post(
                f"{self.magpie_url}/v1/audio/synthesize",
                files=form_data,
                timeout=300)
            if resp.status_code == 200:
                filename = f"{uuid.uuid4().hex}.wav"
                out_path = (_get_storage_dir() / "tmp" / "tts_audio") / filename
                out_path.write_bytes(resp.content)
                logger.debug("Magpie: %d bytes -> %s", len(resp.content), out_path)
                return out_path

            # Mapping error: retry strategies
            if resp.status_code == 400 and "Mapping failed" in resp.text:
                logger.warning("Magpie mapping failed for: %s...", text[:80])

                # Strategy 1: transliterate umlauts
                fallback_text = self._transliterate_for_magpie(text)
                retry_form = {
                    "text": (None, fallback_text),
                    "language": (None, effective_lang),
                    "voice": (None, voice),
                }
                resp2 = requests.post(
                    f"{self.magpie_url}/v1/audio/synthesize",
                    files=retry_form, timeout=300)
                if resp2.status_code == 200:
                    filename = f"{uuid.uuid4().hex}.wav"
                    out_path = (_get_storage_dir() / "tmp" / "tts_audio") / filename
                    out_path.write_bytes(resp2.content)
                    logger.info("Magpie OK after transliteration")
                    return out_path

                err2 = resp2.text[:150] if resp2.text else "(empty)"
                logger.warning("Magpie transliteration also failed: HTTP %d - %s", resp2.status_code, err2)

                # Strategy 2: sentence-by-sentence, skip failures
                logger.warning("Trying sentence-by-sentence fallback")
                return self._magpie_sentence_fallback(
                    fallback_text, effective_lang, voice)

            logger.error("Magpie error: HTTP %d - %s", resp.status_code, resp.text[:200])
            return None
        except Exception as e:
            logger.error("Magpie error: %s", e)
            return None

    def _ensure_f5_model(self, language: str) -> bool:
        """Ensures the correct F5-TTS model for the language is loaded.

        Skips the switch if the language is already active.
        Returns True when the model is ready, False on error.
        """
        lang_key = language.lower() if language else ""

        if lang_key not in self._f5_language_models:
            if "_legacy" in self._f5_language_models:
                lang_key = "_legacy"
            else:
                # No language config and no legacy -> standard F5-TTS_v1
                if self._f5_current_language == "_standard":
                    return True
                return self._switch_to_standard_f5()

        # Already loaded?
        if self._f5_current_language == lang_key:
            return True

        model_info = self._f5_language_models[lang_key]
        ckpt = model_info["ckpt"]

        # Empty ckpt = standard F5-TTS_v1 (no custom model)
        if not ckpt:
            return self._switch_to_standard_f5()

        # Load custom model
        try:
            client = self._get_f5_client()
            logger.info("F5-TTS: loading model for language '%s': %s", lang_key, ckpt.split('/')[-1][:60])
            # Choices: F5-TTS_v1, E2-TTS, Custom
            client.predict(new_choice="Custom", api_name="/switch_tts_model")
            # Base architecture config as default
            cfg = model_info.get("cfg") or self.f5_custom_cfg or (
                '{"dim": 1024, "depth": 22, "heads": 16, "ff_mult": 2, '
                '"text_dim": 512, "text_mask_padding": false, "conv_layers": 4, '
                '"pe_attn_head": 1}'
            )
            client.predict(
                custom_ckpt_path=ckpt,
                custom_vocab_path=model_info.get("vocab", ""),
                custom_model_cfg=cfg,
                api_name="/set_custom_model")
            self._f5_current_language = lang_key
            logger.info("F5-TTS: model for '%s' loaded.", lang_key)
            return True
        except Exception as e:
            logger.error("F5-TTS: model switch for '%s' failed: %s", lang_key, e)
            self._f5_client = None
            self._f5_current_language = None
            return False

    def _switch_to_standard_f5(self) -> bool:
        """Switches to the standard F5-TTS_v1 model (no custom model)."""
        try:
            client = self._get_f5_client()
            logger.info("F5-TTS: switching to standard F5-TTS_v1")
            client.predict(new_choice="F5-TTS_v1", api_name="/switch_tts_model")
            self._f5_current_language = "_standard"
            logger.info("F5-TTS: standard F5-TTS_v1 active.")
            return True
        except Exception as e:
            logger.error("F5-TTS: switch to standard model failed: %s", e)
            self._f5_client = None
            self._f5_current_language = None
            return False

    def _get_f5_client(self):
        """Returns a cached Gradio client for F5-TTS."""
        if self._f5_client is None:
            from gradio_client import Client
            self._f5_client = Client(self.f5_url)
        return self._f5_client

    def _transcribe_ref_audio(self, audio_path: str, language: str = "de") -> str:
        """Transcribes reference audio with faster-whisper. Result is cached."""
        cache_key = f"{audio_path}:{language}"
        if cache_key in self._f5_ref_text_cache:
            return self._f5_ref_text_cache[cache_key]
        try:
            from faster_whisper import WhisperModel
            logger.debug("F5-TTS: transcribing reference audio '%s' (lang=%s) ...", audio_path, language)
            model = WhisperModel("small", device="cpu", compute_type="int8")
            segments, info = model.transcribe(audio_path, language=language or "de")
            text = " ".join(s.text.strip() for s in segments)
            logger.debug("F5-TTS: transcription: '%s...'", text[:100])
            self._f5_ref_text_cache[cache_key] = text
            return text
        except Exception as e:
            logger.error("F5-TTS: auto-transcription failed: %s", e)
            return ""

    def _generate_f5(self, text: str, ref_audio: str, ref_text: str, language: str = "de") -> Optional[Path]:
        """F5-TTS: Sends text to the F5-TTS Gradio server via gradio_client."""
        if not ref_audio:
            logger.error("F5-TTS error: ref_audio is required. Set TTS_F5_REF_AUDIO.")
            return None
        ref_audio = _normalize_reference_audio(ref_audio)

        # Auto-transcription when ref_text is empty
        if not ref_text.strip() and Path(ref_audio).exists():
            ref_text = self._transcribe_ref_audio(ref_audio, language)
            if not ref_text:
                logger.warning("F5-TTS: ref_text empty, F5-TTS attempts server-side transcription.")

        try:
            from gradio_client import handle_file
            client = self._get_f5_client()
            result = client.predict(
                ref_audio_input=handle_file(ref_audio),
                ref_text_input=ref_text,
                gen_text_input=text,
                remove_silence=self.f5_remove_silence,
                nfe_slider=self.f5_nfe_steps,
                speed_slider=self.f5_speed,
                api_name="/basic_tts")
            # Result is tuple: (audio_filepath, spectrogram_filepath, ref_text, seed)
            audio_file = result[0] if isinstance(result, (list, tuple)) else result
            if audio_file and Path(audio_file).exists():
                filename = f"{uuid.uuid4().hex}.wav"
                out_path = (_get_storage_dir() / "tmp" / "tts_audio") / filename
                shutil.copy2(audio_file, out_path)
                file_size = out_path.stat().st_size
                logger.debug("F5-TTS: %d bytes -> %s", file_size, out_path)
                return out_path
            else:
                logger.error("F5-TTS error: No audio file in result")
                return None
        except Exception as e:
            # Reset client on error so it reconnects next time
            self._f5_client = None
            logger.error("F5-TTS error: %s", e)
            return None

    def reload(self):
        """Re-reads config from environment."""
        self._load_config()
        self._available = None
        self._f5_client = None
        self._f5_ref_text_cache.clear()
        self._f5_current_language = None

    def status_info(self) -> Dict[str, Any]:
        """Returns status info for availability summary."""
        if self.backend == "f5":
            url = self.f5_url
            if self._f5_language_models:
                langs = [k for k in self._f5_language_models if k != "_legacy"]
                if langs:
                    model_name = f"F5-TTS ({','.join(langs)})"
                else:
                    ckpt = self._f5_language_models.get("_legacy", {}).get("ckpt", "")
                    model_name = ckpt.split("/")[-2] if ckpt else "F5-TTS"
            else:
                model_name = "F5-TTS"
            voice = f"ref_audio ({model_name})"
        elif self.backend == "magpie":
            url = self.magpie_url
            voice = self.magpie_voice
        elif self.backend == "xtts":
            url = self.xtts_url
            voice = "speaker_wav"
        else:
            url = ""
            voice = ""
        return {
            "enabled": self.enabled,
            "available": self._available if self._available is not None else False,
            "backend": self.backend,
            "fallback_backend": self.fallback_backend or None,
            "url": url,
            "voice": voice,
            "auto": self.auto,
        }


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
_tts_service: Optional[TTSService] = None


def get_tts_service() -> TTSService:
    """Returns the global TTSService singleton."""
    global _tts_service
    if _tts_service is None:
        _tts_service = TTSService()
    return _tts_service


def initialize_tts_service() -> TTSService:
    """Initializes the TTS service and checks availability. Called at startup."""
    global _tts_service
    _tts_service = TTSService()
    _tts_service.is_available()
    return _tts_service


def reload_tts_service() -> Dict[str, Any]:
    """Reloads the TTS service from .env."""
    global _tts_service
    if _tts_service is None:
        _tts_service = TTSService()
    _tts_service.reload()
    _tts_service.is_available()
    return _tts_service.status_info()


# ---------------------------------------------------------------------------
# Chunked TTS Handler — deduplicated streaming TTS logic
# ---------------------------------------------------------------------------

class ChunkedTTSHandler:
    """Handles chunked TTS generation during SSE streaming.

    Usage in a streaming endpoint::

        handler = ChunkedTTSHandler(agent_config, require_auto=True)
        async for event in agent.stream(...):
            if isinstance(event, ContentEvent):
                for sse in handler.feed(event.content):
                    yield sse
        for sse in await handler.flush():
            yield sse
    """

    def __init__(self, agent_config: Dict[str, Any], *, require_auto: bool = False):
        self.enabled = False
        self._svc = None
        self._cfg: Dict[str, Any] = {}
        self._buffer = ""
        self._tasks: List[Tuple[asyncio.Task, int]] = []
        self._idx = 0
        try:
            svc = get_tts_service()
            if svc.enabled and svc.chunk_size > 0:
                cfg = svc.get_character_config(agent_config)
                if cfg.get("enabled", True) and (not require_auto or cfg.get("auto", False)):
                    self.enabled = True
                    self._svc = svc
                    self._cfg = cfg
        except Exception as e:
            logger.error("TTS Chunk init error: %s", e)

    def _gen_task(self, text: str) -> asyncio.Task:
        return asyncio.create_task(asyncio.to_thread(
            self._svc.generate,
            text=text,
            voice=self._cfg.get("voice", ""),
            speaker_wav=self._cfg.get("speaker_wav", ""),
            language=self._cfg.get("language", "de")))

    @staticmethod
    def _audio_sse(url: str, index: int, final: bool) -> str:
        return f"data: {json.dumps({'audio_chunk': {'url': url, 'index': index, 'final': final}})}\n\n"

    def feed(self, text: str) -> List[str]:
        """Feed new text, return list of ready SSE audio chunks."""
        if not self.enabled:
            return []
        self._buffer += text
        cleaned = clean_text_for_tts(self._buffer)
        chunk, rest = split_tts_chunk(cleaned, self._svc.chunk_size)
        if chunk and chunk.strip():
            self._buffer = rest
            idx = self._idx
            self._idx += 1
            self._tasks.append((self._gen_task(chunk), idx))

        results = []
        while self._tasks and self._tasks[0][0].done():
            t, i = self._tasks.pop(0)
            try:
                apath = t.result()
                if apath:
                    results.append(self._audio_sse(f"/tts/tmp/{apath.name}", i, False))
            except Exception as e:
                logger.error("TTS Chunk error chunk %d: %s", i, e)
        return results

    async def flush(self) -> List[str]:
        """Flush remaining buffer and await pending tasks. Returns SSE strings."""
        if not self.enabled:
            return []
        remaining = clean_text_for_tts(self._buffer.strip())
        if remaining.strip():
            idx = self._idx
            self._idx += 1
            self._tasks.append((self._gen_task(remaining), idx))
        self._buffer = ""

        results = []
        for t, i in self._tasks:
            try:
                apath = await t
                is_last = (i == self._tasks[-1][1])
                if apath:
                    results.append(self._audio_sse(f"/tts/tmp/{apath.name}", i, is_last))
            except Exception as e:
                logger.error("TTS Chunk error chunk %d: %s", i, e)
        self._tasks = []
        return results
