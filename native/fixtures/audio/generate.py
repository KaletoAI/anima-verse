#!/usr/bin/env python3
"""Regenerate the synthetic Task 58 tones (Python stdlib + ffmpeg). No recordings."""
import math
from pathlib import Path
import struct
import subprocess
import tempfile
import wave

ROOT = Path(__file__).resolve().parent
RATE = 8000


def tone(path, seconds, frequency):
    # Mono PCM16; a short symmetric envelope avoids clicks in audible checks.
    count = int(seconds * RATE)
    with wave.open(str(path), "wb") as output:
        output.setparams((1, 2, RATE, count, "NONE", "not compressed"))
        output.writeframes(b"".join(struct.pack("<h", round(
            2000 * min(1, i / 80, (count - 1 - i) / 80)
            * math.sin(2 * math.pi * frequency * i / RATE))) for i in range(count)))


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="audio-fixture-") as temp:
        for relative, seconds, hz in [
            ("music/day/day-a.mp3", 9, 220),
            ("music/day/day-b.ogg", 12, 330),
            ("music/night/night.wav", 2, 110),
            ("ambient/grass/grass-a.mp3", 1.5, 440),
            ("ambient/grass/grass-b.wav", 3, 550),
            ("ambient/Forest/forest.ogg", 3, 660),
            ("tts/fixture.wav", 1, 880),
        ]:
            path = ROOT / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.suffix == ".wav":
                tone(path, seconds, hz)
            else:
                intermediate = Path(temp) / "tone.wav"
                tone(intermediate, seconds, hz)
                codec = ["-c:a", "libmp3lame", "-b:a", "16k"] if path.suffix == ".mp3" else ["-c:a", "libvorbis", "-q:a", "0"]
                subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                                "-i", str(intermediate), "-map_metadata", "-1",
                                *codec, str(path)], check=True)
            assert path.stat().st_size < 50000, relative
    (ROOT / "ambient/grass/broken.mp3").write_bytes(b"deliberately invalid audio\n")
