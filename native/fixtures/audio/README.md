# Audio fixture world (Task 58 / E8-T1)

Synthetic input for the Task 59 native `--check audio` consumer. All sound is
generated sine tones; the TTS URL also carries a tone, with no recorded speech,
names or copyrighted audio. No C# consumer or new check section is added here.

Ruling: use a separate `audio/` fixture world, keeping existing fixtures intact.
Load it with `FixtureSource(audioDir, parentFixturesDir)` for fallback data.
The local heightfield is flat. Local `locations.json`, `worldmap.json`,
`terrain.json` and `model3d.json` provide two synthetic terrain footprints and
one placeholder avatar. No scene/model downloads are required.
Both worldmap rows and location details carry terrain: the native
`FootprintAt(...).Loc.Terrain` lookup reads the worldmap row directly.

`audio_manifest.json` is the `GET /assets/audio` response, using the exact
shape and sorted filename/terrain order of `app/routes/game_audio.py:86–109`.
`urls.json` maps that endpoint and every listed URL to a local file, plus
`/tts/tmp/fixture.wav` for the `speak` action. `Forest` deliberately differs
in case from the location's `forest` terrain. The server lists `broken.mp3`
because it has an allowed extension; its bytes deliberately cannot decode.
This is a decode failure, not a missing URL. For a 404 probe, use an unmapped
URL such as `/assets/audio/music/day/missing.mp3`.

Run the vector and fixture checks from the repository root:

```sh
node client3d/scripts/smoke_audio_math.mjs
```

To regenerate the audio files, install Python 3 and ffmpeg with libmp3lame and
libvorbis, then run `python3 native/fixtures/audio/generate.py`. The generator
uses only synthetic mono PCM16 at 8000 Hz, amplitude at most 2000/32768,
with 10-ms attack/release. MP3 uses 16 kbit/s; Ogg uses Vorbis quality 0.
Ogg container serials/encoder versions may change file bytes on regeneration.
Every generated file must remain strictly below 50000 bytes.

| File (relative to this directory) | Tone Hz | PCM samples | Decoded seconds | Bytes |
|---|---:|---:|---:|---:|
| `music/day/day-a.mp3` | 220 | 72000 | 9 | 18549 |
| `music/day/day-b.ogg` | 330 | 96000 | 12 | 9608 |
| `music/night/night.wav` | 110 | 16000 | 2 | 32044 |
| `ambient/grass/grass-a.mp3` | 440 | 12000 | 1.5 | 3573 |
| `ambient/grass/grass-b.wav` | 550 | 24000 | 3 | 48044 |
| `ambient/Forest/forest.ogg` | 660 | 24000 | 3 | 4415 |
| `tts/fixture.wav` | 880 | 8000 | 1 | 16044 |
| `ambient/grass/broken.mp3` | — | — | invalid | 27 |

Durations are hand-derived as samples/8000. WAV is 44 header bytes plus
2 bytes/sample: 16000 samples → 32044 bytes, 24000 → 48044, 8000 → 16044.
The MP3 container durations reported by ffprobe are 9.144 and 1.656 seconds
(encoder delay/padding); decoded PCM is exactly 9 and 1.5 seconds.
Godot 4.7.2 runtime `LoadFromBuffer`/`GetLength()` was checked headless and
returns 9, 12, 2, 1.5, 3, 3 and 1 seconds respectively. Schedule against the
decoded stream length. Codec frame tolerance for subsequent runtime checks:
MP3 MPEG-2.5 layer III 576/8000 = .072 seconds; these Vorbis files advertise
512-sample blocks (identification-header exponents 9/9), so one block is
512/8000 = .064 seconds (the measured Ogg lengths are exact);
PCM WAV one sample = .000125 seconds. Prefer the exact expected lengths when
the runtime returns them; a tolerance is not an alternate scheduling input.

Hand scheduling numbers (seconds, initial `begin=10`, fake clock `now=10`):

| Track | Crossfade | Fade = min(crossfade, length/3) | Seam = begin+length−fade | Wake delay = max(0,seam−6−now) |
|---|---:|---:|---:|---:|
| day MP3, 9 s | 4 | 3 | 16 | 0 |
| day Ogg, 12 s | 4 | 4 | 18 | 2 |
| night WAV, 2 s | 4 | 2/3 | 11 1/3 | 0 |
| grass MP3, 1.5 s | 3 | .5 | 11 | 0 |
| grass WAV or Forest Ogg, 3 s | 3 | 1 | 12 | 0 |

For the day MP3, eight fade-in steps occupy 3/8=.375 seconds each. At
10.1875, halfway along the first step, gain=.09754516100806413; at 11.5,
gain=.7071067811865476. The outgoing fade starts at seam 16 and has gain
.7071067811865476 at 17.5. At a music switch at t=20, a current gain .8
stops linearly over 4 seconds: .8 at 20, .4 at 22, 0 at 24. A volume slider
change .8→.2 at t=2 gives .5 at 2.025 and .2 at 2.05.

The two world footprints are 10×10 squares: grass centered at (0,0), forest
at (20,0), both yaw 0 on y=0. Grass bounds are x/z −5..5; forest x=15..25,
z=−5..5. Camera target (0,0) therefore selects grass in overview; the avatar
at (20,0) selects forest when embodied. First grass at t=1000 ms applies
immediately; forest at 2000 starts pending, stays grass at 6999, and applies
at 7000. Moving off both footprints selects silence with the same 5000-ms
hold. The music driver can probe 12:00/day and 22:00/night; the hysteresis
itself is pinned in `audio.json` at strict thresholds .2/.8.

Speech follows P3-R30: cap three WAITING lines and discard the oldest on
overflow; an already sounding line is separate. Browser provenance is
`client3d/src/game/voiceover.ts:214–224`. Stopping speech must leave both
playlists alone. Those lifecycle checks belong to Task 59.
